"""The composite task (spec §8): a thin Celery wrapper over the pure render logic
in :mod:`compositor.render`. The actual FFmpeg work lives there so the Phase 1
sequential driver can call it directly, bypassing Celery entirely."""

from __future__ import annotations

import logging

from celery import shared_task

from compositor.render import composite_package  # noqa: F401  (re-exported for callers)

log = logging.getLogger("compositor")


@shared_task(name="compositor.composite", bind=True, queue="composite")
def composite(self, project_id: str) -> dict:
    log.info("composite project=%s", project_id)
    # TODO(week2): load the ProductionPackage for `project_id` from Postgres state,
    # then `composite_package(pkg)`. The Phase 1 driver calls composite_package()
    # directly with an in-memory package, so this Celery entrypoint stays unused
    # until durable package state exists.
    raise NotImplementedError(
        "compositor.composite needs Phase 2 package state; "
        "Phase 1 calls compositor.render.composite_package() directly"
    )
