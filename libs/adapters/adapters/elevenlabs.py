"""ElevenLabs adapter — text-to-speech narration (spec §3.2, §6.4).

Kept separate from fal on purpose — different key, rate limit, error model, and
response shape, which preserves the genuine multi-provider story. ElevenLabs TTS
is a single synchronous call that returns ``audio/mpeg`` **bytes**, not a queued
URL, so we capture the audio at ``submit`` time into the handle and hand it back
on ``fetch_result`` via ``JobResult.content`` — the driver archives the bytes to
object storage, keeping the adapter free of any storage knowledge.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from adapters.base import JobHandle, JobResult, ProviderError

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# provider_hint suffix -> ElevenLabs model_id.
# ⚠️ ``multilingual-v3`` maps to the GA ``eleven_multilingual_v2`` (eleven_v3 is
# not generally available on the standard TTS endpoint); revisit before the real run.
_MODEL_IDS = {
    "multilingual-v3": "eleven_multilingual_v2",
    "multilingual-v2": "eleven_multilingual_v2",
}
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"

# Per-character price (USD). ~$0.30 / 1k chars approximates ElevenLabs' creator
# tier and yields ~$0.34 for the fixture's ~1.1k-char narration, in line with the
# spec §13.1 ~$0.40 narration estimate.
_PRICE_PER_CHAR = 0.0003


class ElevenLabsAdapter:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=ELEVENLABS_BASE,
            headers={"xi-api-key": self._api_key},
            timeout=httpx.Timeout(30.0, read=300.0),
        )

    async def submit(self, model: str, payload: dict[str, Any]) -> JobHandle:
        if not self._api_key:
            raise ProviderError("ELEVENLABS_API_KEY is not set", transient=False)
        text = payload.get("text")
        if not text:
            raise ProviderError("elevenlabs requires non-empty text", transient=False)
        voice_id = payload.get("voice_id")
        if not voice_id:
            raise ProviderError("elevenlabs requires a voice_id", transient=False)

        model_id = _MODEL_IDS.get(model, model or _DEFAULT_MODEL_ID)
        try:
            resp = await self._client.post(
                f"/text-to-speech/{voice_id}",
                json={"text": text, "model_id": model_id},
                headers={"accept": "audio/mpeg"},
            )
        except httpx.RequestError as exc:  # network/timeout -> retryable
            raise ProviderError(f"elevenlabs network error: {exc}", transient=True) from exc
        if not resp.is_success:
            transient = resp.status_code >= 500 or resp.status_code == 429
            raise ProviderError(
                f"elevenlabs HTTP {resp.status_code}: {resp.text[:500]}", transient=transient
            )

        cost = round(len(text) * _PRICE_PER_CHAR, 4)
        # The whole asset is already in hand; stash it for fetch_result.
        return JobHandle(
            provider=self.name,
            job_id=f"el_{voice_id}",
            meta={"content": resp.content, "cost": cost},
        )

    async def poll(self, handle: JobHandle) -> JobResult:
        # Synchronous provider: the result is ready the moment submit returns.
        return await self.fetch_result(handle)

    async def fetch_result(self, handle: JobHandle) -> JobResult:
        return JobResult(
            asset_url="",
            cost_usd=handle.meta["cost"],
            content=handle.meta["content"],
            done=True,
        )
