"""Extract the editable planning stages (the story) from a package, and check a draft of one."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Literal

from pydantic import BaseModel
from schema import (
    Asset,
    AssetType,
    Character,
    Location,
    ProductionPackage,
    World,
)

from planning.assembly import ref_node_id
from planning.models import Brief, Scene, Screenplay, Shot, Story

SHOT_TYPES = ("establishing", "wide", "aerial", "medium", "close-up", "detail")
MIN_SHOT_S, MAX_SHOT_S = 0.5, 15.0
MIN_FILM_S, MAX_FILM_S = 10.0, 300.0
MAX_PREMISE_CHARS = 500


class StoryResponse(BaseModel):
    project_id: str
    film_id: str
    version: int
    mode: Literal["new_version", "in_place"]  # in_place while the package is unapproved
    base_hash: str
    story: Story
    prompts: dict[str, str]  # shot id -> its current video prompt, read-only context
    spoken_narration: str
    narration_diverged: bool


def _videos(pkg: ProductionPackage) -> list[Asset]:
    start = {t.node_id: t.in_s for t in pkg.timeline}
    videos = [a for a in pkg.assets if a.type is AssetType.VIDEO]
    order = {a.node_id: i for i, a in enumerate(videos)}
    return sorted(videos, key=lambda a: (a.node_id not in start, start.get(a.node_id, 0.0), order[a.node_id]))


def voiceovers(pkg: ProductionPackage) -> list[Asset]:
    return [a for a in pkg.assets if a.type is AssetType.VOICEOVER]


def spoken_narration(pkg: ProductionPackage) -> str:
    return " ".join((a.text or "").strip() for a in voiceovers(pkg) if a.text).strip()


def scene_narration(script: Screenplay) -> str:
    return " ".join(s.narration.strip() for s in script.scenes if s.narration).strip()


def _normalized(text: str) -> str:
    return " ".join(text.split())


def narration_diverged(pkg: ProductionPackage, story: Story) -> bool:
    return _normalized(spoken_narration(pkg)) != _normalized(scene_narration(story.script))


def entity_by_ref(world: World) -> dict[str, Character | Location]:
    """ref node id -> the entity it pictures (the same ids assembly mints)."""
    out: dict[str, Character | Location] = {}
    for entity in (*world.characters, *world.locations):
        ids = entity.reference_image_ids or [ref_node_id(entity)]
        for ref_id in ids:
            out.setdefault(ref_id, entity)
    return out


def _location_named(world: World, text: str) -> str | None:
    wanted = text.strip().lower()
    return next((l.id for l in world.locations if l.name.strip().lower() == wanted), None)


def _infer_tags(asset: Asset, world: World, scene_location: str) -> tuple[str, list[str]]:
    by_ref = entity_by_ref(world)
    location_id = ""
    subjects: list[str] = []
    for ref_id in asset.reference_image_ids:
        entity = by_ref.get(ref_id)
        if isinstance(entity, Location) and not location_id:
            location_id = entity.id
        elif isinstance(entity, Character) and entity.id not in subjects:
            subjects.append(entity.id)
    if not location_id:
        location_id = _location_named(world, scene_location) or (
            world.locations[0].id if world.locations else ""
        )
    return location_id, subjects


def story_from_package(pkg: ProductionPackage) -> Story:
    vos = voiceovers(pkg)
    voice = (vos[0].spec.get("voice_id") if vos else None) or pkg.meta.narration_voice_id
    brief = Brief(
        premise=pkg.meta.premise,
        target_duration_s=pkg.meta.target_duration_s,
        style=pkg.meta.style,
        narration_voice_id=voice,
    )
    world = pkg.world.model_copy(deep=True)
    narrative = pkg.narrative

    if narrative is not None and narrative.scenes:
        scenes = [
            Scene(id=s.id, heading=s.heading, location=s.location, beat=s.beat, narration=s.narration)
            for s in narrative.scenes
        ]
        logline = narrative.logline
    else:
        scenes = [
            Scene(
                id="scene_01",
                heading=pkg.meta.title,
                location=world.locations[0].name if world.locations else "",
                beat=pkg.meta.premise,
                narration=spoken_narration(pkg),
            )
        ]
        logline = narrative.logline if narrative is not None else ""
    script = Screenplay(title=pkg.meta.title, logline=logline, scenes=scenes)

    scene_location = {s.id: s.location for s in scenes}
    tagged = {s.node_id: s for s in narrative.shots} if narrative is not None else {}
    shots: list[Shot] = []
    for asset in _videos(pkg):
        ns = tagged.get(asset.node_id)
        scene_id = ns.scene_id if ns is not None and ns.scene_id in scene_location else scenes[0].id
        if ns is not None and ns.location_id:
            location_id, subjects = ns.location_id, list(ns.subject_ids)
        else:
            location_id, subjects = _infer_tags(asset, world, scene_location[scene_id])
        shots.append(
            Shot(
                id=asset.node_id,
                scene_id=scene_id,
                shot_type=(ns.shot_type if ns is not None and ns.shot_type else "wide"),
                duration_s=float(asset.spec.get("duration_s") or 3.0),
                location_id=location_id,
                subject_ids=subjects,
                action=ns.action if ns is not None else "",
            )
        )
    return Story(brief=brief, world=world, script=script, shots=shots)


def story_hash(story: Story) -> str:
    return hashlib.sha256(story.model_dump_json().encode("utf-8")).hexdigest()[:16]


def validate_story(story: Story) -> list[str]:
    errors: list[str] = []
    premise = story.brief.premise.strip()
    if not premise or len(story.brief.premise) > MAX_PREMISE_CHARS:
        errors.append(f"The premise must be 1-{MAX_PREMISE_CHARS} characters.")
    if not MIN_FILM_S <= story.brief.target_duration_s <= MAX_FILM_S:
        errors.append(f"The length must be {MIN_FILM_S:.0f}-{MAX_FILM_S:.0f} seconds.")

    world = story.world
    seen: set[str] = set()
    for kind, prefix, entities in (
        ("character", "char_", world.characters),
        ("location", "loc_", world.locations),
    ):
        for entity in entities:
            if entity.id in seen:
                errors.append(f"Duplicate world id {entity.id!r}.")
            seen.add(entity.id)
            if not entity.id.startswith(prefix):
                errors.append(f"The {kind} id {entity.id!r} must start with {prefix!r}.")
            if not entity.name.strip():
                errors.append(f"The {kind} {entity.id!r} needs a name.")
            if not entity.canonical_description.strip():
                errors.append(f"The {kind} {entity.name or entity.id!r} needs a description.")
    if not world.locations:
        errors.append("The world needs at least one location.")

    scene_ids: set[str] = set()
    for scene in story.script.scenes:
        if scene.id in scene_ids:
            errors.append(f"Duplicate scene id {scene.id!r}.")
        scene_ids.add(scene.id)
        if not scene.heading.strip():
            errors.append(f"Scene {scene.id!r} needs a heading.")
    if not story.script.scenes:
        errors.append("The script needs at least one scene.")

    location_ids = {l.id for l in world.locations}
    character_ids = {c.id for c in world.characters}
    shot_ids: set[str] = set()
    for shot in story.shots:
        if shot.id in shot_ids:
            errors.append(f"Duplicate shot id {shot.id!r}.")
        shot_ids.add(shot.id)
        if shot.scene_id not in scene_ids:
            errors.append(f"Shot {shot.id!r} belongs to unknown scene {shot.scene_id!r}.")
        if shot.location_id not in location_ids:
            errors.append(f"Shot {shot.id!r} is set at unknown location {shot.location_id!r}.")
        for subject in shot.subject_ids:
            if subject not in character_ids:
                errors.append(f"Shot {shot.id!r} shows unknown character {subject!r}.")
        if not MIN_SHOT_S <= shot.duration_s <= MAX_SHOT_S:
            errors.append(
                f"Shot {shot.id!r} must last {MIN_SHOT_S}-{MAX_SHOT_S:.0f} seconds."
            )
    return errors


def next_scene_id(existing: Iterable[str]) -> str:
    numbers = [int(m.group(1)) for sid in existing if (m := re.fullmatch(r"scene_(\d+)", sid))]
    return f"scene_{max(numbers, default=0) + 1:02d}"


def unique_entity_id(name: str, prefix: str, existing: Iterable[str]) -> str:
    taken = set(existing)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "new"
    candidate = f"{prefix}{slug}"
    n = 2
    while candidate in taken:
        candidate = f"{prefix}{slug}_{n}"
        n += 1
    return candidate
