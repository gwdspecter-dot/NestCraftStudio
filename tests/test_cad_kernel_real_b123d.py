"""
Интеграционные тесты реального B-Rep ядра build123d (ревизия 2, п. 1.9).

В обычном прогоне `tests/conftest.py` подменяет `build123d` легковесным стабом,
чтобы юнит-тесты проходили мгновенно без OpenCASCADE.
Этот модуль помечен `@pytest.mark.slow`: он временно убирает стаб `build123d`,
запрашивает реальный пакет `build123d` через `pytest.importorskip("build123d")`
и проверяет настоящие булевы операции `CADKernel` (глухое отверстие без overshoot
на слепом конце, совпадение B-Rep bounding_box повернутой панели с `Panel.world_aabb()`,
вычитание паза и расчёт объёма пересечения 3D-тел).
"""

import contextlib
import importlib
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tests.conftest  # noqa: F401
import pytest


@contextlib.contextmanager
def _real_build123d_cad_kernel():
    """
    Временно выгружает стаб `build123d` из `sys.modules`, импортирует реальный
    `build123d` (или пропускает тест через `pytest.importorskip`) и загружает
    реальный `core.cad_kernel.CADKernel`, работающий на настоящем B-Rep.
    После выхода восстанавливает исходное состояние `sys.modules`.
    """
    saved_b123d = sys.modules.get("build123d")
    saved_cad_kernel = sys.modules.get("core.cad_kernel")
    try:
        if saved_b123d is not None and not getattr(saved_b123d, "__file__", None):
            sys.modules.pop("build123d", None)

        real_b123d = pytest.importorskip(
            "build123d",
            reason="Real build123d (OpenCASCADE) is required for slow B-Rep tests",
        )
        if not getattr(real_b123d, "__file__", None):
            pytest.skip("build123d is a stub, real OpenCASCADE package is not installed")

        sys.modules.pop("core.cad_kernel", None)
        cad_kernel_mod = importlib.import_module("core.cad_kernel")
        cad_kernel_mod.CADKernel.clear_collision_cache()
        yield cad_kernel_mod.CADKernel
    finally:
        if saved_b123d is not None:
            sys.modules["build123d"] = saved_b123d
        if saved_cad_kernel is not None:
            sys.modules["core.cad_kernel"] = saved_cad_kernel


@pytest.mark.slow
def test_blind_hole_volume():
    """
    Ревизия 2, п. 1.9: глухое отверстие (0, 50, 50, r=3.5, depth=10, 'X') имеет
    ровно длину 10 мм внутри детали (overshoot только со стороны входной грани X=0).
    """
    with _real_build123d_cad_kernel() as CADKernel:
        s = CADKernel.build_panel_solid_data(
            0, 0, 0, 16, 100, 100,
            holes=[(0, 50, 50, 3.5, 10, "X")],
        )
        expected = 16.0 * 100.0 * 100.0 - math.pi * (3.5 ** 2) * 10.0
        assert abs(float(s.volume) - expected) < 1.0


@pytest.mark.slow
def test_rotated_panel_bounding_box_matches_world_aabb():
    """
    Ревизия 2, п. 1.9: bounding_box твердого тела панели с rx=30, ry=40, rz=50
    совпадает с Panel.world_aabb() в пределах 0.1 мм.
    """
    with _real_build123d_cad_kernel() as CADKernel:
        from models.panel import Panel

        p = Panel(
            "Rotated",
            10.0, 20.0, 30.0,
            16.0, 200.0, 100.0,
            rx=30.0, ry=40.0, rz=50.0,
            rebuild=False,
        )
        s = CADKernel.build_panel_solid(p)
        bb = s.bounding_box()
        (ax0, ay0, az0), (ax1, ay1, az1) = p.world_aabb()
        assert abs(float(bb.min.X) - ax0) < 0.1
        assert abs(float(bb.min.Y) - ay0) < 0.1
        assert abs(float(bb.min.Z) - az0) < 0.1
        assert abs(float(bb.max.X) - ax1) < 0.1
        assert abs(float(bb.max.Y) - ay1) < 0.1
        assert abs(float(bb.max.Z) - az1) < 0.1


@pytest.mark.slow
def test_real_b123d_boolean_hole_and_groove_subtraction():
    """
    Реальное булево вычитание отверстия и паза из плиты в build123d уменьшает
    объём твердого тела и строит непустую триангуляцию.
    """
    with _real_build123d_cad_kernel() as CADKernel:
        solid_plain = CADKernel.build_panel_solid_data(
            0.0, 0.0, 0.0,
            100.0, 100.0, 16.0,
            grooves=[],
            holes=[],
        )
        assert solid_plain is not None
        V_plain, T_plain, N_plain = CADKernel.get_render_mesh(solid_plain)
        assert len(T_plain) >= 12
        vol_plain = float(solid_plain.volume)
        assert vol_plain == pytest.approx(100.0 * 100.0 * 16.0, rel=1e-3)

        solid_cut = CADKernel.build_panel_solid_data(
            0.0, 0.0, 0.0,
            100.0, 100.0, 16.0,
            grooves=[(10.0, 0.0, 10.0, 4.0, 100.0, 6.0)],
            holes=[(50.0, 50.0, 0.0, 5.0, 10.0, "Z")],
        )
        assert solid_cut is not None
        V_cut, T_cut, N_cut = CADKernel.get_render_mesh(solid_cut)
        assert len(T_cut) > len(T_plain)
        vol_cut = float(solid_cut.volume)
        assert vol_cut < vol_plain


@pytest.mark.slow
def test_real_b123d_check_collision():
    """
    Реальная проверка булева пересечения двух 3D-деталей через CADKernel.check_collision.
    """
    with _real_build123d_cad_kernel() as CADKernel:
        from models.panel import Panel

        p1 = Panel("P1", 0.0, 0.0, 0.0, 100.0, 100.0, 16.0, rebuild=False)
        p2_overlap = Panel("P2", 50.0, 0.0, 0.0, 100.0, 100.0, 16.0, rebuild=False)
        p3_apart = Panel("P3", 250.0, 0.0, 0.0, 100.0, 100.0, 16.0, rebuild=False)

        p1.solid = CADKernel.build_panel_solid_data(0.0, 0.0, 0.0, 100.0, 100.0, 16.0)
        p2_overlap.solid = CADKernel.build_panel_solid_data(50.0, 0.0, 0.0, 100.0, 100.0, 16.0)
        p3_apart.solid = CADKernel.build_panel_solid_data(250.0, 0.0, 0.0, 100.0, 100.0, 16.0)
        p1.geometry_pending = False
        p2_overlap.geometry_pending = False
        p3_apart.geometry_pending = False

        vol_overlap = CADKernel.check_collision(p1, p2_overlap)
        assert vol_overlap == pytest.approx(50.0 * 100.0 * 16.0, rel=1e-2)

        vol_apart = CADKernel.check_collision(p1, p3_apart)
        assert vol_apart == 0.0


if __name__ == "__main__":
    try:
        test_blind_hole_volume()
        test_rotated_panel_bounding_box_matches_world_aabb()
        test_real_b123d_boolean_hole_and_groove_subtraction()
        test_real_b123d_check_collision()
        print("REAL BUILD123D SLOW TESTS PASSED")
    except Exception as exc:
        if exc.__class__.__name__ in ("Skipped", "_SkipTestException", "SkipTest"):
            print(f"SKIPPED real build123d slow tests: {exc}")
        else:
            raise
