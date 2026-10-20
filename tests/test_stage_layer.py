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


LIGHT = (-0.5, -1.0, 0.5)                             # MMD's light (where it shines to)


def floor_points(xs, zs, y=0.0):
    gx, gz = numpy.meshgrid(xs, zs)
    return numpy.stack([gx.ravel(), numpy.full(gx.size, y), gz.ravel()], axis=1)


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class ShadowTest(unittest.TestCase):
    CAPSULES = [((0.0, 6.0, 0.0), (0.0, 10.0, 0.0), 1.2), ((-1.0, 0.42, 0.5), (-1.2, 0.42, -1.0), 0.42),
                ((0.3, 14.5, 0.1), (0.3, 16.0, 0.1), 1.55)]
    GROUPS = ["torso", "left foot", "head"]

    def exact(self, P, capsules, groups):
        """mv_world's shadow at every point itself: per part the most any capsule keeps off the key light, the parts
        multiplied; the light from all round multiplied capsule by capsule (soft_shadow_grid's sums without its grid)"""
        ell = mv_world.toward_light(LIGHT)
        held = {}
        contact = numpy.ones(len(P))
        y = P[0, 1]
        for (a, b, r), g in zip(capsules, groups):
            a, b = numpy.subtract(a, (0, y, 0)), numpy.subtract(b, (0, y, 0))
            flat = P - [0.0, y, 0.0]
            held[g] = numpy.maximum(held.get(g, numpy.zeros(len(P))), mv_world.capsule_key(flat, a, b, r, ell, math.radians(5.0)))
            contact *= 1.0 - mv_world.capsule_contact(flat, a, b, r)
        key = numpy.ones(len(P))
        for kept in held.values():
            key *= 1.0 - kept
        return key, contact

    def test_on_a_floor_the_shadow_is_mv_worlds_at_every_point(self):
        for y in (0.0, 1.0):
            capsules = [(numpy.add(a, (0, y, 0)), numpy.add(b, (0, y, 0)), r) for a, b, r in self.CAPSULES]
            P = floor_points(numpy.linspace(-12, 6, 61), numpy.linspace(-6, 14, 67), y)
            key, contact = stage_layer.shadow_at(P, [[0.0, 1.0, 0.0]] * len(P), capsules, self.GROUPS, LIGHT, 5.0)
            want_key, want_contact = self.exact(P, capsules, self.GROUPS)
            # (past the box of each capsule's shadow, 4 standard deviations of the light's spread out, it keeps off under
            # 1e-4 of the light, and is not worked out: as mv_world's grid)
            numpy.testing.assert_allclose(key, want_key, atol=2e-4)
            numpy.testing.assert_allclose(contact, want_contact, atol=1e-9)
            self.assertLess(float(key.min()), 0.05)                     # a shadow is there to get right
            self.assertLess(float(contact.min()), 0.2)                  # under the sole

    def test_away_from_a_sharp_edge_it_is_the_shadow_of_mv_worlds_grid(self):
        # the grid (cells of 0.08) blurs the sole's sharp edge on the floor; the shadows of the body high above it gives
        high = self.CAPSULES[::2]
        P = floor_points(numpy.linspace(-12, 6, 61), numpy.linspace(-6, 14, 67))
        key, contact = stage_layer.shadow_at(P, [[0.0, 1.0, 0.0]] * len(P), high, ["torso", "head"], LIGHT, 5.0)
        want_key, want_contact = mv_world.soft_shadow_grid(high, LIGHT, 5.0, groups=["torso", "head"]).at(P[:, 0], P[:, 2])
        self.assertLess(float(numpy.abs(key - want_key).max()), 0.01)
        self.assertLess(float(numpy.abs(contact - want_contact).max()), 0.01)

    def test_a_step_takes_the_shadow_at_its_own_height(self):
        # a kerb 1 high beside her: on it the shadow is the one of a floor at 1, beside it the one of a floor at 0
        P = numpy.concatenate([floor_points(numpy.linspace(-12, -4, 17), [6.0], 1.0),
                               floor_points(numpy.linspace(-3, 3, 13), [6.0])])
        key, _ = stage_layer.shadow_at(P, [[0.0, 1.0, 0.0]] * len(P), self.CAPSULES, self.GROUPS, LIGHT, 5.0)
        on_kerb = mv_world.soft_shadow_grid(self.CAPSULES, LIGHT, 5.0, floor_y=1.0, groups=self.GROUPS).at(P[:17, 0], P[:17, 2])[0]
        on_floor = mv_world.soft_shadow_grid(self.CAPSULES, LIGHT, 5.0, groups=self.GROUPS).at(P[17:, 0], P[17:, 2])[0]
        numpy.testing.assert_allclose(key, numpy.concatenate([on_kerb, on_floor]), atol=0.02)
        self.assertLess(float(key.min()), 0.5)

    def test_a_wall_behind_her_takes_her_shadow_where_the_light_carries_it(self):
        # the light shines to -x, down and +z: a wall at z = 2 facing -z behind a ball 5 up at the origin is shaded round
        # where the ray from the ball along the light meets it (x -2, y 1), lit far from there
        ball = [((0.0, 5.0, 0.0), (0.0, 5.0, 0.0), 1.0)]
        P = numpy.array([(-2.0, 1.0, 2.0), (6.0, 1.0, 2.0), (-2.0, 12.0, 2.0)])
        n = [[0.0, 0.0, -1.0]] * 3
        key, _ = stage_layer.shadow_at(P, n, ball, None, LIGHT, 3.0)
        self.assertLess(key[0], 0.1)
        self.assertGreater(key[1], 0.999)
        self.assertGreater(key[2], 0.999)

    def test_on_a_floor_what_it_keeps_is_mv_worlds_soft_light(self):
        stage = dict(shadow=1.0, shadow_light=list(LIGHT), shadow_contact=0.9, shadow_key=0.6)
        key = numpy.array([0.0, 0.3, 1.0, 1.0])
        contact = numpy.array([1.0, 0.5, 0.2, 1.0])
        got = stage_layer.soft_light_at(key, contact, [[0.0, 1.0, 0.0]] * 4, stage)
        numpy.testing.assert_allclose(got, mv_world.soft_light(key, contact, stage), atol=1e-12)

    def test_a_face_turned_from_the_key_light_loses_none_of_it_and_one_facing_it_more_loses_more(self):
        stage = dict(shadow=1.0, shadow_light=list(LIGHT), shadow_contact=0.9, shadow_key=0.6)
        ell = -numpy.asarray(LIGHT) / numpy.linalg.norm(LIGHT)
        away = stage_layer.soft_light_at(numpy.zeros(1), numpy.ones(1), [-ell], stage)
        floor = stage_layer.soft_light_at(numpy.zeros(1), numpy.ones(1), [[0.0, 1.0, 0.0]], stage)
        facing = stage_layer.soft_light_at(numpy.zeros(1), numpy.ones(1), [ell], stage)
        self.assertAlmostEqual(float(away[0]), 1.0, places=12)
        self.assertAlmostEqual(float(floor[0]), 0.4, places=12)
        self.assertLess(float(facing[0]), float(floor[0]))


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class LampTest(unittest.TestCase):
    LAYER = {"lamp_colour": [255.0, 214.0, 170.0], "lamp_reach": 40.0, "lamp_spot": 2.0}

    def test_a_lamp_lights_the_floor_under_it_most_and_nothing_that_faces_away(self):
        P = numpy.array([(0.0, 0.0, 0.0), (30.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
        n = numpy.array([(0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)])
        for compiled in (False, True) if stage_layer.has_numba() else (False,):
            got = stage_layer.lamp_light(P, n, [(0.0, 20.0, 0.0)], self.LAYER, compiled=compiled)
            self.assertAlmostEqual(float(got[0, 0]), 1.0 / (1.0 + (20.0 / 40.0) ** 2), places=12)
            self.assertLess(got[1, 0], got[0, 0])
            self.assertEqual(float(got[2].max()), 0.0)
            numpy.testing.assert_allclose(got[0] / got[0, 0], numpy.array(self.LAYER["lamp_colour"]) / 255.0)

    def test_the_compiled_and_the_plain_lamps_agree(self):
        if not stage_layer.has_numba():
            self.skipTest("numba is not installed")
        rng = numpy.random.default_rng(2)
        P = rng.uniform(-50, 50, size=(500, 3))
        n = rng.normal(size=(500, 3))
        n /= numpy.linalg.norm(n, axis=1, keepdims=True)
        lamps = rng.uniform(-60, 60, size=(7, 3))
        numpy.testing.assert_allclose(stage_layer.lamp_light(P, n, lamps, self.LAYER, compiled=True),
                                      stage_layer.lamp_light(P, n, lamps, self.LAYER, compiled=False), rtol=1e-9, atol=1e-12)


def lit_scene(size=(320, 180)):
    """a floor (y 0, material 0) and a wall standing on it 20 behind the origin (z 20, y 0..8, material 1), seen from 40 in
    front of a point 4 up, looking down by 10 degrees"""
    mats = [stage_layer.Material("floor"), stage_layer.Material("sign", power=105.0)]
    tris = quad(0.0, -60, 60, -60, 120) + wall(20.0, -10, 10, 0, 8)
    m = mesh(tris, materials=mats, face_material=[0, 0, 1, 1])
    v = view(look_at=(0.0, 4.0, 0.0), distance=40.0, angles=(10.0, 0.0, 0.0), size=size)
    return m, v


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class ReflectionTest(unittest.TestCase):
    def test_a_bright_wall_on_the_floor_is_mirrored_under_it(self):
        m, v = lit_scene()
        depth, face = stage_layer.rasterize(v, m)
        s = stage_layer.surface(v, depth, face, m)
        colour = numpy.where((s.material == 1)[..., None], 240.0, 10.0) * numpy.ones(3)
        self.assertEqual(stage_layer.floor_levels(s), [0.0])
        mirror, got = stage_layer.reflection(v, s, colour, [0.0])
        # the wall's mirror image: its points (x, -y, 20) seen through the floor
        u, w, _ = v.project([(0.0, -4.0, 20.0), (0.0, -2.0, 20.0), (5.0, -6.0, 20.0)])
        for x, y in zip(u, w):
            self.assertTrue(got[int(round(y)), int(round(x))], (x, y))
            self.assertAlmostEqual(float(mirror[int(round(y)), int(round(x)), 0]), 240.0, places=6)
        # beyond the mirror image (a mirrored point 12 below the floor: past the wall's height)
        u, w, _ = v.project([(0.0, -12.0, 20.0)])
        self.assertFalse(got[int(round(w[0])), int(round(u[0]))])
        # nothing is mirrored but on the floor
        self.assertFalse(got[s.material != 0].any())

    def test_the_gaps_between_mirrored_points_are_filled(self):
        img = numpy.zeros((40, 40, 3))
        got = numpy.zeros((40, 40), bool)
        img[::3, ::3] = 200.0
        got[::3, ::3] = True
        filled = stage_layer.fill_holes(img, got, 1.0)
        self.assertGreater(float(filled[10:30, 10:30].min()), 150.0)


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class DefocusTest(unittest.TestCase):
    def test_opencv_blurs_by_depth_as_mv_world_does(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is not installed")
        rng = numpy.random.default_rng(4)
        img = rng.uniform(0, 300, size=(90, 160, 3))
        sigma = numpy.tile(numpy.linspace(0.0, 9.0, 160), (90, 1))
        a = stage_layer.defocus(img, sigma)
        b = mv_world.defocus(img, sigma)
        self.assertLess(float(numpy.abs(a - b).max()), 0.5)
        self.assertLess(float(numpy.abs(a - b).mean()), 0.02)


def layer_look(stage=None, **layer):
    """mv_look's look with the stage of a model on (layer.on 1) and the settings given"""
    mv_look = load("mv_look")
    return mv_look.merge_look({"stage": dict({"world": 1}, **(stage or {})), "layer": dict({"on": 1}, **layer)})


def scene_still(look, size=(320, 180)):
    """the Still of lit_scene's camera over a picture MMD might draw of it: the floor 100 grey, the wall (emissive) 200,
    nothing (alpha 0) where no face is"""
    m, v = lit_scene(size)
    depth, face = stage_layer.rasterize(v, m)
    s = stage_layer.surface(v, depth, face, m)
    picture = numpy.where((s.material == 0)[..., None], 100.0, numpy.where((s.material == 1)[..., None], 200.0, 0.0)) * numpy.ones(3)
    spec = stage_layer.check_set({"model": "unused.pmx", "emissive": ["sign"], "lamps": [[0.0, 30.0, 10.0]]})
    table = stage_layer.emissive_table(m, spec)
    return stage_layer.still(look, spec, m, table, v, picture, s.seen.astype(numpy.float64)), s


class State:
    """what Figure.state gives the stage: her capsules and their parts"""

    def __init__(self, capsules, groups=None):
        self.capsules = capsules
        self.capsule_groups = groups


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class FrameTest(unittest.TestCase):
    def test_the_night_takes_the_stage_down_but_its_emissive_materials_and_the_sky_fills_where_nothing_is(self):
        look = layer_look(night=0.3, tint=[1.0, 1.0, 2.0], emissive=1.2)
        st, s = scene_still(look)
        img = stage_layer.stage_frame(look, st)
        floor, sign = s.material == 0, s.material == 1
        numpy.testing.assert_allclose(img[floor], [[30.0, 30.0, 60.0]] * int(floor.sum()), atol=1e-9)
        numpy.testing.assert_allclose(img[sign], [[240.0] * 3] * int(sign.sum()), atol=1e-9)
        sky = ~s.seen
        self.assertTrue(sky.any())
        numpy.testing.assert_allclose(img[sky], st.sky[sky], atol=1e-9)
        top = numpy.asarray(look["layer"]["sky_top"])
        horizon = numpy.asarray(look["layer"]["sky_horizon"])
        self.assertTrue(((img[sky] >= numpy.minimum(top, horizon) - 1e-9) & (img[sky] <= numpy.maximum(top, horizon) + 1e-9)).all())

    def test_the_lamps_light_the_floor_round_them_and_not_the_emissive_materials(self):
        look = layer_look(night=0.3, lamp=2.0)
        st, s = scene_still(look)
        img = stage_layer.stage_frame(look, st)
        floor = s.material == 0
        self.assertGreater(float(img[floor].max()), 30.0 + 1.0)
        lamp = layer_look(night=0.3, lamp=2.0)["layer"]
        want = 100.0 * (0.3 + 2.0 * stage_layer.lamp_light(s.points[floor], s.normals[floor], [[0.0, 30.0, 10.0]], lamp))
        numpy.testing.assert_allclose(img[floor], want, atol=1e-9)
        numpy.testing.assert_allclose(img[s.material == 1], 200.0, atol=1e-9)

    def test_her_shadow_falls_on_the_floor_round_her_and_leaves_the_rest(self):
        look = layer_look(stage={"shadow": 1.0}, night=0.5)
        st, s = scene_still(look)
        her = State([((0.0, 5.0, 0.0), (0.0, 9.0, 0.0), 1.2), ((0.0, 0.42, -0.5), (0.0, 0.42, 0.8), 0.42)], ["torso", "foot"])
        lit = stage_layer.stage_frame(look, st)
        dark = stage_layer.stage_frame(look, st, her)
        floor = s.material == 0
        keep = dark[floor][:, 0] / lit[floor][:, 0]
        self.assertLess(float(keep.min()), 0.5)
        far = numpy.linalg.norm(s.points[floor][:, [0, 2]], axis=1) > 25.0
        numpy.testing.assert_allclose(keep[far], 1.0, atol=1e-9)
        # and what each point keeps is soft_light_at of the shadow mv_world lays on its floor there (its grid)
        grid = mv_world.soft_shadow_grid(her.capsules, look["stage"]["shadow_light"], look["stage"]["shadow_blur"], 0.0,
                                         groups=her.capsule_groups)
        key, contact = grid.at(s.points[floor][:, 0], s.points[floor][:, 2])
        # (past the box the shadows reach, 4 standard deviations of the light's spread out, under 1e-4 of the light is kept
        # off, and nothing is worked out there)
        numpy.testing.assert_allclose(keep, stage_layer.soft_light_at(key, contact, s.normals[floor], look["stage"]), atol=1e-4)

    def test_her_shadow_is_mv_worlds_grid_on_a_level_floor_and_worked_out_at_the_points_elsewhere(self):
        her = State([((0.0, 5.0, 0.0), (0.0, 9.0, 0.0), 1.2), ((0.0, 0.42, -0.5), (0.0, 0.42, 0.8), 0.42)], ["torso", "foot"])
        stage = dict(shadow=1.0, shadow_light=list(LIGHT), shadow_blur=5.0, shadow_contact=0.9, shadow_key=0.6)
        floor = floor_points(numpy.linspace(-12, 4, 41), numpy.linspace(-4, 12, 41), 0.0)
        wall = numpy.array([(-2.0, 1.0, 2.0), (-3.0, 0.5, 2.0), (6.0, 1.0, 2.0)])
        P = numpy.concatenate([floor, wall])
        n = numpy.concatenate([[[0.0, 1.0, 0.0]] * len(floor), [[0.0, 0.0, -1.0]] * len(wall)])
        key, contact = stage_layer.her_shadow(P, n, her, stage)
        grid = mv_world.soft_shadow_grid(her.capsules, LIGHT, 5.0, 0.0, groups=her.capsule_groups)
        want = grid.at(floor[:, 0], floor[:, 2])
        numpy.testing.assert_allclose(key[:len(floor)], want[0], atol=1e-12)
        numpy.testing.assert_allclose(contact[:len(floor)], want[1], atol=1e-12)
        exact = stage_layer.shadow_at(wall, n[len(floor):], her.capsules, her.capsule_groups, LIGHT, 5.0)
        numpy.testing.assert_allclose(key[len(floor):], exact[0], atol=1e-12)
        numpy.testing.assert_allclose(contact[len(floor):], exact[1], atol=1e-12)
        self.assertLess(float(key[len(floor):].min()), 0.5)

    def test_her_shadow_does_not_put_out_a_sign(self):
        # standing right in front of the sign, between it and the light: the sign gives its light all the same
        look = layer_look(stage={"shadow": 1.0}, night=0.5)
        st, s = scene_still(look)
        her = State([((0.0, 2.0, 17.0), (0.0, 9.0, 17.0), 2.0)])
        key, _ = stage_layer.shadow_at(s.points[s.material == 1], s.normals[s.material == 1], her.capsules, None,
                                       look["stage"]["shadow_light"], look["stage"]["shadow_blur"])
        self.assertLess(float(key.min()), 0.2)                        # (her shadow would fall on it)
        sign = s.material == 1
        numpy.testing.assert_array_equal(stage_layer.stage_frame(look, st, her)[sign], stage_layer.stage_frame(look, st)[sign])

    def test_the_floor_mirrors_the_lit_stage_by_its_share(self):
        look = layer_look(night=0.3, reflect=1.0, reflect_blur=0.0)
        st, s = scene_still(look)
        plain = stage_layer.stage_frame(layer_look(night=0.3), scene_still(layer_look(night=0.3))[0])
        img = stage_layer.stage_frame(look, st)
        m, v = lit_scene()
        u, w, _ = v.project([(0.0, -3.0, 20.0)])                   # where the wall's mirror image is
        at = (int(round(w[0])), int(round(u[0])))
        share = float(mv_world.fresnel(v)[at])
        self.assertAlmostEqual(float(img[at][0] - plain[at][0]), 200.0 * share, delta=200.0 * share * 0.05)

    def test_the_depth_of_field_blurs_the_far_stage_and_keeps_the_focus_sharp(self):
        sharp = layer_look(night=1.0)
        soft = layer_look(stage={"dof": 6.0}, night=1.0)
        a = stage_layer.stage_frame(sharp, scene_still(sharp)[0])
        b = stage_layer.stage_frame(soft, scene_still(soft)[0])
        m, v = lit_scene()
        # the wall's top edge, 60 from the eye past a focus of 40: blurred; the floor at the focus: as sharp
        u, w, _ = v.project([(0.0, 8.0, 20.0)])
        col, row = int(round(u[0])), int(round(w[0]))
        self.assertLess(float(numpy.abs(numpy.diff(b[row - 4:row + 5, col, 0])).max()),
                        0.6 * float(numpy.abs(numpy.diff(a[row - 4:row + 5, col, 0])).max()))
        u, w, _ = v.project([(0.0, 0.0, 0.0)])
        self.assertLess(float(numpy.abs(a[int(round(w[0])), int(round(u[0]))] - b[int(round(w[0])), int(round(u[0]))]).max()), 1.0)

    def test_the_glows_spread_the_bright_and_the_emissive(self):
        look = layer_look(night=1.0, emissive=1.2, emissive_glow=0.5, glow=1.0, glow_threshold=200.0)
        st, s = scene_still(look)
        img = stage_layer.stage_frame(look, st)
        none = stage_layer.stage_frame(layer_look(night=1.0, emissive=1.2), st)
        m, v = lit_scene()
        u, w, _ = v.project([(0.0, 9.0, 20.0)])                    # just above the wall's top: the glow reaches there
        at = (int(round(w[0])), int(round(u[0])))
        self.assertGreater(float(img[at][0] - none[at][0]), 5.0)


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class PictureTest(unittest.TestCase):
    def test_a_camera_that_stands_still_needs_one_picture_and_a_missing_one_is_refused(self):
        still_view = view()
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, stage_layer.PICTURE % 3), "wb").close()
            self.assertEqual(stage_layer.picture_frame(d, 9, lambda f: still_view), 3)
            self.assertEqual(stage_layer.picture_frame(d, 3, lambda f: still_view), 3)
            with self.assertRaises(ValueError):
                stage_layer.picture_frame(d, 2, lambda f: still_view)
            moving = lambda f: view(angles=(15.0, float(f), 0.0))
            with self.assertRaises(ValueError):                      # frame 9's camera is not frame 3's
                stage_layer.picture_frame(d, 9, moving)

    def test_the_batch_draws_the_model_alone_placed_by_its_root_with_its_shadows_off(self):
        spec = stage_layer.check_set({"model": "C:/s/stage.pmx", "offset": [0.0, 0.111, 0.0]})
        lines = stage_layer.batch_lines(spec, "C:/c/cam.vmd", (640, 720), "C:/m/MikuMikuDance.exe", avi="C:/o/s.avi", first=10,
                                        last=20)
        self.assertEqual(lines[0], ["launch", "--headless", "--exe", "C:/m/MikuMikuDance.exe"])
        for wanted in (["menu", "set", "215", "off"], ["menu", "set", "221", "off"], ["menu", "set", "282", "on"],
                       ["model", "load", "C:/s/stage.pmx"], ["bone", "set", "全ての親", "--pos", "0.000000", "0.111000", "0.000000",
                                                              "--frame", "0"], ["menu", "set", "279", "off"],
                       ["motion", "load", "C:/c/cam.vmd", "--frame", "0"],
                       ["render", "avi", "C:/o/s.avi", "--from", "10", "--to", "20", "--fps", "30", "--size", "640", "720",
                        "--codec", "未圧縮"]):
            self.assertIn(wanted, lines)
        self.assertLess(lines.index(["model", "load", "C:/s/stage.pmx"]), lines.index(["menu", "set", "279", "off"]))
        self.assertEqual(lines[-1], ["quit"])
        with self.assertRaises(ValueError):
            stage_layer.check_set({"model": "a.pmx", "offst": [0, 0, 0]})
        with self.assertRaises(ValueError):
            stage_layer.check_set({"model": "a.pmx", "offset": [0, 0]})


class Moving:
    """a dancer as check_placement reads her (mv_world.Figure): her capsules at every frame and the parts they belong to.
    Two soles on the floor at y 0.111 (their bottoms there), a body above them; she walks along x by `step` a frame"""

    def __init__(self, step=0.0, lift=0.0, sink=0.0):
        self.step, self.lift, self.sink = step, lift, sink
        self.body = State(None, ["torso", "head", "left foot", "right foot"])
        self.body.groups = self.body.capsule_groups

    def state(self, frame):
        x = self.step * frame
        y = 0.111 + 0.42 + self.lift - self.sink
        return State([((x, 4.0, 0.0), (x, 12.0, 0.0), 1.2), ((x, 14.0, 0.0), (x, 16.0, 0.0), 1.5),
                      ((x - 1.0, y, -0.5), (x - 1.0, y, 1.0), 0.42), ((x + 1.0, y, -0.5), (x + 1.0, y, 1.0), 0.42)],
                     self.body.groups)


def cam_track(eye_z=-40.0, look_at=(0.0, 8.0, 0.0), angles=(5.0, 0.0, 0.0)):
    """a camera motion held from frame 0 to 100 (what check_placement reads)"""
    from mmd_cli.formats import vmd
    key = dict(distance=-(look_at[2] - eye_z), position=tuple(look_at), rotation=(-math.radians(angles[0]), math.radians(angles[1]), 0.0),
               fov=30)
    keys = fk.camera_keys(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **key), vmd.CameraKey(frame=100, **key)]))
    return keys, [k.frame for k in keys]


def box(lo, hi):
    """the six faces of a closed box, their fronts facing out"""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    return (quad(y1, x0, x1, z0, z1) + quad(y0, x0, x1, z0, z1, up=False)
            + wall(z0, x0, x1, y0, y1) + wall(z1, x0, x1, y0, y1, towards_minus_z=False)
            + [((x0, y0, z0), (x0, y0, z1), (x0, y1, z1)), ((x0, y0, z0), (x0, y1, z1), (x0, y1, z0))]
            + [((x1, y0, z0), (x1, y1, z1), (x1, y0, z1)), ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1))])


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class CheckTest(unittest.TestCase):
    FLOOR = quad(0.111, -60, 60, -60, 60)

    def test_soles_on_the_floor_are_on_it_and_one_in_it_or_off_its_edge_is_counted(self):
        got = stage_layer.check_placement(mesh(self.FLOOR), Moving(), range(3), {})
        self.assertEqual(got["feet"]["sunk_frames"], 0)
        self.assertEqual(got["feet"]["off_floor_frames"], 0)
        self.assertAlmostEqual(got["feet"]["floor_height_min"], 0.111, places=9)
        self.assertAlmostEqual(got["feet"]["floor_height_max"], 0.111, places=9)
        self.assertEqual(stage_layer.check_placement(mesh(self.FLOOR), Moving(sink=0.2), range(3), {})["feet"]["sunk_frames"], 3)
        # walking off the floor's edge (x 60) by the 30th frame
        off = stage_layer.check_placement(mesh(self.FLOOR), Moving(step=2.5), range(30), {})
        self.assertEqual(off["feet"]["off_floor"][0]["frames"][1], 29)
        self.assertGreater(off["feet"]["off_floor_frames"], 0)

    def test_a_post_she_walks_into_is_counted(self):
        post = box((9.0, 0.111, -0.5), (10.0, 30.0, 0.5))
        got = stage_layer.check_placement(mesh(self.FLOOR + post), Moving(step=1.0), range(15), {})
        frames = [f for run in got["body"]["into_things"] for f in range(run["frames"][0], run["frames"][1] + 1)]
        self.assertIn(10, frames)                                   # her body's middle at the post
        self.assertNotIn(0, frames)
        self.assertEqual(got["feet"]["sunk_frames"], 0)

    def test_a_camera_in_a_building_or_behind_a_wall_before_her_is_counted(self):
        house = box((-10.0, 0.111, -50.0), (10.0, 30.0, -30.0))
        cams = {"open": cam_track(eye_z=-40.0), "in": cam_track(eye_z=-40.0)}
        open_floor = stage_layer.check_placement(mesh(self.FLOOR), Moving(), range(2), {"open": cams["open"]})
        self.assertEqual(open_floor["cameras"]["open"]["inside_frames"], 0)
        self.assertEqual(open_floor["cameras"]["open"]["hidden_frames"], 0)
        inside = stage_layer.check_placement(mesh(self.FLOOR + house), Moving(), range(2), {"in": cams["in"]})
        self.assertEqual(inside["cameras"]["in"]["inside_frames"], 2)
        screen = wall(-20.0, -10.0, 10.0, 0.111, 25.0)               # a wall between the camera and her
        hidden = stage_layer.check_placement(mesh(self.FLOOR + screen), Moving(), range(2), {"open": cams["open"]})
        self.assertEqual(hidden["cameras"]["open"]["hidden_frames"], 2)
        self.assertEqual(hidden["cameras"]["open"]["inside_frames"], 0)


@unittest.skipUnless(stage_layer, "needs Pillow and numpy")
class LookTest(unittest.TestCase):
    def setUp(self):
        self.mv_look = load("mv_look")

    def test_the_layer_is_off_unless_the_look_says_and_its_values_need_it_on(self):
        look = self.mv_look.merge_look({})
        self.assertEqual(look["layer"]["on"], 0)
        with self.assertRaises(ValueError) as said:
            self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"night": 0.3}})
        self.assertIn("layer.on", str(said.exception))

    def test_the_stage_of_a_model_needs_the_world_and_its_floor_and_refuses_mv_worlds_light(self):
        for bad in ({"stage": {"world": 0}}, {"stage": {"world": 1, "floor": 0}},
                    {"stage": {"world": 1, "pool": 0.5}}, {"stage": {"world": 1, "reflect": 0.3}},
                    {"stage": {"world": 1, "shadow": 1.0, "shadow_soft": 0}}, {"stage": {"world": 1}, "lamps": {"cyc": 10}},
                    {"stage": {"world": 1}, "layer": {"reflect": 1.5}}, {"stage": {"world": 1}, "layer": {"tint": [1, -1, 1]}}):
            look = dict(bad)
            look["layer"] = dict({"on": 1}, **bad.get("layer", {}))
            with self.assertRaises(ValueError, msg=bad):
                self.mv_look.merge_look(look)
        self.mv_look.merge_look({"stage": {"world": 1, "shadow": 1.0, "dof": 6.5}, "layer": {"on": 1, "night": 0.3}})

    def test_the_light_round_her_is_one_more_input_and_only_with_spill(self):
        stage = {"pattern": "W/stage/stage_%05d.png", "first": 30, "frames": 10, "spill": "W/stage/spill_%05d.png"}
        world = self.mv_look.merge_look({"stage": {"world": 1}})
        without = self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"on": 1, "night": 0.3}})
        args = ("fg.avi", "out.mp4", None, None)
        a = self.mv_look.ffmpeg_command(*args, world, (320, 180), 30, stage=dict(stage, spill=None), start=1.0, duration=10 / 30.0)
        b = self.mv_look.ffmpeg_command(*args, without, (320, 180), 30, stage=stage, start=1.0, duration=10 / 30.0)
        self.assertEqual(a, b)                                       # no spill: the argv of the stage in the world
        lit = self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"on": 1, "spill": 0.8, "spill_wrap": 0.5}})
        c = self.mv_look.ffmpeg_command(*args, lit, (320, 180), 30, stage=stage, start=1.0, duration=10 / 30.0)
        self.assertIn("W/stage/spill_%05d.png", c)
        graph = c[c.index("-filter_complex") + 1]
        self.assertIn("[lit_dancer]", graph)
        self.assertIn("[2:v]scale=320:180", graph)
        with self.assertRaises(ValueError):                          # spill asked, but no light round her drawn
            self.mv_look.ffmpeg_command(*args, lit, (320, 180), 30, stage=dict(stage, spill=None), start=1.0, duration=10 / 30.0)

    def test_the_light_on_her_scales_her_colour_and_only_when_asked(self):
        stage = {"pattern": "W/stage/stage_%05d.png", "first": 30, "frames": 10, "spill": None}
        args = ("fg.avi", "out.mp4", None, None)
        for glow in (0.45, 0.0):
            plain = self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"on": 1}, "glow": {"strength": glow}})
            dim = self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"on": 1, "person": 0.8, "person_tint": [1.0, 0.9, 0.8]},
                                           "glow": {"strength": glow}})
            a = self.mv_look.ffmpeg_command(*args, plain, (320, 180), 30, stage=stage, start=1.0, duration=10 / 30.0)
            b = self.mv_look.ffmpeg_command(*args, dim, (320, 180), 30, stage=stage, start=1.0, duration=10 / 30.0)
            self.assertNotIn("colorchannelmixer", a[a.index("-filter_complex") + 1])
            self.assertIn("colorchannelmixer=rr=0.8:gg=0.72:bb=0.64", b[b.index("-filter_complex") + 1])
        with self.assertRaises(ValueError):
            self.mv_look.merge_look({"stage": {"world": 1}, "layer": {"person": 0.8}})          # (it needs layer.on 1)


FFMPEG = __import__("shutil").which("ffmpeg")


@unittest.skipUnless(stage_layer and FFMPEG, "needs Pillow, numpy and ffmpeg")
class RenderTest(unittest.TestCase):
    """end to end: mv_look render with the stage of a model (a floor and a sign behind a grey box, the dancer), a camera that
    stands still: MMD's one picture of the stage serves every frame"""
    SIZE = (320, 180)

    @classmethod
    def setUpClass(cls):
        import json as _json
        import subprocess
        from mmd_cli.formats import vmd
        cls.mv_look = load("mv_look")
        cls.folder = tempfile.mkdtemp()
        f = cls.folder
        points = [(-60, 0, -60), (-60, 0, 120), (60, 0, 120), (60, 0, -60), (-10, 0, 20), (-10, 8, 20), (10, 8, 20), (10, 0, 20)]
        faces = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
        with open(os.path.join(f, "stage.pmx"), "wb") as fh:
            fh.write(pmx_bytes(points, faces, [("floor", 0, 5.0, 1.0, 2), ("sign", 0, 105.0, 1.0, 2)]))
        with open(os.path.join(f, "set.json"), "w", encoding="utf-8") as fh:
            _json.dump({"model": "stage.pmx", "emissive": ["sign"]}, fh)
        key = dict(distance=-40.0, position=(0.0, 4.0, 0.0), rotation=(-math.radians(10.0), 0.0, 0.0), fov=30)
        cls.camera = os.path.join(f, "camera.vmd")
        with open(cls.camera, "wb") as fh:
            fh.write(vmd.dumps(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **key), vmd.CameraKey(frame=60, **key)])))
        # MMD's picture of the stage at frame 0: the floor 100, the sign 200 (drawn here from the geometry)
        v = mv_world.view_at(mv_world.camera_track(cls.camera), 0, cls.SIZE)
        m = stage_layer.load_mesh(os.path.join(f, "stage.pmx"))
        depth, face = stage_layer.rasterize(v, m)
        s = stage_layer.surface(v, depth, face, m)
        rgba = numpy.zeros((cls.SIZE[1], cls.SIZE[0], 4), numpy.uint8)
        rgba[s.material == 0] = (100, 100, 100, 255)
        rgba[s.material == 1] = (200, 60, 60, 255)
        cls.pictures = os.path.join(f, "pictures")
        os.makedirs(cls.pictures)
        Image.fromarray(rgba, "RGBA").save(os.path.join(cls.pictures, stage_layer.PICTURE % 0))
        cls.material = s.material
        cls.fg = os.path.join(f, "fg.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black@0.0:s=%dx%d:r=30,format=rgba,drawbox=x=150:y=60:w=20:h=60:color=0x808080@1.0:t=fill:replace=1"
                        % cls.SIZE, "-frames:v", "12", "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True,
                       stdin=subprocess.DEVNULL)
        cls.outs = {}
        for name, layer in (("plain", {}), ("spill", {"spill": 1.0, "spill_radius": 60.0}), ("dim", {"person": 0.5})):
            look = os.path.join(f, "look_%s.json" % name)
            with open(look, "w", encoding="utf-8") as fh:
                _json.dump({"stage": {"world": 1}, "layer": dict({"on": 1, "night": 0.5}, **layer), "glow": {"strength": 0},
                            "lens": {"vignette": 0, "grain": 0}}, fh)
            out = os.path.join(f, "%s.mp4" % name)
            stream = __import__("io").StringIO()
            with __import__("contextlib").redirect_stdout(stream):
                code = cls.mv_look.main(["render", cls.fg, look, out, "--work", os.path.join(f, "work_" + name), "--camera",
                                         cls.camera, "--stage-set", os.path.join(f, "set.json"), "--stage-pictures", cls.pictures])
            cls.outs[name] = (code, stream.getvalue(), out)

    @classmethod
    def tearDownClass(cls):
        __import__("shutil").rmtree(cls.folder, ignore_errors=True)

    def frames(self, path):
        import subprocess
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=in_color_matrix=bt709:in_range=tv:out_range=pc",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True,
                             stdin=subprocess.DEVNULL).stdout
        n = self.SIZE[0] * self.SIZE[1] * 3
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], numpy.uint8).reshape(self.SIZE[1], self.SIZE[0], 3).astype(float)
                for i in range(len(raw) // n)]

    def test_the_stage_of_the_model_lies_behind_her_at_night(self):
        code, said, out = self.outs["plain"]
        self.assertEqual(code, 0, said)
        frames = self.frames(out)
        self.assertEqual(len(frames), 12)
        img = frames[6]
        floor = (self.material == 0)
        floor[55:125, 140:180] = False                                 # (not where she stands)
        self.assertAlmostEqual(float(numpy.median(img[floor][:, 0])), 50.0, delta=3.0)        # the floor at night 0.5
        sign = self.material == 1
        sign[55:125, 140:180] = False
        self.assertAlmostEqual(float(numpy.median(img[sign][:, 0])), 200.0, delta=4.0)        # the sign keeps its light
        self.assertAlmostEqual(float(img[70:110, 153:167].mean()), 128.0, delta=4.0)          # and she is herself

    def test_the_light_round_her_tints_her_and_nothing_else(self):
        plain = self.frames(self.outs["plain"][2])[6]
        code, said, out = self.outs["spill"]
        self.assertEqual(code, 0, said)
        lit = self.frames(out)[6]
        her = (slice(70, 110), slice(153, 167))
        gain = lit[her].mean(axis=(0, 1)) - plain[her].mean(axis=(0, 1))
        self.assertGreater(float(gain[0]), 2.0)                      # the red sign's light on her
        self.assertGreater(float(gain[0]), 2.0 * float(max(gain[1], gain[2], 0.1)))
        away = numpy.ones(plain.shape[:2], bool)
        away[50:130, 130:190] = False
        diff = numpy.abs(lit[away] - plain[away])
        dim = self.frames(self.outs["dim"][2])[6]
        self.assertEqual(self.outs["dim"][0], 0, self.outs["dim"][1])
        self.assertAlmostEqual(float(dim[her].mean()), 0.5 * float(plain[her].mean()), delta=3.0)   # half the light on her
        self.assertLess(float(numpy.abs(dim[away] - plain[away]).mean()), 0.3)                    # and the stage as it was
        self.assertLess(float(diff.mean()), 0.3)                     # (x264 codes the two a little apart)
        self.assertLess(float(numpy.percentile(diff, 99.5)), 3.0)


if __name__ == "__main__":
    unittest.main()
