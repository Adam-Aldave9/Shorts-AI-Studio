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
    "fetch_package_owner",
    "list_project_ids",
    "list_project_ids_for_owner",
    "write_node_status",
    "write_attempts",
    "insert_user",
    "fetch_user_by_username",
    "fetch_user_by_id",
    "update_user_password",
    "UserExistsError",
    "INIT_STATEMENTS",
]


class UserExistsError(Exception):
    """Raised when inserting a user whose (normalized) username already exists.

    Maps the Postgres unique-violation on ``users.username`` to a typed error the
    auth layer can translate into a 409, without leaking driver exceptions upward."""

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
    # Accounts (auth): ``username`` is the normalized (lowercased) form and is
    # UNIQUE for case-insensitive uniqueness; ``display_username`` keeps the exact
    # casing the user registered with. ``password_hash`` is an Argon2id hash — never
    # a plaintext or reversible value.
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id          TEXT PRIMARY KEY,
        username         TEXT NOT NULL UNIQUE,
        display_username TEXT NOT NULL,
        password_hash    TEXT NOT NULL,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Per-user ownership on the already-existing ``packages`` table. ADD COLUMN IF
    # NOT EXISTS is the migration here (no Alembic): ``CREATE TABLE IF NOT EXISTS``
    # alone never adds a column to a table that already exists. Legacy rows -> NULL
    # owner (unowned).
    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "CREATE INDEX IF NOT EXISTS packages_owner_idx ON packages (owner_id)",
]

_UPSERT_PACKAGE = """
INSERT INTO packages (project_id, title, schema_version, created_at, spec, approved, owner_id)
VALUES (%(project_id)s, %(title)s, %(schema_version)s, %(created_at)s, %(spec)s,
        COALESCE(%(approved)s, FALSE), %(owner_id)s)
ON CONFLICT (project_id) DO UPDATE SET
    title          = EXCLUDED.title,
    schema_version = EXCLUDED.schema_version,
    created_at     = EXCLUDED.created_at,
    spec           = EXCLUDED.spec,
    approved       = COALESCE(%(approved)s, packages.approved),
    -- COALESCE preserves the original owner across checkpoint edits (which pass
    -- owner_id=None), so a later save can never null out or reassign ownership.
    owner_id       = COALESCE(%(owner_id)s, packages.owner_id)
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
_SELECT_PROJECT_IDS_FOR_OWNER = (
    "SELECT project_id FROM packages WHERE owner_id = %(owner_id)s"
)
_SELECT_PACKAGE_OWNER = "SELECT owner_id FROM packages WHERE project_id = %(project_id)s"
_MARK_APPROVED = "UPDATE packages SET approved = TRUE WHERE project_id = %(project_id)s"

_INSERT_USER = """
INSERT INTO users (user_id, username, display_username, password_hash)
VALUES (%(user_id)s, %(username)s, %(display_username)s, %(password_hash)s)
"""
_SELECT_USER_BY_USERNAME = (
    "SELECT user_id, username, display_username, password_hash, created_at "
    "FROM users WHERE username = %(username)s"
)
_SELECT_USER_BY_ID = (
    "SELECT user_id, username, display_username, password_hash, created_at "
    "FROM users WHERE user_id = %(user_id)s"
)
_UPDATE_USER_PASSWORD = (
    "UPDATE users SET password_hash = %(password_hash)s WHERE user_id = %(user_id)s"
)


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


def package_params(
    package: ProductionPackage, approved: bool | None, owner_id: str | None = None
) -> dict[str, Any]:
    """Bind a package to the upsert: queryable columns + the full spec as JSON.

    ``spec`` is the JSON-mode dump (the replay source of truth); the caller wraps it
    in ``psycopg ... Jsonb`` before execution. ``approved=None`` preserves the stored
    flag, and ``owner_id=None`` preserves the stored owner (see the ``COALESCE``s in
    the upsert)."""
    return {
        "project_id": package.project_id,
        "title": package.meta.title,
        "schema_version": package.schema_version,
        "created_at": package.created_at,
        "spec": package.model_dump(mode="json"),
        "approved": approved,
        "owner_id": owner_id,
    }


def row_to_user(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map a ``users`` row (the SELECT column order above) to a plain dict — the
    shape the auth layer consumes. ``password_hash`` is included so ``authenticate``
    can verify it; callers must never surface it past the auth boundary."""
    return {
        "user_id": row[0],
        "username": row[1],
        "display_username": row[2],
        "password_hash": row[3],
        "created_at": row[4],
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


async def write_package(
    package: ProductionPackage, approved: bool | None = None, owner_id: str | None = None
) -> None:
    from psycopg.types.json import Jsonb

    params = package_params(package, approved, owner_id)
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


async def fetch_package_owner(project_id: str) -> str | None:
    """Return the durable ``owner_id`` for a package (NULL/None if unowned/legacy)."""
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_PACKAGE_OWNER, {"project_id": project_id})
        row = await cur.fetchone()
    finally:
        await conn.close()
    return row[0] if row else None


async def list_project_ids_for_owner(owner_id: str) -> list[str]:
    """Project ids owned by ``owner_id`` — the durable backing for scoped History."""
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_PROJECT_IDS_FOR_OWNER, {"owner_id": owner_id})
        rows = await cur.fetchall()
    finally:
        await conn.close()
    return [row[0] for row in rows]


# --------------------------------------------------------------------------
# Users (accounts / auth)
# --------------------------------------------------------------------------
async def insert_user(
    user_id: str, username: str, display_username: str, password_hash: str
) -> None:
    """Insert a new account. Raises :class:`UserExistsError` if the normalized
    ``username`` is already taken (Postgres unique-violation, translated here)."""
    import psycopg.errors

    try:
        await _execute(
            _INSERT_USER,
            {
                "user_id": user_id,
                "username": username,
                "display_username": display_username,
                "password_hash": password_hash,
            },
        )
    except psycopg.errors.UniqueViolation as exc:
        raise UserExistsError(username) from exc


async def fetch_user_by_username(username: str) -> dict[str, Any] | None:
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_USER_BY_USERNAME, {"username": username})
        row = await cur.fetchone()
    finally:
        await conn.close()
    return row_to_user(row) if row else None


async def fetch_user_by_id(user_id: str) -> dict[str, Any] | None:
    conn = await _connect()
    try:
        cur = await conn.execute(_SELECT_USER_BY_ID, {"user_id": user_id})
        row = await cur.fetchone()
    finally:
        await conn.close()
    return row_to_user(row) if row else None


async def update_user_password(user_id: str, password_hash: str) -> None:
    """Replace a user's stored hash (rehash-on-login / password change)."""
    await _execute(
        _UPDATE_USER_PASSWORD, {"user_id": user_id, "password_hash": password_hash}
    )
