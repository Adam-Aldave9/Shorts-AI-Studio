"""The DAG-walker daemon (spec §6.1).

A reconciliation loop, not a one-shot walk: each tick, for every approved package,
rebuild the DAG from the *live* shared state — so a worker's success unlocks its
dependents on the next tick — then dispatch every ready node onto Celery under a
per-project budget gate, hand the finished timeline to the compositor exactly once,
and surface a stalled run as ``blocked``. Runs as an asyncio task inside the FastAPI
process; it only ever *sends* Celery tasks, never runs them (spec §3, §6.2).
"""

from __future__ import annotations

import asyncio
import logging
import os

import redis.asyncio as redis
from rate_limiter import BudgetExceeded, CostTracker
from schema import NodeStatus, ProductionPackage

from scheduler.celery_app import (
    COMPOSITE_TASK,
    COMPOSITOR_QUEUE,
    RENDER_TASK,
    WORKER_QUEUE,
    celery_app,
)
from scheduler.dag import Dag
from scheduler.state import (
    PHASE_BLOCKED,
    PHASE_COMPOSITING,
    PHASE_EXECUTING,
    PHASE_PAUSED,
    get_project_phase,
    iter_approved_packages,
    set_node_status,
    set_project_phase,
)

log = logging.getLogger("scheduler.daemon")

POLL_INTERVAL_S = 1.0
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# CostTracker's Redis client. The daemon runs in one long-lived loop (FastAPI), so a
# single lazily-created client is fine — unlike the worker, which gets a fresh loop
# per task. Tests inject fakeredis via ``use_budget_client``.
_budget_override: redis.Redis | None = None
_budget_cache: redis.Redis | None = None


def use_budget_client(client: redis.Redis | None) -> None:
    """Inject the Redis client backing the budget gate (tests / fakeredis)."""
    global _budget_override
    _budget_override = client


def _budget_client() -> redis.Redis:
    global _budget_cache
    if _budget_override is not None:
        return _budget_override
    if _budget_cache is None:
        _budget_cache = redis.from_url(REDIS_URL)
    return _budget_cache


async def _advance(package: ProductionPackage) -> None:
    """One reconciliation step for a single package, driven entirely by live state.

    The package is already hydrated (``get_package`` overlaid each node's live hash),
    so its asset statuses reflect what the workers have reported.
    """
    project_id = package.project_id

    phase = await get_project_phase(project_id)
    if phase is None:  # first sight of a freshly approved package
        phase = PHASE_EXECUTING
        await set_project_phase(project_id, PHASE_EXECUTING)

    # Only an actively-executing project is the daemon's to drive: ``compositing``
    # waits on the compositor; ``complete``/``paused``/``blocked`` wait on a human
    # (spec §10.2). Returning here is also what makes the handoffs below fire once.
    if phase != PHASE_EXECUTING:
        return

    dag = Dag(package)

    # Completion: hand the finished timeline to the compositor exactly once. The
    # executing -> compositing transition is the guard that stops COMPOSITE_TASK from
    # re-firing on every subsequent tick.
    if dag.all_succeeded():
        await set_project_phase(project_id, PHASE_COMPOSITING)
        log.info("project=%s all nodes succeeded -> compositor", project_id)
        celery_app.send_task(COMPOSITE_TASK, args=[project_id], queue=COMPOSITOR_QUEUE)
        return

    # Stalled: nothing ready, nothing in flight, yet not all succeeded -> a failed or
    # dead-lettered node has orphaned its dependents. Surface for human edit + re-run.
    if dag.is_blocked():
        await set_project_phase(project_id, PHASE_BLOCKED)
        log.warning("project=%s blocked: a failed node orphaned its dependents", project_id)
        return

    # Dispatch every ready node, each gated on the live per-project budget (spec §6.5).
    # ``reserve`` checks cumulative spend without atomically reserving — safe while this
    # single daemon is the sole dispatcher (see "Budget reserve race" in the plan).
    cost = CostTracker(_budget_client(), project_id, package.meta.budget_usd)
    for node_id in dag.ready_nodes():
        asset = package.asset_by_id(node_id)
        assert asset is not None
        try:
            await cost.reserve(asset.estimated_cost_usd)
        except BudgetExceeded as exc:
            await set_project_phase(project_id, PHASE_PAUSED)
            log.warning("project=%s paused: %s", project_id, exc)
            return
        log.info("enqueue node=%s project=%s", node_id, project_id)
        celery_app.send_task(RENDER_TASK, args=[project_id, node_id], queue=WORKER_QUEUE)
        await set_node_status(project_id, node_id, NodeStatus.DISPATCHED)


async def run_daemon(stop: asyncio.Event) -> None:
    log.info("DAG-walker daemon started")
    while not stop.is_set():
        try:
            async for package in iter_approved_packages():
                await _advance(package)
        except Exception:  # keep the daemon alive; surface in logs
            log.exception("daemon tick failed")
        await asyncio.sleep(POLL_INTERVAL_S)
    log.info("DAG-walker daemon stopped")
