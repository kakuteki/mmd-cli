"""tools/anatomy_layer.py: anatomical joints (a hinge elbow, the twists on the twist bones, the trunk and the neck shared out,
the shoulder girdle's rhythm and the range of motion) baked onto a dance."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, FIXED_AXIS, LOCAL_AXIS, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_TREE = "C:/Users/kaga/Desktop/mmd-cli"           # the main working tree, where the real data lives


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("anatomy_layer", os.path.join(ROOT, "tools", "anatomy_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


anatomy_layer = load_tool()
LAST = 60

# Sour's Rin's rest positions (model units) of the bones the layer reads or writes, the left side; the right side is the
# mirror image.  The elbow helper carries her local axes (read for the elbow's hinge).
LEFT = [("肩P", "上半身2", (0.23, 15.393, -0.222), {}),
        ("肩", "肩P", (0.23, 15.393, -0.222), {}),
        ("肩C", "肩", (0.911, 15.277, -0.248), {"flags": NORMAL | APPEND_ROTATE, "append": ("肩P", -1.0)}),
        ("腕", "肩C", (0.911, 15.277, -0.248), {}),
        ("腕捩", "腕", (1.909, 14.505, -0.259), {"flags": NORMAL | FIXED_AXIS, "axis": (0.7908, -0.6120, -0.0086)}),
        ("ひじ", "腕捩", (2.907, 13.732, -0.27), {}),
        ("ひじ補助", "腕捩", (2.907, 13.732, -0.27),
         {"flags": NORMAL | APPEND_ROTATE | LOCAL_AXIS, "append": ("ひじ", 0.6),
          "local_axes": ((0.2714, -0.9622, -0.0213), (0.0058, -0.0205, 0.9998))}),
        ("手捩", "ひじ", (3.78, 13.071, -0.253), {"flags": NORMAL | FIXED_AXIS, "axis": (0.7970, -0.6038, 0.0151)}),
        ("手首", "手捩", (4.652, 12.41, -0.237), {}),
        ("人指１", "手首", (5.375, 11.884, -0.436), {}), ("人指２", "人指１", (5.64, 11.687, -0.43), {}),
        ("人指３", "人指２", (5.777, 11.554, -0.421), {}),
        ("中指１", "手首", (5.41, 11.935, -0.261), {}), ("中指２", "中指１", (5.714, 11.691, -0.264), {}),
        ("中指３", "中指２", (5.87, 11.538, -0.264), {}),
        ("薬指１", "手首", (5.387, 11.944, -0.1), {}), ("薬指２", "薬指１", (5.664, 11.723, -0.105), {}),
        ("薬指３", "薬指２", (5.795, 11.589, -0.111), {}),
        ("小指１", "手首", (5.332, 11.951, 0.038), {}), ("小指２", "小指１", (5.544, 11.778, 0.03), {}),
        ("小指３", "小指２", (5.659, 11.661, 0.02), {})]


def mirrored(kw):
    out = dict(kw)
    if "axis" in out:
        out["axis"] = (-out["axis"][0], out["axis"][1], out["axis"][2])
    if "local_axes" in out:
        (x, z) = out["local_axes"]
        out["local_axes"] = ((-x[0], x[1], x[2]), (-z[0], z[1], z[2]))
    return out


def model_bytes():
    w = Writer(bone=2)
    bones = [("全ての親", None, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.847, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("腰", "センター", (0.0, 11.726, 0.255), {}),
             ("下半身", "腰", (0.0, 12.225, -0.649), {}),
             ("上半身", "腰", (0.0, 12.225, -0.649), {}),
             ("上半身2", "上半身", (0.0, 13.798, -0.678), {}),
             ("首", "上半身2", (0.0, 15.646, -0.134), {}),
             ("頭", "首", (0.0, 16.243, 0.0), {}),
             ("頭先", "頭", (0.0, 18.766, -0.16), {}),
             ("両目", "頭", (0.0, 17.214, -0.562), {}),
             ("左足ＩＫ", "全ての親", (1.12, 1.745, 0.37), {"flags": NORMAL | TRANSLATE})]
    for side, sx in (("左", 1.0), ("右", -1.0)):
        for name, parent, (x, y, z), kw in LEFT:
            parent = parent if parent in ("上半身2",) else side + parent
            kw = dict(kw) if sx > 0 else mirrored(kw)
            if "append" in kw:
                kw["append"] = (side + kw["append"][0], kw["append"][1])
            bones.append((side + name, parent, (sx * x, y, z), kw))
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"][0]], kw["append"][1])
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-like", bones=built)


MODEL = pmx.loads(model_bytes())


def axis_angle(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


def compose(*qs):
    out = (0.0, 0.0, 0.0, 1.0)
    for q in qs:
        out = fk.multiply(out, q)
    return out


def key(name, frame, q=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0)):
    return vmd.BoneKey(name, frame, tuple(position), fk.stored(tuple(q)))


def untouched_keys(last=LAST):
    return [key("センター", 0, position=(0.0, -0.2, 0.1)), key("センター", 30, position=(0.3, -0.4, 0.1)),
            key("センター", last, position=(0.3, -0.4, 0.1)),
            key("左足ＩＫ", 0, position=(0.1, 0.0, 0.2)), key("左足ＩＫ", last, position=(0.1, 0.0, 0.2)),
            key("下半身", 0, axis_angle((1, 0, 0), 5.0)), key("下半身", last, axis_angle((1, 0, 0), 5.0))]


def odd_elbow_dance(last=LAST, supinate=0.0, shrug=0.0, hyper=False):
    """the left arm raised and swung, its elbow bent sideways and upwards as a ball joint (the trace's habit: the upper arm's
    roll hidden in the elbow), the forearm twisted on 手捩 and 手首 (fix_twist's split), the trunk and the head turned and
    bent on 上半身 and 頭 alone.  supinate adds that many degrees of forearm twist; shrug lifts 左肩 that many degrees;
    hyper bends the elbow backwards and out instead"""
    keys = untouched_keys(last)
    poses = {
        0: dict(arm=axis_angle((0, 0, 1), 10.0), elbow=axis_angle((0.3, 0.2, 1.0), 50.0)),
        20: dict(arm=compose(axis_angle((0, 1, 0), 30.0), axis_angle((0, 0, 1), 45.0)),
                 elbow=axis_angle((0.6, 0.6, 0.5), 80.0)),
        40: dict(arm=compose(axis_angle((0, 1, 0), -20.0), axis_angle((0, 0, 1), 70.0)),
                 elbow=axis_angle((0.0, 0.5, 1.0), 95.0)),
        last: dict(arm=axis_angle((0, 0, 1), 25.0), elbow=axis_angle((0.2, 1.0, 0.4), 60.0)),
    }
    if hyper:
        for p in poses.values():
            p["arm"] = axis_angle((0, 0, 1), -35.0)
            p["elbow"] = axis_angle((-0.6, -0.8, 0.15), 32.0)         # the forearm bent back past straight, a little out
    d_f = (0.7970, -0.6038, 0.0151)
    for f, p in poses.items():
        keys.append(key("左腕", f, p["arm"]))
        keys.append(key("左ひじ", f, p["elbow"]))
        twist = {20: 30.0, 40: 30.0 + supinate}.get(f, 10.0)
        keys.append(key("左手捩", f, axis_angle(d_f, 0.5 * twist)))
        wrist = {0: 15.0, 20: 45.0, 40: -30.0}.get(f, 10.0)
        keys.append(key("左手首", f, compose(axis_angle(d_f, 0.5 * twist), axis_angle((0, 0, 1), wrist))))
        keys.append(key("左中指１", f, axis_angle((0, 0, 1), -20.0)))
        if shrug:
            keys.append(key("左肩", f, axis_angle((0, 0, 1), shrug)))
    for f, deg in ((0, 0.0), (25, 30.0), (last, 10.0)):
        keys.append(key("上半身", f, compose(axis_angle((0, 1, 0), deg), axis_angle((1, 0, 0), deg / 2.0))))
        keys.append(key("頭", f, compose(axis_angle((0, 1, 0), -1.5 * deg), axis_angle((1, 0, 0), deg / 3.0))))
    keys.append(key("右腕", 0, axis_angle((0, 0, 1), -20.0)))
    keys.append(key("右腕", last, axis_angle((0, 0, 1), -20.0)))
    return vmd.Motion(model_name="dancer", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)])


def worlds(motion, names, last=LAST):
    pose = fk.Pose(MODEL, motion, names)
    out = {n: ([], []) for n in names}
    for f in range(last + 1):
        w = pose.at(f)
        for n in names:
            out[n][0].append(w[n][0])
            out[n][1].append(w[n][1])
    return {n: (np.array(p), np.array(r)) for n, (p, r) in out.items()}


def rot_deg(a, b):
    """the angle between two arrays of rotations, degrees"""
    d = np.abs(np.sum(a * b, axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(d, 0.0, 1.0)))


def locals_of(motion, name, last=LAST):
    keys = fk.tracks_of(motion)[name]
    frames = [k.frame for k in keys]
    return np.array([fk.applied(fk.sample(keys, f, frames)[1]) for f in range(last + 1)])


def split_only():
    p = anatomy_layer.default_params()
    p.update(girdle=False, rom=False)
    return p


class SoftLimitTest(unittest.TestCase):
    def test_identity_below_the_start_and_below_the_cap_above_it(self):
        x = np.array([-50.0, 0.0, 89.9, 90.0, 95.0, 120.0, 400.0])
        y = anatomy_layer.soft_limit(x, 90.0, 131.0)
        np.testing.assert_allclose(y[:4], x[:4])
        self.assertTrue(np.all(y[4:] < 131.0))
        self.assertTrue(np.all(np.diff(y) > 0))

    def test_value_and_slope_are_continuous_at_the_start(self):
        e = 1e-4
        y = anatomy_layer.soft_limit(np.array([90.0 - e, 90.0, 90.0 + e]), 90.0, 131.0)
        self.assertAlmostEqual((y[2] - y[1]) / e, 1.0, places=3)
        self.assertAlmostEqual((y[1] - y[0]) / e, 1.0, places=3)


class SplitTest(unittest.TestCase):
    """step 1 alone: the same world pose of the hands, the head and the chest, the rotations put where a body has them"""

    @classmethod
    def setUpClass(cls):
        cls.dance = odd_elbow_dance()
        cls.result = anatomy_layer.layer(MODEL, cls.dance, split_only())
        cls.names = ["左手首", "右手首", "頭", "上半身2", "左ひじ", "左腕捩", "左腕", "左手捩", "左肩C", "首", "上半身"]
        cls.win = worlds(cls.dance, cls.names)
        cls.wout = worlds(cls.result.motion, cls.names)

    def test_the_hand_keeps_its_world_pose(self):
        p_in, r_in = self.win["左手首"]
        p_out, r_out = self.wout["左手首"]
        self.assertLess(rot_deg(r_in, r_out).max(), 0.05)
        self.assertLess(np.linalg.norm(p_in - p_out, axis=1).max(), 0.01)      # 0.8 mm (the chest moves a little)

    def test_the_head_and_the_chest_keep_their_world_orientation(self):
        for name in ("頭", "上半身2"):
            self.assertLess(rot_deg(self.win[name][1], self.wout[name][1]).max(), 0.05, name)

    def test_the_elbow_turns_about_one_axis(self):
        q = locals_of(self.result.motion, "左ひじ")
        h = np.array(self.result.report["rest"]["左"]["hinge_axis"])
        v = q[:, :3]
        n = np.linalg.norm(v, axis=1)
        bent = n > 1e-3
        self.assertTrue(bent.all())
        off = np.linalg.norm(np.cross(v[bent] / n[bent, None], h), axis=1)
        self.assertLess(off.max(), 1e-4)

    def test_the_hinge_axis_comes_from_the_bones_and_the_elbow_helper(self):
        rest = self.result.report["rest"]["左"]
        h, d_f = np.array(rest["hinge_axis"]), np.array(rest["forearm"])
        self.assertAlmostEqual(float(h @ d_f), 0.0, places=6)
        # the helper's local Z is nearly +Z (back): the forearm bends to the front, the axis lies in the frontal plane
        self.assertGreater(abs(h[0]), 0.5)
        self.assertLess(abs(h[2]), 0.05)

    def test_the_upper_arm_twist_is_on_the_twist_bone(self):
        d_u = np.array(self.result.report["rest"]["左"]["upper_arm"])
        tw = locals_of(self.result.motion, "左腕捩")
        off = np.linalg.norm(np.cross(tw[:, :3], d_u), axis=1)
        self.assertLess(off.max(), 1e-5)                                    # 腕捩 turns about its own axis only
        arm = locals_of(self.result.motion, "左腕")
        self.assertLess(np.abs(arm[:, :3] @ d_u).max(), 1e-5)              # 腕 has no part about the upper arm's axis
        self.assertGreater(np.degrees(2 * np.arccos(np.clip(np.abs(tw[:, 3]), 0, 1))).max(), 5.0)

    def test_the_forearm_twist_follows_fix_twist_s_rule_by_default(self):
        d_f = np.array(self.result.report["rest"]["左"]["forearm"])
        tw = locals_of(self.result.motion, "左手捩")
        self.assertLess(np.linalg.norm(np.cross(tw[:, :3], d_f), axis=1).max(), 1e-5)      # about the forearm only
        self.assertLessEqual(np.degrees(2 * np.arccos(np.clip(np.abs(tw[:, 3]), 0, 1))).max(), 45.0 + 1e-6)

    def test_the_forearm_twist_bone_kept_as_it_was_when_asked(self):
        p = split_only()
        p["forearm_twist"] = "keep"
        out = anatomy_layer.layer(MODEL, self.dance, p).motion
        tracks_in, tracks_out = fk.tracks_of(self.dance), fk.tracks_of(out)
        self.assertEqual([(k.frame, k.rotation) for k in tracks_in["左手捩"]],
                         [(k.frame, k.rotation) for k in tracks_out["左手捩"]])
        w = worlds(out, ["左手首"])
        self.assertLess(rot_deg(self.win["左手首"][1], w["左手首"][1]).max(), 0.05)
        self.assertLess(np.linalg.norm(self.win["左手首"][0] - w["左手首"][0], axis=1).max(), 0.01)

    def test_the_forearm_twist_back_on_the_hand_twist_bone_when_asked(self):
        p = split_only()
        p["forearm_twist"] = "handtw"
        out = anatomy_layer.layer(MODEL, self.dance, p).motion
        w = worlds(out, ["左手首"])
        self.assertLess(rot_deg(self.win["左手首"][1], w["左手首"][1]).max(), 0.05)
        d_f = np.array(self.result.report["rest"]["左"]["forearm"])
        wrist = locals_of(out, "左手首")
        self.assertLess(np.abs(wrist[:, :3] @ d_f).max(), 1e-5)             # no twist left on the wrist

    def test_the_trunk_and_the_neck_are_shared(self):
        lo, up = locals_of(self.result.motion, "上半身"), locals_of(self.result.motion, "上半身2")
        f = 25
        self.assertGreater(rot_deg(up[f:f + 1], np.array([[0.0, 0.0, 0.0, 1.0]]))[0], 5.0)
        lo_in = locals_of(self.dance, "上半身")
        self.assertLess(rot_deg(lo[f:f + 1], np.array([[0, 0, 0, 1.0]]))[0], rot_deg(lo_in[f:f + 1], np.array([[0, 0, 0, 1.0]]))[0])
        neck = locals_of(self.result.motion, "首")
        # the head turned 45 degrees: about a third of the turn goes to the neck
        twist = np.degrees(2 * np.arctan2(neck[f, 1], neck[f, 3]))
        self.assertAlmostEqual(abs(twist), 15.0, delta=2.0)

        def flexion(q):
            up = anatomy_layer.qrot(q, np.array([0.0, 1.0, 0.0]))
            return abs(np.degrees(np.arctan2(up[..., 2], up[..., 1])))
        # the head bent 10 degrees: 0.6 of it goes to the neck; the trunk bent 15: 0.25 of it to 上半身2 (under the
        # saturation that keeps the chest's shift small)
        self.assertAlmostEqual(flexion(neck[f]), 6.0, delta=1.5)
        self.assertGreater(flexion(up[f]), 2.0)
        self.assertLess(flexion(up[f]), 0.25 * 15.0 + 0.5)

    def test_a_trunk_turned_half_round_with_the_pelvis_is_split_against_the_pelvis(self):
        # the trace turns 上半身 and 下半身 together by about half a turn on 腰's frame; the spine's own turn is small, and
        # the split must not jump where the half turn passes 180 degrees
        keys = [k for k in untouched_keys() if k.name != "下半身"]
        for f, deg in ((0, 170.0), (30, 190.0), (LAST, 200.0)):
            keys.append(key("下半身", f, axis_angle((0, 1, 0), deg)))
            keys.append(key("上半身", f, compose(axis_angle((0, 1, 0), deg + 20.0), axis_angle((1, 0, 0), 10.0))))
        dance = vmd.Motion(model_name="d", bones=keys)
        out = anatomy_layer.layer(MODEL, dance, split_only())
        lo = locals_of(out.motion, "上半身")
        step = rot_deg(lo[1:], lo[:-1])
        self.assertLess(step.max(), 2.0)
        up = locals_of(out.motion, "上半身2")
        turn = np.degrees(2 * np.arctan2(up[:, 1], up[:, 3]))
        self.assertAlmostEqual(abs(turn[0]), 0.4 * 20.0, delta=1.0)                # 0.4 of the spine's 20 degrees
        w_in, w_out = worlds(dance, ["上半身2"]), worlds(out.motion, ["上半身2"])
        self.assertLess(rot_deg(w_in["上半身2"][1], w_out["上半身2"][1]).max(), 0.05)

    def test_untouched_bones_and_morphs_are_byte_for_byte_the_same(self):
        self.assertTrue(self.result.report["untouched"]["identical"])
        self.assertTrue(self.result.report["untouched"]["morphs_identical"])
        before = vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in self.dance.bones if k.name in ("センター", "下半身", "左足ＩＫ")]))
        after = vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in self.result.motion.bones if k.name in ("センター", "下半身", "左足ＩＫ")]))
        self.assertEqual(before, after)

    def test_the_report_measures_the_pose_error(self):
        err = self.result.report["pose_error"]
        self.assertLess(err["左手首"]["rot_deg"]["max"], 0.05)
        self.assertIn("p95", err["頭"]["pos_cm"])


class GirdleTest(unittest.TestCase):
    def test_a_shrug_beyond_the_cap_comes_down_and_the_hand_stays(self):
        dance = odd_elbow_dance(shrug=60.0)
        p = anatomy_layer.default_params()
        p.update(rom=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        g = result.report["girdle"]["左"]
        self.assertGreater(g["elevation_in"]["max"], 50.0)
        self.assertLess(g["elevation_out"]["max"], p["girdle_limits"]["elevation"][1] + 0.01)
        # a stronger shrug stays stronger below the cap
        self.assertLess(anatomy_layer.soft_limit(np.array([30.0]), *p["girdle_limits"]["elevation"])[0],
                        anatomy_layer.soft_limit(np.array([50.0]), *p["girdle_limits"]["elevation"])[0] - 2.0)
        # the elbow keeps its bend; the hand follows the shoulder down by at most the slack, and keeps its rotation
        self.assertLess(result.report["new_jumps"]["左"]["bend_change_deg"]["max"], anatomy_layer.BEND_TOL_DEG + 0.5)
        win, wout = worlds(dance, ["左手首"]), worlds(result.motion, ["左手首"])
        self.assertLess(np.linalg.norm(win["左手首"][0] - wout["左手首"][0], axis=1).max() * 8.0,
                        anatomy_layer.GIRDLE_HAND_SLACK_CM + 0.5)
        self.assertLess(rot_deg(win["左手首"][1], wout["左手首"][1]).max(), 0.05)

    def test_a_shoulder_pushed_forward_stays_with_the_arm_down_or_up(self):
        for arm in (-30.0, 50.0):                                          # hanging, raised to the side
            keys = untouched_keys()
            for f, deg in ((0, 0.0), (20, 15.0), (LAST, 15.0)):
                keys.append(key("左肩", f, axis_angle((0, 1, 0), deg)))   # the 肩 bone swung to the front
                keys.append(key("左腕", f, axis_angle((0, 0, 1), arm)))
            dance = vmd.Motion(model_name="d", bones=keys)
            p = anatomy_layer.default_params()
            p.update(rom=False)
            g = anatomy_layer.layer(MODEL, dance, p).report["girdle"]["左"]
            self.assertGreater(g["protraction_in"]["max"], 10.0)
            self.assertGreater(g["protraction_out"]["max"], g["protraction_in"]["max"] - 2.0, arm)

    def test_the_rhythm_never_makes_a_straight_arm_s_hand_slide(self):
        keys = untouched_keys()
        for f, deg in ((0, 0.0), (30, 70.0), (LAST, 90.0)):
            keys.append(key("左腕", f, compose(axis_angle((0, 1, 0), 25.0), axis_angle((0, 0, 1), deg))))
        dance = vmd.Motion(model_name="d", bones=keys)
        p = anatomy_layer.default_params()
        p.update(rom=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        p.update(girdle=False)
        bare = anatomy_layer.layer(MODEL, dance, p)
        # the trunk's split moves the shoulder a little; the straight arm stays straight and its hand follows by that
        # much, with or without the girdle: the rhythm adds nothing
        slid, slid_bare = (r.report["girdle"]["左"]["hand_slid_cm"]["max"] for r in (result, bare))
        self.assertLess(slid, 0.5)
        self.assertLessEqual(slid, slid_bare + 0.01)
        for r in (result, bare):
            self.assertLess(r.report["new_jumps"]["左"]["bend_change_deg"]["max"], anatomy_layer.BEND_TOL_DEG + 0.5)
        win, wout = worlds(dance, ["左手首"]), worlds(result.motion, ["左手首"])
        self.assertLess(np.linalg.norm(win["左手首"][0] - wout["左手首"][0], axis=1).max() * 8.0, slid + 0.01)

    def test_a_straight_arm_stays_straight_when_the_chest_bends(self):
        keys = untouched_keys()
        for f, deg in ((0, 0.0), (30, 35.0), (LAST, 10.0)):
            keys.append(key("左腕", f, axis_angle((0, 0, 1), 40.0)))
            keys.append(key("上半身", f, compose(axis_angle((1, 0, 0), deg), axis_angle((0, 0, 1), deg / 2.0))))
        dance = vmd.Motion(model_name="d", bones=keys)
        r = anatomy_layer.layer(MODEL, dance, split_only())
        j = r.report["new_jumps"]["左"]
        self.assertLess(j["bend_change_deg"]["max"], anatomy_layer.BEND_TOL_DEG + 0.5)
        self.assertEqual(j["straight_turned_bent"], 0)

    def test_the_rhythm_lifts_the_shoulder_a_little_with_the_arm(self):
        dance = odd_elbow_dance()
        p = anatomy_layer.default_params()
        p.update(rom=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        g = result.report["girdle"]["左"]
        self.assertGreater(g["elevation_out"]["max"], g["elevation_in"]["max"])
        self.assertLess(g["elevation_out"]["max"], 10.0)


class RangeTest(unittest.TestCase):
    def test_a_supination_beyond_the_cap_is_eased_and_the_hand_stays(self):
        dance = odd_elbow_dance(supinate=-90.0)
        p = anatomy_layer.default_params()
        p.update(girdle=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        arm = result.report["arm"]["左"]
        self.assertGreater(arm["pronation_abs"]["in_max"], 100.0)
        self.assertLess(arm["pronation_abs"]["out_max"], arm["pronation_abs"]["in_max"] - 20.0)
        win, wout = worlds(dance, ["左手首"]), worlds(result.motion, ["左手首"])
        self.assertLess(np.linalg.norm(win["左手首"][0] - wout["左手首"][0], axis=1).max(), 0.01)
        self.assertLess(rot_deg(win["左手首"][1], wout["左手首"][1]).max(), 0.05)

    def test_frames_far_from_an_excess_keep_the_elbow_where_it_was(self):
        dance = odd_elbow_dance(supinate=-90.0)
        p = anatomy_layer.default_params()
        p.update(girdle=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        split = anatomy_layer.layer(MODEL, dance, split_only())
        a, b = worlds(result.motion, ["左ひじ"]), worlds(split.motion, ["左ひじ"])
        moved = np.linalg.norm(a["左ひじ"][0] - b["左ひじ"][0], axis=1) * 8.0
        self.assertGreater(moved.max(), 0.5)                               # the excess moved the elbow somewhere
        # the excess sits around frame 40; frames 0..8 keep the split's elbow
        self.assertLess(moved[:9].max(), 0.05)

    def test_a_backward_elbow_becomes_a_bend_a_body_can_make(self):
        dance = odd_elbow_dance(hyper=True)
        p = anatomy_layer.default_params()
        p.update(girdle=False)
        result = anatomy_layer.layer(MODEL, dance, p)
        arm = result.report["arm"]["左"]
        self.assertGreater(arm["per_angle"]["elbow_extension"]["over_cap_in"], 50)
        self.assertEqual(arm["per_angle"]["elbow_extension"]["over_cap_out"], 0)
        self.assertGreater(arm["angles"]["elbow"]["out"]["min"], -18.0)      # no longer bent back beyond the cap
        # what the elbow gave up went beyond another cap by a little at most (the elbow may move about 5 cm), and what
        # is left is listed by name
        worst = max(arm["per_angle"].items(), key=lambda kv: kv[1]["max_over_cap_out"])
        self.assertLess(worst[1]["max_over_cap_out"], 8.0)
        if worst[1]["max_over_cap_out"] > 0.5:
            self.assertTrue(any(worst[0] in s["beyond"] for s in arm["beyond_cap_stretches_out"]))

    def test_the_trace_keys_where_the_shape_changes_are_listed(self):
        dance = odd_elbow_dance(supinate=-90.0)
        trace = vmd.Motion(model_name="trace", bones=[key("左腕", f) for f in (0, 20, 40, LAST)])
        p = anatomy_layer.default_params()
        p.update(girdle=False)
        result = anatomy_layer.layer(MODEL, dance, p, key_frames=anatomy_layer.key_frames_of(trace))
        listed = result.report["key_changes"]
        frames = {item["frame"] for item in listed if item["side"] == "左"}
        self.assertIn(40, frames, listed)
        self.assertNotIn(0, frames)


class TenodesisTest(unittest.TestCase):
    def test_off_by_default_and_fingers_untouched(self):
        dance = odd_elbow_dance()
        result = anatomy_layer.layer(MODEL, dance, split_only())
        a = [(k.frame, k.rotation) for k in dance.bones if k.name == "左中指１"]
        b = [(k.frame, k.rotation) for k in result.motion.bones if k.name == "左中指１"]
        self.assertEqual(a, b)

    def test_relaxed_fingers_follow_the_wrist(self):
        dance = odd_elbow_dance()
        p = split_only()
        p["tenodesis"] = True
        result = anatomy_layer.layer(MODEL, dance, p)
        t = result.report["tenodesis"]["左"]
        self.assertGreater(t["frames"], 0)
        # Su 2005: about 0.30 degree of MP flexion (towards the palm) per degree of wrist extension, the extension read
        # again from the arm; a wrong sign gives -0.30
        self.assertAlmostEqual(t["slope_mp"], 0.30, delta=0.05)

    def test_a_fist_is_not_a_relaxed_hand(self):
        keys = [k for k in odd_elbow_dance().bones if "指" not in k.name]
        for f in (0, LAST):
            for fn in ("人指", "中指", "薬指", "小指"):
                for num in ("１", "２", "３"):
                    keys.append(key("左" + fn + num, f, axis_angle((0, 0, 1), -75.0)))
        p = split_only()
        p["tenodesis"] = True
        result = anatomy_layer.layer(MODEL, vmd.Motion(model_name="d", bones=keys), p)
        self.assertEqual(result.report["tenodesis"]["左"]["frames"], 0)
        self.assertEqual(result.report["tenodesis"]["左"]["relaxed_frames"], 0)


class CommandTest(unittest.TestCase):
    def test_writes_the_dance_and_the_report(self):
        folder = tempfile.mkdtemp()
        try:
            src, out, rep = (os.path.join(folder, n) for n in ("in.vmd", "out.vmd", "r.json"))
            model = os.path.join(folder, "m.pmx")
            vmd.dump(odd_elbow_dance(), src)
            with open(model, "wb") as f:
                f.write(model_bytes())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = anatomy_layer.main([src, model, out, "--report", rep])
            self.assertEqual(code, 0, buf.getvalue())
            printed = json.loads(buf.getvalue())
            self.assertTrue(printed["ok"])
            self.assertTrue(vmd.load(out).bones)
            with open(rep, encoding="ascii") as f:
                self.assertIn("pose_error", json.load(f))
        finally:
            shutil.rmtree(folder)

    def test_refuses_shares_out_of_range(self):
        folder = tempfile.mkdtemp()
        try:
            src, out = os.path.join(folder, "in.vmd"), os.path.join(folder, "out.vmd")
            model = os.path.join(folder, "m.pmx")
            vmd.dump(odd_elbow_dance(), src)
            with open(model, "wb") as f:
                f.write(model_bytes())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = anatomy_layer.main([src, model, out, "--neck-shares", "0.6,1.7,0.3"])
            self.assertEqual(code, 2)
            self.assertIn("neck-shares", json.loads(buf.getvalue())["error"]["message"])
            self.assertFalse(os.path.exists(out))
        finally:
            shutil.rmtree(folder)

    def test_refuses_to_write_over_the_dance(self):
        folder = tempfile.mkdtemp()
        try:
            src = os.path.join(folder, "in.vmd")
            model = os.path.join(folder, "m.pmx")
            vmd.dump(odd_elbow_dance(), src)
            with open(model, "wb") as f:
                f.write(model_bytes())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = anatomy_layer.main([src, model, src])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(buf.getvalue())["ok"])
        finally:
            shutil.rmtree(folder)


# ---- the real dance (skipped where it is not) ------------------------------------------------------

def real_file(*parts):
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    path = os.path.join(MAIN_TREE, *parts)
    return path if os.path.isfile(path) else None


def rin_path():
    """Sour's Rin: MMD_CLI_RIN when set, else the model folder of MMD under the user's Desktop"""
    rel = os.path.join("MikuMikuDance_v932x64", "UserFile", "Model", "Sour式鏡音リンVer.2.01", "White.pmx")
    for path in (os.environ.get("MMD_CLI_RIN"), os.path.join(os.path.expanduser("~"), "Desktop", rel)):
        if path and os.path.isfile(path):
            return path
    return None


TRACE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_twist.vmd") or os.environ.get("MMD_CLI_TRACE")
RIN = rin_path()
REAL = bool(TRACE) and os.path.isfile(TRACE) and RIN is not None


def crop(motion, first, last):
    """the motion between two frames as a motion of its own (a key on every frame, the linear curve)"""
    out = []
    for name, keys in fk.tracks_of(motion).items():
        frames = [k.frame for k in keys]
        for f in range(first, last + 1):
            p, r = fk.sample(keys, f, frames)
            out.append(vmd.BoneKey(keys[0].name, f - first, p, r, vmd.bone_interpolation(vmd.LINEAR_CURVE),
                                   raw_name=keys[0].raw_name))
    return vmd.Motion(model_name=motion.model_name, bones=out, morphs=list(motion.morphs))


@unittest.skipUnless(REAL, "the trace or Rin is not here")
class RealDanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pmx.load(RIN)
        cls.dance = vmd.load(TRACE)

    def test_the_left_shoulder_drawn_back_at_3882_comes_forward_and_the_hand_stays(self):
        part = crop(self.dance, 3860, 3920)
        result = anatomy_layer.layer(self.model, part, anatomy_layer.default_params())
        g = result.report["girdle"]["左"]
        self.assertLess(g["protraction_in"]["min"], -50.0)
        self.assertGreater(g["protraction_out"]["min"], -25.5)
        # the arm is straight there: the hand follows the shoulder along the arm (the bend kept) by at most the trunk's
        # share and the slack, and keeps its rotation
        err = result.report["pose_error"]["左手首"]
        self.assertLess(err["pos_cm"]["max"], anatomy_layer.GIRDLE_HAND_SLACK_CM + 3.0)
        self.assertAlmostEqual(err["pos_cm"]["max"], g["hand_slid_cm"]["max"], delta=0.05)
        self.assertLess(err["rot_deg"]["max"], 0.05)
        self.assertLess(result.report["new_jumps"]["左"]["bend_change_deg"]["max"], anatomy_layer.BEND_TOL_DEG + 0.5)

    def test_the_right_shoulder_up_to_the_ear_at_3240_comes_down(self):
        part = crop(self.dance, 3215, 3260)
        result = anatomy_layer.layer(self.model, part, anatomy_layer.default_params())
        g = result.report["girdle"]["右"]
        self.assertGreater(g["elevation_in"]["max"], 60.0)
        self.assertLess(g["elevation_out"]["max"], anatomy_layer.GIRDLE_LIMITS["elevation"][1] + 0.05)

    def test_no_new_one_frame_jumps_where_the_first_version_made_them(self):
        # the review of 2026-10-10 (H2): the elbow jumped 9 cm in a frame at 4,023 (right), the upper arm's skin turned
        # 141, 102 and 91 degrees in a frame at 1,482, 4,023 and 7,136 (right); the left elbow jumped at 1,513
        for first, last, side in ((4005, 4045, "右"), (1465, 1500, "右"), (7120, 7150, "右"), (1500, 1525, "左")):
            result = anatomy_layer.layer(self.model, crop(self.dance, first, last), anatomy_layer.default_params())
            j = result.report["new_jumps"][side]
            self.assertEqual(j["elbow"], 0, (first, j["elbow_frames"]))
            self.assertEqual(j["upper_arm_roll"], 0, (first, j["upper_arm_roll_frames"]))
            self.assertLess(j["bend_change_deg"]["max"], anatomy_layer.BEND_TOL_DEG + 0.5, first)

    def test_an_excess_that_needs_the_elbow_moved_far_is_left(self):
        # 6,528 - 6,542 (left): the hand is twisted almost half round; the first version moved the elbow 13 cm
        result = anatomy_layer.layer(self.model, crop(self.dance, 6505, 6565), anatomy_layer.default_params())
        arm = result.report["arm"]["左"]
        self.assertLess(arm["elbow_moved_by_rom_cm"]["max"], 7.0)
        self.assertTrue(any("supination" in s["beyond"] for s in arm["beyond_cap_stretches_out"]))


if __name__ == "__main__":
    unittest.main()
