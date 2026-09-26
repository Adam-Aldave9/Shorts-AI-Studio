"""World agent (spec §4.1.4): brief -> world.

Invents the film's fixed cast and set from its premise — the first step of the
planning chain, before the script is written. Each brief gets a bespoke world
(a lighthouse-keeper brief yields a lighthouse world; a robot-chef brief yields a
neon-city kitchen) instead of the single hand-authored rainforest that every run
used to share. The generated world then threads through the script, breakdown, and
prompts agents exactly like the static one did, and assembly mints one generated
reference image per entity — so a generated world flows through the same DAG
machinery with zero execution-tier changes.

The world is **generated only on the real, keyed path**. ``MOCK=true`` / no
``ANTHROPIC_API_KEY`` still short-circuits to the hand-authored rainforest package
(``graph.use_mock``), so the $0 path is unchanged. ``planning.world.load_world``
remains as the fixture loader (tests + optional ``WORLD_PATH`` pin).

Mirrors the other agents: a pure ``build_prompt`` + ``parse`` over the swappable
``call_structured``. Unlike ``Screenplay`` / ``ShotList`` (pure intermediates), the
world is persisted verbatim in ``ProductionPackage.world``, so it is a first-class
``schema.World`` — returned directly rather than via a draft model.
"""

from __future__ import annotations

from schema import World

from planning.llm import MODEL_WORLD, Messages, call_structured
from planning.models import WorldRevision

_DEFAULT_STYLE = "flat 2D animation, warm earth tones"

SYSTEM = (
    "You are the world-building agent in an automated film pipeline. From a short "
    "premise you invent the fixed cast and set for a narrated animated film: the "
    "characters and locations every later step will draw from. Produce 2-5 "
    "characters and 3-6 locations. Give each a stable id (characters `char_*`, "
    "locations `loc_*`), a short name, and a `canonical_description` concrete "
    "enough to redraw the entity identically across dozens of shots. Keep each "
    "canonical_description under 500 characters. Lead with identity-defining visual "
    "traits (age, build, face, hair, clothing, signature props), and end with one "
    "short sentence stating the visual style, worded identically for every entity. "
    "Ground the world in the premise — a lighthouse premise gives a lighthouse and its keeper, "
    "not a jungle. Do not fill in any reference image ids. Return only the "
    "structured world."
)


def build_prompt(brief: dict) -> Messages:
    """Pure: brief -> chat messages. No network, no langchain."""
    style = brief.get("style") or _DEFAULT_STYLE
    human = (
        f"Premise:\n{brief['premise']}\n\n"
        f"Visual style: {style}.\n\n"
        "Invent the world for this film: 2-5 characters and 3-6 locations. "
        "Each needs a stable id, a short name, and a canonical_description detailed "
        "enough to redraw identically across many shots. Keep each canonical_description "
        "under 500 characters. Lead with identity-defining visual traits (age, build, "
        "face, hair, clothing, signature props), and end with one short sentence stating "
        "the visual style, worded identically for every entity. Leave reference image "
        "ids empty."
    )
    return [("system", SYSTEM), ("human", human)]


def parse(result: World | dict) -> World:
    """Coerce the LLM's structured output into a World, clearing any reference image
    ids so assembly mints the canonical ``ref_{entity.id}`` image nodes (matching how
    the hand-authored world's ids become image nodes today)."""
    world = result if isinstance(result, World) else World.model_validate(result)
    for entity in (*world.characters, *world.locations):
        entity.reference_image_ids = []
    return world


def run(brief: dict, *, call=call_structured) -> World:
    messages = build_prompt(brief)
    raw = call(model=MODEL_WORLD, messages=messages, schema=World, temperature=0.9)
    return parse(raw)


REVISE_SYSTEM = (
    "You are the world-building agent in an automated film pipeline, revising an existing cast "
    "and set. You receive the current characters and locations, the film's premise and style, "
    "and the director's notes. Change only what the notes ask for. Keep every id you keep "
    "exactly as given, and keep a kept entity's canonical_description word for word unless the "
    "notes ask to change it. New characters use `char_*` ids and new locations `loc_*` ids. "
    "Keep each canonical_description under 500 characters: lead with identity-defining visual "
    "traits (age, build, face, hair, clothing, signature props) and end with one short sentence "
    "stating the visual style, worded identically for every entity. Do not remove these "
    "locations, because shots use them: {used_locations}. Return the complete world and one "
    "sentence on what you changed."
)


def _entity_lines(world: World) -> str:
    chars = "\n".join(
        f"  - {c.id} ({c.name}): {c.canonical_description}" for c in world.characters
    ) or "  (none)"
    locs = "\n".join(
        f"  - {l.id} ({l.name}): {l.canonical_description}" for l in world.locations
    ) or "  (none)"
    return f"Characters:\n{chars}\nLocations:\n{locs}"


def build_revise_prompt(
    brief: dict, world: World, notes: str, targets: list[str], used_locations: list[str]
) -> Messages:
    """Pure: current world + director's notes -> chat messages."""
    style = brief.get("style") or _DEFAULT_STYLE
    system = REVISE_SYSTEM.format(used_locations=", ".join(used_locations) or "(none)")
    human = (
        f"Premise:\n{brief['premise']}\n\n"
        f"Visual style: {style}.\n\n"
        f"Current world:\n{_entity_lines(world)}\n\n"
        f"Director's notes:\n{notes.strip() or '(none: improve it as you see fit)'}\n"
    )
    if targets:
        human += (
            f"\nRewrite only these entities: {', '.join(targets)}. Return just those entities, "
            "with the same ids."
        )
    return [("system", system), ("human", human)]


def parse_revision(result: WorldRevision | dict) -> WorldRevision:
    return result if isinstance(result, WorldRevision) else WorldRevision.model_validate(result)


def revise(
    brief: dict,
    world: World,
    notes: str,
    targets: list[str],
    used_locations: list[str],
    *,
    call=call_structured,
) -> WorldRevision:
    messages = build_revise_prompt(brief, world, notes, targets, used_locations)
    raw = call(model=MODEL_WORLD, messages=messages, schema=WorldRevision, temperature=0.7)
    return parse_revision(raw)
