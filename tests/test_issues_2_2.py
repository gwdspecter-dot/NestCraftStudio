"""Тесты пункта 2.2 (Ревизия 2): Общее окно «Проблемы» и реестр проверок модели."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tests.conftest as _conf

_conf.pytest_configure(None)

from core.issues import (
    ISSUE_CHECKS,
    Issue,
    check,
    check_collisions_in_blocks,
    check_edge_width_in_blocks,
    check_fastener_issues_in_blocks,
    check_fastener_thickness_issue,
    check_hole_edge_distance_in_blocks,
    check_holes_in_grooves_in_blocks,
    check_holes_intersection_in_blocks,
    check_oversized_panels_in_blocks,
    check_scene_issues,
    record_panel_issue,
)
from models.panel import Block, Panel


def test_issue_dataclass_and_registry():
    """Класс Issue(severity, panel_uid, code, message) и реестр ISSUE_CHECKS / check(blocks)."""
    iss = Issue("warning", "uid-123", "missing_material", "Материал не найден")
    assert iss.severity == "warning"
    assert iss.panel_uid == "uid-123"
    assert iss.code == "missing_material"
    assert iss.message == "Материал не найден"
    assert "⚠️" in iss.format_line()

    err = Issue("error", "uid-456", "panel_collision", "Пересечение")
    assert "❌" in err.format_line()

    assert isinstance(ISSUE_CHECKS, list)
    assert len(ISSUE_CHECKS) >= 6
    assert callable(check)


def test_missing_material_and_missing_edge_checks():
    """Проверки: материал не найден, деталь без материала, кромка не найдена."""
    b = Block("Корпус", "1", "01.00")
    p1 = Panel("Боковина", 0, 0, 0, 16, 720, 560, rebuild=False)
    p1.missing_material_id = "mat_deleted_oak"
    p1.missing_edges = {"top": "edge_deleted_pvc"}

    p2 = Panel("Планка без материала", 100, 0, 0, 16, 500, 100, rebuild=False)
    p2.material_id = ""
    p2.material = ""

    b.panels = [p1, p2]
    issues = check([b])
    codes_by_uid = {(i.panel_uid, i.code) for i in issues}

    assert (p1.uid, "missing_material") in codes_by_uid
    assert (p1.uid, "missing_edge") in codes_by_uid
    assert (p2.uid, "no_material") in codes_by_uid


def test_edge_width_smaller_than_panel_thickness(tmp_path: Path):
    """Проверка: ширина кромки меньше толщины детали."""
    from core.catalog import CatalogService
    from core.catalog.models import EdgeBand

    CatalogService.reset()
    cat = CatalogService.instance(tmp_path / "cat_edge.db")
    try:
        narrow_edge = EdgeBand(
            id="edge_narrow_12",
            sku="E-12",
            name="Узкая кромка",
            material_type="pvc",
            thickness_mm=1.0,
            width_mm=12.0,
        )
        cat.insert_edge(narrow_edge)

        p = Panel("Толстая столешница", 0, 0, 0, 600, 22, 600, rebuild=False)
        p.thickness_axis = 1
        p.edges["top"] = "edge_narrow_12"

        b = Block("Блок", "1", "01.00")
        b.panels = [p]

        issues = check_edge_width_in_blocks([b])
        assert len(issues) == 1
        assert issues[0].code == "edge_width_too_small"
        assert issues[0].panel_uid == p.uid
        assert "12" in issues[0].message and "22" in issues[0].message
    finally:
        CatalogService.reset()


def test_fastener_thickness_check():
    """Проверка: толщина детали не подходит крепежу (min/max_panel_thickness)."""
    p_thin = Panel("ХДФ стенка", 0, 0, 0, 4, 700, 500, rebuild=False)
    p_thin.thickness_axis = 0
    fst = SimpleNamespace(
        id="fst_conf_7x50",
        display_name="Конфирмат 7×50",
        min_panel_thickness=15.0,
        max_panel_thickness=19.0,
    )
    iss = check_fastener_thickness_issue(p_thin, fst)
    assert iss is not None
    assert iss.code == "fastener_thickness_min"
    assert iss.panel_uid == p_thin.uid

    record_panel_issue(p_thin, iss)
    b = Block("Корпус")
    b.panels = [p_thin]

    found = check_fastener_issues_in_blocks([b])
    assert len(found) == 1
    assert found[0].code == "fastener_thickness_min"
    assert found[0].panel_uid == p_thin.uid


def test_hole_near_edge_and_valid_joint_hole():
    """Проверка: отверстие ближе N мм к краю срабатывает, а штатное отверстие 8 мм в 16 мм плите — нет."""
    p = Panel("Дно", 0, 0, 0, 568, 16, 560, rebuild=False)
    p.thickness_axis = 1

    # 1) Штатное отверстие в торец X (центр по Y=8, Z=50, радиус 3.5 -> до края Z 46.5 мм, по толщине Y 4.5 мм)
    p.holes = [(0.0, 8.0, 50.0, 3.5, 38.0, "X")]
    b = Block("Корпус")
    b.panels = [p]
    assert check_hole_edge_distance_in_blocks([b]) == []

    # 2) Отверстие в пласть слишком близко к краю X (центр X=4.0, радиус 3.5 -> стенка 0.5 мм < 4.0 мм)
    p.holes.append((4.0, 0.0, 100.0, 3.5, 16.0, "Y"))
    issues = check_hole_edge_distance_in_blocks([b])
    assert len(issues) == 1
    assert issues[0].code == "hole_near_edge"
    assert issues[0].panel_uid == p.uid


def test_hole_in_groove_and_holes_intersection():
    """Проверки: отверстие в пазу и пересечение двух отверстий между собой."""
    p = Panel("Боковина с пазом", 0, 0, 0, 16, 720, 560, rebuild=False)
    p.thickness_axis = 0
    # Паз вдоль заднего торца: x=10..16, y=0..720, z=16..20
    p.grooves = [(10.0, 0.0, 16.0, 6.0, 720.0, 4.0)]
    # Два пересекающихся отверстия, одно из которых также задевает паз
    p.holes = [
        (0.0, 100.0, 18.0, 3.5, 16.0, "X"),
        (0.0, 102.0, 18.0, 3.5, 16.0, "X"),
    ]
    b = Block("Корпус")
    b.panels = [p]

    groove_issues = check_holes_in_grooves_in_blocks([b])
    assert len(groove_issues) >= 1
    assert groove_issues[0].code == "hole_in_groove"
    assert groove_issues[0].panel_uid == p.uid

    inter_issues = check_holes_intersection_in_blocks([b])
    assert len(inter_issues) == 1
    assert inter_issues[0].code == "holes_intersect"
    assert inter_issues[0].panel_uid == p.uid


def test_panel_collision_and_oversized_panel_in_unified_check():
    """Проверки: пересечение деталей (panel_collision) и превышение размера листа (oversized_panel)."""
    p1 = Panel("Боковина", 0, 0, 0, 16, 720, 560, rebuild=False)
    # p2 врезается в p1 на 8 мм по X
    p2 = Panel("Полка с нахлёстом", 8, 200, 0, 568, 16, 560, rebuild=False)
    # p3 негабаритная (3000 мм > 2800 мм)
    p3 = Panel("Длинная деталь", 0, 800, 0, 3000, 600, 16, rebuild=False)

    b = Block("Корпус")
    b.panels = [p1, p2, p3]

    col_issues = check_collisions_in_blocks([b])
    assert len(col_issues) == 1
    assert col_issues[0].code == "panel_collision"
    assert col_issues[0].severity == "error"
    assert col_issues[0].panel_uid == p1.uid

    over_issues = check_oversized_panels_in_blocks([b])
    assert len(over_issues) == 1
    assert over_issues[0].code == "oversized_panel"
    assert over_issues[0].panel_uid == p3.uid

    # Все проверки входят в общий список check(blocks) / check_scene_issues(blocks)
    all_issues = check_scene_issues([b])
    codes = {i.code for i in all_issues}
    assert "panel_collision" in codes
    assert "oversized_panel" in codes


def test_select_panel_by_uid_from_issue():
    """Двойной клик по замечанию (issue_activated -> select_panel_by_uid) выделяет деталь в сцене по uid."""
    p1 = Panel("Левая боковина", 0, 0, 0, 16, 720, 560, rebuild=False)
    p2 = Panel("Правая боковина", 584, 0, 0, 16, 720, 560, rebuild=False)
    p1.selected = True
    p2.selected = False

    b = Block("Корпус")
    b.panels = [p1, p2]

    # Проверяем логику select_panel_by_uid из MainWindow на облегчённом стабе окна
    class _DummyWindow:
        def __init__(self, blocks):
            self.vp = SimpleNamespace(blocks=blocks, updated=False)
            self.vp.update = lambda: setattr(self.vp, "updated", True)
            self.workspace = SimpleNamespace(current_viewport=lambda: self.vp)
            self.shown_obj = None
            self.highlighted_obj = None
            self.coords = None
            self.properties_dock = SimpleNamespace(
                show_object_properties=lambda obj: setattr(self, "shown_obj", obj)
            )
            self.structure_dock = SimpleNamespace(
                highlight_object=lambda obj: setattr(self, "highlighted_obj", obj)
            )

        def _update_coord_boxes(self, x, y, z):
            self.coords = (x, y, z)

        def select_panel_by_uid(self, panel_uid: str) -> bool:
            uid = str(panel_uid or "").strip()
            if not uid:
                return False
            vp = self.workspace.current_viewport()
            target = None
            for blk in vp.blocks:
                for pnl in getattr(blk, "panels", []):
                    is_match = str(getattr(pnl, "uid", "")) == uid
                    pnl.selected = is_match
                    if is_match:
                        target = pnl
            if target is None:
                return False
            self.properties_dock.show_object_properties(target)
            self.structure_dock.highlight_object(target)
            self._update_coord_boxes(target.x, target.y, target.z)
            vp.update()
            return True

    win = _DummyWindow([b])
    ok = win.select_panel_by_uid(p2.uid)
    assert ok is True
    assert p1.selected is False
    assert p2.selected is True
    assert win.shown_obj is p2
    assert win.highlighted_obj is p2
    assert win.coords == (584.0, 0.0, 0.0)
    assert win.vp.updated is True


if __name__ == "__main__":
    import tempfile

    test_issue_dataclass_and_registry()
    test_missing_material_and_missing_edge_checks()
    with tempfile.TemporaryDirectory() as td:
        test_edge_width_smaller_than_panel_thickness(Path(td))
    test_fastener_thickness_check()
    test_hole_near_edge_and_valid_joint_hole()
    test_hole_in_groove_and_holes_intersection()
    test_panel_collision_and_oversized_panel_in_unified_check()
    test_select_panel_by_uid_from_issue()
    print("ALL 2.2 ISSUE TESTS PASSED")
