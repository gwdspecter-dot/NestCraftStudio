"""Сохранение и загрузка проекта NestCraft (.b3d JSON), миграции, автосохранение и недавние файлы (план §2.8)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from models.panel import Panel, Block, ParametricCabinet, new_uid
from core.logging_setup import get_logger, user_data_dir
from core.version import FORMAT_VERSION, MIN_SUPPORTED_VERSION

_log = get_logger("project_io")

FILE_FILTER = "NestCraft проект (*.b3d);;JSON (*.json);;Все файлы (*.*)"
MAX_RECENT_FILES = 10
_EDGE_SIDES = ("top", "bottom", "left", "right")


def _parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for p in str(v or "0").strip().lstrip("vV").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def version_cmp(a: str, b: str) -> int:
    """-1 if a<b, 0 if equal, 1 if a>b."""
    aa, bb = _parse_version(a), _parse_version(b)
    n = max(len(aa), len(bb))
    aa += (0,) * (n - len(aa))
    bb += (0,) * (n - len(bb))
    if aa < bb:
        return -1
    if aa > bb:
        return 1
    return 0


# ── Цепочка миграций формата .b3d (план §2.8) ─────────────────


def _iter_panel_dicts(data: dict):
    """Итерирует по всем словарям панелей внутри блоков проекта."""
    for bd in data.get("blocks", []) or []:
        if not isinstance(bd, dict):
            continue
        for pd in bd.get("panels", []) or []:
            if isinstance(pd, dict):
                yield bd, pd


def _migrate_to_0_0_2(data: dict) -> dict:
    """v0.0.1 -> v0.0.2: нормализация корневых полей blocks, grooves, holes."""
    if not isinstance(data.get("blocks"), list):
        data["blocks"] = []
    for _bd, pd in _iter_panel_dicts(data):
        pd.setdefault("grooves", [])
        pd.setdefault("holes", [])
        pd.setdefault("pos_num", "")
        pd.setdefault("code", "")
    return data


def _migrate_to_0_0_3(data: dict) -> dict:
    """v0.0.2 -> v0.0.3: добавление канонического поля material_id на панелях."""
    for _bd, pd in _iter_panel_dicts(data):
        pd.setdefault("material_id", "")
        pd.setdefault("material", "")
    return data


def _migrate_to_0_0_4(data: dict) -> dict:
    """v0.0.3 -> v0.0.4: добавление углов поворота (rx, ry, rz) и словаря кромок edges."""
    for _bd, pd in _iter_panel_dicts(data):
        pd.setdefault("rx", 0.0)
        pd.setdefault("ry", 0.0)
        pd.setdefault("rz", 0.0)
        raw_edges = pd.get("edges")
        norm_edges = {s: "" for s in _EDGE_SIDES}
        if isinstance(raw_edges, dict):
            for s in _EDGE_SIDES:
                if s in raw_edges and raw_edges[s] is not None:
                    norm_edges[s] = str(raw_edges[s])
        pd["edges"] = norm_edges
    return data


def _migrate_to_0_0_5(data: dict) -> dict:
    """v0.0.4 -> v0.0.5: вычисление thickness_axis по минимальному габариту и role для деталей корпуса."""
    for bd, pd in _iter_panel_dicts(data):
        if "thickness_axis" not in pd or pd.get("thickness_axis") is None:
            try:
                w = float(pd.get("width", 100))
                h = float(pd.get("height", 100))
                d = float(pd.get("depth", 16))
                dims = (w, h, d)
                pd["thickness_axis"] = int(min(range(3), key=lambda i: dims[i]))
            except (TypeError, ValueError):
                pd["thickness_axis"] = 0
        else:
            try:
                pd["thickness_axis"] = int(pd["thickness_axis"]) % 3
            except (TypeError, ValueError):
                pd["thickness_axis"] = 0

        if not pd.get("role"):
            if bd.get("type") == "cabinet":
                inferred = ParametricCabinet._infer_role_from_name(str(pd.get("name") or ""))
                pd["role"] = inferred or ""
            else:
                pd["role"] = ""
    return data


def _migrate_to_0_0_6(data: dict) -> dict:
    """v0.0.5 -> v0.0.6: назначение стабильных uid блокам/панелям и поля missing_material_id / missing_edges."""
    for bd in data.get("blocks", []) or []:
        if not isinstance(bd, dict):
            continue
        if not str(bd.get("uid") or "").strip():
            bd["uid"] = new_uid()
        for pd in bd.get("panels", []) or []:
            if not isinstance(pd, dict):
                continue
            if not str(pd.get("uid") or "").strip():
                pd["uid"] = new_uid()
            pd.setdefault("missing_material_id", "")
            if not isinstance(pd.get("missing_edges"), dict):
                pd["missing_edges"] = {}
    return data


def _migrate_to_0_0_7(data: dict) -> dict:
    """v0.0.6 -> v0.0.7: добавление списка параметрических стыков `joints` в блоки (ревизия 2, п. 3.1)."""
    from core.joint import JointRecord

    for bd in data.get("blocks", []) or []:
        if not isinstance(bd, dict):
            continue
        raw_joints = bd.get("joints")
        if not isinstance(raw_joints, list):
            bd["joints"] = []
        else:
            norm_joints = []
            for jd in raw_joints:
                if isinstance(jd, dict):
                    norm_joints.append(JointRecord.from_dict(jd).to_dict())
            bd["joints"] = norm_joints
    return data


def _migrate_to_0_0_8(data: dict) -> dict:
    """v0.0.7 -> v0.0.8: метка joint_uid (7-й элемент) на отверстиях стыка (ревизия 3 §1.2).

    Если у панели есть joint_hole_map, отверстия, совпадающие по геометрии с
    записями карты, получают uid стыка. Несовпавшие остаются ручными (6 полей).
    """
    from core.joint import holes_equal

    for bd in data.get("blocks", []) or []:
        if not isinstance(bd, dict):
            continue
        for pd in bd.get("panels", []) or []:
            if not isinstance(pd, dict):
                continue
            jmap = pd.get("joint_hole_map") or {}
            if not isinstance(jmap, dict) or not jmap:
                continue
            holes = list(pd.get("holes") or [])
            # копии списков карты для однократного сопоставления
            remaining = {
                str(k): [tuple(h[:6]) for h in (v or []) if len(h) >= 6]
                for k, v in jmap.items()
                if k and v
            }
            new_holes = []
            new_map: dict[str, list] = {k: [] for k in remaining}
            for h in holes:
                if not h or len(h) < 6:
                    new_holes.append(h)
                    continue
                # уже с меткой
                if len(h) >= 7 and str(h[6] or "").strip():
                    uid = str(h[6]).strip()
                    new_holes.append(list(h[:6]) + [uid])
                    new_map.setdefault(uid, []).append(list(h[:6]) + [uid])
                    continue
                h6 = tuple(h[:6])
                matched_uid = None
                for uid, lst in remaining.items():
                    for idx, jh in enumerate(lst):
                        if holes_equal(h6, jh):
                            matched_uid = uid
                            lst.pop(idx)
                            break
                    if matched_uid:
                        break
                if matched_uid:
                    tagged = list(h6) + [matched_uid]
                    new_holes.append(tagged)
                    new_map.setdefault(matched_uid, []).append(tagged)
                else:
                    new_holes.append(list(h6))
            pd["holes"] = new_holes
            # обновить карту с метками
            pd["joint_hole_map"] = {
                uid: holes for uid, holes in new_map.items() if holes
            }
    return data


def _migrate_to_0_0_10(data: dict) -> dict:
    """v0.0.9 -> v0.0.10: персистентные формулы `drivers` на панелях."""
    for bd in data.get("blocks") or []:
        if not isinstance(bd, dict):
            continue
        for pd in bd.get("panels") or []:
            if isinstance(pd, dict) and not isinstance(pd.get("drivers"), dict):
                pd["drivers"] = {}
    return data


def _migrate_to_0_0_9(data: dict) -> dict:
    """v0.0.8 -> v0.0.9: ассоциативные ссылки `assoc_refs` на блоках."""
    for bd in data.get("blocks", []) or []:
        if not isinstance(bd, dict):
            continue
        raw = bd.get("assoc_refs")
        if not isinstance(raw, list):
            bd["assoc_refs"] = []
        else:
            from core.assoc import AssocRef

            norm = []
            for item in raw:
                if isinstance(item, dict):
                    norm.append(AssocRef.from_dict(item).to_dict())
            bd["assoc_refs"] = norm
        for pd in bd.get("panels", []) or []:
            if isinstance(pd, dict) and not isinstance(pd.get("assoc_hole_map"), dict):
                pd["assoc_hole_map"] = {}
    return data


MIGRATION_STEPS: list[tuple[str, str, Callable[[dict], dict]]] = [
    ("0.0.1", "0.0.2", _migrate_to_0_0_2),
    ("0.0.2", "0.0.3", _migrate_to_0_0_3),
    ("0.0.3", "0.0.4", _migrate_to_0_0_4),
    ("0.0.4", "0.0.5", _migrate_to_0_0_5),
    ("0.0.5", "0.0.6", _migrate_to_0_0_6),
    ("0.0.6", "0.0.7", _migrate_to_0_0_7),
    ("0.0.7", "0.0.8", _migrate_to_0_0_8),
    ("0.0.8", "0.0.9", _migrate_to_0_0_9),
    ("0.0.9", "0.0.10", _migrate_to_0_0_10),
]


def migrate_project_dict(data: dict, *, in_place: bool = False) -> tuple[dict, list[str]]:
    """Прогоняет словарь проекта по цепочке миграций до текущей FORMAT_VERSION.

    Возвращает (migrated_dict, applied_steps), где applied_steps — список строк вида
    '0.0.4 -> 0.0.5'. Если версия файла уже равна или новее FORMAT_VERSION,
    шаги не применяются.
    """
    if not isinstance(data, dict):
        raise ValueError("Некорректный файл проекта")
    out = data if in_place else copy.deepcopy(data)
    raw_ver = str(out.get("version") or "0.0.1").strip() or "0.0.1"
    if version_cmp(raw_ver, FORMAT_VERSION) >= 0:
        return out, []

    cur_ver = raw_ver
    applied: list[str] = []
    for _src_ver, dst_ver, step_fn in MIGRATION_STEPS:
        if version_cmp(cur_ver, dst_ver) < 0:
            out = step_fn(out)
            applied.append(f"{cur_ver} -> {dst_ver}")
            cur_ver = dst_ver
            out["version"] = dst_ver

    return out, applied


# ── Сериализация панелей и блоков ─────────────────────────────


def _panel_to_dict(p: Panel) -> dict:
    out = {
        "uid": getattr(p, "uid", "") or "",
        "name": p.name,
        "pos_num": p.pos_num,
        "code": p.code,
        "role": getattr(p, "role", "") or "",
        "x": p.x,
        "y": p.y,
        "z": p.z,
        "rx": getattr(p, "rx", 0.0),
        "ry": getattr(p, "ry", 0.0),
        "rz": getattr(p, "rz", 0.0),
        "width": p.width,
        "height": p.height,
        "depth": p.depth,
        "thickness_axis": int(getattr(p, "thickness_axis", 0)) % 3,
        "material_id": getattr(p, "material_id", "") or "",
        # Исходный id из файла, если материал не найден в каталоге (не теряем ссылку)
        "missing_material_id": getattr(p, "missing_material_id", "") or "",
        "material": p.material,  # display name (для читаемости и старых инструментов)
        "color": list(p.color),
        "edges": dict(getattr(p, "edges", {}) or {}),
        "missing_edges": dict(getattr(p, "missing_edges", {}) or {}),
        "grooves": [list(g) for g in p.grooves],
        "holes": [list(h) for h in p.holes],  # 6 полей + опционально joint_uid
    }
    jmap = getattr(p, "joint_hole_map", None) or {}
    if isinstance(jmap, dict) and jmap:
        out["joint_hole_map"] = {
            str(k): [list(h) for h in (v or [])]
            for k, v in jmap.items()
            if k and v
        }
    amap = getattr(p, "assoc_hole_map", None) or {}
    if isinstance(amap, dict) and amap:
        out["assoc_hole_map"] = {
            str(k): [list(h) for h in (v or [])]
            for k, v in amap.items()
            if k and v
        }
    drivers = getattr(p, "drivers", None) or {}
    if isinstance(drivers, dict) and drivers:
        out["drivers"] = {
            str(k): str(v)
            for k, v in drivers.items()
            if k and v is not None and str(v).strip()
        }
    return out


def _panel_from_dict(d: dict) -> Panel:
    from core.scene_controller import SceneController

    ctrl = SceneController.instance()
    ctrl.bind_to_panel_class()
    return Panel.from_dict(d, rebuild=True)


def _block_to_dict(b: Block) -> dict:
    data = {
        "type": "cabinet" if isinstance(b, ParametricCabinet) else "block",
        "uid": getattr(b, "uid", "") or "",
        "name": b.name,
        "pos_num": b.pos_num,
        "code": b.code,
        "panels": [_panel_to_dict(p) for p in b.panels],
        "joints": [
            jr.to_dict() if hasattr(jr, "to_dict") else dict(jr)
            for jr in (getattr(b, "joints", None) or [])
        ],
        "assoc_refs": [
            ar.to_dict() if hasattr(ar, "to_dict") else dict(ar)
            for ar in (getattr(b, "assoc_refs", None) or [])
        ],
    }
    if isinstance(b, ParametricCabinet):
        data["params"] = {
            "x": b.x,
            "y": b.y,
            "z": b.z,
            "width": b.width,
            "height": b.height,
            "depth": b.depth,
            "thickness": b.thickness,
            "shelves_count": b.shelves_count,
            "has_facade": b.has_facade,
            "is_upper": b.is_upper,
            "has_groove": b.has_groove,
        }
    return data


def _block_from_dict(d: dict) -> Block:
    from core.assoc import AssocRef, apply_assoc_refs
    from core.joint import JointRecord, apply_joints

    btype = d.get("type", "block")
    panels_data = d.get("panels", [])
    raw_joints = d.get("joints") or []
    joints = [
        jr if isinstance(jr, JointRecord) else JointRecord.from_dict(jr)
        for jr in raw_joints
        if isinstance(jr, (dict, JointRecord))
    ]
    raw_assoc = d.get("assoc_refs") or []
    assoc_refs = [
        ar if isinstance(ar, AssocRef) else AssocRef.from_dict(ar)
        for ar in raw_assoc
        if isinstance(ar, (dict, AssocRef))
    ]

    if btype == "cabinet" and "params" in d:
        pr = d["params"]
        cab = ParametricCabinet(
            name=d.get("name", "Корпус"),
            x=pr.get("x", 0),
            y=pr.get("y", 0),
            z=pr.get("z", 0),
            width=pr.get("width", 600),
            height=pr.get("height", 720),
            depth=pr.get("depth", 560),
            thickness=pr.get("thickness", 16),
            shelves_count=pr.get("shelves_count", 1),
            has_facade=pr.get("has_facade", True),
            is_upper=pr.get("is_upper", False),
            has_groove=pr.get("has_groove", True),
            pos_num=d.get("pos_num", "1"),
            code=d.get("code", "01.00"),
            uid=str(d.get("uid") or ""),
            joints=joints,
            rebuild_on_init=not bool(panels_data),
        )
        cab.assoc_refs = assoc_refs
        # Восстанавливаем сохраненные панели из файла (с пазами/присадкой), если они есть
        if panels_data:
            cab.panels = [_panel_from_dict(pd) for pd in panels_data]
            for p in cab.panels:
                p._block = cab
            if cab.joints:
                apply_joints(cab)
            if cab.assoc_refs:
                apply_assoc_refs(cab)
        return cab

    block = Block(
        name=d.get("name", "Блок"),
        pos_num=d.get("pos_num", ""),
        code=d.get("code", ""),
        uid=str(d.get("uid") or ""),
        joints=joints,
        assoc_refs=assoc_refs,
    )
    block.panels = [_panel_from_dict(pd) for pd in panels_data]
    for p in block.panels:
        p._block = block
    if block.joints:
        apply_joints(block)
    if block.assoc_refs:
        apply_assoc_refs(block)
    return block


def scene_to_dict(blocks: list, project_name: str = "project") -> dict:
    return {
        "format": "NestCraft",
        "version": FORMAT_VERSION,
        "name": project_name,
        "blocks": [_block_to_dict(b) for b in blocks],
    }


def scene_from_dict(data: dict) -> tuple[str, list]:
    if not isinstance(data, dict):
        raise ValueError("Некорректный файл проекта")
    migrated, _steps = migrate_project_dict(data, in_place=False)
    name = migrated.get("name", "project")
    blocks = [_block_from_dict(bd) for bd in migrated.get("blocks", [])]
    return name, blocks


def collect_missing_materials(blocks: list) -> list[str]:
    """Id материалов из файла, которых нет в каталоге.

    Смотрит panel.missing_material_id (выставляется при загрузке), а не
    текущий material_id — тот уже может быть подменён на default в Panel.__init__.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        for p in getattr(b, "panels", []) or []:
            mid = str(getattr(p, "missing_material_id", "") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            missing.append(mid)
    return missing


def collect_missing_edges(blocks: list) -> list[str]:
    """Id кромок из файла, которых нет в каталоге (план §2.8, аналог §1.1)."""
    missing: list[str] = []
    seen: set[str] = set()
    cat = None
    try:
        from core.catalog import CatalogService
        cat = CatalogService.instance()
    except Exception:
        _log.exception("Failed to acquire CatalogService in collect_missing_edges")
        cat = None

    for b in blocks:
        for p in getattr(b, "panels", []) or []:
            medges = getattr(p, "missing_edges", None) or {}
            if isinstance(medges, dict):
                for _side, eid in medges.items():
                    eid_str = str(eid or "").strip()
                    if eid_str and eid_str not in seen:
                        seen.add(eid_str)
                        missing.append(eid_str)
            if cat is not None:
                edges = getattr(p, "edges", None) or {}
                if isinstance(edges, dict):
                    for _side, eid in edges.items():
                        eid_str = str(eid or "").strip()
                        if eid_str and eid_str not in seen and cat.get_edge(eid_str) is None:
                            seen.add(eid_str)
                            missing.append(eid_str)
    return missing


def _atomic_write_text(path: Path, payload: str) -> None:
    """Атомарная запись текста через временный файл в той же директории с сохранением прав."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            if path.exists():
                shutil.copymode(path, tmp_name)
            else:
                um = os.umask(0)
                os.umask(um)
                os.chmod(tmp_name, 0o666 & ~um)
        except OSError:
            _log.debug("Could not apply file permissions on %s", tmp_name, exc_info=True)
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            _log.debug("Could not remove temporary file %s after failure", tmp_name, exc_info=True)
        raise


def save_project(path: str | Path, blocks: list, project_name: str = "project") -> None:
    """Атомарная запись: temp-файл в той же папке + os.replace."""
    path = Path(path)
    data = scene_to_dict(blocks, project_name)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        _atomic_write_text(path, payload)
    except Exception:
        _log.exception("save_project failed path=%s", path)
        raise


class ProjectDataSnapshot:
    """Неизменяемый снимок прочитанного и мигрированного JSON проекта (без обращения к UI/Catalog)."""

    def __init__(
        self,
        path: Path,
        name: str,
        raw_version: str,
        migrated_dict: dict,
        warnings: list[str] | None = None,
        migrations: list[str] | None = None,
    ):
        self.path = Path(path)
        self.name = str(name or "project")
        self.raw_version = str(raw_version or "")
        self.migrated_dict = migrated_dict
        self.warnings = list(warnings or [])
        self.migrations = list(migrations or [])


class ProjectLoadResult:
    """Результат загрузки с предупреждениями (версия, миграции, материалы, кромки)."""

    def __init__(
        self,
        name: str,
        blocks: list,
        version: str = "",
        warnings: list[str] | None = None,
        migrations: list[str] | None = None,
        path: str | Path | None = None,
    ):
        self.name = name
        self.blocks = blocks
        self.version = version or ""
        self.warnings = list(warnings or [])
        self.migrations = list(migrations or [])
        self.path = str(path) if path is not None else ""


def read_project_snapshot(
    path: str | Path,
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> ProjectDataSnapshot:
    """Читает, парсит и мигрирует `.b3d` в потоке пула (безопасно вне UI-потока, п. 2.4)."""
    path = Path(path)
    if progress_cb is not None:
        progress_cb(1, 3, f"Чтение файла «{path.name}»…")
    raw_text = path.read_text(encoding="utf-8")

    if progress_cb is not None:
        progress_cb(2, 3, f"Разбор JSON «{path.name}»…")
    data = json.loads(raw_text)
    if not isinstance(data, dict):
        raise ValueError("Некорректный файл проекта")

    warnings: list[str] = []
    file_ver = str(data.get("version") or "0.0.1")
    if version_cmp(file_ver, FORMAT_VERSION) > 0:
        warnings.append(
            f"Файл версии {file_ver}, программа поддерживает {FORMAT_VERSION}. "
            "Часть данных может быть прочитана неверно."
        )
    elif version_cmp(file_ver, MIN_SUPPORTED_VERSION) < 0:
        warnings.append(
            f"Очень старая версия файла ({file_ver}). Рекомендуется проверить модель после открытия."
        )

    if progress_cb is not None:
        progress_cb(3, 3, f"Миграция схемы «{path.name}»…")
    migrated, applied_migrations = migrate_project_dict(data, in_place=True)
    if applied_migrations:
        _log.info("Migrated project %s (%s): %s", path.name, file_ver, ", ".join(applied_migrations))

    return ProjectDataSnapshot(
        path=path,
        name=str(migrated.get("name") or "project"),
        raw_version=file_ver,
        migrated_dict=migrated,
        warnings=warnings,
        migrations=applied_migrations,
    )


def materialize_project_snapshot(
    snapshot: ProjectDataSnapshot,
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> ProjectLoadResult:
    """Создаёт объекты `Block` и `Panel` из `ProjectDataSnapshot` и собирает предупреждения каталога."""
    raw_blocks = snapshot.migrated_dict.get("blocks", []) or []
    total_blocks = len(raw_blocks)
    blocks: list = []
    for idx, bd in enumerate(raw_blocks, start=1):
        blocks.append(_block_from_dict(bd))
        if progress_cb is not None:
            progress_cb(idx, max(1, total_blocks), f"Построение блоков: {idx}/{total_blocks}…")

    warnings = list(snapshot.warnings)
    missing_mats = collect_missing_materials(blocks)
    if missing_mats:
        preview = ", ".join(missing_mats[:8])
        more = f" и ещё {len(missing_mats) - 8}" if len(missing_mats) > 8 else ""
        warnings.append(
            f"В каталоге нет материалов, на которые ссылается проект: {preview}{more}. "
            "Деталям назначен материал по умолчанию, ссылка сохранена в проекте."
        )

    missing_edges = collect_missing_edges(blocks)
    if missing_edges:
        preview = ", ".join(missing_edges[:8])
        more = f" и ещё {len(missing_edges) - 8}" if len(missing_edges) > 8 else ""
        warnings.append(
            f"В каталоге нет кромок, на которые ссылается проект: {preview}{more}. "
            "Проверьте кромкооблицовку деталей или добавьте кромки в каталог."
        )

    return ProjectLoadResult(
        name=snapshot.name,
        blocks=blocks,
        version=snapshot.raw_version,
        warnings=warnings,
        migrations=list(snapshot.migrations),
        path=snapshot.path,
    )


def load_project(
    path: str | Path,
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> ProjectLoadResult:
    snapshot = read_project_snapshot(path, progress_cb=progress_cb)
    return materialize_project_snapshot(snapshot, progress_cb=progress_cb)


# ── Список недавних файлов (план §2.8) ────────────────────────


def recent_files_path(base_dir: str | Path | None = None) -> Path:
    """Путь к JSON-файлу со списком недавних проектов."""
    root = Path(base_dir) if base_dir is not None else user_data_dir()
    return root / "recent_files.json"


def load_recent_files(
    *,
    storage_path: str | Path | None = None,
    only_existing: bool = True,
) -> list[str]:
    """Возвращает список путей к недавним файлам (от новых к старым)."""
    sf = Path(storage_path) if storage_path is not None else recent_files_path()
    if not sf.is_file():
        return []
    try:
        raw = json.loads(sf.read_text(encoding="utf-8"))
        items = raw.get("recent_files", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    except Exception:
        _log.exception("Failed to read recent_files from %s", sf)
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        p_str = str(item).strip()
        if not p_str:
            continue
        norm = os.path.normcase(os.path.abspath(p_str))
        if norm in seen:
            continue
        if only_existing and not Path(p_str).is_file():
            continue
        seen.add(norm)
        result.append(os.path.abspath(p_str))
        if len(result) >= MAX_RECENT_FILES:
            break
    return result


def _save_recent_files_list(paths: list[str], sf: Path) -> None:
    payload = json.dumps({"recent_files": paths[:MAX_RECENT_FILES]}, ensure_ascii=False, indent=2)
    try:
        _atomic_write_text(sf, payload)
    except Exception:
        _log.exception("Failed to write recent_files to %s", sf)


def add_recent_file(
    path: str | Path,
    *,
    storage_path: str | Path | None = None,
    max_items: int = MAX_RECENT_FILES,
) -> list[str]:
    """Добавляет путь на первое место в списке недавних файлов (без дублей)."""
    sf = Path(storage_path) if storage_path is not None else recent_files_path()
    target_abs = os.path.abspath(str(path))
    target_norm = os.path.normcase(target_abs)

    existing = load_recent_files(storage_path=sf, only_existing=False)
    updated = [target_abs]
    for p in existing:
        if os.path.normcase(os.path.abspath(p)) != target_norm:
            updated.append(os.path.abspath(p))
        if len(updated) >= max(1, int(max_items)):
            break

    _save_recent_files_list(updated, sf)
    return updated


def remove_recent_file(
    path: str | Path,
    *,
    storage_path: str | Path | None = None,
) -> list[str]:
    """Удаляет указанный путь из списка недавних файлов."""
    sf = Path(storage_path) if storage_path is not None else recent_files_path()
    target_norm = os.path.normcase(os.path.abspath(str(path)))
    existing = load_recent_files(storage_path=sf, only_existing=False)
    updated = [p for p in existing if os.path.normcase(os.path.abspath(p)) != target_norm]
    _save_recent_files_list(updated, sf)
    return updated


def clear_recent_files(*, storage_path: str | Path | None = None) -> None:
    """Очищает список недавних файлов."""
    sf = Path(storage_path) if storage_path is not None else recent_files_path()
    _save_recent_files_list([], sf)


# ── Автосохранение и восстановление после сбоя (план §2.8, ревизия 2 п. 1.11 и 2.4) ────

# Позволяет в модульных тестах подменять проверку активности PID
_PID_ALIVE_CHECKER: Callable[[int], bool] | None = None
# Подмена времени старта процесса (тесты / без OS API)
_PROCESS_START_CHECKER: Callable[[int], float | None] | None = None

# Допуск при сравнении create_time (сек) — ревизия 4 §1.3
_PROCESS_START_TOLERANCE_SEC = 2.0

# WinAPI: сигнатуры один раз (HANDLE на x64 — 64 бита)
_WIN_K32 = None
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _WIN_K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WIN_K32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _WIN_K32.OpenProcess.restype = wintypes.HANDLE
    _WIN_K32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _WIN_K32.GetExitCodeProcess.restype = wintypes.BOOL
    _WIN_K32.CloseHandle.argtypes = [wintypes.HANDLE]
    _WIN_K32.CloseHandle.restype = wintypes.BOOL
    _WIN_K32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    _WIN_K32.GetProcessTimes.restype = wintypes.BOOL


def _ensure_win_k32():
    """Инициализация WinAPI (в т.ч. если тесты подменили sys.platform после импорта)."""
    global _WIN_K32
    if _WIN_K32 is not None:
        return _WIN_K32
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    k32.GetProcessTimes.restype = wintypes.BOOL
    _WIN_K32 = k32
    return k32


def _filetime_to_unix(ft) -> float:
    """FILETIME (100-ns с 1601-01-01) → unix time."""
    val = (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)
    return val / 10_000_000.0 - 11_644_473_600.0


def process_start_time(pid: int) -> float | None:
    """Время старта процесса (unix seconds) или None, если недоступно."""
    if _PROCESS_START_CHECKER is not None:
        try:
            return _PROCESS_START_CHECKER(int(pid))
        except Exception:
            return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if pid == os.getpid():
        # приближение: время старта интерпретатора недоступно портативно —
        # для своего PID мета при записи всё равно берётся в момент create_autosave
        return None

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = _ensure_win_k32()
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            ctime = wintypes.FILETIME()
            etime = wintypes.FILETIME()
            ktime = wintypes.FILETIME()
            utime = wintypes.FILETIME()
            if not k32.GetProcessTimes(
                handle, ctypes.byref(ctime), ctypes.byref(etime),
                ctypes.byref(ktime), ctypes.byref(utime),
            ):
                return None
            return _filetime_to_unix(ctime)
        finally:
            k32.CloseHandle(handle)

    # Linux: /proc/<pid>/stat field 22 (starttime, ticks since boot) + btime
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/stat", encoding="utf-8") as f:
                btime = None
                for line in f:
                    if line.startswith("btime "):
                        btime = float(line.split()[1])
                        break
            with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
                stat = f.read()
            # comm may contain spaces/parens — split after last ')'
            rparen = stat.rfind(")")
            fields = stat[rparen + 2 :].split()
            start_ticks = float(fields[19])  # field 22 → index 19 after comm
            ticks = float(os.sysconf("SC_CLK_TCK") or 100)
            if btime is not None:
                return btime + start_ticks / ticks
        except Exception:
            return None
    return None


def _pid_alive_native(pid: int) -> bool:
    """Проверка «процесс жив» без сигнала, который на Windows убивает цель.

    Linux/macOS: ``os.kill(pid, 0)`` — безопасный probe.
    Windows: ``OpenProcess`` + ``GetExitCodeProcess`` (STILL_ACTIVE=259)
    с объявленными argtypes/restype (ревизия 4 §1.3).
    """
    if sys.platform == "win32":
        from ctypes import wintypes

        k32 = _ensure_win_k32()
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return int(code.value) == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)

    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def is_pid_running(pid: int | None) -> bool:
    """Возвращает True, если процесс с указанным PID существует и активен в ОС."""
    if pid is None:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    if _PID_ALIVE_CHECKER is not None:
        return bool(_PID_ALIVE_CHECKER(pid_int))
    if pid_int == os.getpid():
        return True
    return _pid_alive_native(pid_int)


def is_same_process(pid: int | None, expected_start: float | None) -> bool:
    """True, если PID жив и (если задано) время старта совпадает с expected_start.

    Защита от переиспользования PID (ревизия 4 §1.3): чужой процесс с тем же PID
    не блокирует восстановление autosave.
    """
    if not is_pid_running(pid):
        return False
    if expected_start is None:
        return True  # старые файлы без process_start — только PID
    actual = process_start_time(int(pid))
    if actual is None:
        # Не удалось прочитать start time — консервативно считаем «тот же»
        return True
    return abs(float(actual) - float(expected_start)) <= _PROCESS_START_TOLERANCE_SEC


def extract_autosave_pid(path: Path, raw_data: dict | None = None) -> int | None:
    """Извлекает PID владельца из `autosave_meta.pid` или из имени `autosave_recovery_<pid>.b3d`."""
    if isinstance(raw_data, dict):
        meta = raw_data.get("autosave_meta")
        if isinstance(meta, dict) and meta.get("pid") is not None:
            try:
                return int(meta["pid"])
            except (TypeError, ValueError):
                _log.debug("Invalid pid in autosave_meta of %s", path)
    stem = path.stem  # например, autosave_recovery_12345
    prefix = "autosave_recovery_"
    if stem.startswith(prefix):
        tail = stem[len(prefix):]
        if tail.isdigit():
            return int(tail)
    return None


def extract_autosave_process_start(raw_data: dict | None) -> float | None:
    """Время старта владельца из autosave_meta.process_start (unix sec)."""
    if not isinstance(raw_data, dict):
        return None
    meta = raw_data.get("autosave_meta")
    if not isinstance(meta, dict) or meta.get("process_start") is None:
        return None
    try:
        return float(meta["process_start"])
    except (TypeError, ValueError):
        return None


def autosave_file_path(
    base_dir: str | Path | None = None,
    *,
    pid: int | None = None,
) -> Path:
    """Путь к временному файлу автосохранения текущего процесса (с PID в имени, п. 1.11)."""
    root = Path(base_dir) if base_dir is not None else (user_data_dir() / "autosave")
    actual_pid = int(pid) if pid is not None else os.getpid()
    return root / f"autosave_recovery_{actual_pid}.b3d"


def create_autosave_snapshot(
    blocks: list,
    project_name: str = "Новый проект.b3d",
    original_path: str | Path | None = None,
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    pid: int | None = None,
) -> dict:
    """Формирует в памяти чистый словарь-снимок сцены для последующей записи в `QRunnable` (п. 2.4)."""
    actual_pid = int(pid) if pid is not None else os.getpid()
    target = (
        Path(autosave_path)
        if autosave_path is not None
        else autosave_file_path(base_dir, pid=actual_pid)
    )
    data = scene_to_dict(blocks, project_name)
    start = process_start_time(actual_pid)
    if start is None:
        # свой процесс: фиксируем момент снимка как якорь (для чужого PID сверим через OS)
        start = time.time()
    data["autosave_meta"] = {
        "original_path": os.path.abspath(str(original_path)) if original_path else "",
        "project_name": str(project_name or "Новый проект.b3d"),
        "timestamp": time.time(),
        "pid": actual_pid,
        "process_start": float(start),
        "target_path": str(target),
    }
    return data


def write_autosave_snapshot(
    snapshot: dict,
    *,
    autosave_path: str | Path | None = None,
) -> Path:
    """Атомарно записывает готовый словарь-снимок автосохранения на диск (безопасно в `QRunnable`)."""
    meta = snapshot.get("autosave_meta") if isinstance(snapshot.get("autosave_meta"), dict) else {}
    target_str = str(autosave_path or meta.get("target_path") or "")
    target = Path(target_str) if target_str else autosave_file_path(pid=meta.get("pid"))
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    _atomic_write_text(target, payload)
    return target


def write_autosave(
    blocks: list,
    project_name: str = "Новый проект.b3d",
    original_path: str | Path | None = None,
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    pid: int | None = None,
) -> Path:
    """Атомарно записывает снимок текущего несохранённого проекта во временный файл."""
    snapshot = create_autosave_snapshot(
        blocks,
        project_name=project_name,
        original_path=original_path,
        autosave_path=autosave_path,
        base_dir=base_dir,
        pid=pid,
    )
    return write_autosave_snapshot(snapshot, autosave_path=autosave_path)


def _inspect_autosave_candidate(
    candidate: Path,
    *,
    current_pid: int | None = None,
    check_foreign_pid: bool = True,
) -> dict | None:
    """Возвращает распарсенный словарь автосохранения, если файл валиден и не занят живым чужим процессом."""
    if not candidate.is_file():
        return None
    try:
        if candidate.stat().st_size <= 2:
            return None
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        if not (isinstance(raw, dict) and isinstance(raw.get("blocks"), list)):
            return None
        if check_foreign_pid:
            cur_pid = int(current_pid) if current_pid is not None else os.getpid()
            owner_pid = extract_autosave_pid(candidate, raw)
            owner_start = extract_autosave_process_start(raw)
            # Чужой ЖИВОЙ экземпляр (тот же PID+start) — не трогаем.
            # Переиспользованный PID (start не совпал) — можно предлагать восстановление.
            if (
                owner_pid is not None
                and owner_pid != cur_pid
                and is_same_process(owner_pid, owner_start)
            ):
                return None
        return raw
    except Exception:
        _log.debug("Invalid or unreadable autosave candidate %s", candidate, exc_info=True)
        return None


def find_recoverable_autosave(
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    current_pid: int | None = None,
) -> Path | None:
    """Находит самый свежий файл автосохранения для восстановления, игнорируя файлы живых параллельных процессов."""
    if autosave_path is not None:
        target = Path(autosave_path)
        raw = _inspect_autosave_candidate(
            target,
            current_pid=current_pid,
            check_foreign_pid=(current_pid is not None),
        )
        return target if raw is not None else None

    root = Path(base_dir) if base_dir is not None else (user_data_dir() / "autosave")
    if not root.is_dir():
        return None

    candidates = sorted(
        root.glob("autosave_recovery*.b3d"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for cand in candidates:
        if _inspect_autosave_candidate(cand, current_pid=current_pid, check_foreign_pid=True) is not None:
            return cand
    return None


def has_autosave(
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    current_pid: int | None = None,
) -> bool:
    """True, если существует непустой и валидный файл автосохранения (не занятый другим живым PID)."""
    return (
        find_recoverable_autosave(
            autosave_path=autosave_path,
            base_dir=base_dir,
            current_pid=current_pid,
        )
        is not None
    )


def load_autosave(
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    current_pid: int | None = None,
) -> tuple[ProjectLoadResult, dict]:
    """Загружает проект из файла автосохранения и возвращает (ProjectLoadResult, autosave_meta)."""
    target = find_recoverable_autosave(
        autosave_path=autosave_path,
        base_dir=base_dir,
        current_pid=current_pid,
    )
    if target is None:
        fallback = Path(autosave_path) if autosave_path is not None else autosave_file_path(base_dir, pid=current_pid)
        raise FileNotFoundError(f"Файл автосохранения не найден: {fallback}")
    raw = json.loads(target.read_text(encoding="utf-8"))
    meta = raw.get("autosave_meta") if isinstance(raw, dict) and isinstance(raw.get("autosave_meta"), dict) else {}
    meta_out = dict(meta)
    meta_out["autosave_file"] = str(target)
    res = load_project(target)
    return res, meta_out


def clear_autosave(
    *,
    autosave_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    pid: int | None = None,
    clear_orphaned: bool = True,
) -> None:
    """Удаляет временный файл автосохранения текущего процесса (и осиротевшие файлы упавших процессов)."""
    if autosave_path is not None:
        target = Path(autosave_path)
        try:
            if target.exists():
                target.unlink()
        except OSError:
            _log.exception("Failed to remove autosave file %s", target)
        return

    cur_pid = int(pid) if pid is not None else os.getpid()
    own_target = autosave_file_path(base_dir, pid=cur_pid)
    try:
        if own_target.exists():
            own_target.unlink()
    except OSError:
        _log.exception("Failed to remove autosave file %s", own_target)

    if clear_orphaned:
        root = Path(base_dir) if base_dir is not None else (user_data_dir() / "autosave")
        if root.is_dir():
            for cand in list(root.glob("autosave_recovery*.b3d")):
                owner_pid = extract_autosave_pid(cand)
                owner_start = None
                try:
                    raw = json.loads(cand.read_text(encoding="utf-8"))
                    owner_start = extract_autosave_process_start(raw)
                    if owner_pid is None:
                        owner_pid = extract_autosave_pid(cand, raw)
                except Exception:
                    _log.debug("Could not read autosave meta for %s", cand, exc_info=True)
                if (
                    owner_pid is not None
                    and owner_pid != cur_pid
                    and is_same_process(owner_pid, owner_start)
                ):
                    # Файл принадлежит другому запущенному экземпляру — не удаляем!
                    continue
                try:
                    if cand.exists():
                        cand.unlink()
                except OSError:
                    _log.debug("Failed to remove orphaned autosave file %s", cand, exc_info=True)


