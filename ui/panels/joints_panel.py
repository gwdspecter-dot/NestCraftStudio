"""Панель управления параметрическими стыками (ревизия 2, п. 3.1)."""

from __future__ import annotations

from typing import Any, Callable

try:
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtWidgets import (
        QComboBox,
        QDockWidget,
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # Headless / тестовый режим без PyQt6
    class _HeadlessSignalInstance:
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

    class _HeadlessSignalDescriptor:
        def __init__(self, *_types: Any) -> None:
            self._attr_name = ""

        def __set_name__(self, owner: Any, name: str) -> None:
            self._attr_name = f"__jd_sig_{name}"

        def __get__(self, instance: Any, owner: Any = None) -> Any:
            if instance is None:
                return self
            sig = getattr(instance, self._attr_name, None)
            if sig is None:
                sig = _HeadlessSignalInstance()
                setattr(instance, self._attr_name, sig)
            return sig

    def pyqtSignal(*types: Any) -> Any:  # type: ignore[misc]
        return _HeadlessSignalDescriptor(*types)

    class Qt:  # type: ignore[no-redef]
        class DockWidgetArea:
            LeftDockWidgetArea = 1
            RightDockWidgetArea = 2

        class ItemDataRole:
            UserRole = 256

    class QWidget:  # type: ignore[no-redef]
        def __init__(self, parent: Any = None) -> None:
            self._parent = parent
            self._enabled = True
            self._tooltip = ""

        def setEnabled(self, enabled: bool) -> None:
            self._enabled = bool(enabled)

        def isEnabled(self) -> bool:
            return self._enabled

        def setToolTip(self, text: str) -> None:
            self._tooltip = str(text)

    class QDockWidget(QWidget):  # type: ignore[no-redef]
        def __init__(self, title: str = "", parent: Any = None) -> None:
            super().__init__(parent)
            self._title = str(title)
            self._widget: Any = None

        def setAllowedAreas(self, _areas: Any) -> None:
            pass

        def setWidget(self, w: Any) -> None:
            self._widget = w

        def setWindowTitle(self, title: str) -> None:
            self._title = str(title)

        def windowTitle(self) -> str:
            return self._title

    class QVBoxLayout:  # type: ignore[no-redef]
        def __init__(self, _parent: Any = None) -> None:
            pass

        def setContentsMargins(self, *_args: Any) -> None:
            pass

        def setSpacing(self, *_args: Any) -> None:
            pass

        def addLayout(self, *_args: Any) -> None:
            pass

        def addWidget(self, *_args: Any) -> None:
            pass

    class QHBoxLayout(QVBoxLayout):  # type: ignore[no-redef]
        pass

    class QFormLayout(QVBoxLayout):  # type: ignore[no-redef]
        def addRow(self, *_args: Any) -> None:
            pass

    class QLabel(QWidget):  # type: ignore[no-redef]
        def __init__(self, text: str = "", parent: Any = None) -> None:
            super().__init__(parent)
            self._text = str(text)

    class QPushButton(QWidget):  # type: ignore[no-redef]
        clicked = pyqtSignal()

        def __init__(self, text: str = "", parent: Any = None) -> None:
            super().__init__(parent)
            self._text = str(text)

    class QListWidgetItem:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self._text = str(text)
            self._data: dict[int, Any] = {}

        def text(self) -> str:
            return self._text

        def setData(self, role: int, value: Any) -> None:
            self._data[int(role)] = value

        def data(self, role: int) -> Any:
            return self._data.get(int(role))

    class QListWidget(QWidget):  # type: ignore[no-redef]
        currentItemChanged = pyqtSignal(object, object)

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._items: list[QListWidgetItem] = []
            self._current_row: int = -1

        def clear(self) -> None:
            self._items.clear()
            self._current_row = -1

        def addItem(self, item: QListWidgetItem | str) -> None:
            it = item if isinstance(item, QListWidgetItem) else QListWidgetItem(str(item))
            self._items.append(it)

        def count(self) -> int:
            return len(self._items)

        def item(self, row: int) -> QListWidgetItem | None:
            if 0 <= row < len(self._items):
                return self._items[row]
            return None

        def currentItem(self) -> QListWidgetItem | None:
            return self.item(self._current_row)

        def setCurrentRow(self, row: int) -> None:
            prev = self.currentItem()
            self._current_row = int(row) if 0 <= int(row) < len(self._items) else -1
            cur = self.currentItem()
            self.currentItemChanged.emit(cur, prev)

    class QComboBox(QWidget):  # type: ignore[no-redef]
        currentIndexChanged = pyqtSignal(int)

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._entries: list[tuple[str, Any]] = []
            self._index: int = -1

        def addItem(self, text: str, userData: Any = None) -> None:
            self._entries.append((str(text), userData))
            if self._index < 0:
                self._index = 0

        def findData(self, data: Any) -> int:
            for idx, (_txt, ud) in enumerate(self._entries):
                if ud == data:
                    return idx
            return -1

        def itemData(self, index: int) -> Any:
            if 0 <= index < len(self._entries):
                return self._entries[index][1]
            return None

        def currentIndex(self) -> int:
            return self._index

        def setCurrentIndex(self, index: int) -> None:
            self._index = int(index)
            self.currentIndexChanged.emit(self._index)

    class QDoubleSpinBox(QWidget):  # type: ignore[no-redef]
        editingFinished = pyqtSignal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._val: float = 0.0

        def setRange(self, _lo: float, _hi: float) -> None:
            pass

        def setDecimals(self, _d: int) -> None:
            pass

        def setSingleStep(self, _s: float) -> None:
            pass

        def setSpecialValueText(self, _t: str) -> None:
            pass

        def setSuffix(self, _s: str) -> None:
            pass

        def setValue(self, val: float) -> None:
            self._val = float(val)

        def value(self) -> float:
            return self._val

    class QSpinBox(QWidget):  # type: ignore[no-redef]
        editingFinished = pyqtSignal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._val: int = 1

        def setRange(self, _lo: int, _hi: int) -> None:
            pass

        def setValue(self, val: int) -> None:
            self._val = int(val)

        def value(self) -> int:
            return self._val

from core.joint import FASTENER_PRESET_ORDER, JointRecord, get_fastener_preset


class JointsDock(QDockWidget):
    """Док-панель «Стыки»: список параметрических стыков, смена пресета, шага, отступов и удаление."""

    joint_selected = pyqtSignal(object, str)  # (block, joint_uid)
    joint_modified = pyqtSignal(object, str, dict, dict)  # (block, joint_uid, old_state, new_state)
    joint_deleted = pyqtSignal(object, str)  # (block, joint_uid)
    add_joint_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Стыки", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.blocks_ref: list = []
        self._updating_ui = False

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self.btn_add = QPushButton("➕ Добавить стык (2 панели)")
        self.btn_add.setToolTip("Создать параметрический стык между двумя выделенными панелями")
        self.btn_add.clicked.connect(self.add_joint_requested.emit)
        top_row.addWidget(self.btn_add)

        self.btn_delete = QPushButton("🗑 Удалить стык")
        self.btn_delete.setToolTip("Удалить выбранный стык и все созданные им отверстия")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_selected_joint)
        top_row.addWidget(self.btn_delete)
        layout.addLayout(top_row)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self.list_widget, 1)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 2, 0, 0)
        form.setSpacing(4)

        self.preset_combo = QComboBox()
        for pid in FASTENER_PRESET_ORDER:
            preset = get_fastener_preset(pid)
            label = preset.get("label", pid) if preset else pid
            self.preset_combo.addItem(str(label), pid)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_combo_changed)
        form.addRow(QLabel("Пресет:"), self.preset_combo)

        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(0.0, 2000.0)
        self.pitch_spin.setDecimals(1)
        self.pitch_spin.setSingleStep(16.0)
        self.pitch_spin.setSpecialValueText("Равномерно (авто)")
        self.pitch_spin.setSuffix(" мм")
        self.pitch_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Шаг:"), self.pitch_spin)

        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(5.0, 500.0)
        self.margin_spin.setDecimals(1)
        self.margin_spin.setSingleStep(5.0)
        self.margin_spin.setValue(50.0)
        self.margin_spin.setSuffix(" мм")
        self.margin_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Отступ:"), self.margin_spin)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 20)
        self.count_spin.setValue(3)
        self.count_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Точек:"), self.count_spin)

        layout.addWidget(form_widget)
        self._set_controls_enabled(False)
        self.setWidget(container)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.preset_combo.setEnabled(enabled)
        self.pitch_spin.setEnabled(enabled)
        self.margin_spin.setEnabled(enabled)
        self.count_spin.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    @staticmethod
    def _format_joint_item(block, jr: JointRecord) -> str:
        by_uid = {
            str(getattr(p, "uid", "")): getattr(p, "name", "Панель")
            for p in getattr(block, "panels", []) or []
        }
        name_a = by_uid.get(jr.panel_a_uid, jr.panel_a_uid[:8])
        name_b = by_uid.get(jr.panel_b_uid, jr.panel_b_uid[:8])
        preset = get_fastener_preset(jr.preset_id)
        preset_lbl = preset.get("label", jr.preset_id) if preset else (jr.preset_id or "Крепёж")
        pitch = jr.params.get("pitch")
        margin = float(jr.params.get("margin", 50.0) or 50.0)
        count = int(jr.params.get("count", 3) or 3)
        if pitch is not None and float(pitch) > 0:
            step_txt = f"шаг {float(pitch):g} мм"
        else:
            step_txt = f"×{count}"
        return f"🔩 {name_a} ↔ {name_b} [{preset_lbl}, {step_txt}, отст. {margin:g} мм]"

    def load_joints(self, blocks: list) -> None:
        """Обновляет список стыков по всем блокам сцены."""
        prev_block, prev_uid = self.current_joint_ref()
        self.blocks_ref = list(blocks or [])

        self._updating_ui = True
        try:
            self.list_widget.clear()
            total = 0
            selected_row = -1
            for b in self.blocks_ref:
                by_uid = {
                    str(getattr(p, "uid", "") or ""): p
                    for p in getattr(b, "panels", []) or []
                    if str(getattr(p, "uid", "") or "")
                }
                for jr in getattr(b, "joints", None) or []:
                    rec = jr if isinstance(jr, JointRecord) else JointRecord.from_dict(jr)
                    txt = self._format_joint_item(b, rec)
                    broken = False
                    pa = by_uid.get(str(rec.panel_a_uid or ""))
                    pb = by_uid.get(str(rec.panel_b_uid or ""))
                    if pa is None or pb is None:
                        broken = True
                        txt = "⚠ " + txt + " [нет детали]"
                    else:
                        try:
                            from core.joint import find_joint
                            if find_joint(pa, pb) is None and find_joint(pa, pb, tol=3.0) is None:
                                broken = True
                                txt = "⚠ " + txt + " [не касаются]"
                        except Exception as exc:
                            broken = True
                            txt = "⚠ " + txt + " [ошибка проверки]"
                            _ = exc
                    item = QListWidgetItem(txt)
                    item.setData(Qt.ItemDataRole.UserRole, (b, rec.uid))
                    if broken:
                        try:
                            from PyQt6.QtGui import QColor, QBrush
                            item.setForeground(QBrush(QColor(200, 40, 40)))
                        except Exception as exc:
                            # headless / без QtGui — текст уже с ⚠
                            _ = exc
                    self.list_widget.addItem(item)
                    if prev_uid and rec.uid == prev_uid and (prev_block is None or b is prev_block):
                        selected_row = total
                    total += 1

            if total > 0:
                self.setWindowTitle(f"Стыки ({total})")
                if selected_row >= 0:
                    self.list_widget.setCurrentRow(selected_row)
                elif self.list_widget.count() > 0:
                    self.list_widget.setCurrentRow(0)
            else:
                self.setWindowTitle("Стыки")
                self._set_controls_enabled(False)
        finally:
            self._updating_ui = False

        cur_b, cur_uid = self.current_joint_ref()
        self._sync_controls_from_record(cur_b, cur_uid)

    def current_joint_ref(self) -> tuple[object | None, str]:
        item = self.list_widget.currentItem()
        if item is None:
            return None, ""
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            return data[0], str(data[1] or "")
        return None, ""

    def _find_record(self, block, joint_uid: str) -> JointRecord | None:
        if block is None or not joint_uid:
            return None
        for jr in getattr(block, "joints", None) or []:
            if str(getattr(jr, "uid", "")) == joint_uid:
                return jr
        return None

    def _sync_controls_from_record(self, block, joint_uid: str) -> None:
        rec = self._find_record(block, joint_uid)
        if rec is None:
            self._set_controls_enabled(False)
            return

        self._updating_ui = True
        try:
            self._set_controls_enabled(True)
            idx = self.preset_combo.findData(rec.preset_id)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
            pitch = rec.params.get("pitch")
            self.pitch_spin.setValue(float(pitch) if pitch is not None and float(pitch) > 0 else 0.0)
            self.margin_spin.setValue(float(rec.params.get("margin", 50.0) or 50.0))
            self.count_spin.setValue(max(1, int(rec.params.get("count", 3) or 3)))
        finally:
            self._updating_ui = False

    def _on_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self._updating_ui:
            return
        if current is None:
            self._set_controls_enabled(False)
            return
        block, juid = self.current_joint_ref()
        self._sync_controls_from_record(block, juid)
        if block is not None and juid:
            self.joint_selected.emit(block, juid)

    def select_joint_by_uid(self, joint_uid: str) -> bool:
        """Выбирает стык в списке по его `uid`."""
        target = str(joint_uid or "").strip()
        if not target:
            return False
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item is None:
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) == 2 and str(data[1]) == target:
                self.list_widget.setCurrentRow(row)
                return True
        return False

    def _on_preset_combo_changed(self, index: int) -> None:
        if self._updating_ui or index < 0:
            return
        preset_id = str(self.preset_combo.itemData(index) or "")
        if preset_id:
            self.change_selected_preset(preset_id)

    def _on_params_edited(self) -> None:
        if self._updating_ui:
            return
        pitch_val = float(self.pitch_spin.value())
        pitch_opt = pitch_val if pitch_val > 0.0 else None
        margin_val = float(self.margin_spin.value())
        count_val = int(self.count_spin.value())
        self.change_selected_params(pitch=pitch_opt, margin=margin_val, count=count_val)

    def change_selected_preset(self, preset_id: str) -> bool:
        """Меняет пресет выбранного стыка и испускает `joint_modified`."""
        block, juid = self.current_joint_ref()
        rec = self._find_record(block, juid)
        if rec is None:
            return False
        old_state = rec.to_dict()
        updated = JointRecord.from_dict(old_state)
        if not updated.apply_preset(preset_id):
            return False
        new_state = updated.to_dict()
        if old_state == new_state:
            return False
        self.joint_modified.emit(block, juid, old_state, new_state)
        self.load_joints(self.blocks_ref)
        return True

    def change_selected_params(
        self,
        *,
        pitch: float | None = -1.0,
        margin: float | None = None,
        count: int | None = None,
    ) -> bool:
        """Меняет параметры (шаг, отступ, количество точек) выбранного стыка и испускает `joint_modified`."""
        block, juid = self.current_joint_ref()
        rec = self._find_record(block, juid)
        if rec is None:
            return False
        old_state = rec.to_dict()
        updated = JointRecord.from_dict(old_state)
        if pitch != -1.0:
            updated.params["pitch"] = float(pitch) if (pitch is not None and float(pitch) > 0) else None
        if margin is not None:
            updated.params["margin"] = max(1.0, float(margin))
        if count is not None:
            updated.params["count"] = max(1, int(count))
        new_state = updated.to_dict()
        if old_state == new_state:
            return False
        self.joint_modified.emit(block, juid, old_state, new_state)
        self.load_joints(self.blocks_ref)
        return True

    def delete_selected_joint(self) -> bool:
        """Удаляет выбранный стык и испускает `joint_deleted`."""
        block, juid = self.current_joint_ref()
        if block is None or not juid:
            return False
        self.joint_deleted.emit(block, juid)
        self.load_joints(self.blocks_ref)
        return True
