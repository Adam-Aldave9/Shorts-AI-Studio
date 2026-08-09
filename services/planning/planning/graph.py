"""LangGraph wiring for the planning agents (spec §4.2).

    Brief -> World -> Script -> Breakdown -> Prompts -> (validate) -> Package

A real ``StateGraph`` whose nodes are the four agents (each a pure build/parse
pair over a thin, swappable LLM call) plus a terminal assemble+validate step. The
world agent invents a bespoke cast + set from the brief as the first step, and it
is threaded through the rest of state; the prompts node injects each entity's
canonical description — the consistency mechanism.

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
from typing import Callable, TypedDict

from schema import ProductionPackage, World
from state import PLAN_STAGES
from validator import validate_package

from planning.agents import breakdown, prompts, script, world
from planning.assembly import assemble_package

log = logging.getLogger("planning")

# The chain's nodes in execution order — the last is the terminal assemble+validate
# step. The async runner and the frontend use this to render "stage 3 of 5" progress
# as ``on_stage`` fires per node. Keep in sync with the edges in ``_build_graph``.
STAGE_SEQUENCE = list(PLAN_STAGES)

# Seconds the mock simulation dwells on each stage. The mock path skips the chain
# entirely, so without this the progress UI flashes straight to done and is neither
# demoable nor testable in the primary dev loop. ``0`` restores the instant behavior.
_DEFAULT_MOCK_PLAN_DELAY_S = 1.5

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


OnDetail = Callable[[str, dict], None]


def _video_shot_count(package: ProductionPackage) -> int:
    return sum(1 for asset in package.assets if asset.type.value == "video")


def _assemble_detail(package: ProductionPackage) -> dict:
    return {
        "nodes": len(package.assets),
        "shots": _video_shot_count(package),
        "cost_estimate_usd": round(sum(a.estimated_cost_usd for a in package.assets), 2),
    }


def _build_graph(on_detail: OnDetail | None = None):
    """Compile the script -> breakdown -> prompts -> assemble StateGraph.

    ``langgraph`` is imported here, lazily, so importing this module (and the mock
    path) needs no LLM stack.

    Each node reports what it produced through ``on_detail`` as soon as it knows —
    before ``on_stage`` fires for that node — so a finished stage row on the Planning
    screen can show its output rather than just a check mark.
    """
    from langgraph.graph import END, START, StateGraph

    def detail(stage: str, payload: dict) -> None:
        if on_detail is not None:
            on_detail(stage, payload)

    def world_node(state: PlanningState) -> dict:
        built = world.run(state["brief"])
        detail(
            "world",
            {
                "characters": [c.name for c in built.characters],
                "locations": [l.name for l in built.locations],
            },
        )
        return {"world": built}

    def script_node(state: PlanningState) -> dict:
        screenplay = script.run(state["brief"], state["world"])
        detail(
            "script",
            {
                "title": screenplay.title,
                "logline": screenplay.logline,
                "scenes": len(screenplay.scenes),
            },
        )
        return {"screenplay": screenplay}

    def breakdown_node(state: PlanningState) -> dict:
        shot_list = breakdown.run(state["brief"], state["screenplay"], state["world"])
        detail("breakdown", {"shots": len(shot_list.shots)})
        return {"shot_list": shot_list}

    def prompts_node(state: PlanningState) -> dict:
        shot_prompts = prompts.run(
            state["brief"],
            state["shot_list"],
            state["world"],
            on_progress=lambda done, total: detail("prompts", {"done": done, "total": total}),
        )
        return {"shot_prompts": shot_prompts}

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
        detail("assemble", _assemble_detail(package))
        return {"package": package}

    graph = StateGraph(PlanningState)
    graph.add_node("world", world_node)
    graph.add_node("script", script_node)
    graph.add_node("breakdown", breakdown_node)
    graph.add_node("prompts", prompts_node)
    graph.add_node("assemble", assemble_node)
    graph.add_edge(START, "world")
    graph.add_edge("world", "script")
    graph.add_edge("script", "breakdown")
    graph.add_edge("breakdown", "prompts")
    graph.add_edge("prompts", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def _run_chain_sync(
    brief: dict,
    on_stage: Callable[[str], None] | None = None,
    on_detail: OnDetail | None = None,
) -> ProductionPackage:
    """Run the compiled graph end to end (blocking: real LLM calls).

    The world node fills ``state["world"]`` from the brief, so the initial state is
    just the brief — no preloaded world.

    ``stream(stream_mode="updates")`` yields ``{node_name: node_output}`` after each
    node completes; we fire ``on_stage(node_name)`` per step (so the caller can report
    per-stage progress) and accumulate the final ``package`` from the assemble step's
    update."""
    compiled = _build_graph(on_detail)
    package: ProductionPackage | None = None
    for step in compiled.stream({"brief": brief}, stream_mode="updates"):
        for node_name, output in step.items():
            if on_stage is not None:
                on_stage(node_name)
            if output and "package" in output:
                package = output["package"]
    if package is None:  # the assemble node always emits a package; guard for safety
        raise RuntimeError("planning chain produced no package")
    return package


def _mock_delay_s() -> float:
    raw = os.environ.get("MOCK_PLAN_DELAY_S")
    if raw is None or not raw.strip():
        return _DEFAULT_MOCK_PLAN_DELAY_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_MOCK_PLAN_DELAY_S


# How many times the mock prompts stage ticks its sub-progress across its dwell.
_MOCK_PROMPT_TICKS = 5


async def _run_mock(
    brief: dict, on_stage: Callable[[str], None] | None, on_detail: OnDetail | None
) -> ProductionPackage:
    """Walk the stage sequence at ``MOCK_PLAN_DELAY_S`` per stage, reporting detail read
    off the hand-authored package so the numbers on screen are real ones.

    ``on_stage(node)`` means *that node finished* (the caller maps it to its successor),
    so each stage sleeps first and fires afterwards."""
    package = _load_mock_package(brief)
    delay = _mock_delay_s()
    shots = _video_shot_count(package)
    details = {
        "world": {
            "characters": [c.name for c in package.world.characters],
            "locations": [l.name for l in package.world.locations],
        },
        "script": {"title": package.meta.title, "logline": package.meta.premise},
        "breakdown": {"shots": shots},
        "assemble": _assemble_detail(package),
    }

    for stage in STAGE_SEQUENCE:
        if stage == "prompts":
            for tick in range(1, _MOCK_PROMPT_TICKS + 1):
                if delay:
                    await asyncio.sleep(delay / _MOCK_PROMPT_TICKS)
                if on_detail is not None:
                    done = round(shots * tick / _MOCK_PROMPT_TICKS)
                    on_detail("prompts", {"done": done, "total": shots})
        else:
            if delay:
                await asyncio.sleep(delay)
            if on_detail is not None:
                on_detail(stage, details[stage])
        if on_stage is not None:
            on_stage(stage)
    return package


async def run_planning(
    brief: dict,
    on_stage: Callable[[str], None] | None = None,
    on_detail: OnDetail | None = None,
) -> ProductionPackage:
    """Compile a brief into an (unvalidated-by-caller) production package.

    Mock/no-key -> the hand-authored package, walked stage by stage so the Planning
    screen is demoable and testable for $0. Otherwise run the agent chain on a worker
    thread so the blocking LLM calls don't stall the FastAPI event loop; the callbacks
    are invoked from that thread as each node completes.
    """
    if _use_mock():
        log.info("planning: MOCK fallback -> hand-authored package")
        return await _run_mock(brief, on_stage, on_detail)
    return await asyncio.to_thread(_run_chain_sync, brief, on_stage, on_detail)
