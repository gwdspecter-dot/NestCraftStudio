"""
Репозиторий материалов и кромки.
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from core.catalog.models import (
    Material, EdgeBand, MaterialCategory, Supplier, CatalogGroup,
)


def _row_keys(row: sqlite3.Row) -> set:
    try:
        return set(row.keys())
    except Exception:
        return set()


def _row_to_material(row: sqlite3.Row) -> Material:
    keys = _row_keys(row)
    return Material(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        category_id=row["category_id"],
        group_id=row["group_id"] if "group_id" in keys else None,
        supplier_id=row["supplier_id"],
        material_type=row["material_type"],
        thickness_mm=row["thickness_mm"],
        density=row["density"] or 0.0,
        color_name=row["color_name"] or "",
        color_rgb=(row["color_r"], row["color_g"], row["color_b"]),
        texture_path=row["texture_path"] or "",
        grain_direction=row["grain_direction"] or "none",
        price_per_m2=row["price_per_m2"] or 0.0,
        currency=row["currency"] or "RUB",
        max_drill_depth_face=row["max_drill_depth_face"] or 0.0,
        max_drill_depth_edge=row["max_drill_depth_edge"] or 0.0,
        is_builtin=bool(row["is_builtin"]),
        is_active=bool(row["is_active"]),
        notes=row["notes"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_edge(row: sqlite3.Row) -> EdgeBand:
    keys = _row_keys(row)
    return EdgeBand(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        group_id=row["group_id"] if "group_id" in keys else None,
        supplier_id=row["supplier_id"],
        material_type=row["material_type"],
        thickness_mm=row["thickness_mm"],
        width_mm=row["width_mm"],
        color_name=row["color_name"] or "",
        color_rgb=(row["color_r"], row["color_g"], row["color_b"]),
        texture_path=row["texture_path"] or "",
        price_per_m=row["price_per_m"] or 0.0,
        currency=row["currency"] or "RUB",
        is_builtin=bool(row["is_builtin"]),
        is_active=bool(row["is_active"]),
        notes=row["notes"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class MaterialRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ── Materials ──────────────────────────────────────────────

    def get(self, material_id: str) -> Optional[Material]:
        row = self._conn.execute(
            "SELECT * FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        return _row_to_material(row) if row else None

    def get_by_sku(self, sku: str) -> Optional[Material]:
        row = self._conn.execute(
            "SELECT * FROM materials WHERE sku = ?", (sku,)
        ).fetchone()
        return _row_to_material(row) if row else None

    def list(
        self,
        *,
        material_type: Optional[str] = None,
        thickness_mm: Optional[float] = None,
        category_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
        active_only: bool = True,
    ) -> List[Material]:
        clauses = []
        params: list = []

        if active_only:
            clauses.append("is_active = 1")
        if material_type:
            clauses.append("material_type = ?")
            params.append(material_type)
        if thickness_mm is not None:
            clauses.append("thickness_mm = ?")
            params.append(thickness_mm)
        if category_id:
            clauses.append("category_id = ?")
            params.append(category_id)
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            clauses.append(f"group_id IN ({placeholders})")
            params.extend(group_ids)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM materials{where} ORDER BY name, thickness_mm"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_material(r) for r in rows]

    def search(self, query: str, *, active_only: bool = True) -> List[Material]:
        """Поиск по имени, артикулу и цвету (регистронезависимый, в т.ч. кириллица)."""
        q = query.strip().lower()
        if not q:
            return self.list(active_only=active_only)
        # SQLite LOWER() не умеет кириллицу без ICU — фильтруем в Python
        candidates = self.list(active_only=active_only)
        return [
            m for m in candidates
            if q in m.name.lower()
            or q in m.sku.lower()
            or q in m.color_name.lower()
        ]

    def insert(self, m: Material) -> None:
        self._conn.execute(
            """
            INSERT INTO materials (
                id, sku, name, category_id, group_id, supplier_id, material_type,
                thickness_mm, density, color_name, color_r, color_g, color_b,
                texture_path, grain_direction, price_per_m2, currency,
                max_drill_depth_face, max_drill_depth_edge,
                is_builtin, is_active, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                m.id, m.sku, m.name, m.category_id, m.group_id, m.supplier_id, m.material_type,
                m.thickness_mm, m.density, m.color_name,
                m.color_rgb[0], m.color_rgb[1], m.color_rgb[2],
                m.texture_path, m.grain_direction, m.price_per_m2, m.currency,
                m.max_drill_depth_face, m.max_drill_depth_edge,
                int(m.is_builtin), int(m.is_active), m.notes,
                m.created_at, m.updated_at,
            ),
        )

    def update(self, m: Material) -> None:
        self._conn.execute(
            """
            UPDATE materials SET
                sku=?, name=?, category_id=?, group_id=?, supplier_id=?, material_type=?,
                thickness_mm=?, density=?, color_name=?, color_r=?, color_g=?, color_b=?,
                texture_path=?, grain_direction=?, price_per_m2=?, currency=?,
                max_drill_depth_face=?, max_drill_depth_edge=?,
                is_builtin=?, is_active=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                m.sku, m.name, m.category_id, m.group_id, m.supplier_id, m.material_type,
                m.thickness_mm, m.density, m.color_name,
                m.color_rgb[0], m.color_rgb[1], m.color_rgb[2],
                m.texture_path, m.grain_direction, m.price_per_m2, m.currency,
                m.max_drill_depth_face, m.max_drill_depth_edge,
                int(m.is_builtin), int(m.is_active), m.notes, m.updated_at,
                m.id,
            ),
        )

    def delete(self, material_id: str) -> bool:
        """Удаляет материал по id. Возвращает True, если строка была удалена."""
        cur = self._conn.execute(
            "DELETE FROM materials WHERE id = ?", (material_id,)
        )
        return cur.rowcount > 0

    # ── Edge bands ─────────────────────────────────────────────

    def get_edge(self, edge_id: str) -> Optional[EdgeBand]:
        row = self._conn.execute(
            "SELECT * FROM edge_bands WHERE id = ?", (edge_id,)
        ).fetchone()
        return _row_to_edge(row) if row else None

    def list_edges(
        self,
        *,
        group_ids: Optional[List[str]] = None,
        active_only: bool = True,
    ) -> List[EdgeBand]:
        clauses = []
        params: list = []
        if active_only:
            clauses.append("is_active = 1")
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            clauses.append(f"group_id IN ({placeholders})")
            params.extend(group_ids)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM edge_bands{where} ORDER BY name, thickness_mm"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_edge(r) for r in rows]

    def insert_edge(self, e: EdgeBand) -> None:
        self._conn.execute(
            """
            INSERT INTO edge_bands (
                id, sku, name, group_id, supplier_id, material_type,
                thickness_mm, width_mm, color_name, color_r, color_g, color_b,
                texture_path, price_per_m, currency,
                is_builtin, is_active, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                e.id, e.sku, e.name, e.group_id, e.supplier_id, e.material_type,
                e.thickness_mm, e.width_mm, e.color_name,
                e.color_rgb[0], e.color_rgb[1], e.color_rgb[2],
                e.texture_path, e.price_per_m, e.currency,
                int(e.is_builtin), int(e.is_active), e.notes,
                e.created_at, e.updated_at,
            ),
        )

    def update_edge(self, e: EdgeBand) -> None:
        """Обновляет запись кромки в базе данных."""
        self._conn.execute(
            """
            UPDATE edge_bands SET
                sku=?, name=?, group_id=?, supplier_id=?, material_type=?,
                thickness_mm=?, width_mm=?, color_name=?, color_r=?, color_g=?, color_b=?,
                texture_path=?, price_per_m=?, currency=?,
                is_builtin=?, is_active=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                e.sku, e.name, e.group_id, e.supplier_id, e.material_type,
                e.thickness_mm, e.width_mm, e.color_name,
                e.color_rgb[0], e.color_rgb[1], e.color_rgb[2],
                e.texture_path, e.price_per_m, e.currency,
                int(e.is_builtin), int(e.is_active), e.notes, e.updated_at,
                e.id,
            ),
        )

    def delete_edge(self, edge_id: str) -> bool:
        """Удаляет запись кромки по id. Возвращает True, если строка удалена."""
        cur = self._conn.execute("DELETE FROM edge_bands WHERE id = ?", (edge_id,))
        return cur.rowcount > 0

    # ── Categories & Suppliers ─────────────────────────────────

    def list_categories(self) -> List[MaterialCategory]:
        rows = self._conn.execute(
            "SELECT * FROM material_categories ORDER BY sort_order, name"
        ).fetchall()
        return [
            MaterialCategory(
                id=r["id"], name=r["name"],
                parent_id=r["parent_id"], sort_order=r["sort_order"],
            )
            for r in rows
        ]

    def list_suppliers(self, *, active_only: bool = True) -> List[Supplier]:
        sql = "SELECT * FROM suppliers"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY name"
        rows = self._conn.execute(sql).fetchall()
        return [
            Supplier(
                id=r["id"], name=r["name"], country=r["country"] or "",
                website=r["website"] or "", notes=r["notes"] or "",
                is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    def insert_category(self, c: MaterialCategory) -> None:
        self._conn.execute(
            "INSERT INTO material_categories (id, name, parent_id, sort_order) VALUES (?,?,?,?)",
            (c.id, c.name, c.parent_id, c.sort_order),
        )

    def insert_supplier(self, s: Supplier) -> None:
        self._conn.execute(
            "INSERT INTO suppliers (id, name, country, website, notes, is_active) VALUES (?,?,?,?,?,?)",
            (s.id, s.name, s.country, s.website, s.notes, int(s.is_active)),
        )

    # ── Catalog groups (дерево) ────────────────────────────────

    def list_groups(self) -> List[CatalogGroup]:
        rows = self._conn.execute(
            "SELECT * FROM catalog_groups ORDER BY sort_order, name"
        ).fetchall()
        return [
            CatalogGroup(
                id=r["id"], name=r["name"], parent_id=r["parent_id"],
                sort_order=r["sort_order"] or 0, scope=r["scope"] or "all",
                is_builtin=bool(r["is_builtin"]),
            )
            for r in rows
        ]

    def get_group(self, group_id: str) -> Optional[CatalogGroup]:
        row = self._conn.execute(
            "SELECT * FROM catalog_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not row:
            return None
        return CatalogGroup(
            id=row["id"], name=row["name"], parent_id=row["parent_id"],
            sort_order=row["sort_order"] or 0, scope=row["scope"] or "all",
            is_builtin=bool(row["is_builtin"]),
        )

    def insert_group(self, g: CatalogGroup) -> None:
        self._conn.execute(
            "INSERT INTO catalog_groups (id, name, parent_id, sort_order, scope, is_builtin) "
            "VALUES (?,?,?,?,?,?)",
            (g.id, g.name, g.parent_id, g.sort_order, g.scope, int(g.is_builtin)),
        )

    def update_group(self, g: CatalogGroup) -> None:
        self._conn.execute(
            "UPDATE catalog_groups SET name=?, parent_id=?, sort_order=?, scope=?, is_builtin=? "
            "WHERE id=?",
            (g.name, g.parent_id, g.sort_order, g.scope, int(g.is_builtin), g.id),
        )

    def delete_group(self, group_id: str) -> bool:
        self._conn.execute("UPDATE materials SET group_id = NULL WHERE group_id = ?", (group_id,))
        self._conn.execute("UPDATE edge_bands SET group_id = NULL WHERE group_id = ?", (group_id,))
        self._conn.execute("UPDATE fasteners SET group_id = NULL WHERE group_id = ?", (group_id,))
        children = self._conn.execute(
            "SELECT id FROM catalog_groups WHERE parent_id = ?", (group_id,)
        ).fetchall()
        for ch in children:
            self.delete_group(ch["id"])
        cur = self._conn.execute("DELETE FROM catalog_groups WHERE id = ?", (group_id,))
        return cur.rowcount > 0

    def descendant_group_ids(self, group_id: str) -> List[str]:
        groups = self.list_groups()
        by_parent: dict = {}
        for g in groups:
            by_parent.setdefault(g.parent_id, []).append(g.id)
        result = []
        stack = [group_id]
        while stack:
            gid = stack.pop()
            result.append(gid)
            stack.extend(by_parent.get(gid, []))
        return result
