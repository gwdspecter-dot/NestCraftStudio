"""Тесты габаритной рамки изделия и создания модели NestCraft Studio.

Покрывают все 8 сценариев ТЗ (§11), миграцию формата .b3d 0.0.10 -> 0.0.11,
сохранение/загрузку метаданных (наименование, номер заказа, габаритная рамка),
обратимость через UndoStack, инвариант неизменности существующих панелей и
правила оформления UI (AGENTS.md §10).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from core.issues import check_scene_issues
from core.project_io import (
    create_autosave_snapshot,
    load_autosave,
    load_project,
    migrate_project_dict,
    save_project,
    scene_to_dict,
    write_autosave_snapshot,
)
from core.undo import EditProductParamsCommand, UndoStack
from core.version import FORMAT_VERSION
from models.bounding_frame import (
    BoundingFrame,
    MAX_FRAME_DIM_MM,
    MIN_FRAME_DIM_MM,
    validate_bounding_frame_dims,
)
from models.panel import Block, Panel

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_DIALOGS_PY = ROOT / "ui" / "product_dialogs.py"
MAIN_WINDOW_PY = ROOT / "ui" / "main_window.py"
VIEWPORT_PY = ROOT / "ui" / "viewport.py"


def _panel_snapshot(panel: Panel) -> tuple:
    return (
        panel.uid,
        panel.name,
        float(panel.x),
        float(panel.y),
        float(panel.z),
        float(panel.width),
        float(panel.height),
        float(panel.depth),
    )


# ── Тест 1: Создание изделия с габаритной рамкой ──────────────


def test_1_bounding_frame_creation_and_geometry():
    """ТЗ §11 Тест 1: изделие 800×2000×500 (X=Ширина, Y=Высота, Z=Глубина)."""
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0)
    assert bf.width == 800.0
    assert bf.height == 2000.0
    assert bf.depth == 500.0
    assert (bf.x, bf.y, bf.z) == (0.0, 0.0, 0.0)
    assert bf.visible is True

    assert bf.world_aabb() == ((0.0, 0.0, 0.0), (800.0, 2000.0, 500.0))
    assert bf.center() == (400.0, 1000.0, 250.0)
    assert len(bf.corners()) == 8
    assert len(bf.edge_segments()) == 12
    assert bf.face_planes() == {
        "x_min": 0.0,
        "x_max": 800.0,
        "y_min": 0.0,
        "y_max": 2000.0,
        "z_min": 0.0,
        "z_max": 500.0,
    }
    # 8 углов + 12 середин рёбер + 6 центров граней = 26 точек привязки
    snaps = bf.snap_points()
    assert len(snaps) == 26
    assert all(item[3] is None for item in snaps)


def test_bounding_frame_validation_rejects_invalid_values():
    """ТЗ §7: некорректные и неположительные размеры отклоняются понятным сообщением."""
    for bad in (
        (0, 2000, 500),
        (-100, 2000, 500),
        (800, 0, 500),
        (800, 2000, -5),
        (MIN_FRAME_DIM_MM - 1, 2000, 500),
        (MAX_FRAME_DIM_MM + 1, 2000, 500),
        (float("nan"), 2000, 500),
        (float("inf"), 2000, 500),
        ("abc", 2000, 500),
    ):
        with pytest.raises(ValueError):
            validate_bounding_frame_dims(*bad)


# ── Тест 2: Создание панели внутри рамки ──────────────────────


def test_2_default_panel_geometry_uses_current_bounding_frame():
    """ТЗ §11 Тест 2: стартовые размеры новой панели берутся из текущей рамки."""
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0, x=10.0, y=20.0, z=30.0)

    v = bf.default_panel_geometry("vertical", thickness=16.0)
    assert v["width"] == 16.0
    assert v["height"] == 2000.0
    assert v["depth"] == 500.0
    assert (v["dim1"], v["dim2"]) == (2000.0, 500.0)
    assert (v["x"], v["y"], v["z"]) == (10.0, 20.0, 30.0)

    h = bf.default_panel_geometry("horizontal", thickness=16.0)
    assert h["width"] == 800.0
    assert h["height"] == 16.0
    assert h["depth"] == 500.0
    assert (h["dim1"], h["dim2"]) == (800.0, 500.0)

    f = bf.default_panel_geometry("frontal", thickness=16.0)
    assert f["width"] == 800.0
    assert f["height"] == 2000.0
    assert f["depth"] == 16.0
    assert (f["dim1"], f["dim2"]) == (2000.0, 800.0)


# ── Тест 3: Выход панели за пределы рамки ─────────────────────


def test_3_panels_freely_exist_and_move_outside_bounding_frame():
    """ТЗ §11 Тест 3: панели можно создавать и сдвигать за пределы рамки без обрезки."""
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0)
    block = Block("Шкаф", "1", "01.00")

    # Столешница/козырёк шире и глубже габаритной рамки + смещена в минус по X
    overhang = Panel(
        "Крышка выступающая",
        x=-100.0,
        y=2000.0,
        z=-50.0,
        width=1200.0,
        height=16.0,
        depth=700.0,
        pos_num="1.1",
        rebuild=False,
    )
    block.add_panel(overhang)

    assert overhang in block.panels
    assert overhang.x == -100.0
    assert overhang.width == 1200.0
    assert overhang.depth == 700.0
    # Габаритная рамка осталась на своих исходных размерах
    assert (bf.width, bf.height, bf.depth) == (800.0, 2000.0, 500.0)


# ── Тест 4 и 5: Изменение параметров изделия не меняет панели ─


def test_4_and_5_editing_bounding_frame_keeps_existing_panels_untouched_with_undo():
    """ТЗ §11 Тесты 4 и 5: смена ширины/высоты/глубины обновляет только рамку + Undo/Redo."""
    block = Block("Шкаф 800", "1", "01.00")
    left_side = Panel("Боковина Л", 0.0, 0.0, 0.0, 16.0, 2000.0, 500.0, "1.1", rebuild=False)
    bottom = Panel("Дно", 16.0, 0.0, 0.0, 768.0, 16.0, 500.0, "1.2", rebuild=False)
    block.add_panel(left_side)
    block.add_panel(bottom)

    before_left = _panel_snapshot(left_side)
    before_bottom = _panel_snapshot(bottom)

    holder = {
        "name": "Шкаф 800",
        "order_number": "ЗАК-001",
        "bounding_frame": BoundingFrame(width=800.0, height=2000.0, depth=500.0),
    }

    def _apply(state: dict) -> None:
        holder["name"] = state["name"]
        holder["order_number"] = state["order_number"]
        holder["bounding_frame"] = state["bounding_frame"]

    stack = UndoStack()
    # Шаг 1: изменяем ширину 800 -> 1000 и номер заказа
    cmd1 = EditProductParamsCommand(
        old_state=dict(holder),
        new_state={
            "name": "Шкаф 1000",
            "order_number": "ЗАК-002",
            "bounding_frame": BoundingFrame(width=1000.0, height=2000.0, depth=500.0),
        },
        apply_fn=_apply,
    )
    stack.push(cmd1, execute=True)

    assert holder["name"] == "Шкаф 1000"
    assert holder["order_number"] == "ЗАК-002"
    assert holder["bounding_frame"].width == 1000.0
    assert _panel_snapshot(left_side) == before_left
    assert _panel_snapshot(bottom) == before_bottom

    # Новая панель после изменения рамки уже получает ширину 1000
    new_horiz = holder["bounding_frame"].default_panel_geometry("horizontal", thickness=16.0)
    assert new_horiz["width"] == 1000.0

    # Шаг 2: изменяем глубину 500 -> 650 и высоту 2000 -> 2400
    cmd2 = EditProductParamsCommand(
        old_state=dict(holder),
        new_state={
            "name": "Шкаф 1000",
            "order_number": "ЗАК-002",
            "bounding_frame": BoundingFrame(width=1000.0, height=2400.0, depth=650.0),
        },
        apply_fn=_apply,
    )
    stack.push(cmd2, execute=True)
    assert (
        holder["bounding_frame"].width,
        holder["bounding_frame"].height,
        holder["bounding_frame"].depth,
    ) == (1000.0, 2400.0, 650.0)
    assert _panel_snapshot(left_side) == before_left
    assert _panel_snapshot(bottom) == before_bottom

    # Undo возвращает 1000×2000×500, затем 800×2000×500; панели неизменны
    stack.undo()
    assert (
        holder["bounding_frame"].width,
        holder["bounding_frame"].height,
        holder["bounding_frame"].depth,
    ) == (1000.0, 2000.0, 500.0)
    stack.undo()
    assert holder["name"] == "Шкаф 800"
    assert holder["order_number"] == "ЗАК-001"
    assert holder["bounding_frame"].width == 800.0
    assert _panel_snapshot(left_side) == before_left
    assert _panel_snapshot(bottom) == before_bottom

    # Redo возвращает 1000×2000×500
    stack.redo()
    assert holder["bounding_frame"].width == 1000.0
    assert _panel_snapshot(left_side) == before_left


# ── Тест 6: Скрытие и показ габаритной рамки ──────────────────


def test_6_visibility_toggle_does_not_delete_frame_or_affect_panels():
    """ТЗ §11 Тест 6: скрытие рамки не удаляет объект и не влияет на расчёты."""
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0, visible=True)
    bf.visible = False
    assert bf.visible is False
    assert (bf.width, bf.height, bf.depth) == (800.0, 2000.0, 500.0)

    bf.visible = True
    assert bf.visible is True


# ── Тест 7: Сохранение, загрузка и миграция .b3d ──────────────


def test_7_save_load_roundtrip_and_autosave_preserve_order_and_bounding_frame(tmp_path: Path):
    """ТЗ §11 Тест 7: сохранение и открытие .b3d + автосохранение восстанавливают рамку и заказ."""
    block = Block("Шкаф-купе", "1", "01.00")
    p = Panel("Боковина", 0.0, 0.0, 0.0, 16.0, 2000.0, 500.0, "1.1", rebuild=False)
    block.add_panel(p)
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0, x=5.0, y=10.0, z=15.0, visible=False)

    out_path = tmp_path / "wardrobe.b3d"
    save_project(
        out_path,
        [block],
        "Шкаф-купе 800",
        order_number="ЗАК-2026-042",
        bounding_frame=bf,
    )

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["version"] == FORMAT_VERSION == "0.0.13"
    assert raw["order_number"] == "ЗАК-2026-042"
    assert raw["bounding_frame"]["width"] == 800.0
    assert raw["bounding_frame"]["visible"] is False

    res = load_project(out_path)
    assert res.name == "Шкаф-купе 800"
    assert res.order_number == "ЗАК-2026-042"
    assert res.bounding_frame is not None
    assert res.bounding_frame.to_dict() == bf.to_dict()
    assert len(res.blocks) == 1
    assert len(res.blocks[0].panels) == 1
    assert res.blocks[0].panels[0].name == "Боковина"

    # Автосохранение тоже сохраняет и восстанавливает order_number и bounding_frame
    auto_path = tmp_path / "autosave_recovery_999999.b3d"
    snap = create_autosave_snapshot(
        [block],
        project_name="Шкаф-купе 800",
        original_path=out_path,
        order_number="ЗАК-2026-042",
        bounding_frame=bf,
        autosave_path=auto_path,
        pid=999999,
    )
    write_autosave_snapshot(snap, autosave_path=auto_path)
    auto_res, auto_meta = load_autosave(autosave_path=auto_path)
    assert auto_res.order_number == "ЗАК-2026-042"
    assert auto_meta.get("order_number") == "ЗАК-2026-042"
    assert auto_res.bounding_frame is not None
    assert auto_res.bounding_frame.to_dict() == bf.to_dict()


def test_7b_migration_0_0_10_to_0_0_11_loads_legacy_project_safely(tmp_path: Path):
    """ТЗ §10: старый .b3d v0.0.10 без bounding_frame мигрирует без ошибок и без изменения панелей."""
    legacy = {
        "format": "NestCraft",
        "version": "0.0.10",
        "name": "Старый шкаф",
        "blocks": [
            {
                "type": "block",
                "uid": "blk-legacy-1",
                "name": "Корпус",
                "pos_num": "1",
                "code": "01.00",
                "joints": [],
                "assoc_refs": [],
                "panels": [
                    {
                        "uid": "pan-legacy-1",
                        "name": "Стенка",
                        "pos_num": "1.1",
                        "code": "",
                        "role": "",
                        "x": 100.0,
                        "y": 200.0,
                        "z": 50.0,
                        "rx": 0.0,
                        "ry": 0.0,
                        "rz": 0.0,
                        "width": 16.0,
                        "height": 720.0,
                        "depth": 560.0,
                        "thickness_axis": 0,
                        "material_id": "",
                        "material": "ЛДСП 16мм",
                        "color": [0.85, 0.78, 0.65],
                        "edges": {"top": "", "bottom": "", "left": "", "right": ""},
                        "grooves": [],
                        "holes": [],
                        "drivers": {},
                    }
                ],
            }
        ],
    }

    migrated, steps = migrate_project_dict(legacy, in_place=False)
    assert "0.0.10 -> 0.0.11" in steps
    assert migrated["version"] == FORMAT_VERSION
    assert migrated["order_number"] == ""
    assert migrated["bounding_frame"] is None

    legacy_path = tmp_path / "legacy_v10.b3d"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    loaded = load_project(legacy_path)
    assert loaded.bounding_frame is None
    assert loaded.order_number == ""
    assert len(loaded.blocks) == 1
    p = loaded.blocks[0].panels[0]
    assert (p.x, p.y, p.z, p.width, p.height, p.depth) == (100.0, 200.0, 50.0, 16.0, 720.0, 560.0)


# ── Тест 8: Независимость от производственных расчётов и UI AST ─


def test_8_bounding_frame_excluded_from_panels_and_issues():
    """ТЗ §11 Тест 8: рамка не попадает в Block.panels, scene_to_dict['blocks'] и check_scene_issues."""
    bf = BoundingFrame(width=800.0, height=2000.0, depth=500.0)
    block = Block("Изделие", "1", "01.00")
    p = Panel("Полка", 16.0, 400.0, 0.0, 768.0, 16.0, 480.0, "1.1", rebuild=False)
    block.add_panel(p)

    data = scene_to_dict([block], "Изделие", order_number="ЗАК-77", bounding_frame=bf)
    assert len(data["blocks"]) == 1
    assert len(data["blocks"][0]["panels"]) == 1
    assert all(isinstance(item, Panel) for item in block.panels)

    # Проверка проблем сцены работает исключительно по физическим панелям
    issues = check_scene_issues([block])
    assert all("рамк" not in str(iss.message).lower() for iss in issues)


def test_product_dialogs_have_no_hardcoded_hex_or_rgb_colors():
    """AGENTS.md §10: все цвета в ui/product_dialogs.py берутся из ui.theme.current_theme()."""
    src = PRODUCT_DIALOGS_PY.read_text(encoding="utf-8")
    hex_hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", src)
    rgb_hits = re.findall(r"\brgba?\s*\(", src)
    assert not hex_hits, f"В ui/product_dialogs.py найдены жёстко заданные hex-цвета: {hex_hits}"
    assert not rgb_hits, f"В ui/product_dialogs.py найдены жёстко заданные rgb()-цвета: {rgb_hits}"


def test_product_dialogs_main_window_and_viewport_wiring_ast():
    """Проверяет наличие ключевых классов, режимов и методов через AST без запуска Qt."""
    dlg_src = PRODUCT_DIALOGS_PY.read_text(encoding="utf-8")
    dlg_tree = ast.parse(dlg_src, filename="ui/product_dialogs.py")
    dlg_classes = {n.name for n in dlg_tree.body if isinstance(n, ast.ClassDef)}
    assert {"CreateModelDialog", "ProductParamsDialog"} <= dlg_classes
    assert '"Габаритная рамка"' in dlg_src
    assert '"Габаритная рамка помещения"' in dlg_src
    assert '"Планировка помещения"' in dlg_src
    assert '"Наименование:"' in dlg_src
    assert '"Номер заказа:"' in dlg_src

    mw_src = MAIN_WINDOW_PY.read_text(encoding="utf-8")
    mw_tree = ast.parse(mw_src, filename="ui/main_window.py")
    mw_cls = next(n for n in mw_tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    mw_methods = {n.name for n in mw_cls.body if isinstance(n, ast.FunctionDef)}
    for req in (
        "_on_home_create_model",
        "_create_model_with_settings",
        "open_product_params_dialog",
        "_apply_product_params_state",
        "_toggle_bounding_frame_visible",
        "_sync_bounding_frame_action",
    ):
        assert req in mw_methods, f"MainWindow не содержит метод {req}"
    assert '"Параметры изделия…"' in mw_src
    assert '"Показать габаритную рамку"' in mw_src

    vp_src = VIEWPORT_PY.read_text(encoding="utf-8")
    vp_tree = ast.parse(vp_src, filename="ui/viewport.py")
    vp_cls = next(n for n in vp_tree.body if isinstance(n, ast.ClassDef) and n.name == "Viewport3D")
    vp_methods = {n.name for n in vp_cls.body if isinstance(n, ast.FunctionDef)}
    for req in ("set_bounding_frame", "set_bounding_frame_visible", "_draw_bounding_frame"):
        assert req in vp_methods, f"Viewport3D не содержит метод {req}"


@pytest.mark.gui
def test_create_model_and_product_params_dialogs_gui():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    from ui.product_dialogs import CreateModelDialog, ProductParamsDialog
    from ui.theme import DARK, LIGHT, apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, LIGHT)

    dlg = CreateModelDialog()
    assert dlg.mode_tabs.count() == 2
    assert dlg.mode_tabs.tabText(0) == "Габаритная рамка"
    assert dlg.mode_tabs.tabText(1) == "Габаритная рамка помещения"
    assert dlg.current_mode() == CreateModelDialog.MODE_BOUNDING_FRAME

    # На вкладке «Габаритная рамка помещения» ОК блокируется до завершения планировки
    ok_btn = dlg.button_box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None and ok_btn.isEnabled()
    dlg.mode_tabs.setCurrentIndex(1)
    assert not ok_btn.isEnabled()
    dlg.mode_tabs.setCurrentIndex(0)
    assert ok_btn.isEnabled()

    # Невалидная ширина (0) не закрывает диалог и показывает ошибку
    dlg.width_spin.setValue(0.0)
    dlg._on_accept()
    assert dlg._error_label.isVisible()

    # Корректные данные проходят валидацию
    dlg.name_edit.setText("Шкаф распашной")
    dlg.order_edit.setText("ЗАК-105")
    dlg.width_spin.setValue(800.0)
    dlg.height_spin.setValue(2000.0)
    dlg.depth_spin.setValue(500.0)
    dlg._on_accept()
    settings = dlg.get_model_settings()
    assert settings["name"] == "Шкаф распашной"
    assert settings["order_number"] == "ЗАК-105"
    assert (
        settings["bounding_frame"].width,
        settings["bounding_frame"].height,
        settings["bounding_frame"].depth,
    ) == (800.0, 2000.0, 500.0)

    # Диалог «Параметры изделия» и смена темы
    apply_theme(app, DARK)
    pdlg = ProductParamsDialog(
        name="Шкаф распашной",
        order_number="ЗАК-105",
        bounding_frame=settings["bounding_frame"],
    )
    pdlg.width_spin.setValue(1000.0)
    pdlg.visible_cb.setChecked(False)
    pdlg._on_accept()
    updated = pdlg.get_product_params()
    assert updated["bounding_frame"].width == 1000.0
    assert updated["bounding_frame"].visible is False
    apply_theme(app, LIGHT)
