# -*- coding: utf-8 -*-
"""ViewCube: цели камеры и hit-test логика (без OpenGL)."""

from __future__ import annotations

from ui.viewcube import (
    FACE_TARGETS,
    ISO_TARGET,
    ORTHO_HALF_TAN,
    blend_projection_matrices,
    build_drawable,
    hit_test,
    layout_for_widget,
    pan_for_pivot,
    pivot_from_pan,
    target_for_hit,
)


def test_face_targets_match_standard_views():
    assert FACE_TARGETS["front"][:3] == (0.0, 0.0, True)
    assert FACE_TARGETS["top"][:3] == (90.0, 0.0, True)
    assert ISO_TARGET[0] == 25.0 and ISO_TARGET[2] is False


def test_target_for_home_and_edge():
    rx, ry, ortho, label = target_for_hit("home", "home")
    assert abs(rx - 25.0) < 1e-6 and ortho is False
    rx, ry, ortho, _ = target_for_hit("edge", "e_front_top")
    assert ortho is True
    # между front (0) и top (90)
    assert 0.0 < rx < 90.0


def test_layout_top_right():
    lay = layout_for_widget(800, 600)
    assert lay.cx > 700
    assert lay.cy < 120


def test_hit_home_button():
    lay = layout_for_widget(800, 600)
    drawable = build_drawable(25.0, -35.0, lay)
    hx, hy, hw, hh = lay.home_rect
    hit = hit_test(hx + hw * 0.5, hy + hh * 0.5, drawable, lay)
    assert hit == ("home", "home")


def test_chamfer_edge_strip_and_axes_triad():
    """Проверяет, что у граней есть внутренние площадки и русские подписи, у рёбер — полигоны-фаски
    (клик работает вдоль длины ребра, а не только в центральной точке), а также строится 3D-компас осей X/Y/Z.
    """
    lay = layout_for_widget(800, 600)
    drawable = build_drawable(25.0, -35.0, lay)
    assert [a["axis"] for a in sorted(drawable["axes"], key=lambda x: x["axis"])] == ["X", "Y", "Z"]

    front_face = next(f for f in drawable["faces"] if f["id"] == "front")
    assert front_face["caption"] == "СПЕРЕДИ"
    assert len(front_face["inner_poly"]) == 4

    edge_ft = next(e for e in drawable["edges"] if e["id"] == "e_front_top")
    assert edge_ft["visible"] is True
    assert len(edge_ft["poly"]) >= 4
    # Точка на 60% вдоль отрезка ребра (далеко от середины ребра) должна попадать в hit_test ребра
    ax, ay = edge_ft["seg_a"]
    bx, by = edge_ft["seg_b"]
    px = ax + (bx - ax) * 0.25
    py = ay + (by - ay) * 0.25
    assert hit_test(px, py, drawable, lay) == ("edge", "e_front_top")


def test_bevel_corner_hit_and_watertight_shade():
    """Проверяет треугольные фаски углов, расчёт освещения (shade) и отсутствие перекрытий с триадой осей."""
    lay = layout_for_widget(800, 600)
    drawable = build_drawable(25.0, -35.0, lay)
    corner_rtf = next(c for c in drawable["corners"] if c["id"] == "c_RTF")
    assert corner_rtf["visible"] is True
    assert len(corner_rtf["poly"]) == 3
    cx_tri, cy_tri = corner_rtf["pos"]
    assert hit_test(cx_tri, cy_tri, drawable, lay) == ("corner", "c_RTF")

    top_face = next(f for f in drawable["faces"] if f["id"] == "top")
    assert 0.0 <= top_face["shade"] <= 1.0
    # Триада осей вынесена за пределы тела куба (не закрывает грани)
    for ax in drawable["axes"]:
        ox, oy = ax["start"]
        assert ox < lay.cx - lay.half
        assert oy >= lay.cy + lay.half


def test_front_faces_are_visible_and_clickable_not_back_faces():
    """При изометрии (25°, -35°) видимы ровно 3 передние грани (front, right, top),
    а клик в центр куба попадает в видимую переднюю грань, а не в заднюю (back/left/bottom).
    """
    lay = layout_for_widget(800, 600)
    drawable = build_drawable(25.0, -35.0, lay)
    vis_faces = {f["id"] for f in drawable["faces"] if f["visible"]}
    assert vis_faces == {"front", "right", "top"}

    # На чистом виде спереди (0, 0) видима только грань front, и клик по центру попадает в неё
    drawable_front = build_drawable(0.0, 0.0, lay)
    vis_front = {f["id"] for f in drawable_front["faces"] if f["visible"]}
    assert vis_front == {"front"}
    hit_center = hit_test(lay.cx, lay.cy, drawable_front, lay)
    assert hit_center == ("face", "front")


def test_all_edges_and_corners_bring_target_to_cube_center():
    """Для каждого из 12 рёбер и 8 углов вычисленные (rot_x, rot_y) поворачивают куб так,
    что выбранное ребро или угол оказывается точно в центре ViewCube лицом к камере (depth > 0).
    """
    from ui.viewcube import _corner_points, _edge_midpoints, _rot_matrix, project_point

    lay = layout_for_widget(800, 600)

    # Проверяем проблемные ранее рёбра: e_back_top (45°, 180°) и e_top_right (45°, -90°)
    rx_bt, ry_bt, ortho_bt, _ = target_for_hit("edge", "e_back_top")
    assert ortho_bt is True
    assert abs(rx_bt - 45.0) < 1e-3 and abs(abs(ry_bt) - 180.0) < 1e-3

    rx_tr, ry_tr, ortho_tr, _ = target_for_hit("edge", "e_top_right")
    assert ortho_tr is True
    assert abs(rx_tr - 45.0) < 1e-3 and abs(ry_tr - (-90.0)) < 1e-3

    for eid, mid, _fa, _fb in _edge_midpoints():
        rx, ry, _ortho, _lbl = target_for_hit("edge", eid)
        R = _rot_matrix(rx, ry)
        sx, sy, depth = project_point(mid, R, lay)
        assert abs(sx - lay.cx) < 1e-2, f"Edge {eid} did not center X"
        assert abs(sy - lay.cy) < 1e-2, f"Edge {eid} did not center Y"
        assert depth > 0.9, f"Edge {eid} is not facing camera (depth={depth})"

    for cid, pt, _faces in _corner_points():
        rx, ry, ortho, _lbl = target_for_hit("corner", cid)
        assert ortho is False
        R = _rot_matrix(rx, ry)
        sx, sy, depth = project_point(pt, R, lay)
        assert abs(sx - lay.cx) < 1e-2, f"Corner {cid} did not center X"
        assert abs(sy - lay.cy) < 1e-2, f"Corner {cid} did not center Y"
        assert depth > 1.5, f"Corner {cid} is not facing camera (depth={depth})"


def test_pivot_roundtrip_and_view_rotation_keeps_point_centered():
    """Проверяет, что пересчёт (pan_x, pan_y) через 3D-pivot удерживает центр шкафа
    (например, [300, 360, 280]) строго в центре экрана при любом повороте камеры
    (Спереди, Справа, Сверху, Изометрия).
    """
    from ui.viewcube import _rot_matrix
    import numpy as np

    cabinet_center = (300.0, 360.0, 280.0)
    for rx, ry in [(0.0, 0.0), (0.0, -90.0), (90.0, 0.0), (25.0, -35.0), (-35.264, 45.0)]:
        px, py = pan_for_pivot(rx, ry, cabinet_center)
        # Применяем поворот камеры и панорамирование к точке cabinet_center
        R = _rot_matrix(rx, ry)
        v_cam = R @ np.array(cabinet_center, dtype=np.float32)
        x_screen = float(v_cam[0]) + px
        y_screen = float(v_cam[1]) + py
        assert abs(x_screen) < 1e-3
        assert abs(y_screen) < 1e-3

        # И обратное восстановление pivot при ручном панорамировании
        restored = pivot_from_pan(rx, ry, px + 45.0, py - 20.0, cabinet_center)
        px2, py2 = pan_for_pivot(rx, ry, restored)
        assert abs(px2 - (px + 45.0)) < 1e-3
        assert abs(py2 - (py - 20.0)) < 1e-3


def test_ortho_scale_and_projection_matrix_blend():
    """Масштаб ортографии совпадает с перспективой 45° на глубине zoom_dist,
    а плавное смешивание матриц даёт непрерывный переход от 0.0 до 1.0 без скачка.
    """
    import math
    import numpy as np

    assert abs(ORTHO_HALF_TAN - math.tan(math.radians(22.5))) < 1e-7
    zoom_dist = 1800.0
    aspect = 16.0 / 9.0
    f = 1.0 / math.tan(math.radians(45.0) * 0.5)
    proj_p = np.array([
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, -1.0, -20.0],
        [0.0, 0.0, -1.0, 0.0],
    ], dtype=np.float32)
    half_h = zoom_dist * ORTHO_HALF_TAN
    half_w = half_h * aspect
    proj_o = np.array([
        [1.0 / half_w, 0.0, 0.0, 0.0],
        [0.0, 1.0 / half_h, 0.0, 0.0],
        [0.0, 0.0, -0.0001, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ], dtype=np.float32)

    m0 = blend_projection_matrices(proj_p, proj_o, 0.0, zoom_dist)
    m1 = blend_projection_matrices(proj_p, proj_o, 1.0, zoom_dist)
    m_mid = blend_projection_matrices(proj_p, proj_o, 0.5, zoom_dist)

    assert abs(float(m0[0][0]) - float(proj_p[0][0])) < 1e-5
    assert abs(float(m1[0][0]) - float(proj_o[0][0])) < 1e-5
    # На глубине z = -zoom_dist нормализованный масштаб X/W одинаков у persp, mid и ortho
    w_mid = float(-m_mid[3][2] * zoom_dist + m_mid[3][3])
    assert abs(w_mid - 1.0) < 1e-4
    ndc_x_persp = float(proj_p[0][0] * 100.0) / zoom_dist
    ndc_x_ortho = float(proj_o[0][0] * 100.0) / 1.0
    ndc_x_mid = float(m_mid[0][0] * 100.0) / w_mid
    assert abs(ndc_x_persp - ndc_x_ortho) < 1e-5
    assert abs(ndc_x_mid - ndc_x_ortho) < 1e-5


def test_draw_viewcube_has_no_hover_tooltip():
    """При наведении на грань, ребро, угол или кнопку «Домой» всплывающая HUD-подсказка не рисуется."""
    import sys
    import types

    from ui.viewcube import draw_viewcube

    saved = {k: sys.modules.get(k) for k in ("PyQt6", "PyQt6.QtCore", "PyQt6.QtGui")}
    if "PyQt6.QtGui" not in sys.modules:
        qt_mod = types.ModuleType("PyQt6")
        qt_core = types.ModuleType("PyQt6.QtCore")
        qt_gui = types.ModuleType("PyQt6.QtGui")

        class _EnumVal:
            def __init__(self, v: int = 0):
                self._v = v

            def __int__(self):
                return self._v

        qt_core.QPointF = lambda x=0.0, y=0.0: (x, y)
        qt_core.Qt = types.SimpleNamespace(
            PenStyle=types.SimpleNamespace(NoPen=_EnumVal(0), SolidLine=_EnumVal(1)),
            BrushStyle=types.SimpleNamespace(NoBrush=_EnumVal(0)),
            PenCapStyle=types.SimpleNamespace(RoundCap=_EnumVal(1)),
            PenJoinStyle=types.SimpleNamespace(RoundJoin=_EnumVal(1)),
            AlignmentFlag=types.SimpleNamespace(AlignCenter=_EnumVal(1)),
        )

        class _Color:
            def __init__(self, *a):
                self.args = a

            def darker(self, _f=150):
                return self

            def lighter(self, _f=150):
                return self

        class _Grad:
            def __init__(self, *a):
                pass

            def setColorAt(self, *a):
                pass

        class _Font:
            def __init__(self, *a):
                pass

            def setPointSize(self, _s):
                pass

            def setBold(self, _b):
                pass

        class _Path:
            def moveTo(self, *a):
                pass

            def lineTo(self, *a):
                pass

            def closeSubpath(self):
                pass

        qt_gui.QColor = _Color
        qt_gui.QBrush = lambda *a: None
        qt_gui.QPen = lambda *a: None
        qt_gui.QFont = _Font
        qt_gui.QPainterPath = _Path
        qt_gui.QLinearGradient = _Grad
        qt_gui.QRadialGradient = _Grad
        qt_mod.QtCore = qt_core
        qt_mod.QtGui = qt_gui
        sys.modules["PyQt6"] = qt_mod
        sys.modules["PyQt6.QtCore"] = qt_core
        sys.modules["PyQt6.QtGui"] = qt_gui

    class _RecorderPainter:
        def __init__(self):
            self.rounded_rects: list[tuple[int, int, int, int]] = []
            self.texts: list[str] = []

        def setPen(self, *_a):
            pass

        def setBrush(self, *_a):
            pass

        def setFont(self, *_a):
            pass

        def drawEllipse(self, *_a):
            pass

        def drawLine(self, *_a):
            pass

        def drawPath(self, *_a):
            pass

        def drawRoundedRect(self, x, y, w, h, *_a):
            self.rounded_rects.append((x, y, w, h))

        def drawText(self, _x, _y, _w, _h, _align, txt):
            self.texts.append(txt)

    try:
        for hover_item in (
            ("face", "front"),
            ("edge", "e_front_top"),
            ("corner", "c_RTF"),
            ("home", "home"),
        ):
            p = _RecorderPainter()
            draw_viewcube(p, 25.0, -35.0, 800, 600, hover=hover_item)
            # Единственный drawRoundedRect — кнопка Home (никакого бейджа-подсказки)
            assert len(p.rounded_rects) == 1
            assert "Домой (Изометрия)" not in p.texts
            assert "Спереди + Сверху" not in p.texts
            assert "Спереди" not in p.texts
    finally:
        for k, prev in saved.items():
            if prev is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = prev



