"""Mock mode — a first-class feature (spec §7). Validates the payload, sleeps for
a Poisson-distributed duration matching real provider latencies, and returns a
placeholder asset URL with a realistic fake cost. This is what makes the
throughput experiments free."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from adapters.base import Adapter, JobHandle, JobResult, ProviderError

# Mean latency (seconds) and unit price per model family, used to make mock runs
# behave like the real provider tier for scheduling/rate-limit experiments.
_PROFILES: dict[str, tuple[float, float]] = {
    "image": (8.0, 0.04),
    "video": (40.0, 0.10),
    "voiceover": (6.0, 0.40),
}

_PLACEHOLDERS = {
    "image": "s3://film-assets/_mock/placeholder.png",
    "video": "s3://film-assets/_mock/placeholder.mp4",
    "voiceover": "s3://film-assets/_mock/placeholder.mp3",
}


class MockAdapter:
    """Stands in for any provider when ``MOCK=true``."""

    def __init__(self, name: str) -> None:
        self.name = name

    def _kind(self, payload: dict[str, Any]) -> str:
        kind = payload.get("asset_type", "image")
        if kind not in _PROFILES:
            raise ProviderError(f"unknown asset_type {kind!r}", transient=False)
        return kind

    async def submit(self, model: str, payload: dict[str, Any]) -> JobHandle:
        kind = self._kind(payload)
        return JobHandle(provider=self.name, job_id=f"mock_{random.randint(0, 1 << 30)}",
                         meta={"kind": kind, "model": model})

    async def poll(self, handle: JobHandle) -> JobResult:
        return await self.fetch_result(handle)

    async def fetch_result(self, handle: JobHandle) -> JobResult:
        kind = handle.meta["kind"]
        mean_latency, unit_cost = _PROFILES[kind]
        # Poisson-ish jitter around the mean to mimic real provider variance.
        await asyncio.sleep(random.expovariate(1.0 / mean_latency))
        return JobResult(asset_url=_PLACEHOLDERS[kind], cost_usd=unit_cost)


# Satisfy the Protocol at type-check time without importing it at runtime.
_: Adapter = MockAdapter("_typecheck")
