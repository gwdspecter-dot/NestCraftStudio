"""Диалоги создания панели и присадки."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QCheckBox,
    QDialogButtonBox,
    QVBoxLayout,
    QLabel,
)

from PyQt6.QtGui import QValidator
from core.formula import context_vars_from_object, eval_math_expression
from core.logging_setup import get_logger

_log = get_logger("dialogs")


class SmartDoubleSpinBox(QDoubleSpinBox):
    """Числовое поле с поддержкой ввода арифметических формул (`600 - 32`, `720 / 3`, `+= 16`)."""

    _ALLOWED_CHARS = frozenset("0123456789.,+-*/()= \t×÷abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def __init__(self, parent=None, context_obj=None):
        super().__init__(parent)
        self._context_obj = context_obj
        self.setToolTip("Поддерживаются числа и формулы: например, 600 - 32, 720 / 3, (800 - 48) / 2")

    def validate(self, text: str, pos: int):
        s = (text or "").strip()
        if not s:
            return (QValidator.State.Intermediate, text, pos)
        if any(ch not in self._ALLOWED_CHARS for ch in s):
            return (QValidator.State.Invalid, text, pos)
        try:
            env = context_vars_from_object(self._context_obj, current_value=float(self.value()))
            val = eval_math_expression(s, current_value=float(self.value()), variables=env)
            if self.minimum() <= val <= self.maximum():
                return (QValidator.State.Acceptable, text, pos)
            return (QValidator.State.Intermediate, text, pos)
        except ValueError:
            return (QValidator.State.Intermediate, text, pos)

    def valueFromText(self, text: str) -> float:
        try:
            env = context_vars_from_object(self._context_obj, current_value=float(self.value()))
            val = eval_math_expression(text, current_value=float(self.value()), variables=env)
            return min(max(val, float(self.minimum())), float(self.maximum()))
        except ValueError:
            return float(self.value())



class CreatePanelDialog(QDialog):
    """Окно ввода размеров и координат новой панели."""

    def __init__(self, panel_type: str, default_x=0.0, default_y=0.0, default_z=0.0, parent=None):
        super().__init__(parent)
        self.panel_type = panel_type

        titles = {
            "vertical": "Создание вертикальной панели (Боковина / Перегородка)",
            "horizontal": "Создание горизонтальной панели (Дно / Крышка / Полка)",
            "frontal": "Создание фронтальной панели (Фасад / Задняя стенка)",
        }
        self.setWindowTitle(titles.get(panel_type, "Создание панели"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit("Панель")
        form.addRow("Наименование:", self.name_edit)

        # Толщина только из материала каталога — спиннер read-only
        default_t = 16.0
        try:
            from core.catalog import CatalogService
            mat = CatalogService.instance().default_material()
            if mat is not None and float(mat.thickness_mm) > 0:
                default_t = float(mat.thickness_mm)
        except Exception:
            _log.exception("Не удалось получить толщину материала по умолчанию из каталога")
            default_t = 16.0
        self.thick_spin = self._make_spin(default_t)
        self.thick_spin.setReadOnly(True)
        self.thick_spin.setEnabled(False)
        self.thick_spin.setToolTip("Толщина задаётся материалом из каталога")
        self.dim1_spin = self._make_spin(720.0)
        self.dim2_spin = self._make_spin(560.0)

        if panel_type == "vertical":
            form.addRow("Толщина (по оси X), мм — из материала:", self.thick_spin)
            form.addRow("Высота (по оси Y), мм:", self.dim1_spin)
            form.addRow("Глубина (по оси Z), мм:", self.dim2_spin)
        elif panel_type == "horizontal":
            form.addRow("Ширина (по оси X), мм:", self.dim1_spin)
            form.addRow("Толщина (по оси Y), мм — из материала:", self.thick_spin)
            form.addRow("Глубина (по оси Z), мм:", self.dim2_spin)
        else:
            form.addRow("Ширина (по оси X), мм:", self.dim2_spin)
            form.addRow("Высота (по оси Y), мм:", self.dim1_spin)
            form.addRow("Толщина (по оси Z), мм — из материала:", self.thick_spin)

        self.x_spin = self._make_spin(default_x, min_val=-10000.0)
        self.y_spin = self._make_spin(default_y, min_val=-10000.0)
        self.z_spin = self._make_spin(default_z, min_val=-10000.0)
        form.addRow("Координата X (слева), мм:", self.x_spin)
        form.addRow("Координата Y (снизу), мм:", self.y_spin)
        form.addRow("Координата Z (сзади), мм:", self.z_spin)

        self.groove_cb = QCheckBox("Вырезать паз 4х6 мм под ХДФ (сзади)")
        form.addRow("", self.groove_cb)

        layout.addLayout(form)

        hint = QLabel("💡 После создания панель можно двигать стрелками (← → ↑ ↓ и PgUp/PgDn)")
        hint.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _make_spin(val: float, min_val=1.0, max_val=10000.0) -> QDoubleSpinBox:
        sb = SmartDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setDecimals(1)
        sb.setValue(val)
        return sb

    def get_panel_data(self) -> dict:
        t = self.thick_spin.value()
        d1 = self.dim1_spin.value()
        d2 = self.dim2_spin.value()

        if self.panel_type == "vertical":
            w, h, d = t, d1, d2
        elif self.panel_type == "horizontal":
            w, h, d = d1, t, d2
        else:
            w, h, d = d2, d1, t

        return {
            "name": f"{self.name_edit.text()} ({int(w)}x{int(h)}x{int(d)})",
            "x": self.x_spin.value(),
            "y": self.y_spin.value(),
            "z": self.z_spin.value(),
            "width": w,
            "height": h,
            "depth": d,
            "has_groove": self.groove_cb.isChecked(),
        }


class HoleDialog(QDialog):
    """Добавление отверстия присадки на выбранную панель.

    Шаблоны берутся из каталога крепежа (CatalogService).
    Показываются правила сверления в пласть и в торец.
    """

    # Fallback, если каталог недоступен
    _FALLBACK = [
        {"id": "", "label": "Евровинт Ø7 × 50", "dia": 7.0, "depth": 50.0, "axis": "X",
         "face_dia": 7.0, "face_depth": 0.0, "edge_dia": 5.0, "edge_depth": 38.0},
        {"id": "", "label": "Шкант Ø8 × 30", "dia": 8.0, "depth": 30.0, "axis": "X",
         "face_dia": 8.0, "face_depth": 12.0, "edge_dia": 8.0, "edge_depth": 18.0},
        {"id": "", "label": "Свой размер", "dia": 8.0, "depth": 30.0, "axis": "X",
         "face_dia": 8.0, "face_depth": 30.0, "edge_dia": 8.0, "edge_depth": 30.0},
    ]

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle(f"Присадка — {panel.name}")
        self.setMinimumWidth(440)

        self._presets: list[dict] = self._load_presets()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # ── Шаблон из каталога ────────────────────────────────
        self.preset = QComboBox()
        for p in self._presets:
            self.preset.addItem(p["label"], p["id"])
        self.preset.currentIndexChanged.connect(self._on_preset_index)
        form.addRow("Крепёж (каталог):", self.preset)

        # ── Параметры отверстия ───────────────────────────────
        self.diameter = self._make_spin(7.0, min_val=1.0, max_val=50.0)
        self.depth = self._make_spin(50.0, min_val=1.0, max_val=200.0)
        form.addRow("Диаметр, мм:", self.diameter)
        form.addRow("Глубина, мм:", self.depth)

        self.axis = QComboBox()
        self.axis.addItems(["X", "Y", "Z"])
        form.addRow("Ось сверления:", self.axis)

        # ── Инфо о правилах сверления ─────────────────────────
        self.rules_label = QLabel("")
        self.rules_label.setWordWrap(True)
        self.rules_label.setStyleSheet(
            "color: #444; font-size: 11px; background: #f5f5f5; "
            "padding: 6px 8px; border-radius: 4px;"
        )
        form.addRow("Правила:", self.rules_label)

        # ── Позиция ───────────────────────────────────────────
        self.hx = self._make_spin(max(0.0, panel.width / 2), min_val=-1000, max_val=10000)
        self.hy = self._make_spin(max(0.0, panel.height / 2), min_val=-1000, max_val=10000)
        self.hz = self._make_spin(0.0, min_val=-1000, max_val=10000)
        form.addRow("Позиция X (локально), мм:", self.hx)
        form.addRow("Позиция Y (локально), мм:", self.hy)
        form.addRow("Позиция Z (локально), мм:", self.hz)

        layout.addLayout(form)

        hint = QLabel(
            "Координаты в системе панели (0,0,0 — угол).\n"
            "Ось — направление сверла от точки входа. Ядро вычитает цилиндр из B-Rep."
        )
        hint.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self._presets:
            self._on_preset_index(0)

    # ── data ──────────────────────────────────────────────────

    @staticmethod
    def _load_presets() -> list[dict]:
        """Загружает крепёж из каталога; при ошибке — fallback."""
        try:
            from core.catalog import CatalogService
            cat = CatalogService.instance()
            types = {t.id: t for t in cat.list_fastener_types()}
            result = []
            for f in cat.list_fasteners(active_only=True):
                type_name = types.get(f.type_id)
                type_label = type_name.name if type_name else f.name
                # Для ручной присадки: диаметр/глубина по пласти (типичный случай)
                dia = f.drill_face_diameter or f.diameter_mm
                depth = f.drill_face_depth if f.drill_face_depth > 0 else f.length_mm
                # Ось по умолчанию: Z для минификса (эксцентрик в пласть), иначе X
                axis = "Z" if (type_name and type_name.code in ("minifix", "rafix")) else "X"
                result.append({
                    "id": f.id,
                    "label": f"{type_label} · {f.display_name}",
                    "dia": dia,
                    "depth": depth if depth > 0 else f.length_mm,
                    "axis": axis,
                    "face_dia": f.drill_face_diameter or f.diameter_mm,
                    "face_depth": f.drill_face_depth,
                    "edge_dia": f.drill_edge_diameter or f.diameter_mm,
                    "edge_depth": f.drill_edge_depth,
                    "through": f.drill_through,
                    "spacing": f.recommended_spacing_mm,
                })
            # «Свой размер» всегда в конце
            result.append({
                "id": "",
                "label": "Свой размер",
                "dia": 8.0,
                "depth": 30.0,
                "axis": "X",
                "face_dia": 8.0,
                "face_depth": 30.0,
                "edge_dia": 8.0,
                "edge_depth": 30.0,
                "through": False,
                "spacing": 64.0,
            })
            return result if result else list(HoleDialog._FALLBACK)
        except Exception:
            _log.exception("Не удалось загрузить пресеты крепежа из каталога, используется резервный список")
            return list(HoleDialog._FALLBACK)

    def _current_preset(self) -> dict | None:
        idx = self.preset.currentIndex()
        if 0 <= idx < len(self._presets):
            return self._presets[idx]
        return None

    def _on_preset_index(self, index: int):
        if index < 0 or index >= len(self._presets):
            return
        p = self._presets[index]
        self.diameter.setValue(float(p["dia"]))
        self.depth.setValue(float(p["depth"]))
        self.axis.setCurrentText(p.get("axis", "X"))

        face_d = p.get("face_dia", p["dia"])
        face_h = p.get("face_depth", 0)
        edge_d = p.get("edge_dia", p["dia"])
        edge_h = p.get("edge_depth", 0)
        through = p.get("through", False)
        spacing = p.get("spacing", 64)

        face_txt = (
            f"пласт: Ø{face_d:g}" + (" сквозное" if through or face_h <= 0 else f" × {face_h:g} мм")
        )
        edge_txt = f"торец: Ø{edge_d:g} × {edge_h:g} мм" if edge_h > 0 else f"торец: Ø{edge_d:g}"
        self.rules_label.setText(
            f"{face_txt}\n{edge_txt}\nрекомендуемый шаг: {spacing:g} мм"
        )

    def _make_spin(self, val: float, min_val=1.0, max_val=10000.0) -> QDoubleSpinBox:
        sb = SmartDoubleSpinBox(context_obj=getattr(self, "panel", None))
        sb.setRange(min_val, max_val)
        sb.setDecimals(1)
        sb.setValue(val)
        return sb

    def get_hole(self) -> tuple:
        """Кортеж для panel.holes: (hx, hy, hz, radius, depth, axis)."""
        return (
            self.hx.value(),
            self.hy.value(),
            self.hz.value(),
            self.diameter.value() / 2.0,
            self.depth.value(),
            self.axis.currentText(),
        )

    def get_fastener_id(self) -> str:
        """id крепежа из каталога (пустая строка для «Свой размер»)."""
        p = self._current_preset()
        return (p or {}).get("id", "") or ""
