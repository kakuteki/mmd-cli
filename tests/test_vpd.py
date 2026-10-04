import unittest

from mmd_cli.formats import vpd

# the layout MMD itself writes (tabs, CRLF, comments, "Quatanion" spelling included)
SAMPLE = (
    "Vocaloid Pose Data file\r\n"
    "\r\n"
    "miku.osm;\t\t// 親ファイル名\r\n"
    "2;\t\t\t\t// 総ポーズボーン数\r\n"
    "\r\n"
    "Bone0{右親指１\r\n"
    "  -0.000000,0.000000,0.000000;\t\t\t\t// trans x,y,z\r\n"
    "  0.071834,0.539167,0.266196,0.795784;\t\t// Quatanion x,y,z,w\r\n"
    "}\r\n"
    "\r\n"
    "Bone1{センター\r\n"
    "  1.500000,-2.000000,3.250000;\t\t\t\t// trans x,y,z\r\n"
    "  0.000000,0.000000,0.000000,1.000000;\t\t// Quatanion x,y,z,w\r\n"
    "}\r\n"
    "\r\n"
).encode("cp932")


class LoadsTest(unittest.TestCase):
    def test_reads_what_mmd_writes(self):
        pose = vpd.loads(SAMPLE)
        self.assertEqual(pose.model_file, "miku.osm")
        self.assertEqual([b.name for b in pose.bones], ["右親指１", "センター"])
        self.assertEqual(pose.bones[0].rotation, (0.071834, 0.539167, 0.266196, 0.795784))
        self.assertEqual(pose.bones[1].position, (1.5, -2.0, 3.25))

    def test_model_file_containing_the_word_bone(self):
        # the parent file name comes from the lines before the first "BoneN{" block, not before the word "Bone"
        pose = vpd.loads(SAMPLE.replace(b"miku.osm", b"MyBone.osm"))
        self.assertEqual(pose.model_file, "MyBone.osm")
        self.assertEqual([b.name for b in pose.bones], ["右親指１", "センター"])

    def test_wrong_header_is_rejected(self):
        with self.assertRaises(ValueError):
            vpd.loads(b"hello\r\n")

    def test_bone_block_without_rotation_is_rejected(self):
        broken = SAMPLE.replace(b"  0.000000,0.000000,0.000000,1.000000;", b"")
        with self.assertRaises(ValueError):
            vpd.loads(broken)


class DumpsTest(unittest.TestCase):
    def test_roundtrip(self):
        pose = vpd.Pose(model_file="x.osm", bones=[
            vpd.PoseBone("左腕", (0.0, 0.0, 0.0), (0.0, 0.0, -0.382683, 0.92388)),
            vpd.PoseBone("センター", (0.0, 3.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        ])
        back = vpd.loads(vpd.dumps(pose))
        self.assertEqual(back.model_file, "x.osm")
        self.assertEqual([(b.name, b.position, b.rotation) for b in back.bones],
                         [("左腕", (0.0, 0.0, 0.0), (0.0, 0.0, -0.382683, 0.92388)),
                          ("センター", (0.0, 3.0, 0.0), (0.0, 0.0, 0.0, 1.0))])

    def test_output_is_cp932_text_with_crlf_and_the_bone_count(self):
        data = vpd.dumps(vpd.Pose(model_file="x.osm", bones=[vpd.PoseBone("頭", (0, 0, 0), (0, 0, 0, 1))]))
        text = data.decode("cp932")
        self.assertTrue(text.startswith("Vocaloid Pose Data file\r\n"))
        self.assertIn("\r\n1;", text)
        self.assertIn("Bone0{頭\r\n", text)
        self.assertNotIn("\n", text.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()
