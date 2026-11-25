"""Домашняя страница NestCraft Studio (стартовый экран приложения).

Структура:
- Слева — раздел «Запуск»:
    1. Создать модель (заготовка под окно габаритной рамки)
    2. Открыть модель (диалог выбора файла проекта)
    3. Создать фурнитуру (заглушка)
    4. Создать модуль (заглушка)
- Справа — раздел «Последние файлы» со списком недавно открытых моделей
  в порядке открытия (последние открытые — сверху).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeyEvent, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.logging_setup import get_logger
from core.project_io import RecentFileEntry, build_recent_file_entries
from core.version import APP_VERSION
from ui.theme import current_theme

_log = get_logger("ui.home_page")
_ICONS_DIR = Path(__file__).resolve().parent / "icons"
_DPR_SCALE = 2

# Описания пунктов левого блока «Запуск» в точном порядке отображения.
HOME_LAUNCH_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "create_model",
        "Создать модель",
        "home_new_model.svg",
        "Создать новую модель изделия (скоро: окно габаритной рамки)",
    ),
    (
        "open_model",
        "Открыть модель",
        "home_open_model.svg",
        "Открыть существующий проект (.b3d, .json)",
    ),
    (
        "create_fastener",
        "Создать фурнитуру",
        "home_new_fastener.svg",
        "Создать фурнитуру (в разработке)",
    ),
    (
        "create_module",
        "Создать модуль",
        "home_new_module.svg",
        "Создать модуль (в разработке)",
    ),
)


def _render_themed_svg_icon(svg_path: Path, color_hex: str, size: int = 24) -> QIcon:
    """Рендерит SVG-иконку с подстановкой цвета текущей темы в HiDPI-качестве."""
    if not svg_path.is_file():
        return QIcon()
    try:
        raw = svg_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log.debug("Не удалось прочитать SVG-иконку %s: %s", svg_path, exc)
        return QIcon(str(svg_path))

    colored = raw.replace("currentColor", color_hex)
    renderer = QSvgRenderer(QByteArray(colored.encode("utf-8")))
    if not renderer.isValid():
        return QIcon(str(svg_path))

    px_size = max(1, int(size) * _DPR_SCALE)
    pm = QPixmap(px_size, px_size)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(float(_DPR_SCALE))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
    painter.end()
    return QIcon(pm)


class _RecentFileRowWidget(QWidget):
    """Строка одного недавнего файла: иконка, имя файла и путь каталога."""

    def __init__(self, entry: RecentFileEntry, icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        self._icon_lbl = QLabel(self)
        self._icon_lbl.setFixedSize(20, 20)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setPixmap(icon.pixmap(QSize(20, 20)))
        row.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._name_lbl = QLabel(entry.name, self)
        self._name_lbl.setObjectName("recentFileName")
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        text_col.addWidget(self._name_lbl)

        self._dir_lbl = QLabel(entry.directory, self)
        self._dir_lbl.setObjectName("recentFileDir")
        self._dir_lbl.setTextFormat(Qt.TextFormat.PlainText)
        text_col.addWidget(self._dir_lbl)

        row.addLayout(text_col, 1)

    def set_icon(self, icon: QIcon) -> None:
        self._icon_lbl.setPixmap(icon.pixmap(QSize(20, 20)))


class _RecentFilesList(QListWidget):
    """Список недавних файлов с открытием по Enter и без двойного срабатывания клика."""

    enter_pressed = pyqtSignal(QListWidgetItem)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.enter_pressed.emit(item)
                event.accept()
                return
        super().keyPressEvent(event)


class HomePage(QWidget):
    """Домашняя страница, отображаемая при запуске NestCraft Studio."""

    create_model_requested = pyqtSignal()
    open_model_requested = pyqtSignal()
    create_fastener_requested = pyqtSignal()
    create_module_requested = pyqtSignal()
    recent_file_requested = pyqtSignal(str)
    remove_recent_requested = pyqtSignal(str)
    clear_recent_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self._theme_name: str = ""
        self._recent_entries: list[RecentFileEntry] = []
        self._action_buttons: dict[str, QToolButton] = {}

        self._build_ui()
        self.refresh_theme()
        self.refresh_recent_files()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("homeScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._scroll)

        canvas = QWidget(self._scroll)
        canvas.setObjectName("homeCanvas")
        self._scroll.setWidget(canvas)

        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(32, 36, 32, 36)
        outer.setSpacing(0)
        outer.addStretch(1)

        container = QWidget(canvas)
        container.setObjectName("homeContainer")
        container.setMinimumWidth(680)
        container.setMaximumWidth(960)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(container, 10)
        outer.addStretch(1)

        main_col = QVBoxLayout(container)
        main_col.setContentsMargins(0, 0, 0, 0)
        main_col.setSpacing(24)

        # ── Шапка приложения ────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)

        logo_path = _ICONS_DIR / "logo.svg"
        if logo_path.is_file():
            logo_lbl = QLabel(container)
            logo_lbl.setFixedSize(44, 44)
            logo_lbl.setPixmap(QIcon(str(logo_path)).pixmap(QSize(44, 44)))
            header.addWidget(logo_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        app_title = QLabel("NestCraft Studio", container)
        app_title.setObjectName("homeAppTitle")
        title_col.addWidget(app_title)

        app_sub = QLabel(f"Проектирование корпусной мебели · версия {APP_VERSION}", container)
        app_sub.setObjectName("homeAppSubtitle")
        title_col.addWidget(app_sub)

        header.addLayout(title_col, 1)
        main_col.addLayout(header)

        divider = QFrame(container)
        divider.setObjectName("homeDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        main_col.addWidget(divider)

        # ── Двухколоночное содержимое ───────────────────────────────
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(44)

        # Левая колонка: «Запуск»
        left_widget = QWidget(container)
        left_widget.setMinimumWidth(260)
        left_widget.setMaximumWidth(340)
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)

        start_heading = QLabel("Запуск", left_widget)
        start_heading.setObjectName("homeSectionTitle")
        left_col.addWidget(start_heading)

        signal_map = {
            "create_model": self.create_model_requested,
            "open_model": self.open_model_requested,
            "create_fastener": self.create_fastener_requested,
            "create_module": self.create_module_requested,
        }

        for action_id, label, _icon_name, tooltip in HOME_LAUNCH_ACTIONS:
            btn = QToolButton(left_widget)
            btn.setObjectName("homeActionBtn")
            btn.setText(label)
            btn.setToolTip(tooltip)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIconSize(QSize(24, 24))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.clicked.connect(signal_map[action_id].emit)
            left_col.addWidget(btn)
            self._action_buttons[action_id] = btn

        self.btn_create_model = self._action_buttons["create_model"]
        self.btn_open_model = self._action_buttons["open_model"]
        self.btn_create_fastener = self._action_buttons["create_fastener"]
        self.btn_create_module = self._action_buttons["create_module"]

        left_col.addStretch(1)
        columns.addWidget(left_widget, 0)

        # Правая колонка: «Последние файлы»
        right_widget = QWidget(container)
        right_col = QVBoxLayout(right_widget)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(10)

        recent_hdr = QHBoxLayout()
        recent_hdr.setContentsMargins(0, 0, 0, 0)
        recent_hdr.setSpacing(8)

        recent_heading = QLabel("Последние файлы", right_widget)
        recent_heading.setObjectName("homeSectionTitle")
        recent_hdr.addWidget(recent_heading)
        recent_hdr.addStretch(1)

        self.btn_clear_recent = QPushButton("Очистить", right_widget)
        self.btn_clear_recent.setObjectName("homeClearBtn")
        self.btn_clear_recent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_recent.setToolTip("Очистить список последних файлов")
        self.btn_clear_recent.clicked.connect(self.clear_recent_requested.emit)
        recent_hdr.addWidget(self.btn_clear_recent)
        right_col.addLayout(recent_hdr)

        self.recent_list = _RecentFilesList(right_widget)
        self.recent_list.setObjectName("homeRecentList")
        self.recent_list.setSpacing(2)
        self.recent_list.setUniformItemSizes(False)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.itemClicked.connect(self._on_recent_item_triggered)
        self.recent_list.enter_pressed.connect(self._on_recent_item_triggered)
        self.recent_list.customContextMenuRequested.connect(self._on_recent_context_menu)
        right_col.addWidget(self.recent_list, 1)

        self._empty_box = QFrame(right_widget)
        self._empty_box.setObjectName("homeEmptyBox")
        empty_l = QVBoxLayout(self._empty_box)
        empty_l.setContentsMargins(20, 24, 20, 24)
        empty_l.setSpacing(6)
        empty_title = QLabel("Нет недавно открытых файлов", self._empty_box)
        empty_title.setObjectName("homeEmptyTitle")
        empty_l.addWidget(empty_title)
        empty_hint = QLabel(
            "Откройте существующую модель (.b3d), и она появится в этом списке.",
            self._empty_box,
        )
        empty_hint.setObjectName("homeEmptyHint")
        empty_hint.setWordWrap(True)
        empty_l.addWidget(empty_hint)
        right_col.addWidget(self._empty_box)
        right_col.addStretch(0)

        columns.addWidget(right_widget, 1)
        main_col.addLayout(columns, 1)

    def _action_icon_color(self) -> str:
        c = current_theme()
        return c.accent_soft if c.name == "dark" else c.accent

    def refresh_theme(self) -> None:
        """Обновляет палитру и перекрашивает SVG-иконки под текущую тему."""
        c = current_theme()
        self._theme_name = c.name

        self.setStyleSheet(
            f"""
            QWidget#homePage, QScrollArea#homeScroll, QWidget#homeCanvas {{
                background-color: {c.bg};
                color: {c.text};
            }}
            QLabel#homeAppTitle {{
                font-size: 24px;
                font-weight: 600;
                color: {c.text_title};
            }}
            QLabel#homeAppSubtitle {{
                font-size: 12px;
                color: {c.text_dim};
            }}
            QFrame#homeDivider {{
                background-color: {c.border};
                border: none;
            }}
            QLabel#homeSectionTitle {{
                font-size: 15px;
                font-weight: 600;
                color: {c.text_title};
                padding-bottom: 4px;
            }}
            QToolButton#homeActionBtn {{
                background-color: transparent;
                color: {c.text};
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 10px 12px;
                font-size: 13px;
                text-align: left;
            }}
            QToolButton#homeActionBtn:hover {{
                background-color: {c.bg_panel};
                border-color: {c.border};
            }}
            QToolButton#homeActionBtn:pressed {{
                background-color: {c.select_bg};
                color: {c.select_fg};
                border-color: {c.accent};
            }}
            QPushButton#homeClearBtn {{
                background: transparent;
                color: {c.text_dim};
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QPushButton#homeClearBtn:hover {{
                color: {c.text};
                background-color: {c.bg_panel};
                border-color: {c.border};
            }}
            QListWidget#homeRecentList {{
                background-color: {c.bg_panel};
                border: 1px solid {c.border};
                border-radius: 4px;
                padding: 4px;
                outline: none;
            }}
            QListWidget#homeRecentList::item {{
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0px;
            }}
            QListWidget#homeRecentList::item:hover {{
                background-color: {c.bg_input};
                border-color: {c.border};
            }}
            QListWidget#homeRecentList::item:selected {{
                background-color: {c.select_bg};
                color: {c.select_fg};
            }}
            QLabel#recentFileName {{
                font-size: 13px;
                font-weight: 600;
                color: {c.text};
            }}
            QLabel#recentFileDir {{
                font-size: 11px;
                color: {c.text_dim};
            }}
            QFrame#homeEmptyBox {{
                background-color: {c.bg_panel};
                border: 1px solid {c.border};
                border-radius: 4px;
            }}
            QLabel#homeEmptyTitle {{
                font-size: 13px;
                font-weight: 600;
                color: {c.text};
            }}
            QLabel#homeEmptyHint {{
                font-size: 12px;
                color: {c.text_dim};
            }}
            """
        )

        icon_color = self._action_icon_color()
        for action_id, _label, icon_name, _tooltip in HOME_LAUNCH_ACTIONS:
            btn = self._action_buttons.get(action_id)
            if btn is not None:
                btn.setIcon(_render_themed_svg_icon(_ICONS_DIR / icon_name, icon_color, size=24))

        file_icon = _render_themed_svg_icon(_ICONS_DIR / "home_recent_file.svg", c.text_dim, size=20)
        for row_idx in range(self.recent_list.count()):
            item = self.recent_list.item(row_idx)
            if item is None:
                continue
            row_w = self.recent_list.itemWidget(item)
            if isinstance(row_w, _RecentFileRowWidget):
                row_w.set_icon(file_icon)

    def refresh_recent_files(self, *, storage_path: str | Path | None = None) -> None:
        """Перечитывает список последних файлов с диска и обновляет отображение."""
        entries = build_recent_file_entries(storage_path=storage_path, only_existing=True)
        self.set_recent_files(entries)

    def set_recent_files(self, entries: list[RecentFileEntry] | list[str]) -> None:
        """Заполняет список «Последние файлы» в переданном порядке открытия."""
        normalized: list[RecentFileEntry] = []
        for item in entries:
            if isinstance(item, RecentFileEntry):
                normalized.append(item)
            else:
                normalized.extend(build_recent_file_entries([str(item)], only_existing=False))

        self._recent_entries = normalized
        self.recent_list.clear()

        has_items = bool(normalized)
        self.recent_list.setVisible(has_items)
        self._empty_box.setVisible(not has_items)
        self.btn_clear_recent.setVisible(has_items)
        if not has_items:
            return

        c = current_theme()
        file_icon = _render_themed_svg_icon(_ICONS_DIR / "home_recent_file.svg", c.text_dim, size=20)
        for entry in normalized:
            list_item = QListWidgetItem(self.recent_list)
            list_item.setData(Qt.ItemDataRole.UserRole, entry.path)
            list_item.setToolTip(entry.path)
            row_w = _RecentFileRowWidget(entry, file_icon, self.recent_list)
            list_item.setSizeHint(row_w.sizeHint())
            self.recent_list.addItem(list_item)
            self.recent_list.setItemWidget(list_item, row_w)

    def recent_file_paths(self) -> list[str]:
        """Возвращает пути отображаемых сейчас последних файлов в порядке списка."""
        return [e.path for e in self._recent_entries]

    def _on_recent_item_triggered(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if path:
            self.recent_file_requested.emit(path)

    def _on_recent_context_menu(self, pos: QPoint) -> None:
        item = self.recent_list.itemAt(pos)
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not path:
            return
        menu = QMenu(self)
        act_open = menu.addAction("Открыть")
        act_remove = menu.addAction("Убрать из списка")
        chosen = menu.exec(self.recent_list.viewport().mapToGlobal(pos))
        if chosen is act_open:
            self.recent_file_requested.emit(path)
        elif chosen is act_remove:
            self.remove_recent_requested.emit(path)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._theme_name != current_theme().name:
            self.refresh_theme()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            if self._theme_name != current_theme().name:
                self.refresh_theme()
