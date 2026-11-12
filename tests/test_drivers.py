# -*- coding: utf-8 -*-
"""Персистентные формулы (drivers) на панелях."""

from __future__ import annotations

from core.drivers import (
    apply_block_drivers,
    apply_panel_drivers,
    evaluate_driver,
    set_driver,
    should_persist_formula,
)
from core.project_io import _panel_from_dict, _panel_to_dict, migrate_project_dict
from core.version import FORMAT_VERSION
from models.panel import Block, Panel


def test_should_persist_formula():
    assert should_persist_formula("cw - 2*ct")
    assert should_persist_formula("= w - 32")
    assert not should_persist_formula("600")
    assert not should_persist_formula("+= 16")
    assert not should_persist_formula("-= 10")


def test_evaluate_and_apply_with_parent_cabinet_vars():
    cab = Block(name="Корпус")
    # имитируем ParametricCabinet: width/height/depth/thickness + rebuild
    cab.width = 800.0
    cab.height = 720.0
    cab.depth = 560.0
    cab.thickness = 16.0
    cab.rebuild = lambda **_kw: None  # type: ignore[method-assign]

    panel = Panel(
        name="Полка",
        x=16,
        y=300,
        z=0,
        width=100,
        height=16,
        depth=560,
        uid="p1",
        rebuild=False,
    )
    cab.add_panel(panel)

    set_driver(panel, "width", "cw - 2*ct")
    val = evaluate_driver("cw - 2*ct", panel, attr="width")
    assert abs(val - 768.0) < 1e-6

    changed = apply_panel_drivers(panel)
    assert "width" in changed
    assert abs(float(panel.width) - 768.0) < 1e-6

    cab.width = 1000.0
    apply_block_drivers(cab)
    assert abs(float(panel.width) - 968.0) < 1e-6


def test_drivers_roundtrip_and_migration():
    panel = Panel(
        name="P",
        x=0,
        y=0,
        z=0,
        width=100,
        height=16,
        depth=500,
        uid="u1",
        rebuild=False,
    )
    set_driver(panel, "width", "cw - 32")
    d = _panel_to_dict(panel)
    assert d.get("drivers", {}).get("width") == "cw - 32"

    # migration 0.0.9 -> 0.0.10
    raw = {
        "version": "0.0.9",
        "name": "t",
        "blocks": [{"type": "block", "name": "B", "panels": [{"name": "X", "x": 0, "y": 0, "z": 0, "width": 10, "height": 10, "depth": 10}]}],
    }
    migrated, steps = migrate_project_dict(raw, in_place=False)
    assert any("0.0.10" in s for s in steps)
    assert migrated["version"] == FORMAT_VERSION
    assert isinstance(migrated["blocks"][0]["panels"][0].get("drivers"), dict)
