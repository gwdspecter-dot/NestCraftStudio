"""Публичный CRUD CatalogService (план §2.6)."""

from pathlib import Path
import tempfile
from core.catalog.catalog_service import CatalogService
from core.catalog.models import Material


def test_insert_update_delete_material_public_api():
    CatalogService.reset()
    tmp = Path(tempfile.mkdtemp()) / "cat.db"
    cat = CatalogService.instance(tmp)

    mid = "mat_test_api_xyz"
    m = Material(
        id=mid,
        sku="TEST-API",
        name="Test API Mat",
        category_id="cat_ldsp",
        material_type="ldsp",
        thickness_mm=16.0,
        is_builtin=False,
        is_active=True,
    )
    # category may not exist in empty - seed_if_empty should have cats
    try:
        cat.insert_material(m)
    except Exception:
        # ensure categories exist via seed
        from core.catalog.seed import seed_if_empty
        seed_if_empty(cat._conn)
        cat.insert_material(m)

    got = cat.get_material(mid)
    assert got is not None
    assert got.name == "Test API Mat"
    assert mid in cat._mat_cache

    m.name = "Renamed"
    cat.update_material(m)
    assert cat.get_material(mid).name == "Renamed"

    assert cat.delete_material(mid)
    assert cat.get_material(mid) is None
    CatalogService.reset()


def test_edge_cache_always_present():
    CatalogService.reset()
    tmp = Path(tempfile.mkdtemp()) / "cat2.db"
    cat = CatalogService.instance(tmp)
    assert hasattr(cat, "_edge_cache")
    assert isinstance(cat._edge_cache, dict)
    CatalogService.reset()
