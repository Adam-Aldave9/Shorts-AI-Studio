"""Script agent (spec §4.1.1): brief -> screenplay.

Turns a one-line premise into scenes with beats and voiceover narration, written
around the fixed cast and locations of the world so the downstream breakdown
can map every shot onto a known entity. Narration is voiceover text spoken over the
footage — never on-screen dialogue.
"""

from __future__ import annotations

from schema import World

from planning.llm import MODEL_SCRIPT, Messages, call_structured
from planning.models import Screenplay, ScreenplayRevision

SYSTEM = (
    "You are the script agent in an automated film pipeline. You turn a short "
    "premise into a tight screenplay for a narrated explainer film: a sequence of "
    "scenes, each with a single visual beat and a line of voiceover narration. "
    "Narration is spoken over the footage; it is never on-screen dialogue. Write "
    "for the fixed cast and locations you are given — every scene should take place "
    "in one of the listed locations and feature the listed characters where natural. "
    "Pace the scenes so their narration, read aloud, roughly fills the target "
    "duration. Return only the structured screenplay."
)


def _world_lines(world: World) -> str:
    chars = "\n".join(f"  - {c.id} ({c.name})" for c in world.characters) or "  (none)"
    locs = "\n".join(f"  - {l.id} ({l.name})" for l in world.locations) or "  (none)"
    return f"Characters:\n{chars}\nLocations:\n{locs}"


def build_prompt(brief: dict, world: World) -> Messages:
    """Pure: brief + world -> chat messages. No network, no langchain."""
    duration = float(brief.get("target_duration_s") or 90)
    style = brief.get("style") or "flat 2D animation, warm earth tones"
    human = (
        f"Premise:\n{brief['premise']}\n\n"
        f"Target duration: {duration:.0f} seconds.\n"
        f"Visual style: {style}.\n\n"
        f"Available world (fixed cast and locations):\n{_world_lines(world)}\n\n"
        "Write the screenplay: a title, a logline, and an ordered list of scenes. "
        "Each scene needs a heading, the location it plays in, the visual beat, and "
        "its narration line."
    )
    return [("system", SYSTEM), ("human", human)]


def parse(result: Screenplay | dict) -> Screenplay:
    """Coerce the LLM's structured output (model or dict) into a Screenplay."""
    return result if isinstance(result, Screenplay) else Screenplay.model_validate(result)


def run(brief: dict, world: World, *, call=call_structured) -> Screenplay:
    messages = build_prompt(brief, world)
    raw = call(model=MODEL_SCRIPT, messages=messages, schema=Screenplay, temperature=0.8)
    return parse(raw)


REVISE_SYSTEM = (
    "You are the script agent in an automated film pipeline, revising an existing screenplay. "
    "You receive the current screenplay, the fixed cast and locations, the premise, the target "
    "duration and the director's notes. Change only what the notes ask for; keep every other "
    "scene word for word, with its id. Narration is voiceover spoken over the footage, never "
    "on-screen dialogue. Every scene plays in one of the listed locations. Pace the narration "
    "so that, read aloud, it roughly fills the target duration. Return the complete screenplay "
    "and one sentence on what you changed."
)


def _screenplay_lines(screenplay: Screenplay) -> str:
    return "\n".join(
        f"  [{s.id}] {s.heading} @ {s.location}\n      beat: {s.beat}\n      narration: {s.narration}"
        for s in screenplay.scenes
    ) or "  (no scenes)"


def build_revise_prompt(
    brief: dict, world: World, screenplay: Screenplay, notes: str, targets: list[str]
) -> Messages:
    """Pure: current screenplay + director's notes -> chat messages."""
    duration = float(brief.get("target_duration_s") or 90)
    human = (
        f"Premise:\n{brief['premise']}\n\n"
        f"Target duration: {duration:.0f} seconds.\n\n"
        f"Available world (fixed cast and locations):\n{_world_lines(world)}\n\n"
        f"Current screenplay: {screenplay.title}\nLogline: {screenplay.logline}\n"
        f"Scenes:\n{_screenplay_lines(screenplay)}\n\n"
        f"Director's notes:\n{notes.strip() or '(none: improve it as you see fit)'}\n"
    )
    if targets:
        human += (
            f"\nRewrite only these scenes: {', '.join(targets)}. Return just those scenes, "
            "keeping their ids."
        )
    return [("system", REVISE_SYSTEM), ("human", human)]


def parse_revision(result: ScreenplayRevision | dict) -> ScreenplayRevision:
    if isinstance(result, ScreenplayRevision):
        return result
    return ScreenplayRevision.model_validate(result)


def revise(
    brief: dict,
    world: World,
    screenplay: Screenplay,
    notes: str,
    targets: list[str],
    *,
    call=call_structured,
) -> ScreenplayRevision:
    messages = build_revise_prompt(brief, world, screenplay, notes, targets)
    raw = call(model=MODEL_SCRIPT, messages=messages, schema=ScreenplayRevision, temperature=0.7)
    return parse_revision(raw)
