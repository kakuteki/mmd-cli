"""tools/look_credits.py: the credits of MMD videos read from their descriptions (the tools, the effects and their
authors, the models, motions, cameras and stages), counted over a channel."""
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    spec = importlib.util.spec_from_file_location("look_credits", os.path.join(ROOT, "tools", "look_credits.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LC = load_tool()

BOILER = "\n\nEnglish\n\n*Reprinting without the author's authorization is prohibited.*\n\nHello!\nThis work was made..."

# the shapes credits come in (made up, after the shapes seen on the channel)
KEYED = """Model：someone/studio

Motion：mover
Camera：shooter

Stage：builder

Effects：ray1.5.2 （Rui）
AutoLuminous4（そぼろ）
MotionBlur3（そぼろ）
ikBokeh（ikeno）
SMAA/FXAA（Rui）""" + BOILER

BRACKETS = """【模型】studio / maker
【场景】builder
【动作】mover
【MME】Rui/そぼろ/ikeno/ P.I.P /三金络合物/""" + BOILER

AUTHORS_ONLY = """MODEL：studio
MME：Rui / そぼろ / ビームマンP / ikeno / データP / 三金络合物
Tools：MikuMikuDance / PR / SVFI""" + BOILER

UNKEYED = """模型：someone
场景：somewhere
ray https://github.com/ray-cast/ray-mmd
PostRimLighting ミーフォ茜
ikGodray
MikuMikuEffect用ディフュージョンフィルタ
製作：そぼろ
AutoLuminous Ver.2.0 製作：そぼろ
HgSAO.fx ver0.0.2 & ScreenTex.fx ver0.0.4 by 針金P""" + BOILER

OLD = "-English-\n\nHello!\nThis video is sponsored by 「Bilibili」 creators."


class SectionTest(unittest.TestCase):
    def test_the_credits_end_where_the_channels_own_text_begins(self):
        self.assertTrue(LC.credit_section(KEYED).startswith("Model："))
        self.assertNotIn("Reprinting", LC.credit_section(KEYED))
        self.assertEqual(LC.credit_section(OLD), "")
        self.assertEqual(LC.credit_section("English\n\nHello!"), "")

    def test_fields_are_read_from_keys_in_several_languages_and_brackets(self):
        f = LC.fields(LC.credit_section(KEYED))
        self.assertEqual(f["model"], "someone/studio")
        self.assertEqual(f["motion"], "mover")
        self.assertEqual(f["camera"], "shooter")
        self.assertEqual(f["stage"], "builder")
        self.assertIn("AutoLuminous4", f["effects"])            # the lines after a key belong to it
        self.assertIn("SMAA", f["effects"])
        b = LC.fields(LC.credit_section(BRACKETS))
        self.assertEqual(b["model"], "studio / maker")
        self.assertEqual(b["stage"], "builder")
        self.assertIn("P.I.P", b["effects"])
        a = LC.fields(LC.credit_section(AUTHORS_ONLY))
        self.assertIn("SVFI", a["tools"])


class EffectTest(unittest.TestCase):
    def test_effects_are_found_by_name_wherever_they_are_written(self):
        self.assertEqual(LC.effects(LC.credit_section(KEYED)),
                         ["AutoLuminous", "FXAA/SMAA", "MotionBlur", "ikBokeh", "ray-mmd"])
        found = LC.effects(LC.credit_section(UNKEYED))
        for name in ("ray-mmd", "PostRimLighting", "ikGodray", "Diffusion", "AutoLuminous", "HgSAO", "ScreenTex"):
            self.assertIn(name, found)
        self.assertNotIn("ikDiffusion", found)                  # そぼろ's diffusion filter is not ikeno's

    def test_a_word_inside_another_is_no_effect(self):
        # "Gray Raven" has "ray" in it, "PRISM" has "PR": neither is ray-mmd or Premiere
        text = "Model：Punishing Gray Raven team\nStage：PRISM hall"
        self.assertEqual(LC.effects(text), [])
        self.assertEqual(LC.tools(text), [])

    def test_authors_are_split_from_the_effects_field(self):
        self.assertEqual(LC.authors(LC.fields(LC.credit_section(BRACKETS))),
                         ["P.I.P", "Rui", "ikeno", "そぼろ", "三金络合物"])
        names = LC.authors(LC.fields(LC.credit_section(KEYED)))
        self.assertIn("そぼろ", names)
        self.assertIn("Rui", names)
        self.assertIn("ikeno", names)

    def test_tools_besides_mmd(self):
        self.assertEqual(LC.tools(LC.credit_section(AUTHORS_ONLY)), ["MikuMikuDance", "Premiere Pro", "SVFI"])
        self.assertEqual(LC.tools("使用软件：MMD/PE/AE"), ["After Effects", "MikuMikuDance", "PmxEditor"])
        self.assertEqual(LC.tools("后期：达芬奇 + AviUtl"), ["AviUtl", "DaVinci Resolve"])


class CountTest(unittest.TestCase):
    def test_a_channel_is_counted_video_by_video_with_the_words_kept(self):
        videos = [{"id": "a", "title": "A", "upload_date": "20261018", "view_count": 10, "description": KEYED},
                  {"id": "b", "title": "B", "upload_date": "20261017", "view_count": 20, "description": BRACKETS},
                  {"id": "c", "title": "C", "upload_date": "20200101", "view_count": 30, "description": OLD}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for v in videos:
                    f.write(json.dumps(v, ensure_ascii=False) + "\n")
            report = LC.count(path)
        self.assertEqual(report["videos"], 3)
        self.assertEqual(report["with_credits"], 2)
        self.assertEqual(report["effects"]["ray-mmd"]["videos"], 1)
        self.assertEqual(report["authors"]["Rui"]["videos"], 2)
        self.assertEqual(report["authors"]["そぼろ"]["videos"], 2)
        example = report["effects"]["AutoLuminous"]["examples"][0]
        self.assertEqual(example["id"], "a")
        self.assertIn("AutoLuminous4（そぼろ）", example["line"])        # the words as written
        self.assertEqual(report["per_video"][0]["effects"], ["AutoLuminous", "FXAA/SMAA", "MotionBlur", "ikBokeh",
                                                              "ray-mmd"])


if __name__ == "__main__":
    unittest.main()
