"""tools/stage_layer.py: the stage of a model MMD draws (a street, a hall), laid behind the dancer in place of mv_world's."""
import importlib.util
import math
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy
    from PIL import Image  # noqa: F401
except ImportError:                                   # the tool needs Pillow and numpy; the rest of the suite does not
    numpy = None

if numpy is not None:
    sys.path.insert(0, ROOT)
    from mmd_cli import fk
    from tests.test_pmx import Writer


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage_layer = load("stage_layer") if numpy is not None else None
mv_world = load("mv_world") if numpy is not None else None
SIZE = (160, 90)


def view(look_at=(0.0, 0.0, 0.0), distance=40.0, angles=(15.0, 0.0, 0.0), fov=30.0, size=SIZE):
    """mv_world's View of a camera state: by default 40 in front of the origin, looking down at it by 15 degrees"""
    return mv_world.View(fk.CameraState(0, tuple(look_at), float(distance), tuple(angles), float(fov)), size)


def mesh(triangles, materials=None, face_material=None):
    """a Mesh of triangles ((a, b, c) world points each), every one of its own vertices; materials default to one
    single-sided material"""
    tri = numpy.asarray(triangles, dtype=numpy.float64).reshape(-1, 3, 3)
    mats = materials or [stage_layer.Material("m", flags=0, power=5.0, alpha=1.0)]
    fm = numpy.zeros(len(tri), dtype=numpy.int64) if face_material is None else numpy.asarray(face_material, dtype=numpy.int64)
    return stage_layer.Mesh(tri.reshape(-1, 3), numpy.arange(3 * len(tri)).reshape(-1, 3), fm, mats)


def quad(y, x0, x1, z0, z1, up=True):
    """two triangles of the floor y between x0..x1 and z0..z1, their front facing up (or down)"""
    a, b, c, d = (x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0)
    return [(a, b, c), (a, c, d)] if up else [(a, c, b), (a, d, c)]


def wall(z, x0, x1, y0, y1, towards_minus_z=True):
    """two triangles of the wall z between x0..x1 and y0..y1, their front facing -z (the camera in front) or +z"""
    a, b, c, d = (x0, y0, z), (x0, y1, z), (x1, y1, z), (x1, y0, z)
    return [(a, b, c), (a, c, d)] if towards_minus_z else [(a, c, b), (a, d, c)]


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class RasterTest(unittest.TestCase):
    def test_a_floor_has_the_depth_where_mv_worlds_floor_has_it(self):
        v = view()
        depth, face = stage_layer.rasterize(v, mesh(quad(0.0, -500, 500, -30, 500)))
        want = mv_world.floor_depth(v, 0.0)
        seen = numpy.isfinite(depth)
        self.assertGreater(seen.mean(), 0.5)
        numpy.testing.assert_allclose(depth[seen], want[seen], rtol=1e-9)
        self.assertTrue((face[seen] >= 0).all() and (face[~seen] == -1).all())

    def test_a_floor_running_behind_the_camera_is_cut_at_the_near_plane_and_still_drawn_to_the_bottom(self):
        v = view(distance=20.0, angles=(30.0, 0.0, 0.0))
        depth, _ = stage_layer.rasterize(v, mesh(quad(0.0, -500, 500, -500, 500)))
        want = mv_world.floor_depth(v, 0.0)
        self.assertTrue(numpy.isfinite(depth[-1]).all())            # the bottom row looks at the floor near the camera
        numpy.testing.assert_allclose(depth[numpy.isfinite(want)], want[numpy.isfinite(want)], rtol=1e-9)

    def test_the_nearer_of_two_faces_wins_whichever_comes_first(self):
        v = view(angles=(0.0, 0.0, 0.0))
        near, far = wall(5.0, -50, 50, -50, 50), wall(20.0, -50, 50, -50, 50)
        for order in ((near + far, (0, 1)), (far + near, (2, 3))):
            depth, face = stage_layer.rasterize(v, mesh(order[0]))
            middle = (SIZE[1] // 2, SIZE[0] // 2)
            self.assertAlmostEqual(depth[middle], 40.0 + 5.0, places=9)     # the eye is 40 in front of the origin
            self.assertIn(int(face[middle]), order[1])

    def test_a_face_whose_back_is_seen_is_not_drawn_unless_it_is_drawn_on_both_sides(self):
        v = view(angles=(0.0, 0.0, 0.0))
        back = wall(5.0, -50, 50, -50, 50, towards_minus_z=False)
        depth, _ = stage_layer.rasterize(v, mesh(back))
        self.assertFalse(numpy.isfinite(depth).any())
        both = [stage_layer.Material("both", flags=stage_layer.BOTH_SIDES, power=5.0, alpha=1.0)]
        depth, _ = stage_layer.rasterize(v, mesh(back, materials=both))
        self.assertTrue(numpy.isfinite(depth).all())

    def test_a_point_of_a_face_lands_on_the_pixel_mv_world_projects_it_to(self):
        v = view(look_at=(3.0, 5.0, 2.0), distance=30.0, angles=(10.0, 25.0, 0.0), size=(320, 180))
        tri = [((-2.0, 4.0, 6.0), (6.0, 9.0, 3.0), (5.0, 1.0, -1.0))]
        tri = tri if numpy.dot(numpy.cross(numpy.subtract(tri[0][1], tri[0][0]), numpy.subtract(tri[0][2], tri[0][0])),
                               v.eye - numpy.asarray(tri[0][0])) > 0 else [(tri[0][0], tri[0][2], tri[0][1])]
        depth, _ = stage_layer.rasterize(v, mesh(tri))
        # the pixels drawn are those whose centres (pixel i at i) lie inside the corners as mv_world projects them
        us, ws, _ = v.project(tri[0])
        px, py = numpy.meshgrid(numpy.arange(320.0), numpy.arange(180.0))

        def side(i, j):
            return (us[j] - us[i]) * (py - ws[i]) - (ws[j] - ws[i]) * (px - us[i])
        s = [side(0, 1), side(1, 2), side(2, 0)]
        inside = ((s[0] >= 0) & (s[1] >= 0) & (s[2] >= 0)) | ((s[0] <= 0) & (s[1] <= 0) & (s[2] <= 0))
        self.assertGreater(inside.sum(), 200)
        drawn = numpy.isfinite(depth)
        self.assertLessEqual(int((drawn != inside).sum()), 2)      # (a centre on an edge may go either way)
        # and the depth there is the distance along the line of sight to the face's plane
        n = numpy.cross(numpy.subtract(tri[0][1], tri[0][0]), numpy.subtract(tri[0][2], tri[0][0]))
        rays = v.rays(1)
        t = numpy.dot(numpy.asarray(tri[0][0]) - v.eye, n) / (rays @ n)
        numpy.testing.assert_allclose(depth[drawn], (t * v.focal)[drawn], rtol=1e-9)

    def test_the_compiled_and_the_plain_rasterizer_draw_the_same(self):
        if not stage_layer.has_numba():
            self.skipTest("numba is not installed: the plain rasterizer is the only one")
        rng = numpy.random.default_rng(5)
        tris = []
        for _ in range(300):
            c = rng.uniform((-30, -5, -10), (30, 25, 60))
            tris.append(c + rng.normal(0.0, 4.0, size=(3, 3)))
        big = quad(0.0, -400, 400, -400, 800)
        m = mesh(tris + big, materials=[stage_layer.Material("both", flags=stage_layer.BOTH_SIDES, power=5.0, alpha=1.0)])
        v = view(distance=35.0, angles=(12.0, 10.0, 0.0))
        d1, f1 = stage_layer.rasterize(v, m, compiled=True)
        d2, f2 = stage_layer.rasterize(v, m, compiled=False)
        same = numpy.isfinite(d1) == numpy.isfinite(d2)
        self.assertGreater(same.mean(), 0.999)                    # (a pixel centre on an edge may go either way)
        both = numpy.isfinite(d1) & numpy.isfinite(d2)
        self.assertLess(numpy.abs(d1[both] - d2[both]).max() / d1[both].max(), 1e-9)


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class SurfaceTest(unittest.TestCase):
    def test_the_points_of_a_floor_lie_on_it_and_its_normal_is_up(self):
        v = view()
        m = mesh(quad(1.5, -500, 500, -30, 500))
        depth, face = stage_layer.rasterize(v, m)
        s = stage_layer.surface(v, depth, face, m)
        self.assertTrue((s.seen == numpy.isfinite(depth)).all())
        numpy.testing.assert_allclose(s.points[s.seen][:, 1], 1.5, atol=1e-9)
        numpy.testing.assert_allclose(s.normals[s.seen], [[0.0, 1.0, 0.0]] * int(s.seen.sum()), atol=1e-12)
        self.assertTrue((s.material[s.seen] == 0).all() and (s.material[~s.seen] == -1).all())

    def test_a_normal_faces_the_camera_even_on_a_face_drawn_from_its_back(self):
        v = view(angles=(0.0, 0.0, 0.0))
        both = [stage_layer.Material("both", flags=stage_layer.BOTH_SIDES, power=5.0, alpha=1.0)]
        m = mesh(wall(5.0, -50, 50, -50, 50, towards_minus_z=False), materials=both)
        depth, face = stage_layer.rasterize(v, m)
        s = stage_layer.surface(v, depth, face, m)
        numpy.testing.assert_allclose(s.normals[s.seen], [[0.0, 0.0, -1.0]] * int(s.seen.sum()), atol=1e-12)

    def test_the_offset_moves_the_model(self):
        v = view()
        m = mesh(quad(0.0, -500, 500, -30, 500))
        moved = stage_layer.placed(m, (0.0, 2.0, 0.0))
        depth, _ = stage_layer.rasterize(v, moved)
        want = mv_world.floor_depth(v, 2.0)
        ok = numpy.isfinite(depth)
        numpy.testing.assert_allclose(depth[ok], want[ok], rtol=1e-9)
        self.assertEqual(m.positions[:, 1].max(), 0.0)              # the model itself is not changed


def pmx_bytes(points, faces, materials):
    """a PMX 2.0 file of the given vertices (positions; normal up, uv 0), faces and materials ((name, flags, power,
    alpha, face count)), every vertex on bone 0"""
    w = Writer(vertex=2)
    verts = [struct.pack("<8f", x, y, z, 0, 1, 0, 0, 0) + b"\x00" + w.index(0, "bone") + struct.pack("<f", 1.0)
             for x, y, z in points]
    face_bytes = [w.index(i, "vertex") for f in faces for i in f]
    mats = []
    for name, flags, power, alpha, count in materials:
        mats.append(w.text(name) + w.text("") + struct.pack("<4f3ff3f", 0.8, 0.8, 0.8, alpha, 0, 0, 0, power, 0.4, 0.4, 0.4)
                    + bytes([flags]) + struct.pack("<4ff", 0, 0, 0, 1, 1) + w.index(-1, "texture") + w.index(-1, "texture")
                    + b"\x00" + b"\x01" + b"\x00" + w.text("") + struct.pack("<i", 3 * count))
    return w.build(vertices=verts, faces=face_bytes, materials=mats, bones=[w.bone("全ての親")])


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class MeshFileTest(unittest.TestCase):
    def test_a_pmx_is_read_with_its_faces_materials_and_their_flags(self):
        points = [(0, 0, 0), (0, 0, 1), (1, 0, 1), (0, 5, 3), (2, 5, 3), (0, 7, 3)]
        data = pmx_bytes(points, [(0, 1, 2), (3, 4, 5)], [("床", 0, 5.0, 1.0, 1), ("看板", stage_layer.BOTH_SIDES, 105.0, 1.0, 1)])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stage.pmx")
            with open(path, "wb") as f:
                f.write(data)
            m = stage_layer.load_mesh(path)
        numpy.testing.assert_allclose(m.positions, points)
        self.assertEqual(m.faces.tolist(), [[0, 1, 2], [3, 4, 5]])
        self.assertEqual(m.face_material.tolist(), [0, 1])
        self.assertEqual([x.name for x in m.materials], ["床", "看板"])
        self.assertEqual([x.flags for x in m.materials], [0, stage_layer.BOTH_SIDES])
        self.assertEqual([x.power for x in m.materials], [5.0, 105.0])
        self.assertEqual(m.material_index("看板"), 1)
        with self.assertRaises(ValueError):
            m.material_index("無い")

    def test_faces_of_a_material_mmd_does_not_draw_are_left_out(self):
        clear = [stage_layer.Material("glass", flags=0, power=5.0, alpha=0.0), stage_layer.Material("m", flags=0, power=5.0, alpha=1.0)]
        v = view(angles=(0.0, 0.0, 0.0))
        m = mesh(wall(5.0, -50, 50, -50, 50) + wall(20.0, -50, 50, -50, 50), materials=clear, face_material=[0, 0, 1, 1])
        depth, _ = stage_layer.rasterize(v, m)
        self.assertAlmostEqual(depth[SIZE[1] // 2, SIZE[0] // 2], 60.0, places=9)     # through the clear glass to the wall


if __name__ == "__main__":
    unittest.main()
