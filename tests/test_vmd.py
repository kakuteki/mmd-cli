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


if __name__ == "__main__":
    unittest.main()
