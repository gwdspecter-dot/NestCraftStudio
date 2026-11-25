"""Конструктор параметрической фурнитуры (крепёж по стыку).

Макет:
  [Параметрическая | Пользовательская]
  ┌────┬─────────────────────┬──────────────────┐
  │ ик │  схемы с размерами  │  3D предпросмотр │
  │ он │                     │                  │
  │ ки │  таблица параметров │                  │
  │    │  [+] [×] [копия]    │                  │
  └────┴─────────────────────┴──────────────────┘
Пока реализован только тип «Конфирмат»; остальные кнопки-заглушки.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QSize, QByteArray, QEvent, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QBrush, QFont, QPixmap, QShortcut
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.fastener_constructor import (
    ConfirmatParams,
    FASTENER_FIELD_LABELS,
    apply_fastener_cell_input,
    compute_rows_dirty_state,
    format_constructor_title,
    format_row_number_label,
    load_confirmat_rows,
    recalculate_confirmat_row,
    save_confirmat_rows,
    validate_confirmat_row,
)
from ui.theme import current_theme

_BASE_DIALOG_TITLE = "Конструктор параметрической фурнитуры"
_COL_TO_FIELD: dict[int, str] = {
    2: "d1",
    3: "d2",
    4: "h",
    5: "h1",
}
_FIELD_TO_COL: dict[str, int] = {v: k for k, v in _COL_TO_FIELD.items()}
_FORMULA_ROLE = Qt.ItemDataRole.UserRole + 1

_ICONS = Path(__file__).resolve().parent / "icons" / "fasteners"

# Типы в левой панели (порядок = как в макете)
_TYPE_BUTTONS: list[tuple[str, str, str]] = [
    ("hinge", "Петля", "hinge.svg"),
    ("confirmat", "Конфирмат", "confirmat.svg"),
    ("minifix", "Эксцентриковая стяжка", "minifix.svg"),
    ("double_minifix", "Двухсторонняя стяжка", "double_minifix.svg"),
    ("shelf_pin", "Полкодержатель", "shelf_pin.svg"),
    ("corner_bracket", "Уголок", "corner_bracket.svg"),
    ("dowel", "Шкант", "dowel.svg"),
    ("handle", "Ручка", "handle.svg"),
]

# Реализованные типы
_IMPLEMENTED_TYPES = {"confirmat"}



def _recolor_svg(raw: str, *, for_dark: bool) -> str:
    """Подменяет палитру SVG под светлую / тёмную тему.

    Монохромные иконки типов (серая шкала) на тёмной теме инвертируются.
    Схемы group/group2 сохраняют прежнюю CAD-палитру.
    """
    if for_dark:
        mapping = {
            # монохромные иконки типов: инверсия серой шкалы под тёмный фон
            "#0c0e12": "#e9edf3",
            "#4e535c": "#cfd6e0",
            "#7b828e": "#a8b0bc",
            "#a8b0bc": "#7b828e",
            "#cfd6e0": "#4e535c",
            "#e9edf3": "#2a2e36",
            "#ffffff": "#1a1d22",
            "#0C0E12": "#e9edf3",
            "#4E535C": "#cfd6e0",
            "#7B828E": "#a8b0bc",
            "#A8B0BC": "#7b828e",
            "#CFD6E0": "#4e535c",
            "#E9EDF3": "#2a2e36",
            "#FFFFFF": "#1a1d22",
            # схемы (group.svg) — почти чёрные тела панелей
            "#0F141C": "#334155",
            "#1E293B": "#475569",
            "#0f141c": "#334155",
            "#1e293b": "#475569",
            # вспомогательные на схемах
            "#787880": "#94a3b8",
        }
    else:
        mapping = {
            # светлая тема: монохром оставляем как есть (тёмный на светлом)
            # схемы: светлая CAD-палитра на белом фоне
            "#0F141C": "#94a3b8",
            "#1E293B": "#cbd5e1",
            "#0f141c": "#94a3b8",
            "#1e293b": "#cbd5e1",
            "#787880": "#64748b",
            # контуры панелей/винта → тёмно-графитовые
            "#E2F1FF": "#1e293b",
            "#e2f1ff": "#1e293b",
            # осевая линия
            "#F43F5E": "#e11d48",
            "#f43f5e": "#e11d48",
            # размерные линии и подписи D1/D2/H
            "#38BDF8": "#0284c7",
            "#38bdf8": "#0284c7",
            "#7DD3FC": "#0369a1",
            "#7dd3fc": "#0369a1",
            # размерная линия и подпись H1 (жёлтый → контрастный янтарный)
            "#FBBF24": "#d97706",
            "#fbbf24": "#d97706",
            "#FDE68A": "#b45309",
            "#fde68a": "#b45309",
        }
    for old, new in mapping.items():
        raw = raw.replace(old, new)
    return raw


def _themed_fastener_icon(svg_path: Path, size: int = 48) -> QIcon:
    """Рендерит SVG-иконку с перекраской под текущую тему (без подложки — обводка только у кнопки)."""
    if not svg_path.is_file():
        return QIcon()
    try:
        raw = svg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return QIcon(str(svg_path))

    c = current_theme()
    raw = _recolor_svg(raw, for_dark=(c.name == "dark"))

    renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
    if not renderer.isValid():
        return QIcon(str(svg_path))

    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Небольшой внутренний отступ, чтобы иконка не касалась синей рамки selected
    margin = max(2, size // 14)
    renderer.render(painter, QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    painter.end()
    return QIcon(pm)


class _SchemeWidget(QWidget):
    """Некликабельные схемы с размерными линиями (SVG group / group2)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._renderers: list[QSvgRenderer] = []
        self._theme_name: str = ""
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Перезагружает и перекрашивает SVG-схемы под текущую тему."""
        c = current_theme()
        self._theme_name = c.name
        for_dark = c.name == "dark"
        renderers: list[QSvgRenderer] = []
        for name in ("group.svg", "group2.svg"):
            path = _ICONS / name
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            raw = _recolor_svg(raw, for_dark=for_dark)
            r = QSvgRenderer(QByteArray(raw.encode("utf-8")))
            if r.isValid():
                renderers.append(r)
        self._renderers = renderers
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._theme_name != current_theme().name:
            self.refresh_theme()
        if not self._renderers:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self._renderers)
        margin = 8
        gap = 12
        avail_w = self.width() - 2 * margin - gap * (n - 1)
        cell_w = avail_w / max(n, 1)
        cell_h = self.height() - 2 * margin
        for i, r in enumerate(self._renderers):
            x = margin + i * (cell_w + gap)
            vb = r.viewBoxF()
            if vb.width() <= 0 or vb.height() <= 0:
                continue
            scale = min(cell_w / vb.width(), cell_h / vb.height())
            w = vb.width() * scale
            h = vb.height() * scale
            rx = x + (cell_w - w) / 2
            ry = margin + (cell_h - h) / 2
            from PyQt6.QtCore import QRectF
            r.render(p, QRectF(rx, ry, w, h))
        p.end()


class ConfirmatPreview3D(QWidget):
    """Интерактивный 3D-предпросмотр конфирмата между двумя панелями.

    ЛКМ + перетаскивание — вращение, колесо — масштаб, двойной клик — сброс вида.
    Рисуется через QPainter с сортировкой граней по глубине.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("ЛКМ — вращать · колесо — масштаб · двойной клик — сброс")

        self._params = ConfirmatParams()
        self._panel_thickness = 16.0
        # Камера: углы в градусах, zoom
        self._yaw = 35.0
        self._pitch = 25.0
        self._zoom = 1.0
        self._drag_pos: tuple[float, float] | None = None
        self._theme_name: str = ""
        self._apply_theme_colors()

    def set_params(self, p: ConfirmatParams, *, panel_thickness: float | None = None) -> None:
        self._params = p
        if panel_thickness is not None:
            self._panel_thickness = max(4.0, float(panel_thickness))
        self.update()

    def refresh_theme(self) -> None:
        """Обновляет палитру 3D-предпросмотра при смене светлой/тёмной темы."""
        self._apply_theme_colors()
        self.update()

    def _apply_theme_colors(self) -> None:
        """Фон и цвета модели под текущую тему (не всегда тёмный viewport)."""
        c = current_theme()
        self._theme_name = c.name
        if c.name == "dark":
            self._bg = QColor(c.bg_alt)
            self._panel = QColor(0x4A, 0xD0, 0x6E, 150)
            self._panel_edge = QColor(0x3A, 0xB0, 0x58)
            self._screw = QColor(0x6A, 0xE0, 0x8A)
            self._screw_edge = QColor(0x2E, 0x9E, 0x4F)
            self._dim = QColor(c.text)
            self._hint = QColor(c.text_dim)
        else:
            self._bg = QColor(c.bg_panel)  # светлая панель
            self._panel = QColor(0x22, 0xA0, 0x55, 160)
            self._panel_edge = QColor(0x16, 0x7A, 0x3F)
            self._screw = QColor(0x18, 0x90, 0x4E)
            self._screw_edge = QColor(0x0F, 0x6B, 0x38)
            self._dim = QColor(c.text)
            self._hint = QColor(c.text_dim)

    # ── mouse / wheel ───────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (event.position().x(), event.position().y())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            x, y = event.position().x(), event.position().y()
            dx = x - self._drag_pos[0]
            dy = y - self._drag_pos[1]
            self._yaw += dx * 0.45
            self._pitch = max(-80.0, min(80.0, self._pitch + dy * 0.45))
            self._drag_pos = (x, y)
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._yaw = 35.0
            self._pitch = 25.0
            self._zoom = 1.0
            self.update()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            factor = 1.1 if delta > 0 else 1 / 1.1
            self._zoom = max(0.4, min(3.0, self._zoom * factor))
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    # ── projection ──────────────────────────────────────────────────

    def _project(self, x: float, y: float, z: float, cx: float, cy: float, scale: float):
        """Поворот (yaw/pitch) + простая перспективная проекция → (sx, sy, depth)."""
        yaw = math.radians(self._yaw)
        pitch = math.radians(self._pitch)
        # yaw around Y
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        x1 = x * cos_y + z * sin_y
        z1 = -x * sin_y + z * cos_y
        y1 = y
        # pitch around X
        cos_p, sin_p = math.cos(pitch), math.sin(pitch)
        y2 = y1 * cos_p - z1 * sin_p
        z2 = y1 * sin_p + z1 * cos_p
        x2 = x1
        # orthographic-ish with slight perspective
        s = scale * self._zoom
        return cx + x2 * s, cy - y2 * s, z2

    # ── paint ───────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF

        if self._theme_name != current_theme().name:
            self._apply_theme_colors()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self._bg)

        w, h = self.width(), self.height()
        cx, cy = w * 0.5, h * 0.52
        # Базовый масштаб от размера виджета (мм → px при zoom=1)
        base_scale = min(w, h) / 160.0

        pr = self._params
        d1 = max(pr.d1, 1.0)   # Ø пласть (сквозное)
        d2 = max(pr.d2, 0.5)   # Ø торец (глухое)
        length = max(pr.h, 5.0)  # общая длина конфирмата

        # ── Геометрия как в make_joint_holes / каталоге ──────────────
        # Панель A (пласть): сквозное ØD1 через толщину
        # Панель B (торец): глухое ØD2 в середину торца
        # Ось сверления — X, точка стыка в центре торца B (y=0, z=0)
        t = max(4.0, float(self._panel_thickness))  # толщина панелей, мм
        face_h = 56.0            # высота/ширина куска панели в превью
        half = face_h * 0.5
        # Глубина глухого в торец (единая формула с selected_fastener / make_joint_holes)
        edge_depth = pr.edge_depth(t)

        # A: вертикальная, толщина по X, грань стыка x=0 (пласть)
        #    x ∈ [-t, 0], y ∈ [-half, half], z ∈ [-half, half]
        panel_a = (-t, -half, -half, t, face_h, face_h)
        # B: «полка», торец к стыку; толщина по Z, длина по X
        #    торец в плоскости x=0, центр торца (0, 0, 0)
        panel_b_len = max(edge_depth + 18.0, 40.0)
        panel_b = (0.0, -half, -t * 0.5, panel_b_len, face_h, t)

        faces: list[tuple[float, list[tuple[float, float]], QColor, QColor]] = []

        def add_box(x0, y0, z0, dx, dy, dz, fill: QColor, edge: QColor) -> None:
            corners = [
                (x0, y0, z0),
                (x0 + dx, y0, z0),
                (x0 + dx, y0 + dy, z0),
                (x0, y0 + dy, z0),
                (x0, y0, z0 + dz),
                (x0 + dx, y0, z0 + dz),
                (x0 + dx, y0 + dy, z0 + dz),
                (x0, y0 + dy, z0 + dz),
            ]
            proj = [self._project(c[0], c[1], c[2], cx, cy, base_scale) for c in corners]
            face_idx = [
                (0, 1, 2, 3), (4, 5, 6, 7),
                (0, 1, 5, 4), (3, 2, 6, 7),
                (0, 3, 7, 4), (1, 2, 6, 5),
            ]
            normals = [
                (0, 0, -1), (0, 0, 1),
                (0, -1, 0), (0, 1, 0),
                (-1, 0, 0), (1, 0, 0),
            ]
            light = (0.35, 0.75, 0.45)
            light_len = math.sqrt(sum(v * v for v in light))
            for fi, idx in enumerate(face_idx):
                pts2 = [(proj[i][0], proj[i][1]) for i in idx]
                depth = sum(proj[i][2] for i in idx) / 4.0
                nx, ny, nz = normals[fi]
                yaw = math.radians(self._yaw)
                pitch = math.radians(self._pitch)
                cos_y, sin_y = math.cos(yaw), math.sin(yaw)
                nx1 = nx * cos_y + nz * sin_y
                nz1 = -nx * sin_y + nz * cos_y
                ny1 = ny
                cos_p, sin_p = math.cos(pitch), math.sin(pitch)
                ny2 = ny1 * cos_p - nz1 * sin_p
                nz2 = ny1 * sin_p + nz1 * cos_p
                nx2 = nx1
                if nz2 < -0.05:
                    continue
                ndot = (nx2 * light[0] + ny2 * light[1] + nz2 * light[2]) / light_len
                shade = 0.55 + 0.45 * max(0.0, ndot)
                col = QColor(
                    min(255, int(fill.red() * shade)),
                    min(255, int(fill.green() * shade)),
                    min(255, int(fill.blue() * shade)),
                    fill.alpha(),
                )
                faces.append((depth, pts2, col, edge))

        def add_cylinder(x0, y0, z0, length_mm, radius, fill, edge, n=14) -> None:
            """Цилиндр вдоль +X, ось в (y0,z0)."""
            rings = []
            for end in (0.0, length_mm):
                ring = []
                for i in range(n):
                    a = 2 * math.pi * i / n
                    yy = y0 + radius * math.sin(a)
                    zz = z0 + radius * math.cos(a)
                    ring.append(self._project(x0 + end, yy, zz, cx, cy, base_scale))
                rings.append(ring)
            for i in range(n):
                j = (i + 1) % n
                r0, r1 = rings[0], rings[1]
                pts2 = [
                    (r0[i][0], r0[i][1]),
                    (r0[j][0], r0[j][1]),
                    (r1[j][0], r1[j][1]),
                    (r1[i][0], r1[i][1]),
                ]
                depth = (r0[i][2] + r0[j][2] + r1[j][2] + r1[i][2]) / 4.0
                shade = 0.62 + 0.38 * abs(math.cos(2 * math.pi * i / n))
                col = QColor(
                    min(255, int(fill.red() * shade)),
                    min(255, int(fill.green() * shade)),
                    min(255, int(fill.blue() * shade)),
                    fill.alpha(),
                )
                faces.append((depth, pts2, col, edge))
            for ring in rings:
                pts2 = [(pt[0], pt[1]) for pt in ring]
                depth = sum(pt[2] for pt in ring) / len(ring)
                col = QColor(fill).lighter(108)
                faces.append((depth, pts2, col, edge))

        def add_cone(x0, y0, z0, length_mm, radius, fill, edge, n=12) -> None:
            tip = self._project(x0 + length_mm, y0, z0, cx, cy, base_scale)
            ring = []
            for i in range(n):
                a = 2 * math.pi * i / n
                yy = y0 + radius * math.sin(a)
                zz = z0 + radius * math.cos(a)
                ring.append(self._project(x0, yy, zz, cx, cy, base_scale))
            for i in range(n):
                j = (i + 1) % n
                pts2 = [
                    (ring[i][0], ring[i][1]),
                    (ring[j][0], ring[j][1]),
                    (tip[0], tip[1]),
                ]
                depth = (ring[i][2] + ring[j][2] + tip[2]) / 3.0
                shade = 0.58 + 0.42 * abs(math.cos(2 * math.pi * i / n))
                col = QColor(
                    min(255, int(fill.red() * shade)),
                    min(255, int(fill.green() * shade)),
                    min(255, int(fill.blue() * shade)),
                    fill.alpha(),
                )
                faces.append((depth, pts2, col, edge))

        # Панели
        add_box(*panel_a, self._panel, self._panel_edge)
        add_box(*panel_b, self._panel, self._panel_edge)

        # Отверстия: чуть темнее / контрастнее панелей (вырезы)
        hole_fill = QColor(self._bg)
        if hole_fill.lightness() > 140:
            hole_fill = QColor(0x30, 0x30, 0x30, 200)
        else:
            hole_fill = QColor(0x10, 0x10, 0x10, 210)
        hole_edge = QColor(self._panel_edge).darker(130)

        # 1) Сквозное в пласть A: ØD1 через всю толщину t, по центру
        add_cylinder(-t, 0.0, 0.0, t, d1 * 0.5, hole_fill, hole_edge)
        # 2) Глухое в торец B: ØD2 от плоскости стыка вглубь, центр торца
        add_cylinder(0.0, 0.0, 0.0, edge_depth, d2 * 0.5, hole_fill, hole_edge)

        # Конфирмат: головка снаружи пласти A → стержень → конус в глухом
        head_len = max(d1 * 0.4, 2.0)
        tip_len = max(d2 * 1.0, 3.5)
        # Общая длина H; часть в A = t, остальное в B
        x_head = -t - head_len * 0.15  # головка чуть выступает из пласти
        # Стержень идёт от головки через A и в B
        # Длина стержня = H - head - tip, позиция от конца головки
        total_body = max(length - head_len - tip_len, t + 6.0)
        add_cylinder(x_head, 0.0, 0.0, head_len, d1 * 0.55, self._screw, self._screw_edge)
        add_cylinder(x_head + head_len, 0.0, 0.0, total_body, d2 * 0.5, self._screw, self._screw_edge)
        add_cone(
            x_head + head_len + total_body, 0.0, 0.0,
            tip_len, d2 * 0.5, self._screw, self._screw_edge,
        )

        faces.sort(key=lambda f: f[0])
        for _depth, pts2, col, edge in faces:
            poly = QPolygonF([QPointF(x, y) for x, y in pts2])
            p.setBrush(QBrush(col))
            p.setPen(QPen(edge, 1.0))
            p.drawPolygon(poly)

        # Подписи (с переносом/учётом ширины превью, чтобы не обрезались справа)
        from PyQt6.QtCore import QRectF

        p.setPen(self._dim)
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        label = f"D1={pr.d1:g} (пласть) · D2={pr.d2:g} (торец) · H={pr.h:g}"
        if pr.h1 or pr.has_formula("h1"):
            h1_expr = pr.formula_for("h1")
            label += f" · H1={pr.h1:g} (={h1_expr})" if h1_expr else f" · H1={pr.h1:g}"
        p.drawText(QRectF(12, 8, max(40.0, w - 24), 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        p.setPen(self._hint)
        p.drawText(
            QRectF(12, 26, max(40.0, w - 24), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"Плита t={t:g} мм · глубина в торец {edge_depth:g} мм",
        )
        p.drawText(
            QRectF(12, max(44.0, h - 24), max(40.0, w - 24), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "ЛКМ: вращать · колесо: зум · 2×ЛКМ: сброс",
        )
        p.end()


class _FormulaCellDelegate(QStyledItemDelegate):
    """При редактировании ячейки с формулой открывает исходное выражение ``=...``."""

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        formula = index.data(_FORMULA_ROLE)
        if formula and isinstance(editor, QLineEdit):
            editor.setText(f"={formula}")
            editor.selectAll()
            return
        super().setEditorData(editor, index)


class FastenerConstructorDialog(QDialog):
    """Окно конструктора параметрической фурнитуры."""

    fastener_accepted = pyqtSignal(dict)  # выбранный вариант → dict

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        panel_thickness: float = 16.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_BASE_DIALOG_TITLE)
        self.setMinimumSize(940, 580)
        self.resize(1020, 640)

        self._current_type = "confirmat"
        self._panel_thickness = max(4.0, min(50.0, float(panel_thickness or 16.0)))
        loaded_rows, initial_sel = load_confirmat_rows()
        self._rows: list[ConfirmatParams] = [r.clone() for r in loaded_rows]
        self._saved_rows: list[ConfirmatParams] = [r.clone() for r in loaded_rows]
        for row in self._rows:
            if row.formulas:
                recalculate_confirmat_row(row, panel_thickness=self._panel_thickness)
        self._initial_selected_row: int = initial_sel
        self._type_buttons: dict[str, QToolButton] = {}
        self._last_error: str = ""
        self._syncing_formula_bar: bool = False
        self._applied_theme_name: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Вкладки Параметрическая / Пользовательская ──────────────
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_parametric_page(), "Параметрическая")
        user_page = QWidget()
        user_l = QVBoxLayout(user_page)
        self._user_stub = QLabel("Пользовательская фурнитура — скоро.")
        self._user_stub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        user_l.addWidget(self._user_stub)
        self.tabs.addTab(user_page, "Пользовательская")
        root.addWidget(self.tabs, 1)

        # ── OK / Cancel ─────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        save_shortcut.activated.connect(self._save_rows)

        self._select_type("confirmat")
        self._reload_table(select_row=self._initial_selected_row)
        self._apply_theme(force=True)
        self._sync_formula_bar()
        self._sync_preview()

    # ── parametric page ─────────────────────────────────────────────

    def _build_parametric_page(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Левая колонка иконок (крупнее + перекраска под тему)
        self._left_bar = QFrame()
        self._left_bar.setObjectName("fastenerTypeBar")
        self._left_bar.setFixedWidth(64)
        left_l = QVBoxLayout(self._left_bar)
        left_l.setContentsMargins(6, 10, 6, 10)
        left_l.setSpacing(6)

        icon_px = 44
        for type_id, title, icon_name in _TYPE_BUTTONS:
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolTip(title)
            btn.setIconSize(QSize(icon_px, icon_px))
            icon_path = _ICONS / icon_name
            if not icon_path.is_file():
                btn.setText(title[:1])
            btn.setFixedSize(52, 52)
            btn.setEnabled(type_id in _IMPLEMENTED_TYPES)
            if type_id not in _IMPLEMENTED_TYPES:
                btn.setToolTip(f"{title} (скоро)")
            btn.clicked.connect(lambda checked, t=type_id: self._select_type(t) if checked else None)
            left_l.addWidget(btn)
            self._type_buttons[type_id] = btn
        left_l.addStretch(1)
        outer.addWidget(self._left_bar)

        # Центр + справа
        mid_split = QSplitter(Qt.Orientation.Horizontal)
        mid_split.setChildrenCollapsible(False)

        # Центральная колонка: схемы + таблица + кнопки
        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(8, 8, 8, 8)
        center_l.setSpacing(8)

        self.scheme = _SchemeWidget()
        center_l.addWidget(self.scheme)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["№", "Наименование", "D1", "D2", "H", "H1"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3, 4, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._formula_delegate = _FormulaCellDelegate(self.table)
        for col in _COL_TO_FIELD:
            self.table.setItemDelegateForColumn(col, self._formula_delegate)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        center_l.addWidget(self.table, 1)

        ctrl_h = 28

        # Строка формулы (fx): растягивается на всю ширину таблицы
        fx_row = QHBoxLayout()
        fx_row.setContentsMargins(0, 0, 0, 0)
        fx_row.setSpacing(6)
        self.fx_tag = QLabel("fx  H1:")
        self.fx_tag.setMinimumWidth(46)

        self.formula_edit = QLineEdit()
        self.formula_edit.setFixedHeight(ctrl_h)
        self.formula_edit.setPlaceholderText("Число или формула: =H - t + 4, D1 - 3, round(H*0.76, 1)")
        self.formula_edit.returnPressed.connect(self._apply_formula_bar)

        self.btn_apply_fx = QPushButton("Применить")
        self.btn_apply_fx.setFixedHeight(ctrl_h)
        self.btn_apply_fx.setMinimumWidth(96)
        self.btn_apply_fx.clicked.connect(self._apply_formula_bar)

        fx_row.addWidget(self.fx_tag)
        fx_row.addWidget(self.formula_edit, 1)
        fx_row.addWidget(self.btn_apply_fx)
        center_l.addLayout(fx_row)

        # Единый ряд кнопок таблицы + контрастный переключатель толщины плиты t справа
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self.btn_add = QPushButton("Добавить +")
        self.btn_del = QPushButton("Удалить ×")
        self.btn_copy = QPushButton("Копия")
        self.btn_copy.setToolTip("Создать копию выбранной строки")
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setToolTip("Сохранить таблицу крепежа (Ctrl+S)")
        for b in (self.btn_add, self.btn_del, self.btn_copy, self.btn_save):
            b.setFixedHeight(ctrl_h)
        self.btn_add.clicked.connect(self._add_row)
        self.btn_del.clicked.connect(self._delete_row)
        self.btn_copy.clicked.connect(self._copy_row)
        self.btn_save.clicked.connect(self._save_rows)

        self._t_lbl = QLabel("Плита t:")
        self._t_lbl.setToolTip("Толщина плиты для предпросмотра и расчёта формул с переменной t")
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setFixedSize(96, ctrl_h)
        self.thickness_spin.setRange(4.0, 50.0)
        self.thickness_spin.setDecimals(1)
        self.thickness_spin.setSingleStep(1.0)
        self.thickness_spin.setSuffix(" мм")
        self.thickness_spin.setValue(self._panel_thickness)
        self.thickness_spin.setToolTip("Толщина плиты (переменная t в формулах)")
        self.thickness_spin.valueChanged.connect(self._on_thickness_changed)

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        btn_row.addWidget(self._t_lbl)
        btn_row.addWidget(self.thickness_spin)
        center_l.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        center_l.addWidget(self.status_label)

        mid_split.addWidget(center)

        # Правая колонка — 3D
        self._right_pane = QFrame()
        self._right_pane.setObjectName("previewPane")
        right_l = QVBoxLayout(self._right_pane)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)
        self.preview = ConfirmatPreview3D()
        right_l.addWidget(self.preview, 1)
        mid_split.addWidget(self._right_pane)

        mid_split.setStretchFactor(0, 3)
        mid_split.setStretchFactor(1, 2)
        outer.addWidget(mid_split, 1)
        return page

    # ── live theme adaptation ───────────────────────────────────────

    def _apply_theme(self, *, force: bool = False) -> None:
        """Применяет светлую/тёмную палитру ко всем кастомным элементам диалога."""
        c = current_theme()
        if not force and self._applied_theme_name == c.name:
            return
        self._applied_theme_name = c.name
        is_dark = c.name == "dark"

        if hasattr(self, "_user_stub"):
            self._user_stub.setStyleSheet(f"color: {c.text_dim}; font-size: 13px;")

        if hasattr(self, "_left_bar"):
            # Одна обводка: прозрачная в покое, синяя 2px только у выбранного типа
            self._left_bar.setStyleSheet(
                f"""
                QFrame#fastenerTypeBar {{
                    background: {c.bg_panel};
                    border-right: 1px solid {c.border};
                }}
                QFrame#fastenerTypeBar QToolButton {{
                    background: transparent;
                    border: 2px solid transparent;
                    border-radius: 8px;
                    padding: 2px;
                }}
                QFrame#fastenerTypeBar QToolButton:hover {{
                    background: {c.bg_input};
                    border-color: transparent;
                }}
                QFrame#fastenerTypeBar QToolButton:checked {{
                    background: {c.select_bg};
                    border: 2px solid {c.accent};
                }}
                QFrame#fastenerTypeBar QToolButton:disabled {{
                    background: transparent;
                    border-color: transparent;
                }}
                """
            )

        icon_px = 44
        for type_id, _title, icon_name in _TYPE_BUTTONS:
            btn = self._type_buttons.get(type_id)
            if btn is None:
                continue
            icon_path = _ICONS / icon_name
            if icon_path.is_file():
                btn.setIcon(_themed_fastener_icon(icon_path, size=icon_px * 2))

        # Мягкие поля: без контрастных обводок (в духе ui.theme)
        input_bg = c.bg_input
        input_border = "#4a4a4a" if is_dark else c.border
        spin_btn_bg = c.bg_panel if is_dark else c.bg_alt

        if hasattr(self, "fx_tag"):
            self.fx_tag.setStyleSheet(f"color: {c.text_dim}; font-weight: 600;")
        if hasattr(self, "_t_lbl"):
            self._t_lbl.setStyleSheet(f"color: {c.text_dim}; font-weight: 600;")

        if hasattr(self, "formula_edit"):
            self.formula_edit.setStyleSheet(
                f"""
                QLineEdit {{
                    background-color: {input_bg};
                    color: {c.text};
                    border: 1px solid {input_border};
                    border-radius: 4px;
                    padding: 2px 8px;
                }}
                QLineEdit:focus {{
                    border: 1px solid {c.accent};
                }}
                """
            )

        if hasattr(self, "thickness_spin"):
            icons_dir = Path(__file__).resolve().parent / "icons"
            chev_up = (icons_dir / "chevron_up.svg").resolve().as_posix()
            chev_dn = (icons_dir / "chevron_down.svg").resolve().as_posix()
            self.thickness_spin.setStyleSheet(
                f"""
                QDoubleSpinBox {{
                    background-color: {input_bg};
                    color: {c.text};
                    border: 1px solid {input_border};
                    border-radius: 4px;
                    padding: 2px 22px 2px 8px;
                    font-weight: 600;
                }}
                QDoubleSpinBox:focus {{
                    border: 1px solid {c.accent};
                }}
                QDoubleSpinBox::up-button {{
                    subcontrol-origin: border;
                    subcontrol-position: top right;
                    width: 20px;
                    background-color: {spin_btn_bg};
                    border-left: 1px solid {input_border};
                    border-bottom: 1px solid {input_border};
                    border-top-right-radius: 3px;
                    margin: 0px;
                }}
                QDoubleSpinBox::down-button {{
                    subcontrol-origin: border;
                    subcontrol-position: bottom right;
                    width: 20px;
                    background-color: {spin_btn_bg};
                    border-left: 1px solid {input_border};
                    border-bottom-right-radius: 3px;
                    margin: 0px;
                }}
                QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
                    background-color: {c.select_bg};
                }}
                QDoubleSpinBox::up-arrow {{
                    image: url({chev_up});
                    width: 10px;
                    height: 10px;
                }}
                QDoubleSpinBox::down-arrow {{
                    image: url({chev_dn});
                    width: 10px;
                    height: 10px;
                }}
                """
            )

        if hasattr(self, "_right_pane"):
            self._right_pane.setStyleSheet(
                f"QFrame#previewPane {{ background: {c.bg_panel}; border-left: 1px solid {c.border}; }}"
            )
        if hasattr(self, "scheme"):
            self.scheme.refresh_theme()
        if hasattr(self, "preview"):
            self.preview.refresh_theme()
        if hasattr(self, "table"):
            self._refresh_dirty_state()

    def refresh_theme(self) -> None:
        """Публичный хук обновления темы (вызывается из ui.theme.apply_theme)."""
        self._apply_theme(force=True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_theme()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        ):
            self._apply_theme()

    # ── type selection ──────────────────────────────────────────────

    def _select_type(self, type_id: str) -> None:
        if type_id not in _IMPLEMENTED_TYPES:
            return
        self._current_type = type_id
        for tid, btn in self._type_buttons.items():
            btn.setChecked(tid == type_id)
        self._sync_preview()

    # ── table & formulas ────────────────────────────────────────────

    def _apply_row_cells(self, row_idx: int, *, is_dirty_row: bool) -> None:
        """Обновляет отображение одной строки таблицы (без генерации itemChanged)."""
        if row_idx < 0 or row_idx >= len(self._rows):
            return
        c = current_theme()
        row = self._rows[row_idx]
        num = self.table.item(row_idx, 0)
        if num is None:
            num = QTableWidgetItem()
            self.table.setItem(row_idx, 0, num)
        num.setText(format_row_number_label(row_idx, is_dirty_row))
        num.setFlags(num.flags() & ~Qt.ItemFlag.ItemIsEditable)
        num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num_font = QFont()
        num_font.setBold(is_dirty_row)
        num.setFont(num_font)
        if is_dirty_row:
            num.setForeground(QBrush(QColor(c.warning)))
            num.setToolTip("Строка изменена (не сохранено)")
        else:
            num.setForeground(QBrush(QColor(c.text_dim)))
            num.setToolTip("")

        name_it = self.table.item(row_idx, 1)
        if name_it is None:
            name_it = QTableWidgetItem()
            self.table.setItem(row_idx, 1, name_it)
        if name_it.text() != row.name:
            name_it.setText(row.name)

        for col, fld in _COL_TO_FIELD.items():
            val = float(getattr(row, fld))
            expr = row.formula_for(fld)
            it = self.table.item(row_idx, col)
            if it is None:
                it = QTableWidgetItem()
                self.table.setItem(row_idx, col, it)
            it.setText(f"{val:g}")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setData(_FORMULA_ROLE, expr)
            fnt = QFont()
            if expr:
                fnt.setItalic(True)
                it.setFont(fnt)
                it.setForeground(QBrush(QColor(c.accent_soft)))
                it.setToolTip(f"Формула: ={expr}\nЗначение: {val:g} мм (t={self._panel_thickness:g} мм)")
            else:
                it.setFont(fnt)
                it.setData(Qt.ItemDataRole.ForegroundRole, None)
                it.setToolTip(f"{FASTENER_FIELD_LABELS[fld]} = {val:g} мм (можно ввести формулу, например =H - t + 4)")

    def _reload_table(self, select_row: int = 0) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rows))
        _is_dirty, dirty_indices = compute_rows_dirty_state(
            self._rows, self._saved_rows, panel_thickness=self._panel_thickness
        )
        for i in range(len(self._rows)):
            self._apply_row_cells(i, is_dirty_row=(i in dirty_indices))
        self.table.blockSignals(False)
        if self._rows:
            target = max(0, min(int(select_row), len(self._rows) - 1))
            self.table.selectRow(target)
            if self.table.currentColumn() not in _COL_TO_FIELD:
                self.table.setCurrentCell(target, _FIELD_TO_COL["h1"])

    def _current_row_index(self) -> int:
        sel = self.table.selectionModel().selectedRows()
        if sel:
            return sel[0].row()
        cur = self.table.currentRow()
        if 0 <= cur < len(self._rows):
            return cur
        return 0 if self._rows else -1

    def _active_formula_field(self) -> str:
        col = self.table.currentColumn()
        return _COL_TO_FIELD.get(col, "h1")

    def _refresh_dirty_state(self) -> None:
        is_dirty, dirty_indices = compute_rows_dirty_state(
            self._rows, self._saved_rows, panel_thickness=self._panel_thickness
        )
        self.setWindowTitle(format_constructor_title(_BASE_DIALOG_TITLE, is_dirty))
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(is_dirty)
            self.btn_save.setText("Сохранить *" if is_dirty else "Сохранить")
        self.table.blockSignals(True)
        for i in range(min(len(self._rows), self.table.rowCount())):
            self._apply_row_cells(i, is_dirty_row=(i in dirty_indices))
        self.table.blockSignals(False)
        self._update_status_line(is_dirty)

    def _update_status_line(self, is_dirty: bool) -> None:
        if not hasattr(self, "status_label"):
            return
        c = current_theme()
        if self._last_error:
            self.status_label.setText(self._last_error)
            self.status_label.setStyleSheet(f"color: {c.error}; font-size: 11px;")
            return
        idx = self._current_row_index()
        if 0 <= idx < len(self._rows):
            warnings = validate_confirmat_row(self._rows[idx], panel_thickness=self._panel_thickness)
            if warnings:
                prefix = "Не сохранено (*) · " if is_dirty else ""
                self.status_label.setText(prefix + "; ".join(warnings))
                self.status_label.setStyleSheet(f"color: {c.warning}; font-size: 11px;")
                return
        if is_dirty:
            self.status_label.setText(
                "Есть несохранённые изменения (*) · Ctrl+S или OK для сохранения · Формулы: D1, D2, H, H1, t"
            )
            self.status_label.setStyleSheet(f"color: {c.warning}; font-size: 11px;")
        else:
            self.status_label.setText(
                "Сохранено · В ячейках D1/D2/H/H1 поддерживаются формулы (например =H - t + 4, D1 - 3, += 2)"
            )
            self.status_label.setStyleSheet(f"color: {c.text_dim}; font-size: 11px;")

    def _sync_formula_bar(self) -> None:
        if not hasattr(self, "formula_edit"):
            return
        idx = self._current_row_index()
        fld = self._active_formula_field()
        self.fx_tag.setText(f"fx  {FASTENER_FIELD_LABELS[fld]}:")
        self._syncing_formula_bar = True
        try:
            if 0 <= idx < len(self._rows):
                row = self._rows[idx]
                expr = row.formula_for(fld)
                if expr:
                    self.formula_edit.setText(f"={expr}")
                else:
                    self.formula_edit.setText(f"{float(getattr(row, fld)):g}")
                self.formula_edit.setEnabled(True)
                self.btn_apply_fx.setEnabled(True)
            else:
                self.formula_edit.setText("")
                self.formula_edit.setEnabled(False)
                self.btn_apply_fx.setEnabled(False)
        finally:
            self._syncing_formula_bar = False

    def _on_selection_changed(self) -> None:
        self._last_error = ""
        self._sync_formula_bar()
        self._sync_preview()
        is_dirty, _ = compute_rows_dirty_state(
            self._rows, self._saved_rows, panel_thickness=self._panel_thickness
        )
        self._update_status_line(is_dirty)

    def _on_current_cell_changed(self, _row: int, _col: int, _prev_r: int, _prev_c: int) -> None:
        self._sync_formula_bar()

    def _on_thickness_changed(self, val: float) -> None:
        self._panel_thickness = max(4.0, float(val))
        for row in self._rows:
            if row.formulas:
                recalculate_confirmat_row(row, panel_thickness=self._panel_thickness)
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _apply_formula_bar(self) -> None:
        if self._syncing_formula_bar:
            return
        idx = self._current_row_index()
        if idx < 0 or idx >= len(self._rows):
            return
        fld = self._active_formula_field()
        ok, err = apply_fastener_cell_input(
            self._rows[idx],
            fld,
            self.formula_edit.text(),
            panel_thickness=self._panel_thickness,
        )
        self._last_error = "" if ok else err
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _save_rows(self) -> None:
        save_confirmat_rows(self._rows, self._current_row_index())
        self._saved_rows = [r.clone() for r in self._rows]
        self._last_error = ""
        self._refresh_dirty_state()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        r = item.row()
        c = item.column()
        if r < 0 or r >= len(self._rows):
            return
        row = self._rows[r]
        text = item.text().strip()
        if c == 1:
            row.name = text or row.name
            self._last_error = ""
        elif c in _COL_TO_FIELD:
            fld = _COL_TO_FIELD[c]
            ok, err = apply_fastener_cell_input(
                row,
                fld,
                text,
                panel_thickness=self._panel_thickness,
            )
            self._last_error = "" if ok else err
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _add_row(self) -> None:
        n = len(self._rows) + 1
        self._rows.append(ConfirmatParams(f"Конфирмат {n}", 8.0, 5.0, 50.0, 0.0))
        new_idx = len(self._rows) - 1
        self._last_error = ""
        self._reload_table(select_row=new_idx)
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _delete_row(self) -> None:
        idx = self._current_row_index()
        if idx < 0 or not self._rows:
            return
        if len(self._rows) <= 1:
            return  # минимум одна строка
        del self._rows[idx]
        new_idx = min(idx, len(self._rows) - 1)
        self._last_error = ""
        self._reload_table(select_row=new_idx)
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _copy_row(self) -> None:
        idx = self._current_row_index()
        if idx < 0:
            return
        src = self._rows[idx]
        clone = src.clone()
        clone.name = f"{src.name} (копия)"
        self._rows.insert(idx + 1, clone)
        self._last_error = ""
        self._reload_table(select_row=idx + 1)
        self._refresh_dirty_state()
        self._sync_formula_bar()
        self._sync_preview()

    def _sync_preview(self) -> None:
        idx = self._current_row_index()
        if 0 <= idx < len(self._rows):
            self.preview.set_params(self._rows[idx], panel_thickness=self._panel_thickness)

    # ── accept ──────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        self._save_rows()
        data = self.selected_fastener()
        if data:
            self.fastener_accepted.emit(data)
        self.accept()

    def selected_fastener(self) -> dict[str, Any] | None:
        idx = self._current_row_index()
        if idx < 0 or idx >= len(self._rows):
            return None
        return self._rows[idx].to_selected_fastener_dict(panel_thickness=self._panel_thickness)

