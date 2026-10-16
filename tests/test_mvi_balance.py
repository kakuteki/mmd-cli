"""tools/mvi/balance.py (重心とバランス): the ZMP rows and places from tools/wb_dynamics' report (set by the test), and
a05's and p24's single support on a synthetic body."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import balance, base, report

F = 600


def wb(inside=0.2, runs=(), single=300):
    rep = {"zmp": {"frames": 500, "inside_share": inside, "margin_cm_single": {"p50": -8.0}, "tilt_deg_per_min": 900.0,
                   "outside_runs": list(runs)},
           "support": {"frames": 560, "single": single, "double": 200, "air": 60},
           "follow": {"head": {"slope": 0.8, "2-4Hz": 0.7}, "chest": {"slope": 0.9}, "arms": {"slope": 0.85}}}
    arr = {"margin": np.full(F, -0.05), "com": np.zeros((F, 3)), "zmp": np.zeros((F, 2)), "hulls": [np.zeros((0, 2))] * F,
           "floor_y": 0.111}
    return rep, arr


def measured(move=None, w=None):
    names, pos, rot = MF.pack(F, move)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), wb=w or wb())


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class ZmpTest(unittest.TestCase):
    def test_the_share_inside_and_single_support_against_people(self):
        r = rows_of(balance.measure(measured()))
        self.assertAlmostEqual(r["balance.zmp_inside_pct"]["value"], 20.0)
        self.assertEqual(r["balance.zmp_inside_pct"]["judge"]["word"], "下へ外")
        self.assertAlmostEqual(r["balance.single_share_pct"]["value"], 100.0 * 300 / 560)
        self.assertEqual(r["balance.zmp_margin_single_cm"]["value"], -8.0)

    def test_a_stretch_outside_tilting_past_peoples_is_a_place(self):
        p99, scale = base.event_rule("balance.zmp_inside_pct")
        runs = [{"first": 100, "last": 110, "tilt_deg": p99 + 2 * scale, "depth_cm": 9.0, "support": "L"},
                {"first": 200, "last": 203, "tilt_deg": p99 - 1.0, "depth_cm": 3.0, "support": "R"}]
        res = balance.measure(measured(w=wb(runs=runs)))
        ev = [e for e in res["events"] if e["id"] == "balance.zmp_inside_pct"]
        self.assertEqual([(e["first"], e["last"]) for e in ev], [(100, 110)])
        self.assertAlmostEqual(ev[0]["severity"], 2.0, places=3)
        # the stretch tilts above its edge while the share inside goes down: listed when that share is 下へ外 (the review
        # of 10-17: v10's 78 stretches were never listed, the share being 下へ外 and the places' side +1)
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        self.assertEqual(rows_of(res)["balance.zmp_inside_pct"]["judge"]["word"], "下へ外")
        self.assertEqual([e["why"] for e in rep["events"] if e["id"] == "balance.zmp_inside_pct"], ["measure"])


class SingleSupportTest(unittest.TestCase):
    def test_the_rows_of_a05_and_p24(self):
        lift = np.array([0.0, 1.0, 0.0])
        move = lambda n, t, p: p + lift if n in ("右足ＩＫ", "右つま先ＩＫ") and 100 <= t <= 400 else None  # noqa: E731
        r = rows_of(balance.measure(measured(move)))
        for mid in ("balance.com_lateral_cm", "balance.moving_com_lateral_cm", "balance.moving_mos_ml_cm"):
            self.assertIsNotNone(r[mid]["value"], mid)
        self.assertEqual(r["balance.com_lateral_cm"]["frames"], 301)
        self.assertIsNotNone(r["balance.com_lateral_cm"]["ref"])


if __name__ == "__main__":
    unittest.main()
