"""Геометрия помещения, триангуляция стен с проёмами и неровностями, привязки и диагностика.

Модуль работает в чистом Python (без зависимостей от PyQt6 и OpenGL) и обеспечивает:
- построение 3D-сеток стен с реальными вырезами проёмов и фактической криволинейной/
  отклонённой внутренней поверхностью по контрольным станциям замера;
- триангуляцию произвольных (в том числе невыпуклых) полигонов пола и потолка;
- расчёт дуг и зон открывания дверей, рам окон и препятствий;
- мировую трансформацию размещённых изделий `PlacedProduct` без изменения их локальных панелей;
- генерацию точек привязки в формате `Viewport3D` и позиционирование мебели вдоль стен;
- многоточечный анализ зазоров до неровной стены (`WallGapReport`) и проверки пересечений
  с выдачей стандартных `core.issues.Issue`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.issues import Issue
from models.room_frame import (
    DEFAULT_ALLOWED_GAP_MM,
    DEFAULT_COLLISION_TOLERANCE_MM,
    PlacedProduct,
    RoomFrame,
    RoomObstacle,
    RoomWall,
    RoomWorkspace,
    WallOpening,
)

# Максимальный шаг разбиения сетки стены при наличии контрольных точек отклонения (мм)
DEVIATION_GRID_STEP_MM: float = 250.0
# Количество сегментов дуги открывания двери
DOOR_ARC_SEGMENTS: int = 18
# Допуск для проверки принадлежности точки полигону и коллизий (мм)
GEOM_EPS_MM: float = 1e-4


# ── Вспомогательная 2D/3D математика ──────────────────────────


def transform_point_y(
    lx: float,
    ly: float,
    lz: float,
    tx: float,
    ty: float,
    tz: float,
    rotation_y_deg: float,
) -> tuple[float, float, float]:
    """Переводит локальную точку изделия `(lx, ly, lz)` в мировые координаты помещения.

    Поворот выполняется вокруг вертикальной оси Y (`rotation_y_deg` в градусах):
    при `0°` локальная ось `+X` совпадает с мировой `+X`, `+Z` — с мировой `+Z`.
    """
    rad = math.radians(float(rotation_y_deg))
    c = math.cos(rad)
    s = math.sin(rad)
    wx = float(tx) + float(lx) * c + float(lz) * s
    wy = float(ty) + float(ly)
    wz = float(tz) - float(lx) * s + float(lz) * c
    return (wx, wy, wz)


def product_world_corners_xz(product: PlacedProduct) -> list[tuple[float, float]]:
    """4 угла основания габаритной рамки размещённого изделия в плоскости XZ (мм).

    Порядок: `[0: (0,0) зад-лево, 1: (W,0) зад-право, 2: (W,D) перед-право, 3: (0,D) перед-лево]`.
    """
    bf = product.bounding_frame
    bx0, bz0 = float(bf.x), float(bf.z)
    bx1, bz1 = bx0 + float(bf.width), bz0 + float(bf.depth)
    local = [(bx0, bz0), (bx1, bz0), (bx1, bz1), (bx0, bz1)]
    out: list[tuple[float, float]] = []
    for lx, lz in local:
        wx, _wy, wz = transform_point_y(lx, 0.0, lz, product.x, product.y, product.z, product.rotation_y_deg)
        out.append((wx, wz))
    return out


def product_world_corners_3d(product: PlacedProduct) -> list[tuple[float, float, float]]:
    """8 вершин габаритной рамки размещённого изделия в мировых координатах помещения."""
    bf = product.bounding_frame
    pts: list[tuple[float, float, float]] = []
    for lx, ly, lz in bf.corners():
        pts.append(transform_point_y(lx, ly, lz, product.x, product.y, product.z, product.rotation_y_deg))
    return pts


def product_world_y_range(product: PlacedProduct) -> tuple[float, float]:
    """Вертикальный интервал `[y_min, y_max]` размещённого изделия в помещении."""
    bf = product.bounding_frame
    y0 = float(product.y) + float(bf.y)
    return (y0, y0 + float(bf.height))


def obstacle_world_corners_xz(obs: RoomObstacle, *, inflate_mm: float = 0.0) -> list[tuple[float, float]]:
    """4 угла прямоугольного препятствия (с опциональным расширением на `inflate_mm`) в XZ."""
    pad = max(0.0, float(inflate_mm))
    local = [
        (-pad, -pad),
        (float(obs.width) + pad, -pad),
        (float(obs.width) + pad, float(obs.depth) + pad),
        (-pad, float(obs.depth) + pad),
    ]
    out: list[tuple[float, float]] = []
    for lx, lz in local:
        wx, _wy, wz = transform_point_y(lx, 0.0, lz, obs.x, obs.y, obs.z, obs.rotation_y_deg)
        out.append((wx, wz))
    return out


def point_in_polygon_xz(px: float, pz: float, polygon: list[tuple[float, float]], *, tol: float = 0.5) -> bool:
    """Проверяет, лежит ли точка `(px, pz)` внутри (или в пределах `tol` от границы) полигона."""
    n = len(polygon)
    if n < 3:
        return False
    # Сначала проверяем близость к рёбрам (граничное касание считается внутри)
    for i in range(n):
        x0, z0 = polygon[i]
        x1, z1 = polygon[(i + 1) % n]
        if _point_segment_dist_2d(px, pz, x0, z0, x1, z1) <= tol:
            return True
    inside = False
    j = n - 1
    for i in range(n):
        xi, zi = polygon[i]
        xj, zj = polygon[j]
        if ((zi > pz) != (zj > pz)) and (px < (xj - xi) * (pz - zi) / ((zj - zi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _point_segment_dist_2d(
    px: float, pz: float, ax: float, az: float, bx: float, bz: float
) -> float:
    vx, vz = bx - ax, bz - az
    l2 = vx * vx + vz * vz
    if l2 <= 1e-12:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * vx + (pz - az) * vz) / l2))
    qx = ax + t * vx
    qz = az + t * vz
    return math.hypot(px - qx, pz - qz)


def _project_poly_on_axis(poly: list[tuple[float, float]], ax: float, az: float) -> tuple[float, float]:
    vals = [p[0] * ax + p[1] * az for p in poly]
    return (min(vals), max(vals))


def convex_polygons_penetration_2d(
    poly_a: list[tuple[float, float]],
    poly_b: list[tuple[float, float]],
) -> float:
    """Глубина взаимного проникновения двух выпуклых 2D-полигонов (SAT).

    Возвращает `> 0`, если полигоны пересекаются; `<= 0` (отрицательное расстояние или 0 при касании),
    если пересечения нет.
    """
    if len(poly_a) < 3 or len(poly_b) < 3:
        return -1e9
    min_overlap = float("inf")
    for poly in (poly_a, poly_b):
        n = len(poly)
        for i in range(n):
            x0, z0 = poly[i]
            x1, z1 = poly[(i + 1) % n]
            ex, ez = x1 - x0, z1 - z0
            el = math.hypot(ex, ez)
            if el < 1e-9:
                continue
            nx, nz = -ez / el, ex / el
            a_min, a_max = _project_poly_on_axis(poly_a, nx, nz)
            b_min, b_max = _project_poly_on_axis(poly_b, nx, nz)
            overlap = min(a_max, b_max) - max(a_min, b_min)
            if overlap <= 0.0:
                return overlap
            if overlap < min_overlap:
                min_overlap = overlap
    return min_overlap if math.isfinite(min_overlap) else 0.0


def _y_overlap_mm(y_a: tuple[float, float], y_b: tuple[float, float]) -> float:
    return min(y_a[1], y_b[1]) - max(y_a[0], y_b[0])


# ── Триангуляция произвольного (в т.ч. невыпуклого) 2D-полигона ─


def _cross2(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_in_triangle_2d(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    c1 = _cross2(a, b, p)
    c2 = _cross2(b, c, p)
    c3 = _cross2(c, a, p)
    has_neg = (c1 < -1e-6) or (c2 < -1e-6) or (c3 < -1e-6)
    has_pos = (c1 > 1e-6) or (c2 > 1e-6) or (c3 > 1e-6)
    return not (has_neg and has_pos)


def triangulate_polygon_xz(points: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Триангуляция простого (включая невыпуклого) полигона методом отсечения ушей (Ear Clipping)."""
    n = len(points)
    if n < 3:
        return []
    # Определяем ориентацию контура
    area2 = 0.0
    for i in range(n):
        x0, z0 = points[i]
        x1, z1 = points[(i + 1) % n]
        area2 += x0 * z1 - x1 * z0
    ccw = area2 > 0.0
    indices = list(range(n))
    tris: list[tuple[int, int, int]] = []
    guard = 0
    while len(indices) > 3 and guard < n * n + 10:
        guard += 1
        ear_found = False
        m = len(indices)
        for i in range(m):
            i_prev = indices[(i - 1) % m]
            i_curr = indices[i]
            i_next = indices[(i + 1) % m]
            a, b, c = points[i_prev], points[i_curr], points[i_next]
            cr = _cross2(a, b, c)
            if (ccw and cr <= 1e-6) or (not ccw and cr >= -1e-6):
                continue
            # Убеждаемся, что внутри треугольника нет других вершин
            contains_other = False
            for j in indices:
                if j in (i_prev, i_curr, i_next):
                    continue
                if _point_in_triangle_2d(points[j], a, b, c):
                    contains_other = True
                    break
            if contains_other:
                continue
            tris.append((i_prev, i_curr, i_next))
            indices.pop(i)
            ear_found = True
            break
        if not ear_found:
            # Резервный веер для почти вырожденных углов
            tris.append((indices[0], indices[1], indices[2]))
            indices.pop(1)
    if len(indices) == 3:
        tris.append((indices[0], indices[1], indices[2]))
    return tris


# ── Генерация 3D-геометрии помещения для OpenGL и 2D-плана ────


@dataclass
class SimpleMesh:
    """Лёгкая триангулированная 3D-сетка без зависимости от OpenGL/numpy."""

    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    edges: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)

    def add_quad(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        p3: tuple[float, float, float],
        *,
        add_border_edges: bool = False,
    ) -> None:
        """Добавляет четырёхугольник `(p0, p1, p2, p3)` двумя треугольниками с плоской нормалью."""
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        nl = math.sqrt(nx * nx + ny * ny + nz * nz)
        nrm = (nx / nl, ny / nl, nz / nl) if nl > 1e-9 else (0.0, 1.0, 0.0)
        base = len(self.vertices)
        self.vertices.extend([p0, p1, p2, p3])
        self.normals.extend([nrm, nrm, nrm, nrm])
        self.indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
        if add_border_edges:
            self.edges.extend([(p0, p1), (p1, p2), (p2, p3), (p3, p0)])

    def add_box(
        self,
        x0: float,
        y0: float,
        z0: float,
        w: float,
        h: float,
        d: float,
        *,
        tx: float = 0.0,
        ty: float = 0.0,
        tz: float = 0.0,
        rotation_y_deg: float = 0.0,
        add_edges: bool = True,
    ) -> None:
        """Добавляет ориентированный параллелепипед в сетку."""
        local = [
            (x0, y0, z0),
            (x0 + w, y0, z0),
            (x0 + w, y0, z0 + d),
            (x0, y0, z0 + d),
            (x0, y0 + h, z0),
            (x0 + w, y0 + h, z0),
            (x0 + w, y0 + h, z0 + d),
            (x0, y0 + h, z0 + d),
        ]
        c = [transform_point_y(px, py, pz, tx, ty, tz, rotation_y_deg) for px, py, pz in local]
        self.add_quad(c[0], c[3], c[2], c[1])  # низ
        self.add_quad(c[4], c[5], c[6], c[7])  # верх
        self.add_quad(c[0], c[1], c[5], c[4])  # зад
        self.add_quad(c[3], c[7], c[6], c[2])  # перед
        self.add_quad(c[0], c[4], c[7], c[3])  # лево
        self.add_quad(c[1], c[2], c[6], c[5])  # право
        if add_edges:
            for i, j in (
                (0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7),
            ):
                self.edges.append((c[i], c[j]))


def _unique_sorted(values: list[float], tol: float = 0.5) -> list[float]:
    out: list[float] = []
    for val in sorted(values):
        if not out or abs(val - out[-1]) > tol:
            out.append(float(val))
    return out


def _opening_contains_cell(op: WallOpening, s_mid: float, y_mid: float) -> bool:
    return (
        op.offset_s_mm + 0.5 < s_mid < op.offset_s_mm + op.width_mm - 0.5
        and op.sill_height_mm + 0.5 < y_mid < op.sill_height_mm + op.height_mm - 0.5
    )


def build_wall_mesh(room: RoomFrame, wall: RoomWall) -> SimpleMesh:
    """Строит 3D-сетку стены с реальными вырезами проёмов и неровной внутренней поверхностью."""
    mesh = SimpleMesh()
    info = room.wall_geometry(wall)
    L = info.length_mm
    H = float(wall.height_mm)
    T = float(wall.thickness_mm)
    y_floor = float(room.floor_elevation_mm)
    x0, z0 = info.start_xz
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz

    s_breaks = [0.0, L]
    y_breaks = [0.0, H]
    for op in wall.openings:
        s_breaks.extend([max(0.0, op.offset_s_mm), min(L, op.offset_s_mm + op.width_mm)])
        y_breaks.extend([max(0.0, op.sill_height_mm), min(H, op.sill_height_mm + op.height_mm)])

    if wall.deviation_stations:
        for st in wall.deviation_stations:
            s_breaks.append(max(0.0, min(L, st.s_mm)))
            y_breaks.append(max(0.0, min(H, st.height_mm)))
        # Делим крупные пролёты, чтобы плавно передать выпуклость/вогнутость и завал стены в 3D
        n_s = max(2, int(math.ceil(L / DEVIATION_GRID_STEP_MM)))
        for k in range(1, n_s):
            s_breaks.append(L * k / n_s)
        n_y = max(2, int(math.ceil(H / DEVIATION_GRID_STEP_MM)))
        for k in range(1, n_y):
            y_breaks.append(H * k / n_y)

    s_grid = _unique_sorted(s_breaks)
    y_grid = _unique_sorted(y_breaks)

    def _pt_in(s: float, y_rel: float) -> tuple[float, float, float]:
        off = room.evaluate_wall_offset(wall, s, y_rel)
        return (x0 + tx * s + nx * off, y_floor + y_rel, z0 + tz * s + nz * off)

    def _pt_out(s: float, y_rel: float) -> tuple[float, float, float]:
        return (x0 + tx * s - nx * T, y_floor + y_rel, z0 + tz * s - nz * T)

    ns = len(s_grid) - 1
    ny = len(y_grid) - 1
    solid_cell: list[list[bool]] = [[True] * ny for _ in range(ns)]

    for i in range(ns):
        s_mid = 0.5 * (s_grid[i] + s_grid[i + 1])
        for j in range(ny):
            y_mid = 0.5 * (y_grid[j] + y_grid[j + 1])
            if any(_opening_contains_cell(op, s_mid, y_mid) for op in wall.openings):
                solid_cell[i][j] = False

    # Внутренняя и внешняя поверхности + торцы + откосы вырезанных проёмов
    for i in range(ns):
        s0, s1 = s_grid[i], s_grid[i + 1]
        for j in range(ny):
            if not solid_cell[i][j]:
                continue
            y0, y1 = y_grid[j], y_grid[j + 1]
            in00, in10, in11, in01 = _pt_in(s0, y0), _pt_in(s1, y0), _pt_in(s1, y1), _pt_in(s0, y1)
            out00, out10, out11, out01 = _pt_out(s0, y0), _pt_out(s1, y0), _pt_out(s1, y1), _pt_out(s0, y1)

            # Внутренняя грань (обращена внутрь помещения)
            mesh.add_quad(in00, in10, in11, in01)
            # Внешняя грань
            mesh.add_quad(out00, out01, out11, out10)

            # Граничные стенки: торцы стены и откосы проёмов
            if i == 0 or not solid_cell[i - 1][j]:
                mesh.add_quad(out00, in00, in01, out01, add_border_edges=True)
            if i == ns - 1 or not solid_cell[i + 1][j]:
                mesh.add_quad(in10, out10, out11, in11, add_border_edges=True)
            if j == 0 or not solid_cell[i][j - 1]:
                mesh.add_quad(out00, out10, in10, in00, add_border_edges=True)
            if j == ny - 1 or not solid_cell[i][j + 1]:
                mesh.add_quad(in01, in11, out11, out01, add_border_edges=True)

    # Контурные рёбра неровной внутренней поверхности (если есть отклонения — рисуем профиль)
    if wall.deviation_stations:
        for j in (0, ny):
            yr = y_grid[j]
            for i in range(ns):
                mesh.edges.append((_pt_in(s_grid[i], yr), _pt_in(s_grid[i + 1], yr)))
        for i in (0, ns):
            sr = s_grid[i]
            for j in range(ny):
                mesh.edges.append((_pt_in(sr, y_grid[j]), _pt_in(sr, y_grid[j + 1])))
        # Внутренние линии рельефа на высотах и позициях станций замера
        for st in wall.deviation_stations:
            for i in range(ns):
                mesh.edges.append((_pt_in(s_grid[i], st.height_mm), _pt_in(s_grid[i + 1], st.height_mm)))
    return mesh


def build_floor_ceiling_meshes(room: RoomFrame) -> tuple[SimpleMesh, SimpleMesh]:
    """Строит 3D-сетки пола и потолка по произвольному замкнутому контуру помещения."""
    floor_mesh = SimpleMesh()
    ceil_mesh = SimpleMesh()
    pts = room.ordered_polygon_xz()
    if len(pts) < 3:
        return floor_mesh, ceil_mesh
    tris = triangulate_polygon_xz(pts)
    y_floor = float(room.floor_elevation_mm)
    y_ceil = y_floor + float(room.ceiling_height_mm)

    for px, pz in pts:
        floor_mesh.vertices.append((px, y_floor, pz))
        floor_mesh.normals.append((0.0, 1.0, 0.0))
        ceil_mesh.vertices.append((px, y_ceil, pz))
        ceil_mesh.normals.append((0.0, -1.0, 0.0))

    for i0, i1, i2 in tris:
        floor_mesh.indices.extend([i0, i1, i2])
        ceil_mesh.indices.extend([i0, i2, i1])

    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        floor_mesh.edges.append(((a[0], y_floor, a[1]), (b[0], y_floor, b[1])))
        ceil_mesh.edges.append(((a[0], y_ceil, a[1]), (b[0], y_ceil, b[1])))
    return floor_mesh, ceil_mesh


CAMERA_OCCLUSION_DOT_THRESHOLD: float = 0.08
TOP_DOWN_CAMERA_Y_THRESHOLD: float = 0.92


def room_display_style(
    display_mode: str,
    *,
    wireframe_only: bool = False,
) -> str:
    """Возвращает канонический режим отрисовки стен помещения: ``wireframe`` | ``xray`` | ``solid``.

    Логика совпадает с панелями:
    - ``wireframe`` — только контуры без заливки;
    - ``xray`` — depth-prepass + скрытые контуры светло-серые, видимые тёмные;
    - ``solid`` — твёрдотельная заливка (или ручная полупрозрачность при ``walls_translucent``).
    """
    mode = str(display_mode or "solid").strip().lower()
    if mode == "wireframe" or wireframe_only:
        return "wireframe"
    if mode == "xray":
        return "xray"
    return "solid"


def compute_room_wall_alpha(
    display_mode: str,
    *,
    wireframe_only: bool = False,
    walls_translucent: bool = False,
    custom_alpha: float = 0.38,
) -> float:
    """Возвращает прозрачность заливки стен для режима отображения.

    В режимах «Каркас» и «X-Ray» стены рисуются контурами по логике панелей (без заливки, ``0.0``).
    В твёрдотельном режиме возвращается ``1.0`` или пользовательская полупрозрачность.
    """
    style = room_display_style(display_mode, wireframe_only=wireframe_only)
    if style in ("wireframe", "xray"):
        return 0.0
    if walls_translucent:
        return max(0.05, min(1.0, float(custom_alpha)))
    return 1.0


def is_wall_occluding_camera(
    room: RoomFrame,
    wall: RoomWall,
    camera_forward_xyz: tuple[float, float, float],
    *,
    view_mode: str = "3d",
    dot_threshold: float = CAMERA_OCCLUSION_DOT_THRESHOLD,
) -> bool:
    """True, если стена находится перед камерой и заслоняет обзор внутрь помещения.

    Условие: вектор взгляда камеры в плоскости XZ направлен со стороны внешней грани стены
    внутрь помещения (`dot(forward_xz, inward_normal_xz) > dot_threshold`).
    - При взгляде на одну стену пропадает только она; при повороте она появляется, а пропадает новая.
    - При взгляде на угол помещения обе стены угла имеют положительную проекцию и скрываются вместе.
    - В 2D-плане и при взгляде почти строго сверху вниз (`|forward_y| > 0.92`) стены не скрываются.
    """
    if str(view_mode or "3d").strip().lower() == "2d":
        return False
    fx, fy, fz = float(camera_forward_xyz[0]), float(camera_forward_xyz[1]), float(camera_forward_xyz[2])
    if abs(fy) > TOP_DOWN_CAMERA_Y_THRESHOLD:
        return False
    fl = math.hypot(fx, fz)
    if fl < 1e-6:
        return False
    vx, vz = fx / fl, fz / fl
    info = room.wall_geometry(wall)
    inx, inz = info.inward_normal_xz
    return (vx * inx + vz * inz) > float(dot_threshold)


def door_swing_geometry_xz(
    room: RoomFrame,
    wall: RoomWall,
    opening: WallOpening,
) -> dict[str, Any]:
    """Вычисляет геометрию открывания двери в 2D-плане XZ: петля, полотно, дуга и сектор.

    Возвращает словарь `{hinge_xz, closed_tip_xz, open_tip_xz, arc_points_xz, sector_polygon_xz}`.
    """
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz
    s0 = float(opening.offset_s_mm)
    w = float(opening.width_mm)
    s1 = s0 + w

    is_in = opening.swing_dir.startswith("in")
    is_left = opening.swing_dir.endswith("left")
    swing_n = (nx, nz) if is_in else (-nx, -nz)
    # При открывании внутрь ось полотна лежит на внутренней линии стены; наружу — на внешней
    plane_shift = 0.0 if is_in else -float(wall.thickness_mm)

    hinge_s = s0 if is_left else s1
    tip_s = s1 if is_left else s0
    hx = x0 + tx * hinge_s + nx * plane_shift
    hz = z0 + tz * hinge_s + nz * plane_shift
    cx = x0 + tx * tip_s + nx * plane_shift
    cz = z0 + tz * tip_s + nz * plane_shift

    # Базовый вектор от петли к свободному краю в закрытом состоянии
    ux = (cx - hx) / max(w, 1e-6)
    uz = (cz - hz) / max(w, 1e-6)
    ang_rad = math.radians(max(0.0, min(180.0, float(opening.swing_angle_deg))))

    arc_pts: list[tuple[float, float]] = []
    steps = max(4, DOOR_ARC_SEGMENTS)
    for k in range(steps + 1):
        theta = ang_rad * (k / steps)
        px = hx + w * (math.cos(theta) * ux + math.sin(theta) * swing_n[0])
        pz = hz + w * (math.cos(theta) * uz + math.sin(theta) * swing_n[1])
        arc_pts.append((px, pz))

    sector_poly = [(hx, hz)] + arc_pts
    return {
        "hinge_xz": (hx, hz),
        "closed_tip_xz": (cx, cz),
        "open_tip_xz": arc_pts[-1],
        "arc_points_xz": arc_pts,
        "sector_polygon_xz": sector_poly,
    }


def opening_zone_polygon_xz(
    room: RoomFrame,
    wall: RoomWall,
    opening: WallOpening,
    *,
    clearance_inward_mm: float = 20.0,
) -> list[tuple[float, float]]:
    """Прямоугольник проёма в плане XZ (включая небольшую монтажную зону перед проёмом)."""
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz
    s0 = float(opening.offset_s_mm)
    s1 = s0 + float(opening.width_mm)
    out_d = -float(wall.thickness_mm)
    in_d = max(0.0, float(clearance_inward_mm))
    return [
        (x0 + tx * s0 + nx * out_d, z0 + tz * s0 + nz * out_d),
        (x0 + tx * s1 + nx * out_d, z0 + tz * s1 + nz * out_d),
        (x0 + tx * s1 + nx * in_d, z0 + tz * s1 + nz * in_d),
        (x0 + tx * s0 + nx * in_d, z0 + tz * s0 + nz * in_d),
    ]


def build_opening_visual_edges(
    room: RoomFrame,
    wall: RoomWall,
    opening: WallOpening,
) -> tuple[list[tuple[tuple[float, float, float], tuple[float, float, float]]], SimpleMesh]:
    """Строит 3D-рёбра (рама, подоконник, дуга двери) и вспомогательную сетку проёма."""
    edges: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    mesh = SimpleMesh()
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz
    y_floor = float(room.floor_elevation_mm)
    s0 = float(opening.offset_s_mm)
    s1 = s0 + float(opening.width_mm)
    y0 = y_floor + float(opening.sill_height_mm)
    y1 = y0 + float(opening.height_mm)
    T = float(wall.thickness_mm)

    def _p(s: float, y: float, n_shift: float) -> tuple[float, float, float]:
        return (x0 + tx * s + nx * n_shift, y, z0 + tz * s + nz * n_shift)

    # Рама проёма на внутренней и внешней плоскости
    for sh in (0.0, -T):
        a, b, c, d = _p(s0, y0, sh), _p(s1, y0, sh), _p(s1, y1, sh), _p(s0, y1, sh)
        edges.extend([(a, b), (b, c), (c, d), (d, a)])

    if opening.kind == "window":
        # Подоконник (выступает внутрь комнаты на sill_depth_mm)
        sd = max(10.0, float(opening.sill_depth_mm))
        sill_thick = 28.0
        p00 = _p(s0 - 20.0, y0 - sill_thick, -T)
        p10 = _p(s1 + 20.0, y0 - sill_thick, -T)
        p11 = _p(s1 + 20.0, y0 - sill_thick, sd)
        p01 = _p(s0 - 20.0, y0 - sill_thick, sd)
        q00 = _p(s0 - 20.0, y0, -T)
        q10 = _p(s1 + 20.0, y0, -T)
        q11 = _p(s1 + 20.0, y0, sd)
        q01 = _p(s0 - 20.0, y0, sd)
        mesh.add_quad(q00, q10, q11, q01, add_border_edges=True)
        mesh.add_quad(p01, p11, q11, q01, add_border_edges=True)
        mesh.add_quad(p00, p01, q01, q00)
        mesh.add_quad(p10, q10, q11, p11)
        # Импост окна (перекрестие в центре)
        sm = 0.5 * (s0 + s1)
        edges.append((_p(sm, y0, -0.5 * T), _p(sm, y1, -0.5 * T)))
    elif opening.kind == "door":
        sw = door_swing_geometry_xz(room, wall, opening)
        arc = sw["arc_points_xz"]
        hx, hz = sw["hinge_xz"]
        ox, oz = sw["open_tip_xz"]
        # Дуга открывания на уровне пола (y0 + 3 мм, чтобы не сливалась с полом)
        ya = y0 + 3.0
        for i in range(len(arc) - 1):
            edges.append(((arc[i][0], ya, arc[i][1]), (arc[i + 1][0], ya, arc[i + 1][1])))
        # Дверное полотно в открытом положении (контур + полупрозрачная плоскость)
        h0, h1 = (hx, y0, hz), (hx, y1, hz)
        o0, o1 = (ox, y0, oz), (ox, y1, oz)
        edges.extend([(h0, o0), (o0, o1), (o1, h1), (h1, h0)])
        mesh.add_quad(h0, o0, o1, h1)

    return edges, mesh


# ── Точки привязки и позиционирование мебели ──────────────────


def collect_room_snap_points(
    workspace: RoomWorkspace,
) -> list[tuple[tuple[float, float, float], str, str, None, dict[str, Any]]]:
    """Собирает цели привязки помещения и размещённой мебели в формате `Viewport3D`.

    Формат каждого элемента совпадает с `BoundingFrame.snap_points()`:
    `(point_xyz, description, kind, owner_panel=None, meta_dict)`.
    """
    out: list[tuple[tuple[float, float, float], str, str, None, dict[str, Any]]] = []
    room = workspace.room_frame
    y_floor = float(room.floor_elevation_mm)

    # 1. Углы стен (на полу и у потолка)
    for idx, v in enumerate(room.vertices, start=1):
        out.append(
            (
                (v.x, y_floor, v.z),
                f"Угол помещения {idx} (пол)",
                "corner",
                None,
                {"source": "room_vertex", "vertex_uid": v.uid},
            )
        )
        out.append(
            (
                (v.x, y_floor + float(room.ceiling_height_mm), v.z),
                f"Угол помещения {idx} (потолок)",
                "corner",
                None,
                {"source": "room_vertex", "vertex_uid": v.uid},
            )
        )

    # 2. Внутренние поверхности стен, середины рёбер и проёмы
    if room.show_walls:
        for w in room.walls:
            if not w.visible:
                continue
            info = room.wall_geometry(w)
            x0, z0 = info.start_xz
            tx, tz = info.tangent_xz
            nx, nz = info.inward_normal_xz
            mid_s = 0.5 * info.length_mm
            mid_h = 0.5 * float(w.height_mm)
            off_floor = room.evaluate_wall_offset(w, mid_s, 0.0)
            off_mid = room.evaluate_wall_offset(w, mid_s, mid_h)
            out.append(
                (
                    (x0 + tx * mid_s + nx * off_floor, y_floor, z0 + tz * mid_s + nz * off_floor),
                    f"Низ стены [{w.name}]",
                    "edge_mid",
                    None,
                    {"source": "room_wall", "wall_uid": w.uid},
                )
            )
            out.append(
                (
                    (x0 + tx * mid_s + nx * off_mid, y_floor + mid_h, z0 + tz * mid_s + nz * off_mid),
                    f"Поверхность стены [{w.name}]",
                    "face_center",
                    None,
                    {"source": "room_wall", "wall_uid": w.uid},
                )
            )
            if room.show_openings:
                for op in w.openings:
                    for tag, s_pos in (("левый край", op.offset_s_mm), ("правый край", op.offset_s_mm + op.width_mm)):
                        oy = y_floor + float(op.sill_height_mm)
                        out.append(
                            (
                                (x0 + tx * s_pos, oy, z0 + tz * s_pos),
                                f"{op.name}: {tag}",
                                "corner",
                                None,
                                {"source": "room_opening", "opening_uid": op.uid, "wall_uid": w.uid},
                            )
                        )

    # 3. Препятствия
    if room.show_obstacles:
        for obs in room.obstacles:
            if not obs.visible:
                continue
            for c_idx, (cx, cz) in enumerate(obstacle_world_corners_xz(obs), start=1):
                out.append(
                    (
                        (cx, float(obs.y), cz),
                        f"Угол {c_idx} [{obs.name}]",
                        "corner",
                        None,
                        {"source": "room_obstacle", "obstacle_uid": obs.uid},
                    )
                )

    # 4. Размещённые изделия (их габаритные рамки)
    if room.show_furniture:
        for prod in workspace.products:
            if not prod.visible:
                continue
            for c_idx, pt in enumerate(product_world_corners_3d(prod), start=1):
                out.append(
                    (
                        pt,
                        f"Угол {c_idx} [{prod.name}]",
                        "corner",
                        None,
                        {"source": "room_product", "product_uid": prod.uid},
                    )
                )

    return out


def snap_product_to_wall(
    room: RoomFrame,
    product: PlacedProduct,
    wall_uid: str,
    *,
    offset_mm: float = 0.0,
    s_position_mm: float | None = None,
    elevation_y_mm: float | None = None,
) -> PlacedProduct:
    """Привязывает изделие к внутренней плоскости выбранной стены с точным отступом и ориентацией.

    Изделие поворачивается так, чтобы его задняя грань (`local z = bf.z`) была параллельна стене,
    фасад (`local +Z`) смотрел внутрь помещения, а локальная ось `+X` (ширина изделия) шла вдоль
    направления стены. Локальная геометрия панелей и `bounding_frame` изделия не изменяются.
    """
    wall = room.get_wall(wall_uid)
    if wall is None:
        raise ValueError("Стена для привязки изделия не найдена.")
    info = room.wall_geometry(wall)
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz
    x0, z0 = info.start_xz

    # Поворот вокруг Y: локальный +X = (cos a, -sin a), локальный +Z = (sin a, cos a).
    # Требуется локальный +Z == (nx, nz), чтобы задняя плоскость прилегала к стене, а фасад смотрел внутрь.
    rot_rad = math.atan2(nx, nz)
    rot_deg = math.degrees(rot_rad)

    # Направление локальной оси +X после поворота: (cos(rot), -sin(rot)) = (nz, -nx)
    local_x_world = (math.cos(rot_rad), -math.sin(rot_rad))
    dot_tx = local_x_world[0] * tx + local_x_world[1] * tz

    bf = product.bounding_frame
    eff_s = (
        float(s_position_mm)
        if s_position_mm is not None
        else max(0.0, 0.5 * (info.length_mm - float(bf.width)))
    )
    eff_off = float(offset_mm)

    # Точка на внутренней линии стены, соответствующая левому-заднему углу изделия
    if dot_tx >= 0.0:
        anchor_s = eff_s
    else:
        # Локальный +X направлен противоположно касательной стены — сдвигаем старт на ширину изделия
        anchor_s = eff_s + float(bf.width)

    target_wx = x0 + tx * anchor_s + nx * eff_off
    target_wz = z0 + tz * anchor_s + nz * eff_off

    # Учитываем возможное смещение `bf.x, bf.z` внутри локальной системы изделия
    bx_wx, _by, bx_wz = transform_point_y(bf.x, 0.0, bf.z, 0.0, 0.0, 0.0, rot_deg)
    product.x = target_wx - bx_wx
    product.z = target_wz - bx_wz
    if elevation_y_mm is not None:
        product.y = float(room.floor_elevation_mm) + float(elevation_y_mm) - float(bf.y)
    else:
        product.y = float(room.floor_elevation_mm) - float(bf.y)
    product.rotation_y_deg = round(rot_deg, 4)
    product.anchor_wall_uid = wall.uid
    product.wall_offset_mm = eff_off
    return product


# ── Анализ зазоров до неровной стены (ТЗ §8.2) ────────────────


@dataclass
class WallGapSample:
    """Результат замера зазора между мебелью и фактической поверхностью стены в одной точке."""

    label: str
    s_mm: float
    y_mm: float
    gap_mm: float
    wall_offset_mm: float
    furniture_point: tuple[float, float, float]
    wall_point: tuple[float, float, float]
    status: str  # "collision" | "ok" | "excess_gap"


@dataclass
class WallGapReport:
    """Сводка многоточечного анализа зазоров между изделием и стеной."""

    product_uid: str
    product_name: str
    wall_uid: str
    wall_name: str
    side_label: str
    allowed_gap_mm: float
    tolerance_mm: float
    samples: list[WallGapSample] = field(default_factory=list)
    min_gap_mm: float = 0.0
    max_gap_mm: float = 0.0
    delta_gap_mm: float = 0.0
    has_collision: bool = False
    has_excess_gap: bool = False

    def format_summary(self) -> str:
        """Форматирует понятную сводку зазоров (например: слева / центр / справа + мин/макс/разница)."""
        if not self.samples:
            return f"«{self.product_name}» ↔ «{self.wall_name}»: нет общих точек проекции вдоль стены."
        # Берём средний ряд по высоте для компактного перечисления слева-центр-справа
        mid_row = [s for s in self.samples if "центр(H)" in s.label] or self.samples[:3]
        parts = " / ".join(f"{s.gap_mm:.1f} мм" for s in mid_row)
        return (
            f"«{self.product_name}» ({self.side_label}) ↔ «{self.wall_name}»: {parts} "
            f"(мин {self.min_gap_mm:.1f} мм, макс {self.max_gap_mm:.1f} мм, перепад {self.delta_gap_mm:.1f} мм)"
        )


def _select_closest_product_face_to_wall(
    room: RoomFrame,
    product: PlacedProduct,
    wall: RoomWall,
) -> tuple[str, tuple[float, float], tuple[float, float]]:
    """Выбирает сторону изделия (задняя/передняя/левая/правая), ближайшую к стене."""
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    nx, nz = info.inward_normal_xz
    corners = product_world_corners_xz(product)
    # 4 стороны рамки: зад (0-1), право (1-2), перед (2-3), лево (3-0)
    sides = [
        ("задняя плоскость", corners[0], corners[1]),
        ("правая боковина", corners[1], corners[2]),
        ("передняя плоскость", corners[2], corners[3]),
        ("левая боковина", corners[3], corners[0]),
    ]
    best = sides[0]
    best_dist = float("inf")
    for label, a, b in sides:
        mx, mz = 0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])
        d = abs((mx - x0) * nx + (mz - z0) * nz)
        if d < best_dist:
            best_dist = d
            best = (label, a, b)
    return best


def measure_product_wall_gaps(
    room: RoomFrame,
    product: PlacedProduct,
    wall_uid: str,
    *,
    samples_w: int = 3,
    samples_h: int = 3,
    allowed_gap_mm: float = DEFAULT_ALLOWED_GAP_MM,
    tolerance_mm: float = DEFAULT_COLLISION_TOLERANCE_MM,
) -> WallGapReport:
    """Измеряет расстояние от ближайшей стороны мебели до фактической (неровной) поверхности стены.

    Точки замера распределяются по ширине (`samples_w`, минимум 2) и высоте (`samples_h`, минимум 1)
    стороны изделия, ближайшей к стене. Положительный `gap_mm` — зазор; отрицательный — врезание.
    """
    wall = room.get_wall(wall_uid)
    if wall is None:
        raise ValueError("Стена для анализа зазоров не найдена.")
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    tx, tz = info.tangent_xz
    nx, nz = info.inward_normal_xz
    y_floor = float(room.floor_elevation_mm)

    side_label, pt_a, pt_b = _select_closest_product_face_to_wall(room, product, wall)
    y_min, y_max = product_world_y_range(product)

    nw = max(2, int(samples_w))
    nh = max(1, int(samples_h))
    w_labels = ["слева", "центр", "справа"] if nw == 3 else [f"W{i + 1}" for i in range(nw)]
    h_labels = ["низ(H)", "центр(H)", "верх(H)"] if nh == 3 else [f"H{j + 1}" for j in range(nh)]

    samples: list[WallGapSample] = []
    for j in range(nh):
        vh = 0.5 if nh == 1 else j / (nh - 1)
        wy = y_min + (y_max - y_min) * vh
        y_rel = max(0.0, min(float(wall.height_mm), wy - y_floor))
        for i in range(nw):
            vw = i / (nw - 1)
            fx = pt_a[0] + (pt_b[0] - pt_a[0]) * vw
            fz = pt_a[1] + (pt_b[1] - pt_a[1]) * vw
            s = (fx - x0) * tx + (fz - z0) * tz
            # Пропускаем точки, уходящие далеко за концы стены
            if s < -tolerance_mm or s > info.length_mm + tolerance_mm:
                continue
            s_clamped = max(0.0, min(info.length_mm, s))
            base_dist = (fx - x0) * nx + (fz - z0) * nz
            wall_off = room.evaluate_wall_offset(wall, s_clamped, y_rel)
            gap = base_dist - wall_off
            wall_pt = (
                x0 + tx * s_clamped + nx * wall_off,
                wy,
                z0 + tz * s_clamped + nz * wall_off,
            )
            if gap < -tolerance_mm:
                status = "collision"
            elif gap > allowed_gap_mm + tolerance_mm:
                status = "excess_gap"
            else:
                status = "ok"
            samples.append(
                WallGapSample(
                    label=f"{w_labels[i]} / {h_labels[j]}",
                    s_mm=s_clamped,
                    y_mm=y_rel,
                    gap_mm=gap,
                    wall_offset_mm=wall_off,
                    furniture_point=(fx, wy, fz),
                    wall_point=wall_pt,
                    status=status,
                )
            )

    if samples:
        gaps = [s.gap_mm for s in samples]
        min_g = min(gaps)
        max_g = max(gaps)
        delta_g = max_g - min_g
        has_col = any(s.status == "collision" for s in samples)
        has_exc = any(s.status == "excess_gap" for s in samples)
    else:
        min_g = max_g = delta_g = 0.0
        has_col = has_exc = False

    return WallGapReport(
        product_uid=product.uid,
        product_name=product.name,
        wall_uid=wall.uid,
        wall_name=wall.name,
        side_label=side_label,
        allowed_gap_mm=float(allowed_gap_mm),
        tolerance_mm=float(tolerance_mm),
        samples=samples,
        min_gap_mm=min_g,
        max_gap_mm=max_g,
        delta_gap_mm=delta_g,
        has_collision=has_col,
        has_excess_gap=has_exc,
    )


def find_nearest_wall_for_product(room: RoomFrame, product: PlacedProduct) -> RoomWall | None:
    """Возвращает привязанную или геометрически ближайшую стену помещения для изделия."""
    if product.anchor_wall_uid:
        anchored = room.get_wall(product.anchor_wall_uid)
        if anchored is not None:
            return anchored
    corners = product_world_corners_xz(product)
    cx = sum(p[0] for p in corners) / 4.0
    cz = sum(p[1] for p in corners) / 4.0
    best_wall: RoomWall | None = None
    best_d = float("inf")
    for w in room.walls:
        info = room.wall_geometry(w)
        d = _point_segment_dist_2d(cx, cz, info.start_xz[0], info.start_xz[1], info.end_xz[0], info.end_xz[1])
        if d < best_d:
            best_d = d
            best_wall = w
    return best_wall


# ── Полная диагностика помещения (ТЗ §8.1, §8.3) ──────────────


def _wall_solid_polygon_xz(room: RoomFrame, wall: RoomWall) -> list[tuple[float, float]]:
    """Базовый 2D-прямоугольник тела стены (от внутренней линии к внешней толщине)."""
    info = room.wall_geometry(wall)
    x0, z0 = info.start_xz
    x1, z1 = info.end_xz
    ox, oz = info.outward_normal_xz
    t = float(wall.thickness_mm)
    return [
        (x0, z0),
        (x1, z1),
        (x1 + ox * t, z1 + oz * t),
        (x0 + ox * t, z0 + oz * t),
    ]


def check_room_issues(workspace: RoomWorkspace) -> list[Issue]:
    """Выполняет все проверки соответствия мебели помещению и возвращает список `Issue`.

    Проверки (ТЗ §8.1 и §8.2):
    1. Мебель — стена (включая фактическую отклонённую поверхность стены; касание в пределах допуска не ошибка).
    2. Мебель — оконный/дверной проём.
    3. Мебель — зона открывания двери (сектор дуги открывания).
    4. Мебель — препятствие (колонна, короб, радиатор и др. с учётом `clearance_mm`).
    5. Мебель — мебель (пересечение независимых размещённых изделий между собой).
    6. Мебель — границы помещения (выход за внутренний контур или выше потолка).
    7. Превышение допустимого зазора до неровной привязанной/ближайшей стены.
    """
    issues: list[Issue] = []
    room = workspace.room_frame
    tol = float(workspace.collision_tolerance_mm)
    allowed_gap = float(workspace.allowed_gap_mm)
    poly_room = room.ordered_polygon_xz()
    y_floor = float(room.floor_elevation_mm)
    y_ceil = y_floor + float(room.ceiling_height_mm)

    visible_products = [p for p in workspace.products if p.visible]

    for prod in visible_products:
        p_poly = product_world_corners_xz(prod)
        p_yr = product_world_y_range(prod)

        # 1. Выход за границы помещения (контур плана проверяем только для замкнутого контура + пол/потолок)
        if room.is_closed():
            outside_corners = sum(
                1 for cx, cz in p_poly if not point_in_polygon_xz(cx, cz, poly_room, tol=tol + 0.5)
            )
            if outside_corners > 0:
                issues.append(
                    Issue(
                        severity="error",
                        panel_uid=prod.uid,
                        code="room_outside_bounds",
                        message=(
                            f"Изделие «{prod.name}» выходит за внутренние границы помещения "
                            f"(углов вне контура: {outside_corners})"
                        ),
                    )
                )
        if p_yr[0] < y_floor - tol:
            issues.append(
                Issue(
                    severity="error",
                    panel_uid=prod.uid,
                    code="room_below_floor",
                    message=(
                        f"Изделие «{prod.name}» заглублено ниже отметки пола на "
                        f"{(y_floor - p_yr[0]):.1f} мм"
                    ),
                )
            )
        if p_yr[1] > y_ceil + tol:
            issues.append(
                Issue(
                    severity="error",
                    panel_uid=prod.uid,
                    code="room_above_ceiling",
                    message=(
                        f"Изделие «{prod.name}» превышает высоту потолка на "
                        f"{(p_yr[1] - y_ceil):.1f} мм"
                    ),
                )
            )

        # 2. Проверка по стенам (тело стены + неровность + проёмы + зона открывания двери)
        for wall in room.walls:
            w_yr = (y_floor, y_floor + float(wall.height_mm))
            if _y_overlap_mm(p_yr, w_yr) <= tol:
                continue

            # 2a. Пересечение с базовым телом стены (касание в пределах tol допустимо)
            wall_pen = convex_polygons_penetration_2d(p_poly, _wall_solid_polygon_xz(room, wall))
            # 2b. Пересечение с фактической отклонённой внутренней поверхностью стены
            gap_rep = measure_product_wall_gaps(
                room,
                prod,
                wall.uid,
                samples_w=5,
                samples_h=3,
                allowed_gap_mm=allowed_gap,
                tolerance_mm=tol,
            )
            min_gap_pen = -gap_rep.min_gap_mm if (gap_rep.samples and gap_rep.min_gap_mm < -tol) else 0.0
            eff_pen = max(wall_pen if wall_pen > tol else 0.0, min_gap_pen)
            if eff_pen > tol:
                issues.append(
                    Issue(
                        severity="error",
                        panel_uid=prod.uid,
                        code="room_wall_collision",
                        message=(
                            f"Изделие «{prod.name}» пересекает стену «{wall.name}» "
                            f"(врезание {eff_pen:.1f} мм)"
                        ),
                    )
                )

            # 2c. Проёмы и зоны открывания дверей
            for op in wall.openings:
                op_yr = (y_floor + float(op.sill_height_mm), y_floor + float(op.sill_height_mm + op.height_mm))
                if _y_overlap_mm(p_yr, op_yr) <= tol:
                    continue
                op_poly = opening_zone_polygon_xz(room, wall, op, clearance_inward_mm=25.0)
                if convex_polygons_penetration_2d(p_poly, op_poly) > tol:
                    issues.append(
                        Issue(
                            severity="warning",
                            panel_uid=prod.uid,
                            code="room_opening_blocked",
                            message=(
                                f"Изделие «{prod.name}» перекрывает проём «{op.name}» "
                                f"на стене «{wall.name}»"
                            ),
                        )
                    )
                if op.kind == "door" and op.swing_angle_deg > 1.0:
                    sw = door_swing_geometry_xz(room, wall, op)
                    sector = sw["sector_polygon_xz"]
                    # Проверяем пересечение с каждым треугольником сектора открывания (точно для любого угла <= 180°)
                    hinge = sector[0]
                    hit_swing = False
                    for k in range(1, len(sector) - 1):
                        tri = [hinge, sector[k], sector[k + 1]]
                        if convex_polygons_penetration_2d(p_poly, tri) > tol:
                            hit_swing = True
                            break
                    if hit_swing:
                        issues.append(
                            Issue(
                                severity="warning",
                                panel_uid=prod.uid,
                                code="room_door_swing_blocked",
                                message=(
                                    f"Изделие «{prod.name}» попадает в зону открывания двери «{op.name}» "
                                    f"(стена «{wall.name}»)"
                                ),
                            )
                        )

        # 3. Препятствия и инженерные элементы
        for obs in room.obstacles:
            if not obs.visible:
                continue
            obs_yr = (float(obs.y), float(obs.y) + float(obs.height))
            if _y_overlap_mm(p_yr, obs_yr) <= tol:
                continue
            pen_core = convex_polygons_penetration_2d(p_poly, obstacle_world_corners_xz(obs, inflate_mm=0.0))
            if pen_core > tol:
                issues.append(
                    Issue(
                        severity="error",
                        panel_uid=prod.uid,
                        code="room_obstacle_collision",
                        message=(
                            f"Изделие «{prod.name}» пересекает препятствие «{obs.name}» "
                            f"(врезание {pen_core:.1f} мм)"
                        ),
                    )
                )
            elif obs.clearance_mm > tol:
                pen_clr = convex_polygons_penetration_2d(
                    p_poly, obstacle_world_corners_xz(obs, inflate_mm=obs.clearance_mm)
                )
                if pen_clr > tol:
                    issues.append(
                        Issue(
                            severity="warning",
                            panel_uid=prod.uid,
                            code="room_obstacle_clearance",
                            message=(
                                f"Изделие «{prod.name}» нарушает зону зазора ({obs.clearance_mm:g} мм) "
                                f"препятствия «{obs.name}»"
                            ),
                        )
                    )

        # 4. Превышение допустимого зазора до привязанной / ближайшей неровной стены
        ref_wall = find_nearest_wall_for_product(room, prod)
        if ref_wall is not None and (ref_wall.deviation_stations or prod.anchor_wall_uid == ref_wall.uid):
            rep = measure_product_wall_gaps(
                room,
                prod,
                ref_wall.uid,
                samples_w=5,
                samples_h=3,
                allowed_gap_mm=allowed_gap,
                tolerance_mm=tol,
            )
            if rep.samples and not rep.has_collision and rep.max_gap_mm > allowed_gap + tol and rep.delta_gap_mm > tol:
                issues.append(
                    Issue(
                        severity="warning",
                        panel_uid=prod.uid,
                        code="room_wall_excess_gap",
                        message=(
                            f"Неравномерный зазор «{prod.name}» ↔ «{ref_wall.name}»: "
                            f"мин {rep.min_gap_mm:.1f} мм, макс {rep.max_gap_mm:.1f} мм "
                            f"(перепад {rep.delta_gap_mm:.1f} мм > допуска {allowed_gap:g} мм)"
                        ),
                    )
                )

    # 5. Пересечение изделий мебели между собой
    n_prod = len(visible_products)
    for i in range(n_prod):
        pa = visible_products[i]
        poly_a = product_world_corners_xz(pa)
        yr_a = product_world_y_range(pa)
        for j in range(i + 1, n_prod):
            pb = visible_products[j]
            yr_b = product_world_y_range(pb)
            if _y_overlap_mm(yr_a, yr_b) <= tol:
                continue
            pen = convex_polygons_penetration_2d(poly_a, product_world_corners_xz(pb))
            if pen > tol:
                issues.append(
                    Issue(
                        severity="error",
                        panel_uid=pa.uid,
                        code="room_furniture_collision",
                        message=(
                            f"Пересечение изделий «{pa.name}» и «{pb.name}» "
                            f"(врезание {pen:.1f} мм)"
                        ),
                    )
                )

    return issues
