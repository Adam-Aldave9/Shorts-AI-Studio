"""LangGraph wiring for the planning agents (spec §4.2).

    Brief -> Script -> Breakdown -> Prompts -> (validate) -> Package
                        World bible ----^

A real ``StateGraph`` whose nodes are the three agents (each a pure build/parse
pair over a thin, swappable LLM call) plus a terminal assemble+validate step. The
world bible is loaded once and threaded through state; the prompts node injects each
entity's canonical description — the consistency mechanism.

Mock-first, $0 by default: when ``MOCK=true`` or ``ANTHROPIC_API_KEY`` is unset,
``run_planning`` short-circuits to the hand-authored, already-validated
``data/example-packages/rainforest-90s.json`` (30 shots) without importing the LLM stack
at all. That keeps the checkpoint, frontend, and end-to-end demo free and offline —
the same gate that kept Phase 1/2 free — and is a strict upgrade over the old
3-node stub. ``langgraph`` / ``langchain`` are imported lazily so neither the mock
path nor the unit tests need them installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from schema import ProductionPackage, World
from validator import validate_package

from planning.agents import breakdown, prompts, script
from planning.assembly import assemble_package
from planning.world import load_world

log = logging.getLogger("planning")

# services/planning/planning/graph.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MOCK_PACKAGE = _REPO_ROOT / "data" / "example-packages" / "rainforest-90s.json"

_TRUTHY = {"1", "true", "yes", "on"}


def _use_mock() -> bool:
    """Mock when explicitly asked, or whenever there is no key to spend (so a bare
    checkout runs the whole front for $0)."""
    if os.environ.get("MOCK", "").strip().lower() in _TRUTHY:
        return True
    return not os.environ.get("ANTHROPIC_API_KEY")


def _mock_package_path() -> Path:
    return Path(os.environ.get("MOCK_PACKAGE_PATH") or _DEFAULT_MOCK_PACKAGE)


def _load_mock_package(brief: dict) -> ProductionPackage:
    """Return the hand-authored package with a fresh identity so each submit is a
    distinct, separately persisted run."""
    pkg = ProductionPackage.model_validate_json(
        _mock_package_path().read_text(encoding="utf-8")
    )
    pkg.project_id = f"p_{uuid.uuid4().hex[:6]}"
    pkg.created_at = datetime.now(timezone.utc)
    return pkg


class PlanningState(TypedDict, total=False):
    """The state the graph carries from brief to package."""

    brief: dict
    world: World
    screenplay: object
    shot_list: object
    shot_prompts: object
    package: ProductionPackage


def _build_graph():
    """Compile the script -> breakdown -> prompts -> assemble StateGraph.

    ``langgraph`` is imported here, lazily, so importing this module (and the mock
    path) needs no LLM stack.
    """
    from langgraph.graph import END, START, StateGraph

    def script_node(state: PlanningState) -> dict:
        return {"screenplay": script.run(state["brief"], state["world"])}

    def breakdown_node(state: PlanningState) -> dict:
        return {"shot_list": breakdown.run(state["brief"], state["screenplay"], state["world"])}

    def prompts_node(state: PlanningState) -> dict:
        return {"shot_prompts": prompts.run(state["brief"], state["shot_list"], state["world"])}

    def assemble_node(state: PlanningState) -> dict:
        package = assemble_package(
            state["brief"],
            state["world"],
            state["screenplay"],
            state["shot_list"],
            state["shot_prompts"],
        )
        report = validate_package(package)  # terminal gate (spec §4.1.5)
        if not report.ok:
            log.warning("assembled package failed validation: %s", report.errors)
        return {"package": package}

    graph = StateGraph(PlanningState)
    graph.add_node("script", script_node)
    graph.add_node("breakdown", breakdown_node)
    graph.add_node("prompts", prompts_node)
    graph.add_node("assemble", assemble_node)
    graph.add_edge(START, "script")
    graph.add_edge("script", "breakdown")
    graph.add_edge("breakdown", "prompts")
    graph.add_edge("prompts", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def _run_chain_sync(brief: dict) -> ProductionPackage:
    """Run the compiled graph end to end (blocking: real LLM calls)."""
    world = load_world()
    compiled = _build_graph()
    final: PlanningState = compiled.invoke({"brief": brief, "world": world})
    return final["package"]


async def run_planning(brief: dict) -> ProductionPackage:
    """Compile a brief into an (unvalidated-by-caller) production package.

    Mock/no-key -> the hand-authored package. Otherwise run the agent chain on a
    worker thread so the blocking LLM calls don't stall the FastAPI event loop.
    """
    if _use_mock():
        log.info("planning: MOCK fallback -> hand-authored package")
        return _load_mock_package(brief)
    return await asyncio.to_thread(_run_chain_sync, brief)
