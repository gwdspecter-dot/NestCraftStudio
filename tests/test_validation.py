import conftest

conftest.pytest_configure(None)

import unittest

from core.undo import EditPropertyCommand, UndoStack
from core.validation import ValidationError, validate_cabinet_params
from models.panel import ParametricCabinet


def test_ok_cabinet():
    assert validate_cabinet_params(600, 720, 560, 16, 1) == []


def test_too_narrow():
    errs = validate_cabinet_params(30, 720, 560, 16, 0)
    assert any("Ширина" in e for e in errs)


def test_too_shallow():
    errs = validate_cabinet_params(600, 720, 100, 16, 0)
    assert any("Глубина" in e for e in errs)


def test_edit_property_command_rejects_narrow_cabinet_width():
    """Ревизия 2, п. 1.3: EditPropertyCommand(cab, 'width', 600, 30) выбрасывает ValidationError и не портит корпус."""
    cab = ParametricCabinet("Тумба", 0, 0, 0, 600, 720, 560, 16, shelves_count=1)
    stack = UndoStack()
    stack.mark_clean()

    cmd = EditPropertyCommand(cab, "width", 600.0, 30.0)
    try:
        stack.push(cmd, execute=True)
    except ValidationError as exc:
        assert "Ширина" in str(exc)
        assert exc.errors
    else:
        raise AssertionError("Expected ValidationError for width=30")

    assert cab.width == 600.0
    assert stack.is_clean() is True
    assert not stack.can_undo()
    for p in cab.panels:
        assert p.width > 0 and p.height > 0 and p.depth > 0, (
            f"Panel {p.role or p.name} got non-positive dimension"
        )


def test_edit_property_command_rejects_excessive_shelves_for_height():
    """Ревизия 2, п. 1.3: проверка несовместимого числа полок и высоты в EditPropertyCommand."""
    cab = ParametricCabinet("Тумба", 0, 0, 0, 600, 200, 560, 16, shelves_count=1)
    cmd = EditPropertyCommand(cab, "shelves_count", 1, 10)
    try:
        cmd.redo()
    except ValidationError as exc:
        assert "полок" in str(exc)
    else:
        raise AssertionError("Expected ValidationError for too many shelves")

    assert cab.shelves_count == 1


class _ValidationTests(unittest.TestCase):
    def test_all(self):
        test_ok_cabinet()
        test_too_narrow()
        test_too_shallow()
        test_edit_property_command_rejects_narrow_cabinet_width()
        test_edit_property_command_rejects_excessive_shelves_for_height()


if __name__ == "__main__":
    unittest.main()

