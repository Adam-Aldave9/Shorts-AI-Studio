"""Shared run-state for the AI Film Pipeline (spec §6.7).

A thin async Redis layer that the scheduler daemon, worker fleet, and compositor
all read/write so a run has one coherent view. Mirrors ``libs/storage``: the
implementation lives in :mod:`state.store`; this package re-exports its API.
"""

from state.store import (
    PHASE_BLOCKED,
    PHASE_COMPLETE,
    PHASE_COMPOSITING,
    PHASE_EXECUTING,
    PHASE_PAUSED,
    approve_package,
    get_cost,
    get_dep_provider_urls,
    get_final_url,
    get_node,
    get_package,
    get_project_phase,
    increment_attempts,
    iter_approved_packages,
    save_package,
    set_final_url,
    set_node_status,
    set_project_phase,
    use_client,
)

__all__ = [
    "PHASE_EXECUTING",
    "PHASE_COMPOSITING",
    "PHASE_COMPLETE",
    "PHASE_BLOCKED",
    "PHASE_PAUSED",
    "use_client",
    "save_package",
    "get_package",
    "approve_package",
    "iter_approved_packages",
    "set_node_status",
    "get_node",
    "increment_attempts",
    "get_dep_provider_urls",
    "get_project_phase",
    "set_project_phase",
    "set_final_url",
    "get_final_url",
    "get_cost",
]
