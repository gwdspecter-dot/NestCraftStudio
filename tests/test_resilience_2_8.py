"""Тесты устойчивости проекта и данных (план §2.8):
- цепочка миграций формата .b3d (v0.0.1 -> ... -> v0.0.6);
- предупреждение и сохранение ссылок на удалённые кромки (missing_edges);
- список недавних файлов (recent_files);
- автосохранение во временный файл и восстановление после сбоя (autosave).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tests.conftest as _conf

_conf.pytest_configure(None)

from models.panel import Panel, Block
from core.project_io import (
    FORMAT_VERSION,
    migrate_project_dict,
    save_project,
    load_project,
    collect_missing_edges,
    add_recent_file,
    load_recent_files,
    remove_recent_file,
    clear_recent_files,
    write_autosave,
    has_autosave,
    load_autosave,
    clear_autosave,
)


def test_b3d_migration_chain_from_0_0_4():
    """План §2.8: миграция v0.0.4 -> v0.0.5 -> v0.0.6 проходит по цепочке функций."""
    raw = {
        "format": "NestCraft",
        "version": "0.0.4",
        "name": "legacy_004",
        "blocks": [
            {
                "type": "cabinet",
                "name": "Тумба 600",
                "params": {
                    "x": 0, "y": 0, "z": 0,
                    "width": 600, "height": 720, "depth": 560,
                    "thickness": 16, "shelves_count": 1,
                    "has_facade": False, "is_upper": False, "has_groove": True,
                },
                "panels": [
                    {
                        "name": "Дно вкладное 568x560x16",
                        "x": 16, "y": 0, "z": 0,
                        "width": 568, "height": 16, "depth": 560,
                        "rx": 0.0, "ry": 0.0, "rz": 0.0,
                        "edges": {"top": "edge_pvc_04", "bottom": "", "left": "", "right": ""},
                    }
                ],
            }
        ],
    }

    migrated, steps = migrate_project_dict(raw)
    assert steps == [
        "0.0.4 -> 0.0.5",
        "0.0.5 -> 0.0.6",
        "0.0.6 -> 0.0.7",
        "0.0.7 -> 0.0.8",
        "0.0.8 -> 0.0.9",
        "0.0.9 -> 0.0.10",
    ], f"Unexpected steps: {steps}"
    assert migrated["version"] == FORMAT_VERSION

    blk = migrated["blocks"][0]
    assert blk.get("uid"), "Block uid must be generated in 0.0.5 -> 0.0.6"
    assert blk.get("joints") == [], "Block joints list must be initialized in 0.0.6 -> 0.0.7"
    pd = blk["panels"][0]
    assert pd["thickness_axis"] == 1, "thickness_axis must be inferred as Y (16mm) in 0.0.4 -> 0.0.5"
    assert pd["role"] == "bottom", "role must be inferred for cabinet panel in 0.0.4 -> 0.0.5"
    assert pd.get("uid"), "Panel uid must be generated in 0.0.5 -> 0.0.6"


def test_b3d_migration_chain_from_0_0_1():
    """Полная цепочка v0.0.1 -> v0.0.2 -> v0.0.3 -> v0.0.4 -> v0.0.5 -> v0.0.6 -> v0.0.7."""
    raw = {
        "format": "NestCraft",
        "version": "0.0.1",
        "name": "ancient_proj",
        "blocks": [
            {
                "type": "block",
                "name": "Блок 1",
                "panels": [
                    {
                        "name": "Боковина",
                        "x": 0, "y": 0, "z": 0,
                        "width": 16, "height": 720, "depth": 560,
                    }
                ],
            }
        ],
    }

    migrated, steps = migrate_project_dict(raw)
    assert steps == [
        "0.0.1 -> 0.0.2",
        "0.0.2 -> 0.0.3",
        "0.0.3 -> 0.0.4",
        "0.0.4 -> 0.0.5",
        "0.0.5 -> 0.0.6",
        "0.0.6 -> 0.0.7",
        "0.0.7 -> 0.0.8",
        "0.0.8 -> 0.0.9",
        "0.0.9 -> 0.0.10",
    ]
    assert migrated["blocks"][0]["joints"] == []
    pd = migrated["blocks"][0]["panels"][0]
    assert pd["edges"] == {"top": "", "bottom": "", "left": "", "right": ""}
    assert pd["rx"] == 0.0 and pd["ry"] == 0.0 and pd["rz"] == 0.0
    assert pd["thickness_axis"] == 0
    assert pd["uid"]


def test_missing_edges_warning_and_roundtrip(tmp_path: Path):
    """План §2.8: для ссылок на удалённые кромки показывается предупреждение и ссылка сохраняется."""
    from core.catalog import CatalogService

    _cat = CatalogService.instance(tmp_path / "catalog.db")
    try:
        p = Panel(
            "Деталь с удалённой кромкой",
            0, 0, 0,
            600, 400, 16,
            edges={"top": "edge_deleted_2mm", "bottom": "edge_deleted_04mm", "left": "", "right": ""},
            rebuild=False,
        )
        b = Block("Блок 1")
        b.add_panel(p)

        proj_file = tmp_path / "missing_edges.b3d"
        save_project(proj_file, [b], "missing_edges")

        res = load_project(proj_file)
        loaded_panel = res.blocks[0].panels[0]

        assert loaded_panel.missing_edges.get("top") == "edge_deleted_2mm"
        assert loaded_panel.missing_edges.get("bottom") == "edge_deleted_04mm"
        assert loaded_panel.edges.get("top") == "edge_deleted_2mm"

        missing_list = collect_missing_edges(res.blocks)
        assert "edge_deleted_2mm" in missing_list
        assert "edge_deleted_04mm" in missing_list
        assert any("нет кромок" in w and "edge_deleted_2mm" in w for w in res.warnings), (
            f"Expected missing edge warning in {res.warnings}"
        )

        # Повторное сохранение не теряет ссылку на отсутствующую кромку
        proj_file2 = tmp_path / "missing_edges_resaved.b3d"
        save_project(proj_file2, res.blocks, "missing_edges_resaved")
        res2 = load_project(proj_file2)
        p2 = res2.blocks[0].panels[0]
        assert p2.missing_edges.get("top") == "edge_deleted_2mm"
        assert p2.edges.get("top") == "edge_deleted_2mm"
    finally:
        CatalogService.reset()


def test_recent_files_management(tmp_path: Path):
    """План §2.8: список недавних файлов (дедупликация, порядок, фильтрация удалённых)."""
    storage = tmp_path / "recent_files.json"
    f1 = tmp_path / "proj1.b3d"
    f2 = tmp_path / "proj2.b3d"
    f3 = tmp_path / "proj3.b3d"
    for f in (f1, f2, f3):
        f.write_text("{}", encoding="utf-8")

    add_recent_file(f1, storage_path=storage)
    add_recent_file(f2, storage_path=storage)
    add_recent_file(f3, storage_path=storage)
    # Повторное открытие f1 поднимает его на 1-е место без дубля
    recent = add_recent_file(f1, storage_path=storage)
    assert [Path(p).name for p in recent] == ["proj1.b3d", "proj3.b3d", "proj2.b3d"]

    # Если файл удалён с диска, load_recent_files(only_existing=True) его скрывает
    f3.unlink()
    existing_only = load_recent_files(storage_path=storage, only_existing=True)
    assert [Path(p).name for p in existing_only] == ["proj1.b3d", "proj2.b3d"]

    remove_recent_file(f1, storage_path=storage)
    after_remove = load_recent_files(storage_path=storage, only_existing=True)
    assert [Path(p).name for p in after_remove] == ["proj2.b3d"]

    clear_recent_files(storage_path=storage)
    assert load_recent_files(storage_path=storage) == []


def test_autosave_and_crash_recovery(tmp_path: Path):
    """План §2.8: автосохранение во временный файл и восстановление после сбоя."""
    as_file = tmp_path / "autosave_recovery.b3d"
    assert not has_autosave(autosave_path=as_file)

    p = Panel("Столешница", 10, 20, 30, 1200, 38, 600, rebuild=False)
    b = Block("Кухня")
    b.add_panel(p)

    orig_target = tmp_path / "kitchen_order.b3d"
    written = write_autosave(
        [b],
        project_name="kitchen_order.b3d",
        original_path=orig_target,
        autosave_path=as_file,
    )
    assert written == as_file
    assert has_autosave(autosave_path=as_file)

    res, meta = load_autosave(autosave_path=as_file)
    assert meta["project_name"] == "kitchen_order.b3d"
    assert Path(meta["original_path"]).name == "kitchen_order.b3d"
    assert len(res.blocks) == 1
    assert len(res.blocks[0].panels) == 1
    restored_panel = res.blocks[0].panels[0]
    assert restored_panel.name == "Столешница"
    assert restored_panel.width == 1200

    clear_autosave(autosave_path=as_file)
    assert not has_autosave(autosave_path=as_file)


class _TestResilience28(unittest.TestCase):
    def test_all(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            test_b3d_migration_chain_from_0_0_4()
            test_b3d_migration_chain_from_0_0_1()
            test_missing_edges_warning_and_roundtrip(tmp)
            test_recent_files_management(tmp)
            test_autosave_and_crash_recovery(tmp)


if __name__ == "__main__":
    unittest.main()
