"""AI rewrite proposals for one studio stage. Never persisted: the user accepts or discards them.

Whatever the model returns is merged deterministically into the draft, so every proposal
yields a valid story: kept entities keep their reference image ids, locations still in use
survive, and re-planned shots only ever use known ids.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from schema import Character, Location, World

from planning.agents import breakdown, script, world as world_agent
from planning.models import Scene, Screenplay, Story
from planning.revision import mock_replan, sanitize_replanned, shot_targets, splice_shots
from planning.story import next_scene_id, unique_entity_id

MOCK_NOTE = "MOCK mode: deterministic stand-in; no LLM was called."


class ProposalRequest(BaseModel):
    stage: Literal["world", "script", "shots"]
    story: Story  # the studio's current draft
    targets: list[str] = []  # entity ids (world) or scene ids (script, shots); empty = whole stage
    notes: str = ""


class ProposalResponse(BaseModel):
    story: Story  # the request's story with the proposal applied
    changed: list[str]
    notes: str


class ProposalError(ValueError):
    """The request can't be proposed for (maps to 422)."""


def _brief(story: Story) -> dict:
    return story.brief.model_dump()


def _entities(w: World) -> dict[str, Character | Location]:
    return {e.id: e for e in (*w.characters, *w.locations)}


def _changed_entities(before: World, after: World) -> list[str]:
    b, a = _entities(before), _entities(after)
    changed = [
        eid for eid, e in a.items()
        if eid not in b or (b[eid].name, b[eid].canonical_description) != (e.name, e.canonical_description)
    ]
    return changed + [eid for eid in b if eid not in a]


def merge_world(story: Story, proposed: World, targets: list[str]) -> tuple[Story, str]:
    """Apply a proposed world to the draft. Returns the new story and a note on anything
    the merge had to undo."""
    draft = story.model_copy(deep=True)
    current = _entities(draft.world)

    if targets:
        returned = _entities(proposed)
        for eid in targets:
            if eid in current and eid in returned:
                current[eid].name = returned[eid].name or current[eid].name
                current[eid].canonical_description = (
                    returned[eid].canonical_description or current[eid].canonical_description
                )
        return draft, ""

    taken: set[str] = set()
    characters: list[Character] = []
    locations: list[Location] = []
    for kind, prefix, cls, items, bucket in (
        ("character", "char_", Character, proposed.characters, characters),
        ("location", "loc_", Location, proposed.locations, locations),
    ):
        for entity in items:
            old = current.get(entity.id)
            if isinstance(old, cls) and entity.id not in taken:
                eid, refs = entity.id, list(old.reference_image_ids)
            else:
                base = entity.id if entity.id.startswith(prefix) and entity.id not in taken and entity.id not in current else ""
                eid = base or unique_entity_id(entity.name or kind, prefix, taken | set(current))
                refs = []
            taken.add(eid)
            bucket.append(
                cls(id=eid, name=entity.name, canonical_description=entity.canonical_description,
                    reference_image_ids=refs)
            )

    used = {s.location_id for s in draft.shots}
    restored = [l for l in draft.world.locations if l.id in used and l.id not in taken]
    locations.extend(l.model_copy(deep=True) for l in restored)
    if not locations:
        locations = [l.model_copy(deep=True) for l in draft.world.locations]
        restored = list(draft.world.locations)
    character_ids = {c.id for c in characters}
    for shot in draft.shots:
        shot.subject_ids = [s for s in shot.subject_ids if s in character_ids]
    draft.world = World(characters=characters, locations=locations)
    note = ""
    if restored:
        note = f"Kept {', '.join(l.name for l in restored)}, which shots still use."
    return draft, note


def merge_script(story: Story, proposed: Screenplay, targets: list[str]) -> Story:
    draft = story.model_copy(deep=True)
    if targets:
        returned = {s.id: s for s in proposed.scenes}
        for scene in draft.script.scenes:
            new = returned.get(scene.id)
            if scene.id in targets and new is not None:
                scene.heading, scene.location = new.heading, new.location
                scene.beat, scene.narration = new.beat, new.narration
        return draft

    existing = {s.id for s in draft.script.scenes}
    seen: set[str] = set()
    scenes: list[Scene] = []
    for scene in proposed.scenes:
        sid = scene.id
        if sid not in existing or sid in seen:
            sid = next_scene_id(existing | seen | {s.id for s in scenes})
        seen.add(sid)
        scenes.append(scene.model_copy(update={"id": sid}))
    kept = {s.id for s in scenes}
    draft.script = Screenplay(title=proposed.title or draft.script.title,
                              logline=proposed.logline, scenes=scenes)
    draft.shots = [s for s in draft.shots if s.scene_id in kept]
    return draft


def _changed_scenes(before: Story, after: Story) -> list[str]:
    b = {s.id: s for s in before.script.scenes}
    a = {s.id: s for s in after.script.scenes}
    changed = [sid for sid, s in a.items() if sid not in b or b[sid] != s]
    return changed + [sid for sid in b if sid not in a]


def propose(parent_story: Story, request: ProposalRequest, *, mock: bool) -> ProposalResponse:
    """Blocking (LLM calls on the live path); the API runs it on a worker thread."""
    story = request.story
    notes = request.notes.strip()

    if request.stage == "world":
        if mock:
            draft = story.model_copy(deep=True)
            for entity in (*draft.world.characters, *draft.world.locations):
                if not request.targets or entity.id in request.targets:
                    entity.canonical_description += f" [mock rewrite: {notes or 'no notes'}]"
            summary = MOCK_NOTE
        else:
            used = sorted({s.location_id for s in story.shots})
            revision = world_agent.revise(_brief(story), story.world, notes, request.targets, used)
            draft, restored = merge_world(story, revision.world, request.targets)
            summary = " ".join(filter(None, [revision.notes, restored]))
        return ProposalResponse(
            story=draft, changed=_changed_entities(story.world, draft.world), notes=summary
        )

    if request.stage == "script":
        if mock:
            draft = story.model_copy(deep=True)
            for scene in draft.script.scenes:
                if not request.targets or scene.id in request.targets:
                    scene.beat += f" (mock rewrite: {notes or 'no notes'})"
            summary = MOCK_NOTE
        else:
            revision = script.revise(_brief(story), story.world, story.script, notes, request.targets)
            draft = merge_script(story, revision.screenplay, request.targets)
            summary = revision.notes
        return ProposalResponse(story=draft, changed=_changed_scenes(story, draft), notes=summary)

    scene_ids = {s.id for s in story.script.scenes}
    targets = [t for t in request.targets if t in scene_ids]
    if not targets:
        raise ProposalError("Choose the scenes whose shots to re-plan.")
    counts = shot_targets(parent_story, story, targets)
    if mock:
        raw = mock_replan(story, counts, parent_story)
        summary = MOCK_NOTE
    else:
        raw = breakdown.run_scenes(_brief(story), story.script, story.world, counts)
        summary = f"Re-planned the shots of {len(targets)} scene{'s' if len(targets) != 1 else ''}."
    others = story.model_copy(update={"shots": [s for s in story.shots if s.scene_id not in targets]})
    replanned = sanitize_replanned(raw, others, counts, parent_story)
    draft = story.model_copy(deep=True)
    draft.shots = splice_shots(draft, replanned)
    return ProposalResponse(story=draft, changed=targets, notes=summary)
