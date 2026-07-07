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
(``graph._use_mock``), so the $0 path is unchanged. ``planning.world.load_world``
remains as the fixture loader (tests + optional ``WORLD_PATH`` pin).

Mirrors the other agents: a pure ``build_prompt`` + ``parse`` over the swappable
``call_structured``. Unlike ``Screenplay`` / ``ShotList`` (pure intermediates), the
world is persisted verbatim in ``ProductionPackage.world``, so it is a first-class
``schema.World`` — returned directly rather than via a draft model.
"""

from __future__ import annotations

from schema import World

from planning.llm import MODEL_WORLD, Messages, call_structured

_DEFAULT_STYLE = "flat 2D animation, warm earth tones"

SYSTEM = (
    "You are the world-building agent in an automated film pipeline. From a short "
    "premise you invent the fixed cast and set for a narrated animated film: the "
    "characters and locations every later step will draw from. Produce 2-5 "
    "characters and 3-6 locations. Give each a stable id (characters `char_*`, "
    "locations `loc_*`), a short name, and a vivid `canonical_description` that "
    "(a) is concrete enough to redraw the entity identically across dozens of shots "
    "and (b) states the visual style verbatim so every shot inherits it. Ground the "
    "world in the premise — a lighthouse premise gives a lighthouse and its keeper, "
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
        "Each needs a stable id, a short name, and a canonical_description that "
        "bakes in the visual style and is detailed enough to redraw identically "
        "across many shots. Leave reference image ids empty."
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
