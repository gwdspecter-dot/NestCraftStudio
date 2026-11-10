"""Тесты разделения модели Panel и сервисов через SceneController (ревизия 2, п. 2.1)."""

from __future__ import annotations

import ast
import dataclasses
import tempfile
from pathlib import Path

import tests.conftest  # noqa: F401
from models.panel import Panel, Block
from core.scene_controller import SceneController


def test_panel_is_pure_dataclass_without_service_imports():
    """План §2.1: Panel является @dataclass, а models/panel.py не импортирует CatalogService, GeometryService или CADKernel."""
    assert dataclasses.is_dataclass(Panel), "Panel must be a @dataclass"
    field_names = {f.name for f in dataclasses.fields(Panel)}
    for required in ("name", "x", "y", "z", "width", "height", "depth", "uid", "material_id", "edges"):
        assert required in field_names, f"Missing dataclass field {required!r}"

    panel_src_path = Path(__file__).resolve().parents[1] / "models" / "panel.py"
    tree = ast.parse(panel_src_path.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = {"core.catalog", "core.geometry_service", "core.cad_kernel"}
    overlap = imported_modules & forbidden
    assert not overlap, f"models/panel.py must not import services directly, found: {overlap}"


def test_panel_works_standalone_when_controller_unbound():
    """План §2.1: без SceneController экземпляр Panel работает как чистая структура данных."""
    SceneController.unbind_from_panel_class()
    try:
        p = Panel("Чистая деталь", 10, 20, 30, 600, 400, 16, rebuild=True)
        assert p.name == "Чистая деталь"
        assert p.thickness_axis == 2
        assert p.get_thickness() == 16.0
        assert p.geometry_generation == 1

        # Локальное назначение кромки с явно переданной толщиной без каталога
        p.set_edge("top", "edge_custom_2", thickness_mm=2.0)
        p.set_edge("bottom", "edge_custom_2", thickness_mm=2.0)
        assert p.get_edge_thickness("top") == 2.0
        sx, sy, sz = p.get_saw_dimensions()
        assert abs(sx - 600.0) < 1e-6
        assert abs(sy - (400.0 - 4.0)) < 1e-6
        assert abs(sz - 16.0) < 1e-6
    finally:
        SceneController.instance().bind_to_panel_class()


def test_scene_controller_manages_materials_edges_and_geometry():
    """План §2.1: материалы, кромки и пересборка геометрии идут через SceneController."""
    from core.catalog import CatalogService
    from core.geometry_service import GeometryService

    with tempfile.TemporaryDirectory() as td:
        CatalogService.reset()
        cat = CatalogService.instance(Path(td) / "catalog.db")
        geom = GeometryService.instance()
        ctrl = SceneController(catalog_service=cat, geometry_service=geom)
        ctrl.bind_to_panel_class()
        try:
            p = Panel("Боковина", 0, 0, 0, 16, 720, 560, rebuild=False)
            assert p.thickness_axis == 0

            # Назначаем 18-мм материал через SceneController -> ширина по оси X должна стать 18 мм
            mats = cat.list_materials()
            mat_18 = next((m for m in mats if abs(float(m.thickness_mm) - 18.0) < 1e-3), None)
            if mat_18 is not None:
                assert ctrl.apply_material(p, mat_18.id, rebuild=True) is True
                assert p.material_id == mat_18.id
                assert abs(p.width - 18.0) < 1e-6
                assert p.geometry_generation >= 1
                assert p.mesh_data is not None

            # Назначаем существующую и несуществующую кромки через SceneController
            edges = cat.list_edge_bands()
            assert edges, "Seed catalog must contain edge bands"
            e0 = edges[0]
            assert ctrl.set_edge(p, "left", e0.id) is True
            assert abs(ctrl.get_edge_thickness(p, "left") - float(e0.thickness_mm)) < 1e-6
            assert "left" not in p.missing_edges

            assert ctrl.set_edge(p, "right", "nonexistent_edge_id") is True
            assert p.missing_edges.get("right") == "nonexistent_edge_id"

            # Пересборка блока через SceneController
            b = Block("Тестовый блок")
            b.add_panel(p)
            gen_before = p.geometry_generation
            ctrl.rebuild_block_geometry(b, sync=True)
            assert p.geometry_generation == gen_before + 1
        finally:
            CatalogService.reset()
            SceneController.reset()
            SceneController.instance()


def test_conftest_does_not_replace_service_modules_in_sys_modules():
    """План §2.1: conftest не подменяет core.geometry_service и core.cad_kernel фейковыми модулями в sys.modules."""
    import core.cad_kernel as ck
    import core.geometry_service as gs

    assert getattr(ck, "__file__", None), "core.cad_kernel must be the real module, not a sys.modules stub"
    assert getattr(gs, "__file__", None), "core.geometry_service must be the real module, not a sys.modules stub"


def test_parametric_cabinet_auto_resolves_controller_and_builds_mesh():
    """Регрессия: при создании Panel / ParametricCabinet без предварительного импорта SceneController геометрия (mesh_data) гарантированно строится."""
    from models.panel import ParametricCabinet

    SceneController.reset()
    assert Panel._scene_controller is None
    assert Panel._controller_unbound is False

    cab = ParametricCabinet("Тумба 600", 0, 100, 0, 600, 720, 560, shelves_count=1, has_facade=True)
    assert Panel._scene_controller is not None
    assert len(cab.panels) >= 6
    for p in cab.panels:
        assert p.mesh_data is not None, f"mesh_data missing for {p.name}"
        verts, tris, normals = p.mesh_data
        assert len(verts) >= 24 and len(tris) >= 12 and len(normals) == len(verts)


if __name__ == "__main__":
    test_panel_is_pure_dataclass_without_service_imports()
    test_panel_works_standalone_when_controller_unbound()
    test_scene_controller_manages_materials_edges_and_geometry()
    test_conftest_does_not_replace_service_modules_in_sys_modules()
    test_parametric_cabinet_auto_resolves_controller_and_builds_mesh()
    print("ALL 2.1 SCENE CONTROLLER TESTS PASSED")
