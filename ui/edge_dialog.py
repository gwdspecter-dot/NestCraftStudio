"""Диалог создания / редактирования кромки каталога."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

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
)
from PyQt6.QtGui import QColor

from core.catalog.models import EdgeBand


_EDGE_TYPES = [
    ("pvc", "ПВХ (поливинилхлорид)"),
    ("abs", "АБС (ударопрочный)"),
    ("melamine", "Меламин (бумажная)"),
    ("acrylic", "Акрил (3D глянец)"),
    ("other", "Прочее"),
]


def _slug(text: str) -> str:
    """Простой slug для id: латиница/цифры/подчёркивания."""
    t = text.strip().lower()
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
    return t[:40] if t else "edge"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EdgeBandEditDialog(QDialog):
    """Форма создания новой кромки (или правки существующей в БД)."""

    def __init__(self, parent=None, edge: Optional[EdgeBand] = None):
        super().__init__(parent)
        self._edit = edge  # EdgeBand | None
        self.setWindowTitle("Новая кромка" if edge is None else f"Кромка — {edge.name}")
        self.setMinimumWidth(400)

        self._color_rgb: Tuple[float, float, float] = (
            edge.color_rgb if edge else (0.92, 0.92, 0.92)
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Название
        self.name_edit = QLineEdit(edge.name if edge else "")
        self.name_edit.setPlaceholderText("Например: ПВХ Дуб Сонома")
        form.addRow("Название *:", self.name_edit)

        # Артикул (SKU)
        self.sku_edit = QLineEdit(edge.sku if edge else "")
        self.sku_edit.setPlaceholderText("Например: PVC-22-2-SONOMA")
        form.addRow("Артикул / SKU:", self.sku_edit)

        # Тип материала кромки
        self.type_combo = QComboBox()
        for code, label in _EDGE_TYPES:
            self.type_combo.addItem(label, code)
        if edge:
            for idx in range(self.type_combo.count()):
                if self.type_combo.itemData(idx) == edge.material_type:
                    self.type_combo.setCurrentIndex(idx)
                    break
        form.addRow("Тип кромки:", self.type_combo)

        # Толщина
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setRange(0.2, 5.0)
        self.thickness_spin.setSingleStep(0.2)
        self.thickness_spin.setDecimals(2)
        self.thickness_spin.setSuffix(" мм")
        self.thickness_spin.setValue(edge.thickness_mm if edge else 0.4)
        form.addRow("Толщина *:", self.thickness_spin)

        # Ширина
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(10.0, 100.0)
        self.width_spin.setSingleStep(1.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setSuffix(" мм")
        self.width_spin.setValue(edge.width_mm if edge else 22.0)
        form.addRow("Ширина *:", self.width_spin)

        # Цвет
        color_layout = QHBoxLayout()
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(48, 24)
        self.color_preview.setAutoFillBackground(True)
        self._update_color_preview()
        color_layout.addWidget(self.color_preview)

        self.color_btn = QPushButton("Выбрать цвет…")
        self.color_btn.clicked.connect(self._choose_color)
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        form.addRow("Цвет кромки:", color_layout)

        # Название декора цвета
        self.color_name_edit = QLineEdit(edge.color_name if edge else "")
        self.color_name_edit.setPlaceholderText("Например: Белый шагрень")
        form.addRow("Имя декора:", self.color_name_edit)

        # Цена за метр
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0, 10000.0)
        self.price_spin.setSingleStep(5.0)
        self.price_spin.setDecimals(1)
        self.price_spin.setSuffix(" руб/пог.м")
        self.price_spin.setValue(edge.price_per_m if edge else 25.0)
        form.addRow("Цена:", self.price_spin)

        # Заметки
        self.notes_edit = QTextEdit(edge.notes if edge else "")
        self.notes_edit.setMaximumHeight(60)
        form.addRow("Заметки:", self.notes_edit)

        layout.addLayout(form)

        # Кнопки диалога
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_color(self) -> None:
        r, g, b = self._color_rgb
        initial = QColor(int(r * 255), int(g * 255), int(b * 255))
        c = QColorDialog.getColor(initial, self, "Цвет кромки")
        if c.isValid():
            self._color_rgb = (c.redF(), c.greenF(), c.blueF())
            self._update_color_preview()

    def _update_color_preview(self) -> None:
        r, g, b = self._color_rgb
        hex_color = QColor(int(r * 255), int(g * 255), int(b * 255)).name()
        self.color_preview.setStyleSheet(
            f"border: 1px solid #777; border-radius: 3px; background-color: {hex_color};"
        )

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Кромка", "Укажите название кромки.")
            self.name_edit.setFocus()
            return
        self.accept()

    def get_edge_band(self) -> Optional[EdgeBand]:
        """Собирает EdgeBand из полей формы."""
        name = self.name_edit.text().strip()
        if not name:
            return None

        mtype = self.type_combo.currentData() or "pvc"
        thickness = float(self.thickness_spin.value())
        width = float(self.width_spin.value())
        sku = self.sku_edit.text().strip()
        if not sku:
            sku = f"{mtype.upper()}-{int(width)}-{thickness:g}-{_slug(name)[:10].upper()}"

        now = _utc_now()
        if self._edit:
            edge_id = self._edit.id
            created_at = self._edit.created_at or now
            is_builtin = self._edit.is_builtin
        else:
            edge_id = f"edge_{mtype}_{int(width)}_{str(thickness).replace('.', '')}_{_slug(name)}"
            created_at = now
            is_builtin = False

        return EdgeBand(
            id=edge_id,
            sku=sku,
            name=name,
            supplier_id=self._edit.supplier_id if self._edit else None,
            material_type=mtype,
            thickness_mm=thickness,
            width_mm=width,
            color_name=self.color_name_edit.text().strip() or name,
            color_rgb=self._color_rgb,
            texture_path=self._edit.texture_path if self._edit else "",
            price_per_m=float(self.price_spin.value()),
            currency="RUB",
            is_builtin=is_builtin,
            is_active=True,
            notes=self.notes_edit.toPlainText().strip(),
            created_at=created_at,
            updated_at=now,
        )
