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


def between_lines(view, z=7.5, x=2.5):
    """the pixel of a point of the floor between its lines (they lie every 5 units)"""
    u, v, _ = view.project([(x, 0.0, z)])
    return int(round(v[0])), int(round(u[0]))


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class FloorLightTest(unittest.TestCase):
    """the light on the floor (look2): its plane takes stage.floor_plane, and it mirrors the cyc, the light and the lamps
    above it (stage.reflect, by Fresnel's share: more at a grazing view, the far floor)"""

    def test_the_plane_between_the_lines_takes_its_colour_and_the_lines_keep_theirs(self):
        view = mv_world.View(state(**DOWN), SIZE)
        plain = mv_world.floor([view], mv_look.merge_look({"stage": {"world": 1}}), SIZE)[0]
        lit = mv_world.floor([view], mv_look.merge_look({"stage": {"world": 1, "floor_plane": [30.0, 45.0, 90.0]}}), SIZE)[0]
        row, col = between_lines(view)
        numpy.testing.assert_allclose(plain[row, col], mv_world.FLOOR_COLOURS["plane"], atol=0.01)
        numpy.testing.assert_allclose(lit[row, col], [30.0, 45.0, 90.0], atol=0.01)
        u, v, _ = view.project([(5.0 + 0.0, 0.0, 7.5)])           # on the line x = 5 (an accent every 4: x 20 is one)
        on = (int(round(v[0])), int(round(u[0])))
        self.assertGreater(lit[on].sum(), lit[row, col].sum())

    def test_on_a_brightly_lit_floor_the_lines_still_shine_over_it(self):
        # v7's line material lets 45 % of the plane under it through (its alpha 0.55; an accent 20 %, alpha 0.80): a plane
        # lit brighter than a line's own light shows through it, and the line stays brighter than the plane round it
        view = mv_world.View(state(**DOWN), SIZE)
        bright = [66.0, 88.0, 156.0]
        dark = mv_world.floor([view], mv_look.merge_look({"stage": {"world": 1}}), SIZE)[0]
        lit = mv_world.floor([view], mv_look.merge_look({"stage": {"world": 1, "floor_plane": bright}}), SIZE)[0]
        row, col = between_lines(view)
        for x in (5.0, 0.0):                                       # a line, and an accent (x 0: every 4th from 0)
            u, v, _ = view.project([(x, 0.0, 7.5)])
            on = (int(round(v[0])), int(round(u[0])))
            self.assertGreater(lit[on].sum(), lit[row, col].sum() + 20.0, x)
            self.assertGreater(lit[on].sum(), dark[on].sum())

    def test_the_floor_mirrors_the_cyc_more_where_it_is_seen_at_a_grazing_angle(self):
        flat = {"world": 1, "floor_plane": [0.0, 0.0, 0.0]}
        look = dict(PLAIN, plate={"vignette": 0.0, "base": [60, 70, 110]})
        dark = stage(dict(look, stage=flat), SIZE, state(**DOWN))
        mirror = stage(dict(look, stage=dict(flat, reflect=1.0)), SIZE, state(**DOWN))
        view = mv_world.View(state(**DOWN), SIZE)
        near, far = between_lines(view, z=-7.5), between_lines(view, z=37.5)
        lift = lambda at: float((mirror[at] - dark[at]).sum())
        self.assertGreater(lift(far), 0.0)
        self.assertGreater(lift(far), 2.0 * lift(near), (lift(far), lift(near)))
        # off the floor (the cyc above it) nothing changes
        numpy.testing.assert_array_equal(mirror[:5], dark[:5])

    def test_the_floor_mirrors_a_bright_band_where_a_mirror_would_show_it(self):
        # the plate's haze band at the horizon of the reference picture: a level camera at height 6 over a mirror sees it at
        # the elevation e above its eye and its reflection at -(e + 2 x 6 / distance) below: under the horizon, upside down
        level = dict(look_at=(0.0, 6.0, 0.0), distance=40.0, angles=(0.0, 0.0, 0.0), fov=40.0)
        look = dict(PLAIN, plate={"vignette": 0.0, "horizon": 0.30, "haze": [200, 200, 200], "pool": [0, 0, 0]})
        flat = {"world": 1, "floor_plane": [0.0, 0.0, 0.0], "floor_half": 200.0}
        dark = stage(dict(look, stage=flat), SIZE, state(**level))
        mirror = stage(dict(look, stage=dict(flat, reflect=1.0, reflect_blur=0.5)), SIZE, state(**level))
        column = (mirror - dark)[:, SIZE[0] // 2].sum(axis=1)
        band = int(numpy.argmax(dark[:, SIZE[0] // 2].sum(axis=1)))                   # the haze band, above the horizon
        self.assertLess(band, SIZE[1] // 2)
        seen = int(numpy.argmax(column))
        self.assertGreater(seen, SIZE[1] // 2)                                       # its reflection lies under the horizon
        self.assertGreater(column[seen], 5.0)

    def test_the_floor_light_is_refused_out_of_its_range(self):
        for stage_ in ({"world": 1, "reflect": -0.1}, {"world": 1, "reflect": 1.5}, {"world": 1, "reflect_blur": -1.0},
                       {"world": 1, "floor_plane": [10, -1, 3]}, {"reflect": 0.5}):
            with self.assertRaises(ValueError, msg=stage_):
                mv_look.merge_look({"stage": stage_})


LAMPS = {"cyc": 400, "edge_step": 2.5, "size": 2.0, "power": 3.0, "twinkle": 0.0}


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class LampsTest(unittest.TestCase):
    """small lamps on the stage (look2): a star cloth on the cyc and lamps along the floor's edges, brighter than white at
    their cores, with a glow of their own"""

    def look(self, **lamps):
        return mv_look.merge_look(dict(PLAIN, stage={"world": 1}, lamps=dict(LAMPS, **lamps)))

    def test_the_lamps_lie_on_the_cyc_and_along_the_edges_of_the_floor(self):
        look = self.look()
        places = mv_world.lamp_places(look, SIZE)
        cyc = [p for p in places if p["on"] == "cyc"]
        edge = [p for p in places if p["on"] == "edge"]
        self.assertEqual(len(cyc), 400)
        for p in cyc:
            self.assertAlmostEqual(math.hypot(p["at"][0], p["at"][2]), 120.0, places=6)      # on the cyc (stage.radius)
            self.assertLess(abs(math.degrees(math.atan2(p["at"][0], p["at"][2]))), 80.0 + 1e-9)  # over stage.specks
        self.assertEqual(len(edge), 4 * 48)                       # 120 / 2.5 to a side, the corners once
        for p in edge:
            x, y, z = p["at"]
            self.assertTrue(abs(abs(x) - 60.0) < 1e-9 or abs(abs(z) - 60.0) < 1e-9, p["at"])
            self.assertAlmostEqual(y, look["stage"]["floor_y"] + mv_world.LAMP_LIFT)
        self.assertEqual(mv_world.lamp_places(mv_look.merge_look({"stage": {"world": 1}}), SIZE), [])

    def test_a_lamp_is_brighter_than_white_at_its_core_where_it_projects(self):
        look = self.look(cyc=0)
        view = mv_world.View(state(**DOWN), SIZE)
        layer = mv_world.lamp_layer(view, look, 0.0, mv_world.lamp_places(look, SIZE))
        u, v, depth = view.project([p["at"] for p in mv_world.lamp_places(look, SIZE) if p["at"][2] == 60.0])
        seen = [(int(round(b)), int(round(a))) for a, b, d in zip(u, v, depth) if 3 <= a < SIZE[0] - 3 and 3 <= b < SIZE[1] - 3]
        self.assertGreater(len(seen), 5)
        for row, col in seen:
            self.assertGreater(layer[row, col].min(), 255.0)       # every channel past white at the core

    def test_the_floor_hides_the_cyc_lamps_behind_it_and_the_dancer_does_the_rest(self):
        look = self.look(edge_step=0.0)
        img = stage(look, SIZE, state(**DOWN))
        bare = stage(dict(PLAIN, stage={"world": 1}), SIZE, state(**DOWN))
        view = mv_world.View(state(**DOWN), SIZE)
        _, cover = mv_world.floor([view], look, SIZE)
        lit = (img - bare).sum(axis=2) > 30
        self.assertGreater(lit[cover < 0.01].sum(), 10)            # over the cyc
        self.assertEqual(int(lit[cover > 0.99].sum()), 0)          # none through the floor

    def test_the_lamps_twinkle_round_the_light_loop_and_close_it(self):
        look = self.look(cyc=0, twinkle=0.8, cycles=3)
        view = mv_world.View(state(**DOWN), SIZE)
        places = mv_world.lamp_places(look, SIZE)
        layers = [mv_world.lamp_layer(view, look, phase, places) for phase in (0.0, 0.7, 2.0 * math.pi)]
        numpy.testing.assert_allclose(layers[0], layers[2], atol=1e-6)
        self.assertGreater(float(numpy.abs(layers[1] - layers[0]).max()), 50.0)
        self.assertLessEqual(float(layers[1].max()), float(LAMPS["power"]) * 255.0 + 1e-6)

    def test_the_glow_spreads_the_lamps_light_and_none_without_it(self):
        view = mv_world.View(state(**DOWN), SIZE)
        u, v, _ = view.project([(0.0, 0.0, 60.0)])
        row, col = int(round(v[0])), int(round(u[0]))
        # (one lamp in the picture: a lamp every 60 along the edges, the far edge's middle one; the corners lie outside)
        bare = stage(self.look(cyc=0, edge_step=60.0, glow=0.0), SIZE, state(**DOWN))
        glow = stage(self.look(cyc=0, edge_step=60.0, glow=0.6, glow_radius=16.0), SIZE, state(**DOWN))
        ring = (slice(row - 6, row - 3), slice(col - 1, col + 2))    # 3 to 6 px above the far edge's middle lamp
        # the glow's middle is 0.6 of the lamp's colour: at 3 to 6 px of a Gaussian of 4 px, some 0.4 to 0.75 of that
        self.assertGreater(float(glow[ring].mean()), float(bare[ring].mean()) + 40.0)
        far = (slice(row - 6, row - 3), slice(col + 40, col + 43))   # and nothing 40 px away
        self.assertAlmostEqual(float(glow[far].mean()), float(bare[far].mean()), delta=0.5)

    def test_under_dof_a_far_lamp_blurs_into_a_disc_and_stays_white(self):
        view = mv_world.View(state(**DOWN), SIZE)
        u, v, _ = view.project([(0.0, 0.0, 60.0)])
        row, col = int(round(v[0])), int(round(u[0]))
        # (a far lamp spreads its light as it blurs: one twenty times white keeps a disc of white, a bigger one)
        sharp = stage(self.look(cyc=0, power=20.0), SIZE, state(**DOWN))
        soft = stage(dict(self.look(cyc=0, power=20.0), stage={"world": 1, "dof": 12.0}), SIZE, state(**DOWN))
        bright = lambda img: int((img[row - 8:row + 9, col - 8:col + 9].min(axis=2) >= 250).sum())
        self.assertGreater(bright(soft), bright(sharp))             # a bigger disc of white

    def test_lamps_are_refused_without_the_world_or_out_of_their_range(self):
        for look in ({"lamps": {"cyc": 10}}, {"stage": {"world": 1}, "lamps": {"cyc": -1}},
                     {"stage": {"world": 1}, "lamps": {"cyc": 2.5}}, {"stage": {"world": 1}, "lamps": {"edge_step": -1}},
                     {"stage": {"world": 1}, "lamps": {"cycles": 0}}, {"stage": {"world": 1}, "lamps": {"twinkle": 1.5}},
                     {"stage": {"world": 1}, "lamps": {"size": 0}}, {"stage": {"world": 1}, "lamps": {"glow": -0.1}}):
            with self.assertRaises(ValueError, msg=look):
                mv_look.merge_look(look)


if __name__ == "__main__":
    unittest.main()
