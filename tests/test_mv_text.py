"""tools/mv_text.py: MV-style text drawn with Pillow into PNG sequences and overlaid with ffmpeg."""
import fractions
import importlib.util
import os
import tempfile
import unittest

try:
    from PIL import Image, ImageDraw
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


if __name__ == "__main__":
    unittest.main()
