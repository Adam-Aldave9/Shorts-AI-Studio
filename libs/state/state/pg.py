"""Postgres durability layer for run-state (spec §6.7) - the system of record.

Additive behind :mod:`state.store`: Redis stays the hot read/write path; this
module mirrors every write into Postgres and serves reads on a Redis miss, so the
History list and per-run records survive a Redis flush (durability / replay).

The split mirrors the worker / compositor / planning agents: the SQL-building and
row-mapping helpers are **pure** (no ``psycopg``, unit-tested offline); the thin
connection wrappers import ``psycopg`` lazily and are exercised by the opt-in
integration test and the compose e2e. ``psycopg`` is only touched when
``POSTGRES_URL`` is set, so the Redis-only dev/test path never needs it installed.

Tables (created idempotently on first connection in each process - no Alembic)
-----------------------------------------------------------------------------
``packages``      one row per project: the durable History source + replay spec.
``node_history``  one row per (project, node): latest status / cost / provider / error.
``cost_actuals``  view: actual spend per project, summed from ``node_history``.
"""

from __future__ import annotations

import os
from typing import Any

from schema import ProductionPackage

__all__ = [
    "enabled",
    "package_params",
    "node_params",
    "row_to_package",
    "write_package",
    "mark_approved",
    "fetch_package",
    "list_project_ids",
    "write_node_status",
    "write_attempts",
    "INIT_STATEMENTS",
]

# --------------------------------------------------------------------------
# DDL + statements (constants -> pure / unit-inspectable)
# --------------------------------------------------------------------------
# A single idempotent ``CREATE ... IF NOT EXISTS`` per startup is enough for v1.
# Kept as separate statements: psycopg executes one command per ``execute`` call.
INIT_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS packages (
        project_id     TEXT PRIMARY KEY,
        title          TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        created_at     TIMESTAMPTZ NOT NULL,
        spec           JSONB NOT NULL,
        approved       BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS node_history (
        project_id      TEXT NOT NULL,
        node_id         TEXT NOT NULL,
        status          TEXT,
        actual_cost_usd DOUBLE PRECISION,
        provider_url    TEXT,
        attempts        INTEGER,
        error           TEXT,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, node_id)
    )
    """,
    """
    CREATE OR REPLACE VIEW cost_actuals AS
        SELECT project_id, COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd
        FROM node_history
        GROUP BY project_id
    """,
]

_UPSERT_PACKAGE = """
INSERT INTO packages (project_id, title, schema_version, created_at, spec, approved)
VALUES (%(project_id)s, %(title)s, %(schema_version)s, %(created_at)s, %(spec)s,
        COALESCE(%(approved)s, FALSE))
ON CONFLICT (project_id) DO UPDATE SET
    title          = EXCLUDED.title,
    schema_version = EXCLUDED.schema_version,
    created_at     = EXCLUDED.created_at,
    spec           = EXCLUDED.spec,
    approved       = COALESCE(%(approved)s, packages.approved)
"""

# COALESCE on update so a later partial write (e.g. status only) does not clobber
# a provider_url / cost recorded by an earlier one.
_UPSERT_NODE = """
INSERT INTO node_history (project_id, node_id, status, actual_cost_usd, provider_url, error, updated_at)
VALUES (%(project_id)s, %(node_id)s, %(status)s, %(actual_cost_usd)s, %(provider_url)s, %(error)s, now())
ON CONFLICT (project_id, node_id) DO UPDATE SET
    status          = COALESCE(EXCLUDED.status, node_history.status),
    actual_cost_usd = COALESCE(EXCLUDED.actual_cost_usd, node_history.actual_cost_usd),
    provider_url    = COALESCE(EXCLUDED.provider_url, node_history.provider_url),
    error           = COALESCE(EXCLUDED.error, node_history.error),
    updated_at      = now()
"""

_UPSERT_ATTEMPTS = """
INSERT INTO node_history (project_id, node_id, attempts, updated_at)
VALUES (%(project_id)s, %(node_id)s, %(attempts)s, now())
ON CONFLICT (project_id, node_id) DO UPDATE SET
    attempts   = EXCLUDED.attempts,
    updated_at = now()
"""

_SELECT_PACKAGE = "SELECT spec FROM packages WHERE project_id = %(project_id)s"
_SELECT_PROJECT_IDS = "SELECT project_id FROM packages"
_MARK_APPROVED = "UPDATE packages SET approved = TRUE WHERE project_id = %(project_id)s"


# --------------------------------------------------------------------------
# Pure helpers (no I/O - unit-tested offline)
# --------------------------------------------------------------------------
def enabled() -> bool:
    """Postgres write-through is active only when ``POSTGRES_URL`` is configured."""
    return bool(os.environ.get("POSTGRES_URL"))


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def package_params(package: ProductionPackage, approved: bool | None) -> dict[str, Any]:
    """Bind a package to the upsert: queryable columns + the full spec as JSON.

    ``spec`` is the JSON-mode dump (the replay source of truth); the caller wraps it
    in ``psycopg ... Jsonb`` before execution. ``approved=None`` preserves the stored
    flag (see the ``COALESCE`` in the upsert)."""
    return {
        "project_id": package.project_id,
        "title": package.meta.title,
        "schema_version": package.schema_version,
        "created_at": package.created_at,
        "spec": package.model_dump(mode="json"),
        "approved": approved,
    }


def node_params(project_id: str, node_id: str, status: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Bind one node-status write. ``asset_url`` (a ``fields`` key) is intentionally
    not a ``node_history`` column, so it is ignored here."""
    return {
        "project_id": project_id,
        "node_id": node_id,
        "status": _status_value(status),
        "actual_cost_usd": _as_float(fields.get("actual_cost_usd")),
        "provider_url": fields.get("provider_url"),
        "error": fields.get("error"),
    }


def row_to_package(spec: dict[str, Any]) -> ProductionPackage:
    """Rebuild a package from its stored ``spec`` JSONB (the replay path)."""
    return ProductionPackage.model_validate(spec)


# --------------------------------------------------------------------------
# Thin connection wrappers (lazy psycopg - integration / e2e only)
# --------------------------------------------------------------------------
# Conninfo strings already initialized in this process, so the idempotent CREATEs
# run once per process, not on every connection.
_initialized: set[str] = set()


async def _connect():  # type: ignore[no-untyped-def]
    import psycopg  # lazy: only needed when POSTGRES_URL is set

    url = os.environ["POSTGRES_URL"]
    conn = await psycopg.AsyncConnection.connect(url, autocommit=True, connect_timeout=5)
    if url not in _initialized:
        for statement in INIT_STATEMENTS:
            await conn.execute(statement)
        _initialized.add(url)
    return conn


async def _execute(sql: str, params: dict[str, Any]) -> None:
    conn = await _connect()
    try:
        await conn.execute(sql, params)
    finally:
        await conn.close()


async def write_package(package: ProductionPackage, approved: bool | None = None) -> None:
    from psycopg.types.json import Jsonb

    params = package_params(package, approved)
    params["spec"] = Jsonb(params["spec"])
    await _execute(_UPSERT_PACKAGE, params)


async def mark_approved(project_id: str) -> None:
    await _execute(_MARK_APPROVED, {"project_id": project_id})


async def write_node_status(project_id: str, node_id: str, status: Any, fields: dict[str, Any]) -> None:
    await _execute(_UPSERT_NODE, node_params(project_id, node_id, status, fields))


async def write_attempts(project_id: str, node_id: str, attempts: int) -> None:
    await _execute(
        _UPSERT_ATTEMPTS, {"project_id": project_id, "node_id": node_id, "attempts": attempts}
    )


async def fetch_package(project_id: str) -> ProductionPackage | None:
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_PACKAGE, {"project_id": project_id})
        row = await cur.fetchone()
    finally:
        await conn.close()
    return row_to_package(row[0]) if row else None


async def list_project_ids() -> list[str]:
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_PROJECT_IDS)
        rows = await cur.fetchall()
    finally:
        await conn.close()
    return [row[0] for row in rows]
