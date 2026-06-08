"""Adapter resolution. ``provider_hint`` on a node looks like ``fal:flux-pro`` or
``elevenlabs:multilingual-v3``; the part before the colon selects the adapter.
When ``MOCK=true`` every provider is transparently replaced by the mock."""

from __future__ import annotations

import os

from adapters.base import Adapter
from adapters.elevenlabs import ElevenLabsAdapter
from adapters.fal import FalAdapter
from adapters.mock import MockAdapter

_REAL = {
    "fal": FalAdapter,
    "elevenlabs": ElevenLabsAdapter,
}


def mock_enabled() -> bool:
    return os.environ.get("MOCK", "false").lower() in {"1", "true", "yes"}


def provider_of(hint: str) -> str:
    return hint.split(":", 1)[0]


def get_adapter(provider_hint: str) -> Adapter:
    provider = provider_of(provider_hint)
    if provider not in _REAL:
        raise ValueError(f"unknown provider {provider!r} in hint {provider_hint!r}")
    if mock_enabled():
        return MockAdapter(provider)
    return _REAL[provider]()
