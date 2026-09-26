"""The revision job end to end in the planning process: request checks, the job frame,
persistence as a new version or in place, and the live path's scoped agent calls."""

from __future__ import annotations

import asyncio

import pytest
from schema import Lineage, NodeStatus, ProductionPackage

import state
from planning import main, revision
from planning.graph import _load_mock_package
from planning.models import ShotList, ShotPrompt, ShotPrompts
from planning.revision import RevisionRequest
from planning.story import story_from_package, story_hash

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


async def drive_job_to_terminal(job_id: str, timeout_s: float = 5.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        frame = await state.get_plan_job(job_id)
        if frame and frame["status"] in {state.PLAN_SUCCEEDED, state.PLAN_FAILED}:
            return frame
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def _run(scenario, monkeypatch, *, mock: bool = True):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    if mock:
        monkeypatch.setenv("MOCK", "true")
    else:
        monkeypatch.delenv("MOCK", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def wrapper():
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        try:
            await scenario()
        finally:
            state.use_client(None)

    asyncio.run(wrapper())


async def _parent(*, approved: bool) -> ProductionPackage:
    pkg = _load_mock_package({})
    pkg.lineage = Lineage(film_id=pkg.project_id, version=1)
    await state.save_package(pkg, approved=approved, owner_id="u")
    if approved:
        for node_id in ("ref_canopy_01", "shot_001"):
            await state.set_node_status(pkg.project_id, node_id, NodeStatus.SUCCEEDED,
                                        asset_url=f"s3://film-assets/x/{node_id}")
    return pkg


def _request(pkg: ProductionPackage, edit=None, **kw) -> RevisionRequest:
    base = story_from_package(pkg)
    story = base.model_copy(deep=True)
    if edit is not None:
        edit(story)
    return RevisionRequest(story=story, base_hash=story_hash(base), **kw)


def _beat(story):
    story.script.scenes[2].beat = "The river floods."


async def _create(pid: str, request: RevisionRequest) -> dict:
    accepted = await main.create_revision(pid, request, user_id="u")
    return await drive_job_to_terminal(accepted.job_id)


def test_revising_an_approved_version_creates_v2(monkeypatch):
    async def scenario():
        parent = await _parent(approved=True)
        raw_before = await state.get_package_raw(parent.project_id)
        accepted = await main.create_revision(
            parent.project_id, _request(parent, _beat, note="brighter river"), user_id="u"
        )
        started = await state.get_plan_job(accepted.job_id)
        assert (started["kind"], started["mode"]) == ("revision", "new_version")
        assert started["skipped"] == ["world", "script"]
        assert started["details"]["world"]["edited"] is False

        frame = await drive_job_to_terminal(accepted.job_id)
        assert frame["status"] == state.PLAN_SUCCEEDED, frame["errors"]
        assert frame["details"]["breakdown"] == {"shots": 30, "replanned": 1}
        assert frame["details"]["prompts"] == {"done": 5, "total": 5}
        v2_id = frame["project_id"]
        assert v2_id != parent.project_id

        v2 = await state.get_package(v2_id)
        assert v2.lineage.film_id == parent.project_id
        assert v2.lineage.version == 2
        assert v2.lineage.parent_project_id == parent.project_id
        assert v2.lineage.from_stage == "script"
        assert v2.lineage.note == "brighter river"
        assert v2.lineage.changes == [
            'Rewrote scene "The river that feeds it"',
            "Re-planned shots for 1 scene",
            "Rewrote 5 shot prompts",
        ]
        assert await state.get_project_owner(v2_id) == "u"
        assert not await state.is_package_approved(v2_id)

        # I3: the approved parent is untouched, spec and live state.
        assert await state.get_package_raw(parent.project_id) == raw_before
        assert (await state.get_node(parent.project_id, "shot_001"))["status"] == "succeeded"

        # The next revision of the film is v3, whichever version it starts from.
        await state.approve_package(v2_id)
        frame3 = await _create(parent.project_id, _request(parent))
        assert (await state.get_package(frame3["project_id"])).lineage.version == 3

    _run(scenario, monkeypatch)


def test_revising_a_draft_updates_it_in_place(monkeypatch):
    async def scenario():
        parent = await _parent(approved=False)

        def narration(story):
            story.script.scenes[0].narration = "A new first line."

        frame = await _create(parent.project_id, _request(parent, narration))
        assert frame["status"] == state.PLAN_SUCCEEDED, frame["errors"]
        assert frame["project_id"] == parent.project_id
        assert frame["mode"] == "in_place"
        assert sorted(frame["skipped"]) == ["breakdown", "prompts", "script", "world"]

        draft = await state.get_package(parent.project_id)
        assert draft.asset_by_id("narration_full").text.startswith("A new first line.")
        assert (draft.lineage.film_id, draft.lineage.version) == (parent.project_id, 1)
        assert draft.lineage.changes == ['New narration in scene "Dawn over the canopy"']
        assert draft.created_at == parent.created_at
        assert await state.get_project_owner(parent.project_id) == "u"
        ids = [p.project_id async for p in state.iter_user_packages("u")]
        assert ids == [parent.project_id]

    _run(scenario, monkeypatch)


def test_a_draft_approved_mid_job_becomes_a_new_version(monkeypatch):
    async def never(_package):
        return False

    monkeypatch.setattr(main.state, "replace_package_if_unapproved", never)

    async def scenario():
        parent = await _parent(approved=False)
        frame = await _create(parent.project_id, _request(parent, _beat))
        assert frame["status"] == state.PLAN_SUCCEEDED
        assert frame["project_id"] != parent.project_id
        assert (await state.get_package(frame["project_id"])).lineage.version == 2

    _run(scenario, monkeypatch)


def test_request_errors(monkeypatch):
    async def scenario():
        parent = await _parent(approved=False)
        stale = _request(parent, _beat)
        stale.base_hash = "0" * 16
        with pytest.raises(main.HTTPException) as exc:
            await main.create_revision(parent.project_id, stale, user_id="u")
        assert exc.value.status_code == 409

        def bad(story):
            story.shots[0].location_id = "loc_mars"

        with pytest.raises(main.HTTPException) as exc:
            await main.create_revision(parent.project_id, _request(parent, bad), user_id="u")
        assert exc.value.status_code == 422
        assert any("loc_mars" in e for e in exc.value.detail)

        with pytest.raises(main.HTTPException) as exc:
            await main.create_revision(parent.project_id, _request(parent), user_id="u")
        assert exc.value.status_code == 422
        assert exc.value.detail == "Nothing to change."

        with pytest.raises(main.HTTPException) as exc:
            await main.create_revision("p_missing", _request(parent), user_id="u")
        assert exc.value.status_code == 404

    _run(scenario, monkeypatch)


def test_a_noop_revision_of_an_approved_version_is_allowed(monkeypatch):
    async def scenario():
        parent = await _parent(approved=True)
        frame = await _create(parent.project_id, _request(parent))
        assert frame["status"] == state.PLAN_SUCCEEDED
        assert sorted(frame["skipped"]) == ["breakdown", "prompts", "script", "world"]
        v2 = await state.get_package(frame["project_id"])
        assert v2.lineage.changes == []

    _run(scenario, monkeypatch)


def test_a_validation_failure_fails_the_job(monkeypatch):
    from validator import ValidationReport

    monkeypatch.setattr(main, "validate_package", lambda _pkg: ValidationReport(errors=["nope"]))

    async def scenario():
        parent = await _parent(approved=True)
        frame = await _create(parent.project_id, _request(parent, _beat))
        assert frame["status"] == state.PLAN_FAILED
        assert frame["errors"] == ["nope"]

    _run(scenario, monkeypatch)


def test_preview_endpoint(monkeypatch):
    async def scenario():
        parent = await _parent(approved=True)
        result = await main.preview_revision(parent.project_id, _request(parent, _beat))
        assert result.mode == "new_version"
        assert result.next_version == 2
        assert result.stale_scenes == ["scene_03"]
        # Only ref_canopy_01 and shot_001 (animated from it) rendered in this fixture.
        assert (result.predicted_render, result.predicted_reuse) == (39, 2)

        def bad(story):
            story.brief.premise = ""

        broken = await main.preview_revision(parent.project_id, _request(parent, bad))
        assert broken.errors and broken.predicted_render is None

    _run(scenario, monkeypatch)


def test_live_path_scopes_agent_calls(monkeypatch):
    seen: dict = {}

    def fake_run_scenes(brief, screenplay, world, targets, **kw):
        seen["targets"] = dict(targets)
        return ShotList(shots=[])

    def fake_prompts(brief, shot_list, world, *, on_progress=None, **kw):
        seen["prompted"] = [s.id for s in shot_list.shots]
        if on_progress:
            on_progress(len(shot_list.shots), len(shot_list.shots))
        return ShotPrompts(prompts=[
            ShotPrompt(shot_id=s.id, prompt=f"live {s.id}") for s in shot_list.shots
        ])

    def unexpected(*a, **kw):
        raise AssertionError("a full breakdown was not expected")

    monkeypatch.setattr(revision.breakdown, "run_scenes", fake_run_scenes)
    monkeypatch.setattr(revision.breakdown, "run", unexpected)
    monkeypatch.setattr(revision.prompts, "run", fake_prompts)

    async def scenario():
        parent = await _parent(approved=True)

        def edits(story):
            _beat(story)
            next(s for s in story.shots if s.id == "shot_001").action = "A new opening move."

        frame = await _create(parent.project_id, _request(parent, edits))
        assert frame["status"] == state.PLAN_SUCCEEDED, frame["errors"]
        v2 = await state.get_package(frame["project_id"])
        assert v2.asset_by_id("shot_001").prompt == "live shot_001"

    _run(scenario, monkeypatch, mock=False)
    assert seen["targets"] == {"scene_03": 5}
    # scene_03 returned nothing, so it gets one fallback shot.
    assert seen["prompted"] == ["shot_001", "rp_scene_03_1"]
