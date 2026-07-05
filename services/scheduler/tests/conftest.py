"""Test setup: ``scheduler.main`` now imports ``auth.config``, which requires
``SECRET_KEY`` at import time — set it (and force the Redis-only user path) before any
test module imports the app."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.pop("POSTGRES_URL", None)
