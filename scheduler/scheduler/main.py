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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from schema import ProductionPackage
from sse_starlette.sse import EventSourceResponse

from scheduler.daemon import run_daemon
from scheduler.dag import Dag
from scheduler.state import approve_package, get_package, save_package

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = FastAPI(title="AI Film Pipeline — Scheduler Service", version="1.0.0")
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/packages/{project_id}", response_model=ProductionPackage)
async def read_package(project_id: str) -> ProductionPackage:
    package = await get_package(project_id)
    if not package:
        raise HTTPException(404, "package not found")
    return package


@app.put("/packages/{project_id}", response_model=ProductionPackage)
async def update_package(project_id: str, package: ProductionPackage) -> ProductionPackage:
    """Save a checkpoint edit. Re-runs the validator server-side (spec §4.3)."""
    from planning.validator import validate_package  # lazy: avoid hard dep at import

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


@app.get("/packages/{project_id}/events")
async def events(project_id: str) -> EventSourceResponse:
    """SSE stream of live node status for the Status screen (spec §9.2)."""

    async def gen():
        while True:
            package = await get_package(project_id)
            if package:
                dag = Dag(package)
                payload = {
                    "project_id": project_id,
                    "nodes": {a.node_id: a.status.value for a in package.assets},
                    "critical_path_s": dag.critical_path_estimate(),
                    "complete": dag.is_complete(),
                }
                yield {"event": "status", "data": json.dumps(payload)}
                if dag.is_complete():
                    break
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())
