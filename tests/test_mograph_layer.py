"""tools/mograph_layer.py: the motion graphics of the MV (the look's "mograph" section, drawn by tools/mv_look.py): punches,
shakes, flashes, fades, dissolves, glitches and the particles in the air, placed on the song's structure."""
import contextlib
import copy
import importlib.util
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy
    from PIL import Image
except ImportError:                                   # the tool needs Pillow and numpy; the rest of the suite does not
    numpy = None

if numpy is not None:
    import sys
    sys.path.insert(0, ROOT)
    from mmd_cli import fk, motion_edit
    from mmd_cli.formats import vmd


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ML = load("mograph_layer") if numpy is not None else None
mv_look = load("mv_look") if numpy is not None else None
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
SIZE = (320, 180)


def analyzer():
    try:
        import cv2  # noqa: F401
        import scipy.ndimage  # noqa: F401
    except ImportError:
        return None
    return load("mograph_analyze")


MA = analyzer() if numpy is not None else None

# a song of 60 bars at 140 BPM, as looks/song_structure.json gives one (the parts plan reads)
FIRST, PERIOD = 0.01593, 0.4285714


def at(beat):
    return round(FIRST + beat * PERIOD, 3)


STRUCTURE = {
    "seconds": 100.0, "beat": {"bpm": 140.0, "first": FIRST, "period": PERIOD, "per_bar": 4},
    "sections": [{"id": sid, "beat": b, "t": at(b)} for sid, b in (
        ("intro", 0), ("band", 16), ("verse1", 32), ("pre1", 48), ("chorus1", 64), ("inter1", 96), ("verse2", 112),
        ("pre2", 128), ("chorus2", 144), ("bridge", 176), ("bridge2", 184), ("break", 192), ("chorus3", 200),
        ("outro", 216), ("last", 224), ("end", 228))],
    "chorus_halves": [{"beat": 80, "t": at(80)}, {"beat": 160, "t": at(160)}, {"beat": 208, "t": at(208)}],
    "hooks": [{"n": 1, "beat": 93, "t": at(93)}, {"n": 2, "beat": 173, "t": at(173)}, {"n": 3, "beat": 225, "t": at(225)}],
    "interludes": [{"from": 40.0, "to": 47.5}, {"from": 82.0, "to": 85.5}],
    "end": {"from": 97.7, "to": 100.0},
    "landings": [{"t": 30.0, "air_frames": 8}, {"t": 30.3, "air_frames": 6}, {"t": 60.0, "air_frames": 9}],
    "accents": [{"t": 20.06, "decel": 6.0}, {"t": 30.1, "decel": 7.0}, {"t": 70.0, "decel": 3.0}],
    "skirt": [at(80) + 0.3, at(128) + 0.3],
}


def fr(seconds):
    """the frame of the song (30 a second) an event at `seconds` starts on"""
    return ML.frame_of(seconds, 30)


def picture_look(**mograph):
    """a look fixed to the picture with nothing that moves but the motion graphics (no light loop, no glow, no lens)"""
    return {"mograph": dict({"on": 1}, **mograph), "flares": [], "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0},
            "beams": {"count": 0, "loop_seconds": 1}, "bokeh": {"count": 0},
            "plate": {"base": [60, 60, 60], "haze": [0, 0, 0], "pool": [0, 0, 0], "vignette": 0}}


# ---- the section ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(ML, "needs numpy")
class SectionTest(unittest.TestCase):
    def test_the_default_draws_nothing_and_a_look_without_it_is_the_look_of_before(self):
        self.assertEqual(ML.merge({})["on"], 0)
        look = mv_look.merge_look({})
        self.assertEqual(look["mograph"]["on"], 0)
        self.assertEqual(mv_look.merge_look({"mograph": {"on": 0}})["mograph"]["on"], 0)

    def test_values_put_over_the_defaults_and_events_come_sorted(self):
        s = ML.merge({"on": 1, "punch": {"amount": 0.15}, "events": [
            {"kind": "flash", "t": 2.0, "note": "late"}, {"kind": "punch", "t": 1.0, "amount": 0.2}]})
        self.assertEqual(s["punch"]["amount"], 0.15)
        self.assertEqual(s["punch"]["fall"], ML.DEFAULTS["punch"]["fall"])
        self.assertEqual([e["t"] for e in s["events"]], [1.0, 2.0])
        full = ML.events_of(s)
        self.assertEqual(full[0]["amount"], 0.2)                       # the event's own value
        self.assertEqual(full[0]["fall"], ML.DEFAULTS["punch"]["fall"])
        self.assertEqual(full[1]["strength"], ML.DEFAULTS["flash"]["strength"])
        self.assertNotEqual(ML.DEFAULTS["punch"]["amount"], 0.15)     # the defaults are not touched

    def test_a_wrong_value_is_an_error(self):
        for bad in ({"on": 2}, {"on": True}, {"punch": {"amonut": 0.1}}, {"punch": {"amount": 0.9}},
                    {"punch": {"rise": 0}}, {"punch": {"rise": 1.5}}, {"punch": {"centre": [0.5]}},
                    {"punch": {"centre": [1.2, 0.5]}}, {"shake": {"hz": 20}}, {"flash": {"colour": [300, 0, 0]}},
                    {"fade": {"hold": -2}}, {"glitch": {"bands": -1}}, {"particles": {"box": [0, 0, 0, 1, -1, 1]}},
                    {"events": [{"kind": "zoom", "t": 1.0}]}, {"events": [{"kind": "punch", "t": -1.0}]},
                    {"events": [{"kind": "punch", "t": 1.0, "strength": 0.3}]}, {"events": [{"kind": "flash"}]},
                    {"events": [{"kind": "flash", "t": 1.0, "note": 3}]}, {"events": "soon"},
                    {"busy": [[3.0, 1.0, 2.0]]}, {"busy": [[1.0, 3.0]]}, {"wobble": 1}):
            with self.assertRaises(ValueError, msg=bad):
                ML.merge(dict({"on": 1}, **bad))

    def test_a_value_that_would_draw_nothing_is_an_error(self):
        # (as layer.*: a setting that silently does nothing is refused)
        for idle in ({"events": [{"kind": "flash", "t": 1.0}]}, {"particles": {"specks": 10}}, {"punch": {"amount": 0.2}}):
            with self.assertRaises(ValueError, msg=idle):
                ML.merge(dict({"on": 0}, **idle))
            ML.merge(dict({"on": 1}, **idle))

    def test_the_look_takes_the_section_and_refuses_particles_off_the_world(self):
        look = mv_look.merge_look({"mograph": {"on": 1, "events": [{"kind": "punch", "t": 1.0}]}})
        self.assertEqual(look["mograph"]["events"][0]["kind"], "punch")
        with self.assertRaises(ValueError):
            mv_look.merge_look({"mograph": {"on": 1, "particles": {"specks": 10}}})          # a stage fixed to the picture
        mv_look.merge_look({"mograph": {"on": 1, "particles": {"specks": 10}}, "stage": {"world": 1}})
        with self.assertRaises(ValueError):
            mv_look.merge_look({"mograph": {"on": 1, "events": [{"kind": "punch", "t": 1.0, "rise": 0}]}})


# ---- the plan --------------------------------------------------------------------------------------------------------

@unittest.skipUnless(ML, "needs numpy")
class PlanTest(unittest.TestCase):
    def setUp(self):
        self.section = ML.plan(copy.deepcopy(STRUCTURE))
        self.events = ML.events_of(self.section)

    def kind(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def frames(self, kind):
        return sorted(fr(e["t"]) for e in self.kind(kind))

    def test_every_event_is_written_as_its_frames_time_so_round_and_ceil_agree(self):
        # (a flare's punch began a frame after its picture where a time sat a hair over its frame: lookfrom, 2026-10-21)
        for e in self.events:
            for fps in (30, 60, 240):                    # (under the frame by 0.3 to 1.3 ms: half a frame at 240 is 2.1)
                x = e["t"] * fps
                self.assertEqual(math.ceil(x), round(x), (e, fps))
            self.assertEqual(e["t"], round(e["t"], 3), e)
        self.assertEqual(ML.frame_time(1334), 44.466)                          # the coordinator's 44.466 and 225.799
        self.assertEqual(ML.frame_time(6774), 225.799)

    def test_a_flash_on_the_first_beat_of_every_title_word_and_nowhere_else(self):
        # (the references' flashes are 0.8 a minute, and of those the editor's white ones fewer: typorev's targets)
        self.assertEqual(self.frames("flash"), sorted(fr(h["t"]) for h in STRUCTURE["hooks"]))

    def test_a_punch_on_every_title_word_every_chorus_and_the_pre_choruses_only(self):
        punches = self.frames("punch")
        for h in STRUCTURE["hooks"]:
            self.assertIn(fr(h["t"]), punches)
        for sid in ("chorus1", "chorus2", "chorus3", "pre1"):
            self.assertIn(fr([s for s in STRUCTURE["sections"] if s["id"] == sid][0]["t"]), punches, sid)
        for b in (80, 160, 208, 184):                    # the choruses' halves and the bridge's second half: none
            self.assertNotIn(fr(at(b)), punches, b)
        # (three choruses and two pre-choruses: pre2's is next to the skirt, below)
        self.assertEqual(len(punches), len(STRUCTURE["hooks"]) + 5 - 1)

    def test_every_punch_and_flash_is_on_a_beat_and_every_event_says_why(self):
        for e in self.kind("punch") + self.kind("flash"):
            beat = round((e["t"] - FIRST) / PERIOD)
            self.assertEqual(fr(e["t"]), fr(FIRST + beat * PERIOD), e)
        for e in self.events:
            self.assertTrue(e.get("note"), e)

    def test_no_punch_or_shake_where_the_skirt_flares(self):
        for skirt in STRUCTURE["skirt"]:
            for e in self.kind("punch") + self.kind("shake"):
                a, b = ML.event_frames(e, 30)
                self.assertFalse(a / 30.0 - 0.5 < skirt < b / 30.0 + 0.5, e)
        self.assertNotIn(fr(at(128)), self.frames("punch"))                  # pre2's, next to it, is left out
        self.assertIn(fr(at(48)), self.frames("punch"))

    def test_shakes_on_landings_and_strong_accents_half_a_second_apart(self):
        shakes = self.frames("shake")
        self.assertIn(fr(30.0), shakes)
        self.assertNotIn(fr(30.1), shakes)               # within half a second of the landing at 30.0
        self.assertNotIn(fr(30.3), shakes)
        self.assertIn(fr(60.0), shakes)
        self.assertIn(fr(20.06), shakes)                 # an accent the dance stops on
        self.assertNotIn(fr(70.0), shakes)               # one it does not (deceleration 3)
        self.assertTrue(all(b - a >= 15 for a, b in zip(shakes, shakes[1:])))

    def test_the_fades_dissolves_and_glitches_go_where_the_song_changes(self):
        def lead(b):
            # the frame of the change: the references' cuts come CUT_LEAD (0.077 s, 2.3 frames) before the beat
            return fr(at(b) - ML.CUT_LEAD)
        for b in (16, 112, 176, 192, 228):
            self.assertIn(fr(at(b)) - lead(b), (2, 3), b)
        fades = self.kind("fade")
        dip = [e for e in fades if e["back"] == 0 and e["hold"] >= 0][0]
        # black until the change before the band's first beat, then back at once, without a flash
        self.assertEqual(fr(dip["t"]) + dip["out"] + dip["hold"], lead(16))
        self.assertNotIn(fr(at(16)), self.frames("flash"))
        brk = [e for e in fades if e["hold"] == 4][0]
        self.assertEqual(fr(brk["t"]) + brk["out"], lead(192))                 # black at the break
        self.assertEqual([fr(e["t"]) for e in fades if e["hold"] == -1], [lead(228)])   # the end, from the last bar line on
        self.assertEqual(self.frames("dissolve"), [lead(112), lead(176)])
        self.assertEqual(self.frames("glitch"), [fr(at(199)), fr(at(216))])

    def test_the_particles_are_busier_over_the_interludes(self):
        self.assertEqual(self.section["busy"], [[40.0, 47.5, 1.3], [82.0, 85.5, 1.3]])
        self.assertGreater(self.section["particles"]["specks"], 0)

    def test_the_plan_is_a_table_to_edit_by_hand(self):
        # drop a punch, move a flash, add a glitch: the section takes the edit as it is
        doc = json.loads(json.dumps({k: v for k, v in self.section.items()}))
        punches = [i for i, e in enumerate(doc["events"]) if e["kind"] == "punch"]
        del doc["events"][punches[0]]
        doc["events"].append({"kind": "glitch", "t": 12.5, "frames": 3, "note": "by hand"})
        edited = ML.merge(doc)
        self.assertEqual(len([e for e in edited["events"] if e["kind"] == "punch"]), len(punches) - 1)
        self.assertIn(12.5, [e["t"] for e in edited["events"] if e["kind"] == "glitch"])

    def test_the_level_scales_the_strength_of_punches_shakes_and_flashes(self):
        soft = ML.events_of(ML.plan(copy.deepcopy(STRUCTURE), level=0.5))
        for a, b in zip(self.events, soft):
            key = {"punch": "amount", "shake": "amount", "flash": "strength"}.get(a["kind"])
            if key:
                self.assertAlmostEqual(b[key], a[key] * 0.5, places=4)

    def test_the_rates_a_minute(self):
        r = ML.rates(self.section, STRUCTURE["seconds"])
        self.assertAlmostEqual(r["flash"], len(self.kind("flash")) * 60.0 / STRUCTURE["seconds"])
        self.assertAlmostEqual(r["glitch"], sum(e["frames"] for e in self.kind("glitch")) * 60.0 / STRUCTURE["seconds"])

    def test_the_command_writes_a_look_with_the_section(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "structure.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(STRUCTURE, f)
        base = os.path.join(folder, "base.json")
        with open(base, "w", encoding="utf-8") as f:
            json.dump({"glow": {"strength": 0.3}, "stage": {"world": 1}}, f)
        out = os.path.join(folder, "look.json")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = ML.main(["plan", path, out, "--look", base])
        result = json.loads(stream.getvalue())
        self.assertEqual(code, 0, result)
        look = mv_look.load_look(out)
        self.assertEqual(look["glow"]["strength"], 0.3)                    # the look's own values are kept
        self.assertEqual(look["mograph"]["on"], 1)
        self.assertEqual(len(look["mograph"]["events"]), result["events"])


# ---- the envelopes -------------------------------------------------------------------------------------------------

@unittest.skipUnless(ML, "needs numpy")
class EnvelopeTest(unittest.TestCase):
    def test_a_punch_is_most_of_the_way_in_on_its_first_frame_and_eases_back(self):
        values = [ML.punch_value(x, 2, 10) for x in range(-1, 13)]
        self.assertEqual(values[0], 0.0)
        self.assertGreaterEqual(values[1], 0.7)                       # the frame of the beat already shows it
        self.assertEqual(values[2], 1.0)
        falling = values[2:12]
        self.assertTrue(all(a > b for a, b in zip(falling, falling[1:])), falling)
        self.assertEqual(values[12], 0.0)

    def test_a_flash_starts_at_its_strength_and_falls(self):
        values = [ML.flash_value(x, 0.3, 6) for x in range(0, 7)]
        self.assertEqual(values[0], 0.3)
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))
        self.assertEqual(values[6], 0.0)

    def test_a_fade_goes_out_holds_and_comes_back(self):
        values = [ML.fade_value(x, 4, 2, 3) for x in range(-1, 11)]
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[4], 1.0)                              # the frame out - 1 is all colour
        self.assertEqual(values[5:7], [1.0, 1.0])                     # held
        self.assertTrue(0 < values[7] < 1 and values[7] > values[8] > values[9] > 0)
        self.assertEqual(values[10], 0.0)
        self.assertEqual(ML.fade_value(500, 4, -1, 3), 1.0)            # hold -1: to the end

    def test_a_shake_dies_away_within_its_frames(self):
        dx = [abs(ML.shake_values(x, 5.0, 10, 9.0, 30)[0]) for x in range(0, 11)]
        self.assertAlmostEqual(dx[0], 5.0)
        self.assertEqual(dx[10], 0.0)
        reach = [ML.shake_values(x, 5.0, 10, 9.0, 30)[2] for x in range(0, 10)]
        for x in range(10):
            d = ML.shake_values(x, 5.0, 10, 9.0, 30)
            self.assertLessEqual(max(abs(d[0]), abs(d[1])), reach[x] + 1e-9)    # the zoom covers every jolt

    def test_an_event_lasts_as_many_seconds_at_60_fps(self):
        for kind, values in (("punch", {"rise": 2, "fall": 10}), ("flash", {"frames": 7}), ("shake", {"frames": 10})):
            e = dict(values, kind=kind, t=1.0)
            a30, b30 = ML.event_frames(e, 30)
            a60, b60 = ML.event_frames(e, 60)
            self.assertEqual((a60, b60 + 1), (2 * a30, 2 * (b30 + 1)), kind)


# ---- the filters in mv_look's graph ------------------------------------------------------------------------------

PLAN_CUES = {"cues": [{"start": 0.5, "frames": 30, "x": 20, "y": 12, "layer": "back", "pattern": "W/cue_title/f%05d.png"},
                      {"start": 0.2, "frames": 30, "x": 16, "y": 140, "layer": "front", "pattern": "W/cue_credit/f%05d.png"}]}


@unittest.skipUnless(ML, "needs numpy")
class GraphTest(unittest.TestCase):
    def argv(self, look, **kw):
        return mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", mv_look.merge_look(look), SIZE,
                                      30, plan=PLAN_CUES, flare_pattern="W/flare_%05d.png", flare_frames=12, **kw)

    def graph(self, look, **kw):
        argv = self.argv(look, **kw)
        return argv[argv.index("-filter_complex") + 1]

    def test_off_the_argv_is_the_one_without_the_section(self):
        for look in ({}, {"flares": [1.0]}):
            self.assertEqual(self.argv(dict(look, mograph={"on": 0})), self.argv(look))

    def test_the_effects_go_between_the_camera_and_the_lens_and_the_veils_under_the_front_text(self):
        look = {"flares": [1.0], "lens": {"vignette": 0.3, "grain": 3}, "mograph": {"on": 1, "events": [
            {"kind": "punch", "t": 1.0}, {"kind": "flash", "t": 1.0}, {"kind": "fade", "t": 1.2}, {"kind": "glitch", "t": 1.1}]}}
        g = self.graph(look)
        flare_punch, persp, glitch, lens, veil, front = (g.index(p) for p in (
            "eval=frame:flags=bilinear", "perspective=", "geq=r='r(", "vignette=", "s=1x1", "overlay=x=16:y=140"))
        self.assertTrue(flare_punch < persp < glitch < lens < veil < front, (flare_punch, persp, glitch, lens, veil, front))

    def test_an_event_outside_the_excerpt_adds_nothing(self):
        look = {"mograph": {"on": 1, "events": [{"kind": "punch", "t": 5.0}, {"kind": "flash", "t": 5.0}]}}
        g = self.graph(look, start=1.0, duration=1.0)
        self.assertNotIn("perspective", g)
        self.assertNotIn("s=1x1", g)
        self.assertIn("perspective", self.graph(look, start=4.5, duration=1.0))

    def test_an_event_that_began_before_the_excerpt_goes_on_from_its_frame(self):
        # a punch at 1.0 s seen from an excerpt from 1.1 s: three frames of it are spent
        g = self.graph({"mograph": {"on": 1, "events": [{"kind": "punch", "t": 1.0}]}}, start=1.1, duration=1.0)
        self.assertIn("((in-1)+3)", g)
        self.assertIn("between(n,0,", g)

    def test_a_dissolve_needs_the_frame_before_it_in_the_excerpt(self):
        look = {"mograph": {"on": 1, "events": [{"kind": "dissolve", "t": 1.0}]}}
        with self.assertRaises(ValueError):
            self.graph(look, start=1.0, duration=1.0)                  # it holds the frame at 0.967 s
        self.assertIn("trim=start_frame=0:end_frame=1", self.graph(look, start=1.0 - 1 / 30.0, duration=1.0))

    def test_punches_of_one_render_share_their_centre(self):
        look = {"mograph": {"on": 1, "events": [{"kind": "punch", "t": 1.0}, {"kind": "punch", "t": 1.5, "centre": [0.4, 0.4]}]}}
        with self.assertRaises(ValueError):
            self.graph(look)

    def test_particles_need_their_frames(self):
        look = {"stage": {"world": 1}, "mograph": {"on": 1, "particles": {"specks": 5}}}
        with self.assertRaises(ValueError):
            mv_look.ffmpeg_command("fg.avi", "out.mp4", None, None, mv_look.merge_look(look), SIZE, 30,
                                   stage={"pattern": "W/stage/stage_%05d.png", "first": 12}, start=0.4, duration=0.6)
        argv = mv_look.ffmpeg_command("fg.avi", "out.mp4", None, None, mv_look.merge_look(look), SIZE, 30,
                                      stage={"pattern": "W/stage/stage_%05d.png", "first": 12}, start=0.4, duration=0.6,
                                      particles={"back": "W/mograph/back_%05d.png", "front": "W/mograph/front_%05d.png",
                                                 "first": 12})
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs[-2:], ["W/mograph/back_%05d.png", "W/mograph/front_%05d.png"])
        g = argv[argv.index("-filter_complex") + 1]
        self.assertLess(g.index("[mg_back_on]"), g.index("[fg]overlay"))          # behind her
        self.assertGreater(g.index("[mg_front_on]"), g.index("[fg]overlay"))       # in front of her

    def test_a_graph_too_long_for_the_command_line_goes_into_a_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        events = [{"kind": "shake", "t": 0.5 * k} for k in range(1, 200)]
        argv = self.argv({"mograph": {"on": 1, "events": events}})
        self.assertGreater(sum(len(a) + 3 for a in argv), ML.ARGV_MOST)
        short = ML.long_argv(argv, os.path.join(folder, "graph.txt"))
        self.assertIn("-/filter_complex", short)
        self.assertNotIn("-filter_complex", short)
        with open(os.path.join(folder, "graph.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), argv[argv.index("-filter_complex") + 1])
        small = self.argv({"mograph": {"on": 1, "events": events[:2]}})
        self.assertEqual(ML.long_argv(small, os.path.join(folder, "other.txt")), small)


# ---- the real thing ------------------------------------------------------------------------------------------------

def make_dancer(path, moving=False, fps=30, frames=45):
    """an uncompressed BGRA AVI as MMD writes one: a white box 80 px wide (still, at x 120..200), or one 40 px wide moving 4 px a
    frame from x 40"""
    if moving:
        graph = ("color=c=black@0.0:s=%dx%d:r=%d,format=rgba[bg];color=c=white:s=40x100:r=%d,format=rgba[box];"
                 "[bg][box]overlay=x='40+%d*t':y=40:format=auto,format=rgba" % (SIZE + (fps, fps, 4 * fps)))
    else:
        graph = ("color=c=black@0.0:s=%dx%d:r=%d,format=rgba,drawbox=x=120:y=30:w=80:h=120:color=white@1.0:t=fill:replace=1"
                 % (SIZE + (fps,)))
    rate = "10000000/333333" if fps == 30 else str(fps)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-frames:v", str(frames), "-r", rate,
                    "-c:v", "rawvideo", "-pix_fmt", "bgra", path], check=True, stdin=subprocess.DEVNULL)
    return path


def read_frames(path, size=SIZE):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True,
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    n = size[0] * size[1] * 3
    return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).reshape(size[1], size[0], 3).astype(numpy.float64)
            for i in range(len(raw) // n)]


def luma(img):
    return (img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722) / 255.0


def box_columns(img, row=90, least=200):
    cols = numpy.nonzero(img[row].min(axis=1) > least)[0]
    return (int(cols.min()), int(cols.max())) if cols.size else None


def render(folder, name, look, dancer, *extra):
    path = os.path.join(folder, name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(look, f)
    out = os.path.join(folder, name + ".mp4")
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = mv_look.main(["render", dancer, path, out, "--work", os.path.join(folder, name + "_work")] + list(extra))
    result = json.loads(stream.getvalue())
    if code != 0:
        raise AssertionError(result)
    return out


@unittest.skipUnless(ML and FFMPEG, "needs numpy, Pillow, ffmpeg and ffprobe")
class RenderTest(unittest.TestCase):
    """the effects in the picture mv_look renders: a white box (the dancer) over a grey plate, 1.5 s"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.still = make_dancer(os.path.join(cls.folder, "still.avi"))
        cls.moving = make_dancer(os.path.join(cls.folder, "moving.avi"), moving=True)
        cls.plain = read_frames(render(cls.folder, "plain", picture_look(), cls.still))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self, name, events, dancer=None, **mograph):
        return read_frames(render(self.folder, name, picture_look(events=events, **mograph), dancer or self.still))

    def test_a_punch_zooms_in_on_its_frame_and_comes_back(self):
        frames = self.frames("punch", [{"kind": "punch", "t": 0.5, "amount": 0.2, "centre": [0.5, 0.5]}])
        widths = [box_columns(f)[1] - box_columns(f)[0] + 1 for f in frames]
        self.assertAlmostEqual(widths[14], 80, delta=1)                 # the frame before: as it was
        self.assertAlmostEqual(widths[15], 80 * 1.15, delta=2)          # frame 15 = 0.5 s: three quarters of the way
        self.assertAlmostEqual(widths[16], 80 * 1.2, delta=2)
        self.assertAlmostEqual(widths[26], 80, delta=1)                 # back after rise + fall
        self.assertTrue(all(a >= b - 1 for a, b in zip(widths[16:26], widths[17:27])), widths[16:27])
        centre = [sum(box_columns(f)) / 2.0 for f in frames]
        self.assertAlmostEqual(centre[16], centre[10], delta=1)         # about the middle of the picture

    def test_a_shake_jolts_the_picture_and_dies_away(self):
        frames = self.frames("shake", [{"kind": "shake", "t": 0.5, "amount": 20.0, "frames": 10}])
        centre = [sum(box_columns(f)) / 2.0 for f in frames]
        self.assertAlmostEqual(centre[14], centre[10], delta=0.6)
        self.assertGreater(abs(centre[15] - centre[10]), 3.5)           # 20 px of a 720 line picture: 5 px here
        self.assertAlmostEqual(centre[25], centre[10], delta=0.6)       # still after its 10 frames

    def test_a_flash_lifts_the_picture_towards_white_and_falls(self):
        frames = self.frames("flash", [{"kind": "flash", "t": 0.5, "strength": 0.4, "frames": 6}])
        y = [float(luma(f)[:, :100].mean()) for f in frames]
        base = y[10]
        self.assertAlmostEqual(y[14], base, delta=0.01)
        self.assertAlmostEqual(y[15] - base, 0.4 * (1 - base), delta=0.04)
        self.assertTrue(y[15] > y[16] > y[17] > y[18] > y[20] - 0.005, y[14:22])
        self.assertAlmostEqual(y[21], base, delta=0.01)
        # over the whole picture alike on every frame of it: drawn 2 x 2, ffmpeg 8.0 left a quarter unlit from the second frame on
        for k in range(15, 20):
            quarters = [float(luma(frames[k])[r, c].mean() - luma(frames[10])[r, c].mean())
                        for r in (slice(0, 90), slice(90, 180)) for c in (slice(0, 100), slice(220, 320))]
            self.assertLess(max(quarters) - min(quarters), 0.02, (k, quarters))

    def test_a_fade_goes_to_black_holds_and_comes_back(self):
        frames = self.frames("fade", [{"kind": "fade", "t": 0.5, "out": 6, "hold": 3, "back": 6}])
        y = [float(luma(f).mean()) for f in frames]
        self.assertGreater(y[14], 0.2)
        self.assertLess(max(y[20:24]), 0.03)                            # out over 6 frames: black from 20, held to 23
        self.assertAlmostEqual(y[30], y[10], delta=0.01)
        held = self.frames("fade_end", [{"kind": "fade", "t": 0.5, "out": 6, "hold": -1}])
        self.assertLess(max(float(luma(f).mean()) for f in held[20:]), 0.03)     # hold -1: black to the end

    def test_a_dissolve_holds_the_frame_before_and_fades_it_out(self):
        frames = self.frames("dissolve", [{"kind": "dissolve", "t": 0.5, "frames": 6}], dancer=self.moving)
        # the box moves 4 px a frame from x 40: on frame 14 it covers 96..135, on frame 15 100..139.  Column 97 is the held
        # box's alone from frame 15 on
        col = [float(f[60:120, 97].mean()) for f in frames]
        ground = float(frames[30][60:120, 97].mean())
        self.assertGreater(col[14], 240)                                  # the live box
        self.assertAlmostEqual(col[15], ground + (255 - ground) * 6 / 7.0, delta=12)
        self.assertAlmostEqual(col[20], ground + (255 - ground) * 1 / 7.0, delta=12)
        self.assertAlmostEqual(col[21], ground, delta=4)
        self.assertTrue(col[15] > col[17] > col[19] > col[21])

    @unittest.skipUnless(MA, "needs OpenCV and SciPy (tools/mograph_analyze.py)")
    def test_a_glitch_parts_red_from_blue_on_its_frames_only(self):
        event = {"kind": "glitch", "t": 0.5, "frames": 2, "split": 16.0, "bands": 3, "shift": 40.0}
        frames = self.frames("glitch", [event])
        split = [MA._split(f / 255.0, reach=12) for f in frames]
        self.assertLess(max(split[:15] + split[17:]), 0.5)
        planned = {frame: s for frame, s, _ in ML.glitch_frames(dict(ML.DEFAULTS["glitch"], **event), 30, SIZE)}
        for k in (15, 16):
            # red one way and blue the other by the frame's split: twice it between them (px of this picture)
            self.assertAlmostEqual(split[k], 2 * planned[k], delta=1.5, msg=(k, split[k], planned[k]))
            self.assertGreater(split[k] * 720.0 / SIZE[1], 8.0)          # tools/mograph_analyze.py's glitch frame

    def test_an_excerpt_shows_what_the_whole_render_shows_on_its_frames(self):
        events = [{"kind": "punch", "t": 0.5, "amount": 0.2}, {"kind": "flash", "t": 0.55, "frames": 7},
                  {"kind": "shake", "t": 0.6, "amount": 16.0}]
        whole = self.frames("whole", events)
        part = read_frames(render(self.folder, "part", picture_look(events=events), self.still, "--from", "0.6", "--to", "1.2"))
        self.assertEqual(len(part), 18)
        for k in range(len(part)):
            self.assertLess(float(numpy.abs(part[k] - whole[18 + k]).mean()), 1.5, k)

    def test_the_effects_last_as_many_seconds_at_60_fps(self):
        d60 = make_dancer(os.path.join(self.folder, "still60.avi"), fps=60, frames=90)
        events = [{"kind": "punch", "t": 0.5, "amount": 0.2}]
        f30 = self.frames("punch30", events)
        f60 = read_frames(render(self.folder, "punch60", picture_look(events=events), d60))
        self.assertEqual(len(f60), 90)
        for k in (14, 16, 20, 25, 27):
            w30 = box_columns(f30[k])[1] - box_columns(f30[k])[0]
            w60 = box_columns(f60[2 * k + 1])[1] - box_columns(f60[2 * k + 1])[0]
            self.assertAlmostEqual(w60, w30, delta=2, msg=k)


@unittest.skipUnless(ML and FFMPEG and MA, "needs numpy, Pillow, ffmpeg, OpenCV and SciPy")
class AnalyzerTest(unittest.TestCase):
    """tools/mograph_analyze.py, the measure of the references, reads our effects as it read theirs (laid over a still
    picture with detail all over, as an MV's is: a flat grey plate gives the optical flow nothing to follow, and a test
    pattern that moves by itself gives it motion of its own)"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        rng = numpy.random.default_rng(1)
        # a soft ground with grey blocks of all sizes, the three channels going together as a picture's do: the optical flow
        # has edges to follow all over (and a punch of 12 % must not read as a cut)
        from PIL import ImageDraw
        ground = Image.fromarray((rng.random((22, 40)) * 255).astype(numpy.uint8)).resize(SIZE, Image.BICUBIC)
        grey = Image.fromarray((numpy.clip(0.45 + 0.25 * (numpy.asarray(ground, dtype=numpy.float64) / 255.0 - 0.5), 0, 1)
                                * 255).astype(numpy.uint8))
        draw = ImageDraw.Draw(grey)
        for k in range(40):
            x, y = int(rng.random() * (SIZE[0] - 20)), int(rng.random() * (SIZE[1] - 15))
            draw.rectangle([x, y, x + 6 + int(rng.random() * 34), y + 6 + int(rng.random() * 40)], fill=int(rng.random() * 255))
        picture = numpy.asarray(grey, dtype=numpy.float64) / 255.0
        still = Image.fromarray((picture[..., None] * numpy.array([[[0.9, 0.8, 1.0]]]) * 255).astype(numpy.uint8))
        png = os.path.join(cls.folder, "still.png")
        still.save(png)
        video = os.path.join(cls.folder, "source.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-i", png, "-frames:v", "90",
                        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709",
                        "-c:v", "libx264", "-crf", "12", video], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"mograph": {"on": 1, "events": [{"kind": "punch", "t": 0.7, "amount": 0.12}, {"kind": "flash", "t": 1.5},
                                                       {"kind": "glitch", "t": 2.2, "frames": 1, "split": 8.0}]}}, f)
        cls.video = os.path.join(cls.folder, "events.mp4")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = ML.main(["apply", video, look, cls.video])
        cls.events = MA.events_video(cls.video, size=(128, 72)) if cls.code == 0 else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_the_punch_and_the_flash_are_found_on_their_frames_and_nothing_reads_as_a_cut(self):
        # (the glitch's red and blue part by 4 to 6 px of this 180 line picture: read at 128 x 72, the measure's size, the chroma
        # of a picture this small blurs them together; RenderTest reads it at full size, the previews at 1280 x 720)
        self.assertEqual(self.code, 0)
        self.assertEqual(len(self.events["punches"]), 1, self.events["punches"])
        self.assertAlmostEqual(self.events["punches"][0]["frame"], 21, delta=1)
        self.assertAlmostEqual(self.events["punches"][0]["log_scale"], math.log(1.12), delta=0.01)
        self.assertEqual([f["start"] for f in self.events["flashes"]], [45])
        self.assertEqual(self.events["cuts"], [])


# ---- the particles -------------------------------------------------------------------------------------------------

def world_look(**particles):
    return mv_look.merge_look({"stage": {"world": 1, "dof": 0.0}, "mograph": {"on": 1, "particles": dict(
        {"specks": 40, "lights": 10, "seed": 3}, **particles)}})


def one_particle(look, point, kind="speck"):
    """a field of the look's section with its first particle of `kind` standing still at `point` and every other one gone"""
    field = ML.Field(look["mograph"])
    i = list(field.kind).index(kind)
    keep = numpy.zeros(len(field.kind), bool)
    keep[i] = True
    for name in ("kind", "rank", "start", "velocity", "sway", "sway_hz", "phase", "radius", "bright", "twinkle_hz",
                 "twinkle_phase", "colour"):
        setattr(field, name, getattr(field, name)[keep])
    for name in ("lo", "size"):
        setattr(field, name, getattr(field, name)[keep])
    field.start[0] = numpy.array(point, float)
    field.lo[0] = field.start[0] - 50.0                     # a box of its own round it: no face (and no fade) near
    field.size[0] = 100.0
    field.velocity[0] = 0.0
    field.sway[0] = 0.0
    field.twinkle_hz[0] = 0.0
    field.twinkle_phase[0] = math.pi / 2
    field.bright[0] = 0.9
    field.base = {"speck": 1 if kind == "speck" else 0, "light": 1 if kind == "light" else 0}
    field.rank[0] = 0.0
    return field


def view(eye_x=0.0, size=SIZE):
    """a camera 38 in front of the stage centre (as the reference of tools/mv_world.py), moved sideways by eye_x"""
    WT = ML.world_tool()
    return WT.View(fk.CameraState(0, (eye_x, 13.0, 0.0), 38.0, (0.0, 0.0, 0.0), 30.0), size)


@unittest.skipUnless(ML, "needs numpy")
class ParticleTest(unittest.TestCase):
    def test_the_same_seed_gives_the_same_particles_and_they_stay_in_their_box(self):
        look = world_look()
        a, b = ML.Field(look["mograph"]), ML.Field(look["mograph"])
        for t in (0.0, 37.5, 2500.0):
            pa, wa = a.at(t)
            pb, wb = b.at(t)
            self.assertTrue(numpy.array_equal(pa, pb) and numpy.array_equal(wa, wb))
            for kind, name in (("speck", "box"), ("light", "light_box")):
                box = look["mograph"]["particles"][name]
                mine = pa[a.kind == kind]
                self.assertTrue(len(mine) > 0)
                self.assertTrue(((mine >= numpy.array(box[:3])) & (mine <= numpy.array(box[3:]))).all(), (t, kind))
        other = ML.Field(world_look(seed=4)["mograph"])
        self.assertFalse(numpy.array_equal(other.at(1.0)[0], a.at(1.0)[0]))

    def test_they_drift_slowly(self):
        field = ML.Field(world_look()["mograph"])
        p0, w0 = field.at(10.0)
        p1, _ = field.at(10.0 + 1 / 30.0)
        step = numpy.linalg.norm(p1 - p0, axis=1)
        self.assertLess(float(numpy.median(step[w0 > 0])), 0.1)       # units a frame: a speck of dust, not a spark

    def test_the_busy_spans_bring_more_of_them(self):
        quiet = world_look()
        busy = mv_look.merge_look({"stage": {"world": 1}, "mograph": dict(quiet["mograph"], busy=[[10.0, 20.0, 2.0]])})
        field = ML.Field(busy["mograph"])
        shown = lambda t: float((field.at(t)[1] > 0).sum())             # noqa: E731
        self.assertAlmostEqual(shown(15.0) / shown(30.0), 2.0, delta=0.3)
        self.assertGreater(shown(9.5), shown(30.0))                     # coming in over a second
        self.assertLess(shown(9.5), shown(15.0))

    def test_the_dancers_place_is_kept_clear(self):
        field = ML.Field(world_look(specks=400, lights=0)["mograph"])
        for t in (0.0, 12.0, 40.0):
            p, w = field.at(t)
            r = numpy.hypot(p[:, 0], p[:, 2] + 5.0)
            self.assertFalse(((r < 8.0) & (p[:, 1] < 24.0) & (w > 0)).any(), t)

    def test_one_nearer_than_the_dancer_goes_in_front_and_one_beyond_her_behind(self):
        look = world_look()
        for z, side in ((-28.0, 1), (30.0, 0)):                       # the camera's eye at z -38, the dancer at 0
            field = one_particle(look, (2.0, 12.0, z))
            layers = field.draw(view(), 0.0, look, SIZE)
            self.assertGreater(float(layers[side][..., 3].max()), 80, z)
            self.assertEqual(float(layers[1 - side][..., 3].max()), 0.0, z)

    def test_one_in_front_never_covers_her_by_more_than_its_cap(self):
        look = world_look(front=0.3)
        field = one_particle(look, (0.0, 13.0, -30.0), kind="light")
        _, front = field.draw(view(), 0.0, look, SIZE)
        self.assertLessEqual(float(front[..., 3].max()), 0.3 * 255 + 1)

    def test_they_lie_in_the_world_so_a_near_one_moves_more_than_a_far_one(self):
        look = world_look()
        near, far = one_particle(look, (2.0, 13.0, -20.0)), one_particle(look, (2.0, 13.0, 60.0))

        def where(field, eye_x):
            layer = sum(field.draw(view(eye_x), 0.0, look, SIZE))
            a = layer[..., 3]
            ys, xs = numpy.nonzero(a > 0.5 * a.max())
            return float(xs.mean())
        focal = SIZE[1] / 2.0 / math.tan(math.radians(15.0))
        for field, d in ((near, 18.0), (far, 98.0)):
            # the camera moved 3 to the right: a point d in front of it goes 3 x focal / d to the left on the picture
            moved = where(field, 3.0) - where(field, 0.0)
            self.assertAlmostEqual(moved, -3.0 * focal / d, delta=1.0)

    def test_the_depth_of_field_blurs_one_far_from_the_focus_into_a_disc(self):
        sharp, soft = world_look(), mv_look.merge_look({"stage": {"world": 1, "dof": 6.5}, "mograph": world_look()["mograph"]})
        point = (4.0, 14.0, 100.0)
        spread = []
        for look in (sharp, soft):
            back = one_particle(look, point, kind="light").draw(view(size=(1280, 720)), 0.0, look, (1280, 720))[0]
            spread.append(int((back[..., 3] > 10).sum()))
        self.assertGreater(spread[1], 2 * spread[0])                    # 6.5 px far away: 4.7 px at 138 from the eye

    @unittest.skipUnless(MA, "needs OpenCV and SciPy (tools/mograph_analyze.py)")
    def test_the_measure_of_the_references_counts_them_as_particles(self):
        look = world_look(specks=120, lights=0)
        field = ML.Field(look["mograph"])
        back, front = field.draw(view(size=(640, 360)), 3.0, look, (640, 360))
        card = numpy.full((360, 640, 3), 20.0)
        for layer in (back, front):
            a = layer[..., 3:] / 255.0
            card = card * (1 - a) + layer[..., :3] * a
        found = MA.particles(card / 255.0, unit=0.5)["particle.count"]
        p, w = field.at(3.0)
        u, v, depth = view(size=(640, 360)).project(p)
        inside = (depth > 8) & (u > 2) & (u < 638) & (v > 2) & (v < 358)
        bright = int((inside & (w * field.bright > 0.3)).sum())      # those well above the analyzer's 0.12 of Y'
        self.assertGreater(found, 0.6 * bright)
        self.assertLessEqual(found, int((inside & (w > 0)).sum()) + 2)

    @unittest.skipUnless(MA, "needs OpenCV and SciPy (tools/mograph_analyze.py)")
    def test_the_lights_far_behind_her_read_as_bokeh_and_most_of_them_show(self):
        # (the light box of 2026-10-21's first two tries lay above the frame of the fixed front camera, which looks down on
        # her: 9 of 40 in the picture, and so faint, 0.2 at most, that the measure found 3)
        look = mv_look.merge_look({"stage": {"world": 1, "dof": 6.5}, "mograph": {"on": 1, "particles": {"specks": 0, "lights": 40}}})
        field = ML.Field(look["mograph"])
        size = (1280, 720)
        down = fk.CameraState(0, (0.0, 12.0, 0.0), 45.0, (16.0, 0.0, 0.0), 30.0)     # the window's degrees: looking down 16
        for camera in (view(size=size), ML.world_tool().View(down, size)):
            p, w = field.at(3.0)
            u, v, depth = camera.project(p)
            inside = (depth > 8) & (u > 20) & (u < 1260) & (v > 20) & (v < 700) & (w > 0.5)
            self.assertGreater(int(inside.sum()), 0.5 * len(p))
            back, front = field.draw(camera, 3.0, look, size)
            card = numpy.full((720, 1280, 3), 20.0)
            for layer in (back, front):
                a = layer[..., 3:] / 255.0
                card = card * (1 - a) + layer[..., :3] * a
            read = MA.particles(card / 255.0)
            self.assertGreater(read["particle.count"], 0.6 * int(inside.sum()))
            self.assertGreater(read["particle.bokeh"], 0.7)


@unittest.skipUnless(ML, "needs numpy and Pillow")
class ParticleFramesTest(unittest.TestCase):
    """write_particles and mv_look's render and prepare with particles (ffmpeg stood in for)"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        keys = []
        for frame in range(60):
            values = {"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, -10.0 + 20.0 * frame / 59.0, 0.0), "fov": 30,
                      "perspective": True}
            keys.append(motion_edit.camera_key_from_ui(values, frame=frame))
        self.camera = os.path.join(self.folder, "camera.vmd")
        with open(self.camera, "wb") as f:
            f.write(vmd.dumps(vmd.Motion.for_camera(cameras=keys)))
        self.look = os.path.join(self.folder, "look.json")
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump({"stage": {"world": 1}, "beams": {"loop_seconds": 1}, "mograph": {"on": 1, "particles": {
                "specks": 30, "lights": 6}, "events": [{"kind": "flash", "t": 0.5}]}}, f)
        self.fg = os.path.join(self.folder, "fg.avi")
        open(self.fg, "wb").close()
        self.work = os.path.join(self.folder, "work")
        share = unittest.mock.patch.object(mv_look, "floor_share", return_value=0.0)
        share.start()
        self.addCleanup(share.stop)

    def run_tool(self, argv):
        calls = []

        def fake(cmd, **kw):
            calls.append(list(cmd))
            if cmd[0] == "ffmpeg" and cmd[-1] not in ("-", "NUL"):
                with open(cmd[-1], "wb") as f:
                    f.write(b"mp4")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        stream = io.StringIO()
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake), contextlib.redirect_stdout(stream):
            code = mv_look.main(argv)
        return code, json.loads(stream.getvalue()), [c for c in calls if c[0] == "ffmpeg"]

    def render(self, *extra):
        return self.run_tool(["render", self.fg, self.look, os.path.join(self.folder, "out.mp4"), "--size", "320x180", "--fps",
                              "30", "--offset", "0.2", "--from", "0.4", "--to", "1.0", "--camera", self.camera] + list(extra))

    def test_a_render_draws_the_particles_of_its_excerpt_and_reads_them_from_its_first_frame(self):
        code, result, calls = self.render("--work", self.work)
        self.assertEqual(code, 0, result)
        names = sorted(os.listdir(os.path.join(self.work, "mograph")))
        self.assertEqual(names, sorted(["back_%05d.png" % n for n in range(12, 30)] + ["front_%05d.png" % n for n in range(12, 30)]))
        argv = calls[-1]
        for side in ("back", "front"):
            pattern = os.path.join(self.work, "mograph", side + "_%05d.png").replace("\\", "/")
            self.assertEqual(argv[argv.index(pattern) - 3:argv.index(pattern) - 1], ["-start_number", "12"])

    def test_prepare_draws_them_with_the_stage_and_render_prepared_reads_them_and_writes_nothing(self):
        code, result, _ = self.run_tool(["prepare", self.look, self.work, "--size", "320x180", "--fps", "30", "--camera",
                                         self.camera, "--from", "0.4", "--to", "1.0"])
        self.assertEqual(code, 0, result)
        self.assertEqual(len([n for n in os.listdir(os.path.join(self.work, "mograph")) if n.startswith("back_")]), 18)
        before = sorted(os.listdir(os.path.join(self.work, "mograph")))
        code, result, calls = self.render("--prepared", self.work)
        self.assertEqual(code, 0, result)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "mograph"))), before)
        os.remove(os.path.join(self.work, "mograph", "front_00020.png"))
        code, result, calls = self.render("--prepared", self.work)
        self.assertEqual(code, 2, result)                               # a frame of the particles is missing

    def test_jobs_draw_the_same_particles(self):
        code, one, _ = self.run_tool(["prepare", self.look, self.work, "--size", "320x180", "--fps", "30", "--camera",
                                      self.camera, "--from", "0.4", "--to", "1.0"])
        self.assertEqual(code, 0, one)
        folder = os.path.join(self.work, "mograph")

        def contents():
            found = {}
            for name in os.listdir(folder):
                with open(os.path.join(folder, name), "rb") as f:
                    found[name] = f.read()
            return found
        drawn = contents()
        code, two, _ = self.run_tool(["prepare", self.look, self.work, "--size", "320x180", "--fps", "30", "--camera",
                                      self.camera, "--from", "0.4", "--to", "1.0", "--jobs", "2"])
        self.assertEqual(code, 0, two)
        self.assertEqual(contents(), drawn)


@unittest.skipUnless(ML and FFMPEG, "needs numpy, Pillow, ffmpeg and ffprobe")
class WorldParticlesRenderTest(unittest.TestCase):
    """end to end: the particles over the stage in the world, behind and in front of a white box"""

    def test_the_particles_show_round_her_and_she_stays_white(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        keys = [motion_edit.camera_key_from_ui({"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, 0.0, 0.0), "fov": 30,
                                                 "perspective": True}, frame=f) for f in range(30)]
        camera = os.path.join(folder, "camera.vmd")
        with open(camera, "wb") as f:
            f.write(vmd.dumps(vmd.Motion.for_camera(cameras=keys)))
        dancer = make_dancer(os.path.join(folder, "still.avi"), frames=30)
        base = {"stage": {"world": 1, "radius": 0, "floor": 1}, "plate": {"vignette": 0}, "beams": {"count": 0, "loop_seconds": 1},
                "bokeh": {"count": 0}, "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0}}
        with_particles = dict(base, mograph={"on": 1, "particles": {"specks": 150, "lights": 0, "brightness": 2.0}})
        bare = read_frames(render(folder, "bare", base, dancer, "--camera", camera))
        lit = read_frames(render(folder, "lit", with_particles, dancer, "--camera", camera))
        self.assertEqual(len(lit), 30)
        sky = (slice(0, 25), slice(0, 320))                           # above her and the floor: the cyc
        self.assertGreater(float(numpy.abs(lit[10][sky] - bare[10][sky]).max()), 60)
        self.assertGreater(float(lit[10][40:140, 125:195].min()), 230)   # she is in front of the ones behind


@unittest.skipUnless(ML and FFMPEG, "needs numpy, Pillow, ffmpeg and ffprobe")
class ApplyTest(unittest.TestCase):
    def test_an_excerpt_of_a_finished_video_starts_on_its_own_frame(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        video = os.path.join(folder, "moving.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                        "color=c=0x202020:s=%dx%d:r=30[bg];color=c=white:s=8x60:r=30[box];[bg][box]overlay=x='8+4*n':y=60"
                        % SIZE, "-frames:v", "70", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", video],
                       check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"mograph": {"on": 1, "events": [{"kind": "flash", "t": 0.1}]}}, f)        # (before the excerpt)
        whole = read_frames(video)
        for start, to in (("1.0", "1.5"), ("0.7", "1.2"), ("1.3333333", "1.9")):
            out = os.path.join(folder, "part_%s.mp4" % start)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ML.main(["apply", video, look, out, "--from", start, "--to", to]), 0)
            part = read_frames(out)
            first = int(round(float(start) * 30))
            self.assertEqual(len(part), int(round(float(to) * 30)) - first, start)
            for k in (0, len(part) - 1):
                self.assertEqual(box_columns(part[k], row=90, least=150), box_columns(whole[first + k], row=90, least=150), start)

    def test_an_excerpt_reads_its_own_frames_where_the_frames_lie_a_hair_early(self):
        # (v7's frames from 40 s on lie a third of a millisecond before their times: its excerpt 40-60 s read 601 frames, the
        # last one 60.0 s's, and every effect after it came a frame late in the whole song laid in excerpts; 2026-10-21)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        video = os.path.join(folder, "early.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                        "color=c=0x202020:s=%dx%d:r=30[bg];color=c=white:s=8x60:r=30[box];[bg][box]overlay=x='8+4*n':y=60,"
                        "settb=1/15360,setpts='N*512-gte(N,30)*5'[v];sine=frequency=440:sample_rate=48000:duration=3[a]" % SIZE,
                        "-map", "[v]", "-map", "[a]", "-frames:v", "70", "-fps_mode", "passthrough", "-enc_time_base:v", "1/15360",
                        "-video_track_timescale", "15360", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", "-c:a", "aac", video],
                       check=True, stdin=subprocess.DEVNULL)
        pts = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts", "-of", "csv=p=0",
                              video], capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout.split()
        self.assertEqual(pts[29:31], ["14848", "15355"])                 # (the frames from 1 s on lie 5 ticks early)
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"mograph": {"on": 1, "events": [{"kind": "flash", "t": 2.2}]}}, f)        # (after the excerpts)
        whole = read_frames(video)
        for start, to in (("0.0", "1.0"), ("0.5", "1.0"), ("0.2", "1.5"), ("1.1", "1.6")):
            out = os.path.join(folder, "part_%s.mp4" % start)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ML.main(["apply", video, look, out, "--from", start, "--to", to]), 0)
            part = read_frames(out)
            first = int(round(float(start) * 30))
            want = int(round(float(to) * 30)) - first
            self.assertEqual(len(part), want, start)
            for k in (0, len(part) - 1):
                self.assertEqual(box_columns(part[k], row=90, least=150), box_columns(whole[first + k], row=90, least=150), start)
            # the sound of the same span (within a frame)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of",
                                    "csv=p=0", out], capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout
            self.assertAlmostEqual(float(probe.strip()), want / 30.0, delta=1.5 / 30.0, msg=start)

    def test_a_shake_over_a_finished_video_never_shows_past_its_edges(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        video = os.path.join(folder, "framed.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=%dx%d:r=30" % SIZE, "-vf",
                        "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=3,format=yuv420p", "-frames:v", "45", "-c:v", "libx264",
                        "-crf", "12", video], check=True, stdin=subprocess.DEVNULL)
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"mograph": {"on": 1, "events": [{"kind": "shake", "t": 0.5, "amount": 40.0, "frames": 10}]}}, f)
        out = os.path.join(folder, "shaken.mp4")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = ML.main(["apply", video, look, out])
        self.assertEqual(code, 0, stream.getvalue())
        frames = read_frames(out)
        self.assertEqual(len(frames), 45)
        self.assertGreater(float(frames[10][:, :2].mean()), 200)         # the white frame of the picture, before
        for k in (15, 16, 17):
            # the picture is zoomed in as far as the jolt goes: the white frame slides out and nothing past the picture's edge
            # (the edge smeared) slides in.  Without the zoom the first jolt (10 px here) shows 10 white columns at the left
            for edge in (frames[k][:, :6], frames[k][:, -6:], frames[k][:6], frames[k][-6:]):
                self.assertLess(float((edge.min(axis=-1) > 200).mean()), 0.5, k)


if __name__ == "__main__":
    unittest.main()
