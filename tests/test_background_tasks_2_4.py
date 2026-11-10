"""Тесты по пункту 2.4 и 1.11 (Ревизия 2):
- единый механизм фоновых операций `BackgroundTaskManager` (`QThreadPool` / `QRunnable`, снимки, сигналы прогресса);
- анализ коллизий по неизменяемым снимкам `CollisionPanelSnapshot` без чтения живых `Panel` из фонового потока;
- автосохранение из снимка сцены в `QRunnable` и изоляция файлов автосохранения по PID между процессами;
- фоновое чтение, парсинг и миграция больших файлов проектов (`ProjectDataSnapshot`).
"""

from __future__ import annotations

from pathlib import Path

from core.background_tasks import (
    BackgroundTaskManager,
    CollisionAnalysisResult,
    CollisionAnalysisSnapshot,
    CollisionPanelSnapshot,
    TASK_AUTOSAVE,
    TASK_COLLISION,
    TASK_PROJECT_LOAD,
)
import core.project_io as project_io
from core.project_io import (
    ProjectDataSnapshot,
    autosave_file_path,
    clear_autosave,
    has_autosave,
    load_autosave,
    materialize_project_snapshot,
    save_project,
)
from models.panel import Block, Panel


def test_collision_snapshot_isolation_and_signals():
    """П. 1.11 + 2.4: воркер коллизий работает по снимку и не зависит от мутаций живых Panel в UI."""
    BackgroundTaskManager.reset()
    mgr = BackgroundTaskManager.instance()

    p1 = Panel("Боковина Л", 0, 0, 0, 16, 720, 560, rebuild=False)
    p2 = Panel("Полка пересекающая", 8, 300, 0, 584, 16, 560, rebuild=False)
    p3 = Panel("Далекая деталь", 2000, 0, 0, 16, 720, 560, rebuild=False)

    snap = CollisionAnalysisSnapshot.from_panels([p1, p2, p3], min_volume=0.1)
    assert len(snap.panels) == 3
    assert all(isinstance(s, CollisionPanelSnapshot) for s in snap.panels)

    # Мутируем живые объекты Panel после создания снимка (имитация правок пользователя в UI)
    p1.x = 99999.0
    p1.width = 1.0
    p1.holes.append((2.0, 2.0, 2.0, 4.0, 10.0, "X"))
    # Ставим заведомо некорректный solid на живой объект — снимок НЕ должен к нему обращаться
    p1.solid = "LIVE_PANEL_SOLID_MUST_NOT_BE_READ"

    started_events: list[tuple[int, str, str]] = []
    progress_events: list[tuple[int, str, int, int, str]] = []
    finished_events: list[tuple[int, str, object]] = []

    mgr.task_started.connect(lambda tid, k, msg: started_events.append((tid, k, msg)))
    mgr.task_progress.connect(
        lambda tid, k, cur, tot, msg: progress_events.append((tid, k, cur, tot, msg))
    )
    mgr.task_finished.connect(lambda tid, k, res: finished_events.append((tid, k, res)))

    task_id, _ = mgr.submit_collision_analysis(snap, sync=True)
    mgr.wait_for_done()

    assert len(started_events) == 1
    assert started_events[0][0] == task_id
    assert started_events[0][1] == TASK_COLLISION

    assert len(progress_events) >= 1
    assert progress_events[-1][2] == 1 and progress_events[-1][3] == 1

    assert len(finished_events) == 1
    res = finished_events[0][2]
    assert isinstance(res, CollisionAnalysisResult)
    assert len(res.hits) == 1

    # Сопоставляем результат обратно живым панелям по uid
    resolved = res.resolve_for_panels([p1, p2, p3])
    assert len(resolved) == 1
    hit_a, hit_b, vol = resolved[0]
    assert {hit_a.uid, hit_b.uid} == {p1.uid, p2.uid}
    assert vol is not None and vol > 50.0


def test_autosave_pid_isolation_and_background_task(tmp_path: Path, monkeypatch):
    """П. 1.11 + 2.4: два одновременно запущенных экземпляра (PID 1001 и 1002) не перезаписывают друг друга."""
    BackgroundTaskManager.reset()
    mgr = BackgroundTaskManager.instance()

    alive_pids = {1001, 1002}
    monkeypatch.setattr(project_io, "_PID_ALIVE_CHECKER", lambda pid: pid in alive_pids)

    b1 = Block("Проект первого окна")
    b1.add_panel(Panel("Деталь А", 0, 0, 0, 600, 720, 16, rebuild=False))

    b2 = Block("Проект второго окна")
    b2.add_panel(Panel("Деталь Б", 0, 0, 0, 800, 900, 16, rebuild=False))

    finished: list[Path] = []
    mgr.task_finished.connect(
        lambda _tid, kind, res: finished.append(res) if kind == TASK_AUTOSAVE else None
    )

    mgr.submit_autosave(
        [b1],
        project_name="window_1.b3d",
        base_dir=tmp_path,
        pid=1001,
        sync=True,
    )
    mgr.submit_autosave(
        [b2],
        project_name="window_2.b3d",
        base_dir=tmp_path,
        pid=1002,
        sync=True,
    )

    f1 = autosave_file_path(tmp_path, pid=1001)
    f2 = autosave_file_path(tmp_path, pid=1002)
    assert f1.is_file() and f2.is_file()
    assert f1 != f2
    assert len(finished) == 2

    # Пока оба процесса 1001 и 1002 живы, третий процесс (1003) не считает их файлы осиротевшими
    assert not has_autosave(base_dir=tmp_path, current_pid=1003)
    clear_autosave(base_dir=tmp_path, pid=1003)
    assert f1.is_file() and f2.is_file(), "Файлы живых процессов не должны удаляться чужим экземпляром"

    # Теперь процесс 1001 аварийно завершился, а 1002 продолжает работать
    alive_pids.remove(1001)
    assert has_autosave(base_dir=tmp_path, current_pid=1003)

    recovered, meta = load_autosave(base_dir=tmp_path, current_pid=1003)
    assert meta["pid"] == 1001
    assert meta["project_name"] == "window_1.b3d"
    assert recovered.blocks[0].panels[0].name == "Деталь А"

    # Очистка в 1003 удаляет осиротевший файл 1001, но не трогает живой файл 1002
    clear_autosave(base_dir=tmp_path, pid=1003)
    assert not f1.exists()
    assert f2.is_file()


def test_background_project_load_snapshot_and_progress(tmp_path: Path):
    """П. 2.4: фоновая загрузка файла читает и мигрирует JSON в ProjectDataSnapshot с сигналами прогресса."""
    BackgroundTaskManager.reset()
    mgr = BackgroundTaskManager.instance()

    b = Block("Шкаф-купе")
    b.add_panel(Panel("Боковина", 0, 0, 0, 16, 2200, 600, rebuild=False))
    b.add_panel(Panel("Крышка", 0, 2200, 0, 1200, 16, 600, rebuild=False))

    proj_file = tmp_path / "wardrobe_large.b3d"
    save_project(proj_file, [b], "wardrobe_large")

    progress_steps: list[tuple[int, int, str]] = []
    results: list[ProjectDataSnapshot] = []

    mgr.task_progress.connect(
        lambda _tid, kind, cur, tot, msg: (
            progress_steps.append((cur, tot, msg)) if kind == TASK_PROJECT_LOAD else None
        )
    )
    mgr.task_finished.connect(
        lambda _tid, kind, res: results.append(res) if kind == TASK_PROJECT_LOAD else None
    )

    mgr.submit_project_load(proj_file, sync=True)
    assert len(results) == 1
    snap = results[0]
    assert isinstance(snap, ProjectDataSnapshot)
    assert snap.name == "wardrobe_large"
    assert [step[:2] for step in progress_steps] == [(1, 3), (2, 3), (3, 3)]

    loaded = materialize_project_snapshot(snap)
    assert loaded.name == "wardrobe_large"
    assert len(loaded.blocks) == 1
    assert len(loaded.blocks[0].panels) == 2
