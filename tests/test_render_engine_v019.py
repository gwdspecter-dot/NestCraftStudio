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
        # Умные поля ввода с формулами + Тянуть грань в 3D (Direct Face Push-Pull)
        self.assertIn("def _panel_face_handles", src)
        self.assertIn("def _panel_face_corners_world", src)
        self.assertIn("def _find_face_handle", src)
        self.assertIn("def _cursor_on_face_axis", src)
        self.assertIn("def _apply_face_push_pull", src)

    def test_smart_formula_evaluator_v019(self):
        """Проверяем безопасное вычисление арифметических формул и контекстных переменных детали (w, h, d, t, cur)."""
        from core.formula import context_vars_from_object, eval_math_expression, is_formula_text
        from models.panel import Panel

        self.assertEqual(eval_math_expression("600 - 32"), 568.0)
        self.assertEqual(eval_math_expression("720 / 3"), 240.0)
        self.assertEqual(eval_math_expression("(800 - 3 * 16) / 2"), 376.0)
        self.assertEqual(eval_math_expression("= 568,5 + 15,5"), 584.0)
        self.assertEqual(eval_math_expression("+= 50", current_value=400.0), 450.0)
        self.assertEqual(eval_math_expression("-= 32", current_value=600.0), 568.0)
        self.assertEqual(eval_math_expression("*= 2", current_value=150.0), 300.0)
        self.assertEqual(eval_math_expression("/= 2", current_value=500.0), 250.0)
        self.assertTrue(is_formula_text("600 - 32"))
        self.assertTrue(is_formula_text("+= 50"))
        self.assertFalse(is_formula_text("568"))

        Panel._controller_unbound = True
        try:
            p = Panel("Полка", 16.0, 350.0, 0.0, 568.0, 16.0, 540.0, rebuild=False)
            p.thickness_axis = 1
            ctx = context_vars_from_object(p, current_value=p.width)
            self.assertEqual(ctx["w"], 568.0)
            self.assertEqual(ctx["t"], 16.0)
            self.assertEqual(eval_math_expression("w - 2 * t", variables=ctx), 536.0)
            self.assertEqual(eval_math_expression("cur + t", variables=ctx, current_value=568.0), 584.0)
        finally:
            Panel._controller_unbound = False

    def test_face_push_pull_handles_and_resize_v019(self):
        """Проверяем расчёт центров граней compute_panel_face_handles и растяжение compute_face_push_pull_box."""
        from models.panel import Panel

        Panel._controller_unbound = True
        try:
            p = Panel("Полка", 16.0, 350.0, 0.0, 568.0, 16.0, 500.0, rebuild=False)
            p.thickness_axis = 1

            handles = glmath.compute_panel_face_handles(p)
            # Ось толщины Y (1) пропускается -> остаётся 4 рабочих торца: (-X), (+X), (-Z), (+Z)
            face_ids = [h[0] for h in handles]
            self.assertEqual(face_ids, [(0, 0), (0, 1), (2, 0), (2, 1)])

            orig_box = (p.x, p.y, p.z, p.width, p.height, p.depth)
            # Вытягивание правого торца (+X, face_id=(0, 1)) до длины 600 мм (левый торец x=16.0 остаётся на месте)
            nx, ny, nz, nw, nh, nd = glmath.compute_face_push_pull_box(orig_box, (0, 1), 600.0, panel=p)
            self.assertAlmostEqual(nx, 16.0)
            self.assertAlmostEqual(nw, 600.0)
            self.assertAlmostEqual(ny, 350.0)
            self.assertAlmostEqual(nh, 16.0)

            # Вытягивание левого торца (-X, face_id=(0, 0)) наружу до длины 584 мм (правый торец x+w=584.0 неподвижен, x -> 0.0)
            nx2, ny2, nz2, nw2, nh2, nd2 = glmath.compute_face_push_pull_box(orig_box, (0, 0), 584.0, panel=p)
            self.assertAlmostEqual(nx2, 0.0)
            self.assertAlmostEqual(nw2, 584.0)
            self.assertAlmostEqual(nx2 + nw2, 584.0)
        finally:
            Panel._controller_unbound = False

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

    def test_live_panel_collisions_v019(self):
        """Проверяем быстрый расчёт 3D-пересечений find_live_panel_collisions (касание 0 мм не является коллизией, врезание возвращает бокс пересечения)."""
        from models.panel import Panel

        Panel._controller_unbound = True
        try:
            # Левая стойка [0..16] и полка [16..584] ровно встык — коллизий быть не должно
            left = Panel("Боковина Л", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, rebuild=False)
            shelf_touch = Panel("Полка встык", 16.0, 350.0, 0.0, 568.0, 16.0, 540.0, rebuild=False)
            hits_touch = glmath.find_live_panel_collisions([left, shelf_touch])
            self.assertEqual(len(hits_touch), 0)

            # Полка врезается в левую боковину на 8 мм (x=8.0 -> бокс пересечения x=8, y=350, z=0, w=8, h=16, d=540)
            shelf_overlap = Panel("Полка с врезанием", 8.0, 350.0, 0.0, 568.0, 16.0, 540.0, rebuild=False)
            hits_overlap = glmath.find_live_panel_collisions([left, shelf_overlap])
            self.assertEqual(len(hits_overlap), 1)
            pa, pb, ibox, vol = hits_overlap[0]
            self.assertIs(pa, left)
            self.assertIs(pb, shelf_overlap)
            self.assertEqual(ibox, (8.0, 350.0, 0.0, 8.0, 16.0, 540.0))
            self.assertAlmostEqual(vol, 8.0 * 16.0 * 540.0)
        finally:
            Panel._controller_unbound = False

    def test_mirror_panel_and_linear_array_v019(self):
        """Проверяем зеркальное копирование детали (с отражением кромок, пазов и сверловки) и линейный массив (шаг, просвет, деление проёма)."""
        from core.array_mirror import (
            build_linear_array_panels,
            build_mirror_panel,
            compute_mirror_plane_coord,
        )
        from models.panel import Block, Panel

        Panel._controller_unbound = True
        try:
            blk = Block("Корпус 600", "1", "01.00")
            blk.x = 0.0
            blk.width = 600.0
            left_side = Panel("Боковина левая", 0.0, 0.0, 0.0, 16.0, 720.0, 560.0, rebuild=False)
            left_side.edges = {"left": "ПВХ 2 мм", "right": "ПВХ 0.4 мм", "front": "ПВХ 2 мм"}
            left_side.holes = [(16.0, 100.0, 50.0, 4.0, 12.0, "-X")]
            left_side.grooves = [{"face": "right", "axis": "Y", "offset": 20.0, "width": 4.0, "depth": 8.0}]
            blk.add_panel(left_side)

            plane_x = compute_mirror_plane_coord(left_side, "X", "cabinet", block=blk)
            self.assertAlmostEqual(plane_x, 300.0)

            right_side = build_mirror_panel(
                left_side,
                axis="X",
                plane_coord=plane_x,
                new_name="Боковина правая",
                new_pos_num="1.2",
                mirror_features=True,
            )
            # X: 2*300 - (0 + 16) = 584 мм
            self.assertAlmostEqual(right_side.x, 584.0)
            self.assertEqual(right_side.edges.get("left"), "ПВХ 0.4 мм")
            self.assertEqual(right_side.edges.get("right"), "ПВХ 2 мм")
            # Отверстие на x=16 со стороны -X отражается в x=0 со стороны +X
            self.assertEqual(right_side.holes[0][0], 0.0)
            self.assertEqual(right_side.holes[0][5], "+X")
            # Паз на правой грани отражается на левую грань
            self.assertEqual(right_side.grooves[0]["face"], "left")

            # Линейный массив полок: 3 полки в проёме 688 мм (равные ниши по высоте)
            base_shelf = Panel("Полка", 16.0, 0.0, 0.0, 568.0, 16.0, 540.0, rebuild=False)
            shelves_span = build_linear_array_panels(
                base_shelf,
                axis="Y",
                count=3,
                mode="divide_span",
                value=688.0,
                include_ends=False,
            )
            self.assertEqual(len(shelves_span), 3)
            # Просвет одной ниши: (688 - 3 * 16) / 4 = 640 / 4 = 160 мм -> шаги: 160, 336, 512
            self.assertAlmostEqual(shelves_span[0].y, 160.0)
            self.assertAlmostEqual(shelves_span[1].y, 336.0)
            self.assertAlmostEqual(shelves_span[2].y, 512.0)

            # Линейный массив с чистым просветом 200 мм (шаг = 200 + 16 = 216 мм)
            shelves_gap = build_linear_array_panels(
                base_shelf,
                axis="Y",
                count=2,
                mode="clear_gap",
                value=200.0,
            )
            self.assertEqual(len(shelves_gap), 2)
            self.assertAlmostEqual(shelves_gap[0].y, 216.0)
            self.assertAlmostEqual(shelves_gap[1].y, 432.0)
        finally:
            Panel._controller_unbound = False


if __name__ == "__main__":
    unittest.main()


