# -*- coding: utf-8 -*-
"""Безопасный вычислитель математических выражений и формул для числовых полей ввода CAD.

Поддерживает:
- Арифметику: `600 - 32`, `720 / 3`, `(800 - 3 * 16) / 2`, `1800 - 100 - 16`
- Десятичную запятую и точку: `568,5 + 15,5`, `= 600 - 32`
- Относительные приращения к текущему значению (`current_value`):
  `+= 50`, `-= 32`, `*= 2`, `/= 2`
- Переменные контекста детали/корпуса (`w`, `h`, `d`, `t`, `x`, `y`, `z`, `cur`, `pi`)
- Базовые функции: `round`, `abs`, `min`, `max`, `sqrt`, `sin`, `cos`, `tan` (тригонометрия в градусах)
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from core.logging_setup import get_logger

_log = get_logger("formula")
_MAX_FORMULA_LEN = 200

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_SAFE_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": lambda deg: math.sin(math.radians(float(deg))),
    "cos": lambda deg: math.cos(math.radians(float(deg))),
    "tan": lambda deg: math.tan(math.radians(float(deg))),
}


def is_formula_text(raw: str) -> bool:
    """Возвращает True, если строка содержит арифметическое выражение, а не просто запись числа."""
    s = str(raw or "").strip()
    if not s:
        return False
    if s.startswith(("=", "+=", "-=", "*=", "/=")):
        return True
    # Игнорируем ведущий знак у обычного числа (например "-150.5")
    body = s[1:].strip() if s[0] in "+-" else s
    return any(ch in body for ch in ("+", "-", "*", "/", "(", ")", "w", "h", "d", "t", "x", "y", "z"))


def context_vars_from_object(obj: Any, current_value: float | None = None) -> dict[str, float]:
    """Собирает словарь переменных (`w`, `h`, `d`, `t`, `x`, `y`, `z`, `cur`) из `Panel` или `ParametricCabinet`."""
    env: dict[str, float] = {"pi": math.pi}
    if current_value is not None and math.isfinite(float(current_value)):
        env["cur"] = float(current_value)
    if obj is None:
        return env
    for key, attr in (
        ("w", "width"),
        ("width", "width"),
        ("h", "height"),
        ("height", "height"),
        ("d", "depth"),
        ("depth", "depth"),
        ("x", "x"),
        ("y", "y"),
        ("z", "z"),
    ):
        val = getattr(obj, attr, None)
        if isinstance(val, (int, float)) and math.isfinite(float(val)):
            env[key] = float(val)
    if hasattr(obj, "material_thickness_mm") and callable(obj.material_thickness_mm):
        try:
            t_val = float(obj.material_thickness_mm())
            if math.isfinite(t_val) and t_val > 0.0:
                env["t"] = t_val
        except Exception as exc:
            _log.debug("Не удалось получить толщину материала для контекста формулы: %s", exc)
    if "t" not in env and hasattr(obj, "thickness"):
        t_val = getattr(obj, "thickness", None)
        if isinstance(t_val, (int, float)) and math.isfinite(float(t_val)) and float(t_val) > 0.0:
            env["t"] = float(t_val)
    if "t" not in env and all(k in env for k in ("w", "h", "d")):
        tax = getattr(obj, "thickness_axis", None)
        if isinstance(tax, str) and tax.upper() in ("X", "Y", "Z"):
            env["t"] = env[{"X": "w", "Y": "h", "Z": "d"}[tax.upper()]]
        elif isinstance(tax, int) and tax in (0, 1, 2):
            env["t"] = env[("w", "h", "d")[tax]]
        else:
            env["t"] = min(env["w"], env["h"], env["d"])
    return env


def eval_math_expression(
    raw: str,
    *,
    current_value: float | None = None,
    variables: dict[str, float] | None = None,
) -> float:
    """Безопасно вычисляет число или арифметическую формулу из строки `raw`.

    При любой синтаксической ошибке, делении на ноль или выходе за конечные float
    выбрасывает `ValueError`.
    """
    if not isinstance(raw, str):
        raise ValueError("Formula must be a string")
    s = raw.strip()
    if not s or len(s) > _MAX_FORMULA_LEN:
        raise ValueError("Empty or too long expression")

    # Убираем ведущий '=' (как в таблицах: '= 600 - 32')
    if s.startswith("="):
        s = s[1:].strip()
        if not s:
            raise ValueError("Empty expression after '='")

    # Заменяем запятые на точки, а символы '×' и '÷' на '*' и '/'
    s = s.replace(",", ".").replace("×", "*").replace("÷", "/")

    # Быстрый путь для обычного числа
    try:
        direct: float | None = float(s)
    except ValueError:
        direct = None
    if direct is not None:
        if not math.isfinite(direct):
            raise ValueError("Result is not finite")
        return direct

    # Обработка относительных операторов: +=, -=, *=, /=
    rel_op = None
    for prefix, op_fn in (
        ("+=", operator.add),
        ("-=", operator.sub),
        ("*=", operator.mul),
        ("/=", operator.truediv),
    ):
        if s.startswith(prefix):
            if current_value is None or not math.isfinite(float(current_value)):
                raise ValueError(f"Relative operator '{prefix}' requires current_value")
            rel_op = op_fn
            s = s[len(prefix):].strip()
            break

    env: dict[str, float] = {"pi": math.pi}
    if current_value is not None and math.isfinite(float(current_value)):
        env["cur"] = float(current_value)
    if variables:
        for k, v in variables.items():
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                env[str(k).lower()] = float(v)

    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid formula syntax: {raw}") from exc

    def _eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                val = float(node.value)
                if not math.isfinite(val):
                    raise ValueError("Non-finite constant")
                return val
            raise ValueError(f"Unsupported constant: {node.value!r}")
        if isinstance(node, ast.Name):
            name = node.id.lower()
            if name in env:
                return float(env[name])
            raise ValueError(f"Unknown variable: {node.id}")
        if isinstance(node, ast.UnaryOp):
            uop = _UNARY_OPS.get(type(node.op))
            if uop is None:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            return float(uop(_eval_node(node.operand)))
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Pow):
                base = _eval_node(node.left)
                exp = _eval_node(node.right)
                if abs(exp) > 10.0:
                    raise ValueError("Exponent too large")
                return float(base ** exp)
            bop = _BINARY_OPS.get(type(node.op))
            if bop is None:
                raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and abs(right) < 1e-12:
                raise ValueError("Division by zero")
            return float(bop(left, right))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ValueError("Only simple function calls are allowed")
            fname = node.func.id.lower()
            fn = _SAFE_FUNCS.get(fname)
            if fn is None:
                raise ValueError(f"Unsupported function: {node.func.id}")
            args = [_eval_node(a) for a in node.args]
            if not args:
                raise ValueError(f"Function {fname} requires arguments")
            return float(fn(*args))
        raise ValueError(f"Unsupported syntax node: {type(node).__name__}")

    try:
        result = _eval_node(tree)
        if rel_op is not None and current_value is not None:
            if rel_op is operator.truediv and abs(result) < 1e-12:
                raise ValueError("Division by zero")
            result = float(rel_op(float(current_value), result))
    except (ZeroDivisionError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"Formula evaluation error: {raw}") from exc

    if not math.isfinite(result):
        raise ValueError("Formula result is not finite")
    return float(result)
