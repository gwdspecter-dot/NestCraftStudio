"""round-trip .b3d: role, thickness_axis, rx/ry/rz, missing_material."""

from core.project_io import _panel_to_dict, _panel_from_dict, scene_to_dict, scene_from_dict


def test_panel_roundtrip_fields(make_panel):
    p = make_panel(name="Shelf", width=568, height=16, depth=560, role="shelf_1")
    p.rx, p.ry, p.rz = 1.5, 2.5, 3.5
    p.thickness_axis = 1
    p.holes = [(10, 0, 20, 3.5, 12, "Y")]
    p.edges = {"top": "e1", "bottom": "", "left": "", "right": ""}
    p.missing_material_id = "mat_gone"

    d = _panel_to_dict(p)
    assert d["role"] == "shelf_1"
    assert d["thickness_axis"] == 1
    assert abs(d["rz"] - 3.5) < 1e-9
    assert d["missing_material_id"] == "mat_gone"

    p2 = _panel_from_dict(d)
    assert p2.role == "shelf_1"
    assert p2.thickness_axis == 1
    assert abs(p2.rz - 3.5) < 1e-9
    assert len(p2.holes) == 1


def test_scene_roundtrip_empty():
    data = scene_to_dict([], "empty")
    assert data["format"] == "NestCraft"
    name, blocks = scene_from_dict(data)
    assert name == "empty"
    assert blocks == []


def test_save_project_permissions_not_0600(tmp_path):
    """План §1.9: новый файл получает 0o666 & ~umask (не 0600 от mkstemp), а у существующего сохраняются его права."""
    import os
    import stat
    import sys
    from core.project_io import save_project

    out = tmp_path / "test_proj.b3d"
    save_project(out, [], "proj")
    assert out.is_file()

    if sys.platform != "win32":
        um = os.umask(0)
        os.umask(um)
        expected_mode = 0o666 & ~um
        actual_mode = stat.S_IMODE(out.stat().st_mode)
        assert actual_mode == expected_mode
        assert actual_mode != 0o600

        # Если у существующего файла выставлены особые права (например, 0o640), повторное сохранение их сохраняет
        os.chmod(out, 0o640)
        save_project(out, [], "proj_updated")
        assert stat.S_IMODE(out.stat().st_mode) == 0o640

