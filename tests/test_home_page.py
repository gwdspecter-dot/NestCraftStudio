"""Тесты домашней страницы NestCraft Studio (ui/home_page.py и интеграция в MainWindow)."""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.project_io import (
    add_recent_file,
    build_recent_file_entries,
    clear_recent_files,
    remove_recent_file,
)

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "ui" / "icons"
HOME_PAGE_PY = ROOT / "ui" / "home_page.py"
MAIN_WINDOW_PY = ROOT / "ui" / "main_window.py"

EXPECTED_ICONS = (
    "home_new_model.svg",
    "home_open_model.svg",
    "home_new_fastener.svg",
    "home_new_module.svg",
    "home_recent_file.svg",
)

EXPECTED_LAUNCH_LABELS = [
    "Создать модель",
    "Открыть модель",
    "Создать фурнитуру",
    "Создать модуль",
]


def test_build_recent_file_entries_preserves_opening_order_and_deduplicates(tmp_path: Path):
    storage = tmp_path / "recent_files.json"
    dir_a = tmp_path / "kitchen"
    dir_b = tmp_path / "wardrobe"
    dir_a.mkdir()
    dir_b.mkdir()

    f1 = dir_a / "tumba.b3d"
    f2 = dir_b / "shkaf.b3d"
    f3 = dir_a / "penal.b3d"
    for f in (f1, f2, f3):
        f.write_text("{}", encoding="utf-8")

    add_recent_file(f1, storage_path=storage)
    add_recent_file(f2, storage_path=storage)
    add_recent_file(f3, storage_path=storage)
    # Повторное открытие f1 поднимает его на самый верх без дублей
    add_recent_file(f1, storage_path=storage)

    entries = build_recent_file_entries(storage_path=storage, only_existing=True)
    assert [e.name for e in entries] == ["tumba.b3d", "penal.b3d", "shkaf.b3d"]
    assert entries[0].directory == str(dir_a.resolve())
    assert entries[2].directory == str(dir_b.resolve())
    assert all(e.exists for e in entries)

    # Удалённый с диска файл скрывается при only_existing=True
    f2.unlink()
    entries_after_unlink = build_recent_file_entries(storage_path=storage, only_existing=True)
    assert [e.name for e in entries_after_unlink] == ["tumba.b3d", "penal.b3d"]

    # Явное удаление и очистка
    remove_recent_file(f3, storage_path=storage)
    entries_after_remove = build_recent_file_entries(storage_path=storage, only_existing=True)
    assert [e.name for e in entries_after_remove] == ["tumba.b3d"]

    clear_recent_files(storage_path=storage)
    assert build_recent_file_entries(storage_path=storage, only_existing=True) == []


def test_home_page_temporary_icons_exist_and_valid_svg():
    for name in EXPECTED_ICONS:
        svg_path = ICONS_DIR / name
        assert svg_path.is_file(), f"Отсутствует временная иконка {name}"
        raw = svg_path.read_text(encoding="utf-8")
        root = ET.fromstring(raw)
        assert root.tag.endswith("svg"), f"{name}: корневой тег должен быть <svg>"
        assert "currentColor" in raw, f"{name}: иконка должна поддерживать перекраску под тему"


def test_home_page_has_no_hardcoded_hex_or_rgb_colors():
    """AGENTS.md §10: все цвета берутся из ui.theme.current_theme(), без хардкода."""
    src = HOME_PAGE_PY.read_text(encoding="utf-8")
    hex_hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", src)
    rgb_hits = re.findall(r"\brgba?\s*\(", src)
    assert not hex_hits, f"В ui/home_page.py найдены жёстко заданные hex-цвета: {hex_hits}"
    assert not rgb_hits, f"В ui/home_page.py найдены жёстко заданные rgb()-цвета: {rgb_hits}"


def test_home_page_structure_and_main_window_wiring_ast():
    hp_src = HOME_PAGE_PY.read_text(encoding="utf-8")
    hp_tree = ast.parse(hp_src, filename="ui/home_page.py")

    # Проверяем порядок и тексты пунктов блока «Запуск»
    launch_const = None
    for node in hp_tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "HOME_LAUNCH_ACTIONS":
                launch_const = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "HOME_LAUNCH_ACTIONS":
                    launch_const = ast.literal_eval(node.value)

    assert launch_const is not None, "В ui/home_page.py должна быть константа HOME_LAUNCH_ACTIONS"
    assert [row[1] for row in launch_const] == EXPECTED_LAUNCH_LABELS
    assert [row[2] for row in launch_const] == list(EXPECTED_ICONS[:4])

    assert '"Запуск"' in hp_src
    assert '"Последние файлы"' in hp_src

    hp_cls = next(n for n in hp_tree.body if isinstance(n, ast.ClassDef) and n.name == "HomePage")
    hp_methods = {n.name for n in hp_cls.body if isinstance(n, ast.FunctionDef)}
    for req in ("refresh_theme", "refresh_recent_files", "set_recent_files", "recent_file_paths"):
        assert req in hp_methods, f"HomePage не содержит метод {req}"

    mw_src = MAIN_WINDOW_PY.read_text(encoding="utf-8")
    mw_tree = ast.parse(mw_src, filename="ui/main_window.py")
    mw_cls = next(n for n in mw_tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    mw_methods = {n.name for n in mw_cls.body if isinstance(n, ast.FunctionDef)}
    for req in (
        "refresh_theme",
        "is_home_page_visible",
        "show_home_page",
        "show_workspace",
        "_ensure_workspace_viewport",
        "_on_home_create_model",
        "_on_home_create_fastener",
        "_on_home_create_module",
        "_on_remove_recent_file",
    ):
        assert req in mw_methods, f"MainWindow не содержит метод {req}"


@pytest.mark.gui
def test_home_page_widget_actions_and_recent_files_gui(tmp_path: Path):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from ui.home_page import HomePage
    from ui.theme import DARK, LIGHT, apply_theme

    app = QApplication.instance() or QApplication([])

    apply_theme(app, LIGHT)
    page = HomePage()

    assert page.btn_create_model.text() == "Создать модель"
    assert page.btn_open_model.text() == "Открыть модель"
    assert page.btn_create_fastener.text() == "Создать фурнитуру"
    assert page.btn_create_module.text() == "Создать модуль"

    fired: list[str] = []
    page.create_model_requested.connect(lambda: fired.append("create_model"))
    page.open_model_requested.connect(lambda: fired.append("open_model"))
    page.create_fastener_requested.connect(lambda: fired.append("create_fastener"))
    page.create_module_requested.connect(lambda: fired.append("create_module"))

    page.btn_create_model.click()
    page.btn_open_model.click()
    page.btn_create_fastener.click()
    page.btn_create_module.click()
    assert fired == ["create_model", "open_model", "create_fastener", "create_module"]

    f1 = tmp_path / "first.b3d"
    f2 = tmp_path / "second.b3d"
    f1.write_text("{}", encoding="utf-8")
    f2.write_text("{}", encoding="utf-8")

    opened: list[str] = []
    page.recent_file_requested.connect(opened.append)
    page.set_recent_files([str(f2), str(f1)])
    assert page.recent_list.count() == 2
    assert page.recent_file_paths() == [str(f2.resolve()), str(f1.resolve())]

    page.recent_list.itemClicked.emit(page.recent_list.item(0))
    assert opened == [str(f2.resolve())]

    # Переключение темы не должно падать
    apply_theme(app, DARK)
    page.refresh_theme()
    apply_theme(app, LIGHT)
    page.refresh_theme()
