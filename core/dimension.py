"""Модель размерных линий и умные 3D-измерения (в стиле QymCAD)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


def _cross3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Векторное произведение 3D-векторов (совместимо с легковесным numpy-стабом)."""
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    bx, by, bz = float(b[0]), float(b[1]), float(b[2])
    return np.array(
        [
            ay * bz - az * by,
            az * bx - ax * bz,
            ax * by - ay * bx,
        ],
        dtype=float,
    )


@dataclass
class DimensionLine:
    """Размерная линия между двумя точками в 3D пространстве."""

    pt1: np.ndarray  # shape (3,) float
    pt2: np.ndarray  # shape (3,) float
    color: tuple[float, float, float] = (0.96, 0.45, 0.12)  # Яркий оранжевый цвет размерных линий
    name: str = ""
    sub_label: str = ""

    @property
    def distance(self) -> float:
        return float(np.linalg.norm(self.pt2 - self.pt1))

    @property
    def delta(self) -> tuple[float, float, float]:
        d = self.pt2 - self.pt1
        return float(d[0]), float(d[1]), float(d[2])

    @property
    def midpoint(self) -> np.ndarray:
        return 0.5 * (self.pt1 + self.pt2)

    def main_badge_text(self) -> str:
        """Заголовок 2D-бейджа размерной линии."""
        if self.name:
            return self.name
        return f"{self.distance:.1f} мм"

    def sub_badge_text(self) -> str:
        """Подстрока 2D-бейджа размерной линии."""
        if self.sub_label:
            return self.sub_label
        dx, dy, dz = self.delta
        return f"ΔX: {abs(dx):.1f}  ΔY: {abs(dy):.1f}  ΔZ: {abs(dz):.1f}"

    def format_label(self, show_deltas: bool = True) -> str:
        dist = self.distance
        dx, dy, dz = self.delta
        if self.name:
            if not show_deltas:
                return self.name
            if self.sub_label:
                return f"{self.name} ({self.sub_label})"
            return f"{self.name} (ΔX: {abs(dx):.1f}, ΔY: {abs(dy):.1f}, ΔZ: {abs(dz):.1f})"
        # Если измерение идет строго вдоль одной оси:
        if abs(dy) < 0.1 and abs(dz) < 0.1:
            return f"X: {abs(dx):.1f} мм"
        if abs(dx) < 0.1 and abs(dz) < 0.1:
            return f"Y: {abs(dy):.1f} мм"
        if abs(dx) < 0.1 and abs(dy) < 0.1:
            return f"Z: {abs(dz):.1f} мм"
        if not show_deltas:
            return f"{dist:.1f} мм"
        return f"{dist:.1f} мм (ΔX: {abs(dx):.1f}, ΔY: {abs(dy):.1f}, ΔZ: {abs(dz):.1f})"


@dataclass
class DimensionAngle:
    """Угловой размер между тремя точками: pt1, вершина (vertex) и pt3."""

    pt1: np.ndarray     # shape (3,) float (первая точка луча 1)
    vertex: np.ndarray  # shape (3,) float (вершина угла)
    pt3: np.ndarray     # shape (3,) float (вторая точка луча 2)
    color: tuple[float, float, float] = (0.98, 0.73, 0.01)  # Янтарный / золотистый цвет для углов
    name: str = ""

    @property
    def distance1(self) -> float:
        return float(np.linalg.norm(self.pt1 - self.vertex))

    @property
    def distance2(self) -> float:
        return float(np.linalg.norm(self.pt3 - self.vertex))

    @property
    def angle_deg(self) -> float:
        v1 = self.pt1 - self.vertex
        v2 = self.pt3 - self.vertex
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-8 or n2 < 1e-8:
            return 0.0
        cos_val = float(np.dot(v1, v2) / (n1 * n2))
        cos_val = max(-1.0, min(1.0, cos_val))
        return float(math.degrees(math.acos(cos_val)))

    @property
    def is_right_angle(self) -> bool:
        return abs(self.angle_deg - 90.0) < 0.35

    def arc_points(self, num_segments: int = 24, radius: float = 45.0) -> list[np.ndarray]:
        """Генерирует последовательность точек 3D дуги или квадрата прямого угла."""
        v1 = self.pt1 - self.vertex
        v2 = self.pt3 - self.vertex
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-8 or n2 < 1e-8:
            return []

        u1 = v1 / n1
        u2 = v2 / n2
        dot = float(np.dot(u1, u2))

        # Адаптивный радиус дуги: не более 35% от меньшей стороны
        r = min(radius, max(18.0, min(n1, n2) * 0.35))

        # Архитектурный квадратный символ для прямых углов 90°
        if self.is_right_angle:
            p_a = self.vertex + u1 * r
            p_b = self.vertex + (u1 + u2) * r
            p_c = self.vertex + u2 * r
            return [p_a, p_b, p_c]

        # Для обычных углов: интерполяция дуги в плоскости векторов
        if abs(dot) > 0.9999:
            return []

        u_perp = u2 - dot * u1
        n_perp = float(np.linalg.norm(u_perp))
        if n_perp < 1e-8:
            return []
        u_perp = u_perp / n_perp

        theta_total = float(math.acos(max(-1.0, min(1.0, dot))))
        pts = []
        for i in range(num_segments + 1):
            t = theta_total * (i / num_segments)
            p = self.vertex + r * (math.cos(t) * u1 + math.sin(t) * u_perp)
            pts.append(p)
        return pts

    def bisector_point(self, distance: float = 40.0) -> np.ndarray:
        """Точка вдоль биссектрисы угла для размещения 2D бейджа."""
        v1 = self.pt1 - self.vertex
        v2 = self.pt3 - self.vertex
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-8 or n2 < 1e-8:
            return self.vertex

        u1 = v1 / n1
        u2 = v2 / n2
        bisect = u1 + u2
        n_bisect = float(np.linalg.norm(bisect))
        if n_bisect < 1e-8:
            # Развернутый угол 180°: смещаем перпендикулярно
            up = np.array([0.0, 1.0, 0.0]) if abs(float(u1[1])) < 0.9 else np.array([1.0, 0.0, 0.0])
            perp = _cross3(u1, up)
            n_p = float(np.linalg.norm(perp))
            if n_p > 1e-8:
                return self.vertex + (perp / n_p) * distance
            return self.vertex

        u_b = bisect / n_bisect
        r = min(distance, max(22.0, min(n1, n2) * 0.35))
        return self.vertex + u_b * (r + 14.0)


# ---------------------------------------------------------------------------
# Умные 3D-измерения по типу геометрии (грань, отверстие, ребро, вершина)
# ---------------------------------------------------------------------------

_FACE_INFO_RU: dict[str, str] = {
    "left": "Левая грань",
    "right": "Правая грань",
    "bottom": "Нижняя грань",
    "top": "Верхняя грань",
    "back": "Задняя грань",
    "front": "Передняя грань",
}


def detect_panel_face_at_point(
    panel: Any,
    world_pt: np.ndarray,
) -> tuple[str, str, np.ndarray, tuple[float, float]]:
    """Определяет ближайшую локальную грань панели для мировой точки `world_pt`.

    Возвращает `(face_id, face_label_ru, world_normal, (dim_a, dim_b))`.
    Поддерживает повёрнутые панели через `world_to_local` / `rotate_vector`.
    """
    w = float(getattr(panel, "width", 0.0))
    h = float(getattr(panel, "height", 0.0))
    d = float(getattr(panel, "depth", 0.0))

    wx, wy, wz = float(world_pt[0]), float(world_pt[1]), float(world_pt[2])
    if hasattr(panel, "world_to_local"):
        lx, ly, lz = panel.world_to_local(wx, wy, wz)
    else:
        lx = wx - float(getattr(panel, "x", 0.0))
        ly = wy - float(getattr(panel, "y", 0.0))
        lz = wz - float(getattr(panel, "z", 0.0))

    candidates = [
        ("left", abs(lx - 0.0), (-1.0, 0.0, 0.0), (d, h)),
        ("right", abs(lx - w), (1.0, 0.0, 0.0), (d, h)),
        ("bottom", abs(ly - 0.0), (0.0, -1.0, 0.0), (w, d)),
        ("top", abs(ly - h), (0.0, 1.0, 0.0), (w, d)),
        ("back", abs(lz - 0.0), (0.0, 0.0, -1.0), (w, h)),
        ("front", abs(lz - d), (0.0, 0.0, 1.0), (w, h)),
    ]
    face_id, _dist, loc_n, dims = min(candidates, key=lambda item: item[1])
    if hasattr(panel, "rotate_vector"):
        nx, ny, nz = panel.rotate_vector(loc_n[0], loc_n[1], loc_n[2])
    else:
        nx, ny, nz = loc_n
    norm_vec = np.array([nx, ny, nz], dtype=float)
    n_len = float(np.linalg.norm(norm_vec))
    if n_len > 1e-8:
        norm_vec = norm_vec / n_len
    return face_id, _FACE_INFO_RU.get(face_id, "Грань"), norm_vec, dims


def inspect_hole_on_panel(panel: Any, hole: tuple) -> dict[str, Any]:
    """Возвращает геометрический паспорт отверстия на панели:
    диаметр, глубину, ось сверления и отступы центра отверстия до ближайших кромок грани.
    """
    hx = float(hole[0]) if len(hole) > 0 else 0.0
    hy = float(hole[1]) if len(hole) > 1 else 0.0
    hz = float(hole[2]) if len(hole) > 2 else 0.0
    radius = float(hole[3]) if len(hole) > 3 else 4.0
    depth = float(hole[4]) if len(hole) > 4 else 13.0
    axis = str(hole[5] if len(hole) > 5 else "X").upper()

    w = float(getattr(panel, "width", 0.0))
    h = float(getattr(panel, "height", 0.0))
    d = float(getattr(panel, "depth", 0.0))

    if axis == "X":
        m1 = min(hy, max(0.0, h - hy))
        m2 = min(hz, max(0.0, d - hz))
    elif axis == "Y":
        m1 = min(hx, max(0.0, w - hx))
        m2 = min(hz, max(0.0, d - hz))
    else:
        m1 = min(hx, max(0.0, w - hx))
        m2 = min(hy, max(0.0, h - hy))

    margin_min = min(m1, m2)
    margin_max = max(m1, m2)
    return {
        "diameter": radius * 2.0,
        "radius": radius,
        "depth": depth,
        "axis": axis,
        "margin_min": margin_min,
        "margin_max": margin_max,
        "local_pos": (hx, hy, hz),
    }


@dataclass
class MeasureTarget:
    """Распознанная 3D-цель под курсором в инструменте «Рулетка / Измерение»."""

    point: np.ndarray
    kind: str  # "corner" | "edge_mid" | "face_center" | "surface" | "hole" | "center" | "floor" | "space"
    description: str
    panel: Any = None
    face_id: str = ""
    face_label: str = ""
    face_normal: np.ndarray | None = None
    face_dims: tuple[float, float] = (0.0, 0.0)
    edge_length: float = 0.0
    hole_info: dict[str, Any] | None = None

    @property
    def is_face(self) -> bool:
        return self.kind in ("surface", "face_center") and self.face_normal is not None

    @property
    def is_hole(self) -> bool:
        return self.kind == "hole" and self.hole_info is not None

    @property
    def is_edge(self) -> bool:
        return self.kind == "edge_mid" and self.edge_length > 0.0

    def format_hover_summary(self) -> str:
        """Краткая информационная сводка об объекте под курсором (без клика, как в QymCAD)."""
        pname = str(getattr(self.panel, "name", "") or "")
        prefix = f"{pname}: " if pname else ""
        if self.is_hole and self.hole_info:
            diam = self.hole_info["diameter"]
            depth = self.hole_info["depth"]
            axis = self.hole_info["axis"]
            m_min = self.hole_info["margin_min"]
            m_max = self.hole_info["margin_max"]
            return (
                f"{prefix}Отверстие Ø{diam:.1f}×{depth:.0f} мм (ось {axis}) | "
                f"От края: {m_min:.1f} / {m_max:.1f} мм"
            )
        if self.is_edge:
            return f"{prefix}Ребро L = {self.edge_length:.1f} мм"
        if self.is_face:
            da, db = self.face_dims
            flabel = self.face_label or "Грань"
            if da > 0.0 and db > 0.0:
                return f"{prefix}{flabel} ({da:.0f}×{db:.0f} мм)"
            return f"{prefix}{flabel}"
        return self.description


def build_measure_target(
    point: np.ndarray,
    description: str,
    kind: str,
    panel: Any = None,
    meta: dict[str, Any] | None = None,
) -> MeasureTarget:
    """Создаёт обогащённый `MeasureTarget` из данных привязки или пересечения луча."""
    pt = np.asarray(point, dtype=float)
    meta = meta or {}
    face_id = ""
    face_label = ""
    face_normal = None
    face_dims = (0.0, 0.0)
    edge_length = float(meta.get("edge_length", 0.0) or 0.0)
    hole_info = None

    if panel is not None and kind in ("surface", "face_center"):
        face_id, face_label, face_normal, face_dims = detect_panel_face_at_point(panel, pt)
    elif panel is not None and kind == "hole" and "hole" in meta:
        hole_info = inspect_hole_on_panel(panel, meta["hole"])

    return MeasureTarget(
        point=pt,
        kind=kind,
        description=description,
        panel=panel,
        face_id=face_id,
        face_label=face_label,
        face_normal=face_normal,
        face_dims=face_dims,
        edge_length=edge_length,
        hole_info=hole_info,
    )


@dataclass
class SmartMeasurementResult:
    """Результат вычисления измерения между двумя целями `t1` и `t2`."""

    mode: str  # "parallel_faces" | "angled_faces" | "hole_step" | "hole_to_face" | "point_to_point"
    dimension_line: DimensionLine
    angle_dimension: DimensionAngle | None
    status_message: str
    hud_summary: str
    allows_third_point_angle: bool = True


def compute_smart_measurement(t1: MeasureTarget, t2: MeasureTarget) -> SmartMeasurementResult:
    """Контекстное вычисление размера между двумя указанными объектами (по принципу QymCAD):
    - Две параллельные грани → перпендикулярное расстояние «в свету» (или толщина/габарит одной детали);
    - Две непараллельные грани → угол между гранями + расстояние;
    - Два отверстия → межцентровый шаг сверловки (с проверкой кратности 32 мм);
    - Отверстие и грань → перпендикулярное расстояние от центра отверстия до плоскости грани;
    - Две точки/вершины/ребра → линейное расстояние и проекции ΔX, ΔY, ΔZ.
    """
    p1 = np.asarray(t1.point, dtype=float)
    p2 = np.asarray(t2.point, dtype=float)
    direct_vec = p2 - p1
    direct_dist = float(np.linalg.norm(direct_vec))

    # 1. Грань + Грань
    if t1.is_face and t2.is_face and t1.face_normal is not None and t2.face_normal is not None:
        n1 = t1.face_normal
        n2 = t2.face_normal
        dot_n = float(np.dot(n1, n2))
        abs_dot = abs(dot_n)

        if abs_dot >= 0.998:
            signed_perp = float(np.dot(direct_vec, n1))
            perp_dist = abs(signed_perp)
            if perp_dist > 0.05:
                p2_perp = p1 + signed_perp * n1
                same_panel = (t1.panel is not None) and (t1.panel is t2.panel)
                prefix_label = "Толщина/габарит" if same_panel else "В свету"
                main_title = f"{prefix_label}: {perp_dist:.1f} мм"
                if abs(direct_dist - perp_dist) > 0.5:
                    sub_lbl = f"По нормали граней (по прямой: {direct_dist:.1f} мм)"
                else:
                    dx, dy, dz = abs(float(p2_perp[0] - p1[0])), abs(float(p2_perp[1] - p1[1])), abs(float(p2_perp[2] - p1[2]))
                    sub_lbl = f"ΔX: {dx:.1f}  ΔY: {dy:.1f}  ΔZ: {dz:.1f}"

                dim = DimensionLine(
                    pt1=p1,
                    pt2=p2_perp,
                    color=(0.16, 0.80, 0.45),
                    name=main_title,
                    sub_label=sub_lbl,
                )
                status = (
                    f"📏 {main_title} ({t1.format_hover_summary()} ↔ {t2.format_hover_summary()}) | "
                    f"По прямой: {direct_dist:.1f} мм"
                )
                return SmartMeasurementResult(
                    mode="parallel_faces",
                    dimension_line=dim,
                    angle_dimension=None,
                    status_message=status,
                    hud_summary=main_title,
                    allows_third_point_angle=False,
                )
        else:
            face_angle = float(math.degrees(math.acos(max(0.0, min(1.0, abs_dot)))))
            mid = 0.5 * (p1 + p2)
            arm_len = max(40.0, min(120.0, direct_dist * 0.5 if direct_dist > 10.0 else 60.0))
            inward1 = -n1 if float(np.dot(direct_vec, n1)) > 0 else n1
            inward2 = -n2 if float(np.dot(-direct_vec, n2)) > 0 else n2
            ang_dim = DimensionAngle(
                pt1=mid + inward1 * arm_len,
                vertex=mid,
                pt3=mid + inward2 * arm_len,
                name=f"Угол граней: {face_angle:.1f}°",
            )
            right_str = " [Прямой 90°]" if abs(face_angle - 90.0) < 0.35 else ""
            main_title = f"∠ граней: {face_angle:.1f}°{right_str}"
            sub_lbl = f"Расстояние между точками: {direct_dist:.1f} мм"
            dim = DimensionLine(
                pt1=p1,
                pt2=p2,
                color=(0.98, 0.73, 0.01),
                name=main_title,
                sub_label=sub_lbl,
            )
            status = f"📐 Угол между гранями: {face_angle:.1f}°{right_str} | Расстояние: {direct_dist:.1f} мм"
            return SmartMeasurementResult(
                mode="angled_faces",
                dimension_line=dim,
                angle_dimension=ang_dim,
                status_message=status,
                hud_summary=main_title,
                allows_third_point_angle=False,
            )

    # 2. Отверстие + Отверстие (межцентровый шаг)
    if t1.is_hole and t2.is_hole and t1.hole_info and t2.hole_info:
        d1 = t1.hole_info["diameter"]
        d2 = t2.hole_info["diameter"]
        mult32 = round(direct_dist / 32.0) if direct_dist >= 31.5 else 0
        is_sys32 = mult32 >= 1 and abs(direct_dist - mult32 * 32.0) <= 0.2
        sys32_tag = f" [Система 32: {int(mult32)}×32]" if is_sys32 else ""
        main_title = f"Шаг Ø{d1:.0f}→Ø{d2:.0f}: {direct_dist:.1f} мм"
        dx, dy, dz = abs(float(direct_vec[0])), abs(float(direct_vec[1])), abs(float(direct_vec[2]))
        sub_lbl = f"ΔX: {dx:.1f}  ΔY: {dy:.1f}  ΔZ: {dz:.1f}{sys32_tag}"
        dim = DimensionLine(
            pt1=p1,
            pt2=p2,
            color=(0.22, 0.74, 0.97),
            name=main_title,
            sub_label=sub_lbl,
        )
        status = f"🕳 {main_title}{sys32_tag} (ΔX: {dx:.1f}, ΔY: {dy:.1f}, ΔZ: {dz:.1f})"
        return SmartMeasurementResult(
            mode="hole_step",
            dimension_line=dim,
            angle_dimension=None,
            status_message=status,
            hud_summary=f"{main_title}{sys32_tag}",
            allows_third_point_angle=False,
        )

    # 3. Отверстие + Грань (или Грань + Отверстие)
    if (t1.is_hole and t2.is_face) or (t1.is_face and t2.is_hole):
        hole_t = t1 if t1.is_hole else t2
        face_t = t2 if t2.is_face else t1
        assert face_t.face_normal is not None
        fn = face_t.face_normal
        h_pt = np.asarray(hole_t.point, dtype=float)
        f_pt = np.asarray(face_t.point, dtype=float)
        signed_d = float(np.dot(f_pt - h_pt, fn))
        perp_dist = abs(signed_d)
        if perp_dist > 0.05:
            f_proj = h_pt + signed_d * fn
            diam = hole_t.hole_info["diameter"] if hole_t.hole_info else 0.0
            main_title = f"До грани от Ø{diam:.0f}: {perp_dist:.1f} мм"
            sub_lbl = f"{face_t.face_label or 'Грань'} (по прямой: {direct_dist:.1f} мм)"
            dim = DimensionLine(
                pt1=h_pt,
                pt2=f_proj,
                color=(0.65, 0.55, 0.98),
                name=main_title,
                sub_label=sub_lbl,
            )
            status = f"📏 Отступ отверстия Ø{diam:.1f} до грани «{face_t.face_label}»: {perp_dist:.1f} мм"
            return SmartMeasurementResult(
                mode="hole_to_face",
                dimension_line=dim,
                angle_dimension=None,
                status_message=status,
                hud_summary=main_title,
                allows_third_point_angle=False,
            )

    # 4. Стандартное измерение точка ↔ точка (с возможностью 3-й точкой померить угол)
    dim = DimensionLine(pt1=p1, pt2=p2)
    dx, dy, dz = abs(float(direct_vec[0])), abs(float(direct_vec[1])), abs(float(direct_vec[2]))
    status = f"📏 Отрезок: {direct_dist:.1f} мм (ΔX: {dx:.1f}, ΔY: {dy:.1f}, ΔZ: {dz:.1f})"
    return SmartMeasurementResult(
        mode="point_to_point",
        dimension_line=dim,
        angle_dimension=None,
        status_message=status,
        hud_summary=f"{direct_dist:.1f} мм",
        allows_third_point_angle=True,
    )
