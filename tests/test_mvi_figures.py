"""tools/mvi/plot.py (the time figure) and marks.py (the marks on a rendered picture): the projection through a camera VMD
puts the look-at point in the picture's middle and the model's left on the picture's right; the marks and the figure
are drawn where the points and the places are."""
import math
import os
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from tests import mvi_fixtures as MF
from mvi import base, marks, plot, report


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cam_path = MF.front_camera(os.path.join(self.folder, "cam.vmd"), y=10.0, distance=45.0, fov=30)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_the_look_at_point_is_the_middle(self):
        cam = marks.Camera(self.cam_path).at(0, (1280, 720))
        q = marks.project([[0.0, 10.0, 0.0]], cam)[0]
        self.assertAlmostEqual(q[0], 640.0, places=6)
        self.assertAlmostEqual(q[1], 360.0, places=6)

    def test_the_models_left_is_the_pictures_right_and_up_is_up(self):
        cam = marks.Camera(self.cam_path).at(0, (1280, 720))
        f = 360.0 / math.tan(math.radians(15.0))
        q = marks.project([[1.0, 10.0, 0.0], [0.0, 11.0, 0.0]], cam)
        self.assertAlmostEqual(q[0][0], 640.0 + f * 1.0 / 45.0, places=6)
        self.assertAlmostEqual(q[1][1], 360.0 - f * 1.0 / 45.0, places=6)

    def test_a_point_behind_the_camera_is_not_drawn(self):
        cam = marks.Camera(self.cam_path).at(0, (1280, 720))
        self.assertTrue(np.all(np.isnan(marks.project([[0.0, 10.0, -60.0]], cam))))

    def test_marks_on_a_picture(self):
        F = 10
        arr = {"com": np.tile(np.array([0.0, 0.8, 0.0]), (F, 1)), "zmp": np.tile(np.array([0.08, 0.0]), (F, 1)),
               "margin": np.full(F, 0.02), "floor_y": 0.111,
               "hulls": [np.array([[-0.1, -0.05], [0.1, -0.05], [0.1, 0.05], [-0.1, 0.05]])] * F}
        pts = os.path.join(self.folder, "marks.npz")
        marks.save_points(pts, arr)
        pic = os.path.join(self.folder, "pic.png")
        Image.new("RGB", (1280, 720), (90, 90, 90)).save(pic)
        rep = {"label": "t", "events": [dict(base.event("skirt.floor_over122_frames", 3, 6, 130.0, "u/s²", 122.0, 12.2, "床で 130"),
                                             listed=True)]}
        res = marks.mark(rep, pts, self.cam_path, [(4, pic)], os.path.join(self.folder, "out"))
        self.assertTrue(os.path.isfile(res[0]["out"]))
        self.assertEqual(res[0]["events"], ["skirt.floor_over122_frames"])
        cam = marks.Camera(self.cam_path).at(4, (1280, 720))
        exp = marks.project([[0.0, 0.8 / 0.08, 0.0]], cam)[0]
        self.assertAlmostEqual(res[0]["com_px"][0], exp[0], places=1)
        self.assertEqual(len(res[0]["support_px"]), 4)
        img = np.asarray(Image.open(res[0]["out"]).convert("RGB"), dtype=int)
        x, y = [int(round(v)) for v in res[0]["zmp_px"]]
        self.assertGreater(img[y, x, 0], 150)                     # the red cross is drawn at the ZMP

    def test_a_base_of_one_point_is_drawn_and_no_base_is_said(self):
        F = 4
        one = np.array([[0.05, 0.0]])
        arr = {"com": np.tile(np.array([0.0, 0.8, 0.0]), (F, 1)), "zmp": np.tile(np.array([-0.3, 0.0]), (F, 1)),
               "margin": np.array([-0.35, -0.35, np.nan, np.nan]), "floor_y": 0.0,
               "hulls": [one, one, np.zeros((0, 2)), np.zeros((0, 2))]}
        pts = os.path.join(self.folder, "marks.npz")
        marks.save_points(pts, arr)
        pic = os.path.join(self.folder, "pic.png")
        Image.new("RGB", (1280, 720), (90, 90, 90)).save(pic)
        res = marks.mark({"label": "t", "events": []}, pts, self.cam_path, [(1, pic), (2, pic)], os.path.join(self.folder, "out"))
        img = np.asarray(Image.open(res[0]["out"]).convert("RGB"), dtype=int)
        x, y = [int(round(v)) for v in res[0]["support_px"][0]]
        self.assertGreater(img[y, x, 1], 120)                     # the one point of support is a green dot
        self.assertLess(img[y, x, 0], 60)
        self.assertNotIn("support_px", res[1])                    # no foot on the floor: nothing drawn for the base

    def test_a_rolling_camera_is_refused(self):
        k = dict(distance=-45.0, position=(0.0, 10.0, 0.0), rotation=(0.0, 0.0, 0.3), fov=30)
        from mmd_cli.formats import vmd
        path = os.path.join(self.folder, "roll.vmd")
        vmd.dump(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **k)]), path)
        with self.assertRaises(ValueError):
            marks.Camera(path).at(0, (1280, 720))


class FigureTest(unittest.TestCase):
    def test_the_time_figure(self):
        folder = tempfile.mkdtemp()
        try:
            F = 900
            rep = report.mark_listed({"label": "t", "frames": F, "measures": [
                {"id": "skirt.floor_over122_frames", "concept": "skirt", "judge": {"side": 1}, "ref": {"kind": "limit", "max": 0}}],
                "events": [base.event("skirt.floor_over122_frames", 300, 310, 140.0, "u/s²", 122.0, 12.2)],
                "series": {"pelvis_down": {"label": "腰", "unit": "u/s²", "lo": None, "hi": 122.0, "concept": "skirt",
                                           "ids": ["skirt.floor_over122_frames"]}}})
            y = np.zeros(F)
            y[300:311] = 140.0
            path = plot.figure(rep, {"pelvis_down": y, "air": np.zeros(F, bool)}, os.path.join(folder, "f.png"))
            img = Image.open(path)
            self.assertEqual(img.size, (plot.WIDTH, plot.TOP + plot.ROW + 40))
            a = np.asarray(img.convert("RGB"), dtype=int)
            x = int(plot.LEFT + 305 / F * (plot.WIDTH - plot.LEFT - plot.RIGHT))
            band = a[plot.TOP + 23:plot.TOP + 29, x]
            self.assertTrue(np.any((band[:, 0] > 180) & (band[:, 1] < 80)))      # the place in red above the curve
            with self.assertRaises(ValueError):
                plot.figure(rep, {"pelvis_down": y}, os.path.join(folder, "g.png"), t0=10.0, t1=10.0)
        finally:
            shutil.rmtree(folder)

    def test_a_foots_place_is_on_that_foots_row_and_a_short_span_is_one_line(self):
        folder = tempfile.mkdtemp()
        try:
            F = 100
            shoe = {"unit": "cm", "lo": 0.0, "hi": None, "concept": "feet", "ids": ["feet.slide10_per_min"]}
            rep = report.mark_listed({"label": "t", "frames": F, "measures": [
                {"id": "feet.slide10_per_min", "concept": "feet", "judge": {"side": 1}, "ref": {"kind": "limit", "max": 0}}],
                "events": [base.event("feet.slide10_per_min", 40, 60, 20.0, "cm", 10.0, 10.0, foot="R")],
                "series": {"shoe_left": dict(shoe, label="左", foot="L"), "shoe_right": dict(shoe, label="右", foot="R")}})
            y = np.linspace(0.0, 5.0, F)
            path = plot.figure(rep, {"shoe_left": y, "shoe_right": y}, os.path.join(folder, "f.png"))
            a = np.asarray(Image.open(path).convert("RGB"), dtype=int)
            cols = plot.WIDTH - plot.LEFT - plot.RIGHT
            x = int(plot.LEFT + 50.5 / F * cols)
            red = lambda k: np.any((a[plot.TOP + k * plot.ROW + 23:plot.TOP + k * plot.ROW + 29, x, 0] > 180) &   # noqa: E731
                                   (a[plot.TOP + k * plot.ROW + 23:plot.TOP + k * plot.ROW + 29, x, 1] < 80))
            self.assertFalse(red(0))                                  # the left shoe's row: not the right foot's place
            self.assertTrue(red(1))
            row = a[plot.TOP + 31:plot.TOP + plot.ROW - 7]
            blue = (np.abs(row[:, :, 0] - plot.CURVE[0]) < 40) & (np.abs(row[:, :, 2] - plot.CURVE[2]) < 40) & (row[:, :, 2] > 120)
            xs = range(int(plot.LEFT + 0.5 / F * cols) + 1, int(plot.LEFT + 99.5 / F * cols) - 1)
            self.assertTrue(all(blue[:, c].any() for c in xs))        # no gaps between the frames
        finally:
            shutil.rmtree(folder)


if __name__ == "__main__":
    unittest.main()
