"""Intermediate, agent-facing models for the planning chain (spec §4.1).

These are *not* the production-package schema (``schema.ProductionPackage``) — they
are the structured-output shapes each agent returns, the rungs the chain climbs on
its way to a package:

    Script    -> Screenplay   (scenes + beats + narration lines)
    Breakdown -> ShotList     (shots tagged with type / duration / subjects / location)
    Prompts   -> ShotPrompts  (per-shot Flux/motion prompt + provider hint + cost)

Keeping them separate from the schema means :mod:`planning.assembly` owns the one
mapping from "creative intent" to "DAG of provider calls", and the agents stay
small and unit-testable. Each is fed to ``with_structured_output`` so the LLM
returns schema-shaped JSON, not free text to regex (spec §4.4).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Script agent — the screenplay
# --------------------------------------------------------------------------


class Scene(BaseModel):
    """One beat of the film: a location, what happens in frame, and its narration."""

    id: str = Field(description="Stable scene id, e.g. 'scene_01'.")
    heading: str = Field(description="Short slug for the scene, e.g. 'Canopy at dawn'.")
    location: str = Field(
        description="Where the scene takes place — prefer a world location name."
    )
    beat: str = Field(description="What the viewer sees: the visual action of the scene.")
    narration: str = Field(
        description="Voiceover line(s) for this scene. Narration is spoken over the "
        "footage — never on-screen dialogue."
    )


class Screenplay(BaseModel):
    title: str = Field(description="A short, evocative title for the film.")
    logline: str = Field(description="One-sentence summary of the film.")
    scenes: list[Scene] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Breakdown agent — the shot list
# --------------------------------------------------------------------------


class Shot(BaseModel):
    """One shot derived from a scene. ``location_id`` / ``subject_ids`` reference
    world entity ids so :mod:`planning.assembly` can resolve the reference
    images each shot depends on."""

    id: str = Field(description="Stable shot id, e.g. 'shot_001'.")
    scene_id: str = Field(description="The scene this shot belongs to.")
    shot_type: str = Field(
        description="establishing | wide | aerial | medium | close-up | detail"
    )
    duration_s: float = Field(default=3.0, description="Shot length in seconds (3-5s).")
    location_id: str = Field(description="World location id, e.g. 'loc_canopy'.")
    subject_ids: list[str] = Field(
        default_factory=list,
        description="World character ids visible in the shot, e.g. ['char_jaguar'].",
    )
    action: str = Field(description="The motion/action to animate (drives the i2v prompt).")


class ShotList(BaseModel):
    shots: list[Shot] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Prompts agent — per-shot provider prompts
# --------------------------------------------------------------------------


class ShotPrompt(BaseModel):
    """The render-ready prompt for one shot. The prose is where the world's
    ``canonical_description`` strings are woven in — that injection is the
    consistency mechanism (spec §4.1.3)."""

    shot_id: str = Field(description="The shot this prompt is for (matches Shot.id).")
    prompt: str = Field(
        description="Vivid image-to-video prompt with the canonical descriptions of "
        "every referenced entity baked in."
    )
    provider_hint: str = Field(
        default="fal:pixverse-v6-i2v",
        description="Adapter route — use the exact registry hint string.",
    )
    estimated_cost_usd: float = Field(default=0.1, description="Rough per-shot cost.")


class ShotPrompts(BaseModel):
    prompts: list[ShotPrompt] = Field(default_factory=list)
