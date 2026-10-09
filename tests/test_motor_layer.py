"""tools/motor_layer.py: torque-limited joint tracking with proximal-to-distal delays, baked onto a dance."""
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
from tests.test_pmx import APPEND_ROTATE, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_TREE = "C:/Users/kaga/Desktop/mmd-cli"           # the main working tree, where the real data lives


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("motor_layer", os.path.join(ROOT, "tools", "motor_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


motor_layer = load_tool()
LAST = 90


def model_bytes(hand_at_face=False, fingers=True):
    """the bones of Sour's Rin the layer reads or writes (her rest positions, model units), with her 肩P / 肩C (肩C takes
    肩P's turn with ratio -1) and the twist bones between the joints.  hand_at_face folds the left arm up so that the tip
    of the left middle finger rests 6.8 cm in front of the left eye"""
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
             ("左目", "頭", (0.41, 17.214, -0.562), {}),
             ("右目", "頭", (-0.41, 17.214, -0.562), {}),
             ("左肩P", "上半身2", (0.23, 15.393, -0.222), {}),
             ("左肩", "左肩P", (0.23, 15.393, -0.222), {}),
             ("左肩C", "左肩", (0.911, 15.277, -0.248), {"flags": NORMAL | APPEND_ROTATE, "append": "左肩P"}),
             ("左腕", "左肩C", (0.911, 15.277, -0.248), {})]
    if hand_at_face:
        left = [("左腕捩", "左腕", (1.2, 14.6, -0.6)), ("左ひじ", "左腕捩", (1.5, 14.0, -1.5)),
                ("左手捩", "左ひじ", (1.2, 15.1, -1.55)), ("左手首", "左手捩", (0.9, 16.2, -1.6)),
                ("左中指１", "左手首", (0.6, 16.8, -1.5)), ("左中指２", "左中指１", (0.45, 17.0, -1.45)),
                ("左中指３", "左中指２", (0.3, 17.2, -1.4))]
    else:
        left = [("左腕捩", "左腕", (1.909, 14.505, -0.259)), ("左ひじ", "左腕捩", (2.907, 13.732, -0.27)),
                ("左手捩", "左ひじ", (3.78, 13.071, -0.253)), ("左手首", "左手捩", (4.652, 12.41, -0.237)),
                ("左中指１", "左手首", (5.41, 11.935, -0.261)), ("左中指２", "左中指１", (5.714, 11.691, -0.264)),
                ("左中指３", "左中指２", (5.87, 11.538, -0.264))]
    if not fingers:
        left = left[:4]
    bones += [(n, p, pos, {}) for n, p, pos in left]
    bones += [("右肩", "上半身2", (-0.23, 15.393, -0.222), {}),
              ("右腕", "右肩", (-0.911, 15.277, -0.248), {}),
              ("右ひじ", "右腕", (-2.907, 13.732, -0.27), {}),
              ("右手首", "右ひじ", (-4.652, 12.41, -0.237), {}),
              ("左足ＩＫ", "全ての親", (1.12, 1.745, 0.37), {"flags": NORMAL | TRANSLATE})]
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"]], -1.0)
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-like", bones=built)


MODEL = pmx.loads(model_bytes())


def axis_angle(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


def key(name, frame, q=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0)):
    return vmd.BoneKey(name, frame, tuple(position), fk.stored(tuple(q)))


def untouched_keys(last=LAST):
    return [key("センター", 0, position=(0.0, -0.2, 0.1)), key("センター", 50, position=(0.3, -0.4, 0.1)),
            key("センター", last, position=(0.3, -0.4, 0.1)),
            key("左足ＩＫ", 0, position=(0.1, 0.0, 0.2)), key("左足ＩＫ", last, position=(0.1, 0.0, 0.2)),
            key("下半身", 0, axis_angle((1, 0, 0), 5.0)), key("下半身", last, axis_angle((1, 0, 0), 5.0)),
            key("左手捩", 0, axis_angle((1, -0.6, 0), 10.0)), key("左手捩", last, axis_angle((1, -0.6, 0), 10.0))]


def swing_dance(last=LAST, speed_frames=6):
    """the left arm swings down and in (upper arm, elbow and wrist together, on the same frames, as a trace does) in
    `speed_frames` frames from frame 20, holds, and swings back at frame 60; the body bends a little"""
    a, b = 20, 20 + speed_frames
    keys = untouched_keys(last)
    for name, axis, deg in (("左腕", (0, 0, 1), 70.0), ("左ひじ", (0, 1, 0), -60.0), ("左手首", (0, 0, 1), 40.0),
                            ("左中指１", (0, 0, 1), 30.0), ("左中指２", (0, 0, 1), 30.0)):
        q = axis_angle(axis, deg)
        keys += [key(name, 0), key(name, a), key(name, b, q), key(name, 60, q), key(name, 60 + speed_frames),
                 key(name, last)]
    keys += [key("上半身", 0), key("上半身", 30, axis_angle((1, 0, 0), 8.0)), key("上半身", last)]
    return vmd.Motion(model_name="dancer", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)])


def stiff_params():
    """very stiff, critically damped, the whole target acceleration fed forward, no delays: must give back the input"""
    p = motor_layer.default_params()
    for c in p["classes"].values():
        c.update(fn=40.0, zeta=1.0, ff=1.0, delay=(0.0, 0.0))
    p["finger_delay"] = 0.0
    p["torque_scale"] = 1e6
    p["lead"] = 0.0
    return p


def angle_deg(a, b):
    d = abs(float(np.dot(np.asarray(a, float), np.asarray(b, float))))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


def key_track(motion, name):
    return {k.frame: k for k in motion.bones if k.name == name}


def relative(world, parent, child):
    """per frame the rotation of `child` in the frame of `parent` (numpy, as the tool's world dicts)"""
    rp, rc = world[parent][1], world[child][1]
    return motor_layer.qnorm(motor_layer.qmul(motor_layer.qconj(rp), rc))


def crossing(values, level):
    """the first fractional frame where values (rising) reach level"""
    for f in range(1, len(values)):
        if values[f - 1] < level <= values[f]:
            return f - 1 + (level - values[f - 1]) / (values[f] - values[f - 1])
    return None


def turned(q_track, q0):
    """degrees from q0 per frame"""
    return np.array([angle_deg(q, q0) for q in q_track])


def key_bytes(keys):
    return [(k.raw_name, k.name, k.frame, k.position, k.rotation, k.interpolation) for k in keys]


class IdentityTest(unittest.TestCase):
    def test_a_stiff_layer_without_delays_gives_back_the_input(self):
        dance = swing_dance()
        result = motor_layer.layer(MODEL, dance, stiff_params())
        errors = []
        for name in ("上半身", "上半身2", "首", "頭", "左肩", "左腕", "左ひじ", "左手首", "左中指１", "左中指３", "右手首"):
            got = key_track(result.motion, name)
            own = sorted([k for k in dance.bones if k.name == name], key=lambda k: k.frame)
            for f in range(LAST + 1):
                want = fk.sample(own, f)[1] if own else (0.0, 0.0, 0.0, 1.0)
                errors.append(angle_deg(got[f].rotation, want))
        # the error left is at the kinks of the keyed speed (a 6-frame swing at 350 deg/s starting and stopping dead)
        self.assertLess(max(errors), 1.5)
        self.assertLess(float(np.median(errors)), 0.01)
        # and in the world: the hand where the input has it
        err = np.linalg.norm(result.world_out["左手首"][0] - result.world_in["左手首"][0], axis=1) * 80.0
        self.assertLess(float(err.max()), 10.0)         # mm, at those kinks (1.1 degrees on a 40 cm arm)
        self.assertLess(float(np.median(err)), 0.5)


class DelayOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dance = swing_dance()
        cls.result = motor_layer.layer(MODEL, cls.dance, motor_layer.default_params())

    def half_way(self, world, parent, child):
        q = relative(world, parent, child)
        moved = turned(q[:40], q[19])
        return crossing(moved, 0.5 * moved[35])

    def test_the_joints_start_proximal_to_distal(self):
        # the trace moves the upper arm, the elbow and the wrist on the same frames; the layer makes the elbow follow
        # the upper arm and the wrist the elbow (the half-way time of each joint's turn, output minus input)
        shifts = []
        for parent, child in (("左肩", "左腕"), ("左腕", "左ひじ"), ("左ひじ", "左手首"), ("左手首", "左中指１")):
            t_in = self.half_way(self.result.world_in, parent, child)
            t_out = self.half_way(self.result.world_out, parent, child)
            shifts.append(t_out - t_in)
        self.assertLess(shifts[0], shifts[1] - 0.2, shifts)
        self.assertLess(shifts[1], shifts[2] - 0.2, shifts)
        self.assertLess(shifts[2], shifts[3] - 0.1, shifts)
        # the hand arrives about on time (the research: within half a frame), the arm root leads
        self.assertLess(shifts[0], 0.0, shifts)
        self.assertLess(abs(shifts[2]), 1.2, shifts)

    def test_the_stop_overshoots_and_settles(self):
        # at the stop (frame 26) the wrist runs past the held pose and comes back: within 1 degree 10 frames later
        q_in = relative(self.result.world_in, "左ひじ", "左手首")
        q_out = relative(self.result.world_out, "左ひじ", "左手首")
        hold = q_in[30]
        direction = motor_layer.qlog(motor_layer.qnorm(motor_layer.qmul(motor_layer.qconj(hold), q_in[23])))
        direction = -direction / np.linalg.norm(direction)
        dev = motor_layer.qlog(motor_layer.qnorm(motor_layer.qmul(motor_layer.qconj(np.broadcast_to(hold, q_out.shape)),
                                                                   q_out)))
        past = np.degrees(dev[26:45] @ direction)
        self.assertGreater(float(past.max()), 0.2)
        self.assertLess(float(np.degrees(np.linalg.norm(dev[36:58], axis=1)).max()), 1.0)
        self.assertLess(float(np.degrees(np.linalg.norm(dev[50:58], axis=1)).max()), 0.1)

    def test_the_report_has_the_measures(self):
        r = self.result.report
        for k in ("a09", "a02", "fidelity", "proximity", "jumps", "fallback", "lead", "untouched", "params", "body"):
            self.assertIn(k, r)
        self.assertGreater(r["body"]["height_m"], 1.3)
        self.assertLess(r["body"]["height_m"], 1.7)


class UntouchedTest(unittest.TestCase):
    def test_other_bones_and_morphs_are_byte_for_byte_the_input(self):
        dance = swing_dance()
        result = motor_layer.layer(MODEL, dance, motor_layer.default_params())
        sim = set(result.report["bones"])
        self.assertIn("左腕", sim)
        for n in ("センター", "下半身", "腰", "左足ＩＫ", "左手捩", "左腕捩", "左目", "右目"):
            self.assertNotIn(n, sim)
        kin = key_bytes([k for k in dance.bones if k.name not in sim])
        kout = key_bytes([k for k in result.motion.bones if k.name not in sim])
        self.assertEqual(kin, kout)
        self.assertEqual([(m.name, m.frame, m.weight) for m in dance.morphs],
                         [(m.name, m.frame, m.weight) for m in result.motion.morphs])
        self.assertTrue(result.report["untouched"]["identical"])
        # every simulated bone is keyed on every frame
        self.assertEqual(sorted(key_track(result.motion, "左ひじ")), list(range(LAST + 1)))


class EndToEndTest(unittest.TestCase):
    def test_the_written_file_is_what_the_report_measured(self):
        dance = swing_dance()
        result = motor_layer.layer(MODEL, dance, motor_layer.default_params())
        back = vmd.loads(vmd.dumps(result.motion))
        names = ["左手首", "左中指３", "頭", "右手首", "上半身2"]
        pose = fk.Pose(MODEL, back, names)
        worst = 0.0
        for f in range(0, LAST + 1, 3):
            w = pose.at(f)
            for n in names:
                worst = max(worst, float(np.max(np.abs(np.array(w[n][0]) - result.world_out[n][0][f]))))
        self.assertLess(worst, 1e-4)


class JumpTest(unittest.TestCase):
    def test_a_one_frame_jump_of_the_input_passes_through(self):
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name != "左手首"]
        q = axis_angle((1, 0, 0), 120.0)
        dance.bones += [key("左手首", 0), key("左手首", 40), key("左手首", 41, q), key("左手首", LAST, q)]
        result = motor_layer.layer(MODEL, dance, motor_layer.default_params())
        jumps = [(j["bone"], j["frame"]) for j in result.report["jumps"]]
        self.assertIn(("左手首", 40), jumps)
        self.assertNotIn("左腕", [b for b, _ in jumps])
        got = key_track(result.motion, "左手首")
        self.assertLess(angle_deg(got[40].rotation, (0, 0, 0, 1)), 0.05)
        self.assertLess(angle_deg(got[41].rotation, q), 0.05)
        self.assertLess(angle_deg(got[42].rotation, q), 0.05)
        spans = [s for s in result.report["fallback"] if s["reason"] == "jump"]
        self.assertTrue(any(s["first"] <= 40 and s["last"] >= 41 and "左手首" in s["bones"] for s in spans), spans)


class UnsolvedTest(unittest.TestCase):
    def test_a_hand_left_far_behind_goes_back_to_the_input_and_is_reported(self):
        # a layer far too soft for a 6-frame swing: the hand ends up 10 cm and more from where the input has it
        p = motor_layer.default_params()
        for c in p["classes"].values():
            if not c.get("kinematic"):
                c.update(fn=1.5, zeta=0.6, ff=0.0)
        p["floor"] = False
        p["lead"] = 0.0
        result = motor_layer.layer(MODEL, swing_dance(), p)
        spans = [s for s in result.report["fallback"] if s["reason"] == "unsolved"]
        self.assertTrue(spans)
        self.assertTrue(any("左腕" in s["bones"] for s in spans), spans)
        self.assertEqual([r for r in result.report["floor_residual"] if r["reason"] == "unsolved"], [])
        a, b = result.world_in["左手首"][0], result.world_out["左手首"][0]
        best = np.min(np.stack([np.linalg.norm(b[1 + d:LAST - 3 + d] - a[1:LAST - 3], axis=1) for d in range(-1, 4)]),
                      axis=0) * 8.0
        self.assertLessEqual(float(best.max()), motor_layer.DEVIATION_CM + 1e-6)


class FingerTest(unittest.TestCase):
    """the fingers: kinematic, a short delay after the wrist; in a snap (faster than 2,000 deg/s) no delay of their own:
    they ride the hand's timing"""

    def dance(self):
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name not in ("左中指１", "左中指２")]
        snap = axis_angle((0, 0, 1), 150.0)            # 75 deg a frame: 2,250 deg/s
        slow = axis_angle((0, 0, 1), 40.0)
        dance.bones += [key("左中指１", 0), key("左中指１", 70), key("左中指１", 72, snap), key("左中指１", 76, snap),
                        key("左中指２", 0), key("左中指２", 30), key("左中指２", 50, slow), key("左中指２", LAST, slow)]
        return dance

    def errors(self, params, name, frames):
        dance = self.dance()
        result = motor_layer.layer(MODEL, dance, params)
        got = key_track(result.motion, name)
        own = sorted([k for k in dance.bones if k.name == name], key=lambda k: k.frame)
        return [angle_deg(got[f].rotation, fk.sample(own, f)[1]) for f in frames]

    def test_a_snap_drops_the_fingers_own_delay(self):
        with_snap = max(self.errors(motor_layer.default_params(), "左中指１", range(68, 76)))
        p = motor_layer.default_params()
        p["snap"] = False
        without = max(self.errors(p, "左中指１", range(68, 76)))
        self.assertLess(with_snap, without - 10.0)

    def test_a_slow_curl_follows_the_wrist_a_little_later(self):
        errors = self.errors(motor_layer.default_params(), "左中指２", range(32, 48))
        self.assertGreater(min(errors), 0.3)             # 2 deg/frame read some 0.7 frames late
        self.assertLess(max(errors), 3.0)


class FloorTest(unittest.TestCase):
    """the left hand swings in to rest 6.8 cm in front of the eye, fast, along a path that would go on into the face"""

    @classmethod
    def setUpClass(cls):
        cls.model = pmx.loads(model_bytes(hand_at_face=True))
        r = np.array([0.3 - 0.911, 17.2 - 15.277, -1.4 + 0.248])
        u = np.array([0.41 - 0.3, 17.214 - 17.2, -0.562 + 1.4])
        axis = tuple(np.cross(r, u))
        keys = untouched_keys()
        keys += [key("左腕", 0, axis_angle(axis, -45.0)), key("左腕", 20, axis_angle(axis, -45.0)), key("左腕", 24),
                 key("左腕", LAST)]
        cls.dance = vmd.Motion(model_name="dancer", bones=keys)

    def weak(self, floor):
        p = motor_layer.default_params()
        for c in p["classes"].values():
            if not c.get("kinematic"):
                c.update(fn=3.0, zeta=0.35, ff=0.0)
        p["contact"] = False
        p["holds"] = False
        p["floor"] = floor
        return p

    def tip_eye_mm(self, world):
        eyes = 0.5 * (world["左目"][0] + world["右目"][0])
        return np.linalg.norm(world["左中指３"][0] - eyes, axis=1) * 80.0

    def test_without_the_floor_the_overshoot_goes_into_the_face(self):
        result = motor_layer.layer(self.model, self.dance, self.weak(False))
        d_in, d_out = self.tip_eye_mm(result.world_in), self.tip_eye_mm(result.world_out)
        self.assertLess(float(np.min(d_out - d_in)), -10.0)

    def test_the_floor_keeps_the_hand_off_the_face(self):
        result = motor_layer.layer(self.model, self.dance, self.weak(True))
        d_in, d_out = self.tip_eye_mm(result.world_in), self.tip_eye_mm(result.world_out)
        near = d_in < 200.0
        # the floor: within 10 cm of the eyes at most 8 mm closer than the input, a quarter of the rest further out
        self.assertGreaterEqual(float(np.min((d_out - motor_layer.floor_of(d_in))[near])), -0.5)
        self.assertTrue(any(s["reason"] == "floor" for s in result.report["fallback"]), result.report["fallback"])

    def test_the_contact_zone_keeps_the_input_there_by_itself(self):
        p = motor_layer.default_params()
        p["floor"] = False
        result = motor_layer.layer(self.model, self.dance, p)
        d_in, d_out = self.tip_eye_mm(result.world_in), self.tip_eye_mm(result.world_out)
        near = d_in < 100.0
        self.assertGreaterEqual(float(np.min((d_out - d_in)[near])), -10.0)


def wrist_step_excess(result, first, last):
    """the largest step (cm/frame) of the output's left wrist less the input's, frames first..last"""
    a, b = result.world_in["左手首"][0], result.world_out["左手首"][0]
    si = np.linalg.norm(np.diff(a, axis=0), axis=1)[first:last] * 8.0
    so = np.linalg.norm(np.diff(b, axis=0), axis=1)[first:last] * 8.0
    return float(np.max(so - si))


def soft_params(fn=1.5, ff=0.0, zeta=0.6, seams=None):
    p = motor_layer.default_params()
    for c in p["classes"].values():
        if not c.get("kinematic"):
            c.update(fn=fn, zeta=zeta, ff=ff)
    p["floor"] = False
    p["lead"] = 0.0
    if seams is not None:
        p["seams"] = seams
    return p


class SeamTest(unittest.TestCase):
    """a stretch given back to the input must not make the hand step at its edges (the review: 6,393, 10.7 cm in one
    frame where the input moved 3.0)"""

    def test_the_edges_do_not_step(self):
        result = motor_layer.layer(MODEL, swing_dance(), soft_params())
        spans = [s for s in result.report["fallback"] if s["reason"] == "unsolved"]
        self.assertTrue(spans)
        self.assertLessEqual(wrist_step_excess(result, 1, LAST - 1), motor_layer.SEAM_STEP_CM)
        seams = result.report["seams"]
        self.assertGreater(seams["edges"], 0)
        self.assertLessEqual(seams["max_excess_cm"], motor_layer.SEAM_STEP_CM)
        self.assertEqual(seams["over_%g_cm" % motor_layer.SEAM_STEP_CM], 0)

    def test_without_the_seam_care_they_step(self):
        result = motor_layer.layer(MODEL, swing_dance(), soft_params(seams=False))
        self.assertGreater(result.report["seams"]["max_excess_cm"], motor_layer.SEAM_STEP_CM)

    def test_a_wrist_far_on_the_same_frame_is_given_back(self):
        # late allowed (f-1 .. f+3) the hand may look near; on the same frame it may not be more than 12 cm away
        result = motor_layer.layer(MODEL, swing_dance(), soft_params(fn=1.0))
        a, b = result.world_in["左手首"][0], result.world_out["左手首"][0]
        self.assertLessEqual(float(np.max(np.linalg.norm(b - a, axis=1))) * 8.0, motor_layer.DEVIATION_SAME_CM + 1e-6)


class PresetTest(unittest.TestCase):
    def overshoot(self, params):
        result = motor_layer.layer(MODEL, swing_dance(), params)
        q_in = relative(result.world_in, "左ひじ", "左手首")
        q_out = relative(result.world_out, "左ひじ", "左手首")
        hold = q_in[30]
        u = motor_layer.qlog(motor_layer.qnorm(motor_layer.qmul(motor_layer.qconj(hold), q_in[23])))
        u = -u / np.linalg.norm(u)
        dev = motor_layer.qlog(motor_layer.qnorm(motor_layer.qmul(motor_layer.qconj(np.broadcast_to(hold, q_out.shape)),
                                                                   q_out)))
        return float(np.degrees(dev[26:45] @ u).max()), result

    def test_strong_runs_on_further_and_still_does_not_step(self):
        base, _ = self.overshoot(motor_layer.default_params())
        strong, result = self.overshoot(motor_layer.default_params("strong"))
        self.assertGreater(strong, 1.5 * base)
        self.assertEqual(result.report["params"]["preset"], "strong")
        self.assertLessEqual(result.report["seams"]["max_excess_cm"] or 0.0, motor_layer.SEAM_STEP_CM)

    def test_the_presets(self):
        p = motor_layer.default_params("strong")
        self.assertEqual(p["classes"]["upper"]["fn"], 3.5)
        self.assertEqual(p["classes"]["wrist"]["ff"], 0.5)
        self.assertEqual(motor_layer.default_params()["classes"]["upper"]["fn"], 7.0)    # the default unchanged
        with self.assertRaises(ValueError):
            motor_layer.default_params("weird")


class MechanismTest(unittest.TestCase):
    """the parts the review's mutations broke without a test noticing"""

    def test_the_torque_limit_binds_the_correction_only(self):
        # with the whole target acceleration fed forward and a strength of almost nothing the arm still follows; a
        # limit on the total torque would leave it standing (the research, 4.3 rule 3)
        p = stiff_params()
        for c in p["classes"].values():
            c.update(fn=8.0, zeta=0.85)
        p.update(torque_scale=1e-4, unsolved=False, floor=False)
        result = motor_layer.layer(MODEL, swing_dance(), p)
        q_in, q_out = relative(result.world_in, "左肩", "左腕"), relative(result.world_out, "左肩", "左腕")
        # (the parents' acceleration is not fed forward: the drag is what is left uncorrected, about 12 degrees)
        self.assertLess(float(motor_layer.qangle_deg(q_in, q_out).max()), 20.0)
        self.assertGreater(result.report["bones"]["左腕"]["torque_limit_share"], 0.5)

    def beat_hold_error(self, kime):
        p = motor_layer.default_params()
        p["kime"] = kime
        result = motor_layer.layer(MODEL, swing_dance(), p, beats=(26.0 / 30.0, 100.0))
        q_in, q_out = relative(result.world_in, "左ひじ", "左手首"), relative(result.world_out, "左ひじ", "左手首")
        return float(motor_layer.qangle_deg(q_in[24:30], q_out[24:30]).max()), result

    def test_a_beat_hold_is_met_on_time(self):
        with_kime, result = self.beat_hold_error(True)
        without, _ = self.beat_hold_error(False)
        self.assertGreaterEqual(result.report["beat_holds"]["count"], 1)
        self.assertLess(with_kime, 0.6 * without)

    def head_world_change(self, world):
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name not in ("上半身", "頭")]
        turn = axis_angle((0, 1, 0), 50.0)
        back = axis_angle((0, 1, 0), -50.0)
        dance.bones += [key("上半身", 0), key("上半身", 40), key("上半身", 43, turn), key("上半身", LAST, turn),
                        key("頭", 0), key("頭", 40), key("頭", 43, back), key("頭", LAST, back)]
        p = motor_layer.default_params()
        p["classes"]["head"]["world"] = world
        result = motor_layer.layer(MODEL, dance, p)
        return float(motor_layer.qangle_deg(result.world_in["頭"][1], result.world_out["頭"][1]).max())

    def test_the_head_keeps_its_world_direction_while_the_trunk_turns(self):
        # the input turns the trunk 50 degrees in 3 frames and the head back: the head looks the same way in the world
        aimed = self.head_world_change(True)
        self.assertLess(aimed, 2.0)
        self.assertGreater(self.head_world_change(False), 2.0 * aimed)

    def test_the_delays_slope_enters_the_target_speed(self):
        p = stiff_params()
        for c in p["classes"].values():
            c.update(fn=10.0, zeta=1.0)
        for k in ("holds", "kime", "contact", "slow", "snap", "jumps"):
            p[k] = False
        plan = motor_layer.Plan(MODEL, swing_dance(), p)
        j = plan.names.index("左手首")
        ramp = np.clip((np.arange(plan.F) - 18.0) / 8.0, 0.0, 1.0) * 3.0   # 0 -> 3 frames over the swing
        plan.D[:, j] = ramp
        plan.Dp = np.clip(np.gradient(plan.D, axis=0), -0.8, 0.8)
        local, _, _ = motor_layer.simulate(plan, {"arm": 0.0, "axial": 0.0})
        want, _, _ = motor_layer.target_at(plan, np.full(plan.F, j), np.arange(plan.F) - plan.D[:, j])
        # (with the slope left out of the target's speed the error rises to 3.1 degrees)
        self.assertLess(float(motor_layer.qangle_deg(local[:, j], want)[15:40].max()), 2.2)

    def test_a_jump_sets_the_bone_and_carries_its_children(self):
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name != "左ひじ"]
        q = axis_angle((1, 0, 0), 120.0)
        dance.bones += [key("左ひじ", 0), key("左ひじ", 40), key("左ひじ", 41, q), key("左ひじ", LAST, q)]
        p = motor_layer.default_params()
        for c in p["classes"].values():
            c["delay"] = (0.0, 0.0)
        plan = motor_layer.Plan(MODEL, dance, p)
        self.assertIn(("左ひじ", 40), [(x["bone"], x["frame"]) for x in plan.jumps])
        local, _, _ = motor_layer.simulate(plan, {"arm": 0.0, "axial": 0.0})
        e, w = plan.names.index("左ひじ"), plan.names.index("左手首")
        self.assertLess(float(motor_layer.qangle_deg(local[41, e], plan.qt[41, e])), 3.0)    # a step, not a sweep
        self.assertLess(float(motor_layer.qangle_deg(local[41, w], plan.qt[41, w])), 3.0)    # the wrist came along

    def test_an_inertia_carries_the_segments_below(self):
        plan = motor_layer.Plan(MODEL, swing_dance(), motor_layer.default_params())
        j = plan.names.index("左腕")
        m, com, r, _ = plan.segments[j]
        joint = plan.skel.rest[plan.bi[j]] * motor_layer.UNIT_M
        own = m * (float(np.sum((com - joint) ** 2)) + r * r)
        self.assertGreater(plan.I[j], 1.5 * own)

    def test_far_from_the_target_is_given_back_even_without_the_limit(self):
        # 150 degrees in 2 frames, a layer of 1 Hz and no strength limit: the tracking error passes 45 degrees
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name != "左腕"]
        q = axis_angle((0, 0, 1), 150.0)
        dance.bones += [key("左腕", 0), key("左腕", 30), key("左腕", 32, q), key("左腕", LAST, q)]
        p = soft_params(fn=1.0, zeta=1.0)
        p["torque_scale"] = 1e6
        result = motor_layer.layer(MODEL, dance, p)
        self.assertTrue(any("tracking error" in s["detail"] for s in result.report["fallback"]), result.report["fallback"])

    def test_the_checks_go_round_again_with_the_trunk(self):
        # the trunk lags a fast turn: giving back the arm alone leaves the hand far, the second round adds the trunk
        dance = swing_dance()
        dance.bones = [k for k in dance.bones if k.name != "上半身"]
        turn = axis_angle((0, 1, 0), 70.0)
        dance.bones += [key("上半身", 0), key("上半身", 40), key("上半身", 44, turn), key("上半身", LAST, turn)]
        p = motor_layer.default_params()
        p["classes"]["trunk"].update(fn=1.0, ff=0.0, zeta=1.0)
        p["floor"] = False
        result = motor_layer.layer(MODEL, dance, p)
        self.assertGreaterEqual(result.report["rounds"]["checks"], 2)
        self.assertEqual(result.report["floor_residual"], [])


class CliTest(unittest.TestCase):
    def test_main_writes_the_motion_and_the_report(self):
        folder = tempfile.mkdtemp()
        try:
            model_path = os.path.join(folder, "m.pmx")
            with open(model_path, "wb") as f:
                f.write(model_bytes())
            dance_path = os.path.join(folder, "d.vmd")
            vmd.dump(swing_dance(), dance_path)
            out, rep = os.path.join(folder, "o.vmd"), os.path.join(folder, "r.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = motor_layer.main([dance_path, model_path, out, "--report", rep])
            self.assertEqual(code, 0, buf.getvalue())
            self.assertTrue(json.loads(buf.getvalue().strip().splitlines()[-1])["ok"])
            with open(rep, encoding="ascii") as f:
                report = json.load(f)
            self.assertIn("a09", report)
            self.assertEqual(len(vmd.load(out).bones), len(motor_layer.layer(MODEL, swing_dance()).motion.bones))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(motor_layer.main([dance_path, model_path, dance_path]), 2)
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


REAL_DANCE = real_file("_spike", "out", "stage1", "breath", "dance_v3_breath.vmd")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"
REAL = REAL_DANCE is not None and os.path.isfile(RIN)


def crop(motion, first, last):
    """the motion between two frames as a motion of its own (a key on every frame, the linear curve)"""
    out = []
    for name, keys in fk.tracks_of(motion).items():
        frames = [k.frame for k in keys]
        for f in range(first, last + 1):
            p, r = fk.sample(keys, f, frames)
            out.append(vmd.BoneKey(keys[0].name, f - first, p, r, vmd.bone_interpolation(vmd.LINEAR_CURVE),
                                   raw_name=keys[0].raw_name))
    return vmd.Motion(model_name=motion.model_name, bones=out)


@unittest.skipUnless(REAL, "the stage-1 dance (breath) or Rin is not here")
class RealDanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pmx.load(RIN)
        cls.dance = vmd.load(REAL_DANCE)

    def test_the_known_jumps_are_found(self):
        # the spike (2026-10-10) found these one-frame jumps of the input: 右腕 1,899 -> 1,900, 左手首 5,963 -> 5,964,
        # the right hand's fingers 3,888 -> 3,889
        for first, last, bone, frame in ((1880, 1915, "右腕", 1899), (5950, 5980, "左手首", 5963),
                                         (3875, 3900, None, 3888)):
            result = motor_layer.layer(self.model, crop(self.dance, first, last), motor_layer.default_params())
            found = [(j["bone"], j["frame"] + first) for j in result.report["jumps"]]
            if bone is not None:
                self.assertIn((bone, frame), found)
            else:
                self.assertTrue(any(b.startswith("右") and "指" in b and f == frame for b, f in found), found)

    def test_the_left_hand_does_not_go_into_the_face_at_5914(self):
        result = motor_layer.layer(self.model, crop(self.dance, 5880, 5935), motor_layer.default_params())
        eyes_in = 0.5 * (result.world_in["左目"][0] + result.world_in["右目"][0])
        eyes_out = 0.5 * (result.world_out["左目"][0] + result.world_out["右目"][0])
        d_in = np.linalg.norm(result.world_in["左中指３"][0] - eyes_in, axis=1) * 80.0
        d_out = np.linalg.norm(result.world_out["左中指３"][0] - eyes_out, axis=1) * 80.0
        near = d_in < 200.0
        self.assertTrue(near.any())
        self.assertGreaterEqual(float(np.min((d_out - motor_layer.floor_of(d_in))[near])), -0.5)
        self.assertTrue(result.report["untouched"]["identical"])


if __name__ == "__main__":
    unittest.main()
