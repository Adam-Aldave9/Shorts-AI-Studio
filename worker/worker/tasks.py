"""The render task — one DAG node, end to end (spec §6.3).

  1. acquire a rate-limit token for the target provider
  2. submit to the provider via the adapter (or mock mode)
  3. poll/await completion
  4. download the asset to object storage
  5. report cost actuals and node status
  6. release the token

Retries use tenacity with exponential backoff + jitter; permanent failures are
dead-lettered (spec §6.6).
"""

from __future__ import annotations

import asyncio
import logging
import os

import redis.asyncio as redis
from adapters import ProviderError, get_adapter
from adapters.registry import provider_of
from celery import shared_task
from rate_limiter import TokenBucket
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger("worker.render")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Per-provider bucket sizing (capacity, refill/sec). Tune to real provider limits.
_BUCKETS = {
    "fal": (10, 2.0),
    "elevenlabs": (5, 1.0),
}


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.transient


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential_jitter(initial=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _generate(provider_hint: str, payload: dict) -> tuple[str, float]:
    provider = provider_of(provider_hint)
    model = provider_hint.split(":", 1)[1] if ":" in provider_hint else ""
    client = redis.from_url(REDIS_URL)
    capacity, refill = _BUCKETS.get(provider, (5, 1.0))
    bucket = TokenBucket(client, provider, capacity=capacity, refill_per_sec=refill)

    await bucket.acquire(1)
    adapter = get_adapter(provider_hint)
    handle = await adapter.submit(model, payload)
    result = await adapter.poll(handle)
    while not result.done:
        await asyncio.sleep(1.0)
        result = await adapter.poll(handle)
    # TODO(week1): download result.asset_url into MinIO/S3 (boto3).
    return result.asset_url, result.cost_usd


@shared_task(name="worker.render_node", bind=True, queue="render")
def render_node(self, project_id: str, node_id: str) -> dict:
    """Celery entrypoint. Resolves the node from state, renders it, reports back."""
    log.info("render project=%s node=%s", project_id, node_id)
    # TODO(week2): load the asset spec from Postgres/Redis state.
    payload = {"asset_type": "image", "node_id": node_id, "project_id": project_id}
    provider_hint = "fal:flux-schnell"

    try:
        asset_url, cost = asyncio.run(_generate(provider_hint, payload))
    except ProviderError as exc:
        if not exc.transient:
            log.error("dead-letter node=%s: %s", node_id, exc)
            return {"node_id": node_id, "status": "dead-lettered", "error": str(exc)}
        raise
    # TODO(week2): write status=succeeded + actual cost back to state stores.
    return {"node_id": node_id, "status": "succeeded", "asset_url": asset_url, "cost_usd": cost}
