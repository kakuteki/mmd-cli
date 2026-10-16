"""tools/mvi/pixels.py (描いた絵): the measures that read rendered pictures and never render: the underwear pixels of the
green copy's renders (green 160 or more, red and blue 90 or less, opaque) and the floor shadow's flicker
(tools/shadow_check's roughness of the shaded / plain ratio)."""
import os
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from tests import mvi_fixtures  # noqa: F401
from mvi import pixels


class PantsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def picture(self, name, green=0, alpha=255, mode="RGBA"):
        a = np.zeros((40, 60, 4), np.uint8)
        a[..., :3] = (120, 80, 60)
        a[..., 3] = 255
        a[10:10 + green, 20:21] = (30, 200, 40, alpha)
        a[30, 0:5] = (100, 200, 100, 255)                     # bright but not the flat green (red over 90)
        path = os.path.join(self.folder, name)
        Image.fromarray(a, "RGBA").convert(mode).save(path)
        return path

    def test_counts_the_green_pixels_per_picture(self):
        paths = [self.picture("p0.png"), self.picture("p1.png", green=7), self.picture("p2.png", green=3)]
        res = pixels.pants(paths, first_frame=100)
        self.assertEqual([c["pixels"] for c in res["counts"]], [0, 7, 3])
        row = res["rows"][0]
        self.assertEqual((row["value"], row["judge"]["word"]), (2, "上へ外"))
        self.assertEqual([e["first"] for e in res["events"]], [101, 102])

    def test_see_through_green_does_not_count_and_a_box_limits(self):
        p = self.picture("a.png", green=7, alpha=40)
        self.assertEqual(pixels.pants_count(Image.open(p)), 0)
        q = self.picture("b.png", green=7)
        self.assertEqual(pixels.pants_count(Image.open(q), box=(0, 0, 10, 40)), 0)
        self.assertEqual(pixels.pants_count(Image.open(q), box=(15, 0, 30, 40)), 7)

    def test_a_picture_without_alpha_is_read_by_its_colour(self):
        p = self.picture("rgb.png", green=5, mode="RGB")
        self.assertEqual(pixels.pants_count(Image.open(p)), 5)

    def test_no_pants_is_inside_the_rule(self):
        res = pixels.pants([self.picture("z.png")])
        self.assertEqual(res["rows"][0]["judge"]["word"], "中")


class ShadowTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def series(self, darkness):
        for i, d in enumerate(darkness):
            plain = np.full((20, 20, 3), 200, np.uint8)
            shaded = plain.copy()
            shaded[5:15, 5:15] = int(round(200 * (1.0 - d)))
            Image.fromarray(plain).save(os.path.join(self.folder, "plain_%05d.png" % i))
            Image.fromarray(shaded).save(os.path.join(self.folder, "shaded_%05d.png" % i))
        return (os.path.join(self.folder, "plain_%05d.png"), os.path.join(self.folder, "shaded_%05d.png"))

    def test_a_smooth_shadow_is_smooth_and_a_flickering_one_is_rough(self):
        smooth = self.series([0.3 + 0.2 * k / 20.0 for k in range(21)])
        res = pixels.shadow(smooth[0], smooth[1], 0, 20)
        self.assertLess(res["rows"][0]["value"], 0.2)
        rng = np.random.default_rng(1)
        rough = self.series(list(0.4 + 0.1 * rng.standard_normal(21)))
        res = pixels.shadow(rough[0], rough[1], 0, 20)
        self.assertGreater(res["rows"][0]["value"], 1.2)


if __name__ == "__main__":
    unittest.main()
