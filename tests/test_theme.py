import pytest

pytest.importorskip("PyQt6")

from ui.theme import DARK, LIGHT, build_palette, build_stylesheet, theme_for_system

def test_palettes_differ():
    assert DARK.bg != LIGHT.bg
    assert "dark" in build_stylesheet(DARK)
    assert "light" in build_stylesheet(LIGHT)
    assert build_palette(DARK) is not None

def test_theme_for_system_returns_known():
    t = theme_for_system()
    assert t.name in ("dark", "light")
