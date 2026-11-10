"""Сверление по правилам Fastener из каталога (план §2.4)."""

from types import SimpleNamespace
from core.joint import _hole_dims_for_fastener, is_face_drilling


class P:
    def __init__(self, w, h, d):
        self.width, self.height, self.depth = w, h, d


def test_confirmat_face_through_from_catalog():
    panel = P(16, 720, 560)  # thickness on X
    # face drill along X into side panel
    fst = SimpleNamespace(
        id="fst_conf_7x50",
        drill_face_diameter=7.0,
        drill_face_depth=0,
        drill_edge_diameter=5.0,
        drill_edge_depth=38.0,
        drill_through=True,
        diameter_mm=7.0,
        min_panel_thickness=15,
        max_panel_thickness=19,
    )
    # axis X on 16mm panel → face
    assert is_face_drilling(panel, "X")
    dia, dep = _hole_dims_for_fastener(panel, "X", 7.0, 42.0, fastener=fst)
    assert abs(dia - 7.0) < 1e-9
    assert abs(dep - 16.0) < 1e-9  # through = thickness


def test_confirmat_edge_from_catalog():
    panel = P(568, 16, 560)  # thickness on Y; edge drill along X
    fst = SimpleNamespace(
        id="fst_conf_7x50",
        drill_face_diameter=7.0,
        drill_face_depth=0,
        drill_edge_diameter=5.0,
        drill_edge_depth=38.0,
        drill_through=True,
        diameter_mm=7.0,
        min_panel_thickness=0,
        max_panel_thickness=0,
    )
    assert not is_face_drilling(panel, "X")
    dia, dep = _hole_dims_for_fastener(panel, "X", 7.0, 42.0, fastener=fst)
    assert abs(dia - 5.0) < 1e-9
    assert abs(dep - 38.0) < 1e-9


def test_dowel_face_depth_from_catalog():
    panel = P(16, 720, 560)
    fst = SimpleNamespace(
        id="fst_dowel_8x30",
        drill_face_diameter=8.0,
        drill_face_depth=12.0,
        drill_edge_diameter=8.0,
        drill_edge_depth=18.0,
        drill_through=False,
        diameter_mm=8.0,
        min_panel_thickness=0,
        max_panel_thickness=0,
    )
    dia, dep = _hole_dims_for_fastener(panel, "X", 8.0, 24.0, fastener=fst)
    assert abs(dia - 8.0) < 1e-9
    assert abs(dep - 12.0) < 1e-9  # not hardcoded thickness-2


def test_legacy_without_fastener():
    panel = P(16, 720, 560)
    dia, dep = _hole_dims_for_fastener(panel, "X", 7.0, 42.0, fastener=None)
    assert abs(dia - 7.0) < 1e-9
    assert abs(dep - 16.0) < 1e-9


def test_fastener_thickness_incompatibility_collected_as_issue(make_panel):
    """Пункт 1.8: несовместимость крепежа с min/max_panel_thickness собирается в Issue и check_scene_issues."""
    from core.issues import check_scene_issues
    from core.joint import find_joint, make_joint_holes
    from models.panel import Block

    thin = make_panel(name="Тонкая боковина", x=0, y=0, z=0, width=10, height=500, depth=400)
    thin.thickness_axis = 0
    shelf = make_panel(name="Полка", x=10, y=0, z=0, width=500, height=16, depth=400)
    shelf.thickness_axis = 1

    fst = SimpleNamespace(
        id="fst_conf_7x50",
        display_name="Конфирмат 7×50",
        drill_face_diameter=7.0,
        drill_face_depth=0,
        drill_edge_diameter=5.0,
        drill_edge_depth=38.0,
        drill_through=True,
        diameter_mm=7.0,
        min_panel_thickness=15,
        max_panel_thickness=19,
    )

    j = find_joint(thin, shelf, tol=2.5)
    assert j is not None

    collected = []
    ha, hb = make_joint_holes(j, [10.0, 8.0, 200.0], fastener=fst, issues=collected)
    thin.holes.append(ha)
    shelf.holes.append(hb)

    assert len(collected) == 1
    assert collected[0].code == "fastener_thickness_min"
    assert collected[0].panel_uid == thin.uid
    assert "Тонкая боковина" in collected[0].message
    assert "10" in collected[0].message and "15" in collected[0].message

    blk = Block("Корпус", "1", "01.00")
    blk.panels = [thin, shelf]
    scene_issues = check_scene_issues([blk])
    assert any(
        iss.code == "fastener_thickness_min" and iss.panel_uid == thin.uid
        for iss in scene_issues
    )

