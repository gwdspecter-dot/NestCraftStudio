"""Unit-тесты п. 1.5 плана: поддержка поворота (OBB, local_to_world / world_to_local, стыки и отверстия на повёрнутых панелях)."""

from __future__ import annotations

import math
import unittest

import tests.conftest as _conf

_conf.pytest_configure(None)

import numpy as np
from models.panel import Panel
from core.joint import find_joint, make_joint_holes, world_to_local_hole


class TestRotationOBB15(unittest.TestCase):
    def test_local_to_world_and_world_to_local_roundtrip(self):
        """Для любых углов (rx, ry, rz) перевод local_to_world → world_to_local обратим."""
        p = Panel("RotPanel", 120.0, 45.0, -30.0, 600.0, 400.0, 16.0, rebuild=False)
        p.rx, p.ry, p.rz = 25.0, -40.0, 90.0

        test_pts = [
            (0.0, 0.0, 0.0),
            (600.0, 400.0, 16.0),
            (300.0, 200.0, 8.0),
            (50.0, 120.0, 4.0),
        ]
        for lx, ly, lz in test_pts:
            wx, wy, wz = p.local_to_world(lx, ly, lz)
            rlx, rly, rlz = p.world_to_local(wx, wy, wz)
            self.assertAlmostEqual(lx, rlx, places=6)
            self.assertAlmostEqual(ly, rly, places=6)
            self.assertAlmostEqual(lz, rlz, places=6)

    def test_obb_orthonormal_axes_and_extents(self):
        """Panel.obb() возвращает мировой центр, 3 ортонормированные оси и полуразмеры."""
        p = Panel("OBBPanel", 10.0, 20.0, 30.0, 500.0, 300.0, 16.0, rebuild=False)
        p.rx, p.ry, p.rz = 0.0, 0.0, 45.0
        center, axes, half = p.obb()

        self.assertEqual(half, (250.0, 150.0, 8.0))
        wc = p.local_to_world(250.0, 150.0, 8.0)
        for a, b in zip(center, wc):
            self.assertAlmostEqual(a, b, places=6)

        # Ортонормированность осей
        for i in range(3):
            norm_i = math.sqrt(sum(c * c for c in axes[i]))
            self.assertAlmostEqual(norm_i, 1.0, places=6)
            for j in range(i + 1, 3):
                dot_ij = sum(axes[i][k] * axes[j][k] for k in range(3))
                self.assertAlmostEqual(dot_ij, 0.0, places=6)

        # Восстановление 8 углов из OBB совпадает с world_corners()
        obb_corners = set()
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    cx = center[0] + sx * half[0] * axes[0][0] + sy * half[1] * axes[1][0] + sz * half[2] * axes[2][0]
                    cy = center[1] + sx * half[0] * axes[0][1] + sy * half[1] * axes[1][1] + sz * half[2] * axes[2][1]
                    cz = center[2] + sx * half[0] * axes[0][2] + sy * half[1] * axes[1][2] + sz * half[2] * axes[2][2]
                    obb_corners.add((round(cx, 4), round(cy, 4), round(cz, 4)))
        wc_set = {(round(x, 4), round(y, 4), round(z, 4)) for x, y, z in p.world_corners()}
        self.assertEqual(obb_corners, wc_set)

    def test_find_joint_and_make_holes_on_90deg_rotated_panel(self):
        """
        Горизонтальная панель, созданная вертикальной (16x700x500) и повернутая на rz = -90° вокруг своего центра:
        мировой центр должен быть (366, 8, 250), чтобы её мировой бокс был X in [16, 716], Y in [0, 16], Z in [0, 500].
        Тогда x = 366 - 8 = 358, y = 8 - 350 = -342, z = 0.
        Она стыкуется с левой вертикальной боковиной X in [0, 16], Y in [0, 720], Z in [0, 500] по плоскости X=16.
        """
        side = Panel("Боковина", 0.0, 0.0, 0.0, 16.0, 720.0, 500.0, rebuild=False)
        shelf_rot = Panel("Полка повёрнутая", 358.0, -342.0, 0.0, 16.0, 700.0, 500.0, rebuild=False)
        shelf_rot.rz = -90.0

        (xmin, ymin, zmin), (xmax, ymax, zmax) = shelf_rot.world_aabb()
        self.assertAlmostEqual(xmin, 16.0, places=5)
        self.assertAlmostEqual(xmax, 716.0, places=5)
        self.assertAlmostEqual(ymin, 0.0, places=5)
        self.assertAlmostEqual(ymax, 16.0, places=5)

        j = find_joint(side, shelf_rot)
        self.assertIsNotNone(j, "find_joint должен находить стык для повернутой на 90° панели через OBB")
        self.assertAlmostEqual(float(j.origin[0]), 16.0, places=4)

        # Ставим крепёж в середине стыка (X=16, Y=8, Z=250)
        pt = np.array([16.0, 8.0, 250.0], dtype=float)
        ha, hb = make_joint_holes(j, pt, diameter=7.0, depth=42.0)

        # У боковины (не повернута) сверление вдоль X
        self.assertEqual(ha[5], "X")
        # У повернутой на -90° вокруг Z полки мировая ось X соответствует её локальной оси Y!
        self.assertEqual(hb[5], "Y")

        # Проверяем, что локальные координаты отверстия в shelf_rot при переводе в мир дают Y=8, Z=250
        wx, wy, wz = shelf_rot.local_to_world(hb[0], hb[1], hb[2])
        self.assertAlmostEqual(wy, 8.0, places=4)
        self.assertAlmostEqual(wz, 250.0, places=4)

    def test_find_joint_on_45deg_corotated_panels(self):
        """Две соосно повернутые на 45° панели, касающиеся гранями, находятся через OBB find_joint."""
        p1 = Panel("P1", 0.0, 0.0, 0.0, 16.0, 400.0, 500.0, rebuild=False)
        p1.rz = 45.0
        c1 = p1.world_center()
        dx, dy, dz = p1.rotate_vector(8.0 + 150.0, 0.0, 0.0)
        c2 = (c1[0] + dx, c1[1] + dy, c1[2] + dz)
        p2 = Panel("P2", c2[0] - 150.0, c2[1] - 200.0, c2[2] - 250.0, 300.0, 400.0, 500.0, rebuild=False)
        p2.rz = 45.0

        j = find_joint(p1, p2)
        self.assertIsNotNone(j, "find_joint должен находить стык двух повернутых на 45° панелей")
        ax_x = p1.rotate_vector(1.0, 0.0, 0.0)
        dot = abs(float(j.drill_dir[0]) * ax_x[0] + float(j.drill_dir[1]) * ax_x[1] + float(j.drill_dir[2]) * ax_x[2])
        self.assertAlmostEqual(dot, 1.0, places=5)

    def test_world_to_local_hole_rotated(self):
        """world_to_local_hole корректно переводит мировую точку входа и направление в локальную ось повернутой панели."""
        p = Panel("P", 100.0, 50.0, 0.0, 400.0, 300.0, 16.0, rebuild=False)
        p.rz = 90.0
        # Локальная точка на грани lx=0, ly=150, lz=8; направление сверления вдоль локальной оси X
        w0 = np.array(p.local_to_world(0.0, 150.0, 8.0), dtype=float)
        drill_dir = np.array(p.rotate_vector(1.0, 0.0, 0.0), dtype=float)
        hx, hy, hz, r, length, axis = world_to_local_hole(
            p, w0, drill_axis="Y", depth=34.0, radius=3.5, drill_dir=drill_dir
        )
        self.assertEqual(axis, "X")
        self.assertAlmostEqual(hx, 0.0, places=5)
        self.assertAlmostEqual(hy, 150.0, places=5)
        self.assertAlmostEqual(hz, 8.0, places=5)
        self.assertAlmostEqual(length, 34.0, places=5)


if __name__ == "__main__":
    unittest.main()
