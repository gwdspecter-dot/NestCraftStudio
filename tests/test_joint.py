"""find_joint, make_joint_holes, joint_array_points."""

import numpy as np

from core.joint import (
    _overlap_1d,
    find_joint,
    make_joint_holes,
    joint_array_points,
    clamp_joint_point,
)


class FakePanel:
    def __init__(self, x, y, z, w, h, d, grooves=None):
        self.x, self.y, self.z = x, y, z
        self.width, self.height, self.depth = w, h, d
        self.grooves = grooves or []
        self.holes = []

    def has_rotation(self):
        return False

    def check_hole_groove_collision(self, hole):
        if not self.grooves or len(hole) < 6:
            return False
        hx, hy, hz, radius, length, axis = hole
        if axis == "X":
            h_min = (hx, hy - radius, hz - radius)
            h_max = (hx + length, hy + radius, hz + radius)
        elif axis == "Y":
            h_min = (hx - radius, hy, hz - radius)
            h_max = (hx + radius, hy + length, hz + radius)
        else:
            h_min = (hx - radius, hy - radius, hz)
            h_max = (hx + radius, hy + radius, hz + length)
        for g in self.grooves:
            gx, gy, gz, gw, gh, gd = g
            g_max = (gx + gw, gy + gh, gz + gd)
            if (h_min[0] < g_max[0] and h_max[0] > gx and
                h_min[1] < g_max[1] and h_max[1] > gy and
                h_min[2] < g_max[2] and h_max[2] > gz):
                return True
        return False


def test_overlap_rejects_zero_length():
    assert _overlap_1d(0, 10, 10, 20, min_len=0.5) is None
    assert _overlap_1d(0, 10, 9.4, 20, min_len=0.5) is not None


def test_find_joint_face_contact():
    side = FakePanel(0, 0, 0, 16, 720, 560)
    bottom = FakePanel(16, 0, 0, 568, 16, 560)
    j = find_joint(side, bottom, tol=2.5)
    assert j is not None
    assert j.drill_axis == "X"


def test_find_joint_edge_only_rejected():
    a = FakePanel(0, 0, 0, 16, 720, 560)
    b = FakePanel(16, 720, 0, 600, 16, 560)  # only edge touch in Y
    assert find_joint(a, b, tol=2.5) is None


def test_find_joint_gap_too_large():
    a = FakePanel(0, 0, 0, 16, 720, 560)
    b = FakePanel(30, 0, 0, 568, 16, 560)  # gap 14 mm > tol 2.5
    assert find_joint(a, b, tol=2.5) is None


def test_make_joint_holes_coaxial():
    side = FakePanel(0, 0, 0, 16, 720, 560)
    bottom = FakePanel(16, 0, 0, 568, 16, 560)
    j = find_joint(side, bottom, tol=2.5)
    pt = clamp_joint_point(j, np.array([16.0, 8.0, 200.0]), margin=20)
    ha, hb = make_joint_holes(j, pt, diameter=7.0, depth=42.0)
    wy_a, wy_b = side.y + ha[1], bottom.y + hb[1]
    wz_a, wz_b = side.z + ha[2], bottom.z + hb[2]
    assert abs(wy_a - wy_b) < 1e-5
    assert abs(wz_a - wz_b) < 1e-5


def test_make_joint_holes_coaxial_with_groove():
    side = FakePanel(0, 0, 0, 16, 720, 560, grooves=[(11, 0, 16, 5, 720, 4)])
    bottom = FakePanel(16, 0, 0, 568, 16, 560)
    j = find_joint(side, bottom, tol=2.5)
    pt = clamp_joint_point(j, np.array([16.0, 8.0, 18.0]), margin=5)
    ha, hb = make_joint_holes(j, pt, diameter=7.0, depth=42.0)
    assert abs((side.y + ha[1]) - (bottom.y + hb[1])) < 1e-5
    assert abs((side.z + ha[2]) - (bottom.z + hb[2])) < 1e-5


def test_joint_array_points_count_and_margin():
    side = FakePanel(0, 0, 0, 16, 720, 560)
    bottom = FakePanel(16, 0, 0, 568, 16, 560)
    j = find_joint(side, bottom, tol=2.5)
    pts = joint_array_points(j, count=3, margin=50.0, pitch=None)
    assert len(pts) == 3
    # points along slide within joint range with margins
    for pt in pts:
        assert isinstance(pt, (list, tuple, np.ndarray))


def test_narrow_strip_16x10x500_uses_get_thickness(make_panel):
    """Пункт 1.7: у узкой планки 16×10×500 (thickness_axis=0, толщина плиты 16 мм)
    is_face_drilling и _hole_dims_for_fastener / make_joint_holes используют panel.get_thickness() (16 мм),
    а не min(width, height, depth) (10 мм).
    """
    from core.joint import is_face_drilling, _hole_dims_for_fastener

    strip = make_panel(name="Планка", x=0, y=0, z=0, width=16, height=10, depth=500)
    strip.thickness_axis = 0  # толщина плиты по X = 16 мм, ширина планки по Y = 10 мм
    assert abs(strip.get_thickness() - 16.0) < 1e-6

    # Сверление по X (сквозь 16 мм) — это пласть; по Y (в 10 мм грань) — это торец
    assert is_face_drilling(strip, "X") is True
    assert is_face_drilling(strip, "Y") is False
    assert is_face_drilling(strip, "Z") is False

    # Конфирмат в пласть X: сквозное отверстие Ø7 на полную толщину 16 мм (не 10 мм)
    dia_face, dep_face = _hole_dims_for_fastener(strip, "X", diameter=7.0, depth=42.0)
    assert abs(dia_face - 7.0) < 1e-6
    assert abs(dep_face - 16.0) < 1e-6

    # Шкант Ø8 в пласть X: глубина min(16 - 2, 12) = 12 мм (а не 10 - 2 = 8 мм)
    dia_dowel, dep_dowel = _hole_dims_for_fastener(strip, "X", diameter=8.0, depth=24.0)
    assert abs(dia_dowel - 8.0) < 1e-6
    assert abs(dep_dowel - 12.0) < 1e-6

    # Стык узкой планки 16×10×500 (пласть X) с примыкающей деталью справа
    other = make_panel(name="Полка", x=16, y=0, z=0, width=300, height=10, depth=500)
    other.thickness_axis = 1
    j = find_joint(strip, other, tol=2.5)
    assert j is not None
    assert j.drill_axis == "X"
    ha, hb = make_joint_holes(j, [16.0, 5.0, 250.0], diameter=7.0, depth=42.0)
    # В планке отверстие в пласть Ø7 (r=3.5) глубиной 16 мм (а не 10 мм)
    assert abs(ha[3] - 3.5) < 1e-6
    assert abs(ha[4] - 16.0) < 1e-6
    # В ответной детали отверстие в торец Ø5 (r=2.5)
    assert abs(hb[3] - 2.5) < 1e-6

