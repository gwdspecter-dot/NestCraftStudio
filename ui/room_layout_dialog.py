"""Окно планировки помещения (2D-план, стены, неровности, проёмы, препятствия) и диалоги режима помещения.

Оформление полностью подчиняется `ui/theme.py` (`current_theme()`), без зашитых цветов.
Иконки загружаются из `ui/icons/room_*.svg` и перекрашиваются под текущую светлую/тёмную тему.
"""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.logging_setup import get_logger
from core.room_geometry import (
    WallGapReport,
    door_swing_geometry_xz,
    find_nearest_wall_for_product,
    measure_product_wall_gaps,
    obstacle_world_corners_xz,
)
from models.room_frame import (
    DEFAULT_ROOM_DEPTH_MM,
    DEFAULT_ROOM_HEIGHT_MM,
    DEFAULT_ROOM_WIDTH_MM,
    DEFAULT_WALL_THICKNESS_MM,
    MAX_WALL_DEVIATION_MM,
    MAX_WALL_HEIGHT_MM,
    MAX_WALL_LENGTH_MM,
    MAX_WALL_THICKNESS_MM,
    MIN_WALL_HEIGHT_MM,
    MIN_WALL_LENGTH_MM,
    MIN_WALL_THICKNESS_MM,
    OBSTACLE_KIND_LABELS,
    OBSTACLE_KINDS,
    OPENING_KIND_LABELS,
    OPENING_KINDS,
    SWING_DIRECTION_LABELS,
    SWING_DIRECTIONS,
    PlacedProduct,
    RoomFrame,
    RoomObstacle,
    RoomWorkspace,
    WallDeviationStation,
    WallOpening,
)
from ui.dialogs import SmartDoubleSpinBox
from ui.theme import current_theme

_log = get_logger("room_layout_dialog")
_ICONS_DIR = Path(__file__).resolve().parent / "icons"


def render_room_svg_icon(icon_name: str, color_hex: str | None = None, size: int = 18) -> QIcon:
    """Рендерит тематическую SVG-иконку помещения (`currentColor` → цвет темы, HiDPI)."""
    svg_path = _ICONS_DIR / icon_name
    if not svg_path.is_file():
        return QIcon()
    color = color_hex or current_theme().text
    try:
        raw = svg_path.read_text(encoding="utf-8")
        tinted = raw.replace("currentColor", color).encode("utf-8")
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
        _log.exception("Не удалось отрендерить SVG-иконку помещения %s", svg_path)
        return QIcon(str(svg_path))


def _make_spin(
    value: float,
    min_val: float,
    max_val: float,
    *,
    step: float = 10.0,
    decimals: int = 1,
    suffix: str = " мм",
) -> SmartDoubleSpinBox:
    sb = SmartDoubleSpinBox()
    sb.setRange(float(min_val), float(max_val))
    sb.setDecimals(int(decimals))
    sb.setSingleStep(float(step))
    sb.setSuffix(suffix)
    sb.setValue(float(value))
    return sb


# ── Интерактивный 2D-холст планировки помещения ───────────────


class RoomPlan2DCanvas(QWidget):
    """Интерактивный 2D-план помещения в плоскости XZ с перетаскиванием узлов и рисованием контура."""

    wall_selected = pyqtSignal(str)
    vertex_selected = pyqtSignal(str)
    vertex_moved_finished = pyqtSignal(str, float, float)
    polygon_drawn = pyqtSignal(list)
    cursor_coords_changed = pyqtSignal(float, float)

    def __init__(self, room: RoomFrame, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 420)
        self.setMouseTracking(True)
        self.room: RoomFrame = room
        self.selected_wall_uid: str = room.walls[0].uid if room.walls else ""
        self.selected_vertex_uid: str = ""
        self.selected_obstacle_uid: str = ""

        # Камера 2D-вида: центр мировых координат (cx, cz) и масштаб (пикселей на мм)
        self._cam_x: float = 1800.0
        self._cam_z: float = 1500.0
        self._scale: float = 0.12  # px / mm
        self._grid_snap_mm: float = 10.0

        self._dragging_vertex_uid: str = ""
        self._drag_origin_xz: tuple[float, float] | None = None
        self._panning: bool = False
        self._pan_last_pos: QPointF | None = None

        # Режим ручного рисования произвольного замкнутого контура по точкам
        self.draw_mode: bool = False
        self._draft_points: list[tuple[float, float]] = []
        self._hover_world: tuple[float, float] | None = None

        self.fit_to_room()

    def set_room(self, room: RoomFrame, *, keep_view: bool = True) -> None:
        self.room = room
        if self.selected_wall_uid and room.get_wall(self.selected_wall_uid) is None:
            self.selected_wall_uid = room.walls[0].uid if room.walls else ""
        if self.selected_vertex_uid and room.get_vertex(self.selected_vertex_uid) is None:
            self.selected_vertex_uid = ""
        if not keep_view:
            self.fit_to_room()
        self.update()

    def set_draw_mode(self, enabled: bool) -> None:
        self.draw_mode = bool(enabled)
        self._draft_points.clear()
        self.setCursor(Qt.CursorShape.CrossCursor if self.draw_mode else Qt.CursorShape.ArrowCursor)
        self.update()

    def fit_to_room(self) -> None:
        (x0, _y0, z0), (x1, _y1, z1) = self.room.world_aabb()
        w_mm = max(500.0, x1 - x0)
        d_mm = max(500.0, z1 - z0)
        self._cam_x = 0.5 * (x0 + x1)
        self._cam_z = 0.5 * (z0 + z1)
        vw = max(200.0, float(self.width() or 540))
        vh = max(200.0, float(self.height() or 460))
        self._scale = min((vw * 0.72) / w_mm, (vh * 0.72) / d_mm)
        self._scale = max(0.01, min(2.0, self._scale))
        self.update()

    def _w2s(self, wx: float, wz: float) -> QPointF:
        cx = 0.5 * float(self.width())
        cy = 0.5 * float(self.height())
        sx = cx + (wx - self._cam_x) * self._scale
        sy = cy + (wz - self._cam_z) * self._scale
        return QPointF(sx, sy)

    def _s2w(self, pos: QPointF) -> tuple[float, float]:
        cx = 0.5 * float(self.width())
        cy = 0.5 * float(self.height())
        wx = self._cam_x + (pos.x() - cx) / max(self._scale, 1e-6)
        wz = self._cam_z + (pos.y() - cy) / max(self._scale, 1e-6)
        return (wx, wz)

    def _snap_world(self, wx: float, wz: float, *, modifiers: Qt.KeyboardModifier) -> tuple[float, float]:
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return (round(wx, 1), round(wz, 1))
        step = self._grid_snap_mm
        return (round(wx / step) * step, round(wz / step) * step)

    def _pick_vertex(self, pos: QPointF, radius_px: float = 11.0) -> str:
        best_uid = ""
        best_d = radius_px
        for v in self.room.vertices:
            sp = self._w2s(v.x, v.z)
            d = math.hypot(sp.x() - pos.x(), sp.y() - pos.y())
            if d < best_d:
                best_d = d
                best_uid = v.uid
        return best_uid

    def _pick_wall(self, pos: QPointF, max_dist_px: float = 12.0) -> str:
        best_uid = ""
        best_d = max_dist_px
        for w in self.room.walls:
            info = self.room.wall_geometry(w)
            a = self._w2s(*info.start_xz)
            b = self._w2s(*info.end_xz)
            vx, vy = b.x() - a.x(), b.y() - a.y()
            l2 = vx * vx + vy * vy
            if l2 < 1e-6:
                continue
            t = max(0.0, min(1.0, ((pos.x() - a.x()) * vx + (pos.y() - a.y()) * vy) / l2))
            qx, qy = a.x() + t * vx, a.y() + t * vy
            d = math.hypot(pos.x() - qx, pos.y() - qy)
            if d < best_d:
                best_d = d
                best_uid = w.uid
        return best_uid

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        pos = event.position()
        before = self._s2w(pos)
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        self._scale = max(0.008, min(3.0, self._scale * factor))
        after = self._s2w(pos)
        self._cam_x += before[0] - after[0]
        self._cam_z += before[1] - after[1]
        self.update()

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            if self.draw_mode and event.button() == Qt.MouseButton.RightButton and self._draft_points:
                self._draft_points.pop()
                self.update()
                return
            self._panning = True
            self._pan_last_pos = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.draw_mode:
            wx, wz = self._snap_world(*self._s2w(pos), modifiers=event.modifiers())
            # Если клик рядом с первой точкой при >=3 вершинах — замыкаем контур
            if len(self._draft_points) >= 3:
                first_sp = self._w2s(*self._draft_points[0])
                if math.hypot(first_sp.x() - pos.x(), first_sp.y() - pos.y()) <= 14.0:
                    pts = list(self._draft_points)
                    self._draft_points.clear()
                    self.draw_mode = False
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.polygon_drawn.emit(pts)
                    self.update()
                    return
            if self._draft_points:
                lx, lz = self._draft_points[-1]
                if math.hypot(wx - lx, wz - lz) < MIN_WALL_LENGTH_MM:
                    return
            self._draft_points.append((wx, wz))
            self.update()
            return

        v_uid = self._pick_vertex(pos)
        if v_uid:
            v = self.room.get_vertex(v_uid)
            if v is not None:
                self.selected_vertex_uid = v_uid
                self._dragging_vertex_uid = v_uid
                self._drag_origin_xz = (v.x, v.z)
                self.vertex_selected.emit(v_uid)
                self.update()
                return

        w_uid = self._pick_wall(pos)
        if w_uid:
            self.selected_wall_uid = w_uid
            self.selected_vertex_uid = ""
            self.wall_selected.emit(w_uid)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        wx, wz = self._s2w(pos)
        self._hover_world = self._snap_world(wx, wz, modifiers=event.modifiers())
        self.cursor_coords_changed.emit(self._hover_world[0], self._hover_world[1])

        if self._panning and self._pan_last_pos is not None:
            dx = (pos.x() - self._pan_last_pos.x()) / max(self._scale, 1e-6)
            dy = (pos.y() - self._pan_last_pos.y()) / max(self._scale, 1e-6)
            self._cam_x -= dx
            self._cam_z -= dy
            self._pan_last_pos = pos
            self.update()
            return

        if self._dragging_vertex_uid:
            nx, nz = self._hover_world
            try:
                self.room.move_vertex(self._dragging_vertex_uid, nx, nz)
            except ValueError as exc:
                _log.debug("Позиция вершины при перетаскивании отклонена: %s", exc)
            self.update()
            return

        if self.draw_mode:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self._pan_last_pos = None
            self.setCursor(Qt.CursorShape.CrossCursor if self.draw_mode else Qt.CursorShape.ArrowCursor)
            return
        if self._dragging_vertex_uid:
            uid = self._dragging_vertex_uid
            self._dragging_vertex_uid = ""
            v = self.room.get_vertex(uid)
            if v is not None and self._drag_origin_xz is not None:
                ox, oz = self._drag_origin_xz
                if math.hypot(v.x - ox, v.z - oz) > 0.1:
                    self.vertex_moved_finished.emit(uid, v.x, v.z)
            self._drag_origin_xz = None
            self.update()

    def paintEvent(self, event) -> None:
        t = current_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(t.bg_input))

        # 1. Координатная сетка
        self._draw_grid(p, t)

        # 2. Внутренний пол помещения
        poly_pts = self.room.ordered_polygon_xz()
        if len(poly_pts) >= 3:
            qpoly = QPolygonF([self._w2s(x, z) for x, z in poly_pts])
            floor_col = QColor(t.bg_panel)
            floor_col.setAlpha(185)
            p.setBrush(QBrush(floor_col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(qpoly)

        # 3. Препятствия
        for obs in self.room.obstacles:
            if not obs.visible:
                continue
            if obs.clearance_mm > 0.5:
                clr_poly = QPolygonF([self._w2s(x, z) for x, z in obstacle_world_corners_xz(obs, inflate_mm=obs.clearance_mm)])
                clr_pen = QPen(QColor(t.warning), 1.2, Qt.PenStyle.DashLine)
                p.setPen(clr_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(clr_poly)
            obs_poly = QPolygonF([self._w2s(x, z) for x, z in obstacle_world_corners_xz(obs)])
            obs_fill = QColor(t.warning)
            obs_fill.setAlpha(70)
            p.setBrush(QBrush(obs_fill))
            p.setPen(QPen(QColor(t.warning), 1.6))
            p.drawPolygon(obs_poly)

        # 4. Стены, толщина, фактическая неровность и проёмы
        font_dim = QFont(self.font())
        font_dim.setPointSize(8)
        font_dim.setBold(True)
        p.setFont(font_dim)

        for w in self.room.walls:
            info = self.room.wall_geometry(w)
            x0, z0 = info.start_xz
            x1, z1 = info.end_xz
            ox, oz = info.outward_normal_xz
            tx, tz = info.tangent_xz
            nx, nz = info.inward_normal_xz
            thick = float(w.thickness_mm)

            is_sel = w.uid == self.selected_wall_uid
            shell = QPolygonF([
                self._w2s(x0, z0),
                self._w2s(x1, z1),
                self._w2s(x1 + ox * thick, z1 + oz * thick),
                self._w2s(x0 + ox * thick, z0 + oz * thick),
            ])
            wall_fill = QColor(t.accent if is_sel else t.border)
            wall_fill.setAlpha(110 if is_sel else 135)
            p.setBrush(QBrush(wall_fill))
            p.setPen(QPen(QColor(t.accent if is_sel else t.text_dim), 2.0 if is_sel else 1.2))
            p.drawPolygon(shell)

            # Если есть контрольные станции неровности — рисуем реальную искривлённую линию внутренней грани
            if w.deviation_stations:
                steps = max(12, int(math.ceil(info.length_mm / 150.0)))
                path = QPainterPath()
                mid_h = 0.5 * float(w.height_mm)
                for k in range(steps + 1):
                    s_val = info.length_mm * (k / steps)
                    off = self.room.evaluate_wall_offset(w, s_val, mid_h)
                    sp = self._w2s(x0 + tx * s_val + nx * off, z0 + tz * s_val + nz * off)
                    if k == 0:
                        path.moveTo(sp)
                    else:
                        path.lineTo(sp)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(t.warning), 2.0))
                p.drawPath(path)

            # Проёмы на стене
            for op in w.openings:
                s0 = float(op.offset_s_mm)
                s1 = s0 + float(op.width_mm)
                op_poly = QPolygonF([
                    self._w2s(x0 + tx * s0, z0 + tz * s0),
                    self._w2s(x0 + tx * s1, z0 + tz * s1),
                    self._w2s(x0 + tx * s1 + ox * thick, z0 + tz * s1 + oz * thick),
                    self._w2s(x0 + tx * s0 + ox * thick, z0 + tz * s0 + oz * thick),
                ])
                p.setBrush(QBrush(QColor(t.bg_input)))
                op_col = QColor(t.heading if op.kind == "window" else (t.accent_soft if op.kind == "door" else t.text_dim))
                p.setPen(QPen(op_col, 1.5))
                p.drawPolygon(op_poly)
                if op.kind == "door" and op.swing_angle_deg > 1.0:
                    sw = door_swing_geometry_xz(self.room, w, op)
                    h_pt = self._w2s(*sw["hinge_xz"])
                    o_pt = self._w2s(*sw["open_tip_xz"])
                    p.setPen(QPen(op_col, 1.8))
                    p.drawLine(h_pt, o_pt)
                    arc_path = QPainterPath()
                    for idx_a, ap in enumerate(sw["arc_points_xz"]):
                        sp_a = self._w2s(*ap)
                        if idx_a == 0:
                            arc_path.moveTo(sp_a)
                        else:
                            arc_path.lineTo(sp_a)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(op_col, 1.2, Qt.PenStyle.DashLine))
                    p.drawPath(arc_path)

            # Подпись фактической длины стены
            mid_x = 0.5 * (x0 + x1) + ox * (thick + 140.0)
            mid_z = 0.5 * (z0 + z1) + oz * (thick + 140.0)
            sp_mid = self._w2s(mid_x, mid_z)
            lbl = f"{info.length_mm:.0f} мм"
            p.setPen(QColor(t.accent_soft if is_sel else t.text))
            p.drawText(QRectF(sp_mid.x() - 48, sp_mid.y() - 10, 96, 20), Qt.AlignmentFlag.AlignCenter, lbl)

        # 5. Узлы и подписи фактических углов (выделяем выбранный угол и непрямые углы != 90°)
        for idx, v in enumerate(self.room.vertices, start=1):
            sp = self._w2s(v.x, v.z)
            is_v_sel = v.uid == self.selected_vertex_uid
            if is_v_sel:
                halo = QColor(t.accent)
                halo.setAlpha(65)
                p.setBrush(QBrush(halo))
                p.setPen(QPen(QColor(t.accent_soft), 1.4))
                p.drawEllipse(sp, 11.0, 11.0)
            r = 6.5 if is_v_sel else 4.8
            p.setBrush(QBrush(QColor(t.accent if is_v_sel else t.bg_panel)))
            p.setPen(QPen(QColor(t.accent_soft if is_v_sel else t.text), 1.8))
            p.drawEllipse(sp, r, r)

            if self.room.has_corner_angle(v.uid):
                ang = self.room.interior_angle_at_vertex(v.uid)
                is_non_90 = abs(ang - 90.0) > 0.2
                p.setPen(QColor(t.accent_soft if is_v_sel else (t.warning if is_non_90 else t.text_dim)))
                p.drawText(
                    QRectF(sp.x() + 9, sp.y() - 18, 66, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{ang:.1f}°",
                )

        # 6. Черновик ручного контура (в режиме рисования по точкам)
        if self.draw_mode and self._draft_points:
            p.setPen(QPen(QColor(t.accent_soft), 2.0))
            for i in range(len(self._draft_points) - 1):
                p.drawLine(self._w2s(*self._draft_points[i]), self._w2s(*self._draft_points[i + 1]))
            if self._hover_world is not None:
                last_pt = self._draft_points[-1]
                p.setPen(QPen(QColor(t.accent_soft), 1.5, Qt.PenStyle.DashLine))
                p.drawLine(self._w2s(*last_pt), self._w2s(*self._hover_world))
                seg_l = math.hypot(self._hover_world[0] - last_pt[0], self._hover_world[1] - last_pt[1])
                mp = self._w2s(0.5 * (last_pt[0] + self._hover_world[0]), 0.5 * (last_pt[1] + self._hover_world[1]))
                p.setPen(QColor(t.text_title))
                p.drawText(QRectF(mp.x() - 45, mp.y() - 20, 90, 18), Qt.AlignmentFlag.AlignCenter, f"{seg_l:.0f} мм")
            for idx_d, dp in enumerate(self._draft_points):
                sp_d = self._w2s(*dp)
                p.setBrush(QBrush(QColor(t.success if idx_d == 0 else t.accent)))
                p.setPen(QPen(QColor(t.text_title), 1.4))
                p.drawEllipse(sp_d, 5.5 if idx_d == 0 else 4.2, 5.5 if idx_d == 0 else 4.2)

        # Рамка области холста
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(t.border), 1.0))
        p.drawRect(QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0))

    def _draw_grid(self, p: QPainter, t) -> None:
        step = 500.0
        if step * self._scale < 22.0:
            step = 1000.0
        elif step * self._scale > 120.0:
            step = 100.0
        tl = self._s2w(QPointF(0.0, 0.0))
        br = self._s2w(QPointF(float(self.width()), float(self.height())))
        x_start = math.floor(min(tl[0], br[0]) / step) * step
        x_end = math.ceil(max(tl[0], br[0]) / step) * step
        z_start = math.floor(min(tl[1], br[1]) / step) * step
        z_end = math.ceil(max(tl[1], br[1]) / step) * step

        grid_col = QColor(t.border)
        grid_col.setAlpha(95)
        p.setPen(QPen(grid_col, 1.0))
        x = x_start
        while x <= x_end:
            sx = self._w2s(x, 0.0).x()
            p.drawLine(QPointF(sx, 0.0), QPointF(sx, float(self.height())))
            x += step
        z = z_start
        while z <= z_end:
            sy = self._w2s(0.0, z).y()
            p.drawLine(QPointF(0.0, sy), QPointF(float(self.width()), sy))
            z += step

        # Оси начала координат (0, 0)
        o = self._w2s(0.0, 0.0)
        p.setPen(QPen(QColor(t.error), 1.2))
        p.drawLine(o, QPointF(o.x() + 36.0, o.y()))
        p.setPen(QPen(QColor(t.accent_soft), 1.2))
        p.drawLine(o, QPointF(o.x(), o.y() + 36.0))


# ── Главный диалог «Планировка помещения» ─────────────────────


class RoomLayoutDialog(QDialog):
    """Окно проектирования габаритной рамки помещения перед передачей в основную 3D-среду."""

    def __init__(
        self,
        room_frame: RoomFrame | None = None,
        parent=None,
        *,
        finish_button_text: str = "Закончить планировку",
    ):
        super().__init__(parent)
        self.setWindowTitle("Планировка помещения")
        self.setMinimumSize(980, 650)
        self.resize(1120, 720)

        self._room: RoomFrame = (
            room_frame.clone()
            if isinstance(room_frame, RoomFrame)
            else RoomFrame.create_rectangular()
        )
        self._undo_history: list[RoomFrame] = []
        self._redo_history: list[RoomFrame] = []
        self._syncing_ui: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Верхняя панель быстрых инструментов
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self.btn_draw_poly = QPushButton("Рисовать контур по точкам", self)
        self.btn_draw_poly.setCheckable(True)
        self.btn_draw_poly.toggled.connect(self._on_toggle_draw_mode)
        top_bar.addWidget(self.btn_draw_poly)

        self.btn_fit = QPushButton("По размеру окна", self)
        self.btn_fit.clicked.connect(lambda: self.canvas.fit_to_room())
        top_bar.addWidget(self.btn_fit)

        self.btn_undo = QPushButton("Отменить", self)
        self.btn_undo.clicked.connect(self._undo)
        top_bar.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("Повторить", self)
        self.btn_redo.clicked.connect(self._redo)
        top_bar.addWidget(self.btn_redo)

        top_bar.addStretch(1)
        self._coords_label = QLabel("X: 0 мм · Z: 0 мм", self)
        top_bar.addWidget(self._coords_label)
        root.addLayout(top_bar)

        # Центральный сплиттер: слева 2D-план, справа редактор параметров
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.canvas = RoomPlan2DCanvas(self._room, splitter)
        self.canvas.wall_selected.connect(self._on_canvas_wall_selected)
        self.canvas.vertex_selected.connect(self._on_canvas_vertex_selected)
        self.canvas.vertex_moved_finished.connect(self._on_canvas_vertex_moved)
        self.canvas.polygon_drawn.connect(self._on_canvas_polygon_drawn)
        self.canvas.cursor_coords_changed.connect(self._on_cursor_coords)
        splitter.addWidget(self.canvas)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(8)

        self.inspector_tabs = QTabWidget(right_panel)
        self.inspector_tabs.addTab(self._build_walls_tab(), "Стены")
        self.inspector_tabs.addTab(self._build_deviations_tab(), "Неровности")
        self.inspector_tabs.addTab(self._build_openings_tab(), "Проёмы")
        self.inspector_tabs.addTab(self._build_obstacles_tab(), "Препятствия")
        right_layout.addWidget(self.inspector_tabs)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 440])
        root.addWidget(splitter, 1)

        # Нижняя строка: сводка + «Закончить планировку» / «Отмена»
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)
        self._summary_label = QLabel("", self)
        bottom_bar.addWidget(self._summary_label, 1)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(self.btn_cancel)

        self.btn_finish = QPushButton(finish_button_text, self)
        self.btn_finish.clicked.connect(self._on_finish)
        bottom_bar.addWidget(self.btn_finish)
        root.addLayout(bottom_bar)

        # Отключаем autoDefault у всех кнопок, чтобы Enter в полях ввода применял размер, а не закрывал окно
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(False)
            btn.setDefault(False)

        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self._redo)

        self.refresh_theme()
        self._reload_all_views(select_first_wall=True)

    def keyPressEvent(self, event) -> None:
        # Не позволяем QDialog закрывать окно по Enter — Enter применяет размеры в полях ввода
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _bind_enter_apply(widget, callback) -> None:
        """Привязывает применение значения по нажатию Enter в поле ввода (без кнопки «Применить»)."""
        if hasattr(widget, "lineEdit") and callable(widget.lineEdit):
            le = widget.lineEdit()
            if le is not None:
                le.returnPressed.connect(callback)
        elif hasattr(widget, "returnPressed"):
            widget.returnPressed.connect(callback)

    # ── Вкладки инспектора ────────────────────────────────────

    def _build_walls_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Базовое прямоугольное помещение
        rect_hdr = QLabel("Быстрое построение прямоугольника", w)
        self._lbl_rect_hdr = rect_hdr
        lay.addWidget(rect_hdr)

        rect_row = QHBoxLayout()
        self.rect_w_spin = _make_spin(DEFAULT_ROOM_WIDTH_MM, MIN_WALL_LENGTH_MM, MAX_WALL_LENGTH_MM, step=100.0)
        self.rect_d_spin = _make_spin(DEFAULT_ROOM_DEPTH_MM, MIN_WALL_LENGTH_MM, MAX_WALL_LENGTH_MM, step=100.0)
        self.rect_h_spin = _make_spin(self._room.ceiling_height_mm, MIN_WALL_HEIGHT_MM, MAX_WALL_HEIGHT_MM, step=50.0)
        for sp in (self.rect_w_spin, self.rect_d_spin, self.rect_h_spin):
            self._bind_enter_apply(sp, self._on_create_rect)
        rect_row.addWidget(QLabel("Ш:"))
        rect_row.addWidget(self.rect_w_spin)
        rect_row.addWidget(QLabel("Г:"))
        rect_row.addWidget(self.rect_d_spin)
        rect_row.addWidget(QLabel("В:"))
        rect_row.addWidget(self.rect_h_spin)
        lay.addLayout(rect_row)

        btn_rect = QPushButton("Создать прямоугольный контур", w)
        btn_rect.clicked.connect(self._on_create_rect)
        lay.addWidget(btn_rect)

        # Список стен
        self.walls_list = QListWidget(w)
        self.walls_list.setMaximumHeight(115)
        self.walls_list.currentRowChanged.connect(self._on_wall_list_row_changed)
        lay.addWidget(self.walls_list)

        # Параметры выбранной стены (применение по Enter)
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self.wall_name_edit = QLineEdit(w)
        self.wall_len_spin = _make_spin(3000.0, MIN_WALL_LENGTH_MM, MAX_WALL_LENGTH_MM, step=10.0)
        self.wall_thick_spin = _make_spin(DEFAULT_WALL_THICKNESS_MM, MIN_WALL_THICKNESS_MM, MAX_WALL_THICKNESS_MM, step=10.0)
        self.wall_height_spin = _make_spin(DEFAULT_ROOM_HEIGHT_MM, MIN_WALL_HEIGHT_MM, MAX_WALL_HEIGHT_MM, step=50.0)
        self.wall_visible_cb = QCheckBox("Отображать стену в 3D", w)
        self.wall_visible_cb.setChecked(True)

        self._bind_enter_apply(self.wall_name_edit, self._on_apply_wall)
        for sp in (self.wall_len_spin, self.wall_thick_spin, self.wall_height_spin):
            self._bind_enter_apply(sp, self._on_apply_wall)
        self.wall_visible_cb.toggled.connect(self._on_wall_visible_toggled)

        form.addRow("Название:", self.wall_name_edit)
        form.addRow("Длина стены:", self.wall_len_spin)
        form.addRow("Толщина стены:", self.wall_thick_spin)
        form.addRow("Высота стены:", self.wall_height_spin)
        form.addRow("", self.wall_visible_cb)
        lay.addLayout(form)

        # Выбранный угол контура (клик по точке угла на плане + ввод градусов по Enter)
        self._lbl_corner_hdr = QLabel("Выбранный угол контура", w)
        lay.addWidget(self._lbl_corner_hdr)
        corner_form = QFormLayout()
        corner_form.setHorizontalSpacing(10)
        corner_form.setVerticalSpacing(6)
        self.corner_info_label = QLabel("Нажмите на точку угла на плане", w)
        self.vertex_angle_spin = _make_spin(90.0, 15.0, 345.0, step=0.5, decimals=1, suffix=" °")
        self.vertex_angle_spin.setEnabled(False)
        self._bind_enter_apply(self.vertex_angle_spin, self._on_apply_vertex_angle)
        corner_form.addRow("Точка угла:", self.corner_info_label)
        corner_form.addRow("Угол (Enter):", self.vertex_angle_spin)
        lay.addLayout(corner_form)

        self._wall_enter_hint = QLabel("Размеры стены и выбранный угол применяются по нажатию Enter.", w)
        self._wall_enter_hint.setWordWrap(True)
        lay.addWidget(self._wall_enter_hint)

        # Операции с контуром: разбиение, ниша/выступ, удаление стены (разомкнуть), удаление узла
        ops_row = QHBoxLayout()
        self.btn_split_wall = QPushButton("Разбить стену", w)
        self.btn_split_wall.clicked.connect(self._on_split_wall)
        self.btn_niche = QPushButton("Ниша / выступ…", w)
        self.btn_niche.clicked.connect(self._on_insert_niche)
        ops_row.addWidget(self.btn_split_wall)
        ops_row.addWidget(self.btn_niche)
        lay.addLayout(ops_row)

        ops_row2 = QHBoxLayout()
        self.btn_del_wall = QPushButton("Удалить стену", w)
        self.btn_del_wall.setToolTip("Удаляет выбранную стену и оставляет контур незамкнутым")
        self.btn_del_wall.clicked.connect(self._on_delete_wall)
        self.btn_del_vertex = QPushButton("Удалить узел", w)
        self.btn_del_vertex.clicked.connect(self._on_delete_selected_or_end_vertex)
        ops_row2.addWidget(self.btn_del_wall)
        ops_row2.addWidget(self.btn_del_vertex)
        lay.addLayout(ops_row2)

        # Высота потолка / отметка пола (по Enter)
        room_form = QFormLayout()
        self.ceiling_spin = _make_spin(self._room.ceiling_height_mm, MIN_WALL_HEIGHT_MM, MAX_WALL_HEIGHT_MM, step=50.0)
        self.floor_elev_spin = _make_spin(self._room.floor_elevation_mm, -5000.0, 5000.0, step=10.0)
        self._bind_enter_apply(self.ceiling_spin, self._on_room_levels_changed)
        self._bind_enter_apply(self.floor_elev_spin, self._on_room_levels_changed)
        room_form.addRow("Высота потолка:", self.ceiling_spin)
        room_form.addRow("Отметка пола:", self.floor_elev_spin)
        lay.addLayout(room_form)
        lay.addStretch(1)
        return w

    def _build_deviations_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._dev_hint = QLabel(
            "Контрольные точки замера неровности выбранной стены (завал от вертикали, "
            "выпуклость «+» внутрь комнаты, вогнутость «−» наружу). Поверхность строится "
            "в 3D и участвует в замере зазоров до мебели.",
            w,
        )
        self._dev_hint.setWordWrap(True)
        lay.addWidget(self._dev_hint)

        self.dev_table = QTableWidget(0, 3, w)
        self.dev_table.setHorizontalHeaderLabels(["Вдоль стены s, мм", "Высота H, мм", "Отклонение, мм"])
        self.dev_table.verticalHeader().setVisible(False)
        self.dev_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.dev_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.dev_table, 1)

        form = QFormLayout()
        self.dev_s_spin = _make_spin(0.0, 0.0, MAX_WALL_LENGTH_MM, step=50.0)
        self.dev_h_spin = _make_spin(1200.0, 0.0, MAX_WALL_HEIGHT_MM, step=100.0)
        self.dev_off_spin = _make_spin(12.0, -MAX_WALL_DEVIATION_MM, MAX_WALL_DEVIATION_MM, step=1.0)
        for sp in (self.dev_s_spin, self.dev_h_spin, self.dev_off_spin):
            self._bind_enter_apply(sp, self._on_add_deviation)
        form.addRow("Позиция вдоль стены (s):", self.dev_s_spin)
        form.addRow("Высота замера от пола:", self.dev_h_spin)
        form.addRow("Смещение (+ внутрь):", self.dev_off_spin)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.btn_add_dev = QPushButton("Добавить замер", w)
        self.btn_add_dev.clicked.connect(self._on_add_deviation)
        self.btn_del_dev = QPushButton("Удалить выбранный", w)
        self.btn_del_dev.clicked.connect(self._on_remove_deviation)
        row.addWidget(self.btn_add_dev)
        row.addWidget(self.btn_del_dev)
        lay.addLayout(row)

        preset_row = QHBoxLayout()
        btn_tilt = QPushButton("Пресет: завал верха +15 мм", w)
        btn_tilt.clicked.connect(self._on_preset_tilt)
        btn_bow = QPushButton("Пресет: выпуклость +15 мм", w)
        btn_bow.clicked.connect(self._on_preset_bow)
        preset_row.addWidget(btn_tilt)
        preset_row.addWidget(btn_bow)
        lay.addLayout(preset_row)
        return w

    def _build_openings_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.openings_list = QListWidget(w)
        self.openings_list.setMaximumHeight(130)
        self.openings_list.currentRowChanged.connect(self._on_opening_list_row_changed)
        lay.addWidget(self.openings_list)

        form = QFormLayout()
        self.op_kind_combo = QComboBox(w)
        for k in OPENING_KINDS:
            self.op_kind_combo.addItem(OPENING_KIND_LABELS[k], k)
        self.op_kind_combo.currentIndexChanged.connect(self._on_opening_kind_changed)

        self.op_name_edit = QLineEdit("Дверь", w)
        self.op_s_spin = _make_spin(500.0, 0.0, MAX_WALL_LENGTH_MM, step=50.0)
        self.op_w_spin = _make_spin(900.0, 50.0, 10000.0, step=50.0)
        self.op_h_spin = _make_spin(2050.0, 50.0, 10000.0, step=50.0)
        self.op_sill_spin = _make_spin(0.0, 0.0, 10000.0, step=50.0)
        self.op_swing_combo = QComboBox(w)
        for sd in SWING_DIRECTIONS:
            self.op_swing_combo.addItem(SWING_DIRECTION_LABELS[sd], sd)
        self.op_angle_spin = _make_spin(90.0, 0.0, 180.0, step=15.0, decimals=0, suffix=" °")
        self.op_sill_depth_spin = _make_spin(60.0, 0.0, 500.0, step=10.0)

        for fld in (
            self.op_name_edit,
            self.op_s_spin,
            self.op_w_spin,
            self.op_h_spin,
            self.op_sill_spin,
            self.op_angle_spin,
            self.op_sill_depth_spin,
        ):
            self._bind_enter_apply(fld, self._on_apply_or_add_opening)

        form.addRow("Тип проёма:", self.op_kind_combo)
        form.addRow("Наименование:", self.op_name_edit)
        form.addRow("Отступ вдоль стены:", self.op_s_spin)
        form.addRow("Ширина проёма:", self.op_w_spin)
        form.addRow("Высота проёма:", self.op_h_spin)
        form.addRow("Отметка от пола:", self.op_sill_spin)
        form.addRow("Открывание двери:", self.op_swing_combo)
        form.addRow("Угол открывания:", self.op_angle_spin)
        form.addRow("Выступ подоконника:", self.op_sill_depth_spin)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.btn_add_opening = QPushButton("Добавить проём на стену", w)
        self.btn_add_opening.clicked.connect(self._on_add_opening)
        self.btn_del_opening = QPushButton("Удалить проём", w)
        self.btn_del_opening.clicked.connect(self._on_remove_opening)
        row.addWidget(self.btn_add_opening)
        row.addWidget(self.btn_del_opening)
        lay.addLayout(row)
        lay.addStretch(1)
        self._on_opening_kind_changed(0)
        return w

    def _build_obstacles_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.obstacles_list = QListWidget(w)
        self.obstacles_list.setMaximumHeight(130)
        self.obstacles_list.currentRowChanged.connect(self._on_obstacle_list_row_changed)
        lay.addWidget(self.obstacles_list)

        form = QFormLayout()
        self.obs_kind_combo = QComboBox(w)
        for k in OBSTACLE_KINDS:
            self.obs_kind_combo.addItem(OBSTACLE_KIND_LABELS[k], k)
        self.obs_name_edit = QLineEdit("Колонна", w)
        self.obs_x_spin = _make_spin(200.0, -50000.0, 50000.0, step=50.0)
        self.obs_y_spin = _make_spin(0.0, -5000.0, 20000.0, step=50.0)
        self.obs_z_spin = _make_spin(200.0, -50000.0, 50000.0, step=50.0)
        self.obs_w_spin = _make_spin(300.0, 10.0, 20000.0, step=20.0)
        self.obs_h_spin = _make_spin(self._room.ceiling_height_mm, 10.0, 20000.0, step=50.0)
        self.obs_d_spin = _make_spin(300.0, 10.0, 20000.0, step=20.0)
        self.obs_rot_spin = _make_spin(0.0, -180.0, 180.0, step=5.0, decimals=1, suffix=" °")
        self.obs_clr_spin = _make_spin(50.0, 0.0, 2000.0, step=10.0)

        for fld in (
            self.obs_name_edit,
            self.obs_x_spin,
            self.obs_y_spin,
            self.obs_z_spin,
            self.obs_w_spin,
            self.obs_h_spin,
            self.obs_d_spin,
            self.obs_rot_spin,
            self.obs_clr_spin,
        ):
            self._bind_enter_apply(fld, self._on_apply_or_add_obstacle)

        form.addRow("Тип объекта:", self.obs_kind_combo)
        form.addRow("Название:", self.obs_name_edit)
        form.addRow("Позиция X:", self.obs_x_spin)
        form.addRow("Высота от пола Y:", self.obs_y_spin)
        form.addRow("Позиция Z:", self.obs_z_spin)
        form.addRow("Ширина (X):", self.obs_w_spin)
        form.addRow("Высота (Y):", self.obs_h_spin)
        form.addRow("Глубина (Z):", self.obs_d_spin)
        form.addRow("Поворот вокруг Y:", self.obs_rot_spin)
        form.addRow("Зона зазора / запрета:", self.obs_clr_spin)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.btn_add_obs = QPushButton("Добавить препятствие", w)
        self.btn_add_obs.clicked.connect(self._on_add_obstacle)
        self.btn_del_obs = QPushButton("Удалить", w)
        self.btn_del_obs.clicked.connect(self._on_remove_obstacle)
        row.addWidget(self.btn_add_obs)
        row.addWidget(self.btn_del_obs)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    # ── Тема и иконки ─────────────────────────────────────────

    def refresh_theme(self) -> None:
        t = current_theme()
        self._lbl_rect_hdr.setStyleSheet(f"color: {t.heading}; font-weight: 600;")
        self._lbl_corner_hdr.setStyleSheet(f"color: {t.heading}; font-weight: 600;")
        self._wall_enter_hint.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self.corner_info_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._dev_hint.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._coords_label.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")
        self._summary_label.setStyleSheet(f"color: {t.text_dim}; font-size: 12px;")

        self.btn_draw_poly.setIcon(render_room_svg_icon("room_plan.svg", t.text, 16))
        self.btn_niche.setIcon(render_room_svg_icon("room_niche.svg", t.text, 16))
        self.btn_finish.setIcon(render_room_svg_icon("room_check_done.svg", t.select_fg, 16))
        self.inspector_tabs.setTabIcon(0, render_room_svg_icon("room_wall.svg", t.text, 15))
        self.inspector_tabs.setTabIcon(1, render_room_svg_icon("room_deviation.svg", t.warning, 15))
        self.inspector_tabs.setTabIcon(2, render_room_svg_icon("room_door.svg", t.accent_soft, 15))
        self.inspector_tabs.setTabIcon(3, render_room_svg_icon("room_obstacle.svg", t.warning, 15))
        self.canvas.update()

    # ── Внутренний Undo/Redo планировки ───────────────────────

    def _push_undo_snapshot(self) -> None:
        self._undo_history.append(self._room.clone())
        if len(self._undo_history) > 40:
            self._undo_history.pop(0)
        self._redo_history.clear()
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        self.btn_undo.setEnabled(bool(self._undo_history))
        self.btn_redo.setEnabled(bool(self._redo_history))

    def _undo(self) -> None:
        if not self._undo_history:
            return
        self._redo_history.append(self._room.clone())
        self._room = self._undo_history.pop()
        self.canvas.set_room(self._room, keep_view=True)
        self._reload_all_views()

    def _redo(self) -> None:
        if not self._redo_history:
            return
        self._undo_history.append(self._room.clone())
        self._room = self._redo_history.pop()
        self.canvas.set_room(self._room, keep_view=True)
        self._reload_all_views()

    # ── Синхронизация списков и форм ──────────────────────────

    def _selected_wall(self):
        return self._room.get_wall(self.canvas.selected_wall_uid)

    def _reload_all_views(self, *, select_first_wall: bool = False) -> None:
        self._syncing_ui = True
        try:
            self.walls_list.clear()
            sel_row = 0
            for idx, w in enumerate(self._room.walls):
                info = self._room.wall_geometry(w)
                extras = []
                if w.openings:
                    extras.append(f"проёмов: {len(w.openings)}")
                if w.deviation_stations:
                    extras.append(f"замеров: {len(w.deviation_stations)}")
                extra_txt = f" [{', '.join(extras)}]" if extras else ""
                item = QListWidgetItem(
                    f"{w.name} — {info.length_mm:.0f} мм{extra_txt}"
                )
                item.setData(Qt.ItemDataRole.UserRole, w.uid)
                self.walls_list.addItem(item)
                if w.uid == self.canvas.selected_wall_uid:
                    sel_row = idx
            if self.walls_list.count() > 0:
                if select_first_wall and not self.canvas.selected_wall_uid:
                    sel_row = 0
                self.walls_list.setCurrentRow(sel_row)
                item = self.walls_list.item(sel_row)
                if item is not None:
                    self.canvas.selected_wall_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")

            self.ceiling_spin.setValue(float(self._room.ceiling_height_mm))
            self.floor_elev_spin.setValue(float(self._room.floor_elevation_mm))
            self._sync_selected_wall_controls()
            self._sync_selected_vertex_controls()
            self._sync_obstacles_list()
            self._update_summary()
            self._update_undo_buttons()
        finally:
            self._syncing_ui = False
        self.canvas.update()

    def _sync_selected_vertex_controls(self) -> None:
        v_uid = str(self.canvas.selected_vertex_uid or "")
        v = self._room.get_vertex(v_uid) if v_uid else None
        if v is None:
            self.corner_info_label.setText("Нажмите на точку угла на плане")
            self.vertex_angle_spin.setEnabled(False)
            return
        v_idx = next((i + 1 for i, vt in enumerate(self._room.vertices) if vt.uid == v.uid), 1)
        w_in = next((w for w in self._room.walls if w.end_vertex_uid == v.uid), None)
        w_out = next((w for w in self._room.walls if w.start_vertex_uid == v.uid), None)
        if w_in is not None and w_out is not None:
            ang = self._room.interior_angle_at_vertex(v.uid)
            self.corner_info_label.setText(f"Угол №{v_idx} ({w_in.name} ↔ {w_out.name})")
            self.vertex_angle_spin.setEnabled(True)
            self.vertex_angle_spin.setValue(ang)
        else:
            self.corner_info_label.setText(f"Узел №{v_idx} (край незамкнутого контура)")
            self.vertex_angle_spin.setEnabled(False)

    def _sync_selected_wall_controls(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        info = self._room.wall_geometry(w)
        self.wall_name_edit.setText(w.name)
        self.wall_len_spin.setValue(info.length_mm)
        self.wall_thick_spin.setValue(float(w.thickness_mm))
        self.wall_height_spin.setValue(float(w.height_mm))
        self.wall_visible_cb.setChecked(bool(w.visible))

        # Таблица контрольных станций неровности
        self.dev_table.setRowCount(len(w.deviation_stations))
        for row, st in enumerate(w.deviation_stations):
            it_s = QTableWidgetItem(f"{st.s_mm:.1f}")
            it_s.setData(Qt.ItemDataRole.UserRole, st.uid)
            self.dev_table.setItem(row, 0, it_s)
            self.dev_table.setItem(row, 1, QTableWidgetItem(f"{st.height_mm:.1f}"))
            self.dev_table.setItem(row, 2, QTableWidgetItem(f"{st.offset_mm:+.1f}"))

        # Список проёмов стены
        self.openings_list.clear()
        for op in w.openings:
            kind_lbl = OPENING_KIND_LABELS.get(op.kind, op.kind)
            item = QListWidgetItem(
                f"{op.name} ({kind_lbl}) — s={op.offset_s_mm:.0f}, {op.width_mm:.0f}×{op.height_mm:.0f} мм"
            )
            item.setData(Qt.ItemDataRole.UserRole, op.uid)
            self.openings_list.addItem(item)

    def _sync_obstacles_list(self) -> None:
        self.obstacles_list.clear()
        for obs in self._room.obstacles:
            kind_lbl = OBSTACLE_KIND_LABELS.get(obs.kind, obs.kind)
            clr = f", зазор {obs.clearance_mm:g} мм" if obs.clearance_mm > 0 else ""
            item = QListWidgetItem(
                f"{obs.name} ({kind_lbl}) — {obs.width:.0f}×{obs.height:.0f}×{obs.depth:.0f} мм{clr}"
            )
            item.setData(Qt.ItemDataRole.UserRole, obs.uid)
            self.obstacles_list.addItem(item)

    def _update_summary(self) -> None:
        n_openings = sum(len(w.openings) for w in self._room.walls)
        n_devs = sum(len(w.deviation_stations) for w in self._room.walls)
        contour_state = "замкнутый" if self._room.is_closed() else "незамкнутый"
        self._summary_label.setText(
            f"Стен: {len(self._room.walls)} ({contour_state}) · Площадь: {self._room.floor_area_m2():.2f} м² · "
            f"Высота: {self._room.ceiling_height_mm:.0f} мм · Проёмов: {n_openings} · "
            f"Замеров: {n_devs} · Препятствий: {len(self._room.obstacles)}"
        )

    # ── Обработчики событий ───────────────────────────────────

    def _on_cursor_coords(self, wx: float, wz: float) -> None:
        hint = " (ЛКМ — точка, клик по 1-й точке — замкнуть, ПКМ — шаг назад)" if self.canvas.draw_mode else ""
        self._coords_label.setText(f"X: {wx:.0f} мм · Z: {wz:.0f} мм{hint}")

    def _on_toggle_draw_mode(self, checked: bool) -> None:
        self.canvas.set_draw_mode(bool(checked))

    def _on_canvas_wall_selected(self, wall_uid: str) -> None:
        self._reload_all_views()

    def _on_canvas_vertex_selected(self, vertex_uid: str) -> None:
        self._syncing_ui = True
        try:
            self._sync_selected_vertex_controls()
        finally:
            self._syncing_ui = False
        if self.vertex_angle_spin.isEnabled():
            self.inspector_tabs.setCurrentIndex(0)
            self.vertex_angle_spin.setFocus()
            self.vertex_angle_spin.selectAll()

    def _on_canvas_vertex_moved(self, vertex_uid: str, x: float, z: float) -> None:
        # Холст уже сдвинул узел в реальном времени — обновляем таблицы и сводку
        self._reload_all_views()

    def _on_canvas_polygon_drawn(self, points_xz: list) -> None:
        self.btn_draw_poly.blockSignals(True)
        self.btn_draw_poly.setChecked(False)
        self.btn_draw_poly.blockSignals(False)
        try:
            new_room = RoomFrame.from_polygon(
                points_xz,
                height_mm=self._room.ceiling_height_mm,
                wall_thickness_mm=self._room.default_wall_thickness_mm,
                name=self._room.name,
            )
            self._push_undo_snapshot()
            self._room = new_room
            self.canvas.set_room(self._room, keep_view=False)
            self._reload_all_views(select_first_wall=True)
        except ValueError as exc:
            QMessageBox.warning(self, "Контур помещения", str(exc))

    def _on_wall_list_row_changed(self, row: int) -> None:
        if self._syncing_ui or row < 0:
            return
        item = self.walls_list.item(row)
        if item is None:
            return
        self.canvas.selected_wall_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._syncing_ui = True
        try:
            self._sync_selected_wall_controls()
        finally:
            self._syncing_ui = False
        self.canvas.update()

    def _on_create_rect(self) -> None:
        try:
            new_room = RoomFrame.create_rectangular(
                width_mm=self.rect_w_spin.value(),
                depth_mm=self.rect_d_spin.value(),
                height_mm=self.rect_h_spin.value(),
                wall_thickness_mm=self._room.default_wall_thickness_mm,
                name=self._room.name,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Прямоугольное помещение", str(exc))
            return
        self._push_undo_snapshot()
        self._room = new_room
        self.canvas.set_room(self._room, keep_view=False)
        self._reload_all_views(select_first_wall=True)

    def _on_wall_visible_toggled(self, checked: bool) -> None:
        if self._syncing_ui:
            return
        self._on_apply_wall()

    def _on_apply_wall(self) -> None:
        if self._syncing_ui:
            return
        w = self._selected_wall()
        if w is None:
            return
        cur_info = self._room.wall_geometry(w)
        new_name = self.wall_name_edit.text().strip() or w.name
        new_thick = float(self.wall_thick_spin.value())
        new_height = float(self.wall_height_spin.value())
        new_vis = bool(self.wall_visible_cb.isChecked())
        new_len = float(self.wall_len_spin.value())
        if (
            new_name == w.name
            and abs(new_thick - w.thickness_mm) <= 1e-3
            and abs(new_height - w.height_mm) <= 1e-3
            and new_vis == w.visible
            and abs(new_len - cur_info.length_mm) <= 0.1
        ):
            return
        self._push_undo_snapshot()
        try:
            w.name = new_name
            w.thickness_mm = new_thick
            w.height_mm = new_height
            w.visible = new_vis
            if abs(new_len - cur_info.length_mm) > 0.1:
                self._room.set_wall_length(w.uid, new_len)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Параметры стены", str(exc))
        self._reload_all_views()

    def _on_apply_vertex_angle(self) -> None:
        if self._syncing_ui:
            return
        v_uid = str(self.canvas.selected_vertex_uid or "")
        if not v_uid or not self._room.has_corner_angle(v_uid):
            return
        target_angle = float(self.vertex_angle_spin.value())
        cur_angle = self._room.interior_angle_at_vertex(v_uid)
        if abs(target_angle - cur_angle) <= 0.05:
            return
        self._push_undo_snapshot()
        try:
            self._room.set_vertex_angle(v_uid, target_angle)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Угол контура", str(exc))
        self._reload_all_views()

    def _on_split_wall(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        self._push_undo_snapshot()
        try:
            self._room.split_wall(w.uid, ratio=0.5)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Разбиение стены", str(exc))
        self._reload_all_views()

    def _on_insert_niche(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        info = self._room.wall_geometry(w)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Ниша / выступ на стене «{w.name}»")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        s_spin = _make_spin(max(200.0, info.length_mm * 0.25), 50.0, max(100.0, info.length_mm - 100.0), step=50.0)
        w_spin = _make_spin(min(1000.0, max(200.0, info.length_mm * 0.4)), 50.0, max(100.0, info.length_mm - 100.0), step=50.0)
        d_spin = _make_spin(-400.0, -5000.0, 5000.0, step=50.0)
        form.addRow("Отступ от начала стены:", s_spin)
        form.addRow("Ширина ниши / выступа:", w_spin)
        form.addRow("Глубина (− ниша / + выступ):", d_spin)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dlg.exec():
            return
        self._push_undo_snapshot()
        try:
            self._room.insert_niche_or_protrusion(w.uid, s_spin.value(), w_spin.value(), d_spin.value())
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Ниша / выступ", str(exc))
        self._reload_all_views()

    def _on_delete_wall(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        self._push_undo_snapshot()
        try:
            self._room.delete_wall(w.uid)
            self.canvas.selected_wall_uid = self._room.walls[0].uid if self._room.walls else ""
            if self.canvas.selected_vertex_uid and self._room.get_vertex(self.canvas.selected_vertex_uid) is None:
                self.canvas.selected_vertex_uid = ""
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Удаление стены", str(exc))
        self._reload_all_views(select_first_wall=True)

    def _on_delete_selected_or_end_vertex(self) -> None:
        v_uid = str(self.canvas.selected_vertex_uid or "")
        if not v_uid:
            w = self._selected_wall()
            if w is None:
                return
            v_uid = w.end_vertex_uid
        self._push_undo_snapshot()
        try:
            merged = self._room.delete_vertex(v_uid)
            self.canvas.selected_wall_uid = merged.uid
            self.canvas.selected_vertex_uid = ""
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Удаление узла", str(exc))
        self._reload_all_views()

    def _on_room_levels_changed(self) -> None:
        if self._syncing_ui:
            return
        new_h = float(self.ceiling_spin.value())
        new_f = float(self.floor_elev_spin.value())
        old_h = float(self._room.ceiling_height_mm)
        old_f = float(self._room.floor_elevation_mm)
        if abs(new_h - old_h) <= 1e-3 and abs(new_f - old_f) <= 1e-3:
            return
        self._push_undo_snapshot()
        self._room.ceiling_height_mm = new_h
        self._room.floor_elevation_mm = new_f
        for w in self._room.walls:
            if abs(w.height_mm - old_h) < 1.0:
                w.height_mm = new_h
        self._reload_all_views()

    def _on_add_deviation(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        self._push_undo_snapshot()
        try:
            st = WallDeviationStation(
                s_mm=self.dev_s_spin.value(),
                height_mm=self.dev_h_spin.value(),
                offset_mm=self.dev_off_spin.value(),
            )
            self._room.add_deviation_station(w.uid, st)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Контрольная точка", str(exc))
        self._reload_all_views()

    def _on_remove_deviation(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        row = self.dev_table.currentRow()
        if row < 0:
            return
        it = self.dev_table.item(row, 0)
        if it is None:
            return
        st_uid = str(it.data(Qt.ItemDataRole.UserRole) or "")
        self._push_undo_snapshot()
        self._room.remove_deviation_station(w.uid, st_uid)
        self._reload_all_views()

    def _on_preset_tilt(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        info = self._room.wall_geometry(w)
        self._push_undo_snapshot()
        w.deviation_stations = [
            WallDeviationStation(s_mm=0.5 * info.length_mm, height_mm=0.0, offset_mm=0.0),
            WallDeviationStation(s_mm=0.5 * info.length_mm, height_mm=float(w.height_mm), offset_mm=15.0),
        ]
        self._reload_all_views()

    def _on_preset_bow(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        info = self._room.wall_geometry(w)
        mid_h = 0.5 * float(w.height_mm)
        self._push_undo_snapshot()
        w.deviation_stations = [
            WallDeviationStation(s_mm=0.0, height_mm=mid_h, offset_mm=0.0),
            WallDeviationStation(s_mm=0.5 * info.length_mm, height_mm=mid_h, offset_mm=15.0),
            WallDeviationStation(s_mm=info.length_mm, height_mm=mid_h, offset_mm=0.0),
        ]
        self._reload_all_views()

    def _on_opening_kind_changed(self, _index: int) -> None:
        kind = str(self.op_kind_combo.currentData() or "door")
        is_door = kind == "door"
        is_win = kind == "window"
        self.op_swing_combo.setEnabled(is_door)
        self.op_angle_spin.setEnabled(is_door)
        self.op_sill_depth_spin.setEnabled(is_win)
        if is_win and self.op_sill_spin.value() < 10.0:
            self.op_sill_spin.setValue(850.0)
            self.op_h_spin.setValue(1400.0)
            self.op_w_spin.setValue(1400.0)
            self.op_name_edit.setText("Окно")
        elif is_door:
            self.op_sill_spin.setValue(0.0)
            self.op_h_spin.setValue(2050.0)
            self.op_w_spin.setValue(900.0)
            self.op_name_edit.setText("Дверь")
        else:
            self.op_sill_spin.setValue(0.0)
            self.op_h_spin.setValue(2100.0)
            self.op_name_edit.setText("Проход")

    def _on_opening_list_row_changed(self, row: int) -> None:
        if self._syncing_ui or row < 0:
            return
        item = self.openings_list.item(row)
        if item is None:
            return
        op_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        pair = self._room.get_opening(op_uid)
        if pair is None:
            return
        _w, op = pair
        self._syncing_ui = True
        try:
            k_idx = self.op_kind_combo.findData(op.kind)
            if k_idx >= 0:
                self.op_kind_combo.setCurrentIndex(k_idx)
            self.op_name_edit.setText(op.name)
            self.op_s_spin.setValue(float(op.offset_s_mm))
            self.op_w_spin.setValue(float(op.width_mm))
            self.op_h_spin.setValue(float(op.height_mm))
            self.op_sill_spin.setValue(float(op.sill_height_mm))
            s_idx = self.op_swing_combo.findData(op.swing_dir)
            if s_idx >= 0:
                self.op_swing_combo.setCurrentIndex(s_idx)
            self.op_angle_spin.setValue(float(op.swing_angle_deg))
            self.op_sill_depth_spin.setValue(float(op.sill_depth_mm))
        finally:
            self._syncing_ui = False

    def _on_apply_or_add_opening(self) -> None:
        if self._syncing_ui:
            return
        item = self.openings_list.currentItem()
        if item is None:
            self._on_add_opening()
            return
        op_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        pair = self._room.get_opening(op_uid)
        if pair is None:
            self._on_add_opening()
            return
        w, old_op = pair
        self._push_undo_snapshot()
        try:
            updated = WallOpening(
                kind=str(self.op_kind_combo.currentData() or old_op.kind),
                name=self.op_name_edit.text().strip() or old_op.name,
                offset_s_mm=self.op_s_spin.value(),
                width_mm=self.op_w_spin.value(),
                height_mm=self.op_h_spin.value(),
                sill_height_mm=self.op_sill_spin.value(),
                swing_dir=str(self.op_swing_combo.currentData() or old_op.swing_dir),
                swing_angle_deg=self.op_angle_spin.value(),
                sill_depth_mm=self.op_sill_depth_spin.value(),
                uid=old_op.uid,
            )
            self._room.remove_opening(old_op.uid)
            self._room.add_opening(w.uid, updated)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Параметры проёма", str(exc))
        self._reload_all_views()

    def _on_add_opening(self) -> None:
        w = self._selected_wall()
        if w is None:
            return
        self._push_undo_snapshot()
        try:
            op = WallOpening(
                kind=str(self.op_kind_combo.currentData() or "door"),
                name=self.op_name_edit.text().strip(),
                offset_s_mm=self.op_s_spin.value(),
                width_mm=self.op_w_spin.value(),
                height_mm=self.op_h_spin.value(),
                sill_height_mm=self.op_sill_spin.value(),
                swing_dir=str(self.op_swing_combo.currentData() or "in_left"),
                swing_angle_deg=self.op_angle_spin.value(),
                sill_depth_mm=self.op_sill_depth_spin.value(),
            )
            self._room.add_opening(w.uid, op)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Добавление проёма", str(exc))
        self._reload_all_views()

    def _on_remove_opening(self) -> None:
        item = self.openings_list.currentItem()
        if item is None:
            return
        op_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._push_undo_snapshot()
        self._room.remove_opening(op_uid)
        self._reload_all_views()

    def _on_obstacle_list_row_changed(self, row: int) -> None:
        if self._syncing_ui or row < 0:
            return
        item = self.obstacles_list.item(row)
        if item is None:
            return
        obs_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        obs = self._room.get_obstacle(obs_uid)
        if obs is None:
            return
        self._syncing_ui = True
        try:
            k_idx = self.obs_kind_combo.findData(obs.kind)
            if k_idx >= 0:
                self.obs_kind_combo.setCurrentIndex(k_idx)
            self.obs_name_edit.setText(obs.name)
            self.obs_x_spin.setValue(float(obs.x))
            self.obs_y_spin.setValue(float(obs.y))
            self.obs_z_spin.setValue(float(obs.z))
            self.obs_w_spin.setValue(float(obs.width))
            self.obs_h_spin.setValue(float(obs.height))
            self.obs_d_spin.setValue(float(obs.depth))
            self.obs_rot_spin.setValue(float(obs.rotation_y_deg))
            self.obs_clr_spin.setValue(float(obs.clearance_mm))
        finally:
            self._syncing_ui = False

    def _on_apply_or_add_obstacle(self) -> None:
        if self._syncing_ui:
            return
        item = self.obstacles_list.currentItem()
        if item is None:
            self._on_add_obstacle()
            return
        obs_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        obs = self._room.get_obstacle(obs_uid)
        if obs is None:
            self._on_add_obstacle()
            return
        self._push_undo_snapshot()
        try:
            updated = RoomObstacle(
                kind=str(self.obs_kind_combo.currentData() or obs.kind),
                name=self.obs_name_edit.text().strip() or obs.name,
                x=self.obs_x_spin.value(),
                y=self.obs_y_spin.value(),
                z=self.obs_z_spin.value(),
                width=self.obs_w_spin.value(),
                height=self.obs_h_spin.value(),
                depth=self.obs_d_spin.value(),
                rotation_y_deg=self.obs_rot_spin.value(),
                clearance_mm=self.obs_clr_spin.value(),
                visible=obs.visible,
                uid=obs.uid,
            )
            idx = next((i for i, o in enumerate(self._room.obstacles) if o.uid == obs.uid), -1)
            if idx >= 0:
                self._room.obstacles[idx] = updated
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Параметры препятствия", str(exc))
        self._reload_all_views()

    def _on_add_obstacle(self) -> None:
        self._push_undo_snapshot()
        try:
            obs = RoomObstacle(
                kind=str(self.obs_kind_combo.currentData() or "column"),
                name=self.obs_name_edit.text().strip(),
                x=self.obs_x_spin.value(),
                y=self.obs_y_spin.value(),
                z=self.obs_z_spin.value(),
                width=self.obs_w_spin.value(),
                height=self.obs_h_spin.value(),
                depth=self.obs_d_spin.value(),
                rotation_y_deg=self.obs_rot_spin.value(),
                clearance_mm=self.obs_clr_spin.value(),
            )
            self._room.add_obstacle(obs)
        except ValueError as exc:
            self._room = self._undo_history.pop()
            self.canvas.set_room(self._room, keep_view=True)
            QMessageBox.warning(self, "Добавление препятствия", str(exc))
        self._reload_all_views()

    def _on_remove_obstacle(self) -> None:
        item = self.obstacles_list.currentItem()
        if item is None:
            return
        obs_uid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._push_undo_snapshot()
        self._room.remove_obstacle(obs_uid)
        self._reload_all_views()

    def _on_finish(self) -> None:
        try:
            self._room.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверка планировки", str(exc))
            return
        self.accept()

    def get_room_frame(self) -> RoomFrame:
        """Возвращает подтверждённую копию габаритной рамки помещения."""
        return self._room.clone()


# ── Вспомогательные диалоги режима помещения ──────────────────


class SnapProductToWallDialog(QDialog):
    """Диалог привязки выбранного изделия к стене помещения с точным отступом."""

    def __init__(self, room: RoomFrame, product: PlacedProduct, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Привязать к стене: {product.name}")
        self.setMinimumWidth(400)
        self._room = room
        self._product = product

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.wall_combo = QComboBox(self)
        default_wall = find_nearest_wall_for_product(room, product)
        default_idx = 0
        for idx, w in enumerate(room.walls):
            info = room.wall_geometry(w)
            self.wall_combo.addItem(f"{w.name} ({info.length_mm:.0f} мм)", w.uid)
            if default_wall is not None and w.uid == default_wall.uid:
                default_idx = idx
        self.wall_combo.setCurrentIndex(default_idx)

        self.offset_spin = _make_spin(product.wall_offset_mm, 0.0, 5000.0, step=5.0)
        self.center_cb = QCheckBox("Отцентрировать вдоль стены", self)
        self.center_cb.setChecked(True)
        self.s_spin = _make_spin(0.0, 0.0, MAX_WALL_LENGTH_MM, step=50.0)
        self.s_spin.setEnabled(False)
        self.center_cb.toggled.connect(lambda checked: self.s_spin.setEnabled(not checked))
        self.elev_spin = _make_spin(max(0.0, product.y - room.floor_elevation_mm), 0.0, 10000.0, step=50.0)

        form.addRow("Стена привязки:", self.wall_combo)
        form.addRow("Монтажный отступ:", self.offset_spin)
        form.addRow("", self.center_cb)
        form.addRow("Отступ вдоль стены (s):", self.s_spin)
        form.addRow("Высота установки от пола:", self.elev_spin)
        root.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = bb.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText("Привязать")
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def get_snap_params(self) -> dict:
        return {
            "wall_uid": str(self.wall_combo.currentData() or ""),
            "offset_mm": float(self.offset_spin.value()),
            "s_position_mm": None if self.center_cb.isChecked() else float(self.s_spin.value()),
            "elevation_y_mm": float(self.elev_spin.value()),
        }


class WallGapReportDialog(QDialog):
    """Окно многоточечного анализа зазоров между выбранным изделием и неровной стеной."""

    def __init__(self, workspace: RoomWorkspace, product: PlacedProduct, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Анализ зазоров до стены — {product.name}")
        self.setMinimumSize(560, 420)
        self._workspace = workspace
        self._product = product
        self.last_report: WallGapReport | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top = QFormLayout()
        self.wall_combo = QComboBox(self)
        nearest = find_nearest_wall_for_product(workspace.room_frame, product)
        def_idx = 0
        for idx, w in enumerate(workspace.room_frame.walls):
            self.wall_combo.addItem(f"{w.name} (замеров неровности: {len(w.deviation_stations)})", w.uid)
            if nearest is not None and w.uid == nearest.uid:
                def_idx = idx
        self.wall_combo.setCurrentIndex(def_idx)
        self.wall_combo.currentIndexChanged.connect(self._recompute)

        self.allowed_spin = _make_spin(workspace.allowed_gap_mm, 0.0, 200.0, step=1.0)
        self.allowed_spin.valueChanged.connect(self._recompute)

        top.addRow("Стена для замера:", self.wall_combo)
        top.addRow("Допустимый зазор:", self.allowed_spin)
        root.addLayout(top)

        self._summary_box = QLabel("", self)
        self._summary_box.setWordWrap(True)
        root.addWidget(self._summary_box)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Точка замера", "Отклонение стены, мм", "Зазор, мм", "Статус"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self._note_lbl = QLabel(
            "Анализ носит справочный характер: размеры изделия не изменяются автоматически.",
            self,
        )
        self._note_lbl.setWordWrap(True)
        root.addWidget(self._note_lbl)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_btn = bb.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("Закрыть")
        bb.rejected.connect(self.accept)
        root.addWidget(bb)

        self._recompute()

    def _recompute(self) -> None:
        t = current_theme()
        wall_uid = str(self.wall_combo.currentData() or "")
        if not wall_uid:
            return
        rep = measure_product_wall_gaps(
            self._workspace.room_frame,
            self._product,
            wall_uid,
            samples_w=3,
            samples_h=3,
            allowed_gap_mm=self.allowed_spin.value(),
            tolerance_mm=self._workspace.collision_tolerance_mm,
        )
        self.last_report = rep
        self._workspace.allowed_gap_mm = float(self.allowed_spin.value())

        col = t.error if rep.has_collision else (t.warning if rep.has_excess_gap else t.success)
        self._summary_box.setText(rep.format_summary())
        self._summary_box.setStyleSheet(f"color: {col}; font-weight: 600;")
        self._note_lbl.setStyleSheet(f"color: {t.text_dim}; font-size: 11px;")

        status_map = {
            "collision": "Пересечение со стеной",
            "excess_gap": "Зазор > допуска",
            "ok": "В допуске",
        }
        self.table.setRowCount(len(rep.samples))
        for row, smp in enumerate(rep.samples):
            self.table.setItem(row, 0, QTableWidgetItem(smp.label))
            self.table.setItem(row, 1, QTableWidgetItem(f"{smp.wall_offset_mm:+.1f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{smp.gap_mm:.1f}"))
            st_item = QTableWidgetItem(status_map.get(smp.status, smp.status))
            if smp.status == "collision":
                st_item.setForeground(QColor(t.error))
            elif smp.status == "excess_gap":
                st_item.setForeground(QColor(t.warning))
            else:
                st_item.setForeground(QColor(t.success))
            self.table.setItem(row, 3, st_item)
