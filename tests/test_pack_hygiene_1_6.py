"""Гигиена архива поставки (ревизия 4 §1.6)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pack_script_excludes_caches():
    script = ROOT / "scripts" / "pack_src.sh"
    assert script.is_file(), "scripts/pack_src.sh отсутствует"
    text = script.read_text(encoding="utf-8")
    for token in (
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".ruff_cache",
        "*.log",
        "data/catalog/*.db",
    ):
        assert token in text, f"в pack_src.sh нет исключения {token!r}"


def test_gitignore_covers_bytecode_and_caches():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for token in ("__pycache__/", "*.pyc", ".pytest_cache/", ".ruff_cache/", "*.log"):
        assert token in gi, f"в .gitignore нет {token!r}"
