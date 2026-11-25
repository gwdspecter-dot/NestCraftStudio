# -*- coding: utf-8 -*-
"""3D-навигация от отверстия к породившему стыку (JointRecord) или ассоциации (AssocRef).

Модуль не зависит от PyQt6/OpenGL и полностью тестируется в headless-окружении:
- ``classify_hole_owner`` — определяет владельца отверстия (``joint`` / ``assoc`` / ``manual``);
- ``hole_world_segment`` — вычисляет мировой отрезок оси отверстия с учётом поворота панели (OBB);
- ``ray_segment_closest`` — точное кратчайшее расстояние между лучом и отрезком оси отверстия;
- ``pick_hole_at_ray`` — 3D + экранный выбор ближайшего отверстия под курсором с учётом
  плоскости сечения и перекрытия передними панелями;
- ``collect_owner_holes`` — собирает все отверстия блока, принадлежащие одному стыку или ассоциации,
  для групповой 3D-подсветки;
- ``describe_hole_hit`` — формирует краткую русскоязычную подпись для HUD / статусной строки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from core import glmath
from core.assoc import AssocRef, evaluate_assoc_ref, hole_assoc_uid
from core.joint import JointRecord, get_fastener_preset, hole_joint_uid
from core.logging_setup import get_logger

_log = get_logger("hole_nav")


@dataclass(frozen=True)
class HoleHit:
    """Результат попадания курсора/луча в 3D-отверстие на панели."""

    block: Any
    panel: Any
    hole_index: int
    hole: tuple
    kind: str  # "joint" | "assoc" | "manual"
    owner_uid: str
    world_p0: tuple[float, float, float]
    world_p1: tuple[float, float, float]
    world_mid: tuple[float, float, float]
    ray_t: float
    screen_dist_px: float
    screen_mid: tuple[float, float] | None = None

    @property
    def has_owner(self) -> bool:
        return self.kind in ("joint", "assoc") and bool(self.owner_uid)


def classify_hole_owner(hole: tuple | list | None) -> tuple[str, str]:
    """Определяет происхождение отверстия: ``("assoc", uid)``, ``("joint", uid)`` или ``("manual", "")``."""
    if hole is None or len(hole) < 6:
        return "manual", ""
    auid = hole_assoc_uid(hole)
    if auid:
        return "assoc", auid
    juid = hole_joint_uid(hole)
    if juid:
        return "joint", juid
    return "manual", ""


def hole_world_segment(panel: Any, hole: tuple | list) -> tuple[np.ndarray, np.ndarray, float]:
    """Возвращает ``(world_p0, world_p1, radius)`` цилиндра отверстия с учётом поворота панели."""
    hx = float(hole[0])
    hy = float(hole[1])
    hz = float(hole[2])
    radius = max(0.5, float(hole[3]) if len(hole) > 3 else 4.0)
    length = max(0.5, float(hole[4]) if len(hole) > 4 else 12.0)
    axis = str(hole[5] if len(hole) > 5 else "Z").upper()

    if axis == "X":
        loc_dir = (1.0, 0.0, 0.0)
    elif axis == "Y":
        loc_dir = (0.0, 1.0, 0.0)
    else:
        loc_dir = (0.0, 0.0, 1.0)

    if hasattr(panel, "local_to_world"):
        x0, y0, z0 = panel.local_to_world(hx, hy, hz)
        x1, y1, z1 = panel.local_to_world(
            hx + loc_dir[0] * length,
            hy + loc_dir[1] * length,
            hz + loc_dir[2] * length,
        )
        p0 = np.array([float(x0), float(y0), float(z0)], dtype=float)
        p1 = np.array([float(x1), float(y1), float(z1)], dtype=float)
    else:
        px = float(getattr(panel, "x", 0.0))
        py = float(getattr(panel, "y", 0.0))
        pz = float(getattr(panel, "z", 0.0))
        p0 = np.array([px + hx, py + hy, pz + hz], dtype=float)
        p1 = np.array(
            [
                px + hx + loc_dir[0] * length,
                py + hy + loc_dir[1] * length,
                pz + hz + loc_dir[2] * length,
            ],
            dtype=float,
        )
    return p0, p1, radius


def ray_segment_closest(
    ray_origin: np.ndarray,
    ray_dir: np.ndarray,
    seg_p0: np.ndarray,
    seg_p1: np.ndarray,
) -> tuple[float, float, float]:
    """Кратчайшее расстояние между лучом ``O + t*D (t >= 0)`` и отрезком ``[P0, P1]``.

    Возвращает ``(distance_3d, ray_t, seg_s)``, где ``ray_t >= 0`` и ``0 <= seg_s <= 1``.
    """
    ro = np.asarray(ray_origin, dtype=float)
    rd = np.asarray(ray_dir, dtype=float)
    rd_len = float(np.linalg.norm(rd))
    if rd_len < 1e-12:
        p0 = np.asarray(seg_p0, dtype=float)
        return float(np.linalg.norm(p0 - ro)), 0.0, 0.0
    u = rd / rd_len

    p0 = np.asarray(seg_p0, dtype=float)
    p1 = np.asarray(seg_p1, dtype=float)
    v = p1 - p0
    w0 = ro - p0

    a = 1.0  # dot(u, u)
    b = float(np.dot(u, v))
    c = float(np.dot(v, v))
    d = float(np.dot(u, w0))
    e = float(np.dot(v, w0))

    if c < 1e-12:
        t = max(0.0, -d)
        pt = ro + t * u
        return float(np.linalg.norm(pt - p0)), t, 0.0

    denom = a * c - b * b
    if abs(denom) < 1e-10:
        # Луч почти параллелен оси отверстия — проверяем оба торца отрезка
        t0 = max(0.0, -d)
        dist0 = float(np.linalg.norm((ro + t0 * u) - p0))
        d1 = float(np.dot(u, ro - p1))
        t1 = max(0.0, -d1)
        dist1 = float(np.linalg.norm((ro + t1 * u) - p1))
        if dist0 <= dist1:
            return dist0, t0, 0.0
        return dist1, t1, 1.0

    s_num = a * e - b * d
    t_num = b * e - c * d

    if s_num < 0.0:
        s = 0.0
        t = max(0.0, -d)
    elif s_num > denom:
        s = 1.0
        t = max(0.0, -(d - b))
    else:
        if t_num < 0.0:
            t = 0.0
            s = max(0.0, min(1.0, e / c))
        else:
            t = t_num / denom
            s = s_num / denom

    closest_ray = ro + t * u
    closest_seg = p0 + s * v
    dist = float(np.linalg.norm(closest_ray - closest_seg))
    return dist, float(t), float(s)


def _point_to_segment_2d(
    px: float,
    py: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> float:
    vx = x1 - x0
    vy = y1 - y0
    seg_len2 = vx * vx + vy * vy
    if seg_len2 < 1e-9:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * vx + (py - y0) * vy) / seg_len2
    t = max(0.0, min(1.0, t))
    cx = x0 + t * vx
    cy = y0 + t * vy
    return math.hypot(px - cx, py - cy)


def _project_to_logical(
    pt: np.ndarray,
    mvp: np.ndarray,
    viewport: tuple[int, int, int, int],
    dpr: float,
) -> tuple[float, float, float] | None:
    try:
        wx, wy, wz = glmath.project(float(pt[0]), float(pt[1]), float(pt[2]), mvp, viewport)
    except Exception as exc:  # noqa: BLE001
        _log.debug("project failed in hole_nav: %s", exc)
        return None
    if wz < 0.0 or wz > 1.0:
        return None
    inv_dpr = 1.0 / max(0.25, float(dpr))
    return float(wx) * inv_dpr, float(viewport[3] - wy) * inv_dpr, float(wz)


def pick_hole_at_ray(
    blocks: list[Any],
    ray_origin: np.ndarray,
    ray_dir: np.ndarray,
    *,
    mvp: np.ndarray | None = None,
    viewport: tuple[int, int, int, int] | None = None,
    mouse_xy: tuple[float, float] | None = None,
    dpr: float = 1.0,
    max_screen_px: float = 12.0,
    ray_margin_mm: float = 4.0,
    section_plane: tuple[float, float, float, float] | None = None,
    occluded_t: float | None = None,
    front_panel: Any | None = None,
    ignore_occlusion: bool = False,
) -> HoleHit | None:
    """Находит ближайшее отверстие под курсором/лучом среди всех видимых панелей ``blocks``.

    Поддерживает два режима:
    - с матрицей ``mvp`` + ``viewport`` + ``mouse_xy``: экранный допуск ``max(max_screen_px, r_px)``
      плюс отсечение скрытых отверстий за передними панелями (если ``not ignore_occlusion``);
    - чисто геометрический (без ``mvp``): пересечение луча с цилиндром отверстия в 3D
      с допуском ``radius + ray_margin_mm``.
    """
    if not blocks:
        return None

    ro = np.asarray(ray_origin, dtype=float)
    rd = np.asarray(ray_dir, dtype=float)
    rd_len = float(np.linalg.norm(rd))
    if rd_len < 1e-12:
        return None
    rd = rd / rd_len

    use_screen = mvp is not None and viewport is not None and mouse_xy is not None
    mx = float(mouse_xy[0]) if mouse_xy is not None else 0.0
    my = float(mouse_xy[1]) if mouse_xy is not None else 0.0

    best_hit: HoleHit | None = None
    best_rank: tuple[int, float, float, int] | None = None

    for block in blocks:
        for panel in getattr(block, "panels", None) or []:
            if not getattr(panel, "visible", True):
                continue
            holes = getattr(panel, "holes", None) or []
            if not holes:
                continue

            for idx, hole in enumerate(holes):
                if hole is None or len(hole) < 6:
                    continue
                p0, p1, radius = hole_world_segment(panel, hole)
                mid = 0.5 * (p0 + p1)

                if section_plane is not None:
                    passes = (
                        glmath.point_passes_clip_plane(float(p0[0]), float(p0[1]), float(p0[2]), section_plane)
                        or glmath.point_passes_clip_plane(float(p1[0]), float(p1[1]), float(p1[2]), section_plane)
                        or glmath.point_passes_clip_plane(float(mid[0]), float(mid[1]), float(mid[2]), section_plane)
                    )
                    if not passes:
                        continue

                dist_3d, ray_t, _seg_s = ray_segment_closest(ro, rd, p0, p1)
                if ray_t < 0.0:
                    continue

                hole_len = float(np.linalg.norm(p1 - p0))
                is_front_panel = front_panel is not None and panel is front_panel

                # Защита от выбора отверстия на дальней детали сквозь сплошную переднюю панель
                if occluded_t is not None and not ignore_occlusion and not is_front_panel:
                    tol_depth = max(hole_len + radius + 10.0, 26.0)
                    if ray_t > float(occluded_t) + tol_depth:
                        continue

                screen_dist = dist_3d
                screen_mid: tuple[float, float] | None = None
                if use_screen:
                    sp0 = _project_to_logical(p0, mvp, viewport, dpr)
                    sp1 = _project_to_logical(p1, mvp, viewport, dpr)
                    smid = _project_to_logical(mid, mvp, viewport, dpr)
                    if sp0 is None and sp1 is None and smid is None:
                        continue
                    if sp0 is not None and sp1 is not None:
                        screen_dist = _point_to_segment_2d(mx, my, sp0[0], sp0[1], sp1[0], sp1[1])
                        screen_mid = (0.5 * (sp0[0] + sp1[0]), 0.5 * (sp0[1] + sp1[1]))
                    else:
                        ref_sp = smid or sp0 or sp1
                        assert ref_sp is not None
                        screen_dist = math.hypot(mx - ref_sp[0], my - ref_sp[1])
                        screen_mid = (ref_sp[0], ref_sp[1])

                    # Оцениваем экранный радиус отверстия, чтобы вблизи попадать в любую точку круга
                    eff_px = float(max_screen_px)
                    if smid is not None:
                        perp = np.array([1.0, 0.0, 0.0], dtype=float)
                        if abs(float(np.dot(perp, rd))) > 0.9:
                            perp = np.array([0.0, 1.0, 0.0], dtype=float)
                        s_edge = _project_to_logical(mid + perp * radius, mvp, viewport, dpr)
                        if s_edge is not None:
                            r_px = math.hypot(s_edge[0] - smid[0], s_edge[1] - smid[1])
                            eff_px = max(eff_px, r_px + 4.0)

                    # Принимаем, если курсор в экранном радиусе ИЛИ луч прямо пробивает цилиндр отверстия
                    if screen_dist > eff_px and dist_3d > (radius + 1.5):
                        continue
                else:
                    if dist_3d > (radius + float(ray_margin_mm)):
                        continue

                kind, owner_uid = classify_hole_owner(hole)
                # Приоритет:
                # 1. Отверстия на передней панели под курсором (если не xray/wireframe);
                # 2. Ближайшее по экранному расстоянию / глубине;
                # 3. При прочих равных: привязанные (joint/assoc) выше ручных.
                front_priority = 0 if (is_front_panel and not ignore_occlusion) else 1
                owner_priority = 0 if kind in ("joint", "assoc") else 1
                if use_screen:
                    rank = (front_priority, round(screen_dist, 1), round(ray_t, 2), owner_priority)
                else:
                    rank = (front_priority, round(ray_t, 2), round(dist_3d, 2), owner_priority)

                if best_rank is None or rank < best_rank:
                    best_rank = rank
                    best_hit = HoleHit(
                        block=block,
                        panel=panel,
                        hole_index=idx,
                        hole=tuple(hole),
                        kind=kind,
                        owner_uid=owner_uid,
                        world_p0=(float(p0[0]), float(p0[1]), float(p0[2])),
                        world_p1=(float(p1[0]), float(p1[1]), float(p1[2])),
                        world_mid=(float(mid[0]), float(mid[1]), float(mid[2])),
                        ray_t=float(ray_t),
                        screen_dist_px=float(screen_dist),
                        screen_mid=screen_mid,
                    )

    return best_hit


def _nav_scene_blocks(block: Any, blocks: list[Any] | None = None) -> list[Any]:
    if isinstance(blocks, (list, tuple)) and blocks:
        seq = [b for b in blocks if b is not None]
        if block is not None and block not in seq:
            seq.append(block)
        return seq
    sb = getattr(block, "_scene_blocks", None) if block is not None else None
    if isinstance(sb, list) and sb and (block is None or block in sb):
        return [b for b in sb if b is not None]
    return [block] if block is not None else []


def collect_owner_holes(
    block: Any,
    kind: str,
    owner_uid: str,
    *,
    blocks: list[Any] | None = None,
) -> list[tuple[Any, tuple]]:
    """Возвращает все пары ``(panel, hole)`` блока/сцены, принадлежащие стыку или ассоциации ``owner_uid``."""
    uid = str(owner_uid or "").strip()
    if (block is None and not blocks) or not uid or kind not in ("joint", "assoc"):
        return []
    out: list[tuple[Any, tuple]] = []
    seen_panels: set[int] = set()
    for blk in _nav_scene_blocks(block, blocks):
        for panel in getattr(blk, "panels", None) or []:
            if id(panel) in seen_panels:
                continue
            seen_panels.add(id(panel))
            if not getattr(panel, "visible", True):
                continue
            for hole in getattr(panel, "holes", None) or []:
                if hole is None or len(hole) < 6:
                    continue
                h_kind, h_uid = classify_hole_owner(hole)
                if h_kind == kind and h_uid == uid:
                    out.append((panel, tuple(hole)))
    return out


def _find_joint_record(
    block: Any,
    joint_uid: str,
    *,
    blocks: list[Any] | None = None,
) -> JointRecord | None:
    if (block is None and not blocks) or not joint_uid:
        return None
    for blk in _nav_scene_blocks(block, blocks):
        if hasattr(blk, "get_joint_by_uid"):
            rec = blk.get_joint_by_uid(joint_uid)
            if rec is not None:
                return rec
        for raw in getattr(blk, "joints", None) or []:
            jr = raw if isinstance(raw, JointRecord) else JointRecord.from_dict(raw)
            if str(getattr(jr, "uid", "")) == joint_uid:
                return jr
    return None


def _find_assoc_record(
    block: Any,
    assoc_uid: str,
    *,
    blocks: list[Any] | None = None,
) -> AssocRef | None:
    if (block is None and not blocks) or not assoc_uid:
        return None
    for blk in _nav_scene_blocks(block, blocks):
        for raw in getattr(blk, "assoc_refs", None) or []:
            ref = raw if isinstance(raw, AssocRef) else AssocRef.from_dict(raw)
            if str(getattr(ref, "uid", "")) == assoc_uid:
                return ref
    return None


def describe_hole_hit(
    hit: HoleHit,
    *,
    include_hint: bool = False,
    compact: bool = True,
    blocks: list[Any] | None = None,
) -> str:
    """Краткая подпись отверстия под курсором (без эмодзи)."""
    hole = hit.hole
    dia = float(hole[3]) * 2.0 if len(hole) > 3 else 0.0
    depth = float(hole[4]) if len(hole) > 4 else 0.0
    dim_str = f"Ø{dia:g}×{depth:g}"
    panel_name = str(getattr(hit.panel, "name", "Панель"))
    scene_blocks = _nav_scene_blocks(hit.block, blocks)
    by_uid = {
        str(getattr(p, "uid", "")): str(getattr(p, "name", "Панель"))
        for blk in scene_blocks
        for p in (getattr(blk, "panels", None) or [])
    }

    if hit.kind == "joint":
        rec = _find_joint_record(hit.block, hit.owner_uid, blocks=scene_blocks)
        if rec is not None:
            pa = by_uid.get(str(rec.panel_a_uid), "?")
            pb = by_uid.get(str(rec.panel_b_uid), "?")
            preset = get_fastener_preset(rec.preset_id) or {}
            plabel = str(preset.get("label") or rec.preset_id or "Стык")
            if compact:
                base = f"Стык: {plabel} · {dim_str}"
            else:
                base = f"Стык: {pa} ↔ {pb} ({plabel}) · {dim_str}"
        else:
            if compact:
                base = f"Стык · {dim_str}"
            else:
                base = f"Стык [{hit.owner_uid[:8]}] на «{panel_name}» · {dim_str}"
        return base + ("  [ЛКМ×2 / ПКМ]" if include_hint else "")

    if hit.kind == "assoc":
        ref = _find_assoc_record(hit.block, hit.owner_uid, blocks=scene_blocks)
        if ref is not None:
            st = evaluate_assoc_ref(hit.block, ref, all_blocks=scene_blocks)
            tgt = by_uid.get(str(ref.target_uid), panel_name)
            src = by_uid.get(str(ref.source_uid), (ref.source_uid or "?")[:8])
            if ref.fixed:
                base = (
                    f"Ассоциация (фикс.) · {dim_str}"
                    if compact
                    else f"Ассоциация (фикс.): {tgt} · {dim_str}"
                )
            else:
                tag = " [!]" if st.severity != "ok" else ""
                base = (
                    f"Ассоциация{tag}: {src}.{ref.source_face} · {dim_str}"
                    if compact
                    else f"Ассоциация{tag}: {tgt} ← {src}.{ref.source_face} · {dim_str}"
                )
        else:
            if compact:
                base = f"Ассоциация · {dim_str}"
            else:
                base = f"Ассоциация [{hit.owner_uid[:8]}] на «{panel_name}» · {dim_str}"
        return base + ("  [ЛКМ×2 / ПКМ]" if include_hint else "")

    base = f"Отверстие · {dim_str}" if compact else f"Отверстие ({panel_name}): {dim_str}"
    return base + ("  [ЛКМ×2 / ПКМ]" if include_hint else "")


