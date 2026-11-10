"""Единый реестр замечаний и проблем модели (ревизия 2, п. 1.8, 2.2 и 3.8)."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from core.logging_setup import get_logger

_log = get_logger("issues")


# Минимальный технологический отступ от края отверстия (стенки цилиндра) до кромки детали, мм
DEFAULT_MIN_HOLE_EDGE_DISTANCE = 4.0

# Стандартный размер листа ЛДСП для проверки негабаритных деталей, мм
DEFAULT_MAX_SHEET_LENGTH = 2800.0
DEFAULT_MAX_SHEET_WIDTH = 2070.0


@dataclass
class Issue:
    """Замечание проверки модели / технологичности."""

    severity: str  # "warning" | "error"
    panel_uid: str
    code: str
    message: str

    def format_line(self) -> str:
        prefix = "❌" if self.severity == "error" else "⚠️"
        return f"{prefix} {self.message}"


def _panel_thickness_mm(panel) -> float:
    if hasattr(panel, "get_thickness") and callable(panel.get_thickness):
        return float(panel.get_thickness())
    if getattr(panel, "thickness_axis", None) is not None:
        dims = (float(panel.width), float(panel.height), float(panel.depth))
        ta = panel.thickness_axis
        if isinstance(ta, str) and ta.upper() in ("X", "Y", "Z"):
            return dims[("X", "Y", "Z").index(ta.upper())]
        return dims[int(ta) % 3]
    return float(min(panel.width, panel.height, panel.depth))


def _panel_thickness_axis_name(panel) -> str:
    dims = {"X": float(panel.width), "Y": float(panel.height), "Z": float(panel.depth)}
    ta = getattr(panel, "thickness_axis", None)
    if ta is not None:
        if isinstance(ta, str) and ta.upper() in ("X", "Y", "Z"):
            return ta.upper()
        try:
            return ("X", "Y", "Z")[int(ta) % 3]
        except (TypeError, ValueError):
            _log.debug("Invalid thickness_axis=%r on panel, falling back to min dim", ta)
    return min(dims, key=dims.get)


def _active_catalog():
    """Возвращает активный экземпляр CatalogService, если он уже инициализирован."""
    try:
        from core.catalog import CatalogService

        if getattr(CatalogService, "_instance", None) is not None:
            return CatalogService.instance()
    except Exception:
        _log.exception("Failed to acquire active CatalogService in issues check")
    return None


def check_fastener_thickness_issue(panel, fastener) -> Issue | None:
    """Проверяет совместимость толщины панели с min/max_panel_thickness крепежа (п. 1.8)."""
    if fastener is None or panel is None:
        return None
    thickness = _panel_thickness_mm(panel)
    tmin = float(getattr(fastener, "min_panel_thickness", 0) or 0)
    tmax = float(getattr(fastener, "max_panel_thickness", 0) or 0)
    pname = str(getattr(panel, "name", "") or "Панель")
    puid = str(getattr(panel, "uid", "") or "")
    fname = str(
        getattr(fastener, "display_name", "")
        or getattr(fastener, "name", "")
        or getattr(fastener, "id", "крепёж")
    )

    if tmin > 0 and thickness + 1e-6 < tmin:
        return Issue(
            severity="warning",
            panel_uid=puid,
            code="fastener_thickness_min",
            message=(
                f"Несовместимая толщина: деталь «{pname}» ({thickness:g} мм) "
                f"тоньше допустимого минимума {tmin:g} мм для крепежа «{fname}»"
            ),
        )
    if tmax > 0 and thickness - 1e-6 > tmax:
        return Issue(
            severity="warning",
            panel_uid=puid,
            code="fastener_thickness_max",
            message=(
                f"Несовместимая толщина: деталь «{pname}» ({thickness:g} мм) "
                f"толще допустимого максимума {tmax:g} мм для крепежа «{fname}»"
            ),
        )
    return None


def record_panel_issue(panel, issue: Issue) -> None:
    """Сохраняет замечание на объекте панели без дубликатов (сбрасывается при очистке отверстий)."""
    if panel is None or issue is None:
        return
    existing: list[Issue] = list(getattr(panel, "fastener_issues", []) or [])
    for it in existing:
        if it.code == issue.code and it.message == issue.message:
            return
    existing.append(issue)
    panel.fastener_issues = existing


def _iter_panels(blocks):
    for b in blocks or []:
        for p in getattr(b, "panels", []) or []:
            yield p


def check_fastener_issues_in_blocks(blocks) -> list[Issue]:
    """Собирает замечания по несовместимости крепежа с толщиной детали (п. 1.8 и 2.2)."""
    out: list[Issue] = []
    for p in _iter_panels(blocks):
        f_issues = getattr(p, "fastener_issues", None) or []
        if not f_issues:
            continue
        puid = str(getattr(p, "uid", "") or "")
        for iss in f_issues:
            out.append(
                Issue(
                    severity=iss.severity,
                    panel_uid=puid or iss.panel_uid,
                    code=iss.code,
                    message=iss.message,
                )
            )
    return out


def check_missing_materials_in_blocks(blocks) -> list[Issue]:
    """Проверяет отсутствующие в каталоге материалы и детали без материала (п. 2.2, 3.8)."""
    from models.panel import DEFAULT_MATERIAL_ID

    out: list[Issue] = []
    cat = _active_catalog()
    for p in _iter_panels(blocks):
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        mid = str(getattr(p, "missing_material_id", "") or "").strip()
        if mid:
            out.append(
                Issue(
                    severity="warning",
                    panel_uid=puid,
                    code="missing_material",
                    message=f"Деталь «{pname}»: материал «{mid}» не найден в каталоге",
                )
            )
            continue

        cur_mid = str(getattr(p, "material_id", "") or "").strip()
        cur_mname = str(getattr(p, "material", "") or "").strip()
        if not cur_mid and not cur_mname:
            out.append(
                Issue(
                    severity="warning",
                    panel_uid=puid,
                    code="no_material",
                    message=f"Деталь «{pname}»: не назначен материал",
                )
            )
        elif cat is not None and cur_mid and cur_mid != DEFAULT_MATERIAL_ID:
            try:
                if cat.get_material(cur_mid) is None:
                    out.append(
                        Issue(
                            severity="warning",
                            panel_uid=puid,
                            code="missing_material",
                            message=f"Деталь «{pname}»: материал «{cur_mid}» не найден в каталоге",
                        )
                    )
            except Exception:
                _log.exception("Failed to check material %s in catalog", cur_mid)
    return out


def check_missing_edges_in_blocks(blocks) -> list[Issue]:
    """Проверяет отсутствующие в каталоге кромки (п. 2.2)."""
    out: list[Issue] = []
    cat = _active_catalog()
    for p in _iter_panels(blocks):
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        reported_sides: set[str] = set()

        missing = getattr(p, "missing_edges", None) or {}
        if isinstance(missing, dict):
            for side, eid in missing.items():
                if eid:
                    reported_sides.add(str(side))
                    out.append(
                        Issue(
                            severity="warning",
                            panel_uid=puid,
                            code="missing_edge",
                            message=f"Деталь «{pname}» ({side}): кромка «{eid}» не найдена в каталоге",
                        )
                    )

        if cat is not None:
            edges = getattr(p, "edges", None) or {}
            if isinstance(edges, dict):
                for side, eid in edges.items():
                    eid_str = str(eid or "").strip()
                    if not eid_str or str(side) in reported_sides:
                        continue
                    try:
                        if cat.get_edge(eid_str) is None:
                            out.append(
                                Issue(
                                    severity="warning",
                                    panel_uid=puid,
                                    code="missing_edge",
                                    message=f"Деталь «{pname}» ({side}): кромка «{eid_str}» не найдена в каталоге",
                                )
                            )
                    except Exception:
                        _log.exception("Failed to check edge %s in catalog", eid_str)
    return out


def check_edge_width_in_blocks(blocks) -> list[Issue]:
    """Проверяет, что ширина кромки не меньше толщины детали (п. 2.2, 3.8)."""
    out: list[Issue] = []
    cat = _active_catalog()
    if cat is None:
        return out

    for p in _iter_panels(blocks):
        edges = getattr(p, "edges", None) or {}
        if not isinstance(edges, dict):
            continue
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        thickness = _panel_thickness_mm(p)
        for side, eid in edges.items():
            eid_str = str(eid or "").strip()
            if not eid_str:
                continue
            try:
                eb = cat.get_edge(eid_str)
            except Exception:
                _log.exception("Failed to load edge %s for width check", eid_str)
                eb = None
            if eb is None:
                continue
            w_mm = float(getattr(eb, "width_mm", 0.0) or 0.0)
            if w_mm > 0 and w_mm + 1e-6 < thickness:
                ename = getattr(eb, "display_name", None) or getattr(eb, "name", eid_str)
                out.append(
                    Issue(
                        severity="warning",
                        panel_uid=puid,
                        code="edge_width_too_small",
                        message=(
                            f"Деталь «{pname}» ({side}): ширина кромки «{ename}» "
                            f"({w_mm:g} мм) меньше толщины детали ({thickness:g} мм)"
                        ),
                    )
                )
    return out


def check_hole_edge_distance_in_blocks(
    blocks,
    min_edge_distance: float = DEFAULT_MIN_HOLE_EDGE_DISTANCE,
) -> list[Issue]:
    """Проверяет отверстия, расположенные ближе N мм к краю детали (п. 2.2, 3.8)."""
    out: list[Issue] = []
    min_dist = float(min_edge_distance)
    for p in _iter_panels(blocks):
        holes = getattr(p, "holes", None) or []
        if not holes:
            continue
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        dims = {
            "X": float(getattr(p, "width", 0.0)),
            "Y": float(getattr(p, "height", 0.0)),
            "Z": float(getattr(p, "depth", 0.0)),
        }
        ta_axis = _panel_thickness_axis_name(p)

        for idx, h in enumerate(holes, start=1):
            if len(h) < 6:
                continue
            hx, hy, hz, radius, _depth, raw_axis = h[:6]
            axis = str(raw_axis or "X").upper()
            if axis not in ("X", "Y", "Z"):
                axis = "X"
            r = max(0.0, float(radius))
            coords = {"X": float(hx), "Y": float(hy), "Z": float(hz)}
            perp_axes = [a for a in ("X", "Y", "Z") if a != axis]

            for a in perp_axes:
                c = coords[a]
                span = dims[a]
                wall_dist = min(c - r, span - (c + r))
                # При сверлении в торец (ось a == ось толщины) допустима стандартная стенка >= 1.0 мм,
                # а вдоль габаритных краёв детали проверяем отступ min_dist (по умолчанию 4.0 мм).
                threshold = 1.0 if a == ta_axis else min_dist
                if wall_dist + 1e-6 < threshold:
                    out.append(
                        Issue(
                            severity="warning",
                            panel_uid=puid,
                            code="hole_near_edge",
                            message=(
                                f"Деталь «{pname}»: отверстие #{idx} слишком близко к краю "
                                f"(остаток {wall_dist:.1f} мм < {threshold:g} мм)"
                            ),
                        )
                    )
                    break
    return out


def check_holes_in_grooves_in_blocks(blocks) -> list[Issue]:
    """Проверяет попадание отверстий присадки в пазы детали (п. 2.2, 3.8)."""
    out: list[Issue] = []
    for p in _iter_panels(blocks):
        if not getattr(p, "grooves", None) or not getattr(p, "holes", None):
            continue
        if not hasattr(p, "check_hole_groove_collision"):
            continue
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        for idx, h in enumerate(p.holes, start=1):
            if p.check_hole_groove_collision(h):
                out.append(
                    Issue(
                        severity="warning",
                        panel_uid=puid,
                        code="hole_in_groove",
                        message=f"Деталь «{pname}»: отверстие #{idx} пересекает паз",
                    )
                )
    return out


def _hole_segment_and_aabb(hole: tuple):
    hx, hy, hz, radius, length, raw_axis = hole[:6]
    hx, hy, hz = float(hx), float(hy), float(hz)
    r = max(0.0, float(radius))
    length = max(0.0, float(length))
    axis = str(raw_axis or "X").upper()
    if axis == "X":
        p0 = (hx, hy, hz)
        p1 = (hx + length, hy, hz)
        mn = (hx, hy - r, hz - r)
        mx = (hx + length, hy + r, hz + r)
    elif axis == "Y":
        p0 = (hx, hy, hz)
        p1 = (hx, hy + length, hz)
        mn = (hx - r, hy, hz - r)
        mx = (hx + r, hy + length, hz + r)
    else:
        p0 = (hx, hy, hz)
        p1 = (hx, hy, hz + length)
        mn = (hx - r, hy - r, hz)
        mx = (hx + r, hy + r, hz + length)
    return p0, p1, r, mn, mx


def _segments_distance_3d(p0, p1, q0, q1) -> float:
    """Кратчайшее расстояние между двумя 3D-отрезками [p0, p1] и [q0, q1]."""
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    vx, vy, vz = q1[0] - q0[0], q1[1] - q0[1], q1[2] - q0[2]
    wx, wy, wz = p0[0] - q0[0], p0[1] - q0[1], p0[2] - q0[2]

    a = ux * ux + uy * uy + uz * uz
    b = ux * vx + uy * vy + uz * vz
    c = vx * vx + vy * vy + vz * vz
    d = ux * wx + uy * wy + uz * wz
    e = vx * wx + vy * wy + vz * wz
    denom = a * c - b * b

    s_n, s_d = denom, denom
    t_n, t_d = denom, denom

    if denom < 1e-12:
        s_n = 0.0
        s_d = 1.0
        t_n = e
        t_d = c
    else:
        s_n = b * e - c * d
        t_n = a * e - b * d
        if s_n < 0.0:
            s_n = 0.0
            t_n = e
            t_d = c
        elif s_n > s_d:
            s_n = s_d
            t_n = e + b
            t_d = c

    if t_n < 0.0:
        t_n = 0.0
        if -d < 0.0:
            s_n = 0.0
        elif -d > a:
            s_n = s_d
        else:
            s_n = -d
            s_d = a
    elif t_n > t_d:
        t_n = t_d
        if (-d + b) < 0.0:
            s_n = 0.0
        elif (-d + b) > a:
            s_n = s_d
        else:
            s_n = -d + b
            s_d = a

    sc = 0.0 if abs(s_n) < 1e-12 else s_n / s_d
    tc = 0.0 if abs(t_n) < 1e-12 else t_n / t_d

    dx = wx + sc * ux - tc * vx
    dy = wy + sc * uy - tc * vy
    dz = wz + sc * uz - tc * vz
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def check_holes_intersection_in_blocks(blocks) -> list[Issue]:
    """Проверяет пересечение отверстий между собой внутри одной детали (п. 2.2, 3.8)."""
    out: list[Issue] = []
    for p in _iter_panels(blocks):
        holes = getattr(p, "holes", None) or []
        if len(holes) < 2:
            continue
        pname = str(getattr(p, "name", "") or "Панель")
        puid = str(getattr(p, "uid", "") or "")
        geom = [_hole_segment_and_aabb(h) for h in holes if len(h) >= 6]
        n = len(geom)
        for i in range(n):
            p0, p1, r1, mn1, mx1 = geom[i]
            for j in range(i + 1, n):
                q0, q1, r2, mn2, mx2 = geom[j]
                if not (
                    mn1[0] < mx2[0] - 1e-6 and mx1[0] > mn2[0] + 1e-6 and
                    mn1[1] < mx2[1] - 1e-6 and mx1[1] > mn2[1] + 1e-6 and
                    mn1[2] < mx2[2] - 1e-6 and mx1[2] > mn2[2] + 1e-6
                ):
                    continue
                dist = _segments_distance_3d(p0, p1, q0, q1)
                if dist + 1e-4 < (r1 + r2):
                    out.append(
                        Issue(
                            severity="warning",
                            panel_uid=puid,
                            code="holes_intersect",
                            message=f"Деталь «{pname}»: отверстия #{i + 1} и #{j + 1} пересекаются",
                        )
                    )
    return out


def check_oversized_panels_in_blocks(
    blocks,
    max_length: float = DEFAULT_MAX_SHEET_LENGTH,
    max_width: float = DEFAULT_MAX_SHEET_WIDTH,
) -> list[Issue]:
    """Проверяет, не превышает ли пильный габарит детали стандартный лист (п. 2.2, 3.8)."""
    out: list[Issue] = []
    lim_l = max(float(max_length), float(max_width))
    lim_w = min(float(max_length), float(max_width))
    for p in _iter_panels(blocks):
        if hasattr(p, "get_saw_dimensions") and callable(p.get_saw_dimensions):
            dims = sorted([float(x) for x in p.get_saw_dimensions()], reverse=True)
        else:
            dims = sorted([float(p.width), float(p.height), float(p.depth)], reverse=True)
        if len(dims) < 2:
            continue
        length, width = dims[0], dims[1]
        if length > lim_l + 1e-6 or width > lim_w + 1e-6:
            pname = str(getattr(p, "name", "") or "Панель")
            puid = str(getattr(p, "uid", "") or "")
            out.append(
                Issue(
                    severity="warning",
                    panel_uid=puid,
                    code="oversized_panel",
                    message=(
                        f"Деталь «{pname}»: габарит {length:g}×{width:g} мм "
                        f"превышает размер стандартного листа ({lim_l:g}×{lim_w:g} мм)"
                    ),
                )
            )
    return out


def issues_from_collision_hits(hits: list) -> list[Issue]:
    """Преобразует результаты CADKernel.find_scene_collisions в список Issue (п. 2.2)."""
    from core.cad_kernel import CADKernel

    out: list[Issue] = []
    for p1, p2, vol in hits or []:
        puid = str(getattr(p1, "uid", "") or getattr(p2, "uid", "") or "")
        text = CADKernel.format_collision_hit(p1, p2, vol)
        # Срезаем ведущий эмодзи из format_collision_hit, т.к. Issue.format_line() добавляет его сам
        clean_msg = text.lstrip("❌⚠️ ").strip()
        if vol is None or (isinstance(vol, float) and math.isnan(vol)):
            out.append(
                Issue(
                    severity="warning",
                    panel_uid=puid,
                    code="collision_check_failed",
                    message=clean_msg,
                )
            )
        else:
            out.append(
                Issue(
                    severity="error",
                    panel_uid=puid,
                    code="panel_collision",
                    message=clean_msg,
                )
            )
    return out


def check_collisions_in_blocks(blocks, min_volume: float = 0.1) -> list[Issue]:
    """Проверяет 3D-пересечения деталей сцены и возвращает список Issue (п. 2.2).

    Пересечения считает ``CADKernel.find_scene_collisions`` (тот же путь, что в UI).
    """
    from core.cad_kernel import CADKernel

    panels = list(_iter_panels(blocks))
    if len(panels) < 2:
        return []

    hits = list(CADKernel.find_scene_collisions(panels, min_volume=min_volume))
    return issues_from_collision_hits(hits)


def check_broken_joints_in_blocks(blocks) -> list[Issue]:
    """Стыки, у которых панели пропали или больше не касаются (ревизия 3 §1.3).

    ``apply_joints`` в этом случае молча не ставит присадку — без замечания
    технолог видит «полку без крепежа» и не понимает причину.
    """
    from core.joint import find_joint

    issues: list[Issue] = []
    for b in blocks or []:
        by_uid = {
            str(getattr(p, "uid", "") or ""): p
            for p in (getattr(b, "panels", None) or [])
            if str(getattr(p, "uid", "") or "")
        }
        for jr in getattr(b, "joints", None) or []:
            a_uid = str(getattr(jr, "panel_a_uid", "") or "")
            b_uid = str(getattr(jr, "panel_b_uid", "") or "")
            pa = by_uid.get(a_uid)
            pb = by_uid.get(b_uid)
            if pa is None or pb is None:
                ref = pa or pb or b
                ref_uid = str(getattr(ref, "uid", "") or "")
                missing = []
                if pa is None:
                    missing.append(a_uid or "?")
                if pb is None:
                    missing.append(b_uid or "?")
                issues.append(
                    Issue(
                        severity="warning",
                        panel_uid=ref_uid,
                        code="joint_panel_missing",
                        message=(
                            f"Стык ссылается на удалённую деталь "
                            f"(uid: {', '.join(missing)})"
                        ),
                    )
                )
                continue

            joint = find_joint(pa, pb)
            if joint is None:
                joint = find_joint(pa, pb, tol=3.0)
            if joint is None:
                na = str(getattr(pa, "name", "") or "A")
                nb = str(getattr(pb, "name", "") or "B")
                issues.append(
                    Issue(
                        severity="warning",
                        panel_uid=str(getattr(pa, "uid", "") or ""),
                        code="joint_broken",
                        message=(
                            f"Стык «{na}» — «{nb}»: детали не касаются, "
                            f"присадка стыка снята"
                        ),
                    )
                )
    return issues


# Реестр проверок модели: список функций check(blocks) -> list[Issue] (ревизия 2, п. 2.2)
ISSUE_CHECKS: list[Callable[[list], list[Issue]]] = [
    check_missing_materials_in_blocks,
    check_missing_edges_in_blocks,
    check_edge_width_in_blocks,
    check_fastener_issues_in_blocks,
    check_hole_edge_distance_in_blocks,
    check_holes_in_grooves_in_blocks,
    check_holes_intersection_in_blocks,
    check_oversized_panels_in_blocks,
    check_broken_joints_in_blocks,
    check_collisions_in_blocks,
]

CHECKS = ISSUE_CHECKS


def register_issue_check(fn: Callable[[list], list[Issue]]) -> Callable[[list], list[Issue]]:
    """Регистрирует функцию проверки check(blocks) -> list[Issue] в общем реестре."""
    if fn not in ISSUE_CHECKS:
        ISSUE_CHECKS.append(fn)
    return fn


def check_scene_issues(blocks, *, include_collisions: bool = True) -> list[Issue]:
    """Запускает все зарегистрированные проверки сцены и возвращает список Issue без дубликатов."""
    issues: list[Issue] = []
    seen: set[tuple[str, str, str]] = set()
    for fn in ISSUE_CHECKS:
        if not include_collisions and fn is check_collisions_in_blocks:
            continue
        for iss in fn(blocks):
            key = (iss.panel_uid, iss.code, iss.message)
            if key not in seen:
                seen.add(key)
                issues.append(iss)
    return issues


def check(blocks) -> list[Issue]:
    """Единая точка входа проверки блоков сцены (алиас check_scene_issues)."""
    return check_scene_issues(blocks, include_collisions=True)
