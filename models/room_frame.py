"""Параметрическая модель габаритной рамки помещения и рабочего пространства «Помещение».

Система координат совпадает с принятой в NestCraft Studio:
- X — ширина (слева направо);
- Y — высота (от пола к потолку);
- Z — глубина (сзади вперёд; 2D-план помещения строится в плоскости XZ).

Модуль не зависит от PyQt6 и OpenGL и не изменяет семантику `BoundingFrame`
отдельного мебельного изделия: каждое размещённое в помещении изделие хранит
собственную габаритную рамку и локальную структуру блоков/панелей отдельно от
трансформации размещения в помещении.
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from models.bounding_frame import BoundingFrame

# ── Константы и допуски помещения ─────────────────────────────

DEFAULT_ROOM_WIDTH_MM: float = 3600.0
DEFAULT_ROOM_DEPTH_MM: float = 3000.0
DEFAULT_ROOM_HEIGHT_MM: float = 2700.0
DEFAULT_WALL_THICKNESS_MM: float = 120.0

MIN_WALL_LENGTH_MM: float = 50.0
MAX_WALL_LENGTH_MM: float = 100000.0
MIN_WALL_THICKNESS_MM: float = 10.0
MAX_WALL_THICKNESS_MM: float = 2000.0
MIN_WALL_HEIGHT_MM: float = 300.0
MAX_WALL_HEIGHT_MM: float = 20000.0
MAX_WALL_DEVIATION_MM: float = 500.0
WALL_DEVIATION_TOLERANCE_MM: float = 0.05

DEFAULT_ALLOWED_GAP_MM: float = 10.0
DEFAULT_COLLISION_TOLERANCE_MM: float = 0.5

OPENING_KINDS: tuple[str, ...] = ("door", "window", "passage")
OPENING_KIND_LABELS: dict[str, str] = {
    "door": "Дверь",
    "window": "Окно",
    "passage": "Проход",
}

SWING_DIRECTIONS: tuple[str, ...] = ("in_left", "in_right", "out_left", "out_right")
SWING_DIRECTION_LABELS: dict[str, str] = {
    "in_left": "Внутрь (левая)",
    "in_right": "Внутрь (правая)",
    "out_left": "Наружу (левая)",
    "out_right": "Наружу (правая)",
}

OBSTACLE_KINDS: tuple[str, ...] = (
    "column",
    "duct",
    "radiator",
    "pipe",
    "vent",
    "cabinet_tech",
    "ceiling_drop",
    "other",
)
OBSTACLE_KIND_LABELS: dict[str, str] = {
    "column": "Колонна",
    "duct": "Короб",
    "radiator": "Радиатор",
    "pipe": "Труба",
    "vent": "Вентиляция",
    "cabinet_tech": "Технический шкаф",
    "ceiling_drop": "Понижение потолка",
    "other": "Препятствие",
}


def new_room_uid(prefix: str = "rm") -> str:
    """Генерирует стабильный короткий уникальный идентификатор элемента помещения."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _finite_float(value: Any, label: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле «{label}» должно быть числом.") from exc
    if not math.isfinite(num):
        raise ValueError(f"Поле «{label}» должно быть конечным числом.")
    return num


def _bounded_float(
    value: Any,
    label: str,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
) -> float:
    num = _finite_float(value, label)
    if min_val is not None and num < min_val:
        raise ValueError(f"Поле «{label}» не может быть меньше {min_val:g}.")
    if max_val is not None and num > max_val:
        raise ValueError(f"Поле «{label}» не может превышать {max_val:g}.")
    return num


# ── Элементы геометрии помещения ──────────────────────────────


@dataclass
class RoomVertex:
    """Узел (вершина) контура помещения в 2D-плане XZ (мм)."""

    x: float
    z: float
    uid: str = field(default_factory=lambda: new_room_uid("vtx"))

    def __post_init__(self) -> None:
        self.x = _finite_float(self.x, "Координата X узла")
        self.z = _finite_float(self.z, "Координата Z узла")
        self.uid = str(self.uid or "").strip() or new_room_uid("vtx")

    def clone(self) -> "RoomVertex":
        return RoomVertex(x=self.x, z=self.z, uid=self.uid)

    def to_dict(self) -> dict[str, Any]:
        return {"uid": self.uid, "x": float(self.x), "z": float(self.z)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomVertex":
        return cls(
            x=data.get("x", 0.0),
            z=data.get("z", 0.0),
            uid=str(data.get("uid") or new_room_uid("vtx")),
        )


@dataclass
class WallDeviationStation:
    """Контрольная точка (станция замера) отклонения внутренней поверхности стены.

    - `s_mm` — расстояние от начала стены вдоль её базовой линии (мм);
    - `height_mm` — высота точки замера от уровня пола (мм);
    - `offset_mm` — смещение поверхности вдоль внутренней нормали стены (мм):
      `> 0` — выпуклость / завал внутрь помещения, `< 0` — вогнутость / отклонение наружу.
    """

    s_mm: float
    height_mm: float
    offset_mm: float
    uid: str = field(default_factory=lambda: new_room_uid("dev"))

    def __post_init__(self) -> None:
        self.s_mm = _bounded_float(self.s_mm, "Позиция вдоль стены (s)", min_val=0.0)
        self.height_mm = _bounded_float(self.height_mm, "Высота замера", min_val=0.0)
        self.offset_mm = _bounded_float(
            self.offset_mm,
            "Отклонение поверхности",
            min_val=-MAX_WALL_DEVIATION_MM,
            max_val=MAX_WALL_DEVIATION_MM,
        )
        self.uid = str(self.uid or "").strip() or new_room_uid("dev")

    def clone(self) -> "WallDeviationStation":
        return WallDeviationStation(
            s_mm=self.s_mm,
            height_mm=self.height_mm,
            offset_mm=self.offset_mm,
            uid=self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "s_mm": float(self.s_mm),
            "height_mm": float(self.height_mm),
            "offset_mm": float(self.offset_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WallDeviationStation":
        return cls(
            s_mm=data.get("s_mm", 0.0),
            height_mm=data.get("height_mm", 0.0),
            offset_mm=data.get("offset_mm", 0.0),
            uid=str(data.get("uid") or new_room_uid("dev")),
        )


@dataclass
class WallOpening:
    """Проём в стене: дверь, окно или проход без двери."""

    kind: str = "door"  # "door" | "window" | "passage"
    offset_s_mm: float = 500.0
    width_mm: float = 900.0
    height_mm: float = 2050.0
    sill_height_mm: float = 0.0
    swing_dir: str = "in_left"
    swing_angle_deg: float = 90.0
    sill_depth_mm: float = 60.0
    name: str = ""
    uid: str = field(default_factory=lambda: new_room_uid("opn"))

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "door").strip().lower()
        if self.kind not in OPENING_KINDS:
            raise ValueError(
                f"Недопустимый тип проёма «{self.kind}». Доступно: {', '.join(OPENING_KINDS)}."
            )
        self.offset_s_mm = _bounded_float(self.offset_s_mm, "Положение проёма вдоль стены", min_val=0.0)
        self.width_mm = _bounded_float(self.width_mm, "Ширина проёма", min_val=50.0, max_val=20000.0)
        self.height_mm = _bounded_float(self.height_mm, "Высота проёма", min_val=50.0, max_val=15000.0)
        self.sill_height_mm = _bounded_float(
            self.sill_height_mm, "Высота от пола / подоконника", min_val=0.0, max_val=15000.0
        )
        self.swing_dir = str(self.swing_dir or "in_left").strip().lower()
        if self.swing_dir not in SWING_DIRECTIONS:
            self.swing_dir = "in_left"
        self.swing_angle_deg = _bounded_float(
            self.swing_angle_deg, "Угол открывания двери", min_val=0.0, max_val=180.0
        )
        self.sill_depth_mm = _bounded_float(
            self.sill_depth_mm, "Выступ подоконника", min_val=0.0, max_val=1000.0
        )
        self.uid = str(self.uid or "").strip() or new_room_uid("opn")
        self.name = str(self.name or "").strip() or OPENING_KIND_LABELS.get(self.kind, "Проём")

    def clone(self) -> "WallOpening":
        return WallOpening(
            kind=self.kind,
            offset_s_mm=self.offset_s_mm,
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            sill_height_mm=self.sill_height_mm,
            swing_dir=self.swing_dir,
            swing_angle_deg=self.swing_angle_deg,
            sill_depth_mm=self.sill_depth_mm,
            name=self.name,
            uid=self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "kind": self.kind,
            "name": self.name,
            "offset_s_mm": float(self.offset_s_mm),
            "width_mm": float(self.width_mm),
            "height_mm": float(self.height_mm),
            "sill_height_mm": float(self.sill_height_mm),
            "swing_dir": self.swing_dir,
            "swing_angle_deg": float(self.swing_angle_deg),
            "sill_depth_mm": float(self.sill_depth_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WallOpening":
        return cls(
            kind=data.get("kind", "door"),
            offset_s_mm=data.get("offset_s_mm", 500.0),
            width_mm=data.get("width_mm", 900.0),
            height_mm=data.get("height_mm", 2050.0),
            sill_height_mm=data.get("sill_height_mm", 0.0),
            swing_dir=data.get("swing_dir", "in_left"),
            swing_angle_deg=data.get("swing_angle_deg", 90.0),
            sill_depth_mm=data.get("sill_depth_mm", 60.0),
            name=str(data.get("name") or ""),
            uid=str(data.get("uid") or new_room_uid("opn")),
        )


@dataclass
class RoomWall:
    """Стена контура помещения между двумя вершинами `start_vertex_uid → end_vertex_uid`."""

    start_vertex_uid: str
    end_vertex_uid: str
    name: str = "Стена"
    thickness_mm: float = DEFAULT_WALL_THICKNESS_MM
    height_mm: float = DEFAULT_ROOM_HEIGHT_MM
    visible: bool = True
    deviation_stations: list[WallDeviationStation] = field(default_factory=list)
    openings: list[WallOpening] = field(default_factory=list)
    uid: str = field(default_factory=lambda: new_room_uid("wall"))

    def __post_init__(self) -> None:
        self.start_vertex_uid = str(self.start_vertex_uid or "").strip()
        self.end_vertex_uid = str(self.end_vertex_uid or "").strip()
        if not self.start_vertex_uid or not self.end_vertex_uid:
            raise ValueError("Стена должна ссылаться на начальный и конечный узлы.")
        if self.start_vertex_uid == self.end_vertex_uid:
            raise ValueError("Начальный и конечный узлы стены не могут совпадать.")
        self.name = str(self.name or "").strip() or "Стена"
        self.thickness_mm = _bounded_float(
            self.thickness_mm,
            "Толщина стены",
            min_val=MIN_WALL_THICKNESS_MM,
            max_val=MAX_WALL_THICKNESS_MM,
        )
        self.height_mm = _bounded_float(
            self.height_mm,
            "Высота стены",
            min_val=MIN_WALL_HEIGHT_MM,
            max_val=MAX_WALL_HEIGHT_MM,
        )
        self.visible = bool(self.visible)
        self.deviation_stations = [
            st if isinstance(st, WallDeviationStation) else WallDeviationStation.from_dict(st)
            for st in (self.deviation_stations or [])
        ]
        self.openings = [
            op if isinstance(op, WallOpening) else WallOpening.from_dict(op)
            for op in (self.openings or [])
        ]
        self.uid = str(self.uid or "").strip() or new_room_uid("wall")

    def clone(self) -> "RoomWall":
        return RoomWall(
            start_vertex_uid=self.start_vertex_uid,
            end_vertex_uid=self.end_vertex_uid,
            name=self.name,
            thickness_mm=self.thickness_mm,
            height_mm=self.height_mm,
            visible=self.visible,
            deviation_stations=[st.clone() for st in self.deviation_stations],
            openings=[op.clone() for op in self.openings],
            uid=self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "start_vertex_uid": self.start_vertex_uid,
            "end_vertex_uid": self.end_vertex_uid,
            "name": self.name,
            "thickness_mm": float(self.thickness_mm),
            "height_mm": float(self.height_mm),
            "visible": bool(self.visible),
            "deviation_stations": [st.to_dict() for st in self.deviation_stations],
            "openings": [op.to_dict() for op in self.openings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomWall":
        return cls(
            start_vertex_uid=str(data.get("start_vertex_uid") or ""),
            end_vertex_uid=str(data.get("end_vertex_uid") or ""),
            name=str(data.get("name") or "Стена"),
            thickness_mm=data.get("thickness_mm", DEFAULT_WALL_THICKNESS_MM),
            height_mm=data.get("height_mm", DEFAULT_ROOM_HEIGHT_MM),
            visible=bool(data.get("visible", True)),
            deviation_stations=[
                WallDeviationStation.from_dict(st)
                for st in (data.get("deviation_stations") or [])
                if isinstance(st, dict)
            ],
            openings=[
                WallOpening.from_dict(op)
                for op in (data.get("openings") or [])
                if isinstance(op, dict)
            ],
            uid=str(data.get("uid") or new_room_uid("wall")),
        )


@dataclass
class RoomObstacle:
    """Универсальное препятствие / инженерный элемент в помещении."""

    kind: str = "column"
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    width: float = 300.0
    height: float = 2700.0
    depth: float = 300.0
    rotation_y_deg: float = 0.0
    clearance_mm: float = 0.0
    visible: bool = True
    uid: str = field(default_factory=lambda: new_room_uid("obs"))

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "other").strip().lower()
        if self.kind not in OBSTACLE_KINDS:
            self.kind = "other"
        self.name = str(self.name or "").strip() or OBSTACLE_KIND_LABELS.get(self.kind, "Препятствие")
        self.x = _finite_float(self.x, "Позиция X препятствия")
        self.y = _finite_float(self.y, "Позиция Y препятствия")
        self.z = _finite_float(self.z, "Позиция Z препятствия")
        self.width = _bounded_float(self.width, "Ширина препятствия", min_val=10.0, max_val=50000.0)
        self.height = _bounded_float(self.height, "Высота препятствия", min_val=10.0, max_val=20000.0)
        self.depth = _bounded_float(self.depth, "Глубина препятствия", min_val=10.0, max_val=50000.0)
        self.rotation_y_deg = _finite_float(self.rotation_y_deg, "Поворот препятствия")
        self.clearance_mm = _bounded_float(self.clearance_mm, "Зона запрета / зазор", min_val=0.0, max_val=5000.0)
        self.visible = bool(self.visible)
        self.uid = str(self.uid or "").strip() or new_room_uid("obs")

    def clone(self) -> "RoomObstacle":
        return RoomObstacle(
            kind=self.kind,
            name=self.name,
            x=self.x,
            y=self.y,
            z=self.z,
            width=self.width,
            height=self.height,
            depth=self.depth,
            rotation_y_deg=self.rotation_y_deg,
            clearance_mm=self.clearance_mm,
            visible=self.visible,
            uid=self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "kind": self.kind,
            "name": self.name,
            "x": float(self.x),
            "y": float(self.y),
            "z": float(self.z),
            "width": float(self.width),
            "height": float(self.height),
            "depth": float(self.depth),
            "rotation_y_deg": float(self.rotation_y_deg),
            "clearance_mm": float(self.clearance_mm),
            "visible": bool(self.visible),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomObstacle":
        return cls(
            kind=data.get("kind", "column"),
            name=str(data.get("name") or ""),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            z=data.get("z", 0.0),
            width=data.get("width", 300.0),
            height=data.get("height", DEFAULT_ROOM_HEIGHT_MM),
            depth=data.get("depth", 300.0),
            rotation_y_deg=data.get("rotation_y_deg", 0.0),
            clearance_mm=data.get("clearance_mm", 0.0),
            visible=bool(data.get("visible", True)),
            uid=str(data.get("uid") or new_room_uid("obs")),
        )


@dataclass
class WallGeometryInfo:
    """Вычисленная геометрия отдельной стены в координатах плана XZ."""

    wall_uid: str
    start_xz: tuple[float, float]
    end_xz: tuple[float, float]
    length_mm: float
    tangent_xz: tuple[float, float]
    inward_normal_xz: tuple[float, float]
    outward_normal_xz: tuple[float, float]
    angle_deg: float
    interior_angle_start_deg: float
    interior_angle_end_deg: float


@dataclass
class RoomFrame:
    """Габаритная рамка помещения: замкнутый контур стен, пол, потолок, проёмы и препятствия."""

    name: str = "Помещение"
    floor_elevation_mm: float = 0.0
    ceiling_height_mm: float = DEFAULT_ROOM_HEIGHT_MM
    default_wall_thickness_mm: float = DEFAULT_WALL_THICKNESS_MM
    vertices: list[RoomVertex] = field(default_factory=list)
    walls: list[RoomWall] = field(default_factory=list)
    obstacles: list[RoomObstacle] = field(default_factory=list)
    show_walls: bool = True
    show_floor: bool = True
    show_ceiling: bool = False
    show_openings: bool = True
    show_obstacles: bool = True
    show_furniture: bool = True
    walls_translucent: bool = False
    walls_alpha: float = 0.38
    auto_hide_front_walls: bool = True
    orientation_sign: int = 1
    uid: str = field(default_factory=lambda: new_room_uid("room"))

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip() or "Помещение"
        self.floor_elevation_mm = _finite_float(self.floor_elevation_mm, "Отметка пола")
        self.ceiling_height_mm = _bounded_float(
            self.ceiling_height_mm,
            "Высота потолка",
            min_val=MIN_WALL_HEIGHT_MM,
            max_val=MAX_WALL_HEIGHT_MM,
        )
        self.default_wall_thickness_mm = _bounded_float(
            self.default_wall_thickness_mm,
            "Толщина стен по умолчанию",
            min_val=MIN_WALL_THICKNESS_MM,
            max_val=MAX_WALL_THICKNESS_MM,
        )
        self.walls_alpha = _bounded_float(self.walls_alpha, "Прозрачность стен", min_val=0.05, max_val=1.0)
        self.vertices = [
            v if isinstance(v, RoomVertex) else RoomVertex.from_dict(v)
            for v in (self.vertices or [])
        ]
        self.walls = [
            w if isinstance(w, RoomWall) else RoomWall.from_dict(w)
            for w in (self.walls or [])
        ]
        self.obstacles = [
            o if isinstance(o, RoomObstacle) else RoomObstacle.from_dict(o)
            for o in (self.obstacles or [])
        ]
        self.walls_translucent = bool(self.walls_translucent)
        self.auto_hide_front_walls = bool(self.auto_hide_front_walls)
        self.orientation_sign = -1 if int(self.orientation_sign) < 0 else 1
        self.uid = str(self.uid or "").strip() or new_room_uid("room")

    # ── Фабрики ───────────────────────────────────────────────

    @classmethod
    def create_rectangular(
        cls,
        width_mm: float = DEFAULT_ROOM_WIDTH_MM,
        depth_mm: float = DEFAULT_ROOM_DEPTH_MM,
        height_mm: float = DEFAULT_ROOM_HEIGHT_MM,
        wall_thickness_mm: float = DEFAULT_WALL_THICKNESS_MM,
        name: str = "Помещение",
    ) -> "RoomFrame":
        """Создаёт базовое прямоугольное помещение шириной `width_mm` (X) × глубиной `depth_mm` (Z)."""
        w = _bounded_float(width_mm, "Ширина помещения", min_val=MIN_WALL_LENGTH_MM, max_val=MAX_WALL_LENGTH_MM)
        d = _bounded_float(depth_mm, "Глубина помещения", min_val=MIN_WALL_LENGTH_MM, max_val=MAX_WALL_LENGTH_MM)
        h = _bounded_float(height_mm, "Высота помещения", min_val=MIN_WALL_HEIGHT_MM, max_val=MAX_WALL_HEIGHT_MM)
        t = _bounded_float(
            wall_thickness_mm, "Толщина стен", min_val=MIN_WALL_THICKNESS_MM, max_val=MAX_WALL_THICKNESS_MM
        )
        return cls.from_polygon(
            [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)],
            height_mm=h,
            wall_thickness_mm=t,
            name=name,
        )

    @classmethod
    def from_polygon(
        cls,
        points_xz: list[tuple[float, float]],
        *,
        height_mm: float = DEFAULT_ROOM_HEIGHT_MM,
        wall_thickness_mm: float = DEFAULT_WALL_THICKNESS_MM,
        name: str = "Помещение",
    ) -> "RoomFrame":
        """Создаёт замкнутый контур помещения из произвольного списка вершин `(x, z)` (>= 3)."""
        if len(points_xz) < 3:
            raise ValueError("Контур помещения должен содержать минимум 3 вершины.")
        verts = [RoomVertex(x=float(px), z=float(pz)) for px, pz in points_xz]
        n = len(verts)
        walls: list[RoomWall] = []
        for idx in range(n):
            v0 = verts[idx]
            v1 = verts[(idx + 1) % n]
            seg_len = math.hypot(v1.x - v0.x, v1.z - v0.z)
            if seg_len < MIN_WALL_LENGTH_MM:
                raise ValueError(
                    f"Длина стены {idx + 1} ({seg_len:.1f} мм) меньше минимально допустимой ({MIN_WALL_LENGTH_MM:g} мм)."
                )
            walls.append(
                RoomWall(
                    start_vertex_uid=v0.uid,
                    end_vertex_uid=v1.uid,
                    name=f"Стена {idx + 1}",
                    thickness_mm=wall_thickness_mm,
                    height_mm=height_mm,
                )
            )
        rf = cls(
            name=name,
            ceiling_height_mm=height_mm,
            default_wall_thickness_mm=wall_thickness_mm,
            vertices=verts,
            walls=walls,
        )
        area = rf.signed_area_mm2()
        rf.orientation_sign = -1 if area < 0.0 else 1
        return rf

    # ── Поиск и геометрические запросы ────────────────────────

    def vertex_map(self) -> dict[str, RoomVertex]:
        return {v.uid: v for v in self.vertices}

    def get_vertex(self, uid: str) -> RoomVertex | None:
        for v in self.vertices:
            if v.uid == uid:
                return v
        return None

    def get_wall(self, uid: str) -> RoomWall | None:
        for w in self.walls:
            if w.uid == uid:
                return w
        return None

    def get_opening(self, opening_uid: str) -> tuple[RoomWall, WallOpening] | None:
        for w in self.walls:
            for op in w.openings:
                if op.uid == opening_uid:
                    return w, op
        return None

    def get_obstacle(self, uid: str) -> RoomObstacle | None:
        for o in self.obstacles:
            if o.uid == uid:
                return o
        return None

    def is_closed(self) -> bool:
        """True, если стены образуют один замкнутый контур (минимум 3 стены)."""
        if len(self.walls) < 3:
            return False
        vmap = self.vertex_map()
        out_map: dict[str, list[RoomWall]] = {}
        in_count: dict[str, int] = {}
        for w in self.walls:
            if w.start_vertex_uid not in vmap or w.end_vertex_uid not in vmap:
                return False
            out_map.setdefault(w.start_vertex_uid, []).append(w)
            in_count[w.end_vertex_uid] = in_count.get(w.end_vertex_uid, 0) + 1
        if any(len(ws) != 1 for ws in out_map.values()):
            return False
        if any(in_count.get(v_uid, 0) != 1 for v_uid in out_map):
            return False
        start_v = self.walls[0].start_vertex_uid
        cur_v = start_v
        visited = 0
        while visited < len(self.walls):
            ws = out_map.get(cur_v)
            if not ws:
                return False
            cur_v = ws[0].end_vertex_uid
            visited += 1
            if cur_v == start_v:
                break
        return visited == len(self.walls) and cur_v == start_v

    def has_corner_angle(self, vertex_uid: str) -> bool:
        """True, если в вершине сходятся входящая и исходящая стены (есть внутренний угол)."""
        has_in = any(w.end_vertex_uid == vertex_uid for w in self.walls)
        has_out = any(w.start_vertex_uid == vertex_uid for w in self.walls)
        return has_in and has_out

    def ordered_vertex_chain(self) -> list[RoomVertex]:
        """Упорядоченная цепочка вершин по связям стен (корректно работает и для незамкнутых контуров)."""
        vmap = self.vertex_map()
        if not self.walls:
            return list(self.vertices)

        out_map: dict[str, list[RoomWall]] = {}
        in_deg: dict[str, int] = {}
        for w in self.walls:
            out_map.setdefault(w.start_vertex_uid, []).append(w)
            in_deg[w.end_vertex_uid] = in_deg.get(w.end_vertex_uid, 0) + 1

        # Для незамкнутого контура начинаем с вершины без входящей стены
        open_starts = [w.start_vertex_uid for w in self.walls if in_deg.get(w.start_vertex_uid, 0) == 0]
        start_uid = open_starts[0] if open_starts else self.walls[0].start_vertex_uid

        ordered_uids: list[str] = []
        used_walls: set[str] = set()

        def _walk_from(uid: str) -> None:
            cur = uid
            if cur in vmap and (not ordered_uids or ordered_uids[-1] != cur):
                ordered_uids.append(cur)
            while True:
                nxt_wall = next((w for w in out_map.get(cur, ()) if w.uid not in used_walls), None)
                if nxt_wall is None:
                    break
                used_walls.add(nxt_wall.uid)
                cur = nxt_wall.end_vertex_uid
                if cur == uid and ordered_uids and ordered_uids[0] == uid:
                    break
                if cur in vmap and cur not in ordered_uids:
                    ordered_uids.append(cur)

        _walk_from(start_uid)
        for w in self.walls:
            if w.uid not in used_walls:
                _walk_from(w.start_vertex_uid)

        return [vmap[u] for u in ordered_uids if u in vmap]

    def ordered_polygon_xz(self) -> list[tuple[float, float]]:
        """Упорядоченный контур вершин `(x, z)` по цепочке стен (включая конечную вершину незамкнутого контура)."""
        return [(v.x, v.z) for v in self.ordered_vertex_chain()]

    def signed_area_mm2(self) -> float:
        """Знаковая площадь контура в плоскости XZ (мм²).

        В системе XZ (X вправо, Z вперёд/вниз на плане):
        `> 0` — обход по часовой стрелке на плане (внутренняя нормаль слева от вектора стены `(-tz, tx)`),
        `< 0` — против часовой стрелки (внутренняя нормаль справа `(tz, -tx)`).
        """
        pts = self.ordered_polygon_xz()
        n = len(pts)
        if n < 3:
            return 0.0
        acc = 0.0
        for i in range(n):
            x0, z0 = pts[i]
            x1, z1 = pts[(i + 1) % n]
            acc += x0 * z1 - x1 * z0
        return 0.5 * acc

    def _effective_orientation_sign(self) -> int:
        area = self.signed_area_mm2()
        if abs(area) > 100.0:
            return 1 if area > 0.0 else -1
        return -1 if self.orientation_sign < 0 else 1

    def floor_area_m2(self) -> float:
        """Площадь помещения по внутреннему контуру, м²."""
        return abs(self.signed_area_mm2()) / 1_000_000.0

    def perimeter_mm(self) -> float:
        """Суммарная длина стен по внутреннему контуру, мм."""
        return sum(self.wall_length(w) for w in self.walls)

    def wall_length(self, wall: RoomWall) -> float:
        vmap = self.vertex_map()
        v0 = vmap.get(wall.start_vertex_uid)
        v1 = vmap.get(wall.end_vertex_uid)
        if v0 is None or v1 is None:
            return 0.0
        return math.hypot(v1.x - v0.x, v1.z - v0.z)

    def _inward_normal_for_tangent(self, tx: float, tz: float) -> tuple[float, float]:
        # Для положительной знаковой площади (x0*z1 - x1*z0 > 0) поворот на +90° даёт (-tz, tx) — внутрь.
        if self._effective_orientation_sign() >= 0:
            return (-tz, tx)
        return (tz, -tx)

    def interior_angle_at_vertex(self, vertex_uid: str) -> float:
        """Фактический внутренний угол между смежными стенами в вершине (градусы, 0..360)."""
        incoming: RoomWall | None = None
        outgoing: RoomWall | None = None
        for w in self.walls:
            if w.end_vertex_uid == vertex_uid:
                incoming = w
            if w.start_vertex_uid == vertex_uid:
                outgoing = w
        if incoming is None or outgoing is None:
            return 90.0
        vmap = self.vertex_map()
        vp = vmap.get(incoming.start_vertex_uid)
        vc = vmap.get(vertex_uid)
        vn = vmap.get(outgoing.end_vertex_uid)
        if vp is None or vc is None or vn is None:
            return 90.0

        # Векторы от вершины вдоль предыдущей и следующей стен
        ax, az = vp.x - vc.x, vp.z - vc.z
        bx, bz = vn.x - vc.x, vn.z - vc.z
        la = math.hypot(ax, az)
        lb = math.hypot(bx, bz)
        if la < 1e-9 or lb < 1e-9:
            return 90.0
        ax, az = ax / la, az / la
        bx, bz = bx / lb, bz / lb

        dot = max(-1.0, min(1.0, ax * bx + az * bz))
        cross = ax * bz - az * bx
        # В зависимости от ориентации контура определяем внутренний угол (включая > 180° для выступов)
        if self._effective_orientation_sign() >= 0:
            # Для обхода с положительной площадью внутренний поворот: от outgoing к incoming против знака cross
            ang = math.degrees(math.atan2(-cross, dot))
        else:
            ang = math.degrees(math.atan2(cross, dot))
        if ang <= 0.0:
            ang += 360.0
        return ang

    def wall_geometry(self, wall: RoomWall | str) -> WallGeometryInfo:
        """Возвращает полную геометрию стены (координаты, длина, касательная, нормали, углы)."""
        w = self.get_wall(wall) if isinstance(wall, str) else wall
        if w is None:
            raise ValueError(f"Стена «{wall}» не найдена.")
        vmap = self.vertex_map()
        v0 = vmap.get(w.start_vertex_uid)
        v1 = vmap.get(w.end_vertex_uid)
        if v0 is None or v1 is None:
            raise ValueError(f"У стены «{w.name}» отсутствуют конечные узлы.")
        dx = v1.x - v0.x
        dz = v1.z - v0.z
        length = math.hypot(dx, dz)
        if length < 1e-9:
            tx, tz = 1.0, 0.0
        else:
            tx, tz = dx / length, dz / length
        nx, nz = self._inward_normal_for_tangent(tx, tz)
        return WallGeometryInfo(
            wall_uid=w.uid,
            start_xz=(v0.x, v0.z),
            end_xz=(v1.x, v1.z),
            length_mm=length,
            tangent_xz=(tx, tz),
            inward_normal_xz=(nx, nz),
            outward_normal_xz=(-nx, -nz),
            angle_deg=math.degrees(math.atan2(dz, dx)),
            interior_angle_start_deg=self.interior_angle_at_vertex(w.start_vertex_uid),
            interior_angle_end_deg=self.interior_angle_at_vertex(w.end_vertex_uid),
        )

    def evaluate_wall_offset(self, wall: RoomWall | str, s_mm: float, y_mm: float) -> float:
        """Интерполирует фактическое отклонение поверхности стены (мм) в точке `(s_mm, y_mm)`.

        Точность воспроизведения контрольных станций <= `WALL_DEVIATION_TOLERANCE_MM` (0.05 мм):
        в самих точках замера возвращается точное измеренное значение.
        - 0 станций → 0.0 мм (идеально плоская стена);
        - 1 станция → равномерное смещение (или завал, задаётся >=2 станциями);
        - станции на одной высоте → кусочно-линейная интерполяция по `s` (выпуклость/вогнутость);
        - станции в одном сечении по длине → кусочно-линейная интерполяция по `y` (завал от вертикали);
        - произвольный 2D-набор станций `(s, y)` → гладкая IDW-интерполяция Шепарда (p=2),
          точно проходящая через все контрольные точки.
        """
        w = self.get_wall(wall) if isinstance(wall, str) else wall
        if w is None or not w.deviation_stations:
            return 0.0

        stations = w.deviation_stations
        if len(stations) == 1:
            return float(stations[0].offset_mm)

        s = float(s_mm)
        y = float(y_mm)

        # Точное совпадение со станцией замера
        for st in stations:
            if math.hypot(s - st.s_mm, y - st.height_mm) <= WALL_DEVIATION_TOLERANCE_MM:
                return float(st.offset_mm)

        s_span = max(st.s_mm for st in stations) - min(st.s_mm for st in stations)
        y_span = max(st.height_mm for st in stations) - min(st.height_mm for st in stations)

        # Вырожденный 1D-случай по длине (все станции на одной высоте)
        if y_span <= 1.0 and s_span > 1.0:
            ordered = sorted(stations, key=lambda st: st.s_mm)
            if s <= ordered[0].s_mm:
                return float(ordered[0].offset_mm)
            if s >= ordered[-1].s_mm:
                return float(ordered[-1].offset_mm)
            for i in range(len(ordered) - 1):
                a, b = ordered[i], ordered[i + 1]
                if a.s_mm <= s <= b.s_mm:
                    span = max(b.s_mm - a.s_mm, 1e-6)
                    t = (s - a.s_mm) / span
                    return float(a.offset_mm + (b.offset_mm - a.offset_mm) * t)

        # Вырожденный 1D-случай по высоте (завал стены от вертикали)
        if s_span <= 1.0 and y_span > 1.0:
            ordered = sorted(stations, key=lambda st: st.height_mm)
            if y <= ordered[0].height_mm:
                return float(ordered[0].offset_mm)
            if y >= ordered[-1].height_mm:
                return float(ordered[-1].offset_mm)
            for i in range(len(ordered) - 1):
                a, b = ordered[i], ordered[i + 1]
                if a.height_mm <= y <= b.height_mm:
                    span = max(b.height_mm - a.height_mm, 1e-6)
                    t = (y - a.height_mm) / span
                    return float(a.offset_mm + (b.offset_mm - a.offset_mm) * t)

        # Общий 2D-случай: нормализованная обратная квадратичная весовая интерполяция (Shepard p=2)
        scale_s = max(s_span, self.wall_length(w), 1.0)
        scale_y = max(y_span, float(w.height_mm), 1.0)
        num = 0.0
        den = 0.0
        for st in stations:
            ds = (s - st.s_mm) / scale_s
            dy = (y - st.height_mm) / scale_y
            d2 = ds * ds + dy * dy
            if d2 < 1e-12:
                return float(st.offset_mm)
            weight = 1.0 / d2
            num += weight * float(st.offset_mm)
            den += weight
        return float(num / den) if den > 0.0 else 0.0

    def world_aabb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Мировой ограничивающий бокс всего помещения `((x0, y0, z0), (x1, y1, z1))`."""
        xs: list[float] = []
        zs: list[float] = []
        max_h = float(self.ceiling_height_mm)
        for v in self.vertices:
            xs.append(v.x)
            zs.append(v.z)
        for w in self.walls:
            max_h = max(max_h, float(w.height_mm))
            try:
                info = self.wall_geometry(w)
                ox, oz = info.outward_normal_xz
                t = float(w.thickness_mm)
                xs.extend([info.start_xz[0] + ox * t, info.end_xz[0] + ox * t])
                zs.extend([info.start_xz[1] + oz * t, info.end_xz[1] + oz * t])
            except ValueError:
                continue
        if not xs or not zs:
            return ((0.0, self.floor_elevation_mm, 0.0), (DEFAULT_ROOM_WIDTH_MM, max_h, DEFAULT_ROOM_DEPTH_MM))
        y0 = float(self.floor_elevation_mm)
        return ((min(xs), y0, min(zs)), (max(xs), y0 + max_h, max(zs)))

    # ── Редактирование геометрии контура ──────────────────────

    def move_vertex(self, vertex_uid: str, x: float, z: float) -> None:
        v = self.get_vertex(vertex_uid)
        if v is None:
            raise ValueError("Указанный узел помещения не найден.")
        nx = _finite_float(x, "Координата X узла")
        nz = _finite_float(z, "Координата Z узла")
        old_x, old_z = v.x, v.z
        v.x, v.z = nx, nz
        # Проверяем, что смежные стены не выродились
        for w in self.walls:
            if w.start_vertex_uid == vertex_uid or w.end_vertex_uid == vertex_uid:
                if self.wall_length(w) < MIN_WALL_LENGTH_MM:
                    v.x, v.z = old_x, old_z
                    raise ValueError(
                        f"Длина смежной стены «{w.name}» не может быть меньше {MIN_WALL_LENGTH_MM:g} мм."
                    )

    def set_wall_length(self, wall_uid: str, new_length_mm: float) -> None:
        """Изменяет длину стены, перемещая её конечный узел вдоль текущего направления стены."""
        w = self.get_wall(wall_uid)
        if w is None:
            raise ValueError("Стена не найдена.")
        target = _bounded_float(
            new_length_mm, "Длина стены", min_val=MIN_WALL_LENGTH_MM, max_val=MAX_WALL_LENGTH_MM
        )
        info = self.wall_geometry(w)
        tx, tz = info.tangent_xz
        nx = info.start_xz[0] + tx * target
        nz = info.start_xz[1] + tz * target
        self.move_vertex(w.end_vertex_uid, nx, nz)

    def set_vertex_angle(self, vertex_uid: str, target_interior_angle_deg: float) -> None:
        """Задаёт внутренний угол в вершине `vertex_uid`, подстраивая исходящую стену без искажения остальных углов.

        - В незамкнутом контуре жёстко поворачивает всю последующую цепочку стен вокруг `vertex_uid`:
          все остальные углы и длины стен остаются полностью неизменными.
        - В замкнутом контуре поворачивает луч исходящей стены и пересекает его с линией следующей стены,
          сдвигая только её начальный узел вдоль этой линии: предыдущий угол, дальний угол и все
          несмежные углы контура остаются неизменными.
        """
        v = self.get_vertex(vertex_uid)
        if v is None:
            raise ValueError("Указанный угол (узел) не найден.")
        w_in = next((w for w in self.walls if w.end_vertex_uid == vertex_uid), None)
        w_out = next((w for w in self.walls if w.start_vertex_uid == vertex_uid), None)
        if w_in is None or w_out is None:
            raise ValueError("В выбранной точке нет двух смежных стен для задания угла.")

        angle = _bounded_float(target_interior_angle_deg, "Угол между стенами", min_val=15.0, max_val=345.0)
        cur_angle = self.interior_angle_at_vertex(vertex_uid)
        delta_deg = angle - cur_angle
        if abs(delta_deg) < 1e-6:
            return

        orient = self._effective_orientation_sign()
        # При положительной знаковой площади увеличение внутреннего угла поворачивает исходящую стену по часовой (минус rad)
        sign = -1.0 if orient >= 0 else 1.0
        rad = math.radians(sign * delta_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        vmap = self.vertex_map()
        v_next = vmap.get(w_out.end_vertex_uid)
        if v_next is None:
            raise ValueError("Конечный узел исходящей стены не найден.")

        dx0 = v_next.x - v.x
        dz0 = v_next.z - v.z
        l_out = math.hypot(dx0, dz0)
        if l_out < 1e-9:
            raise ValueError("Исходящая стена имеет нулевую длину.")
        ux, uz = dx0 / l_out, dz0 / l_out
        u_new_x = ux * cos_a - uz * sin_a
        u_new_z = ux * sin_a + uz * cos_a

        saved_coords = {vt.uid: (vt.x, vt.z) for vt in self.vertices}
        self.orientation_sign = orient

        def _rollback() -> None:
            for vt in self.vertices:
                if vt.uid in saved_coords:
                    vt.x, vt.z = saved_coords[vt.uid]

        # Случай 1: незамкнутый контур — жёсткий поворот всей последующей цепочки вершин вокруг v
        if not self.is_closed():
            downstream_uids: list[str] = []
            seen: set[str] = {vertex_uid}
            cur_u = w_out.end_vertex_uid
            while cur_u and cur_u not in seen:
                seen.add(cur_u)
                downstream_uids.append(cur_u)
                nxt_w = next((w for w in self.walls if w.start_vertex_uid == cur_u), None)
                cur_u = nxt_w.end_vertex_uid if nxt_w is not None else ""

            for du in downstream_uids:
                vt = vmap.get(du)
                if vt is None:
                    continue
                rx = vt.x - v.x
                rz = vt.z - v.z
                vt.x = v.x + rx * cos_a - rz * sin_a
                vt.z = v.z + rx * sin_a + rz * cos_a

            for w in self.walls:
                if self.wall_length(w) < MIN_WALL_LENGTH_MM:
                    _rollback()
                    raise ValueError(
                        f"Длина стены «{w.name}» стала меньше {MIN_WALL_LENGTH_MM:g} мм."
                    )
            return

        # Случай 2: замкнутый контур — пересекаем повёрнутый луч исходящей стены с линией следующей стены,
        # чтобы угол в конце следующей стены (и предыдущий угол) остались строго неизменными.
        w_after = next((w for w in self.walls if w.start_vertex_uid == v_next.uid), None)
        moved_by_intersection = False
        if w_after is not None and w_after.end_vertex_uid != vertex_uid:
            v_after = vmap.get(w_after.end_vertex_uid)
            if v_after is not None:
                dax = v_next.x - v_after.x
                daz = v_next.z - v_after.z
                da_len = math.hypot(dax, daz)
                if da_len > 1e-6:
                    det = u_new_z * dax - u_new_x * daz
                    if abs(det) > 1e-4:
                        rx = v_after.x - v.x
                        rz = v_after.z - v.z
                        t = (rz * dax - rx * daz) / det
                        if MIN_WALL_LENGTH_MM <= t <= MAX_WALL_LENGTH_MM:
                            cand_x = v.x + t * u_new_x
                            cand_z = v.z + t * u_new_z
                            seg_after_len = math.hypot(cand_x - v_after.x, cand_z - v_after.z)
                            # Не переворачиваем следующую стену в обратную сторону через v_after
                            same_dir = (cand_x - v_after.x) * dax + (cand_z - v_after.z) * daz > 0.0
                            if MIN_WALL_LENGTH_MM <= seg_after_len <= MAX_WALL_LENGTH_MM and same_dir:
                                v_next.x = cand_x
                                v_next.z = cand_z
                                moved_by_intersection = True

        if not moved_by_intersection:
            # Резервный вариант (если лучи почти параллельны или пересечение вне допустимых пределов):
            # поворачиваем конечный узел исходящей стены с сохранением её длины.
            v_next.x = v.x + u_new_x * l_out
            v_next.z = v.z + u_new_z * l_out

        for w in self.walls:
            if self.wall_length(w) < MIN_WALL_LENGTH_MM:
                _rollback()
                raise ValueError(
                    f"Не удалось задать угол {angle:g}°: смежная стена «{w.name}» короче {MIN_WALL_LENGTH_MM:g} мм."
                )

    def set_wall_angle_at_start(self, wall_uid: str, target_interior_angle_deg: float) -> None:
        """Поворачивает стену вокруг начального узла для получения заданного внутреннего угла."""
        w = self.get_wall(wall_uid)
        if w is None:
            raise ValueError("Стена не найдена.")
        self.set_vertex_angle(w.start_vertex_uid, target_interior_angle_deg)

    def split_wall(self, wall_uid: str, ratio: float = 0.5) -> tuple[RoomVertex, RoomWall, RoomWall]:
        """Разбивает стену на два последовательных сегмента, добавляя новый узел."""
        idx = next((i for i, w in enumerate(self.walls) if w.uid == wall_uid), -1)
        if idx < 0:
            raise ValueError("Стена не найдена.")
        w = self.walls[idx]
        r = _bounded_float(ratio, "Точка разбиения", min_val=0.05, max_val=0.95)
        info = self.wall_geometry(w)
        split_s = info.length_mm * r
        if split_s < MIN_WALL_LENGTH_MM or (info.length_mm - split_s) < MIN_WALL_LENGTH_MM:
            raise ValueError("Стена слишком короткая для разбиения.")
        mx = info.start_xz[0] + (info.end_xz[0] - info.start_xz[0]) * r
        mz = info.start_xz[1] + (info.end_xz[1] - info.start_xz[1]) * r
        new_v = RoomVertex(x=mx, z=mz)

        # Вставляем вершину сразу после стартовой вершины стены
        start_v_idx = next((i for i, v in enumerate(self.vertices) if v.uid == w.start_vertex_uid), len(self.vertices) - 1)
        self.vertices.insert(start_v_idx + 1, new_v)

        w1 = RoomWall(
            start_vertex_uid=w.start_vertex_uid,
            end_vertex_uid=new_v.uid,
            name=w.name,
            thickness_mm=w.thickness_mm,
            height_mm=w.height_mm,
            visible=w.visible,
        )
        w2 = RoomWall(
            start_vertex_uid=new_v.uid,
            end_vertex_uid=w.end_vertex_uid,
            name=f"Стена {len(self.walls) + 1}",
            thickness_mm=w.thickness_mm,
            height_mm=w.height_mm,
            visible=w.visible,
        )
        # Распределяем станции отклонения по двум новым сегментам
        for st in w.deviation_stations:
            if st.s_mm <= split_s:
                w1.deviation_stations.append(st.clone())
            else:
                w2.deviation_stations.append(
                    WallDeviationStation(s_mm=st.s_mm - split_s, height_mm=st.height_mm, offset_mm=st.offset_mm)
                )
        # Сохраняем проёмы, целиком попавшие в один из сегментов
        for op in w.openings:
            if op.offset_s_mm + op.width_mm <= split_s:
                w1.openings.append(op.clone())
            elif op.offset_s_mm >= split_s:
                op2 = op.clone()
                op2.offset_s_mm -= split_s
                w2.openings.append(op2)

        self.walls[idx : idx + 1] = [w1, w2]
        return new_v, w1, w2

    def insert_niche_or_protrusion(
        self,
        wall_uid: str,
        start_s_mm: float,
        width_mm: float,
        depth_mm: float,
    ) -> list[RoomWall]:
        """Врезает нишу (`depth_mm < 0`, наружу) или выступ (`depth_mm > 0`, внутрь комнаты) в стену.

        Разбивает выбранную стену на 5 связанных стен контура без создания фиктивных мебельных деталей.
        """
        idx = next((i for i, w in enumerate(self.walls) if w.uid == wall_uid), -1)
        if idx < 0:
            raise ValueError("Стена не найдена.")
        w = self.walls[idx]
        info = self.wall_geometry(w)
        s0 = _bounded_float(start_s_mm, "Отступ начала", min_val=MIN_WALL_LENGTH_MM)
        nw = _bounded_float(width_mm, "Ширина ниши/выступа", min_val=MIN_WALL_LENGTH_MM)
        nd = _finite_float(depth_mm, "Глубина ниши/выступа")
        if abs(nd) < MIN_WALL_LENGTH_MM:
            raise ValueError(f"Модуль глубины ниши/выступа должен быть не меньше {MIN_WALL_LENGTH_MM:g} мм.")
        if s0 + nw > info.length_mm - MIN_WALL_LENGTH_MM:
            raise ValueError("Ниша/выступ выходит за пределы длины стены (нужны отступы по краям >= 50 мм).")

        tx, tz = info.tangent_xz
        nx, nz = info.inward_normal_xz
        x0, z0 = info.start_xz

        p1 = RoomVertex(x=x0 + tx * s0, z=z0 + tz * s0)
        p2 = RoomVertex(x=p1.x + nx * nd, z=p1.z + nz * nd)
        p3 = RoomVertex(x=p2.x + tx * nw, z=p2.z + tz * nw)
        p4 = RoomVertex(x=x0 + tx * (s0 + nw), z=z0 + tz * (s0 + nw))

        start_v_idx = next((i for i, v in enumerate(self.vertices) if v.uid == w.start_vertex_uid), len(self.vertices) - 1)
        for offset_i, nv in enumerate((p1, p2, p3, p4), start=1):
            self.vertices.insert(start_v_idx + offset_i, nv)

        kind_lbl = "Выступ" if nd > 0 else "Ниша"
        base_num = len(self.walls)
        new_walls = [
            RoomWall(w.start_vertex_uid, p1.uid, name=w.name, thickness_mm=w.thickness_mm, height_mm=w.height_mm),
            RoomWall(p1.uid, p2.uid, name=f"{kind_lbl} (бок 1)", thickness_mm=w.thickness_mm, height_mm=w.height_mm),
            RoomWall(p2.uid, p3.uid, name=f"{kind_lbl} (задняя)", thickness_mm=w.thickness_mm, height_mm=w.height_mm),
            RoomWall(p3.uid, p4.uid, name=f"{kind_lbl} (бок 2)", thickness_mm=w.thickness_mm, height_mm=w.height_mm),
            RoomWall(p4.uid, w.end_vertex_uid, name=f"Стена {base_num + 4}", thickness_mm=w.thickness_mm, height_mm=w.height_mm),
        ]
        self.walls[idx : idx + 1] = new_walls
        return new_walls

    def delete_wall(self, wall_uid: str) -> None:
        """Удаляет одну стену и оставляет контур помещения незамкнутым (минимум 1 стена сохраняется)."""
        if len(self.walls) <= 1:
            raise ValueError("Нельзя удалить последнюю стену помещения.")
        idx = next((i for i, w in enumerate(self.walls) if w.uid == wall_uid), -1)
        if idx < 0:
            raise ValueError("Стена для удаления не найдена.")
        # Фиксируем ориентацию контура до размыкания, чтобы внутренние нормали стен не перевернулись
        self.orientation_sign = self._effective_orientation_sign()
        self.walls.pop(idx)
        referenced = {w.start_vertex_uid for w in self.walls} | {w.end_vertex_uid for w in self.walls}
        self.vertices = [v for v in self.vertices if v.uid in referenced]

    def delete_vertex(self, vertex_uid: str) -> RoomWall:
        """Удаляет узел контура: для внутреннего угла объединяет смежные стены, для свободного края удаляет стену."""
        in_idx = next((i for i, w in enumerate(self.walls) if w.end_vertex_uid == vertex_uid), -1)
        out_idx = next((i for i, w in enumerate(self.walls) if w.start_vertex_uid == vertex_uid), -1)
        if in_idx < 0 and out_idx < 0:
            raise ValueError("Указанный узел не связан со стенами.")

        # Свободный край незамкнутого контура — удаляем примыкающую стену
        if in_idx < 0 or out_idx < 0:
            if len(self.walls) <= 1:
                raise ValueError("Невозможно удалить узел: должна остаться минимум 1 стена.")
            rem_idx = in_idx if in_idx >= 0 else out_idx
            self.delete_wall(self.walls[rem_idx].uid)
            return self.walls[0]

        if in_idx == out_idx:
            raise ValueError("Указанный узел не связан с двумя разными стенами.")
        if self.is_closed() and (len(self.vertices) <= 3 or len(self.walls) <= 3):
            raise ValueError(
                "Для замкнутого контура из 3 стен удалите отдельную стену («Удалить стену»), чтобы разомкнуть контур."
            )

        w_in = self.walls[in_idx]
        w_out = self.walls[out_idx]
        vmap = self.vertex_map()
        v_prev = vmap.get(w_in.start_vertex_uid)
        v_next = vmap.get(w_out.end_vertex_uid)
        if v_prev is None or v_next is None or v_prev.uid == v_next.uid:
            raise ValueError("Удаление узла приведёт к вырожденному контуру.")
        if math.hypot(v_next.x - v_prev.x, v_next.z - v_prev.z) < MIN_WALL_LENGTH_MM:
            raise ValueError("Результирующая стена после удаления узла короче допустимого минимума.")

        merged = RoomWall(
            start_vertex_uid=w_in.start_vertex_uid,
            end_vertex_uid=w_out.end_vertex_uid,
            name=w_in.name,
            thickness_mm=w_in.thickness_mm,
            height_mm=w_in.height_mm,
            visible=w_in.visible,
        )
        # Удаляем w_out и заменяем w_in на объединённую стену
        self.walls[in_idx] = merged
        self.walls.pop(out_idx)
        self.vertices = [v for v in self.vertices if v.uid != vertex_uid]
        return merged

    def add_opening(self, wall_uid: str, opening: WallOpening) -> WallOpening:
        """Добавляет и валидирует проём (дверь / окно / проход) на указанной стене."""
        w = self.get_wall(wall_uid)
        if w is None:
            raise ValueError("Стена для проёма не найдена.")
        length = self.wall_length(w)
        if opening.offset_s_mm + opening.width_mm > length + 1e-6:
            raise ValueError(
                f"Проём ({opening.offset_s_mm:g} + {opening.width_mm:g} мм) выходит за длину стены ({length:.0f} мм)."
            )
        if opening.sill_height_mm + opening.height_mm > w.height_mm + 1e-6:
            raise ValueError(
                f"Проём ({opening.sill_height_mm:g} + {opening.height_mm:g} мм) превышает высоту стены ({w.height_mm:.0f} мм)."
            )
        # Проверка пересечения с уже существующими проёмами на той же стене
        for other in w.openings:
            if other.uid == opening.uid:
                continue
            ov_s = opening.offset_s_mm < other.offset_s_mm + other.width_mm - 1.0 and (
                opening.offset_s_mm + opening.width_mm > other.offset_s_mm + 1.0
            )
            ov_y = opening.sill_height_mm < other.sill_height_mm + other.height_mm - 1.0 and (
                opening.sill_height_mm + opening.height_mm > other.sill_height_mm + 1.0
            )
            if ov_s and ov_y:
                raise ValueError(f"Проём пересекается с существующим проёмом «{other.name}».")
        w.openings.append(opening)
        return opening

    def remove_opening(self, opening_uid: str) -> bool:
        for w in self.walls:
            before = len(w.openings)
            w.openings = [op for op in w.openings if op.uid != opening_uid]
            if len(w.openings) != before:
                return True
        return False

    def add_deviation_station(self, wall_uid: str, station: WallDeviationStation) -> WallDeviationStation:
        """Добавляет контрольную точку отклонения поверхности на указанную стену."""
        w = self.get_wall(wall_uid)
        if w is None:
            raise ValueError("Стена для замера отклонения не найдена.")
        length = self.wall_length(w)
        if station.s_mm > length + 1e-6:
            raise ValueError(
                f"Позиция замера ({station.s_mm:g} мм) превышает длину стены ({length:.0f} мм)."
            )
        if station.height_mm > w.height_mm + 1e-6:
            raise ValueError(
                f"Высота замера ({station.height_mm:g} мм) превышает высоту стены ({w.height_mm:.0f} мм)."
            )
        w.deviation_stations.append(station)
        return station

    def remove_deviation_station(self, wall_uid: str, station_uid: str) -> bool:
        w = self.get_wall(wall_uid)
        if w is None:
            return False
        before = len(w.deviation_stations)
        w.deviation_stations = [st for st in w.deviation_stations if st.uid != station_uid]
        return len(w.deviation_stations) != before

    def add_obstacle(self, obstacle: RoomObstacle) -> RoomObstacle:
        self.obstacles.append(obstacle)
        return obstacle

    def remove_obstacle(self, obstacle_uid: str) -> bool:
        before = len(self.obstacles)
        self.obstacles = [o for o in self.obstacles if o.uid != obstacle_uid]
        return len(self.obstacles) != before

    def validate(self) -> None:
        """Проверяет целостность контура помещения (допускаются как замкнутые, так и незамкнутые контуры)."""
        if len(self.vertices) < 2 or len(self.walls) < 1:
            raise ValueError("Помещение должно содержать минимум 1 стену и 2 узла.")
        vmap = self.vertex_map()
        for w in self.walls:
            if w.start_vertex_uid not in vmap or w.end_vertex_uid not in vmap:
                raise ValueError(f"Стена «{w.name}» ссылается на несуществующий узел.")
            if self.wall_length(w) < MIN_WALL_LENGTH_MM:
                raise ValueError(f"Длина стены «{w.name}» меньше {MIN_WALL_LENGTH_MM:g} мм.")
        if self.is_closed() and abs(self.signed_area_mm2()) < 1000.0:
            raise ValueError("Площадь помещения слишком мала или контур вырожден.")

    def clone(self) -> "RoomFrame":
        return RoomFrame(
            name=self.name,
            floor_elevation_mm=self.floor_elevation_mm,
            ceiling_height_mm=self.ceiling_height_mm,
            default_wall_thickness_mm=self.default_wall_thickness_mm,
            vertices=[v.clone() for v in self.vertices],
            walls=[w.clone() for w in self.walls],
            obstacles=[o.clone() for o in self.obstacles],
            show_walls=self.show_walls,
            show_floor=self.show_floor,
            show_ceiling=self.show_ceiling,
            show_openings=self.show_openings,
            show_obstacles=self.show_obstacles,
            show_furniture=self.show_furniture,
            walls_translucent=self.walls_translucent,
            walls_alpha=self.walls_alpha,
            auto_hide_front_walls=self.auto_hide_front_walls,
            orientation_sign=self.orientation_sign,
            uid=self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "name": self.name,
            "floor_elevation_mm": float(self.floor_elevation_mm),
            "ceiling_height_mm": float(self.ceiling_height_mm),
            "default_wall_thickness_mm": float(self.default_wall_thickness_mm),
            "vertices": [v.to_dict() for v in self.vertices],
            "walls": [w.to_dict() for w in self.walls],
            "obstacles": [o.to_dict() for o in self.obstacles],
            "show_walls": bool(self.show_walls),
            "show_floor": bool(self.show_floor),
            "show_ceiling": bool(self.show_ceiling),
            "show_openings": bool(self.show_openings),
            "show_obstacles": bool(self.show_obstacles),
            "show_furniture": bool(self.show_furniture),
            "walls_translucent": bool(self.walls_translucent),
            "walls_alpha": float(self.walls_alpha),
            "auto_hide_front_walls": bool(self.auto_hide_front_walls),
            "orientation_sign": int(self.orientation_sign),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RoomFrame | None":
        if data is None:
            return None
        if isinstance(data, cls):
            return data.clone()
        if not isinstance(data, dict):
            return None
        return cls(
            name=str(data.get("name") or "Помещение"),
            floor_elevation_mm=data.get("floor_elevation_mm", 0.0),
            ceiling_height_mm=data.get("ceiling_height_mm", DEFAULT_ROOM_HEIGHT_MM),
            default_wall_thickness_mm=data.get("default_wall_thickness_mm", DEFAULT_WALL_THICKNESS_MM),
            vertices=[RoomVertex.from_dict(v) for v in (data.get("vertices") or []) if isinstance(v, dict)],
            walls=[RoomWall.from_dict(w) for w in (data.get("walls") or []) if isinstance(w, dict)],
            obstacles=[RoomObstacle.from_dict(o) for o in (data.get("obstacles") or []) if isinstance(o, dict)],
            show_walls=bool(data.get("show_walls", True)),
            show_floor=bool(data.get("show_floor", True)),
            show_ceiling=bool(data.get("show_ceiling", False)),
            show_openings=bool(data.get("show_openings", True)),
            show_obstacles=bool(data.get("show_obstacles", True)),
            show_furniture=bool(data.get("show_furniture", True)),
            walls_translucent=bool(data.get("walls_translucent", False)),
            walls_alpha=data.get("walls_alpha", 0.38),
            auto_hide_front_walls=bool(data.get("auto_hide_front_walls", True)),
            orientation_sign=int(data.get("orientation_sign", 1)),
            uid=str(data.get("uid") or new_room_uid("room")),
        )


# ── Размещённое мебельное изделие и рабочее пространство ──────


@dataclass
class PlacedProduct:
    """Независимое мебельное изделие NestCraft, размещённое в рабочем пространстве помещения.

    Хранит:
    - собственную габаритную рамку изделия (`bounding_frame`) и локальные блоки/панели (`blocks_data`);
    - трансформацию размещения в координатах помещения (`x, y, z, rotation_y_deg`) и опциональную
      привязку к стене (`anchor_wall_uid`, `wall_offset_mm`).

    Изменение положения/поворота `PlacedProduct` не меняет локальные координаты панелей изделия;
    изменение самого изделия в редакторе не меняет геометрию помещения и других изделий.
    """

    name: str = "Изделие"
    order_number: str = ""
    bounding_frame: BoundingFrame = field(default_factory=BoundingFrame)
    blocks_data: list[dict[str, Any]] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rotation_y_deg: float = 0.0
    anchor_wall_uid: str = ""
    wall_offset_mm: float = 0.0
    visible: bool = True
    uid: str = field(default_factory=lambda: new_room_uid("prod"))

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip() or "Изделие"
        self.order_number = str(self.order_number or "").strip()
        if isinstance(self.bounding_frame, dict):
            bf = BoundingFrame.from_dict(self.bounding_frame)
            self.bounding_frame = bf if bf is not None else BoundingFrame()
        elif not isinstance(self.bounding_frame, BoundingFrame):
            self.bounding_frame = BoundingFrame()
        self.blocks_data = [
            copy.deepcopy(bd) for bd in (self.blocks_data or []) if isinstance(bd, dict)
        ]
        self.x = _finite_float(self.x, "Позиция X изделия")
        self.y = _finite_float(self.y, "Высота установки Y изделия")
        self.z = _finite_float(self.z, "Позиция Z изделия")
        self.rotation_y_deg = _finite_float(self.rotation_y_deg, "Поворот изделия")
        self.anchor_wall_uid = str(self.anchor_wall_uid or "").strip()
        self.wall_offset_mm = _finite_float(self.wall_offset_mm, "Отступ от стены")
        self.visible = bool(self.visible)
        self.uid = str(self.uid or "").strip() or new_room_uid("prod")

    def panel_count(self) -> int:
        return sum(len(bd.get("panels") or []) for bd in self.blocks_data if isinstance(bd, dict))

    def clone(self, *, new_uid: bool = False) -> "PlacedProduct":
        return PlacedProduct(
            name=self.name,
            order_number=self.order_number,
            bounding_frame=self.bounding_frame.clone(),
            blocks_data=copy.deepcopy(self.blocks_data),
            x=self.x,
            y=self.y,
            z=self.z,
            rotation_y_deg=self.rotation_y_deg,
            anchor_wall_uid=self.anchor_wall_uid,
            wall_offset_mm=self.wall_offset_mm,
            visible=self.visible,
            uid=new_room_uid("prod") if new_uid else self.uid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "name": self.name,
            "order_number": self.order_number,
            "bounding_frame": self.bounding_frame.to_dict(),
            "blocks_data": copy.deepcopy(self.blocks_data),
            "x": float(self.x),
            "y": float(self.y),
            "z": float(self.z),
            "rotation_y_deg": float(self.rotation_y_deg),
            "anchor_wall_uid": self.anchor_wall_uid,
            "wall_offset_mm": float(self.wall_offset_mm),
            "visible": bool(self.visible),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlacedProduct":
        bf = BoundingFrame.from_dict(data.get("bounding_frame")) or BoundingFrame()
        return cls(
            name=str(data.get("name") or "Изделие"),
            order_number=str(data.get("order_number") or ""),
            bounding_frame=bf,
            blocks_data=list(data.get("blocks_data") or []),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            z=data.get("z", 0.0),
            rotation_y_deg=data.get("rotation_y_deg", 0.0),
            anchor_wall_uid=str(data.get("anchor_wall_uid") or ""),
            wall_offset_mm=data.get("wall_offset_mm", 0.0),
            visible=bool(data.get("visible", True)),
            uid=str(data.get("uid") or new_room_uid("prod")),
        )


@dataclass
class RoomWorkspace:
    """Рабочее пространство «Помещение»: габаритная рамка помещения + размещённые изделия."""

    room_frame: RoomFrame = field(default_factory=RoomFrame.create_rectangular)
    products: list[PlacedProduct] = field(default_factory=list)
    view_mode: str = "3d"  # "2d" | "3d"
    allowed_gap_mm: float = DEFAULT_ALLOWED_GAP_MM
    collision_tolerance_mm: float = DEFAULT_COLLISION_TOLERANCE_MM

    def __post_init__(self) -> None:
        if isinstance(self.room_frame, dict):
            rf = RoomFrame.from_dict(self.room_frame)
            self.room_frame = rf if rf is not None else RoomFrame.create_rectangular()
        elif not isinstance(self.room_frame, RoomFrame):
            self.room_frame = RoomFrame.create_rectangular()
        self.products = [
            p if isinstance(p, PlacedProduct) else PlacedProduct.from_dict(p)
            for p in (self.products or [])
        ]
        self.view_mode = "2d" if str(self.view_mode or "3d").lower() == "2d" else "3d"
        self.allowed_gap_mm = _bounded_float(self.allowed_gap_mm, "Допустимый зазор", min_val=0.0, max_val=500.0)
        self.collision_tolerance_mm = _bounded_float(
            self.collision_tolerance_mm, "Допуск касания", min_val=0.0, max_val=50.0
        )

    def get_product(self, product_uid: str) -> PlacedProduct | None:
        for p in self.products:
            if p.uid == product_uid:
                return p
        return None

    def add_product(self, product: PlacedProduct) -> PlacedProduct:
        self.products.append(product)
        return product

    def remove_product(self, product_uid: str) -> bool:
        before = len(self.products)
        self.products = [p for p in self.products if p.uid != product_uid]
        return len(self.products) != before

    def duplicate_product(self, product_uid: str, *, offset_x_mm: float = 200.0, offset_z_mm: float = 0.0) -> PlacedProduct:
        src = self.get_product(product_uid)
        if src is None:
            raise ValueError("Изделие для дублирования не найдено.")
        dup = src.clone(new_uid=True)
        dup.name = f"{src.name} (копия)"
        dup.x += float(offset_x_mm)
        dup.z += float(offset_z_mm)
        self.products.append(dup)
        return dup

    def clone(self) -> "RoomWorkspace":
        return RoomWorkspace(
            room_frame=self.room_frame.clone(),
            products=[p.clone() for p in self.products],
            view_mode=self.view_mode,
            allowed_gap_mm=self.allowed_gap_mm,
            collision_tolerance_mm=self.collision_tolerance_mm,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_frame": self.room_frame.to_dict(),
            "products": [p.to_dict() for p in self.products],
            "view_mode": self.view_mode,
            "allowed_gap_mm": float(self.allowed_gap_mm),
            "collision_tolerance_mm": float(self.collision_tolerance_mm),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RoomWorkspace | None":
        if data is None:
            return None
        if isinstance(data, cls):
            return data.clone()
        if not isinstance(data, dict):
            return None
        rf = RoomFrame.from_dict(data.get("room_frame"))
        if rf is None:
            return None
        return cls(
            room_frame=rf,
            products=[
                PlacedProduct.from_dict(pd)
                for pd in (data.get("products") or [])
                if isinstance(pd, dict)
            ],
            view_mode=str(data.get("view_mode") or "3d"),
            allowed_gap_mm=data.get("allowed_gap_mm", DEFAULT_ALLOWED_GAP_MM),
            collision_tolerance_mm=data.get("collision_tolerance_mm", DEFAULT_COLLISION_TOLERANCE_MM),
        )
