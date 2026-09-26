"""Revisions: what changed in an edited story, what must be regenerated, and the new package."""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from typing import Callable, Literal

from pydantic import BaseModel
from schema import (
    SCHEMA_VERSION,
    Asset,
    AssetType,
    Character,
    Location,
    NodeStatus,
    ProductionPackage,
    prompt_max_bytes,
    whole_seconds,
)

from planning.agents import breakdown, prompts
from planning.assembly import VIDEO_HINT, _normalize_durations, assemble_package, ref_node_id
from planning.graph import _mock_delay_s
from planning.models import Scene, Shot, ShotList, ShotPrompt, ShotPrompts, Story
from planning.prompt_budget import fit_to_bytes, normalize_punctuation
from planning.story import SHOT_TYPES, spoken_narration, voiceovers

log = logging.getLogger(__name__)

BRIEF_FIELDS = ("premise", "target_duration_s", "style", "narration_voice_id")
STAGES = ("brief", "world", "script", "shots")
SECONDS_PER_SHOT = 3.5
NEW_SHOT_COST_USD = 0.10
NEW_REF_COST_USD = 0.03
NEW_NARRATION_COST_USD = 0.20
_MAX_NAMED = 3

OnStage = Callable[[str], None]
OnDetail = Callable[[str, dict], None]


class RevisionRequest(BaseModel):
    story: Story
    keep_shots: list[str] = []  # changed scenes whose current shots the user keeps
    note: str = ""
    base_hash: str


class RevisionPreview(BaseModel):
    mode: Literal["new_version", "in_place"]
    next_version: int | None
    errors: list[str]
    warnings: list[str]
    has_changes: bool
    from_stage: str | None
    changes: list[str]
    entity_status: dict[str, str]
    scene_status: dict[str, str]
    stale_scenes: list[str]
    shot_targets: dict[str, int]
    shot_status: dict[str, str]
    rerendered_refs: list[str]
    narration_rerender: bool
    predicted_render: int | None
    predicted_reuse: int | None
    predicted_cost_usd: float | None


@dataclass
class RevisionPlan:
    brief_changes: list[str]
    entity_status: dict[str, str]
    scene_status: dict[str, str]
    narration_changed: bool
    stale_scenes: list[str]
    shot_targets: dict[str, int]
    full_replan: bool
    shot_status: dict[str, str]
    rerendered_refs: list[str]
    narration_rerender: bool
    shots_hand_edited: bool
    script_edited: bool
    from_stage: str | None
    changes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


# --------------------------------------------------------------------------
# Change detection
# --------------------------------------------------------------------------
def _entities(story: Story) -> dict[str, Character | Location]:
    return {e.id: e for e in (*story.world.characters, *story.world.locations)}


def _prompt_inputs(shot: Shot) -> tuple:
    return (shot.shot_type, shot.action, shot.location_id, tuple(shot.subject_ids))


def _shot_key(shot: Shot) -> tuple:
    return (shot.id, *_prompt_inputs(shot), shot.duration_s)


def shots_of(story: Story, scene_id: str) -> list[Shot]:
    return [s for s in story.shots if s.scene_id == scene_id]


def _words(text: str) -> int:
    return len(text.split())


def shot_targets(parent_story: Story, story: Story, stale: list[str]) -> dict[str, int]:
    """How many shots to plan for each stale scene: an existing scene keeps its count (and so
    its pacing); a new one gets its narration's share of the film."""
    scenes = story.script.scenes
    total_words = sum(_words(s.narration) for s in scenes)
    parent_scene_ids = {s.id for s in parent_story.script.scenes}
    targets: dict[str, int] = {}
    for scene in scenes:
        if scene.id not in stale:
            continue
        before = len(shots_of(parent_story, scene.id)) if scene.id in parent_scene_ids else 0
        if before:
            targets[scene.id] = before
            continue
        share = _words(scene.narration) / total_words if total_words else 1 / len(scenes)
        targets[scene.id] = max(1, round(story.brief.target_duration_s * share / SECONDS_PER_SHOT))
    return targets


def plan_revision(
    parent: ProductionPackage, parent_story: Story, story: Story, keep_shots: list[str]
) -> RevisionPlan:
    s0, s1 = parent_story, story
    brief_changes = [f for f in BRIEF_FIELDS if getattr(s0.brief, f) != getattr(s1.brief, f)]

    e0, e1 = _entities(s0), _entities(s1)
    entity_status: dict[str, str] = {}
    for eid, entity in e1.items():
        old = e0.get(eid)
        if old is None:
            entity_status[eid] = "new"
        elif old.canonical_description != entity.canonical_description:
            entity_status[eid] = "changed"
        elif old.name != entity.name:
            entity_status[eid] = "renamed"
    for eid in e0:
        if eid not in e1:
            entity_status[eid] = "removed"

    sc0 = {s.id: s for s in s0.script.scenes}
    sc1 = {s.id: s for s in s1.script.scenes}
    scene_status: dict[str, str] = {}
    for sid, scene in sc1.items():
        old = sc0.get(sid)
        if old is None:
            scene_status[sid] = "new"
        elif (old.heading, old.location, old.beat) != (scene.heading, scene.location, scene.beat):
            scene_status[sid] = "changed"
        elif old.narration != scene.narration:
            scene_status[sid] = "narration"
    for sid in sc0:
        if sid not in sc1:
            scene_status[sid] = "removed"
    scenes_reordered = [s.id for s in s0.script.scenes if s.id in sc1] != [
        s.id for s in s1.script.scenes if s.id in sc0
    ]
    narration_changed = [(s.id, s.narration) for s in s1.script.scenes] != [
        (s.id, s.narration) for s in s0.script.scenes
    ]

    stale: list[str] = []
    for scene in s1.script.scenes:
        now = [_shot_key(s) for s in shots_of(s1, scene.id)]
        if not now:
            stale.append(scene.id)
            continue
        untouched = now == [_shot_key(s) for s in shots_of(s0, scene.id)]
        if untouched and (
            scene_status.get(scene.id) in {"new", "changed"} or "target_duration_s" in brief_changes
        ):
            stale.append(scene.id)
    stale = [s for s in stale if s not in keep_shots or not shots_of(s1, s)]
    targets = shot_targets(s0, s1, stale)
    full_replan = bool(stale) and len(stale) == len(s1.script.scenes)

    parent_videos = {a.node_id for a in parent.assets if a.type is AssetType.VIDEO}
    shots0 = {s.id: s for s in s0.shots}
    dirty_entities = {e for e, st in entity_status.items() if st in {"changed", "renamed", "removed"}}
    style_changed = "style" in brief_changes
    stale_set = set(stale)
    shot_status: dict[str, str] = {}
    for shot in s1.shots:
        if shot.scene_id in stale_set:
            shot_status[shot.id] = "stale"
        elif shot.id not in parent_videos or shot.id not in shots0:
            shot_status[shot.id] = "new"
        elif _prompt_inputs(shot) != _prompt_inputs(shots0[shot.id]):
            shot_status[shot.id] = "edited"
        elif style_changed or shot.location_id in dirty_entities or any(
            s in dirty_entities for s in shot.subject_ids
        ):
            shot_status[shot.id] = "prompt"
        else:
            shot_status[shot.id] = "kept"
    s1_ids = {s.id for s in s1.shots}
    for sid in shots0:
        if sid not in s1_ids:
            shot_status[sid] = "removed"

    rerendered_refs = [
        eid for eid in e1 if style_changed or entity_status.get(eid) in {"new", "changed"}
    ]
    narration_rerender = narration_changed or "narration_voice_id" in brief_changes

    added = [s for s in s1.shots if s.id not in shots0]
    removed = [
        sid for sid, s in shots0.items() if sid not in s1_ids and scene_status.get(s.scene_id) != "removed"
    ]
    common = [s for s in s1.shots if s.id in shots0]
    edited = [
        s for s in common
        if s.scene_id not in stale_set and _shot_key(s)[1:] != _shot_key(shots0[s.id])[1:]
    ]
    reordered = [s.id for s in common] != [s.id for s in s0.shots if s.id in s1_ids] or any(
        s.scene_id != shots0[s.id].scene_id for s in common
    )
    shots_hand_edited = bool(added or removed or edited or reordered)
    script_edited = bool(scene_status or scenes_reordered) or (
        (s0.script.title, s0.script.logline) != (s1.script.title, s1.script.logline)
    )

    lines = _change_lines(
        s0, s1, brief_changes, entity_status, scene_status, scenes_reordered,
        stale, len(edited), len(added), len(removed), reordered,
    )
    from_stage = next((stage for stage in STAGES if lines[stage]), None)
    return RevisionPlan(
        brief_changes=brief_changes,
        entity_status=entity_status,
        scene_status=scene_status,
        narration_changed=narration_changed,
        stale_scenes=stale,
        shot_targets=targets,
        full_replan=full_replan,
        shot_status=shot_status,
        rerendered_refs=rerendered_refs,
        narration_rerender=narration_rerender,
        shots_hand_edited=shots_hand_edited,
        script_edited=script_edited,
        from_stage=from_stage,
        changes=[line for stage in STAGES for line in lines[stage]],
    )


def _named(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_NAMED])
    extra = len(items) - _MAX_NAMED
    return f"{shown} and {extra} more" if extra > 0 else shown


def _plural(noun: str, n: int) -> str:
    return noun if n == 1 else f"{noun}s"


def _count(n: int, noun: str) -> str:
    return f"{n} {_plural(noun, n)}"


def _change_lines(
    s0: Story, s1: Story, brief_changes: list[str], entity_status: dict[str, str],
    scene_status: dict[str, str], scenes_reordered: bool, stale: list[str],
    edited: int, added: int, removed: int, reordered: bool,
) -> dict[str, list[str]]:
    lines: dict[str, list[str]] = {stage: [] for stage in STAGES}

    brief = lines["brief"]
    if "premise" in brief_changes:
        brief.append("Premise rewritten")
    if "style" in brief_changes:
        brief.append(f'Style: "{s0.brief.style or ""}" -> "{s1.brief.style or ""}"')
    if "target_duration_s" in brief_changes:
        brief.append(f"Length: {s0.brief.target_duration_s:.0f}s -> {s1.brief.target_duration_s:.0f}s")
    if "narration_voice_id" in brief_changes:
        brief.append("Narration voice changed")

    e0, e1 = _entities(s0), _entities(s1)
    world = lines["world"]
    for status, verb, pool in (("new", "Added", e1), ("removed", "Removed", e0), ("changed", "Changed", e1)):
        for kind, cls in (("character", Character), ("location", Location)):
            names = [
                pool[eid].name for eid, st in entity_status.items()
                if st == status and isinstance(pool[eid], cls)
            ]
            if names:
                world.append(f"{verb} {_plural(kind, len(names))} {_named(names)}")
    renames = [f"{e0[eid].name} -> {e1[eid].name}" for eid, st in entity_status.items() if st == "renamed"]
    if renames:
        world.append(f"Renamed {_named(renames)}")

    sc0 = {s.id: s for s in s0.script.scenes}
    sc1 = {s.id: s for s in s1.script.scenes}
    script = lines["script"]
    if s0.script.title != s1.script.title:
        script.append(f'Title: "{s0.script.title}" -> "{s1.script.title}"')
    if s0.script.logline != s1.script.logline:
        script.append("Logline rewritten")
    for status, verb, pool in (
        ("new", "Added", sc1),
        ("removed", "Removed", sc0),
        ("changed", "Rewrote", sc1),
        ("narration", "New narration in", sc1),
    ):
        headings = [f'"{pool[sid].heading}"' for sid, st in scene_status.items() if st == status]
        if headings:
            script.append(f"{verb} {_plural('scene', len(headings))} {_named(headings)}")
    if scenes_reordered:
        script.append("Reordered scenes")

    shots = lines["shots"]
    if stale:
        shots.append(f"Re-planned shots for {_count(len(stale), 'scene')}")
    if edited:
        shots.append(f"Edited {_count(edited, 'shot')}")
    if added:
        shots.append(f"Added {_count(added, 'shot')}")
    if removed:
        shots.append(f"Removed {_count(removed, 'shot')}")
    if reordered:
        shots.append("Reordered shots")
    return lines


def change_lines(parent: ProductionPackage, parent_story: Story, story: Story) -> list[str]:
    return plan_revision(parent, parent_story, story, []).changes


def prompts_line(rewritten: int) -> str:
    return f"Rewrote {_count(rewritten, 'shot prompt')}"


# --------------------------------------------------------------------------
# Preview (pure, no LLM)
# --------------------------------------------------------------------------
def _warnings(parent: ProductionPackage, parent_story: Story, story: Story, plan: RevisionPlan) -> list[str]:
    warnings: list[str] = []
    descriptions_changed = any(st in {"changed", "new"} for st in plan.entity_status.values())
    if "style" in plan.brief_changes and not descriptions_changed:
        warnings.append(
            "Character and location descriptions still describe the old style. Consider "
            "'Restyle world with AI' on the Brief tab."
        )
    if "premise" in plan.brief_changes and not plan.entity_status and not plan.script_edited:
        warnings.append("The world and script were written for the old premise.")
    spoken = " ".join(spoken_narration(parent).split())
    joined = " ".join(" ".join(s.narration for s in parent_story.script.scenes).split())
    if plan.narration_changed and spoken != joined:
        warnings.append(
            "The spoken narration was edited at the checkpoint; your scene narration will replace it."
        )
    names = {l.name.strip().lower() for l in story.world.locations}
    for scene in story.script.scenes:
        if scene.location.strip() and scene.location.strip().lower() not in names:
            warnings.append(
                f"Scene '{scene.heading}' is set at '{scene.location}', which isn't a world location."
            )
    return warnings


def _predicted_shots(story: Story, plan: RevisionPlan) -> list[tuple[Shot | None, float]]:
    if plan.full_replan:
        count = breakdown.target_shot_count({"target_duration_s": story.brief.target_duration_s})
        planned: list[Shot | None] = [None] * count
        raw = [SECONDS_PER_SHOT] * count
    else:
        planned, raw = [], []
        for scene in story.script.scenes:
            if scene.id in plan.shot_targets:
                planned += [None] * plan.shot_targets[scene.id]
                raw += [SECONDS_PER_SHOT] * plan.shot_targets[scene.id]
            else:
                for shot in shots_of(story, scene.id):
                    planned.append(shot)
                    raw.append(shot.duration_s)
    return list(zip(planned, _normalize_durations(raw, story.brief.target_duration_s)))


def _predict(parent: ProductionPackage, story: Story, plan: RevisionPlan) -> tuple[int, int, float]:
    by_id = {a.node_id: a for a in parent.assets}

    def succeeded(node_id: str) -> bool:
        asset = by_id.get(node_id)
        return asset is not None and asset.status is NodeStatus.SUCCEEDED

    def estimate(node_id: str | None, default: float) -> float:
        asset = by_id.get(node_id) if node_id else None
        return asset.estimated_cost_usd if asset is not None else default

    render = reuse = 0
    cost = 0.0
    rerendered = set(plan.rerendered_refs)
    refs: dict[str, str] = {}
    for entity in (*story.world.characters, *story.world.locations):
        refs.setdefault(ref_node_id(entity), entity.id)
    fresh_refs: set[str] = set()
    for ref_id, entity_id in refs.items():
        if entity_id not in rerendered and succeeded(ref_id):
            reuse += 1
        else:
            render += 1
            fresh_refs.add(ref_id)
            cost += estimate(ref_id, NEW_REF_COST_USD)

    parent_refs = {ref_node_id(e) for e in (*parent.world.characters, *parent.world.locations)}
    for shot, duration in _predicted_shots(story, plan):
        old = by_id.get(shot.id) if shot is not None else None
        carried = (
            shot is not None and old is not None and plan.shot_status.get(shot.id) == "kept"
        )
        if carried:
            live = [r for r in old.reference_image_ids if r in refs or (r in by_id and r not in parent_refs)]
            start = live[0] if live else None
            carried = (
                start is not None
                and start == (old.reference_image_ids[0] if old.reference_image_ids else None)
                and start not in fresh_refs
                and whole_seconds(duration) == whole_seconds(old.spec.get("duration_s"))
            )
        if carried and succeeded(shot.id):
            reuse += 1
        else:
            render += 1
            cost += estimate(shot.id if shot is not None else None, NEW_SHOT_COST_USD)

    vos = voiceovers(parent)
    vo_id = vos[0].node_id if vos else None
    if not plan.narration_rerender and vo_id and len(vos) == 1 and succeeded(vo_id):
        reuse += 1
    else:
        render += 1
        cost += estimate(vo_id, NEW_NARRATION_COST_USD)
    return render, reuse, round(cost, 2)


def preview(
    parent: ProductionPackage,
    parent_story: Story,
    story: Story,
    keep_shots: list[str],
    *,
    mode: Literal["new_version", "in_place"],
    next_version: int | None,
    errors: list[str],
) -> RevisionPreview:
    """``parent`` is hydrated: its live statuses drive the reuse prediction."""
    plan = plan_revision(parent, parent_story, story, keep_shots)
    render = reuse = cost = None
    if mode == "new_version" and not errors:
        render, reuse, cost = _predict(parent, story, plan)
    return RevisionPreview(
        mode=mode,
        next_version=next_version if mode == "new_version" else None,
        errors=errors,
        warnings=[] if errors else _warnings(parent, parent_story, story, plan),
        has_changes=plan.has_changes,
        from_stage=plan.from_stage,
        changes=plan.changes,
        entity_status=plan.entity_status,
        scene_status=plan.scene_status,
        stale_scenes=plan.stale_scenes,
        shot_targets=plan.shot_targets,
        shot_status=plan.shot_status,
        rerendered_refs=plan.rerendered_refs,
        narration_rerender=plan.narration_rerender,
        predicted_render=render,
        predicted_reuse=reuse,
        predicted_cost_usd=cost,
    )


def skipped_stages(plan: RevisionPlan) -> list[str]:
    skipped = ["world", "script"]
    if not plan.stale_scenes:
        skipped.append("breakdown")
        if all(st in {"kept", "removed"} for st in plan.shot_status.values()):
            skipped.append("prompts")
    return skipped


# --------------------------------------------------------------------------
# Re-planned shots: sanitize and splice
# --------------------------------------------------------------------------
def _scene_location(story: Story, scene: Scene, parent_story: Story | None) -> str:
    wanted = scene.location.strip().lower()
    named = next((l.id for l in story.world.locations if l.name.strip().lower() == wanted), None)
    if named:
        return named
    location_ids = {l.id for l in story.world.locations}
    for source in (story, parent_story):
        if source is None:
            continue
        first = next((s for s in source.shots if s.scene_id == scene.id), None)
        if first is not None and first.location_id in location_ids:
            return first.location_id
    return story.world.locations[0].id if story.world.locations else ""


def _clamp_duration(value: float | None) -> float:
    if not isinstance(value, (int, float)) or value <= 0:
        return SECONDS_PER_SHOT
    return max(1.0, min(15.0, float(value)))


def sanitize_replanned(
    shot_list: ShotList,
    story: Story,
    targets: dict[str, int],
    parent_story: Story | None = None,
) -> dict[str, list[Shot]]:
    """Coerce an LLM (or mock) shot list for ``targets`` scenes into valid shots: known
    ids only, one shot at least per scene, and ``rp_<scene>_<n>`` ids that can never be
    mistaken for a node of the parent."""
    scenes = {s.id: s for s in story.script.scenes}
    location_ids = {l.id for l in story.world.locations}
    character_ids = {c.id for c in story.world.characters}
    fallback = {sid: _scene_location(story, scenes[sid], parent_story) for sid in targets if sid in scenes}
    out: dict[str, list[Shot]] = {sid: [] for sid in fallback}
    for shot in shot_list.shots:
        if shot.scene_id not in out:
            continue
        subjects: list[str] = []
        for sid in shot.subject_ids:
            if sid in character_ids and sid not in subjects:
                subjects.append(sid)
        shot_type = (shot.shot_type or "").strip().lower()
        out[shot.scene_id].append(
            Shot(
                id="",
                scene_id=shot.scene_id,
                shot_type=shot_type if shot_type in SHOT_TYPES else "wide",
                duration_s=_clamp_duration(shot.duration_s),
                location_id=shot.location_id if shot.location_id in location_ids else fallback[shot.scene_id],
                subject_ids=subjects,
                action=shot.action,
            )
        )
    taken = {s.id for s in story.shots}
    for sid, shots in out.items():
        if not shots:
            shots.append(
                Shot(id="", scene_id=sid, shot_type="wide", duration_s=SECONDS_PER_SHOT,
                     location_id=fallback[sid], subject_ids=[], action=scenes[sid].beat)
            )
        n = 1
        for shot in shots:
            while f"rp_{sid}_{n}" in taken:
                n += 1
            shot.id = f"rp_{sid}_{n}"
            taken.add(shot.id)
    return out


def splice_shots(story: Story, replanned: dict[str, list[Shot]]) -> list[Shot]:
    """The final shot list, in scene order: a re-planned scene's new shots replace its old ones."""
    out: list[Shot] = []
    for scene in story.script.scenes:
        out.extend(replanned[scene.id] if scene.id in replanned else shots_of(story, scene.id))
    return out


def mock_replan(story: Story, targets: dict[str, int], parent_story: Story | None = None) -> ShotList:
    """A deterministic stand-in for the breakdown agent (MOCK mode, $0)."""
    scenes = {s.id: s for s in story.script.scenes}
    cycle = ("wide", "medium", "close-up")
    shots: list[Shot] = []
    for sid, count in targets.items():
        scene = scenes[sid]
        location = _scene_location(story, scene, parent_story)
        for k in range(1, count + 1):
            shots.append(
                Shot(id=f"mock_{sid}_{k}", scene_id=sid, shot_type=cycle[(k - 1) % 3],
                     duration_s=SECONDS_PER_SHOT, location_id=location, subject_ids=[],
                     action=f"{scene.beat} (shot {k} of {count})")
            )
    return ShotList(shots=shots)


def mock_prompt(shot: Shot, story: Story) -> ShotPrompt:
    location = next((l.name for l in story.world.locations if l.id == shot.location_id), shot.location_id)
    text = f"{shot.shot_type.capitalize()} shot. {shot.action} Setting: {location}. {story.brief.style}."
    fitted = fit_to_bytes(normalize_punctuation(text), prompt_max_bytes(VIDEO_HINT))
    return ShotPrompt(shot_id=shot.id, prompt=fitted, estimated_cost_usd=NEW_SHOT_COST_USD)


# --------------------------------------------------------------------------
# Build: assemble, then carry the parent's content over
# --------------------------------------------------------------------------
def _brief_dict(story: Story, parent: ProductionPackage) -> dict:
    return {**story.brief.model_dump(), "aspect_ratio": parent.meta.aspect_ratio}


def build_revision(
    parent: ProductionPackage,
    story: Story,
    plan: RevisionPlan,
    shots: list[Shot],
    fresh_prompts: dict[str, ShotPrompt],
) -> ProductionPackage:
    """``parent`` must be the raw spec: its content is copied verbatim into the new package."""
    by_id = {a.node_id: a for a in parent.assets}

    def prompt_for(shot: Shot) -> ShotPrompt:
        old = by_id.get(shot.id)
        if plan.shot_status.get(shot.id) == "kept" and old is not None:
            return ShotPrompt(shot_id=shot.id, prompt=old.prompt or "", estimated_cost_usd=old.estimated_cost_usd)
        return fresh_prompts.get(shot.id) or ShotPrompt(shot_id=shot.id, prompt=shot.action)

    shot_prompts = ShotPrompts(prompts=[prompt_for(s) for s in shots])
    pkg = assemble_package(
        _brief_dict(story, parent), story.world, story.script, ShotList(shots=shots), shot_prompts
    )
    carry_over(pkg, parent, story, plan, shots)
    pkg.meta.budget_usd = round(
        max(parent.meta.budget_usd, 1.25 * sum(a.estimated_cost_usd for a in pkg.assets)), 2
    )
    pkg.schema_version = SCHEMA_VERSION
    return pkg


def carry_over(
    pkg: ProductionPackage,
    parent: ProductionPackage,
    story: Story,
    plan: RevisionPlan,
    shots: list[Shot],
) -> None:
    """Copy each parent node's exact content where its inputs didn't change. Verbatim, not
    re-assembled: assembly normalizes punctuation and re-derives refs location-first, either
    of which would change the render fingerprint of an untouched node."""
    by_id = {a.node_id: a for a in parent.assets}
    rerendered = set(plan.rerendered_refs)
    entity_for_ref = {ref_node_id(e): e for e in (*story.world.characters, *story.world.locations)}

    for node in pkg.assets:
        if node.type is not AssetType.IMAGE:
            continue
        old = by_id.get(node.node_id)
        if old is None or old.type is not AssetType.IMAGE:
            continue
        node.provider_hint = old.provider_hint
        node.spec = copy.deepcopy(old.spec)
        entity = entity_for_ref.get(node.node_id)
        if entity is not None and entity.id not in rerendered:
            node.prompt = old.prompt
            node.take = old.take
            node.estimated_cost_usd = old.estimated_cost_usd

    parent_entity_refs = {ref_node_id(e) for e in (*parent.world.characters, *parent.world.locations)}
    image_ids = {a.node_id for a in pkg.assets if a.type is AssetType.IMAGE}
    video_ids = {a.node_id for a in pkg.assets if a.type is AssetType.VIDEO}
    extra_images: list[Asset] = []
    videos = [a for a in pkg.assets if a.type is AssetType.VIDEO]
    for node, shot in zip(videos, shots):
        old = by_id.get(shot.id)
        if old is None or old.type is not AssetType.VIDEO:
            continue
        node.provider_hint = old.provider_hint
        node.spec = {**old.spec, "duration_s": node.spec["duration_s"], "aspect": node.spec["aspect"]}
        if plan.shot_status.get(shot.id) != "kept":
            continue
        node.prompt = old.prompt
        node.take = old.take
        node.estimated_cost_usd = old.estimated_cost_usd
        refs: list[str] = []
        for ref_id in old.reference_image_ids:
            source = by_id.get(ref_id)
            if ref_id in image_ids:
                refs.append(ref_id)
            elif source is not None and source.type is AssetType.IMAGE and ref_id not in parent_entity_refs:
                # A hand-authored image node outside the world's refs: carry it along, as a
                # clean spec (the parent may be hydrated with live state).
                extra = source.model_copy(deep=True)
                extra.status, extra.asset_url, extra.actual_cost_usd = NodeStatus.PENDING, None, None
                extra_images.append(extra)
                image_ids.add(ref_id)
                refs.append(ref_id)
        if refs:
            continuation = [d for d in node.depends_on if d in video_ids]
            node.reference_image_ids = refs
            node.depends_on = refs + continuation
    if extra_images:
        first_video = next(i for i, a in enumerate(pkg.assets) if a.type is AssetType.VIDEO)
        pkg.assets[first_video:first_video] = extra_images

    vos = voiceovers(parent)
    voiceover = next((a for a in pkg.assets if a.type is AssetType.VOICEOVER), None)
    if vos and voiceover is not None:
        old = next((a for a in vos if a.node_id == voiceover.node_id), vos[0])
        voiceover.provider_hint = old.provider_hint
        voiceover.spec = {
            **old.spec,
            "voice_id": story.brief.narration_voice_id or old.spec.get("voice_id"),
        }
        # A legacy package with several voiceover nodes collapses into assembly's single
        # narration track, spoken from the joined scene narration.
        if not plan.narration_changed and len(vos) == 1:
            voiceover.text = old.text
            voiceover.take = old.take
            voiceover.estimated_cost_usd = old.estimated_cost_usd


# --------------------------------------------------------------------------
# The revision job's work
# --------------------------------------------------------------------------
def _dirty(shots: list[Shot], plan: RevisionPlan) -> list[Shot]:
    return [s for s in shots if plan.shot_status.get(s.id, "new") != "kept"]


@dataclass
class RevisionResult:
    package: ProductionPackage
    rewritten_prompts: int


async def _run_mock(
    parent: ProductionPackage, parent_story: Story, story: Story, plan: RevisionPlan,
    on_stage: OnStage, on_detail: OnDetail,
) -> RevisionResult:
    delay = _mock_delay_s()
    replanned: dict[str, list[Shot]] = {}
    if plan.stale_scenes:
        if delay:
            await asyncio.sleep(delay)
        raw = mock_replan(story, plan.shot_targets, parent_story)
        replanned = sanitize_replanned(raw, story, plan.shot_targets, parent_story)
    shots = splice_shots(story, replanned)
    if plan.stale_scenes:
        on_detail("breakdown", {"shots": len(shots), "replanned": len(plan.stale_scenes)})
        on_stage("breakdown")

    dirty = _dirty(shots, plan)
    fresh: dict[str, ShotPrompt] = {}
    if dirty:
        ticks = min(5, len(dirty))
        for tick in range(1, ticks + 1):
            if delay:
                await asyncio.sleep(delay / ticks)
            upto = round(len(dirty) * tick / ticks)
            for shot in dirty[len(fresh):upto]:
                fresh[shot.id] = mock_prompt(shot, story)
            on_detail("prompts", {"done": upto, "total": len(dirty)})
        on_stage("prompts")

    if delay:
        await asyncio.sleep(delay)
    package = build_revision(parent, story, plan, shots, fresh)
    return RevisionResult(package=package, rewritten_prompts=len(dirty))


def _run_live(
    parent: ProductionPackage, parent_story: Story, story: Story, plan: RevisionPlan,
    on_stage: OnStage, on_detail: OnDetail,
) -> RevisionResult:
    brief = _brief_dict(story, parent)
    replanned: dict[str, list[Shot]] = {}
    if plan.stale_scenes:
        if plan.full_replan:
            raw = breakdown.run(brief, story.script, story.world)
        else:
            raw = breakdown.run_scenes(brief, story.script, story.world, plan.shot_targets)
        replanned = sanitize_replanned(raw, story, plan.shot_targets, parent_story)
    shots = splice_shots(story, replanned)
    if plan.stale_scenes:
        on_detail("breakdown", {"shots": len(shots), "replanned": len(plan.stale_scenes)})
        on_stage("breakdown")

    dirty = _dirty(shots, plan)
    fresh: dict[str, ShotPrompt] = {}
    if dirty:
        written = prompts.run(
            brief,
            ShotList(shots=dirty),
            story.world,
            on_progress=lambda done, total: on_detail("prompts", {"done": done, "total": total}),
        )
        fresh = {p.shot_id: p for p in written.prompts}
        on_stage("prompts")

    package = build_revision(parent, story, plan, shots, fresh)
    return RevisionResult(package=package, rewritten_prompts=len(dirty))


async def run_revision(
    parent: ProductionPackage,
    parent_story: Story,
    story: Story,
    plan: RevisionPlan,
    on_stage: OnStage,
    on_detail: OnDetail,
    *,
    mock: bool,
) -> RevisionResult:
    """Re-plan the stale scenes, rewrite the dirty prompts, and build the unpersisted package.
    The live path's blocking LLM calls run on a worker thread."""
    if mock:
        return await _run_mock(parent, parent_story, story, plan, on_stage, on_detail)
    return await asyncio.to_thread(_run_live, parent, parent_story, story, plan, on_stage, on_detail)
