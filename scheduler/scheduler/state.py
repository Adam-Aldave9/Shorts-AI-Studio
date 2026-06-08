"""Persistence seam for the scheduler (spec §6.7).

Durable package + node history live in Postgres; live node status lives in Redis.
v1 stub: an in-memory store so the API and daemon are runnable before the DB
layer lands in Week 2/3.
"""

from __future__ import annotations

from typing import AsyncIterator

from schema import ProductionPackage

# project_id -> (package, approved)
_STORE: dict[str, tuple[ProductionPackage, bool]] = {}


async def save_package(package: ProductionPackage, *, approved: bool | None = None) -> None:
    existing_approved = _STORE.get(package.project_id, (None, False))[1]
    _STORE[package.project_id] = (
        package,
        existing_approved if approved is None else approved,
    )


async def get_package(project_id: str) -> ProductionPackage | None:
    entry = _STORE.get(project_id)
    return entry[0] if entry else None


async def approve_package(project_id: str) -> bool:
    entry = _STORE.get(project_id)
    if not entry:
        return False
    _STORE[project_id] = (entry[0], True)
    return True


async def iter_approved_packages() -> AsyncIterator[ProductionPackage]:
    for package, approved in list(_STORE.values()):
        if approved:
            yield package
