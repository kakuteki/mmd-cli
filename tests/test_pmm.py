import os
import unittest

from mmd_cli.formats import pmm

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "scene_v932.pmm")
# The fixture was saved by MMD v9.32 from this scene (paths rewritten afterwards):
#   model 初音ミク.pmd, current frame 10
#   camera registered at frame 0: center (1.5, 12, -3.25), angle (10, 20, 5), distance 30, view angle 45
#   light registered at frame 0: rgb (200, 100, 50), direction (-0.2, -0.8, 0.3)
#   motion loaded at frame 10: センター@10 pos (0,5,0) / センター@30 pos (1,2,3) rot z 30deg / 右腕@10 rot z 45deg
#                              まばたき@10 = 1.0 / あ@15 = 0.5
#   accessory negi.x registered at frame 10: pos (1,2,3), rot (10,20,30), size 2, Tr 0.5
#   wave t1.wav


def load():
    with open(FIXTURE, "rb") as f:
        return pmm.loads(f.read())


class Close(unittest.TestCase):
    def assert_close(self, got, want, places=4):
        self.assertEqual(len(got), len(want), "%r vs %r" % (got, want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=places, msg="%r != %r" % (got, want))


class HeaderTest(Close):
    def test_version_and_view(self):
        p = load()
        self.assertEqual(p["version"], 2)
        self.assertEqual((p["view_width"], p["view_height"]), (640, 360))
        self.assertAlmostEqual(p["edit_view_angle"], 45.0)

    def test_current_frame_and_wave(self):
        p = load()
        self.assertEqual(p["frame"], 10)
        self.assertEqual(p["wave"], {"enabled": True, "path": "C:\\work\\t1.wav"})


class ModelTest(Close):
    def test_names_and_counts(self):
        m = load()["models"][0]
        self.assertEqual(m["name"], "初音ミク")
        self.assertEqual(m["name_en"], "Miku Hatsune")
        self.assertEqual(m["path"], "C:\\MMD\\UserFile\\Model\\初音ミク.pmd")
        self.assertEqual(len(m["bones"]), 122)
        self.assertEqual(m["bones"][0], "センター")
        self.assertEqual(m["bones"][48], "右腕")
        self.assertEqual(len(m["morphs"]), 16)
        self.assertEqual(m["last_frame"], 30)

    def test_bone_keys_know_their_bone(self):
        m = load()["models"][0]
        got = sorted((k["bone"], k["frame"]) for k in m["bone_keys"])
        self.assertEqual(got, [(0, 10), (0, 30), (48, 10)])
        k30 = [k for k in m["bone_keys"] if k["frame"] == 30][0]
        self.assert_close(k30["position"], (1.0, 2.0, 3.0))
        self.assert_close(k30["rotation"], (0.0, 0.0, 0.258819, 0.965926))

    def test_morph_keys_know_their_morph(self):
        m = load()["models"][0]
        got = sorted((m["morphs"][k["morph"]], k["frame"], round(k["weight"], 4)) for k in m["morph_keys"])
        self.assertEqual(got, [("あ", 15, 0.5), ("まばたき", 10, 1.0)])

    def test_every_bone_and_morph_has_an_initial_frame(self):
        m = load()["models"][0]
        self.assertEqual(len(m["bone_init"]), 122)
        self.assertEqual(len(m["morph_init"]), 16)
        self.assertEqual(m["bone_init"][0]["frame"], 0)

    def test_current_pose_is_the_pose_at_the_current_frame(self):
        m = load()["models"][0]
        self.assert_close(m["bone_current"][0]["position"], (0.0, 5.0, 0.0))
        self.assert_close(m["bone_current"][48]["rotation"], (0.0, 0.0, 0.382683, 0.92388))
        self.assertAlmostEqual(m["morph_current"][5], 1.0, places=4)       # まばたき
        self.assertAlmostEqual(m["morph_current"][9], 1.0 / 3.0, places=4)  # あ, interpolated towards 0.5@15


class CameraLightTest(Close):
    def test_camera_initial_frame_holds_the_registered_values(self):
        c = load()["camera"]["init"]
        self.assertAlmostEqual(c["distance"], -30.0, places=4)   # stored negated
        self.assert_close(c["position"], (1.5, 12.0, -3.25))
        self.assert_close(c["rotation"], (-0.174533, 0.349066, 0.087266))  # radians, x negated
        self.assertEqual(c["fov"], 45)
        self.assertEqual(load()["camera"]["keys"], [])

    def test_light_initial_frame(self):
        light = load()["light"]["init"]
        self.assert_close(light["rgb"], (200 / 256.0, 100 / 256.0, 50 / 256.0))
        self.assert_close(light["direction"], (-0.2, -0.8, 0.3))


class AccessoryTest(Close):
    def test_accessory_key_and_current_state(self):
        accs = load()["accessories"]
        self.assertEqual([a["name"] for a in accs], ["negi.x"])
        a = accs[0]
        self.assertEqual(a["path"], "C:\\MMD\\UserFile\\Accessory\\negi.x")
        self.assertEqual([k["frame"] for k in a["keys"]], [10])
        key = a["keys"][0]
        self.assert_close(key["position"], (1.0, 2.0, 3.0))
        self.assert_close(key["rotation"], (0.174533, 0.349066, 0.523599))
        self.assertAlmostEqual(key["scale"], 2.0)
        self.assertEqual((key["visible"], key["transparency_percent"]), (True, 50))
        cur = a["current"]
        self.assert_close(cur["position"], (1.0, 2.0, 3.0))
        self.assert_close(cur["rotation"], (0.174533, 0.349066, 0.523599))
        self.assertAlmostEqual(cur["scale"], 2.0)


class ErrorTest(unittest.TestCase):
    def test_version_1_files_are_rejected_with_a_clear_message(self):
        data = b"Polygon Movie maker 0001" + b"\x00" * 200
        with self.assertRaises(pmm.PmmFormatError) as ctx:
            pmm.loads(data)
        self.assertIn("0001", str(ctx.exception))

    def test_not_a_pmm(self):
        with self.assertRaises(pmm.PmmFormatError):
            pmm.loads(b"hello world" * 10)

    def test_truncated_file(self):
        with open(FIXTURE, "rb") as f:
            data = f.read()
        with self.assertRaises(pmm.PmmFormatError):
            pmm.loads(data[:5000])

    def test_trailing_bytes_mean_the_layout_was_misread(self):
        with open(FIXTURE, "rb") as f:
            data = f.read()
        with self.assertRaises(pmm.PmmFormatError):
            pmm.loads(data + b"\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
