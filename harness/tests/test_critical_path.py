"""The two critical-path floors for the flagship — the Graph B reference numbers
(spec §12.2). Both come from one shared implementation (``scheduler.dag.Dag``),
the content floor by default and the render-time floor via the harness's
latency weight, so the CLI / scheduler / notebook never drift."""

from __future__ import annotations

from pathlib import Path

from schema import ProductionPackage
from scheduler.dag import Dag

from harness.cli import _latency_weight

FIXTURE = Path(__file__).resolve().parents[2] / "example-packages" / "rainforest-90s.json"


def _pkg() -> ProductionPackage:
    return ProductionPackage.model_validate_json(FIXTURE.read_text())


def test_content_floor_is_seven_seconds():
    # Longest chain by spec.duration_s: ref (no duration_s -> default 1.0)
    # + shot_001 (3.0) + shot_002 (3.0) = 7.0. Unchanged from the old behavior.
    assert Dag(_pkg()).critical_path_estimate() == 7.0


def test_render_floor_is_eightyeight_seconds():
    # Same ref -> shot_001 -> shot_002 chain weighted by mock provider latency:
    # image 8 + video 40 + video 40 = 88.0 -- the wall-clock no parallelism beats.
    assert Dag(_pkg()).critical_path_estimate(weight=_latency_weight) == 88.0
