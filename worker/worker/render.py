"""The render logic for one DAG node — pure, no Celery (spec §6.3).

This is the canonical per-node implementation: build the provider payload, acquire
a rate-limit token, submit/poll the adapter, archive the result to object storage,
record cost, and write live state. It is the same load-bearing logic the Phase 1
sequential driver ran (``harness/cli.py``), lifted here so the driver and the
Celery worker share one source of truth. The thin Celery wrapper in ``tasks.py``
adds retries, dead-lettering, and ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import redis.asyncio as redis
import state
from adapters import ProviderError, get_adapter
from adapters.registry import provider_of
from rate_limiter import CostTracker, TokenBucket
from schema import Meta, NodeStatus
from storage import Storage

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# How long to wait between status polls for async providers (fal). Mock mode
# completes on the first poll, so this only bites real runs.
_POLL_INTERVAL_S = 3.0

# Per-provider bucket sizing (capacity, refill/sec). Tune to real provider limits.
_BUCKETS = {
    "fal": (10, 2.0),
    "elevenlabs": (5, 1.0),
}


def build_payload(asset, meta: Meta, dep_provider_urls: dict[str, str]) -> dict:
    """Uniform payload understood by both the real adapters and the mock adapter.

    ``asset_type`` drives the mock; the real adapters read the type-specific fields.
    For i2v we feed the **upstream provider URL** of the reference image (fal fetches
    ``image_url`` over the public internet), not the MinIO copy.
    """
    kind = asset.type.value
    payload: dict = {"asset_type": kind}
    if kind == "image":
        payload.update(prompt=asset.prompt or "", width=asset.spec.get("width"), height=asset.spec.get("height"))
    elif kind == "video":
        image_url = next(
            (dep_provider_urls[r] for r in asset.reference_image_ids if r in dep_provider_urls), None
        )
        payload.update(prompt=asset.prompt or "", duration=asset.spec.get("duration_s"), image_url=image_url)
    elif kind == "voiceover":
        payload.update(text=asset.text or "", voice_id=asset.spec.get("voice_id") or meta.narration_voice_id)
    return payload


def ext_for(kind: str, url: str) -> str:
    """Pick a file extension from the result URL, falling back per asset type."""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a"}:
        return suffix
    return {"image": ".png", "video": ".mp4", "voiceover": ".mp3"}[kind]


def archive_result(result, store: Storage, project_id: str, node_id: str, kind: str) -> tuple[str, str]:
    """Archive a node result to MinIO; return ``(asset_url, provider_url)``.

    Three cases (ported verbatim from the Phase 1 driver):
      * inline ``content`` bytes (ElevenLabs) -> ``put_bytes``;
      * an ``s3://`` URL (mock placeholder already in storage) -> pass through;
      * an http(s) provider URL -> copy into MinIO, but keep the provider URL so a
        downstream i2v node can hand it to fal as a public ``image_url``.
    """
    if result.content is not None:
        asset_url = store.put_bytes(f"{project_id}/{node_id}.mp3", result.content, "audio/mpeg")
        return asset_url, asset_url
    if result.asset_url.startswith("s3://"):
        return result.asset_url, result.asset_url
    ext = ext_for(kind, result.asset_url)
    asset_url = store.put_from_url(f"{project_id}/{node_id}{ext}", result.asset_url)
    return asset_url, result.asset_url


async def render_node(project_id: str, node_id: str) -> float:
    """Generate one node end to end and write its result to shared state.

    Raises ``ProviderError`` (transient/permanent) so the Celery wrapper can retry
    or dead-letter. On success the node hash carries status + asset/provider URLs +
    actual cost, and cumulative project cost is recorded.
    """
    package = await state.get_package(project_id)
    if package is None:
        raise ProviderError(f"package {project_id!r} not found in state", transient=False)
    asset = package.asset_by_id(node_id)
    if asset is None:
        raise ProviderError(f"node {node_id!r} not in package {project_id!r}", transient=False)

    hint = asset.provider_hint or ""
    model = hint.split(":", 1)[1] if ":" in hint else ""
    dep_urls = await state.get_dep_provider_urls(project_id, asset.reference_image_ids)
    payload = build_payload(asset, package.meta, dep_urls)

    client = redis.from_url(REDIS_URL)
    provider = provider_of(hint)
    capacity, refill = _BUCKETS.get(provider, (5, 1.0))
    bucket = TokenBucket(client, provider, capacity=capacity, refill_per_sec=refill)
    await bucket.acquire(1)

    adapter = get_adapter(hint)
    handle = await adapter.submit(model, payload)
    result = await adapter.poll(handle)
    while not result.done:
        await asyncio.sleep(_POLL_INTERVAL_S)
        result = await adapter.poll(handle)

    asset_url, provider_url = archive_result(result, Storage(), project_id, node_id, asset.type.value)
    await CostTracker(client, project_id, package.meta.budget_usd).record(result.cost_usd)
    await state.set_node_status(
        project_id,
        node_id,
        NodeStatus.SUCCEEDED,
        asset_url=asset_url,
        provider_url=provider_url,
        actual_cost_usd=result.cost_usd,
    )
    return result.cost_usd
