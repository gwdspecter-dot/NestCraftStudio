"""get_saw_dimensions при разных кромках."""


def test_saw_no_edges(make_panel):
    p = make_panel(width=600, height=16, depth=400)
    sx, sy, sz = p.get_saw_dimensions()
    assert abs(sx - 600) < 1e-6
    assert abs(sy - 16) < 1e-6
    assert abs(sz - 400) < 1e-6


def test_saw_with_edge_thickness(make_panel, monkeypatch):
    p = make_panel(width=600, height=16, depth=400)
    p.edges = {"top": "e1", "bottom": "e2", "left": "e3", "right": "e4"}

    def fake_thickness(side):
        return {"top": 0.4, "bottom": 0.4, "left": 2.0, "right": 2.0}.get(side, 0.0)

    monkeypatch.setattr(p, "get_edge_thickness", fake_thickness)
    sx, sy, sz = p.get_saw_dimensions()
    # length axis = max dim (X=600), width axis = next (Z=400)
    assert abs(sx - (600 - 2 - 2)) < 1e-6  # left+right
    assert abs(sz - (400 - 0.4 - 0.4)) < 1e-6  # top+bottom on width axis
