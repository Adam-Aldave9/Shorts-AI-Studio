"""Test setup: importing ``scheduler.main`` needs ``SECRET_KEY``, and the recovery
end-to-end test runs the whole pipeline in MOCK mode, so set both before any import."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.pop("POSTGRES_URL", None)
os.environ["MOCK"] = "true"
