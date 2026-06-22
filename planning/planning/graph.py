"""LangGraph wiring for the planning agents (spec §4.2).

    Brief -> Script -> Breakdown -> Prompts -> (validated) Package
                         World bible ----^

v1 stub: the agents return hand-shaped placeholder output so the rest of the
pipeline (checkpoint, scheduler, workers) can be exercised before the LLM chain
is wired in.
"""

from __future__ import annotations

import uuid

from schema import (
    Asset,
    AssetType,
    Meta,
    NodeStatus,
    ProductionPackage,
    TimelineEntry,
)


async def run_planning(brief: dict) -> ProductionPackage:
    """Run the agent chain and return an (unvalidated) production package.

    TODO: replace this with a real LangGraph StateGraph whose nodes are the
    script, breakdown, and prompts agents, with the hand-authored world bible
    injected before the prompts node.
    """
    project_id = f"p_{uuid.uuid4().hex[:6]}"
    duration = float(brief.get("target_duration_s", 90))

    meta = Meta(
        title="Untitled",
        premise=brief["premise"],
        target_duration_s=duration,
        style=brief.get("style") or "flat 2D animation",
        narration_voice_id=brief.get("narration_voice_id") or "elevenlabs_voice_default",
        budget_usd=15.0,
    )

    # Minimal one-shot package so the DAG/compositor path is exercisable.
    ref = Asset(
        node_id="ref_establishing_01",
        type=AssetType.IMAGE,
        provider_hint="fal:flux-pro",
        spec={"width": 1024, "height": 576, "asset_type": "image"},
        prompt="Establishing reference frame.",
        estimated_cost_usd=0.04,
        status=NodeStatus.PENDING,
    )
    shot = Asset(
        node_id="shot_001",
        type=AssetType.VIDEO,
        depends_on=["ref_establishing_01"],
        provider_hint="fal:pixverse-v6-i2v",
        spec={"duration_s": 3.0, "aspect": "16:9", "asset_type": "video"},
        prompt="Opening shot.",
        reference_image_ids=["ref_establishing_01"],
        estimated_cost_usd=0.10,
        status=NodeStatus.PENDING,
    )
    narration = Asset(
        node_id="narration_full",
        type=AssetType.VOICEOVER,
        provider_hint="elevenlabs:multilingual-v3",
        spec={"voice_id": meta.narration_voice_id, "asset_type": "voiceover"},
        text="Narration placeholder.",
        estimated_cost_usd=0.40,
        status=NodeStatus.PENDING,
    )

    return ProductionPackage(
        project_id=project_id,
        meta=meta,
        assets=[ref, shot, narration],
        timeline=[
            TimelineEntry(node_id="shot_001", in_s=0.0, out_s=3.0),
            TimelineEntry(node_id="narration_full", in_s=0.0, out_s=duration, audio_track=1),
        ],
    )
