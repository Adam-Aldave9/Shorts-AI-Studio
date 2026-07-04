"""Shared test setup for the auth lib.

``auth.config`` reads its constants at import time, so the required env must exist
before any ``auth`` module is imported — set it here (conftest is imported first).
Tests run Redis-backed pieces against fakeredis injected via ``state.use_client`` (no
``POSTGRES_URL`` -> the Redis-only user/session path), matching the repo's style.
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.pop("POSTGRES_URL", None)  # force the Redis-only branch in state

import pytest

import state

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


@pytest.fixture
def fake_state():
    """Wire a fresh fakeredis into the shared state layer for one test."""
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    client = fakeredis_aio.FakeRedis(decode_responses=True)
    state.use_client(client)
    try:
        yield client
    finally:
        state.use_client(None)
