"""Opaque server-side session store over Redis.

The session id is a cryptographically random, opaque token; **all** session data
lives server-side in a Redis hash keyed ``session:{sid}`` (never in the cookie), so
sessions are trivially revocable (delete the key) and carry no client-forgeable
state. Two TTLs bound a session: a **sliding idle** window (reset on every touch) and
an **absolute** cap checked against ``created_at``.

Redis access reuses :mod:`state.store`'s per-loop client so the whole stack shares
one connection pool — and so a test that injects fakeredis via ``state.use_client``
transparently backs sessions too.
"""

from __future__ import annotations

import secrets
import time

import redis.asyncio as redis
from state import store as _state_store

from auth.config import SESSION_ABSOLUTE_TTL, SESSION_IDLE_TTL


def _redis() -> redis.Redis:
    # Shared with the rest of the app (and honors test client injection).
    return _state_store._redis()


def _session_key(sid: str) -> str:
    return f"session:{sid}"


def _user_sessions_key(user_id: str) -> str:
    return f"sessions:user:{user_id}"


async def create_session(user_id: str) -> tuple[str, str]:
    """Mint a fresh session for ``user_id`` and return ``(session_id, csrf_token)``.

    A new id is always minted (never reused), which is the session-fixation defense:
    the id a user holds pre-login can never become their authenticated id."""
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = time.time()
    r = _redis()
    await r.hset(
        _session_key(sid),
        mapping={
            "user_id": user_id,
            "csrf": csrf,
            "created_at": now,
            "last_seen": now,
        },
    )
    await r.expire(_session_key(sid), SESSION_IDLE_TTL)
    # Index the session under its user so a password change / "log out everywhere"
    # can revoke all of them without scanning the keyspace.
    await r.sadd(_user_sessions_key(user_id), sid)
    await r.expire(_user_sessions_key(user_id), SESSION_ABSOLUTE_TTL)
    return sid, csrf


async def get_session(sid: str) -> dict[str, str] | None:
    """Return the raw session hash, or ``None`` if it is absent/expired."""
    data = await _redis().hgetall(_session_key(sid))
    return data or None


async def touch_session(sid: str) -> dict[str, str] | None:
    """Validate + refresh a session on each authenticated request.

    Enforces the absolute cap (destroy + ``None`` once ``created_at`` is older than
    :data:`SESSION_ABSOLUTE_TTL`), then slides the idle TTL forward and stamps
    ``last_seen``. Returns the session hash when still valid, else ``None``."""
    r = _redis()
    data = await r.hgetall(_session_key(sid))
    if not data:
        return None
    now = time.time()
    try:
        created_at = float(data.get("created_at", 0.0))
    except (TypeError, ValueError):
        created_at = 0.0
    if now - created_at > SESSION_ABSOLUTE_TTL:
        await destroy_session(sid)
        return None
    await r.hset(_session_key(sid), "last_seen", now)
    await r.expire(_session_key(sid), SESSION_IDLE_TTL)
    data["last_seen"] = str(now)
    return data


async def destroy_session(sid: str) -> None:
    """Revoke a single session (logout). Idempotent."""
    r = _redis()
    data = await r.hgetall(_session_key(sid))
    await r.delete(_session_key(sid))
    user_id = data.get("user_id") if data else None
    if user_id:
        await r.srem(_user_sessions_key(user_id), sid)


async def destroy_user_sessions(user_id: str) -> None:
    """Revoke every session a user holds (password change / global logout)."""
    r = _redis()
    key = _user_sessions_key(user_id)
    sids = await r.smembers(key)
    for sid in sids:
        await r.delete(_session_key(sid))
    await r.delete(key)
