"""WinAPI типы + process_start против переиспользования PID (ревизия 4 §1.3)."""

from __future__ import annotations

import json

from core import project_io


def test_same_process_without_start_uses_pid_only(monkeypatch):
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: pid == 42)
    assert project_io.is_same_process(42, None) is True
    assert project_io.is_same_process(99, None) is False


def test_same_process_rejects_reused_pid(monkeypatch):
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: True)
    monkeypatch.setattr(project_io, "_PROCESS_START_CHECKER", lambda pid: 1000.0)
    assert project_io.is_same_process(7, 1000.0) is True
    assert project_io.is_same_process(7, 5000.0) is False  # другой процесс, тот же PID


def test_autosave_meta_includes_process_start(tmp_path, monkeypatch):
    monkeypatch.setattr(project_io, "process_start_time", lambda pid: 12345.5)
    from models.panel import Block

    snap = project_io.create_autosave_snapshot(
        [Block("B")],
        project_name="t.b3d",
        base_dir=tmp_path,
        pid=111,
    )
    meta = snap["autosave_meta"]
    assert meta["pid"] == 111
    assert abs(float(meta["process_start"]) - 12345.5) < 1e-6


def test_inspect_allows_recovery_when_pid_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: True)
    monkeypatch.setattr(project_io, "_PROCESS_START_CHECKER", lambda pid: 9999.0)

    path = tmp_path / "autosave_recovery_55.b3d"
    data = {
        "format": "NestCraft",
        "version": "0.0.8",
        "name": "x",
        "blocks": [],
        "autosave_meta": {"pid": 55, "process_start": 100.0},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    # PID 55 «жив», но start другой → файл должен быть доступен для recovery
    raw = project_io._inspect_autosave_candidate(path, current_pid=1)
    assert raw is not None
    assert raw["name"] == "x"


def test_inspect_blocks_live_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: True)
    monkeypatch.setattr(project_io, "_PROCESS_START_CHECKER", lambda pid: 100.0)

    path = tmp_path / "autosave_recovery_55.b3d"
    data = {
        "format": "NestCraft",
        "version": "0.0.8",
        "name": "x",
        "blocks": [],
        "autosave_meta": {"pid": 55, "process_start": 100.0},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    raw = project_io._inspect_autosave_candidate(path, current_pid=1)
    assert raw is None
