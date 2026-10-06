"""mmd_cli.fk: forward kinematics of a PMX model under a VMD motion, and the world position of a VMD camera."""
import importlib.util
import math
import os
import random
import unittest
from unittest import mock

from mmd_cli import fk, mathutil, motion_edit
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, APPEND_TRANSLATE, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_fix_twist():
    spec = importlib.util.spec_from_file_location("fix_twist", os.path.join(ROOT, "tools", "fix_twist.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def about(axis, degrees):
    """the quaternion of a turn by `degrees` about `axis` (Hamilton, right-hand rule on the numbers)"""
    half = math.radians(degrees) / 2.0
    n = math.sqrt(sum(a * a for a in axis))
    s = math.sin(half) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def build_model(*bones):
    """bones: (name, parent index or -1, rest position, Writer.bone keyword arguments)"""
    w = Writer(bone=2)
    return pmx.loads(w.build(bones=[w.bone(name, parent=parent, position=pos, **kw) for name, parent, pos, kw in bones]))


def key(name, frame, rotation=(0.0, 0.0, 0.0, 1.0), pos=(0.0, 0.0, 0.0), curve=None):
    interpolation = vmd.bone_interpolation(curve) if curve else vmd.DEFAULT_BONE_INTERPOLATION
    return vmd.BoneKey(name, frame, tuple(float(v) for v in pos), tuple(rotation), interpolation)


def motion(*keys):
    return vmd.Motion(model_name="test", bones=list(keys))


def close(test, a, b, places=6, msg=None):
    test.assertEqual(len(a), len(b), msg)
    for x, y in zip(a, b):
        test.assertAlmostEqual(x, y, places=places, msg=msg)


def angle_of(q):
    return math.degrees(2.0 * math.acos(min(1.0, abs(q[3]))))


def same_rotation(test, a, b, degrees=1e-6):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    test.assertLess(math.degrees(2.0 * math.acos(min(1.0, dot))), degrees, (a, b))


class ConventionTest(unittest.TestCase):
    def test_the_default_applies_the_numbers_as_stored(self):
        self.assertEqual(fk.KEY_ROTATION_SIGNS, (1.0, 1.0, 1.0))
        q = about((1.0, 2.0, 3.0), 40.0)
        self.assertEqual(fk.applied(q), q)
        self.assertEqual(fk.stored(q), q)

    def test_stored_undoes_applied_whatever_the_signs(self):
        q = about((1.0, -2.0, 0.5), 70.0)
        for signs in ((1.0, 1.0, 1.0), (-1.0, -1.0, -1.0), (1.0, -1.0, 1.0), (-1.0, 1.0, -1.0)):
            with mock.patch.object(fk, "KEY_ROTATION_SIGNS", signs):
                close(self, fk.stored(fk.applied(q)), q)
                close(self, fk.applied(fk.stored(q)), q)

    def test_under_the_default_a_negative_x_turn_bends_a_knee_backward(self):
        # the evidence for the default (docs/reviews/2026-10-06-batch-g-eye-gaze.md): Sour Rin's knees may only
        # turn about X between -180 and 0 degrees (their IK limits), and a knee bends backward.  Below the knee
        # the shin points down; the model faces -Z, so "backward" is +Z
        shin = fk.rotate(fk.applied(mathutil.ui_to_quat(-60.0, 0.0, 0.0)), (0.0, -1.0, 0.0))
        self.assertGreater(shin[2], 0.8)
        with mock.patch.object(fk, "KEY_ROTATION_SIGNS", (-1.0, -1.0, -1.0)):
            shin = fk.rotate(fk.applied(mathutil.ui_to_quat(-60.0, 0.0, 0.0)), (0.0, -1.0, 0.0))
        self.assertLess(shin[2], -0.8)


class QuaternionTest(unittest.TestCase):
    def test_rotate_follows_the_right_hand_rule_on_the_numbers(self):
        close(self, fk.rotate(about(Y, 90.0), (0.0, 0.0, -2.0)), (-2.0, 0.0, 0.0))
        close(self, fk.rotate(about(X, 90.0), (0.0, 0.0, -2.0)), (0.0, 2.0, 0.0))
        close(self, fk.rotate(about(Z, 90.0), (1.0, 0.0, 0.0)), (0.0, 1.0, 0.0))

    def test_multiply_applies_the_right_factor_first(self):
        q = fk.multiply(about(Y, 90.0), about(X, 90.0))
        close(self, fk.rotate(q, (0.0, 0.0, -1.0)), fk.rotate(about(Y, 90.0), fk.rotate(about(X, 90.0), (0.0, 0.0, -1.0))))

    def test_power_scales_the_angle_about_the_same_axis(self):
        same_rotation(self, fk.power(about(Y, 90.0), 0.5), about(Y, 45.0))
        same_rotation(self, fk.power(about(Y, 90.0), -1.0), about(Y, -90.0))
        same_rotation(self, fk.power(about(Y, 90.0), 0.0), fk.IDENTITY)
        same_rotation(self, fk.power(tuple(-v for v in about(X, 30.0)), 2.0), about(X, 60.0))   # q and -q alike


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.model = build_model(("A", -1, (0.0, 10.0, 0.0), {}), ("B", 0, (0.0, 10.0, -2.0), {}),
                                 ("C", 1, (0.0, 10.0, -4.0), {}))

    def world(self, keys, name, frame=0):
        return fk.Pose(self.model, motion(*keys), [name]).at(frame)[name]

    def test_a_parent_turned_90_degrees_about_y_carries_its_child(self):
        position, rotation = self.world([key("A", 0, about(Y, 90.0))], "B")
        close(self, position, (-2.0, 10.0, 0.0))
        same_rotation(self, rotation, about(Y, 90.0))

    def test_the_convention_is_one_switch(self):
        with mock.patch.object(fk, "KEY_ROTATION_SIGNS", (-1.0, -1.0, -1.0)):
            position, _ = self.world([key("A", 0, about(Y, 90.0))], "B")
        close(self, position, (2.0, 10.0, 0.0))

    def test_rotations_compose_from_the_parent_down(self):
        # B turns about its own X after A turned about Y: C (2 in front of B) goes up, not sideways
        position, rotation = self.world([key("A", 0, about(Y, 90.0)), key("B", 0, about(X, 90.0))], "C")
        close(self, position, (-2.0, 12.0, 0.0))
        same_rotation(self, rotation, fk.multiply(about(Y, 90.0), about(X, 90.0)))

    def test_a_bone_without_keys_keeps_its_rest_offset(self):
        position, rotation = self.world([], "C")
        close(self, position, (0.0, 10.0, -4.0))
        same_rotation(self, rotation, fk.IDENTITY)

    def test_translation_keys_add_in_the_parents_frame(self):
        position, _ = self.world([key("A", 0, pos=(1.0, 2.0, 3.0))], "A")
        close(self, position, (1.0, 12.0, 3.0))
        keys = [key("A", 0, about(Y, 90.0), pos=(1.0, 2.0, 3.0)), key("B", 0, pos=(0.0, 0.0, -1.0))]
        position, _ = self.world(keys, "B")
        close(self, position, (-2.0, 12.0, 3.0))                 # (1, 12, 3) + the turned (0, 0, -3)

    def test_between_keys_the_value_is_what_mmd_shows(self):
        keys = [key("A", 0, about(Y, 0.0)), key("A", 10, about(Y, 90.0))]
        self.assertAlmostEqual(angle_of(self.world(keys, "A", 5)[1]), 45.0, places=4)
        eased = [key("A", 0, about(Y, 0.0)), key("A", 10, about(Y, 90.0), curve=(64, 0, 64, 127))]
        self.assertLess(angle_of(self.world(eased, "A", 2)[1]), 9.0)                   # a slow start
        self.assertAlmostEqual(angle_of(self.world(keys, "A", 50)[1]), 90.0, places=4)  # held after the last

    def test_the_pose_at_any_frame_matches_the_track(self):
        rng = random.Random(3)
        keys = []
        for name in ("A", "B", "C"):
            for frame in sorted(rng.sample(range(0, 40), 5)):
                axis = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
                keys.append(key(name, frame, about(axis, rng.uniform(-170, 170)),
                                pos=(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)),
                                curve=(rng.randint(0, 127), rng.randint(0, 127), rng.randint(0, 127), rng.randint(0, 127))))
        m = motion(*keys)
        track = fk.world_track(self.model, m, ["C", "A"], 0, 45)
        self.assertEqual(sorted(track), ["A", "C"])
        self.assertEqual(len(track["C"]), 46)
        pose = fk.Pose(self.model, m, ["C", "A"])
        for frame in (0, 7, 23, 45):
            here = pose.at(frame)
            close(self, track["C"][frame][0], here["C"][0])
            close(self, track["A"][frame][1], here["A"][1])


class AppendTest(unittest.TestCase):
    def setUp(self):
        self.model = build_model(
            ("A", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
            ("half", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | APPEND_ROTATE, "append": (0, 0.5)}),
            ("back", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | APPEND_ROTATE, "append": (0, -1.0)}),
            ("moved", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | APPEND_TRANSLATE | TRANSLATE, "append": (0, 0.5)}),
            ("頭", -1, (0.0, 16.0, 0.0), {}),
            ("両目", 4, (0.0, 19.0, -0.3), {}),
            ("左目", 4, (0.4, 17.0, -0.5), {"flags": NORMAL | APPEND_ROTATE, "append": (5, 1.0)}),
            ("右目", 4, (-0.4, 17.0, -0.5), {"flags": NORMAL | APPEND_ROTATE, "append": (5, 1.0)}))

    def world(self, keys, name):
        return fk.Pose(self.model, motion(*keys), [name]).at(0)[name]

    def test_ratio_half_gives_half_the_rotation(self):
        same_rotation(self, self.world([key("A", 0, about(Y, 90.0))], "half")[1], about(Y, 45.0))

    def test_a_negative_ratio_turns_the_other_way(self):
        same_rotation(self, self.world([key("A", 0, about(Y, 90.0))], "back")[1], about(Y, -90.0))

    def test_the_appended_rotation_comes_before_the_bones_own(self):
        rotation = self.world([key("A", 0, about(Y, 90.0)), key("half", 0, about(X, 90.0))], "half")[1]
        same_rotation(self, rotation, fk.multiply(about(X, 90.0), about(Y, 45.0)))
        close(self, fk.rotate(rotation, (0.0, 0.0, -1.0)), (-math.sqrt(0.5), math.sqrt(0.5), 0.0))

    def test_an_appended_translation_adds_the_parents_key_times_the_ratio(self):
        position, _ = self.world([key("A", 0, pos=(2.0, 4.0, 6.0))], "moved")
        close(self, position, (1.0, 2.0, 3.0))

    def test_the_eyes_turn_with_both_eyes_and_stay_where_they_are(self):
        keys = [key("両目", 0, about(Y, 20.0))]
        for name in ("左目", "右目"):
            position, rotation = self.world(keys, name)
            same_rotation(self, rotation, about(Y, 20.0))
        close(self, self.world(keys, "左目")[0], (0.4, 17.0, -0.5))


class NameTest(unittest.TestCase):
    def test_an_unknown_bone_is_an_error(self):
        model = build_model(("A", -1, (0.0, 0.0, 0.0), {}))
        with self.assertRaises(ValueError) as ctx:
            fk.Pose(model, motion(), ["B"])
        self.assertIn("B", str(ctx.exception))

    def test_a_long_name_matches_the_15_byte_name_of_the_file(self):
        long_name = "とても長いボーンの名前です"                     # 26 bytes in cp932; a vmd keeps the first 15
        model = build_model((long_name, -1, (0.0, 0.0, 0.0), {}))
        raw = long_name.encode("cp932")[:15]                        # cut inside the 8th character, as MMD writes it
        cut = vmd.BoneKey(fk.vmd_name(long_name), 0, (0.0, 0.0, 0.0), about(Y, 30.0), raw_name=raw)
        from_file = vmd.loads(vmd.dumps(motion(cut)))
        self.assertNotEqual(from_file.bones[0].name, long_name)
        self.assertEqual(from_file.bones[0].name, fk.vmd_name(long_name))
        same_rotation(self, fk.Pose(model, from_file, [long_name]).at(0)[long_name][1], about(Y, 30.0))

    def test_a_bone_without_a_rest_position_is_an_error(self):
        model = build_model(("A", -1, (0.0, 0.0, 0.0), {}))
        model.bones[0].position = None                              # as a reader that does not keep it
        with self.assertRaises(ValueError) as ctx:
            fk.Pose(model, motion(), ["A"])
        self.assertIn("rest position", str(ctx.exception))


class SampleTest(unittest.TestCase):
    def test_the_sample_is_the_one_of_fix_twist(self):
        fix_twist = load_fix_twist()
        rng = random.Random(11)
        for _ in range(20):
            keys = []
            for frame in sorted(rng.sample(range(0, 60), 4)):
                axis = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
                keys.append(key("A", frame, about(axis, rng.uniform(-179, 179)),
                                pos=(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)),
                                curve=(rng.randint(0, 127), rng.randint(0, 127), rng.randint(0, 127), rng.randint(0, 127))))
            for frame in range(0, 62, 3):
                ours, theirs = fk.sample(keys, frame), fix_twist.sample(keys, frame)
                close(self, ours[0], theirs[0], places=9)
                close(self, ours[1], theirs[1], places=9)


def camera_key(frame, pos, distance, rot, curve=None, fov=30):
    return motion_edit.camera_key_from_ui({"pos": pos, "distance": distance, "rot": rot, "fov": fov, "perspective": True},
                                          curve=curve, frame=frame)


class CameraTest(unittest.TestCase):
    def position(self, keys, frame):
        keys = fk.camera_keys(vmd.Motion.for_camera(cameras=keys))
        return fk.camera_position(fk.camera_at(keys, frame))

    def test_window_angles_zero_put_the_camera_in_front_of_the_model(self):
        close(self, self.position([camera_key(0, (0.0, 10.0, 0.0), 45.0, (0.0, 0.0, 0.0))], 0), (0.0, 10.0, -45.0))

    def test_window_x_positive_lifts_the_camera_to_look_down(self):
        expected = (0.0, 10.0 + 45.0 * math.sin(math.radians(30.0)), -45.0 * math.cos(math.radians(30.0)))
        close(self, self.position([camera_key(0, (0.0, 10.0, 0.0), 45.0, (30.0, 0.0, 0.0))], 0), expected)

    def test_window_y_positive_swings_the_camera_to_plus_x(self):
        close(self, self.position([camera_key(0, (0.0, 10.0, 0.0), 45.0, (0.0, 90.0, 0.0))], 0), (45.0, 10.0, 0.0))
        c30 = math.cos(math.radians(30.0))
        close(self, self.position([camera_key(0, (1.0, 10.0, 2.0), 45.0, (30.0, 90.0, 0.0))], 0),
              (1.0 + 45.0 * c30, 32.5, 2.0))

    def test_the_state_is_shown_as_the_window_shows_it(self):
        keys = fk.camera_keys(vmd.Motion.for_camera(cameras=[camera_key(0, (0.5, 12.0, -1.0), 38.0, (10.0, -15.0, 2.0), fov=27)]))
        state = fk.camera_at(keys, 0)
        self.assertEqual(state.frame, 0)
        close(self, state.look_at, (0.5, 12.0, -1.0))
        self.assertAlmostEqual(state.distance, 38.0)
        close(self, state.angles, (10.0, -15.0, 2.0))
        self.assertAlmostEqual(state.fov, 27.0)

    def test_each_channel_follows_its_own_curve(self):
        ease_in = (127, 0, 127, 64)
        second = camera_key(10, (10.0, 10.0, 0.0), 50.0, (20.0, 40.0, 0.0))
        curves = {"x": vmd.LINEAR_CURVE, "y": vmd.LINEAR_CURVE, "z": vmd.LINEAR_CURVE, "rotation": ease_in,
                  "distance": ease_in, "fov": vmd.LINEAR_CURVE}
        second.interpolation = bytes(sum(([c[0], c[2], c[1], c[3]] for c in (curves[n] for n in vmd.CAMERA_CHANNELS)), []))
        keys = fk.camera_keys(vmd.Motion.for_camera(cameras=[second, camera_key(0, (0.0, 10.0, 0.0), 30.0, (0.0, 0.0, 0.0))]))
        state = fk.camera_at(keys, 5)
        eased = fk.bezier_y(ease_in, 0.5)
        self.assertLess(eased, 0.4)
        self.assertAlmostEqual(state.look_at[0], 5.0)                         # x is linear
        self.assertAlmostEqual(state.distance, 30.0 + 20.0 * eased)            # the distance eases in
        close(self, state.angles, (20.0 * eased, 40.0 * eased, 0.0))           # one curve for the three angles

    def test_held_before_the_first_and_after_the_last_key(self):
        keys = [camera_key(10, (0.0, 10.0, 0.0), 30.0, (0.0, 0.0, 0.0)), camera_key(20, (5.0, 10.0, 0.0), 30.0, (0.0, 0.0, 0.0))]
        close(self, self.position(keys, 0), (0.0, 10.0, -30.0))
        close(self, self.position(keys, 99), (5.0, 10.0, -30.0))

    def test_no_camera_keys_is_an_error(self):
        with self.assertRaises(ValueError):
            fk.camera_keys(vmd.Motion(model_name="dancer"))


if __name__ == "__main__":
    unittest.main()
