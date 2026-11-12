# -*- coding: utf-8 -*-
"""Персистентные формулы (drivers) для числовых свойств панелей.

Хранятся в ``panel.drivers[attr] = expression`` и пересчитываются при
изменении контекста (размеры панели / родительского корпуса).
"""

from __future__ import annotations

from typing import Any

from core.formula import context_vars_from_object, eval_math_expression, is_formula_text
from core.logging_setup import get_logger

_log = get_logger("drivers")

# Свойства, для которых разрешены drivers
DRIVABLE_ATTRS = frozenset({"width", "height", "depth", "x", "y", "z"})


def should_persist_formula(raw: str) -> bool:
    """True, если выражение стоит сохранить как driver (не разовое +=/-= и не голое число)."""
    s = str(raw or "").strip()
    if not s or not is_formula_text(s):
        return False
    # Относительные приращения — разовые, не drivers
    if s.startswith(("+=", "-=", "*=", "/=")):
        return False
    return True


def normalize_driver_expr(raw: str) -> str:
    """Нормализует строку driver (без ведущего '=', trim)."""
    s = str(raw or "").strip()
    if s.startswith("="):
        s = s[1:].strip()
    return s


def parent_context_object(panel) -> Any | None:
    """Родительский объект для переменных cw/ch/cd/ct — ParametricCabinet, если есть."""
    block = getattr(panel, "_block", None)
    if block is None:
        return None
    # ParametricCabinet имеет width/height/depth/thickness
    if hasattr(block, "rebuild") and hasattr(block, "width"):
        return block
    return None


def evaluate_driver(expr: str, panel, *, attr: str | None = None) -> float:
    """Вычисляет выражение driver в контексте панели и родителя."""
    parent = parent_context_object(panel)
    cur = None
    if attr and hasattr(panel, attr):
        try:
            cur = float(getattr(panel, attr))
        except (TypeError, ValueError):
            cur = None
    env = context_vars_from_object(panel, current_value=cur, parent=parent)
    return float(
        eval_math_expression(
            normalize_driver_expr(expr),
            current_value=cur,
            variables=env,
        )
    )


def apply_panel_drivers(panel, *, attrs: set[str] | None = None) -> list[str]:
    """Пересчитывает drivers панели. Возвращает список изменённых атрибутов."""
    drivers = getattr(panel, "drivers", None) or {}
    if not isinstance(drivers, dict) or not drivers:
        return []
    changed: list[str] = []
    target_attrs = attrs if attrs is not None else set(drivers.keys())
    for attr, expr in list(drivers.items()):
        if attr not in DRIVABLE_ATTRS or attr not in target_attrs:
            continue
        if not expr:
            continue
        try:
            new_val = evaluate_driver(str(expr), panel, attr=attr)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            _log.debug("Driver %s=%r на %s не вычислен: %s", attr, expr, getattr(panel, "name", "?"), exc)
            continue
        if attr in ("width", "height", "depth"):
            if new_val < 1.0 or new_val > 10000.0:
                _log.debug("Driver %s=%r → %s вне диапазона размера", attr, expr, new_val)
                continue
        try:
            old = float(getattr(panel, attr))
        except (TypeError, ValueError):
            old = None
        if old is not None and abs(old - new_val) < 1e-9:
            continue
        setattr(panel, attr, float(new_val))
        changed.append(attr)
    if changed and hasattr(panel, "rebuild_geometry"):
        try:
            if hasattr(panel, "lock_thickness_to_material"):
                panel.lock_thickness_to_material()
            panel.rebuild_geometry()
        except Exception as exc:  # noqa: BLE001
            _log.debug("rebuild_geometry после drivers: %s", exc)
    return changed


def apply_block_drivers(block) -> int:
    """Пересчитывает drivers всех панелей блока. Возвращает число панелей с изменениями."""
    n = 0
    for p in getattr(block, "panels", None) or []:
        if apply_panel_drivers(p):
            n += 1
    # После смены размеров панелей — стыки и assoc
    try:
        from core.undo import _reapply_panel_block_joints

        panels = getattr(block, "panels", None) or []
        if panels:
            _reapply_panel_block_joints(panels[0])
    except Exception as exc:  # noqa: BLE001
        _log.debug("reapply joints after drivers: %s", exc)
    return n


def set_driver(panel, attr: str, expr: str | None) -> None:
    """Устанавливает или снимает driver для атрибута."""
    if not hasattr(panel, "drivers") or panel.drivers is None:
        panel.drivers = {}
    if not isinstance(panel.drivers, dict):
        panel.drivers = {}
    attr = str(attr or "")
    if attr not in DRIVABLE_ATTRS:
        return
    if expr is None or str(expr).strip() == "":
        panel.drivers.pop(attr, None)
        return
    if not should_persist_formula(str(expr)):
        panel.drivers.pop(attr, None)
        return
    panel.drivers[attr] = normalize_driver_expr(str(expr))


def clear_driver(panel, attr: str) -> None:
    set_driver(panel, attr, None)
