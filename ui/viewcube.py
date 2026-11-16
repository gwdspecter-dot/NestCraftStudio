# -*- coding: utf-8 -*-
"""Интерактивный 3D ViewCube в стиле NestCraft Studio:
монолитная фасочная геометрия (6 граней + 12 фасок рёбер + 8 фасок углов),
современный безрамочный дизайн с компасом, векторной кнопкой «Домой» и 3D-триадой осей X/Y/Z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

# Размер виджета куба (логический px) и отступ от правого верхнего угла вьюпорта
CUBE_SIZE = 104
CUBE_MARGIN = 18
HOME_BTN_SIZE = 24
CHAMFER = 0.25  # ширина фаски рёбер и углов в долях полуребра (c = 1 - CHAMFER = 0.75)
ANIM_MS = 150

# Полувысота усечённой пирамиды при FOV=45° на единичном расстоянии: tan(22.5°).
# Совпадение коэффициента ortho scale с tan(22.5°) устраняет скачок масштаба при переходе Perspective <-> Ortho.
ORTHO_HALF_TAN = math.tan(math.radians(22.5))

# Имена граней (мировые оси NestCraft: X вправо, Y вверх, Z на нас в виде Спереди)
FACE_TARGETS: dict[str, tuple[float, float, bool, str]] = {
    "front": (0.0, 0.0, True, "Спереди"),
    "back": (0.0, 180.0, True, "Сзади"),
    "right": (0.0, -90.0, True, "Справа"),
    "left": (0.0, 90.0, True, "Слева"),
    "top": (90.0, 0.0, True, "Сверху"),
    "bottom": (-90.0, 0.0, True, "Снизу"),
}

FACE_CAPTIONS: dict[str, str] = {
    "front": "СПЕРЕДИ",
    "back": "СЗАДИ",
    "right": "СПРАВА",
    "left": "СЛЕВА",
    "top": "СВЕРХУ",
    "bottom": "СНИЗУ",
}

FACE_NORMALS: dict[str, tuple[float, float, float]] = {
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "bottom": (0.0, -1.0, 0.0),
}

ISO_TARGET: tuple[float, float, bool, str] = (25.0, -35.0, False, "Изометрия")


def _rot_matrix(rx_deg: float, ry_deg: float) -> np.ndarray:
    """3×3: Ry затем Rx (как viewport: rotate_x * rotate_y на столбцах = Ry сначала на векторе)."""
    ax = math.radians(float(rx_deg))
    ay = math.radians(float(ry_deg))
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    return rx @ ry


def pan_for_pivot(
    rot_x: float,
    rot_y: float,
    pivot: tuple[float, float, float],
) -> tuple[float, float]:
    """Вычисляет (pan_x, pan_y), при которых мировая 3D-точка `pivot` проецируется в центр экрана (0, 0)."""
    R = _rot_matrix(rot_x, rot_y)
    rp = R @ np.array([float(pivot[0]), float(pivot[1]), float(pivot[2])], dtype=float)
    return -float(rp[0]), -float(rp[1])


def pivot_from_pan(
    rot_x: float,
    rot_y: float,
    pan_x: float,
    pan_y: float,
    ref_point: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Восстанавливает мировую 3D-точку в центре экрана по текущим (rot_x, rot_y, pan_x, pan_y)
    на глубине опорной точки `ref_point` (удовлетворяет тождеству pan_for_pivot(rot, pivot) == pan).
    """
    R = _rot_matrix(rot_x, rot_y)
    ref_v = R @ np.array([float(ref_point[0]), float(ref_point[1]), float(ref_point[2])], dtype=float)
    z_view = float(ref_v[2])
    rt = np.array(
        [
            [float(R[0][0]), float(R[1][0]), float(R[2][0])],
            [float(R[0][1]), float(R[1][1]), float(R[2][1])],
            [float(R[0][2]), float(R[1][2]), float(R[2][2])],
        ],
        dtype=float,
    )
    w_pt = rt @ np.array([-float(pan_x), -float(pan_y), z_view], dtype=float)
    return float(w_pt[0]), float(w_pt[1]), float(w_pt[2])


def blend_projection_matrices(
    proj_persp: np.ndarray,
    proj_ortho: np.ndarray,
    ortho_blend: float,
    zoom_dist: float,
) -> np.ndarray:
    """Плавное однородное смешивание матриц Perspective и Ortho без скачка масштаба на глубине `zoom_dist`."""
    b = max(0.0, min(1.0, float(ortho_blend)))
    if b <= 1e-4:
        return proj_persp
    if b >= 1.0 - 1e-4:
        return proj_ortho
    d = max(abs(float(zoom_dist)), 1.0)
    a_w = (1.0 - b) / d
    return np.asarray(proj_persp * a_w + proj_ortho * b, dtype=np.float32)


def _face_vertices(scale: float = 1.0 - CHAMFER) -> dict[str, list[tuple[float, float, float]]]:
    """Углы квадратной площадки каждой грани фасочного куба (±c, ±c, ±1)."""
    s = float(scale)
    return {
        "front": [(-s, -s, 1.0), (s, -s, 1.0), (s, s, 1.0), (-s, s, 1.0)],
        "back": [(s, -s, -1.0), (-s, -s, -1.0), (-s, s, -1.0), (s, s, -1.0)],
        "right": [(1.0, -s, s), (1.0, -s, -s), (1.0, s, -s), (1.0, s, s)],
        "left": [(-1.0, -s, -s), (-1.0, -s, s), (-1.0, s, s), (-1.0, s, -s)],
        "top": [(-s, 1.0, s), (s, 1.0, s), (s, 1.0, -s), (-s, 1.0, -s)],
        "bottom": [(-s, -1.0, -s), (s, -1.0, -s), (s, -1.0, s), (-s, -1.0, s)],
    }


def _edge_definitions() -> list[tuple[str, tuple[float, float, float], tuple[float, float, float], str, str]]:
    """Возвращает список (edge_id, vert_a, vert_b, face_a, face_b) для всех 12 рёбер."""
    verts = {
        "LBF": (-1.0, -1.0, 1.0),
        "RBF": (1.0, -1.0, 1.0),
        "RTF": (1.0, 1.0, 1.0),
        "LTF": (-1.0, 1.0, 1.0),
        "LBB": (-1.0, -1.0, -1.0),
        "RBB": (1.0, -1.0, -1.0),
        "RTB": (1.0, 1.0, -1.0),
        "LTB": (-1.0, 1.0, -1.0),
    }
    pairs = [
        ("e_front_bottom", "LBF", "RBF", "front", "bottom"),
        ("e_front_top", "LTF", "RTF", "front", "top"),
        ("e_front_left", "LBF", "LTF", "front", "left"),
        ("e_front_right", "RBF", "RTF", "front", "right"),
        ("e_back_bottom", "LBB", "RBB", "back", "bottom"),
        ("e_back_top", "LTB", "RTB", "back", "top"),
        ("e_back_left", "LBB", "LTB", "back", "left"),
        ("e_back_right", "RBB", "RTB", "back", "right"),
        ("e_top_left", "LTF", "LTB", "top", "left"),
        ("e_top_right", "RTF", "RTB", "top", "right"),
        ("e_bottom_left", "LBF", "LBB", "bottom", "left"),
        ("e_bottom_right", "RBF", "RBB", "bottom", "right"),
    ]
    return [(eid, verts[ka], verts[kb], fa, fb) for eid, ka, kb, fa, fb in pairs]


def _edge_midpoints() -> list[tuple[str, tuple[float, float, float], str, str]]:
    """(edge_id, midpoint, face_a, face_b)."""
    edges = []
    for eid, va, vb, fa, fb in _edge_definitions():
        mid = ((va[0] + vb[0]) * 0.5, (va[1] + vb[1]) * 0.5, (va[2] + vb[2]) * 0.5)
        edges.append((eid, mid, fa, fb))
    return edges


def _edge_bevel_quad_3d(
    va: tuple[float, float, float],
    vb: tuple[float, float, float],
    fa: str,
    fb: str,
    chamfer: float = CHAMFER,
) -> tuple[list[tuple[float, float, float]], tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Возвращает плоский прямоугольник 45°-фаски ребра, центр осевой линии и концы осевой линии."""
    c = 1.0 - float(chamfer)
    t_vec = ((vb[0] - va[0]) * 0.5, (vb[1] - va[1]) * 0.5, (vb[2] - va[2]) * 0.5)
    na = FACE_NORMALS[fa]
    nb = FACE_NORMALS[fb]
    # Рёбра соседних квадратных граней: na + c*nb и nb + c*na
    base_a = (na[0] + c * nb[0], na[1] + c * nb[1], na[2] + c * nb[2])
    base_b = (nb[0] + c * na[0], nb[1] + c * na[1], nb[2] + c * na[2])
    pa0 = (base_a[0] - c * t_vec[0], base_a[1] - c * t_vec[1], base_a[2] - c * t_vec[2])
    pa1 = (base_a[0] + c * t_vec[0], base_a[1] + c * t_vec[1], base_a[2] + c * t_vec[2])
    pb1 = (base_b[0] + c * t_vec[0], base_b[1] + c * t_vec[1], base_b[2] + c * t_vec[2])
    pb0 = (base_b[0] - c * t_vec[0], base_b[1] - c * t_vec[1], base_b[2] - c * t_vec[2])
    mid_base = (0.5 * (base_a[0] + base_b[0]), 0.5 * (base_a[1] + base_b[1]), 0.5 * (base_a[2] + base_b[2]))
    seg_a = (mid_base[0] - c * t_vec[0], mid_base[1] - c * t_vec[1], mid_base[2] - c * t_vec[2])
    seg_b = (mid_base[0] + c * t_vec[0], mid_base[1] + c * t_vec[1], mid_base[2] + c * t_vec[2])
    return [pa0, pa1, pb1, pb0], mid_base, seg_a, seg_b


def _corner_points() -> list[tuple[str, tuple[float, float, float], tuple[str, str, str]]]:
    return [
        ("c_LTF", (-1.0, 1.0, 1.0), ("left", "top", "front")),
        ("c_RTF", (1.0, 1.0, 1.0), ("right", "top", "front")),
        ("c_LBF", (-1.0, -1.0, 1.0), ("left", "bottom", "front")),
        ("c_RBF", (1.0, -1.0, 1.0), ("right", "bottom", "front")),
        ("c_LTB", (-1.0, 1.0, -1.0), ("left", "top", "back")),
        ("c_RTB", (1.0, 1.0, -1.0), ("right", "top", "back")),
        ("c_LBB", (-1.0, -1.0, -1.0), ("left", "bottom", "back")),
        ("c_RBB", (1.0, -1.0, -1.0), ("right", "bottom", "back")),
    ]


def _corner_bevel_tri_3d(
    pt: tuple[float, float, float],
    chamfer: float = CHAMFER,
) -> tuple[list[tuple[float, float, float]], tuple[float, float, float]]:
    """Равносторонний треугольник угловой фаски и его геометрический центр."""
    sx, sy, sz = float(pt[0]), float(pt[1]), float(pt[2])
    c = 1.0 - float(chamfer)
    v_z = (sx * c, sy * c, sz)
    v_x = (sx, sy * c, sz * c)
    v_y = (sx * c, sy, sz * c)
    center = (
        (v_z[0] + v_x[0] + v_y[0]) / 3.0,
        (v_z[1] + v_x[1] + v_y[1]) / 3.0,
        (v_z[2] + v_x[2] + v_y[2]) / 3.0,
    )
    return [v_z, v_x, v_y], center


def _angles_from_direction(
    nx: float,
    ny: float,
    nz: float,
    fallback_ry: float = 0.0,
) -> tuple[float, float]:
    """Точные углы камеры (rot_x, rot_y) для взгляда снаружи вдоль нормали (nx, ny, nz)."""
    horiz = math.hypot(float(nx), float(nz))
    rx = math.degrees(math.atan2(float(ny), horiz))
    if horiz < 1e-9:
        ry = float(fallback_ry)
    else:
        ry = math.degrees(math.atan2(-float(nx), float(nz)))
        if abs(ry + 180.0) < 1e-6:
            ry = 180.0
    return round(rx, 4), round(ry, 4)


def _blend_angles(targets: list[tuple[float, float, bool]]) -> tuple[float, float, bool]:
    """Совместимый хелпер: перевод углов (rx, ry) в единичные 3D-направления и расчёт точного среднего вектора."""
    if not targets:
        return ISO_TARGET[0], ISO_TARGET[1], ISO_TARGET[2]
    sx = sy = sz = 0.0
    for rx_deg, ry_deg, _ortho in targets:
        rx_r = math.radians(float(rx_deg))
        ry_r = math.radians(float(ry_deg))
        ch = math.cos(rx_r)
        sx += -math.sin(ry_r) * ch
        sy += math.sin(rx_r)
        sz += math.cos(ry_r) * ch
    rx, ry = _angles_from_direction(sx, sy, sz)
    ortho = all(t[2] for t in targets)
    return rx, ry, ortho


def target_for_hit(kind: str, key: str) -> tuple[float, float, bool, str]:
    """Возвращает (rot_x, rot_y, is_ortho, label) для клика по грани, ребру, углу или Home."""
    if kind == "home" or key == "home":
        return ISO_TARGET
    if kind == "face" and key in FACE_TARGETS:
        return FACE_TARGETS[key]
    if kind == "edge":
        for eid, mid, fa, fb in _edge_midpoints():
            if eid == key:
                ta = FACE_TARGETS[fa]
                tb = FACE_TARGETS[fb]
                rx, ry = _angles_from_direction(mid[0], mid[1], mid[2])
                return rx, ry, True, f"{ta[3]} + {tb[3]}"
    if kind == "corner":
        for cid, pt, faces in _corner_points():
            if cid == key:
                rx, ry = _angles_from_direction(pt[0], pt[1], pt[2])
                label = " + ".join(FACE_TARGETS[f][3] for f in faces)
                return rx, ry, False, f"Угол ({label})"
    return ISO_TARGET


@dataclass
class CubeLayout:
    cx: float
    cy: float
    half: float
    home_rect: tuple[float, float, float, float]  # x, y, w, h


def layout_for_widget(width: int, height: int) -> CubeLayout:
    """Правый верхний угол 3D-вьюпорта (как в Fusion 360 / Onshape / QymCAD)."""
    half = CUBE_SIZE * 0.42
    cx = float(width) - CUBE_MARGIN - CUBE_SIZE * 0.5 - 8.0
    cy = float(CUBE_MARGIN) + CUBE_SIZE * 0.5 + 8.0
    # Кнопка «Домой» аккуратно слева-сверху у кольца куба
    hx = cx - half - HOME_BTN_SIZE - 8.0
    hy = cy - half - 6.0
    return CubeLayout(cx=cx, cy=cy, half=half, home_rect=(hx, hy, float(HOME_BTN_SIZE), float(HOME_BTN_SIZE)))


def is_in_viewcube_region(mx: float, my: float, layout: CubeLayout) -> bool:
    """Быстрая проверка попадания курсора в область ViewCube или кнопки Home."""
    pad = layout.half + 20.0
    hx, hy, hw, hh = layout.home_rect
    in_cube = (layout.cx - pad <= mx <= layout.cx + pad and layout.cy - pad <= my <= layout.cy + pad + 18.0)
    in_home = (hx - 3.0 <= mx <= hx + hw + 3.0 and hy - 3.0 <= my <= hy + hh + 3.0)
    return in_cube or in_home


def project_point(
    p: tuple[float, float, float],
    R: np.ndarray,
    layout: CubeLayout,
) -> tuple[float, float, float]:
    """Мировые координаты куба → экран (x, y) + глубина z (больше = ближе к камере)."""
    v = R @ np.array([p[0], p[1], p[2]], dtype=float)
    sx = layout.cx + float(v[0]) * layout.half
    sy = layout.cy - float(v[1]) * layout.half  # Y вверх на экране
    depth = float(v[2])
    return sx, sy, depth


def build_drawable(rot_x: float, rot_y: float, layout: CubeLayout) -> dict[str, Any]:
    """Строит замкнутый фасочный 3D-многогранник (6 квадратных граней, 12 прямоугольных фасок рёбер,
    8 равносторонних треугольных фасок углов), а также синхронизированную 3D-триаду осей X/Y/Z.
    """
    R = _rot_matrix(rot_x, rot_y)
    face_squares = _face_vertices(1.0 - CHAMFER)

    # Направленный студийный свет сверху-спереди-слева
    light = np.array([-0.32, 0.72, 0.61], dtype=float)
    inv_sqrt2 = 1.0 / math.sqrt(2.0)
    inv_sqrt3 = 1.0 / math.sqrt(3.0)

    faces_out = []
    for name, verts in face_squares.items():
        pts2 = [project_point(v, R, layout) for v in verts]
        n_world = FACE_NORMALS[name]
        nv = R @ np.array(n_world, dtype=float)
        depth = float(nv[2])
        shade = max(0.0, float(nv[0]) * float(light[0]) + float(nv[1]) * float(light[1]) + float(nv[2]) * float(light[2]))
        cx = sum(p[0] for p in pts2) / 4.0
        cy = sum(p[1] for p in pts2) / 4.0
        label = FACE_TARGETS[name][3]
        poly_xy = [(p[0], p[1]) for p in pts2]
        faces_out.append(
            {
                "id": name,
                "kind": "face",
                "poly": poly_xy,
                "inner_poly": poly_xy,
                "center": (cx, cy),
                "depth": depth,
                "shade": shade,
                "normal_view": (float(nv[0]), float(nv[1]), float(nv[2])),
                "visible": depth > 0.02,
                "label": label,
                "caption": FACE_CAPTIONS.get(name, label.upper()),
            }
        )
    faces_out.sort(key=lambda f: f["depth"])

    edges_out = []
    for eid, va, vb, fa, fb in _edge_definitions():
        quad_3d, mid_3d, seg_a_3d, seg_b_3d = _edge_bevel_quad_3d(va, vb, fa, fb, CHAMFER)
        q2 = [project_point(p, R, layout) for p in quad_3d]
        sx, sy, _ = project_point(mid_3d, R, layout)
        sa = project_point(seg_a_3d, R, layout)
        sb = project_point(seg_b_3d, R, layout)

        na = FACE_NORMALS[fa]
        nb = FACE_NORMALS[fb]
        n_world = ((na[0] + nb[0]) * inv_sqrt2, (na[1] + nb[1]) * inv_sqrt2, (na[2] + nb[2]) * inv_sqrt2)
        nv = R @ np.array(n_world, dtype=float)
        nz = float(nv[2])
        shade = max(0.0, float(nv[0]) * float(light[0]) + float(nv[1]) * float(light[1]) + float(nv[2]) * float(light[2]))

        edges_out.append(
            {
                "id": eid,
                "kind": "edge",
                "pos": (sx, sy),
                "seg_a": (sa[0], sa[1]),
                "seg_b": (sb[0], sb[1]),
                "poly": [(p[0], p[1]) for p in q2],
                "depth": nz,
                "shade": shade,
                "visible": nz > 0.015,
                "faces": (fa, fb),
            }
        )
    edges_out.sort(key=lambda e: e["depth"])

    corners_out = []
    for cid, pt, faces in _corner_points():
        tri_3d, c_3d = _corner_bevel_tri_3d(pt, CHAMFER)
        t2 = [project_point(p, R, layout) for p in tri_3d]
        sx, sy, _ = project_point(c_3d, R, layout)

        n_world = (float(pt[0]) * inv_sqrt3, float(pt[1]) * inv_sqrt3, float(pt[2]) * inv_sqrt3)
        nv = R @ np.array(n_world, dtype=float)
        nz = float(nv[2])
        shade = max(0.0, float(nv[0]) * float(light[0]) + float(nv[1]) * float(light[1]) + float(nv[2]) * float(light[2]))

        corners_out.append(
            {
                "id": cid,
                "kind": "corner",
                "pos": (sx, sy),
                "poly": [(p[0], p[1]) for p in t2],
                "depth": nz,
                "shade": shade,
                "visible": nz > 0.015,
                "faces": faces,
            }
        )
    corners_out.sort(key=lambda c: c["depth"])

    # Компас мировых осей X/Y/Z — закреплён в чистой точке слева-снизу у компасного кольца,
    # чтобы никогда не перекрывать грани самого ViewCube под любым углом поворота.
    triad_ox = layout.cx - layout.half - 16.0
    triad_oy = layout.cy + layout.half + 2.0
    axis_len = 16.0
    axes_spec = [
        ("X", (1.0, 0.0, 0.0), (239, 68, 68)),
        ("Y", (0.0, 1.0, 0.0), (16, 185, 129)),
        ("Z", (0.0, 0.0, 1.0), (14, 165, 233)),
    ]
    axes_out = []
    for axis_name, vec, rgb in axes_spec:
        rv = R @ np.array(vec, dtype=float)
        ex = triad_ox + float(rv[0]) * axis_len
        ey = triad_oy - float(rv[1]) * axis_len
        ez = float(rv[2])
        axes_out.append(
            {
                "axis": axis_name,
                "start": (triad_ox, triad_oy),
                "end": (ex, ey),
                "depth": ez,
                "rgb": rgb,
            }
        )
    axes_out.sort(key=lambda a: a["depth"])

    return {
        "faces": faces_out,
        "edges": edges_out,
        "corners": corners_out,
        "axes": axes_out,
        "layout": layout,
        "R": R,
    }


def _dist_point_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def hit_test(mx: float, my: float, drawable: dict[str, Any], layout: CubeLayout) -> tuple[str, str] | None:
    """Возвращает (kind, id) или None. Приоритет: home > видимый corner > видимый edge > видимая face."""
    hx, hy, hw, hh = layout.home_rect
    if hx <= mx <= hx + hw and hy <= my <= hy + hh:
        return "home", "home"

    # 1. Видимые угловые треугольные фаски (точное попадание в полигон или <= 8 px от центра угла)
    for c in reversed(drawable["corners"]):
        if not c.get("visible", c["depth"] > 0.015):
            continue
        poly = c.get("poly") or []
        if len(poly) >= 3 and _point_in_poly(mx, my, poly):
            return "corner", c["id"]

    # 2. Видимые 45°-фаски рёбер (точное попадание в прямоугольник фаски или <= 4.5 px от осевой)
    for e in reversed(drawable["edges"]):
        if not e.get("visible", e["depth"] > 0.015):
            continue
        poly = e.get("poly") or []
        if len(poly) >= 3 and _point_in_poly(mx, my, poly):
            return "edge", e["id"]

    # 3. Запасной допуск по близости к видимому углу или ребру (для удобства попадания под острыми углами)
    best_corner = None
    best_cd = 7.5
    for c in reversed(drawable["corners"]):
        if not c.get("visible", c["depth"] > 0.015):
            continue
        px, py = c["pos"]
        d = math.hypot(mx - px, my - py)
        if d < best_cd:
            best_cd = d
            best_corner = ("corner", c["id"])
    if best_corner:
        return best_corner

    best_edge = None
    best_ed = 4.5
    for e in reversed(drawable["edges"]):
        if not e.get("visible", e["depth"] > 0.015):
            continue
        if "seg_a" in e and "seg_b" in e:
            ax, ay = e["seg_a"]
            bx, by = e["seg_b"]
            d_seg = _dist_point_to_segment(mx, my, ax, ay, bx, by)
        else:
            px, py = e["pos"]
            d_seg = math.hypot(mx - px, my - py)
        if d_seg < best_ed:
            best_ed = d_seg
            best_edge = ("edge", e["id"])
    if best_edge:
        return best_edge

    # 4. Видимые квадратные грани
    faces = drawable["faces"]
    if not faces:
        return None
    for f in reversed(faces):
        if not f.get("visible", f["depth"] > 0.02):
            continue
        if _point_in_poly(mx, my, f["poly"]):
            return "face", f["id"]
    return None


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _is_dark_ui_theme() -> bool:
    try:
        from ui.theme import current_theme

        return current_theme().name == "dark"
    except Exception:
        return False


def _shade_slate(shade: float, depth: float, dark_mode: bool, role: str) -> tuple[int, int, int]:
    """Архитектурный сатиновый металл/керамика в духе NestCraft (без «радуги»)."""
    # Комбинируем студийное освещение (shade) и фронтальную глубину (depth)
    k = max(0.0, min(1.0, 0.58 * float(shade) + 0.42 * max(0.0, float(depth))))
    if dark_mode:
        # Благородный тёмно-графитовый алюминий для Dark-темы
        if role == "face":
            base = 64 + int(k * 36)
        elif role == "edge":
            base = 52 + int(k * 30)
        else:
            base = 44 + int(k * 26)
        return max(0, base - 4), base, min(255, base + 7)
    # Чистый архитектурный светло-серый алюминий для Light-темы (как панели NestCraft #eef0f3 / #e4e7ec)
    if role == "face":
        base = 216 + int(k * 32)
    elif role == "edge":
        base = 196 + int(k * 28)
    else:
        base = 178 + int(k * 26)
    return max(0, base - 4), base, min(255, base + 6)


def draw_viewcube(
    painter,
    rot_x: float,
    rot_y: float,
    width: int,
    height: int,
    hover: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Рисует современный фасочный 3D ViewCube в едином стиле NestCraft Studio."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import (
        QBrush,
        QColor,
        QFont,
        QLinearGradient,
        QPainterPath,
        QPen,
        QRadialGradient,
    )

    layout = layout_for_widget(width, height)
    drawable = build_drawable(rot_x, rot_y, layout)
    dark_mode = _is_dark_ui_theme()

    # 1. Мягкая радиальная тень под кубом — без громоздкой прямоугольной карточки
    shadow_r = layout.half * 1.48
    shadow_grad = QRadialGradient(layout.cx, layout.cy + 4.0, shadow_r)
    shadow_grad.setColorAt(0.0, QColor(15, 23, 42, 34))
    shadow_grad.setColorAt(0.68, QColor(15, 23, 42, 14))
    shadow_grad.setColorAt(1.0, QColor(15, 23, 42, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(shadow_grad))
    painter.drawEllipse(
        QPointF(layout.cx, layout.cy + 4.0),
        shadow_r,
        shadow_r,
    )

    # 2. Тонкое архитектурное кольцо компаса с 4 рисками
    ring_r = layout.half + 10.5
    ring_col = QColor(100, 116, 139, 92) if not dark_mode else QColor(148, 163, 184, 80)
    painter.setPen(QPen(ring_col, 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(layout.cx, layout.cy), ring_r, ring_r)
    for deg in (0, 90, 180, 270):
        rad = math.radians(deg + float(rot_y))
        rx_u, ry_u = math.cos(rad), math.sin(rad)
        p1 = QPointF(layout.cx + rx_u * (ring_r - 3.0), layout.cy + ry_u * (ring_r - 3.0))
        p2 = QPointF(layout.cx + rx_u * (ring_r + 2.5), layout.cy + ry_u * (ring_r + 2.5))
        painter.drawLine(p1, p2)

    # 3. Собираем все видимые фасеты (6 граней + 12 фасок рёбер + 8 фасок углов)
    #    в единый список без взаимного перекрытия.
    seam_col = QColor(100, 116, 139, 170) if not dark_mode else QColor(71, 85, 105, 220)
    hover_face_pen = QPen(QColor(0, 120, 212), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    hover_bevel_pen = QPen(QColor(249, 115, 22), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    idle_pen = QPen(seam_col, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    facets_to_draw: list[tuple[float, str, dict[str, Any]]] = []
    for f in drawable["faces"]:
        if f.get("visible", f["depth"] > 0.02):
            facets_to_draw.append((float(f["depth"]), "face", f))
    for e in drawable["edges"]:
        if e.get("visible", e["depth"] > 0.015):
            facets_to_draw.append((float(e["depth"]), "edge", e))
    for c in drawable["corners"]:
        if c.get("visible", c["depth"] > 0.015):
            facets_to_draw.append((float(c["depth"]), "corner", c))

    facets_to_draw.sort(key=lambda item: item[0])

    for _depth, role, item in facets_to_draw:
        poly = item["poly"]
        if len(poly) < 3:
            continue
        path = QPainterPath()
        path.moveTo(poly[0][0], poly[0][1])
        for p in poly[1:]:
            path.lineTo(p[0], p[1])
        path.closeSubpath()

        is_hover = hover == (role, item["id"])
        ys = [p[1] for p in poly]
        xs = [p[0] for p in poly]
        gx0, gy0 = 0.5 * (min(xs) + max(xs)), min(ys)
        gx1, gy1 = gx0, max(ys)

        if is_hover and role == "face":
            # Фирменный синий акцент NestCraft (#38bdf8 -> #0078d4)
            grad = QLinearGradient(gx0, gy0, gx1, gy1)
            grad.setColorAt(0.0, QColor(56, 189, 248, 245))
            grad.setColorAt(1.0, QColor(0, 120, 212, 245))
            painter.setBrush(QBrush(grad))
            painter.setPen(hover_face_pen)
            painter.drawPath(path)
        elif is_hover and role in ("edge", "corner"):
            # Фирменный тёпло-оранжевый акцент NestCraft (logo #f9984f / push-pull #f97316)
            grad = QLinearGradient(gx0, gy0, gx1, gy1)
            grad.setColorAt(0.0, QColor(251, 146, 60, 245))
            grad.setColorAt(1.0, QColor(249, 115, 22, 245))
            painter.setBrush(QBrush(grad))
            painter.setPen(hover_bevel_pen)
            painter.drawPath(path)
        else:
            r, g, b = _shade_slate(item.get("shade", 0.5), item["depth"], dark_mode, role)
            grad = QLinearGradient(gx0, gy0, gx1, gy1)
            grad.setColorAt(0.0, QColor(min(255, r + 9), min(255, g + 9), min(255, b + 9), 246))
            grad.setColorAt(1.0, QColor(max(0, r - 8), max(0, g - 8), max(0, b - 8), 246))
            painter.setBrush(QBrush(grad))
            painter.setPen(idle_pen)
            painter.drawPath(path)

    # 4. Чистые подписи видимых граней с плавным затуханием при сильном наклоне
    for f in drawable["faces"]:
        if not f.get("visible", f["depth"] > 0.02):
            continue
        depth = float(f["depth"])
        if depth < 0.24:
            continue
        is_hover = hover == ("face", f["id"])
        alpha = 250 if is_hover else max(0, min(235, int(250 * (depth - 0.20) / 0.36)))
        if alpha < 35:
            continue
        caption = f.get("caption", f["label"].upper())
        font = QFont("Segoe UI")
        font.setPointSize(7 if len(caption) >= 6 else 8)
        font.setBold(True)
        painter.setFont(font)
        cx_f, cy_f = f["center"]
        if is_hover:
            text_col = QColor(255, 255, 255, alpha)
        elif dark_mode:
            text_col = QColor(226, 232, 240, alpha)
        else:
            text_col = QColor(30, 41, 59, alpha)
        painter.setPen(text_col)
        painter.drawText(
            int(round(cx_f - 26)),
            int(round(cy_f - 8)),
            52,
            16,
            int(Qt.AlignmentFlag.AlignCenter),
            caption,
        )

    # 5. Синхронизированная 3D-триада осей X / Y / Z (слева-снизу от куба)
    axis_font = QFont("Segoe UI")
    axis_font.setPointSize(7)
    axis_font.setBold(True)
    painter.setFont(axis_font)
    axes_list = drawable.get("axes", ())
    if axes_list:
        ox0, oy0 = axes_list[0]["start"]
        painter.setBrush(QBrush(QColor(15, 23, 42, 200) if not dark_mode else QColor(226, 232, 240, 220)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(ox0, oy0), 2.3, 2.3)

    for ax in axes_list:
        sx, sy = ax["start"]
        ex, ey = ax["end"]
        r, g, b = ax["rgb"]
        depth = float(ax["depth"])
        alpha = 165 if depth < -0.15 else 245
        col = QColor(r, g, b, alpha)
        painter.setPen(QPen(col, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(sx, sy), QPointF(ex, ey))
        # Мини-точка на конце оси и аккуратная буква
        painter.setBrush(QBrush(col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(ex, ey), 2.0, 2.0)

        dx, dy = ex - sx, ey - sy
        norm = max(math.hypot(dx, dy), 1e-3)
        lx = ex + (dx / norm) * 6.5
        ly = ey + (dy / norm) * 6.5
        painter.setPen(col.darker(115) if not dark_mode else col.lighter(115))
        painter.drawText(
            int(round(lx - 6)),
            int(round(ly - 6)),
            12,
            12,
            int(Qt.AlignmentFlag.AlignCenter),
            ax["axis"],
        )

    # 6. Кнопка «Домой» с векторной иконкой домика (в стиле ui/icons/*.svg)
    hx, hy, hw, hh = layout.home_rect
    is_home = hover == ("home", "home")
    if is_home:
        home_bg = QColor(0, 120, 212, 240)
        home_border = QColor(14, 165, 233)
        icon_col = QColor(255, 255, 255)
    elif dark_mode:
        home_bg = QColor(45, 45, 45, 228)
        home_border = QColor(71, 85, 105, 220)
        icon_col = QColor(226, 232, 240)
    else:
        home_bg = QColor(247, 248, 250, 235)
        home_border = QColor(197, 202, 211, 235)
        icon_col = QColor(51, 65, 85)

    painter.setBrush(QBrush(home_bg))
    painter.setPen(QPen(home_border, 1.1))
    painter.drawRoundedRect(int(round(hx)), int(round(hy)), int(round(hw)), int(round(hh)), 7, 7)

    # Векторный контур домика внутри home_rect
    hcx = hx + hw * 0.5
    hcy = hy + hh * 0.5
    house_pen = QPen(icon_col, 1.55, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(house_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    roof = QPainterPath()
    roof.moveTo(hcx - 6.0, hcy - 0.5)
    roof.lineTo(hcx, hcy - 6.0)
    roof.lineTo(hcx + 6.0, hcy - 0.5)
    painter.drawPath(roof)
    walls = QPainterPath()
    walls.moveTo(hcx - 4.4, hcy - 1.5)
    walls.lineTo(hcx - 4.4, hcy + 5.2)
    walls.lineTo(hcx - 1.4, hcy + 5.2)
    walls.lineTo(hcx - 1.4, hcy + 2.0)
    walls.lineTo(hcx + 1.4, hcy + 2.0)
    walls.lineTo(hcx + 1.4, hcy + 5.2)
    walls.lineTo(hcx + 4.4, hcy + 5.2)
    walls.lineTo(hcx + 4.4, hcy - 1.5)
    painter.drawPath(walls)

    # 7. HUD-подсказка ракурса в фирменном стиле вьюпорта (QColor(15, 23, 42, 230))
    if hover is not None:
        h_kind, h_key = hover
        if h_kind == "home":
            tip_text = "Домой (Изометрия)"
            tip_border = QColor(56, 189, 248)
        elif h_kind == "face":
            _rx, _ry, _ortho, lbl = target_for_hit(h_kind, h_key)
            tip_text = lbl
            tip_border = QColor(56, 189, 248)
        else:
            _rx, _ry, _ortho, lbl = target_for_hit(h_kind, h_key)
            tip_text = lbl
            tip_border = QColor(249, 115, 22)

        tip_font = QFont("Segoe UI")
        tip_font.setPointSize(8)
        tip_font.setBold(True)
        painter.setFont(tip_font)
        tw = max(78, min(190, len(tip_text) * 7 + 18))
        th = 20
        tx = int(min(max(6.0, layout.cx - tw * 0.5), float(width) - tw - 6.0))
        ty = int(round(layout.cy + ring_r + 6.0))
        painter.setBrush(QBrush(QColor(15, 23, 42, 232)))
        painter.setPen(QPen(tip_border, 1.2))
        painter.drawRoundedRect(tx, ty, tw, th, 6, 6)
        painter.setPen(QColor(248, 250, 252))
        painter.drawText(tx, ty, tw, th, int(Qt.AlignmentFlag.AlignCenter), tip_text)

    drawable["layout"] = layout
    return drawable
