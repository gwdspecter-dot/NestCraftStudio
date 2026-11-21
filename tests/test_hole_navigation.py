# -*- coding: utf-8 -*-
"""Тесты 3D-навигации от отверстия к стыку (JointRecord) или ассоциации (AssocRef)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from core import glmath
from core.assoc import AssocRef, capture_face_hint, freeze_assoc_ref_state
from core.hole_nav import (
    classify_hole_owner,
    collect_owner_holes,
    describe_hole_hit,
    hole_world_segment,
    pick_hole_at_ray,
    ray_segment_closest,
)
from core.joint import JointRecord
from models.panel import Block, Panel
from ui.panels.assoc_panel import AssocDock
from ui.panels.joints_panel import JointsDock

ROOT = Path(__file__).resolve().parent.parent


def _make_scene_block() -> tuple[Block, Panel, Panel, JointRecord, AssocRef]:
    """Блок с боковиной и полкой, одним стыком (конфирмат), одной ассоциацией и ручным отверстием."""
    side = Panel(
        name="Боковина",
        x=0.0,
        y=0.0,
        z=0.0,
        width=16.0,
        height=720.0,
        depth=560.0,
        uid="nav-side",
        rebuild=False,
    )
    shelf = Panel(
        name="Полка",
        x=16.0,
        y=352.0,
        z=0.0,
        width=568.0,
        height=16.0,
        depth=560.0,
        uid="nav-shelf",
        rebuild=False,
    )
    block = Block(name="Шкаф", uid="nav-blk")
    block.add_panel(side)
    block.add_panel(shelf)

    jr = JointRecord(
        panel_a_uid=side.uid,
        panel_b_uid=shelf.uid,
        preset_id="confirmat_2",
    )
    block.add_joint(jr, apply=True)

    ref = AssocRef(
        target_uid=shelf.uid,
        source_uid=side.uid,
        source_face="X+",
        anchor="center",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
        face_hint=capture_face_hint(side, "X+"),
    )
    block.add_assoc_ref(ref, apply=True)

    # Ручное отверстие вдали от стыка и ассоциации
    shelf.holes.append((400.0, 0.0, 280.0, 2.5, 12.0, "Y"))
    return block, side, shelf, jr, ref


def test_classify_hole_owner_types():
    assert classify_hole_owner((10.0, 20.0, 30.0, 4.0, 12.0, "X")) == ("manual", "")
    assert classify_hole_owner((10.0, 20.0, 30.0, 4.0, 12.0, "X", "")) == ("manual", "")
    assert classify_hole_owner((10.0, 20.0, 30.0, 4.0, 12.0, "X", "j-123")) == ("joint", "j-123")
    assert classify_hole_owner((10.0, 20.0, 30.0, 4.0, 12.0, "X", "a:assoc-9")) == ("assoc", "assoc-9")


def test_hole_world_segment_with_rotation():
    p = Panel(name="P", x=100.0, y=50.0, z=0.0, width=100.0, height=200.0, depth=16.0, rebuild=False)
    p.rz = 90.0
    hole = (0.0, 0.0, 8.0, 4.0, 20.0, "X")
    p0, p1, rad = hole_world_segment(p, hole)
    assert abs(rad - 4.0) < 1e-6
    seg = p1 - p0
    # Локальная ось +X при повороте на +90° вокруг Z направлена вдоль +Y (или -Y в зависимости от знака поворота)
    assert abs(float(np.linalg.norm(seg)) - 20.0) < 1e-4
    assert abs(float(seg[0])) < 1e-4
    assert abs(abs(float(seg[1])) - 20.0) < 1e-4


def test_ray_segment_closest_exact_and_parallel():
    seg_p0 = np.array([10.0, 0.0, 0.0], dtype=float)
    seg_p1 = np.array([10.0, 20.0, 0.0], dtype=float)

    # Прямое попадание в середину отрезка
    dist, t, s = ray_segment_closest(
        np.array([10.0, 10.0, 100.0]),
        np.array([0.0, 0.0, -1.0]),
        seg_p0,
        seg_p1,
    )
    assert dist < 1e-6
    assert abs(t - 100.0) < 1e-6
    assert abs(s - 0.5) < 1e-6

    # Промах на 5 мм по X
    dist2, t2, _s2 = ray_segment_closest(
        np.array([15.0, 10.0, 100.0]),
        np.array([0.0, 0.0, -1.0]),
        seg_p0,
        seg_p1,
    )
    assert abs(dist2 - 5.0) < 1e-6
    assert abs(t2 - 100.0) < 1e-6

    # Луч параллелен отрезку оси отверстия
    dist3, t3, _s3 = ray_segment_closest(
        np.array([12.0, -30.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        seg_p0,
        seg_p1,
    )
    assert abs(dist3 - 2.0) < 1e-6
    assert abs(t3 - 30.0) < 1e-6


def test_pick_hole_at_ray_identifies_joint_assoc_manual_and_occlusion():
    block, side, shelf, jr, ref = _make_scene_block()

    # 1. Находим отверстие ассоциации на полке (луч сверху вниз вдоль -Y, мимо передних конфирматов на z=510)
    assoc_holes = collect_owner_holes(block, "assoc", ref.uid)
    assert len(assoc_holes) == 1
    p_a, h_a = assoc_holes[0]
    ap0, ap1, _ = hole_world_segment(p_a, h_a)
    amid = 0.5 * (ap0 + ap1)

    hit_a = pick_hole_at_ray(
        [block],
        amid + np.array([0.0, 500.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
    )
    assert hit_a is not None
    assert hit_a.kind == "assoc"
    assert hit_a.owner_uid == ref.uid
    assert hit_a.panel is shelf

    # 2. Находим отверстие стыка на боковине и собираем всю группу стыка
    joint_holes = collect_owner_holes(block, "joint", jr.uid)
    assert len(joint_holes) >= 4  # 2 конфирмата × 2 детали
    p_j, h_j = joint_holes[0]
    jp0, jp1, _ = hole_world_segment(p_j, h_j)
    jmid = 0.5 * (jp0 + jp1)

    hit_j = pick_hole_at_ray(
        [block],
        jmid + np.array([-300.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    assert hit_j is not None
    assert hit_j.kind == "joint"
    assert hit_j.owner_uid == jr.uid

    # 3. Защита от перекрытия: если передняя панель ближе (occluded_t = 100), дальнее отверстие (t ~ 300) отсекается
    blocked = pick_hole_at_ray(
        [block],
        jmid + np.array([-300.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        occluded_t=100.0,
        front_panel=shelf,
        ignore_occlusion=False,
    )
    assert blocked is None or blocked.panel is shelf

    # В режиме X-Ray / Wireframe (ignore_occlusion=True) дальнее отверстие выбирается свободно
    xray_hit = pick_hole_at_ray(
        [block],
        jmid + np.array([-300.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        occluded_t=100.0,
        front_panel=shelf,
        ignore_occlusion=True,
    )
    assert xray_hit is not None
    assert xray_hit.kind == "joint"

    # 4. Плоскость сечения отсекает отверстия за ней (-x - 500 >= 0 не выполняется для x > 0)
    clipped = pick_hole_at_ray(
        [block],
        amid + np.array([0.0, 500.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
        section_plane=(-1.0, 0.0, 0.0, -500.0),
    )
    assert clipped is None


def test_pick_hole_screen_space_halo_and_describe():
    block, side, shelf, jr, ref = _make_scene_block()

    # Строим реальную перспективную камеру (как в Viewport3D), смотрящую на ручное отверстие полки (416, 358, 280)
    target_pt = np.array([416.0, 358.0, 280.0], dtype=float)
    eye = np.array([416.0, 358.0, 900.0], dtype=float)
    proj = glmath.perspective(45.0, 800.0 / 600.0, 10.0, 5000.0)
    view = glmath.translate(-float(eye[0]), -float(eye[1]), -float(eye[2]))
    mvp = proj @ view
    vp = (0, 0, 800, 600)

    wx, wy, _wz = glmath.project(float(target_pt[0]), float(target_pt[1]), float(target_pt[2]), mvp, vp)
    sx = float(wx)
    sy = float(600.0 - wy)

    # Кликаем с небольшим промахом в 6 px — экранный ореол должен поймать ручное отверстие
    ray_dir = (target_pt - eye) / float(np.linalg.norm(target_pt - eye))
    hit_m = pick_hole_at_ray(
        [block],
        eye,
        ray_dir,
        mvp=mvp,
        viewport=vp,
        mouse_xy=(sx + 6.0, sy - 4.0),
        dpr=1.0,
        max_screen_px=12.0,
    )
    assert hit_m is not None
    assert hit_m.kind == "manual"
    assert hit_m.panel is shelf
    assert hit_m.screen_mid is not None
    desc_m = describe_hole_hit(hit_m)
    assert "Отверстие" in desc_m and "Ø5" in desc_m
    desc_m_full = describe_hole_hit(hit_m, compact=False)
    assert "Полка" in desc_m_full and "Ø5" in desc_m_full

    # Проверяем подписи для joint и assoc (включая fixed), без эмодзи и лишних подсказок
    j_panel, j_hole = collect_owner_holes(block, "joint", jr.uid)[0]
    jp0, jp1, _ = hole_world_segment(j_panel, j_hole)
    j_hit = pick_hole_at_ray([block], 0.5 * (jp0 + jp1) + np.array([0, 200.0, 0.0]), np.array([0, -1.0, 0.0]))
    assert j_hit is not None
    j_desc = describe_hole_hit(j_hit)
    assert "Стык" in j_desc

    a_panel, a_hole = collect_owner_holes(block, "assoc", ref.uid)[0]
    ap0, ap1, _ = hole_world_segment(a_panel, a_hole)
    a_hit = pick_hole_at_ray([block], 0.5 * (ap0 + ap1) + np.array([0, 200.0, 0.0]), np.array([0, -1.0, 0.0]))
    assert a_hit is not None
    a_desc = describe_hole_hit(a_hit)
    assert "Ассоциация" in a_desc

    frozen = AssocRef.from_dict(freeze_assoc_ref_state(block, ref))
    block.assoc_refs = [frozen]
    f_desc = describe_hole_hit(a_hit)
    assert "фикс." in f_desc

    for txt in (desc_m, desc_m_full, j_desc, a_desc, f_desc):
        for bad in ("🔩", "🔗", "📌", "○", "⚠", "двойной клик"):
            assert bad not in txt, f"Unexpected {bad!r} in {txt!r}"


def test_headless_navigation_to_joints_and_assoc_docks():
    """Проверяет сквозную навигацию от HoleHit к выбору записи в JointsDock и AssocDock."""
    block, _side, _shelf, jr, ref = _make_scene_block()

    joints_dock = JointsDock()
    joints_dock.load_joints([block])
    assoc_dock = AssocDock()
    assoc_dock.load_assocs([block])

    selected_joints: list[str] = []
    selected_assocs: list[str] = []
    joints_dock.joint_selected.connect(lambda _b, uid: selected_joints.append(uid))
    assoc_dock.assoc_selected.connect(lambda _b, uid: selected_assocs.append(uid))

    assert joints_dock.select_joint_by_uid(jr.uid) is True
    assert joints_dock.current_joint_ref()[1] == jr.uid

    assert assoc_dock.select_assoc_by_uid(ref.uid) is True
    assert assoc_dock.current_assoc_ref()[1] == ref.uid


def test_viewport_and_main_window_wire_hole_navigation():
    """AST-проверка подключения сигналов/обработчиков 3D-навигации и единого стиля 2D-оверлеев."""
    vp_src = (ROOT / "ui" / "viewport.py").read_text(encoding="utf-8")
    mw_src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    vp_tree = ast.parse(vp_src, filename="ui/viewport.py")
    mw_tree = ast.parse(mw_src, filename="ui/main_window.py")

    vp_defs = {n.name for n in ast.walk(vp_tree) if isinstance(n, ast.FunctionDef)}
    mw_defs = {n.name for n in ast.walk(mw_tree) if isinstance(n, ast.FunctionDef)}

    for fn in (
        "pick_hole_at_screen",
        "set_active_hole_owner",
        "_draw_highlighted_holes",
        "_draw_hole_hover_overlay",
        "_overlay_palette",
        "_show_hole_context_menu",
        "mouseDoubleClickEvent",
    ):
        assert fn in vp_defs, f"Viewport3D missing {fn}"

    assert "_draw_live_collisions_overlay" not in vp_defs
    for dark_pill in ("QColor(69, 10, 10", "QColor(22, 26, 34", "QColor(15, 23, 42", "⚡ Врезание"):
        assert dark_pill not in vp_src

    for fn in (
        "navigate_to_hole_owner",
        "_on_hole_navigated",
        "_on_hole_edit_requested",
    ):
        assert fn in mw_defs, f"MainWindow missing {fn}"

    assert "hole_navigated" in vp_src
    assert "hole_edit_requested" in vp_src
    assert "hole_navigated" in mw_src
    assert "hole_edit_requested" in mw_src

