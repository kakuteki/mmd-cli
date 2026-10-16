"""tools/mvi/gravity.py (重力感): the measures and the places, on a synthetic body (tests.mvi_fixtures) whose engines run
for real (a05, fq, hb) and whose comparison with the dance (vertical) is set by the test."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import base, gravity, report

F = 600


def hover(f0, f1, cm=2.0):
    up = np.array([0.0, cm / 8.0, 0.0])

    def move(n, t, p):
        if f0 <= t <= f1 and n in ("左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ"):
            return p + up
        return None
    return move


def measured(move=None, vertical=None):
    names, pos, rot = MF.pack(F, move)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), vertical=vertical)


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class HoverTest(unittest.TestCase):
    def test_a_long_hover_is_a_place_and_the_rate_is_judged_against_people(self):
        res = gravity.measure(measured(hover(200, 219)))
        r = rows_of(res)
        self.assertAlmostEqual(r["gravity.hover_pct"]["value"], 100.0 * 20 / F)
        self.assertEqual(r["gravity.hover_runs6_per_min"]["value"], 1 / (F / 1800.0))
        self.assertEqual(r["gravity.hover_runs6_per_min"]["judge"]["word"], "上へ外")
        ev = [e for e in res["events"] if e["id"] == "gravity.hover_runs6_per_min"]
        self.assertEqual([(e["first"], e["last"], e["value"]) for e in ev], [(200, 219, 20.0)])
        edge, scale = base.event_rule("gravity.hover_runs6_per_min")
        self.assertAlmostEqual(ev[0]["severity"], (20 - edge) / scale, places=3)

    def test_a_short_hover_within_peoples_places_is_not_a_place(self):
        res = gravity.measure(measured(hover(200, 203)))
        self.assertEqual([e for e in res["events"] if e["id"] == "gravity.hover_runs6_per_min"], [])


class AirTest(unittest.TestCase):
    def air(self, g):
        def move(n, t, p):
            if 300 <= t <= 311:
                if n in ("左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ"):
                    return p + np.array([0.0, 0.5, 0.0])
                if n == "下半身":
                    tt = (t - 299) / 30.0
                    return p + np.array([0.0, 0.5 * g * tt * (13 / 30.0 - tt), 0.0])
            return None
        return gravity.measure(measured(move))

    def test_an_air_phase_slower_than_half_gravity_is_a_place(self):
        res = self.air(30.0)
        ev = [e for e in res["events"] if e["id"] == "gravity.air_slow_share"]
        self.assertEqual(len(ev), 1)
        self.assertAlmostEqual(ev[0]["value"], -30.0, delta=0.3)
        self.assertEqual(rows_of(res)["gravity.air_slow_share"]["value"], 1.0)

    def test_an_air_phase_falling_with_gravity_is_not(self):
        res = self.air(122.5)
        self.assertEqual([e for e in res["events"] if e["id"] == "gravity.air_slow_share"], [])
        self.assertEqual(rows_of(res)["gravity.air_slow_share"]["value"], 0.0)


class CentreTest(unittest.TestCase):
    def test_a_centre_falling_faster_than_peoples_falls_is_a_place(self):
        acc = 250.0

        def move(n, t, p):
            if n == "グルーブ" and 300 <= t <= 320:
                tt = (t - 300) / 30.0
                return p + np.array([0.0, -0.5 * acc * tt * tt, 0.0])
            if n == "グルーブ" and t > 320:
                return p + np.array([0.0, -0.5 * acc * (20 / 30.0) ** 2, 0.0])
            return None
        res = gravity.measure(measured(move))
        r = rows_of(res)
        self.assertLess(r["gravity.centre_down_max"]["value"], -240.0)
        self.assertEqual(r["gravity.centre_down_max"]["judge"]["word"], "下へ外")
        ev = [e for e in res["events"] if e["id"] == "gravity.centre_down_gt98_pct"]
        self.assertEqual(len(ev), 1)
        self.assertTrue(300 <= ev[0]["first"] <= ev[0]["last"] <= 320)
        self.assertEqual(ev[0]["side"], -1)


class DanceTest(unittest.TestCase):
    def test_without_a_reference_the_dances_jumps_are_not_measured(self):
        r = rows_of(gravity.measure(measured()))
        self.assertIsNone(r["gravity.jump_apex_lowered"]["value"])
        self.assertIsNone(r["gravity.jump_apex_lowered"]["judge"])
        self.assertIn("reference", r["gravity.jump_apex_lowered"]["from"])

    def test_a_lowered_jump_and_a_weakened_beat_dip_are_places_of_the_rule(self):
        vt = {"summary": {"jumps": {"n": 2, "top_lowered_over_2cm": 1, "top_lowered_over_5cm": 0},
                          "beat": {"n": 3, "drop_ratio_under_0.8": 1, "drop_ratio_under_0.9": 1}},
              "jumps": [{"first": 100, "last": 108, "top_cm": -3.0}, {"first": 200, "last": 206, "top_cm": -0.5}],
              "dips": [{"f": 300, "beat": True, "ref": {"drop_cm": 4.0}, "ver": {"drop_cm": 1.0}},
                       {"f": 330, "beat": True, "ref": {"drop_cm": 4.0}, "ver": {"drop_cm": 3.9}},
                       {"f": 360, "beat": False, "ref": {"drop_cm": 4.0}, "ver": {"drop_cm": 0.5}}]}
        res = gravity.measure(measured(vertical=vt))
        r = rows_of(res)
        self.assertEqual(r["gravity.jump_apex_lowered"]["value"], 1)
        self.assertEqual(r["gravity.jump_apex_lowered"]["judge"]["word"], "上へ外")
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        listed = [(e["id"], e["first"]) for e in rep["events"] if e["listed"]]
        self.assertIn(("gravity.jump_apex_lowered", 100), listed)
        self.assertNotIn(("gravity.jump_apex_lowered", 200), listed)
        self.assertIn(("gravity.beat_dips_weak", 300), listed)
        self.assertNotIn(("gravity.beat_dips_weak", 360), [(e["id"], e["first"]) for e in res["events"]])


class LandingTest(unittest.TestCase):
    def test_a_deep_sink_after_a_touchdown_is_a_place_past_peoples_landings(self):
        lift = np.array([0.0, 0.5, 0.0])

        def move(n, t, p):
            if n in ("右足ＩＫ", "右つま先ＩＫ") and 200 <= t <= 220:
                return p + lift
            if n == "下半身" and 221 <= t <= 260:
                return p + np.array([0.0, -1.25 * min(t - 221, 5) / 5.0, 0.0])          # 10 cm
            return None
        res = gravity.measure(measured(move))
        ev = [e for e in res["events"] if e["id"] == "gravity.landing_sink_cm"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["first"], 221)
        self.assertAlmostEqual(ev[0]["value"], -10.0, delta=0.01)
        self.assertEqual(ev[0]["side"], -1)


if __name__ == "__main__":
    unittest.main()
