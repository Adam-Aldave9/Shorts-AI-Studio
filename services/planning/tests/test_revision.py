"""Pure revision logic: change detection, carry-over (I1, I4), shot targets, change lines and
the preview's predictions. No LLM, no Redis."""

from __future__ import annotations

import pytest
from schema import AssetType, Character, NodeStatus, ProductionPackage, fingerprints
from validator import validate_package

from planning.graph import _load_mock_package
from planning.models import Scene, Shot, ShotList, Story
from planning.revision import (
    build_revision,
    mock_prompt,
    mock_replan,
    plan_revision,
    preview,
    sanitize_replanned,
    shot_targets,
    skipped_stages,
    splice_shots,
)
from planning.story import story_from_package

PARENT = _load_mock_package({})


def _parent() -> ProductionPackage:
    return PARENT.model_copy(deep=True)


def _story(pkg: ProductionPackage | None = None) -> Story:
    return story_from_package(pkg or PARENT)


def _revise(parent: ProductionPackage, story: Story, keep: list[str] | None = None) -> ProductionPackage:
    """The job's work on the mock path, synchronously."""
    parent_story = story_from_package(parent)
    plan = plan_revision(parent, parent_story, story, keep or [])
    replanned = {}
    if plan.stale_scenes:
        raw = mock_replan(story, plan.shot_targets, parent_story)
        replanned = sanitize_replanned(raw, story, plan.shot_targets, parent_story)
    shots = splice_shots(story, replanned)
    fresh = {
        s.id: mock_prompt(s, story) for s in shots if plan.shot_status.get(s.id, "new") != "kept"
    }
    return build_revision(parent, story, plan, shots, fresh)


def _changed_prints(parent: ProductionPackage, child: ProductionPackage) -> set[str]:
    before, after = fingerprints(parent), fingerprints(child)
    unchanged = set(before.values()) & set(after.values())
    return {nid for nid, fp in after.items() if fp not in unchanged}


def _shots(story: Story, scene_id: str) -> list[Shot]:
    return [s for s in story.shots if s.scene_id == scene_id]


# --------------------------------------------------------------------------
# I1: a no-op revision reuses everything
# --------------------------------------------------------------------------
def test_noop_revision_matches_the_parent_exactly():
    parent = _parent()
    story = _story(parent)
    plan = plan_revision(parent, story, story, [])
    assert not plan.has_changes
    assert set(plan.shot_status.values()) == {"kept"}
    pkg = build_revision(parent, story, plan, story.shots, {})

    assert fingerprints(pkg) == fingerprints(parent)
    assert {a.node_id for a in pkg.assets} == {a.node_id for a in parent.assets}
    assert validate_package(pkg).ok
    as_tuples = lambda p: [(t.node_id, t.in_s, t.out_s) for t in p.timeline]  # noqa: E731
    assert as_tuples(pkg) == as_tuples(parent)
    assert pkg.schema_version == "1.2"
    # Assembly records each shot's breakdown tags, so a 1.2 child no longer needs inference.
    assert pkg.narrative.shots[4].location_id == "loc_canopy"


# --------------------------------------------------------------------------
# I4: untouched checkpoint edits survive
# --------------------------------------------------------------------------
def _checkpoint_edited_parent() -> ProductionPackage:
    parent = _parent()
    parent.asset_by_id("narration_full").text += " A line added at the checkpoint."
    parent.asset_by_id("narration_full").provider_hint = "elevenlabs:multilingual-v3"
    parent.asset_by_id("ref_jaguar_01").prompt = "Hand-tuned jaguar sheet."
    parent.asset_by_id("shot_001").prompt = "Dawn — slow pan over the canopy."
    parent.asset_by_id("shot_002").take = "abc12345"
    return parent


def test_checkpoint_edits_survive_an_unrelated_edit():
    parent = _checkpoint_edited_parent()
    story = _story(parent)
    story.script.scenes[-1].beat = "A new closing image."  # scene_09 only
    pkg = _revise(parent, story)

    assert validate_package(pkg).ok
    assert pkg.asset_by_id("narration_full").text == parent.asset_by_id("narration_full").text
    assert pkg.asset_by_id("narration_full").provider_hint == "elevenlabs:multilingual-v3"
    assert pkg.asset_by_id("ref_jaguar_01").prompt == "Hand-tuned jaguar sheet."
    assert pkg.asset_by_id("shot_001").prompt == "Dawn — slow pan over the canopy."
    assert pkg.asset_by_id("shot_002").take == "abc12345"
    # Everything outside scene_09 renders identically.
    changed = _changed_prints(parent, pkg)
    assert changed == {"shot_030"}


def test_a_narration_edit_rebuilds_the_text_but_keeps_the_hint():
    parent = _checkpoint_edited_parent()
    story = _story(parent)
    story.script.scenes[0].narration = "A brand new opening line."
    pkg = _revise(parent, story)
    narration = pkg.asset_by_id("narration_full")
    assert narration.text.startswith("A brand new opening line.")
    assert "checkpoint" not in narration.text
    assert narration.provider_hint == "elevenlabs:multilingual-v3"
    assert _changed_prints(parent, pkg) == {"narration_full"}


# --------------------------------------------------------------------------
# plan_revision: what goes stale, and each shot's status
# --------------------------------------------------------------------------
def _statuses(plan, scene_story: Story, scene_id: str) -> set[str]:
    return {plan.shot_status[s.id] for s in _shots(scene_story, scene_id)}


def test_scene_beat_change_makes_the_scene_stale():
    story = _story()
    story.script.scenes[2].beat = "The river floods."
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.stale_scenes == ["scene_03"]
    assert plan.shot_targets == {"scene_03": 5}
    assert _statuses(plan, story, "scene_03") == {"stale"}
    assert not plan.full_replan
    assert plan.from_stage == "script"
    assert plan.changes == ['Rewrote scene "The river that feeds it"', "Re-planned shots for 1 scene"]
    assert skipped_stages(plan) == ["world", "script"]


def test_hand_edited_shots_own_their_scene():
    story = _story()
    story.script.scenes[2].beat = "The river floods."
    _shots(story, "scene_03")[0].action = "Water pours over the bank."
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.stale_scenes == []
    first, *rest = _shots(story, "scene_03")
    assert plan.shot_status[first.id] == "edited"
    assert {plan.shot_status[s.id] for s in rest} == {"kept"}
    assert "Edited 1 shot" in plan.changes


def test_keep_shots_keeps_a_changed_scene():
    story = _story()
    story.script.scenes[2].beat = "The river, typo fixed."
    plan = plan_revision(PARENT, _story(), story, ["scene_03"])
    assert plan.stale_scenes == []
    assert _statuses(plan, story, "scene_03") == {"kept"}
    assert skipped_stages(plan) == ["world", "script", "breakdown", "prompts"]


def test_a_new_scene_without_shots_is_planned():
    story = _story()
    story.script.scenes.append(
        Scene(id="scene_10", heading="Epilogue", location="Amazon River", beat="Sunset.",
              narration="And so the river runs on, carrying the forest to the sea.")
    )
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.stale_scenes == ["scene_10"]
    assert plan.scene_status == {"scene_10": "new"}
    assert plan.shot_targets["scene_10"] >= 1


def test_a_duration_change_replans_every_untouched_scene():
    story = _story()
    story.brief.target_duration_s = 60
    plan = plan_revision(PARENT, _story(), story, [])
    assert len(plan.stale_scenes) == 9
    assert plan.full_replan
    assert plan.from_stage == "brief"
    assert "Length: 90s -> 60s" in plan.changes


def test_character_description_change_rewrites_its_prompts_and_ref():
    story = _story()
    jaguar = next(c for c in story.world.characters if c.id == "char_jaguar")
    jaguar.canonical_description = "A lean black jaguar with amber eyes."
    plan = plan_revision(PARENT, _story(), story, [])
    with_jaguar = {s.id for s in story.shots if "char_jaguar" in s.subject_ids}
    assert with_jaguar
    assert {plan.shot_status[i] for i in with_jaguar} == {"prompt"}
    assert {plan.shot_status[s.id] for s in story.shots if s.id not in with_jaguar} == {"kept"}
    assert plan.rerendered_refs == ["char_jaguar"]
    assert plan.entity_status == {"char_jaguar": "changed"}
    assert plan.changes == ["Changed character The Jaguar"]


def test_a_rename_rewrites_prompts_but_keeps_the_ref():
    story = _story()
    next(c for c in story.world.characters if c.id == "char_jaguar").name = "Onca"
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.entity_status == {"char_jaguar": "renamed"}
    assert plan.rerendered_refs == []
    assert "prompt" in plan.shot_status.values()
    assert plan.changes == ["Renamed The Jaguar -> Onca"]


def test_style_change_rewrites_everything_visual():
    story = _story()
    story.brief.style = "charcoal sketch"
    plan = plan_revision(PARENT, _story(), story, [])
    assert set(plan.shot_status.values()) == {"prompt"}
    assert len(plan.rerendered_refs) == 10
    assert not plan.narration_rerender


def test_voice_change_rerecords_only_the_narration():
    parent = _parent()
    story = _story(parent)
    story.brief.narration_voice_id = "elevenlabs_voice_adam"
    plan = plan_revision(parent, _story(parent), story, [])
    assert set(plan.shot_status.values()) == {"kept"}
    assert plan.rerendered_refs == []
    assert plan.narration_rerender and not plan.narration_changed
    assert plan.changes == ["Narration voice changed"]
    pkg = _revise(parent, story)
    assert pkg.asset_by_id("narration_full").spec["voice_id"] == "elevenlabs_voice_adam"
    assert _changed_prints(parent, pkg) == {"narration_full"}


def test_moving_a_shot_between_scenes_keeps_its_prompt():
    story = _story()
    story.shots[1].scene_id = "scene_02"  # last shot of scene_01 joins scene_02
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.stale_scenes == []
    assert set(plan.shot_status.values()) == {"kept"}
    assert "Reordered shots" in plan.changes


def test_reordering_shots_keeps_them():
    story = _story()
    story.shots[2], story.shots[3] = story.shots[3], story.shots[2]
    plan = plan_revision(PARENT, _story(), story, [])
    assert set(plan.shot_status.values()) == {"kept"}
    assert plan.changes == ["Reordered shots"]
    assert plan.from_stage == "shots"


def test_removing_a_character_strips_it_and_edits_those_shots():
    story = _story()
    story.world.characters = [c for c in story.world.characters if c.id != "char_macaw"]
    touched = [s for s in story.shots if "char_macaw" in s.subject_ids]
    for shot in touched:
        shot.subject_ids = [x for x in shot.subject_ids if x != "char_macaw"]
    plan = plan_revision(PARENT, _story(), story, [])
    assert touched
    assert {plan.shot_status[s.id] for s in touched} == {"edited"}
    assert plan.entity_status == {"char_macaw": "removed"}
    assert plan.from_stage == "world"


def test_removed_parent_shots_are_marked():
    story = _story()
    removed = story.shots.pop(0)
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.shot_status[removed.id] == "removed"
    assert "Removed 1 shot" in plan.changes


# --------------------------------------------------------------------------
# Targets, change lines, sanitizing
# --------------------------------------------------------------------------
def test_shot_targets():
    parent_story = _story()
    story = _story()
    story.script.scenes.append(Scene(id="scene_10", heading="Epilogue", location="Amazon River",
                                     beat="b", narration=" ".join(["word"] * 40)))
    targets = shot_targets(parent_story, story, ["scene_03", "scene_10"])
    assert targets["scene_03"] == 5
    total_words = sum(len(s.narration.split()) for s in story.script.scenes)
    assert targets["scene_10"] == max(1, round(90 * 40 / total_words / 3.5))


def test_change_lines_truncate_long_lists():
    story = _story()
    for i in range(5):
        story.world.characters.append(
            Character(id=f"char_new_{i}", name=f"N{i}", canonical_description="d")
        )
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.changes == ["Added characters N0, N1, N2 and 2 more"]


def test_change_lines_cover_the_brief_and_script():
    story = _story()
    story.brief.premise = "Something else entirely."
    story.brief.style = "ink wash"
    story.script.title = "Green Ocean"
    story.script.logline = "New logline."
    story.script.scenes[0], story.script.scenes[1] = story.script.scenes[1], story.script.scenes[0]
    plan = plan_revision(PARENT, _story(), story, [])
    assert plan.changes[:2] == [
        "Premise rewritten",
        'Style: "flat 2D animation, warm earth tones, soft painterly textures" -> "ink wash"',
    ]
    assert 'Title: "The Amazon Rainforest" -> "Green Ocean"' in plan.changes
    assert "Logline rewritten" in plan.changes
    assert "Reordered scenes" in plan.changes
    assert plan.from_stage == "brief"


def test_sanitize_replanned_repairs_bad_ids():
    story = _story()
    raw = ShotList(shots=[
        Shot(id="shot_001", scene_id="scene_03", shot_type="Wide", duration_s=40,
             location_id="loc_mars", subject_ids=["char_jaguar", "ghost"], action="a"),
        Shot(id="x", scene_id="scene_99", shot_type="wide", duration_s=3, location_id="loc_river",
             action="dropped"),
    ])
    out = sanitize_replanned(raw, story, {"scene_03": 2, "scene_04": 1})
    [shot] = out["scene_03"]
    assert shot.id == "rp_scene_03_1"
    assert shot.location_id == "loc_river"  # the scene's location, matched by name
    assert shot.subject_ids == ["char_jaguar"]
    assert shot.duration_s == 15
    assert shot.shot_type == "wide"
    [fallback] = out["scene_04"]
    assert fallback.action == story.script.scenes[3].beat
    assert fallback.shot_type == "wide"


# --------------------------------------------------------------------------
# Building after a script change, and the preview
# --------------------------------------------------------------------------
def test_a_replanned_scene_keeps_every_other_render():
    parent = _parent()
    story = _story(parent)
    story.script.scenes[2].beat = "The river floods."
    pkg = _revise(parent, story)
    assert validate_package(pkg).ok
    videos = [a for a in pkg.assets if a.type is AssetType.VIDEO]
    assert len(videos) == 30
    changed = _changed_prints(parent, pkg)
    assert len(changed) == 5
    assert all(pkg.asset_by_id(n).type is AssetType.VIDEO for n in changed)


def _hydrated(parent: ProductionPackage) -> ProductionPackage:
    hydrated = parent.model_copy(deep=True)
    for asset in hydrated.assets:
        asset.status = NodeStatus.SUCCEEDED
        asset.asset_url = f"s3://film-assets/{parent.project_id}/{asset.node_id}"
    return hydrated


def test_preview_predicts_reuse_and_cost():
    parent = _parent()
    story = _story(parent)
    story.script.scenes[2].beat = "The river floods."
    result = preview(_hydrated(parent), _story(parent), story, [], mode="new_version",
                     next_version=2, errors=[])
    assert result.next_version == 2
    assert (result.predicted_render, result.predicted_reuse) == (5, 36)
    assert result.predicted_cost_usd == pytest.approx(
        sum(parent.asset_by_id(s.id).estimated_cost_usd for s in _shots(story, "scene_03"))
    )
    assert result.stale_scenes == ["scene_03"]


def test_preview_counts_unfinished_parent_nodes_as_renders():
    parent = _parent()
    hydrated = _hydrated(parent)
    hydrated.asset_by_id("shot_010").status = NodeStatus.FAILED
    story = _story(parent)
    result = preview(hydrated, story, story, [], mode="new_version", next_version=2, errors=[])
    assert (result.predicted_render, result.predicted_reuse) == (1, 40)
    assert not result.has_changes


def test_preview_in_place_has_no_predictions_and_warns():
    parent = _parent()
    story = _story(parent)
    story.brief.style = "ink wash"
    story.script.scenes[0].location = "Mars"
    result = preview(parent, _story(parent), story, [], mode="in_place", next_version=5, errors=[])
    assert result.next_version is None
    assert result.predicted_render is None
    assert any("old style" in w for w in result.warnings)
    assert any("isn't a world location" in w for w in result.warnings)


def test_preview_warns_when_scene_narration_replaces_checkpoint_text():
    parent = _checkpoint_edited_parent()
    story = _story(parent)
    story.script.scenes[0].narration = "New."
    result = preview(parent, _story(parent), story, [], mode="in_place", next_version=None, errors=[])
    assert any("edited at the checkpoint" in w for w in result.warnings)
