"""FastAPI surface for the scheduler (spec §3, §4.3, §9.2).

Serves the frontend: read a package, save checkpoint edits (re-validated), approve
(hand off to execution), recover failed nodes in place (edit + retry), and stream
live node status over SSE. The DAG-walker daemon is started as a background asyncio
task on app startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from datetime import datetime

from auth import auth_router, current_user_id, install_auth, owned_package
from auth.config import AUTH_ALLOWED_ORIGINS
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from schema import (
    PROMPT_MAX_BYTES,
    Asset,
    AssetType,
    NodeStatus,
    ProductionPackage,
    film_id_of,
    version_of,
)
from sse_starlette.sse import EventSourceResponse
from validator import content_errors, validate_package

from scheduler import reuse
from scheduler.daemon import run_daemon
from scheduler.dag import FAILED_STATUSES, Dag
from scheduler.state import (
    PHASE_BLOCKED,
    PHASE_COMPLETE,
    PHASE_COMPOSITING,
    PHASE_EXECUTING,
    PHASE_PAUSED,
    EditConflict,
    approve_and_seed,
    get_cost,
    get_final_url,
    get_node,
    get_package,
    get_package_raw,
    get_project_owner,
    get_project_phase,
    is_package_approved,
    iter_user_packages,
    reset_node,
    save_package,
    update_asset_content,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = FastAPI(title="AI Film Pipeline — Scheduler Service", version="1.0.0")

# The SSE stream closes only once the final cut exists. ``blocked`` and ``paused``
# runs are recovered from the same Status page, so their stream stays open.
_TERMINAL_PHASES = {PHASE_COMPLETE}

_RECOVERABLE_PHASES = {PHASE_EXECUTING, PHASE_BLOCKED}

# Auth: mount the shared /auth router and enforce session + CSRF on everything except
# the public allow-list. Middleware is added auth-first then CORS-last so CORS ends up
# outermost — it annotates even auth-denied responses in the direct-origin dev case
# (behind the reverse proxy the browser is same-origin, so CORS mostly stops applying).
app.include_router(auth_router)
install_auth(app, public_paths={"/health", "/auth/login", "/auth/register", "/auth/csrf"})
# Credentialed CORS: an explicit origin allow-list (never "*" with credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=AUTH_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_stop = asyncio.Event()
_daemon_task: asyncio.Task | None = None


@app.on_event("startup")
async def _start_daemon() -> None:
    global _daemon_task
    _stop.clear()
    _daemon_task = asyncio.create_task(run_daemon(_stop))


@app.on_event("shutdown")
async def _stop_daemon() -> None:
    _stop.set()
    if _daemon_task:
        with contextlib.suppress(asyncio.CancelledError):
            await _daemon_task


class PackageSummary(BaseModel):
    """A compact package row for the History list (spec §9.2) — enough to render the
    table and link into a run without shipping the whole DAG. ``phase`` and
    ``cost_usd`` are overlaid from live run state, the rest from the package spec."""

    project_id: str
    title: str
    created_at: datetime
    phase: str | None
    cost_usd: float
    film_id: str
    version: int
    parent_project_id: str | None


class ApproveRequest(BaseModel):
    rerender: list[str] = []  # reused nodes to render afresh anyway


class ApproveResult(BaseModel):
    status: str
    reused: int


class ReusedNode(BaseModel):
    source_project_id: str
    source_node_id: str
    source_version: int


class ReusePlan(BaseModel):
    """Which nodes reuse an earlier version's render. ``final`` once approved, when it is
    read from the seeded node hashes rather than predicted."""

    final: bool
    nodes: dict[str, ReusedNode]  # a node absent from this map renders
    render_cost_usd: float
    full_cost_usd: float


class VersionSummary(BaseModel):
    project_id: str
    version: int
    title: str
    created_at: datetime
    approved: bool
    phase: str | None
    cost_usd: float
    parent_project_id: str | None
    note: str
    from_stage: str | None
    changes: list[str]
    has_final_cut: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/packages", status_code=201)
async def create_package(
    package: ProductionPackage, user_id: str = Depends(current_user_id)
) -> dict[str, str]:
    """Ingest a full production package — the execution entry point.

    The package is already authored/validated upstream (the sequential driver, the
    ``harness submit`` test entry, or the planning tier handing off the
    same way), so this does not re-run the validator; checkpoint edits via ``PUT``
    do. Persisting it stamps the caller as owner and makes it visible to the daemon
    once ``/approve`` adds it to the approved set.

    An import starts its own film: lineage is server-owned, and dropping it keeps
    re-submitted packages (harness ``submit``/``bench``) out of any reuse.
    """
    package.lineage = None
    await save_package(package, owner_id=user_id)
    return {"project_id": package.project_id}


@app.get("/packages", response_model=list[PackageSummary])
async def list_packages(user_id: str = Depends(current_user_id)) -> list[PackageSummary]:
    """List the caller's persisted packages for the History screen (spec §9.2),
    newest first — per-user isolation, so a user only ever sees their own runs.

    Scoped by owner via ``iter_user_packages`` (durable ``packages.owner_id`` when
    Postgres is on, else the Redis owner index); phase and cost-to-date are overlaid
    from live run state."""
    summaries = [
        PackageSummary(
            project_id=pkg.project_id,
            title=pkg.meta.title,
            created_at=pkg.created_at,
            phase=await get_project_phase(pkg.project_id),
            cost_usd=await get_cost(pkg.project_id),
            film_id=film_id_of(pkg),
            version=version_of(pkg),
            parent_project_id=pkg.lineage.parent_project_id if pkg.lineage else None,
        )
        async for pkg in iter_user_packages(user_id)
    ]
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


@app.get(
    "/packages/{project_id}",
    response_model=ProductionPackage,
    dependencies=[Depends(owned_package)],
)
async def read_package(project_id: str) -> ProductionPackage:
    # ``owned_package`` already 404s if the caller doesn't own project_id (no
    # existence leak), so a hit here means the package is both present and owned.
    package = await get_package(project_id)
    if not package:
        raise HTTPException(404, "package not found")
    return package


@app.put(
    "/packages/{project_id}",
    response_model=ProductionPackage,
    dependencies=[Depends(owned_package)],
)
async def update_package(project_id: str, package: ProductionPackage) -> ProductionPackage:
    """Save a checkpoint edit. Re-runs the validator server-side (spec §4.3).

    ``owner_id`` is omitted so the existing owner is preserved (the store/Postgres
    COALESCE ownership across edits) — an edit can never reassign a package.

    Once the package is approved the run has started (or is about to — the daemon
    picks up the approved set within ~1s), so edits are locked out with a 409 rather
    than mutating a spec already in flight. ``is_package_approved`` (approved-set
    membership) is the race-free lock condition; ``phase`` is ``None`` for the first
    tick after approval. After approval, failed shots are fixed one node at a time via
    ``PATCH /packages/{id}/nodes/{node_id}`` and ``POST /packages/{id}/retry``."""
    if await is_package_approved(project_id):
        raise HTTPException(409, "Package is approved and locked; edits are no longer accepted.")
    # A mismatched body would persist under a different Redis key than the one
    # ``owned_package`` authorized — reject it rather than write cross-project.
    if package.project_id != project_id:
        raise HTTPException(422, "project_id in body must match URL")
    stored = await get_package(project_id)
    package.lineage = stored.lineage if stored else None
    report = validate_package(package)
    if not report.ok:
        raise HTTPException(422, detail=report.errors)
    await save_package(package)
    return package


@app.post(
    "/packages/{project_id}/approve",
    response_model=ApproveResult,
    dependencies=[Depends(owned_package)],
)
async def approve(project_id: str, body: ApproveRequest | None = None) -> ApproveResult:
    """Lock the package and hand it to the daemon. In the same transaction, nodes whose
    render already exists in another version of the film are seeded as succeeded, and
    ``rerender`` nodes get a fresh take so they render regardless."""
    # Approving is the point of no return for edits, so a second approve is a
    # conflict (409), not a silent idempotent no-op — the caller's UI must learn the
    # run is already locked.
    if await is_package_approved(project_id):
        raise HTTPException(409, "Package is already approved.")
    raw = await get_package_raw(project_id)
    if raw is None:
        raise HTTPException(404, "package not found")
    package = ProductionPackage.model_validate_json(raw)
    report = validate_package(package)
    if not report.ok:
        raise HTTPException(422, detail=report.errors)
    rerender = body.rerender if body is not None else []
    unknown = [n for n in rerender if package.asset_by_id(n) is None]
    if unknown:
        raise HTTPException(422, f"unknown node(s): {', '.join(unknown)}")
    owner = await get_project_owner(project_id)
    try:
        seeds = await approve_and_seed(
            project_id, expected_raw=raw, rerender=rerender, seed=reuse.seeder(owner)
        )
    except EditConflict:
        raise HTTPException(409, "The package changed while approving; review it and approve again.")
    except KeyError:
        raise HTTPException(404, "package not found")
    return ApproveResult(status="approved", reused=len(seeds))


@app.get(
    "/packages/{project_id}/reuse",
    response_model=ReusePlan,
    dependencies=[Depends(owned_package)],
)
async def reuse_plan(project_id: str) -> ReusePlan:
    package = await get_package(project_id)
    if package is None:
        raise HTTPException(404, "package not found")
    nodes: dict[str, ReusedNode] = {}
    final = await is_package_approved(project_id)
    if final:
        versions: dict[str, int] = {}
        for asset in package.assets:
            reused_from = (await get_node(project_id, asset.node_id)).get("reused_from")
            if not reused_from:
                continue
            source_pid, _, source_nid = reused_from.partition("/")
            if source_pid not in versions:
                source = await get_package(source_pid)
                versions[source_pid] = version_of(source) if source else 0
            nodes[asset.node_id] = ReusedNode(
                source_project_id=source_pid,
                source_node_id=source_nid,
                source_version=versions[source_pid],
            )
    else:
        owner = await get_project_owner(project_id)
        matched = reuse.match(package, await reuse.reuse_sources(package, owner))
        nodes = {
            node_id: ReusedNode(
                source_project_id=src.project_id,
                source_node_id=src.node_id,
                source_version=src.version,
            )
            for node_id, src in matched.items()
        }
    full = sum(a.estimated_cost_usd for a in package.assets)
    render = sum(a.estimated_cost_usd for a in package.assets if a.node_id not in nodes)
    return ReusePlan(
        final=final,
        nodes=nodes,
        render_cost_usd=round(render, 2),
        full_cost_usd=round(full, 2),
    )


async def _version_summary(pkg: ProductionPackage) -> VersionSummary:
    lineage = pkg.lineage
    return VersionSummary(
        project_id=pkg.project_id,
        version=version_of(pkg),
        title=pkg.meta.title,
        created_at=pkg.created_at,
        approved=await is_package_approved(pkg.project_id),
        phase=await get_project_phase(pkg.project_id),
        cost_usd=await get_cost(pkg.project_id),
        parent_project_id=lineage.parent_project_id if lineage else None,
        note=lineage.note if lineage else "",
        from_stage=lineage.from_stage if lineage else None,
        changes=list(lineage.changes) if lineage else [],
        has_final_cut=bool(await get_final_url(pkg.project_id)),
    )


@app.get(
    "/packages/{project_id}/versions",
    response_model=list[VersionSummary],
    dependencies=[Depends(owned_package)],
)
async def list_versions(project_id: str) -> list[VersionSummary]:
    """Every version of this package's film, oldest first."""
    package = await get_package(project_id)
    if package is None:
        raise HTTPException(404, "package not found")
    film_id = film_id_of(package)
    owner = await get_project_owner(project_id)
    if owner is None:
        members = [package]
    else:
        members = [p async for p in iter_user_packages(owner) if film_id_of(p) == film_id]
    summaries = [await _version_summary(p) for p in members]
    summaries.sort(key=lambda s: (s.version, s.created_at))
    return summaries


_media_client = None


def _media():  # type: ignore[no-untyped-def]
    """The object-storage client for signing playback URLs, built on first use so the
    scheduler starts (and its tests run) without S3 configured."""
    global _media_client
    if _media_client is None:
        from storage import Storage

        _media_client = Storage()
    return _media_client


def _download_name(package: ProductionPackage) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", package.meta.title.lower()).strip("-") or "film"
    return f"{slug}-v{version_of(package)}.mp4"


@app.get("/packages/{project_id}/final", dependencies=[Depends(owned_package)])
async def final_cut(project_id: str, download: int = 0) -> RedirectResponse:
    """Redirect to a short-lived presigned URL of the final cut. The browser requests
    this same-origin, so the session cookie authorizes it before it leaves for S3."""
    final_url = await get_final_url(project_id)
    if not final_url:
        raise HTTPException(404, "This version has no final cut yet.")
    name = None
    if download:
        package = await get_package(project_id)
        name = _download_name(package) if package else "film.mp4"
    return RedirectResponse(_media().presigned_get_url(final_url, download_name=name), status_code=307)


class PackageStatus(BaseModel):
    """Editability of a package for the Checkpoint screen. Kept off the shared
    ``ProductionPackage`` schema so the seam contract stays clean — the UI reads this
    to decide whether to lock the form. ``approved`` is the authoritative lock flag;
    ``phase`` is advisory (``None`` for the ~1s before the daemon starts the run)."""

    project_id: str
    approved: bool
    phase: str | None


class NodeEdit(BaseModel):
    """An in-place fix to one node of an approved run."""

    prompt: str | None = None  # image / video
    text: str | None = None  # voiceover
    voice_id: str | None = None  # voiceover (spec.voice_id)


class RetryRequest(BaseModel):
    node_ids: list[str] | None = None  # default: every failed / dead-lettered node


class ProviderLimits(BaseModel):
    prompt_max_bytes: dict[str, int]


@app.get(
    "/packages/{project_id}/status",
    response_model=PackageStatus,
    dependencies=[Depends(owned_package)],
)
async def package_status(project_id: str) -> PackageStatus:
    return PackageStatus(
        project_id=project_id,
        approved=await is_package_approved(project_id),
        phase=await get_project_phase(project_id),
    )


@app.get("/limits", response_model=ProviderLimits)
async def limits() -> ProviderLimits:
    return ProviderLimits(prompt_max_bytes=dict(PROMPT_MAX_BYTES))


async def _require_recoverable_run(project_id: str) -> ProductionPackage:
    if not await is_package_approved(project_id):
        raise HTTPException(409, "This run isn't approved yet; edit it at the checkpoint.")
    phase = await get_project_phase(project_id)
    if phase == PHASE_PAUSED:
        raise HTTPException(
            409, "This run is paused at its budget limit; raising the budget isn't supported yet."
        )
    if phase in (PHASE_COMPOSITING, PHASE_COMPLETE):
        raise HTTPException(409, "This run has finished rendering; its shots can't be changed.")
    if phase not in _RECOVERABLE_PHASES:
        raise HTTPException(409, "This run is still starting; try again in a moment.")
    package = await get_package(project_id)
    if package is None:
        raise HTTPException(404, "package not found")
    return package


def _edit_changes(asset: Asset, edit: NodeEdit) -> dict[str, str]:
    """The fields ``edit`` sets, checked against the node type (422 on a mismatch)."""
    if asset.type is AssetType.VOICEOVER:
        allowed, wrong = {"text", "voice_id"}, "prompt"
    else:
        allowed, wrong = {"prompt"}, "text or voice_id"
    changes = edit.model_dump(exclude_none=True)
    if set(changes) - allowed:
        raise HTTPException(422, f"{asset.type.value} nodes don't take {wrong}.")
    if not changes:
        raise HTTPException(422, "Nothing to change.")
    blank = [name for name, value in changes.items() if not value.strip()]
    if blank:
        raise HTTPException(422, f"{', '.join(blank)} can't be blank.")
    return changes


@app.patch(
    "/packages/{project_id}/nodes/{node_id}",
    response_model=Asset,
    dependencies=[Depends(owned_package)],
)
async def edit_node(project_id: str, node_id: str, edit: NodeEdit) -> Asset:
    """Fix one failed (or still-waiting) node of an approved run in place. Nodes that
    already rendered or are rendering are never touched; the edit only saves, and
    ``/retry`` re-renders."""
    package = await _require_recoverable_run(project_id)
    asset = package.asset_by_id(node_id)
    if asset is None:
        raise HTTPException(404, "node not found")
    changes = _edit_changes(asset, edit)
    if not Dag(package).is_editable(node_id):
        raise HTTPException(409, f"{node_id} has already rendered or is rendering.")

    candidate = asset.model_copy(deep=True)
    candidate.prompt = changes.get("prompt", candidate.prompt)
    candidate.text = changes.get("text", candidate.text)
    errors = content_errors(candidate)
    if errors:
        raise HTTPException(422, detail=errors)

    failed = asset.status in FAILED_STATUSES
    allowed = FAILED_STATUSES if failed else {NodeStatus.PENDING}
    try:
        await update_asset_content(project_id, node_id, allowed_statuses=set(allowed), **changes)
    except EditConflict:
        raise HTTPException(409, f"{node_id} just started rendering; it can no longer be edited.")
    refreshed = await get_package(project_id)
    return refreshed.asset_by_id(node_id)


@app.post(
    "/packages/{project_id}/retry",
    response_model=PackageStatus,
    dependencies=[Depends(owned_package)],
)
async def retry(project_id: str, body: RetryRequest | None = None) -> PackageStatus:
    """Re-render failed nodes; everything that succeeded is kept. The daemon resumes
    a blocked run by itself on its next tick."""
    package = await _require_recoverable_run(project_id)
    failed = [a.node_id for a in package.assets if a.status in FAILED_STATUSES]
    targets = body.node_ids if body is not None and body.node_ids is not None else failed
    unknown = [n for n in targets if package.asset_by_id(n) is None]
    if unknown:
        raise HTTPException(404, f"unknown node(s): {', '.join(unknown)}")
    not_failed = [n for n in targets if n not in failed]
    if not_failed:
        raise HTTPException(409, f"only failed nodes can be retried: {', '.join(not_failed)}")
    if not targets:
        raise HTTPException(409, "Nothing to retry.")
    errors = [e for n in targets for e in content_errors(package.asset_by_id(n))]
    if errors:
        raise HTTPException(422, detail=errors)
    for node_id in targets:
        await reset_node(project_id, node_id)
    return await package_status(project_id)


async def _status_event(project_id: str) -> dict | None:
    """Build one SSE status frame from live shared state — the run's observability
    surface (spec §9.2, §12.4): per-node status/attempts/error, project phase,
    cost-to-date, the content critical-path floor, and the final cut URL once it
    exists. Returns ``None`` while the package is unknown (not yet ingested)."""
    package = await get_package(project_id)
    if not package:
        return None
    dag = Dag(package)
    blocked = dag.blocked_by()
    nodes: dict[str, dict] = {}
    for asset in package.assets:
        live = await get_node(project_id, asset.node_id)
        nodes[asset.node_id] = {
            "status": asset.status.value,
            "attempts": int(live.get("attempts", 0)),
            "error": live.get("error"),
            "error_code": live.get("error_code"),
            "error_detail": live.get("error_detail"),
            "blocked_by": blocked.get(asset.node_id, []),
            "reused_from": live.get("reused_from"),
        }
    phase = await get_project_phase(project_id)
    return {
        "project_id": project_id,
        "phase": phase,
        "cost_usd": await get_cost(project_id),
        "nodes": nodes,
        # The *content* critical path (spec.duration_s along the longest chain),
        # not the latency-weighted render-time floor (Graph B) the benchmark computes.
        "critical_path_s": dag.critical_path_estimate(),
        "final_url": await get_final_url(project_id),
        "complete": phase == PHASE_COMPLETE,
    }


@app.get("/packages/{project_id}/events", dependencies=[Depends(owned_package)])
async def events(project_id: str) -> EventSourceResponse:
    """SSE stream of live run state for the Status screen (spec §9.2).

    Streams through ``executing``, ``blocked``, ``paused`` and ``compositing`` and only
    closes once the run is complete — crucially *after* the compositor sets
    ``final_url``, so the last frame carries the final cut."""

    async def gen():
        while True:
            payload = await _status_event(project_id)
            if payload is not None:
                yield {"event": "status", "data": json.dumps(payload)}
                if payload["phase"] in _TERMINAL_PHASES:
                    break
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())
