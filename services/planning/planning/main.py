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
from concurrent.futures import Future
from uuid import uuid4

import state
from auth import auth_router, current_user_id, install_auth, owned_job
from auth.config import AUTH_ALLOWED_ORIGINS
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from schema import ProductionPackage
from sse_starlette.sse import EventSourceResponse

from planning.graph import STAGE_SEQUENCE, run_planning
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


class Brief(BaseModel):
    premise: str
    target_duration_s: float = 90
    style: str | None = None
    narration_voice_id: str | None = None


class PlanningJobAccepted(BaseModel):
    """The 202 response handed back to the Submit screen, which routes the browser to
    ``/planning/{job_id}`` to follow the job's SSE progress stream."""

    job_id: str


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
