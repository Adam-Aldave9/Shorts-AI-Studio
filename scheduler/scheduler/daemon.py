"""The DAG-walker daemon (spec §6.1).

Loop: load approved packages, find ready nodes, enqueue them onto Celery, advance
node state as workers report back, and trigger the compositor when the timeline's
assets are all ``succeeded``. Runs as an asyncio task inside the FastAPI process.
"""

from __future__ import annotations

import asyncio
import logging

from scheduler.celery_app import (
    COMPOSITE_TASK,
    COMPOSITOR_QUEUE,
    RENDER_TASK,
    WORKER_QUEUE,
    celery_app,
)
from scheduler.dag import Dag
from scheduler.state import iter_approved_packages, save_package

log = logging.getLogger("scheduler.daemon")

POLL_INTERVAL_S = 1.0


async def _advance(dag: Dag) -> None:
    for node_id in dag.ready_nodes():
        asset = dag.package.asset_by_id(node_id)
        assert asset is not None
        log.info("enqueue node=%s project=%s", node_id, dag.package.project_id)
        celery_app.send_task(
            RENDER_TASK,
            args=[dag.package.project_id, node_id],
            queue=WORKER_QUEUE,
        )
        asset.status = asset.status.DISPATCHED

    if dag.is_complete():
        log.info("project=%s all nodes terminal -> compositor", dag.package.project_id)
        celery_app.send_task(
            COMPOSITE_TASK,
            args=[dag.package.project_id],
            queue=COMPOSITOR_QUEUE,
        )

    await save_package(dag.package)


async def run_daemon(stop: asyncio.Event) -> None:
    log.info("DAG-walker daemon started")
    while not stop.is_set():
        try:
            async for package in iter_approved_packages():
                await _advance(Dag(package))
        except Exception:  # keep the daemon alive; surface in logs
            log.exception("daemon tick failed")
        await asyncio.sleep(POLL_INTERVAL_S)
    log.info("DAG-walker daemon stopped")
