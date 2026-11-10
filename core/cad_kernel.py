import math
import threading

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from build123d import Box, Cylinder, Pos, Rot, Align, Rotation, Extrinsic
from core.logging_setup import get_logger


# Глобальный замок B-Rep: OCC/build123d не потокобезопасны
OCC_LOCK = threading.Lock()


class CADKernel:
    """
    Промышленное твердотельное B-Rep ядро на базе OpenCASCADE (build123d).
    Обеспечивает точную математическую геометрию, булевы операции (пазы, присадку),
    анализ пересечений и будущий экспорт в STEP / DXF для ЧПУ.
    """

    @staticmethod
    def build_panel_solid_data(
        x, y, z, width, height, depth, grooves=None, holes=None, rx=0.0, ry=0.0, rz=0.0
    ):
        """B-Rep из plain-данных (безопасно вызывать из worker-потока)."""
        solid = Box(
            float(width), float(height), float(depth),
            align=(Align.MIN, Align.MIN, Align.MIN)
        )
        for groove in grooves or []:
            gx, gy, gz, gw, gh, gd = groove
            cutter = Pos(gx, gy, gz) * Box(
                gw, gh, gd,
                align=(Align.MIN, Align.MIN, Align.MIN)
            )
            solid = solid - cutter

        # Overshoot только там, где конец цилиндра лежит НА ГРАНИ панели.
        # Сквозное: вылет с обоих концов (анти-копланарность OCC).
        # Глухое: вылет только у входа — слепой конец не углубляется на 0.5 мм (план §1.6).
        overshoot = 0.5
        face_tol = 1e-3
        fw, fh, fd = float(width), float(height), float(depth)
        for hole in holes or []:
            hx, hy, hz, radius, length, axis = hole[:6]
            length = float(length)
            hx, hy, hz = float(hx), float(hy), float(hz)

            if axis == "X":
                start, end, dim = hx, hx + length, fw
            elif axis == "Y":
                start, end, dim = hy, hy + length, fh
            else:
                start, end, dim = hz, hz + length, fd

            start_on_face = start <= face_tol
            end_on_face = end >= (dim - face_tol)
            start_o = overshoot if start_on_face else 0.0
            end_o = overshoot if end_on_face else 0.0
            cyl_len = length + start_o + end_o

            cyl = Cylinder(
                radius=float(radius), height=cyl_len,
                align=(Align.CENTER, Align.CENTER, Align.MIN)
            )
            shift_x, shift_y, shift_z = 0.0, 0.0, 0.0
            if axis == "X":
                cyl = Rot(0, 90, 0) * cyl
                shift_x = -start_o
            elif axis == "Y":
                cyl = Rot(-90, 0, 0) * cyl
                shift_y = -start_o
            else:
                shift_z = -start_o

            solid = solid - (Pos(hx + shift_x, hy + shift_y, hz + shift_z) * cyl)

        # Поворот вокруг геометрического центра панели (не min-corner).
        # Порядок углов: Extrinsic.XYZ ≡ R = Rz @ Ry @ Rx (градусы).
        # Явно, потому что build123d.Rot() по умолчанию Intrinsic.XYZ и при
        # двух+ ненулевых углах расходится с Panel.rotation_matrix / превью.
        cx, cy, cz = float(width) * 0.5, float(height) * 0.5, float(depth) * 0.5
        if abs(rx) > 1e-6 or abs(ry) > 1e-6 or abs(rz) > 1e-6:
            solid = Pos(-cx, -cy, -cz) * solid
            solid = Rotation(float(rx), float(ry), float(rz), ordering=Extrinsic.XYZ) * solid
            solid = Pos(float(x) + cx, float(y) + cy, float(z) + cz) * solid
        else:
            solid = Pos(float(x), float(y), float(z)) * solid

        return solid

    @staticmethod
    def build_panel_solid(panel):
        """Создает точное B-Rep тело панели с пазами, присадкой и ориентацией."""
        return CADKernel.build_panel_solid_data(
            panel.x, panel.y, panel.z,
            panel.width, panel.height, panel.depth,
            getattr(panel, "grooves", []),
            getattr(panel, "holes", []),
            getattr(panel, "rx", 0.0),
            getattr(panel, "ry", 0.0),
            getattr(panel, "rz", 0.0),
        )

    @staticmethod
    def warmup():
        """Реальный прогрев ядра B-Rep: сборка тела с присадкой и триангуляция OCC (п. 1.4)."""
        s = CADKernel.build_panel_solid_data(
            0, 0, 0, 16, 100, 100, holes=[(8, 50, 50, 3.5, 16, "X")]
        )
        return CADKernel.get_render_mesh(s)

    @staticmethod
    def make_aabb_mesh(x, y, z, w, h, d, rx=0.0, ry=0.0, rz=0.0):
        """Low-poly превью: 12 треугольников AABB/OBB без OCC.

        24 уникальные вершины (по 4 на грань) — иначе shared verts ломают
        нормали и дают тёмные «артефакты» при Phong-освещении.
        При ненулевом повороте — оболочка, повёрнутая вокруг центра.
        """
        x0, y0, z0 = float(x), float(y), float(z)
        fw, fh, fd = float(w), float(h), float(d)
        x1, y1, z1 = x0 + fw, y0 + fh, z0 + fd

        def _xf(px, py, pz):
            if abs(rx) < 1e-9 and abs(ry) < 1e-9 and abs(rz) < 1e-9:
                return (px, py, pz)
            cx, cy, cz = x0 + fw * 0.5, y0 + fh * 0.5, z0 + fd * 0.5
            vx, vy, vz = px - cx, py - cy, pz - cz
            # Rz·Ry·Rx
            a, b, c = math.radians(rx), math.radians(ry), math.radians(rz)
            ca, sa = math.cos(a), math.sin(a)
            cb, sb = math.cos(b), math.sin(b)
            cc, sc = math.cos(c), math.sin(c)
            # Rx
            vy, vz = ca * vy - sa * vz, sa * vy + ca * vz
            # Ry
            vx, vz = cb * vx + sb * vz, -sb * vx + cb * vz
            # Rz
            vx, vy = cc * vx - sc * vy, sc * vx + cc * vy
            return (cx + vx, cy + vy, cz + vz)

        # (verts_4 local AABB, normal local) — нормали тоже крутим
        faces = [
            # -Z
            ([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], (0.0, 0.0, -1.0)),
            # +Z
            ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0.0, 0.0, 1.0)),
            # -Y
            ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0.0, -1.0, 0.0)),
            # +Y
            ([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], (0.0, 1.0, 0.0)),
            # -X
            ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1.0, 0.0, 0.0)),
            # +X
            ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1.0, 0.0, 0.0)),
        ]

        def _nrot(nx, ny, nz):
            if abs(rx) < 1e-9 and abs(ry) < 1e-9 and abs(rz) < 1e-9:
                return (nx, ny, nz)
            a, b, c = math.radians(rx), math.radians(ry), math.radians(rz)
            ca, sa = math.cos(a), math.sin(a)
            cb, sb = math.cos(b), math.sin(b)
            cc, sc = math.cos(c), math.sin(c)
            vy, vz = ca * ny - sa * nz, sa * ny + ca * nz
            vx, vz = cb * nx + sb * vz, -sb * nx + cb * vz
            vx, vy = cc * vx - sc * vy, sc * vx + cc * vy
            return (vx, vy, vz)

        verts = []
        normals = []
        tris = []
        for corners, n in faces:
            base = len(verts)
            rn = _nrot(n[0], n[1], n[2])
            for c in corners:
                verts.append(_xf(c[0], c[1], c[2]))
                normals.append(rn)
            tris.append([base, base + 1, base + 2])
            tris.append([base, base + 2, base + 3])
        if np is None:
            return verts, tris, normals
        return (
            np.asarray(verts, dtype=float),
            np.asarray(tris, dtype=int),
            np.asarray(normals, dtype=float),
        )

    # Кэш результатов проверки пересечений пар панелей по (uid, geometry_generation, world_aabb) (план §2.5)
    _COLLISION_CACHE: dict[tuple, float] = {}
    _COLLISION_CACHE_MAX = 4096

    @staticmethod
    def clear_collision_cache() -> None:
        CADKernel._COLLISION_CACHE.clear()

    @staticmethod
    def get_render_mesh(solid):
        """Триангулирует B-Rep в сетку с точными нормалями граней для чистого CAD-освещения.

        Векторизовано через numpy без Python-цикла по треугольникам (план §2.5).
        """
        if solid is None:
            if np is None:
                return [], [], []
            empty = np.zeros((0, 3), dtype=float)
            return empty, np.zeros((0, 3), dtype=int), empty

        try:
            target = solid
            if not hasattr(target, "tessellate") and isinstance(target, (list, tuple)) and len(target) > 0:
                target = target[0]
            try:
                verts_raw, tris_raw = target.tessellate(tolerance=0.5, angular_tolerance=0.2)
            except TypeError:
                verts_raw, tris_raw = target.tessellate(0.5)

            def _to_xyz(v):
                if hasattr(v, "toTuple"):
                    return v.toTuple()
                if hasattr(v, "to_tuple"):
                    return v.to_tuple()
                if hasattr(v, "X") and hasattr(v, "Y") and hasattr(v, "Z"):
                    vx, vy, vz = v.X, v.Y, v.Z
                    return (
                        float(vx() if callable(vx) else vx),
                        float(vy() if callable(vy) else vy),
                        float(vz() if callable(vz) else vz),
                    )
                return tuple(v)

            v_tuples = [_to_xyz(v) for v in verts_raw]
        except Exception:
            get_logger("cad_kernel").exception("tessellate failed")
            if np is None:
                return [], [], []
            empty = np.zeros((0, 3), dtype=float)
            return empty, np.zeros((0, 3), dtype=int), empty

        if not tris_raw or not v_tuples:
            if np is None:
                return [], [], []
            empty = np.zeros((0, 3), dtype=float)
            return empty, np.zeros((0, 3), dtype=int), empty

        if np is not None and hasattr(np, "repeat"):
            verts = np.asarray(v_tuples, dtype=float)
            tris = np.asarray(tris_raw, dtype=int)
            # Векторное разворачивание треугольников с раздельными нормалями (план §2.5)
            V = verts[tris].reshape(-1, 3)
            p0, p1, p2 = V[0::3], V[1::3], V[2::3]
            n = np.cross(p1 - p0, p2 - p0)
            lengths = np.linalg.norm(n, axis=1, keepdims=True)
            zero_mask = lengths[:, 0] <= 1e-12
            n = n / np.maximum(lengths, 1e-12)
            if np.any(zero_mask):
                n[zero_mask] = np.array([0.0, 1.0, 0.0], dtype=float)
            N = np.repeat(n, 3, axis=0)
            T = np.arange(len(V), dtype=int).reshape(-1, 3)
            return V, T, N

        # Чистый fallback только при отсутствии numpy в окружении
        V_list, T_list, N_list = [], [], []
        for idx_tri, (i0, i1, i2) in enumerate(tris_raw):
            p0, p1, p2 = v_tuples[i0], v_tuples[i1], v_tuples[i2]
            ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
            vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            n_vec = (nx / ln, ny / ln, nz / ln) if ln > 1e-12 else (0.0, 1.0, 0.0)
            V_list.extend((p0, p1, p2))
            N_list.extend((n_vec, n_vec, n_vec))
            base = idx_tri * 3
            T_list.append((base, base + 1, base + 2))
        return V_list, T_list, N_list

    @staticmethod
    def _panel_aabb(p) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        if hasattr(p, "world_aabb"):
            return p.world_aabb()
        return (
            (float(p.x), float(p.y), float(p.z)),
            (float(p.x + p.width), float(p.y + p.height), float(p.z + p.depth)),
        )

    @staticmethod
    def _panel_collision_token(p, aabb=None) -> tuple:
        if aabb is None:
            aabb = CADKernel._panel_aabb(p)
        a0, a1 = aabb
        uid = getattr(p, "uid", None) or id(p)
        gen = int(getattr(p, "geometry_generation", 0))
        return (
            uid,
            gen,
            round(float(a0[0]), 3), round(float(a0[1]), 3), round(float(a0[2]), 3),
            round(float(a1[0]), 3), round(float(a1[1]), 3), round(float(a1[2]), 3),
        )

    @staticmethod
    def aabb_overlaps(a0_or_pa, a1_or_pb, b0=None, b1=None, eps: float = 1e-4) -> bool:
        """Broad-phase проверка строгого пересечения двух world-AABB (касание граней не считается).

        Поддерживает вызов как aabb_overlaps(panel_a, panel_b), так и aabb_overlaps(a0, a1, b0, b1).
        """
        if b0 is None or b1 is None:
            a0, a1 = CADKernel._panel_aabb(a0_or_pa)
            b0, b1 = CADKernel._panel_aabb(a1_or_pb)
        else:
            a0, a1 = a0_or_pa, a1_or_pb
        return not (
            a1[0] <= b0[0] + eps or b1[0] <= a0[0] + eps or
            a1[1] <= b0[1] + eps or b1[1] <= a0[1] + eps or
            a1[2] <= b0[2] + eps or b1[2] <= a0[2] + eps
        )

    @staticmethod
    def _resolve_solid_for_collision(panel_or_snap, solid_cache: dict | None = None):
        """Строит или берёт из локального кэша B-Rep solid (для снимков не трогает живой Panel)."""
        key = getattr(panel_or_snap, "uid", None) or id(panel_or_snap)
        if solid_cache is not None and key in solid_cache:
            return solid_cache[key]
        if getattr(panel_or_snap, "_is_snapshot", False):
            solid = CADKernel.build_panel_solid(panel_or_snap)
        else:
            solid = getattr(panel_or_snap, "solid", None) or CADKernel.build_panel_solid(panel_or_snap)
        if solid_cache is not None:
            solid_cache[key] = solid
        return solid

    @staticmethod
    def check_collision(
        panel_a,
        panel_b,
        _errors: list | None = None,
        _solid_cache: dict | None = None,
    ) -> float:
        """
        Точная B-Rep проверка физического пересечения двух деталей в OpenCASCADE.
        Возвращает объем пересечения в мм³. Использует broad-phase по world-AABB
        и кэш по geometry_generation (план §2.5).
        При сбое B-Rep логирует исключение и возвращает 0.0 без записи в кэш (ревизия 2, п. 1.6).
        """
        a0, a1 = CADKernel._panel_aabb(panel_a)
        b0, b1 = CADKernel._panel_aabb(panel_b)
        if not CADKernel.aabb_overlaps(a0, a1, b0, b1):
            return 0.0

        tok_a = CADKernel._panel_collision_token(panel_a, (a0, a1))
        tok_b = CADKernel._panel_collision_token(panel_b, (b0, b1))
        cache_key = (tok_a, tok_b) if tok_a <= tok_b else (tok_b, tok_a)
        cached = CADKernel._COLLISION_CACHE.get(cache_key)
        if cached is not None:
            return cached

        vol = 0.0
        try:
            with OCC_LOCK:
                solid_a = CADKernel._resolve_solid_for_collision(panel_a, _solid_cache)
                solid_b = CADKernel._resolve_solid_for_collision(panel_b, _solid_cache)

                common = solid_a & solid_b
                if common is not None:
                    # volume даёт и OCC-solid, и тестовый stub (conftest: AABB-пересечение)
                    vol = float(common.volume)
        except Exception:
            get_logger("cad_kernel").exception("collision failed")
            if _errors is not None:
                _errors.append((panel_a, panel_b))
            return 0.0  # не кэшируем

        if len(CADKernel._COLLISION_CACHE) >= CADKernel._COLLISION_CACHE_MAX:
            CADKernel._COLLISION_CACHE.clear()
        CADKernel._COLLISION_CACHE[cache_key] = vol
        return vol

    @staticmethod
    def find_scene_collisions(
        panels: list,
        min_volume: float = 0.1,
        progress_cb=None,
    ) -> list[tuple]:
        """Пакетный поиск коллизий со стадией broad-phase по world-AABB и кэшем поколений.

        Поддерживает передачу как живых `Panel`, так и неизменяемых снимков `CollisionPanelSnapshot`
        (ревизия 2, п. 1.11 и 2.4). Для пар, где B-Rep проверка завершилась исключением, добавляет
        `(p1, p2, None)`, чтобы анализ отобразил их как «не удалось проверить» (п. 1.6).
        """
        n = len(panels)
        if n < 2:
            if progress_cb is not None:
                progress_cb(0, 0)
            return []
        aabbs = [CADKernel._panel_aabb(p) for p in panels]
        candidates: list[tuple[int, int]] = []
        for i in range(n):
            a0, a1 = aabbs[i]
            for j in range(i + 1, n):
                b0, b1 = aabbs[j]
                if CADKernel.aabb_overlaps(a0, a1, b0, b1):
                    candidates.append((i, j))

        total_pairs = len(candidates)
        if total_pairs == 0:
            if progress_cb is not None:
                progress_cb(0, 0)
            return []

        solid_cache: dict = {}
        results = []
        for idx, (i, j) in enumerate(candidates, start=1):
            p1 = panels[i]
            p2 = panels[j]
            pair_errors: list = []
            vol = CADKernel.check_collision(
                p1, p2, _errors=pair_errors, _solid_cache=solid_cache
            )
            if pair_errors:
                results.append((p1, p2, None))
            elif vol > min_volume:
                results.append((p1, p2, vol))
            if progress_cb is not None:
                progress_cb(idx, total_pairs)
        return results

    @staticmethod
    def format_collision_hit(panel_a, panel_b, vol: float | None) -> str:
        """Форматирует строку результата проверки пары для панели «Анализ пересечений» (ревизия 2, п. 1.6)."""
        name_a = getattr(panel_a, "name", str(panel_a))
        name_b = getattr(panel_b, "name", str(panel_b))
        if vol is None or (isinstance(vol, float) and math.isnan(vol)):
            return f"⚠️ Не удалось проверить: {name_a} <-> {name_b}"
        return f"❌ Пересечение ({int(vol)} мм³): {name_a} <-> {name_b}"