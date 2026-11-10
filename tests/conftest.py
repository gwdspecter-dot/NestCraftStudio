"""Заглушки GUI/OCC/каталога для unit-тестов без PyQt/OpenGL (план §2.2)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _install_bare_numpy_stub():
    """Если в окружении нет numpy, регистрирует легковесный совместимый модуль для 3D-векторов."""
    try:
        import numpy  # noqa: F401
        return
    except ImportError:
        pass

    import math
    np_mod = types.ModuleType("numpy")

    class _Vec(list):
        def __init__(self, seq):
            super().__init__(seq)

        @property
        def size(self) -> int:
            if not self:
                return 0
            if isinstance(self[0], (list, tuple)):
                return sum(len(row) for row in self)
            return len(self)

        def copy(self):
            return _Vec([x.copy() if isinstance(x, _Vec) else x for x in self])

        def astype(self, _dtype):
            return self.copy()

        def tolist(self):
            return [x.tolist() if isinstance(x, _Vec) else x for x in self]

        def __getitem__(self, idx):
            if isinstance(idx, tuple) and len(idx) == 2:
                r_idx, c_idx = idx
                rows = super().__getitem__(r_idx) if isinstance(r_idx, slice) else [super().__getitem__(r_idx)]
                return _Vec([row[c_idx] for row in rows])
            return super().__getitem__(idx)

        def __setitem__(self, idx, val):
            if isinstance(idx, tuple) and len(idx) == 2:
                r_idx, c_idx = idx
                rows = super().__getitem__(r_idx) if isinstance(r_idx, slice) else [super().__getitem__(r_idx)]
                if isinstance(val, (list, tuple)):
                    for row, v in zip(rows, val):
                        row[c_idx] = v
                else:
                    for row in rows:
                        row[c_idx] = val
                return
            super().__setitem__(idx, val)

        def __add__(self, other):
            if isinstance(other, (list, tuple)):
                return _Vec([a + b for a, b in zip(self, other)])
            return _Vec([a + other for a in self])

        def __iadd__(self, other):
            return self.__add__(other)

        def __radd__(self, other):
            return self.__add__(other)

        def __sub__(self, other):
            if isinstance(other, (list, tuple)):
                return _Vec([a - b for a, b in zip(self, other)])
            return _Vec([a - other for a in self])

        def __isub__(self, other):
            return self.__sub__(other)

        def __rsub__(self, other):
            if isinstance(other, (list, tuple)):
                return _Vec([b - a for a, b in zip(self, other)])
            return _Vec([other - a for a in self])

        def __mul__(self, other):
            if isinstance(other, (list, tuple)):
                return _Vec([a * b for a, b in zip(self, other)])
            return _Vec([a * other for a in self])

        def __rmul__(self, other):
            return self.__mul__(other)

        def __truediv__(self, other):
            return _Vec([a / other for a in self])

        def __neg__(self):
            return _Vec([-a for a in self])

    def _array(seq, dtype=float, copy: bool = True):
        if isinstance(seq, _Vec):
            return seq.copy() if copy else seq
        if isinstance(seq, (list, tuple)) and seq and isinstance(seq[0], (list, tuple)):
            return _Vec([_array(row, dtype=dtype, copy=copy) for row in seq])
        return _Vec([float(x) if dtype is float else x for x in seq])

    np_mod.ndarray = _Vec
    np_mod.float32 = float
    np_mod.float64 = float
    np_mod.uint32 = int
    np_mod.array = _array
    np_mod.asarray = _array
    np_mod.zeros = lambda shape, dtype=float: (
        _Vec([_Vec([0.0] * shape[1]) for _ in range(shape[0])])
        if isinstance(shape, tuple) and len(shape) == 2
        else _Vec([0.0] * (shape[0] if isinstance(shape, tuple) else int(shape)))
    )
    np_mod.eye = lambda n, dtype=float: _Vec([
        _Vec([1.0 if i == j else 0.0 for j in range(n)]) for i in range(n)
    ])
    np_mod.dot = lambda a, b: sum(float(x) * float(y) for x, y in zip(a, b))
    np_mod.abs = lambda a: _Vec([abs(float(x)) for x in a]) if isinstance(a, (list, tuple)) else abs(a)
    np_mod.argmax = lambda a: max(range(len(a)), key=lambda i: a[i])
    np_mod.clip = lambda v, lo, hi: max(lo, min(hi, v))
    np_mod.allclose = lambda a, b, atol=1e-5: (
        all(abs(float(x) - float(y)) <= atol for x, y in zip(a, b))
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
        else abs(float(a) - float(b)) <= atol
    )
    np_mod.linalg = types.SimpleNamespace(
        norm=lambda v: math.sqrt(sum(float(x) * float(x) for x in v))
    )
    sys.modules["numpy"] = np_mod


_install_bare_numpy_stub()


def pytest_configure(config):
    """До импорта тестовых модулей: stub build123d, GeometryService, CADKernel."""
    if "build123d" not in sys.modules:
        b = types.ModuleType("build123d")

        class _Dummy:
            """Лёгкий solid-stub с AABB: Box/Pos/& дают volume пересечения (без ветки в prod)."""

            def __init__(self, *a, **k):
                self._mn = (0.0, 0.0, 0.0)
                self._mx = (0.0, 0.0, 0.0)
                # Box(w, h, d, align=...) — локальный бокс от (0,0,0)
                if len(a) >= 3 and all(isinstance(x, (int, float)) for x in a[:3]):
                    w, h, d = float(a[0]), float(a[1]), float(a[2])
                    self._mn = (0.0, 0.0, 0.0)
                    self._mx = (w, h, d)

            def _clone_aabb(self, mn, mx):
                n = object.__new__(_Dummy)
                n._mn, n._mx = mn, mx
                return n

            def translate(self, offset):
                dx, dy, dz = (float(offset[0]), float(offset[1]), float(offset[2]))
                mn = (self._mn[0] + dx, self._mn[1] + dy, self._mn[2] + dz)
                mx = (self._mx[0] + dx, self._mx[1] + dy, self._mx[2] + dz)
                return self._clone_aabb(mn, mx)

            def __mul__(self, other):
                # Rot * solid → игнор поворота в stub
                if isinstance(other, _Dummy):
                    return other
                return self

            def __rmul__(self, other):
                # Pos * solid / Rot * solid
                if hasattr(other, "offset"):
                    return self.translate(other.offset)
                return self

            def __sub__(self, other):
                return self

            def __and__(self, other):
                return _DummyIntersection(self, other)

            @property
            def volume(self):
                return max(0.0, self._mx[0] - self._mn[0]) * max(0.0, self._mx[1] - self._mn[1]) * max(
                    0.0, self._mx[2] - self._mn[2]
                )

            def bounding_box(self):
                class V:
                    def __init__(self, x, y, z):
                        self.X, self.Y, self.Z = x, y, z

                class BB:
                    def __init__(self, mn, mx):
                        self.min = V(*mn)
                        self.max = V(*mx)

                return BB(self._mn, self._mx)

            def tessellate(self, *a, **k):
                return [], []

        class _DummyIntersection:
            def __init__(self, a, b):
                self._a, self._b = a, b

            @property
            def volume(self):
                a, b = self._a, self._b
                ox = max(0.0, min(a._mx[0], b._mx[0]) - max(a._mn[0], b._mn[0]))
                oy = max(0.0, min(a._mx[1], b._mx[1]) - max(a._mn[1], b._mn[1]))
                oz = max(0.0, min(a._mx[2], b._mx[2]) - max(a._mn[2], b._mn[2]))
                return ox * oy * oz

        class _Pos:
            def __init__(self, x=0.0, y=0.0, z=0.0, *a, **k):
                if len(a) >= 2 and not isinstance(x, (int, float)):
                    pass
                self.offset = (float(x), float(y), float(z))

            def __mul__(self, solid):
                if hasattr(solid, "translate"):
                    return solid.translate(self.offset)
                return solid

        b.Box = _Dummy
        b.Cylinder = _Dummy
        b.Pos = _Pos
        b.Rot = _Dummy
        b.Align = types.SimpleNamespace(MIN="MIN", CENTER="CENTER")
        b.Rotation = _Dummy
        b.Extrinsic = types.SimpleNamespace(XYZ="XYZ")
        b.Intrinsic = types.SimpleNamespace(XYZ="XYZ")
        sys.modules["build123d"] = b


pytest_configure(None)


try:
    import pytest
except ImportError:
    class _SkipTestException(Exception):
        pass

    class _MarkStub:
        def __getattr__(self, _name: str):
            def _decorator(obj):
                return obj
            return _decorator

    class _ApproxVal:
        def __init__(self, expected, rel: float = 1e-6, abs_tol: float = 1e-12):
            self.expected = float(expected)
            self.rel = float(rel)
            self.abs_tol = float(abs_tol)

        def __eq__(self, actual):
            tol = max(self.abs_tol, abs(self.expected) * self.rel)
            return abs(float(actual) - self.expected) <= tol

    class _PytestStub(types.ModuleType):
        SkipException = _SkipTestException

        def __init__(self):
            super().__init__("pytest")
            self.mark = _MarkStub()

        @staticmethod
        def fixture(fn=None, **_kw):
            if fn is None:
                return lambda f: f
            return fn

        @staticmethod
        def approx(expected, rel: float = 1e-6, abs: float = 1e-12):
            return _ApproxVal(expected, rel=rel, abs_tol=abs)

        @staticmethod
        def skip(reason: str = ""):
            raise _SkipTestException(reason)

        @staticmethod
        def importorskip(modname: str, minversion: str | None = None, reason: str | None = None):
            import importlib
            try:
                mod = importlib.import_module(modname)
            except Exception as exc:
                msg = reason or f"could not import {modname!r}: {exc}"
                raise _SkipTestException(msg) from exc
            if mod is None:
                raise _SkipTestException(reason or f"module {modname!r} is None")
            return mod

    pytest = _PytestStub()
    sys.modules["pytest"] = pytest


@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на всю сессию pytest — иначе временные QApp[] в GUI-тестах
    уничтожают GeometryService, если он когда-либо был child of QApplication.

    Organization/Application name выставляем сразу: иначе QStandardPaths.AppDataLocation
    даёт ``…/python`` без ``NestCraft`` и ломает test_catalog_paths.
    """
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    if not app.organizationName():
        app.setOrganizationName("NestCraft")
    if not app.applicationName():
        app.setApplicationName("NestCraft Studio")
    yield app


@pytest.fixture(autouse=True)
def _ensure_geometry_service_alive(qapp):
    """Перед каждым тестом: живой GeometryService + привязка SceneController.

    Защита от «wrapped C/C++ object of type GeometryService has been deleted»,
    когда предыдущий тест создавал/уничтожал временный QApplication.
    """
    try:
        from core.geometry_service import GeometryService
        from core.scene_controller import SceneController

        GeometryService.instance()  # recreate if deleted
        # Не сбрасываем SceneController принудительно — часть тестов сама
        # делает reset/unbind; только гарантируем, что geometry singleton жив.
        _ = SceneController  # noqa: F841 — импорт для side-effect при необходимости
    except Exception as exc:
        # tests-only fixture: не валим сессию, если сервисы ещё не импортируются
        import sys
        print(f"[conftest] geometry ensure skipped: {exc}", file=sys.stderr)
    yield


@pytest.fixture
def panel_cls():
    from models.panel import Panel
    return Panel


@pytest.fixture
def make_panel(panel_cls):
    def _make(**kw):
        defaults = dict(
            name="P",
            x=0, y=0, z=0,
            width=100, height=200, depth=16,
            rebuild=False,
        )
        defaults.update(kw)
        return panel_cls(**defaults)
    return _make
