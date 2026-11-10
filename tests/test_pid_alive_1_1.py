"""is_pid_running / _pid_alive_native — ревизия 3 §1.1 (Windows не убивает процесс)."""

from __future__ import annotations

import os

from core import project_io


def test_self_pid_is_alive():
    assert project_io.is_pid_running(os.getpid()) is True


def test_invalid_pid():
    assert project_io.is_pid_running(None) is False
    assert project_io.is_pid_running(-1) is False
    assert project_io.is_pid_running(0) is False
    assert project_io.is_pid_running("nope") is False


def test_checker_override(monkeypatch):
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: pid == 42)
    assert project_io.is_pid_running(42) is True
    assert project_io.is_pid_running(99) is False


def test_windows_branch_uses_openprocess_not_kill(monkeypatch):
    """На win32 не должен вызываться os.kill."""
    calls = {"kill": 0, "open": 0}

    class FakeKernel:
        def OpenProcess(self, access, inherit, pid):
            calls["open"] += 1
            return 0  # fail open → process not found

        def GetExitCodeProcess(self, handle, code_ref):
            return 0

        def CloseHandle(self, handle):
            return 1

    def boom_kill(*a, **k):
        calls["kill"] += 1
        raise AssertionError("os.kill must not be used on Windows")

    monkeypatch.setattr(project_io.sys, "platform", "win32")
    monkeypatch.setattr(project_io.os, "kill", boom_kill)
    monkeypatch.setattr(project_io, "_ensure_win_k32", lambda: FakeKernel())
    # wintypes.DWORD used in branch
    from ctypes import wintypes  # noqa: F401

    result = project_io._pid_alive_native(12345)

    assert calls["kill"] == 0
    assert calls["open"] == 1
    assert result is False  # OpenProcess returned 0



def test_posix_uses_kill(monkeypatch):
    if project_io.sys.platform == "win32":
        return
    seen = []

    def fake_kill(pid, sig):
        seen.append((pid, sig))
        # pretend not found
        raise ProcessLookupError

    monkeypatch.setattr(project_io.os, "kill", fake_kill)
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", None)
    assert project_io.is_pid_running(999_999_999) is False
    assert seen and seen[0][1] == 0


def test_probe_does_not_kill_live_process():
    """Реальный subprocess: is_pid_running не завершает процесс (ревизия 4 §1.4).

    На Windows раньше os.kill(pid, 0) вызывал TerminateProcess — этот тест
    ловит регрессию на любой ОС, включая windows-latest в CI.
    """
    import subprocess
    import sys

    # Сбрасываем тестовые подмены, если остались от соседних тестов
    project_io._PID_ALIVE_CHECKER = None

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    try:
        assert project_io.is_pid_running(child.pid) is True
        assert child.poll() is None, "probe must not terminate the child process"
    finally:
        child.kill()
        child.wait(timeout=10)
    assert project_io.is_pid_running(child.pid) is False
