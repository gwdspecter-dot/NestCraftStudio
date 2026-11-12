"""Простой стек отмены/повтора для операций над сценой."""

from __future__ import annotations

import copy
from typing import Callable

from core.logging_setup import get_logger

_log = get_logger("undo")


def _reapply_panel_block_joints(panel) -> None:
    """Пересчитывает зависимые features блока после сдвига/resize панели.

    - при наличии joints вызывает apply_joints (он же тянет assoc_refs);
    - иначе, если есть только assoc_refs — apply_assoc_refs.
    """
    block = getattr(panel, "_block", None)
    if block is None:
        return
    has_joints = bool(getattr(block, "joints", None))
    has_assoc = bool(getattr(block, "assoc_refs", None))
    if has_joints:
        from core.joint import apply_joints

        apply_joints(block)
        return
    if has_assoc:
        from core.assoc import apply_assoc_refs

        apply_assoc_refs(block)


class Command:
    """Одна обратимая операция."""

    def __init__(self, description: str):
        self.description = description

    def undo(self) -> None:
        raise NotImplementedError

    def redo(self) -> None:
        raise NotImplementedError

    def can_merge_with(self, next_cmd: "Command") -> bool:
        return False

    def merge_with(self, next_cmd: "Command") -> None:
        pass


class UndoStack:
    """Стек undo/redo с ограничением глубины и поддержкой объединения шагов.

    «Чистая точка» (_clean): вершина стека на момент последнего Save / Open / New.
    is_clean() == True → документ совпадает с сохранённым состоянием.
    """

    def __init__(self, limit: int = 50):
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._limit = limit
        self._on_changed: Callable[[], None] | None = None
        # None = пустой стек как clean; иначе id() верхней команды на момент clean
        self._clean_top: object | None = None

    def set_on_changed(self, callback: Callable[[], None] | None) -> None:
        self._on_changed = callback

    def _notify(self) -> None:
        if self._on_changed:
            self._on_changed()

    def mark_clean(self) -> None:
        """Запомнить текущую вершину undo как «сохранено»."""
        self._clean_top = self._undo[-1] if self._undo else None

    def is_clean(self) -> bool:
        top = self._undo[-1] if self._undo else None
        return top is self._clean_top

    def push(self, command: Command, execute: bool = True, merge: bool = False) -> None:
        if execute:
            command.redo()
        top = self._undo[-1] if self._undo else None
        if (
            merge
            and top is not None
            and top is not self._clean_top
            and top.can_merge_with(command)
        ):
            top.merge_with(command)
        else:
            self._undo.append(command)
            if len(self._undo) > self._limit:
                self._undo.pop(0)
        self._redo.clear()
        self._notify()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        self._notify()
        return cmd.description

    def redo(self) -> str | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.redo()
        self._undo.append(cmd)
        self._notify()
        return cmd.description

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._clean_top = None  # пустой стек = clean
        self._notify()

    def history_labels(self) -> list[str]:
        """Список описаний для UI (от старых к новым)."""
        return [c.description for c in self._undo]


class AddPanelCommand(Command):
    def __init__(self, blocks: list, block, panel, description: str | None = None):
        super().__init__(description or f"Добавление: {panel.name}")
        self.blocks = blocks
        self.block = block
        self.panel = panel
        self._block_was_missing = False

    def redo(self) -> None:
        if self.block not in self.blocks:
            self.blocks.append(self.block)
            self._block_was_missing = True
        self.panel._block = self.block
        if self.panel not in self.block.panels:
            self.block.panels.append(self.panel)
        if getattr(self.block, "joints", None):
            from core.joint import apply_joints

            apply_joints(self.block)

    def undo(self) -> None:
        if self.panel in self.block.panels:
            self.block.panels.remove(self.panel)
        if getattr(self.block, "joints", None):
            from core.joint import apply_joints

            apply_joints(self.block)
        if self._block_was_missing and self.block in self.blocks and not self.block.panels:
            self.blocks.remove(self.block)


class DeleteItemsCommand(Command):
    """Удаление выделенных блоков и панелей с возможностью вернуть."""

    def __init__(self, blocks: list, description: str = "Удаление"):
        super().__init__(description)
        self.blocks = blocks
        # (index_in_blocks, block) for removed whole blocks
        self.removed_blocks: list[tuple[int, object]] = []
        # (block, index_in_panels, panel)
        self.removed_panels: list[tuple[object, int, object]] = []
        # (block, index_in_joints, joint_record)
        self.removed_joints: list[tuple[object, int, object]] = []

    def capture(self) -> bool:
        """Снять снимок того, что удалится. True если есть что удалять."""
        self.removed_blocks.clear()
        self.removed_panels.clear()
        self.removed_joints.clear()
        for i, b in enumerate(self.blocks):
            if b.selected:
                self.removed_blocks.append((i, b))
            else:
                removed_uids: set[str] = set()
                for j, p in enumerate(b.panels):
                    if p.selected:
                        self.removed_panels.append((b, j, p))
                        uid = str(getattr(p, "uid", "") or "")
                        if uid:
                            removed_uids.add(uid)
                if removed_uids and getattr(b, "joints", None):
                    for k, jr in enumerate(b.joints):
                        if (
                            str(getattr(jr, "panel_a_uid", "")) in removed_uids
                            or str(getattr(jr, "panel_b_uid", "")) in removed_uids
                        ):
                            self.removed_joints.append((b, k, jr))
        return bool(self.removed_blocks or self.removed_panels)

    def redo(self) -> None:
        affected_blocks: list = []
        for b, _k, jr in reversed(self.removed_joints):
            if jr in getattr(b, "joints", []):
                b.joints.remove(jr)
            if b not in affected_blocks:
                affected_blocks.append(b)
        for b, _j, p in reversed(self.removed_panels):
            if p in b.panels:
                b.panels.remove(p)
            if b not in affected_blocks:
                affected_blocks.append(b)
        for _i, b in reversed(self.removed_blocks):
            if b in self.blocks:
                self.blocks.remove(b)
        from core.joint import apply_joints

        for b in affected_blocks:
            if b in self.blocks:
                apply_joints(b)

    def undo(self) -> None:
        for i, b in sorted(self.removed_blocks, key=lambda t: t[0]):
            if b not in self.blocks:
                self.blocks.insert(min(i, len(self.blocks)), b)
        affected_blocks: list = []
        # restore panels in original order by index
        for b, j, p in sorted(self.removed_panels, key=lambda t: t[1]):
            p._block = b
            if p not in b.panels:
                b.panels.insert(min(j, len(b.panels)), p)
            if b not in affected_blocks:
                affected_blocks.append(b)
        for b, k, jr in sorted(self.removed_joints, key=lambda t: t[1]):
            if not hasattr(b, "joints"):
                b.joints = []
            if jr not in b.joints:
                b.joints.insert(min(k, len(b.joints)), jr)
            if b not in affected_blocks:
                affected_blocks.append(b)
        from core.joint import apply_joints

        for b in affected_blocks:
            if getattr(b, "joints", None):
                apply_joints(b)


class MovePanelCommand(Command):
    def __init__(self, panel, old_xyz: tuple[float, float, float], new_xyz: tuple[float, float, float]):
        super().__init__(f"Сдвиг: {panel.name}")
        self.panel = panel
        self.old_xyz = old_xyz
        self.new_xyz = new_xyz

    def can_merge_with(self, next_cmd: Command) -> bool:
        return isinstance(next_cmd, MovePanelCommand) and next_cmd.panel is self.panel

    def merge_with(self, next_cmd: Command) -> None:
        if isinstance(next_cmd, MovePanelCommand):
            self.new_xyz = next_cmd.new_xyz

    @staticmethod
    def _shift_mesh(panel, dx: float, dy: float, dz: float) -> None:
        """Сдвигает вершины текущего mesh в мировых координатах (заливка = контур)."""
        if abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(dz) < 1e-12:
            return
        md = getattr(panel, "mesh_data", None)
        if not md or len(md) < 2:
            return
        try:
            import numpy as np
            verts = np.asarray(md[0], dtype=float)
            if verts.size == 0:
                return
            verts = verts.copy()
            verts[:, 0] += float(dx)
            verts[:, 1] += float(dy)
            verts[:, 2] += float(dz)
            if len(md) >= 3 and md[2] is not None:
                panel.mesh_data = (verts, md[1], md[2])
            else:
                panel.mesh_data = (verts, md[1])
            panel._gl_arrays = None
        except Exception:
            _log.exception("MovePanelCommand._shift_mesh failed")

    def redo(self) -> None:
        ox = float(self.panel.x)
        oy = float(self.panel.y)
        oz = float(self.panel.z)
        nx, ny, nz = (float(self.new_xyz[0]), float(self.new_xyz[1]), float(self.new_xyz[2]))
        self.panel.x, self.panel.y, self.panel.z = nx, ny, nz
        # Мгновенно двигаем mesh, чтобы заливка не отставала от контура
        self._shift_mesh(self.panel, nx - ox, ny - oy, nz - oz)
        self.panel.rebuild_geometry()
        _reapply_panel_block_joints(self.panel)

    def undo(self) -> None:
        ox = float(self.panel.x)
        oy = float(self.panel.y)
        oz = float(self.panel.z)
        nx, ny, nz = (float(self.old_xyz[0]), float(self.old_xyz[1]), float(self.old_xyz[2]))
        self.panel.x, self.panel.y, self.panel.z = nx, ny, nz
        self._shift_mesh(self.panel, nx - ox, ny - oy, nz - oz)
        self.panel.rebuild_geometry()
        _reapply_panel_block_joints(self.panel)



class ResizePanelCommand(Command):
    """Изменение габаритов и позиции панели (растягивание за угол)."""

    def __init__(self, panel, old_box: tuple, new_box: tuple):
        # box = (x, y, z, width, height, depth)
        super().__init__(f"Размер: {panel.name}")
        self.panel = panel
        self.old_box = tuple(float(v) for v in old_box)
        self.new_box = tuple(float(v) for v in new_box)

    def can_merge_with(self, next_cmd: Command) -> bool:
        return isinstance(next_cmd, ResizePanelCommand) and next_cmd.panel is self.panel

    def merge_with(self, next_cmd: Command) -> None:
        if isinstance(next_cmd, ResizePanelCommand):
            self.new_box = next_cmd.new_box

    def _apply(self, box: tuple) -> None:
        self.panel.x, self.panel.y, self.panel.z = box[0], box[1], box[2]
        self.panel.width, self.panel.height, self.panel.depth = box[3], box[4], box[5]
        if hasattr(self.panel, "lock_thickness_to_material"):
            self.panel.lock_thickness_to_material()
        self.panel._gl_arrays = None
        self.panel.rebuild_geometry()
        _reapply_panel_block_joints(self.panel)

    def redo(self) -> None:
        self._apply(self.new_box)

    def undo(self) -> None:
        self._apply(self.old_box)


class EditPropertyCommand(Command):
    """Изменение свойства панели или параметрического блока с поддержкой отмены.

    Важно: rebuild вызывается только для свойств, влияющих на геометрию/структуру.
    Метаданные (имя, pos_num, code) и сдвиг корпуса по XYZ больше не уничтожают
    пользовательские правки (присадка, кромка, материалы панелей).
    """

    # Свойства, которые никогда не должны вызывать пересборку
    METADATA_ATTRS = frozenset({"name", "pos_num", "code"})

    # Свойства ParametricCabinet, меняющие состав/размеры панелей → полный rebuild()
    CABINET_STRUCTURE_ATTRS = frozenset({
        "width", "height", "depth", "thickness",
        "shelves_count", "has_facade", "is_upper", "has_groove",
    })

    # Атрибуты корпуса, проходящие технологическую валидацию в _apply_value (ревизия 2, п. 1.3)
    CABINET_VALIDATED_ATTRS = frozenset({
        "width", "height", "depth", "thickness", "shelves_count",
    })

    # Свойства Panel, влияющие на B-Rep
    PANEL_GEOMETRY_ATTRS = frozenset({
        "width", "height", "depth", "x", "y", "z",
        "rx", "ry", "rz", "material",
    })

    def __init__(
        self,
        obj,
        attr_name: str,
        old_val,
        new_val,
        description: str | None = None,
        *,
        formula_expr: str | None = None,
    ):
        label = getattr(obj, "name", "Объект")
        super().__init__(description or f"Свойство {attr_name}: {label}")
        self.obj = obj
        self.attr_name = attr_name
        self.old_val = old_val
        self.new_val = new_val
        # formula_expr: None = не трогать driver; "" = снять; иначе установить
        self.formula_expr = formula_expr
        self._old_driver: str | None = None
        if formula_expr is not None and hasattr(obj, "drivers"):
            drv = getattr(obj, "drivers", None) or {}
            self._old_driver = str(drv.get(attr_name)) if attr_name in (drv or {}) else None
        # Для смены материала сохраняем связку id + color + missing_material_id
        self._old_material_id = getattr(obj, "material_id", None) if attr_name == "material" else None
        self._old_color = getattr(obj, "color", None) if attr_name == "material" else None
        self._old_missing_material_id = getattr(obj, "missing_material_id", "") if attr_name == "material" else ""
        self._new_material_id = None
        self._new_color = None
        # Словари удалённых при структурном rebuild() панелей (role -> dict) для восстановления при Undo (план §1.8)
        self._removed_panels_by_role: dict[str, dict] = {}
        if attr_name == "material":
            self._resolve_material_side_effects(new_val)

    def _resolve_material_side_effects(self, name_or_id: str) -> None:
        """Подбирает material_id и color по введённому имени / id через SceneController."""
        try:
            from core.scene_controller import SceneController

            ctrl = SceneController.instance()
            mid, mname, mcolor, _mat_t, found = ctrl.resolve_material(
                material_id=str(name_or_id),
                legacy_name=str(name_or_id),
            )
            if found:
                self._new_material_id = mid
                self._new_color = mcolor
                self.new_val = mname
        except Exception:
            _log.exception("Failed to resolve material side effects for %r", name_or_id)

    def can_merge_with(self, next_cmd: Command) -> bool:
        return (
            isinstance(next_cmd, EditPropertyCommand)
            and next_cmd.obj is self.obj
            and next_cmd.attr_name == self.attr_name
        )

    def merge_with(self, next_cmd: Command) -> None:
        if isinstance(next_cmd, EditPropertyCommand):
            self.new_val = next_cmd.new_val
            if next_cmd.formula_expr is not None:
                self.formula_expr = next_cmd.formula_expr
            if self.attr_name == "material":
                self._new_material_id = next_cmd._new_material_id
                self._new_color = next_cmd._new_color
            for role, pdict in next_cmd._removed_panels_by_role.items():
                self._removed_panels_by_role.setdefault(role, pdict)

    def _is_cabinet(self) -> bool:
        return hasattr(self.obj, "rebuild") and hasattr(self.obj, "panels")

    def _snapshot_cabinet_panels_by_role(self) -> dict[str, dict]:
        """Снимает словари текущих панелей корпуса по ролям перед структурным rebuild()."""
        from core.project_io import _panel_to_dict

        snap: dict[str, dict] = {}
        for p in getattr(self.obj, "panels", None) or []:
            role = getattr(p, "role", "") or ""
            if not role and hasattr(self.obj, "_infer_role_from_name"):
                role = self.obj._infer_role_from_name(getattr(p, "name", ""))
                if role:
                    p.role = role
            if role and role not in snap:
                snap[role] = _panel_to_dict(p)
        return snap

    @staticmethod
    def _sanitize_property_value(attr_name: str, value):
        """Финальный барьер: nan/inf/нелегальные размеры не попадают в модель."""
        import math
        if attr_name in ("width", "height", "depth", "thickness"):
            try:
                v = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v) or v < 1.0 or v > 10000.0:
                return None
            return v
        if attr_name in ("x", "y", "z"):
            try:
                v = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v) or abs(v) > 50000.0:
                return None
            return v
        if attr_name in ("rx", "ry", "rz"):
            try:
                v = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v) or abs(v) > 360.0:
                return None
            return v
        if attr_name == "shelves_count":
            try:
                n = int(value)
            except (TypeError, ValueError):
                return None
            if n < 0 or n > 50:
                return None
            return n
        return value

    def _apply_value(self, value) -> None:
        """Записывает значение свойства (без rebuild)."""

        if self.attr_name.startswith("edge_"):
            side = self.attr_name.split("_", 1)[1]
            if hasattr(self.obj, "set_edge"):
                self.obj.set_edge(side, value)
        elif self.attr_name == "edges_all":
            if hasattr(self.obj, "set_edge"):
                if isinstance(value, dict):
                    for s, val in value.items():
                        self.obj.set_edge(s, val)
                else:
                    for s in ("top", "bottom", "left", "right"):
                        self.obj.set_edge(s, value)
        else:
            if self._is_cabinet() and self.attr_name in self.CABINET_VALIDATED_ATTRS:
                from core.validation import (
                    ValidationError,
                    cabinet_params_from_obj,
                    validate_cabinet_params,
                )

                errs = validate_cabinet_params(
                    **cabinet_params_from_obj(self.obj, {self.attr_name: value})
                )
                if errs:
                    raise ValidationError(errs[0], errs)
            sanitized = self._sanitize_property_value(self.attr_name, value)
            if sanitized is None:
                return
            setattr(self.obj, self.attr_name, sanitized)

    def _apply_material_extras(self, material_id, color, missing_material_id: str = "") -> None:
        if material_id is not None:
            self.obj.material_id = material_id
        if color is not None:
            self.obj.color = color
        if hasattr(self.obj, "missing_material_id"):
            self.obj.missing_material_id = str(missing_material_id or "")
        if hasattr(self.obj, "lock_thickness_to_material"):
            self.obj.lock_thickness_to_material()

    def _shift_cabinet_panels(self, dx: float, dy: float, dz: float) -> None:
        """Сдвигает все панели корпуса на delta без пересоздания."""
        if abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(dz) < 1e-12:
            return
        panels = getattr(self.obj, "panels", None) or []
        for p in panels:
            p.x = float(p.x) + dx
            p.y = float(p.y) + dy
            p.z = float(p.z) + dz
            # Мгновенный сдвиг mesh (как в MovePanelCommand)
            md = getattr(p, "mesh_data", None)
            if md and len(md) >= 2:
                try:
                    import numpy as np
                    verts = np.asarray(md[0], dtype=float).copy()
                    if verts.size:
                        verts[:, 0] += dx
                        verts[:, 1] += dy
                        verts[:, 2] += dz
                        if len(md) >= 3 and md[2] is not None:
                            p.mesh_data = (verts, md[1], md[2])
                        else:
                            p.mesh_data = (verts, md[1])
                        p._gl_arrays = None
                except Exception:
                    _log.exception("EditPropertyCommand._shift_cabinet_panels mesh shift failed")
            if hasattr(p, "rebuild_geometry"):
                p.rebuild_geometry()

    def _after_change(self, is_redo: bool) -> None:
        """Решает, нужен ли rebuild / сдвиг, и выполняет его."""
        attr = self.attr_name

        # 1. Метаданные — только setattr, ничего больше
        if attr in self.METADATA_ATTRS:
            return

        # 2. Кромки — set_edge уже применён; геометрия панели (пильный размер) может
        #    зависеть от кромки, но B-Rep панели обычно не меняется. Не трогаем.
        if attr.startswith("edge_") or attr == "edges_all":
            return

        # 3. ParametricCabinet
        if self._is_cabinet():
            if attr in ("x", "y", "z"):
                # Сдвиг корпуса: двигаем существующие панели, не пересоздаём
                if is_redo:
                    old = float(self.old_val)
                    new = float(self.new_val)
                else:
                    old = float(self.new_val)
                    new = float(self.old_val)
                dx = dy = dz = 0.0
                if attr == "x":
                    dx = new - old
                elif attr == "y":
                    dy = new - old
                else:
                    dz = new - old
                self._shift_cabinet_panels(dx, dy, dz)
                if getattr(self.obj, "joints", None):
                    from core.joint import apply_joints

                    apply_joints(self.obj)
                return

            if attr in self.CABINET_STRUCTURE_ATTRS:
                # Перед структурным rebuild() сохраняем словари панелей, которые могут быть
                # удалены (например, при уменьшении shelves_count или отключении фасада),
                # и передаём сохранённые снимки для восстановления по роли при Undo/Redo.
                before_by_role = self._snapshot_cabinet_panels_by_role()
                try:
                    self.obj.rebuild(restore_by_role=self._removed_panels_by_role)
                except TypeError:
                    self.obj.rebuild()
                remaining_roles = {
                    getattr(p, "role", "") or ""
                    for p in (getattr(self.obj, "panels", None) or [])
                }
                for role, pdict in before_by_role.items():
                    if role not in remaining_roles:
                        self._removed_panels_by_role[role] = pdict
                # Пересчёт персистентных формул на панелях (cw/ch/cd)
                try:
                    from core.drivers import apply_block_drivers

                    apply_block_drivers(self.obj)
                except Exception:
                    _log.exception("apply_block_drivers after cabinet rebuild failed")
                return

            # Неизвестное свойство корпуса — на всякий случай не трогаем геометрию
            return

        # 4. Обычная Panel
        if attr == "material":
            if is_redo:
                self._apply_material_extras(self._new_material_id, self._new_color, "")
            else:
                self._apply_material_extras(self._old_material_id, self._old_color, self._old_missing_material_id)
            if hasattr(self.obj, "rebuild_geometry"):
                self.obj.rebuild_geometry()
            _reapply_panel_block_joints(self.obj)
            return

        if attr in self.PANEL_GEOMETRY_ATTRS:
            if hasattr(self.obj, "rebuild_geometry"):
                self.obj.rebuild_geometry()
            _reapply_panel_block_joints(self.obj)
            return

        # Всё остальное (неизвестные attrs) — без rebuild

    def _apply_driver_side_effect(self, *, is_redo: bool) -> None:
        """Устанавливает/снимает driver для атрибута панели (если formula_expr задан)."""
        if self.formula_expr is None:
            return
        if not hasattr(self.obj, "drivers"):
            return
        from core.drivers import DRIVABLE_ATTRS, clear_driver, set_driver

        if self.attr_name not in DRIVABLE_ATTRS:
            return
        if is_redo:
            if self.formula_expr == "":
                clear_driver(self.obj, self.attr_name)
            else:
                set_driver(self.obj, self.attr_name, self.formula_expr)
                try:
                    from core.drivers import apply_panel_drivers

                    apply_panel_drivers(self.obj, attrs={self.attr_name})
                except Exception:
                    _log.exception("apply_panel_drivers after set_driver failed")
        else:
            if self._old_driver:
                set_driver(self.obj, self.attr_name, self._old_driver)
                try:
                    from core.drivers import apply_panel_drivers

                    apply_panel_drivers(self.obj, attrs={self.attr_name})
                except Exception:
                    _log.exception("apply_panel_drivers after restore driver failed")
            else:
                clear_driver(self.obj, self.attr_name)

    def redo(self) -> None:
        self._apply_value(self.new_val)
        # material extras применяются внутри _after_change, чтобы не дублировать
        if self.attr_name == "material" and self._new_material_id is not None:
            pass  # handled in _after_change
        self._apply_driver_side_effect(is_redo=True)
        self._after_change(is_redo=True)

    def undo(self) -> None:
        self._apply_value(self.old_val)
        self._apply_driver_side_effect(is_redo=False)
        self._after_change(is_redo=False)


class ReplaceBlocksCommand(Command):
    """Замена всего списка блоков (очистка сцены / вставка шаблона пачкой)."""

    def __init__(self, blocks_ref: list, new_blocks: list, description: str):
        super().__init__(description)
        self.blocks_ref = blocks_ref
        self.old_blocks = list(blocks_ref)
        self.new_blocks = list(new_blocks)

    def redo(self) -> None:
        self.blocks_ref[:] = list(self.new_blocks)

    def undo(self) -> None:
        self.blocks_ref[:] = list(self.old_blocks)


class SetHolesCommand(Command):
    """Замена списка отверстий присадки на панели."""

    def __init__(self, panel, old_holes: list, new_holes: list, description: str = "Присадка"):
        super().__init__(description)
        self.panel = panel
        self.old_holes = [tuple(h) for h in old_holes]
        self.new_holes = [tuple(h) for h in new_holes]
        self.old_fastener_issues = list(getattr(panel, "fastener_issues", []) or [])

    def redo(self) -> None:
        self.panel.holes = [tuple(h) for h in self.new_holes]
        if not self.new_holes and hasattr(self.panel, "fastener_issues"):
            self.panel.fastener_issues = []
        self.panel.rebuild_geometry()

    def undo(self) -> None:
        self.panel.holes = [tuple(h) for h in self.old_holes]
        if hasattr(self.panel, "fastener_issues"):
            self.panel.fastener_issues = list(self.old_fastener_issues)
        self.panel.rebuild_geometry()


class PlaceJointFastenerCommand(Command):
    """Ставит отверстия присадки на двух панелях по стыку и регистрирует JointRecord в block.joints (п. 3.1)."""

    def __init__(
        self,
        panel_a,
        holes_a_old,
        holes_a_new,
        panel_b,
        holes_b_old,
        holes_b_new,
        description: str = "Крепёж по стыку",
        *,
        block=None,
        joint_record=None,
    ):
        super().__init__(description)
        self.panel_a = panel_a
        self.panel_b = panel_b
        self.holes_a_old = [tuple(h) for h in holes_a_old]
        self.holes_a_new = [tuple(h) for h in holes_a_new]
        self.holes_b_old = [tuple(h) for h in holes_b_old]
        self.holes_b_new = [tuple(h) for h in holes_b_new]
        self.issues_a_new = list(getattr(panel_a, "fastener_issues", []) or [])
        self.issues_b_new = list(getattr(panel_b, "fastener_issues", []) or [])
        self.issues_a_old = list(self.issues_a_new) if holes_a_old else []
        self.issues_b_old = list(self.issues_b_new) if holes_b_old else []
        self.block = block if block is not None else (
            getattr(panel_a, "_block", None) or getattr(panel_b, "_block", None)
        )
        self.joint_record = joint_record
        self._jmap_a_old = copy.deepcopy(getattr(panel_a, "joint_hole_map", {}) or {})
        self._jmap_b_old = copy.deepcopy(getattr(panel_b, "joint_hole_map", {}) or {})

    def redo(self) -> None:
        if self.joint_record is not None and self.block is not None:
            from core.joint import apply_joints

            if not hasattr(self.block, "joints") or self.block.joints is None:
                self.block.joints = []
            rec_uid = str(getattr(self.joint_record, "uid", ""))
            for idx, existing in enumerate(self.block.joints):
                if str(getattr(existing, "uid", "")) == rec_uid:
                    self.block.joints[idx] = self.joint_record
                    break
            else:
                self.block.joints.append(self.joint_record)
            apply_joints(self.block)
            return

        self.panel_a.holes = [tuple(h) for h in self.holes_a_new]
        self.panel_b.holes = [tuple(h) for h in self.holes_b_new]
        if hasattr(self.panel_a, "fastener_issues"):
            self.panel_a.fastener_issues = list(self.issues_a_new)
        if hasattr(self.panel_b, "fastener_issues"):
            self.panel_b.fastener_issues = list(self.issues_b_new)
        self.panel_a.rebuild_geometry()
        self.panel_b.rebuild_geometry()

    def undo(self) -> None:
        if self.joint_record is not None and self.block is not None and hasattr(self.block, "joints"):
            rec_uid = str(getattr(self.joint_record, "uid", ""))
            self.block.joints = [
                jr for jr in self.block.joints if str(getattr(jr, "uid", "")) != rec_uid
            ]
        self.panel_a.holes = [tuple(h) for h in self.holes_a_old]
        self.panel_b.holes = [tuple(h) for h in self.holes_b_old]
        if hasattr(self.panel_a, "joint_hole_map"):
            self.panel_a.joint_hole_map = copy.deepcopy(self._jmap_a_old)
        if hasattr(self.panel_b, "joint_hole_map"):
            self.panel_b.joint_hole_map = copy.deepcopy(self._jmap_b_old)
        if hasattr(self.panel_a, "fastener_issues"):
            self.panel_a.fastener_issues = list(self.issues_a_old)
        if hasattr(self.panel_b, "fastener_issues"):
            self.panel_b.fastener_issues = list(self.issues_b_old)
        self.panel_a.rebuild_geometry()
        self.panel_b.rebuild_geometry()


class AddJointCommand(Command):
    """Добавление параметрического стыка JointRecord в блок с поддержкой Undo/Redo (п. 3.1)."""

    def __init__(self, block, joint_record, description: str = "Добавление стыка"):
        super().__init__(description)
        self.block = block
        self.joint_record = joint_record

    def redo(self) -> None:
        from core.joint import apply_joints

        if not hasattr(self.block, "joints") or self.block.joints is None:
            self.block.joints = []
        rec_uid = str(getattr(self.joint_record, "uid", ""))
        for idx, existing in enumerate(self.block.joints):
            if str(getattr(existing, "uid", "")) == rec_uid:
                self.block.joints[idx] = self.joint_record
                break
        else:
            self.block.joints.append(self.joint_record)
        apply_joints(self.block)

    def undo(self) -> None:
        from core.joint import apply_joints

        if hasattr(self.block, "joints") and self.block.joints is not None:
            rec_uid = str(getattr(self.joint_record, "uid", ""))
            self.block.joints = [
                jr for jr in self.block.joints if str(getattr(jr, "uid", "")) != rec_uid
            ]
        apply_joints(self.block)


class EditJointCommand(Command):
    """Изменение пресета и параметров параметрического стыка с поддержкой Undo/Redo (п. 3.1)."""

    def __init__(
        self,
        block,
        joint_uid: str,
        old_state: dict,
        new_state: dict,
        description: str = "Параметры стыка",
    ):
        super().__init__(description)
        self.block = block
        self.joint_uid = str(joint_uid or "").strip()
        self.old_state = copy.deepcopy(old_state)
        self.new_state = copy.deepcopy(new_state)

    def can_merge_with(self, next_cmd: Command) -> bool:
        return (
            isinstance(next_cmd, EditJointCommand)
            and next_cmd.block is self.block
            and next_cmd.joint_uid == self.joint_uid
        )

    def merge_with(self, next_cmd: Command) -> None:
        if isinstance(next_cmd, EditJointCommand):
            self.new_state = copy.deepcopy(next_cmd.new_state)

    def _apply_state(self, state: dict) -> None:
        from core.joint import JointRecord, apply_joints

        joints = getattr(self.block, "joints", None) or []
        for idx, jr in enumerate(joints):
            if str(getattr(jr, "uid", "")) == self.joint_uid:
                updated = JointRecord.from_dict(state)
                updated.uid = self.joint_uid
                joints[idx] = updated
                break
        apply_joints(self.block)

    def redo(self) -> None:
        self._apply_state(self.new_state)

    def undo(self) -> None:
        self._apply_state(self.old_state)


class DeleteJointCommand(Command):
    """Удаление параметрического стыка (и его отверстий) с поддержкой Undo/Redo (п. 3.1)."""

    def __init__(self, block, joint_uid: str, description: str = "Удаление стыка"):
        super().__init__(description)
        self.block = block
        self.joint_uid = str(joint_uid or "").strip()
        self._removed_index: int = -1
        self._removed_record = None
        for idx, jr in enumerate(getattr(block, "joints", None) or []):
            if str(getattr(jr, "uid", "")) == self.joint_uid:
                self._removed_index = idx
                self._removed_record = copy.deepcopy(jr)
                break

    def redo(self) -> None:
        from core.joint import apply_joints

        if hasattr(self.block, "joints") and self.block.joints is not None:
            for idx, jr in enumerate(self.block.joints):
                if str(getattr(jr, "uid", "")) == self.joint_uid:
                    self._removed_index = idx
                    self._removed_record = copy.deepcopy(jr)
                    break
            self.block.joints = [
                jr for jr in self.block.joints if str(getattr(jr, "uid", "")) != self.joint_uid
            ]
        apply_joints(self.block)

    def undo(self) -> None:
        from core.joint import apply_joints

        if self._removed_record is None:
            return
        if not hasattr(self.block, "joints") or self.block.joints is None:
            self.block.joints = []
        rec_copy = copy.deepcopy(self._removed_record)
        if not any(str(getattr(jr, "uid", "")) == self.joint_uid for jr in self.block.joints):
            ins_idx = (
                min(max(0, self._removed_index), len(self.block.joints))
                if self._removed_index >= 0
                else len(self.block.joints)
            )
            self.block.joints.insert(ins_idx, rec_copy)
        apply_joints(self.block)


class AddAssocRefCommand(Command):
    """Добавление ассоциативной ссылки AssocRef в блок с Undo/Redo."""

    def __init__(self, block, assoc_ref, description: str = "Ассоциативная ссылка"):
        super().__init__(description)
        self.block = block
        self.assoc_ref = assoc_ref

    def redo(self) -> None:
        from core.assoc import apply_assoc_refs

        if not hasattr(self.block, "assoc_refs") or self.block.assoc_refs is None:
            self.block.assoc_refs = []
        rec_uid = str(getattr(self.assoc_ref, "uid", ""))
        for idx, existing in enumerate(self.block.assoc_refs):
            if str(getattr(existing, "uid", "")) == rec_uid:
                self.block.assoc_refs[idx] = self.assoc_ref
                break
        else:
            self.block.assoc_refs.append(self.assoc_ref)
        apply_assoc_refs(self.block)

    def undo(self) -> None:
        from core.assoc import apply_assoc_refs

        if hasattr(self.block, "assoc_refs") and self.block.assoc_refs is not None:
            rec_uid = str(getattr(self.assoc_ref, "uid", ""))
            self.block.assoc_refs = [
                r for r in self.block.assoc_refs if str(getattr(r, "uid", "")) != rec_uid
            ]
        apply_assoc_refs(self.block)


class EditAssocRefCommand(Command):
    """Изменение параметров AssocRef (грань, u/v, диаметр…) с Undo/Redo."""

    def __init__(
        self,
        block,
        assoc_uid: str,
        old_state: dict,
        new_state: dict,
        description: str = "Параметры ассоциации",
    ):
        super().__init__(description)
        self.block = block
        self.assoc_uid = str(assoc_uid or "").strip()
        self.old_state = copy.deepcopy(old_state)
        self.new_state = copy.deepcopy(new_state)

    def can_merge_with(self, next_cmd: Command) -> bool:
        return (
            isinstance(next_cmd, EditAssocRefCommand)
            and next_cmd.block is self.block
            and next_cmd.assoc_uid == self.assoc_uid
        )

    def merge_with(self, next_cmd: Command) -> None:
        if isinstance(next_cmd, EditAssocRefCommand):
            self.new_state = copy.deepcopy(next_cmd.new_state)

    def _apply_state(self, state: dict) -> None:
        from core.assoc import AssocRef, apply_assoc_refs

        refs = getattr(self.block, "assoc_refs", None) or []
        for idx, ref in enumerate(refs):
            if str(getattr(ref, "uid", "")) == self.assoc_uid:
                updated = AssocRef.from_dict(state)
                updated.uid = self.assoc_uid
                refs[idx] = updated
                break
        apply_assoc_refs(self.block)

    def redo(self) -> None:
        self._apply_state(self.new_state)

    def undo(self) -> None:
        self._apply_state(self.old_state)


class DeleteAssocRefCommand(Command):
    """Удаление ассоциативной ссылки и её отверстий с Undo/Redo."""

    def __init__(self, block, assoc_uid: str, description: str = "Удаление ассоциации"):
        super().__init__(description)
        self.block = block
        self.assoc_uid = str(assoc_uid or "").strip()
        self._removed_index: int = -1
        self._removed_record = None
        for idx, ref in enumerate(getattr(block, "assoc_refs", None) or []):
            if str(getattr(ref, "uid", "")) == self.assoc_uid:
                self._removed_index = idx
                # Снимок через to_dict, чтобы не делить мутабельный params
                from core.assoc import AssocRef

                if isinstance(ref, AssocRef):
                    self._removed_record = AssocRef.from_dict(ref.to_dict())
                elif isinstance(ref, dict):
                    self._removed_record = AssocRef.from_dict(ref)
                else:
                    self._removed_record = copy.deepcopy(ref)
                break

    def redo(self) -> None:
        from core.assoc import AssocRef, apply_assoc_refs

        if hasattr(self.block, "assoc_refs") and self.block.assoc_refs is not None:
            for idx, ref in enumerate(self.block.assoc_refs):
                if str(getattr(ref, "uid", "")) == self.assoc_uid:
                    self._removed_index = idx
                    if isinstance(ref, AssocRef):
                        self._removed_record = AssocRef.from_dict(ref.to_dict())
                    elif isinstance(ref, dict):
                        self._removed_record = AssocRef.from_dict(ref)
                    else:
                        self._removed_record = copy.deepcopy(ref)
                    break
            self.block.assoc_refs = [
                r for r in self.block.assoc_refs if str(getattr(r, "uid", "")) != self.assoc_uid
            ]
        apply_assoc_refs(self.block)

    def undo(self) -> None:
        from core.assoc import AssocRef, apply_assoc_refs

        if self._removed_record is None:
            return
        if not hasattr(self.block, "assoc_refs") or self.block.assoc_refs is None:
            self.block.assoc_refs = []
        if isinstance(self._removed_record, AssocRef):
            rec_copy = AssocRef.from_dict(self._removed_record.to_dict())
        elif isinstance(self._removed_record, dict):
            rec_copy = AssocRef.from_dict(self._removed_record)
        else:
            rec_copy = copy.deepcopy(self._removed_record)
        if not any(str(getattr(r, "uid", "")) == self.assoc_uid for r in self.block.assoc_refs):
            ins_idx = (
                min(max(0, self._removed_index), len(self.block.assoc_refs))
                if self._removed_index >= 0
                else len(self.block.assoc_refs)
            )
            self.block.assoc_refs.insert(ins_idx, rec_copy)
        apply_assoc_refs(self.block)


class PasteBlocksCommand(Command):
    """Вставка клонированных блоков (Ctrl+V)."""

    def __init__(self, blocks: list, new_blocks: list, description: str = "Вставка"):
        super().__init__(description)
        self.blocks = blocks
        self.new_blocks = list(new_blocks)

    def redo(self) -> None:
        for b in self.new_blocks:
            if b not in self.blocks:
                self.blocks.append(b)
            for p in getattr(b, "panels", []) or []:
                p._block = b
                p.selected = True
            b.selected = True

    def undo(self) -> None:
        for b in self.new_blocks:
            if b in self.blocks:
                self.blocks.remove(b)
            b.selected = False
            for p in getattr(b, "panels", []) or []:
                p.selected = False


class AddMultiplePanelsCommand(Command):
    """Добавление пачки панелей (Зеркальная копия / Линейный массив) за один шаг Undo/Redo."""

    def __init__(self, blocks: list, block, panels: list, description: str = "Массив деталей"):
        super().__init__(description)
        self.blocks = blocks
        self.block = block
        self.panels = list(panels)
        self._block_was_missing = False

    def redo(self) -> None:
        if self.block not in self.blocks:
            self.blocks.append(self.block)
            self._block_was_missing = True
        for b in self.blocks:
            b.selected = False
            for existing in getattr(b, "panels", []) or []:
                existing.selected = False
        for p in self.panels:
            p._block = self.block
            if p not in self.block.panels:
                self.block.panels.append(p)
            p.selected = True
        if getattr(self.block, "joints", None):
            from core.joint import apply_joints

            apply_joints(self.block)

    def undo(self) -> None:
        for p in self.panels:
            p.selected = False
            if p in self.block.panels:
                self.block.panels.remove(p)
        if getattr(self.block, "joints", None):
            from core.joint import apply_joints

            apply_joints(self.block)
        if self._block_was_missing and self.block in self.blocks and not self.block.panels:
            self.blocks.remove(self.block)

