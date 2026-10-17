"""tools/selfshadow_check.py: the probe models and cameras, the reference of a wide light, and the measures on pictures
whose answer is known."""
import importlib.util
import math
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = None

if np is not None:
    spec = importlib.util.spec_from_file_location("selfshadow_check", os.path.join(ROOT, "tools", "selfshadow_check.py"))
    ssc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ssc)
    mv_world = ssc._mv_world()
    from mmd_cli.formats import pmx

SIZE = (960, 540)


def floor_points(view, normal=(0.0, 1.0, 0.0)):
    """the point on the floor (the plane through the origin with this normal) of every pixel, by the rays of mv_world (not
    the projection the measures use): points, hit"""
    d = view.rays()
    n = np.asarray(normal, dtype=np.float64)
    t = -float(view.eye @ n) / (d @ n)
    hit = (t > 0) & np.isfinite(t)
    return view.eye[None, None, :] + t[..., None] * d, hit


def save(path, grey, alpha):
    rgba = np.zeros(grey.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = np.clip(np.round(grey * 255.0), 0, 255).astype(np.uint8)[..., None]
    rgba[..., 3] = alpha
    Image.fromarray(rgba, "RGBA").save(path)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.doc = ssc.probe(self.out, 10.0, SIZE)

    def test_the_models_read_back_as_pmx(self):
        for name, faces in (("ramp.pmx", 2 * 3), ("fan.pmx", 2 * 2 * len(ssc.FAN_ANGLES))):     # both windings
            model = pmx.load(os.path.join(self.out, name))
            self.assertEqual(model.counts["faces"], faces, name)
            self.assertEqual((model.counts["materials"], model.counts["bones"], model.counts["display_frames"]), (1, 1, 2))
            self.assertEqual(model.bones[0].name, "センター")

    def test_each_plate_is_turned_from_the_light_by_its_angle_and_faces_up(self):
        L = ssc.unit(ssc.LIGHT)
        for i, a in enumerate(ssc.FAN_ANGLES):
            centre, corners, n = ssc.plate_corners(i, a)
            self.assertAlmostEqual(float(n @ -L), math.cos(math.radians(a)), places=9)
            self.assertGreater(n[1], 0.0)
            # the corners lie on the plate's plane, a square of side 2 x half
            for c in corners:
                self.assertAlmostEqual(float((c - centre) @ n), 0.0, places=9)
            self.assertAlmostEqual(float(np.linalg.norm(corners[1] - corners[0])), 2 * ssc.PLATE_HALF, places=9)
        # nothing lies between a plate and the light: the next plate is across the light
        _, t, _ = ssc.frame_axes()
        self.assertAlmostEqual(float(t @ L), 0.0, places=12)

    def test_the_cameras_read_back_from_their_files_see_the_probe(self):
        for part, model in (("ramp", ssc.ramp_model(10.0)), ("fan", ssc.fan_model())):
            track = mv_world.camera_track(os.path.join(self.out, self.doc[part]["camera"]))
            view = mv_world.view_at(track, 0, SIZE)
            u, v, depth = view.project([p for p, _ in model[0]])
            self.assertTrue((depth > 0).all() and (u > 0).all() and (u < SIZE[0]).all() and (v > 0).all()
                            and (v < SIZE[1]).all(), part)
            # the same camera as the measures take it
            mine = ssc._view(self.doc, part, SIZE)
            np.testing.assert_allclose(mine.eye, view.eye, atol=1e-4)
            np.testing.assert_allclose(mine.forward, view.forward, atol=1e-6)
        # the ramp's camera looks from the side of the shadow: it sees the floor behind the wall's foot
        view = ssc._view(self.doc, "ramp", SIZE)
        _, _, l = ssc.frame_axes()
        self.assertGreater(float(view.forward @ -l), 0.5)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class ContactTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.doc = ssc.probe(self.out, 10.0, SIZE)

    def ramp_picture(self, spread, gap=0.0, least=0.03, part="ramp", wall=None):
        """the floor of the ramp's picture with a shadow whose edge is a Gaussian of spread x distance (floor units, at
        least `least`) and which starts `gap` past the wall's foot.  The distance and the edge are worked out here from
        the light and the wall: the top edge at u is (u - u0) H / (u1 - u0) up, its ray down the light meets the floor"""
        view = ssc._view(self.doc, part, SIZE)
        ramp = self.doc[part]
        t, wa, nf = ssc.floor_axes(ramp["tilt"])
        P, hit = floor_points(view, nf)
        u, w = P @ t, P @ wa
        on = hit & (u >= ramp["floor_u"][0]) & (u <= ramp["floor_u"][1]) & (w >= ramp["floor_w"][0]) & (w <= ramp["floor_w"][1])
        H, u0, u1 = ramp["height"], ramp["from"], ramp["to"]
        L = ssc.unit(ssc.LIGHT)
        top = np.clip((u - u0) * H / (u1 - u0), 0, None)
        along = -nf[1] / float(nf @ L)           # the light's length from the top edge to the floor per unit of height (n.t = 0)
        s = top * along
        kk = (H / (u1 - u0)) * (wa[1] + along * float(L @ wa))     # where it meets the floor: w = kk (u - u0)
        sigma = np.maximum(least, spread * s)
        signed = (w - kk * (u - u0)) / math.hypot(1.0, kk)
        grey = ssc._phi(signed / sigma)
        grey = np.where((w < gap) | (u < u0) | (u > u1), 1.0, grey)
        grey = np.where(on, grey, 0.0)
        if wall is not None:
            # the wall in front of the floor where the rays meet it first: the plane w = 0 under the top edge, of grey `wall`
            _, _, l = ssc.frame_axes()
            d = view.rays()
            tw = -float(view.eye @ l) / (d @ l)
            Q = view.eye[None, None, :] + tw[..., None] * d
            qu, qy = Q @ t, Q[..., 1]
            tf = ((P - view.eye[None, None, :]) * d).sum(axis=2) / (d * d).sum(axis=2)
            front = (tw > 0) & (qu >= u0) & (qu <= u1) & (qy >= 0) & (qy <= (qu - u0) * H / (u1 - u0)) & (~on | (tw < tf))
            grey = np.where(front, wall, grey)
            on = on | front
        path = os.path.join(self.out, "%s_%g_%g.png" % (part, spread, gap))
        save(path, grey, np.where(on, 255, 0).astype(np.uint8))
        return path

    def test_it_reads_the_spread_of_the_edge_and_the_gap_at_the_foot(self):
        got = ssc.contact(self.doc, self.ramp_picture(0.06, gap=0.15))
        self.assertTrue(got["placed"])
        rows = [r for r in got["rows"] if r["distance"] >= 1.0]
        self.assertGreater(len(rows), 10)
        for r in rows:
            self.assertAlmostEqual(r["sigma"], 0.06 * r["distance"], delta=0.06 * 0.06 * r["distance"] + 0.006, msg=r)
        self.assertAlmostEqual(got["sigma_per_distance"], 0.06, delta=0.004)
        self.assertAlmostEqual(got["lit_gap_median"], 0.15, delta=0.03)                  # about a pixel
        # the light's own spread on the floor: radians(5) x the stretch
        self.assertAlmostEqual(got["light_per_distance"], math.radians(5.0) * got["stretch"], places=3)
        self.assertGreater(got["stretch"], 1.0)

    def test_on_a_floor_that_faces_the_light_too(self):
        got = ssc.contact(self.doc, self.ramp_picture(0.06, gap=0.1, part="ramp_tilt"), part="ramp_tilt")
        self.assertTrue(got["placed"])
        self.assertAlmostEqual(got["tilt"], ssc.FACING, places=2)
        rows = [r for r in got["rows"] if r["distance"] >= 1.0]
        self.assertGreater(len(rows), 10)
        for r in rows:
            self.assertAlmostEqual(r["sigma"], 0.06 * r["distance"], delta=0.06 * 0.06 * r["distance"] + 0.006, msg=r)
        self.assertAlmostEqual(got["lit_gap_median"], 0.1, delta=0.03)
        # the floor faces the light: what goes across the light is not stretched on it (the edge is across the light too)
        _, _, nf = ssc.floor_axes(ssc.FACING)
        np.testing.assert_allclose(nf, -ssc.unit(ssc.LIGHT), atol=1e-9)

    def test_it_reads_how_dark_the_wall_shows_itself(self):
        # nothing shadows the wall: its grey is the acne of the effect (here drawn 0.8 everywhere)
        got = ssc.contact(self.doc, self.ramp_picture(0.06, wall=0.8))
        self.assertAlmostEqual(got["wall_mean"], 0.8, delta=0.01)
        self.assertIsNotNone(got["rows"])
        lit = ssc.contact(self.doc, self.ramp_picture(0.06, wall=1.0))
        self.assertAlmostEqual(lit["wall_mean"], 1.0, delta=0.01)

    def test_a_softer_edge_reads_softer(self):
        hard = ssc.contact(self.doc, self.ramp_picture(0.02))
        soft = ssc.contact(self.doc, self.ramp_picture(0.08))
        self.assertGreater(soft["sigma_per_distance"], 3.0 * hard["sigma_per_distance"])
        self.assertLess(hard["lit_gap_median"], 0.03)

    def test_a_picture_of_something_else_is_not_placed(self):
        path = os.path.join(self.out, "blank.png")
        save(path, np.ones((SIZE[1], SIZE[0])), np.full((SIZE[1], SIZE[0]), 255, dtype=np.uint8))
        self.assertFalse(ssc.contact(self.doc, path)["placed"])

    def test_the_edge_fit_finds_a_known_edge(self):
        tau = np.linspace(-1.0, 1.0, 161)
        c, s, rms = ssc.fit_edge(tau, ssc._phi((tau - 0.1) / 0.2))
        self.assertAlmostEqual(c, 0.1, delta=0.002)
        self.assertAlmostEqual(s, 0.2, delta=0.002)
        self.assertLess(rms, 1e-3)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class FanTest(unittest.TestCase):
    def test_a_plate_shadowing_itself_is_found_and_the_others_are_lit(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        doc = ssc.probe(out, 10.0, SIZE)
        view = ssc._view(doc, "fan", SIZE)
        d = view.rays()
        grey = np.zeros(d.shape[:2])
        alpha = np.zeros(d.shape[:2], dtype=np.uint8)
        best = np.full(d.shape[:2], np.inf)
        _, t, _ = ssc.frame_axes()
        for i, a in enumerate(ssc.FAN_ANGLES):
            centre, corners, n = ssc.plate_corners(i, a)
            a2 = ssc.unit(np.cross(n, t))
            s = ((centre - view.eye) @ n) / (d @ n)
            p = view.eye + s[..., None] * d
            pu, pv = (p - centre) @ t, (p - centre) @ a2
            on = (s > 0) & (np.abs(pu) <= ssc.PLATE_HALF) & (np.abs(pv) <= ssc.PLATE_HALF) & (s < best)
            best = np.where(on, s, best)
            value = np.where((i == 5) & (pv > 0), 0.3, 1.0)                # plate 5 dark over half of it
            grey = np.where(on, value, grey)
            alpha = np.where(on, 255, alpha).astype(np.uint8)
        path = os.path.join(out, "fan.png")
        save(path, grey, alpha)
        got = ssc.fan(doc, path)
        self.assertTrue(got["placed"])
        for i, plate in enumerate(got["plates"]):
            if i == 5:
                self.assertAlmostEqual(plate["darker_05"], 0.5, delta=0.05)
                self.assertAlmostEqual(plate["mean"], 0.65, delta=0.04)
            else:
                self.assertEqual(plate["darker_095"], 0.0, plate)
            self.assertAlmostEqual(plate["n_dot_light"], math.cos(math.radians(plate["angle"])), places=3)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class AcneTest(unittest.TestCase):
    def test_only_the_darkening_far_from_mmds_shadow_counts(self):
        h, w = 120, 200
        alpha = np.full((h, w), 255.0)
        sharp = np.ones((h, w))
        sharp[:, :50] = 0.0                                            # MMD's shadow
        soft = sharp.copy()
        x = np.arange(w)[None, :].repeat(h, axis=0)
        soft = np.where(x < 70, np.clip((x - 40) / 30.0, 0.0, 1.0), soft)    # its edge blurred over 30 px: near it
        soft[50:60, 170:180] = 0.7                                         # a stain far from it: acne
        rgb = lambda g: np.repeat((g * 255.0)[..., None], 3, axis=2)
        got = ssc.acne_of([((rgb(sharp), alpha), (rgb(soft), alpha))], far=40)
        lit = ssc.inner(alpha) & ~ssc.near(ssc.inner(alpha) & (sharp < 0.95), 40) & (sharp > 0.999)
        self.assertEqual(got["far_lit_px"], int(lit.sum()))
        self.assertAlmostEqual(got["darker_095"], 100.0 / lit.sum(), places=4)
        self.assertAlmostEqual(got["mean_taken"], 100 * 0.3 / lit.sum(), places=4)
        self.assertEqual(got["darker_08"], round(100.0 / lit.sum(), 5))
        # the blur alone (no stain) is no acne
        soft[50:60, 170:180] = 1.0
        self.assertEqual(ssc.acne_of([((rgb(sharp), alpha), (rgb(soft), alpha))], far=40)["darker_095"], 0.0)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class SeenTest(unittest.TestCase):
    def edge_frames(self, centres, h=40, w=160, sigma=6.0):
        lit = np.full((h, w, 3), 200.0)
        alpha = np.full((h, w), 255.0)
        x = np.arange(w)[None, :]
        out = []
        for c in centres:
            r = 0.4 + 0.6 * ssc._phi((x - c) / sigma)
            out.append(((lit * r[..., None].repeat(h, axis=0), alpha), (lit, alpha)))
        return out

    def test_a_shade_gliding_is_smooth_and_one_stepping_back_and_forth_is_rough(self):
        glide = ssc.seen_of(self.edge_frames([40 + 0.25 * i for i in range(64)]), sub=4, shutter=0.5)
        jitter = ssc.seen_of(self.edge_frames([40 + (2.0 if (i // 4) % 2 else -2.0) for i in range(64)]), sub=4, shutter=0.5)
        self.assertEqual(glide["at_video"]["maps"], 16)
        self.assertLess(glide["at_video"]["roughness"], 0.3)
        self.assertGreater(jitter["at_video"]["roughness"], 1.5)
        self.assertGreater(jitter["at_video"]["rms_change"], glide["at_video"]["rms_change"])
        self.assertAlmostEqual(glide["shade_p10"], 0.4, delta=0.02)          # the shade keeps 0.4 of the light

    def test_the_fold_averages_the_open_subframes_premultiplied(self):
        a, b = np.full((2, 2, 3), 100.0), np.full((2, 2, 3), 200.0)
        on, off = np.full((2, 2), 255.0), np.zeros((2, 2))
        got = list(ssc.fold([(a, on), (b, off), (b, on), (b, on)], 4, 0.5))       # the first 2 of 4 are open
        self.assertEqual(len(got), 1)
        np.testing.assert_allclose(got[0][1], 127.5)
        np.testing.assert_allclose(got[0][0], 100.0)                       # the transparent subframe adds no colour


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class JitterTest(unittest.TestCase):
    """the reference of a wide light that does not go through the effect's sums: MMD's own hard test drawn under many
    directions of the light and averaged (review of softshadow-mme2)"""

    def axes(self):
        L = ssc.unit(ssc.LIGHT)
        a = ssc.unit(np.cross(L, [0.0, 1.0, 0.0]))
        return L, a, np.cross(L, a)

    def test_the_directions_spread_as_a_light_of_the_blur_round_it(self):
        L, a, b = self.axes()
        dirs = ssc.light_jitter(64, 5.0)
        self.assertEqual(len(dirs), 64)
        angles = []
        for d in dirs:
            d = np.asarray(d)
            self.assertAlmostEqual(float(np.abs(d).max()), 1.0, places=9)          # MMD's light boxes: -1 to 1
            u = ssc.unit(d)
            angles.append((math.atan2(float(u @ a), float(u @ L)), math.atan2(float(u @ b), float(u @ L))))
        angles = np.degrees(np.array(angles))
        for k in (0, 1):                     # a standard deviation of 5 degrees on each axis, round the light itself
            self.assertAlmostEqual(float(np.sqrt((angles[:, k] ** 2).mean())), 5.0, delta=0.2)
            self.assertLess(abs(float(angles[:, k].mean())), 0.3)
        self.assertEqual(len({tuple(np.round(d, 6)) for d in dirs}), 64)
        np.testing.assert_allclose(ssc.light_jitter(1, 5.0)[0], ssc.LIGHT)
        self.assertEqual(ssc.light_jitter(64, 5.0), dirs)                           # the same each time

    def test_a_hard_edge_averaged_over_them_is_the_wide_lights_edge(self):
        # a straight edge 4 units up the light from a plane across it: under each direction its hard shadow falls
        # 4 x tan(the angle) aside; the mean is a Gaussian edge of radians(5) x 4
        L, a, _ = self.axes()
        x = np.linspace(-2.0, 2.0, 801)
        mean = np.zeros_like(x)
        dirs = ssc.light_jitter(64, 5.0)
        for d in dirs:
            u = ssc.unit(d)
            mean += x > 4.0 * float(u @ a) / float(u @ L)
        c, s, _ = ssc.fit_edge(x, mean / len(dirs))
        self.assertAlmostEqual(s, math.radians(5.0) * 4.0, delta=0.04 * math.radians(5.0) * 4.0)
        self.assertAlmostEqual(c, 0.0, delta=0.02)

    def test_the_reference_is_the_mean_of_the_pictures(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        h, w = 20, 30
        g1, g2 = np.zeros((h, w)), np.ones((h, w))
        a1, a2 = np.full((h, w), 255, dtype=np.uint8), np.full((h, w), 255, dtype=np.uint8)
        a2[0, 0] = 0
        save(os.path.join(out, "1.png"), g1, a1)
        save(os.path.join(out, "2.png"), g2, a2)
        grey, alpha = ssc.truth([os.path.join(out, "1.png"), os.path.join(out, "2.png")])
        np.testing.assert_allclose(grey, 0.5)
        self.assertEqual(alpha[0, 0], 0)                                # the least alpha: a pixel not always body
        self.assertEqual(alpha[1, 1], 255)
        ssc.save_truth(os.path.join(out, "t.npz"), grey, alpha, 2)
        g, a = ssc.load_truth(os.path.join(out, "t.npz"))
        np.testing.assert_allclose(g, grey, atol=1e-6)
        np.testing.assert_array_equal(a, alpha)


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class AgainstTest(unittest.TestCase):
    H, W = 120, 240

    def edge(self, sigma, centre=100.0):
        x = np.arange(self.W)[None, :].repeat(self.H, axis=0).astype(np.float64)
        return ssc._phi((x - centre) / sigma)

    def alpha(self):
        return np.full((self.H, self.W), 255.0)

    def test_the_same_shadow_has_no_error(self):
        t = self.edge(6.0)
        got = ssc.against(t, self.alpha(), t.copy(), self.alpha())
        self.assertEqual(got["mae"], 0.0)
        self.assertEqual((got["leak"], got["dark"]), (0.0, 0.0))
        self.assertAlmostEqual(got["mass_ratio"], 1.0, places=9)
        self.assertEqual(got["edge_px_soft"], got["edge_px_truth"])
        self.assertEqual(got["rough"], 0.0)
        self.assertEqual((got["tiles_leak"], got["tiles_dark"]), ([], []))

    def test_a_leak_in_the_shadow_and_a_stain_on_the_lit_are_found_where_they_are(self):
        t = self.edge(6.0)
        s = t.copy()
        s[40:60, 20:44] = 0.8                                  # in the shadow (x under 82): light let through
        s[72:96, 168:192] = 0.5                                # on the lit side: a stain (one tile of 24)
        got = ssc.against(t, self.alpha(), s, self.alpha(), tile=24)
        n = got["px"]
        self.assertEqual(n, (self.H - 2) * (self.W - 2))       # the inner pixels
        self.assertAlmostEqual(got["leak"], 20 * 24 / float(n), places=6)
        self.assertAlmostEqual(got["dark"], 24 * 24 / float(n), places=6)
        self.assertLess(got["mass_ratio"], 1.0)                # more light let through than taken
        x0, y0, x1, y1 = got["tiles_leak"][0]["box"]
        self.assertTrue(x0 < 44 and x1 > 20 and y0 < 60 and y1 > 40, got["tiles_leak"][0])
        self.assertEqual(got["tiles_dark"][0]["box"], [168, 72, 192, 96])
        self.assertGreater(got["umbra_soft_over_05"], 0.0)
        self.assertGreater(got["lit_soft_under_095"], 0.0)

    def test_a_wider_edge_reads_wider(self):
        got = ssc.against(self.edge(6.0), self.alpha(), self.edge(12.0), self.alpha())
        # a Gaussian edge: 1 / its steepest slope is sqrt(2 pi) sigma
        self.assertAlmostEqual(got["edge_px_truth"], math.sqrt(2.0 * math.pi) * 6.0, delta=0.6)
        self.assertAlmostEqual(got["edge_px_soft"] / got["edge_px_truth"], 2.0, delta=0.1)
        self.assertEqual(got["leak"], 0.0)

    def test_with_a_toon_picture_only_the_side_facing_the_light_counts(self):
        t = self.edge(6.0)
        s = t.copy()
        s[72:96, 180:204] = 0.5
        toon = np.ones((self.H, self.W))
        toon[:, 160:] = 0.4                                    # turned from the light: its own shade covers the stain
        got = ssc.against(t, self.alpha(), s, self.alpha(), toon=toon)
        self.assertEqual(got["dark"], 0.0)
        self.assertLess(got["px"], (self.H - 2) * (self.W - 2))

    def test_a_penumbra_cut_short_and_steps_in_it_are_read(self):
        # the soft edge stops 0.9 standard deviations out (lit past it, as a search that finds nothing there leaves it)
        # and has a bright line through it: neither is in the reference
        t = self.edge(6.0)
        x = np.arange(self.W)[None, :].repeat(self.H, axis=0)
        s = np.where(x > 100 + 0.9 * 6.0, 1.0, t)
        s[:, 92] = np.minimum(1.0, s[:, 92] + 0.2)
        got = ssc.against(t, self.alpha(), s, self.alpha())
        ti, xi = t[1:-1, 1:-1], x[1:-1, 1:-1]
        pen = (ti > 0.05) & (ti < 0.95)
        self.assertEqual(got["penumbra_px"], int(pen.sum()))
        tail = (ti > 0.05) & (ti < 0.9)
        self.assertAlmostEqual(got["tail_cut"], (tail & (xi > 105.4)).sum() / float(tail.sum()), places=6)
        # the steps: where the soft one jumps to a neighbour 0.08 more than the reference does, in its penumbra (the
        # cut at 105 to 106 and the line at 91 to 93), and nowhere in the reference itself
        steps = got["steps"] * pen.sum()
        self.assertAlmostEqual(steps, 5 * (self.H - 2), delta=1.0)
        clean = ssc.against(t, self.alpha(), t.copy(), self.alpha())
        self.assertEqual((clean["tail_cut"], clean["steps"]), (0.0, 0.0))
        # ripples: a line brighter (or darker) than both its neighbours across the edge is one; the cut is a step, not a
        # ripple, and a narrower edge that keeps going one way has none
        self.assertAlmostEqual(got["ripples"] * pen.sum(), 1 * (self.H - 2), delta=1.0)
        self.assertEqual(clean["ripples"], 0.0)
        narrow = ssc.against(t, self.alpha(), self.edge(2.0), self.alpha())
        self.assertEqual(narrow["ripples"], 0.0)
        self.assertGreater(narrow["steps"], 0.0)                 # a narrower edge is steeper than the reference

    def test_speckle_reads_rough_and_a_box_keeps_to_its_part(self):
        t = self.edge(6.0)
        s = t.copy()
        yy, xx = np.mgrid[0:self.H, 0:self.W]
        s = np.clip(s + np.where((xx > 85) & (xx < 115), 0.2 * ((xx + yy) % 2 * 2 - 1), 0.0), 0.0, 1.0)
        got = ssc.against(t, self.alpha(), s, self.alpha())
        self.assertGreater(got["rough"], 0.04)
        part = ssc.against(t, self.alpha(), s, self.alpha(), box=(150, 0, 240, 120))
        self.assertEqual(part["rough"], 0.0)
        self.assertEqual(part["px"], (self.H - 2) * (90 - 2))


@unittest.skipUnless(np is not None, "needs numpy and Pillow")
class TogglesTest(unittest.TestCase):
    def frames(self, greys):
        alpha = np.full(greys[0].shape, 255.0)
        return [(np.repeat((g * 255.0)[..., None], 3, axis=2), alpha) for g in greys]

    def test_a_shadow_sliding_over_jumps_once_and_a_blinking_patch_jumps_back(self):
        h, w = 40, 120
        x = np.arange(w)[None, :].repeat(h, axis=0)
        slide = [np.where(x < 30 + i, 0.0, 1.0) for i in range(32)]         # a hard edge, a pixel each frame
        got = ssc.toggles_of(self.frames(slide), sub=4, shutter=0.5)
        self.assertGreater(got["at_subframes"]["jump_share"], 0.0)
        self.assertEqual(got["at_subframes"]["reversal_share"], 0.0)
        blink = []
        for i in range(32):
            g = np.ones((h, w))
            g[10:20, 80:90] = 0.2 if i % 2 else 0.9                         # a patch flickering each frame
            blink.append(g)
        got = ssc.toggles_of(self.frames(blink), sub=4, shutter=0.5, tile=10)
        inner = (h - 2) * (w - 2)
        self.assertAlmostEqual(got["at_subframes"]["reversal_share"], 100.0 / inner, places=6)
        self.assertEqual(got["at_subframes"]["tiles"][0]["box"], [80, 10, 90, 20])
        # folded (the first 2 of every 4 averaged) the patch is the same in every video frame: no flicker left
        self.assertEqual(got["at_video"]["reversal_share"], 0.0)
        self.assertEqual(got["at_video"]["frames"], 8)


if __name__ == "__main__":
    unittest.main()
