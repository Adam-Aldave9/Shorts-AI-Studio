"""The adapter contract. Every provider implements the same three verbs so the
scheduler and worker never branch on provider identity (spec §6.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Raised by an adapter. ``transient`` controls retry vs dead-letter."""

    def __init__(self, message: str, *, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class JobHandle:
    """Opaque reference returned by ``submit`` and passed back to ``poll``."""

    provider: str
    job_id: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobResult:
    asset_url: str
    cost_usd: float
    done: bool = True
    # Some providers (ElevenLabs TTS) return the asset inline as bytes rather than
    # a fetchable URL. Optional + additive so URL-returning adapters are unchanged
    # and adapters stay free of any storage knowledge (spec §6.4).
    content: bytes | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Adapter(Protocol):
    """Uniform interface over a media-generation provider."""

    name: str

    async def submit(self, model: str, payload: dict[str, Any]) -> JobHandle:
        """Validate the payload and start a generation job."""
        ...

    async def poll(self, handle: JobHandle) -> JobResult:
        """Return the current status; ``done=False`` means keep polling."""
        ...

    async def fetch_result(self, handle: JobHandle) -> JobResult:
        """Return the terminal result (asset URL + cost)."""
        ...
