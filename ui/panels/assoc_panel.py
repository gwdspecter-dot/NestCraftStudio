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
            self._text = str(text)

        def setText(self, text: str) -> None:
            self._text = str(text)

        def text(self) -> str:
            return self._text

        def setWordWrap(self, _v: bool) -> None:
            pass

        def setStyleSheet(self, _s: str) -> None:
            pass

    class QPushButton(QWidget):  # type: ignore[no-redef]
        clicked = pyqtSignal()

        def __init__(self, text: str = "", parent: Any = None) -> None:
            super().__init__(parent)
            self._text = str(text)

        def setText(self, text: str) -> None:
            self._text = str(text)

        def text(self) -> str:
            return self._text

    class QListWidgetItem:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self._text = text
            self._data: dict[int, Any] = {}
            self._tooltip = ""

        def text(self) -> str:
            return self._text

        def setToolTip(self, tip: str) -> None:
            self._tooltip = str(tip)

        def toolTip(self) -> str:
            return self._tooltip

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


from core.assoc import (
    ANCHOR_LABELS,
    ANCHOR_MODES,
    FACE_NAMES,
    AssocAttachmentStatus,
    AssocRef,
    capture_face_hint,
    evaluate_assoc_ref,
    freeze_assoc_ref_state,
    rebind_assoc_ref_state,
    unfreeze_assoc_ref_state,
)
from core.logging_setup import get_logger

_log = get_logger("assoc_panel")


def _theme_colors():
    """Возвращает палитру текущей темы (или безопасный fallback в headless-режиме)."""
    try:
        from ui.theme import current_theme

        t = current_theme()
        return t.error, t.warning, t.accent, t.success, t.text_dim
    except Exception as exc:
        _log.debug("ui.theme недоступна в headless-режиме: %s", exc)
        return "#c82828", "#b56800", "#325fa5", "#2e7d32", "#666666"


class AssocPanelWidget(QWidget):
    """Встраиваемый виджет «Ассоциации»: список ссылок, статус, правка, фиксация и удаление."""

    assoc_selected = pyqtSignal(object, str)  # (block, assoc_uid)
    assoc_modified = pyqtSignal(object, str, dict, dict)  # (block, uid, old, new)
    assoc_deleted = pyqtSignal(object, str)
    add_assoc_requested = pyqtSignal()
    edit_assoc_requested = pyqtSignal(object, str)  # полный диалог
    title_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocks_ref: list = []
        self._updating_ui = False
        self._title: str = "Ассоциации"
        self._last_status: AssocAttachmentStatus | None = None

        layout = QVBoxLayout(self)
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

        recovery_row = QHBoxLayout()
        self.btn_toggle_fixed = QPushButton("📌 Зафиксировать")
        self.btn_toggle_fixed.setToolTip(
            "Заморозить текущие координаты отверстия на target (отвязать от грани source) или вернуть привязку"
        )
        self.btn_toggle_fixed.setEnabled(False)
        self.btn_toggle_fixed.clicked.connect(self.toggle_fixed_selected_assoc)
        recovery_row.addWidget(self.btn_toggle_fixed)

        self.btn_rebind_face = QPushButton("🧭 Подобрать грань")
        self.btn_rebind_face.setToolTip(
            "Подобрать актуальную грань source (после поворота или перемещения) и обновить привязку"
        )
        self.btn_rebind_face.setEnabled(False)
        self.btn_rebind_face.clicked.connect(self.rebind_selected_assoc)
        recovery_row.addWidget(self.btn_rebind_face)
        layout.addLayout(recovery_row)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        if hasattr(self.list_widget, "itemDoubleClicked"):
            self.list_widget.itemDoubleClicked.connect(lambda _it: self._emit_edit_requested())
        layout.addWidget(self.list_widget, 1)

        _, _, _, _, dim_col = _theme_colors()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {dim_col}; font-size: 11px;")
        layout.addWidget(self.status_label)

        form_w = QWidget()
        form = QFormLayout(form_w)
        form.setContentsMargins(0, 2, 0, 0)
        form.setSpacing(4)

        self.face_combo = QComboBox()
        for face in FACE_NAMES:
            self.face_combo.addItem(face, face)
        self.face_combo.currentIndexChanged.connect(self._on_params_edited)
        form.addRow(QLabel("Грань source:"), self.face_combo)

        self.anchor_combo = QComboBox()
        for mode in ANCHOR_MODES:
            self.anchor_combo.addItem(ANCHOR_LABELS.get(mode, mode), mode)
        self.anchor_combo.currentIndexChanged.connect(self._on_params_edited)
        form.addRow(QLabel("Якорь грани:"), self.anchor_combo)

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

        self._hint_label = QLabel(
            "Отверстие на target считается от грани source с учётом якоря.\n"
            "📌 Зафиксировать — заморозить позицию на target; 🧭 Подобрать грань — восстановить после поворота."
        )
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet(f"color: {dim_col}; font-size: 11px;")
        layout.addWidget(self._hint_label)

        self._set_controls_enabled(False)

    def panel_title(self) -> str:
        return self._title

    def _set_panel_title(self, title: str) -> None:
        self._title = str(title)
        self.title_changed.emit(self._title)

    def refresh_theme(self) -> None:
        _, _, _, _, dim_col = _theme_colors()
        self._hint_label.setStyleSheet(f"color: {dim_col}; font-size: 11px;")
        if self._last_status is not None:
            self._update_status_banner(self._last_status)
        else:
            self.status_label.setStyleSheet(f"color: {dim_col}; font-size: 11px;")

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self.face_combo,
            self.anchor_combo,
            self.u_spin,
            self.v_spin,
            self.inset_spin,
            self.dia_spin,
            self.depth_spin,
            self.btn_delete,
            self.btn_edit,
            self.btn_toggle_fixed,
            self.btn_rebind_face,
        ):
            w.setEnabled(enabled)
        if not enabled:
            self.btn_toggle_fixed.setText("📌 Зафиксировать")
            self._last_status = None
            self.status_label.setText("")

    @staticmethod
    def _status_badge(status: AssocAttachmentStatus | None, ref: AssocRef) -> tuple[str, str]:
        """Возвращает `(префикс, суффикс)` для строки списка."""
        if status is None:
            return ("📌", " [фикс.]") if ref.fixed else ("🔗", "")
        if status.severity == "error":
            if status.state == "broken_missing_panel":
                return ("❌", " [нет детали]")
            if status.state == "broken_same_panel":
                return ("❌", " [та же деталь]")
            return ("❌", " [ошибка]")
        if status.severity == "warning":
            tags = {
                "out_of_target": " [вне детали]",
                "out_of_source_face": " [вне грани]",
                "face_drifted": (
                    f" [сдвиг грани → {status.suggested_face}]"
                    if status.suggested_face and status.suggested_face != ref.source_face
                    else " [сдвиг грани]"
                ),
            }
            return ("⚠", tags.get(status.state, " [предупр.]"))
        if status.state == "fixed" or ref.fixed:
            return ("📌", " [фикс.]")
        return ("🔗", "")

    @staticmethod
    def _format_item(
        block,
        ref: AssocRef,
        status: AssocAttachmentStatus | None = None,
        all_panels_by_uid: dict[str, Any] | None = None,
    ) -> str:
        if all_panels_by_uid is not None:
            by_uid = {
                uid: getattr(p, "name", "Панель")
                for uid, p in all_panels_by_uid.items()
            }
        else:
            by_uid = {
                str(getattr(p, "uid", "")): getattr(p, "name", "Панель")
                for p in getattr(block, "panels", []) or []
            }
        tgt = by_uid.get(ref.target_uid, (ref.target_uid or "?")[:8])
        src = by_uid.get(ref.source_uid, (ref.source_uid or "?")[:8])
        dia = float(ref.params.get("diameter") or 0.0)
        face = ref.source_face or "?"
        prefix, suffix = AssocPanelWidget._status_badge(status, ref)
        if ref.fixed and (status is None or status.state == "fixed"):
            return f"{prefix} {tgt}  Ø{dia:g}{suffix}"
        return f"{prefix} {tgt} ← {src}.{face}  Ø{dia:g}{suffix}"

    @staticmethod
    def _apply_item_color(item: QListWidgetItem, status: AssocAttachmentStatus) -> None:
        err_col, warn_col, acc_col, _ok_col, _dim_col = _theme_colors()
        color_hex: str | None = None
        if status.severity == "error":
            color_hex = err_col
        elif status.severity == "warning":
            color_hex = warn_col
        elif status.state == "fixed":
            color_hex = acc_col
        if color_hex is None:
            return
        try:
            from PyQt6.QtGui import QBrush, QColor

            item.setForeground(QBrush(QColor(color_hex)))
        except Exception as exc:  # noqa: BLE001
            _log.debug("QtGui foreground color unavailable (headless): %s", exc)

    def load_assocs(self, blocks: list) -> None:
        """Обновляет список ассоциаций по всем блокам сцены."""
        prev_block, prev_uid = self.current_assoc_ref()
        self.blocks_ref = list(blocks or [])

        all_by_uid: dict[str, Any] = {}
        for b in self.blocks_ref:
            for p in getattr(b, "panels", []) or []:
                puid = str(getattr(p, "uid", "") or "")
                if puid:
                    all_by_uid[puid] = p

        self._updating_ui = True
        try:
            self.list_widget.clear()
            total = 0
            problems = 0
            selected_row = -1
            for b in self.blocks_ref:
                for raw in getattr(b, "assoc_refs", None) or []:
                    ref = raw if isinstance(raw, AssocRef) else AssocRef.from_dict(raw)
                    st = evaluate_assoc_ref(b, ref, all_blocks=self.blocks_ref)
                    if st.severity != "ok":
                        problems += 1
                    txt = self._format_item(b, ref, st, all_panels_by_uid=all_by_uid)
                    item = QListWidgetItem(txt)
                    item.setData(Qt.ItemDataRole.UserRole, (b, ref.uid))
                    tip = st.message + (f"\n{st.remedy}" if st.remedy else "")
                    if hasattr(item, "setToolTip"):
                        item.setToolTip(tip)
                    self._apply_item_color(item, st)
                    self.list_widget.addItem(item)
                    if prev_uid and ref.uid == prev_uid and (prev_block is None or b is prev_block):
                        selected_row = total
                    total += 1

            if total > 0:
                if problems > 0:
                    self._set_panel_title(f"Ассоциации ({total} · ⚠ {problems})")
                else:
                    self._set_panel_title(f"Ассоциации ({total})")
                if selected_row >= 0:
                    self.list_widget.setCurrentRow(selected_row)
                elif self.list_widget.count() > 0:
                    self.list_widget.setCurrentRow(0)
            else:
                self._set_panel_title("Ассоциации")
                self._set_controls_enabled(False)
        finally:
            self._updating_ui = False

        cur_b, cur_uid = self.current_assoc_ref()
        self._sync_controls_from_record(cur_b, cur_uid)

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

    def _find_panel(self, block, panel_uid: str):
        if not panel_uid:
            return None
        target_uid = str(panel_uid)
        if block is not None:
            for p in getattr(block, "panels", None) or []:
                if str(getattr(p, "uid", "")) == target_uid:
                    return p
        for b in self.blocks_ref:
            for p in getattr(b, "panels", None) or []:
                if str(getattr(p, "uid", "")) == target_uid:
                    return p
        return None

    def _update_status_banner(self, status: AssocAttachmentStatus) -> None:
        self._last_status = status
        err_col, warn_col, acc_col, ok_col, _dim_col = _theme_colors()
        text = status.message
        if status.remedy:
            text = f"{text}\n{status.remedy}"
        self.status_label.setText(text)
        if status.severity == "error":
            self.status_label.setStyleSheet(f"color: {err_col}; font-size: 11px; font-weight: bold;")
        elif status.severity == "warning":
            self.status_label.setStyleSheet(f"color: {warn_col}; font-size: 11px;")
        elif status.state == "fixed":
            self.status_label.setStyleSheet(f"color: {acc_col}; font-size: 11px;")
        else:
            self.status_label.setStyleSheet(f"color: {ok_col}; font-size: 11px;")

    def _sync_controls_from_record(self, block, assoc_uid: str) -> None:
        ref = self._find_record(block, assoc_uid)
        if ref is None:
            self._set_controls_enabled(False)
            return
        st = evaluate_assoc_ref(block, ref, all_blocks=self.blocks_ref)
        target = self._find_panel(block, ref.target_uid)
        source = self._find_panel(block, ref.source_uid)

        self._updating_ui = True
        try:
            self._set_controls_enabled(True)
            self._update_status_banner(st)

            idx = self.face_combo.findData(ref.source_face)
            if idx >= 0:
                self.face_combo.setCurrentIndex(idx)
            aidx = self.anchor_combo.findData(ref.anchor)
            if aidx >= 0:
                self.anchor_combo.setCurrentIndex(aidx)

            self.u_spin.setValue(float(ref.params.get("u") or 0.0))
            self.v_spin.setValue(float(ref.params.get("v") or 0.0))
            self.inset_spin.setValue(float(ref.params.get("inset") or 0.0))
            self.dia_spin.setValue(float(ref.params.get("diameter") or 5.0))
            self.depth_spin.setValue(float(ref.params.get("depth") or 12.0))

            # В режиме fixed позиция заморожена на target — отключаем поля грани/смещений
            is_fixed = bool(ref.fixed)
            for w in (self.face_combo, self.anchor_combo, self.u_spin, self.v_spin, self.inset_spin):
                w.setEnabled(not is_fixed)

            if is_fixed:
                self.btn_toggle_fixed.setText("🔗 Привязать")
                self.btn_toggle_fixed.setEnabled(target is not None and source is not None)
            else:
                self.btn_toggle_fixed.setText("📌 Зафиксировать")
                self.btn_toggle_fixed.setEnabled(target is not None)

            can_rebind = (
                target is not None
                and source is not None
                and str(getattr(target, "uid", "")) != str(getattr(source, "uid", ""))
            )
            self.btn_rebind_face.setEnabled(can_rebind)
            if st.suggested_face:
                self.btn_rebind_face.setToolTip(
                    f"Перепривязать к рекомендуемой грани {st.suggested_face} и обновить снимок грани"
                )
            else:
                self.btn_rebind_face.setToolTip(
                    "Подобрать ближайшую подходящую грань source и обновить привязку"
                )
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
        new_face = str(self.face_combo.currentData() or ref.source_face)
        new_anchor = str(self.anchor_combo.currentData() or ref.anchor or "center")
        new_state["source_face"] = new_face
        if new_anchor != "center":
            new_state["anchor"] = new_anchor
        else:
            new_state.pop("anchor", None)
        new_state["params"] = dict(new_state.get("params") or {})
        new_state["params"]["u"] = float(self.u_spin.value())
        new_state["params"]["v"] = float(self.v_spin.value())
        new_state["params"]["inset"] = float(self.inset_spin.value())
        new_state["params"]["diameter"] = float(self.dia_spin.value())
        new_state["params"]["depth"] = float(self.depth_spin.value())

        if not ref.fixed:
            source = self._find_panel(block, ref.source_uid)
            if source is not None:
                hint = capture_face_hint(source, new_face)
                if hint is not None:
                    new_state["face_hint"] = hint

        if old_state == new_state:
            return
        self.assoc_modified.emit(block, uid, old_state, new_state)
        self.load_assocs(self.blocks_ref)

    def toggle_fixed_selected_assoc(self) -> bool:
        """Переключает выбранную ссылку между живой привязкой и режимом ``fixed=True`` (Undo/Redo)."""
        block, uid = self.current_assoc_ref()
        ref = self._find_record(block, uid)
        if block is None or ref is None:
            return False
        old_state = ref.to_dict()
        if ref.fixed:
            new_state = unfreeze_assoc_ref_state(block, ref, all_blocks=self.blocks_ref)
        else:
            new_state = freeze_assoc_ref_state(block, ref, all_blocks=self.blocks_ref)
        if not new_state or new_state == old_state:
            return False
        self.assoc_modified.emit(block, uid, old_state, new_state)
        self.load_assocs(self.blocks_ref)
        return True

    def rebind_selected_assoc(self, new_face: str | None = None) -> bool:
        """Перепривязывает выбранную ссылку к актуальной грани ``source`` (Undo/Redo)."""
        block, uid = self.current_assoc_ref()
        ref = self._find_record(block, uid)
        if block is None or ref is None:
            return False
        old_state = ref.to_dict()
        new_state = rebind_assoc_ref_state(
            block, ref, new_face=new_face, all_blocks=self.blocks_ref
        )
        if not new_state or new_state == old_state:
            return False
        self.assoc_modified.emit(block, uid, old_state, new_state)
        self.load_assocs(self.blocks_ref)
        return True

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


class AssocDock(QDockWidget):
    """Совместимая обёртка QDockWidget вокруг `AssocPanelWidget`."""

    assoc_selected = pyqtSignal(object, str)  # (block, assoc_uid)
    assoc_modified = pyqtSignal(object, str, dict, dict)  # (block, uid, old, new)
    assoc_deleted = pyqtSignal(object, str)
    add_assoc_requested = pyqtSignal()
    edit_assoc_requested = pyqtSignal(object, str)  # полный диалог

    def __init__(self, parent=None):
        self._cached_title: str = "Ассоциации"
        super().__init__("Ассоциации", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.panel = AssocPanelWidget(self)
        self.setWidget(self.panel)

        self.btn_add = self.panel.btn_add
        self.btn_edit = self.panel.btn_edit
        self.btn_delete = self.panel.btn_delete
        self.btn_toggle_fixed = self.panel.btn_toggle_fixed
        self.btn_rebind_face = self.panel.btn_rebind_face
        self.list_widget = self.panel.list_widget
        self.status_label = self.panel.status_label
        self.face_combo = self.panel.face_combo
        self.anchor_combo = self.panel.anchor_combo
        self.u_spin = self.panel.u_spin
        self.v_spin = self.panel.v_spin
        self.inset_spin = self.panel.inset_spin
        self.dia_spin = self.panel.dia_spin
        self.depth_spin = self.panel.depth_spin

        self.panel.assoc_selected.connect(self.assoc_selected.emit)
        self.panel.assoc_modified.connect(self.assoc_modified.emit)
        self.panel.assoc_deleted.connect(self.assoc_deleted.emit)
        self.panel.add_assoc_requested.connect(self.add_assoc_requested.emit)
        self.panel.edit_assoc_requested.connect(self.edit_assoc_requested.emit)
        self.panel.title_changed.connect(self._on_panel_title_changed)

    def _on_panel_title_changed(self, title: str) -> None:
        self._cached_title = str(title)
        self.setWindowTitle(self._cached_title)

    @property
    def _title(self) -> str:
        panel = getattr(self, "panel", None)
        if panel is not None:
            return panel._title
        return getattr(self, "_cached_title", "Ассоциации")

    @_title.setter
    def _title(self, value: str) -> None:
        self._cached_title = str(value)
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel._title = self._cached_title

    def panel_title(self) -> str:
        return self._title

    @property
    def blocks_ref(self) -> list:
        return self.panel.blocks_ref

    @blocks_ref.setter
    def blocks_ref(self, value: list) -> None:
        self.panel.blocks_ref = value

    def load_assocs(self, blocks: list) -> None:
        self.panel.load_assocs(blocks)

    def refresh(self, _block=None) -> None:
        self.panel.refresh(_block)

    def current_assoc_ref(self) -> tuple[object | None, str]:
        return self.panel.current_assoc_ref()

    def toggle_fixed_selected_assoc(self) -> bool:
        return self.panel.toggle_fixed_selected_assoc()

    def rebind_selected_assoc(self, new_face: str | None = None) -> bool:
        return self.panel.rebind_selected_assoc(new_face=new_face)

    def delete_selected_assoc(self) -> bool:
        return self.panel.delete_selected_assoc()

    def select_assoc_by_uid(self, assoc_uid: str) -> bool:
        return self.panel.select_assoc_by_uid(assoc_uid)

