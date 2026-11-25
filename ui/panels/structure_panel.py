"""Док-панель «Структура модели»: плоские детали, блоки, стыки, одиночная фурнитура и ассоциации."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)

from core.assoc import AssocRef
from core.joint import JointRecord, get_fastener_preset, get_joint_fastener_items
from core.logging_setup import get_logger
from models.panel import Block, Panel
from ui.theme import current_theme

_log = get_logger("structure_panel")
_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"

_ICON_FILES: dict[str, str] = {
    "block": "struct_block.svg",
    "panel": "struct_panel.svg",
    "joint": "struct_joint.svg",
    "fastener": "struct_fastener.svg",
    "assoc": "struct_assoc.svg",
}


def _render_tinted_svg_icon(svg_path: Path, color_hex: str, size: int = 16) -> QIcon:
    """Рендерит SVG-иконку с заменой ``currentColor`` на цвет текущей темы (HiDPI)."""
    if not svg_path.is_file():
        return QIcon()
    try:
        raw = svg_path.read_text(encoding="utf-8")
        tinted = raw.replace("currentColor", color_hex).encode("utf-8")
        renderer = QSvgRenderer(QByteArray(tinted))
        if not renderer.isValid():
            return QIcon(str(svg_path))
        dpr = 2.0
        px = int(size * dpr)
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
        painter.end()
        return QIcon(pm)
    except Exception:
        _log.exception("Не удалось отрендерить SVG-иконку %s", svg_path)
        return QIcon(str(svg_path))


class StructureDock(QDockWidget):
    """Дерево «Структура модели».

    - Свободные детали (из корневого контейнера ``is_root=True``) лежат напрямую в корне изделия.
    - Пользовательские блоки (``is_root=False``) создаются явно через ПКМ → «Создать блок…».
    - Стыки отображаются как узлы-контейнеры (без позиций!) с дочерними элементами одиночной фурнитуры.
    - Ассоциативные отверстия отображаются как листовые элементы (без позиций!).
    """

    # Сигнал, передающий выбранный объект (Panel, Block или None)
    object_selected = pyqtSignal(object)
    # Выбор стыка или одиночной фурнитуры внутри стыка: (owner_block, joint_uid)
    joint_selected = pyqtSignal(object, str)
    # Выбор ассоциативного отверстия: (owner_block, assoc_uid)
    assoc_selected = pyqtSignal(object, str)
    # Запрос создания нового блока из выделенных панелей: list[Panel]
    create_block_requested = pyqtSignal(list)
    # Множественное выделение панелей в дереве (синхронизация с 3D)
    multi_panels_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__("Структура модели", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Элемент", "П...", "Обозначение"])
        self.tree.setColumnWidth(0, 195)
        self.tree.setColumnWidth(1, 38)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        self.setWidget(self.tree)
        self.blocks_ref: list[Block] = []
        self._last_model_name: str = ""
        self._last_order_number: str = ""
        self._icons: dict[str, QIcon] = {}
        self._rebuild_icons()

    def _rebuild_icons(self) -> None:
        t = current_theme()
        colors = {
            "block": t.accent,
            "panel": t.text,
            "joint": t.warning,
            "fastener": t.text_dim,
            "assoc": t.accent,
        }
        self._icons = {
            key: _render_tinted_svg_icon(_ICONS_DIR / fname, colors[key], size=16)
            for key, fname in _ICON_FILES.items()
        }

    def refresh_theme(self) -> None:
        """Перестраивает иконки дерева под текущую светлую/тёмную тему."""
        self._rebuild_icons()
        if self._last_model_name or self.blocks_ref:
            self.load_structure(
                self._last_model_name,
                self.blocks_ref,
                order_number=self._last_order_number,
            )

    def load_structure(self, model_name: str, blocks: list[Block], order_number: str = "") -> None:
        """Заполняет дерево панелями, блоками, стыками, одиночной фурнитурой и ассоциациями."""
        self.blocks_ref = blocks
        self._last_model_name = str(model_name or "")
        self._last_order_number = str(order_number or "")

        self.tree.blockSignals(True)
        try:
            self.tree.clear()

            root_code = str(order_number or "").strip() or "00.00"
            root = QTreeWidgetItem(self.tree, [model_name, "", root_code])
            root.setData(0, Qt.ItemDataRole.UserRole, None)

            panel_by_uid: dict[str, Panel] = {}
            panel_to_block: dict[str, Block] = {}
            for block in blocks:
                for panel in getattr(block, "panels", []) or []:
                    puid = str(getattr(panel, "uid", "") or "")
                    if puid:
                        panel_by_uid[puid] = panel
                        panel_to_block[puid] = block

            block_tree_items: dict[int, QTreeWidgetItem] = {}

            # 1. Свободные панели (из корневого контейнера is_root=True) — напрямую в корне
            for block in blocks:
                if not getattr(block, "is_root", False):
                    continue
                for panel in getattr(block, "panels", []) or []:
                    p_item = QTreeWidgetItem(root, [panel.name, "", panel.code])
                    p_item.setIcon(0, self._icons["panel"])
                    p_item.setData(0, Qt.ItemDataRole.UserRole, panel)

            # 2. Пользовательские блоки (is_root=False) и их панели
            for block in blocks:
                if getattr(block, "is_root", False):
                    continue
                is_asm = bool(getattr(block, "is_assembly", True))
                b_pos = str(getattr(block, "pos_num", "") or "") if is_asm else ""
                b_item = QTreeWidgetItem(root, [block.name, b_pos, block.code])
                b_item.setIcon(0, self._icons["block"])
                b_item.setData(0, Qt.ItemDataRole.UserRole, block)
                block_tree_items[id(block)] = b_item

                for panel in getattr(block, "panels", []) or []:
                    p_pos = str(getattr(panel, "pos_num", "") or "") if is_asm else ""
                    p_item = QTreeWidgetItem(b_item, [panel.name, p_pos, panel.code])
                    p_item.setIcon(0, self._icons["panel"])
                    p_item.setData(0, Qt.ItemDataRole.UserRole, panel)

            # 3. Стыки (блок-узлы без позиций) и их дочерняя одиночная фурнитура (без позиций)
            for block in blocks:
                for raw_jr in getattr(block, "joints", None) or []:
                    jr = raw_jr if isinstance(raw_jr, JointRecord) else JointRecord.from_dict(raw_jr)
                    pa_uid = str(getattr(jr, "panel_a_uid", "") or "")
                    pb_uid = str(getattr(jr, "panel_b_uid", "") or "")
                    pa = panel_by_uid.get(pa_uid)
                    pb = panel_by_uid.get(pb_uid)
                    blk_a = panel_to_block.get(pa_uid)
                    blk_b = panel_to_block.get(pb_uid)

                    if (
                        blk_a is not None
                        and blk_a is blk_b
                        and id(blk_a) in block_tree_items
                    ):
                        parent_item = block_tree_items[id(blk_a)]
                    else:
                        parent_item = root

                    name_a = getattr(pa, "name", pa_uid[:8] or "?") if pa is not None else (pa_uid[:8] or "?")
                    name_b = getattr(pb, "name", pb_uid[:8] or "?") if pb is not None else (pb_uid[:8] or "?")
                    preset = get_fastener_preset(jr.preset_id)
                    preset_lbl = (
                        str(preset.get("label", jr.preset_id))
                        if preset
                        else (jr.preset_id or "Крепёж")
                    )
                    j_label = f"Стык: {name_a} ↔ {name_b}"
                    j_item = QTreeWidgetItem(parent_item, [j_label, "", ""])
                    j_item.setIcon(0, self._icons["joint"])
                    j_item.setToolTip(0, f"{j_label} ({preset_lbl})")
                    j_item.setData(0, Qt.ItemDataRole.UserRole, ("joint", block, jr.uid))

                    for f_info in get_joint_fastener_items(jr, blocks):
                        f_item = QTreeWidgetItem(j_item, [str(f_info["name"]), "", ""])
                        f_item.setIcon(0, self._icons["fastener"])
                        f_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            ("fastener", block, jr.uid, int(f_info["index"])),
                        )

            # 4. Ассоциативные отверстия (листовые элементы без позиций)
            for block in blocks:
                for raw_ref in getattr(block, "assoc_refs", None) or []:
                    ref = raw_ref if isinstance(raw_ref, AssocRef) else AssocRef.from_dict(raw_ref)
                    tgt_uid = str(ref.target_uid or "")
                    src_uid = str(ref.source_uid or "")
                    tgt = panel_by_uid.get(tgt_uid)
                    src = panel_by_uid.get(src_uid)
                    tgt_blk = panel_to_block.get(tgt_uid)
                    if tgt_blk is not None and id(tgt_blk) in block_tree_items:
                        parent_item = block_tree_items[id(tgt_blk)]
                    else:
                        parent_item = root

                    tgt_name = getattr(tgt, "name", tgt_uid[:8] or "?") if tgt is not None else (tgt_uid[:8] or "?")
                    src_name = getattr(src, "name", src_uid[:8] or "?") if src is not None else (src_uid[:8] or "?")
                    dia = float(ref.params.get("diameter") or 0.0)
                    dep = float(ref.params.get("depth") or 0.0)
                    if ref.fixed:
                        a_label = f"Ассоциация: {tgt_name} [фикс.]"
                    else:
                        a_label = f"Ассоциация: {tgt_name} ← {src_name}.{ref.source_face}"
                    size_txt = f"Ø{dia:g}×{dep:g}" if dia > 0 and dep > 0 else (f"Ø{dia:g}" if dia > 0 else "")
                    a_item = QTreeWidgetItem(parent_item, [a_label, "", size_txt])
                    a_item.setIcon(0, self._icons["assoc"])
                    a_item.setData(0, Qt.ItemDataRole.UserRole, ("assoc", block, ref.uid))

            self.tree.expandAll()
        finally:
            self.tree.blockSignals(False)

    def _iter_tree_items(self):
        root = self.tree.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            item = stack.pop(0)
            yield item
            for i in range(item.childCount()):
                stack.append(item.child(i))

    def highlight_object(self, obj) -> None:
        """Подсвечивает панель или блок в дереве без эмита сигналов (синхронизация из 3D)."""
        self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            if obj is None:
                return
            for item in self._iter_tree_items():
                if item.data(0, Qt.ItemDataRole.UserRole) is obj:
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
                    break
        finally:
            self.tree.blockSignals(False)

    def highlight_joint(self, joint_uid: str) -> None:
        """Подсвечивает стык в дереве по его ``uid`` без эмита сигналов."""
        target = str(joint_uid or "").strip()
        if not target:
            return
        self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            for item in self._iter_tree_items():
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, tuple) and len(data) >= 3 and data[0] == "joint" and str(data[2]) == target:
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
                    break
        finally:
            self.tree.blockSignals(False)

    def highlight_assoc(self, assoc_uid: str) -> None:
        """Подсвечивает ассоциацию в дереве по её ``uid`` без эмита сигналов."""
        target = str(assoc_uid or "").strip()
        if not target:
            return
        self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            for item in self._iter_tree_items():
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, tuple) and len(data) >= 3 and data[0] == "assoc" and str(data[2]) == target:
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
                    break
        finally:
            self.tree.blockSignals(False)

    def _collect_selected_panels(self) -> list[Panel]:
        """Собирает уникальные панели из текущего выделения в дереве."""
        panels: list[Panel] = []
        seen: set[int] = set()
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Panel):
                if id(data) not in seen:
                    seen.add(id(data))
                    panels.append(data)
            elif isinstance(data, Block) and not getattr(data, "is_root", False):
                for p in getattr(data, "panels", []) or []:
                    if id(p) not in seen:
                        seen.add(id(p))
                        panels.append(p)
        return panels

    def _on_context_menu(self, pos: QPoint) -> None:
        clicked = self.tree.itemAt(pos)
        if clicked is not None and not clicked.isSelected():
            self.tree.setCurrentItem(clicked)

        panels = self._collect_selected_panels()
        if not panels:
            return

        menu = QMenu(self)
        act_create_block = menu.addAction(self._icons["block"], "Создать блок…")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is act_create_block:
            self.create_block_requested.emit(panels)

    def _on_selection_changed(self) -> None:
        # Сбрасываем старое выделение со всех объектов
        for b in self.blocks_ref:
            b.selected = False
            for p in getattr(b, "panels", []) or []:
                p.selected = False

        selected_items = self.tree.selectedItems()
        if not selected_items:
            self.object_selected.emit(None)
            return

        if len(selected_items) == 1:
            data = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) >= 3:
                kind = data[0]
                owner_block = data[1]
                uid = str(data[2] or "")
                if kind in ("joint", "fastener") and owner_block is not None and uid:
                    self.joint_selected.emit(owner_block, uid)
                    return
                if kind == "assoc" and owner_block is not None and uid:
                    self.assoc_selected.emit(owner_block, uid)
                    return
            if isinstance(data, (Panel, Block)):
                data.selected = True
            self.object_selected.emit(data if isinstance(data, (Panel, Block)) else None)
            return

        # Множественное выделение (например, перед ПКМ → «Создать блок…»)
        selected_panels: list[Panel] = []
        first_obj = None
        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Panel):
                data.selected = True
                selected_panels.append(data)
                if first_obj is None:
                    first_obj = data
            elif isinstance(data, Block) and not getattr(data, "is_root", False):
                data.selected = True
                if first_obj is None:
                    first_obj = data

        if selected_panels:
            self.multi_panels_selected.emit(selected_panels)
        self.object_selected.emit(first_obj)