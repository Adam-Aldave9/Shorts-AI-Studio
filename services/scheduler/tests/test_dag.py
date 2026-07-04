"""DAG predicates over synthetic node statuses (no network).

Covers the readiness / completion / blocked transitions the daemon relies on:
``ready_nodes`` unlocks dependents as deps succeed, ``all_succeeded`` gates the
compositor handoff, and ``is_blocked`` detects a failed node orphaning the rest.
"""

from __future__ import annotations

from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

from scheduler.dag import Dag


def _pkg(statuses: dict[str, NodeStatus]) -> ProductionPackage:
    """A fixed three-node DAG (two roots, one dependent) with the given statuses."""
    return ProductionPackage(
        project_id="p1",
        meta=Meta(
            title="T", premise="P", target_duration_s=6, style="s",
            narration_voice_id="v", budget_usd=100.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, status=statuses["ref_a"]),
            Asset(node_id="narration", type=AssetType.VOICEOVER, status=statuses["narration"]),
            Asset(
                node_id="shot_a",
                type=AssetType.VIDEO,
                depends_on=["ref_a"],
                status=statuses["shot_a"],
            ),
        ],
    )


def test_ready_nodes_are_roots_then_unlock_dependents():
    P, S = NodeStatus.PENDING, NodeStatus.SUCCEEDED

    # All pending: only the dependency-free roots are ready.
    dag = Dag(_pkg({"ref_a": P, "narration": P, "shot_a": P}))
    assert sorted(dag.ready_nodes()) == ["narration", "ref_a"]

    # ref_a succeeded: its dependent unlocks; narration already (would be) running.
    dag = Dag(_pkg({"ref_a": S, "narration": S, "shot_a": P}))
    assert dag.ready_nodes() == ["shot_a"]


def test_dispatched_dependency_does_not_unlock_dependent():
    P, D = NodeStatus.PENDING, NodeStatus.DISPATCHED
    dag = Dag(_pkg({"ref_a": D, "narration": D, "shot_a": P}))
    assert dag.ready_nodes() == []  # shot_a waits until ref_a *succeeds*, not dispatch


def test_all_succeeded_and_is_complete():
    S, P, F = NodeStatus.SUCCEEDED, NodeStatus.PENDING, NodeStatus.FAILED

    done = Dag(_pkg({"ref_a": S, "narration": S, "shot_a": S}))
    assert done.all_succeeded() and done.is_complete()

    partial = Dag(_pkg({"ref_a": S, "narration": P, "shot_a": P}))
    assert not partial.all_succeeded() and not partial.is_complete()

    # A failed node is terminal (is_complete) but not all-succeeded.
    failed = Dag(_pkg({"ref_a": F, "narration": S, "shot_a": F}))
    assert failed.is_complete() and not failed.all_succeeded()


def test_critical_path_default_is_content_floor_weight_overrides():
    # ref_a -> shot_a is a 2-node chain; narration is a lone parallel root.
    pkg = ProductionPackage(
        project_id="p1",
        meta=Meta(
            title="T", premise="P", target_duration_s=6, style="s",
            narration_voice_id="v", budget_usd=100.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE),  # no duration_s -> default 1.0
            Asset(node_id="narration", type=AssetType.VOICEOVER, spec={"duration_s": 5.0}),
            Asset(node_id="shot_a", type=AssetType.VIDEO, depends_on=["ref_a"],
                  spec={"duration_s": 3.0}),
        ],
    )
    dag = Dag(pkg)

    # Default weight = content seconds (1.0 fallback): chain ref_a(1)+shot_a(3)=4
    # loses to the lone narration root (5). This is the pre-existing behavior.
    assert dag.critical_path_estimate() == 5.0

    # A latency-style weight keyed by type (image 8, video 40, voiceover 6):
    # now ref_a(8)+shot_a(40)=48 dominates narration(6) -> a different floor.
    profile = {AssetType.IMAGE: 8.0, AssetType.VIDEO: 40.0, AssetType.VOICEOVER: 6.0}
    assert dag.critical_path_estimate(weight=lambda a: profile[a.type]) == 48.0


def test_is_blocked_only_when_nothing_can_progress():
    P, D, S, F = (
        NodeStatus.PENDING, NodeStatus.DISPATCHED, NodeStatus.SUCCEEDED, NodeStatus.FAILED,
    )

    # Failed root orphans its dependent, nothing else in flight -> blocked.
    assert Dag(_pkg({"ref_a": F, "narration": S, "shot_a": P})).is_blocked()

    # Same orphan but narration still dispatched -> not blocked (work in flight).
    assert not Dag(_pkg({"ref_a": F, "narration": D, "shot_a": P})).is_blocked()

    # Roots still ready to dispatch -> not blocked.
    assert not Dag(_pkg({"ref_a": P, "narration": P, "shot_a": P})).is_blocked()

    # Everything succeeded -> complete, not blocked.
    assert not Dag(_pkg({"ref_a": S, "narration": S, "shot_a": S})).is_blocked()
