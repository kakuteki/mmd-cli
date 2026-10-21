"""tools/make_camera.py: a calm camera motion generated from a dance motion, without MMD."""
import contextlib
import glob
import importlib.util
import io
import json
import math
import os
import tempfile
import unittest

from mmd_cli import mathutil, motion_edit
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("make_camera", os.path.join(ROOT, "tools", "make_camera.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_camera = load_tool()

# the synthetic dance: a quiet part, a wild part, a quiet tail (frames, both ends of each part included)
QUIET = (0, 599)
WILD = (600, 1199)
TAIL = (1200, 1499)
LAST = 1499
CENTER_X_END, CENTER_Z_END = 4.0, -2.0           # where the center walks to during the wild part


def center_at(frame):
    """the center's x, z of the synthetic dance: still, then a straight walk during the wild part"""
    if frame <= WILD[0]:
        t = 0.0
    elif frame >= WILD[1] + 1:
        t = 1.0
    else:
        t = (frame - WILD[0]) / float(WILD[1] + 1 - WILD[0])
    return CENTER_X_END * t, CENTER_Z_END * t


def bone(name, frame, pos=(0, 0, 0), rot=(0, 0, 0)):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in pos), mathutil.euler_to_quat(*rot))


def synthetic_dance():
    """arms and head sway 5 degrees every 2 seconds in the quiet parts and swing 60 degrees every 10 frames in
    the wild part, while the center walks to (4, -2) during the wild part; keys are in no particular order"""
    bones = []
    for frame in range(QUIET[0], QUIET[1] + 1, 60):
        sign = 1 if (frame // 60) % 2 == 0 else -1
        bones += [bone("右腕", frame, rot=(0, 0, 5 * sign)), bone("左腕", frame, rot=(0, 0, -5 * sign)),
                  bone("頭", frame, rot=(0, 3 * sign, 0)), bone("センター", frame)]
    for frame in range(WILD[0], WILD[1] + 1, 10):
        sign = 1 if (frame // 10) % 2 == 0 else -1
        x, z = center_at(frame)
        bones += [bone("右腕", frame, rot=(0, 0, 60 * sign)), bone("左腕", frame, rot=(0, 0, -60 * sign)),
                  bone("頭", frame, rot=(0, 20 * sign, 0)), bone("センター", frame, pos=(x, 0, z))]
    for frame in range(TAIL[0], TAIL[1] + 1, 60):
        sign = 1 if (frame // 60) % 2 == 0 else -1
        x, z = center_at(frame)
        bones += [bone("右腕", frame, rot=(0, 0, 5 * sign)), bone("左腕", frame, rot=(0, 0, -5 * sign)),
                  bone("頭", frame, rot=(0, 3 * sign, 0)), bone("センター", frame, pos=(x, 0, z))]
    bones.append(bone("センター", LAST, pos=(CENTER_X_END, 0, CENTER_Z_END)))
    bones.reverse()
    return vmd.Motion(model_name="synthetic", bones=bones)


def mean(values):
    return sum(values) / float(len(values))


class IntensityTest(unittest.TestCase):
    def test_the_wild_part_is_much_stronger_than_the_quiet_parts(self):
        analysis = make_camera.analyze(synthetic_dance())
        intensity = analysis.intensity
        self.assertEqual(len(intensity), LAST + 1)
        self.assertEqual(analysis.last, LAST)
        quiet = mean(intensity[QUIET[0]:QUIET[1] + 1])
        wild = mean(intensity[WILD[0] + 30:WILD[1] - 30])
        tail = mean(intensity[TAIL[0] + 60:TAIL[1] + 1])
        self.assertGreater(quiet, 0.0)
        self.assertGreater(wild, 5 * quiet)
        self.assertGreater(wild, 5 * tail)
        self.assertTrue(all(v >= 0.0 for v in intensity))

    def test_sections_split_the_wild_part_from_the_quiet_ones(self):
        analysis = make_camera.analyze(synthetic_dance())
        self.assertLess(analysis.thresholds["low"], analysis.thresholds["high"])
        high = [s for s in analysis.sections if s.level == "high"]
        low = [s for s in analysis.sections if s.level == "low"]
        self.assertTrue(high and low)
        # the sections cover every frame once, in order
        self.assertEqual(analysis.sections[0].start, 0)
        self.assertEqual(analysis.sections[-1].end, LAST)
        for before, after in zip(analysis.sections, analysis.sections[1:]):
            self.assertEqual(after.start, before.end + 1)
            self.assertNotEqual(after.level, before.level)
        # the biggest high section sits inside the wild part (give or take the smoothing windows)
        biggest = max(high, key=lambda s: s.end - s.start)
        self.assertGreater(biggest.start, WILD[0] - 90)
        self.assertLess(biggest.end, WILD[1] + 90)
        self.assertGreater(biggest.end - biggest.start, 300)
        boundaries = [b.frame for b in analysis.boundaries]
        self.assertEqual(boundaries, [s.start for s in analysis.sections[1:]])
        self.assertTrue(all(b.strength > 0 for b in analysis.boundaries))

    def test_the_cut_lands_within_half_a_second_of_the_change_of_pace(self):
        # the pace changes at 600 and at 1200; the hysteresis confirms it only later (the trend reaches the
        # upper threshold about 1.2 s after 600), but the cut must sit where the pace changed
        analysis = make_camera.analyze(synthetic_dance())
        strongest = sorted(analysis.boundaries, key=lambda b: -b.strength)[:2]
        frames = sorted(b.frame for b in strongest)
        self.assertEqual(len(frames), 2)
        self.assertLessEqual(abs(frames[0] - WILD[0]), 15, frames)
        self.assertLessEqual(abs(frames[1] - TAIL[0]), 15, frames)

    def test_a_still_dance_has_one_section_and_zero_intensity(self):
        still = vmd.Motion(model_name="m", bones=[bone("センター", 0), bone("センター", 300)])
        analysis = make_camera.analyze(still)
        self.assertEqual(analysis.last, 300)
        self.assertEqual(set(analysis.intensity), {0.0})
        self.assertEqual(len(analysis.sections), 1)
        self.assertEqual((analysis.sections[0].start, analysis.sections[0].end), (0, 300))
        self.assertEqual(analysis.boundaries, [])

    def test_no_bone_keys_is_an_error(self):
        with self.assertRaises(ValueError):
            make_camera.analyze(vmd.Motion(model_name="m"))
        with self.assertRaises(ValueError):
            make_camera.analyze(vmd.Motion(model_name="m", bones=[bone("センター", 0)]))


class WeightsTest(unittest.TestCase):
    def total(self, name, rot=(0, 0, 0), pos=(0, 0, 0)):
        motion = vmd.Motion(model_name="m", bones=[bone(name, 0), bone(name, 60, pos=pos, rot=rot)])
        return sum(make_camera.analyze(motion).intensity)

    def test_the_same_turn_counts_by_what_the_bone_swings(self):
        arm, elbow, head, finger = (self.total(n, rot=(0, 0, 30)) for n in ("右腕", "右ひじ", "頭", "右人指１"))
        self.assertGreater(arm, elbow)
        self.assertGreater(elbow, head)
        self.assertGreater(head, finger)
        self.assertGreater(finger, 0.0)
        self.assertGreater(self.total("上半身", rot=(0, 30, 0)), arm * 0.99)

    def test_a_foot_ik_turn_counts_little_but_its_move_counts(self):
        self.assertLess(self.total("右足ＩＫ", rot=(0, 0, 30)), self.total("右足", rot=(0, 0, 30)))
        self.assertEqual(self.total("右足IK", rot=(0, 0, 30)), self.total("右足ＩＫ", rot=(0, 0, 30)))    # half-width IK too
        self.assertGreater(self.total("右足ＩＫ", pos=(0, 0, 2)), 0.0)
        self.assertGreater(self.total("センター", pos=(0, 0, 2)), self.total("右足ＩＫ", pos=(0, 0, 2)))

    def test_a_twist_bone_counts_as_little_as_a_hand_twist(self):
        # 腕捩 turns the arm about its own axis: the hand hardly moves, so it must not count as an arm swing
        self.assertEqual(self.total("右腕捩", rot=(0, 30, 0)), self.total("右手捩", rot=(0, 30, 0)))
        self.assertLess(self.total("右腕捩", rot=(0, 30, 0)), self.total("右腕", rot=(0, 30, 0)) / 3.0)

    def test_a_turn_is_measured_as_the_angle_between_the_quaternions(self):
        q = mathutil.euler_to_quat(0, 0, 40)
        self.assertAlmostEqual(make_camera.quat_angle((0, 0, 0, 1), q), 40.0 * 3.141592653589793 / 180.0, places=6)
        self.assertAlmostEqual(make_camera.quat_angle(q, tuple(-c for c in q)), 0.0, places=9)     # q and -q are one rotation
        self.assertAlmostEqual(make_camera.quat_angle(q, q), 0.0, places=9)
        self.assertEqual(self.total("右腕", rot=(0, 0, 30)), self.total("右腕", rot=(0, 0, -30)))

    def test_the_turn_is_spread_over_the_frames_between_the_keys(self):
        motion = vmd.Motion(model_name="m", bones=[bone("右腕", 0), bone("右腕", 100, rot=(0, 0, 30)), bone("右腕", 200, rot=(0, 0, 30))])
        intensity = make_camera.analyze(motion).intensity
        self.assertGreater(intensity[50], 0.0)
        self.assertAlmostEqual(intensity[50], intensity[60], places=9)
        self.assertEqual(intensity[170], 0.0)           # nothing moves after frame 100 (the window ends before 170)


def still_dance(last):
    return vmd.Motion(model_name="m", bones=[bone("センター", 0), bone("センター", last)])


def length(shot):
    return shot.end - shot.start + 1


class ShotLengthTest(unittest.TestCase):
    def test_shots_cover_the_dance_in_order_within_the_limits(self):
        shots = make_camera.plan_shots(synthetic_dance(), seed=1)
        self.assertEqual(shots[0].start, 0)
        self.assertEqual(shots[-1].end, LAST)
        for before, after in zip(shots, shots[1:]):
            self.assertEqual(after.start, before.end + 1)
        for s in shots:
            self.assertTrue(make_camera.MIN_SHOT <= length(s) <= make_camera.MAX_SHOT, (s.start, s.end))
        self.assertGreaterEqual(len(shots), 4)                       # 1500 frames, at most 480 each
        self.assertEqual([s.index for s in shots], list(range(len(shots))))

    def test_a_cut_falls_on_the_strongest_boundary_in_reach(self):
        dance = synthetic_dance()
        analysis = make_camera.analyze(dance)
        shots = make_camera.plan_shots(dance, analysis=analysis)
        strongest = max(analysis.boundaries, key=lambda b: b.strength).frame
        self.assertIn(strongest, [s.start for s in shots])
        before = [s for s in shots if s.end == strongest - 1][0]
        self.assertEqual(before.cut, "section")
        self.assertIn(shots[-1].cut, ("end",))

    def test_a_dance_without_boundaries_is_cut_evenly(self):
        shots = make_camera.plan_shots(still_dance(5999))
        self.assertEqual(shots[-1].end, 5999)
        for s in shots:
            self.assertTrue(make_camera.MIN_SHOT <= length(s) <= make_camera.MAX_SHOT, (s.start, s.end))
        self.assertEqual({s.cut for s in shots[:-1]}, {"even"})
        self.assertLessEqual(max(length(s) for s in shots) - min(length(s) for s in shots), 1)

    def test_other_limits_and_their_checks(self):
        shots = make_camera.plan_shots(synthetic_dance(), min_shot=90, max_shot=200)
        for s in shots:
            self.assertTrue(90 <= length(s) <= 200, (s.start, s.end))
        self.assertGreaterEqual(len(shots), 8)
        for bad in (dict(min_shot=200, max_shot=300), dict(min_shot=1, max_shot=10), dict(min_shot=0, max_shot=0)):
            with self.assertRaises(ValueError, msg=bad):
                make_camera.plan_shots(synthetic_dance(), **bad)

    def test_a_dance_shorter_than_a_shot_is_one_shot(self):
        shots = make_camera.plan_shots(still_dance(100))
        self.assertEqual([(s.start, s.end) for s in shots], [(0, 100)])

    def analysis_with(self, last, boundaries):
        """an Analysis whose only content is the cuts: (frame, strength) pairs"""
        n = last + 1
        sections, start, level = [], 0, "low"
        for frame, _ in boundaries:
            sections.append(make_camera.Section(start, frame - 1, level, 0.0))
            start, level = frame, "high" if level == "low" else "low"
        sections.append(make_camera.Section(start, last, level, 0.0))
        return make_camera.Analysis(last, [0.0] * n, [0.0] * n, {"low": 0.0, "high": 0.0}, sections,
                                    [make_camera.Boundary(f, s) for f, s in boundaries])

    def test_a_cut_just_out_of_reach_is_met_by_dividing_the_stretch_before_it(self):
        # 523 is 43 frames beyond the longest shot: two shots of 262 / 261 end on it instead of 456 + ...
        shots = make_camera.cut_shots(self.analysis_with(1499, [(523, 10.0)]))
        self.assertEqual(shots[:2], [(0, 261, "even"), (262, 522, "section")])
        self.assertEqual(shots[2][0], 523)
        self.assertEqual(shots[-1][1], 1499)
        for start, end, _ in shots:
            self.assertTrue(180 <= end - start + 1 <= 480, (start, end))

    def test_random_cuts_always_respect_the_limits(self):
        import random
        rng = random.Random(0)
        for _ in range(300):
            min_shot = rng.choice((2, 30, 180, 300))
            max_shot = min_shot * rng.choice((2, 3, 5)) + rng.randint(0, 50)
            last = rng.randint(min_shot, 12000)
            frames = sorted(set(rng.randint(1, last) for _ in range(rng.randint(0, 40))))
            boundaries = [(f, rng.random() * 100) for f in frames]
            shots = make_camera.cut_shots(self.analysis_with(last, boundaries), min_shot, max_shot)
            self.assertEqual((shots[0][0], shots[-1][1]), (0, last), (min_shot, max_shot, last, frames))
            for (a0, a1, _), (b0, _, _) in zip(shots, shots[1:]):
                self.assertEqual(b0, a1 + 1)
            for start, end, _ in shots:
                self.assertTrue(min_shot <= end - start + 1 <= max_shot, (min_shot, max_shot, last, frames, shots))

    def test_only_a_clear_cut_is_aimed_at_from_afar(self):
        # 700 is weak (below the median strength): the stretch is divided up to 900, and 900 is the cut
        shots = make_camera.cut_shots(self.analysis_with(2999, [(700, 1.0), (900, 50.0)]))
        self.assertEqual(shots[:2], [(0, 449, "even"), (450, 899, "section")])
        # in reach, the strongest cut wins even when it is weak in absolute terms
        shots = make_camera.cut_shots(self.analysis_with(2999, [(300, 1.0), (1500, 50.0)]))
        self.assertEqual(shots[0], (0, 299, "section"))


class ShotTypeTest(unittest.TestCase):
    def plans(self, dance, seeds=range(10), **limits):
        return [make_camera.plan_shots(dance, seed=seed, **limits) for seed in seeds]

    def test_the_same_type_never_follows_itself(self):
        for shots in self.plans(synthetic_dance()) + self.plans(still_dance(5999), seeds=range(3)):
            for s in shots:
                self.assertIn(s.kind, make_camera.TYPES)
            for before, after in zip(shots, shots[1:]):
                self.assertNotEqual(before.kind, after.kind, [s.kind for s in shots])

    def test_values_stay_inside_the_ranges(self):
        plans = self.plans(synthetic_dance()) + self.plans(synthetic_dance(), seeds=range(3), min_shot=90, max_shot=200)
        for shots in plans:
            for s in shots:
                for d in s.distance:
                    self.assertTrue(make_camera.DISTANCE_RANGE[0] <= d <= make_camera.DISTANCE_RANGE[1], s)
                self.assertTrue(make_camera.HEIGHT_RANGE[0] <= s.height <= make_camera.HEIGHT_RANGE[1], s)
                for x, y, z in s.rot:
                    self.assertTrue(make_camera.ANGLE_X_RANGE[0] <= x <= make_camera.ANGLE_X_RANGE[1], s)
                    self.assertTrue(make_camera.ANGLE_Y_RANGE[0] <= y <= make_camera.ANGLE_Y_RANGE[1], s)
                    self.assertEqual(z, 0.0)

    def test_each_type_has_its_values_and_peaks_pull_back(self):
        want = {"push_in": (38.0, 32.0), "pull_out": (32.0, 42.0), "orbit": (34.0, 34.0), "above": (38.0, 36.0)}
        heights = {"push_in": 13.0, "pull_out": 13.0, "orbit": 12.0, "above": 12.0}
        seen = set()
        for shots in self.plans(synthetic_dance(), seeds=range(20)):
            for s in shots:
                seen.add((s.kind, s.level))
                add = 6.0 if s.level == "peak" else 0.0
                self.assertEqual(s.distance, (want[s.kind][0] + add, want[s.kind][1] + add), s)
                self.assertEqual(s.height, heights[s.kind], s)
                self.assertEqual(s.rot[0][0], 10.0 if s.kind == "above" else 0.0)
                self.assertEqual(s.rot[1][0], s.rot[0][0])
                if s.kind == "orbit":
                    swing = 22.0 if s.level == "peak" else 15.0
                    self.assertEqual(sorted((s.rot[0][1], s.rot[1][1])), [-swing, swing], s)
                else:
                    self.assertEqual((s.rot[0][1], s.rot[1][1]), (0.0, 0.0))
        self.assertTrue({k for k, lv in seen} >= set(make_camera.TYPES))
        self.assertIn(("orbit", "peak"), seen)

    def test_the_wild_part_is_a_peak_and_the_quiet_parts_are_valleys(self):
        dance = synthetic_dance()
        analysis = make_camera.analyze(dance)
        shots = make_camera.plan_shots(dance, analysis=analysis)
        wild = min(shots, key=lambda s: abs(s.start - WILD[0]))           # the shot that starts on the change of pace
        self.assertLessEqual(abs(wild.start - WILD[0]), 15)
        self.assertEqual(wild.level, "peak")
        self.assertEqual(shots[0].level, "valley")
        self.assertEqual(shots[-1].level, "valley")
        self.assertGreater(wild.intensity["mean"], 5 * shots[0].intensity["mean"])
        self.assertGreaterEqual(wild.intensity["max"], wild.intensity["mean"])

    def test_valleys_lean_to_push_ins_and_peaks_away_from_them(self):
        by_level = {"peak": [], "valley": []}
        for shots in self.plans(synthetic_dance(), seeds=range(40)):
            for s in shots:
                if s.level in by_level:
                    by_level[s.level].append(s.kind)
        share = {lv: kinds.count("push_in") / float(len(kinds)) for lv, kinds in by_level.items()}
        self.assertGreater(share["valley"], share["peak"] + 0.15, share)

    def test_orbits_alternate_their_direction(self):
        directions = []
        for shots in self.plans(still_dance(11999), seeds=range(2)):
            directions.append([1 if s.rot[1][1] > s.rot[0][1] else -1 for s in shots if s.kind == "orbit"])
        self.assertTrue(all(len(d) >= 3 for d in directions), directions)
        for d in directions:
            for before, after in zip(d, d[1:]):
                self.assertEqual(after, -before)

    def test_every_cut_changes_the_picture_clearly(self):
        # a cut between two nearly equal pictures (the end of a push in, the start of a pull out: the same
        # angle, 13 % more distance) reads as a dropped frame, not as a cut
        plans = self.plans(synthetic_dance(), seeds=range(40)) + self.plans(still_dance(11999), seeds=range(3))
        pairs = 0
        for shots in plans:
            for before, after in zip(shots, shots[1:]):
                pairs += 1
                (x0, y0, _), (x1, y1, _) = before.rot[1], after.rot[0]
                clear = (abs(after.distance[0] - before.distance[1]) >= 8.0 or abs(x1 - x0) >= 10.0
                         or abs(y1 - y0) >= 10.0 or abs(after.height - before.height) >= 3.0)
                self.assertTrue(clear, (before.kind, before.level, before.distance, before.height, before.rot,
                                        after.kind, after.level, after.distance, after.height, after.rot))
        self.assertGreater(pairs, 100)


def picture_span(distance, height, x_angle, fov=30.0):
    """the heights the picture covers at the dancer's plane: the camera sits `distance` from the look-at point
    (x, `height`) along a line tilted by the X angle (the window's value: negative looks up), and the picture
    is `fov` degrees tall"""
    up = math.radians(-x_angle)
    camera_height = height - distance * math.sin(up)
    forward = distance * math.cos(up)
    half = math.radians(fov / 2.0)
    return camera_height + forward * math.tan(up - half), camera_height + forward * math.tan(up + half)


class FramingTest(unittest.TestCase):
    HEAD_ROOM, KNEES = 21.0, 5.0        # Rin's head top is at about 19.5, the ribbon at 20.8 (the frame 0 render)

    def test_the_span_formula_matches_the_frame_0_render(self):
        # the spike's frame 0 (look-at 15, distance 25, angles 0) showed the hem cut at the bottom and the
        # ribbon touching the top: 8.3 to 21.7
        bottom, top = picture_span(25.0, 15.0, 0.0)
        self.assertAlmostEqual(bottom, 8.30, places=2)
        self.assertAlmostEqual(top, 21.70, places=2)
        self.assertEqual(make_camera.picture_span(25.0, 15.0, 0.0), (bottom, top))

    def test_every_kind_keeps_the_dancer_from_the_knees_to_above_the_head(self):
        for kind in make_camera.TYPES:
            for level in ("valley", "peak", "mid"):
                for sign in (1, -1):
                    distance, height, rot = make_camera.shot_values(kind, level, sign)
                    for which in (0, 1):
                        bottom, top = picture_span(distance[which], height, rot[which][0])
                        self.assertGreaterEqual(top, self.HEAD_ROOM, (kind, level, which, distance, height, rot))
                        self.assertLessEqual(bottom, self.KNEES, (kind, level, which, distance, height, rot))

    HIPS = 10.0                         # the hem of Rin's skirt is at about 8, her hips at about 10

    def camera_height(self, distance, height, x_angle):
        return height - distance * math.sin(math.radians(-x_angle))

    def test_no_camera_sits_below_the_hips(self):
        # a camera below the hips looks up into a skirt that flares in a turn: seen on the first full render,
        # where the low angle shot (camera 4 units above the floor) showed the underwear for some frames
        for kind in make_camera.TYPES:
            for level in ("valley", "peak", "mid"):
                distance, height, rot = make_camera.shot_values(kind, level, 1)
                for which in (0, 1):
                    self.assertGreaterEqual(self.camera_height(distance[which], height, rot[which][0]), self.HIPS,
                                            (kind, level, which, distance, height, rot))

    def test_the_shot_from_above_looks_down_from_about_head_height(self):
        distance, height, rot = make_camera.shot_values("above", "valley", 1)
        self.assertGreater(rot[0][0], 0.0)                           # the window's positive X looks down
        self.assertTrue(16.0 < self.camera_height(distance[0], height, rot[0][0]) < 20.0)
        self.assertNotIn("low", make_camera.TYPES)


def swaying_dance(last=2999, amplitude=5.0, period=600):
    """the center sways `amplitude` units from side to side every `period` frames (a 20 second figure of eight
    is too wide to follow with a straight line per shot) while the arms swing; one center key per 10 frames"""
    bones = []
    for frame in range(0, last + 1, 10):
        sign = 1 if (frame // 10) % 2 == 0 else -1
        bones += [bone("右腕", frame, rot=(0, 0, 40 * sign)), bone("左腕", frame, rot=(0, 0, -40 * sign)),
                  bone("センター", frame, pos=(sway_x(frame, amplitude, period), 0, 0))]
    return vmd.Motion(model_name="sway", bones=bones)


def sway_x(frame, amplitude=5.0, period=600):
    return amplitude * math.sin(2 * math.pi * frame / float(period))


def interpolated(track, frame):
    """the look-at point MMD shows at `frame`: a straight line between the shot's keys around it"""
    for (f0, p0), (f1, p1) in zip(track, track[1:]):
        if f0 <= frame <= f1:
            t = (frame - f0) / float(f1 - f0)
            return tuple(a + (b - a) * t for a, b in zip(p0, p1))
    raise AssertionError((frame, track))


class LookAtTest(unittest.TestCase):
    def test_the_look_at_follows_the_center_at_both_ends_of_a_shot(self):
        # within a tenth of a unit: the look-at point is the center smoothed over 3 seconds, which rounds the
        # corners of the walk (at 600 and 1200) by less than that; where the center stands still it is exact
        for shots in (make_camera.plan_shots(synthetic_dance(), seed=s) for s in range(3)):
            for s in shots:
                for frame, pos in ((s.start, s.pos[0]), (s.end, s.pos[1])):
                    x, z = center_at(frame)
                    self.assertLess(abs(pos[0] - x), 0.1, (s.start, s.end, frame, pos))
                    self.assertLess(abs(pos[2] - z), 0.1, (s.start, s.end, frame, pos))
                    self.assertEqual(pos[1], s.height)
        shots = make_camera.plan_shots(synthetic_dance())
        self.assertEqual(shots[0].pos[0], (0.0, shots[0].height, 0.0))
        self.assertAlmostEqual(shots[-1].pos[1][0], CENTER_X_END, places=5)
        self.assertAlmostEqual(shots[-1].pos[1][2], CENTER_Z_END, places=5)

    def test_the_dancer_stays_near_the_look_at_through_a_shot(self):
        # the shot's keys (3 seconds apart at most) keep the dancer within a unit of the look-at point; two keys
        # per shot would let a 20 second sway drift 5 units (a third of the picture) off centre
        dance = swaying_dance()
        for seed in range(3):
            shots = make_camera.plan_shots(dance, seed=seed)
            for s in shots:
                frames = [f for f, _ in s.track]
                self.assertEqual((frames[0], frames[-1]), (s.start, s.end))
                self.assertTrue(all(b > a for a, b in zip(frames, frames[1:])), frames)
                self.assertLessEqual(max(b - a for a, b in zip(frames, frames[1:])), 90, frames)
                self.assertEqual((s.pos[0], s.pos[1]), (s.track[0][1], s.track[-1][1]))
                for frame in range(s.start, s.end + 1):
                    x, y, z = interpolated(s.track, frame)
                    self.assertLess(abs(x - sway_x(frame)), 1.0, (s.start, s.end, frame, x))
                    self.assertEqual((y, z), (s.height, 0.0))

    def test_the_look_at_does_not_twitch_with_a_bouncing_center(self):
        # a center that hops a unit to the side and back every 10 frames (a step) must not shake the camera;
        # the average stays centred on its frame, so it narrows towards the two ends of the dance (there the
        # look-at point is the center itself) and the first and last keys are left out here
        bones = []
        for frame in range(0, 1200, 10):
            bones += [bone("センター", frame, pos=(1.0 if (frame // 10) % 2 else -1.0, 0, 0)), bone("右腕", frame, rot=(0, 0, 20))]
        shots = make_camera.plan_shots(vmd.Motion(model_name="hop", bones=bones))
        checked = 0
        for s in shots:
            for frame, pos in s.track:
                if 45 <= frame <= 1190 - 45:
                    self.assertLess(abs(pos[0]), 0.15, (frame, pos))
                    checked += 1
        self.assertGreater(checked, 8)
        self.assertEqual(shots[0].track[0][1][0], -1.0)                  # frame 0: the center itself

    def test_the_parents_of_the_center_are_added(self):
        dance = synthetic_dance()
        dance.bones += [bone("全ての親", 0, pos=(10, 0, 0)), bone("全ての親", LAST, pos=(10, 0, 0)),
                        bone("グルーブ", 0, pos=(0, 1, 1)), bone("グルーブ", LAST, pos=(0, 1, 1))]
        shots = make_camera.plan_shots(dance)
        self.assertAlmostEqual(shots[0].pos[0][0], 10.0, places=6)
        self.assertAlmostEqual(shots[0].pos[0][2], 1.0, places=6)
        self.assertAlmostEqual(shots[-1].pos[1][0], 10.0 + CENTER_X_END, places=5)
        self.assertEqual(shots[0].pos[0][1], shots[0].height)         # the parents' height is not followed

    def test_before_the_first_and_after_the_last_center_key(self):
        track = make_camera.center_track(vmd.Motion(model_name="m", bones=[
            bone("センター", 100, pos=(1, 0, 0)), bone("センター", 200, pos=(3, 0, -2)), bone("右腕", 0), bone("右腕", 300)]))
        self.assertEqual(make_camera.look_at(track, 0, 12.0), (1.0, 12.0, 0.0))
        self.assertEqual(make_camera.look_at(track, 150, 12.0), (2.0, 12.0, -1.0))
        self.assertEqual(make_camera.look_at(track, 300, 9.0), (3.0, 9.0, -2.0))
        self.assertEqual(make_camera.look_at(make_camera.center_track(vmd.Motion(model_name="m")), 5, 7.0), (0.0, 7.0, 0.0))


def read_back(shots):
    return vmd.loads(vmd.dumps(make_camera.camera_motion(shots)))


def keys_by_shot(shots, back):
    """the keys of each shot, in order"""
    out, keys = [], list(back.cameras)
    for s in shots:
        mine = [k for k in keys if s.start <= k.frame <= s.end]
        out.append(mine)
    return out


def bezier_y_at(curve, x):
    """y of an MMD curve (x1, y1, x2, y2 in 0..127) at x in 0..1, by bisection on the cubic's x"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)

    def point(t):
        u = 1.0 - t
        return (3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3, 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if point(mid)[0] < x:
            lo = mid
        else:
            hi = mid
    return point((lo + hi) / 2.0)[1]


class OutputTest(unittest.TestCase):
    def test_one_key_on_the_cut_then_one_every_3_seconds_at_most(self):
        shots = make_camera.plan_shots(synthetic_dance())
        back = read_back(shots)
        self.assertTrue(back.is_camera)
        self.assertEqual((back.bones, back.morphs, back.lights), ([], [], []))
        frames = [k.frame for k in back.cameras]
        self.assertEqual((frames[0], frames[-1]), (0, LAST))
        self.assertTrue(all(b > a for a, b in zip(frames, frames[1:])), frames)
        self.assertEqual(frames, [f for s in shots for f, _ in s.track])
        for s, keys in zip(shots, keys_by_shot(shots, back)):
            self.assertEqual(len(keys), 1 + int(math.ceil((s.end - s.start) / 90.0)), (s.start, s.end))
            self.assertLessEqual(max(b.frame - a.frame for a, b in zip(keys, keys[1:])), 90)
            cut = {channel: make_camera.CUT_CURVE for channel in vmd.CAMERA_CHANNELS}
            self.assertEqual(vmd.camera_curves(keys[0].interpolation), cut)       # nothing is drawn mid-cut
            for key in keys[1:]:
                curves = vmd.camera_curves(key.interpolation)
                for channel in ("x", "y", "z"):
                    self.assertEqual(curves[channel], vmd.LINEAR_CURVE)          # the look-at point just follows
                self.assertEqual(curves["rotation"], curves["distance"])
                self.assertEqual(curves["fov"], curves["distance"])
        for key in back.cameras:
            self.assertEqual((key.fov, key.perspective), (30, True))
            self.assertLess(key.distance, 0.0)                        # the file holds the negative distance

    def test_the_distance_and_the_angles_ease_over_the_whole_shot(self):
        # the pieces on the keys of a shot, played one after the other, are the S curve of the whole shot:
        # the move starts slowly on the cut, is fastest in the middle and settles before the next cut
        shots = make_camera.plan_shots(synthetic_dance(), seed=1)
        back = read_back(shots)
        checked = 0
        for s, keys in zip(shots, keys_by_shot(shots, back)):
            length = float(s.end - s.start)
            for before, after in zip(keys, keys[1:]):
                piece = vmd.camera_curves(after.interpolation)["distance"]
                for frame in range(before.frame, after.frame + 1, 7):
                    inside = (frame - before.frame) / float(after.frame - before.frame)
                    got = -(before.distance + (after.distance - before.distance) * bezier_y_at(piece, inside))
                    whole = bezier_y_at(make_camera.S_CURVE, (frame - s.start) / length)
                    want = s.distance[0] + (s.distance[1] - s.distance[0]) * whole
                    self.assertLess(abs(got - want), 0.05, (s.start, s.end, frame, got, want))
                    checked += 1
            if s.kind == "orbit":
                middle = keys[len(keys) // 2]
                y = motion_edit.camera_to_ui(middle)["rot"][1]
                self.assertLess(abs(y), abs(s.rot[0][1]))                       # the swing is under way
        self.assertGreater(checked, 100)

    def test_the_keys_carry_the_shot_values_as_the_window_shows_them(self):
        shots = make_camera.plan_shots(synthetic_dance(), seed=0)
        back = read_back(shots)
        for shot, keys in zip(shots, keys_by_shot(shots, back)):
            for key, which in ((keys[0], 0), (keys[-1], 1)):
                ui = motion_edit.camera_to_ui(key)
                self.assertEqual(ui["distance"], shot.distance[which])
                self.assertEqual(ui["pos"], [round(v, 4) for v in shot.pos[which]])
                self.assertEqual(ui["rot"], list(shot.rot[which]))
            for key, (frame, pos) in zip(keys, shot.track):
                ui = motion_edit.camera_to_ui(key)
                self.assertEqual(key.frame, frame)
                self.assertEqual(ui["pos"], [round(v, 4) for v in pos])
                self.assertTrue(min(shot.distance) <= ui["distance"] <= max(shot.distance), ui)
                self.assertEqual(ui["rot"][0], shot.rot[0][0])
                self.assertEqual(ui["rot"][2], 0.0)
        above = [s for s in shots if s.kind == "above"]
        self.assertTrue(above)
        key = keys_by_shot(shots, back)[above[0].index][0]
        self.assertAlmostEqual(key.rotation[0], math.radians(-10.0), places=6)     # the window's +10 is -10 in the file
        self.assertEqual(key.position[1], 12.0)

    def test_the_same_input_and_seed_give_the_same_bytes(self):
        a = vmd.dumps(make_camera.camera_motion(make_camera.plan_shots(synthetic_dance(), seed=3)))
        b = vmd.dumps(make_camera.camera_motion(make_camera.plan_shots(synthetic_dance(), seed=3)))
        self.assertEqual(a, b)
        kinds = {seed: [s.kind for s in make_camera.plan_shots(synthetic_dance(), seed=seed)] for seed in range(6)}
        self.assertGreater(len({tuple(k) for k in kinds.values()}), 1)        # the seed does choose



class HandheldTest(unittest.TestCase):
    """a camera held by a person drifts a little: --handheld adds a slow sway, well under a degree"""

    def setUp(self):
        self.shots = make_camera.plan_shots(synthetic_dance(), seed=0)

    def base(self):
        """the window values on the frames where the plain camera has keys"""
        return {k.frame: motion_edit.camera_to_ui(k) for k in read_back(self.shots).cameras}

    def test_no_handheld_leaves_the_camera_as_it_was(self):
        plain = vmd.dumps(make_camera.camera_motion(self.shots))
        self.assertEqual(vmd.dumps(make_camera.camera_motion(self.shots, handheld=0.0, seed=4)), plain)

    def test_a_key_on_every_frame_and_a_step_on_every_cut(self):
        keys = make_camera.camera_motion(self.shots, handheld=1.0, seed=0).cameras
        self.assertEqual([k.frame for k in keys], list(range(0, LAST + 1)))
        starts = {s.start for s in self.shots}
        step = {c: make_camera.CUT_CURVE for c in vmd.CAMERA_CHANNELS}
        linear = {c: vmd.LINEAR_CURVE for c in vmd.CAMERA_CHANNELS}
        for k in keys:
            self.assertEqual(vmd.camera_curves(k.interpolation), step if k.frame in starts else linear, k.frame)

    def test_the_sway_stays_small(self):
        base = self.base()
        keys = {k.frame: motion_edit.camera_to_ui(k) for k in make_camera.camera_motion(self.shots, handheld=1.0, seed=0).cameras}
        amp = make_camera.HANDHELD
        biggest = {"angle": 0.0, "look_at": 0.0, "distance": 0.0}
        for frame, want in base.items():
            got = keys[frame]
            angle = max(abs(got["rot"][i] - want["rot"][i]) for i in (0, 1))
            look = max(abs(got["pos"][i] - want["pos"][i]) for i in (0, 1))
            dist = abs(got["distance"] - want["distance"])
            self.assertLessEqual(angle, amp["angle"] + 0.01, frame)
            self.assertLessEqual(look, amp["look_at"] + 0.001, frame)
            self.assertLessEqual(dist, amp["distance"] + 0.001, frame)
            self.assertEqual(got["rot"][2], want["rot"][2])                       # no roll
            biggest = {"angle": max(biggest["angle"], angle), "look_at": max(biggest["look_at"], look),
                       "distance": max(biggest["distance"], dist)}
        for name, value in biggest.items():
            self.assertGreater(value, 0.3 * amp[name], name)                      # it does sway
        half = {k.frame: motion_edit.camera_to_ui(k) for k in make_camera.camera_motion(self.shots, handheld=0.5, seed=0).cameras}
        for frame, want in base.items():
            self.assertLessEqual(abs(half[frame]["rot"][1] - want["rot"][1]), 0.5 * amp["angle"] + 0.01)

    def test_the_sway_is_slow_and_smooth(self):
        # no shake: the sway is a sum of slow sines (under SWAY_MAX_HZ), so its second difference per frame is
        # bounded by amplitude * (2 pi f / fps)^2
        for channel in range(5):
            values = [make_camera.sway(channel, f, seed=0) for f in range(0, 600)]
            self.assertLessEqual(max(abs(v) for v in values), 1.0 + 1e-9)
            bound = (2 * math.pi * make_camera.SWAY_MAX_HZ / make_camera.FPS) ** 2
            second = max(abs(a - 2 * b + c) for a, b, c in zip(values, values[1:], values[2:]))
            self.assertLessEqual(second, bound * 1.01)
            self.assertGreater(max(values) - min(values), 0.8)                     # the whole range is used
        self.assertLess(make_camera.SWAY_MAX_HZ, 1.0)

    def test_the_same_seed_sways_the_same_way(self):
        a = vmd.dumps(make_camera.camera_motion(self.shots, handheld=1.0, seed=2))
        self.assertEqual(a, vmd.dumps(make_camera.camera_motion(self.shots, handheld=1.0, seed=2)))
        self.assertNotEqual(a, vmd.dumps(make_camera.camera_motion(self.shots, handheld=1.0, seed=3)))

    def test_a_negative_strength_is_an_error(self):
        with self.assertRaises(ValueError):
            make_camera.camera_motion(self.shots, handheld=-0.5)

def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = make_camera.main(argv)
    text = out.getvalue()
    text.encode("ascii")                                                      # the terminal is cp932: ASCII only
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dance = os.path.join(self.folder, "dance.vmd")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(synthetic_dance()))
        self.out = os.path.join(self.folder, "sub", "camera.vmd")

    def test_writes_the_camera_the_report_and_the_analysis(self):
        report, analysis = os.path.join(self.folder, "r.json"), os.path.join(self.folder, "a.json")
        code, result = run([self.dance, self.out, "--report", report, "--analysis", analysis, "--seed", "2"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual((result["in"], result["out"]), (os.path.abspath(self.dance), os.path.abspath(self.out)))
        self.assertEqual((result["report"], result["analysis"]), (os.path.abspath(report), os.path.abspath(analysis)))
        back = vmd.load(self.out)
        self.assertTrue(back.is_camera)
        self.assertEqual(result["keys"], len(back.cameras))
        self.assertGreater(result["keys"], result["shots"] * 2)
        self.assertEqual(result["frames"], [0, LAST])
        self.assertEqual(result["key_frames"], [0, LAST])
        self.assertEqual((result["seed"], result["min_shot"], result["max_shot"]), (2, 180, 480))
        self.assertEqual(sum(result["kinds"].values()), result["shots"])
        with open(report, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual((r["in"], r["out"], r["seed"]), (result["in"], result["out"], 2))
        self.assertEqual(len(r["shots"]), result["shots"])
        shot = r["shots"][0]
        self.assertEqual(sorted(shot), ["cut", "distance", "end", "frames", "height", "index", "intensity", "keys", "kind",
                                        "level", "picture", "pos", "rot", "seconds", "start"])
        self.assertEqual((shot["start"], shot["index"]), (0, 0))
        self.assertEqual(shot["frames"], shot["end"] - shot["start"] + 1)
        self.assertEqual(shot["seconds"], round(shot["frames"] / 30.0, 2))
        self.assertEqual(sum(s["keys"] for s in r["shots"]), result["keys"])
        for s in r["shots"]:
            # the heights the picture covers at the dancer, at the start and at the end of the shot
            self.assertEqual([len(p) for p in s["picture"]], [2, 2])
            for bottom, top in s["picture"]:
                self.assertLess(bottom, 5.0)
                self.assertGreater(top, 21.0)
        self.assertEqual((r["cut_curve"], r["look_at_step"]), ([127, 0, 127, 0], 90))
        self.assertEqual(sorted(r["thresholds"]), ["high", "low"])
        self.assertEqual(r["kinds"], result["kinds"])
        with open(analysis, encoding="utf-8") as f:
            a = json.load(f)
        self.assertEqual(len(a["intensity"]), LAST + 1)
        self.assertEqual(a["in"], result["in"])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["camera.vmd"])

    def test_the_output_is_deterministic_and_replaces_an_old_file(self):
        os.makedirs(os.path.dirname(self.out))
        with open(self.out, "wb") as f:
            f.write(b"not a vmd")
        code, _ = run([self.dance, self.out, "--seed", "5"])
        self.assertEqual(code, 0)
        with open(self.out, "rb") as f:
            first = f.read()
        code, _ = run([self.dance, self.out, "--seed", "5"])
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), first)
        self.assertEqual(os.listdir(os.path.dirname(self.out)), ["camera.vmd"])
        self.assertTrue(vmd.loads(first).is_camera)

    def test_errors_exit_2_before_anything_is_written(self):
        for argv in ([self.dance, self.out, "--min-shot", "300", "--max-shot", "400"],
                     [os.path.join(self.folder, "none.vmd"), self.out],
                     [self.dance, self.out, "--min-shot", "1", "--max-shot", "10"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertIn("message", result["error"])
            self.assertFalse(os.path.exists(self.out), argv)
        camera = os.path.join(self.folder, "camera_in.vmd")
        with open(camera, "wb") as f:
            f.write(vmd.dumps(vmd.Motion.for_camera(cameras=[vmd.CameraKey(0, -45.0, (0, 10, 0), (0, 0, 0))])))
        code, result = run([camera, self.out])
        self.assertEqual(code, 2)
        self.assertIn("bone", result["error"]["message"])
        self.assertFalse(os.path.exists(self.out))

    def test_handheld_reaches_the_camera(self):
        code, result = run([self.dance, self.out, "--handheld", "1"])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["keys"], result["handheld"]), (LAST + 1, 1.0))
        code, result = run([self.dance, self.out, "--handheld", "-1"])
        self.assertEqual(code, 2)

    def test_other_limits_reach_the_plan(self):
        code, result = run([self.dance, self.out, "--min-shot", "90", "--max-shot", "200"])
        self.assertEqual(code, 0)
        self.assertEqual((result["min_shot"], result["max_shot"]), (90, 200))
        self.assertGreaterEqual(result["shots"], 8)

    def test_dance_and_out_must_differ(self):
        # writing the camera over the dance (or a JSON over either) would lose the dance for good
        with open(self.dance, "rb") as f:
            original = f.read()
        same = os.path.join(self.folder, "DANCE.VMD") if os.path.normcase("A") == os.path.normcase("a") else self.dance
        for argv in ([self.dance, same], [self.dance, self.out, "--report", same], [self.dance, self.out, "--analysis", same],
                     [self.dance, self.out, "--report", self.out], [self.dance, self.out, "--report", self.out + ".json",
                                                                     "--analysis", self.out + ".json"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertIn("same file", result["error"]["message"])
            self.assertFalse(os.path.exists(self.out), argv)
        with open(self.dance, "rb") as f:
            self.assertEqual(f.read(), original)


def real_dance():
    """the distributed dance (the sleeve-less variant used in the scene), kept outside the repository in
    _spike/ of this checkout or of the checkout this worktree hangs under; None when it is not there"""
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
    def test_the_whole_dance_is_covered_by_20_to_60_shots(self):
        motion = vmd.load(REAL)
        analysis = make_camera.analyze(motion)
        self.assertEqual(analysis.last, 7742)
        self.assertGreater(len(analysis.sections), 2)
        shots = make_camera.plan_shots(motion, analysis=analysis)
        self.assertTrue(20 <= len(shots) <= 60, len(shots))
        self.assertEqual((shots[0].start, shots[-1].end), (0, 7742))
        for before, after in zip(shots, shots[1:]):
            self.assertEqual(after.start, before.end + 1)
            self.assertNotEqual(before.kind, after.kind)
        for s in shots:
            self.assertTrue(make_camera.MIN_SHOT <= length(s) <= make_camera.MAX_SHOT, (s.start, s.end))
            for d in s.distance:
                self.assertTrue(make_camera.DISTANCE_RANGE[0] <= d <= make_camera.DISTANCE_RANGE[1])
        self.assertEqual({s.level for s in shots} - {"peak", "valley", "mid"}, set())
        self.assertIn("peak", {s.level for s in shots})
        back = read_back(shots)
        frames = [k.frame for k in back.cameras]
        self.assertEqual((frames[0], frames[-1]), (0, 7742))
        self.assertEqual(len(frames), sum(len(s.track) for s in shots))
        self.assertGreater(len(frames), 2 * len(shots))
        self.assertTrue(all(b > a for a, b in zip(frames, frames[1:])))
        self.assertLessEqual(max(b - a for a, b in zip(frames, frames[1:])), 90)
        self.assertEqual(vmd.dumps(back), vmd.dumps(read_back(make_camera.plan_shots(motion, analysis=analysis))))


class AnalysisJsonTest(unittest.TestCase):
    def test_the_json_is_plain_data_with_the_definitions(self):
        analysis = make_camera.analyze(synthetic_dance())
        text = json.dumps(make_camera.analysis_json(analysis), ensure_ascii=True)
        data = json.loads(text)
        self.assertEqual(data["frames"], [0, LAST])
        self.assertEqual((data["window"], data["trend_window"]), (make_camera.WINDOW, make_camera.TREND_WINDOW))
        self.assertEqual(len(data["intensity"]), LAST + 1)
        self.assertEqual(len(data["trend"]), LAST + 1)
        self.assertEqual(sorted(data["thresholds"]), ["high", "low"])
        self.assertEqual(data["sections"][0]["start"], 0)
        self.assertIn(data["sections"][0]["level"], ("high", "low"))
        self.assertEqual([b["frame"] for b in data["boundaries"]], [s["start"] for s in data["sections"][1:]])
        self.assertIn("rotation", data["weights"])
        self.assertIn("position", data["weights"])



# ---- --song: the camera cut and moved on the song ----------------------------------------------------------------------

BEAT = 0.5                    # s: 120 BPM, 15 frames a beat, 60 a bar
LEAD = 0.077                  # s: the references cut 2.3 frames before the beat (song_structure's cut_lead)
SECTIONS = [("intro", 0), ("verse1", 4), ("chorus1", 12), ("break", 20), ("end", 24)]     # (id, first bar)
HOOK = 17 * 4 + 2             # a title word on the third beat of bar 17 (in the chorus)


def synthetic_song():
    beats = [BEAT * k for k in range(25 * 4 + 1)]
    bars = beats[::4]
    sections = [{"id": sid, "beat": bar * 4, "t": bars[bar], "frame": int(round(bars[bar] * 30))} for sid, bar in SECTIONS]
    return {"fps": 30, "beats": beats, "bars": bars, "sections": sections, "cut_lead": LEAD,
            "hooks": [{"n": 1, "beat": HOOK, "t": beats[HOOK], "frame": int(round(beats[HOOK] * 30))}]}


# a strong onset on the second beat of the verse's first bar, a weak one in the chorus, a strong one in the break
ONSETS = [{"t": BEAT * (4 * 4 + 1), "z": 6.0}, {"t": BEAT * (12 * 4 + 1), "z": 2.5}, {"t": BEAT * (21 * 4), "z": 7.0}]


def frames_of_bar(bar):
    return int(round((BEAT * 4 * bar - LEAD) * 30))


class MusicTest(unittest.TestCase):
    """make_camera --song: the cuts on the song's bars a little before the beat, the shots by the part of the song (long
    in the quiet parts, short in the chorus), every shot moving in whole beats (a dolly, an orbit, a crane, a track)
    from its cut or from a strong onset, still only where the song stops (the break, the end), the dancer framed from
    the knees to above the head, no push in over a title word"""

    def setUp(self):
        self.song = synthetic_song()
        self.shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0)

    def section_of(self, shot):
        return shot.section.rstrip("0123456789")

    def test_cuts_fall_on_the_bars_a_little_before_the_beat(self):
        shots = self.shots
        self.assertEqual((shots[0].start, shots[-1].end), (0, LAST))
        heads = {frames_of_bar(b) for b in range(1, 25)}
        for before, after in zip(shots, shots[1:]):
            self.assertEqual(after.start, before.end + 1)
            self.assertIn(after.start, heads, after.start)

    def test_the_chorus_cuts_often_and_the_quiet_parts_hold(self):
        bars = {}
        for s in self.shots:
            bars.setdefault(self.section_of(s), []).append(s.bars)
        self.assertEqual(bars["verse"], [4, 4])
        self.assertEqual(bars["chorus"], [2, 2, 1, 1, 2])
        self.assertEqual(bars["break"], [4])
        self.assertEqual(len(bars["end"]), 1)
        per_bar = {k: len(v) / float(sum(v)) for k, v in bars.items()}
        self.assertGreater(per_bar["chorus"], 2 * per_bar["verse"])

    def test_every_shot_moves_in_whole_beats_from_its_cut_or_a_strong_onset(self):
        beat_frames = BEAT * 30
        for s in self.shots:
            kind = self.section_of(s)
            if kind in ("break", "end"):
                self.assertEqual(s.moves, [], (s.start, kind))
                continue
            self.assertTrue(s.moves, (s.start, kind))
            first = s.moves[0]
            onset = [round(o["t"] * 30) for o in ONSETS if o["z"] >= 4.0 and s.start < round(o["t"] * 30) < s.start + 60]
            self.assertIn(first.start, [s.start] + onset, (s.start, kind))
            for m in s.moves:
                self.assertIn(m.name, make_camera.MUSIC_MOVES, m.name)
                whole = m.frames / beat_frames
                self.assertAlmostEqual(whole, round(whole), delta=0.07, msg=(s.start, m.name, m.frames))
                self.assertIn(int(round(whole)), (4, 8), (s.start, m.name))
                # a move ends at the latest on the first beat after its shot (the cut leads that beat by LEAD: the last
                # frames of the move are hidden by the cut, MOVE_OVERRUN at most), but for the shot's last move when it
                # starts MOVE_TAIL beats or more before the shot's end (the next cut cuts into it)
                if m is s.moves[-1] and m.start + m.frames > s.end + make_camera.MOVE_OVERRUN:
                    self.assertLessEqual(m.start, s.end + 1 - make_camera.MOVE_TAIL * beat_frames, (s.start, m.name))
                    continue
                beat_after = math.ceil((s.end + 1) / beat_frames - 1e-9) * beat_frames
                self.assertLessEqual(m.start + m.frames, beat_after, (s.start, m.name))
                self.assertLessEqual(m.start + m.frames, s.end + make_camera.MOVE_OVERRUN, (s.start, m.name))
        # the strong onset of the verse's first bar starts that shot's move; the weak one in the chorus does not
        verse = [s for s in self.shots if self.section_of(s) == "verse"][0]
        self.assertEqual(verse.moves[0].start, round(ONSETS[0]["t"] * 30))
        self.assertEqual(verse.moves[0].shape, "hit")
        chorus = [s for s in self.shots if self.section_of(s) == "chorus"][0]
        self.assertEqual(chorus.moves[0].start, chorus.start)

    def test_most_of_the_song_moves_and_the_break_holds_still(self):
        values = make_camera.music_values(self.shots, LAST)
        moving = 0
        counted = 0
        for s in self.shots:
            kind = self.section_of(s)
            for f in range(s.start + 1, s.end + 1):
                a, b = values[f - 1], values[f]
                changed = (abs(a["distance"] - b["distance"]) > 1e-6 or abs(a["rot"][0] - b["rot"][0]) > 1e-6 or
                           abs(a["rot"][1] - b["rot"][1]) > 1e-6 or math.dist(a["offset"], b["offset"]) > 1e-6)
                if kind in ("break", "end"):
                    self.assertFalse(changed, f)
                else:
                    counted += 1
                    moving += changed
        self.assertGreater(moving / float(counted), 0.6)

    def test_the_dancer_stays_framed_and_the_camera_above_her_hips(self):
        values = make_camera.music_values(self.shots, LAST)
        for f, v in enumerate(values):
            bottom, top = make_camera.picture_span(v["distance"], v["pos"][1], v["rot"][0])
            self.assertLess(bottom, 5.0, f)
            self.assertGreater(top, 21.0, f)
            up = math.radians(-v["rot"][0])
            self.assertGreater(v["pos"][1] - v["distance"] * math.sin(up), 12.0, f)          # the eye's height

    def test_a_cut_changes_the_picture_clearly(self):
        values = make_camera.music_values(self.shots, LAST)
        for before, after in zip(self.shots, self.shots[1:]):
            a, b = values[before.end], values[after.start]
            self.assertTrue(make_camera.changes_clearly((a["distance"], a["pos"][1], a["rot"]),
                                                        (b["distance"], b["pos"][1], b["rot"])), after.start)

    def test_no_push_in_over_a_title_word(self):
        hook = self.song["hooks"][0]["frame"]
        for s in self.shots:
            for m in s.moves:
                if m.name == "dolly_in":
                    self.assertFalse(m.start - make_camera.HOOK_REACH <= hook <= m.start + m.frames + make_camera.HOOK_REACH,
                                     (m.start, m.frames))

    def test_the_keys_follow_the_values_with_a_step_on_every_cut(self):
        motion = make_camera.music_motion(self.shots, LAST, handheld=0.0, seed=0)
        keys = motion.cameras
        self.assertEqual([k.frame for k in keys], list(range(0, LAST + 1)))
        starts = {s.start for s in self.shots}
        step = {c: make_camera.CUT_CURVE for c in vmd.CAMERA_CHANNELS}
        values = make_camera.music_values(self.shots, LAST)
        for k in keys:
            self.assertEqual(vmd.camera_curves(k.interpolation) == step, k.frame in starts, k.frame)
            ui = motion_edit.camera_to_ui(k)
            self.assertAlmostEqual(ui["distance"], values[k.frame]["distance"], places=3)
            self.assertAlmostEqual(ui["rot"][1], values[k.frame]["rot"][1], places=3)

    def test_a_drive_comes_up_to_pace_in_a_beat_holds_it_and_comes_to_rest(self):
        r = 0.125                                   # a beat of an 8-beat move
        values = [make_camera._shape("drive", i / 800.0, r) for i in range(801)]
        self.assertAlmostEqual(values[0], 0.0, places=9)
        self.assertAlmostEqual(values[-1], 1.0, places=9)
        steps = [b - a for a, b in zip(values, values[1:])]
        self.assertTrue(all(d >= -1e-12 for d in steps))
        even = steps[int(800 * r) + 2:int(800 * (1 - r)) - 2]
        self.assertLess(max(even) - min(even), 1e-9)                       # an even pace between the ramps
        self.assertLess(steps[0], 0.05 * even[0])                          # it starts and ends at rest
        self.assertLess(steps[-1], 0.05 * even[0])

    def test_the_quiet_parts_are_shot_wider_with_her_feet_in(self):
        values = make_camera.music_values(self.shots, LAST)
        for s in self.shots:
            if self.section_of(s) in ("verse", "break"):
                self.assertGreaterEqual(s.base["distance"], 40.0, s.start)
        feet = [f for s in self.shots if self.section_of(s) in ("verse", "break") for f in range(s.start, s.end + 1)
                if make_camera.picture_span(values[f]["distance"], values[f]["pos"][1], values[f]["rot"][0])[0] < 0.1]
        self.assertTrue(feet)

    def test_a_crane_down_is_not_drawn_where_the_guard_raises_the_camera(self):
        # the plain plan draws a crane down somewhere; the guard of a first pass tilts the camera up over those frames (15
        # degrees): the second pass draws no crane down where the guard rises (it would turn the move into a rise)
        downs = [m for s in self.shots for m in s.moves if m.name == "crane_down"]
        self.assertTrue(downs)
        tilt = [0.0] * (LAST + 1)
        for m in downs:
            for f in range(m.start, min(LAST + 1, m.start + m.frames + 1)):
                tilt[f] = 15.0 * (f - m.start) / float(m.frames)
        shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0, rising=tilt)
        for m in (m for s in shots for m in s.moves if m.name == "crane_down"):
            span = tilt[m.start:min(LAST + 1, m.start + m.frames + 1)]
            self.assertLessEqual(max(span) - span[0], make_camera.GUARD_RISE_LEAST, (m.start, m.frames))

    def test_a_crane_up_is_not_drawn_where_the_guard_lowers_the_camera(self):
        # the guard of a first pass swings the camera up over the first half of each crane up of the plain plan and back
        # down over the second (a window of the guard: the music camera's 5th build ran a crane up against it for 42
        # frames at 212.5 s): the second pass draws no crane up where the guard's tilt falls from its height
        ups = [m for s in self.shots for m in s.moves if m.name == "crane_up"]
        self.assertTrue(ups)
        tilt = [0.0] * (LAST + 1)
        for m in ups:
            for f in range(m.start, min(LAST + 1, m.start + m.frames + 1)):
                tilt[f] = 15.0 * math.sin(math.pi * (f - m.start) / float(m.frames))
        shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0, rising=tilt)
        for m in (m for s in shots for m in s.moves if m.name == "crane_up"):
            span = tilt[m.start:min(LAST + 1, m.start + m.frames + 1)]
            fall = max(max(span[:i + 1]) - span[i] for i in range(len(span)))
            self.assertLessEqual(fall, make_camera.GUARD_RISE_LEAST, (m.start, m.frames))

    def test_the_shot_of_a_contact_stands_where_her_face_looks(self):
        # she turns her upper body 30 degrees about Y round the wanted contact (a key turning +Y swings her face to -X,
        # her right: mmd_cli/fk.py's convention); the camera of the shot that holds it stands on her face's way, at the
        # window's Y of -30 (Y positive swings the camera to +X), not in front of the stage
        t = 10.5
        c = int(round(t * 30))
        dance = synthetic_dance()
        dance.bones += [bone("上半身", 0), bone("上半身", c - 60, rot=(0, 30, 0)), bone("上半身", c + 90, rot=(0, 30, 0)),
                        bone("上半身", c + 150)]
        self.assertAlmostEqual(make_camera.facing_at(make_camera.facing_chain(dance), c), -30.0, delta=3.5)
        shots = make_camera.plan_music_shots(dance, self.song, ONSETS, seed=0, contacts=[t])
        shot = [s for s in shots if s.start <= c <= s.end][0]
        self.assertTrue(shot.contact)
        self.assertAlmostEqual(shot.base["yaw"], -30.0, delta=4.0)
        self.assertTrue(all(m.name in ("dolly_in", "dolly_out") for m in shot.moves))

    def test_a_cut_falls_on_each_light_flash(self):
        # the MV's light flashes (--cut-on): one 2 frames after a planned cut (the cut moves onto it), one on the head of bar
        # 10 inside the verse's second shot (a cut is added there); the other cuts stay, and both halves of the split shot
        # still move in whole beats from their cuts
        moved, added = frames_of_bar(14) + 2, int(round(BEAT * 4 * 10 * 30))
        shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0, cut_on=[added, moved])
        plain = [s.start for s in self.shots]
        want = sorted([c for c in plain if c != frames_of_bar(14)] + [moved, added])
        self.assertEqual([s.start for s in shots], want)
        for s in shots:
            self.assertGreaterEqual(s.end, s.start)
        # the command takes them as --cut-on and --punch and reports them
        folder = tempfile.mkdtemp()
        dance, song, out, report = (os.path.join(folder, n) for n in ("dance.vmd", "song.json", "cam.vmd", "r.json"))
        with open(dance, "wb") as f:
            f.write(vmd.dumps(synthetic_dance()))
        with open(song, "w", encoding="utf-8") as f:
            json.dump(synthetic_song(), f)
        code, result = run([dance, out, "--song", song, "--cut-on", str(added), str(moved), "--punch", "700", "--report", report])
        self.assertEqual(code, 0, result)
        with open(report, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["cut_on"], sorted([added, moved]))
        self.assertEqual(r["punches"], [700])
        self.assertEqual([s["start"] for s in r["shots"]], want)
        # the shot after the moved cut is 2 frames short of its 2 bars and still moves over all of them (an 8-beat move; the
        # cut hides its last frames), as it did before the cut moved
        after_move = [s for s in shots if s.start == moved][0]
        plain_after = [s for s in self.shots if s.start == frames_of_bar(14)][0]
        self.assertEqual([m.frames for m in after_move.moves], [m.frames for m in plain_after.moves])
        split = [s for s in shots if s.start == added][0]
        before = [s for s in shots if s.end == added - 1][0]
        for s in (before, split):
            self.assertEqual(self.section_of(s), "verse")
            self.assertTrue(s.moves)
            self.assertEqual(s.moves[0].start, s.start)
            for m in s.moves:
                self.assertIn(m.frames, (60, 120))
                self.assertLessEqual(m.start + m.frames, s.end + make_camera.MOVE_OVERRUN)

    def test_a_shot_does_not_stand_still_for_beats_after_its_last_move(self):
        # the verse's first shot starts its move on the strong onset of its second beat: 8 beats, then 4, and then 3.1
        # beats are left; a 4-beat move runs into the next cut there (the camera still moves at the cut) instead of standing
        # still; no shot of the song stands still MOVE_TAIL beats or more after its last move
        beat = BEAT * 30
        for s in self.shots:
            if self.section_of(s) in ("break", "end"):
                continue
            last = s.moves[-1]
            left = (s.end + 1 - (last.start + last.frames)) / beat
            self.assertLess(left, make_camera.MOVE_TAIL, (s.start, [(m.start, m.frames) for m in s.moves]))
        verse = [s for s in self.shots if self.section_of(s) == "verse"][0]
        self.assertEqual([m.frames for m in verse.moves], [120, 60, 60])
        self.assertGreater(verse.moves[-1].start + verse.moves[-1].frames, verse.end + make_camera.MOVE_OVERRUN)
        self.assertLessEqual(verse.moves[-1].start, verse.end + 1 - make_camera.MOVE_TAIL * beat)

    def test_a_shot_a_few_frames_short_of_its_bars_still_moves_over_all_of_them(self):
        # the first shot of the intro starts on frame 0 and ends 2 frames before bar 4 (the next cut leads the beat): 238
        # frames, 2 short of 16 beats; it moves over all of them in 8-beat moves (no 4 beats of standing still at its end)
        shot = self.shots[0]
        frames = shot.end - shot.start + 1
        self.assertEqual(frames, frames_of_bar(4))
        self.assertEqual([m.frames for m in shot.moves], [120, 120])
        self.assertGreaterEqual(sum(m.frames for m in shot.moves), frames - make_camera.MOVE_OVERRUN)

    def test_no_push_in_over_a_punch_of_the_motion_graphics(self):
        # a punch of the motion graphics (--punch) where the plain plan pushes in: the plan with it puts no dolly in there
        # (the punch is the zoom; a push under it doubles it)
        pushes = [m for s in self.shots for m in s.moves if m.name == "dolly_in"]
        self.assertTrue(pushes)
        punch = pushes[0].start + 5
        shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0, punches=[punch])
        for m in (m for s in shots for m in s.moves if m.name == "dolly_in"):
            self.assertFalse(m.start - make_camera.HOOK_REACH <= punch <= m.start + m.frames + make_camera.HOOK_REACH,
                             (m.start, m.frames, punch))

    def test_the_way_of_a_contact_is_where_her_face_holds_still_nearest_the_wanted_time(self):
        # her upper body faces the front up to frame 100, turns to Y +40 (her face to -X, Y -40) by frame 200 and holds
        # there to 400: wanted at 50 the camera takes the front, wanted at 300 the way she holds after the turn, and the
        # frames are the ones she holds it over (within FACING_HOLD either side), not the turn
        dance = vmd.Motion(model_name="synthetic", bones=[bone("上半身", 0), bone("上半身", 100), bone("上半身", 200, rot=(0, 40, 0)),
                                                          bone("上半身", 400, rot=(0, 40, 0))])
        chain = make_camera.facing_chain(dance)
        a, b, way = make_camera.steady_facing(chain, 0, 400, [50])
        self.assertEqual(a, 0)
        self.assertGreaterEqual(b, 100)
        self.assertLess(b, 200)
        self.assertAlmostEqual(way, 0.0, delta=4.0)
        a, b, way = make_camera.steady_facing(chain, 0, 400, [300])
        self.assertGreater(a, 100)
        self.assertEqual(b, 400)
        self.assertAlmostEqual(way, -40.0, delta=4.0)
        for f in range(a, b + 1):
            self.assertLessEqual(abs(make_camera.facing_at(chain, f) - way), 2 * make_camera.FACING_HOLD)
        # the spine bones of the MV's model are in the chain, in its order (腰椎上部 under 上半身2, 胸椎上部 under 首)
        bones = make_camera.FACING_BONES
        self.assertLess(bones.index("上半身"), bones.index("腰椎上部"))
        self.assertLess(bones.index("腰椎上部"), bones.index("上半身2"))
        self.assertLess(bones.index("上半身2"), bones.index("胸椎上部"))
        self.assertLess(bones.index("胸椎上部"), bones.index("首"))

    def test_a_shot_round_an_eye_contact_holds_the_camera_before_her_face(self):
        # an eye contact wanted at 10.5 s (in the verse): the shot holding it looks at her from the front, level with
        # her eyes (window X at most 5, Y within 12 degrees), and only dollies; round the contact the camera hardly turns,
        # so the gaze tool can hold her eyes on it (eye_gaze: within reach for 1.6 s, a turn of the head's range)
        t = 10.5
        shots = make_camera.plan_music_shots(synthetic_dance(), self.song, ONSETS, seed=0, contacts=[t])
        values = make_camera.music_values(shots, LAST)
        c = int(round(t * 30))
        shot = [s for s in shots if s.start <= c <= s.end][0]
        self.assertLessEqual(shot.base["pitch"], 5.0)
        self.assertLessEqual(abs(shot.base["yaw"]), 12.0)
        self.assertTrue(all(m.name in ("dolly_in", "dolly_out") for m in shot.moves), [m.name for m in shot.moves])
        near = values[max(shot.start, c - 30):min(shot.end, c + 60) + 1]
        self.assertLess(max(v["rot"][1] for v in near) - min(v["rot"][1] for v in near), 2.0)
        self.assertLess(max(v["rot"][0] for v in near) - min(v["rot"][0] for v in near), 2.0)
        # (without the contact the same shot is drawn otherwise: the test is not empty)
        plain = [s for s in self.shots if s.start <= c <= s.end][0]
        self.assertTrue(plain.base["pitch"] > 5.0 or abs(plain.base["yaw"]) > 12.0 or
                        any(m.name not in ("dolly_in", "dolly_out") for m in plain.moves))
        # the picture still holds her from below the knees to above the head, from above her waist
        for v in values[shot.start:shot.end + 1]:
            bottom, top = make_camera.picture_span(v["distance"], make_camera.MUSIC_HEIGHT, v["pitch"])
            self.assertLess(bottom, 5.0)
            self.assertGreater(top, 21.0)
            self.assertGreater(make_camera.MUSIC_HEIGHT + v["distance"] * math.sin(math.radians(v["pitch"])), 12.0)
        # the cuts stay where they were
        self.assertEqual([s.start for s in shots], [s.start for s in self.shots])

    def test_the_contacts_come_from_a_list_of_seconds_or_from_the_gaze_report_and_go_to_a_long_shot(self):
        folder = tempfile.mkdtemp()
        dance, song = os.path.join(folder, "dance.vmd"), os.path.join(folder, "song.json")
        with open(dance, "wb") as f:
            f.write(vmd.dumps(synthetic_dance()))
        with open(song, "w", encoding="utf-8") as f:
            json.dump(synthetic_song(), f)
        seconds, report = os.path.join(folder, "seconds.json"), os.path.join(folder, "gaze.json")
        with open(seconds, "w", encoding="utf-8") as f:
            json.dump([10.5], f)
        with open(report, "w", encoding="utf-8") as f:     # eye_gaze's report: the contact from 300 to 330 (10.5 s in the middle)
            json.dump({"contacts": {"count": 1, "list": [{"first": 300, "last": 330, "seconds": 1.033, "anchor": None}]}}, f)
        self.assertEqual(make_camera.load_contacts(seconds), [10.5])
        self.assertEqual(make_camera.load_contacts(report), [10.5])
        outs = []
        for path in (seconds, report):
            out, r = os.path.join(folder, "cam_%d.vmd" % len(outs)), os.path.join(folder, "r_%d.json" % len(outs))
            code, result = run([dance, out, "--song", song, "--contacts", path, "--report", r])
            self.assertEqual(code, 0, result)
            self.assertEqual(result["contact_shots"], 1)
            with open(r, encoding="utf-8") as f:
                shots = json.load(f)["shots"]
            held = [s for s in shots if s["contact"]]
            self.assertEqual(len(held), 1)
            self.assertTrue(held[0]["start"] <= 315 <= held[0]["end"])
            with open(out, "rb") as f:
                outs.append(f.read())
        self.assertEqual(outs[0], outs[1])
        # a wanted time in a shot too short to hold a contact goes to the nearest long one
        spans = [(0, 59), (60, 89), (90, 239)]
        self.assertEqual(make_camera.contact_shots(spans, [70 / 30.0]), {2: [70]})
        self.assertEqual(make_camera.contact_shots(spans, [1.0, 5.0]), {2: [30, 150]})
        self.assertEqual(make_camera.contact_shots(spans, []), {})

    def test_the_same_input_and_seed_give_the_same_bytes_and_the_command_writes_them(self):
        a = vmd.dumps(make_camera.music_motion(self.shots, LAST, handheld=1.0, seed=0))
        again = make_camera.plan_music_shots(synthetic_dance(), synthetic_song(), ONSETS, seed=0)
        self.assertEqual(a, vmd.dumps(make_camera.music_motion(again, LAST, handheld=1.0, seed=0)))
        folder = tempfile.mkdtemp()
        dance, song, onsets = (os.path.join(folder, n) for n in ("dance.vmd", "song.json", "onsets.json"))
        with open(dance, "wb") as f:
            f.write(vmd.dumps(synthetic_dance()))
        with open(song, "w", encoding="utf-8") as f:
            json.dump(synthetic_song(), f)
        with open(onsets, "w", encoding="utf-8") as f:
            json.dump({"onsets": ONSETS}, f)
        out, report = os.path.join(folder, "cam.vmd"), os.path.join(folder, "r.json")
        code, result = run([dance, out, "--song", song, "--onsets", onsets, "--handheld", "1", "--report", report])
        self.assertEqual(code, 0, result)
        # (the dance read back from its file: a VMD keeps float32, so the centre the camera follows is that one)
        read = make_camera.plan_music_shots(vmd.load(dance), synthetic_song(), ONSETS, seed=0)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), vmd.dumps(make_camera.music_motion(read, LAST, handheld=1.0, seed=0)))
        with open(report, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(len(r["shots"]), len(self.shots))
        for key in ("section", "bars", "moves", "start", "end"):
            self.assertIn(key, r["shots"][0])
        self.assertEqual(r["song"]["cut_lead"], LEAD)


# ---- (review camsyncrev 2026-10-21) the cases the tests above let pass: the tools broken one place at a time (139 ways:
# 80 that changed what the tool does were not caught), each case below fails on one of them and passes on the tool as it is
import shutil  # noqa: E402

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx  # noqa: E402

mc = make_camera


def load(name):
    spec = importlib.util.spec_from_file_location("_mc_test_" + name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(folder, name, data):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def quiet(main, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


KEY = {"dolly": "distance", "orbit": "yaw", "crane": "pitch", "track": "track"}


def plan(song=None, onsets=None, seed=0, dance=None, **kw):
    return mc.plan_music_shots(synthetic_dance() if dance is None else dance, synthetic_song() if song is None else song,
                               ONSETS if onsets is None else onsets, seed=seed, **kw)



class MusicPartsTest(unittest.TestCase):
    def test_a_part_that_starts_off_the_bar_lines_starts_its_first_bar_there(self):
        # the verse comes in two beats before bar 4: its bars begin at its head (T2-03)
        song = synthetic_song()
        head = song["bars"][4] - 2 * BEAT
        song["sections"][1] = dict(song["sections"][1], t=head, frame=int(round(head * 30)))
        verse = [p for p in mc.song_parts(song, LAST) if p[0] == "verse1"][0]
        self.assertAlmostEqual(verse[2][0], head)
        self.assertEqual(verse[3], int(round((head - LEAD) * 30)))

    def test_a_song_without_bars_is_cut_on_every_fourth_beat(self):
        song = synthetic_song()
        plain = [s.start for s in plan(song=song)]
        del song["bars"]
        self.assertEqual([s.start for s in plan(song=song)], plain)                       # T2-04

    def test_a_song_without_its_lead_is_cut_with_the_references_lead(self):
        # the synthetic song gives the references' lead (0.077 s, 2.3 frames: typorev); without it the cuts are the same
        # (T2-05)
        song = synthetic_song()
        plain = [s.start for s in plan(song=song)]
        del song["cut_lead"]
        self.assertEqual([s.start for s in plan(song=song)], plain)


class MusicMovesTest(unittest.TestCase):
    def test_a_hit_starts_at_full_pace_and_eases_out(self):
        # the verse's move from its strong onset and the chorus's one-bar shots are hits: fastest on their first frame,
        # slower on every frame after (T2-06, T2-50)
        shots = plan()
        values = mc.music_values(shots, LAST)
        hits = [(s, m) for s in shots for m in s.moves if m.shape == "hit"]
        self.assertTrue(any(s.section.startswith("verse") for s, _ in hits))
        self.assertTrue(any(s.section.startswith("chorus") and s.bars == 1 for s, _ in hits))
        for s, m in hits:
            key = KEY[mc._move_channel(m.name)]
            steps = [abs(values[f + 1][key] - values[f][key]) for f in range(m.start, min(m.start + m.frames, s.end))]
            self.assertEqual(max(steps), steps[0], (s.start, m.name))
            self.assertTrue(all(b <= a + 1e-12 for a, b in zip(steps, steps[1:])), (s.start, m.name))

    def test_a_drive_is_at_its_even_pace_from_one_beat_in(self):
        # up to pace over a beat, even, down over a beat (T2-46: two beats of ramp)
        shots = plan()
        values = mc.music_values(shots, LAST)
        beat = int(round(BEAT * 30))
        checked = 0
        for s in shots:
            for m in s.moves:
                if m.shape != "drive":
                    continue
                key = KEY[mc._move_channel(m.name)]
                step = [values[f + 1][key] - values[f][key] for f in range(m.start, min(m.start + m.frames, s.end))]
                if len(step) < m.frames - beat - 1:
                    continue                                # (a tail move the next cut cuts into before its even part ends)
                middle = step[m.frames // 2]
                for i in range(beat + 1, min(m.frames - beat - 1, len(step))):
                    self.assertAlmostEqual(step[i], middle, delta=1e-9, msg=(s.start, m.name, i))
                self.assertLess(abs(step[beat // 2]), abs(middle))
                checked += 1
        self.assertGreater(checked, 3)

    def test_the_camera_stays_within_its_ranges_on_every_frame(self):
        # distance, pitch, yaw and track within MUSIC_RANGE on every frame, whatever the seed (T2-13, T2-14, T2-15, T2-17)
        for seed in range(8):
            values = mc.music_values(plan(seed=seed), LAST)
            for f, v in enumerate(values):
                for key in ("distance", "pitch", "yaw", "track"):
                    lo, hi = mc.MUSIC_RANGE[key]
                    self.assertTrue(lo - 1e-6 <= v[key] <= hi + 1e-6, (seed, f, key, v[key]))

    def test_every_move_is_at_most_its_full_size(self):
        # a move takes its full size times its part's energy, or less where the range leaves less (T2-13: a dolly out
        # taking all the room up to the far end, more than its full size)
        for seed in range(8):
            for s in plan(seed=seed):
                for m in s.moves:
                    full = mc.MUSIC_FULL[mc._move_channel(m.name)] * mc.MUSIC_ENERGY[s.kind]
                    self.assertLessEqual(abs(m.amount), full + 1e-6, (seed, s.start, m.name, m.amount))

    def test_a_track_of_a_lively_part_stays_within_its_range(self):
        # the band (energy 0.9) tracks 7.2 units at full size, more than the range's 5 either side: the track is held
        # within the range (T2-17)
        song = synthetic_song()
        song["sections"][1] = dict(song["sections"][1], id="band1")
        shots = plan(song=song)
        self.assertTrue(any(m.name == "track" for s in shots if s.kind == "band" for m in s.moves))
        lo, hi = mc.MUSIC_RANGE["track"]
        for f, v in enumerate(mc.music_values(shots, LAST)):
            self.assertTrue(lo - 1e-6 <= v["track"] <= hi + 1e-6, (f, v["track"]))

    def test_an_orbit_with_no_room_on_its_side_swings_the_other_way(self):
        # 5 degrees from the end of the range on the side drawn: the orbit goes the other way, its full size (T2-16)
        for yaw, sign in ((60.0, 1), (-60.0, -1)):
            values = {"distance": 40.0, "pitch": 9.0, "yaw": yaw, "track": 0.0}
            self.assertEqual(mc._room("orbit", values, 1.0, sign), -sign * mc.MUSIC_FULL["orbit"])

    def test_a_track_moves_across_the_line_of_sight(self):
        # the look-at point and the camera go sideways together: the offset is square to where the camera looks (T2-20)
        shots = plan()
        values = mc.music_values(shots, LAST)
        keys = fk.camera_keys(mc.music_motion(shots, LAST))
        frames = [k.frame for k in keys]
        checked = 0
        for s in shots:
            for m in s.moves:
                if m.name != "track":
                    continue
                for f in range(m.start + 1, min(m.start + m.frames, s.end) + 1):
                    ox, oz = values[f]["offset"]
                    if math.hypot(ox, oz) < 0.5:
                        continue
                    d = fk.camera_direction(fk.camera_at(keys, f, frames))
                    cos = (ox * d[0] + oz * d[2]) / (math.hypot(ox, oz) * math.hypot(d[0], d[2]))
                    self.assertLess(abs(cos), 0.02, (s.start, f, cos))
                    checked += 1
        self.assertGreater(checked, 10)

    def test_every_cut_changes_the_picture_clearly_whatever_the_seed(self):
        for seed in range(10):                                                              # T2-51
            shots = plan(seed=seed)
            values = mc.music_values(shots, LAST)
            for before, after in zip(shots, shots[1:]):
                a, b = values[before.end], values[after.start]
                self.assertTrue(mc.changes_clearly((a["distance"], a["pos"][1], a["rot"]), (b["distance"], b["pos"][1], b["rot"])),
                                (seed, after.start))

    def test_the_sway_grows_with_the_handheld_strength(self):
        shots = plan()                                                                     # T2-55

        def rots(strength):
            return [motion_edit.camera_to_ui(k)["rot"] for k in mc.music_motion(shots, LAST, handheld=strength, seed=0).cameras]
        plain, one, two = rots(0.0), rots(1.0), rots(2.0)
        for f in range(0, LAST + 1, 37):
            for i in (0, 1):
                self.assertAlmostEqual(two[f][i] - plain[f][i], 2.0 * (one[f][i] - plain[f][i]), places=3)
        self.assertGreater(max(abs(a[1] - b[1]) for a, b in zip(one, plain)), 0.1)


class MusicCutsTest(unittest.TestCase):
    def test_no_push_in_runs_while_a_punch_zooms(self):
        # a punch of the motion graphics zooms over mograph_layer's rise and fall frames from its frame: put one 7 frames
        # before a push in of the plain plan; the plan with it draws no push in while it zooms (T2-21, T2-22)
        ml = load("mograph_layer")
        zoom = ml.DEFAULTS["punch"]["rise"] + ml.DEFAULTS["punch"]["fall"]
        pushes = [m for s in plan() for m in s.moves if m.name == "dolly_in" and m.start >= 20]
        self.assertTrue(pushes)
        for m0 in pushes[:3]:
            p = m0.start - 7
            for m in (m for s in plan(punches=[p]) for m in s.moves if m.name == "dolly_in"):
                self.assertFalse(m.start < p + zoom and p < m.start + m.frames, (m.start, m.frames, p))

    def test_a_flash_up_to_cut_snap_frames_from_a_planned_cut_moves_it(self):
        planned = frames_of_bar(14)                                                        # T2-35
        for d in (mc.CUT_SNAP, -mc.CUT_SNAP):
            starts = [s.start for s in plan(cut_on=[planned + d])]
            self.assertIn(planned + d, starts, d)
            self.assertNotIn(planned, starts, d)

    def test_a_flash_5_frames_after_a_planned_cut_moves_it(self):
        # (pins CUT_SNAP: "6 frames, under half a beat at 140 BPM") a shot of 5 frames would read as a dropped frame (T2-36)
        planned = frames_of_bar(14)
        shots = plan(cut_on=[planned + 5])
        self.assertIn(planned + 5, [s.start for s in shots])
        self.assertGreater(min(s.end - s.start + 1 for s in shots), 30)

    def test_an_onset_of_the_strong_z_itself_starts_a_move(self):
        onsets = [dict(ONSETS[0], z=mc.STRONG)] + ONSETS[1:]                              # T2-37
        verse = [s for s in plan(onsets=onsets) if s.section.startswith("verse")][0]
        self.assertEqual(verse.moves[0].start, int(round(ONSETS[0]["t"] * 30)))

    def test_the_onset_of_the_bar_the_cut_leads_starts_no_move_of_its_own(self):
        # the cut leads its bar by the references' 2.3 frames, so the bar's own onset falls 2 frames after the cut: the
        # cut is on it and the move starts with the cut, not a hit 2 frames later (T2-39)
        onsets = ONSETS + [{"t": BEAT * 4 * 8, "z": 6.0}]
        shot = [s for s in plan(onsets=onsets) if s.start == frames_of_bar(8)][0]
        self.assertEqual(shot.moves[0].start, shot.start)

    def test_only_a_short_tail_move_runs_into_the_next_cut(self):
        # a cut moved 5 frames later onto a flash leaves the 2-bar shot after it 5 frames short: its move gives way to
        # 4-beat ones, no 8-beat move runs more than MOVE_OVERRUN frames past its shot (T2-41)
        beat = BEAT * 30
        for shot in plan(cut_on=[frames_of_bar(14) + 5]):
            for m in shot.moves:
                if m.frames > 4 * beat + 1e-9:
                    self.assertLessEqual(m.start + m.frames, shot.end + mc.MOVE_OVERRUN, (shot.start, m.start, m.frames))

    def test_a_whole_move_is_cut_at_most_a_tenth_of_a_second_short(self):
        # (pins MOVE_OVERRUN: 3 frames, "a cut moved onto a flash shortens its shot by 2, a shot that ends on a cut before
        # the beat is a few frames short") a shot 3 frames short keeps no 8-beat move cut 4 frames before its end (T2-42)
        flash = frames_of_bar(14) + 3
        shot = [s for s in plan(cut_on=[flash]) if s.start == flash][0]
        self.assertTrue(all(m.frames <= 60 for m in shot.moves), [(m.start, m.frames) for m in shot.moves])


class MusicFacingTest(unittest.TestCase):
    def test_her_faces_way_is_the_heads_way_in_the_forward_kinematics(self):
        # she bows 40 degrees (上半身 about X) and turns her neck 30 degrees (首 about Y): her face's way is the head's -Z as
        # mmd_cli/fk.py composes the bones from the root (T2-28: composed from the head the bow does not tilt the turn)
        from tests.test_operator_camera import rin_like_model
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "rin.pmx")
        with open(path, "wb") as f:
            f.write(rin_like_model())
        dance = vmd.Motion(model_name="d", bones=[bone("上半身", 0, rot=(40, 0, 0)), bone("首", 0, rot=(0, 30, 0)),
                                                  bone("上半身", 30, rot=(40, 0, 0)), bone("首", 30, rot=(0, 30, 0))])
        track = fk.world_track(pmx.load(path), dance, ["頭"], 0, 30)
        chain = mc.facing_chain(dance)
        for f in (0, 15, 30):
            x, _, z = fk.rotate(track["頭"][f][1], (0.0, 0.0, -1.0))
            self.assertAlmostEqual(mc.facing_at(chain, f), math.degrees(math.atan2(x, -z)), delta=0.5)

    def test_her_way_across_the_back_is_one_span(self):
        # she faces the back and sways 5 degrees either side of it: one span over all the frames, her way about 180 (T2-29)
        dance = vmd.Motion(model_name="s", bones=[bone("上半身", f, rot=(0, 175 if (f // 30) % 2 == 0 else 185, 0))
                                                  for f in range(0, 301, 30)])
        a, b, way = mc.steady_facing(mc.facing_chain(dance), 0, 300, [150])
        self.assertEqual((a, b), (0, 300))
        self.assertAlmostEqual(abs(way), 180.0, delta=6.0)

    def test_the_span_she_holds_her_way_over_is_as_long_as_it_can_be(self):
        # within FACING_HOLD either side of its middle, and one frame more either way would not be (T2-30)
        dance = vmd.Motion(model_name="synthetic", bones=[bone("上半身", 0), bone("上半身", 100), bone("上半身", 200, rot=(0, 40, 0)),
                                                          bone("上半身", 400, rot=(0, 40, 0))])
        chain = mc.facing_chain(dance)
        ways = [mc.facing_at(chain, f) for f in range(401)]
        width = 2.0 * mc.FACING_HOLD
        for wanted in (50, 300):
            a, b, _ = mc.steady_facing(chain, 0, 400, [wanted])
            self.assertLessEqual(max(ways[a:b + 1]) - min(ways[a:b + 1]), width + 1e-9)
            if a > 0:
                self.assertGreater(max(ways[a - 1:b + 1]) - min(ways[a - 1:b + 1]), width, (wanted, a, b))
            if b < 400:
                self.assertGreater(max(ways[a:b + 2]) - min(ways[a:b + 2]), width, (wanted, a, b))

    def test_a_shot_of_the_least_length_holds_a_contact(self):
        least = mc.MUSIC_CONTACT_LEAST                                                     # T2-33
        self.assertEqual(mc.contact_shots([(0, least - 1), (least, least + 9)], [1.0]), {0: [30]})

    def test_a_contact_goes_to_the_long_shot_whose_end_is_nearest(self):
        self.assertEqual(mc.contact_shots([(0, 199), (200, 209), (210, 399)], [202 / 30.0]), {0: [202]})   # T2-34

    def test_a_contact_shot_is_aimed_at_the_frames_a_contact_can_be_in(self):
        # eye_gaze makes no contact 6 frames after a cut nor 2 before the next (CONTACT_CLEAR): the frames the shot is
        # aimed at lie between (T2-60)
        t = 10.5
        c = int(round(t * 30))
        shot = [s for s in plan(contacts=[t]) if s.start <= c <= s.end][0]
        a, b = shot.contact
        self.assertGreaterEqual(a, shot.start + mc.CONTACT_CLEAR[0])
        self.assertLessEqual(b, shot.end - mc.CONTACT_CLEAR[1])

    def test_a_contact_shot_of_a_quiet_part_is_still_shot_wide(self):
        # the verse is shot wide (her feet in); its contact shot too, when a wide distance cuts clearly (T2-61)
        t = 10.5
        c = int(round(t * 30))
        shot = [s for s in plan(contacts=[t]) if s.start <= c <= s.end][0]
        self.assertTrue(shot.section.startswith("verse"))
        self.assertIn(shot.base["distance"], mc.MUSIC_DISTANCES["wide"])


class MusicCommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(synthetic_dance()))
        self.song = write_json(self.folder, "song.json", synthetic_song())

    def report(self, *args):
        out, report = os.path.join(self.folder, "cam.vmd"), os.path.join(self.folder, "r.json")
        code, result = quiet(mc.main, [self.dance, out, "--song", self.song, "--report", report] + list(args))
        self.assertEqual(code, 0, result)
        with open(report, encoding="utf-8") as f:
            return json.load(f)

    def test_the_command_reads_the_guard_report(self):
        # the guard's tilt of a first pass rises 15 degrees over each crane down of the plain plan: --guard-report puts no
        # crane down there (T2-57)
        downs = [m for s in plan(dance=vmd.load(self.dance)) for m in s.moves if m.name == "crane_down"]
        self.assertTrue(downs)
        tilt = [0.0] * (LAST + 1)
        for m in downs:
            for f in range(m.start, min(LAST + 1, m.start + m.frames + 1)):
                tilt[f] = 15.0 * (f - m.start) / float(m.frames)
        guard = write_json(self.folder, "guard.json", {"per_frame": {"tilt": tilt}})
        for s in self.report("--guard-report", guard)["shots"]:
            for m in s["moves"]:
                if m["name"] == "crane_down":
                    span = tilt[m["start"]:min(LAST + 1, m["start"] + m["frames"] + 1)]
                    self.assertLessEqual(max(span) - span[0], mc.GUARD_RISE_LEAST, m)

    def test_the_command_takes_the_strong_z(self):
        # at --strong 7 the verse's onset of z 6 is weak: the verse's move starts at its cut (T2-59)
        onsets = write_json(self.folder, "onsets.json", {"onsets": ONSETS})
        r = self.report("--onsets", onsets, "--strong", "7")
        self.assertEqual(r["song"]["strong"], 7.0)
        verse = [s for s in r["shots"] if s["section"].startswith("verse")][0]
        self.assertEqual(verse["moves"][0]["start"], verse["start"])


# ---- --song with --model: the sizes (camsync2) ---------------------------------------------------------------------------

oc = mc._operator()
# Rin's heights (Sour's White.pmx at rest, as the operator tests have them), her ankles where the leg IK bones are
REST = {"headtop": 19.5, "eyes": 17.21, "chin": 16.24, "chest": 13.8, "waist": 12.23, "hips": 10.66, "toes": 0.1,
        "center": 7.85, "lshoulder": 15.28, "rshoulder": 15.28, "lhip": 10.66, "rhip": 10.66, "ltoe": 0.1, "rtoe": 0.1,
        "lankle": 1.75, "rankle": 1.75}
SIDE = {"lshoulder": 0.91, "rshoulder": -0.91, "lhip": 0.90, "rhip": -0.90, "ltoe": 0.90, "rtoe": -0.90, "lankle": 0.90,
        "rankle": -0.90}
SPIN = (740, 770)             # frames: her shoulders and lower body turn twice round at 720 degrees a second (chorus, bars 12-13)
STEPS = (1078, 1197)          # frames: her feet step fast (chorus, bars 18-19)
TURNED = (905, 1035)          # frames: she turns her face 60 degrees to her left and back (chorus, bars 15-17)
NOTE = (18.2, 18.9)           # s: a sustained note (verse, bar 9)
SQUAT = (300, 312)            # frames: she squats, her hips 5 units down at the deepest (verse, bar 5)
THIGH, SHIN = 4.76, 4.15      # her legs (Sour's Rin: hip joint 10.66, knee 5.9, ankle 1.75)
CONTACT = 29.0                # s: an eye contact wanted (chorus, bars 14-15)


def sized_centre(f):
    return 1.5 * math.sin(2.0 * math.pi * f / 900.0), 0.4 * math.sin(2.0 * math.pi * f / 1300.0)


def sized_dance():
    """センター walks a little side to side; her whole body turns (センター's Y) by TURNED's 60 degrees and back"""
    keys = []
    for f in list(range(0, LAST + 1, 15)) + [LAST]:
        x, z = sized_centre(f)
        a = 0.0
        if TURNED[0] <= f <= TURNED[1]:
            a = 60.0 * math.sin(math.pi * (f - TURNED[0]) / float(TURNED[1] - TURNED[0])) ** 0.5
        keys.append(bone("センター", f, pos=(x, 0.0, z), rot=(0.0, a, 0.0)))
    return vmd.Motion(model_name="sized", bones=keys)


def sized_dancer(motion):
    """her landmarks over the sized dance: standing where センター is, facing where the dance turns her (facing_at), her
    shoulders and lower body spinning over SPIN, her feet stepping over STEPS"""
    chain = mc.facing_chain(motion)
    out = {n: [] for n in oc.LANDMARKS + oc.HIP_LANDMARKS + oc.LEG_LANDMARKS}
    for f in range(LAST + 1):
        x, z = sized_centre(f)
        way = mc.facing_at(chain, f)
        spin = 720.0 * (f - SPIN[0]) / 30.0 if SPIN[0] <= f <= SPIN[1] else 0.0
        a = math.radians(way + spin)
        step = 1.5 * math.sin(2.0 * math.pi * 3.0 * f / 30.0) if STEPS[0] <= f <= STEPS[1] else 0.0
        down = 5.0 * math.sin(math.pi * (f - SQUAT[0]) / float(SQUAT[1] - SQUAT[0])) if SQUAT[0] <= f <= SQUAT[1] else 0.0
        for name in oc.LANDMARKS + ("lhip", "rhip", "ltoe", "rtoe", "lankle", "rankle"):
            s = SIDE.get(name, 0.0)
            dx = (step if name in ("ltoe", "lankle") else -step if name in ("rtoe", "rankle") else 0.0)
            dy = 0.0 if name in ("ltoe", "rtoe", "lankle", "rankle", "toes") else -down
            out[name].append((x + s * math.cos(a) + dx, REST[name] + dy, z + s * math.sin(a)))
        out["pelvis_front"].append((x + math.sin(a), REST["waist"] - down, z - math.cos(a)))
        for side, (hip, ankle, toe) in (("l", ("lhip", "lankle", "ltoe")), ("r", ("rhip", "rankle", "rtoe"))):
            # the knee of her legs' lengths, bent the way she faces
            ahead = tuple(v + w for v, w in zip(out[ankle][-1], (math.sin(a), 0.0, -math.cos(a))))
            out[side + "knee"].append(oc.two_bone_knee(out[hip][-1], out[ankle][-1], ahead, THIGH, SHIN))
    return oc.Dancer(out)


def sized_song():
    song = synthetic_song()
    song["lines"] = [{"n": 1, "from": BEAT * 16, "to": BEAT * 47}, {"n": 2, "from": BEAT * 48, "to": BEAT * 79}]
    return song


def sized_plan(seed=0, **kw):
    motion = sized_dance()
    dancer = sized_dancer(motion)
    shots = mc.plan_music_shots(motion, sized_song(), ONSETS, seed=seed, contacts=[CONTACT], dancer=dancer,
                                notes=[NOTE], **kw)
    return motion, dancer, shots


def sized_cameras(shot):
    return [mc.sized_camera(v, shot.fov) for v in mc.music_shot_values(shot)]


def angle_off(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class MusicSizesTest(unittest.TestCase):
    """the sizes of the shots from what each holds (music_sizes): a shot with a fast turn, footwork or a busy dance is
    full, one that holds an eye contact chest, the sustained notes and the sung lines of the verses close (waist) first,
    then the chorus's, each share up to its target; the quiet parts are never close but for a contact; knee then takes
    its share of the rest, and full the remainder"""

    def shots(self):
        f = lambda n, kind, **kw: dict({"frames": n, "kind": kind, "chorus": kind == "chorus", "contact": False,
                                       "note": False, "sung": 0.0, "wide": False, "spin": False, "calm": True, "pace": 5.0},
                                      **kw)
        return [f(240, "intro"), f(240, "verse", sung=1.0), f(240, "verse", sung=1.0, note=True),
                f(120, "chorus", sung=1.0, wide=True), f(120, "chorus", sung=1.0, contact=True), f(60, "chorus", sung=1.0),
                f(60, "chorus", sung=1.0, calm=False), f(120, "chorus", sung=1.0, wide=True), f(240, "break", wide=True),
                f(60, "end", wide=True)]

    def test_wide_shots_are_full_and_a_contact_chest(self):
        sizes = mc.music_sizes(self.shots())
        self.assertEqual([sizes[i] for i in (3, 7, 8, 9)], ["full"] * 4)
        self.assertEqual(sizes[4], "chest")
        # a contact in a wide shot is not close
        shots = self.shots()
        shots[3]["contact"] = True
        self.assertEqual(mc.music_sizes(shots)[3], "full")

    def test_a_spin_is_never_close_and_may_be_knee(self):
        shots = self.shots()
        shots[2]["spin"] = True                         # the note's shot holds a fast turn
        shots[4]["spin"] = True                         # and the contact's
        sizes = mc.music_sizes(shots, share=dict(mc.MUSIC_SIZE_SHARE, knee=0.5), chorus_share=dict(mc.MUSIC_CHORUS_SHARE, knee=0.5))
        self.assertNotIn(sizes[2], mc.MUSIC_CLOSE)
        self.assertNotIn(sizes[4], mc.MUSIC_CLOSE)
        self.assertIn("knee", (sizes[2], sizes[4]))

    def test_the_sustained_note_and_the_verse_lines_come_close_first_and_the_quiet_parts_never(self):
        sizes = mc.music_sizes(self.shots())
        self.assertEqual(sizes[2], "waist")                                   # the note
        self.assertNotIn(sizes[0], mc.MUSIC_CLOSE)                            # the intro
        # with room for more close shots the other verse shot and then the chorus's come close, never the intro's
        share = dict(mc.MUSIC_SIZE_SHARE, waist=0.5)
        chorus_share = dict(mc.MUSIC_CHORUS_SHARE, waist=0.5)
        sizes = mc.music_sizes(self.shots(), share=share, chorus_share=chorus_share)
        self.assertEqual(sizes[1], "waist")
        self.assertIn("waist", [sizes[5], sizes[6]])
        self.assertNotIn(sizes[0], mc.MUSIC_CLOSE)
        # a contact in the intro is close
        shots = self.shots()
        shots[0]["contact"] = True
        self.assertEqual(mc.music_sizes(shots)[0], "chest")

    def test_each_share_comes_to_its_target_within_half_a_shot(self):
        shots = self.shots()
        sizes = mc.music_sizes(shots)
        total = float(sum(s["frames"] for s in shots))
        for size in ("waist", "knee"):
            got = sum(s["frames"] for s, z in zip(shots, sizes) if z == size)
            target = mc.MUSIC_SIZE_SHARE[size] * total
            self.assertLessEqual(got, target + 120 + 1e-9, size)
        # every size is one of the four, the face is not used
        self.assertTrue(set(sizes) <= set(mc.MUSIC_SIZES))
        self.assertEqual(mc.MUSIC_SIZES, ("full", "knee", "waist", "chest"))


class MusicSizedPlanTest(unittest.TestCase):
    """make_camera --song with her body (--model, camsync2): the cuts of the plain plan, each shot a size from what it holds,
    framed from her body (operator_camera.frame_size) so that every frame shows it (full: both toes and some floor; knee:
    the knees, not the ankles; waist: the hip joints, not the knees; chest: the shoulders, not the hip joints; her head
    top and eyes inside the picture with room for the punch's zoom), a close shot looking down at her hips and hip joints
    by CLOSE_LOOK_DOWN, every cut a size or 30 degrees, none across the line of her face's way"""

    @classmethod
    def setUpClass(cls):
        cls.motion, cls.dancer, cls.shots = sized_plan()

    def test_the_cuts_are_those_of_the_plain_plan(self):
        plain = mc.plan_music_shots(self.motion, sized_song(), ONSETS, seed=0, contacts=[CONTACT])
        self.assertEqual([(s.start, s.end) for s in self.shots], [(s.start, s.end) for s in plain])
        self.assertTrue(all(s.size in mc.MUSIC_SIZES for s in self.shots))
        self.assertTrue(all(s.size is None and s.height is None and s.fov is None for s in plain))

    def test_every_frame_shows_its_size_and_her_head(self):
        # her head under the row a punch's zoom leaves room for where it may zoom (round the title word and the parts'
        # first frames), under the free row elsewhere; the size on `hold` of the frames and on both ends of the shot
        song = sized_song()
        zoom = mc.zoom_frames([mc.song_parts(song, LAST)[i][3] for i in range(len(mc.song_parts(song, LAST)))],
                              [h["frame"] for h in song["hooks"]])
        self.assertIn(song["hooks"][0]["frame"] + 5, zoom)
        self.assertNotIn(song["hooks"][0]["frame"] + 40, zoom)
        ends = mc.MUSIC_FRAME["ends"]
        for s in self.shots:
            cams = sized_cameras(s)
            rows = [mc.MUSIC_FRAME["head_row"] if s.start + i in zoom else mc.MUSIC_FRAME["head_free"] for i in range(len(cams))]
            shown = [mc.size_shown(self.dancer, s.start + i, cam, s.size, rows[i]) for i, cam in enumerate(cams)]
            self.assertGreaterEqual(sum(shown) / float(len(shown)), mc.MUSIC_FRAME["hold"], (s.start, s.size))
            self.assertTrue(all(shown[:ends]) and all(shown[-ends:]), (s.start, s.size))
            for i, cam in enumerate(cams):
                f = s.start + i
                for name in ("headtop", "eyes"):
                    u, v, depth = oc.project(cam.position, cam.yaw, cam.pitch, 0.0, cam.fov, self.dancer.at(name, f))
                    self.assertGreater(depth, 0.0)
                    self.assertLessEqual(v, rows[i] + 1e-9, (f, name, s.size))
                    self.assertLessEqual(abs(u), mc.MUSIC_FRAME["side"] + 1e-9, (f, name, s.size))

    def test_a_close_shot_looks_down_at_her_hips_and_hip_joints_by_30_degrees(self):
        close = [s for s in self.shots if s.size in mc.MUSIC_CLOSE]
        self.assertTrue(close)
        for s in close:
            for i, cam in enumerate(sized_cameras(s)):
                points = [self.dancer.at(n, s.start + i) for n in ("hips", "lhip", "rhip")]
                self.assertGreaterEqual(oc.look_down_at(cam.position, points), oc.CLOSE_LOOK_DOWN, (s.start + i, s.size))

    def test_a_full_shot_shows_both_toes_and_a_little_floor(self):
        full = [s for s in self.shots if s.size == "full"]
        self.assertTrue(full)
        for s in full:
            for i, cam in enumerate(sized_cameras(s)):
                for toe in ("ltoe", "rtoe"):
                    u, v, _ = oc.project(cam.position, cam.yaw, cam.pitch, 0.0, cam.fov, self.dancer.at(toe, s.start + i))
                    self.assertGreaterEqual(v, -1.0 + mc.MUSIC_FRAME["floor"] - 1e-9, (s.start + i, toe))

    def test_a_spin_and_footwork_are_shot_full_and_the_contact_chest_within_reach_of_her_eyes(self):
        def holding(f):
            return [s for s in self.shots if s.start <= f <= s.end][0]
        self.assertEqual(holding(SPIN[0]).size, "full")
        self.assertEqual(holding(STEPS[0] + 30).size, "full")
        contact = holding(int(CONTACT * 30))
        self.assertEqual(contact.size, "chest")
        self.assertTrue(contact.contact)
        a, b = contact.contact
        chain = mc.facing_chain(self.motion)
        run = best = 0
        for i, cam in enumerate(sized_cameras(contact)):
            f = contact.start + i
            if not a <= f <= b:
                continue
            # within reach of her eyes, off her head's way (its pitch taken away): up to MUSIC_CONTACT_UP above it, up to
            # MUSIC_CONTACT_SIDE round from it, on a run of MUSIC_CONTACT_RUN frames
            way, pitch = mc.facing_both(chain, f)
            within = (mc.eyes_up(self.dancer, f, cam) - pitch <= mc.MUSIC_CONTACT_UP + 1e-6
                      and angle_off(mc.eyes_round(self.dancer, f, cam), way) <= mc.MUSIC_CONTACT_SIDE + 1e-6)
            run = run + 1 if within else 0
            best = max(best, run)
            self.assertLessEqual(angle_off(cam.yaw, mc.facing_at(chain, f)), 16.0, f)
        self.assertGreaterEqual(best, min(mc.MUSIC_CONTACT_RUN, b - a + 1))
        # the note's shot is close, and the quiet parts are not
        self.assertIn(holding(int(NOTE[0] * 30)).size, mc.MUSIC_CLOSE)
        for s in self.shots:
            if s.kind in ("intro", "break", "end"):
                self.assertNotIn(s.size, mc.MUSIC_CLOSE, s.start)

    def test_every_cut_changes_the_size_or_turns_30_degrees_and_none_crosses_the_line(self):
        chain = mc.facing_chain(self.motion)
        for seed in range(4):
            _, _, shots = sized_plan(seed=seed) if seed else (None, None, self.shots)
            dancer = self.dancer
            for before, after in zip(shots, shots[1:]):
                yaw_before = mc.music_shot_values(before)[-1]["yaw"]
                yaw_after = after.base["yaw"]
                # the turn as the picture shows it: her center to the eye before and after the cut
                az_before = mc.camera_azimuth(dancer, before.end, sized_cameras(before)[-1])
                az_after = mc.camera_azimuth(dancer, after.start, sized_cameras(after)[0])
                self.assertTrue(before.size != after.size or angle_off(az_before, az_after) >= 30.0,
                                (seed, after.start, before.size, after.size, az_before, az_after))
                if angle_off(az_before, az_after) < 30.0:
                    # another size that turns less changes her height in the picture as a size does (not a jump cut)
                    ratio = (mc.picture_height(dancer, after.start, sized_cameras(after)[0])
                             / mc.picture_height(dancer, before.end, sized_cameras(before)[-1]))
                    self.assertFalse(0.8 <= ratio <= 1.25, (seed, after.start, before.size, after.size, ratio))
                self.assertFalse(mc.crosses_line(mc.facing_at(chain, after.start), yaw_before, yaw_after),
                                 (seed, after.start, yaw_before, yaw_after))

    def test_a_knee_shot_keeps_both_her_knees_in_on_every_frame(self):
        # (a frame of a knee shot without her knees reads as waist up, which asks the close look-down)
        knee = [s for s in self.shots if s.size == "knee"]
        self.assertTrue(knee)
        for s in knee:
            for i, cam in enumerate(sized_cameras(s)):
                for p in mc._knees(self.dancer, s.start + i):
                    v = oc.project(cam.position, cam.yaw, cam.pitch, 0.0, cam.fov, p)[1]
                    self.assertGreaterEqual(v, -1.0 + mc.MUSIC_FRAME["in"] - 1e-9, (s.start + i))

    def test_a_window_is_planned_at_its_look_down(self):
        # a window of 25 degrees over the break (a whole-body shot from about 5 degrees): the shot that holds it is planned
        # from high enough, so guard has nothing to add there
        window = [1250, 1280, 25.0]
        _, _, shots = sized_plan(windows=[window])
        held = [s for s in shots if s.start <= window[0] <= s.end][0]
        plain = [s for s in self.shots if s.start == held.start][0]
        for f in range(window[0], window[1] + 1):
            cam = sized_cameras(held)[f - held.start]
            points = [self.dancer.at(n, f) for n in ("hips", "lhip", "rhip")]
            self.assertGreaterEqual(oc.look_down_at(cam.position, points), 25.0 - 1e-6, f)
        f = window[0]
        self.assertLess(oc.look_down_at(sized_cameras(plain)[f - plain.start].position,
                                        [self.dancer.at(n, f) for n in ("hips", "lhip", "rhip")]), 25.0)

    def test_the_cut_rule_gives_way_before_her_face_is_left_on_the_words(self):
        # (her face off the words is a guard, the cut rule a target): a shot whose ways that keep the rule all leave her face
        # on the words takes one that waives the rule's turn and keeps her face off them
        real = mc._sized_shot
        target = [s for s in self.shots if s.kind == "verse"][0].start

        def fake(dancer, size, index, frame, end, *rest, **kw):
            shot, hits, turns, why = real(dancer, size, index, frame, end, *rest, **kw)
            waive = rest[18] if len(rest) > 18 else kw.get("waive", 0)
            if frame == target and shot is not None and not waive:
                return shot, 5, turns, why                       # every way that keeps the rule: her face on the words
            return shot, hits, turns, why
        mc._sized_shot = fake
        try:
            _, _, shots = sized_plan()
        finally:
            mc._sized_shot = real
        held = [s for s in shots if s.start == target][0]
        self.assertEqual(held.features["face_hits"], 0)
        self.assertEqual(held.features["rule_waived"], 1)

    def test_the_line_is_crossed_when_her_face_turns_from_one_side_of_the_picture_to_the_other(self):
        self.assertTrue(mc.crosses_line(0.0, -40.0, 40.0))
        self.assertFalse(mc.crosses_line(0.0, -40.0, -10.0))
        self.assertFalse(mc.crosses_line(0.0, -5.0, 5.0))                  # she faces the camera on both: no side
        self.assertTrue(mc.crosses_line(60.0, 10.0, 110.0))

    def test_the_sized_values_reach_the_keys(self):
        motion = mc.music_motion(self.shots, LAST)
        keys = {k.frame: k for k in motion.cameras}
        for s in self.shots:
            for f in (s.start, s.end):
                ui = motion_edit.camera_to_ui(keys[f])
                v = mc.music_shot_values(s)[f - s.start]
                self.assertEqual(ui["fov"], s.fov, f)
                self.assertAlmostEqual(ui["pos"][1], s.height, places=3)
                self.assertAlmostEqual(ui["distance"], v["distance"], places=3)

    def test_without_her_body_nothing_changes(self):
        shots = plan()
        for s in shots:
            for v in mc.music_shot_values(s):
                self.assertEqual(v["pos"][1], mc.MUSIC_HEIGHT)
        self.assertTrue(all(motion_edit.camera_to_ui(k)["fov"] == mc.FOV for k in mc.music_motion(shots, LAST).cameras))

    def test_a_box_of_words_moves_her_face_off_it(self):
        # a narrow box down the middle of the picture's upper half over the whole first verse shot: her face is put
        # beside it
        verse = [s for s in self.shots if s.kind == "verse"][0]
        box = [verse.start, verse.end, 0.44, 0.0, 0.56, 0.5, "front"]
        _, _, shots = sized_plan(keep_clear=[box])
        moved = [s for s in shots if s.start == verse.start][0]
        hit = 0
        for i, cam in enumerate(sized_cameras(moved)):
            f = moved.start + i
            if mc.face_on_boxes(self.dancer, f, cam, [box]):
                hit += 1
        self.assertEqual(hit, 0)
        plain_hit = sum(1 for i, cam in enumerate(sized_cameras(verse)) if mc.face_on_boxes(self.dancer, verse.start + i, cam, [box]))
        self.assertGreater(plain_hit, 0)

    def test_a_close_shot_the_words_leave_no_room_for_is_shot_wide_and_its_share_goes_on(self):
        # a band of words across the whole picture's middle over the note's shot: no close way of seeing keeps her face
        # off it, a whole-body shot (her face above the band) does; the waist share goes to the other verse shot
        note = [s for s in self.shots if s.start <= int(NOTE[0] * 30) <= s.end][0]
        other = [s for s in self.shots if s.kind == "verse" and s is not note][0]
        self.assertIn(note.size, mc.MUSIC_CLOSE)
        self.assertNotIn(other.size, mc.MUSIC_CLOSE)
        box = [note.start, note.end, 0.0, 0.32, 1.0, 0.62, "back"]
        _, _, shots = sized_plan(keep_clear=[box])
        by_start = {s.start: s for s in shots}
        self.assertNotIn(by_start[note.start].size, mc.MUSIC_CLOSE)
        self.assertEqual(by_start[note.start].features["face_hits"], 0)
        self.assertIn(by_start[other.start].size, mc.MUSIC_CLOSE)
        # planned once (no second round), the note's shot is still widened but nothing takes its share
        rounds = mc.MUSIC_ROUNDS
        mc.MUSIC_ROUNDS = 1
        try:
            _, _, once = sized_plan(keep_clear=[box])
        finally:
            mc.MUSIC_ROUNDS = rounds
        self.assertNotIn({s.start: s for s in once}[other.start].size, mc.MUSIC_CLOSE)


def sized_model():
    """the bones the camera reads, laid out as on Sour's Rin at rest, with the leg IK bones (the ankles)"""
    from tests.test_pmx import NORMAL, TRANSLATE, Writer
    w = Writer(bone=2)
    bones = [("全ての親", -1, (0.0, 0.0, 0.0), NORMAL | TRANSLATE), ("センター", 0, (0.0, 7.85, 0.0), NORMAL | TRANSLATE),
             ("上半身", 1, (0.0, 12.23, -0.65), NORMAL), ("上半身2", 2, (0.0, 13.8, -0.68), NORMAL),
             ("首", 3, (0.0, 15.65, -0.13), NORMAL), ("頭", 4, (0.0, 16.24, 0.0), NORMAL),
             ("左目", 5, (0.41, 17.21, -0.56), NORMAL), ("右目", 5, (-0.41, 17.21, -0.56), NORMAL),
             ("下半身", 1, (0.0, 12.23, -0.65), NORMAL), ("左腕", 3, (0.91, 15.28, -0.25), NORMAL),
             ("右腕", 3, (-0.91, 15.28, -0.25), NORMAL), ("左つま先ＩＫ", 0, (1.05, 0.1, -1.15), NORMAL | TRANSLATE),
             ("右つま先ＩＫ", 0, (-1.05, 0.1, -1.15), NORMAL | TRANSLATE), ("左足", 8, (0.90, 10.66, 0.007), NORMAL),
             ("右足", 8, (-0.90, 10.59, 0.007), NORMAL), ("左足ＩＫ", 0, (0.93, 1.75, 0.38), NORMAL | TRANSLATE),
             ("右足ＩＫ", 0, (-0.93, 1.75, 0.38), NORMAL | TRANSLATE), ("左ひざ", 13, (0.92, 6.0, -0.30), NORMAL),
             ("右ひざ", 14, (-0.92, 5.95, -0.30), NORMAL), ("左足首", 17, (0.93, 1.75, 0.38), NORMAL),
             ("右足首", 18, (-0.93, 1.75, 0.38), NORMAL)]
    return w.build(name="rin-sized", bones=[w.bone(n, parent=p, position=pos, flags=fl) for n, p, pos, fl in bones])


class MusicSizedCommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(sized_dance()))
        self.model = os.path.join(self.folder, "rin.pmx")
        with open(self.model, "wb") as f:
            f.write(sized_model())
        self.song = write_json(self.folder, "song.json", sized_song())
        # lip_sync's alignment (--align-out): a vowel at NOTE held on by a long mark, the rest short
        self.notes = write_json(self.folder, "align.json", [
            {"line": 0, "mora": "x", "kana": "x", "consonant": "", "vowel": "a", "held": False, "word_start": True,
             "c0": 10.0, "v0": 10.0, "v1": 10.2},
            {"line": 0, "mora": "x", "kana": "x", "consonant": "", "vowel": "a", "held": False, "word_start": False,
             "c0": NOTE[0], "v0": NOTE[0], "v1": NOTE[0] + 0.3},
            {"line": 0, "mora": "x", "kana": "x", "consonant": "", "vowel": "a", "held": True, "word_start": False,
             "c0": NOTE[0] + 0.3, "v0": NOTE[0] + 0.3, "v1": NOTE[1]}])

    def test_the_model_and_the_notes_reach_the_plan(self):
        out, report = os.path.join(self.folder, "cam.vmd"), os.path.join(self.folder, "r.json")
        code, result = quiet(mc.main, [self.dance, out, "--song", self.song, "--report", report, "--model", self.model,
                                       "--notes", self.notes])
        self.assertEqual(code, 0, result)
        with open(report, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["notes"]["wanted"], [[NOTE[0], NOTE[1]]])
        sizes = [s["size"] for s in data["shots"]]
        self.assertTrue(set(sizes) <= set(mc.MUSIC_SIZES), sizes)
        self.assertIn("full", sizes)
        self.assertTrue(set(sizes) & set(mc.MUSIC_CLOSE), sizes)
        self.assertEqual(result["sizes"], {k: sizes.count(k) for k in sorted(set(sizes))})
        # without --model the report has no sizes and the camera is the plain one
        plain_out, plain_report = os.path.join(self.folder, "plain.vmd"), os.path.join(self.folder, "p.json")
        code, _ = quiet(mc.main, [self.dance, plain_out, "--song", self.song, "--report", plain_report])
        self.assertEqual(code, 0)
        with open(plain_report, encoding="utf-8") as f:
            self.assertNotIn("size", json.load(f)["shots"][0])

    def test_notes_are_the_vowels_held_long_enough(self):
        self.assertEqual(mc.load_notes(self.notes), [(NOTE[0], NOTE[1])])

if __name__ == "__main__":
    unittest.main()
