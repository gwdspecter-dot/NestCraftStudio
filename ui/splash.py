"""
Splash / loading screen для NestCraft Studio (Adobe-style).

Тёмный фон, логотип, название, MIT / GitHub, прогресс-бар, статус и версия.
Статичный текст из splash.svg на нижней полосе не используется —
статус и версия рисуются только динамически.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, QSize, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget, QApplication

from core.version import APP_VERSION

_ICONS = Path(__file__).resolve().parent / "icons"
_LOGO_SVG = _ICONS / "logo.svg"
_SPLASH_SVG = _ICONS / "splash.svg"

# Цвета из макета
BG = QColor("#1c2023")
ORANGE = QColor("#f9984f")
BLUE = QColor("#0065dc")
BLUE_DARK = QColor("#004bd0")
WHITE = QColor("#ffffff")
BAR_TRACK = QColor("#ffffff")
TEXT_MUTED = QColor("#c8cdd2")

SPLASH_W = 720
SPLASH_H = 400


def _try_svg_pixmap(path: Path, size: QSize) -> QPixmap | None:
    """Рендер SVG в QPixmap, если доступен QtSvg."""
    if not path.is_file():
        return None
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size.width(), size.height()))
    p.end()
    return pm


def _try_svg_region(path: Path, src: QRectF, out_size: QSize) -> QPixmap | None:
    """Рендер фрагмента SVG (для логотипа без нижнего текста)."""
    if not path.is_file():
        return None
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    pm = QPixmap(out_size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    # viewBox исходного splash: 0 0 3138.04 1739.34
    renderer.render(p, QRectF(0, 0, out_size.width(), out_size.height()))
    p.end()
    return pm


class SplashScreen(QWidget):
    """Бесрамочный экран загрузки с прогресс-баром и статусом."""

    def __init__(self, version: str = APP_VERSION, parent=None):
        super().__init__(parent)
        self._version = version if version.startswith("v") else f"v{version}"
        self._progress = 0  # 0..100
        self._status = "Инициализация…"
        self._logo_pm: QPixmap | None = None
        self._mark_pm: QPixmap | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(SPLASH_W, SPLASH_H)
        self.setObjectName("NestCraftSplash")

        # Только логотип-марка, без нижнего текста splash.svg
        self._logo_pm = _try_svg_pixmap(_LOGO_SVG, QSize(140, 157))
        # Верхняя часть splash (название + марка) — обрежем снизу при отрисовке
        self._mark_pm = _try_svg_pixmap(_SPLASH_SVG, QSize(SPLASH_W, SPLASH_H))

        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )

    def set_progress(self, value: int, status: str | None = None) -> None:
        self._progress = max(0, min(100, int(value)))
        if status is not None:
            self._status = status
        self.update()
        QApplication.processEvents()

    def show_message(self, message: str, progress: int | None = None) -> None:
        if progress is not None:
            self._progress = max(0, min(100, int(progress)))
        self._status = message
        self.update()
        QApplication.processEvents()

    def finish(self, main_window: QWidget | None = None) -> None:
        self.set_progress(100, "Готово")
        QTimer.singleShot(180, self.close)
        if main_window is not None:
            main_window.raise_()
            main_window.activateWindow()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1) Фон
        p.fillRect(self.rect(), BG)

        # 2) Полный макет splash.svg без клипа — логотип не обрезается
        if self._mark_pm is not None and not self._mark_pm.isNull():
            p.drawPixmap(0, 0, self._mark_pm)
        else:
            self._paint_fallback_background(p)

        # 3) Только узкая нижняя полоса (статус + бар в SVG) — без полос по логотипу.
        #    В макете текст статуса ~y=1516/1739 ≈ 87%, бар ~93%.
        footer_top = int(SPLASH_H * 0.84)
        p.fillRect(0, footer_top, SPLASH_W, SPLASH_H - footer_top, BG)
        self._paint_progress_area(p)
        p.end()

    def _paint_fallback_background(self, p: QPainter) -> None:
        """Программный макет, если SVG не загрузился."""
        # Логотип справа
        logo_x, logo_y = SPLASH_W - 210, 55
        if self._logo_pm and not self._logo_pm.isNull():
            p.drawPixmap(logo_x, logo_y, self._logo_pm)
        else:
            self._paint_simple_mark(p, logo_x + 10, logo_y + 5)

        title_font = QFont("Segoe UI", 34, QFont.Weight.Black)
        p.setFont(title_font)
        fm = QFontMetrics(title_font)
        x, y = 36, 88
        p.setPen(ORANGE)
        p.drawText(x, y, "Nest")
        x += fm.horizontalAdvance("Nest")
        p.setPen(BLUE)
        p.drawText(x, y, "Craft")
        x += fm.horizontalAdvance("Craft")
        p.setPen(WHITE)
        studio = QFont("Segoe UI", 28, QFont.Weight.Normal)
        p.setFont(studio)
        p.drawText(x + 6, y, "Studio")

        sub = QFont("Segoe UI", 11)
        p.setFont(sub)
        p.setPen(TEXT_MUTED)
        p.drawText(36, 140, "MIT License  Free for Personal & Commercial Use")
        p.drawText(36, 168, "github.com/gwdspecter-dot/NestCraft-Studio")

    def _paint_simple_mark(self, p: QPainter, x: int, y: int) -> None:
        p.save()
        p.translate(x, y)
        p.scale(0.48, 0.48)
        path = QPainterPath()
        path.moveTo(200, 0)
        path.lineTo(0, 110)
        path.lineTo(200, 220)
        path.lineTo(400, 110)
        path.closeSubpath()
        p.setBrush(ORANGE)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        p.setBrush(BLUE_DARK)
        path2 = QPainterPath()
        path2.moveTo(200, 220)
        path2.lineTo(400, 110)
        path2.lineTo(400, 280)
        path2.lineTo(200, 390)
        path2.closeSubpath()
        p.drawPath(path2)
        p.setBrush(BLUE)
        path3 = QPainterPath()
        path3.moveTo(200, 220)
        path3.lineTo(200, 390)
        path3.lineTo(0, 280)
        path3.lineTo(0, 110)
        path3.closeSubpath()
        p.drawPath(path3)
        p.restore()

    def _paint_progress_area(self, p: QPainter) -> None:
        margin = 36
        bar_h = 4
        # Внутри нижней зоны (footer от ~84% высоты), чуть выше края окна
        bar_y = SPLASH_H - 36
        bar_w = SPLASH_W - margin * 2

        font = QFont("Segoe UI", 10)
        p.setFont(font)
        p.setPen(WHITE)
        fm = QFontMetrics(font)

        status = self._status
        max_status_w = bar_w - fm.horizontalAdvance(self._version) - 24
        if fm.horizontalAdvance(status) > max_status_w:
            status = fm.elidedText(status, Qt.TextElideMode.ElideRight, max_status_w)
        p.drawText(margin, bar_y - 14, status)
        p.drawText(SPLASH_W - margin - fm.horizontalAdvance(self._version), bar_y - 14, self._version)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BAR_TRACK)
        p.drawRect(margin, bar_y, bar_w, bar_h)

        fill_w = int(bar_w * (self._progress / 100.0))
        if fill_w > 0:
            p.setBrush(ORANGE)
            p.drawRect(margin, bar_y, fill_w, bar_h)


def run_with_splash(load_callable, version: str = APP_VERSION):
    """
    Показать splash, выполнить load_callable(splash) → main_window, закрыть splash.
    """
    splash = SplashScreen(version=version)
    splash.show()
    splash.show_message("Запуск NestCraft Studio…", 5)
    QApplication.processEvents()

    window = load_callable(splash)

    splash.finish(window)
    return window
