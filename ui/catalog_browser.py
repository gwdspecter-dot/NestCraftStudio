"""
Библиотека материалов и крепежа — окно просмотра каталога NestCraft.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QLabel,
    QPushButton,
    QWidget,
    QFormLayout,
    QGroupBox,
    QSplitter,
    QAbstractItemView,
    QComboBox,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
    QMenu,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QAction

from core.logging_setup import get_logger

_log = get_logger("catalog_ui")


class CatalogBrowserDialog(QDialog):
    """Просмотр каталога: материалы, кромка, крепёж.

    Сигнал material_assign_requested(material_id) — пользователь нажал
    «Назначить на выделенную панель».
    """

    material_assign_requested = pyqtSignal(str)  # material_id
    edge_assign_requested = pyqtSignal(str, str)  # edge_id, side ("all", "top", "bottom", "left", "right")

    def __init__(self, parent=None, target_panel_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Библиотека материалов и крепежа")
        self.setMinimumSize(1100, 620)
        self.resize(1180, 680)
        self._target_panel_name = target_panel_name or ""
        self._filter_group_ids: list | None = None
        self._filter_scope: str = "all"

        self._catalog = None
        try:
            from core.catalog import CatalogService
            self._catalog = CatalogService.instance()
            if hasattr(self._catalog, "ensure_default_groups"):
                self._catalog.ensure_default_groups()
        except Exception as e:
            QMessageBox.warning(self, "Каталог", f"Не удалось открыть каталог:\n{e}")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(4)

        # ── Заголовок + статистика (компактная полоса) ────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("<b>Справочник NestCraft</b>")
        title.setStyleSheet("font-size: 13px;")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title.setFixedHeight(22)
        header.addWidget(title)
        header.addStretch()
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #888; font-size: 11px;")
        self.stats_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.stats_label.setFixedHeight(22)
        header.addWidget(self.stats_label)
        root.addLayout(header, stretch=0)

        # ── Слева дерево групп | справа вкладки ───────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setChildrenCollapsible(False)
        main_split.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        left = QWidget()
        left.setMinimumWidth(260)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 6, 0)
        left_lay.setSpacing(4)

        left_title = QLabel("<b>Группы каталога</b>")
        left_title.setStyleSheet(
            "font-size: 13px; padding: 4px 6px; background: #e8eef6; border-radius: 4px;"
        )
        left_lay.addWidget(left_title)

        self.group_tree = QTreeWidget()
        self.group_tree.setHeaderHidden(True)
        self.group_tree.setMinimumWidth(240)
        self.group_tree.setIndentation(18)
        self.group_tree.setUniformRowHeights(True)
        self.group_tree.setStyleSheet(
            "QTreeWidget { font-size: 13px; border: 1px solid #c5d0de; }"
            "QTreeWidget::item { padding: 3px 4px; }"
            "QTreeWidget::item:selected { background: #3d6ea5; color: white; }"
        )
        self.group_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_tree.customContextMenuRequested.connect(self._on_group_context_menu)
        self.group_tree.itemSelectionChanged.connect(self._on_group_selected)
        left_lay.addWidget(self.group_tree, stretch=1)

        grp_btns = QHBoxLayout()
        self.btn_add_group = QPushButton("+ Группа")
        self.btn_add_group.setToolTip("Добавить корневую группу")
        self.btn_add_group.clicked.connect(lambda: self._on_add_group(as_child=False))
        grp_btns.addWidget(self.btn_add_group)
        self.btn_add_subgroup = QPushButton("+ Подгруппа")
        self.btn_add_subgroup.setToolTip("Добавить подгруппу в выбранный узел")
        self.btn_add_subgroup.clicked.connect(lambda: self._on_add_group(as_child=True))
        grp_btns.addWidget(self.btn_add_subgroup)
        left_lay.addLayout(grp_btns)

        grp_btns2 = QHBoxLayout()
        self.btn_rename_group = QPushButton("Переименовать")
        self.btn_rename_group.clicked.connect(self._on_rename_group)
        grp_btns2.addWidget(self.btn_rename_group)
        self.btn_del_group = QPushButton("Удалить")
        self.btn_del_group.clicked.connect(self._on_delete_group)
        grp_btns2.addWidget(self.btn_del_group)
        left_lay.addLayout(grp_btns2)

        main_split.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_materials_tab(), "Материалы")
        self.tabs.addTab(self._build_edges_tab(), "Кромка")
        self.tabs.addTab(self._build_fasteners_tab(), "Крепёж")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_split.addWidget(self.tabs)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([280, 860])
        root.addWidget(main_split, stretch=1)

        # ── Низ ───────────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.path_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bottom.addWidget(self.path_label)
        bottom.addStretch()

        self.assign_btn = QPushButton("Назначить на выделенную панель")
        self.assign_btn.setToolTip(
            "Применить выбранный материал к выделенной панели в сцене"
        )
        self.assign_btn.setEnabled(False)
        self.assign_btn.clicked.connect(self._on_assign_clicked)
        bottom.addWidget(self.assign_btn)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom, stretch=0)

        self._refresh_stats()
        self._reload_group_tree()
        self._reload_all()
        self._update_assign_button()
        self._update_material_action_buttons()
        self._update_edge_action_buttons()
        self._update_group_action_buttons()

    # ══════════════════════════════════════════════════════════
    #  Materials tab
    # ══════════════════════════════════════════════════════════

    def _build_materials_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        # Фильтры + кнопка «Новый»
        filters = QHBoxLayout()
        self.mat_search = QLineEdit()
        self.mat_search.setPlaceholderText("Поиск по названию, артикулу, цвету…")
        self.mat_search.textChanged.connect(self._filter_materials)
        filters.addWidget(self.mat_search, stretch=3)

        self.mat_type_filter = QComboBox()
        self.mat_type_filter.addItem("Все типы", "")
        for code, label in [
            ("ldsp", "ЛДСП"), ("mdf", "МДФ"), ("hdf", "ХДФ"),
            ("plywood", "Фанера"), ("solid", "Массив"),
        ]:
            self.mat_type_filter.addItem(label, code)
        self.mat_type_filter.currentIndexChanged.connect(self._filter_materials)
        filters.addWidget(self.mat_type_filter)

        self.mat_thick_filter = QComboBox()
        self.mat_thick_filter.addItem("Любая толщина", 0.0)
        for t in (3, 4, 10, 16, 18, 19, 22, 25):
            self.mat_thick_filter.addItem(f"{t} мм", float(t))
        self.mat_thick_filter.currentIndexChanged.connect(self._filter_materials)
        filters.addWidget(self.mat_thick_filter)

        self.add_mat_btn = QPushButton("+ Новый")
        self.add_mat_btn.setToolTip("Добавить материал в каталог")
        self.add_mat_btn.clicked.connect(self._on_add_material)
        filters.addWidget(self.add_mat_btn)

        self.edit_mat_btn = QPushButton("✎ Изменить")
        self.edit_mat_btn.setToolTip("Редактировать выбранный материал")
        self.edit_mat_btn.setEnabled(False)
        self.edit_mat_btn.clicked.connect(self._on_edit_material)
        filters.addWidget(self.edit_mat_btn)

        self.del_mat_btn = QPushButton("✕ Удалить")
        self.del_mat_btn.setToolTip("Удалить выбранный материал из каталога")
        self.del_mat_btn.setEnabled(False)
        self.del_mat_btn.clicked.connect(self._on_delete_material)
        filters.addWidget(self.del_mat_btn)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.mat_table = QTableWidget(0, 6)
        self.mat_table.setHorizontalHeaderLabels(
            ["Артикул", "Название", "Тип", "Толщина", "Цвет", "Цена ₽/м²"]
        )
        self.mat_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mat_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mat_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mat_table.verticalHeader().setVisible(False)
        self.mat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mat_table.setAlternatingRowColors(True)
        self.mat_table.itemSelectionChanged.connect(self._on_material_selected)
        self.mat_table.doubleClicked.connect(self._on_material_double_clicked)
        splitter.addWidget(self.mat_table)

        self.mat_detail = self._make_detail_box("Свойства материала")
        self.mat_detail_form = self.mat_detail.findChild(QFormLayout)
        splitter.addWidget(self.mat_detail)
        splitter.setSizes([640, 280])

        layout.addWidget(splitter)
        self._mat_rows: list = []  # list of Material
        return w

    def _reload_materials(self) -> None:
        self._mat_rows = []
        if self._catalog:
            if self._filter_group_ids is not None and self._filter_scope in ("edge", "fastener"):
                self._mat_rows = []
            else:
                gids = self._filter_group_ids if self._filter_scope in ("material", "all") else None
                self._mat_rows = self._catalog.list_materials(
                    group_ids=gids, active_only=True
                )
        self._filter_materials()

    def _filter_materials(self) -> None:
        query = self.mat_search.text().strip().lower()
        type_code = self.mat_type_filter.currentData() or ""
        thick = self.mat_thick_filter.currentData() or 0.0

        filtered = []
        for m in self._mat_rows:
            if type_code and m.material_type != type_code:
                continue
            if thick and abs(m.thickness_mm - thick) > 0.05:
                continue
            if query:
                blob = f"{m.name} {m.sku} {m.color_name} {m.display_name}".lower()
                if query not in blob:
                    continue
            filtered.append(m)

        self.mat_table.setRowCount(len(filtered))
        type_map = {
            "ldsp": "ЛДСП", "mdf": "МДФ", "hdf": "ХДФ",
            "plywood": "Фанера", "solid": "Массив",
        }
        for row, m in enumerate(filtered):
            self.mat_table.setItem(row, 0, QTableWidgetItem(m.sku))
            self.mat_table.setItem(row, 1, QTableWidgetItem(m.display_name))
            self.mat_table.setItem(row, 2, QTableWidgetItem(type_map.get(m.material_type, m.material_type)))
            self.mat_table.setItem(row, 3, QTableWidgetItem(f"{m.thickness_mm:g}"))
            color_item = QTableWidgetItem(m.color_name or "—")
            r, g, b = m.color_rgb
            color_item.setBackground(QBrush(QColor(int(r * 255), int(g * 255), int(b * 255))))
            # Контрастный текст
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            color_item.setForeground(QBrush(QColor(0, 0, 0) if luminance > 0.55 else QColor(255, 255, 255)))
            self.mat_table.setItem(row, 4, color_item)
            price = f"{m.price_per_m2:.0f}" if m.price_per_m2 else "—"
            self.mat_table.setItem(row, 5, QTableWidgetItem(price))
            # id в UserRole первой ячейки
            self.mat_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, m.id)

        self.mat_table.setProperty("filtered_ids", [m.id for m in filtered])

    def _on_material_selected(self) -> None:
        items = self.mat_table.selectedItems()
        self._update_assign_button()
        self._update_material_action_buttons()
        if not items or not self._catalog:
            self._clear_form(self.mat_detail_form)
            return
        mid = self.mat_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        m = self._catalog.get_material(mid)
        if not m:
            return
        type_map = {
            "ldsp": "ЛДСП", "mdf": "МДФ", "hdf": "ХДФ",
            "plywood": "Фанера", "solid": "Массив",
        }
        rows = [
            ("ID", m.id),
            ("Артикул", m.sku),
            ("Название", m.name),
            ("Тип", type_map.get(m.material_type, m.material_type)),
            ("Толщина", f"{m.thickness_mm:g} мм"),
            ("Плотность", f"{m.density:g} кг/м³" if m.density else "—"),
            ("Цвет", m.color_name or "—"),
            ("Текстура", m.grain_direction if m.grain_direction != "none" else "нет"),
            ("Цена", f"{m.price_per_m2:.0f} {m.currency}/м²" if m.price_per_m2 else "—"),
            ("Сверление пласть", f"до {m.max_drill_depth_face:g} мм" if m.max_drill_depth_face else "—"),
            ("Сверление торец", f"до {m.max_drill_depth_edge:g} мм" if m.max_drill_depth_edge else "—"),
            ("Встроенный", "да" if m.is_builtin else "пользовательский"),
            ("Заметки", m.notes or "—"),
        ]
        self._fill_form(self.mat_detail_form, rows)

    # ══════════════════════════════════════════════════════════
    #  Edges tab
    # ══════════════════════════════════════════════════════════

    def _build_edges_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        filters = QHBoxLayout()
        self.edge_search = QLineEdit()
        self.edge_search.setPlaceholderText("Поиск кромки по названию, артикулу, декору…")
        self.edge_search.textChanged.connect(self._filter_edges)
        filters.addWidget(self.edge_search, stretch=3)

        self.edge_thick_filter = QComboBox()
        self.edge_thick_filter.addItem("Любая толщина", 0.0)
        for t in (0.4, 0.8, 1.0, 1.3, 2.0):
            self.edge_thick_filter.addItem(f"{t:g} мм", float(t))
        self.edge_thick_filter.currentIndexChanged.connect(self._filter_edges)
        filters.addWidget(self.edge_thick_filter)

        self.add_edge_btn = QPushButton("+ Новая")
        self.add_edge_btn.setToolTip("Добавить новую кромку в каталог")
        self.add_edge_btn.clicked.connect(self._on_add_edge)
        filters.addWidget(self.add_edge_btn)

        self.edit_edge_btn = QPushButton("✎ Изменить")
        self.edit_edge_btn.setToolTip("Редактировать выбранную кромку")
        self.edit_edge_btn.setEnabled(False)
        self.edit_edge_btn.clicked.connect(self._on_edit_edge)
        filters.addWidget(self.edit_edge_btn)

        self.del_edge_btn = QPushButton("✕ Удалить")
        self.del_edge_btn.setToolTip("Удалить выбранную кромку из каталога")
        self.del_edge_btn.setEnabled(False)
        self.del_edge_btn.clicked.connect(self._on_delete_edge)
        filters.addWidget(self.del_edge_btn)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.edge_table = QTableWidget(0, 6)
        self.edge_table.setHorizontalHeaderLabels(
            ["Артикул", "Название", "Тип", "Сечение", "Цвет", "Цена ₽/м"]
        )
        self.edge_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.edge_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.edge_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.edge_table.verticalHeader().setVisible(False)
        self.edge_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.edge_table.setAlternatingRowColors(True)
        self.edge_table.itemSelectionChanged.connect(self._on_edge_selected)
        self.edge_table.doubleClicked.connect(self._on_edge_double_clicked)
        splitter.addWidget(self.edge_table)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.edge_detail = self._make_detail_box("Свойства кромки")
        self.edge_detail_form = self.edge_detail.findChild(QFormLayout)
        right_layout.addWidget(self.edge_detail)

        assign_box = QGroupBox("Нанесение кромки на деталь")
        ab_layout = QVBoxLayout(assign_box)

        self.btn_edge_all = QPushButton("🔲 На все 4 стороны")
        self.btn_edge_all.setToolTip("Облицевать выбранной кромкой все 4 торца (верх, низ, лево, право)")
        self.btn_edge_all.setEnabled(False)
        self.btn_edge_all.clicked.connect(self._on_assign_edge_all)
        ab_layout.addWidget(self.btn_edge_all)

        side_row = QHBoxLayout()
        self.edge_side_combo = QComboBox()
        self.edge_side_combo.addItem("Верхний торец", "top")
        self.edge_side_combo.addItem("Нижний торец", "bottom")
        self.edge_side_combo.addItem("Левый торец", "left")
        self.edge_side_combo.addItem("Правый торец", "right")
        side_row.addWidget(self.edge_side_combo, stretch=2)

        self.btn_edge_side = QPushButton("На торец")
        self.btn_edge_side.setToolTip("Облицевать выбранный торец детали")
        self.btn_edge_side.setEnabled(False)
        self.btn_edge_side.clicked.connect(self._on_assign_edge_side)
        side_row.addWidget(self.btn_edge_side, stretch=1)
        ab_layout.addLayout(side_row)

        right_layout.addWidget(assign_box)
        right_layout.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([620, 300])

        layout.addWidget(splitter)
        self._edge_rows: list = []
        return w

    def _reload_edges(self) -> None:
        self._edge_rows = []
        if self._catalog:
            if self._filter_group_ids is not None and self._filter_scope in ("material", "fastener"):
                self._edge_rows = []
            else:
                gids = self._filter_group_ids if self._filter_scope in ("edge", "all") else None
                self._edge_rows = self._catalog.list_edges(
                    group_ids=gids, active_only=True
                )
        self._filter_edges()

    def _filter_edges(self) -> None:
        query = self.edge_search.text().strip().lower()
        thick = getattr(self, "edge_thick_filter", None)
        thick_val = thick.currentData() if thick else 0.0

        filtered = []
        for e in self._edge_rows:
            if thick_val and abs(e.thickness_mm - thick_val) > 0.05:
                continue
            if query:
                blob = f"{e.name} {e.sku} {e.color_name} {e.display_name}".lower()
                if query not in blob:
                    continue
            filtered.append(e)

        self.edge_table.setRowCount(len(filtered))
        for row, e in enumerate(filtered):
            self.edge_table.setItem(row, 0, QTableWidgetItem(e.sku))
            self.edge_table.setItem(row, 1, QTableWidgetItem(e.display_name))
            self.edge_table.setItem(row, 2, QTableWidgetItem(e.material_type.upper()))
            self.edge_table.setItem(row, 3, QTableWidgetItem(f"{e.thickness_mm:g}×{e.width_mm:g} мм"))

            color_item = QTableWidgetItem(e.color_name or "—")
            r, g, b = e.color_rgb
            color_item.setBackground(QBrush(QColor(int(r * 255), int(g * 255), int(b * 255))))
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            color_item.setForeground(QBrush(QColor(0, 0, 0) if luminance > 0.55 else QColor(255, 255, 255)))
            self.edge_table.setItem(row, 4, color_item)

            price = f"{e.price_per_m:.0f}" if e.price_per_m else "—"
            self.edge_table.setItem(row, 5, QTableWidgetItem(price))
            self.edge_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, e.id)

    def _on_edge_selected(self) -> None:
        items = self.edge_table.selectedItems()
        self._update_assign_button()
        self._update_edge_action_buttons()
        if not items or not self._catalog:
            self._clear_form(self.edge_detail_form)
            return
        eid = self.edge_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        e = self._catalog.get_edge(eid)
        if not e:
            return
        rows = [
            ("ID", e.id),
            ("Артикул", e.sku),
            ("Название", e.name),
            ("Тип", e.material_type.upper()),
            ("Толщина", f"{e.thickness_mm:g} мм"),
            ("Ширина", f"{e.width_mm:g} мм"),
            ("Цвет", e.color_name or "—"),
            ("Цена", f"{e.price_per_m:.0f} {e.currency}/м" if e.price_per_m else "—"),
            ("Встроенный", "да" if e.is_builtin else "пользовательский"),
            ("Заметки", e.notes or "—"),
        ]
        self._fill_form(self.edge_detail_form, rows)

    # ══════════════════════════════════════════════════════════
    #  Fasteners tab
    # ══════════════════════════════════════════════════════════

    def _build_fasteners_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        filters = QHBoxLayout()
        self.fst_search = QLineEdit()
        self.fst_search.setPlaceholderText("Поиск крепежа…")
        self.fst_search.textChanged.connect(self._filter_fasteners)
        filters.addWidget(self.fst_search, stretch=3)

        self.fst_type_filter = QComboBox()
        self.fst_type_filter.addItem("Все типы", "")
        self.fst_type_filter.currentIndexChanged.connect(self._filter_fasteners)
        filters.addWidget(self.fst_type_filter)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.fst_table = QTableWidget(0, 5)
        self.fst_table.setHorizontalHeaderLabels(
            ["Артикул", "Название", "Тип", "Ø×L", "Шаг"]
        )
        self.fst_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fst_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fst_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fst_table.verticalHeader().setVisible(False)
        self.fst_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.fst_table.setAlternatingRowColors(True)
        self.fst_table.itemSelectionChanged.connect(self._on_fastener_selected)
        splitter.addWidget(self.fst_table)

        self.fst_detail = self._make_detail_box("Свойства крепежа")
        self.fst_detail_form = self.fst_detail.findChild(QFormLayout)
        splitter.addWidget(self.fst_detail)
        splitter.setSizes([640, 280])

        layout.addWidget(splitter)
        self._fst_rows: list = []
        self._fst_types: dict = {}
        return w

    def _reload_fasteners(self) -> None:
        self._fst_rows = []
        self._fst_types = {}
        if self._catalog:
            rows = self._catalog.list_fasteners(active_only=True)
            if self._filter_group_ids is not None and self._filter_scope in ("material", "edge"):
                rows = []
            elif self._filter_group_ids is not None and self._filter_scope in ("fastener", "all"):
                gset = set(self._filter_group_ids)
                rows = [f for f in rows if getattr(f, "group_id", None) in gset]
            self._fst_rows = rows
            self._fst_types = {t.id: t for t in self._catalog.list_fastener_types()}
            self.fst_type_filter.blockSignals(True)
            self.fst_type_filter.clear()
            self.fst_type_filter.addItem("Все типы", "")
            for t in self._catalog.list_fastener_types():
                self.fst_type_filter.addItem(t.name, t.code)
            self.fst_type_filter.blockSignals(False)
        self._filter_fasteners()

    def _filter_fasteners(self) -> None:
        query = self.fst_search.text().strip().lower()
        type_code = self.fst_type_filter.currentData() or ""

        filtered = []
        for f in self._fst_rows:
            t = self._fst_types.get(f.type_id)
            if type_code and (not t or t.code != type_code):
                continue
            if query:
                tname = t.name if t else ""
                blob = f"{f.name} {f.sku} {f.display_name} {tname}".lower()
                if query not in blob:
                    continue
            filtered.append(f)

        self.fst_table.setRowCount(len(filtered))
        for row, f in enumerate(filtered):
            t = self._fst_types.get(f.type_id)
            self.fst_table.setItem(row, 0, QTableWidgetItem(f.sku))
            self.fst_table.setItem(row, 1, QTableWidgetItem(f.display_name))
            self.fst_table.setItem(row, 2, QTableWidgetItem(t.name if t else "—"))
            self.fst_table.setItem(row, 3, QTableWidgetItem(f"Ø{f.diameter_mm:g}×{f.length_mm:g}"))
            self.fst_table.setItem(row, 4, QTableWidgetItem(f"{f.recommended_spacing_mm:g}"))
            self.fst_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, f.id)

    def _on_fastener_selected(self) -> None:
        items = self.fst_table.selectedItems()
        if not items or not self._catalog:
            self._clear_form(self.fst_detail_form)
            return
        fid = self.fst_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        f = self._catalog.get_fastener(fid)
        if not f:
            return
        t = self._fst_types.get(f.type_id)
        face = (
            f"Ø{f.drill_face_diameter:g}"
            + (" сквозное" if f.drill_through or f.drill_face_depth <= 0
               else f" × {f.drill_face_depth:g} мм")
        )
        edge = (
            f"Ø{f.drill_edge_diameter:g} × {f.drill_edge_depth:g} мм"
            if f.drill_edge_depth > 0 else f"Ø{f.drill_edge_diameter:g}"
        )
        rows = [
            ("ID", f.id),
            ("Артикул", f.sku),
            ("Название", f.name),
            ("Тип", t.name if t else "—"),
            ("Размер", f"Ø{f.diameter_mm:g} × {f.length_mm:g} мм"),
            ("Головка", f"Ø{f.head_diameter_mm:g}" if f.head_diameter_mm else "—"),
            ("Сверление пласть", face),
            ("Сверление торец", edge),
            ("Толщина панели", f"{f.min_panel_thickness:g}–{f.max_panel_thickness:g} мм"),
            ("Шаг", f"{f.recommended_spacing_mm:g} мм"),
            ("Цена", f"{f.price:.1f} {f.currency}" if f.price else "—"),
            ("Упаковка", f"{f.pack_qty} шт" if f.pack_qty else "—"),
            ("Заметки", f.notes or "—"),
        ]
        self._fill_form(self.fst_detail_form, rows)

    # ══════════════════════════════════════════════════════════
    #  Shared helpers
    # ══════════════════════════════════════════════════════════

    def _make_detail_box(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        # placeholder
        form.addRow(QLabel("Выберите строку в таблице"))
        return box

    def _clear_form(self, form: Optional[QFormLayout]) -> None:
        if form is None:
            return
        while form.rowCount():
            form.removeRow(0)
        form.addRow(QLabel("Выберите строку в таблице"))

    def _fill_form(self, form: Optional[QFormLayout], rows: list) -> None:
        if form is None:
            return
        while form.rowCount():
            form.removeRow(0)
        for label, value in rows:
            lbl = QLabel(f"<span style='color:#666'>{label}:</span>")
            val = QLabel(str(value))
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            form.addRow(lbl, val)

    def _refresh_stats(self) -> None:
        if not self._catalog:
            self.stats_label.setText("каталог недоступен")
            self.path_label.setText("")
            return
        s = self._catalog.stats()
        self.stats_label.setText(
            f"Материалов: {s['materials']}  ·  Кромка: {s['edges']}  ·  "
            f"Крепёж: {s['fasteners']}  ·  Поставщиков: {s['suppliers']}"
        )
        self.path_label.setText(str(s.get("db_path", "")))

    def _reload_all(self) -> None:
        self._reload_materials()
        self._reload_edges()
        self._reload_fasteners()

    # ── Назначение материала на панель ────────────────────────

    def _selected_material_id(self) -> str:
        """id выбранного материала на вкладке Материалы (или пустая строка)."""
        if self.tabs.currentIndex() != 0:
            return ""
        items = self.mat_table.selectedItems()
        if not items:
            return ""
        mid = self.mat_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return mid or ""

    def _selected_edge_id(self) -> str:
        """id выбранной кромки на вкладке Кромка (или пустая строка)."""
        if self.tabs.currentIndex() != 1:
            return ""
        items = self.edge_table.selectedItems()
        if not items:
            return ""
        eid = self.edge_table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return eid or ""

    def _update_assign_button(self) -> None:
        idx = self.tabs.currentIndex()
        has_target = bool(self._target_panel_name)
        if idx == 0:
            mid = self._selected_material_id()
            self.assign_btn.setEnabled(bool(mid) and has_target)
            if not has_target:
                self.assign_btn.setText("Назначить материал на выделенную деталь")
                self.assign_btn.setToolTip("Сначала выделите деталь в сцене")
            elif mid:
                name = mid
                if self._catalog:
                    m = self._catalog.get_material(mid)
                    if m:
                        name = m.display_name
                self.assign_btn.setText(f"Назначить «{name}» → {self._target_panel_name}")
                self.assign_btn.setToolTip(f"Применить материал к панели «{self._target_panel_name}»")
            else:
                self.assign_btn.setText("Назначить материал на деталь")
                self.assign_btn.setToolTip("Выберите материал в таблице")
        elif idx == 1:
            eid = self._selected_edge_id()
            self.assign_btn.setEnabled(bool(eid) and has_target)
            if not has_target:
                self.assign_btn.setText("Нанести кромку на выделенную деталь")
                self.assign_btn.setToolTip("Сначала выделите деталь в сцене")
            elif eid:
                name = eid
                if self._catalog:
                    e = self._catalog.get_edge(eid)
                    if e:
                        name = e.display_name
                self.assign_btn.setText(f"Нанести «{name}» на 4 стороны → {self._target_panel_name}")
                self.assign_btn.setToolTip(f"Облицевать 4 торца детали «{self._target_panel_name}»")
            else:
                self.assign_btn.setText("Нанести кромку на деталь")
                self.assign_btn.setToolTip("Выберите кромку в таблице")
        else:
            self.assign_btn.setEnabled(False)
            self.assign_btn.setText("Справочник крепежа (установка: Ctrl+H на стыке)")
            self.assign_btn.setToolTip("Для расстановки крепежа используйте инструмент на стыке двух деталей")

    def _on_tab_changed(self, _index: int) -> None:
        self._update_assign_button()
        self._update_material_action_buttons()
        self._update_edge_action_buttons()

    def _on_assign_clicked(self) -> None:
        idx = self.tabs.currentIndex()
        if idx == 0:
            mid = self._selected_material_id()
            if not mid:
                return
            self.material_assign_requested.emit(mid)
        elif idx == 1:
            eid = self._selected_edge_id()
            if not eid:
                return
            self.edge_assign_requested.emit(eid, "all")

    def _on_material_double_clicked(self, _index) -> None:
        """Двойной клик по материалу — то же, что кнопка «Назначить»."""
        if self.assign_btn.isEnabled() and self.tabs.currentIndex() == 0:
            self._on_assign_clicked()

    def _on_edge_double_clicked(self, _index) -> None:
        """Двойной клик по кромке — облицовка всех 4 сторон."""
        if self.assign_btn.isEnabled() and self.tabs.currentIndex() == 1:
            self._on_assign_clicked()

    def _update_edge_action_buttons(self) -> None:
        """Активность кнопок Изменить / Удалить и Назначить для кромки."""
        eid = self._selected_edge_id()
        has = bool(eid)
        if hasattr(self, "edit_edge_btn"):
            self.edit_edge_btn.setEnabled(has)
        if hasattr(self, "del_edge_btn"):
            self.del_edge_btn.setEnabled(has)
        has_target = bool(self._target_panel_name)
        can_assign = has and has_target
        if hasattr(self, "btn_edge_all"):
            self.btn_edge_all.setEnabled(can_assign)
            if can_assign:
                self.btn_edge_all.setText(f"🔲 На все 4 стороны → {self._target_panel_name}")
            else:
                self.btn_edge_all.setText("🔲 На все 4 стороны")
        if hasattr(self, "btn_edge_side"):
            self.btn_edge_side.setEnabled(can_assign)

    def _save_edge_to_catalog(self, edge) -> bool:
        """Insert или update кромки в базе SQLite."""
        if not self._catalog:
            return False
        try:
            existing = self._catalog.get_edge(edge.id)
            if existing is not None:
                self._catalog.update_edge(edge)
            else:
                self._catalog.insert_edge(edge)
            self._catalog.commit()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Кромка", f"Не удалось сохранить:\n{e}")
            return False

    def _select_edge_row(self, edge_id: str) -> None:
        for row in range(self.edge_table.rowCount()):
            item = self.edge_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == edge_id:
                self.edge_table.selectRow(row)
                self.edge_table.scrollToItem(item)
                break

    def _on_add_edge(self) -> None:
        """Создание новой кромки в БД."""
        from ui.edge_dialog import EdgeBandEditDialog

        dlg = EdgeBandEditDialog(self)
        if not dlg.exec():
            return
        edge = dlg.get_edge_band()
        if edge is None:
            return
        if not self._save_edge_to_catalog(edge):
            return
        self._reload_edges()
        self._refresh_stats()
        self._select_edge_row(edge.id)
        QMessageBox.information(
            self, "Кромка",
            f"Кромка «{edge.display_name}» сохранена в каталог.",
        )

    def _on_edit_edge(self) -> None:
        """Редактирование кромки."""
        from ui.edge_dialog import EdgeBandEditDialog

        eid = self._selected_edge_id()
        if not eid or not self._catalog:
            return
        existing = self._catalog.get_edge(eid)
        if existing is None:
            QMessageBox.warning(self, "Кромка", "Кромка не найдена в каталоге.")
            return

        dlg = EdgeBandEditDialog(self, edge=existing)
        if not dlg.exec():
            return
        edge = dlg.get_edge_band()
        if edge is None:
            return
        if not self._save_edge_to_catalog(edge):
            return
        self._reload_edges()
        self._refresh_stats()
        self._select_edge_row(edge.id)
        QMessageBox.information(
            self, "Кромка",
            f"Кромка «{edge.display_name}» обновлена в каталоге.",
        )

    def _on_delete_edge(self) -> None:
        """Удаление кромки с подтверждением."""
        eid = self._selected_edge_id()
        if not eid or not self._catalog:
            return
        e = self._catalog.get_edge(eid)
        if e is None:
            return

        if e.is_builtin:
            text = (
                f"«{e.display_name}» — встроенная кромка.\n\n"
                "Удалить её из локального каталога?\n"
                "(При сбросе БД она может быть повторно инициализирована.)"
            )
        else:
            text = f"Удалить кромку «{e.display_name}» из каталога?"

        reply = QMessageBox.question(
            self, "Удаление кромки",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            ok = self._catalog.delete_edge(eid)
            self._catalog.commit()
            if not ok:
                QMessageBox.warning(self, "Кромка", "Запись не найдена.")
                return
        except Exception as ex:
            QMessageBox.critical(self, "Кромка", f"Не удалось удалить:\n{ex}")
            return

        self._reload_edges()
        self._refresh_stats()
        self._clear_form(self.edge_detail_form)
        self._update_edge_action_buttons()
        self._update_assign_button()
        QMessageBox.information(
            self, "Кромка",
            f"Кромка «{e.display_name}» удалена.",
        )

    def _on_assign_edge_all(self) -> None:
        """Назначение выбранной кромки на все 4 стороны."""
        eid = self._selected_edge_id()
        if not eid:
            return
        self.edge_assign_requested.emit(eid, "all")

    def _on_assign_edge_side(self) -> None:
        """Назначение кромки на выбранный торец."""
        eid = self._selected_edge_id()
        if not eid:
            return
        side = self.edge_side_combo.currentData() or "top"
        self.edge_assign_requested.emit(eid, side)

    def _update_material_action_buttons(self) -> None:
        """Активность кнопок Изменить / Удалить по выбранной строке."""
        mid = self._selected_material_id()
        has = bool(mid)
        self.edit_mat_btn.setEnabled(has)
        self.del_mat_btn.setEnabled(has)
        if has and self._catalog:
            m = self._catalog.get_material(mid)
            if m and m.is_builtin:
                self.del_mat_btn.setToolTip(
                    "Встроенный материал: удаление с подтверждением "
                    "(при следующем сбросе БД он может появиться снова из seed)"
                )
            else:
                self.del_mat_btn.setToolTip("Удалить выбранный материал из каталога")

    def _save_material_to_catalog(self, mat) -> bool:
        """Insert или update + commit. True при успехе."""
        if not self._catalog:
            return False
        try:
            existing = self._catalog.get_material(mat.id)
            if existing is not None:
                self._catalog.update_material(mat)
            else:
                self._catalog.insert_material(mat)
            self._catalog.commit()
            # cache updated by service
            return True
        except Exception as e:
            QMessageBox.critical(self, "Материал", f"Не удалось сохранить:\n{e}")
            return False

    def _select_material_row(self, material_id: str) -> None:
        for row in range(self.mat_table.rowCount()):
            item = self.mat_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == material_id:
                self.mat_table.selectRow(row)
                self.mat_table.scrollToItem(item)
                break

    # ══════════════════════════════════════════════════════════
    #  Дерево групп
    # ══════════════════════════════════════════════════════════

    def _reload_group_tree(self) -> None:
        self.group_tree.blockSignals(True)
        self.group_tree.clear()
        if not self._catalog:
            self.group_tree.addTopLevelItem(QTreeWidgetItem(["⚠ Каталог недоступен"]))
            self.group_tree.blockSignals(False)
            return
        try:
            if hasattr(self._catalog, "ensure_default_groups"):
                self._catalog.ensure_default_groups()
            groups = self._catalog.list_groups()
        except Exception as e:
            self.group_tree.addTopLevelItem(QTreeWidgetItem([f"⚠ Ошибка: {e}"]))
            self.group_tree.blockSignals(False)
            return

        by_parent: dict = {}
        for g in groups:
            by_parent.setdefault(g.parent_id, []).append(g)

        mat_counts: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        fst_counts: dict[str, int] = {}
        try:
            for m in self._catalog.list_materials(active_only=True):
                if m.group_id:
                    mat_counts[m.group_id] = mat_counts.get(m.group_id, 0) + 1
            for e in self._catalog.list_edges(active_only=True):
                if getattr(e, "group_id", None):
                    edge_counts[e.group_id] = edge_counts.get(e.group_id, 0) + 1
            for f in self._catalog.list_fasteners(active_only=True):
                if getattr(f, "group_id", None):
                    fst_counts[f.group_id] = fst_counts.get(f.group_id, 0) + 1
        except Exception:
            _log.exception("Не удалось подсчитать позиции каталога по группам")

        def count_for(g) -> int:
            ids = self._catalog.descendant_group_ids(g.id)
            if g.scope == "edge":
                return sum(edge_counts.get(i, 0) for i in ids)
            if g.scope == "fastener":
                return sum(fst_counts.get(i, 0) for i in ids)
            return sum(mat_counts.get(i, 0) for i in ids)

        def add_children(parent_item, parent_id):
            for g in sorted(by_parent.get(parent_id, []), key=lambda x: (x.sort_order, x.name)):
                icon = {"material": "📄", "edge": "📏", "fastener": "🔩"}.get(g.scope, "📁")
                n = count_for(g)
                label = f"{icon} {g.name}" + (f"  ({n})" if n else "")
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, g.id)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, g.scope)
                item.setToolTip(0, f"{g.name} · {g.scope}")
                if parent_item is None:
                    self.group_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                add_children(item, g.id)

        root = QTreeWidgetItem(["📚 Все позиции"])
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        root.setData(0, Qt.ItemDataRole.UserRole + 1, "all")
        self.group_tree.addTopLevelItem(root)
        add_children(None, None)
        if not groups:
            self.group_tree.addTopLevelItem(
                QTreeWidgetItem(["(групп нет — нажмите «+ Группа»)"])
            )
        self.group_tree.expandAll()
        root.setSelected(True)
        self.group_tree.blockSignals(False)

    def _selected_group(self):
        items = self.group_tree.selectedItems()
        if not items:
            return None, "all"
        gid = items[0].data(0, Qt.ItemDataRole.UserRole)
        scope = items[0].data(0, Qt.ItemDataRole.UserRole + 1) or "all"
        return gid, scope

    def _on_group_selected(self) -> None:
        gid, scope = self._selected_group()
        self._filter_scope = scope or "all"
        if gid is None:
            self._filter_group_ids = None
        else:
            self._filter_group_ids = (
                self._catalog.descendant_group_ids(gid) if self._catalog else [gid]
            )
        if scope == "material":
            self.tabs.setCurrentIndex(0)
        elif scope == "edge":
            self.tabs.setCurrentIndex(1)
        elif scope == "fastener":
            self.tabs.setCurrentIndex(2)
        self._reload_materials()
        self._reload_edges()
        self._reload_fasteners()
        self._update_group_action_buttons()

    def _update_group_action_buttons(self) -> None:
        gid, _ = self._selected_group()
        has = gid is not None
        self.btn_add_subgroup.setEnabled(has)
        self.btn_rename_group.setEnabled(has)
        self.btn_del_group.setEnabled(has)

    def _on_add_group(self, as_child: bool = False) -> None:
        if not self._catalog:
            return
        from core.catalog.models import CatalogGroup
        import uuid

        parent_id = None
        scope = "material"
        if as_child:
            gid, scope = self._selected_group()
            if gid is None:
                QMessageBox.information(self, "Группа", "Выберите родительскую группу.")
                return
            parent_id = gid
            parent = self._catalog.get_group(gid)
            if parent:
                scope = parent.scope

        name, ok = QInputDialog.getText(
            self, "Новая группа",
            "Название группы:" if not as_child else "Название подгруппы:",
        )
        if not ok or not name.strip():
            return

        if not as_child:
            scopes = [
                ("Листовые материалы", "material"),
                ("Кромочные материалы", "edge"),
                ("Фурнитура", "fastener"),
                ("Смешанная", "all"),
            ]
            labels = [s[0] for s in scopes]
            label, ok2 = QInputDialog.getItem(
                self, "Тип группы", "Раздел:", labels, 0, False
            )
            if not ok2:
                return
            scope = dict(scopes).get(label, "all")

        new_id = f"grp_{uuid.uuid4().hex[:10]}"
        siblings = [g for g in self._catalog.list_groups() if g.parent_id == parent_id]
        sort_order = max((g.sort_order for g in siblings), default=0) + 10
        g = CatalogGroup(
            id=new_id, name=name.strip(), parent_id=parent_id,
            sort_order=sort_order, scope=scope, is_builtin=False,
        )
        try:
            self._catalog.insert_group(g)
        except Exception as e:
            QMessageBox.critical(self, "Группа", f"Не удалось создать:\n{e}")
            return
        self._reload_group_tree()
        self._refresh_stats()

    def _on_rename_group(self) -> None:
        if not self._catalog:
            return
        gid, _ = self._selected_group()
        if not gid:
            return
        g = self._catalog.get_group(gid)
        if not g:
            return
        name, ok = QInputDialog.getText(
            self, "Переименовать", "Новое название:", text=g.name
        )
        if not ok or not name.strip() or name.strip() == g.name:
            return
        g.name = name.strip()
        try:
            self._catalog.update_group(g)
        except Exception as e:
            QMessageBox.critical(self, "Группа", f"Не удалось переименовать:\n{e}")
            return
        self._reload_group_tree()

    def _on_delete_group(self) -> None:
        if not self._catalog:
            return
        gid, _ = self._selected_group()
        if not gid:
            return
        g = self._catalog.get_group(gid)
        if not g:
            return
        reply = QMessageBox.question(
            self, "Удаление группы",
            f"Удалить группу «{g.name}» и все её подгруппы?\n"
            "Элементы каталога останутся без привязки к группе.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._catalog.delete_group(gid)
        except Exception as e:
            QMessageBox.critical(self, "Группа", f"Не удалось удалить:\n{e}")
            return
        self._filter_group_ids = None
        self._filter_scope = "all"
        self._reload_group_tree()
        self._reload_all()
        self._refresh_stats()

    def _on_group_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_add = QAction("Добавить группу", self)
        act_add.triggered.connect(lambda: self._on_add_group(as_child=False))
        menu.addAction(act_add)
        act_sub = QAction("Добавить подгруппу", self)
        act_sub.triggered.connect(lambda: self._on_add_group(as_child=True))
        menu.addAction(act_sub)
        menu.addSeparator()
        act_ren = QAction("Переименовать", self)
        act_ren.triggered.connect(self._on_rename_group)
        menu.addAction(act_ren)
        act_del = QAction("Удалить", self)
        act_del.triggered.connect(self._on_delete_group)
        menu.addAction(act_del)
        menu.exec(self.group_tree.viewport().mapToGlobal(pos))

    def _on_add_material(self) -> None:
        """Открывает форму создания материала и сохраняет в каталог."""
        from ui.material_dialog import MaterialEditDialog

        dlg = MaterialEditDialog(self)
        if not dlg.exec():
            return
        mat = dlg.get_material()
        if mat is None:
            return
        gid, scope = self._selected_group()
        if gid and scope in ("material", "all"):
            mat.group_id = gid
        if not self._save_material_to_catalog(mat):
            return
        self._reload_materials()
        self._reload_group_tree()
        self._refresh_stats()
        self._select_material_row(mat.id)
        QMessageBox.information(
            self, "Материал",
            f"Материал «{mat.display_name}» сохранён в каталог.",
        )

    def _on_edit_material(self) -> None:
        """Редактирование выбранного материала."""
        from ui.material_dialog import MaterialEditDialog

        mid = self._selected_material_id()
        if not mid or not self._catalog:
            return
        existing = self._catalog.get_material(mid)
        if existing is None:
            QMessageBox.warning(self, "Материал", "Материал не найден.")
            return

        dlg = MaterialEditDialog(self, material=existing)
        if not dlg.exec():
            return
        mat = dlg.get_material()
        if mat is None:
            return
        if not self._save_material_to_catalog(mat):
            return
        self._reload_materials()
        self._refresh_stats()
        self._select_material_row(mat.id)
        self.statusBar_message = f"Материал «{mat.display_name}» обновлён"
        # Нет statusBar у диалога — краткое уведомление
        QMessageBox.information(
            self, "Материал",
            f"Материал «{mat.display_name}» обновлён.",
        )

    def _on_delete_material(self) -> None:
        """Удаление выбранного материала с подтверждением."""
        mid = self._selected_material_id()
        if not mid or not self._catalog:
            return
        m = self._catalog.get_material(mid)
        if m is None:
            return

        if m.is_builtin:
            text = (
                f"«{m.display_name}» — встроенный материал.\n\n"
                "Удалить его из локального каталога?\n"
                "(При полной пересборке БД seed может вернуть его обратно.)"
            )
        else:
            text = f"Удалить материал «{m.display_name}» из каталога?"

        reply = QMessageBox.question(
            self, "Удаление материала",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            ok = self._catalog.delete_material(mid)
            self._catalog.commit()
            # cache updated by service
            if not ok:
                QMessageBox.warning(self, "Материал", "Запись не найдена.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Материал", f"Не удалось удалить:\n{e}")
            return

        self._reload_materials()
        self._refresh_stats()
        self._clear_form(self.mat_detail_form)
        self._update_material_action_buttons()
        self._update_assign_button()
        QMessageBox.information(
            self, "Материал",
            f"Материал «{m.display_name}» удалён.",
        )
