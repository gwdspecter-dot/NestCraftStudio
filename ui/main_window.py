import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QLabel, QLineEdit,
    QComboBox, QMessageBox, QFileDialog, QApplication,
    QAbstractSpinBox, QTextEdit, QPlainTextEdit, QSlider, QToolButton,
)
from PyQt6.QtGui import QAction, QKeySequence, QIcon
from PyQt6.QtCore import Qt, QTimer, QSize, QObject, QRunnable, pyqtSignal

from models.panel import Panel, Block, ParametricCabinet
from ui.viewport import CentralWorkspace
from ui.dialogs import CreatePanelDialog, HoleDialog
from ui.fastener_constructor_dialog import FastenerConstructorDialog
from ui.panels.structure_panel import StructureDock
from ui.panels.properties_panel import PropertiesDock
from ui.panels.browser_panel import BrowserDock
from ui.panels.history_panel import AnalysisDock, HistoryDock
from ui.panels.joints_panel import JointsDock
from core.undo import (
    AddPanelCommand,
    DeleteJointCommand,
    EditJointCommand,
    EditPropertyCommand,
    ReplaceBlocksCommand,
    SetHolesCommand,
)
from core.project_io import (
    save_project,
    load_project,
    materialize_project_snapshot,
    ProjectDataSnapshot,
    FILE_FILTER,
    ProjectLoadResult,
    load_recent_files,
    add_recent_file,
    remove_recent_file,
    clear_recent_files,
    create_autosave_snapshot,
    has_autosave,
    load_autosave,
    clear_autosave,
)
from core.background_tasks import (
    BackgroundTaskManager,
    CollisionAnalysisResult,
    CollisionAnalysisSnapshot,
    CollisionPanelSnapshot,
    TASK_AUTOSAVE,
    TASK_COLLISION,
    TASK_PROJECT_LOAD,
)
from core.logging_setup import get_logger
from core.version import APP_VERSION

_log = get_logger("ui")

# Иконки панелей (рядом с этим файлом: ui/icons/)
_ICONS_DIR = Path(__file__).resolve().parent / "icons"


class _CollisionSignals(QObject):
    finished = pyqtSignal(int, object, object)


class _CollisionWorker(QRunnable):
    """Фоновый расчёт 3D-пересечений по неизменяемым снимкам панелей в QThreadPool (п. 1.11 и 2.4)."""

    def __init__(self, run_id: int, panels: list, scene_sig: tuple):
        super().__init__()
        self.run_id = run_id
        # Снимаем неизменяемые копии на потоке создания воркера (не читаем живые Panel в run)
        self.snapshots = [
            p if isinstance(p, CollisionPanelSnapshot) else CollisionPanelSnapshot.from_panel(p)
            for p in panels
        ]
        self.scene_sig = scene_sig
        self.signals = _CollisionSignals()

    def run(self) -> None:
        from core.cad_kernel import CADKernel

        try:
            hits = CADKernel.find_scene_collisions(self.snapshots, min_volume=0.1)
        except Exception:
            _log.exception("Background collision analysis failed")
            hits = []
        self.signals.finished.emit(self.run_id, self.scene_sig, hits)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project_path: str | None = None
        self.project_name = "Новый проект.b3d"
        self.is_modified = False
        self.setWindowTitle(f"NestCraft Studio - [{self.project_name}]")
        self.resize(1450, 860)
        logo = _ICONS_DIR / "logo.svg"
        if logo.is_file():
            self.setWindowIcon(QIcon(str(logo)))

        self.workspace = CentralWorkspace()
        self.setCentralWidget(self.workspace)

        self._create_menu_bar()
        self._create_toolbars()
        self._create_dock_panels()
        self._create_status_bar()

        self._collision_run_seq: int = 0
        self._collision_cache_sig: tuple | None = None
        self._collision_cache_hits: list[tuple[Panel, Panel, float | None]] | None = None
        self._active_collision_worker: QRunnable | None = None

        # Единый менеджер фоновых задач в QThreadPool (ревизия 2, п. 2.4)
        self.bg_tasks = BackgroundTaskManager.instance()
        self.bg_tasks.task_started.connect(self._on_bg_task_started)
        self.bg_tasks.task_progress.connect(self._on_bg_task_progress)
        self.bg_tasks.task_finished.connect(self._on_bg_task_finished)
        self.bg_tasks.task_failed.connect(self._on_bg_task_failed)

        # Таймер периодического автосохранения (план §2.8, п. 2.4)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)
        self._autosave_timer.timeout.connect(self._perform_autosave)
        self._autosave_timer.start()

        self._connect_signals()
        self._refresh_structure()
        QTimer.singleShot(400, self._check_autosave_recovery)

    def _connect_signals(self):
        self.structure_dock.object_selected.connect(self._on_object_selected)
        self.properties_dock.property_changed.connect(self._on_property_changed)
        self.properties_dock.property_applied.connect(self._on_property_applied)
        self.properties_dock.validation_failed.connect(self._on_validation_failed)
        self.browser_dock.template_double_clicked.connect(self.add_cabinet_from_template)
        self.analysis_dock.run_analysis_requested.connect(self.run_collision_analysis)
        self.analysis_dock.issue_activated.connect(self.select_panel_by_uid)
        self.joints_dock.joint_selected.connect(self._on_joint_selected)
        self.joints_dock.joint_modified.connect(self._on_joint_modified)
        self.joints_dock.joint_deleted.connect(self._on_joint_deleted)
        self.joints_dock.add_joint_requested.connect(self.add_hole_to_selected)

        # Сигналы вкладок: при смене/создании переподключаем viewport
        self.workspace.currentChanged.connect(self._on_tab_changed)
        self._bind_viewport_signals(self.workspace.current_viewport())

    def _bind_viewport_signals(self, vp):
        """Подключает сигналы текущего 3D-вьюпорта (безопасно при смене вкладок)."""
        if vp is None:
            return
        for sig, slot in (
            (vp.panel_clicked, self._on_viewport_clicked),
            (vp.coordinates_changed, self._update_coord_boxes),
            (vp.fastener_message, self._on_fastener_message),
            (vp.scene_structure_changed, self._refresh_structure),
        ):
            try:
                sig.disconnect(slot)
            except TypeError as exc:
                # PyQt6 выбрасывает TypeError, если слот ещё не был подключён к сигналу
                _log.debug("Сигнал вьюпорта ещё не был подключён (%s): %s", slot.__name__, exc)
            sig.connect(slot)

        try:
            vp.measurement_updated.disconnect(self._on_measurement_updated)
        except (TypeError, AttributeError) as exc:
            # Слот ещё не подключён или вьюпорт не поддерживает сигнал рулетки
            _log.debug("Отключение measurement_updated пропущено: %s", exc)
        vp.measurement_updated.connect(self._on_measurement_updated)
        if hasattr(self, "act_measure"):
            self.act_measure.setChecked(vp.measure_mode)
        if hasattr(self, "act_grid"):
            self.act_grid.blockSignals(True)
            self.act_grid.setChecked(bool(getattr(vp, "grid_enabled", True)))
            self.act_grid.blockSignals(False)
            if hasattr(self, "grid_step_combo"):
                step = float(getattr(vp, "grid_step", 50.0))
                label = f"{step:g} мм"
                idx = self.grid_step_combo.findText(label)
                if idx >= 0 and self.grid_step_combo.currentIndex() != idx:
                    self.grid_step_combo.blockSignals(True)
                    self.grid_step_combo.setCurrentIndex(idx)
                    self.grid_step_combo.blockSignals(False)
        self._bind_undo_listener(vp)
        self._refresh_history_dock()

    def _on_tab_changed(self, index: int):
        vp = self.workspace.current_viewport()
        self._bind_viewport_signals(vp)
        self._refresh_structure()
        self._refresh_history_dock()
        if vp:
            sel = vp.get_selected_panel()
            self.properties_dock.show_object_properties(sel)
            if sel:
                self._update_coord_boxes(sel.x, sel.y, sel.z)
            else:
                self._update_coord_boxes(0.0, 0.0, 0.0)
            if hasattr(self, "act_measure"):
                self.act_measure.setChecked(vp.measure_mode)

    def _on_undo_stack_changed(self):
        self._refresh_history_dock()
        self._refresh_issues_only()
        vp = self.workspace.current_viewport()
        if vp and hasattr(vp, "undo_stack"):
            self.mark_modified(not vp.undo_stack.is_clean())
        else:
            self.mark_modified(True)

    def _refresh_history_dock(self):
        vp = self.workspace.current_viewport()
        if not vp or not hasattr(vp, "undo_stack"):
            return
        labels = vp.undo_stack.history_labels()
        self.history_dock.set_history(labels)

    def _bind_undo_listener(self, vp):
        if vp is None or not hasattr(vp, "undo_stack"):
            return
        vp.undo_stack.set_on_changed(self._on_undo_stack_changed)

    def _update_coord_boxes(self, x: float, y: float, z: float):
        """Обновляет поля X, Y, Z на верхней панели при выборе или сдвиге детали"""
        self.coord_edits["X"].setText(f"{x:.1f}")
        self.coord_edits["Y"].setText(f"{y:.1f}")
        self.coord_edits["Z"].setText(f"{z:.1f}")

    def _apply_coord_boxes(self):
        """Позволяет вбить X, Y, Z (или формулу: 600 - 16, += 50) прямо в верхнюю панель и нажать Enter"""
        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        if not sel:
            return
        import math
        try:
            from core.formula import context_vars_from_object, eval_math_expression
            from core.undo import MovePanelCommand

            def _coord(s: str, cur_val: float) -> float:
                env = context_vars_from_object(sel, current_value=cur_val)
                v = eval_math_expression(s, current_value=cur_val, variables=env)
                if not math.isfinite(v) or v < -50000.0 or v > 50000.0:
                    raise ValueError("coord out of range")
                return v

            nx = _coord(self.coord_edits["X"].text(), float(sel.x))
            ny = _coord(self.coord_edits["Y"].text(), float(sel.y))
            nz = _coord(self.coord_edits["Z"].text(), float(sel.z))
            old_xyz = (sel.x, sel.y, sel.z)
            if (nx, ny, nz) != old_xyz:
                vp.undo_stack.push(MovePanelCommand(sel, old_xyz, (nx, ny, nz)), execute=True)
            self._update_coord_boxes(sel.x, sel.y, sel.z)
            self.properties_dock.show_object_properties(sel)
            vp.update()
        except (ValueError, TypeError, OverflowError):
            # Откат полей к текущим координатам детали
            self._update_coord_boxes(sel.x, sel.y, sel.z)

    def _refresh_structure(self):
        vp = self.workspace.current_viewport()
        if vp:
            if hasattr(vp, "_rebuild_scene_gpu_ids"):
                vp._rebuild_scene_gpu_ids()
            self.structure_dock.load_structure(vp.title, vp.blocks)
            if hasattr(self, "joints_dock") and self.joints_dock is not None:
                self.joints_dock.load_joints(vp.blocks)
            self._refresh_issues_only()

    def _on_joint_selected(self, block, joint_uid: str) -> None:
        vp = self.workspace.current_viewport()
        if not vp or block is None:
            return
        rec = block.get_joint_by_uid(joint_uid) if hasattr(block, "get_joint_by_uid") else None
        if rec is None:
            return
        pa_uid = str(getattr(rec, "panel_a_uid", ""))
        pb_uid = str(getattr(rec, "panel_b_uid", ""))
        for b in vp.blocks:
            b.selected = False
            for p in getattr(b, "panels", []):
                p.selected = str(getattr(p, "uid", "")) in {pa_uid, pb_uid}
        vp.update()

    def _on_joint_modified(self, block, joint_uid: str, old_state: dict, new_state: dict) -> None:
        vp = self.workspace.current_viewport()
        if not vp or block is None or not joint_uid:
            return
        cmd = EditJointCommand(block, joint_uid, old_state, new_state, "Параметры стыка")
        vp.undo_stack.push(cmd, execute=True, merge=True)
        self._refresh_structure()
        sel = vp.get_selected_panel()
        if sel is not None:
            self.properties_dock.show_object_properties(sel)
        vp.update()

    def _on_joint_deleted(self, block, joint_uid: str) -> None:
        vp = self.workspace.current_viewport()
        if not vp or block is None or not joint_uid:
            return
        cmd = DeleteJointCommand(block, joint_uid, "Удаление стыка")
        vp.undo_stack.push(cmd, execute=True)
        self._refresh_structure()
        sel = vp.get_selected_panel()
        if sel is not None:
            self.properties_dock.show_object_properties(sel)
        vp.update()

    def _on_object_selected(self, obj):
        self.properties_dock.show_object_properties(obj)
        if isinstance(obj, Panel):
            self._update_coord_boxes(obj.x, obj.y, obj.z)
        vp = self.workspace.current_viewport()
        if vp:
            vp.update()

    def _on_viewport_clicked(self, obj):
        self.properties_dock.show_object_properties(obj)
        if isinstance(obj, Panel):
            self._update_coord_boxes(obj.x, obj.y, obj.z)
        # Подсвечиваем элемент в дереве структуры без повторного сигнала
        self.structure_dock.highlight_object(obj)

    def _on_property_changed(self):
        vp = self.workspace.current_viewport()
        if vp:
            vp.update()
            QTimer.singleShot(0, self._refresh_structure)

    def _on_validation_failed(self, message: str) -> None:
        if message:
            self.statusBar().showMessage(message, 8000)

    def _on_property_applied(self, obj, attr_name: str, old_val, new_val):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        from core.validation import ValidationError

        cmd = EditPropertyCommand(obj, attr_name, old_val, new_val)
        try:
            vp.undo_stack.push(cmd, execute=True)
        except ValidationError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            self.properties_dock.show_object_properties(obj)
            return
        self._refresh_structure()
        vp.update()
        if isinstance(obj, Panel):
            self._update_coord_boxes(obj.x, obj.y, obj.z)

    def add_new_panel(self, panel_type: str):
        """Открывает конструктор панели и добавляет её в сцену"""
        vp = self.workspace.current_viewport()
        if not vp:
            return

        # Если сейчас выделена какая-то деталь, предлагаем ставить новую рядом с ней!
        sel = vp.get_selected_panel()
        def_x = sel.x + sel.width if (sel and panel_type != "vertical") else (sel.x if sel else 0.0)
        def_y = sel.y if sel else 0.0
        def_z = sel.z if sel else 0.0

        dlg = CreatePanelDialog(panel_type, def_x, def_y, def_z, self)
        if dlg.exec():
            data = dlg.get_panel_data()
            
            # Гарантируем, что есть блок для добавления
            if not vp.blocks:
                vp.blocks.append(Block("Корпус 1", "1", "01.00"))
            
            target_block = vp.blocks[-1]
            idx = len(target_block.panels) + 1

            p = Panel(
                data["name"], data["x"], data["y"], data["z"],
                data["width"], data["height"], data["depth"],
                f"{target_block.pos_num}.{idx}"
            )
            # Ось толщины по типу панели
            if panel_type == "vertical":
                p.thickness_axis = 0
            elif panel_type == "horizontal":
                p.thickness_axis = 1
            else:
                p.thickness_axis = 2
            p.lock_thickness_to_material()
            if data["has_groove"]:
                groove_side = "right" if panel_type == "vertical" else "top"
                p.add_back_groove(side=groove_side)

            for b in vp.blocks:
                for old_p in b.panels:
                    old_p.selected = False
            p.selected = True

            vp.undo_stack.push(AddPanelCommand(vp.blocks, target_block, p, f"Построение: {p.name}"))
            self._refresh_structure()
            self.properties_dock.show_object_properties(p)
            self._update_coord_boxes(p.x, p.y, p.z)
            vp.update()

    @staticmethod
    def _next_copy_name(base_name: str, existing_names: set[str]) -> str:
        """Имя копии без «(Копия) (Копия)…»: «Стол» → «Стол (Копия)», затем «Стол (Копия 2)»."""
        import re
        name = (base_name or "Панель").strip()
        # Срезаем хвост « (Копия)» / « (Копия N)»
        m = re.match(r"^(.*?)(?:\s*\(Копия(?:\s+\d+)?\))+$", name)
        if m:
            name = m.group(1).strip() or name
        candidate = f"{name} (Копия)"
        if candidate not in existing_names:
            return candidate
        n = 2
        while True:
            candidate = f"{name} (Копия {n})"
            if candidate not in existing_names:
                return candidate
            n += 1

    @staticmethod
    def _next_pos_num(block, preferred_prefix: str = "") -> str:
        """Уникальный pos_num внутри блока: prefix.N или просто свободный индекс."""
        used = {str(getattr(p, "pos_num", "") or "") for p in getattr(block, "panels", [])}
        prefix = preferred_prefix or str(getattr(block, "pos_num", "") or "1")
        idx = len(getattr(block, "panels", [])) + 1
        while True:
            cand = f"{prefix}.{idx}"
            if cand not in used:
                return cand
            idx += 1

    def duplicate_selected_panel(self):
        """Дублирует выбранную панель (Ctrl+D) со сдвигом на шаг сетки.

        Копируются: размеры, поворот, кромка, материал, пазы, присадка.
        """
        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        if not sel:
            return

        target_block = None
        for b in vp.blocks:
            if sel in b.panels:
                target_block = b
                break
        if target_block is None:
            if not vp.blocks:
                vp.blocks.append(Block("Изделие 1", "1", "01.00"))
            target_block = vp.blocks[-1]

        # Сдвиг: вертикальные — по X, горизонтальные — по Y
        offset_x = vp.move_step if sel.width <= sel.height else 0.0
        offset_y = vp.move_step if sel.width > sel.height else 0.0

        existing_names = {
            str(getattr(p, "name", "") or "")
            for b in vp.blocks
            for p in getattr(b, "panels", [])
        }
        new_name = self._next_copy_name(sel.name, existing_names)
        new_pos = self._next_pos_num(target_block, str(getattr(target_block, "pos_num", "") or "1"))

        clone = sel.clone(
            name=new_name,
            x=float(sel.x) + offset_x,
            y=float(sel.y) + offset_y,
            z=float(sel.z),
            pos_num=new_pos,
            role="",  # не структурная деталь корпуса
        )

        sel.selected = False
        clone.selected = True
        vp.undo_stack.push(AddPanelCommand(vp.blocks, target_block, clone, f"Дублирование: {clone.name}"))
        self._refresh_structure()
        self.properties_dock.show_object_properties(clone)
        self._update_coord_boxes(clone.x, clone.y, clone.z)
        vp.update()

    def clear_scene(self):
        """Очищает сцену для конструирования изделия с нуля"""
        vp = self.workspace.current_viewport()
        if not vp:
            return
        if hasattr(vp, "_free_all_panel_gpu"):
            vp._free_all_panel_gpu()
        empty = [Block("Изделие 1", "1", "01.00")]
        vp.undo_stack.push(
            ReplaceBlocksCommand(vp.blocks, empty, "Очистка сцены"),
            execute=True,
        )
        self._refresh_structure()
        self.properties_dock.show_object_properties(None)
        vp.update()

    def add_cabinet_from_template(self, template_code: str):
        vp = self.workspace.current_viewport()
        if not vp:
            return

        idx = len(vp.blocks) + 1
        pos_str = str(idx)
        code_str = f"{idx:02d}.00"

        next_x_base = max([b.x + b.width for b in vp.blocks if isinstance(b, ParametricCabinet) and b.y < 1000], default=0.0)
        next_x_upper = max([b.x + b.width for b in vp.blocks if isinstance(b, ParametricCabinet) and b.y >= 1000], default=0.0)

        if template_code == "base_600":
            cab = ParametricCabinet(f"Блок{idx} (Тумба 600)", next_x_base, 100, 0, 600, 720, 560, 16, 1, False, False, True, pos_str, code_str)
        elif template_code == "base_800":
            cab = ParametricCabinet(f"Блок{idx} (Тумба 800)", next_x_base, 100, 0, 800, 720, 560, 16, 2, False, False, True, pos_str, code_str)
        elif template_code == "upper_600":
            cab = ParametricCabinet(f"Блок{idx} (Верх 600)", next_x_upper, 1400, 0, 600, 720, 320, 16, 2, True, True, True, pos_str, code_str)
        elif template_code == "tall_600":
            cab = ParametricCabinet(f"Блок{idx} (Пенал 600)", next_x_base, 100, 0, 600, 2140, 560, 16, 4, True, True, True, pos_str, code_str)
        else:
            return

        new_list = list(vp.blocks) + [cab]
        vp.undo_stack.push(
            ReplaceBlocksCommand(vp.blocks, new_list, f"Модуль: {cab.name}"),
            execute=True,
        )
        self._refresh_structure()
        vp.update()

    def select_panel_by_uid(self, panel_uid: str) -> bool:
        """Выделяет деталь в сцене по её uid (по двойному клику в списке «Проблемы»)."""
        uid = str(panel_uid or "").strip()
        if not uid:
            return False
        vp = self.workspace.current_viewport()
        if not vp:
            return False
        target = None
        for b in vp.blocks:
            for p in getattr(b, "panels", []):
                is_match = str(getattr(p, "uid", "")) == uid
                p.selected = is_match
                if is_match:
                    target = p
        if target is None:
            return False
        self.properties_dock.show_object_properties(target)
        self.structure_dock.highlight_object(target)
        self._update_coord_boxes(target.x, target.y, target.z)
        vp.update()
        return True

    def _refresh_issues_only(self, extra_issues: list | None = None) -> None:
        """Обновляет единый список «Проблемы» (материалы, кромки, толщина крепежа, отступы, пазы, кэш коллизий) в AnalysisDock."""
        from core.cad_kernel import CADKernel
        from core.issues import check_scene_issues, issues_from_collision_hits

        if not hasattr(self, "analysis_dock") or self.analysis_dock is None:
            return
        vp = self.workspace.current_viewport()
        if not vp:
            return
        issues = list(extra_issues or [])
        issues.extend(check_scene_issues(vp.blocks, include_collisions=False))

        all_panels = [p for b in vp.blocks for p in getattr(b, "panels", [])]
        if self._collision_cache_hits is not None and self._collision_cache_sig is not None:
            try:
                cur_sig = tuple(CADKernel._panel_collision_token(p) for p in all_panels)
                if cur_sig == self._collision_cache_sig:
                    live_set = set(all_panels)
                    live_hits = [
                        (p1, p2, vol)
                        for p1, p2, vol in self._collision_cache_hits
                        if p1 in live_set and p2 in live_set
                    ]
                    issues.extend(issues_from_collision_hits(live_hits))
            except Exception:
                _log.exception("Ошибка проверки кэша коллизий при обновлении списка проблем")

        if hasattr(self.analysis_dock, "set_issues"):
            self.analysis_dock.set_issues(issues)
        else:
            self.analysis_dock.list_widget.clear()
            for iss in issues:
                self.analysis_dock.list_widget.addItem(iss.format_line())

    def _apply_collision_results(
        self,
        vp,
        all_panels: list[Panel],
        hits: list[tuple[Panel, Panel, float | None]],
    ) -> None:
        from core.issues import check_scene_issues, issues_from_collision_hits

        live_set = set(all_panels)
        all_issues = []
        if vp is not None:
            all_issues.extend(check_scene_issues(vp.blocks, include_collisions=False))

        live_hits = []
        for p1, p2, vol in hits:
            if p1 not in live_set or p2 not in live_set:
                continue
            p1.selected = True
            p2.selected = True
            live_hits.append((p1, p2, vol))

        all_issues.extend(issues_from_collision_hits(live_hits))
        if hasattr(self.analysis_dock, "set_issues"):
            self.analysis_dock.set_issues(all_issues)
        else:
            self.analysis_dock.list_widget.clear()
            if all_issues:
                for iss in all_issues:
                    self.analysis_dock.list_widget.addItem(iss.format_line())
            else:
                self.analysis_dock.list_widget.addItem(
                    "✅ Ошибок нет! Замечаний и пересечений деталей не обнаружено."
                )
        if vp is not None:
            vp.update()

    def _on_bg_task_started(self, task_id: int, kind: str, message: str) -> None:
        if not self.bg_tasks.is_latest(task_id, kind):
            return
        if message:
            self.statusBar().showMessage(message, 4000)

    def _on_bg_task_progress(
        self,
        task_id: int,
        kind: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not self.bg_tasks.is_latest(task_id, kind):
            return
        if total > 0:
            pct = int(round(current * 100.0 / max(1, total)))
            text = f"{message} ({pct}%)" if message else f"⏳ Выполнение ({current}/{total}, {pct}%)"
        else:
            text = message
        if text:
            self.statusBar().showMessage(text, 4000)

    def _on_bg_task_finished(self, task_id: int, kind: str, result: object) -> None:
        if not self.bg_tasks.is_latest(task_id, kind):
            return
        if kind == TASK_AUTOSAVE:
            if isinstance(result, Path):
                _log.debug("Background autosave completed: %s", result)
            return
        if kind == TASK_PROJECT_LOAD and isinstance(result, ProjectDataSnapshot):
            try:
                loaded = materialize_project_snapshot(
                    result,
                    progress_cb=lambda cur, tot, msg: self.statusBar().showMessage(msg, 3000),
                )
                self._apply_loaded_project_result(result.path, loaded)
            except Exception as exc:
                _log.exception("Failed to materialize loaded project %s", result.path)
                QMessageBox.critical(self, "Ошибка открытия", str(exc))
            return
        if kind == TASK_COLLISION and isinstance(result, CollisionAnalysisResult):
            self._on_collision_result_ready(result)

    def _on_bg_task_failed(self, task_id: int, kind: str, error_msg: str) -> None:
        if not self.bg_tasks.is_latest(task_id, kind):
            return
        self.statusBar().showMessage(f"⚠️ Ошибка фоновой операции ({kind}): {error_msg}", 6000)
        if kind == TASK_PROJECT_LOAD:
            QMessageBox.critical(self, "Ошибка открытия", error_msg)

    def run_collision_analysis(self, async_run: bool = True):

        vp = self.workspace.current_viewport()
        if not vp:
            return

        self.analysis_dock.list_widget.clear()
        all_panels = [p for b in vp.blocks for p in b.panels]

        # Коллизии строятся из CollisionPanelSnapshot (свой B-Rep в воркере),
        # ждать geometry_pending нельзя — флаг мог зависнуть, анализ «Проблемы» блокировался навсегда.
        pending_n = sum(1 for p in all_panels if getattr(p, "geometry_pending", False))
        if pending_n:
            self.statusBar().showMessage(
                f"⏳ У {pending_n} дет. ещё строится mesh-превью; анализ коллизий всё равно запускается",
                4000,
            )

        snap = CollisionAnalysisSnapshot.from_panels(all_panels, min_volume=0.1)
        scene_sig = snap.scene_sig
        if (
            self._collision_cache_sig == scene_sig
            and self._collision_cache_hits is not None
        ):
            self._apply_collision_results(vp, all_panels, self._collision_cache_hits)
            return

        if async_run:
            self.analysis_dock.list_widget.addItem("⏳ Анализ пересечений…")

        task_id, _snap = self.bg_tasks.submit_collision_analysis(
            snap,
            min_volume=0.1,
            sync=not async_run,
        )
        self._collision_run_seq = task_id

    def _on_collision_result_ready(self, result: CollisionAnalysisResult) -> None:
        vp = self.workspace.current_viewport()
        if not vp:
            return
        all_panels = [p for b in vp.blocks for p in b.panels]
        live_hits = result.resolve_for_panels(all_panels)
        has_errors = any(vol is None for _, _, vol in live_hits)
        self._collision_cache_sig = None if has_errors else result.scene_sig
        self._collision_cache_hits = None if has_errors else live_hits
        self._apply_collision_results(vp, all_panels, live_hits)
        self.statusBar().showMessage(
            f"✅ Анализ пересечений завершён (найдено: {len(live_hits)})",
            4000,
        )

    def _on_collision_worker_finished(
        self,
        run_id: int,
        scene_sig: object,
        hits: object,
    ) -> None:
        if run_id != self._collision_run_seq:
            return
        self._active_collision_worker = None
        vp = self.workspace.current_viewport()
        if not vp:
            return
        all_panels = [p for b in vp.blocks for p in b.panels]
        raw_hits = list(hits) if isinstance(hits, list) else []
        by_uid = {str(getattr(p, "uid", "") or id(p)): p for p in all_panels}
        hits_list: list[tuple[Panel, Panel, float | None]] = []
        for p1, p2, vol in raw_hits:
            rp1 = by_uid.get(str(getattr(p1, "uid", "") or id(p1)), p1)
            rp2 = by_uid.get(str(getattr(p2, "uid", "") or id(p2)), p2)
            if isinstance(rp1, Panel) and isinstance(rp2, Panel):
                hits_list.append((rp1, rp2, vol))
        has_errors = any(vol is None for _, _, vol in hits_list)
        self._collision_cache_sig = (
            scene_sig if (isinstance(scene_sig, tuple) and not has_errors) else None
        )
        self._collision_cache_hits = None if has_errors else hits_list
        self._apply_collision_results(vp, all_panels, hits_list)

    def undo_action(self):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        desc = vp.undo()
        if desc:
            self._refresh_structure()
            sel = vp.get_selected_panel()
            self.properties_dock.show_object_properties(sel)
            if sel:
                self._update_coord_boxes(sel.x, sel.y, sel.z)

    def redo_action(self):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        desc = vp.redo()
        if desc:
            self._refresh_structure()
            sel = vp.get_selected_panel()
            self.properties_dock.show_object_properties(sel)
            if sel:
                self._update_coord_boxes(sel.x, sel.y, sel.z)


    def _update_window_title(self):
        name = self.project_name
        if self.project_path:
            from pathlib import Path
            name = Path(self.project_path).name
        dirty = " *" if getattr(self, "is_modified", False) else ""
        self.setWindowTitle(f"NestCraft Studio - [{name}]{dirty}")
        vp = self.workspace.current_viewport()
        if vp:
            vp.title = name
            idx = self.workspace.indexOf(vp)
            if idx >= 0:
                self.workspace.setTabText(idx, name + dirty)

    def mark_modified(self, modified: bool = True) -> None:
        if self.is_modified != modified:
            self.is_modified = modified
            self._update_window_title()
        if modified:
            self._perform_autosave()
        else:
            clear_autosave()

    def _perform_autosave(self, *, async_run: bool = True) -> None:
        """Снимает копию сцены на UI-потоке и записывает файл автосохранения в QThreadPool (п. 1.11 и 2.4)."""
        if not getattr(self, "is_modified", False):
            return
        vp = self.workspace.current_viewport()
        if not vp:
            return
        try:
            snapshot = create_autosave_snapshot(
                vp.blocks,
                project_name=self.project_name or "Новый проект.b3d",
                original_path=self.project_path,
            )
            self.bg_tasks.submit_autosave(snapshot, sync=not async_run)
        except Exception:
            _log.exception("Background autosave failed")

    def _check_autosave_recovery(self) -> bool:
        """При старте проверяет наличие временного файла после сбоя и предлагает восстановить."""
        if not has_autosave():
            return False
        try:
            res, meta = load_autosave()
        except Exception:
            _log.exception("Failed to read autosave recovery file")
            clear_autosave()
            return False

        proj_label = str(meta.get("project_name") or res.name or "Новый проект.b3d")
        orig_path = str(meta.get("original_path") or "").strip()
        details = f"Проект: «{proj_label}»"
        if orig_path:
            details += f"\nПуть: {orig_path}"

        ans = QMessageBox.question(
            self,
            "Восстановление после сбоя",
            f"Обнаружена резервная копия несохранённого проекта.\n{details}\n\n"
            "Восстановить несохранённые данные?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            clear_autosave()
            return False

        vp = self.workspace.current_viewport()
        if not vp:
            return False
        if hasattr(vp, "_free_all_panel_gpu"):
            vp._free_all_panel_gpu()
        vp.blocks[:] = list(res.blocks)
        vp.undo_stack.clear()
        self.project_path = orig_path if orig_path else None
        self.project_name = proj_label
        self.is_modified = True
        self._update_window_title()
        self._refresh_structure()
        self._refresh_history_dock()
        self.properties_dock.show_object_properties(None)
        vp.update()
        self.statusBar().showMessage(f"Восстановлен проект из автосохранения: {proj_label}", 6000)
        self._show_load_warnings_in_problems_dock(res.warnings)
        return True

    def _confirm_discard_changes(self, action: str = "продолжить") -> bool:
        """True — можно продолжать (нет правок или пользователь согласен)."""
        if not getattr(self, "is_modified", False):
            return True
        r = QMessageBox.question(
            self,
            "Несохранённые изменения",
            f"В проекте есть несохранённые изменения.\nСохранить перед тем, как {action}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            self.save_project_action()
            # если пользователь отменил Save As — path пуст и всё ещё modified
            if self.is_modified:
                return False
        return True

    def closeEvent(self, event):
        if self._confirm_discard_changes("закрыть программу"):
            clear_autosave()
            event.accept()
        else:
            event.ignore()

    def new_project(self):
        if not self._confirm_discard_changes("создать новый проект"):
            return
        self.clear_scene()
        self.project_path = None
        self.project_name = "Новый проект.b3d"
        vp = self.workspace.current_viewport()
        if vp:
            vp.undo_stack.clear()  # clear → _clean_top=None → is_clean True
            vp.undo_stack.mark_clean()
            self._refresh_history_dock()
        self.mark_modified(False)
        clear_autosave()
        self._update_window_title()

    def open_project(self):
        if not self._confirm_discard_changes("открыть другой файл"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", FILE_FILTER)
        if not path:
            return
        self.open_project_from_path(path, confirm_discard=False)

    def _apply_loaded_project_result(self, p_obj: Path, result: ProjectLoadResult | tuple) -> bool:
        if isinstance(result, ProjectLoadResult):
            name, blocks, warnings = result.name, result.blocks, result.warnings
        else:
            name, blocks = result
            warnings = []
        vp = self.workspace.current_viewport()
        if not vp:
            return False
        # Замена сцены без записи в undo: иначе Ctrl+Z вернёт старую сцену
        # при уже новом project_path и следующее Save перезапишет чужой файл.
        if hasattr(vp, "_free_all_panel_gpu"):
            vp._free_all_panel_gpu()
        vp.blocks[:] = list(blocks)
        vp.undo_stack.clear()
        vp.undo_stack.mark_clean()
        self.project_path = str(p_obj.resolve())
        self.project_name = name or p_obj.name
        self.mark_modified(False)
        clear_autosave()
        add_recent_file(self.project_path)
        self._rebuild_recent_files_menu()
        self._update_window_title()
        self._refresh_structure()
        self._refresh_history_dock()
        self.properties_dock.show_object_properties(None)
        vp.update()
        self.statusBar().showMessage(f"✅ Проект загружен: {self.project_name}", 4000)
        self._show_load_warnings_in_problems_dock(warnings)
        return True

    def open_project_from_path(
        self,
        path: str,
        *,
        confirm_discard: bool = True,
        async_load: bool | None = None,
    ) -> bool:
        """Открывает проект по указанному пути через единый механизм фоновых операций (п. 2.4)."""
        if confirm_discard and not self._confirm_discard_changes("открыть другой файл"):
            return False
        p_obj = Path(path)
        if not p_obj.is_file():
            remove_recent_file(path)
            self._rebuild_recent_files_menu()
            QMessageBox.warning(self, "Файл не найден", f"Файл не существует:\n{path}")
            return False

        # Большие файлы (>= 256 КБ) по умолчанию читаем и мигрируем в QThreadPool
        use_async = bool(async_load) if async_load is not None else (p_obj.stat().st_size >= 256 * 1024)
        if use_async:
            self.bg_tasks.submit_project_load(p_obj, sync=False)
            return True

        try:
            result = load_project(
                p_obj,
                progress_cb=lambda cur, tot, msg: self.statusBar().showMessage(msg, 3000),
            )
        except Exception as e:
            _log.exception("open_project failed path=%s", path)
            QMessageBox.critical(self, "Ошибка открытия", str(e))
            return False
        return self._apply_loaded_project_result(p_obj, result)

    def _show_load_warnings_in_problems_dock(self, warnings: list[str] | None) -> None:
        """Собирает предупреждения открытия/восстановления файла в единое окно «Проблемы» (ревизия 2, п. 2.2)."""
        from core.issues import Issue

        extra: list[Issue] = []
        for w in warnings or []:
            # Предупреждения о материалах и кромках уже формируются подетально через check_scene_issues
            if "В каталоге нет материалов" in w or "В каталоге нет кромок" in w:
                continue
            extra.append(Issue(severity="warning", panel_uid="", code="project_load", message=w))
        self._refresh_issues_only(extra_issues=extra)
        if hasattr(self, "analysis_dock") and self.analysis_dock is not None:
            self.analysis_dock.show()
            self.analysis_dock.raise_()
        if warnings:
            self.statusBar().showMessage(
                f"Проект открыт с замечаниями ({len(warnings)}) — см. панель «Проблемы»",
                8000,
            )

    def save_project_action(self):
        if self.project_path:
            self._write_project(self.project_path)
        else:
            self.save_project_as()

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект", self.project_name or "project.b3d", FILE_FILTER
        )
        if not path:
            return
        if not path.lower().endswith((".b3d", ".json")):
            path += ".b3d"
        self._write_project(path)

    def _write_project(self, path: str):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        from pathlib import Path
        try:
            save_project(path, vp.blocks, Path(path).stem)
        except Exception as e:
            _log.exception("save_project failed path=%s", path)
            QMessageBox.critical(self, "Ошибка сохранения", str(e))
            return
        self.project_path = str(Path(path).resolve())
        self.project_name = Path(path).name
        if vp and hasattr(vp, "undo_stack"):
            vp.undo_stack.mark_clean()
        self.mark_modified(False)
        clear_autosave()
        add_recent_file(self.project_path)
        self._rebuild_recent_files_menu()
        self._update_window_title()
        self.statusBar().showMessage(f"Сохранено: {path}", 4000)

    def _rebuild_recent_files_menu(self) -> None:
        """Обновляет подменю «Недавние файлы» в меню «Файл» (план §2.8)."""
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        menu.clear()
        recent = load_recent_files(only_existing=True)
        if not recent:
            empty_act = QAction("(Нет недавних файлов)", self)
            empty_act.setEnabled(False)
            menu.addAction(empty_act)
            return

        for idx, fpath in enumerate(recent, start=1):
            p = Path(fpath)
            act = QAction(f"{idx}. {p.name}  —  {fpath}", self)
            act.setToolTip(fpath)
            act.triggered.connect(lambda _checked=False, target=fpath: self.open_project_from_path(target))
            menu.addAction(act)

        menu.addSeparator()
        act_clear_recent = QAction("Очистить список недавних файлов", self)
        act_clear_recent.triggered.connect(self._on_clear_recent_files)
        menu.addAction(act_clear_recent)

    def _on_clear_recent_files(self) -> None:
        clear_recent_files()
        self._rebuild_recent_files_menu()

    def add_hole_to_selected(self):
        """Крепёж по стыку: сначала конструктор фурнитуры, затем режим стыка."""
        vp = self.workspace.current_viewport()
        if not vp:
            return

        # Конструктор параметрической фурнитуры
        dlg = FastenerConstructorDialog(self)
        if not dlg.exec():
            return
        chosen = dlg.selected_fastener() or {}
        diam = float(chosen.get("diameter", chosen.get("d1", 7.0)))
        depth = float(chosen.get("depth", 42.0))
        # Сохраняем выбор на viewport для последующих постановок
        if hasattr(vp, "fastener_preset_id") and str(getattr(vp, "fastener_preset_id", "")).startswith("dowel"):
            vp.fastener_preset_id = "confirmat_3"
        vp.fastener_diameter = diam
        vp.fastener_depth = depth
        vp._last_fastener_params = dict(chosen)

        panels = vp.get_selected_panels() if hasattr(vp, "get_selected_panels") else []
        if not panels:
            sel = vp.get_selected_panel()
            panels = [sel] if sel else []

        if len(panels) >= 2:
            msg = vp._activate_joint_mode(panels[0], panels[1], diam, depth)
            if msg != "OK":
                QMessageBox.information(self, "Крепёж по стыку", msg)
                return
            self.statusBar().showMessage(
                f"Крепёж ({chosen.get('name', 'конфирмат')}): "
                "Tab — пресет (шаг/отступ), колесо — число, ЛКМ — поставить, Esc — выход",
                12000,
            )
            return

        if len(panels) == 1:
            vp.begin_fastener_pick(panels[0], diameter=diam, depth=depth)
            self.statusBar().showMessage(
                "Крепёж: кликните ВТОРУЮ панель на стыке (Esc — отмена). "
                "Ручная присадка: Инструменты → По координатам…",
                12000,
            )
            return

        QMessageBox.information(
            self,
            "Крепёж по стыку",
            "Фурнитура выбрана.\n"
            "1) Выделите первую панель\n"
            "2) Нажмите Ctrl+H ещё раз\n"
            "3) Кликните вторую панель на стыке\n"
            "4) Tab — пресет раскладки, ЛКМ — поставить массив",
        )

    def _on_fastener_message(self, text: str):
        if not text:
            return
        self.statusBar().showMessage(text, 10000)
        if "⚠️" in text:
            self._refresh_issues_only()
        if text.startswith("Стык не найден"):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Крепёж по стыку", text)

    def _on_measurement_updated(self, msg: str):
        vp = self.workspace.current_viewport()
        if hasattr(self, "act_measure") and vp is not None:
            self.act_measure.setChecked(vp.measure_mode)
        if msg:
            self.statusBar().showMessage(msg, 6000)
        else:
            self.statusBar().clearMessage()

    def toggle_measure_tool(self, checked: bool | None = None):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        if checked is None or not isinstance(checked, bool):
            is_active = vp.toggle_measure_mode()
        else:
            if checked:
                vp.start_measure_mode()
            else:
                vp.stop_measure_mode()
            is_active = vp.measure_mode
        if hasattr(self, "act_measure"):
            self.act_measure.setChecked(is_active)

    def clear_dimensions_action(self):
        vp = self.workspace.current_viewport()
        if vp:
            vp.clear_dimensions()

    def start_drag_move_tool(self):
        """Запускает режим перемещения детали мышкой кликом (G)."""
        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        vp.start_drag_mode(sel)

    def add_hole_manual(self):
        """Старый диалог присадки по координатам на одной панели."""
        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        if not sel:
            QMessageBox.information(self, "Присадка", "Сначала выберите одну панель.")
            return
        dlg = HoleDialog(sel, self)
        if not dlg.exec():
            return
        hole = dlg.get_hole()
        old_holes = list(sel.holes)
        new_holes = old_holes + [hole]
        vp.undo_stack.push(
            SetHolesCommand(sel, old_holes, new_holes, f"Присадка Ø{hole[3]*2:.0f} на {sel.name}"),
            execute=True,
        )
        self.properties_dock.show_object_properties(sel)
        vp.update()

    def open_catalog_browser(self):
        """Открывает окно библиотеки материалов и крепежа."""
        from ui.catalog_browser import CatalogBrowserDialog
        from models.panel import Panel

        vp = self.workspace.current_viewport()
        sel = vp.get_selected_panel() if vp else None
        target_name = sel.name if isinstance(sel, Panel) else ""

        dlg = CatalogBrowserDialog(self, target_panel_name=target_name)
        dlg.material_assign_requested.connect(
            lambda mid: self._assign_material_from_catalog(mid, dlg)
        )
        dlg.edge_assign_requested.connect(
            lambda eid, side: self._assign_edge_from_catalog(eid, side, dlg)
        )
        dlg.exec()

    def _assign_edge_from_catalog(self, edge_id: str, side: str = "all", dlg=None):
        """Наносит кромку из каталога на выделенную деталь (с Undo)."""
        from models.panel import Panel
        from core.undo import EditPropertyCommand
        from core.catalog import CatalogService

        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        if not isinstance(sel, Panel):
            QMessageBox.information(
                self, "Нанесение кромки",
                "Сначала выделите деталь в сцене.",
            )
            return

        edge = CatalogService.instance().get_edge(edge_id)
        if edge is None:
            QMessageBox.warning(self, "Нанесение кромки", "Кромка не найдена в каталоге.")
            return

        attr_name = "edges_all" if side == "all" else f"edge_{side}"
        old_val = dict(sel.edges) if side == "all" else sel.edges.get(side, "")
        cmd = EditPropertyCommand(sel, attr_name, old_val, edge_id)
        vp.undo_stack.push(cmd, execute=True)
        self.properties_dock.show_object_properties(sel)
        vp.update()

        side_names = {
            "all": "на все 4 стороны",
            "top": "на верхний торец",
            "bottom": "на нижний торец",
            "left": "на левый торец",
            "right": "на правый торец",
        }
        where = side_names.get(side, f"на сторону «{side}»")
        self.statusBar().showMessage(
            f"Кромка «{edge.display_name}» нанесена {where} детали «{sel.name}»", 5000
        )
        if dlg is not None and hasattr(dlg, "_update_assign_button"):
            dlg._target_panel_name = sel.name
            dlg._update_assign_button()

    def _assign_material_from_catalog(self, material_id: str, dlg=None):
        """Назначает материал из библиотеки на выделенную панель (с Undo)."""
        from models.panel import Panel
        from core.undo import EditPropertyCommand
        from core.catalog import CatalogService

        vp = self.workspace.current_viewport()
        if not vp:
            return
        sel = vp.get_selected_panel()
        if not isinstance(sel, Panel):
            QMessageBox.information(
                self, "Назначение материала",
                "Сначала выделите панель в сцене.",
            )
            return

        mat = CatalogService.instance().get_material(material_id)
        if mat is None:
            QMessageBox.warning(self, "Назначение материала", "Материал не найден в каталоге.")
            return

        if getattr(sel, "material_id", None) == material_id:
            self.statusBar().showMessage(
                f"Панель «{sel.name}» уже с материалом «{mat.display_name}»", 4000
            )
            return

        old_display = sel.material
        cmd = EditPropertyCommand(sel, "material", old_display, material_id)
        vp.undo_stack.push(cmd, execute=True)
        self.properties_dock.show_object_properties(sel)
        vp.update()
        self.statusBar().showMessage(
            f"Материал «{mat.display_name}» назначен на «{sel.name}»", 5000
        )
        if dlg is not None and hasattr(dlg, "_update_assign_button"):
            dlg._target_panel_name = sel.name
            dlg._update_assign_button()

    def _create_menu_bar(self):

        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("Файл")
        act_new = QAction("Новый пустой проект", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self.new_project)
        file_menu.addAction(act_new)

        act_open = QAction("Открыть…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.open_project)
        file_menu.addAction(act_open)

        self.recent_menu = file_menu.addMenu("Недавние файлы")
        self._rebuild_recent_files_menu()

        act_save = QAction("Сохранить", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.save_project_action)
        file_menu.addAction(act_save)

        act_save_as = QAction("Сохранить как…", self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.triggered.connect(self.save_project_as)
        file_menu.addAction(act_save_as)

        file_menu.addSeparator()
        act_clear = QAction("Очистить сцену", self)
        act_clear.triggered.connect(self.clear_scene)
        file_menu.addAction(act_clear)

        edit_menu = menubar.addMenu("Правка")
        act_undo = QAction("Отменить (Ctrl+Z)", self)
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.triggered.connect(self.undo_action)
        edit_menu.addAction(act_undo)

        act_redo = QAction("Повторить (Ctrl+Y)", self)
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.triggered.connect(self.redo_action)
        edit_menu.addAction(act_redo)

        edit_menu.addSeparator()
        self.act_copy = QAction("Копировать (Ctrl+C)", self)
        self.act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.act_copy.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.act_copy.triggered.connect(self.copy_selection_action)
        edit_menu.addAction(self.act_copy)

        self.act_paste = QAction("Вставить (Ctrl+V)", self)
        self.act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self.act_paste.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.act_paste.triggered.connect(self.paste_selection_action)
        edit_menu.addAction(self.act_paste)

        act_dup = QAction("Дублировать деталь (Ctrl+D)", self)
        act_dup.setShortcut(QKeySequence("Ctrl+D"))
        act_dup.triggered.connect(self.duplicate_selected_panel)
        edit_menu.addAction(act_dup)

        act_del = QAction("Удалить", self)
        act_del.setShortcut(QKeySequence.StandardKey.Delete)
        act_del.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        act_del.triggered.connect(self.delete_selection)
        edit_menu.addAction(act_del)

        self.act_drag = QAction(QIcon(str(_ICONS_DIR / "tool_move.svg")), "Переместить мышкой", self)
        self.act_drag.setShortcut(QKeySequence("G"))
        self.act_drag.setToolTip("Переместить мышкой (G)")
        self.act_drag.triggered.connect(self.start_drag_move_tool)
        edit_menu.addAction(self.act_drag)

        view_menu = menubar.addMenu("Вид")
        for title, code, shortcut in [
            ("3D Изометрия", "iso", "F5"),
            ("Вид спереди (XY)", "front", "F1"),
            ("Вид сверху (XZ)", "top", "F2"),
            ("Вид слева (ZY)", "left", "F3"),
            ("Вид справа (ZY)", "right", "F4"),
        ]:
            a = QAction(f"{title} ({shortcut})", self)
            a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(lambda checked, c=code: self._set_standard_view(c))
            view_menu.addAction(a)

        view_menu.addSeparator()
        self.act_ghost_others = QAction("👁 Призраки окружения (Isolate)", self)
        self.act_ghost_others.setCheckable(True)
        self.act_ghost_others.setShortcut(QKeySequence("I"))
        self.act_ghost_others.setToolTip(
            "Приглушить невыделенные детали (alpha=0.18, клик сквозь внешние стенки к внутренним полкам и стыкам) [I]"
        )
        self.act_ghost_others.triggered.connect(self._toggle_ghost_others)
        view_menu.addAction(self.act_ghost_others)

        self.act_section = QAction("🔪 Сечение 3D-вида (GL Clip)", self)
        self.act_section.setCheckable(True)
        self.act_section.setShortcut(QKeySequence("Alt+S"))
        self.act_section.setToolTip(
            "Аппаратное 3D-сечение сцены (GL_CLIP_DISTANCE0) для рентгеновского контроля узлов и сверловки [Alt+S]"
        )
        self.act_section.triggered.connect(self._toggle_section_mode)
        view_menu.addAction(self.act_section)

        tools_menu = menubar.addMenu("Инструменты")
        self.act_measure = QAction(QIcon(str(_ICONS_DIR / "tool_measure.svg")), "Рулетка / Измерения", self)
        self.act_measure.setCheckable(True)
        self.act_measure.setShortcut(QKeySequence("M"))
        self.act_measure.setToolTip("Рулетка / Измерения (M)")
        self.act_measure.triggered.connect(self.toggle_measure_tool)
        tools_menu.addAction(self.act_measure)

        self.act_clear_dims = QAction(QIcon(str(_ICONS_DIR / "tool_clear_dims.svg")), "Очистить размерные линии", self)
        self.act_clear_dims.setToolTip("Очистить размерные линии")
        self.act_clear_dims.triggered.connect(self.clear_dimensions_action)
        tools_menu.addAction(self.act_clear_dims)

        tools_menu.addSeparator()

        act_hole = QAction(QIcon(str(_ICONS_DIR / "tool_fastener.svg")), "Крепёж по стыку (Ctrl+H)", self)
        act_hole.setShortcut(QKeySequence("Ctrl+H"))
        act_hole.setToolTip("Крепёж по стыку (Ctrl+H)")
        act_hole.triggered.connect(self.add_hole_to_selected)
        tools_menu.addAction(act_hole)
        act_hole_manual = QAction("Присадка по координатам…", self)
        act_hole_manual.triggered.connect(self.add_hole_manual)
        tools_menu.addAction(act_hole_manual)

        tools_menu.addSeparator()
        act_catalog = QAction("📚 Библиотека материалов и крепежа…", self)
        act_catalog.setShortcut(QKeySequence("Ctrl+Shift+M"))
        act_catalog.triggered.connect(self.open_catalog_browser)
        tools_menu.addAction(act_catalog)

        for menu_name in ["Изделие", "Скрипты"]:
            menubar.addMenu(menu_name)

        help_menu = menubar.addMenu("Справка")
        act_whats_new = QAction("Что нового…", self)
        act_whats_new.triggered.connect(self._show_whats_new)
        help_menu.addAction(act_whats_new)
        act_logs = QAction("Открыть папку логов…", self)
        act_logs.triggered.connect(self._open_log_folder)
        help_menu.addAction(act_logs)
        act_about = QAction("О программе…", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _create_toolbars(self):
        # Верхняя панель 1: Проект + Переключатель видов (2D / 3D) + Режим каркаса + Рулетка
        top_tb1 = QToolBar("Основная панель и Виды")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, top_tb1)

        act_clear = QAction("🧹 Сцена с нуля", self)
        act_clear.triggered.connect(self.clear_scene)
        top_tb1.addAction(act_clear)
        top_tb1.addSeparator()

        # Кнопки быстрого переключения проекций
        view_buttons = [
            ("🧊 3D Изометрия", "iso"),
            ("📐 Спереди", "front"),
            ("📐 Сверху", "top"),
            ("📐 Слева", "left"),
            ("📐 Справа", "right"),
            ("📐 Сзади", "back"),
        ]
        for label, code in view_buttons:
            btn = QAction(label, self)
            btn.triggered.connect(lambda checked, c=code: self._set_standard_view(c))
            top_tb1.addAction(btn)

        top_tb1.addSeparator()

        self.act_grid = QAction("▦ Сетка", self)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_grid.setToolTip(
            "Сетка только в 2D-видах (спереди/сверху/сбоку). "
            "Когда включена, перенос панели (G и стрелки) идёт по шагу сетки."
        )
        self.act_grid.triggered.connect(self._toggle_grid)
        top_tb1.addAction(self.act_grid)

        self.act_face_snap = QAction("📐 Грань↔грань", self)
        self.act_face_snap.setCheckable(True)
        self.act_face_snap.setChecked(True)
        self.act_face_snap.setToolTip(
            "При перемещении (G) притягивать панель гранью к грани другой детали. "
            "Снимите галочку, чтобы отключить."
        )
        self.act_face_snap.triggered.connect(self._toggle_face_snap)
        top_tb1.addAction(self.act_face_snap)

        # Режимы отображения: заливка / каркас / X-Ray (скрытые рёбра серые)
        self.act_wireframe = QAction("🔲 Каркас", self)
        self.act_wireframe.setCheckable(True)
        self.act_wireframe.triggered.connect(self._toggle_wireframe)
        top_tb1.addAction(self.act_wireframe)

        self.act_xray = QAction("👻 X-Ray (скрытые серые)", self)
        self.act_xray.setCheckable(True)
        self.act_xray.setToolTip(
            "Прозрачный вид: видимые рёбра тёмные, скрытые — светло-серые"
        )
        self.act_xray.triggered.connect(self._toggle_xray)
        top_tb1.addAction(self.act_xray)

        top_tb1.addAction(self.act_ghost_others)
        top_tb1.addAction(self.act_section)

        top_tb1.addSeparator()
        top_tb1.addAction(self.act_measure)
        top_tb1.addAction(self.act_drag)

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)

        # Верхняя панель 2: Координаты X, Y, Z и Шаг перемещения стрелками
        top_tb2 = QToolBar("Координаты и Шаг")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, top_tb2)
        
        self.coord_edits = {}
        for coord, val in [("X", "0.0"), ("Y", "0.0"), ("Z", "0.0")]:
            top_tb2.addWidget(QLabel(f"  <b>{coord}:</b> "))
            le = QLineEdit(val)
            le.setFixedWidth(65)
            le.returnPressed.connect(self._apply_coord_boxes)
            top_tb2.addWidget(le)
            self.coord_edits[coord] = le

        top_tb2.addSeparator()
        top_tb2.addWidget(QLabel("  <b>Шаг сдвига (стрелки):</b> "))
        self.step_combo = QComboBox()
        for s in ["1 мм", "10 мм", "16 мм (Толщина ЛДСП)", "50 мм", "100 мм"]:
            self.step_combo.addItem(s)
        self.step_combo.setCurrentIndex(3) # По умолчанию 50 мм
        self.step_combo.currentTextChanged.connect(self._on_step_changed)
        top_tb2.addWidget(self.step_combo)

        top_tb2.addSeparator()
        top_tb2.addWidget(QLabel("  <b>Шаг сетки:</b> "))
        self.grid_step_combo = QComboBox()
        for s in ["1 мм", "10 мм", "16 мм", "32 мм", "50 мм", "100 мм"]:
            self.grid_step_combo.addItem(s)
        self.grid_step_combo.setCurrentIndex(4)  # 50 мм
        self.grid_step_combo.setToolTip("Шаг сетки в 2D и шаг привязки панели, когда сетка включена")
        self.grid_step_combo.currentTextChanged.connect(self._on_grid_step_changed)
        top_tb2.addWidget(self.grid_step_combo)

        top_tb2.addSeparator()
        top_tb2.addWidget(QLabel("  <b>Сечение:</b> "))
        self.section_axis_combo = QComboBox()
        self.section_axis_combo.addItem("Z (Глубина)", "Z")
        self.section_axis_combo.addItem("X (Ширина)", "X")
        self.section_axis_combo.addItem("Y (Высота)", "Y")
        self.section_axis_combo.setToolTip("Ось аппаратной плоскости сечения (GL_CLIP_DISTANCE0)")
        self.section_axis_combo.currentIndexChanged.connect(self._on_section_axis_changed)
        top_tb2.addWidget(self.section_axis_combo)

        self.section_flip_btn = QToolButton()
        self.section_flip_btn.setText("⇄")
        self.section_flip_btn.setCheckable(True)
        self.section_flip_btn.setToolTip("Инвертировать отсекаемую половину сцены")
        self.section_flip_btn.toggled.connect(self._on_section_flip_toggled)
        top_tb2.addWidget(self.section_flip_btn)

        self.section_slider = QSlider(Qt.Orientation.Horizontal)
        self.section_slider.setRange(0, 100)
        self.section_slider.setValue(50)
        self.section_slider.setFixedWidth(110)
        self.section_slider.setToolTip("Глубина плоскости сечения (0..100% габарита сцены или Alt+колесо мыши)")
        self.section_slider.valueChanged.connect(self._on_section_slider_changed)
        top_tb2.addWidget(self.section_slider)

        # Левая вертикальная панель построения панелей
        left_tb = QToolBar("Инструменты построения")
        left_tb.setIconSize(QSize(32, 32))
        left_tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, left_tb)

        icon_vert = QIcon(str(_ICONS_DIR / "vertical_panel.svg"))
        act_vert = QAction(icon_vert, "Вертикальная панель", self)
        act_vert.setToolTip("Добавить вертикальную панель")
        act_vert.triggered.connect(lambda: self.add_new_panel("vertical"))
        left_tb.addAction(act_vert)

        icon_hor = QIcon(str(_ICONS_DIR / "horizontal_panel.svg"))
        act_hor = QAction(icon_hor, "Горизонтальная панель", self)
        act_hor.setToolTip("Добавить горизонтальную панель")
        act_hor.triggered.connect(lambda: self.add_new_panel("horizontal"))
        left_tb.addAction(act_hor)

        icon_front = QIcon(str(_ICONS_DIR / "frontal_panel.svg"))
        act_front = QAction(icon_front, "Фронтальная панель", self)
        act_front.setToolTip("Добавить фронтальную панель")
        act_front.triggered.connect(lambda: self.add_new_panel("frontal"))
        left_tb.addAction(act_front)

        left_tb.addSeparator()
        act_hole_btn = QAction(QIcon(str(_ICONS_DIR / "tool_fastener.svg")), "Крепёж по стыку", self)
        act_hole_btn.setToolTip("Крепёж по стыку (Ctrl+H)")
        act_hole_btn.setShortcut(QKeySequence("Ctrl+H"))
        act_hole_btn.triggered.connect(self.add_hole_to_selected)
        left_tb.addAction(act_hole_btn)

        left_tb.addSeparator()
        act_dup_btn = QAction(QIcon(str(_ICONS_DIR / "tool_duplicate.svg")), "Дублировать", self)
        act_dup_btn.setToolTip("Дублировать (Ctrl+D)")
        act_dup_btn.triggered.connect(self.duplicate_selected_panel)
        left_tb.addAction(act_dup_btn)

        left_tb.addAction(self.act_drag)

        left_tb.addSeparator()
        left_tb.addAction(self.act_measure)
        left_tb.addAction(self.act_clear_dims)

    def _set_standard_view(self, view_code: str):
        vp = self.workspace.current_viewport()
        if vp:
            vp.set_Standard_view(view_code)

    def _toggle_wireframe(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        if checked:
            self.act_xray.blockSignals(True)
            self.act_xray.setChecked(False)
            self.act_xray.blockSignals(False)
            vp.display_mode = "wireframe"
            vp.wireframe_only = True
        else:
            vp.display_mode = "solid"
            vp.wireframe_only = False
        vp.update()

    def _toggle_xray(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        if checked:
            self.act_wireframe.blockSignals(True)
            self.act_wireframe.setChecked(False)
            self.act_wireframe.blockSignals(False)
            vp.display_mode = "xray"
            vp.wireframe_only = False
        else:
            vp.display_mode = "solid"
            vp.wireframe_only = False
        vp.update()

    def _on_step_changed(self, text: str):
        vp = self.workspace.current_viewport()
        if vp:
            val = float(text.split()[0])
            vp.move_step = val

    def _toggle_grid(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.grid_enabled = bool(checked)
        vp.update()

    def _toggle_face_snap(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.face_snap_enabled = bool(checked)

    def _on_grid_step_changed(self, text: str):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        try:
            vp.grid_step = float(text.split()[0])
        except ValueError:
            return
        vp._grid_cache_key = None
        vp.update()

    def _toggle_ghost_others(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        state = vp.toggle_ghost_others_mode(bool(checked))
        self.act_ghost_others.blockSignals(True)
        self.act_ghost_others.setChecked(state)
        self.act_ghost_others.blockSignals(False)

    def _toggle_section_mode(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        state = vp.toggle_section_mode(bool(checked))
        self.act_section.blockSignals(True)
        self.act_section.setChecked(state)
        self.act_section.blockSignals(False)

    def _on_section_axis_changed(self, _index: int):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        axis = str(self.section_axis_combo.currentData() or "Z")
        vp.set_section_axis(axis)

    def _on_section_flip_toggled(self, checked: bool):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.section_flip = bool(checked)
        if vp.section_enabled:
            vp.set_section_ratio(vp.section_ratio)
        else:
            vp.update()

    def _on_section_slider_changed(self, value: int):
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.set_section_ratio(float(value) / 100.0)
        if not vp.section_enabled:
            state = vp.toggle_section_mode(True)
            self.act_section.blockSignals(True)
            self.act_section.setChecked(state)
            self.act_section.blockSignals(False)

    def _focus_is_text_input(self) -> bool:
        """True, если фокус в поле ввода — Delete не должен сносить деталь."""
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        if isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(fw, QComboBox) and fw.isEditable():
            le = fw.lineEdit()
            if le is not None and (le.hasFocus() or fw.hasFocus()):
                return True
        return False

    def copy_selection_action(self) -> None:
        """Копирует выделенные панели/блоки в буфер сцены (Ctrl+C)."""
        if self._focus_is_text_input():
            fw = QApplication.focusWidget()
            if isinstance(fw, QAbstractSpinBox) and fw.lineEdit() is not None:
                fw.lineEdit().copy()
            elif hasattr(fw, "copy") and callable(fw.copy):
                fw.copy()
            return
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.copy_selection()
        vp.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def paste_selection_action(self) -> None:
        """Включает режим вставки из буфера сцены (Ctrl+V)."""
        if self._focus_is_text_input():
            fw = QApplication.focusWidget()
            if isinstance(fw, QAbstractSpinBox) and fw.lineEdit() is not None:
                fw.lineEdit().paste()
            elif hasattr(fw, "paste") and callable(fw.paste):
                fw.paste()
            return
        vp = self.workspace.current_viewport()
        if not vp:
            return
        vp.begin_paste_mode()
        vp.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def delete_selection(self) -> bool:
        """Удаляет выделенное в текущем viewport. False — ничего не удалено."""
        if self._focus_is_text_input():
            return False
        vp = self.workspace.current_viewport()
        if not vp:
            return False
        if vp.delete_selected():
            self._refresh_structure()
            self.properties_dock.show_object_properties(None)
            # Фокус обратно во viewport, чтобы следующий Delete тоже сработал
            vp.setFocus(Qt.FocusReason.ShortcutFocusReason)
            return True
        return False

    def keyPressEvent(self, event):
        is_del = event.key() == Qt.Key.Key_Delete or (
            sys.platform == "darwin" and event.key() == Qt.Key.Key_Backspace
        )
        if is_del:
            if self._focus_is_text_input():
                super().keyPressEvent(event)
                return
            if self.delete_selection():
                event.accept()
                return
        super().keyPressEvent(event)

    def _create_dock_panels(self):
        self.structure_dock = StructureDock(self)
        self.properties_dock = PropertiesDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.structure_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.properties_dock)
        self.splitDockWidget(self.structure_dock, self.properties_dock, Qt.Orientation.Vertical)

        self.browser_dock = BrowserDock(self)
        self.joints_dock = JointsDock(self)
        self.analysis_dock = AnalysisDock(self)
        self.history_dock = HistoryDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.browser_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.joints_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.analysis_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.history_dock)
        self.splitDockWidget(self.browser_dock, self.joints_dock, Qt.Orientation.Vertical)
        self.splitDockWidget(self.joints_dock, self.analysis_dock, Qt.Orientation.Vertical)
        self.splitDockWidget(self.analysis_dock, self.history_dock, Qt.Orientation.Vertical)


    def _open_log_folder(self) -> None:
        """Справка → Открыть папку логов: проводник по фактическому пути log-файла."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from core.logging_setup import log_file_path, setup_logging

        path = log_file_path()
        if path is None or not path.parent.exists():
            path = setup_logging()
        folder = path.parent
        folder.mkdir(parents=True, exist_ok=True)
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
        if ok:
            self.statusBar().showMessage(f"Папка логов: {folder}", 8000)
        else:
            QMessageBox.information(
                self,
                "Папка логов",
                f"Не удалось открыть проводник.\n\nЛог-файл:\n{path}\n\nПапка:\n{folder}",
            )

    def _show_whats_new(self):
        from ui.whats_new_dialog import WhatsNewDialog
        WhatsNewDialog(self).exec()

    def _show_about(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("О программе — NestCraft Studio")
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)

        row = QHBoxLayout()
        logo_path = _ICONS_DIR / "logo.svg"
        if logo_path.is_file():
            icon_lbl = QLabel()
            icon_lbl.setPixmap(QIcon(str(logo_path)).pixmap(QSize(96, 96)))
            icon_lbl.setFixedSize(96, 96)
            row.addWidget(icon_lbl)

        text = QLabel(
            "<h2 style='margin:0'>NestCraft Studio</h2>"
            "<p style='margin:4px 0 0 0;color:#666'>Проектирование корпусной мебели</p>"
            f"<p style='margin:12px 0 0 0'>Версия <b>{APP_VERSION}</b></p>"
            "<p style='color:#888;font-size:11px'>B-Rep · OpenGL · каталог · кромка · крепёж</p>"
        )
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        layout.addLayout(row)

        btn = QPushButton("Закрыть")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _create_status_bar(self):
        status = QStatusBar()
        self.setStatusBar(status)
        mat_label = QLabel("Крепёж: панель → Ctrl+H → вторая панель → мышь + ЛКМ | Esc | Ctrl+Z")
        status.addWidget(mat_label)