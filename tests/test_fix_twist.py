"""tools/fix_twist.py: move the forearm twist of a dance onto the wrist, so a cuff does not collapse."""
import contextlib
import glob
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest

from mmd_cli import mathutil
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("fix_twist", os.path.join(ROOT, "tools", "fix_twist.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fix_twist = load_tool()
AXIS = (1.0, 0.0, 0.0)                      # the forearm of the synthetic dancer lies along x


def about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def angle_between(a, b):
    """degrees between two rotations (q and -q are one rotation)"""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def twist_angle(q):
    return math.degrees(2.0 * math.acos(min(1.0, abs(q[3]))))


def bone(name, frame, rotation, pos=(0.0, 0.0, 0.0), curve=None):
    interpolation = vmd.bone_interpolation(curve) if curve else vmd.DEFAULT_BONE_INTERPOLATION
    return vmd.BoneKey(name, frame, pos, rotation, interpolation)


def dance(twists, wrists=None, extra=()):
    """a right arm whose hand twist follows `twists` ((frame, degrees) about the forearm) and whose wrist
    bends about z as `wrists` says; the left side mirrors it; `extra` keys ride along"""
    wrists = wrists or [(0, 0.0), (twists[-1][0], 30.0)]
    bones = []
    for side, sign in (("右", 1.0), ("左", -1.0)):
        bones += [bone(side + "手捩", f, about(AXIS, sign * d)) for f, d in twists]
        bones += [bone(side + "手首", f, about((0.0, 0.0, 1.0), sign * d)) for f, d in wrists]
    return vmd.Motion(model_name="dancer", bones=bones + list(extra))


_TRACKS = {}


def hand(motion, side, frame):
    """the rotation of the hand against the elbow at `frame`: twist then wrist"""
    if id(motion) not in _TRACKS:
        _TRACKS.clear()                                  # one motion at a time is enough; no stale ids
        _TRACKS[id(motion)] = fix_twist.tracks_of(motion)
    tracks = _TRACKS[id(motion)]
    t = fix_twist.sample(tracks[side + "手捩"], frame)[1]
    w = fix_twist.sample(tracks[side + "手首"], frame)[1]
    return mathutil.quat_multiply(t, w)


class SampleTest(unittest.TestCase):
    def test_between_two_keys_the_rotation_goes_the_short_way_eased_by_the_later_key(self):
        keys = [bone("右手捩", 0, about(AXIS, 0.0)), bone("右手捩", 10, about(AXIS, 90.0))]
        self.assertAlmostEqual(twist_angle(fix_twist.sample(keys, 5)[1]), 45.0, places=4)
        self.assertAlmostEqual(twist_angle(fix_twist.sample(keys, 10)[1]), 90.0, places=4)
        self.assertAlmostEqual(twist_angle(fix_twist.sample(keys, 99)[1]), 90.0, places=4)        # held after the last
        eased = [bone("右手捩", 0, about(AXIS, 0.0)), bone("右手捩", 10, about(AXIS, 90.0), curve=(64, 0, 64, 127))]
        self.assertLess(twist_angle(fix_twist.sample(eased, 2)[1]), 9.0)                         # slow start (linear: 18)
        self.assertAlmostEqual(twist_angle(fix_twist.sample(eased, 5)[1]), 45.0, delta=1.0)

    def test_the_position_follows_its_own_curves(self):
        keys = [bone("センター", 0, (0, 0, 0, 1), pos=(0.0, 0.0, 0.0)), bone("センター", 10, (0, 0, 0, 1), pos=(10.0, 2.0, -4.0))]
        pos, _ = fix_twist.sample(keys, 5)
        self.assertEqual(tuple(round(v, 4) for v in pos), (5.0, 1.0, -2.0))


class ShareTest(unittest.TestCase):
    def test_the_forearm_keeps_a_share_of_a_small_twist_and_none_of_a_half_turn(self):
        self.assertAlmostEqual(fix_twist.kept_twist(40.0, 0.5), 20.0)
        self.assertAlmostEqual(fix_twist.kept_twist(90.0, 0.5), 45.0)        # the most it ever keeps
        self.assertAlmostEqual(fix_twist.kept_twist(135.0, 0.5), 22.5)
        self.assertAlmostEqual(fix_twist.kept_twist(180.0, 0.5), 0.0)        # so the two ways round meet
        self.assertEqual(fix_twist.kept_twist(120.0, 0.0), 0.0)
        self.assertAlmostEqual(fix_twist.kept_twist(60.0, 1.0), 60.0)

    def test_a_share_outside_0_to_1_is_an_error(self):
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                fix_twist.fix(dance([(0, 0.0), (30, 120.0)]), share=bad)


class FixTest(unittest.TestCase):
    def test_the_hand_keeps_its_orientation_at_every_frame(self):
        before = dance([(0, 0.0), (20, 170.0), (40, -60.0), (60, 180.0), (90, 10.0)],
                       wrists=[(0, 0.0), (15, 40.0), (33, -20.0), (90, 25.0)])
        after, _ = fix_twist.fix(before, share=0.5)
        for side in ("右", "左"):
            for frame in range(0, 91):
                self.assertLess(angle_between(hand(before, side, frame), hand(after, side, frame)), 0.02, (side, frame))

    def test_the_forearm_never_twists_more_than_its_share_of_a_quarter_turn(self):
        before = dance([(0, 0.0), (20, 170.0), (40, -60.0), (60, 180.0), (90, 10.0)])
        after, report = fix_twist.fix(before, share=0.5)
        tracks = fix_twist.tracks_of(after)
        worst = max(twist_angle(k.rotation) for k in tracks["右手捩"])
        self.assertLessEqual(worst, 45.0 + 1e-3)
        at_180 = [k for k in tracks["右手捩"] if k.frame == 60][0]
        self.assertLess(twist_angle(at_180.rotation), 0.1)                   # a half turn is all in the wrist
        self.assertGreater(twist_angle([k for k in tracks["右手首"] if k.frame == 60][0].rotation), 150.0)
        self.assertEqual(report["pairs"][0]["twist"], "右手捩")
        self.assertAlmostEqual(report["pairs"][0]["max_twist_before"], 180.0, places=2)
        self.assertLessEqual(report["pairs"][0]["max_twist_after"], 45.01)

    def test_nothing_jumps_when_the_twist_passes_a_half_turn(self):
        # 170 degrees on to 190 (which a file holds as -170): the short way passes 180, where the twist axis flips
        before = dance([(0, 0.0), (30, 170.0), (40, -170.0), (70, 0.0)], wrists=[(0, 0.0), (70, 0.0)])
        after, _ = fix_twist.fix(before, share=0.5)
        tracks = fix_twist.tracks_of(after)
        for name in ("右手捩", "右手首"):
            keys = tracks[name]
            steps = [angle_between(a.rotation, b.rotation) for a, b in zip(keys, keys[1:])]
            # the dance turns 5.7 degrees a frame; past a quarter turn the wrist takes that and what the forearm
            # gives back (half as much again: 8.5).  A jump at the half turn would be 90 degrees or more
            self.assertLess(max(steps), 9.0, (name.encode("ascii", "backslashreplace"), max(steps)))

    def test_a_key_on_every_frame_of_the_span_with_straight_interpolation(self):
        before = dance([(10, 0.0), (50, 120.0)], wrists=[(0, 0.0), (80, 30.0)])
        after, report = fix_twist.fix(before, share=0.5)
        tracks = fix_twist.tracks_of(after)
        for name in ("右手捩", "右手首", "左手捩", "左手首"):
            frames = [k.frame for k in tracks[name]]
            self.assertEqual(frames, list(range(0, 81)), name)               # from the first key of the pair to the last
            for k in tracks[name]:
                self.assertEqual(vmd.bone_curves(k.interpolation)["rotation"], vmd.LINEAR_CURVE)
        self.assertEqual(report["pairs"][0]["frames"], [0, 80])
        self.assertEqual(report["pairs"][0]["keys_before"], {"twist": 2, "wrist": 2})
        self.assertEqual(report["pairs"][0]["keys_after"], {"twist": 81, "wrist": 81})

    def test_everything_else_is_left_as_it_was(self):
        arm = bone("右腕", 7, about((0.0, 0.0, 1.0), 33.0), curve=(64, 0, 64, 127))
        center = bone("センター", 3, (0.0, 0.0, 0.0, 1.0), pos=(1.0, 2.0, 3.0))
        before = dance([(0, 0.0), (30, 150.0)], extra=[arm, center])
        before.morphs.append(vmd.MorphKey("あ", 5, 0.5))
        after, _ = fix_twist.fix(before, share=0.5)
        self.assertEqual(after.model_name, "dancer")
        self.assertEqual(after.morphs, before.morphs)
        kept = [k for k in after.bones if k.name in ("右腕", "センター")]
        self.assertEqual(kept, [arm, center])
        self.assertEqual(len(before.bones), 2 + 4 * 2)                       # the input is not touched
        self.assertEqual(twist_angle([k for k in before.bones if k.name == "右手捩"][-1].rotation), 150.0)

    def test_one_side_alone_and_no_twist_at_all(self):
        only_right = vmd.Motion(model_name="m", bones=[bone("右手捩", 0, about(AXIS, 0.0)), bone("右手捩", 20, about(AXIS, 120.0))])
        after, report = fix_twist.fix(only_right, share=0.5)
        self.assertEqual([p["twist"] for p in report["pairs"]], ["右手捩"])
        wrist = [k for k in after.bones if k.name == "右手首"]
        self.assertEqual(len(wrist), 21)                                     # a wrist without keys rests: it gets the twist
        with self.assertRaises(ValueError):
            fix_twist.fix(vmd.Motion(model_name="m", bones=[bone("右腕", 0, (0, 0, 0, 1))]), share=0.5)


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fix_twist.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(dance([(0, 0.0), (30, 180.0), (60, 20.0)])))

    def test_writes_the_dance_and_the_report(self):
        out, report = os.path.join(self.folder, "sub", "fixed.vmd"), os.path.join(self.folder, "r.json")
        code, result = run([self.dance, out, "--report", report])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual((result["in"], result["out"]), (os.path.abspath(self.dance), os.path.abspath(out)))
        self.assertEqual(result["share"], 0.5)
        back = vmd.load(out)
        self.assertEqual(result["bone_keys"], len(back.bones))
        self.assertEqual(len(result["pairs"]), 2)
        self.assertLessEqual(max(p["max_twist_after"] for p in result["pairs"]), 45.01)
        with open(report, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["pairs"], result["pairs"])
        self.assertEqual(os.listdir(os.path.dirname(out)), ["fixed.vmd"])

    def test_the_dance_is_never_written_over(self):
        with open(self.dance, "rb") as f:
            original = f.read()
        for argv in ([self.dance, self.dance], [self.dance, os.path.join(self.folder, "o.vmd"), "--report", self.dance],
                     [self.dance, os.path.join(self.folder, "o.vmd"), "--share", "2"],
                     [os.path.join(self.folder, "none.vmd"), os.path.join(self.folder, "o.vmd")]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertFalse(os.path.exists(os.path.join(self.folder, "o.vmd")), argv)
        with open(self.dance, "rb") as f:
            self.assertEqual(f.read(), original)


def real_dance():
    folder = ROOT
    for _ in range(4):
        pattern = os.path.join(folder, "_spike", "out", "hibikase", "enuta", "**", "*.vmd")
        found = [p for p in glob.glob(pattern, recursive=True)
                 if "ダンス" in os.path.basename(p) and "袖の値なし" in os.path.basename(p)]
        if found:
            return found[0]
        folder = os.path.dirname(folder)
    return None


REAL = real_dance()


@unittest.skipUnless(REAL, "the distributed dance is not on this machine")
class RealDanceTest(unittest.TestCase):
    def test_the_hand_twist_of_the_whole_dance_is_tamed_and_the_hands_stay(self):
        before = vmd.load(REAL)
        after, report = fix_twist.fix(before, share=0.5)
        self.assertEqual([p["twist"] for p in report["pairs"]], ["右手捩", "左手捩"])
        for pair in report["pairs"]:
            self.assertGreater(pair["max_twist_before"], 179.0)
            self.assertLessEqual(pair["max_twist_after"], 45.01)
        back = vmd.loads(vmd.dumps(after))                                   # as a file holds it (float32)
        for side in ("右", "左"):
            for frame in range(0, 7743, 37):
                self.assertLess(angle_between(hand(before, side, frame), hand(back, side, frame)), 0.05, (side, frame))
        untouched = [k for k in before.bones if k.name not in ("右手捩", "右手首", "左手捩", "左手首")]
        self.assertEqual([k for k in after.bones if k.name not in ("右手捩", "右手首", "左手捩", "左手首")], untouched)


if __name__ == "__main__":
    unittest.main()
