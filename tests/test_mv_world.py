"""tools/mv_world.py: the stage placed in the world and drawn from the camera of the camera motion, frame by frame."""
import importlib.util
import math
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy
    from PIL import Image
except ImportError:                                   # the tool needs Pillow and numpy; the rest of the suite does not
    numpy = Image = None

if numpy is not None:
    import sys
    sys.path.insert(0, ROOT)
    from mmd_cli import fk, motion_edit
    from mmd_cli.formats import vmd
    from tests.test_fk import build_model, close
    from tests.test_fk import key as bone_key
    from tests.test_fk import motion as bone_motion


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_world = load("mv_world") if numpy is not None else None
mv_look = load("mv_look") if numpy is not None else None
SIZE = (320, 180)


def state(look_at=(0.0, 13.0, 0.0), distance=38.0, angles=(0.0, 0.0, 0.0), fov=30.0):
    return fk.CameraState(0, tuple(look_at), float(distance), tuple(angles), float(fov))


def world_look(plate=None, beams=None, bokeh=None, **stage):
    """the look of mv_look with the stage placed in the world (and the settings given)"""
    look = {"stage": dict({"world": 1}, **stage)}
    for name, value in (("plate", plate), ("beams", beams), ("bokeh", bokeh)):
        if value:
            look[name] = value
    return mv_look.merge_look(look)


FLAT = {"vignette": 0.0}                              # the plate without its darker corners: its pool's peak is where it is


def peak_column(image, rows):
    """the column of the brightest mean over the rows (float array h x w x 3)"""
    return int(numpy.argmax(image[rows[0]:rows[1]].sum(axis=2).mean(axis=0)))


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class ViewTest(unittest.TestCase):
    def test_the_look_at_point_is_in_the_middle_of_the_picture(self):
        for angles in ((0, 0, 0), (10, -22, 0), (-8, 15, 0)):
            view = mv_world.View(state((1.0, 12.0, -6.0), 40.0, angles), (1280, 720))
            u, v, depth = view.project([(1.0, 12.0, -6.0)])
            self.assertAlmostEqual(u[0], 640.0, places=6)
            self.assertAlmostEqual(v[0], 360.0, places=6)
            self.assertAlmostEqual(depth[0], 40.0, places=6)

    def test_mmds_x_is_the_right_of_the_picture_and_its_view_angle_the_height(self):
        # the camera at window angles 0 looks along +Z at her face, and MMD's +X (her left) is on the right of the picture
        view = mv_world.View(state((0, 13, 0), 38.0), (1280, 720))
        u, v, _ = view.project([(1.0, 13.0, 0.0), (0.0, 13.0 + 38.0 * math.tan(math.radians(15)), 0.0)])
        self.assertGreater(u[0], 640.0)
        self.assertAlmostEqual(v[1], 0.0, places=6)          # 15 degrees above the axis: the top of a picture 30 degrees tall

    def test_a_camera_that_turns_about_its_line_of_sight_is_refused(self):
        # which way MMD turns the picture for a roll (window Z) has not been measured: no stage is drawn for it
        with self.assertRaises(ValueError):
            mv_world.View(state(angles=(0.0, 0.0, 5.0)), SIZE)

    def test_a_ray_goes_through_its_pixel(self):
        view = mv_world.View(state((0.5, 12.0, -8.0), 40.0, (10.0, 22.0, 0.0)), SIZE)
        rays = view.rays(1)
        for (row, col) in ((0, 0), (90, 160), (179, 319), (37, 251)):
            u, v, _ = view.project([view.eye + 7.0 * rays[row, col]])
            self.assertAlmostEqual(u[0], col, places=6)
            self.assertAlmostEqual(v[0], row, places=6)

    # MMD's own render of the floor of make_stage.py (defaults) at two frames of the MV's camera: where it drew some points of
    # the lines, measured to a fraction of a pixel across each line (2026-10-13, hinata, `render image` 1280x720;
    # _spike/out/stage6/stage_world/proto/fixture_floor_points.py).  (look_at, distance, window angles, view angle), then
    # (world point, the way its line runs, the measured point)
    MMD_FLOOR = [
        (((0.249855, 11.982017, -10.437363), 44.015846, (10.146501, 0.061278, 0.0), 30.0),
         [((-20.0, 0.0, 12.5), "z", (244.564, 511.454)), ((20.0, 0.0, 7.5), "z", (1056.549, 542.028)),
          ((-17.5, 0.0, 20.0), "x", (327.230, 473.500)), ((12.5, 0.0, 20.0), "x", (856.921, 473.587)),
          ((32.5, 0.0, 40.0), "x", (1093.324, 401.000)), ((7.5, 0.0, 0.0), "x", (812.997, 597.159))]),
        (((0.508376, 12.009764, -8.386548), 40.009541, (-0.050093, -0.310009, 0.0), 30.0),
         [((-20.0, 0.0, 12.5), "z", (184.148, 625.933)), ((20.0, 0.0, 7.5), "z", (1105.587, 648.615)),
          ((-17.5, 0.0, 20.0), "x", (282.675, 596.720)), ((12.5, 0.0, 20.0), "x", (872.354, 596.280)),
          ((32.5, 0.0, 40.0), "x", (1121.375, 543.000)), ((7.5, 0.0, 0.0), "x", (832.726, 693.481))]),
    ]

    def test_it_puts_the_floor_where_mmd_draws_it(self):
        for (look_at, distance, angles, fov), points in self.MMD_FLOOR:
            view = mv_world.View(state(look_at, distance, angles, fov), (1280, 720))
            for point, runs, (mu, mv) in points:
                step = (0.05, 0.0, 0.0) if runs == "x" else (0.0, 0.0, 0.05)
                u, v, _ = view.project([point, tuple(p + s for p, s in zip(point, step))])
                tx, ty = u[1] - u[0], v[1] - v[0]
                n = math.hypot(tx, ty)
                across = ((mu - u[0]) * -ty + (mv - v[0]) * tx) / n           # the distance across the line, in pixels
                self.assertLess(abs(across), 0.3, (point, angles))


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class BackdropTest(unittest.TestCase):
    def test_the_camera_the_look_was_made_for_sees_the_plate_of_before(self):
        look = world_look()
        size = (640, 360)
        mine = mv_world.backdrop(mv_world.reference_view(size), look, 2)
        old = numpy.asarray(mv_look.plate((320, 180), look["plate"]), dtype=numpy.float64)
        # above the floor's far edge (below it the floor hides the cyc).  The plate's rows and the rays of the pixels'
        # middles differ by under a pixel, the plate is rounded to whole levels, and the cyc comes nearer to the sides
        u, edge, _ = mv_world.reference_view((320, 180)).project([(0.0, 0.0, 60.0)])
        gap = numpy.abs(mine - old)[:int(edge[0])]
        self.assertLess(float(gap.mean()), 1.0)
        self.assertLess(float(numpy.percentile(gap, 99)), 3.0)

    def test_turning_the_camera_moves_the_backdrop_where_the_world_point_goes(self):
        look = world_look(plate=FLAT, radius=120.0)
        size = (640, 360)
        a = mv_world.View(state((0, 12, 0), 40.0, (0.0, 0.0, 0.0)), size)
        b = mv_world.View(state((0, 12, 0), 40.0, (0.0, 15.0, 0.0)), size)      # an orbit of 15 degrees
        rows = (60, 120)
        found = [peak_column(mv_world.backdrop(v, look, 1), rows) for v in (a, b)]
        # the pool of light is on the cyc behind the stage: where the world point (0, y, 120) goes on the picture
        expect = [v.project([(0.0, 12.0, 120.0)])[0][0] for v in (a, b)]
        self.assertAlmostEqual(found[0], expect[0], delta=6)
        self.assertAlmostEqual(found[1], expect[1], delta=6)
        # the camera swung to +X round her: what lies beyond her went to the right, as on MMD's render (analysis a16)
        self.assertGreater(expect[1], expect[0] + 100)

    def test_a_backdrop_infinitely_far_moves_with_the_turn_alone(self):
        look = world_look(plate=FLAT, radius=0.0)
        size = (640, 360)
        here = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0), size), look, 1)
        moved = mv_world.backdrop(mv_world.View(state((9, 12, -5), 40.0), size), look, 1)   # the same turn elsewhere
        self.assertLess(float(numpy.abs(here - moved).max()), 0.5)
        turned = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0, (0.0, 10.0, 0.0)), size), look, 1)
        shift = peak_column(turned, (60, 120)) - peak_column(here, (60, 120))
        focal = 180.0 / math.tan(math.radians(15))
        self.assertAlmostEqual(shift, focal * math.tan(math.radians(10)), delta=4)

    def test_looking_down_lifts_the_haze_with_the_floor(self):
        look = world_look(plate=dict(FLAT, pool=[0, 0, 0]), radius=0.0)
        size = (640, 360)
        level = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0), size), look, 1)
        down = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0, (10.0, 0.0, 0.0)), size), look, 1)

        def haze_row(img):
            return int(numpy.argmax(img[:, 300:340].sum(axis=2).mean(axis=1)))
        focal = 180.0 / math.tan(math.radians(15))
        # the haze lies at the angle the reference camera saw it (the plate's horizon 0.68 below the middle); looking down
        # 10 degrees lifts it as much as a far thing at that angle goes up the picture
        haze = math.atan((0.5 - 0.68) * 360 / focal)
        rise = focal * (math.tan(haze + math.radians(10)) - math.tan(haze))
        self.assertAlmostEqual(haze_row(level) - haze_row(down), rise, delta=2)

    def test_the_darker_sides_of_the_plate_lie_on_the_cyc(self):
        # the plate was darker towards its sides and its top and bottom (plate.vignette): on the cyc that darkness is paint of
        # the cyc, where the reference camera saw it, so a point of the cyc is as bright from any camera (a darkening fixed
        # to the picture would follow the camera and pull the backdrop with it; the lens's vignette does that for the picture)
        look = world_look(plate={"haze": [0, 0, 0], "pool": [0, 0, 0], "base": [100, 100, 100]}, radius=120.0)
        size = (640, 360)
        views = [mv_world.View(state((0, 12, 0), 40.0, (0.0, y, 0.0)), size) for y in (0.0, 15.0, -15.0)]
        for theta, height in ((0.0, 20.0), (25.0, 30.0), (-20.0, 5.0), (10.0, 12.0)):
            point = (120.0 * math.sin(math.radians(theta)), height, 120.0 * math.cos(math.radians(theta)))
            seen = []
            for view in views:
                u, v, _ = view.project([point])
                if 2 <= u[0] < size[0] - 2 and 2 <= v[0] < size[1] - 2:
                    seen.append(float(mv_world.backdrop(view, look, 1)[int(v[0]), int(u[0])].mean()))
            self.assertGreaterEqual(len(seen), 2, (theta, height))
            self.assertLess(max(seen) - min(seen), 1.5, (theta, height, seen))
        # and the sides are darker than the middle, as on the plate
        middle = mv_world.backdrop(views[0], look, 1)
        self.assertLess(float(middle[150:210, :20].mean()), 0.8 * float(middle[150:210, 310:330].mean()))


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class LightTest(unittest.TestCase):
    def test_the_beams_fan_down_from_the_truss_and_move_with_it(self):
        look = world_look(truss=60.0)
        size = (640, 360)
        view = mv_world.reference_view(size)
        light = mv_world.beams(view, look, 0.0, 2)
        self.assertGreater(float(light.max()), 10.0)
        # the reference camera sees the truss where the old fan had its origin: above the picture, in the middle
        truss = mv_world.truss_point(look)
        u, v, _ = view.project([truss])
        self.assertAlmostEqual(u[0], 320.0, delta=0.5)
        self.assertAlmostEqual(v[0], -0.35 * 360, delta=0.5)
        turned = mv_world.View(state((0, 13, 0), 38.0, (0.0, 20.0, 0.0)), size)
        u2, _, _ = turned.project([truss])
        top = (0, 40)                                     # the beams near the top of the picture, at half size
        here = peak_column(light, top) * 2
        there = peak_column(mv_world.beams(turned, look, 0.0, 2), top) * 2
        self.assertGreater(there - here, 60)              # the fan went to the right with the truss behind her
        self.assertAlmostEqual(there - here, u2[0] - u[0], delta=80)

    def test_the_camera_the_look_was_made_for_sees_the_fan_of_before(self):
        # the beams fan out from the truss in its plane (z = truss): the reference camera sees each at the angle of the
        # picture-fixed fan, fading down the picture as it did, down to where they reach the floor
        look = world_look(truss=60.0)
        size = (640, 360)
        for phase in (0.0, 2.1):
            mine = mv_world.beams(mv_world.reference_view(size), look, phase, 2)
            old = mv_look._beams((320, 180), look["beams"], phase)
            _, edge, _ = mv_world.reference_view((320, 180)).project([(0.0, 0.0, 60.0)])
            rows = slice(0, int(edge[0]) - 10)                     # above where they reach the floor at the truss
            gap = float(numpy.abs(mine[rows] - old[rows]).mean())
            self.assertLess(gap, 0.12 * float(old[rows].mean()), phase)

    def test_the_specks_lie_in_the_world(self):
        look = world_look(radius=120.0)
        size = (640, 360)
        a = mv_world.View(state((0, 12, 0), 40.0), size)
        b = mv_world.View(state((0, 12, 0), 40.0, (0.0, 8.0, 0.0)), size)
        sa, sb = mv_world.specks(a, look, 0.0, 1), mv_world.specks(b, look, 0.0, 1)
        self.assertGreater(float(sa.max()), 10.0)
        # the whole layer moved left; the best match of the two is near the shift of the cyc's points
        expect = b.project([(0.0, 12.0, 110.0)])[0][0] - a.project([(0.0, 12.0, 110.0)])[0][0]
        gray_a, gray_b = sa.sum(axis=2), sb.sum(axis=2)
        errors = {s: float(numpy.abs(gray_a[:, 200:440] - gray_b[:, 200 + s:440 + s]).mean()) for s in range(-160, 161)}
        best = min(errors, key=errors.get)
        self.assertAlmostEqual(best, expect, delta=12)

    def test_the_same_frame_gives_the_same_light(self):
        look = world_look()
        view = mv_world.View(state((0, 12, 0), 40.0, (5.0, 10.0, 0.0)), SIZE)
        one = mv_world.beams(view, look, 1.3, 2) + mv_world.specks(view, look, 1.3, 2)
        two = mv_world.beams(view, look, 1.3, 2) + mv_world.specks(view, look, 1.3, 2)
        self.assertEqual(one.tobytes(), two.tobytes())


# a rig with the bones the shadows and the pool are read from (MMD's X is her left, she faces -Z)
RIG = (("全ての親", -1, (0.0, 0.0, 0.0), {}), ("センター", 0, (0.0, 8.0, 0.0), {}), ("下半身", 1, (0.0, 10.0, 0.0), {}),
       ("左足ＩＫ", 0, (1.0, 1.7, 0.0), {}), ("左つま先ＩＫ", 3, (1.0, 0.1, -1.6), {}),
       ("右足ＩＫ", 0, (-1.0, 1.7, 0.0), {}), ("右つま先ＩＫ", 5, (-1.0, 0.1, -1.6), {}))


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class FigureTest(unittest.TestCase):
    """where the shadows and the pool are drawn from: the IK bones of her feet, her lower body and her centre"""

    def setUp(self):
        self.model = build_model(*RIG)

    def test_the_feet_are_the_ik_bones_and_the_body_is_the_lower_body(self):
        # by frame 10 the left foot steps 2 forward and lifts 1, and the centre moves 3 to her right
        dance = bone_motion(bone_key("左足ＩＫ", 0), bone_key("左足ＩＫ", 10, pos=(0.0, 1.0, -2.0)),
                            bone_key("センター", 0), bone_key("センター", 10, pos=(-3.0, 0.0, 0.0)))
        state = mv_world.Figure(self.model, dance).state(10)
        (left_ankle, left_toe), (right_ankle, right_toe) = state.feet
        close(self, left_ankle, (1.0, 2.7, -2.0))
        close(self, left_toe, (1.0, 1.1, -3.6))                 # the toe IK goes with the leg IK, its parent
        close(self, right_ankle, (-1.0, 1.7, 0.0))
        close(self, right_toe, (-1.0, 0.1, -1.6))
        close(self, state.pelvis, (-3.0, 10.0, 0.0))            # the lower body, not the centre 2 below it

    def test_the_pool_follows_the_centre_averaged_over_90_frames(self):
        # the centre steps 9 to her left at frame 45: the pool is there by half at that frame and wholly 45 frames later
        dance = bone_motion(bone_key("センター", 0), bone_key("センター", 44), bone_key("センター", 45, pos=(9.0, 0.0, 0.0)),
                            bone_key("センター", 200, pos=(9.0, 0.0, 0.0)))
        figure = mv_world.Figure(self.model, dance)
        self.assertAlmostEqual(figure.state(45).centre[0], 9.0 * 46 / 91, places=6)
        self.assertAlmostEqual(figure.state(150).centre[0], 9.0, places=6)
        self.assertAlmostEqual(figure.state(0).centre[0], 0.0, places=6)

    def test_the_height_of_a_foot_on_the_floor_is_the_low_end_of_the_song(self):
        # on the floor for 30 frames, a unit up for 70: the feet's rest is the height on the floor, not the typical one
        keys = [bone_key(name, f, pos=(0.0, 0.0 if f < 30 else 1.0, 0.0)) for name in ("左足ＩＫ", "右足ＩＫ") for f in range(100)]
        figure = mv_world.Figure(self.model, bone_motion(*keys))
        close(self, figure.rest, (1.7, 0.1))

    def test_a_later_motion_replaces_the_keys_of_an_earlier_one_on_the_same_frame(self):
        # as MMD reads motions one after another (the feet a later layer moved are the ones on the floor)
        dance = bone_motion(bone_key("左足ＩＫ", 0), bone_key("左足ＩＫ", 10, pos=(0.0, 0.0, -2.0)))
        later = bone_motion(bone_key("左足ＩＫ", 10, pos=(0.0, 0.0, -5.0)))
        figure = mv_world.Figure(self.model, mv_world.merge_motions([dance, later]))
        close(self, figure.state(10).feet[0][0], (1.0, 1.7, -5.0))
        close(self, figure.state(0).feet[0][0], (1.0, 1.7, 0.0))

    def test_a_model_without_the_bones_is_refused(self):
        with self.assertRaises(ValueError):
            mv_world.Figure(build_model(*RIG[:5]), bone_motion(bone_key("センター", 0)))


class FakeFigure:
    """feet planted or lifted where a test puts them (what Figure.state gives: ankle and toe of each foot, pelvis, centre)"""

    def __init__(self, left=((-2.0, 1.7, 0.0), (-2.2, 0.1, -1.6)), right=((2.0, 1.7, 0.0), (2.2, 0.1, -1.6)),
                 pelvis=(0.0, 10.0, 0.0), centre=(0.0, 0.0)):
        self.feet = [left, right]
        self.pelvis = pelvis
        self.centre = centre
        self.rest = (1.7, 0.1)


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class FloorTest(unittest.TestCase):
    def view(self, angles=(10.0, 0.0, 0.0), distance=40.0, size=(640, 360), look_at=(0, 12, 0)):
        return mv_world.View(state(look_at, distance, angles), size)

    def test_the_lines_lie_where_their_world_lines_project(self):
        look = world_look()
        view = self.view()
        rgb, cover = mv_world.floor([view], look, view.size)
        bright = rgb.sum(axis=2) * cover
        for x in (-10.0, 5.0, 20.0):                      # lines x = k, read across a row near z = 2.5
            u, v, _ = view.project([(x, 0.0, 2.5), (x, 0.0, 2.6)])
            row = int(round(v[0]))
            at = u[0] + (row - v[0]) * (u[1] - u[0]) / (v[1] - v[0])         # where the line crosses that row
            cols = numpy.arange(int(at) - 6, int(at) + 7)
            prof = bright[row, cols] - numpy.percentile(bright[row, cols], 20)
            prof = numpy.clip(prof, 0, None)
            centroid = float((prof * cols).sum() / prof.sum())
            self.assertAlmostEqual(centroid, at, delta=0.2, msg=x)

    def test_the_floor_ends_at_its_edge_and_never_shows_above_the_horizon(self):
        look = world_look()
        view = self.view(angles=(0.0, 0.0, 0.0))
        rgb, cover = mv_world.floor([view], look, view.size)
        h = view.size[1]
        self.assertEqual(float(cover[: h // 2 + 1].max()), 0.0)           # the sky side, and the row at the horizon
        u, v, _ = view.project([(0.0, 0.0, 60.0)])                       # the far edge, in the middle
        edge = int(round(v[0]))
        self.assertEqual(float(cover[edge - 3, int(u[0])]), 0.0)
        self.assertEqual(float(cover[edge + 3, int(u[0])]), 1.0)
        self.assertEqual(float(cover[h - 1, int(u[0])]), 1.0)

    def test_the_floor_has_the_colours_of_the_old_floor(self):
        look = world_look()
        view = mv_world.View(state((0, 0, 0), 26.0, (25.0, 0.0, 0.0)), (640, 360))
        rgb, cover = mv_world.floor([view], look, view.size)
        # between the lines: the plane as v7 showed it (make_stage's blue-black through the fold of the 240 fps render)
        u, v, _ = view.project([(2.5, 0.0, 2.5)])
        plane = rgb[int(v[0]), int(u[0])]
        for got, want in zip(plane, mv_world.FLOOR_COLOURS["plane"]):
            self.assertAlmostEqual(float(got), want, delta=0.5)
        u, v, _ = view.project([(0.0, 0.0, 2.5)])                         # on the amber line x = 0, near the camera
        core = rgb[int(round(v[0])), int(round(u[0]))]
        self.assertGreater(core[0], 150)
        self.assertLess(core[2], 80)

    def test_a_planted_foot_darkens_the_floor_under_its_sole_and_a_lifted_one_less(self):
        look = world_look(shadow=1.0, pool=1.0, shadow_soft=0)               # the shadows of v8 and v9
        view = self.view(angles=(25.0, 0.0, 0.0), distance=30.0, look_at=(0, 0, 0))
        planted = FakeFigure()
        lifted = FakeFigure(right=((2.0, 4.7, 0.0), (2.2, 3.1, -1.6)))        # the right foot 3 units up
        rgb_p, _ = mv_world.floor([view], look, view.size, [planted])
        rgb_l, _ = mv_world.floor([view], look, view.size, [lifted])
        none = world_look(shadow=0.0, pool=1.0)
        rgb_n, _ = mv_world.floor([view], none, view.size, [planted])
        u, v, _ = view.project([(2.1, 0.0, -0.8)])                          # the middle of the right sole, on the floor
        row, col = int(v[0]), int(u[0])
        lum = lambda img: float(img[row - 1:row + 2, col - 1:col + 2].sum(axis=2).mean())
        self.assertLess(lum(rgb_p), 0.5 * lum(rgb_n))
        self.assertGreater(lum(rgb_l), lum(rgb_p) + 0.25 * (lum(rgb_n) - lum(rgb_p)))
        u2, v2, _ = view.project([(14.0, 0.0, 0.0)])                        # far from her: no shadow
        far = lambda img: float(img[int(v2[0]), int(u2[0])].sum())
        self.assertAlmostEqual(far(rgb_p), far(rgb_n), delta=0.5)

    def test_the_pool_of_light_follows_the_dancer(self):
        look = world_look(pool=1.0)
        view = self.view(angles=(25.0, 0.0, 0.0), distance=34.0, look_at=(0, 0, 0))
        here = mv_world.floor([view], look, view.size, [FakeFigure(centre=(0.0, 0.0))])[0]
        there = mv_world.floor([view], look, view.size, [FakeFigure(centre=(8.0, 0.0))])[0]
        dark = mv_world.floor([view], world_look(pool=0.0), view.size, [FakeFigure()])[0]
        u0, v0, _ = view.project([(2.5, 0.0, 2.5)])                         # between the lines
        u8, v8, _ = view.project([(7.5, 0.0, 2.5)])
        at = lambda img, u, v: float(img[int(v[0]), int(u[0])].sum())
        self.assertGreater(at(here, u0, v0), at(dark, u0, v0) + 20)
        self.assertGreater(at(there, u8, v8), at(there, u0, v0))
        self.assertGreater(at(here, u0, v0), at(here, u8, v8))

    # the floor raised to where the model's soles stand (stage.floor_y, make_stage --height; 0.111 on 2026-10-14), seen from
    # close and above: there the height moves the floor's points several pixels on the picture
    LIFT = 0.111

    def close_view(self):
        return mv_world.View(state((0, 1, 0), 6.0, (35.0, 0.0, 0.0)), (640, 360))

    def test_a_raised_floor_has_its_lines_at_its_height(self):
        view = self.close_view()
        rgb, cover = mv_world.floor([view], world_look(floor_y=self.LIFT), view.size)
        bright = rgb.sum(axis=2) * cover
        # lines z = k run across the picture: read down a column, between where the line's two edges project (the amber
        # line at z = 0 is twice as wide)
        for z, half in ((0.0, 0.12), (5.0, 0.06)):
            edges = lambda y: view.project([(1.0, y, z - half), (1.0, y, z + half)])
            u, v, _ = edges(self.LIFT)
            _, v0, _ = edges(0.0)
            middle, middle0 = float(v.mean()), float(v0.mean())
            self.assertGreater(abs(middle - middle0), 2.0)                  # the height shows on the picture
            col = int(round(u.mean()))
            rows = numpy.arange(int(v.min()) - 8, int(v.max()) + 9)
            plane = numpy.median(numpy.r_[bright[rows[:4], col], bright[rows[-4:], col]])
            prof = numpy.clip(bright[rows, col] - plane, 0, None)
            centroid = float((prof * rows).sum() / prof.sum())
            self.assertAlmostEqual(centroid, middle, delta=0.2, msg=z)

    def test_on_a_raised_floor_the_shadow_lies_under_the_sole(self):
        lift = self.LIFT
        view = self.close_view()
        figure = FakeFigure(left=((-30.0, 1.7 + lift, 30.0), (-30.0, 0.1 + lift, 30.0)),       # one foot far off
                            right=((2.5, 1.7 + lift, 2.5), (2.5, 0.1 + lift, 2.5 + 1e-6)),   # a sole as short as a point
                            pelvis=(40.0, 10.0, 40.0))                                        # her body's shade far off
        figure.rest = (1.7 + lift, 0.1 + lift)
        lit = mv_world.floor([view], world_look(floor_y=lift, shadow=0.0), view.size, [figure])[0].sum(axis=2)
        shaded = mv_world.floor([view], world_look(floor_y=lift, shadow=1.0, shadow_soft=0), view.size,
                                [figure])[0].sum(axis=2)
        dark = numpy.clip(lit - shaded, 0, None)
        u, v, _ = view.project([(2.5, lift, 2.5)])
        _, v0, _ = view.project([(2.5, 0.0, 2.5)])
        # the darkest point (the shade is round the sole's point on the floor), to a fraction of a pixel down the picture
        r0, c0 = int(v[0]) - 40, int(u[0]) - 40
        window = dark[r0:r0 + 81, c0:c0 + 81]
        r, c = numpy.unravel_index(int(numpy.argmax(window)), window.shape)
        a, b, d = window[r - 1, c], window[r, c], window[r + 1, c]
        peak = r0 + r + 0.5 * (a - d) / (a - 2 * b + d)
        self.assertGreater(abs(v[0] - v0[0]), 5.0)
        self.assertAlmostEqual(peak, v[0], delta=0.5)

    def test_the_floor_of_several_moments_is_their_average(self):
        look = world_look()
        a, b = self.view(angles=(10.0, -1.0, 0.0)), self.view(angles=(10.0, 1.0, 0.0))
        ra, ca = mv_world.floor([a], look, a.size)
        rb, cb = mv_world.floor([b], look, b.size)
        rab, cab = mv_world.floor([a, b], look, a.size)
        self.assertLess(float(numpy.abs(cab - (ca + cb) / 2).max()), 1e-9)
        both = (ra * ca[..., None] + rb * cb[..., None]) / 2
        self.assertLess(float(numpy.abs(rab * cab[..., None] - both).max()), 1e-6)


def rin_path():
    """Sour's Rin: MMD_CLI_RIN when set, else the model folder of MMD under the user's Desktop"""
    rel = os.path.join("MikuMikuDance_v932x64", "UserFile", "Model", "Sour式鏡音リンVer.2.01", "White.pmx")
    for path in (os.environ.get("MMD_CLI_RIN"), os.path.join(os.path.expanduser("~"), "Desktop", rel)):
        if path and os.path.isfile(path):
            return path
    return None


RIN = rin_path()


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class SoftShadowTest(unittest.TestCase):
    """the soft shadow of her body (stage.shadow_soft 1): capsules lit by a light whose brightness spreads as a Gaussian
    round its direction, and the light from all round"""
    DOWN = (0.0, -1.0, 0.0)

    def through(self, capsules, points, light=(-0.5, -1.0, 0.5), blur=3.0):
        """the shares of the key light and of the light from all round that reach the floor points (x, z)"""
        ell = mv_world.toward_light(light)
        P = numpy.array([(x, 0.0, z) for x, z in points], dtype=float)
        key, contact = numpy.ones(len(P)), numpy.ones(len(P))
        for a, b, r in capsules:
            k, c = mv_world.capsule_shade(P, a, b, r, ell, math.radians(blur))
            key *= 1.0 - k
            contact *= 1.0 - c
        return key, contact

    def test_a_ball_casts_its_shadow_away_from_the_light(self):
        # MMD's light shines to (-0.5, -1, 0.5): the shadow of a point 5 up lies 2.5 to -x and 2.5 to +z of it
        ball = [((0.0, 5.0, 0.0), (0.0, 5.0, 0.0), 1.0)]
        key, contact = self.through(ball, [(-2.5, 2.5), (0.0, 0.0), (2.5, -2.5)])
        self.assertLess(key[0], 0.1)
        self.assertGreater(key[1], 0.99)                 # right under it the slanting light gets through
        self.assertGreater(key[2], 0.999)                # and on the side of the light
        self.assertLess(contact[1], contact[2])          # but it hides a little of the sky from under it
        self.assertGreater(contact[1], 0.9)

    def test_the_edge_of_a_shadow_blurs_in_proportion_to_the_height_of_what_casts_it(self):
        # a long bar across x, the light straight down with a spread of 3 degrees: across z the light comes back from
        # 10 % to 90 % over 2.563 x 3 degrees x the bar's height (the integral of a Gaussian: contact hardening)
        widths = []
        for h in (2.0, 8.0):
            bar = [((-40.0, h, 0.0), (40.0, h, 0.0), 0.5)]
            zs = numpy.linspace(0.0, 4.0, 4001)
            key, _ = self.through(bar, [(0.0, z) for z in zs], light=self.DOWN, blur=3.0)
            width = zs[numpy.argmax(key >= 0.9)] - zs[numpy.argmax(key >= 0.1)]
            want = 2.563 * math.radians(3.0) * h
            self.assertAlmostEqual(width, want, delta=0.1 * want, msg=h)
            widths.append(width)
        self.assertAlmostEqual(widths[1] / widths[0], 4.0, delta=0.3)

    def test_with_no_spread_the_edge_is_sharp(self):
        bar = [((-40.0, 8.0, 0.0), (40.0, 8.0, 0.0), 0.5)]
        zs = numpy.linspace(0.0, 1.0, 1001)
        key, _ = self.through(bar, [(0.0, z) for z in zs], light=self.DOWN, blur=0.0)
        self.assertLess(zs[numpy.argmax(key >= 0.9)] - zs[numpy.argmax(key >= 0.1)], 0.01)

    def test_a_sole_on_the_floor_takes_all_the_light_under_it_and_less_the_higher_it_lifts(self):
        def under(lift):
            sole = [((-1.0, 0.42 + lift, 0.0), (1.0, 0.42 + lift, 0.0), 0.42)]
            return self.through(sole, [(0.0, 0.0), (0.0, 1.5)])
        key, contact = under(0.0)
        self.assertLess(key[0], 0.01)
        self.assertLess(contact[0], 0.01)
        self.assertGreater(contact[1], 0.9)              # 1.5 to its side: a little
        key, contact = under(1.0)
        self.assertGreater(contact[0], 0.9)              # a unit up: under 1/10 of the sky hidden
        self.assertGreater(key[0], 0.9)                  # and the slanting light gets under it

    def test_a_long_bar_shades_as_much_as_its_width_whatever_its_length_past_the_light(self):
        # the band model: lengthening a bar that already crosses the whole light changes nothing
        short = [((-3.0, 4.0, 0.0), (3.0, 4.0, 0.0), 0.3)]
        long = [((-30.0, 4.0, 0.0), (30.0, 4.0, 0.0), 0.3)]
        points = [(0.0, z) for z in (0.0, 0.2, 0.4)]
        for a, b in zip(self.through(short, points, light=self.DOWN), self.through(long, points, light=self.DOWN)):
            numpy.testing.assert_allclose(a, b, atol=1e-6)
        # past its end the light comes back: the end is a disc
        key, _ = self.through(short, [(3.0, 0.0), (3.8, 0.0), (5.0, 0.0)], light=self.DOWN)
        self.assertLess(key[0], key[1])
        self.assertLess(key[1], key[2])
        self.assertGreater(key[2], 0.999)

    def test_the_grid_lies_on_whole_cells_of_the_world_and_has_each_points_value(self):
        capsules = [((0.3, 4.0, 0.2), (1.1, 1.0, -0.4), 0.5)]
        grid = mv_world.soft_shadow_grid(capsules, (-0.5, -1.0, 0.5), 3.0)
        for origin in (grid.x0, grid.z0):
            self.assertAlmostEqual(origin / grid.cell, round(origin / grid.cell), places=6)
        moved = mv_world.soft_shadow_grid([((0.31, 4.0, 0.2), (1.11, 1.0, -0.4), 0.5)], (-0.5, -1.0, 0.5), 3.0)
        self.assertAlmostEqual(moved.x0 / grid.cell, round(moved.x0 / grid.cell), places=6)
        i, j = numpy.unravel_index(int(numpy.argmin(grid.key)), grid.key.shape)
        x, z = grid.x0 + j * grid.cell, grid.z0 + i * grid.cell
        want_key, want_contact = self.through(capsules, [(x, z)])
        got_key, got_contact = grid.at([x], [z])
        self.assertAlmostEqual(float(got_key[0]), float(want_key[0]), places=9)
        # the light from all round changes over the axis's height (1 here): worked out on a grid twice as coarse
        self.assertAlmostEqual(float(got_contact[0]), float(want_contact[0]), delta=0.005)
        self.assertLess(float(got_key[0]), 0.2)
        # off the grid all the light comes; along its border (nearly) all of it already, so it shows no edge
        k, c = grid.at([grid.x0 - 1.0], [grid.z0 - 1.0])
        self.assertEqual((float(k[0]), float(c[0])), (1.0, 1.0))
        for g in (grid.key, grid.contact):
            border = numpy.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
            self.assertGreater(float(border.min()), 0.999)

    def test_a_capsule_high_above_is_worked_out_coarser_and_still_gives_each_points_value(self):
        # a head 17 above the floor: its shadow is blurred over units, so it is worked out on a coarser grid and laid onto
        # the floor's grid; every point of the floor's grid stays within 0.005 of its own value
        head = [((0.0, 16.9, 0.0), (0.0, 17.7, 0.0), 1.55)]
        light = (-0.5, -1.0, 0.5)
        ell = mv_world.toward_light(light)
        low = mv_world._low(head[0][0], head[0][1], 1.55)
        self.assertGreater(mv_world._level(math.radians(5.0) * low / ell[1], mv_world.SHADOW_CELL), 0)
        grid = mv_world.soft_shadow_grid(head, light, 5.0)
        zs, xs = numpy.mgrid[0:grid.key.shape[0]:7, 0:grid.key.shape[1]:7]
        points = [(grid.x0 + j * grid.cell, grid.z0 + i * grid.cell) for i, j in zip(zs.ravel(), xs.ravel())]
        want, _ = self.through(head, points, light=light, blur=5.0)
        got = grid.key[zs.ravel(), xs.ravel()]
        self.assertLess(float(numpy.abs(got - want).max()), 0.005)
        self.assertLess(float(want.min()), 0.6)                          # a shadow is there to get right
        # a skirt-sized ball 9.7 up darkens the floor from all round over many units: also worked out coarser
        skirt = [((0.0, 9.7, 0.0), (0.0, 9.7, 0.0), 2.9)]
        grid = mv_world.soft_shadow_grid(skirt, light, 5.0)
        zs, xs = numpy.mgrid[0:grid.contact.shape[0]:7, 0:grid.contact.shape[1]:7]
        points = [(grid.x0 + j * grid.cell, grid.z0 + i * grid.cell) for i, j in zip(zs.ravel(), xs.ravel())]
        want_key, want_contact = self.through(skirt, points, light=light, blur=5.0)
        self.assertLess(float(numpy.abs(grid.contact[zs.ravel(), xs.ravel()] - want_contact).max()), 0.005)
        self.assertLess(float(numpy.abs(grid.key[zs.ravel(), xs.ravel()] - want_key).max()), 0.005)
        self.assertLess(float(want_contact.min()), 0.95)

    def test_a_floor_raised_takes_the_shadow_at_its_height(self):
        # a ball 3 above a floor raised by 1: its shadow is the one a ball 2 above the floor at 0 casts
        here = mv_world.soft_shadow_grid([((0.0, 3.0, 0.0), (0.0, 3.0, 0.0), 0.8)], self.DOWN, 3.0, floor_y=1.0)
        there = mv_world.soft_shadow_grid([((0.0, 2.0, 0.0), (0.0, 2.0, 0.0), 0.8)], self.DOWN, 3.0)
        xs = numpy.linspace(-2.0, 2.0, 41)
        for a, b in zip(here.at(xs, 0 * xs), there.at(xs, 0 * xs)):
            numpy.testing.assert_allclose(a, b, atol=1e-9)
        self.assertLess(float(here.at([0.0], [0.0])[0][0]), 0.1)

    def test_a_light_from_below_is_refused(self):
        with self.assertRaises(ValueError):
            mv_world.toward_light((0.0, 1.0, 0.0))

    def view(self):
        return mv_world.View(state((0, 0, 0), 30.0, (25.0, 0.0, 0.0)), (640, 360))

    def test_the_soft_shadow_darkens_the_lines_and_the_pool_as_well_as_the_plane(self):
        # a sole lying on the floor across the line x = 5 at z = 2.5: under it the line goes dark too (the shadows of v8
        # and v9 darkened the plane only)
        view = self.view()
        figure = FakeFigure(centre=(5.0, 2.5))
        figure.capsules = [((4.0, 0.42, 2.5), (6.0, 0.42, 2.5), 0.42)]
        lit = mv_world.floor([view], world_look(shadow=0.0, pool=1.0), view.size, [figure])[0]
        soft = mv_world.floor([view], world_look(shadow=1.0, pool=1.0), view.size, [figure])[0]
        u, v, _ = view.project([(5.0, 0.0, 2.5), (5.0, 0.0, 6.0)])
        on_line = lambda img: float(img[int(round(v[0])), int(round(u[0]))].sum())
        self.assertGreater(on_line(lit), 60)                                  # a line (and the pool) there
        self.assertLess(on_line(soft), 0.1 * on_line(lit))
        away = lambda img: float(img[int(round(v[1])), int(round(u[1]))].sum())
        self.assertAlmostEqual(away(soft), away(lit), delta=0.5)              # 3.5 behind it: untouched

    def test_the_soft_shadow_needs_her_body(self):
        view = self.view()
        with self.assertRaises(ValueError) as caught:
            mv_world.floor([view], world_look(shadow=1.0), view.size, [FakeFigure()])
        self.assertIn("shadow_soft", str(caught.exception))
        self.assertTrue(mv_world.needs_body(world_look(shadow=1.0)))
        self.assertFalse(mv_world.needs_body(world_look(shadow=1.0, shadow_soft=0)))
        self.assertFalse(mv_world.needs_body(world_look(shadow=0.0)))


@unittest.skipUnless(mv_world and RIN, "needs Pillow, numpy and Sour's Rin (MMD_CLI_RIN)")
class BodyTest(unittest.TestCase):
    """her body as capsules (mv_world.Body) on Sour's Rin"""

    def body(self, *keys):
        from mmd_cli.formats import pmx
        return mv_world.Body.from_file(RIN, pmx.load(RIN), bone_motion(*keys))

    def test_at_rest_the_capsules_fill_her_height_and_reach_and_the_soles_stand_on_the_floor(self):
        caps = self.body(bone_key("センター", 0), bone_key("センター", 4)).capsules(0)
        low = min(min(a[1], b[1]) - r for a, b, r in caps)
        top = max(max(a[1], b[1]) + r for a, b, r in caps)
        reach = max(max(abs(a[0]), abs(b[0])) + r for a, b, r in caps)
        self.assertAlmostEqual(low, 0.1, delta=0.03)          # the toes' height: her soles on the floor
        self.assertAlmostEqual(top, 20.55, delta=0.3)         # the top of the ribbon (the mesh's 20.55)
        self.assertAlmostEqual(reach, 6.05, delta=0.4)        # the finger tips with the arms out (the mesh's 6.06)
        self.assertEqual(len(caps), len(mv_world.BODY_PARTS) + 2 * (len(mv_world.LEG_PARTS) + 2))

    def test_moving_her_whole_moves_every_capsule_and_between_frames_in_a_straight_line(self):
        body = self.body(bone_key("全ての親", 0), bone_key("全ての親", 10, pos=(3.0, 0.0, -2.0)))
        at0, at10 = body.capsules(0), body.capsules(10)
        for (a0, b0, r0), (a1, b1, r1) in zip(at0, at10):
            numpy.testing.assert_allclose(a1 - a0, (3.0, 0.0, -2.0), atol=1e-6)
            numpy.testing.assert_allclose(b1 - b0, (3.0, 0.0, -2.0), atol=1e-6)
            self.assertEqual(r0, r1)
        at5, at6, part = body.capsules(5), body.capsules(6), body.capsules(5.25)
        for (a5, _, _), (a6, _, _), (ap, _, _) in zip(at5, at6, part):
            numpy.testing.assert_allclose(ap, 0.75 * a5 + 0.25 * a6, atol=1e-9)


def camera_file(folder, shots, step=1, name="camera.vmd"):
    """a camera motion with a key on every `step`-th frame (every frame by default, as the MV's cameras): shots are (first,
    last, Y angle at first, Y angle at last)"""
    keys = []
    for first, last, y0, y1 in shots:
        for frame in list(range(first, last, step)) + [last]:
            t = (frame - first) / float(max(1, last - first))
            values = {"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, y0 + (y1 - y0) * t, 0.0), "fov": 30,
                      "perspective": True}
            keys.append(motion_edit.camera_key_from_ui(values, frame=frame))
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(vmd.dumps(vmd.Motion.for_camera(cameras=keys)))
    return path


@unittest.skipUnless(mv_world, "needs Pillow and numpy")
class StageFramesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.camera = camera_file(self.folder, [(0, 59, -20.0, 20.0)])

    def test_the_camera_of_a_file_at_a_frame_is_the_one_mmd_reads(self):
        track = mv_world.camera_track(self.camera)
        view = mv_world.view_at(track, 30, SIZE)
        expect = fk.camera_position(fk.camera_at(fk.camera_keys(vmd.load(self.camera)), 30))
        self.assertLess(max(abs(a - b) for a, b in zip(view.eye, expect)), 1e-9)

    def test_between_keys_one_frame_apart_mmd_keeps_the_earlier_one(self):
        # measured on 240 fps renders (review of stage-world, R1 and R1b): MMD does not move the camera between two keys one
        # frame apart (the MV's cameras have a key on every frame), and follows the curve between keys further apart
        track = mv_world.camera_track(self.camera)
        here, later = mv_world.view_at(track, 30, SIZE), mv_world.view_at(track, 31, SIZE)
        for t in (30.125, 30.5, 30.875):
            self.assertLess(float(numpy.abs(mv_world.view_at(track, t, SIZE).forward - here.forward).max()), 1e-12, t)
        self.assertGreater(float(numpy.abs(later.forward - here.forward).max()), 1e-3)
        sparse = mv_world.camera_track(camera_file(self.folder, [(0, 60, -20.0, 20.0)], step=2, name="sparse.vmd"))
        a, b = mv_world.view_at(sparse, 30, SIZE), mv_world.view_at(sparse, 32, SIZE)
        mid = (a.forward + b.forward) / 2                                    # keys two frames apart: a straight line
        half = mv_world.view_at(sparse, 31, SIZE).forward
        self.assertLess(float(numpy.abs(half / numpy.linalg.norm(half) - mid / numpy.linalg.norm(mid)).max()), 1e-3)
        self.assertGreater(float(numpy.abs(half - a.forward).max()), 1e-3)

    def test_frames_are_numbered_by_the_frame_of_the_video_and_cover_the_excerpt(self):
        look = world_look()
        light_frames = mv_look.light_frame_count(look, 30)
        made = mv_world.write_stage(look, self.folder, SIZE, 30, mv_world.camera_track(self.camera), 12, 5, light_frames)
        names = sorted(n for n in os.listdir(os.path.join(self.folder, "stage")))
        self.assertEqual(names, ["stage_%05d.png" % n for n in range(12, 17)])
        self.assertEqual((made["first"], made["frames"]), (12, 5))
        self.assertEqual(made["pattern"], os.path.join(self.folder, "stage", "stage_%05d.png").replace("\\", "/"))
        with Image.open(made["pattern"] % 12) as im:
            self.assertEqual((im.size, im.mode), (SIZE, "RGB"))

    def test_the_backdrop_moves_from_frame_to_frame_as_the_camera_orbits(self):
        look = world_look(plate=FLAT, beams={"count": 0}, bokeh={"count": 0}, radius=0.0, floor=0)
        light_frames = mv_look.light_frame_count(look, 30)
        made = mv_world.write_stage(look, self.folder, SIZE, 30, mv_world.camera_track(self.camera), 20, 21, light_frames)
        first = numpy.asarray(Image.open(made["pattern"] % 20), dtype=numpy.float64)
        last = numpy.asarray(Image.open(made["pattern"] % 40), dtype=numpy.float64)
        shift = peak_column(last, (40, 80)) - peak_column(first, (40, 80))
        focal = 90.0 / math.tan(math.radians(15))
        turn = [math.radians(-20.0 + 40.0 * f / 59.0) for f in (20, 40)]
        self.assertAlmostEqual(shift, focal * (math.tan(turn[1]) - math.tan(turn[0])), delta=4)

    def test_writing_again_clears_the_frames_of_before_and_gives_the_same_bytes(self):
        look = world_look()
        track = mv_world.camera_track(self.camera)
        lf = mv_look.light_frame_count(look, 30)
        made = mv_world.write_stage(look, self.folder, SIZE, 30, track, 0, 6, lf)
        with open(made["pattern"] % 3, "rb") as f:
            before = f.read()
        made = mv_world.write_stage(look, self.folder, SIZE, 30, track, 2, 3, lf)
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, "stage"))), ["stage_%05d.png" % n for n in (2, 3, 4)])
        with open(made["pattern"] % 3, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_the_moments_of_a_frame_are_those_the_shutter_keeps(self):
        # mv_look --subframes 8 --shutter 0.5 averages subframes 0..3 of every 8: frame 30 of a 30 fps video shows the song
        # at frames 30, 30 1/8, 30 2/8 and 30 3/8; at 60 fps with 4 subframes, frame 61 shows 30.5 and 30.5 + 1/8
        self.assertEqual(mv_world.moments(30, 30, 8, 0.5), [30.0, 30.125, 30.25, 30.375])
        self.assertEqual(mv_world.moments(61, 60, 4, 0.5), [30.5, 30.625])
        self.assertEqual(mv_world.moments(30, 30), [30.0])

    def test_a_floor_that_moves_under_a_pixel_while_the_shutter_is_open_is_drawn_once_in_the_middle(self):
        # keys two frames apart: MMD moves the camera between them
        track = mv_world.camera_track(camera_file(self.folder, [(0, 60, -20.0, 20.0)], step=2, name="sparse.vmd"))
        times = mv_world.moments(30, 30, 8, 0.5)
        small, big = (160, 90), (1280, 720)          # the same 0.25 degrees of orbit: 0.6 px on the small picture, 4.8 on the big
        moves = [mv_world.floor_moves(mv_world.view_at(track, times[0], s), mv_world.view_at(track, times[-1], s), 60.0)
                 for s in (small, big)]
        self.assertLess(moves[0], mv_world.SHARP_ENOUGH)
        self.assertGreater(moves[1], mv_world.SHARP_ENOUGH)
        self.assertEqual(mv_world.floor_moments(track, times, small, 60.0), [30.1875])
        self.assertEqual(mv_world.floor_moments(track, times, big, 60.0), times)

    def test_a_camera_with_a_key_on_every_frame_gives_one_sharp_floor_at_the_frame(self):
        # the MV's cameras: MMD draws the 8 subframes with the frame's camera, so the floor under her feet is the frame's
        track = mv_world.camera_track(self.camera)
        times = mv_world.moments(30, 30, 8, 0.5)
        size = (1280, 720)
        self.assertEqual(mv_world.floor_moments(track, times, size, 60.0, 0.111), [30.1875])
        look = world_look(floor_y=0.111)
        drawn = mv_world.floor([mv_world.view_at(track, 30.1875, size)], look, size)
        at_frame = mv_world.floor([mv_world.view_at(track, 30, size)], look, size)
        self.assertEqual(drawn[0].tobytes(), at_frame[0].tobytes())
        self.assertEqual(drawn[1].tobytes(), at_frame[1].tobytes())

    def test_a_floor_drawn_at_several_moments_is_their_average_in_the_frame(self):
        look = world_look(radius=0.0)
        bare = world_look(radius=0.0, floor=0)
        track = mv_world.camera_track(camera_file(self.folder, [(0, 60, -20.0, 20.0)], step=2, name="sparse.vmd"))
        lf = mv_look.light_frame_count(look, 30)
        size = (1280, 720)
        times = mv_world.moments(30, 30, 8, 0.5)
        frame = numpy.asarray(mv_world.stage_image(look, size, track, 30, 30, lf, subframes=8, shutter=0.5), dtype=numpy.float64)
        back = numpy.asarray(mv_world.stage_image(bare, size, track, 30, 30, lf, subframes=8, shutter=0.5), dtype=numpy.float64)

        def framed(rgb, cover):
            # the floor over the stage behind it, with the share of it that shows through the floor
            return back * (1 - cover[..., None]) + cover[..., None] * (rgb + mv_world.FLOOR_SEE_THROUGH * back)
        blurred = framed(*mv_world.floor([mv_world.view_at(track, t, size) for t in times], look, size))
        sharp = framed(*mv_world.floor([mv_world.view_at(track, 30.1875, size)], look, size))
        self.assertLess(float(numpy.abs(frame - blurred).max()), 1.01)       # rounded to whole levels
        lines = numpy.abs(blurred - sharp).sum(axis=2) > 30                  # where the average differs from the middle moment
        self.assertGreater(int(lines.sum()), 100)

    def test_jobs_draw_the_same_frames_as_one_process(self):
        look = world_look()
        track = mv_world.camera_track(self.camera)
        lf = mv_look.light_frame_count(look, 30)
        alone = os.path.join(self.folder, "alone")
        jobs = os.path.join(self.folder, "jobs")
        made = mv_world.write_stage(look, alone, SIZE, 30, track, 10, 7, lf, subframes=8, shutter=0.5)
        split = mv_world.write_stage(look, jobs, SIZE, 30, track, 10, 7, lf, subframes=8, shutter=0.5, jobs=3,
                                     sources={"camera": self.camera})
        self.assertEqual((split["first"], split["frames"]), (made["first"], made["frames"]))
        for index in range(10, 17):
            with open(made["pattern"] % index, "rb") as f, open(split["pattern"] % index, "rb") as g:
                self.assertEqual(f.read(), g.read(), index)
        self.assertEqual(sorted(os.listdir(jobs)), ["stage"])                 # the job files and logs went
        with self.assertRaises(RuntimeError):                                  # a job that cannot read its camera
            mv_world.write_stage(look, jobs, SIZE, 30, track, 10, 4, lf, jobs=2,
                                 sources={"camera": os.path.join(self.folder, "missing.vmd")})

    def test_a_camera_file_without_camera_keys_is_refused(self):
        path = os.path.join(self.folder, "empty.vmd")
        with open(path, "wb") as f:
            f.write(vmd.dumps(vmd.Motion.for_camera(cameras=[])))
        with self.assertRaises(ValueError):
            mv_world.camera_track(path)

    def test_a_camera_that_rolls_is_orthographic_or_looks_over_the_top_is_refused_when_it_is_read(self):
        # the stage cannot be drawn for such a key (View refuses it): reading the camera looks at every key, so that a render
        # or a prepare stops before its first frame is drawn, and says at which frame
        for change in ({"rot": (0.0, 10.0, 5.0)}, {"perspective": False}, {"rot": (95.0, 0.0, 0.0)}):
            keys = []
            for frame in range(61):
                values = {"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, 10.0, 0.0), "fov": 30, "perspective": True}
                if frame == 45:
                    values.update(change)
                keys.append(motion_edit.camera_key_from_ui(values, frame=frame))
            path = os.path.join(self.folder, "odd.vmd")
            with open(path, "wb") as f:
                f.write(vmd.dumps(vmd.Motion.for_camera(cameras=keys)))
            with self.assertRaises(ValueError, msg=change) as caught:
                mv_world.camera_track(path)
            self.assertIn("45", str(caught.exception))

    def test_spans_draw_only_their_frames(self):
        # the chunks of a preview lie apart in the song (tools/mv_chunks.py --workers prepares their stage once): the frames
        # between them are not drawn.  Spans that overlap or touch are drawn once; jobs draw the same pictures
        look = world_look()
        track = mv_world.camera_track(self.camera)
        lf = mv_look.light_frame_count(look, 30)
        alone, jobs = os.path.join(self.folder, "alone"), os.path.join(self.folder, "jobs")
        spans = [(20, 2), (10, 3), (12, 4), (22, 1)]
        made = mv_world.write_stage(look, alone, SIZE, 30, track, None, None, lf, spans=spans)
        self.assertEqual(made["spans"], [[10, 6], [20, 3]])
        self.assertEqual((made["first"], made["frames"]), (10, 9))
        drawn = ["stage_%05d.png" % n for n in list(range(10, 16)) + [20, 21, 22]]
        self.assertEqual(sorted(os.listdir(os.path.join(alone, "stage"))), drawn)
        split = mv_world.write_stage(look, jobs, SIZE, 30, track, None, None, lf, jobs=4, sources={"camera": self.camera},
                                     spans=spans)
        self.assertEqual(split["spans"], made["spans"])
        self.assertEqual(sorted(os.listdir(os.path.join(jobs, "stage"))), drawn)
        for name in drawn:
            with open(os.path.join(alone, "stage", name), "rb") as f, open(os.path.join(jobs, "stage", name), "rb") as g:
                self.assertEqual(f.read(), g.read(), name)
        with self.assertRaises(ValueError):
            mv_world.write_stage(look, alone, SIZE, 30, track, None, None, lf, spans=[(10, 0)])


if __name__ == "__main__":
    unittest.main()
