from PyQt6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from ui.icon_utils import render_svg_icon
from ui.theme import current_theme


class BrowserDock(QDockWidget):
    # Сигнал при двойном клике по шаблону в библиотеке
    template_double_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Обозреватель файлов", parent)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск фрагментов...")
        layout.addWidget(self.search_input)

        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setIconSize(QSize(16, 16))
        self.folder_tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._folder_items: list[QTreeWidgetItem] = []
        self._template_items: list[QTreeWidgetItem] = []

        # Папка кухонных модулей с рабочими шаблонами
        kuh_root = QTreeWidgetItem(self.folder_tree, ["#_Библиотека кухонь"])
        self._folder_items.append(kuh_root)
        templates = [
            ("Тумба нижняя 600 (1 полка)", "base_600"),
            ("Тумба нижняя 800 (2 полки)", "base_800"),
            ("Шкаф верхний 600 (2 полки)", "upper_600"),
            ("Пенал высокий 600x2140 (4 полки)", "tall_600"),
        ]
        for title, code in templates:
            item = QTreeWidgetItem(kuh_root, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, code)
            self._template_items.append(item)

        # Остальные папки каталога
        other_folders = [
            "#_Библиотека шкафов", "#_Системы открывания",
            "AKS", "Antarion", "AQ", "Boyard", "DTC"
        ]
        for folder in other_folders:
            f_item = QTreeWidgetItem(self.folder_tree, [folder])
            self._folder_items.append(f_item)

        self.refresh_theme()
        kuh_root.setExpanded(True)
        layout.addWidget(self.folder_tree)
        self.setWidget(container)

    def refresh_theme(self) -> None:
        c = current_theme()
        folder_ico = render_svg_icon("action_folder.svg", c.text, 16)
        add_ico = render_svg_icon("action_add.svg", c.accent, 15)
        for item in self._folder_items:
            if folder_ico is not None:
                item.setIcon(0, folder_ico)
        for item in self._template_items:
            if add_ico is not None:
                item.setIcon(0, add_ico)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        code = item.data(0, Qt.ItemDataRole.UserRole)
        if code:
            self.template_double_clicked.emit(code)