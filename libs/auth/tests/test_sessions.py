"""Opaque Redis session store (fakeredis)."""

from __future__ import annotations

import asyncio
import time

import pytest

import state
from auth import sessions
from auth.config import SESSION_IDLE_TTL

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


def test_create_get_and_touch():
    async def scenario():
        sid, csrf_token = await sessions.create_session("u_1")
        assert sid and csrf_token

        data = await sessions.get_session(sid)
        assert data["user_id"] == "u_1"
        assert data["csrf"] == csrf_token

        touched = await sessions.touch_session(sid)
        assert touched is not None
        # idle TTL is (re)applied on touch
        ttl = await state.store._redis().ttl(f"session:{sid}")
        assert 0 < ttl <= SESSION_IDLE_TTL

    _run(scenario)


def test_absolute_ttl_destroys_session():
    async def scenario():
        sid, _ = await sessions.create_session("u_1")
        # backdate created_at well past the absolute cap
        r = state.store._redis()
        await r.hset(f"session:{sid}", "created_at", time.time() - 10**9)
        assert await sessions.touch_session(sid) is None
        assert await sessions.get_session(sid) is None  # cleaned up

    _run(scenario)


def test_touch_unknown_session_returns_none():
    async def scenario():
        assert await sessions.touch_session("nope") is None

    _run(scenario)


def test_destroy_session_and_destroy_user_sessions():
    async def scenario():
        s1, _ = await sessions.create_session("u_1")
        s2, _ = await sessions.create_session("u_1")
        s_other, _ = await sessions.create_session("u_2")

        await sessions.destroy_session(s1)
        assert await sessions.get_session(s1) is None
        assert await sessions.get_session(s2) is not None

        # revoke everything for u_1; u_2 untouched
        await sessions.destroy_user_sessions("u_1")
        assert await sessions.get_session(s2) is None
        assert await sessions.get_session(s_other) is not None

    _run(scenario)
