"""Deterministic schema / continuity validator (spec §4.1.5).

Code, not an LLM: catches the great majority of what an LLM continuity agent
would, in milliseconds, for free. Run after planning and again server-side on
every checkpoint edit.

Lives in a standalone ``afp-validator`` lib (depends only on ``afp-schema``) so
both the planning tier and the scheduler can run the same gate without dragging
in the LLM stack. ``planning.validator`` re-exports this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema import AssetType, ProductionPackage

__all__ = ["ValidationReport", "validate_package"]

# 1.1 adds the optional, display-only ``narrative`` block; packages written at 1.0 are
# still valid and must keep re-running.
_SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_acyclic(package: ProductionPackage) -> bool:
    ids = {a.node_id for a in package.assets}
    deps = {a.node_id: [d for d in a.depends_on if d in ids] for a in package.assets}
    state: dict[str, int] = {}  # 0=unvisited, 1=on-stack, 2=done

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return False
        if state.get(node) == 2:
            return True
        state[node] = 1
        for d in deps.get(node, []):
            if not visit(d):
                return False
        state[node] = 2
        return True

    return all(visit(n) for n in ids)


def validate_package(package: ProductionPackage, *, tolerance_s: float = 5.0) -> ValidationReport:
    report = ValidationReport()
    ids = {a.node_id for a in package.assets}

    if package.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        report.errors.append(f"unsupported schema_version {package.schema_version!r}")

    # Every dependency edge must resolve.
    for asset in package.assets:
        for dep in asset.depends_on:
            if dep not in ids:
                report.errors.append(f"{asset.node_id} depends on unknown node {dep!r}")

    if not _is_acyclic(package):
        report.errors.append("asset DAG contains a cycle")

    # Every video node needs at least one reference image dependency.
    for asset in package.assets:
        if asset.type is AssetType.VIDEO and not asset.reference_image_ids:
            report.errors.append(f"video node {asset.node_id} has no reference image")

    # Character / location references in the world must be internally consistent.
    valid_refs = {
        rid
        for entity in (*package.world.characters, *package.world.locations)
        for rid in entity.reference_image_ids
    } | {a.node_id for a in package.assets if a.type is AssetType.IMAGE}
    for asset in package.assets:
        for rid in asset.reference_image_ids:
            if rid not in valid_refs:
                report.errors.append(
                    f"{asset.node_id} references unknown image {rid!r}"
                )

    # Shot durations should sum to within tolerance of the target.
    shot_total = sum(
        float(a.spec.get("duration_s", 0))
        for a in package.assets
        if a.type is AssetType.VIDEO
    )
    if shot_total and abs(shot_total - package.meta.target_duration_s) > tolerance_s:
        report.errors.append(
            f"shot durations sum to {shot_total:.1f}s, "
            f"target is {package.meta.target_duration_s:.1f}s"
        )

    # Estimated cost must be under budget.
    est = sum(a.estimated_cost_usd for a in package.assets)
    if est > package.meta.budget_usd:
        report.errors.append(
            f"estimated cost ${est:.2f} exceeds budget ${package.meta.budget_usd:.2f}"
        )

    return report
