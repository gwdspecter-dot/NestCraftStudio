"""Габаритная рамка изделия (пространственный ориентир проектирования).

Система координат соответствует принятой в NestCraft Studio:
- X — ширина изделия (слева направо);
- Y — высота изделия (снизу вверх);
- Z — глубина изделия (сзади вперёд).

Габаритная рамка является самостоятельным объектом модели изделия, не входит
в список физических панелей (`Block.panels`), не участвует в расчётах
материалов, кромок, раскроя и проверки коллизий и не ограничивает свободное
размещение деталей за её пределами.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

DEFAULT_FRAME_WIDTH_MM: float = 800.0
DEFAULT_FRAME_HEIGHT_MM: float = 2000.0
DEFAULT_FRAME_DEPTH_MM: float = 500.0

MIN_FRAME_DIM_MM: float = 10.0
MAX_FRAME_DIM_MM: float = 50000.0

# 12 рёбер параллелепипеда (индексы в списке corners())
_BOX_EDGE_INDICES: tuple[tuple[int, int], ...] = (
    # Нижний контур (y = y0)
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),
    # Верхний контур (y = y1)
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),
    # Вертикальные стойки
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
)


def _validate_finite_float(value: Any, field_label: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле «{field_label}» должно быть числом.") from exc
    if not math.isfinite(num):
        raise ValueError(f"Поле «{field_label}» должно быть конечным числом.")
    return num


def validate_bounding_frame_dims(
    width: Any,
    height: Any,
    depth: Any,
) -> tuple[float, float, float]:
    """Проверяет габаритные размеры (мм) и возвращает `(width, height, depth)`.

    При некорректных значениях выбрасывает `ValueError` с понятным сообщением на русском.
    """
    w = _validate_finite_float(width, "Ширина")
    h = _validate_finite_float(height, "Высота")
    d = _validate_finite_float(depth, "Глубина")

    for val, label in ((w, "Ширина"), (h, "Высота"), (d, "Глубина")):
        if val <= 0.0:
            raise ValueError(f"Поле «{label}» должно быть больше 0 мм.")
        if val < MIN_FRAME_DIM_MM:
            raise ValueError(
                f"Поле «{label}» не может быть меньше {MIN_FRAME_DIM_MM:g} мм."
            )
        if val > MAX_FRAME_DIM_MM:
            raise ValueError(
                f"Поле «{label}» не может превышать {MAX_FRAME_DIM_MM:g} мм."
            )
    return w, h, d


@dataclass
class BoundingFrame:
    """Габаритная рамка изделия: ширина (X), высота (Y), глубина (Z) в мм."""

    width: float = DEFAULT_FRAME_WIDTH_MM
    height: float = DEFAULT_FRAME_HEIGHT_MM
    depth: float = DEFAULT_FRAME_DEPTH_MM
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    visible: bool = True

    def __post_init__(self) -> None:
        self.width, self.height, self.depth = validate_bounding_frame_dims(
            self.width, self.height, self.depth
        )
        self.x = _validate_finite_float(self.x, "Координата X")
        self.y = _validate_finite_float(self.y, "Координата Y")
        self.z = _validate_finite_float(self.z, "Координата Z")
        self.visible = bool(self.visible)

    def world_aabb(
        self,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Возвращает мировой AABB `((x0, y0, z0), (x1, y1, z1))`."""
        x0, y0, z0 = float(self.x), float(self.y), float(self.z)
        return (
            (x0, y0, z0),
            (x0 + float(self.width), y0 + float(self.height), z0 + float(self.depth)),
        )

    def center(self) -> tuple[float, float, float]:
        """Центр габаритной рамки в мировых координатах."""
        return (
            float(self.x) + float(self.width) * 0.5,
            float(self.y) + float(self.height) * 0.5,
            float(self.z) + float(self.depth) * 0.5,
        )

    def corners(self) -> list[tuple[float, float, float]]:
        """8 вершин параллелепипеда габаритной рамки в мировых координатах."""
        (x0, y0, z0), (x1, y1, z1) = self.world_aabb()
        return [
            (x0, y0, z0),  # 0: низ-лево-зад
            (x1, y0, z0),  # 1: низ-право-зад
            (x1, y0, z1),  # 2: низ-право-перед
            (x0, y0, z1),  # 3: низ-лево-перед
            (x0, y1, z0),  # 4: верх-лево-зад
            (x1, y1, z0),  # 5: верх-право-зад
            (x1, y1, z1),  # 6: верх-право-перед
            (x0, y1, z1),  # 7: верх-лево-перед
        ]

    def edge_segments(
        self,
    ) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        """12 отрезков (рёбер) габаритной рамки для отрисовки в 3D."""
        pts = self.corners()
        return [(pts[i], pts[j]) for i, j in _BOX_EDGE_INDICES]

    def face_planes(self) -> dict[str, float]:
        """Координаты 6 плоскостей габаритной рамки по мировым осям."""
        (x0, y0, z0), (x1, y1, z1) = self.world_aabb()
        return {
            "x_min": x0,
            "x_max": x1,
            "y_min": y0,
            "y_max": y1,
            "z_min": z0,
            "z_max": z1,
        }

    def snap_points(
        self,
        label_prefix: str = "Габаритная рамка",
    ) -> list[tuple[tuple[float, float, float], str, str, None, dict[str, Any]]]:
        """Точки привязки рамки: 8 углов, 12 середин рёбер и 6 центров граней.

        Формат элемента совпадает с точками привязки `Viewport3D`:
        `(point_xyz, description, kind, owner_panel=None, meta_dict)`.
        """
        pts = self.corners()
        out: list[tuple[tuple[float, float, float], str, str, None, dict[str, Any]]] = []

        for idx, pt in enumerate(pts, start=1):
            out.append(
                (
                    pt,
                    f"Угол {idx} [{label_prefix}]",
                    "corner",
                    None,
                    {"source": "bounding_frame", "corner_index": idx},
                )
            )

        for e_idx, (i, j) in enumerate(_BOX_EDGE_INDICES, start=1):
            a, b = pts[i], pts[j]
            mid = (
                0.5 * (a[0] + b[0]),
                0.5 * (a[1] + b[1]),
                0.5 * (a[2] + b[2]),
            )
            out.append(
                (
                    mid,
                    f"Середина ребра {e_idx} [{label_prefix}]",
                    "edge_mid",
                    None,
                    {"source": "bounding_frame", "edge_index": e_idx},
                )
            )

        (x0, y0, z0), (x1, y1, z1) = self.world_aabb()
        cx, cy, cz = self.center()
        face_centers = (
            ((x0, cy, cz), "Левая грань", "x_min"),
            ((x1, cy, cz), "Правая грань", "x_max"),
            ((cx, y0, cz), "Нижняя грань", "y_min"),
            ((cx, y1, cz), "Верхняя грань", "y_max"),
            ((cx, cy, z0), "Задняя грань", "z_min"),
            ((cx, cy, z1), "Передняя грань", "z_max"),
        )
        for pt, title, face_id in face_centers:
            out.append(
                (
                    pt,
                    f"{title} [{label_prefix}]",
                    "face_center",
                    None,
                    {"source": "bounding_frame", "face": face_id},
                )
            )

        return out

    def default_panel_geometry(
        self,
        panel_type: str,
        thickness: float = 16.0,
    ) -> dict[str, float]:
        """Возвращает стартовые размеры и координаты новой панели по текущей рамке.

        Значения используются только как ориентир по умолчанию при создании
        новой детали; пользователь вправе задать любые размеры и координаты,
        включая выход за пределы габаритной рамки.
        """
        t = max(1.0, float(thickness))
        w = float(self.width)
        h = float(self.height)
        d = float(self.depth)
        x0, y0, z0 = float(self.x), float(self.y), float(self.z)

        if panel_type == "vertical":
            return {
                "width": t,
                "height": h,
                "depth": d,
                "dim1": h,
                "dim2": d,
                "x": x0,
                "y": y0,
                "z": z0,
            }
        if panel_type == "horizontal":
            return {
                "width": w,
                "height": t,
                "depth": d,
                "dim1": w,
                "dim2": d,
                "x": x0,
                "y": y0,
                "z": z0,
            }
        # frontal (фасад / задняя стенка): dim1 = высота (Y), dim2 = ширина (X)
        return {
            "width": w,
            "height": h,
            "depth": t,
            "dim1": h,
            "dim2": w,
            "x": x0,
            "y": y0,
            "z": z0,
        }

    def clone(self) -> "BoundingFrame":
        """Создаёт независимую копию габаритной рамки."""
        return BoundingFrame(
            width=self.width,
            height=self.height,
            depth=self.depth,
            x=self.x,
            y=self.y,
            z=self.z,
            visible=self.visible,
        )

    def to_dict(self) -> dict[str, Any]:
        """Сериализует габаритную рамку в JSON-совместимый словарь."""
        return {
            "width": float(self.width),
            "height": float(self.height),
            "depth": float(self.depth),
            "x": float(self.x),
            "y": float(self.y),
            "z": float(self.z),
            "visible": bool(self.visible),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "BoundingFrame | None":
        """Восстанавливает габаритную рамку из словаря или возвращает None."""
        if data is None:
            return None
        if isinstance(data, cls):
            return data.clone()
        if not isinstance(data, dict):
            return None
        return cls(
            width=data.get("width", DEFAULT_FRAME_WIDTH_MM),
            height=data.get("height", DEFAULT_FRAME_HEIGHT_MM),
            depth=data.get("depth", DEFAULT_FRAME_DEPTH_MM),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            z=data.get("z", 0.0),
            visible=bool(data.get("visible", True)),
        )
