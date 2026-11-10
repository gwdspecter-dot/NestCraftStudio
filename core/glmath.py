"""Матрицы, адаптивные плоскости отсечения и студийное освещение для OpenGL Core Profile."""

from __future__ import annotations

import math
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]


def identity() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def perspective(fovy_deg: float, aspect: float, z_near: float, z_far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) * 0.5)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / max(aspect, 1e-12)
    m[1, 1] = f
    m[2, 2] = (z_far + z_near) / (z_near - z_far)
    m[2, 3] = (2.0 * z_far * z_near) / (z_near - z_far)
    m[3, 2] = -1.0
    return m


def ortho(left: float, right: float, bottom: float, top: float,
          z_near: float, z_far: float) -> np.ndarray:
    m = np.zeros((4, 4), dtype=np.float32)
    rl = right - left
    tb = top - bottom
    fn = z_far - z_near
    m[0, 0] = 2.0 / rl if abs(rl) > 1e-12 else 1.0
    m[1, 1] = 2.0 / tb if abs(tb) > 1e-12 else 1.0
    m[2, 2] = -2.0 / fn if abs(fn) > 1e-12 else 1.0
    m[0, 3] = -(right + left) / rl if abs(rl) > 1e-12 else 0.0
    m[1, 3] = -(top + bottom) / tb if abs(tb) > 1e-12 else 0.0
    m[2, 3] = -(z_far + z_near) / fn if abs(fn) > 1e-12 else 0.0
    m[3, 3] = 1.0
    return m


def translate(tx: float, ty: float, tz: float) -> np.ndarray:
    m = identity()
    m[0, 3] = tx
    m[1, 3] = ty
    m[2, 3] = tz
    return m


def rotate_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = identity()
    m[1, 1] = c
    m[1, 2] = -s
    m[2, 1] = s
    m[2, 2] = c
    return m


def rotate_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = identity()
    m[0, 0] = c
    m[0, 2] = s
    m[2, 0] = -s
    m[2, 2] = c
    return m


def mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.asarray(a @ b, dtype=np.float32)


def transform_point(m: np.ndarray, x: float, y: float, z: float) -> tuple[float, float, float]:
    v = m @ np.array([x, y, z, 1.0], dtype=np.float32)
    return float(v[0]), float(v[1]), float(v[2])


def project(x: float, y: float, z: float, mvp: np.ndarray,
            viewport: tuple[int, int, int, int]) -> tuple[float, float, float]:
    """Мир → окно (как gluProject). viewport = (x, y, w, h)."""
    v = mvp @ np.array([x, y, z, 1.0], dtype=np.float64)
    if abs(v[3]) < 1e-12:
        return 0.0, 0.0, 0.0
    ndc = v[:3] / v[3]
    vx, vy, vw, vh = viewport
    win_x = vx + (ndc[0] + 1.0) * 0.5 * vw
    win_y = vy + (ndc[1] + 1.0) * 0.5 * vh
    win_z = (ndc[2] + 1.0) * 0.5
    return float(win_x), float(win_y), float(win_z)


def unproject(win_x: float, win_y: float, win_z: float, mvp: np.ndarray,
              viewport: tuple[int, int, int, int]) -> np.ndarray:
    """Окно → мир (как gluUnProject). Возвращает xyz."""
    inv = np.linalg.inv(np.asarray(mvp, dtype=np.float64))
    vx, vy, vw, vh = viewport
    ndc_x = (win_x - vx) / vw * 2.0 - 1.0
    ndc_y = (win_y - vy) / vh * 2.0 - 1.0
    ndc_z = win_z * 2.0 - 1.0
    clip = np.array([ndc_x, ndc_y, ndc_z, 1.0], dtype=np.float64)
    world = inv @ clip
    if abs(world[3]) < 1e-12:
        return world[:3].astype(float)
    return (world[:3] / world[3]).astype(float)


def compute_adaptive_clip_planes(
    zoom: float,
    is_ortho: bool,
    scene_radius: float = 0.0,
) -> tuple[float, float]:
    """Вычисляет адаптивные плоскости отсечения `(z_near, z_far)` под текущий зум и габарит сцены.

    По принципу QymCAD (`ProjParams` / `parts_far_apart_draw_clean`):
    - не раздувает диапазон Z-буфера до фиксированных ±50 000 мм на близких планах,
      повышая точность буфера глубины на тонких кромках и отверстиях в 10–15 раз;
    - автоматически расширяет диапазон при отдалении камеры или большой сцене.
    """
    cam_dist = max(50.0, abs(float(zoom)))
    extent = max(1500.0, float(scene_radius) * 1.6, cam_dist * 1.8)
    if is_ortho:
        half_depth = max(3500.0, cam_dist * 2.5 + extent)
        return (-half_depth, half_depth)

    z_near = max(2.0, min(250.0, cam_dist * 0.04))
    z_far = max(z_near * 60.0, cam_dist + extent * 2.5)
    return (z_near, z_far)


def _norm3(vx: float, vy: float, vz: float) -> tuple[float, float, float]:
    ln = math.sqrt(vx * vx + vy * vy + vz * vz)
    if ln < 1e-12:
        return (0.0, 0.0, 1.0)
    return (vx / ln, vy / ln, vz / ln)


def _view_to_world_dir(
    vx: float,
    vy: float,
    vz: float,
    rot_x_deg: float,
    rot_y_deg: float,
) -> tuple[float, float, float]:
    """Переводит направление из пространства камеры в мировые координаты: R^T = Ry(-rot_y) @ Rx(-rot_x)."""
    ax = math.radians(float(rot_x_deg))
    ay = math.radians(float(rot_y_deg))
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    # Rx^T
    x1 = vx
    y1 = cx * vy + sx * vz
    z1 = -sx * vy + cx * vz
    # Ry^T
    wx = cy * x1 - sy * z1
    wy = y1
    wz = sy * x1 + cy * z1
    return _norm3(wx, wy, wz)


def compute_camera_studio_lights(
    rot_x_deg: float,
    rot_y_deg: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Возвращает `(key_dir, fill_dir, view_dir)` в мировых координатах, привязанные к камере.

    Асимметричная студийная схема из двух источников (в духе QymCAD `SceneLights`):
    - `key_dir` светит сверху-справа-спереди от камеры;
    - `fill_dir` светит снизу-слева-спереди от камеры;
    - `view_dir` направлен от сцены к глазу камеры.
    Гарантирует, что три взаимно перпендикулярные грани детали всегда имеют разные полутона.
    """
    kx, ky, kz = _norm3(0.60, 0.68, 0.42)
    fx, fy, fz = _norm3(-0.25, -0.45, 0.86)
    key_world = _view_to_world_dir(kx, ky, kz, rot_x_deg, rot_y_deg)
    fill_world = _view_to_world_dir(fx, fy, fz, rot_x_deg, rot_y_deg)
    view_world = _view_to_world_dir(0.0, 0.0, 1.0, rot_x_deg, rot_y_deg)
    return key_world, fill_world, view_world


def shade_face_studio(
    normal: tuple[float, float, float] | Any,
    key_dir: tuple[float, float, float] | Any,
    fill_dir: tuple[float, float, float] | Any,
    view_dir: tuple[float, float, float] | Any,
    base_color: tuple[float, float, float] = (0.88, 0.85, 0.80),
) -> tuple[float, float, float]:
    """Точный CPU-эквивалент фрагментного шейдера `_SOLID_FS` для расчёта цвета грани."""
    nx, ny, nz = _norm3(float(normal[0]), float(normal[1]), float(normal[2]))
    vx, vy, vz = _norm3(float(view_dir[0]), float(view_dir[1]), float(view_dir[2]))
    kx, ky, kz = _norm3(float(key_dir[0]), float(key_dir[1]), float(key_dir[2]))
    fx, fy, fz = _norm3(float(fill_dir[0]), float(fill_dir[1]), float(fill_dir[2]))

    ndotk = nx * kx + ny * ky + nz * kz
    ndotf = nx * fx + ny * fy + nz * fz
    key_diff = max(0.0, ndotk) + 0.14 * max(0.0, -ndotk)
    fill_diff = max(0.0, ndotf) + 0.10 * max(0.0, -ndotf)
    shade = 0.28 + 0.62 * key_diff + 0.16 * fill_diff

    hx, hy, hz = _norm3(kx + vx, ky + vy, kz + vz)
    ndh = max(0.0, nx * hx + ny * hy + nz * hz)
    spec = (ndh ** 28.0) * 0.09

    r = min(1.0, max(0.0, float(base_color[0]) * shade + spec))
    g = min(1.0, max(0.0, float(base_color[1]) * shade + spec))
    b = min(1.0, max(0.0, float(base_color[2]) * shade + spec))
    return (r, g, b)


def compute_section_clip_plane(
    axis: str,
    offset: float,
    flip: bool = False,
) -> tuple[float, float, float, float]:
    """Возвращает уравнение секущей плоскости `(nx, ny, nz, d)` для `GL_CLIP_DISTANCE0`.

    Условие видимости фрагмента в GLSL: `dot(worldPos, vec3(nx, ny, nz)) + d >= 0`.
    По умолчанию (`flip=False`) отсекается передняя/верхняя/правая часть (`coord > offset`),
    оставляя видимой внутренность шкафа (`coord <= offset`, т.е. `-coord + offset >= 0`).
    При `flip=True` остаётся видимой часть `coord >= offset` (`+coord - offset >= 0`).
    """
    ax = str(axis or "Z").upper()
    off = float(offset)
    sign = 1.0 if flip else -1.0
    d = -off if flip else off
    if ax == "X":
        return (sign, 0.0, 0.0, d)
    if ax == "Y":
        return (0.0, sign, 0.0, d)
    return (0.0, 0.0, sign, d)


def point_passes_clip_plane(
    x: float,
    y: float,
    z: float,
    plane: tuple[float, float, float, float] | None,
    eps: float = -1e-4,
) -> bool:
    """True, если мировая точка `(x, y, z)` не отсечена плоскостью сечения `plane`."""
    if plane is None:
        return True
    nx, ny, nz, d = float(plane[0]), float(plane[1]), float(plane[2]), float(plane[3])
    if nx * nx + ny * ny + nz * nz < 1e-8:
        return True
    return (x * nx + y * ny + z * nz + d) >= eps


def compute_scene_axis_bounds(
    panels: list[Any] | tuple[Any, ...],
    axis: str = "Z",
) -> tuple[float, float]:
    """Вычисляет габаритный интервал `[lo, hi]` всех видимых деталей сцены по оси `X`, `Y` или `Z`."""
    ax_idx = {"X": 0, "Y": 1, "Z": 2}.get(str(axis or "Z").upper(), 2)
    lo = float("inf")
    hi = float("-inf")
    for p in panels or ():
        if not getattr(p, "visible", True):
            continue
        if hasattr(p, "world_aabb"):
            mn, mx = p.world_aabb()
            c_lo, c_hi = float(mn[ax_idx]), float(mx[ax_idx])
        else:
            coords = (
                (float(p.x), float(p.x) + float(p.width)),
                (float(p.y), float(p.y) + float(p.height)),
                (float(p.z), float(p.z) + float(p.depth)),
            )[ax_idx]
            c_lo, c_hi = min(coords), max(coords)
        if c_lo < lo:
            lo = c_lo
        if c_hi > hi:
            hi = c_hi
    if lo == float("inf") or hi == float("-inf") or hi <= lo:
        defaults = {"X": (0.0, 600.0), "Y": (0.0, 820.0), "Z": (0.0, 560.0)}
        return defaults.get(str(axis or "Z").upper(), (0.0, 600.0))
    return (lo, hi)


def compute_panel_face_handles(
    p: Any,
    allow_axes: tuple[bool, bool, bool] = (True, True, True),
) -> list[tuple[tuple[int, int], Any, Any, str]]:
    """Возвращает ручки вытягивания рабочих торцов детали («Тянуть грань в 3D» / Push-Pull).

    Пропускает пласть вдоль `thickness_axis`, чтобы толщина плиты оставалась неизменной.
    Возвращает список `((axis_idx, side), world_center, world_outward_normal, label)`.
    """
    w, h, d = float(p.width), float(p.height), float(p.depth)
    wm, hm, dm = w * 0.5, h * 0.5, d * 0.5
    raw_tax = getattr(p, "thickness_axis", -1)
    if isinstance(raw_tax, str):
        tax = {"X": 0, "Y": 1, "Z": 2}.get(raw_tax.upper(), -1)
    else:
        try:
            tax = int(raw_tax)
        except (TypeError, ValueError):
            tax = -1
    has_ltw = hasattr(p, "local_to_world")
    has_rot = hasattr(p, "has_rotation") and p.has_rotation() and hasattr(p, "rotate_vector")

    def _vec3(x: float, y: float, z: float):
        if np is not None:
            return np.array([x, y, z], dtype=float)
        return (float(x), float(y), float(z))

    def to_world(lx: float, ly: float, lz: float):
        if has_ltw:
            wx, wy, wz = p.local_to_world(lx, ly, lz)
            return _vec3(wx, wy, wz)
        return _vec3(float(p.x) + lx, float(p.y) + ly, float(p.z) + lz)

    def to_world_dir(nx: float, ny: float, nz: float):
        if has_rot:
            rx, ry, rz = p.rotate_vector(nx, ny, nz)
            ux, uy, uz = _norm3(rx, ry, rz)
        else:
            ux, uy, uz = _norm3(nx, ny, nz)
        return _vec3(ux, uy, uz)

    defs = [
        ((0, 0), (0.0, hm, dm), (-1.0, 0.0, 0.0), "Левый торец (-X)"),
        ((0, 1), (w, hm, dm), (1.0, 0.0, 0.0), "Правый торец (+X)"),
        ((1, 0), (wm, 0.0, dm), (0.0, -1.0, 0.0), "Нижний торец (-Y)"),
        ((1, 1), (wm, h, dm), (0.0, 1.0, 0.0), "Верхний торец (+Y)"),
        ((2, 0), (wm, hm, 0.0), (0.0, 0.0, -1.0), "Задний торец (-Z)"),
        ((2, 1), (wm, hm, d), (0.0, 0.0, 1.0), "Передний торец (+Z)"),
    ]
    out = []
    for (ax_idx, side), lpt, lnrm, label in defs:
        if ax_idx == tax or not allow_axes[ax_idx]:
            continue
        out.append(((ax_idx, side), to_world(*lpt), to_world_dir(*lnrm), label))
    return out


def compute_face_push_pull_box(
    orig_box: tuple[float, float, float, float, float, float],
    face_id: tuple[int, int],
    new_len: float,
    panel: Any = None,
    min_size: float = 10.0,
) -> tuple[float, float, float, float, float, float]:
    """Вычисляет новые `(x, y, z, width, height, depth)` детали при вытягивании торца `face_id = (axis_idx, side)`
    до длины `new_len` при неподвижной в мире противоположной грани."""
    x0, y0, z0, w, h, d = [float(v) for v in orig_box]
    ax_idx, side = int(face_id[0]), int(face_id[1])
    clamped_len = max(float(min_size), float(new_len))
    dims = [w, h, d]
    new_dims = [w, h, d]
    new_dims[ax_idx] = clamped_len

    has_rot = (
        panel is not None
        and hasattr(panel, "has_rotation")
        and panel.has_rotation()
        and hasattr(panel, "rotate_vector")
    )
    if has_rot:
        sign = 1.0 if side == 1 else -1.0
        local_dir = [0.0, 0.0, 0.0]
        local_dir[ax_idx] = sign
        fixed_local = [w * 0.5, h * 0.5, d * 0.5]
        fixed_local[ax_idx] = 0.0 if side == 1 else dims[ax_idx]
        cx_orig, cy_orig, cz_orig = x0 + w * 0.5, y0 + h * 0.5, z0 + d * 0.5
        rfx, rfy, rfz = panel.rotate_vector(
            fixed_local[0] - w * 0.5,
            fixed_local[1] - h * 0.5,
            fixed_local[2] - d * 0.5,
        )
        fwx, fwy, fwz = cx_orig + rfx, cy_orig + rfy, cz_orig + rfz
        rdx, rdy, rdz = panel.rotate_vector(*local_dir)
        ax_x, ax_y, ax_z = _norm3(rdx, rdy, rdz)
        half_len = clamped_len * 0.5
        cx_new = fwx + ax_x * half_len
        cy_new = fwy + ax_y * half_len
        cz_new = fwz + ax_z * half_len
        nx = cx_new - new_dims[0] * 0.5
        ny = cy_new - new_dims[1] * 0.5
        nz = cz_new - new_dims[2] * 0.5
        return (nx, ny, nz, new_dims[0], new_dims[1], new_dims[2])

    coords = [x0, y0, z0]
    if side == 0:
        coords[ax_idx] = (coords[ax_idx] + dims[ax_idx]) - clamped_len
    return (coords[0], coords[1], coords[2], new_dims[0], new_dims[1], new_dims[2])


def compute_aabb_intersection_box(
    a0: tuple[float, float, float],
    a1: tuple[float, float, float],
    b0: tuple[float, float, float],
    b1: tuple[float, float, float],
    eps: float = 0.05,
) -> tuple[float, float, float, float, float, float] | None:
    """Возвращает 3D-бокс зоны взаимного врезания `(x, y, z, w, h, d)` двух AABB или `None`,
    если детали лишь касаются гранями (`overlap <= eps`) либо не пересекаются."""
    ix0 = max(float(a0[0]), float(b0[0]))
    iy0 = max(float(a0[1]), float(b0[1]))
    iz0 = max(float(a0[2]), float(b0[2]))
    ix1 = min(float(a1[0]), float(b1[0]))
    iy1 = min(float(a1[1]), float(b1[1]))
    iz1 = min(float(a1[2]), float(b1[2]))
    iw = ix1 - ix0
    ih = iy1 - iy0
    id_ = iz1 - iz0
    if iw <= eps or ih <= eps or id_ <= eps:
        return None
    return (ix0, iy0, iz0, iw, ih, id_)


def _obb_sat_overlaps(pa: Any, pb: Any, eps: float = 0.05) -> bool:
    """Точная SAT-фильтрация для наклонных панелей (`has_rotation()`) по нормалям граней OBB."""
    if not (hasattr(pa, "obb") and hasattr(pb, "obb")):
        return True
    ca, axes_a, half_a = pa.obb()
    cb, axes_b, half_b = pb.obb()
    dx = float(cb[0]) - float(ca[0])
    dy = float(cb[1]) - float(ca[1])
    dz = float(cb[2]) - float(ca[2])

    for n in tuple(axes_a) + tuple(axes_b):
        nx, ny, nz = float(n[0]), float(n[1]), float(n[2])
        dist = abs(dx * nx + dy * ny + dz * nz)
        ra = sum(
            float(half_a[k]) * abs(float(axes_a[k][0]) * nx + float(axes_a[k][1]) * ny + float(axes_a[k][2]) * nz)
            for k in range(3)
        )
        rb = sum(
            float(half_b[k]) * abs(float(axes_b[k][0]) * nx + float(axes_b[k][1]) * ny + float(axes_b[k][2]) * nz)
            for k in range(3)
        )
        if (ra + rb) - dist <= eps:
            return False
    return True


def find_live_panel_collisions(
    panels: list[Any] | tuple[Any, ...],
    eps: float = 0.05,
    min_volume: float = 1.0,
) -> list[tuple[Any, Any, tuple[float, float, float, float, float, float], float]]:
    """Быстрый поиск живых 3D-коллизий деталей сцены в реальном времени (без блокировки UI).

    Возвращает список `(panel_a, panel_b, overlap_box_xyzwhd, volume_mm3)`:
    - Исключает касание смежных торцов/пластей (`overlap <= eps`);
    - Для повёрнутых панелей дополнительно выполняет SAT-проверку по осям OBB.
    """
    vis_panels = [p for p in (panels or ()) if getattr(p, "visible", True)]
    n = len(vis_panels)
    if n < 2:
        return []

    aabbs = []
    rots = []
    for p in vis_panels:
        if hasattr(p, "world_aabb"):
            aabbs.append(p.world_aabb())
        else:
            x0, y0, z0 = float(p.x), float(p.y), float(p.z)
            aabbs.append(((x0, y0, z0), (x0 + float(p.width), y0 + float(p.height), z0 + float(p.depth))))
        rots.append(bool(hasattr(p, "has_rotation") and p.has_rotation()))

    hits: list[tuple[Any, Any, tuple[float, float, float, float, float, float], float]] = []
    for i in range(n):
        a0, a1 = aabbs[i]
        pa = vis_panels[i]
        rot_a = rots[i]
        for j in range(i + 1, n):
            b0, b1 = aabbs[j]
            box = compute_aabb_intersection_box(a0, a1, b0, b1, eps=eps)
            if box is None:
                continue
            vol = box[3] * box[4] * box[5]
            if vol < min_volume:
                continue
            pb = vis_panels[j]
            if (rot_a or rots[j]) and not _obb_sat_overlaps(pa, pb, eps=eps):
                continue
            hits.append((pa, pb, box, float(vol)))
    return hits



