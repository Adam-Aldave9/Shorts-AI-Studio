"""No-network checks for the sequential driver's ordering + payload helpers."""

from __future__ import annotations

from pathlib import Path

from schema import ProductionPackage

from harness.cli import _build_payload, _ext_for, _topo_order

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "example-packages" / "rainforest-90s.json"


def _pkg() -> ProductionPackage:
    return ProductionPackage.model_validate_json(FIXTURE.read_text())


def test_topo_order_places_dependencies_first():
    pkg = _pkg()
    order = [a.node_id for a in _topo_order(pkg)]
    assert len(order) == len(pkg.assets)
    pos = {n: i for i, n in enumerate(order)}
    for a in pkg.assets:
        for dep in a.depends_on:
            assert pos[dep] < pos[a.node_id], f"{dep} should precede {a.node_id}"


def test_build_payload_image():
    pkg = _pkg()
    payload = _build_payload(pkg.asset_by_id("ref_canopy_01"), pkg, {})
    assert payload["asset_type"] == "image"
    assert payload["width"] == 1024 and payload["height"] == 576
    assert payload["prompt"]


def test_build_payload_video_uses_upstream_provider_url():
    pkg = _pkg()
    payload = _build_payload(pkg.asset_by_id("shot_001"), pkg, {"ref_canopy_01": "https://fal/ref.png"})
    assert payload["asset_type"] == "video"
    assert payload["image_url"] == "https://fal/ref.png"
    assert payload["duration"] == 3.0


def test_build_payload_voiceover_falls_back_to_meta_voice():
    pkg = _pkg()
    payload = _build_payload(pkg.asset_by_id("narration_full"), pkg, {})
    assert payload["asset_type"] == "voiceover"
    assert payload["text"] and payload["voice_id"]


def test_ext_for_prefers_url_suffix_then_falls_back():
    assert _ext_for("image", "https://x/y.jpg?token=1") == ".jpg"
    assert _ext_for("video", "https://x/y") == ".mp4"
    assert _ext_for("voiceover", "https://x/stream") == ".mp3"
