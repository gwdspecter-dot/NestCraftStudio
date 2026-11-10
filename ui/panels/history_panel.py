from PyQt6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import pyqtSignal, Qt


class AnalysisDock(QDockWidget):
    run_analysis_requested = pyqtSignal()
    issue_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Проблемы", parent)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self.btn_check = QPushButton("🔍 Проверить модель (Проблемы и пересечения 3D)")
        self.btn_check.clicked.connect(self.run_analysis_requested.emit)
        layout.addWidget(self.btn_check)

        self.list_widget = QListWidget()
        self.list_widget.addItem("Готово к проверке через ядро OpenCASCADE (B-Rep)")
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

        self.setWidget(container)

    def add_issue_item(self, text: str, panel_uid: str = "", code: str = "", severity: str = "warning") -> QListWidgetItem:
        item = QListWidgetItem(text)
        if panel_uid:
            item.setData(Qt.ItemDataRole.UserRole, str(panel_uid))
        if code:
            item.setData(Qt.ItemDataRole.UserRole + 1, str(code))
        if severity:
            item.setData(Qt.ItemDataRole.UserRole + 2, str(severity))
        self.list_widget.addItem(item)
        return item

    def set_issues(self, issues: list, *, empty_message: str = "✅ Ошибок нет! Замечаний и пересечений деталей не обнаружено.") -> None:
        """Заполняет единый список замечаний списком объектов Issue."""
        self.list_widget.clear()
        if not issues:
            self.setWindowTitle("Проблемы")
            if empty_message:
                self.list_widget.addItem(empty_message)
            return
        self.setWindowTitle(f"Проблемы ({len(issues)})")
        for iss in issues:
            line = iss.format_line() if hasattr(iss, "format_line") else str(iss)
            puid = str(getattr(iss, "panel_uid", "") or "")
            code = str(getattr(iss, "code", "") or "")
            sev = str(getattr(iss, "severity", "warning") or "warning")
            self.add_issue_item(line, panel_uid=puid, code=code, severity=sev)

    def activate_row(self, row: int) -> bool:
        """Активирует строку по индексу (как двойной клик) и испускает issue_activated(uid)."""
        item = self.list_widget.item(row)
        if item is None:
            return False
        self._on_item_double_clicked(item)
        return bool(item.data(Qt.ItemDataRole.UserRole))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        uid = item.data(Qt.ItemDataRole.UserRole)
        if uid:
            self.issue_activated.emit(str(uid))


class HistoryDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("История", parent)
        self.list_widget = QListWidget()
        self.list_widget.addItem("Стек отмены пуст — действия появятся здесь")
        self.setWidget(self.list_widget)

    def set_history(self, labels: list[str]):
        """Обновляет список из UndoStack (старые → новые)."""
        self.list_widget.clear()
        if not labels:
            self.list_widget.addItem("Стек отмены пуст")
            return
        for text in labels:
            self.list_widget.addItem(text)
        self.list_widget.scrollToBottom()
