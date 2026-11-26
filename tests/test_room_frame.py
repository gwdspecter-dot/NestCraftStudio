"""Тесты режима «Габаритная рамка помещения» (Room Frame Mode) NestCraft Studio.

Покрывают все критерии приёмки ТЗ (§14):
1. Произвольный контур помещения (непрямые углы, непараллельные стены, ниши и выступы).
2. Индивидуальные параметры стен, видимость и точки замеров неровностей (2D-интерполяция + 3D-меш).
3. Проёмы (двери с дугой открывания, окна с подоконником, проходы), реально вырезанные в геометрии стен.
4. Препятствия и зоны обслуживания.
5. Размещение нескольких независимых изделий мебели с сохранением локальной СК.
6. Привязка изделий к стенам под произвольным углом с отступом и выравниванием по полу.
7. Диагностика коллизий (стены, проёмы, зона открывания двери, препятствия, соседняя мебель, выход за контур)
   с учётом допуска касания и анализ зазоров до неровной стены.
8. Сериализация `.b3d` v0.0.13, миграция `0.0.12 -> 0.0.13`, обратная совместимость и Undo/Redo.
9. Отсутствие жёстко заданных цветов (AGENTS.md §10) и наличие 17 SVG-иконок помещения.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

import pytest

from core.project_io import (
    create_autosave_snapshot,
    load_autosave,
    load_project,
    migrate_project_dict,
    save_project,
    scene_to_dict,
    write_autosave_snapshot,
)
from core.room_geometry import (
    build_floor_ceiling_meshes,
    build_opening_visual_edges,
    build_wall_mesh,
    check_room_issues,
    collect_room_snap_points,
    compute_room_wall_alpha,
    door_swing_geometry_xz,
    is_wall_occluding_camera,
    measure_product_wall_gaps,
    room_display_style,
    snap_product_to_wall,
)
from core.undo import EditRoomWorkspaceCommand, UndoStack
from core.version import FORMAT_VERSION
from models.bounding_frame import BoundingFrame
from models.panel import Block, Panel
from models.room_frame import (
    PlacedProduct,
    RoomFrame,
    RoomObstacle,
    RoomWorkspace,
    WallDeviationStation,
    WallOpening,
)

ROOT = Path(__file__).resolve().parent.parent
ROOM_DIALOG_PY = ROOT / "ui" / "room_layout_dialog.py"
PRODUCT_DIALOGS_PY = ROOT / "ui" / "product_dialogs.py"
ICONS_DIR = ROOT / "ui" / "icons"


# ── 1. Контур помещения, непрямые углы, ниши и выступы ───────


def test_non_rectangular_room_with_non_90_angles_and_niche():
    """ТЗ §14: помещение со стенами под непрямыми углами и непараллельными стенами + ниша."""
    rf = RoomFrame.from_polygon(
        [
            (0.0, 0.0),
            (4000.0, 0.0),
            (3600.0, 3000.0),
            (400.0, 3100.0),
        ],
        height_mm=2750.0,
    )
    assert len(rf.walls) == 4
    rf.validate()
    assert rf.floor_area_m2() > 9.0

    angles = [rf.interior_angle_at_vertex(v.uid) for v in rf.vertices]
    assert any(abs(a - 90.0) > 3.0 for a in angles)
    assert math.isclose(sum(angles), 360.0, abs_tol=0.5)

    # Изменяем угол при начале стены 1 до 102°
    rf.set_wall_angle_at_start(rf.walls[1].uid, 102.0)
    assert abs(rf.wall_geometry(rf.walls[1]).interior_angle_start_deg - 102.0) < 0.5

    # Добавляем нишу (глубина -300 мм наружу) на стене 0
    rf.insert_niche_or_protrusion(
        rf.walls[0].uid,
        start_s_mm=1000.0,
        width_mm=1200.0,
        depth_mm=-300.0,
    )
    assert len(rf.walls) == 8
    rf.validate()

    # Пол и потолок корректно триангулируются для невыпуклого контура с нишей
    floor_mesh, ceil_mesh = build_floor_ceiling_meshes(rf)
    assert len(floor_mesh.indices) >= 18
    assert len(ceil_mesh.indices) >= 18


def test_wall_length_and_split_preserve_closed_contour():
    """Изменение длины стены и разделение стены сохраняют замкнутый валидный контур."""
    rf = RoomFrame.create_rectangular(3000.0, 2500.0, 2700.0)
    rf.set_wall_length(rf.walls[0].uid, 3800.0)
    assert math.isclose(rf.wall_geometry(rf.walls[0]).length_mm, 3800.0, abs_tol=1e-3)
    rf.validate()

    rf.split_wall(rf.walls[1].uid, ratio=0.5)
    assert len(rf.walls) == 5
    rf.validate()


# ── 2. Неровности стен (2D-интерполяция и 3D-геометрия) ──────


def test_wall_deviations_affect_surface_mesh_and_gap_report():
    """ТЗ §14: точки замера неровностей смещают внутреннюю плоскость стены и влияют на расчёт зазоров."""
    rf = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    w0 = rf.walls[0]
    # В центре стены на высоте 1000 мм выступ внутрь +20 мм, по краям 0 мм и -10 мм (впадина)
    rf.add_deviation_station(w0.uid, WallDeviationStation(s_mm=200.0, height_mm=1000.0, offset_mm=0.0))
    rf.add_deviation_station(w0.uid, WallDeviationStation(s_mm=1000.0, height_mm=1000.0, offset_mm=20.0))
    rf.add_deviation_station(w0.uid, WallDeviationStation(s_mm=1800.0, height_mm=1000.0, offset_mm=-10.0))

    assert math.isclose(rf.evaluate_wall_offset(w0, 200.0, 1000.0), 0.0, abs_tol=1e-6)
    assert math.isclose(rf.evaluate_wall_offset(w0, 1000.0, 1000.0), 20.0, abs_tol=1e-6)
    assert math.isclose(rf.evaluate_wall_offset(w0, 1800.0, 1000.0), -10.0, abs_tol=1e-6)

    # 3D-меш стены отражает выступ внутрь помещения (>= 15 мм)
    mesh = build_wall_mesh(rf, w0)
    max_z = max(p[2] for p in mesh.vertices)
    min_z = min(p[2] for p in mesh.vertices)
    assert max_z >= 15.0
    assert min_z <= -w0.thickness_mm + 1.0

    # Привязываем шкаф 1600×2000×500 к стене 0 с отступом 25 мм
    prod = PlacedProduct(
        name="Шкаф-купе",
        bounding_frame=BoundingFrame(width=1600.0, height=2000.0, depth=500.0),
    )
    snap_product_to_wall(rf, prod, w0.uid, offset_mm=25.0, s_position_mm=200.0)
    rep = measure_product_wall_gaps(rf, prod, w0.uid)
    assert len(rep.samples) == 9
    assert rep.min_gap_mm < 12.0
    assert rep.max_gap_mm > 22.0
    assert rep.delta_gap_mm > 15.0


# ── 3. Проёмы (двери, окна, проходы) и вырезы в 3D ──────────


def test_openings_cut_out_wall_mesh_and_door_swing_collision():
    """ТЗ §14: проёмы вырезаются в стене; мебель в зоне открывания двери фиксируется в проблемах."""
    rf = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    w0 = rf.walls[0]
    plain_mesh = build_wall_mesh(rf, w0)

    door = WallOpening(
        kind="door",
        name="Входная дверь",
        offset_s_mm=500.0,
        width_mm=900.0,
        height_mm=2100.0,
        sill_height_mm=0.0,
        swing_dir="inward_left",
        swing_angle_deg=90.0,
    )
    rf.add_opening(w0.uid, door)
    cut_mesh = build_wall_mesh(rf, w0)
    assert len(cut_mesh.indices) > len(plain_mesh.indices)

    swing = door_swing_geometry_xz(rf, w0, door)
    assert swing is not None
    assert len(swing["arc_points_xz"]) >= 12
    op_edges, _op_mesh = build_opening_visual_edges(rf, w0, door)
    assert len(op_edges) >= 12

    ws = RoomWorkspace(room_frame=rf)
    ws.add_product(
        PlacedProduct(
            name="Тумба в проходе",
            bounding_frame=BoundingFrame(width=600.0, height=720.0, depth=450.0),
            x=600.0,
            y=0.0,
            z=120.0,
        )
    )
    issues = check_room_issues(ws)
    codes = {i.code for i in issues}
    assert "room_door_swing_blocked" in codes


# ── 4. Препятствия, зоны обслуживания, мебель и допуск касания ─


def test_obstacles_clearance_furniture_collisions_and_contact_tolerance():
    """ТЗ §14: коллизии с препятствиями/зоной обслуживания, соседней мебелью и отсутствие ложного срабатывания при касании."""
    rf = RoomFrame.create_rectangular(4500.0, 3500.0, 2700.0)
    w0 = rf.walls[0]
    rf.add_obstacle(
        RoomObstacle(
            kind="radiator",
            name="Радиатор отопления",
            x=1500.0,
            y=150.0,
            z=50.0,
            width=800.0,
            height=600.0,
            depth=120.0,
            clearance_mm=100.0,
        )
    )

    ws = RoomWorkspace(room_frame=rf)
    p1 = PlacedProduct(
        name="Шкаф левый",
        bounding_frame=BoundingFrame(width=800.0, height=2000.0, depth=500.0),
    )
    snap_product_to_wall(rf, p1, w0.uid, offset_mm=0.0, s_position_mm=200.0)

    # Изделие 2 стоит вплотную справа к изделию 1 (касание без перекрытия)
    p2 = PlacedProduct(
        name="Шкаф средний",
        bounding_frame=BoundingFrame(width=500.0, height=2000.0, depth=500.0),
        x=p1.x + p1.bounding_frame.width,
        y=0.0,
        z=p1.z,
        rotation_y_deg=p1.rotation_y_deg,
    )
    ws.add_product(p1)
    ws.add_product(p2)

    issues_clean = check_room_issues(ws)
    assert not any(
        i.code in ("room_wall_collision", "room_furniture_collision", "room_obstacle_collision")
        for i in issues_clean
    ), f"Неожиданные коллизии при чистом касании: {[i.code for i in issues_clean]}"

    # Сдвигаем p2 на 50 мм внутрь p1 и добавляем тумбу в зону радиатора
    p2.x -= 50.0
    p3 = PlacedProduct(
        name="Тумба у радиатора",
        bounding_frame=BoundingFrame(width=600.0, height=800.0, depth=400.0),
        x=1420.0,
        y=0.0,
        z=100.0,
    )
    ws.add_product(p3)

    issues_bad = check_room_issues(ws)
    bad_codes = {i.code for i in issues_bad}
    assert "room_furniture_collision" in bad_codes
    assert "room_obstacle_collision" in bad_codes or "room_obstacle_clearance" in bad_codes


def test_snap_product_to_angled_wall_and_independent_local_coords():
    """ТЗ §14: привязка изделия к наклонной стене сохраняет локальные координаты панелей неизменными."""
    rf = RoomFrame.from_polygon([(0.0, 0.0), (3000.0, 1000.0), (2200.0, 3500.0), (-200.0, 2800.0)])
    w0 = rf.walls[0]
    blk = Block("Шкаф", "", "", is_assembly=False, is_root=True)
    blk.add_panel(Panel("Боковина Л", 0.0, 0.0, 0.0, 16.0, 2000.0, 500.0, rebuild=False))

    prod = PlacedProduct(
        name="Шкаф угловой",
        bounding_frame=BoundingFrame(width=800.0, height=2000.0, depth=500.0),
        blocks_data=scene_to_dict([blk], "Шкаф")["blocks"],
    )
    before_panel_x = prod.blocks_data[0]["panels"][0]["x"]
    snap_product_to_wall(rf, prod, w0.uid, offset_mm=15.0, s_position_mm=400.0)

    # Локальные координаты панели внутри изделия не искажены
    assert prod.blocks_data[0]["panels"][0]["x"] == before_panel_x
    assert prod.wall_offset_mm == 15.0
    assert prod.anchor_wall_uid == w0.uid
    # Угол поворота ненулевой, т.к. стена наклонная
    assert abs(prod.rotation_y_deg) > 10.0

    ws = RoomWorkspace(room_frame=rf, products=[prod])
    snaps = collect_room_snap_points(ws)
    assert len(snaps) >= 20


# ── 5. Сохранение/загрузка .b3d v0.0.13, миграция и Undo/Redo ─


def test_b3d_v0_0_13_roundtrip_autosave_and_migration(tmp_path: Path):
    """ТЗ §14: сохранение/загрузка проекта помещения, автосохранение и миграция v0.0.12 -> v0.0.13."""
    rf = RoomFrame.from_polygon([(0.0, 0.0), (4200.0, 0.0), (4000.0, 3100.0), (0.0, 3000.0)])
    w0 = rf.walls[0]
    rf.add_opening(
        w0.uid,
        WallOpening(
            kind="window",
            name="Окно кухни",
            offset_s_mm=1200.0,
            width_mm=1400.0,
            height_mm=1450.0,
            sill_height_mm=850.0,
        ),
    )
    rf.add_deviation_station(w0.uid, WallDeviationStation(s_mm=2000.0, height_mm=1200.0, offset_mm=12.0))
    rf.add_obstacle(
        RoomObstacle(
            kind="column",
            name="Колонна",
            x=3600.0,
            y=0.0,
            z=2600.0,
            width=300.0,
            height=2700.0,
            depth=300.0,
        )
    )
    rf.walls_translucent = True

    ws = RoomWorkspace(room_frame=rf)
    ws.add_product(
        PlacedProduct(
            name="Кухня низ",
            order_number="ЗАК-77-1",
            bounding_frame=BoundingFrame(width=1800.0, height=850.0, depth=600.0),
            x=300.0,
            y=0.0,
            z=20.0,
        )
    )

    out_path = tmp_path / "kitchen_room.b3d"
    save_project(
        out_path,
        [],
        "Кухня-гостиная",
        order_number="ЗАК-77",
        workspace_mode="room",
        room_workspace=ws,
    )
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["version"] == FORMAT_VERSION == "0.0.13"
    assert raw["workspace_mode"] == "room"
    assert raw["room_workspace"] is not None

    loaded = load_project(out_path)
    assert loaded.name == "Кухня-гостиная"
    assert loaded.order_number == "ЗАК-77"
    assert loaded.workspace_mode == "room"
    assert loaded.room_workspace is not None
    assert len(loaded.room_workspace.room_frame.walls) == 4
    assert len(loaded.room_workspace.room_frame.walls[0].openings) == 1
    assert len(loaded.room_workspace.room_frame.walls[0].deviation_stations) == 1
    assert len(loaded.room_workspace.room_frame.obstacles) == 1
    assert len(loaded.room_workspace.products) == 1
    assert loaded.room_workspace.products[0].name == "Кухня низ"
    assert loaded.room_workspace.room_frame.walls_translucent is True

    # Автосохранение тоже сохраняет room_workspace
    auto_path = tmp_path / "autosave_room_999.b3d"
    snap = create_autosave_snapshot(
        [],
        project_name="Кухня-гостиная",
        original_path=out_path,
        order_number="ЗАК-77",
        workspace_mode="room",
        room_workspace=ws,
        autosave_path=auto_path,
        pid=999,
    )
    write_autosave_snapshot(snap, autosave_path=auto_path)
    auto_res, _meta = load_autosave(autosave_path=auto_path)
    assert auto_res.workspace_mode == "room"
    assert auto_res.room_workspace is not None
    assert len(auto_res.room_workspace.products) == 1

    # Миграция старого файла v0.0.12 (обычное изделие) -> v0.0.13 без ошибок
    legacy_v12 = {
        "format": "NestCraft",
        "version": "0.0.12",
        "name": "Обычный шкаф",
        "order_number": "ЗАК-12",
        "bounding_frame": BoundingFrame(800.0, 2000.0, 500.0).to_dict(),
        "blocks": [],
    }
    migrated, steps = migrate_project_dict(legacy_v12, in_place=False)
    assert steps == ["0.0.12 -> 0.0.13"]
    assert migrated["version"] == "0.0.13"
    assert migrated["workspace_mode"] == "product"
    assert migrated["room_workspace"] is None


def test_undo_redo_room_workspace_command():
    """Undo/Redo обратимо откатывает и повторяет изменения помещения и размещённой мебели."""
    ws1 = RoomWorkspace(room_frame=RoomFrame.create_rectangular(3000.0, 2500.0, 2700.0))
    ws2 = ws1.clone()
    ws2.room_frame.set_wall_length(ws2.room_frame.walls[0].uid, 3600.0)
    ws2.add_product(
        PlacedProduct(name="Пенал", bounding_frame=BoundingFrame(600.0, 2100.0, 560.0))
    )

    state = {"ws": ws1}

    def _apply(w: RoomWorkspace) -> None:
        state["ws"] = w

    stack = UndoStack()
    stack.push(
        EditRoomWorkspaceCommand(
            old_workspace=ws1,
            new_workspace=ws2,
            apply_fn=_apply,
            description="Добавить пенал",
        ),
        execute=True,
    )
    assert len(state["ws"].products) == 1
    assert math.isclose(
        state["ws"].room_frame.wall_geometry(state["ws"].room_frame.walls[0]).length_mm,
        3600.0,
        abs_tol=1e-2,
    )

    stack.undo()
    assert len(state["ws"].products) == 0
    assert math.isclose(
        state["ws"].room_frame.wall_geometry(state["ws"].room_frame.walls[0]).length_mm,
        3000.0,
        abs_tol=1e-2,
    )

    stack.redo()
    assert len(state["ws"].products) == 1

    # Регрессия: проверяем, что main_window.py передаёт корректные именованные аргументы
    mw_src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    mw_tree = ast.parse(mw_src, filename="ui/main_window.py")
    sig_params = set(EditRoomWorkspaceCommand.__init__.__code__.co_varnames)
    found_call = False
    for node in ast.walk(mw_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "EditRoomWorkspaceCommand":
            found_call = True
            for kw in node.keywords:
                assert kw.arg in sig_params, f"Неизвестный аргумент {kw.arg!r} в EditRoomWorkspaceCommand"
    assert found_call, "Вызов EditRoomWorkspaceCommand не найден в ui/main_window.py"


# ── 6. Правила оформления (AGENTS.md §10) и наличие SVG-иконок ─


def test_room_ui_has_no_hardcoded_colors_and_all_svg_icons_exist():
    """AGENTS.md §10: нулевые жёсткие hex/rgb-цвета в room_layout_dialog.py и валидные SVG-иконки."""
    for path in (ROOM_DIALOG_PY, PRODUCT_DIALOGS_PY):
        src = path.read_text(encoding="utf-8")
        hex_hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", src)
        rgb_hits = re.findall(r"\brgba?\s*\(", src)
        assert not hex_hits, f"Найдены жёсткие hex-цвета в {path.name}: {hex_hits}"
        assert not rgb_hits, f"Найдены жёсткие rgb()-цвета в {path.name}: {rgb_hits}"

    expected_icons = (
        "room_frame.svg",
        "room_plan.svg",
        "room_wall.svg",
        "room_door.svg",
        "room_window.svg",
        "room_passage.svg",
        "room_niche.svg",
        "room_deviation.svg",
        "room_obstacle.svg",
        "room_furniture.svg",
        "room_snap_wall.svg",
        "room_gap_check.svg",
        "room_edit_product.svg",
        "room_back_to_room.svg",
        "room_check_done.svg",
        "room_2d_view.svg",
        "room_3d_view.svg",
    )
    for icon_name in expected_icons:
        p = ICONS_DIR / icon_name
        assert p.is_file(), f"Отсутствует SVG-иконка {icon_name}"
        content = p.read_text(encoding="utf-8")
        assert "<svg" in content and "currentColor" in content

    dlg_src = PRODUCT_DIALOGS_PY.read_text(encoding="utf-8")
    assert "Габаритная рамка помещения" in dlg_src
    assert "Планировка помещения" in dlg_src
    assert "Планировка закончена" in dlg_src

    rl_src = ROOM_DIALOG_PY.read_text(encoding="utf-8")
    assert "Закончить планировку" in rl_src
    assert "vertex_selected" in rl_src
    assert "vertex_angle_spin" in rl_src
    assert "btn_del_wall" in rl_src
    assert "_bind_enter_apply" in rl_src
    assert "btn_apply_wall" not in rl_src
    tree = ast.parse(rl_src, filename="ui/room_layout_dialog.py")
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert {"RoomPlan2DCanvas", "RoomLayoutDialog", "SnapProductToWallDialog", "WallGapReportDialog"} <= classes


# ── 7. Правки: незамкнутый контур, углы по вершинам, прозрачность, скрытие стен и прямая сборка ─


def test_delete_single_wall_keeps_open_contour_and_roundtrips(tmp_path: Path):
    """Удаление одной стены оставляет контур помещения незамкнутым, валидным и сохраняемым вместе с панелями."""
    rf = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    assert rf.is_closed() is True

    # Удаляем одну стену — остаётся 3-стенная П-образная незамкнутая комната
    rf.delete_wall(rf.walls[2].uid)
    assert rf.is_closed() is False
    assert len(rf.walls) == 3
    rf.validate()

    # Угловыми точками остаются только реальные стыки 2 стен (у концов контура угла нет)
    corner_count = sum(1 for v in rf.vertices if rf.has_corner_angle(v.uid))
    assert corner_count == 2

    # 3D-геометрия стен и пола строится без ошибок
    for w in rf.walls:
        mesh = build_wall_mesh(rf, w)
        assert len(mesh.vertices) > 0
    floor_mesh, _ceil_mesh = build_floor_ceiling_meshes(rf)
    assert len(floor_mesh.vertices) >= 4

    # Для незамкнутого контура проверка «выход за пределы контура» не выдаёт ложных ошибок
    ws = RoomWorkspace(room_frame=rf)
    ws.add_product(
        PlacedProduct(
            name="Остров",
            bounding_frame=BoundingFrame(width=1200.0, height=900.0, depth=700.0),
            x=1200.0,
            y=0.0,
            z=3500.0,
        )
    )
    issues = check_room_issues(ws)
    assert not any(i.code == "room_outside_bounds" for i in issues)

    # Прямое конструирование панелей внутри помещения сохраняется и загружается вместе с room_workspace
    direct_blk = Block("Прямой корпус", "", "", is_assembly=False, is_root=True)
    direct_blk.add_panel(Panel("Стенка левая", 200.0, 0.0, 200.0, 16.0, 2000.0, 500.0, rebuild=False))

    out_path = tmp_path / "open_room_with_panels.b3d"
    save_project(
        out_path,
        [direct_blk],
        "П-образная кухня",
        order_number="ЗАК-99",
        workspace_mode="room",
        room_workspace=ws,
    )
    loaded = load_project(out_path)
    assert loaded.workspace_mode == "room"
    assert loaded.room_workspace is not None
    assert loaded.room_workspace.room_frame.is_closed() is False
    assert len(loaded.room_workspace.room_frame.walls) == 3
    assert sum(len(b.panels) for b in loaded.blocks) == 1
    assert loaded.blocks[0].panels[0].name == "Стенка левая"


def test_vertex_angle_change_preserves_other_angles():
    """Изменение угла в вершине не искажает соседние углы (незамкнутый и замкнутый контуры)."""
    # 1. Незамкнутый П-образный контур: жёсткий поворот ведомой цепочки сохраняет второй угол и все длины
    rf_open = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    rf_open.delete_wall(rf_open.walls[2].uid)  # оставляем стены 0, 1, 3 (связанная цепочка: 3 -> 0 -> 1)
    # Упорядоченная цепочка вершин: [v3, v0, v1, v2], углы в v0 и v1
    v0 = rf_open.vertices[0].uid
    v1 = rf_open.vertices[1].uid
    orig_lengths = [rf_open.wall_geometry(w).length_mm for w in rf_open.walls]

    rf_open.set_vertex_angle(v0, 110.0)
    assert abs(rf_open.interior_angle_at_vertex(v0) - 110.0) < 0.05
    assert abs(rf_open.interior_angle_at_vertex(v1) - 90.0) < 0.05
    new_lengths = [rf_open.wall_geometry(w).length_mm for w in rf_open.walls]
    for old_l, new_l in zip(orig_lengths, new_lengths):
        assert math.isclose(old_l, new_l, abs_tol=1e-2)

    # 2. Замкнутый 4-угольник: изменение угла в v1 до 105° не меняет углы в v0 и v3
    rf_closed = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    cv0, cv1, _cv2, cv3 = [v.uid for v in rf_closed.vertices]
    rf_closed.set_vertex_angle(cv1, 105.0)
    assert abs(rf_closed.interior_angle_at_vertex(cv1) - 105.0) < 0.05
    assert abs(rf_closed.interior_angle_at_vertex(cv0) - 90.0) < 0.05
    assert abs(rf_closed.interior_angle_at_vertex(cv3) - 90.0) < 0.05
    rf_closed.validate()


def test_wireframe_and_xray_wall_display_matches_panel_logic():
    """В режимах «Каркас» и «X-Ray» стены рисуются контурами по логике панелей (без заливки)."""
    assert room_display_style("solid") == "solid"
    assert room_display_style("wireframe") == "wireframe"
    assert room_display_style("solid", wireframe_only=True) == "wireframe"
    assert room_display_style("xray") == "xray"

    assert compute_room_wall_alpha("solid", walls_translucent=False) == 1.0
    assert compute_room_wall_alpha("wireframe", walls_translucent=False) == 0.0
    assert compute_room_wall_alpha("solid", wireframe_only=True, walls_translucent=False) == 0.0
    assert compute_room_wall_alpha("xray", walls_translucent=False) == 0.0
    assert math.isclose(compute_room_wall_alpha("solid", walls_translucent=True, custom_alpha=0.45), 0.45)

    # Проверяем, что Viewport3D учитывает room_workspace в _scene_view_depth_bounds и _draw_scene_xray
    vp_src = (ROOT / "ui" / "viewport.py").read_text(encoding="utf-8")
    vp_tree = ast.parse(vp_src, filename="ui/viewport.py")
    methods = {}
    for node in ast.walk(vp_tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("_scene_view_depth_bounds", "_draw_scene_xray"):
            methods[node.name] = ast.get_source_segment(vp_src, node) or ""
    assert "room_workspace" in methods["_scene_view_depth_bounds"]
    assert "_collect_room_render_data" in methods["_draw_scene_xray"]
    assert "_draw_room_edge_batches" in methods["_draw_scene_xray"]


def test_camera_auto_hide_front_walls_and_corner_visibility():
    """Стены перед камерой скрываются автоматически; при взгляде на угол скрываются обе стены."""
    rf = RoomFrame.create_rectangular(4000.0, 3000.0, 2700.0)
    # Стена 0: z=0 (внутрь +Z); Стена 1: x=4000 (внутрь -X);
    # Стена 2: z=3000 (внутрь -Z); Стена 3: x=0 (внутрь +X).
    w0, w1, w2, w3 = rf.walls

    # Смотрим прямо спереди (+Z): скрывается только передняя стена 0
    fwd_front = (0.0, -0.25, 0.97)
    assert is_wall_occluding_camera(rf, w0, fwd_front) is True
    assert is_wall_occluding_camera(rf, w1, fwd_front) is False
    assert is_wall_occluding_camera(rf, w2, fwd_front) is False
    assert is_wall_occluding_camera(rf, w3, fwd_front) is False

    # Повернули камеру направо (смотрим влево -X): стена 0 появилась, стена 1 скрылась
    fwd_right = (-0.97, -0.25, 0.0)
    assert is_wall_occluding_camera(rf, w0, fwd_right) is False
    assert is_wall_occluding_camera(rf, w1, fwd_right) is True
    assert is_wall_occluding_camera(rf, w2, fwd_right) is False
    assert is_wall_occluding_camera(rf, w3, fwd_right) is False

    # Смотрим на передний правый угол: скрываются ОБЕ стены (w0 и w1), задние видны
    fwd_corner = (-0.68, -0.25, 0.68)
    assert is_wall_occluding_camera(rf, w0, fwd_corner) is True
    assert is_wall_occluding_camera(rf, w1, fwd_corner) is True
    assert is_wall_occluding_camera(rf, w2, fwd_corner) is False
    assert is_wall_occluding_camera(rf, w3, fwd_corner) is False

    # В 2D-плане и при взгляде строго сверху стены не скрываются
    for w in rf.walls:
        assert is_wall_occluding_camera(rf, w, fwd_corner, view_mode="2d") is False
        assert is_wall_occluding_camera(rf, w, (0.0, -0.98, 0.19), view_mode="3d") is False


def test_room_ui_call_signatures_match_core_apis():
    """Регрессия: все вызовы API помещения (SimpleMesh.add_quad, EditRoomWorkspaceCommand и др.) в ui/ совпадают по сигнатурам."""
    import inspect

    import core.room_geometry as rg_mod
    import core.undo as undo_mod
    import models.room_frame as rf_mod

    targets: dict[str, object] = {}
    for mod in (rf_mod, rg_mod, undo_mod):
        for name, obj in vars(mod).items():
            if inspect.isfunction(obj):
                targets[name] = inspect.signature(obj)
            elif inspect.isclass(obj):
                try:
                    targets[name] = inspect.signature(obj)
                except (TypeError, ValueError):
                    pass
                for mname, mobj in vars(obj).items():
                    if not mname.startswith("_") and callable(mobj):
                        fn = mobj.__func__ if isinstance(mobj, (staticmethod, classmethod)) else mobj
                        try:
                            targets[f".{mname}"] = (
                                obj.__name__,
                                inspect.signature(fn),
                                isinstance(mobj, staticmethod),
                            )
                        except (TypeError, ValueError):
                            pass

    common_names = {"clone", "to_dict", "from_dict", "validate", "get", "update", "clear", "add", "remove", "undo", "redo", "push"}
    ui_files = (
        ROOT / "ui" / "viewport.py",
        ROOT / "ui" / "main_window.py",
        ROOT / "ui" / "room_layout_dialog.py",
        ROOT / "ui" / "panels" / "structure_panel.py",
        ROOT / "ui" / "panels" / "properties_panel.py",
        ROOT / "ui" / "product_dialogs.py",
    )
    mismatches: list[str] = []
    for f in ui_files:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            has_star = any(isinstance(a, ast.Starred) for a in node.args) or any(
                k.arg is None for k in node.keywords
            )
            if has_star:
                continue
            if isinstance(node.func, ast.Name) and node.func.id in targets:
                sig = targets[node.func.id]
                try:
                    sig.bind(*([None] * len(node.args)), **{k.arg: None for k in node.keywords})
                except TypeError as exc:
                    mismatches.append(f"{f.name}:{node.lineno} {node.func.id}(...) -> {exc}")
            elif isinstance(node.func, ast.Attribute):
                key = f".{node.func.attr}"
                if key in targets and node.func.attr not in common_names:
                    cls_name, sig, is_static = targets[key]
                    pos_n = len(node.args) if is_static else len(node.args) + 1
                    try:
                        sig.bind(*([None] * pos_n), **{k.arg: None for k in node.keywords})
                    except TypeError as exc:
                        mismatches.append(f"{f.name}:{node.lineno} .{node.func.attr}(...) [{cls_name}] -> {exc}")

    assert not mismatches, "Найдены несоответствия сигнатур вызовов:\n" + "\n".join(mismatches)


@pytest.mark.gui
def test_room_layout_and_create_model_dialog_gui():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    from ui.product_dialogs import CreateModelDialog
    from ui.room_layout_dialog import RoomLayoutDialog
    from ui.theme import DARK, LIGHT, apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, LIGHT)

    dlg = CreateModelDialog()
    assert dlg.mode_tabs.tabText(1) == "Габаритная рамка помещения"
    dlg.mode_tabs.setCurrentIndex(1)
    ok_btn = dlg.button_box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None and not ok_btn.isEnabled()

    r_dlg = RoomLayoutDialog()
    rf = r_dlg.get_room_frame()
    dlg._room_frame = rf
    dlg._room_layout_done = True
    dlg._sync_room_status_ui()
    dlg._sync_ok_button_state()
    assert ok_btn.isEnabled()
    assert dlg.room_status_label.text() == "Планировка закончена"

    settings = dlg.get_model_settings()
    assert settings["mode"] == CreateModelDialog.MODE_ROOM_LAYOUT
    assert settings["room_frame"] is not None

    apply_theme(app, DARK)
    apply_theme(app, LIGHT)
