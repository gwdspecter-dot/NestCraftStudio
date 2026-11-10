"""Единые headless-обёртки Qt для unit-тестов и сред без PyQt6 (ревизия 3 §1.4)."""

from __future__ import annotations

from typing import Any, Callable

try:
    from PyQt6.QtCore import (  # type: ignore[import]
        QObject,
        QRunnable,
        QThread,
        QThreadPool,
        pyqtSignal,
        pyqtSlot,
    )

    HAS_PYQT = True
except ImportError:  # pragma: no cover - headless
    HAS_PYQT = False

    class HeadlessSignalInstance:
        def __init__(self) -> None:
            self._slots: list[Callable[..., Any]] = []

        def connect(self, slot: Callable[..., Any]) -> None:
            if slot not in self._slots:
                self._slots.append(slot)

        def disconnect(self, slot: Callable[..., Any] | None = None) -> None:
            if slot is None:
                self._slots.clear()
            elif slot in self._slots:
                self._slots.remove(slot)

        def emit(self, *args: Any) -> None:
            for slot in list(self._slots):
                slot(*args)

    class HeadlessSignalDescriptor:
        def __init__(self, *_types: Any) -> None:
            self._attr_name = ""

        def __set_name__(self, owner: Any, name: str) -> None:
            self._attr_name = f"__qt_sig_{name}"

        def __get__(self, instance: Any, owner: Any = None) -> Any:
            if instance is None:
                return self
            sig = getattr(instance, self._attr_name, None)
            if sig is None:
                sig = HeadlessSignalInstance()
                setattr(instance, self._attr_name, sig)
            return sig

    def pyqtSignal(*types: Any) -> Any:  # type: ignore[misc]
        return HeadlessSignalDescriptor(*types)

    def pyqtSlot(*_types: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _dec(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn

        return _dec

    class QObject:  # type: ignore[no-redef]
        def __init__(self, parent: Any = None) -> None:
            self._parent = parent

    class QRunnable:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self._auto_delete = True

        def setAutoDelete(self, val: bool) -> None:
            self._auto_delete = bool(val)

        def run(self) -> None:
            raise NotImplementedError

    class QThread:  # type: ignore[no-redef]
        pass

    class QThreadPool:  # type: ignore[no-redef]
        _instance: "QThreadPool | None" = None

        def __init__(self) -> None:
            pass

        @classmethod
        def globalInstance(cls) -> "QThreadPool":
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def start(self, runnable: Any) -> None:
            # Синхронно в headless — тесты не ждут пул
            if hasattr(runnable, "run"):
                runnable.run()
