"""No-network checks for the worker's per-node helpers (payload / ext / archival).

Mirrors ``harness/tests/test_driver.py`` — these are the same load-bearing helpers,
now shared. ``render_node`` itself needs Redis + a provider, so it is exercised in
the end-to-end mock run, not here.
"""

from __future__ import annotations

from pathlib import Path

from adapters import JobResult
from schema import ProductionPackage

from worker.render import archive_result, build_payload, ext_for

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "example-packages" / "rainforest-90s.json"


def _pkg() -> ProductionPackage:
    return ProductionPackage.model_validate_json(FIXTURE.read_text())


class _FakeStore:
    """Records calls; returns a deterministic s3:// URL for the chosen key."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.calls.append(("put_bytes", key, content_type))
        return f"s3://film-assets/{key}"

    def put_from_url(self, key: str, url: str, content_type: str | None = None) -> str:
        self.calls.append(("put_from_url", key, url))
        return f"s3://film-assets/{key}"


# -- build_payload ----------------------------------------------------------
def test_build_payload_image():
    pkg = _pkg()
    payload = build_payload(pkg.asset_by_id("ref_canopy_01"), pkg.meta, {})
    assert payload["asset_type"] == "image"
    assert payload["width"] == 1024 and payload["height"] == 576
    assert payload["prompt"]


def test_build_payload_video_threads_upstream_provider_url():
    pkg = _pkg()
    payload = build_payload(pkg.asset_by_id("shot_001"), pkg.meta, {"ref_canopy_01": "https://fal/ref.png"})
    assert payload["asset_type"] == "video"
    assert payload["image_url"] == "https://fal/ref.png"
    assert payload["duration"] == 3.0


def test_build_payload_voiceover_falls_back_to_meta_voice():
    pkg = _pkg()
    payload = build_payload(pkg.asset_by_id("narration_full"), pkg.meta, {})
    assert payload["asset_type"] == "voiceover"
    assert payload["text"] and payload["voice_id"]


# -- ext_for ----------------------------------------------------------------
def test_ext_for_prefers_url_suffix_then_falls_back():
    assert ext_for("image", "https://x/y.jpg?token=1") == ".jpg"
    assert ext_for("video", "https://x/y") == ".mp4"
    assert ext_for("voiceover", "https://x/stream") == ".mp3"


# -- archive_result ---------------------------------------------------------
def test_archive_result_inline_content_uploads_bytes():
    store = _FakeStore()
    result = JobResult(asset_url="", cost_usd=0.4, content=b"audio-bytes")
    asset_url, provider_url = archive_result(result, store, "p1", "narration_full", "voiceover")
    assert asset_url == "s3://film-assets/p1/narration_full.mp3"
    assert provider_url == asset_url
    assert store.calls[0][0] == "put_bytes"


def test_archive_result_s3_placeholder_passthrough():
    store = _FakeStore()
    result = JobResult(asset_url="s3://film-assets/_mock/placeholder.png", cost_usd=0.04)
    asset_url, provider_url = archive_result(result, store, "p1", "ref_canopy_01", "image")
    assert asset_url == provider_url == "s3://film-assets/_mock/placeholder.png"
    assert store.calls == []  # nothing uploaded for an already-stored placeholder


def test_archive_result_http_copies_and_keeps_provider_url():
    store = _FakeStore()
    result = JobResult(asset_url="https://fal/out.mp4", cost_usd=0.1)
    asset_url, provider_url = archive_result(result, store, "p1", "shot_001", "video")
    assert asset_url == "s3://film-assets/p1/shot_001.mp4"
    assert provider_url == "https://fal/out.mp4"  # provider URL preserved for i2v threading
    assert store.calls[0][0] == "put_from_url"
