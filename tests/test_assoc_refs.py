# -*- coding: utf-8 -*-
"""Тесты ассоциативных ссылок (AssocRef / face_hole)."""

from __future__ import annotations

from core.assoc import (
    AssocRef,
    apply_assoc_refs,
    face_point_world,
    hole_assoc_uid,
    panel_face_frame,
)
from core.joint import JointRecord, apply_joints, extract_manual_holes, hole_joint_uid
from core.project_io import migrate_project_dict, scene_to_dict, _block_from_dict
from core.version import FORMAT_VERSION
from models.panel import Block, Panel


def _make_block_two_panels() -> Block:
    """Две панели: вертикальная (source) и горизонтальная (target) рядом."""
    # Source: боковина, thickness along X
    source = Panel(
        name="Left",
        x=0,
        y=0,
        z=0,
        width=16,
        height=720,
        depth=560,
        uid="src-uid",
        rebuild=False,
    )
    # Target: полка, thickness along Y, примыкает к X+ грани source
    target = Panel(
        name="Shelf",
        x=16,
        y=300,
        z=0,
        width=568,
        height=16,
        depth=560,
        uid="tgt-uid",
        rebuild=False,
    )
    block = Block(name="Test", uid="blk-uid")
    block.add_panel(source)
    block.add_panel(target)
    return block


def test_panel_face_frame_center():
    p = Panel(name="P", x=10, y=20, z=30, width=100, height=200, depth=16, rebuild=False)
    origin, normal, u_ax, v_ax = panel_face_frame(p, "Z+")
    # Центр верхней грани Z+: z = 30+16, x=10+50, y=20+100
    assert abs(float(origin[0]) - 60.0) < 1e-6
    assert abs(float(origin[1]) - 120.0) < 1e-6
    assert abs(float(origin[2]) - 46.0) < 1e-6
    assert abs(float(normal[2]) - 1.0) < 1e-6


def test_face_hole_created_and_tagged():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    ref = AssocRef(
        kind="face_hole",
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
    )
    block.add_assoc_ref(ref, apply=True)

    assert len(target.holes) == 1
    h = target.holes[0]
    assert hole_assoc_uid(h) == ref.uid
    assert hole_joint_uid(h) == ""
    # radius = diameter/2
    assert abs(float(h[3]) - 4.0) < 1e-6
    assert abs(float(h[4]) - 12.0) < 1e-6
    assert extract_manual_holes(target) == []


def test_assoc_recalculates_when_source_moves():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 50.0, "v": -100.0, "diameter": 5.0, "depth": 10.0},
    )
    block.add_assoc_ref(ref, apply=True)
    h1 = target.holes[0]
    pos1 = (float(h1[0]), float(h1[1]), float(h1[2]))

    # Двигаем source по X — точка на X+ должна сдвинуться
    source.x = 40.0
    apply_assoc_refs(block)

    assert len(target.holes) == 1
    h2 = target.holes[0]
    pos2 = (float(h2[0]), float(h2[1]), float(h2[2]))
    # Локальная X target должна измениться (source уехал)
    assert abs(pos2[0] - pos1[0]) > 1.0


def test_manual_and_joint_holes_survive_assoc_apply():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    manual = (100.0, 8.0, 200.0, 2.5, 12.0, "Y")
    target.holes.append(manual)

    jr = JointRecord(
        panel_a_uid=source.uid,
        panel_b_uid=target.uid,
        preset_id="confirmat_2",
    )
    block.add_joint(jr, apply=True)

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 6.0, "depth": 10.0},
    )
    block.add_assoc_ref(ref, apply=True)

    manuals = extract_manual_holes(target)
    assert any(abs(float(m[0]) - 100.0) < 1e-6 for m in manuals)
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)
    assert any(hole_joint_uid(h) for h in target.holes)


def test_roundtrip_assoc_refs_in_project():
    block = _make_block_two_panels()
    target = block.get_panel_by_uid("tgt-uid")
    source = block.get_panel_by_uid("src-uid")
    assert target is not None and source is not None

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 10.0, "v": 20.0, "diameter": 7.0, "depth": 14.0},
    )
    block.add_assoc_ref(ref, apply=True)

    data = scene_to_dict([block], "assoc-test")
    assert data["version"] == FORMAT_VERSION
    assert data["blocks"][0]["assoc_refs"]
    restored = _block_from_dict(data["blocks"][0])
    assert len(getattr(restored, "assoc_refs", []) or []) == 1
    tgt2 = restored.get_panel_by_uid("tgt-uid")
    assert tgt2 is not None
    assert any(hole_assoc_uid(h) for h in tgt2.holes)


def test_migrate_adds_empty_assoc_refs():
    data = {
        "format": "NestCraft",
        "version": "0.0.8",
        "name": "old",
        "blocks": [{"type": "block", "name": "B", "panels": [], "joints": []}],
    }
    migrated, steps = migrate_project_dict(data)
    assert migrated["version"] == FORMAT_VERSION
    assert any("0.0.9" in s for s in steps)
    assert migrated["blocks"][0].get("assoc_refs") == []
