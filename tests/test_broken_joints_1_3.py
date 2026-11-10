"""Разорванный стык → Issue (ревизия 3 §1.3)."""

from __future__ import annotations


from core.issues import check_broken_joints_in_blocks, check_scene_issues
from core.joint import JointRecord, apply_joints, find_joint
from models.panel import Panel, Block


def _side_bottom_pair():
    """Боковина + дно в контакте (как в joint-тестах)."""
    side = Panel("Боковина", 0, 0, 0, 16, 720, 560, uid="pa", rebuild=False)
    bottom = Panel("Дно", 16, 0, 0, 568, 16, 560, uid="pb", rebuild=False)
    return side, bottom


def test_touching_joint_no_issue():
    side, bottom = _side_bottom_pair()
    assert find_joint(side, bottom) is not None
    block = Block("B")
    block.panels = [side, bottom]
    block.joints = [
        JointRecord(
            uid="jr1",
            panel_a_uid=side.uid,
            panel_b_uid=bottom.uid,
            preset_id="confirmat_3",
        )
    ]
    issues = check_broken_joints_in_blocks([block])
    assert issues == []


def test_moved_apart_reports_joint_broken():
    side, bottom = _side_bottom_pair()
    block = Block("B")
    block.panels = [side, bottom]
    block.joints = [
        JointRecord(
            uid="jr1",
            panel_a_uid=side.uid,
            panel_b_uid=bottom.uid,
            preset_id="confirmat_3",
        )
    ]
    apply_joints(block, rebuild_geometry=False)
    assert len(side.holes) > 0

    # Разрываем стык
    bottom.x = 200.0
    apply_joints(block, rebuild_geometry=False)
    assert side.holes == []  # присадка снята

    issues = check_broken_joints_in_blocks([block])
    assert any(i.code == "joint_broken" for i in issues)


def test_missing_panel_reports_joint_panel_missing():
    side, bottom = _side_bottom_pair()
    block = Block("B")
    block.panels = [side]  # bottom отсутствует
    block.joints = [
        JointRecord(
            uid="jr1",
            panel_a_uid=side.uid,
            panel_b_uid=bottom.uid,
            preset_id="confirmat_3",
        )
    ]
    issues = check_broken_joints_in_blocks([block])
    assert any(i.code == "joint_panel_missing" for i in issues)


def test_registered_in_scene_checks():
    side, bottom = _side_bottom_pair()
    bottom.x = 300.0
    block = Block("B")
    block.panels = [side, bottom]
    block.joints = [
        JointRecord(
            uid="jr1",
            panel_a_uid=side.uid,
            panel_b_uid=bottom.uid,
            preset_id="confirmat_3",
        )
    ]
    issues = check_scene_issues([block], include_collisions=False)
    assert any(i.code == "joint_broken" for i in issues)
