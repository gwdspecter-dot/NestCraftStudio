"""
Подключение к SQLite-каталогу, схема и миграции.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from core.logging_setup import get_logger

_log = get_logger("catalog")

# Текущая версия схемы. При изменении схемы увеличиваем и добавляем миграцию.
SCHEMA_VERSION = 2

# SQL создания всех таблиц (версия 1)
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    country     TEXT DEFAULT '',
    website     TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS material_categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    parent_id   TEXT REFERENCES material_categories(id),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS materials (
    id                      TEXT PRIMARY KEY,
    sku                     TEXT NOT NULL,
    name                    TEXT NOT NULL,
    category_id             TEXT NOT NULL REFERENCES material_categories(id),
    supplier_id             TEXT REFERENCES suppliers(id),
    material_type           TEXT NOT NULL,          -- ldsp/mdf/hdf/plywood/solid/other
    thickness_mm            REAL NOT NULL,
    density                 REAL DEFAULT 0,
    color_name              TEXT DEFAULT '',
    color_r                 REAL DEFAULT 0.88,
    color_g                 REAL DEFAULT 0.85,
    color_b                 REAL DEFAULT 0.80,
    texture_path            TEXT DEFAULT '',
    grain_direction         TEXT DEFAULT 'none',    -- none/length/width
    price_per_m2            REAL DEFAULT 0,
    currency                TEXT DEFAULT 'RUB',
    max_drill_depth_face    REAL DEFAULT 0,
    max_drill_depth_edge    REAL DEFAULT 0,
    is_builtin              INTEGER NOT NULL DEFAULT 1,
    is_active               INTEGER NOT NULL DEFAULT 1,
    notes                   TEXT DEFAULT '',
    created_at              TEXT,
    updated_at              TEXT
);

CREATE INDEX IF NOT EXISTS idx_materials_type ON materials(material_type);
CREATE INDEX IF NOT EXISTS idx_materials_thickness ON materials(thickness_mm);
CREATE INDEX IF NOT EXISTS idx_materials_category ON materials(category_id);
CREATE INDEX IF NOT EXISTS idx_materials_active ON materials(is_active);

CREATE TABLE IF NOT EXISTS edge_bands (
    id              TEXT PRIMARY KEY,
    sku             TEXT NOT NULL,
    name            TEXT NOT NULL,
    supplier_id     TEXT REFERENCES suppliers(id),
    material_type   TEXT NOT NULL,                  -- pvc/abs/melamine/acrylic/other
    thickness_mm    REAL NOT NULL,
    width_mm        REAL NOT NULL,
    color_name      TEXT DEFAULT '',
    color_r         REAL DEFAULT 0.9,
    color_g         REAL DEFAULT 0.9,
    color_b         REAL DEFAULT 0.9,
    texture_path    TEXT DEFAULT '',
    price_per_m     REAL DEFAULT 0,
    currency        TEXT DEFAULT 'RUB',
    is_builtin      INTEGER NOT NULL DEFAULT 1,
    is_active       INTEGER NOT NULL DEFAULT 1,
    notes           TEXT DEFAULT '',
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS material_default_edges (
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    edge_id     TEXT NOT NULL REFERENCES edge_bands(id) ON DELETE CASCADE,
    priority    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (material_id, edge_id)
);

CREATE TABLE IF NOT EXISTS fastener_types (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,               -- confirmat/dowel/minifix/...
    name        TEXT NOT NULL,
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fasteners (
    id                      TEXT PRIMARY KEY,
    sku                     TEXT NOT NULL,
    name                    TEXT NOT NULL,
    type_id                 TEXT NOT NULL REFERENCES fastener_types(id),
    supplier_id             TEXT REFERENCES suppliers(id),
    diameter_mm             REAL NOT NULL,
    length_mm               REAL NOT NULL,
    head_diameter_mm        REAL DEFAULT 0,
    drill_face_diameter     REAL DEFAULT 0,
    drill_face_depth        REAL DEFAULT 0,
    drill_edge_diameter     REAL DEFAULT 0,
    drill_edge_depth        REAL DEFAULT 0,
    drill_through           INTEGER NOT NULL DEFAULT 0,
    min_panel_thickness     REAL DEFAULT 0,
    max_panel_thickness     REAL DEFAULT 0,
    recommended_spacing_mm  REAL DEFAULT 64,
    mesh_params             TEXT DEFAULT '{}',
    price                   REAL DEFAULT 0,
    currency                TEXT DEFAULT 'RUB',
    pack_qty                INTEGER DEFAULT 1,
    is_builtin              INTEGER NOT NULL DEFAULT 1,
    is_active               INTEGER NOT NULL DEFAULT 1,
    notes                   TEXT DEFAULT '',
    created_at              TEXT,
    updated_at              TEXT
);

CREATE INDEX IF NOT EXISTS idx_fasteners_type ON fasteners(type_id);
CREATE INDEX IF NOT EXISTS idx_fasteners_active ON fasteners(is_active);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_app_root() -> Path:
    """Корень установки NestCraft (рядом с main.py)."""
    return Path(__file__).resolve().parents[2]


def get_bundled_db_path() -> Path:
    """Встроенный seed-шаблон (только чтение / копирование при первом запуске)."""
    return get_app_root() / "data" / "catalog" / "nestcraft_catalog.db"


def get_user_db_path() -> Path:
    """Рабочая БД пользователя в AppData (план §2.3)."""
    try:
        from core.logging_setup import user_data_dir
        base = user_data_dir()
    except Exception:
        base = Path.home() / ".local" / "share" / "NestCraft"
    return base / "catalog" / "nestcraft_catalog.db"


def get_default_db_path() -> Path:
    """Рабочий путь каталога — всегда user AppData, не Program Files."""
    return get_user_db_path()


def _copy_seed_if_needed(user_path: Path) -> None:
    """Первый запуск: копируем bundled (или legacy data/) в AppData."""
    if user_path.exists() and user_path.stat().st_size > 0:
        return
    user_path.parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        get_bundled_db_path(),
        # на случай, если кто-то уже работал со старым путём в data/
        get_app_root() / "data" / "catalog" / "nestcraft_catalog.db",
    ]
    for src in candidates:
        try:
            if src.exists() and src.stat().st_size > 0 and src.resolve() != user_path.resolve():
                import shutil
                shutil.copy2(src, user_path)
                _log.info("Catalog DB seeded from %s → %s", src, user_path)
                return
        except Exception:
            _log.exception("Failed to copy seed catalog from %s", src)


def _backup_before_migrate(path: Path, from_ver: int, to_ver: int) -> None:
    """Резервная копия перед миграцией схемы."""
    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        import shutil
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = path.with_name(f"{path.stem}.v{from_ver}-to-{to_ver}.{stamp}.bak")
        shutil.copy2(path, bak)
        _log.info("Catalog backup before migrate: %s", bak)
        # не копим бесконечно: оставляем последние 5 бэкапов
        backups = sorted(path.parent.glob(f"{path.stem}.v*.bak"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-5]:
            try:
                old.unlink()
            except OSError:
                _log.debug("Failed to remove old catalog backup %s", old, exc_info=True)
    except Exception:
        _log.exception("Catalog backup failed for %s", path)


def connect(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Открывает соединение с БД и применяет миграции при необходимости."""
    path = Path(db_path) if db_path else get_default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if db_path is None:
        _copy_seed_if_needed(path)

    # Бэкап, если файл уже есть и схема устареет
    need_backup = path.exists() and path.stat().st_size > 0
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
    except Exception:
        _log.debug("PRAGMA journal_mode = DELETE failed", exc_info=True)

    if need_backup:
        ver = _current_version(conn)
        if ver < SCHEMA_VERSION:
            conn.close()
            _backup_before_migrate(path, ver, SCHEMA_VERSION)
            conn = sqlite3.connect(str(path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

    _migrate(conn)
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _migrate(conn: sqlite3.Connection) -> None:
    ver = _current_version(conn)

    if ver < 1:
        conn.executescript(_SCHEMA_V1)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (1, _utc_now()),
        )
        conn.commit()
        ver = 1

    if ver < 2:
        _migrate_v2(conn)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (2, _utc_now()),
        )
        conn.commit()
        ver = 2


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Дерево групп каталога + group_id у материалов / кромки / крепежа."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_groups (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            parent_id   TEXT REFERENCES catalog_groups(id) ON DELETE CASCADE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            scope       TEXT NOT NULL DEFAULT 'all',
            is_builtin  INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_groups_parent
            ON catalog_groups(parent_id);
        """
    )
    for table, col_sql in (
        ("materials", "group_id TEXT REFERENCES catalog_groups(id)"),
        ("edge_bands", "group_id TEXT REFERENCES catalog_groups(id)"),
        ("fasteners", "group_id TEXT REFERENCES catalog_groups(id)"),
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "group_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_sql}")

    count = conn.execute("SELECT COUNT(*) AS c FROM catalog_groups").fetchone()["c"]
    if count == 0:
        groups = [
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
        conn.executemany(
            "INSERT INTO catalog_groups (id, name, parent_id, sort_order, scope, is_builtin) "
            "VALUES (?,?,?,?,?,1)",
            groups,
        )

    type_to_group = {
        "ldsp": "grp_ldsp", "mdf": "grp_mdf", "hdf": "grp_hdf",
        "plywood": "grp_plywood", "solid": "grp_sheet_other", "other": "grp_sheet_other",
    }
    for mtype, gid in type_to_group.items():
        conn.execute(
            "UPDATE materials SET group_id = ? "
            "WHERE (group_id IS NULL OR group_id = '') AND material_type = ?",
            (gid, mtype),
        )
    conn.execute(
        "UPDATE materials SET group_id = 'grp_sheet_other' "
        "WHERE group_id IS NULL OR group_id = ''"
    )
    for etype, gid in (("pvc", "grp_pvc"), ("abs", "grp_abs")):
        conn.execute(
            "UPDATE edge_bands SET group_id = ? "
            "WHERE (group_id IS NULL OR group_id = '') AND material_type = ?",
            (gid, etype),
        )
    conn.execute(
        "UPDATE edge_bands SET group_id = 'grp_edge_other' "
        "WHERE group_id IS NULL OR group_id = ''"
    )
    conn.execute(
        """
        UPDATE fasteners SET group_id = 'grp_shelf'
        WHERE (group_id IS NULL OR group_id = '')
          AND type_id IN (SELECT id FROM fastener_types WHERE code = 'shelf_support')
        """
    )
    conn.execute(
        "UPDATE fasteners SET group_id = 'grp_fasteners' "
        "WHERE group_id IS NULL OR group_id = ''"
    )
