"""
Dataclass-модели каталога материалов и крепежа NestCraft.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Supplier:
    id: str
    name: str
    country: str = ""
    website: str = ""
    notes: str = ""
    is_active: bool = True


@dataclass
class MaterialCategory:
    id: str
    name: str
    parent_id: Optional[str] = None
    sort_order: int = 0


@dataclass
class CatalogGroup:
    """Узел дерева групп каталога (папки / разделы)."""
    id: str
    name: str
    parent_id: Optional[str] = None
    sort_order: int = 0
    scope: str = "all"          # material | edge | fastener | all
    is_builtin: bool = True


@dataclass
class Material:
    """Листовой материал (ЛДСП, МДФ, ХДФ, фанера и т.д.)."""
    id: str
    sku: str
    name: str
    category_id: str
    material_type: str          # ldsp | mdf | hdf | plywood | solid | other
    thickness_mm: float
    group_id: Optional[str] = None
    supplier_id: Optional[str] = None
    density: float = 0.0        # кг/м³
    color_name: str = ""
    color_rgb: Tuple[float, float, float] = (0.88, 0.85, 0.80)
    texture_path: str = ""
    grain_direction: str = "none"  # none | length | width
    price_per_m2: float = 0.0
    currency: str = "RUB"
    max_drill_depth_face: float = 0.0
    max_drill_depth_edge: float = 0.0
    is_builtin: bool = True
    is_active: bool = True
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Человекочитаемое имя для UI: «МИСТ VL 16 мм»."""
        return f"{self.name} {self.thickness_mm:g} мм"

    @property
    def color(self) -> Tuple[float, float, float]:
        return self.color_rgb


@dataclass
class EdgeBand:
    """Кромка (ПВХ, АБС, меламин…)."""
    id: str
    sku: str
    name: str
    material_type: str          # pvc | abs | melamine | acrylic | other
    thickness_mm: float
    width_mm: float
    group_id: Optional[str] = None
    supplier_id: Optional[str] = None
    color_name: str = ""
    color_rgb: Tuple[float, float, float] = (0.9, 0.9, 0.9)
    texture_path: str = ""
    price_per_m: float = 0.0
    currency: str = "RUB"
    is_builtin: bool = True
    is_active: bool = True
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.thickness_mm:g}×{self.width_mm:g} мм"


@dataclass
class FastenerType:
    id: str
    code: str                   # confirmat | dowel | minifix | rafix | shelf_support | other
    name: str
    description: str = ""


@dataclass
class Fastener:
    """Крепёж с правилами сверления."""
    id: str
    sku: str
    name: str
    type_id: str
    diameter_mm: float
    length_mm: float
    group_id: Optional[str] = None
    supplier_id: Optional[str] = None
    head_diameter_mm: float = 0.0
    # Сверление в пласть
    drill_face_diameter: float = 0.0
    drill_face_depth: float = 0.0
    # Сверление в торец
    drill_edge_diameter: float = 0.0
    drill_edge_depth: float = 0.0
    drill_through: bool = False
    min_panel_thickness: float = 0.0
    max_panel_thickness: float = 0.0
    recommended_spacing_mm: float = 64.0
    mesh_params: str = "{}"     # JSON для параметрического 3D-превью
    price: float = 0.0
    currency: str = "RUB"
    pack_qty: int = 1
    is_builtin: bool = True
    is_active: bool = True
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def display_name(self) -> str:
        return f"{self.name} Ø{self.diameter_mm:g}×{self.length_mm:g}"
