"""Test setup: ``planning.main`` now imports ``auth.config``, which requires
``SECRET_KEY`` at import time — set it (and force the Redis-only user path) before any
test module imports the app."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.pop("POSTGRES_URL", None)

# The mock planning walk dwells on each stage so the progress UI is demoable; at the
# default 1.5s/stage the job-level tests would blow their 5s timeout.
os.environ["MOCK_PLAN_DELAY_S"] = "0"
