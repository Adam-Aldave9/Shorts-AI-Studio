"""Reuse of identical renders across the versions of one film, seeded at approve."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from schema import (
    AssetType,
    NodeStatus,
    ProductionPackage,
    film_id_of,
    fingerprints,
    version_of,
)

from scheduler.state import get_node, iter_user_packages

# adapters/mock.py placeholders and harness seed-mock both live under this prefix.
MOCK_ASSET_MARKER = "/_mock/"


def mock_enabled() -> bool:
    return os.environ.get("MOCK", "false").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class ReuseSource:
    project_id: str
    node_id: str
    version: int
    asset_url: str
    provider_url: str


async def reuse_sources(spec: ProductionPackage, owner_id: str | None) -> dict[str, ReuseSource]:
    """fingerprint -> the best succeeded render of it in another version of this film."""
    film_id = film_id_of(spec)
    if film_id == spec.project_id or not owner_id:
        return {}
    mock = mock_enabled()
    parent_id = spec.lineage.parent_project_id if spec.lineage else None
    best: dict[str, tuple[tuple[bool, int], ReuseSource]] = {}
    async for other in iter_user_packages(owner_id):
        if other.project_id == spec.project_id or film_id_of(other) != film_id:
            continue
        prints: dict[str, str] | None = None
        rank = (other.project_id == parent_id, version_of(other))
        for asset in other.assets:
            if asset.status is not NodeStatus.SUCCEEDED or not asset.asset_url:
                continue
            if not mock and MOCK_ASSET_MARKER in asset.asset_url:
                continue
            provider_url = (await get_node(other.project_id, asset.node_id)).get("provider_url") or ""
            # fal fetches a start frame over the internet, so a real image source needs one.
            if not mock and asset.type is AssetType.IMAGE and not provider_url.startswith("http"):
                continue
            prints = prints or fingerprints(other)
            fingerprint = prints[asset.node_id]
            if fingerprint in best and best[fingerprint][0] >= rank:
                continue
            best[fingerprint] = (
                rank,
                ReuseSource(
                    project_id=other.project_id,
                    node_id=asset.node_id,
                    version=version_of(other),
                    asset_url=asset.asset_url,
                    provider_url=provider_url,
                ),
            )
    return {fingerprint: source for fingerprint, (_, source) in best.items()}


def match(spec: ProductionPackage, sources: dict[str, ReuseSource]) -> dict[str, ReuseSource]:
    if not sources:
        return {}
    return {
        node_id: sources[fingerprint]
        for node_id, fingerprint in fingerprints(spec).items()
        if fingerprint in sources
    }


def seed_fields(source: ReuseSource) -> dict[str, str]:
    fields = {
        "status": NodeStatus.SUCCEEDED.value,
        "asset_url": source.asset_url,
        "actual_cost_usd": "0",
        "reused_from": f"{source.project_id}/{source.node_id}",
    }
    if source.provider_url:
        fields["provider_url"] = source.provider_url
    return fields


def seeder(
    owner_id: str | None,
) -> Callable[[ProductionPackage], Awaitable[dict[str, dict[str, str]]]]:
    async def seed(spec: ProductionPackage) -> dict[str, dict[str, str]]:
        matched = match(spec, await reuse_sources(spec, owner_id))
        return {node_id: seed_fields(source) for node_id, source in matched.items()}

    return seed
