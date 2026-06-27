"""FastAPI surface for the scheduler (spec §3, §4.3, §9.2).

Serves the frontend: read a package, save checkpoint edits (re-validated), approve
(hand off to execution), and stream live node status over SSE. The DAG-walker
daemon is started as a background asyncio task on app startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from schema import ProductionPackage
from sse_starlette.sse import EventSourceResponse
from validator import validate_package

from scheduler.daemon import run_daemon
from scheduler.dag import Dag
from scheduler.state import (
    PHASE_BLOCKED,
    PHASE_COMPLETE,
    PHASE_PAUSED,
    approve_package,
    get_cost,
    get_final_url,
    get_node,
    get_package,
    get_project_phase,
    iter_all_packages,
    save_package,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = FastAPI(title="AI Film Pipeline — Scheduler Service", version="1.0.0")

# Phases from which the run makes no further autonomous progress, so the SSE stream
# can close: ``complete`` (final cut ready), or ``blocked``/``paused`` (awaiting a
# human edit + re-run, spec §10.2). The client reconnects when the run resumes.
_TERMINAL_PHASES = {PHASE_COMPLETE, PHASE_BLOCKED, PHASE_PAUSED}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/packages", status_code=201)
async def create_package(package: ProductionPackage) -> dict[str, str]:
    """Ingest a full production package — the execution entry point.

    The package is already authored/validated upstream (the sequential driver, the
    ``harness submit`` test entry, or the planning tier handing off the
    same way), so this does not re-run the validator; checkpoint edits via ``PUT``
    do. Persisting it makes it visible to the daemon once ``/approve`` adds it to the
    approved set.
    """
    await save_package(package)
    return {"project_id": package.project_id}


@app.get("/packages", response_model=list[PackageSummary])
async def list_packages() -> list[PackageSummary]:
    """List every persisted package for the History screen (spec §9.2), newest first.

    Backed by the ``projects:all`` index that ``save_package`` maintains; phase and
    cost-to-date are overlaid from live run state. (Postgres becomes the durable
    source for this list later, behind the same ``state`` interface.)"""
    summaries = [
        PackageSummary(
            project_id=pkg.project_id,
            title=pkg.meta.title,
            created_at=pkg.created_at,
            phase=await get_project_phase(pkg.project_id),
            cost_usd=await get_cost(pkg.project_id),
        )
        async for pkg in iter_all_packages()
    ]
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


@app.get("/packages/{project_id}", response_model=ProductionPackage)
async def read_package(project_id: str) -> ProductionPackage:
    package = await get_package(project_id)
    if not package:
        raise HTTPException(404, "package not found")
    return package


@app.put("/packages/{project_id}", response_model=ProductionPackage)
async def update_package(project_id: str, package: ProductionPackage) -> ProductionPackage:
    """Save a checkpoint edit. Re-runs the validator server-side (spec §4.3)."""
    report = validate_package(package)
    if not report.ok:
        raise HTTPException(422, detail=report.errors)
    await save_package(package)
    return package


@app.post("/packages/{project_id}/approve")
async def approve(project_id: str) -> dict[str, str]:
    if not await approve_package(project_id):
        raise HTTPException(404, "package not found")
    return {"status": "approved"}


async def _status_event(project_id: str) -> dict | None:
    """Build one SSE status frame from live shared state — the run's observability
    surface (spec §9.2, §12.4): per-node status/attempts/error, project phase,
    cost-to-date, the content critical-path floor, and the final cut URL once it
    exists. Returns ``None`` while the package is unknown (not yet ingested)."""
    package = await get_package(project_id)
    if not package:
        return None
    dag = Dag(package)
    nodes: dict[str, dict] = {}
    for asset in package.assets:
        live = await get_node(project_id, asset.node_id)
        nodes[asset.node_id] = {
            "status": asset.status.value,
            "attempts": int(live.get("attempts", 0)),
            "error": live.get("error"),
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


@app.get("/packages/{project_id}/events")
async def events(project_id: str) -> EventSourceResponse:
    """SSE stream of live run state for the Status screen (spec §9.2).

    Streams through ``executing`` and ``compositing`` and only closes once the run
    reaches a terminal phase — crucially *after* the compositor sets ``final_url``,
    so the last frame carries the final cut (the old ``is_complete`` break closed the
    stream the instant all nodes succeeded, before compositing finished)."""

    async def gen():
        while True:
            payload = await _status_event(project_id)
            if payload is not None:
                yield {"event": "status", "data": json.dumps(payload)}
                if payload["phase"] in _TERMINAL_PHASES:
                    break
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())
