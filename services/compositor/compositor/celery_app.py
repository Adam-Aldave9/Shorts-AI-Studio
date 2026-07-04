"""Celery app for the compositor — its own dedicated queue so the terminal render
never competes with generation tasks for a worker slot (spec §2.4, §8)."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("afp", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="composite",
)

from compositor import tasks  # noqa: E402,F401
