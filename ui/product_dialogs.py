"""Диалоги создания модели изделия и редактирования параметров изделия.

Оформление полностью подчиняется `ui/theme.py` (`current_theme()`), без
зашитых цветов. Поддерживает светлую и тёмную системную тему.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.bounding_frame import (
    BoundingFrame,
    DEFAULT_FRAME_DEPTH_MM,
    DEFAULT_FRAME_HEIGHT_MM,
    DEFAULT_FRAME_WIDTH_MM,
    MAX_FRAME_DIM_MM,
    validate_bounding_frame_dims,
)
from ui.dialogs import SmartDoubleSpinBox
from ui.theme import current_theme


def _make_dim_spin(value: float) -> SmartDoubleSpinBox:
    sb = SmartDoubleSpinBox()
    # Позволяем ввести 0, чтобы сработала понятная валидация при нажатии «ОК»
    sb.setRange(0.0, MAX_FRAME_DIM_MM * 2.0)
    sb.setDecimals(1)
    sb.setSingleStep(10.0)
    sb.setSuffix(" мм")
    sb.setValue(float(value))
    return sb


class CreateModelDialog(QDialog):
    """Окно создания новой модели изделия с выбором режима (стартовый экран)."""

    MODE_BOUNDING_FRAME = "bounding_frame"
    MODE_ROOM_LAYOUT = "room_layout"

    def __init__(
        self,
        parent=None,
        *,
        default_name: str = "Новое изделие",
        default_order_number: str = "",
        default_width: float = DEFAULT_FRAME_WIDTH_MM,
        default_height: float = DEFAULT_FRAME_HEIGHT_MM,
        default_depth: float = DEFAULT_FRAME_DEPTH_MM,
    ):
        super().__init__(parent)
        self.setWindowTitle("Создать модель")
        self.setMinimumWidth(440)
        self._validated_frame: BoundingFrame | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        self.mode_tabs = QTabWidget(self)
        self.mode_tabs.setObjectName("createModelModeTabs")

        # ── Вкладка 1: Габаритная рамка (по умолчанию) ────────
        self._frame_tab = QWidget(self.mode_tabs)
        frame_layout = QVBoxLayout(self._frame_tab)
        frame_layout.setContentsMargins(12, 12, 12, 12)
        frame_layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit(default_name, self._frame_tab)
        self.name_edit.setPlaceholderText("Например, Шкаф-купе 800")
        form.addRow("Наименование:", self.name_edit)

        self.order_edit = QLineEdit(default_order_number, self._frame_tab)
        self.order_edit.setPlaceholderText("Например, ЗАК-001 (для чертежей и обозначения)")
        form.addRow("Номер заказа:", self.order_edit)

        self._frame_section_label = QLabel("Габаритная рамка изделия", self._frame_tab)
        form.addRow(self._frame_section_label)

        self.width_spin = _make_dim_spin(default_width)
        self.height_spin = _make_dim_spin(default_height)
        self.depth_spin = _make_dim_spin(default_depth)

        form.addRow("Ширина (X), мм:", self.width_spin)
        form.addRow("Высота (Y), мм:", self.height_spin)
        form.addRow("Глубина (Z), мм:", self.depth_spin)

        frame_layout.addLayout(form)

        self._hint_label = QLabel(
            "Габаритная рамка задаёт стартовый объём проектирования в 3D-сцене "
            "и не ограничивает размещение деталей за её пределами.",
            self._frame_tab,
        )
        self._hint_label.setWordWrap(True)
        frame_layout.addWidget(self._hint_label)
        frame_layout.addStretch(1)

        # ── Вкладка 2: Планировка помещения (заглушка) ────────
        self._room_tab = QWidget(self.mode_tabs)
        room_layout = QVBoxLayout(self._room_tab)
        room_layout.setContentsMargins(16, 20, 16, 20)
        room_layout.setSpacing(8)

        self._room_stub_card = QFrame(self._room_tab)
        self._room_stub_card.setFrameShape(QFrame.Shape.StyledPanel)
        stub_inner = QVBoxLayout(self._room_stub_card)
        stub_inner.setContentsMargins(16, 16, 16, 16)
        stub_inner.setSpacing(6)

        self._room_title = QLabel("Планировка помещения", self._room_stub_card)
        self._room_desc = QLabel(
            "Режим проектирования планировки помещения находится в разработке.\n"
            "Для создания изделия переключитесь на вкладку «Габаритная рамка».",
            self._room_stub_card,
        )
        self._room_desc.setWordWrap(True)
        stub_inner.addWidget(self._room_title)
        stub_inner.addWidget(self._room_desc)

        room_layout.addWidget(self._room_stub_card)
        room_layout.addStretch(1)

        self.mode_tabs.addTab(self._frame_tab, "Габаритная рамка")
        self.mode_tabs.addTab(self._room_tab, "Планировка помещения")
        self.mode_tabs.setCurrentIndex(0)
        self.mode_tabs.currentChanged.connect(self._on_mode_changed)
        root.addWidget(self.mode_tabs)

        self._error_label = QLabel("", self)
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText("ОК")
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self.refresh_theme()
        self._on_mode_changed(0)
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def refresh_theme(self) -> None:
        t = current_theme()
        self._frame_section_label.setStyleSheet(
            f"color: {t.heading}; font-weight: 600; padding-top: 6px;"
        )
        self._hint_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._error_label.setStyleSheet(
            f"color: {t.error}; font-size: 12px; font-weight: 500;"
        )
        self._room_stub_card.setStyleSheet(
            f"QFrame {{ background: {t.bg_panel}; border: 1px solid {t.border}; border-radius: 6px; }}"
        )
        self._room_title.setStyleSheet(
            f"color: {t.text_title}; font-size: 14px; font-weight: 600; border: none; background: transparent;"
        )
        self._room_desc.setStyleSheet(
            f"color: {t.text_dim}; font-size: 12px; border: none; background: transparent;"
        )

    def current_mode(self) -> str:
        return (
            self.MODE_BOUNDING_FRAME
            if self.mode_tabs.currentIndex() == 0
            else self.MODE_ROOM_LAYOUT
        )

    def _on_mode_changed(self, index: int) -> None:
        self._error_label.setVisible(False)
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(index == 0)

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_accept(self) -> None:
        if self.current_mode() != self.MODE_BOUNDING_FRAME:
            self._show_error("Режим «Планировка помещения» пока в разработке.")
            return

        name = self.name_edit.text().strip()
        if not name:
            self._show_error("Укажите наименование модели.")
            self.name_edit.setFocus()
            return

        try:
            w, h, d = validate_bounding_frame_dims(
                self.width_spin.value(),
                self.height_spin.value(),
                self.depth_spin.value(),
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self._error_label.setVisible(False)
        self._validated_frame = BoundingFrame(width=w, height=h, depth=d, visible=True)
        self.accept()

    def get_model_settings(self) -> dict:
        """Возвращает подтверждённые настройки новой модели и габаритной рамки."""
        bf = self._validated_frame
        if bf is None:
            bf = BoundingFrame(
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                depth=self.depth_spin.value(),
                visible=True,
            )
        return {
            "mode": self.current_mode(),
            "name": self.name_edit.text().strip() or "Новое изделие",
            "order_number": self.order_edit.text().strip(),
            "bounding_frame": bf.clone(),
        }


class ProductParamsDialog(QDialog):
    """Окно «Изделие → Параметры изделия…»: редактирование метаданных и габаритной рамки."""

    def __init__(
        self,
        *,
        name: str = "",
        order_number: str = "",
        bounding_frame: BoundingFrame | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Параметры изделия")
        self.setMinimumWidth(420)
        self._base_frame = bounding_frame.clone() if bounding_frame is not None else None
        self._validated_frame: BoundingFrame | None = None

        init_w = self._base_frame.width if self._base_frame is not None else DEFAULT_FRAME_WIDTH_MM
        init_h = self._base_frame.height if self._base_frame is not None else DEFAULT_FRAME_HEIGHT_MM
        init_d = self._base_frame.depth if self._base_frame is not None else DEFAULT_FRAME_DEPTH_MM
        init_vis = self._base_frame.visible if self._base_frame is not None else True

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit(name or "Новое изделие", self)
        self.name_edit.setPlaceholderText("Наименование изделия")
        form.addRow("Наименование:", self.name_edit)

        self.order_edit = QLineEdit(order_number or "", self)
        self.order_edit.setPlaceholderText("Номер заказа для чертежей и спецификаций")
        form.addRow("Номер заказа:", self.order_edit)

        self._frame_section_label = QLabel("Габаритная рамка изделия", self)
        form.addRow(self._frame_section_label)

        self.width_spin = _make_dim_spin(init_w)
        self.height_spin = _make_dim_spin(init_h)
        self.depth_spin = _make_dim_spin(init_d)

        form.addRow("Ширина (X), мм:", self.width_spin)
        form.addRow("Высота (Y), мм:", self.height_spin)
        form.addRow("Глубина (Z), мм:", self.depth_spin)

        self.visible_cb = QCheckBox("Показывать габаритную рамку в 3D", self)
        self.visible_cb.setChecked(bool(init_vis))
        form.addRow("", self.visible_cb)

        root.addLayout(form)

        self._hint_label = QLabel(
            "Изменение габаритов обновляет только габаритную рамку. "
            "Существующие панели не перемещаются и не изменяют размеры.",
            self,
        )
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

        self._error_label = QLabel("", self)
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText("ОК")
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = current_theme()
        self._frame_section_label.setStyleSheet(
            f"color: {t.heading}; font-weight: 600; padding-top: 6px;"
        )
        self._hint_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._error_label.setStyleSheet(
            f"color: {t.error}; font-size: 12px; font-weight: 500;"
        )

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._show_error("Укажите наименование изделия.")
            self.name_edit.setFocus()
            return
        try:
            w, h, d = validate_bounding_frame_dims(
                self.width_spin.value(),
                self.height_spin.value(),
                self.depth_spin.value(),
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self._error_label.setVisible(False)
        ox = self._base_frame.x if self._base_frame is not None else 0.0
        oy = self._base_frame.y if self._base_frame is not None else 0.0
        oz = self._base_frame.z if self._base_frame is not None else 0.0
        self._validated_frame = BoundingFrame(
            width=w,
            height=h,
            depth=d,
            x=ox,
            y=oy,
            z=oz,
            visible=bool(self.visible_cb.isChecked()),
        )
        self.accept()

    def get_product_params(self) -> dict:
        """Возвращает обновлённые параметры изделия."""
        bf = self._validated_frame
        if bf is None:
            ox = self._base_frame.x if self._base_frame is not None else 0.0
            oy = self._base_frame.y if self._base_frame is not None else 0.0
            oz = self._base_frame.z if self._base_frame is not None else 0.0
            bf = BoundingFrame(
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                depth=self.depth_spin.value(),
                x=ox,
                y=oy,
                z=oz,
                visible=bool(self.visible_cb.isChecked()),
            )
        return {
            "name": self.name_edit.text().strip() or "Новое изделие",
            "order_number": self.order_edit.text().strip(),
            "bounding_frame": bf.clone(),
        }
