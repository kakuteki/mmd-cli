"""tools/mvi/eyes.py (目): the eyes' angles in the head from the merged motion's 両目 against 頭, and eye_gaze's a07 / a13
measures on them (the share at the edge, the longest stay, the share 15 degrees off the middle)."""
import math
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import eyes, report

F = 300


def look(yaw_of_frame, head_yaw=0.0, frames=None):
    """a body of `frames` frames (F) whose 両目 turns by yaw_of_frame(t) degrees (to the model's left) in a head turned by
    head_yaw"""
    frames = frames or F
    names, pos, rot = MF.pack(frames)
    rot = rot.astype(np.float64)
    from mvi import base
    from mvi.analysts import qmul
    eg = base.tool("eye_gaze")
    h = math.radians(head_yaw) / 2.0
    qh = np.array([0.0, math.sin(h), 0.0, math.cos(h)])
    rot[:, names.index("頭")] = qh
    for t in range(frames):
        rot[t, names.index("両目")] = qmul(qh, np.array(eg.eye_rotation(yaw_of_frame(t), 0.0)))
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot.astype(np.float32)))


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class EdgeTest(unittest.TestCase):
    def test_a_second_at_the_edge(self):
        res = eyes.measure(look(lambda t: 17.0 if 100 <= t < 130 else 0.0, head_yaw=30.0))
        r = rows_of(res)
        self.assertAlmostEqual(r["eyes.edge_pct"]["value"], 100.0 * 30 / F, places=6)
        self.assertAlmostEqual(r["eyes.edge_longest_s"]["value"], 1.0, places=6)
        self.assertAlmostEqual(r["eyes.eccentric15_pct"]["value"], 100.0 * 30 / F, places=6)
        self.assertEqual(r["eyes.edge_pct"]["judge"]["word"], "上へ外")
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        ev = [e for e in rep["events"] if e["listed"]]
        self.assertEqual([(e["first"], e["last"]) for e in ev], [(100, 129)])

    def test_a_long_stay_at_the_edge_is_listed_though_the_share_is_small(self):
        # 1.5 s at the edge in 200 s: 0.75 % (inside the 1 % rule) but past the longest-stay rule (1 s): listed (the
        # review of 10-17: such a stay put into v10 was a place but not in the timeline)
        res = eyes.measure(look(lambda t: 17.0 if 1000 <= t < 1045 else 0.0, head_yaw=30.0, frames=6000))
        r = rows_of(res)
        self.assertEqual(r["eyes.edge_pct"]["judge"]["word"], "中")
        self.assertEqual(r["eyes.edge_longest_s"]["judge"]["word"], "上へ外")
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        self.assertEqual([(e["first"], e["last"], e["why"]) for e in rep["events"] if e["listed"]], [(1000, 1044, "measure")])

    def test_eyes_in_the_middle(self):
        r = rows_of(eyes.measure(look(lambda t: 5.0 * math.sin(t / 10.0))))
        self.assertEqual(r["eyes.edge_pct"]["value"], 0.0)
        self.assertEqual(r["eyes.edge_pct"]["judge"]["word"], "中")


if __name__ == "__main__":
    unittest.main()
