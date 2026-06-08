"""Pydantic v2 models for the production package.

This module is the single source of truth for the contract between the planning
tier and the execution tier (spec §5). Both halves are versioned against
``schema_version``. The ``assets`` list is the DAG; ``depends_on`` edges express
both data dependencies (a video needs its reference image) and temporal
dependencies (a shot continues from another shot's last frame).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    VOICEOVER = "voiceover"


class NodeStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead-lettered"


class Character(BaseModel):
    id: str
    name: str
    canonical_description: str
    reference_image_ids: list[str] = Field(default_factory=list)


class Location(BaseModel):
    id: str
    name: str
    canonical_description: str
    reference_image_ids: list[str] = Field(default_factory=list)


class World(BaseModel):
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)


class Meta(BaseModel):
    title: str
    premise: str
    target_duration_s: float
    aspect_ratio: str = "16:9"
    style: str
    narration_voice_id: str
    budget_usd: float


class Asset(BaseModel):
    """One node in the DAG."""

    node_id: str
    type: AssetType
    depends_on: list[str] = Field(default_factory=list)
    provider_hint: str | None = None
    spec: dict[str, Any] = Field(default_factory=dict)
    # One of prompt / text is set depending on type.
    prompt: str | None = None
    text: str | None = None
    reference_image_ids: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float | None = None
    status: NodeStatus = NodeStatus.PENDING
    asset_url: str | None = None


class TimelineEntry(BaseModel):
    node_id: str
    in_s: float
    out_s: float
    audio_track: int | None = None


class ProductionPackage(BaseModel):
    """The replayable artifact that is the seam between the two tiers (spec §5)."""

    schema_version: str = "1.0"
    project_id: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    meta: Meta
    world: World = Field(default_factory=World)
    assets: list[Asset] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)

    def asset_by_id(self, node_id: str) -> Asset | None:
        return next((a for a in self.assets if a.node_id == node_id), None)
