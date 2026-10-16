"""tools/mvi/feet.py (足): the slides of a05 on a synthetic body, and the shoes against the floor and MMD's IK from the
curves tools/sink_check.py and tools/leg_ik.py give (set by the test)."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import base, feet, report

F = 600
FLOOR = 0.111


def shoes(low_left=None, low_right=None, reach_left=None, reach_right=None):
    z = np.full(F, FLOOR)
    return {"floor_y": np.array(FLOOR), "low_left": z.copy() if low_left is None else low_left,
            "low_right": z.copy() if low_right is None else low_right,
            "reach_left": np.zeros(F) if reach_left is None else reach_left,
            "reach_right": np.zeros(F) if reach_right is None else reach_right}


def measured(move=None, sh=None, ref=None):
    names, pos, rot = MF.pack(F, move)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), shoes=sh or shoes(), ref_shoes=ref)


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class SlideTest(unittest.TestCase):
    def test_a_long_slide_on_the_floor_is_a_place_past_peoples_slides(self):
        def move(n, t, p):
            if n in ("左足ＩＫ", "左つま先ＩＫ"):
                return p + np.array([0.125 * (min(max(t, 200), 230) - 200), 0.0, 0.0])        # 30 cm over 30 frames
            return None
        res = feet.measure(measured(move))
        r = rows_of(res)
        self.assertAlmostEqual(r["feet.slide10_per_min"]["value"], 1 / (F / 1800.0))
        ev = [e for e in res["events"] if e["id"] == "feet.slide10_per_min"]
        self.assertEqual(len(ev), 1)
        self.assertAlmostEqual(ev[0]["value"], 30.0, delta=0.01)
        edge, scale = base.event_rule("feet.slide10_per_min")
        self.assertAlmostEqual(ev[0]["severity"], (30.0 - edge) / scale, places=3)

    def test_a_slide_within_peoples_slides_counts_but_is_no_place(self):
        def move(n, t, p):
            if n in ("左足ＩＫ", "左つま先ＩＫ"):
                return p + np.array([0.05 * (min(max(t, 200), 230) - 200), 0.0, 0.0])         # 12 cm
            return None
        res = feet.measure(measured(move))
        self.assertGreater(rows_of(res)["feet.slide10_per_min"]["value"], 0)
        self.assertEqual([e for e in res["events"] if e["id"] == "feet.slide10_per_min"], [])


class FloorTest(unittest.TestCase):
    def test_a_shoe_under_the_floor_breaks_the_rule(self):
        low = np.full(F, FLOOR)
        low[300:305] = FLOOR - 0.05                                          # 4 mm under
        res = feet.measure(measured(sh=shoes(low_left=low)))
        r = rows_of(res)["feet.under_floor_frames"]
        self.assertEqual(r["value"], 5)
        self.assertEqual(r["judge"]["word"], "上へ外")
        ev = [e for e in res["events"] if e["id"] == "feet.under_floor_frames"]
        self.assertEqual([(e["first"], e["last"]) for e in ev], [(300, 304)])
        self.assertAlmostEqual(ev[0]["value"], 0.4, places=5)

    def test_a_shoe_on_the_floor_is_not_under_it(self):
        r = rows_of(feet.measure(measured()))["feet.under_floor_frames"]
        self.assertEqual((r["value"], r["judge"]["word"]), (0, "中"))


class IkTest(unittest.TestCase):
    def test_a_new_miss_on_the_floor_against_the_dance(self):
        reach = np.zeros(F)
        reach[100:103] = 0.25                                                # 2 cm off the goal, on the floor
        reach[400:403] = 0.25
        ref_reach = np.zeros(F)
        ref_reach[400:403] = 0.25                                            # the dance missed there already
        low = np.full(F, FLOOR)
        res = feet.measure(measured(sh=shoes(low_left=low, reach_left=reach), ref=shoes(reach_left=ref_reach)))
        r = rows_of(res)
        self.assertEqual(r["feet.ik_miss_floor_frames"]["value"], 6)
        self.assertEqual(r["feet.ik_new_miss_frames"]["value"], 3)
        ev = [e for e in res["events"] if e["id"] == "feet.ik_new_miss_frames"]
        self.assertEqual([(e["first"], e["last"]) for e in ev], [(100, 102)])

    def test_a_miss_in_the_air_is_not_counted(self):
        reach = np.zeros(F)
        reach[100:103] = 0.25
        low = np.full(F, FLOOR)
        low[95:110] = FLOOR + 1.0                                            # the shoe 8 cm up
        r = rows_of(feet.measure(measured(sh=shoes(low_left=low, reach_left=reach), ref=shoes())))
        self.assertEqual(r["feet.ik_miss_floor_frames"]["value"], 0)

    def test_without_a_reference_the_new_misses_are_not_measured(self):
        r = rows_of(feet.measure(measured()))
        self.assertIsNone(r["feet.ik_new_miss_frames"]["value"])


class KneeTest(unittest.TestCase):
    def test_a_knee_bending_much_after_a_touchdown_is_a_place(self):
        # the right foot lands and the pelvis drops 40 cm in 0.2 s (the knee bends, a05's two-bone leg)
        def move(n, t, p):
            if n in ("右足ＩＫ", "右つま先ＩＫ") and 200 <= t <= 220:
                return p + np.array([0.0, 0.5, 0.0])
            if n == "下半身" and 221 <= t <= 300:
                return p + np.array([0.0, -5.0 * min(t - 221, 6) / 6.0, 0.0])
            return None
        res = feet.measure(measured(move))
        ev = [e for e in res["events"] if e["id"] == "feet.knee_gain_deg"]
        self.assertTrue(any(e["first"] == 221 for e in ev))
        edge, _ = base.event_rule("feet.knee_gain_deg")
        self.assertTrue(all(e["value"] > edge for e in ev))

    def test_straight_knees_on_the_floor_are_listed_when_their_share_is_above_peoples(self):
        # the pelvis 0.1 unit up from 200 to 260: both legs past their length, the knees 0 degrees on the floor
        def move(n, t, p):
            if n == "下半身" and 200 <= t <= 260:
                return p + np.array([0.0, 0.1, 0.0])
            return None
        res = feet.measure(measured(move))
        r = rows_of(res)["feet.knee_straight_pct"]
        self.assertEqual(r["judge"]["word"], "上へ外")
        ev = [e for e in res["events"] if e["id"] == "feet.knee_straight_pct"]
        self.assertTrue(ev and all(e["side"] == -1 and e.get("toward") == 1 for e in ev))
        self.assertTrue(any(e["first"] <= 200 and 260 <= e["last"] for e in ev))
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        listed = [e for e in rep["events"] if e["id"] == "feet.knee_straight_pct" and e["listed"]]
        self.assertTrue(any(e["first"] <= 200 and 260 <= e["last"] for e in listed))

    def test_rows_are_judged(self):
        rep = report.mark_listed({"measures": feet.measure(measured())["rows"], "events": []})
        ids = {r["id"] for r in rep["measures"]}
        for mid in ("feet.slide10_per_min", "feet.slide3_per_min", "feet.slide_path_cm_per_min", "feet.slide_fast_share",
                    "feet.under_floor_frames", "feet.knee_gain_deg", "feet.knee_straight_pct", "feet.ik_miss_floor_frames",
                    "feet.ik_new_miss_frames"):
            self.assertIn(mid, ids)


if __name__ == "__main__":
    unittest.main()
