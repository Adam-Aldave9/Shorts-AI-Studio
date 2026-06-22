"""In-memory DAG over a production package's assets (spec §6.1).

Finds nodes whose dependencies are all ``succeeded`` (ready to dispatch) and
computes the critical path — the throughput floor no amount of parallelism can
beat (spec §2.3, §12.2).
"""

from __future__ import annotations

from schema import NodeStatus, ProductionPackage


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

    def critical_path_estimate(self) -> float:
        """Longest dependency chain by estimated duration — the theoretical floor.

        Uses ``spec.duration_s`` where present, else a flat per-node estimate.
        """
        memo: dict[str, float] = {}

        def cost(node_id: str) -> float:
            if node_id in memo:
                return memo[node_id]
            asset = self._assets[node_id]
            self_cost = float(asset.spec.get("duration_s", 1.0))
            dep_cost = max(
                (cost(d) for d in asset.depends_on if d in self._assets),
                default=0.0,
            )
            memo[node_id] = self_cost + dep_cost
            return memo[node_id]

        return max((cost(n) for n in self._assets), default=0.0)
