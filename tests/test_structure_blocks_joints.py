# -*- coding: utf-8 -*-
"""Тесты структуры модели без автоматических блоков, явного создания блоков,
межблочных стыков/ассоциаций и переноса панелей «Стыки» и «Ассоциации» в «Свойства»."""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── Pure-stdlib тесты (работают без numpy / PyQt6) ────────────────────────────


def test_five_structure_svg_icons_exist_and_valid():
    icons_dir = ROOT / "ui" / "icons"
    expected = (
        "struct_block.svg",
        "struct_panel.svg",
        "struct_joint.svg",
        "struct_fastener.svg",
        "struct_assoc.svg",
    )
    for fname in expected:
        p = icons_dir / fname
        assert p.is_file(), f"Не найдена иконка {fname}"
        raw = p.read_text(encoding="utf-8")
        assert "currentColor" in raw, f"Иконка {fname} должна поддерживать currentColor"
        root = ET.fromstring(raw)
        assert root.tag.endswith("svg"), f"Некорректный корень SVG в {fname}"


def test_mainwindow_removes_standalone_joints_and_assoc_docks_ast():
    mw_src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(mw_src)
    # Не создаём отдельных док-панелей joints_dock и assoc_dock
    assert "self.joints_dock" not in mw_src
    assert "self.assoc_dock" not in mw_src
    # Присутствуют обработчики структуры и создания блока
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "_on_structure_joint_selected" in method_names
    assert "_on_structure_assoc_selected" in method_names
    assert "_on_create_block_requested" in method_names
    assert "navigate_to_hole_owner" in method_names


def test_properties_and_structure_panels_wire_embedded_views_ast():
    prop_src = (ROOT / "ui" / "panels" / "properties_panel.py").read_text(encoding="utf-8")
    struct_src = (ROOT / "ui" / "panels" / "structure_panel.py").read_text(encoding="utf-8")
    dlg_src = (ROOT / "ui" / "product_dialogs.py").read_text(encoding="utf-8")

    assert "JointsPanelWidget" in prop_src
    assert "AssocPanelWidget" in prop_src
    assert "show_joints_panel" in prop_src
    assert "show_assoc_panel" in prop_src
    assert "Сборочная единица" in prop_src

    assert "create_block_requested" in struct_src
    assert "joint_selected" in struct_src
    assert "assoc_selected" in struct_src
    assert "Создать блок…" in struct_src
    for icon_name in (
        "struct_block.svg",
        "struct_panel.svg",
        "struct_joint.svg",
        "struct_fastener.svg",
        "struct_assoc.svg",
    ):
        assert icon_name in struct_src

    assert "class CreateBlockDialog" in dlg_src
    assert "Сборочная единица" in dlg_src


# ── Тесты модели, стыков, ассоциаций, Undo и сериализации (требуют numpy) ────


def test_copy_paste_loose_panel_merges_into_root_and_allows_joint():
    from core.clipboard import capture_selection, materialize, set_anchor
    from core.issues import check_broken_joints_in_blocks
    from core.joint import JointRecord, apply_joints_in_blocks, get_joint_fastener_items
    from core.undo import PasteBlocksCommand, UndoStack
    from models.panel import Block, Panel, bind_scene_blocks

    root = Block("Изделие", "", "", is_assembly=False, is_root=True)
    # Вертикальная стойка 16×720×560 в X=0..16
    p1 = Panel("Стойка 1", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, "")
    p1.selected = True
    root.add_panel(p1)
    blocks = [root]
    bind_scene_blocks(blocks)

    # Ctrl+C → Ctrl+V через PasteBlocksCommand
    payload = capture_selection(blocks)
    assert payload is not None
    set_anchor(payload, 0.0, 0.0, 0.0)
    # Ставим копию как свободную панель
    new_blocks = materialize(payload, (100.0, 0.0, 0.0))
    assert len(new_blocks) == 1
    assert getattr(new_blocks[0], "is_root", False) is True

    stack = UndoStack()
    cmd = PasteBlocksCommand(blocks, new_blocks, "Вставка")
    stack.push(cmd, execute=True)

    # Никакого отдельного блока «Копия» не появилось — обе панели в корневом контейнере
    assert len(blocks) == 1
    assert blocks[0] is root
    assert len(root.panels) == 2

    p2 = root.panels[1]
    # Превращаем копию в горизонтальную полку, примыкающую к стойке p1 (X=16..516, Y=300..316)
    p2.x, p2.y, p2.z = 16.0, 300.0, 0.0
    p2.width, p2.height, p2.depth = 500.0, 16.0, 560.0
    p2.thickness_axis = 1

    jr = JointRecord(
        panel_a_uid=p1.uid,
        panel_b_uid=p2.uid,
        preset_id="confirmat_3",
    )
    root.joints.append(jr)
    issues = apply_joints_in_blocks(blocks, rebuild_geometry=False)
    assert issues == []
    assert len(p1.holes) == 3
    assert len(p2.holes) == 3
    assert check_broken_joints_in_blocks(blocks) == []

    # Дочерние элементы стыка в дереве — 3 одиночных крепежа
    items = get_joint_fastener_items(jr, blocks)
    assert len(items) == 3
    assert all("Конфирмат" in it["name"] for it in items)

    # Undo вставки удаляет вставленную панель и не оставляет лишних блоков
    stack.undo()
    assert len(blocks) == 1
    assert len(root.panels) == 1


def test_cross_block_joint_has_no_broken_issue_and_roundtrips():
    from core.hole_nav import collect_owner_holes
    from core.issues import check_broken_joints_in_blocks
    from core.joint import JointRecord, apply_joints_in_blocks
    from core.project_io import scene_from_dict, scene_to_dict
    from models.panel import Block, Panel, bind_scene_blocks
    from ui.panels.joints_panel import JointsDock

    b1 = Block("Блок A", "1", "01.00", is_assembly=True, is_root=False)
    b2 = Block("Блок B", "", "", is_assembly=False, is_root=False)

    pa = Panel("Стойка", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, "1.1")
    pb = Panel("Полка", 16.0, 350.0, 0.0, 500.0, 16.0, 560.0, "")
    pb.thickness_axis = 1
    b1.add_panel(pa)
    b2.add_panel(pb)

    blocks = [b1, b2]
    bind_scene_blocks(blocks)

    jr = JointRecord(panel_a_uid=pa.uid, panel_b_uid=pb.uid, preset_id="confirmat_3")
    b1.joints.append(jr)

    issues = apply_joints_in_blocks(blocks, rebuild_geometry=False)
    assert issues == []
    assert len(pa.holes) == 3
    assert len(pb.holes) == 3
    assert check_broken_joints_in_blocks(blocks) == []

    # Навигация по отверстиям видит отверстия на обеих панелях из разных блоков
    owner_holes = collect_owner_holes(b1, "joint", jr.uid, blocks=blocks)
    assert len(owner_holes) == 6
    from core.hole_nav import HoleHit, describe_hole_hit

    sample_hit = HoleHit(
        block=b2,
        panel=pb,
        hole_index=0,
        hole=tuple(pb.holes[0]),
        kind="joint",
        owner_uid=jr.uid,
        world_p0=(0.0, 0.0, 0.0),
        world_p1=(0.0, 0.0, 10.0),
        world_mid=(0.0, 0.0, 5.0),
        ray_t=1.0,
        screen_dist_px=0.0,
    )
    desc_full = describe_hole_hit(sample_hit, include_hint=False, compact=False, blocks=blocks)
    assert "Стойка" in desc_full and "Полка" in desc_full
    desc_compact = describe_hole_hit(sample_hit, include_hint=False, compact=True, blocks=blocks)
    assert "Стык:" in desc_compact

    # JointsDock / JointsPanelWidget корректно показывает имена без [нет детали]
    jd = JointsDock()
    jd.load_joints(blocks)
    assert jd.list_widget.count() == 1
    row_txt = jd.list_widget.item(0).text()
    assert "Стойка" in row_txt and "Полка" in row_txt
    assert "[нет детали]" not in row_txt

    # Сохранение и загрузка проекта (.b3d) сохраняют межблочный стык и флаги блоков
    from core.version import FORMAT_VERSION

    data = scene_to_dict(blocks, "Тест")
    assert data["version"] == FORMAT_VERSION
    _name, loaded_blocks = scene_from_dict(data)
    assert len(loaded_blocks) == 2
    assert loaded_blocks[0].is_assembly is True
    assert loaded_blocks[1].is_assembly is False
    assert check_broken_joints_in_blocks(loaded_blocks) == []
    assert len(loaded_blocks[0].panels[0].holes) == 3
    assert len(loaded_blocks[1].panels[0].holes) == 3


def test_cross_block_assoc_ref_works_and_roundtrips():
    from core.assoc import AssocRef, apply_assoc_refs_in_blocks, evaluate_assoc_ref
    from core.issues import check_broken_assocs_in_blocks
    from models.panel import Block, Panel, bind_scene_blocks
    from ui.panels.assoc_panel import AssocDock

    root = Block("Изделие", "", "", is_assembly=False, is_root=True)
    blk = Block("Блок 1", "", "", is_assembly=False, is_root=False)
    pa = Panel("Стойка", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, "")
    pb = Panel("Полка", 16.0, 350.0, 0.0, 500.0, 16.0, 560.0, "")
    pb.thickness_axis = 1
    root.add_panel(pa)
    blk.add_panel(pb)

    blocks = [root, blk]
    bind_scene_blocks(blocks)

    ref = AssocRef(
        target_uid=pa.uid,
        source_uid=pb.uid,
        source_face="X-",
        params={"u": 0.0, "v": 0.0, "inset": 0.0, "diameter": 8.0, "depth": 12.0},
    )
    root.assoc_refs.append(ref)

    notes = apply_assoc_refs_in_blocks(blocks, rebuild_geometry=False)
    assert notes == []
    assert len(pa.holes) == 1
    st = evaluate_assoc_ref(root, ref, all_blocks=blocks)
    assert st.severity == "ok"
    assert check_broken_assocs_in_blocks(blocks) == []

    dock = AssocDock()
    dock.load_assocs(blocks)
    assert dock.list_widget.count() == 1
    txt = dock.list_widget.item(0).text()
    assert "Стойка" in txt and "Полка" in txt
    assert "[нет детали]" not in txt


def test_create_block_command_assembly_flag_and_undo_redo():
    from core.undo import CreateBlockCommand, EditPropertyCommand, UndoStack
    from models.panel import Block, Panel, bind_scene_blocks

    root = Block("Изделие", "", "", is_assembly=False, is_root=True)
    p1 = Panel("Левая", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, "")
    p2 = Panel("Правая", 584.0, 0.0, 0.0, 16.0, 720.0, 560.0, "")
    p3 = Panel("Свободная", 700.0, 0.0, 0.0, 16.0, 720.0, 560.0, "")
    root.add_panel(p1)
    root.add_panel(p2)
    root.add_panel(p3)
    blocks = [root]
    bind_scene_blocks(blocks)

    stack = UndoStack()

    # 1. Создание блока БЕЗ галочки «Сборочная единица» → позиции пустые
    cmd_no_asm = CreateBlockCommand(blocks, [p1, p2], "Группа без позиций", is_assembly=False)
    stack.push(cmd_no_asm, execute=True)
    assert len(blocks) == 2
    nb = cmd_no_asm.new_block
    assert nb is not None
    assert nb.is_assembly is False
    assert nb.pos_num == ""
    assert [p.pos_num for p in nb.panels] == ["", ""]
    assert root.panels == [p3]

    # Включение «Сборочная единица» через свойства расставляет позиции
    prop_cmd = EditPropertyCommand(nb, "is_assembly", False, True)
    stack.push(prop_cmd, execute=True)
    assert nb.is_assembly is True
    assert nb.pos_num == "1"
    assert [p.pos_num for p in nb.panels] == ["1.1", "1.2"]

    # Undo свойства возвращает пустые позиции
    stack.undo()
    assert nb.is_assembly is False
    assert nb.pos_num == ""
    assert [p.pos_num for p in nb.panels] == ["", ""]

    # Undo создания блока возвращает панели в корень на исходные места
    stack.undo()
    assert len(blocks) == 1
    assert root.panels == [p1, p2, p3]
    assert [p.pos_num for p in root.panels] == ["", "", ""]

    # 2. Создание блока С галочкой «Сборочная единица»
    cmd_asm = CreateBlockCommand(blocks, [p1, p2], "Тумба", is_assembly=True)
    stack.push(cmd_asm, execute=True)
    nb2 = cmd_asm.new_block
    assert nb2 is not None
    assert nb2.is_assembly is True
    assert nb2.pos_num == "1"
    assert [p.pos_num for p in nb2.panels] == ["1.1", "1.2"]


def test_migration_0_0_11_to_0_0_12():
    from core.project_io import migrate_project_dict
    from core.version import FORMAT_VERSION

    legacy = {
        "version": "0.0.11",
        "name": "Старый проект",
        "order_number": "Z-1",
        "bounding_frame": None,
        "blocks": [
            {"type": "Block", "name": "Корпус 1", "pos_num": "1", "code": "01.00", "panels": []}
        ],
    }
    migrated, applied = migrate_project_dict(legacy)
    assert migrated["version"] == FORMAT_VERSION
    assert "0.0.11 -> 0.0.12" in applied
    blk = migrated["blocks"][0]
    assert blk["is_assembly"] is True
    assert blk["is_root"] is False
