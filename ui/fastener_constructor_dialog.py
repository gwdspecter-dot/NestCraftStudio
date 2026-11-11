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

from PyQt6.QtCore import Qt, QSize, QByteArray, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QBrush, QFont, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.fastener_constructor import (
    ConfirmatParams,
    load_confirmat_rows,
    save_confirmat_rows,
)
from ui.theme import current_theme

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
    """Подменяет палитру SVG под светлую / тёмную тему."""
    if for_dark:
        mapping = {
            # иконки типов (исходно светло-голубые)
            "#eef8ff": "#f0f9ff",
            "#b8e0ff": "#7dd3fc",
            "#7cc0ff": "#38bdf8",
            "#EEF8FF": "#f0f9ff",
            "#B8E0FF": "#7dd3fc",
            "#7CC0FF": "#38bdf8",
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
            # иконки: тёмные/контрастные на светлом фоне (все 3 тона читаемы)
            "#eef8ff": "#7dd3fc",
            "#b8e0ff": "#0369a1",
            "#7cc0ff": "#0c4a6e",
            "#EEF8FF": "#7dd3fc",
            "#B8E0FF": "#0369a1",
            "#7CC0FF": "#0c4a6e",
            # схемы: серо-синие тела вместо чёрных
            "#0F141C": "#334155",
            "#1E293B": "#475569",
            "#0f141c": "#334155",
            "#1e293b": "#475569",
            "#787880": "#64748b",
            # светлые обводки схем на белом фоне → темнее
            "#E2F1FF": "#64748b",
            "#e2f1ff": "#64748b",
            "#38BDF8": "#0284c7",
            "#38bdf8": "#0284c7",
            "#7DD3FC": "#0ea5e9",
            "#7dd3fc": "#0ea5e9",
        }
    for old, new in mapping.items():
        raw = raw.replace(old, new)
    return raw


def _themed_fastener_icon(svg_path: Path, size: int = 48) -> QIcon:
    """Рендерит SVG-иконку с перекраской под текущую тему."""
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
    # Подложка: на светлой теме заметнее, чтобы иконка не сливалась с фоном
    if c.name == "dark":
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.setPen(Qt.PenStyle.NoPen)
    else:
        painter.setBrush(QColor(224, 242, 254))  # #e0f2fe
        painter.setPen(QPen(QColor(0x7D, 0xD3, 0xFC), max(1, size // 48)))  # #7dd3fc
    margin = max(1, size // 16)
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, size // 8, size // 8)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)





class _SchemeWidget(QWidget):
    """Некликабельные схемы с размерными линиями (SVG group / group2)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._renderers: list[QSvgRenderer] = []
        for_dark = current_theme().name == "dark"
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
                self._renderers.append(r)

    def paintEvent(self, _event) -> None:  # noqa: N802
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
        # Камера: углы в градусах, zoom
        self._yaw = 35.0
        self._pitch = 25.0
        self._zoom = 1.0
        self._drag_pos: tuple[float, float] | None = None
        self._apply_theme_colors()

    def set_params(self, p: ConfirmatParams) -> None:
        self._params = p
        self.update()

    def _apply_theme_colors(self) -> None:
        """Фон и цвета модели под текущую тему (не всегда тёмный viewport)."""
        c = current_theme()
        if c.name == "dark":
            self._bg = QColor(c.bg_alt)
            self._panel = QColor(0x4A, 0xD0, 0x6E, 150)
            self._panel_edge = QColor(0x3A, 0xB0, 0x58)
            self._screw = QColor(0x6A, 0xE0, 0x8A)
            self._screw_edge = QColor(0x2E, 0x9E, 0x4F)
            self._dim = QColor(c.text_dim)
            self._hint = QColor(c.text_dim)
        else:
            self._bg = QColor(c.bg_panel)  # светлая панель
            self._panel = QColor(0x22, 0xA0, 0x55, 160)
            self._panel_edge = QColor(0x16, 0x7A, 0x3F)
            self._screw = QColor(0x18, 0x90, 0x4E)
            self._screw_edge = QColor(0x0F, 0x6B, 0x38)
            self._dim = QColor(c.text_dim)
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
        t = 16.0                 # толщина панелей, мм
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

        # Подписи
        p.setPen(self._dim)
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)
        label = f"D1={pr.d1:g} (пласть, сквозное)  D2={pr.d2:g} (торец, глухое)  H={pr.h:g}"
        if pr.h1:
            label += f"  H1={pr.h1:g}"
        p.drawText(12, 20, label)
        p.setPen(self._hint)
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(12, 36, f"Глубина в торец ≈ {edge_depth:.0f} мм · отверстие по центру торца")
        p.drawText(12, h - 12, "ЛКМ — вращать · колесо — масштаб · двойной клик — сброс")
        p.end()


class FastenerConstructorDialog(QDialog):
    """Окно конструктора параметрической фурнитуры."""

    fastener_accepted = pyqtSignal(dict)  # выбранный вариант → dict

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Конструктор параметрической фурнитуры")
        self.setMinimumSize(920, 560)
        self.resize(1000, 620)

        self._current_type = "confirmat"
        loaded_rows, initial_sel = load_confirmat_rows()
        self._rows: list[ConfirmatParams] = loaded_rows
        self._initial_selected_row: int = initial_sel
        self._type_buttons: dict[str, QToolButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Вкладки Параметрическая / Пользовательская ──────────────
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_parametric_page(), "Параметрическая")
        user_page = QWidget()
        user_l = QVBoxLayout(user_page)
        stub = QLabel("Пользовательская фурнитура — скоро.")
        stub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c = current_theme()
        stub.setStyleSheet(f"color: {c.text_dim}; font-size: 13px;")
        user_l.addWidget(stub)
        self.tabs.addTab(user_page, "Пользовательская")
        root.addWidget(self.tabs, 1)

        # ── OK / Cancel ─────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._select_type("confirmat")
        self._reload_table(select_row=self._initial_selected_row)
        self._sync_preview()

    # ── parametric page ─────────────────────────────────────────────

    def _build_parametric_page(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Левая колонка иконок (крупнее + перекраска под тему)
        left = QFrame()
        left.setObjectName("fastenerTypeBar")
        left.setFixedWidth(64)
        c = current_theme()
        left.setStyleSheet(
            f"""
            QFrame#fastenerTypeBar {{
                background: {c.bg_panel};
                border-right: 1px solid {c.border};
            }}
            QFrame#fastenerTypeBar QToolButton {{
                background: {c.bg_input};
                border: 1px solid {c.border};
                border-radius: 8px;
                padding: 4px;
            }}
            QFrame#fastenerTypeBar QToolButton:hover {{
                background: {c.select_bg};
                border-color: {c.accent_soft};
            }}
            QFrame#fastenerTypeBar QToolButton:checked {{
                background: {c.select_bg};
                border: 2px solid {c.accent};
            }}
            QFrame#fastenerTypeBar QToolButton:disabled {{
                background: {c.bg_panel};
                border-color: {c.border};
            }}
            """
        )
        left_l = QVBoxLayout(left)
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
            if icon_path.is_file():
                btn.setIcon(_themed_fastener_icon(icon_path, size=icon_px * 2))
            else:
                btn.setText(title[:1])
            btn.setFixedSize(52, 52)
            btn.setEnabled(type_id in _IMPLEMENTED_TYPES)
            if type_id not in _IMPLEMENTED_TYPES:
                btn.setToolTip(f"{title} (скоро)")
            btn.clicked.connect(lambda checked, t=type_id: self._select_type(t) if checked else None)
            left_l.addWidget(btn)
            self._type_buttons[type_id] = btn
        left_l.addStretch(1)
        outer.addWidget(left)

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
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._sync_preview)
        center_l.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Добавить +")
        self.btn_del = QPushButton("Удалить ×")
        self.btn_copy = QPushButton("Создать копию")
        self.btn_add.clicked.connect(self._add_row)
        self.btn_del.clicked.connect(self._delete_row)
        self.btn_copy.clicked.connect(self._copy_row)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch(1)
        center_l.addLayout(btn_row)

        mid_split.addWidget(center)

        # Правая колонка — 3D
        right = QFrame()
        right.setObjectName("previewPane")
        right.setStyleSheet(
            f"QFrame#previewPane {{ background: {c.bg_panel}; border-left: 1px solid {c.border}; }}"
        )
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)
        self.preview = ConfirmatPreview3D()
        right_l.addWidget(self.preview, 1)
        mid_split.addWidget(right)

        mid_split.setStretchFactor(0, 3)
        mid_split.setStretchFactor(1, 2)
        outer.addWidget(mid_split, 1)
        return page

    # ── type selection ──────────────────────────────────────────────

    def _select_type(self, type_id: str) -> None:
        if type_id not in _IMPLEMENTED_TYPES:
            return
        self._current_type = type_id
        for tid, btn in self._type_buttons.items():
            btn.setChecked(tid == type_id)
        self._sync_preview()

    # ── table ───────────────────────────────────────────────────────

    def _reload_table(self, select_row: int = 0) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, row in enumerate(self._rows):
            self.table.insertRow(i)
            num = QTableWidgetItem(str(i + 1))
            num.setFlags(num.flags() & ~Qt.ItemFlag.ItemIsEditable)
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, num)
            self.table.setItem(i, 1, QTableWidgetItem(row.name))
            for col, val in ((2, row.d1), (3, row.d2), (4, row.h), (5, row.h1)):
                it = QTableWidgetItem(f"{val:g}")
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, col, it)
        self.table.blockSignals(False)
        if self._rows:
            target = max(0, min(int(select_row), len(self._rows) - 1))
            self.table.selectRow(target)

    def _current_row_index(self) -> int:
        sel = self.table.selectionModel().selectedRows()
        if sel:
            return sel[0].row()
        return 0 if self._rows else -1

    def _persist_rows(self) -> None:
        save_confirmat_rows(self._rows, self._current_row_index())

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        r = item.row()
        c = item.column()
        if r < 0 or r >= len(self._rows):
            return
        row = self._rows[r]
        text = item.text().strip()
        if c == 1:
            row.name = text or row.name
        elif c in (2, 3, 4, 5):
            try:
                val = float(text.replace(",", "."))
            except ValueError:
                return
            if c == 2:
                row.d1 = max(0.1, val)
            elif c == 3:
                row.d2 = max(0.1, val)
            elif c == 4:
                row.h = max(1.0, val)
            elif c == 5:
                row.h1 = max(0.0, val)
        self._persist_rows()
        self._sync_preview()

    def _add_row(self) -> None:
        n = len(self._rows) + 1
        self._rows.append(ConfirmatParams(f"Конфирмат {n}", 8.0, 5.0, 50.0, 0.0))
        new_idx = len(self._rows) - 1
        self._reload_table(select_row=new_idx)
        self._persist_rows()
        self._sync_preview()

    def _delete_row(self) -> None:
        idx = self._current_row_index()
        if idx < 0 or not self._rows:
            return
        if len(self._rows) <= 1:
            return  # минимум одна строка
        del self._rows[idx]
        new_idx = min(idx, len(self._rows) - 1)
        self._reload_table(select_row=new_idx)
        self._persist_rows()
        self._sync_preview()

    def _copy_row(self) -> None:
        idx = self._current_row_index()
        if idx < 0:
            return
        src = self._rows[idx]
        clone = src.clone()
        clone.name = f"{src.name} (копия)"
        self._rows.insert(idx + 1, clone)
        self._reload_table(select_row=idx + 1)
        self._persist_rows()
        self._sync_preview()

    def _sync_preview(self) -> None:
        idx = self._current_row_index()
        if 0 <= idx < len(self._rows):
            self.preview.set_params(self._rows[idx])

    # ── accept ──────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        self._persist_rows()
        data = self.selected_fastener()
        if data:
            self.fastener_accepted.emit(data)
        self.accept()

    def selected_fastener(self) -> dict[str, Any] | None:
        idx = self._current_row_index()
        if idx < 0 or idx >= len(self._rows):
            return None
        return self._rows[idx].to_selected_fastener_dict()
