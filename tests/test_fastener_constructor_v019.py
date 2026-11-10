"""Тесты сквозной связки конструктора крепежа (D1, D2, H) с JointRecord и сверлением (v0.0.19)."""

from __future__ import annotations

from core.fastener_constructor import (
    ConfirmatParams,
    load_confirmat_rows,
    reset_confirmat_rows,
    save_confirmat_rows,
)
from core.joint import JointRecord, apply_joints, find_joint, make_joint_holes
from models.panel import Block, Panel


def test_confirmat_params_edge_depth_and_selected_dict():
    p_std = ConfirmatParams("Конфирмат 7×50 мм, Zn", d1=8.0, d2=5.0, h=50.0, h1=0.0)
    assert abs(p_std.edge_depth(16.0) - 38.0) < 1e-6
    sel = p_std.to_selected_fastener_dict()
    assert sel["drill_face_diameter"] == 8.0
    assert sel["drill_edge_diameter"] == 5.0
    assert sel["drill_edge_depth"] == 38.0

    # Явно заданная глубина H1 переопределяет формулу от H
    p_custom = ConfirmatParams("Конфирмат 6.4×60", d1=7.5, d2=4.5, h=60.0, h1=44.0)
    assert abs(p_custom.edge_depth(16.0) - 44.0) < 1e-6
    sel2 = p_custom.to_selected_fastener_dict()
    assert sel2["drill_face_diameter"] == 7.5
    assert sel2["drill_edge_diameter"] == 4.5
    assert sel2["drill_edge_depth"] == 44.0


def test_confirmat_rows_persistence_roundtrip(tmp_path):
    store = tmp_path / "fastener_rows.json"
    rows = [
        ConfirmatParams("Конфирмат 7×50 мм, Zn", 8.0, 5.0, 50.0, 0.0),
        ConfirmatParams("Евровинт усиленный 7×70", 8.5, 5.5, 70.0, 52.0),
    ]
    save_confirmat_rows(rows, selected_index=1, custom_path=store)
    loaded, sel_idx = load_confirmat_rows(custom_path=store)
    assert sel_idx == 1
    assert len(loaded) == 2
    assert loaded[1].name == "Евровинт усиленный 7×70"
    assert abs(loaded[1].d1 - 8.5) < 1e-6
    assert abs(loaded[1].d2 - 5.5) < 1e-6
    assert abs(loaded[1].h - 70.0) < 1e-6
    assert abs(loaded[1].h1 - 52.0) < 1e-6

    reset_confirmat_rows(custom_path=store)
    assert not store.exists()


def test_make_joint_holes_honors_custom_d1_d2_and_edge_depth():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    j = find_joint(left, shelf)
    assert j is not None

    # Даже при переданном каталожном fastener_id="fst_conf_7x50" кастомные D1/D2/H имеют приоритет
    ha, hb = make_joint_holes(
        j,
        [16.0, 308.0, 280.0],
        diameter=8.4,
        depth=46.0,
        fastener_id="fst_conf_7x50",
        face_diameter=8.4,
        edge_diameter=4.8,
        edge_depth=46.0,
    )
    # left — сверление в пласть (сквозное на толщину 16 мм, радиус = 8.4 / 2 = 4.2)
    assert abs(ha[3] - 4.2) < 1e-6
    assert abs(ha[4] - 16.0) < 1e-6
    # shelf — сверление в торец (радиус = 4.8 / 2 = 2.4, глубина = 46.0)
    assert abs(hb[3] - 2.4) < 1e-6
    assert abs(hb[4] - 46.0) < 1e-6


def test_apply_joints_preserves_custom_constructor_params_across_serialization():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    left.uid = "u-left"
    shelf.uid = "u-shelf"

    chosen = ConfirmatParams("Кастом 9×60", d1=9.0, d2=5.6, h=60.0, h1=45.0).to_selected_fastener_dict()
    rec = JointRecord(
        uid="jr-custom",
        panel_a_uid="u-left",
        panel_b_uid="u-shelf",
        preset_id="confirmat_3",
        fastener_id="fst_conf_7x50",
        params={
            "count": 3,
            "margin": 50.0,
            "d1": chosen["d1"],
            "d2": chosen["d2"],
            "h": chosen["h"],
            "h1": chosen["h1"],
            "drill_face_diameter": chosen["drill_face_diameter"],
            "drill_edge_diameter": chosen["drill_edge_diameter"],
            "drill_edge_depth": chosen["drill_edge_depth"],
        },
    )
    # Проверка round-trip сериализации JointRecord
    rec_restored = JointRecord.from_dict(rec.to_dict())

    b = Block("Cab")
    b.add_panel(left)
    b.add_panel(shelf)
    b.joints = [rec_restored]
    apply_joints(b, rebuild_geometry=False)

    assert len(left.holes) == 3
    assert len(shelf.holes) == 3
    for h_face in left.holes:
        assert abs(h_face[3] - 4.5) < 1e-6  # D1=9.0 -> radius=4.5
        assert abs(h_face[4] - 16.0) < 1e-6
    for h_edge in shelf.holes:
        assert abs(h_edge[3] - 2.8) < 1e-6  # D2=5.6 -> radius=2.8
        assert abs(h_edge[4] - 45.0) < 1e-6  # H1=45.0
