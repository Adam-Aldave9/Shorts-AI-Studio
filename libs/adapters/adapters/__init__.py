"""Provider adapters: a uniform (submit, poll, fetch_result) interface over
heterogeneous third-party APIs, plus a first-class mock mode (spec §6.4, §7)."""

from adapters.base import Adapter, JobHandle, JobResult, ProviderError
from adapters.registry import get_adapter

__all__ = [
    "Adapter",
    "JobHandle",
    "JobResult",
    "ProviderError",
    "get_adapter",
]
