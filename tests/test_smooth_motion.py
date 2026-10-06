"""tools/smooth_motion.py: C1 curves through the keys of a dance, baked to a key per frame; tools/motion_jerk.py: the acceleration."""
import cmath
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


def same_quaternion(a, b, tol=1e-6):
    """components within tol, up to sign (angle_between would amplify the norm error of a stored quaternion)"""
    return all(abs(x - y) <= tol for x, y in zip(a, b)) or all(abs(x + y) <= tol for x, y in zip(a, b))


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
        for k in track[10:41]:                                                # the interior segments: identical frames
            expected = (0.2 * k.frame, -0.1 * k.frame, 0.05 * k.frame)
            for got, want in zip(k.position, expected):
                self.assertAlmostEqual(got, want, places=9, msg=k.frame)
        self.assertLess(track[1].position[0], 0.2)                            # the first and last segment ease in and out
        self.assertGreater(track[49].position[0], 9.8)

    def test_a_steady_turn_about_one_axis_stays_a_steady_turn(self):
        keys = [bone("右腕", 10 * i, rot=about((0.0, 1.0, 0.0), 12.0 * i)) for i in range(6)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右腕")
        for k in track[10:41]:                                                # the interior segments: identical frames
            self.assertLess(angle_between(k.rotation, about((0.0, 1.0, 0.0), 1.2 * k.frame)), 1e-5, k.frame)   # acos noise ~2e-6
        self.assertLess(angle_between(track[1].rotation, IDENTITY), 1.2)      # the first segment eases in

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
            self.assertTrue(same_quaternion(by_frame[k.frame].rotation, k.rotation), k.frame)
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
        # the linear one in the middle was replaced: it leaves the authored key at rest, so it lags the straight path
        straight = original[12][0]
        self.assertNotAlmostEqual(track[12].position[0], straight[0], places=3)
        self.assertGreater(track[12].position[0], straight[0])
        self.assertEqual(report["bones"][0]["segments"], {"linear": 1, "authored": 2, "flat": 0})

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


EASE_LAG = 4.0 / 27.0           # an eased segment lags or leads the linear one by at most this part of its arc


def off_arc(qa, qb, q):
    """degrees of q off the geodesic a -> b, read in the log chart at a"""
    e = smooth_motion.log_map(smooth_motion.relative(qa, qb))
    v = smooth_motion.log_map(smooth_motion.relative(qa, q))
    n2 = sum(c * c for c in e)
    if n2 < 1e-18:
        return math.degrees(math.sqrt(sum(c * c for c in v)))
    t = sum(x * y for x, y in zip(v, e)) / n2
    return math.degrees(math.sqrt(sum((x - t * y) ** 2 for x, y in zip(v, e))))


def deviation_from_mmd_path(before, after):
    """per frame inside the linear, non-flat segments of 2+ frames, against what MMD shows for the original keys:
    {"angle": total degrees, "lateral": degrees off the segment's arc, "excess": total minus the timing bound
    EASE_LAG * arc, "position": distance}, each as (max, p99)"""
    rows = {"angle": [], "lateral": [], "excess": [], "position": []}
    tb, ta = smooth_motion.tracks_of(before), smooth_motion.tracks_of(after)
    for name, keys in tb.items():
        if len(keys) < 2 or name not in ta:
            continue
        frames = [k.frame for k in keys]
        out = ta[name]
        out_frames = [k.frame for k in out]
        for a, b in zip(keys, keys[1:]):
            if b.frame - a.frame < 2 or smooth_motion.is_flat(a, b) or \
                    not all(smooth_motion.is_linear(c) for c in vmd.bone_curves(b.interpolation).values()):
                continue
            qa, qb = smooth_motion._normalized(a.rotation), smooth_motion._normalized(b.rotation)
            arc = angle_between(qa, qb)
            for f in range(a.frame + 1, b.frame):
                p0, q0 = smooth_motion.sample(keys, f, frames)
                p1, q1 = smooth_motion.sample(out, f, out_frames)
                d = angle_between(q0, q1)
                rows["angle"].append(d)
                rows["lateral"].append(off_arc(qa, qb, q1))
                rows["excess"].append(d - EASE_LAG * arc)
                rows["position"].append(math.sqrt(sum((x - y) ** 2 for x, y in zip(p0, p1))))

    def stats(v):
        v = sorted(v)
        return (v[-1], v[int(round(0.99 * (len(v) - 1)))]) if v else (0.0, 0.0)
    return {k: stats(v) for k, v in rows.items()}


class HoldTest(unittest.TestCase):
    """H1: two equal consecutive keys are a hold (a planted foot, a closed finger): it must stay still"""

    def test_a_hold_before_a_move_stays_exactly_at_the_held_value_and_the_move_does_not_dip(self):
        keys = [bone("右足ＩＫ", 0, pos=(1.0, 0.0, 2.0)), bone("右足ＩＫ", 10, pos=(1.0, 0.0, 2.0)),
                bone("右足ＩＫ", 20, pos=(1.0, 5.0, 2.0)), bone("右足ＩＫ", 30, pos=(1.0, 5.0, 2.0))]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右足ＩＫ")
        frames = [k.frame for k in track]
        path = [smooth_motion.sample(track, f, frames)[0] for f in range(0, 31)]
        for f in range(0, 11):
            self.assertEqual(path[f], (1.0, 0.0, 2.0), f)                  # the hold is exactly still
        for f in range(20, 31):
            self.assertEqual(path[f], (1.0, 5.0, 2.0), f)
        ys = [p[1] for p in path[10:21]]
        self.assertGreaterEqual(min(ys), 0.0)                                 # no dip below the hold
        self.assertLessEqual(max(ys), 5.0)                                    # no overshoot past the next hold
        self.assertEqual(ys, sorted(ys))                                      # the move is monotone
        self.assertLess(path[11][1] - path[10][1], 0.5)                       # it eases out of the hold (chord speed 0.5)

    def test_a_held_rotation_stays_exactly_still(self):
        q = about((0.3, 0.5, 0.8), 70.0)
        keys = [bone("右中指３", 0, rot=q), bone("右中指３", 40, rot=q), bone("右中指３", 50, rot=about((0.0, 0.0, 1.0), 20.0)), bone("右中指３", 60, rot=q)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右中指３")
        frames = [k.frame for k in track]
        for f in range(0, 41):
            self.assertEqual(smooth_motion.sample(track, f, frames)[1], smooth_motion._normalized(q), f)


class OvershootTest(unittest.TestCase):
    """M1: the curve never passes beyond the key values"""

    def test_a_sharp_reversal_never_passes_beyond_the_keys(self):
        keys = [bone("センター", 0, pos=(0.0, 0.0, 0.0)), bone("センター", 3, pos=(0.0, 10.0, 0.0)),
                bone("センター", 40, pos=(0.0, 2.0, 0.0)), bone("センター", 44, pos=(0.0, 9.0, 0.0)), bone("センター", 90, pos=(0.0, 9.5, 0.0))]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "センター")
        for a, b in zip(keys, keys[1:]):
            lo, hi = sorted((a.position[1], b.position[1]))
            for k in track[a.frame:b.frame + 1]:
                self.assertTrue(lo - 1e-9 <= k.position[1] <= hi + 1e-9, (k.frame, k.position[1]))
            ys = [k.position[1] for k in track[a.frame:b.frame + 1]]
            self.assertEqual(ys, sorted(ys) if b.position[1] >= a.position[1] else sorted(ys, reverse=True))

    def test_a_rotation_segment_never_turns_further_than_its_own_arc(self):
        keys = [bone("右手捩", 0, rot=IDENTITY), bone("右手捩", 4, rot=about((1.0, 0.0, 0.0), 20.0)),
                bone("右手捩", 42, rot=about((1.0, 0.0, 0.0), 130.0)), bone("右手捩", 46, rot=about((1.0, 0.0, 0.0), 100.0))]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右手捩")
        angles = [math.degrees(math.sqrt(sum(v * v for v in smooth_motion.log_map(smooth_motion._normalized(k.rotation))))) for k in track]
        self.assertLessEqual(max(angles[4:43]), 130.0 + 1e-6)
        self.assertGreaterEqual(min(angles[4:43]), 20.0 - 1e-6)
        self.assertEqual(angles[4:43], sorted(angles[4:43]))
        # a fast turn (10 deg/frame) followed by a crawl (0.1 deg/frame): the tangent at the joint must follow the
        # crawl, else the slow segment shoots past its 4-degree arc and comes back
        keys = [bone("右手捩", 0, rot=IDENTITY), bone("右手捩", 4, rot=about((1.0, 0.0, 0.0), 40.0)), bone("右手捩", 44, rot=about((1.0, 0.0, 0.0), 44.0))]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        angles = [math.degrees(math.sqrt(sum(v * v for v in smooth_motion.log_map(smooth_motion._normalized(k.rotation))))) for k in track_of(out, "右手捩")]
        self.assertLessEqual(max(angles[4:]), 44.0 + 1e-6, max(angles[4:]))
        self.assertEqual(angles[4:], sorted(angles[4:]))

    def test_a_corner_between_two_arcs_60_degrees_apart_stays_within_3_degrees_of_each_arc(self):
        # 90 degrees about x, then 90 about an axis 60 degrees from x, both at 9 deg/frame: the uncapped tangent
        # between the axes would bulge 9 * sin(30) * 10 * 4/27 = 6.7 degrees off each arc; the lateral cap holds it to 3
        second = mathutil.quat_multiply(about((1.0, 0.0, 0.0), 90.0), about((0.5, math.sqrt(0.75), 0.0), 90.0))
        keys = [bone("上半身", 0, rot=IDENTITY), bone("上半身", 10, rot=about((1.0, 0.0, 0.0), 90.0)),
                bone("上半身", 20, rot=second), bone("上半身", 30, rot=second)]
        before = vmd.Motion(model_name="m", bones=keys)
        after, _ = smooth_motion.smooth(before)
        dev = deviation_from_mmd_path(before, after)
        self.assertLess(dev["lateral"][0], 3.5, dev)
        self.assertGreater(dev["lateral"][0], 1.0, dev)                        # ... and the corner is rounded, not a kink

    def test_the_tangent_of_a_mid_key_between_two_large_arcs_is_the_segment_rate(self):
        # M2: 0 -> 100 -> 200 degrees about one axis: MMD turns 100 degrees per segment (the short way each time);
        # the neighbour-to-neighbour short way would be -160 degrees and give a tangent of 1 deg/frame instead of 10
        keys = [bone("右手捩", 10 * i, rot=about((1.0, 0.0, 0.0), 100.0 * i)) for i in range(4)]      # 0, 100, 200, 300
        slopes = smooth_motion.tangents(keys, 0.5)
        for i in (1, 2):
            rate = math.degrees(math.sqrt(sum(v * v for v in slopes[i][1])))
            self.assertAlmostEqual(rate, 10.0, places=6)
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右手捩")
        for k in track[10:21]:                                                # the middle segment: a steady turn stays steady
            self.assertLess(angle_between(k.rotation, about((1.0, 0.0, 0.0), 10.0 * k.frame)), 1e-5, k.frame)
        for k in track:                                                       # the eased ends stay on the axis
            self.assertLess(abs(k.rotation[1]) + abs(k.rotation[2]), 1e-9, k.frame)
        self.assertLess(angle_between(track[1].rotation, IDENTITY), 10.0)     # ... and start at rest

    def test_a_three_axis_track_stays_close_to_the_mmd_path(self):
        # kills the mutants that mix up the frame of the tangent (world instead of body: 93 degrees off)
        rots = [about((1.0, 0.0, 0.0), 60.0), about((0.0, 1.0, 0.0), 50.0), about((0.0, 0.0, 1.0), -70.0),
                about((1.0, 1.0, 0.0), 80.0), about((0.0, 1.0, 1.0), -40.0), IDENTITY]
        gaps = [0, 6, 20, 23, 40, 70]
        keys = [bone("上半身", f, rot=r) for f, r in zip(gaps, rots)]
        before = vmd.Motion(model_name="m", bones=keys)
        after, _ = smooth_motion.smooth(before)
        dev = deviation_from_mmd_path(before, after)
        self.assertLess(dev["lateral"][0], 8.0, dev)                          # off the arc: bounded by the lateral cap
        self.assertLess(dev["excess"][0], 3.0, dev)                           # along the arc: only the ease's timing


class FlatTest(unittest.TestCase):
    """M3: nothing is baked where nothing moves"""

    def test_a_constant_track_is_left_as_its_keys(self):
        q = about((0.0, 1.0, 0.0), 15.0)
        keys = [bone("グルーブ", 0, pos=(0.0, 1.0, 0.0), rot=q), bone("グルーブ", 7000, pos=(0.0, 1.0, 0.0), rot=q)]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        self.assertEqual(out.bones, keys)
        self.assertEqual((report["bones"][0]["keys_after"], report["bones"][0]["changed"]), (2, False))

    def test_a_flat_segment_inside_a_track_keeps_just_its_two_keys(self):
        keys = [bone("センター", 0), bone("センター", 10, pos=(0.0, 3.0, 0.0)), bone("センター", 50, pos=(0.0, 3.0, 0.0)), bone("センター", 60, pos=(0.0, 0.0, 0.0))]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        frames = [k.frame for k in track_of(out, "センター")]
        self.assertEqual(frames, list(range(0, 11)) + list(range(50, 61)))
        self.assertEqual(report["bones"][0]["segments"], {"linear": 2, "authored": 0, "flat": 1})
        self.assertEqual(report["bones"][0]["keys_after"], 22)
        # a flat segment whose keys only differ in the stored sign of the quaternion is still flat
        q = about((1.0, 0.0, 0.0), 30.0)
        keys = [bone("右腕", 0, rot=q), bone("右腕", 10, rot=tuple(-v for v in q)), bone("右腕", 20, rot=IDENTITY)]
        out, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        self.assertEqual([k.frame for k in track_of(out, "右腕")], [0] + list(range(10, 21)))


class MutantTest(unittest.TestCase):
    """M4: the holes the mutation check found (review 7)"""

    def test_keys_with_alternating_stored_sign_still_turn_the_short_way(self):
        # a slerp or relative() that takes the long way would spin 300 degrees between frames 10 and 20
        keys = [bone("右腕", 10 * i, rot=tuple((-1.0) ** i * v for v in about((0.0, 1.0, 0.0), 12.0 * i))) for i in range(6)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右腕")
        for k in track[10:41]:
            self.assertLess(angle_between(k.rotation, about((0.0, 1.0, 0.0), 1.2 * k.frame)), 1e-5, k.frame)
        for k in keys:                                                        # the stored sign of a key is kept
            self.assertEqual(track[k.frame].rotation, k.rotation)
        r = smooth_motion.relative(about((1.0, 0.0, 0.0), 20.0), tuple(-v for v in about((1.0, 0.0, 0.0), 65.0)))
        self.assertLess(angle_between(r, about((1.0, 0.0, 0.0), 45.0)), 1e-6)
        self.assertGreaterEqual(r[3], 0.0)
        self.assertLess(angle_between(smooth_motion.slerp(about((1.0, 0.0, 0.0), 0.0), tuple(-v for v in about((1.0, 0.0, 0.0), 90.0)), 0.5),
                                      about((1.0, 0.0, 0.0), 45.0)), 1e-6)

    def test_a_stored_quaternion_that_is_not_unit_is_written_back_as_it_was(self):
        q = tuple(1.0001 * v for v in about((0.0, 0.0, 1.0), 40.0))
        keys = [bone("右腕", 0, rot=q), bone("右腕", 10, rot=about((0.0, 0.0, 1.0), 80.0)), bone("右腕", 20, rot=IDENTITY)]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        self.assertEqual(track_of(out, "右腕")[0].rotation, q)
        for k in track_of(out, "右腕")[1:10]:
            self.assertAlmostEqual(sum(v * v for v in k.rotation), 1.0, places=9)   # the frames between are unit

    def test_physics_bytes_and_raw_name_are_kept(self):
        flagged = bytearray(vmd.bone_interpolation(vmd.LINEAR_CURVE))
        flagged[2], flagged[3] = 1, 0
        plain = vmd.bone_interpolation(vmd.LINEAR_CURVE)
        keys = [vmd.BoneKey("右腕", 0, (0.0, 0.0, 0.0), IDENTITY, bytes(flagged), b"raw-a"),
                vmd.BoneKey("右腕", 10, (0.0, 0.0, 0.0), about((0.0, 0.0, 1.0), 30.0), plain, b"raw-b"),
                vmd.BoneKey("右腕", 20, (0.0, 0.0, 0.0), IDENTITY, bytes(flagged), b"raw-a")]
        out, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        track = track_of(out, "右腕")
        self.assertEqual([k.interpolation[2:4] for k in track[:3]], [b"\x01\x00"] * 3)   # the frames after a key carry its flag
        self.assertEqual([k.interpolation[2:4] for k in track[10:13]], [b"\x00\x00"] * 3)
        self.assertEqual(track[20].interpolation[2:4], b"\x01\x00")
        self.assertEqual({k.raw_name for k in track[:10]}, {b"raw-a"})
        self.assertEqual({k.raw_name for k in track[10:20]}, {b"raw-b"})
        for k in track:
            self.assertEqual(set(vmd.bone_curves(k.interpolation).values()), {vmd.LINEAR_CURVE})

    def test_the_output_does_not_share_its_lists_with_the_input(self):
        motion = vmd.Motion(model_name="m", bones=zigzag())
        motion.morphs.append(vmd.MorphKey("あ", 5, 0.5))
        out, _ = smooth_motion.smooth(motion)
        self.assertIsNot(out.morphs, motion.morphs)
        self.assertIsNot(out.bones, motion.bones)
        self.assertEqual(out.morphs, motion.morphs)


class JerkTest(unittest.TestCase):
    def test_the_measurement_drops_on_the_smoothed_zigzag(self):
        keys = zigzag() + zigzag("右腕", rotate=True) + zigzag("左腕", rotate=True) + zigzag("上半身", rotate=True)
        before = vmd.Motion(model_name="m", bones=keys)
        after, _ = smooth_motion.smooth(before)
        a, b = motion_jerk.measure(before), motion_jerk.measure(after)
        self.assertEqual(sorted(a["bones"]), ["センター", "上半身", "右腕", "左腕"])
        for name in a["bones"]:
            self.assertGreater(a["bones"][name]["p99"], 3.0 * b["bones"][name]["p99"], name.encode("ascii", "backslashreplace"))
            self.assertGreater(a["bones"][name]["max"], 3.0 * b["bones"][name]["max"])
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


# ---- --denoise (batch H) -------------------------------------------------------------------

DENOISE = 7.5


def swing(name="右腕", step=1, last=90, amplitude=30.0, jitter=1.5, hz=2.0, axis=(1.0, 0.0, 0.0)):
    """a sine swing about one axis, keyed every `step` frames, each key off by +jitter and -jitter degrees in turn"""
    keys = []
    for i, f in enumerate(range(0, last + 1, step)):
        angle = amplitude * math.sin(2.0 * math.pi * hz * f / 30.0) + jitter * (-1) ** i
        keys.append(bone(name, f, rot=about(axis, angle)))
    return keys


def x_degrees(track, first, last):
    """the angle about X, at every frame of the span, of a track that turns about X only"""
    frames = [k.frame for k in track]
    out = []
    for f in range(first, last + 1):
        q = smooth_motion.sample(track, f, frames)[1]
        out.append(math.degrees(2.0 * math.atan2(q[0], q[3])))
    return out


def plain_and_denoised(keys, hz=DENOISE, **options):
    motion = vmd.Motion(model_name="m", bones=keys)
    plain, _ = smooth_motion.smooth(motion)
    denoised, report = smooth_motion.smooth(motion, denoise=hz, **options)
    return plain, denoised, report


def path(motion, name, first=None, last=None):
    return per_frame(track_of(motion, name), first, last)


def high_share(signal, above):
    """the share of the energy of a sequence sampled at 30 fps that lies above `above` Hz (plain DFT)"""
    n = len(signal)
    total = high = 0.0
    for k in range(n // 2 + 1):
        re = sum(v * math.cos(2.0 * math.pi * k * i / n) for i, v in enumerate(signal))
        im = sum(v * math.sin(2.0 * math.pi * k * i / n) for i, v in enumerate(signal))
        e = (re * re + im * im) * (1.0 if k == 0 or 2 * k == n else 2.0)
        total += e
        if k * 30.0 / n > above:
            high += e
    return high / total


def alternation(values, first, last, sign_of=lambda f: (-1) ** f):
    """the amplitude of the +-pattern in values[first:last]"""
    return abs(sum(sign_of(f) * values[f] for f in range(first, last))) / float(last - first)


class DenoiseTest(unittest.TestCase):
    """batch H: --denoise takes the frame-scale jitter out of runs of keys 1-2 frames apart, within caps"""

    CLEAN = [30.0 * math.sin(2.0 * math.pi * 2.0 * f / 30.0) for f in range(0, 91)]

    def amplitude_2hz(self, angles):
        w = 2.0 * math.pi * 2.0 / 30.0                                      # frames 15..74: four whole periods
        a = sum(angles[f] * math.sin(w * f) for f in range(15, 75)) * 2.0 / 60.0
        b = sum(angles[f] * math.cos(w * f) for f in range(15, 75)) * 2.0 / 60.0
        return math.hypot(a, b)

    def test_alternating_jitter_on_a_2_hz_swing_drops_3x_and_the_swing_stays(self):
        plain, denoised, _ = plain_and_denoised(swing())                    # a key on every frame, +-1.5 degrees in turn
        before = x_degrees(track_of(plain, "右腕"), 0, 90)
        after = x_degrees(track_of(denoised, "右腕"), 0, 90)
        error_before = [a - c for a, c in zip(before, self.CLEAN)]
        error_after = [a - c for a, c in zip(after, self.CLEAN)]
        self.assertAlmostEqual(alternation(error_before, 15, 75), 1.5, places=6)
        self.assertLessEqual(alternation(error_after, 15, 75), 1.5 / 3.0)
        self.assertAlmostEqual(self.amplitude_2hz(before), 30.0, delta=0.01)
        self.assertLess(abs(self.amplitude_2hz(after) - 30.0), 3.0)         # within 10 %

    def test_what_is_removed_from_the_swing_lies_above_6_hz(self):
        plain, denoised, _ = plain_and_denoised(swing())
        removed = [a - b for a, b in zip(x_degrees(track_of(plain, "右腕"), 0, 90), x_degrees(track_of(denoised, "右腕"), 0, 90))]
        self.assertGreater(max(abs(v) for v in removed), 1.0)
        self.assertGreater(high_share(removed, 6.0), 0.9)

    def test_keys_two_frames_apart_lose_half_their_alternation_as_the_cutoff_says(self):
        # the alternation of keys 2 frames apart is a 7.5 Hz pattern, and 7.5 Hz is where the default cutoff halves a
        # sine: 1 / (1 + 8 * weight) with weight = 1/8 (the frames between the keys carry no data and cost nothing here)
        plain, denoised, _ = plain_and_denoised(swing(step=2))
        before = x_degrees(track_of(plain, "右腕"), 0, 90)
        after = x_degrees(track_of(denoised, "右腕"), 0, 90)
        on_keys = lambda f: (-1) ** (f // 2) if f % 2 == 0 else 0           # noqa: E731  the keys' frames only
        error_before = [a - c for a, c in zip(before, self.CLEAN)]
        error_after = [a - c for a, c in zip(after, self.CLEAN)]
        self.assertAlmostEqual(alternation(error_before, 14, 74, on_keys) * 2.0, 1.5, places=6)
        ratio = alternation(error_after, 14, 74, on_keys) * 2.0 / 1.5
        self.assertTrue(0.4 <= ratio <= 0.6, ratio)
        self.assertLess(abs(self.amplitude_2hz(after) - 30.0), 3.0)
        # a lower cutoff takes more of it: 6.5 Hz puts the response at 7.5 Hz near 1/3
        _, lower, _ = plain_and_denoised(swing(step=2), hz=6.5)
        ratio = alternation([a - c for a, c in zip(x_degrees(track_of(lower, "右腕"), 0, 90), self.CLEAN)], 14, 74, on_keys) * 2.0 / 1.5
        self.assertLess(ratio, 0.4, ratio)

    def test_a_hold_stays_exactly_still_and_is_left_at_rest(self):
        held = about((1.0, 0.0, 0.0), 20.0)
        keys = [bone("右腕", f, rot=about((1.0, 0.0, 0.0), 10.0 + 0.3 * f + 1.5 * (-1) ** f)) for f in range(0, 30)]
        keys += [bone("右腕", 30, rot=held), bone("右腕", 45, rot=held)]
        keys += [bone("右腕", f, rot=about((1.0, 0.0, 0.0), 20.0 + 2.0 * (f - 47) + 1.5 * (-1) ** f)) for f in range(48, 70)]
        plain, denoised, _ = plain_and_denoised(keys)
        self.assertEqual(path(denoised, "右腕", 30, 45), path(plain, "右腕", 30, 45))
        for pos, rot in path(denoised, "右腕", 30, 45):
            self.assertEqual(rot, smooth_motion._normalized(held))
        self.assertNotEqual(path(denoised, "右腕", 5, 25), path(plain, "右腕", 5, 25))      # not vacuous
        self.assertNotEqual(path(denoised, "右腕", 50, 65), path(plain, "右腕", 50, 65))
        # entered and left at rest as without the denoise: the frames next to the hold keep their values (frame 29 is a
        # dense key, 46 lies within the margin of the dense key 48), and so do the frames next to the first and last key
        for f in (29, 46, 1, 68):
            self.assertEqual(path(denoised, "右腕", f, f), path(plain, "右腕", f, f), f)
        self.assertNotEqual(path(denoised, "右腕", 47, 47), path(plain, "右腕", 47, 47))

    def test_a_foot_never_goes_below_its_floor_keeps_its_contacts_and_does_not_slide_in_a_hold(self):
        for name in ("右足ＩＫ", "左足IK"):                                   # any spelling: the rule is the track's own floor
            keys = []
            for f in range(0, 31):
                if 10 < f < 20:
                    continue                                                # 10 -> 20: a hold on the floor
                phase = f if f <= 10 else f - 20
                lift = 0.6 * math.sin(math.pi * phase / 10.0)
                y = lift + 0.04 * (-1) ** f if lift > 0.05 else 0.0
                x = 0.1 * phase + 0.03 * (-1) ** phase + (0.0 if f <= 10 else 1.0)
                keys.append(bone(name, f, pos=(x, y, 1.0)))
            self.assertEqual(keys[10].position, keys[11].position)
            plain, denoised, _ = plain_and_denoised(keys)
            track = track_of(denoised, name)
            self.assertGreaterEqual(min(k.position[1] for k in track), 0.0, name.encode("ascii", "backslashreplace"))
            by = {k.frame: k for k in track}
            for k in keys:
                if k.position[1] == 0.0:
                    self.assertEqual(by[k.frame].position, k.position, k.frame)        # a contact stays where it was
            for pos, rot in path(denoised, name, 10, 20):
                self.assertEqual(pos, keys[10].position)                                # no slide in the hold
            self.assertNotEqual(track, track_of(plain, name))

    def test_the_center_is_never_lowered_below_its_lowest_key(self):
        keys = [bone("センター", f, pos=(0.0, -2.0 + 0.5 * math.cos(2.0 * math.pi * 2.0 * f / 30.0) + 0.08 * (-1) ** f, 0.0))
                for f in range(0, 61)]
        floor = min(k.position[1] for k in keys)
        plain, denoised, _ = plain_and_denoised(keys)
        self.assertGreaterEqual(min(k.position[1] for k in track_of(denoised, "センター")), floor)
        self.assertNotEqual(track_of(denoised, "センター"), track_of(plain, "センター"))

    def test_every_frame_stays_within_the_caps_of_the_plain_curve(self):
        keys = swing(jitter=10.0) + [bone("センター", f, pos=(0.3 * (-1) ** f, 0.01 * f, 0.0)) for f in range(0, 61)]
        # and a jitter growing from 0 to 10 degrees: some frames want a little more than the cap, some twice as much
        keys += [bone("左腕", f, rot=about((0.0, 0.0, 1.0), 20.0 * math.sin(2.0 * math.pi * 2.0 * f / 30.0) + f / 9.0 * (-1) ** f))
                 for f in range(0, 91)]
        for cap in (None, (1.0, 0.01)):
            options = {} if cap is None else {"denoise_cap": cap}
            plain, denoised, _ = plain_and_denoised(keys, **options)
            cap_deg, cap_units = cap or smooth_motion.DENOISE_CAP
            for name in ("右腕", "左腕"):
                rot = max(angle_between(a[1], b[1]) for a, b in zip(path(plain, name), path(denoised, name)))
                self.assertLessEqual(rot, cap_deg + 1e-5, name.encode("ascii", "backslashreplace"))
                self.assertGreater(rot, cap_deg - 1e-3)                     # the jitter is larger: the cap binds
            pos = max(abs(x - y) for a, b in zip(path(plain, "センター"), path(denoised, "センター")) for x, y in zip(a[0], b[0]))
            self.assertLessEqual(pos, cap_units + 1e-9)
            self.assertGreater(pos, cap_units - 1e-6)
        self.assertEqual(smooth_motion.DENOISE_CAP, (3.0, 0.05))

    def test_sparse_keys_and_every_frame_away_from_a_dense_key_are_untouched(self):
        sparse = [bone("右腕", 4 * i, rot=about((0.0, 1.0, 0.0), 10.0 * math.sin(i) + 3.0 * (-1) ** i)) for i in range(20)]
        plain, denoised, report = plain_and_denoised(sparse)
        self.assertEqual(vmd.dumps(denoised), vmd.dumps(plain))
        mixed = [k for k in sparse if k.frame <= 36]
        mixed += [bone("右腕", f, rot=about((0.0, 1.0, 0.0), 2.0 * (f - 36) + 2.0 * (-1) ** f)) for f in range(37, 46)]
        mixed += [bone("右腕", f, rot=about((0.0, 1.0, 0.0), 20.0 - (f - 49))) for f in range(49, 80, 4)]
        plain, denoised, _ = plain_and_denoised(mixed)
        p, d = path(plain, "右腕"), path(denoised, "右腕")
        margin = smooth_motion.DENOISE_MARGIN
        self.assertEqual(margin, 2)
        for f in list(range(0, 36 - margin)) + list(range(45 + margin + 1, 78)):   # the run is keys 36..45
            self.assertEqual(d[f], p[f], f)
        self.assertNotEqual(d[36:46], p[36:46])
        by = {k.frame: k for k in track_of(denoised, "右腕")}
        for k in mixed:
            if k.frame not in range(36, 46):
                self.assertEqual(by[k.frame].rotation, k.rotation, k.frame)

    def test_an_authored_segment_next_to_a_dense_run_is_untouched(self):
        keys = swing(last=30) + [bone("右腕", 40, rot=about((1.0, 0.0, 0.0), 50.0), curve=EASE)]
        keys += [bone("右腕", f, rot=about((1.0, 0.0, 0.0), 50.0 + f - 40 + 1.5 * (-1) ** f)) for f in range(41, 60)]
        plain, denoised, report = plain_and_denoised(keys)
        self.assertEqual(path(denoised, "右腕", 30, 40), path(plain, "右腕", 30, 40))
        self.assertNotEqual(path(denoised, "右腕", 5, 25), path(plain, "右腕", 5, 25))
        self.assertEqual(report["bones"][0]["segments"]["authored"], 1)

    def test_rotations_stay_unit_and_turn_the_short_way(self):
        keys = swing(jitter=2.0, axis=(0.0, 0.6, 0.8))
        keys = [vmd.BoneKey(k.name, k.frame, k.position, tuple((-1.0) ** i * v for v in k.rotation), k.interpolation)
                for i, k in enumerate(keys)]                                # the stored sign flips at every key
        plain, denoised, _ = plain_and_denoised(keys)
        p, d = track_of(plain, "右腕"), track_of(denoised, "右腕")
        self.assertEqual([k.frame for k in d], [k.frame for k in p])
        cap = smooth_motion.DENOISE_CAP[0]
        moved = 0
        for a, b in zip(p, d):
            if a.rotation != b.rotation:
                moved += 1
                self.assertAlmostEqual(sum(v * v for v in b.rotation), 1.0, places=9)
                self.assertGreaterEqual(sum(x * y for x, y in zip(a.rotation, b.rotation)), 0.0)   # the stored sign is kept
        self.assertGreater(moved, 80)
        for a, a2, b, b2 in zip(p, p[1:], d, d[1:]):
            self.assertLessEqual(angle_between(b.rotation, b2.rotation), angle_between(a.rotation, a2.rotation) + 2.0 * cap + 1e-5)

        def turned(track):                                                  # degrees about the axis, every frame
            frames = [k.frame for k in track]
            out = []
            for f in range(0, 91):
                q = smooth_motion.sample(track, f, frames)[1]
                q = q if q[3] >= 0.0 else tuple(-v for v in q)
                out.append(math.degrees(2.0 * math.atan2(0.6 * q[1] + 0.8 * q[2], q[3])))
            return out
        error_before = [a - c for a, c in zip(turned(p), DenoiseTest.CLEAN)]
        error_after = [a - c for a, c in zip(turned(d), DenoiseTest.CLEAN)]
        self.assertAlmostEqual(alternation(error_before, 15, 75), 2.0, places=6)
        self.assertLessEqual(alternation(error_after, 15, 75), 2.0 / 3.0)   # the flipped signs do not get in the way

    def test_a_run_is_not_moved_as_a_whole_the_mean_and_slope_of_the_correction_are_zero(self):
        keys = [bone("センター", f, pos=(0.5 * math.sin(2.0 * math.pi * 2.0 * f / 30.0) + 0.02 * (-1) ** f + 0.01 * f, 0.0, 0.0))
                for f in range(0, 61)]
        plain, denoised, _ = plain_and_denoised(keys)
        p, d = path(plain, "センター"), path(denoised, "センター")
        zone = list(range(2, 59))                                           # 0, 1, 59 and 60 stay: the ends and their neighbours
        delta = [d[f][0][0] - p[f][0][0] for f in zone]
        self.assertGreater(max(abs(v) for v in delta), 0.01)               # it moved, and below the 0.05 cap
        self.assertLess(max(abs(v) for v in delta), 0.05)
        self.assertLess(abs(sum(delta)), 1e-9)
        self.assertLess(abs(sum((f - 30.0) * v for f, v in zip(zone, delta))), 1e-9)

    def test_a_foot_touching_the_floor_inside_a_dense_run_stays_on_that_spot(self):
        ys = [0.3, 0.22, 0.1, 0.04, 0.0, 0.05, 0.12, 0.2, 0.31, 0.38, 0.44, 0.4, 0.3, 0.25, 0.1, 0.0, 0.06, 0.15, 0.2, 0.3]
        keys = [bone("右足ＩＫ", f, pos=(0.1 * f + 0.04 * (-1) ** f, y, 0.0)) for f, y in enumerate(ys)]
        plain, denoised, _ = plain_and_denoised(keys)
        by = {k.frame: k for k in track_of(denoised, "右足ＩＫ")}
        for f in (4, 15):
            self.assertEqual(by[f].position, keys[f].position, f)
        self.assertNotEqual(by[3].position, keys[3].position)

    def test_the_floor_bounds_every_corrected_frame(self):
        # a steep fall onto the floor and a slow rise: the smoothest curve through the contact dips below the floor
        ys = [0.9, 0.6, 0.3, 0.0, 0.01, 0.02, 0.03, 0.05, 0.07, 0.1, 0.13, 0.16]
        keys = [bone("右足ＩＫ", f, pos=(0.0, y, 0.0)) for f, y in enumerate(ys)]
        plain, denoised, _ = plain_and_denoised(keys)
        heights = [k.position[1] for k in track_of(denoised, "右足ＩＫ")]
        self.assertGreaterEqual(min(heights), 0.0)
        self.assertIn(0.0, heights[4:])                                     # the bound held a frame on the floor

    def test_the_caps_hold_even_when_the_rounds_of_holding_run_out(self):
        saved = smooth_motion.ROUNDS
        smooth_motion.ROUNDS = 1
        self.addCleanup(setattr, smooth_motion, "ROUNDS", saved)
        keys = [bone("左腕", f, rot=about((0.0, 0.0, 1.0), 20.0 * math.sin(2.0 * math.pi * 2.0 * f / 30.0) + f / 9.0 * (-1) ** f))
                for f in range(0, 91)]
        plain, denoised, _ = plain_and_denoised(keys)
        worst = max(angle_between(a[1], b[1]) for a, b in zip(path(plain, "左腕"), path(denoised, "左腕")))
        self.assertLessEqual(worst, smooth_motion.DENOISE_CAP[0] + 1e-5)

    def test_a_zone_of_three_frames_is_left_as_the_plain_curve(self):
        # review 9 M2: hold, one key 2 frames later, hold.  The zone is frames 12-14; with its mean and slope at 0 the only
        # correction left is c(1, -2, 1), which turned a smooth deceleration into steps (6.5, 7.4, 6.9 -> 11.0, 3.0, 8.4 deg)
        keys = [bone("右腕", 0), bone("右腕", 10), bone("右腕", 12, rot=about((1.0, 0.0, 0.0), 68.0)),
                bone("右腕", 17, rot=about((1.0, 0.0, 0.0), 96.0)), bone("右腕", 30, rot=about((1.0, 0.0, 0.0), 96.0))]
        plain, denoised, report = plain_and_denoised(keys)
        self.assertEqual(vmd.dumps(denoised), vmd.dumps(plain))
        self.assertEqual(report["bones"][0]["denoise"]["frames"], 0)
        self.assertEqual(smooth_motion.MIN_ZONE, 4)

    def test_a_zone_of_four_frames_is_corrected(self):
        # hold to frame 10, dense keys 12 and 13 (a small hesitation), the next key 8 frames on: the zone is frames 12-15
        keys = [bone("右腕", 0), bone("右腕", 10), bone("右腕", 12, rot=about((1.0, 0.0, 0.0), 4.0)),
                bone("右腕", 13, rot=about((1.0, 0.0, 0.0), 3.5)), bone("右腕", 21, rot=about((1.0, 0.0, 0.0), 10.0)),
                bone("右腕", 30, rot=about((1.0, 0.0, 0.0), 10.0))]
        plain, denoised, report = plain_and_denoised(keys)
        moved = [f for f, (a, b) in enumerate(zip(path(plain, "右腕"), path(denoised, "右腕"))) if a != b]
        self.assertEqual(moved, [12, 13, 14, 15])
        self.assertLess(max(angle_between(a[1], b[1]) for a, b in zip(path(plain, "右腕"), path(denoised, "右腕"))), 2.9)

    def test_a_capped_zone_keeps_zero_mean_and_slope_and_has_no_lone_frame(self):
        # review 9 M1: every frame of the zone (12-18) wants to move about 0.35, seven times the 0.05 cap.  Holding the
        # frames at the cap one by one left too few free frames for the mean and slope; they were set to 0 and the held
        # frames kept their correction.  The correction must stay a whole: zero mean, zero slope, inside the cap.
        keys = [bone("センター", 0), bone("センター", 10)]
        keys += [bone("センター", f, pos=(0.5 + 0.4 * (-1) ** f, 0.0, 0.0)) for f in range(13, 18)]
        keys += [bone("センター", 20, pos=(1.0, 0.0, 0.0)), bone("センター", 30, pos=(1.0, 0.0, 0.0))]
        plain, denoised, _ = plain_and_denoised(keys)
        p, d = path(plain, "センター"), path(denoised, "センター")
        moved = [f for f in range(31) if p[f] != d[f]]
        self.assertEqual(moved, list(range(12, 19)))                       # all of the zone moves: no lone frame
        delta = [d[f][0][0] - p[f][0][0] for f in moved]
        self.assertLessEqual(max(abs(v) for v in delta), 0.05 + 1e-12)
        self.assertGreater(max(abs(v) for v in delta), 0.04)               # the largest one is at the cap
        self.assertLess(abs(sum(delta)), 1e-9)
        self.assertLess(abs(sum((f - 15.0) * v for f, v in zip(moved, delta))), 1e-9)

    def test_a_rotation_zone_whose_frames_hit_the_cap_moves_as_a_whole(self):
        # a sharp stop at frame 12 and a reversal at 13: frames 12 and 13 hit the cap, which left 14 and 15 alone free
        # (set back to 0), a two-frame bump with nothing around it.  All four frames move now, within the cap.
        keys = [bone("右腕", 0), bone("右腕", 10), bone("右腕", 12, rot=about((1.0, 0.0, 0.0), 40.0)),
                bone("右腕", 13, rot=about((1.0, 0.0, 0.0), 33.0)), bone("右腕", 21, rot=about((1.0, 0.0, 0.0), 70.0)),
                bone("右腕", 30, rot=about((1.0, 0.0, 0.0), 70.0))]
        plain, denoised, _ = plain_and_denoised(keys)
        p, d = x_degrees(track_of(plain, "右腕"), 0, 30), x_degrees(track_of(denoised, "右腕"), 0, 30)
        moved = [f for f in range(31) if abs(p[f] - d[f]) > 1e-9]
        self.assertEqual(moved, [12, 13, 14, 15])
        delta = [d[f] - p[f] for f in moved]
        self.assertLessEqual(max(abs(v) for v in delta), 3.0 + 1e-6)
        self.assertLess(abs(sum(delta)), 0.02 * sum(abs(v) for v in delta))     # zero mean (quaternion components: ~)

    def test_fingers_are_left_out_unless_asked_for(self):
        # review 9 low 3: the traced fingers are not on the 6-degree grid (3 % of their non-zero angles) and gained
        # nothing measurable from the denoise; a bone whose name holds 指 is smoothed but not denoised by default
        keys = swing("右人指１", jitter=4.0) + swing("右腕", jitter=4.0)
        plain, denoised, report = plain_and_denoised(keys)
        self.assertEqual(track_of(denoised, "右人指１"), track_of(plain, "右人指１"))
        self.assertNotEqual(track_of(denoised, "右腕"), track_of(plain, "右腕"))
        entries = {b["name"]: b["denoise"] for b in report["bones"]}
        self.assertEqual((entries["右人指１"]["frames"], entries["右人指１"]["skipped"]), (0, "finger"))
        self.assertEqual(report["denoise"]["fingers"], False)
        _, with_fingers, report = plain_and_denoised(keys, denoise_fingers=True)
        self.assertNotEqual(track_of(with_fingers, "右人指１"), track_of(plain, "右人指１"))
        self.assertEqual(report["denoise"]["fingers"], True)
        with self.assertRaises(ValueError):                                 # without the denoise it would do nothing
            smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys), denoise_fingers=True)

    def test_keys_three_frames_apart_are_not_dense(self):
        # review 9 low 5: a run of keys 3 frames apart is left alone (its alternation is 5 Hz, inside the beat)
        keys = swing(step=3, jitter=4.0)
        plain, denoised, report = plain_and_denoised(keys)
        self.assertEqual(vmd.dumps(denoised), vmd.dumps(plain))
        self.assertEqual(report["bones"][0]["denoise"]["frames"], 0)

    def test_an_already_baked_file_is_warned_about(self):
        # review 9 low 6: given its own output (a key on every frame), --denoise takes every key for dense
        keys = [bone("右腕", 4 * i, rot=about((0.0, 1.0, 0.0), 10.0 * math.sin(i))) for i in range(30)]
        baked, _ = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys))
        _, report = smooth_motion.smooth(baked, denoise=DENOISE)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("baked", report["warnings"][0])
        _, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=keys), denoise=DENOISE)
        self.assertEqual(report["warnings"], [])
        _, report = smooth_motion.smooth(baked)
        self.assertEqual(report["warnings"], [])                            # only the denoise is misled by it

    def test_the_result_is_deterministic(self):
        keys = swing(jitter=4.0) + [bone("センター", f, pos=(0.2 * (-1) ** f, 0.05 * f, 0.0)) for f in range(0, 61)]
        motion = vmd.Motion(model_name="m", bones=keys)
        first = vmd.dumps(smooth_motion.smooth(motion, denoise=DENOISE)[0])
        second = vmd.dumps(smooth_motion.smooth(motion, denoise=DENOISE)[0])
        self.assertEqual(first, second)

    def test_the_report_tells_what_was_moved(self):
        plain, denoised, report = plain_and_denoised(swing(jitter=10.0))
        self.assertEqual(report["denoise"], {"hz": DENOISE, "cap_deg": 3.0, "cap_units": 0.05, "max_gap": 2, "margin": 2})
        entry = report["bones"][0]["denoise"]
        self.assertEqual(entry["keys"], 87)                                 # 91 keys: all but the first two and the last two
        self.assertEqual(entry["frames"], 87)
        self.assertGreater(entry["at_cap"], 0)
        self.assertAlmostEqual(entry["max_deg"], 3.0, places=6)
        self.assertEqual(entry["max_units"], 0.0)
        _, _, report = plain_and_denoised(swing(step=2, jitter=10.0))      # 46 keys 2 frames apart: frames between keys move too
        self.assertEqual((report["bones"][0]["denoise"]["keys"], report["bones"][0]["denoise"]["frames"]), (44, 87))
        _, report = smooth_motion.smooth(vmd.Motion(model_name="m", bones=swing()))
        self.assertIsNone(report["denoise"])
        self.assertNotIn("denoise", report["bones"][0])

    def test_bad_parameters_are_refused(self):
        motion = vmd.Motion(model_name="m", bones=swing())
        for hz in (0.0, -1.0, 15.0, 20.0, float("nan")):
            with self.assertRaises(ValueError):
                smooth_motion.smooth(motion, denoise=hz)
        for cap in ((0.0, 0.05), (3.0, 0.0), (-1.0, 0.05), (float("inf"), 0.05), (3.0,)):
            with self.assertRaises(ValueError):
                smooth_motion.smooth(motion, denoise=DENOISE, denoise_cap=cap)
        with self.assertRaises(ValueError):                                 # a cap without the denoise does nothing: refused
            smooth_motion.smooth(motion, denoise_cap=(1.0, 0.01))


class DenoiseCommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        keys = swing(jitter=10.0) + zigzag()
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(vmd.Motion(model_name="dancer", bones=keys)))
        self.out = os.path.join(self.folder, "out.vmd")

    def test_denoise_with_and_without_a_cutoff(self):
        code, result = run(smooth_motion, [self.dance, self.out, "--denoise"])
        self.assertEqual(code, 0, result)
        summary = result["denoise"]
        self.assertEqual((summary["hz"], summary["cap_deg"], summary["cap_units"]), (7.5, 3.0, 0.05))
        self.assertEqual((summary["keys"], summary["frames"]), (87, 87))
        self.assertAlmostEqual(summary["max_deg"], 3.0, places=6)
        report = os.path.join(self.folder, "r.json")
        code, result = run(smooth_motion, [self.dance, self.out, "--denoise", "6", "--denoise-cap", "2", "0.03", "--report", report])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["denoise"]["hz"], result["denoise"]["cap_deg"], result["denoise"]["cap_units"]), (6.0, 2.0, 0.03))
        self.assertAlmostEqual(result["denoise"]["max_deg"], 2.0, places=5)
        with open(report, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["denoise"]["hz"], 6.0)
        self.assertIn("denoise", [b for b in saved["bones"] if b["name"] == "右腕"][0])
        code, result = run(smooth_motion, [self.dance, self.out])
        self.assertIsNone(result["denoise"])

    def test_fingers_and_the_warning_of_a_baked_file(self):
        code, result = run(smooth_motion, [self.dance, self.out, "--denoise", "--denoise-fingers"])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["denoise"]["fingers"], result["warnings"]), (True, []))
        again = os.path.join(self.folder, "again.vmd")
        code, result = run(smooth_motion, [self.out, again, "--denoise"])     # the output again: a key on every frame
        self.assertEqual(code, 0, result)
        self.assertEqual(result["denoise"]["fingers"], False)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("baked", result["warnings"][0])
        code, result = run(smooth_motion, [self.dance, self.out])
        self.assertEqual(result["warnings"], [])

    def test_bad_denoise_arguments_exit_2(self):
        for argv in (["--denoise-cap", "2", "0.03"], ["--denoise", "16"], ["--denoise", "0"], ["--denoise", "7.5", "--denoise-cap", "0", "1"],
                     ["--denoise-fingers"]):
            code, result = run(smooth_motion, [self.dance, self.out] + argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertFalse(os.path.exists(self.out), argv)


def fft(values):
    """radix-2 FFT of a list of complex numbers whose length is a power of 2"""
    n = len(values)
    a = list(values)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    size = 2
    while size <= n:
        w = cmath.exp(-2j * math.pi / size)
        half = size // 2
        for start in range(0, n, size):
            t = 1.0
            for k in range(start, start + half):
                u, v = a[k], a[k + half] * t
                a[k], a[k + half] = u + v, u - v
                t *= w
        size *= 2
    return a


def energy_bands(signal):
    """(total, above 6 Hz, 1 to 4 Hz) energy of a real sequence sampled at 30 fps, zero padded to a power of 2"""
    n = 1
    while n < len(signal):
        n *= 2
    spectrum = fft([complex(v) for v in signal] + [0j] * (n - len(signal)))
    total = high = low = 0.0
    for k in range(n // 2 + 1):
        e = abs(spectrum[k]) ** 2 * (1.0 if k == 0 or 2 * k == n else 2.0)
        total += e
        high += e if k * 30.0 / n > 6.0 else 0.0
        low += e if 1.0 <= k * 30.0 / n <= 4.0 else 0.0
    return total, high, low


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
            self.assertTrue(same_quaternion(got.rotation, k.rotation), (name.encode("ascii", "backslashreplace"), frame))
        self.assertEqual(back.morphs, before.morphs)
        self.assertGreater(sum(b["keys_after"] for b in report["bones"]), len(before.bones))
        tb, ta = smooth_motion.tracks_of(before), smooth_motion.tracks_of(back)
        for name in ("右足ＩＫ", "左足ＩＫ"):
            floor = min(k.position[1] for k in tb[name])
            self.assertGreaterEqual(min(k.position[1] for k in ta[name]), floor, name.encode("ascii", "backslashreplace"))
        dev = deviation_from_mmd_path(before, back)
        self.assertLess(dev["lateral"][0], 8.0, dev)                          # off the arc, max
        self.assertLess(dev["lateral"][1], 3.0, dev)                          # off the arc, p99
        self.assertLess(dev["excess"][0], 8.0, dev)                           # beyond the ease's timing bound, max
        self.assertLess(dev["position"][0], 1.0, dev)
        self.assertLess(len(data), 50 * 1024 * 1024, len(data))

    def test_the_denoise_of_the_whole_dance_keeps_its_guarantees_and_is_quick(self):
        before = vmd.load(REAL)
        plain, _ = smooth_motion.smooth(before)
        started = time.perf_counter()
        after, report = smooth_motion.smooth(before, denoise=smooth_motion.DENOISE_HZ)
        data = vmd.dumps(after)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 60.0, elapsed)
        self.assertEqual(len(vmd.loads(data).bones), len(plain.bones))     # the denoise moves values, never frames
        cap_deg, cap_units = smooth_motion.DENOISE_CAP
        tp, ta, tb = smooth_motion.tracks_of(plain), smooth_motion.tracks_of(after), smooth_motion.tracks_of(before)
        moved = 0
        for name, keys in tp.items():
            got = ta[name]
            self.assertEqual([k.frame for k in got], [k.frame for k in keys])
            for a, b in zip(keys, got):
                if a is b or (a.position == b.position and a.rotation == b.rotation):
                    continue
                moved += 1
                self.assertLessEqual(max(abs(x - y) for x, y in zip(a.position, b.position)), cap_units + 1e-9)
                # against the rotation the stored quaternion stands for (a stored key is unit only to ~1e-6)
                self.assertLessEqual(angle_between(smooth_motion._normalized(a.rotation), b.rotation), cap_deg + 1e-4)
        self.assertGreater(moved, 10000)
        # review 9 M1: no lone corrected frame (moved frames grouped where they are at most 3 frames apart)
        lone = []
        for name, keys in tp.items():
            frames = [a.frame for a, b in zip(keys, ta[name]) if (a.position, a.rotation) != (b.position, b.rotation)]
            groups = []
            for f in frames:
                if groups and f - groups[-1][-1] <= 3:
                    groups[-1].append(f)
                else:
                    groups.append([f])
            by_p, by_a = {k.frame: k for k in keys}, {k.frame: k for k in ta[name]}
            for g in groups:
                if len(g) == 1 and angle_between(smooth_motion._normalized(by_p[g[0]].rotation), by_a[g[0]].rotation) > 1.0:
                    lone.append((name.encode("ascii", "backslashreplace"), g[0]))
        self.assertEqual(lone, [])
        for name in ("右足ＩＫ", "左足ＩＫ", "センター"):
            floor = min(k.position[1] for k in tb[name])
            self.assertGreaterEqual(min(k.position[1] for k in ta[name]), floor, name.encode("ascii", "backslashreplace"))
        for name, keys in tb.items():                                       # every hold of the dance is still a hold
            by = {k.frame: k for k in ta[name]}
            last = {}
            for k in keys:
                last[k.frame] = k                                           # of two keys on one frame the last one counts
            keys = [last[f] for f in sorted(last)]
            for a, b in zip(keys, keys[1:]):
                if smooth_motion.is_flat(a, b) and a.frame in by:
                    self.assertEqual((by[a.frame].position, by[a.frame].rotation), (by[b.frame].position, by[b.frame].rotation))
        jerk_plain = motion_jerk.measure(plain, ["右腕", "左腕"])["bones"]
        jerk_after = motion_jerk.measure(after, ["右腕", "左腕"])["bones"]
        for name in ("右腕", "左腕"):
            self.assertLess(jerk_after[name]["p99"], 0.85 * jerk_plain[name]["p99"], name.encode("ascii", "backslashreplace"))
        self.assertEqual(report["denoise"]["hz"], smooth_motion.DENOISE_HZ)
        # what is taken out is high frequency: the energy of the removed signal (plain minus denoised, per channel) lies
        # mostly above 6 Hz and little of it in the 1-4 Hz of the beat
        rotation = [0.0, 0.0, 0.0]
        for name in ("センター", "上半身", "右腕", "左腕", "右ひじ", "頭"):
            p, d = {k.frame: k for k in tp[name]}, {k.frame: k for k in ta[name]}
            removed = []
            for f in range(tp[name][0].frame, tp[name][-1].frame + 1):
                same = f not in p or p[f].rotation == d[f].rotation
                removed.append((0.0, 0.0, 0.0) if same else smooth_motion.log_map(smooth_motion.relative(d[f].rotation, p[f].rotation)))
            for c in range(3):
                rotation = [x + y for x, y in zip(rotation, energy_bands([math.degrees(v[c]) for v in removed]))]
        self.assertGreater(rotation[1] / rotation[0], 0.8, rotation)
        self.assertLess(rotation[2] / rotation[0], 0.1, rotation)
        p, d = {k.frame: k for k in tp["センター"]}, {k.frame: k for k in ta["センター"]}
        position = [0.0, 0.0, 0.0]
        for c in range(3):
            removed = [p[f].position[c] - d[f].position[c] if f in p else 0.0 for f in range(min(p), max(p) + 1)]
            position = [x + y for x, y in zip(position, energy_bands(removed))]
        self.assertGreater(position[1] / position[0], 0.8, position)
        self.assertLess(position[2] / position[0], 0.1, position)


if __name__ == "__main__":
    unittest.main()
