"""Тесты качества кода (ревизия 2, п. 2.3):
- отсутствие неиспользуемых импортов в core/, models/, ui/;
- наличие настроек ruff и mypy (для core/ и models/) в pyproject.toml;
- наличие .pre-commit-config.yaml;
- согласованность .github/workflows/tests.yml (п. 1.9 + 2.3).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PROD_DIRS = ("core", "models", "ui")


def _find_unused_imports_in_file(py_path: Path) -> list[str]:
    source = py_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_path))

    # Собираем все используемые имена и строковые аннотации
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Учитываем строковые type annotations (PEP 563 / forward refs)
            for token in node.value.replace("[", " ").replace("]", " ").replace(",", " ").replace("|", " ").split():
                used_names.add(token.split(".")[0])

    # Проверяем __all__
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                used_names.add(elt.value)

    unused: list[str] = []
    # Проверяем только модульные импорты верхнего уровня (кроме __init__.py re-exports)
    if py_path.name == "__init__.py":
        return unused

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name not in used_names:
                    unused.append(f"{py_path.relative_to(ROOT_DIR)}:{node.lineno} unused import '{bound_name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound_name = alias.asname or alias.name
                if bound_name not in used_names:
                    unused.append(f"{py_path.relative_to(ROOT_DIR)}:{node.lineno} unused import '{bound_name}'")

    return unused


def test_no_unused_top_level_imports_in_production_code():
    all_unused: list[str] = []
    for folder in PROD_DIRS:
        base = ROOT_DIR / folder
        for py_file in sorted(base.rglob("*.py")):
            all_unused.extend(_find_unused_imports_in_file(py_file))
    assert not all_unused, "Найдены неиспользуемые импорты:\n" + "\n".join(all_unused)


def test_pyproject_has_ruff_and_mypy_configs():
    pyproject = (ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in pyproject
    assert "[tool.ruff.lint]" in pyproject
    assert '"S110"' in pyproject
    assert '"BLE001"' in pyproject
    assert "[tool.mypy]" in pyproject
    assert '"core"' in pyproject and '"models"' in pyproject


def test_pre_commit_and_ci_configs_exist():
    pre_commit = ROOT_DIR / ".pre-commit-config.yaml"
    assert pre_commit.is_file(), "Отсутствует .pre-commit-config.yaml"
    pc_text = pre_commit.read_text(encoding="utf-8")
    assert "ruff" in pc_text
    assert "mypy" in pc_text

    ci_workflow = ROOT_DIR / ".github" / "workflows" / "tests.yml"
    assert ci_workflow.is_file(), "Отсутствует .github/workflows/tests.yml"
    ci_text = ci_workflow.read_text(encoding="utf-8")
    assert "requirements-dev.txt" in ci_text
    assert "QT_QPA_PLATFORM: offscreen" in ci_text
    assert "not slow and not gui" in ci_text


def test_no_dummy_build123d_references_in_production_code():
    """Ревизия 4 §1.2: в core/models/ui нет упоминаний тестового _Dummy."""
    offenders: list[str] = []
    for folder in ("core", "models", "ui"):
        base = ROOT_DIR / folder
        if not base.is_dir():
            continue
        for py_file in sorted(base.rglob("*.py")):
            text = py_file.read_text(encoding="utf-8")
            if "_Dummy" in text:
                rel = py_file.relative_to(ROOT_DIR).as_posix()
                for i, line in enumerate(text.splitlines(), 1):
                    if "_Dummy" in line:
                        offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "В продакшен-коде остались ссылки на _Dummy (ревизия 4 §1.2):\n"
        + "\n".join(offenders)
    )
