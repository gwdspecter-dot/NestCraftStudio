import re
import pytest

pytest.importorskip("PyQt6")

from ui.theme import DARK, LIGHT, build_palette, build_stylesheet, theme_for_system


def _hex_luma(color: str) -> float:
    """Относительная яркость (0..255) для hex-цвета формата #rrggbb."""
    h = color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def test_palettes_differ():
    assert DARK.bg != LIGHT.bg
    assert "dark" in build_stylesheet(DARK)
    assert "light" in build_stylesheet(LIGHT)
    assert build_palette(DARK) is not None


def test_dark_inputs_soft_contrast():
    """В тёмной теме инпуты чуть светлее панелей, без резкого контраста границ."""
    # Мягкий VS Code–стиль: bg_input >= bg_panel (не «яма»)
    assert _hex_luma(DARK.bg_input) >= _hex_luma(DARK.bg_panel) - 2.0
    assert _hex_luma(DARK.bg_input) > _hex_luma(DARK.bg)
    # border может совпадать с bg_input — рамка рисуется через input_border в QSS
    assert DARK.bg_input == "#3c3c3c"
    assert DARK.border == "#3c3c3c"


def test_stylesheet_separates_tab_pane_from_inputs():
    """Содержимое QTabWidget::pane должно отличаться от фона полей ввода в обеих темах."""
    for theme in (DARK, LIGHT):
        qss = build_stylesheet(theme)
        pane_match = re.search(r"QTabWidget::pane\s*\{([^}]+)\}", qss)
        assert pane_match is not None
        assert f"background: {theme.bg_panel};" in pane_match.group(1)

        input_match = re.search(
            r"QLineEdit,\s*QSpinBox,\s*QDoubleSpinBox[^{]*\{([^}]+)\}", qss
        )
        assert input_match is not None
        assert f"background-color: {theme.bg_input};" in input_match.group(1)
        assert "border: 1px solid" in input_match.group(1)

        assert "QLineEdit:focus" in qss
        assert theme.bg_input != theme.bg_panel


def test_theme_for_system_returns_known():
    t = theme_for_system()
    assert t.name in ("dark", "light")

