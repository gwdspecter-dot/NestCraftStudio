# -*- coding: utf-8 -*-
"""Геометрические операции: Зеркальная копия (Mirror) и Линейный массив (Linear Array) деталей.

Поддерживает:
- Отражение панели относительно центра корпуса/блока, собственного торца или произвольной плоскости X/Y/Z
  с автоматическим зеркалированием локальных отверстий (`holes`), пазов (`grooves`), кромок (`edges`) и углов поворота.
- Построение линейного массива деталей вдоль оси X, Y или Z:
  1) с фиксированным шагом (`step`),
  2) с фиксированным зазором в свету (`clear_gap`),
  3) с равномерным делением проёма на равные ниши в свету (`divide_span`).
"""

from __future__ import annotations

import re
from typing import Any

from models.panel import Panel


def _clean_copy_base_name(name: str) -> str:
    raw = (name or "Панель").strip()
    m = re.match(r"^(.*?)(?:\s*\((?:Копия|Зеркало|Массив)(?:\s+\d+)?\))+$", raw)
    if m:
        return m.group(1).strip() or raw
    return raw


def next_unique_name(base_name: str, suffix: str, existing_names: set[str]) -> str:
    """Генерирует уникальное имя детали с суффиксом («Зеркало», «Массив 1» и т.д.)."""
    clean = _clean_copy_base_name(base_name)
    cand = f"{clean} ({suffix})"
    if cand not in existing_names:
        existing_names.add(cand)
        return cand
    idx = 2
    while True:
        cand = f"{clean} ({suffix} {idx})"
        if cand not in existing_names:
            existing_names.add(cand)
            return cand
        idx += 1


def compute_mirror_plane_coord(
    panel: Panel,
    axis: str = "X",
    mode: str = "cabinet",
    custom_coord: float | None = None,
    block: Any = None,
) -> float:
    """Вычисляет мировую координату плоскости отражения вдоль оси `X`, `Y` или `Z`.

    Режимы `mode`:
    - `"cabinet"` — плоскость симметрии родительского корпуса / блока (или самой детали, если в блоке 1 деталь);
    - `"self_max"` — правый / верхний / передний торец самой детали (`coord + size`);
    - `"self_min"` — левый / нижний / задний торец самой детали (`coord`);
    - `"custom"` — произвольная координата `custom_coord`.
    """
    ax = str(axis or "X").upper().strip()
    if ax not in ("X", "Y", "Z"):
        ax = "X"
    ax_idx = {"X": 0, "Y": 1, "Z": 2}[ax]

    p_coords = (float(panel.x), float(panel.y), float(panel.z))
    p_dims = (float(panel.width), float(panel.height), float(panel.depth))

    if mode == "custom" and custom_coord is not None:
        return float(custom_coord)
    if mode == "self_max":
        return p_coords[ax_idx] + p_dims[ax_idx]
    if mode == "self_min":
        return p_coords[ax_idx]

    # Режим "cabinet": ищем габариты родительского блока
    parent = block if block is not None else getattr(panel, "_block", None)
    if parent is not None:
        coord_attr = ("x", "y", "z")[ax_idx]
        dim_attr = ("width", "height", "depth")[ax_idx]
        b_dim = float(getattr(parent, dim_attr, 0.0) or 0.0)
        if b_dim > 0.0:
            b_coord = float(getattr(parent, coord_attr, 0.0) or 0.0)
            return b_coord + b_dim * 0.5
        panels_in_block = [
            p for p in (getattr(parent, "panels", None) or [])
            if getattr(p, "visible", True)
        ]
        if len(panels_in_block) >= 2:
            lo = min(
                (float(p.x), float(p.y), float(p.z))[ax_idx]
                for p in panels_in_block
            )
            hi = max(
                (float(p.x) + float(p.width), float(p.y) + float(p.height), float(p.z) + float(p.depth))[ax_idx]
                for p in panels_in_block
            )
            if hi > lo:
                return (lo + hi) * 0.5

    # Fallback: отражаем через правый/верхний/передний торец детали
    return p_coords[ax_idx] + p_dims[ax_idx]


def _mirror_panel_holes(holes: list[tuple], axis: str, dims: tuple[float, float, float]) -> list[tuple]:
    """Зеркалит локальные отверстия панели вдоль оси `axis` ('X', 'Y', 'Z')."""
    ax = str(axis or "X").upper()
    w, h, d = dims
    out: list[tuple] = []
    for hole in holes or []:
        if not hole or len(hole) < 6:
            continue
        hx, hy, hz, radius, depth, h_axis = (
            float(hole[0]),
            float(hole[1]),
            float(hole[2]),
            float(hole[3]),
            float(hole[4]),
            str(hole[5] or "X").upper(),
        )
        if ax == "X":
            hx = (w - hx - depth) if h_axis == "X" else (w - hx)
            hx = max(0.0, min(w, hx))
            if h_axis in ("-X", "+X"):
                h_axis = "+X" if h_axis == "-X" else "-X"
        elif ax == "Y":
            hy = (h - hy - depth) if h_axis == "Y" else (h - hy)
            hy = max(0.0, min(h, hy))
            if h_axis in ("-Y", "+Y"):
                h_axis = "+Y" if h_axis == "-Y" else "-Y"
        elif ax == "Z":
            hz = (d - hz - depth) if h_axis == "Z" else (d - hz)
            hz = max(0.0, min(d, hz))
            if h_axis in ("-Z", "+Z"):
                h_axis = "+Z" if h_axis == "-Z" else "-Z"
        # Сохраняем как собственное отверстие детали (6 элементов, без старого joint_uid)
        out.append((round(hx, 4), round(hy, 4), round(hz, 4), radius, depth, h_axis))
    return out


def _mirror_panel_grooves(grooves: list[Any], axis: str, dims: tuple[float, float, float]) -> list[Any]:
    """Зеркалит локальные пазы `(gx, gy, gz, gw, gh, gd)` или словари вдоль оси `axis`."""
    ax = str(axis or "X").upper()
    w, h, d = dims
    out: list[Any] = []
    for g in grooves or []:
        if isinstance(g, dict):
            gd_copy = dict(g)
            face = str(gd_copy.get("face", "") or "").lower()
            if ax == "X" and face in ("left", "right"):
                gd_copy["face"] = "left" if face == "right" else "right"
            elif ax == "Y" and face in ("top", "bottom"):
                gd_copy["face"] = "top" if face == "bottom" else "bottom"
            elif ax == "Z" and face in ("front", "back"):
                gd_copy["face"] = "front" if face == "back" else "back"
            out.append(gd_copy)
            continue
        if not g or len(g) < 6:
            continue
        gx, gy, gz, gw, gh, gd = (
            float(g[0]),
            float(g[1]),
            float(g[2]),
            float(g[3]),
            float(g[4]),
            float(g[5]),
        )
        if ax == "X":
            gx = max(0.0, w - (gx + gw))
        elif ax == "Y":
            gy = max(0.0, h - (gy + gh))
        elif ax == "Z":
            gz = max(0.0, d - (gz + gd))
        out.append((round(gx, 4), round(gy, 4), round(gz, 4), gw, gh, gd))
    return out


def _mirror_panel_edges(edges: dict[str, str] | None, axis: str) -> dict[str, str]:
    """Меняет местами противоположные кромки при зеркальном отражении."""
    base: dict[str, str] = {
        "top": "",
        "bottom": "",
        "left": "",
        "right": "",
    }
    if isinstance(edges, dict):
        for k, v in edges.items():
            base[k] = str(v or "")
    ax = str(axis or "X").upper()
    if ax == "X":
        base["left"], base["right"] = base.get("right", ""), base.get("left", "")
    elif ax == "Y":
        base["top"], base["bottom"] = base.get("bottom", ""), base.get("top", "")
    return base


def build_mirror_panel(
    panel: Panel,
    *,
    axis: str = "X",
    mode: str = "cabinet",
    custom_coord: float | None = None,
    plane_coord: float | None = None,
    mirror_features: bool = True,
    existing_names: set[str] | None = None,
    new_name: str = "",
    pos_num: str = "",
    new_pos_num: str = "",
    block: Any = None,
    rebuild: bool = True,
) -> Panel:
    """Создаёт зеркальную копию `panel` относительно выбранной плоскости отражения."""
    ax = str(axis or "X").upper().strip()
    if ax not in ("X", "Y", "Z"):
        ax = "X"

    if plane_coord is not None:
        plane_val = float(plane_coord)
    else:
        plane_val = compute_mirror_plane_coord(
            panel,
            axis=ax,
            mode=mode,
            custom_coord=custom_coord,
            block=block,
        )

    x, y, z = float(panel.x), float(panel.y), float(panel.z)
    w, h, d = float(panel.width), float(panel.height), float(panel.depth)
    if ax == "X":
        x = 2.0 * plane_val - (x + w)
    elif ax == "Y":
        y = 2.0 * plane_val - (y + h)
    else:
        z = 2.0 * plane_val - (z + d)

    names_pool = existing_names if existing_names is not None else {str(panel.name)}
    final_name = new_name or next_unique_name(panel.name, f"Зеркало {ax}", names_pool)
    final_pos = new_pos_num or pos_num

    clone = panel.clone(
        name=final_name,
        x=round(x, 4),
        y=round(y, 4),
        z=round(z, 4),
        pos_num=final_pos,
        role="",
    )
    # Отвязываем от чужих параметрических стыков
    clone.joint_hole_map = {}

    if mirror_features:
        dims = (w, h, d)
        clone.holes = _mirror_panel_holes(list(getattr(panel, "holes", []) or []), ax, dims)
        clone.grooves = _mirror_panel_grooves(list(getattr(panel, "grooves", []) or []), ax, dims)
        clone.edges = _mirror_panel_edges(getattr(panel, "edges", None), ax)
        # Отражение углов Эйлера для наклонной детали
        rx = float(getattr(panel, "rx", 0.0))
        ry = float(getattr(panel, "ry", 0.0))
        rz = float(getattr(panel, "rz", 0.0))
        if ax == "X":
            clone.ry = -ry
            clone.rz = -rz
        elif ax == "Y":
            clone.rx = -rx
            clone.rz = -rz
        else:
            clone.rx = -rx
            clone.ry = -ry
    else:
        clone.holes = [tuple(h[:6]) for h in (getattr(panel, "holes", []) or []) if h and len(h) >= 6]

    if rebuild:
        clone.rebuild_geometry()
    return clone


def compute_linear_array_offsets(
    panel: Panel,
    *,
    axis: str = "Y",
    count: int = 3,
    spacing_mode: str = "step",
    value_mm: float = 320.0,
) -> list[float]:
    """Вычисляет список координат (по оси `axis`) для `count` элементов линейного массива.

    Режимы `spacing_mode`:
    - `"step"` — фиксированный шаг между копиями (`coord_0 + i * value_mm`, `i = 1..count`);
    - `"clear_gap"` — фиксированный зазор в свету между деталями:
      `step = sign * (size_along_axis + abs(value_mm))`;
    - `"divide_span"` — равномерно делит проём длиной `value_mm` (от начала базовой детали
      или внутри секции) на `count + 1` равных просветов:
      шаг между деталями равен `(value_mm - count * size_along_axis) / (count + 1) + size_along_axis`.
    """
    ax = str(axis or "Y").upper().strip()
    if ax not in ("X", "Y", "Z"):
        ax = "Y"
    ax_idx = {"X": 0, "Y": 1, "Z": 2}[ax]
    n = max(1, min(int(count), 50))

    base_coord = (float(panel.x), float(panel.y), float(panel.z))[ax_idx]
    panel_span = (float(panel.width), float(panel.height), float(panel.depth))[ax_idx]
    val = float(value_mm)

    if spacing_mode == "clear_gap":
        sign = -1.0 if val < 0.0 else 1.0
        step = sign * (panel_span + abs(val))
        return [round(base_coord + i * step, 4) for i in range(1, n + 1)]

    if spacing_mode == "divide_span":
        # Равномерное распределение n деталей внутри проёма длиной abs(val), начиная от base_coord
        span = abs(val)
        sign = -1.0 if val < 0.0 else 1.0
        clear_each = (span - n * panel_span) / float(n + 1)
        pitch = clear_each + panel_span
        return [
            round(base_coord + sign * (clear_each + (i - 1) * pitch), 4)
            for i in range(1, n + 1)
        ]

    # По умолчанию: "step"
    return [round(base_coord + i * val, 4) for i in range(1, n + 1)]


def build_linear_array_panels(
    panel: Panel,
    *,
    axis: str = "Y",
    count: int = 3,
    spacing_mode: str = "step",
    mode: str = "",
    value_mm: float = 320.0,
    value: float | None = None,
    include_ends: bool = False,
    existing_names: set[str] | None = None,
    pos_prefix: str = "1",
    start_pos_index: int = 1,
    rebuild: bool = True,
) -> list[Panel]:
    """Создаёт список из `count` новых панелей линейного массива вдоль оси `axis`."""
    _ = include_ends
    ax = str(axis or "Y").upper().strip()
    if ax not in ("X", "Y", "Z"):
        ax = "Y"

    eff_mode = mode or spacing_mode
    eff_val = float(value) if value is not None else float(value_mm)

    coords = compute_linear_array_offsets(
        panel,
        axis=ax,
        count=count,
        spacing_mode=eff_mode,
        value_mm=eff_val,
    )
    names_pool = existing_names if existing_names is not None else {str(panel.name)}
    out: list[Panel] = []

    for idx, target_c in enumerate(coords, start=1):
        nx, ny, nz = float(panel.x), float(panel.y), float(panel.z)
        if ax == "X":
            nx = target_c
        elif ax == "Y":
            ny = target_c
        else:
            nz = target_c

        new_name = next_unique_name(panel.name, f"Массив {idx}", names_pool)
        pos_str = f"{pos_prefix}.{start_pos_index + idx - 1}" if pos_prefix else ""
        clone = panel.clone(
            name=new_name,
            x=nx,
            y=ny,
            z=nz,
            pos_num=pos_str,
            role="",
        )
        clone.joint_hole_map = {}
        clone.holes = [tuple(h[:6]) for h in (getattr(panel, "holes", []) or []) if h and len(h) >= 6]
        if rebuild:
            clone.rebuild_geometry()
        out.append(clone)

    return out

