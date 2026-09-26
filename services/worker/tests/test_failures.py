"""No-network checks for the worker's failure handling: pre-flight, per-step
retries, the poll deadline, and the terminal status every failure maps to."""

from __future__ import annotations

import asyncio

import pytest
from adapters import JobHandle, JobResult, ProviderError
from schema import Asset, AssetType, ErrorCode, NodeStatus
from tenacity import wait_none

from worker import render
from worker.tasks import failure_fields


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr(render, "RETRY_WAIT", wait_none())


def _shot(prompt: str) -> Asset:
    return Asset(node_id="shot_a", type=AssetType.VIDEO, provider_hint="fal:pixverse-v6-i2v", prompt=prompt)


class _FakeAdapter:
    def __init__(self, polls: list) -> None:
        self.polls = list(polls)
        self.submits = 0
        self.polled: list[JobHandle] = []

    async def submit(self, model, payload) -> JobHandle:
        self.submits += 1
        return JobHandle(provider="fake", job_id=f"job_{self.submits}")

    async def poll(self, handle: JobHandle) -> JobResult:
        self.polled.append(handle)
        outcome = self.polls.pop(0) if self.polls else JobResult(asset_url="", cost_usd=0.0, done=False)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_prompt_budget_preflight_rejects_before_submit():
    with pytest.raises(ProviderError) as ei:
        render.check_prompt_budget(_shot("a" * 2049))
    assert ei.value.code is ErrorCode.PROMPT_TOO_LONG
    assert ei.value.transient is False
    render.check_prompt_budget(_shot("a" * 2048))
    render.check_prompt_budget(Asset(node_id="r", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                                     prompt="a" * 5000))


def test_transient_poll_error_repolls_the_same_job():
    adapter = _FakeAdapter([
        ProviderError("blip", code=ErrorCode.PROVIDER_UNAVAILABLE),
        JobResult(asset_url="https://x/v.mp4", cost_usd=0.1),
    ])

    async def scenario():
        handle = await render.with_retries(lambda: adapter.submit("m", {}))
        return await render.poll_until_done(adapter, handle, interval=0)

    result = asyncio.run(scenario())
    assert result.asset_url == "https://x/v.mp4"
    assert adapter.submits == 1
    assert [h.job_id for h in adapter.polled] == ["job_1", "job_1"]


def test_permanent_poll_error_is_not_retried():
    adapter = _FakeAdapter([ProviderError("nope", code=ErrorCode.CONTENT_POLICY)])
    handle = JobHandle(provider="fake", job_id="job_1")
    with pytest.raises(ProviderError) as ei:
        asyncio.run(render.poll_until_done(adapter, handle, interval=0))
    assert ei.value.code is ErrorCode.CONTENT_POLICY
    assert len(adapter.polled) == 1


def test_transient_submit_retries_three_times_then_raises():
    calls = 0

    async def submit():
        nonlocal calls
        calls += 1
        raise ProviderError("busy", code=ErrorCode.RATE_LIMITED)

    with pytest.raises(ProviderError):
        asyncio.run(render.with_retries(submit))
    assert calls == 3


def test_poll_deadline_raises_timeout():
    adapter = _FakeAdapter([])
    ticks = iter([0.0, 10.0, 25.0, 31.0])
    handle = JobHandle(provider="fake", job_id="job_1")
    with pytest.raises(ProviderError) as ei:
        asyncio.run(render.poll_until_done(adapter, handle, interval=0, deadline_s=30,
                                           clock=lambda: next(ticks)))
    assert ei.value.code is ErrorCode.TIMEOUT
    assert ei.value.transient is False
    assert len(adapter.polled) == 3


def test_poll_deadline_stays_below_celery_redelivery():
    assert render.POLL_DEADLINE_S < 1800


def test_failure_fields_for_provider_errors():
    status, fields = failure_fields(ProviderError("flagged", code=ErrorCode.CONTENT_POLICY, detail="d"))
    assert status is NodeStatus.DEAD_LETTERED
    assert fields == {"error": "flagged", "error_code": "content_policy", "error_detail": "d"}

    status, fields = failure_fields(ProviderError("busy", code=ErrorCode.PROVIDER_UNAVAILABLE))
    assert status is NodeStatus.FAILED
    assert fields["error_code"] == "provider_unavailable"


def test_failure_fields_for_unexpected_exceptions():
    status, fields = failure_fields(KeyError("status_url"))
    assert status is NodeStatus.FAILED
    assert fields["error_code"] == "internal"
    assert fields["error"] == "Unexpected error while rendering this node."
    assert fields["error_detail"] == "KeyError: 'status_url'"
