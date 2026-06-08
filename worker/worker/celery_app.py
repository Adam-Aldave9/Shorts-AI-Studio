"""Celery app for the worker (spec §6.2). Visibility timeout is calibrated to the
longest realistic task — video generation can take minutes."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("afp", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 1800},
    task_default_queue="render",
)

# Import side-effect: registers tasks under their decorated names.
from worker import tasks  # noqa: E402,F401
