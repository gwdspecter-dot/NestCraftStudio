"""Panel.clone копирует все значимые поля."""


def test_clone_copies_rotation_edges_holes(make_panel):
    p = make_panel(width=16, height=720, depth=560, name="Боковина")
    p.rx, p.ry, p.rz = 0, 0, 15
    p.edges = {"top": "e1", "bottom": "e2", "left": "", "right": "e3"}
    p.holes = [(1.0, 2.0, 3.0, 3.5, 16.0, "X")]
    p.grooves = [(0, 0, 0, 1, 2, 3)]
    p.color = (0.1, 0.2, 0.3)
    p.thickness_axis = 0

    c = p.clone(name="Боковина (Копия)", x=10, role="")
    assert c is not p
    assert c.name == "Боковина (Копия)"
    assert abs(c.x - 10) < 1e-9
    assert c.rz == 15
    assert c.edges["top"] == "e1" and c.edges["right"] == "e3"
    assert c.holes == [(1.0, 2.0, 3.0, 3.5, 16.0, "X")]
    assert c.grooves == [(0, 0, 0, 1, 2, 3)]
    assert c.role == ""
    assert c.thickness_axis == 0
