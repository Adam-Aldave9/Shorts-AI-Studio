"""fal.ai adapter — Flux (reference images) and PixVerse V6 (image-to-video) via
fal's async **queue API** (spec §3.2, §6.4).

The contract is the same submit → poll → fetch_result loop the worker's
``_generate`` already drives: ``submit`` POSTs the job and returns a handle
carrying the queue ``status_url``/``response_url`` fal hands back; ``poll`` reads
status; ``fetch_result`` pulls the finished asset URL. We store and reuse the URLs
fal returns rather than reconstructing them, which sidesteps fal's app-id path
quirk (the status URL for ``fal-ai/flux/schnell`` lives under ``fal-ai/flux``).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from adapters.base import JobHandle, JobResult, ProviderError

FAL_QUEUE_BASE = "https://queue.fal.run"

# provider_hint suffix -> fal model path.
# ⚠️ Confirm against current fal docs before the real-money run; PixVerse paths
# drift across versions. Verified against fal.ai/models as of 2026-06.
_MODEL_SLUGS = {
    "flux-schnell": "fal-ai/flux/schnell",
    "flux-pro": "fal-ai/flux-pro",
    "pixverse-v6-i2v": "fal-ai/pixverse/v6/image-to-video",
}

# Per-model price (USD), aligned with the spec §13.1 cost model and the fixture's
# estimated_cost_usd values. Used only to report actuals — fal does not return cost.
_PRICES = {
    "flux-schnell": 0.03,
    "flux-pro": 0.04,
    "pixverse-v6-i2v": 0.10,
}

_VIDEO_MODELS = {"pixverse-v6-i2v"}
_IMAGE_MODELS = {"flux-schnell", "flux-pro"}


class FalAdapter:
    name = "fal"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("FAL_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=FAL_QUEUE_BASE,
            headers={"Authorization": f"Key {self._api_key}"},
            timeout=httpx.Timeout(30.0, read=600.0),
        )

    # -- input building -----------------------------------------------------
    @staticmethod
    def _build_input(model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Translate the uniform driver payload into the provider's input body."""
        if model in _IMAGE_MODELS:
            body: dict[str, Any] = {"prompt": payload.get("prompt") or ""}
            width, height = payload.get("width"), payload.get("height")
            if width and height:
                body["image_size"] = {"width": int(width), "height": int(height)}
            return body
        if model in _VIDEO_MODELS:
            image_url = payload.get("image_url")
            if not image_url:
                raise ProviderError(
                    f"i2v model {model!r} requires a reachable image_url", transient=False
                )
            body = {"prompt": payload.get("prompt") or "", "image_url": image_url}
            if payload.get("duration"):
                # PixVerse V6 takes an integer duration in seconds (1-15).
                body["duration"] = int(round(float(payload["duration"])))
            return body
        raise ProviderError(f"unknown fal model {model!r}", transient=False)

    # -- adapter verbs ------------------------------------------------------
    async def submit(self, model: str, payload: dict[str, Any]) -> JobHandle:
        if not self._api_key:
            raise ProviderError("FAL_API_KEY is not set", transient=False)
        slug = _MODEL_SLUGS.get(model)
        if slug is None:
            raise ProviderError(f"no fal slug mapped for model {model!r}", transient=False)

        body = self._build_input(model, payload)
        try:
            resp = await self._client.post(f"/{slug}", json=body)
        except httpx.RequestError as exc:  # network/timeout -> retryable
            raise ProviderError(f"fal submit network error: {exc}", transient=True) from exc
        self._raise_for_status(resp)

        data = resp.json()
        return JobHandle(
            provider=self.name,
            job_id=data.get("request_id", ""),
            meta={
                "status_url": data["status_url"],
                "response_url": data["response_url"],
                "model": model,
                "kind": "video" if model in _VIDEO_MODELS else "image",
            },
        )

    async def poll(self, handle: JobHandle) -> JobResult:
        try:
            resp = await self._client.get(handle.meta["status_url"])
        except httpx.RequestError as exc:
            raise ProviderError(f"fal poll network error: {exc}", transient=True) from exc
        self._raise_for_status(resp)

        status = resp.json().get("status")
        if status in {"IN_QUEUE", "IN_PROGRESS"}:
            return JobResult(asset_url="", cost_usd=0.0, done=False)
        if status == "COMPLETED":
            return await self.fetch_result(handle)
        raise ProviderError(f"fal job in unexpected state {status!r}", transient=False)

    async def fetch_result(self, handle: JobHandle) -> JobResult:
        try:
            resp = await self._client.get(handle.meta["response_url"])
        except httpx.RequestError as exc:
            raise ProviderError(f"fal fetch network error: {exc}", transient=True) from exc
        self._raise_for_status(resp)

        data = resp.json()
        if handle.meta.get("kind") == "video":
            url = (data.get("video") or {}).get("url")
        else:
            images = data.get("images") or []
            url = images[0].get("url") if images else None
        if not url:
            raise ProviderError(f"fal result missing asset url: {data!r}", transient=False)

        cost = _PRICES.get(handle.meta.get("model", ""), 0.0)
        return JobResult(asset_url=url, cost_usd=cost, done=True)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        # 5xx + 429 are retryable; other 4xx (bad request/auth) are permanent.
        transient = resp.status_code >= 500 or resp.status_code == 429
        raise ProviderError(
            f"fal HTTP {resp.status_code}: {resp.text[:500]}", transient=transient
        )
