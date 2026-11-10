"""Стабильные uid Panel/Block (план §2.7)."""

from models.panel import Block, new_uid
from core.project_io import _panel_to_dict, _panel_from_dict, _block_to_dict, _block_from_dict


def test_new_uid_unique():
    a, b = new_uid(), new_uid()
    assert a and b and a != b


def test_panel_auto_uid(make_panel):
    p = make_panel()
    assert p.uid
    p2 = make_panel()
    assert p.uid != p2.uid


def test_panel_uid_roundtrip(make_panel):
    p = make_panel(name="A")
    fixed = "11111111-2222-3333-4444-555555555555"
    p.uid = fixed
    d = _panel_to_dict(p)
    assert d["uid"] == fixed
    p2 = _panel_from_dict(d)
    assert p2.uid == fixed


def test_legacy_file_gets_uid():
    p = _panel_from_dict({
        "name": "Legacy", "x": 0, "y": 0, "z": 0,
        "width": 100, "height": 16, "depth": 200,
    })
    assert p.uid  # generated on load


def test_clone_new_uid(make_panel):
    p = make_panel()
    c = p.clone(name="Copy")
    assert c.uid and c.uid != p.uid


def test_block_uid_roundtrip():
    b = Block("Изделие", "1", "01")
    fixed = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    b.uid = fixed
    d = _block_to_dict(b)
    assert d["uid"] == fixed
    b2 = _block_from_dict(d)
    assert b2.uid == fixed
