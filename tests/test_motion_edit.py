"""motion_edit: listing and editing the keys of a vmd without MMD."""
import math
import os
import tempfile
import unittest

from mmd_cli import mathutil, motion_edit
from mmd_cli.formats import vmd
from mmd_cli.motion_edit import Operations, Target

try:
    from mmd_cli import app
except ImportError:          # not on Windows
    app = None

from tests.test_mathutil import rotate


def bone(name, frame, pos=(0, 0, 0), rot=(0, 0, 0, 1), interp=vmd.DEFAULT_BONE_INTERPOLATION):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in pos), tuple(float(v) for v in rot), interp)


def camera(frame, distance=-45.0, pos=(0, 10, 0), rot=(0, 0, 0), fov=30, perspective=True,
           interp=vmd.DEFAULT_CAMERA_INTERPOLATION):
    return vmd.CameraKey(frame, float(distance), tuple(float(v) for v in pos), tuple(float(v) for v in rot), fov,
                         perspective, interp)


def model_motion():
    """センター at 0 10 20 30 and 右腕 at 0 20 (the same frames mixed in file order), two morphs"""
    return vmd.Motion(model_name="m",
                      bones=[bone("センター", 0), bone("右腕", 0, rot=mathutil.ui_to_quat(0, 0, 30)),
                             bone("センター", 10, pos=(0, 1, 0)), bone("センター", 20, pos=(0, 2, 0)),
                             bone("右腕", 20, rot=mathutil.ui_to_quat(0, 0, 45)), bone("センター", 30, pos=(0, 3, 0))],
                      morphs=[vmd.MorphKey("まばたき", 5, 1.0), vmd.MorphKey("まばたき", 15, 0.0), vmd.MorphKey("あ", 5, 0.5)])


def camera_motion():
    return vmd.Motion.for_camera(
        cameras=[camera(0, -45), camera(100, -60, pos=(1, 12, 0), rot=(0.1, 0.2, 0.3), fov=40), camera(200, -30)],
        lights=[vmd.LightKey(0, (0.6015625, 0.6015625, 0.6015625), (-0.5, -1.0, 0.5)),
                vmd.LightKey(150, (1.0, 0.5, 0.0), (0.0, -1.0, 0.0))])


def roundtrip(motion):
    return vmd.loads(vmd.dumps(motion))


def frames(keys):
    return [k.frame for k in keys]


def write(path, motion):
    with open(path, "wb") as f:
        f.write(vmd.dumps(motion))


class DuplicateTargetTest(unittest.TestCase):
    def test_the_same_target_named_twice_is_touched_once(self):
        # review 4 (2.1): --bone センター --all-bones shifted センター twice
        m = model_motion()
        targets = motion_edit.resolve_targets(m, [Target("bone", "センター"), Target("bone", None), Target("bone", "センター")])
        self.assertEqual(sorted(t.name for t in targets), ["センター", "右腕"])
        motion_edit.apply(m, targets, Operations(shift=10))
        self.assertEqual(sorted(k.frame for k in m.bones if k.name == "センター"), [10, 20, 30, 40])
        self.assertEqual(sorted(k.frame for k in m.bones if k.name == "右腕"), [10, 30])


class QuatMultiplyTest(unittest.TestCase):
    def assert_close(self, got, want):
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=9, msg="%r != %r" % (got, want))

    def test_identity(self):
        q = mathutil.euler_to_quat(10, 20, 30)
        self.assert_close(mathutil.quat_multiply(q, (0, 0, 0, 1)), q)
        self.assert_close(mathutil.quat_multiply((0, 0, 0, 1), q), q)

    def test_product_rotates_by_the_right_factor_first(self):
        # quat_multiply(a, b) applied to a vector is b first, then a (the Hamilton product)
        a = mathutil.euler_to_quat(90, 0, 0)
        b = mathutil.euler_to_quat(0, 90, 0)
        ab = mathutil.quat_multiply(a, b)
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.3, -0.5, 0.8)):
            self.assert_close(rotate(ab, v), rotate(a, rotate(b, v)))
        self.assertAlmostEqual(sum(c * c for c in ab), 1.0, places=9)
        # the two orders differ for these two rotations
        self.assertNotAlmostEqual(rotate(ab, (1, 0, 0))[1], rotate(mathutil.quat_multiply(b, a), (1, 0, 0))[1], places=3)


class RangeTest(unittest.TestCase):
    def test_both_ends_or_nothing(self):
        self.assertIsNone(motion_edit.check_range(None, None))
        self.assertEqual(motion_edit.check_range(0, 300), (0, 300))
        self.assertEqual(motion_edit.check_range(7, 7), (7, 7))
        for start, end in ((5, None), (None, 5), (10, 5), (-1, 5), (0, -1)):
            with self.assertRaises(ValueError, msg=(start, end)):
                motion_edit.check_range(start, end)


class SelectTest(unittest.TestCase):
    def test_range_includes_both_ends(self):
        m = camera_motion()
        self.assertEqual(frames(motion_edit.select(m, Target("camera"), (100, 200))), [100, 200])
        self.assertEqual(frames(motion_edit.select(m, Target("camera"), (0, 0))), [0])
        self.assertEqual(frames(motion_edit.select(m, Target("camera"), (101, 199))), [])
        self.assertEqual(frames(motion_edit.select(m, Target("camera"))), [0, 100, 200])
        self.assertEqual(frames(motion_edit.select(m, Target("light"), (1, 150))), [150])

    def test_a_bone_name_picks_only_its_own_keys(self):
        m = model_motion()
        self.assertEqual(frames(motion_edit.select(m, Target("bone", "センター"), (10, 20))), [10, 20])
        self.assertEqual(frames(motion_edit.select(m, Target("bone", "右腕"))), [0, 20])
        self.assertEqual(frames(motion_edit.select(m, Target("morph", "まばたき"))), [5, 15])
        self.assertEqual(frames(motion_edit.select(m, Target("bone", "センター"))), [0, 10, 20, 30])


class NamesTest(unittest.TestCase):
    def test_names_in_file_order(self):
        m = model_motion()
        self.assertEqual(motion_edit.names(m, "bone"), ["センター", "右腕"])
        self.assertEqual(motion_edit.names(m, "morph"), ["まばたき", "あ"])

    def test_unknown_names_are_errors_with_candidates(self):
        m = model_motion()
        with self.assertRaises(ValueError) as ctx:
            motion_edit.resolve_targets(m, [Target("bone", "センタ")])
        self.assertIn("センタ", str(ctx.exception))
        self.assertIn("センター", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            motion_edit.resolve_targets(m, [Target("morph", "笑い")])
        self.assertIn("まばたき", str(ctx.exception))        # no close match: the names in the file are listed
        with self.assertRaises(ValueError) as ctx:
            motion_edit.resolve_targets(camera_motion(), [Target("bone", "センター")])
        self.assertIn("no bone keys", str(ctx.exception))

    def test_all_bones_expands_in_file_order(self):
        self.assertEqual(motion_edit.resolve_targets(model_motion(), [Target("bone", None), Target("camera")]),
                         [Target("bone", "センター"), Target("bone", "右腕"), Target("camera")])
        self.assertEqual(motion_edit.resolve_targets(model_motion(), [Target("morph", None)]),
                         [Target("morph", "まばたき"), Target("morph", "あ")])
        with self.assertRaises(ValueError):
            motion_edit.resolve_targets(camera_motion(), [Target("bone", None)])

    def test_target_json_and_label(self):
        self.assertEqual(Target("camera").to_json(), {"kind": "camera"})
        self.assertEqual(Target("bone", "右腕").to_json(), {"kind": "bone", "name": "右腕"})
        self.assertIn("右腕", Target("bone", "右腕").label())


class ListTest(unittest.TestCase):
    def test_summary_counts_and_ranges_per_kind(self):
        s = motion_edit.summary(camera_motion())
        self.assertEqual(s["kind"], "camera")
        self.assertEqual(s["counts"], {"bones": 0, "morphs": 0, "cameras": 3, "lights": 2, "shadows": 0, "show_ik": 0})
        self.assertEqual(s["ranges"], {"bones": None, "morphs": None, "cameras": [0, 200], "lights": [0, 150],
                                       "shadows": None, "show_ik": None})
        s = motion_edit.summary(camera_motion(), (50, 160))
        self.assertEqual((s["counts"]["cameras"], s["ranges"]["cameras"]), (1, [100, 100]))
        self.assertEqual((s["counts"]["lights"], s["ranges"]["lights"]), (1, [150, 150]))
        s = motion_edit.summary(model_motion())
        self.assertEqual((s["kind"], s["model_name"], s["counts"]["bones"], s["ranges"]["bones"]), ("model", "m", 6, [0, 30]))

    def test_camera_keys_show_the_window_values(self):
        out = motion_edit.list_keys(camera_motion(), Target("camera"), (100, 200))
        self.assertEqual((out["target"], out["count"]), ({"kind": "camera"}, 2))
        key = out["keys"][0]
        self.assertEqual(key["frame"], 100)
        self.assertEqual(key["distance"], 60.0)                       # the file holds -60
        self.assertEqual(key["pos"], [1.0, 12.0, 0.0])
        self.assertEqual(key["rot"], [round(math.degrees(-0.1), 4), round(math.degrees(0.2), 4), round(math.degrees(0.3), 4)])
        self.assertEqual((key["fov"], key["perspective"]), (40, True))
        self.assertEqual(sorted(key), ["distance", "fov", "frame", "perspective", "pos", "rot"])

    def test_bone_keys_show_degrees_as_the_window_does(self):
        out = motion_edit.list_keys(model_motion(), Target("bone", "右腕"))
        self.assertEqual([k["frame"] for k in out["keys"]], [0, 20])
        self.assertEqual(out["keys"][0], {"frame": 0, "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 30.0]})
        self.assertEqual(out["keys"][1]["rot"], [0.0, 0.0, 45.0])

    def test_morph_and_light_keys(self):
        self.assertEqual(motion_edit.list_keys(model_motion(), Target("morph", "まばたき"))["keys"],
                         [{"frame": 5, "weight": 1.0}, {"frame": 15, "weight": 0.0}])
        out = motion_edit.list_keys(camera_motion(), Target("light"))["keys"]
        self.assertEqual(out[0], {"frame": 0, "rgb": [154, 154, 154], "dir": [-0.5, -1.0, 0.5]})
        self.assertEqual(out[1]["rgb"], [256, 128, 0])

    def test_keys_are_listed_in_frame_order_whatever_the_file_order(self):
        m = vmd.Motion.for_camera(cameras=[camera(300), camera(100), camera(200)])
        self.assertEqual([k["frame"] for k in motion_edit.list_keys(m, Target("camera"))["keys"]], [100, 200, 300])


class KeysFileTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "cam.vmd")
        write(self.path, camera_motion())

    def test_without_a_target_the_summary_is_returned(self):
        out = motion_edit.keys_file(self.path)
        self.assertEqual((out["path"], out["kind"], out["counts"]["cameras"], out["range"]),
                         (os.path.abspath(self.path), "camera", 3, None))
        self.assertNotIn("keys", out)

    def test_with_a_target_and_a_range(self):
        out = motion_edit.keys_file(self.path, Target("camera"), (0, 100))
        self.assertEqual((out["range"], out["count"], [k["frame"] for k in out["keys"]]), ([0, 100], 2, [0, 100]))
        self.assertEqual(out["target"], {"kind": "camera"})

    def test_unknown_name_is_an_error(self):
        model = os.path.join(self.folder, "m.vmd")
        write(model, model_motion())
        with self.assertRaises(ValueError) as ctx:
            motion_edit.keys_file(model, Target("bone", "左腕"))
        self.assertIn("左腕", str(ctx.exception))
        self.assertEqual([k["frame"] for k in motion_edit.keys_file(model, Target("bone", "右腕"))["keys"]], [0, 20])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            motion_edit.keys_file(os.path.join(self.folder, "none.vmd"))


def edit(motion, targets, span=None, **ops):
    """apply to a copy that went through the file format, like the command does; back through it again"""
    m = roundtrip(motion)
    reports = motion_edit.apply(m, targets, Operations(**ops), span)
    return roundtrip(m), reports


def by_frame(keys):
    return {k.frame: k for k in keys}


class ValidationTest(unittest.TestCase):
    def check(self, **ops):
        motion_edit.check_operations(Operations(**ops), [Target("camera")])

    def test_at_least_one_operation(self):
        with self.assertRaises(ValueError):
            self.check()

    def test_delete_stands_alone(self):
        self.check(delete=True)
        for other in (dict(shift=1), dict(copy_to=1), dict(distance_scale=0.5), dict(interp=(20, 20, 107, 107)), dict(replace=True)):
            with self.assertRaises(ValueError, msg=other):
                self.check(delete=True, **other)

    def test_replace_needs_shift_or_copy(self):
        with self.assertRaises(ValueError):
            self.check(replace=True, distance_scale=0.5)
        self.check(replace=True, shift=1)
        self.check(replace=True, copy_to=1)

    def test_values_that_cannot_be_used(self):
        for bad in (dict(copy_to=-1), dict(distance_scale=0), dict(distance_scale=-1), dict(fov_set=0), dict(interp=(128, 0, 0, 0)),
                    dict(interp=(1, 2, 3))):
            with self.assertRaises(ValueError, msg=bad):
                self.check(**bad)

    def test_value_operations_are_tied_to_a_kind(self):
        cases = ((dict(distance_scale=0.5), "bone"), (dict(distance_add=1), "light"), (dict(fov_add=1), "morph"),
                 (dict(fov_set=30), "bone"), (dict(rot_add=(0, 0, 1)), "camera"), (dict(weight_set=1), "bone"),
                 (dict(weight_scale=1), "camera"), (dict(pos_add=(1, 0, 0)), "morph"), (dict(interp=(20, 20, 107, 107)), "light"))
        for ops, kind in cases:
            with self.assertRaises(ValueError, msg=(ops, kind)) as ctx:
                motion_edit.check_operations(Operations(**ops), [Target("camera"), Target(kind, "x")])
            self.assertIn(_option(ops), str(ctx.exception))
        motion_edit.check_operations(Operations(pos_add=(1, 0, 0)), [Target("camera"), Target("bone", "x")])
        motion_edit.check_operations(Operations(shift=3), [Target(k, "x") for k in motion_edit.KINDS])


def _option(ops):
    return "--" + next(iter(ops)).replace("_", "-")


class ShiftTest(unittest.TestCase):
    def test_range_is_moved_and_the_rest_stays(self):
        m, reports = edit(camera_motion(), [Target("camera")], (100, 200), shift=50)
        self.assertEqual(sorted(frames(m.cameras)), [0, 150, 250])
        self.assertEqual(by_frame(m.cameras)[150].distance, -60.0)
        self.assertEqual(frames(m.lights), [0, 150])
        self.assertEqual(reports, [{"kind": "camera", "selected": 2, "shifted": 2, "touched": 2}])

    def test_negative_shift(self):
        m, _ = edit(camera_motion(), [Target("camera")], (100, 200), shift=-50)
        self.assertEqual(sorted(frames(m.cameras)), [0, 50, 150])

    def test_below_zero_is_an_error_and_nothing_moves(self):
        m = camera_motion()
        with self.assertRaises(ValueError) as ctx:
            motion_edit.apply(m, [Target("camera")], Operations(shift=-10), (0, 100))
        self.assertIn("-10", str(ctx.exception))
        self.assertEqual(frames(m.cameras), [0, 100, 200])

    def test_landing_on_a_key_outside_the_range_needs_replace(self):
        with self.assertRaises(ValueError) as ctx:
            edit(camera_motion(), [Target("camera")], (0, 0), shift=100)
        self.assertIn("100", str(ctx.exception))
        self.assertIn("--replace", str(ctx.exception))
        m, reports = edit(camera_motion(), [Target("camera")], (0, 0), shift=100, replace=True)
        self.assertEqual(sorted(frames(m.cameras)), [100, 200])
        self.assertEqual(by_frame(m.cameras)[100].distance, -45.0)       # the moved key, not the old one
        self.assertEqual(reports[0]["replaced"], 1)
        self.assertEqual(reports[0]["touched"], 2)

    def test_keys_of_the_range_may_move_over_each_other(self):
        m, _ = edit(model_motion(), [Target("bone", "センター")], (0, 30), shift=10)
        self.assertEqual(sorted(frames(motion_edit.keys_of(m, Target("bone", "センター")))), [10, 20, 30, 40])
        self.assertEqual(by_frame(motion_edit.keys_of(m, Target("bone", "センター")))[20].position, (0.0, 1.0, 0.0))

    def test_same_frames_of_another_bone_are_not_in_the_way(self):
        # センター 10 -> 20 collides with センター 20 only; 右腕 has a key at 20 too and keeps it
        with self.assertRaises(ValueError):
            edit(model_motion(), [Target("bone", "センター")], (10, 10), shift=10)
        m, _ = edit(model_motion(), [Target("bone", "センター")], (10, 10), shift=10, replace=True)
        self.assertEqual(sorted(frames(motion_edit.keys_of(m, Target("bone", "センター")))), [0, 20, 30])
        self.assertEqual(by_frame(motion_edit.keys_of(m, Target("bone", "センター")))[20].position, (0.0, 1.0, 0.0))
        self.assertEqual(frames(motion_edit.keys_of(m, Target("bone", "右腕"))), [0, 20])

    def test_empty_range_touches_nothing(self):
        m, reports = edit(camera_motion(), [Target("camera")], (101, 199), shift=5)
        self.assertEqual(frames(m.cameras), [0, 100, 200])
        self.assertEqual(reports[0]["touched"], 0)


class DeleteTest(unittest.TestCase):
    def test_range_is_deleted(self):
        m, reports = edit(camera_motion(), [Target("camera")], (100, 200), delete=True)
        self.assertEqual(frames(m.cameras), [0])
        self.assertEqual(reports, [{"kind": "camera", "selected": 2, "deleted": 2, "touched": 2}])

    def test_only_the_named_bone(self):
        m, _ = edit(model_motion(), [Target("bone", "センター")], None, delete=True)
        self.assertEqual([(k.name, k.frame) for k in m.bones], [("右腕", 0), ("右腕", 20)])
        self.assertEqual(len(m.morphs), 3)

    def test_empty_range(self):
        m, reports = edit(camera_motion(), [Target("camera")], (300, 400), delete=True)
        self.assertEqual(frames(m.cameras), [0, 100, 200])
        self.assertEqual(reports[0]["deleted"], 0)


class CopyTest(unittest.TestCase):
    def test_copies_start_at_the_given_frame(self):
        m, reports = edit(camera_motion(), [Target("camera")], (0, 100), copy_to=300)
        self.assertEqual(sorted(frames(m.cameras)), [0, 100, 200, 300, 400])
        keys = by_frame(m.cameras)
        self.assertEqual((keys[300].distance, keys[400].distance, keys[400].fov), (-45.0, -60.0, 40))
        self.assertEqual(keys[400].interpolation, keys[100].interpolation)
        self.assertEqual(reports, [{"kind": "camera", "selected": 2, "copied": 2, "touched": 4}])

    def test_copies_are_separate_objects(self):
        m = camera_motion()
        motion_edit.apply(m, [Target("camera")], Operations(copy_to=300), (0, 0))
        m.cameras[-1].fov = 99
        self.assertEqual(m.cameras[0].fov, 30)

    def test_landing_on_existing_keys_needs_replace(self):
        with self.assertRaises(ValueError) as ctx:
            edit(camera_motion(), [Target("camera")], (0, 0), copy_to=200)
        self.assertIn("200", str(ctx.exception))
        m, reports = edit(camera_motion(), [Target("camera")], (0, 0), copy_to=200, replace=True)
        self.assertEqual(sorted(frames(m.cameras)), [0, 100, 200])
        self.assertEqual(by_frame(m.cameras)[200].distance, -45.0)
        self.assertEqual((reports[0]["copied"], reports[0]["replaced"]), (1, 1))

    def test_a_copy_may_overlap_its_source_with_replace(self):
        with self.assertRaises(ValueError):
            edit(camera_motion(), [Target("camera")], (0, 200), copy_to=100)
        m, reports = edit(camera_motion(), [Target("camera")], (0, 200), copy_to=100, replace=True)
        self.assertEqual(sorted(frames(m.cameras)), [0, 100, 200, 300])
        keys = by_frame(m.cameras)
        self.assertEqual([keys[f].distance for f in (0, 100, 200, 300)], [-45.0, -45.0, -60.0, -30.0])
        self.assertEqual((reports[0]["copied"], reports[0]["replaced"], reports[0]["touched"]), (3, 2, 6))

    def test_only_the_named_bone_is_copied(self):
        m, _ = edit(model_motion(), [Target("bone", "センター")], (0, 10), copy_to=100)
        self.assertEqual(sorted(frames(motion_edit.keys_of(m, Target("bone", "センター")))), [0, 10, 20, 30, 100, 110])
        self.assertEqual(frames(motion_edit.keys_of(m, Target("bone", "右腕"))), [0, 20])
        self.assertEqual(by_frame(motion_edit.keys_of(m, Target("bone", "センター")))[110].position, (0.0, 1.0, 0.0))

    def test_empty_selection_copies_nothing(self):
        m, reports = edit(camera_motion(), [Target("camera")], (300, 400), copy_to=0)
        self.assertEqual(frames(m.cameras), [0, 100, 200])
        self.assertEqual(reports[0]["copied"], 0)


class CameraValuesTest(unittest.TestCase):
    def test_distance_scale_keeps_the_sign_of_the_file(self):
        m, reports = edit(camera_motion(), [Target("camera")], (0, 100), distance_scale=0.6)
        self.assertEqual([round(k.distance, 6) for k in m.cameras], [-27.0, -36.0, -30.0])
        self.assertEqual(motion_edit.list_keys(m, Target("camera"))["keys"][0]["distance"], 27.0)
        self.assertEqual(reports[0]["changed"], 2)

    def test_distance_add_is_in_window_terms(self):
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), distance_add=10)
        self.assertEqual(m.cameras[0].distance, -55.0)
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), distance_scale=2, distance_add=5)
        self.assertEqual(m.cameras[0].distance, -95.0)                  # scale first, then add

    def test_position_fov_and_their_order(self):
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), pos_add=(1, 2, 3))
        self.assertEqual(m.cameras[0].position, (1.0, 12.0, 3.0))
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), fov_set=50, fov_add=-10)
        self.assertEqual(m.cameras[0].fov, 40)                          # set first, then add
        with self.assertRaises(ValueError):
            edit(camera_motion(), [Target("camera")], (0, 0), fov_add=-30)
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), fov_add=-29)
        self.assertEqual(m.cameras[0].fov, 1)

    def test_only_the_range(self):
        m, _ = edit(camera_motion(), [Target("camera")], (100, 100), fov_set=5)
        self.assertEqual([k.fov for k in m.cameras], [30, 5, 30])

    def test_distance_clamp_bounds_the_magnitude_and_keeps_the_sign(self):
        # the file holds -45, -60, -30: |distance| into 35..50 gives -45, -50, -35
        m, reports = edit(camera_motion(), [Target("camera")], None, distance_clamp=(35, 50))
        self.assertEqual([k.distance for k in m.cameras], [-45.0, -50.0, -35.0])
        self.assertEqual(reports[0]["changed"], 3)
        # a positive (camera on the other side) and a zero distance
        odd = vmd.Motion.for_camera(cameras=[camera(0, 80.0), camera(1, 0.0), camera(2, -0.0)])
        m, _ = edit(odd, [Target("camera")], None, distance_clamp=(10, 60))
        self.assertEqual([k.distance for k in m.cameras], [60.0, -10.0, -10.0])
        m, _ = edit(camera_motion(), [Target("camera")], (0, 100), distance_clamp=(0, 60))
        self.assertEqual([k.distance for k in m.cameras], [-45.0, -60.0, -30.0])

    def test_distance_clamp_comes_after_scale_and_add(self):
        m, _ = edit(camera_motion(), [Target("camera")], (0, 0), distance_scale=2, distance_add=5, distance_clamp=(0, 80))
        self.assertEqual(m.cameras[0].distance, -80.0)                 # 45 -> 90 -> 95 -> 80
        for bad in ((-1, 10), (20, 10), (10,), (1, 2, 3)):
            with self.assertRaises(ValueError, msg=bad):
                motion_edit.check_operations(Operations(distance_clamp=bad), [Target("camera")])
        with self.assertRaises(ValueError):
            motion_edit.check_operations(Operations(distance_clamp=(0, 10)), [Target("bone", "x")])


class BoneValuesTest(unittest.TestCase):
    def test_position_add(self):
        m, _ = edit(model_motion(), [Target("bone", "センター")], (10, 20), pos_add=(1, 0, -1))
        keys = by_frame(motion_edit.keys_of(m, Target("bone", "センター")))
        self.assertEqual((keys[0].position, keys[10].position, keys[20].position, keys[30].position),
                         ((0.0, 0.0, 0.0), (1.0, 1.0, -1.0), (1.0, 2.0, -1.0), (0.0, 3.0, 0.0)))

    def test_rotation_add_in_window_degrees(self):
        m, _ = edit(model_motion(), [Target("bone", "右腕")], None, rot_add=(0, 0, 10))
        rots = [motion_edit.key_json(Target("bone", "右腕"), k)["rot"] for k in motion_edit.keys_of(m, Target("bone", "右腕"))]
        self.assertEqual(rots, [[0.0, 0.0, 40.0], [0.0, 0.0, 55.0]])
        self.assertEqual(motion_edit.key_json(Target("bone", "センター"), m.bones[0])["rot"], [0.0, 0.0, 0.0])

    def test_composition_order_is_key_first_then_the_addition(self):
        # the addition turns about the bone's own axes: v -> q_key (q_add v)
        key = bone("a", 0, rot=mathutil.ui_to_quat(90, 0, 0))
        m = vmd.Motion(model_name="m", bones=[key])
        motion_edit.apply(m, [Target("bone", "a")], Operations(rot_add=(0, 90, 0)))
        got = m.bones[0].rotation
        q_key, q_add = mathutil.ui_to_quat(90, 0, 0), mathutil.ui_to_quat(0, 90, 0)
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.3, -0.5, 0.8)):
            want = rotate(q_key, rotate(q_add, v))
            for g, w in zip(rotate(got, v), want):
                self.assertAlmostEqual(g, w, places=6)
        self.assertAlmostEqual(sum(c * c for c in got), 1.0, places=9)


class MorphValuesTest(unittest.TestCase):
    def test_scale_and_set(self):
        m, _ = edit(model_motion(), [Target("morph", "まばたき")], None, weight_scale=0.5)
        self.assertEqual([(k.name, k.weight) for k in m.morphs], [("まばたき", 0.5), ("まばたき", 0.0), ("あ", 0.5)])
        m, _ = edit(model_motion(), [Target("morph", "あ")], (5, 5), weight_set=0.25)
        self.assertEqual(m.morphs[2].weight, 0.25)
        m, _ = edit(model_motion(), [Target("morph", "あ")], None, weight_set=1.0, weight_scale=0.5)
        self.assertEqual(m.morphs[2].weight, 0.5)                       # set first, then scale


class InterpTest(unittest.TestCase):
    def test_camera_curve_on_the_range(self):
        m, reports = edit(camera_motion(), [Target("camera")], (0, 100), interp=(64, 0, 64, 127))
        want = vmd.camera_interpolation((64, 0, 64, 127))
        self.assertEqual([k.interpolation for k in m.cameras], [want, want, vmd.DEFAULT_CAMERA_INTERPOLATION])
        self.assertEqual(reports[0]["interp"], 2)

    def test_bone_curve_keeps_bytes_2_and_3_of_the_key(self):
        old = bytearray(vmd.DEFAULT_BONE_INTERPOLATION)
        old[2], old[3] = 99, 15
        m = vmd.Motion(model_name="m", bones=[bone("a", 0, interp=bytes(old)), bone("a", 10)])
        m, _ = edit(m, [Target("bone", "a")], None, interp=(64, 0, 64, 127))
        self.assertEqual(m.bones[0].interpolation[2:4], bytes([99, 15]))
        self.assertEqual(m.bones[1].interpolation[2:4], bytes([0, 0]))
        for k in m.bones:
            self.assertEqual(vmd.bone_curves(k.interpolation), {c: (64, 0, 64, 127) for c in vmd.BONE_CHANNELS})

    def test_morph_and_light_have_no_curve(self):
        for target in (Target("morph", "あ"), Target("light")):
            with self.assertRaises(ValueError):
                motion_edit.check_operations(Operations(interp=(20, 20, 107, 107)), [target])


class OrderTest(unittest.TestCase):
    def test_shift_then_copy_then_values_then_interp(self):
        self.assertEqual(motion_edit.ORDER, ("shift", "copy", "values", "interp"))
        m, reports = edit(camera_motion(), [Target("camera")], (0, 100), shift=10, copy_to=500, distance_scale=0.5,
                          interp=(64, 0, 64, 127))
        keys = by_frame(m.cameras)
        self.assertEqual(sorted(keys), [10, 110, 200, 500, 600])
        self.assertEqual([keys[f].distance for f in (10, 110, 200, 500, 600)], [-22.5, -30.0, -30.0, -22.5, -30.0])
        want = vmd.camera_interpolation((64, 0, 64, 127))
        self.assertEqual([keys[f].interpolation == want for f in (10, 110, 200, 500, 600)], [True, True, False, True, True])
        self.assertEqual(reports, [{"kind": "camera", "selected": 2, "shifted": 2, "copied": 2, "changed": 4, "interp": 4,
                                    "touched": 4}])

    def test_several_targets_in_one_call(self):
        m, reports = edit(model_motion(), [Target("bone", "センター"), Target("bone", "右腕")], (0, 0), shift=100)
        self.assertEqual(sorted((k.name, k.frame) for k in m.bones),
                         [("センター", 10), ("センター", 20), ("センター", 30), ("センター", 100), ("右腕", 20), ("右腕", 100)])
        self.assertEqual([r["name"] for r in reports], ["センター", "右腕"])
        m, _ = edit(camera_motion(), [Target("camera"), Target("light")], (0, 0), shift=5)
        self.assertEqual((sorted(frames(m.cameras)), frames(m.lights)), ([5, 100, 200], [5, 150]))


class CameraUiTest(unittest.TestCase):
    def test_round_trip_through_the_window_values(self):
        key = camera(7, -33.5, pos=(1, 2, 3), rot=(0.1, -0.2, 0.3), fov=45, perspective=False)
        ui = motion_edit.camera_to_ui(key)
        back = motion_edit.camera_key_from_ui(ui, curve=(64, 0, 64, 127), frame=7)
        self.assertEqual((back.frame, back.distance, back.position, back.fov, back.perspective), (7, -33.5, (1.0, 2.0, 3.0), 45, False))
        for g, w in zip(back.rotation, key.rotation):
            self.assertAlmostEqual(g, w, places=5)        # the window values carry 4 decimals of a degree
        self.assertEqual(back.interpolation, vmd.camera_interpolation((64, 0, 64, 127)))
        self.assertEqual(motion_edit.camera_key_from_ui(ui).interpolation, vmd.DEFAULT_CAMERA_INTERPOLATION)
        self.assertEqual(ui["rot"][0], round(math.degrees(-0.1), 4))


class EditFileTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.src = os.path.join(self.folder, "in.vmd")
        write(self.src, camera_motion())
        with open(self.src, "rb") as f:
            self.original = f.read()

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_writes_out_and_reports_what_was_read_back(self):
        dst = os.path.join(self.folder, "sub", "out.vmd")
        result = motion_edit.edit_file(self.src, dst, [Target("camera")], Operations(distance_scale=0.5), (0, 100))
        self.assertEqual((result["in"], result["out"], result["range"]), (os.path.abspath(self.src), os.path.abspath(dst), [0, 100]))
        self.assertEqual(result["order"], ["shift", "copy", "values", "interp"])
        self.assertEqual(result["targets"], [{"kind": "camera", "selected": 2, "changed": 2, "touched": 2}])
        self.assertEqual(result["counts"], {"bones": 0, "morphs": 0, "cameras": 3, "lights": 2, "shadows": 0, "show_ik": 0})
        self.assertEqual([k.distance for k in vmd.load(dst).cameras], [-22.5, -30.0, -30.0])
        self.assertEqual(self.read(self.src), self.original)
        self.assertEqual(sorted(os.listdir(os.path.dirname(dst))), ["out.vmd"])

    def test_delete_reports_its_order(self):
        dst = os.path.join(self.folder, "out.vmd")
        result = motion_edit.edit_file(self.src, dst, [Target("light")], Operations(delete=True))
        self.assertEqual((result["order"], result["counts"]["lights"]), (["delete"], 0))

    def test_errors_come_before_anything_is_written(self):
        dst = os.path.join(self.folder, "out.vmd")
        for specs, ops in (([], Operations(shift=1)), ([Target("camera")], Operations()),
                           ([Target("bone", "x")], Operations(shift=1)), ([Target("camera")], Operations(shift=-1))):
            with self.assertRaises(ValueError, msg=(specs, ops)):
                motion_edit.edit_file(self.src, dst, specs, ops)
            self.assertFalse(os.path.exists(dst))
        with self.assertRaises(ValueError):
            motion_edit.edit_file(self.src, dst, [Target("camera")], Operations(shift=1), (5, None))

    @unittest.skipUnless(app is not None, "needs Windows (the output is kept aside with app.keeping_the_old_file)")
    def test_same_path_edits_in_place_and_leaves_no_copy_behind(self):
        result = motion_edit.edit_file(self.src, self.src, [Target("camera")], Operations(shift=1), (0, 0))
        self.assertEqual(frames(vmd.load(self.src).cameras), [1, 100, 200])
        self.assertEqual(result["counts"]["cameras"], 3)
        self.assertEqual(os.listdir(self.folder), ["in.vmd"])

    @unittest.skipUnless(app is not None, "needs Windows")
    def test_an_existing_output_is_replaced_and_a_folder_is_refused(self):
        dst = os.path.join(self.folder, "out.vmd")
        write(dst, model_motion())
        motion_edit.edit_file(self.src, dst, [Target("camera")], Operations(shift=1), (0, 0))
        self.assertEqual(frames(vmd.load(dst).cameras), [1, 100, 200])
        self.assertEqual(sorted(os.listdir(self.folder)), ["in.vmd", "out.vmd"])
        with self.assertRaises(Exception):
            motion_edit.edit_file(self.src, self.folder, [Target("camera")], Operations(shift=1))
        self.assertEqual(self.read(self.src), self.original)


if __name__ == "__main__":
    unittest.main()
