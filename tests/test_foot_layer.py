"""tools/foot_layer.py: the feet measured as MMD shows them (the sole from the mesh, the angles of the ankle complex, the
contact with the floor), and the layer that makes them carry weight anatomically.  Checked by what the feet do: a
rolled foot is measured rolled and laid flat on the floor by the layer, the ball and the toes take a raised heel, the
sole neither sinks into nor hovers over the floor while loaded, the air keeps the dance's foot, nothing else moves."""
import math
import os
import struct
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_leg_ik import REST, axis_angle, key, rest, rin_legs_bytes
from tests.test_pmx import Writer
from tests.test_pmx_spine import load_tool

foot_layer = load_tool("foot_layer")
leg_ik = foot_layer.IK

# the left shoe's sole at rest (Sour's Rin's sizes: the heel block and the forefoot, the toe box on 足先EX); the
# right shoe mirrors x.  (x, y, z, weight on 足先EX)
SOLE = [(0.95, 0.111, 0.55, 0.0), (1.25, 0.111, 0.55, 0.0), (0.95, 0.111, 0.9, 0.0), (1.25, 0.111, 0.9, 0.0),
        (0.75, 0.112, -0.3, 0.1), (1.45, 0.112, -0.3, 0.1), (0.75, 0.112, -0.7, 0.5), (1.45, 0.112, -0.7, 0.5),
        (0.95, 0.13, -1.0, 0.87), (1.2, 0.13, -1.0, 0.87)]
UPPER = [(1.12, 0.6, 0.2, 0.0), (1.1, 0.45, -0.8, 0.6)]       # the shoe's upper: not the sole


def shoe_model_bytes():
    """the leg rig of tests.test_leg_ik with a sole (and two upper vertices) on each foot"""
    def vertices(w, index):
        out = []
        for side, sx in (("左", 1.0), ("右", -1.0)):
            ankle_d, ex = index[side + "足首D"], index[side + "足先EX"]
            for x, y, z, wex in SOLE + UPPER:
                raw = w.vertex("BDEF2", (ex, ankle_d), (wex,)) if wex > 0 else w.vertex("BDEF1", (ankle_d,))
                out.append(struct.pack("<3f", sx * x, y, z) + raw[12:])
        return out
    return rin_legs_bytes(vertices)


DATA = shoe_model_bytes()
RIG = leg_ik.LegRig.loads(DATA)
SHOE = foot_layer.Shoe(RIG, pmx_edit.loads(DATA))


def motion(*keys):
    return vmd.Motion(model_name="rin-legs", bones=list(keys))


def measure(*keys, frames=(0,), floor_y=0.0):
    return foot_layer.measure_feet(RIG, SHOE, motion(*keys), list(frames), floor_y)


class ShoeTest(unittest.TestCase):
    def test_sole_found_and_split(self):
        for s, sx in (("左", 1.0), ("右", -1.0)):
            o = SHOE.sides[s]
            self.assertEqual(len(o.points), len(SOLE))                       # the upper is not the sole
            self.assertAlmostEqual(o.floor, 0.111, 5)
            self.assertEqual(int(o.heel.sum()), 4)
            self.assertEqual(int(o.fore.sum()), 6)
            self.assertGreater(-o.a0[2], 0.99)                                # forward is -Z
            self.assertGreater(o.l0[0] * sx, 0.99)                            # lateral is the foot's outside
            self.assertAlmostEqual(float(o.w_ex.max()), 0.87, 5)


class MeasureTest(unittest.TestCase):
    def test_rest(self):
        m = measure(key("左足ＩＫ", 0))
        for s in ("左", "右"):
            f = m[s]
            self.assertAlmostEqual(float(f["low"][0]), 0.111, 4)
            self.assertAlmostEqual(float(f["pitch"][0]), 0.0, delta=0.02)    # the toe IK's goal is 0.0004 off its bone
            self.assertAlmostEqual(float(f["roll"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["inversion"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["adduction"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["dorsi"][0]), f["rest_dorsi"], delta=0.02)
            self.assertAlmostEqual(float(f["mtp"][0]), f["rest_mtp"], 3)
        # the rest's own anatomy: the shank leans forward 5.2 degrees, the heel pitches the foot down in the shoe
        self.assertAlmostEqual(m["左"]["rest_dorsi"], 5.18 - foot_layer.HEEL_PITCH_DEG, 1)

    def test_roll_of_the_ankle_key_is_measured_as_inversion(self):
        # the foot turned about its own forward axis so that its outside edge falls: 足ＩＫ turned (the toe goal swings)
        # and 足首 keyed by the same turn (the toe IK then has nothing to do): inversion on both sides
        for s, sign in (("左", 1.0), ("右", -1.0)):
            a0 = tuple(SHOE.sides[s].a0)
            q = axis_angle(a0, sign * 12.0)
            f = measure(key(s + "足ＩＫ", 0, q), key(s + "足首", 0, q))[s]
            self.assertAlmostEqual(float(f["roll"][0]), 12.0, delta=0.05)
            self.assertAlmostEqual(float(f["inversion"][0]), 12.0, delta=0.05)
            self.assertAlmostEqual(float(f["adduction"][0]), 0.0, delta=0.05)
            self.assertLess(float(f["low"][0]), float(f["flat_low"][0]) - 0.02)    # the outside edge dips
            self.assertAlmostEqual(float(f["flat_low"][0]), 0.111, delta=0.005)     # laid flat: on the trace's floor

    def test_pitch_and_dorsiflexion(self):
        # the foot IK turned 20 degrees toes-up about X: the foot dorsiflexes 20 against an unmoved shank
        m = measure(key("センター", 0, position=(0, -1.0, 0)), key("左足ＩＫ", 0, axis_angle((1, 0, 0), 20.0)))["左"]
        self.assertAlmostEqual(float(m["pitch"][0]), 20.0, delta=0.5)
        self.assertGreater(float(m["dorsi"][0]) - m["rest_dorsi"], 15.0)        # the shank leans too: not exactly 20

    def test_toes_key_is_extension(self):
        m = measure(key("左足ＩＫ", 0, position=(0, 1.0, 0)), key("左足先EX", 0, axis_angle((1, 0, 0), 25.0)))["左"]
        self.assertAlmostEqual(float(m["mtp"][0]) - m["rest_mtp"], 25.0, places=3)

    def test_contact_mask_hysteresis(self):
        # enters at or below 0.111 + 0.03, leaves above 0.111 + 0.06
        h = np.array([0.5, 0.2, 0.15, 0.13, 0.15, 0.165, 0.18, 0.15, 0.112])
        on = foot_layer.contact_mask(h, 0.111)
        self.assertEqual(on.tolist(), [False, False, False, True, True, True, False, False, True])


RIN_PATHS = ("C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx",
             "C:/Users/nayta/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx")


def rin_path():
    for p in RIN_PATHS:
        if os.path.isfile(p):
            return p
    raise unittest.SkipTest("Sour's Rin (White.pmx) is in none of %s" % (RIN_PATHS,))


class SourRinShoeTest(unittest.TestCase):
    def test_rin_sole(self):
        path = rin_path()
        rig = leg_ik.LegRig.load(path)
        shoe = foot_layer.Shoe.load(rig, path)
        for s, sx in (("左", 1.0), ("右", -1.0)):
            o = shoe.sides[s]
            self.assertAlmostEqual(o.floor, 0.111, 2)
            self.assertGreater(len(o.points), 30)
            # the heel block lies behind the ankle, the forefoot in front of the ball
            heel_t = ((o.points[o.heel] - o.ankle) @ o.a0)
            fore_t = ((o.points[o.fore] - o.ankle) @ o.a0)
            self.assertLess(heel_t.max(), 0.0)
            self.assertGreater(fore_t.min(), 0.4)
            self.assertGreater(o.l0[0] * sx, 0.95)


if __name__ == "__main__":
    unittest.main()
