"""
Каталог материалов и крепежа NestCraft.

Использование:
    from core.catalog import CatalogService

    catalog = CatalogService.instance()
    mat = catalog.get_material("mat_mist_vl_16")
    conf = catalog.default_fastener("confirmat")
"""

from core.catalog.catalog_service import CatalogService
from core.catalog.models import (
    Material,
    EdgeBand,
    Fastener,
    FastenerType,
    MaterialCategory,
    CatalogGroup,
    Supplier,
)

__all__ = [
    "CatalogService",
    "Material",
    "EdgeBand",
    "Fastener",
    "FastenerType",
    "MaterialCategory",
    "CatalogGroup",
    "Supplier",
]
