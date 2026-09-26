"""Content hashes of what each node sends its provider, for reusing identical renders."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from schema.models import Asset, AssetType, Meta, ProductionPackage


def whole_seconds(duration: float | int | str | None) -> int | None:
    """The clip length PixVerse is asked for. Shared with the fal adapter so the two can't drift."""
    return int(round(float(duration))) if duration else None


def render_inputs(asset: Asset, meta: Meta) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "type": asset.type.value,
        "provider": asset.provider_hint or "",
        "take": asset.take,
    }
    if asset.type is AssetType.IMAGE:
        inputs |= {
            "prompt": asset.prompt or "",
            "width": asset.spec.get("width"),
            "height": asset.spec.get("height"),
        }
    elif asset.type is AssetType.VIDEO:
        inputs |= {
            "prompt": asset.prompt or "",
            "duration": whole_seconds(asset.spec.get("duration_s")),
        }
    else:
        inputs |= {
            "text": asset.text or "",
            "voice_id": asset.spec.get("voice_id") or meta.narration_voice_id,
        }
    return inputs


def _digest(inputs: dict[str, Any]) -> str:
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprints(package: ProductionPackage) -> dict[str, str]:
    """node_id -> sha256 hex. A video also hashes its start frame (its first reference image),
    so a changed start image re-renders the shots animated from it. Continuation edges are
    excluded: nothing reads a previous shot's output."""
    by_id = {a.node_id: a for a in package.assets}
    memo: dict[str, str] = {}
    visiting: set[str] = set()

    def print_of(node_id: str) -> str:
        if node_id in memo:
            return memo[node_id]
        asset = by_id[node_id]
        visiting.add(node_id)
        inputs = render_inputs(asset, package.meta)
        if asset.type is AssetType.VIDEO:
            start = asset.reference_image_ids[0] if asset.reference_image_ids else None
            if start in by_id and start not in visiting:
                inputs["start_frame"] = print_of(start)
            else:
                inputs["start_frame"] = start
        visiting.discard(node_id)
        memo[node_id] = _digest(inputs)
        return memo[node_id]

    return {node_id: print_of(node_id) for node_id in by_id}
