"""Prompts agent (spec §4.1.3): shot list + world -> per-shot prompts.

For each shot it writes a vivid image-to-video prompt with the
``canonical_description`` of every entity in frame woven in. That injection is the
consistency mechanism: the same canonical wording on every shot is what keeps the
jaguar the same jaguar across thirty shots. Each prompt must also fit the video
provider's byte limit: the agent is told the budget, and any prompt that comes back
over it gets one tightening call. Assembly fits whatever is still over.

The reference-image dependencies themselves are resolved in
:mod:`planning.assembly` from each shot's tagged ``location_id`` / ``subject_ids``,
not asked of the model — the model can't know the ref node ids assembly will mint.
"""

from __future__ import annotations

import logging
from typing import Callable

from schema import PROMPT_MAX_BYTES, World, utf8_len

from planning.assembly import VIDEO_HINT
from planning.llm import MODEL_PROMPTS, Messages, call_structured
from planning.models import ShotList, ShotPrompt, ShotPrompts

log = logging.getLogger(__name__)

# The shot list is written a batch at a time rather than in one call. The consistency
# mechanism lives in the prompt text (verbatim canonical descriptions), not in seeing
# every shot at once, so splitting costs nothing — and it keeps each response clear of
# ``call_structured``'s 8192-token ceiling, which 30 prose prompts can plausibly breach.
# Batches are contiguous so scene-adjacent shots stay together.
PROMPT_BATCH_SIZE = 6

MAX_BYTES = PROMPT_MAX_BYTES[VIDEO_HINT]


def _target_chars(max_bytes: int) -> int:
    # ~10% headroom so a checkpoint edit rarely forces condensation.
    return int(max_bytes * 0.9)


def _system(max_bytes: int, target_chars: int) -> str:
    return (
        "You are the prompts agent in an automated film pipeline. For each shot you "
        "write one vivid image-to-video prompt describing the camera move and the action. "
        "The video model animates the shot's location reference image, so describe the "
        "setting in one short clause instead of repeating the location's description. "
        "Weave in, word for word, the canonical description of each character in the "
        "shot; this verbatim reuse keeps characters consistent across shots. If the "
        "prompt would exceed its budget, keep the focal character's description verbatim "
        "and condense the others to their name plus two or three distinctive visual "
        "traits. End every prompt with the film's style sentence, once. Every prompt has "
        f"a hard limit of {max_bytes} UTF-8 bytes; stay under {target_chars} characters "
        "and use plain ASCII punctuation (no em dashes or curly quotes). Video providers "
        "run automated content filters: convey danger and conflict through tension, "
        "motion and expression, not graphic violence, injuries, blood, or weapons aimed "
        "or fired at people. Return one prompt per shot, keyed by the shot's id."
    )


def _character_descriptions(world: World) -> str:
    lines = [f"  - {c.id} ({c.name}): {c.canonical_description}" for c in world.characters]
    return "\n".join(lines) or "  (none)"


def _location_descriptions(world: World) -> str:
    lines = [f"  - {l.id} ({l.name}): {l.canonical_description}" for l in world.locations]
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


def build_prompt(
    brief: dict,
    shot_list: ShotList,
    world: World,
    *,
    max_bytes: int = MAX_BYTES,
    note: str | None = None,
) -> Messages:
    """Pure: brief + shot list + world -> chat messages."""
    style = brief.get("style") or "flat 2D animation, warm earth tones"
    target_chars = _target_chars(max_bytes)
    human = (
        f"Visual style (apply to every prompt): {style}.\n\n"
        f"Characters (reuse the wording verbatim for characters in the shot):\n"
        f"{_character_descriptions(world)}\n\n"
        f"Locations (the start frame already shows these; reference them in one short "
        f"clause):\n{_location_descriptions(world)}\n\n"
        f"Shots:\n{_shot_lines(shot_list)}\n\n"
        f"Budget: each prompt at most {max_bytes} UTF-8 bytes (aim for under "
        f"{target_chars} characters).\n"
        + (f"{note}\n" if note else "")
        + "Write one image-to-video prompt per shot. For each, return the shot_id, the "
        "prompt, the provider_hint, and an estimated_cost_usd."
    )
    return [("system", _system(max_bytes, target_chars)), ("human", human)]


def parse(result: ShotPrompts | dict) -> ShotPrompts:
    return result if isinstance(result, ShotPrompts) else ShotPrompts.model_validate(result)


def _tighten(
    brief: dict,
    batch: ShotList,
    world: World,
    written: list[ShotPrompt],
    *,
    call,
    max_bytes: int,
) -> list[ShotPrompt]:
    """One extra call for any prompt over ``max_bytes``; never fails the batch."""
    over = {p.shot_id: utf8_len(p.prompt) for p in written if utf8_len(p.prompt) > max_bytes}
    if not over:
        return written
    sizes = ", ".join(f"{sid} came back at {n} bytes" for sid, n in over.items())
    note = (
        f"Rewrite these shots: {sizes}, over the {max_bytes}-byte limit. Rewrite each in at "
        f"most {max_bytes} bytes: one-clause setting, condense non-focal characters, keep "
        "the style sentence."
    )
    retry_shots = ShotList(shots=[s for s in batch.shots if s.id in over])
    try:
        raw = call(
            model=MODEL_PROMPTS,
            messages=build_prompt(brief, retry_shots, world, max_bytes=max_bytes, note=note),
            schema=ShotPrompts,
            temperature=0.4,
        )
        rewritten = {p.shot_id: p for p in parse(raw).prompts if p.shot_id in over}
    except Exception:
        log.warning("prompt tighten pass failed for %s; keeping originals", list(over), exc_info=True)
        return written
    return [rewritten.get(p.shot_id, p) for p in written]


def run(
    brief: dict,
    shot_list: ShotList,
    world: World,
    *,
    call=call_structured,
    batch_size: int = PROMPT_BATCH_SIZE,
    on_progress: Callable[[int, int], None] | None = None,
    max_bytes: int = MAX_BYTES,
) -> ShotPrompts:
    """Write one prompt per shot, ``batch_size`` shots per LLM call, reporting
    ``on_progress(done, total)`` after each batch (this is the longest stage, so the
    Planning screen shows a real fraction rather than an opaque spinner)."""
    shots = shot_list.shots
    collected: list[ShotPrompt] = []
    for start in range(0, len(shots), batch_size):
        batch = ShotList(shots=shots[start : start + batch_size])
        raw = call(
            model=MODEL_PROMPTS,
            messages=build_prompt(brief, batch, world, max_bytes=max_bytes),
            schema=ShotPrompts,
            temperature=0.4,
        )
        written = _tighten(brief, batch, world, parse(raw).prompts, call=call, max_bytes=max_bytes)
        collected.extend(written)
        if on_progress is not None:
            on_progress(min(start + batch_size, len(shots)), len(shots))
    return ShotPrompts(prompts=collected)
