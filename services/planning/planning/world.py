"""Load the hand-authored world (spec §4.1.4).

The world is the fixed cast + set of the film: canonical character/location
descriptions plus the ids of their pre-generated reference images. Its JSON shape
already matches :class:`schema.World` (the leading ``_comment`` is ignored by
Pydantic), so loading is a parse + validate.

The path defaults to ``data/worlds/amazon-rainforest.json`` at the repo root and
is overridable via ``WORLD_PATH`` so the Docker image (item 7) can point at
wherever it copies the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from schema import World

# services/planning/planning/world.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WORLD = _REPO_ROOT / "data" / "worlds" / "amazon-rainforest.json"


def world_path() -> Path:
    return Path(os.environ.get("WORLD_PATH") or _DEFAULT_WORLD)


def load_world(path: str | Path | None = None) -> World:
    """Parse + validate the world into a :class:`schema.World`."""
    p = Path(path) if path is not None else world_path()
    data = json.loads(p.read_text(encoding="utf-8"))
    data.pop("_comment", None)  # documentation-only field, not part of the schema
    return World.model_validate(data)
