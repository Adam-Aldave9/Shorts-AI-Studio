"""Assemble agent output into a production package (spec §4.2, §5).

This is the one place creative intent becomes a DAG of provider calls. It is
deliberately defensive: an LLM can mis-tag an entity or drift a duration, but the
package handed to the scheduler must pass :func:`validator.validate_package`. So
assembly *guarantees* every gate by construction —

  * one ``image`` reference node per world entity (the valid reference set);
  * every ``video`` shot gets at least one resolvable reference image (falling back
    to the scene's location, then any reference, so the video gate never trips);
  * dependency edges only ever point at nodes that exist and only backwards
    (refs have no deps, continuation points at the previous shot), so the DAG is
    acyclic with no dangling edges;
  * shot durations are rescaled to the target, so the duration gate is satisfied;
  * the budget is set above the summed estimate, so the budget gate is satisfied.

The result is then re-validated terminally in the graph and again server-side on
any checkpoint edit — but it should already be clean leaving here.
"""

from __future__ import annotations

import uuid

from schema import (
    Asset,
    AssetType,
    Character,
    Location,
    Meta,
    ProductionPackage,
    TimelineEntry,
    World,
)

from planning.models import Screenplay, ShotList, ShotPrompts

_DEFAULT_STYLE = "flat 2D animation, warm earth tones"
_DEFAULT_VOICE = "elevenlabs_voice_default"
_DEFAULT_BUDGET = 15.0

_REF_COST = 0.03
_SHOT_COST_MIN, _SHOT_COST_MAX = 0.05, 0.25
_VOICEOVER_COST = 0.4

_IMAGE_HINT = "fal:flux-schnell"
_VIDEO_HINT = "fal:pixverse-v6-i2v"
_VOICEOVER_HINT = "elevenlabs:multilingual-v3"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _ref_prompt(entity: Character | Location, style: str) -> str:
    if isinstance(entity, Character):
        return (
            f"Character reference sheet, {style}: {entity.canonical_description} "
            "Neutral pose, plain background."
        )
    return f"Establishing background, {style}: {entity.canonical_description}"


def _build_ref_nodes(world: World, style: str) -> tuple[list[Asset], dict[str, str]]:
    """One image node per world entity. Returns the nodes and an
    ``entity_id -> ref_node_id`` map for resolving shot references."""
    nodes: list[Asset] = []
    entity_ref: dict[str, str] = {}
    seen: set[str] = set()
    for entity in (*world.characters, *world.locations):
        ref_id = entity.reference_image_ids[0] if entity.reference_image_ids else f"ref_{entity.id}"
        entity_ref[entity.id] = ref_id
        if ref_id in seen:
            continue
        seen.add(ref_id)
        nodes.append(
            Asset(
                node_id=ref_id,
                type=AssetType.IMAGE,
                provider_hint=_IMAGE_HINT,
                spec={"width": 1024, "height": 576},
                prompt=_ref_prompt(entity, style),
                estimated_cost_usd=_REF_COST,
            )
        )
    return nodes, entity_ref


def _resolve_refs(location_id: str, subject_ids: list[str], entity_ref: dict[str, str]) -> list[str]:
    """Map a shot's tagged entities to reference node ids (location first, like the
    flagship package). Always returns at least one ref so the video gate passes."""
    refs: list[str] = []
    if location_id in entity_ref:
        refs.append(entity_ref[location_id])
    for sid in subject_ids:
        rid = entity_ref.get(sid)
        if rid and rid not in refs:
            refs.append(rid)
    if not refs and entity_ref:
        refs.append(next(iter(entity_ref.values())))
    return refs


def _normalize_durations(raw: list[float], target: float) -> list[float]:
    """Rescale the per-shot durations so they sum to the target duration."""
    vals = [d if isinstance(d, (int, float)) and d > 0 else 3.0 for d in raw]
    if not vals:
        return []
    total = sum(vals)
    if total <= 0:
        return [round(target / len(vals), 2)] * len(vals)
    scale = target / total
    return [round(v * scale, 2) for v in vals]


def assemble_package(
    brief: dict,
    world: World,
    screenplay: Screenplay,
    shot_list: ShotList,
    shot_prompts: ShotPrompts,
) -> ProductionPackage:
    project_id = f"p_{uuid.uuid4().hex[:6]}"
    style = brief.get("style") or _DEFAULT_STYLE
    target = float(brief.get("target_duration_s") or 90.0)
    voice = brief.get("narration_voice_id") or _DEFAULT_VOICE

    ref_nodes, entity_ref = _build_ref_nodes(world, style)

    prompt_by_shot = {p.shot_id: p for p in shot_prompts.prompts}
    shots = shot_list.shots
    durations = _normalize_durations([s.duration_s for s in shots], target)

    video_nodes: list[Asset] = []
    prev_id: str | None = None
    prev_loc: str | None = None
    for i, (shot, dur) in enumerate(zip(shots, durations)):
        node_id = f"shot_{i + 1:03d}"
        refs = _resolve_refs(shot.location_id, shot.subject_ids, entity_ref)
        deps = list(refs)
        # Continuation edge: a shot that stays in the same location continues from
        # the previous shot's last frame (i2v chaining). Always points backwards.
        if prev_id is not None and shot.location_id == prev_loc:
            deps.append(prev_id)

        sp = prompt_by_shot.get(shot.id)
        prompt_text = (sp.prompt if sp else None) or shot.action
        hint = (sp.provider_hint if sp else None) or _VIDEO_HINT
        est = _clamp(sp.estimated_cost_usd if sp else 0.1, _SHOT_COST_MIN, _SHOT_COST_MAX)

        video_nodes.append(
            Asset(
                node_id=node_id,
                type=AssetType.VIDEO,
                depends_on=deps,
                provider_hint=hint,
                spec={"duration_s": dur, "aspect": brief.get("aspect_ratio") or "16:9"},
                prompt=prompt_text,
                reference_image_ids=refs,
                estimated_cost_usd=est,
            )
        )
        prev_id, prev_loc = node_id, shot.location_id

    narration = " ".join(s.narration.strip() for s in screenplay.scenes if s.narration).strip()
    voiceover = Asset(
        node_id="narration_full",
        type=AssetType.VOICEOVER,
        provider_hint=_VOICEOVER_HINT,
        spec={"voice_id": voice},
        text=narration or screenplay.logline,
        estimated_cost_usd=_VOICEOVER_COST,
    )

    # Timeline: shots laid end to end, narration spanning the whole film on track 1.
    timeline: list[TimelineEntry] = []
    t = 0.0
    for node, dur in zip(video_nodes, durations):
        timeline.append(TimelineEntry(node_id=node.node_id, in_s=round(t, 2), out_s=round(t + dur, 2)))
        t += dur
    total = round(t, 2)
    timeline.append(TimelineEntry(node_id="narration_full", in_s=0.0, out_s=total, audio_track=1))

    assets = [*ref_nodes, *video_nodes, voiceover]
    est_total = sum(a.estimated_cost_usd for a in assets)
    budget = round(max(_DEFAULT_BUDGET, est_total * 1.25), 2)

    meta = Meta(
        title=screenplay.title or "Untitled",
        premise=brief["premise"],
        target_duration_s=round(target, 2),
        aspect_ratio=brief.get("aspect_ratio") or "16:9",
        style=style,
        narration_voice_id=voice,
        budget_usd=budget,
    )

    return ProductionPackage(
        project_id=project_id,
        meta=meta,
        world=world,
        assets=assets,
        timeline=timeline,
    )
