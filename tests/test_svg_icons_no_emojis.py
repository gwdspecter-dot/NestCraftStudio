"""Проверки отсутствия эмодзи/пиктограмм в рабочем коде и валидности тематических SVG-иконок."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS_DIR = os.path.join(ROOT_DIR, "ui", "icons")

# Эмодзи, символы-пиктограммы и псевдоиконки, запрещённые вместо векторных SVG в рабочем коде
_EMOJI_OR_PICTOGRAPH_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u25A0-\u25FF\u2B00-\u2BFF]"
)

# Наборы новых тематических SVG-иконок, которые должны поддерживать перекрашивание через currentColor
_THEMED_ICON_PREFIXES = (
    "action_",
    "status_",
    "section_",
    "struct_",
)
_THEMED_ICON_EXACT = {
    "view_iso.svg",
    "view_front.svg",
    "view_top.svg",
    "view_left.svg",
    "view_right.svg",
    "view_back.svg",
    "tool_grid.svg",
    "tool_magnet.svg",
}

_SVG_REF_RE = re.compile(r'["\']([a-z0-9_]+\.svg)["\']')


def _iter_python_files(rel_dirs: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for rel in rel_dirs:
        base = os.path.join(ROOT_DIR, rel)
        for dp, _, fns in os.walk(base):
            for fn in sorted(fns):
                if fn.endswith(".py"):
                    out.append(os.path.join(dp, fn))
    return out


def test_no_emojis_in_runtime_code() -> None:
    """В рабочих пакетах core/, models/, ui/ не должно оставаться смайлов и юникод-пиктограмм."""
    offenders: list[str] = []
    for path in _iter_python_files(("core", "models", "ui")):
        rel = os.path.relpath(path, ROOT_DIR)
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                found = _EMOJI_OR_PICTOGRAPH_RE.findall(line)
                if found:
                    offenders.append(f"{rel}:{lineno}: {found} -> {line.strip()[:100]}")
    assert not offenders, "Обнаружены эмодзи/пиктограммы в рабочем коде:\n" + "\n".join(offenders)


def _iter_svg_files() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for dp, _, fns in os.walk(ICONS_DIR):
        for fn in sorted(fns):
            if fn.endswith(".svg"):
                out.append((fn, os.path.join(dp, fn)))
    return out


def test_all_svg_icons_are_valid_xml_with_viewbox() -> None:
    """Все файлы *.svg в ui/icons/ (включая fasteners/) — корректный XML с <svg> и viewBox."""
    svg_files = _iter_svg_files()
    assert len(svg_files) >= 36, f"Ожидалось >= 36 SVG-иконок, найдено {len(svg_files)}"

    for fn, full in svg_files:
        tree = ET.parse(full)
        root = tree.getroot()
        assert root.tag.endswith("svg"), f"{fn}: корневой тег не <svg>, а {root.tag}"
        assert root.attrib.get("viewBox"), f"{fn}: отсутствует атрибут viewBox"

        if fn.startswith(_THEMED_ICON_PREFIXES) or fn in _THEMED_ICON_EXACT:
            with open(full, "r", encoding="utf-8") as fh:
                content = fh.read()
            assert "currentColor" in content, f"{fn}: тематическая иконка должна использовать currentColor"


def test_all_referenced_svg_icons_exist() -> None:
    """Каждое имя *.svg, на которое ссылается код в ui/, должно существовать в ui/icons/ (или fasteners/)."""
    existing = {fn for fn, _ in _iter_svg_files()}
    missing: list[str] = []
    for path in _iter_python_files(("ui",)):
        rel = os.path.relpath(path, ROOT_DIR)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for match in _SVG_REF_RE.finditer(src):
            svg_name = match.group(1)
            if svg_name not in existing:
                missing.append(f"{rel}: отсутствует ui/icons/{svg_name}")
    assert not missing, "Найдены ссылки на отсутствующие SVG-иконки:\n" + "\n".join(missing)


def test_core_and_models_do_not_import_ui() -> None:
    """Инвариант слоёв: core/ и models/ не импортируют ui/ (в том числе ui.icon_utils)."""
    import_re = re.compile(r"^\s*(?:from\s+ui(?:\.|\s)|import\s+ui(?:\.|\s|$))")
    violations: list[str] = []
    for path in _iter_python_files(("core", "models")):
        rel = os.path.relpath(path, ROOT_DIR)
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if import_re.match(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Нарушение архитектуры слоёв (импорт ui из core/models):\n" + "\n".join(violations)
