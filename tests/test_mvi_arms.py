"""tools/mvi/arms.py (腕と指): the fingers' speed against the wrist's (review_fingers_lag's contents B: wrist = 手捩 ->
手首, finger = 手首 -> 中指３) on a synthetic body whose bones turn at known rates, and the arm chain's rows of a09."""
import math
import unittest

import numpy as np

from tests import mvi_fixtures as MF
from mvi import arms

F = 300


def spin(deg_per_s, axis=(1.0, 0.0, 0.0)):
    """rotations [F, 4] turning about `axis` at deg_per_s, as float32 (the pack's)"""
    a = np.radians(deg_per_s * np.arange(F) / 30.0)
    q = np.zeros((F, 4))
    q[:, :3] = np.outer(np.sin(a / 2.0), axis)
    q[:, 3] = np.cos(a / 2.0)
    return q.astype(np.float32)


def compose(a, b):
    from mvi.analysts import qmul
    return qmul(a.astype(np.float64), b.astype(np.float64)).astype(np.float32)


def version(wrist=30.0, finger=60.0):
    names, pos, rot = MF.pack(F)
    rot = rot.copy()
    twist = np.zeros((F, 4), np.float32)
    twist[:, 3] = 1.0
    extra = {}
    for s in ("左", "右"):
        hand = spin(wrist)                                    # the hand against the forearm's twist bone
        tip = compose(hand, spin(finger, (0.0, 0.0, 1.0)))     # the finger against the hand
        rot[:, names.index(s + "手首")] = hand
        rot[:, names.index(s + "中指３")] = tip
        extra[s + "手捩"] = (np.zeros((F, 3), np.float32), twist)
    return MF.FakeVersion(names, pos, rot, extra=extra)


def rows_of(res):
    return {r["id"]: r for r in res["rows"]}


class FingerTest(unittest.TestCase):
    def test_the_speeds_and_their_ratio(self):
        r = rows_of(arms.measure(MF.FakeMeasured(version(30.0, 60.0))))
        for s in ("L", "R"):
            self.assertAlmostEqual(r["arms.finger_speed_" + s]["value"], 60.0, delta=0.05)
            self.assertAlmostEqual(r["arms.finger_wrist_ratio_" + s]["value"], 2.0, delta=0.01)

    def test_fingers_slower_than_peoples_are_below_them(self):
        r = rows_of(arms.measure(MF.FakeMeasured(version(80.0, 20.0))))
        self.assertEqual(r["arms.finger_speed_L"]["judge"]["word"], "下へ外")
        self.assertEqual(r["arms.finger_wrist_ratio_L"]["judge"]["word"], "下へ外")

    def test_without_twist_bones_the_fingers_are_not_measured(self):
        names, pos, rot = MF.pack(F)
        r = rows_of(arms.measure(MF.FakeMeasured(MF.FakeVersion(names, pos, rot))))
        self.assertIsNone(r["arms.finger_speed_L"]["value"])


class ChainTest(unittest.TestCase):
    def test_the_a09_rows_are_judged_against_people(self):
        r = rows_of(arms.measure(MF.FakeMeasured(version())))
        for key in ("shoulder_elbow", "elbow_wrist", "wrist_finger"):
            for s in ("L", "R"):
                self.assertIsNotNone(r["arms.a09_%s_%s" % (key, s)]["ref"])
        self.assertIn("arms.wrist_3_6hz_pct", r)
        self.assertIn("arms.wrist_8hz_pct", r)


if __name__ == "__main__":
    unittest.main()
