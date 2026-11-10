"""Единый механизм фоновых операций на базе QThreadPool и снимков данных (ревизия 2, п. 2.4 и 1.11).

Объединяет три долгие операции в один конвейер:
1. Автосохранение (`autosave`) — снимок словаря сцены на UI-потоке, сериализация JSON и атомарная
   запись на диск в `QRunnable` с изоляцией по PID процесса;
2. Загрузка больших файлов (`project_load`) — чтение, парсинг JSON и миграция словаря в `QRunnable`
   с передачей неизменяемого снимка `ProjectDataSnapshot` в главный поток через сигнал;
3. Анализ коллизий (`collision`) — передача воркеру неизменяемых снимков `CollisionPanelSnapshot`
   (`uid`, размеры, позиция, поворот, пазы, отверстия) без чтения живых объектов `Panel` из другого потока.

Все задачи публикуют статус старта, прогресс `(current, total, message)` и результат/ошибку через сигналы
для отображения в строке состояния `MainWindow`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from core._qt_compat import (
    HAS_PYQT as _HAS_PYQT,
    QObject,
    QRunnable,
    QThreadPool,
    pyqtSignal,
)
from core.cad_kernel import CADKernel
from core.logging_setup import get_logger

_log = get_logger("background_tasks")

TASK_AUTOSAVE = "autosave"
TASK_PROJECT_LOAD = "project_load"
TASK_COLLISION = "collision"


@dataclass(frozen=True)
class CollisionPanelSnapshot:
    """Неизменяемый снимок геометрии панели для фонового анализа коллизий (п. 1.11 и 2.4).

    Не хранит ссылку на живой экземпляр `Panel` или его `solid`, поэтому модификация
    панелей в UI-потоке во время работы `QThreadPool` полностью безопасна.
    """

    uid: str
    name: str
    x: float
    y: float
    z: float
    width: float
    height: float
    depth: float
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    grooves: tuple[tuple[float, ...], ...] = ()
    holes: tuple[tuple[Any, ...], ...] = ()
    geometry_generation: int = 0
    world_aabb_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )
    _is_snapshot: bool = True

    @classmethod
    def from_panel(cls, panel: Any) -> "CollisionPanelSnapshot":
        uid = str(getattr(panel, "uid", "") or id(panel))
        name = str(getattr(panel, "name", "Панель") or "Панель")
        x = float(getattr(panel, "x", 0.0))
        y = float(getattr(panel, "y", 0.0))
        z = float(getattr(panel, "z", 0.0))
        w = float(getattr(panel, "width", 0.0))
        h = float(getattr(panel, "height", 0.0))
        d = float(getattr(panel, "depth", 0.0))
        rx = float(getattr(panel, "rx", 0.0))
        ry = float(getattr(panel, "ry", 0.0))
        rz = float(getattr(panel, "rz", 0.0))
        grooves = tuple(tuple(float(v) for v in g) for g in (getattr(panel, "grooves", None) or ()))
        holes = tuple(
            (float(hl[0]), float(hl[1]), float(hl[2]), float(hl[3]), float(hl[4]), str(hl[5]))
            for hl in (getattr(panel, "holes", None) or ())
        )
        gen = int(getattr(panel, "geometry_generation", 0))
        aabb = CADKernel._panel_aabb(panel)
        a0 = (float(aabb[0][0]), float(aabb[0][1]), float(aabb[0][2]))
        a1 = (float(aabb[1][0]), float(aabb[1][1]), float(aabb[1][2]))
        return cls(
            uid=uid,
            name=name,
            x=x,
            y=y,
            z=z,
            width=w,
            height=h,
            depth=d,
            rx=rx,
            ry=ry,
            rz=rz,
            grooves=grooves,
            holes=holes,
            geometry_generation=gen,
            world_aabb_bounds=(a0, a1),
        )

    def world_aabb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return self.world_aabb_bounds


@dataclass(frozen=True)
class CollisionAnalysisSnapshot:
    """Снимок всей сцены для задачи анализа пересечений."""

    panels: tuple[CollisionPanelSnapshot, ...]
    scene_sig: tuple[Any, ...]
    min_volume: float = 0.1

    @classmethod
    def from_panels(cls, panels: list[Any], *, min_volume: float = 0.1) -> "CollisionAnalysisSnapshot":
        snaps = tuple(
            p if isinstance(p, CollisionPanelSnapshot) else CollisionPanelSnapshot.from_panel(p)
            for p in panels
        )
        sig = tuple(CADKernel._panel_collision_token(s) for s in snaps)
        return cls(panels=snaps, scene_sig=sig, min_volume=float(min_volume))


@dataclass(frozen=True)
class CollisionAnalysisResult:
    """Результат фонового анализа пересечений по снимкам."""

    scene_sig: tuple[Any, ...]
    # Список (uid_a, uid_b, vol_or_None) и снимков (snap_a, snap_b, vol_or_None)
    hits: list[tuple[CollisionPanelSnapshot, CollisionPanelSnapshot, float | None]]

    def resolve_for_panels(self, live_panels: list[Any]) -> list[tuple[Any, Any, float | None]]:
        """Сопоставляет результаты со снимков живым панелям сцены по `uid`."""
        by_uid = {str(getattr(p, "uid", "") or id(p)): p for p in live_panels}
        resolved: list[tuple[Any, Any, float | None]] = []
        for snap_a, snap_b, vol in self.hits:
            pa = by_uid.get(snap_a.uid)
            pb = by_uid.get(snap_b.uid)
            if pa is not None and pb is not None:
                resolved.append((pa, pb, vol))
        return resolved


class BackgroundTaskRunnable(QRunnable):
    """Универсальная задача `QRunnable` для выполнения функции над снимком в `QThreadPool`."""

    def __init__(
        self,
        task_id: int,
        kind: str,
        snapshot: Any,
        work_fn: Callable[[Any, Callable[[int, int, str], None]], Any],
        manager: "BackgroundTaskManager",
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.kind = kind
        self.snapshot = snapshot
        self._work_fn = work_fn
        self._manager = manager
        self.setAutoDelete(True)

    def _report_progress(self, current: int, total: int, message: str = "") -> None:
        self._manager.task_progress.emit(
            self.task_id, self.kind, int(current), int(total), str(message or "")
        )

    def run(self) -> None:
        try:
            result = self._work_fn(self.snapshot, self._report_progress)
            self._manager.task_finished.emit(self.task_id, self.kind, result)
        except Exception as exc:
            _log.exception("Background task failed id=%s kind=%s", self.task_id, self.kind)
            self._manager.task_failed.emit(self.task_id, self.kind, str(exc))


class BackgroundTaskManager(QObject):
    """Единый менеджер фоновых операций (автосохранение, загрузка проектов, анализ коллизий)."""

    # (task_id, kind, status_message)
    task_started = pyqtSignal(int, str, str)
    # (task_id, kind, current, total, status_message)
    task_progress = pyqtSignal(int, str, int, int, str)
    # (task_id, kind, result)
    task_finished = pyqtSignal(int, str, object)
    # (task_id, kind, error_message)
    task_failed = pyqtSignal(int, str, str)

    _instance: Optional["BackgroundTaskManager"] = None

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance() if _HAS_PYQT else None
        self._seq: int = 0
        self._latest_by_kind: dict[str, int] = {}
        self._active_runnables: dict[int, BackgroundTaskRunnable] = {}

        self.task_finished.connect(self._cleanup_runnable)
        self.task_failed.connect(self._cleanup_runnable)

    @classmethod
    def instance(cls) -> "BackgroundTaskManager":
        if cls._instance is None:
            cls._instance = BackgroundTaskManager()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None and cls._instance._pool is not None:
            try:
                cls._instance._pool.waitForDone(2000)
            except Exception as exc:
                _log.debug("Ожидание пула потоков при сбросе BackgroundTaskManager пропущено: %s", exc)
        cls._instance = None

    def _cleanup_runnable(self, task_id: int, *_args: Any) -> None:
        self._active_runnables.pop(task_id, None)

    def latest_task_id(self, kind: str) -> int:
        return self._latest_by_kind.get(kind, 0)

    def is_latest(self, task_id: int, kind: str) -> bool:
        return self._latest_by_kind.get(kind, 0) == task_id

    def wait_for_done(self, timeout_ms: int = 5000) -> bool:
        if self._pool is not None:
            return bool(self._pool.waitForDone(timeout_ms))
        return True

    def submit_task(
        self,
        kind: str,
        snapshot: Any,
        work_fn: Callable[[Any, Callable[[int, int, str], None]], Any],
        *,
        start_message: str = "",
        sync: bool = False,
    ) -> int:
        """Ставит задачу со снимком в `QThreadPool` (или выполняет синхронно при `sync=True`)."""
        self._seq += 1
        task_id = self._seq
        self._latest_by_kind[kind] = task_id

        if start_message:
            self.task_started.emit(task_id, kind, start_message)

        runnable = BackgroundTaskRunnable(task_id, kind, snapshot, work_fn, self)
        if sync or self._pool is None:
            runnable.run()
        else:
            self._active_runnables[task_id] = runnable
            self._pool.start(runnable)
        return task_id

    # ── Специализированные постановщики 3 фоновых операций (п. 2.4) ──────

    def submit_autosave(
        self,
        blocks_or_snapshot: Any,
        *,
        project_name: str = "Новый проект.b3d",
        original_path: str | Path | None = None,
        autosave_path: str | Path | None = None,
        base_dir: str | Path | None = None,
        pid: int | None = None,
        sync: bool = False,
    ) -> int:
        """Создаёт снимок сцены на вызывающем потоке и записывает файл автосохранения в фоне."""
        from core.project_io import create_autosave_snapshot, write_autosave_snapshot

        if isinstance(blocks_or_snapshot, dict) and "autosave_meta" in blocks_or_snapshot:
            snapshot = blocks_or_snapshot
        else:
            snapshot = create_autosave_snapshot(
                blocks_or_snapshot,
                project_name=project_name,
                original_path=original_path,
                autosave_path=autosave_path,
                base_dir=base_dir,
                pid=pid,
            )

        def _work(snap: dict, progress_cb: Callable[[int, int, str], None]) -> Path:
            progress_cb(1, 2, "Автосохранение: сериализация снимка…")
            written_path = write_autosave_snapshot(snap, autosave_path=autosave_path)
            progress_cb(2, 2, f"Автосохранение выполнено ({written_path.name})")
            return written_path

        return self.submit_task(
            TASK_AUTOSAVE,
            snapshot,
            _work,
            start_message="⏳ Автосохранение проекта…",
            sync=sync,
        )

    def submit_project_load(
        self,
        path: str | Path,
        *,
        sync: bool = False,
    ) -> int:
        """Читает, парсит и мигрирует файл проекта в фоне, возвращая `ProjectDataSnapshot`."""
        from core.project_io import read_project_snapshot

        target_path = Path(path)

        def _work(file_path: Path, progress_cb: Callable[[int, int, str], None]) -> Any:
            return read_project_snapshot(file_path, progress_cb=progress_cb)

        return self.submit_task(
            TASK_PROJECT_LOAD,
            target_path,
            _work,
            start_message=f"⏳ Загрузка файла «{target_path.name}»…",
            sync=sync,
        )

    def submit_collision_analysis(
        self,
        panels_or_snapshot: list[Any] | CollisionAnalysisSnapshot,
        *,
        min_volume: float = 0.1,
        sync: bool = False,
    ) -> tuple[int, CollisionAnalysisSnapshot]:
        """Снимает неизменяемый `CollisionAnalysisSnapshot` на UI-потоке и считает B-Rep пересечения в фоне."""
        if isinstance(panels_or_snapshot, CollisionAnalysisSnapshot):
            snap = panels_or_snapshot
        else:
            snap = CollisionAnalysisSnapshot.from_panels(list(panels_or_snapshot), min_volume=min_volume)

        def _work(
            s: CollisionAnalysisSnapshot,
            progress_cb: Callable[[int, int, str], None],
        ) -> CollisionAnalysisResult:
            hits = CADKernel.find_scene_collisions(
                list(s.panels),
                min_volume=s.min_volume,
                progress_cb=lambda cur, tot: progress_cb(
                    cur, tot, f"⏳ Анализ пересечений: {cur}/{tot} пар…"
                ),
            )
            return CollisionAnalysisResult(scene_sig=s.scene_sig, hits=hits)

        task_id = self.submit_task(
            TASK_COLLISION,
            snap,
            _work,
            start_message="⏳ Анализ пересечений…",
            sync=sync,
        )
        return task_id, snap
