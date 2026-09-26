"""Film and version of a package; packages written before schema 1.2 are v1 of their own film."""

from __future__ import annotations

from schema.models import ProductionPackage


def film_id_of(package: ProductionPackage) -> str:
    return package.lineage.film_id if package.lineage else package.project_id


def version_of(package: ProductionPackage) -> int:
    return package.lineage.version if package.lineage else 1
