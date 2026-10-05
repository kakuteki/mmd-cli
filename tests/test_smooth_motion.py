"""tools/smooth_motion.py: C1 curves through the keys of a dance, baked to a key per frame; tools/motion_jerk.py: the acceleration."""
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

from mmd_cli import mathutil
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smooth_motion = load_tool("smooth_motion")
motion_jerk = load_tool("motion_jerk")
IDENTITY = (0.0, 0.0, 0.0, 1.0)
EASE = (64, 0, 64, 127)                         # an authored curve: slow start and end


def about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def angle_between(a, b):
    """degrees between two rotations (q and -q are one rotation)"""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def bone(name, frame, pos=(0.0, 0.0, 0.0), rot=IDENTITY, curve=None):
    interpolation = vmd.bone_interpolation(curve) if curve else vmd.DEFAULT_BONE_INTERPOLATION
    return vmd.BoneKey(name, frame, tuple(float(v) for v in pos), tuple(float(v) for v in rot), interpolation)


def track_of(motion, name):
    return sorted((k for k in motion.bones if k.name == name), key=lambda k: k.frame)


def zigzag(name="センター", amplitude=10.0, n=6, gap=10, rotate=False):
    """6 keys 10 frames apart going there and back: the velocity flips sign at every key"""
    keys = []
    for i in range(n):
        v = amplitude if i % 2 else 0.0
        if rotate:
            keys.append(bone(name, i * gap, rot=about((0.0, 0.0, 1.0), v * 3.0)))
        else:
            keys.append(bone(name, i * gap, pos=(v, 0.0, 0.0)))
    return keys


def per_frame(keys, first=None, last=None):
    """[(position, rotation)] MMD shows at every frame of the span, from the keys and their curves"""
    first = keys[0].frame if first is None else first
    last = keys[-1].frame if last is None else last
    frames = [k.frame for k in keys]
    return [smooth_motion.sample(keys, f, frames) for f in range(first, last + 1)]


def max_position_acceleration(path):
    pos = [p for p, _ in path]
    worst = 0.0
    for a, b, c in zip(pos, pos[1:], pos[2:]):
        worst = max(worst, math.sqrt(sum((x - 2 * y + z) ** 2 for x, y, z in zip(a, b, c))))
    return worst


def max_rotation_acceleration(path):
    rots = [r for _, r in path]
    steps = [smooth_motion.log_map(smooth_motion.relative(a, b)) for a, b in zip(rots, rots[1:])]
    worst = 0.0
    for a, b in zip(steps, steps[1:]):
        worst = max(worst, math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))
    return worst


class QuaternionMathTest(unittest.TestCase):
    def test_log_and_exp_are_inverses_and_the_log_is_the_rotation_vector(self):
        q = about((0.0, 1.0, 0.0), 50.0)
        v = smooth_motion.log_map(q)
        self.assertAlmostEqual(math.degrees(math.sqrt(sum(x * x for x in v))), 50.0, places=6)
        self.assertLess(angle_between(smooth_motion.exp_map(v), q), 1e-6)
        self.assertEqual(smooth_motion.log_map(IDENTITY), (0.0, 0.0, 0.0))
        self.assertLess(angle_between(smooth_motion.exp_map((0.0, 0.0, 0.0)), IDENTITY), 1e-9)
        # q and -q are one rotation: the log takes the short way
        v2 = smooth_motion.log_map(tuple(-x for x in q))
        self.assertAlmostEqual(math.degrees(math.sqrt(sum(x * x for x in v2))), 50.0, places=6)

    def test_relative_is_the_turn_from_a_to_b(self):
        a, b = about((1.0, 0.0, 0.0), 20.0), about((1.0, 0.0, 0.0), 65.0)
        r = smooth_motion.relative(a, b)
        self.assertLess(angle_between(r, about((1.0, 0.0, 0.0), 45.0)), 1e-6)
        self.assertLess(angle_between(mathutil.quat_multiply(a, r), b), 1e-6)


class HermiteTest(unittest.TestCase):
    def test_a_straight_line_at_uniform_speed_stays_a_straight_line(self):
        keys = [bone("センター", 10 * i, pos=(2.0 * i, -1.0 * i, 0.5 * i)) for i in range(6)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "センター")
        self.assertEqual([k.frame for k in track], list(range(0, 51)))
        for k in track:
            expected = (0.2 * k.frame, -0.1 * k.frame, 0.05 * k.frame)
            for got, want in zip(k.position, expected):
                self.assertAlmostEqual(got, want, places=9, msg=k.frame)

    def test_a_steady_turn_about_one_axis_stays_a_steady_turn(self):
        keys = [bone("右腕", 10 * i, rot=about((0.0, 1.0, 0.0), 12.0 * i)) for i in range(6)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        for k in track_of(out, "右腕"):
            self.assertLess(angle_between(k.rotation, about((0.0, 1.0, 0.0), 1.2 * k.frame)), 1e-6, k.frame)

    def test_the_zigzag_loses_its_velocity_jumps_at_the_keys(self):
        for rotate in (False, True):
            keys = zigzag(rotate=rotate)
            before = per_frame(keys)
            out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
            track = track_of(out, "センター")
            after = per_frame(track)
            self.assertEqual(len(after), len(before))
            measure = max_rotation_acceleration if rotate else max_position_acceleration
            spike, smoothed = measure(before), measure(after)
            self.assertGreater(spike / smoothed, 3.0, (rotate, spike, smoothed))
            # the second difference is bounded all along: no spike survives at any key
            self.assertLess(smoothed, 0.35 * spike)

    def test_tension_zero_eases_every_segment_and_tension_scales_the_tangents(self):
        keys = [bone("センター", 10 * i, pos=(2.0 * i, 0.0, 0.0)) for i in range(4)]
        motion = vmd.Motion(model_name="m", bones=keys)
        eased, _ = smooth_motion.smooth(motion, tension=0.0)
        self.assertLess(track_of(eased, "センター")[1].position[0], 0.2 * 0.5)              # slow start of every segment
        self.assertAlmostEqual(track_of(eased, "センター")[15].position[0], 3.0, places=9)   # symmetric
        half, _ = smooth_motion.smooth(motion, tension=0.5)
        self.assertAlmostEqual(track_of(half, "センター")[15].position[0], 3.0, places=9)
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                smooth_motion.smooth(motion, tension=bad)


class KeysTest(unittest.TestCase):
    def test_every_original_key_is_kept_exactly_and_the_rest_is_a_key_per_frame_with_straight_curves(self):
        keys = [bone("右腕", 3, pos=(1.0, 2.0, 3.0), rot=about((1.0, 0.0, 0.0), 10.0)),
                bone("右腕", 9, pos=(0.5, -2.0, 1.0), rot=about((0.0, 1.0, 0.0), 40.0)),
                bone("右腕", 20, pos=(4.0, 0.0, -1.0), rot=about((0.0, 0.0, 1.0), -70.0)),
                bone("右腕", 25, pos=(4.0, 1.0, -1.0), rot=about((0.0, 0.0, 1.0), -30.0))]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右腕")
        self.assertEqual([k.frame for k in track], list(range(3, 26)))
        by_frame = {k.frame: k for k in track}
        for k in keys:
            self.assertEqual(by_frame[k.frame].position, k.position)
            self.assertLess(angle_between(by_frame[k.frame].rotation, k.rotation), 1e-6)
        for k in track:
            self.assertEqual(set(vmd.bone_curves(k.interpolation).values()), {vmd.LINEAR_CURVE})
        self.assertEqual(report["bones"][0]["name"], "右腕")
        self.assertEqual((report["bones"][0]["keys_before"], report["bones"][0]["keys_after"]), (4, 23))

    def test_an_authored_segment_is_reproduced_from_its_own_curve(self):
        keys = [bone("センター", 0, pos=(0.0, 0.0, 0.0)),
                bone("センター", 10, pos=(10.0, 0.0, 0.0), rot=about((0.0, 1.0, 0.0), 60.0), curve=EASE),
                bone("センター", 20, pos=(0.0, 5.0, 0.0)),
                bone("センター", 30, pos=(0.0, 0.0, 0.0), rot=about((0.0, 1.0, 0.0), -20.0), curve=(0, 127, 127, 0))]
        original = per_frame(keys)
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "センター")
        for frame in list(range(0, 11)) + list(range(20, 31)):
            pos, rot = original[frame]
            for got, want in zip(track[frame].position, pos):
                self.assertAlmostEqual(got, want, delta=1e-4, msg=frame)
            self.assertLess(angle_between(track[frame].rotation, rot), 1e-4, frame)
        # the linear one in the middle was replaced: the straight path is not kept there
        straight = original[15][0]
        self.assertNotAlmostEqual(track[15].position[0], straight[0], places=3)
        self.assertEqual(report["bones"][0]["segments"], {"linear": 1, "authored": 2})

    def test_tracks_with_one_key_or_one_frame_pass_through_unchanged(self):
        one = bone("首", 7, rot=about((1.0, 0.0, 0.0), 5.0), curve=EASE)
        same = [bone("頭", 4, pos=(1.0, 0.0, 0.0)), bone("頭", 4, pos=(2.0, 0.0, 0.0))]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=[one] + same))
        self.assertEqual(out.bones, [one] + same)
        names = {b["name"]: b for b in report["bones"]}
        self.assertEqual((names["首"]["keys_before"], names["首"]["keys_after"]), (1, 1))
        self.assertEqual((names["頭"]["keys_before"], names["頭"]["keys_after"]), (2, 2))

    def test_duplicate_frames_keep_the_last_key(self):
        keys = [bone("センター", 0), bone("センター", 10, pos=(1.0, 0.0, 0.0)), bone("センター", 10, pos=(5.0, 0.0, 0.0)), bone("センター", 20)]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "センター")
        self.assertEqual(len(track), 21)
        self.assertEqual(track[10].position, (5.0, 0.0, 0.0))
        self.assertEqual((report["bones"][0]["keys_before"], report["bones"][0]["keys_after"]), (4, 21))

    def test_bones_and_skip_choose_the_tracks_and_everything_else_is_untouched(self):
        arm = [bone("右腕", 0), bone("右腕", 10, rot=about((0.0, 0.0, 1.0), 30.0)), bone("右腕", 20)]
        leg = [bone("右足", 0), bone("右足", 10, rot=about((1.0, 0.0, 0.0), 30.0)), bone("右足", 20)]
        center = [bone("センター", 0), bone("センター", 10, pos=(0.0, 1.0, 0.0)), bone("センター", 20)]
        motion = vmd.Motion(model_name="dancer", bones=arm + leg + center)
        motion.morphs.append(vmd.MorphKey("あ", 5, 0.5))
        motion.cameras.append(vmd.CameraKey(0, -30.0, (0.0, 10.0, 0.0), (0.0, 0.0, 0.0)))
        out, report = smooth_motion.smooth(motion, skip=["右足"])
        self.assertEqual(len(track_of(out, "右腕")), 21)
        self.assertEqual(len(track_of(out, "センター")), 21)
        self.assertEqual(track_of(out, "右足"), leg)
        self.assertEqual(out.morphs, motion.morphs)
        self.assertEqual(out.cameras, motion.cameras)
        self.assertEqual(out.model_name, "dancer")
        self.assertEqual(report["skipped"], ["右足"])
        self.assertEqual({b["name"]: (b["keys_before"], b["keys_after"]) for b in report["bones"]},
                         {"右腕": (3, 21), "右足": (3, 3), "センター": (3, 21)})
        only, report = smooth_motion.smooth(motion, bones=["センター"])
        self.assertEqual(track_of(only, "右腕"), arm)
        self.assertEqual(len(track_of(only, "センター")), 21)
        self.assertEqual(len(motion.bones), 9)                                # the input is not touched

    def test_running_the_tool_on_its_own_output_changes_nothing(self):
        keys = zigzag() + [bone("センター", 60, pos=(3.0, 4.0, 0.0), rot=about((1.0, 1.0, 0.0), 80.0), curve=EASE)]
        keys += [bone("右腕", 0), bone("右腕", 7, rot=about((0.0, 1.0, 0.0), 45.0)), bone("右腕", 30, rot=about((1.0, 0.0, 0.0), -20.0))]
        once, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        once = vmd.loads(vmd.dumps(once))                                     # as a file holds it (float32)
        twice, report = smooth_motion.smooth(once)
        twice = vmd.loads(vmd.dumps(twice))
        self.assertEqual(len(twice.bones), len(once.bones))
        for a, b in zip(sorted(once.bones, key=lambda k: (k.name, k.frame)), sorted(twice.bones, key=lambda k: (k.name, k.frame))):
            self.assertEqual((a.name, a.frame, a.position, a.rotation), (b.name, b.frame, b.position, b.rotation))
        self.assertEqual(sum(b["segments"]["authored"] for b in report["bones"]), 0)


class JerkTest(unittest.TestCase):
    def test_the_measurement_drops_on_the_smoothed_zigzag(self):
        keys = zigzag() + zigzag("右腕", rotate=True) + zigzag("左腕", rotate=True) + zigzag("上半身", rotate=True)
        before = vmd.Motion(model_name="m", bones=keys)
        after, _ = smooth_motion.smooth(before)
        a, b = motion_jerk.measure(before), motion_jerk.measure(after)
        self.assertEqual(sorted(a["bones"]), ["センター", "上半身", "右腕", "左腕"])
        for name in a["bones"]:
            self.assertGreater(a["bones"][name]["p99"], 3.0 * b["bones"][name]["p99"], name.encode("ascii", "backslashreplace"))
            self.assertGreater(a["bones"][name]["mean"], b["bones"][name]["mean"])
            self.assertEqual(a["bones"][name]["frames"], 51)
        self.assertEqual(a["bones"]["センター"]["unit"], "units/frame^2")
        self.assertEqual(a["bones"]["右腕"]["unit"], "deg/frame^2")
        # the zig-zag flips its speed from +1 to -1 at the keys: the second difference there is 2
        self.assertAlmostEqual(a["bones"]["センター"]["max"], 2.0, places=6)

    def test_a_bone_without_keys_is_reported_absent(self):
        m = motion_jerk.measure(vmd.Motion(model_name="m", bones=zigzag()), bones=["センター", "首"])
        self.assertEqual(m["bones"]["首"], None)


def run(tool, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tool.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        keys = zigzag() + zigzag("右腕", rotate=True) + [bone("右足", 0), bone("右足", 5, pos=(0.0, 1.0, 0.0), curve=EASE)]
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(vmd.Motion(model_name="dancer", bones=keys)))

    def test_writes_the_dance_and_the_report(self):
        out, report = os.path.join(self.folder, "sub", "smooth.vmd"), os.path.join(self.folder, "r.json")
        code, result = run(smooth_motion, [self.dance, out, "--report", report, "--skip", "右腕", "--tension", "0.4"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual((result["in"], result["out"]), (os.path.abspath(self.dance), os.path.abspath(out)))
        self.assertEqual(result["tension"], 0.4)
        back = vmd.load(out)
        self.assertEqual(result["bone_keys"], len(back.bones))
        self.assertEqual(back.model_name, "dancer")
        self.assertEqual(len(track_of(back, "センター")), 51)
        self.assertEqual(len(track_of(back, "右腕")), 6)
        self.assertEqual(len(track_of(back, "右足")), 6)
        with open(report, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["bones"], result["bones"])
        self.assertEqual(saved["skipped"], ["右腕"])
        self.assertEqual(os.listdir(os.path.dirname(out)), ["smooth.vmd"])

    def test_the_dance_is_never_written_over(self):
        with open(self.dance, "rb") as f:
            original = f.read()
        o = os.path.join(self.folder, "o.vmd")
        for argv in ([self.dance, self.dance], [self.dance, o, "--report", self.dance], [self.dance, o, "--tension", "2"],
                     [os.path.join(self.folder, "none.vmd"), o]):
            code, result = run(smooth_motion, argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertFalse(os.path.exists(o), argv)
        with open(self.dance, "rb") as f:
            self.assertEqual(f.read(), original)

    def test_the_measurement_command_prints_one_ascii_line(self):
        code, result = run(motion_jerk, [self.dance])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["bones"]["右腕"]["frames"], 51)
        self.assertIsNone(result["bones"]["左腕"])
        code, result = run(motion_jerk, [os.path.join(self.folder, "none.vmd")])
        self.assertEqual(code, 2)


def real_dance():
    for folder in (ROOT, os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))):
        for rel in (("_spike", "dance_original.vmd"), ("_spike", "out", "hibikase", "variants", "dance_original.vmd")):
            path = os.path.join(folder, *rel)
            if os.path.exists(path):
                return path
    return None


REAL = real_dance()


@unittest.skipUnless(REAL, "the distributed dance is not on this machine")
class RealDanceTest(unittest.TestCase):
    def test_every_key_of_the_whole_dance_is_kept_and_the_tool_is_quick(self):
        before = vmd.load(REAL)
        started = time.perf_counter()
        after, report = smooth_motion.smooth(before)
        data = vmd.dumps(after)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 60.0, elapsed)
        back = vmd.loads(data)
        by = {}
        for k in back.bones:
            by[(k.name, k.frame)] = k
        originals = {}
        for k in sorted(before.bones, key=lambda k: k.frame):
            originals[(k.name, k.frame)] = k                                  # a later duplicate wins
        for (name, frame), k in originals.items():
            got = by[(name, frame)]
            self.assertEqual(got.position, k.position, (name.encode("ascii", "backslashreplace"), frame))
            self.assertLess(angle_between(got.rotation, k.rotation), 1e-6, (name.encode("ascii", "backslashreplace"), frame))
        self.assertEqual(back.morphs, before.morphs)
        self.assertGreater(sum(b["keys_after"] for b in report["bones"]), len(before.bones))


if __name__ == "__main__":
    unittest.main()
