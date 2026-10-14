"""tools/balance_layer.py: the weight goes onto the standing foot (センター moves the body over it, before the other foot
lifts) and the knee bends on a landing that takes the weight; a lifted foot's IK goes with the body on the floor plane,
the feet on the floor stay where they were."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, IK, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CM = 8.0                        # cm per model unit
FPS = 30.0


def load_tool():
    spec = importlib.util.spec_from_file_location("balance_layer", os.path.join(ROOT, "tools", "balance_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


balance_layer = load_tool()

# Sour's Rin's rest positions (model units) of the bones the layer reads
SIDE = {"左": 1.0, "右": -1.0}


def model_bytes():
    w = Writer(bone=2)
    bones = [("全ての親", None, (0.0, 0.1, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.8468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("グルーブ", "センター", (0.0, 8.0468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("腰", "グルーブ", (0.0, 11.7255, 0.2554), {}),
             ("上半身", "腰", (0.0, 12.2248, -0.6493), {}),
             ("上半身2", "上半身", (0.0, 13.7985, -0.6784), {}),
             ("首", "上半身2", (0.0, 15.6456, -0.1343), {}),
             ("頭", "首", (0.0, 16.2431, 0.0), {}),
             ("頭先", "頭", (0.0, 18.7663, -0.1601), {}),
             ("左目", "頭", (0.4101, 17.2143, -0.562), {}),
             ("右目", "頭", (-0.4101, 17.2143, -0.562), {}),
             ("下半身", "腰", (0.0, 12.2248, -0.6493), {})]
    for s, sx in SIDE.items():
        bones += [(s + "肩", "上半身2", (sx * 0.2296, 15.3934, -0.222), {}),
                  (s + "腕", s + "肩", (sx * 0.9114, 15.2768, -0.2484), {}),
                  (s + "ひじ", s + "腕", (sx * 2.9071, 13.7325, -0.27), {}),
                  (s + "手首", s + "ひじ", (sx * 4.6524, 12.4104, -0.2368), {}),
                  (s + "中指３", s + "手首", (sx * 5.8701, 11.5382, -0.2637), {})]
    for s, sx, hy in (("左", 1.0, 10.6579), ("右", -1.0, 10.591)):
        bones += [("腰キャンセル" + s, "下半身", (sx * 0.9012, hy, 0.0073), {"flags": NORMAL | APPEND_ROTATE, "append": "腰"}),
                  (s + "足", "腰キャンセル" + s, (sx * 0.9012, hy, 0.0073), {}),
                  (s + "ひざ", s + "足", (sx * 1.0032, 6.2313, -0.0361), {}),
                  (s + "足首", s + "ひざ", (sx * 1.1205, 1.7452, 0.37), {}),
                  (s + "つま先", s + "足首", (sx * 1.0463, 0.1, -1.15), {}),
                  (s + "足IK親", "全ての親", (sx * 1.1205, 0.1, 0.37), {"flags": NORMAL | TRANSLATE}),
                  (s + "足ＩＫ", s + "足IK親", (sx * 1.1205, 1.7452, 0.37),
                   {"flags": NORMAL | TRANSLATE | IK, "ik": (s + "足首", [(s + "ひざ", ((-math.pi, 0, 0), (0, 0, 0))), (s + "足", None)])}),
                  (s + "つま先ＩＫ", s + "足ＩＫ", (sx * 1.0462, 0.1, -1.1496),
                   {"flags": NORMAL | TRANSLATE | IK, "ik": (s + "つま先", [(s + "足首", None)])})]
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"]], -1.0)
        if "ik" in kw:
            target, links = kw["ik"]
            kw["ik"] = {"target": index[target], "loops": 40, "angle": 2.0,
                        "links": [(index[n], lim) for n, lim in links]}
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-like", bones=built)


MODEL = pmx.loads(model_bytes())


def key(name, frame, position=(0.0, 0.0, 0.0), q=(0.0, 0.0, 0.0, 1.0)):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(q)),
                       vmd.bone_interpolation(vmd.LINEAR_CURVE))


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def foot_track(name, last, base, lifts):
    """per-frame keys of a foot IK: at `base` (x, y, z offsets, units) and raised by each (start, up, down, end, height)
    lift (a smoothstep up from start to up, held, down from down to end)"""
    keys = []
    for f in range(last + 1):
        h = 0.0
        for a, b, c, d, height in lifts:
            if a <= f <= d:
                h = max(h, height * min(smooth((f - a) / max(b - a, 1)), 1.0 - smooth((f - c) / max(d - c, 1))))
        keys.append(key(name, f, (base[0], base[1] + h, base[2])))
    return keys


def dance(last=119, spread=1.0, centre=(0.0, -0.6, 0.0), left_lifts=(), right_lifts=(), arms=False, centre_keys=None,
          pelvis_roll_deg=0.0, left_point=None):
    """feet `spread` units out from rest (both sides), センター still at `centre` (as a trace keeps it between the feet),
    the lifts of each foot; morphs and an arm key that the layer must copy byte for byte.  pelvis_roll_deg turns 下半身
    about Z (negative: its left side goes down); left_point (first, last, degrees) turns the left foot IK about X from 0
    to the degrees (negative points the toe down and back)"""
    bones = []
    left = foot_track("左足ＩＫ", last, (spread, 0.0, 0.0), left_lifts)
    if left_point is not None:
        a, b, deg = left_point
        for k in left:
            ang = math.radians(deg) * smooth((k.frame - a) / float(b - a))
            k.rotation = fk.stored((math.sin(ang / 2.0), 0.0, 0.0, math.cos(ang / 2.0)))
    bones += left
    bones += foot_track("右足ＩＫ", last, (-spread, 0.0, 0.0), right_lifts)
    if pelvis_roll_deg:
        h = math.radians(pelvis_roll_deg) / 2.0
        bones += [key("下半身", 0, q=(0.0, 0.0, math.sin(h), math.cos(h))),
                  key("下半身", last, q=(0.0, 0.0, math.sin(h), math.cos(h)))]
    if centre_keys is None:
        bones += [key("センター", 0, centre), key("センター", last, centre)]
    else:
        bones += centre_keys
    bones += [key("上半身", 0), key("上半身", last, q=(0.05, 0.0, 0.0, math.sqrt(1 - 0.0025)))]
    if arms:
        bones += [key("左腕", 0, q=(0.0, 0.0, 0.3, math.sqrt(1 - 0.09))), key("左腕", last)]
    morphs = [vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)]
    return vmd.Motion(model_name="dancer", bones=bones, morphs=morphs)


def centre_offsets(motion_in, motion_out, last):
    """per frame, the world move of センター (units) between the two motions"""
    a = fk.world_track(MODEL, motion_in, ["センター"], 0, last)["センター"]
    b = fk.world_track(MODEL, motion_out, ["センター"], 0, last)["センター"]
    return np.array([np.subtract(pb, pa) for (pa, _), (pb, _) in zip(a, b)])


def others(motion, skip=("センター",)):
    return vmd.dumps(vmd.Motion(model_name=motion.model_name, bones=[k for k in motion.bones if k.name not in skip],
                                morphs=motion.morphs))


LIFT_RIGHT_STANDS = [(40, 50, 80, 90, 2.5)]          # the left foot up 20 cm from 1.33 s to 3 s: the right foot stands


class BodyTest(unittest.TestCase):
    """the body's centre of mass and the legs, which everything else reads"""

    def test_rest_com_on_the_midline_at_a_plausible_height(self):
        motion = dance()
        body = balance_layer.Body(MODEL, motion)
        com = body.com()
        self.assertLess(abs(com[60, 0]), 0.05)                     # symmetric: on the midline (0.4 cm)
        self.assertTrue(9.0 < com[60, 1] < 11.5, com[60, 1])        # near the hips (72 - 92 cm)

    def test_arm_sideways_moves_the_com_by_its_share(self):
        still = balance_layer.Body(MODEL, dance()).com()
        raised = balance_layer.Body(MODEL, dance(arms=True)).com()
        dx = raised[0, 0] - still[0, 0]
        # the left arm turned 35 degrees about Z: the arm's 4.5 % of the mass moves; the COM goes a few mm, not cm
        self.assertGreater(abs(dx), 0.005)
        self.assertLess(abs(dx), 0.15)

    def test_knee_from_the_leg_lengths(self):
        body = balance_layer.Body(MODEL, dance())
        flex = body.knee_flexion("左")
        # センター 0.6 units down: the knees bend (the rest pose is 5.3 degrees)
        self.assertTrue(15.0 < flex[60] < 60.0, flex[60])
        straight = balance_layer.Body(MODEL, dance(centre=(0.0, 0.0, 0.0), spread=0.0))
        self.assertLess(straight.knee_flexion("左")[60], 8.0)


class WeightShiftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.last = 119
        cls.motion = dance(last=cls.last, left_lifts=LIFT_RIGHT_STANDS)
        cls.result = balance_layer.layer(MODEL, cls.motion)
        cls.out = cls.result.motion
        cls.report = cls.result.report
        cls.shift = centre_offsets(cls.motion, cls.out, cls.last)

    def test_body_goes_over_the_standing_foot(self):
        before = balance_layer.Body(MODEL, self.motion)
        after = balance_layer.Body(MODEL, self.out)
        foot = 0.5 * (before.ankle("右") + before.toe("右"))[:, [0, 2]]
        lat_before = np.abs(before.com()[55:80, 0] - foot[55:80, 0]) * CM
        lat_after = np.abs(after.com()[55:80, 0] - foot[55:80, 0]) * CM
        self.assertGreater(lat_before.min(), 12.0)          # the trace's body hangs between the feet
        self.assertLess(lat_after.max(), 3.0)               # over the standing foot while the other is up
        self.assertLess(self.shift[60, 0], -1.2)            # センター went to the right (-X), 10 cm and more

    def test_shift_starts_before_the_foot_lifts(self):
        x = -self.shift[:, 0]
        plateau = np.median(x[60:75])
        lift = 41                                            # the left foot's first frame above the floor
        self.assertGreater(x[lift], 0.5 * plateau)           # mostly done when the foot leaves the floor
        first = int(np.flatnonzero(x > 0.1 * plateau)[0])
        self.assertLessEqual(first, lift - 3)                # began at least 0.1 s before

    def test_shift_returns_after_the_foot_lands(self):
        """back by the end (1 s after the landing) and not begun a second before the lift (a 17 cm move at the bounded
        acceleration takes about 0.8 s)"""
        x = np.abs(self.shift[:, 0])
        self.assertLess(x[self.last], 0.01)
        self.assertLess(x[:10].max(), 0.01)

    def test_no_swing_the_wrong_way(self):
        """the body does not first lean towards the foot that will lift, nor overshoot past the dance after the
        landing (a smoother's ringing; people do not move the body the wrong way before shifting the weight)"""
        towards_lifted = self.shift[:, 0] * CM                  # the left foot lifts: +X is towards it
        self.assertLess(towards_lifted.max(), 0.2)

    def test_smooth_no_one_frame_jump(self):
        step = np.linalg.norm(np.diff(self.shift, axis=0), axis=1) * CM
        self.assertLess(step.max(), 1.5)
        # the COM's added acceleration on the floor stays under the bound (the pressure under the foot can make it), but
        # for the lifted leg's share (thigh, shank and foot: 20.9 % of the mass) of what the carry adds to its foot
        added = (balance_layer.Body(MODEL, self.out).com() - balance_layer.Body(MODEL, self.motion).com())[:, [0, 2]]
        acc = np.linalg.norm(added[2:] - 2 * added[1:-1] + added[:-2], axis=1) * 0.08 * FPS * FPS
        foot = (world(self.out, ["左足ＩＫ"], self.last)["左足ＩＫ"][0] - world(self.motion, ["左足ＩＫ"], self.last)["左足ＩＫ"][0])
        foot_acc = np.linalg.norm(foot[2:] - 2 * foot[1:-1] + foot[:-2], axis=1) * 0.08 * FPS * FPS
        self.assertLess(acc.max(), balance_layer.ACC_MAX * 1.1 + 0.209 * foot_acc.max())
        self.assertLess(acc.max(), 2.0 * balance_layer.ACC_MAX)
        # and the hips' drop (for the legs' reach; no landing takes weight here) is slower still
        down = self.shift[:, 1]
        acc_y = np.abs(down[2:] - 2 * down[1:-1] + down[:-2]) * 0.08 * FPS * FPS
        self.assertLess(acc_y.max(), balance_layer.DROP_ACC_MAX * 1.1)

    def test_feet_and_everything_else_untouched(self):
        """センター and the lifted foot's IK (on the floor plane, while it is up) are written; every other bone, the
        morphs and the standing foot are the dance's bytes"""
        self.assertEqual(others(self.motion, skip=("センター", "左足ＩＫ")), others(self.out, skip=("センター", "左足ＩＫ")))
        self.assertTrue(self.report["untouched"]["identical"])
        self.assertEqual(self.report["untouched"]["written"], ["センター", "左足ＩＫ"])
        before, after = world(self.motion, ["左足ＩＫ"], self.last)["左足ＩＫ"], world(self.out, ["左足ＩＫ"], self.last)["左足ＩＫ"]
        move = after[0] - before[0]
        np.testing.assert_allclose(move[:41], 0.0, atol=1e-6)               # on the floor till it lifts
        np.testing.assert_allclose(move[90:], 0.0, atol=1e-6)               # and from its landing
        np.testing.assert_allclose(move[:, 1], 0.0, atol=1e-6)              # its height is the dance's
        np.testing.assert_allclose(after[1], before[1], atol=1e-6)          # and its turn

    def test_legs_reach_their_feet(self):
        """each leg keeps 1.5 cm of slack to its foot IK (MMD's IK falls short of the target on a leg nearer full
        stretch), or what slack it had"""
        before, after = balance_layer.Body(MODEL, self.motion), balance_layer.Body(MODEL, self.out)
        for s in ("左", "右"):
            room = np.maximum(after.leg_length(s) - balance_layer.REACH_TOL_CM / CM, before.reach(s))
            self.assertTrue(np.all(after.reach(s) <= room + 1e-6), s)
            self.assertEqual(self.report["reach"]["slack_taken_frames_" + {"左": "L", "右": "R"}[s]], 0)

    def test_report_splits_the_added_acceleration(self):
        c = self.report["centre"]
        added = self.shift * 0.08
        acc = added[2:] - 2 * added[1:-1] + added[:-2]
        self.assertAlmostEqual(c["added_acc_h_m_s2"]["max"], float(np.linalg.norm(acc[:, [0, 2]], axis=1).max()) * FPS * FPS, 2)
        self.assertAlmostEqual(c["added_acc_v_m_s2"]["max"], float(np.abs(acc[:, 1]).max()) * FPS * FPS, 2)

    def test_report_measures_a05(self):
        a05 = self.report["a05_lateral_cm"]
        self.assertGreater(a05["before"]["median"], 12.0)
        self.assertLess(a05["after"]["median"], 3.0)
        self.assertEqual(a05["before"]["frames"], a05["after"]["frames"])
        self.assertIn("runs", self.report)

    def test_deterministic(self):
        again = balance_layer.layer(MODEL, self.motion).motion
        self.assertEqual(vmd.dumps(again), vmd.dumps(self.out))


class ShortStepTest(unittest.TestCase):
    def test_brief_step_moves_part_way_only(self):
        """a 0.2 s step cannot carry the body all the way over (the added acceleration is bounded); it goes part way"""
        last = 89
        motion = dance(last=last, left_lifts=[(40, 43, 44, 47, 1.0)])
        out = balance_layer.layer(MODEL, motion).motion
        shift = centre_offsets(motion, out, last)
        far = np.abs(shift[:, 0]).max() * CM
        self.assertGreater(far, 1.0)                          # it does lean onto the standing foot
        self.assertLess(far, 12.0)                            # but not the whole 17 cm in a fifth of a second
        lean = np.flatnonzero(np.abs(shift[:, 0]) * CM > 0.5)
        self.assertGreater(lean[0], 41 - 20)                  # and not for a second around it
        self.assertLess(lean[-1], 46 + 25)


def world(motion, names, last):
    """per name, the world positions [F, 3] (units) and rotations [F, 4] of mmd_cli.fk"""
    track = fk.world_track(MODEL, motion, names, 0, last)
    return {n: (np.array([p for p, _ in track[n]]), np.array([q for _, q in track[n]])) for n in names}


def heel_kick(last=119):
    """standing on the right foot, 14 cm behind the left and near the middle; the left heel kicked up behind the hip
    from 0.5 s to 3 s (the knee folded 155 degrees, as at 195 s of the MV): the layer moves the body back over the right
    foot, towards the kicked heel (left in the world, the heel would fold the knee to 165 degrees)"""
    motion = dance(last=last)
    left = []
    for f in range(last + 1):
        s = min(smooth((f - 15) / 20.0), 1.0 - smooth((f - 70) / 20.0))
        a = math.radians(-90.0) * s
        left.append(key("左足ＩＫ", f, (-0.12 * s, 7.71 * s, 1.44 * s), q=(math.sin(a / 2), 0.0, 0.0, math.cos(a / 2))))
    right = [key("右足ＩＫ", f, (0.8, 0.0, 1.8)) for f in range(last + 1)]
    motion.bones = [k for k in motion.bones if k.name not in ("左足ＩＫ", "右足ＩＫ")] + left + right
    return motion


def fast_kick(last=119):
    """as at 195 s of the MV: standing on the right foot (14 cm behind), the left foot hovering 3 cm up from 0.7 s to
    2.3 s, kicked up behind (knee 140 degrees) in 0.1 s at 1.7 s and down again by 1.9 s: faster than the carry comes in"""
    motion = dance(last=last)
    left = []
    for f in range(last + 1):
        h = 0.375 * min(smooth((f - 20) / 4.0), 1.0 - smooth((f - 70) / 4.0))
        k = min(smooth((f - 50) / 3.0), 1.0 - smooth((f - 55) / 3.0))
        a = math.radians(-90.0) * k
        left.append(key("左足ＩＫ", f, (-0.12 * k, max(h, 7.71 * k), 2.63 * k), q=(math.sin(a / 2), 0.0, 0.0, math.cos(a / 2))))
    right = [key("右足ＩＫ", f, (0.8, 0.0, 1.8)) for f in range(last + 1)]
    motion.bones = [k for k in motion.bones if k.name not in ("左足ＩＫ", "右足ＩＫ")] + left + right
    return motion


class FastKickTest(unittest.TestCase):
    def test_lifted_knee_folds_at_most_five_degrees_more(self):
        """the carry comes in over about 0.4 s, the kick takes 0.1 s: the knee's bound keeps the kicked leg's shape
        (at most LIFT_FOLD_DEG past the dance) while the body still goes over the standing foot"""
        motion = fast_kick()
        before = balance_layer.Body(MODEL, motion)
        out = balance_layer.layer(MODEL, motion).motion
        after = balance_layer.Body(MODEL, out)
        kb, ka = before.knee_flexion("左"), after.knee_flexion("左")
        lifted = before.height("左") >= balance_layer.SUPPORT_H
        self.assertGreater(kb.max(), 135.0)                                       # the fixture: a deep, fast fold
        self.assertLessEqual(float((ka - kb)[lifted].max()), balance_layer.LIFT_FOLD_DEG + 0.5)
        shift = centre_offsets(motion, out, 119)
        self.assertGreater(np.linalg.norm(shift[30:45, [0, 2]], axis=1).max() * CM, 4.0)   # it still moves the body


class CarryTest(unittest.TestCase):
    """a lifted foot goes with the body: its foot IK moves on the floor plane by the shift of センター (its height and
    turn as the dance had them); on the floor it stays where it was traced"""

    @classmethod
    def setUpClass(cls):
        cls.last = 119
        cls.motion = heel_kick(cls.last)
        cls.result = balance_layer.layer(MODEL, cls.motion)
        cls.out = cls.result.motion
        names = ["センター", "左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ"]
        cls.before = world(cls.motion, names, cls.last)
        cls.after = world(cls.out, names, cls.last)

    def test_kicked_foot_moves_with_the_body(self):
        centre = self.after["センター"][0] - self.before["センター"][0]
        foot = self.after["左足ＩＫ"][0] - self.before["左足ＩＫ"][0]
        self.assertGreater(np.linalg.norm(centre[45:60, [0, 2]], axis=1).min() * CM, 5.0)        # the body went back
        np.testing.assert_allclose(foot[45:60][:, [0, 2]], centre[45:60][:, [0, 2]], atol=1e-4)  # the heel with it
        np.testing.assert_allclose(foot[:, 1], 0.0, atol=1e-6)                                  # its height kept
        np.testing.assert_allclose(self.after["左足ＩＫ"][1], self.before["左足ＩＫ"][1], atol=1e-6)   # its turn kept
        toe = self.after["左つま先ＩＫ"][0] - self.before["左つま先ＩＫ"][0]
        np.testing.assert_allclose(toe, foot, atol=1e-6)

    def test_feet_on_the_floor_stay(self):
        body = balance_layer.Body(MODEL, self.motion)
        on = body.height("左") < balance_layer.SUPPORT_H
        self.assertTrue(on[:10].all() and on[-10:].all())
        foot = self.after["左足ＩＫ"][0] - self.before["左足ＩＫ"][0]
        np.testing.assert_allclose(foot[on], 0.0, atol=1e-6)
        np.testing.assert_allclose(self.after["右足ＩＫ"][0], self.before["右足ＩＫ"][0], atol=1e-6)

    def test_carry_is_smooth(self):
        """the carry does not move the foot more abruptly than the dance itself swings it"""
        for motion, out in ((self.motion, self.out), (dance(last=119, left_lifts=LIFT_RIGHT_STANDS), None)):
            out = out or balance_layer.layer(MODEL, motion).motion
            before, after = world(motion, ["左足ＩＫ"], 119)["左足ＩＫ"][0], world(out, ["左足ＩＫ"], 119)["左足ＩＫ"][0]
            carry = after - before
            acc = np.linalg.norm(carry[2:] - 2 * carry[1:-1] + carry[:-2], axis=1)
            own = np.linalg.norm(before[2:] - 2 * before[1:-1] + before[:-2], axis=1)
            self.assertGreater(np.abs(carry).max() * CM, 5.0)
            self.assertLess(acc.max(), 0.75 * own.max())

    def test_kicked_knee_not_folded_past_its_range(self):
        """the knee of the kicked leg stays within 159 degrees (the reference range's upper proposal; left in the
        world, the heel would come nearer the hip and the knee fold to 165)"""
        kb = balance_layer.Body(MODEL, self.motion).knee_flexion("左")
        ka = balance_layer.Body(MODEL, self.out).knee_flexion("左")
        self.assertGreater(kb.max(), 150.0)                                  # the fixture: a deep fold
        self.assertLessEqual(ka.max(), max(balance_layer.KNEE_FLEXION_DEG[1], kb.max()) + 0.5)

    def test_knee_bound_holds_without_the_carry(self):
        """the knee's bound by itself (it guards the frames where the carry is still coming in): with no carry at all
        the shift stops short of folding the kicked knee past 159 degrees"""
        with mock.patch.object(balance_layer, "carry_factor", lambda low, p: np.zeros_like(low)):
            out = balance_layer.layer(MODEL, self.motion).motion
        kb = balance_layer.Body(MODEL, self.motion).knee_flexion("左")
        ka = balance_layer.Body(MODEL, out).knee_flexion("左")
        self.assertLessEqual(ka.max(), max(balance_layer.KNEE_FLEXION_DEG[1], kb.max()) + 0.5)
        shift = centre_offsets(self.motion, out, self.last)
        self.assertGreater(np.linalg.norm(shift[45:60, [0, 2]], axis=1).max() * CM, 3.0)     # it still moves

    def test_report_names_the_carry(self):
        carry = self.result.report["feet_carry"]
        self.assertGreater(carry["左"]["frames"], 20)
        self.assertEqual(carry["右"]["frames"], 0)
        self.assertLess(carry["左"]["on_floor_cm_max"], 1e-4)
        self.assertTrue(self.result.report["untouched"]["identical"])


class SolverTest(unittest.TestCase):
    def test_bounds_met_without_a_kink_when_the_solver_stops_early(self):
        """the solver stopped after 40 rounds, far from converged, with a disc that narrows for 6 frames: the shift is
        still inside every disc, and the curve is not folded to get there (a per-frame fix after the solve made the
        review's 59.23 s kink, 3.57 m/s^2; here it would be 27 m/s^2)"""
        F = 90
        w = np.zeros(F)
        w[30:61] = 1.0
        d = np.zeros((F, 2))
        d[30:61, 0] = 0.2
        r = np.full(F, 0.13)
        r[45:51] = 0.10
        discs = [(np.zeros((F, 2)), r)]
        y, info = balance_layer.solve_shift(w, d, np.ones(F), discs, [], 1.0, 0.1, 0.02, 0.5, iters=40)
        self.assertTrue(np.all(np.linalg.norm(y, axis=1) <= r + 1e-9))
        self.assertGreater(np.linalg.norm(y, axis=1).max(), 0.08)              # it does move
        acc = np.linalg.norm(y[2:] - 2 * y[1:-1] + y[:-2], axis=1) * FPS * FPS
        self.assertLess(acc.max(), 2.0)

    def test_drop_meets_its_need_without_a_kink_when_the_solver_stops_early(self):
        """the hips' drop after 10 rounds: never under its need, and not folded to get there (here 1.9 m/s^2 with
        the per-frame fix; the bound is 0.5)"""
        F = 90
        need = np.zeros(F)
        need[40:46] = 0.015
        y, info = balance_layer.solve_drop(need, 0.5, 0.1, iters=10)
        self.assertTrue(np.all(y >= need - 1e-12))
        acc = np.abs(y[2:] - 2 * y[1:-1] + y[:-2]) * FPS * FPS
        self.assertLess(acc.max(), 1.0)


class TransferStepTest(unittest.TestCase):
    def test_step_that_travels_to_the_next_foot_is_not_pulled_back(self):
        """the body travels from the right foot to the left foot's new place (50 cm/s) while the left foot is in the air
        for 0.37 s and lands 20 cm further out: a step that falls onto the next foot (Hof's XcoM past half the way to
        where the foot lands, Hof 2008); people do not hold the body back over the foot they leave"""
        last = 119
        motion = dance(last=last)
        left = []
        for f in range(last + 1):
            x = 1.0 + 2.5 * smooth((f - 40) / 12.0)
            y = 2.0 * min(smooth((f - 40) / 4.0), 1.0 - smooth((f - 48) / 4.0))
            left.append(key("左足ＩＫ", f, (x, y, 0.0)))
        travel = [key("センター", f, (-0.9 + 2.9 * smooth((f - 36) / 20.0), -0.6, 0.0)) for f in range(last + 1)]
        motion.bones = [k for k in motion.bones if k.name not in ("左足ＩＫ", "センター")] + left + travel
        result = balance_layer.layer(MODEL, motion)
        shift = centre_offsets(motion, result.motion, last)
        back = -shift[30:60, 0] * CM                         # towards the right (standing) foot
        self.assertLess(back.max(), 1.0)
        kinds = {r["kind"] for r in result.report["runs"]}
        self.assertIn("transfer", kinds)


def xcom_margin(body, stance, land):
    """the margin of stability at frame `land` (cm; Hof et al. 2005): the landing foot's outer edge along the step (from the
    stance foot's centre towards the landing foot's; the sole's half width 4.65 cm, a step to the side) minus the
    extrapolated centre of mass there (COM + v / w0, v by central differences, w0 = sqrt(g / COM height))"""
    other = "右" if stance == "左" else "左"
    com = body.com()
    here = 0.5 * (body.ankle(stance)[land] + body.toe(stance)[land])[[0, 2]]
    there = 0.5 * (body.ankle(other)[land] + body.toe(other)[land])[[0, 2]]
    u = (there - here) / np.linalg.norm(there - here)
    v = (com[land + 1, [0, 2]] - com[land - 1, [0, 2]]) * FPS / 2.0
    w0 = math.sqrt(9.81 / (com[land, 1] * 0.08))
    xcom = com[land, [0, 2]] + v / w0
    return float((there - here) @ u + 4.65 / CM - (xcom - here) @ u) * CM


def first_landing(motion, foot="左"):
    """the first frame the foot supports again after it was up (1.6 cm) in the first half of the dance"""
    sup = balance_layer.Body(MODEL, motion).height(foot) * CM < 1.6
    up = np.flatnonzero(~sup)
    up = up[up < 60]
    return int(up[-1] + 1)


def swing_onto_the_landing_foot(last=119):
    """the left foot up 10 cm for half a second (the right one stands), the body setting off towards the left foot as it
    lands (36 cm/s), then the right foot up and the left one holding: the dance's landing catches the body (the margin
    of stability 3.6 cm); held over the right foot and swung over to the left one, the body would come in too fast"""
    motion = dance(last=last)
    left = foot_track("左足ＩＫ", last, (1.0, 0.0, 0.0), [(35, 39, 48, 52, 1.25)])
    right = foot_track("右足ＩＫ", last, (-1.0, 0.0, 0.0), [(56, 60, 95, 99, 1.25)])
    travel = [key("センター", f, (1.8 * smooth((f - 44) / 14.0), -0.6, 0.0)) for f in range(last + 1)]
    motion.bones = [k for k in motion.bones if k.name not in ("左足ＩＫ", "右足ＩＫ", "センター")] + left + right + travel
    return motion


def falling_step(last=119):
    """standing on the right foot, the left foot steps 16 cm up and lands where it was while the body travels 29 cm
    towards it (up to 52 cm/s): the XcoM at the landing is 5 cm past the left foot's outer edge (the dance's landing does
    not catch the body); then the right foot lifts and the left one holds the body alone"""
    motion = dance(last=last)
    left = []
    for f in range(last + 1):
        y = 2.0 * min(smooth((f - 40) / 4.0), 1.0 - smooth((f - 48) / 4.0))
        left.append(key("左足ＩＫ", f, (1.0, y, 0.0)))
    right = foot_track("右足ＩＫ", last, (-1.0, 0.0, 0.0), [(56, 62, 90, 96, 2.0)])
    travel = [key("センター", f, (-0.9 + 3.6 * smooth((f - 36) / 20.0), -0.6, 0.0)) for f in range(last + 1)]
    motion.bones = [k for k in motion.bones if k.name not in ("左足ＩＫ", "右足ＩＫ", "センター")] + left + right + travel
    return motion


class CatchTest(unittest.TestCase):
    """a foot that lands catches the body (Hof et al. 2005, Hof 2008): at the landing the extrapolated centre of mass
    (XcoM = COM + v / w0) is not past the landing foot's outer edge along the step (the margin of stability >= 0)"""

    def test_swing_over_to_the_landing_foot_keeps_the_catch(self):
        """the layer holds the body over the right foot while the left one is up and then takes it over to the left one,
        which stands alone next: it must not throw the XcoM past the left foot as it lands (the static pulls of the two
        runs made it -3.3 cm here; the dance's own margin is +3.6 cm)"""
        motion = swing_onto_the_landing_foot()
        land = first_landing(motion)
        result = balance_layer.layer(MODEL, motion)
        before = xcom_margin(balance_layer.Body(MODEL, motion), "右", land)
        after = xcom_margin(balance_layer.Body(MODEL, result.motion), "右", land)
        self.assertGreater(before, 2.0)                                       # the fixture: the dance catches
        self.assertGreater(after, -0.5)
        shift = centre_offsets(motion, result.motion, 119)
        self.assertGreater(-shift[40:47, 0].min() * CM, 4.0)                 # still over the right foot while up

    def test_landing_that_does_not_catch_is_held_back(self):
        """the dance's left foot lands 5 cm short of catching the body and then holds it alone: the layer holds the body
        back on the way so the left foot catches it (a step whose next foot is placed beyond the XcoM, Hof 2008)"""
        motion = falling_step()
        land = first_landing(motion)
        result = balance_layer.layer(MODEL, motion)
        before = xcom_margin(balance_layer.Body(MODEL, motion), "右", land)
        after = xcom_margin(balance_layer.Body(MODEL, result.motion), "右", land)
        self.assertLess(before, -4.0)                                         # the fixture: the dance does not catch
        self.assertGreater(after, -0.5)
        # the feet stay where the dance put them (the foot that lands is not moved out to catch the body)
        for s in ("左", "右"):
            b = world(motion, [s + "足ＩＫ"], 119)[s + "足ＩＫ"][0]
            a = world(result.motion, [s + "足ＩＫ"], 119)[s + "足ＩＫ"][0]
            sup = balance_layer.Body(MODEL, motion).height(s) < balance_layer.SUPPORT_H
            np.testing.assert_allclose(a[sup], b[sup], atol=1e-6)

    def test_report_names_the_landings(self):
        motion = falling_step()
        land = first_landing(motion)
        rep = balance_layer.layer(MODEL, motion).report["catch"]
        row = [r for r in rep["landings"] if r["frame"] == land][0]
        self.assertEqual(row["stance"], "右")
        self.assertLess(row["margin_cm"][0], -4.0)
        self.assertGreater(row["margin_cm"][1], -0.5)
        self.assertGreaterEqual(rep["summary"]["before_under_0"], 1)
        self.assertEqual(rep["summary"]["newly_under_0"], 0)


class ReachTest(unittest.TestCase):
    def test_wide_stance_low_foot_stops_at_the_reach(self):
        """feet 70 cm apart, the left foot only 6 cm up: the body cannot get over the right foot with the left leg still
        reaching its foot; the layer goes as far as the leg allows and says so"""
        last = 119
        motion = dance(last=last, spread=3.3, centre=(0.0, -1.2, 0.0), left_lifts=[(40, 50, 80, 90, 0.75)])
        result = balance_layer.layer(MODEL, motion)
        after = balance_layer.Body(MODEL, result.motion)
        for s in ("左", "右"):
            reach = np.linalg.norm(after.ankle(s) - after.hip(s), axis=1)
            before = np.linalg.norm(balance_layer.Body(MODEL, motion).ankle(s) - balance_layer.Body(MODEL, motion).hip(s), axis=1)
            # 1.5 cm of slack kept (MMD's IK falls short on a leg nearer full stretch; with 0.3 cm the left leg goes there)
            room = np.maximum(after.leg_length(s) - balance_layer.REACH_TOL_CM / CM, before)
            self.assertTrue(np.all(reach <= room + 1e-6), s)
        self.assertEqual(balance_layer.REACH_TOL_CM, 1.5)
        short = [r for r in result.report["runs"] if r["short_of_target_cm"] > 3.0]
        self.assertTrue(short, "the run that the reach stops must be named")
        self.assertIn("reach", short[0]["limited_by"])


class MmdIkCheckTest(unittest.TestCase):
    """with MMD's IK at hand (--mmd-ik: the feet layer's tools/leg_ik.py), the layer solves its result again with it and
    holds back its change where a foot on the floor would newly fall short of its IK target (over 4 mm, and 1 mm more
    than in the dance).  Here a stand-in IK that falls short on legs with under 2.5 cm of slack"""

    @staticmethod
    def stand_in(motion):
        body = balance_layer.Body(MODEL, motion)
        return {s: np.maximum(0.0, body.reach(s) - (body.leg_length(s) - 2.5 / CM)) for s in ("左", "右")}

    def new_misses(self, before, after, motion):
        sup = {s: balance_layer.Body(MODEL, motion).height(s) < balance_layer.SUPPORT_H for s in ("左", "右")}
        return sum(int(np.sum(sup[s] & (after[s] > 0.05) & (after[s] > before[s] + 0.0125))) for s in ("左", "右"))

    def test_held_back_where_the_ik_would_fall_short(self):
        last = 119
        motion = dance(last=last, spread=3.3, centre=(0.0, -1.2, 0.0), left_lifts=[(40, 50, 80, 90, 0.75)])
        before = self.stand_in(motion)
        plain = balance_layer.layer(MODEL, motion).motion
        self.assertGreater(self.new_misses(before, self.stand_in(plain), motion), 0)       # the fixture: it would miss
        result = balance_layer.layer(MODEL, motion, ik_check=self.stand_in)
        self.assertEqual(self.new_misses(before, self.stand_in(result.motion), motion), 0)
        rep = result.report["mmd_ik"]
        self.assertTrue(rep["checked"])
        self.assertGreaterEqual(rep["rounds"], 1)
        self.assertEqual(rep["remaining"], 0)
        shift = centre_offsets(motion, result.motion, last)
        self.assertGreater(np.abs(shift[:, 0]).max() * CM, 2.0)                        # it still moves the body

    def test_report_says_when_not_checked(self):
        result = balance_layer.layer(MODEL, dance(last=119, left_lifts=LIFT_RIGHT_STANDS))
        self.assertFalse(result.report["mmd_ik"]["checked"])


class RangeTest(unittest.TestCase):
    def test_standing_hip_kept_in_its_range(self):
        """下半身 tilted 22 degrees down on the lifted side: the standing hip is already adducted about 20 degrees, and
        carrying the body over the foot would take it past the reference range (22, the upper proposal); the layer
        stops at the range and says so"""
        last = 119
        motion = dance(last=last, spread=0.5, left_lifts=LIFT_RIGHT_STANDS, pelvis_roll_deg=-22.0)
        result = balance_layer.layer(MODEL, motion)
        before = balance_layer.Body(MODEL, motion).hip_adduction("右")
        after = balance_layer.Body(MODEL, result.motion).hip_adduction("右")
        self.assertGreater(before[60], 15.0)                                  # the fixture: adducted already
        self.assertTrue(np.all(after <= np.maximum(22.0, before) + 1.5), float(np.max(after - np.maximum(22.0, before))))
        run = [r for r in result.report["runs"] if r["first"] <= 60 <= r["last"]][0]
        self.assertIn("hip range", run["limited_by"])

    def test_thigh_kept_in_its_range(self):
        """the range is the thigh's (the hip to the knee), as the report measures it, not the hip-to-ankle line's: the
        standing foot turned in 30 degrees and the pelvis tilted 20 degrees, the knee points in and the thigh is 2 degrees
        more adducted than the line; carrying the body over the foot must stop when the thigh is at 22 degrees (the line
        alone let it go to 23.9)"""
        last = 119
        motion = dance(last=last, spread=0.5, left_lifts=LIFT_RIGHT_STANDS, pelvis_roll_deg=-20.0)
        h = math.radians(-30.0) / 2.0
        for k in motion.bones:
            if k.name == "右足ＩＫ":
                k.rotation = fk.stored((0.0, math.sin(h), 0.0, math.cos(h)))
        result = balance_layer.layer(MODEL, motion)
        before = balance_layer.Body(MODEL, motion).hip_adduction("右")
        after = balance_layer.Body(MODEL, result.motion).hip_adduction("右")
        self.assertTrue(19.0 < before[60] < 22.0)                             # the fixture: near the range, inside it
        self.assertLessEqual(float(np.max(after - np.maximum(22.0, before))), 0.3)
        shift = centre_offsets(motion, result.motion, last)
        self.assertGreater(-shift[55:80, 0].min() * CM, 0.5)                 # it still goes towards the right foot
        self.assertEqual(result.report["hip"]["over_22_newly_R"], 0)

    def test_straight_legs_do_not_buckle(self):
        """straight legs (センター at its rest height): the hips may go down for a leg to reach its foot only as far as
        the other leg on the floor bends 12 degrees; on one foot the standing leg stays straight (its hip goes round
        the ankle) and the body still gets over it"""
        last = 119
        motion = dance(last=last, spread=0.3, centre=(0.0, 0.0, 0.0), left_lifts=LIFT_RIGHT_STANDS)
        result = balance_layer.layer(MODEL, motion)
        before, after = balance_layer.Body(MODEL, motion), balance_layer.Body(MODEL, result.motion)
        for s in ("左", "右"):
            on = before.height(s) < balance_layer.SUPPORT_H
            gain = (after.knee_flexion(s) - before.knee_flexion(s))[on]
            self.assertLess(gain.max(), balance_layer.KNEE_GIVE_DEG + 2.0, s)
        heel, toe = before.sole("右")
        line_x = 0.5 * (heel[:, 0] + toe[:, 0])
        self.assertLess(np.abs(after.com()[65:80, 0] - line_x[65:80]).max() * CM, 3.0)

    def test_pointed_foot_keeps_the_body_continuous(self):
        """the lifted foot points down and on back past the vertical: the knee's side does not flip, the COM does not
        jump"""
        last = 119
        motion = dance(last=last, left_lifts=LIFT_RIGHT_STANDS, left_point=(45, 75, -80.0))
        com = balance_layer.Body(MODEL, motion).com()
        step = np.linalg.norm(np.diff(com, axis=0), axis=1) * CM
        self.assertLess(step.max(), 0.3)


    def test_heel_to_the_hip_keeps_the_knee_continuous(self):
        """the left heel brought up behind to hip height, the toe pointing down and back (as at 133.7 s of the MV): the
        hip-to-ankle line points straight back, against the pelvis's front, so the knee's side must come from the
        hinge (down), not from the pelvis's front (undefined there); the COM's acceleration stays smooth"""
        last = 119
        motion = dance(last=last, spread=0.0)
        fold = []
        for f in range(last + 1):
            s = min(smooth((f - 40) / 20.0), 1.0 - smooth((f - 80) / 20.0))
            a = math.radians(-90.0) * s
            fold.append(key("左足ＩＫ", f, (0.08 * s, 8.25 * s, 2.03 * s), q=(math.sin(a / 2), 0.0, 0.0, math.cos(a / 2))))
        motion.bones = [k for k in motion.bones if k.name != "左足ＩＫ"] + fold
        body = balance_layer.Body(MODEL, motion)
        u = body.ankle("左") - body.hip("左")
        u /= np.linalg.norm(u, axis=1, keepdims=True)
        self.assertGreater(u[60, 2], 0.95)                                    # the fixture: the line points back
        com = body.com()
        acc = np.linalg.norm(com[2:] - 2 * com[1:-1] + com[:-2], axis=1) * CM
        self.assertLess(acc.max(), 0.3)
        self.assertLess(body.knee("左")[60, 1], body.hip("左")[60, 1] - 2.0)   # the knee hangs below the hip


class LandingTest(unittest.TestCase):
    def test_knee_gives_on_a_landing_that_takes_the_weight(self):
        """the left foot steps (up and down); as it lands the right foot lifts: the left leg takes the weight and its knee
        bends more within 0.15 s, then comes back"""
        last = 149
        motion = dance(last=last, left_lifts=[(30, 36, 44, 50, 1.5)], right_lifts=[(52, 60, 100, 108, 2.0)])
        result = balance_layer.layer(MODEL, motion)
        before = balance_layer.Body(MODEL, motion).knee_flexion("左")
        after = balance_layer.Body(MODEL, result.motion).knee_flexion("左")
        land = 50
        gain_before = before[land:land + 5].max() - before[land]
        gain_after = after[land:land + 5].max() - after[land]
        self.assertGreater(gain_after - gain_before, 6.0)
        self.assertLess(abs((after - before)[land + 20]), 3.0)      # back within 0.7 s
        self.assertTrue(result.report["landings"]["dipped"] >= 1)

    def test_two_landings_close_together_stay_smooth(self):
        """a small hop: the left foot lands, the right 8 frames later while the left's dip is on its way back, then the
        left lifts: both landings take weight; their dips add up smoothly (the larger of the two bumps has a corner
        where they cross: 0.81 cm per frame^2 here)"""
        last = 119
        motion = dance(last=last, left_lifts=[(36, 41, 45, 50, 1.0), (62, 68, 90, 96, 2.0)],
                       right_lifts=[(36, 41, 52, 58, 1.0)])
        result = balance_layer.layer(MODEL, motion)
        self.assertGreaterEqual(result.report["landings"]["dipped"], 2)
        down = centre_offsets(motion, result.motion, last)[:, 1] * CM
        acc = np.abs(down[2:] - 2 * down[1:-1] + down[:-2])
        self.assertLess(acc.max(), 0.65)                         # cm per frame^2: a 2 cm bump alone reaches 0.65

    def test_toe_tap_gets_no_dip(self):
        """the left foot taps the floor and lifts again while the right foot stays down: no weight to take"""
        last = 119
        motion = dance(last=last, left_lifts=[(20, 26, 40, 46, 1.5), (49, 55, 70, 76, 1.5)])
        result = balance_layer.layer(MODEL, motion)
        self.assertEqual(result.report["landings"]["dipped"], 0)


def pelvis_down_acc(motion, last):
    """the pelvis's (下半身) downward acceleration per frame (model units/s^2, + down; 30 fps second differences of its
    world height)"""
    y = world(motion, ["下半身"], last)["下半身"][0][:, 1]
    a = np.zeros(len(y))
    a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS * FPS
    return a


def bounce_on_landing(last=149):
    """the landing of LandingTest, with the dance's own bounce on it: センター rises 4 cm and turns down again at its top
    in a frame (a tent from 0.43 to 0.57 s around 1.6 s: 150 units/s^2 down at the top, over MMD's gravity, as the
    traced dance does at 213.3 s)"""
    motion = dance(last=last, left_lifts=[(30, 36, 44, 50, 1.5)], right_lifts=[(52, 60, 100, 108, 2.0)])
    centre = [key("センター", f, (0.0, -0.6 + 0.5 * max(0.0, 1.0 - abs(f - 48) / 3.0), 0.0)) for f in range(last + 1)]
    motion.bones = [k for k in motion.bones if k.name != "センター"] + centre
    return motion


def bouncing(last=119):
    """both feet on the floor, センター bouncing between the beats (every second): up 4 cm and down again in 0.27 s (a
    tent of 8 frames), its top turned in a frame (225 units/s^2 down there, past MMD's gravity, as the traced dance
    does at 213.3 s); down on the beats"""
    motion = dance(last=last)
    centre = []
    for f in range(last + 1):
        h = 0.5 * max(0.0, 1.0 - abs((f % 30) - 15) / 4.0)
        centre.append(key("センター", f, (0.0, -1.1 + h, 0.0)))
    motion.bones = [k for k in motion.bones if k.name != "センター"] + centre
    return motion


class VerticalTest(unittest.TestCase):
    """MMD's gravity is 98 units/s^2 (saba, three.js, MMDAgent-EX and babylon-mmd: 9.8 x 10): a waist that goes down
    faster than that throws the skirt up, and a body held up by the floor cannot fall faster than gravity.  The layer
    keeps the pelvis's downward acceleration (the dance's and its own) under DOWN_ACC_MAX by lowering the body only
    (the lowest points stay where and when the dance has them, on the beat; the fall starts earlier)"""

    @classmethod
    def setUpClass(cls):
        cls.last = 119
        cls.motion = bouncing(cls.last)
        cls.result = balance_layer.layer(MODEL, cls.motion)
        cls.y0 = world(cls.motion, ["下半身"], cls.last)["下半身"][0][:, 1]
        cls.y1 = world(cls.result.motion, ["下半身"], cls.last)["下半身"][0][:, 1]

    def test_bound_under_mmd_gravity(self):
        self.assertLess(balance_layer.DOWN_ACC_MAX, 98.0 * 0.85)
        self.assertGreater(pelvis_down_acc(self.motion, self.last).max(), 98.0)          # the fixture is past g
        self.assertLessEqual(pelvis_down_acc(self.result.motion, self.last).max(), balance_layer.DOWN_ACC_MAX + 0.5)

    def test_lowered_only_and_the_lows_kept(self):
        self.assertLessEqual(float(np.max(self.y1 - self.y0)), 1e-6)                        # never raised
        lows = [f for f in range(1, self.last) if self.y0[f] < self.y0[f - 1] and self.y0[f] <= self.y0[f + 1]]
        self.assertTrue(lows)
        for f in lows:
            self.assertLess(abs(self.y1[f] - self.y0[f]) * CM, 0.05, f)                    # where and when
        self.assertGreater(float(np.max(self.y0 - self.y1)) * CM, 0.5)                     # the tops rounded

    def test_fall_starts_earlier(self):
        """between two beats the top comes no later than the dance's, and lower"""
        for a in (30, 60):
            top0 = a + int(np.argmax(self.y0[a:a + 30]))
            top1 = a + int(np.argmax(self.y1[a:a + 30]))
            self.assertLessEqual(top1, top0)
            self.assertLess(self.y1[top1], self.y0[top0])

    def test_feet_stay(self):
        self.assertEqual(others(self.motion, skip=("センター",)), others(self.result.motion, skip=("センター",)))

    def test_landing_dip_under_the_bound(self):
        last = 149
        motion = dance(last=last, left_lifts=[(30, 36, 44, 50, 1.5)], right_lifts=[(52, 60, 100, 108, 2.0)])
        result = balance_layer.layer(MODEL, motion)
        self.assertLessEqual(pelvis_down_acc(result.motion, last).max(), balance_layer.DOWN_ACC_MAX + 0.5)
        self.assertGreaterEqual(result.report["landings"]["dipped"], 1)

    def test_report_names_the_vertical(self):
        rep = self.result.report["vertical"]
        self.assertEqual(rep["bound_units_s2"], balance_layer.DOWN_ACC_MAX)
        self.assertGreater(rep["pelvis"]["dance_max"], 98.0)
        self.assertLessEqual(rep["pelvis"]["after_max"], balance_layer.DOWN_ACC_MAX + 0.5)
        self.assertGreater(rep["lowered_cm"]["max"], 0.5)
        self.assertGreater(rep["frames_lowered"], 0)


class NothingToDoTest(unittest.TestCase):
    def test_both_feet_down_gives_the_input_back(self):
        motion = dance(last=59)
        result = balance_layer.layer(MODEL, motion)
        self.assertEqual(vmd.dumps(result.motion), vmd.dumps(motion))

    def test_already_balanced_is_left_alone(self):
        """the dance itself puts the body over the right foot before the left lifts"""
        last = 119
        over = [key("センター", f, (-2.5 * min(smooth((f - 10) / 25.0), 1.0 - smooth((f - 95) / 20.0)), -0.6, 0.0))
                for f in range(last + 1)]
        motion = dance(last=last, left_lifts=LIFT_RIGHT_STANDS, centre_keys=over)
        body = balance_layer.Body(MODEL, motion)
        heel, toe = body.sole("右")
        line_x = 0.5 * (heel[:, 0] + toe[:, 0])
        self.assertLess(np.abs(body.com()[36:95, 0] - line_x[36:95]).max() * CM, 1.0)    # the fixture is balanced
        result = balance_layer.layer(MODEL, motion)
        shift = centre_offsets(motion, result.motion, last)
        self.assertLess(np.abs(shift).max() * CM, 1.0)


class ReviewTest(unittest.TestCase):
    """the review's tests (2026-10-14; each fails on a copy broken one way: no short-step discount, a hovering foot's run
    pulled, the pull not weakened by the other foot's height, センター's parent turn applied the wrong way round)"""

    def test_hovering_foot_in_a_wide_stance_leaves_the_body(self):
        """feet 40 cm apart, the left foot only 3 cm up for a second: the trace's feet hover 0.4-4 cm even on two feet
        (a05), a05's single support needs 5 cm, the MV shows no lifted foot: the body is not carried over the right foot"""
        last = 119
        motion = dance(last=last, spread=1.6, centre=(0.0, -0.8, 0.0), left_lifts=[(40, 50, 80, 90, 0.375)])
        out = balance_layer.layer(MODEL, motion).motion
        shift = centre_offsets(motion, out, last)
        self.assertLess(np.linalg.norm(shift[:, [0, 2]], axis=1).max() * CM, 1.0)

    def test_brief_step_pull_is_its_share(self):
        """with the acceleration bound lifted, a 0.2 s step is still pulled only its share of the way (the inverted
        pendulum's drift, about a quarter of 17 cm), not all the way"""
        last = 89
        motion = dance(last=last, left_lifts=[(40, 43, 44, 47, 1.0)])
        out = balance_layer.layer(MODEL, motion, {"acc_max": 30.0}).motion
        far = np.abs(centre_offsets(motion, out, last)[:, 0]).max() * CM
        self.assertGreater(far, 1.0)
        self.assertLess(far, 8.0)

    def test_pull_grows_with_the_other_foot_s_height(self):
        """the plan: in a pulled run the pull's weight follows the other foot's height from 1.6 to 5 cm (half the full
        weight while it is still low), full from 5 cm up; nothing where it never gets 5 cm up"""
        last = 119
        motion = dance(last=last, left_lifts=[(40, 60, 70, 90, 2.5)])            # up slowly over 0.7 s
        body = balance_layer.Body(MODEL, motion)
        plan = balance_layer.support_plan(body, balance_layer.params_default(), body.com())
        low = body.height("左") * CM
        w = plan["w"]
        rising = np.flatnonzero((low > 2.0) & (low < 3.0) & (np.arange(last + 1) < 60))
        self.assertTrue(len(rising))
        self.assertLess(w[rising].max(), 0.75)
        self.assertGreater(w[rising].min(), 0.45)
        self.assertEqual(float(w[(low > 6.0)].min()), 1.0)

    def test_turned_root_still_goes_over_the_standing_foot(self):
        """the whole dance turned 90 degrees by a key on 全ての親: the shift is a world shift, written in センター's
        parent's frame, so the body still goes over the right foot"""
        last = 119
        motion = dance(last=last, left_lifts=LIFT_RIGHT_STANDS)
        h = math.radians(90.0) / 2.0
        motion.bones += [key("全ての親", 0, q=(0.0, math.sin(h), 0.0, math.cos(h))),
                         key("全ての親", last, q=(0.0, math.sin(h), 0.0, math.cos(h)))]
        out = balance_layer.layer(MODEL, motion).motion
        before, after = balance_layer.Body(MODEL, motion), balance_layer.Body(MODEL, out)
        foot = 0.5 * (before.ankle("右") + before.toe("右"))[:, [0, 2]]
        lat_before = np.linalg.norm(before.com()[60:75, [0, 2]] - foot[60:75], axis=1) * CM
        lat_after = np.linalg.norm(after.com()[60:75, [0, 2]] - foot[60:75], axis=1) * CM
        self.assertGreater(lat_before.min(), 12.0)
        self.assertLess(lat_after.max(), 4.0)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.model = os.path.join(self.dir, "m.pmx")
        with open(self.model, "wb") as f:
            f.write(model_bytes())
        self.dance = os.path.join(self.dir, "d.vmd")
        vmd.dump(dance(left_lifts=LIFT_RIGHT_STANDS), self.dance)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_writes_motion_and_report(self):
        out = os.path.join(self.dir, "o.vmd")
        rep = os.path.join(self.dir, "r.json")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, self.model, out, "--report", rep])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out))
        with open(rep, encoding="utf-8") as f:
            report = json.load(f)
        self.assertIn("a05_lateral_cm", report)
        line = json.loads(printed.getvalue().strip().splitlines()[-1])
        self.assertTrue(line["ok"])
        printed.getvalue().encode("cp932")                    # the terminal is cp932

    def test_arrays_for_figures(self):
        """--arrays writes the per-frame curves (the shift, the COM before and after, the pull) for figures and checks"""
        out = os.path.join(self.dir, "o.vmd")
        arr = os.path.join(self.dir, "a.npz")
        with contextlib.redirect_stdout(io.StringIO()):
            code = balance_layer.main([self.dance, self.model, out, "--arrays", arr])
        self.assertEqual(code, 0)
        z = np.load(arr)
        F = fk.last_frame(vmd.load(self.dance)) + 1
        for name in ("shift", "com_before", "com_after", "pull", "drop", "dip"):
            self.assertEqual(len(z[name]), F, name)
        self.assertLess(z["shift"][60, 0], -1.0)                 # the body went over the right foot

    def test_same_path_refused(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, self.model, self.dance])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(printed.getvalue().strip().splitlines()[-1])["ok"])

    def test_model_without_the_feet_refused(self):
        w = Writer(bone=2)
        bare = w.build(name="no feet", bones=[w.bone("センター", flags=NORMAL | TRANSLATE)])
        path = os.path.join(self.dir, "bare.pmx")
        with open(path, "wb") as f:
            f.write(bare)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, path, os.path.join(self.dir, "o.vmd")])
        self.assertEqual(code, 2)
        self.assertIn("足ＩＫ", json.loads(printed.getvalue().strip().splitlines()[-1])["error"]["message"])


# ---- the MV itself ----------------------------------------------------------------------------------

SONG = os.environ.get("BALANCE_SONG")


def song_paths():
    """the MV's inputs named by BALANCE_SONG (a JSON {"model", "dance"} and, for the check with MMD's IK, "leg_ik": the
    feet layer's tools/leg_ik.py): SkipTest, with the reason, when it is not set; a set variable naming files that are not
    there fails instead"""
    if not SONG:
        raise unittest.SkipTest("BALANCE_SONG is not set: it names a JSON of the MV's inputs (model, dance, leg_ik), on "
                                "hinata C:/work/hibikase/stage6/balance/scripts/song_inputs.json")
    with open(SONG, encoding="utf-8") as f:
        paths = json.load(f)
    keys = ("model", "dance") + (("leg_ik",) if "leg_ik" in paths else ())
    missing = ["%s %s" % (k, paths.get(k)) for k in keys if not paths.get(k) or not os.path.isfile(paths[k])]
    if missing:
        raise AssertionError("BALANCE_SONG (%s) names files that are not there: %s" % (SONG, "; ".join(missing)))
    return paths


class SongTest(unittest.TestCase):
    """the MV (BALANCE_SONG), solved with MMD's IK at hand when the JSON names the feet layer's leg_ik"""

    @classmethod
    def setUpClass(cls):
        paths = song_paths()
        cls.model = pmx.load(paths["model"])
        cls.motion = vmd.load(paths["dance"])
        cls.ik = paths.get("leg_ik")
        check = None
        if cls.ik:
            check, _ = balance_layer.mmd_ik_check(cls.ik, paths["model"], fk.last_frame(cls.motion) + 1)
        cls.result = balance_layer.layer(cls.model, cls.motion, ik_check=check)
        cls.report = cls.result.report

    def test_weight_on_the_standing_foot(self):
        a05 = self.report["a05_lateral_cm"]
        self.assertGreater(a05["before"]["median"], 9.0)
        self.assertLess(a05["after"]["median"], a05["before"]["median"] / 2.0)
        self.assertLess(a05["after_holds"]["median"], 3.0)

    def test_feet_untouched_and_smooth(self):
        """no 1-frame jump: the added acceleration of センター stays at its bound on the floor (the solve's curve is
        brought into its bounds smoothly, not frame by frame) and at the landing dip's own (2 cm in 0.13 s: about
        6 m/s^2) upward"""
        self.assertTrue(self.report["untouched"]["identical"])
        c = self.report["centre"]
        self.assertLess(c["added_acc_h_m_s2"]["p99"], balance_layer.ACC_MAX * 1.05)
        self.assertLess(c["added_acc_h_m_s2"]["max"], balance_layer.ACC_MAX * 1.1)
        self.assertLess(c["added_acc_v_m_s2"]["max"], 6.5)

    def test_reach_not_worse(self):
        """no leg loses its slack to its foot IK below 1.5 cm (or below what the dance had): MMD's IK falls short of the
        target on legs nearer full stretch (measured with the feet layer's leg_ik on the MV)"""
        for s in ("L", "R"):
            self.assertEqual(self.report["reach"]["worse_frames_" + s], 0)
            self.assertEqual(self.report["reach"]["slack_taken_frames_" + s], 0)

    def test_no_new_miss_as_mmd_solves_the_legs(self):
        if not self.ik:
            self.skipTest("BALANCE_SONG names no leg_ik (the feet layer's tools/leg_ik.py): MMD's IK is not at hand")
        self.assertTrue(self.report["mmd_ik"]["checked"])
        self.assertEqual(self.report["mmd_ik"]["remaining"], 0)

    def test_lifted_feet_carried_and_knees_in_range(self):
        for s in ("左", "右"):
            carry = self.report["feet_carry"][s]
            self.assertEqual(carry["on_floor_cm_max"], 0.0)
            self.assertEqual(carry["height_cm_max"], 0.0)
            self.assertEqual(self.report["knee"]["over_159_newly_" + {"左": "L", "右": "R"}[s]], 0)
        self.assertGreater(self.report["feet_carry"]["右"]["max_cm"], 5.0)

    def test_hovering_and_travelling_runs_not_pulled(self):
        """the runs whose other foot never gets 5 cm up (the review: 128 of 265) and the steps onto the next foot keep
        the dance's body but for the neighbouring runs' lean coming and going"""
        runs = self.report["runs"]
        hover = [r["shift_cm_max"] for r in runs if r["kind"] == "hover"]
        travel = [r["shift_cm_max"] for r in runs if r["kind"] == "transfer"]
        self.assertGreater(len(hover), 50)
        self.assertGreater(len(travel), 10)
        self.assertLess(float(np.median(hover)), 0.5)
        self.assertLess(float(np.median(travel)), 3.0)


if __name__ == "__main__":
    unittest.main()
