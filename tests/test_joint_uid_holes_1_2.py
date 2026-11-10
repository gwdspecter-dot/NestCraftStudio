"""Метка joint_uid на отверстиях стыка (ревизия 3 §1.2)."""

from __future__ import annotations

from types import SimpleNamespace

from core.joint import (
    extract_manual_holes,
    hole_joint_uid,
    tag_joint_hole,
    holes_equal,
)
from core.project_io import migrate_project_dict, _migrate_to_0_0_8
from core.version import FORMAT_VERSION


def test_format_version_is_008():
    assert FORMAT_VERSION == "0.0.8"


def test_tag_and_extract_by_uid():
    joint_uid = "jr-abc"
    joint_hole = tag_joint_hole((10.0, 20.0, 30.0, 3.5, 16.0, "X"), joint_uid)
    assert hole_joint_uid(joint_hole) == joint_uid
    assert len(joint_hole) == 7
    manual_hole = (1.0, 2.0, 3.0, 4.0, 5.0, "Y")

    panel = SimpleNamespace(
        holes=[joint_hole, manual_hole],
        joint_hole_map={},  # карта пуста — без метки всё было бы «ручным»
    )
    manual = extract_manual_holes(panel)
    assert len(manual) == 1
    assert holes_equal(manual[0], manual_hole)


def test_extract_fallback_jmap_without_tag():
    """Legacy: без 7-го поля, но есть joint_hole_map."""
    jh = (10.0, 20.0, 30.0, 3.5, 16.0, "X")
    mh = (1.0, 2.0, 3.0, 4.0, 5.0, "Y")
    panel = SimpleNamespace(
        holes=[jh, mh],
        joint_hole_map={"jr-1": [jh]},
    )
    manual = extract_manual_holes(panel)
    assert len(manual) == 1
    assert holes_equal(manual[0], mh)


def test_migrate_0_0_8_tags_from_map():
    data = {
        "version": "0.0.7",
        "blocks": [
            {
                "type": "block",
                "name": "B",
                "panels": [
                    {
                        "name": "P",
                        "holes": [
                            [10, 20, 30, 3.5, 16, "X"],
                            [1, 2, 3, 4, 5, "Y"],
                        ],
                        "joint_hole_map": {
                            "jr-42": [[10, 20, 30, 3.5, 16, "X"]],
                        },
                    }
                ],
            }
        ],
    }
    out = _migrate_to_0_0_8(data)
    holes = out["blocks"][0]["panels"][0]["holes"]
    tagged = [h for h in holes if len(h) >= 7]
    assert len(tagged) == 1
    assert tagged[0][6] == "jr-42"
    plain = [h for h in holes if len(h) == 6]
    assert len(plain) == 1


def test_migrate_chain_to_008():
    data = {"version": "0.0.7", "name": "t", "blocks": []}
    migrated, steps = migrate_project_dict(data, in_place=False)
    assert any("0.0.8" in s for s in steps)
    assert migrated["version"] == "0.0.8"
