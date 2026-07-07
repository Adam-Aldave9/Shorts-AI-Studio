"""No-network tests for the planning chain (spec §14.4 verification).

Three layers, none of which touch Anthropic or the LLM stack:
  * each agent's pure ``build_prompt`` / ``parse`` against canned responses, and its
    ``run`` with a stand-in ``call``;
  * ``assemble_package`` from canned agent output -> a package that passes
    ``validate_package`` by construction;
  * ``run_planning`` MOCK fallback and the ``/briefs`` persistence hand-off, both
    against the hand-authored package with fakeredis wired into the state layer.
"""

from __future__ import annotations

import asyncio

import pytest
from schema import AssetType, Character, Location, World
from validator import validate_package

import state
from planning import main
from planning.agents import breakdown, prompts, script, world
from planning.assembly import assemble_package
from planning.graph import _load_mock_package, run_planning
from planning.llm import MODEL_WORLD
from planning.models import Screenplay, ShotList, ShotPrompts
from planning.world import load_world

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


# --------------------------------------------------------------------------
# Fixtures: a tiny world + canned agent outputs
# --------------------------------------------------------------------------
def _world() -> World:
    return World(
        characters=[
            Character(id="char_jaguar", name="The Jaguar",
                      canonical_description="A large golden jaguar.",
                      reference_image_ids=["ref_jaguar_01"]),
        ],
        locations=[
            Location(id="loc_river", name="River",
                     canonical_description="A wide brown river.",
                     reference_image_ids=["ref_river_01"]),
            Location(id="loc_canopy", name="Canopy",
                     canonical_description="A misty canopy.",
                     reference_image_ids=["ref_canopy_01"]),
        ],
    )


def _brief() -> dict:
    return {"premise": "A short film about a river", "target_duration_s": 12,
            "style": "flat 2D", "narration_voice_id": "v_test"}


def _screenplay() -> Screenplay:
    return Screenplay(
        title="River",
        logline="A river at dawn.",
        scenes=[
            {"id": "scene_01", "heading": "River dawn", "location": "River",
             "beat": "Mist on the water", "narration": "The river wakes."},
            {"id": "scene_02", "heading": "Canopy", "location": "Canopy",
             "beat": "Birds overhead", "narration": "Above, the canopy stirs."},
        ],
    )


def _shot_list() -> ShotList:
    return ShotList(shots=[
        {"id": "shot_001", "scene_id": "scene_01", "shot_type": "aerial",
         "duration_s": 4, "location_id": "loc_river", "subject_ids": [],
         "action": "Pan over the river"},
        {"id": "shot_002", "scene_id": "scene_01", "shot_type": "wide",
         "duration_s": 4, "location_id": "loc_river", "subject_ids": ["char_jaguar"],
         "action": "Jaguar drinks at the bank"},
        {"id": "shot_003", "scene_id": "scene_02", "shot_type": "wide",
         "duration_s": 4, "location_id": "loc_canopy", "subject_ids": [],
         "action": "Rise into the canopy"},
    ])


def _shot_prompts() -> ShotPrompts:
    return ShotPrompts(prompts=[
        {"shot_id": "shot_001", "prompt": "Aerial pan over a wide brown river.",
         "provider_hint": "fal:pixverse-v6-i2v", "estimated_cost_usd": 0.1},
        {"shot_id": "shot_002", "prompt": "A large golden jaguar drinks at the bank.",
         "provider_hint": "fal:pixverse-v6-i2v", "estimated_cost_usd": 0.1},
        {"shot_id": "shot_003", "prompt": "Camera rises into a misty canopy.",
         "provider_hint": "fal:pixverse-v6-i2v", "estimated_cost_usd": 0.1},
    ])


# --------------------------------------------------------------------------
# World agent: generated per brief (real-path-only; the mock path is unchanged)
# --------------------------------------------------------------------------
def test_world_build_prompt_and_parse():
    msgs = world.build_prompt(_brief())
    assert [role for role, _ in msgs] == ["system", "human"]
    human = msgs[1][1]
    assert "A short film about a river" in human  # premise
    assert "flat 2D" in human  # style

    # parse coerces a dict -> World and drops any reference image ids so assembly
    # mints the canonical ref_{entity.id} nodes.
    parsed = world.parse({
        "characters": [{"id": "char_a", "name": "A",
                        "canonical_description": "desc",
                        "reference_image_ids": ["should_be_dropped"]}],
        "locations": [{"id": "loc_a", "name": "L",
                       "canonical_description": "desc",
                       "reference_image_ids": ["also_dropped"]}],
    })
    assert isinstance(parsed, World)
    assert all(not e.reference_image_ids
               for e in (*parsed.characters, *parsed.locations))


def test_world_run_uses_injected_call_no_network():
    captured = {}

    def fake_call(*, model, messages, schema, **kw):
        captured["model"] = model
        return _world()

    out = world.run(_brief(), call=fake_call)
    assert isinstance(out, World)
    assert captured["model"] == MODEL_WORLD  # per-agent routing


def test_world_run_propagates_error():
    def boom_call(*, model, messages, schema, **kw):
        raise RuntimeError("world-gen failed")

    # A world-gen failure fails the run — no silent rainforest fallback.
    with pytest.raises(RuntimeError, match="world-gen failed"):
        world.run(_brief(), call=boom_call)


def test_generated_world_assembles_and_validates():
    """A generated-world shape (empty reference_image_ids) yields a valid,
    renderable DAG with one image node per entity."""
    generated = World(
        characters=[Character(id="char_keeper", name="The Keeper",
                              canonical_description="A weathered lighthouse keeper.")],
        locations=[
            Location(id="loc_river", name="River",
                     canonical_description="A wide brown river."),
            Location(id="loc_canopy", name="Canopy",
                     canonical_description="A misty canopy."),
        ],
    )
    assert all(not e.reference_image_ids
               for e in (*generated.characters, *generated.locations))

    pkg = assemble_package(_brief(), generated, _screenplay(), _shot_list(), _shot_prompts())
    assert validate_package(pkg).ok
    images = [a for a in pkg.assets if a.type is AssetType.IMAGE]
    assert len(images) == 3  # one ref image per entity (1 char + 2 locations)


# --------------------------------------------------------------------------
# Agents: pure build_prompt / parse + run with an injected call
# --------------------------------------------------------------------------
def test_script_build_prompt_and_parse():
    msgs = script.build_prompt(_brief(), _world())
    assert [role for role, _ in msgs] == ["system", "human"]
    human = msgs[1][1]
    assert "A short film about a river" in human
    assert "char_jaguar" in human and "loc_river" in human

    parsed = script.parse({"title": "T", "logline": "L", "scenes": []})
    assert isinstance(parsed, Screenplay) and parsed.title == "T"


def test_breakdown_build_prompt_sizes_shot_count_from_duration():
    # 12s / 3.5s ~= 3 shots; the world ids must appear so the model can tag them.
    assert breakdown.target_shot_count(_brief()) == 3
    msgs = breakdown.build_prompt(_brief(), _screenplay(), _world())
    human = msgs[1][1]
    assert "about 3 shots" in human
    assert "loc_canopy" in human

    parsed = breakdown.parse({"shots": []})
    assert isinstance(parsed, ShotList)


def test_prompts_build_prompt_injects_canonical_descriptions():
    msgs = prompts.build_prompt(_brief(), _shot_list(), _world())
    human = msgs[1][1]
    # The consistency mechanism: canonical descriptions are handed to the agent.
    assert "A large golden jaguar." in human
    assert "shot_002" in human

    parsed = prompts.parse({"prompts": []})
    assert isinstance(parsed, ShotPrompts)


def test_agent_run_uses_injected_call_no_network():
    captured = {}

    def fake_call(*, model, messages, schema, **kw):
        captured["model"] = model
        return _screenplay()

    out = script.run(_brief(), _world(), call=fake_call)
    assert isinstance(out, Screenplay)
    assert captured["model"] == "claude-opus-4-8"  # per-agent routing


# --------------------------------------------------------------------------
# Assembly: canned agent output -> a validator-passing package
# --------------------------------------------------------------------------
def test_assemble_produces_validatable_package():
    pkg = assemble_package(_brief(), _world(), _screenplay(), _shot_list(), _shot_prompts())
    assert validate_package(pkg).ok

    images = [a for a in pkg.assets if a.type is AssetType.IMAGE]
    videos = [a for a in pkg.assets if a.type is AssetType.VIDEO]
    voiceovers = [a for a in pkg.assets if a.type is AssetType.VOICEOVER]

    # One ref image per world entity (1 char + 2 locations); 3 shots; 1 voiceover.
    assert len(images) == 3
    assert len(videos) == 3
    assert len(voiceovers) == 1

    # Every shot has a reference image and resolvable deps (validator gates).
    ids = {a.node_id for a in pkg.assets}
    for v in videos:
        assert v.reference_image_ids
        assert all(d in ids for d in v.depends_on)

    # shot_002 stays in loc_river after shot_001 -> a continuation edge; shot_003
    # changes location, so no continuation edge.
    shot2 = pkg.asset_by_id("shot_002")
    shot3 = pkg.asset_by_id("shot_003")
    assert "shot_001" in shot2.depends_on
    assert "shot_002" not in shot3.depends_on

    # Durations rescaled to the target; narration concatenated.
    assert sum(a.spec["duration_s"] for a in videos) == pytest.approx(12.0, abs=0.1)
    assert "The river wakes." in pkg.asset_by_id("narration_full").text


def test_assemble_handles_unknown_entity_tags():
    """Even if the breakdown tags a junk location, the video gate still passes."""
    shots = ShotList(shots=[{"id": "shot_001", "scene_id": "scene_01",
                             "shot_type": "wide", "duration_s": 3,
                             "location_id": "loc_nonexistent", "subject_ids": ["ghost"],
                             "action": "something"}])
    pkg = assemble_package(_brief(), _world(), _screenplay(), shots, ShotPrompts(prompts=[]))
    assert validate_package(pkg).ok
    assert pkg.asset_by_id("shot_001").reference_image_ids  # fell back to a real ref


# --------------------------------------------------------------------------
# run_planning MOCK fallback + /briefs persistence
# --------------------------------------------------------------------------
def test_load_mock_package_is_valid_with_fresh_id():
    pkg = _load_mock_package(_brief())
    assert validate_package(pkg).ok
    assert pkg.project_id.startswith("p_")
    assert len([a for a in pkg.assets if a.type is AssetType.VIDEO]) == 30


def test_run_planning_mock_returns_validatable_package(monkeypatch):
    monkeypatch.setenv("MOCK", "true")
    pkg = asyncio.run(run_planning(_brief()))
    assert validate_package(pkg).ok


def test_create_brief_persists_and_returns_project_id(monkeypatch):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    monkeypatch.setenv("MOCK", "true")

    async def scenario():
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        try:
            accepted = await main.create_brief(main.Brief(**_brief()), user_id="user_a")
            assert accepted.project_id.startswith("p_")
            # The scheduler's store sees the package immediately, unapproved, and
            # stamped with the authenticated caller as owner.
            stored = await state.get_package(accepted.project_id)
            assert stored is not None
            assert await state.get_project_owner(accepted.project_id) == "user_a"
            approved = [p.project_id async for p in state.iter_approved_packages()]
            assert approved == []
        finally:
            state.use_client(None)

    asyncio.run(scenario())


def test_world_loads_from_disk():
    world = load_world()
    ids = {c.id for c in world.characters} | {l.id for l in world.locations}
    assert "char_jaguar" in ids and "loc_river" in ids
