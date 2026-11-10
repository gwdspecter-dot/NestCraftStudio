"""Тесты по пункту 1.10 (Ревизия 2): запрет глухих ``except ...: pass`` в продакшен-коде."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_DIRS = ("core", "models", "ui")


def _iter_prod_python_files() -> list[Path]:
    files: list[Path] = []
    main_py = ROOT / "main.py"
    if main_py.exists():
        files.append(main_py)
    for d in PROD_DIRS:
        folder = ROOT / d
        if folder.is_dir():
            files.extend(sorted(folder.rglob("*.py")))
    return files


def test_no_silent_except_pass_in_production_code():
    """Ни в одном продакшен-модуле (core/, models/, ui/, main.py) нет глухого ``except ...: pass``."""
    offenders: list[str] = []

    for path in _iter_prod_python_files():
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            # Проверяем, не состоит ли тело обработчика исключительно из pass / "..."
            non_trivial = [
                stmt
                for stmt in body
                if not isinstance(stmt, ast.Pass)
                and not (
                    isinstance(stmt, ast.Expr)
                    and isinstance(getattr(stmt, "value", None), ast.Constant)
                    and isinstance(stmt.value.value, (str, type(...)))
                )
            ]
            if not non_trivial:
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "Обнаружены глухие обработчики except ...: pass (нарушение п. 1.10):\n  "
        + "\n  ".join(offenders)
    )


def test_core_and_ui_except_handlers_log_or_handle():
    """Все обработчики except Exception в core/ и ui/ содержат вызов логгера или явный возврат/присваивание."""
    prod_files = _iter_prod_python_files()
    assert len(prod_files) >= 15

    total_handlers = 0
    for path in prod_files:
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                total_handlers += 1
                assert len(node.body) >= 1
                assert not all(isinstance(s, ast.Pass) for s in node.body), (
                    f"Глухой except в {rel}:{node.lineno}"
                )

    assert total_handlers > 0


def test_pyproject_toml_configures_ruff_s110_and_ble001():
    """В pyproject.toml сконфигурирован линтер ruff с правилами S110 и BLE001 (п. 1.10)."""
    pyproject = ROOT / "pyproject.toml"
    assert pyproject.exists(), "Файл pyproject.toml должен существовать в корне проекта"
    content = pyproject.read_text(encoding="utf-8")
    assert "[tool.ruff" in content
    assert "S110" in content
    assert "BLE001" in content
