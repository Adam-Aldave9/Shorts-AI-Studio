"""Persistence seam for the scheduler (spec §6.7).

Phase 1 used an in-memory dict here. Phase 2 promotes run-state to the shared
``afp-state`` lib (Redis) so the daemon, worker fleet, and compositor share one
view. This module stays as a thin re-export to keep the daemon/API import paths
(`from scheduler.state import ...`) unchanged.
"""

from __future__ import annotations

from state import *  # noqa: F401,F403  (re-export the shared state API)
from state import __all__  # noqa: F401
