import os
import unittest

from mmd_cli import scene
from mmd_cli.formats import pmm

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "scene_v932.pmm")


def summary(**kw):
    with open(FIXTURE, "rb") as f:
        return scene.summarize(pmm.loads(f.read()), **kw)


class SummarizeTest(unittest.TestCase):
    def test_top_level(self):
        s = summary()
        self.assertEqual(s["frame"], 10)
        self.assertEqual(s["view_size"], [640, 360])
        self.assertEqual(s["wave"], {"enabled": True, "path": "C:\\work\\t1.wav"})
        self.assertEqual(s["last_frame"], 30)

    def test_playback_settings_use_the_names_of_the_mmd_panel(self):
        self.assertEqual(summary()["play"], {"repeat": False, "range": None, "from_current_frame": False,
                                             "stay_at_stop_frame": False})

    def test_model_overview(self):
        m = summary()["models"][0]
        self.assertEqual(m["index"], 0)
        self.assertEqual(m["name"], "初音ミク")
        self.assertEqual(m["path"], "C:\\MMD\\UserFile\\Model\\初音ミク.pmd")
        self.assertEqual((m["bone_count"], m["morph_count"]), (122, 16))
        self.assertTrue(m["visible"])
        self.assertEqual(m["key_counts"], {"bones": 3, "morphs": 2})

    def test_bone_keys_are_named_and_use_the_angles_of_the_mmd_window(self):
        # the fixture keys are quaternions about +Z (30 and 45 degrees); MMD displays those as negative Z
        keys = summary()["models"][0]["keys"]["bones"]
        self.assertEqual(keys, [
            {"bone": "センター", "frame": 10, "pos": [0.0, 5.0, 0.0], "rot": [0.0, 0.0, 0.0]},
            {"bone": "センター", "frame": 30, "pos": [1.0, 2.0, 3.0], "rot": [0.0, 0.0, -30.0]},
            {"bone": "右腕", "frame": 10, "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, -45.0]},
        ])

    def test_morph_keys_are_named(self):
        keys = summary()["models"][0]["keys"]["morphs"]
        self.assertEqual(keys, [
            {"morph": "まばたき", "frame": 10, "value": 1.0},
            {"morph": "あ", "frame": 15, "value": 0.5},
        ])

    def test_current_pose_lists_only_what_differs_from_rest(self):
        cur = summary()["models"][0]["current"]
        self.assertEqual(cur["bones"], {
            "センター": {"pos": [0.0, 5.0, 0.0], "rot": [0.0, 0.0, 0.0]},
            "右腕": {"pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, -45.0]},
        })
        self.assertEqual(cur["morphs"], {"まばたき": 1.0, "あ": 0.3333})

    def test_keys_can_be_left_out(self):
        m = summary(keys=False)["models"][0]
        self.assertNotIn("keys", m)
        self.assertEqual(m["key_counts"], {"bones": 3, "morphs": 2})

    def test_camera_uses_the_numbers_shown_in_the_mmd_window(self):
        cam = summary()["camera"]
        want = {"pos": [1.5, 12.0, -3.25], "rot": [10.0, 20.0, 5.0], "distance": 30.0, "fov": 45,
                "perspective": True}
        self.assertEqual(cam["current"], want)
        self.assertEqual(cam["keys"], [dict(want, frame=0)])

    def test_light_uses_the_numbers_shown_in_the_mmd_window(self):
        light = summary()["light"]
        self.assertEqual(light["current"], {"rgb": [200, 100, 50], "dir": [-0.2, -0.8, 0.3]})
        self.assertEqual(light["keys"], [{"frame": 0, "rgb": [200, 100, 50], "dir": [-0.2, -0.8, 0.3]}])

    def test_accessory(self):
        accs = summary()["accessories"]
        self.assertEqual(len(accs), 1)
        a = accs[0]
        self.assertEqual((a["index"], a["name"]), (0, "negi.x"))
        self.assertEqual(a["current"], {"pos": [1.0, 2.0, 3.0], "rot": [10.0, 20.0, 30.0], "scale": 2.0,
                                        "alpha": 0.5, "visible": True, "shadow": False,
                                        "parent_model": None, "parent_bone": None})
        self.assertEqual([k["frame"] for k in a["keys"]], [0, 10])
        self.assertEqual(a["keys"][0]["scale"], 1.0)
        self.assertEqual(a["keys"][1]["rot"], [10.0, 20.0, 30.0])


if __name__ == "__main__":
    unittest.main()
