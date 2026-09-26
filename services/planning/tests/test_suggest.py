"""The revise agent and the "Suggest fix" endpoint (no network, fakeredis)."""

from __future__ import annotations

import asyncio

import pytest
import state
from schema import Asset, AssetType, ErrorCode, Meta, NodeStatus, ProductionPackage

from planning import main
from planning.agents import revise
from planning.models import PromptRevision

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def test_revise_prompt_carries_code_specific_guidance():
    too_long = revise.build_prompt("p", ErrorCode.PROMPT_TOO_LONG, max_bytes=2048, style="flat 2D")
    assert "at most 2048 bytes" in too_long[1][1]
    assert "Stay under 2048 UTF-8 bytes" in too_long[1][1]
    assert "flat 2D" in too_long[1][1]

    policy = revise.build_prompt("p", ErrorCode.CONTENT_POLICY, max_bytes=None, style="s")[1][1]
    assert "content filter" in policy and "UTF-8 bytes" not in policy

    other = revise.build_prompt("p", None, max_bytes=2048, style="s")[1][1]
    assert "self-contained description" in other


def test_revise_run_uses_injected_call():
    seen = {}

    def fake_call(*, model, messages, schema, **kw):
        seen["schema"] = schema
        return {"prompt": "calmer", "notes": "softened the action"}

    out = revise.run("draft", ErrorCode.CONTENT_POLICY, max_bytes=2048, style="s", call=fake_call)
    assert seen["schema"] is PromptRevision
    assert out == PromptRevision(prompt="calmer", notes="softened the action")


def _pkg() -> ProductionPackage:
    return ProductionPackage(
        project_id="p1",
        meta=Meta(
            title="T", premise="P", target_duration_s=3, style="flat 2D",
            narration_voice_id="v", budget_usd=15.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, provider_hint="fal:flux-schnell", prompt="a tree"),
            Asset(
                node_id="shot_a", type=AssetType.VIDEO, depends_on=["ref_a"],
                reference_image_ids=["ref_a"], provider_hint="fal:pixverse-v6-i2v",
                spec={"duration_s": 3.0}, prompt="A tree sways [mock-fail:content_policy] in wind.",
            ),
            Asset(node_id="narration", type=AssetType.VOICEOVER, text="Hi.", spec={"voice_id": "v"}),
        ],
    )


def _run(scenario):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def wrapper():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            await state.save_package(_pkg(), approved=True, owner_id="user_a")
            await state.set_node_status(
                "p1", "shot_a", NodeStatus.DEAD_LETTERED, error="x", error_code="content_policy"
            )
            await scenario()
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


def test_suggest_in_mock_mode_strips_the_failure_token(monkeypatch):
    monkeypatch.setenv("MOCK", "true")

    async def scenario():
        out = await main.suggest_fix("p1", "shot_a", None)
        assert out.prompt == "A tree sways in wind."
        assert out.error_code is ErrorCode.CONTENT_POLICY
        assert out.max_bytes == 2048
        assert "MOCK" in out.notes

        drafted = await main.suggest_fix("p1", "shot_a", main.SuggestRequest(prompt="Mine [mock-fail:timeout]"))
        assert drafted.prompt == "Mine"

        # Suggest never writes.
        stored = await state.get_package("p1")
        assert "[mock-fail:content_policy]" in stored.asset_by_id("shot_a").prompt

    _run(scenario)


def test_suggest_real_path_fits_and_normalizes_the_revision(monkeypatch):
    monkeypatch.setattr(main, "use_mock", lambda: False)
    calls = []

    def fake_run(prompt, code, *, max_bytes, style):
        calls.append((prompt, code, max_bytes, style))
        return PromptRevision(prompt="A tree sways " + chr(0x2014) + " gently.", notes="calmer")

    monkeypatch.setattr(main.revise, "run", fake_run)

    async def scenario():
        out = await main.suggest_fix("p1", "shot_a", None)
        assert out.prompt == "A tree sways - gently."
        assert calls == [(
            "A tree sways [mock-fail:content_policy] in wind.",
            ErrorCode.CONTENT_POLICY, 2048, "flat 2D",
        )]

    _run(scenario)


def test_suggest_llm_failure_is_502(monkeypatch):
    monkeypatch.setattr(main, "use_mock", lambda: False)

    def boom(*args, **kwargs):
        raise RuntimeError("anthropic down")

    monkeypatch.setattr(main.revise, "run", boom)

    async def scenario():
        with pytest.raises(main.HTTPException) as exc:
            await main.suggest_fix("p1", "shot_a", None)
        assert exc.value.status_code == 502

    _run(scenario)


def test_suggest_rejects_voiceover_and_unknown_nodes(monkeypatch):
    monkeypatch.setenv("MOCK", "true")

    async def scenario():
        with pytest.raises(main.HTTPException) as exc:
            await main.suggest_fix("p1", "narration", None)
        assert exc.value.status_code == 422
        with pytest.raises(main.HTTPException) as exc:
            await main.suggest_fix("p1", "ghost", None)
        assert exc.value.status_code == 404

    _run(scenario)
