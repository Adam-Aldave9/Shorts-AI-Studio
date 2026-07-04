"""Shared run-state over Redis (spec §6.7).

Three isolated processes — the DAG-walker daemon, the worker fleet, and the
compositor — read and write one shared view of a run. This module is that
seam, mirroring the extraction of ``libs/storage``: an async API backed by
``redis.asyncio`` that all of them import.

Key layout
----------
``pkg:{project_id}``                 the package spec JSON (``model_dump_json``).
``projects:all``                     set of every persisted ``project_id`` (History list).
``projects:approved``                set of approved ``project_id``s.
``node:{project_id}:{node_id}``      hash of *live, mutable* run state — ``status``,
                                     ``asset_url``, ``provider_url``,
                                     ``actual_cost_usd``, ``attempts``, ``error``.
``cost:{project_id}``                float owned by ``CostTracker`` (rate-limiter lib).
``project:{project_id}:phase``       ``executing|compositing|complete|blocked|paused``.
``project:{project_id}:final_url``   final MP4 URL.

``provider_url`` is kept distinct from the MinIO ``asset_url``: it is the upstream
provider (fal http) URL, and is load-bearing for i2v ``image_url`` threading in real
mode — fal fetches the reference image over the public internet, not the local copy.

Redis is the hot path. When ``POSTGRES_URL`` is set, every write is also mirrored
into Postgres (the durable system of record, :mod:`state.pg`) on a best-effort basis
— a Postgres failure logs but never breaks the run — and reads fall back to Postgres
on a Redis miss. With no ``POSTGRES_URL`` this is Redis-only, exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, AsyncIterator, Callable

import redis.asyncio as redis

from schema import NodeStatus, ProductionPackage

from state import pg
from state.pg import UserExistsError  # re-exported for the auth layer

log = logging.getLogger(__name__)

# -- project phases (string-valued; constants keep the daemon/compositor honest) --
PHASE_EXECUTING = "executing"
PHASE_COMPOSITING = "compositing"
PHASE_COMPLETE = "complete"
PHASE_BLOCKED = "blocked"
PHASE_PAUSED = "paused"

__all__ = [
    "PHASE_EXECUTING",
    "PHASE_COMPOSITING",
    "PHASE_COMPLETE",
    "PHASE_BLOCKED",
    "PHASE_PAUSED",
    "use_client",
    "save_package",
    "get_package",
    "approve_package",
    "iter_approved_packages",
    "iter_all_packages",
    "iter_user_packages",
    "get_project_owner",
    "create_user",
    "get_user_by_username",
    "get_user_by_id",
    "set_user_password_hash",
    "UserExistsError",
    "set_node_status",
    "get_node",
    "increment_attempts",
    "get_dep_provider_urls",
    "get_project_phase",
    "set_project_phase",
    "set_final_url",
    "get_final_url",
    "get_cost",
]


# --------------------------------------------------------------------------
# Client management
# --------------------------------------------------------------------------
# A ``redis.asyncio`` client's connection pool binds to the loop running when it
# first issues a command. The scheduler has one long-lived loop, but the worker runs
# each Celery task in its own ``asyncio.run`` — a fresh loop per task. So we cache one
# client per running loop (pruning closed ones), not a single global that would raise
# "attached to a different loop" on the worker's second task. ``use_client`` is for tests.
_override: redis.Redis | None = None
_clients: dict[asyncio.AbstractEventLoop, redis.Redis] = {}


def use_client(client: redis.Redis | None) -> None:
    """Inject a Redis client (tests / fakeredis). Pass ``None`` to reset."""
    global _override
    _override = client


# --------------------------------------------------------------------------
# Postgres write-through (best-effort, additive behind this interface)
# --------------------------------------------------------------------------
async def _mirror(write: Callable[[], Awaitable[None]], what: str) -> None:
    """Mirror a write into Postgres when configured. The durability layer must
    never break the Redis hot path, so any failure is logged and swallowed."""
    if not pg.enabled():
        return
    try:
        await write()
    except Exception:  # noqa: BLE001 - durability is additive; the run goes on
        log.warning("postgres write-through failed (%s)", what, exc_info=True)


async def _fallback_package(project_id: str) -> ProductionPackage | None:
    """Serve a package from Postgres on a Redis miss (durability / replay)."""
    if not pg.enabled():
        return None
    try:
        return await pg.fetch_package(project_id)
    except Exception:  # noqa: BLE001
        log.warning("postgres read-fallback failed for %s", project_id, exc_info=True)
        return None


async def _all_project_ids() -> list[str]:
    """Project ids for the History list: the durable ``packages`` table when
    Postgres is configured (survives a Redis flush), else the Redis index."""
    if pg.enabled():
        try:
            return await pg.list_project_ids()
        except Exception:  # noqa: BLE001
            log.warning("postgres list failed; falling back to redis index", exc_info=True)
    return list(await _redis().smembers("projects:all"))


def _redis() -> redis.Redis:
    if _override is not None:
        return _override
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        for dead in [lp for lp in _clients if lp.is_closed()]:
            _clients.pop(dead, None)
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        client = redis.from_url(url, decode_responses=True)
        _clients[loop] = client
    return client


# --------------------------------------------------------------------------
# Packages
# --------------------------------------------------------------------------
async def save_package(
    package: ProductionPackage, *, approved: bool | None = None, owner_id: str | None = None
) -> None:
    """Persist the package spec and register it in the ``projects:all`` index (the
    History list, spec §9.2). ``approved`` only touches the approved set when set.

    ``owner_id`` is passed on the create path (brief->package / ``POST /packages``)
    and stamps ownership: ``project:{id}:owner`` plus membership in the owner's
    ``user:{uid}:projects`` set (scoped History). Checkpoint edits pass
    ``owner_id=None``, and both Redis and the Postgres upsert preserve the existing
    owner, so an edit can never reassign or drop ownership."""
    r = _redis()
    await r.set(f"pkg:{package.project_id}", package.model_dump_json())
    await r.sadd("projects:all", package.project_id)
    if owner_id is not None:
        await r.set(f"project:{package.project_id}:owner", owner_id)
        await r.sadd(f"user:{owner_id}:projects", package.project_id)
    if approved is True:
        await r.sadd("projects:approved", package.project_id)
    elif approved is False:
        await r.srem("projects:approved", package.project_id)
    await _mirror(lambda: pg.write_package(package, approved, owner_id), "save_package")


async def get_package(project_id: str) -> ProductionPackage | None:
    """Load the spec, then overlay each asset's live node hash so callers see the
    current run view (status / asset_url / actual cost), not the frozen spec."""
    r = _redis()
    raw = await r.get(f"pkg:{project_id}")
    if not raw:
        return await _fallback_package(project_id)
    package = ProductionPackage.model_validate_json(raw)
    for asset in package.assets:
        node = await r.hgetall(f"node:{project_id}:{asset.node_id}")
        if not node:
            continue
        if node.get("status"):
            asset.status = NodeStatus(node["status"])
        if node.get("asset_url"):
            asset.asset_url = node["asset_url"]
        if node.get("actual_cost_usd"):
            asset.actual_cost_usd = float(node["actual_cost_usd"])
    return package


async def approve_package(project_id: str) -> bool:
    """Mark an existing package approved (idempotent). False if it doesn't exist."""
    r = _redis()
    if not await r.exists(f"pkg:{project_id}"):
        return False
    await r.sadd("projects:approved", project_id)
    await _mirror(lambda: pg.mark_approved(project_id), "approve_package")
    return True


async def iter_approved_packages() -> AsyncIterator[ProductionPackage]:
    for project_id in await _redis().smembers("projects:approved"):
        package = await get_package(project_id)
        if package is not None:
            yield package


async def iter_all_packages() -> AsyncIterator[ProductionPackage]:
    """Yield every persisted package — the History list (spec §9.2). Backed by the
    durable ``packages`` table when Postgres is configured (so it survives a Redis
    flush), else by the ``projects:all`` index ``save_package`` maintains."""
    for project_id in await _all_project_ids():
        package = await get_package(project_id)
        if package is not None:
            yield package


async def _user_project_ids(user_id: str) -> list[str]:
    """Project ids owned by ``user_id`` — the durable ``packages.owner_id`` index
    when Postgres is configured (survives a Redis flush), else the Redis
    ``user:{uid}:projects`` set ``save_package`` maintains."""
    if pg.enabled():
        try:
            return await pg.list_project_ids_for_owner(user_id)
        except Exception:  # noqa: BLE001
            log.warning("postgres owner-list failed; falling back to redis", exc_info=True)
    return list(await _redis().smembers(f"user:{user_id}:projects"))


async def iter_user_packages(user_id: str) -> AsyncIterator[ProductionPackage]:
    """Yield every package owned by ``user_id`` — the per-user scoped History list."""
    for project_id in await _user_project_ids(user_id):
        package = await get_package(project_id)
        if package is not None:
            yield package


async def get_project_owner(project_id: str) -> str | None:
    """Return the owning ``user_id`` for a package (``None`` if unowned/legacy).

    Reads the Redis ``project:{id}:owner`` key; on a miss (e.g. after a Redis flush)
    falls back to the durable ``packages.owner_id`` column so ownership checks stay
    correct across the durability boundary."""
    owner = await _redis().get(f"project:{project_id}:owner")
    if owner:
        return owner
    if pg.enabled():
        try:
            return await pg.fetch_package_owner(project_id)
        except Exception:  # noqa: BLE001
            log.warning("postgres owner-fetch failed for %s", project_id, exc_info=True)
    return None


# --------------------------------------------------------------------------
# Users (accounts / auth)
# --------------------------------------------------------------------------
# Postgres is the durable system of record for accounts when configured (the auth
# layer requires it in production); the Redis-only branch keeps registration/login
# working in dev/test (fakeredis) exactly as the package path degrades. Uniqueness is
# enforced by the Postgres UNIQUE constraint (``UserExistsError``) or, on the Redis
# branch, an atomic ``SET ... NX`` on the username index key.
#
# Keys (Redis branch):
#   ``user:name:{username}`` -> user_id   (uniqueness index + username lookup)
#   ``user:id:{user_id}``    -> hash(user_id, username, display_username,
#                                    password_hash, created_at)
def _user_hash(
    user_id: str, username: str, display_username: str, password_hash: str, created_at: str
) -> dict[str, str]:
    return {
        "user_id": user_id,
        "username": username,
        "display_username": display_username,
        "password_hash": password_hash,
        "created_at": created_at,
    }


async def create_user(
    user_id: str,
    username: str,
    display_username: str,
    password_hash: str,
    created_at: str,
) -> None:
    """Persist a new account. Raises :class:`UserExistsError` if ``username`` (already
    normalized/lowercased by the caller) is taken."""
    if pg.enabled():
        # Postgres is the source of truth: its UNIQUE constraint is the authority on
        # duplicates, so the error must propagate (not be swallowed like a mirror).
        await pg.insert_user(user_id, username, display_username, password_hash)
        return
    r = _redis()
    if not await r.set(f"user:name:{username}", user_id, nx=True):
        raise UserExistsError(username)
    await r.hset(
        f"user:id:{user_id}",
        mapping=_user_hash(user_id, username, display_username, password_hash, created_at),
    )


async def get_user_by_username(username: str) -> dict[str, str] | None:
    """Look up an account by its normalized username. Includes ``password_hash`` for
    the authenticator; callers must never surface it past the auth boundary."""
    if pg.enabled():
        row = await pg.fetch_user_by_username(username)
        return {k: str(v) for k, v in row.items()} if row else None
    user_id = await _redis().get(f"user:name:{username}")
    if not user_id:
        return None
    return await get_user_by_id(user_id)


async def get_user_by_id(user_id: str) -> dict[str, str] | None:
    if pg.enabled():
        row = await pg.fetch_user_by_id(user_id)
        return {k: str(v) for k, v in row.items()} if row else None
    data = await _redis().hgetall(f"user:id:{user_id}")
    return data or None


async def set_user_password_hash(user_id: str, password_hash: str) -> None:
    """Update a user's stored password hash (rehash-on-login / password change)."""
    if pg.enabled():
        await pg.update_user_password(user_id, password_hash)
        return
    await _redis().hset(f"user:id:{user_id}", "password_hash", password_hash)


# --------------------------------------------------------------------------
# Live node state
# --------------------------------------------------------------------------
async def set_node_status(
    project_id: str,
    node_id: str,
    status: NodeStatus | str,
    **fields: object,
) -> None:
    """Write a node's status (+ any of asset_url/provider_url/actual_cost_usd/error).

    Only the supplied fields are touched, so ``attempts`` and prior writes survive.
    """
    mapping: dict[str, str] = {
        "status": status.value if isinstance(status, NodeStatus) else str(status)
    }
    for key, value in fields.items():
        if value is not None:
            mapping[key] = value if isinstance(value, str) else str(value)
    await _redis().hset(f"node:{project_id}:{node_id}", mapping=mapping)
    await _mirror(
        lambda: pg.write_node_status(project_id, node_id, status, fields), "set_node_status"
    )


async def get_node(project_id: str, node_id: str) -> dict[str, str]:
    """Return the raw live node hash (empty dict if the node has never been written)."""
    return await _redis().hgetall(f"node:{project_id}:{node_id}")


async def increment_attempts(project_id: str, node_id: str) -> int:
    """Bump and return the node's attempt counter (one per try, for SSE/observability)."""
    count = await _redis().hincrby(f"node:{project_id}:{node_id}", "attempts", 1)
    await _mirror(lambda: pg.write_attempts(project_id, node_id, count), "increment_attempts")
    return count


async def get_dep_provider_urls(project_id: str, dep_ids: list[str]) -> dict[str, str]:
    """Map each dependency node_id to its upstream provider URL, where one exists.

    Feeds i2v ``image_url`` threading: a video node's reference image is fetched by
    fal from the public provider URL, not the local MinIO copy.
    """
    r = _redis()
    out: dict[str, str] = {}
    for dep_id in dep_ids:
        provider_url = await r.hget(f"node:{project_id}:{dep_id}", "provider_url")
        if provider_url:
            out[dep_id] = provider_url
    return out


# --------------------------------------------------------------------------
# Project phase + final cut
# --------------------------------------------------------------------------
async def get_project_phase(project_id: str) -> str | None:
    return await _redis().get(f"project:{project_id}:phase")


async def set_project_phase(project_id: str, phase: str) -> None:
    await _redis().set(f"project:{project_id}:phase", phase)


async def set_final_url(project_id: str, url: str) -> None:
    await _redis().set(f"project:{project_id}:final_url", url)


async def get_final_url(project_id: str) -> str | None:
    return await _redis().get(f"project:{project_id}:final_url")


async def get_cost(project_id: str) -> float:
    """Cumulative spend-to-date for the run (the ``cost:{project_id}`` key owned by
    ``CostTracker``). Read-only view for the SSE observability surface (spec §12.4)."""
    raw = await _redis().get(f"cost:{project_id}")
    return float(raw) if raw else 0.0
