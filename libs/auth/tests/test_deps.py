"""Ownership dependency: a caller may only touch packages they own (fakeredis)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import state
from auth import deps

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover
    fakeredis_aio = None


def _request_for(user_id: str | None) -> Request:
    """A minimal ASGI request whose state carries (or omits) an authenticated user."""
    scope = {"type": "http", "headers": [], "state": {}}
    if user_id is not None:
        scope["state"]["user_id"] = user_id
    return Request(scope)


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


def test_owner_passes_foreign_and_missing_are_404():
    async def scenario():
        # stamp ownership of p_a to user_a (owner index only; no package body needed)
        await state.store._redis().set("project:p_a:owner", "user_a")

        assert await deps.owned_package("p_a", _request_for("user_a")) == "p_a"

        with pytest.raises(HTTPException) as foreign:
            await deps.owned_package("p_a", _request_for("user_b"))
        assert foreign.value.status_code == 404  # 404, not 403 (no existence leak)

        with pytest.raises(HTTPException) as missing:
            await deps.owned_package("nope", _request_for("user_a"))
        assert missing.value.status_code == 404

    _run(scenario)


def test_current_user_id_requires_authenticated_state():
    with pytest.raises(HTTPException) as exc:
        deps.current_user_id(_request_for(None))
    assert exc.value.status_code == 401
    assert deps.current_user_id(_request_for("user_x")) == "user_x"
