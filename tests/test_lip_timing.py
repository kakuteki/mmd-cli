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


def onsets_of(*runs):
    """the onsets of runs of (vowels, start) sung one every 6 frames"""
    morphs = []
    for vowels, start in runs:
        morphs += sung(vowels, start)
    return lip_timing.onsets(vmd.Motion(model_name="m", morphs=morphs))


class AlignTest(unittest.TestCase):
    """all the lines of a song are placed at once, in their order, each key going to one line at most"""

    def test_a_line_does_not_take_the_last_vowels_of_the_line_before(self):
        # the second line begins with "ou" like the end of the first, but the mouth skipped its o: searched alone (with
        # one error) it begins on the last u of the first line (the fault of lyric lines 01 and 26 of the MV)
        onsets = onsets_of(("aoaiou", 100), ("uaeii", 160))
        alone = lip_timing.find(onsets, "ouaeii", errors=1)
        self.assertEqual(alone[0]["frames"][0], 130)                    # the last u of the first line
        first, second = lip_timing.align(onsets, ["aoaiou", "ouaeii"])
        self.assertEqual(first["frames"], [100, 106, 112, 118, 124, 130])
        self.assertEqual((second["frames"], second["errors"]), ([160, 166, 172, 178, 184], 1))

    def test_the_same_line_sung_again_is_placed_at_each_of_its_times_in_order(self):
        onsets = onsets_of(("iiae", 100), ("aaa", 200), ("iiae", 300))
        placed = lip_timing.align(onsets, ["iiae", "aaa", "iiae"])
        self.assertEqual([p["frames"][0] for p in placed], [100, 200, 300])
        self.assertEqual([p["errors"] for p in placed], [0, 0, 0])

    def test_keys_before_between_and_after_the_lines_are_left_out(self):
        onsets = onsets_of(("o", 10), ("aiu", 100), ("e", 150), ("ie", 200), ("u", 400))
        placed = lip_timing.align(onsets, ["aiu", "ie"])
        self.assertEqual([p["frames"] for p in placed], [[100, 106, 112], [200, 206]])

    def test_a_line_does_not_run_on_over_a_long_pause(self):
        # "aiua" could end on the a sung after a pause of 6 s, but a line is sung in one breath: its last a is missing
        onsets = onsets_of(("aiu", 100), ("aeo", 300))
        first, second = lip_timing.align(onsets, ["aiua", "eo"])
        self.assertEqual((first["frames"], first["errors"]), ([100, 106, 112], 1))
        self.assertEqual(second["frames"], [306, 312])

    def test_an_extra_key_inside_a_line_is_an_error_of_the_line(self):
        first, = lip_timing.align(onsets_of(("aeiu", 100)), ["aiu"])
        self.assertEqual((first["frames"], first["errors"]), ([100, 112, 118], 1))

    def test_a_line_with_no_key_left_is_placed_nowhere(self):
        onsets = onsets_of(("aiu", 100))
        first, second = lip_timing.align(onsets, ["aiu", "eee"])
        self.assertEqual(first["frames"], [100, 106, 112])
        self.assertEqual((second["frames"], second["errors"]), ([], 3))

    def test_a_line_without_vowels_is_an_error(self):
        with self.assertRaises(ValueError):
            lip_timing.align(onsets_of(("aiu", 100)), ["aiu", ""])


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
        self.assertEqual(result["found"], [{"index": 0, "line": "iiae", "frames": [200, 206, 212, 218], "seconds": [6.667, 7.267],
                                            "errors": 0}])
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["onsets"]), 9)
        self.assertEqual(data["phrases"][1], {"start": 200, "end": 218, "seconds": [6.667, 7.267], "vowels": "iiae"})
        self.assertEqual(data["found"], result["found"])

    def test_the_lines_are_placed_together_in_their_order(self):
        code, result = run([self.lips, "--find", "あいうえお", "--find", "ひびかせ", "--find", "おおお"])
        self.assertEqual(code, 0, result)
        self.assertEqual([(f["index"], f["line"], f["frames"][:1], f["errors"]) for f in result["found"]],
                         [(0, "aiueo", [100], 0), (1, "iiae", [200], 0), (2, "ooo", [], 3)])
        self.assertIsNone(result["found"][2]["seconds"])

    def test_the_lines_can_come_from_a_file(self):
        lines = os.path.join(self.folder, "lines.txt")
        with open(lines, "w", encoding="utf-8") as f:
            f.write("あいうえお\n\nひびかせ\n")                             # a blank row is no line
        code, result = run([self.lips, "--lines", lines])
        self.assertEqual(code, 0, result)
        self.assertEqual([(f["index"], f["frames"][0]) for f in result["found"]], [(0, 100), (1, 200)])

    def test_search_finds_every_place_a_line_is_sung(self):
        morphs = sung("iiae", 100) + sung("aaa", 200) + sung("iiae", 300)
        with open(self.lips, "wb") as f:
            f.write(vmd.dumps(vmd.Motion(model_name="m", morphs=morphs)))
        code, result = run([self.lips, "--search", "ひびかせ"])
        self.assertEqual(code, 0, result)
        self.assertEqual([(s["line"], s["frames"][0]) for s in result["searched"]], [("iiae", 100), ("iiae", 300)])
        self.assertEqual(result["found"], [])

    def test_errors_exit_2(self):
        lines = os.path.join(self.folder, "lines.txt")
        with open(lines, "w", encoding="utf-8") as f:
            f.write("ひびかせ\n")
        for argv in ([os.path.join(self.folder, "none.vmd")], [self.lips, "--find", "響かせ"], [self.lips, "--gap", "0"],
                     [self.lips, "--find", "ひびかせ", "--lines", lines], [self.lips, "--lines", os.path.join(self.folder, "no.txt")],
                     [self.lips, "--find", "ん"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])

    def test_errors_without_search_is_an_error(self):
        # review: --errors used to go with --find; with all lines placed at once it has no meaning there, and leaving it
        # out silently would hide that --find ひびかせ no longer finds every chorus
        for argv in ([self.lips, "--find", "ひびかせ", "--errors", "1"], [self.lips, "--errors", "1"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("--search", result["error"]["message"])
        code, result = run([self.lips, "--search", "ひびかせ", "--errors", "1"])
        self.assertEqual(code, 0, result)

    def test_one_line_to_find_is_placed_once_with_a_warning(self):
        # the old use, --find ひびかせ for every chorus, now places the word once: the summary says to use --search
        code, result = run([self.lips, "--find", "ひびかせ"])
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["found"]), 1)
        self.assertIn("--search", result["warning"])
        code, result = run([self.lips, "--find", "あいうえお", "--find", "ひびかせ"])
        self.assertNotIn("warning", result)


def real_file(*parts):
    """a file of the real song under _spike/ of this tree or of a tree up to 4 folders above (a worktree)"""
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    return None


REAL_LIPS = real_file("_spike", "out", "hibikase", "kazusa", "ヒビカセ（Choreography by ATY）", "ヒビカセ　Face&Lips 歌ってる方.vmd")
REAL_LINES = real_file("_spike", "out", "hibikase", "mv", "lyrics", "kana_lines.txt")


@unittest.skipUnless(REAL_LIPS and REAL_LINES, "needs the lip motion and the lyric lines of the MV under _spike/")
class RealSongTest(unittest.TestCase):
    """the 49 lines of ヒビカセ on KAZUSA's lip motion (622 vowel keys)"""

    @classmethod
    def setUpClass(cls):
        with open(REAL_LINES, encoding="utf-8") as f:
            lines = [lip_timing.vowels_of(line) for line in f if line.strip()]
        cls.placed = lip_timing.align(lip_timing.onsets(vmd.load(REAL_LIPS)), lines)

    def test_every_line_is_placed_and_no_key_is_in_two_lines(self):
        self.assertEqual(len(self.placed), 49)
        frames = [f for p in self.placed for f in p["frames"]]
        self.assertTrue(all(p["frames"] for p in self.placed))
        self.assertEqual(frames, sorted(set(frames)))                  # in time order, each key once

    def test_the_four_lines_the_search_put_off_begin_where_they_are_sung(self):
        # a19: 01 and 26 took the last vowels of the line before (1062 こ, 4055 ル); 10 and 11 were filled a vowel late
        firsts = {i: self.placed[i]["frames"][0] for i in (1, 10, 11, 26)}
        self.assertEqual(firsts, {1: 1085, 10: 2011, 11: 2104, 26: 4068})
        self.assertEqual((self.placed[0]["frames"][-1], self.placed[25]["frames"][-1]), (1072, 4055))


if __name__ == "__main__":
    unittest.main()
