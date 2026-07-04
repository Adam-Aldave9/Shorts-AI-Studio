"""Celery client handle used by the scheduler to enqueue ready nodes onto the
worker and compositor queues. The scheduler only *sends* tasks; it never runs
them (spec §3, §6.2)."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("afp", broker=REDIS_URL, backend=REDIS_URL)

# Task names are referenced by string so the scheduler need not import worker code.
RENDER_TASK = "worker.render_node"
COMPOSITE_TASK = "compositor.composite"
WORKER_QUEUE = "render"
COMPOSITOR_QUEUE = "composite"
