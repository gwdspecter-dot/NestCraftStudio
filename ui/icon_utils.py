# -*- coding: utf-8 -*-
"""Единый загрузчик и кеш тематических SVG-иконок из ``ui/icons/``.

Все иконки используют ``currentColor`` и перекрашиваются под текущую тему
приложения (``ui/theme.py``) с HiDPI-рендерингом (DPR 2.0). Безопасно работает
и в headless-тестах без графического контекста Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.logging_setup import get_logger

_log = get_logger("icon_utils")

ICONS_DIR = Path(__file__).resolve().parent / "icons"

_ICON_CACHE: dict[tuple[str, str, int], Any] = {}
_PIXMAP_CACHE: dict[tuple[str, str, int], Any] = {}


def clear_icon_cache() -> None:
    """Сбрасывает кеш отрендеренных иконок (например, при смене темы)."""
    _ICON_CACHE.clear()
    _PIXMAP_CACHE.clear()


def _resolve_color(color_hex: str | None) -> str:
    if color_hex:
        return str(color_hex)
    try:
        from ui.theme import current_theme

        return str(current_theme().text)
    except Exception:
        _log.debug("Fallback to neutral icon color outside theme context", exc_info=True)
        return "#d4d4d4"


def render_svg_pixmap(
    icon_name: str,
    color_hex: str | None = None,
    size: int = 16,
) -> Any:
    """Рендерит SVG из ``ui/icons/<icon_name>`` в ``QPixmap`` нужного цвета и размера."""
    try:
        from PyQt6.QtCore import QByteArray, QRectF, Qt
        from PyQt6.QtGui import QPainter, QPixmap
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        _log.debug("PyQt6.QtSvg unavailable; returning None pixmap for %s", icon_name)
        return None

    svg_path = ICONS_DIR / icon_name
    if not svg_path.is_file():
        _log.warning("SVG icon not found: %s", svg_path)
        return QPixmap()

    color = _resolve_color(color_hex)
    key = (icon_name, color, int(size))
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        raw = svg_path.read_text(encoding="utf-8")
        tinted = raw.replace("currentColor", color).encode("utf-8")
        renderer = QSvgRenderer(QByteArray(tinted))
        if not renderer.isValid():
            return QPixmap(str(svg_path))
        dpr = 2.0
        px = max(1, int(round(size * dpr)))
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
        painter.end()
        _PIXMAP_CACHE[key] = pm
        return pm
    except Exception:
        # Headless-тесты без QGuiApplication не могут создать QPixmap
        _log.debug("Failed to render SVG pixmap %s", svg_path, exc_info=True)
        return QPixmap()


def render_svg_icon(
    icon_name: str,
    color_hex: str | None = None,
    size: int = 16,
) -> Any:
    """Рендерит SVG из ``ui/icons/<icon_name>`` в ``QIcon`` с цветом текущей темы."""
    try:
        from PyQt6.QtGui import QIcon
    except Exception:
        _log.debug("PyQt6.QtGui unavailable; returning None icon for %s", icon_name)
        return None

    svg_path = ICONS_DIR / icon_name
    if not svg_path.is_file():
        _log.warning("SVG icon not found: %s", svg_path)
        return QIcon()

    color = _resolve_color(color_hex)
    key = (icon_name, color, int(size))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    pm = render_svg_pixmap(icon_name, color, size=size)
    if pm is None or (hasattr(pm, "isNull") and pm.isNull()):
        return QIcon()
    icon = QIcon(pm)
    _ICON_CACHE[key] = icon
    return icon
