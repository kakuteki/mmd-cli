"""tools/mv_text.py: MV-style text drawn with Pillow into PNG sequences and overlaid with ffmpeg."""
import contextlib
import dataclasses
import fractions
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:                       # the package needs nothing; this one tool draws with Pillow
    raise unittest.SkipTest("Pillow is not installed: tools/mv_text.py draws with it")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("mv_text", os.path.join(ROOT, "tools", "mv_text.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_text = load_tool()

# which fonts this machine has: the tool runs without the Y1 fonts (it falls back and says so), the tests
# that look at a Y1 face skip
Y1 = all(os.path.exists(os.path.join(mv_text.USER_FONTS, name)) for name in mv_text.LATIN_FILES.values())
NOTO = os.path.exists(mv_text.JP_FONTS[0])
NO_Y1 = "the Y1 fonts (YUTAONE) are not installed for this user"
NO_NOTO = "Noto Sans JP (variable) is not installed"
STATIC_FONTS = (os.path.join(mv_text.USER_FONTS, "Y1RevForge.otf"), "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/meiryo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def first_existing(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def ink_box(font, text):
    """the box of the pixels a text really sets, drawn with its origin at (60, 200)"""
    im = Image.new("L", (400, 300), 0)
    ImageDraw.Draw(im).text((60, 200), text, font=font, fill=255, anchor="ls")
    return im.getbbox()


class RunsTest(unittest.TestCase):
    def test_a_line_is_split_where_the_script_changes(self):
        self.assertEqual(mv_text.runs("Motion \u3048\u306c\u305f / Model Sour"),
                         [("latin", "Motion "), ("jp", "\u3048\u306c\u305f"), ("latin", " / Model Sour")])

    def test_kana_kanji_and_fullwidth_forms_are_japanese(self):
        # U+2E80 and above: CJK radicals, kana, kanji, fullwidth forms; below it (accents, dashes) is Latin
        self.assertEqual(mv_text.runs("\u30d2\u30d3\u30ab\u30bb"), [("jp", "\u30d2\u30d3\u30ab\u30bb")])
        self.assertEqual(mv_text.runs("\u93e1\u97f3\u30ea\u30f3\uff01"), [("jp", "\u93e1\u97f3\u30ea\u30f3\uff01")])
        self.assertEqual(mv_text.runs("caf\u00e9 \u2014 A"), [("latin", "caf\u00e9 \u2014 A")])
        self.assertEqual(mv_text.runs("\u2e80"), [("jp", "\u2e80")])
        self.assertEqual(mv_text.runs("\u2e7f"), [("latin", "\u2e7f")])
        self.assertEqual(mv_text.runs(""), [])

    def test_the_runs_put_together_are_the_line(self):
        text = "Sour\u5f0f\u93e1\u97f3\u30ea\u30f3 Ver.2.01"
        parts = mv_text.runs(text)
        self.assertEqual("".join(part for _, part in parts), text)
        self.assertEqual([script for script, _ in parts], ["latin", "jp", "latin"])


class FontFilesTest(unittest.TestCase):
    def test_every_role_resolves_to_a_file_that_exists_or_to_a_recorded_fallback(self):
        try:
            book = mv_text.FontBook()
        except ValueError as e:
            self.skipTest("no Japanese font of the candidates on this machine: %s" % e)
        self.assertEqual(sorted(book.files), ["accent", "jp", "latin", "logo"])
        for role, path in book.files.items():
            self.assertTrue(os.path.exists(path), role)
        for role, name in mv_text.LATIN_FILES.items():
            wanted = os.path.join(mv_text.USER_FONTS, name)
            if os.path.exists(wanted):
                self.assertEqual(os.path.normcase(book.files[role]), os.path.normcase(wanted))
            else:
                self.assertEqual(book.files[role], book.files["jp"])
                self.assertTrue(any(name in w for w in book.warnings), book.warnings)
        if Y1 and NOTO:
            self.assertEqual(book.warnings, [])

    def test_a_missing_y1_font_falls_back_to_the_japanese_font_and_says_so(self):
        jp = first_existing(mv_text.JP_FONTS)
        if jp is None:
            self.skipTest("no Japanese font of the candidates on this machine")
        empty = tempfile.mkdtemp()
        book = mv_text.FontBook(user_dir=empty)
        self.assertEqual({book.files[role] for role in ("logo", "latin", "accent")}, {book.files["jp"]})
        self.assertEqual(book.files["jp"], jp)
        for name in mv_text.LATIN_FILES.values():
            self.assertEqual(len([w for w in book.warnings if name in w]), 1, book.warnings)
        for warning in book.warnings:
            warning.encode("ascii")

    def test_the_first_japanese_candidate_that_exists_is_used_and_a_later_one_is_a_warning(self):
        font = first_existing(STATIC_FONTS + mv_text.JP_FONTS)
        if font is None:
            self.skipTest("no TrueType font of the candidates on this machine")
        missing = os.path.join(tempfile.mkdtemp(), "none.ttf")
        book = mv_text.FontBook(user_dir=tempfile.mkdtemp(), jp_candidates=(missing, font))
        self.assertEqual(book.files["jp"], font)
        self.assertTrue(any("none.ttf" in w for w in book.warnings), book.warnings)
        first = mv_text.FontBook(user_dir=tempfile.mkdtemp(), jp_candidates=(font, missing))
        self.assertFalse(any("none.ttf" in w for w in first.warnings), first.warnings)

    def test_no_japanese_font_at_all_is_an_error(self):
        folder = tempfile.mkdtemp()
        with self.assertRaises(ValueError) as caught:
            mv_text.FontBook(user_dir=folder, jp_candidates=(os.path.join(folder, "a.ttf"), os.path.join(folder, "b.ttf")))
        self.assertIn("a.ttf", str(caught.exception))


class LoadFontTest(unittest.TestCase):
    @unittest.skipUnless(NOTO, NO_NOTO)
    def test_the_weight_axis_changes_the_ink_of_a_kana(self):
        # the advance of a kana is one em at every weight: the weight shows in the ink only
        warnings = []
        black = mv_text.load_font(mv_text.JP_FONTS[0], 100, 900, warnings)
        regular = mv_text.load_font(mv_text.JP_FONTS[0], 100, 400, warnings)
        self.assertEqual(warnings, [])
        wide, narrow = ink_box(black, "\u3042"), ink_box(regular, "\u3042")
        self.assertGreater(wide[2] - wide[0], narrow[2] - narrow[0])
        self.assertEqual(black.getlength("\u3042"), regular.getlength("\u3042"))

    def test_a_font_without_a_weight_axis_loads_as_it_is_and_says_so(self):
        path = first_existing(STATIC_FONTS)
        if path is None:
            self.skipTest("no static TrueType font of the candidates on this machine")
        warnings = []
        font = mv_text.load_font(path, 40, 900, warnings)
        self.assertIsNotNone(ink_box(font, "A"))
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("900", warnings[0])
        self.assertIn(os.path.basename(path), warnings[0])
        mv_text.load_font(path, 20, 900, warnings)                  # said once, not once per size
        self.assertEqual(len(warnings), 1, warnings)
        quiet = []
        mv_text.load_font(path, 40, None, quiet)                    # no weight asked for: nothing to say
        self.assertEqual(quiet, [])

    @unittest.skipUnless(Y1, NO_Y1)
    def test_a_glyph_a_font_lacks_is_told_from_one_it_has(self):
        # the glitch face has letters and digits, no "/" (it would be drawn as an empty box)
        book = mv_text.FontBook()
        glitch = book.font("accent", 60, 900)
        self.assertFalse(book.has_glyph(glitch, "/"))
        for ch in "HIBKASE09 ":
            self.assertTrue(book.has_glyph(glitch, ch), ch)
        self.assertTrue(book.has_glyph(book.font("latin", 30, 400), "/"))

    def test_the_same_face_is_loaded_once(self):
        try:
            book = mv_text.FontBook()
        except ValueError as e:
            self.skipTest(str(e))
        self.assertIs(book.font("jp", 44, 900), book.font("jp", 44, 900))
        self.assertIsNot(book.font("jp", 44, 900), book.font("jp", 44, 400))


NEW_FORMAT = {
    "fps": 30, "size": [1280, 720], "palette": "dark",
    "cues": [
        {"id": "title", "start": 1.0, "end": 6.0, "x": "left", "y": "top", "anim": "tracking-in",
         "lines": [{"text": "HIBIKASE", "style": "logo"}, {"text": "\u30d2\u30d3\u30ab\u30bb", "style": "title_jp"},
                   {"text": "feat. KAGAMINE RIN", "style": "sub"}]},
        {"id": "credit1", "start": 2.0, "end": 7.0, "x": "left", "y": "bottom", "anim": "rise",
         "text": "Motion \u3048\u306c\u305f / Model Sour / Music \u30ae\u30ac", "style": "credit"},
        {"id": "hook1", "start": 44.5, "end": 45.3, "x": "center", "y": "middle", "anim": "flash", "text": "HIBIKASE",
         "style": "hook"},
        {"id": "lyric1", "start": 60.0, "end": 64.0, "x": "center", "y": "lower", "anim": "rise",
         "text": "\u97ff\u304b\u305b", "style": "lyric", "enter": 0.3, "exit": 0.2},
    ]}

OLD_FORMAT = [
    {"text": "\u30d2\u30d3\u30ab\u30bb", "start": 1.0, "end": 5.0, "style": "title", "anim": "fade", "x": "left", "y": "top"},
    {"text": "Sour\u5f0f\u93e1\u97f3\u30ea\u30f3 Ver.2.01", "start": 2.0, "end": 6.0, "style": "credit", "anim": "slide-up",
     "x": "left", "y": "bottom"},
    {"text": "note", "start": 3, "end": 4, "style": "caption", "anim": "slide-left"},
    {"text": "la la", "start": 8.0, "end": 9.5, "style": "lyric", "fontsize": 60},
]


def one_cue(**fields):
    cue = {"id": "a", "start": 1.0, "end": 3.0, "text": "x", "style": "lyric"}
    cue.update(fields)
    return {"cues": [cue]}


class CueFileTest(unittest.TestCase):
    def test_the_new_format_loads_lines_and_single_texts(self):
        sheet = mv_text.parse_cues(NEW_FORMAT)
        self.assertEqual((sheet.fps, sheet.size, sheet.palette), (fractions.Fraction(30), (1280, 720), "dark"))
        self.assertEqual([c.id for c in sheet.cues], ["title", "credit1", "hook1", "lyric1"])
        title, credit, hook, lyric = sheet.cues
        self.assertEqual([(line.text, line.style) for line in title.lines],
                         [("HIBIKASE", "logo"), ("\u30d2\u30d3\u30ab\u30bb", "title_jp"), ("feat. KAGAMINE RIN", "sub")])
        self.assertEqual((title.start, title.end, title.x, title.y, title.anim), (1.0, 6.0, "left", "top", "tracking-in"))
        self.assertEqual([(line.text, line.style) for line in credit.lines],
                         [("Motion \u3048\u306c\u305f / Model Sour / Music \u30ae\u30ac", "credit")])
        self.assertEqual((hook.anim, hook.x, hook.y, hook.lines[0].style), ("flash", "center", "middle", "hook"))
        self.assertEqual((title.enter, title.exit), (0.6, 0.4))                   # the defaults
        self.assertEqual((lyric.enter, lyric.exit), (0.3, 0.2))                   # per cue

    def test_what_a_cue_file_leaves_out(self):
        sheet = mv_text.parse_cues({"cues": [{"start": 0, "end": 1, "text": "x"}]})
        self.assertEqual((sheet.fps, sheet.size, sheet.palette), (fractions.Fraction(30), (1280, 720), "dark"))
        cue = sheet.cues[0]
        self.assertEqual((cue.id, cue.x, cue.y, cue.anim, cue.lines[0].style), ("c00", "center", "lower", "fade", "lyric"))
        light = mv_text.parse_cues({"palette": "light", "fps": "30000/1001", "size": [1920, 1080], "cues": []})
        self.assertEqual((light.fps, light.size, light.palette), (fractions.Fraction(30000, 1001), (1920, 1080), "light"))

    def test_a_text_with_line_breaks_is_several_lines_of_one_style(self):
        sheet = mv_text.parse_cues(one_cue(text="one\ntwo", style="credit"))
        self.assertEqual([(line.text, line.style) for line in sheet.cues[0].lines], [("one", "credit"), ("two", "credit")])

    def test_the_old_flat_list_loads_and_maps_styles_and_anims(self):
        sheet = mv_text.parse_cues(OLD_FORMAT)
        self.assertEqual((sheet.fps, sheet.size, sheet.palette), (fractions.Fraction(30), (1280, 720), "dark"))
        self.assertEqual([c.lines[0].style for c in sheet.cues], ["logo", "credit", "sub", "lyric"])
        self.assertEqual([c.anim for c in sheet.cues], ["fade", "rise", "rise", "fade"])
        self.assertEqual([c.id for c in sheet.cues], ["c00", "c01", "c02", "c03"])
        self.assertEqual([(c.x, c.y) for c in sheet.cues], [("left", "top"), ("left", "bottom"), ("center", "lower"),
                                                             ("center", "lower")])
        self.assertEqual(sheet.cues[0].lines[0].text, "\u30d2\u30d3\u30ab\u30bb")
        self.assertEqual((sheet.cues[1].start, sheet.cues[1].end), (2.0, 6.0))
        # the old per cue font size still reaches the line
        self.assertEqual([c.lines[0].size for c in sheet.cues], [None, None, None, 60])

    def test_the_old_names_are_read_in_the_flat_list_only(self):
        # "caption" is a style of its own in the new format, and the old slide names are not anims there
        sheet = mv_text.parse_cues(one_cue(style="caption"))
        self.assertEqual(sheet.cues[0].lines[0].style, "caption")
        with self.assertRaises(ValueError):
            mv_text.parse_cues(one_cue(anim="slide-up"))
        with self.assertRaises(ValueError):
            mv_text.parse_cues(one_cue(style="title"))

    def test_an_end_that_is_not_after_the_start_names_the_cue(self):
        for start, end in ((2.0, 2.0), (3.0, 1.0)):
            with self.assertRaises(ValueError) as caught:
                mv_text.parse_cues(one_cue(id="chorus2", start=start, end=end))
            self.assertIn("chorus2", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            mv_text.parse_cues([{"text": "a", "start": 0, "end": 1}, {"text": "b", "start": 5, "end": 5}])
        self.assertIn("c01", str(caught.exception))

    def test_an_unknown_anim_style_or_anchor_names_the_cue_and_the_value(self):
        for field, value in (("anim", "spin"), ("style", "comic"), ("x", "middle"), ("y", "left")):
            with self.assertRaises(ValueError) as caught:
                mv_text.parse_cues(one_cue(id="verse1", **{field: value}))
            self.assertIn("verse1", str(caught.exception), field)
            self.assertIn(value, str(caught.exception), field)
        with self.assertRaises(ValueError) as caught:
            mv_text.parse_cues({"cues": [{"id": "t", "start": 0, "end": 1, "lines": [{"text": "x", "style": "nope"}]}]})
        self.assertIn("nope", str(caught.exception))

    def test_a_cue_needs_a_text_and_numbers(self):
        bad = ({"id": "verse9", "start": 0, "end": 1}, {"id": "verse9", "start": 0, "end": 1, "text": ""},
               {"id": "verse9", "start": 0, "end": 1, "text": "  \n "}, {"id": "verse9", "start": 0, "end": 1, "lines": []},
               {"id": "verse9", "start": 0, "end": 1, "lines": [{"style": "logo"}]},
               {"id": "verse9", "start": 0, "end": 1, "text": "x", "lines": [{"text": "y"}]},
               {"id": "verse9", "start": "0", "end": 1, "text": "x"}, {"id": "verse9", "end": 1, "text": "x"},
               {"id": "verse9", "start": -1, "end": 1, "text": "x"}, {"id": "verse9", "start": True, "end": 2, "text": "x"},
               {"id": "verse9", "start": 0, "end": 1, "text": "x", "enter": -0.1},
               {"id": "verse9", "start": 0, "end": 1, "text": "x", "exit": "soon"},
               {"id": "verse9", "start": 0, "end": 1, "text": "x", "size": 0}, "not a cue")
        for cue in bad:
            with self.assertRaises(ValueError, msg=repr(cue)) as caught:
                mv_text.parse_cues({"cues": [cue]})
            if isinstance(cue, dict):
                self.assertIn("verse9", str(caught.exception), repr(cue))

    def test_ids_name_the_folders_so_they_are_plain_and_differ(self):
        with self.assertRaises(ValueError) as caught:
            mv_text.parse_cues({"cues": [{"id": "dup1", "start": 0, "end": 1, "text": "x"},
                                         {"id": "dup1", "start": 2, "end": 3, "text": "y"}]})
        self.assertIn("dup1", str(caught.exception))
        for bad in ("../up", "a b", "", "\u6b4c", "a/b", 7):
            with self.assertRaises(ValueError, msg=repr(bad)):
                mv_text.parse_cues(one_cue(id=bad))
        self.assertEqual(mv_text.parse_cues(one_cue(id="Verse_1-a")).cues[0].id, "Verse_1-a")

    def test_the_frame_the_rate_and_the_palette_are_checked(self):
        for data in ({"palette": "sepia", "cues": []}, {"fps": 0, "cues": []}, {"fps": "fast", "cues": []},
                     {"size": [1280], "cues": []}, {"size": [0, 720], "cues": []}, {"size": "1280x720", "cues": []},
                     {"cues": {}}, {}, "text", 3):
            with self.assertRaises(ValueError, msg=repr(data)):
                mv_text.parse_cues(data)

    def test_a_cue_is_in_front_of_the_dancer_unless_it_says_back(self):
        # the layer only matters to a tool that puts the dancer between the two; it travels with the cue
        sheet = mv_text.parse_cues({"cues": [{"id": "a", "start": 0, "end": 1, "text": "x"},
                                             {"id": "b", "start": 0, "end": 1, "text": "x", "layer": "back"},
                                             {"id": "c", "start": 0, "end": 1, "text": "x", "layer": "front"}]})
        self.assertEqual([c.layer for c in sheet.cues], ["front", "back", "front"])
        self.assertEqual([c.layer for c in mv_text.parse_cues(OLD_FORMAT).cues], ["front"] * 4)
        for bad in ("middle", "", None, 1, "Back"):
            with self.assertRaises(ValueError, msg=repr(bad)) as caught:
                mv_text.parse_cues(one_cue(id="title7", layer=bad))
            self.assertIn("title7", str(caught.exception))
            self.assertIn("layer", str(caught.exception))

    def test_a_lyric_can_stand_beside_the_dancer(self):
        for x in ("left", "center", "right", "left-third", "right-third"):
            self.assertEqual(mv_text.parse_cues(one_cue(x=x)).cues[0].x, x)

    def test_a_cue_file_is_read_as_utf8(self):
        path = os.path.join(tempfile.mkdtemp(), "cues.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('[{"text": "\u30d2\u30d3\u30ab\u30bb", "start": 1, "end": 2, "style": "title"}]')
        sheet = mv_text.load_cues(path)
        self.assertEqual(sheet.cues[0].lines[0].text, "\u30d2\u30d3\u30ab\u30bb")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            mv_text.load_cues(path)


def motion(anim, start=1.0, end=4.0, **more):
    """a cue from 1.0 to 4.0 s: it has come at 1.6 (enter 0.6) and starts to go at 3.6 (exit 0.4)"""
    return mv_text.Motion(anim, start, end, **more)


def frame_times(m, count=None):
    """the times of the frames of a cue, the first on its start"""
    total = int(round((m.end - m.start) * m.fps))
    return [m.start + i / m.fps for i in range(total if count is None else count)]


class MotionTest(unittest.TestCase):
    def test_a_cue_comes_holds_and_goes(self):
        for anim in ("fade", "rise", "tracking-in"):
            m = motion(anim)
            self.assertEqual(m.at(1.0).alpha, 0.0, anim)
            self.assertEqual(m.at(1.6).alpha, 1.0, anim)
            self.assertEqual(m.at(2.5).alpha, 1.0, anim)
            self.assertEqual(m.at(3.59).alpha, 1.0, anim)                      # just before it starts to go
            self.assertAlmostEqual(m.at(4.0).alpha, 0.0, places=9, msg=anim)
            alphas = [m.at(t).alpha for t in frame_times(m)]
            self.assertTrue(all(0.0 <= a <= 1.0 for a in alphas), anim)
            coming, going = alphas[:19], alphas[78:]                           # frames 0..18 and 78..89
            self.assertEqual(coming, sorted(coming), anim)
            self.assertEqual(going, sorted(going, reverse=True), anim)
            # the last frame drawn is one before the end: 1 - (11/12)^3 of it is left, then it is gone
            self.assertAlmostEqual(going[-1], 1 - (11.0 / 12.0) ** 3, places=6, msg=anim)

    def test_coming_eases_out_and_going_eases_in(self):
        # cubic: half way through the enter the cue is already 1 - 0.5^3 there, half way through the exit it
        # has lost only 0.5^3
        m = motion("fade")
        self.assertAlmostEqual(m.at(1.3).alpha, 0.875)
        self.assertAlmostEqual(m.at(3.8).alpha, 0.875)
        self.assertAlmostEqual(m.at(1.15).alpha, 1 - 0.75 ** 3)
        self.assertAlmostEqual(m.at(3.9).alpha, 1 - 0.75 ** 3)

    def test_fade_moves_nothing(self):
        m = motion("fade")
        for t in frame_times(m):
            s = m.at(t)
            self.assertEqual((s.dx, s.dy, s.tracking_extra, s.wipe), (0.0, 0.0, 0.0, 1.0))

    def test_rise_comes_up_24_px_and_leaves_12_px_higher(self):
        m = motion("rise")
        self.assertEqual(m.at(1.0).dy, 24.0)
        self.assertEqual(m.at(1.6).dy, 0.0)
        self.assertEqual(m.at(3.0).dy, 0.0)
        self.assertAlmostEqual(m.at(4.0).dy, -12.0)
        ys = [m.at(t).dy for t in frame_times(m)]
        self.assertEqual(ys, sorted(ys, reverse=True))                         # it only ever moves up
        self.assertAlmostEqual(m.at(1.3).dy, 24.0 * 0.125)
        self.assertEqual(m.at(1.0).dx, 0.0)
        # the px are those of a 720 high frame: twice as far in a 1440 high one
        self.assertEqual(motion("rise", scale=2.0).at(1.0).dy, 48.0)
        self.assertEqual(m.extents(), (-12.0, 24.0, 0.0))

    def test_tracking_in_starts_spread_and_closes(self):
        m = motion("tracking-in")
        self.assertEqual(m.at(1.0).tracking_extra, 0.6)
        self.assertEqual(m.at(1.6).tracking_extra, 0.0)
        self.assertEqual(m.at(3.0).tracking_extra, 0.0)
        self.assertAlmostEqual(m.at(4.0).tracking_extra, 0.1)
        self.assertAlmostEqual(m.at(1.3).tracking_extra, 0.6 * 0.125)
        self.assertEqual(m.at(1.0).dy, 0.0)
        self.assertEqual(m.extents(), (0.0, 0.0, 0.6))

    def test_wipe_shows_from_the_left_at_full_alpha_and_goes_by_fading(self):
        m = motion("wipe")
        self.assertEqual((m.at(1.0).wipe, m.at(1.0).alpha), (0.0, 1.0))
        self.assertEqual((m.at(1.6).wipe, m.at(1.6).alpha), (1.0, 1.0))
        self.assertAlmostEqual(m.at(1.3).wipe, 0.875)
        self.assertEqual((m.at(3.8).wipe, m.at(3.0).alpha), (1.0, 1.0))
        self.assertAlmostEqual(m.at(3.8).alpha, 0.875)
        self.assertAlmostEqual(m.at(4.0).alpha, 0.0, places=9)

    def test_flash_blinks_for_five_frames_holds_and_is_cut_off(self):
        m = motion("flash", start=44.5, end=45.3)
        times = frame_times(m)
        self.assertEqual(len(times), 24)
        alphas = [m.at(t).alpha for t in times]
        self.assertEqual(alphas[:5], [1.0, 0.0, 1.0, 0.35, 1.0])
        self.assertEqual(set(alphas[5:]), {1.0})                               # the last frame is as strong: no fade
        for t in times:
            s = m.at(t)
            self.assertEqual((s.dx, s.dy, s.tracking_extra, s.wipe, s.underline), (0.0, 0.0, 0.0, 1.0, 1.0))
        # the blink is counted in frames, whatever the rate
        fast = motion("flash", start=2.0, end=3.0, fps=60.0)
        self.assertEqual([fast.at(t).alpha for t in frame_times(fast, 6)], [1.0, 0.0, 1.0, 0.35, 1.0, 1.0])

    def test_roll_travels_at_one_speed_from_its_first_offset_to_its_last(self):
        m = motion("roll", start=10.0, end=30.0, roll=(672.0, -548.0))
        self.assertEqual(m.at(10.0).dy, 672.0)
        self.assertAlmostEqual(m.at(30.0).dy, -548.0)
        self.assertAlmostEqual(m.at(20.0).dy, (672.0 - 548.0) / 2)
        ys = [m.at(t).dy for t in frame_times(m)]
        self.assertTrue(all(a > b for a, b in zip(ys, ys[1:])))                # strictly up, every frame
        steps = [a - b for a, b in zip(ys, ys[1:])]
        self.assertAlmostEqual(max(steps), min(steps), places=6)
        self.assertEqual({m.at(t).alpha for t in frame_times(m)}, {1.0})
        self.assertEqual(m.extents(), (-548.0, 672.0, 0.0))

    def test_the_underline_is_drawn_while_the_cue_comes(self):
        for anim in ("fade", "rise", "tracking-in", "wipe"):
            m = motion(anim)
            self.assertEqual(m.at(1.0).underline, 0.0, anim)
            self.assertAlmostEqual(m.at(1.3).underline, 0.875, msg=anim)
            self.assertEqual(m.at(1.6).underline, 1.0, anim)
            self.assertEqual(m.at(3.9).underline, 1.0, anim)                   # it goes with the alpha, not by itself

    def test_the_cue_sets_how_long_it_takes_to_come_and_go(self):
        m = motion("rise", enter=1.0, exit=2.0)
        self.assertEqual(m.at(2.0).alpha, 1.0)
        self.assertAlmostEqual(m.at(1.5).alpha, 0.875)
        self.assertAlmostEqual(m.at(3.0).alpha, 0.875)
        # no time at all: it is there on the first frame and until the last
        sudden = motion("rise", enter=0.0, exit=0.0)
        self.assertEqual((sudden.at(1.0).alpha, sudden.at(1.0).dy), (1.0, 0.0))
        self.assertEqual((sudden.at(3.99).alpha, sudden.at(3.99).dy), (1.0, 0.0))

    def test_a_cue_shorter_than_its_enter_and_exit_still_shows(self):
        m = motion("fade", start=1.0, end=1.5)
        alphas = [m.at(t).alpha for t in frame_times(m)]
        self.assertGreater(max(alphas), 0.5)
        self.assertTrue(all(0.0 <= a <= 1.0 for a in alphas))
        self.assertEqual(alphas[0], 0.0)

    def test_what_does_not_move_has_no_extents(self):
        for anim in ("fade", "wipe", "flash"):
            self.assertEqual(motion(anim).extents(), (0.0, 0.0, 0.0), anim)
        self.assertEqual(motion("rise", scale=0.25).extents(), (-3.0, 6.0, 0.0))


BOOK = []


def book():
    """the fonts of this machine, resolved once (the Y1 faces or what stands in for them: the layout holds
    either way); a test that lays out or draws skips on a machine with no Japanese font at all"""
    if not BOOK:
        try:
            BOOK.append(mv_text.FontBook())
        except ValueError as e:
            raise unittest.SkipTest(str(e))
    return BOOK[0]


def lay(cue, size=(1280, 720), fps=30, palette="dark"):
    sheet = mv_text.parse_cues({"fps": fps, "size": list(size), "palette": palette, "cues": [cue]})
    return mv_text.layout_cue(sheet.cues[0], sheet, book())


def cue_of(text="\u97ff\u304b\u305b", style="lyric", **fields):
    cue = {"id": "a", "start": 1.0, "end": 4.0, "text": text, "style": style, "anim": "fade", "x": "center", "y": "middle"}
    cue.update(fields)
    return cue


def title(**fields):
    cue = dict(NEW_FORMAT["cues"][0])
    cue.update(fields)
    return cue


def rect(origin, size):
    return (origin[0], origin[1], origin[0] + size[0], origin[1] + size[1])


class AnchorTest(unittest.TestCase):
    def test_left_center_and_right_keep_the_64_px_margins(self):
        for cue in (title, cue_of):
            left, center, right = (lay(cue(x=x)) for x in ("left", "center", "right"))
            self.assertEqual(left.anchor[0], 64)
            self.assertEqual(right.anchor[0] + right.block[0], 1280 - 64)
            self.assertLessEqual(abs(center.anchor[0] + center.block[0] / 2.0 - 640), 1)
            self.assertEqual(left.block, right.block)

    def test_the_thirds_centre_the_block_on_a_quarter_and_on_three_quarters(self):
        left, right = lay(cue_of(x="left-third")), lay(cue_of(x="right-third"))
        self.assertLessEqual(abs(left.anchor[0] + left.block[0] / 2.0 - 320), 1)
        self.assertLessEqual(abs(right.anchor[0] + right.block[0] / 2.0 - 960), 1)
        # a block too wide to be centred there stops at the safe margin
        wide = "\u97ff\u304b\u305b" * 6
        left, right = lay(cue_of(wide, x="left-third")), lay(cue_of(wide, x="right-third"))
        self.assertGreater(left.block[0], 2 * (320 - 64))
        self.assertEqual(left.anchor[0], 64)
        self.assertEqual(right.anchor[0] + right.block[0], 1280 - 64)

    def test_top_middle_lower_and_bottom_keep_the_48_px_margins(self):
        for cue in (title, cue_of):
            top, middle, lower, bottom = (lay(cue(y=y)) for y in ("top", "middle", "lower", "bottom"))
            self.assertEqual(top.anchor[1], 48)
            self.assertEqual(bottom.anchor[1] + bottom.block[1], 720 - 48)
            self.assertLessEqual(abs(middle.anchor[1] + middle.block[1] / 2.0 - 360), 1)
            self.assertLessEqual(lower.anchor[1] + lower.block[1], 720 - 48)
            self.assertGreater(lower.anchor[1], middle.anchor[1])
        # the lower third: a block that fits is centred on five sixths of the height
        lower = lay(cue_of(y="lower"))
        self.assertLessEqual(abs(lower.anchor[1] + lower.block[1] / 2.0 - 600), 1)

    def test_the_margins_and_the_sizes_follow_the_frame_height(self):
        for size, margin_x, margin_y, px in (((1920, 1080), 96, 72, 69), ((640, 360), 32, 24, 23), ((320, 180), 16, 12, 12)):
            layout = lay(cue_of(x="left", y="top"), size=size)
            self.assertEqual(layout.anchor, (margin_x, margin_y), size)
            self.assertEqual(layout.lines[0].size, px, size)                   # lyric is 46 px in a 720 high frame
            bottom = lay(cue_of(x="right", y="bottom"), size=size)
            self.assertEqual(rect(bottom.anchor, bottom.block)[2:], (size[0] - margin_x, size[1] - margin_y), size)

    def test_the_title_lockup_stays_inside_the_margins_at_every_anchor(self):
        for x in mv_text.X_ANCHORS:
            for y in mv_text.Y_ANCHORS:
                layout = lay(title(x=x, y=y))
                x0, y0, x1, y1 = rect(layout.anchor, layout.block)
                self.assertGreaterEqual(x0, 64, (x, y))
                self.assertLessEqual(x1, 1280 - 64, (x, y))
                self.assertGreaterEqual(y0, 48, (x, y))
                self.assertLessEqual(y1, 720 - 48, (x, y))
        self.assertEqual(len(mv_text.X_ANCHORS) * len(mv_text.Y_ANCHORS), 20)

    def test_roll_starts_below_the_frame_and_ends_above_it_whatever_the_anchor(self):
        for y in mv_text.Y_ANCHORS:
            layout = lay(title(anim="roll", y=y, start=10.0, end=30.0))
            first, last = layout.motion.at(layout.motion.start), layout.motion.at(layout.motion.end)
            self.assertEqual(layout.anchor[1] + first.dy, 720, y)                              # its top on the bottom edge
            self.assertAlmostEqual(layout.anchor[1] + layout.block[1] + last.dy, 0, msg=y)     # its bottom on the top edge
            self.assertEqual({first.alpha, last.alpha}, {1.0})


class LinesTest(unittest.TestCase):
    def test_lines_are_stacked_a_third_of_the_larger_em_apart(self):
        # 0.35 em, to the whole pixel: lines at rest sit on whole pixels, or their stems blur
        layout = lay(title())
        self.assertEqual(len(layout.lines), 3)
        for above, below in zip(layout.lines, layout.lines[1:]):
            gap = (below.baseline + below.top) - (above.baseline + above.bottom)
            self.assertLessEqual(abs(gap - 0.35 * max(above.size, below.size)), 0.5)
            self.assertEqual(gap, int(gap))
        self.assertEqual([line.baseline for line in layout.lines], [int(line.baseline) for line in layout.lines])
        self.assertEqual(layout.origin, (int(layout.origin[0]), int(layout.origin[1])))
        self.assertEqual([line.size for line in layout.lines[1:]], [44, 30])
        self.assertLessEqual(layout.lines[0].size, 150)
        # the same lines the other way round still measure the gap from the larger one
        flipped = dict(title(), lines=list(reversed(NEW_FORMAT["cues"][0]["lines"])))
        lines = lay(flipped).lines
        gap = (lines[2].baseline + lines[2].top) - (lines[1].baseline + lines[1].bottom)
        self.assertLessEqual(abs(gap - 0.35 * lines[2].size), 0.5)

    def test_lines_follow_the_side_the_block_is_anchored_to(self):
        left, center, right = (lay(title(x=x)) for x in ("left", "center", "right"))
        self.assertEqual((left.align, center.align, right.align), ("left", "center", "right"))
        self.assertEqual(lay(title(x="left-third")).align, "center")
        widths = [line.width for line in left.lines]
        self.assertEqual([left.line_x(line) for line in left.lines], [0.0, 0.0, 0.0])
        for layout in (center, right):
            self.assertAlmostEqual(max(layout.line_x(line) + line.width for line in layout.lines), layout.width)
        self.assertEqual([right.line_x(line) for line in right.lines], [max(widths) - w for w in widths])
        self.assertEqual([center.line_x(line) for line in center.lines], [(max(widths) - w) / 2.0 for w in widths])

    def test_japanese_and_latin_in_one_line_use_two_fonts(self):
        layout = lay(cue_of("Motion \u3048\u306c\u305f / Model Sour", "credit"))
        glyphs = layout.lines[0].glyphs
        self.assertEqual("".join(g.char for g in glyphs), "Motion \u3048\u306c\u305f / Model Sour")
        latin, jp = book().font("latin", 22, 400), book().font("jp", 24, 400)
        for g in glyphs:
            if ord(g.char) >= 0x2E80:
                self.assertIs(g.font, jp, g.char)
                self.assertEqual((g.size, g.tracking), (24, 0.0))
            else:
                self.assertIs(g.font, latin, g.char)
                self.assertEqual((g.size, g.tracking), (22, 0.12))
        self.assertEqual(layout.lines[0].size, 24)
        self.assertEqual(layout.lines[0].colour, mv_text.PALETTES["dark"]["secondary"])

    def test_tracking_is_added_after_every_character_but_the_last(self):
        layout = lay(cue_of("ABC", "sub"))
        glyphs = layout.lines[0].glyphs
        self.assertEqual([g.tracking for g in glyphs], [0.25, 0.25, 0.25])
        self.assertAlmostEqual(layout.lines[0].width, sum(g.advance for g in glyphs) + 2 * 0.25 * 30)
        self.assertAlmostEqual(layout.line_width(layout.lines[0], 0.6), layout.lines[0].width + 2 * 0.6 * 30)

    def test_sub_is_set_in_capitals_and_in_the_accent(self):
        layout = lay(cue_of("feat. Kagamine Rin", "sub"))
        self.assertEqual("".join(g.char for g in layout.lines[0].glyphs), "FEAT. KAGAMINE RIN")
        self.assertEqual(layout.lines[0].colour, (240, 160, 48))
        self.assertEqual("".join(g.char for g in lay(cue_of("feat. Rin", "credit")).lines[0].glyphs), "feat. Rin")

    def test_the_palette_gives_the_colours(self):
        dark, light = lay(title()), lay(title(), palette="light")
        self.assertEqual([line.colour for line in dark.lines], [(245, 245, 248), (245, 245, 248), (240, 160, 48)])
        self.assertEqual([line.colour for line in light.lines], [(22, 22, 30), (22, 22, 30), (240, 160, 48)])
        self.assertEqual(lay(cue_of("x", "credit"), palette="light").lines[0].colour, (120, 120, 130))
        # the secondary colour of the dark palette is 70 % of its text colour (halves go up)
        self.assertEqual(mv_text.PALETTES["dark"]["secondary"], tuple((7 * c + 5) // 10 for c in (245, 245, 248)))

    def test_a_size_on_the_line_replaces_the_size_of_the_style(self):
        layout = lay(cue_of("la la", "lyric", size=60))
        self.assertEqual({g.size for g in layout.lines[0].glyphs}, {60})
        self.assertEqual({g.size for g in lay(cue_of("la la", "lyric", size=60), size=(2560, 1440)).lines[0].glyphs}, {120})
        # both scripts of a style grow by the same share: credit is 22 (Latin) and 24 (Japanese)
        credit = lay(cue_of("A\u3042", "credit", size=44)).lines[0].glyphs
        self.assertEqual([g.size for g in credit], [44, 48])

    def test_a_line_wider_than_the_safe_width_is_made_smaller_and_says_so(self):
        layout = lay(cue_of("HIBIKASE HIBIKASE HIBIKASE", "logo", id="long1", x="left"))
        line = layout.lines[0]
        self.assertLessEqual(line.width, 1280 - 2 * 64)
        self.assertGreater(line.width, 0.9 * (1280 - 2 * 64))                  # no smaller than it has to be
        self.assertLess(line.size, 150)
        self.assertEqual(len(layout.warnings), 1, layout.warnings)
        self.assertIn("long1", layout.warnings[0])
        layout.warnings[0].encode("ascii")
        x0, _, x1, _ = rect(layout.anchor, layout.block)
        self.assertGreaterEqual(x0, 64)
        self.assertLessEqual(x1, 1280 - 64)
        self.assertEqual(lay(cue_of("AB", "logo")).warnings, [])

    @unittest.skipUnless(Y1, NO_Y1)
    def test_a_character_the_face_lacks_is_drawn_with_the_japanese_font_and_says_so(self):
        layout = lay(cue_of("A/B", "hook", id="hook9"))
        a, slash, b = layout.lines[0].glyphs
        self.assertIs(a.font, b.font)
        self.assertIs(a.font, book().font("accent", 180, 900))
        self.assertIs(slash.font, book().font("jp", 180, 900))
        self.assertEqual(len(layout.warnings), 1, layout.warnings)
        self.assertIn("U+002F", layout.warnings[0])
        self.assertIn("hook9", layout.warnings[0])
        self.assertEqual(lay(cue_of("AB09", "hook")).warnings, [])

    def test_the_block_holds_the_reference_box_and_the_ink(self):
        for cue in (title(), cue_of(), cue_of("HIBIKASE", "hook"), cue_of("gypsy jig", "caption")):
            layout = lay(cue)
            self.assertGreaterEqual(layout.block[0], layout.width - 1e-6)
            for line in layout.lines:
                x = layout.origin[0] + layout.line_x(line)
                y = layout.origin[1] + line.baseline
                self.assertGreaterEqual(x, 0.0)
                self.assertGreaterEqual(y + line.top, -1e-6)
                self.assertLessEqual(y + line.bottom, layout.block[1] + 1e-6)
                for g in line.glyphs:
                    if g.ink is not None:
                        self.assertGreaterEqual(x + g.ink[0], -1e-6, g.char)
                        self.assertGreaterEqual(y + g.ink[1], -1e-6, g.char)
                        self.assertLessEqual(x + g.ink[2], layout.block[0] + 1e-6, g.char)
                        self.assertLessEqual(y + g.ink[3], layout.block[1] + 1e-6, g.char)
                    x += g.advance + g.tracking * g.size


class CanvasTest(unittest.TestCase):
    def test_a_cue_that_does_not_move_has_its_block_and_8_px_around(self):
        layout = lay(cue_of("ABC", "caption"))
        self.assertEqual(rect(layout.canvas_origin, layout.canvas),
                         (layout.anchor[0] - 8, layout.anchor[1] - 8, layout.anchor[0] + layout.block[0] + 8,
                          layout.anchor[1] + layout.block[1] + 8))

    def test_rise_has_room_below_to_come_from_and_above_to_leave_to(self):
        layout = lay(cue_of("ABC", "caption", anim="rise"))
        x0, y0, x1, y1 = rect(layout.canvas_origin, layout.canvas)
        self.assertEqual((x0, x1), (layout.anchor[0] - 8, layout.anchor[0] + layout.block[0] + 8))
        self.assertEqual(y0, layout.anchor[1] - 12 - 8)
        self.assertEqual(y1, layout.anchor[1] + layout.block[1] + 24 + 8)

    def test_tracking_in_has_room_on_the_side_the_letters_spread_to(self):
        grow = 0.6 * 150 * 3                                                   # four letters: three gaps of 0.6 em
        left, center, right = (lay(cue_of("HIBI", "logo", anim="tracking-in", x=x)) for x in ("left", "center", "right"))
        self.assertEqual(left.canvas_origin[0], left.anchor[0] - 8)
        self.assertGreaterEqual(left.canvas_origin[0] + left.canvas[0], left.anchor[0] + left.block[0] + grow)
        self.assertEqual(right.canvas_origin[0] + right.canvas[0], right.anchor[0] + right.block[0] + 8)
        self.assertLessEqual(right.canvas_origin[0], right.anchor[0] - grow)
        self.assertLessEqual(center.canvas_origin[0], center.anchor[0] - grow / 2)
        self.assertGreaterEqual(center.canvas_origin[0] + center.canvas[0], center.anchor[0] + center.block[0] + grow / 2)

    def test_the_canvas_is_cut_at_the_frame(self):
        # what leaves the frame is never seen: a spread title and a roll would otherwise need huge pictures
        for cue in (title(), title(anim="roll", start=10.0, end=30.0), title(x="right", y="bottom", anim="rise"),
                    cue_of("HIBIKASE", "hook", anim="tracking-in")):
            layout = lay(cue)
            x0, y0, x1, y1 = rect(layout.canvas_origin, layout.canvas)
            self.assertGreaterEqual(x0, 0, cue["anim"])
            self.assertGreaterEqual(y0, 0, cue["anim"])
            self.assertLessEqual(x1, 1280, cue["anim"])
            self.assertLessEqual(y1, 720, cue["anim"])
            self.assertGreater(layout.canvas[0] * layout.canvas[1], 0)
        roll = lay(title(anim="roll", start=10.0, end=30.0))
        self.assertEqual((roll.canvas_origin[1], roll.canvas[1]), (0, 720))    # the whole height it travels through
        self.assertEqual(roll.canvas[0], roll.block[0] + 16)

    def test_a_small_cue_has_a_small_canvas(self):
        layout = lay(cue_of(anim="rise", y="lower"))
        self.assertLess(layout.canvas[0] * layout.canvas[1], 1280 * 720 // 20)

    def test_a_soft_shadow_gets_the_room_its_blur_needs(self):
        # lyric has a shadow blurred 6 px and 2 px lower: Pillow's blur reaches 15 px, 3 radii are kept free
        layout = lay(cue_of(style="lyric"))
        self.assertEqual(rect(layout.canvas_origin, layout.canvas),
                         (layout.anchor[0] - 20, layout.anchor[1] - 20, layout.anchor[0] + layout.block[0] + 20,
                          layout.anchor[1] + layout.block[1] + 20))
        big = lay(cue_of(style="lyric"), size=(2560, 1440))
        self.assertEqual(big.anchor[0] - big.canvas_origin[0], 40)


class FramesTest(unittest.TestCase):
    def test_a_cue_covers_the_frames_from_its_start_to_just_before_its_end(self):
        layout = lay(cue_of(start=44.5, end=45.3))
        self.assertEqual((layout.start_frame, layout.frames), (1335, 24))
        self.assertEqual((layout.motion.start, layout.motion.end, layout.motion.fps), (44.5, 1359 / 30.0, 30.0))
        sixty = lay(cue_of(start=1.0, end=4.0), fps=60)
        self.assertEqual((sixty.start_frame, sixty.frames, sixty.motion.fps), (60, 180, 60.0))
        ntsc = lay(cue_of(start=1.0, end=4.0), fps="30000/1001")
        self.assertEqual((ntsc.start_frame, ntsc.frames), (30, 90))
        self.assertAlmostEqual(ntsc.motion.start, 30 * 1001 / 30000.0)

    def test_times_between_two_frames_go_to_the_nearer_one(self):
        layout = lay(cue_of(start=1.01, end=2.02))
        self.assertEqual((layout.start_frame, layout.frames), (30, 31))
        self.assertEqual(layout.motion.start, 1.0)                             # the motion runs on the frame grid

    def test_a_cue_shorter_than_a_frame_is_an_error_that_names_it(self):
        with self.assertRaises(ValueError) as caught:
            lay(cue_of(id="blink3", start=1.0, end=1.01))
        self.assertIn("blink3", str(caught.exception))

    def test_the_motion_of_the_layout_is_the_anim_of_the_cue(self):
        layout = lay(cue_of(anim="rise", enter=0.3, exit=0.2), size=(1920, 1080))
        m = layout.motion
        self.assertEqual((m.anim, m.enter, m.exit, m.scale), ("rise", 0.3, 0.2, 1.5))
        self.assertEqual(m.at(1.0).dy, 36.0)


TEXT, ACCENT, INK, SECONDARY = (245, 245, 248), (240, 160, 48), (22, 22, 30), (172, 172, 174)
BAR = "\u2588" * 10                       # ten full blocks: one solid bar, 280 x 28 px in "caption"


def block_rect(layout):
    """the block inside the canvas"""
    x, y = layout.anchor[0] - layout.canvas_origin[0], layout.anchor[1] - layout.canvas_origin[1]
    return (x, y, x + layout.block[0], y + layout.block[1])


def hold(layout):
    """the State in the middle of the cue: it has come and has not started to go"""
    return layout.motion.at((layout.motion.start + layout.motion.end) / 2.0)


def frame(layout, index):
    return mv_text.draw(layout, layout.motion.at(layout.motion.start + index / layout.motion.fps))


def alpha(im):
    return im.getchannel("A")


def pixels(im, test):
    """the mask (255 / 0) of the pixels whose (r, g, b, a) pass `test` channel by channel: a value to equal or
    a function of the value"""
    mask = Image.new("L", im.size, 255)
    for band, want in zip(im.split(), test):
        if want is None:
            continue
        check = want if callable(want) else (lambda v, want=want: v == want)
        mask = ImageChops.multiply(mask, band.point(lambda v, check=check: 255 if check(v) else 0))
    return mask


def solid(im, colour):
    """the box of the opaque pixels of exactly this colour; None when there is none"""
    return pixels(im, colour + (255,)).getbbox()


def inside(box, outer, slack=0):
    return (box[0] >= outer[0] - slack and box[1] >= outer[1] - slack and box[2] <= outer[2] + slack
            and box[3] <= outer[3] + slack)


class DrawTest(unittest.TestCase):
    def test_a_cue_at_rest_is_opaque_in_its_block_and_empty_outside_it(self):
        cues = (title(anim="fade"), cue_of("Motion \u3048\u306c\u305f / Model Sour", "credit"), cue_of("HIBIKASE", "hook"),
                cue_of("gypsy jig", "caption", x="left", y="bottom"), cue_of("\u97ff\u304b\u305b", "title_jp", x="right", y="top"))
        for cue in cues:
            layout = lay(cue)
            im = mv_text.draw(layout, hold(layout))
            self.assertEqual((im.mode, im.size), ("RGBA", layout.canvas))
            block = block_rect(layout)
            self.assertGreater(alpha(im).crop(block).getextrema()[1], 250, cue["style"] if "style" in cue else "title")
            self.assertTrue(inside(alpha(im).getbbox(), block, slack=2), (alpha(im).getbbox(), block))

    def test_the_first_frame_of_a_fade_is_empty_and_the_cue_is_whole_once_it_has_come(self):
        layout = lay(cue_of("ABC", "caption"))
        self.assertEqual(alpha(frame(layout, 0)).getextrema(), (0, 0))
        partly = alpha(frame(layout, 9)).getextrema()[1]                    # half way through the enter: 0.875
        self.assertLessEqual(abs(partly - 0.875 * 255), 1.5)
        self.assertEqual(alpha(frame(layout, 18)).getextrema()[1], 255)
        self.assertEqual(frame(layout, 18).tobytes(), mv_text.draw(layout, hold(layout)).tobytes())

    def test_the_colour_is_not_darkened_where_the_edge_is_half_transparent(self):
        # the pictures are straight alpha: a half covered pixel has the full colour and half the alpha.  Drawing
        # text onto a transparent picture directly mixes the colour with the transparent black instead, which
        # shows as a dark rim once ffmpeg lays it over the video.
        layout = lay(cue_of("gypsy jig", "caption"))
        im = mv_text.draw(layout, hold(layout))
        colours = {rgba[:3] for _, rgba in im.getcolors(maxcolors=1 << 20) if rgba[3] > 0}
        self.assertEqual(colours, {TEXT})
        self.assertTrue(any(0 < rgba[3] < 255 for _, rgba in im.getcolors(maxcolors=1 << 20)))
        half = mv_text.draw(layout, dataclasses.replace(hold(layout), alpha=0.5))
        self.assertEqual({rgba[:3] for _, rgba in half.getcolors(maxcolors=1 << 20) if rgba[3] > 0}, {TEXT})
        self.assertLessEqual(abs(alpha(half).getextrema()[1] - 127.5), 1.0)

    def test_each_line_has_the_colour_of_its_style(self):
        layout = lay(title(anim="fade"))
        im = mv_text.draw(layout, hold(layout))
        block = block_rect(layout)
        text_box, accent_box = solid(im, TEXT), solid(im, ACCENT)
        # the logo and the Japanese title in the text colour, the sub-head under them in the accent
        self.assertLessEqual(abs(text_box[1] - block[1]), 1)
        self.assertGreater(accent_box[1], text_box[3] - 1)
        self.assertLessEqual(abs(accent_box[3] - block[3]), 1)
        light = lay(title(anim="fade"), palette="light")
        im = mv_text.draw(light, hold(light))
        self.assertIsNotNone(solid(im, INK))
        self.assertIsNone(solid(im, TEXT))
        credit = lay(cue_of("Motion \u3048\u306c\u305f", "credit"))
        box = solid(mv_text.draw(credit, hold(credit)), SECONDARY)
        self.assertGreater(box[2] - box[0], 0.9 * credit.block[0])            # both scripts are drawn, end to end

    def test_tracking_in_starts_wider_than_it_rests_and_closes_towards_its_anchor(self):
        for x in ("left", "center", "right"):
            layout = lay(cue_of("HIBI", "logo", anim="tracking-in", x=x))
            rest = alpha(mv_text.draw(layout, hold(layout))).getbbox()
            start = layout.motion.at(layout.motion.start)
            self.assertEqual((start.alpha, start.tracking_extra), (0.0, 0.6))
            spread = alpha(mv_text.draw(layout, dataclasses.replace(start, alpha=1.0))).getbbox()
            grown = (spread[2] - spread[0]) - (rest[2] - rest[0])
            self.assertLessEqual(abs(grown - 0.6 * 150 * 3), 2, x)            # three gaps of 0.6 em
            if x == "left":
                self.assertLessEqual(abs(spread[0] - rest[0]), 1)
            elif x == "right":
                self.assertLessEqual(abs(spread[2] - rest[2]), 1)
            else:
                self.assertLessEqual(abs((spread[0] + spread[2]) - (rest[0] + rest[2])), 2)
            # the first frame that shows anything is still spread
            second = alpha(frame(layout, 1)).getbbox()
            self.assertGreater(second[2] - second[0], rest[2] - rest[0] + 200, x)

    def test_rise_draws_the_cue_lower_while_it_comes_and_higher_as_it_goes(self):
        layout = lay(cue_of("ABC", "caption", anim="rise"))
        rest = alpha(mv_text.draw(layout, hold(layout))).getbbox()
        self.assertTrue(inside(rest, block_rect(layout), slack=1))
        start = dataclasses.replace(layout.motion.at(layout.motion.start), alpha=1.0)
        low = alpha(mv_text.draw(layout, start)).getbbox()
        self.assertEqual((low[1] - rest[1], low[3] - rest[3]), (24, 24))
        self.assertEqual((low[0], low[2]), (rest[0], rest[2]))
        last = alpha(frame(layout, layout.frames - 1)).getbbox()
        self.assertLess(last[1], rest[1])
        self.assertGreaterEqual(last[1], rest[1] - 12)

    def test_wipe_half_way_shows_the_left_and_nothing_of_the_right(self):
        layout = lay(cue_of(BAR, "caption", anim="wipe"))
        x0, y0, x1, y1 = block_rect(layout)
        whole = mv_text.draw(layout, hold(layout))
        self.assertEqual(alpha(whole).crop((x0, y0, x1, y1)).getextrema(), (255, 255))       # the bar fills its block
        half = mv_text.draw(layout, dataclasses.replace(hold(layout), wipe=0.5))
        width = x1 - x0
        self.assertIsNone(alpha(half).crop((x0 + int(0.6 * width), 0, half.size[0], half.size[1])).getbbox())
        self.assertEqual(alpha(half).crop((x0, y0, x0 + int(0.4 * width), y1)).getextrema(), (255, 255))
        # the edge is soft over 24 px: along a row the alpha only falls, through that many steps
        row = [alpha(half).getpixel((x, (y0 + y1) // 2)) for x in range(x0, x1)]
        self.assertEqual(row, sorted(row, reverse=True))
        self.assertLessEqual(abs(len([v for v in row if 0 < v < 255]) - 24), 2)
        # half way the edge has passed half of the block and of its own width: 280 / 2 + 24 / 2 = 152 px
        self.assertEqual(row.index(0), 152)
        self.assertEqual(len([v for v in row if v == 255]), 128)
        # a shadow reaches past the block: nothing of it shows before the wipe starts, all of it at the end
        soft = lay(cue_of(BAR, "lyric", anim="wipe"))
        self.assertEqual(alpha(mv_text.draw(soft, dataclasses.replace(hold(soft), wipe=0.0))).getextrema(), (0, 0))
        self.assertEqual(mv_text.draw(soft, dataclasses.replace(hold(soft), wipe=0.999999)).tobytes(),
                         mv_text.draw(soft, hold(soft)).tobytes())
        self.assertEqual(alpha(mv_text.draw(layout, dataclasses.replace(hold(layout), wipe=0.0))).getextrema(), (0, 0))
        self.assertEqual(mv_text.draw(layout, dataclasses.replace(hold(layout), wipe=1.0)).tobytes(), whole.tobytes())
        # a wipe comes at full alpha: what is shown on its first frames is opaque
        self.assertEqual(alpha(frame(layout, 0)).getextrema(), (0, 0))
        self.assertEqual(alpha(frame(layout, 4)).getextrema()[1], 255)

    def test_flash_is_there_gone_there_dim_there(self):
        layout = lay(cue_of("HIBIKASE", "hook", anim="flash", start=44.5, end=45.3))
        peaks = [alpha(frame(layout, i)).getextrema()[1] for i in range(7)]
        self.assertEqual(peaks[:3], [255, 0, 255])
        self.assertLessEqual(abs(peaks[3] - 0.35 * 255), 1.0)
        self.assertEqual(peaks[4:], [255, 255, 255])
        self.assertEqual(alpha(frame(layout, layout.frames - 1)).getextrema()[1], 255)     # cut off, not faded
        self.assertEqual(frame(layout, 0).tobytes(), frame(layout, layout.frames - 1).tobytes())

    def test_the_hook_has_a_copy_in_ink_3_px_to_its_left(self):
        layout = lay(cue_of("HIBIKASE", "hook"))
        im = mv_text.draw(layout, hold(layout))
        ink, accent = solid(im, INK), solid(im, ACCENT)
        self.assertIsNotNone(ink)
        self.assertEqual(ink[0], accent[0] - 3)                               # ink shows to the left of the accent
        self.assertLessEqual(ink[2], accent[2])                               # and never to its right
        self.assertLessEqual(max(abs(ink[1] - accent[1]), abs(ink[3] - accent[3])), 2)     # at the same height
        self.assertTrue(inside(ink, block_rect(layout), slack=1))
        # twice as far in a frame twice as high
        big = lay(cue_of("HIBIKASE", "hook"), size=(2560, 1440))
        im = mv_text.draw(big, hold(big))
        self.assertEqual(solid(im, INK)[0], solid(im, ACCENT)[0] - 6)
        self.assertIsNone(solid(mv_text.draw(lay(cue_of("AB", "logo")), hold(lay(cue_of("AB", "logo")))), INK))

    def test_a_lyric_has_an_accent_rule_under_it_60_percent_of_its_width(self):
        text = "\u97ff\u304b\u305b\u3066\u3044\u304f\u3088"                      # 7 kana and kanji: 322 px
        layout = lay(cue_of(text, "lyric"))
        im = mv_text.draw(layout, hold(layout))
        rule = solid(im, ACCENT)
        self.assertLessEqual(abs((rule[2] - rule[0]) - 0.6 * layout.width), 3)
        self.assertEqual(rule[3] - rule[1], 2)
        x0, y0, x1, y1 = block_rect(layout)
        self.assertLessEqual(abs((rule[0] + rule[2]) - (x0 + x1)), 2)         # centred under the text
        self.assertEqual(rule[3], y1)                                         # the last thing in the block
        words = solid(im, TEXT)
        self.assertGreater(rule[1], words[3])                                 # under the text, clear of it
        # every pixel of the rule's rows between its ends is accent: a row, not dots
        self.assertEqual(pixels(im, ACCENT + (255,)).crop(rule).getextrema(), (255, 255))
        # it is drawn while the cue comes: nothing at first, 87.5 % half way through the enter
        self.assertIsNone(solid(mv_text.draw(layout, dataclasses.replace(hold(layout), underline=0.0)), ACCENT))
        grown = solid(mv_text.draw(layout, dataclasses.replace(hold(layout), underline=0.875)), ACCENT)
        self.assertEqual(grown[0], rule[0])                                   # from its left end
        self.assertLessEqual(abs((grown[2] - grown[0]) - 0.875 * (rule[2] - rule[0])), 1)
        coming = pixels(frame(layout, 9), ACCENT + (lambda a: a > 0,)).getbbox()   # frame 9 of the cue itself
        self.assertEqual(coming, grown)
        self.assertIsNone(pixels(frame(layout, 0), ACCENT + (None,)).getbbox())
        # left and right anchored lyrics keep the rule on their side
        left, right = lay(cue_of(text, "lyric", x="left")), lay(cue_of(text, "lyric", x="right"))
        self.assertEqual(solid(mv_text.draw(left, hold(left)), ACCENT)[0], block_rect(left)[0])
        self.assertEqual(solid(mv_text.draw(right, hold(right)), ACCENT)[2], block_rect(right)[2])
        self.assertIsNone(solid(mv_text.draw(lay(cue_of(text, "caption")), hold(lay(cue_of(text, "caption")))), ACCENT))

    def test_a_lyric_has_a_soft_shadow_under_its_text(self):
        # the same text in black at alpha 170, blurred 6 px, 2 px lower, under the text.  A solid bar shows
        # its measure: Pillow's blur of 6 reaches 15 px past the bar, so 13 px above it and 17 px below.
        layout = lay(cue_of(BAR, "lyric"))
        im = mv_text.draw(layout, hold(layout))
        bar, shadow = solid(im, TEXT), pixels(im, (0, 0, 0, lambda a: a > 0)).getbbox()
        self.assertEqual((bar[1] - shadow[1], shadow[3] - bar[3]), (13, 17))
        self.assertEqual((bar[0] - shadow[0], shadow[2] - bar[2]), (15, 15))
        blacks = sorted(a for _, (r, g, b, a) in im.getcolors(maxcolors=1 << 20) if (r, g, b) == (0, 0, 0) and a > 0)
        self.assertLessEqual(blacks[-1], 170)
        # beside a long straight edge the blur leaves just under half of the shadow (120 of 255, measured):
        # 170 x 120 / 255 = 80
        beside = im.getpixel((bar[0] - 1, (bar[1] + bar[3]) // 2))
        self.assertEqual(beside[:3], (0, 0, 0))
        self.assertLessEqual(abs(beside[3] - 80), 2)
        self.assertEqual(blacks[0], 1)                                        # and it fades out to nothing
        # the canvas has the room: its border is empty, so the blur was not cut off
        w, h = im.size
        for edge in ((0, 0, w, 1), (0, h - 1, w, h), (0, 0, 1, h), (w - 1, 0, w, h)):
            self.assertEqual(alpha(im).crop(edge).getextrema(), (0, 0), edge)
        # the text lies over it untouched
        self.assertEqual(alpha(im).crop(bar).getextrema(), (255, 255))
        # the shadow goes with the cue: half as strong at half alpha, none in a style without it
        half = mv_text.draw(layout, dataclasses.replace(hold(layout), alpha=0.5))
        strongest = max(a for _, (r, g, b, a) in half.getcolors(maxcolors=1 << 20) if (r, g, b) == (0, 0, 0))
        self.assertLessEqual(abs(strongest - blacks[-1] / 2.0), 1.5)
        caption = lay(cue_of(BAR, "caption"))
        self.assertIsNone(pixels(mv_text.draw(caption, hold(caption)), (0, 0, 0, lambda a: a > 0)).getbbox())
        # real words have it too, and in a frame twice as high it reaches twice as far
        words = lay(cue_of("\u97ff\u304b\u305b\u3066", "lyric"))
        self.assertIsNotNone(pixels(mv_text.draw(words, hold(words)), (0, 0, 0, lambda a: a > 20)).getbbox())
        big = lay(cue_of(BAR, "lyric"), size=(2560, 1440))
        im = mv_text.draw(big, hold(big))
        bar, shadow = solid(im, TEXT), pixels(im, (0, 0, 0, lambda a: a > 0)).getbbox()
        self.assertEqual((shadow[3] - bar[3]) - (bar[1] - shadow[1]), 8)
        self.assertGreater(bar[1] - shadow[1], 22)

    def test_every_letter_sits_on_a_whole_pixel_the_nearest_halves_up(self):
        # Pillow draws a glyph on whole pixels only (asked for x.25 it draws at x, for x.75 at x + 1), so the
        # tool says itself which pixel: the nearest, halves going up.  sub has 7.5 px of tracking after every
        # letter (0.25 em of 30 px), so most letters of a line ask for half a pixel.
        layout = lay(cue_of("feat. KAGAMINE RIN", "sub"))
        line = layout.lines[0]
        ox = layout.anchor[0] + layout.origin[0] - layout.canvas_origin[0]
        oy = layout.anchor[1] + layout.origin[1] - layout.canvas_origin[1] + line.baseline
        self.assertEqual(oy, int(oy))

        def expected(extra, nearest):
            mask = Image.new("L", layout.canvas, 0)
            pen, x = ImageDraw.Draw(mask), ox + layout.line_x(line, extra)
            halves = 0
            for g in line.glyphs:
                halves += (x % 1.0 == 0.5)
                pen.text((nearest(x), int(oy)), g.char, font=g.font, fill=255, anchor="ls")
                x += g.advance + (g.tracking + extra) * g.size
            return mask, halves

        def up(x):
            return int(math.floor(x + 0.5))

        wanted, halves = expected(0.0, up)
        self.assertGreater(halves, 4)
        self.assertNotEqual(wanted.tobytes(), expected(0.0, lambda x: int(round(x)))[0].tobytes())      # halves to even differ
        self.assertEqual(alpha(mv_text.draw(layout, hold(layout))).tobytes(), wanted.tobytes())
        # letters that spread or close move by whole pixels too
        moving = dataclasses.replace(hold(layout), tracking_extra=0.31)
        self.assertEqual(alpha(mv_text.draw(layout, moving)).tobytes(), expected(0.31, up)[0].tobytes())

    def test_a_block_moves_by_fractions_of_a_pixel(self):
        # a slow move in whole pixels steps (a roll at 1.87 px a frame would go 2, 2, 2, 1, 2 ...).  The picture
        # a fraction of a pixel on the way is the two whole-pixel pictures around it, mixed in that proportion.
        # (Each colour is shifted by itself and then they are laid over each other, so this holds to the last
        # level where one colour is drawn; the hook's ink copy under its text mixes a little differently
        # where their soft edges meet.)
        for style in ("caption", "lyric"):
            layout = lay(cue_of("ABC", style, anim="rise"))
            rest = hold(layout)
            for axis in ("dy", "dx"):
                low, high = (mv_text.draw(layout, dataclasses.replace(rest, **{axis: v})) for v in (3.0, 4.0))
                self.assertNotEqual(low.tobytes(), high.tobytes())
                for share in (0.25, 0.5, 0.75):
                    between = mv_text.draw(layout, dataclasses.replace(rest, **{axis: 3.0 + share}))
                    off = ImageChops.difference(alpha(between), Image.blend(alpha(low), alpha(high), share)).getextrema()[1]
                    self.assertLessEqual(off, 3, (style, axis, share))
            up = mv_text.draw(layout, dataclasses.replace(rest, dy=-0.5))
            low, high = (mv_text.draw(layout, dataclasses.replace(rest, dy=v)) for v in (-1.0, 0.0))
            off = ImageChops.difference(alpha(up), Image.blend(alpha(low), alpha(high), 0.5)).getextrema()[1]
            self.assertLessEqual(off, 3, style)
        # a whole number of pixels is the picture at rest moved, nothing softened
        layout = lay(cue_of("ABC", "caption", anim="rise"))
        still = alpha(mv_text.draw(layout, hold(layout)))
        moved = alpha(mv_text.draw(layout, dataclasses.replace(hold(layout), dy=5.0, dx=-3.0)))
        self.assertEqual(moved.tobytes(), ImageChops.offset(still, -3, 5).tobytes())
        # and the colour stays the text's own where the edge is mixed
        soft = mv_text.draw(layout, dataclasses.replace(hold(layout), dy=0.5))
        self.assertEqual({rgba[:3] for _, rgba in soft.getcolors(maxcolors=1 << 20) if rgba[3] > 0}, {TEXT})

    def test_under_ink_text_the_shadow_is_a_white_halo(self):
        # a black shadow under dark text smears it: on the white stage the text is ink, so what parts it from
        # the picture is light around it
        layout = lay(cue_of(BAR, "lyric"), palette="light")
        im = mv_text.draw(layout, hold(layout))
        self.assertIsNone(pixels(im, (0, 0, 0, lambda a: a > 0)).getbbox())
        bar, halo = solid(im, INK), pixels(im, (255, 255, 255, lambda a: a > 0)).getbbox()
        self.assertEqual((bar[1] - halo[1], halo[3] - bar[3]), (13, 17))
        whites = [a for _, (r, g, b, a) in im.getcolors(maxcolors=1 << 20) if (r, g, b) == (255, 255, 255) and a > 0]
        self.assertLessEqual(max(whites), 170)
        self.assertEqual(mv_text.PALETTES["dark"]["shadow"], (0, 0, 0))

    def test_a_roll_passes_through_the_frame(self):
        layout = lay(title(anim="roll", start=10.0, end=30.0, x="center"))
        self.assertEqual(alpha(frame(layout, 0)).getextrema(), (0, 0))        # still under the frame
        middle = alpha(frame(layout, layout.frames // 2)).getbbox()
        self.assertIsNotNone(middle)
        early, late = alpha(frame(layout, 100)).getbbox(), alpha(frame(layout, 200)).getbbox()
        self.assertLess(late[1], early[1])                                    # it moves up
        last = alpha(frame(layout, layout.frames - 1)).getbbox()
        self.assertTrue(last is None or last[3] < 12)                         # all but gone over the top


def small_doc(*cues, **top):
    """a cue file for a 640 x 360 frame at 30 fps"""
    doc = {"fps": 30, "size": [640, 360], "cues": list(cues)}
    doc.update(top)
    return doc


RISE_CUE = {"id": "a1", "start": 0.5, "end": 1.5, "text": "ABC", "style": "caption", "anim": "rise", "x": "left", "y": "top"}
BACK_CUE = {"id": "b2", "start": 1.0, "end": 3.0, "text": "HIBI", "style": "logo", "anim": "fade", "layer": "back"}


class SequencesTest(unittest.TestCase):
    def setUp(self):
        book()                                                                # skip without any font
        self.work = os.path.join(tempfile.mkdtemp(), "work")

    def test_every_frame_of_a_cue_is_a_png_of_its_canvas(self):
        plan = mv_text.render_sequences(small_doc(RISE_CUE), self.work)
        entry = plan["cues"][0]
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "cue_a1"))), ["f%05d.png" % i for i in range(30)])
        self.assertEqual(os.listdir(self.work), ["cue_a1"])
        layout = lay(RISE_CUE, size=(640, 360))
        for i in (0, 1, 9, 17, 18, 24, 29):
            with Image.open(entry["pattern"] % i) as im:
                self.assertEqual((im.mode, im.size), ("RGBA", layout.canvas), i)
                self.assertEqual(im.tobytes(), frame(layout, i).tobytes(), i)   # the frame draw() gives for that time
        with Image.open(entry["pattern"] % 0) as im:
            self.assertEqual(alpha(im).getextrema(), (0, 0))
        with Image.open(entry["pattern"] % 18) as im:                        # the one frame fully there: 0.6 s in
            self.assertEqual(alpha(im).getextrema()[1], 255)

    def test_the_plan_says_where_and_when_each_sequence_goes(self):
        plan = mv_text.render_sequences(small_doc(RISE_CUE, BACK_CUE), self.work)
        self.assertEqual(sorted(plan), ["cues", "fps", "size", "warnings"])
        # the warnings are those of the fonts of this machine (none where the Y1 faces and Noto are installed)
        self.assertEqual((plan["fps"], plan["size"], plan["warnings"]), (30, [640, 360], mv_text.FontBook().warnings))
        self.assertEqual([sorted(entry) for entry in plan["cues"]],
                         [["canvas", "frames", "id", "layer", "pattern", "start", "start_frame", "x", "y"]] * 2)
        first, second = plan["cues"]
        layout = lay(RISE_CUE, size=(640, 360))
        self.assertEqual((first["id"], first["layer"], first["start_frame"], first["start"], first["frames"]),
                         ("a1", "front", 15, 0.5, 30))
        self.assertEqual(((first["x"], first["y"]), first["canvas"]), (layout.canvas_origin, list(layout.canvas)))
        self.assertEqual((second["id"], second["layer"], second["start_frame"], second["start"], second["frames"]),
                         ("b2", "back", 30, 1.0, 60))
        # the printf path of the pictures, with forward slashes, whatever folder the caller is in
        folder = os.path.abspath(self.work).replace("\\", "/")
        self.assertEqual(first["pattern"], folder + "/cue_a1/f%05d.png")
        self.assertEqual(second["pattern"], folder + "/cue_b2/f%05d.png")
        self.assertTrue(os.path.isabs(first["pattern"]))
        # a folder given relative to where the caller stands is still told in full
        here = os.getcwd()
        os.chdir(os.path.dirname(self.work))
        try:
            relative = mv_text.render_sequences(small_doc(RISE_CUE), "work")
        finally:
            os.chdir(here)
        self.assertEqual(relative["cues"][0]["pattern"], first["pattern"])
        for entry in plan["cues"]:
            self.assertTrue(os.path.exists(entry["pattern"] % (entry["frames"] - 1)))
            self.assertFalse(os.path.exists(entry["pattern"] % entry["frames"]))
        # it travels as one line of ASCII JSON
        text = json.dumps(plan, ensure_ascii=True)
        self.assertEqual(json.loads(text), plan)
        self.assertNotIn("\n", text)

    def test_the_frame_and_the_rate_can_be_given_instead_of_the_cue_files(self):
        plan = mv_text.render_sequences(small_doc(RISE_CUE), self.work, size=(320, 180), fps=60)
        self.assertEqual((plan["fps"], plan["size"]), (60, [320, 180]))
        entry = plan["cues"][0]
        self.assertEqual((entry["start_frame"], entry["start"], entry["frames"]), (30, 0.5, 60))
        layout = lay(RISE_CUE, size=(320, 180), fps=60)
        self.assertEqual(entry["canvas"], list(layout.canvas))
        self.assertEqual(len(os.listdir(os.path.join(self.work, "cue_a1"))), 60)
        # a rate that is not a whole number stays exact: the text ffmpeg takes
        ntsc = mv_text.render_sequences(small_doc(RISE_CUE), self.work, fps="30000/1001")
        self.assertEqual(ntsc["fps"], "30000/1001")
        self.assertEqual((ntsc["cues"][0]["start_frame"], ntsc["cues"][0]["frames"]), (15, 30))
        self.assertAlmostEqual(ntsc["cues"][0]["start"], 15 * 1001 / 30000.0)
        self.assertEqual(mv_text.render_sequences(small_doc(RISE_CUE), self.work, fps=fractions.Fraction(25))["fps"], 25)

    def test_the_cues_can_be_the_document_its_path_or_a_sheet(self):
        doc = small_doc(RISE_CUE)
        path = os.path.join(os.path.dirname(self.work), "cues.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        wanted = mv_text.render_sequences(doc, self.work)
        self.assertEqual(mv_text.render_sequences(path, self.work), wanted)
        self.assertEqual(mv_text.render_sequences(mv_text.parse_cues(doc), self.work), wanted)
        flat = mv_text.render_sequences([{"text": "x", "start": 0, "end": 0.2, "style": "credit"}], self.work)
        self.assertEqual((flat["size"], flat["cues"][0]["id"], flat["cues"][0]["frames"]), ([1280, 720], "c00", 6))

    def test_frames_left_by_an_earlier_longer_run_are_removed(self):
        # ffmpeg reads a sequence until a number is missing: a frame left behind would lengthen the cue
        folder = os.path.join(self.work, "cue_a1")
        os.makedirs(folder)
        for name in ("f00030.png", "f00031.png", "f00100.png", "notes.txt", "f00002.png.part", "f00050.png.part"):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(b"old")
        mv_text.render_sequences(small_doc(RISE_CUE), self.work)
        self.assertEqual(sorted(os.listdir(folder)), ["f%05d.png" % i for i in range(30)] + ["notes.txt"])

    def test_frames_that_look_the_same_are_the_same_bytes(self):
        plan = mv_text.render_sequences(small_doc(dict(RISE_CUE, end=3.5)), self.work)
        pattern = plan["cues"][0]["pattern"]

        def data(i):
            with open(pattern % i, "rb") as f:
                return f.read()
        self.assertEqual(data(30), data(60))                                  # both at rest
        self.assertNotEqual(data(5), data(30))
        self.assertNotEqual(data(89), data(60))

    def test_it_prints_nothing_and_collects_the_warnings(self):
        out = io.StringIO()
        without_y1 = mv_text.FontBook(user_dir=tempfile.mkdtemp())
        wide = {"id": "w", "start": 0, "end": 0.1, "text": "HIBIKASE " * 6, "style": "logo"}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            plan = mv_text.render_sequences(small_doc(RISE_CUE, wide), self.work, book=without_y1)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(len([w for w in plan["warnings"] if "Y1RevForge.otf" in w]), 1, plan["warnings"])
        self.assertEqual(len([w for w in plan["warnings"] if w.startswith("cue w:")]), 1, plan["warnings"])
        for warning in plan["warnings"]:
            warning.encode("ascii")

    def test_a_bad_cue_stops_it_before_anything_is_written(self):
        short = {"id": "z", "start": 1.0, "end": 1.01, "text": "x"}
        with self.assertRaises(ValueError):
            mv_text.render_sequences(small_doc(RISE_CUE, short), self.work)
        self.assertFalse(os.path.exists(self.work))
        for size, fps in (((0, 180), None), ((320,), None), ("320x180", None), (None, 0), (None, "fast")):
            with self.assertRaises(ValueError, msg=repr((size, fps))):
                mv_text.render_sequences(small_doc(RISE_CUE), self.work, size=size, fps=fps)
        self.assertFalse(os.path.exists(self.work))

    def test_no_cues_is_an_empty_plan(self):
        plan = mv_text.render_sequences(small_doc(), self.work)
        self.assertEqual(plan, {"fps": 30, "size": [640, 360], "cues": [], "warnings": mv_text.FontBook().warnings})
        self.assertFalse(os.path.exists(self.work))


def plan_cue(cue_id, x, y, start_frame, frames, fps=30):
    return {"id": cue_id, "layer": "front", "x": x, "y": y, "canvas": [200, 60], "start_frame": start_frame,
            "start": float(fractions.Fraction(start_frame) / fractions.Fraction(str(fps))), "frames": frames,
            "pattern": "C:/work/cue_%s/f%%05d.png" % cue_id}


PLAN = {"fps": 30, "size": [1280, 720], "warnings": [],
        "cues": [plan_cue("title", 56, 40, 30, 150), plan_cue("hook1", 240, 278, 1335, 24), plan_cue("late", 0, 600, 123, 12)]}


def after(cmd, flag):
    """the arguments that follow each `flag`"""
    return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == flag]


class CommandTest(unittest.TestCase):
    def test_the_video_comes_first_then_one_input_per_cue(self):
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", PLAN)
        self.assertTrue(all(isinstance(arg, str) for arg in cmd))
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertEqual(cmd[-1], "out.mp4")
        self.assertEqual(after(cmd, "-i"), ["in.avi", "C:/work/cue_title/f%05d.png", "C:/work/cue_hook1/f%05d.png",
                                            "C:/work/cue_late/f%05d.png"])
        for pattern in after(cmd, "-i")[1:]:
            at = cmd.index(pattern)
            self.assertEqual(cmd[at - 5:at], ["-framerate", "30", "-start_number", "0", "-i"])
        self.assertLess(cmd.index("-y"), cmd.index("-i"))
        self.assertIn("-nostdin", cmd)                                        # it must not wait for a key

    def test_each_sequence_is_shifted_to_its_start_and_laid_at_its_canvas(self):
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", PLAN)
        chains = after(cmd, "-filter_complex")[0].split(";")
        self.assertEqual(chains, [
            "[1:v]format=rgba,setpts=PTS-STARTPTS+round(1/1/TB)[t1]", "[0:v][t1]overlay=x=56:y=40:eof_action=pass[v1]",
            "[2:v]format=rgba,setpts=PTS-STARTPTS+round(89/2/TB)[t2]", "[v1][t2]overlay=x=240:y=278:eof_action=pass[v2]",
            "[3:v]format=rgba,setpts=PTS-STARTPTS+round(41/10/TB)[t3]", "[v2][t3]overlay=x=0:y=600:eof_action=pass[v3]"])
        for chain, cue in zip(chains[0::2], PLAN["cues"]):
            num, den = re.search(r"\+round\((\d+)/(\d+)/TB\)", chain).groups()
            self.assertEqual(fractions.Fraction(int(num), int(den)), fractions.Fraction(cue["start_frame"], 30))
            self.assertAlmostEqual(int(num) / float(den), cue["start"])

    def test_the_shift_is_rounded_because_setpts_cuts_its_result_off(self):
        # setpts turns its result into a whole tick by cutting the fraction off, and 4.1 s over a tick of
        # 1/30 s is 122.99999999999999 in floating point: without round() the cue that starts on frame 123
        # shows from frame 122 (seen with ffmpeg 8.1.2: frames 122..134 lit instead of 123..134)
        self.assertEqual(int(4.1 / (1 / 30.0)), 122)
        self.assertEqual(int(round(4.1 / (1 / 30.0))), 123)
        graph = after(mv_text.ffmpeg_command("in.avi", "out.mp4", PLAN), "-filter_complex")[0]
        self.assertEqual(graph.count("setpts=PTS-STARTPTS+round("), 3)
        self.assertEqual(len(re.findall(r"setpts=[^\[]*/TB(?!\))", graph)), 0)       # no shift is left bare

    def test_the_last_picture_is_mapped_encoded_and_the_sound_copied(self):
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", PLAN)
        self.assertEqual(after(cmd, "-map"), ["[v3]", "0:a?"])
        pairs = list(zip(cmd, cmd[1:]))
        for pair in (("-c:v", "libx264"), ("-preset", "medium"), ("-crf", "18"), ("-pix_fmt", "yuv420p"),
                     ("-movflags", "+faststart"), ("-c:a", "copy")):
            self.assertIn(pair, pairs)
        self.assertGreater(cmd.index("-map"), cmd.index("-filter_complex"))

    def test_a_rate_that_is_a_fraction_stays_exact(self):
        plan = dict(PLAN, fps="30000/1001", cues=[plan_cue("title", 56, 40, 30, 150, fps="30000/1001")])
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", plan)
        self.assertEqual(after(cmd, "-framerate"), ["30000/1001"])
        self.assertIn("setpts=PTS-STARTPTS+round(1001/1000/TB)", after(cmd, "-filter_complex")[0])
        # MMD writes its rate as 30000030/1000001, which is 30 exactly (30 x 1000001): it is passed on as 30
        mmd = dict(PLAN, fps="30000030/1000001", cues=[plan_cue("title", 56, 40, 30, 150, fps="30000030/1000001")])
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", mmd)
        self.assertEqual(after(cmd, "-framerate"), ["30"])
        self.assertIn("setpts=PTS-STARTPTS+round(1/1/TB)", after(cmd, "-filter_complex")[0])

    def test_without_cues_the_video_is_only_encoded(self):
        cmd = mv_text.ffmpeg_command("in.avi", "out.mp4", dict(PLAN, cues=[]))
        self.assertNotIn("-filter_complex", cmd)
        self.assertEqual(after(cmd, "-i"), ["in.avi"])
        self.assertEqual(after(cmd, "-map"), ["0:v", "0:a?"])

    def test_more_cues_than_a_command_line_holds_is_an_error(self):
        # Windows takes 32767 characters; every cue adds an input and two filters
        many = dict(PLAN, cues=[plan_cue("c%03d" % i, 0, 0, i * 30, 20) for i in range(400)])
        with self.assertRaises(ValueError) as caught:
            mv_text.ffmpeg_command("in.avi", "out.mp4", many)
        self.assertIn("400", str(caught.exception))
        mv_text.ffmpeg_command("in.avi", "out.mp4", dict(PLAN, cues=many["cues"][:60]))

    def test_the_probe_asks_ffprobe_for_the_frame_and_the_rate(self):
        self.assertEqual(mv_text.probe_command("in.avi"),
                         ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-of", "json", "in.avi"])
        answer = '{"programs": [], "streams": [{"width": 1280, "height": 720, "r_frame_rate": "30000030/1000001"}]}'
        self.assertEqual(mv_text.parse_probe(answer), ((1280, 720), fractions.Fraction(30)))       # what MMD writes
        ntsc = '{"streams": [{"width": 1920, "height": 1080, "r_frame_rate": "30000/1001"}]}'
        self.assertEqual(mv_text.parse_probe(ntsc), ((1920, 1080), fractions.Fraction(30000, 1001)))
        self.assertEqual(mv_text.parse_probe('{"streams": [{"width": 320, "height": 180, "r_frame_rate": "30/1"}]}'),
                         ((320, 180), fractions.Fraction(30)))
        for bad in ('{"streams": []}', "{}", "", "not json", '{"streams": [{"width": 320}]}',
                    '{"streams": [{"width": 320, "height": 180, "r_frame_rate": "0/0"}]}'):
            with self.assertRaises(ValueError, msg=bad):
                mv_text.parse_probe(bad)

    def test_a_size_on_the_command_line_is_width_x_height(self):
        self.assertEqual(mv_text.parse_size("1280x720"), (1280, 720))
        self.assertEqual(mv_text.parse_size("320X180"), (320, 180))
        for bad in ("1280", "1280x", "x720", "0x720", "1280x720x3", "wide", "12.5x7", "-1280x720"):
            with self.assertRaises(ValueError, msg=bad):
                mv_text.parse_size(bad)


def run(argv):
    """main() with its one line of output, which must be ASCII (the terminal is cp932) and JSON"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mv_text.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    if text.count("\n") != 1 or not text.endswith("\n"):
        raise AssertionError("not one line: %r" % text)
    return code, json.loads(text)


class MainTest(unittest.TestCase):
    def setUp(self):
        book()
        self.folder = tempfile.mkdtemp()
        self.cues = os.path.join(self.folder, "cues.json")
        self.write(dict(NEW_FORMAT, size=[640, 360]))

    def write(self, doc):
        with open(self.cues, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def path(self, name):
        return os.path.join(self.folder, name)

    def test_frames_writes_the_sequences_and_prints_the_plan(self):
        self.write(small_doc(RISE_CUE, BACK_CUE))
        code, result = run(["frames", self.cues, self.path("work")])
        self.assertEqual(code, 0, result)
        wanted = mv_text.render_sequences(small_doc(RISE_CUE, BACK_CUE), self.path("work"))
        self.assertEqual(result, dict(wanted, ok=True))
        self.assertEqual([c["layer"] for c in result["cues"]], ["front", "back"])
        self.assertEqual(len(os.listdir(self.path("work/cue_a1"))), 30)

    def test_frames_takes_the_frame_and_the_rate_from_the_command_line(self):
        self.write(small_doc(RISE_CUE))
        code, result = run(["frames", self.cues, self.path("work"), "--size", "320x180", "--fps", "60"])
        self.assertEqual((code, result["size"], result["fps"], result["cues"][0]["frames"]), (0, [320, 180], 60, 60))
        code, result = run(["frames", self.cues, self.path("work"), "--fps", "30000/1001"])
        self.assertEqual((code, result["fps"], result["size"]), (0, "30000/1001", [640, 360]))

    def test_preview_draws_the_cues_of_that_moment_on_the_stage(self):
        out = self.path("shots/at3.png")
        code, result = run(["preview", self.cues, out, "--at", "3.0"])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["ok"], result["out"], result["at"], result["size"]), (True, os.path.abspath(out), 3.0, [640, 360]))
        self.assertEqual(result["cues"], ["title", "credit1"])               # 1 to 6 s and 2 to 7 s; the others are later
        with Image.open(out) as im:
            self.assertEqual((im.mode, im.size), ("RGB", (640, 360)))
            self.assertEqual(im.getpixel((639, 0)), (0, 0, 0))                # the black stage of the dark palette
            self.assertIsNotNone(pixels(im.convert("RGBA"), TEXT + (None,)).getbbox())
            self.assertIsNotNone(pixels(im.convert("RGBA"), ACCENT + (None,)).getbbox())
        self.assertEqual(os.listdir(os.path.dirname(out)), ["at3.png"])
        code, result = run(["preview", self.cues, out, "--at", "30"])
        self.assertEqual((code, result["cues"]), (0, []))
        with Image.open(out) as im:
            self.assertEqual(im.getextrema(), ((0, 0), (0, 0), (0, 0)))

    def test_preview_of_the_light_palette_is_on_white(self):
        self.write(dict(NEW_FORMAT, size=[640, 360], palette="light"))
        code, result = run(["preview", self.cues, self.path("light.png"), "--at", "3"])
        self.assertEqual(code, 0, result)
        with Image.open(self.path("light.png")) as im:
            self.assertEqual(im.getpixel((639, 0)), (255, 255, 255))
            self.assertIsNotNone(pixels(im.convert("RGBA"), INK + (None,)).getbbox())

    def test_preview_over_a_frame_of_the_video_keeps_the_frame_around_the_text(self):
        still = self.path("still.png")
        Image.new("RGB", (320, 180), (10, 80, 160)).save(still)
        out = self.path("over.png")
        code, result = run(["preview", self.cues, out, "--at", "3", "--over", still])
        self.assertEqual((code, result["size"], result["cues"]), (0, [320, 180], ["title", "credit1"]))
        with Image.open(out) as im:
            self.assertEqual(im.size, (320, 180))
            self.assertEqual(im.getpixel((319, 90)), (10, 80, 160))
            self.assertIsNotNone(pixels(im.convert("RGBA"), TEXT + (None,)).getbbox())
        with Image.open(still) as im:
            self.assertEqual(im.getextrema(), ((10, 10), (80, 80), (160, 160)))                 # the frame itself is untouched
        # a size asked for wins: the frame is scaled to it
        code, result = run(["preview", self.cues, out, "--at", "3", "--over", still, "--size", "640x360"])
        self.assertEqual((code, result["size"]), (0, [640, 360]))
        with Image.open(out) as im:
            self.assertEqual((im.size, im.getpixel((639, 180))), ((640, 360), (10, 80, 160)))

    def test_preview_draws_back_and_front_cues_alike(self):
        self.write(small_doc(dict(RISE_CUE, id="f1", start=0.0, end=4.0), dict(BACK_CUE, start=0.0, end=4.0)))
        code, result = run(["preview", self.cues, self.path("layers.png"), "--at", "2"])
        self.assertEqual((code, result["cues"]), (0, ["f1", "b2"]))

    def test_preview_shows_a_cue_in_the_middle_of_its_motion(self):
        self.write(small_doc(dict(RISE_CUE, start=1.0, end=3.0)))
        boxes, shown = {}, {}
        for at in ("0.99", "1.0", "1.1", "2.0", "3.0"):
            code, result = run(["preview", self.cues, self.path("m.png"), "--at", at])
            self.assertEqual(code, 0)
            shown[at] = result["cues"]
            with Image.open(self.path("m.png")) as im:
                boxes[at] = im.getbbox()
        self.assertIsNone(boxes["1.0"])                                       # alpha 0 on its first frame
        self.assertGreater(boxes["1.1"][1], boxes["2.0"][1])                  # still rising
        # a cue is on from its start to just before its end
        self.assertEqual(shown, {"0.99": [], "1.0": ["a1"], "1.1": ["a1"], "2.0": ["a1"], "3.0": []})
        # a flash is cut off at full strength: at its end there is nothing
        self.write(small_doc({"id": "h", "start": 1.0, "end": 2.0, "text": "HI", "style": "hook", "anim": "flash"}))
        for at, lit in (("1.9", True), ("2.0", False)):
            run(["preview", self.cues, self.path("m.png"), "--at", at])
            with Image.open(self.path("m.png")) as im:
                self.assertEqual(im.getbbox() is not None, lit, at)

    def test_render_moves_a_finished_video_over_out_and_removes_a_failed_one(self):
        # ffmpeg itself is stood in for: it writes where it is told and succeeds or fails
        video, out = self.path("in.avi"), self.path("final.mp4")
        for name, data in ((video, b"video"), (out, b"the old output")):
            with open(name, "wb") as f:
                f.write(data)
        self.write(small_doc(RISE_CUE))
        calls = []

        def fake(code):
            def run_it(argv):
                calls.append(argv)
                with open(argv[-1], "wb") as f:
                    f.write(b"new video")
                return code, "", "it broke\n"
            return run_it

        real = mv_text._run
        try:
            mv_text._run = fake(3)
            code, result = run(["render", video, self.cues, out, "--size", "640x360", "--fps", "30"])
            self.assertEqual((code, result["ok"], result["ffmpeg"]), (1, False, 3))
            self.assertEqual(result["error"], {"type": "ffmpeg", "message": "ffmpeg exited with 3: it broke"})
            self.assertEqual((result["cues"], result["frames"], result["out"]), (1, 30, os.path.abspath(out)))
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"the old output")
            self.assertEqual(sorted(os.listdir(self.folder)), ["cues.json", "final.mp4", "final.mp4.work", "in.avi"])
            mv_text._run = fake(0)
            code, result = run(["render", video, self.cues, out, "--size", "640x360", "--fps", "30"])
            self.assertEqual((code, result["ok"], result["ffmpeg"]), (0, True, 0))
            self.assertNotIn("error", result)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"new video")
            self.assertEqual(sorted(os.listdir(self.folder)), ["cues.json", "final.mp4", "final.mp4.work", "in.avi"])
        finally:
            mv_text._run = real
        # ffmpeg was asked to write next to the output, under a name that keeps the extension
        self.assertEqual([argv[0] for argv in calls], ["ffmpeg", "ffmpeg"])
        self.assertEqual(calls[0][-1], os.path.abspath(self.path("final.part.mp4")))
        self.assertEqual(calls[0], mv_text.ffmpeg_command(os.path.abspath(video), calls[0][-1],
                                                          mv_text.render_sequences(small_doc(RISE_CUE), self.path("final.mp4.work"))))
        self.assertEqual(sorted(result), ["cues", "ffmpeg", "fps", "frames", "ok", "out", "size", "warnings", "work"])

    def test_a_bad_cue_file_is_exit_2_and_writes_nothing(self):
        self.write({"cues": [{"id": "x", "start": 2, "end": 1, "text": "a"}]})
        for argv in (["frames", self.cues, self.path("work")], ["preview", self.cues, self.path("p.png"), "--at", "1"],
                     ["render", self.cues, self.cues, self.path("o.mp4")],
                     ["frames", self.path("none.json"), self.path("work")],
                     ["preview", self.path("none.json"), self.path("p.png"), "--at", "1"]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertEqual(sorted(result["error"]), ["message", "type"])
        self.assertEqual(os.listdir(self.folder), ["cues.json"])

    def test_arguments_that_cannot_be_used_are_exit_2(self):
        still = self.path("still.png")
        Image.new("RGB", (320, 180), (0, 0, 0)).save(still)
        for argv in (["frames", self.cues, self.path("work"), "--size", "640"],
                     ["frames", self.cues, self.path("work"), "--fps", "0"],
                     ["preview", self.cues, self.path("p.png"), "--at", "-1"],
                     ["preview", self.cues, self.cues, "--at", "1"],
                     ["preview", self.cues, still, "--at", "1", "--over", still],
                     ["preview", self.cues, self.path("p.png"), "--at", "1", "--over", self.path("none.png")],
                     ["render", self.path("none.avi"), self.cues, self.path("o.mp4")],
                     ["render", still, self.cues, still]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"], argv)
        self.assertEqual(sorted(os.listdir(self.folder)), ["cues.json", "still.png"])
        with open(self.cues, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["size"], [640, 360])                # the cue file was not written over

    def test_the_warnings_are_printed_as_ascii(self):
        self.write(small_doc({"id": "w", "start": 0, "end": 0.2, "text": "\u97ff\u304b\u305b" * 30}))
        code, result = run(["frames", self.cues, self.path("work")])
        self.assertEqual(code, 0)
        self.assertEqual(len([w for w in result["warnings"] if w.startswith("cue w:")]), 1, result["warnings"])


FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y"] + list(args), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise AssertionError("ffmpeg failed: %s" % result.stderr.decode("ascii", "replace")[-400:])
    return result.stdout


def streams(path):
    """what ffprobe says of a file: its duration and its streams"""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,nb_frames",
                          "-of", "json", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    return json.loads(out.decode("ascii"))


def still_at(path, seconds):
    """the frame of a video at a time, as a picture"""
    return Image.open(io.BytesIO(ffmpeg("-ss", "%.3f" % seconds, "-i", path, "-frames:v", "1", "-f", "image2pipe",
                                        "-c:v", "png", "-"))).convert("RGB")


def brightness(path, size):
    """the brightest pixel of every frame of a video"""
    data = ffmpeg("-i", path, "-f", "rawvideo", "-pix_fmt", "gray", "-")
    step = size[0] * size[1]
    return [max(data[i:i + step]) for i in range(0, len(data), step)]


@unittest.skipUnless(FFMPEG, "ffmpeg and ffprobe are not on the PATH")
class FfmpegTest(unittest.TestCase):
    def setUp(self):
        book()
        self.folder = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.folder, name)

    def cues(self, *cues):
        with open(self.path("cues.json"), "w", encoding="utf-8") as f:
            json.dump({"cues": list(cues)}, f)
        return self.path("cues.json")

    def test_two_cues_over_a_two_second_clip(self):
        clip = self.path("in.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30", "-f", "lavfi", "-i", "sine=frequency=440",
               "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip)
        cues = self.cues({"id": "fade1", "start": 0.3, "end": 1.5, "text": "HIBIKASE", "style": "logo", "anim": "fade",
                          "x": "center", "y": "middle"},
                         {"id": "rise1", "start": 0.5, "end": 1.2, "text": "\u97ff\u304b\u305b", "style": "lyric", "anim": "rise"})
        out = self.path("out/with_text.mp4")
        code, result = run(["render", clip, cues, out])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["ok"], result["ffmpeg"], result["cues"], result["frames"]), (True, 0, 2, 36 + 21))
        self.assertEqual((result["out"], result["size"], result["fps"]), (os.path.abspath(out), [320, 180], 30))
        self.assertEqual(result["work"], os.path.abspath(out) + ".work")      # the pictures stay next to the output
        self.assertEqual(sorted(os.listdir(self.path("out"))), ["with_text.mp4", "with_text.mp4.work"])
        info = streams(out)
        self.assertLessEqual(abs(float(info["format"]["duration"]) - 2.0), 0.1)
        video = [s for s in info["streams"] if s["codec_type"] == "video"]
        self.assertEqual([(s["width"], s["height"], s["codec_name"]) for s in video], [(320, 180, "h264")])
        self.assertEqual([s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"], ["aac"])   # copied
        self.assertGreater(max(high for _, high in still_at(out, 0.9).getextrema()), 200)      # the text is there
        self.assertLess(max(high for _, high in still_at(out, 1.9).getextrema()), 20)          # and gone: black again
        self.assertLess(max(high for _, high in still_at(out, 0.1).getextrema()), 20)
        # the text sits where the plan says: inside the canvas of the cue, nowhere else
        plan = mv_text.render_sequences(mv_text.load_cues(cues), self.path("again"), size=(320, 180), fps=30)
        lit = still_at(out, 0.9).convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
        boxes = [(c["x"], c["y"], c["x"] + c["canvas"][0], c["y"] + c["canvas"][1]) for c in plan["cues"]]
        union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        self.assertTrue(inside(lit, union, slack=2), (lit, union))

    def test_a_cue_starts_on_its_frame_and_lasts_its_frames(self):
        # a flash is lit on its first frame, dark on its second, lit on its third and cut off at its end: its
        # place in time shows to the frame.  Frame 123 (4.1 s) is one that a bare setpts shift puts on 122.
        clip = self.path("in.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip)
        cues = self.cues({"id": "f123", "start": 4.1, "end": 4.5, "text": "HI", "style": "hook", "anim": "flash", "x": "center",
                          "y": "middle"},
                         {"id": "f31", "start": 31 / 30.0, "end": 41 / 30.0, "text": "HI", "style": "hook", "anim": "flash",
                          "x": "left", "y": "top"})
        out = self.path("flash.mp4")
        code, result = run(["render", clip, cues, out, "--work", self.path("w")])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["work"], os.path.abspath(self.path("w")))
        levels = brightness(out, (320, 180))
        self.assertEqual(len(levels), 150)
        lit = [i for i, level in enumerate(levels) if level > 128]
        self.assertEqual(lit, [31, 33] + list(range(35, 41)) + [123, 125] + list(range(127, 135)))
        self.assertEqual([s["codec_type"] for s in streams(out)["streams"]], ["video"])        # no sound in, none out

    def test_a_failed_ffmpeg_is_exit_1_and_leaves_no_output(self):
        clip = self.path("in.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip)
        cues = self.cues({"id": "a", "start": 0.1, "end": 0.5, "text": "HI", "style": "caption"})
        old = self.path("keep.mp4")
        with open(old, "wb") as f:
            f.write(b"the old output")
        broken = self.path("not_a_video.mp4")
        with open(broken, "wb") as f:
            f.write(b"this is not a video")
        code, result = run(["render", broken, cues, old, "--size", "320x180", "--fps", "30"])
        self.assertEqual(code, 1, result)
        self.assertFalse(result["ok"])
        self.assertNotEqual(result["ffmpeg"], 0)
        self.assertEqual(result["error"]["type"], "ffmpeg")
        self.assertTrue(result["error"]["message"])
        with open(old, "rb") as f:
            self.assertEqual(f.read(), b"the old output")                     # a failure leaves the old file as it was
        self.assertEqual(sorted(n for n in os.listdir(self.folder) if "part" in n), [])
        # without --size and --fps the same file fails earlier, at the probe: exit 2
        code, result = run(["render", broken, cues, old])
        self.assertEqual(code, 2, result)


if __name__ == "__main__":
    unittest.main()
