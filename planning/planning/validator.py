"""Deterministic schema / continuity validator (spec §4.1.5).

The implementation now lives in the standalone ``afp-validator`` lib so the
scheduler can run the same gate without the LLM stack. This module stays as a
thin re-export to keep planning's import path (``from planning.validator import
...``) unchanged — exactly like ``scheduler.state`` re-exports ``state``.
"""

from __future__ import annotations

from validator import *  # noqa: F401,F403  (re-export the shared validator API)
from validator import __all__  # noqa: F401
