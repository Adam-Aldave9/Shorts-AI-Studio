"""Postgres durability layer (:mod:`state.pg`).

Two tiers, matching the plan's "option 2" verification:

* **Pure-fn units** (always run): the SQL constants + param-binding + row-mapping
  helpers, which touch neither ``psycopg`` nor a database.
* **Opt-in integration** (auto-skips): the real write-through / read-fallback round
  trip against a live Postgres. Skips cleanly when ``psycopg`` is not installed or no
  database is reachable, so the offline suite stays green. Point it at a database with
  ``AFP_TEST_POSTGRES_URL`` (default: the compose mapping on ``localhost:5432``); the
  usual way to make it run is ``docker compose up -d postgres``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

import pytest

from schema import Asset, AssetType, Meta, NodeStatus, ProductionPackage

import state
from state import pg

try:
    import fakeredis.aioredis as fakeredis_aio
except ImportError:  # pragma: no cover - optional dev dependency
    fakeredis_aio = None


def _pkg(project_id: str = "p_test") -> ProductionPackage:
    return ProductionPackage(
        project_id=project_id,
        meta=Meta(
            title="T",
            premise="P",
            target_duration_s=6,
            style="s",
            narration_voice_id="v_meta",
            budget_usd=15.0,
        ),
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, provider_hint="fal:flux-schnell", prompt="x"),
            Asset(
                node_id="shot_a",
                type=AssetType.VIDEO,
                depends_on=["ref_a"],
                reference_image_ids=["ref_a"],
                provider_hint="fal:pixverse-v6-i2v",
                spec={"duration_s": 3.0},
                prompt="y",
            ),
        ],
    )


# --------------------------------------------------------------------------
# Pure-fn units (no psycopg, no database)
# --------------------------------------------------------------------------
def test_init_statements_are_idempotent_ddl():
    joined = "\n".join(pg.INIT_STATEMENTS).lower()
    assert "create table if not exists packages" in joined
    assert "create table if not exists node_history" in joined
    assert "create or replace view cost_actuals" in joined


def test_enabled_reflects_postgres_url(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert pg.enabled() is False
    monkeypatch.setenv("POSTGRES_URL", "postgresql://x")
    assert pg.enabled() is True


def test_package_params_extracts_columns_and_full_spec():
    pkg = _pkg()
    params = pg.package_params(pkg, approved=True)
    assert params["project_id"] == pkg.project_id
    assert params["title"] == pkg.meta.title
    assert params["schema_version"] == pkg.schema_version
    assert params["created_at"] == pkg.created_at
    assert params["approved"] is True
    # spec is the full JSON-mode dump (the replay source of truth)
    assert params["spec"] == pkg.model_dump(mode="json")


def test_package_params_approved_none_is_preserved_as_none():
    # None means "do not touch the stored approved flag" (the upsert COALESCEs it).
    assert pg.package_params(_pkg(), approved=None)["approved"] is None


def test_node_params_maps_status_cost_and_drops_asset_url():
    params = pg.node_params(
        "p",
        "ref_a",
        NodeStatus.SUCCEEDED,
        {"asset_url": "s3://x", "provider_url": "https://fal/x", "actual_cost_usd": 0.04},
    )
    assert params == {
        "project_id": "p",
        "node_id": "ref_a",
        "status": "succeeded",  # enum coerced to its value
        "actual_cost_usd": 0.04,
        "provider_url": "https://fal/x",
        "error": None,
    }
    # asset_url is a Redis field, not a node_history column
    assert "asset_url" not in params


def test_node_params_accepts_plain_string_status():
    assert pg.node_params("p", "n", "failed", {})["status"] == "failed"


def test_row_to_package_roundtrips_spec():
    pkg = _pkg()
    spec = pkg.model_dump(mode="json")
    rebuilt = pg.row_to_package(spec)
    assert rebuilt.project_id == pkg.project_id
    assert rebuilt.model_dump(mode="json") == spec


# --------------------------------------------------------------------------
# Opt-in integration (live Postgres; auto-skips when unavailable)
# --------------------------------------------------------------------------
@pytest.fixture
def pg_url(monkeypatch):
    url = os.environ.get("AFP_TEST_POSTGRES_URL", "postgresql://afp:afp@localhost:5432/afp")
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg not installed")
    try:
        psycopg.connect(url, connect_timeout=2).close()
    except Exception as exc:  # pragma: no cover - depends on local env
        pytest.skip(f"no postgres reachable at {url}: {exc}")
    monkeypatch.setenv("POSTGRES_URL", url)
    return url


def _run_async(coro) -> None:
    """Run the integration scenario on a SelectorEventLoop.

    psycopg's async path rejects Windows' default ProactorEventLoop. The Linux
    containers that actually run the services use a compatible loop, so this shim is
    a Windows-local-dev concern only, not a library issue."""
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()
    else:
        asyncio.run(coro)


async def _scalar(url: str, sql: str, params: dict) -> object:
    import psycopg

    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await conn.close()


async def _cleanup(url: str, project_id: str) -> None:
    import psycopg

    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        await conn.execute("DELETE FROM node_history WHERE project_id = %(p)s", {"p": project_id})
        await conn.execute("DELETE FROM packages WHERE project_id = %(p)s", {"p": project_id})
    finally:
        await conn.close()


def test_pg_roundtrip_and_cost_actuals_view(pg_url):
    project_id = f"p_pg_{uuid4().hex[:8]}"

    async def scenario():
        pkg = _pkg(project_id)
        await pg.write_package(pkg)
        fetched = await pg.fetch_package(project_id)
        assert fetched is not None
        assert fetched.model_dump(mode="json") == pkg.model_dump(mode="json")
        assert project_id in await pg.list_project_ids()

        await pg.write_node_status(
            project_id,
            "ref_a",
            NodeStatus.SUCCEEDED,
            {"actual_cost_usd": 0.04, "provider_url": "https://fal/ref_a"},
        )
        await pg.write_attempts(project_id, "ref_a", 3)
        cost = await _scalar(
            pg_url,
            "SELECT actual_cost_usd FROM cost_actuals WHERE project_id = %(p)s",
            {"p": project_id},
        )
        assert float(cost) == pytest.approx(0.04)
        await _cleanup(pg_url, project_id)

    _run_async(scenario())


def test_save_package_write_through_and_redis_miss_fallback(pg_url):
    if fakeredis_aio is None:
        pytest.skip("fakeredis not installed")
    project_id = f"p_fb_{uuid4().hex[:8]}"

    async def scenario():
        pkg = _pkg(project_id)
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        await state.save_package(pkg)  # mirrors into Postgres

        # simulate a Redis flush: swap in a fresh empty client
        state.use_client(fakeredis_aio.FakeRedis(decode_responses=True))
        got = await state.get_package(project_id)  # Redis miss -> Postgres fallback
        assert got is not None
        assert got.project_id == project_id

        # the History list is now backed by the durable packages table
        ids = [p.project_id async for p in state.iter_all_packages()]
        assert project_id in ids

        state.use_client(None)
        await _cleanup(pg_url, project_id)

    _run_async(scenario())
