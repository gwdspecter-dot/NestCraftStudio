from __future__ import annotations

import math
import re
from dataclasses import InitVar, dataclass, field
from typing import Any, ClassVar, Optional, Tuple
from uuid import uuid4

# Параметры материала по умолчанию (МИСТ VL 16 мм из seed-каталога)
DEFAULT_MATERIAL_ID = "mat_mist_vl_16"
DEFAULT_MATERIAL_NAME = "МИСТ VL 16 мм"
DEFAULT_MATERIAL_COLOR: Tuple[float, float, float] = (0.88, 0.85, 0.80)


def new_uid() -> str:
    """Стабильный идентификатор объекта сцены (Panel / Block)."""
    return str(uuid4())


@dataclass(eq=False)
class Panel:
    """Чистая модель мебельной панели (dataclass без прямых обращений к сервисам, ревизия 2, п. 2.1).

    Материалы, кромки и пересборка геометрии управляются через `SceneController`
    (`core.scene_controller.SceneController`), который связывает `Panel` с
    `CatalogService` и `GeometryService`.
    """

    name: str
    x: float
    y: float
    z: float
    width: float
    height: float
    depth: float
    pos_num: str = ""
    code: str = ""
    material: str = ""
    material_id: Optional[str] = None
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    edges: Optional[dict[str, str]] = None
    role: str = ""
    uid: str = ""
    rebuild: InitVar[bool] = True
    thickness_axis: Optional[int] = None
    color: Tuple[float, float, float] = DEFAULT_MATERIAL_COLOR
    missing_material_id: str = ""
    missing_edges: dict[str, str] = field(default_factory=dict)
    selected: bool = False
    grooves: list[tuple] = field(default_factory=list)
    holes: list[tuple] = field(default_factory=list)
    fastener_issues: list = field(default_factory=list)
    joint_hole_map: dict[str, list[tuple]] = field(default_factory=dict, repr=False)
    assoc_hole_map: dict[str, list[tuple]] = field(default_factory=dict, repr=False)
    # Персистентные формулы: attr -> expression (например width: "cw - 2*ct")
    drivers: dict[str, str] = field(default_factory=dict)
    _block: Any = field(default=None, repr=False)
    solid: object = field(default=None, repr=False)
    mesh_data: object = field(default=None, repr=False)
    _gl_arrays: object = field(default=None, repr=False)
    geometry_generation: int = field(default=0, repr=False)
    geometry_pending: bool = field(default=False, repr=False)
    _gpu_id: Optional[int] = field(default=None, repr=False)
    _mesh_pose_key: Optional[tuple] = field(default=None, repr=False)
    _corners_cache_key: Optional[tuple] = field(default=None, repr=False)
    _corners_cache_data: Optional[list[tuple[float, float, float]]] = field(default=None, repr=False)
    _snap_cache_key: Optional[tuple] = field(default=None, repr=False)
    _snap_cache_data: Optional[list[tuple]] = field(default=None, repr=False)
    material_thickness: float = field(default=0.0, repr=False)
    edge_thicknesses: dict[str, float] = field(default_factory=dict, repr=False)

    # Опциональная ссылка на активный SceneController (устанавливается контроллером сцены)
    _scene_controller: ClassVar[Any] = None
    _controller_unbound: ClassVar[bool] = False

    @classmethod
    def _get_controller(cls):
        if cls._scene_controller is not None:
            return cls._scene_controller
        if cls._controller_unbound:
            return None
        try:
            from core.scene_controller import SceneController
            return SceneController.instance()
        except ImportError:
            # Нет модуля контроллера — изолированный / headless-режим
            return None
        except Exception:  # noqa: BLE001 — логируем сбой контроллера/каталога
            # Ошибка инициализации (каталог, БД и т.п.) — не маскируем под «нет контроллера»
            from core.logging_setup import get_logger
            get_logger("panel").exception(
                "SceneController.instance() failed; panel runs without controller"
            )
            return None

    def __post_init__(self, rebuild: bool) -> None:
        self.uid = str(self.uid).strip() if self.uid else new_uid()
        self.name = str(self.name)
        self.pos_num = str(self.pos_num or "")
        self.code = str(self.code or "")
        self.role = str(self.role or "")
        self.x = float(self.x)
        self.y = float(self.y)
        self.z = float(self.z)
        self.rx = float(self.rx)
        self.ry = float(self.ry)
        self.rz = float(self.rz)
        self.width = float(self.width)
        self.height = float(self.height)
        self.depth = float(self.depth)

        raw_edges = self.edges if isinstance(self.edges, dict) else None
        norm_edges: dict[str, str] = {
            "top": "",
            "bottom": "",
            "left": "",
            "right": "",
        }
        if raw_edges:
            for k in ("top", "bottom", "left", "right"):
                if k in raw_edges:
                    norm_edges[k] = str(raw_edges[k] or "")
        self.edges = norm_edges

        requested_material_id = self.material_id
        legacy_material = self.material
        explicit_tax = self.thickness_axis

        self.material_id = str(requested_material_id or DEFAULT_MATERIAL_ID)
        self.material = str(legacy_material or DEFAULT_MATERIAL_NAME)
        self.color = tuple(self.color) if self.color else DEFAULT_MATERIAL_COLOR

        dims0 = (self.width, self.height, self.depth)
        if explicit_tax is not None:
            self.thickness_axis = int(explicit_tax) % 3
        else:
            self.thickness_axis = int(min(range(3), key=lambda i: dims0[i]))

        ctrl = self._get_controller()
        if ctrl is not None:
            ctrl.on_panel_created(
                self,
                requested_material_id=requested_material_id,
                legacy_material=legacy_material or None,
                explicit_thickness_axis=explicit_tax,
                rebuild=bool(rebuild),
            )
        elif rebuild:
            self.rebuild_geometry(sync=False)

    # ── ориентация / world-space ──────────────────────────────

    def has_rotation(self, eps: float = 1e-6) -> bool:
        """True, если задан ненулевой поворот."""
        return (
            abs(float(getattr(self, "rx", 0.0))) > eps
            or abs(float(getattr(self, "ry", 0.0))) > eps
            or abs(float(getattr(self, "rz", 0.0))) > eps
        )

    def rotation_matrix(self):
        """3×3 матрица поворота R = Rz @ Ry @ Rx (градусы).

        Соглашение: Extrinsic.XYZ — то же, что CADKernel.build_panel_solid_data
        (Rotation(..., ordering=Extrinsic.XYZ)). Не путать с build123d.Rot(),
        у которого по умолчанию Intrinsic.XYZ.
        """
        import numpy as np
        rx = math.radians(float(getattr(self, "rx", 0.0)))
        ry = math.radians(float(getattr(self, "ry", 0.0)))
        rz = math.radians(float(getattr(self, "rz", 0.0)))
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
        return Rz @ Ry @ Rx

    def local_center(self) -> tuple[float, float, float]:
        return (float(self.width) * 0.5, float(self.height) * 0.5, float(self.depth) * 0.5)

    def world_center(self) -> tuple[float, float, float]:
        """Центр панели в мировых координатах (инвариантен относительно rx/ry/rz)."""
        cx, cy, cz = self.local_center()
        return (float(self.x) + cx, float(self.y) + cy, float(self.z) + cz)

    def rotate_vector(self, vx: float, vy: float, vz: float) -> tuple[float, float, float]:
        """Поворачивает локальный вектор в мировые координаты (R = Rz @ Ry @ Rx)."""
        x, y, z = float(vx), float(vy), float(vz)
        if not self.has_rotation():
            return (x, y, z)
        a = math.radians(float(getattr(self, "rx", 0.0)))
        b = math.radians(float(getattr(self, "ry", 0.0)))
        c = math.radians(float(getattr(self, "rz", 0.0)))
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)
        # Rx
        y, z = ca * y - sa * z, sa * y + ca * z
        # Ry
        x, z = cb * x + sb * z, -sb * x + cb * z
        # Rz
        x, y = cc * x - sc * y, sc * x + cc * y
        return (x, y, z)

    def unrotate_vector(self, wx: float, wy: float, wz: float) -> tuple[float, float, float]:
        """Поворачивает мировой вектор обратно в локальные координаты (R^T = Rx^T @ Ry^T @ Rz^T)."""
        x, y, z = float(wx), float(wy), float(wz)
        if not self.has_rotation():
            return (x, y, z)
        a = math.radians(float(getattr(self, "rx", 0.0)))
        b = math.radians(float(getattr(self, "ry", 0.0)))
        c = math.radians(float(getattr(self, "rz", 0.0)))
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(b), math.sin(b)
        cc, sc = math.cos(c), math.sin(c)
        # Rz^T
        x, y = cc * x + sc * y, -sc * x + cc * y
        # Ry^T
        x, z = cb * x - sb * z, sb * x + cb * z
        # Rx^T
        y, z = ca * y + sa * z, -sa * y + ca * z
        return (x, y, z)

    def local_to_world(self, lx: float, ly: float, lz: float) -> tuple[float, float, float]:
        """Локальная точка панели → мир.

        Поворот вокруг геометрического центра панели (не min-corner),
        затем перенос в (x,y,z). Согласовано с CADKernel.build_panel_solid_data.
        """
        cx, cy, cz = self.local_center()
        vx, vy, vz = self.rotate_vector(float(lx) - cx, float(ly) - cy, float(lz) - cz)
        return (
            float(self.x) + cx + vx,
            float(self.y) + cy + vy,
            float(self.z) + cz + vz,
        )

    def world_to_local(self, wx: float, wy: float, wz: float) -> tuple[float, float, float]:
        """Мировая точка → локальные координаты панели [0..width, 0..height, 0..depth]."""
        cx, cy, cz = self.local_center()
        dx = float(wx) - (float(self.x) + cx)
        dy = float(wy) - (float(self.y) + cy)
        dz = float(wz) - (float(self.z) + cz)
        lx, ly, lz = self.unrotate_vector(dx, dy, dz)
        return (cx + lx, cy + ly, cz + lz)

    def obb(self) -> tuple[
        tuple[float, float, float],
        tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
        tuple[float, float, float],
    ]:
        """Ориентированный бокс (OBB) панели в мировых координатах (план §1.5).

        Возвращает (center, (axis_x, axis_y, axis_z), (half_w, half_h, half_d)):
        - center: (cx, cy, cz) в мире;
        - axes: три ортонормированных орта локальных осей X, Y, Z в мире;
        - half_extents: половины размеров (width/2, height/2, depth/2).
        """
        center = self.world_center()
        axes = (
            self.rotate_vector(1.0, 0.0, 0.0),
            self.rotate_vector(0.0, 1.0, 0.0),
            self.rotate_vector(0.0, 0.0, 1.0),
        )
        half_extents = self.local_center()
        return center, axes, half_extents

    def pose_key(self) -> tuple:
        """Ключ положения, габаритов и ориентации детали в мировых координатах."""
        return (
            round(float(self.x), 4),
            round(float(self.y), 4),
            round(float(self.z), 4),
            round(float(self.width), 4),
            round(float(self.height), 4),
            round(float(self.depth), 4),
            round(float(getattr(self, "rx", 0.0)), 4),
            round(float(getattr(self, "ry", 0.0)), 4),
            round(float(getattr(self, "rz", 0.0)), 4),
        )

    def snap_cache_token(self, label_prefix: str = "") -> tuple:
        """Ключ актуальности кэша мировых точек привязки детали (поза + отверстия + префикс)."""
        holes_raw = getattr(self, "holes", None) or ()
        holes_key = tuple(tuple(h[:6]) for h in holes_raw if h and len(h) >= 3)
        return (
            self.pose_key(),
            holes_key,
            str(label_prefix or ""),
        )

    def invalidate_spatial_caches(self) -> None:
        """Сбрасывает кэши мировых углов и точек привязки."""
        self._corners_cache_key = None
        self._corners_cache_data = None
        self._snap_cache_key = None
        self._snap_cache_data = None

    def world_corners(self) -> list[tuple[float, float, float]]:
        """8 углов панели в мире (с учётом поворота и кэшированием по pose_key)."""
        pk = self.pose_key()
        if getattr(self, "_corners_cache_key", None) == pk:
            cached = getattr(self, "_corners_cache_data", None)
            if cached is not None:
                return list(cached)
        w, h, d = float(self.width), float(self.height), float(self.depth)
        locals_ = [
            (0.0, 0.0, 0.0), (w, 0.0, 0.0), (w, h, 0.0), (0.0, h, 0.0),
            (0.0, 0.0, d), (w, 0.0, d), (w, h, d), (0.0, h, d),
        ]
        corners = [self.local_to_world(lx, ly, lz) for lx, ly, lz in locals_]
        self._corners_cache_key = pk
        self._corners_cache_data = corners
        return list(corners)

    def world_aabb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Ось-выровненный AABB в мире (оболочка OBB при повороте)."""
        if not self.has_rotation():
            return (
                (float(self.x), float(self.y), float(self.z)),
                (float(self.x) + float(self.width),
                 float(self.y) + float(self.height),
                 float(self.z) + float(self.depth)),
            )
        corners = self.world_corners()
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        zs = [c[2] for c in corners]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def clone(
        self,
        *,
        name: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        pos_num: str | None = None,
        role: str = "",
    ) -> "Panel":
        """Полная копия панели: геометрия, поворот, кромка, пазы, присадка, материал.

        role по умолчанию пустой — копия не считается структурной деталью корпуса.
        """
        p = Panel(
            name=name if name is not None else self.name,
            x=self.x if x is None else float(x),
            y=self.y if y is None else float(y),
            z=self.z if z is None else float(z),
            width=self.width,
            height=self.height,
            depth=self.depth,
            pos_num=self.pos_num if pos_num is None else pos_num,
            code=self.code,
            material=self.material,
            material_id=getattr(self, "material_id", None),
            rx=float(getattr(self, "rx", 0.0)),
            ry=float(getattr(self, "ry", 0.0)),
            rz=float(getattr(self, "rz", 0.0)),
            edges=dict(getattr(self, "edges", {}) or {}),
            role=role,
            uid="",  # копия — новый uid
            rebuild=False,
        )
        p.color = tuple(self.color) if self.color else p.color
        p.thickness_axis = int(getattr(self, "thickness_axis", p.thickness_axis))
        p.material_thickness = float(getattr(self, "material_thickness", 0.0) or 0.0)
        p.edge_thicknesses = dict(getattr(self, "edge_thicknesses", {}) or {})
        p.missing_material_id = str(getattr(self, "missing_material_id", "") or "")
        p.missing_edges = dict(getattr(self, "missing_edges", {}) or {})
        p.grooves = [tuple(g) for g in getattr(self, "grooves", [])]
        p.holes = [tuple(h) for h in getattr(self, "holes", [])]
        p.rebuild_geometry()
        return p

    # ── Материалы, кромки и геометрия (делегируются в SceneController при наличии) ──

    def set_edge(self, side: str, edge_band_id: Optional[str], thickness_mm: Optional[float] = None) -> bool:
        """Назначает кромку на торец ('top', 'bottom', 'left', 'right')."""
        ctrl = self._get_controller()
        if ctrl is not None and thickness_mm is None:
            return ctrl.set_edge(self, side, edge_band_id)
        if side in self.edges:
            eid = str(edge_band_id or "")
            self.edges[side] = eid
            if not eid:
                self.missing_edges.pop(side, None)
                self.edge_thicknesses.pop(side, None)
            elif thickness_mm is not None:
                self.edge_thicknesses[side] = float(thickness_mm)
                self.missing_edges.pop(side, None)
            return True
        return False

    def get_edge_thickness(self, side: str) -> float:
        """Возвращает толщину кромки в мм на указанном торце."""
        edge_id = self.edges.get(side)
        if not edge_id:
            return 0.0
        if isinstance(self.edge_thicknesses, dict) and side in self.edge_thicknesses:
            return float(self.edge_thicknesses[side])
        ctrl = self._get_controller()
        if ctrl is not None:
            return ctrl.get_edge_thickness(self, side)
        return 0.0

    def get_saw_dimensions(self) -> tuple[float, float, float]:
        """Возвращает технологические пильные размеры детали (габариты под раскрой).

        По отраслевым стандартам (ГОСТ / Базис-Мебельщик):
        Чистовой размер изделия уменьшается на толщину наклеиваемой кромки:
        L_saw = L - T_edge_left - T_edge_right
        W_saw = W - T_edge_top - T_edge_bottom
        """
        dims = {"X": self.width, "Y": self.height, "Z": self.depth}
        sorted_axes = sorted(dims.keys(), key=lambda a: dims[a], reverse=True)
        length_axis, width_axis, _ = sorted_axes[0], sorted_axes[1], sorted_axes[2]

        t_left = self.get_edge_thickness("left")
        t_right = self.get_edge_thickness("right")
        t_top = self.get_edge_thickness("top")
        t_bottom = self.get_edge_thickness("bottom")

        saw_dims = dict(dims)
        saw_dims[length_axis] = max(1.0, saw_dims[length_axis] - (t_left + t_right))
        saw_dims[width_axis] = max(1.0, saw_dims[width_axis] - (t_top + t_bottom))

        return (saw_dims["X"], saw_dims["Y"], saw_dims["Z"])

    def get_manual_holes(self) -> list[tuple]:
        """Возвращает только ручные отверстия присадки (поставленные без JointRecord, п. 3.1)."""
        from core.joint import extract_manual_holes

        return extract_manual_holes(self)

    def check_hole_groove_collision(self, hole: tuple) -> bool:
        """Проверяет пересечение цилиндра отверстия с существующими пазами детали.

        Предотвращает пробитие крепежом паза задней стенки (ХДФ).
        hole: (lx, ly, lz, radius, depth, axis)
        """
        if not self.grooves or len(hole) < 6:
            return False

        hx, hy, hz, radius, length, axis = hole[:6]
        if axis == "X":
            h_min = (hx, hy - radius, hz - radius)
            h_max = (hx + length, hy + radius, hz + radius)
        elif axis == "Y":
            h_min = (hx - radius, hy, hz - radius)
            h_max = (hx + radius, hy + length, hz + radius)
        else:
            h_min = (hx - radius, hy - radius, hz)
            h_max = (hx + radius, hy + radius, hz + length)

        for g in self.grooves:
            gx, gy, gz, gw, gh, gd = g
            g_max = (gx + gw, gy + gh, gz + gd)

            if (h_min[0] < g_max[0] and h_max[0] > gx and
                h_min[1] < g_max[1] and h_max[1] > gy and
                h_min[2] < g_max[2] and h_max[2] > gz):
                return True

        return False

    def material_thickness_mm(self) -> float:
        """Толщина материала детали (мм). Fallback — локальный кэш или текущий габарит по оси толщины."""
        ctrl = self._get_controller()
        if ctrl is not None:
            return ctrl.material_thickness_mm(self)
        if float(getattr(self, "material_thickness", 0.0) or 0.0) > 0:
            return float(self.material_thickness)
        return self.get_thickness()

    def get_thickness(self) -> float:
        """Актуальная толщина панели по оси thickness_axis."""
        dims = (float(self.width), float(self.height), float(self.depth))
        ax = int(getattr(self, "thickness_axis", 0)) % 3
        return dims[ax]

    def lock_thickness_to_material(self) -> bool:
        """Принудительно выставляет габарит по оси толщины = thickness материала.
        Возвращает True, если значение изменилось.
        """
        ctrl = self._get_controller()
        if ctrl is not None:
            return ctrl.lock_thickness_to_material(self)
        t = float(self.material_thickness_mm())
        if t <= 0:
            return False
        ax = int(getattr(self, "thickness_axis", 0)) % 3
        cur = (self.width, self.height, self.depth)[ax]
        if abs(cur - t) < 1e-9:
            return False
        if ax == 0:
            self.width = t
        elif ax == 1:
            self.height = t
        else:
            self.depth = t
        return True

    def apply_material(self, material_id: str) -> bool:
        """Назначает материал по id (через SceneController или локально в чистом режиме)."""
        ctrl = self._get_controller()
        if ctrl is not None:
            return ctrl.apply_material(self, material_id)
        if not material_id:
            return False
        self.material_id = str(material_id)
        self.lock_thickness_to_material()
        return True

    def add_back_groove(self, offset_z: float = 16.0, groove_w: float = 4.0, groove_depth: float = 6.0, side: str = "right"):
        """Добавляет паз под ХДФ (заднюю стенку) вдоль заднего торца.

        side: "right" | "left" (для вертикальной боковины) или "top" | "bottom" (для горизонтального дна/крышки).
        Ориентация определяется по оси толщины детали.
        """
        self.grooves.clear()
        thickness = self.get_thickness()
        groove_depth = min(groove_depth, max(1.0, thickness - 1.0))
        ax = int(getattr(self, "thickness_axis", 0)) % 3

        if ax == 0 or abs(self.width - thickness) < 1e-6:
            # Вертикальная боковина: толщина по X, паз вдоль высоты Y
            gx = 0.0 if side == "left" else (self.width - groove_depth)
            self.grooves.append((gx, 0, offset_z, groove_depth, self.height, groove_w))
        elif ax == 1 or abs(self.height - thickness) < 1e-6:
            # Горизонтальное дно/крышка: толщина по Y, паз вдоль ширины X
            gy = 0.0 if side == "bottom" else (self.height - groove_depth)
            self.grooves.append((0, gy, offset_z, self.width, groove_depth, groove_w))
        elif ax == 2 or abs(self.depth - thickness) < 1e-6:
            pass
        self.rebuild_geometry()

    def rebuild_geometry(self, sync: bool = False):
        """Запрашивает пересборку геометрии через SceneController (или помечает поколение в чистом режиме)."""
        self.invalidate_spatial_caches()
        ctrl = self._get_controller()
        if ctrl is not None:
            ctrl.rebuild_geometry(self, sync=sync)
            return
        self.geometry_generation = int(getattr(self, "geometry_generation", 0)) + 1
        self.geometry_pending = False
        self._gl_arrays = None

    @classmethod
    def from_dict(cls, d: dict, *, rebuild: bool = True) -> "Panel":
        """Создаёт панель из словаря сериализованного состояния."""
        material_id = d.get("material_id") or None
        legacy_material = d.get("material") or ""
        p = cls(
            name=d.get("name", "Панель"),
            x=d.get("x", 0),
            y=d.get("y", 0),
            z=d.get("z", 0),
            width=d.get("width", 100),
            height=d.get("height", 100),
            depth=d.get("depth", 16),
            pos_num=d.get("pos_num", ""),
            code=d.get("code", ""),
            material=legacy_material,
            material_id=material_id,
            rx=float(d.get("rx", 0.0)),
            ry=float(d.get("ry", 0.0)),
            rz=float(d.get("rz", 0.0)),
            edges=d.get("edges", None),
            role=d.get("role", "") or "",
            uid=str(d.get("uid") or ""),
            rebuild=False,
        )
        raw_missing = str(d.get("missing_material_id") or "").strip()
        raw_missing_edges = d.get("missing_edges") if isinstance(d.get("missing_edges"), dict) else {}

        ctrl = cls._get_controller()
        if ctrl is not None:
            ctrl.sync_panel_catalog(
                p,
                requested_material_id=material_id,
                raw_missing_material_id=raw_missing,
                raw_missing_edges=raw_missing_edges,
            )
        else:
            p.missing_material_id = raw_missing
            p.missing_edges = dict(raw_missing_edges)

        if "thickness_axis" in d:
            try:
                p.thickness_axis = int(d.get("thickness_axis", 0)) % 3
            except (TypeError, ValueError):
                dims = (p.width, p.height, p.depth)
                p.thickness_axis = int(min(range(3), key=lambda i: dims[i]))
        else:
            dims = (p.width, p.height, p.depth)
            p.thickness_axis = int(min(range(3), key=lambda i: dims[i]))

        col = d.get("color")
        if col and len(col) == 3:
            p.color = (float(col[0]), float(col[1]), float(col[2]))
        p.grooves = [tuple(g) for g in d.get("grooves", [])]
        p.holes = [tuple(h) for h in d.get("holes", [])]
        raw_jmap = d.get("joint_hole_map")
        if isinstance(raw_jmap, dict):
            p.joint_hole_map = {
                str(k): [tuple(h) for h in (v or [])]
                for k, v in raw_jmap.items()
                if k
            }
        raw_amap = d.get("assoc_hole_map")
        if isinstance(raw_amap, dict):
            p.assoc_hole_map = {
                str(k): [tuple(h) for h in (v or [])]
                for k, v in raw_amap.items()
                if k
            }
        raw_drivers = d.get("drivers")
        if isinstance(raw_drivers, dict):
            p.drivers = {
                str(k): str(v)
                for k, v in raw_drivers.items()
                if k and v is not None and str(v).strip()
            }
        if rebuild:
            p.rebuild_geometry()
        return p


class Block:
    """Базовый сборочный блок"""
    def __init__(
        self,
        name: str,
        pos_num: str = "",
        code: str = "",
        uid: str = "",
        joints: list | None = None,
        assoc_refs: list | None = None,
    ):
        self.uid = str(uid).strip() if uid else new_uid()
        self.name = name
        self.pos_num = pos_num
        self.code = code
        self.panels: list[Panel] = []
        self.joints: list = list(joints) if joints else []
        self.assoc_refs: list = list(assoc_refs) if assoc_refs else []
        self.selected = False

    def add_panel(self, panel: Panel):
        panel._block = self
        self.panels.append(panel)

    def get_panel_by_uid(self, uid: str) -> Optional[Panel]:
        target = str(uid or "").strip()
        if not target:
            return None
        for p in self.panels:
            if str(getattr(p, "uid", "")) == target:
                return p
        return None

    def get_joint_by_uid(self, uid: str):
        target = str(uid or "").strip()
        if not target:
            return None
        for jr in self.joints:
            if str(getattr(jr, "uid", "")) == target:
                return jr
        return None

    def add_joint(self, record, *, apply: bool = True):
        from core.joint import JointRecord, apply_joints

        rec = record if isinstance(record, JointRecord) else JointRecord.from_dict(record)
        for i, existing in enumerate(self.joints):
            if str(getattr(existing, "uid", "")) == rec.uid:
                self.joints[i] = rec
                break
        else:
            self.joints.append(rec)
        if apply:
            apply_joints(self)
        return rec

    def remove_joint(self, uid: str, *, apply: bool = True) -> bool:
        from core.joint import apply_joints

        target = str(uid or "").strip()
        if not target:
            return False
        before = len(self.joints)
        self.joints = [jr for jr in self.joints if str(getattr(jr, "uid", "")) != target]
        removed = len(self.joints) < before
        if removed and apply:
            apply_joints(self)
        return removed

    def get_assoc_by_uid(self, uid: str):
        target = str(uid or "").strip()
        if not target:
            return None
        for ref in getattr(self, "assoc_refs", []) or []:
            if str(getattr(ref, "uid", "")) == target:
                return ref
        return None

    def add_assoc_ref(self, record, *, apply: bool = True):
        from core.assoc import AssocRef, apply_assoc_refs

        rec = record if isinstance(record, AssocRef) else AssocRef.from_dict(record)
        refs = list(getattr(self, "assoc_refs", []) or [])
        for i, existing in enumerate(refs):
            if str(getattr(existing, "uid", "")) == rec.uid:
                refs[i] = rec
                break
        else:
            refs.append(rec)
        self.assoc_refs = refs
        if apply:
            apply_assoc_refs(self)
        return rec

    def remove_assoc_ref(self, uid: str, *, apply: bool = True) -> bool:
        from core.assoc import apply_assoc_refs

        target = str(uid or "").strip()
        if not target:
            return False
        refs = list(getattr(self, "assoc_refs", []) or [])
        before = len(refs)
        self.assoc_refs = [r for r in refs if str(getattr(r, "uid", "")) != target]
        removed = len(self.assoc_refs) < before
        if removed and apply:
            apply_assoc_refs(self)
        return removed


class ParametricCabinet(Block):
    """Умный параметрический корпус на базе твердотельного ядра"""
    def __init__(self, name: str, x: float = 0, y: float = 0, z: float = 0,
                 width: float = 600, height: float = 720, depth: float = 560,
                 thickness: float = 16, shelves_count: int = 1, 
                 has_facade: bool = True, is_upper: bool = False,
                 has_groove: bool = True,
                 pos_num: str = "1", code: str = "01.00",
                 uid: str = "",
                 joints: list | None = None,
                 rebuild_on_init: bool = True):
        super().__init__(name, pos_num, code, uid=uid, joints=joints)
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.width = float(width)
        self.height = float(height)
        self.depth = float(depth)
        self.thickness = float(thickness)
        self.shelves_count = int(shelves_count)
        self.has_facade = bool(has_facade)
        self.is_upper = bool(is_upper)
        self.has_groove = bool(has_groove)  # Паз под заднюю стенку ХДФ

        if rebuild_on_init:
            self.rebuild()

    # ── умная пересборка ──────────────────────────────────────

    @staticmethod
    def _infer_role_from_name(name: str) -> str:
        """Эвристика для старых проектов без поля role."""
        n = (name or "").lower()
        if "боковина лев" in n or ("лев" in n and "боков" in n):
            return "left"
        if "боковина прав" in n or ("прав" in n and "боков" in n):
            return "right"
        if "дно" in n:
            return "bottom"
        if "крышк" in n:
            return "top"
        if "царга перед" in n:
            return "tsarga_front"
        if "царга зад" in n:
            return "tsarga_back"
        if n.startswith("полка") or "полка " in n:
            m = re.search(r"полка\s*(\d+)", n)
            if m:
                return f"shelf_{int(m.group(1)) - 1}"
            return "shelf_0"
        if "фасад" in n:
            return "facade"
        return ""

    def _desired_specs(self) -> list[dict]:
        """Спецификации панелей корпуса при текущих параметрах."""
        t = self.thickness
        w, h, d = self.width, self.height, self.depth
        bx, by, bz = self.x, self.y, self.z
        inner_w = w - 2 * t
        specs: list[dict] = []

        def groove_depth() -> float:
            return min(6.0, max(1.0, t - 1.0))

        left_grooves: list[tuple] = []
        right_grooves: list[tuple] = []
        if self.has_groove:
            gd, gw, gz = groove_depth(), 4.0, 16.0
            left_grooves = [(t - gd, 0, gz, gd, h, gw)]
            right_grooves = [(0, 0, gz, gd, h, gw)]
        specs.append({
            "role": "left",
            "name": f"Боковина левая {int(h)}x{int(d)}x{int(t)}",
            "x": bx, "y": by, "z": bz,
            "width": t, "height": h, "depth": d,
            "grooves": left_grooves,
        })
        specs.append({
            "role": "right",
            "name": f"Боковина правая {int(h)}x{int(d)}x{int(t)}",
            "x": bx + w - t, "y": by, "z": bz,
            "width": t, "height": h, "depth": d,
            "grooves": right_grooves,
        })

        bottom_grooves: list[tuple] = []
        if self.has_groove:
            gd = groove_depth()
            bottom_grooves = [(0, t - gd, 16, inner_w, gd, 4)]
        specs.append({
            "role": "bottom",
            "name": f"Дно вкладное {int(inner_w)}x{int(d)}x{int(t)}",
            "x": bx + t, "y": by, "z": bz,
            "width": inner_w, "height": t, "depth": d,
            "grooves": bottom_grooves,
        })

        if self.is_upper:
            top_grooves: list[tuple] = []
            if self.has_groove:
                gd = groove_depth()
                top_grooves = [(0, 0, 16, inner_w, gd, 4)]
            specs.append({
                "role": "top",
                "name": f"Крышка вкладная {int(inner_w)}x{int(d)}x{int(t)}",
                "x": bx + t, "y": by + h - t, "z": bz,
                "width": inner_w, "height": t, "depth": d,
                "grooves": top_grooves,
            })
        else:
            tsarga_d = 100.0
            specs.append({
                "role": "tsarga_front",
                "name": f"Царга передняя {int(inner_w)}x100x{int(t)}",
                "x": bx + t, "y": by + h - t, "z": bz + d - tsarga_d,
                "width": inner_w, "height": t, "depth": tsarga_d,
                "grooves": [],
            })
            specs.append({
                "role": "tsarga_back",
                "name": f"Царга задняя {int(inner_w)}x100x{int(t)}",
                "x": bx + t, "y": by + h - t, "z": bz + 20,
                "width": inner_w, "height": t, "depth": tsarga_d,
                "grooves": [],
            })

        if self.shelves_count > 0:
            step_y = h / (self.shelves_count + 1)
            shelf_w = inner_w - 2
            shelf_d = d - 35
            for i in range(self.shelves_count):
                sy = by + step_y * (i + 1) - t / 2
                specs.append({
                    "role": f"shelf_{i}",
                    "name": f"Полка {i+1} ({int(shelf_w)}x{int(shelf_d)}x{int(t)})",
                    "x": bx + t + 1, "y": sy, "z": bz + 22,
                    "width": shelf_w, "height": t, "depth": shelf_d,
                    "grooves": [],
                })

        if self.has_facade:
            gap = 2.0
            fw = w - 2 * gap
            fh = h - 2 * gap
            specs.append({
                "role": "facade",
                "name": f"Фасад {int(fw)}x{int(fh)}x{int(t)}",
                "x": bx + gap, "y": by + gap, "z": bz + d + 2,
                "width": fw, "height": fh, "depth": t,
                "grooves": [],
                "default_color": (0.42, 0.32, 0.25),
            })

        return specs

    @staticmethod
    def _remap_local_coord(old_c: float, old_size: float, new_size: float) -> float:
        """Привязка одиночной координаты к ближайшему ребру при смене габарита."""
        if old_size <= 1e-9:
            return float(old_c)
        dist_min = float(old_c)
        dist_max = float(old_size) - float(old_c)
        if dist_min <= dist_max:
            return dist_min
        return float(new_size) - dist_max

    @staticmethod
    def _stretch_coord(
        c: float, lo: float, hi: float, old_dim: float, new_dim: float
    ) -> float:
        """Растягивает координату в ряду отверстий [lo..hi] с сохранением краевых отступов."""
        if old_dim <= 1e-9:
            return float(c)
        if hi - lo < 1e-9:
            return float(c) if c <= old_dim / 2.0 else float(new_dim) - (float(old_dim) - float(c))
        new_lo = float(lo)
        new_hi = float(new_dim) - (float(old_dim) - float(hi))
        return new_lo + (float(c) - float(lo)) * (new_hi - new_lo) / (float(hi) - float(lo))

    @staticmethod
    def _remap_holes(
        holes: list,
        old_w: float, old_h: float, old_d: float,
        new_w: float, new_h: float, new_d: float,
    ) -> list:
        """Пересчитывает локальные координаты отверстий под новые габариты панели.

        Группы из >= 2 отверстий, лежащих на одной прямой вдоль изменившегося габарита
        (одинаковая ось сверления и поперечные координаты), растягиваются между крайними
        отверстиями с сохранением отступов от краёв. Одиночные отверстия привязываются
        к ближайшему ребру.
        """
        if not holes:
            return list(holes)
        if (
            abs(old_w - new_w) < 1e-9
            and abs(old_h - new_h) < 1e-9
            and abs(old_d - new_d) < 1e-9
        ):
            return list(holes)

        old_dims = (float(old_w), float(old_h), float(old_d))
        new_dims = (float(new_w), float(new_h), float(new_d))

        valid_indices: list[int] = []
        old_coords: dict[int, tuple[float, float, float]] = {}
        drill_axes: dict[int, str] = {}

        for idx, h in enumerate(holes):
            if not h or len(h) < 3:
                continue
            valid_indices.append(idx)
            old_coords[idx] = (float(h[0]), float(h[1]), float(h[2]))
            ax = str(h[5]).upper() if len(h) >= 6 else "Z"
            drill_axes[idx] = ax

        new_coords: dict[int, list[float]] = {
            idx: list(old_coords[idx]) for idx in valid_indices
        }

        for axis_idx in range(3):
            old_dim = old_dims[axis_idx]
            new_dim = new_dims[axis_idx]
            if abs(old_dim - new_dim) < 1e-9:
                continue

            other_a, other_b = [i for i in range(3) if i != axis_idx]
            groups: dict[tuple[str, float, float], list[int]] = {}
            for idx in valid_indices:
                oc = old_coords[idx]
                key = (drill_axes[idx], round(oc[other_a], 3), round(oc[other_b], 3))
                groups.setdefault(key, []).append(idx)

            for grp in groups.values():
                if len(grp) >= 2:
                    vals = [old_coords[i][axis_idx] for i in grp]
                    lo, hi = min(vals), max(vals)
                    for i in grp:
                        new_coords[i][axis_idx] = ParametricCabinet._stretch_coord(
                            old_coords[i][axis_idx], lo, hi, old_dim, new_dim
                        )
                else:
                    i = grp[0]
                    new_coords[i][axis_idx] = ParametricCabinet._remap_local_coord(
                        old_coords[i][axis_idx], old_dim, new_dim
                    )

        remapped = []
        for idx, h in enumerate(holes):
            if idx not in new_coords:
                remapped.append(h)
                continue
            lx, ly, lz = new_coords[idx]
            rest = list(h[3:])
            if len(rest) >= 2:
                radius = float(rest[0])
                depth = float(rest[1])
                axis = rest[2] if len(rest) >= 3 else "Z"
                ax = str(axis).upper()
                if ax == "X" and abs(depth - old_w) < 1.5:
                    depth = float(new_w)
                elif ax == "Y" and abs(depth - old_h) < 1.5:
                    depth = float(new_h)
                elif ax == "Z" and abs(depth - old_d) < 1.5:
                    depth = float(new_d)
                lx = max(0.0, min(lx, max(0.0, new_w)))
                ly = max(0.0, min(ly, max(0.0, new_h)))
                lz = max(0.0, min(lz, max(0.0, new_d)))
                remapped.append((lx, ly, lz, radius, depth, axis) + tuple(rest[3:]))
            else:
                remapped.append((lx, ly, lz) + tuple(h[3:]))
        return remapped

    def _update_panel_from_spec(self, panel: Panel, spec: dict, pos_num: str) -> None:
        """Обновляет геометрию существующей панели, сохраняя user-данные."""
        old_w = float(panel.width)
        old_h = float(panel.height)
        old_d = float(panel.depth)

        panel.role = spec["role"]
        panel.x = float(spec["x"])
        panel.y = float(spec["y"])
        panel.z = float(spec["z"])
        panel.width = float(spec["width"])
        panel.height = float(spec["height"])
        panel.depth = float(spec["depth"])
        panel.pos_num = pos_num

        new_name = spec["name"]
        old_name = (panel.name or "").strip()
        is_auto_name = (
            not old_name
            or bool(
                re.match(
                    r"^(Боковина левая|Боковина правая|Дно вкладное|Крышка вкладная|"
                    r"Царга передняя|Царга задняя|Полка \d+|Фасад)\s*\(?\d+x\d+x\d+\)?$",
                    old_name,
                )
            )
        )
        if is_auto_name:
            panel.name = new_name

        # Структурные пазы корпуса пересчитываем
        panel.grooves = [tuple(g) for g in spec.get("grooves", [])]
        panel._block = self

        # Ручные отверстия всегда ремапим под новые габариты (ревизия 4 §1.1).
        # Отверстия стыков сбрасываем — apply_joints(self) в конце rebuild() построит заново.
        if getattr(self, "joints", None):
            manual = panel.get_manual_holes()
            panel.joint_hole_map = {}
            panel.holes = self._remap_holes(
                manual,
                old_w, old_h, old_d,
                panel.width, panel.height, panel.depth,
            )
        else:
            # Без JointRecord: все отверстия (ряды / привязка к рёбрам)
            panel.holes = self._remap_holes(
                list(getattr(panel, "holes", []) or []),
                old_w, old_h, old_d,
                panel.width, panel.height, panel.depth,
            )

        dims = (panel.width, panel.height, panel.depth)
        panel.thickness_axis = int(min(range(3), key=lambda i: dims[i]))

        panel._gl_arrays = None
        panel.rebuild_geometry()

    def _create_panel_from_spec(self, spec: dict, pos_num: str) -> Panel:
        p = Panel(
            name=spec["name"],
            x=spec["x"], y=spec["y"], z=spec["z"],
            width=spec["width"], height=spec["height"], depth=spec["depth"],
            pos_num=pos_num,
            role=spec["role"],
            rebuild=False,
        )
        p._block = self
        p.grooves = [tuple(g) for g in spec.get("grooves", [])]
        if spec.get("role") == "facade" and "default_color" in spec:
            p.color = spec["default_color"]
        p.rebuild_geometry()
        return p

    def rebuild(self, restore_by_role: dict[str, dict] | None = None):
        """Diff-пересборка по role: не уничтожает присадку, кромку, материал."""
        specs = self._desired_specs()
        desired_roles = {s["role"] for s in specs}

        by_role: dict[str, Panel] = {}
        orphans: list[Panel] = []
        for p in self.panels:
            role = getattr(p, "role", "") or ""
            if not role:
                role = self._infer_role_from_name(getattr(p, "name", ""))
                if role:
                    p.role = role
            if role and role not in by_role:
                by_role[role] = p
            else:
                orphans.append(p)

        new_panels: list[Panel] = []
        idx = 1

        def next_num() -> str:
            nonlocal idx
            res = f"{self.pos_num}.{idx}"
            idx += 1
            return res

        for spec in specs:
            role = spec["role"]
            pos = next_num()
            existing = by_role.pop(role, None)
            if existing is None and restore_by_role and role in restore_by_role:
                existing = Panel.from_dict(restore_by_role[role], rebuild=False)
            if existing is not None:
                was_selected = bool(getattr(existing, "selected", False))
                self._update_panel_from_spec(existing, spec, pos)
                existing.selected = was_selected
                new_panels.append(existing)
            else:
                new_panels.append(self._create_panel_from_spec(spec, pos))

        for p in orphans:
            role = getattr(p, "role", "") or ""
            if role and role not in desired_roles:
                continue
            if not role:
                p.pos_num = next_num()
                new_panels.append(p)

        self.panels = new_panels
        for p in self.panels:
            p._block = self
        if getattr(self, "joints", None):
            from core.joint import apply_joints

            apply_joints(self)
