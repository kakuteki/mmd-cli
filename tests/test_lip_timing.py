"""tools/lip_timing.py: when a song is sung, read from the vowels of a lip motion; and where a lyric line falls."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("lip_timing", os.path.join(ROOT, "tools", "lip_timing.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lip_timing = load_tool()
NAMES = {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}


def sung(vowels, start, step=6):
    """the morph keys of `vowels` sung one every `step` frames from `start`: each mouth opens to a peak and
    closes again (0 two frames before, 1 on the frame, 0 three frames after)"""
    keys = []
    for i, v in enumerate(vowels):
        f = start + i * step
        keys += [vmd.MorphKey(NAMES[v], f - 2, 0.0), vmd.MorphKey(NAMES[v], f, 1.0), vmd.MorphKey(NAMES[v], f + 3, 0.0)]
    return keys


def song():
    """two phrases a second apart, a blink that is no vowel, and a mouth that only half opens"""
    morphs = sung("aiueo", 100) + sung("iiae", 200) + [vmd.MorphKey("まばたき", 150, 1.0), vmd.MorphKey("まばたき", 153, 0.0)]
    morphs += [vmd.MorphKey("あ", 398, 0.0), vmd.MorphKey("あ", 400, 0.2), vmd.MorphKey("あ", 403, 0.0)]     # too small to count
    return vmd.Motion(model_name="singer", morphs=morphs)


class OnsetTest(unittest.TestCase):
    def test_a_vowel_sounds_where_its_mouth_is_widest(self):
        onsets = lip_timing.onsets(song())
        self.assertEqual([(o.frame, o.vowel) for o in onsets],
                         [(100, "a"), (106, "i"), (112, "u"), (118, "e"), (124, "o"), (200, "i"), (206, "i"), (212, "a"), (218, "e")])
        self.assertTrue(all(o.weight == 1.0 for o in onsets))

    def test_a_held_mouth_counts_once_at_its_first_frame(self):
        held = vmd.Motion(model_name="m", morphs=[vmd.MorphKey("あ", 10, 0.0), vmd.MorphKey("あ", 12, 0.8), vmd.MorphKey("あ", 30, 0.8),
                                                  vmd.MorphKey("あ", 33, 0.0)])
        self.assertEqual([(o.frame, o.vowel) for o in lip_timing.onsets(held)], [(12, "a")])

    def test_no_vowel_morph_is_an_error(self):
        with self.assertRaises(ValueError):
            lip_timing.onsets(vmd.Motion(model_name="m", morphs=[vmd.MorphKey("まばたき", 1, 1.0)]))


class PhraseTest(unittest.TestCase):
    def test_a_silence_ends_a_phrase(self):
        phrases = lip_timing.phrases(lip_timing.onsets(song()), gap=24)
        self.assertEqual([(p.start, p.end, p.vowels) for p in phrases], [(100, 124, "aiueo"), (200, 218, "iiae")])
        one = lip_timing.phrases(lip_timing.onsets(song()), gap=200)
        self.assertEqual([p.vowels for p in one], ["aiueoiiae"])


class VowelsOfTest(unittest.TestCase):
    def test_kana_become_their_vowels(self):
        self.assertEqual(lip_timing.vowels_of("ひびかせ"), "iiae")
        self.assertEqual(lip_timing.vowels_of("ヒビカセ"), "iiae")
        self.assertEqual(lip_timing.vowels_of("きょうのよる"), "ouoou")        # a small ょ rides on its kana: kyo-u-no-yo-ru
        self.assertEqual(lip_timing.vowels_of("がっこう"), "aou")              # the small っ is a stop, not a vowel
        self.assertEqual(lip_timing.vowels_of("さん ぽ"), "ao")                # ん and spaces sound no vowel
        self.assertEqual(lip_timing.vowels_of("ラーメン"), "aae")              # a long mark repeats the vowel before it

    def test_latin_vowels_are_taken_as_written(self):
        self.assertEqual(lip_timing.vowels_of("hibikase"), "iiae")
        self.assertEqual(lip_timing.vowels_of("Kyou no yoru"), "ouoou")

    def test_a_kanji_cannot_be_read(self):
        with self.assertRaises(ValueError) as ctx:
            lip_timing.vowels_of("響かせ")
        self.assertIn("kana", str(ctx.exception))


class FindTest(unittest.TestCase):
    def test_the_exact_run_of_vowels_is_found_with_its_frames(self):
        onsets = lip_timing.onsets(song())
        hits = lip_timing.find(onsets, "iiae")
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["frames"], hits[0]["errors"]), ([200, 206, 212, 218], 0))

    def test_a_line_sung_with_one_vowel_swallowed_is_still_placed(self):
        # the singer's mouth skips the u: "aieo" is sung for the line "aiueo"; one error is within a fifth of the line
        morphs = sung("aieo", 100) + sung("ooooo", 300)
        onsets = lip_timing.onsets(vmd.Motion(model_name="m", morphs=morphs))
        hits = lip_timing.find(onsets, "aiueo", errors=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["frames"][0], hits[0]["frames"][-1], hits[0]["errors"]), (100, 118, 1))
        self.assertEqual(lip_timing.find(onsets, "aiueo", errors=0), [])

    def test_matches_do_not_overlap_and_come_in_time_order(self):
        morphs = sung("iiae", 100) + sung("iiae", 300) + sung("iiae", 500)
        hits = lip_timing.find(lip_timing.onsets(vmd.Motion(model_name="m", morphs=morphs)), "iiae")
        self.assertEqual([h["frames"][0] for h in hits], [100, 300, 500])

    def test_a_run_spread_over_a_pause_is_not_one_line(self):
        morphs = sung("ii", 100) + sung("ae", 400)
        onsets = lip_timing.onsets(vmd.Motion(model_name="m", morphs=morphs))
        self.assertEqual(lip_timing.find(onsets, "iiae", span=60), [])
        self.assertEqual(len(lip_timing.find(onsets, "iiae", span=600)), 1)


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = lip_timing.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.lips = os.path.join(self.folder, "lips.vmd")
        with open(self.lips, "wb") as f:
            f.write(vmd.dumps(song()))

    def test_the_summary_and_the_file_of_onsets(self):
        out = os.path.join(self.folder, "timing.json")
        code, result = run([self.lips, "--out", out, "--find", "ひびかせ"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual((result["onsets"], result["phrases"], result["first"], result["last"]), (9, 2, 100, 218))
        self.assertEqual(result["found"], [{"line": "iiae", "frames": [200, 206, 212, 218], "seconds": [6.667, 7.267], "errors": 0}])
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["onsets"]), 9)
        self.assertEqual(data["phrases"][1], {"start": 200, "end": 218, "seconds": [6.667, 7.267], "vowels": "iiae"})

    def test_errors_exit_2(self):
        for argv in ([os.path.join(self.folder, "none.vmd")], [self.lips, "--find", "響かせ"], [self.lips, "--gap", "0"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
