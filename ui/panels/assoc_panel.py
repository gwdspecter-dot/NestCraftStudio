# -*- coding: utf-8 -*-
"""Док-панель ассоциативных ссылок (AssocRef / face_hole)."""

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
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # Headless
    class _HeadlessSignalInstance:
        def __init__(self) -> None:
            self._slots: list[Callable[..., Any]] = []

        def connect(self, slot: Callable[..., Any]) -> None:
            if slot not in self._slots:
                self._slots.append(slot)

        def emit(self, *args: Any) -> None:
            for slot in list(self._slots):
                slot(*args)

    class _HeadlessSignalDescriptor:
        def __set_name__(self, owner: Any, name: str) -> None:
            self._attr_name = f"__as_sig_{name}"

        def __get__(self, instance: Any, owner: Any = None) -> Any:
            if instance is None:
                return self
            sig = getattr(instance, self._attr_name, None)
            if sig is None:
                sig = _HeadlessSignalInstance()
                setattr(instance, self._attr_name, sig)
            return sig

    def pyqtSignal(*_types: Any) -> Any:  # type: ignore[misc]
        return _HeadlessSignalDescriptor()

    class Qt:  # type: ignore[no-redef]
        class DockWidgetArea:
            LeftDockWidgetArea = 1
            RightDockWidgetArea = 2

        class ItemDataRole:
            UserRole = 256

    class QWidget:  # type: ignore[no-redef]
        def __init__(self, parent: Any = None) -> None:
            pass

        def setEnabled(self, _e: bool) -> None:
            pass

        def setToolTip(self, _t: str) -> None:
            pass

    class QDockWidget(QWidget):  # type: ignore[no-redef]
        def __init__(self, title: str = "", parent: Any = None) -> None:
            super().__init__(parent)
            self._title = title

        def setAllowedAreas(self, *_a: Any) -> None:
            pass

        def setWidget(self, _w: Any) -> None:
            pass

        def setWindowTitle(self, title: str) -> None:
            self._title = title

    class QVBoxLayout:  # type: ignore[no-redef]
        def __init__(self, *_a: Any) -> None:
            pass

        def setContentsMargins(self, *_a: Any) -> None:
            pass

        def setSpacing(self, *_a: Any) -> None:
            pass

        def addLayout(self, *_a: Any) -> None:
            pass

        def addWidget(self, *_a: Any, **_k: Any) -> None:
            pass

    class QHBoxLayout(QVBoxLayout):  # type: ignore[no-redef]
        pass

    class QFormLayout(QVBoxLayout):  # type: ignore[no-redef]
        def addRow(self, *_a: Any) -> None:
            pass

    class QLabel(QWidget):  # type: ignore[no-redef]
        def __init__(self, text: str = "", parent: Any = None) -> None:
            super().__init__(parent)

        def setWordWrap(self, _v: bool) -> None:
            pass

        def setStyleSheet(self, _s: str) -> None:
            pass

    class QPushButton(QWidget):  # type: ignore[no-redef]
        clicked = pyqtSignal()

        def __init__(self, text: str = "", parent: Any = None) -> None:
            super().__init__(parent)

    class QListWidgetItem:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self._text = text
            self._data: dict[int, Any] = {}

        def setData(self, role: int, value: Any) -> None:
            self._data[int(role)] = value

        def data(self, role: int) -> Any:
            return self._data.get(int(role))

        def setForeground(self, _b: Any) -> None:
            pass

    class QListWidget(QWidget):  # type: ignore[no-redef]
        currentItemChanged = pyqtSignal(object, object)
        itemDoubleClicked = pyqtSignal(object)

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._items: list[QListWidgetItem] = []
            self._row = -1

        def clear(self) -> None:
            self._items.clear()
            self._row = -1

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
            return self.item(self._row)

        def setCurrentRow(self, row: int) -> None:
            prev = self.currentItem()
            self._row = int(row) if 0 <= int(row) < len(self._items) else -1
            self.currentItemChanged.emit(self.currentItem(), prev)

    class QComboBox(QWidget):  # type: ignore[no-redef]
        currentIndexChanged = pyqtSignal(int)

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._entries: list[tuple[str, Any]] = []
            self._index = -1

        def addItem(self, text: str, userData: Any = None) -> None:
            self._entries.append((str(text), userData))
            if self._index < 0:
                self._index = 0

        def findData(self, data: Any) -> int:
            for i, (_t, ud) in enumerate(self._entries):
                if ud == data:
                    return i
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

        def currentData(self) -> Any:
            return self.itemData(self._index)

        def blockSignals(self, _b: bool) -> None:
            pass

    class QDoubleSpinBox(QWidget):  # type: ignore[no-redef]
        editingFinished = pyqtSignal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._val = 0.0

        def setRange(self, *_a: Any) -> None:
            pass

        def setDecimals(self, *_a: Any) -> None:
            pass

        def setSingleStep(self, *_a: Any) -> None:
            pass

        def setSuffix(self, *_a: Any) -> None:
            pass

        def setValue(self, val: float) -> None:
            self._val = float(val)

        def value(self) -> float:
            return self._val


from core.assoc import FACE_NAMES, AssocRef


class AssocDock(QDockWidget):
    """Список ассоциативных ссылок блока: добавление, правка параметров, удаление."""

    assoc_selected = pyqtSignal(object, str)  # (block, assoc_uid)
    assoc_modified = pyqtSignal(object, str, dict, dict)  # (block, uid, old, new)
    assoc_deleted = pyqtSignal(object, str)
    add_assoc_requested = pyqtSignal()
    edit_assoc_requested = pyqtSignal(object, str)  # полный диалог

    def __init__(self, parent=None):
        super().__init__("Ассоциации", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.blocks_ref: list = []
        self._updating_ui = False

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.btn_add = QPushButton("➕ Добавить")
        self.btn_add.setToolTip("Создать ассоциативное отверстие (Ctrl+Shift+H)")
        self.btn_add.clicked.connect(self.add_assoc_requested.emit)
        top.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✎ Правка…")
        self.btn_edit.setToolTip("Открыть полный диалог выбранной ссылки")
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self._emit_edit_requested)
        top.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("🗑 Удалить")
        self.btn_delete.setToolTip("Удалить выбранную ассоциацию и её отверстия")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_selected_assoc)
        top.addWidget(self.btn_delete)
        layout.addLayout(top)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        if hasattr(self.list_widget, "itemDoubleClicked"):
            self.list_widget.itemDoubleClicked.connect(lambda _it: self._emit_edit_requested())
        layout.addWidget(self.list_widget, 1)

        form_w = QWidget()
        form = QFormLayout(form_w)
        form.setContentsMargins(0, 2, 0, 0)
        form.setSpacing(4)

        self.face_combo = QComboBox()
        for face in FACE_NAMES:
            self.face_combo.addItem(face, face)
        self.face_combo.currentIndexChanged.connect(self._on_params_edited)
        form.addRow(QLabel("Грань source:"), self.face_combo)

        self.u_spin = QDoubleSpinBox()
        self.u_spin.setRange(-5000.0, 5000.0)
        self.u_spin.setDecimals(2)
        self.u_spin.setSingleStep(1.0)
        self.u_spin.setSuffix(" мм")
        self.u_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("u:"), self.u_spin)

        self.v_spin = QDoubleSpinBox()
        self.v_spin.setRange(-5000.0, 5000.0)
        self.v_spin.setDecimals(2)
        self.v_spin.setSingleStep(1.0)
        self.v_spin.setSuffix(" мм")
        self.v_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("v:"), self.v_spin)

        self.inset_spin = QDoubleSpinBox()
        self.inset_spin.setRange(-500.0, 500.0)
        self.inset_spin.setDecimals(2)
        self.inset_spin.setSingleStep(1.0)
        self.inset_spin.setSuffix(" мм")
        self.inset_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Inset:"), self.inset_spin)

        self.dia_spin = QDoubleSpinBox()
        self.dia_spin.setRange(1.0, 50.0)
        self.dia_spin.setDecimals(2)
        self.dia_spin.setSingleStep(0.5)
        self.dia_spin.setSuffix(" мм")
        self.dia_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Ø:"), self.dia_spin)

        self.depth_spin = QDoubleSpinBox()
        self.depth_spin.setRange(1.0, 200.0)
        self.depth_spin.setDecimals(2)
        self.depth_spin.setSingleStep(1.0)
        self.depth_spin.setSuffix(" мм")
        self.depth_spin.editingFinished.connect(self._on_params_edited)
        form.addRow(QLabel("Глубина:"), self.depth_spin)

        layout.addWidget(form_w)

        hint = QLabel(
            "Отверстие на target считается от грани source.\n"
            "Двойной клик — полный диалог. Параметры ниже правятся сразу."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self._set_controls_enabled(False)
        self.setWidget(container)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self.face_combo,
            self.u_spin,
            self.v_spin,
            self.inset_spin,
            self.dia_spin,
            self.depth_spin,
            self.btn_delete,
            self.btn_edit,
        ):
            w.setEnabled(enabled)

    @staticmethod
    def _format_item(block, ref: AssocRef) -> str:
        by_uid = {
            str(getattr(p, "uid", "")): getattr(p, "name", "Панель")
            for p in getattr(block, "panels", []) or []
        }
        tgt = by_uid.get(ref.target_uid, (ref.target_uid or "?")[:8])
        src = by_uid.get(ref.source_uid, (ref.source_uid or "?")[:8])
        dia = float(ref.params.get("diameter") or 0.0)
        face = ref.source_face or "?"
        return f"🔗 {tgt} ← {src}.{face}  Ø{dia:g}"

    def load_assocs(self, blocks: list) -> None:
        """Обновляет список ассоциаций по всем блокам сцены."""
        prev_block, prev_uid = self.current_assoc_ref()
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
                for raw in getattr(b, "assoc_refs", None) or []:
                    ref = raw if isinstance(raw, AssocRef) else AssocRef.from_dict(raw)
                    txt = self._format_item(b, ref)
                    broken = False
                    if by_uid.get(ref.target_uid) is None or by_uid.get(ref.source_uid) is None:
                        broken = True
                        txt = "⚠ " + txt + " [нет детали]"
                    item = QListWidgetItem(txt)
                    item.setData(Qt.ItemDataRole.UserRole, (b, ref.uid))
                    if broken:
                        try:
                            from PyQt6.QtGui import QBrush, QColor

                            item.setForeground(QBrush(QColor(200, 40, 40)))
                        except Exception as exc:
                            # headless / без QtGui — текст уже с ⚠
                            _ = exc
                    self.list_widget.addItem(item)
                    if prev_uid and ref.uid == prev_uid and (prev_block is None or b is prev_block):
                        selected_row = total
                    total += 1

            if total > 0:
                self.setWindowTitle(f"Ассоциации ({total})")
                if selected_row >= 0:
                    self.list_widget.setCurrentRow(selected_row)
                elif self.list_widget.count() > 0:
                    self.list_widget.setCurrentRow(0)
            else:
                self.setWindowTitle("Ассоциации")
                self._set_controls_enabled(False)
        finally:
            self._updating_ui = False

        cur_b, cur_uid = self.current_assoc_ref()
        self._sync_controls_from_record(cur_b, cur_uid)

    # alias for callers that used refresh(block)
    def refresh(self, _block=None) -> None:
        self.load_assocs(self.blocks_ref)

    def current_assoc_ref(self) -> tuple[object | None, str]:
        item = self.list_widget.currentItem()
        if item is None:
            return None, ""
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            return data[0], str(data[1] or "")
        return None, ""

    def _find_record(self, block, assoc_uid: str) -> AssocRef | None:
        if block is None or not assoc_uid:
            return None
        for raw in getattr(block, "assoc_refs", None) or []:
            ref = raw if isinstance(raw, AssocRef) else AssocRef.from_dict(raw)
            if str(getattr(ref, "uid", "")) == assoc_uid:
                return ref
        return None

    def _sync_controls_from_record(self, block, assoc_uid: str) -> None:
        ref = self._find_record(block, assoc_uid)
        if ref is None:
            self._set_controls_enabled(False)
            return
        self._updating_ui = True
        try:
            self._set_controls_enabled(True)
            idx = self.face_combo.findData(ref.source_face)
            if idx >= 0:
                self.face_combo.setCurrentIndex(idx)
            self.u_spin.setValue(float(ref.params.get("u") or 0.0))
            self.v_spin.setValue(float(ref.params.get("v") or 0.0))
            self.inset_spin.setValue(float(ref.params.get("inset") or 0.0))
            self.dia_spin.setValue(float(ref.params.get("diameter") or 5.0))
            self.depth_spin.setValue(float(ref.params.get("depth") or 12.0))
        finally:
            self._updating_ui = False

    def _on_current_item_changed(self, current, _previous) -> None:
        if self._updating_ui:
            return
        if current is None:
            self._set_controls_enabled(False)
            return
        block, uid = self.current_assoc_ref()
        self._sync_controls_from_record(block, uid)
        if block is not None and uid:
            self.assoc_selected.emit(block, uid)

    def _on_params_edited(self, *_args) -> None:
        if self._updating_ui:
            return
        block, uid = self.current_assoc_ref()
        ref = self._find_record(block, uid)
        if ref is None:
            return
        old_state = ref.to_dict()
        new_state = ref.to_dict()
        new_state["source_face"] = str(self.face_combo.currentData() or ref.source_face)
        new_state["params"] = dict(new_state.get("params") or {})
        new_state["params"]["u"] = float(self.u_spin.value())
        new_state["params"]["v"] = float(self.v_spin.value())
        new_state["params"]["inset"] = float(self.inset_spin.value())
        new_state["params"]["diameter"] = float(self.dia_spin.value())
        new_state["params"]["depth"] = float(self.depth_spin.value())
        if old_state == new_state:
            return
        self.assoc_modified.emit(block, uid, old_state, new_state)
        self.load_assocs(self.blocks_ref)

    def _emit_edit_requested(self) -> None:
        block, uid = self.current_assoc_ref()
        if block is not None and uid:
            self.edit_assoc_requested.emit(block, uid)

    def delete_selected_assoc(self) -> bool:
        block, uid = self.current_assoc_ref()
        if block is None or not uid:
            return False
        self.assoc_deleted.emit(block, uid)
        self.load_assocs(self.blocks_ref)
        return True

    def select_assoc_by_uid(self, assoc_uid: str) -> bool:
        target = str(assoc_uid or "").strip()
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
