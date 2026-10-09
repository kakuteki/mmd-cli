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
        # MMD writes "30 fps" as 30.00003 (ffprobe: 10000000/333333); the layers must run at 30, not drift
        self.assertEqual(mv_look.parse_rate("10000000/333333"), 30)
        self.assertIsInstance(mv_look.parse_rate("10000000/333333"), int)
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
        # review 11: the flare at 1.0 s has 4 frames of picture (over at 1.133 s) and 10 of punch (until 1.333 s)
        look = mv_look.merge_look({"flares": [1.0], "flare": {"frames": 4},
                                   "camera": {"punch": 0.05, "punch_frames": 10, "aberration": 8}})
        argv = mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, 30,
                                      flare_pattern="W/flare_%05d.png", flare_frames=4, start=1.2, light_frames=30)
        self.assertNotIn("W/flare_%05d.png", argv)                       # no picture left to lay over
        f = self.filter_of(argv)
        self.assertIn("(t+0.200)", f)
        self.assertIn("between(t,-0.200,0.133)", f)

    def test_a_flare_that_began_before_the_chunk_has_its_punch_part_spent(self):
        # review 10: the flare at 1.0 s seen from a chunk that begins at 1.1 s began 0.1 s before the chunk
        look = {"flares": [1.0], "camera": {"punch": 0.05, "punch_frames": 9, "aberration": 8}}
        f = self.filter_of(self.graph(look=look, start=1.1, light_frames=30))
        self.assertIn("(t+0.100)", f)
        self.assertIn("gte(t,-0.100)", f)
        self.assertNotIn("(t-0.000)", f)
        self.assertIn("between(t,-0.100,0.200)", f)

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
        self.assertEqual(argv[argv.index("-ss") + 1], "0.100")
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


if __name__ == "__main__":
    unittest.main()
