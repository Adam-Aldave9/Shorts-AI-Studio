"""Per-provider token bucket in Redis, refilled lazily by a server-side Lua script
so the check-and-decrement is atomic across the whole fleet (spec §6.5)."""

from __future__ import annotations

import time

import redis.asyncio as redis

# KEYS[1] = bucket key. ARGV = capacity, refill_per_sec, now, requested.
# Stores {tokens, ts} in a hash; refills based on elapsed time, then tries to
# take `requested` tokens. Returns 1 on success, 0 if not enough tokens.
_ACQUIRE_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local want = tonumber(ARGV[4])
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * refill)
local ok = 0
if tokens >= want then tokens = tokens - want; ok = 1 end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 3600)
return ok
"""


class TokenBucket:
    def __init__(
        self,
        client: redis.Redis,
        provider: str,
        *,
        capacity: int,
        refill_per_sec: float,
    ) -> None:
        self._client = client
        self._key = f"ratelimit:{provider}"
        self._capacity = capacity
        self._refill = refill_per_sec
        self._script = client.register_script(_ACQUIRE_LUA)

    async def try_acquire(self, tokens: int = 1) -> bool:
        ok = await self._script(
            keys=[self._key],
            args=[self._capacity, self._refill, time.time(), tokens],
        )
        return bool(ok)

    async def acquire(self, tokens: int = 1, *, poll_interval: float = 0.25) -> None:
        """Block (async) until ``tokens`` are available."""
        import asyncio

        while not await self.try_acquire(tokens):
            await asyncio.sleep(poll_interval)
