"""
Репозиторий крепежа.
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from core.catalog.models import Fastener, FastenerType


def _row_to_fastener(row: sqlite3.Row) -> Fastener:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return Fastener(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        type_id=row["type_id"],
        group_id=row["group_id"] if "group_id" in keys else None,
        supplier_id=row["supplier_id"],
        diameter_mm=row["diameter_mm"],
        length_mm=row["length_mm"],
        head_diameter_mm=row["head_diameter_mm"] or 0.0,
        drill_face_diameter=row["drill_face_diameter"] or 0.0,
        drill_face_depth=row["drill_face_depth"] or 0.0,
        drill_edge_diameter=row["drill_edge_diameter"] or 0.0,
        drill_edge_depth=row["drill_edge_depth"] or 0.0,
        drill_through=bool(row["drill_through"]),
        min_panel_thickness=row["min_panel_thickness"] or 0.0,
        max_panel_thickness=row["max_panel_thickness"] or 0.0,
        recommended_spacing_mm=row["recommended_spacing_mm"] or 64.0,
        mesh_params=row["mesh_params"] or "{}",
        price=row["price"] or 0.0,
        currency=row["currency"] or "RUB",
        pack_qty=row["pack_qty"] or 1,
        is_builtin=bool(row["is_builtin"]),
        is_active=bool(row["is_active"]),
        notes=row["notes"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class FastenerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, fastener_id: str) -> Optional[Fastener]:
        row = self._conn.execute(
            "SELECT * FROM fasteners WHERE id = ?", (fastener_id,)
        ).fetchone()
        return _row_to_fastener(row) if row else None

    def get_by_sku(self, sku: str) -> Optional[Fastener]:
        row = self._conn.execute(
            "SELECT * FROM fasteners WHERE sku = ?", (sku,)
        ).fetchone()
        return _row_to_fastener(row) if row else None

    def list(
        self,
        *,
        type_code: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Fastener]:
        clauses = []
        params: list = []

        if active_only:
            clauses.append("f.is_active = 1")
        if type_code:
            clauses.append("t.code = ?")
            params.append(type_code)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT f.* FROM fasteners f
            JOIN fastener_types t ON t.id = f.type_id
            {where}
            ORDER BY t.name, f.name, f.length_mm
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_fastener(r) for r in rows]

    def list_types(self) -> List[FastenerType]:
        rows = self._conn.execute(
            "SELECT * FROM fastener_types ORDER BY name"
        ).fetchall()
        return [
            FastenerType(
                id=r["id"], code=r["code"],
                name=r["name"], description=r["description"] or "",
            )
            for r in rows
        ]

    def insert_type(self, t: FastenerType) -> None:
        self._conn.execute(
            "INSERT INTO fastener_types (id, code, name, description) VALUES (?,?,?,?)",
            (t.id, t.code, t.name, t.description),
        )

    def insert(self, f: Fastener) -> None:
        self._conn.execute(
            """
            INSERT INTO fasteners (
                id, sku, name, type_id, supplier_id,
                diameter_mm, length_mm, head_diameter_mm,
                drill_face_diameter, drill_face_depth,
                drill_edge_diameter, drill_edge_depth, drill_through,
                min_panel_thickness, max_panel_thickness, recommended_spacing_mm,
                mesh_params, price, currency, pack_qty,
                is_builtin, is_active, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f.id, f.sku, f.name, f.type_id, f.supplier_id,
                f.diameter_mm, f.length_mm, f.head_diameter_mm,
                f.drill_face_diameter, f.drill_face_depth,
                f.drill_edge_diameter, f.drill_edge_depth, int(f.drill_through),
                f.min_panel_thickness, f.max_panel_thickness, f.recommended_spacing_mm,
                f.mesh_params, f.price, f.currency, f.pack_qty,
                int(f.is_builtin), int(f.is_active), f.notes,
                f.created_at, f.updated_at,
            ),
        )

    def update(self, f: Fastener) -> None:
        self._conn.execute(
            """
            UPDATE fasteners SET
                sku=?, name=?, type_id=?, supplier_id=?,
                diameter_mm=?, length_mm=?, head_diameter_mm=?,
                drill_face_diameter=?, drill_face_depth=?,
                drill_edge_diameter=?, drill_edge_depth=?, drill_through=?,
                min_panel_thickness=?, max_panel_thickness=?, recommended_spacing_mm=?,
                mesh_params=?, price=?, currency=?, pack_qty=?,
                is_builtin=?, is_active=?, notes=?, updated_at=?
            WHERE id=?
            """,
            (
                f.sku, f.name, f.type_id, f.supplier_id,
                f.diameter_mm, f.length_mm, f.head_diameter_mm,
                f.drill_face_diameter, f.drill_face_depth,
                f.drill_edge_diameter, f.drill_edge_depth, int(f.drill_through),
                f.min_panel_thickness, f.max_panel_thickness, f.recommended_spacing_mm,
                f.mesh_params, f.price, f.currency, f.pack_qty,
                int(f.is_builtin), int(f.is_active), f.notes, f.updated_at,
                f.id,
            ),
        )
