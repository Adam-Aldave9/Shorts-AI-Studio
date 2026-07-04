"""The composite task (spec §8): a thin Celery wrapper over the pure render logic
in :mod:`compositor.render`. The actual FFmpeg work lives there so the
sequential driver can call it directly, bypassing Celery entirely.

This entrypoint is wired into shared state: the daemon fires it exactly once
when every node has succeeded (see ``scheduler.daemon``). It loads the *hydrated*
package (every ``asset_url`` populated by the workers) from :mod:`state`, renders
the final cut, and records the result + phase back to state so the SSE stream and
the next daemon tick observe a ``complete`` run.
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task
from storage import Storage

import state
from compositor.render import composite_package  # noqa: F401  (re-exported for callers)

log = logging.getLogger("compositor")


@shared_task(name="compositor.composite", bind=True, queue="composite")
def composite(self, project_id: str) -> dict:
    log.info("composite project=%s", project_id)
    pkg = asyncio.run(state.get_package(project_id))
    if pkg is None:
        raise RuntimeError(f"package {project_id!r} not found in state")

    # composite_package is synchronous (subprocess FFmpeg); run it outside any loop.
    url = composite_package(pkg, Storage())

    asyncio.run(_finalize(project_id, url))
    log.info("composite project=%s complete -> %s", project_id, url)
    return {"project_id": project_id, "final_url": url}


async def _finalize(project_id: str, url: str) -> None:
    """Record the final cut and flip the run to ``complete`` in one place."""
    await state.set_final_url(project_id, url)
    await state.set_project_phase(project_id, state.PHASE_COMPLETE)
