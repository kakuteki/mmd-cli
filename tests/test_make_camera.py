"""tools/make_camera.py: a calm camera motion generated from a dance motion, without MMD."""
import importlib.util
import os
import unittest

from mmd_cli import mathutil
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
        self.assertGreater(self.total("右足ＩＫ", pos=(0, 0, 2)), 0.0)
        self.assertGreater(self.total("センター", pos=(0, 0, 2)), self.total("右足ＩＫ", pos=(0, 0, 2)))

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
        want = {"push_in": (32.0, 26.0), "pull_out": (30.0, 42.0), "orbit": (34.0, 34.0), "low": (30.0, 28.0)}
        heights = {"push_in": 12.0, "pull_out": 13.0, "orbit": 12.0, "low": 7.0}
        seen = set()
        for shots in self.plans(synthetic_dance(), seeds=range(20)):
            for s in shots:
                seen.add((s.kind, s.level))
                add = 6.0 if s.level == "peak" else 0.0
                self.assertEqual(s.distance, (want[s.kind][0] + add, want[s.kind][1] + add), s)
                self.assertEqual(s.height, heights[s.kind], s)
                self.assertEqual(s.rot[0][0], -6.0 if s.kind == "low" else 0.0)
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
        strongest = max(analysis.boundaries, key=lambda b: b.strength).frame
        wild = [s for s in shots if s.start == strongest][0]
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


class LookAtTest(unittest.TestCase):
    def test_the_look_at_follows_the_center_at_both_ends_of_a_shot(self):
        for shots in (make_camera.plan_shots(synthetic_dance(), seed=s) for s in range(3)):
            for s in shots:
                for frame, pos in ((s.start, s.pos[0]), (s.end, s.pos[1])):
                    x, z = center_at(frame)
                    self.assertAlmostEqual(pos[0], x, places=5, msg=(s.start, s.end, frame))
                    self.assertAlmostEqual(pos[2], z, places=5, msg=(s.start, s.end, frame))
                    self.assertEqual(pos[1], s.height)
        shots = make_camera.plan_shots(synthetic_dance())
        self.assertEqual(shots[0].pos[0][0], 0.0)
        self.assertAlmostEqual(shots[-1].pos[1][0], CENTER_X_END, places=5)

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


class AnalysisJsonTest(unittest.TestCase):
    def test_the_json_is_plain_data_with_the_definitions(self):
        import json
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


if __name__ == "__main__":
    unittest.main()
