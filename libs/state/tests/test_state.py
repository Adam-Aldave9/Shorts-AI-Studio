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


def test_projects_all_index_lists_every_package():
    async def scenario():
        approved = _pkg()  # p_test
        unapproved = _pkg()
        unapproved.project_id = "p_other"
        await state.save_package(approved, approved=True)
        await state.save_package(unapproved)

        # projects:all carries every persisted package, approved or not (History list)
        all_ids = sorted([p.project_id async for p in state.iter_all_packages()])
        assert all_ids == ["p_other", "p_test"]

        # the approved set is still independent — only the approved one is in it
        approved_ids = [p.project_id async for p in state.iter_approved_packages()]
        assert approved_ids == ["p_test"]

    _run(scenario)


def test_missing_package_and_approve():
    async def scenario():
        assert await state.get_package("nope") is None
        assert await state.approve_package("nope") is False

    _run(scenario)


# --------------------------------------------------------------------------
# Ownership (per-user isolation)
# --------------------------------------------------------------------------
def test_owner_stamped_and_scoped_history():
    async def scenario():
        a = _pkg()  # p_test, owned by user_a
        b = _pkg()
        b.project_id = "p_b"
        await state.save_package(a, owner_id="user_a")
        await state.save_package(b, owner_id="user_b")

        assert await state.get_project_owner("p_test") == "user_a"
        assert await state.get_project_owner("p_b") == "user_b"
        assert await state.get_project_owner("nope") is None

        # each user sees only their own packages
        a_ids = [p.project_id async for p in state.iter_user_packages("user_a")]
        b_ids = [p.project_id async for p in state.iter_user_packages("user_b")]
        assert a_ids == ["p_test"]
        assert b_ids == ["p_b"]

    _run(scenario)


def test_checkpoint_edit_preserves_owner():
    async def scenario():
        pkg = _pkg()
        await state.save_package(pkg, owner_id="user_a")
        # a later save with no owner_id (a checkpoint edit) must not drop ownership
        await state.save_package(pkg)
        assert await state.get_project_owner("p_test") == "user_a"

    _run(scenario)


# --------------------------------------------------------------------------
# Users (accounts / auth) — Redis-only branch
# --------------------------------------------------------------------------
def test_create_and_fetch_user():
    async def scenario():
        await state.create_user("u_1", "alice", "Alice", "hash_x", "2026-07-04T00:00:00Z")

        by_name = await state.get_user_by_username("alice")
        assert by_name is not None
        assert by_name["user_id"] == "u_1"
        assert by_name["display_username"] == "Alice"
        assert by_name["password_hash"] == "hash_x"

        by_id = await state.get_user_by_id("u_1")
        assert by_id["username"] == "alice"

        assert await state.get_user_by_username("nobody") is None
        assert await state.get_user_by_id("nobody") is None

    _run(scenario)


def test_create_user_rejects_duplicate_username():
    async def scenario():
        await state.create_user("u_1", "alice", "Alice", "h1", "2026-07-04T00:00:00Z")
        with pytest.raises(state.UserExistsError):
            await state.create_user("u_2", "alice", "Alice", "h2", "2026-07-04T00:00:00Z")

    _run(scenario)


# --------------------------------------------------------------------------
# Planning jobs (transient, Redis-only)
# --------------------------------------------------------------------------
def test_plan_job_lifecycle_success():
    async def scenario():
        assert await state.get_plan_job("j_x") is None  # unknown -> None

        await state.create_plan_job("j_x", owner_id="user_a")
        frame = await state.get_plan_job("j_x")
        assert frame == {
            "job_id": "j_x",
            "status": state.PLAN_QUEUED,
            "stage": None,
            "stage_index": -1,
            "stage_count": len(state.PLAN_STAGES),
            "elapsed_s": frame["elapsed_s"],
            "stage_elapsed_s": frame["stage_elapsed_s"],
            "stage_timings": {},
            "details": {},
            "project_id": None,
            "errors": None,
        }
        # created_at is stamped, so the frame carries a (tiny, non-negative) elapsed.
        assert frame["elapsed_s"] >= 0.0
        assert await state.get_plan_job_owner("j_x") == "user_a"

        await state.set_plan_stage("j_x", "script")
        frame = await state.get_plan_job("j_x")
        assert frame["status"] == state.PLAN_RUNNING
        assert frame["stage"] == "script"
        assert frame["stage_index"] == 1

        await state.set_plan_succeeded("j_x", "p_123")
        frame = await state.get_plan_job("j_x")
        assert frame["status"] == state.PLAN_SUCCEEDED
        assert frame["project_id"] == "p_123"
        # The terminal setter closes the final stage's timer — this is what lets the
        # last row on the Planning screen render as done rather than forever spinning.
        assert "script" in frame["stage_timings"]

    _run(scenario)


def test_plan_job_records_stage_timings_and_details():
    async def scenario():
        await state.create_plan_job("j_t", owner_id="user_a")

        assert await state.set_plan_stage("j_t", "world") is None  # nothing to close yet
        await state.set_plan_detail("j_t", "world", {"characters": ["Mira"], "locations": []})

        closed = await state.set_plan_stage("j_t", "script")
        assert closed is not None
        outgoing, elapsed = closed
        assert outgoing == "world"
        assert elapsed >= 0.0

        await state.set_plan_detail("j_t", "script", {"title": "The Last Light", "scenes": 7})

        frame = await state.get_plan_job("j_t")
        assert "world" in frame["stage_timings"]
        assert "script" not in frame["stage_timings"]  # still in progress
        assert frame["details"] == {
            "world": {"characters": ["Mira"], "locations": []},
            "script": {"title": "The Last Light", "scenes": 7},
        }

    _run(scenario)


def test_plan_job_failed_carries_errors():
    async def scenario():
        await state.create_plan_job("j_y", owner_id="user_b")
        await state.set_plan_stage("j_y", "prompts")
        await state.set_plan_failed("j_y", ["bad rule", "another"])
        frame = await state.get_plan_job("j_y")
        assert frame["status"] == state.PLAN_FAILED
        assert frame["errors"] == ["bad rule", "another"]
        # The failing stage stays named, with its timing closed out, so the screen can
        # keep the completed rows on display alongside the error.
        assert frame["stage"] == "prompts"
        assert "prompts" in frame["stage_timings"]

        # owner check is scoped: a miss returns None (backs the 404 in owned_job)
        assert await state.get_plan_job_owner("nope") is None

    _run(scenario)
