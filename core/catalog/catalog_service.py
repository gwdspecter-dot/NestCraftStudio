"""
Единая точка доступа к каталогу материалов и крепежа.
Синглтон — загружается один раз при первом обращении.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from core.catalog.db import connect, get_default_db_path
from core.catalog.models import Material, EdgeBand, Fastener, FastenerType, MaterialCategory, Supplier
from core.catalog.material_repo import MaterialRepository
from core.catalog.fastener_repo import FastenerRepository
from core.catalog.seed import seed_if_empty
from core.logging_setup import get_logger

_log = get_logger("catalog")


class CatalogService:
    """Фасад над репозиториями. Использовать через CatalogService.instance()."""

    _instance: Optional["CatalogService"] = None

    def __init__(self, db_path: Optional[Path | str] = None):
        self._db_path = Path(db_path) if db_path else get_default_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._materials: Optional[MaterialRepository] = None
        self._fasteners: Optional[FastenerRepository] = None
        # In-memory кэш (всегда инициализирован — без hasattr)
        self._mat_cache: dict[str, Material] = {}
        self._edge_cache: dict[str, EdgeBand] = {}
        self._fst_cache: dict[str, Fastener] = {}

    # ── Singleton ─────────────────────────────────────────────

    @classmethod
    def instance(cls, db_path: Optional[Path | str] = None) -> "CatalogService":
        if cls._instance is None:
            cls._instance = CatalogService(db_path)
            cls._instance.open()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Закрыть и сбросить синглтон (для тестов)."""
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None

    # ── Lifecycle ─────────────────────────────────────────────

    def open(self) -> None:
        if self._conn is not None:
            return
        self._conn = connect(self._db_path)
        seed_if_empty(self._conn)
        self._materials = MaterialRepository(self._conn)
        self._fasteners = FastenerRepository(self._conn)
        self._mat_cache.clear()
        self._edge_cache.clear()
        self._fst_cache.clear()
        self.ensure_default_groups()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._materials = None
            self._fasteners = None
            self._mat_cache.clear()
            self._edge_cache.clear()
            self._fst_cache.clear()

    def commit(self) -> None:
        if self._conn:
            self._conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Materials ─────────────────────────────────────────────

    def get_material(self, material_id: str) -> Optional[Material]:
        if material_id in self._mat_cache:
            return self._mat_cache[material_id]
        m = self._materials.get(material_id)
        if m:
            self._mat_cache[material_id] = m
        return m

    def get_material_by_sku(self, sku: str) -> Optional[Material]:
        return self._materials.get_by_sku(sku)

    def list_materials(
        self,
        *,
        material_type: Optional[str] = None,
        thickness_mm: Optional[float] = None,
        category_id: Optional[str] = None,
        group_ids: Optional[list] = None,
        active_only: bool = True,
    ) -> List[Material]:
        return self._materials.list(
            material_type=material_type,
            thickness_mm=thickness_mm,
            category_id=category_id,
            group_ids=group_ids,
            active_only=active_only,
        )

    def search_materials(self, query: str) -> List[Material]:
        return self._materials.search(query)

    def default_material(self) -> Material:
        """Материал по умолчанию для новых панелей (МИСТ VL 16 мм)."""
        m = self.get_material("mat_mist_vl_16")
        if m:
            return m
        # fallback — первый ЛДСП 16 мм
        items = self.list_materials(material_type="ldsp", thickness_mm=16.0)
        if items:
            return items[0]
        items = self.list_materials()
        if not items:
            raise RuntimeError("Каталог материалов пуст")
        return items[0]

    def insert_material(self, m: Material) -> None:
        """Добавить материал и обновить кэш."""
        self._materials.insert(m)
        self.commit()
        self._mat_cache[m.id] = m

    def update_material(self, m: Material) -> None:
        """Обновить материал и инвалидировать/обновить кэш."""
        self._materials.update(m)
        self.commit()
        self._mat_cache[m.id] = m

    def delete_material(self, material_id: str) -> bool:
        """Удалить материал (или деактивировать — по правилам репозитория)."""
        ok = self._materials.delete(material_id)
        if ok:
            self.commit()
            self._mat_cache.pop(material_id, None)
        return ok

    # ── Edge bands ────────────────────────────────────────────

    def get_edge(self, edge_id: str) -> Optional[EdgeBand]:
        if edge_id in self._edge_cache:
            return self._edge_cache[edge_id]
        e = self._materials.get_edge(edge_id)
        if e:
            self._edge_cache[edge_id] = e
        return e

    def get_edge_band(self, edge_id: str) -> Optional[EdgeBand]:
        """Алиас для get_edge."""
        return self.get_edge(edge_id)

    def list_edges(
        self,
        *,
        group_ids: Optional[list] = None,
        active_only: bool = True,
    ) -> List[EdgeBand]:
        return self._materials.list_edges(group_ids=group_ids, active_only=active_only)

    def list_edge_bands(self, *, active_only: bool = True) -> List[EdgeBand]:
        """Алиас для list_edges."""
        return self.list_edges(active_only=active_only)

    def insert_edge(self, e: EdgeBand) -> None:
        self._materials.insert_edge(e)
        self.commit()
        self._edge_cache[e.id] = e

    def update_edge(self, e: EdgeBand) -> None:
        self._materials.update_edge(e)
        self.commit()
        self._edge_cache[e.id] = e

    def delete_edge(self, edge_id: str) -> bool:
        ok = self._materials.delete_edge(edge_id)
        if ok:
            self.commit()
            self._edge_cache.pop(edge_id, None)
        return ok

    def default_edge(self, thickness_mm: float = 0.4) -> Optional[EdgeBand]:
        """Возвращает кромку по умолчанию (ПВХ 0.4 мм)."""
        edges = self.list_edges()
        for e in edges:
            if abs(e.thickness_mm - thickness_mm) < 0.1:
                return e
        return edges[0] if edges else None

    # ── Fasteners ─────────────────────────────────────────────

    def get_fastener(self, fastener_id: str) -> Optional[Fastener]:
        if fastener_id in self._fst_cache:
            return self._fst_cache[fastener_id]
        f = self._fasteners.get(fastener_id)
        if f:
            self._fst_cache[fastener_id] = f
        return f

    def list_fasteners(
        self,
        *,
        type_code: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Fastener]:
        return self._fasteners.list(type_code=type_code, active_only=active_only)

    def list_fastener_types(self) -> List[FastenerType]:
        return self._fasteners.list_types()

    def default_fastener(self, type_code: str = "confirmat") -> Optional[Fastener]:
        items = self.list_fasteners(type_code=type_code)
        return items[0] if items else None

    def insert_fastener(self, f: Fastener) -> None:
        self._fasteners.insert(f)
        self.commit()
        self._fst_cache[f.id] = f

    def update_fastener(self, f: Fastener) -> None:
        self._fasteners.update(f)
        self.commit()
        self._fst_cache[f.id] = f

    def delete_fastener(self, fastener_id: str) -> bool:
        """Мягкое удаление, если репозиторий поддерживает; иначе deactivate."""
        ok = False
        if hasattr(self._fasteners, "delete"):
            ok = bool(self._fasteners.delete(fastener_id))
        elif hasattr(self._fasteners, "set_active"):
            ok = bool(self._fasteners.set_active(fastener_id, False))
        else:
            f = self.get_fastener(fastener_id)
            if f is not None:
                f.is_active = False
                self._fasteners.update(f)
                ok = True
        if ok:
            self.commit()
            self._fst_cache.pop(fastener_id, None)
        return ok

    # ── Meta ──────────────────────────────────────────────────

    def list_categories(self) -> List[MaterialCategory]:
        return self._materials.list_categories()

    def list_suppliers(self) -> List[Supplier]:
        return self._materials.list_suppliers()

    # ── Groups tree ───────────────────────────────────────────

    def list_groups(self):
        return self._materials.list_groups()

    def get_group(self, group_id: str):
        return self._materials.get_group(group_id)

    def insert_group(self, g) -> None:
        self._materials.insert_group(g)
        self.commit()

    def update_group(self, g) -> None:
        self._materials.update_group(g)
        self.commit()

    def delete_group(self, group_id: str) -> bool:
        ok = self._materials.delete_group(group_id)
        if ok:
            self.commit()
            self._mat_cache.clear()
        return ok

    def descendant_group_ids(self, group_id: str) -> list:
        return self._materials.descendant_group_ids(group_id)

    def ensure_default_groups(self) -> None:
        """Создать стандартные группы при необходимости и привязать позиции без group_id."""
        if self._materials is None:
            return
        from core.catalog.models import CatalogGroup
        try:
            existing = {g.id for g in self._materials.list_groups()}
        except Exception:
            _log.exception("Catalog groups table unavailable")
            return
        defaults = [
            ("grp_sheet", "Листовые материалы", None, 10, "material"),
            ("grp_edge", "Кромочные материалы", None, 20, "edge"),
            ("grp_hardware", "Фурнитура", None, 30, "fastener"),
            ("grp_ldsp", "ЛДСП", "grp_sheet", 10, "material"),
            ("grp_mdf", "МДФ", "grp_sheet", 20, "material"),
            ("grp_hdf", "ХДФ", "grp_sheet", 30, "material"),
            ("grp_plywood", "Фанера", "grp_sheet", 40, "material"),
            ("grp_sheet_other", "Прочее", "grp_sheet", 90, "material"),
            ("grp_pvc", "ПВХ", "grp_edge", 10, "edge"),
            ("grp_abs", "АБС", "grp_edge", 20, "edge"),
            ("grp_edge_other", "Прочее", "grp_edge", 90, "edge"),
            ("grp_fasteners", "Крепёж корпусной", "grp_hardware", 10, "fastener"),
            ("grp_shelf", "Полкодержатели", "grp_hardware", 20, "fastener"),
            ("grp_hw_other", "Прочее", "grp_hardware", 90, "fastener"),
        ]
        for gid, name, parent, order, scope in defaults:
            if gid in existing:
                continue
            try:
                self._materials.insert_group(CatalogGroup(
                    id=gid, name=name, parent_id=parent,
                    sort_order=order, scope=scope, is_builtin=True,
                ))
            except Exception:
                _log.exception("Catalog group ensure failed")
        type_map = {
            "ldsp": "grp_ldsp", "mdf": "grp_mdf", "hdf": "grp_hdf",
            "plywood": "grp_plywood", "solid": "grp_sheet_other", "other": "grp_sheet_other",
        }
        try:
            for m in self._materials.list(active_only=False):
                if not m.group_id:
                    m.group_id = type_map.get(m.material_type, "grp_sheet_other")
                    self._materials.update(m)
            for e in self._materials.list_edges(active_only=False):
                if not getattr(e, "group_id", None):
                    e.group_id = {"pvc": "grp_pvc", "abs": "grp_abs"}.get(
                        e.material_type, "grp_edge_other"
                    )
                    self._materials.update_edge(e)
            if self._fasteners is not None and self._conn is not None:
                self._conn.execute(
                    "UPDATE fasteners SET group_id = 'grp_fasteners' "
                    "WHERE group_id IS NULL OR group_id = ''"
                )
        except Exception:
            _log.exception("Catalog commit after seed failed")
        self.commit()

    def stats(self) -> dict:
        """Краткая статистика каталога."""
        return {
            "materials": len(self.list_materials(active_only=False)),
            "edges": len(self.list_edges(active_only=False)),
            "fasteners": len(self.list_fasteners(active_only=False)),
            "categories": len(self.list_categories()),
            "groups": len(self.list_groups()),
            "suppliers": len(self.list_suppliers()),
            "db_path": str(self._db_path),
        }
