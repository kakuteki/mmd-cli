"""tools/mvi/spikes.py (突起): a08's one-frame spikes per minute against people, and as places only the spikes bigger
than people's own (their pooled spikes' 90 % point)."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import base, report, spikes

F = 600


def jump(frame, units):
    """センター jumps sideways by `units` between frame and frame + 1 (one step of speed units * 2.4 m/s)"""
    return lambda n, t, p: p + np.array([units, 0.0, 0.0]) if n == "センター" and t > frame else None   # noqa: E731


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class SpikeTest(unittest.TestCase):
    def measure(self, move):
        names, pos, rot = MF.pack(F, move)
        return spikes.measure(MF.FakeMeasured(MF.FakeVersion(names, pos, rot)))

    def test_a_big_spike_is_a_place(self):
        res = self.measure(jump(300, 0.3))                                   # 0.72 m/s
        r = rows_of(res)
        self.assertEqual(r["spikes.centre_per_min"]["up_dn"], [1, 0])
        ev = [e for e in res["events"] if e["id"] == "spikes.centre_per_min"]
        self.assertEqual([(e["first"], e["last"]) for e in ev], [(300, 301)])
        self.assertAlmostEqual(ev[0]["value"], 0.72, places=5)
        edge, scale = base.event_rule("spikes.centre_per_min")
        self.assertAlmostEqual(ev[0]["severity"], (0.72 - edge) / scale, places=3)

    def test_a_spike_past_peoples_99_is_listed_though_the_rate_is_like_peoples(self):
        # one jolt in 20 s: 3 a minute, inside people's rate; 0.72 m/s is past people's 99 % point of spikes (0.60):
        # listed as such (the review of 10-17: a one-frame jolt of the head put into v10 was a place, not listed)
        res = self.measure(jump(300, 0.3))
        r = rows_of(res)
        self.assertEqual(r["spikes.centre_per_min"]["judge"]["word"], "中")
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        self.assertEqual([(e["first"], e["why"]) for e in rep["events"] if e["id"] == "spikes.centre_per_min"], [(300, "extreme")])

    def test_a_spike_smaller_than_peoples_counts_but_is_no_place(self):
        res = self.measure(jump(300, 0.1))                                   # 0.24 m/s: past T 0.15, under people's p90
        r = rows_of(res)
        self.assertEqual(r["spikes.centre_per_min"]["up_dn"], [1, 0])
        self.assertEqual([e for e in res["events"] if e["id"] == "spikes.centre_per_min"], [])


if __name__ == "__main__":
    unittest.main()
