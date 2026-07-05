"""Account operations — the policy layer between the HTTP router and persistence.

Owns username normalization, password hashing/verification, the user-enumeration
defense (dummy-hash verify for unknown users), and rehash-on-login. Persistence is
delegated to :mod:`state` (Redis hot path + Postgres durability). Failures surface as
two typed exceptions the router maps to 409 / 401.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import state

from auth.models import UserOut, normalize_username
from auth.passwords import (
    DUMMY_HASH,
    hash_password,
    needs_rehash,
    verify_password,
)

# Re-export so callers catch a single auth-layer error type.
UserExistsError = state.UserExistsError


class InvalidCredentials(Exception):
    """Login failed — wrong username *or* password. Deliberately undifferentiated so
    the caller can return one generic message (no user enumeration)."""


def _new_user_id() -> str:
    return f"u_{secrets.token_urlsafe(16)}"


async def register_user(username: str, password: str) -> UserOut:
    """Create an account. ``username`` is normalized for identity; the original
    casing is kept as the display name. Raises :class:`UserExistsError` if taken."""
    normalized = normalize_username(username)
    display = username.strip()
    user_id = _new_user_id()
    password_hash = hash_password(password)
    created_at = datetime.now(timezone.utc).isoformat()
    await state.create_user(user_id, normalized, display, password_hash, created_at)
    return UserOut(user_id=user_id, username=display)


async def authenticate(username: str, password: str) -> UserOut:
    """Verify credentials and return the account, else raise
    :class:`InvalidCredentials`.

    For an unknown username we still run a full verify against :data:`DUMMY_HASH`, so
    the response time does not reveal whether the username exists."""
    normalized = normalize_username(username)
    user = await state.get_user_by_username(normalized)
    if user is None:
        verify_password(DUMMY_HASH, password)  # burn equivalent CPU (timing parity)
        raise InvalidCredentials()
    if not verify_password(user["password_hash"], password):
        raise InvalidCredentials()
    # Transparently upgrade the stored hash if our params have since hardened.
    if needs_rehash(user["password_hash"]):
        await state.set_user_password_hash(user["user_id"], hash_password(password))
    return UserOut(user_id=user["user_id"], username=user["display_username"])


async def get_user(user_id: str) -> UserOut | None:
    """Load the public view of an account by id (session bootstrap / ``/auth/me``)."""
    user = await state.get_user_by_id(user_id)
    if user is None:
        return None
    return UserOut(user_id=user["user_id"], username=user["display_username"])
