"""tools/mv_look.py: the stage, the light and the glow put around the dancer MMD rendered with an alpha channel."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy  # noqa: F401
    from PIL import Image
except ImportError:                                   # the tool needs Pillow and numpy; the rest of the suite does not
    Image = None


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("mv_look", os.path.join(ROOT, "tools", "mv_look.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_look = load_tool() if Image is not None else None
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
SIZE = (320, 180)


def mean(image, box):
    """the mean (r, g, b) of a box of an image"""
    crop = image.convert("RGB").crop(box)
    pixels = list(crop.getdata())
    return tuple(sum(p[i] for p in pixels) / float(len(pixels)) for i in range(3))


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class LookSettingsTest(unittest.TestCase):
    def test_a_look_file_overrides_single_values_of_the_default(self):
        look = mv_look.merge_look({"glow": {"strength": 0.2}, "flares": [1.5, 3.0]})
        self.assertEqual(look["glow"]["strength"], 0.2)
        self.assertEqual(look["glow"]["radius"], mv_look.DEFAULT_LOOK["glow"]["radius"])
        self.assertEqual(look["flares"], [1.5, 3.0])
        self.assertEqual(look["plate"], mv_look.DEFAULT_LOOK["plate"])
        self.assertEqual(mv_look.DEFAULT_LOOK["glow"]["strength"], mv_look.merge_look({})["glow"]["strength"])
        self.assertNotEqual(mv_look.DEFAULT_LOOK["glow"]["strength"], 0.2)          # the default is not touched

    def test_a_frame_rate_a_hair_off_a_whole_number_is_that_number(self):
        # MMD writes "30 fps" as 30.00003 (ffprobe: 30000030/1000001); the layers must run at 30, not drift
        self.assertEqual(mv_look.parse_rate("30000030/1000001"), 30)
        self.assertIsInstance(mv_look.parse_rate("30000030/1000001"), int)
        self.assertEqual(mv_look.parse_rate("60/1"), 60)
        self.assertAlmostEqual(mv_look.parse_rate("30000/1001"), 29.97, places=2)   # a real 29.97 stays
        with self.assertRaises(ValueError):
            mv_look.parse_rate("0/0")

    def test_an_unknown_setting_is_an_error(self):
        for bad in ({"glov": {}}, {"glow": {"radious": 3}}, {"beams": {"count": "many"}}, {"flares": "soon"}):
            with self.assertRaises(ValueError):
                mv_look.merge_look(bad)


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class PlateTest(unittest.TestCase):
    def test_the_plate_is_dark_with_a_pool_of_light_behind_the_dancer(self):
        plate = mv_look.plate(SIZE, mv_look.DEFAULT_LOOK["plate"])
        self.assertEqual((plate.size, plate.mode), (SIZE, "RGB"))
        w, h = SIZE
        corner = mean(plate, (0, 0, 16, 16))
        centre = mean(plate, (w // 2 - 8, h // 2 - 8, w // 2 + 8, h // 2 + 8))
        self.assertLess(max(corner), 40)                                # a dark stage
        self.assertGreater(sum(centre), 2 * sum(corner))                # lighter behind the dancer
        self.assertGreater(centre[2], centre[0])                        # and blue rather than red
        self.assertEqual(plate.tobytes(), mv_look.plate(SIZE, mv_look.DEFAULT_LOOK["plate"]).tobytes())

    def test_the_colours_come_from_the_look(self):
        settings = dict(mv_look.DEFAULT_LOOK["plate"], pool=[200, 40, 40])
        plate = mv_look.plate(SIZE, settings)
        w, h = SIZE
        centre = mean(plate, (w // 2 - 8, h // 2 - 8, w // 2 + 8, h // 2 + 8))
        self.assertGreater(centre[0], centre[2])


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class LightLoopTest(unittest.TestCase):
    def frames(self, **beams):
        look = mv_look.merge_look({"beams": dict({"loop_seconds": 2}, **beams)})
        return look, mv_look.light_frame_count(look, 30)

    def test_the_loop_has_whole_seconds_of_frames_and_closes(self):
        look, count = self.frames()
        self.assertEqual(count, 60)
        first = mv_look.light_frame(SIZE, look, 0, count)
        self.assertEqual((first.size, first.mode), (SIZE, "RGB"))
        # the frame after the last is the first again, and the last is close to the first (no jump at the seam)
        self.assertEqual(first.tobytes(), mv_look.light_frame(SIZE, look, count, count).tobytes())
        last = mv_look.light_frame(SIZE, look, count - 1, count)
        half = mv_look.light_frame(SIZE, look, count // 2, count)
        self.assertLess(difference(first, last), difference(first, half))
        self.assertGreater(difference(first, half), 0.2)                # it does move

    def test_light_is_added_on_black(self):
        look, count = self.frames()
        frame = mv_look.light_frame(SIZE, look, 7, count)
        pixels = list(frame.getdata())
        self.assertLess(min(sum(p) for p in pixels), 12)                # black where no beam falls
        self.assertGreater(max(sum(p) for p in pixels), 120)            # and light where one does
        self.assertLess(sum(sum(p) for p in pixels) / (3.0 * len(pixels)), 90)     # never a white-out

    def test_no_beams_and_no_bokeh_is_black(self):
        look = mv_look.merge_look({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}})
        frame = mv_look.light_frame(SIZE, look, 3, mv_look.light_frame_count(look, 30))
        self.assertEqual(frame.getextrema(), ((0, 0), (0, 0), (0, 0)))

    def test_the_same_look_gives_the_same_frames(self):
        look, count = self.frames()
        a = mv_look.light_frame(SIZE, look, 11, count)
        b = mv_look.light_frame(SIZE, mv_look.merge_look({"beams": {"loop_seconds": 2}}), 11, count)
        self.assertEqual(a.tobytes(), b.tobytes())


def difference(a, b):
    """the mean absolute difference of two images, per channel value"""
    pa, pb = a.tobytes(), b.tobytes()
    return sum(abs(x - y) for x, y in zip(pa, pb)) / float(len(pa))


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class FlareTest(unittest.TestCase):
    """a flare is a burst of light with a streak across it, not a veil: an even white over the whole picture
    reads as grey fog (seen on the first version)"""

    def alpha(self, index):
        frame = mv_look.flare_frame(SIZE, mv_look.DEFAULT_LOOK["flare"], index)
        self.assertEqual((frame.size, frame.mode), (SIZE, "RGBA"))
        return frame.getchannel("A")

    def at(self, alpha, x, y):
        w, h = SIZE
        return alpha.getpixel((int(x * (w - 1)), int(y * (h - 1))))

    def test_the_light_is_in_the_middle_and_the_corners_stay_nearly_clear(self):
        a = self.alpha(0)
        centre, corner = self.at(a, 0.5, 0.42), self.at(a, 0.02, 0.97)
        self.assertGreater(centre, 180)
        self.assertLess(corner, 64)                                   # a quarter of full at most
        self.assertGreater(centre, 3 * corner)

    def test_a_streak_runs_across_the_picture_at_the_height_of_the_burst(self):
        a = self.alpha(0)
        on_streak, beside = self.at(a, 0.08, 0.42), self.at(a, 0.08, 0.70)
        self.assertGreater(on_streak, 2 * beside)
        self.assertGreater(on_streak, 100)

    def test_it_is_brightest_at_once_and_gone_after_its_frames(self):
        frames = int(mv_look.DEFAULT_LOOK["flare"]["frames"])
        levels = [self.at(self.alpha(i), 0.5, 0.42) for i in range(frames)]
        self.assertEqual(levels, sorted(levels, reverse=True))
        self.assertGreater(levels[0], 4 * max(1, levels[-1]))
        self.assertEqual(self.alpha(frames).getextrema(), (0, 0))


PLAN = {"fps": 30, "size": [320, 180], "warnings": [], "cues": [
    {"id": "title", "layer": "back", "x": 20, "y": 12, "start": 0.5, "start_frame": 15, "frames": 30,
     "pattern": "W/cue_title/f%05d.png", "canvas": [200, 60]},
    {"id": "credit", "layer": "front", "x": 16, "y": 140, "start": 0.2, "start_frame": 6, "frames": 20,
     "pattern": "W/cue_credit/f%05d.png", "canvas": [150, 24]},
]}


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class GraphTest(unittest.TestCase):
    def graph(self, plan=None, look=None, **kw):
        look = mv_look.merge_look(look or {})
        return mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, 30,
                                      plan=plan, flare_pattern="W/flare_%05d.png", flare_frames=12, **kw)

    def filter_of(self, argv):
        return argv[argv.index("-filter_complex") + 1]

    def test_the_inputs_are_the_dancer_the_plate_and_the_looped_light(self):
        argv = self.graph()
        self.assertEqual(argv[0], "ffmpeg")
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs, ["fg.avi", "W/plate.png", "W/light_%05d.png"])
        light = argv.index("W/light_%05d.png")
        self.assertIn("-stream_loop", argv[argv.index("W/plate.png"):light])        # the light repeats for the whole song
        self.assertEqual(argv[-1], "out.mp4")
        self.assertIn("libx264", argv)
        self.assertIn("yuv420p", argv)

    def test_the_order_is_stage_back_text_dancer_glow_front_text(self):
        f = self.filter_of(self.graph(plan=PLAN))
        stage, back, dancer, glow, front = (f.index(part) for part in (
            "[stage]", "overlay=x=20:y=12", "[fg]overlay", "blend=all_mode=screen:all_opacity=", "overlay=x=16:y=140"))
        self.assertTrue(stage < back < dancer < glow < front, (stage, back, dancer, glow, front))
        self.assertIn("setpts=PTS-STARTPTS+0.500/TB", f)                 # a cue starts when its plan says
        self.assertIn("setpts=PTS-STARTPTS+0.200/TB", f)
        self.assertEqual(f.count("eof_action=pass"), 2)                  # the picture goes on after a cue ends
        argv = self.graph(plan=PLAN)
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs[3:], ["W/cue_title/f%05d.png", "W/cue_credit/f%05d.png"])

    def test_the_glow_takes_the_bright_parts_of_the_dancer_only(self):
        f = self.filter_of(self.graph(look={"glow": {"threshold": 180, "radius": 9, "strength": 0.4}}))
        self.assertIn("(val-180)*255/(255-180)", f)
        self.assertIn("gblur=sigma=2.25", f)                               # 9 px of a 720 line picture, at 180 lines
        self.assertIn("all_opacity=0.400", f)
        self.assertNotIn("light", f[f.index("[fgk]"):f.index("gblur")])  # the glow is made from the dancer alone

    def test_no_glow_when_its_strength_is_zero(self):
        f = self.filter_of(self.graph(look={"glow": {"strength": 0}}))
        self.assertNotIn("gblur", f)

    def test_the_picture_ends_with_the_dancer(self):
        f = self.filter_of(self.graph())
        self.assertIn("shortest=1", f[f.index("[fg]overlay"):])

    def test_a_flare_at_every_hook_time(self):
        argv = self.graph(look={"flares": [1.0, 2.5]})
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs.count("W/flare_%05d.png"), 2)
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS-STARTPTS+1.000/TB", f)
        self.assertIn("setpts=PTS-STARTPTS+2.500/TB", f)

    def test_an_excerpt_shifts_the_cues_and_drops_the_ones_outside(self):
        argv = self.graph(plan=PLAN, start=0.4, duration=0.3)             # 0.4 .. 0.7 s of the song
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS-STARTPTS+0.100/TB", f)                  # the title (0.5 s) is 0.1 s into the excerpt
        self.assertIn("W/cue_credit/f%05d.png", argv)                     # the credit began before: it is cut in
        credit = argv.index("W/cue_credit/f%05d.png")
        self.assertEqual(argv[argv.index("-start_number", credit - 6) + 1], "6")      # its 7th frame is at 0.4 s
        self.assertIn("-ss", argv[:argv.index("fg.avi")])
        self.assertIn("-t", argv[:argv.index("fg.avi")])
        gone = self.graph(plan=PLAN, start=5.0, duration=1.0)
        self.assertNotIn("W/cue_title/f%05d.png", gone)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class RenderTest(unittest.TestCase):
    """the real thing on a small synthetic dancer: a white box with an alpha channel, 1.5 seconds"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.mov")
        source = ("color=c=black@0.0:s=%dx%d:r=30,format=rgba,"
                  "drawbox=x=120:y=40:w=80:h=120:color=white@1.0:t=fill:replace=1" % SIZE)   # replace: alpha too
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "1.5", "-c:v", "png", cls.fg],
                       check=True, stdin=subprocess.DEVNULL)
        cls.out = os.path.join(cls.folder, "out.mp4")
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}, "flares": [1.0]}, f)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            cls.code = mv_look.main(["render", cls.fg, look, cls.out, "--work", os.path.join(cls.folder, "work")])
        cls.text = stream.getvalue()
        # the same picture without the glow, to tell the glow from the pool of light of the plate
        cls.plain = os.path.join(cls.folder, "plain.mp4")
        plain_look = os.path.join(cls.folder, "plain.json")
        with open(plain_look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}, "glow": {"strength": 0}}, f)
        with contextlib.redirect_stdout(io.StringIO()):
            mv_look.main(["render", cls.fg, plain_look, cls.plain, "--work", os.path.join(cls.folder, "work_plain")])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frame(self, seconds, video=None):
        path = os.path.join(self.folder, "frame_%s_%s.png" % (seconds, "plain" if video else "look"))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(seconds), "-i", video or self.out, "-frames:v", "1", path],
                       check=True, stdin=subprocess.DEVNULL)
        with Image.open(path) as image:
            return image.convert("RGB")

    def test_the_summary_is_one_ascii_json_line(self):
        self.text.encode("ascii")
        result = json.loads(self.text)
        self.assertEqual(self.code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["out"], os.path.abspath(self.out))
        self.assertEqual((result["size"], result["fps"]), (list(SIZE), 30))
        self.assertEqual(result["flares"], 1)

    def test_the_output_is_as_long_and_as_large_as_the_dancer(self):
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height:format=duration", "-of", "json", self.out],
                               check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        data = json.loads(probe.stdout)
        self.assertEqual((data["streams"][0]["width"], data["streams"][0]["height"]), SIZE)
        self.assertAlmostEqual(float(data["format"]["duration"]), 1.5, delta=0.1)

    def test_the_dancer_is_kept_the_stage_is_behind_and_the_glow_spreads(self):
        frame = self.frame(0.5)
        box = mean(frame, (150, 90, 170, 110))
        self.assertGreater(min(box), 225)                                # the dancer herself, untouched
        corner = mean(frame, (0, 0, 12, 12))
        self.assertLess(max(corner), 60)                                 # the dark stage
        plain = self.frame(0.5, self.plain)
        near = (201, 90, 205, 110)                                       # just right of the box (x 200 is its edge)
        far = (290, 90, 300, 110)
        self.assertGreater(sum(mean(frame, near)), sum(mean(plain, near)) + 30)       # her glow reaches out
        self.assertLess(abs(sum(mean(frame, far)) - sum(mean(plain, far))), 12)       # and has faded 90 px away

    def test_the_flare_lights_the_whole_picture_for_a_moment(self):
        before, during = self.frame(0.8), self.frame(1.03)
        self.assertGreater(sum(mean(during, (0, 0, 40, 40))), sum(mean(before, (0, 0, 40, 40))) + 20)
        after = self.frame(1.45)
        self.assertLess(sum(mean(after, (0, 0, 40, 40))), sum(mean(during, (0, 0, 40, 40))))


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class CommandTest(unittest.TestCase):
    def run_tool(self, argv):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = mv_look.main(argv)
        text = stream.getvalue()
        text.encode("ascii")
        return code, json.loads(text)

    def test_a_missing_dancer_or_a_bad_look_exits_2_with_a_message(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            f.write("{}")
        code, result = self.run_tool(["render", os.path.join(folder, "none.avi"), look, os.path.join(folder, "o.mp4")])
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertIn("message", result["error"])
        with open(look, "w", encoding="utf-8") as f:
            f.write('{"glov": 1}')
        fg = os.path.join(folder, "fg.avi")
        open(fg, "wb").close()
        code, result = self.run_tool(["render", fg, look, os.path.join(folder, "o.mp4")])
        self.assertEqual(code, 2)
        self.assertIn("glov", result["error"]["message"])
        self.assertFalse(os.path.exists(os.path.join(folder, "o.mp4")))

    def test_layers_writes_the_plate_and_the_light_loop(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}}, f)
        code, result = self.run_tool(["layers", look, os.path.join(folder, "w"), "--size", "320x180", "--fps", "10"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["light_frames"], 10)
        self.assertTrue(os.path.exists(result["plate"]))
        names = sorted(os.listdir(os.path.dirname(result["light_pattern"])))
        self.assertEqual(len([n for n in names if n.startswith("light_")]), 10)
        with Image.open(result["plate"]) as plate:
            self.assertEqual(plate.size, SIZE)


if __name__ == "__main__":
    unittest.main()
