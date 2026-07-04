"""Account policy: register / authenticate / enumeration defense (fakeredis)."""

from __future__ import annotations

import asyncio

import pytest

import state
from auth import users

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover
    fakeredis_aio = None

_PW = "a-good-long-password"


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


def test_register_normalizes_username_and_hides_hash():
    async def scenario():
        user = await users.register_user("Alice", _PW)
        assert user.username == "Alice"  # display casing preserved
        assert not hasattr(user, "password_hash")

        # stored under the normalized (lowercased) identity
        stored = await state.get_user_by_username("alice")
        assert stored["user_id"] == user.user_id
        assert stored["password_hash"].startswith("$argon2id$")

    _run(scenario)


def test_register_duplicate_is_case_insensitive():
    async def scenario():
        await users.register_user("Alice", _PW)
        with pytest.raises(users.UserExistsError):
            await users.register_user("alice", _PW)  # same identity

    _run(scenario)


def test_authenticate_success_and_wrong_password():
    async def scenario():
        created = await users.register_user("bob", _PW)
        ok = await users.authenticate("BOB", _PW)  # case-insensitive login
        assert ok.user_id == created.user_id

        with pytest.raises(users.InvalidCredentials):
            await users.authenticate("bob", "wrong-password-xx")

    _run(scenario)


def test_authenticate_unknown_user_raises_invalid_credentials():
    async def scenario():
        # No such user: still raises the same generic error (no enumeration).
        with pytest.raises(users.InvalidCredentials):
            await users.authenticate("ghost", _PW)

    _run(scenario)


def test_get_user_by_id():
    async def scenario():
        created = await users.register_user("carol", _PW)
        got = await users.get_user(created.user_id)
        assert got is not None and got.username == "carol"
        assert await users.get_user("nope") is None

    _run(scenario)
