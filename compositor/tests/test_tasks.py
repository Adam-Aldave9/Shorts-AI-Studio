"""Wiring of the compositor Celery task to shared state (no FFmpeg, no network).

Stubs the pure ``composite_package`` render and ``Storage`` so the test exercises
only the task's wiring: load the *hydrated* package from state, hand it to the
renderer, then record ``final_url`` + flip the run to ``complete``. The actual
filtergraph is covered separately by the render tests. Skipped if
``fakeredis`` is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

import state
from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

from compositor import tasks

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
            Asset(node_id="shot_a", type=AssetType.VIDEO, estimated_cost_usd=0.10),
        ],
    )


def test_composite_loads_state_renders_and_records_complete(monkeypatch):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    client = fakeredis_aio.FakeRedis(decode_responses=True)
    state.use_client(client)

    seen: dict[str, object] = {}

    def fake_composite_package(pkg, storage):
        # Receives the hydrated package with the worker-reported asset_url overlaid.
        seen["asset_url"] = pkg.asset_by_id("shot_a").asset_url
        return "s3://film-assets/p1/final.mp4"

    monkeypatch.setattr(tasks, "composite_package", fake_composite_package)
    monkeypatch.setattr(tasks, "Storage", lambda: object())

    try:
        asyncio.run(state.save_package(_pkg()))
        asyncio.run(state.set_node_status(
            "p1", "shot_a", NodeStatus.SUCCEEDED, asset_url="s3://film-assets/p1/shot_a.mp4"
        ))

        result = tasks.composite("p1")

        assert seen["asset_url"] == "s3://film-assets/p1/shot_a.mp4"
        assert result["final_url"] == "s3://film-assets/p1/final.mp4"
        assert asyncio.run(state.get_final_url("p1")) == "s3://film-assets/p1/final.mp4"
        assert asyncio.run(state.get_project_phase("p1")) == state.PHASE_COMPLETE
    finally:
        state.use_client(None)


def test_composite_missing_package_raises(monkeypatch):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
    monkeypatch.setattr(tasks, "Storage", lambda: object())
    try:
        with pytest.raises(RuntimeError, match="not found in state"):
            tasks.composite("missing")
    finally:
        state.use_client(None)
