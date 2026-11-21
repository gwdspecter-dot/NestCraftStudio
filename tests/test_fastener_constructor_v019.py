"""Тесты сквозной связки конструктора крепежа (D1, D2, H) с JointRecord и сверлением (v0.0.19)."""

from __future__ import annotations

from core.fastener_constructor import (
    ConfirmatParams,
    load_confirmat_rows,
    reset_confirmat_rows,
    save_confirmat_rows,
)
from core.joint import JointRecord, apply_joints, find_joint, make_joint_holes
from models.panel import Block, Panel


def test_confirmat_params_edge_depth_and_selected_dict():
    p_std = ConfirmatParams("Конфирмат 7×50 мм, Zn", d1=8.0, d2=5.0, h=50.0, h1=0.0)
    assert abs(p_std.edge_depth(16.0) - 38.0) < 1e-6
    sel = p_std.to_selected_fastener_dict()
    assert sel["drill_face_diameter"] == 8.0
    assert sel["drill_edge_diameter"] == 5.0
    assert sel["drill_edge_depth"] == 38.0

    # Явно заданная глубина H1 переопределяет формулу от H
    p_custom = ConfirmatParams("Конфирмат 6.4×60", d1=7.5, d2=4.5, h=60.0, h1=44.0)
    assert abs(p_custom.edge_depth(16.0) - 44.0) < 1e-6
    sel2 = p_custom.to_selected_fastener_dict()
    assert sel2["drill_face_diameter"] == 7.5
    assert sel2["drill_edge_diameter"] == 4.5
    assert sel2["drill_edge_depth"] == 44.0


def test_confirmat_rows_persistence_roundtrip(tmp_path):
    store = tmp_path / "fastener_rows.json"
    rows = [
        ConfirmatParams("Конфирмат 7×50 мм, Zn", 8.0, 5.0, 50.0, 0.0),
        ConfirmatParams("Евровинт усиленный 7×70", 8.5, 5.5, 70.0, 52.0),
    ]
    save_confirmat_rows(rows, selected_index=1, custom_path=store)
    loaded, sel_idx = load_confirmat_rows(custom_path=store)
    assert sel_idx == 1
    assert len(loaded) == 2
    assert loaded[1].name == "Евровинт усиленный 7×70"
    assert abs(loaded[1].d1 - 8.5) < 1e-6
    assert abs(loaded[1].d2 - 5.5) < 1e-6
    assert abs(loaded[1].h - 70.0) < 1e-6
    assert abs(loaded[1].h1 - 52.0) < 1e-6

    reset_confirmat_rows(custom_path=store)
    assert not store.exists()


def test_make_joint_holes_honors_custom_d1_d2_and_edge_depth():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    j = find_joint(left, shelf)
    assert j is not None

    # Даже при переданном каталожном fastener_id="fst_conf_7x50" кастомные D1/D2/H имеют приоритет
    ha, hb = make_joint_holes(
        j,
        [16.0, 308.0, 280.0],
        diameter=8.4,
        depth=46.0,
        fastener_id="fst_conf_7x50",
        face_diameter=8.4,
        edge_diameter=4.8,
        edge_depth=46.0,
    )
    # left — сверление в пласть (сквозное на толщину 16 мм, радиус = 8.4 / 2 = 4.2)
    assert abs(ha[3] - 4.2) < 1e-6
    assert abs(ha[4] - 16.0) < 1e-6
    # shelf — сверление в торец (радиус = 4.8 / 2 = 2.4, глубина = 46.0)
    assert abs(hb[3] - 2.4) < 1e-6
    assert abs(hb[4] - 46.0) < 1e-6


def test_apply_joints_preserves_custom_constructor_params_across_serialization():
    left = Panel("L", 0, 0, 0, 16, 720, 560, rebuild=False)
    shelf = Panel("S", 16, 300, 0, 568, 16, 560, rebuild=False)
    left.uid = "u-left"
    shelf.uid = "u-shelf"

    chosen = ConfirmatParams("Кастом 9×60", d1=9.0, d2=5.6, h=60.0, h1=45.0).to_selected_fastener_dict()
    rec = JointRecord(
        uid="jr-custom",
        panel_a_uid="u-left",
        panel_b_uid="u-shelf",
        preset_id="confirmat_3",
        fastener_id="fst_conf_7x50",
        params={
            "count": 3,
            "margin": 50.0,
            "d1": chosen["d1"],
            "d2": chosen["d2"],
            "h": chosen["h"],
            "h1": chosen["h1"],
            "drill_face_diameter": chosen["drill_face_diameter"],
            "drill_edge_diameter": chosen["drill_edge_diameter"],
            "drill_edge_depth": chosen["drill_edge_depth"],
        },
    )
    # Проверка round-trip сериализации JointRecord
    rec_restored = JointRecord.from_dict(rec.to_dict())

    b = Block("Cab")
    b.add_panel(left)
    b.add_panel(shelf)
    b.joints = [rec_restored]
    apply_joints(b, rebuild_geometry=False)

    assert len(left.holes) == 3
    assert len(shelf.holes) == 3
    for h_face in left.holes:
        assert abs(h_face[3] - 4.5) < 1e-6  # D1=9.0 -> radius=4.5
        assert abs(h_face[4] - 16.0) < 1e-6
    for h_edge in shelf.holes:
        assert abs(h_edge[3] - 2.8) < 1e-6  # D2=5.6 -> radius=2.8
        assert abs(h_edge[4] - 45.0) < 1e-6  # H1=45.0


def test_fastener_formulas_recalc_and_thickness_dependency():
    from core.fastener_constructor import (
        apply_fastener_cell_input,
        recalculate_confirmat_row,
    )

    row = ConfirmatParams("Конфирмат формульный", d1=8.0, d2=5.0, h=50.0, h1=0.0)

    ok, err = apply_fastener_cell_input(row, "d2", "=D1 - 3")
    assert ok and not err
    assert abs(row.d2 - 5.0) < 1e-6
    assert row.formula_for("d2") == "D1 - 3"

    ok, err = apply_fastener_cell_input(row, "h1", "H - t + 4", panel_thickness=16.0)
    assert ok and not err
    assert abs(row.h1 - 38.0) < 1e-6
    assert row.formula_for("h1") == "H - t + 4"

    # Меняем D1 и H — зависимые D2 и H1 пересчитываются автоматически
    ok, err = apply_fastener_cell_input(row, "d1", "9,0")
    assert ok and not err
    assert abs(row.d1 - 9.0) < 1e-6
    assert abs(row.d2 - 6.0) < 1e-6

    ok, err = apply_fastener_cell_input(row, "h", "+= 20", panel_thickness=16.0)
    assert ok and not err
    assert abs(row.h - 70.0) < 1e-6
    assert not row.has_formula("h")  # += одноразовое приращение
    assert abs(row.h1 - 58.0) < 1e-6

    # Динамический расчёт edge_depth и selected_dict для плиты 18 мм (t=18)
    assert abs(row.edge_depth(18.0) - 56.0) < 1e-6
    sel18 = row.to_selected_fastener_dict(panel_thickness=18.0)
    assert abs(sel18["drill_edge_depth"] - 56.0) < 1e-6
    assert sel18["formulas"]["h1"] == "H - t + 4"

    # Пересчёт на плите 22 мм
    errs = recalculate_confirmat_row(row, panel_thickness=22.0)
    assert not errs
    assert abs(row.h1 - 52.0) < 1e-6

    # Ввод обычного числа снимает формулу с поля
    ok, err = apply_fastener_cell_input(row, "h1", "44")
    assert ok and not err
    assert not row.has_formula("h1")
    assert abs(row.h1 - 44.0) < 1e-6


def test_fastener_formula_cycle_and_error_rollback():
    from core.fastener_constructor import apply_fastener_cell_input, detect_formula_cycle

    row = ConfirmatParams("Тест циклов", d1=8.0, d2=5.0, h=50.0, h1=38.0)
    assert apply_fastener_cell_input(row, "d2", "=D1 - 3")[0]

    # Прямой цикл D1 -> D2 -> D1 должен отклоняться с откатом
    ok, err = apply_fastener_cell_input(row, "d1", "=D2 + 3")
    assert not ok
    assert "Цикл" in err
    assert abs(row.d1 - 8.0) < 1e-6
    assert not row.has_formula("d1")

    # Самоссылка H1 = H1 + 2 должна отклоняться
    ok2, err2 = apply_fastener_cell_input(row, "h1", "=H1 + 2")
    assert not ok2
    assert "Цикл" in err2
    assert abs(row.h1 - 38.0) < 1e-6

    # Деление на ноль и выход за границы не портят строку
    ok3, _ = apply_fastener_cell_input(row, "h", "=50 / 0")
    assert not ok3
    assert abs(row.h - 50.0) < 1e-6

    ok4, _ = apply_fastener_cell_input(row, "d1", "-5")
    assert not ok4
    assert abs(row.d1 - 8.0) < 1e-6

    cyc = detect_formula_cycle({"d1": "d2 + 1", "d2": "d1 - 1"})
    assert cyc is not None and len(cyc) >= 3


def test_fastener_dirty_status_star_and_persistence_with_formulas():
    import tempfile
    from pathlib import Path

    from core.fastener_constructor import (
        apply_fastener_cell_input,
        compute_rows_dirty_state,
        format_constructor_title,
        format_row_number_label,
        validate_confirmat_row,
    )

    saved = [
        ConfirmatParams("Базовый", 8.0, 5.0, 50.0, 38.0, formulas={"h1": "H - t + 4"}),
    ]
    current = [r.clone() for r in saved]

    # Неизменённый список — чистый, даже при смене толщины плиты t в предпросмотре
    is_dirty, dirty_rows = compute_rows_dirty_state(current, saved, panel_thickness=16.0)
    assert not is_dirty and not dirty_rows
    assert format_constructor_title("Конструктор", is_dirty) == "Конструктор"
    assert format_row_number_label(0, False) == "1"

    is_dirty18, dirty_rows18 = compute_rows_dirty_state(current, saved, panel_thickness=18.0)
    assert not is_dirty18 and not dirty_rows18

    # Меняем H — появляется статус * у заголовка и строки 0
    assert apply_fastener_cell_input(current[0], "h", "70", panel_thickness=16.0)[0]
    is_dirty, dirty_rows = compute_rows_dirty_state(current, saved, panel_thickness=16.0)
    assert is_dirty and dirty_rows == {0}
    assert format_constructor_title("Конструктор", is_dirty) == "Конструктор *"
    assert format_row_number_label(0, True) == "1*"

    # Откатываем H обратно к 50 — статус * пропадает
    assert apply_fastener_cell_input(current[0], "h", "50", panel_thickness=16.0)[0]
    is_dirty, dirty_rows = compute_rows_dirty_state(current, saved, panel_thickness=16.0)
    assert not is_dirty and not dirty_rows

    # Проверка инженерных предупреждений
    warn_row = ConfirmatParams("Странный", d1=5.0, d2=8.0, h=40.0, h1=55.0)
    warns = validate_confirmat_row(warn_row)
    assert len(warns) == 2

    # Round-trip сохранения и загрузки с формулами
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "fastener_formulas.json"
        assert apply_fastener_cell_input(current[0], "d2", "=D1 - 3")[0]
        save_confirmat_rows(current, selected_index=0, custom_path=store)
        loaded, sel = load_confirmat_rows(custom_path=store)
        assert sel == 0
        assert loaded[0].formula_for("h1") == "H - t + 4"
        assert loaded[0].formula_for("d2") == "D1 - 3"
        assert abs(loaded[0].h1 - 38.0) < 1e-6


def test_fastener_constructor_dialog_ast_wiring():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    src = (root / "ui" / "fastener_constructor_dialog.py").read_text(encoding="utf-8")
    tree = ast.parse(src, filename="ui/fastener_constructor_dialog.py")
    cls_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    fn_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    assert "_FormulaCellDelegate" in cls_names
    for fn in (
        "_apply_row_cells",
        "_refresh_dirty_state",
        "_sync_formula_bar",
        "_apply_formula_bar",
        "_on_thickness_changed",
        "_save_rows",
        "_apply_theme",
        "refresh_theme",
        "showEvent",
        "changeEvent",
    ):
        assert fn in fn_names, f"Missing {fn} in FastenerConstructorDialog"

    # Убеждаемся, что при редактировании ячеек нет преждевременного _persist_rows
    assert "_persist_rows" not in fn_names
    assert "format_constructor_title" in src
    assert "format_row_number_label" in src
    assert "apply_fastener_cell_input" in src
    # Обычные числовые ячейки не запекают жёсткий цвет текста (унаследуют цвет текущей темы)
    assert "ForegroundRole, None" in src
    # Светлая тема перекрашивает контуры и подпись H1 (#FDE68A -> #b45309) на SVG-схемах
    assert '"#FDE68A": "#b45309"' in src
    assert '"#E2F1FF": "#1e293b"' in src


