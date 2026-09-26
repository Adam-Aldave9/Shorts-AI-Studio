"""Render reuse across the versions of one film: source selection, atomic approve with
seeds, lineage guards, the version list, and playback redirects (fakeredis, no network)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import state
from schema import Asset, AssetType, Lineage, Meta, NodeStatus, ProductionPackage

from scheduler import daemon, main, reuse
from scheduler.celery_app import COMPOSITE_TASK, RENDER_TASK

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None

FILM = "p_v1"


def _pkg(project_id: str = FILM, version: int = 1, parent: str | None = None) -> ProductionPackage:
    return ProductionPackage(
        project_id=project_id,
        created_at=datetime(2026, 9, version, tzinfo=timezone.utc),
        meta=Meta(title="River Song", premise="P", target_duration_s=6, style="s",
                  narration_voice_id="v", budget_usd=100.0),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                  prompt="a tree", estimated_cost_usd=0.03),
            Asset(node_id="ref_b", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                  prompt="a river", estimated_cost_usd=0.03),
            Asset(node_id="shot_a", type=AssetType.VIDEO, provider_hint="fal:pixverse-v6-i2v",
                  depends_on=["ref_a"], reference_image_ids=["ref_a"], prompt="tree sways",
                  spec={"duration_s": 3.0}, estimated_cost_usd=0.10),
            Asset(node_id="shot_b", type=AssetType.VIDEO, provider_hint="fal:pixverse-v6-i2v",
                  depends_on=["ref_b"], reference_image_ids=["ref_b"], prompt="river flows",
                  spec={"duration_s": 3.0}, estimated_cost_usd=0.10),
        ],
        lineage=Lineage(film_id=FILM, version=version, parent_project_id=parent),
    )


def _run(scenario, monkeypatch=None, mock: bool = True) -> list[tuple]:
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    sends: list[tuple] = []

    def fake_send_task(name, args=None, queue=None, **_):
        sends.append((name, args, queue))

    async def wrapper():
        client = fakeredis_aio.FakeRedis(decode_responses=True)
        state.use_client(client)
        daemon.use_budget_client(client)
        original = daemon.celery_app.send_task
        daemon.celery_app.send_task = fake_send_task
        try:
            await scenario()
        finally:
            daemon.celery_app.send_task = original
            state.use_client(None)
            daemon.use_budget_client(None)

    if monkeypatch is not None:
        if mock:
            monkeypatch.setenv("MOCK", "true")
        else:
            monkeypatch.delenv("MOCK", raising=False)
    asyncio.run(wrapper())
    return sends


async def _rendered_v1(owner: str = "u", project_id: str = FILM, version: int = 1,
                       parent: str | None = None, url_root: str = "s3://film-assets") -> None:
    """Save a version as approved with every node succeeded."""
    pkg = _pkg(project_id, version, parent)
    await state.save_package(pkg, approved=True, owner_id=owner)
    ext = {"ref_a": "png", "ref_b": "png", "shot_a": "mp4", "shot_b": "mp4"}
    for node_id, suffix in ext.items():
        url = f"{url_root}/{project_id}/{node_id}.{suffix}"
        await state.set_node_status(project_id, node_id, NodeStatus.SUCCEEDED, asset_url=url,
                                    provider_url=f"https://fal.media/{project_id}/{node_id}")


async def _draft_v2(owner: str = "u", project_id: str = "p_v2", parent: str = FILM,
                    version: int = 2) -> ProductionPackage:
    pkg = _pkg(project_id, version, parent)
    await state.save_package(pkg, owner_id=owner)
    return pkg


# --------------------------------------------------------------------------
# Reuse sources
# --------------------------------------------------------------------------
def test_reuses_from_another_version_of_the_same_film(monkeypatch):
    async def scenario():
        await _rendered_v1()
        v2 = await _draft_v2()
        v2.asset_by_id("shot_b").prompt = "river roars"
        matched = reuse.match(v2, await reuse.reuse_sources(v2, "u"))
        assert set(matched) == {"ref_a", "ref_b", "shot_a"}
        assert matched["shot_a"].project_id == FILM
        assert matched["shot_a"].asset_url == f"s3://film-assets/{FILM}/shot_a.mp4"
        assert matched["shot_a"].version == 1

    _run(scenario, monkeypatch)


def test_ignores_other_films_owners_itself_and_unfinished_nodes(monkeypatch):
    async def scenario():
        # Same content, but another film / another owner.
        other_film = _pkg("p_other")
        other_film.lineage = Lineage(film_id="p_other")
        await state.save_package(other_film, approved=True, owner_id="u")
        await state.set_node_status("p_other", "ref_a", NodeStatus.SUCCEEDED, asset_url="s3://x/a")
        await _rendered_v1(owner="someone_else")
        v2 = await _draft_v2()
        assert await reuse.reuse_sources(v2, "u") == {}

        # The package's own succeeded nodes never count, nor do failed ones elsewhere.
        await state.set_node_status("p_v2", "ref_a", NodeStatus.SUCCEEDED, asset_url="s3://x/b")
        v3 = _pkg("p_v3", 3, "p_v2")
        await state.save_package(v3, owner_id="u")
        await state.set_node_status("p_v2", "ref_b", NodeStatus.FAILED, asset_url="s3://x/c")
        matched = reuse.match(v3, await reuse.reuse_sources(v3, "u"))
        assert set(matched) == {"ref_a"}
        assert matched["ref_a"].project_id == "p_v2"
        assert reuse.match(v2, await reuse.reuse_sources(v2, "u")) == {}

    _run(scenario, monkeypatch)


def test_v1_and_unowned_packages_have_no_sources(monkeypatch):
    async def scenario():
        await _rendered_v1()
        v1 = _pkg()
        assert await reuse.reuse_sources(v1, "u") == {}
        assert await reuse.reuse_sources(_pkg("p_v2", 2, FILM), None) == {}

    _run(scenario, monkeypatch)


def test_real_mode_skips_mock_assets_and_images_without_http_urls(monkeypatch):
    async def scenario():
        await _rendered_v1(url_root="s3://film-assets/_mock")
        v2 = await _draft_v2()
        assert await reuse.reuse_sources(v2, "u") == {}

        v1b = _pkg("p_v1b", 3, FILM)
        await state.save_package(v1b, approved=True, owner_id="u")
        await state.set_node_status("p_v1b", "ref_a", NodeStatus.SUCCEEDED,
                                    asset_url="s3://film-assets/p_v1b/ref_a.png",
                                    provider_url="s3://film-assets/p_v1b/ref_a.png")
        await state.set_node_status("p_v1b", "shot_a", NodeStatus.SUCCEEDED,
                                    asset_url="s3://film-assets/p_v1b/shot_a.mp4",
                                    provider_url="s3://film-assets/p_v1b/shot_a.mp4")
        matched = reuse.match(v2, await reuse.reuse_sources(v2, "u"))
        assert set(matched) == {"shot_a"}

    _run(scenario, monkeypatch, mock=False)


def test_mock_mode_reuses_placeholders(monkeypatch):
    async def scenario():
        await _rendered_v1(url_root="s3://film-assets/_mock")
        v2 = await _draft_v2()
        assert len(reuse.match(v2, await reuse.reuse_sources(v2, "u"))) == 4

    _run(scenario, monkeypatch)


def test_prefers_the_parent_then_the_highest_version(monkeypatch):
    async def scenario():
        await _rendered_v1()
        await _rendered_v1(project_id="p_v2", version=2, parent=FILM)
        await _rendered_v1(project_id="p_v3", version=3, parent=FILM)
        v4 = _pkg("p_v4", 4, "p_v2")
        await state.save_package(v4, owner_id="u")
        assert reuse.match(v4, await reuse.reuse_sources(v4, "u"))["ref_a"].project_id == "p_v2"

        v5 = _pkg("p_v5", 5, "p_missing")
        await state.save_package(v5, owner_id="u")
        assert reuse.match(v5, await reuse.reuse_sources(v5, "u"))["ref_a"].project_id == "p_v3"

    _run(scenario, monkeypatch)


# --------------------------------------------------------------------------
# Approve with reuse
# --------------------------------------------------------------------------
def test_approve_seeds_reused_nodes(monkeypatch):
    async def scenario():
        await _rendered_v1()
        v2 = await _draft_v2()
        v2.asset_by_id("shot_b").prompt = "river roars"
        await main.update_package("p_v2", v2)

        result = await main.approve("p_v2")
        assert (result.status, result.reused) == ("approved", 3)
        got = await state.get_package("p_v2")
        assert got.asset_by_id("shot_a").status is NodeStatus.SUCCEEDED
        assert got.asset_by_id("shot_a").asset_url == f"s3://film-assets/{FILM}/shot_a.mp4"
        assert got.asset_by_id("shot_b").status is NodeStatus.PENDING
        live = await state.get_node("p_v2", "ref_a")
        assert live["reused_from"] == f"{FILM}/ref_a"
        assert live["provider_url"] == f"https://fal.media/{FILM}/ref_a"
        assert live["actual_cost_usd"] == "0"

    _run(scenario, monkeypatch)


def test_rerender_cascades_from_an_image_to_its_shots(monkeypatch):
    async def scenario():
        await _rendered_v1()
        await _draft_v2()
        result = await main.approve("p_v2", main.ApproveRequest(rerender=["ref_a"]))
        assert result.reused == 2
        got = await state.get_package("p_v2")
        assert {a.node_id for a in got.assets if a.status is NodeStatus.SUCCEEDED} == {"ref_b", "shot_b"}
        assert got.asset_by_id("ref_a").take

    _run(scenario, monkeypatch)


def test_approve_rejects_unknown_rerender_ids(monkeypatch):
    async def scenario():
        await _draft_v2()
        with pytest.raises(main.HTTPException) as exc:
            await main.approve("p_v2", main.ApproveRequest(rerender=["ghost"]))
        assert exc.value.status_code == 422
        assert not await state.is_package_approved("p_v2")

    _run(scenario, monkeypatch)


def test_v1_never_seeds(monkeypatch):
    async def scenario():
        await _rendered_v1(project_id="p_other", version=2, parent=FILM)
        await state.save_package(_pkg(), owner_id="u")
        result = await main.approve(FILM)
        assert result.reused == 0

    _run(scenario, monkeypatch)


def test_seeded_nodes_are_never_dispatched_and_a_full_reuse_composites_once(monkeypatch):
    async def scenario():
        await _rendered_v1()
        await _draft_v2()
        await main.approve("p_v2")
        for _ in range(3):
            async for pkg in state.iter_approved_packages():
                if pkg.project_id == "p_v2":
                    await daemon._advance(pkg)
        assert await state.get_project_phase("p_v2") == state.PHASE_COMPOSITING

    sends = _run(scenario, monkeypatch)
    assert [(name, args) for name, args, _ in sends] == [(COMPOSITE_TASK, ["p_v2"])]


def test_partial_reuse_dispatches_only_the_rest(monkeypatch):
    async def scenario():
        await _rendered_v1()
        v2 = await _draft_v2()
        v2.asset_by_id("shot_b").prompt = "river roars"
        await main.update_package("p_v2", v2)
        await main.approve("p_v2")
        await daemon._advance(await state.get_package("p_v2"))

    sends = _run(scenario, monkeypatch)
    assert [args for name, args, _ in sends if name == RENDER_TASK] == [["p_v2", "shot_b"]]


# --------------------------------------------------------------------------
# Lineage guards
# --------------------------------------------------------------------------
def test_put_preserves_the_stored_lineage(monkeypatch):
    async def scenario():
        await _draft_v2()
        body = _pkg("p_v2", 2, FILM)
        body.lineage = Lineage(film_id="p_hijack", version=99)
        result = await main.update_package("p_v2", body)
        assert result.lineage.film_id == FILM
        assert (await state.get_package("p_v2")).lineage.version == 2

    _run(scenario, monkeypatch)


def test_post_strips_lineage(monkeypatch):
    async def scenario():
        await main.create_package(_pkg("p_imp", 5, FILM), user_id="u")
        assert (await state.get_package("p_imp")).lineage is None

    _run(scenario, monkeypatch)


def test_list_packages_reports_film_and_version(monkeypatch):
    async def scenario():
        await _rendered_v1()
        await _draft_v2()
        rows = {s.project_id: s for s in await main.list_packages(user_id="u")}
        assert (rows["p_v2"].film_id, rows["p_v2"].version, rows["p_v2"].parent_project_id) == (
            FILM, 2, FILM)
        assert (rows[FILM].film_id, rows[FILM].version) == (FILM, 1)

    _run(scenario, monkeypatch)


# --------------------------------------------------------------------------
# Versions + reuse plan
# --------------------------------------------------------------------------
def test_versions_are_sorted_and_film_scoped(monkeypatch):
    async def scenario():
        await _draft_v2(project_id="p_v3", version=3, parent="p_v2")
        await _rendered_v1()
        await _draft_v2()
        unrelated = _pkg("p_x")
        unrelated.lineage = None
        await state.save_package(unrelated, owner_id="u")
        await state.set_final_url(FILM, f"s3://film-assets/{FILM}/final.mp4")

        versions = await main.list_versions("p_v2")
        assert [v.project_id for v in versions] == [FILM, "p_v2", "p_v3"]
        assert [v.version for v in versions] == [1, 2, 3]
        assert versions[0].approved and versions[0].has_final_cut
        assert not versions[1].approved and not versions[1].has_final_cut
        assert [v.project_id for v in await main.list_versions("p_x")] == ["p_x"]

    _run(scenario, monkeypatch)


def test_reuse_plan_before_and_after_approval(monkeypatch):
    async def scenario():
        await _rendered_v1()
        v2 = await _draft_v2()
        v2.asset_by_id("shot_b").prompt = "river roars"
        await main.update_package("p_v2", v2)

        preview = await main.reuse_plan("p_v2")
        assert preview.final is False
        assert set(preview.nodes) == {"ref_a", "ref_b", "shot_a"}
        assert preview.nodes["shot_a"].source_version == 1
        assert preview.full_cost_usd == pytest.approx(0.26)
        assert preview.render_cost_usd == pytest.approx(0.10)

        await main.approve("p_v2", main.ApproveRequest(rerender=["ref_b"]))
        final = await main.reuse_plan("p_v2")
        assert final.final is True
        assert set(final.nodes) == {"ref_a", "shot_a"}
        assert final.nodes["ref_a"].source_project_id == FILM
        assert final.nodes["ref_a"].source_version == 1

    _run(scenario, monkeypatch)


def test_status_event_carries_reused_from(monkeypatch):
    async def scenario():
        await _rendered_v1()
        await _draft_v2()
        await main.approve("p_v2")
        frame = await main._status_event("p_v2")
        assert frame["nodes"]["shot_a"]["reused_from"] == f"{FILM}/shot_a"

    _run(scenario, monkeypatch)


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------
class _FakeMedia:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def presigned_get_url(self, key, *, download_name=None, expires_s=3600):
        self.calls.append((key, download_name))
        return f"http://localhost:9000/signed?key={key}"


def test_final_cut_404_without_a_final_url(monkeypatch):
    async def scenario():
        await _draft_v2()
        with pytest.raises(main.HTTPException) as exc:
            await main.final_cut("p_v2")
        assert exc.value.status_code == 404

    _run(scenario, monkeypatch)


def test_final_cut_redirects_to_a_presigned_url(monkeypatch):
    media = _FakeMedia()
    monkeypatch.setattr(main, "_media", lambda: media)

    async def scenario():
        await _draft_v2()
        await state.set_final_url("p_v2", "s3://film-assets/p_v2/final.mp4")
        response = await main.final_cut("p_v2")
        assert response.status_code == 307
        assert response.headers["location"].startswith("http://localhost:9000/signed")
        await main.final_cut("p_v2", download=1)

    _run(scenario, monkeypatch)
    assert media.calls == [
        ("s3://film-assets/p_v2/final.mp4", None),
        ("s3://film-assets/p_v2/final.mp4", "river-song-v2.mp4"),
    ]
