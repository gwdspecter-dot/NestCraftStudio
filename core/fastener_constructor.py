"""Модель параметров и персистентность строк конструктора крепежа (v0.0.19)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.logging_setup import get_logger, user_data_dir

_log = get_logger("fastener_constructor")


@dataclass
class ConfirmatParams:
    """Параметры конфирмата (D1 — пласть, D2 — торец, H — длина, H1 — глубина в торец при >0)."""

    name: str = "Конфирмат 7×50 мм, Zn"
    d1: float = 8.0   # диаметр сверления в пласть (сквозное)
    d2: float = 5.0   # диаметр сверления в торец (глухое)
    h: float = 50.0   # общая длина метиза
    h1: float = 0.0   # явная глубина сверления в торец (если > 0; иначе вычисляется от H)

    def clone(self) -> "ConfirmatParams":
        return ConfirmatParams(
            str(self.name),
            float(self.d1),
            float(self.d2),
            float(self.h),
            float(self.h1),
        )

    def edge_depth(self, panel_thickness: float = 16.0) -> float:
        """Глубина глухого отверстия в торец (мм)."""
        if float(self.h1) > 0:
            return max(4.0, float(self.h1))
        # Для стандартной плиты 16 мм и H=50 глубина в торец = 38 мм (H - 12)
        offset = max(8.0, float(panel_thickness) - 4.0)
        return max(12.0, round(float(self.h) - offset, 2))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": str(self.name),
            "d1": float(self.d1),
            "d2": float(self.d2),
            "h": float(self.h),
            "h1": float(self.h1),
            "type": "confirmat",
        }

    def to_selected_fastener_dict(self) -> dict[str, Any]:
        """Словарь параметров выбранного метиза для Viewport3D, JointRecord и make_joint_holes."""
        d = self.to_dict()
        edep = self.edge_depth()
        d["diameter"] = float(self.d1)
        d["depth"] = float(edep)
        d["drill_face_diameter"] = float(self.d1)
        d["drill_edge_diameter"] = float(self.d2)
        d["drill_edge_depth"] = float(edep)
        d["drill_through"] = True
        d["fastener_type"] = "confirmat"
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfirmatParams":
        if isinstance(data, cls):
            return data.clone()
        return cls(
            name=str(data.get("name") or "Конфирмат 7×50 мм, Zn"),
            d1=max(0.1, float(data.get("d1", 8.0))),
            d2=max(0.1, float(data.get("d2", 5.0))),
            h=max(1.0, float(data.get("h", 50.0))),
            h1=max(0.0, float(data.get("h1", 0.0))),
        )


def default_confirmat_rows() -> list[ConfirmatParams]:
    return [
        ConfirmatParams("Конфирмат 7×50 мм, Zn", 8.0, 5.0, 50.0, 0.0),
    ]


_SESSION_ROWS: list[ConfirmatParams] | None = None
_SESSION_SELECTED_INDEX: int = 0


def _storage_file(custom_path: Path | None = None) -> Path:
    if custom_path is not None:
        return Path(custom_path)
    return user_data_dir() / "fastener_constructor_rows.json"


def load_confirmat_rows(
    custom_path: Path | None = None,
) -> tuple[list[ConfirmatParams], int]:
    """Загружает сохранённые строки конструктора конфирматов и индекс выбранной строки."""
    global _SESSION_ROWS, _SESSION_SELECTED_INDEX
    target = _storage_file(custom_path)
    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            raw_rows = raw.get("rows") if isinstance(raw, dict) else None
            if isinstance(raw_rows, list) and raw_rows:
                rows = [
                    ConfirmatParams.from_dict(item)
                    for item in raw_rows
                    if isinstance(item, dict)
                ]
                if rows:
                    sel = int(raw.get("selected_index", 0) or 0)
                    sel = max(0, min(sel, len(rows) - 1))
                    if custom_path is None:
                        _SESSION_ROWS = [r.clone() for r in rows]
                        _SESSION_SELECTED_INDEX = sel
                    return rows, sel
        except Exception:  # noqa: BLE001 — граница JSON I/O
            _log.debug("Could not load fastener_constructor_rows.json", exc_info=True)

    if custom_path is None and _SESSION_ROWS:
        sel = max(0, min(_SESSION_SELECTED_INDEX, len(_SESSION_ROWS) - 1))
        return [r.clone() for r in _SESSION_ROWS], sel

    rows = default_confirmat_rows()
    return rows, 0


def save_confirmat_rows(
    rows: list[ConfirmatParams],
    selected_index: int = 0,
    custom_path: Path | None = None,
) -> None:
    """Сохраняет строки конструктора конфирматов в память и на диск."""
    global _SESSION_ROWS, _SESSION_SELECTED_INDEX
    clean = [r.clone() for r in (rows or [])] or default_confirmat_rows()
    sel = max(0, min(int(selected_index or 0), len(clean) - 1))
    if custom_path is None:
        _SESSION_ROWS = [r.clone() for r in clean]
        _SESSION_SELECTED_INDEX = sel

    target = _storage_file(custom_path)
    payload = {
        "selected_index": sel,
        "rows": [r.to_dict() for r in clean],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 — граница JSON I/O
        _log.debug("Could not save fastener_constructor_rows.json", exc_info=True)


def reset_confirmat_rows(custom_path: Path | None = None) -> None:
    """Сбрасывает пользовательские строки конструктора к значениям по умолчанию."""
    global _SESSION_ROWS, _SESSION_SELECTED_INDEX
    if custom_path is None:
        _SESSION_ROWS = None
        _SESSION_SELECTED_INDEX = 0
    target = _storage_file(custom_path)
    if target.is_file():
        try:
            target.unlink()
        except OSError:
            _log.debug("Could not remove fastener_constructor_rows.json", exc_info=True)
