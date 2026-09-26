"""Story extraction from packages, draft validation, and the story view endpoint."""

from __future__ import annotations

import asyncio

import pytest
from schema import Asset, AssetType, Lineage, Meta, NarrativeShot, ProductionPackage, World

import state
from planning import main
from planning.graph import _load_mock_package
from planning.models import Shot
from planning.story import (
    narration_diverged,
    next_scene_id,
    story_from_package,
    story_hash,
    unique_entity_id,
    validate_story,
)

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _fixture() -> ProductionPackage:
    return _load_mock_package({})


def test_fixture_story_has_every_stage():
    story = story_from_package(_fixture())
    assert len(story.script.scenes) == 9
    assert len(story.shots) == 30
    assert len(story.world.characters) == 4
    assert len(story.world.locations) == 6
    assert validate_story(story) == []
    assert story.brief.target_duration_s == 90
    assert story.script.title == "The Amazon Rainforest"
    assert [s.id for s in story.shots][:3] == ["shot_001", "shot_002", "shot_003"]


def test_tags_are_inferred_by_entity_kind():
    shots = {s.id: s for s in story_from_package(_fixture()).shots}
    # A character ref listed first doesn't become the location.
    assert shots["shot_005"].location_id == "loc_canopy"
    assert shots["shot_005"].subject_ids == ["char_naturalist"]
    # No location ref: matched by the scene's location name.
    assert shots["shot_017"].location_id == "loc_understory"
    assert shots["shot_017"].subject_ids == ["char_jaguar"]
    # Two location refs: the first wins.
    assert shots["shot_026"].location_id == "loc_river"


def test_voice_comes_from_the_node_spec():
    pkg = _fixture()
    next(a for a in pkg.assets if a.type is AssetType.VOICEOVER).spec["voice_id"] = "v_patched"
    assert story_from_package(pkg).brief.narration_voice_id == "v_patched"
    next(a for a in pkg.assets if a.type is AssetType.VOICEOVER).spec.pop("voice_id")
    assert story_from_package(pkg).brief.narration_voice_id == pkg.meta.narration_voice_id


def test_schema_1_2_uses_the_stored_tags():
    pkg = _fixture()
    pkg.lineage = Lineage(film_id=pkg.project_id)
    ns = next(s for s in pkg.narrative.shots if s.node_id == "shot_005")
    ns.location_id = "loc_emergent"
    ns.subject_ids = ["char_macaw"]
    shot = next(s for s in story_from_package(pkg).shots if s.id == "shot_005")
    assert (shot.location_id, shot.subject_ids) == ("loc_emergent", ["char_macaw"])


def test_schema_1_0_package_gets_one_synthetic_scene():
    pkg = _fixture()
    pkg.narrative = None
    pkg.schema_version = "1.0"
    story = story_from_package(pkg)
    assert len(story.script.scenes) == 1
    scene = story.script.scenes[0]
    assert scene.id == "scene_01"
    assert scene.heading == pkg.meta.title
    assert scene.beat == pkg.meta.premise
    assert scene.narration == pkg.asset_by_id("narration_full").text
    assert {s.scene_id for s in story.shots} == {"scene_01"}
    assert all(s.action == "" and s.shot_type == "wide" for s in story.shots)
    assert validate_story(story) == []


def test_shots_follow_timeline_order():
    pkg = _fixture()
    first, second = pkg.timeline[0], pkg.timeline[1]
    first.in_s, second.in_s = second.in_s, first.in_s
    ids = [s.id for s in story_from_package(pkg).shots]
    assert ids[:2] == [second.node_id, first.node_id]


def test_narration_divergence():
    pkg = _fixture()
    story = story_from_package(pkg)
    assert not narration_diverged(pkg, story)
    pkg.asset_by_id("narration_full").text += " Edited at the checkpoint."
    assert narration_diverged(pkg, story)


def test_story_hash_is_stable_and_content_sensitive():
    a = story_from_package(_fixture())
    b = story_from_package(_fixture())
    assert story_hash(a) == story_hash(b)
    assert len(story_hash(a)) == 16
    b.script.scenes[0].beat += "!"
    assert story_hash(a) != story_hash(b)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda s: setattr(s.brief, "premise", " "), "premise"),
        (lambda s: setattr(s.brief, "premise", "x" * 501), "premise"),
        (lambda s: setattr(s.brief, "target_duration_s", 5), "length"),
        (lambda s: setattr(s.brief, "target_duration_s", 301), "length"),
        (lambda s: setattr(s.world.characters[1], "id", s.world.characters[0].id), "Duplicate world id"),
        (lambda s: setattr(s.world.characters[0], "id", "jaguar"), "must start with 'char_'"),
        (lambda s: setattr(s.world.locations[0], "id", "canopy"), "must start with 'loc_'"),
        (lambda s: setattr(s.world.characters[0], "name", ""), "needs a name"),
        (lambda s: setattr(s.world.locations[0], "canonical_description", ""), "needs a description"),
        (lambda s: setattr(s, "world", World(characters=s.world.characters)), "at least one location"),
        (lambda s: setattr(s.script.scenes[1], "id", s.script.scenes[0].id), "Duplicate scene id"),
        (lambda s: setattr(s.script, "scenes", []), "at least one scene"),
        (lambda s: setattr(s.script.scenes[0], "heading", " "), "needs a heading"),
        (lambda s: setattr(s.shots[1], "id", s.shots[0].id), "Duplicate shot id"),
        (lambda s: setattr(s.shots[0], "scene_id", "scene_99"), "unknown scene"),
        (lambda s: setattr(s.shots[0], "location_id", "loc_mars"), "unknown location"),
        (lambda s: setattr(s.shots[0], "subject_ids", ["char_ghost"]), "unknown character"),
        (lambda s: setattr(s.shots[0], "duration_s", 0.2), "must last"),
        (lambda s: setattr(s.shots[0], "duration_s", 16), "must last"),
    ],
)
def test_validate_story_rules(mutate, fragment):
    story = story_from_package(_fixture())
    mutate(story)
    errors = validate_story(story)
    assert any(fragment.lower() in e.lower() for e in errors), errors


def test_a_scene_without_shots_is_valid():
    story = story_from_package(_fixture())
    story.shots = [s for s in story.shots if s.scene_id != "scene_03"]
    assert validate_story(story) == []


def test_id_helpers():
    assert next_scene_id(["scene_01", "scene_09", "other"]) == "scene_10"
    assert next_scene_id([]) == "scene_01"
    assert unique_entity_id("The Otter", "char_", []) == "char_the_otter"
    assert unique_entity_id("Otter", "char_", ["char_otter", "char_otter_2"]) == "char_otter_3"


def _mini_pkg() -> ProductionPackage:
    pkg = ProductionPackage(
        project_id="p_mini",
        meta=Meta(title="T", premise="P", target_duration_s=3, style="s",
                  narration_voice_id="v", budget_usd=15),
        world=World.model_validate({
            "characters": [],
            "locations": [{"id": "loc_a", "name": "A", "canonical_description": "d"}],
        }),
        assets=[
            Asset(node_id="ref_loc_a", type=AssetType.IMAGE, prompt="p"),
            Asset(node_id="shot_001", type=AssetType.VIDEO, reference_image_ids=["ref_loc_a"],
                  prompt="the prompt", spec={"duration_s": 3}),
            Asset(node_id="narration_full", type=AssetType.VOICEOVER, text="Hi."),
        ],
    )
    return pkg


def test_get_story_endpoint_reports_mode_and_context():
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")

    async def scenario():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            pkg = _mini_pkg()
            await state.save_package(pkg, owner_id="u")
            view = await main.get_story("p_mini")
            assert view.mode == "in_place"
            assert (view.film_id, view.version) == ("p_mini", 1)
            assert view.prompts == {"shot_001": "the prompt"}
            assert view.spoken_narration == "Hi."
            assert view.base_hash == story_hash(view.story)
            assert isinstance(view.story.shots[0], Shot)

            await state.approve_package("p_mini")
            await state.set_node_status("p_mini", "shot_001", "succeeded", asset_url="s3://x")
            again = await main.get_story("p_mini")
            assert again.mode == "new_version"
            assert again.base_hash == view.base_hash

            with pytest.raises(main.HTTPException) as exc:
                await main.get_story("p_missing")
            assert exc.value.status_code == 404
        finally:
            state.use_client(None)

    asyncio.run(scenario())


def test_narrative_shot_defaults_parse():
    assert NarrativeShot(node_id="a", scene_id="b").subject_ids == []
