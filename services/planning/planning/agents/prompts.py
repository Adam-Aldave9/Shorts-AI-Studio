"""Prompts agent (spec §4.1.3): shot list + world -> per-shot prompts.

For each shot it writes a vivid image-to-video prompt with the
``canonical_description`` of every entity in frame woven in. That injection is the
consistency mechanism: the same canonical wording on every shot is what keeps the
jaguar the same jaguar across thirty shots. It also picks the provider route (the
exact ``adapters.registry`` hint string) and a rough per-shot cost.

The reference-image dependencies themselves are resolved in
:mod:`planning.assembly` from each shot's tagged ``location_id`` / ``subject_ids``,
not asked of the model — the model can't know the ref node ids assembly will mint.
"""

from __future__ import annotations

from schema import World

from planning.llm import MODEL_PROMPTS, Messages, call_structured
from planning.models import ShotList, ShotPrompts

SYSTEM = (
    "You are the prompts agent in an automated film pipeline. For each shot you "
    "write one vivid image-to-video prompt describing the camera move and the action. "
    "Weave in, word for word, the canonical description of every character and "
    "location that appears in the shot — this verbatim reuse is what keeps subjects "
    "consistent across shots. Use the provider hint 'fal:pixverse-v6-i2v' for these "
    "image-to-video shots. Return one prompt per shot, keyed by the shot's id."
)


def _entity_descriptions(world: World) -> str:
    lines = []
    for c in world.characters:
        lines.append(f"  - {c.id} ({c.name}): {c.canonical_description}")
    for l in world.locations:
        lines.append(f"  - {l.id} ({l.name}): {l.canonical_description}")
    return "\n".join(lines) or "  (none)"


def _shot_lines(shot_list: ShotList) -> str:
    out = []
    for s in shot_list.shots:
        subjects = ", ".join(s.subject_ids) if s.subject_ids else "(none)"
        out.append(
            f"  [{s.id}] {s.shot_type} @ {s.location_id}, subjects: {subjects}\n"
            f"      action: {s.action}"
        )
    return "\n".join(out)


def build_prompt(brief: dict, shot_list: ShotList, world: World) -> Messages:
    """Pure: brief + shot list + world -> chat messages."""
    style = brief.get("style") or "flat 2D animation, warm earth tones"
    human = (
        f"Visual style (apply to every prompt): {style}.\n\n"
        f"Canonical entity descriptions (reuse the wording verbatim where the entity "
        f"appears):\n{_entity_descriptions(world)}\n\n"
        f"Shots:\n{_shot_lines(shot_list)}\n\n"
        "Write one image-to-video prompt per shot. For each, return the shot_id, the "
        "prompt, the provider_hint, and an estimated_cost_usd."
    )
    return [("system", SYSTEM), ("human", human)]


def parse(result: ShotPrompts | dict) -> ShotPrompts:
    return result if isinstance(result, ShotPrompts) else ShotPrompts.model_validate(result)


def run(brief: dict, shot_list: ShotList, world: World, *, call=call_structured) -> ShotPrompts:
    messages = build_prompt(brief, shot_list, world)
    raw = call(model=MODEL_PROMPTS, messages=messages, schema=ShotPrompts, temperature=0.4)
    return parse(raw)
