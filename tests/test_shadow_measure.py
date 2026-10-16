"""tools/shadow_measure.py: the width of a shadow's edges, its cover and its flicker, on pictures whose answer is known."""
import importlib.util
import math
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
except ImportError:
    np = None

if np is not None:
    spec = importlib.util.spec_from_file_location("shadow_measure", os.path.join(ROOT, "tools", "shadow_measure.py"))
    shadow_measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shadow_measure)


def erf(x):
    return np.vectorize(math.erf)(x)


def edge(sigma, shape=(120, 160), at=80.0, angle=0.0):
    """a shadow edge blurred by a Gaussian of `sigma` px (lit to the right of x = at, turned by `angle` degrees), a body
    covering the whole picture"""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float64)
    a = math.radians(angle)
    d = (xx - at) * math.cos(a) + (yy - shape[0] / 2.0) * math.sin(a)
    s = 0.5 * (1.0 + erf(d / (sigma * math.sqrt(2.0)))) if sigma > 0 else (d >= 0).astype(np.float64)
    return s, np.full(shape, 255.0)


@unittest.skipUnless(np is not None, "needs numpy")
class FrameTest(unittest.TestCase):
    def test_the_edge_width_is_the_10_to_90_percent_width_of_a_gaussian_edge(self):
        for sigma in (2.0, 5.0):
            for angle in (0.0, 30.0):
                s, a = edge(sigma, angle=angle)
                m = shadow_measure.frame_measures(s, a)
                self.assertAlmostEqual(m["edge_width_px"], 2.563 * sigma, delta=0.08 * 2.563 * sigma, msg=(sigma, angle))

    def test_a_softer_edge_measures_wider_and_covers_the_same(self):
        hard = shadow_measure.frame_measures(*edge(0.6))
        soft = shadow_measure.frame_measures(*edge(4.0))
        self.assertGreater(soft["edge_width_px"], 3 * hard["edge_width_px"])
        self.assertAlmostEqual(soft["mean_light"], hard["mean_light"], delta=0.01)
        self.assertGreater(soft["half_lit"], hard["half_lit"])

    def test_the_outline_of_the_body_is_no_shadow_edge(self):
        # a lit body on a transparent background: its border is not measured as an edge
        s = np.ones((60, 80))
        a = np.zeros((60, 80))
        a[10:50, 20:60] = 255
        m = shadow_measure.frame_measures(s, a)
        self.assertEqual(m["half_px"], 0)
        self.assertIsNone(m["edge_width_px"])
        self.assertEqual(m["full_shadow"], 0.0)
        self.assertEqual(m["body_px"], 38 * 38)


@unittest.skipUnless(np is not None, "needs numpy")
class FlickerTest(unittest.TestCase):
    def test_a_still_shadow_does_not_flicker_and_one_that_steps_back_and_forth_does(self):
        s, a = edge(1.0)
        still = shadow_measure.flicker([s, s, s, s], [a, a, a, a])
        self.assertEqual(still, {"mean_change": 0.0, "rms_change": 0.0, "jump_share": 0.0,
                                 "mean_second_difference": 0.0, "flicker_ratio": 0.0})
        left, _ = edge(0.0, at=79.0)
        right, _ = edge(0.0, at=81.0)
        hard = shadow_measure.flicker([left, right, left, right], [a] * 4)
        self.assertGreater(hard["jump_share"], 0.0)
        self.assertAlmostEqual(hard["flicker_ratio"], 2.0, places=6)      # one way and back
        # the same steps made by a soft edge: the same mean change, but no jumps and a smaller root mean square
        sl, _ = edge(4.0, at=79.0)
        sr, _ = edge(4.0, at=81.0)
        soft = shadow_measure.flicker([sl, sr, sl, sr], [a] * 4)
        self.assertAlmostEqual(soft["mean_change"], hard["mean_change"], delta=0.02 * hard["mean_change"])
        self.assertEqual(soft["jump_share"], 0.0)
        self.assertLess(soft["rms_change"], 0.5 * hard["rms_change"])
        self.assertAlmostEqual(soft["flicker_ratio"], 2.0, places=6)

    def test_a_shadow_gliding_one_way_has_a_small_flicker_ratio(self):
        frames = [edge(3.0, at=60.0 + 0.5 * t)[0] for t in range(6)]
        a = np.full(frames[0].shape, 255.0)
        glide = shadow_measure.flicker(frames, [a] * 6)
        self.assertGreater(glide["mean_change"], 0.0)
        self.assertLess(glide["flicker_ratio"], 0.3)


@unittest.skipUnless(np is not None, "needs numpy")
class ShadeTest(unittest.TestCase):
    """what the shade keeps of the light, on pictures whose answer is known"""

    def test_the_shade_keeps_what_the_shaded_picture_keeps_of_the_lit_one(self):
        h, w = 40, 60
        shadow = np.ones((h, w))
        shadow[:, :30] = 0.0                                   # the left half in full shadow
        alpha = np.full((h, w), 255.0)
        lit = np.zeros((h, w, 3))
        lit[...] = (220.0, 180.0, 170.0)
        shaded = lit.copy()
        shaded[:, :30] *= 0.4                                  # the shade keeps 0.4 of every channel
        got = shadow_measure.shade([shadow], [alpha], [(shaded, alpha)], [(lit, alpha)])
        self.assertAlmostEqual(got["shade_keeps"], 0.4, places=6)
        self.assertAlmostEqual(got["lit_keeps"], 1.0, places=6)
        self.assertGreater(got["shade_keeps_px"], 500)
        # a tinted shade (MMD's toon colour): its luma over the lit luma
        tint = np.array([0.99, 0.86, 0.89])
        shaded[:, :30] = lit[:, :30] * tint
        got = shadow_measure.shade([shadow], [alpha], [(shaded, alpha)], [(lit, alpha)])
        want = float((lit[0, 0] * tint) @ shadow_measure.LUMA / (lit[0, 0] @ shadow_measure.LUMA))
        self.assertAlmostEqual(got["shade_keeps"], want, places=6)

    def test_only_the_body_and_bright_enough_pixels_count(self):
        h, w = 30, 30
        shadow = np.zeros((h, w))
        alpha = np.full((h, w), 255.0)
        alpha[:, 20:] = 0.0                                    # not body
        lit = np.full((h, w, 3), 200.0)
        lit[:5] = 10.0                                         # too dark to read
        shaded = lit * 0.5
        got = shadow_measure.shade([shadow], [alpha], [(shaded, alpha)], [(lit, alpha)])
        self.assertAlmostEqual(got["shade_keeps"], 0.5, places=6)
        self.assertEqual(got["shade_keeps_px"], int(shadow_measure.inner(alpha)[5:].sum()))
        self.assertIsNone(got["lit_keeps"])


if __name__ == "__main__":
    unittest.main()
