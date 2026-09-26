"""In-process $0 recovery: a shot fails, the run blocks, the user fixes the prompt and
retries it, and the run resumes to the compositor without re-rendering anything.

Drives the real daemon, the real worker task body and the real scheduler handlers
against one fakeredis, with the mock adapter honoring ``[mock-fail:<code>]``."""

from __future__ import annotations

import asyncio

import pytest
import state
from adapters import mock as mock_adapter
from schema import Asset, AssetType, Meta, ProductionPackage, strip_mock_failure
from tenacity import wait_none

from scheduler import daemon, main
from scheduler.celery_app import COMPOSITE_TASK, RENDER_TASK
from worker import render, tasks

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None

PID = "p_recover"
FAILING_PROMPT = "Wide shot, a heron takes off [mock-fail:content_policy] over the river."


def _package() -> ProductionPackage:
    return ProductionPackage(
        project_id=PID,
        meta=Meta(
            title="Recover", premise="P", target_duration_s=6, style="flat 2D",
            narration_voice_id="v", budget_usd=15.0,
        ),
        assets=[
            Asset(node_id="ref", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                  prompt="A river at dawn.", estimated_cost_usd=0.03),
            Asset(node_id="shot_a", type=AssetType.VIDEO, depends_on=["ref"],
                  reference_image_ids=["ref"], provider_hint="fal:pixverse-v6-i2v",
                  spec={"duration_s": 3.0}, prompt=FAILING_PROMPT, estimated_cost_usd=0.1),
            Asset(node_id="shot_b", type=AssetType.VIDEO, depends_on=["ref", "shot_a"],
                  reference_image_ids=["ref"], provider_hint="fal:pixverse-v6-i2v",
                  spec={"duration_s": 3.0}, prompt="The heron lands.", estimated_cost_usd=0.1),
            Asset(node_id="narration", type=AssetType.VOICEOVER,
                  provider_hint="elevenlabs:flash-v2.5", text="The river wakes.",
                  spec={"voice_id": "v"}, estimated_cost_usd=0.2),
        ],
    )


class _NoLimitBucket:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def acquire(self, tokens: int = 1) -> None:
        return None


class _NoStorage:
    pass


@pytest.fixture
def fast_mock(monkeypatch):
    for kind, (_, cost) in list(mock_adapter._PROFILES.items()):
        # Not 0: expovariate(1/0) divides by zero.
        monkeypatch.setitem(mock_adapter._PROFILES, kind, (0.001, cost))
    monkeypatch.setattr(render, "_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(render, "RETRY_WAIT", wait_none())
    monkeypatch.setattr(render, "TokenBucket", _NoLimitBucket)
    monkeypatch.setattr(render, "Storage", _NoStorage)


def test_failed_shot_is_fixed_and_retried_in_place(fast_mock, monkeypatch):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    sends: list[tuple[str, list]] = []

    def fake_send_task(name, args=None, queue=None, **_):
        sends.append((name, args))

    monkeypatch.setattr(daemon.celery_app, "send_task", fake_send_task)

    handled = 0

    async def drain() -> None:
        """Tick the daemon and run whatever it sends, until it sends nothing new."""
        nonlocal handled
        while True:
            async for package in state.iter_approved_packages():
                await daemon._advance(package)
            new = sends[handled:]
            if not new:
                return
            handled = len(sends)
            for name, args in new:
                if name == RENDER_TASK:
                    await tasks.execute(*args)

    async def scenario() -> None:
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        daemon.use_budget_client(client)
        monkeypatch.setattr(render.redis, "from_url", lambda *a, **k: client)
        try:
            await state.save_package(_package(), approved=True, owner_id="u")
            await drain()

            assert await state.get_project_phase(PID) == state.PHASE_BLOCKED
            shot_a = await state.get_node(PID, "shot_a")
            assert shot_a["status"] == "dead-lettered"
            assert shot_a["error_code"] == "content_policy"
            frame = await main._status_event(PID)
            assert frame["nodes"]["shot_b"]["blocked_by"] == ["shot_a"]
            rendered_before = [args[1] for name, args in sends if name == RENDER_TASK]

            await main.edit_node(PID, "shot_a", main.NodeEdit(prompt=strip_mock_failure(FAILING_PROMPT)))
            await main.retry(PID, main.RetryRequest(node_ids=["shot_a"]))
            sends_before_retry = len(sends)
            await drain()

            assert await state.get_project_phase(PID) == state.PHASE_COMPOSITING
            assert [n for n, _ in sends].count(COMPOSITE_TASK) == 1
            rerendered = [args[1] for name, args in sends[sends_before_retry:] if name == RENDER_TASK]
            assert sorted(rerendered) == ["shot_a", "shot_b"]
            assert set(rendered_before) == {"ref", "narration", "shot_a"}

            costs = {kind: cost for kind, (_, cost) in mock_adapter._PROFILES.items()}
            expected = costs["image"] + 2 * costs["video"] + costs["voiceover"]
            assert await state.get_cost(PID) == pytest.approx(expected)
            assert (await state.get_node(PID, "shot_a"))["attempts"] == "2"
        finally:
            state.use_client(None)
            daemon.use_budget_client(None)

    asyncio.run(scenario())
