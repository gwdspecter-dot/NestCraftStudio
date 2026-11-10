"""Panel._get_controller не глотает ошибки молча (ревизия 3 §1.5)."""

from __future__ import annotations

import logging

from models.panel import Panel


def test_unbound_flag_returns_none():
    prev = Panel._controller_unbound
    prev_sc = Panel._scene_controller
    try:
        Panel._scene_controller = None
        Panel._controller_unbound = True
        assert Panel._get_controller() is None
    finally:
        Panel._controller_unbound = prev
        Panel._scene_controller = prev_sc


def test_explicit_controller_used():
    class Fake:
        pass

    prev = Panel._scene_controller
    prev_u = Panel._controller_unbound
    try:
        Panel._controller_unbound = False
        Panel._scene_controller = Fake()
        assert Panel._get_controller() is Panel._scene_controller
    finally:
        Panel._scene_controller = prev
        Panel._controller_unbound = prev_u


def test_get_logger_panel_propagates():
    """get_logger('panel') → nestcraft.panel, propagate=True (ревизия 4 §1.7)."""
    from core.logging_setup import get_logger

    log = get_logger("panel")
    assert log.name == "nestcraft.panel"
    assert log.propagate is True


def test_instance_failure_is_logged(monkeypatch, caplog):
    import core.scene_controller as sc
    from core.logging_setup import get_logger

    prev = Panel._scene_controller
    prev_u = Panel._controller_unbound
    prev_inst = sc.SceneController._instance
    try:
        Panel._scene_controller = None
        Panel._controller_unbound = False
        sc.SceneController._instance = None

        def boom(cls):
            raise RuntimeError("catalog db locked")

        monkeypatch.setattr(sc.SceneController, "instance", classmethod(boom))
        # Логгер, которым пишет panel._get_controller
        assert get_logger("panel").name == "nestcraft.panel"
        with caplog.at_level(logging.ERROR, logger="nestcraft.panel"):
            assert Panel._get_controller() is None
        msgs = [r.message for r in caplog.records]
        assert any("SceneController.instance() failed" in m for m in msgs), msgs
        assert any(r.name == "nestcraft.panel" for r in caplog.records)
    finally:
        Panel._scene_controller = prev
        Panel._controller_unbound = prev_u
        sc.SceneController._instance = prev_inst
