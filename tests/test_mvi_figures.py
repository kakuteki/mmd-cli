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


if __name__ == "__main__":
    unittest.main()
