"""Distributed rate limiter and cost tracker (spec §6.5).

Per-provider token buckets live in Redis so the entire worker fleet collectively
respects each provider's rate limit. The cost tracker enforces the per-project
budget live: once cumulative cost exceeds ``meta.budget_usd`` new dispatches are
blocked and the project is paused for human review.
"""

from rate_limiter.cost_tracker import BudgetExceeded, CostTracker
from rate_limiter.token_bucket import TokenBucket

__all__ = ["TokenBucket", "CostTracker", "BudgetExceeded"]
