# -*- coding: utf-8 -*-
"""Диалог создания / правки ассоциативного отверстия (AssocRef / face_hole)."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from core.assoc import FACE_NAMES, AssocRef, face_point_world, panel_face_frame
from ui.dialogs import SmartDoubleSpinBox


class AssocRefDialog(QDialog):
    """Создание или правка ``face_hole``.

    ``existing_ref`` — если задан, диалог в режиме правки (uid сохраняется).
    ``preview_callback(world_xyz | None)`` — live-превью точки в viewport.
    """

    def __init__(
        self,
        block,
        target_panel=None,
        parent=None,
        *,
        existing_ref: AssocRef | None = None,
        preview_callback: Callable[[tuple[float, float, float] | None], None] | None = None,
    ):
        super().__init__(parent)
        self.block = block
        self._existing_ref = existing_ref
        self._preview_callback = preview_callback
        self.setWindowTitle(
            "Ассоциативное отверстие — правка" if existing_ref else "Ассоциативное отверстие"
        )
        self.setMinimumWidth(460)

        panels = list(getattr(block, "panels", []) or [])
        self._panels = [p for p in panels if str(getattr(p, "uid", "") or "")]

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.target_combo = QComboBox()
        self.source_combo = QComboBox()
        for p in self._panels:
            label = f"{getattr(p, 'name', 'Панель')}  [{str(p.uid)[:8]}]"
            self.target_combo.addItem(label, p)
            self.source_combo.addItem(label, p)

        form.addRow("Панель с отверстием (target):", self.target_combo)
        form.addRow("Опорная панель (source):", self.source_combo)

        self.face_combo = QComboBox()
        for face in FACE_NAMES:
            self.face_combo.addItem(face, face)
        idx_xp = self.face_combo.findData("X+")
        if idx_xp >= 0:
            self.face_combo.setCurrentIndex(idx_xp)
        form.addRow("Грань source:", self.face_combo)

        ctx = target_panel
        self.u_spin = self._spin(0.0, -5000.0, 5000.0, ctx)
        self.v_spin = self._spin(0.0, -5000.0, 5000.0, ctx)
        form.addRow("Смещение u (в плоскости грани), мм:", self.u_spin)
        form.addRow("Смещение v (в плоскости грани), мм:", self.v_spin)

        self.inset_spin = self._spin(0.0, -500.0, 500.0, ctx)
        form.addRow("Inset вдоль нормали, мм:", self.inset_spin)

        self.dia_spin = self._spin(8.0, 1.0, 50.0, ctx)
        self.depth_spin = self._spin(12.0, 1.0, 200.0, ctx)
        form.addRow("Диаметр, мм:", self.dia_spin)
        form.addRow("Глубина, мм:", self.depth_spin)

        self.axis_combo = QComboBox()
        self.axis_combo.addItem("Авто (по нормали грани)", None)
        for ax in ("X", "Y", "Z"):
            self.axis_combo.addItem(ax, ax)
        form.addRow("Ось сверления:", self.axis_combo)

        layout.addLayout(form)

        hint = QLabel(
            "Отверстие ставится на target; позиция — центр грани source + u/v.\n"
            "При сдвиге source отверстие пересчитывается. Точка превью — в 3D-виде."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Defaults: existing or selection
        if existing_ref is not None:
            self._apply_existing(existing_ref)
        elif target_panel is not None:
            t_uid = str(getattr(target_panel, "uid", "") or "")
            for i in range(self.target_combo.count()):
                p = self.target_combo.itemData(i)
                if p is not None and str(getattr(p, "uid", "")) == t_uid:
                    self.target_combo.setCurrentIndex(i)
                    break
            for i in range(self.source_combo.count()):
                p = self.source_combo.itemData(i)
                if p is not None and str(getattr(p, "uid", "")) != t_uid:
                    self.source_combo.setCurrentIndex(i)
                    break

        self.target_combo.currentIndexChanged.connect(self._sync_source_if_same)
        self.source_combo.currentIndexChanged.connect(self._sync_target_if_same)
        for w in (
            self.target_combo,
            self.source_combo,
            self.face_combo,
            self.u_spin,
            self.v_spin,
            self.inset_spin,
            self.axis_combo,
        ):
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._emit_preview)
            if hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._emit_preview)
            if hasattr(w, "editingFinished"):
                w.editingFinished.connect(self._emit_preview)

        self._emit_preview()

    def _apply_existing(self, ref: AssocRef) -> None:
        t_uid = str(ref.target_uid or "")
        s_uid = str(ref.source_uid or "")
        for i in range(self.target_combo.count()):
            p = self.target_combo.itemData(i)
            if p is not None and str(getattr(p, "uid", "")) == t_uid:
                self.target_combo.setCurrentIndex(i)
                break
        for i in range(self.source_combo.count()):
            p = self.source_combo.itemData(i)
            if p is not None and str(getattr(p, "uid", "")) == s_uid:
                self.source_combo.setCurrentIndex(i)
                break
        fi = self.face_combo.findData(ref.source_face)
        if fi >= 0:
            self.face_combo.setCurrentIndex(fi)
        self.u_spin.setValue(float(ref.params.get("u") or 0.0))
        self.v_spin.setValue(float(ref.params.get("v") or 0.0))
        self.inset_spin.setValue(float(ref.params.get("inset") or 0.0))
        self.dia_spin.setValue(float(ref.params.get("diameter") or 8.0))
        self.depth_spin.setValue(float(ref.params.get("depth") or 12.0))
        axis = ref.params.get("axis")
        if axis in ("X", "Y", "Z"):
            ai = self.axis_combo.findData(axis)
            if ai >= 0:
                self.axis_combo.setCurrentIndex(ai)

    @staticmethod
    def _spin(val: float, min_val: float, max_val: float, ctx: Any) -> SmartDoubleSpinBox:
        sb = SmartDoubleSpinBox(context_obj=ctx)
        sb.setRange(min_val, max_val)
        sb.setDecimals(2)
        sb.setSingleStep(1.0)
        sb.setValue(float(val))
        return sb

    def _sync_source_if_same(self, _idx: int = 0) -> None:
        t = self.target_combo.currentData()
        s = self.source_combo.currentData()
        if t is None or s is None:
            return
        if str(getattr(t, "uid", "")) == str(getattr(s, "uid", "")):
            t_uid = str(getattr(t, "uid", ""))
            for i in range(self.source_combo.count()):
                p = self.source_combo.itemData(i)
                if p is not None and str(getattr(p, "uid", "")) != t_uid:
                    self.source_combo.blockSignals(True)
                    self.source_combo.setCurrentIndex(i)
                    self.source_combo.blockSignals(False)
                    break
        self._emit_preview()

    def _sync_target_if_same(self, _idx: int = 0) -> None:
        t = self.target_combo.currentData()
        s = self.source_combo.currentData()
        if t is None or s is None:
            return
        if str(getattr(t, "uid", "")) == str(getattr(s, "uid", "")):
            s_uid = str(getattr(s, "uid", ""))
            for i in range(self.target_combo.count()):
                p = self.target_combo.itemData(i)
                if p is not None and str(getattr(p, "uid", "")) != s_uid:
                    self.target_combo.blockSignals(True)
                    self.target_combo.setCurrentIndex(i)
                    self.target_combo.blockSignals(False)
                    break
        self._emit_preview()

    def _emit_preview(self, *_args) -> None:
        if self._preview_callback is None:
            return
        try:
            ref = self.build_ref()
            source = self.source_combo.currentData()
            if source is None:
                self._preview_callback(None)
                return
            u = float(ref.params.get("u") or 0.0)
            v = float(ref.params.get("v") or 0.0)
            inset = float(ref.params.get("inset") or 0.0)

            _origin, normal, _ua, _va = panel_face_frame(source, ref.source_face)
            pt = face_point_world(source, ref.source_face, u, v)
            if abs(inset) > 1e-9:
                pt = pt + (-float(inset)) * normal
            self._preview_callback((float(pt[0]), float(pt[1]), float(pt[2])))
        except Exception:
            self._preview_callback(None)

    def build_ref(self) -> AssocRef:
        target = self.target_combo.currentData()
        source = self.source_combo.currentData()
        if target is None or source is None:
            raise ValueError("Не выбраны панели target/source")
        t_uid = str(getattr(target, "uid", "") or "")
        s_uid = str(getattr(source, "uid", "") or "")
        if not t_uid or not s_uid or t_uid == s_uid:
            raise ValueError("Target и source должны быть разными панелями")

        params: dict[str, Any] = {
            "u": float(self.u_spin.value()),
            "v": float(self.v_spin.value()),
            "inset": float(self.inset_spin.value()),
            "diameter": float(self.dia_spin.value()),
            "depth": float(self.depth_spin.value()),
        }
        axis = self.axis_combo.currentData()
        if axis in ("X", "Y", "Z"):
            params["axis"] = axis

        face = str(self.face_combo.currentData() or "X+")
        uid = ""
        if self._existing_ref is not None:
            uid = str(getattr(self._existing_ref, "uid", "") or "")
        return AssocRef(
            uid=uid,
            kind="face_hole",
            target_uid=t_uid,
            source_uid=s_uid,
            source_face=face,
            params=params,
        )

    def reject(self) -> None:
        if self._preview_callback is not None:
            self._preview_callback(None)
        super().reject()

    def accept(self) -> None:
        if self._preview_callback is not None:
            self._preview_callback(None)
        super().accept()
