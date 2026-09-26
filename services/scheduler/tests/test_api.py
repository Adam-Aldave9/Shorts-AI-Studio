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


def _valid_pkg() -> ProductionPackage:
    """Like ``_pkg`` but passes the server-side validator (video node carries its
    reference image), so the edit-lock tests exercise the real save path."""
    pkg = _pkg()
    pkg.assets[1].reference_image_ids = ["ref_a"]
    return pkg


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


def test_create_package_stamps_owner_and_returns_id():
    async def scenario(_client):
        result = await main.create_package(_pkg(), user_id="user_a")
        assert result == {"project_id": "p1"}

        # Persisted and readable back through the shared state layer.
        stored = await state.get_package("p1")
        assert stored is not None
        assert [a.node_id for a in stored.assets] == ["ref_a", "shot_a"]

        # Ownership is stamped from the authenticated caller.
        assert await state.get_project_owner("p1") == "user_a"

        # Ingest does not approve — the daemon won't see it until /approve.
        approved = [p.project_id async for p in state.iter_approved_packages()]
        assert approved == []

    _run(scenario)


def test_list_packages_is_scoped_to_owner_newest_first():
    async def scenario(client):
        from datetime import datetime, timezone

        older = _pkg()  # p1, title "T"
        older.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = _pkg()
        newer.project_id = "p2"
        newer.meta.title = "Second"
        newer.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        other = _pkg()  # owned by a different user — must not appear
        other.project_id = "p3"
        other.meta.title = "Someone else's"

        await state.save_package(older, owner_id="user_a")
        await state.save_package(newer, owner_id="user_a")
        await state.save_package(other, owner_id="user_b")
        # p1 has live phase + cost; p2 has neither yet.
        await state.set_project_phase("p1", state.PHASE_COMPLETE)
        await client.set("cost:p1", "1.50")

        summaries = await main.list_packages(user_id="user_a")
        assert [s.project_id for s in summaries] == ["p2", "p1"]  # newest first, own only

        newest, oldest = summaries
        assert newest.title == "Second"
        assert newest.phase is None
        assert newest.cost_usd == pytest.approx(0.0)

        assert oldest.title == "T"
        assert oldest.phase == state.PHASE_COMPLETE
        assert oldest.cost_usd == pytest.approx(1.50)

        # user_b sees only their own package
        b_summaries = await main.list_packages(user_id="user_b")
        assert [s.project_id for s in b_summaries] == ["p3"]

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
        assert nodes["ref_a"] == {
            "status": "succeeded", "attempts": 1, "error": None,
            "error_code": None, "error_detail": None, "blocked_by": [],
            "reused_from": None,
        }
        assert nodes["shot_a"] == {
            "status": "failed", "attempts": 2, "error": "boom",
            "error_code": None, "error_detail": None, "blocked_by": [],
            "reused_from": None,
        }

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


# --- Edit lock: PUT/approve gate on approved-set membership (spec §4.3) ---


def test_update_package_before_approval_persists():
    async def scenario(_client):
        await main.create_package(_valid_pkg(), user_id="user_a")
        edited = _valid_pkg()
        edited.meta.title = "Edited title"
        result = await main.update_package("p1", edited)
        assert result.meta.title == "Edited title"

        stored = await state.get_package("p1")
        assert stored is not None
        assert stored.meta.title == "Edited title"

    _run(scenario)


def test_update_package_after_approval_is_409():
    async def scenario(_client):
        await main.create_package(_pkg(), user_id="user_a")
        assert await state.approve_package("p1") is True

        edited = _pkg()
        edited.meta.title = "Too late"
        with pytest.raises(main.HTTPException) as exc:
            await main.update_package("p1", edited)
        assert exc.value.status_code == 409

        # The pre-approval spec is untouched.
        stored = await state.get_package("p1")
        assert stored is not None and stored.meta.title == "T"

    _run(scenario)


def test_approve_twice_is_409():
    async def scenario(_client):
        await main.create_package(_valid_pkg(), user_id="user_a")
        result = await main.approve("p1")
        assert result.status == "approved"
        assert result.reused == 0

        with pytest.raises(main.HTTPException) as exc:
            await main.approve("p1")
        assert exc.value.status_code == 409

    _run(scenario)


def test_update_package_project_id_mismatch_is_422():
    async def scenario(_client):
        await main.create_package(_pkg(), user_id="user_a")
        mismatched = _pkg()
        mismatched.project_id = "someone-else"
        with pytest.raises(main.HTTPException) as exc:
            await main.update_package("p1", mismatched)
        assert exc.value.status_code == 422

    _run(scenario)


def test_update_package_still_runs_validator():
    async def scenario(_client):
        await main.create_package(_valid_pkg(), user_id="user_a")
        # Budget below the estimated cost fails the validator's budget rule — proves
        # the validator path still runs on the pre-approval edit (the package is
        # otherwise valid, so budget is the sole failure).
        bad = _valid_pkg()
        bad.meta.budget_usd = 0.01
        with pytest.raises(main.HTTPException) as exc:
            await main.update_package("p1", bad)
        assert exc.value.status_code == 422

    _run(scenario)


def test_package_status_reports_approval_and_phase():
    async def scenario(_client):
        await main.create_package(_pkg(), user_id="user_a")

        before = await main.package_status("p1")
        assert before.approved is False
        assert before.phase is None

        await state.approve_package("p1")
        await state.set_project_phase("p1", state.PHASE_EXECUTING)

        after = await main.package_status("p1")
        assert after.approved is True
        assert after.phase == "executing"

    _run(scenario)


def test_approve_rejects_an_over_limit_prompt():
    async def scenario(_client):
        pkg = _valid_pkg()
        pkg.assets[1].provider_hint = "fal:pixverse-v6-i2v"
        pkg.assets[1].prompt = "a" * 2049
        await main.create_package(pkg, user_id="user_a")
        with pytest.raises(main.HTTPException) as exc:
            await main.approve("p1")
        assert exc.value.status_code == 422
        assert "shot_a prompt is 2049 bytes" in exc.value.detail[0]
        assert await state.is_package_approved("p1") is False

    _run(scenario)


def test_limits_lists_provider_byte_limits():
    result = asyncio.run(main.limits())
    assert result.prompt_max_bytes == {"fal:pixverse-v6-i2v": 2048}


# --- In-place recovery: PATCH a failed/waiting node, POST /retry ---


def _recovery_pkg() -> ProductionPackage:
    """ref_a -> shot_a -> shot_b, plus narration; every node renderable."""
    pkg = _valid_pkg()
    pkg.assets[0].provider_hint = "fal:flux-schnell"
    pkg.assets[0].prompt = "a tree"
    pkg.assets[1].provider_hint = "fal:pixverse-v6-i2v"
    pkg.assets[1].prompt = "a tree sways"
    pkg.assets.append(Asset(
        node_id="shot_b", type=AssetType.VIDEO, depends_on=["ref_a", "shot_a"],
        reference_image_ids=["ref_a"], provider_hint="fal:pixverse-v6-i2v", prompt="leaves fall",
    ))
    pkg.assets.append(Asset(
        node_id="narration", type=AssetType.VOICEOVER, provider_hint="elevenlabs:flash-v2.5",
        text="Once upon a time.", spec={"voice_id": "v1"},
    ))
    return pkg


async def _blocked_run(*, phase: str = state.PHASE_BLOCKED) -> None:
    await state.save_package(_recovery_pkg(), approved=True, owner_id="user_a")
    await state.set_node_status("p1", "ref_a", NodeStatus.SUCCEEDED)
    await state.set_node_status("p1", "narration", NodeStatus.SUCCEEDED)
    await state.increment_attempts("p1", "shot_a")
    await state.set_node_status(
        "p1", "shot_a", NodeStatus.DEAD_LETTERED,
        error="flagged", error_code="content_policy", error_detail="fal fetch HTTP 422: {}",
    )
    await state.set_project_phase("p1", phase)


async def _raw_asset(client, node_id: str) -> Asset:
    spec = ProductionPackage.model_validate_json(await client.get("pkg:p1"))
    return spec.asset_by_id(node_id)


def _status_code(coro) -> int:
    async def inner():
        with pytest.raises(main.HTTPException) as exc:
            await coro
        return exc.value.status_code
    return inner()


def test_patch_dead_lettered_node_saves_the_prompt():
    async def scenario(client):
        await _blocked_run()
        asset = await main.edit_node("p1", "shot_a", main.NodeEdit(prompt="a calm tree"))
        assert asset.prompt == "a calm tree"
        assert asset.status is NodeStatus.DEAD_LETTERED  # saving alone doesn't retry
        assert (await _raw_asset(client, "shot_a")).prompt == "a calm tree"

    _run(scenario)


def test_patch_pending_node_waiting_on_a_failed_dependency():
    async def scenario(client):
        await _blocked_run()
        asset = await main.edit_node("p1", "shot_b", main.NodeEdit(prompt="leaves drift"))
        assert asset.prompt == "leaves drift"

    _run(scenario)


def test_patch_voiceover_text_and_voice():
    async def scenario(client):
        await _blocked_run()
        await state.set_node_status("p1", "narration", NodeStatus.DEAD_LETTERED, error="voice")
        asset = await main.edit_node(
            "p1", "narration", main.NodeEdit(text="Hello there.", voice_id="v2")
        )
        assert asset.text == "Hello there." and asset.spec["voice_id"] == "v2"

    _run(scenario)


def test_patch_conflicts():
    async def scenario(client):
        await _blocked_run()
        edit = main.NodeEdit(prompt="x")
        assert await _status_code(main.edit_node("p1", "ref_a", edit)) == 409  # succeeded

        await state.set_node_status("p1", "shot_a", NodeStatus.DISPATCHED)
        assert await _status_code(main.edit_node("p1", "shot_a", edit)) == 409  # rendering

        await state.set_node_status("p1", "shot_a", NodeStatus.SUCCEEDED)
        assert await _status_code(main.edit_node("p1", "shot_b", edit)) == 409  # ready

        assert await _status_code(main.edit_node("p1", "ghost", edit)) == 404

    _run(scenario)


@pytest.mark.parametrize("phase", [state.PHASE_PAUSED, state.PHASE_COMPLETE, state.PHASE_COMPOSITING])
def test_patch_and_retry_refuse_finished_or_paused_runs(phase):
    async def scenario(client):
        await _blocked_run(phase=phase)
        assert await _status_code(main.edit_node("p1", "shot_a", main.NodeEdit(prompt="x"))) == 409
        assert await _status_code(main.retry("p1", main.RetryRequest())) == 409

    _run(scenario)


def test_patch_and_retry_refuse_unapproved_runs():
    async def scenario(client):
        await state.save_package(_recovery_pkg(), owner_id="user_a")
        assert await _status_code(main.edit_node("p1", "shot_a", main.NodeEdit(prompt="x"))) == 409
        assert await _status_code(main.retry("p1", main.RetryRequest())) == 409

    _run(scenario)


def test_patch_validation_errors():
    async def scenario(client):
        await _blocked_run()
        cases = [
            main.NodeEdit(prompt="a" * 2049),  # over the byte limit
            main.NodeEdit(prompt="   "),  # blank
            main.NodeEdit(text="narration on a video"),  # wrong field for the type
            main.NodeEdit(),  # nothing to change
        ]
        for edit in cases:
            assert await _status_code(main.edit_node("p1", "shot_a", edit)) == 422
        await state.set_node_status("p1", "narration", NodeStatus.FAILED)
        assert await _status_code(
            main.edit_node("p1", "narration", main.NodeEdit(prompt="x"))
        ) == 422
        assert (await _raw_asset(client, "shot_a")).prompt == "a tree sways"

    _run(scenario)


def test_retry_resets_the_failed_node_and_leaves_the_phase():
    async def scenario(client):
        await _blocked_run()
        result = await main.retry("p1", main.RetryRequest(node_ids=["shot_a"]))
        assert result.phase == state.PHASE_BLOCKED  # the daemon self-heals it
        node = await state.get_node("p1", "shot_a")
        assert node == {"status": "pending", "attempts": "1"}

    _run(scenario)


def test_retry_defaults_to_every_failed_node():
    async def scenario(client):
        await _blocked_run()
        await state.set_node_status("p1", "narration", NodeStatus.FAILED, error="busy")
        await main.retry("p1", None)
        assert (await state.get_node("p1", "shot_a"))["status"] == "pending"
        assert (await state.get_node("p1", "narration"))["status"] == "pending"

    _run(scenario)


def test_retry_errors():
    async def scenario(client):
        await _blocked_run()
        assert await _status_code(main.retry("p1", main.RetryRequest(node_ids=["ref_a"]))) == 409
        assert await _status_code(main.retry("p1", main.RetryRequest(node_ids=["ghost"]))) == 404

        # A legacy over-limit prompt must be fixed before it can be retried.
        spec = ProductionPackage.model_validate_json(await client.get("pkg:p1"))
        spec.asset_by_id("shot_a").prompt = "a" * 2049
        await client.set("pkg:p1", spec.model_dump_json())
        assert await _status_code(main.retry("p1", main.RetryRequest(node_ids=["shot_a"]))) == 422

        await state.set_node_status("p1", "shot_a", NodeStatus.SUCCEEDED)
        assert await _status_code(main.retry("p1", main.RetryRequest())) == 409  # nothing to retry

    _run(scenario)


def test_status_event_carries_error_code_and_blocked_by():
    async def scenario(client):
        await _blocked_run()
        frame = await main._status_event("p1")
        shot_a, shot_b = frame["nodes"]["shot_a"], frame["nodes"]["shot_b"]
        assert shot_a["error_code"] == "content_policy"
        assert shot_a["error_detail"] == "fal fetch HTTP 422: {}"
        assert shot_b["blocked_by"] == ["shot_a"]

    _run(scenario)


def test_event_stream_stays_open_while_blocked(monkeypatch):
    async def no_sleep(_s):
        return None

    monkeypatch.setattr(main.asyncio, "sleep", no_sleep)

    async def scenario(client):
        await _blocked_run()
        response = await main.events("p1")
        frames = []
        async for frame in response.body_iterator:
            frames.append(frame)
            if len(frames) == 3:
                break
        assert len(frames) == 3

    _run(scenario)
