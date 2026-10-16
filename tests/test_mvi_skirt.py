"""tools/mvi/skirt.py (スカートの危なさ): the pelvis's downward acceleration on the floor against the bound 122 (the
curves of tools/sink_check.py, set by the test): on the floor it breaks the rule and is a place; in the air (the
dance's own fall) it is counted apart and not judged."""
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import report, skirt

F = 300


def shoes(drop_at, acc, air_at=None):
    """the pelvis's heights with a fall of `acc` units/s^2 over 4 frames from drop_at; air over air_at (a range)"""
    y = np.full(F, 10.0)
    dt = 1.0 / 30.0
    for k in range(1, 5):
        y[drop_at + k:] -= acc * dt * dt * k                      # the speed grows by acc dt each frame
    y[drop_at + 5:] = y[drop_at + 4]
    air = np.zeros(F, bool)
    if air_at is not None:
        air[air_at[0]:air_at[1] + 1] = True
    return {"lower_body_y": y, "centre_y": y - 4.0, "air": air}


def measured(sh):
    names, pos, rot = MF.pack(F)
    return MF.FakeMeasured(MF.FakeVersion(names, pos, rot), shoes=sh)


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class SkirtTest(unittest.TestCase):
    def test_a_fall_faster_than_the_bound_on_the_floor_is_a_place(self):
        res = skirt.measure(measured(shoes(100, 200.0)))
        r = rows_of(res)
        self.assertGreater(r["skirt.floor_over122_frames"]["value"], 0)
        self.assertEqual(r["skirt.floor_over122_frames"]["judge"]["word"], "上へ外")
        self.assertAlmostEqual(r["skirt.floor_max"]["value"], 200.0, delta=0.5)
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        ev = [e for e in rep["events"] if e["listed"]]
        self.assertTrue(ev and all(100 <= e["first"] <= 106 for e in ev))

    def test_a_fall_within_the_bound_is_not(self):
        r = rows_of(skirt.measure(measured(shoes(100, 110.0))))
        self.assertEqual(r["skirt.floor_over122_frames"]["value"], 0)
        self.assertEqual(r["skirt.floor_over122_frames"]["judge"]["word"], "中")

    def test_the_same_fall_in_the_air_is_counted_apart_and_not_judged(self):
        res = skirt.measure(measured(shoes(100, 200.0, air_at=(95, 110))))
        r = rows_of(res)
        self.assertEqual(r["skirt.floor_over122_frames"]["value"], 0)
        self.assertGreater(r["skirt.air_over122_frames"]["value"], 0)
        self.assertIsNone(r["skirt.air_over122_frames"]["judge"])
        self.assertEqual(res["events"], [])


if __name__ == "__main__":
    unittest.main()
