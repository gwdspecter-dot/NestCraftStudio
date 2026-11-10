# -*- coding: utf-8 -*-
"""Тесты Пакет 1 улучшений 3D-движка (ревизия 0.0.19):
- Привязанный к камере студийный свет (Key + Fill + Ambient) и разделение тонов взаимно перпендикулярных граней
- Адаптивные плоскости отсечения z_near / z_far (высокая точность буфера глубины вблизи и отсутствие клиппинга вдали)
- Шейдер _SOLID_FS со стабилизацией нормалей (dFdx/dFdy) и аппаратным Polygon Offset
"""
from __future__ import annotations

import os
import unittest

from core import glmath


class TestRenderEngineV019(unittest.TestCase):
    def test_orthogonal_faces_part_in_light(self):
        """Как в faces_part_in_light из QymCAD: три видимые ортогональные грани панели
        при изометрических и рабочих ракурсах камеры всегда имеют различную яркость."""
        camera_angles = [
            (25.0, -35.0),
            (30.0, 45.0),
            (20.0, 135.0),
            (35.0, -125.0),
            (-25.0, 40.0),
        ]
        normals = [
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ]
        for rx, ry in camera_angles:
            key_dir, fill_dir, view_dir = glmath.compute_camera_studio_lights(rx, ry)
            # Ориентируем нормали трёх ортогональных граней лицом к камере
            visible_normals = []
            for nx, ny, nz in normals:
                dot_v = nx * view_dir[0] + ny * view_dir[1] + nz * view_dir[2]
                if dot_v >= 0.0:
                    visible_normals.append((nx, ny, nz))
                else:
                    visible_normals.append((-nx, -ny, -nz))

            lumas = []
            for n in visible_normals:
                r, g, b = glmath.shade_face_studio(n, key_dir, fill_dir, view_dir, (0.8, 0.8, 0.8))
                luma = 0.299 * r + 0.587 * g + 0.114 * b
                lumas.append(luma)

            # Каждая пара из трёх видимых ортогональных граней должна заметно отличаться по тону
            diff_01 = abs(lumas[0] - lumas[1])
            diff_12 = abs(lumas[1] - lumas[2])
            diff_02 = abs(lumas[0] - lumas[2])
            self.assertGreater(
                min(diff_01, diff_12, diff_02),
                0.035,
                f"Грани сливаются по тону при камере ({rx}, {ry}): lumas={lumas}",
            )

    def test_opposite_faces_differ_in_tone(self):
        """Противоположные грани (+N и -N) больше не имеют идентичной яркости (как было при abs(dot))."""
        key_dir, fill_dir, view_dir = glmath.compute_camera_studio_lights(25.0, -35.0)
        front = glmath.shade_face_studio((0.0, 1.0, 0.0), key_dir, fill_dir, view_dir)
        back = glmath.shade_face_studio((0.0, -1.0, 0.0), key_dir, fill_dir, view_dir)
        self.assertGreater(abs(front[0] - back[0]), 0.15)

    def test_adaptive_clip_planes_precision_and_far_range(self):
        """Адаптивный расчёт z_near / z_far сужает диапазон на ближнем зуме и расширяет для далёких деталей."""
        # Ближний план (осмотр крепежа с расстояния 300 мм)
        z_near_close, z_far_close = glmath.compute_adaptive_clip_planes(
            zoom=-300.0, is_ortho=False, scene_radius=800.0
        )
        self.assertGreaterEqual(z_near_close, 1.0)
        ratio_close = z_far_close / z_near_close
        # Раньше фиксированный диапазон 10..50000 давал ratio = 5000; теперь существенно плотнее
        self.assertLess(ratio_close, 1200.0)

        # Огромная сцена (детали разнесены на 40 метров)
        z_near_far, z_far_far = glmath.compute_adaptive_clip_planes(
            zoom=-15000.0, is_ortho=False, scene_radius=45000.0
        )
        self.assertGreater(z_far_far, 100000.0)
        self.assertGreater(z_near_far, 50.0)

        # Ортографическая проекция — симметричный охват
        ortho_near, ortho_far = glmath.compute_adaptive_clip_planes(
            zoom=-1800.0, is_ortho=True, scene_radius=2000.0
        )
        self.assertEqual(ortho_near, -ortho_far)
        self.assertGreaterEqual(ortho_far, 2000.0)

    def test_viewport_shader_has_studio_lights_and_polygon_offset(self):
        """Проверяем наличие dFdx/dFdy, uKeyDir/uFillDir, _scene_bounding_radius по self.blocks и _apply_studio_light_uniforms."""
        vp_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui",
            "viewport.py",
        )
        with open(vp_path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("cross(dFdx(vPos), dFdy(vPos))", src)
        self.assertIn("uniform vec3 uKeyDir;", src)
        self.assertIn("uniform vec3 uFillDir;", src)
        self.assertIn("def _apply_studio_light_uniforms", src)
        self.assertIn("compute_adaptive_clip_planes", src)
        self.assertIn('blocks = getattr(self, "blocks", None)', src)
        self.assertIn("def panels(self)", src)
        # Пакет 3: Screen-Space BBox Cull, кэш точек привязки и удержание VAO/VBO без мигания
        self.assertIn("def _panel_within_screen_radius", src)
        self.assertIn("p.snap_cache_token(label_prefix)", src)
        self.assertIn('entry["dirty"] = True', src)
        self.assertIn('entry.get("pose") == pose', src)
        # Пакет 2: Сечение 3D-вида (GL_CLIP_DISTANCE0) + Призраки окружения (Isolate / Ghost Others)
        self.assertIn("GL_CLIP_DISTANCE0", src)
        self.assertIn("gl_ClipDistance[0] = dot(vec4(aPos, 1.0), uClipPlane);", src)
        self.assertIn("def toggle_section_mode", src)
        self.assertIn("def toggle_ghost_others_mode", src)
        self.assertIn("def _draw_section_plane_gizmo", src)

    def test_section_clip_plane_and_axis_bounds_v019(self):
        """Проверяем расчёт плоскости сечения compute_section_clip_plane, фильтр point_passes_clip_plane и габариты compute_scene_axis_bounds."""
        from models.panel import Panel

        # По умолчанию (flip=False) оставляем область coord <= offset: -coord + offset >= 0
        plane_z = glmath.compute_section_clip_plane("Z", 300.0, flip=False)
        self.assertEqual(plane_z, (0.0, 0.0, -1.0, 300.0))
        self.assertTrue(glmath.point_passes_clip_plane(100.0, 200.0, 150.0, plane_z))
        self.assertTrue(glmath.point_passes_clip_plane(100.0, 200.0, 300.0, plane_z))
        self.assertFalse(glmath.point_passes_clip_plane(100.0, 200.0, 420.0, plane_z))

        # При flip=True оставляем область coord >= offset: +coord - offset >= 0
        plane_z_flip = glmath.compute_section_clip_plane("Z", 300.0, flip=True)
        self.assertEqual(plane_z_flip, (0.0, 0.0, 1.0, -300.0))
        self.assertFalse(glmath.point_passes_clip_plane(100.0, 200.0, 150.0, plane_z_flip))
        self.assertTrue(glmath.point_passes_clip_plane(100.0, 200.0, 420.0, plane_z_flip))

        Panel._controller_unbound = True
        try:
            p1 = Panel("Левая", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, rebuild=False)
            p2 = Panel("Правая", 584.0, 0.0, 0.0, 16.0, 720.0, 560.0, rebuild=False)
            self.assertEqual(glmath.compute_scene_axis_bounds([p1, p2], "X"), (0.0, 600.0))
            self.assertEqual(glmath.compute_scene_axis_bounds([p1, p2], "Y"), (0.0, 720.0))
            self.assertEqual(glmath.compute_scene_axis_bounds([p1, p2], "Z"), (0.0, 560.0))
        finally:
            Panel._controller_unbound = False

    def test_panel_spatial_and_snap_cache_v019(self):
        """Проверяем кэширование world_corners(), pose_key(), snap_cache_token() и инвалидацию при rebuild_geometry()."""
        from models.panel import Panel

        Panel._controller_unbound = True
        try:
            p = Panel("Боковина", 10, 20, 30, 16, 720, 560, rebuild=False)
            c1 = p.world_corners()
            self.assertEqual(len(c1), 8)
            self.assertEqual(p._corners_cache_key, p.pose_key())
            # Повторный вызов возвращает данные из кэша по тому же ключу
            c2 = p.world_corners()
            self.assertEqual(c1, c2)

            tok1 = p.snap_cache_token("Боковина")
            p.holes.append((8.0, 100.0, 50.0, 3.5, 16.0, "X"))
            tok2 = p.snap_cache_token("Боковина")
            self.assertNotEqual(tok1, tok2)

            p._snap_cache_key = tok2
            p._snap_cache_data = [("dummy",)]
            p.rebuild_geometry()
            self.assertIsNone(p._snap_cache_key)
            self.assertIsNone(p._snap_cache_data)
            self.assertIsNone(p._corners_cache_key)
        finally:
            Panel._controller_unbound = False


if __name__ == "__main__":
    unittest.main()

