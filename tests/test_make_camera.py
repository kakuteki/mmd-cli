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
