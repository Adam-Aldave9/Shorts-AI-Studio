"""No-network checks for the shared run-state layer, against fakeredis.

Skipped automatically if ``fakeredis`` is not installed (keeps the suite green
without a real Redis). The async API is exercised inside a single ``asyncio.run``
so the injected client lives on one event loop.
"""

from __future__ import annotations

import asyncio

import pytest

from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

import state

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _pkg() -> ProductionPackage:
    return ProductionPackage(
        project_id="p_test",
        meta=Meta(
            title="T",
            premise="P",
            target_duration_s=6,
            style="s",
            narration_voice_id="v_meta",
            budget_usd=15.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, provider_hint="fal:flux-schnell", prompt="x"),
            Asset(
                node_id="shot_a",
                type=AssetType.VIDEO,
                depends_on=["ref_a"],
                reference_image_ids=["ref_a"],
                provider_hint="fal:pixverse-v6-i2v",
                spec={"duration_s": 3.0},
                prompt="y",
            ),
        ],
    )


def _run(scenario) -> None:
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def wrapper():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            await scenario()
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


def test_save_get_overlay_and_dep_urls():
    async def scenario():
        pkg = _pkg()
        await state.save_package(pkg, approved=True)

        # approved-set iteration sees the package
        ids = [p.project_id async for p in state.iter_approved_packages()]
        assert ids == ["p_test"]

        # untouched nodes overlay back to the spec default (PENDING)
        got = await state.get_package("p_test")
        assert {a.node_id: a.status for a in got.assets} == {
            "ref_a": NodeStatus.PENDING,
            "shot_a": NodeStatus.PENDING,
        }

        # a worker success overlays onto the hydrated package
        await state.set_node_status(
            "p_test",
            "ref_a",
            NodeStatus.SUCCEEDED,
            asset_url="s3://film-assets/p_test/ref_a.png",
            provider_url="https://fal/ref_a.png",
            actual_cost_usd=0.04,
        )
        got = await state.get_package("p_test")
        ref = got.asset_by_id("ref_a")
        assert ref.status is NodeStatus.SUCCEEDED
        assert ref.asset_url == "s3://film-assets/p_test/ref_a.png"
        assert ref.actual_cost_usd == pytest.approx(0.04)

        # i2v threading: the dependency's upstream provider URL is recoverable
        deps = await state.get_dep_provider_urls("p_test", ["ref_a"])
        assert deps == {"ref_a": "https://fal/ref_a.png"}

    _run(scenario)


def test_attempts_phase_and_final_url():
    async def scenario():
        await state.save_package(_pkg(), approved=True)

        assert await state.increment_attempts("p_test", "shot_a") == 1
        assert await state.increment_attempts("p_test", "shot_a") == 2
        assert (await state.get_node("p_test", "shot_a"))["attempts"] == "2"

        await state.set_project_phase("p_test", state.PHASE_COMPLETE)
        assert await state.get_project_phase("p_test") == "complete"

        await state.set_final_url("p_test", "s3://film-assets/p_test/final.mp4")
        assert await state.get_final_url("p_test") == "s3://film-assets/p_test/final.mp4"

    _run(scenario)


def test_missing_package_and_approve():
    async def scenario():
        assert await state.get_package("nope") is None
        assert await state.approve_package("nope") is False

    _run(scenario)
