"""AI Film Pipeline — production package schema (the API between tiers)."""

from schema.errors import (
    TRANSIENT_CODES,
    ErrorCode,
    mock_failure_code,
    strip_mock_failure,
)
from schema.limits import PROMPT_MAX_BYTES, prompt_max_bytes, utf8_len
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
    "ErrorCode",
    "TRANSIENT_CODES",
    "PROMPT_MAX_BYTES",
    "prompt_max_bytes",
    "utf8_len",
    "mock_failure_code",
    "strip_mock_failure",
]
