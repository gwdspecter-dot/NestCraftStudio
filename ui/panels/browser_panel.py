from PyQt6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal


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
        self.folder_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        # Папка кухонных модулей с рабочими шаблонами
        kuh_root = QTreeWidgetItem(self.folder_tree, ["📁 #_Библиотека кухонь"])
        templates = [
            ("➕ Тумба нижняя 600 (1 полка)", "base_600"),
            ("➕ Тумба нижняя 800 (2 полки)", "base_800"),
            ("➕ Шкаф верхний 600 (2 полки)", "upper_600"),
            ("➕ Пенал высокий 600x2140 (4 полки)", "tall_600"),
        ]
        for title, code in templates:
            item = QTreeWidgetItem(kuh_root, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, code)

        # Остальные папки каталога
        other_folders = [
            "#_Библиотека шкафов", "#_Системы открывания",
            "AKS", "Antarion", "AQ", "Boyard", "DTC"
        ]
        for folder in other_folders:
            QTreeWidgetItem(self.folder_tree, [f"📁 {folder}"])

        kuh_root.setExpanded(True)
        layout.addWidget(self.folder_tree)
        self.setWidget(container)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        code = item.data(0, Qt.ItemDataRole.UserRole)
        if code:
            self.template_double_clicked.emit(code)