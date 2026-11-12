"""ParametricCabinet.rebuild сохраняет присадку/кромку/материал по role."""

import conftest
conftest.pytest_configure(None)
from models.panel import ParametricCabinet


def test_rebuild_preserves_user_holes_and_edges():
    cab = ParametricCabinet(
        "Корпус", width=600, height=720, depth=560, thickness=16,
        shelves_count=1, has_facade=False, rebuild_on_init=True,
    )
    left = next(p for p in cab.panels if getattr(p, "role", "") == "left" or "лев" in p.name.lower())
    left.holes = [(0, 100, 50, 3.5, 16, "X")]
    left.edges = {"top": "e_top", "bottom": "", "left": "", "right": ""}
    left.material = "Custom"
    _mid = getattr(left, "material_id", "")

    cab.width = 700
    cab.rebuild()

    left2 = next(
        (p for p in cab.panels if getattr(p, "role", "") == "left"),
        next((p for p in cab.panels if "лев" in p.name.lower()), None),
    )
    assert left2 is not None
    assert left2.holes == [(0, 100, 50, 3.5, 16, "X")]
    assert left2.edges.get("top") == "e_top"


def test_three_equidistant_holes_stretch_on_cabinet_resize():
    """Ревизия 2, п. 1.2: 3 равноудалённых отверстия вдоль изменившегося габарита остаются равноудалёнными."""
    cab = ParametricCabinet(
        "Корпус", width=600, height=720, depth=560, thickness=16,
        shelves_count=1, has_facade=False, rebuild_on_init=True,
    )
    bottom = next(p for p in cab.panels if getattr(p, "role", "") == "bottom")
    assert abs(bottom.width - 568.0) < 1e-6  # 600 - 2 * 16 = 568

    # Три равноудалённых отверстия по ширине (X): 50 / 284 / 518 при ширине дна 568
    # и одиночное отверстие у правого края (550, 8, 100), которое должно ехать с правым ребром
    bottom.holes = [
        (50.0, 8.0, 280.0, 3.5, 16.0, "Y"),
        (284.0, 8.0, 280.0, 3.5, 16.0, "Y"),
        (518.0, 8.0, 280.0, 3.5, 16.0, "Y"),
        (550.0, 8.0, 100.0, 4.0, 30.0, "X"),
    ]

    # Расширяем корпус с 600 до 800 -> ширина дна меняется с 568 до 768
    cab.width = 800
    cab.rebuild()

    bottom_after = next(p for p in cab.panels if getattr(p, "role", "") == "bottom")
    assert abs(bottom_after.width - 768.0) < 1e-6

    xs = [h[0] for h in bottom_after.holes[:3]]
    assert abs(xs[0] - 50.0) < 1e-6
    assert abs(xs[1] - 384.0) < 1e-6
    assert abs(xs[2] - 718.0) < 1e-6
    # Проверяем равноудалённость: шаг между 1-м и 2-м равен шагу между 2-м и 3-м
    assert abs((xs[1] - xs[0]) - (xs[2] - xs[1])) < 1e-6

    # Одиночное отверстие у правого края сохранило отступ 568 - 550 = 18 мм -> 768 - 18 = 750
    assert abs(bottom_after.holes[3][0] - 750.0) < 1e-6

    # При возврате ширины корпуса обратно к 600 координаты возвращаются к 50 / 284 / 518 и 550
    cab.width = 600
    cab.rebuild()
    xs_back = [h[0] for h in bottom_after.holes[:3]]
    assert abs(xs_back[0] - 50.0) < 1e-6
    assert abs(xs_back[1] - 284.0) < 1e-6
    assert abs(xs_back[2] - 518.0) < 1e-6
    assert abs(bottom_after.holes[3][0] - 550.0) < 1e-6


def test_undo_removed_shelf_restores_holes_edges_uid_and_name():
    """План §1.8: уменьшение числа полок и Undo возвращает полку со всеми её данными."""
    from core.undo import EditPropertyCommand, UndoStack

    cab = ParametricCabinet(
        "Корпус", width=600, height=720, depth=560, thickness=16,
        shelves_count=3, has_facade=True, rebuild_on_init=True,
    )
    shelf_1 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_1")
    shelf_2 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_2")

    orig_uid_1 = shelf_1.uid
    orig_uid_2 = shelf_2.uid
    shelf_1.name = "Полка средняя кастом"
    shelf_1.holes = [(10.0, 8.0, 50.0, 4.0, 24.0, "X"), (10.0, 8.0, 300.0, 4.0, 24.0, "X")]
    shelf_1.edges = {"top": "edge_pvc_20_mist", "bottom": "edge_pvc_04_mist", "left": "", "right": ""}
    shelf_1.color = (0.2, 0.5, 0.8)

    shelf_2.holes = [(50.0, 8.0, 120.0, 7.5, 12.5, "Y")]
    shelf_2.edges = {"top": "edge_pvc_20_mist", "bottom": "", "left": "edge_pvc_04_mist", "right": ""}

    stack = UndoStack()
    cmd = EditPropertyCommand(cab, "shelves_count", 3, 1)
    stack.push(cmd, execute=True)

    roles_after_redo = {getattr(p, "role", "") for p in cab.panels}
    assert "shelf_0" in roles_after_redo
    assert "shelf_1" not in roles_after_redo
    assert "shelf_2" not in roles_after_redo

    # Undo: полки shelf_1 и shelf_2 должны вернуться со своей присадкой, кромкой, именем и uid
    stack.undo()
    assert cab.shelves_count == 3

    restored_1 = next((p for p in cab.panels if getattr(p, "role", "") == "shelf_1"), None)
    restored_2 = next((p for p in cab.panels if getattr(p, "role", "") == "shelf_2"), None)
    assert restored_1 is not None
    assert restored_2 is not None

    assert restored_1.uid == orig_uid_1
    assert restored_1.name == "Полка средняя кастом"
    assert restored_1.holes == [(10.0, 8.0, 50.0, 4.0, 24.0, "X"), (10.0, 8.0, 300.0, 4.0, 24.0, "X")]
    assert restored_1.edges == {
        "top": "edge_pvc_20_mist",
        "bottom": "edge_pvc_04_mist",
        "left": "",
        "right": "",
    }
    assert restored_1.color == (0.2, 0.5, 0.8)

    assert restored_2.uid == orig_uid_2
    assert restored_2.holes == [(50.0, 8.0, 120.0, 7.5, 12.5, "Y")]
    assert restored_2.edges.get("top") == "edge_pvc_20_mist"
    assert restored_2.edges.get("left") == "edge_pvc_04_mist"

    # Повторный Redo -> Undo также не теряет данные
    stack.redo()
    assert all(getattr(p, "role", "") not in ("shelf_1", "shelf_2") for p in cab.panels)
    stack.undo()
    restored_1_again = next((p for p in cab.panels if getattr(p, "role", "") == "shelf_1"), None)
    assert restored_1_again is not None
    assert restored_1_again.holes == [(10.0, 8.0, 50.0, 4.0, 24.0, "X"), (10.0, 8.0, 300.0, 4.0, 24.0, "X")]


def test_undo_merged_shelf_reductions_restores_all_removed_shelves():
    """План §1.8: склейка шагов (merge=True) 3 -> 2 -> 1 сохраняет снимки обеих удалённых полок."""
    from core.undo import EditPropertyCommand, UndoStack

    cab = ParametricCabinet(
        "Корпус", width=600, height=720, depth=560, thickness=16,
        shelves_count=3, has_facade=False, rebuild_on_init=True,
    )
    s1 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_1")
    s2 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_2")
    s1.edges = {"top": "e1", "bottom": "", "left": "", "right": ""}
    s2.edges = {"top": "e2", "bottom": "", "left": "", "right": ""}

    stack = UndoStack()
    stack.push(EditPropertyCommand(cab, "shelves_count", 3, 2), execute=True, merge=True)
    stack.push(EditPropertyCommand(cab, "shelves_count", 2, 1), execute=True, merge=True)

    assert cab.shelves_count == 1
    stack.undo()
    assert cab.shelves_count == 3

    r1 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_1")
    r2 = next(p for p in cab.panels if getattr(p, "role", "") == "shelf_2")
    assert r1.edges["top"] == "e1"
    assert r2.edges["top"] == "e2"


def test_version_and_back_groove_without_modulo_hack(make_panel):
    """План §1.10: единый core.version и явный side в add_back_groove без x % 600."""
    from core.version import APP_VERSION, FORMAT_VERSION
    from core.project_io import FORMAT_VERSION as IO_FMT

    assert APP_VERSION == "0.0.21"
    assert FORMAT_VERSION == IO_FMT
    from core.project_io import version_cmp

    assert version_cmp(FORMAT_VERSION, "0.0.8") >= 0

    # Вертикальная панель на x=550 (раньше из-за 550 % 600 >= 300 паз прыгал на gx=0)
    p_vert = make_panel(x=550, y=0, z=0, width=16, height=720, depth=560)
    p_vert.add_back_groove(side="right")
    assert len(p_vert.grooves) == 1
    assert abs(p_vert.grooves[0][0] - 10.0) < 1e-6  # width(16) - depth(6) = 10

    p_vert.add_back_groove(side="left")
    assert abs(p_vert.grooves[0][0] - 0.0) < 1e-6


if __name__ == "__main__":
    from models.panel import Panel
    test_rebuild_preserves_user_holes_and_edges()
    test_three_equidistant_holes_stretch_on_cabinet_resize()
    test_undo_removed_shelf_restores_holes_edges_uid_and_name()
    test_undo_merged_shelf_reductions_restores_all_removed_shelves()
    test_version_and_back_groove_without_modulo_hack(
        lambda **kw: Panel("P", **{**dict(x=0, y=0, z=0, width=100, height=200, depth=16, rebuild=False), **kw})
    )
    print("OK")



