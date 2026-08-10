"""AI Film Pipeline — production package schema (the API between tiers)."""

from schema.models import (
    Asset,
    AssetType,
    Character,
    Location,
    Meta,
    Narrative,
    NarrativeScene,
    NarrativeShot,
    NodeStatus,
    ProductionPackage,
    TimelineEntry,
    World,
)

SCHEMA_VERSION = "1.1"

__all__ = [
    "Asset",
    "AssetType",
    "Character",
    "Location",
    "Meta",
    "Narrative",
    "NarrativeScene",
    "NarrativeShot",
    "NodeStatus",
    "ProductionPackage",
    "TimelineEntry",
    "World",
    "SCHEMA_VERSION",
]
