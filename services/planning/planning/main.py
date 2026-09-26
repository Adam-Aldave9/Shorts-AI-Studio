"""FastAPI surface for the planning tier (spec §4, §9.2 Submit screen).

Accepts a brief and runs the world -> script -> breakdown -> prompts -> validator
chain as an **async in-process background job**: ``POST /briefs`` returns a job id
immediately (202) and the work streams its progress to shared Redis state, which the
frontend follows over SSE (``GET /jobs/{id}/events``). This mirrors the execution
tier's daemon+SSE shape — a real (``MOCK=false``) chain is several sequential LLM
calls and takes tens of seconds to minutes, far too long to hold an HTTP request open.

On success the validated package is persisted into the shared store the scheduler
already serves — so its existing GET/PUT/approve endpoints see the package the instant
planning finishes (the package is the API; no bespoke planning->scheduler handoff). The
Pydantic-derived JSON schema is served so the frontend's Monaco editor can validate
edits at the checkpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from concurrent.futures import Future
from datetime import datetime, timezone
from uuid import uuid4

import state
from auth import auth_router, current_user_id, install_auth, owned_job, owned_package
from auth.config import AUTH_ALLOWED_ORIGINS
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from schema import (
    SCHEMA_VERSION,
    AssetType,
    ErrorCode,
    Lineage,
    ProductionPackage,
    film_id_of,
    prompt_max_bytes,
    strip_mock_failure,
    version_of,
)
from sse_starlette.sse import EventSourceResponse

from planning.agents import revise
from planning.graph import STAGE_SEQUENCE, _assemble_detail, run_planning, use_mock
from planning.models import Brief, PromptRevision, Story
from planning.prompt_budget import fit_to_bytes, normalize_punctuation
from planning.proposals import ProposalError, ProposalRequest, ProposalResponse, propose
from planning.revision import (
    RevisionPlan,
    RevisionPreview,
    RevisionRequest,
    plan_revision,
    preview,
    prompts_line,
    run_revision,
    skipped_stages,
)
from planning.story import (
    StoryResponse,
    narration_diverged,
    spoken_narration,
    story_from_package,
    story_hash,
    validate_story,
)
from planning.validator import ValidationReport, validate_package

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("planning")

app = FastAPI(title="AI Film Pipeline — Planning Service", version="1.0.0")

# Auth: same shared layer as the scheduler. ``/schema`` is public (non-sensitive
# static JSON schema for the Monaco editor); briefs require a session so the resulting
# package can be stamped with an owner. ``/jobs/{id}/events`` stays non-public too and
# rides the session cookie (EventSource ``withCredentials``); GET is CSRF-exempt.
# CORS is added last so it stays outermost.
app.include_router(auth_router)
install_auth(
    app,
    public_paths={"/health", "/schema", "/auth/login", "/auth/register", "/auth/csrf"},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=AUTH_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Terminal job statuses: the SSE stream emits a final frame and closes once reached.
_TERMINAL_STATUSES = {state.PLAN_SUCCEEDED, state.PLAN_FAILED}

# Keep strong references to in-flight background tasks so the event loop doesn't GC a
# fire-and-forget ``create_task`` mid-run (same spirit as the scheduler's ``_daemon_task``
# global). The done-callback prunes finished tasks.
_jobs: set[asyncio.Task] = set()


class PlanningJobAccepted(BaseModel):
    """The 202 response handed back to the Submit screen, which routes the browser to
    ``/planning/{job_id}`` to follow the job's SSE progress stream."""

    job_id: str


class SuggestRequest(BaseModel):
    prompt: str | None = None  # the user's current draft; defaults to the stored prompt


class PromptSuggestion(BaseModel):
    prompt: str
    notes: str
    error_code: ErrorCode | None
    max_bytes: int | None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mock": os.environ.get("MOCK", "false")}


@app.get("/schema")
def package_schema() -> dict:
    """JSON schema for the production package — consumed by Monaco at the checkpoint."""
    return ProductionPackage.model_json_schema()


def _next_stage(completed_node: str) -> str:
    """Map a just-completed chain node to the stage now in progress (its successor in
    :data:`STAGE_SEQUENCE`), so the reported ``stage`` reflects live work rather than
    the step that just finished. The terminal ``assemble`` node has no successor, so it
    reports itself while the package is assembled + validated."""
    try:
        idx = STAGE_SEQUENCE.index(completed_node)
    except ValueError:  # unknown node name — surface it verbatim rather than guessing
        return completed_node
    return STAGE_SEQUENCE[min(idx + 1, len(STAGE_SEQUENCE) - 1)]


async def _advance(job_id: str, stage: str) -> None:
    """Move the job to ``stage`` and log how long the outgoing one took — the only
    per-stage timing measurement in the repo, and what will eventually replace the
    frontend's guessed ``typicalS`` values with measured ones."""
    closed = await state.set_plan_stage(job_id, stage)
    if closed:
        log.info("planning job %s: stage %s finished in %.1fs", job_id, *closed)


async def run_planning_job(job_id: str, brief: dict, user_id: str) -> None:
    """Background runner: drive the planning chain, stream stage progress to Redis, and
    land the job on a terminal status.

    The real chain runs on a worker thread (``run_planning`` -> ``asyncio.to_thread``),
    so the callbacks marshal each Redis write back onto *this* loop via
    ``run_coroutine_threadsafe`` — which reuses the per-loop Redis client correctly even
    though the callback fires from the worker thread, and is equally safe from the loop's
    own thread (the mock path) as long as the callback itself never awaits them. The whole
    body is guarded so any failure (chain exception or validation) lands as a ``failed``
    frame the UI renders.
    """
    loop = asyncio.get_running_loop()
    progress: set[Future] = set()

    def spawn(coro) -> None:
        # Fire-and-forget: progress writes must never block or crash the chain thread.
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        progress.add(future)
        future.add_done_callback(progress.discard)

    def on_stage(completed_node: str) -> None:
        spawn(_advance(job_id, _next_stage(completed_node)))

    def on_detail(stage: str, detail: dict) -> None:
        spawn(state.set_plan_detail(job_id, stage, detail))

    async def drain() -> None:
        """Let queued progress writes land before the terminal frame. Without this a
        still-pending ``_advance`` could flip ``status`` back to ``running`` *after* the
        job succeeded — reachable on the mock path, where the callbacks are scheduled
        from the loop's own thread and so only run once it next yields."""
        pending = [asyncio.wrap_future(f) for f in list(progress)]
        if pending:
            await asyncio.wait(pending)

    try:
        await _advance(job_id, STAGE_SEQUENCE[0])
        package = await run_planning(brief, on_stage, on_detail)
        await drain()
        report: ValidationReport = validate_package(package)
        if not report.ok:
            # Preserves today's 422-detail semantics (the validator error list), now
            # delivered via the failed frame instead of an HTTP error body.
            await state.set_plan_failed(job_id, report.errors)
            return
        package.lineage = Lineage(film_id=package.project_id, version=1)
        package.schema_version = SCHEMA_VERSION
        # Persist into the store the scheduler serves, stamping the authenticated caller
        # as owner — this is the brief->package handoff where identity enters the run, so
        # the scheduler's ownership checks (and scoped History) apply from creation.
        await state.save_package(package, owner_id=user_id)
        await state.set_plan_succeeded(job_id, package.project_id)
    except Exception as exc:  # noqa: BLE001 - any failure must land as a failed frame
        log.exception("planning job %s failed", job_id)
        await drain()
        await state.set_plan_failed(job_id, [str(exc)])


@app.post("/briefs", status_code=202, response_model=PlanningJobAccepted)
async def create_brief(
    brief: Brief, user_id: str = Depends(current_user_id)
) -> PlanningJobAccepted:
    """Accept a brief and kick off async planning. Returns a job id the client follows
    over SSE; the work runs in-process and persists the package on success."""
    job_id = f"j_{uuid4().hex[:8]}"
    await state.create_plan_job(job_id, owner_id=user_id)
    task = asyncio.create_task(run_planning_job(job_id, brief.model_dump(), user_id))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return PlanningJobAccepted(job_id=job_id)


@app.get("/jobs/{job_id}/events", dependencies=[Depends(owned_job)])
async def job_events(job_id: str) -> EventSourceResponse:
    """SSE stream of a planning job's progress for the Planning screen.

    Polls the Redis job state each second, yields a ``status`` frame, and closes once
    the job reaches a terminal status. If the hash vanishes mid-stream (TTL expiry after
    a process restart orphaned the job), emit one ``failed`` frame and close so the
    client isn't left hanging."""

    async def gen():
        while True:
            frame = await state.get_plan_job(job_id)
            if frame is None:
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "job_id": job_id,
                            "kind": "brief",
                            "mode": None,
                            "skipped": [],
                            "status": state.PLAN_FAILED,
                            "stage": None,
                            "stage_index": -1,
                            "stage_count": len(STAGE_SEQUENCE),
                            "elapsed_s": 0.0,
                            "stage_elapsed_s": 0.0,
                            "stage_timings": {},
                            "details": {},
                            "project_id": None,
                            "errors": ["job expired or no longer exists"],
                        }
                    ),
                }
                break
            yield {"event": "status", "data": json.dumps(frame)}
            if frame["status"] in _TERMINAL_STATUSES:
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())


# --------------------------------------------------------------------------
# Revisions: go back to a planning stage of a version and build an updated one
# --------------------------------------------------------------------------
# Version numbers are allocated under a per-film lock. The planning service runs as a single
# uvicorn process; with several, this would need a Redis counter instead.
_film_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _load_spec(project_id: str) -> ProductionPackage:
    """The raw, un-hydrated spec: live status must never leak into a new package."""
    raw = await state.get_package_raw(project_id)
    spec = ProductionPackage.model_validate_json(raw) if raw else await state.get_package(project_id)
    if spec is None:
        raise HTTPException(404, "package not found")
    return spec


async def _mode(project_id: str) -> str:
    return "new_version" if await state.is_package_approved(project_id) else "in_place"


async def _next_version(film_id: str, owner_id: str | None) -> int:
    highest = 0
    if owner_id:
        async for pkg in state.iter_user_packages(owner_id):
            if film_id_of(pkg) == film_id:
                highest = max(highest, version_of(pkg))
    return highest + 1


@app.get(
    "/packages/{project_id}/story",
    response_model=StoryResponse,
    dependencies=[Depends(owned_package)],
)
async def get_story(project_id: str) -> StoryResponse:
    """Every editable planning stage of this version, pre-filled with its real content."""
    spec = await _load_spec(project_id)
    story = story_from_package(spec)
    return StoryResponse(
        project_id=project_id,
        film_id=film_id_of(spec),
        version=version_of(spec),
        mode=await _mode(project_id),
        base_hash=story_hash(story),
        story=story,
        prompts={a.node_id: a.prompt or "" for a in spec.assets if a.type is AssetType.VIDEO},
        spoken_narration=spoken_narration(spec),
        narration_diverged=narration_diverged(spec, story),
    )


@app.post(
    "/packages/{project_id}/story/preview",
    response_model=RevisionPreview,
    dependencies=[Depends(owned_package)],
)
async def preview_revision(project_id: str, body: RevisionRequest) -> RevisionPreview:
    """What a revision with this story would change and regenerate. Pure and fast: no LLM,
    and ``base_hash`` isn't checked."""
    spec = await _load_spec(project_id)
    hydrated = await state.get_package(project_id) or spec
    mode = await _mode(project_id)
    next_version = None
    if mode == "new_version":
        next_version = await _next_version(film_id_of(spec), await state.get_project_owner(project_id))
    return preview(
        hydrated,
        story_from_package(spec),
        body.story,
        body.keep_shots,
        mode=mode,
        next_version=next_version,
        errors=validate_story(body.story),
    )


@app.post(
    "/packages/{project_id}/story/propose",
    response_model=ProposalResponse,
    dependencies=[Depends(owned_package)],
)
async def propose_story(project_id: str, body: ProposalRequest) -> ProposalResponse:
    """Propose an AI rewrite of one stage (or selected items). Never writes: the studio shows
    it for review, and the user accepts or discards it."""
    spec = await _load_spec(project_id)
    try:
        return await asyncio.to_thread(propose, story_from_package(spec), body, mock=use_mock())
    except ProposalError as exc:
        raise HTTPException(422, str(exc))
    except Exception:  # noqa: BLE001 - any LLM failure is a bad gateway to the UI
        log.exception("story proposal failed for %s (%s)", project_id, body.stage)
        raise HTTPException(502, "The AI rewrite failed; try again or edit by hand.")


def _skipped_details(story: Story, plan: RevisionPlan, skipped: list[str]) -> dict[str, dict]:
    world_edited = bool(plan.entity_status)
    details = {
        "world": {
            "characters": [c.name for c in story.world.characters],
            "locations": [l.name for l in story.world.locations],
            "edited": world_edited,
        },
        "script": {
            "title": story.script.title,
            "logline": story.script.logline,
            "scenes": len(story.script.scenes),
            "edited": plan.script_edited,
        },
        "breakdown": {"shots": len(story.shots), "edited": plan.shots_hand_edited},
    }
    return {stage: details[stage] for stage in skipped if stage in details}


async def persist_revision(
    parent: ProductionPackage,
    package: ProductionPackage,
    request: RevisionRequest,
    plan: RevisionPlan,
    rewritten_prompts: int,
    user_id: str,
) -> ProductionPackage:
    """An unapproved draft is updated in place; an approved version (or a draft approved
    while the job ran) gets a new version with its own project id."""
    film_id = film_id_of(parent)
    changes = list(plan.changes)
    if rewritten_prompts:
        changes.append(prompts_line(rewritten_prompts))
    note = request.note.strip()
    async with _film_locks[film_id]:
        if not await state.is_package_approved(parent.project_id):
            lineage = (parent.lineage or Lineage(film_id=film_id)).model_copy(deep=True)
            lineage.changes += [c for c in changes if c not in lineage.changes]
            if note:
                lineage.note = note
            draft = package.model_copy(
                update={"project_id": parent.project_id, "created_at": parent.created_at, "lineage": lineage}
            )
            if await state.replace_package_if_unapproved(draft):
                return draft
        package.project_id = f"p_{uuid4().hex[:6]}"
        package.created_at = datetime.now(timezone.utc)
        package.lineage = Lineage(
            film_id=film_id,
            version=await _next_version(film_id, user_id),
            parent_project_id=parent.project_id,
            note=note,
            from_stage=plan.from_stage,
            changes=changes,
        )
        await state.save_package(package, owner_id=user_id)
        return package


async def run_revision_job(
    job_id: str,
    parent: ProductionPackage,
    request: RevisionRequest,
    plan: RevisionPlan,
    skipped: list[str],
    user_id: str,
) -> None:
    """Background runner for a revision, mirroring ``run_planning_job``: progress writes are
    marshalled onto this loop, and any failure lands as a ``failed`` frame."""
    loop = asyncio.get_running_loop()
    progress: set[Future] = set()

    def spawn(coro) -> None:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        progress.add(future)
        future.add_done_callback(progress.discard)

    def on_stage(completed_node: str) -> None:
        spawn(_advance(job_id, _next_stage(completed_node)))

    def on_detail(stage: str, detail: dict) -> None:
        spawn(state.set_plan_detail(job_id, stage, detail))

    async def drain() -> None:
        pending = [asyncio.wrap_future(f) for f in list(progress)]
        if pending:
            await asyncio.wait(pending)

    try:
        await _advance(job_id, next(s for s in STAGE_SEQUENCE if s not in skipped))
        result = await run_revision(
            parent, story_from_package(parent), request.story, plan, on_stage, on_detail,
            mock=use_mock(),
        )
        await drain()
        await state.set_plan_detail(job_id, "assemble", _assemble_detail(result.package))
        report: ValidationReport = validate_package(result.package)
        if not report.ok:
            await state.set_plan_failed(job_id, report.errors)
            return
        package = await persist_revision(
            parent, result.package, request, plan, result.rewritten_prompts, user_id
        )
        await state.set_plan_succeeded(job_id, package.project_id)
    except Exception as exc:  # noqa: BLE001 - any failure must land as a failed frame
        log.exception("revision job %s failed", job_id)
        await drain()
        await state.set_plan_failed(job_id, [str(exc)])


@app.post(
    "/packages/{project_id}/revisions",
    status_code=202,
    response_model=PlanningJobAccepted,
    dependencies=[Depends(owned_package)],
)
async def create_revision(
    project_id: str, body: RevisionRequest, user_id: str = Depends(current_user_id)
) -> PlanningJobAccepted:
    """Start a background job that turns this version plus the edited story into a new
    version (or, for an unapproved draft, an updated draft). Only what the edits affect is
    regenerated; everything else is carried over verbatim."""
    parent = await _load_spec(project_id)
    parent_story = story_from_package(parent)
    if body.base_hash != story_hash(parent_story):
        raise HTTPException(
            409, "This version changed since you opened the editor. Reload to continue."
        )
    errors = validate_story(body.story)
    if errors:
        raise HTTPException(422, detail=errors)
    plan = plan_revision(parent, parent_story, body.story, body.keep_shots)
    mode = await _mode(project_id)
    if mode == "in_place" and not plan.has_changes:
        raise HTTPException(422, "Nothing to change.")

    job_id = f"j_{uuid4().hex[:8]}"
    skipped = skipped_stages(plan)
    await state.create_plan_job(job_id, owner_id=user_id, kind="revision", mode=mode, skipped=skipped)
    for stage, detail in _skipped_details(body.story, plan, skipped).items():
        await state.set_plan_detail(job_id, stage, detail)
    task = asyncio.create_task(run_revision_job(job_id, parent, body, plan, skipped, user_id))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return PlanningJobAccepted(job_id=job_id)


def _error_code(raw: str | None) -> ErrorCode | None:
    try:
        return ErrorCode(raw) if raw else None
    except ValueError:
        return None


@app.post(
    "/packages/{project_id}/nodes/{node_id}/suggest",
    response_model=PromptSuggestion,
    dependencies=[Depends(owned_package)],
)
async def suggest_fix(
    project_id: str, node_id: str, body: SuggestRequest | None = None
) -> PromptSuggestion:
    """Propose a rewrite of a failed shot's prompt for its specific error. Never
    writes: the user reviews the suggestion and saves it through the scheduler."""
    package = await state.get_package(project_id)
    if package is None:
        raise HTTPException(404, "package not found")
    asset = package.asset_by_id(node_id)
    if asset is None:
        raise HTTPException(404, "node not found")
    if asset.type is AssetType.VOICEOVER:
        raise HTTPException(422, "Suggest fix rewrites image and video prompts only.")

    draft = body.prompt if body is not None and body.prompt is not None else asset.prompt or ""
    code = _error_code((await state.get_node(project_id, node_id)).get("error_code"))
    limit = prompt_max_bytes(asset.provider_hint)

    if use_mock():
        revision = PromptRevision(
            prompt=strip_mock_failure(draft),
            notes="MOCK mode: removed the simulated-failure token; no LLM was called.",
        )
    else:
        try:
            revision = await asyncio.to_thread(
                revise.run, draft, code, max_bytes=limit, style=package.meta.style
            )
        except Exception:  # noqa: BLE001 - any LLM failure is a bad gateway to the UI
            log.exception("suggest fix failed for %s/%s", project_id, node_id)
            raise HTTPException(502, "The AI suggestion failed; try again or edit by hand.")

    return PromptSuggestion(
        prompt=fit_to_bytes(normalize_punctuation(revision.prompt), limit),
        notes=revision.notes,
        error_code=code,
        max_bytes=limit,
    )
