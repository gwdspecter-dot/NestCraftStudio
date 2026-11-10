"""EditPropertyCommand: rename без rebuild; undo/redo."""

from core.undo import EditPropertyCommand


def test_rename_does_not_call_rebuild(make_panel, monkeypatch):
    p = make_panel(name="Old")
    calls = []

    def fake_rebuild(*a, **k):
        calls.append(True)

    monkeypatch.setattr(p, "rebuild_geometry", fake_rebuild)
    cmd = EditPropertyCommand(p, "name", "Old", "New")
    cmd.redo()
    assert p.name == "New"
    assert calls == []
    cmd.undo()
    assert p.name == "Old"
    assert calls == []


def test_size_change_triggers_rebuild(make_panel, monkeypatch):
    p = make_panel(width=100)
    calls = []
    monkeypatch.setattr(p, "rebuild_geometry", lambda *a, **k: calls.append(1))
    cmd = EditPropertyCommand(p, "width", 100.0, 200.0)
    cmd.redo()
    assert abs(p.width - 200) < 1e-9
    assert calls  # geometry attr → rebuild
    cmd.undo()
    assert abs(p.width - 100) < 1e-9
