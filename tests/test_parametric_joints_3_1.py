"""Модульные тесты параметрических стыков (ревизия 2, п. 3.1)."""

from __future__ import annotations

from pathlib import Path

from core.joint import JointRecord, apply_joints
from core.project_io import load_project, migrate_project_dict, save_project
from core.undo import (
    DeleteJointCommand,
    EditJointCommand,
    EditPropertyCommand,
    PlaceJointFastenerCommand,
    ResizePanelCommand,
    UndoStack,
)
from core.version import FORMAT_VERSION
from models.panel import Block, Panel, ParametricCabinet


def _get_role(cab: ParametricCabinet, role: str) -> Panel:
    for p in cab.panels:
        if getattr(p, "role", "") == role:
            return p
    raise AssertionError(f"Panel with role={role!r} not found")


def test_joint_record_recalculates_on_rebuild_and_preserves_manual_holes():
    """П. 3.1: apply_joints(block) пересчитывает отверстия стыков после смены габаритов и не трогает ручные."""
    cab = ParametricCabinet(
        "Тумба 600",
        width=600,
        height=720,
        depth=560,
        thickness=16,
        shelves_count=0,
        has_facade=False,
    )
    left = _get_role(cab, "left")
    bottom = _get_role(cab, "bottom")

    # 1. Ставим ручное отверстие (без JointRecord) на боковине и на дне
    manual_left = (0.0, 350.0, 123.5, 2.5, 12.0, "X")
    manual_bottom = (200.0, 0.0, 123.5, 4.0, 16.0, "Y")
    left.holes.append(manual_left)
    bottom.holes.append(manual_bottom)

    # 2. Добавляем параметрический стык (3 конфирмата с отступом 50 мм)
    jr = JointRecord(
        panel_a_uid=left.uid,
        panel_b_uid=bottom.uid,
        preset_id="confirmat_3",
    )
    cab.add_joint(jr, apply=True)

    # На каждой из двух панелей должно быть 1 ручное + 3 стыковых = 4 отверстия
    assert len(left.holes) == 4
    assert len(bottom.holes) == 4
    assert left.get_manual_holes() == [manual_left]
    assert bottom.get_manual_holes() == [manual_bottom]

    joint_zs_560 = sorted(round(h[2], 2) for h in left.joint_hole_map[jr.uid])
    assert joint_zs_560 == [50.0, 280.0, 510.0]

    # 3. Меняем глубину корпуса 560 -> 760 через EditPropertyCommand
    stack = UndoStack()
    stack.push(EditPropertyCommand(cab, "depth", 560.0, 760.0), execute=True)

    # Ручные отверстия не тронуты
    assert left.get_manual_holes() == [manual_left]
    assert bottom.get_manual_holes() == [manual_bottom]
    assert manual_left in left.holes
    assert manual_bottom in bottom.holes

    # Стыковые отверстия пересчитались под новую глубину 760 мм: 50, 380, 710
    joint_zs_760 = sorted(round(h[2], 2) for h in left.joint_hole_map[jr.uid])
    assert joint_zs_760 == [50.0, 380.0, 710.0]

    # 4. Undo возвращает глубину 560 и координаты стыка 50, 280, 510
    stack.undo()
    assert cab.depth == 560.0
    assert sorted(round(h[2], 2) for h in left.joint_hole_map[jr.uid]) == [50.0, 280.0, 510.0]
    assert left.get_manual_holes() == [manual_left]


def test_joint_pitch_preset_adds_points_when_panel_grows():
    """П. 3.1: при пресете с фиксированным шагом (pitch=128) увеличение длины стыка пересчитывает число точек."""
    block = Block("Блок с шагом")
    side = Panel("Боковина", 0, 0, 0, 16, 720, 400, rebuild=False)
    bottom = Panel("Дно", 16, 0, 0, 568, 16, 400, rebuild=False)
    block.add_panel(side)
    block.add_panel(bottom)

    jr = JointRecord(
        panel_a_uid=side.uid,
        panel_b_uid=bottom.uid,
        preset_id="confirmat_128",
    )
    block.add_joint(jr, apply=True)

    # При глубине 400 мм и отступе 50 мм полезная длина 300 мм; шаг 128 мм от t0=50 -> 3 точки (50, 178, 306)
    zs_400 = sorted(round(h[2], 2) for h in side.joint_hole_map[jr.uid])
    assert len(zs_400) == 3
    assert zs_400 == [50.0, 178.0, 306.0]

    # Растягиваем обе панели по глубине до 700 мм через ResizePanelCommand
    stack = UndoStack()
    stack.push(
        ResizePanelCommand(side, (0, 0, 0, 16, 720, 400), (0, 0, 0, 16, 720, 700)),
        execute=True,
    )
    stack.push(
        ResizePanelCommand(bottom, (16, 0, 0, 568, 16, 400), (16, 0, 0, 568, 16, 700)),
        execute=True,
    )

    # При глубине 700 мм (полезная длина 600 мм, шаг 128 мм) -> 5 точек
    zs_700 = sorted(round(h[2], 2) for h in side.joint_hole_map[jr.uid])
    assert len(zs_700) == 5
    for a, b in zip(zs_700, zs_700[1:]):
        assert abs((b - a) - 128.0) < 1e-4


def test_edit_and_delete_joint_commands_with_undo_redo():
    """П. 3.1: смена пресета, шага, отступа и удаление стыка целиком с поддержкой Undo/Redo."""
    block = Block("Тестовый блок")
    p_a = Panel("Боковина Л", 0, 0, 0, 16, 720, 560, rebuild=False)
    p_b = Panel("Дно", 16, 0, 0, 568, 16, 560, rebuild=False)
    block.add_panel(p_a)
    block.add_panel(p_b)

    manual_hole = (0.0, 500.0, 200.0, 2.5, 10.0, "X")
    p_a.holes.append(manual_hole)

    jr = JointRecord(
        panel_a_uid=p_a.uid,
        panel_b_uid=p_b.uid,
        preset_id="confirmat_3",
    )

    stack = UndoStack()
    cmd_place = PlaceJointFastenerCommand(
        p_a,
        list(p_a.holes),
        list(p_a.holes),
        p_b,
        list(p_b.holes),
        list(p_b.holes),
        block=block,
        joint_record=jr,
    )
    stack.push(cmd_place, execute=True)
    assert len(block.joints) == 1
    assert len(p_a.holes) == 4  # 1 manual + 3 joint
    assert len(p_b.holes) == 3

    # Меняем пресет и отступ через EditJointCommand
    old_state = block.joints[0].to_dict()
    updated_rec = JointRecord.from_dict(old_state)
    updated_rec.apply_preset("dowel_96")
    updated_rec.params["margin"] = 60.0
    new_state = updated_rec.to_dict()

    stack.push(EditJointCommand(block, jr.uid, old_state, new_state), execute=True)
    assert block.joints[0].preset_id == "dowel_96"
    assert block.joints[0].fastener_id == "fst_dowel_8x30"
    assert block.joints[0].params["margin"] == 60.0
    # Диаметр шканта 8 мм -> радиус 4.0 мм
    joint_holes_a = p_a.joint_hole_map[jr.uid]
    assert len(joint_holes_a) >= 4
    assert all(abs(h[3] - 4.0) < 1e-6 for h in joint_holes_a)
    assert manual_hole in p_a.holes

    # Удаляем стык целиком через DeleteJointCommand
    stack.push(DeleteJointCommand(block, jr.uid), execute=True)
    assert len(block.joints) == 0
    assert p_a.holes == [manual_hole]
    assert p_b.holes == []

    # Undo удаления стыка -> стык и отверстия возвращаются
    stack.undo()
    assert len(block.joints) == 1
    assert block.joints[0].preset_id == "dowel_96"
    assert len(p_a.holes) == 1 + len(joint_holes_a)

    # Undo редактирования стыка -> возвращается confirmat_3 (3 точки Ø7 -> r=3.5)
    stack.undo()
    assert block.joints[0].preset_id == "confirmat_3"
    assert len(p_a.holes) == 4
    assert all(abs(h[3] - 3.5) < 1e-6 for h in p_a.joint_hole_map[jr.uid])

    # Undo постановки стыка -> остаётся только ручное отверстие
    stack.undo()
    assert len(block.joints) == 0
    assert p_a.holes == [manual_hole]
    assert p_b.holes == []


def test_b3d_format_0_0_7_migration_and_roundtrip(tmp_path: Path):
    """П. 3.1: хранение JointRecord в block.joints и в .b3d (миграция 0.0.6 → FORMAT_VERSION + roundtrip)."""
    assert FORMAT_VERSION >= "0.0.7"

    raw_006 = {
        "format": "NestCraft",
        "version": "0.0.6",
        "name": "legacy_006",
        "blocks": [
            {
                "type": "block",
                "uid": "blk-1",
                "name": "Корпус",
                "panels": [],
            }
        ],
    }
    migrated, steps = migrate_project_dict(raw_006)
    assert "0.0.6 -> 0.0.7" in steps
    assert migrated["version"] == FORMAT_VERSION
    assert migrated["blocks"][0]["joints"] == []

    # Roundtrip сохранения и загрузки проекта с параметрическим стыком и ручным отверстием
    cab = ParametricCabinet(
        "Шкаф",
        width=600,
        height=720,
        depth=560,
        thickness=16,
        shelves_count=0,
        has_facade=False,
    )
    left = _get_role(cab, "left")
    bottom = _get_role(cab, "bottom")
    manual_h = (0.0, 250.0, 180.0, 2.5, 12.0, "X")
    left.holes.append(manual_h)

    jr = JointRecord(
        uid="joint-left-bottom",
        panel_a_uid=left.uid,
        panel_b_uid=bottom.uid,
        preset_id="confirmat_3",
        params={"margin": 65.0, "count": 3, "pitch": None},
    )
    cab.add_joint(jr, apply=True)

    proj_file = tmp_path / "joints_3_1.b3d"
    save_project(proj_file, [cab], project_name="joints_3_1")

    loaded = load_project(proj_file)
    assert len(loaded.blocks) == 1
    loaded_cab = loaded.blocks[0]
    assert len(loaded_cab.joints) == 1
    loaded_jr = loaded_cab.joints[0]
    assert loaded_jr.uid == "joint-left-bottom"
    assert loaded_jr.preset_id == "confirmat_3"
    assert loaded_jr.params["margin"] == 65.0

    loaded_left = _get_role(loaded_cab, "left")
    assert loaded_left.get_manual_holes() == [manual_h]
    assert sorted(round(h[2], 2) for h in loaded_left.joint_hole_map["joint-left-bottom"]) == [
        65.0,
        280.0,
        495.0,
    ]

    # Меняем глубину после загрузки -> стык пересчитывается с сохранённым отступом 65 мм
    loaded_cab.depth = 660.0
    loaded_cab.rebuild()
    assert loaded_left.get_manual_holes() == [manual_h]
    assert sorted(round(h[2], 2) for h in loaded_left.joint_hole_map["joint-left-bottom"]) == [
        65.0,
        330.0,
        595.0,
    ]


def test_joints_dock_ui_list_preset_pitch_margin_and_delete():
    """П. 3.1: UI-панель JointsDock отображает список стыков, меняет пресет, шаг, отступы и удаляет стык."""
    from ui.panels.joints_panel import JointsDock

    try:
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
    except ImportError:
        _app = None

    block = Block("Корпус UI")
    p_a = Panel("Боковина левая", 0, 0, 0, 16, 720, 560, rebuild=False)
    p_b = Panel("Дно вкладное", 16, 0, 0, 568, 16, 560, rebuild=False)
    block.add_panel(p_a)
    block.add_panel(p_b)

    jr = JointRecord(uid="j-ui-1", panel_a_uid=p_a.uid, panel_b_uid=p_b.uid, preset_id="confirmat_3")
    block.add_joint(jr, apply=True)

    dock = JointsDock()
    stack = UndoStack()
    dock.joint_modified.connect(
        lambda blk, juid, old_s, new_s: stack.push(
            EditJointCommand(blk, juid, old_s, new_s), execute=True
        )
    )
    dock.joint_deleted.connect(
        lambda blk, juid: stack.push(DeleteJointCommand(blk, juid), execute=True)
    )

    dock.load_joints([block])
    assert dock.list_widget.count() == 1
    assert dock.select_joint_by_uid("j-ui-1")

    # 1. Смена пресета через UI (confirmat_128 -> шаг 128 мм)
    assert dock.change_selected_preset("confirmat_128")
    assert block.joints[0].preset_id == "confirmat_128"
    assert block.joints[0].params["pitch"] == 128.0

    # 2. Смена шага и отступа через UI
    assert dock.change_selected_params(pitch=96.0, margin=70.0)
    assert block.joints[0].params["pitch"] == 96.0
    assert block.joints[0].params["margin"] == 70.0
    apply_joints(block)
    zs = sorted(round(h[2], 2) for h in p_a.joint_hole_map["j-ui-1"])
    assert len(zs) >= 4
    for a, b in zip(zs, zs[1:]):
        assert abs((b - a) - 96.0) < 1e-4

    # 3. Удаление стыка через UI
    assert dock.delete_selected_joint()
    assert len(block.joints) == 0
    assert len(p_a.holes) == 0
    assert dock.list_widget.count() == 0

    # 4. Отмена удаления через UndoStack
    stack.undo()
    dock.load_joints([block])
    assert len(block.joints) == 1
    assert dock.list_widget.count() == 1
    assert len(p_a.holes) == len(zs)
