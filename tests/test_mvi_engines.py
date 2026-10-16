"""The engines of tools/mvi (the earlier work's measures, copied as they are): hb (the analysts' a01 a02 a08 a09 a18 a20 as
the human baseline ran them), a05 (the weight: contacts, slides, touchdowns, hover support, single support), fq
(floaty's pelvis: the air and its parabola), vertical (balance-v3's jumps and dips against the dance).  Checked on a
synthetic body (tests.mvi_fixtures.pack) with moves of known size."""
import math
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import a05 as A05, fq as FQ, hb as HB, vertical as VT

F = 300


def at(name, f0, f1, offset):
    """a move that adds `offset` (units) to bone `name` on frames f0..f1"""
    def move(n, t, p):
        if n == name and f0 <= t <= f1:
            return p + np.asarray(offset(t) if callable(offset) else offset, dtype=np.float64)
        return None
    return move


def chain(*moves):
    def move(n, t, p):
        out = None
        for m in moves:
            q = m(n, t, p if out is None else out)
            if q is not None:
                out = q
        return out
    return move


class HbTest(unittest.TestCase):
    def test_the_dance_range_follows_the_upper_body(self):
        names, pos, rot = MF.pack(F)
        res, _ = HB.measure(names, pos, rot)
        a, b = res["range"]
        self.assertLess(a, 40)
        self.assertGreater(b, F - 40)

    def test_no_range_when_the_upper_body_stands_still(self):
        names, pos, rot = MF.pack(F, sway=0.0)
        res, _ = HB.measure(names, pos, rot)
        self.assertEqual(res, {"skipped": "no dance range"})

    def test_a_one_step_jump_of_the_centre_is_a_spike_at_that_step(self):
        jump = lambda n, t, p: p + np.array([0.1, 0.0, 0.0]) if n == "センター" and t > 150 else None   # noqa: E731
        names, pos, rot = MF.pack(F, jump)
        res, ev = HB.measure(names, pos, rot)
        self.assertEqual(res["a08"]["センター"]["spikes_up_dn"], [1, 0])
        steps = ev["a08"]["センター"]["spikes"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][0], 150)                                # the step from frame 150 to 151
        self.assertAlmostEqual(steps[0][1], 0.1 * 0.08 * 30.0, places=5)  # 0.24 m/s

    def test_the_centre_falling_with_a_constant_acceleration_reads_it(self):
        acc = 200.0                                                       # units/s^2

        def fall(n, t, p):
            if n == "グルーブ" and t >= 100:
                tt = min(t - 100, 30) / 30.0
                extra = (t - 130) / 30.0 if t > 130 else 0.0
                return p + np.array([0.0, -0.5 * acc * tt * tt - acc * 1.0 * extra, 0.0])
            return None
        names, pos, rot = MF.pack(F, fall)
        res, ev = HB.measure(names, pos, rot)
        self.assertAlmostEqual(res["a18"]["center_ay"]["min"], -acc, delta=2.0)
        self.assertGreater(res["a18"]["center_ay"]["down_gt_98u_pct"], 5.0)
        self.assertEqual(len(ev["a18"]["center_ay"]), res["range"][1] - res["range"][0])


class A05Test(unittest.TestCase):
    def run_a05(self, move):
        names, pos, rot = MF.pack(F, move)
        return A05.run(names, pos, rot, rest=MF.rin_rest())

    def test_the_rest_of_the_model_is_a05s(self):
        rest, ankle, toe = MF.rin_rest()
        self.assertAlmostEqual(ankle, 1.7452340126037598)
        self.assertAlmostEqual(toe, 0.10000000149011612)

    def test_both_feet_just_above_the_floor_is_hover_support(self):
        up = np.array([0.0, 0.25, 0.0])                                   # 2 cm
        out = self.run_a05(chain(*[at(s + n, 100, 109, up) for s in ("左", "右") for n in ("足ＩＫ", "つま先ＩＫ")]))
        hs = out["s11"]["hover_support"]
        self.assertEqual(hs["frames"], 10)
        self.assertEqual(hs["_runs"], [(100, 109)])
        self.assertEqual(hs["runs_>=6frames"], 1)
        self.assertAlmostEqual(out["rows"]["hover_support_pct"], 100.0 * 10 / F)

    def test_feet_high_in_the_air_are_not_hover_support(self):
        up = np.array([0.0, 1.0, 0.0])                                    # 8 cm
        out = self.run_a05(chain(*[at(s + n, 100, 109, up) for s in ("左", "右") for n in ("足ＩＫ", "つま先ＩＫ")]))
        self.assertEqual(out["s11"]["hover_support"]["frames"], 0)

    def test_a_foot_sliding_on_the_floor_is_a_slide(self):
        slide = lambda t: np.array([0.0625 * (t - 100), 0.0, 0.0])        # 0.5 cm a frame
        hold = lambda t: np.array([0.0625 * 30, 0.0, 0.0])                # noqa: E731
        out = self.run_a05(chain(at("左足ＩＫ", 100, 130, slide), at("左つま先ＩＫ", 100, 130, slide),
                                 at("左足ＩＫ", 131, F, hold), at("左つま先ＩＫ", 131, F, hold)))
        rows = out["_s04_rows"]["左"]
        longest = max(rows, key=lambda r: r["slip_path_cm"])
        self.assertAlmostEqual(longest["slip_path_cm"], 15.0, delta=0.01)
        self.assertEqual(out["s04"]["左"]["intervals_slip_path>10cm"], 1)
        self.assertAlmostEqual(out["rows"]["slips10_per_min"], 1.0 / (F / 1800.0))

    def test_the_pelvis_sinking_after_a_touchdown(self):
        lift = np.array([0.0, 0.5, 0.0])
        sink = lambda t: np.array([0.0, -0.375 * min(t - 121, 5) / 5.0, 0.0])   # 3 cm over 5 frames after the landing
        out = self.run_a05(chain(at("右足ＩＫ", 100, 120, lift), at("右つま先ＩＫ", 100, 120, lift), at("下半身", 121, 160, sink)))
        ev = out["_ev"]
        self.assertIn(121, list(ev["final_R_td"]))
        k = list(ev["final_R_td"]).index(121)
        self.assertAlmostEqual(ev["final_R_sink_cm"][k], -3.0, delta=0.01)

    def test_single_support_offsets_and_the_table_fields(self):
        lift = np.array([0.0, 1.0, 0.0])
        out = self.run_a05(chain(at("右足ＩＫ", 50, 250, lift), at("右つま先ＩＫ", 50, 250, lift)))
        ss = out["s15"]["single_support_com_lateral_medial_cm"]
        self.assertEqual(ss["frames"], 201)
        self.assertEqual(out["rows"]["single_frames"], 201)
        self.assertAlmostEqual(out["rows"]["single_pct"], round(100.0 * 201 / F, 2))


class FqTest(unittest.TestCase):
    def air(self, g):
        def move(n, t, p):
            if 100 <= t <= 111:
                if n in ("左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ"):
                    return p + np.array([0.0, 0.5, 0.0])
                if n == "下半身":
                    tt = (t - 99) / 30.0
                    T = 13 / 30.0
                    return p + np.array([0.0, 0.5 * g * tt * (T - tt), 0.0])
            return None
        names, pos, _ = MF.pack(F, move)
        p64 = pos.astype(np.float64)
        rng = FQ.dance_range_fq(p64)
        return FQ.measure(p64, *rng, events=True)

    def test_a_fall_with_gravity_is_not_floating(self):
        r = self.air(122.5)
        self.assertEqual(len(r["events"]["air"]), 1)
        self.assertAlmostEqual(r["events"]["air"][0]["acc"], -122.5, delta=0.2)
        self.assertEqual(r["air_frac_slower_half_g"], 0.0)

    def test_a_fall_slower_than_half_gravity_is_floating(self):
        r = self.air(40.0)
        self.assertAlmostEqual(r["events"]["air"][0]["acc"], -40.0, delta=0.2)
        self.assertEqual(r["air_frac_slower_half_g"], 1.0)


class VerticalTest(unittest.TestCase):
    def test_a_lowered_jump_top_and_a_weakened_dip_on_the_beat(self):
        n = 400
        y0 = np.full(n, 10.0)
        y = y0.copy()
        low = {s: np.zeros(n) for s in ("左", "右")}
        for s in low:
            low[s][100:110] = 0.5
        y0[100:110] += 1.0                                              # the dance jumps 8 cm
        y[100:110] += 1.0 - 0.375                                       # the version 3 cm lower
        beat = int(round((VT.BEAT0 + 20 * VT.PERIOD) * 30.0))
        y0[beat - 4:beat + 1] -= np.linspace(0, 0.5, 5)                 # a 4 cm dip on the beat
        y0[beat + 1:beat + 5] -= np.linspace(0.5, 0, 4)
        y[beat - 4:beat + 1] -= np.linspace(0, 0.1, 5)                  # the version 0.8 cm
        y[beat + 1:beat + 5] -= np.linspace(0.1, 0, 4)
        r = VT.compare((y0, low), (y, low))
        self.assertEqual(r["summary"]["jumps"]["n"], 1)
        self.assertEqual(r["summary"]["jumps"]["top_lowered_over_2cm"], 1)
        self.assertAlmostEqual(r["jumps"][0]["top_cm"], -3.0, places=5)
        self.assertEqual(r["summary"]["beat"]["drop_ratio_under_0.8"], 1)
        self.assertTrue(VT.on_beat(beat))


if __name__ == "__main__":
    unittest.main()
