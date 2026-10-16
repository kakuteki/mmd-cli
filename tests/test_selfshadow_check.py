"""tools/selfshadow_check.py: the probe models and cameras, and the measures on pictures whose answer is known."""
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

    def ramp_picture(self, spread, gap=0.0, least=0.03, part="ramp"):
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
        path = os.path.join(self.out, "%s_%g_%g.png" % (part, spread, gap))
        save(path, np.where(on, grey, 0.0), np.where(on, 255, 0).astype(np.uint8))
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


if __name__ == "__main__":
    unittest.main()
