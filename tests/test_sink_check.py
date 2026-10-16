"""tools/sink_check.py: a change that moves the whole figure (the hover sink of the foot layer) checked from what the
viewer sees, apart from the layer's own judges: the pelvis's downward acceleration against the skirt's bound, on the floor
and in the air; the change's own depth and how sharply it comes and goes; the shoes against the floor (under it, on it,
sliding along it, nothing holding the body); the knees' bend.  Checked on the leg rig of Sour's Rin with a shoe on each
foot (tests.test_foot_layer)."""
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_foot_layer import CAP, SOLE, UPPER, shoe_model_bytes
from tests.test_leg_ik import key
from tests.test_pmx_spine import load_tool

sink_check = load_tool("sink_check")

DATA = shoe_model_bytes()
RIG = sink_check.IK.LegRig.loads(DATA)
DOC = pmx_edit.loads(DATA)
FLOOR = 0.111                   # the synthetic shoes' soles at rest
BENT = -1.2                     # センター this far down: the knees bent, every goal in reach


def motion(*keys):
    return vmd.Motion(model_name="rin-legs", bones=list(keys))


def dance(F, centre=lambda t: 0.0, feet=None, extra=()):
    """F frames, センター at BENT + centre(t) (a key on every frame), both foot IKs at feet(side, t) (on the floor when
    not given), more keys after"""
    keys = [key("センター", t, position=(0.0, BENT + centre(t), 0.0)) for t in range(F)]
    if feet is not None:
        keys += [key(s + "足ＩＫ", t, position=feet(s, t)) for t in range(F) for s in ("左", "右")]
    return motion(*(keys + list(extra)))


def check(before, after, **kw):
    return sink_check.compare(RIG, DOC, before, after, **kw)


class ShoeTest(unittest.TestCase):
    def test_every_vertex_of_the_shoe_is_found_and_the_floor_is_its_lowest_at_rest(self):
        for s in ("左", "右"):
            pts, _w, _bones = sink_check.shoe_vertices(RIG, DOC, s)
            self.assertEqual(len(pts), len(SOLE) + len(UPPER) + 1)
            self.assertTrue(np.all(pts[:, 0] > 0.0) if s == "左" else np.all(pts[:, 0] < 0.0))
        self.assertAlmostEqual(sink_check.rest_floor(RIG, DOC), FLOOR, places=5)

    def test_the_lowest_point_follows_a_pointed_foot_onto_its_toe_cap(self):
        # pointed 45 degrees toes-down in the air: the toe cap's front edge, above the sole at rest, goes lowest
        h = math.radians(45.0) / 2.0
        q = (-math.sin(h), 0.0, 0.0, math.cos(h))
        m = motion(key("左足ＩＫ", 0, q, position=(0, 2.0, 0)), key("左足首", 0, q))
        f = sink_check.shoe_track(RIG, DOC, m, [0])["左"]
        self.assertLess(float(f["low"][0]), 2.0 + FLOOR)                        # under the lifted sole
        self.assertGreater(float(f["low"][0]), FLOOR + 0.5)                     # but well over the floor
        pts, _w, _b = sink_check.shoe_vertices(RIG, DOC, "左")
        self.assertLess(float(np.linalg.norm(pts[int(f["argmin"][0])] - np.array(CAP[:3]))), 1e-6)


class PelvisTest(unittest.TestCase):
    def test_the_heights_are_those_of_forward_kinematics(self):
        m = motion(*[key("センター", t, position=(0.1 * t, BENT + 0.05 * math.sin(t), 0.0)) for t in range(12)])
        r = check(m, m)
        pose = fk.Pose(pmx.loads(DATA), m, ["下半身", "センター"])
        for t in (0, 5, 11):
            w = pose.at(t)
            self.assertAlmostEqual(float(r["_arrays"]["before"]["下半身_y"][t]), w["下半身"][0][1], places=5)
            self.assertAlmostEqual(float(r["_arrays"]["before"]["センター_y"][t]), w["センター"][0][1], places=5)

    def test_a_still_figure_has_no_acceleration_and_nothing_past_the_bound(self):
        m = dance(20)
        r = check(m, m)
        for name in ("下半身", "センター"):
            self.assertEqual(r["pelvis"][name]["after"]["past_bound_floor"], 0)
            self.assertEqual(r["pelvis"][name]["new_past_bound"], [])
            self.assertLess(r["pelvis"][name]["after"]["max_floor"], 1e-6)
        self.assertEqual(r["change"]["stretches"], [])

    def test_a_quick_lowering_is_past_the_bound_and_a_slow_one_is_not(self):
        F = 40
        before = dance(F)
        quick = dance(F, lambda t: -0.25 if t >= 16 else 0.0)                    # 2 cm in a frame: 225 units/s^2
        r = check(before, quick)
        new = r["pelvis"]["下半身"]["new_past_bound"]
        self.assertEqual([row["frame"] for row in new], [15])
        self.assertAlmostEqual(new[0]["after"], 225.0, delta=1.0)
        self.assertGreater(r["pelvis"]["下半身"]["after"]["past_bound_floor"], 0)    # the feet stay on the floor
        slow = dance(F, lambda t: -0.25 * 0.5 * (1.0 - math.cos(math.pi * min(1.0, max(0.0, (t - 5) / 30.0)))))
        r2 = check(before, slow)
        self.assertEqual(r2["pelvis"]["下半身"]["new_past_bound"], [])
        st = r2["change"]["stretches"]
        self.assertEqual(len(st), 1)
        self.assertAlmostEqual(st[0]["deepest_cm"], 2.0, delta=0.05)              # 0.25 units of 8 cm
        self.assertLess(r2["change"]["acc_max_units_s2"], 5.0)
        self.assertGreater(r["change"]["acc_max_units_s2"], 200.0)

    def test_a_lower_bound_counts_more(self):
        F = 30
        before = dance(F)
        after = dance(F, lambda t: -0.1 if t >= 12 else 0.0)                     # 90 units/s^2 at frame 11
        self.assertEqual(check(before, after)["pelvis"]["下半身"]["new_past_bound"], [])
        self.assertEqual([row["frame"] for row in check(before, after, bound=80.0)["pelvis"]["下半身"]["new_past_bound"]], [11])

    def test_in_the_air_the_fall_is_counted_apart_from_the_floor(self):
        # both feet 3 cm up for 8 frames (no foot supports: the air) and the pelvis dropping fast inside them
        F = 30
        feet = lambda s, t: (0.0, 0.375 if 10 <= t < 18 else 0.0, 0.0)          # noqa: E731
        before = dance(F, feet=feet)
        after = dance(F, lambda t: -0.2 * min(4, max(0, t - 11)), feet=feet)      # 180 units/s^2 at frame 11
        r = check(before, after)
        p = r["pelvis"]["下半身"]["after"]
        self.assertGreater(p["past_bound_air"], 0)
        self.assertEqual(p["past_bound_floor"], 0)
        air = np.asarray(r["_arrays"]["after"]["air"])
        self.assertTrue(air[10:18].all())
        self.assertFalse(air[:10].any())
        self.assertFalse(air[18:].any())


class ShoeFloorTest(unittest.TestCase):
    def test_a_shoe_pushed_under_the_floor_is_counted_with_its_depth(self):
        F = 10
        before = dance(F)
        after = dance(F, feet=lambda s, t: (0.0, -0.125 if s == "左" and 3 <= t < 7 else 0.0, 0.0))
        r = check(before, after)
        pen = r["feet"]["左"]["after"]["under_floor"]
        self.assertEqual(pen["frames"], 4)
        self.assertAlmostEqual(pen["deepest_cm"], 1.0, delta=0.05)
        self.assertEqual(r["feet"]["左"]["before"]["under_floor"]["frames"], 0)
        self.assertEqual(r["feet"]["右"]["after"]["under_floor"]["frames"], 0)

    def test_a_shoe_sliding_on_the_floor_is_measured_at_its_speed(self):
        F = 16
        before = dance(F)
        after = dance(F, feet=lambda s, t: (0.0, 0.0, -0.05 * max(0, min(t, 12) - 2) if s == "左" else 0.0))
        r = check(before, after)
        a = r["feet"]["左"]["after"]["slide"]
        self.assertAlmostEqual(a["max_cm_s"], 12.0, delta=0.5)                   # 0.05 units x 8 cm x 30 fps
        self.assertEqual(a["frames_over_5cm_s"], 10)
        self.assertLess(r["feet"]["左"]["before"]["slide"]["max_cm_s"], 0.1)
        self.assertLess(r["feet"]["右"]["after"]["slide"]["max_cm_s"], 0.1)

    def test_a_shoe_turning_on_its_touching_point_does_not_slide(self):
        # on the toe cap (pitched 30 -> 40 degrees toes-down), the heel rising about the cap held on the floor: the touching
        # point stays, though the rest of the shoe moves
        ankle0 = np.array([1.1205, 1.7452, 0.37])
        cap = np.array(CAP[:3])
        place = np.array([cap[0], FLOOR, cap[2]])
        keys = [key("センター", t, position=(0.0, BENT, 0.0)) for t in range(11)]
        for t in range(11):
            h = math.radians(-(30.0 + t)) / 2.0
            q = (math.sin(h), 0.0, 0.0, math.cos(h))
            ankle = place - sink_check.IK.qrot(np.array(q), cap - ankle0)
            keys += [key("左足ＩＫ", t, q, position=tuple(ankle - ankle0)), key("左足首", t, q)]
        m = motion(*keys)
        r = check(m, m)
        f = r["feet"]["左"]["before"]
        self.assertEqual(f["on_floor"]["frames"], 11)
        self.assertLess(f["slide"]["max_cm_s"], 0.5)
        moved = sink_check.shoe_track(RIG, DOC, m, range(11))["左"]
        self.assertTrue(np.all(moved["touching"] == 1))                          # the cap alone

    def test_a_flat_shoe_turning_about_a_point_over_its_sole_slides_with_its_sole(self):
        # the left shoe flat on the floor, turned 3 degrees a frame about the vertical through the upper's vertex (not
        # touching; the bones' turns given directly): the sole's point nearest that axis, 0.373 units off it, moves 0.373 x 3
        # degrees a frame (4.7 cm/s), though the upper's vertex stays put
        F = 9
        rest = {n: np.array(RIG.bones[RIG.by_name["左" + n]].position, dtype=float) for n in ("足首", "足先EX")}
        up = np.array(UPPER[0][:3])
        sol = sink_check.IK.solve(RIG, dance(F), range(F))
        q = np.array([[0.0, math.sin(math.radians(3.0 * t) / 2.0), 0.0, math.cos(math.radians(3.0 * t) / 2.0)] for t in range(F)])
        ankle = up[None] - sink_check.IK.qrot(q, (up - rest["足首"])[None])
        sol["左"] = dict(sol["左"], ankle=ankle, q_foot=q, ex=ankle + sink_check.IK.qrot(q, (rest["足先EX"] - rest["足首"])[None]),
                        q_ex=q)
        f = sink_check.shoe_track(RIG, DOC, None, range(F), sol)["左"]
        self.assertLess(float(np.abs(f["low"] - FLOOR).max()), 1e-6)                # flat on the floor throughout
        near = min(math.hypot(x - up[0], z - up[2]) for x, _y, z, _w in SOLE)
        self.assertAlmostEqual(near, 0.373, delta=0.001)
        expect = near * math.radians(3.0)
        for t in range(F - 1):
            self.assertAlmostEqual(float(f["slide"][t]), expect, delta=0.002)

    def test_a_figure_held_by_nothing_is_counted(self):
        # both shoes 1.5 cm over the floor for 10 frames, the pelvis held: nothing holds the body (a05's 'hover support')
        F = 30
        before = dance(F, feet=lambda s, t: (0.0, 0.1875 if 10 <= t < 20 else 0.0, 0.0))
        after = dance(F)
        r = check(before, after)
        self.assertEqual(r["held_by_nothing"]["before"]["frames"], 10)
        self.assertEqual(r["held_by_nothing"]["before"]["runs_6_or_more"], 1)
        self.assertEqual(r["held_by_nothing"]["after"]["frames"], 0)
        self.assertEqual(r["feet"]["左"]["before"]["support"]["frames"], F)      # 1.5 cm is still a support (under 1.6)


class KneeTest(unittest.TestCase):
    def test_lowering_the_figure_on_its_feet_bends_both_knees(self):
        F = 20
        r = check(dance(F), dance(F, lambda t: -0.25 if 8 <= t < 12 else 0.0))   # 2 cm: about 6 degrees more bend
        for s in ("左", "右"):
            kn = r["knees"][s]
            self.assertGreater(kn["more_bent_max_deg"], 5.0)
            self.assertLess(kn["more_bent_max_deg"], 8.0)
            self.assertLess(kn["straighter_max_deg"], 1e-3)
            self.assertEqual(kn["frames_over_5_deg"], 4)

    def test_the_same_dance_changes_nothing(self):
        m = dance(15, extra=[key("左足ＩＫ", 5, position=(0, 0.5, 0.3))])
        r = check(m, m)
        for s in ("左", "右"):
            self.assertEqual(r["knees"][s]["frames_over_5_deg"], 0)
            self.assertLess(r["knees"][s]["more_bent_max_deg"], 1e-6)


class CliTest(unittest.TestCase):
    def test_main_writes_the_report_and_the_arrays(self):
        tmp = tempfile.mkdtemp()
        try:
            model = os.path.join(tmp, "m.pmx")
            with open(model, "wb") as f:
                f.write(DATA)
            a, b = os.path.join(tmp, "a.vmd"), os.path.join(tmp, "b.vmd")
            vmd.dump(dance(10), a)
            vmd.dump(dance(10, lambda t: -0.1 if 4 <= t < 7 else 0.0), b)
            rep, arr = os.path.join(tmp, "r.json"), os.path.join(tmp, "a.npz")
            self.assertEqual(sink_check.main([a, b, model, "--report", rep, "--arrays", arr]), 0)
            with open(rep, encoding="utf-8") as f:
                r = json.load(f)
            self.assertEqual(r["frames"], 10)
            self.assertIn("下半身", r["pelvis"])
            self.assertNotIn("_arrays", r)
            z = np.load(arr)
            self.assertEqual(z["after_lower_body_y"].shape, (10,))
            self.assertEqual(z["before_low_left"].shape, (10,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
