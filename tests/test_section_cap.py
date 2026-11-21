"""Тесты сплошной stencil-заглушки сечения со штриховкой деталей (OpenGL Core 3.3)."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace

from core import glmath

ROOT = Path(__file__).resolve().parent.parent


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    ln = math.sqrt(_dot(v, v))
    assert ln > 1e-9
    return (v[0] / ln, v[1] / ln, v[2] / ln)


def _luma(rgb: tuple[float, float, float]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def test_panel_intersects_section_plane_cases():
    p = SimpleNamespace(x=100.0, y=0.0, z=50.0, width=16.0, height=720.0, depth=500.0, visible=True)
    # Внутри диапазона Z=[50, 550]
    assert glmath.panel_intersects_section_plane(p, "Z", 300.0) is True
    # Снаружи диапазона
    assert glmath.panel_intersects_section_plane(p, "Z", 20.0) is False
    assert glmath.panel_intersects_section_plane(p, "Z", 600.0) is False
    # Касание граней исключено (eps=0.05)
    assert glmath.panel_intersects_section_plane(p, "Z", 50.0) is False
    assert glmath.panel_intersects_section_plane(p, "Z", 550.0) is False
    # Ось X=[100, 116]
    assert glmath.panel_intersects_section_plane(p, "X", 108.0) is True
    assert glmath.panel_intersects_section_plane(p, "X", 116.0) is False
    # Скрытая панель не участвует
    hidden = SimpleNamespace(x=0.0, y=0.0, z=0.0, width=500.0, height=500.0, depth=500.0, visible=False)
    assert glmath.panel_intersects_section_plane(hidden, "Z", 250.0) is False


def test_panel_intersects_section_plane_uses_world_aabb():
    # Повёрнутая панель с мировым AABB, отличным от локального (x..x+w)
    rotated = SimpleNamespace(
        x=0.0, y=0.0, z=0.0, width=16.0, height=500.0, depth=500.0, visible=True,
        world_aabb=lambda: ((-150.0, 0.0, 0.0), (150.0, 500.0, 500.0)),
    )
    assert glmath.panel_intersects_section_plane(rotated, "X", -80.0) is True
    assert glmath.panel_intersects_section_plane(rotated, "X", 200.0) is False


def test_compute_section_cap_quad_winding_and_basis_all_axes():
    mn = (10.0, 20.0, 30.0)
    mx = (210.0, 740.0, 530.0)
    offset = 125.0
    pad = 15.0

    for axis_idx, axis in enumerate(("X", "Y", "Z")):
        for flip in (False, True):
            plane = glmath.compute_section_clip_plane(axis, offset, flip=flip)
            expected_normal = (-plane[0], -plane[1], -plane[2])

            verts, cap_normal, u_axis, v_axis = glmath.compute_section_cap_quad(
                axis, offset, flip, mn, mx, pad=pad
            )
            assert len(verts) == 6
            assert cap_normal == expected_normal

            # Все 6 вершин лежат строго в плоскости сечения
            for v in verts:
                assert abs(v[axis_idx] - offset) < 1e-6

            # Правый ортонормированный базис: u × v == cap_normal
            assert abs(_dot(u_axis, u_axis) - 1.0) < 1e-6
            assert abs(_dot(v_axis, v_axis) - 1.0) < 1e-6
            assert abs(_dot(u_axis, v_axis)) < 1e-6
            assert abs(_dot(u_axis, cap_normal)) < 1e-6
            assert abs(_dot(v_axis, cap_normal)) < 1e-6
            uv_cross = _cross(u_axis, v_axis)
            assert _dot(uv_cross, cap_normal) > 0.9999

            # Оба треугольника (v0,v1,v2) и (v3,v4,v5) ориентированы CCW вдоль cap_normal
            n1 = _norm(_cross(_sub(verts[1], verts[0]), _sub(verts[2], verts[0])))
            n2 = _norm(_cross(_sub(verts[4], verts[3]), _sub(verts[5], verts[3])))
            assert _dot(n1, cap_normal) > 0.9999
            assert _dot(n2, cap_normal) > 0.9999

            # Покрытие расширенного AABB по двум осям в плоскости среза
            for k in range(3):
                if k == axis_idx:
                    continue
                coords = [v[k] for v in verts]
                assert abs(min(coords) - (mn[k] - pad)) < 1e-6
                assert abs(max(coords) - (mx[k] + pad)) < 1e-6


def test_compute_section_cap_style_orientations_and_thickness():
    vert = SimpleNamespace(
        width=16.0, height=720.0, depth=560.0,
        thickness_axis=0, thickness=16.0, color=(0.86, 0.82, 0.74),
    )
    horiz = SimpleNamespace(
        width=600.0, height=16.0, depth=560.0,
        thickness_axis=1, thickness=16.0, color=(0.86, 0.82, 0.74),
    )
    hdf = SimpleNamespace(
        width=596.0, height=716.0, depth=4.0,
        thickness_axis=2, thickness=4.0, color=(0.90, 0.89, 0.86),
    )
    slab = SimpleNamespace(
        width=1200.0, height=38.0, depth=600.0,
        thickness_axis=1, thickness=38.0, color=(0.76, 0.70, 0.62),
    )

    s_v0 = glmath.compute_section_cap_style(vert, panel_index=0)
    s_v1 = glmath.compute_section_cap_style(vert, panel_index=1)
    s_h0 = glmath.compute_section_cap_style(horiz, panel_index=0)
    s_hdf = glmath.compute_section_cap_style(hdf, panel_index=0)
    s_slab = glmath.compute_section_cap_style(slab, panel_index=0)

    # Взаимно перпендикулярные и соседние детали имеют различимые углы штриховки
    assert s_v0["hatch_angle_deg"] != s_h0["hatch_angle_deg"]
    assert s_v0["hatch_angle_deg"] != s_hdf["hatch_angle_deg"]
    assert s_h0["hatch_angle_deg"] != s_hdf["hatch_angle_deg"]
    assert s_v0["hatch_angle_deg"] != s_v1["hatch_angle_deg"]

    # Шаг штриховки зависит от толщины материала: ХДФ < ЛДСП < столешница
    assert s_hdf["hatch_spacing_mm"] < s_v0["hatch_spacing_mm"] < s_slab["hatch_spacing_mm"]
    assert abs(math.hypot(*s_v0["hatch_dir"]) - 1.0) < 1e-6


def test_compute_section_cap_style_dark_vs_light_contrast_and_states():
    light = SimpleNamespace(
        width=16.0, height=720.0, depth=560.0,
        thickness_axis=0, thickness=16.0, color=(0.94, 0.94, 0.92),
    )
    dark = SimpleNamespace(
        width=16.0, height=720.0, depth=560.0,
        thickness_axis=0, thickness=16.0, color=(0.08, 0.08, 0.10),
    )

    s_light = glmath.compute_section_cap_style(light)
    s_dark = glmath.compute_section_cap_style(dark)

    # На светлом материале штриховка темнее подложки, на тёмном (Антрацит/Венге) — светлее
    assert _luma(s_light["hatch_color"]) < _luma(s_light["cap_color"]) - 0.15
    assert _luma(s_dark["hatch_color"]) > _luma(s_dark["cap_color"]) + 0.12

    # Выделение и коллизия имеют отдельные акцентные цвета среза
    s_sel = glmath.compute_section_cap_style(light, is_selected=True)
    s_col = glmath.compute_section_cap_style(light, is_colliding=True)
    assert s_sel["cap_color"] != s_light["cap_color"]
    assert s_col["cap_color"] != s_sel["cap_color"]
    assert s_col["cap_color"][0] > s_col["cap_color"][1] * 2.0


def test_stencil_section_cap_wired_in_main_viewport_and_window():
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    vp_src = (ROOT / "ui" / "viewport.py").read_text(encoding="utf-8")
    mw_src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")

    # 8-bit stencil buffer выделен в обоих QSurfaceFormat
    assert "setStencilBufferSize(8)" in main_src
    assert "setStencilBufferSize(8)" in vp_src

    # В OpenGL 3.3 Core GL_STENCIL_BITS удалён (GL_INVALID_ENUM) — защита от регрессии по AST
    vp_tree = ast.parse(vp_src)
    vp_refs = {
        node.id for node in ast.walk(vp_tree) if isinstance(node, ast.Name)
    } | {
        alias.name
        for node in ast.walk(vp_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "GL_STENCIL_BITS" not in vp_refs, "GL_STENCIL_BITS недопустим в OpenGL 3.3 Core Profile"

    # Шейдеры, Core 3.3 FBO-детект stencil и 2-проходная stencil-логика присутствуют в viewport.py
    for token in (
        "_SECTION_MASK_VS",
        "_SECTION_MASK_FS",
        "_SECTION_CAP_VS",
        "_SECTION_CAP_FS",
        "GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE",
        "glGetFramebufferAttachmentParameteriv",
        "glClearStencil",
        "glFrontFace",
        "GL_STENCIL_BUFFER_BIT",
        "GL_INCR_WRAP",
        "GL_DECR_WRAP",
        "glStencilOpSeparate",
        "dFdx(",
        "dFdy(",
        "def _detect_stencil_buffer",
        "def toggle_section_cap",
        "def _draw_section_caps",
    ):
        assert token in vp_src, f"Отсутствует ожидаемый токен {token} в ui/viewport.py"

    # Кнопка переключения заглушки на панели инструментов MainWindow
    assert "section_cap_btn" in mw_src
    assert "def _on_section_cap_toggled" in mw_src

    # Все изменённые файлы корректно парсятся в AST
    for rel in ("main.py", "core/glmath.py", "ui/viewport.py", "ui/main_window.py"):
        ast.parse((ROOT / rel).read_text(encoding="utf-8"))
