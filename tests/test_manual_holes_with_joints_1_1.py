"""Ручные отверстия ремапятся при смене габаритов даже если в блоке есть стыки (ревизия 4 §1.1)."""

from __future__ import annotations

from core.joint import JointRecord, apply_joints, extract_manual_holes
from models.panel import ParametricCabinet


def _role(cab: ParametricCabinet, role: str):
    for p in cab.panels:
        if getattr(p, "role", "") == role:
            return p
    raise AssertionError(f"role {role!r} not found")


def test_manual_hole_follows_edge_with_joints():
    cab = ParametricCabinet(
        "Шкаф",
        width=600,
        height=720,
        depth=560,
        thickness=16,
        shelves_count=1,
        has_facade=False,
    )
    shelf = _role(cab, "shelf_0")
    left = _role(cab, "left")
    # ручное отверстие у правого края полки (ширина ~568)
    shelf.holes = [(500.0, 0.0, 250.0, 4.0, 12.0, "Y")]
    shelf.joint_hole_map = {}

    cab.joints = [
        JointRecord(
            uid="jr-shelf-left",
            panel_a_uid=left.uid,
            panel_b_uid=shelf.uid,
            preset_id="confirmat_3",
        )
    ]
    apply_joints(cab, rebuild_geometry=False)

    # после стыка: ручное + стыковые
    assert len(extract_manual_holes(shelf)) == 1
    assert len(shelf.holes) > 1

    cab.width = 800.0
    cab.rebuild()

    shelf2 = _role(cab, "shelf_0")
    manuals = extract_manual_holes(shelf2)
    assert len(manuals) == 1
    hx = float(manuals[0][0])
    # 500 у правого края 568 → при ширине полки ~768 ожидаем ~700
    assert abs(hx - 700.0) < 1.0, f"manual hole x={hx}, expected ~700"


def test_manual_hole_not_outside_after_shrink_with_joints():
    cab = ParametricCabinet(
        "Шкаф",
        width=600,
        height=720,
        depth=560,
        thickness=16,
        shelves_count=1,
        has_facade=False,
    )
    shelf = _role(cab, "shelf_0")
    left = _role(cab, "left")
    shelf.holes = [(500.0, 0.0, 250.0, 4.0, 12.0, "Y")]
    cab.joints = [
        JointRecord(
            uid="jr-1",
            panel_a_uid=left.uid,
            panel_b_uid=shelf.uid,
            preset_id="confirmat_3",
        )
    ]
    apply_joints(cab, rebuild_geometry=False)

    cab.width = 400.0
    cab.rebuild()
    shelf2 = _role(cab, "shelf_0")
    manuals = extract_manual_holes(shelf2)
    assert len(manuals) == 1
    hx = float(manuals[0][0])
    # полка ~368 мм — отверстие не должно остаться на 500
    assert hx < float(shelf2.width) + 1e-6
    assert abs(hx - 300.0) < 5.0, f"manual hole x={hx} after shrink"
