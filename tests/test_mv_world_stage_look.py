"""tools/mv_world.py: the look of the stage in the world (look2, 2026-10-18): the stage blurred by its distance from the
focus (depth of field), and every new setting left off draws the stage of before, byte for byte."""
import hashlib
import importlib.util
import math
import os
import sys
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
    from mmd_cli.formats import vmd


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_world = load("mv_world") if numpy is not None else None
mv_look = load("mv_look") if numpy is not None else None


class Fig:
    """a dancer as Figure.state gives her: two feet, the pelvis, the centre, and two capsules of her body"""

    def __init__(self):
        self.feet = [((-1.0, 0.9, 0.5), (-1.2, 0.1, -1.0)), ((1.0, 2.0, 0.3), (1.1, 1.2, -1.1))]
        self.pelvis = (0.0, 10.0, 0.0)
        self.centre = (0.5, 0.2)
        self.rest = (0.9, 0.1)
        self.capsules = [((0.0, 10.0, 0.0), (0.0, 15.0, 0.0), 1.0), ((-1.0, 0.9, 0.5), (-1.2, 0.42, -1.0), 0.42)]
        self.capsule_groups = ["torso", "left foot"]

    def state(self, frame):
        return self


def state(look_at=(0.0, 13.0, 0.0), distance=38.0, angles=(0.0, 0.0, 0.0), fov=30.0):
    return fk.CameraState(0, tuple(look_at), float(distance), tuple(angles), float(fov))


def track_of(st):
    """a camera motion that holds the camera state `st` from frame 0 to 100 (what stage_image reads)"""
    key = dict(distance=-st.distance, position=st.look_at,
               rotation=(-math.radians(st.angles[0]), math.radians(st.angles[1]), 0.0), fov=st.fov)
    keys = fk.camera_keys(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **key), vmd.CameraKey(frame=100, **key)]))
    return keys, [k.frame for k in keys]


def stage(look, size, st, index=0, figure=None):
    """the stage picture of video frame `index` (30 fps, the dancer folded from 8 subframes at a shutter of 0.5) as floats"""
    look = mv_look.merge_look(look)
    img = mv_world.stage_image(look, size, track_of(st), 30, index, mv_look.light_frame_count(look, 30), subframes=8,
                               shutter=0.5, figure=figure)
    return numpy.asarray(img, dtype=numpy.float64)


# three stages main c6030c6 drew (the SHA-256 of their pixels, the same on this PC with numpy 2.4.6 and on hinata with 2.2.6,
# _spike/out/stage6/look2/scripts/stage_golden.py): the default stage in the world from above and in front, the stage of
# v11 r2 (its look, the pool and the soft shadow of a dancer) and a cyc infinitely far seen turned 30 degrees
BEFORE = (
    ("plain", {"stage": {"world": 1}}, (320, 180), ((0.0, 11.0, 0.0), 42.0, (12.0, 0.0, 0.0), 30.0), False,
     {0: "6a740d43ac9bcbb3bff9d6d88971b2d05104ec8f589d9303898555cebf908c04",
      37: "da97ca5ab6de3b116a06fb7b8a20efa6ee6a3720bc28270b175c2d0fb8872aa3"}),
    ("v11", {"flares": [44.467], "beams": {"loop_seconds": 27.428571, "cycles": [2, 3]}, "bokeh": {"cycles": [2, 3]},
             "stage": {"world": 1, "pool": 1.0, "shadow": 1.0, "floor_y": 0.111}}, (160, 180),
     ((1.0, 9.0, 2.0), 45.0, (15.0, -8.0, 0.0), 30.0), True,
     {0: "d4a263410991a36a267ef0c7f4ddc93fa28e22bbc46718e9a08644a5f806f22c",
      37: "e1297fe7b969f0508505eef0075b462c3c20b18679ccc76fa0de3011e24f2466"}),
    ("far", {"stage": {"world": 1, "radius": 0.0}}, (320, 180), ((0.0, 13.0, 0.0), 38.0, (0.0, 30.0, 0.0), 24.0), False,
     {0: "71b0b8dfdce193db1e63a166edbefc87f97b67eaf95a78a9f24e0ba85f1c3a35",
      37: "05fa4c7cc4fa2f0d9364d8a5808f960a9cfc64872b79bec4a3e9a0677d234c07"}),
)


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class StageOfBeforeTest(unittest.TestCase):
    def test_every_new_setting_left_off_draws_the_stage_of_before(self):
        for name, look, size, (look_at, distance, angles, fov), dancer, golden in BEFORE:
            for index, digest in golden.items():
                look_ = mv_look.merge_look(look)
                img = mv_world.stage_image(look_, size, track_of(state(look_at, distance, angles, fov)), 30, index,
                                           mv_look.light_frame_count(look_, 30), subframes=8, shutter=0.5,
                                           figure=Fig() if dancer else None)
                self.assertEqual(hashlib.sha256(numpy.asarray(img).tobytes()).hexdigest(), digest, (name, index))


# a camera 40 in front of a point on the floor, looking down at it by 20 degrees: the floor runs from in front of the focus
# (the bottom of the picture) to far behind it (the top), the cyc above
DOWN = dict(look_at=(0.0, 0.0, 0.0), distance=40.0, angles=(20.0, 0.0, 0.0), fov=30.0)
SIZE = (320, 180)
PLAIN = {"beams": {"count": 0}, "bokeh": {"count": 0}, "plate": {"vignette": 0.0}}


def contrast(img, centre, half=6):
    """how far the luminance spreads (max - min) in a square round a pixel (u, v): the floor's lines against its plane"""
    u, v = int(round(centre[0])), int(round(centre[1]))
    y = img[v - half:v + half + 1, u - half:u + half + 1] @ numpy.array([0.2126, 0.7152, 0.0722])
    return float(y.max() - y.min())


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class DepthOfFieldTest(unittest.TestCase):
    def test_the_blur_is_none_at_the_focus_and_grows_as_a_thin_lens_has_it(self):
        # a thin lens: the circle of confusion of what lies at depth d with the focus at f grows as |1 - f / d|: 0 at the
        # focus, half of the far blur at twice its distance, all of it infinitely far, as much again at half its distance
        # (in front of it), and no more than DOF_MOST times it nearer still
        got = mv_world.blur_of(numpy.array([40.0, 80.0, numpy.inf, 20.0, 1.0]), 40.0, 3.0)
        numpy.testing.assert_allclose(got[:4], [0.0, 1.5, 3.0, 3.0], atol=1e-9)
        self.assertEqual(got[4], mv_world.DOF_MOST * 3.0)
        self.assertGreater(mv_world.DOF_MOST, 1.0)

    def test_defocus_spreads_a_point_by_its_own_blur(self):
        img = numpy.zeros((61, 81, 3))
        img[30, 20] = img[30, 60] = 1000.0
        sigma = numpy.zeros((61, 81))
        sigma[:, 40:] = 2.5                           # the left point in focus, the right one blurred by 2.5 px
        out = mv_world.defocus(img, sigma)
        numpy.testing.assert_array_equal(out[:, :38], img[:, :38])
        right = out[18:43, 48:73, 0]
        self.assertAlmostEqual(right.sum(), 1000.0, delta=1.0)                  # the light is kept, only spread
        ys, xs = numpy.mgrid[18:43, 48:73]
        spread = math.sqrt(float((right * ((ys - 30) ** 2 + (xs - 60) ** 2)).sum() / right.sum() / 2.0))
        self.assertAlmostEqual(spread, 2.5, delta=0.15)
        # between two levels of blur the spread is between theirs
        sigma[:, 40:] = 1.7
        right = mv_world.defocus(img, sigma)[18:43, 48:73, 0]
        spread = math.sqrt(float((right * ((ys - 30) ** 2 + (xs - 60) ** 2)).sum() / right.sum() / 2.0))
        self.assertAlmostEqual(spread, 1.7, delta=0.15)

    def test_the_floor_at_the_focus_stays_sharp_and_the_floor_behind_it_and_the_cyc_blur(self):
        # (12 px of a 720 line picture are 3 at these 180 lines: the floor at z 45 lies about twice as far as the focus)
        sharp = stage(dict(PLAIN, stage={"world": 1}), SIZE, state(**DOWN))
        soft = stage(dict(PLAIN, stage={"world": 1, "dof": 12.0}), SIZE, state(**DOWN))
        view = mv_world.View(state(**DOWN), SIZE)
        (u0, u1), (v0, v1), _ = view.project([(2.5, 0.0, 0.0), (2.5, 0.0, 45.0)])
        at_focus, far = (u0, v0), (u1, v1)
        self.assertLess(abs(contrast(soft, at_focus) - contrast(sharp, at_focus)), 0.05 * contrast(sharp, at_focus) + 1.0)
        self.assertLess(contrast(soft, far), 0.75 * contrast(sharp, far), (contrast(soft, far), contrast(sharp, far)))
        # the cyc (its haze and its pool) only softens: the mean light over the picture stays
        self.assertAlmostEqual(soft.mean(), sharp.mean(), delta=0.5)

    def test_the_focus_is_the_cameras_look_at_point_unless_dof_focus_says(self):
        view = mv_world.View(state(**DOWN), SIZE)
        u, v, depth = view.project([(2.5, 0.0, 0.0)])
        self.assertAlmostEqual(float(depth[0]), 40.0, delta=1.5)      # the look-at point lies at the camera's distance
        sharp = stage(dict(PLAIN, stage={"world": 1}), SIZE, state(**DOWN))
        near = stage(dict(PLAIN, stage={"world": 1, "dof": 12.0, "dof_focus": 20.0}), SIZE, state(**DOWN))
        at = (u[0], v[0])
        self.assertLess(contrast(near, at), 0.75 * contrast(sharp, at))

    def test_dof_is_refused_where_it_cannot_blur(self):
        for stage_ in ({"dof": 2.0}, {"world": 1, "dof": -1.0}, {"world": 1, "dof_focus": -5.0}):
            with self.assertRaises(ValueError, msg=stage_):
                mv_look.merge_look({"stage": stage_})
        mv_look.merge_look({"stage": {"world": 1, "dof": 2.0, "dof_focus": 30.0}})


if __name__ == "__main__":
    unittest.main()
