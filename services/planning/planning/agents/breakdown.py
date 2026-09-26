"""Breakdown agent (spec §4.1.2): screenplay -> shot list.

Decomposes each scene into short shots, sizing the shot count from the target
duration at 3-5 s/shot (90 s / 3 s ~= 30 shots). Every shot is tagged with a
world ``location_id`` and the ``subject_ids`` of any characters in frame, so
:mod:`planning.assembly` can resolve the reference images the shot depends on. The
continuation edges (shot_n -> shot_{n-1}) are derived deterministically in assembly
from adjacency, not asked of the model.
"""

from __future__ import annotations

from schema import World

from planning.llm import MODEL_BREAKDOWN, Messages, call_structured
from planning.models import Screenplay, ShotList

_SECONDS_PER_SHOT = 3.5  # midpoint of the 3-5 s/shot pacing band

SYSTEM = (
    "You are the breakdown agent in an automated film pipeline. You convert a "
    "screenplay into a flat, ordered shot list for image-to-video generation. Each "
    "shot is 3 to 5 seconds and shows one clear action. Cover every scene, in order, "
    "and split a scene into several shots when its beat needs it. Tag each shot with "
    "exactly one location_id and the subject_ids of any characters in frame, using "
    "ONLY the world ids you are given. Hit the requested shot count closely so "
    "the shots' durations sum to the target. Return only the structured shot list."
)


def _world_lines(world: World) -> str:
    chars = "\n".join(f"  - {c.id} ({c.name})" for c in world.characters) or "  (none)"
    locs = "\n".join(f"  - {l.id} ({l.name})" for l in world.locations) or "  (none)"
    return f"Locations:\n{locs}\nCharacters:\n{chars}"


def _scene_lines(screenplay: Screenplay) -> str:
    return "\n".join(
        f"  [{s.id}] {s.heading} @ {s.location}: {s.beat}" for s in screenplay.scenes
    )


def target_shot_count(brief: dict) -> int:
    duration = float(brief.get("target_duration_s") or 90)
    return max(1, round(duration / _SECONDS_PER_SHOT))


def build_prompt(brief: dict, screenplay: Screenplay, world: World) -> Messages:
    """Pure: brief + screenplay + world -> chat messages."""
    duration = float(brief.get("target_duration_s") or 90)
    n_shots = target_shot_count(brief)
    human = (
        f"Target duration: {duration:.0f} seconds.\n"
        f"Produce about {n_shots} shots (~{_SECONDS_PER_SHOT:.0f}s each), in order.\n\n"
        f"World ids (use these exact ids for location_id / subject_ids):\n"
        f"{_world_lines(world)}\n\n"
        f"Screenplay: {screenplay.title}\nScenes:\n{_scene_lines(screenplay)}\n\n"
        "Break the screenplay into the shot list. For each shot give a stable id "
        "(shot_001, shot_002, ...), the scene_id it comes from, a shot_type, a "
        "duration in seconds, its location_id, the subject_ids in frame, and the "
        "action to animate."
    )
    return [("system", SYSTEM), ("human", human)]


def parse(result: ShotList | dict) -> ShotList:
    return result if isinstance(result, ShotList) else ShotList.model_validate(result)


def run(brief: dict, screenplay: Screenplay, world: World, *, call=call_structured) -> ShotList:
    messages = build_prompt(brief, screenplay, world)
    raw = call(model=MODEL_BREAKDOWN, messages=messages, schema=ShotList, temperature=0.3)
    return parse(raw)


SCENE_SYSTEM = (
    "You are the breakdown agent in an automated film pipeline. You break the listed scenes of "
    "a screenplay into short shots for image-to-video generation; the other scenes are shown "
    "only for context. Each shot is 3 to 5 seconds and shows one clear action. Produce shots "
    "only for the listed scenes, in order, and hit each scene's requested shot count closely. "
    "Tag each shot with its scene_id, exactly one location_id and the subject_ids of any "
    "characters in frame, using ONLY the world ids you are given. Return only the structured "
    "shot list."
)


def build_scene_prompt(
    brief: dict, screenplay: Screenplay, world: World, targets: dict[str, int]
) -> Messages:
    """Pure: the scenes to re-plan (with shot counts) + the whole script for context."""
    wanted = "\n".join(
        f"  [{s.id}] {s.heading} @ {s.location}: {s.beat} - about {targets[s.id]} shots"
        for s in screenplay.scenes
        if s.id in targets
    )
    human = (
        f"Scenes to break into shots:\n{wanted}\n\n"
        f"Whole screenplay for context: {screenplay.title}\nScenes:\n{_scene_lines(screenplay)}\n\n"
        f"World ids (use these exact ids for location_id / subject_ids):\n{_world_lines(world)}\n\n"
        "For each shot give an id, the scene_id it comes from, a shot_type, a duration in "
        "seconds, its location_id, the subject_ids in frame, and the action to animate."
    )
    return [("system", SCENE_SYSTEM), ("human", human)]


def run_scenes(
    brief: dict,
    screenplay: Screenplay,
    world: World,
    targets: dict[str, int],
    *,
    call=call_structured,
) -> ShotList:
    messages = build_scene_prompt(brief, screenplay, world, targets)
    raw = call(model=MODEL_BREAKDOWN, messages=messages, schema=ShotList, temperature=0.3)
    return parse(raw)
