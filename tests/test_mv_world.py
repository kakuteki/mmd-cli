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

    def test_the_picture_keeps_its_darker_corners(self):
        # the plate's corners were darker than its middle; in the world they stay a property of the picture
        look = world_look(radius=0.0)
        img = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0, (0.0, 30.0, 0.0)), (640, 360)), look, 1)
        flat = mv_look.merge_look({"stage": {"world": 1, "radius": 0.0}, "plate": {"vignette": 0.0}})
        plain = mv_world.backdrop(mv_world.View(state((0, 12, 0), 40.0, (0.0, 30.0, 0.0)), (640, 360)), flat, 1)
        self.assertLess(float(img[:20, :20].mean()), 0.75 * float(plain[:20, :20].mean()))
        self.assertAlmostEqual(float(img[175:185, 315:325].mean()), float(plain[175:185, 315:325].mean()), delta=1.0)


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
        look = world_look(shadow=1.0, pool=1.0)
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

    def test_the_floor_of_several_moments_is_their_average(self):
        look = world_look()
        a, b = self.view(angles=(10.0, -1.0, 0.0)), self.view(angles=(10.0, 1.0, 0.0))
        ra, ca = mv_world.floor([a], look, a.size)
        rb, cb = mv_world.floor([b], look, b.size)
        rab, cab = mv_world.floor([a, b], look, a.size)
        self.assertLess(float(numpy.abs(cab - (ca + cb) / 2).max()), 1e-9)
        both = (ra * ca[..., None] + rb * cb[..., None]) / 2
        self.assertLess(float(numpy.abs(rab * cab[..., None] - both).max()), 1e-6)


def camera_file(folder, shots):
    """a camera motion with a key on every frame: shots are (first, last, Y angle at first, Y angle at last)"""
    keys = []
    for first, last, y0, y1 in shots:
        for frame in range(first, last + 1):
            t = (frame - first) / float(max(1, last - first))
            values = {"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, y0 + (y1 - y0) * t, 0.0), "fov": 30,
                      "perspective": True}
            keys.append(motion_edit.camera_key_from_ui(values, frame=frame))
    path = os.path.join(folder, "camera.vmd")
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
        half = mv_world.view_at(track, 30.5, SIZE)                          # between two keys: a straight line
        later = mv_world.view_at(track, 31, SIZE)
        mid = [(a + b) / 2 for a, b in zip(view.forward, later.forward)]
        self.assertLess(max(abs(a - b) for a, b in zip(half.forward, mid)), 1e-3)

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
        track = mv_world.camera_track(self.camera)
        times = mv_world.moments(30, 30, 8, 0.5)
        small, big = (160, 90), (1280, 720)          # the same 0.25 degrees of orbit: 0.6 px on the small picture, 4.8 on the big
        moves = [mv_world.floor_moves(mv_world.view_at(track, times[0], s), mv_world.view_at(track, times[-1], s), 60.0)
                 for s in (small, big)]
        self.assertLess(moves[0], mv_world.SHARP_ENOUGH)
        self.assertGreater(moves[1], mv_world.SHARP_ENOUGH)
        self.assertEqual(mv_world.floor_moments(track, times, small, 60.0), [30.1875])
        self.assertEqual(mv_world.floor_moments(track, times, big, 60.0), times)

    def test_a_floor_drawn_at_several_moments_is_their_average_in_the_frame(self):
        look = world_look(radius=0.0)
        bare = world_look(radius=0.0, floor=0)
        track = mv_world.camera_track(self.camera)
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


if __name__ == "__main__":
    unittest.main()
