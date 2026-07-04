"""The render task — one DAG node, end to end (spec §6.3).

A thin Celery wrapper over the pure orchestration in :mod:`worker.render` (the
same pure-fn + thin-task split the compositor already uses). This layer owns only
what Celery needs: drive the async render via ``asyncio.run``, retry transient
provider failures with exponential backoff + jitter, dead-letter permanent ones
(spec §6.6), and bump the per-node attempt counter for observability/SSE.
"""

from __future__ import annotations

import asyncio
import logging

import state
from adapters import ProviderError
from celery import shared_task
from schema import NodeStatus
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from worker import render

log = logging.getLogger("worker.render")


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.transient


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential_jitter(initial=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _attempt(project_id: str, node_id: str) -> float:
    # One increment per try (including retries) so SSE can show progress/stragglers.
    await state.increment_attempts(project_id, node_id)
    return await render.render_node(project_id, node_id)


@shared_task(name="worker.render_node", bind=True, queue="render")
def render_node(self, project_id: str, node_id: str) -> dict:
    """Celery entrypoint. Resolves the node from shared state, renders it, reports back."""
    log.info("render project=%s node=%s", project_id, node_id)
    try:
        cost = asyncio.run(_attempt(project_id, node_id))
    except ProviderError as exc:
        # Permanent error, or transient retries exhausted: mark the node terminal so
        # the daemon stops waiting on it (and can surface blocked dependents).
        status = NodeStatus.DEAD_LETTERED if not exc.transient else NodeStatus.FAILED
        asyncio.run(state.set_node_status(project_id, node_id, status, error=str(exc)))
        log.error("node=%s -> %s: %s", node_id, status.value, exc)
        return {"node_id": node_id, "status": status.value, "error": str(exc)}
    return {"node_id": node_id, "status": NodeStatus.SUCCEEDED.value, "cost_usd": cost}
