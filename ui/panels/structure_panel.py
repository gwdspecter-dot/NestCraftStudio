from PyQt6.QtWidgets import QDockWidget, QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from models.panel import Block, Panel


class StructureDock(QDockWidget):
    # Сигнал, передающий выбранный объект (Panel, Block или None)
    object_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__("Структура модели", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Элемент", "П...", "Обозначение"])
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 35)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        self.setWidget(self.tree)
        self.blocks_ref: list[Block] = []

    def load_structure(self, model_name: str, blocks: list[Block]):
        """Заполняет дерево реальными блоками и панелями из 3D-сцены"""
        self.blocks_ref = blocks
        self.tree.blockSignals(True)  # <-- Блокируем лишние сигналы при перестройке
        self.tree.clear()

        root = QTreeWidgetItem(self.tree, [model_name, "", "00.00"])
        root.setData(0, Qt.ItemDataRole.UserRole, None)

        for block in blocks:
            b_item = QTreeWidgetItem(root, [f"📦 {block.name}", block.pos_num, block.code])
            b_item.setData(0, Qt.ItemDataRole.UserRole, block)

            for panel in block.panels:
                p_item = QTreeWidgetItem(b_item, [f"📄 {panel.name}", panel.pos_num, panel.code])
                p_item.setData(0, Qt.ItemDataRole.UserRole, panel)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    def highlight_object(self, obj):
        """Подсвечивает объект в дереве без эмита object_selected (синхронизация из 3D)."""
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        if obj is None:
            self.tree.blockSignals(False)
            return
        root = self.tree.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) is obj:
                item.setSelected(True)
                self.tree.scrollToItem(item)
                break
            for i in range(item.childCount()):
                stack.append(item.child(i))
        self.tree.blockSignals(False)

    def _on_selection_changed(self):
        # Сбрасываем старое выделение со всех объектов
        for b in self.blocks_ref:
            b.selected = False
            for p in b.panels:
                p.selected = False

        selected_items = self.tree.selectedItems()
        if not selected_items:
            self.object_selected.emit(None)
            return

        obj = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(obj, (Panel, Block)):
            obj.selected = True

        self.object_selected.emit(obj)