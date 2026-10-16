"""tools/upper_body_check.py: measures of the upper body over the hips that a layer does not aim at (the head's stops,
the trunk's and the neck's bend, the head's lag behind the hips, the local follow, the beat, a hand at the face).  Each
test builds a motion whose answer is known without the tool."""
import importlib.util
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import vmd
from tests.test_balance_layer import MODEL, dance, model_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 30.0
U = 0.08


def load_tool():
    spec = importlib.util.spec_from_file_location("upper_body_check", os.path.join(ROOT, "tools", "upper_body_check.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ub = load_tool()


def still_parts(F):
    """a standing body's bones (units) with no turn: the hips, the trunk, the head, the eyes and the hands"""
    rest = {"下半身": (0.0, 12.2, -0.65), "上半身": (0.0, 12.2, -0.65), "上半身2": (0.0, 13.8, -0.68), "首": (0.0, 15.6, -0.13),
            "頭": (0.0, 16.2, 0.0), "左目": (0.4, 17.2, -0.56), "右目": (-0.4, 17.2, -0.56), "左手首": (4.6, 12.4, -0.24),
            "右手首": (-4.6, 12.4, -0.24), "左中指３": (5.9, 11.5, -0.26), "右中指３": (-5.9, 11.5, -0.26)}
    ident = np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
    return {k: (np.tile(np.asarray(v, dtype=np.float64), (F, 1)), ident.copy()) for k, v in rest.items()}


def path_from_speed(v):
    """positions (units) along x whose step speeds (m/s) are v [F - 1]"""
    return np.concatenate([[0.0], np.cumsum(v) / FPS / U])


def wander(F, seed=0, lo=0.3, hi=6.0):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(size=(F, 2)), 0)
    x = ub.D.lowpass(x - ub.D.lowpass(x, lo), hi)
    return np.stack([x[:, 0], np.zeros(F), x[:, 1]], 1)


def turn_about(axis, angles):
    axis = np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis)
    h = np.asarray(angles, dtype=np.float64) / 2.0
    return np.concatenate([np.sin(h)[:, None] * axis[None, :], np.cos(h)[:, None]], 1)


class StopsTest(unittest.TestCase):
    def speed_profile(self, fall_steps):
        """1.2 m/s, a straight fall to 0.1 m/s over fall_steps steps, then a rise back (one stop)"""
        v = [1.2] * 20 + [1.2 - k * 1.1 / fall_steps for k in range(1, fall_steps + 1)] + \
            [0.1 + k * 0.2 for k in range(1, 6)] + [1.1] * 20
        return np.array(v)

    def test_the_fall_time_80_to_20_percent(self):
        """a straight fall over n steps takes 0.6 n steps from 80 to 20 % of the drop (n up to a08's 8 steps: the peak
        is looked for in the 8 steps before the minimum)"""
        for n in (3, 7):
            p = np.zeros((len(self.speed_profile(n)) + 1, 3))
            p[:, 0] = path_from_speed(self.speed_profile(n))
            r = ub.stops(p)
            self.assertEqual(r["n"], 1, n)
            self.assertAlmostEqual(r["t80_20_ms"]["p50"], 0.6 * n * 1000.0 / FPS, delta=0.5, msg=n)

    def test_a_slow_move_has_no_stop(self):
        p = np.zeros((len(self.speed_profile(3)) + 1, 3))
        p[:, 0] = path_from_speed(0.4 * self.speed_profile(3))             # its peak 0.48 m/s: under a08's 0.6
        self.assertEqual(ub.stops(p)["n"], 0)

    def test_the_lowest_step_is_reported(self):
        v = self.speed_profile(3)
        p = np.zeros((len(v) + 1, 3))
        p[:, 0] = path_from_speed(v)
        r = ub.stops(p, rng=(0, len(p) - 1))
        self.assertEqual(r["frames"], [int(np.argmin(v))])


class RangeTest(unittest.TestCase):
    def test_the_dance_proper(self):
        """still for 60 frames, the head moving at 0.3 m/s over steps 60 .. 359, still again: frames 75 .. 344"""
        F = 420
        parts = still_parts(F)
        v = np.zeros(F - 1)
        v[60:360] = 0.3
        parts["頭"][0][:, 0] = path_from_speed(v)
        self.assertEqual(ub.dance_range(parts), (75, 344))
        self.assertIsNone(ub.dance_range(still_parts(F)))


class BendTest(unittest.TestCase):
    def test_the_turn_against_the_hips_not_the_world(self):
        """the chest turns at 60 deg/s against the hips while the whole body also turns about the vertical"""
        F = 90
        parts = still_parts(F)
        t = np.arange(F) / FPS
        whole = turn_about((0, 1, 0), np.radians(90.0) * t)
        own = turn_about((0, 0, 1), np.radians(60.0) * t)
        parts["下半身"] = (parts["下半身"][0], whole)
        parts["上半身2"] = (parts["上半身2"][0], ub.D.qmul(whole, own))
        parts["頭"] = (parts["頭"][0], ub.D.qmul(whole, own))
        b = ub.bend(parts)
        self.assertAlmostEqual(b["chest_on_hips"]["speed_deg_s"]["p50"], 60.0, delta=0.5)
        self.assertLess(b["head_on_chest"]["speed_deg_s"]["p99"], 0.5)
        self.assertAlmostEqual(b["chest_on_hips"]["angle_deg"]["max"], 60.0 * t[-1], delta=0.5)

    def test_quick_and_slow_bends(self):
        F = 300
        t = np.arange(F) / FPS
        for hz, quick in ((3.0, True), (0.4, False)):
            parts = still_parts(F)
            parts["上半身2"] = (parts["上半身2"][0], turn_about((1, 0, 0), np.radians(4.0) * np.sin(2 * math.pi * hz * t)))
            share = ub.bend(parts)["chest_on_hips"]["share_over_1_5Hz"]
            if quick:
                self.assertGreater(share, 0.95)
            else:
                self.assertLess(share, 0.05)


class LagTest(unittest.TestCase):
    def setUp(self):
        self.F = 900
        self.pel = wander(self.F)

    def test_a_head_behind_the_hips(self):
        for k in (3, -3):
            head = np.roll(self.pel, k, axis=0)                     # head(t) = pel(t - k)
            r = ub.lag(head, self.pel, rng=(20, self.F - 21))
            self.assertAlmostEqual(r["peak_lag_ms"], k * 1000.0 / FPS, delta=5.0, msg=k)
            self.assertGreater(np.sign(k) * r["lean"], 0.2, k)

    def test_a_smoothed_copy_has_no_lag(self):
        """a head that moves as a zero-phase smoothed copy of the hips (what a layer driven by the hips' quick part
        gives a carried head) peaks at 0 and leans neither way"""
        head = 0.1 * self.pel + 0.9 * ub.D.lowpass(self.pel, 1.5)
        r = ub.lag(head, self.pel, rng=(20, self.F - 21))
        self.assertLess(abs(r["peak_lag_ms"]), 5.0)
        self.assertLess(abs(r["lean"]), 0.05)


class LocalFollowTest(unittest.TestCase):
    def test_against_and_carried(self):
        F = 900
        pel = wander(F, seed=1)
        head = pel.copy()
        head[F // 2:] *= -1.0                                        # carried, then thrown the other way
        r = ub.local_follow(head, pel)
        self.assertGreater(r["share_carried"], 0.35)
        self.assertGreater(r["share_against"], 0.35)
        self.assertLess(r["most_against"][0]["slope"], -0.9)
        still = ub.local_follow(np.zeros_like(pel), pel)
        self.assertEqual(still["share_carried"], 0.0)
        self.assertEqual(still["share_against"], 0.0)


class BeatTest(unittest.TestCase):
    def test_depth_of_the_speed_on_the_beat(self):
        F = 600
        beats = list(np.arange(0.0, F / FPS + 1.0, 0.5))
        t = np.arange(F) / FPS
        ph = (t % 0.5) / 0.5
        speed = 1.0 + 0.8 * np.cos(2 * math.pi * ph)                 # m/s: fastest on the beat
        p = np.zeros((F, 3))
        p[:, 0] = np.cumsum(speed) / FPS / U
        r = ub.beat_depth(p, beats, rng=(10, F - 11))
        self.assertGreater(r["depth"], 1.2)
        self.assertGreater(r["bins_m_s"][0], r["bins_m_s"][4])
        flat = np.zeros((F, 3))
        flat[:, 0] = np.arange(F) / FPS / U
        self.assertLess(ub.beat_depth(flat, beats, rng=(10, F - 11))["depth"], 0.01)

    def test_stops_on_the_beat(self):
        beats = [1.0, 1.5, 2.0, 2.5]
        self.assertEqual(ub.on_beat_share([30, 45, 60], beats), 1.0)           # the step 30 -> 31 is at 1.0167 s
        self.assertEqual(ub.on_beat_share([37, 52], beats), 0.0)               # half a beat off


class FaceTest(unittest.TestCase):
    def test_a_hand_at_the_face(self):
        F = 40
        before = still_parts(F)
        e = ub.eyes(before)
        tip = e + np.array([0.0, 0.0, -5.0 / 8.0])                   # 5 cm in front of the eyes
        before["左中指３"] = (tip, before["左中指３"][1])
        after = {k: (v[0].copy(), v[1].copy()) for k, v in before.items()}
        for n in ("左目", "右目", "頭"):
            after[n][0][:, 2] += 3.0 / 8.0                            # the head 3 cm back, the hand stays
        r = ub.face(before, after)
        self.assertEqual(r["frames"], F)                              # the right hand is far: only the left counts
        self.assertAlmostEqual(r["change_cm"]["p50"], 3.0, places=6)
        self.assertEqual(r["farther_2cm"], F)
        self.assertEqual(r["closer_1cm"], 0)
        c = ub.compare(before, after)
        self.assertAlmostEqual(c["moves"]["head_cm"]["max"], 3.0, places=6)
        self.assertAlmostEqual(c["moves"]["fingertip_L_cm"]["max"], 0.0, places=6)
        self.assertIsNone(c["waist"])                                 # no hip joints: no waist

    def test_a_hand_on_the_hip(self):
        """a hand laid on the hip (4 cm from the line from the hips' middle to 下半身) that the chest carries 3 cm out"""
        F = 40
        before = still_parts(F)
        for n, x in (("左足", 0.9), ("右足", -0.9)):
            before[n] = (np.tile([x, 10.6, 0.0], (F, 1)), before["下半身"][1].copy())
        before["左中指３"] = (np.tile([0.5, 11.4, -0.325], (F, 1)), before["左中指３"][1])     # off the line's middle along x
        after = {k: (v[0].copy(), v[1].copy()) for k, v in before.items()}
        after["左中指３"][0][:, 0] += 3.0 / 8.0
        r = ub.compare(before, after)["waist"]
        self.assertEqual(r["frames"], F)
        self.assertAlmostEqual(r["change_cm"]["p50"], 3.0, places=6)
        self.assertEqual(r["farther_2cm"], F)


class SourceTest(unittest.TestCase):
    def test_from_motion_is_the_fk(self):
        motion = dance(left_lifts=[(20, 30, 40, 50, 2.0)], arms=True)
        parts = ub.from_motion(MODEL, motion)
        last = fk.last_frame(motion)
        tr = fk.world_track(MODEL, motion, list(parts), 0, last)
        for n, (p, q) in parts.items():
            np.testing.assert_allclose(p, np.array([x for x, _ in tr[n]]), atol=1e-6, err_msg=n)
            dq = np.abs(np.sum(q * np.array([y for _, y in tr[n]]), axis=1))
            self.assertGreater(dq.min(), 1.0 - 1e-9, n)


class CommandTest(unittest.TestCase):
    def test_measure_and_compare(self):
        tmp = tempfile.mkdtemp()
        try:
            a, b, m = (os.path.join(tmp, n) for n in ("a.vmd", "b.vmd", "m.pmx"))
            with open(a, "wb") as f:
                f.write(vmd.dumps(dance(left_lifts=[(20, 30, 60, 70, 2.0)], arms=True)))
            with open(b, "wb") as f:
                f.write(vmd.dumps(dance(left_lifts=[(20, 30, 60, 70, 2.0)])))
            with open(m, "wb") as f:
                f.write(model_bytes())
            beats = os.path.join(tmp, "beats.json")
            with open(beats, "w", encoding="utf-8") as f:
                json.dump({"beats": [0.5 * k for k in range(20)]}, f)
            r1, r2 = os.path.join(tmp, "r1.json"), os.path.join(tmp, "r2.json")
            self.assertEqual(ub.main(["measure", a, "--model", m, "--report", r1, "--beats", beats]), 0)
            with open(r1, encoding="utf-8") as f:
                rep = json.load(f)
            for k in ("stops", "bend", "lag", "local", "beats"):
                self.assertIn(k, rep)
            self.assertEqual(ub.main(["compare", a, b, "--model", m, "--report", r2]), 0)
            with open(r2, encoding="utf-8") as f:
                self.assertIn("moves", json.load(f))
            self.assertEqual(ub.main(["compare", a, a, "--model", m, "--report", r2]), 2)
            self.assertEqual(ub.main(["measure", a, "--report", r1]), 2)            # a dance needs its model
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
