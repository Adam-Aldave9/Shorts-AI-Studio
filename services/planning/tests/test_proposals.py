"""AI rewrite proposals: the new agent modes' prompts and routing, the deterministic merge
rules, the MOCK stand-ins, and the endpoint's error mapping."""

from __future__ import annotations

import asyncio

import pytest
from schema import Character, World

import state
from planning import main, proposals
from planning.agents import breakdown, script, world
from planning.graph import _load_mock_package
from planning.llm import MODEL_BREAKDOWN, MODEL_SCRIPT, MODEL_WORLD
from planning.models import (
    Scene,
    Screenplay,
    ScreenplayRevision,
    Shot,
    ShotList,
    WorldRevision,
)
from planning.proposals import ProposalRequest, merge_script, merge_world, propose
from planning.story import story_from_package

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None

PARENT = _load_mock_package({})


def _story():
    return story_from_package(PARENT)


# --------------------------------------------------------------------------
# Prompt builders + routing
# --------------------------------------------------------------------------
def test_world_revise_prompt_carries_notes_targets_content_and_used_locations():
    story = _story()
    system, human = (m[1] for m in world.build_revise_prompt(
        story.brief.model_dump(), story.world, "make the jaguar black", ["char_jaguar"],
        ["loc_river", "loc_canopy"]))
    assert "loc_river, loc_canopy" in system
    assert "make the jaguar black" in human
    assert "Rewrite only these entities: char_jaguar" in human
    assert story.world.characters[1].canonical_description in human


def test_script_revise_prompt_carries_notes_targets_and_scenes():
    story = _story()
    _, human = (m[1] for m in script.build_revise_prompt(
        story.brief.model_dump(), story.world, story.script, "brighter ending", ["scene_09"]))
    assert "brighter ending" in human
    assert "Rewrite only these scenes: scene_09" in human
    assert "[scene_03]" in human and story.script.scenes[2].narration in human
    assert "loc_river" in human


def test_scene_breakdown_prompt_lists_targets_and_context():
    story = _story()
    _, human = (m[1] for m in breakdown.build_scene_prompt(
        story.brief.model_dump(), story.script, story.world, {"scene_03": 4}))
    wanted, context = human.split("Whole screenplay")
    assert "[scene_03]" in wanted and "about 4 shots" in wanted
    assert "[scene_01]" not in wanted
    assert "  [scene_01] " in context
    assert "loc_canopy" in human


def _router(seen: dict):
    def call(*, model, messages, schema, **kw):
        seen["model"], seen["schema"] = model, schema
        if schema is WorldRevision:
            return WorldRevision(world=_story().world, notes="n")
        if schema is ScreenplayRevision:
            return ScreenplayRevision(screenplay=_story().script, notes="n")
        return ShotList(shots=[])
    return call


def test_revise_modes_route_to_their_model_and_schema():
    story = _story()
    brief = story.brief.model_dump()
    seen: dict = {}
    world.revise(brief, story.world, "", [], [], call=_router(seen))
    assert (seen["model"], seen["schema"]) == (MODEL_WORLD, WorldRevision)
    script.revise(brief, story.world, story.script, "", [], call=_router(seen))
    assert (seen["model"], seen["schema"]) == (MODEL_SCRIPT, ScreenplayRevision)
    breakdown.run_scenes(brief, story.script, story.world, {"scene_01": 2}, call=_router(seen))
    assert (seen["model"], seen["schema"]) == (MODEL_BREAKDOWN, ShotList)


# --------------------------------------------------------------------------
# Merge rules
# --------------------------------------------------------------------------
def test_targeted_world_touches_only_targets_and_keeps_ref_ids():
    story = _story()
    proposed = World(characters=[
        Character(id="char_jaguar", name="Onca", canonical_description="A black jaguar."),
        Character(id="char_macaw", name="Ignored", canonical_description="Ignored."),
    ])
    merged, note = merge_world(story, proposed, ["char_jaguar"])
    jaguar = next(c for c in merged.world.characters if c.id == "char_jaguar")
    macaw = next(c for c in merged.world.characters if c.id == "char_macaw")
    assert (jaguar.name, jaguar.canonical_description) == ("Onca", "A black jaguar.")
    assert jaguar.reference_image_ids == ["ref_jaguar_01"]
    assert macaw.name == "The Scarlet Macaw"
    assert note == ""


def test_whole_world_restores_used_locations_and_strips_removed_characters():
    story = _story()
    kept_loc = story.world.locations[0].model_copy(update={"reference_image_ids": []})
    proposed = World(
        characters=[Character(id="char_jaguar", name="J", canonical_description="d"),
                    Character(id="otter", name="Giant Otter", canonical_description="An otter.")],
        locations=[kept_loc],
    )
    merged, note = merge_world(story, proposed, [])
    ids = [c.id for c in merged.world.characters]
    assert ids == ["char_jaguar", "char_giant_otter"]
    assert merged.world.characters[0].reference_image_ids == ["ref_jaguar_01"]
    assert merged.world.characters[1].reference_image_ids == []
    assert merged.world.locations[0].reference_image_ids == ["ref_canopy_01"]
    used = {s.location_id for s in story.shots}
    assert used <= {l.id for l in merged.world.locations}
    assert "which shots still use" in note
    assert all(set(s.subject_ids) <= {"char_jaguar", "char_giant_otter"} for s in merged.shots)


def test_whole_script_normalizes_ids_and_drops_orphan_shots():
    story = _story()
    first = story.script.scenes[0]
    proposed = Screenplay(title="New", logline="L", scenes=[
        first,
        Scene(id="scene_01", heading="Dup", location="Amazon River", beat="b", narration="n"),
        Scene(id="intro", heading="Fresh", location="Amazon River", beat="b", narration="n"),
    ])
    merged = merge_script(story, proposed, [])
    assert [s.id for s in merged.script.scenes] == ["scene_01", "scene_10", "scene_11"]
    assert {s.scene_id for s in merged.shots} == {"scene_01"}
    assert merged.script.title == "New"


def test_targeted_script_replaces_only_targets():
    story = _story()
    proposed = Screenplay(title="x", logline="y", scenes=[
        Scene(id="scene_02", heading="H", location="Amazon River", beat="B", narration="N"),
        Scene(id="scene_03", heading="no", location="no", beat="no", narration="no"),
    ])
    merged = merge_script(story, proposed, ["scene_02"])
    assert merged.script.scenes[1].heading == "H"
    assert merged.script.scenes[2] == story.script.scenes[2]
    assert merged.script.title == story.script.title


def test_shots_proposal_sanitizes_and_falls_back(monkeypatch):
    story = _story()

    def fake_run_scenes(brief, screenplay, world_, targets, **kw):
        assert targets == {"scene_03": 5, "scene_04": 3}
        return ShotList(shots=[
            Shot(id="s", scene_id="scene_03", shot_type="wide", duration_s=4,
                 location_id="loc_nowhere", subject_ids=["char_ghost", "char_jaguar"], action="a"),
        ])

    monkeypatch.setattr(proposals.breakdown, "run_scenes", fake_run_scenes)
    request = ProposalRequest(stage="shots", story=story, targets=["scene_03", "scene_04"])
    out = propose(story, request, mock=False)
    assert out.changed == ["scene_03", "scene_04"]
    s3 = [s for s in out.story.shots if s.scene_id == "scene_03"]
    s4 = [s for s in out.story.shots if s.scene_id == "scene_04"]
    assert [s.id for s in s3] == ["rp_scene_03_1"]
    assert s3[0].location_id == "loc_river" and s3[0].subject_ids == ["char_jaguar"]
    assert len(s4) == 1 and s4[0].action == story.script.scenes[3].beat
    assert len(out.story.shots) == 30 - 5 - 3 + 2


def test_shots_proposal_needs_targets():
    with pytest.raises(proposals.ProposalError):
        propose(_story(), ProposalRequest(stage="shots", story=_story()), mock=True)


# --------------------------------------------------------------------------
# MOCK stand-ins
# --------------------------------------------------------------------------
def test_mock_proposals_are_deterministic():
    story = _story()
    world_req = ProposalRequest(stage="world", story=story, targets=["char_jaguar"], notes="darker")
    a, b = propose(story, world_req, mock=True), propose(story, world_req, mock=True)
    assert a == b
    assert a.changed == ["char_jaguar"]
    assert a.notes == proposals.MOCK_NOTE
    jaguar = next(c for c in a.story.world.characters if c.id == "char_jaguar")
    assert jaguar.canonical_description.endswith(" [mock rewrite: darker]")

    script_out = propose(story, ProposalRequest(stage="script", story=story), mock=True)
    assert len(script_out.changed) == 9
    assert script_out.story.script.scenes[0].beat.endswith("(mock rewrite: no notes)")

    shots_out = propose(story, ProposalRequest(stage="shots", story=story, targets=["scene_01"]), mock=True)
    s1 = [s for s in shots_out.story.shots if s.scene_id == "scene_01"]
    assert [s.shot_type for s in s1] == ["wide", "medium"]
    assert s1[0].action.endswith("(shot 1 of 2)")
    assert all(s.location_id == "loc_canopy" and s.subject_ids == [] for s in s1)


# --------------------------------------------------------------------------
# Endpoint error mapping
# --------------------------------------------------------------------------
def _with_package(scenario):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def wrapper():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            pkg = PARENT.model_copy(deep=True)
            await state.save_package(pkg, owner_id="u")
            await scenario(pkg.project_id)
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


def test_llm_failure_is_502_and_missing_targets_422(monkeypatch):
    monkeypatch.delenv("MOCK", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    def boom(*a, **kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(proposals.world_agent, "revise", boom)

    async def scenario(pid):
        with pytest.raises(main.HTTPException) as exc:
            await main.propose_story(pid, ProposalRequest(stage="world", story=_story()))
        assert exc.value.status_code == 502
        with pytest.raises(main.HTTPException) as exc:
            await main.propose_story(pid, ProposalRequest(stage="shots", story=_story()))
        assert exc.value.status_code == 422

    _with_package(scenario)


def test_mock_endpoint_proposes_without_an_llm(monkeypatch):
    monkeypatch.setenv("MOCK", "true")

    async def scenario(pid):
        out = await main.propose_story(pid, ProposalRequest(stage="script", story=_story(),
                                                            targets=["scene_02"], notes="n"))
        assert out.changed == ["scene_02"]

    _with_package(scenario)
