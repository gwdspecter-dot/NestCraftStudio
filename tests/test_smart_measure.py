"""Unit-тесты умной 3D-линейки (в стиле QymCAD): грани в свету, углы граней, шаг отверстий, отступ от края."""

from __future__ import annotations

import numpy as np

from core.dimension import (
    DimensionAngle,
    DimensionLine,
    build_measure_target,
    compute_smart_measurement,
    detect_panel_face_at_point,
    inspect_hole_on_panel,
)
from models.panel import Panel


def test_parallel_faces_clearance_between_two_shelves():
    """Две параллельные полки: клик по верхней грани нижней полки и нижней грани верхней полки
    в разных по X/Z точках выдаёт строго перпендикулярное расстояние «В свету».
    """
    shelf_bottom = Panel("Полка нижняя", x=16.0, y=100.0, z=0.0, width=568.0, height=16.0, depth=500.0, rebuild=False)
    shelf_top = Panel("Полка верхняя", x=16.0, y=456.0, z=0.0, width=568.0, height=16.0, depth=500.0, rebuild=False)

    t1 = build_measure_target(
        np.array([80.0, 116.0, 420.0]),
        "Поверхность",
        "surface",
        panel=shelf_bottom,
    )
    t2 = build_measure_target(
        np.array([510.0, 456.0, 90.0]),
        "Поверхность",
        "surface",
        panel=shelf_top,
    )

    assert t1.is_face and t1.face_id == "top"
    assert t2.is_face and t2.face_id == "bottom"

    res = compute_smart_measurement(t1, t2)
    assert res.mode == "parallel_faces"
    assert not res.allows_third_point_angle
    assert abs(res.dimension_line.distance - 340.0) < 1e-4
    assert "В свету: 340.0 мм" in res.dimension_line.main_badge_text()


def test_parallel_faces_same_panel_thickness():
    """Две противоположные грани одной детали измеряют её толщину."""
    side = Panel("Стоевая", x=0.0, y=0.0, z=0.0, width=16.0, height=720.0, depth=500.0, rebuild=False)
    t1 = build_measure_target(np.array([0.0, 300.0, 200.0]), "Левая", "surface", panel=side)
    t2 = build_measure_target(np.array([16.0, 450.0, 350.0]), "Правая", "surface", panel=side)

    res = compute_smart_measurement(t1, t2)
    assert res.mode == "parallel_faces"
    assert abs(res.dimension_line.distance - 16.0) < 1e-4
    assert "Толщина/габарит: 16.0 мм" in res.dimension_line.main_badge_text()


def test_perpendicular_faces_angle_90_deg():
    """Две непараллельные грани (стоевая и полка) сразу возвращают угол между гранями 90°."""
    side = Panel("Стоевая левая", x=0.0, y=0.0, z=0.0, width=16.0, height=720.0, depth=500.0, rebuild=False)
    shelf = Panel("Полка", x=16.0, y=300.0, z=0.0, width=568.0, height=16.0, depth=500.0, rebuild=False)

    t1 = build_measure_target(np.array([16.0, 350.0, 250.0]), "Правая грань", "surface", panel=side)
    t2 = build_measure_target(np.array([200.0, 316.0, 250.0]), "Верхняя грань", "surface", panel=shelf)

    res = compute_smart_measurement(t1, t2)
    assert res.mode == "angled_faces"
    assert res.angle_dimension is not None
    assert "90.0°" in res.dimension_line.main_badge_text()


def test_hole_inspection_and_system32_step():
    """Наведение на отверстие показывает его Ø, глубину и отступы до кромок,
    а выбор двух отверстий с шагом 64 мм определяет кратность Системе 32 (2×32).
    """
    side = Panel("Стоевая", x=0.0, y=0.0, z=0.0, width=16.0, height=720.0, depth=500.0, rebuild=False)
    h1 = (16.0, 100.0, 37.0, 4.0, 13.0, "X")
    h2 = (16.0, 164.0, 37.0, 4.0, 13.0, "X")
    side.holes = [h1, h2]

    info1 = inspect_hole_on_panel(side, h1)
    assert abs(info1["diameter"] - 8.0) < 1e-6
    assert abs(info1["depth"] - 13.0) < 1e-6
    assert abs(info1["margin_min"] - 37.0) < 1e-6
    assert abs(info1["margin_max"] - 100.0) < 1e-6

    t1 = build_measure_target(np.array([16.0, 100.0, 37.0]), "Отверстие 1", "hole", panel=side, meta={"hole": h1})
    t2 = build_measure_target(np.array([16.0, 164.0, 37.0]), "Отверстие 2", "hole", panel=side, meta={"hole": h2})

    assert "Ø8.0×13" in t1.format_hover_summary()
    assert "37.0" in t1.format_hover_summary()

    res = compute_smart_measurement(t1, t2)
    assert res.mode == "hole_step"
    assert abs(res.dimension_line.distance - 64.0) < 1e-4
    assert "Система 32: 2×32" in res.status_message


def test_hole_to_face_perpendicular_offset():
    """Выбор отверстия и торцевой грани детали вычисляет точный перпендикулярный отступ от края."""
    side = Panel("Стоевая", x=0.0, y=0.0, z=0.0, width=16.0, height=720.0, depth=500.0, rebuild=False)
    h1 = (16.0, 100.0, 37.0, 2.5, 13.0, "X")

    t_hole = build_measure_target(np.array([16.0, 100.0, 37.0]), "Отверстие", "hole", panel=side, meta={"hole": h1})
    t_face = build_measure_target(np.array([8.0, 350.0, 0.0]), "Задняя грань", "surface", panel=side)

    res = compute_smart_measurement(t_hole, t_face)
    assert res.mode == "hole_to_face"
    assert abs(res.dimension_line.distance - 37.0) < 1e-4
    assert "37.0 мм" in res.dimension_line.main_badge_text()


def test_rotated_panel_face_detection_and_angle():
    """Повёрнутая на 45° панель корректно отдаёт мировую нормаль своей грани."""
    p = Panel("Наклонная", x=0.0, y=0.0, z=0.0, width=400.0, height=16.0, depth=300.0, rz=45.0, rebuild=False)
    top_world = np.array(p.local_to_world(200.0, 16.0, 150.0), dtype=float)
    face_id, _label, normal, _dims = detect_panel_face_at_point(p, top_world)
    assert face_id == "top"
    assert abs(float(normal[0]) - (-0.70710678)) < 1e-3
    assert abs(float(normal[1]) - 0.70710678) < 1e-3


def test_legacy_dimension_line_and_angle_compatibility():
    """Стандартные DimensionLine и DimensionAngle сохраняют полную обратную совместимость."""
    dim = DimensionLine(np.array([0.0, 0.0, 0.0]), np.array([100.0, 0.0, 0.0]))
    assert abs(dim.distance - 100.0) < 1e-6
    assert dim.format_label() == "X: 100.0 мм"

    ang = DimensionAngle(
        np.array([100.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 0.0]),
        np.array([0.0, 100.0, 0.0]),
    )
    assert ang.is_right_angle
    assert len(ang.arc_points()) == 3
