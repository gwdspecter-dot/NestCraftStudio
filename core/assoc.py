# -*- coding: utf-8 -*-
"""Ассоциативные ссылки: feature (отверстие) привязан к геометрии соседней панели.

Модель сознательно зеркалит JointRecord / apply_joints и развивает паттерн
SolidCraft ``face-attachments.md``:
- записи живут на Block (``block.assoc_refs``);
- отверстия, порождённые ссылкой, помечаются 7-м полем (``a:<uid>``);
- ручные отверстия и отверстия JointRecord не трогаются;
- поддерживаются якоря на грани (``center`` и 4 угла ``min_min``…``max_max``),
  отпечаток грани ``face_hint`` (обнаружение поворота/дрейфа грани),
  режим заморозки ``fixed=True`` (локальные координаты на target без зависимости от source),
  единая диагностика ``AssocAttachmentStatus`` и восстановление (заморозка / авто-подбор грани).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any
from uuid import uuid4

import numpy as np

from core.logging_setup import get_logger

_log = get_logger("assoc")

# Имена граней в локальных осях панели (нормаль наружу от объёма).
FACE_NAMES = ("X+", "X-", "Y+", "Y-", "Z+", "Z-")

# Режимы опорной точки (якоря) на грани source-панели.
ANCHOR_MODES = ("center", "min_min", "max_min", "min_max", "max_max")
ANCHOR_LABELS = {
    "center": "Центр грани",
    "min_min": "Угол (u⁻, v⁻)",
    "max_min": "Угол (u⁺, v⁻)",
    "min_max": "Угол (u⁻, v⁺)",
    "max_max": "Угол (u⁺, v⁺)",
}

# Допуски диагностики привязки к грани (мм / градусы)
FACE_BOUNDS_TOL_MM = 1.5
TARGET_BOUNDS_TOL_MM = 1.5
FACE_DRIFT_ANGLE_DEG = 15.0

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


def _norm_anchor(name: str | None) -> str:
    key = str(name or "center").strip().lower()
    return key if key in ANCHOR_MODES else "center"


def _norm_vec3_tuple(raw: Any) -> tuple[float, float, float] | None:
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        vals = (float(raw[0]), float(raw[1]), float(raw[2]))
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(x) for x in vals):
        return None
    return vals


def panel_face_extents(panel, face: str) -> tuple[float, float]:
    """Габариты `(u_span, v_span)` выбранной грани панели в миллиметрах."""
    face = _norm_face(face)
    ax = _FACE_AXIS[face]
    dims = (
        abs(float(panel.width)),
        abs(float(panel.height)),
        abs(float(panel.depth)),
    )
    other = [i for i in (0, 1, 2) if i != ax]
    return float(dims[other[0]]), float(dims[other[1]])


def face_anchor_offset(u_span: float, v_span: float, anchor: str = "center") -> tuple[float, float]:
    """Смещение `(du, dv)` от центра грани до выбранного якоря."""
    mode = _norm_anchor(anchor)
    hu = 0.5 * abs(float(u_span))
    hv = 0.5 * abs(float(v_span))
    if mode == "min_min":
        return (-hu, -hv)
    if mode == "max_min":
        return (hu, -hv)
    if mode == "min_max":
        return (-hu, hv)
    if mode == "max_max":
        return (hu, hv)
    return (0.0, 0.0)


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


def face_point_world(
    panel,
    face: str,
    u: float,
    v: float,
    *,
    anchor: str = "center",
) -> np.ndarray:
    """Мировая точка: якорь грани (по умолчанию центр) + u * u_axis + v * v_axis."""
    origin, _n, u_axis, v_axis = panel_face_frame(panel, face)
    u_span, v_span = panel_face_extents(panel, face)
    au, av = face_anchor_offset(u_span, v_span, anchor)
    return origin + (au + float(u)) * u_axis + (av + float(v)) * v_axis


def capture_face_hint(source, face: str) -> dict[str, Any] | None:
    """Снимает компактный геометрический отпечаток грани source (нормаль, центр, габариты).

    Используется для обнаружения дрейфа грани после поворота детали и для авто-перепривязки.
    """
    if source is None:
        return None
    try:
        origin, normal, _ua, _va = panel_face_frame(source, face)
        u_span, v_span = panel_face_extents(source, face)
    except (ValueError, AttributeError) as exc:
        _log.debug("capture_face_hint failed: %s", exc)
        return None
    return {
        "normal": [round(float(normal[0]), 5), round(float(normal[1]), 5), round(float(normal[2]), 5)],
        "origin": [round(float(origin[0]), 3), round(float(origin[1]), 3), round(float(origin[2]), 3)],
        "extents": [round(float(u_span), 3), round(float(v_span), 3)],
    }


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
      ``inset`` (смещение вдоль нормали грани в сторону target, мм);
    - ``anchor``: опорная точка на грани (``center``, ``min_min``, ``max_min``, ``min_max``, ``max_max``);
    - ``fixed``: режим заморозки (``fixed:true`` из face-attachments.md) — позиция берётся
      из ``fixed_local`` на target и не ломается при сдвиге/удалении source;
    - ``fixed_local`` / ``fixed_axis``: замороженные локальные координаты и ось отверстия;
    - ``face_hint``: опциональный отпечаток мировой нормали/центра грани для диагностики дрейфа.
    """

    uid: str = ""
    kind: str = "face_hole"
    target_uid: str = ""
    source_uid: str = ""
    source_face: str = "Z+"
    params: dict[str, Any] = field(default_factory=dict)
    anchor: str = "center"
    fixed: bool = False
    fixed_local: tuple[float, float, float] | None = None
    fixed_axis: str | None = None
    face_hint: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.uid = str(self.uid or "").strip() or str(uuid4())
        self.kind = str(self.kind or "face_hole").strip() or "face_hole"
        self.target_uid = str(self.target_uid or "").strip()
        self.source_uid = str(self.source_uid or "").strip()
        try:
            self.source_face = _norm_face(self.source_face)
        except ValueError:
            self.source_face = "Z+"
        self.anchor = _norm_anchor(self.anchor)
        self.fixed = bool(self.fixed)
        self.fixed_local = _norm_vec3_tuple(self.fixed_local)
        if self.fixed_axis is not None:
            fax = str(self.fixed_axis).strip().upper()
            self.fixed_axis = fax if fax in ("X", "Y", "Z") else None
        if isinstance(self.face_hint, dict):
            n_hint = _norm_vec3_tuple(self.face_hint.get("normal"))
            if n_hint is not None:
                clean_hint: dict[str, Any] = {"normal": list(n_hint)}
                o_hint = _norm_vec3_tuple(self.face_hint.get("origin"))
                if o_hint is not None:
                    clean_hint["origin"] = list(o_hint)
                ext = self.face_hint.get("extents")
                if isinstance(ext, (list, tuple)) and len(ext) >= 2:
                    try:
                        eu, ev = float(ext[0]), float(ext[1])
                        if math.isfinite(eu) and math.isfinite(ev):
                            clean_hint["extents"] = [eu, ev]
                    except (TypeError, ValueError) as exc:
                        _log.debug("Invalid face_hint extents ignored: %s", exc)
                self.face_hint = clean_hint
            else:
                self.face_hint = None
        else:
            self.face_hint = None

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
        out: dict[str, Any] = {
            "uid": str(self.uid),
            "kind": str(self.kind),
            "target_uid": str(self.target_uid),
            "source_uid": str(self.source_uid),
            "source_face": str(self.source_face),
            "params": dict(self.params),
        }
        if self.anchor != "center":
            out["anchor"] = str(self.anchor)
        if self.fixed:
            out["fixed"] = True
            if self.fixed_local is not None:
                out["fixed_local"] = [
                    float(self.fixed_local[0]),
                    float(self.fixed_local[1]),
                    float(self.fixed_local[2]),
                ]
            if self.fixed_axis in ("X", "Y", "Z"):
                out["fixed_axis"] = str(self.fixed_axis)
        if self.face_hint is not None:
            out["face_hint"] = dict(self.face_hint)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | "AssocRef") -> "AssocRef":
        if isinstance(data, AssocRef):
            return cls(
                uid=data.uid,
                kind=data.kind,
                target_uid=data.target_uid,
                source_uid=data.source_uid,
                source_face=data.source_face,
                params=dict(data.params),
                anchor=data.anchor,
                fixed=data.fixed,
                fixed_local=data.fixed_local,
                fixed_axis=data.fixed_axis,
                face_hint=dict(data.face_hint) if isinstance(data.face_hint, dict) else None,
            )
        return cls(
            uid=str(data.get("uid") or ""),
            kind=str(data.get("kind") or "face_hole"),
            target_uid=str(data.get("target_uid") or ""),
            source_uid=str(data.get("source_uid") or ""),
            source_face=str(data.get("source_face") or "Z+"),
            params=dict(data.get("params") or {}) if isinstance(data.get("params"), dict) else {},
            anchor=str(data.get("anchor") or "center"),
            fixed=bool(data.get("fixed", False)),
            fixed_local=_norm_vec3_tuple(data.get("fixed_local")),
            fixed_axis=data.get("fixed_axis"),
            face_hint=dict(data["face_hint"]) if isinstance(data.get("face_hint"), dict) else None,
        )

    def clone(self, *, new_id: bool = True) -> "AssocRef":
        return AssocRef(
            uid="" if new_id else self.uid,
            kind=self.kind,
            target_uid=self.target_uid,
            source_uid=self.source_uid,
            source_face=self.source_face,
            params=dict(self.params),
            anchor=self.anchor,
            fixed=self.fixed,
            fixed_local=self.fixed_local,
            fixed_axis=self.fixed_axis,
            face_hint=dict(self.face_hint) if isinstance(self.face_hint, dict) else None,
        )


@dataclass(frozen=True)
class AssocAttachmentStatus:
    """Типизированная диагностика состояния привязки ``AssocRef`` (паттерн face-attachments.md)."""

    state: str
    severity: str  # "ok" | "warning" | "error"
    code: str
    message: str
    remedy: str = ""
    hole: tuple | None = None
    world_point: tuple[float, float, float] | None = None
    suggested_face: str | None = None
    drift_angle_deg: float = 0.0
    outside_mm: float = 0.0

    @property
    def is_healthy(self) -> bool:
        return self.severity == "ok"


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
    """Считает локальное отверстие на target по грани source (или из fixed_local при fixed=True)."""
    if target is None or ref is None:
        return None
    if ref.kind != "face_hole":
        return None

    diameter = float(ref.params.get("diameter") or 5.0)
    depth = float(ref.params.get("depth") or 12.0)
    if diameter <= 0.0 or depth <= 0.0:
        return None
    radius = float(diameter) * 0.5

    if ref.fixed:
        if ref.fixed_local is None:
            return None
        lx, ly, lz = ref.fixed_local
        axis = ref.params.get("axis") or ref.fixed_axis or "Z"
        if axis not in ("X", "Y", "Z"):
            axis = "Z"
        return (float(lx), float(ly), float(lz), float(radius), float(depth), str(axis))

    if source is None:
        return None
    if str(getattr(target, "uid", "")) == str(getattr(source, "uid", "")):
        return None

    u = float(ref.params.get("u") or 0.0)
    v = float(ref.params.get("v") or 0.0)
    inset = float(ref.params.get("inset") or 0.0)

    try:
        _origin, normal, _ua, _va = panel_face_frame(source, ref.source_face)
        world_pt = face_point_world(source, ref.source_face, u, v, anchor=ref.anchor)
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
            n_end = world_pt + normal
            nx, ny, nz = target.world_to_local(float(n_end[0]), float(n_end[1]), float(n_end[2]))
            local_n = np.array([nx - lx, ny - ly, nz - lz], dtype=float)
            axis = _axis_from_normal(local_n)
        except Exception as exc:  # noqa: BLE001
            _log.debug("local normal projection failed for assoc %s: %s", ref.uid, exc)
            axis = _axis_from_normal(normal)

    # Радиус в формате holes NestCraft (поле [3] — radius, не diameter)
    return (float(lx), float(ly), float(lz), float(radius), float(depth), str(axis))


def _panel_world_center(panel) -> np.ndarray:
    if hasattr(panel, "local_to_world"):
        cx, cy, cz = panel.local_to_world(
            float(panel.width) * 0.5,
            float(panel.height) * 0.5,
            float(panel.depth) * 0.5,
        )
        return np.array([float(cx), float(cy), float(cz)], dtype=float)
    return np.array(
        [
            float(panel.x) + float(panel.width) * 0.5,
            float(panel.y) + float(panel.height) * 0.5,
            float(panel.z) + float(panel.depth) * 0.5,
        ],
        dtype=float,
    )


def _target_outside_distance_mm(target, lx: float, ly: float, lz: float) -> float:
    """Расстояние (мм) от локальной точки `(lx, ly, lz)` до объёма target (0.0, если внутри)."""
    tw = abs(float(getattr(target, "width", 0.0)))
    th = abs(float(getattr(target, "height", 0.0)))
    td = abs(float(getattr(target, "depth", 0.0)))
    ox = max(0.0, -float(lx), float(lx) - tw)
    oy = max(0.0, -float(ly), float(ly) - th)
    oz = max(0.0, -float(lz), float(lz) - td)
    return math.sqrt(ox * ox + oy * oy + oz * oz)


def suggest_rebind_face(target, source, ref: AssocRef | None = None) -> str | None:
    """Подбирает наиболее подходящую грань ``source`` для перепривязки к ``target``.

    1. Если в ``ref.face_hint`` сохранена исходная мировая нормаль (например, после
       поворота панели source), сначала ищется грань с той же мировой ориентацией (dot > 0.92).
    2. Иначе выбирается грань ``source``, обращённая к ``target`` с минимальным расстоянием
       до центра/объёма ``target``.
    """
    if target is None or source is None:
        return None
    if str(getattr(target, "uid", "")) == str(getattr(source, "uid", "")):
        return None

    # 1. Приоритет: сохранение мировой ориентации грани по face_hint
    if ref is not None and isinstance(ref.face_hint, dict):
        hint_n = _norm_vec3_tuple(ref.face_hint.get("normal"))
        if hint_n is not None:
            hn = np.array(hint_n, dtype=float)
            hn_len = float(np.linalg.norm(hn))
            if hn_len > 1e-9:
                hn = hn / hn_len
                best_hint_face: str | None = None
                best_hint_dot = -2.0
                for fname in FACE_NAMES:
                    try:
                        _o, n, _ua, _va = panel_face_frame(source, fname)
                    except (ValueError, AttributeError):
                        continue
                    dot = float(np.dot(n, hn))
                    if dot > best_hint_dot:
                        best_hint_dot = dot
                        best_hint_face = fname
                if best_hint_face is not None and best_hint_dot > 0.92:
                    return best_hint_face

    # 2. Геометрический подбор ближайшей грани source, обращённой к target
    tgt_c = _panel_world_center(target)
    best_face: str | None = None
    best_score = float("inf")
    for fname in FACE_NAMES:
        try:
            origin, normal, _ua, _va = panel_face_frame(source, fname)
        except (ValueError, AttributeError):
            continue
        delta = tgt_c - origin
        dist = float(np.linalg.norm(delta))
        signed = float(np.dot(delta, normal))
        # Предпочитаем грани, нормаль которых смотрит в сторону target (signed >= -1 мм)
        facing_penalty = 0.0 if signed >= -1.0 else (abs(signed) * 4.0 + 1000.0)
        score = dist + facing_penalty
        if score < best_score:
            best_score = score
            best_face = fname
    return best_face


def evaluate_assoc_ref_panels(target, source, ref: AssocRef) -> AssocAttachmentStatus:
    """Оценивает здоровье привязки ``ref`` по конкретным панелям ``target`` и ``source``."""
    if ref is None:
        return AssocAttachmentStatus(
            state="broken_invalid_params",
            severity="error",
            code="assoc_invalid",
            message="Пустая ассоциативная ссылка",
            remedy="Удалите некорректную запись",
        )

    tgt_name = str(getattr(target, "name", "") or (ref.target_uid or "?")[:8]) if target is not None else (ref.target_uid or "?")[:8]
    src_name = str(getattr(source, "name", "") or (ref.source_uid or "?")[:8]) if source is not None else (ref.source_uid or "?")[:8]

    if ref.kind != "face_hole":
        return AssocAttachmentStatus(
            state="broken_invalid_params",
            severity="error",
            code="assoc_invalid",
            message=f"Ассоциация «{tgt_name}»: неподдерживаемый тип {ref.kind!r}",
            remedy="Удалите или пересоздайте ассоциацию",
        )

    diameter = float(ref.params.get("diameter") or 0.0)
    depth = float(ref.params.get("depth") or 0.0)
    if diameter <= 0.0 or depth <= 0.0:
        return AssocAttachmentStatus(
            state="broken_invalid_params",
            severity="error",
            code="assoc_invalid",
            message=f"Ассоциация «{tgt_name}»: диаметр ({diameter:g}) и глубина ({depth:g}) должны быть > 0",
            remedy="Укажите корректные Ø и глубину отверстия",
        )

    # --- Режим заморозки (fixed: true) ---
    if ref.fixed:
        if target is None:
            return AssocAttachmentStatus(
                state="broken_missing_panel",
                severity="error",
                code="assoc_panel_missing",
                message=f"Зафиксированная ассоциация ссылается на удалённую деталь target ({tgt_name})",
                remedy="Удалите ссылку или перепривяжите её к существующей детали",
            )
        hole = compute_face_hole(target, source, ref)
        if hole is None:
            return AssocAttachmentStatus(
                state="broken_invalid_params",
                severity="error",
                code="assoc_invalid",
                message=f"Ассоциация «{tgt_name}» (фикс.): отсутствуют зафиксированные локальные координаты",
                remedy="Нажмите «Привязать» и пересоздайте фиксацию",
            )
        lx, ly, lz = float(hole[0]), float(hole[1]), float(hole[2])
        wx, wy, wz = target.local_to_world(lx, ly, lz)
        wpt = (float(wx), float(wy), float(wz))
        out_mm = _target_outside_distance_mm(target, lx, ly, lz)
        if out_mm > TARGET_BOUNDS_TOL_MM:
            return AssocAttachmentStatus(
                state="out_of_target",
                severity="warning",
                code="assoc_out_of_target",
                message=(
                    f"Зафиксированное отверстие на «{tgt_name}» вышло за пределы детали "
                    f"на {out_mm:.1f} мм"
                ),
                remedy="Откройте «Правка…» или перепривяжите отверстие к грани",
                hole=hole,
                world_point=wpt,
                outside_mm=out_mm,
            )
        return AssocAttachmentStatus(
            state="fixed",
            severity="ok",
            code="",
            message=f"Зафиксировано на «{tgt_name}» ({lx:.1f}, {ly:.1f}, {lz:.1f} мм) — не зависит от source",
            remedy="Нажмите «Привязать», чтобы вернуть слежение за гранью",
            hole=hole,
            world_point=wpt,
        )

    # --- Живая привязка к грани source ---
    if target is None or source is None:
        missing = []
        if target is None:
            missing.append(f"target ({tgt_name})")
        if source is None:
            missing.append(f"source ({src_name})")
        return AssocAttachmentStatus(
            state="broken_missing_panel",
            severity="error",
            code="assoc_panel_missing",
            message=f"Ассоциация ссылается на удалённую деталь: {', '.join(missing)}",
            remedy="Зафиксируйте отверстие (Fixed), перепривяжите в «Правка…» или удалите ссылку",
        )

    if str(getattr(target, "uid", "")) == str(getattr(source, "uid", "")):
        return AssocAttachmentStatus(
            state="broken_same_panel",
            severity="error",
            code="assoc_invalid",
            message=f"Ассоциация «{tgt_name}»: target и source совпадают",
            remedy="Выберите разные детали в «Правка…»",
        )

    hole = compute_face_hole(target, source, ref)
    if hole is None:
        return AssocAttachmentStatus(
            state="broken_invalid_params",
            severity="error",
            code="assoc_invalid",
            message=f"Ассоциация «{tgt_name} ← {src_name}.{ref.source_face}»: не удалось вычислить отверстие",
            remedy="Проверьте параметры грани и размеры детали",
        )

    lx, ly, lz = float(hole[0]), float(hole[1]), float(hole[2])
    wx, wy, wz = target.local_to_world(lx, ly, lz)
    wpt = (float(wx), float(wy), float(wz))

    origin, normal, _ua, _va = panel_face_frame(source, ref.source_face)
    u_span, v_span = panel_face_extents(source, ref.source_face)

    # 1. Проверка дрейфа ориентации грани относительно сохранённого face_hint
    if isinstance(ref.face_hint, dict):
        hint_n = _norm_vec3_tuple(ref.face_hint.get("normal"))
        if hint_n is not None:
            hn = np.array(hint_n, dtype=float)
            hn_len = float(np.linalg.norm(hn))
            if hn_len > 1e-9:
                dot = max(-1.0, min(1.0, float(np.dot(normal, hn / hn_len))))
                angle_deg = math.degrees(math.acos(dot))
                if angle_deg > FACE_DRIFT_ANGLE_DEG:
                    sug = suggest_rebind_face(target, source, ref)
                    remedy = (
                        f"Нажмите «Подобрать грань» (рекомендуется {sug}) или «Зафиксировать»"
                        if sug and sug != ref.source_face
                        else "Перепривяжите грань в «Правка…» или зафиксируйте позицию (Fixed)"
                    )
                    return AssocAttachmentStatus(
                        state="face_drifted",
                        severity="warning",
                        code="assoc_face_drifted",
                        message=(
                            f"Ассоциация «{tgt_name} ← {src_name}.{ref.source_face}»: "
                            f"грань повернулась на {angle_deg:.0f}° от исходной ориентации"
                        ),
                        remedy=remedy,
                        hole=hole,
                        world_point=wpt,
                        suggested_face=sug,
                        drift_angle_deg=angle_deg,
                    )

    # 2. Проверка выхода (u, v) за габариты грани source
    u = float(ref.params.get("u") or 0.0)
    v = float(ref.params.get("v") or 0.0)
    au, av = face_anchor_offset(u_span, v_span, ref.anchor)
    cu = au + u
    cv = av + v
    src_over = max(
        0.0,
        abs(cu) - 0.5 * u_span,
        abs(cv) - 0.5 * v_span,
    )
    if src_over > FACE_BOUNDS_TOL_MM:
        return AssocAttachmentStatus(
            state="out_of_source_face",
            severity="warning",
            code="assoc_out_of_source_face",
            message=(
                f"Ассоциация «{tgt_name} ← {src_name}.{ref.source_face}»: "
                f"точка (u={u:g}, v={v:g}) вышла за пределы грани на {src_over:.1f} мм"
            ),
            remedy="Уменьшите u/v, смените якорь или зафиксируйте позицию (Fixed)",
            hole=hole,
            world_point=wpt,
            outside_mm=src_over,
        )

    # 3. Проверка выхода вычисленного отверстия за пределы объёма target
    tgt_over = _target_outside_distance_mm(target, lx, ly, lz)
    if tgt_over > TARGET_BOUNDS_TOL_MM:
        sug = suggest_rebind_face(target, source, ref)
        remedy = (
            f"Нажмите «Подобрать грань» ({sug}), поправьте u/v/inset или зафиксируйте (Fixed)"
            if sug and sug != ref.source_face
            else "Поправьте u/v/inset, смените грань или зафиксируйте позицию (Fixed)"
        )
        return AssocAttachmentStatus(
            state="out_of_target",
            severity="warning",
            code="assoc_out_of_target",
            message=(
                f"Ассоциация «{tgt_name} ← {src_name}.{ref.source_face}»: "
                f"отверстие вышло за пределы «{tgt_name}» на {tgt_over:.1f} мм"
            ),
            remedy=remedy,
            hole=hole,
            world_point=wpt,
            suggested_face=sug,
            outside_mm=tgt_over,
        )

    anchor_lbl = ANCHOR_LABELS.get(ref.anchor, ref.anchor)
    return AssocAttachmentStatus(
        state="ok",
        severity="ok",
        code="",
        message=f"Привязка активна: «{tgt_name}» ← «{src_name}.{ref.source_face}» ({anchor_lbl})",
        remedy="",
        hole=hole,
        world_point=wpt,
    )


def _resolve_assoc_scene_blocks(block, all_blocks=None) -> list:
    """Возвращает список блоков сцены для поиска панелей ассоциативных ссылок."""
    if isinstance(all_blocks, (list, tuple)) and all_blocks:
        seq = [b for b in all_blocks if b is not None]
        if block is not None and block not in seq:
            seq.append(block)
        return seq
    scene_blocks = getattr(block, "_scene_blocks", None) if block is not None else None
    if isinstance(scene_blocks, list) and scene_blocks and (block is None or block in scene_blocks):
        return [b for b in scene_blocks if b is not None]
    return [block] if block is not None else []


def _assoc_panels_by_uid(block, all_blocks=None) -> dict[str, Any]:
    by_uid: dict[str, Any] = {}
    for blk in _resolve_assoc_scene_blocks(block, all_blocks=all_blocks):
        for p in getattr(blk, "panels", None) or []:
            uid = str(getattr(p, "uid", "") or "")
            if uid:
                by_uid[uid] = p
    return by_uid


def evaluate_assoc_ref(block, ref: AssocRef, *, all_blocks=None) -> AssocAttachmentStatus:
    """Оценивает здоровье ``ref`` внутри блока или всей сцены (единый источник истины для UI и issues.py)."""
    if (block is None and not all_blocks) or ref is None:
        return evaluate_assoc_ref_panels(None, None, ref)
    by_uid = _assoc_panels_by_uid(block, all_blocks=all_blocks)
    target = by_uid.get(str(ref.target_uid or ""))
    source = by_uid.get(str(ref.source_uid or ""))
    return evaluate_assoc_ref_panels(target, source, ref)


def resolve_assoc_world_point(block, ref: AssocRef, *, all_blocks=None) -> tuple[float, float, float] | None:
    """Мировая 3D-точка превью для живой или замороженной (fixed=True) ассоциации."""
    st = evaluate_assoc_ref(block, ref, all_blocks=all_blocks)
    if st.world_point is not None:
        return st.world_point
    if (block is None and not all_blocks) or ref is None or ref.fixed:
        return None
    by_uid = _assoc_panels_by_uid(block, all_blocks=all_blocks)
    source = by_uid.get(str(ref.source_uid or ""))
    if source is None:
        return None
    try:
        u = float(ref.params.get("u") or 0.0)
        v = float(ref.params.get("v") or 0.0)
        inset = float(ref.params.get("inset") or 0.0)
        _o, normal, _ua, _va = panel_face_frame(source, ref.source_face)
        pt = face_point_world(source, ref.source_face, u, v, anchor=ref.anchor)
        if abs(inset) > 1e-9:
            pt = pt + (-inset) * normal
        return (float(pt[0]), float(pt[1]), float(pt[2]))
    except (ValueError, AttributeError) as exc:
        _log.debug("resolve_assoc_world_point failed for %s: %s", ref.uid, exc)
        return None


def freeze_assoc_ref_state(block, ref: AssocRef, *, all_blocks=None) -> dict[str, Any] | None:
    """Готовит новое состояние ``AssocRef`` в режиме ``fixed=True`` на текущей позиции отверстия.

    Даже если панель ``source`` уже удалена, пытается спасти последние координаты отверстия
    из ``target.holes`` / ``target.assoc_hole_map`` (паттерн ``fixed:true``).
    """
    if (block is None and not all_blocks) or ref is None:
        return None
    by_uid = _assoc_panels_by_uid(block, all_blocks=all_blocks)
    target = by_uid.get(str(ref.target_uid or ""))
    source = by_uid.get(str(ref.source_uid or ""))
    if target is None:
        return None

    hole = compute_face_hole(target, source, ref)
    if hole is None:
        # Фолбэк: пробуем восстановить координаты из уже существующего assoc-отверстия на target
        for h in list(getattr(target, "holes", []) or []):
            if hole_assoc_uid(h) == ref.uid and len(h) >= 6:
                hole = tuple(h[:6])
                break
    if hole is None:
        return None

    frozen = AssocRef.from_dict(ref.to_dict())
    frozen.fixed = True
    frozen.fixed_local = (float(hole[0]), float(hole[1]), float(hole[2]))
    frozen.fixed_axis = str(hole[5]) if str(hole[5]) in ("X", "Y", "Z") else "Z"
    return frozen.to_dict()


def unfreeze_assoc_ref_state(block, ref: AssocRef, *, all_blocks=None) -> dict[str, Any] | None:
    """Снимает заморозку ``fixed=False``, проецируя зафиксированную точку на ``source_face`` без скачка."""
    if (block is None and not all_blocks) or ref is None:
        return None
    by_uid = _assoc_panels_by_uid(block, all_blocks=all_blocks)
    target = by_uid.get(str(ref.target_uid or ""))
    source = by_uid.get(str(ref.source_uid or ""))
    if target is None or source is None:
        return None

    live = AssocRef.from_dict(ref.to_dict())
    live.fixed = False

    # Если есть замороженная точка — пересчитываем u/v/inset на грани source, чтобы отверстие не прыгало
    if ref.fixed_local is not None:
        try:
            wx, wy, wz = target.local_to_world(*ref.fixed_local)
            wpt = np.array([float(wx), float(wy), float(wz)], dtype=float)
            origin, normal, u_axis, v_axis = panel_face_frame(source, live.source_face)
            u_span, v_span = panel_face_extents(source, live.source_face)
            au, av = face_anchor_offset(u_span, v_span, live.anchor)
            rel = wpt - origin
            live.params["u"] = round(float(np.dot(rel, u_axis)) - au, 3)
            live.params["v"] = round(float(np.dot(rel, v_axis)) - av, 3)
            live.params["inset"] = round(-float(np.dot(rel, normal)), 3)
        except Exception as exc:  # noqa: BLE001
            _log.debug("unfreeze projection failed for assoc %s: %s", ref.uid, exc)

    live.fixed_local = None
    live.fixed_axis = None
    live.face_hint = capture_face_hint(source, live.source_face)
    return live.to_dict()


def rebind_assoc_ref_state(
    block,
    ref: AssocRef,
    new_face: str | None = None,
    *,
    all_blocks=None,
) -> dict[str, Any] | None:
    """Перепривязывает ``AssocRef`` к актуальной грани ``source`` и обновляет ``face_hint``.

    Если прежнее отверстие уже вышло за пределы ``target``, дополнительно подбирает
    ``(u, v, inset)`` проекцией центра ``target`` (с обрезкой по грани ``source``),
    чтобы отверстие сразу легло в рабочую зону детали.
    """
    if (block is None and not all_blocks) or ref is None:
        return None
    by_uid = _assoc_panels_by_uid(block, all_blocks=all_blocks)
    target = by_uid.get(str(ref.target_uid or ""))
    source = by_uid.get(str(ref.source_uid or ""))
    if target is None or source is None:
        return None

    chosen = _norm_face(new_face) if new_face else suggest_rebind_face(target, source, ref)
    if not chosen:
        return None

    old_status = evaluate_assoc_ref_panels(target, source, ref)
    rebound = AssocRef.from_dict(ref.to_dict())
    rebound.source_face = chosen
    rebound.fixed = False
    rebound.fixed_local = None
    rebound.fixed_axis = None
    rebound.face_hint = capture_face_hint(source, chosen)

    # Проверяем, валидна ли перепривязанная точка при прежних u/v/inset; если нет — проецируем центр target
    new_status = evaluate_assoc_ref_panels(target, source, rebound)
    if new_status.state in ("out_of_target", "out_of_source_face") or (
        old_status.state == "face_drifted" and new_status.state != "ok"
    ):
        try:
            origin, normal, u_axis, v_axis = panel_face_frame(source, chosen)
            u_span, v_span = panel_face_extents(source, chosen)
            au, av = face_anchor_offset(u_span, v_span, rebound.anchor)
            # Если раньше точка была валидна на target — сохраняем её, иначе проецируем центр target
            if old_status.world_point is not None and old_status.state not in ("out_of_target",):
                anchor_pt = np.array(old_status.world_point, dtype=float)
            else:
                anchor_pt = _panel_world_center(target)
            rel = anchor_pt - origin
            cu = max(-0.5 * u_span, min(0.5 * u_span, float(np.dot(rel, u_axis))))
            cv = max(-0.5 * v_span, min(0.5 * v_span, float(np.dot(rel, v_axis))))
            rebound.params["u"] = round(cu - au, 3)
            rebound.params["v"] = round(cv - av, 3)
            rebound.params["inset"] = round(-float(np.dot(rel, normal)), 3)
        except Exception as exc:  # noqa: BLE001
            _log.debug("rebind auto-projection failed for assoc %s: %s", ref.uid, exc)

    return rebound.to_dict()


def apply_assoc_refs_in_blocks(blocks, *, rebuild_geometry: bool = True) -> list:
    """Пересчитывает ассоциативные отверстия по всем блокам сцены (включая межблочные)."""
    scene_blocks = [b for b in (blocks or []) if b is not None]
    if not scene_blocks:
        return []

    from core.joint import (
        extract_manual_holes,
        hole_geometry,
        hole_joint_uid,
        holes_equal,
    )

    panels: list = []
    seen_panel_ids: set[int] = set()
    all_refs: list[AssocRef] = []

    for blk in scene_blocks:
        raw_refs = list(getattr(blk, "assoc_refs", []) or [])
        norm_refs: list[AssocRef] = []
        for item in raw_refs:
            if isinstance(item, AssocRef):
                norm_refs.append(item)
            elif isinstance(item, dict):
                norm_refs.append(AssocRef.from_dict(item))
        blk.assoc_refs = norm_refs
        all_refs.extend(norm_refs)

        for p in list(getattr(blk, "panels", []) or []):
            if id(p) in seen_panel_ids:
                continue
            seen_panel_ids.add(id(p))
            try:
                p._block = blk
            except Exception as exc:  # noqa: BLE001
                _log.debug("Could not bind _block on panel: %s", exc)
            panels.append(p)

    old_holes_by_id: dict[int, list[tuple]] = {}
    for p in panels:
        old_holes_by_id[id(p)] = [
            hole_geometry(h) for h in (getattr(p, "holes", []) or []) if len(h) >= 6
        ]

        # Надёжный путь: взять manual через joint-helper, затем добавить joint-отверстия из map/tag
        manual = extract_manual_holes(p)
        jmap = getattr(p, "joint_hole_map", None) or {}
        joint_from_map: list[tuple] = []
        for hlist in jmap.values():
            for jh in hlist or []:
                if len(jh) >= 6:
                    joint_from_map.append(tuple(jh) if len(jh) >= 7 else hole_geometry(jh))
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
    for ref in all_refs:
        target = by_uid.get(ref.target_uid)
        source = by_uid.get(ref.source_uid)
        st = evaluate_assoc_ref_panels(target, source, ref)
        if st.severity != "ok":
            notes.append(st.message)
        if st.hole is None or target is None:
            continue
        tagged = tag_assoc_hole(st.hole, ref.uid)
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


def apply_assoc_refs(block, *, rebuild_geometry: bool = True, all_blocks=None) -> list:
    """Пересчитывает отверстия из ``block.assoc_refs`` (с поддержкой межблочных ссылок)."""
    if block is None and not all_blocks:
        return []
    scene_blocks = _resolve_assoc_scene_blocks(block, all_blocks=all_blocks)
    return apply_assoc_refs_in_blocks(scene_blocks, rebuild_geometry=rebuild_geometry)

