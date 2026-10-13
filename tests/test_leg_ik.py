"""tools/leg_ik.py: the legs and feet as MMD's IK puts them (the leg IK 足ＩＫ on ひざ and 足, the toe IK つま先ＩＫ on
足首), checked by what the solved bones do: the ankle reaches a reachable goal, the knee bends forward as a hinge
inside its limit, the bones keep their lengths, an unreachable goal straightens the leg toward it, the toe points at
the toe goal, a keyed roll of 足首 survives the toe IK, and the D bones and 足先EX follow."""
import math
import os
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx import IK, NORMAL, TRANSLATE, APPEND_ROTATE, Writer
from tests.test_pmx_spine import load_tool

leg_ik = load_tool("leg_ik")

# the rest positions of Sour's Rin (White.pmx), left side; the right side mirrors x
REST = {
    "全ての親": (0.0, 0.1, 0.0), "センター": (0.0, 7.8468, 0.0), "グルーブ": (0.0, 8.0468, 0.0),
    "腰": (0.0, 11.7255, 0.2554), "下半身": (0.0, 12.2248, -0.6493),
    "腰キャンセル": (0.9012, 10.6579, 0.0073), "足": (0.9012, 10.6579, 0.0073), "ひざ": (1.0032, 6.2313, -0.0361),
    "足首": (1.1205, 1.7452, 0.37), "つま先": (1.0463, 0.1, -1.15), "足IK親": (1.1205, 0.1, 0.37),
    "足ＩＫ": (1.1205, 1.7452, 0.37), "つま先ＩＫ": (1.0462, 0.1, -1.1496), "足先EX": (1.0794, 0.2877, -0.3235),
}
KNEE_LIMITS = ((-math.pi, 0.0, 0.0), (0.0, 0.0, 0.0))


def rin_legs_bytes(vertices=None):
    """a model with the leg rig of Sour's Rin: the body chain, 腰キャンセル (腰 x -1), the leg IK (40 loops, 2 rad, the knee
    limited to an X turn of -180..0), the toe IK (3 loops, 4 rad), the D bones (append x 1) and 足先EX.  `vertices`, when
    given, is called with the Writer and the bone indices by name and returns the vertex records."""
    w = Writer(bone=2, vertex=2)
    rows = [("全ての親", None, "全ての親", NORMAL | TRANSLATE, {}), ("センター", "全ての親", "センター", NORMAL | TRANSLATE, {}),
            ("グルーブ", "センター", "グルーブ", NORMAL | TRANSLATE, {}), ("腰", "グルーブ", "腰", NORMAL, {}),
            ("下半身", "腰", "下半身", NORMAL, {})]
    for side, sx in (("左", 1.0), ("右", -1.0)):
        s = side
        rows += [("腰キャンセル" + s, "下半身", "腰キャンセル", NORMAL | APPEND_ROTATE, {"append": ("腰", -1.0)}),
                 (s + "足", "腰キャンセル" + s, "足", NORMAL, {}), (s + "ひざ", s + "足", "ひざ", NORMAL, {}),
                 (s + "足首", s + "ひざ", "足首", NORMAL, {}), (s + "つま先", s + "足首", "つま先", NORMAL, {}),
                 (s + "足IK親", "全ての親", "足IK親", NORMAL | TRANSLATE, {}),
                 (s + "足ＩＫ", s + "足IK親", "足ＩＫ", NORMAL | TRANSLATE | IK,
                  {"layer": 1, "ik": (s + "足首", 40, 2.0, [(s + "ひざ", KNEE_LIMITS), (s + "足", None)])}),
                 (s + "つま先ＩＫ", s + "足ＩＫ", "つま先ＩＫ", NORMAL | TRANSLATE | IK,
                  {"layer": 2, "ik": (s + "つま先", 3, 4.0, [(s + "足首", None)])}),
                 (s + "足D", "腰キャンセル" + s, "足", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足", 1.0)}),
                 (s + "ひざD", s + "足D", "ひざ", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "ひざ", 1.0)}),
                 (s + "足首D", s + "ひざD", "足首", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足首", 1.0)}),
                 (s + "足先EX", s + "足首D", "足先EX", NORMAL, {"layer": 2})]
    index = {r[0]: i for i, r in enumerate(rows)}
    sides = {}
    for name, parent, rest, flags, kw in rows:
        sx = -1.0 if name.startswith("右") or name.endswith("右") else 1.0
        x, y, z = REST[rest]
        sides[name] = (sx * x, y, z)
    built = []
    for name, parent, rest, flags, kw in rows:
        args = {"parent": -1 if parent is None else index[parent], "position": sides[name], "flags": flags,
                "layer": kw.get("layer", 0)}
        if "append" in kw:
            args["append"] = (index[kw["append"][0]], kw["append"][1])
        if "ik" in kw:
            target, loops, angle, links = kw["ik"]
            args["ik"] = {"target": index[target], "loops": loops, "angle": angle,
                          "links": [(index[l], lim) for l, lim in links]}
        built.append(w.bone(name, **args))
    return w.build(name="rin-legs", bones=built, vertices=vertices(w, index) if vertices else ())


DATA = rin_legs_bytes()
MODEL = pmx.loads(DATA)


def rig():
    return leg_ik.LegRig.loads(DATA)


def axis_angle(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


def key(name, frame, q=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0)):
    return vmd.BoneKey(name, frame, tuple(position), fk.stored(tuple(q)))


def motion(*keys):
    return vmd.Motion(model_name="rin-legs", bones=list(keys))


def length(v):
    return float(np.linalg.norm(v))


def rest(name, side="左"):
    x, y, z = REST[name]
    return np.array([x if side == "左" else -x, y, z])


class RestTest(unittest.TestCase):
    def test_rest_pose_is_the_model(self):
        out = leg_ik.solve(rig(), motion(key("左足ＩＫ", 0)), [0, 1])
        for side in ("左", "右"):
            leg = out[side]
            for f in (0, 1):
                self.assertLess(length(leg["ankle"][f] - rest("足首", side)), 1e-4)
                self.assertLess(length(leg["knee"][f] - rest("ひざ", side)), 1e-4)
                self.assertLess(length(leg["toe"][f] - rest("つま先", side)), 1e-3)
                self.assertLess(length(leg["ex"][f] - rest("足先EX", side)), 1e-3)

    def test_model_without_the_rig_is_refused(self):
        w = Writer(bone=2)
        with self.assertRaises(ValueError):
            leg_ik.LegRig.loads(w.build(bones=[w.bone("全ての親", flags=NORMAL | TRANSLATE)]))

    def test_knee_without_a_limit_is_refused(self):
        # MMD solves a knee without a limit as a free link: not this module's plane solve, so it says so
        limits = leg_ik.ik_limits(pmx_edit.loads(DATA))
        free = {i: [None if j == 0 else lim for j, lim in enumerate(links)] for i, links in limits.items()}
        with self.assertRaises(ValueError):
            leg_ik.LegRig(MODEL, free)


class LegTest(unittest.TestCase):
    def solve(self, *keys, frames=(0,)):
        return leg_ik.solve(rig(), motion(*keys), list(frames))

    def test_reachable_goal_is_reached_with_a_forward_hinge_knee(self):
        # the left foot lifted 3 units and brought 1 unit forward (-z), the pelvis lowered
        out = self.solve(key("左足ＩＫ", 0, position=(0.0, 3.0, -1.0)), key("センター", 0, position=(0.0, -0.5, 0.0)))
        leg = out["左"]
        goal = rest("足ＩＫ") + np.array([0.0, 3.0, -1.0])
        self.assertLess(length(leg["ankle"][0] - goal), 2e-3)
        self.assertLess(leg["reach"][0], 2e-3)
        # bone lengths
        self.assertAlmostEqual(length(leg["knee"][0] - leg["hip"][0]), length(rest("ひざ") - rest("足")), 4)
        self.assertAlmostEqual(length(leg["ankle"][0] - leg["knee"][0]), length(rest("足首") - rest("ひざ")), 4)
        # the knee bends: the angle is inside the limit and well away from straight
        self.assertLess(leg["knee_angle"][0], -math.radians(30))
        self.assertGreaterEqual(leg["knee_angle"][0], -math.pi - 1e-9)
        # forward: the knee is in front (-z) of the line from the hip to the ankle
        hip, knee, ankle = leg["hip"][0], leg["knee"][0], leg["ankle"][0]
        t = np.dot(knee - hip, ankle - hip) / np.dot(ankle - hip, ankle - hip)
        self.assertLess((knee - (hip + t * (ankle - hip)))[2], -0.3)

    def test_knee_local_turn_is_about_x_only(self):
        out = self.solve(key("左足ＩＫ", 0, position=(0.5, 4.0, -2.0)))
        q = out["左"]["local_knee"][0]
        self.assertLess(abs(q[1]) + abs(q[2]), 1e-9)

    def test_unreachable_goal_straightens_the_leg_toward_it(self):
        out = self.solve(key("左足ＩＫ", 0, position=(0.0, -3.0, 0.0)))
        leg = out["左"]
        hip, ankle = leg["hip"][0], leg["ankle"][0]
        goal = rest("足ＩＫ") + np.array([0.0, -3.0, 0.0])
        thigh, shin = length(rest("ひざ") - rest("足")), length(rest("足首") - rest("ひざ"))
        self.assertGreater(length(goal - hip), thigh + shin)
        self.assertGreater(length(ankle - hip), thigh + shin - 0.05)         # nearly straight
        # the ankle lies on the way from the hip to the goal
        d = (goal - hip) / length(goal - hip)
        self.assertGreater(np.dot((ankle - hip) / length(ankle - hip), d), math.cos(math.radians(3)))
        self.assertGreater(leg["reach"][0], 1.0)

    def test_hip_key_turns_the_knee_plane(self):
        # a keyed turn of the thigh about the vertical starts the CCD elsewhere: the knee points elsewhere (the swivel)
        a = self.solve(key("左足ＩＫ", 0, position=(0.0, 3.0, -1.0)))["左"]
        b = self.solve(key("左足ＩＫ", 0, position=(0.0, 3.0, -1.0)), key("左足", 0, axis_angle((0, 1, 0), 40.0)))["左"]
        self.assertLess(length(a["ankle"][0] - b["ankle"][0]), 4e-3)        # the ankle reaches the goal either way
        self.assertGreater(length(a["knee"][0] - b["knee"][0]), 0.5)          # the knee does not

    def test_frames_together_equal_frames_alone(self):
        keys = [key("左足ＩＫ", 0, position=(0.0, 0.0, 0.0)), key("左足ＩＫ", 10, position=(1.0, 4.0, -2.0)),
                key("左足ＩＫ", 20, position=(-0.5, 1.0, 1.0)), key("センター", 0), key("センター", 20, position=(0, -1.5, 0))]
        r = rig()
        together = leg_ik.solve(r, motion(*keys), list(range(21)))
        for f in (3, 10, 17):
            alone = leg_ik.solve(r, motion(*keys), [f])
            for name in ("ankle", "knee", "toe", "ex"):
                self.assertLess(length(together["左"][name][f] - alone["左"][name][0]), 1e-9)


class ToeTest(unittest.TestCase):
    def solve(self, *keys):
        return leg_ik.solve(rig(), motion(*keys), [0])["左"]

    def test_toe_points_at_the_toe_goal(self):
        # pitch the foot IK 30 degrees toe-down about x: the toe goal swings down around the ankle
        leg = self.solve(key("左足ＩＫ", 0, axis_angle((1, 0, 0), -30.0), position=(0.0, 1.0, 0.0)))
        ankle, toe, goal = leg["ankle"][0], leg["toe"][0], leg["goal_toe"][0]
        self.assertGreater(np.dot((toe - ankle) / length(toe - ankle), (goal - ankle) / length(goal - ankle)),
                           math.cos(math.radians(0.05)))
        self.assertAlmostEqual(length(toe - ankle), length(rest("つま先") - rest("足首")), 4)
        self.assertLess(toe[1], rest("つま先")[1] + 1.0 - 0.3)            # it went down relative to a level lift

    def test_keyed_roll_of_the_ankle_survives(self):
        # a 足首 key rolled about the foot's own long axis: the toe IK swings the toe only, so the sole stays rolled
        axis = rest("つま先") - rest("足首")
        flat = self.solve(key("左足ＩＫ", 0, position=(0, 2, 0)))
        rolled = self.solve(key("左足ＩＫ", 0, position=(0, 2, 0)), key("左足首", 0, axis_angle(axis, 20.0)))
        self.assertLess(length(flat["toe"][0] - rolled["toe"][0]), 1e-4)
        # the two feet differ by a turn of 20 degrees about the toe's own axis
        rel = fk.multiply(fk.conjugate(tuple(flat["q_foot"][0])), tuple(rolled["q_foot"][0]))
        self.assertAlmostEqual(math.degrees(2.0 * math.acos(min(1.0, abs(rel[3])))), 20.0, places=3)
        self.assertGreater(abs(np.dot(np.array(rel[:3]) / length(rel[:3]), axis / length(axis))), 1.0 - 1e-6)

    def test_toe_bone_follows_ankle_d_and_ex_key(self):
        # 足先EX turned 30 degrees about x: its world turn is the foot's turn times its own
        leg = self.solve(key("左足ＩＫ", 0, position=(0, 2, 0)), key("左足先EX", 0, axis_angle((1, 0, 0), 30.0)))
        rel = fk.multiply(fk.conjugate(tuple(leg["q_foot"][0])), tuple(leg["q_ex"][0]))
        self.assertAlmostEqual(math.degrees(2 * math.acos(min(1.0, abs(rel[3])))), 30.0, places=3)
        # 足先EX sits on the foot (足首D copies the solved 足首): its place is the rest offset turned with the foot
        self.assertLess(length(leg["ex"][0] - (leg["ankle"][0] + fk.rotate(tuple(leg["q_foot"][0]), tuple(rest("足先EX") - rest("足首"))))), 1e-5)


RIN_PATHS = ("C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx",
             "C:/Users/nayta/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx")


def rin_path():
    for p in RIN_PATHS:
        if os.path.isfile(p):
            return p
    raise unittest.SkipTest("Sour's Rin (White.pmx) is in none of %s" % (RIN_PATHS,))


class SourRinTest(unittest.TestCase):
    def test_rig_of_rin(self):
        left = leg_ik.LegRig.load(rin_path()).sides["左"]
        self.assertEqual(left.leg_loops, 40)
        self.assertAlmostEqual(left.leg_limit, 2.0, 5)
        self.assertEqual(left.toe_loops, 3)
        self.assertAlmostEqual(left.knee_lo, -math.pi, 5)
        self.assertAlmostEqual(left.knee_hi, 0.0, 9)

    def test_rest_of_rin(self):
        model = pmx.load(rin_path())
        out = leg_ik.solve(leg_ik.LegRig.load(rin_path()), motion(key("左足ＩＫ", 0)), [0])
        names = [b.name for b in model.bones]
        for side in ("左", "右"):
            for bone, part in (("足首", "ankle"), ("ひざ", "knee"), ("つま先", "toe"), ("足先EX", "ex")):
                p = model.bones[names.index(side + bone)].position
                self.assertLess(length(out[side][part][0] - np.array(p)), 2e-3, side + bone)


if __name__ == "__main__":
    unittest.main()
