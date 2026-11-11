"""Системная тема NestCraft: светлая / тёмная в духе VS Code, по цветовой схеме ОС."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from core.logging_setup import get_logger

_log = get_logger("theme")


@dataclass(frozen=True)
class ThemeColors:
    name: str
    # surfaces
    bg: str
    bg_alt: str
    bg_panel: str
    bg_input: str
    border: str
    # text
    text: str
    text_dim: str
    text_title: str
    # accents
    accent: str
    accent_hover: str
    accent_soft: str
    select_bg: str
    select_fg: str
    code_bg: str
    code_fg: str
    heading: str
    error: str
    warning: str
    success: str


DARK = ThemeColors(
    name="dark",
    bg="#1e1e1e",
    bg_alt="#252526",
    bg_panel="#2d2d2d",
    bg_input="#3c3c3c",
    border="#3c3c3c",
    text="#d4d4d4",
    text_dim="#858585",
    text_title="#e8e8e8",
    accent="#0e639c",
    accent_hover="#1177bb",
    accent_soft="#4fc1ff",
    select_bg="#094771",
    select_fg="#ffffff",
    code_bg="#2d2d2d",
    code_fg="#ce9178",
    heading="#4ec9b0",
    error="#f14c4c",
    warning="#cca700",
    success="#89d185",
)

LIGHT = ThemeColors(
    name="light",
    # Каркас UI чуть серее; контент/инпуты — белые → зоны читаются
    bg="#eef0f3",          # общий фон окна
    bg_alt="#e4e7ec",      # меню, тулбары, статусбар
    bg_panel="#f7f8fa",     # доки, боковые панели
    bg_input="#ffffff",     # поля ввода, таблицы, списки
    border="#c5cad3",      # заметные границы
    text="#1e1e1e",
    text_dim="#5c6570",
    text_title="#111827",
    accent="#0078d4",
    accent_hover="#106ebe",
    accent_soft="#005a9e",
    select_bg="#cce8ff",
    select_fg="#000000",
    code_bg="#f0f2f5",
    code_fg="#a31515",
    heading="#267f99",
    error="#c72e0f",
    warning="#bf8803",
    success="#388a34",
)

_current: ThemeColors = LIGHT


def current_theme() -> ThemeColors:
    return _current


def is_system_dark() -> bool:
    """True, если ОС / Qt сообщает тёмную схему."""
    app = QApplication.instance()
    if app is None:
        return False
    try:
        scheme = app.styleHints().colorScheme()
        # Qt 6.5+
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception as exc:
        _log.debug("styleHints().colorScheme() недоступен: %s", exc)
    # Fallback: яркость window-цвета палитры
    try:
        c = app.palette().color(QPalette.ColorRole.Window)
        return (c.red() + c.green() + c.blue()) / 3 < 128
    except Exception as exc:
        _log.debug("Проверка яркости палитры Window не удалась: %s", exc)
        return False


def theme_for_system() -> ThemeColors:
    return DARK if is_system_dark() else LIGHT


def build_palette(c: ThemeColors) -> QPalette:
    pal = QPalette()
    bg = QColor(c.bg)
    bg_alt = QColor(c.bg_alt)
    text = QColor(c.text)
    dim = QColor(c.text_dim)
    select = QColor(c.select_bg)
    select_fg = QColor(c.select_fg)
    base = QColor(c.bg_input)
    border = QColor(c.border)

    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, bg_alt)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, dim)
    pal.setColor(QPalette.ColorRole.Button, bg_alt)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Highlight, select)
    pal.setColor(QPalette.ColorRole.HighlightedText, select_fg)
    pal.setColor(QPalette.ColorRole.Link, QColor(c.accent))
    pal.setColor(QPalette.ColorRole.LinkVisited, QColor(c.accent_soft))
    pal.setColor(QPalette.ColorRole.ToolTipBase, bg_alt)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Light, border)
    pal.setColor(QPalette.ColorRole.Mid, border)
    pal.setColor(QPalette.ColorRole.Dark, QColor(c.bg_panel))
    # Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, dim)
    return pal


def _icon_url(icons_dir: Path | None, name: str) -> str:
    if icons_dir is None:
        return ""
    p = icons_dir / name
    if not p.is_file():
        return ""
    # Qt stylesheet: forward slashes
    return p.resolve().as_posix()


def build_stylesheet(c: ThemeColors, icons_dir: Path | None = None) -> str:
    chevron_down = _icon_url(icons_dir, "chevron_down.svg")
    chevron_up = _icon_url(icons_dir, "chevron_up.svg")
    close_ico = _icon_url(icons_dir, "close.svg")
    return f"""
/* NestCraft theme: {c.name} */
QWidget {{
    color: {c.text};
}}
QMainWindow, QDialog {{
    background-color: {c.bg};
}}
QMainWindow::separator {{
    background: {c.border};
    width: 1px;
    height: 1px;
}}
QMenuBar {{
    background-color: {c.bg_alt};
    color: {c.text};
    border-bottom: 1px solid {c.border};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background-color: {c.select_bg};
    color: {c.select_fg};
}}
QMenu {{
    background-color: {c.bg_alt};
    color: {c.text};
    border: 1px solid {c.border};
}}
QMenu::item:selected {{
    background-color: {c.select_bg};
    color: {c.select_fg};
}}
QMenu::separator {{
    height: 1px;
    background: {c.border};
    margin: 4px 8px;
}}
QToolBar {{
    background-color: {c.bg_alt};
    border: none;
    border-bottom: 1px solid {c.border};
    border-right: 1px solid {c.border};
    spacing: 4px;
    padding: 3px;
}}
QToolBar QLabel {{
    color: {c.text_dim};
    padding-left: 4px;
}}
QToolButton {{
    background: transparent;
    color: {c.text};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    background-color: {c.bg_panel};
    border-color: {c.border};
}}
QToolButton:pressed, QToolButton:checked {{
    background-color: {c.select_bg};
    color: {c.select_fg};
}}
QStatusBar {{
    background-color: {c.bg_alt};
    color: {c.text_dim};
    border-top: 1px solid {c.border};
}}
QDockWidget {{
    color: {c.text};
    titlebar-close-icon: none;
    border: 1px solid {c.border};
    background-color: {c.bg_panel};
}}
QDockWidget > QWidget {{
    background-color: {c.bg_panel};
}}
QDockWidget::title {{
    background-color: {c.bg_alt};
    color: {c.text_title};
    padding: 6px 8px;
    border-bottom: 1px solid {c.border};
    font-weight: 600;
}}
QTreeWidget, QListWidget, QTableWidget, QTableView, QTreeView {{
    background-color: {c.bg_input};
    alternate-background-color: {c.bg_panel};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: 3px;
    outline: none;
}}
QTreeWidget::item:selected, QListWidget::item:selected,
QTableWidget::item:selected, QTreeView::item:selected {{
    background-color: {c.select_bg};
    color: {c.select_fg};
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {c.bg_panel};
}}
QHeaderView::section {{
    background-color: {c.bg_alt};
    color: {c.text};
    border: none;
    border-right: 1px solid {c.border};
    border-bottom: 1px solid {c.border};
    padding: 4px 8px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {c.bg_input};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {c.select_bg};
    selection-color: {c.select_fg};
}}
QComboBox QAbstractItemView {{
    background-color: {c.bg_alt};
    color: {c.text};
    selection-background-color: {c.select_bg};
}}
QPushButton {{
    background-color: {c.bg_panel};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: 4px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    background-color: {c.bg_input};
    border-color: {c.accent};
}}
QPushButton:pressed {{
    background-color: {c.select_bg};
    color: {c.select_fg};
}}
QPushButton:default {{
    background-color: {c.accent};
    color: #ffffff;
    border-color: {c.accent};
}}
QPushButton:default:hover {{
    background-color: {c.accent_hover};
}}
QTabWidget::pane {{
    border: 1px solid {c.border};
    background: {c.bg_input};
    top: -1px;
}}
QTabBar {{
    background: {c.bg};
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: {c.bg_alt};
    color: {c.text_dim};
    border: 1px solid {c.border};
    padding: 6px 12px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    background: {c.bg_input};
    color: {c.text_title};
    border-bottom-color: {c.bg_input};
}}
QScrollBar:vertical {{
    background: {c.bg};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c.text_dim};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c.bg};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {c.text_dim};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QToolTip {{
    background-color: {c.bg_panel};
    color: {c.text};
    border: 1px solid {c.border};
    padding: 4px;
}}
QGroupBox {{
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QSplitter::handle {{
    background-color: {c.border};
}}
QCheckBox, QRadioButton {{
    color: {c.text};
    spacing: 6px;
}}
QProgressBar {{
    border: 1px solid {c.border};
    border-radius: 3px;
    background: {c.bg_alt};
    text-align: center;
    color: {c.text};
}}
QProgressBar::chunk {{
    background-color: {c.accent};
}}
QComboBox {{
    padding-right: 22px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url({chevron_down});
    width: 12px;
    height: 12px;
}}
QSpinBox, QDoubleSpinBox {{
    padding-right: 20px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    background: transparent;
    margin-right: 2px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    background: transparent;
    margin-right: 2px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({chevron_up});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({chevron_down});
    width: 10px;
    height: 10px;
}}
QTabBar::tab {{
    padding: 6px 28px 6px 12px;
    min-height: 22px;
}}
QTabBar::close-button {{
    image: url({close_ico});
    subcontrol-position: right;
    subcontrol-origin: padding;
    width: 14px;
    height: 14px;
    margin-right: 4px;
    background: transparent;
    border-radius: 3px;
    padding: 1px;
}}
QTabBar::close-button:hover {{
    background: rgba(128, 128, 128, 0.35);
}}
"""


def apply_theme(app: QApplication | None = None, theme: ThemeColors | None = None) -> ThemeColors:
    """Применить палитру + stylesheet. По умолчанию — схема ОС."""
    global _current
    app = app or QApplication.instance()
    if app is None:
        return _current
    c = theme or theme_for_system()
    _current = c
    icons_dir = Path(__file__).resolve().parent / "icons"
    app.setPalette(build_palette(c))
    app.setStyleSheet(build_stylesheet(c, icons_dir=icons_dir))
    _log.info("Theme applied: %s (system_dark=%s)", c.name, is_system_dark())
    return c


def install_system_theme_watcher(app: QApplication | None = None) -> None:
    """Переключать тему при смене светлой/тёмной схемы ОС (Qt 6.5+)."""
    app = app or QApplication.instance()
    if app is None:
        return
    try:
        hints = app.styleHints()
        hints.colorSchemeChanged.connect(lambda *_: apply_theme(app))
        _log.debug("System colorScheme watcher installed")
    except Exception:
        _log.debug("colorSchemeChanged not available", exc_info=True)
