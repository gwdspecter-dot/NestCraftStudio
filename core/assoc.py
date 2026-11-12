# -*- coding: utf-8 -*-
"""Ассоциативные ссылки: feature (отверстие) привязан к геометрии соседней панели.

Модель сознательно зеркалит JointRecord / apply_joints:
- записи живут на Block (`block.assoc_refs`);
- отверстия, порождённые ссылкой, помечаются 7-м полем (owner uid);
- ручные отверстия не трогаются;
- после изменения габаритов/позы вызывается apply_assoc_refs(block).

MVP kind = ``face_hole``:
  отверстие на target-панели, позиция считается от выбранной грани source-панели
  (центр грани + смещения u/v в плоскости грани).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import numpy as np

from core.logging_setup import get_logger

_log = get_logger("assoc")

# Имена граней в локальных осях панели (нормаль наружу от объёма).
FACE_NAMES = ("X+", "X-", "Y+", "Y-", "Z+", "Z-")

_FACE_AXIS = {
    "X+": 0,
    "X-": 0,
    "Y+": 1,
    "Y-": 1,
    "Z+": 2,
    "Z-": 2,
}
_FACE_SIGN = {
    "X+": 1.0,
    "X-": -1.0,
    "Y+": 1.0,
    "Y-": -1.0,
    "Z+": 1.0,
    "Z-": -1.0,
}


def _norm_face(name: str) -> str:
    key = str(name or "").strip().upper().replace(" ", "")
    aliases = {
        "XP": "X+",
        "XM": "X-",
        "YP": "Y+",
        "YM": "Y-",
        "ZP": "Z+",
        "ZM": "Z-",
        "+X": "X+",
        "-X": "X-",
        "+Y": "Y+",
        "-Y": "Y-",
        "+Z": "Z+",
        "-Z": "Z-",
        "MAX_X": "X+",
        "MIN_X": "X-",
        "MAX_Y": "Y+",
        "MIN_Y": "Y-",
        "MAX_Z": "Z+",
        "MIN_Z": "Z-",
    }
    key = aliases.get(key, key)
    if key not in FACE_NAMES:
        raise ValueError(f"Unknown face name: {name!r}")
    return key


def panel_face_frame(panel, face: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Возвращает (origin_world, normal_world, u_axis_world, v_axis_world) для грани панели.

    origin — центр грани в мире.
    u, v — ортонормированный базис плоскости грани (из локальных осей панели).
    """
    face = _norm_face(face)
    ax = _FACE_AXIS[face]
    sign = _FACE_SIGN[face]

    dims = np.array(
        [float(panel.width), float(panel.height), float(panel.depth)],
        dtype=float,
    )
    local_center = dims * 0.5
    local_origin = local_center.copy()
    local_origin[ax] = dims[ax] if sign > 0 else 0.0

    # Локальные оси плоскости: две оставшиеся координатные оси
    other = [i for i in (0, 1, 2) if i != ax]
    local_u = np.zeros(3, dtype=float)
    local_v = np.zeros(3, dtype=float)
    local_u[other[0]] = 1.0
    local_v[other[1]] = 1.0
    local_n = np.zeros(3, dtype=float)
    local_n[ax] = sign

    def _to_world_vec(lx: float, ly: float, lz: float) -> np.ndarray:
        wx, wy, wz = panel.rotate_vector(lx, ly, lz)
        return np.array([wx, wy, wz], dtype=float)

    def _to_world_pt(lx: float, ly: float, lz: float) -> np.ndarray:
        wx, wy, wz = panel.local_to_world(lx, ly, lz)
        return np.array([wx, wy, wz], dtype=float)

    origin = _to_world_pt(float(local_origin[0]), float(local_origin[1]), float(local_origin[2]))
    normal = _to_world_vec(float(local_n[0]), float(local_n[1]), float(local_n[2]))
    u_axis = _to_world_vec(float(local_u[0]), float(local_u[1]), float(local_u[2]))
    v_axis = _to_world_vec(float(local_v[0]), float(local_v[1]), float(local_v[2]))

    n_len = float(np.linalg.norm(normal))
    u_len = float(np.linalg.norm(u_axis))
    v_len = float(np.linalg.norm(v_axis))
    if n_len < 1e-12 or u_len < 1e-12 or v_len < 1e-12:
        raise ValueError("Degenerate panel face frame")
    normal = normal / n_len
    u_axis = u_axis / u_len
    v_axis = v_axis / v_len
    return origin, normal, u_axis, v_axis


def face_point_world(panel, face: str, u: float, v: float) -> np.ndarray:
    """Мировая точка: центр грани + u * u_axis + v * v_axis."""
    origin, _n, u_axis, v_axis = panel_face_frame(panel, face)
    return origin + float(u) * u_axis + float(v) * v_axis


def _axis_from_normal(normal: np.ndarray) -> str:
    """Ближайшая координатная ось к нормали ('X'|'Y'|'Z')."""
    ax = int(np.argmax(np.abs(normal)))
    return ("X", "Y", "Z")[ax]


@dataclass
class AssocRef:
    """Параметрическая ассоциативная ссылка внутри блока.

    Поля:
    - ``uid``: id записи;
    - ``kind``: тип (MVP: ``face_hole``);
    - ``target_uid``: панель, на которой создаётся отверстие;
    - ``source_uid``: панель-источник геометрии;
    - ``source_face``: грань источника (``X+`` … ``Z-``);
    - ``params``: ``u``, ``v``, ``diameter``, ``depth``, ``axis`` (опционально),
      ``inset`` (смещение вдоль нормали грани в сторону target, мм).
    """

    uid: str = ""
    kind: str = "face_hole"
    target_uid: str = ""
    source_uid: str = ""
    source_face: str = "Z+"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.uid = str(self.uid or "").strip() or str(uuid4())
        self.kind = str(self.kind or "face_hole").strip() or "face_hole"
        self.target_uid = str(self.target_uid or "").strip()
        self.source_uid = str(self.source_uid or "").strip()
        try:
            self.source_face = _norm_face(self.source_face)
        except ValueError:
            self.source_face = "Z+"
        raw = dict(self.params) if isinstance(self.params, dict) else {}
        raw.setdefault("u", 0.0)
        raw.setdefault("v", 0.0)
        raw.setdefault("diameter", 5.0)
        raw.setdefault("depth", 12.0)
        raw.setdefault("inset", 0.0)
        for key in ("u", "v", "diameter", "depth", "inset"):
            try:
                raw[key] = float(raw[key])
            except (TypeError, ValueError):
                raw[key] = 0.0 if key in ("u", "v", "inset") else (5.0 if key == "diameter" else 12.0)
        if raw.get("axis") is not None:
            ax = str(raw["axis"]).strip().upper()
            raw["axis"] = ax if ax in ("X", "Y", "Z") else None
        self.params = raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": str(self.uid),
            "kind": str(self.kind),
            "target_uid": str(self.target_uid),
            "source_uid": str(self.source_uid),
            "source_face": str(self.source_face),
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | "AssocRef") -> "AssocRef":
        if isinstance(data, cls):
            return cls(
                uid=data.uid,
                kind=data.kind,
                target_uid=data.target_uid,
                source_uid=data.source_uid,
                source_face=data.source_face,
                params=dict(data.params),
            )
        return cls(
            uid=str(data.get("uid") or ""),
            kind=str(data.get("kind") or "face_hole"),
            target_uid=str(data.get("target_uid") or ""),
            source_uid=str(data.get("source_uid") or ""),
            source_face=str(data.get("source_face") or "Z+"),
            params=dict(data.get("params") or {}) if isinstance(data.get("params"), dict) else {},
        )

    def clone(self, *, new_id: bool = True) -> "AssocRef":
        return AssocRef(
            uid="" if new_id else self.uid,
            kind=self.kind,
            target_uid=self.target_uid,
            source_uid=self.source_uid,
            source_face=self.source_face,
            params=dict(self.params),
        )


def hole_assoc_uid(hole) -> str:
    """Uid ассоциативной записи из 7-го поля, если отверстие принадлежит AssocRef."""
    if hole is None or len(hole) < 7:
        return ""
    raw = str(hole[6] or "").strip()
    if raw.startswith("a:"):
        return raw[2:].strip()
    return ""


def tag_assoc_hole(hole, assoc_uid: str) -> tuple:
    """Помечает отверстие как порождённое AssocRef (префикс a: в 7-м поле)."""
    from core.joint import hole_geometry

    g = hole_geometry(hole)
    uid = str(assoc_uid or "").strip()
    if not uid:
        return g
    return g + (f"a:{uid}",)


def extract_assoc_holes(panel) -> list[tuple]:
    """Отверстия с меткой AssocRef (полный кортеж с 7-м полем)."""
    out: list[tuple] = []
    for h in list(getattr(panel, "holes", []) or []):
        if len(h) >= 7 and hole_assoc_uid(h):
            out.append(tuple(h))
    return out


def compute_face_hole(target, source, ref: AssocRef) -> tuple | None:
    """Считает локальное отверстие на target по грани source. None если не удалось."""
    if target is None or source is None or ref is None:
        return None
    if str(getattr(target, "uid", "")) == str(getattr(source, "uid", "")):
        return None

    u = float(ref.params.get("u") or 0.0)
    v = float(ref.params.get("v") or 0.0)
    diameter = float(ref.params.get("diameter") or 5.0)
    depth = float(ref.params.get("depth") or 12.0)
    inset = float(ref.params.get("inset") or 0.0)
    if diameter <= 0 or depth <= 0:
        return None

    try:
        origin, normal, _ua, _va = panel_face_frame(source, ref.source_face)
        world_pt = face_point_world(source, ref.source_face, u, v)
    except (ValueError, AttributeError) as exc:
        _log.debug("face frame failed for assoc %s: %s", ref.uid, exc)
        return None

    # Смещаем точку вдоль нормали грани (часто внутрь target)
    if abs(inset) > 1e-9:
        world_pt = world_pt + (-float(inset)) * normal

    try:
        lx, ly, lz = target.world_to_local(float(world_pt[0]), float(world_pt[1]), float(world_pt[2]))
    except Exception as exc:  # noqa: BLE001
        _log.debug("world_to_local failed for assoc %s: %s", ref.uid, exc)
        return None

    axis = ref.params.get("axis")
    if axis not in ("X", "Y", "Z"):
        # Ось сверления — вдоль нормали грани источника, в локали target
        try:
            # нормаль мира → локальный вектор target
            n_end = world_pt + normal
            nx, ny, nz = target.world_to_local(float(n_end[0]), float(n_end[1]), float(n_end[2]))
            local_n = np.array([nx - lx, ny - ly, nz - lz], dtype=float)
            axis = _axis_from_normal(local_n)
        except Exception:  # noqa: BLE001
            axis = _axis_from_normal(normal)

    # Радиус в формате holes NestCraft (поле [3] — radius, не diameter)
    radius = float(diameter) * 0.5
    return (float(lx), float(ly), float(lz), float(radius), float(depth), str(axis))


def apply_assoc_refs(block, *, rebuild_geometry: bool = True) -> list:
    """Пересчитывает отверстия из ``block.assoc_refs``.

    - Ручные отверстия и отверстия JointRecord сохраняются.
    - Старые assoc-отверстия снимаются и создаются заново.
    - Возвращает список замечаний (строки/Issue-совместимые сообщения).
    """
    if block is None:
        return []

    from core.joint import (
        extract_manual_holes,
        hole_geometry,
        hole_joint_uid,
        holes_equal,
    )

    panels = list(getattr(block, "panels", []) or [])
    raw_refs = list(getattr(block, "assoc_refs", []) or [])
    norm_refs: list[AssocRef] = []
    for item in raw_refs:
        if isinstance(item, AssocRef):
            norm_refs.append(item)
        elif isinstance(item, dict):
            norm_refs.append(AssocRef.from_dict(item))
    block.assoc_refs = norm_refs

    old_holes_by_id: dict[int, list[tuple]] = {}
    for p in panels:
        try:
            p._block = block
        except Exception as exc:  # noqa: BLE001
            _log.debug("Could not bind _block on panel: %s", exc)
        old_holes_by_id[id(p)] = [
            hole_geometry(h) for h in (getattr(p, "holes", []) or []) if len(h) >= 6
        ]

        # Сохраняем: ручные + joint-tagged (не assoc)
        kept: list[tuple] = []
        for h in list(getattr(p, "holes", []) or []):
            if len(h) < 6:
                continue
            if hole_assoc_uid(h):
                continue
            if hole_joint_uid(h) and not str(h[6]).startswith("a:"):
                kept.append(tuple(h))
                continue
            # без метки — кандидат в manual; final manual через extract после очистки assoc
            kept.append(tuple(h) if len(h) >= 7 else hole_geometry(h))

        # Пересобираем holes: manual + joints (без assoc)
        manual = []
        jointed = []
        for h in kept:
            if hole_joint_uid(h) and not str(h[6] if len(h) > 6 else "").startswith("a:"):
                jointed.append(tuple(h))
            elif not hole_assoc_uid(h):
                # возможно joint через legacy map — extract_manual_holes разберёт
                pass
        # Надёжный путь: взять manual через joint-helper, затем добавить joint-отверстия из map/tag
        manual = extract_manual_holes(p)
        # extract_manual пропускает любые 7-е поля; joint holes нужно вернуть из joint_hole_map
        jmap = getattr(p, "joint_hole_map", None) or {}
        joint_from_map: list[tuple] = []
        for hlist in jmap.values():
            for jh in hlist or []:
                if len(jh) >= 6:
                    joint_from_map.append(tuple(jh) if len(jh) >= 7 else hole_geometry(jh))
        # Также явные joint-tagged в текущем списке
        for h in list(getattr(p, "holes", []) or []):
            if len(h) >= 7 and hole_joint_uid(h) and not str(h[6]).startswith("a:"):
                if not any(holes_equal(h, x) for x in joint_from_map):
                    joint_from_map.append(tuple(h))

        p.holes = list(manual) + list(joint_from_map)
        if hasattr(p, "assoc_hole_map"):
            p.assoc_hole_map = {}

    by_uid = {
        str(getattr(p, "uid", "") or ""): p
        for p in panels
        if str(getattr(p, "uid", "") or "")
    }

    notes: list = []
    for ref in norm_refs:
        if ref.kind != "face_hole":
            notes.append(f"assoc {ref.uid}: unsupported kind {ref.kind!r}")
            continue
        target = by_uid.get(ref.target_uid)
        source = by_uid.get(ref.source_uid)
        if target is None or source is None:
            notes.append(f"assoc {ref.uid}: missing panel")
            continue
        hole = compute_face_hole(target, source, ref)
        if hole is None:
            notes.append(f"assoc {ref.uid}: compute failed")
            continue
        tagged = tag_assoc_hole(hole, ref.uid)
        target.holes.append(tagged)
        amap = getattr(target, "assoc_hole_map", None)
        if amap is None:
            target.assoc_hole_map = {}
            amap = target.assoc_hole_map
        amap.setdefault(ref.uid, []).append(tagged)

    if rebuild_geometry:
        for p in panels:
            cur = [hole_geometry(h) for h in (getattr(p, "holes", []) or []) if len(h) >= 6]
            old = old_holes_by_id.get(id(p), [])
            if len(cur) != len(old) or any(not holes_equal(a, b) for a, b in zip(cur, old)):
                p._gl_arrays = None
                if hasattr(p, "rebuild_geometry"):
                    p.rebuild_geometry()

    return notes
