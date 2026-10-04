import struct
import unittest

from mmd_cli.formats import vmd


class DumpsTest(unittest.TestCase):
    def test_header_and_empty_sections(self):
        data = vmd.dumps(vmd.Motion(model_name="abc"))
        self.assertEqual(data[:25], b"Vocaloid Motion Data 0002")
        self.assertEqual(data[25:30], b"\x00" * 5)
        self.assertEqual(data[30:33], b"abc")
        self.assertEqual(data[33:50], b"\x00" * 17)
        # six empty sections: bone, morph, camera, light, self shadow, show/ik
        self.assertEqual(data[50:], struct.pack("<6I", 0, 0, 0, 0, 0, 0))

    def test_bone_key_layout(self):
        key = vmd.BoneKey("センター", 12, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0))
        data = vmd.dumps(vmd.Motion(model_name="m", bones=[key]))
        self.assertEqual(struct.unpack_from("<I", data, 50)[0], 1)
        rec = data[54:54 + 111]
        self.assertEqual(rec[:15], "センター".encode("cp932") + b"\x00" * 7)
        self.assertEqual(struct.unpack_from("<I3f4f", rec, 15), (12, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0))
        self.assertEqual(len(data), 50 + 4 + 111 + 5 * 4)

    def test_default_interpolation_is_the_one_mmd_writes(self):
        key = vmd.BoneKey("a", 0, (0, 0, 0), (0, 0, 0, 1))
        data = vmd.dumps(vmd.Motion(model_name="m", bones=[key]))
        interp = data[54 + 47:54 + 111]
        self.assertEqual(interp[:16], bytes([20, 20, 0, 0, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107]))
        self.assertEqual(interp[16:32], bytes([20] * 7 + [107] * 8 + [0]))
        self.assertEqual(len(interp), 64)

    def test_morph_key_layout(self):
        data = vmd.dumps(vmd.Motion(model_name="m", morphs=[vmd.MorphKey("あ", 7, 0.5)]))
        self.assertEqual(struct.unpack_from("<II", data, 50), (0, 1))
        rec = data[58:58 + 23]
        self.assertEqual(rec[:15], "あ".encode("cp932") + b"\x00" * 13)
        self.assertEqual(struct.unpack_from("<If", rec, 15), (7, 0.5))

    def test_name_longer_than_the_field_is_rejected(self):
        key = vmd.BoneKey("あいうえおかきく", 0, (0, 0, 0), (0, 0, 0, 1))  # 16 bytes in cp932
        with self.assertRaises(ValueError):
            vmd.dumps(vmd.Motion(model_name="m", bones=[key]))

    def test_long_model_name_is_truncated_on_a_character_boundary(self):
        data = vmd.dumps(vmd.Motion(model_name="あ" * 11))  # 22 bytes in cp932, field is 20
        self.assertEqual(data[30:50], ("あ" * 10).encode("cp932"))

    def test_name_exactly_15_bytes_is_accepted(self):
        name = "あいうえおかき" + "x"                       # 14 + 1 = 15 bytes in cp932
        data = vmd.dumps(vmd.Motion(model_name="m", bones=[vmd.BoneKey(name, 0, (0, 0, 0), (0, 0, 0, 1))]))
        self.assertEqual(data[54:69], name.encode("cp932"))

    def test_unencodable_name_is_a_value_error(self):
        # U+2665 has no cp932 code; the codec's UnicodeEncodeError must not reach the user raw
        for motion in (vmd.Motion(model_name="m", bones=[vmd.BoneKey("♥", 0, (0, 0, 0), (0, 0, 0, 1))]),
                       vmd.Motion(model_name="m", morphs=[vmd.MorphKey("♥", 0, 1.0)]),
                       vmd.Motion.for_camera(shadows=[], cameras=[])):
            if motion.is_camera:
                motion.show_iks = [vmd.ShowIkKey(0, True, [("♥", True)])]
            with self.assertRaises(ValueError) as ctx:
                vmd.dumps(motion)
            self.assertNotIsInstance(ctx.exception, UnicodeEncodeError)
            self.assertIn("cp932", str(ctx.exception))
            self.assertIn("♥", str(ctx.exception))

    def test_negative_frame_is_a_value_error(self):
        cases = (("bone", vmd.Motion(model_name="m", bones=[vmd.BoneKey("a", -1, (0, 0, 0), (0, 0, 0, 1))])),
                 ("morph", vmd.Motion(model_name="m", morphs=[vmd.MorphKey("a", -1, 1.0)])),
                 ("camera", vmd.Motion.for_camera(cameras=[vmd.CameraKey(-1, -30.0, (0, 0, 0), (0, 0, 0))])),
                 ("light", vmd.Motion.for_camera(lights=[vmd.LightKey(-1, (1, 1, 1), (0, -1, 0))])))
        for what, motion in cases:
            with self.assertRaises(ValueError) as ctx:
                vmd.dumps(motion)
            self.assertIn(what, str(ctx.exception))
            self.assertIn("frame -1", str(ctx.exception))

    def test_model_name_with_replacement_character_is_written(self):
        # a pmm model name that did not decode cleanly carries U+FFFD; the name is only the label MMD
        # compares before asking "load this motion?", so it is written with '?' instead of failing
        data = vmd.dumps(vmd.Motion(model_name="�♥abc"))
        self.assertEqual(data[30:50], b"??abc".ljust(20, b"\x00"))

    def test_camera_motion_uses_the_camera_model_name(self):
        key = vmd.CameraKey(frame=5, distance=-30.0, position=(1.0, 2.0, 3.0), rotation=(0.1, 0.2, 0.3), fov=45)
        data = vmd.dumps(vmd.Motion.for_camera(cameras=[key]))
        self.assertEqual(data[30:42], "カメラ・照明".encode("cp932"))
        self.assertEqual(struct.unpack_from("<III", data, 50), (0, 0, 1))
        rec = data[62:62 + 61]
        self.assertEqual(struct.unpack_from("<If3f3f", rec, 0)[:2], (5, -30.0))
        self.assertEqual(struct.unpack_from("<IB", rec, 56), (45, 0))


class LoadsTest(unittest.TestCase):
    def test_roundtrip(self):
        src = vmd.Motion(
            model_name="初音ミク",
            bones=[vmd.BoneKey("センター", 10, (0.0, 5.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
                   vmd.BoneKey("右腕", 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.5, 0.5))],
            morphs=[vmd.MorphKey("まばたき", 3, 1.0)],
        )
        back = vmd.loads(vmd.dumps(src))
        self.assertEqual(back.model_name, "初音ミク")
        self.assertEqual([(k.name, k.frame, k.position, k.rotation) for k in back.bones],
                         [("センター", 10, (0.0, 5.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
                          ("右腕", 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.5, 0.5))])
        self.assertEqual([(k.name, k.frame, k.weight) for k in back.morphs], [("まばたき", 3, 1.0)])

    def test_camera_roundtrip_keeps_the_stored_values(self):
        key = vmd.CameraKey(frame=5, distance=-30.0, position=(1.0, 2.0, 3.0), rotation=(0.25, 0.5, 0.75), fov=45)
        back = vmd.loads(vmd.dumps(vmd.Motion.for_camera(cameras=[key])))
        self.assertTrue(back.is_camera)
        self.assertEqual(len(back.cameras), 1)
        got = back.cameras[0]
        self.assertEqual((got.frame, got.distance, got.position, got.rotation, got.fov, got.perspective),
                         (5, -30.0, (1.0, 2.0, 3.0), (0.25, 0.5, 0.75), 45, True))

    def test_roundtrip_of_light_shadow_and_show_ik_sections(self):
        src = vmd.Motion.for_camera(
            lights=[vmd.LightKey(frame=2, rgb=(0.5, 0.25, 0.125), direction=(-0.5, -1.0, 0.5))],
            shadows=[vmd.ShadowKey(frame=3, mode=1, distance=0.015625)],
        )
        src.show_iks = [vmd.ShowIkKey(frame=4, visible=False, iks=[("左足ＩＫ", True), ("右足ＩＫ", False)])]
        back = vmd.loads(vmd.dumps(src))
        self.assertEqual([(k.frame, k.rgb, k.direction) for k in back.lights],
                         [(2, (0.5, 0.25, 0.125), (-0.5, -1.0, 0.5))])
        self.assertEqual([(k.frame, k.mode, k.distance) for k in back.shadows], [(3, 1, 0.015625)])
        self.assertEqual([(k.frame, k.visible, k.iks) for k in back.show_iks],
                         [(4, False, [("左足ＩＫ", True), ("右足ＩＫ", False)])])

    def test_files_that_end_after_the_morph_section_are_accepted(self):
        data = vmd.dumps(vmd.Motion(model_name="m", morphs=[vmd.MorphKey("あ", 1, 1.0)]))
        short = data[:-16]  # old writers stop after the morph section
        self.assertEqual(len(vmd.loads(short).morphs), 1)

    def test_wrong_magic_is_rejected(self):
        with self.assertRaises(ValueError):
            vmd.loads(b"not a vmd file" + b"\x00" * 60)

    def test_truncated_bone_section_is_rejected(self):
        data = vmd.dumps(vmd.Motion(model_name="m", bones=[vmd.BoneKey("a", 0, (0, 0, 0), (0, 0, 0, 1))]))
        with self.assertRaises(ValueError):
            vmd.loads(data[:100])


def shifted_rows(first):
    """the 64 bytes MMD writes for a bone key whose canonical 16 bytes are `first`: rows 2-4 are row 1
    shifted left by one byte each (padded with 0), and bytes 2 and 3 of row 1 are 0"""
    first = list(first)
    rows = [first[i:] + [0] * i for i in range(4)]
    rows[0][2] = rows[0][3] = 0
    return bytes(sum(rows, []))


class InterpolationLayoutTest(unittest.TestCase):
    """Where x1 y1 x2 y2 of each channel live in the 64 (bone) / 24 (camera) bytes.

    Measured on 2026-10-04: every bone key of two distributed dance motions (39,660 + 52,030 keys)
    has rows 2-4 equal to row 1 shifted by one byte per row, bytes 2 and 3 of row 1 are 0 in all of
    them even when the curve is not linear (so they are not part of the curve), and the curved keys
    read as four groups x1 / y1 / x2 / y2 of the four channels (64 64 64 20 | 0 0 0 20 | 64 64 64 107 |
    127 127 127 107 is the ease-in-out (64, 0)-(64, 127) on X Y Z and linear rotation).  A curved camera
    key reads 64 64 0 127 per channel, the same curve as x1 x2 y1 y2.  The channel order inside a group
    (X Y Z rotation; X Y Z rotation distance view angle) is the commonly documented one and could not be
    told apart from the data; it does not matter while every channel gets the same curve."""

    def test_linear_curve_builds_the_bytes_mmd_writes(self):
        self.assertEqual(vmd.bone_interpolation(vmd.LINEAR_CURVE), vmd.DEFAULT_BONE_INTERPOLATION)
        self.assertEqual(vmd.camera_interpolation(vmd.LINEAR_CURVE), vmd.DEFAULT_CAMERA_INTERPOLATION)
        self.assertEqual(vmd.LINEAR_CURVE, (20, 20, 107, 107))

    def test_bone_rows_are_x1_y1_x2_y2_groups_shifted_by_one_byte_per_row(self):
        data = vmd.bone_interpolation((64, 5, 100, 127))
        self.assertEqual(len(data), 64)
        self.assertEqual(data[:16], bytes([64, 64, 0, 0, 5, 5, 5, 5, 100, 100, 100, 100, 127, 127, 127, 127]))
        self.assertEqual(data[16:32], bytes([64, 64, 64, 5, 5, 5, 5, 100, 100, 100, 100, 127, 127, 127, 127, 0]))
        self.assertEqual(data[32:48], bytes([64, 64, 5, 5, 5, 5, 100, 100, 100, 100, 127, 127, 127, 127, 0, 0]))
        self.assertEqual(data[48:64], bytes([64, 5, 5, 5, 5, 100, 100, 100, 100, 127, 127, 127, 127, 0, 0, 0]))
        self.assertEqual(data, shifted_rows([64] * 4 + [5] * 4 + [100] * 4 + [127] * 4))

    def test_bone_curves_read_back_per_channel(self):
        curves = vmd.bone_curves(vmd.bone_interpolation((64, 5, 100, 127)))
        self.assertEqual(curves, {"x": (64, 5, 100, 127), "y": (64, 5, 100, 127), "z": (64, 5, 100, 127),
                                  "rotation": (64, 5, 100, 127)})
        self.assertEqual(vmd.bone_curves(vmd.DEFAULT_BONE_INTERPOLATION), {c: (20, 20, 107, 107) for c in vmd.BONE_CHANNELS})

    def test_a_distributed_key_with_different_channels_is_read_from_the_intact_rows(self):
        # measured block: X Y Z ease-in-out, rotation linear; bytes 2 and 3 of row 1 are 0 in the file
        data = shifted_rows([64, 64, 64, 20, 0, 0, 0, 20, 64, 64, 64, 107, 127, 127, 127, 107])
        self.assertEqual(data[2:4], b"\x00\x00")
        self.assertEqual(vmd.bone_curves(data), {"x": (64, 0, 64, 127), "y": (64, 0, 64, 127), "z": (64, 0, 64, 127),
                                                 "rotation": (20, 20, 107, 107)})

    def test_keep_preserves_bytes_2_and_3_of_the_first_row(self):
        # MMD writes something other than the curve there (0 on every key seen; said to be the physics
        # flag), so a curve written over an existing key leaves the two bytes alone
        old = bytes(range(64))
        data = vmd.bone_interpolation((64, 5, 100, 127), keep=old)
        self.assertEqual(data[2:4], bytes([2, 3]))
        self.assertEqual(data[:2] + data[4:], vmd.bone_interpolation((64, 5, 100, 127))[:2] + vmd.bone_interpolation((64, 5, 100, 127))[4:])
        self.assertEqual(vmd.bone_curves(data)["z"], (64, 5, 100, 127))

    def test_camera_channels_are_x1_x2_y1_y2_each(self):
        data = vmd.camera_interpolation((64, 0, 64, 127))
        self.assertEqual(data, bytes([64, 64, 0, 127] * 6))
        self.assertEqual(vmd.camera_curves(data), {c: (64, 0, 64, 127) for c in vmd.CAMERA_CHANNELS})
        self.assertEqual(vmd.CAMERA_CHANNELS, ("x", "y", "z", "rotation", "distance", "fov"))
        self.assertEqual(vmd.BONE_CHANNELS, ("x", "y", "z", "rotation"))

    def test_curve_values_must_be_whole_numbers_from_0_to_127(self):
        for bad in ((128, 0, 0, 0), (0, -1, 0, 0), (20, 20, 107), (20, 20, 107, 107, 1), (20.5, 20, 107, 107), ("20", 20, 107, 107)):
            with self.assertRaises(ValueError, msg=repr(bad)):
                vmd.bone_interpolation(bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                vmd.camera_interpolation(bad)
        self.assertEqual(vmd.check_curve((0, 127.0, 64, 1)), (0, 127, 64, 1))

    def test_keys_built_with_a_curve_survive_the_file(self):
        bone = vmd.BoneKey("a", 3, (0, 0, 0), (0, 0, 0, 1), vmd.bone_interpolation((10, 20, 30, 40)))
        cam = vmd.CameraKey(3, -30.0, (0, 0, 0), (0, 0, 0), interpolation=vmd.camera_interpolation((10, 20, 30, 40)))
        back = vmd.loads(vmd.dumps(vmd.Motion(model_name="m", bones=[bone])))
        self.assertEqual(vmd.bone_curves(back.bones[0].interpolation)["rotation"], (10, 20, 30, 40))
        back = vmd.loads(vmd.dumps(vmd.Motion.for_camera(cameras=[cam])))
        self.assertEqual(vmd.camera_curves(back.cameras[0].interpolation)["fov"], (10, 20, 30, 40))


class CutNameTest(unittest.TestCase):
    def test_a_name_cut_inside_a_double_byte_character_survives_a_round_trip(self):
        # review 4 (2.2): MMD cuts long names at 15 bytes, sometimes in the middle of a character; such a file
        # must still be written back unchanged (editing only the camera of a dance is a common wish)
        name = "あいうえおかき".encode("cp932") + b"\x82"            # 14 bytes and the first byte of く
        self.assertEqual(len(name), 15)
        bone = vmd._BONE.pack(name, 3, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, vmd.DEFAULT_BONE_INTERPOLATION)
        data = vmd.MAGIC.ljust(30, b"\x00") + b"m".ljust(20, b"\x00") + struct.pack("<I", 1) + bone + struct.pack("<I", 0) * 5
        m = vmd.loads(data)
        self.assertIn("\ufffd", m.bones[0].name)
        self.assertEqual(vmd.dumps(m), data)
        m.bones[0].frame = 7                                           # a changed key keeps its bytes too
        self.assertEqual(vmd.loads(vmd.dumps(m)).bones[0].frame, 7)

    def test_a_renamed_key_is_written_from_its_new_name(self):
        m = vmd.loads(vmd.dumps(vmd.Motion(model_name="m", bones=[vmd.BoneKey("センター", 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))])))
        m.bones[0].name = "右腕"
        self.assertEqual(vmd.loads(vmd.dumps(m)).bones[0].name, "右腕")


if __name__ == "__main__":
    unittest.main()
