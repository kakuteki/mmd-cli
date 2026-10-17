"""The body size in tools/mvi (base.leg_cm, base.size_scale, shared.Scaled): people's values were measured on one body,
FineDance's standard body (every sequence retargeted to SMPL-X's neutral body, legs 78.3 cm from the hip to the ankle,
the two sides' mean), while Sour's Rin's legs are about 71 cm.  A measure in cm, or one that counts against a threshold
in cm, then compares a smaller body with a larger one.  The size-aligned value measures her again with her body made as
large as people's (every position of the pack and of the rest, the timing kept).  So a body c times as large, dancing
the same dance c times as large, gets the same size-aligned values, while its raw values in cm scale with c."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import balance, base, feet, gravity, shared

F = 600


def rest_scaled(c):
    rest, ay, ty = MF.rin_rest()
    return {k: v * c for k, v in rest.items()}, ay * c, ty * c


def legs(left_hip_y=10.0, right_hip_y=10.0):
    """a rest with straight legs: the hips at the heights given, the knees at 5.5, the ankles at 1.0 (units)"""
    rest = {}
    for s, x, hy in (("左", 1.0, left_hip_y), ("右", -1.0, right_hip_y)):
        rest[s + "足"] = np.array([x, hy, 0.0])
        rest[s + "ひざ"] = np.array([x, 5.5, 0.0])
        rest[s + "足首"] = np.array([x, 1.0, 0.0])
    return rest


def single_support(t0=100, t1=420):
    """the right foot lifted 1 unit on t0..t1 (single support on the left), the body swaying sideways over the left foot,
    the centre sinking 0.3 units at each touchdown and the left foot sliding 0.5 units on 200..230"""
    def move(n, t, p):
        q = None
        if n in ("右足ＩＫ", "右つま先ＩＫ") and t0 <= t <= t1:
            q = p + np.array([0.0, 1.0, 0.0])
        if n in ("左足ＩＫ", "左つま先ＩＫ") and 200 <= t:
            q = (p if q is None else q) + np.array([0.5 * (min(t, 230) - 200) / 30.0, 0.0, 0.0])
        if n in ("センター", "グルーブ", "腰", "下半身"):
            k = 0.3 * (np.exp(-((t - t1 - 3) / 4.0) ** 2) + np.exp(-((t - t0 + 3) / 4.0) ** 2))
            bob = 0.2 * (1.0 - np.cos(2.0 * np.pi * t / 26.0))              # a bob down on every second beat
            q = p + np.array([0.35 * np.sin(2.0 * np.pi * t / 90.0), -k - bob, 0.0])
        return q
    return move


def shoes(c):
    z = np.full(F, 0.111 * c)
    return {"floor_y": np.array(0.111 * c), "low_left": z.copy(), "low_right": z.copy(), "reach_left": np.zeros(F),
            "reach_right": np.zeros(F)}


def measured(c, move, w=None):
    """the fake version of the synthetic body c times as large (pack and rest about the origin)"""
    names, pos, rot = MF.pack(F, move)
    pos = (pos.astype(np.float64) * c).astype(np.float32)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), wb=w, shoes=shoes(c), rest=rest_scaled(c))


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


def wb():
    rep = {"zmp": {"frames": 500, "inside_share": 0.2, "margin_cm_single": {"p50": -8.0}, "tilt_deg_per_min": 900.0,
                   "outside_runs": []},
           "support": {"frames": 560, "single": 300, "double": 200, "air": 60},
           "follow": {"head": {"slope": 0.8, "2-4Hz": 0.7}, "chest": {"slope": 0.9}, "arms": {"slope": 0.85}}}
    arr = {"margin": np.full(F, -0.05), "com": np.zeros((F, 3)), "zmp": np.zeros((F, 2)), "hulls": [np.zeros((0, 2))] * F,
           "floor_y": 0.111}
    return rep, arr


class LegTest(unittest.TestCase):
    def test_the_leg_is_hip_to_knee_and_knee_to_ankle_in_cm(self):
        self.assertAlmostEqual(base.leg_cm(legs()), 9.0 * base.UNIT_CM)

    def test_the_two_legs_are_averaged(self):
        # Sour's Rin's hips stand at 10.66 and 10.59: the legs differ, the mean is the body's
        self.assertAlmostEqual(base.leg_cm(legs(10.0, 9.8)), 0.5 * (9.0 + 8.8) * base.UNIT_CM)

    def test_a_missing_leg_bone_is_no_leg(self):
        rest = legs()
        del rest["右ひざ"]
        self.assertIsNone(base.leg_cm(rest))

    def test_peoples_leg_is_the_body_their_values_were_measured_on(self):
        body = base.human()["_about"]["body"]
        self.assertAlmostEqual(base.people_leg_cm(), body["thigh_cm"] + body["shank_cm"], places=6)
        self.assertIn("SMPL-X", body["what"])

    def test_peoples_leg_is_the_mean_of_their_two_legs(self):
        # SMPL-X's rest joints are not symmetric (the left leg 78.94 cm, the right 77.70): people's leg is the two
        # sides' mean, as leg_cm takes hers (review_adapt: the left alone made the scale 0.8 % larger)
        body = base.human()["_about"]["body"]
        self.assertGreater(body["legs_left_cm"] - body["legs_right_cm"], 1.0)
        self.assertAlmostEqual(base.people_leg_cm(), 0.5 * (body["legs_left_cm"] + body["legs_right_cm"]), delta=0.011)

    def test_the_scale_makes_her_legs_peoples(self):
        rest = legs()
        s = base.size_scale(rest)
        self.assertAlmostEqual(s * base.leg_cm(rest), base.people_leg_cm(), places=6)
        self.assertIsNone(base.size_scale({}))

    def test_rins_legs_are_shorter_than_peoples(self):
        rest, _, _ = MF.rin_rest()
        self.assertGreater(base.size_scale(rest), 1.05)


class ScaledTest(unittest.TestCase):
    """a body 0.8 times as large and one 1.25 times as large against Rin's own size"""

    @classmethod
    def setUpClass(cls):
        cls.m = {c: measured(c, single_support(), w=wb()) for c in (0.8, 1.0, 1.25)}
        cls.s = {c: m.scaled(base.size_scale(m.rest()[0])) for c, m in cls.m.items()}

    def test_the_scaled_engines_see_one_body_whatever_her_size(self):
        a = self.s[1.0].a05()["rows"]
        self.assertGreater(a["single_frames"], 100)
        self.assertGreater(a["slip_path_cm_per_min"], 0.0)
        for c in (0.8, 1.25):
            b = self.s[c].a05()["rows"]
            # (single_lat_median_cm and sink_mean are rounded to 0.01 cm by a05's table)
            for k in ("single_frames", "single_lat_median_cm", "slip3_per_min", "slip_path_cm_per_min", "sink_mean",
                      "hover_support_pct"):
                self.assertIsNotNone(a[k], k)
                self.assertAlmostEqual(b[k], a[k], delta=max(0.011, 1e-3 * abs(a[k])), msg="%s at %.2f" % (k, c))
            fa, fb = self.s[1.0].fq(), self.s[c].fq()
            self.assertEqual(fb["range"], self.m[c].fq()["range"])          # the version's own frames
            for k in ("beat_range_median_cm", "vy_abs_p95"):
                self.assertGreater(fa[k], 0.0)
                self.assertAlmostEqual(fb[k], fa[k], delta=1e-3 * max(1.0, abs(fa[k])), msg=k)

    def test_the_raw_lengths_scale_with_her_size(self):
        a = self.m[1.0].a05()["rows"]["slip_path_cm_per_min"]
        self.assertGreater(a, 0.0)
        for c in (0.8, 1.25):
            self.assertAlmostEqual(self.m[c].a05()["rows"]["slip_path_cm_per_min"], c * a, delta=1e-3 * a)

    def test_the_size_aligned_rows_of_the_parts_are_the_same(self):
        for part in (feet, balance, gravity):
            ra = rows_of(part.measure(self.s[1.0]))
            for c in (0.8, 1.25):
                rb = rows_of(part.measure(self.s[c]))
                for mid in base.SIZE_ALIGNED:
                    if mid not in ra or ra[mid]["value"] is None:
                        continue
                    self.assertAlmostEqual(rb[mid]["value"], ra[mid]["value"], delta=1e-3 * max(1.0, abs(ra[mid]["value"])),
                                           msg="%s at %.2f" % (mid, c))

    def test_the_other_engines_are_the_versions_own(self):
        s = self.s[0.8]
        self.assertIs(s.wb(), self.m[0.8].wb())
        self.assertIs(s.hb(), self.m[0.8].hb())
        self.assertEqual(s.shoes(), self.m[0.8].shoes())

    def test_a_scale_of_one_measures_the_same_as_the_version(self):
        m = self.m[1.0]
        one = m.scaled(1.0)
        a, b = m.a05()["rows"], one.a05()["rows"]
        for k, v in a.items():
            if isinstance(v, float) and np.isfinite(v):
                self.assertAlmostEqual(b[k], v, places=9, msg=k)

    def test_aligned_measures_are_lengths_not_gravity(self):
        # the measures tied to gravity (the fall's acceleration, the share falling slower than half of it) are the same
        # for every body and are never aligned; the upper body and the ZMP are not the legs' (another shape)
        for mid in ("gravity.centre_down_max", "gravity.air_acc_median", "gravity.air_slow_share", "skirt.floor_over122_frames",
                    "balance.zmp_inside_pct", "upper.head_acc_p99"):
            self.assertNotIn(mid, base.SIZE_ALIGNED)
        for mid in ("balance.com_lateral_cm", "gravity.landing_sink_cm", "feet.slide10_per_min", "gravity.hover_pct"):
            self.assertIn(mid, base.SIZE_ALIGNED)
        self.assertTrue(all(mid in base.human() for mid in base.SIZE_ALIGNED))


if __name__ == "__main__":
    unittest.main()
