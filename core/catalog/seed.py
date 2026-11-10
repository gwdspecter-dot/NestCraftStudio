"""
Стартовое наполнение каталога (встроенные материалы и крепёж).
Вызывается один раз при первом создании БД.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core.catalog.models import (
    Supplier, MaterialCategory, Material, EdgeBand,
    FastenerType, Fastener,
)
from core.catalog.material_repo import MaterialRepository
from core.catalog.fastener_repo import FastenerRepository


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    """Заполняет каталог стартовыми данными, если таблица materials пуста.
    Возвращает True, если сидинг был выполнен.
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM materials").fetchone()["c"]
    if count > 0:
        return False

    mat_repo = MaterialRepository(conn)
    fst_repo = FastenerRepository(conn)
    ts = _now()

    # ── Поставщики ────────────────────────────────────────────
    suppliers = [
        Supplier("sup_egger", "Egger", "Австрия", "https://www.egger.com"),
        Supplier("sup_kronospan", "Kronospan", "Австрия", "https://kronospan.com"),
        Supplier("sup_swiss_krono", "Swiss Krono", "Швейцария"),
        Supplier("sup_lamarty", "Ламарти", "Россия"),
        Supplier("sup_generic", "Универсальный", "—"),
    ]
    for s in suppliers:
        mat_repo.insert_supplier(s)

    # ── Категории ─────────────────────────────────────────────
    categories = [
        MaterialCategory("cat_ldsp", "ЛДСП", sort_order=10),
        MaterialCategory("cat_mdf", "МДФ", sort_order=20),
        MaterialCategory("cat_hdf", "ХДФ", sort_order=30),
        MaterialCategory("cat_plywood", "Фанера", sort_order=40),
        MaterialCategory("cat_other", "Прочее", sort_order=90),
    ]
    for c in categories:
        mat_repo.insert_category(c)

    # ── Материалы ─────────────────────────────────────────────
    # Цвета примерно соответствуют реальным декору
    materials = [
        # --- Популярные ЛДСП 16 мм ---
        Material(
            id="mat_mist_vl_16", sku="MIST-VL-16", name="МИСТ VL",
            category_id="cat_ldsp", supplier_id="sup_lamarty",
            material_type="ldsp", thickness_mm=16.0, density=680,
            color_name="МИСТ VL", color_rgb=(0.88, 0.85, 0.80),
            price_per_m2=1450, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_white_16", sku="W980-ST2-16", name="Белый премиум",
            category_id="cat_ldsp", supplier_id="sup_egger",
            material_type="ldsp", thickness_mm=16.0, density=650,
            color_name="Белый ST2", color_rgb=(0.96, 0.96, 0.95),
            price_per_m2=1380, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_oak_sonoma_16", sku="H3133-ST12-16", name="Дуб Сонома",
            category_id="cat_ldsp", supplier_id="sup_egger",
            material_type="ldsp", thickness_mm=16.0, density=670,
            color_name="Дуб Сонома", color_rgb=(0.82, 0.72, 0.55),
            grain_direction="length",
            price_per_m2=1620, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_wenge_16", sku="WENGE-16", name="Венге",
            category_id="cat_ldsp", supplier_id="sup_kronospan",
            material_type="ldsp", thickness_mm=16.0, density=680,
            color_name="Венге", color_rgb=(0.28, 0.20, 0.15),
            grain_direction="length",
            price_per_m2=1550, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_anthracite_16", sku="U961-ST9-16", name="Антрацит",
            category_id="cat_ldsp", supplier_id="sup_egger",
            material_type="ldsp", thickness_mm=16.0, density=660,
            color_name="Антрацит", color_rgb=(0.22, 0.22, 0.23),
            price_per_m2=1520, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # --- ЛДСП 18 мм ---
        Material(
            id="mat_white_18", sku="W980-ST2-18", name="Белый премиум",
            category_id="cat_ldsp", supplier_id="sup_egger",
            material_type="ldsp", thickness_mm=18.0, density=650,
            color_name="Белый ST2", color_rgb=(0.96, 0.96, 0.95),
            price_per_m2=1550, max_drill_depth_face=16, max_drill_depth_edge=14,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_oak_sonoma_18", sku="H3133-ST12-18", name="Дуб Сонома",
            category_id="cat_ldsp", supplier_id="sup_egger",
            material_type="ldsp", thickness_mm=18.0, density=670,
            color_name="Дуб Сонома", color_rgb=(0.82, 0.72, 0.55),
            grain_direction="length",
            price_per_m2=1780, max_drill_depth_face=16, max_drill_depth_edge=14,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # --- ХДФ ---
        Material(
            id="mat_hdf_3", sku="HDF-WHITE-3", name="ХДФ белый",
            category_id="cat_hdf", supplier_id="sup_generic",
            material_type="hdf", thickness_mm=3.0, density=850,
            color_name="Белый", color_rgb=(0.95, 0.95, 0.94),
            price_per_m2=420, max_drill_depth_face=0, max_drill_depth_edge=0,
            is_builtin=True, created_at=ts, updated_at=ts,
            notes="Задняя стенка",
        ),
        Material(
            id="mat_hdf_4", sku="HDF-WHITE-4", name="ХДФ белый",
            category_id="cat_hdf", supplier_id="sup_generic",
            material_type="hdf", thickness_mm=4.0, density=850,
            color_name="Белый", color_rgb=(0.95, 0.95, 0.94),
            price_per_m2=480, max_drill_depth_face=0, max_drill_depth_edge=0,
            is_builtin=True, created_at=ts, updated_at=ts,
            notes="Задняя стенка",
        ),
        # --- МДФ ---
        Material(
            id="mat_mdf_16", sku="MDF-16", name="МДФ шлифованный",
            category_id="cat_mdf", supplier_id="sup_generic",
            material_type="mdf", thickness_mm=16.0, density=750,
            color_name="Натуральный", color_rgb=(0.85, 0.80, 0.72),
            price_per_m2=980, max_drill_depth_face=14, max_drill_depth_edge=12,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        Material(
            id="mat_mdf_19", sku="MDF-19", name="МДФ шлифованный",
            category_id="cat_mdf", supplier_id="sup_generic",
            material_type="mdf", thickness_mm=19.0, density=750,
            color_name="Натуральный", color_rgb=(0.85, 0.80, 0.72),
            price_per_m2=1120, max_drill_depth_face=16, max_drill_depth_edge=14,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
    ]
    for m in materials:
        mat_repo.insert(m)

    # ── Кромка ────────────────────────────────────────────────
    edges = [
        EdgeBand(
            id="edge_pvc_22_04_white", sku="PVC-22-0.4-W", name="ПВХ белый",
            material_type="pvc", thickness_mm=0.4, width_mm=22.0,
            color_name="Белый", color_rgb=(0.96, 0.96, 0.95),
            price_per_m=12, is_builtin=True, created_at=ts, updated_at=ts,
        ),
        EdgeBand(
            id="edge_pvc_22_04_oak", sku="PVC-22-0.4-OAK", name="ПВХ Дуб Сонома",
            material_type="pvc", thickness_mm=0.4, width_mm=22.0,
            color_name="Дуб Сонома", color_rgb=(0.82, 0.72, 0.55),
            price_per_m=18, is_builtin=True, created_at=ts, updated_at=ts,
        ),
        EdgeBand(
            id="edge_pvc_22_04_wenge", sku="PVC-22-0.4-WG", name="ПВХ Венге",
            material_type="pvc", thickness_mm=0.4, width_mm=22.0,
            color_name="Венге", color_rgb=(0.28, 0.20, 0.15),
            price_per_m=18, is_builtin=True, created_at=ts, updated_at=ts,
        ),
        EdgeBand(
            id="edge_pvc_22_04_anthracite", sku="PVC-22-0.4-ANT", name="ПВХ Антрацит",
            material_type="pvc", thickness_mm=0.4, width_mm=22.0,
            color_name="Антрацит", color_rgb=(0.22, 0.22, 0.23),
            price_per_m=16, is_builtin=True, created_at=ts, updated_at=ts,
        ),
        EdgeBand(
            id="edge_pvc_19_04_white", sku="PVC-19-0.4-W", name="ПВХ белый",
            material_type="pvc", thickness_mm=0.4, width_mm=19.0,
            color_name="Белый", color_rgb=(0.96, 0.96, 0.95),
            price_per_m=11, is_builtin=True, created_at=ts, updated_at=ts,
        ),
        EdgeBand(
            id="edge_abs_22_2_white", sku="ABS-22-2-W", name="АБС белый",
            material_type="abs", thickness_mm=2.0, width_mm=22.0,
            color_name="Белый", color_rgb=(0.96, 0.96, 0.95),
            price_per_m=45, is_builtin=True, created_at=ts, updated_at=ts,
            notes="Толстая кромка для видимых торцов",
        ),
    ]
    for e in edges:
        mat_repo.insert_edge(e)

    # ── Типы крепежа ──────────────────────────────────────────
    types = [
        FastenerType("ftype_confirmat", "confirmat", "Евровинт (конфирмат)",
                     "Саморезная стяжка для корпусной мебели"),
        FastenerType("ftype_dowel", "dowel", "Шкант",
                     "Деревянный или пластиковый шкант"),
        FastenerType("ftype_minifix", "minifix", "Минификс",
                     "Эксцентриковая стяжка"),
        FastenerType("ftype_rafix", "rafix", "Рафикс",
                     "Эксцентриковая стяжка Hettich"),
        FastenerType("ftype_shelf", "shelf_support", "Полкодержатель",
                     "Скрытый или видимый полкодержатель"),
    ]
    for t in types:
        fst_repo.insert_type(t)

    # ── Крепёж ────────────────────────────────────────────────
    # Правила сверления соответствуют реальной практике корпусной мебели
    fasteners = [
        # Конфирмат 7×50 (самый ходовой)
        Fastener(
            id="fst_conf_7x50", sku="CONF-7x50", name="Евровинт",
            type_id="ftype_confirmat",
            diameter_mm=7.0, length_mm=50.0, head_diameter_mm=10.0,
            drill_face_diameter=7.0, drill_face_depth=0,   # сквозное в пласть
            drill_edge_diameter=5.0, drill_edge_depth=38,  # глухое в торец
            drill_through=True,
            min_panel_thickness=16, max_panel_thickness=22,
            recommended_spacing_mm=64,
            price=3.5, pack_qty=200,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # Конфирмат 7×70
        Fastener(
            id="fst_conf_7x70", sku="CONF-7x70", name="Евровинт",
            type_id="ftype_confirmat",
            diameter_mm=7.0, length_mm=70.0, head_diameter_mm=10.0,
            drill_face_diameter=7.0, drill_face_depth=0,
            drill_edge_diameter=5.0, drill_edge_depth=50,
            drill_through=True,
            min_panel_thickness=16, max_panel_thickness=25,
            recommended_spacing_mm=64,
            price=4.2, pack_qty=200,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # Шкант 8×30
        Fastener(
            id="fst_dowel_8x30", sku="DOWEL-8x30", name="Шкант деревянный",
            type_id="ftype_dowel",
            diameter_mm=8.0, length_mm=30.0,
            drill_face_diameter=8.0, drill_face_depth=12,
            drill_edge_diameter=8.0, drill_edge_depth=18,
            drill_through=False,
            min_panel_thickness=16, max_panel_thickness=25,
            recommended_spacing_mm=64,
            price=1.2, pack_qty=500,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # Шкант 8×35
        Fastener(
            id="fst_dowel_8x35", sku="DOWEL-8x35", name="Шкант деревянный",
            type_id="ftype_dowel",
            diameter_mm=8.0, length_mm=35.0,
            drill_face_diameter=8.0, drill_face_depth=14,
            drill_edge_diameter=8.0, drill_edge_depth=21,
            drill_through=False,
            min_panel_thickness=16, max_panel_thickness=25,
            recommended_spacing_mm=64,
            price=1.4, pack_qty=500,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
        # Минификс (эксцентрик + шток)
        Fastener(
            id="fst_minifix_15", sku="MINIFIX-15", name="Минификс 15",
            type_id="ftype_minifix",
            diameter_mm=15.0, length_mm=34.0, head_diameter_mm=15.0,
            drill_face_diameter=15.0, drill_face_depth=12.5,  # под эксцентрик
            drill_edge_diameter=8.0, drill_edge_depth=25,     # под шток
            drill_through=False,
            min_panel_thickness=16, max_panel_thickness=22,
            recommended_spacing_mm=96,
            price=8.5, pack_qty=100,
            is_builtin=True, created_at=ts, updated_at=ts,
            notes="Комплект: эксцентрик + шток + дюбель",
        ),
        # Полкодержатель скрытый
        Fastener(
            id="fst_shelf_5x16", sku="SHELF-5x16", name="Полкодержатель скрытый",
            type_id="ftype_shelf",
            diameter_mm=5.0, length_mm=16.0,
            drill_face_diameter=5.0, drill_face_depth=12,
            drill_edge_diameter=0, drill_edge_depth=0,
            drill_through=False,
            min_panel_thickness=16, max_panel_thickness=25,
            recommended_spacing_mm=0,
            price=2.8, pack_qty=100,
            is_builtin=True, created_at=ts, updated_at=ts,
        ),
    ]
    for f in fasteners:
        fst_repo.insert(f)

    conn.commit()
    return True
