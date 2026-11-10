"""Технологические и геометрические проверки входных параметров."""

from __future__ import annotations

import math


class ValidationError(ValueError):
    """Ошибка технологической или геометрической валидации параметров."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors: list[str] = list(errors) if errors is not None else [message]


def validate_cabinet_params(
    width: float,
    height: float,
    depth: float,
    thickness: float,
    shelves_count: int = 0,
) -> list[str]:
    """Проверки габаритов параметрического корпуса.

    Возвращает список сообщений об ошибках (пустой — ок).
    Правила согласованы с планом v0.0.18 §1.3 и типовой мебельной практикой.
    """
    errs: list[str] = []
    try:
        w = float(width)
        h = float(height)
        d = float(depth)
        t = float(thickness)
        if not (math.isfinite(w) and math.isfinite(h) and math.isfinite(d) and math.isfinite(t)):
            return ["Некорректное числовое значение"]
        if isinstance(shelves_count, float) and not math.isfinite(shelves_count):
            return ["Некорректное числовое значение"]
        n = int(shelves_count)
    except (TypeError, ValueError, OverflowError):
        return ["Некорректное числовое значение"]

    if t < 1.0 or t > 100.0:
        errs.append(f"Толщина ЛДСП {t:g} мм вне диапазона 1…100")

    # Внутри корпуса должно остаться место: 2 боковины + зазор
    min_w = 2.0 * t + 50.0
    if w < min_w:
        errs.append(f"Ширина корпуса {w:g} мм меньше минимума {min_w:g} мм (2×толщина + 50)")

    min_h = 3.0 * t + 50.0
    if h < min_h:
        errs.append(f"Высота корпуса {h:g} мм меньше минимума {min_h:g} мм (3×толщина + 50)")

    # Глубина: дно/крышка и полезный объём
    if d < 140.0:
        errs.append(f"Глубина корпуса {d:g} мм меньше минимума 140 мм")

    if w > 10000.0 or h > 10000.0 or d > 10000.0:
        errs.append("Габарит корпуса превышает 10000 мм")

    if n < 0 or n > 50:
        errs.append(f"Число полок {n} вне диапазона 0…50")
    elif n > 0:
        # Полки + дно + крышка должны физически помещаться по высоте
        # n полок + 2 горизонтали (дно/крышка) ≈ (n+2)*t + зазоры
        need = (n + 2) * t + (n + 1) * 20.0  # минимум ~20 мм проём между полками
        if h < need:
            errs.append(
                f"Высоты {h:g} мм недостаточно для {n} полок "
                f"(нужно ≥ {need:g} мм при толщине {t:g})"
            )

    return errs


def cabinet_params_from_obj(obj, overrides: dict | None = None) -> dict:
    """Снимок параметров корпуса с возможной подменой одного поля."""
    data = {
        "width": float(getattr(obj, "width", 600)),
        "height": float(getattr(obj, "height", 720)),
        "depth": float(getattr(obj, "depth", 560)),
        "thickness": float(getattr(obj, "thickness", 16)),
        "shelves_count": int(getattr(obj, "shelves_count", 0)),
    }
    if overrides:
        data.update(overrides)
    return data

