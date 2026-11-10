"""Менеджер сцены (SceneController), связывающий чистую модель Panel с CatalogService и GeometryService (ревизия 2, п. 2.1)."""

from __future__ import annotations

from typing import Optional, Tuple

from core.logging_setup import get_logger
from models.panel import (
    DEFAULT_MATERIAL_COLOR,
    DEFAULT_MATERIAL_ID,
    DEFAULT_MATERIAL_NAME,
    Block,
    Panel,
)

_log = get_logger("scene_controller")
_EDGE_SIDES = ("top", "bottom", "left", "right")


class SceneController:
    """Координирует работу с материалами, кромками (CatalogService) и геометрией (GeometryService).

    Модель `Panel` остаётся чистым `@dataclass` без прямых обращений к сервисам.
    """

    _instance: Optional["SceneController"] = None

    def __init__(self, catalog_service=None, geometry_service=None):
        self._catalog_service = catalog_service
        self._geometry_service = geometry_service

    @classmethod
    def instance(cls) -> "SceneController":
        if cls._instance is None:
            cls._instance = SceneController()
            cls._instance.bind_to_panel_class()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        Panel._scene_controller = None
        Panel._controller_unbound = False

    def bind_to_panel_class(self) -> None:
        """Регистрирует этот контроллер как активный обработчик для экземпляров Panel."""
        Panel._controller_unbound = False
        Panel._scene_controller = self

    @staticmethod
    def unbind_from_panel_class() -> None:
        """Отвязывает контроллер от класса Panel (чистый dataclass-режим для изолированных тестов)."""
        Panel._scene_controller = None
        Panel._controller_unbound = True

    @property
    def catalog(self):
        if self._catalog_service is not None:
            return self._catalog_service
        try:
            from core.catalog import CatalogService
            return CatalogService.instance()
        except Exception:
            _log.exception("Failed to acquire CatalogService instance")
            return None

    @property
    def geometry(self):
        if self._geometry_service is not None:
            return self._geometry_service
        try:
            from core.geometry_service import GeometryService
            return GeometryService.instance()
        except Exception:
            _log.exception("Failed to acquire GeometryService instance")
            return None

    # ── Материалы и толщина ───────────────────────────────────

    def resolve_material(
        self,
        material_id: Optional[str] = None,
        legacy_name: Optional[str] = None,
    ) -> Tuple[str, str, Tuple[float, float, float], float, bool]:
        """Возвращает (material_id, display_name, color_rgb, thickness_mm, found_exact).

        При отсутствии каталога или записи возвращает безопасный fallback.
        """
        cat = self.catalog
        if cat is None:
            return (
                material_id or DEFAULT_MATERIAL_ID,
                legacy_name or DEFAULT_MATERIAL_NAME,
                DEFAULT_MATERIAL_COLOR,
                16.0,
                False,
            )
        try:
            mat = None
            found_exact = False
            if material_id:
                mat = cat.get_material(material_id)
                if mat is not None:
                    found_exact = True
            if mat is None and legacy_name:
                q = legacy_name.strip().lower()
                for m in cat.list_materials():
                    if q in m.name.lower() or q in m.display_name.lower() or q in m.sku.lower():
                        mat = m
                        found_exact = True
                        break
            if mat is None:
                mat = cat.default_material()
            if mat is not None:
                return (
                    mat.id,
                    mat.display_name,
                    mat.color_rgb,
                    float(mat.thickness_mm),
                    found_exact,
                )
        except Exception:
            _log.exception("Material resolution failed for id=%s name=%s", material_id, legacy_name)
        return (
            DEFAULT_MATERIAL_ID,
            DEFAULT_MATERIAL_NAME,
            DEFAULT_MATERIAL_COLOR,
            16.0,
            False,
        )

    def material_thickness_mm(self, panel: Panel) -> float:
        """Толщина материала детали из каталога (мм); fallback — кэш на панели или текущий габарит."""
        cat = self.catalog
        mid = getattr(panel, "material_id", None)
        if cat is not None and mid:
            try:
                mat = cat.get_material(mid)
                if mat is not None and float(mat.thickness_mm) > 0:
                    t = float(mat.thickness_mm)
                    panel.material_thickness = t
                    return t
            except Exception:
                _log.exception("Failed to read material thickness for %s", mid)
        cached = float(getattr(panel, "material_thickness", 0.0) or 0.0)
        if cached > 0:
            return cached
        return panel.get_thickness()

    def lock_thickness_to_material(self, panel: Panel) -> bool:
        """Выставляет габарит панели по оси thickness_axis равным толщине материала."""
        t = float(self.material_thickness_mm(panel))
        if t <= 0:
            return False
        ax = int(getattr(panel, "thickness_axis", 0)) % 3
        cur = (panel.width, panel.height, panel.depth)[ax]
        if abs(cur - t) < 1e-9:
            return False
        if ax == 0:
            panel.width = t
        elif ax == 1:
            panel.height = t
        else:
            panel.depth = t
        return True

    def apply_material(self, panel: Panel, material_id: str, *, rebuild: bool = False) -> bool:
        """Назначает материал из каталога по id, обновляя имя, цвет, толщину и кэш панели."""
        cat = self.catalog
        if cat is None:
            return False
        try:
            mat = cat.get_material(material_id)
            if mat is None:
                return False
            panel.material_id = mat.id
            panel.material = mat.display_name
            panel.color = mat.color_rgb
            panel.material_thickness = float(mat.thickness_mm)
            panel.missing_material_id = ""
            self.lock_thickness_to_material(panel)
            if rebuild:
                self.rebuild_geometry(panel)
            return True
        except Exception:
            _log.exception("apply_material failed for %s", material_id)
            return False

    def apply_material_to_block(self, block: Block, material_id: str, *, rebuild: bool = True) -> int:
        """Назначает материал всем панелям блока. Возвращает число обновлённых панелей."""
        count = 0
        for p in getattr(block, "panels", None) or []:
            if self.apply_material(p, material_id, rebuild=rebuild):
                count += 1
        return count

    # ── Кромки ────────────────────────────────────────────────

    def set_edge(self, panel: Panel, side: str, edge_band_id: Optional[str]) -> bool:
        """Назначает кромку на торец ('top', 'bottom', 'left', 'right') и синхронизирует кэш толщины."""
        if side not in panel.edges:
            return False
        eid = str(edge_band_id or "")
        panel.edges[side] = eid
        if not isinstance(getattr(panel, "missing_edges", None), dict):
            panel.missing_edges = {}
        if not isinstance(getattr(panel, "edge_thicknesses", None), dict):
            panel.edge_thicknesses = {}

        if not eid:
            panel.missing_edges.pop(side, None)
            panel.edge_thicknesses.pop(side, None)
            return True

        cat = self.catalog
        if cat is not None:
            try:
                eb = cat.get_edge(eid)
                if eb is not None:
                    panel.missing_edges.pop(side, None)
                    panel.edge_thicknesses[side] = float(eb.thickness_mm)
                else:
                    panel.missing_edges[side] = eid
                    panel.edge_thicknesses.pop(side, None)
            except Exception:
                _log.exception("Failed to check edge %s in catalog", eid)
                panel.missing_edges.pop(side, None)
        return True

    def get_edge_thickness(self, panel: Panel, side: str) -> float:
        """Возвращает толщину кромки в мм на указанном торце детали."""
        edge_id = panel.edges.get(side)
        if not edge_id:
            return 0.0
        cat = self.catalog
        if cat is not None:
            try:
                eb = cat.get_edge_band(edge_id)
                if eb is not None:
                    t = float(eb.thickness_mm)
                    if isinstance(getattr(panel, "edge_thicknesses", None), dict):
                        panel.edge_thicknesses[side] = t
                    return t
            except Exception:
                _log.exception("Failed to get edge thickness for %s", edge_id)
        if isinstance(getattr(panel, "edge_thicknesses", None), dict):
            return float(panel.edge_thicknesses.get(side, 0.0))
        return 0.0

    def sync_panel_catalog(
        self,
        panel: Panel,
        *,
        requested_material_id: Optional[str] = None,
        raw_missing_material_id: str = "",
        raw_missing_edges: Optional[dict[str, str]] = None,
    ) -> None:
        """Проверяет ссылки панели на материал и кромки в каталоге (при загрузке .b3d и др.)."""
        panel.missing_material_id = ""
        panel.missing_edges = {}
        raw_me_dict = raw_missing_edges if isinstance(raw_missing_edges, dict) else {}
        req_mat = str(requested_material_id or "").strip()
        raw_missing = str(raw_missing_material_id or "").strip()

        cat = self.catalog
        if cat is None:
            if req_mat:
                panel.missing_material_id = raw_missing or ""
            for side in _EDGE_SIDES:
                raw_me = str(raw_me_dict.get(side) or "").strip()
                if raw_me:
                    panel.missing_edges[side] = raw_me
            return

        try:
            if req_mat and cat.get_material(req_mat) is None:
                panel.missing_material_id = req_mat
            elif raw_missing and cat.get_material(raw_missing) is None:
                panel.missing_material_id = raw_missing
            elif raw_missing and cat.get_material(raw_missing) is not None:
                panel.missing_material_id = ""

            for side in _EDGE_SIDES:
                eid = str(panel.edges.get(side) or "").strip()
                raw_me = str(raw_me_dict.get(side) or "").strip()
                if eid:
                    eb = cat.get_edge(eid)
                    if eb is None:
                        panel.missing_edges[side] = eid
                        panel.edge_thicknesses.pop(side, None)
                    else:
                        panel.edge_thicknesses[side] = float(eb.thickness_mm)
                elif raw_me:
                    eb = cat.get_edge(raw_me)
                    if eb is None:
                        panel.missing_edges[side] = raw_me
                        panel.edges[side] = raw_me
                    else:
                        panel.edges[side] = raw_me
                        panel.edge_thicknesses[side] = float(eb.thickness_mm)
        except Exception:
            _log.exception("Catalog check failed while syncing panel material_id=%s", req_mat)
            if req_mat:
                panel.missing_material_id = raw_missing or ""
            for side in _EDGE_SIDES:
                raw_me = str(raw_me_dict.get(side) or "").strip()
                if raw_me:
                    panel.missing_edges[side] = raw_me

    # ── Геометрия ─────────────────────────────────────────────

    def rebuild_geometry(self, panel: Panel, sync: bool = False) -> None:
        """Запрашивает пересборку геометрии панели через GeometryService."""
        svc = self.geometry
        if svc is not None:
            svc.request_rebuild(panel, sync=sync)
        else:
            panel.geometry_generation = int(getattr(panel, "geometry_generation", 0)) + 1
            panel.geometry_pending = False
            panel._gl_arrays = None

    def rebuild_block_geometry(self, block: Block, sync: bool = False) -> None:
        for p in getattr(block, "panels", None) or []:
            self.rebuild_geometry(p, sync=sync)

    # ── Инициализация новой панели ────────────────────────────

    def on_panel_created(
        self,
        panel: Panel,
        *,
        requested_material_id: Optional[str] = None,
        legacy_material: Optional[str] = None,
        explicit_thickness_axis: Optional[int] = None,
        rebuild: bool = True,
    ) -> None:
        """Обогащает созданную панель данными из CatalogService и при необходимости строит геометрию."""
        mid, mname, mcolor, mat_t, _found = self.resolve_material(
            material_id=requested_material_id,
            legacy_name=legacy_material or None,
        )
        panel.material_id = mid
        panel.material = mname
        panel.color = mcolor
        panel.material_thickness = mat_t

        dims0 = (panel.width, panel.height, panel.depth)
        if explicit_thickness_axis is not None:
            panel.thickness_axis = int(explicit_thickness_axis) % 3
        else:
            min_ax = int(min(range(3), key=lambda i: dims0[i]))
            if mat_t > 0 and dims0[min_ax] + 1e-6 < mat_t:
                matched = [i for i in range(3) if abs(dims0[i] - mat_t) < 1e-3]
                panel.thickness_axis = matched[0] if matched else min_ax
            else:
                panel.thickness_axis = min_ax

        # Синхронизируем кромки, если они были переданы при создании
        for side in _EDGE_SIDES:
            eid = panel.edges.get(side, "")
            if eid:
                self.set_edge(panel, side, eid)

        if rebuild:
            self.rebuild_geometry(panel, sync=False)


# Инициализируем и привязываем контроллер по умолчанию при импорте модуля
SceneController.instance()
