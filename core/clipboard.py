"""Буфер обмена сцены: Ctrl+C / Ctrl+V с точкой привязки (ревизия 4 / клоны)."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.logging_setup import get_logger
from core.project_io import _block_to_dict, _panel_to_dict
from models.panel import Block, Panel, ParametricCabinet, new_uid

_log = get_logger("clipboard")


@dataclass
class ClipboardPayload:
    """Снимок выделения: блоки (целиком) и/или свободные панели."""

    block_dicts: list[dict] = field(default_factory=list)
    # Панели вне целиком скопированных блоков: (parent_block_name_hint, panel_dict)
    free_panel_dicts: list[dict] = field(default_factory=list)
    # Стыки между free-панелями (если оба конца в наборе)
    free_joint_dicts: list[dict] = field(default_factory=list)
    anchor: tuple[float, float, float] | None = None
    count_panels: int = 0
    count_blocks: int = 0


def _selected_blocks_and_panels(blocks: list) -> tuple[list, list[Panel], set[int]]:
    """Возвращает (целые выделенные блоки, выделенные панели, id панелей в целых блоках)."""
    whole_blocks: list = []
    panels_in_whole: set[int] = set()
    for b in blocks or []:
        if getattr(b, "selected", False):
            whole_blocks.append(b)
            for p in getattr(b, "panels", []) or []:
                panels_in_whole.add(id(p))
    loose: list[Panel] = []
    for b in blocks or []:
        if b in whole_blocks:
            continue
        for p in getattr(b, "panels", []) or []:
            if getattr(p, "selected", False) and id(p) not in panels_in_whole:
                loose.append(p)
    return whole_blocks, loose, panels_in_whole


def capture_selection(blocks: list) -> ClipboardPayload | None:
    """Собрать payload из текущего выделения. None если пусто."""
    whole, loose, _ = _selected_blocks_and_panels(blocks)
    if not whole and not loose:
        return None

    payload = ClipboardPayload()
    for b in whole:
        payload.block_dicts.append(_block_to_dict(b))
        payload.count_blocks += 1
        payload.count_panels += len(getattr(b, "panels", []) or [])

    loose_uids = {str(getattr(p, "uid", "") or "") for p in loose}
    for p in loose:
        payload.free_panel_dicts.append(_panel_to_dict(p))
        payload.count_panels += 1

    # Стыки, оба конца которых в loose-наборе
    seen_jr: set[str] = set()
    for b in blocks or []:
        for jr in getattr(b, "joints", None) or []:
            a = str(getattr(jr, "panel_a_uid", "") or "")
            bb = str(getattr(jr, "panel_b_uid", "") or "")
            if a in loose_uids and bb in loose_uids:
                juid = str(getattr(jr, "uid", "") or id(jr))
                if juid in seen_jr:
                    continue
                seen_jr.add(juid)
                if hasattr(jr, "to_dict"):
                    payload.free_joint_dicts.append(jr.to_dict())
                else:
                    payload.free_joint_dicts.append(dict(jr))

    return payload


def set_anchor(payload: ClipboardPayload, x: float, y: float, z: float) -> None:
    payload.anchor = (float(x), float(y), float(z))


def _remap_hole_joint_uids(
    holes: list,
    uid_map: dict[str, str],
    valid_joint_uids: set[str] | None = None,
) -> list:
    out = []
    for h in holes or []:
        if not h or len(h) < 6:
            out.append(h)
            continue
        if len(h) >= 7 and h[6]:
            old = str(h[6]).strip()
            if valid_joint_uids is not None and old not in valid_joint_uids:
                # Стык не вошёл в копируемый набор — оставляем отверстие как ручное (6 полей)
                out.append(tuple(h[:6]))
                continue
            new = uid_map.setdefault(old, new_uid())
            out.append(tuple(list(h[:6]) + [new]))
        else:
            out.append(tuple(h[:6]))
    return out


def _clone_panel_dict(
    pd: dict,
    uid_map: dict[str, str],
    dx: float,
    dy: float,
    dz: float,
    valid_joint_uids: set[str] | None = None,
) -> Panel:
    from core.joint import holes_equal

    d = dict(pd)
    old_uid = str(d.get("uid") or "")
    new = new_uid()
    if old_uid:
        uid_map[old_uid] = new
    d["uid"] = new
    d["x"] = float(d.get("x", 0)) + dx
    d["y"] = float(d.get("y", 0)) + dy
    d["z"] = float(d.get("z", 0)) + dz

    jmap = d.get("joint_hole_map")
    new_map: dict[str, list] = {}
    legacy_untagged_by_new_uid: dict[str, list[tuple]] = {}
    if isinstance(jmap, dict) and jmap:
        for k, holes in jmap.items():
            old_k = str(k).strip()
            if not old_k:
                continue
            if valid_joint_uids is not None and old_k not in valid_joint_uids:
                continue
            nk = uid_map.setdefault(old_k, new_uid())
            remapped_list = [
                list(h[:6]) + [nk]
                for h in (holes or [])
                if h and len(h) >= 6
            ]
            if remapped_list:
                new_map[nk] = remapped_list
                legacy_untagged_by_new_uid[nk] = [tuple(h[:6]) for h in remapped_list]
        d["joint_hole_map"] = new_map
    else:
        d["joint_hole_map"] = {}

    # holes: remap joint_uid labels (и проставить метку для legacy 6-элементных дырок из joint_hole_map)
    raw_holes = d.get("holes") or []
    remapped_holes = []
    for h in _remap_hole_joint_uids(raw_holes, uid_map, valid_joint_uids=valid_joint_uids):
        if not h or len(h) < 6:
            remapped_holes.append(list(h) if isinstance(h, (list, tuple)) else h)
            continue
        if len(h) >= 7 and h[6]:
            remapped_holes.append(list(h[:7]))
            continue
        h6 = tuple(h[:6])
        matched_nk = None
        for nk, cand_list in legacy_untagged_by_new_uid.items():
            for idx, ch in enumerate(cand_list):
                if holes_equal(h6, ch):
                    matched_nk = nk
                    cand_list.pop(idx)
                    break
            if matched_nk:
                break
        if matched_nk:
            remapped_holes.append(list(h6) + [matched_nk])
        else:
            remapped_holes.append(list(h6))
    d["holes"] = remapped_holes

    p = Panel.from_dict(d, rebuild=True)
    return p


def _prepopulate_joint_uids(
    joint_dicts: list,
    panel_uids: set[str],
    uid_map: dict[str, str],
) -> set[str]:
    """Предварительно резервирует новые UID для всех валидных стыков набора."""
    valid_old_joint_uids: set[str] = set()
    for jd in joint_dicts or []:
        if not isinstance(jd, dict):
            continue
        a = str(jd.get("panel_a_uid") or "")
        b = str(jd.get("panel_b_uid") or "")
        if a not in panel_uids or b not in panel_uids:
            continue
        old_j_uid = str(jd.get("uid") or "").strip()
        if old_j_uid:
            uid_map.setdefault(old_j_uid, new_uid())
            valid_old_joint_uids.add(old_j_uid)
    return valid_old_joint_uids


def _clone_block_dict(bd: dict, dx: float, dy: float, dz: float) -> Block:
    uid_map: dict[str, str] = {}
    raw_panel_dicts = list(bd.get("panels") or [])
    raw_joint_dicts = list(bd.get("joints") or [])
    src_panel_uids = {
        str(pd.get("uid") or "")
        for pd in raw_panel_dicts
        if isinstance(pd, dict) and str(pd.get("uid") or "")
    }
    valid_joint_uids = _prepopulate_joint_uids(raw_joint_dicts, src_panel_uids, uid_map)

    panels = []
    for pd in raw_panel_dicts:
        panels.append(
            _clone_panel_dict(pd, uid_map, dx, dy, dz, valid_joint_uids=valid_joint_uids)
        )

    btype = bd.get("type") or "block"
    new_block_uid = new_uid()
    name = str(bd.get("name") or "Блок")
    if not name.endswith(" (копия)"):
        name = f"{name} (копия)"

    if btype == "cabinet":
        params = dict(bd.get("params") or {})
        cab = ParametricCabinet(
            name,
            x=float(params.get("x", 0)) + dx,
            y=float(params.get("y", 0)) + dy,
            z=float(params.get("z", 0)) + dz,
            width=float(params.get("width", 600)),
            height=float(params.get("height", 720)),
            depth=float(params.get("depth", 560)),
            thickness=float(params.get("thickness", 16)),
            shelves_count=int(params.get("shelves_count", 1)),
            has_facade=bool(params.get("has_facade", True)),
            is_upper=bool(params.get("is_upper", False)),
            has_groove=bool(params.get("has_groove", True)),
            pos_num=str(bd.get("pos_num") or ""),
            code=str(bd.get("code") or ""),
            uid=new_block_uid,
            joints=[],
            rebuild_on_init=False,
        )
        # Заменяем панели на клоны (не пересобирать parametric — сохранить user geometry)
        cab.panels = panels
        for p in panels:
            p._block = cab
        block = cab
    else:
        block = Block(
            name,
            pos_num=str(bd.get("pos_num") or ""),
            code=str(bd.get("code") or ""),
            uid=new_block_uid,
            joints=[],
        )
        for p in panels:
            block.add_panel(p)

    # Joints with remapped panel uids and synchronized joint uid
    from core.joint import JointRecord, apply_joints

    new_joints = []
    for jd in raw_joint_dicts:
        if not isinstance(jd, dict):
            continue
        a = str(jd.get("panel_a_uid") or "")
        b = str(jd.get("panel_b_uid") or "")
        na = uid_map.get(a)
        nb = uid_map.get(b)
        if not na or not nb:
            continue
        old_j_uid = str(jd.get("uid") or "").strip()
        new_j_uid = uid_map.get(old_j_uid) if old_j_uid else ""
        if not new_j_uid:
            new_j_uid = new_uid()
            if old_j_uid:
                uid_map[old_j_uid] = new_j_uid
        rec = JointRecord(
            uid=new_j_uid,
            panel_a_uid=na,
            panel_b_uid=nb,
            preset_id=str(jd.get("preset_id") or "confirmat_3"),
            fastener_id=str(jd.get("fastener_id") or ""),
            params=dict(jd.get("params") or {}) if isinstance(jd.get("params"), dict) else {},
        )
        new_joints.append(rec)
    block.joints = new_joints
    if new_joints:
        try:
            apply_joints(block)
        except Exception:  # noqa: BLE001 — граница apply_joints
            _log.exception("apply_joints after clone failed")
    return block


def materialize(
    payload: ClipboardPayload,
    target: tuple[float, float, float],
) -> list[Block]:
    """Создать новые блоки/панели: anchor → target (delta)."""
    if payload.anchor is None:
        raise ValueError("clipboard anchor is not set")
    dx = float(target[0]) - float(payload.anchor[0])
    dy = float(target[1]) - float(payload.anchor[1])
    dz = float(target[2]) - float(payload.anchor[2])

    result: list[Block] = []
    for bd in payload.block_dicts:
        result.append(_clone_block_dict(bd, dx, dy, dz))

    if payload.free_panel_dicts:
        uid_map: dict[str, str] = {}
        src_panel_uids = {
            str(pd.get("uid") or "")
            for pd in payload.free_panel_dicts
            if isinstance(pd, dict) and str(pd.get("uid") or "")
        }
        valid_joint_uids = _prepopulate_joint_uids(
            payload.free_joint_dicts, src_panel_uids, uid_map
        )
        panels = [
            _clone_panel_dict(
                pd, uid_map, dx, dy, dz, valid_joint_uids=valid_joint_uids
            )
            for pd in payload.free_panel_dicts
        ]
        block = Block("Копия", uid=new_uid(), joints=[])
        for p in panels:
            block.add_panel(p)
        from core.joint import JointRecord, apply_joints

        joints = []
        for jd in payload.free_joint_dicts:
            a = str(jd.get("panel_a_uid") or "")
            b = str(jd.get("panel_b_uid") or "")
            na, nb = uid_map.get(a), uid_map.get(b)
            if not na or not nb:
                continue
            old_j_uid = str(jd.get("uid") or "").strip()
            new_j_uid = uid_map.get(old_j_uid) if old_j_uid else ""
            if not new_j_uid:
                new_j_uid = new_uid()
                if old_j_uid:
                    uid_map[old_j_uid] = new_j_uid
            joints.append(
                JointRecord(
                    uid=new_j_uid,
                    panel_a_uid=na,
                    panel_b_uid=nb,
                    preset_id=str(jd.get("preset_id") or "confirmat_3"),
                    fastener_id=str(jd.get("fastener_id") or ""),
                    params=dict(jd.get("params") or {}) if isinstance(jd.get("params"), dict) else {},
                )
            )
        block.joints = joints
        if joints:
            try:
                apply_joints(block)
            except Exception:  # noqa: BLE001 — граница apply_joints
                _log.exception("apply_joints free panels failed")
        result.append(block)

    return result


def panel_dict_preview_corners(
    pd: dict,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
) -> list[tuple[float, float, float]]:
    """Возвращает 8 углов панели в мировых координатах со сдвигом (dx, dy, dz), с учётом поворота OBB."""
    x = float(pd.get("x", 0.0)) + float(dx)
    y = float(pd.get("y", 0.0)) + float(dy)
    z = float(pd.get("z", 0.0)) + float(dz)
    w = float(pd.get("width", 100.0))
    h = float(pd.get("height", 16.0))
    d = float(pd.get("depth", 100.0))
    rx = float(pd.get("rx", 0.0) or 0.0)
    ry = float(pd.get("ry", 0.0) or 0.0)
    rz = float(pd.get("rz", 0.0) or 0.0)
    if abs(rx) > 1e-6 or abs(ry) > 1e-6 or abs(rz) > 1e-6:
        tmp = Panel(
            name=str(pd.get("name") or "P"),
            x=x,
            y=y,
            z=z,
            width=w,
            height=h,
            depth=d,
            rx=rx,
            ry=ry,
            rz=rz,
            rebuild=False,
        )
        return tmp.world_corners()
    x2, y2, z2 = x + w, y + h, z + d
    return [
        (x, y, z), (x2, y, z), (x2, y2, z), (x, y2, z),
        (x, y, z2), (x2, y, z2), (x2, y2, z2), (x, y2, z2),
    ]
