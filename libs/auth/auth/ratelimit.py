"""Brute-force throttling for the auth endpoints.

A thin wrapper over the shared ``afp-rate-limiter`` ``TokenBucket`` (Redis + Lua,
atomic across the fleet). Login is limited on **both** axes — per-username (stops a
password-spray against one account) and per-IP (stops one host hammering many
accounts) — and registration is limited per-IP. Each attempt consumes a token; an
empty bucket refills slowly, which is the lockout/backoff.
"""

from __future__ import annotations

from rate_limiter.token_bucket import TokenBucket
from state import store as _state_store

# (capacity, refill tokens/sec). Capacity is the burst before lockout; refill is how
# fast attempts are handed back (1/60s = one more try per minute).
_LOGIN_USER = (5, 1.0 / 60.0)
_LOGIN_IP = (20, 1.0 / 30.0)
_REGISTER_IP = (5, 1.0 / 300.0)


def _bucket(provider: str, capacity: int, refill: float) -> TokenBucket:
    return TokenBucket(
        _state_store._redis(), provider, capacity=capacity, refill_per_sec=refill
    )


async def allow_login(username: str, ip: str) -> bool:
    """Consume one login attempt for this username and IP; ``False`` when either
    bucket is empty (caller returns 429)."""
    user_ok = await _bucket(f"login:{username}", *_LOGIN_USER).try_acquire()
    ip_ok = await _bucket(f"login-ip:{ip}", *_LOGIN_IP).try_acquire()
    return user_ok and ip_ok


async def allow_register(ip: str) -> bool:
    """Consume one registration attempt for this IP; ``False`` when throttled."""
    return await _bucket(f"register-ip:{ip}", *_REGISTER_IP).try_acquire()
