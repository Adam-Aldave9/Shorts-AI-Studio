"""Login/register throttling (fakeredis-backed token buckets)."""

from __future__ import annotations

import asyncio

import pytest

import state
from auth import ratelimit

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover
    fakeredis_aio = None


def _run(scenario):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def wrapper():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            await scenario()
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


def test_login_locks_out_after_burst():
    async def scenario():
        # per-username capacity is 5; the 6th consecutive attempt is throttled
        allowed = [await ratelimit.allow_login("mallory", "10.0.0.1") for _ in range(6)]
        assert allowed[:5] == [True] * 5
        assert allowed[5] is False

    _run(scenario)


def test_login_buckets_are_per_username():
    async def scenario():
        for _ in range(5):
            await ratelimit.allow_login("userA", "10.0.0.9")
        assert await ratelimit.allow_login("userA", "10.0.0.9") is False
        # a different username on the same IP still has its own username budget
        assert await ratelimit.allow_login("userB", "10.0.0.9") is True

    _run(scenario)


def test_register_locks_out_after_burst():
    async def scenario():
        allowed = [await ratelimit.allow_register("10.0.0.2") for _ in range(6)]
        assert allowed[:5] == [True] * 5
        assert allowed[5] is False

    _run(scenario)
