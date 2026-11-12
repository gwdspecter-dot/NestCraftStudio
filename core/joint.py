"""Поиск стыка двух осевых панелей и проекция точки на стык."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
import numpy as np

from core.logging_setup import get_logger

_log = get_logger("joint")


@dataclass
class Joint:
    """Прямоугольный стык (контакт двух AABB-панелей)."""
    panel_a: object
    panel_b: object
    # Точка-начало стыка (мировые координаты)
    origin: np.ndarray  # shape (3,)
    # Ось скольжения крепежа (единичный)
    slide_dir: np.ndarray
    # Вторая ось в плоскости стыка (если стык-площадка; иначе ~0)
    slide_dir2: np.ndarray
    # Диапазоны параметра t вдоль slide_dir: position = origin + t * slide_dir + s * slide_dir2
    t_min: float
    t_max: float
    s_min: float
    s_max: float
    # Нормаль сверления: из A в B
    drill_dir: np.ndarray
    drill_axis: str  # "X" | "Y" | "Z"


def _overlap_1d(a0, a1, b0, b1, tol=0.5, min_len: float = 0.5):
    """Перекрытие двух отрезков.

    Возвращает (lo, hi) только если длина перекрытия строго >= min_len.
    Касание ребром/углом (нулевая длина) больше не считается стыком.
    Параметр tol сохранён для совместимости вызовов; на длину не влияет.
    """
    lo = max(float(a0), float(b0))
    hi = min(float(a1), float(b1))
    if hi - lo < float(min_len):
        return None
    return (lo, hi)


def _panel_obb_arrays(p):
    """Возвращает (center, axes_3x3, half_extents) как np.ndarray float."""
    if hasattr(p, "obb"):
        c, axes, half = p.obb()
        return (
            np.asarray(c, dtype=float),
            np.asarray(axes, dtype=float),
            np.asarray(half, dtype=float),
        )
    cx = float(p.x) + float(p.width) * 0.5
    cy = float(p.y) + float(p.height) * 0.5
    cz = float(p.z) + float(p.depth) * 0.5
    return (
        np.array([cx, cy, cz], dtype=float),
        np.eye(3, dtype=float),
        np.array([float(p.width) * 0.5, float(p.height) * 0.5, float(p.depth) * 0.5], dtype=float),
    )


def _obb_interval(center: np.ndarray, axes: np.ndarray, half: np.ndarray, unit_dir: np.ndarray) -> tuple[float, float]:
    """Проекция OBB на единичную ось unit_dir -> (lo, hi)."""
    c_proj = float(np.dot(center, unit_dir))
    r = float(
        half[0] * abs(np.dot(axes[0], unit_dir))
        + half[1] * abs(np.dot(axes[1], unit_dir))
        + half[2] * abs(np.dot(axes[2], unit_dir))
    )
    return c_proj - r, c_proj + r


def _find_joint_obb(panel_a, panel_b, tol: float = 2.5) -> Joint | None:
    """Поиск плоского стыка двух OBB-панелей (с поддержкой произвольных поворотов, план §1.5)."""
    ca, ua, ha = _panel_obb_arrays(panel_a)
    cb, ub, hb = _panel_obb_arrays(panel_b)

    # Быстрая проверка по разделяющим осям (6 нормалей граней OBB)
    for u in (ua[0], ua[1], ua[2], ub[0], ub[1], ub[2]):
        a0, a1 = _obb_interval(ca, ua, ha, u)
        b0, b1 = _obb_interval(cb, ub, hb, u)
        if a1 < b0 - tol or b1 < a0 - tol:
            return None

    best_joint: Joint | None = None
    best_gap = float(tol) + 1.0

    # Проверяем каждую грань панели A (и симметрично грани панели B) как плоскость контакта
    candidate_bases = [
        (ua[0], ua[1], ua[2]),
        (ua[1], ua[0], ua[2]),
        (ua[2], ua[0], ua[1]),
        (ub[0], ub[1], ub[2]),
        (ub[1], ub[0], ub[2]),
        (ub[2], ub[0], ub[1]),
    ]

    for un_raw, e1_raw, e2_raw in candidate_bases:
        un = un_raw / max(float(np.linalg.norm(un_raw)), 1e-12)
        e1 = e1_raw / max(float(np.linalg.norm(e1_raw)), 1e-12)
        e2 = e2_raw / max(float(np.linalg.norm(e2_raw)), 1e-12)

        # Обе панели должны иметь грань, коллинеарную un (косинус >= 0.985, т.е. ~10°)
        align_a = max(abs(float(np.dot(ua[m], un))) for m in range(3))
        align_b = max(abs(float(np.dot(ub[m], un))) for m in range(3))
        if align_a < 0.985 or align_b < 0.985:
            continue

        a_lo, a_hi = _obb_interval(ca, ua, ha, un)
        b_lo, b_hi = _obb_interval(cb, ub, hb, un)

        gap_ab = abs(a_hi - b_lo)
        gap_ba = abs(b_hi - a_lo)
        if gap_ab <= tol and gap_ab <= gap_ba:
            gap = gap_ab
            pn = 0.5 * (a_hi + b_lo)
            drill = un.copy()  # из A в B
        elif gap_ba <= tol:
            gap = gap_ba
            pn = 0.5 * (b_hi + a_lo)
            drill = -un.copy()  # из A в B
        else:
            continue

        # Перекрытие в касательной плоскости (e1, e2)
        a1_lo, a1_hi = _obb_interval(ca, ua, ha, e1)
        b1_lo, b1_hi = _obb_interval(cb, ub, hb, e1)
        o1 = _overlap_1d(a1_lo, a1_hi, b1_lo, b1_hi, tol)
        if o1 is None:
            continue

        a2_lo, a2_hi = _obb_interval(ca, ua, ha, e2)
        b2_lo, b2_hi = _obb_interval(cb, ub, hb, e2)
        o2 = _overlap_1d(a2_lo, a2_hi, b2_lo, b2_hi, tol)
        if o2 is None:
            continue

        u0, u1 = o1
        v0, v1 = o2
        len1 = u1 - u0
        len2 = v1 - v0
        if len1 >= len2:
            origin = pn * un + u0 * e1 + 0.5 * (v0 + v1) * e2
            slide = e1.copy()
            slide2 = e2.copy()
            t_min, t_max = 0.0, float(len1)
            s_min, s_max = -0.5 * float(len2), 0.5 * float(len2)
        else:
            origin = pn * un + 0.5 * (u0 + u1) * e1 + v0 * e2
            slide = e2.copy()
            slide2 = e1.copy()
            t_min, t_max = 0.0, float(len2)
            s_min, s_max = -0.5 * float(len1), 0.5 * float(len1)

        dom_idx = int(np.argmax(np.abs(drill)))
        dom_axis = ("X", "Y", "Z")[dom_idx]

        if gap < best_gap:
            best_gap = gap
            best_joint = Joint(
                panel_a, panel_b,
                origin, slide, slide2,
                t_min, t_max, s_min, s_max,
                drill, dom_axis,
            )

    return best_joint


def find_joint(panel_a, panel_b, tol: float = 2.5) -> Joint | None:
    """
    Ищет контакт двух панелей (AABB или OBB при повороте, план §1.5).
    Стык = одна ось с зазором ~0 (касание граней), две другие — перекрытие.
    """
    a, b = panel_a, panel_b
    if getattr(a, "has_rotation", lambda: False)() or getattr(b, "has_rotation", lambda: False)():
        return _find_joint_obb(a, b, tol=tol)
    ax0, ay0, az0 = a.x, a.y, a.z
    ax1, ay1, az1 = a.x + a.width, a.y + a.height, a.z + a.depth
    bx0, by0, bz0 = b.x, b.y, b.z
    bx1, by1, bz1 = b.x + b.width, b.y + b.height, b.z + b.depth

    # Касание по X?
    touch_x = abs(ax1 - bx0) <= tol or abs(bx1 - ax0) <= tol
    touch_y = abs(ay1 - by0) <= tol or abs(by1 - ay0) <= tol
    touch_z = abs(az1 - bz0) <= tol or abs(bz1 - az0) <= tol

    oy = _overlap_1d(ay0, ay1, by0, by1, tol)
    oz = _overlap_1d(az0, az1, bz0, bz1, tol)
    ox = _overlap_1d(ax0, ax1, bx0, bx1, tol)

    # Приоритет: явная грань касания
    if touch_x and oy and oz:
        # плоскость YZ
        if abs(ax1 - bx0) <= tol:
            x = 0.5 * (ax1 + bx0)
            drill = np.array([1.0, 0.0, 0.0])  # A -> B (A слева, B справа)
        else:
            x = 0.5 * (bx1 + ax0)
            drill = np.array([-1.0, 0.0, 0.0])  # A -> B (A справа, B слева)
        y0, y1 = oy
        z0, z1 = oz
        # Скольжение вдоль длинной стороны стыка
        if (y1 - y0) >= (z1 - z0):
            origin = np.array([x, y0, 0.5 * (z0 + z1)])
            slide = np.array([0.0, 1.0, 0.0])
            slide2 = np.array([0.0, 0.0, 1.0])
            t_min, t_max = 0.0, y1 - y0
            s_min, s_max = z0 - origin[2], z1 - origin[2]
        else:
            origin = np.array([x, 0.5 * (y0 + y1), z0])
            slide = np.array([0.0, 0.0, 1.0])
            slide2 = np.array([0.0, 1.0, 0.0])
            t_min, t_max = 0.0, z1 - z0
            s_min, s_max = y0 - origin[1], y1 - origin[1]
        return Joint(a, b, origin, slide, slide2, t_min, t_max, s_min, s_max, drill, "X")

    if touch_y and ox and oz:
        if abs(ay1 - by0) <= tol:
            y = 0.5 * (ay1 + by0)
            drill = np.array([0.0, 1.0, 0.0])
        else:
            y = 0.5 * (by1 + ay0)
            drill = np.array([0.0, -1.0, 0.0])
        x0, x1 = ox
        z0, z1 = oz
        if (x1 - x0) >= (z1 - z0):
            origin = np.array([x0, y, 0.5 * (z0 + z1)])
            slide = np.array([1.0, 0.0, 0.0])
            slide2 = np.array([0.0, 0.0, 1.0])
            t_min, t_max = 0.0, x1 - x0
            s_min, s_max = z0 - origin[2], z1 - origin[2]
        else:
            origin = np.array([0.5 * (x0 + x1), y, z0])
            slide = np.array([0.0, 0.0, 1.0])
            slide2 = np.array([1.0, 0.0, 0.0])
            t_min, t_max = 0.0, z1 - z0
            s_min, s_max = x0 - origin[0], x1 - origin[0]
        return Joint(a, b, origin, slide, slide2, t_min, t_max, s_min, s_max, drill, "Y")

    if touch_z and ox and oy:
        if abs(az1 - bz0) <= tol:
            z = 0.5 * (az1 + bz0)
            drill = np.array([0.0, 0.0, 1.0])
        else:
            z = 0.5 * (bz1 + az0)
            drill = np.array([0.0, 0.0, -1.0])
        x0, x1 = ox
        y0, y1 = oy
        if (x1 - x0) >= (y1 - y0):
            origin = np.array([x0, 0.5 * (y0 + y1), z])
            slide = np.array([1.0, 0.0, 0.0])
            slide2 = np.array([0.0, 1.0, 0.0])
            t_min, t_max = 0.0, x1 - x0
            s_min, s_max = y0 - origin[1], y1 - origin[1]
        else:
            origin = np.array([0.5 * (x0 + x1), y0, z])
            slide = np.array([0.0, 1.0, 0.0])
            slide2 = np.array([1.0, 0.0, 0.0])
            t_min, t_max = 0.0, y1 - y0
            s_min, s_max = x0 - origin[0], x1 - origin[0]
        return Joint(a, b, origin, slide, slide2, t_min, t_max, s_min, s_max, drill, "Z")

    return None


def _panel_local_drill_axis(panel, drill_dir, fallback_axis: str = "X") -> str:
    """Определяет локальную ось сверления ('X'|'Y'|'Z') панели по мировому вектору drill_dir."""
    if drill_dir is not None and hasattr(panel, "has_rotation") and panel.has_rotation() and hasattr(panel, "unrotate_vector"):
        lx, ly, lz = panel.unrotate_vector(float(drill_dir[0]), float(drill_dir[1]), float(drill_dir[2]))
        vals = (abs(lx), abs(ly), abs(lz))
        idx = 0 if (vals[0] >= vals[1] and vals[0] >= vals[2]) else (1 if vals[1] >= vals[2] else 2)
        return ("X", "Y", "Z")[idx]
    return fallback_axis


def _panel_thickness(panel) -> float:
    """Возвращает толщину детали через panel.get_thickness() (с fallback для тестовых стабов)."""
    if hasattr(panel, "get_thickness") and callable(panel.get_thickness):
        return float(panel.get_thickness())
    if getattr(panel, "thickness_axis", None) is not None:
        ta = panel.thickness_axis
        dims = (float(panel.width), float(panel.height), float(panel.depth))
        if isinstance(ta, str) and ta.upper() in ("X", "Y", "Z"):
            return dims[("X", "Y", "Z").index(ta.upper())]
        return dims[int(ta) % 3]
    return float(min(panel.width, panel.height, panel.depth))


def is_face_drilling(panel, axis: str) -> bool:
    """Определяет, сверлится ли деталь в пласть (вдоль оси толщины panel.get_thickness()) или в торец."""
    thickness = _panel_thickness(panel)
    dims = {"X": float(panel.width), "Y": float(panel.height), "Z": float(panel.depth)}
    if getattr(panel, "thickness_axis", None) is not None:
        ta = panel.thickness_axis
        if isinstance(ta, str) and ta.upper() in ("X", "Y", "Z"):
            ta_axis = ta.upper()
        else:
            ta_axis = ("X", "Y", "Z")[int(ta) % 3]
        if abs(dims[ta_axis] - thickness) < 1e-6:
            return axis == ta_axis
    if axis in dims and abs(dims[axis] - thickness) < 1e-6:
        return True
    min_dim_axis = min(dims, key=dims.get)
    return axis == min_dim_axis


def clamp_joint_point(joint: Joint, world_point: np.ndarray, margin: float = 20.0) -> np.ndarray:
    """Проецирует точку на плоскость/отрезок стыка с отступами от краёв."""
    o = joint.origin
    d1 = joint.slide_dir
    d2 = joint.slide_dir2
    rel = world_point - o
    t = float(np.dot(rel, d1))
    s = float(np.dot(rel, d2)) if np.linalg.norm(d2) > 1e-9 else 0.0

    t0 = joint.t_min + margin
    t1 = joint.t_max - margin
    if t1 < t0:
        t = 0.5 * (joint.t_min + joint.t_max)
    else:
        t = min(max(t, t0), t1)

    s0 = joint.s_min + margin * 0.25
    s1 = joint.s_max - margin * 0.25
    if s1 < s0:
        s = 0.5 * (joint.s_min + joint.s_max)
    else:
        s = min(max(s, s0), s1)

    return o + t * d1 + s * d2


# Пресеты крепежа по стыку: раскладка (шаг/число) + ссылка на каталог.
# diameter/depth подтягиваются из CatalogService при первом обращении (см. _enrich_presets).
FASTENER_PRESETS: dict[str, dict] = {
    "confirmat_3": {
        "label": "Конфирмат ×3 (отступ 50)",
        "fastener_id": "fst_conf_7x50",
        "diameter": 7.0,
        "depth": 42.0,
        "count": 3,
        "margin": 50.0,
        "pitch": None,
    },
    "confirmat_128": {
        "label": "Конфирмат шаг 128 (отступ 50)",
        "fastener_id": "fst_conf_7x50",
        "diameter": 7.0,
        "depth": 42.0,
        "count": None,
        "margin": 50.0,
        "pitch": 128.0,
    },
    "dowel_96": {
        "label": "Шкант Ø8 шаг 96 (отступ 50)",
        "fastener_id": "fst_dowel_8x30",
        "diameter": 8.0,
        "depth": 24.0,
        "count": None,
        "margin": 50.0,
        "pitch": 96.0,
    },
    "confirmat_2": {
        "label": "Конфирмат ×2 (отступ 50)",
        "fastener_id": "fst_conf_7x50",
        "diameter": 7.0,
        "depth": 42.0,
        "count": 2,
        "margin": 50.0,
        "pitch": None,
    },
}

FASTENER_PRESET_ORDER = ["confirmat_3", "confirmat_128", "dowel_96", "confirmat_2"]

_presets_enriched = False


def resolve_fastener(fastener=None, fastener_id: str | None = None):
    """Достаёт объект Fastener из аргумента или каталога. None — если нет."""
    if fastener is not None:
        return fastener
    fid = (fastener_id or "").strip()
    if not fid:
        return None
    try:
        from core.catalog import CatalogService
        return CatalogService.instance().get_fastener(fid)
    except Exception:  # noqa: BLE001 — граница каталога SQLite
        _log.exception("resolve_fastener(%s) failed", fid)
        return None


def _enrich_presets_from_catalog() -> None:
    """Один раз подставляет diameter/depth из каталога крепежа (для UI)."""
    global _presets_enriched
    if _presets_enriched:
        return
    _presets_enriched = True
    try:
        from core.catalog import CatalogService
        cat = CatalogService.instance()
        for preset in FASTENER_PRESETS.values():
            fid = preset.get("fastener_id")
            if not fid:
                continue
            f = cat.get_fastener(fid)
            if f is None:
                continue
            # UI-ориентир: диаметр пласти, глубина торца
            if f.drill_face_diameter > 0:
                preset["diameter"] = float(f.drill_face_diameter)
            elif f.diameter_mm > 0:
                preset["diameter"] = float(f.diameter_mm)
            if f.drill_edge_depth > 0:
                preset["depth"] = float(f.drill_edge_depth)
            elif f.length_mm > 0:
                preset["depth"] = float(f.length_mm)
    except Exception:  # noqa: BLE001 — граница каталога
        _log.exception("preset catalog enrich failed")


def get_fastener_preset(preset_id: str) -> dict:
    """Возвращает пресет с актуальными diameter/depth из каталога."""
    _enrich_presets_from_catalog()
    return FASTENER_PRESETS.get(preset_id, {})


def joint_array_points(
    joint: Joint,
    count: int | None = 3,
    margin: float | None = None,
    diameter: float = 7.0,
    center_t: float | None = None,
    pitch: float | None = None,
) -> list[np.ndarray]:
    """
    Массив точек крепежа вдоль стыка.

    - count: равномерно на [t_min+margin, t_max-margin]
    - pitch: шаг мм от t0; count игнорируется (или ограничивает число)
    - center_t: сдвиг группы к курсору в пределах стыка
    """
    if margin is None:
        margin = max(18.0, float(diameter) * 2.0)
    o = joint.origin
    d1 = joint.slide_dir
    d2 = joint.slide_dir2
    s = 0.5 * (joint.s_min + joint.s_max)
    t0 = joint.t_min + margin
    t1 = joint.t_max - margin
    if t1 < t0:
        tm = 0.5 * (joint.t_min + joint.t_max)
        return [o + tm * d1 + s * d2]

    span = t1 - t0
    ts: list[float] = []

    if pitch is not None and float(pitch) > 1e-6:
        p = float(pitch)
        t = t0
        while t <= t1 + 1e-6:
            ts.append(t)
            t += p
        if not ts:
            ts = [0.5 * (t0 + t1)]
        if count is not None and int(count) > 0 and len(ts) > int(count):
            # оставить count точек ближе к центру / center_t
            ref = float(center_t) if center_t is not None else 0.5 * (t0 + t1)
            ts.sort(key=lambda x: abs(x - ref))
            ts = sorted(ts[: int(count)])
    else:
        n = max(1, min(int(count or 3), 12))
        if n <= 1:
            ts = [0.5 * (t0 + t1)]
        else:
            ts = [t0 + span * i / (n - 1) for i in range(n)]

    if center_t is not None and ts:
        mid = 0.5 * (ts[0] + ts[-1])
        shift = float(center_t) - mid
        ts = [t + shift for t in ts]
        if ts[0] < t0:
            sh = t0 - ts[0]
            ts = [t + sh for t in ts]
        if ts[-1] > t1:
            sh = t1 - ts[-1]
            ts = [t + sh for t in ts]

    return [o + float(t) * d1 + s * d2 for t in ts]


def world_to_local_hole(panel, world_pt: np.ndarray, drill_axis: str, depth: float, radius: float, drill_dir=None):
    """Локальные координаты отверстия на панели (точка входа на грани)."""
    if hasattr(panel, "world_to_local") and getattr(panel, "has_rotation", lambda: False)():
        lx, ly, lz = panel.world_to_local(float(world_pt[0]), float(world_pt[1]), float(world_pt[2]))
    else:
        lx = float(world_pt[0] - panel.x)
        ly = float(world_pt[1] - panel.y)
        lz = float(world_pt[2] - panel.z)
    loc_axis = _panel_local_drill_axis(panel, drill_dir, drill_axis)
    # Прижимаем точку входа к соответствующей грани по оси сверления
    if loc_axis == "X":
        if lx < panel.width * 0.5:
            lx = 0.0
        else:
            lx = panel.width
        ly = min(max(ly, radius), panel.height - radius)
        lz = min(max(lz, radius), panel.depth - radius)
    elif loc_axis == "Y":
        if ly < panel.height * 0.5:
            ly = 0.0
        else:
            ly = panel.height
        lx = min(max(lx, radius), panel.width - radius)
        lz = min(max(lz, radius), panel.depth - radius)
    else:
        if lz < panel.depth * 0.5:
            lz = 0.0
        else:
            lz = panel.depth
        lx = min(max(lx, radius), panel.width - radius)
        ly = min(max(ly, radius), panel.height - radius)
    return (lx, ly, lz, radius, depth, loc_axis)


def _hole_dims_for_fastener(
    panel,
    axis: str,
    diameter: float,
    depth: float,
    fastener=None,
    issues: list | None = None,
    *,
    face_diameter: float | None = None,
    edge_diameter: float | None = None,
    edge_depth: float | None = None,
):
    """Диаметр и глубина сверления для одной панели (пласть / торец).

    Приоритет:
    1) Явные переопределения конструктора крепежа (face_diameter / d1, edge_diameter / d2, edge_depth);
    2) Правила Fastener из каталога (drill_face_* / drill_edge_* / drill_through);
    3) Legacy-эвристика по диаметру.
    """
    is_face = is_face_drilling(panel, axis)
    thickness = _panel_thickness(panel)
    f_dia_override = float(face_diameter) if (face_diameter is not None and float(face_diameter) > 0) else None
    e_dia_override = float(edge_diameter) if (edge_diameter is not None and float(edge_diameter) > 0) else None
    e_dep_override = float(edge_depth) if (edge_depth is not None and float(edge_depth) > 0) else None

    if fastener is not None:
        # Совместимость с толщиной детали (п. 1.8: лог + сбор замечаний Issue)
        tmin = float(getattr(fastener, "min_panel_thickness", 0) or 0)
        tmax = float(getattr(fastener, "max_panel_thickness", 0) or 0)
        if tmin > 0 and thickness + 1e-6 < tmin:
            _log.warning(
                "Fastener %s: thickness %.1f < min %.1f",
                getattr(fastener, "id", "?"), thickness, tmin,
            )
        if tmax > 0 and thickness - 1e-6 > tmax:
            _log.warning(
                "Fastener %s: thickness %.1f > max %.1f",
                getattr(fastener, "id", "?"), thickness, tmax,
            )
        try:
            from core.issues import check_fastener_thickness_issue, record_panel_issue
            iss = check_fastener_thickness_issue(panel, fastener)
            if iss is not None:
                record_panel_issue(panel, iss)
                if issues is not None and not any(
                    x.code == iss.code and x.message == iss.message for x in issues
                ):
                    issues.append(iss)
        except Exception:  # noqa: BLE001 — не рвём сверление из-за issues
            _log.exception("Failed to record fastener thickness issue")

        if is_face:
            dia = f_dia_override if f_dia_override is not None else float(
                getattr(fastener, "drill_face_diameter", 0)
                or getattr(fastener, "diameter_mm", 0)
                or diameter
            )
            if getattr(fastener, "drill_through", False) or f_dia_override is not None:
                dep = thickness
            else:
                face_d = float(getattr(fastener, "drill_face_depth", 0) or 0)
                dep = min(face_d, thickness) if face_d > 0 else thickness
            return dia, float(dep)

        dia = e_dia_override if e_dia_override is not None else float(
            getattr(fastener, "drill_edge_diameter", 0)
            or getattr(fastener, "diameter_mm", 0)
            or diameter
        )
        if e_dep_override is not None:
            dep = e_dep_override
        else:
            edge_d = float(getattr(fastener, "drill_edge_depth", 0) or 0)
            dep = edge_d if edge_d > 0 else float(depth)
        return dia, float(dep)

    if f_dia_override is not None or e_dia_override is not None or e_dep_override is not None:
        if is_face:
            return float(f_dia_override if f_dia_override is not None else diameter), thickness
        return (
            float(e_dia_override if e_dia_override is not None else diameter),
            float(e_dep_override if e_dep_override is not None else depth),
        )

    # Legacy fallback (нет записи каталога)
    if abs(diameter - 7.0) < 0.6:  # конфирмат
        if is_face:
            return 7.0, thickness
        return 5.0, min(float(depth), 38.0)
    if abs(diameter - 8.0) < 0.6:  # шкант
        if is_face:
            return 8.0, min(max(1.0, thickness - 2.0), 12.0)
        return 8.0, 24.0
    if is_face:
        return float(diameter), thickness
    return float(diameter), float(depth)


def _place_hole_along_axis(panel, axis: str, lx, ly, lz, radius, actual_depth):
    """Ставит старт отверстия у ближайшей грани по оси сверления, клип поперёк."""
    if axis == "X":
        d = min(actual_depth, max(3.0, panel.width))
        if abs(lx - panel.width) <= abs(lx - 0.0):
            lx = max(0.0, panel.width - d)
        else:
            lx = 0.0
        ly = float(np.clip(ly, radius + 1.0, max(radius + 1.0, panel.height - radius - 1.0)))
        lz = float(np.clip(lz, radius + 1.0, max(radius + 1.0, panel.depth - radius - 1.0)))
    elif axis == "Y":
        d = min(actual_depth, max(3.0, panel.height))
        if abs(ly - panel.height) <= abs(ly - 0.0):
            ly = max(0.0, panel.height - d)
        else:
            ly = 0.0
        lx = float(np.clip(lx, radius + 1.0, max(radius + 1.0, panel.width - radius - 1.0)))
        lz = float(np.clip(lz, radius + 1.0, max(radius + 1.0, panel.depth - radius - 1.0)))
    else:
        d = min(actual_depth, max(3.0, panel.depth))
        if abs(lz - panel.depth) <= abs(lz - 0.0):
            lz = max(0.0, panel.depth - d)
        else:
            lz = 0.0
        lx = float(np.clip(lx, radius + 1.0, max(radius + 1.0, panel.width - radius - 1.0)))
        ly = float(np.clip(ly, radius + 1.0, max(radius + 1.0, panel.height - radius - 1.0)))
    return lx, ly, lz, d


def _avoid_grooves(panel, hole: tuple, max_passes: int = 3) -> tuple:
    """Сдвигает отверстие из паза. Работает по всем осям, с повторной проверкой.

    Возвращает скорректированный hole. Если безопасной позиции нет — исходный hole
    (вызывающий код может решить, принимать ли его).
    Сдвиг выполняется в мировых поперечных координатах внутри локальной СК панели.
    """
    if not hasattr(panel, "check_hole_groove_collision"):
        return hole
    if not panel.check_hole_groove_collision(hole):
        return hole

    lx, ly, lz, radius, depth, axis = hole[:6]
    grooves = list(getattr(panel, "grooves", []) or [])
    if not grooves:
        return hole

    for _ in range(max_passes):
        if not panel.check_hole_groove_collision((lx, ly, lz, radius, depth, axis)):
            break
        moved = False
        for g in grooves:
            gx, gy, gz, gw, gh, gd = g
            # AABB паза
            g_xmin, g_xmax = gx, gx + gw
            g_ymin, g_ymax = gy, gy + gh
            g_zmin, g_zmax = gz, gz + gd
            pad = float(radius) + 4.0

            # Сдвигаем поперёк оси сверления (вдоль осей, где паз имеет протяжённость)
            candidates = []
            # По X
            if lx + radius > g_xmin and lx - radius < g_xmax:
                candidates.append(("x", g_xmax + pad))
                candidates.append(("x", g_xmin - pad))
            # По Y
            if ly + radius > g_ymin and ly - radius < g_ymax:
                candidates.append(("y", g_ymax + pad))
                candidates.append(("y", g_ymin - pad))
            # По Z
            if lz + radius > g_zmin and lz - radius < g_zmax:
                candidates.append(("z", g_zmax + pad))
                candidates.append(("z", g_zmin - pad))

            for which, val in candidates:
                nlx, nly, nlz = lx, ly, lz
                if which == "x":
                    nlx = val
                elif which == "y":
                    nly = val
                else:
                    nlz = val
                # В пределах панели
                nlx = float(np.clip(nlx, radius + 1.0, max(radius + 1.0, panel.width - radius - 1.0)))
                nly = float(np.clip(nly, radius + 1.0, max(radius + 1.0, panel.height - radius - 1.0)))
                nlz = float(np.clip(nlz, radius + 1.0, max(radius + 1.0, panel.depth - radius - 1.0)))
                # Ось сверления не трогаем — старт уже на грани
                if axis == "X":
                    nlx = lx
                elif axis == "Y":
                    nly = ly
                else:
                    nlz = lz
                trial = (nlx, nly, nlz, radius, depth, axis)
                if not panel.check_hole_groove_collision(trial):
                    lx, ly, lz = nlx, nly, nlz
                    moved = True
                    break
            if moved:
                break
        if not moved:
            break

    return (lx, ly, lz, radius, depth, axis)


def make_joint_holes(
    joint: Joint,
    world_pt,
    diameter: float = 7.0,
    depth: float = 42.0,
    fastener=None,
    fastener_id: str | None = None,
    issues: list | None = None,
    *,
    face_diameter: float | None = None,
    edge_diameter: float | None = None,
    edge_depth: float | None = None,
):
    """
    Парные отверстия от плоскости стыка внутрь каждой панели.

    Правила сверления:
    - явные параметры конструктора (face_diameter / d1, edge_diameter / d2, edge_depth), если переданы;
    - объект Fastener из каталога (или fastener_id);
    - diameter/depth — fallback, если каталог недоступен.

    Важно: поперечный сдвиг (защита от паза) применяется к ОБЕИМ панелям
    одинаково в мировых координатах — иначе крепёж получается несоосным.

    Формат: (lx, ly, lz, radius, depth, axis) — как в CADKernel.
    """
    axis = joint.drill_axis
    drill_dir = getattr(joint, "drill_dir", None)
    pt = np.asarray(world_pt, dtype=float).copy()
    fst = resolve_fastener(fastener=fastener, fastener_id=fastener_id)

    def build_raw(panel, world):
        if hasattr(panel, "world_to_local") and getattr(panel, "has_rotation", lambda: False)():
            lx, ly, lz = panel.world_to_local(float(world[0]), float(world[1]), float(world[2]))
        else:
            lx = float(world[0] - panel.x)
            ly = float(world[1] - panel.y)
            lz = float(world[2] - panel.z)
        loc_axis = _panel_local_drill_axis(panel, drill_dir, axis)
        actual_dia, actual_depth = _hole_dims_for_fastener(
            panel,
            loc_axis,
            diameter,
            depth,
            fastener=fst,
            issues=issues,
            face_diameter=face_diameter,
            edge_diameter=edge_diameter,
            edge_depth=edge_depth,
        )
        radius = actual_dia / 2.0
        lx, ly, lz, d = _place_hole_along_axis(panel, loc_axis, lx, ly, lz, radius, actual_depth)
        return (lx, ly, lz, radius, d, loc_axis)

    pa, pb = joint.panel_a, joint.panel_b
    hole_a = build_raw(pa, pt)
    hole_b = build_raw(pb, pt)

    # Защита от паза: считаем желаемый мировой сдвиг поперечных координат
    # и применяем его к исходной world-точке, затем перестраиваем ОБЕ дырки.
    def transverse_world_delta(panel, hole_before, hole_after):
        """Дельта мировых координат, возникшая из сдвига локальных (кроме оси сверления)."""
        dx = (hole_after[0] - hole_before[0])
        dy = (hole_after[1] - hole_before[1])
        dz = (hole_after[2] - hole_before[2])
        loc_axis = hole_before[5] if len(hole_before) > 5 else axis
        # Ось сверления — локальный старт на грани, его не переносим в world-точку стыка
        if loc_axis == "X":
            dx = 0.0
        elif loc_axis == "Y":
            dy = 0.0
        else:
            dz = 0.0
        if hasattr(panel, "rotate_vector") and getattr(panel, "has_rotation", lambda: False)():
            wx, wy, wz = panel.rotate_vector(dx, dy, dz)
            return np.array([wx, wy, wz], dtype=float)
        return np.array([dx, dy, dz], dtype=float)

    shifted_pt = pt.copy()
    for panel, hole in ((pa, hole_a), (pb, hole_b)):
        avoided = _avoid_grooves(panel, hole)
        delta = transverse_world_delta(panel, hole, avoided)
        if np.linalg.norm(delta) > 1e-9:
            shifted_pt = shifted_pt + delta

    if np.linalg.norm(shifted_pt - pt) > 1e-9:
        # Перестраиваем оба отверстия из общей сдвинутой world-точки
        hole_a = build_raw(pa, shifted_pt)
        hole_b = build_raw(pb, shifted_pt)
        # Финальная проверка: если всё ещё конфликт — локальный avoid без ломки соосности
        # (сдвигаем оба одинаково ещё раз, если нужно)
        for _ in range(2):
            da = _avoid_grooves(pa, hole_a)
            db = _avoid_grooves(pb, hole_b)
            delta = transverse_world_delta(pa, hole_a, da) + transverse_world_delta(pb, hole_b, db)
            if np.linalg.norm(delta) < 1e-9:
                hole_a, hole_b = da, db
                break
            shifted_pt = shifted_pt + 0.5 * delta
            hole_a = build_raw(pa, shifted_pt)
            hole_b = build_raw(pb, shifted_pt)
        else:
            hole_a = _avoid_grooves(pa, hole_a)
            hole_b = _avoid_grooves(pb, hole_b)
    else:
        hole_a = _avoid_grooves(pa, hole_a)
        hole_b = _avoid_grooves(pb, hole_b)
        if not (getattr(pa, "has_rotation", lambda: False)() or getattr(pb, "has_rotation", lambda: False)()):
            # Если avoid сдвинул только одну — выровнять вторую по world
            wa = np.array([pa.x + hole_a[0], pa.y + hole_a[1], pa.z + hole_a[2]])
            wb = np.array([pb.x + hole_b[0], pb.y + hole_b[1], pb.z + hole_b[2]])
            # Поперечные координаты должны совпасть
            if axis == "X":
                mid_y, mid_z = 0.5 * (wa[1] + wb[1]), 0.5 * (wa[2] + wb[2])
                hole_a = (hole_a[0], mid_y - pa.y, mid_z - pa.z, hole_a[3], hole_a[4], hole_a[5])
                hole_b = (hole_b[0], mid_y - pb.y, mid_z - pb.z, hole_b[3], hole_b[4], hole_b[5])
            elif axis == "Y":
                mid_x, mid_z = 0.5 * (wa[0] + wb[0]), 0.5 * (wa[2] + wb[2])
                hole_a = (mid_x - pa.x, hole_a[1], mid_z - pa.z, hole_a[3], hole_a[4], hole_a[5])
                hole_b = (mid_x - pb.x, hole_b[1], mid_z - pb.z, hole_b[3], hole_b[4], hole_b[5])
            else:
                mid_x, mid_y = 0.5 * (wa[0] + wb[0]), 0.5 * (wa[1] + wb[1])
                hole_a = (mid_x - pa.x, mid_y - pa.y, hole_a[2], hole_a[3], hole_a[4], hole_a[5])
                hole_b = (mid_x - pb.x, mid_y - pb.y, hole_b[2], hole_b[3], hole_b[4], hole_b[5])

    return hole_a, hole_b


# ── Параметрические стыки (ревизия 2, п. 3.1) ─────────────────


@dataclass
class JointRecord:
    """Параметрическая запись стыка двух панелей внутри блока (ревизия 2, п. 3.1).

    Поля:
    - `uid`: уникальный идентификатор записи стыка;
    - `panel_a_uid`: uid первой панели стыка;
    - `panel_b_uid`: uid второй панели стыка;
    - `preset_id`: идентификатор пресета раскладки (например, `"confirmat_3"`, `"confirmat_128"`, `"dowel_96"`, `"confirmat_2"`);
    - `fastener_id`: канонический id крепежа из каталога (`"fst_conf_7x50"`, `"fst_dowel_8x30"`, …);
    - `params`: словарь параметров раскладки (`count`, `margin`, `pitch`, `diameter`, `depth`, `center_ratio`).
    """

    uid: str = ""
    panel_a_uid: str = ""
    panel_b_uid: str = ""
    preset_id: str = "confirmat_3"
    fastener_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.uid = str(self.uid or "").strip() or str(uuid4())
        self.panel_a_uid = str(self.panel_a_uid or "").strip()
        self.panel_b_uid = str(self.panel_b_uid or "").strip()
        self.preset_id = str(self.preset_id or "confirmat_3").strip() or "confirmat_3"

        raw_params = dict(self.params) if isinstance(self.params, dict) else {}
        preset = get_fastener_preset(self.preset_id) or FASTENER_PRESETS.get(self.preset_id, {})

        if not self.fastener_id:
            self.fastener_id = str(
                raw_params.get("fastener_id")
                or preset.get("fastener_id")
                or "fst_conf_7x50"
            )
        else:
            self.fastener_id = str(self.fastener_id).strip()

        if "margin" not in raw_params or raw_params["margin"] is None:
            raw_params["margin"] = float(
                preset.get("margin") if preset.get("margin") is not None else 50.0
            )
        else:
            raw_params["margin"] = float(raw_params["margin"])

        if "pitch" not in raw_params:
            p_val = preset.get("pitch")
            raw_params["pitch"] = float(p_val) if p_val is not None else None
        elif raw_params["pitch"] is not None:
            p_f = float(raw_params["pitch"])
            raw_params["pitch"] = p_f if p_f > 1e-6 else None

        if "count" not in raw_params:
            c_val = preset.get("count")
            raw_params["count"] = int(c_val) if c_val is not None else None
        elif raw_params["count"] is not None:
            c_i = int(raw_params["count"])
            raw_params["count"] = c_i if c_i > 0 else None

        if "d1" in raw_params and raw_params["d1"] is not None:
            raw_params["d1"] = float(raw_params["d1"])
            raw_params.setdefault("drill_face_diameter", raw_params["d1"])
        if "d2" in raw_params and raw_params["d2"] is not None:
            raw_params["d2"] = float(raw_params["d2"])
            raw_params.setdefault("drill_edge_diameter", raw_params["d2"])
        if "drill_face_diameter" in raw_params and raw_params["drill_face_diameter"] is not None:
            raw_params["drill_face_diameter"] = float(raw_params["drill_face_diameter"])
        if "drill_edge_diameter" in raw_params and raw_params["drill_edge_diameter"] is not None:
            raw_params["drill_edge_diameter"] = float(raw_params["drill_edge_diameter"])
        if "drill_edge_depth" in raw_params and raw_params["drill_edge_depth"] is not None:
            raw_params["drill_edge_depth"] = float(raw_params["drill_edge_depth"])
        if "h" in raw_params and raw_params["h"] is not None:
            raw_params["h"] = float(raw_params["h"])
        if "h1" in raw_params and raw_params["h1"] is not None:
            raw_params["h1"] = float(raw_params["h1"])

        if "diameter" not in raw_params or raw_params["diameter"] is None:
            raw_params["diameter"] = float(
                raw_params.get("drill_face_diameter")
                or raw_params.get("d1")
                or preset.get("diameter")
                or 7.0
            )
        else:
            raw_params["diameter"] = float(raw_params["diameter"])

        if "depth" not in raw_params or raw_params["depth"] is None:
            raw_params["depth"] = float(
                raw_params.get("drill_edge_depth")
                or preset.get("depth")
                or 42.0
            )
        else:
            raw_params["depth"] = float(raw_params["depth"])

        if "center_ratio" in raw_params and raw_params["center_ratio"] is not None:
            raw_params["center_ratio"] = float(raw_params["center_ratio"])

        if "center_offset" in raw_params and raw_params["center_offset"] is not None:
            raw_params["center_offset"] = float(raw_params["center_offset"])

        self.params = raw_params

    @property
    def margin(self) -> float:
        return float(self.params.get("margin") if self.params.get("margin") is not None else 50.0)

    @margin.setter
    def margin(self, value: float) -> None:
        self.params["margin"] = float(value)

    @property
    def pitch(self) -> float | None:
        val = self.params.get("pitch")
        return float(val) if (val is not None and float(val) > 1e-6) else None

    @pitch.setter
    def pitch(self, value: float | None) -> None:
        self.params["pitch"] = float(value) if (value is not None and float(value) > 1e-6) else None

    @property
    def count(self) -> int | None:
        val = self.params.get("count")
        return int(val) if (val is not None and int(val) > 0) else None

    @count.setter
    def count(self, value: int | None) -> None:
        self.params["count"] = int(value) if (value is not None and int(value) > 0) else None

    @property
    def diameter(self) -> float:
        return float(self.params.get("diameter") or 7.0)

    @diameter.setter
    def diameter(self, value: float) -> None:
        self.params["diameter"] = float(value)

    @property
    def depth(self) -> float:
        return float(self.params.get("depth") or 42.0)

    @depth.setter
    def depth(self, value: float) -> None:
        self.params["depth"] = float(value)

    def apply_preset(self, preset_id: str) -> bool:
        """Обновляет пресет, `fastener_id` и параметры раскладки из справочника `FASTENER_PRESETS`."""
        preset = get_fastener_preset(preset_id) or FASTENER_PRESETS.get(preset_id, {})
        if not preset:
            return False
        self.preset_id = str(preset_id)
        if preset.get("fastener_id"):
            self.fastener_id = str(preset["fastener_id"])
        self.params["margin"] = float(preset.get("margin") if preset.get("margin") is not None else 50.0)
        p_val = preset.get("pitch")
        self.params["pitch"] = float(p_val) if p_val is not None else None
        c_val = preset.get("count")
        self.params["count"] = int(c_val) if c_val is not None else None
        self.params["diameter"] = float(preset.get("diameter") or self.diameter)
        self.params["depth"] = float(preset.get("depth") or self.depth)
        return True

    def snapshot_state(self) -> dict[str, Any]:
        """Возвращает полный словарь состояния записи для команд Undo/Redo."""
        return {
            "preset_id": str(self.preset_id),
            "fastener_id": str(self.fastener_id),
            "params": dict(self.params),
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Восстанавливает состояние записи из снимка."""
        if "preset_id" in state:
            self.preset_id = str(state["preset_id"])
        if "fastener_id" in state:
            self.fastener_id = str(state["fastener_id"])
        if isinstance(state.get("params"), dict):
            self.params = dict(state["params"])

    def clone(self, *, new_id: bool = True) -> "JointRecord":
        return JointRecord(
            uid="" if new_id else self.uid,
            panel_a_uid=self.panel_a_uid,
            panel_b_uid=self.panel_b_uid,
            preset_id=self.preset_id,
            fastener_id=self.fastener_id,
            params=dict(self.params),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": str(self.uid),
            "panel_a_uid": str(self.panel_a_uid),
            "panel_b_uid": str(self.panel_b_uid),
            "preset_id": str(self.preset_id),
            "fastener_id": str(self.fastener_id),
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JointRecord":
        if isinstance(data, cls):
            return data.clone(new_id=False)
        return cls(
            uid=str(data.get("uid") or ""),
            panel_a_uid=str(data.get("panel_a_uid") or ""),
            panel_b_uid=str(data.get("panel_b_uid") or ""),
            preset_id=str(data.get("preset_id") or "confirmat_3"),
            fastener_id=str(data.get("fastener_id") or ""),
            params=dict(data.get("params") or {}) if isinstance(data.get("params"), dict) else {},
        )


def holes_equal(a: tuple, b: tuple, tol: float = 1e-4) -> bool:
    """Сравнивает два кортежа отверстий `(lx, ly, lz, radius, depth, axis)` с допуском `tol`."""
    if len(a) < 6 or len(b) < 6:
        return False
    if str(a[5]).upper() != str(b[5]).upper():
        return False
    return all(abs(float(a[i]) - float(b[i])) <= tol for i in range(5))


def _contains_hole(holes_list: list[tuple], target: tuple, tol: float = 1e-4) -> bool:
    return any(holes_equal(h, target, tol=tol) for h in holes_list)


def hole_geometry(hole) -> tuple:
    """Первые 6 полей отверстия (lx, ly, lz, radius, depth, axis)."""
    h = tuple(hole)
    if len(h) < 6:
        raise ValueError("hole must have at least 6 fields")
    return (float(h[0]), float(h[1]), float(h[2]), float(h[3]), float(h[4]), str(h[5]))


def hole_joint_uid(hole) -> str:
    """Метка стыка (7-й элемент), если есть; иначе пустая строка.

    Метки ассоциативных ссылок (`a:<uid>`) не считаются joint-метками.
    """
    if hole is None or len(hole) < 7:
        return ""
    raw = str(hole[6] or "").strip()
    if not raw or raw.startswith("a:"):
        return ""
    return raw


def tag_joint_hole(hole, joint_uid: str) -> tuple:
    """Возвращает отверстие с меткой joint_uid (геометрия без изменений)."""
    g = hole_geometry(hole)
    uid = str(joint_uid or "").strip()
    if not uid:
        return g
    # Не допускаем путаницу с assoc-префиксом
    if uid.startswith("a:"):
        uid = uid[2:]
    return g + (uid,)


def extract_manual_holes(panel) -> list[tuple]:
    """Возвращает отверстия, поставленные вручную (не JointRecord и не AssocRef).

    Приоритет: 7-й элемент owner-метки (формат ≥0.0.8).
    Fallback: совпадение координат с ``panel.joint_hole_map`` (legacy ≤0.0.7).
    """
    raw_holes = list(getattr(panel, "holes", []) or [])
    jmap = getattr(panel, "joint_hole_map", None) or {}

    remaining_joint_holes: list[tuple] = []
    for hlist in jmap.values():
        for jh in hlist or []:
            if len(jh) >= 6:
                remaining_joint_holes.append(hole_geometry(jh))

    manual: list[tuple] = []
    for h in raw_holes:
        if len(h) < 6:
            continue
        # Явная метка стыка — не ручное
        if hole_joint_uid(h):
            continue
        # Метка ассоциативной ссылки (a:<uid>) — не ручное
        raw_tag = str(h[6] or "").strip() if len(h) >= 7 else ""
        if raw_tag.startswith("a:"):
            continue
        h6 = hole_geometry(h)
        matched_idx = None
        for idx, jh in enumerate(remaining_joint_holes):
            if holes_equal(h6, jh):
                matched_idx = idx
                break
        if matched_idx is not None:
            remaining_joint_holes.pop(matched_idx)
        else:
            # Сохраняем полный кортеж (без метки) как ручное
            manual.append(h6)
    return manual


def compute_joint_record_points(joint: Joint, record: JointRecord) -> list[np.ndarray]:
    """Вычисляет мировые точки сверления на стыке `joint` по параметрам `record`."""
    preset = get_fastener_preset(record.preset_id) if record.preset_id else {}
    params = record.params if isinstance(record.params, dict) else {}

    diameter = float(params.get("diameter") or preset.get("diameter") or 7.0)
    margin = (
        float(params["margin"])
        if params.get("margin") is not None
        else float(preset.get("margin") if preset.get("margin") is not None else 50.0)
    )
    pitch_val = params.get("pitch") if "pitch" in params else preset.get("pitch")
    pitch = float(pitch_val) if (pitch_val is not None and float(pitch_val) > 1e-6) else None

    count_val = params.get("count") if "count" in params else preset.get("count")
    count = int(count_val) if (count_val is not None and int(count_val) > 0) else None

    center_t: float | None = None
    if params.get("center_ratio") is not None:
        ratio = min(max(float(params["center_ratio"]), 0.0), 1.0)
        center_t = float(joint.t_min) + ratio * float(joint.t_max - joint.t_min)
    elif params.get("center_t") is not None:
        center_t = float(params["center_t"])
    elif params.get("center_offset") is not None:
        mid_t = 0.5 * (float(joint.t_min) + float(joint.t_max))
        center_t = mid_t + float(params["center_offset"])

    return joint_array_points(
        joint,
        count=count,
        margin=margin,
        diameter=diameter,
        center_t=center_t,
        pitch=pitch,
    )


def apply_joints(block, *, rebuild_geometry: bool = True) -> list:
    """Пересчитывает присадку из записей `block.joints` после любого изменения габаритов или `rebuild()` (п. 3.1).

    - Отверстия, поставленные вручную (без записи `JointRecord`), сохраняются без изменений.
    - При удалении записи из `block.joints` её отверстия автоматически снимаются с обеих деталей.
    - Возвращает список замечаний `Issue`, возникших при проверке правил крепежа.
    """
    if block is None:
        return []

    panels = list(getattr(block, "panels", []) or [])
    raw_joints = list(getattr(block, "joints", []) or [])
    norm_joints: list[JointRecord] = []
    for item in raw_joints:
        if isinstance(item, JointRecord):
            norm_joints.append(item)
        elif isinstance(item, dict):
            norm_joints.append(JointRecord.from_dict(item))
    block.joints = norm_joints

    old_holes_by_id: dict[int, list[tuple]] = {}
    for p in panels:
        try:
            p._block = block
        except Exception as exc:  # noqa: BLE001 — optional back-ref
            _log.debug("Could not bind _block on panel: %s", exc)
        old_holes_by_id[id(p)] = [hole_geometry(h) for h in (getattr(p, "holes", []) or []) if len(h) >= 6]
        manual = extract_manual_holes(p)
        # Сохраняем ассоциативные отверстия (a:<uid>) — ими управляет apply_assoc_refs
        assoc_kept: list[tuple] = []
        for h in list(getattr(p, "holes", []) or []):
            if len(h) >= 7 and str(h[6] or "").startswith("a:"):
                assoc_kept.append(tuple(h))
        p.holes = list(manual) + assoc_kept
        p.joint_hole_map = {}
        if hasattr(p, "fastener_issues"):
            p.fastener_issues = []

    by_uid = {
        str(getattr(p, "uid", "") or ""): p
        for p in panels
        if str(getattr(p, "uid", "") or "")
    }

    all_issues: list = []
    for jr in norm_joints:
        pa = by_uid.get(jr.panel_a_uid)
        pb = by_uid.get(jr.panel_b_uid)
        if pa is None or pb is None or pa is pb:
            continue

        joint = find_joint(pa, pb)
        if joint is None:
            joint = find_joint(pa, pb, tol=3.0)
        if joint is None:
            continue

        preset = get_fastener_preset(jr.preset_id) if jr.preset_id else {}
        params = jr.params if isinstance(jr.params, dict) else {}
        fastener_id = str(jr.fastener_id or preset.get("fastener_id") or "")
        diameter = float(params.get("diameter") or preset.get("diameter") or 7.0)
        depth = float(params.get("depth") or preset.get("depth") or 42.0)
        raw_face_dia = (
            params.get("drill_face_diameter")
            if params.get("drill_face_diameter") is not None
            else params.get("d1")
        )
        raw_edge_dia = (
            params.get("drill_edge_diameter")
            if params.get("drill_edge_diameter") is not None
            else params.get("d2")
        )
        raw_edge_dep = params.get("drill_edge_depth")
        face_dia = float(raw_face_dia) if (raw_face_dia is not None and float(raw_face_dia) > 0) else None
        edge_dia = float(raw_edge_dia) if (raw_edge_dia is not None and float(raw_edge_dia) > 0) else None
        edge_dep = float(raw_edge_dep) if (raw_edge_dep is not None and float(raw_edge_dep) > 0) else None

        pts = compute_joint_record_points(joint, jr)
        holes_a_for_jr: list[tuple] = []
        holes_b_for_jr: list[tuple] = []
        for pt in pts:
            ha, hb = make_joint_holes(
                joint,
                pt,
                diameter=diameter,
                depth=depth,
                fastener_id=fastener_id or None,
                issues=all_issues,
                face_diameter=face_dia,
                edge_diameter=edge_dia,
                edge_depth=edge_dep,
            )
            ha_t = tag_joint_hole(ha, jr.uid)
            hb_t = tag_joint_hole(hb, jr.uid)
            holes_a_for_jr.append(ha_t)
            holes_b_for_jr.append(hb_t)
            if not _contains_hole(pa.holes, ha_t):
                pa.holes.append(ha_t)
            if not _contains_hole(pb.holes, hb_t):
                pb.holes.append(hb_t)

        pa.joint_hole_map.setdefault(jr.uid, []).extend(holes_a_for_jr)
        pb.joint_hole_map.setdefault(jr.uid, []).extend(holes_b_for_jr)

    if rebuild_geometry:
        for p in panels:
            cur_holes = [hole_geometry(h) for h in (getattr(p, "holes", []) or []) if len(h) >= 6]
            old_holes = old_holes_by_id.get(id(p), [])
            if len(cur_holes) != len(old_holes) or any(
                not holes_equal(a, b) for a, b in zip(cur_holes, old_holes)
            ):
                p._gl_arrays = None
                if hasattr(p, "rebuild_geometry"):
                    p.rebuild_geometry()

    # Ассоциативные отверстия пересчитываются после стыков (общая точка входа после rebuild).
    if getattr(block, "assoc_refs", None):
        try:
            from core.assoc import apply_assoc_refs

            apply_assoc_refs(block, rebuild_geometry=rebuild_geometry)
        except Exception as exc:  # noqa: BLE001 — не ломаем стыки из‑за assoc
            _log.exception("apply_assoc_refs after joints failed: %s", exc)

    return all_issues

