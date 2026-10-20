"""tools/mv_look.py: the stage, the light and the glow put around the dancer MMD rendered with an alpha channel."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

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


# the last conversion of every picture since look2 (2026-10-18), and the one before it; and the overlays of the text and the
# flares, which work in RGB since then (before, in Y'CbCr 4:2:0)
COLOUR_NOW = ("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:"
              "colorspace=bt709:range=tv[out]")
COLOUR_BEFORE = "format=yuv420p[out]"
OVERLAY_NOW, OVERLAY_BEFORE = ":eof_action=pass:format=gbrp[", ":eof_action=pass["
VIGNETTE_NOW = re.compile(r"format=rgb24,(vignette=angle=[0-9.]+),format=gbrp")


def colour_of_before(argv):
    """the argv with its colour conversions put back as they were before look2: the graph's end, the format of the overlays
    of the text and the flares and the packed RGB round the vignette, nothing else"""
    return [VIGNETTE_NOW.sub(r"\1", a.replace(COLOUR_NOW, COLOUR_BEFORE).replace(OVERLAY_NOW, OVERLAY_BEFORE))
            if a.endswith(COLOUR_NOW) else a for a in argv]


# lookfrom (2026-10-21): the camera of an excerpt runs on the song's clock, between these two
CLOCK_IN = re.compile(r"setpts=PTS\+round\(\d+/\([0-9.]+\*TB\)\),")
CLOCK_OUT = re.compile(r",setpts=PTS-round\(\d+/\([0-9.]+\*TB\)\)")


def excerpt_of_before(argv, clip_start, span):
    """the argv of an excerpt with what lookfrom (2026-10-21) changed put back as it was: -ss and -t with three decimals of a
    second (now from whole frames, to the microsecond), and the camera (the punch and the parted colours) on the excerpt's own
    clock, the time of each flare less the excerpt's start (`clip_start`, its --from) written with three decimals, in place of
    the song's clock (the times of the song, the frames' times moved by the excerpt's first frame).  `span` is the punch's
    length in seconds.  For flare times of three decimals or fewer, as the looks write them; nothing else is touched"""
    out = list(argv)
    dancer = out.index("-i")
    for flag in ("-ss", "-t"):
        if flag in out[:dancer]:
            at = out.index(flag)
            out[at + 1] = "%.3f" % float(out[at + 1])
    at = out.index("-filter_complex") + 1
    graph = CLOCK_OUT.sub("", CLOCK_IN.sub("", out[at]))

    def since(text):
        return float(text) - clip_start

    def since_term(match):
        s = since(match.group(1))
        return "(t-%.3f)" % s if s >= 0 else "(t+%.3f)" % -s
    graph = re.sub(r"\(t-([0-9.]+)\)", since_term, graph)
    graph = re.sub(r"gte\(t,([0-9.]+)\)", lambda m: "gte(t,%.3f)" % since(m.group(1)), graph)
    graph = re.sub(r"between\(t,([0-9.]+),[0-9.]+\)",
                   lambda m: "between(t,%.3f,%.3f)" % (since(m.group(1)), since(m.group(1)) + span), graph)
    out[at] = graph
    return out


def numbered_dancer(path, frames, rate, size=SIZE, box=True):
    """a dancer of `frames` frames at `rate` (frames a second; "10000000/333333" as MMD writes 30) whose frame n says n where it
    is see-through (red n % 256, green n // 256, alpha 0: the stage shows through) and, with `box`, has a white box 12 px wide
    at x = 20 + 4 n (modulo the room there is), over the middle three fifths of the height (opaque).  A .mov holds PNG (a dancer
    folded beforehand: its frames timed in ticks of 1/15360 s, finer than a frame), an .avi the uncompressed BGRA MMD writes (its
    frames timed in whole frames)"""
    folder = path + ".frames"
    os.makedirs(folder)
    w, h = size
    for n in range(frames):
        image = Image.new("RGBA", size, (n % 256, n // 256, 0, 0))
        if box:
            x = 20 + (4 * n) % max(1, w - 32)
            image.paste((255, 255, 255, 255), (x, h // 5, x + 12, h - h // 5))
        image.save(os.path.join(folder, "f%05d.png" % n))
    if path.endswith(".mov"):
        argv = ["-framerate", str(rate), "-i", os.path.join(folder, "f%05d.png"), "-c:v", "png"]
    else:
        argv = ["-framerate", "30" if "/" in str(rate) else str(rate), "-i", os.path.join(folder, "f%05d.png"), "-r", str(rate),
                "-c:v", "rawvideo", "-pix_fmt", "bgra"]
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + argv + [path], check=True, stdin=subprocess.DEVNULL)
    shutil.rmtree(folder)


def numbers_read(args):
    """the numbers the frames of a numbered_dancer say that ffmpeg reads with the input arguments `args` (mv_look.dancer_input)"""
    raw = subprocess.run(["ffmpeg", "-v", "error"] + args + ["-vf", "crop=1:1:0:0", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                         check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
    return [raw[i] + 256 * raw[i + 1] for i in range(0, len(raw) - 3, 4)]


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
        # MMD writes "30 fps" as 30.00003 (ffprobe: 10000000/333333); the layers must run at 30, not drift
        self.assertEqual(mv_look.parse_rate("10000000/333333"), 30)
        self.assertIsInstance(mv_look.parse_rate("10000000/333333"), int)
        self.assertEqual(mv_look.parse_rate("60/1"), 60)
        # MMD writes the time of a frame in whole 100 ns units: 960 fps is 10000000/10416 (ffprobe 625000/651 = 960.06), and
        # --physics-align refused it as not a whole multiple of 120 (hinata, 2026-10-16)
        for text, fps in (("625000/651", 960), ("10000000/10416", 960), ("10000000/20833", 480), ("10000000/41666", 240)):
            self.assertEqual(mv_look.parse_rate(text), fps, text)
            self.assertIsInstance(mv_look.parse_rate(text), int)
        self.assertAlmostEqual(mv_look.parse_rate("24000/1001"), 23.976, places=3)
        self.assertAlmostEqual(mv_look.parse_rate("30000/1001"), 29.97, places=2)   # a real 29.97 stays
        with self.assertRaises(ValueError):
            mv_look.parse_rate("0/0")

    def test_an_unknown_setting_is_an_error(self):
        for bad in ({"glov": {}}, {"glow": {"radious": 3}}, {"beams": {"count": "many"}}, {"flares": "soon"}):
            with self.assertRaises(ValueError):
                mv_look.merge_look(bad)

    def test_the_stage_section_takes_only_what_the_world_stage_can_draw(self):
        look = mv_look.merge_look({"stage": {"world": 1, "radius": 0, "pool": 0.5}})
        self.assertEqual((look["stage"]["world"], look["stage"]["radius"], look["stage"]["pool"]), (1, 0, 0.5))
        self.assertEqual(look["stage"]["truss"], mv_look.DEFAULT_LOOK["stage"]["truss"])
        self.assertEqual(mv_look.merge_look({})["stage"]["world"], 0)        # by default fixed to the picture, as before
        for bad in ({"world": 2}, {"floor": 0.5}, {"radius": -1}, {"specks": 0}, {"pool": 1.5}, {"shadow": -0.1},
                    {"floor_step": 0}, {"floor_accent_every": 1.5}, {"pool_colour": [1, 2]}, {"wrold": 1},
                    {"world": 1, "floor": 0, "shadow": 0.5}, {"floor_y": float("nan")}, {"floor_y": "high"},
                    {"shadow_soft": 2}, {"shadow_blur": -1}, {"shadow_blur": 45}, {"shadow_light": [0, 1, 0]},
                    {"shadow_light": [0, -1]}, {"shadow_contact": 1.5}, {"shadow_share": 2}, {"shadow_share": 0.5},
                    {"shadow_key": -0.1}, {"shadow_key": 1.5}):
            with self.assertRaises(ValueError, msg=bad):
                mv_look.merge_look({"stage": bad})
        # the floor shadow's shares of light: 1 (2026-10-17) unless the look asks for the floor of before (0)
        self.assertEqual(mv_look.merge_look({})["stage"]["shadow_share"], 1)
        self.assertEqual(mv_look.merge_look({})["stage"]["shadow_key"], 0.6)              # mv_world.KEY_SHARE
        self.assertEqual(mv_look.merge_look({"stage": {"shadow_key": 0.35}})["stage"]["shadow_key"], 0.35)
        self.assertEqual(mv_look.merge_look({"stage": {"shadow_share": 0}})["stage"]["shadow_share"], 0)
        # the floor's height: 0 (make_stage.py's floor) unless the look raises it (0.111: where the model's soles stand)
        self.assertEqual(mv_look.merge_look({})["stage"]["floor_y"], 0.0)
        self.assertEqual(mv_look.merge_look({"stage": {"floor_y": 0.111}})["stage"]["floor_y"], 0.111)


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

    def test_a_look_file_sets_part_of_the_beams_and_keeps_the_rest(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "look.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 27.4286, "cycles": [2, 3]}, "bokeh": {"cycles": [2, 3]}}, f)
        look = mv_look.load_look(path)
        self.assertEqual((look["beams"]["loop_seconds"], look["beams"]["cycles"], look["bokeh"]["cycles"]), (27.4286, [2, 3], [2, 3]))
        self.assertEqual(look["beams"]["sway"], mv_look.DEFAULT_LOOK["beams"]["sway"])
        self.assertEqual(look["bokeh"]["count"], mv_look.DEFAULT_LOOK["bokeh"]["count"])
        self.assertEqual(mv_look.light_frame_count(look, 30), 823)            # 16 bars at 140 BPM, 822.86 frames

    def test_the_default_sways_once_and_twice_per_loop(self):
        self.assertEqual(mv_look.DEFAULT_LOOK["beams"]["cycles"], [1, 2])
        self.assertEqual(mv_look.DEFAULT_LOOK["bokeh"]["cycles"], [1, 2])

    def test_every_motion_closes_the_loop_whatever_its_cycles(self):
        for cycles in ([2, 3], [3, 5]):
            look, count = self.frames(cycles=cycles)
            look["bokeh"]["cycles"] = cycles
            first = mv_look.light_frame(SIZE, look, 0, count)
            self.assertEqual(first.tobytes(), mv_look.light_frame(SIZE, look, count, count).tobytes())
            self.assertLess(difference(first, mv_look.light_frame(SIZE, look, count - 1, count)),
                            difference(first, mv_look.light_frame(SIZE, look, count // 3, count)))

    def test_the_cycles_set_how_often_the_picture_repeats_within_the_loop(self):
        # every motion twice per loop: the picture of half the loop is the first one again; with 2 and 3 it is not
        look, count = self.frames(cycles=[2, 4])
        look["bokeh"]["cycles"] = [2, 4]
        self.assertEqual(mv_look.light_frame(SIZE, look, 0, count).tobytes(), mv_look.light_frame(SIZE, look, count // 2, count).tobytes())
        look, count = self.frames(cycles=[2, 3])
        look["bokeh"]["cycles"] = [2, 3]
        self.assertGreater(difference(mv_look.light_frame(SIZE, look, 0, count), mv_look.light_frame(SIZE, look, count // 2, count)), 0.2)

    def test_the_specks_twinkle_their_own_number_of_times(self):
        # review (mutants M10, M14): the second bokeh count is the twinkle, apart from the drift and not fixed at 2
        look = mv_look.merge_look({"beams": {"count": 0, "loop_seconds": 2}})
        count = mv_look.light_frame_count(look, 30)
        frames = {}
        for cycles in ([1, 2], [1, 3], [3, 3]):
            look["bokeh"]["cycles"] = cycles
            frames[tuple(cycles)] = mv_look.light_frame(SIZE, look, 7, count)
        self.assertGreater(difference(frames[(1, 2)], frames[(1, 3)]), 0.05)     # the twinkle count alone changes it
        look["bokeh"]["cycles"] = [3, 1]
        self.assertGreater(difference(mv_look.light_frame(SIZE, look, 7, count), frames[(3, 3)]), 0.05)

    def test_cycles_are_whole_numbers_from_one(self):
        # a motion with a part of a period per loop would jump where the loop starts again
        for bad in ({"beams": {"cycles": [1.5, 2]}}, {"beams": {"cycles": [0, 2]}}, {"bokeh": {"cycles": [1, -2]}},
                    {"beams": {"cycles": [1]}}, {"bokeh": {"cycles": [True, 2]}}):
            with self.assertRaises(ValueError):
                mv_look.merge_look(bad)

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
        self.assertIn("setpts=PTS-STARTPTS+round(0.500000/TB)", f)     # a cue starts when its plan says
        self.assertIn("setpts=PTS-STARTPTS+round(0.200000/TB)", f)
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

    def test_the_picture_leaves_in_bt709_with_its_four_tags(self):
        # lookref / lookrev 2026-10-18: the graph ended in format=yuv420p, which ffmpeg turns into Y'CbCr by BT.601 and tags
        # with nothing, and a player reads an untagged HD video as BT.709 (red brighter, green darker, up to 17 of 255).
        # -colorspace and the like on the output alone left two of the four tags out (ffmpeg 8.0): setparams writes them on
        # the frames, after the conversion by BT.709 in the TV range
        for look in ({}, {"glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0}}):
            f = self.filter_of(self.graph(plan=PLAN, look=look))
            self.assertTrue(f.endswith("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:"
                                       "color_trc=bt709:colorspace=bt709:range=tv[out]"), f[-200:])
            self.assertEqual(f.count("out_color_matrix"), 1)

    def test_a_flare_at_every_hook_time(self):
        argv = self.graph(look={"flares": [1.0, 2.5]})
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs.count("W/flare_%05d.png"), 2)
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS-STARTPTS+round(1.000000/TB)", f)
        self.assertIn("setpts=PTS-STARTPTS+round(2.500000/TB)", f)

    def test_the_camera_punches_in_at_every_flare_between_the_glow_and_the_front_text(self):
        f = self.filter_of(self.graph(plan=PLAN, look={"flares": [1.0, 2.5], "camera": {"punch": 0.05, "punch_frames": 9}}))
        self.assertIn("eval=frame", f)                                    # the size follows the time
        self.assertIn("(t-1.000)", f)
        self.assertIn("(t-2.500)", f)
        self.assertIn("0.05", f)
        self.assertIn("crop=320:180", f)                                  # and the picture keeps its size
        glow, punch, front = f.index("all_opacity="), f.index("eval=frame"), f.index("overlay=x=16:y=140")
        self.assertTrue(glow < punch < front, (glow, punch, front))       # the text in front does not jump with it

    def test_the_colours_part_for_the_length_of_the_punch(self):
        f = self.filter_of(self.graph(look={"flares": [1.0], "camera": {"aberration": 8, "punch_frames": 9}}))
        self.assertIn("rgbashift=rh=-2:bh=2", f)                          # 8 px of a 720 line picture, at 180 lines
        self.assertIn("between(t,1.000,1.300)", f)

    def test_a_chunk_drops_the_head_of_the_looped_light_up_to_its_song_time(self):
        # review 10: a chunk that begins at 1.1 s shows light frame 33 mod 30 = 3 first.  Review 11: one looped input with
        # its first frames dropped (two inputs joined with concat came out a frame off when the first part was 1 or 3)
        argv = self.graph(start=1.1, light_frames=30)
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs[:3], ["fg.avi", "W/plate.png", "W/light_%05d.png"])
        self.assertEqual(inputs.count("W/light_%05d.png"), 1)
        self.assertIn("-stream_loop", argv[argv.index("W/plate.png"):argv.index("W/light_%05d.png")])
        self.assertIn("[2:v]trim=start_frame=3,setpts=PTS-STARTPTS,", self.filter_of(argv))

    def test_a_chunk_time_written_with_six_decimals_finds_its_frame_of_the_loop(self):
        # review 13: mv_chunks writes --from as %.6f, so a cut at frame 256 comes as 8.533333 s (255.99999 frames);
        # rounded it is frame 256 (16 of a 30 frame loop), cut down it would be 255 (15)
        argv = self.graph(start=8.533333, light_frames=30)
        self.assertIn("[2:v]trim=start_frame=16,", self.filter_of(argv))

    def test_a_chunk_on_a_whole_loop_reads_the_loop_from_its_start(self):
        argv = self.graph(start=2.0, light_frames=30)
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == "-i"][:3], ["fg.avi", "W/plate.png", "W/light_%05d.png"])
        self.assertNotIn("trim=", self.filter_of(argv))
        self.assertNotIn("concat=", self.filter_of(argv))

    def test_a_chunk_finds_its_frame_of_a_loop_of_16_bars(self):
        # the loop of the MV v3 is 823 frames: a chunk from the cut at frame 4983 (166.1 s) starts at 4983 - 6 * 823 = 45
        look = {"beams": {"loop_seconds": 27.428571, "cycles": [2, 3]}}
        count = mv_look.light_frame_count(mv_look.merge_look(look), 30)
        self.assertEqual(count, 823)
        argv = self.graph(look=look, start=4983 / 30.0, light_frames=count)
        self.assertIn("[2:v]trim=start_frame=45,setpts=PTS-STARTPTS,", self.filter_of(argv))

    def test_the_punch_is_cut_out_of_the_middle_of_the_scaled_picture(self):
        # review 11: crop keeps the size of the first frame for iw and ih, so (iw-W)/2 left the punch at the top left
        f = self.filter_of(self.graph(look={"flares": [1.0], "camera": {"punch": 0.05, "punch_frames": 9}}))
        scale = f[f.index("scale=w='") + len("scale=w='"):]
        width = scale[:scale.index("'")]
        self.assertIn("crop=320:180:x='(%s-320)/2'" % width, f)

    def test_a_punch_outlives_a_flare_picture_that_ended_before_the_chunk(self):
        # review 11: the flare at 1.0 s has 4 frames of picture (over at 1.133 s) and 10 of punch (until 1.333 s).  The chunk from
        # 1.2 s (frame 36 of the song) runs its camera on the song's clock (lookfrom): its frames' times are those of the song there
        look = mv_look.merge_look({"flares": [1.0], "flare": {"frames": 4},
                                   "camera": {"punch": 0.05, "punch_frames": 10, "aberration": 8}})
        argv = mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, 30,
                                      flare_pattern="W/flare_%05d.png", flare_frames=4, start=1.2, light_frames=30)
        self.assertNotIn("W/flare_%05d.png", argv)                       # no picture left to lay over
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS+round(36/(30*TB)),scale=", f)
        self.assertIn("(t-1.000)", f)
        self.assertIn("between(t,1.000,1.333)", f)

    def test_a_flare_that_began_before_the_chunk_has_its_punch_part_spent(self):
        # review 10: the flare at 1.0 s seen from a chunk that begins at 1.1 s (frame 33) began 0.1 s before the chunk: the chunk's
        # first frame is 1.1 s on the clock of its camera, and the punch is part spent there
        look = {"flares": [1.0], "camera": {"punch": 0.05, "punch_frames": 9, "aberration": 8}}
        f = self.filter_of(self.graph(look=look, start=1.1, light_frames=30))
        self.assertIn("setpts=PTS+round(33/(30*TB)),scale=", f)
        self.assertIn("(t-1.000)", f)
        self.assertIn("gte(t,1.000)", f)
        self.assertNotIn("(t-0.000)", f)
        self.assertIn("between(t,1.000,1.300)',setpts=PTS-round(33/(30*TB))[parted]", f)

    def test_the_punch_lasts_as_many_seconds_at_60_fps(self):
        # punch_frames counts frames of the song (MMD's 30 fps): a version at 60 fps punches in for as long as the one at
        # 30, over twice the frames (at 9 / 60 s it was over in half the time)
        look = mv_look.merge_look({"flares": [1.0], "camera": {"punch": 0.05, "punch_frames": 9, "aberration": 8}})
        for fps in (30, 60):
            f = self.filter_of(mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, fps,
                                                      flare_pattern="W/flare_%05d.png", flare_frames=12 * fps // 30))
            self.assertIn("pow(max(0,1-(t-1.000)/0.300),2)", f, fps)
            self.assertIn("between(t,1.000,1.300)", f, fps)

    def test_a_punch_that_began_before_a_chunk_at_60_fps_runs_on_as_at_30(self):
        # a flare 0.25 s before the chunk: its punch (9 frames of the song, 0.3 s) is still on at the chunk's start.  The chunk
        # starts on the frame nearest 1.25 s: 38 of 30 fps (the even one of 37.5, as the stage and the light take it), 75 of 60
        look = mv_look.merge_look({"flares": [1.0], "flare": {"frames": 4},
                                   "camera": {"punch": 0.05, "punch_frames": 9, "aberration": 8}})
        for fps, first in ((30, 38), (60, 75)):
            f = self.filter_of(mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, fps,
                                                      flare_pattern="W/flare_%05d.png", flare_frames=4 * fps // 30,
                                                      start=1.25, light_frames=fps))
            self.assertIn("setpts=PTS+round(%d/(%d*TB)),scale=" % (first, fps), f, fps)
            self.assertIn("pow(max(0,1-(t-1.000)/0.300),2)", f, fps)
            self.assertIn("between(t,1.000,1.300)", f, fps)

    def test_an_excerpt_runs_its_camera_on_the_song_clock(self):
        # lookfrom (2026-10-21): the expressions of the punch and of the parted colours in a chunk from frame 256 of the song
        # (8.533333 s, as mv_chunks writes it) are those of the whole song, between two setpts that move the frames' times to the
        # song's and back.  Written as times of the chunk with three decimals, the flare at 30.0 s was 21.467 s, after the frame
        # of 21.4667 s: the punch came a frame late
        look = {"flares": [30.0], "camera": {"punch": 0.05, "punch_frames": 10, "aberration": 8}}
        whole = self.filter_of(self.graph(look=look))
        chunk = self.filter_of(self.graph(look=look, start=8.533333, offset=4.533333, light_frames=30))

        def camera(f):
            return f[f.index("scale=w='"):f.index("[parted]")]
        self.assertIn("setpts=PTS+round(256/(30*TB))," + camera(whole) + ",setpts=PTS-round(256/(30*TB))[parted]", chunk)
        self.assertIn("gte(t,30.000)", camera(whole))
        self.assertNotIn("21.46", camera(chunk))
        self.assertIn("setpts=PTS-STARTPTS+round(21.466667/TB)", chunk)  # the flare's picture is laid by the chunk's own clock
        self.assertNotIn("setpts=PTS+round(", whole)                     # the whole song: as before
        # no punch, only the parted colours: the clock goes round them alone
        parted = self.filter_of(self.graph(look={"flares": [30.0], "camera": {"punch": 0, "aberration": 8}}, start=8.533333,
                                           light_frames=30))
        self.assertIn("rgbashift=rh=-2:bh=2:enable='between(t,30.000,30.333)',setpts=PTS-round(256/(30*TB))[parted]", parted)
        self.assertIn("]setpts=PTS+round(256/(30*TB)),rgbashift=", parted)

    def test_no_camera_effect_without_a_flare_or_when_it_is_zero(self):
        for look in ({}, {"flares": [1.0], "camera": {"punch": 0, "aberration": 0}}):
            f = self.filter_of(self.graph(look=look))
            self.assertNotIn("eval=frame", f)
            self.assertNotIn("rgbashift", f)

    def test_the_lens_darkens_the_corners_and_adds_grain_under_the_front_text(self):
        f = self.filter_of(self.graph(plan=PLAN, look={"lens": {"vignette": 0.4, "grain": 6}}))
        self.assertIn("vignette=", f)
        self.assertIn("noise=alls=6:allf=t", f)
        glow, lens, front = f.index("all_opacity="), f.index("vignette="), f.index("overlay=x=16:y=140")
        self.assertTrue(glow < lens < front, (glow, lens, front))         # the text in front stays clean
        plain = self.filter_of(self.graph(look={"lens": {"vignette": 0, "grain": 0}}))
        self.assertNotIn("vignette", plain)
        self.assertNotIn("noise", plain)

    def test_subframes_are_averaged_into_one_output_frame(self):
        # the dancer rendered at 4 times the output rate; a half-open shutter averages the first 2 of every 4,
        # with straight alpha turned into premultiplied for the average (a transparent pixel has colour 0)
        argv = self.graph(subframes=4, shutter=0.5)
        self.assertEqual(argv[argv.index("fg.avi") - 3:argv.index("fg.avi") - 1], ["-r", "120"])
        f = self.filter_of(argv)
        parts = ["premultiply=inplace=1", "tmix=frames=2", "select='eq(mod(n,4),1)'", "setpts=N/(30*TB)",
                 "unpremultiply=inplace=1"]
        at = [f.index(p) for p in parts]
        self.assertEqual(at, sorted(at), f)
        self.assertLess(at[-1], f.index("[fg]overlay"))
        self.assertLess(f.index("[0:v]"), at[0])
        full = self.filter_of(self.graph(subframes=4, shutter=1.0))
        self.assertIn("tmix=frames=4", full)
        self.assertIn("select='eq(mod(n,4),3)'", full)

    def test_no_subframes_no_blur(self):
        f = self.filter_of(self.graph())
        for part in ("tmix", "premultiply", "select="):
            self.assertNotIn(part, f)
        argv = self.graph()
        self.assertEqual(argv[argv.index("fg.avi") - 3:argv.index("fg.avi") - 1], ["-r", "30"])

    def test_a_shutter_must_open_and_subframes_must_be_whole(self):
        for kw in ({"subframes": 0}, {"subframes": 4, "shutter": 0.0}, {"subframes": 4, "shutter": 1.5},
                   {"subframes": 4, "shutter": 0.1}):
            with self.assertRaises(ValueError, msg=kw):
                self.graph(**kw)

    def test_an_excerpt_shifts_the_cues_and_drops_the_ones_outside(self):
        argv = self.graph(plan=PLAN, start=0.4, duration=0.3)             # 0.4 .. 0.7 s of the song
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS-STARTPTS+round(0.100000/TB)", f)      # the title (0.5 s) is 0.1 s into the excerpt
        self.assertIn("W/cue_credit/f%05d.png", argv)                     # the credit began before: it is cut in
        credit = argv.index("W/cue_credit/f%05d.png")
        self.assertEqual(argv[argv.index("-start_number", credit - 6) + 1], "6")      # its 7th frame is at 0.4 s
        self.assertIn("-ss", argv[:argv.index("fg.avi")])
        self.assertIn("-t", argv[:argv.index("fg.avi")])
        gone = self.graph(plan=PLAN, start=5.0, duration=1.0)
        self.assertNotIn("W/cue_title/f%05d.png", gone)

    def test_a_chunk_of_the_song_rendered_from_a_later_frame_keeps_the_song_clock(self):
        # the dancer's file starts at 0.3 s of the song (a chunk rendered from frame 9): the cues keep their
        # song times, and --from/--to still count in seconds of the song
        argv = self.graph(plan=PLAN, offset=0.3)
        f = self.filter_of(argv)
        self.assertIn("setpts=PTS-STARTPTS+round(0.200000/TB)", f)      # the title at 0.5 s is 0.2 s into the file
        credit = argv.index("W/cue_credit/f%05d.png")                    # the credit began at 0.2 s: 3 frames are gone
        self.assertEqual(argv[argv.index("-start_number", credit - 6) + 1], "3")
        self.assertNotIn("-ss", argv[:argv.index("fg.avi")])
        argv = self.graph(plan=PLAN, offset=0.3, start=0.4, duration=0.3)   # 0.4 .. 0.7 s of the song = 0.1 s into the file
        self.assertEqual(argv[argv.index("-ss") + 1], "0.100000")       # 3 frames into the file, to the microsecond (lookfrom)
        self.assertEqual(argv[argv.index("-t") + 1], "0.300000")
        self.assertIn("setpts=PTS-STARTPTS+round(0.100000/TB)", self.filter_of(argv))
        with self.assertRaises(ValueError):
            self.graph(plan=PLAN, offset=0.3, start=0.1, duration=0.1)       # before the file begins


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class RenderTest(unittest.TestCase):
    """the real thing on a small synthetic dancer: a white box with an alpha channel, 1.5 seconds"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        # as MMD writes it: an uncompressed BGRA AVI whose "30 fps" is 10000000/333333
        cls.fg = os.path.join(cls.folder, "fg.avi")
        source = ("color=c=black@0.0:s=%dx%d:r=30,format=rgba,"
                  "drawbox=x=120:y=40:w=80:h=120:color=white@1.0:t=fill:replace=1" % SIZE)   # replace: alpha too
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "45",
                        "-r", "10000000/333333", "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg],
                       check=True, stdin=subprocess.DEVNULL)
        cls.out = os.path.join(cls.folder, "out.mp4")
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}, "flares": [1.0], "lens": {"vignette": 0, "grain": 0}}, f)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            cls.code = mv_look.main(["render", cls.fg, look, cls.out, "--work", os.path.join(cls.folder, "work")])
        cls.text = stream.getvalue()
        # the same picture without the glow, to tell the glow from the pool of light of the plate
        cls.plain = os.path.join(cls.folder, "plain.mp4")
        plain_look = os.path.join(cls.folder, "plain.json")
        with open(plain_look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}, "glow": {"strength": 0}, "flares": [1.0],
                       "flare": {"strength": 0}, "camera": {"punch": 0.1, "aberration": 0},
                       "lens": {"vignette": 0, "grain": 0}}, f)
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
        # her glow reaches out: it adds some 30 there; x264 moves the box by 1 or 2 when other frames of the clip change
        # (review 11 measured the old margin at 5.5, and the centred punch of frames 30-36 took 1.5 of it), so 20
        self.assertGreater(sum(mean(frame, near)), sum(mean(plain, near)) + 20)
        self.assertLess(abs(sum(mean(frame, far)) - sum(mean(plain, far))), 12)       # and has faded 90 px away

    def test_no_frame_of_the_dancer_is_lost(self):
        # 45 frames in, 45 out.  MMD's frames come a hair early (30.00003 fps), and against layers at exactly 30
        # the last frame of the stage came after the dancer's last frame and was dropped (7742 of 7743 on the song)
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames", "-of", "csv=p=0", self.out],
                               check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(int(probe.stdout.strip().strip(",")), 45)

    def test_a_cue_starts_on_its_frame_and_not_one_before(self):
        # 16 / 30 s is 0.5333...: written with three decimals it falls a hair short of the 16th tick and setpts
        # cut it down to the 15th, so one cue in three came a frame early
        work = os.path.join(self.folder, "cue_work")
        cue_dir = os.path.join(work, "cue")
        os.makedirs(cue_dir)
        for i in range(10):
            Image.new("RGBA", (40, 20), (255, 255, 255, 255)).save(os.path.join(cue_dir, "f%05d.png" % i))
        look = mv_look.merge_look({"beams": {"loop_seconds": 1}, "glow": {"strength": 0}})
        layers = mv_look.write_layers(look, work, SIZE, 30)
        plan = {"cues": [{"id": "block", "layer": "front", "x": 4, "y": 4, "start": 16 / 30.0, "start_frame": 16, "frames": 10,
                          "pattern": os.path.join(cue_dir, "f%05d.png").replace("\\", "/"), "canvas": [40, 20]}], "warnings": []}
        out = os.path.join(self.folder, "cue.mp4")
        argv = mv_look.ffmpeg_command(self.fg, out, layers["plate"], layers["light_pattern"], look, SIZE, 30, plan=plan,
                                      flare_pattern=layers["flare_pattern"], flare_frames=layers["flare_frames"])
        subprocess.run(argv, check=True, stdin=subprocess.DEVNULL)

        def block(n):
            path = os.path.join(self.folder, "cue_%d.png" % n)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", "select='eq(n,%d)'" % n, "-frames:v", "1", path],
                           check=True, stdin=subprocess.DEVNULL)
            with Image.open(path) as image:
                return min(mean(image, (10, 8, 38, 20)))
        self.assertLess(block(15), 80)                                   # not yet
        self.assertGreater(block(16), 200)                               # from its own frame
        self.assertGreater(block(25), 200)                               # 10 frames long
        self.assertLess(block(26), 80)

    def test_the_lens_darkens_the_corners_but_not_the_middle(self):
        def corner_and_middle(lens):
            work = os.path.join(self.folder, "lens_%s" % lens["vignette"])
            look = mv_look.merge_look({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                                       "lens": lens})
            layers = mv_look.write_layers(look, work, SIZE, 30)
            out = os.path.join(work, "out.mp4")
            argv = mv_look.ffmpeg_command(self.fg, out, layers["plate"], layers["light_pattern"], look, SIZE, 30,
                                          flare_pattern=layers["flare_pattern"], flare_frames=layers["flare_frames"])
            subprocess.run(argv, check=True, stdin=subprocess.DEVNULL)
            path = os.path.join(work, "frame.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", out, "-frames:v", "1", path],
                           check=True, stdin=subprocess.DEVNULL)
            with Image.open(path) as image:
                return sum(mean(image, (0, 60, 24, 120))), sum(mean(image, (100, 70, 116, 110)))
        clear_edge, clear_middle = corner_and_middle({"vignette": 0, "grain": 0})
        dark_edge, dark_middle = corner_and_middle({"vignette": 0.6, "grain": 0})
        edge, middle = dark_edge / clear_edge, dark_middle / clear_middle
        self.assertLess(edge, 0.6, (edge, middle))                       # the left edge, where the plate has light
        self.assertGreater(middle, 0.8, (edge, middle))                  # beside the dancer much less changes
        self.assertLess(edge, middle - 0.25, (edge, middle))

    def test_the_camera_punches_in_and_comes_back(self):
        # the plain picture has a punch of a tenth at 1.0 s and a flare without light: the box (80 px wide) is
        # some 6 px wider a frame later and back to its size before the next third of a second is over
        def width(seconds):
            frame = self.frame(seconds, self.plain)
            return sum(1 for x in range(SIZE[0]) if min(frame.getpixel((x, 100))) > 200)
        self.assertAlmostEqual(width(0.8), 80, delta=2)
        self.assertGreaterEqual(width(1.04), 84)
        self.assertAlmostEqual(width(1.45), 80, delta=2)

    def test_the_flare_lights_the_whole_picture_for_a_moment(self):
        before, during = self.frame(0.8), self.frame(1.03)
        self.assertGreater(sum(mean(during, (0, 0, 40, 40))), sum(mean(before, (0, 0, 40, 40))) + 20)
        after = self.frame(1.45)
        self.assertLess(sum(mean(after, (0, 0, 40, 40))), sum(mean(during, (0, 0, 40, 40))))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class ColourRenderTest(unittest.TestCase):
    """look2 (2026-10-18): the colours the graph makes are the colours a player shows.  A dancer of eight flat patches over
    the whole picture (the colours lookrev read wrong: the red, the green and the orange of the tie, a pink skin, a dark
    navy), nothing else on the picture: the video says BT.709 with all four of its tags, and read as BT.709 (what a player
    does with them, and with an untagged HD video) every patch comes back within a few of 255"""

    PATCHES = [(200, 60, 40), (40, 160, 70), (50, 80, 200), (230, 200, 60), (128, 128, 128), (250, 180, 160),
               (240, 160, 40), (20, 30, 60)]

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.avi")
        w = SIZE[0] // len(cls.PATCHES)
        boxes = ",".join("drawbox=x=%d:y=0:w=%d:h=%d:color=0x%02X%02X%02X@1.0:t=fill:replace=1" % ((i * w, w, SIZE[1]) + c)
                         for i, c in enumerate(cls.PATCHES))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black@0.0:s=%dx%d:r=30,format=rgba,%s" % (SIZE + (boxes,)), "-frames:v", "15",
                        "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                       "lens": {"vignette": 0, "grain": 0}, "flares": []}, f)
        cls.out = os.path.join(cls.folder, "out.mp4")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = mv_look.main(["render", cls.fg, look, cls.out, "--work", os.path.join(cls.folder, "work")])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def read(self, matrix=None):
        """the middle of every patch of frame 7, read as `matrix` says (None: as the video's tags say)"""
        vf = ("scale=in_color_matrix=%s:in_range=tv:out_range=pc,format=rgb24" % matrix) if matrix else "format=rgb24"
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", self.out, "-vf", "select=eq(n\\,7)," + vf, "-frames:v", "1",
                              "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        image = numpy.frombuffer(raw[:SIZE[0] * SIZE[1] * 3], dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3)
        w = SIZE[0] // len(self.PATCHES)
        return [tuple(int(v) for v in image[SIZE[1] // 2, i * w + w // 2]) for i in range(len(self.PATCHES))]

    def test_the_video_carries_all_four_tags_of_bt709(self):
        self.assertEqual(self.code, 0)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=color_space,color_primaries,color_transfer,color_range", "-of", "json", self.out],
                               check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        tags = json.loads(probe.stdout)["streams"][0]
        self.assertEqual(tags, {"color_space": "bt709", "color_primaries": "bt709", "color_transfer": "bt709",
                                "color_range": "tv"})

    def test_read_as_bt709_the_colours_come_back(self):
        for matrix in ("bt709", None):
            got = self.read(matrix)
            worst = max(abs(g - c) for patch, made in zip(got, self.PATCHES) for g, c in zip(patch, made))
            self.assertLessEqual(worst, 3, (matrix, got))

    def test_read_as_bt601_they_would_not(self):
        # the test tells the two apart: the conversion of before (BT.601) read as BT.709 moved the red by 12 and the green
        # by 17 (lookrev's patches); this one read as BT.601 moves them as far the other way
        got = self.read("bt601")
        worst = max(abs(g - c) for patch, made in zip(got, self.PATCHES) for g, c in zip(patch, made))
        self.assertGreaterEqual(worst, 8, got)

    def test_the_picture_stays_rgb_under_a_flare_and_the_text(self):
        # an overlay of ffmpeg works in Y'CbCr 4:2:0 unless told otherwise: under a flare or a cue the picture was turned
        # into Y'CbCr by BT.601 half way and then into BT.709 at the end (the excerpt test saw it: the same frame with and
        # without a flare laid over it came out 1.2 of 255 apart before x264).  A flare without light and a clear cue over
        # the patches leave every pixel as it is
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cue = os.path.join(folder, "cue")
        os.makedirs(cue)
        for i in range(15):
            Image.new("RGBA", (64, 32), (255, 255, 255, 0)).save(os.path.join(cue, "f%05d.png" % i))
        plan = {"cues": [{"start": 0.0, "frames": 15, "x": 8, "y": 8, "layer": layer, "pattern": os.path.join(cue, "f%05d.png")}
                         for layer in ("back", "front")]}
        # the lens too: ffmpeg's vignette takes no planar RGB, and was handed the picture in Y'CbCr 4:4:4 by BT.601
        for lens in ({"vignette": 0, "grain": 0}, {"vignette": 0.3, "grain": 3}):
            frames = {}
            for name, look in (("bare", {}), ("laid", {"flares": [0.0], "flare": {"strength": 0},
                                                        "camera": {"punch": 0, "aberration": 0}})):
                look = mv_look.merge_look(dict({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0},
                                                "glow": {"strength": 0}, "lens": lens, "flares": []}, **look))
                layers = mv_look.write_layers(look, os.path.join(folder, "work_" + name), SIZE, 30)
                out = os.path.join(folder, name + ".nut")
                argv = mv_look.ffmpeg_command(self.fg, out, layers["plate"], layers["light_pattern"], look, SIZE, 30,
                                              plan=plan if name == "laid" else None, flare_pattern=layers["flare_pattern"],
                                              flare_frames=layers["flare_frames"], light_frames=layers["light_frames"])
                argv = argv[:argv.index("-c:v")] + ["-c:v", "rawvideo", "-pix_fmt", "yuv420p", out]     # nothing lost after it
                subprocess.run(argv, check=True, capture_output=True, stdin=subprocess.DEVNULL)
                frames[name] = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                                              check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
            self.assertEqual(len(frames["laid"]), len(frames["bare"]), lens)
            bare = numpy.frombuffer(frames["bare"], dtype=numpy.uint8).astype(numpy.int16)
            laid = numpy.frombuffer(frames["laid"], dtype=numpy.uint8).astype(numpy.int16)
            self.assertEqual(int(numpy.abs(laid - bare).max()), 0, (lens, float(numpy.abs(laid - bare).mean())))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class RimLightRenderTest(unittest.TestCase):
    """look2 (2026-10-18): a light from behind her (look rim) lights the inner band of her edges that face where it comes from,
    and nothing else.  A grey box (her) on a black stage, no glow, no lens: a cool light from above"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.avi")
        source = ("color=c=black@0.0:s=%dx%d:r=30,format=rgba,"
                  "drawbox=x=100:y=40:w=120:h=100:color=0x808080@1.0:t=fill:replace=1" % SIZE)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "10", "-c:v", "rawvideo",
                        "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        cls.frames = {}
        for name, rim in (("bare", {}), ("lit", {"rim": {"strength": 1.0, "colour": [0, 0, 255], "width": 12.0,
                                                          "from": [0.0, -1.0]}})):
            look = os.path.join(cls.folder, name + ".json")
            with open(look, "w", encoding="utf-8") as f:
                json.dump(dict({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                                "plate": {"base": [0, 0, 0], "haze": [0, 0, 0], "pool": [0, 0, 0]},
                                "lens": {"vignette": 0, "grain": 0}}, **rim), f)
            out = os.path.join(cls.folder, name + ".mp4")
            with contextlib.redirect_stdout(io.StringIO()):
                assert mv_look.main(["render", cls.fg, look, out, "--work", os.path.join(cls.folder, "w_" + name)]) == 0
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vf", "select=eq(n\\,5),format=rgb24", "-frames:v", "1",
                                  "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
            cls.frames[name] = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3).astype(numpy.int16)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def blue(self, rows, cols):
        lit, bare = self.frames["lit"], self.frames["bare"]
        return float((lit[rows, cols, 2] - bare[rows, cols, 2]).mean())

    def test_the_edge_facing_the_light_is_lit_and_the_rest_is_not(self):
        top = self.blue(slice(40, 43), slice(130, 190))              # the band just inside her top edge (12 px of 720: 3 here)
        bottom = self.blue(slice(134, 138), slice(130, 190))         # her bottom edge faces away from the light
        middle = self.blue(slice(80, 100), slice(130, 190))
        outside = self.blue(slice(10, 30), slice(130, 190))
        self.assertGreater(top, 40.0, (top, bottom, middle, outside))
        self.assertLess(abs(bottom), 4.0)
        self.assertLess(abs(middle), 4.0)
        self.assertLess(abs(outside), 4.0)

    def test_no_rim_unless_asked(self):
        argv = mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", mv_look.merge_look({}), SIZE, 30)
        self.assertNotIn("alphamerge", argv[argv.index("-filter_complex") + 1])
        for bad in ({"strength": -0.1}, {"width": -1}, {"from": [0, 0]}):
            with self.assertRaises(ValueError, msg=bad):
                mv_look.merge_look({"rim": bad})


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class NightLightLookTest(unittest.TestCase):
    """light3 (2026-10-21, @PizaCG's lighting): the look's light section.  light.person is the night's light on her, drawn by
    MMD through MME (tools/mme_shadow.py prepare --look takes it; this tool only checks it); light.grade grades the picture
    under the front text; light.flicker makes the street's lit signs flicker (tools/stage_layer.py).  Unwritten, nothing
    changes"""

    NIGHT = {"on": 1, "key": [1.0, 0.7, 0.45], "fill": [0.2, 0.22, 0.34], "rim": [0.5, 0.7, 1.0], "rim_from": [-0.7, -0.7],
             "sections": [[0, 1.0, 0.7, 0.45, 0.2, 0.22, 0.34, 0.5, 0.7, 1.0], [44.467, 0.8, 0.5, 1.0, 0.2, 0.15, 0.2, 1, 0.6, 0.3]]}
    GRADE = {"shadows": [-0.02, -0.03, 0.06], "mids": [-0.04, -0.05, 0.07], "highs": [0.0, 0.0, 0.0], "saturation": 1.15}

    def argv(self, look):
        return mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", mv_look.merge_look(look), SIZE, 30)

    def test_unwritten_the_light_changes_nothing(self):
        look = mv_look.merge_look({})
        self.assertEqual(look["light"], mv_look.DEFAULT_LOOK["light"])
        self.assertEqual(look["light"]["person"]["on"], 0)
        self.assertEqual(self.argv({}), self.argv({"light": {}}))
        self.assertNotIn("curves=", self.argv({})[self.argv({}).index("-filter_complex") + 1])

    def test_the_light_on_her_is_mmds_and_checked_by_mme_shadow(self):
        look = mv_look.merge_look({"light": {"person": self.NIGHT}})
        self.assertEqual(look["light"]["person"]["fill"], [0.2, 0.22, 0.34])
        self.assertEqual(look["light"]["person"]["face"], 0.75)                  # the rest from tools/mme_shadow.py
        # her light is drawn by MMD: the graph is the one without it
        self.assertEqual(self.argv({"light": {"person": self.NIGHT}}), self.argv({}))
        for bad in ({"fill": [0, 0, 9]}, {"sections": [[3, 1, 1, 1, 0, 0, 0, 0, 0, 0], [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]]},
                    {"rim_from": [0, 0]}, {"warmth": 1}):
            with self.assertRaises(ValueError, msg=bad):
                mv_look.merge_look({"light": {"person": dict(self.NIGHT, **bad)}})

    def test_the_grade_comes_after_her_glow_and_before_the_lens_and_the_front_text(self):
        argv = self.argv({"light": {"grade": self.GRADE}})
        graph = argv[argv.index("-filter_complex") + 1]
        # a curve a channel through 0, the quarter, the half and the three quarters moved by the shifts, and 1
        self.assertIn("curves=r='0/0 0.25/0.23 0.5/0.46 0.75/0.75 1/1':g='0/0 0.25/0.22 0.5/0.45 0.75/0.75 1/1':"
                      "b='0/0 0.25/0.31 0.5/0.57 0.75/0.75 1/1'", graph)
        self.assertLess(graph.index("[comp][glow]blend=all_mode=screen"), graph.index("curves="))
        self.assertLess(graph.index("curves="), graph.index("vignette="))
        # saturation: a matrix on RGB about the luma (BT.709), the picture kept RGB
        m = re.search(r"colorchannelmixer=rr=([-0-9.]+):rg=([-0-9.]+):rb=([-0-9.]+):gr=([-0-9.]+):gg=([-0-9.]+):gb=([-0-9.]+):"
                      r"br=([-0-9.]+):bg=([-0-9.]+):bb=([-0-9.]+)", graph)
        rows = [[float(m.group(1 + 3 * r + c)) for c in range(3)] for r in range(3)]
        for r in rows:
            self.assertAlmostEqual(sum(r), 1.0, places=3)                    # a grey stays grey
        self.assertAlmostEqual(rows[0][0], 0.2126 + 1.15 * (1 - 0.2126), places=3)
        self.assertNotIn("format=yuv", graph[:graph.index("curves=")])
        for bad in ({"mids": [0, 0, 0.5]}, {"saturation": -1}, {"highs": [0, 0]}, {"lift": [0, 0, 0]},
                    {"shadows": [0.2, 0, 0], "mids": [-0.2, 0, 0]}):
            with self.assertRaises(ValueError, msg=bad):
                mv_look.merge_look({"light": {"grade": bad}})

    def test_her_shadow_on_the_floor_falls_from_her_key_light(self):
        # her key light is MMD's light (tools/mme_shadow.py light-vmd), her shadow on the floor falls from stage.shadow_light
        world = {"world": 1, "floor": 1, "shadow": 1.0}
        night = dict(self.NIGHT, direction=[-0.75, -0.55, 0.35])
        with self.assertRaises(ValueError):
            mv_look.merge_look({"stage": world, "light": {"person": night}})
        look = mv_look.merge_look({"stage": dict(world, shadow_light=[-0.75, -0.55, 0.35]), "light": {"person": night}})
        self.assertEqual(look["stage"]["shadow_light"], [-0.75, -0.55, 0.35])
        # MMD's default light on both sides: nothing to say
        mv_look.merge_look({"stage": world, "light": {"person": self.NIGHT}})

    def test_the_flicker_is_a_share_of_the_signs_light(self):
        for bad in ({"flicker": -0.1}, {"flicker": 1.5}, {"flicker_seed": 1.5}, {"glitter": 1}):
            with self.assertRaises(ValueError, msg=bad):
                mv_look.merge_look({"light": bad})
        # it flickers the signs of the stage of a model (tools/stage_layer.py): without one it would do nothing, so it is refused
        with self.assertRaises(ValueError):
            mv_look.merge_look({"light": {"flicker": 0.08}, "layer": {"on": 0}})
        look = mv_look.merge_look({"light": {"flicker": 0.08}, "stage": {"world": 1}, "layer": {"on": 1}})
        self.assertEqual(look["light"]["flicker"], 0.08)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class GradeRenderTest(unittest.TestCase):
    """light3: the grade rendered for real on a grey box (her) over a black stage: the middle tones lean as the look says, the
    picture stays RGB to the end (no detour through Y'CbCr: a grey stays grey), and a grade of nothing is no grade"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.avi")
        source = ("color=c=black@0.0:s=%dx%d:r=30,format=rgba,"
                  "drawbox=x=100:y=40:w=120:h=100:color=0x808080@1.0:t=fill:replace=1" % SIZE)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "6", "-c:v", "rawvideo",
                        "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        cls.frames = {}
        base = {"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                "plate": {"base": [0, 0, 0], "haze": [0, 0, 0], "pool": [0, 0, 0]}, "lens": {"vignette": 0, "grain": 0}}
        for name, light in (("bare", {}), ("none", {"light": {"grade": {"saturation": 1.0}}}),
                            ("blue", {"light": {"grade": {"mids": [-0.06, -0.04, 0.1]}}}),
                            ("grey", {"light": {"grade": {"saturation": 1.6}}})):
            look = os.path.join(cls.folder, name + ".json")
            with open(look, "w", encoding="utf-8") as f:
                json.dump(dict(base, **light), f)
            out = os.path.join(cls.folder, name + ".mp4")
            with contextlib.redirect_stdout(io.StringIO()):
                assert mv_look.main(["render", cls.fg, look, out, "--work", os.path.join(cls.folder, "w_" + name)]) == 0
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vf",
                                  "select=eq(n\\,3),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-frames:v", "1",
                                  "-f", "rawvideo", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
            cls.frames[name] = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3).astype(numpy.int16)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def box(self, name):
        return self.frames[name][60:120, 120:200].reshape(-1, 3).mean(axis=0)

    def test_a_grade_of_nothing_is_no_grade(self):
        self.assertTrue(numpy.array_equal(self.frames["none"], self.frames["bare"]))

    def test_the_middle_tones_lean_blue(self):
        bare, blue = self.box("bare"), self.box("blue")
        self.assertGreater(blue[2] - bare[2], 6.0, (bare, blue))
        self.assertLess(blue[0] - bare[0], -3.0, (bare, blue))

    def test_saturation_leaves_a_grey_grey(self):
        bare, grey = self.box("bare"), self.box("grey")
        self.assertLess(numpy.abs(grey - bare).max(), 1.5, (bare, grey))
        self.assertLess(numpy.ptp(grey), 1.5)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class ChunkLightRenderTest(unittest.TestCase):
    """review 10: rendered for real, a chunk of the song shows the light loop as the whole song shows it at that time
    (a loop of 10 frames whose frame i is a flat grey of 20 * i, nobody on the stage, a black plate)"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        light = os.path.join(cls.folder, "light")
        os.makedirs(light)
        for i in range(10):
            Image.new("RGB", SIZE, (20 * i,) * 3).save(os.path.join(light, "light_%05d.png" % i))
        cls.pattern = os.path.join(light, "light_%05d.png").replace("\\", "/")
        cls.plate = os.path.join(cls.folder, "plate.png")
        Image.new("RGB", SIZE, (0, 0, 0)).save(cls.plate)
        cls.fg = os.path.join(cls.folder, "fg.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=%dx%d:r=30,format=rgba" % SIZE,
                        "-frames:v", "60", "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        cls.look = mv_look.merge_look({"glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0},
                                       "camera": {"punch": 0, "aberration": 0}, "flares": []})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def greys(self, start, frames):
        out = os.path.join(self.folder, "out_%s.mp4" % start)
        argv = mv_look.ffmpeg_command(self.fg, out, self.plate, self.pattern, self.look, SIZE, 30, start=start,
                                      duration=frames / 30.0, offset=0.0, light_frames=10)
        subprocess.run(argv, check=True, capture_output=True, stdin=subprocess.DEVNULL)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1]
        return [sum(raw[i * n:(i + 1) * n]) / float(n) for i in range(len(raw) // n)]

    def test_the_whole_song_starts_the_loop_at_its_first_frame(self):
        greys = self.greys(None, 12)
        self.assertEqual(len(greys), 12)
        for j, g in enumerate(greys):
            self.assertAlmostEqual(g, 20 * (j % 10), delta=8, msg=(j, [round(x) for x in greys]))

    def test_a_chunk_goes_on_with_the_loop_from_its_song_time_at_every_phase(self):
        # review 11: joining two inputs put the light a frame off when the loop's first part was 1 or 3 frames long
        for first in range(10, 20):
            greys = self.greys(first / 30.0, 12)
            self.assertEqual(len(greys), 12, first)
            for j, g in enumerate(greys):
                self.assertAlmostEqual(g, 20 * ((first + j) % 10), delta=8, msg=(first, j, [round(x) for x in greys]))


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class StaleLayersTest(unittest.TestCase):
    def test_a_shorter_loop_or_flare_leaves_none_of_the_earlier_frames(self):
        # review 11: ffmpeg reads a numbered sequence until a number is missing, so frames of an earlier, longer look in
        # the same work folder came back into the loop and the flare
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        for seconds, flare in ((2, 12), (1, 4)):
            look = mv_look.merge_look({"beams": {"loop_seconds": seconds}, "flare": {"frames": flare}})
            layers = mv_look.write_layers(look, work, SIZE, 30)
        self.assertEqual(layers["light_frames"], 30)
        self.assertEqual(len([n for n in os.listdir(os.path.join(work, "light")) if n.startswith("light_")]), 30)
        self.assertEqual(len([n for n in os.listdir(os.path.join(work, "flare")) if n.startswith("flare_")]), 4)


def file_bytes(path):
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class SongClockTest(unittest.TestCase):
    """A version at 60 fps shows what the one at 30 fps shows at the same time (tools/mv_chunks.py --out-fps 60): the frame
    counts of the look (flare.frames, camera.punch_frames) and the light loop are frames of the song (1/30 s), so frame 2n
    at 60 fps is frame n at 30"""

    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_the_flare_and_the_light_of_60_fps_are_those_of_30_fps_twice_as_often(self):
        look = mv_look.merge_look({"beams": {"loop_seconds": 2, "cycles": [2, 3]}, "bokeh": {"cycles": [2, 3]},
                                   "flare": {"frames": 5}})
        a = mv_look.write_layers(look, os.path.join(self.work, "30"), SIZE, 30)
        b = mv_look.write_layers(look, os.path.join(self.work, "60"), SIZE, 60)
        self.assertEqual((a["light_frames"], a["flare_frames"]), (60, 5))
        self.assertEqual((b["light_frames"], b["flare_frames"]), (120, 10))
        for n in range(5):
            self.assertEqual(file_bytes(b["flare_pattern"] % (2 * n)), file_bytes(a["flare_pattern"] % n), n)
        for n in (0, 1, 7, 31, 59):
            self.assertEqual(file_bytes(b["light_pattern"] % (2 * n)), file_bytes(a["light_pattern"] % n), n)
        # and the frames between are frames of their own: the flare fades on, the light moves on
        self.assertNotEqual(file_bytes(b["flare_pattern"] % 1), file_bytes(b["flare_pattern"] % 0))
        self.assertNotEqual(file_bytes(b["light_pattern"] % 15), file_bytes(b["light_pattern"] % 14))
        self.assertEqual(sorted(os.listdir(os.path.dirname(b["flare_pattern"]))), ["flare_%05d.png" % i for i in range(10)])

    def test_a_loop_of_no_whole_number_of_frames_at_60_has_twice_the_frames_of_30(self):
        # 0.35 s is 10.5 frames of the song (10, to the even) and 21 at 60 fps: the light of 60 would drift from the light
        # of 30 by a frame of 60 every loop.  It is the loop of the song at every rate that is a whole number of times 30
        look = mv_look.merge_look({"beams": {"loop_seconds": 0.35}})
        self.assertEqual([mv_look.light_frame_count(look, fps) for fps in (30, 60, 120)], [10, 20, 40])
        self.assertEqual(mv_look.light_frame_count(look, 25), 9)                    # another clock: its own nearest frame
        v3 = mv_look.merge_look({"beams": {"loop_seconds": 27.428571}})
        self.assertEqual([mv_look.light_frame_count(v3, fps) for fps in (30, 60)], [823, 1646])

    def test_the_flare_of_the_default_look_lasts_twelve_frames_of_the_song(self):
        for fps, frames in ((30, 12), (60, 24)):
            layers = mv_look.write_layers(mv_look.merge_look({"beams": {"loop_seconds": 1}}), os.path.join(self.work, str(fps)),
                                          SIZE, fps)
            self.assertEqual(layers["flare_frames"], frames, fps)


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class ThirtyArgvTest(unittest.TestCase):
    """The video to publish is folded at 30 fps: the ffmpeg argv of mv_look at 30 stays the one main 60956b2 built, byte for
    byte (the SHA-256 of the argv joined by NUL, written with the tool of 60956b2).  A chunk like v7_04 of the MV (the
    flare of the look v3 on its first frame, two cues), one into which a punch runs on, and the default look unblurred"""

    V3 = {"flares": [44.467, 86.933, 155.533, 225.8, 241.233], "flare": {"strength": 0.75},
          "beams": {"loop_seconds": 27.428571, "cycles": [2, 3]}, "bokeh": {"cycles": [2, 3]}}
    PLAN = {"cues": [{"start": 42.7, "frames": 105, "x": 120, "y": 560, "layer": "front", "pattern": "W/text/cue_l/f%05d.png"},
                     {"start": 86.933333, "frames": 27, "x": 240, "y": 280, "layer": "back", "pattern": "W/text/cue_h/f%05d.png"}]}
    GOLDEN = {"v7_04_flare_on_the_cut": "7ff22ffc633cebad18cba8523d5ea55a431cf450ab317d66b0291ff4cf18d411",
              "punch_carried_into_a_chunk": "3c3b826f7c6d28ab2e652afa6fd28687f7cc237ff48751ce31aac86d2f21a2ba",
              "default_look_no_blur": "b3483e659532ad12cee21f3ab7101aff4fabed12187656ba181cdd5dae33fba8"}

    def argvs(self):
        """(name, the excerpt's --from or None, argv)"""
        look = mv_look.merge_look(self.V3)
        common = dict(flare_pattern="W/flare/flare_%05d.png", flare_frames=12, subframes=8, shutter=0.5, light_frames=823)
        yield "v7_04_flare_on_the_cut", 1334 / 30.0, mv_look.ffmpeg_command(
            "C:/out/v7_04.avi", "C:/out/v7_04.mp4", "W/plate.png", "W/light/light_%05d.png", look, (1280, 720), 30, plan=self.PLAN,
            start=1334 / 30.0, duration=406 / 30.0, offset=1214 / 30.0, **common)
        yield "punch_carried_into_a_chunk", 2610 / 30.0, mv_look.ffmpeg_command(
            "C:/out/x.avi", "C:/out/x.mp4", "W/plate.png", "W/light/light_%05d.png", look, (1280, 720), 30, plan=self.PLAN,
            start=2610 / 30.0, duration=40 / 30.0, offset=2490 / 30.0, **common)
        yield "default_look_no_blur", None, mv_look.ffmpeg_command(
            "C:/out/y.avi", "C:/out/y.mp4", "W/plate.png", "W/light/light_%05d.png", mv_look.merge_look({}), (1280, 720), 30)

    def test_the_argv_at_30_fps_is_the_one_of_before(self):
        # but for its last colour conversion (BT.709 and its tags, look2 2026-10-18) and, in a chunk, the seconds of its excerpt
        # and the clock of its camera (lookfrom 2026-10-21): with those put back as they were, every byte of the argv is the one of
        # main 60956b2
        for name, start, argv in self.argvs():
            if start is not None:
                argv = excerpt_of_before(argv, start, 10 / 30.0)
            self.assertEqual(hashlib.sha256("\0".join(colour_of_before(argv)).encode("utf-8")).hexdigest(), self.GOLDEN[name],
                             name)

    def test_a_chunk_reads_whole_frames_and_punches_on_the_song_clock(self):
        # what lookfrom changed in the chunk v7_04 (the flare at 44.467 s, 0.000333 s after its cut at frame 1334)
        argv = dict((name, argv) for name, _, argv in self.argvs())["v7_04_flare_on_the_cut"]
        at = argv.index("C:/out/v7_04.avi")
        self.assertEqual(argv[at - 7:at + 1], ["-ss", "4.000000", "-t", "13.533333", "-r", "240", "-i", "C:/out/v7_04.avi"])
        f = argv[argv.index("-filter_complex") + 1]
        self.assertIn("[lit]setpts=PTS+round(1334/(30*TB)),scale=w='trunc(1280*(1+0.04*pow(max(0,1-(t-44.467)/0.333),2)*"
                      "gte(t,44.467))/2)*2'", f)
        self.assertIn("rgbashift=rh=-3:bh=3:enable='between(t,44.467,44.800)',setpts=PTS-round(1334/(30*TB))[parted]", f)

    def test_the_counts_of_the_layers_at_30_fps_are_those_of_before(self):
        # what write_layers hands the argv at 30 (12 flare frames, the loop of v3 in 823): the values of main 60956b2
        self.assertEqual(mv_look.light_frame_count(mv_look.merge_look(self.V3), 30), 823)
        self.assertEqual(mv_look.song_frames(12, 30), 12)
        self.assertEqual(mv_look.song_frames(12.7, 30), 12)                         # main took int() of it too


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class SixtyRenderTest(unittest.TestCase):
    """The same dancer folded to 30 fps and to 60 fps (a white box rendered at 120 fps for 1.2 s, a flare at 0.5 s with a
    punch of a tenth): there are twice the frames, and frame 2n at 60 fps shows what frame n at 30 shows"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg120.avi")
        source = ("color=c=black@0.0:s=%dx%d:r=120,format=rgba,"
                  "drawbox=x=120:y=40:w=80:h=120:color=white@1.0:t=fill:replace=1" % SIZE)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "144",
                        "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                       "lens": {"vignette": 0, "grain": 0}, "flares": [0.5],
                       "camera": {"punch": 0.1, "punch_frames": 10, "aberration": 0}}, f)
        cls.results = {}
        for fps, subframes in ((30, 4), (60, 2)):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = mv_look.main(["render", cls.fg, look, os.path.join(cls.folder, "out%d.mp4" % fps),
                                     "--work", os.path.join(cls.folder, "work%d" % fps), "--subframes", str(subframes)])
            cls.results[fps] = (code, json.loads(stream.getvalue()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, fps):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, "out%d.mp4" % fps), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).astype(numpy.int16) for i in range(len(raw) // n)]

    def test_the_version_at_60_fps_has_twice_the_frames(self):
        self.assertEqual([self.results[fps][0] for fps in (30, 60)], [0, 0], self.results)
        self.assertEqual([self.results[fps][1]["fps"] for fps in (30, 60)], [30, 60])
        self.assertEqual([len(self.frames(fps)) for fps in (30, 60)], [36, 72])

    def test_frame_2n_at_60_fps_is_frame_n_at_30(self):
        thirty, sixty = self.frames(30), self.frames(60)
        gaps = [float(numpy.abs(sixty[2 * n] - thirty[n]).mean()) for n in range(36)]
        self.assertLess(max(gaps), 2.0, [round(g, 2) for g in gaps])
        # and the test can see a difference: during the flare and the punch one frame of 30 fps differs from the next
        moving = max(float(numpy.abs(thirty[n + 1] - thirty[n]).mean()) for n in range(15, 26))
        self.assertGreater(moving, 3 * max(gaps) + 0.5)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class PunchCentreRenderTest(unittest.TestCase):
    """review 11: a white line 60 px above the middle of a 180 line picture, punched in by 0.3 at 1.0 s: zoomed about the
    middle it goes up to 90 - 60 * 1.3 = 12 at the flare; zoomed about the top left it went down to 30 * 1.3 = 39"""

    def test_the_punch_zooms_about_the_middle_of_the_picture(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        plate = os.path.join(folder, "plate.png")
        image = Image.new("RGB", SIZE, (0, 0, 0))
        image.paste((255, 255, 255), (0, 29, SIZE[0], 31))
        image.save(plate)
        light = os.path.join(folder, "light")
        os.makedirs(light)
        Image.new("RGB", SIZE, (0, 0, 0)).save(os.path.join(light, "light_00000.png"))
        flare = os.path.join(folder, "flare")
        os.makedirs(flare)
        Image.new("RGBA", SIZE, (0, 0, 0, 0)).save(os.path.join(flare, "flare_00000.png"))   # a flare frame is see-through
        fg = os.path.join(folder, "fg.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=%dx%d:r=30,format=rgba" % SIZE,
                        "-frames:v", "45", "-c:v", "rawvideo", "-pix_fmt", "bgra", fg], check=True, stdin=subprocess.DEVNULL)
        look = mv_look.merge_look({"flares": [1.0], "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0},
                                   "flare": {"frames": 1, "strength": 0}, "camera": {"punch": 0.3, "punch_frames": 10, "aberration": 0}})
        out = os.path.join(folder, "out.mp4")
        argv = mv_look.ffmpeg_command(fg, out, plate, os.path.join(light, "light_%05d.png").replace("\\", "/"), look, SIZE, 30,
                                      flare_pattern=os.path.join(flare, "flare_%05d.png").replace("\\", "/"), flare_frames=1,
                                      light_frames=1)
        subprocess.run(argv, check=True, capture_output=True, stdin=subprocess.DEVNULL)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        w, h = SIZE

        def line_row(frame):
            column = [raw[frame * w * h + y * w + w // 2] for y in range(h)]
            bright = [y for y in range(h) if column[y] > 128]
            return sum(bright) / float(len(bright))
        self.assertAlmostEqual(line_row(20), 29.5, delta=1.5)            # before the flare
        self.assertLess(line_row(30), 16, [round(line_row(f), 1) for f in range(28, 36)])
        self.assertAlmostEqual(line_row(42), 29.5, delta=1.5)            # and back after it


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class ExcerptRenderTest(unittest.TestCase):
    """review 10 and 11, through the command line mv_chunks uses: an excerpt from 1.9 s shows what the whole song shows
    at the same time.  The light loop is 30 frames, so the excerpt starts in it at frame 27 (a first part of 3 frames,
    which two joined inputs got wrong); a flare at frame 53 has 4 frames of picture, over before the excerpt, and 10 of
    punch, still running at its start"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.avi")
        source = ("color=c=black@0.0:s=%dx%d:r=30,format=rgba,"
                  "drawbox=x=40:y=30:w=60:h=40:color=white@1.0:t=fill:replace=1" % SIZE)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "90",
                        "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"count": 6, "opacity": 0.9, "sway": 25, "loop_seconds": 1}, "bokeh": {"count": 0},
                       "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0}, "flares": [53 / 30.0],
                       "flare": {"frames": 4}, "camera": {"punch": 0.3, "punch_frames": 10, "aberration": 3}}, f)
        cls.codes = []
        for name, extra in (("whole", []), ("part", ["--from", "1.9", "--to", "2.7"])):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                cls.codes.append(mv_look.main(["render", cls.fg, look, os.path.join(cls.folder, name + ".mp4"),
                                               "--work", os.path.join(cls.folder, "work_" + name)] + extra))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, name):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, name + ".mp4"), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).astype(numpy.int16) for i in range(len(raw) // n)]

    def test_the_excerpt_shows_the_whole_song_at_the_same_time(self):
        self.assertEqual(self.codes, [0, 0])
        whole, part = self.frames("whole"), self.frames("part")
        self.assertEqual(len(part), 24)
        gaps = [float(numpy.abs(part[j] - whole[57 + j]).mean()) for j in range(24)]
        self.assertLess(max(gaps), 2.0, [round(g, 2) for g in gaps])         # x264 noise: 1.1 (review 12); a wrong phase 4 to 19
        # and the test can see a difference: the light moves from frame to frame, and the punch is on at the start
        self.assertGreater(float(numpy.abs(whole[57] - whole[58]).mean()), 3 * max(gaps) + 0.5)
        self.assertGreater(float(numpy.abs(whole[57] - whole[65]).mean()), 3 * max(gaps) + 0.5)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class FromFrameTest(unittest.TestCase):
    """review stagecityrev: a dancer folded beforehand to 30 fps (PNG in a MOV, its frames timed in ticks of 1/15360 s) under an
    excerpt from frame K of the song.  -ss %.3f wrote 448 / 30 s as 14.933, and with -r before the file ffmpeg reads from the
    frame it seeks to, the last one at or before that time: the frame before, for every K of 1 mod 3.  An excerpt reads the
    dancer from its first frame (the one nearest --from, as the stage, the light and the cues take it), from such a MOV and from
    MMD's AVI alike, and a render lays under every frame the dancer of its frame of the song"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.files = {"mov": os.path.join(cls.folder, "folded.mov"), "avi": os.path.join(cls.folder, "mmd.avi")}
        numbered_dancer(cls.files["mov"], 48, 30)
        numbered_dancer(cls.files["avi"], 48, "10000000/333333")
        cls.look = os.path.join(cls.folder, "look.json")
        with open(cls.look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                       "lens": {"vignette": 0, "grain": 0}}, f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_an_excerpt_reads_the_dancer_from_its_first_frame(self):
        for kind, fg in sorted(self.files.items()):
            for first in range(1, 10):
                got = numbers_read(mv_look.dancer_input(fg, 30, 1, first / 30.0, 6 / 30.0, 0.0))
                self.assertEqual(got, list(range(first, first + 6)), (kind, first))
            # a chunk's file from frame 6 of the song (--offset), the excerpt from frame 10: frame 4 of the file
            self.assertEqual(numbers_read(mv_look.dancer_input(fg, 30, 1, 10 / 30.0, 3 / 30.0, 0.2)), [4, 5, 6], kind)

    def test_a_from_written_with_three_decimals_reads_the_frame_nearest_it(self):
        # 0.133 s for frame 4 (3.99 frames): the frame the stage, the light and the cues start on, whatever the file
        for kind, fg in sorted(self.files.items()):
            self.assertEqual(numbers_read(mv_look.dancer_input(fg, 30, 1, 0.133, 0.1, 0.0)), [4, 5, 6], kind)

    def box_edges(self, path):
        """the left edge of the dancer's box in every frame of a render (row 90, the first column of white)"""
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True,
                             capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        edges = []
        for i in range(len(raw) // n):
            row = numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3)[90].min(axis=1)
            white = numpy.nonzero(row > 200)[0]
            edges.append(int(white[0]) if len(white) else None)
        return edges

    def render(self, name, fg, *extra):
        out = os.path.join(self.folder, name + ".mp4")
        code, result = tool_answer(["render", fg, self.look, out, "--work", os.path.join(self.folder, "work_" + name)] + list(extra))
        self.assertEqual(code, 0, result)
        return self.box_edges(out)

    def test_a_render_lays_under_every_frame_the_dancer_of_its_frame_of_the_song(self):
        # the box of dancer frame j is at x = 20 + 4 j (x264 may move an edge by a pixel; a frame off moves it by 4)
        whole = self.render("whole", self.files["mov"])
        self.assertEqual(len(whole), 48)
        self.assertTrue(all(e is not None and abs(e - (20 + 4 * j)) <= 1 for j, e in enumerate(whole)), whole)
        for first in (3, 4, 5):
            part = self.render("from_%d" % first, self.files["mov"], "--from", "%.6f" % (first / 30.0),
                               "--to", "%.6f" % ((first + 12) / 30.0))
            self.assertEqual(len(part), 12, first)
            self.assertTrue(all(e is not None and abs(e - (20 + 4 * (first + k))) <= 1 for k, e in enumerate(part)),
                            (first, part))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class HighRateExcerptTest(unittest.TestCase):
    """an excerpt of a dancer at 1920 fps (64 subframes to a frame of 30 fps; `phase` and the fold take it) reads the frames of
    its span and no others.  Three decimals of a second are two thirds of a subframe there: -ss and -t of 1 / 30 s written as
    0.033 read from subframe 63 and 63 of them, 2 / 30 s as 0.067 read 129.  (A MOV: ffmpeg's AVI muxer writes 1920 fps as 600)"""

    def test_the_excerpt_reads_whole_frames_of_its_span(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        fg = os.path.join(folder, "fg1920.mov")
        numbered_dancer(fg, 64 * 5, 1920, size=(16, 8), box=False)
        for first in (1, 2):
            for frames in (1, 2):
                got = numbers_read(mv_look.dancer_input(fg, 30, 64, first / 30.0, frames / 30.0, 0.0))
                self.assertEqual(got, list(range(64 * first, 64 * (first + frames))), (first, frames))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class CameraClockRenderTest(unittest.TestCase):
    """lookfrom (2026-10-21): an excerpt punches and parts the colours of every frame as the whole song does that frame.  A black
    plate with a white line across (60 px above the middle) and one down (at x 100), a see-through dancer, a flare at 1.0 s with a
    punch of 0.3 and the colours parted by 2 px: in every frame, the row of the line across (the zoom) and how far red lies from
    blue on the line down.  With its times written as times of the excerpt to three decimals, the punch of an excerpt from frame
    1 mod 3 of the song began a frame late (1.0 - 1 / 30 s as 0.967, after the frame of 0.9667 s) and the one from 2 mod 3 was a
    little smaller on its first frame (0.933: 0.3 s from the flare's own time)"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.plate = os.path.join(cls.folder, "plate.png")
        image = Image.new("RGB", SIZE, (0, 0, 0))
        image.paste((255, 255, 255), (0, 29, SIZE[0], 31))
        image.paste((255, 255, 255), (100, 0, 102, SIZE[1]))
        image.save(cls.plate)
        light = os.path.join(cls.folder, "light")
        os.makedirs(light)
        Image.new("RGB", SIZE, (0, 0, 0)).save(os.path.join(light, "light_00000.png"))
        cls.light = os.path.join(light, "light_%05d.png").replace("\\", "/")
        flare = os.path.join(cls.folder, "flare")
        os.makedirs(flare)
        Image.new("RGBA", SIZE, (0, 0, 0, 0)).save(os.path.join(flare, "flare_00000.png"))
        cls.flare = os.path.join(flare, "flare_%05d.png").replace("\\", "/")
        cls.dancers = {}
        for rate in (30, 120):                                          # 1.6 s, see-through (a folded MOV keeps it small)
            cls.dancers[rate] = os.path.join(cls.folder, "fg%d.mov" % rate)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.0:s=%dx%d:r=%d,format=rgba"
                            % (SIZE[0], SIZE[1], rate), "-frames:v", str(rate * 8 // 5), "-c:v", "png", cls.dancers[rate]],
                           check=True, stdin=subprocess.DEVNULL)
        cls.look = mv_look.merge_look({"flares": [1.0], "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0},
                                       "flare": {"frames": 1, "strength": 0},
                                       "camera": {"punch": 0.3, "punch_frames": 10, "aberration": 8}})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def render(self, name, fps, subframes, **kw):
        """[(row of the line across, red's column less blue's on the line down)] of every frame"""
        out = os.path.join(self.folder, name + ".mp4")
        argv = mv_look.ffmpeg_command(self.dancers[fps * subframes], out, self.plate, self.light, self.look, SIZE, fps,
                                      flare_pattern=self.flare, flare_frames=1, light_frames=1, subframes=subframes, **kw)
        subprocess.run(argv, check=True, capture_output=True, stdin=subprocess.DEVNULL)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True,
                             capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        found = []
        for i in range(len(raw) // n):
            frame = numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3).astype(float)
            across = frame[:, 200:240].mean(axis=(1, 2))
            across = numpy.where(across > 40, across, 0)
            down = frame[120:160, 40:160]
            red, blue = down[:, :, 0].sum(axis=0), down[:, :, 2].sum(axis=0)
            x = numpy.arange(40, 160)
            found.append((float((across * numpy.arange(SIZE[1])).sum() / across.sum()),
                          float((red * x).sum() / red.sum() - (blue * x).sum() / blue.sum())))
        return found

    def test_an_excerpt_punches_and_parts_every_frame_as_the_whole_song(self):
        for fps, subframes in ((30, 1), (30, 4), (60, 2)):
            whole = self.render("whole_%d_%d" % (fps, subframes), fps, subframes)
            self.assertEqual(len(whole), fps * 8 // 5)
            punched = [j for j, (row, _) in enumerate(whole) if row < 25]
            parted = [j for j, (_, gap) in enumerate(whole) if gap < -2]
            self.assertEqual(punched[0], fps, (fps, subframes))                 # from its frame at 1.0 s
            self.assertEqual(parted, list(range(fps, fps + fps // 3)), (fps, subframes))   # for 10 frames of the song
            for first in range(1, 7):
                part = self.render("from_%d_%d_%d" % (first, fps, subframes), fps, subframes, start=first / float(fps),
                                   duration=(len(whole) - first) / float(fps))
                self.assertEqual(len(part), len(whole) - first, (fps, subframes, first))
                for k, ((row, gap), (row0, gap0)) in enumerate(zip(part, whole[first:])):
                    self.assertAlmostEqual(row, row0, delta=0.2, msg=(fps, subframes, first, first + k))
                    self.assertAlmostEqual(gap, gap0, delta=1.0, msg=(fps, subframes, first, first + k))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class LengthRenderTest(unittest.TestCase):
    """lookfrom (2026-10-21): -t comes from whole frames of the dancer, written to the microsecond.  At the rates MMD renders (30
    to 960 fps) ffmpeg reads a whole number of frames of three decimals' length too (it rounds -t to a frame of the dancer): a
    render with --to and no --from is the video of before, byte for byte (the argv of before is DefaultArgvTest's)"""

    def test_a_length_of_whole_frames_reads_what_three_decimals_read(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        size = (64, 36)
        look = mv_look.merge_look({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                                   "lens": {"vignette": 0, "grain": 0}})
        layers = mv_look.write_layers(look, os.path.join(folder, "work"), size, 30)
        for rate in ("10000000/333333", 240, 960):
            fg = os.path.join(folder, "fg_%s.avi" % str(rate).replace("/", "_"))
            subframes = 1 if "/" in str(rate) else rate // 30
            numbered_dancer(fg, 8 * subframes, rate, size=size)
            for frames in (4, 5):                                       # 0.1333 and 0.1667 s: three decimals cut down and up
                videos = []
                for name in ("now", "before"):
                    out = os.path.join(folder, "%s_%d_%s.mp4" % (subframes, frames, name))
                    argv = mv_look.ffmpeg_command(fg, out, layers["plate"], layers["light_pattern"], look, size, 30,
                                                  flare_pattern=layers["flare_pattern"], flare_frames=layers["flare_frames"],
                                                  duration=frames / 30.0, subframes=subframes, light_frames=layers["light_frames"])
                    if name == "before":
                        argv[argv.index("-t") + 1] = "%.3f" % (frames / 30.0)
                    subprocess.run(argv, check=True, capture_output=True, stdin=subprocess.DEVNULL)
                    videos.append(file_bytes(out))
                self.assertEqual(videos[0], videos[1], (rate, frames))
                count = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                        "stream=nb_read_frames", "-of", "csv=p=0", out], check=True, capture_output=True,
                                       text=True, stdin=subprocess.DEVNULL).stdout
                self.assertEqual(int(count.strip().strip(",")), frames, (rate, frames))


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class SubframeRenderTest(unittest.TestCase):
    """a white box moving 4 px per subframe at 120 fps, folded into 30 fps with a half-open shutter: each output
    frame shows it at two positions 4 px apart, so its two 4 px edges are half covered"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        frames = os.path.join(cls.folder, "src")
        os.makedirs(frames)
        for i in range(48):
            im = Image.new("RGBA", SIZE, (0, 0, 0, 0))
            im.paste((255, 255, 255, 255), (40 + 4 * i, 40, 120 + 4 * i, 160))
            im.save(os.path.join(frames, "f%05d.png" % i))
        cls.fg = os.path.join(cls.folder, "fg120.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "120", "-i", os.path.join(frames, "f%05d.png"),
                        "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0}, "glow": {"strength": 0},
                       "lens": {"vignette": 0, "grain": 0}}, f)
        cls.out = os.path.join(cls.folder, "out.mp4")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            cls.code = mv_look.main(["render", cls.fg, look, cls.out, "--work", os.path.join(cls.folder, "work"),
                                     "--subframes", "4", "--shutter", "0.5"])
        cls.result = json.loads(stream.getvalue())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_the_output_runs_at_a_quarter_of_the_rate(self):
        self.assertEqual(self.code, 0, self.result)
        self.assertEqual((self.result["fps"], self.result["subframes"], self.result["shutter"]), (30, 4, 0.5))
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames,r_frame_rate", "-of", "csv=p=0", self.out],
                               check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        rate, count = probe.stdout.strip().strip(",").split(",")
        self.assertEqual((rate, int(count)), ("30/1", 12))

    def test_the_box_is_smeared_over_two_positions_with_half_covered_edges(self):
        for k in (2, 5):
            path = os.path.join(self.folder, "k%d.png" % k)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", self.out, "-vf", "select='eq(n,%d)'" % k, "-frames:v", "1",
                            path], check=True, stdin=subprocess.DEVNULL)
            with Image.open(path) as image:
                row = [sum(image.convert("RGB").getpixel((x, 100))) / 3.0 for x in range(SIZE[0])]
            left, right = 40 + 16 * k, 124 + 16 * k                     # the union of the two positions
            core = [x for x in range(SIZE[0]) if row[x] > 225]
            self.assertTrue(abs(len(core) - 76) <= 3, (k, len(core)))
            self.assertTrue(abs(core[0] - (left + 4)) <= 2 and abs(core[-1] - (right - 5)) <= 2, (k, core[0], core[-1]))
            edges = [row[x] for x in list(range(left, left + 4)) + list(range(right - 4, right))]
            # white at half cover over the dark stage is about (255 + stage) / 2; an average of straight alpha
            # (without premultiplying) would give about a quarter of white instead
            self.assertTrue(all(95 < v < 200 for v in edges[1:3] + edges[5:7]), (k, [round(v) for v in edges]))

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


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class SixtyArgvTest(unittest.TestCase):
    """The version at 60 fps (tools/mv_chunks.py --out-fps 60) keeps its argv too when --encoder and --prepared come in: the
    SHA-256 of the argv of ThirtyArgvTest's chunks at the rate and layers of 60 fps, written with the tool of main afd25c4
    (_spike/out/stage5/fast_render/golden_argv60.py)"""

    GOLDEN = {"v7_04_flare_on_the_cut_60": "ded9433c9f18bb601fc385999787fa362f8df32ee83bbc61996223440c60eea3",
              "punch_carried_into_a_chunk_60": "f2cc475670d792a2aabac545b46b19083b0a98679938f8db0e90601bf717f587"}

    def test_the_argv_at_60_fps_is_the_one_of_before(self):
        # with the seconds of the excerpt and the clock of its camera put back as they were (lookfrom 2026-10-21, as at 30 fps)
        look = mv_look.merge_look(ThirtyArgvTest.V3)
        common = dict(flare_pattern="W/flare/flare_%05d.png", flare_frames=24, subframes=4, shutter=0.5, light_frames=1646)
        argvs = {"v7_04_flare_on_the_cut_60": (1334 / 30.0, mv_look.ffmpeg_command(
                     "C:/out/v7_04.avi", "C:/out/v7_04.mp4", "W/plate.png", "W/light/light_%05d.png", look, (1280, 720), 60,
                     plan=ThirtyArgvTest.PLAN, start=1334 / 30.0, duration=406 / 30.0, offset=1214 / 30.0, **common)),
                 "punch_carried_into_a_chunk_60": (2610 / 30.0, mv_look.ffmpeg_command(
                     "C:/out/x.avi", "C:/out/x.mp4", "W/plate.png", "W/light/light_%05d.png", look, (1280, 720), 60,
                     plan=ThirtyArgvTest.PLAN, start=2610 / 30.0, duration=40 / 30.0, offset=2490 / 30.0, **common))}
        for name, (start, argv) in argvs.items():
            self.assertIn("setpts=PTS+round(%d/(60*TB))," % round(start * 60), argv[argv.index("-filter_complex") + 1], name)
            argv = excerpt_of_before(argv, start, 10 / 30.0)
            self.assertEqual(hashlib.sha256("\0".join(colour_of_before(argv)).encode("utf-8")).hexdigest(), self.GOLDEN[name],
                             name)


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class DefaultArgvTest(unittest.TestCase):
    """lookfrom (2026-10-21) changes what an excerpt (--from) hands ffmpeg only: without --from the argv is the one main 058acae
    built, byte for byte (the SHA-256 of the argv joined by NUL, written with the tool of 058acae: the default look; the look v3
    with its cues over the whole song folded at 30 fps and at 60, from a chunk's file without --from, with nvenc and with the
    physics' shifts; a stage in the world; a stage of a model with its light on her), so a render without --from is the video of
    before.  With --to alone its length now comes in whole frames to the microsecond: with that put back to three decimals the
    argv is the one of 058acae too, and LengthRenderTest renders both to the same bytes"""

    V3 = ThirtyArgvTest.V3
    PLAN = ThirtyArgvTest.PLAN
    WORLD = {"stage": {"world": 1, "floor": 1, "shadow": 0.6, "dof": 1.5}, "flares": [0.6, 1.0, 44.467], "camera": {"aberration": 3}}
    LAYER = {"stage": {"world": 1, "floor": 1, "shadow": 0.5}, "flares": [1.0, 44.467],
             "layer": {"on": 1, "spill": 0.8, "spill_wrap": 1.4, "person": 0.9, "person_tint": [1.0, 0.95, 1.1]},
             "rim": {"strength": 0.5}}
    GOLDEN = {"default_look": "698f76371e5021036c89f53abd4cecaa025b63bf87f6b43eab9b279798c31a5b",
              "v3_whole_song_fold8": "072e34c7f08358e7cc4c5927f6c6b122fa5cef4088170a66187436a92cd06c83",
              "v3_whole_song_60fps": "e900c7612b506040dd04d2a7e3c3f131dd1891ac3798d7083810a3c828ad8667",
              "v3_chunk_file_offset_only": "f899678d2e08df873a76c65ad4a3263a680aff4748d4d456ff58ab33d05ed12f",
              "v3_to_only": "4fc5be99bc1d8de75ff8378507b2a7be0a5f2119b42f44b808be584ec48139a9",
              "v3_nvenc": "203c53f8a8d1dc67993b2678ca798da59aae9df3d17dee4970cd544529339a8b",
              "v3_physics_shifts": "9b49ac116eaacecc714702e19d94a0d5e0ec903a58ddb06adec513b407380284",
              "world_stage_fold16": "55f8bd0ba2675a7ebaf19fec3409c8076aac89f44f242aea5c2e0721b533d52e",
              "layer_spill_fold16": "c31eb110edb32e52fef3b470e678f35dd1d5aaa7dc97cfb85fc2586b12bb044b"}

    def argvs(self):
        v3 = mv_look.merge_look(self.V3)
        common = dict(flare_pattern="W/flare/flare_%05d.png", flare_frames=12, subframes=8, shutter=0.5, light_frames=823)
        yield "default_look", mv_look.ffmpeg_command(
            "C:/out/y.avi", "C:/out/y.mp4", "W/plate.png", "W/light/light_%05d.png", mv_look.merge_look({}), (1280, 720), 30,
            flare_pattern="W/flare/flare_%05d.png", flare_frames=12, light_frames=360)
        yield "v3_whole_song_fold8", mv_look.ffmpeg_command(
            "C:/out/w.avi", "C:/out/w.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 30, plan=self.PLAN, **common)
        yield "v3_whole_song_60fps", mv_look.ffmpeg_command(
            "C:/out/w.avi", "C:/out/w60.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 60, plan=self.PLAN,
            flare_pattern="W/flare/flare_%05d.png", flare_frames=24, subframes=4, shutter=0.5, light_frames=1646)
        yield "v3_chunk_file_offset_only", mv_look.ffmpeg_command(
            "C:/out/c.avi", "C:/out/c.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 30, plan=self.PLAN,
            offset=1214 / 30.0, **common)
        yield "v3_to_only", excerpt_of_before(mv_look.ffmpeg_command(
            "C:/out/t.avi", "C:/out/t.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 30, plan=self.PLAN,
            duration=406 / 30.0, **common), 0.0, 10 / 30.0)
        yield "v3_nvenc", mv_look.ffmpeg_command(
            "C:/out/w.avi", "C:/out/n.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 30, plan=self.PLAN,
            encoder="nvenc", **common)
        yield "v3_physics_shifts", mv_look.ffmpeg_command(
            "C:/out/w.avi", "C:/out/p.mp4", "W/plate.png", "W/light/light_%05d.png", v3, (1280, 720), 30, plan=self.PLAN,
            shifts=[(0, 2), (40, 5)], **common)
        yield "world_stage_fold16", mv_look.ffmpeg_command(
            "C:/out/s.avi", "C:/out/s.mp4", None, None, mv_look.merge_look(self.WORLD), (1280, 720), 30, plan=self.PLAN,
            flare_pattern="W/flare/flare_%05d.png", flare_frames=12, subframes=16, shutter=0.5,
            stage={"pattern": "W/stage/stage_%05d.png", "first": 0})
        yield "layer_spill_fold16", mv_look.ffmpeg_command(
            "C:/out/l.avi", "C:/out/l.mp4", None, None, mv_look.merge_look(self.LAYER), (1280, 720), 30, plan=self.PLAN,
            flare_pattern="W/flare/flare_%05d.png", flare_frames=12, subframes=16, shutter=0.5,
            stage={"pattern": "W/stage/stage_%05d.png", "first": 0, "spill": "W/stage/spill_%05d.png"})

    def test_without_from_the_argv_is_the_one_of_058acae(self):
        names = []
        for name, argv in self.argvs():
            names.append(name)
            self.assertEqual(hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest(), self.GOLDEN[name], name)
        self.assertEqual(sorted(names), sorted(self.GOLDEN))

    def test_with_to_alone_only_the_length_is_written_otherwise(self):
        argv = mv_look.ffmpeg_command("C:/out/t.avi", "C:/out/t.mp4", "W/plate.png", "W/light/light_%05d.png",
                                      mv_look.merge_look(self.V3), (1280, 720), 30, plan=self.PLAN, duration=406 / 30.0,
                                      flare_pattern="W/flare/flare_%05d.png", flare_frames=12, subframes=8, light_frames=823)
        self.assertEqual(argv[4:10], ["-t", "13.533333", "-r", "240", "-i", "C:/out/t.avi"])
        self.assertNotIn("-ss", argv)
        self.assertNotIn("setpts=PTS+round(", argv[argv.index("-filter_complex") + 1])


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class EncoderArgvTest(unittest.TestCase):
    """--encoder nvenc encodes on the GPU (h264_nvenc).  Everything before the encoder (the inputs, the graph, the rate) is
    the argv of libx264, and libx264 stays the default"""

    def argv(self, **kw):
        return mv_look.ffmpeg_command("C:/out/a.avi", "C:/out/a.mp4", "W/plate.png", "W/light/light_%05d.png",
                                      mv_look.merge_look(ThirtyArgvTest.V3), (1280, 720), 60, plan=ThirtyArgvTest.PLAN,
                                      flare_pattern="W/flare/flare_%05d.png", flare_frames=24, start=1334 / 30.0,
                                      duration=406 / 30.0, offset=1214 / 30.0, subframes=4, shutter=0.5, light_frames=1646, **kw)

    def test_libx264_at_crf_16_is_the_default(self):
        argv = self.argv()
        self.assertEqual(argv, self.argv(encoder="x264"))
        self.assertEqual(argv[argv.index("-c:v"):], ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                                                     "-movflags", "+faststart", "C:/out/a.mp4"])

    def test_nvenc_changes_the_encoder_and_nothing_before_it(self):
        x264, nvenc = self.argv(), self.argv(encoder="nvenc")
        cut = x264.index("-c:v")
        self.assertEqual(nvenc[:cut], x264[:cut])
        self.assertEqual(nvenc[cut:cut + 2], ["-c:v", "h264_nvenc"])
        self.assertEqual(nvenc[cut + 2:-5], mv_look.NVENC)
        self.assertEqual(nvenc[-5:], ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "C:/out/a.mp4"])
        self.assertNotIn("libx264", nvenc)
        self.assertNotIn("-crf", nvenc)

    def test_an_encoder_it_does_not_know_is_refused(self):
        for encoder in ("h264", "", None, "NVENC"):
            with self.assertRaises(ValueError, msg=encoder):
                self.argv(encoder=encoder)


class FakeRun:
    """stands in for subprocess.run inside mv_look: records each argv, writes the output file ffmpeg would, and answers as
    `answer` says (the return code of an encoder check)"""

    def __init__(self, answer=0):
        self.calls = []
        self.answer = answer

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "ffmpeg" and argv[-1] not in ("-", "NUL") and self.answer == 0:
            with open(argv[-1], "wb") as f:
                f.write(b"mp4")
        return subprocess.CompletedProcess(argv, self.answer, "", "ffmpeg said no" if self.answer else "")


def tool_answer(argv):
    """mv_look.main(argv) as the drivers run it: the exit code and its one line of JSON"""
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = mv_look.main(argv)
    return code, json.loads(stream.getvalue())


def listing(folder):
    """every file under folder with its size and time of writing"""
    found = {}
    for top, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(top, name)
            found[os.path.relpath(path, folder)] = (os.path.getsize(path), os.stat(path).st_mtime_ns)
    return found


def font_book_or_skip():
    """the cue tests draw text: skipped on a machine with no Japanese font (as tests/test_mv_text.py does)"""
    spec = importlib.util.spec_from_file_location("mv_text", os.path.join(ROOT, "tools", "mv_text.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.FontBook()
    except ValueError as exc:
        raise unittest.SkipTest(str(exc))


CUES = {"fps": 30, "size": [320, 180],
        "cues": [{"id": "a1", "start": 0.2, "end": 0.9, "text": "ABC", "style": "caption", "anim": "rise", "x": "left", "y": "top"},
                 {"id": "b2", "start": 0.4, "end": 1.2, "text": "HIBI", "style": "logo", "anim": "fade", "layer": "back"}]}


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class PreparedLayersTest(unittest.TestCase):
    """`prepare` writes the layers and the text sequences once, with a note of what they were made from (tools/mv_chunks.py
    --workers folds several chunks at the same time, and they share one set); `render --prepared WORK` uses them as they
    are, after checking that they were made from the same look, cues, size and rate by the same tools, and builds the argv
    that `render --work WORK` builds"""

    def setUp(self):
        font_book_or_skip()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.look = self.put("look.json", {"beams": {"loop_seconds": 1}, "flares": [0.5], "flare": {"frames": 4}})
        self.cues = self.put("cues.json", CUES)
        self.work = os.path.join(self.folder, "work")
        self.fg = os.path.join(self.folder, "fg.avi")
        open(self.fg, "wb").close()                          # never read: the size and the rate are given

    def put(self, name, doc):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def prepare(self, *extra, **kw):
        code, result = tool_answer(["prepare", kw.get("look", self.look), kw.get("work", self.work), "--size", "320x180",
                                    "--fps", "30", "--cues", self.cues] + list(extra))
        self.assertEqual(code, 0, result)
        return result

    def render(self, *extra, **kw):
        fake = FakeRun()
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake):
            code, result = tool_answer(["render", self.fg, kw.get("look", self.look), os.path.join(self.folder, "out.mp4"),
                                        "--size", kw.get("size", "320x180"), "--fps", kw.get("fps", "120"), "--subframes", "4",
                                        "--offset", "0.2", "--from", "0.3", "--to", "1.0"] + list(extra))
        return code, result, [c for c in fake.calls if c[0] == "ffmpeg"]

    def test_prepare_writes_the_layers_the_text_and_what_they_were_made_from(self):
        result = self.prepare()
        self.assertEqual((result["light_frames"], result["flare_frames"], result["cues"]), (30, 4, 2))
        names = sorted(os.listdir(self.work))
        self.assertEqual(names, ["flare", "light", "plate.png", "prepared.json", "text"])
        self.assertEqual(len(os.listdir(os.path.join(self.work, "light"))), 30)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "text"))), ["cue_a1", "cue_b2"])
        with open(os.path.join(self.work, "prepared.json"), encoding="utf-8") as f:
            note = json.load(f)
        self.assertEqual(sorted(note), ["key", "layers", "text", "work"])

    def test_render_with_prepared_layers_writes_nothing_and_builds_the_argv_of_its_work_folder(self):
        self.prepare()
        before = listing(self.work)
        code, result, prepared = self.render("--prepared", self.work, "--cues", self.cues)
        self.assertEqual(code, 0, result)
        self.assertEqual(listing(self.work), before)                         # read only: the other chunks use them too
        self.assertEqual((result["work"], result["prepared"]), (os.path.abspath(self.work), True))
        code, result, worked = self.render("--work", self.work, "--cues", self.cues)
        self.assertEqual(code, 0, result)
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared, worked)                                   # so the video is the same, byte for byte

    def test_layers_prepared_from_something_else_are_refused(self):
        self.prepare()
        other_look = self.put("other.json", {"beams": {"loop_seconds": 1}, "flares": [0.6], "flare": {"frames": 4}})
        other_cues = self.put("other_cues.json", dict(CUES, cues=CUES["cues"][:1]))
        for label, kw, extra in (("another look", {"look": other_look}, ["--cues", self.cues]),
                                 ("another rate", {"fps": "240"}, ["--cues", self.cues]),
                                 ("another size", {"size": "160x90"}, ["--cues", self.cues]),
                                 ("no cues", {}, []),
                                 ("other cues", {}, ["--cues", other_cues])):
            code, result, calls = self.render("--prepared", self.work, *extra, **kw)
            self.assertEqual(code, 2, (label, result))
            self.assertIn("prepare", result["error"]["message"], label)
            self.assertEqual(calls, [], label)

    def test_a_prepared_folder_short_of_a_frame_or_with_one_too_many_is_refused(self):
        self.prepare()
        cue = os.path.join(self.work, "text", "cue_a1")

        def one_more_cue_frame():                     # right after its last: ffmpeg would read it (a gap further on it would not)
            shutil.copyfile(os.path.join(cue, "f00000.png"), os.path.join(cue, "f%05d.png" % len(os.listdir(cue))))
        for label, change in (("a light frame gone", lambda: os.remove(os.path.join(self.work, "light", "light_00003.png"))),
                              ("a flare frame more", lambda: shutil.copyfile(os.path.join(self.work, "flare", "flare_00000.png"),
                                                                            os.path.join(self.work, "flare", "flare_00004.png"))),
                              ("a cue frame more", one_more_cue_frame)):
            self.prepare()                                                    # whole again
            change()
            code, result, calls = self.render("--prepared", self.work, "--cues", self.cues)
            self.assertEqual(code, 2, (label, result))
            self.assertIn("prepare", result["error"]["message"], label)
        self.prepare()
        moved = os.path.join(self.folder, "moved")
        shutil.copytree(self.work, moved)                                     # its patterns still name the old folder
        code, result, calls = self.render("--prepared", moved, "--cues", self.cues)
        self.assertEqual(code, 2, result)
        self.assertIn("prepare", result["error"]["message"])

    def test_a_folder_that_was_never_prepared_is_refused(self):
        code, result, calls = self.render("--prepared", os.path.join(self.folder, "nothing"), "--cues", self.cues)
        self.assertEqual(code, 2, result)
        self.assertIn("prepare", result["error"]["message"])

    def test_prepared_and_work_do_not_go_together(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mv_look.main(["render", self.fg, self.look, os.path.join(self.folder, "o.mp4"), "--work", self.work,
                          "--prepared", self.work])

    def test_prepare_again_clears_what_a_longer_loop_left(self):
        self.prepare()
        self.put("look.json", {"beams": {"loop_seconds": 0.5}, "flares": [0.5], "flare": {"frames": 2}})
        result = self.prepare()
        self.assertEqual((result["light_frames"], result["flare_frames"]), (15, 2))
        self.assertEqual(len(os.listdir(os.path.join(self.work, "light"))), 15)
        code, result, calls = self.render("--prepared", self.work, "--cues", self.cues)
        self.assertEqual(code, 0, result)

    def test_layers_drawn_again_with_work_or_layers_take_the_note_away(self):
        # `render --work` and `layers` into a prepared folder draw their own layers there: the note of prepare must not go on
        # vouching for them (review of fast-render, 2-d: look A prepared, look B drawn with --work, then A --prepared folded
        # with the layers of B and said nothing)
        self.prepare()
        other = self.put("other.json", {"beams": {"loop_seconds": 1, "opacity": 0.9}, "flares": [0.5], "flare": {"frames": 4}})
        code, result, calls = self.render("--work", self.work, "--cues", self.cues, look=other)
        self.assertEqual(code, 0, result)
        self.assertFalse(os.path.exists(os.path.join(self.work, "prepared.json")))
        code, result, calls = self.render("--prepared", self.work, "--cues", self.cues)
        self.assertEqual(code, 2, result)
        self.assertIn("prepare", result["error"]["message"])
        self.assertEqual(calls, [])
        self.prepare()
        code, result = tool_answer(["layers", other, self.work, "--size", "320x180", "--fps", "30"])
        self.assertEqual(code, 0, result)
        code, result, calls = self.render("--prepared", self.work, "--cues", self.cues)
        self.assertEqual(code, 2, result)

    def test_a_prepare_that_fails_half_way_leaves_no_note(self):
        # the note of an earlier prepare goes first: a prepare that draws other layers and then fails on its cue file leaves no
        # note that vouches for them (review of fast-render, m23)
        self.prepare()
        other = self.put("other.json", {"beams": {"loop_seconds": 1, "opacity": 0.9}, "flares": [0.5], "flare": {"frames": 4}})
        broken = os.path.join(self.folder, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{broken")
        code, result = tool_answer(["prepare", other, self.work, "--size", "320x180", "--fps", "30", "--cues", broken])
        self.assertEqual(code, 2, result)
        for look in (self.look, other):
            code, result, calls = self.render("--prepared", self.work, "--cues", self.cues, look=look)
            self.assertEqual(code, 2, (look, result))
            self.assertEqual(calls, [])

    def test_layers_prepared_by_another_version_of_the_tools_are_refused(self):
        # the note holds the code of mv_look, mv_text and mv_world (review of fast-render, m15): with a copy of the tools, a
        # byte more in any of them after prepare refuses the layers
        copy = os.path.join(self.folder, "tools")
        os.makedirs(copy)
        for name in ("mv_look.py", "mv_text.py", "mv_world.py"):
            shutil.copyfile(os.path.join(ROOT, "tools", name), os.path.join(copy, name))
        spec = importlib.util.spec_from_file_location("mv_look_copy", os.path.join(copy, "mv_look.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        look = module.load_look(self.look)
        module.prepare(look, self.work, (320, 180), 30, self.cues)
        module.load_prepared(self.work, look, (320, 180), 30, self.cues)                # as it was: taken
        for name in ("mv_look.py", "mv_text.py", "mv_world.py"):
            path = os.path.join(copy, name)
            with open(path, "rb") as f:
                kept = f.read()
            with open(path, "ab") as f:
                f.write(b"\n# another version\n")
            with self.assertRaises(ValueError, msg=name) as ctx:
                module.load_prepared(self.work, look, (320, 180), 30, self.cues)
            self.assertIn("another version", str(ctx.exception))
            with open(path, "wb") as f:
                f.write(kept)
        module.load_prepared(self.work, look, (320, 180), 30, self.cues)                # both back: taken again


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class EncoderCheckTest(unittest.TestCase):
    """the look check of the drivers (`layers`, `prepare`) with --encoder nvenc also encodes a few frames with h264_nvenc,
    so that a machine without it stops the run before MMD renders; libx264 is not tried (the default does what it did)"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.look = os.path.join(self.folder, "look.json")
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 0.2}}, f)

    def check(self, answer, *extra):
        fake = FakeRun(answer)
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake):
            code, result = tool_answer(["layers", self.look, os.path.join(self.folder, "w"), "--size", "64x36", "--fps", "30"]
                                       + list(extra))
        return code, result, fake.calls

    def test_nvenc_that_does_not_work_stops_the_check(self):
        code, result, calls = self.check(1, "--encoder", "nvenc")
        self.assertEqual(code, 2, result)
        self.assertIn("h264_nvenc", result["error"]["message"])
        self.assertIn("ffmpeg said no", result["error"]["message"])
        self.assertEqual(len(calls), 1)
        self.assertIn("h264_nvenc", calls[0])

    def test_nvenc_that_works_passes(self):
        code, result, calls = self.check(0, "--encoder", "nvenc")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(calls), 1)

    def test_the_default_runs_no_encoder(self):
        code, result, calls = self.check(1)
        self.assertEqual(code, 0, result)
        self.assertEqual(calls, [])


def nvenc_works():
    """h264_nvenc encodes here (an NVIDIA GPU, a driver and an ffmpeg built with it); False otherwise"""
    if not FFMPEG:
        return False
    done = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=30", "-frames:v", "3",
                           "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    return done.returncode == 0


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class PreparedRenderTest(unittest.TestCase):
    """rendered for real: a chunk folded with prepared layers is the chunk folded with its own work folder, byte for byte; and
    with --encoder nvenc (where h264_nvenc works) it has the same frames, close to those of libx264"""

    @classmethod
    def setUpClass(cls):
        font_book_or_skip()
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg120.avi")
        graph = ("color=c=black@0.0:s=%dx%d:r=120,format=rgba[stage];color=c=white:s=60x90:r=120,format=rgba[box];"
                 "[stage][box]overlay=x='40+2*n':y=40:shortest=1" % SIZE)              # a box moving 2 px a subframe
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-frames:v", "144", "-c:v", "rawvideo",
                        "-pix_fmt", "bgra", cls.fg], check=True, stdin=subprocess.DEVNULL)
        cls.look = os.path.join(cls.folder, "look.json")
        with open(cls.look, "w", encoding="utf-8") as f:
            json.dump({"beams": {"loop_seconds": 1}, "flares": [0.5], "flare": {"frames": 4}, "lens": {"grain": 0}}, f)
        cls.cues = os.path.join(cls.folder, "cues.json")
        with open(cls.cues, "w", encoding="utf-8") as f:
            json.dump(CUES, f)
        cls.prepared = os.path.join(cls.folder, "prepared")
        cls.codes = [tool_answer(["prepare", cls.look, cls.prepared, "--size", "%dx%d" % SIZE, "--fps", "30",
                                  "--cues", cls.cues])[0]]
        common = ["--cues", cls.cues, "--subframes", "4", "--offset", "0.1", "--from", "0.2", "--to", "1.1"]
        for name, extra in (("worked", ["--work", os.path.join(cls.folder, "work")]), ("prepared", ["--prepared", cls.prepared])):
            cls.codes.append(tool_answer(["render", cls.fg, cls.look, os.path.join(cls.folder, name + ".mp4")] + common + extra)[0])
        cls.nvenc = nvenc_works()
        if cls.nvenc:
            cls.codes.append(tool_answer(["render", cls.fg, cls.look, os.path.join(cls.folder, "nvenc.mp4"), "--prepared",
                                          cls.prepared, "--encoder", "nvenc"] + common)[0])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, name):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, name + ".mp4"), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).astype(numpy.int16) for i in range(len(raw) // n)]

    def test_prepared_layers_give_the_video_of_the_work_folder_byte_for_byte(self):
        self.assertTrue(all(code == 0 for code in self.codes), self.codes)
        self.assertEqual(file_bytes(os.path.join(self.folder, "prepared.mp4")), file_bytes(os.path.join(self.folder, "worked.mp4")))
        self.assertEqual(len(self.frames("prepared")), 27)

    def test_nvenc_gives_the_same_frames_close_to_libx264(self):
        if not self.nvenc:
            self.skipTest("h264_nvenc does not work on this machine")
        self.assertTrue(all(code == 0 for code in self.codes), self.codes)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt",
                                "-of", "csv=p=0", os.path.join(self.folder, "nvenc.mp4")],
                               check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(probe.stdout.strip(), "h264,yuv420p")
        x264, nvenc = self.frames("prepared"), self.frames("nvenc")
        self.assertEqual(len(nvenc), len(x264))
        gaps = [float(numpy.abs(a - b).mean()) for a, b in zip(x264, nvenc)]
        self.assertLess(max(gaps), 2.0, [round(g, 2) for g in gaps])


if __name__ == "__main__":
    unittest.main()
