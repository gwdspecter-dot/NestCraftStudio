"""Панель свойств выделенного объекта (панель / корпус)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.logging_setup import get_logger
from models.panel import Panel, ParametricCabinet

_log = get_logger("properties_ui")


class PropertiesDock(QDockWidget):
    property_changed = pyqtSignal()
    # obj, attr_name, old_val, new_val
    property_applied = pyqtSignal(object, str, object, object)
    # Сообщение об отклонённом вводе (для statusBar)
    validation_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Свойства", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.current_obj = None
        self._updating = False

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Параметр", "Значение"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)

        self.setWidget(self.table)
        self.show_object_properties(None)

    # ── public API ────────────────────────────────────────────

    def show_object_properties(self, obj):
        self._updating = True
        self.current_obj = obj
        self.table.setRowCount(0)
        # Убираем старые виджеты-редакторы (combo и т.п.)
        self.table.clearContents()

        if isinstance(obj, ParametricCabinet):
            props = [
                ("Наименование модуля", obj.name, "name"),
                ("Ширина корпуса (X), мм", str(int(obj.width)), "width"),
                ("Высота корпуса (Y), мм", str(int(obj.height)), "height"),
                ("Глубина корпуса (Z), мм", str(int(obj.depth)), "depth"),
                ("Толщина ЛДСП, мм", str(int(obj.thickness)), "thickness"),
                ("Количество полок, шт", str(obj.shelves_count), "shelves_count"),
                ("Фасад (1 - да, 0 - нет)", "1" if obj.has_facade else "0", "has_facade"),
                ("Позиция X, мм", str(int(obj.x)), "x"),
                ("Позиция Y, мм", str(int(obj.y)), "y"),
                ("Позиция Z, мм", str(int(obj.z)), "z"),
            ]
            self._fill_text_props(props)

        elif isinstance(obj, Panel):
            saw_x, saw_y, saw_z = (
                obj.get_saw_dimensions()
                if hasattr(obj, "get_saw_dimensions")
                else (obj.width, obj.height, obj.depth)
            )
            saw_str = f"{saw_x:.1f} × {saw_y:.1f} × {saw_z:.1f} мм"

            t_mm = float(obj.material_thickness_mm()) if hasattr(obj, "material_thickness_mm") else min(obj.width, obj.height, obj.depth)
            tax = int(getattr(obj, "thickness_axis", 0)) % 3
            axis_names = ("X", "Y", "Z")
            props = [
                ("Наименование", obj.name, "name"),
                # row 1: Материал (combo)
                ("Ширина (по X), мм", str(obj.width), "width" if tax != 0 else None),
                ("Высота (по Y), мм", str(obj.height), "height" if tax != 1 else None),
                ("Глубина (по Z), мм", str(obj.depth), "depth" if tax != 2 else None),
                (f"Толщина плиты (ось {axis_names[tax]}), мм", f"{t_mm:g} — из материала", None),
                ("Пильный размер (раскрой)", saw_str, None),
                ("Координата X, мм", str(obj.x), "x"),
                ("Координата Y, мм", str(obj.y), "y"),
                ("Координата Z, мм", str(obj.z), "z"),
                ("Поворот Rx, град", str(getattr(obj, "rx", 0.0)), "rx"),
                ("Поворот Ry, град", str(getattr(obj, "ry", 0.0)), "ry"),
                ("Поворот Rz, град", str(getattr(obj, "rz", 0.0)), "rz"),
                # Далее 4 строки кромки (combos)
            ]

            edge_sides = [
                ("Кромка Верх (L1)", "top"),
                ("Кромка Низ (L2)", "bottom"),
                ("Кромка Лево (W1)", "left"),
                ("Кромка Право (W2)", "right"),
            ]

            total_rows = 1 + 1 + (len(props) - 1) + len(edge_sides)
            self.table.setRowCount(total_rows)

            # 0. Наименование
            self._set_label_cell(0, "Наименование", "name")
            self._set_value_cell(0, obj.name, editable=True)

            # 1. Материал (combo)
            self._set_label_cell(1, "Материал", "material")
            combo = self._make_material_combo(obj)
            self.table.setCellWidget(1, 1, combo)

            # 2..N. Числовые свойства
            curr_row = 2
            for label, val, attr in props[1:]:
                self._set_label_cell(curr_row, label, attr)
                self._set_value_cell(curr_row, val, editable=(attr is not None))
                curr_row += 1

            # N+1..N+4. Кромкооблицовка (combos)
            for edge_label, side in edge_sides:
                self._set_label_cell(curr_row, edge_label, f"edge_{side}")
                e_combo = self._make_edge_combo(obj, side)
                self.table.setCellWidget(curr_row, 1, e_combo)
                curr_row += 1

        else:
            props = [
                ("Наименование", "Новый проект", None),
                ("Заказ", "Новый проект", None),
                ("Основной материал", "МИСТ VL 16 мм", None),
            ]
            self._fill_text_props(props)

        self._updating = False

    # ── helpers ───────────────────────────────────────────────

    def _fill_text_props(self, props: list) -> None:
        self.table.setRowCount(len(props))
        for row, (label, val, attr) in enumerate(props):
            self._set_label_cell(row, label, attr)
            self._set_value_cell(row, val, editable=(attr is not None))

    def _set_label_cell(self, row: int, label: str, attr) -> None:
        lbl_item = QTableWidgetItem(label)
        lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        lbl_item.setData(Qt.ItemDataRole.UserRole, attr)
        self.table.setItem(row, 0, lbl_item)

    def _set_value_cell(self, row: int, val: str, *, editable: bool) -> None:
        val_item = QTableWidgetItem(str(val) if val is not None else "")
        if not editable:
            val_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 1, val_item)

    def _make_material_combo(self, panel: Panel) -> QComboBox:
        """QComboBox со списком материалов из каталога."""
        combo = QComboBox()
        combo.setEditable(False)
        combo.setMaxVisibleItems(16)
        combo.setStyleSheet("QComboBox { padding: 2px 6px; }")

        current_id = getattr(panel, "material_id", "") or ""
        materials = []
        try:
            from core.catalog import CatalogService
            materials = CatalogService.instance().list_materials(active_only=True)
        except Exception:
            _log.exception("Не удалось загрузить список материалов из каталога для комбобокса")
            materials = []

        # Группируем визуально: сначала по типу, потом по толщине/имени
        # (QComboBox не умеет настоящие группы без QStandardItemModel — просто сортируем)
        materials = sorted(
            materials,
            key=lambda m: (m.material_type, m.thickness_mm, m.name),
        )

        selected_idx = 0
        for i, m in enumerate(materials):
            # «ЛДСП · МИСТ VL 16 мм»
            type_label = {
                "ldsp": "ЛДСП",
                "mdf": "МДФ",
                "hdf": "ХДФ",
                "plywood": "Фанера",
                "solid": "Массив",
            }.get(m.material_type, m.material_type.upper())
            label = f"{type_label} · {m.display_name}"
            combo.addItem(label, m.id)  # userData = material_id
            if m.id == current_id:
                selected_idx = i

        if materials:
            combo.setCurrentIndex(selected_idx)
        else:
            # Каталог пуст / недоступен — показываем текущее имя
            combo.addItem(panel.material or "—", current_id or "")
            combo.setCurrentIndex(0)

        combo.currentIndexChanged.connect(self._on_material_combo_changed)
        return combo

    def _on_material_combo_changed(self, index: int) -> None:
        if self._updating or not isinstance(self.current_obj, Panel):
            return
        combo = self.sender()
        if not isinstance(combo, QComboBox) or index < 0:
            return

        new_id = combo.currentData()
        if not new_id:
            return

        old_id = getattr(self.current_obj, "material_id", None)
        if new_id == old_id:
            return

        # Передаём material_id как new_val — EditPropertyCommand умеет резолвить и id, и имя
        old_display = self.current_obj.material
        self.property_applied.emit(self.current_obj, "material", old_display, new_id)
        self.property_changed.emit()

    def _make_edge_combo(self, panel: Panel, side: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem("— (Без кромки)", "")

        edges = []
        try:
            from core.catalog import CatalogService
            edges = CatalogService.instance().list_edge_bands()
        except Exception:
            _log.exception("Не удалось загрузить список кромок из каталога для комбобокса")
            edges = []

        current_edge_id = getattr(panel, "edges", {}).get(side, "")
        selected_idx = 0

        for i, eb in enumerate(edges):
            label = f"{eb.display_name} ({eb.thickness_mm:g} мм)"
            combo.addItem(label, eb.id)
            if eb.id == current_edge_id:
                selected_idx = i + 1

        if current_edge_id and selected_idx == 0:
            combo.addItem(f"⚠ Не найдена в каталоге ({current_edge_id})", current_edge_id)
            selected_idx = combo.count() - 1

        combo.setCurrentIndex(selected_idx)
        combo.currentIndexChanged.connect(lambda idx, s=side, c=combo: self._on_edge_combo_changed(s, c))
        return combo

    def _on_edge_combo_changed(self, side: str, combo: QComboBox) -> None:
        if self._updating or not isinstance(self.current_obj, Panel):
            return
        new_edge_id = combo.currentData() or ""
        old_edge_id = getattr(self.current_obj, "edges", {}).get(side, "")
        if new_edge_id == old_edge_id:
            return

        self.current_obj.set_edge(side, new_edge_id)
        self.property_applied.emit(self.current_obj, f"edge_{side}", old_edge_id, new_edge_id)
        self.property_changed.emit()
        self.show_object_properties(self.current_obj)

    # ── text cell editing ─────────────────────────────────────

    # Габариты / толщина: конечные положительные мм
    _SIZE_ATTRS = frozenset({"width", "height", "depth", "thickness"})
    _SIZE_MIN = 1.0
    _SIZE_MAX = 10000.0
    # Координаты: конечные, разумный диапазон цеха
    _COORD_ATTRS = frozenset({"x", "y", "z"})
    _COORD_MIN = -50000.0
    _COORD_MAX = 50000.0
    # Углы поворота, градусы
    _ANGLE_ATTRS = frozenset({"rx", "ry", "rz"})
    _ANGLE_MIN = -360.0
    _ANGLE_MAX = 360.0

    @staticmethod
    def _parse_finite_float(
        text: str,
        *,
        current_value: float | None = None,
        obj: object = None,
    ) -> float:
        """Вычисляет число или арифметическую формулу (`600 - 32`, `720 / 3`, `w - 32`, `+= 16`) без nan/inf."""
        from core.formula import context_vars_from_object, eval_math_expression

        env = context_vars_from_object(obj, current_value=current_value)
        return eval_math_expression(text, current_value=current_value, variables=env)

    def _validate_numeric_attr(self, attr_name: str, raw: str):
        """Возвращает (ok, value_or_None). ok=False → откатить ячейку."""
        cur_raw = getattr(self.current_obj, attr_name, None) if self.current_obj is not None else None
        cur_float = float(cur_raw) if isinstance(cur_raw, (int, float)) and not isinstance(cur_raw, bool) else None
        try:
            if attr_name in self._SIZE_ATTRS:
                v = self._parse_finite_float(raw, current_value=cur_float, obj=self.current_obj)
                if v < self._SIZE_MIN or v > self._SIZE_MAX:
                    return False, None
                return True, v
            if attr_name in self._COORD_ATTRS:
                v = self._parse_finite_float(raw, current_value=cur_float, obj=self.current_obj)
                if v < self._COORD_MIN or v > self._COORD_MAX:
                    return False, None
                return True, v
            if attr_name in self._ANGLE_ATTRS:
                v = self._parse_finite_float(raw, current_value=cur_float, obj=self.current_obj)
                if v < self._ANGLE_MIN or v > self._ANGLE_MAX:
                    return False, None
                return True, v
            if attr_name == "shelves_count":
                v = self._parse_finite_float(raw, current_value=cur_float, obj=self.current_obj)
                n = int(round(v))
                if n < 0 or n > 50:
                    return False, None
                return True, n
            if attr_name == "has_facade":
                return True, raw.strip().lower() in ("1", "да", "true", "+", "yes", "y")
        except (ValueError, TypeError, OverflowError):
            return False, None
        return True, raw  # строки (name и т.п.)

    def _revert_item(self, item: QTableWidgetItem, attr_name: str) -> None:
        self._updating = True
        try:
            cur = getattr(self.current_obj, attr_name, "")
            if attr_name == "has_facade":
                item.setText("1" if cur else "0")
            elif isinstance(cur, float):
                item.setText(f"{cur:g}")
            else:
                item.setText(str(cur))
        except Exception:
            _log.exception("Не удалось откатить значение ячейки %s в таблице свойств", attr_name)
        self._updating = False

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._updating or self.current_obj is None or item.column() != 1:
            return

        attr_name = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        if not attr_name or attr_name == "material" or str(attr_name).startswith("edge_"):
            return

        old_val = getattr(self.current_obj, attr_name, None)
        raw_input = item.text().strip()
        new_val_str = raw_input.replace(",", ".")
        if not new_val_str and attr_name in (
            self._SIZE_ATTRS | self._COORD_ATTRS | self._ANGLE_ATTRS | {"shelves_count"}
        ):
            self._revert_item(item, attr_name)
            return

        ok, new_val = self._validate_numeric_attr(attr_name, new_val_str)
        if not ok:
            self._revert_item(item, attr_name)
            self.validation_failed.emit(f"Недопустимое значение или формула «{raw_input}» для «{attr_name}»")
            return

        is_num_attr = attr_name in (
            self._SIZE_ATTRS | self._COORD_ATTRS | self._ANGLE_ATTRS | {"shelves_count"}
        )
        if not is_num_attr and attr_name != "has_facade":
            new_val = item.text()  # имя и прочий текст — как ввели

        # Персистентный driver: формула с переменными; «+=» — разово, голое число снимает driver
        self._pending_driver_expr = None
        if is_num_attr:
            from core.drivers import should_persist_formula
            from core.formula import is_formula_text

            if should_persist_formula(raw_input):
                self._pending_driver_expr = raw_input
            elif attr_name in ("width", "height", "depth", "x", "y", "z"):
                # явное число / разовое += → снять driver
                self._pending_driver_expr = ""

            if is_formula_text(raw_input):
                self._updating = True
                try:
                    item.setText(f"{new_val:g}" if isinstance(new_val, float) else str(new_val))
                finally:
                    self._updating = False
                mark = "📌" if self._pending_driver_expr else "🧮"
                self.validation_failed.emit(f"{mark} Формула [{attr_name}]: {raw_input} = {new_val:g}")

        if old_val == new_val and self._pending_driver_expr is None:
            return

        # Корпус: геометрические/технологические минимумы (план §1.3)
        if isinstance(self.current_obj, ParametricCabinet) and attr_name in (
            "width", "height", "depth", "thickness", "shelves_count"
        ):
            from core.validation import validate_cabinet_params, cabinet_params_from_obj
            params = cabinet_params_from_obj(self.current_obj, {attr_name: new_val})
            errs = validate_cabinet_params(**params)
            if errs:
                self._revert_item(item, attr_name)
                self.validation_failed.emit(errs[0])
                return

        self.property_applied.emit(self.current_obj, attr_name, old_val, new_val)
        self.property_changed.emit()

