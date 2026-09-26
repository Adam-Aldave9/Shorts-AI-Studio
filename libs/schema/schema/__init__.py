"""AI Film Pipeline — production package schema (the API between tiers)."""

from schema.errors import (
    TRANSIENT_CODES,
    ErrorCode,
    mock_failure_code,
    strip_mock_failure,
)
from schema.fingerprint import fingerprints, render_inputs, whole_seconds
from schema.lineage import film_id_of, version_of
from schema.limits import PROMPT_MAX_BYTES, prompt_max_bytes, utf8_len
from schema.models import (
    Asset,
    AssetType,
    Character,
    Lineage,
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

SCHEMA_VERSION = "1.2"

__all__ = [
    "Asset",
    "AssetType",
    "Character",
    "Lineage",
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
    "film_id_of",
    "version_of",
    "fingerprints",
    "render_inputs",
    "whole_seconds",
]
