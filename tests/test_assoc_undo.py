# -*- coding: utf-8 -*-
"""Undo/Redo для ассоциативных ссылок."""

from __future__ import annotations

from core.assoc import AssocRef, hole_assoc_uid
from core.undo import (
    AddAssocRefCommand,
    DeleteAssocRefCommand,
    EditAssocRefCommand,
    MovePanelCommand,
    UndoStack,
)
from models.panel import Block, Panel


def _block_pair() -> tuple[Block, Panel, Panel]:
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
    return block, source, target


def test_add_assoc_undo_redo():
    block, source, target = _block_pair()
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0},
    )
    stack = UndoStack()
    stack.push(AddAssocRefCommand(block, ref), execute=True)

    assert len(block.assoc_refs) == 1
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)

    stack.undo()
    assert block.assoc_refs == []
    assert not any(hole_assoc_uid(h) for h in target.holes)

    stack.redo()
    assert len(block.assoc_refs) == 1
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)


def test_edit_assoc_undo_redo():
    block, source, target = _block_pair()
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 5.0, "depth": 10.0},
    )
    stack = UndoStack()
    stack.push(AddAssocRefCommand(block, ref), execute=True)

    old_state = ref.to_dict()
    new_state = ref.to_dict()
    new_state["params"] = dict(new_state["params"])
    new_state["params"]["u"] = 80.0
    new_state["params"]["diameter"] = 10.0

    h_before = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    pos_before = (float(h_before[0]), float(h_before[1]), float(h_before[2]))
    radius_before = float(h_before[3])

    stack.push(
        EditAssocRefCommand(block, ref.uid, old_state, new_state),
        execute=True,
    )

    h_after = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    assert abs(float(h_after[3]) - 5.0) < 1e-6  # diameter 10 → radius 5
    assert abs(float(h_after[1]) - pos_before[1]) > 1.0 or abs(float(h_after[2]) - pos_before[2]) > 1.0

    stack.undo()
    h_undo = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    assert abs(float(h_undo[3]) - radius_before) < 1e-6

    stack.redo()
    h_redo = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    assert abs(float(h_redo[3]) - 5.0) < 1e-6


def test_delete_assoc_undo_redo():
    block, source, target = _block_pair()
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 10.0, "v": -20.0, "diameter": 6.0, "depth": 11.0},
    )
    stack = UndoStack()
    stack.push(AddAssocRefCommand(block, ref), execute=True)
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)

    stack.push(DeleteAssocRefCommand(block, ref.uid), execute=True)
    assert block.assoc_refs == []
    assert not any(hole_assoc_uid(h) for h in target.holes)

    stack.undo()
    assert len(block.assoc_refs) == 1
    assert str(block.assoc_refs[0].uid) == ref.uid
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)

    stack.redo()
    assert block.assoc_refs == []
    assert not any(hole_assoc_uid(h) for h in target.holes)


def test_move_source_panel_reapplies_assoc():
    block, source, target = _block_pair()
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 5.0, "depth": 10.0},
    )
    stack = UndoStack()
    stack.push(AddAssocRefCommand(block, ref), execute=True)

    h0 = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    x0 = float(h0[0])

    stack.push(
        MovePanelCommand(source, (source.x, source.y, source.z), (40.0, source.y, source.z)),
        execute=True,
    )
    h1 = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    assert abs(float(h1[0]) - x0) > 1.0

    stack.undo()
    h2 = next(h for h in target.holes if hole_assoc_uid(h) == ref.uid)
    assert abs(float(h2[0]) - x0) < 1e-3
