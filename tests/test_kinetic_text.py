"""tools/kinetic_text.py: the lyrics cut into short pieces at the syllables of the voice, each piece coming in, moving on
and going out in about a second (subtitles in front of the dancer, large words behind her), and the credits at the end.

The lines here are made up for the tests (the MV's lyrics are not distributed); their syllables are timed by hand.
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import statistics
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
    from PIL import Image
    import cv2
except ImportError:                       # the tool draws with Pillow, numpy and OpenCV; the rest of the suite does not
    np = None


def load_tool(name):
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KT = load_tool("kinetic_text") if np is not None else None
NEEDS = "needs Pillow, numpy and OpenCV"
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")

SMALL = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")


def morae_of(reading):
    """the morae of a reading as lip_sync's alignment cuts them: a small kana goes with the kana before it"""
    out = []
    for ch in reading:
        if ch.isspace() or ch in "「」、。":
            continue
        if ch in SMALL and out:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def timed(reading, t0, step=0.2, word_gap=0.0):
    """the alignment's rows for a reading: a mora every `step` s from t0 (consonant 0.04 s before the vowel), a word start
    after every space"""
    rows, t, start = [], t0, True
    for part in reading.split(" "):
        for k, kana in enumerate(morae_of(part)):
            rows.append({"kana": kana, "c0": round(t, 3), "v0": round(t + 0.04, 3), "v1": round(t + step - 0.01, 3),
                         "word_start": k == 0})
            t += step
        t += word_gap
    return rows


# made-up lines (text, reading)
SKY = ("青空に歌う 光の街",
       "あおぞらにうたう ひかりのまち")            # 青空に歌う 光の街
SIGNAL = ("シグナル送れ", "しぐなるおくれ")         # シグナル送れ
CHOCO = ("チョコレートの雨",
         "ちょこれーとのあめ")                                   # チョコレートの雨
QUOTE = ("「もう一度」と言った",
         "「もういちど」といった")                       # 「もう一度」と言った
LONG = ("星を数えて夜明けまで歩き続ける小さな夢",
        "ほしをかぞえてよあけまであるきつづける"
        "ちいさなゆめ")                                                       # 星を数えて夜明けまで歩き続ける小さな夢
PHRASE = ("あおいそら白いくも", "あおいそらしろいくも")              # あおいそら白いくも
WINDOW = ("まどをあけて朝をまつ", "まどをあけてあさをまつ")          # まどをあけて朝をまつ
SCHOOL = ("きのうがっこうにいった", "きのうがっこうにいった")        # きのうがっこうにいった
JUMP = ("トランポリンでとんだ", "とらんぽりんでとんだ")              # トランポリンでとんだ
BRACKET = ("まどの「そと」へでた", "まどの「そと」へでた")            # まどの「そと」へでた
CAT = ("ねこがしゃべるよる", "ねこがしゃべるよる")                    # ねこがしゃべるよる
CAMERA = ("カメラマン呼べ", "かめらまんよべ")                        # カメラマン呼べ


@unittest.skipUnless(KT, NEEDS)
class ReadingTest(unittest.TestCase):
    """which part of the reading each character of the text is: kana match kana, a run of kanji takes what lies between"""

    def test_kanji_take_the_reading_between_the_kana(self):
        text, reading = "青空に歌う", "あおぞらにうたう"
        ruby = KT.align_reading(text, reading)
        self.assertEqual([(r.start, r.end) for r in ruby], [(0, 4), (0, 4), (4, 5), (5, 7), (7, 8)])
        # the two kanji of one run are one word (a piece never cuts it)
        self.assertEqual(ruby[0].group, ruby[1].group)
        self.assertNotEqual(ruby[2].group, ruby[1].group)

    def test_katakana_and_hiragana_are_the_same_sound(self):
        ruby = KT.align_reading(*SIGNAL)
        self.assertEqual([(r.start, r.end) for r in ruby][:4], [(0, 1), (1, 2), (2, 3), (3, 4)])
        self.assertEqual((ruby[4].start, ruby[4].end), (4, 6))           # 送 = おく

    def test_spaces_and_marks_on_either_side_are_passed_over(self):
        # the text has a comma the reading lacks, the reading a space the text lacks
        text = "風、光揺れる"                                        # 風、光揺れる
        reading = "かぜ ひかり ゆれる"                        # かぜ ひかり ゆれる
        ruby = KT.align_reading(text, reading)
        spans = sorted({(r.start, r.end) for r in ruby})                  # a run of kanji shares one span
        self.assertEqual("".join(reading[a:b] for a, b in spans).replace(" ", ""), reading.replace(" ", ""))
        self.assertEqual(ruby[1].start, ruby[1].end)                      # the comma is read as nothing
        # 光揺 stand together in the text and are two words of the reading: one run, read across the space
        self.assertEqual(ruby[2].group, ruby[3].group)
        self.assertEqual(reading[ruby[2].start:ruby[2].end], "ひかり ゆ")

    def test_a_line_that_cannot_be_read_so_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            KT.align_reading("青空に", "あおぞら")             # 青空に / あおぞら: no に
        self.assertIn("\\u9752", str(caught.exception))                  # it names the line (escaped for cp932)

    def test_a_kana_of_two_letters_is_one_mora(self):
        text, reading = CHOCO
        index = KT.reading_morae(reading, morae_of(reading))
        # ち ょ こ れ ー と の あ め -> ちょ こ れ ー と の あ め
        self.assertEqual(index, [0, 0, 1, 2, 3, 4, 5, 6, 7])

    def test_morae_that_do_not_spell_the_reading_are_refused(self):
        with self.assertRaises(ValueError):
            KT.reading_morae("あお", ["あ", "い"])

    def test_every_character_is_timed_by_its_morae(self):
        text, reading = SKY
        chars = KT.line_chars(text, reading, timed(reading, 10.0, step=0.2))
        self.assertEqual("".join(c.ch for c in chars), text)
        # 青空 is あおぞら: from the consonant of あ to the end of ら, both characters
        self.assertAlmostEqual(chars[0].t0, 10.0)
        self.assertAlmostEqual(chars[1].t0, 10.0)
        self.assertAlmostEqual(chars[0].t1, 10.0 + 3 * 0.2 + 0.19)
        # に is the fifth mora
        self.assertAlmostEqual(chars[2].t0, 10.8)
        # the space holds the time of the character after it
        self.assertAlmostEqual(chars[5].t0, chars[6].t0)


@unittest.skipUnless(KT, NEEDS)
class PiecesTest(unittest.TestCase):
    """a line cut into pieces of about five characters (the references' lines: 5 [5, 6] characters)"""

    def pieces(self, line, **settings):
        text, reading = line
        chars = KT.line_chars(text, reading, timed(reading, 0.0))
        # the cutting by characters (sung 0) at a target of 5 (2 to 7) unless a test asks another, with the life of before (a
        # piece sung longer than 0.77 + 0.25 s costs more): the rules, not the look's values (SungTest cuts by the sung time)
        base = {"chars": 5, "chars_min": 2, "chars_max": 7, "sung": 0.0, "life": [0.62, 0.77]}
        cut = KT.cut_line(chars, dict(KT.default_settings(), **dict(base, **settings)))
        return ["".join(c.ch for c in chars[a:b]) for a, b in cut]

    def test_a_space_is_where_a_line_is_cut_first(self):
        self.assertEqual(self.pieces(SKY), ["青空に歌う", "光の街"])

    def test_a_long_line_is_cut_into_pieces_of_about_the_size_asked(self):
        for target, least, most in ((5, 2, 7), (6, 3, 8)):
            parts = self.pieces(LONG, chars=target, chars_min=least, chars_max=most)
            sizes = [len(p) for p in parts]
            self.assertEqual("".join(parts), LONG[0])
            self.assertTrue(all(least <= n <= most for n in sizes), sizes)
            self.assertTrue(target - 1 <= statistics.median(sizes) <= target + 1, (target, sizes))

    def test_a_word_is_not_cut(self):
        # 星を数えて夜明けまで...: a run of kanji (夜明) stays whole, and so does a run of katakana
        for part in self.pieces(LONG):
            self.assertFalse(part.startswith("明"), part)
        for part in self.pieces(SIGNAL, chars=3, chars_min=2):
            self.assertFalse(part.startswith(("グ", "ナ", "ル")), part)

    def test_no_piece_begins_with_a_small_kana_a_long_mark_or_a_closing_mark(self):
        for line in (CHOCO, QUOTE, LONG):
            for chars in (3, 4, 5):
                for part in self.pieces(line, chars=chars, chars_min=2):
                    self.assertNotIn(part[0], "ョー」、っッ", (line[0], chars, part))
                    self.assertNotEqual(part[-1], "「", (line[0], chars, part))

    def test_the_pieces_are_the_line_in_order(self):
        for line in (SKY, SIGNAL, CHOCO, QUOTE, LONG):
            self.assertEqual("".join(self.pieces(line)), line[0].replace(" ", ""))

    # (the tests below: kineticrev 2026-10-21, the rules of the cutting that broken copies of the tool got through)

    def test_a_line_is_cut_where_a_phrase_starts(self):
        # before a word of kanji after hiragana, after a particle, never inside the ending of a verb
        for chars in (2, 3, 4, 5):
            self.assertEqual(self.pieces(PHRASE, chars=chars), ["あおいそら", "白いくも"], chars)
        self.assertEqual(self.pieces(WINDOW, chars=2), ["まどを", "あけて", "朝を", "まつ"])
        self.assertEqual(self.pieces(WINDOW, chars=4), ["まどをあけて", "朝をまつ"])
        self.assertEqual(self.pieces(LONG, chars=5), ["星を数えて", "夜明けまで", "歩き続ける", "小さな夢"])

    def test_a_small_kana_of_hiragana_stays_with_the_kana_before_it(self):
        for chars in (2, 3, 4, 5):
            for part in self.pieces(SCHOOL, chars=chars):
                self.assertNotIn(part[0], "ぁぃぅぇぉっゃゅょゎ", (chars, part))

    def test_no_piece_begins_with_the_n(self):
        # no Japanese word begins with ん: a piece that does parts a word (a line of the MV was cut so, 2026-10-21)
        for line in (JUMP, SKY, LONG, SCHOOL):
            for chars, least, most in ((2, 2, 7), (3, 2, 7), (4, 2, 7), (5, 2, 7), (7, 4, 9)):
                for part in self.pieces(line, chars=chars, chars_min=least, chars_max=most):
                    self.assertNotIn(part[0], "んン", (line[0], chars, part))

    def test_an_opening_bracket_goes_with_the_word_after_it(self):
        for chars, least, most in ((4, 2, 7), (5, 2, 7), (6, 3, 8)):
            for part in self.pieces(BRACKET, chars=chars, chars_min=least, chars_max=most):
                self.assertNotEqual(part[-1], "「", (chars, part))
                self.assertNotEqual(part[0], "」", (chars, part))

    def test_no_piece_is_longer_than_the_most_but_a_word(self):
        for chars, least, most in ((6, 3, 8), (7, 4, 8)):
            self.assertTrue(all(len(p) <= most for p in self.pieces(CAT, chars=chars, chars_min=least, chars_max=most)),
                            (chars, self.pieces(CAT, chars=chars, chars_min=least, chars_max=most)))

    def test_a_word_shorter_than_the_least_is_no_piece_of_its_own(self):
        self.assertEqual(self.pieces(("夜明 星", "よあけ ほし"), chars=2, chars_min=2), ["夜明 星"])     # 夜明 星

    def test_a_word_of_katakana_stays_whole(self):
        for chars in (2, 3, 4):
            self.assertIn("カメラマン", self.pieces(CAMERA, chars=chars), chars)

    def test_the_cutting_by_characters_with_the_defaults_is_as_before(self):
        # sung 0 cuts by characters as before (kinetic3rev 2026-10-21, the coordinator: what is not asked for gives the same
        # output).  kinetic3's chars_max 12 for the cutting by the time let 星を数えて夜明けまで through whole here (before,
        # 5 and 5: 7 of the MV's 48 lines were cut otherwise), and the rules of the cutting by the time are not its own
        # (カーニバル|かしらねえ朝まで: a cut after katakana costs as before)
        s = dict(KT.default_settings(), sung=0.0)
        for (text, reading), want in ((("星を数えて夜明けまで", "ほしをかぞえてよあけまで"), ["星を数えて", "夜明けまで"]),
                                      (("カーニバルかしらねえ朝まで", "かーにばるかしらねえあさまで"),
                                       ["カーニバル", "かしらねえ朝まで"])):                       # (made up)
            chars = KT.line_chars(text, reading, timed(reading, 2.0, 0.2))
            self.assertEqual([text[a:b] for a, b in KT.cut_line(chars, s)], want)


@unittest.skipUnless(KT, NEEDS)
class SungTest(unittest.TestCase):
    """the subtitles cut by how long they are sung, and on until they are sung (kinetic2 2026-10-21, the coordinator: 92 of the
    MV's 94 subtitles went before their words were sung, 0.8 s at the median, as the references' short life of 0.72 s was
    kept by the clock).  Now a piece is sung about `sung` s (the references' life) and stays until its last sound ends, plus
    `hang` s (its way to go); the words are still not cut, nor begun with a small kana, the long mark, a closing mark or ん"""

    def setUp(self):
        self.s = KT.default_settings()

    def plan_line(self, line, step, **settings):
        """the subtitles of one line sung a mora every `step` s from 2.0 s, and the sung span of each of its pieces"""
        s = dict(self.s, **settings)
        words = song(lines=[line_of(line[0], line[1], 2.0, step)], sections=[{"kind": "verse", "start": 0, "end": 60}])
        chars = KT.line_chars(line[0], line[1], timed(line[1], 2.0, step))
        cuts = KT.cut_line(chars, s)
        subs = sorted((p for p in KT.plan_words(words, s) if p.role in ("sub", "column")), key=lambda p: p.start)
        sung = [(min(c.t0 for c in chars[a:b] if c.first >= 0), max(c.t1 for c in chars[a:b] if c.first >= 0)) for a, b in cuts]
        return subs, sung, cuts, chars

    def test_a_subtitle_stays_until_its_words_are_sung(self):
        for step in (0.2, 0.4):
            subs, sung, _, _ = self.plan_line(LONG, step)
            self.assertEqual(len(subs), len(sung))
            for p, (t0, t1) in zip(subs, sung):
                self.assertGreaterEqual(p.end, t1 + self.s["hang"] - 1e-6, (step, p.id))     # on until its last sound ends
                self.assertLessEqual(p.end, max(p.start + self.s["life"][0], t1 + self.s["hang"]) + 1e-6, (step, p.id))

    def test_a_line_sung_slowly_is_cut_into_more_pieces(self):
        # (no more than its words allow: sung slowly, a piece a word; kinetic3)
        fast = self.plan_line(LONG, 0.12)[0]
        slow = self.plan_line(LONG, 0.35)[0]
        self.assertGreater(len(slow), len(fast))

    def test_a_piece_is_sung_about_as_long_as_asked_and_no_word_is_parted(self):
        for line in (LONG, WINDOW, SCHOOL, JUMP):
            _, sung, cuts, chars = self.plan_line(line, 0.2)
            lengths = [t1 - t0 for t0, t1 in sung]
            if len(lengths) > 2:
                self.assertLess(abs(statistics.median(lengths) - self.s["sung"]), 0.3, (line[0], lengths))
            for a, b in cuts:
                self.assertNotIn(chars[a].ch, "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮーんン」、。", (line[0], a))
                self.assertNotEqual(chars[b - 1].ch, "「", (line[0], b))
        for step in (0.12, 0.3):                                       # a word of katakana stays whole
            _, _, cuts, chars = self.plan_line(CAMERA, step)
            self.assertTrue(any("カメラマン" in "".join(c.ch for c in chars[a:b]) for a, b in cuts), step)

    def test_a_word_sung_long_is_not_parted_for_the_time(self):
        # 書きなおしたくなる (9 morae, 1.8 s): every cut inside it is inside a word (the ending of a verb: hiragana after kanji
        # or after hiragana that is no particle); cut by the time it would part it (words8 of 2026-10-21 had 26 such cuts, as
        # a verb's stem parted from its negation, read the other way round for a moment)
        line = ("書きなおしたくなる", "かきなおしたくなる")                 # (made up)
        for step in (0.2, 0.22):
            _, _, cuts, chars = self.plan_line(line, step)
            self.assertEqual(len(cuts), 1, (step, ["".join(c.ch for c in chars[a:b]) for a, b in cuts]))

    def test_a_piece_over_a_space_holds_whole_phrases(self):
        # 眠るだけでね 森へ, its first phrase sung long and the second short: cut by the time alone, the ね that ends the first
        # went over the space with the second (the で before it reads as a particle, a cut of 2), a piece that begins with
        # the last sound of one phrase and reads as the next one's (words8 of 2026-10-21 had 7 pieces over a space begun
        # inside a phrase and 6 ended inside one).  A space is where the lyrics part their phrases
        line = ("眠るだけでね 森へ", "ねむるだけでね もりへ")                    # (made up)
        # ... and ほら 海の灯台 sung fast: by the time alone ほら 海の | 灯台, a piece ended inside a phrase
        other = ("ほら 海の灯台", "ほら うみのとうだい")                          # (made up)
        for line, step in [(line, 0.2), (line, 0.22), (line, 0.25), (other, 0.15), (other, 0.16), (other, 0.17)]:
            _, _, cuts, chars = self.plan_line(line, step)
            texts = ["".join(c.ch for c in chars[a:b]) for a, b in cuts]
            for a, b in cuts:
                if any(c.kind == "space" for c in chars[a:b]):
                    self.assertTrue(a == 0 or chars[a - 1].kind == "space", (step, texts))
                    self.assertTrue(b == len(chars) or chars[b].kind == "space", (step, texts))
            if line[0].startswith("眠"):
                self.assertEqual(texts, ["眠るだけでね", "森へ"], step)

    def test_no_large_word_is_on_with_the_title_word(self):
        # the title word is large behind her by itself (a line that sings it has no large word of its own): on until sung,
        # the echo of the line before came after its words and lay under the title word (words8 of 2026-10-21: the last
        # chorus line's echo under the last title word for 1.6 s); with its subtitle (kinetic3), its tail still may
        n = len(morae_of(LONG[1]))
        for gap in (0.0, 0.1, 0.2):
            lines = [line_of(LONG[0], LONG[1], 2.0), line_of("輝き", HOOK_READING, 2.0 + n * 0.2 + gap)]
            words = song(lines=lines, sections=[{"kind": "chorus", "start": 0.0, "end": 20.0}])
            pieces = KT.plan_words(words, self.s)
            hooks = [p for p in pieces if p.role == "hook"]
            self.assertEqual(len(hooks), 1, gap)
            h = hooks[0]
            # (with no title word there, the line before has a large word on in its time)
            bare = KT.plan_words(dict(words, hook={"reading": "ぬ", "text": "ヌ"}), self.s)
            self.assertTrue([b for b in bare if b.role == "big" and b.line == 0 and b.start < h.end and b.end > h.start], gap)
            for b in [p for p in pieces if p.role == "big"]:
                self.assertTrue(b.end <= h.start + 1e-6 or b.start >= h.end - 1e-6, (gap, b.id, b.start, b.end))
                self.assertGreaterEqual(b.end - b.start, 0.3 - 1e-6, (gap, b.id))

    def test_two_subtitles_never_share_a_row_at_once(self):
        # on until sung, a subtitle is still going (its hang) when the next one comes: the last of a line of 3 pieces and the
        # first of the next line both took the first row (words8 of 2026-10-21: 12 such pairs, 8 of them both seen at once,
        # up to 0.29 s at full strength, drawn over each other).  Short phrases sung fast are on three at once
        s = dict(self.s, column_share=0.0)
        quick = ("ねえ ほら 見て", "ねえ ほら みて")                                # (made up)
        for first, step in [(SKY, 0.15), (SKY, 0.2), (SKY, 0.25), (WINDOW, 0.2), (quick, 0.12)]:
            n = len(morae_of(first[1]))
            words = song(lines=[line_of(first[0], first[1], 2.0, step), line_of(SKY[0], SKY[1], 2.0 + n * step, step)],
                         sections=[{"kind": "verse", "start": 0, "end": 60}])
            subs = sorted((p for p in KT.plan_words(words, s) if p.role == "sub"), key=lambda p: p.start)
            self.assertGreater(len(subs), 3, step)
            for i, p in enumerate(subs):
                for q in subs[i + 1:]:
                    if abs(p.y - q.y) < 1e-9:
                        self.assertGreaterEqual(q.start, p.end - 1e-6, (step, p.id, q.id))
                if first is not quick:                          # (two on at once: the other row, none cut short)
                    self.assertGreaterEqual(p.end, KT._life(p.start, p.sung_end, s) - 1e-6, (step, p.id))

    def test_phrases_are_not_put_together(self):
        # a phrase (between spaces) is a piece of its own (the coordinator 2026-10-21, kinetic3: the phrases first): ねえ ほら
        # 見て sung in 0.72 s is three, not one
        line = ("ねえ ほら 見て", "ねえ ほら みて")                                # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.12)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["ねえ", "ほら", "見て"])

    def test_a_phrase_sung_up_to_the_limit_is_one_piece_and_a_longer_one_is_cut_at_its_words(self):
        # まどをあけて 朝をまつ: each phrase sung up to `phrase` s (1.5) is one piece, though sung longer than `sung` (by the
        # time alone まどを|あけて); sung longer, it is cut at its words
        line = ("まどをあけて 朝をまつ", "まどをあけて あさをまつ")                # (made up)
        _, sung, cuts, chars = self.plan_line(line, 0.22)                          # 1.31 s and 1.09 s
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["まどをあけて", "朝をまつ"])
        _, sung, cuts, chars = self.plan_line(line, 0.3)                           # 1.79 s and 1.49 s
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["まどを", "あけて", "朝をまつ"])

    def test_a_long_phrase_is_cut_into_more_pieces_only_for_a_real_gain(self):
        # 雪の花と夜の灯が揺れる, sung 2.8 s: by the time alone 雪の|花と|夜の灯が|揺れる (2 characters a piece, nearer 0.72 s);
        # a piece more costs PIECE_COST (the meaning's borders first, the time what to near): 雪の花と|夜の灯が|揺れる
        line = ("雪の花と夜の灯が揺れる", "ゆきのはなとよるのひがゆれる")              # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.2)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["雪の花と", "夜の灯が", "揺れる"])

    def test_a_word_and_what_goes_with_it_may_run_past_nine_characters(self):
        # カーニバルかしらねえ朝まで, sung 2.6 s: its only border is before 朝; with at most 9 characters a piece the first 10
        # were cut inside (カーニバル|かしらねえ); cut by the time a piece has at most sung_chars_max (12) characters
        line = ("カーニバルかしらねえ朝まで", "かーにばるかしらねえあさまで")          # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.2)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["カーニバルかしらねえ", "朝まで"])
        _, _, cuts, chars = self.plan_line(line, 0.2, sung_chars_max=9)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["カーニバル", "かしらねえ", "朝まで"])

    def test_the_most_characters_cut_by_the_time_is_a_whole_number_from_chars_min(self):
        for bad in (1, 9.5):
            with self.assertRaises(ValueError) as caught:
                KT.check_settings(dict(self.s, sung_chars_max=bad))
            self.assertIn("sung_chars_max", str(caught.exception))

    def test_two_kana_between_kanji_are_two_words(self):
        # the rule of a verb made of two takes one kana that is no particle between the kanji: with two (見ちゃ駄目, a
        # contraction and a word of its own) they are two words, and sung slowly (2 s) the phrase is cut between them
        line = ("見ちゃ駄目", "みちゃだめ")                                          # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.5)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["見ちゃ", "駄目"])

    def test_a_compound_verb_is_not_parted(self):
        # 歩き出す: a kanji, one kana that is no particle and a kanji again is one word (a verb made of two: 歩き|出す read
        # as two); sung 2 s it stays one piece
        line = ("歩き出す", "あるきだす")                                          # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.4)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["歩き出す"])

    def test_a_katakana_word_keeps_what_follows_it(self):
        # パレードだよ: hiragana after katakana goes with the word (a particle or the copula after a noun: パレード|だよ
        # begins a piece with them); sung 2 s it stays one piece
        line = ("パレードだよ", "ぱれーどだよ")                                    # (made up)
        _, _, cuts, chars = self.plan_line(line, 0.35)
        self.assertEqual(["".join(c.ch for c in chars[a:b]) for a, b in cuts], ["パレードだよ"])

    def test_a_long_held_sound_keeps_its_piece_on(self):
        # its last mora held 2.5 s: the piece is on until it ends (life's upper bound is only a guard)
        words = song(lines=[{"text": "空", "reading": "そら", "morae": [["そ", 2.0, 2.05, 2.2], ["ら", 2.2, 2.25, 4.7]]}],
                     sections=[{"kind": "verse", "start": 0, "end": 60}])
        p = [q for q in KT.plan_words(words, self.s) if q.role in ("sub", "column")][0]
        self.assertAlmostEqual(p.end, 4.7 + self.s["hang"])

    def test_a_large_word_comes_and_goes_on_the_marks_its_subtitle_does(self):
        # on with its subtitle (kinetic3): the subtitle comes on a mark up to MARK_EARLIER s sooner and, its words sung, goes
        # on a mark in its tail (up to END_SOONER s before its singing ended); its large word comes and goes on the same
        # marks (the MV's words file has them: 41 of 41 the same)
        base = KT.plan_words(song(), self.s)
        big = [p for p in base if p.role == "big"][0]
        sub = [p for p in base if p.id == big.id.replace("b", "p")][0]
        come = on_frame(sub.start - 0.1)
        go = on_frame(sub.sung_end + 0.05, up=True)
        self.assertGreater(sub.end - go, KT.END_SOONER)                 # (further from its end than a piece's own reach)
        got = {p.id: p for p in KT.plan_words(song(marks={"starts": [come], "cuts": [go], "sections": [], "hooks": []}),
                                              self.s)}
        self.assertAlmostEqual(got[sub.id].start, come)
        self.assertAlmostEqual(got[sub.id].end, go)
        self.assertAlmostEqual(got[big.id].start, come)
        self.assertAlmostEqual(got[big.id].end, go)

    def test_a_sung_subtitle_goes_on_a_mark_in_its_tail(self):
        # its words sung, it may go on a mark of the song structure up to END_SOONER s before its singing ended and up to
        # END_LATER after it would go (the tail is its way to go: the picture changes or flashes there)
        words = song()
        sub = sorted((p for p in KT.plan_words(words, self.s) if p.role == "sub"), key=lambda p: p.start)[0]
        sung_end = sub.end - self.s["hang"]
        mark = on_frame(sung_end + 0.05, up=True)
        got = {p.id: p for p in KT.plan_words(song(marks={"starts": [mark], "cuts": [], "sections": [mark], "hooks": []}), self.s)}
        self.assertAlmostEqual(got[sub.id].end, mark)
        self.assertAlmostEqual(got[sub.id].start, sub.start)

    def test_the_interludes_title_comes_on_its_head_and_the_last_echo_goes_there(self):
        # a chorus line sung up to 0.1 s before the interlude's head: its subtitle's tail and its large word's echo would lie
        # across the head; the title comes on the head (the coordinator 2026-10-21: nothing came on the break's head),
        # the subtitle goes there and no large word of the chorus is on after it
        head = on_frame(12.0 + 0.2 * 20 - 0.1, up=True)
        lines = [line_of(LONG[0], LONG[1], 12.0 - 0.2 * (len(LONG[1]) - 20))]
        marks = {"starts": [head], "cuts": [], "sections": [head], "hooks": []}
        # (without the interlude, a large word of the chorus is on up to the head: with its subtitle, it goes on the head's
        # mark as its subtitle does; the interlude's rule takes off one across it)
        s = dict(self.s, big_per_line=10.0)                 # (every piece has its large word: the last one reaches it)
        whole = KT.plan_words(song(lines=lines, sections=[{"kind": "chorus", "start": 0.0, "end": head + 14.0}], marks=marks,
                                   credits=[]), s)
        self.assertTrue([p for p in whole if p.role == "big" and p.end > head - 1e-6])
        words = song(lines=lines, marks=marks, credits=[],
                     sections=[{"kind": "chorus", "start": 0.0, "end": head}, {"kind": "interlude", "start": head, "end": head + 8.0},
                               {"kind": "end", "start": head + 8.0, "end": head + 14.0}])
        pieces = KT.plan_words(words, s)
        title = [p for p in pieces if p.role == "interlude"]
        self.assertEqual(len(title), 1)
        self.assertAlmostEqual(title[0].start, head)
        self.assertFalse([p.id for p in pieces if p.role in ("sub", "column", "big") and p.end > head + 1e-6])

    def test_a_sung_time_below_0_is_refused(self):
        for key in ("sung", "phrase"):
            with self.assertRaises(ValueError) as caught:
                KT.check_settings(dict(self.s, **{key: -0.1}))
            self.assertIn(key, str(caught.exception))


def line_of(text, reading, t0, step=0.2):
    return {"text": text, "reading": reading,
            "morae": [[m["kana"], m["c0"], m["v0"], m["v1"]] for m in timed(reading, t0, step)]}


HOOK_READING = "かがやき"                  # かがやき
HOOK_TEXT = "カガヤキ"                     # カガヤキ
HOOKED = ("光の街に輝き", "ひかりのまちにかがやき")   # 光の街に輝き


def song(**extra):
    """a made-up song: two verse lines, two chorus lines (the second ends with the title word), an interlude, the end"""
    words = {"kind": "kinetic_words", "version": 1,
             "lines": [line_of(SKY[0], SKY[1], 2.0), line_of(LONG[0], LONG[1], 6.0), line_of(CHOCO[0], CHOCO[1], 12.0),
                       line_of(HOOKED[0], HOOKED[1], 15.0)],
             "sections": [{"kind": "verse", "start": 1.5, "end": 11.8}, {"kind": "chorus", "start": 11.8, "end": 17.8},
                          {"kind": "interlude", "start": 17.8, "end": 24.0}, {"kind": "end", "start": 24.0, "end": 30.0}],
             "hook": {"reading": HOOK_READING, "text": HOOK_TEXT},
             "interlude": {"text": "SKYLINE"},
             "accents": {"blue": ["光"], "red": ["雨"]},
             "credits": [{"start": 24.5, "end": 28.0, "x": 0.07, "y": 0.5,
                          "rows": [{"role": "MUSIC", "name": "ある作曲者"}, {"role": "MOTION", "name": "SOMEONE"}]}],
             "end": 30.0}
    words.update(extra)
    return words


@unittest.skipUnless(KT, NEEDS)
class PlanTest(unittest.TestCase):
    """which piece goes where and when"""

    @classmethod
    def setUpClass(cls):
        cls.s = KT.default_settings()
        cls.pieces = KT.plan_words(song(), cls.s)

    def of(self, role):
        return [p for p in self.pieces if p.role == role]

    def test_a_piece_comes_with_its_first_syllable_and_stays_about_a_second(self):
        subs = [p for p in self.pieces if p.role in ("sub", "column")]
        self.assertTrue(subs)
        first = [p for p in subs if p.line == 0][0]
        # the vowel of its first mora (0.04 s after its consonant, timed()), less the lead
        self.assertAlmostEqual(first.start, 2.0 + (0.04 if self.s["at_vowel"] else 0.0) - self.s["lead"])
        for p in subs:
            self.assertGreaterEqual(p.end - p.start, self.s["life"][0] - 1e-9)
            self.assertLessEqual(p.end - p.start, self.s["life"][1] + 1e-9)
            self.assertEqual(p.layer, "front")

    def test_the_pieces_of_a_line_take_the_rows_in_turn(self):
        line1 = [p for p in self.pieces if p.line == 1 and p.role == "sub"]
        self.assertGreater(len(line1), 2)
        self.assertEqual([p.y for p in line1[:2]], self.s["sub_rows"][:2])
        # each drifts across: it starts half its way to the left of sub_x, so that half way through its life it is there
        for p in line1:
            middle = p.x + 0.5 * p.drift[0] * (p.end - p.start) * p.rows[0].size / (16.0 / 9.0)
            self.assertAlmostEqual(middle, self.s["sub_x"], places=6)
            self.assertLess(p.x, self.s["sub_x"])

    def test_a_chorus_line_has_large_words_behind_the_dancer(self):
        big = self.of("big")
        # line 3 sings the title word: it is large already (the hook), and has no large word of its own
        self.assertEqual(sorted({p.line for p in big}), [2])
        pieces_of_line = sum(1 for p in self.pieces if p.line == 2 and p.role in ("sub", "column"))
        # big_per_line may be a fraction: the lines with large words take its whole part and one more in turn (the first:
        # floor of it)
        first = int(math.floor(self.s["big_per_line"] + 1e-9))
        self.assertEqual(sum(1 for p in big if p.line == 2), min(first, pieces_of_line))
        self.assertTrue(all(p.layer == "back" for p in big))
        self.assertFalse([p for p in big if p.line in (0, 1)])                  # none in the verse

    def test_a_fraction_of_large_words_a_line_is_kept_over_the_lines(self):
        lines = [line_of(LONG[0], LONG[1], 2.0 + 6.0 * k) for k in range(8)]
        pieces = KT.plan_words(song(lines=lines, sections=[{"kind": "chorus", "start": 0, "end": 100}]),
                               dict(self.s, big_per_line=1.5))
        per_line = [sum(1 for p in pieces if p.role == "big" and p.line == k) for k in range(8)]
        self.assertEqual(per_line, [1, 2, 1, 2, 1, 2, 1, 2])

    def test_a_large_word_is_on_while_its_words_are_sung(self):
        # with its subtitle (the coordinator 2026-10-21, kinetic3: the same words large and small at once are an emphasis;
        # coming after them, as the subtitles are on until sung, it lay over the next line's subtitles 62 % of its time)
        subs = {(p.line, p.rows[0].text.replace(" ", "").strip("「」")): p for p in self.pieces if p.role == "sub"}
        self.assertTrue(self.of("big"))
        for big in self.of("big"):
            text = "".join(r.text for r in big.rows)
            src = subs[(big.line, text)]
            self.assertAlmostEqual(big.start, src.start)
            self.assertAlmostEqual(big.end, src.end)
            self.assertEqual(big.id, src.id.replace("p", "b"))
            # (over a later line's subtitle at most its tail, the time it takes to go)
            for q in self.pieces:
                if q.role in ("sub", "column") and q.line is not None and q.line > big.line:
                    self.assertLessEqual(min(q.end, big.end) - max(q.start, big.start), self.s["hang"] + 1e-6, (big.id, q.id))

    def test_a_large_word_that_is_not_hollow_stays_inside_the_picture(self):
        # 週末の映画館へ, a phrase sung 1.3 s, is one piece: its large word (the first: tilted, on the left) grows by `push` all
        # the while it is on, and at x 0.3 its first character was cut by the picture's edge (kinetic3rev 2026-10-21: three of
        # the MV's tilted words of 7 characters, by up to 70 px of 720).  While whole (come and not yet going) its ink stays
        # inside; a short one keeps its place, and the hollow ones are still cut by the edge (EDGE_X)
        long_line = ("週末の映画館へ", "しゅうまつのえいがかんへ")                  # (made up)
        for line, step, moved in ((long_line, 0.12, True), (("映画", "えいが"), 0.2, False)):
            words = song(lines=[line_of(line[0], line[1], 2.0, step)], sections=[{"kind": "chorus", "start": 0.0, "end": 20.0}],
                         credits=[])
            drawer = KT.Drawer(words, (320, 180), 30, self.s)
            big = [p for p in drawer.pieces if p.role == "big"]
            self.assertEqual(len(big), 1)
            p = big[0]
            self.assertTrue(p.tilt and not p.hollow)
            self.assertEqual(abs(p.x - self.s["big_x"][0]) > 1e-6, moved, (line[0], p.x))
            enter_s, exit_s = KT._times(p)
            frames = [n for n in range(int(math.ceil(p.start * 30)), int(math.ceil(p.end * 30)))
                      if p.start + enter_s <= n / 30.0 < p.end - exit_s]
            self.assertGreater(len(frames), 3)
            for n in frames:
                img = np.zeros((180, 320, 4), np.float32)
                KT.draw_piece(img, drawer.layouts[p.id], KT.piece_state(p, n / 30.0, self.s), self.s)
                a = img[..., 3]
                edge = int((a[:, 0] > 0.1).sum() + (a[:, -1] > 0.1).sum() + (a[0, :] > 0.1).sum() + (a[-1, :] > 0.1).sum())
                self.assertEqual(edge, 0, (line[0], n))
        pieces = KT.plan_words(song(lines=[line_of(LONG[0], LONG[1], 2.0)], sections=[{"kind": "chorus", "start": 0.0, "end": 20.0}],
                                    credits=[]), dict(self.s, big_per_line=4.0))
        hollow = [p for p in pieces if p.role == "big" and p.hollow]
        self.assertTrue(hollow)
        self.assertTrue(all(p.x in KT.EDGE_X for p in hollow), [p.x for p in hollow])

    def test_the_title_word_comes_one_character_a_syllable(self):
        hooks = self.of("hook")
        self.assertEqual(len(hooks), 1)
        h = hooks[0]
        self.assertEqual(h.rows[0].text, HOOK_TEXT)
        self.assertEqual(h.layer, "back")
        # かがやき are the last four morae of the line at 15.0 s, 0.2 s apart: 光の街に is ひかりのまちに (7 morae); each comes
        # at its vowel (0.04 s after its consonant, timed()), less the lead
        vowel = 0.04 if self.s["at_vowel"] else 0.0
        want = [round(15.0 + 0.2 * (7 + k) + vowel - self.s["lead"], 4) for k in range(4)]
        self.assertEqual([round(t, 4) for t in h.char_times], want)

    def test_an_interlude_has_the_title_drifting_behind_and_no_lyric(self):
        inter = self.of("interlude")
        self.assertEqual(len(inter), 1)
        p = inter[0]
        self.assertEqual((p.layer, p.rows[0].text), ("back", "SKYLINE"))
        hook_end = self.of("hook")[0].end
        self.assertGreaterEqual(p.start, max(17.8, hook_end))
        self.assertLessEqual(p.end, 24.0)
        self.assertNotEqual(p.drift[0], 0.0)
        self.assertFalse([q for q in self.pieces if q.role in ("sub", "column", "big") and p.start < q.start < p.end])

    def test_the_title_lies_behind_the_dancer_unless_written_in_front(self):
        # (kineticrev 2026-10-21: in front, the opening title lay over her face for 198 of its 200 frames on the final camera
        # D, its Latin rows across her eyes; behind her, like the large words, she hides a part of it and it never hides her)
        title = {"start": 0.5, "end": 1.8, "rows": [{"text": "SKYLINE", "style": "title"}]}
        got = [p for p in KT.plan_words(song(title=title), self.s) if p.role == "title"]
        self.assertEqual([p.layer for p in got], ["back"])
        got = [p for p in KT.plan_words(song(title=dict(title, layer="front")), self.s) if p.role == "title"]
        self.assertEqual([p.layer for p in got], ["front"])
        with self.assertRaises(ValueError):
            KT.plan_words(song(title=dict(title, layer="over")), self.s)

    def test_the_credits_are_in_front_at_their_time(self):
        cards = self.of("credit")
        self.assertEqual(len(cards), 1)
        c = cards[0]
        self.assertEqual((c.layer, c.start, c.end, c.align), ("front", 24.5, 28.0, "left"))
        self.assertEqual([r.text for r in c.rows], ["MUSIC", "ある作曲者", "MOTION", "SOMEONE"])

    def test_the_ways_to_come_and_go_are_taken_in_the_shares_of_the_mix(self):
        lines = [line_of(SKY[0], SKY[1], 2.0 + 4.0 * k) for k in range(40)]
        pieces = KT.plan_words(song(lines=lines, sections=[{"kind": "verse", "start": 0, "end": 200}]), self.s)
        subs = [p for p in pieces if p.role in ("sub", "column")]
        n = len(subs)
        weights = [w / sum(self.s["enter_mix"]) for w in self.s["enter_mix"]]
        for name, w in zip(KT.ENTERS, weights):
            got = sum(1 for p in subs if p.enter == name)
            self.assertLessEqual(abs(got - w * n), 1.0, (name, got, w * n))
        self.assertGreater(len({p.enter for p in subs[:12]}), 3)               # not one way after another in a block

    def test_the_shares_of_the_lines_are_rounded_not_cut(self):
        # 11 lines at 0.45 in Mincho are 5 (4.95 rounded), not 4 (kineticrev: a floor got through the tests)
        lines = [line_of(SKY[0], SKY[1], 2.0 + 4.0 * k) for k in range(11)]
        s = dict(self.s, mincho_share=0.45)
        pieces = KT.plan_words(song(lines=lines, sections=[{"kind": "verse", "start": 0, "end": 200}]), s)
        self.assertEqual(len({p.line for p in pieces if p.role in ("sub", "column") and p.rows[0].face == "mincho"}), 5)

    def test_a_share_of_the_verses_lines_stands_in_a_column(self):
        lines = [line_of(SKY[0], SKY[1], 2.0 + 4.0 * k) for k in range(30)]
        pieces = KT.plan_words(song(lines=lines, sections=[{"kind": "verse", "start": 0, "end": 200}]), self.s)
        columns = {p.line for p in pieces if p.role == "column"}
        self.assertEqual(len(columns), round(self.s["column_share"] * 30))
        for p in pieces:
            if p.role == "column":
                self.assertTrue(p.vertical)
                self.assertIn(p.x, self.s["column_x"])

    def test_an_outline_goes_round_the_sans_lines_only(self):
        # the outline (2 px at 720 lines) is as wide as a thin Mincho stroke: round a Mincho line it buries the strokes in
        # its colour (typo_analyze read their fill as the outline's blue, L* 42 C* 34), so the Mincho lines have none
        for mincho in (0.0, 1.0):
            s = dict(self.s, mincho_share=mincho, outline_share=1.0)
            subs = [p for p in KT.plan_words(song(), s) if p.role in ("sub", "column")]
            self.assertTrue(subs)
            self.assertEqual({p.rows[0].face for p in subs}, {"mincho" if mincho else "sans"})
            self.assertEqual({p.outline for p in subs}, {not mincho})

    def test_an_accented_word_takes_its_colour(self):
        sub = [p for p in self.pieces if p.line == 0 and p.role in ("sub", "column") and "光" in p.rows[0].text][0]
        k = sub.rows[0].text.index("光")                                          # 光 of 光の街
        self.assertEqual(sub.rows[0].colours[k], "blue")
        self.assertEqual(sub.rows[0].colours[k + 1], "fill")


def on_frame(t, up=False):
    """a time on a frame of 30 fps (the marks of the song structure are frames)"""
    return (math.ceil(t * 30 - 1e-9) if up else math.floor(t * 30 + 1e-9)) / 30.0


@unittest.skipUnless(KT, NEEDS)
class MarksTest(unittest.TestCase):
    """the marks of the MV's shared song structure (the motion graphics' table: the white flash and the punch start on a
    section's first frame and on the title word's, the picture changes on a section's cut): the text comes and goes on them"""

    @classmethod
    def setUpClass(cls):
        # (the pieces cut by characters, as these tests were laid out for: the marks' rules do not depend on the cutting)
        cls.s = dict(KT.default_settings(), sung=0.0, chars=7, chars_min=4, hang=0.0, life=[0.62, 0.77])
        cls.base = {p.id: p for p in KT.plan_words(song(), cls.s)}

    def plan(self, **marks):
        full = {"starts": [], "cuts": [], "sections": [], "hooks": []}
        full.update(marks)
        return {p.id: p for p in KT.plan_words(song(marks=full), self.s)}

    def subs(self):
        return sorted((p for p in self.base.values() if p.role == "sub"), key=lambda p: p.start)

    def test_without_marks_the_plan_is_the_plan_of_before(self):
        records = [KT.piece_record(p) for p in KT.plan_words(song(), self.s)]
        self.assertEqual([KT.piece_record(p) for p in KT.plan_words(song(marks={"starts": [], "cuts": [], "sections": [],
                                                                               "hooks": []}), self.s)], records)

    def test_a_piece_comes_on_a_mark_just_before_or_after_its_time(self):
        a, b, c = self.subs()[0], self.subs()[2], self.subs()[3]
        early = on_frame(a.start - 0.1)                 # 0.1 to 0.13 s before: it comes on the mark
        late = on_frame(c.start + 0.05, up=True)        # 0.05 to 0.08 s after: it waits for it
        far = on_frame(b.start - 0.4)                   # 0.4 s before: too far, it keeps its time
        got = self.plan(starts=[early, far, late])
        self.assertAlmostEqual(got[a.id].start, early)
        self.assertAlmostEqual(got[c.id].start, late)
        self.assertAlmostEqual(got[b.id].start, b.start)
        self.assertAlmostEqual(got[a.id].end, a.end)    # its going stays where it was

    def test_a_piece_is_gone_on_a_cut_just_before_or_after_its_end(self):
        a, b = self.subs()[0], self.subs()[1]
        after = on_frame(a.end + 0.05, up=True)         # the picture changes just after it would go: it goes with it
        before = on_frame(b.end - 0.1)                  # ... or just before: it goes with it too
        got = self.plan(cuts=[after, before])
        self.assertAlmostEqual(got[a.id].end, after)
        self.assertAlmostEqual(got[b.id].end, before)
        self.assertAlmostEqual(got[a.id].start, a.start)

    def test_a_piece_does_not_wait_long_for_a_mark(self):
        # a mark 0.3 s after its time is too late: it keeps its time (it waits MARK_LATER at most; kineticrev)
        c = self.subs()[3]
        late = on_frame(c.start + 0.3, up=True)
        self.assertAlmostEqual(self.plan(starts=[late])[c.id].start, c.start)

    def test_the_title_word_comes_on_its_mark_one_character_a_syllable_and_goes_on_the_next_section(self):
        hook = [p for p in self.base.values() if p.role == "hook"][0]
        at = on_frame(hook.start - 0.07)
        syllables = [at, on_frame(at + 0.21), on_frame(at + 0.43), on_frame(at + 0.64)]
        section = on_frame(syllables[-1] + 0.8)
        got = self.plan(hooks=[{"at": at, "syllables": syllables}], sections=[section], starts=[at, section])
        h = got[hook.id]
        self.assertAlmostEqual(h.start, at)
        self.assertEqual([round(t, 6) for t in h.char_times], [round(t, 6) for t in syllables])
        self.assertAlmostEqual(h.end - h.exit_s, section)          # it starts to go on the next section's mark

    def test_a_title_word_of_the_table_off_its_singing_is_warned_of(self):
        # (kinetic2 2026-10-21: version 2 of the song structure had the title word's syllables an eighth, 0.21 s, early, so its
        # characters came before the singing; kinetic and kineticrev had checked them against the table only)
        hook = [p for p in self.base.values() if p.role == "hook"][0]
        vowels = [t + self.s["lead"] for t in hook.char_times]          # (without marks: each at its vowel, less the lead)

        def words_with(shift):
            syllables = [on_frame(v + shift) for v in vowels]
            return song(marks={"starts": [], "cuts": [], "sections": [], "hooks": [{"at": syllables[0], "syllables": syllables}]})

        for shift, warned in ((-0.21, 1), (0.0, 0), (0.07, 0), (0.15, 1)):
            self.assertEqual(len(KT.hook_warnings(words_with(shift))), warned, shift)
        early = words_with(-0.21)
        self.assertIn("before", KT.hook_warnings(early)[0])
        work = tempfile.mkdtemp()
        try:
            plan = KT.render_sequences(early, work, (320, 180), 30, span=(25.0, 25.1))
            self.assertEqual([w for w in plan["warnings"] if "title word" in w], KT.hook_warnings(early))
            path = os.path.join(work, "words.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(early, f, ensure_ascii=False)
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                self.assertEqual(KT.main(["sheet", path, os.path.join(work, "sheet.json")]), 0)
            self.assertEqual([w for w in json.loads(said.getvalue())["warnings"] if "title word" in w], KT.hook_warnings(early))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_the_interludes_title_comes_and_goes_on_the_sections_marks(self):
        inter = [p for p in self.base.values() if p.role == "interlude"][0]
        hook = [p for p in self.base.values() if p.role == "hook"][0]
        comes = on_frame(max(17.8, hook.char_times[-1] + 0.5), up=True)
        goes = on_frame(inter.end + 0.2, up=True)                  # the next section, just after it would go
        got = self.plan(sections=[comes, goes], starts=[comes, goes])
        p = [q for q in got.values() if q.role == "interlude"][0]
        self.assertAlmostEqual(p.start, comes)
        self.assertAlmostEqual(p.end, goes)

    def test_the_end_card_comes_on_the_end_sections_mark(self):
        card = [p for p in self.base.values() if p.role == "credit"][0]
        mark = on_frame(card.start - 0.13)
        got = self.plan(sections=[mark], starts=[mark])
        self.assertAlmostEqual([q for q in got.values() if q.role == "credit"][0].start, mark)
        far = on_frame(card.start - 1.0)
        got = self.plan(sections=[far], starts=[far])
        self.assertAlmostEqual([q for q in got.values() if q.role == "credit"][0].start, card.start)

    def test_the_marks_are_read_from_the_shared_song_structure(self):
        structure = {"version": 2, "fps": 30,
                     "sections": [{"id": "intro", "frame": 0, "change_frame": 0}, {"id": "chorus", "frame": 357, "change_frame": 355}],
                     "chorus_halves": [{"frame": 420}],
                     "hooks": [{"frame": 492, "syllables": [16.399, 16.613, 16.828, 17.042]}]}
        marks = KT.marks_of(structure)
        self.assertEqual(marks["sections"], [0.0, 357 / 30.0])
        self.assertEqual(marks["starts"], [0.0, 357 / 30.0, 420 / 30.0, 492 / 30.0])
        self.assertEqual(marks["cuts"], [0.0, 355 / 30.0])
        self.assertEqual(marks["hooks"], [{"at": 492 / 30.0, "syllables": [492 / 30.0, 498 / 30.0, 505 / 30.0, 511 / 30.0]}])
        with self.assertRaises(ValueError):
            KT.marks_of(dict(structure, version=1))                  # version 1 has no frames


@unittest.skipUnless(KT, NEEDS)
class MotionTest(unittest.TestCase):
    """how a piece moves from the frame it comes on to the frame it is gone"""

    @classmethod
    def setUpClass(cls):
        cls.s = KT.default_settings()

    def piece(self, enter, exit, **kw):
        row = KT.Row("青空に歌う", 0.04)
        p = KT.Piece("t", kw.pop("role", "sub"), "front", [row], 10.0, 11.2, 0.5, 0.7, enter=enter, exit=exit, **kw)
        p.drift = KT._drift(p, self.s)
        return p

    def frames(self, p, fps=30):
        return [(n / float(fps), KT.piece_state(p, n / float(fps), self.s)) for n in range(int(p.start * fps) - 2, int(p.end * fps) + 2)]

    def test_nothing_shows_before_it_comes_or_after_it_is_gone(self):
        p = self.piece("rise", "lift")
        self.assertIsNone(KT.piece_state(p, 9.99, self.s))
        self.assertIsNone(KT.piece_state(p, 11.2, self.s))
        self.assertAlmostEqual(KT.piece_state(p, 10.0, self.s).alpha, 0.0)       # a fade starts from nothing
        self.assertGreater(KT.piece_state(p, 10.5, self.s).alpha, 0.99)
        self.assertLess(KT.piece_state(p, 11.2 - 1.0 / 30, self.s).alpha, 0.05)

    def test_it_stands_still_only_between_coming_and_going(self):
        # tools/typo_analyze.py reads a text as still when it moves less than 0.03 of its height and grows less than
        # 0.6 % from one frame to the next (STILL, STILL_SCALE).  The references' lines stand still 0.05 s at the median
        # (typorev): ours drift slowly, below that, and come and go by moves, zooms, fades and blurs: they stand still at
        # most between the end of their way to come and the start of their way to go (a frame either side)
        for enter in KT.ENTERS:
            for exit in KT.EXITS:
                p = self.piece(enter, exit)
                p.enter_s = {"cut": 0.0, "pop": KT.POP_S}.get(enter, p.enter_s)
                p.exit_s = {"cutout": 0.0, "popout": KT.POP_S}.get(exit, p.exit_s)
                frames = [(t, st) for t, st in self.frames(p) if st is not None]
                still = []
                for (t0, a), (t1, b) in zip(frames, frames[1:]):
                    moved = math.hypot(b.dx - a.dx, b.dy - a.dy)
                    grew = abs(math.log(b.scale / a.scale))
                    faded = abs(b.alpha - a.alpha) > 0.02 or b.blur != a.blur or b.split or a.split
                    chars = a.chars != b.chars
                    seen = min(a.alpha, b.alpha) >= 0.15          # (fainter, the tool does not see it at all)
                    if seen and moved < 0.03 and grew < 0.006 and not faded and not chars:
                        still.append(t1)
                enter_s, exit_s = KT._times(p)
                if not MotionTest.EASED.get(enter) or not MotionTest.EASED.get(exit):
                    continue                              # a quick way: still from it to the next way, by design
                for t in still:                                   # (an eased way is slow at its end: up to 5 frames)
                    if not KT.MOVES[enter].get("overshoot"):      # (one that overshoots stops where it turns back)
                        self.assertGreaterEqual(t, p.start + enter_s - 5 / 30.0 - 1e-9, (enter, exit, t))
                    self.assertLessEqual(t, p.end - exit_s + 5 / 30.0 + 1e-9, (enter, exit, t))

    # the quick ways (a cut, a pop, a glitch: their few frames are the way) leave it still up to them, by design
    EASED = {name: not (KT.MOVES[name].get("cut") or KT.MOVES[name].get("pop") or KT.MOVES[name].get("glitch"))
             for name in KT.MOVES} if KT else {}

    def test_the_large_words_grow_all_the_while(self):
        p = self.piece("zoom", "zoomout", role="big", push=self.s["push"])
        seq = [st for _, st in self.frames(p) if st is not None]
        for a, b in zip(seq, seq[1:]):
            self.assertTrue(abs(math.log(b.scale / a.scale)) >= 0.006 or math.hypot(b.dx - a.dx, b.dy - a.dy) >= 0.03)

    def test_characters_one_after_another_come_in_their_order(self):
        p = self.piece("type", "lift")
        crossed = []
        for k in range(5):
            for t, st in self.frames(p, fps=240):
                if st is not None and st.chars and st.chars[k][0] >= 0.5:
                    crossed.append(t)
                    break
        steps = [b - a for a, b in zip(crossed, crossed[1:])]
        self.assertTrue(all(abs(d - self.s["stagger"]) < 0.01 for d in steps), steps)

    def test_a_glitch_parts_the_colours_for_its_frames_and_flickers_once(self):
        p = self.piece("glitch", "lift")
        seq = [st for _, st in self.frames(p) if st is not None]
        n = int(self.s["glitch_frames"])
        self.assertTrue(all(st.split > 0 for st in seq[:n]))
        self.assertTrue(all(st.split == 0 for st in seq[n:]))
        self.assertEqual(sum(1 for st in seq[:n] if st.alpha == 0.0), 1)

    def test_a_cut_is_there_at_once(self):
        p = self.piece("cut", "cutout", enter_s=0.0, exit_s=0.0)
        self.assertEqual(KT.piece_state(p, 10.0, self.s).alpha, 1.0)
        self.assertEqual(KT.piece_state(p, 11.2 - 1e-6, self.s).alpha, 1.0)

    # (the tests below: kineticrev 2026-10-21, ways of the motion that broken copies of the tool got through)

    def test_after_a_cut_in_it_stands_still_before_it_drifts(self):
        # the tool reads a cut only next to a text that stands still: STILL_AT_CUT s still after a cut in, before a cut out
        p = self.piece("cut", "cutout", enter_s=0.0, exit_s=0.0)
        at = lambda t: KT.piece_state(p, t, self.s).dx
        self.assertEqual(at(10.0), at(10.0 + KT.STILL_AT_CUT - 0.01))
        self.assertGreater(at(10.0 + KT.STILL_AT_CUT + 0.2), at(10.0))
        self.assertEqual(at(11.2 - 1e-6), at(11.2 - KT.STILL_AT_CUT + 0.01))

    def test_a_short_piece_shares_its_life_between_coming_and_going(self):
        p = KT.Piece("t", "sub", "front", [KT.Row("青空に歌う", 0.04)], 10.0, 10.5, 0.5, 0.7, enter="fadein", exit="fadeout",
                     enter_s=0.4, exit_s=0.4)
        self.assertEqual(KT._times(p), (0.25, 0.25))
        self.assertGreater(KT.piece_state(p, 10.25, self.s).alpha, 0.95)          # whole half way, if only for a moment

    def test_a_pop_is_whole_in_two_frames(self):
        p = self.piece("pop", "popout", enter_s=KT.POP_S, exit_s=KT.POP_S)
        self.assertGreater(KT.piece_state(p, 10.0 + 2 / 30.0, self.s).alpha, 0.99)
        self.assertLess(KT.piece_state(p, 10.0 + 1 / 60.0, self.s).alpha, 0.5)

    def test_the_hooks_characters_come_at_their_syllables(self):
        p = self.piece("fadein", "glitchout", char_times=(10.0, 10.2, 10.4, 10.6, 10.8), enter_s=0.0)
        st = KT.piece_state(p, 10.3, self.s)
        self.assertGreater(st.chars[0][0], 0.9)
        self.assertGreater(st.chars[1][0], 0.0)
        self.assertLess(st.chars[1][0], 0.8)                 # ... still coming (HOOK_COME s from its syllable)
        self.assertGreater(st.chars[1][3], 1.0)              # ... from larger
        self.assertEqual(st.chars[2][0], 0.0)
        self.assertEqual(st.chars[4][0], 0.0)


def ink(img):
    """the alpha of a straight RGBA picture (0..1)"""
    return img[..., 3].astype(np.float64) / 255.0


@unittest.skipUnless(KT, NEEDS)
class DrawTest(unittest.TestCase):
    """the pixels of a piece"""

    SIZE = (960, 540)

    @classmethod
    def setUpClass(cls):
        cls.s = KT.default_settings()
        cls.book = KT.FontBook()

    def draw(self, piece, t=None, **settings):
        s = dict(self.s, **settings)
        layout = KT.layout_piece(piece, self.SIZE, self.book, s)
        frame = np.zeros((self.SIZE[1], self.SIZE[0], 4), np.float32)
        t = piece.start + 0.6 if t is None else t
        KT.draw_piece(frame, layout, KT.piece_state(piece, t, s), s)
        return KT.straight(frame)

    def sub(self, text="青空に歌う", **kw):
        p = KT.Piece("t", kw.pop("role", "sub"), "front", [KT.Row(text, kw.pop("size", 0.04), colours=kw.pop("colours", ()))],
                     10.0, 11.2, kw.pop("x", 0.5), kw.pop("y", 0.6), enter="fadein", exit="fadeout", enter_s=0.2, exit_s=0.2, **kw)
        return p

    def test_the_characters_are_as_tall_as_the_size(self):
        a = ink(self.draw(self.sub(glow=0.0)))
        rows = np.nonzero(a.max(axis=1) > 0.5)[0]
        height = (rows.max() - rows.min() + 1) / float(self.SIZE[1])
        self.assertGreater(height, 0.04 * 0.75)
        self.assertLess(height, 0.04 * 1.25)
        cols = np.nonzero(a.max(axis=0) > 0.5)[0]
        self.assertAlmostEqual((cols.min() + cols.max()) / 2.0 / self.SIZE[0], 0.5, delta=0.06)   # it drifted a little

    def test_a_glow_lights_round_the_strokes(self):
        lit = ink(self.draw(self.sub(glow=0.5)))
        bare = ink(self.draw(self.sub(glow=0.0)))
        cv2 = KT._cv2()
        strokes = (bare > 0.5).astype(np.uint8)
        near = cv2.dilate(strokes, np.ones((9, 9), np.uint8)) - cv2.dilate(strokes, np.ones((3, 3), np.uint8))
        self.assertGreater(lit[near > 0].mean(), 0.05)
        self.assertLess(bare[near > 0].mean(), 0.02)

    def test_a_tilted_word_leans_by_the_tilt(self):
        p = self.sub("アアアアア", size=0.1, glow=0.0, tilt=-20.0, role="big")
        a = ink(self.draw(p))
        ys, xs = np.nonzero(a > 0.5)
        cov = np.cov(np.vstack([xs, ys]).astype(np.float64))
        w, v = np.linalg.eigh(cov)
        major = v[:, np.argmax(w)]
        angle = math.degrees(math.atan2(major[1], major[0]))
        angle = (angle + 90) % 180 - 90
        self.assertAlmostEqual(angle, -20.0, delta=3.0)

    def test_a_hollow_word_is_only_its_edge(self):
        p = self.sub("■", size=0.2, glow=0.0, hollow=True, role="big")
        a = ink(self.draw(p))
        ys, xs = np.nonzero(a > 0.5)
        cy, cx = int(ys.mean()), int(xs.mean())
        self.assertLess(a[cy - 5:cy + 5, cx - 5:cx + 5].max(), 0.1)              # the middle of the square is empty
        self.assertGreater(a.max(), 0.9)

    def test_an_outline_is_dark_round_a_light_fill(self):
        img = self.draw(self.sub("■", size=0.1, glow=0.0, outline=True))
        a = ink(img)
        ys, xs = np.nonzero(a > 0.9)
        cy, cx = int(ys.mean()), int(xs.mean())
        fill = img[cy, cx, :3].astype(float)
        edge_x = xs[ys == cy].min()
        edge = img[cy, edge_x, :3].astype(float)
        self.assertGreater(fill.mean(), 180)
        self.assertLess(edge.mean(), 90)

    def test_a_column_stands_upright(self):
        p = self.sub(vertical=True, role="column", x=0.1)
        a = ink(self.draw(p))
        ys, xs = np.nonzero(a > 0.5)
        self.assertGreater(ys.max() - ys.min(), 3 * (xs.max() - xs.min()))

    def test_mincho_is_drawn_from_the_file_of_the_nearest_weight(self):
        # Shippori Mincho has a file a weight: 600 takes the Bold (700) of Regular (400) and Bold, 450 the Regular
        book = KT.FontBook()
        a, b = book.files["sans"], book.files["serif"]
        book.mincho = {400: a, 700: b}
        self.assertEqual(book.font("mincho", 24, 600).path, b)
        self.assertEqual(book.font("mincho", 24, 450).path, a)

    def test_an_accented_character_takes_its_colour(self):
        img = self.draw(self.sub("光の街", glow=0.0, colours=("blue", "fill", "fill")))
        a = ink(img)
        cols = np.nonzero(a.max(axis=0) > 0.5)[0]
        first = img[:, cols.min():cols.min() + 8][..., :3][a[:, cols.min():cols.min() + 8] > 0.9]
        self.assertGreater(first[:, 2].mean() - first[:, 0].mean(), 60)            # blue: more blue than red


@unittest.skipUnless(KT, NEEDS)
class SequencesTest(unittest.TestCase):
    """the two layers written for tools/mv_look.py"""

    def test_the_layers_hold_their_pieces_frame_by_frame(self):
        work = tempfile.mkdtemp()
        try:
            s = KT.default_settings()
            pieces = KT.plan_words(song(), s)
            big = [p for p in pieces if p.role == "big"][0]
            sub = [p for p in pieces if p.id == big.id.replace("b", "p")][0]               # the subtitle it repeats
            a = round(sub.start, 1)
            plan = KT.render_sequences(song(), work, (320, 180), 30, span=(a, a + 2.0))
            by = {c["layer"]: c for c in plan["cues"]}
            self.assertEqual(sorted(by), ["back", "front"])
            for layer, cue in by.items():
                self.assertEqual((cue["start_frame"], cue["frames"], cue["x"], cue["y"]), (int(round(a * 30)), 60, 0, 0))
                folder = os.path.dirname(cue["pattern"])
                self.assertEqual(sorted(os.listdir(folder)), ["f%05d.png" % n for n in range(60)])
            at_sub = int(round((sub.start + 0.5 * (sub.end - sub.start) - a) * 30))       # the subtitle half way through
            at_big = int(round((big.start + 0.5 - a) * 30))                                 # the large word come
            front = np.asarray(Image.open(by["front"]["pattern"] % at_sub))
            back = np.asarray(Image.open(by["back"]["pattern"] % at_big))
            self.assertEqual(front.shape, (180, 320, 4))
            self.assertGreater(front[..., 3].max(), 200)                               # the subtitle of the chorus line
            self.assertGreater(back[..., 3].max(), 100)                                # its large word, with it
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_span_starts_on_the_frame_nearest_its_start(self):
        work = tempfile.mkdtemp()
        try:
            plan = KT.render_sequences(song(), work, (320, 180), 30, span=(2.5 + 0.6 / 30.0, 2.7))   # frame 75.6: 76
            self.assertEqual([c["start_frame"] for c in plan["cues"]], [76])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_span_with_nothing_on_a_layer_has_no_sequence_for_it(self):
        work = tempfile.mkdtemp()
        try:
            plan = KT.render_sequences(song(), work, (320, 180), 30, span=(2.5, 3.0))       # a verse: subtitles only
            self.assertEqual([c["layer"] for c in plan["cues"]], ["front"])
        finally:
            shutil.rmtree(work, ignore_errors=True)


@unittest.skipUnless(KT and FFMPEG, NEEDS + ", ffmpeg and ffprobe")
class OverTest(unittest.TestCase):
    """both layers over a still (the measuring video for tools/typo_analyze.py)"""

    def test_the_text_is_laid_over_the_picture_for_the_span(self):
        work = tempfile.mkdtemp()
        try:
            still = os.path.join(work, "still.png")
            Image.new("RGB", (320, 180), (30, 40, 60)).save(still)
            out = os.path.join(work, "out.mp4")
            done = KT.over_command(still, song(), out, start=12.0, end=13.0, fps=30)
            self.assertEqual(done["frames"], 30)
            probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                    "stream=nb_read_frames,width,height,color_space", "-of", "json", out],
                                   capture_output=True, text=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((int(stream["nb_read_frames"]), stream["width"], stream["height"], stream["color_space"]),
                             (30, 320, 180, "bt709"))
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vf", "select=eq(n\\,20)", "-frames:v", "1", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            frame = np.frombuffer(raw, np.uint8).reshape(180, 320, 3)
            self.assertGreater(frame.max(), 150)                      # the text, light on the dark picture
        finally:
            shutil.rmtree(work, ignore_errors=True)


    def test_laid_in_numpy_it_is_the_picture_of_the_layers_pngs(self):
        # over a still the layers are laid in numpy instead of through the PNGs mv_look reads: the same picture but for the
        # rounding of the PNGs' 8 bits
        work = tempfile.mkdtemp()
        try:
            base = (np.random.default_rng(3).random((180, 320, 3)) * 0.5).astype(np.float32)
            drawer = KT.Drawer(song(), (320, 180), 30)
            big = [p for p in drawer.pieces if p.role == "big"][0]
            a = round(big.start + 0.1, 1)                                     # a large word and its subtitle are on
            plan = KT.render_sequences(song(), work, (320, 180), 30, span=(a, a + 0.5))
            for n in (3, 9, 14):
                t = a + n / 30.0
                fast = KT.compose(base, drawer, t)
                slow = base.copy()
                for cue in sorted(plan["cues"], key=lambda c: KT.LAYERS.index(c["layer"])):
                    layer = np.asarray(Image.open(cue["pattern"] % n), np.float32) / 255.0
                    slow = slow * (1.0 - layer[..., 3:4]) + layer[..., :3] * layer[..., 3:4]
                self.assertIsNotNone(fast)
                self.assertLess(np.abs(fast - slow).max(), 3.0 / 255.0)
        finally:
            shutil.rmtree(work, ignore_errors=True)


@unittest.skipUnless(KT, NEEDS)
class CommandTest(unittest.TestCase):
    """the words file made from the MV's files, and the sheet"""

    def test_words_then_sheet(self):
        work = tempfile.mkdtemp()
        try:
            cues = {"cues": [{"id": "lyric00", "start": 2.0, "end": 5.0, "style": "lyric", "text": SKY[0]},
                             {"id": "lyric01", "start": 6.0, "end": 11.0, "style": "lyric", "text": LONG[0]},
                             {"id": "title", "start": 0.5, "end": 1.5, "text": "T", "style": "logo"}]}
            align = [dict(m, line=0) for m in timed(SKY[1], 2.0)] + [dict(m, line=1) for m in timed(LONG[1], 6.0)] + \
                [dict(m, line=2) for m in timed(HOOK_READING, 12.0)]
            files = {"cues.json": cues, "align.json": align,
                     "structure.json": {"sections": [{"kind": "verse", "start": 0, "end": 11.9}, {"kind": "outro", "start": 11.9, "end": 14}],
                                        "hook": {"reading": HOOK_READING, "text": HOOK_TEXT}}}
            for name, data in files.items():
                with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            with open(os.path.join(work, "lines.tsv"), "w", encoding="utf-8") as f:
                f.write("# start\tend\tline\n2.0\t5.0\t%s\n6.0\t11.0\t%s\n12.0\t13.0\t%s\n" % (SKY[1], LONG[1], HOOK_READING))
            p = lambda name: os.path.join(work, name)
            argv = ["words", p("words.json"), "--cues", p("cues.json"), "--lines", p("lines.tsv"), "--align", p("align.json"),
                    "--structure", p("structure.json")]
            self.assertEqual(KT.main(argv), 0)
            words = KT.load_words(p("words.json"))
            self.assertEqual([ln["text"] for ln in words["lines"]], [SKY[0], LONG[0], None])   # the third line has no cue
            self.assertEqual(KT.main(["sheet", p("words.json"), p("sheet.json")]), 0)
            with open(p("sheet.json"), encoding="utf-8") as f:
                sheet = json.load(f)
            roles = [x["role"] for x in sheet["pieces"]]
            self.assertIn("hook", roles)                                   # the line without text is its title word only
            self.assertEqual(sum(1 for x in sheet["pieces"] if x["line"] == 2 and x["role"] != "hook"), 0)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_cue_that_is_not_its_line_is_refused(self):
        cues = {"cues": [{"id": "lyric00", "start": 9.0, "end": 12.0, "style": "lyric", "text": SKY[0]}]}
        with self.assertRaises(ValueError):
            KT.build_words(cues, "2.0\t5.0\t%s\n" % SKY[1], [dict(m, line=0) for m in timed(SKY[1], 2.0)])


@unittest.skipUnless(KT, NEEDS)
class CreditsTest(unittest.TestCase):
    """the end credits are there long enough and large enough to read"""

    def test_every_card_is_whole_for_most_of_its_time_and_readable(self):
        s = KT.default_settings()
        pieces = [p for p in KT.plan_words(song(), s) if p.role == "credit"]
        for p in pieces:
            whole = [n / 30.0 for n in range(int(p.start * 30), int(p.end * 30))
                     if KT.piece_state(p, n / 30.0, s) is not None and KT.piece_state(p, n / 30.0, s).alpha > 0.95]
            self.assertGreater(len(whole) / 30.0, (p.end - p.start) - 2 * s["credit_fade"] - 0.1)
            self.assertGreaterEqual(min(r.size for r in p.rows), 0.022)


@unittest.skipUnless(KT, NEEDS)
class VocalTest(unittest.TestCase):
    """the singer is named in one place, the words file's vocal ({latin, name}): the title, the tag and the credits write
    {vocal.latin} and {vocal.name} where the singer goes, so that a change of the voice is one change (kineticrev,
    2026-10-21: the title said one singer and the credits another, in three texts of two files)"""

    def words(self, vocal, **extra):
        cards = {"title": {"start": 0.5, "end": 1.8, "rows": [{"text": "SKYLINE", "style": "latin"},
                                                               {"text": "feat. {vocal.latin}", "style": "small"}]},
                 "tag": {"text": "SKYLINE / {vocal.latin}", "start": 2.0, "end": 20.0},
                 "credits": [{"start": 24.5, "end": 28.0, "rows": [{"role": "MUSIC", "name": "ある作曲者"},
                                                                   {"role": "VOCAL", "name": "{vocal.name}"}]}]}
        words = song(**dict(cards, **extra))
        if vocal is not None:
            words["vocal"] = vocal
        return words

    def texts(self, words):
        pieces = KT.plan_words(words, KT.default_settings())
        return {p.role: [r.text for r in p.rows] for p in pieces if p.role in ("title", "tag", "credit")}

    def test_the_title_the_tag_and_the_credits_take_the_singer_from_one_place(self):
        for latin, name in (("HATSUNE MIKU", "初音ミク"), ("KAGAMINE RIN", "鏡音リン")):
            got = self.texts(self.words({"latin": latin, "name": name}))
            self.assertEqual(got["title"], ["SKYLINE", "feat. " + latin])
            self.assertEqual(got["tag"], ["SKYLINE / " + latin])
            self.assertEqual(got["credit"], ["MUSIC", "ある作曲者", "VOCAL", name])

    def test_texts_without_the_singer_are_as_written(self):
        words = song(title={"start": 0.5, "end": 1.8, "rows": [{"text": "feat. SOMEONE", "style": "small"}]})
        self.assertEqual(self.texts(words)["title"], ["feat. SOMEONE"])
        self.assertEqual(self.texts(dict(words, vocal={"latin": "A B", "name": "エー"}))["title"], ["feat. SOMEONE"])

    def test_a_singer_written_in_but_not_named_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            KT.plan_words(self.words(None), KT.default_settings())
        self.assertIn("vocal", str(caught.exception))
        with self.assertRaises(ValueError):
            KT.check_words(self.words({"latin": "HATSUNE MIKU"}))                 # no name for the credits
        with self.assertRaises(ValueError):
            KT.check_words(self.words({"latin": "A", "name": "B", "kana": "C"}))   # not a form of the singer
        with self.assertRaises(ValueError):
            KT.check_words(self.words({"latin": "A", "name": "B"}, tag={"text": "{vocal.kana}", "start": 2.0, "end": 3.0}))
        with self.assertRaises(ValueError):
            KT.check_words(self.words({"latin": "", "name": "B"}))

    def test_two_singers_in_the_two_forms_are_warned_of(self):
        # (the words file of 2026-10-21 named Kagamine Rin in the title and Hatsune Miku in the credits)
        mixed = self.words({"latin": "KAGAMINE RIN", "name": "初音ミク"})
        self.assertEqual(len(KT.vocal_warnings(mixed)), 1)
        self.assertEqual(KT.vocal_warnings(self.words({"latin": "KAGAMINE RIN", "name": "鏡音リン"})), [])
        self.assertEqual(KT.vocal_warnings(self.words({"latin": "SOMEONE", "name": "初音ミク"})), [])     # not known
        work = tempfile.mkdtemp()
        try:
            plan = KT.render_sequences(mixed, work, (320, 180), 30, span=(25.0, 25.1))
            self.assertEqual([w for w in plan["warnings"] if "singer" in w], KT.vocal_warnings(mixed))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_the_structure_carries_the_singer_into_the_words_file(self):
        cues = {"cues": [{"id": "lyric00", "start": 2.0, "end": 5.0, "style": "lyric", "text": SKY[0]}]}
        vocal = {"latin": "KAGAMINE RIN", "name": "鏡音リン"}
        words = KT.build_words(cues, "2.0\t5.0\t%s\n" % SKY[1], [dict(m, line=0) for m in timed(SKY[1], 2.0)],
                               structure={"vocal": vocal, "tag": {"text": "{vocal.latin}", "start": 1.0, "end": 9.0}})
        self.assertEqual(words["vocal"], vocal)
        self.assertEqual(self.texts(words)["tag"], ["KAGAMINE RIN"])


@unittest.skipUnless(KT, NEEDS)
class LookTest(unittest.TestCase):
    """tools/mv_look.py: the look's text2 section; without it the look is the look of before"""

    @classmethod
    def setUpClass(cls):
        cls.mv_look = load_tool("mv_look")

    def test_by_default_the_text_of_before(self):
        look = self.mv_look.merge_look({})
        self.assertEqual(look["text2"]["on"], 0)

    def test_its_values_need_it_on(self):
        with self.assertRaises(ValueError) as caught:
            self.mv_look.merge_look({"text2": {"glow": 0.45}})
        self.assertIn("text2.on 1", str(caught.exception))
        self.mv_look.merge_look({"text2": {"on": 1, "glow": 0.45}})

    def test_a_wrong_value_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            self.mv_look.merge_look({"text2": {"on": 1, "chars_min": 9}})
        self.assertIn("chars_min", str(caught.exception))

    def test_the_prepared_note_holds_the_code_of_the_kinetic_text_when_it_is_on(self):
        # (tools/mv_chunks.py -Resume reads the note: a change of tools/kinetic_text.py must draw the text again)
        work = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(work, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
            spec = importlib.util.spec_from_file_location("mv_look_copy", os.path.join(work, "tools", "mv_look.py"))
            copy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(copy)
            on, off = copy.merge_look({"text2": {"on": 1}}), copy.merge_look({})
            keys = [copy.prepared_key(look, (1280, 720), 30, None) for look in (on, off)]
            with open(os.path.join(work, "tools", "kinetic_text.py"), "a", encoding="utf-8") as f:
                f.write("\n# changed\n")
            self.assertNotEqual(copy.prepared_key(on, (1280, 720), 30, None), keys[0])
            self.assertEqual(copy.prepared_key(off, (1280, 720), 30, None), keys[1])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_the_prepared_note_of_a_look_without_it_is_the_note_of_before(self):
        look = self.mv_look.merge_look({})
        before = {k: v for k, v in look.items() if k != "text2"}
        self.assertEqual(self.mv_look.prepared_key(look, (1280, 720), 30, None),
                         self.mv_look.prepared_key(before, (1280, 720), 30, None))
        on = self.mv_look.merge_look({"text2": {"on": 1}})
        self.assertNotEqual(self.mv_look.prepared_key(on, (1280, 720), 30, None),
                            self.mv_look.prepared_key(look, (1280, 720), 30, None))

    def test_with_it_on_the_text_plan_is_the_kinetic_text(self):
        work = tempfile.mkdtemp()
        try:
            path = os.path.join(work, "words.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(song(), f, ensure_ascii=False)
            look = self.mv_look.merge_look({"text2": {"on": 1}})
            pieces = KT.plan_words(song(), look["text2"])
            big = [p for p in pieces if p.role == "big"][0]                   # a large word and the subtitle it came with
            a = round(big.start + 0.1, 1)
            plan = self.mv_look.text_plan(path, work, (320, 180), 30, look, span=(a, a + 0.5))
            self.assertEqual(sorted(c["id"] for c in plan["cues"]), ["kinetic_back", "kinetic_front"])
            self.assertTrue(all(c["frames"] == 15 and c["start_frame"] == int(round(a * 30)) for c in plan["cues"]))
        finally:
            shutil.rmtree(work, ignore_errors=True)


@unittest.skipUnless(KT and FFMPEG, NEEDS + ", ffmpeg and ffprobe")
class RenderTest(unittest.TestCase):
    """tools/mv_look.py with text2 on, rendered for real as tools/mv_chunks.py renders a chunk: folded with the text prepared
    once for the whole song (--workers: `prepare`, then `render --prepared`) it is the chunk folded with its own work folder
    (`render --work` draws only the excerpt's frames), byte for byte; and the text in it is the kinetic text of its seconds
    (both layers, where and when the plan has them)"""

    @classmethod
    def setUpClass(cls):
        cls.mv_look = load_tool("mv_look")
        cls.folder = tempfile.mkdtemp()
        cls.words = os.path.join(cls.folder, "words.json")
        with open(cls.words, "w", encoding="utf-8") as f:
            json.dump(song(), f, ensure_ascii=False)
        cls.settings = cls.mv_look.merge_look({"text2": {"on": 1}})["text2"]
        big = [p for p in KT.plan_words(song(), cls.settings) if p.role == "big"][0]
        cls.at = round(big.start + 0.1, 1)                       # a large word (behind) and the subtitles (in front) are on
        fg = os.path.join(cls.folder, "fg120.avi")                # no dancer: nothing at 120 fps from 0.2 s before
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=320x180:r=120,format=rgba",
                        "-frames:v", "144", "-c:v", "rawvideo", "-pix_fmt", "bgra", fg], check=True, stdin=subprocess.DEVNULL)
        looks = {}
        for name, text2 in (("on", {"on": 1}), ("off", None)):
            looks[name] = os.path.join(cls.folder, "look_%s.json" % name)
            look = {"beams": {"loop_seconds": 1}, "flares": [0.5], "flare": {"frames": 4}, "lens": {"grain": 0}}
            if text2:
                look["text2"] = text2
            with open(looks[name], "w", encoding="utf-8") as f:
                json.dump(look, f)
        prepared = os.path.join(cls.folder, "prepared")
        cls.codes = [cls.answer(["prepare", looks["on"], prepared, "--size", "320x180", "--fps", "30", "--cues", cls.words])]
        common = ["--subframes", "4", "--offset", "%.6f" % (cls.at - 0.2), "--from", "%.6f" % cls.at,
                  "--to", "%.6f" % (cls.at + 0.5)]
        for name, look, extra in (("worked", "on", ["--cues", cls.words, "--work", os.path.join(cls.folder, "work")]),
                                  ("prepared", "on", ["--cues", cls.words, "--prepared", prepared]),
                                  ("plain", "off", ["--work", os.path.join(cls.folder, "plain")])):
            cls.codes.append(cls.answer(["render", fg, looks[look], os.path.join(cls.folder, name + ".mp4")] + common + extra))

    @classmethod
    def answer(cls, argv):
        """mv_look.main(argv) as the drivers run it: its exit code (its one line of JSON goes nowhere)"""
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return cls.mv_look.main(argv)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, name):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, name + ".mp4"), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = 320 * 180 * 3
        return [np.frombuffer(raw[i * n:(i + 1) * n], np.uint8).reshape(180, 320, 3).astype(np.int16)
                for i in range(len(raw) // n)]

    def test_prepared_once_it_is_the_chunk_drawn_on_its_own_byte_for_byte(self):
        self.assertEqual(self.codes, [0, 0, 0, 0])
        with open(os.path.join(self.folder, "prepared.mp4"), "rb") as f, open(os.path.join(self.folder, "worked.mp4"), "rb") as g:
            self.assertEqual(f.read(), g.read())
        self.assertEqual(len(self.frames("prepared")), 15)

    def test_its_text_is_the_kinetic_text_of_its_frames(self):
        # where the video has the text (the render with it less the render without) is where the plan has it at that frame of
        # the song, and not where it has it a frame or two before or after (where the text moves, fades or changes)
        self.assertEqual(self.codes, [0, 0, 0, 0])
        drawer = KT.Drawer(song(), (320, 180), 30, self.settings)

        def planned(n):
            alpha = np.zeros((180, 320), np.float32)
            for layer in KT.LAYERS:
                img, box = drawer.frame(self.at + n / 30.0, layer)
                if box:
                    alpha = np.maximum(alpha, img[..., 3])
            return alpha

        def shape(alpha):
            return alpha / max(float(alpha.max()), 1e-6)
        texts, plains = self.frames("worked"), self.frames("plain")
        self.assertEqual(len(texts), len(plains))
        timed = 0
        for n in range(len(texts)):
            seen = np.abs(texts[n] - plains[n]).max(axis=2).astype(np.float32)
            maps = {k: planned(n + k) for k in (-2, -1, 0, 1, 2)}
            # (how alike the text of the video and the plan's alpha are, whatever the fade: their correlation)
            alike = {k: float(np.corrcoef(seen.ravel(), m.ravel())[0, 1]) for k, m in maps.items()}
            self.assertGreater(alike[0], 0.8, (n, alike))                     # the letters where the plan has them, nothing else
            if float(np.abs(shape(maps[-1]) - shape(maps[1])).sum()) >= 30:   # (the text moves or changes about this frame)
                self.assertEqual(max(alike, key=alike.get), 0, (n, alike))
                timed += 1
        self.assertGreaterEqual(timed, 3)


@unittest.skipUnless(KT and FFMPEG, NEEDS + ", ffmpeg and ffprobe")
class LayerOrderTest(unittest.TestCase):
    """tools/mv_look.py lays the kinetic text where the MV's look puts it among the other layers (kineticrev, 2026-10-21):
    the back layer behind the dancer (she hides it, it shows beside her), the front one over her; the motion graphics' fade
    to black (mograph, hold -1: the end of the song) covers the back layer and leaves the front one (the end credits on the
    black); the grade of light3 (light.grade) colours the back layer with the stage and the dancer, not the front one.
    Rendered for real through an opaque made-up dancer (a column in the middle of the picture), with large subtitles that
    fade in and out quickly (so that their strokes are whole for most of their life at 180 lines)"""

    SIZE = (320, 180)
    COLUMN = (96, 224)                    # the dancer: x from, x to (all rows), opaque
    FADE = [1.0 if name == "fadein" else 0.0 for name in KT.ENTERS] if KT else []
    OUT = [1.0 if name == "fadeout" else 0.0 for name in KT.EXITS] if KT else []

    @classmethod
    def setUpClass(cls):
        cls.mv_look = load_tool("mv_look")
        cls.folder = tempfile.mkdtemp()
        cls.words = os.path.join(cls.folder, "words.json")
        with open(cls.words, "w", encoding="utf-8") as f:
            json.dump(song(), f, ensure_ascii=False)
        text2 = {"on": 1, "sub_size": 0.1, "enter": 0.1, "exit": 0.1, "glow": 0.0, "outline_share": 0.0, "shadow_share": 0.0,
                 "enter_mix": cls.FADE, "exit_mix": cls.OUT, "big_enter_mix": cls.FADE, "big_exit_mix": cls.OUT}
        cls.settings = cls.mv_look.merge_look({"text2": text2})["text2"]
        pieces = KT.plan_words(song(), cls.settings)
        big = [p for p in pieces if p.role == "big"][0]
        sub = [p for p in pieces if p.id == big.id.replace("b", "p")][0]               # the subtitle it repeats
        # while the subtitle (over the dancer) and its large word (behind her) are both whole
        cls.at = math.ceil((sub.start + 0.15) * 30) / 30.0
        cls.count = int(round((min(sub.end, big.end) - 0.15 - cls.at) * 30))
        cls.fade_at = cls.at - 0.2                               # black from before the excerpt to the end
        fg = os.path.join(cls.folder, "fg120.avi")
        x0, x1 = cls.COLUMN
        # (geq writes the alpha: drawbox paints the colour and leaves the alpha 0)
        column = "if(between(X\\,%d\\,%d)\\,255\\,0)" % (x0, x1 - 1)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black@0.0:s=%dx%d:r=120,format=rgba,geq=r=64:g=192:b=96:a='%s'" % (cls.SIZE + (column,)),
                        "-frames:v", str(4 * cls.count + 48), "-c:v", "rawvideo", "-pix_fmt", "bgra", fg],
                       check=True, stdin=subprocess.DEVNULL)
        base = {"flares": [], "lens": {"grain": 0}}
        fade = {"mograph": {"on": 1, "events": [{"kind": "fade", "t": cls.fade_at, "out": 3, "hold": -1, "back": 0}]}}
        grade = {"light": {"grade": {"mids": [0.2, 0.2, 0.2], "highs": [0.2, 0.2, 0.2]}}}
        cases = {"on": dict(base, text2=text2), "off": base, "fade_on": dict(base, text2=text2, **fade),
                 "fade_off": dict(base, **fade), "grade_on": dict(base, text2=text2, **grade)}
        common = ["--subframes", "4", "--offset", "%.6f" % (cls.at - 0.2), "--from", "%.6f" % cls.at,
                  "--to", "%.6f" % (cls.at + cls.count / 30.0)]
        cls.codes = {}
        for name, look in cases.items():
            path = os.path.join(cls.folder, "look_%s.json" % name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(look, f)
            extra = ["--cues", cls.words] if "text2" in look else []
            cls.codes[name] = RenderTest.answer.__func__(cls, ["render", fg, path, os.path.join(cls.folder, name + ".mp4")]
                                                          + common + extra + ["--work", os.path.join(cls.folder, "w_" + name)])
        drawer = KT.Drawer(song(), cls.SIZE, 30, cls.settings)
        cls.alpha = {layer: [drawer.frame(cls.at + n / 30.0, layer)[0][..., 3] for n in range(cls.count)] for layer in KT.LAYERS}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, name):
        return RenderTest.frames(self, name)

    def masks(self, n):
        """the pixels of the back layer alone and of the front layer, inside and outside the dancer, at frame n"""
        back, front = self.alpha["back"][n], self.alpha["front"][n]
        inside = np.zeros(back.shape, bool)
        inside[:, self.COLUMN[0]:self.COLUMN[1]] = True
        alone = (back > 0.6) & (front < 0.01)
        return {"back_in": alone & inside, "back_out": alone & ~inside, "front": front > 0.9,
                "front_in": (front > 0.9) & inside}

    def test_it_rendered(self):
        self.assertEqual(self.codes, {"on": 0, "off": 0, "fade_on": 0, "fade_off": 0, "grade_on": 0})
        self.assertEqual(len(self.frames("on")), self.count)

    def test_the_back_layer_is_behind_the_dancer_and_the_front_one_over_her(self):
        on, off = self.frames("on"), self.frames("off")
        counted = {"back_in": 0, "back_out": 0, "front_in": 0}
        for n in range(self.count):
            m = self.masks(n)
            d = np.abs(on[n] - off[n]).max(axis=2)
            if m["back_in"].sum() >= 20:                     # she hides the large word ...
                self.assertLessEqual(float(d[m["back_in"]].mean()), 1.5, n)
                counted["back_in"] += 1
            if m["back_out"].sum() >= 20:                    # ... which shows beside her
                self.assertGreater(float(d[m["back_out"]].mean()), 40.0, n)
                counted["back_out"] += 1
            if m["front_in"].sum() >= 20:                    # the subtitle is over her
                self.assertGreater(float(d[m["front_in"]].mean()), 60.0, n)
                counted["front_in"] += 1
        self.assertTrue(all(v >= 3 for v in counted.values()), counted)

    def test_the_fade_to_black_covers_the_back_layer_and_leaves_the_front_one(self):
        on, off = self.frames("fade_on"), self.frames("fade_off")
        counted = {"back": 0, "front": 0}
        for n in range(self.count):
            m = self.masks(n)
            self.assertLessEqual(int(off[n].max()), 20, n)                       # the picture is black ...
            if m["back_out"].sum() >= 20:
                self.assertLessEqual(float(on[n][m["back_out"]].max()), 24.0, n)   # ... and so is the large word
                counted["back"] += 1
            if m["front"].sum() >= 20:
                self.assertGreater(float(on[n][m["front"]].mean()), 100.0, n)    # the front text is on the black (an accent
                                                                                 # colour, red 255 88 112, is 152 on average)
                counted["front"] += 1
        self.assertTrue(all(v >= 3 for v in counted.values()), counted)

    def luma(self, name):
        """the frames' Y' (whole resolution: the colours of 4:2:0 mix a stroke with the pixels beside it)"""
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, name + ".mp4"), "-f", "rawvideo",
                              "-pix_fmt", "gray", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = self.SIZE[0] * self.SIZE[1]
        return [np.frombuffer(raw[i * n:(i + 1) * n], np.uint8).reshape(self.SIZE[1], self.SIZE[0]).astype(np.float64)
                for i in range(len(raw) // n)]

    def test_the_grade_colours_the_back_layer_and_not_the_front_one(self):
        # the grade lifts the middle tones and the highlights: a stroke of the back layer is graded with the stage (its light
        # fill rises by some 13 of 255, more where the stage shows through it); one of the front layer is laid over the graded
        # picture and keeps its colour (what changes is what shows through it and the encoder's rounding: a few of 255)
        on, graded = self.luma("on"), self.luma("grade_on")
        counted = {"back": 0, "front": 0}
        for n in range(self.count):
            m = self.masks(n)
            d = graded[n] - on[n]
            if m["back_out"].sum() >= 20:
                self.assertGreater(float(d[m["back_out"]].mean()), 10.0, n)
                counted["back"] += 1
            if m["front"].sum() >= 20:
                self.assertLess(abs(float(d[m["front"]].mean())), 4.0, n)
                counted["front"] += 1
        self.assertTrue(all(v >= 3 for v in counted.values()), counted)


if __name__ == "__main__":
    unittest.main()
