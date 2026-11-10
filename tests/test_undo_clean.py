import conftest
conftest.pytest_configure(None)
from core.undo import UndoStack, Command, MovePanelCommand
from models.panel import Panel


class C(Command):
    def __init__(self, n, mergeable=False):
        super().__init__(n)
        self.mergeable = mergeable
        self.merged_names = [n]

    def undo(self):
        pass

    def redo(self):
        pass

    def can_merge_with(self, next_cmd: "Command") -> bool:
        return self.mergeable and isinstance(next_cmd, C) and next_cmd.mergeable

    def merge_with(self, next_cmd: "Command") -> None:
        if isinstance(next_cmd, C):
            self.merged_names.extend(next_cmd.merged_names)


def test_clean_point():
    s = UndoStack()
    s.mark_clean()
    assert s.is_clean()
    s.push(C("a"), execute=True)
    assert not s.is_clean()
    s.undo()
    assert s.is_clean()
    s.push(C("b"), execute=True)
    s.mark_clean()
    assert s.is_clean()
    s.clear()
    assert s.is_clean()


def test_merge_does_not_swallow_clean_point():
    stack = UndoStack()
    stack.push(C("move_before_save", mergeable=True), execute=True, merge=True)
    stack.mark_clean()
    assert stack.is_clean() is True

    # Сдвиг после сохранения с merge=True не должен сливаться в команду точки сохранения
    stack.push(C("move_after_save_1", mergeable=True), execute=True, merge=True)
    assert stack.is_clean() is False
    assert len(stack.history_labels()) == 2

    # Следующий сдвиг уже сливается со второй командой (после точки сохранения)
    stack.push(C("move_after_save_2", mergeable=True), execute=True, merge=True)
    assert stack.is_clean() is False
    assert len(stack.history_labels()) == 2

    # Один Ctrl+Z возвращает документ ровно в сохранённое состояние
    stack.undo()
    assert stack.is_clean() is True


def test_move_panel_command_merge_after_save():
    p = Panel("Боковина", 0, 0, 0, 16, 720, 560)
    stack = UndoStack()

    stack.push(MovePanelCommand(p, (0, 0, 0), (10, 0, 0)), execute=True, merge=True)
    stack.mark_clean()
    assert stack.is_clean() is True
    assert p.x == 10.0

    stack.push(MovePanelCommand(p, (10, 0, 0), (20, 0, 0)), execute=True, merge=True)
    assert stack.is_clean() is False
    assert p.x == 20.0

    stack.push(MovePanelCommand(p, (20, 0, 0), (25, 0, 0)), execute=True, merge=True)
    assert stack.is_clean() is False
    assert p.x == 25.0

    # Отмена возвращает к позиции на момент сохранения (x=10), а не к (x=0)
    stack.undo()
    assert stack.is_clean() is True
    assert p.x == 10.0


if __name__ == "__main__":
    test_clean_point()
    test_merge_does_not_swallow_clean_point()
    test_move_panel_command_merge_after_save()
    print("OK")

