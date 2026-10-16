"""tools/mvi/upper.py (上体): the follow of the head and the chest on the hips (tools/wb_dynamics' report, set by the
test) and the head's stops (a08, a18) and its quick motion against the pelvis (tools/upper_body_check) on a synthetic
body."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from tests.test_mvi_balance import wb
from mvi import base, report, upper

F = 600
HEAD = ("首", "頭", "両目", "左目", "右目")


def sharp_stop(f0, f1, step=0.4):
    """the head moves sideways `step` units a frame (0.96 m/s for 0.4; past a08's 0.6 m/s with the sway against it) from
    f0 to f1 and stops dead"""
    def move(n, t, p):
        if n in HEAD and t >= f0:
            return p + np.array([step * (min(t, f1) - f0), 0.0, 0.0])
        return None
    return move


def measured(move=None):
    names, pos, rot = MF.pack(F, move, sway=0.25)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), wb=wb())


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class FollowTest(unittest.TestCase):
    def test_the_follow_rows_from_the_balance_report(self):
        r = rows_of(upper.measure(measured()))
        self.assertEqual(r["upper.head_follow"]["value"], 0.8)
        self.assertEqual(r["upper.head_follow"]["judge"]["word"], "上へ外")
        self.assertEqual(r["upper.chest_follow"]["value"], 0.9)
        self.assertEqual(r["upper.head_follow_2_4hz"]["value"], 0.7)


class CarriedTest(unittest.TestCase):
    def test_the_head_riding_on_the_hips_for_seconds_is_a_place(self):
        # the hips sway 2.4 cm at 2 Hz all along; from 300 to 599 the whole upper body sways with them (carried), else it
        # stays (the review of 10-17: the upper body held still on the hips for 10 s in v10 gave no place at all)
        F_ = 900

        def move(n, t, p):
            if n == "下半身" or (n in MF.UPPER and 300 <= t < 600):
                return p + np.array([0.3 * np.sin(2.0 * np.pi * 2.0 * t / 30.0), 0.0, 0.0])
            return None
        names, pos, rot = MF.pack(F_, move, sway=0.0)
        res = upper.measure(MF.FakeMeasured(MF.FakeVersion(names, pos, rot), wb=wb()))
        ev = [e for e in res["events"] if e["id"] == "upper.local_follow_carried"]
        self.assertEqual(len(ev), 1, ev)
        self.assertTrue(280 <= ev[0]["first"] <= 315 and 585 <= ev[0]["last"] <= 620, ev[0])
        edge, scale = base.event_rule("upper.local_follow_carried")
        self.assertGreater(ev[0]["value"], edge)
        self.assertEqual(rows_of(res)["upper.local_follow_carried"]["judge"]["word"], "上へ外")
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        self.assertEqual([e["why"] for e in rep["events"] if e["id"] == "upper.local_follow_carried"], ["measure"])

    def test_the_windows_are_upper_body_checks(self):
        # the windows give upper_body_check.local_follow's share carried (the people's check of the review: 62 of 62 equal)
        F_ = 900

        def move(n, t, p):
            if n == "下半身" or (n in MF.UPPER and 300 <= t < 600):
                return p + np.array([0.3 * np.sin(2.0 * np.pi * 2.0 * t / 30.0), 0.0, 0.0])
            return None
        names, pos, rot = MF.pack(F_, move, sway=0.0)
        ub = base.tool("upper_body_check")
        parts = ub.from_pack(names, pos, rot)
        rng = (20, 880)
        st, sl, wt = upper.local_windows(ub.eyes(parts), parts["下半身"][0], rng)
        theirs = ub.local_follow(ub.eyes(parts), parts["下半身"][0], rng)
        self.assertEqual(len(st), theirs["windows"])
        self.assertAlmostEqual(round(float(wt[sl > upper.CARRIED].sum() / wt.sum()), 4), theirs["share_carried"], places=6)


class StopTest(unittest.TestCase):
    def test_a_dead_stop_of_the_head_is_sharper_than_peoples_and_a_place(self):
        res = upper.measure(measured(sharp_stop(300, 315)))
        ev = [e for e in res["events"] if e["id"] == "upper.head_stop_ms"]
        self.assertTrue(ev)
        edge, _ = base.event_rule("upper.head_stop_ms")
        stop = [e for e in ev if 300 <= e["first"] <= 316]
        self.assertTrue(stop)
        self.assertLess(stop[0]["value"], edge)
        self.assertEqual(stop[0]["side"], -1)

    def test_the_rows_are_there_and_judged(self):
        r = rows_of(upper.measure(measured(sharp_stop(300, 315))))
        for mid in ("upper.head_stop_ms", "upper.head_stops_per_min", "upper.head_sudden_stops_per_min",
                    "upper.upper_sudden_stops_per_min", "upper.head_acc_p99", "upper.head_pelvis_xcorr_peak",
                    "upper.local_follow_p50", "upper.local_follow_carried"):
            self.assertIn(mid, r)
            self.assertIsNotNone(r[mid]["ref"], mid)
        self.assertIsNotNone(r["upper.head_stop_ms"]["value"])


if __name__ == "__main__":
    unittest.main()
