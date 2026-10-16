"""tools/contact_check.py: the feet against the floor measured as MMD shows them (the shoes skinned by tools/sink_check.py on
MMD's IK, the centre of mass by tools/wb_dynamics.py), apart from the contact layer's own judges: feet on the floor are
counted as standing, a foot held still over it as held, both over it as a hover, a contact's slide by its slowest
touching point, a run with no foot down as air with its parabola, the pelvis falling fast on the floor past the bound, and
between two dances the places and times of the contacts."""
import contextlib
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli.formats import vmd
from tests.test_contact_layer import BENT, DATA, DOC, MODEL, RIG, dance
from tests.test_pmx_spine import load_tool

contact_check = load_tool("contact_check")
FPS, CM, G = 30.0, 8.0, 122.5


def check(m, before=None):
    return contact_check.check(RIG, DOC, MODEL, m, before)


class OneDanceTest(unittest.TestCase):
    def test_two_feet_standing_still(self):
        r = check(dance(30))["after"]
        self.assertEqual(r["support_1.2cm"]["two_pct"], 100.0)
        self.assertEqual(r["contact_4mm"]["two_pct"], 100.0)
        self.assertEqual(r["hover"]["pct"], 0.0)
        self.assertEqual(r["held"]["runs_per_min"], 0.0)
        self.assertEqual(r["slides"]["over_3cm_per_min"], 0.0)
        self.assertEqual(r["air"]["runs4"], 0)
        self.assertEqual(r["pelvis_floor"]["past_bound"], 0)

    def test_a_foot_held_still_over_the_floor_is_held_not_a_hover(self):
        # the right foot 2 cm up for frames 10-29, the left on the floor: held from frame 11 (a05 s11's still: the step
        # into the frame under 0.05 cm; frame 10 steps up 2 cm)
        F = 40
        r = check(dance(F, right=lambda t: ((0.0, 0.25 if 10 <= t <= 29 else 0.0, 0.0), None)))["after"]
        self.assertEqual(len(r["held"]["runs"]), 1)
        run = r["held"]["runs"][0]
        self.assertEqual(run["foot"], "right")
        self.assertEqual(run["s"], [round(11 / FPS, 2), round(30 / FPS, 2)])
        self.assertAlmostEqual(run["height_cm"], 2.0, delta=0.2)
        self.assertEqual(run["other_on"], 1.0)
        self.assertIsNotNone(run["com_outside_other_cm"])
        self.assertAlmostEqual(r["held"]["pct"], 100.0 * 19 / (2 * F), delta=0.01)
        self.assertEqual(r["hover"]["pct"], 0.0)
        self.assertAlmostEqual(r["support_1.2cm"]["one_pct"], 100.0 * 20 / F, delta=0.01)

    def test_both_feet_just_over_the_floor_is_a_hover(self):
        F = 30
        r = check(dance(F, left=lambda t: ((0.0, 0.25 if 10 <= t <= 19 else 0.0, 0.0), None),
                        right=lambda t: ((0.0, 0.25 if 10 <= t <= 19 else 0.0, 0.0), None)))["after"]
        self.assertAlmostEqual(r["hover"]["pct"], 100.0 * 10 / F, delta=0.01)
        self.assertEqual(len(r["hover"]["runs6_s"]), 1)
        self.assertEqual(r["air"]["runs_per_min"]["7-12"], round(1 / (F / FPS / 60.0), 2))

    def test_a_sliding_contact_is_measured_by_its_slowest_touching_point(self):
        # the left foot on the floor slides 0.05 units a frame for 12 frames (12 cm/s, 4.8 cm), the right lifted high:
        # single support
        F = 30
        m = dance(F, left=lambda t: ((0.0, 0.0, -0.05 * min(max(t - 5, 0), 12)), None),
                  right=lambda t: ((0.0, 1.5, 0.0), None))
        r = check(m)["after"]["slides"]
        minutes = F / FPS / 60.0
        self.assertEqual(r["over_3cm_per_min"], round(1 / minutes, 2))
        self.assertEqual(r["over_10cm_per_min"], 0.0)
        self.assertAlmostEqual(r["path_cm_per_min"] * minutes, 4.8, delta=0.3)
        self.assertAlmostEqual(r["single_stand_speed_cm_s"]["p90"], 12.0, delta=0.5)

    def test_air_with_the_body_falling_by_gravity(self):
        # the whole body (the feet too) on a parabola of -g from frame 9 to 18: the feet 4 cm and more up over 10-17
        F, a, b = 30, 10, 17

        def y(t):
            tt = (min(max(t, a - 1), b + 1) - (a - 1)) / FPS
            T = (b + 1 - (a - 1)) / FPS
            return 0.5 * G * tt * (T - tt)
        m = dance(F, centre=lambda t: (0.0, BENT + y(t), 0.0), left=lambda t: ((0.0, y(t), 0.0), None),
                  right=lambda t: ((0.0, y(t), 0.0), None))
        r = check(m)["after"]["air"]
        self.assertEqual(r["runs4"], 1)
        self.assertAlmostEqual(r["list"][0]["pelvis_acc"], -G, delta=1.0)
        self.assertAlmostEqual(r["list"][0]["com_acc"], -G, delta=1.0)
        self.assertEqual(r["pelvis_slower_than_half_g"], 0.0)

    def test_the_pelvis_falling_fast_on_the_floor_is_past_the_bound(self):
        # the feet on the floor, the pelvis dropped 4 cm in two frames
        F = 20
        m = dance(F, centre=lambda t: (0.0, BENT - (0.5 if t >= 10 else 0.0), 0.0))
        r = check(m)["after"]["pelvis_floor"]
        self.assertGreater(r["past_bound"], 0)
        self.assertGreater(r["max"], 400.0)


class CompareTest(unittest.TestCase):
    def test_a_moved_landing_and_the_same_timing(self):
        # the left foot lifted over frames 5-14 and down again at 15; after: it lands 2.5 cm further forward
        F = 30

        def foot(dz):
            return lambda t: ((0.0, 1.0 if 5 <= t <= 14 else 0.0, (dz if t >= 15 else 0.0)), None)
        before = dance(F, left=foot(0.0))
        after = dance(F, left=foot(-2.5 / CM))
        r = check(after, before)["change"]
        self.assertAlmostEqual(r["placements"]["max_cm"], 2.5, delta=0.05)
        self.assertEqual(r["placements"]["over_2cm"], 1)
        self.assertEqual(r["timing"]["start_moved"], 0)
        self.assertEqual(r["timing"]["end_moved"], 0)
        same = check(before, before)["change"]
        self.assertAlmostEqual(same["placements"]["max_cm"], 0.0, delta=1e-6)
        self.assertEqual(same["pelvis"]["frames_changed"], 0)

    def test_main_writes_the_report_and_the_arrays(self):
        d = tempfile.mkdtemp()
        try:
            src, model, rep, arr = (os.path.join(d, n) for n in ("in.vmd", "m.pmx", "r.json", "a.npz"))
            vmd.dump(dance(20, right=lambda t: ((0.0, 0.25 if 5 <= t <= 15 else 0.0, 0.0), None)), src)
            with open(model, "wb") as f:
                f.write(DATA)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(contact_check.main([src, model, "--report", rep, "--before", src, "--arrays", arr]), 0)
            with open(rep, encoding="ascii") as f:
                r = json.load(f)
            self.assertEqual(len(r["after"]["held"]["runs"]), 1)
            self.assertIn("change", r)
            with np.load(arr) as z:
                self.assertEqual(len(z["after_low_right"]), 20)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
