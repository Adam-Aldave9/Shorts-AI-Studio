"""No-network checks for the deterministic validator (spec §4.1.5).

Builds a minimal package that passes every gate, then mutates one thing per test
to trip exactly one error class — acyclicity, dangling ``depends_on``,
video-without-ref, budget-exceeded, and duration-tolerance.
"""

from __future__ import annotations

from schema import (
    Asset,
    AssetType,
    Meta,
    Narrative,
    NarrativeScene,
    NarrativeShot,
    ProductionPackage,
)

from validator import validate_package


def _valid_pkg() -> ProductionPackage:
    """A small package that passes every check: one ref image + one shot that
    references it, shot duration == target, est cost under budget."""
    return ProductionPackage(
        project_id="p_test",
        meta=Meta(
            title="T",
            premise="P",
            target_duration_s=3.0,
            style="s",
            narration_voice_id="v_meta",
            budget_usd=15.0,
        ),
        assets=[
            Asset(
                node_id="ref_a",
                type=AssetType.IMAGE,
                provider_hint="fal:flux-schnell",
                prompt="a tree",
                estimated_cost_usd=0.01,
            ),
            Asset(
                node_id="shot_a",
                type=AssetType.VIDEO,
                depends_on=["ref_a"],
                reference_image_ids=["ref_a"],
                provider_hint="fal:pixverse-v6-i2v",
                spec={"duration_s": 3.0},
                prompt="a tree sways",
                estimated_cost_usd=0.5,
            ),
        ],
    )


def test_valid_package_passes():
    report = validate_package(_valid_pkg())
    assert report.ok
    assert report.errors == []


def test_cycle_is_rejected():
    pkg = _valid_pkg()
    # Two image nodes that depend on each other form a cycle.
    pkg.assets = [
        Asset(node_id="ref_a", type=AssetType.IMAGE, depends_on=["ref_b"], prompt="x"),
        Asset(node_id="ref_b", type=AssetType.IMAGE, depends_on=["ref_a"], prompt="y"),
    ]
    report = validate_package(pkg)
    assert not report.ok
    assert any("cycle" in e for e in report.errors)


def test_dangling_depends_on_is_rejected():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").depends_on = ["ghost"]
    report = validate_package(pkg)
    assert not report.ok
    assert any("depends on unknown node 'ghost'" in e for e in report.errors)


def test_video_without_reference_image_is_rejected():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").reference_image_ids = []
    report = validate_package(pkg)
    assert not report.ok
    assert any("shot_a has no reference image" in e for e in report.errors)


def test_unknown_image_reference_is_rejected():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").reference_image_ids = ["ref_missing"]
    report = validate_package(pkg)
    assert not report.ok
    assert any("references unknown image 'ref_missing'" in e for e in report.errors)


def test_budget_exceeded_is_rejected():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").estimated_cost_usd = 100.0  # > budget_usd (15)
    report = validate_package(pkg)
    assert not report.ok
    assert any("exceeds budget" in e for e in report.errors)


def test_duration_outside_tolerance_is_rejected():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").spec = {"duration_s": 30.0}  # target is 3s, tol 5s
    report = validate_package(pkg)
    assert not report.ok
    assert any("shot durations sum to" in e for e in report.errors)


def test_duration_within_tolerance_passes():
    pkg = _valid_pkg()
    pkg.asset_by_id("shot_a").spec = {"duration_s": 6.0}  # 3s off target, within 5s tol
    report = validate_package(pkg)
    assert report.ok


def test_unsupported_schema_version_is_rejected():
    pkg = _valid_pkg()
    pkg.schema_version = "9.9"
    report = validate_package(pkg)
    assert not report.ok
    assert any("unsupported schema_version" in e for e in report.errors)


def test_schema_1_0_package_still_passes():
    """Packages written before the narrative block must keep re-running."""
    pkg = _valid_pkg()
    pkg.schema_version = "1.0"
    pkg.narrative = None
    report = validate_package(pkg)
    assert report.ok


def test_package_without_narrative_key_parses():
    dumped = _valid_pkg().model_dump(mode="json")
    dumped.pop("narrative")
    dumped["schema_version"] = "1.0"
    pkg = ProductionPackage.model_validate(dumped)
    assert pkg.narrative is None
    assert validate_package(pkg).ok


def test_narrative_is_not_gated():
    """The block is display-only: a stale or empty one must never block a run."""
    pkg = _valid_pkg()
    pkg.narrative = Narrative(
        logline="A tree, and then some.",
        scenes=[NarrativeScene(id="scene_01", heading="A tree", narration="It sways.")],
        shots=[NarrativeShot(node_id="ghost_shot", scene_id="scene_99")],
    )
    report = validate_package(pkg)
    assert report.ok
