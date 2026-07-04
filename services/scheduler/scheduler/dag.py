"""In-memory DAG over a production package's assets (spec §6.1).

Finds nodes whose dependencies are all ``succeeded`` (ready to dispatch) and
computes the critical path — the longest dependency chain, the throughput floor
no amount of parallelism can beat (spec §2.3, §12.2). One parameterized
implementation yields two floors: a *content* floor (spec durations, the
default) and a *render-time* floor (latency-weighted; Graph B).
"""

from __future__ import annotations

from collections.abc import Callable

from schema import Asset, NodeStatus, ProductionPackage


class Dag:
    def __init__(self, package: ProductionPackage) -> None:
        self.package = package
        self._assets = {a.node_id: a for a in package.assets}

    def ready_nodes(self) -> list[str]:
        """Pending nodes whose every dependency has succeeded."""
        ready = []
        for node_id, asset in self._assets.items():
            if asset.status is not NodeStatus.PENDING:
                continue
            if all(
                self._assets[d].status is NodeStatus.SUCCEEDED
                for d in asset.depends_on
                if d in self._assets
            ):
                ready.append(node_id)
        return ready

    def is_complete(self) -> bool:
        terminal = {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.DEAD_LETTERED}
        return all(a.status in terminal for a in self._assets.values())

    def all_succeeded(self) -> bool:
        """Every node succeeded — the only state from which the compositor may run."""
        return all(a.status is NodeStatus.SUCCEEDED for a in self._assets.values())

    def is_blocked(self) -> bool:
        """The run can make no further progress yet isn't done: nothing is ready,
        nothing is in flight, and not everything succeeded — so a ``failed`` or
        ``dead-lettered`` node has orphaned its dependents (spec §10.2). The user
        must edit + re-run the failed nodes to recover.
        """
        if self.all_succeeded():
            return False
        if self.ready_nodes():
            return False
        return not any(
            a.status is NodeStatus.DISPATCHED for a in self._assets.values()
        )

    def critical_path_estimate(
        self, weight: Callable[[Asset], float] | None = None
    ) -> float:
        """Longest dependency chain by per-node ``weight`` — a critical-path floor.

        With the default ``weight`` (each node's ``spec.duration_s``, i.e. *content*
        seconds, flat ``1.0`` where absent) this is the **content** critical path:
        the mode-independent floor the SSE stream / frontend report. Pass a *latency*
        weight (per-node execution time — in mock mode the provider latency from
        ``adapters.mock._PROFILES``) to get the **render-time floor** (Graph B, spec
        §12.2): the wall-clock no amount of parallelism can beat. One algorithm, two
        floors — so the scheduler, the harness, and the notebook never drift.
        """
        if weight is None:
            def weight(asset: Asset) -> float:
                return float(asset.spec.get("duration_s", 1.0))

        memo: dict[str, float] = {}

        def cost(node_id: str) -> float:
            if node_id in memo:
                return memo[node_id]
            asset = self._assets[node_id]
            dep_cost = max(
                (cost(d) for d in asset.depends_on if d in self._assets),
                default=0.0,
            )
            memo[node_id] = weight(asset) + dep_cost
            return memo[node_id]

        return max((cost(n) for n in self._assets), default=0.0)
