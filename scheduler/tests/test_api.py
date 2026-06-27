"""Scheduler API ingress + SSE status frame (no network, no live server).

Exercises the two scheduler surfaces against fakeredis wired into the shared state
layer: ``POST /packages`` (``create_package``) persists a package the daemon can
then see, and ``_status_event`` builds the richer observability frame the SSE
stream emits — per-node status/attempts/error, phase, cost-to-date, and final_url.
Skipped if ``fakeredis`` is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

import state
from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

from scheduler import main

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _pkg() -> ProductionPackage:
    return ProductionPackage(
        project_id="p1",
        meta=Meta(
            title="T", premise="P", target_duration_s=6, style="s",
            narration_voice_id="v", budget_usd=100.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, estimated_cost_usd=0.04),
            Asset(node_id="shot_a", type=AssetType.VIDEO, depends_on=["ref_a"],
                  estimated_cost_usd=0.10),
        ],
    )


def _run(scenario):
    """Run ``scenario(client)`` on one loop with fakeredis wired into state."""
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def wrapper():
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        try:
            await scenario(client)
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


def test_create_package_persists_and_returns_id():
    async def scenario(_client):
        result = await main.create_package(_pkg())
        assert result == {"project_id": "p1"}

        # Persisted and readable back through the shared state layer.
        stored = await state.get_package("p1")
        assert stored is not None
        assert [a.node_id for a in stored.assets] == ["ref_a", "shot_a"]

        # Ingest does not approve — the daemon won't see it until /approve.
        approved = [p.project_id async for p in state.iter_approved_packages()]
        assert approved == []

    _run(scenario)


def test_list_packages_returns_summaries_newest_first():
    async def scenario(client):
        from datetime import datetime, timezone

        older = _pkg()  # p1, title "T"
        older.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = _pkg()
        newer.project_id = "p2"
        newer.meta.title = "Second"
        newer.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

        await state.save_package(older)
        await state.save_package(newer)
        # p1 has live phase + cost; p2 has neither yet.
        await state.set_project_phase("p1", state.PHASE_COMPLETE)
        await client.set("cost:p1", "1.50")

        summaries = await main.list_packages()
        assert [s.project_id for s in summaries] == ["p2", "p1"]  # newest first

        newest, oldest = summaries
        assert newest.title == "Second"
        assert newest.phase is None
        assert newest.cost_usd == pytest.approx(0.0)

        assert oldest.title == "T"
        assert oldest.phase == state.PHASE_COMPLETE
        assert oldest.cost_usd == pytest.approx(1.50)

    _run(scenario)


def test_status_event_carries_live_node_phase_cost_and_final_url():
    async def scenario(client):
        await state.save_package(_pkg())
        # ref_a succeeded after 1 try; shot_a failed twice with an error.
        await state.set_node_status("p1", "ref_a", NodeStatus.SUCCEEDED,
                                    asset_url="s3://b/ref_a.png")
        await state.increment_attempts("p1", "ref_a")
        await state.set_node_status("p1", "shot_a", NodeStatus.FAILED, error="boom")
        await state.increment_attempts("p1", "shot_a")
        await state.increment_attempts("p1", "shot_a")
        await state.set_project_phase("p1", state.PHASE_EXECUTING)
        await client.set("cost:p1", "0.04")

        frame = await main._status_event("p1")
        assert frame is not None
        assert frame["phase"] == state.PHASE_EXECUTING
        assert frame["cost_usd"] == pytest.approx(0.04)
        assert frame["final_url"] is None
        assert frame["complete"] is False

        nodes = frame["nodes"]
        assert nodes["ref_a"] == {"status": "succeeded", "attempts": 1, "error": None}
        assert nodes["shot_a"] == {"status": "failed", "attempts": 2, "error": "boom"}

    _run(scenario)


def test_status_event_reports_complete_with_final_url():
    async def scenario(_client):
        await state.save_package(_pkg())
        await state.set_project_phase("p1", state.PHASE_COMPLETE)
        await state.set_final_url("p1", "s3://film-assets/p1/final.mp4")

        frame = await main._status_event("p1")
        assert frame["phase"] == state.PHASE_COMPLETE
        assert frame["complete"] is True
        assert frame["final_url"] == "s3://film-assets/p1/final.mp4"

    _run(scenario)


def test_status_event_none_before_package_ingested():
    async def scenario(_client):
        assert await main._status_event("missing") is None

    _run(scenario)
