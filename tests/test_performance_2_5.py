"""Тесты оптимизаций производительности п. 2.5 (меш, батчинг линий, коллизии, _scene_gpu_ids)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests.conftest  # noqa: F401
import pytest

from models.panel import Panel, Block
from core.cad_kernel import CADKernel


class _FakeVector:
    def __init__(self, x: float, y: float, z: float):
        self._t = (float(x), float(y), float(z))

    def toTuple(self):
        return self._t


class _FakeSolid:
    """Минимальный стаб solid с методом tessellate() для проверки векторизации get_render_mesh."""

    def tessellate(self, tolerance: float):
        verts = [
            _FakeVector(0, 0, 0),
            _FakeVector(10, 0, 0),
            _FakeVector(0, 10, 0),
            _FakeVector(0, 0, 10),
        ]
        tris = [
            (0, 1, 2),
            (0, 2, 3),
        ]
        return verts, tris


def test_get_render_mesh_vectorized_shapes_and_normals():
    solid = _FakeSolid()
    V, T, N = CADKernel.get_render_mesh(solid)
    assert len(V) == 6
    assert len(T) == 2
    assert len(N) == 6
    # Первый треугольник в плоскости XY -> нормаль (0, 0, 1)
    for k in range(3):
        assert abs(float(N[k][0])) < 1e-5
        assert abs(float(N[k][1])) < 1e-5
        assert abs(float(N[k][2]) - 1.0) < 1e-5
    # Второй треугольник в плоскости YZ -> нормаль (1, 0, 0)
    for k in range(3, 6):
        assert abs(float(N[k][0]) - 1.0) < 1e-5
        assert abs(float(N[k][1])) < 1e-5
        assert abs(float(N[k][2])) < 1e-5


def test_collision_world_aabb_and_generation_cache():
    CADKernel.clear_collision_cache()
    p1 = Panel("P1", 0, 0, 0, 100, 100, 16)
    p2 = Panel("P2", 50, 50, 0, 100, 100, 16)
    p3 = Panel("P3", 500, 500, 0, 100, 100, 16)

    assert CADKernel.aabb_overlaps(p1, p2) is True
    assert CADKernel.aabb_overlaps(p1, p3) is False
    assert CADKernel.check_collision(p1, p3) == 0.0

    # Повернутая панель: проверяем, что aabb_overlaps использует world_aabb()
    p_rot = Panel("PRot", 120, 0, 0, 16, 200, 100)
    assert CADKernel.aabb_overlaps(p1, p_rot) is False
    p_rot.rz = 90.0  # после поворота вокруг Z уходит в отрицательный X и пересекает p1
    assert CADKernel.aabb_overlaps(p1, p_rot) is True

    # Кэширование по geometry_generation: кладём известное значение в кэш пары и проверяем hit
    k1 = CADKernel._panel_collision_token(p1)
    k2 = CADKernel._panel_collision_token(p2)
    pair_key = (k1, k2) if k1 <= k2 else (k2, k1)
    CADKernel._COLLISION_CACHE[pair_key] = 1234.5
    assert CADKernel.check_collision(p1, p2) == 1234.5

    # При изменении geometry_generation токен меняется -> кэш инвалидируется
    p2.geometry_generation += 1
    new_k2 = CADKernel._panel_collision_token(p2)
    assert new_k2 != k2


@pytest.mark.gui
def test_scene_gpu_ids_and_line_batching():
    """Проверка батчинга линий и O(1) принадлежности панели сцене без создания GL-контекста."""
    pytest.importorskip("PyQt6")
    from ui.viewport import Viewport3D

    # Создаём облегчённый объект с методами Viewport3D без инициализации QOpenGLWidget
    vp = Viewport3D.__new__(Viewport3D)
    b = Block("Корпус", "1", "01.00")
    p_in = Panel("Своя", 0, 0, 0, 400, 720, 16)
    p_out = Panel("Чужая", 0, 0, 0, 400, 720, 16)
    b.panels.append(p_in)
    vp.blocks = [b]
    vp._panel_gpu = {}
    vp._scene_gpu_ids = set()
    vp._scene_gpu_ids_token = None
    vp._rebuild_scene_gpu_ids()

    assert vp._panel_belongs_here(p_in) is True
    assert vp._panel_belongs_here(p_out) is False
    assert vp._panel_gpu_key(p_in) in vp._scene_gpu_ids

    # Проверим батчинг линий: несколько вызовов _draw_lines одного цвета сливаются в один flush
    drawn_batches = []
    vp._draw_lines_immediate = lambda arr, col: drawn_batches.append((len(arr), col))
    vp._begin_line_batch()
    vp._draw_lines([[0, 0, 0], [10, 0, 0]], (0.15, 0.15, 0.15))
    vp._draw_lines([[0, 10, 0], [10, 10, 0]], (0.15, 0.15, 0.15))
    vp._draw_lines([[0, 0, 5], [10, 0, 5]], (0.95, 0.1, 0.1))
    assert len(drawn_batches) == 0
    vp._flush_line_batch()
    assert len(drawn_batches) == 2
    assert drawn_batches[0] == (4, (0.15, 0.15, 0.15))
    assert drawn_batches[1] == (2, (0.95, 0.1, 0.1))


def test_cad_kernel_warmup_builds_brep_and_tessellates(monkeypatch=None):
    """Ревизия 2, п. 1.4: прогрев вызывает build_panel_solid_data с отверстием и get_render_mesh."""
    calls = []
    orig_build = CADKernel.build_panel_solid_data
    orig_mesh = CADKernel.get_render_mesh
    fake_solid = _FakeSolid()

    def _spy_build(*args, **kwargs):
        calls.append(("build", args, kwargs))
        return fake_solid

    def _spy_mesh(solid):
        calls.append(("mesh", solid))
        return orig_mesh(solid)

    try:
        CADKernel.build_panel_solid_data = staticmethod(_spy_build)
        CADKernel.get_render_mesh = staticmethod(_spy_mesh)
        V, T, N = CADKernel.warmup()
        assert len(V) == 6
        assert len(T) == 2
        assert len(N) == 6
    finally:
        CADKernel.build_panel_solid_data = staticmethod(orig_build)
        CADKernel.get_render_mesh = staticmethod(orig_mesh)

    assert len(calls) == 2
    assert calls[0][0] == "build"
    assert calls[0][1] == (0, 0, 0, 16, 100, 100)
    assert calls[0][2] == {"holes": [(8, 50, 50, 3.5, 16, "X")]}
    assert calls[1] == ("mesh", fake_solid)


def test_cad_kernel_raises_importerror_without_build123d():
    """Ревизия 2, п. 1.5: без build123d (или без Extrinsic) импорт cad_kernel выбрасывает ImportError, а не подменяет классы на None."""
    import builtins
    import importlib
    import sys

    saved_b123d = sys.modules.get("build123d")
    saved_ck = sys.modules.get("core.cad_kernel")
    real_import = builtins.__import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "build123d" or name.startswith("build123d."):
            raise ImportError("No module named 'build123d'")
        return real_import(name, globals, locals, fromlist, level)

    try:
        sys.modules.pop("build123d", None)
        sys.modules.pop("core.cad_kernel", None)
        builtins.__import__ = _blocked_import
        try:
            importlib.import_module("core.cad_kernel")
            raise AssertionError("Expected ImportError when build123d is missing")
        except ImportError as exc:
            assert "build123d" in str(exc)
    finally:
        builtins.__import__ = real_import
        if saved_b123d is not None:
            sys.modules["build123d"] = saved_b123d
        if saved_ck is not None:
            sys.modules["core.cad_kernel"] = saved_ck


def test_collision_error_not_cached_and_reported_as_unverified():
    """Ревизия 2, п. 1.6: при ошибке B-Rep check_collision логирует сбой, не пишет 0.0 в кэш, а анализ помечает пару как «не удалось проверить»."""
    CADKernel.clear_collision_cache()
    p1 = Panel("Боковина", 0, 0, 0, 100, 100, 16, rebuild=False)
    p2 = Panel("Полка", 50, 50, 0, 100, 100, 16, rebuild=False)

    class _BrokenSolid:
        def __and__(self, other):
            raise RuntimeError("OCC boolean intersection failed")

    class _ValidCommon:
        volume = 512.0

    class _ValidSolid:
        def __and__(self, other):
            return _ValidCommon()

    p1.solid = _BrokenSolid()
    p2.solid = _ValidSolid()

    k1 = CADKernel._panel_collision_token(p1)
    k2 = CADKernel._panel_collision_token(p2)
    pair_key = (k1, k2) if k1 <= k2 else (k2, k1)

    # 1) Сбой в check_collision возвращает 0.0, но НЕ сохраняет пару в _COLLISION_CACHE
    assert CADKernel.check_collision(p1, p2) == 0.0
    assert pair_key not in CADKernel._COLLISION_CACHE

    # 2) find_scene_collisions возвращает (p1, p2, None) для непроверенной пары
    scene_hits = CADKernel.find_scene_collisions([p1, p2], min_volume=0.1)
    assert scene_hits == [(p1, p2, None)]
    assert pair_key not in CADKernel._COLLISION_CACHE

    # 3) В анализе такая пара форматируется как «не удалось проверить»
    label = CADKernel.format_collision_hit(*scene_hits[0])
    assert "не удалось проверить" in label.lower()
    assert "Боковина" in label and "Полка" in label

    # 4) После починки solid (даже без изменения geometry_generation) повторная проверка считает реальный объём
    p1.solid = _ValidSolid()
    assert CADKernel.check_collision(p1, p2) == 512.0
    assert CADKernel._COLLISION_CACHE.get(pair_key) == 512.0
    ok_hits = CADKernel.find_scene_collisions([p1, p2], min_volume=0.1)
    assert ok_hits == [(p1, p2, 512.0)]
    assert "512 мм³" in CADKernel.format_collision_hit(*ok_hits[0])


if __name__ == "__main__":
    test_get_render_mesh_vectorized_shapes_and_normals()
    test_collision_world_aabb_and_generation_cache()
    try:
        test_scene_gpu_ids_and_line_batching()
    except Exception as exc:
        if exc.__class__.__name__ in ("Skipped", "_SkipTestException", "SkipTest"):
            print(f"SKIPPED test_scene_gpu_ids_and_line_batching: {exc}")
        else:
            raise
    test_cad_kernel_warmup_builds_brep_and_tessellates()
    test_cad_kernel_raises_importerror_without_build123d()
    test_collision_error_not_cached_and_reported_as_unverified()
    print("ALL PERFORMANCE 2.5 TESTS PASSED")
