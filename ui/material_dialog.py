"""Диалог создания / редактирования материала каталога."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Tuple

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QComboBox,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QHBoxLayout,
    QPushButton,
    QColorDialog,
    QMessageBox,
    QWidget,
)
from PyQt6.QtGui import QColor


# Тип материала → категория в БД
_TYPE_TO_CATEGORY = {
    "ldsp": "cat_ldsp",
    "mdf": "cat_mdf",
    "hdf": "cat_hdf",
    "plywood": "cat_plywood",
    "solid": "cat_other",
    "other": "cat_other",
}

_TYPE_LABELS = [
    ("ldsp", "ЛДСП"),
    ("mdf", "МДФ"),
    ("hdf", "ХДФ"),
    ("plywood", "Фанера"),
    ("solid", "Массив"),
    ("other", "Прочее"),
]

_GRAIN_LABELS = [
    ("none", "Нет"),
    ("length", "По длине"),
    ("width", "По ширине"),
]


def _slug(text: str) -> str:
    """Простой slug для id: латиница/цифры/подчёркивания."""
    t = text.strip().lower()
    # Транслит частых кириллических букв (упрощённо)
    table = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    })
    t = t.translate(table)
    t = re.sub(r"[^a-z0-9]+", "_", t)
    t = t.strip("_")
    return t[:40] if t else "mat"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MaterialEditDialog(QDialog):
    """Форма создания нового материала (или правки существующего)."""

    def __init__(self, parent=None, material=None):
        super().__init__(parent)
        self._edit = material  # Material | None
        self.setWindowTitle("Новый материал" if material is None else f"Материал — {material.name}")
        self.setMinimumWidth(420)

        self._color_rgb: Tuple[float, float, float] = (
            material.color_rgb if material else (0.88, 0.85, 0.80)
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Название
        self.name_edit = QLineEdit(material.name if material else "")
        self.name_edit.setPlaceholderText("Например: Дуб натуральный")
        form.addRow("Название *:", self.name_edit)

        # Артикул
        self.sku_edit = QLineEdit(material.sku if material else "")
        self.sku_edit.setPlaceholderText("Например: CUSTOM-OAK-16")
        form.addRow("Артикул:", self.sku_edit)

        # Тип
        self.type_combo = QComboBox()
        for code, label in _TYPE_LABELS:
            self.type_combo.addItem(label, code)
        if material:
            idx = self.type_combo.findData(material.material_type)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        form.addRow("Тип *:", self.type_combo)

        # Толщина
        self.thick_spin = QDoubleSpinBox()
        self.thick_spin.setRange(1.0, 100.0)
        self.thick_spin.setDecimals(1)
        self.thick_spin.setSuffix(" мм")
        self.thick_spin.setValue(material.thickness_mm if material else 16.0)
        form.addRow("Толщина *:", self.thick_spin)

        # Цвет — название + кнопка выбора
        self.color_name_edit = QLineEdit(material.color_name if material else "")
        self.color_name_edit.setPlaceholderText("Название цвета")
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_name_edit, stretch=1)
        self.color_btn = QPushButton("  ")
        self.color_btn.setFixedWidth(40)
        self.color_btn.setToolTip("Выбрать цвет для 3D")
        self.color_btn.clicked.connect(self._pick_color)
        self._apply_color_btn()
        color_row.addWidget(self.color_btn)
        color_w = QWidget()
        color_w.setLayout(color_row)
        form.addRow("Цвет:", color_w)

        # Направление текстуры
        self.grain_combo = QComboBox()
        for code, label in _GRAIN_LABELS:
            self.grain_combo.addItem(label, code)
        if material:
            idx = self.grain_combo.findData(material.grain_direction)
            if idx >= 0:
                self.grain_combo.setCurrentIndex(idx)
        form.addRow("Текстура:", self.grain_combo)

        # Плотность
        self.density_spin = QDoubleSpinBox()
        self.density_spin.setRange(0, 2000)
        self.density_spin.setDecimals(0)
        self.density_spin.setSuffix(" кг/м³")
        self.density_spin.setValue(material.density if material else 680)
        form.addRow("Плотность:", self.density_spin)

        # Цена
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1_000_000)
        self.price_spin.setDecimals(0)
        self.price_spin.setSuffix(" ₽/м²")
        self.price_spin.setValue(material.price_per_m2 if material else 0)
        form.addRow("Цена:", self.price_spin)

        # Сверление
        self.drill_face_spin = QDoubleSpinBox()
        self.drill_face_spin.setRange(0, 50)
        self.drill_face_spin.setDecimals(1)
        self.drill_face_spin.setSuffix(" мм")
        self.drill_face_spin.setValue(
            material.max_drill_depth_face if material else 14.0
        )
        form.addRow("Макс. сверление пласть:", self.drill_face_spin)

        self.drill_edge_spin = QDoubleSpinBox()
        self.drill_edge_spin.setRange(0, 50)
        self.drill_edge_spin.setDecimals(1)
        self.drill_edge_spin.setSuffix(" мм")
        self.drill_edge_spin.setValue(
            material.max_drill_depth_edge if material else 12.0
        )
        form.addRow("Макс. сверление торец:", self.drill_edge_spin)

        # Заметки
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)
        self.notes_edit.setPlaceholderText("Необязательные заметки…")
        if material and material.notes:
            self.notes_edit.setPlainText(material.notes)
        form.addRow("Заметки:", self.notes_edit)

        layout.addLayout(form)

        hint = QLabel("* — обязательные поля. Материал сохранится в локальный каталог.")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._result_material = None

    # ── UI helpers ────────────────────────────────────────────

    def _apply_color_btn(self) -> None:
        r, g, b = self._color_rgb
        qc = QColor(int(r * 255), int(g * 255), int(b * 255))
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background-color: {qc.name()}; border: 1px solid #888; }}"
        )

    def _pick_color(self) -> None:
        r, g, b = self._color_rgb
        initial = QColor(int(r * 255), int(g * 255), int(b * 255))
        color = QColorDialog.getColor(initial, self, "Цвет материала")
        if color.isValid():
            self._color_rgb = (color.redF(), color.greenF(), color.blueF())
            self._apply_color_btn()

    # ── Save ──────────────────────────────────────────────────

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Материал", "Укажите название материала.")
            self.name_edit.setFocus()
            return

        thickness = self.thick_spin.value()
        if thickness < 1:
            QMessageBox.warning(self, "Материал", "Толщина должна быть не меньше 1 мм.")
            return

        material_type = self.type_combo.currentData()
        category_id = _TYPE_TO_CATEGORY.get(material_type, "cat_other")
        sku = self.sku_edit.text().strip()
        if not sku:
            sku = f"{_slug(name).upper()}-{int(thickness)}"

        ts = _utc_now()

        if self._edit is not None:
            mid = self._edit.id
            is_builtin = self._edit.is_builtin
            created_at = self._edit.created_at or ts
        else:
            base = f"mat_{_slug(name)}_{int(thickness)}"
            mid = base
            # Гарантируем уникальность id
            try:
                from core.catalog import CatalogService
                cat = CatalogService.instance()
                if cat.get_material(mid) is not None:
                    mid = f"{base}_{uuid.uuid4().hex[:6]}"
            except Exception:
                mid = f"{base}_{uuid.uuid4().hex[:6]}"
            is_builtin = False
            created_at = ts

        from core.catalog.models import Material

        self._result_material = Material(
            id=mid,
            sku=sku,
            name=name,
            category_id=category_id,
            material_type=material_type,
            thickness_mm=thickness,
            density=self.density_spin.value(),
            color_name=self.color_name_edit.text().strip() or name,
            color_rgb=self._color_rgb,
            grain_direction=self.grain_combo.currentData() or "none",
            price_per_m2=self.price_spin.value(),
            currency="RUB",
            max_drill_depth_face=self.drill_face_spin.value(),
            max_drill_depth_edge=self.drill_edge_spin.value(),
            is_builtin=is_builtin,
            is_active=True,
            notes=self.notes_edit.toPlainText().strip(),
            created_at=created_at,
            updated_at=ts,
        )
        self.accept()

    def get_material(self):
        """Material после успешного Save, иначе None."""
        return self._result_material
