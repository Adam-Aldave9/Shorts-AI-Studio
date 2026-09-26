"""The render task — one DAG node, end to end (spec §6.3).

A thin Celery wrapper over the pure orchestration in :mod:`worker.render` (the
same pure-fn + thin-task split the compositor already uses). Retries live in
``render``; this layer only turns whatever ended the render into a terminal node
status, so every dispatched node lands somewhere and the daemon never waits forever.
"""

from __future__ import annotations

import asyncio
import logging

import state
from adapters import ProviderError
from celery import shared_task
from schema import ErrorCode, NodeStatus

from worker import render

log = logging.getLogger("worker.render")


def failure_fields(exc: BaseException) -> tuple[NodeStatus, dict[str, str | None]]:
    if isinstance(exc, ProviderError):
        status = NodeStatus.FAILED if exc.transient else NodeStatus.DEAD_LETTERED
        return status, {"error": str(exc), "error_code": exc.code.value, "error_detail": exc.detail}
    return NodeStatus.FAILED, {
        "error": "Unexpected error while rendering this node.",
        "error_code": ErrorCode.INTERNAL.value,
        "error_detail": f"{type(exc).__name__}: {exc}"[:500],
    }


async def execute(project_id: str, node_id: str) -> dict:
    try:
        cost = await render.render_node(project_id, node_id)
    except Exception as exc:
        if isinstance(exc, ProviderError):
            log.error("node=%s failed [%s]: %s", node_id, exc.code, exc)
        else:
            log.exception("node=%s crashed", node_id)
        status, fields = failure_fields(exc)
        await state.set_node_status(project_id, node_id, status, **fields)
        return {"node_id": node_id, "status": status.value, "error_code": fields["error_code"]}
    return {"node_id": node_id, "status": NodeStatus.SUCCEEDED.value, "cost_usd": cost}


@shared_task(name="worker.render_node", bind=True, queue="render")
def render_node(self, project_id: str, node_id: str) -> dict:
    """Celery entrypoint. Resolves the node from shared state, renders it, reports back."""
    log.info("render project=%s node=%s", project_id, node_id)
    return asyncio.run(execute(project_id, node_id))
