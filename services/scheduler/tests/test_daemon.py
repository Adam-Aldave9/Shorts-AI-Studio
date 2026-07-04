"""Reconciliation behaviour of the DAG-walker daemon (no network).

Exercises ``_advance`` against fakeredis (shared by the state layer and the budget
gate) with Celery's ``send_task`` stubbed to record dispatches. Verifies: ready
roots are dispatched and marked, dependents unlock on dep success, the compositor
fires exactly once, a failed node parks the run as ``blocked``, and a blown budget
parks it as ``paused``. Skipped if ``fakeredis`` is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

import state
from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

from scheduler import daemon
from scheduler.celery_app import COMPOSITE_TASK, RENDER_TASK

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _pkg(statuses: dict[str, NodeStatus], *, budget_usd: float = 100.0) -> ProductionPackage:
    return ProductionPackage(
        project_id="p1",
        meta=Meta(
            title="T", premise="P", target_duration_s=6, style="s",
            narration_voice_id="v", budget_usd=budget_usd,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, estimated_cost_usd=0.04,
                  status=statuses["ref_a"]),
            Asset(node_id="narration", type=AssetType.VOICEOVER, estimated_cost_usd=0.30,
                  status=statuses["narration"]),
            Asset(node_id="shot_a", type=AssetType.VIDEO, depends_on=["ref_a"],
                  estimated_cost_usd=0.10, status=statuses["shot_a"]),
        ],
    )


def _run(scenario) -> list[tuple]:
    """Run ``scenario(sends)`` on one loop with fakeredis wired into state + budget.

    Returns the recorded ``send_task`` calls as ``(name, args, queue)`` tuples.
    """
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    sends: list[tuple] = []

    def fake_send_task(name, args=None, queue=None, **_):
        sends.append((name, args, queue))

    async def wrapper():
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        daemon.use_budget_client(client)
        original = daemon.celery_app.send_task
        daemon.celery_app.send_task = fake_send_task
        try:
            await scenario(sends)
        finally:
            daemon.celery_app.send_task = original
            state.use_client(None)
            daemon.use_budget_client(None)

    asyncio.run(wrapper())
    return sends


def test_dispatches_ready_roots_marks_them_and_sets_executing():
    P = NodeStatus.PENDING

    async def scenario(sends):
        pkg = _pkg({"ref_a": P, "narration": P, "shot_a": P})
        await daemon._advance(pkg)

        # Both dependency-free roots dispatched onto the render queue; shot_a waits.
        dispatched = sorted(args[1] for name, args, _ in sends if name == RENDER_TASK)
        assert dispatched == ["narration", "ref_a"]

        # Their live state flipped to DISPATCHED; the dependent stayed untouched.
        assert (await state.get_node("p1", "ref_a"))["status"] == NodeStatus.DISPATCHED.value
        assert (await state.get_node("p1", "narration"))["status"] == NodeStatus.DISPATCHED.value
        assert await state.get_node("p1", "shot_a") == {}

        assert await state.get_project_phase("p1") == state.PHASE_EXECUTING

    _run(scenario)


def test_dependent_unlocks_after_dependency_succeeds():
    S, P = NodeStatus.SUCCEEDED, NodeStatus.PENDING

    async def scenario(sends):
        pkg = _pkg({"ref_a": S, "narration": S, "shot_a": P})
        await daemon._advance(pkg)

        renders = [args[1] for name, args, _ in sends if name == RENDER_TASK]
        assert renders == ["shot_a"]  # only the now-ready dependent

    _run(scenario)


def test_compositor_fires_exactly_once_when_all_succeeded():
    S = NodeStatus.SUCCEEDED

    async def scenario(sends):
        pkg = _pkg({"ref_a": S, "narration": S, "shot_a": S})

        await daemon._advance(pkg)  # all succeeded -> hand off + flip to compositing
        assert [name for name, *_ in sends] == [COMPOSITE_TASK]
        assert await state.get_project_phase("p1") == state.PHASE_COMPOSITING

        await daemon._advance(pkg)  # next tick: phase guard stops a re-send
        assert [name for name, *_ in sends] == [COMPOSITE_TASK]

    _run(scenario)


def test_failed_node_orphaning_dependents_parks_blocked():
    F, S, P = NodeStatus.FAILED, NodeStatus.SUCCEEDED, NodeStatus.PENDING

    async def scenario(sends):
        pkg = _pkg({"ref_a": F, "narration": S, "shot_a": P})
        await daemon._advance(pkg)

        assert sends == []  # nothing dispatchable
        assert await state.get_project_phase("p1") == state.PHASE_BLOCKED

    _run(scenario)


def test_budget_exceeded_parks_paused_without_dispatch():
    P = NodeStatus.PENDING

    async def scenario(sends):
        # Budget below even the cheapest node (est $0.04): the first reserve trips,
        # so the run parks paused before dispatching anything.
        pkg = _pkg({"ref_a": P, "narration": P, "shot_a": P}, budget_usd=0.01)
        await daemon._advance(pkg)

        assert sends == []
        assert await state.get_project_phase("p1") == state.PHASE_PAUSED

    _run(scenario)
