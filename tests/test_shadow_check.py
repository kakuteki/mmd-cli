"""tools/shadow_check.py: measures of the floor shadow that do not go through the soft shadow's own sums (a light integrated
by many rays past the capsules, the floor shadow read back from the drawn pixels, MMD's ground shadow, the roughness of a
series in time)."""
import importlib.util
import math
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy
    from PIL import Image  # noqa: F401  (the tools need Pillow)
except ImportError:
    numpy = None

if numpy is not None:
    import sys
    sys.path.insert(0, ROOT)
    from mmd_cli import fk


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shadow_check = load("shadow_check") if numpy is not None else None
DOWN = (0.0, -1.0, 0.0)
MMD_LIGHT = (-0.5, -1.0, 0.5)


def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@unittest.skipUnless(shadow_check, "needs Pillow and numpy")
class RayTest(unittest.TestCase):
    def hits(self, origin, direction, a, b, r):
        d = numpy.asarray(direction, dtype=float)
        return bool(shadow_check.ray_capsule_hits(numpy.array([origin], dtype=float), (d / numpy.linalg.norm(d))[None, :],
                                                  a, b, r)[0])

    def test_a_ray_meets_a_ball_on_its_way_and_not_one_beside_it_or_behind_it(self):
        ball = ((0.0, 5.0, 0.0), (0.0, 5.0, 0.0), 1.0)
        self.assertTrue(self.hits((0, 0, 0), (0, 1, 0), *ball))
        self.assertTrue(self.hits((0.95, 0, 0), (0, 1, 0), *ball))             # grazes it within its radius
        self.assertFalse(self.hits((1.05, 0, 0), (0, 1, 0), *ball))
        self.assertFalse(self.hits((0, 0, 0), (0, -1, 0), *ball))              # the ball is behind the ray's start
        self.assertTrue(self.hits((0, 4.5, 0), (0, -1, 0), *ball))             # the start inside it

    def test_a_ray_meets_a_bar_along_its_length_and_round_its_ends(self):
        bar = ((-3.0, 4.0, 0.0), (3.0, 4.0, 0.0), 0.5)
        self.assertTrue(self.hits((2.9, 0, 0.4), (0, 1, 0), *bar))
        self.assertFalse(self.hits((2.9, 0, 0.6), (0, 1, 0), *bar))
        self.assertTrue(self.hits((3.4, 0, 0), (0, 1, 0), *bar))               # the round end reaches 0.5 past it
        self.assertFalse(self.hits((3.35, 0, 0.4), (0, 1, 0), *bar))           # 0.53 from the end's centre: out
        self.assertTrue(self.hits((-10, 4.0, 0), (1, 0, 0), *bar))             # along its axis

    def test_a_slanting_ray_meets_what_lies_on_its_line(self):
        ell = numpy.array([0.5, 1.0, -0.5]) / math.sqrt(1.5)
        target = numpy.array([1.0, 0.0, 2.0]) + 6.0 * ell
        self.assertTrue(self.hits((1.0, 0.0, 2.0), ell, target, target, 0.1))
        self.assertFalse(self.hits((1.3, 0.0, 2.0), ell, target, target, 0.1))


@unittest.skipUnless(shadow_check, "needs Pillow and numpy")
class LightTest(unittest.TestCase):
    def test_the_directions_spread_round_the_light_as_its_gaussian(self):
        ell = numpy.array([0.5, 1.0, -0.5]) / math.sqrt(1.5)
        dirs, weights = shadow_check.gaussian_directions(MMD_LIGHT, 5.0, side=48)
        self.assertEqual(dirs.shape, (48 * 48, 3))
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=9)
        numpy.testing.assert_allclose(numpy.linalg.norm(dirs, axis=1), 1.0, atol=1e-12)
        mean = (dirs * weights[:, None]).sum(axis=0)
        self.assertGreater(float(mean @ ell / numpy.linalg.norm(mean)), 0.99999)
        angle = numpy.degrees(numpy.arccos(numpy.clip(dirs @ ell, -1.0, 1.0)))
        # the angle from the light of a 2-d Gaussian of 5 degrees: Rayleigh, its root mean square sqrt(2) x 5 degrees
        self.assertAlmostEqual(float(numpy.sqrt((weights * angle ** 2).sum())), math.sqrt(2.0) * 5.0, delta=0.15)
        same, _ = shadow_check.gaussian_directions(MMD_LIGHT, 0.0, side=4)
        numpy.testing.assert_allclose(same, numpy.tile(ell, (16, 1)), atol=1e-12)

    def test_a_long_bar_lets_through_what_the_gaussian_has_outside_its_band(self):
        # an (all but) endless bar of radius r at height h over the floor, the light straight down: from a floor point z
        # off the bar's line the bar hides the angles between atan((z - r') / h) and atan((z + r') / h) (r' the tangent
        # lines' reach at the floor); the share through is 1 - the Gaussian between them
        h, r, sigma = 4.0, 0.5, 5.0
        bar = [((-60.0, h, 0.0), (60.0, h, 0.0), r)]
        zs = numpy.array([0.0, 0.3, 0.6, 0.9, 1.4])
        got = shadow_check.light_through(numpy.stack([0 * zs, 0 * zs, zs], axis=1), bar, DOWN, sigma, side=96)
        s = math.radians(sigma)
        for z, g in zip(zs, got):
            centre = math.atan2(-z, h)                    # the bar seen from the point, from straight up
            half = math.asin(r / math.hypot(z, h))
            want = 1.0 - (normal_cdf((centre + half) / s) - normal_cdf((centre - half) / s))
            self.assertAlmostEqual(float(g), want, delta=0.02, msg=z)

    def test_two_capsules_in_the_same_place_hide_what_one_hides(self):
        # the light that reaches a point is what no capsule hides: two capsules over each other hide what one does (each
        # taken on its own and multiplied, they would hide it twice)
        ball = ((0.0, 3.0, 0.0), (0.0, 3.0, 0.0), 0.4)
        points = numpy.array([[0.0, 0.0, 0.0], [0.15, 0.0, 0.0], [0.3, 0.0, 0.0]])
        one = shadow_check.light_through(points, [ball], DOWN, 5.0, side=64)
        two = shadow_check.light_through(points, [ball, ball], DOWN, 5.0, side=64)
        numpy.testing.assert_allclose(two, one, atol=1e-12)
        apart = shadow_check.light_through(points, [ball, ball], DOWN, 5.0, side=64, union=False)
        numpy.testing.assert_allclose(apart, one ** 2, atol=1e-12)
        self.assertLess(float(apart[1]), float(one[1]) - 0.05)

    def test_far_from_her_all_the_light_comes_and_under_a_big_ball_none(self):
        ball = [((0.0, 3.0, 0.0), (0.0, 3.0, 0.0), 2.0)]
        got = shadow_check.light_through(numpy.array([[0.0, 0.0, 0.0], [30.0, 0.0, 0.0]]), ball, DOWN, 5.0, side=32)
        self.assertEqual(float(got[0]), 0.0)
        self.assertEqual(float(got[1]), 1.0)


mv_world = load("mv_world") if numpy is not None else None


def view(look_at=(0.0, 10.0, 0.0), distance=40.0, angles=(15.0, 10.0, 0.0), size=(320, 180)):
    return mv_world.View(fk.CameraState(0, tuple(look_at), float(distance), tuple(angles), 30.0), size)


@unittest.skipUnless(shadow_check, "needs Pillow and numpy")
class PixelTest(unittest.TestCase):
    def test_each_pixel_finds_the_floor_point_it_shows(self):
        v = view()
        for floor_y in (0.0, 0.111):
            X, Z, hit = shadow_check.floor_points(v, floor_y)
            for i, j in ((120, 40), (150, 160), (179, 319), (100, 200)):
                self.assertTrue(hit[i, j])
                # the floor point of the pixel lands on the pixel's centre
                u, row, _ = v.project([(X[i, j], floor_y, Z[i, j])])
                self.assertAlmostEqual(float(u[0]), j, places=6)
                self.assertAlmostEqual(float(row[0]), i, places=6)
            u, row, _ = v.project([(1.0, floor_y, -2.0)])
            i, j = int(round(row[0])), int(round(u[0]))
            self.assertLess(math.hypot(X[i, j] - 1.0, Z[i, j] + 2.0), 0.5)    # within a pixel's footprint
        X, Z, hit = shadow_check.floor_points(view(angles=(10.0, 0.0, 0.0)), 0.0)
        self.assertFalse(hit[0].any())                    # the top row looks over the horizon
        self.assertTrue(hit[-1].all())

    def test_the_ratio_is_what_the_shadow_leaves_of_the_light_where_it_can_be_read(self):
        plain = numpy.full((4, 4, 3), 40.0)
        plain[0, 0] = 1.0                                 # too dark to read a ratio from
        shaded = plain * 0.25
        shaded[3, 3] = plain[3, 3]
        r = shadow_check.ratio_map(shaded, plain, min_plain=4.0)
        self.assertTrue(math.isnan(r[0, 0]))
        self.assertAlmostEqual(float(r[1, 1]), 0.25, places=9)
        self.assertAlmostEqual(float(r[3, 3]), 1.0, places=9)

    def test_the_width_of_an_edge_is_where_it_rises_from_a_tenth_to_nine_tenths(self):
        s = numpy.linspace(-5.0, 5.0, 2001)
        for spread in (0.2, 0.8):
            values = numpy.array([0.2 + 0.7 * normal_cdf(x / spread) for x in s])
            self.assertAlmostEqual(shadow_check.edge_width(s, values), 2.0 * 1.2815516 * spread, delta=0.01)
        step = numpy.where(s < 1.0, 0.1, 0.9)
        self.assertLess(shadow_check.edge_width(s, step), 0.01)
        # a profile that dips again past the edge (another shadow) is read up to its first rise
        dip = numpy.array([normal_cdf(x / 0.5) for x in s]) - 0.6 * numpy.exp(-(s - 3.5) ** 2)
        self.assertAlmostEqual(shadow_check.edge_width(s, dip), 2.0 * 1.2815516 * 0.5, delta=0.1)


@unittest.skipUnless(shadow_check, "needs Pillow and numpy")
class GroundShadowTest(unittest.TestCase):
    def test_the_ground_shadow_is_what_menu_221_adds_outside_her(self):
        on = numpy.zeros((3, 4, 4))
        off = numpy.zeros((3, 4, 4))
        on[0, 0] = off[0, 0] = (200, 180, 170, 255)        # her
        on[1, 1] = (10, 10, 10, 120)                       # the ground shadow
        on[2, 2] = (12, 12, 12, 3)                         # below what is read as a shadow
        mask, her = shadow_check.ground_shadow(on, off)
        self.assertEqual(mask.sum(), 1)
        self.assertTrue(mask[1, 1])
        self.assertTrue(her[0, 0])
        self.assertFalse(her[1, 1])

    def test_two_masks_agree_by_their_overlap(self):
        a = numpy.zeros((10, 10), dtype=bool)
        b = numpy.zeros((10, 10), dtype=bool)
        a[0:4, 0:5] = True                                 # 20
        b[2:6, 0:5] = True                                 # 20, 10 of them in a
        got = shadow_check.agreement(a, b)
        self.assertAlmostEqual(got["iou"], 10.0 / 30.0, places=9)
        self.assertAlmostEqual(got["a_in_b"], 0.5, places=9)
        self.assertAlmostEqual(got["b_in_a"], 0.5, places=9)
        valid = numpy.ones((10, 10), dtype=bool)
        valid[0:2] = False                                 # rows 0-1 of a are not looked at
        got = shadow_check.agreement(a, b, valid)
        self.assertAlmostEqual(got["a_in_b"], 10.0 / 10.0, places=9)


@unittest.skipUnless(shadow_check, "needs Pillow and numpy")
class RoughnessTest(unittest.TestCase):
    def test_noise_is_rough_and_a_smooth_motion_is_not(self):
        rng = numpy.random.default_rng(3)
        self.assertAlmostEqual(shadow_check.roughness(rng.normal(size=20000)), math.sqrt(3.0), delta=0.05)
        t = numpy.arange(300) / 30.0
        self.assertLess(shadow_check.roughness(numpy.sin(2.0 * math.pi * 0.7 * t)), 0.2)
        # a pixel series per column: the roughness of all of them together
        both = numpy.stack([numpy.sin(2.0 * math.pi * 0.5 * t), numpy.cos(2.0 * math.pi * 0.4 * t)], axis=1)
        self.assertLess(shadow_check.roughness(both), 0.2)
        self.assertTrue(math.isnan(shadow_check.roughness(numpy.ones(10))))      # nothing moves


if __name__ == "__main__":
    unittest.main()
