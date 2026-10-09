"""tools/breath_layer.py: breathing, an inhale before each sung line and a moving hold, layered onto a baked dance."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import time
import unittest

from mmd_cli import fk, mathutil
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("breath_layer", os.path.join(ROOT, "tools", "breath_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


breath_layer = load_tool()
LAST = 360                      # 12 seconds
UNIT_MM = 80.0
FPS = 30.0


def rin_like_bytes(hand_at_face=False, shoulder_parent=False):
    """the bones of Sour's Rin that the layer reads or writes, at her rest positions (model units).  hand_at_face puts
    the left middle finger tip 3 cm in front of the left eye; shoulder_parent adds 左肩P and 左肩C (左肩C takes 左肩P's
    turn with ratio -1, as on Rin) between the chest and the left arm"""
    w = Writer(bone=2)
    left_tip = (0.3, 17.0, -0.95) if hand_at_face else (5.5, 11.8, -0.24)
    bones = [("全ての親", None, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.85, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("下半身", "センター", (0.0, 12.225, -0.649), {}),
             ("上半身", "センター", (0.0, 12.225, -0.649), {}),
             ("上半身2", "上半身", (0.0, 13.798, -0.678), {}),
             ("首", "上半身2", (0.0, 15.646, -0.134), {}),
             ("頭", "首", (0.0, 16.243, 0.0), {}),
             ("左目", "頭", (0.41, 17.214, -0.562), {}),
             ("右目", "頭", (-0.41, 17.214, -0.562), {})]
    if shoulder_parent:
        bones += [("左肩P", "上半身2", (0.23, 15.393, -0.222), {}),
                  ("左肩", "左肩P", (0.23, 15.393, -0.222), {}),
                  ("左肩C", "左肩", (0.911, 15.277, -0.248), {"flags": NORMAL | APPEND_ROTATE, "append": "左肩P"}),
                  ("左腕", "左肩C", (0.911, 15.277, -0.248), {})]
    else:
        bones += [("左肩", "上半身2", (0.23, 15.393, -0.222), {}),
                  ("左腕", "左肩", (0.911, 15.277, -0.248), {})]
    bones += [("左ひじ", "左腕", (2.907, 13.732, -0.27), {}),
              ("左手首", "左ひじ", (4.652, 12.41, -0.237), {}),
              ("左中指３", "左手首", left_tip, {}),
              ("右肩", "上半身2", (-0.23, 15.393, -0.222), {}),
              ("右腕", "右肩", (-0.911, 15.277, -0.248), {}),
              ("右ひじ", "右腕", (-2.907, 13.732, -0.27), {}),
              ("右手首", "右ひじ", (-4.652, 12.41, -0.237), {}),
              ("右中指３", "右手首", (-5.5, 11.8, -0.24), {}),
              ("左足ＩＫ", "全ての親", (1.12, 1.745, 0.37), {"flags": NORMAL | TRANSLATE})]
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"]], -1.0)
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-like", bones=built)


MODEL = pmx.loads(rin_like_bytes())


def key(name, frame, ui=(0.0, 0.0, 0.0), position=(0.0, 0.0, 0.0)):
    return vmd.BoneKey(name, frame, tuple(position), mathutil.ui_to_quat(*ui))


POSE = {"上半身": (-15.0, 5.0, 0.0), "上半身2": (5.0, 0.0, 3.0), "頭": (10.0, -20.0, 0.0), "左肩": (0.0, 0.0, 5.0),
        "左腕": (20.0, 30.0, 35.0), "右腕": (10.0, -25.0, -35.0), "下半身": (5.0, 0.0, 0.0)}


def still_dance(last=LAST, extra=()):
    """a dance holding one pose: keys on the first and last frame (as smooth_motion leaves a hold), a morph key"""
    keys = [key("センター", 0, position=(0.0, -0.2, 0.1)), key("センター", last, position=(0.0, -0.2, 0.1)),
            key("左足ＩＫ", 0, position=(0.1, 0.0, 0.2)), key("左足ＩＫ", last, position=(0.1, 0.0, 0.2))]
    for name, ui in POSE.items():
        keys += [key(name, 0, ui), key(name, last, ui)]
    keys += list(extra)
    return vmd.Motion(model_name="dancer", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 90, 0.0)])


def busy_dance(last=LAST):
    """the same pose with the upper body swinging 40 degrees about Y every 10 frames (120 deg/s) all along"""
    keys = [k for k in still_dance(last).bones if k.name != "上半身"]
    for frame in range(0, last + 1, 10):
        sign = 1.0 if (frame // 10) % 2 == 0 else -1.0
        keys.append(key("上半身", frame, (-15.0, 5.0 + 20.0 * sign, 0.0)))
    return vmd.Motion(model_name="dancer", bones=keys)


def run_layer(dance=None, model=MODEL, lines=(), seed=0, **kw):
    return breath_layer.breathe(model, dance if dance is not None else still_dance(), lines=lines, seed=seed, **kw)


def world(model, motion, names, last=LAST):
    return fk.world_track(model, motion, names, 0, last)


def speeds(track, scale):
    """per frame step (frame f-1 -> f, f >= 1) of positions, times FPS and scale"""
    return [math.dist(track[f - 1][0], track[f][0]) * FPS * scale for f in range(1, len(track))]


def turn_speeds(track):
    out = []
    for f in range(1, len(track)):
        d = fk.multiply(fk.conjugate(track[f - 1][1]), track[f][1])
        out.append(math.degrees(2.0 * math.atan2(math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2), abs(d[3]))) * FPS)
    return out


def in_frame(rotation, origin, point):
    """point - origin in the frame of `rotation`"""
    return fk.rotate(fk.conjugate(rotation), tuple(p - o for p, o in zip(point, origin)))


def rotation_vector_degrees(q):
    if q[3] < 0.0:
        q = tuple(-v for v in q)
    n = math.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    angle = math.degrees(2.0 * math.atan2(n, q[3]))
    return tuple(angle * v / n for v in q[:3])


def key_bytes(keys):
    return [(k.raw_name, k.name, k.frame, k.position, k.rotation, k.interpolation) for k in keys]


class StillPoseTest(unittest.TestCase):
    """a held pose gets breathing and a moving hold; the a20 measure of a frozen torso finds nothing"""

    @classmethod
    def setUpClass(cls):
        cls.dance = still_dance()
        cls.result = run_layer(cls.dance)
        names = ["センター", "上半身2", "左目", "右目", "頭"]
        cls.before = world(MODEL, cls.dance, names)
        cls.after = world(MODEL, cls.result.motion, names)

    def test_the_torso_is_never_frozen(self):
        # a20: the torso is frozen on a frame when センター and 上半身2 move less than 0.5 cm/s and 上半身2 turns less than
        # 1 deg/s.  The input is frozen on every frame; the output on none
        center = speeds(self.after["センター"], 8.0)
        chest = speeds(self.after["上半身2"], 8.0)
        chest_turn = turn_speeds(self.after["上半身2"])
        self.assertTrue(all(v == 0.0 for v in speeds(self.before["上半身2"], 8.0)))
        frozen = [f for f, (a, b, c) in enumerate(zip(center, chest, chest_turn), 1) if a < 0.5 and b < 0.5 and c < 1.0]
        self.assertEqual(frozen, [])
        self.assertGreater(min(chest_turn), 1.0)
        self.assertLess(max(chest_turn), 6.0)                        # a moving hold, not a dance

    def test_the_head_moves_like_a_person_standing_still(self):
        # a01: the head of a person trying to stand still moves 3.9 to 14 mm/s; the layer aims at 3 to 9
        eyes = [max(a, b, c) for a, b, c in zip(speeds(self.after["左目"], UNIT_MM), speeds(self.after["右目"], UNIT_MM),
                                                speeds(self.after["頭"], UNIT_MM))]
        eyes.sort()
        median = eyes[len(eyes) // 2]
        self.assertTrue(3.0 <= median <= 9.0, median)
        self.assertGreater(eyes[int(0.05 * len(eyes))], 1.0)
        self.assertLess(eyes[int(0.95 * len(eyes))], 14.0)

    def test_the_pose_stays_the_pose(self):
        # the layer is a few degrees at most: the chest turns less than 2.5 degrees away from the choreographed pose
        for f in range(0, LAST + 1, 7):
            d = fk.multiply(fk.conjugate(self.before["上半身2"][f][1]), self.after["上半身2"][f][1])
            self.assertLess(math.degrees(2.0 * math.acos(min(1.0, abs(d[3])))), 2.5, f)

    def test_the_input_is_not_changed(self):
        self.assertEqual(key_bytes(self.dance.bones), key_bytes(still_dance().bones))


class CompositionTest(unittest.TestCase):
    def test_the_composed_poses_are_those_of_the_written_motion(self):
        # the report and the last check use poses composed from the input's; they must be what mmd_cli.fk finds in
        # the written file, through the shoulder parent and its cancel bone too
        model = pmx.loads(rin_like_bytes(shoulder_parent=True))
        dance = busy_dance()
        dance.bones = [k for k in dance.bones if k.name != "左腕"]
        dance.bones += [key("左肩P", 0, (0.0, 0.0, 10.0)), key("左肩P", LAST, (0.0, 0.0, 10.0)),
                        key("左腕", 0, (20.0, 30.0, 35.0)), key("左腕", LAST, (-10.0, 40.0, 50.0))]   # not about Z alone
        plan = breath_layer.Plan(model, dance, [(3.0, 6.0)], 0, 1.0)
        deltas = plan.deltas()
        composed = plan.compose(deltas)
        written = world(model, plan.build(deltas), [n for n, _ in plan.chain])
        for name, _ in plan.chain:
            for f in range(0, LAST + 1, 5):
                self.assertLess(math.dist(composed[name][f][0], written[name][f][0]), 1e-5, (name, f))
                dot = abs(sum(a * b for a, b in zip(composed[name][f][1], written[name][f][1])))
                self.assertGreater(dot, 1.0 - 1e-9, (name, f))


class WhatIsWrittenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dance = still_dance()
        cls.result = run_layer(cls.dance)

    def test_bones_it_does_not_layer_are_kept_byte_for_byte(self):
        layered = set(breath_layer.LAYERED)
        self.assertNotIn("センター", layered)
        self.assertNotIn("左足ＩＫ", layered)
        self.assertNotIn("頭", layered)
        kept_in = [k for k in self.dance.bones if k.name not in layered]
        kept_out = [k for k in self.result.motion.bones if k.name not in layered]
        self.assertEqual(key_bytes(kept_out), key_bytes(kept_in))
        self.assertEqual(vmd.dumps(vmd.Motion(bones=kept_out)), vmd.dumps(vmd.Motion(bones=kept_in)))
        self.assertEqual(self.result.motion.morphs, self.dance.morphs)
        self.assertEqual(self.result.motion.model_name, "dancer")

    def test_the_layered_bones_have_a_linear_key_on_every_frame(self):
        for name in breath_layer.LAYERED:
            frames = [k.frame for k in self.result.motion.bones if k.name == name]
            self.assertEqual(frames, list(range(LAST + 1)), name)
            for k in self.result.motion.bones:
                if k.name == name:
                    self.assertEqual(vmd.bone_curves(k.interpolation)["rotation"], vmd.LINEAR_CURVE)

    def test_the_same_seed_gives_the_same_file(self):
        again = run_layer(still_dance())
        self.assertEqual(vmd.dumps(again.motion), vmd.dumps(self.result.motion))
        other = run_layer(still_dance(), seed=1)
        self.assertNotEqual(vmd.dumps(other.motion), vmd.dumps(self.result.motion))

    def test_physics_bytes_of_the_original_keys_are_kept(self):
        k0 = key("上半身", 0, POSE["上半身"])
        k0.interpolation = vmd.bone_interpolation(vmd.LINEAR_CURVE, keep=bytes([0, 0, 99, 99] + [0] * 60))
        dance = still_dance()
        dance.bones = [k0 if (k.name, k.frame) == ("上半身", 0) else k for k in dance.bones]
        out = [k for k in run_layer(dance).motion.bones if k.name == "上半身"]
        self.assertEqual((out[0].interpolation[2], out[0].interpolation[3]), (99, 99))
        self.assertEqual((out[100].interpolation[2], out[100].interpolation[3]), (99, 99))


class ShoulderTest(unittest.TestCase):
    def check_arm_follows_the_chest(self, model, dance):
        result = run_layer(dance, model=model)
        names = ["上半身2", "左腕", "左手首", "右腕"]
        before, after = world(model, dance, names), world(model, result.motion, names)
        lifts = []
        for f in range(0, LAST + 1, 3):
            for arm in ("左腕", "右腕"):
                # the upper arm keeps its turn against the chest: the shoulder lifts it, it does not swing it
                rb = fk.multiply(fk.conjugate(before["上半身2"][f][1]), before[arm][f][1])
                ra = fk.multiply(fk.conjugate(after["上半身2"][f][1]), after[arm][f][1])
                self.assertLess(math.degrees(2.0 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(rb, ra)))))), 1e-3)
            wb = in_frame(before["上半身2"][f][1], before["上半身2"][f][0], before["左手首"][f][0])
            wa = in_frame(after["上半身2"][f][1], after["上半身2"][f][0], after["左手首"][f][0])
            self.assertLess(math.dist(wa, wb) * UNIT_MM, 4.5)
            ab = in_frame(before["上半身2"][f][1], before["上半身2"][f][0], before["左腕"][f][0])
            aa = in_frame(after["上半身2"][f][1], after["上半身2"][f][0], after["左腕"][f][0])
            lifts.append((aa[1] - ab[1]) * UNIT_MM)
        self.assertGreater(max(lifts), 1.5)                          # an inhale lifts the shoulder by millimetres
        self.assertGreater(min(lifts), -0.5)                         # and never pushes it down

    def test_the_arms_are_lifted_with_the_shoulders_not_swung(self):
        self.check_arm_follows_the_chest(MODEL, still_dance())

    def test_also_through_a_shoulder_parent_and_its_cancel_bone(self):
        model = pmx.loads(rin_like_bytes(shoulder_parent=True))
        dance = still_dance(extra=[key("左肩P", 0, (0.0, 0.0, 10.0)), key("左肩P", LAST, (0.0, 0.0, 10.0))])
        self.check_arm_follows_the_chest(model, dance)

    def test_a_hand_at_the_face_stays_there(self):
        model = pmx.loads(rin_like_bytes(hand_at_face=True))
        dance = still_dance()
        dance.bones = [k for k in dance.bones if k.name not in ("左肩", "左腕", "頭")]      # the hand rests at the face
        result = run_layer(dance, model=model)
        names = ["左中指３", "左目", "右目", "右中指３"]
        before, after = world(model, dance, names), world(model, result.motion, names)

        def gap(track, f, tip):
            eyes = tuple((a + b) / 2.0 for a, b in zip(track["左目"][f][0], track["右目"][f][0]))
            return math.dist(track[tip][f][0], eyes) * UNIT_MM

        self.assertLess(gap(before, 0, "左中指３"), 60.0)
        worst = max(abs(gap(after, f, "左中指３") - gap(before, f, "左中指３")) for f in range(LAST + 1))
        self.assertLess(worst, 1.0)
        far = max(abs(gap(after, f, "右中指３") - gap(before, f, "右中指３")) for f in range(LAST + 1))
        self.assertGreater(far, 1.0)                                  # the other hand is far: its shoulder breathes


class LineTest(unittest.TestCase):
    """an inhale before each sung line: the shoulders lift and the chest opens in the 0.7 s before the line"""

    LINES = ((2.0, 4.6), (5.0, 8.0), (8.4, 11.0))

    def layer_signals(self, lines):
        dance = still_dance()
        result = run_layer(dance, lines=lines)
        names = ["上半身", "上半身2", "左腕", "右腕"]
        before, after = world(MODEL, dance, names), world(MODEL, result.motion, names)
        lift, pitch = [], []
        for f in range(LAST + 1):
            h = []
            for track in (before, after):
                arms = [in_frame(track["上半身2"][f][1], track["上半身2"][f][0], track[a][f][0])[1] for a in ("左腕", "右腕")]
                h.append(sum(arms) / 2.0 * UNIT_MM)
            lift.append(h[1] - h[0])
            rb = fk.multiply(fk.conjugate(before["上半身"][f][1]), before["上半身2"][f][1])
            ra = fk.multiply(fk.conjugate(after["上半身"][f][1]), after["上半身2"][f][1])
            pitch.append(rotation_vector_degrees(fk.multiply(fk.conjugate(rb), ra))[0])
        return result, lift, pitch

    def test_each_line_has_an_inhale_before_it(self):
        result, lift, pitch = self.layer_signals(self.LINES)
        for start, _ in self.LINES:
            t0 = int(round(start * FPS))
            d_lift = sum(lift[t0 - 6:t0]) / 6.0 - sum(lift[t0 - 30:t0 - 24]) / 6.0           # a06's D
            d_pitch = sum(pitch[t0 - 6:t0]) / 6.0 - sum(pitch[t0 - 30:t0 - 24]) / 6.0
            self.assertGreater(d_lift, 1.0, start)
            self.assertGreater(d_pitch, 0.4, start)                   # + is the chest opening (leaning back)
            peak = max(range(t0 - 30, t0 + 15), key=lambda f: lift[f])
            self.assertLessEqual(abs(peak - t0), 8, start)
        self.assertEqual(result.report["lines"]["count"], 3)
        self.assertEqual(result.report["lines"]["inhales"], 3)

    def test_a_shifted_line_shifts_its_inhale(self):
        _, a, _ = self.layer_signals(((5.0, 8.0),))
        _, b, _ = self.layer_signals(((5.3, 8.3),))
        peak_a = max(range(120, 170), key=lambda f: a[f])
        peak_b = max(range(120, 180), key=lambda f: b[f])
        self.assertTrue(8 <= peak_b - peak_a <= 10, (peak_a, peak_b))

    def test_lines_closer_than_an_inhale_still_work(self):
        result, lift, _ = self.layer_signals(((3.0, 3.4), (3.3, 6.0), (3.35, 6.0)))
        self.assertTrue(all(math.isfinite(v) for v in lift))
        self.assertGreaterEqual(result.report["lines"]["inhales"], 1)

    def test_lines_from_the_cue_file(self):
        cues = {"cues": [{"id": "t", "start": 1.0, "end": 3.0, "lines": [{"text": "x", "style": "logo"}]},
                         {"id": "l1", "start": 32.633, "end": 35.35, "style": "lyric", "text": "a"},
                         {"id": "l0", "start": 30.0, "end": 32.7, "style": "lyric", "text": "b"},
                         {"id": "h", "start": 40.0, "end": 41.0, "style": "hook", "text": "c"}]}
        self.assertEqual(breath_layer.lines_from_cues(cues), [(30.0, 32.7), (32.633, 35.35)])


class MotionTest(unittest.TestCase):
    def test_a_big_motion_gets_only_a_trace_of_the_layer(self):
        def added(dance):
            result = run_layer(dance)
            out = {}
            for name in ("上半身", "上半身2"):
                ka = {k.frame: k for k in dance.bones if k.name == name}
                tr = fk.tracks_of(dance)[name]
                frames = [k.frame for k in tr]
                worst = 0.0
                for k in result.motion.bones:
                    if k.name == name and 60 <= k.frame <= LAST - 60:
                        q = fk.sample(tr, k.frame, frames)[1]
                        d = fk.multiply(fk.conjugate(q), k.rotation)
                        worst = max(worst, math.degrees(2.0 * math.acos(min(1.0, abs(d[3])))))
                out[name] = worst
            return out

        still, busy = added(still_dance()), added(busy_dance())
        self.assertGreater(still["上半身2"], 0.9)
        self.assertLess(busy["上半身2"], 0.6 * still["上半身2"])
        self.assertLess(busy["上半身"], 0.5 * still["上半身"])

    def test_before_the_first_move_she_breathes_in_and_sinks(self):
        # still for 4 s, then the head lifts 20 degrees in 1 s: an inhale, then a small sink of the upper body just
        # before the head starts (the anticipation)
        move = 120
        extra = [key("頭", move, POSE["頭"]), key("頭", move + 30, (POSE["頭"][0] - 20.0, POSE["頭"][1], 0.0))]
        dance = still_dance()
        dance.bones = [k for k in dance.bones if not (k.name == "頭" and k.frame == LAST)] + extra + [
            key("頭", LAST, (POSE["頭"][0] - 20.0, POSE["頭"][1], 0.0))]
        result = run_layer(dance)
        self.assertEqual(result.report["intro"]["first_move_frame"], move)
        names = ["上半身", "上半身2", "センター"]
        before, after = world(MODEL, dance, names), world(MODEL, result.motion, names)

        def spine_pitch(f):
            rb = fk.multiply(fk.conjugate(before["センター"][f][1]), before["上半身"][f][1])
            ra = fk.multiply(fk.conjugate(after["センター"][f][1]), after["上半身"][f][1])
            return rotation_vector_degrees(fk.multiply(fk.conjugate(rb), ra))[0]

        def chest_pitch(f):
            rb = fk.multiply(fk.conjugate(before["上半身"][f][1]), before["上半身2"][f][1])
            ra = fk.multiply(fk.conjugate(after["上半身"][f][1]), after["上半身2"][f][1])
            return rotation_vector_degrees(fk.multiply(fk.conjugate(rb), ra))[0]

        # inhaled shortly before the move (the chest open more than a second earlier)
        self.assertGreater(chest_pitch(move - 10), chest_pitch(move - 45) + 0.3)
        # the sink: the upper body bends forward (negative X) right before the move, more than a moment earlier
        self.assertLess(spine_pitch(move - 3), spine_pitch(move - 20) - 0.3)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        self.model = os.path.join(self.folder, "model.pmx")
        vmd.dump(still_dance(), self.dance)
        with open(self.model, "wb") as f:
            f.write(rin_like_bytes())

    def run_main(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = breath_layer.main(args)
        return code, json.loads(out.getvalue())

    def test_writes_the_motion_and_the_report(self):
        cues = os.path.join(self.folder, "cues.json")
        with open(cues, "w", encoding="utf-8") as f:
            json.dump({"cues": [{"start": 5.0, "end": 8.0, "style": "lyric", "text": "x"}]}, f)
        out, report = os.path.join(self.folder, "o.vmd"), os.path.join(self.folder, "r.json")
        code, summary = self.run_main([self.dance, self.model, out, "--cues", cues, "--report", report])
        self.assertEqual(code, 0, summary)
        self.assertTrue(summary["ok"])
        back = vmd.load(out)
        self.assertEqual(len([k for k in back.bones if k.name == "上半身"]), LAST + 1)
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertEqual(full["torso_frozen"]["after"]["frames"], 0)
        self.assertGreater(full["torso_frozen"]["before"]["frames"], 300)
        self.assertEqual(full["lines"]["count"], 1)
        self.assertTrue(full["untouched"]["identical"])
        self.assertEqual(summary["torso_frozen"]["after"]["frames"], 0)

    def test_the_input_is_never_written_over(self):
        code, summary = self.run_main([self.dance, self.model, self.dance])
        self.assertEqual(code, 2)
        self.assertFalse(summary["ok"])

    def test_a_model_without_the_chest_is_an_error(self):
        w = Writer()
        with open(self.model, "wb") as f:
            f.write(w.build(bones=[w.bone("センター"), w.bone("上半身", parent=0)]))
        code, summary = self.run_main([self.dance, self.model, os.path.join(self.folder, "o.vmd")])
        self.assertEqual(code, 2)
        self.assertIn("上半身2", summary["error"]["message"])


def real_file(*parts):
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    return None


REAL_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_final_dn6_twist.vmd")
REAL_CUES = real_file("_spike", "out", "hibikase", "mv", "production", "cues_mv.json")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"


@unittest.skipUnless(REAL_DANCE and REAL_CUES and os.path.isfile(RIN), "the dance, the cues or Sour's Rin is not here")
class RealSongTest(unittest.TestCase):
    def test_the_whole_song(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out, report = os.path.join(folder, "breath.vmd"), os.path.join(folder, "r.json")
        started = time.time()
        summary = breath_layer.run(REAL_DANCE, RIN, out, cues_path=REAL_CUES, report_path=report)
        self.assertLess(time.time() - started, 60.0)
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertGreater(full["torso_frozen"]["before"]["dance_share"], 0.05)          # a20: 5.7 %
        self.assertEqual(full["torso_frozen"]["after"]["frames"], 0)
        self.assertTrue(full["untouched"]["identical"])
        self.assertEqual(full["lines"]["count"], 48)
        self.assertEqual(full["lines"]["inhales"], 48)
        holds = full["head_in_holds"]["after"]
        self.assertTrue(3.0 <= holds["median"] <= 9.0, holds)
        self.assertLess(full["contacts"]["hand_face"]["max_change_mm"], 3.0)
        dance, back = vmd.load(REAL_DANCE), vmd.load(out)
        for name in ("センター", "左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ"):
            self.assertEqual(key_bytes([k for k in back.bones if k.name == name]),
                             key_bytes([k for k in dance.bones if k.name == name]), name)
        self.assertEqual(summary["frames"], [0, 7742])


if __name__ == "__main__":
    unittest.main()
