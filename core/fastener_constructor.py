"""Модель параметров, формул, статуса изменений (*) и персистентности конструктора крепежа."""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.formula import eval_math_expression
from core.logging_setup import get_logger, user_data_dir

_log = get_logger("fastener_constructor")

FASTENER_FORMULA_FIELDS: tuple[str, ...] = ("d1", "d2", "h", "h1")
FASTENER_FIELD_LABELS: dict[str, str] = {
    "d1": "D1",
    "d2": "D2",
    "h": "H",
    "h1": "H1",
}
FASTENER_FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "d1": (0.1, 100.0),
    "d2": (0.1, 100.0),
    "h": (1.0, 500.0),
    "h1": (0.0, 500.0),
}
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_REL_PREFIXES = ("+=", "-=", "*=", "/=")


def is_fastener_formula(raw: str) -> bool:
    """True, если строка является формулой для поля конструктора (а не простым числом и не разовым +=/-=)."""
    s = str(raw or "").strip()
    if not s:
        return False
    if s.startswith(_REL_PREFIXES):
        return False
    if s.startswith("="):
        return True
    s_norm = _DECIMAL_COMMA_RE.sub(".", s.replace("×", "*").replace("÷", "/"))
    try:
        val = float(s_norm)
    except ValueError:
        return True
    return not math.isfinite(val)


def normalize_fastener_formula(raw: str) -> str:
    """Нормализует текст формулы (убирает пробелы по краям и ведущий знак '=')."""
    s = str(raw or "").strip()
    if s.startswith("="):
        s = s[1:].strip()
    return s


def extract_formula_deps(expr: str) -> set[str]:
    """Возвращает множество полей конструктора (``d1/d2/h/h1``), на которые ссылается формула."""
    norm = normalize_fastener_formula(expr)
    if not norm:
        return set()
    base = norm.replace("×", "*").replace("÷", "/")
    candidates = (
        _DECIMAL_COMMA_RE.sub(".", base).replace(";", ","),
        base.replace(";", ","),
    )
    tree = None
    for cand in candidates:
        try:
            tree = ast.parse(cand, mode="eval")
            break
        except SyntaxError:
            continue
    if tree is None:
        return set()
    deps: set[str] = set()
    field_set = set(FASTENER_FORMULA_FIELDS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id.lower()
            if name in field_set:
                deps.add(name)
    return deps


def detect_formula_cycle(formulas: dict[str, str]) -> list[str] | None:
    """Обнаруживает цикл в зависимостях формул (включая самоссылку). Возвращает путь цикла или None."""
    graph: dict[str, set[str]] = {}
    for fld, expr in (formulas or {}).items():
        key = str(fld).lower()
        if key in FASTENER_FORMULA_FIELDS and str(expr or "").strip():
            graph[key] = extract_formula_deps(str(expr))

    state: dict[str, int] = {}  # 0 = unvisited, 1 = visiting, 2 = done
    stack: list[str] = []

    def _dfs(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            if dep == node:
                return [node, node]
            if dep not in graph:
                continue
            st = state.get(dep, 0)
            if st == 1:
                idx = stack.index(dep)
                return stack[idx:] + [dep]
            if st == 0:
                cyc = _dfs(dep)
                if cyc is not None:
                    return cyc
        stack.pop()
        state[node] = 2
        return None

    for fld in FASTENER_FORMULA_FIELDS:
        if fld in graph and state.get(fld, 0) == 0:
            cyc = _dfs(fld)
            if cyc is not None:
                return cyc
    return None


def _topological_formula_order(formulas: dict[str, str]) -> list[str]:
    """Возвращает порядок вычисления формульных полей (зависимости раньше зависимых)."""
    active = [f for f in FASTENER_FORMULA_FIELDS if f in formulas and str(formulas[f]).strip()]
    active_set = set(active)
    visited: set[str] = set()
    order: list[str] = []

    def _visit(node: str, trail: set[str]) -> None:
        if node in visited or node in trail:
            return
        trail.add(node)
        for dep in sorted(extract_formula_deps(formulas[node])):
            if dep in active_set and dep != node:
                _visit(dep, trail)
        trail.discard(node)
        visited.add(node)
        order.append(node)

    for fld in active:
        _visit(fld, set())
    return order


@dataclass
class ConfirmatParams:
    """Параметры конфирмата (D1 — пласть, D2 — торец, H — длина, H1 — глубина в торец при >0)."""

    name: str = "Конфирмат 7×50 мм, Zn"
    d1: float = 8.0   # диаметр сверления в пласть (сквозное)
    d2: float = 5.0   # диаметр сверления в торец (глухое)
    h: float = 50.0   # общая длина метиза
    h1: float = 0.0   # явная глубина сверления в торец (если > 0; иначе вычисляется от H)
    formulas: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        clean: dict[str, str] = {}
        if isinstance(self.formulas, dict):
            for k, v in self.formulas.items():
                key = str(k).lower().strip()
                norm = normalize_fastener_formula(str(v or ""))
                if key in FASTENER_FORMULA_FIELDS and norm:
                    clean[key] = norm
        self.formulas = clean

    def clone(self) -> "ConfirmatParams":
        return ConfirmatParams(
            str(self.name),
            float(self.d1),
            float(self.d2),
            float(self.h),
            float(self.h1),
            dict(self.formulas),
        )

    def has_formula(self, field_name: str) -> bool:
        return str(field_name).lower() in self.formulas

    def formula_for(self, field_name: str) -> str:
        return self.formulas.get(str(field_name).lower(), "")

    def edge_depth(self, panel_thickness: float = 16.0) -> float:
        """Глубина глухого отверстия в торец (мм), с учётом формул и толщины плиты ``t``."""
        t_val = max(1.0, float(panel_thickness))
        if self.formulas:
            resolved = self.clone()
            errs = recalculate_confirmat_row(resolved, panel_thickness=t_val)
            if not errs:
                if float(resolved.h1) > 0:
                    return max(4.0, round(float(resolved.h1), 2))
                offset = max(8.0, t_val - 4.0)
                return max(12.0, round(float(resolved.h) - offset, 2))
        if float(self.h1) > 0:
            return max(4.0, float(self.h1))
        # Для стандартной плиты 16 мм и H=50 глубина в торец = 38 мм (H - 12)
        offset = max(8.0, t_val - 4.0)
        return max(12.0, round(float(self.h) - offset, 2))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": str(self.name),
            "d1": float(self.d1),
            "d2": float(self.d2),
            "h": float(self.h),
            "h1": float(self.h1),
            "type": "confirmat",
        }
        if self.formulas:
            out["formulas"] = {k: self.formulas[k] for k in FASTENER_FORMULA_FIELDS if k in self.formulas}
        return out

    def to_selected_fastener_dict(self, panel_thickness: float = 16.0) -> dict[str, Any]:
        """Словарь параметров выбранного метиза для Viewport3D, JointRecord и make_joint_holes."""
        resolved = self.clone()
        if resolved.formulas:
            recalculate_confirmat_row(resolved, panel_thickness=panel_thickness)
        d = resolved.to_dict()
        edep = resolved.edge_depth(panel_thickness=panel_thickness)
        d["diameter"] = float(resolved.d1)
        d["depth"] = float(edep)
        d["drill_face_diameter"] = float(resolved.d1)
        d["drill_edge_diameter"] = float(resolved.d2)
        d["drill_edge_depth"] = float(edep)
        d["drill_through"] = True
        d["fastener_type"] = "confirmat"
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfirmatParams":
        if isinstance(data, cls):
            return data.clone()
        raw_formulas = data.get("formulas")
        formulas = raw_formulas if isinstance(raw_formulas, dict) else {}
        obj = cls(
            name=str(data.get("name") or "Конфирмат 7×50 мм, Zn"),
            d1=max(0.1, float(data.get("d1", 8.0))),
            d2=max(0.1, float(data.get("d2", 5.0))),
            h=max(1.0, float(data.get("h", 50.0))),
            h1=max(0.0, float(data.get("h1", 0.0))),
            formulas=formulas,
        )
        if obj.formulas:
            recalculate_confirmat_row(obj, panel_thickness=16.0)
        return obj


def fastener_formula_vars(
    row: ConfirmatParams,
    *,
    panel_thickness: float = 16.0,
) -> dict[str, float]:
    """Словарь переменных для вычисления формул в строке конструктора фурнитуры."""
    return {
        "d1": float(row.d1),
        "d2": float(row.d2),
        "h": float(row.h),
        "h1": float(row.h1),
        "t": max(1.0, float(panel_thickness)),
    }


def recalculate_confirmat_row(
    row: ConfirmatParams,
    *,
    panel_thickness: float = 16.0,
) -> dict[str, str]:
    """Пересчитывает все формульные поля строки ``row`` в топологическом порядке.

    Возвращает словарь ``{field: error_message}`` (пустой, если ошибок нет).
    """
    if not row.formulas:
        return {}

    cycle = detect_formula_cycle(row.formulas)
    if cycle is not None:
        chain = " → ".join(FASTENER_FIELD_LABELS.get(c, c.upper()) for c in cycle)
        msg = f"Циклическая зависимость формул: {chain}"
        return {c: msg for c in cycle[:-1]}

    errors: dict[str, str] = {}
    order = _topological_formula_order(row.formulas)
    for fld in order:
        expr = row.formulas.get(fld, "")
        if not expr:
            continue
        env = fastener_formula_vars(row, panel_thickness=panel_thickness)
        cur_val = float(getattr(row, fld))
        try:
            val = eval_math_expression(expr, current_value=cur_val, variables=env)
        except ValueError as exc:
            errors[fld] = f"{FASTENER_FIELD_LABELS[fld]}: ошибка формулы «{expr}» ({exc})"
            continue
        lo, hi = FASTENER_FIELD_BOUNDS[fld]
        if val < lo or val > hi:
            errors[fld] = (
                f"{FASTENER_FIELD_LABELS[fld]}={val:g} вне допустимого диапазона [{lo:g}..{hi:g}]"
            )
            continue
        setattr(row, fld, round(float(val), 3))
    return errors


def apply_fastener_cell_input(
    row: ConfirmatParams,
    field_name: str,
    raw: str,
    *,
    panel_thickness: float = 16.0,
) -> tuple[bool, str]:
    """Применяет пользовательский ввод (число, формулу или +=/-=) к полю строки ``row``.

    При любой ошибке (синтаксис, цикл, выход за границы, поломка зависимого поля)
    выполняет полный откат ``row`` и возвращает ``(False, message)``.
    """
    fld = str(field_name).lower().strip()
    if fld not in FASTENER_FORMULA_FIELDS:
        return False, f"Неизвестное поле: {field_name}"

    text = str(raw or "").strip()
    backup = row.clone()

    def _rollback(msg: str) -> tuple[bool, str]:
        row.name = backup.name
        row.d1 = backup.d1
        row.d2 = backup.d2
        row.h = backup.h
        row.h1 = backup.h1
        row.formulas = dict(backup.formulas)
        return False, msg

    if not text:
        if fld == "h1":
            row.h1 = 0.0
            row.formulas.pop("h1", None)
            errs = recalculate_confirmat_row(row, panel_thickness=panel_thickness)
            if errs:
                return _rollback(next(iter(errs.values())))
            return True, ""
        return _rollback(f"Поле {FASTENER_FIELD_LABELS[fld]} не может быть пустым")

    lo, hi = FASTENER_FIELD_BOUNDS[fld]
    env = fastener_formula_vars(row, panel_thickness=panel_thickness)
    cur_val = float(getattr(row, fld))

    # 1. Одноразовое относительное приращение (+=, -=, *=, /=): вычисляем и снимаем формулу
    if text.startswith(_REL_PREFIXES):
        try:
            val = eval_math_expression(text, current_value=cur_val, variables=env)
        except ValueError as exc:
            return _rollback(f"{FASTENER_FIELD_LABELS[fld]}: ошибка выражения «{text}» ({exc})")
        if val < lo or val > hi:
            return _rollback(
                f"{FASTENER_FIELD_LABELS[fld]}={val:g} вне допустимого диапазона [{lo:g}..{hi:g}]"
            )
        row.formulas.pop(fld, None)
        setattr(row, fld, round(float(val), 3))
        errs = recalculate_confirmat_row(row, panel_thickness=panel_thickness)
        if errs:
            return _rollback(next(iter(errs.values())))
        return True, ""

    # 2. Персистентная формула (=H - 12, D1 - 3, H - t + 4, ...)
    if is_fastener_formula(text):
        norm = normalize_fastener_formula(text)
        if not norm:
            return _rollback(f"{FASTENER_FIELD_LABELS[fld]}: пустая формула")
        row.formulas[fld] = norm
        errs = recalculate_confirmat_row(row, panel_thickness=panel_thickness)
        if errs:
            return _rollback(next(iter(errs.values())))
        return True, ""

    # 3. Обычное число — записываем значение и снимаем формулу с этого поля
    try:
        val = eval_math_expression(text, current_value=cur_val, variables=env)
    except ValueError as exc:
        return _rollback(f"{FASTENER_FIELD_LABELS[fld]}: неверное число «{text}» ({exc})")
    if val < lo or val > hi:
        return _rollback(
            f"{FASTENER_FIELD_LABELS[fld]}={val:g} вне допустимого диапазона [{lo:g}..{hi:g}]"
        )
    row.formulas.pop(fld, None)
    setattr(row, fld, round(float(val), 3))
    errs = recalculate_confirmat_row(row, panel_thickness=panel_thickness)
    if errs:
        return _rollback(next(iter(errs.values())))
    return True, ""


def validate_confirmat_row(
    row: ConfirmatParams,
    *,
    panel_thickness: float = 16.0,
) -> list[str]:
    """Возвращает список инженерных предупреждений для строки конфирмата (не блокирующих сохранение)."""
    warnings: list[str] = []
    if row.d2 > row.d1:
        warnings.append(f"D2 ({row.d2:g} мм) больше D1 ({row.d1:g} мм)")
    eff_depth = row.edge_depth(panel_thickness=panel_thickness)
    if row.h1 > 0 and row.h1 > row.h:
        warnings.append(f"Глубина H1 ({row.h1:g} мм) превышает длину H ({row.h:g} мм)")
    elif eff_depth > row.h:
        warnings.append(f"Глубина в торец ({eff_depth:g} мм) превышает длину H ({row.h:g} мм)")
    return warnings


def compute_rows_dirty_state(
    current_rows: list[ConfirmatParams],
    saved_rows: list[ConfirmatParams],
    *,
    panel_thickness: float = 16.0,
) -> tuple[bool, set[int]]:
    """Сравнивает текущий список строк с последним сохранённым снимком.

    Возвращает ``(is_dirty, dirty_row_indices)`` для отображения статуса ``*`` в заголовке и таблице.
    При сравнении формульные строки приводятся к одной толщине ``panel_thickness``, чтобы смена
    толщины плиты в предпросмотре не помечала неизменённые строки как несохранённые.
    """
    def _canonical(row: ConfirmatParams) -> dict[str, Any]:
        c = row.clone()
        if c.formulas:
            recalculate_confirmat_row(c, panel_thickness=panel_thickness)
        return c.to_dict()

    dirty_indices: set[int] = set()
    saved_dicts = [_canonical(r) for r in (saved_rows or [])]
    for idx, row in enumerate(current_rows or []):
        if idx >= len(saved_dicts) or _canonical(row) != saved_dicts[idx]:
            dirty_indices.add(idx)
    is_dirty = bool(dirty_indices) or len(current_rows or []) != len(saved_dicts)
    return is_dirty, dirty_indices


def format_constructor_title(base_title: str, is_dirty: bool) -> str:
    """Форматирует заголовок окна конструктора с индикатором несохранённых изменений ``*``."""
    clean = str(base_title or "").rstrip(" *")
    return f"{clean} *" if is_dirty else clean


def format_row_number_label(index: int, is_dirty: bool) -> str:
    """Форматирует номер строки в колонке ``№`` (с суффиксом ``*`` для изменённой строки)."""
    return f"{int(index) + 1}*" if is_dirty else str(int(index) + 1)


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
