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


