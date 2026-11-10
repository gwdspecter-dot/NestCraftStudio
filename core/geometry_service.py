"""Асинхронный B-Rep rebuild: QThreadPool + low-poly превью на UI-потоке."""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field
from typing import Any, Optional

from core._qt_compat import (
    HAS_PYQT as _HAS_PYQT,
    QObject,
    QRunnable,
    QThreadPool,
    pyqtSignal,
    pyqtSlot,
)
from core.cad_kernel import CADKernel, OCC_LOCK as _OCC_LOCK
from core.logging_setup import get_logger

_log = get_logger("geometry")

def _detach_mesh(mesh):
    """Копия mesh в numpy/list без ссылок на OCC (безопасно между потоками)."""
    if mesh is None:
        return None
    try:
        import numpy as np
    except ImportError:
        np = None
    if not isinstance(mesh, (tuple, list)) or len(mesh) < 2:
        return None
    verts, tris = mesh[0], mesh[1]
    normals = mesh[2] if len(mesh) > 2 else None
    if np is not None:
        verts = np.array(verts, dtype=float, copy=True)
        tris = np.array(tris, dtype=int, copy=True)
        if normals is not None:
            normals = np.array(normals, dtype=float, copy=True)
            return verts, tris, normals
        return verts, tris
    # pure python fallback
    verts = [tuple(map(float, v)) for v in verts]
    tris = [tuple(map(int, t)) for t in tris]
    if normals is not None:
        normals = [tuple(map(float, n)) for n in normals]
        return verts, tris, normals
    return verts, tris





@dataclass
class PanelSnapshot:
    """Снимок параметров панели для worker (без живых ссылок OCC)."""
    panel_id: int
    generation: int
    x: float
    y: float
    z: float
    width: float
    height: float
    depth: float
    grooves: list = field(default_factory=list)
    holes: list = field(default_factory=list)
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0


class RebuildRunnable(QRunnable):
    """Считает B-Rep + mesh в фоне; результат шлёт сигналами GeometryService (main thread)."""

    def __init__(self, snap: PanelSnapshot, service: "GeometryService"):
        super().__init__()
        self.snap = snap
        self._service = service
        self.setAutoDelete(True)

    def run(self):
        s = self.snap
        try:
            # Весь OCC (solid + tessellate) только в этом потоке; в UI уходит копия mesh.
            with _OCC_LOCK:
                solid = CADKernel.build_panel_solid_data(
                    s.x, s.y, s.z, s.width, s.height, s.depth, s.grooves, s.holes,
                    s.rx, s.ry, s.rz,
                )
                mesh = CADKernel.get_render_mesh(solid)
                mesh = _detach_mesh(mesh)
                # solid не передаём между потоками — OCC thread-affine
            self._service.store_rebuild_result(s.panel_id, s.generation, mesh, None)
            if _qt_obj_alive(self._service):
                try:
                    self._service.worker_finished.emit(s.panel_id, s.generation)
                except RuntimeError as emit_err:
                    _log.warning("worker_finished emit skipped: %s", emit_err)
        except Exception as e:
            _log.exception("B-Rep rebuild failed panel_id=%s gen=%s", s.panel_id, s.generation)
            if _qt_obj_alive(self._service):
                try:
                    self._service.worker_failed.emit(s.panel_id, s.generation, str(e))
                except RuntimeError as emit_err:
                    _log.warning("worker_failed emit skipped: %s", emit_err)



def _qt_obj_alive(obj: Any) -> bool:
    """True, если обёртка PyQt всё ещё связана с живым C++-объектом."""
    if obj is None:
        return False
    try:
        import shiboken6  # type: ignore[import]

        return bool(shiboken6.isValid(obj))
    except Exception as exc:
        _log.debug("shiboken6.isValid unavailable: %s", exc)
    try:
        from PyQt6 import sip  # type: ignore[attr-defined]

        return not sip.isdeleted(obj)
    except Exception as exc:
        _log.debug("sip.isdeleted unavailable: %s", exc)
    # headless / без sip: считаем живым
    return True


class GeometryService(QObject):
    """Синглтон: ставит rebuild в пул, применяет результат на UI-потоке."""

    # Внутренние сигналы (worker → UI): только POD — без OCC-объектов в очереди Qt
    worker_finished = pyqtSignal(int, int)  # panel_id, gen
    worker_failed = pyqtSignal(int, int, str)

    # Публичные
    panel_geometry_updated = pyqtSignal(object)  # Panel
    rebuild_failed = pyqtSignal(object, str)  # Panel | None, message

    _instance: Optional["GeometryService"] = None

    def __init__(self, parent=None):
        # Всегда parent=None: процессный синглтон не должен умирать вместе
        # с временным QApplication из GUI-тестов (иначе «wrapped C/C++ object … deleted»).
        super().__init__(None)
        if _HAS_PYQT:
            # Отдельный пул на 1 поток: OCC нельзя гонять параллельно
            self._pool = QThreadPool(self)
            self._pool.setMaxThreadCount(1)
            self._pool.setObjectName("NestCraftBRepPool")
        else:
            self._pool = None
        self._panel_refs: dict[int, weakref.ref] = {}
        self._result_store: dict[tuple[int, int], tuple[Any, Any]] = {}
        self._result_lock = threading.Lock()

        self.worker_finished.connect(self._on_finished)
        self.worker_failed.connect(self._on_failed)

    def store_rebuild_result(self, panel_id: int, generation: int, mesh, solid) -> None:
        with self._result_lock:
            self._result_store[(int(panel_id), int(generation))] = (mesh, solid)

    def take_rebuild_result(self, panel_id: int, generation: int):
        with self._result_lock:
            return self._result_store.pop((int(panel_id), int(generation)), None)

    def _safe_emit(self, signal, *args) -> None:
        """emit с защитой от уже удалённого C++-объекта (тесты / shutdown)."""
        if not _qt_obj_alive(self):
            _log.warning("GeometryService C++ object deleted — skip emit")
            return
        try:
            signal.emit(*args)
        except RuntimeError as e:
            # «wrapped C/C++ object of type GeometryService has been deleted»
            _log.warning("GeometryService emit failed: %s", e)

    @classmethod
    def instance(cls) -> "GeometryService":
        inst = cls._instance
        if inst is not None and not _qt_obj_alive(inst):
            # Зомби после уничтожения QApplication-родителя (старые версии) или deleteLater
            cls._instance = None
            inst = None
        if inst is None:
            # parent всегда None — см. __init__
            cls._instance = GeometryService(None)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Сброс синглтона (unit-тесты). Пул дожидается завершения задач."""
        inst = cls._instance
        if inst is not None:
            pool = getattr(inst, "_pool", None)
            if pool is not None and _qt_obj_alive(inst):
                try:
                    pool.waitForDone(2000)
                except Exception as exc:
                    _log.debug("GeometryService.reset waitForDone: %s", exc)
            try:
                if _qt_obj_alive(inst):
                    inst._panel_refs.clear()
                    with inst._result_lock:
                        inst._result_store.clear()
            except Exception as exc:
                _log.debug("GeometryService.reset clear refs: %s", exc)
        cls._instance = None

    def _register(self, panel) -> int:
        pid = id(panel)
        self._panel_refs[pid] = weakref.ref(panel)
        return pid

    def _resolve(self, panel_id: int):
        ref = self._panel_refs.get(panel_id)
        if ref is None:
            return None
        panel = ref()
        if panel is None:
            self._panel_refs.pop(panel_id, None)
        return panel

    @staticmethod
    def _panel_pose_key(panel) -> tuple:
        if hasattr(panel, "pose_key"):
            return panel.pose_key()
        return (
            round(float(panel.x), 4),
            round(float(panel.y), 4),
            round(float(panel.z), 4),
            round(float(panel.width), 4),
            round(float(panel.height), 4),
            round(float(panel.depth), 4),
            round(float(getattr(panel, "rx", 0.0)), 4),
            round(float(getattr(panel, "ry", 0.0)), 4),
            round(float(getattr(panel, "rz", 0.0)), 4),
        )

    def request_rebuild(self, panel, sync: bool = False) -> None:
        """
        Low-poly превью сразу (если габарит/поза сменились или меша ещё нет);
        если меняются только отверстия/пазы на той же позе — удерживаем предыдущий меш без мигания в AABB.
        Точный B-Rep+mesh — в пуле (или sync на текущем потоке).
        """
        if hasattr(panel, "invalidate_spatial_caches"):
            panel.invalidate_spatial_caches()
        panel.geometry_generation = int(getattr(panel, "geometry_generation", 0)) + 1
        gen = panel.geometry_generation
        panel.geometry_pending = True

        new_pose = self._panel_pose_key(panel)
        prev_pose = getattr(panel, "_mesh_pose_key", None)
        has_valid_prev_mesh = self._is_non_empty_mesh(getattr(panel, "mesh_data", None))

        if not has_valid_prev_mesh or prev_pose != new_pose:
            # Мгновенное превью — AABB/OBB-mesh (без OCC), с учётом поворота
            panel.mesh_data = CADKernel.make_aabb_mesh(
                panel.x, panel.y, panel.z, panel.width, panel.height, panel.depth,
                float(getattr(panel, "rx", 0.0)),
                float(getattr(panel, "ry", 0.0)),
                float(getattr(panel, "rz", 0.0)),
            )
            panel._mesh_pose_key = new_pose
            panel.solid = None
            panel._gl_arrays = None
            self._safe_emit(self.panel_geometry_updated, panel)
        else:
            # Удерживаем предыдущий меш и GPU-буфер до завершения B-Rep (бесшовный ребилд без мигания)
            panel.solid = None

        snap = PanelSnapshot(
            panel_id=self._register(panel),
            generation=gen,
            x=float(panel.x),
            y=float(panel.y),
            z=float(panel.z),
            width=float(panel.width),
            height=float(panel.height),
            depth=float(panel.depth),
            grooves=[tuple(g) for g in getattr(panel, "grooves", [])],
            holes=[tuple(h) for h in getattr(panel, "holes", [])],
            rx=float(getattr(panel, "rx", 0.0)),
            ry=float(getattr(panel, "ry", 0.0)),
            rz=float(getattr(panel, "rz", 0.0)),
        )

        has_features = bool(snap.grooves or snap.holes)
        # Пазы/отверстия: синхронно на UI-потоке — OCC thread-affine, так mesh с вырезами гарантирован.
        # Пустые плиты можно считать в фоне.
        if sync or has_features or self._pool is None:
            try:
                _log.info(
                    "B-Rep rebuild sync panel_id=%s gen=%s grooves=%s holes=%s",
                    snap.panel_id, gen, len(snap.grooves), len(snap.holes),
                )
                with _OCC_LOCK:
                    solid = CADKernel.build_panel_solid_data(
                        snap.x, snap.y, snap.z, snap.width, snap.height, snap.depth,
                        snap.grooves, snap.holes, snap.rx, snap.ry, snap.rz
                    )
                    mesh = CADKernel.get_render_mesh(solid)
                    mesh = _detach_mesh(mesh)
                self._apply(snap.panel_id, gen, mesh, solid)
            except Exception as e:
                _log.exception("Sync B-Rep rebuild failed panel_id=%s", snap.panel_id)
                panel.geometry_pending = False
                self._safe_emit(self.rebuild_failed, panel, str(e))
            return

        _log.info("B-Rep rebuild async panel_id=%s gen=%s", snap.panel_id, gen)
        self._pool.start(RebuildRunnable(snap, self))

    @pyqtSlot(int, int)
    def _on_finished(self, panel_id: int, generation: int):
        data = self.take_rebuild_result(panel_id, generation)
        if data is None:
            panel = self._resolve(panel_id)
            if panel is not None and generation == getattr(panel, "geometry_generation", -1):
                panel.geometry_pending = False
                _log.warning(
                    "Rebuild finished without stored result panel_id=%s gen=%s",
                    panel_id,
                    generation,
                )
            return
        mesh, solid = data
        self._apply(panel_id, generation, mesh, solid)

    @pyqtSlot(int, int, str)
    def _on_failed(self, panel_id: int, generation: int, message: str):
        # на всякий случай вычистить склад
        self.take_rebuild_result(panel_id, generation)
        panel = self._resolve(panel_id)
        if panel is None:
            return
        if generation != getattr(panel, "geometry_generation", -1):
            return
        panel.geometry_pending = False
        self._safe_emit(self.rebuild_failed, panel, message)

    @staticmethod
    def _is_non_empty_mesh(mesh) -> bool:
        if mesh is None or not isinstance(mesh, (tuple, list)) or len(mesh) < 2:
            return False
        verts, tris = mesh[0], mesh[1]
        if verts is None or tris is None:
            return False
        return len(verts) > 0 and len(tris) > 0

    def _apply(self, panel_id: int, generation: int, mesh, solid) -> None:
        panel = self._resolve(panel_id)
        if panel is None:
            return
        if generation != getattr(panel, "geometry_generation", -1):
            return  # устаревший результат — отбрасываем

        if self._is_non_empty_mesh(mesh):
            panel.mesh_data = mesh
            panel._mesh_pose_key = self._panel_pose_key(panel)
        else:
            # Не затираем уже хорошую сетку; AABB — только если нечего показать
            if not self._is_non_empty_mesh(getattr(panel, "mesh_data", None)):
                panel.mesh_data = CADKernel.make_aabb_mesh(
                    panel.x, panel.y, panel.z, panel.width, panel.height, panel.depth,
                    float(getattr(panel, "rx", 0.0)),
                    float(getattr(panel, "ry", 0.0)),
                    float(getattr(panel, "rz", 0.0)),
                )
                panel._mesh_pose_key = self._panel_pose_key(panel)
            _log.warning(
                "B-Rep mesh empty for panel_id=%s gen=%s (grooves=%s holes=%s) — AABB fallback",
                panel_id,
                generation,
                len(getattr(panel, "grooves", []) or []),
                len(getattr(panel, "holes", []) or []),
            )
        panel.solid = solid
        panel._gl_arrays = None
        panel.geometry_pending = False
        self._safe_emit(self.panel_geometry_updated, panel)
