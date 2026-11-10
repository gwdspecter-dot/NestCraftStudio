"""Ctrl+C/V: клон блоков со стыками и сдвиг по якорю."""

from __future__ import annotations

from core.clipboard import capture_selection, set_anchor, materialize
from core.joint import JointRecord, apply_joints
from models.panel import Block, Panel


def test_clone_block_with_joints_remaps_uids():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    left.uid = "uid-left"
    shelf.uid = "uid-shelf"
    b = Block("Cab")
    b.add_panel(left)
    b.add_panel(shelf)
    b.selected = True
    b.joints = [
        JointRecord(
            uid="j1",
            panel_a_uid="uid-left",
            panel_b_uid="uid-shelf",
            preset_id="confirmat_3",
        )
    ]
    apply_joints(b, rebuild_geometry=False)

    payload = capture_selection([b])
    assert payload is not None
    assert payload.count_blocks == 1
    set_anchor(payload, 0.0, 0.0, 0.0)
    clones = materialize(payload, (200.0, 50.0, 10.0))
    assert len(clones) == 1
    cb = clones[0]
    assert len(cb.panels) == 2
    old_uids = {"uid-left", "uid-shelf"}
    new_uids = {p.uid for p in cb.panels}
    assert new_uids.isdisjoint(old_uids)
    assert len(cb.joints) == 1
    jr = cb.joints[0]
    assert jr.panel_a_uid in new_uids
    assert jr.panel_b_uid in new_uids
    xs = sorted(p.x for p in cb.panels)
    assert abs(xs[0] - 200.0) < 0.1
    assert abs(xs[1] - 216.0) < 0.1
    # Новый uid стыка должен быть единым в JointRecord, joint_hole_map и 7-м поле holes
    assert jr.uid != "j1"
    for p in cb.panels:
        assert jr.uid in p.joint_hole_map
        assert len(p.holes) == 3
        for h in p.holes:
            assert len(h) >= 7 and h[6] == jr.uid
        for jh in p.joint_hole_map[jr.uid]:
            assert len(jh) >= 7 and jh[6] == jr.uid

    # Повторный apply_joints не должен дублировать отверстия
    apply_joints(cb, rebuild_geometry=False)
    for p in cb.panels:
        assert len(p.holes) == 3


def test_clone_block_preserves_manual_and_offset_joint_holes_without_duplication():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    left.uid = "uid-left"
    shelf.uid = "uid-shelf"
    # Одно ручное отверстие (6 полей) на левой боковине
    left.holes.append((0.0, 100.0, 100.0, 2.5, 12.0, "X"))

    b = Block("Cab")
    b.add_panel(left)
    b.add_panel(shelf)
    b.selected = True
    b.joints = [
        JointRecord(
            uid="j-offset",
            panel_a_uid="uid-left",
            panel_b_uid="uid-shelf",
            preset_id="confirmat_3",
            params={"center_offset": 25.0, "count": 3, "margin": 50.0},
        )
    ]
    apply_joints(b, rebuild_geometry=False)
    assert len(left.holes) == 4  # 1 ручное + 3 по стыку
    assert len(shelf.holes) == 3

    payload = capture_selection([b])
    assert payload is not None
    set_anchor(payload, 0.0, 0.0, 0.0)
    clones = materialize(payload, (300.0, 0.0, 0.0))
    cb = clones[0]
    c_left = next(p for p in cb.panels if p.name == "L")
    c_shelf = next(p for p in cb.panels if p.name == "S")
    assert len(c_left.holes) == 4
    assert len(c_shelf.holes) == 3

    # Ещё один пересчёт стыков на клоне не меняет количество и координаты отверстий
    before_left = list(c_left.holes)
    apply_joints(cb, rebuild_geometry=False)
    assert len(c_left.holes) == 4
    assert len(c_shelf.holes) == 3
    assert list(c_left.holes) == before_left


def test_capture_loose_panels_only():
    p1 = Panel("A", 0, 0, 0, 100, 16, 100, rebuild=False)
    p2 = Panel("B", 200, 0, 0, 100, 16, 100, rebuild=False)
    p1.selected = True
    p2.selected = False
    b = Block("B")
    b.add_panel(p1)
    b.add_panel(p2)
    payload = capture_selection([b])
    assert payload is not None
    assert payload.count_panels == 1
    assert payload.count_blocks == 0
    set_anchor(payload, 0, 0, 0)
    out = materialize(payload, (10, 0, 0))
    assert len(out) == 1
    assert len(out[0].panels) == 1
    assert abs(out[0].panels[0].x - 10.0) < 0.1


def test_copy_single_drilled_loose_panel_converts_orphan_joint_holes_to_manual():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    left.uid = "uid-left"
    shelf.uid = "uid-shelf"
    b = Block("Cab")
    b.add_panel(left)
    b.add_panel(shelf)
    b.joints = [
        JointRecord(uid="j1", panel_a_uid="uid-left", panel_b_uid="uid-shelf", preset_id="confirmat_3")
    ]
    apply_joints(b, rebuild_geometry=False)
    assert len(left.holes) == 3

    # Копируем ТОЛЬКО левую боковину без полки
    left.selected = True
    shelf.selected = False
    payload = capture_selection([b])
    assert payload is not None
    assert payload.count_panels == 1
    assert len(payload.free_joint_dicts) == 0

    set_anchor(payload, 0.0, 0.0, 0.0)
    clones = materialize(payload, (100.0, 0.0, 0.0))
    c_block = clones[0]
    c_left = c_block.panels[0]
    assert len(c_left.holes) == 3
    # Осиротевшие отверстия стыка должны стать 6-элементными (ручными) и сохраняться при apply_joints
    assert all(len(h) == 6 for h in c_left.holes)
    assert c_left.joint_hole_map == {}
    apply_joints(c_block, rebuild_geometry=False)
    assert len(c_left.holes) == 3


def test_rotated_panel_paste_preview_corners():
    from pathlib import Path
    from core.clipboard import panel_dict_preview_corners

    p_rot = Panel("Rot", 10, 20, 30, 200, 16, 100, rz=45.0, rebuild=False)
    p_rot.selected = True
    b = Block("B")
    b.add_panel(p_rot)
    payload = capture_selection([b])
    assert payload is not None
    pd = payload.free_panel_dicts[0]

    corners = panel_dict_preview_corners(pd, dx=50.0, dy=-10.0, dz=5.0)
    assert len(corners) == 8

    expected_panel = Panel("Rot", 60, 10, 35, 200, 16, 100, rz=45.0, rebuild=False)
    expected_corners = expected_panel.world_corners()
    for c_actual, c_exp in zip(corners, expected_corners):
        for a, e in zip(c_actual, c_exp):
            assert abs(a - e) < 1e-6

    root = Path(__file__).resolve().parents[1]
    mw_src = (root / "ui" / "main_window.py").read_text(encoding="utf-8")
    vp_src = (root / "ui" / "viewport.py").read_text(encoding="utf-8")
    assert "Копировать (Ctrl+C)" in mw_src
    assert "Вставить (Ctrl+V)" in mw_src
    assert "def copy_selection_action" in mw_src
    assert "def paste_selection_action" in mw_src
    assert "_draw_oriented_box_wireframe" in vp_src
    assert "panel_dict_preview_corners" in vp_src
