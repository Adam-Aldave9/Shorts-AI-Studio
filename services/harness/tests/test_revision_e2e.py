"""In-process $0 revision: a finished v1 is revised (one shot, one line of narration), and
v2 renders only those two nodes, reusing every other render of v1. A no-op v3 then renders
nothing at all and goes straight to the compositor.

Drives the real planning revision job, the real scheduler approve, the real daemon and the
real worker task body against one fakeredis, in MOCK mode."""

from __future__ import annotations

import asyncio

import pytest
import state
from adapters import mock as mock_adapter
from schema import Character, Lineage, Location, World
from tenacity import wait_none

from planning import main as planning_main
from planning.assembly import assemble_package
from planning.models import Screenplay, ShotList, ShotPrompts
from planning.revision import RevisionRequest
from scheduler import daemon
from scheduler import main as scheduler_main
from scheduler.celery_app import COMPOSITE_TASK, RENDER_TASK
from worker import render, tasks

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _v1():
    world = World(
        characters=[Character(id="char_heron", name="The Heron",
                              canonical_description="A tall grey heron.")],
        locations=[
            Location(id="loc_river", name="River", canonical_description="A wide brown river."),
            Location(id="loc_reeds", name="Reeds", canonical_description="Tall green reeds."),
        ],
    )
    screenplay = Screenplay(title="Heron", logline="A heron's morning.", scenes=[
        {"id": "scene_01", "heading": "River dawn", "location": "River",
         "beat": "Mist on the water", "narration": "The river wakes."},
        {"id": "scene_02", "heading": "Reeds", "location": "Reeds",
         "beat": "The heron hunts", "narration": "In the reeds, a hunter waits."},
    ])
    shots = ShotList(shots=[
        {"id": "a", "scene_id": "scene_01", "shot_type": "aerial", "duration_s": 4,
         "location_id": "loc_river", "subject_ids": [], "action": "Pan over the river"},
        {"id": "b", "scene_id": "scene_01", "shot_type": "wide", "duration_s": 4,
         "location_id": "loc_river", "subject_ids": ["char_heron"], "action": "The heron lands"},
        {"id": "c", "scene_id": "scene_02", "shot_type": "close-up", "duration_s": 4,
         "location_id": "loc_reeds", "subject_ids": ["char_heron"], "action": "The heron strikes"},
    ])
    prompts = ShotPrompts(prompts=[
        {"shot_id": "a", "prompt": "Aerial pan over a wide brown river. Flat 2D."},
        {"shot_id": "b", "prompt": "A tall grey heron lands at the bank. Flat 2D."},
        {"shot_id": "c", "prompt": "Close on a tall grey heron striking. Flat 2D."},
    ])
    brief = {"premise": "A heron's morning on the river", "target_duration_s": 12,
             "style": "flat 2D", "narration_voice_id": "v"}
    pkg = assemble_package(brief, world, screenplay, shots, prompts)
    pkg.lineage = Lineage(film_id=pkg.project_id, version=1)
    return pkg


class _NoLimitBucket:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def acquire(self, tokens: int = 1) -> None:
        return None


class _NoStorage:
    pass


@pytest.fixture
def fast_mock(monkeypatch):
    for kind, (_, cost) in list(mock_adapter._PROFILES.items()):
        # Not 0: expovariate(1/0) divides by zero.
        monkeypatch.setitem(mock_adapter._PROFILES, kind, (0.001, cost))
    monkeypatch.setattr(render, "_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(render, "RETRY_WAIT", wait_none())
    monkeypatch.setattr(render, "TokenBucket", _NoLimitBucket)
    monkeypatch.setattr(render, "Storage", _NoStorage)


async def _finish_job(job_id: str) -> str:
    for _ in range(250):
        frame = await state.get_plan_job(job_id)
        if frame and frame["status"] == state.PLAN_SUCCEEDED:
            return frame["project_id"]
        assert not frame or frame["status"] != state.PLAN_FAILED, frame["errors"]
        await asyncio.sleep(0.02)
    raise AssertionError(f"revision job {job_id} did not finish")


def test_revision_renders_only_what_changed(fast_mock, monkeypatch):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    sends: list[tuple[str, list]] = []

    def fake_send_task(name, args=None, queue=None, **_):
        sends.append((name, args))

    monkeypatch.setattr(daemon.celery_app, "send_task", fake_send_task)
    handled = 0

    async def drain() -> None:
        """Tick the daemon and run whatever it sends, until it sends nothing new."""
        nonlocal handled
        while True:
            async for package in state.iter_approved_packages():
                await daemon._advance(package)
            new = sends[handled:]
            if not new:
                return
            handled = len(sends)
            for name, args in new:
                if name == RENDER_TASK:
                    await tasks.execute(*args)

    async def revise(project_id: str, edit=None) -> str:
        view = await planning_main.get_story(project_id)
        story = view.story.model_copy(deep=True)
        if edit is not None:
            edit(story)
        accepted = await planning_main.create_revision(
            project_id, RevisionRequest(story=story, base_hash=view.base_hash), user_id="u"
        )
        return await _finish_job(accepted.job_id)

    def edit_shot_and_narration(story) -> None:
        story.shots[1].action = "The heron lands and folds its wings"
        story.script.scenes[1].narration = "Among the reeds, a patient hunter waits."

    async def scenario() -> None:
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        daemon.use_budget_client(client)
        monkeypatch.setattr(render.redis, "from_url", lambda *a, **k: client)
        try:
            v1 = _v1()
            await state.save_package(v1, approved=True, owner_id="u")
            await drain()
            assert await state.get_project_phase(v1.project_id) == state.PHASE_COMPOSITING
            await state.set_final_url(v1.project_id, f"s3://film-assets/{v1.project_id}/final.mp4")
            await state.set_project_phase(v1.project_id, state.PHASE_COMPLETE)
            assert [name for name, _ in sends].count(RENDER_TASK) == 3 + 3 + 1

            v2 = await revise(v1.project_id, edit_shot_and_narration)
            assert v2 != v1.project_id
            result = await scheduler_main.approve(v2)
            assert result.reused == 3 + 2  # 3 refs + 2 untouched shots
            before = len(sends)
            await drain()

            rendered = sorted(args[1] for name, args in sends[before:] if name == RENDER_TASK)
            assert rendered == ["narration_full", "shot_002"]
            assert [name for name, _ in sends[before:]].count(COMPOSITE_TASK) == 1
            assert await state.get_project_phase(v2) == state.PHASE_COMPOSITING
            package = await state.get_package(v2)
            for asset in package.assets:
                live = await state.get_node(v2, asset.node_id)
                assert live["status"] == "succeeded"
                if asset.node_id not in rendered:
                    assert live["reused_from"] == f"{v1.project_id}/{asset.node_id}"
            costs = {kind: cost for kind, (_, cost) in mock_adapter._PROFILES.items()}
            assert await state.get_cost(v2) == pytest.approx(costs["video"] + costs["voiceover"])
            await state.set_project_phase(v2, state.PHASE_COMPLETE)

            v3 = await revise(v2)
            assert (await state.get_package(v3)).lineage.version == 3
            before = len(sends)
            await scheduler_main.approve(v3)
            await drain()
            assert [name for name, _ in sends[before:]] == [COMPOSITE_TASK]
            assert await state.get_cost(v3) == 0.0

            versions = await scheduler_main.list_versions(v3)
            assert [v.version for v in versions] == [1, 2, 3]
        finally:
            state.use_client(None)
            daemon.use_budget_client(None)

    asyncio.run(scenario())
