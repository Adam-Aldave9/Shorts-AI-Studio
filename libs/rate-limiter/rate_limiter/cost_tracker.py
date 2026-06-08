"""Per-project live cost tracking and budget enforcement (spec §6.5).

Cumulative spend is held in Redis for fast reads during a run; actuals are also
recorded back to Postgres per node by the worker for post-run analysis.
"""

from __future__ import annotations

import redis.asyncio as redis


class BudgetExceeded(Exception):
    def __init__(self, project_id: str, spent: float, budget: float) -> None:
        super().__init__(
            f"project {project_id} budget exceeded: ${spent:.2f} > ${budget:.2f}"
        )
        self.project_id = project_id
        self.spent = spent
        self.budget = budget


class CostTracker:
    def __init__(self, client: redis.Redis, project_id: str, budget_usd: float) -> None:
        self._client = client
        self._key = f"cost:{project_id}"
        self._project_id = project_id
        self._budget = budget_usd

    async def spent(self) -> float:
        raw = await self._client.get(self._key)
        return float(raw) if raw else 0.0

    async def reserve(self, estimated_usd: float) -> None:
        """Check the budget *before* dispatching. Raises if it would be blown."""
        projected = await self.spent() + estimated_usd
        if projected > self._budget:
            raise BudgetExceeded(self._project_id, projected, self._budget)

    async def record(self, actual_usd: float) -> float:
        """Record realized spend after a node succeeds; returns new cumulative."""
        return float(await self._client.incrbyfloat(self._key, actual_usd))
