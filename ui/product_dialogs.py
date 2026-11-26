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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
from models.room_frame import RoomFrame
from ui.dialogs import SmartDoubleSpinBox
from ui.room_layout_dialog import RoomLayoutDialog, render_room_svg_icon
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
        self.setMinimumWidth(460)
        self._validated_frame: BoundingFrame | None = None
        self._room_frame: RoomFrame | None = None
        self._room_layout_done: bool = False

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

        # ── Вкладка 2: Габаритная рамка помещения ─────────────
        self._room_tab = QWidget(self.mode_tabs)
        room_layout = QVBoxLayout(self._room_tab)
        room_layout.setContentsMargins(12, 12, 12, 12)
        room_layout.setSpacing(10)

        room_form = QFormLayout()
        room_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        room_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        room_form.setHorizontalSpacing(14)
        room_form.setVerticalSpacing(8)

        self.room_name_edit = QLineEdit("Новое помещение", self._room_tab)
        self.room_name_edit.setPlaceholderText("Например, Кухня-гостиная")
        room_form.addRow("Наименование:", self.room_name_edit)

        self.room_order_edit = QLineEdit(default_order_number, self._room_tab)
        self.room_order_edit.setPlaceholderText("Например, ЗАК-001 (для чертежей и обозначения)")
        room_form.addRow("Номер заказа:", self.room_order_edit)

        self._room_section_label = QLabel("Габаритная рамка помещения", self._room_tab)
        room_form.addRow(self._room_section_label)

        plan_row_widget = QWidget(self._room_tab)
        plan_row = QHBoxLayout(plan_row_widget)
        plan_row.setContentsMargins(0, 0, 0, 0)
        plan_row.setSpacing(10)

        self.room_layout_btn = QPushButton("Планировка помещения", plan_row_widget)
        self.room_layout_btn.clicked.connect(self._on_open_room_layout)
        plan_row.addWidget(self.room_layout_btn)

        self._room_done_icon_label = QLabel(plan_row_widget)
        self._room_done_icon_label.setVisible(False)
        plan_row.addWidget(self._room_done_icon_label)

        self.room_status_label = QLabel("Планировка закончена", plan_row_widget)
        self.room_status_label.setVisible(False)
        plan_row.addWidget(self.room_status_label)
        plan_row.addStretch(1)

        room_form.addRow("Контур помещения:", plan_row_widget)
        room_layout.addLayout(room_form)

        self._room_summary_label = QLabel(
            "Нажмите «Планировка помещения», чтобы задать стены, углы, неровности, "
            "проёмы и препятствия перед переходом в основную 3D-среду.",
            self._room_tab,
        )
        self._room_summary_label.setWordWrap(True)
        room_layout.addWidget(self._room_summary_label)
        room_layout.addStretch(1)

        self.mode_tabs.addTab(self._frame_tab, "Габаритная рамка")
        self.mode_tabs.addTab(self._room_tab, "Габаритная рамка помещения")
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
        self._room_section_label.setStyleSheet(
            f"color: {t.heading}; font-weight: 600; padding-top: 6px;"
        )
        self._hint_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._room_summary_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._error_label.setStyleSheet(
            f"color: {t.error}; font-size: 12px; font-weight: 500;"
        )
        self.room_status_label.setStyleSheet(
            f"color: {t.success}; font-size: 12px; font-weight: 600;"
        )
        self.room_layout_btn.setIcon(render_room_svg_icon("room_plan.svg", t.text, 16))
        self.mode_tabs.setTabIcon(1, render_room_svg_icon("room_frame.svg", t.text, 15))
        done_ico = render_room_svg_icon("room_check_done.svg", t.success, 16)
        self._room_done_icon_label.setPixmap(done_ico.pixmap(16, 16))

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
            ok_btn.setEnabled(index == 0 or self._room_layout_done)

    def _on_open_room_layout(self) -> None:
        dlg = RoomLayoutDialog(self._room_frame, parent=self)
        if dlg.exec():
            self._room_frame = dlg.get_room_frame()
            self._room_layout_done = True
            self._room_done_icon_label.setVisible(True)
            self.room_status_label.setVisible(True)
            n_openings = sum(len(w.openings) for w in self._room_frame.walls)
            self._room_summary_label.setText(
                f"Стен: {len(self._room_frame.walls)} · "
                f"Площадь: {self._room_frame.floor_area_m2():.2f} м² · "
                f"Высота: {self._room_frame.ceiling_height_mm:.0f} мм · "
                f"Проёмов: {n_openings} · Препятствий: {len(self._room_frame.obstacles)}"
            )
            self._error_label.setVisible(False)
            self._on_mode_changed(self.mode_tabs.currentIndex())

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_accept(self) -> None:
        if self.current_mode() == self.MODE_ROOM_LAYOUT:
            name = self.room_name_edit.text().strip()
            if not name:
                self._show_error("Укажите наименование помещения.")
                self.room_name_edit.setFocus()
                return
            if not self._room_layout_done or self._room_frame is None:
                self._show_error("Сначала выполните планировку помещения кнопкой «Планировка помещения».")
                return
            try:
                self._room_frame.validate()
            except ValueError as exc:
                self._show_error(str(exc))
                return
            self._room_frame.name = name
            self._error_label.setVisible(False)
            self.accept()
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
        """Возвращает подтверждённые настройки новой модели (изделия или помещения)."""
        if self.current_mode() == self.MODE_ROOM_LAYOUT:
            rf = self._room_frame.clone() if self._room_frame is not None else RoomFrame.create_rectangular()
            name = self.room_name_edit.text().strip() or "Новое помещение"
            rf.name = name
            return {
                "mode": self.MODE_ROOM_LAYOUT,
                "name": name,
                "order_number": self.room_order_edit.text().strip(),
                "bounding_frame": None,
                "room_frame": rf,
            }
        bf = self._validated_frame
        if bf is None:
            bf = BoundingFrame(
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                depth=self.depth_spin.value(),
                visible=True,
            )
        return {
            "mode": self.MODE_BOUNDING_FRAME,
            "name": self.name_edit.text().strip() or "Новое изделие",
            "order_number": self.order_edit.text().strip(),
            "bounding_frame": bf.clone(),
            "room_frame": None,
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


class CreateBlockDialog(QDialog):
    """Диалог «Создать блок…»: название блока и признак сборочной единицы."""

    def __init__(
        self,
        *,
        default_name: str = "Блок 1",
        panel_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Создать блок")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit(default_name or "Блок 1", self)
        self.name_edit.setPlaceholderText("Например, Корпус тумбы")
        form.addRow("Название блока:", self.name_edit)

        self.assembly_cb = QCheckBox("Сборочная единица", self)
        self.assembly_cb.setChecked(False)
        form.addRow("", self.assembly_cb)

        root.addLayout(form)

        count_hint = (
            f"Выбрано элементов: {int(panel_count)}.\n"
            if int(panel_count) > 0
            else ""
        )
        self._hint_label = QLabel(
            f"{count_hint}"
            "Если отмечена «Сборочная единица», блоку и входящим в него деталям "
            "будут расставлены позиции. Если галочка снята — позиции не назначаются.",
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
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def refresh_theme(self) -> None:
        t = current_theme()
        self._hint_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._error_label.setStyleSheet(
            f"color: {t.error}; font-size: 12px; font-weight: 500;"
        )

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._error_label.setText("Укажите название блока.")
            self._error_label.setVisible(True)
            self.name_edit.setFocus()
            return
        self._error_label.setVisible(False)
        self.accept()

    def get_block_params(self) -> dict:
        """Возвращает подтверждённые параметры создаваемого блока."""
        return {
            "name": self.name_edit.text().strip() or "Блок",
            "is_assembly": bool(self.assembly_cb.isChecked()),
        }

