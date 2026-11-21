# -*- coding: utf-8 -*-
"""Тесты ассоциативных ссылок (AssocRef / face_hole)."""

from __future__ import annotations

from core.assoc import (
    AssocRef,
    apply_assoc_refs,
    capture_face_hint,
    evaluate_assoc_ref,
    face_point_world,
    freeze_assoc_ref_state,
    hole_assoc_uid,
    panel_face_frame,
    rebind_assoc_ref_state,
    resolve_assoc_world_point,
    suggest_rebind_face,
    unfreeze_assoc_ref_state,
)
from core.joint import JointRecord, extract_manual_holes, hole_joint_uid
from core.project_io import migrate_project_dict, scene_to_dict, _block_from_dict
from core.version import FORMAT_VERSION
from models.panel import Block, Panel
from ui.panels.assoc_panel import AssocDock


def _make_block_two_panels() -> Block:
    """Две панели: вертикальная (source) и горизонтальная (target) рядом."""
    # Source: боковина, thickness along X
    source = Panel(
        name="Left",
        x=0,
        y=0,
        z=0,
        width=16,
        height=720,
        depth=560,
        uid="src-uid",
        rebuild=False,
    )
    # Target: полка, thickness along Y, примыкает к X+ грани source
    target = Panel(
        name="Shelf",
        x=16,
        y=300,
        z=0,
        width=568,
        height=16,
        depth=560,
        uid="tgt-uid",
        rebuild=False,
    )
    block = Block(name="Test", uid="blk-uid")
    block.add_panel(source)
    block.add_panel(target)
    return block


def test_panel_face_frame_center():
    p = Panel(name="P", x=10, y=20, z=30, width=100, height=200, depth=16, rebuild=False)
    origin, normal, u_ax, v_ax = panel_face_frame(p, "Z+")
    # Центр верхней грани Z+: z = 30+16, x=10+50, y=20+100
    assert abs(float(origin[0]) - 60.0) < 1e-6
    assert abs(float(origin[1]) - 120.0) < 1e-6
    assert abs(float(origin[2]) - 46.0) < 1e-6
    assert abs(float(normal[2]) - 1.0) < 1e-6


def test_face_hole_created_and_tagged():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    ref = AssocRef(
        kind="face_hole",
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
    )
    block.add_assoc_ref(ref, apply=True)

    assert len(target.holes) == 1
    h = target.holes[0]
    assert hole_assoc_uid(h) == ref.uid
    assert hole_joint_uid(h) == ""
    # radius = diameter/2
    assert abs(float(h[3]) - 4.0) < 1e-6
    assert abs(float(h[4]) - 12.0) < 1e-6
    assert extract_manual_holes(target) == []


def test_assoc_recalculates_when_source_moves():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 50.0, "v": -100.0, "diameter": 5.0, "depth": 10.0},
    )
    block.add_assoc_ref(ref, apply=True)
    h1 = target.holes[0]
    pos1 = (float(h1[0]), float(h1[1]), float(h1[2]))

    # Двигаем source по X — точка на X+ должна сдвинуться
    source.x = 40.0
    apply_assoc_refs(block)

    assert len(target.holes) == 1
    h2 = target.holes[0]
    pos2 = (float(h2[0]), float(h2[1]), float(h2[2]))
    # Локальная X target должна измениться (source уехал)
    assert abs(pos2[0] - pos1[0]) > 1.0


def test_manual_and_joint_holes_survive_assoc_apply():
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    manual = (100.0, 8.0, 200.0, 2.5, 12.0, "Y")
    target.holes.append(manual)

    jr = JointRecord(
        panel_a_uid=source.uid,
        panel_b_uid=target.uid,
        preset_id="confirmat_2",
    )
    block.add_joint(jr, apply=True)

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 6.0, "depth": 10.0},
    )
    block.add_assoc_ref(ref, apply=True)

    manuals = extract_manual_holes(target)
    assert any(abs(float(m[0]) - 100.0) < 1e-6 for m in manuals)
    assert any(hole_assoc_uid(h) == ref.uid for h in target.holes)
    assert any(hole_joint_uid(h) for h in target.holes)


def test_roundtrip_assoc_refs_in_project():
    block = _make_block_two_panels()
    target = block.get_panel_by_uid("tgt-uid")
    source = block.get_panel_by_uid("src-uid")
    assert target is not None and source is not None

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 10.0, "v": 20.0, "diameter": 7.0, "depth": 14.0},
    )
    block.add_assoc_ref(ref, apply=True)

    data = scene_to_dict([block], "assoc-test")
    assert data["version"] == FORMAT_VERSION
    assert data["blocks"][0]["assoc_refs"]
    restored = _block_from_dict(data["blocks"][0])
    assert len(getattr(restored, "assoc_refs", []) or []) == 1
    tgt2 = restored.get_panel_by_uid("tgt-uid")
    assert tgt2 is not None
    assert any(hole_assoc_uid(h) for h in tgt2.holes)


def test_migrate_adds_empty_assoc_refs():
    data = {
        "format": "NestCraft",
        "version": "0.0.8",
        "name": "old",
        "blocks": [{"type": "block", "name": "B", "panels": [], "joints": []}],
    }
    migrated, steps = migrate_project_dict(data)
    assert migrated["version"] == FORMAT_VERSION
    assert any("0.0.9" in s for s in steps)
    assert migrated["blocks"][0].get("assoc_refs") == []


def test_anchor_modes_pin_hole_to_corner_on_source_resize():
    """Якорь min_min / max_max удерживает отступ от угла грани при изменении размера source."""
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    # Грань X+ боковины [0..16, 0..720, 0..560]: u_axis = +Y, v_axis = +Z.
    # При anchor="min_min" точка (u=308, v=50) лежит на y=308, z=50 (ровно в полке y=[300..316]).
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        anchor="min_min",
        params={"u": 308.0, "v": 50.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
    )
    block.add_assoc_ref(ref, apply=True)
    pt_before = face_point_world(source, "X+", 308.0, 50.0, anchor="min_min")
    assert abs(float(pt_before[1]) - 308.0) < 1e-6
    assert abs(float(pt_before[2]) - 50.0) < 1e-6
    st1 = evaluate_assoc_ref(block, ref)
    assert st1.state == "ok" and st1.is_healthy

    # Увеличиваем высоту и глубину боковины: min_min угол (0, 0) не смещается -> отверстие стоит на месте!
    source.height = 900.0
    source.depth = 620.0
    apply_assoc_refs(block)
    h_after = target.holes[0]
    # В локали target (x=16, y=300, z=0): ly = 308-300 = 8, lz = 50
    assert abs(float(h_after[1]) - 8.0) < 1e-6
    assert abs(float(h_after[2]) - 50.0) < 1e-6


def test_face_hint_drift_detection_and_rebind():
    """Поворот source на 90° обнаруживается как face_drifted; rebind подбирает грань и лечит ссылку."""
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    # Позиционируем полку напротив центра грани X+ боковины (y=360)
    target.y = 352.0
    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        anchor="center",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
        face_hint=capture_face_hint(source, "X+"),
    )
    block.add_assoc_ref(ref, apply=True)
    assert evaluate_assoc_ref(block, ref).state == "ok"

    # Поворачиваем боковину на 90° вокруг Y — исходная грань X+ теперь смотрит вдоль -Z,
    # а вдоль исходной мировой нормали (+1, 0, 0) теперь смотрит грань Z+.
    source.ry = 90.0
    drifted = evaluate_assoc_ref(block, ref)
    assert drifted.state == "face_drifted"
    assert drifted.severity == "warning"
    assert drifted.code == "assoc_face_drifted"
    assert drifted.drift_angle_deg >= 89.0
    assert drifted.suggested_face == "Z+"
    assert suggest_rebind_face(target, source, ref) == "Z+"

    # Перепривязка восстанавливает нормаль и переводит статус в здоровый "ok"
    rebound_dict = rebind_assoc_ref_state(block, ref)
    assert rebound_dict is not None
    rebound = AssocRef.from_dict(rebound_dict)
    assert rebound.source_face == "Z+"
    block.assoc_refs = [rebound]
    apply_assoc_refs(block)
    healed = evaluate_assoc_ref(block, rebound)
    assert healed.state == "ok"
    assert healed.is_healthy


def test_out_of_source_face_and_out_of_target_diagnostics():
    """Диагностика выхода точки за границы грани source и за пределы объёма target."""
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None

    # Выход за грань source (высота 720 -> полуширина 360; u=500 выходит на 140 мм)
    ref_src = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 500.0, "v": 0.0, "diameter": 5.0, "depth": 10.0},
    )
    st_src = evaluate_assoc_ref(block, ref_src)
    assert st_src.state == "out_of_source_face"
    assert st_src.severity == "warning"
    assert st_src.code == "assoc_out_of_source_face"
    assert st_src.outside_mm > 100.0

    # Внутри грани source (u=0 -> y=360), но вне полки target (y=[300..316] -> 44 мм выше полки)
    ref_tgt = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 5.0, "depth": 10.0},
    )
    st_tgt = evaluate_assoc_ref(block, ref_tgt)
    assert st_tgt.state == "out_of_target"
    assert st_tgt.severity == "warning"
    assert st_tgt.code == "assoc_out_of_target"
    assert abs(st_tgt.outside_mm - 44.0) < 1e-3


def test_fixed_mode_survives_source_move_delete_roundtrip_and_unfreeze():
    """Заморозка fixed=True сохраняет отверстие при движении/удалении source, сериализуется в .b3d и снимается без скачка."""
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None
    target.y = 352.0  # центр полки на y=360, совпадает с центром грани X+ боковины

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        anchor="min_min",
        params={"u": 360.0, "v": 280.0, "diameter": 8.0, "depth": 12.0, "inset": 0.0},
        face_hint=capture_face_hint(source, "X+"),
    )
    block.add_assoc_ref(ref, apply=True)
    orig_hole = tuple(target.holes[0][:3])

    # Замораживаем (fixed=True)
    frozen_dict = freeze_assoc_ref_state(block, ref)
    assert frozen_dict is not None
    assert frozen_dict.get("fixed") is True
    frozen = AssocRef.from_dict(frozen_dict)
    block.assoc_refs = [frozen]
    apply_assoc_refs(block)

    st_fixed = evaluate_assoc_ref(block, frozen)
    assert st_fixed.state == "fixed"
    assert st_fixed.is_healthy
    assert resolve_assoc_world_point(block, frozen) is not None

    # Двигаем source — замороженное отверстие не шевелится
    source.x = 120.0
    apply_assoc_refs(block)
    assert tuple(target.holes[0][:3]) == orig_hole

    # Сериализация в .b3d сохраняет fixed, fixed_local, anchor, face_hint без смены FORMAT_VERSION
    data = scene_to_dict([block], "fixed-assoc-test")
    assert data["version"] == FORMAT_VERSION
    restored = _block_from_dict(data["blocks"][0])
    rest_ref = restored.assoc_refs[0]
    assert rest_ref.fixed is True
    assert rest_ref.anchor == "min_min"
    assert rest_ref.fixed_local is not None
    assert isinstance(rest_ref.face_hint, dict)

    # Возвращаем source на место и снимаем заморозку -> позиция отверстия не прыгает
    source.x = 0.0
    live_dict = unfreeze_assoc_ref_state(block, frozen)
    assert live_dict is not None
    live = AssocRef.from_dict(live_dict)
    assert live.fixed is False
    block.assoc_refs = [live]
    apply_assoc_refs(block)
    new_hole = tuple(target.holes[0][:3])
    for a, b in zip(orig_hole, new_hole):
        assert abs(a - b) < 1e-2

    # Удаляем source: для fixed-ссылки отверстие и статус остаются валидными!
    block.assoc_refs = [frozen]
    block.panels = [target]
    apply_assoc_refs(block)
    assert len(target.holes) == 1
    assert evaluate_assoc_ref(block, frozen).state == "fixed"


def test_assoc_dock_headless_status_and_recovery_actions():
    """Headless-тест AssocDock: счётчик проблем в заголовке, статусы, кнопки Зафиксировать и Подобрать грань."""
    block = _make_block_two_panels()
    source = block.get_panel_by_uid("src-uid")
    target = block.get_panel_by_uid("tgt-uid")
    assert source is not None and target is not None
    target.y = 352.0

    ref = AssocRef(
        target_uid=target.uid,
        source_uid=source.uid,
        source_face="X+",
        params={"u": 0.0, "v": 0.0, "diameter": 8.0, "depth": 12.0},
        face_hint=capture_face_hint(source, "X+"),
    )
    block.add_assoc_ref(ref, apply=True)

    # Поворачиваем source на 90°, чтобы ссылка перешла в warning (face_drifted)
    source.ry = 90.0

    dock = AssocDock()
    modifications: list[tuple] = []

    def _apply_mod(blk, uid, _old, new_state):
        modifications.append((uid, new_state))
        for i, raw in enumerate(blk.assoc_refs):
            cur = raw if isinstance(raw, AssocRef) else AssocRef.from_dict(raw)
            if cur.uid == uid:
                blk.assoc_refs[i] = AssocRef.from_dict(new_state)
                break
        apply_assoc_refs(blk)

    dock.assoc_modified.connect(_apply_mod)
    dock.load_assocs([block])

    assert "⚠ 1" in dock._title
    item0 = dock.list_widget.item(0)
    assert item0 is not None
    assert "⚠" in item0.text() and "сдвиг грани" in item0.text()
    assert "Z+" in dock.status_label.text()

    # 1. Нажимаем «Подобрать грань» -> assoc_modified перепривязывает на Z+, проблемы исчезают
    assert dock.rebind_selected_assoc() is True
    assert len(modifications) == 1
    assert modifications[-1][1]["source_face"] == "Z+"
    assert "⚠" not in dock._title

    # 2. Нажимаем «Зафиксировать» -> fixed=True и кнопка меняется на «Привязать»
    assert dock.toggle_fixed_selected_assoc() is True
    assert modifications[-1][1].get("fixed") is True
    assert "Привязать" in dock.btn_toggle_fixed.text()
    item_fixed = dock.list_widget.item(0)
    assert item_fixed is not None and "📌" in item_fixed.text()

    # 3. Нажимаем «Привязать» -> fixed снимается обратно
    assert dock.toggle_fixed_selected_assoc() is True
    assert not modifications[-1][1].get("fixed")
    assert "Зафиксировать" in dock.btn_toggle_fixed.text()

