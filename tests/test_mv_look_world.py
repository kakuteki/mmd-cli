"""tools/mv_look.py with the look setting "stage": {"world": 1}: the stage of tools/mv_world.py (drawn from the camera motion,
with a floor of its own) takes the place of the plate and the light fixed to the picture."""
import contextlib
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
    from PIL import Image  # noqa: F401
except ImportError:                                   # the tool needs Pillow and numpy; the rest of the suite does not
    numpy = None

if numpy is not None:
    import sys
    sys.path.insert(0, ROOT)
    from mmd_cli import motion_edit
    from mmd_cli.formats import vmd


def load_tool():
    spec = importlib.util.spec_from_file_location("mv_look", os.path.join(ROOT, "tools", "mv_look.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_look = load_tool() if numpy is not None else None
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
SIZE = (320, 180)


def camera_file(path, last, y0, y1):
    """a camera motion with a key on every frame 0..last, orbiting at distance 40 from Y angle y0 to y1"""
    keys = []
    for frame in range(last + 1):
        t = frame / float(max(1, last))
        values = {"distance": 40.0, "pos": (0.0, 12.0, 0.0), "rot": (0.0, y0 + (y1 - y0) * t, 0.0), "fov": 30, "perspective": True}
        keys.append(motion_edit.camera_key_from_ui(values, frame=frame))
    with open(path, "wb") as f:
        f.write(vmd.dumps(vmd.Motion.for_camera(cameras=keys)))
    return path


class FakeRun:
    """subprocess.run inside mv_look: records each argv and writes the file ffmpeg would"""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "ffmpeg" and argv[-1] not in ("-", "NUL"):
            with open(argv[-1], "wb") as f:
                f.write(b"mp4")
        return subprocess.CompletedProcess(argv, 0, "", "")


def answer(argv):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = mv_look.main(argv)
    return code, json.loads(stream.getvalue())


def listing(folder):
    found = {}
    for top, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(top, name)
            found[os.path.relpath(path, folder)] = (os.path.getsize(path), os.stat(path).st_mtime_ns)
    return found


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class WorldArgvTest(unittest.TestCase):
    PLAN = {"cues": [{"start": 0.5, "frames": 30, "x": 20, "y": 12, "layer": "back", "pattern": "W/cue_t/f%05d.png"}]}

    def test_the_stage_frames_take_the_place_of_the_plate_and_the_light(self):
        look = mv_look.merge_look({"stage": {"world": 1}, "flares": [0.6]})
        argv = mv_look.ffmpeg_command("fg.avi", "out.mp4", None, None, look, SIZE, 30, plan=self.PLAN,
                                      flare_pattern="W/flare_%05d.png", flare_frames=12, start=1.2, duration=1.0,
                                      stage={"pattern": "W/stage/stage_%05d.png", "first": 36})
        inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
        self.assertEqual(inputs[:2], ["fg.avi", "W/stage/stage_%05d.png"])
        self.assertNotIn("-stream_loop", argv)                        # no loop of light: every frame of the stage is its own
        at = argv.index("W/stage/stage_%05d.png")
        self.assertEqual(argv[at - 5:at], ["-framerate", "30", "-start_number", "36", "-i"])
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertTrue(graph.startswith("[1:v]format=gbrp[stage];"), graph[:80])
        self.assertNotIn("blend=all_mode=screen[stage]", graph)
        self.assertIn("[2:v]format=rgba", graph)                     # the cue is the third input now

    def test_a_look_fixed_to_the_picture_takes_no_stage(self):
        look = mv_look.merge_look({})
        with self.assertRaises(ValueError):
            mv_look.ffmpeg_command("fg.avi", "out.mp4", "W/plate.png", "W/light_%05d.png", look, SIZE, 30,
                                   stage={"pattern": "W/stage/stage_%05d.png", "first": 0})


@unittest.skipUnless(mv_look, "needs Pillow and numpy")
class WorldCommandTest(unittest.TestCase):
    """the commands with a world look, ffmpeg stood in for: what they need, what they draw, what they hand ffmpeg"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.camera = camera_file(os.path.join(self.folder, "camera.vmd"), 59, -10.0, 10.0)
        self.world = self.put("world.json", {"stage": {"world": 1}, "beams": {"loop_seconds": 1}, "flares": [0.5],
                                              "flare": {"frames": 4}})
        self.plain = self.put("plain.json", {"beams": {"loop_seconds": 1}, "flares": [0.5], "flare": {"frames": 4}})
        self.fg = os.path.join(self.folder, "fg.avi")
        open(self.fg, "wb").close()                                   # never read: the size and the rate are given
        self.work = os.path.join(self.folder, "work")
        share = unittest.mock.patch.object(mv_look, "floor_share", return_value=0.0)
        self.share = share.start()
        self.addCleanup(share.stop)

    def put(self, name, doc):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def render(self, look, *extra):
        fake = FakeRun()
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake):
            code, result = answer(["render", self.fg, look, os.path.join(self.folder, "out.mp4"), "--size", "320x180",
                                   "--fps", "30", "--offset", "0.2", "--from", "0.4", "--to", "1.0"] + list(extra))
        return code, result, [c for c in fake.calls if c[0] == "ffmpeg"]

    def test_a_world_look_needs_the_camera(self):
        code, result, calls = self.render(self.world, "--work", self.work)
        self.assertEqual(code, 2, result)
        self.assertIn("--camera", result["error"]["message"])
        self.assertEqual(calls, [])
        for command in ("prepare", "layers"):
            code, result = answer([command, self.world, self.work, "--size", "320x180", "--fps", "30"])
            self.assertEqual(code, 2, (command, result))
            self.assertIn("--camera", result["error"]["message"])

    def test_the_pool_and_the_shadows_need_the_dancer(self):
        look = self.put("lit.json", {"stage": {"world": 1, "shadow": 0.5}})
        code, result, calls = self.render(look, "--work", self.work, "--camera", self.camera)
        self.assertEqual(code, 2, result)
        self.assertIn("--model", result["error"]["message"])

    def test_a_look_fixed_to_the_picture_ignores_the_camera(self):
        code, result, without = self.render(self.plain, "--work", self.work)
        self.assertEqual(code, 0, result)
        code, result, given = self.render(self.plain, "--work", self.work, "--camera", os.path.join(self.folder, "none.vmd"))
        self.assertEqual(code, 0, result)
        self.assertEqual(given, without)
        self.assertFalse(os.path.exists(os.path.join(self.work, "stage")))
        self.share.assert_not_called()

    def test_a_world_render_draws_the_stage_of_its_excerpt_and_reads_it_from_its_first_frame(self):
        code, result, calls = self.render(self.world, "--work", self.work, "--camera", self.camera)
        self.assertEqual(code, 0, result)
        names = sorted(os.listdir(os.path.join(self.work, "stage")))
        self.assertEqual(names, ["stage_%05d.png" % n for n in range(12, 30)])          # 0.4 s to 1.0 s at 30 fps
        argv = calls[-1]
        pattern = os.path.join(self.work, "stage", "stage_%05d.png").replace("\\", "/")
        at = argv.index(pattern)
        self.assertEqual(argv[at - 3:at - 1], ["-start_number", "12"])
        self.assertEqual((result["stage"]["first"], result["stage"]["frames"]), (12, 18))
        self.assertFalse(os.path.exists(os.path.join(self.work, "light")))             # no loop of light is drawn
        self.share.assert_called_once()

    def test_the_floor_accessory_in_the_dancer_stops_a_world_floor(self):
        self.share.return_value = 0.4
        code, result, calls = self.render(self.world, "--work", self.work, "--camera", self.camera)
        self.assertEqual(code, 2, result)
        self.assertIn("floor accessory", result["error"]["message"])
        self.assertEqual(calls, [])
        bare = self.put("bare.json", {"stage": {"world": 1, "floor": 0}})          # MMD draws the floor: as it should
        code, result, calls = self.render(bare, "--work", self.work, "--camera", self.camera)
        self.assertEqual(code, 0, result)

    def test_prepare_draws_the_stage_of_the_whole_song_and_render_prepared_reads_its_part(self):
        code, result = answer(["prepare", self.world, self.work, "--size", "320x180", "--fps", "30", "--camera", self.camera])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["stage"]["first"], result["stage"]["frames"]), (0, 60))  # the camera's frames 0..59
        self.assertEqual(len(os.listdir(os.path.join(self.work, "stage"))), 60)
        before = listing(self.work)
        code, result, calls = self.render(self.world, "--prepared", self.work, "--camera", self.camera)
        self.assertEqual(code, 0, result)
        self.assertEqual(listing(self.work), before)
        argv = calls[-1]
        pattern = os.path.join(os.path.abspath(self.work), "stage", "stage_%05d.png").replace("\\", "/")
        self.assertEqual(argv[argv.index(pattern) - 3:argv.index(pattern) - 1], ["-start_number", "12"])

    def test_a_stage_prepared_from_another_camera_or_shutter_is_refused(self):
        code, result = answer(["prepare", self.world, self.work, "--size", "320x180", "--fps", "30", "--camera", self.camera])
        self.assertEqual(code, 0, result)
        other = camera_file(os.path.join(self.folder, "other.vmd"), 59, -12.0, 10.0)
        code, result, calls = self.render(self.world, "--prepared", self.work, "--camera", other)
        self.assertEqual(code, 2, result)
        self.assertIn("prepare", result["error"]["message"])
        code, result, calls = self.render(self.world, "--prepared", self.work, "--camera", self.camera, "--subframes", "1",
                                          "--shutter", "0.5")
        self.assertEqual(code, 0, result)
        fake = FakeRun()
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake):
            code, result = answer(["render", self.fg, self.world, os.path.join(self.folder, "o.mp4"), "--size", "320x180",
                                   "--fps", "240", "--subframes", "8", "--offset", "0.2", "--from", "0.4", "--to", "1.0",
                                   "--prepared", self.work, "--camera", self.camera])
        self.assertEqual(code, 2, result)                              # prepared without the shutter of 8 subframes
        self.assertIn("prepare", result["error"]["message"])

    def test_an_excerpt_past_the_prepared_stage_is_refused(self):
        code, result = answer(["prepare", self.world, self.work, "--size", "320x180", "--fps", "30", "--camera", self.camera])
        self.assertEqual(code, 0, result)
        fake = FakeRun()
        with unittest.mock.patch.object(mv_look.subprocess, "run", fake):
            code, result = answer(["render", self.fg, self.world, os.path.join(self.folder, "o.mp4"), "--size", "320x180",
                                   "--fps", "30", "--offset", "1.5", "--from", "1.6", "--to", "2.5",
                                   "--prepared", self.work, "--camera", self.camera])
        self.assertEqual(code, 2, result)
        self.assertIn("stage", result["error"]["message"])


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class FloorShareTest(unittest.TestCase):
    def test_the_share_of_the_floor_accessorys_alpha_in_the_first_picture(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        for name, fill, expect in (("floor", "drawbox=x=0:y=72:w=320:h=108:color=0x10121e@0.92:t=fill:replace=1", 0.6),
                                   ("dancer", "drawbox=x=140:y=20:w=40:h=140:color=white@1.0:t=fill:replace=1", 0.0)):
            path = os.path.join(folder, name + ".avi")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=black@0.0:s=320x180:r=30,format=rgba," + fill, "-frames:v", "3", "-c:v", "rawvideo",
                            "-pix_fmt", "bgra", path], check=True, stdin=subprocess.DEVNULL)
            self.assertAlmostEqual(mv_look.floor_share(path), expect, delta=0.02, msg=name)


@unittest.skipUnless(mv_look and FFMPEG, "needs Pillow, numpy, ffmpeg and ffprobe")
class WorldRenderTest(unittest.TestCase):
    """end to end: a white box (the dancer) over the stage in the world while the camera orbits 40 degrees in 40 frames"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.fg = os.path.join(cls.folder, "fg.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black@0.0:s=%dx%d:r=30,format=rgba,drawbox=x=150:y=30:w=20:h=60:color=white@1.0:t=fill:replace=1"
                        % SIZE, "-frames:v", "40", "-c:v", "rawvideo", "-pix_fmt", "bgra", cls.fg],
                       check=True, stdin=subprocess.DEVNULL)
        cls.camera = camera_file(os.path.join(cls.folder, "camera.vmd"), 39, -20.0, 20.0)
        look = os.path.join(cls.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"stage": {"world": 1, "radius": 0}, "plate": {"vignette": 0}, "beams": {"count": 0, "loop_seconds": 1},
                       "bokeh": {"count": 0}, "glow": {"strength": 0}, "lens": {"vignette": 0, "grain": 0}}, f)
        cls.code, cls.result = answer(["render", cls.fg, look, os.path.join(cls.folder, "out.mp4"), "--work",
                                       os.path.join(cls.folder, "work"), "--camera", cls.camera])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def frames(self):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(self.folder, "out.mp4"), "-f", "rawvideo", "-pix_fmt",
                              "rgb24", "-"], check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
        n = SIZE[0] * SIZE[1] * 3
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).reshape(SIZE[1], SIZE[0], 3).astype(numpy.float64)
                for i in range(len(raw) // n)]

    def test_the_backdrop_turns_with_the_camera_and_the_dancer_stays(self):
        self.assertEqual(self.code, 0, self.result)
        frames = self.frames()
        self.assertEqual(len(frames), 40)

        def pool(img):
            # the plate's pool of light at its own height (the picture's middle; higher up the perspective of a far pool
            # bends its brightest column away from the middle), under the box: the middle of what is above half its height
            prof = img[91:100].sum(axis=2).mean(axis=0)
            top = prof - (prof.max() + prof.min()) / 2.0
            cols = numpy.arange(prof.size)
            return float((numpy.clip(top, 0, None) * cols).sum() / numpy.clip(top, 0, None).sum())
        focal = 90.0 / math.tan(math.radians(15))
        turn = [math.radians(-20.0 + 40.0 * f / 39.0) for f in (12, 27)]
        # the pool lies straight ahead of the reference camera: where that far direction is on each picture (left, then right
        # of the box), and how far it went
        self.assertAlmostEqual(pool(frames[12]), 160 + focal * math.tan(turn[0]), delta=4)
        self.assertAlmostEqual(pool(frames[27]) - pool(frames[12]), focal * (math.tan(turn[1]) - math.tan(turn[0])), delta=6)
        for img in (frames[12], frames[27]):
            self.assertGreater(float(img[40:80, 152:168].mean()), 240)      # the white box where it was

    def test_the_floor_is_drawn_under_her(self):
        frame = self.frames()[20]
        rows = frame[150:180].sum(axis=2)
        self.assertGreater(float(rows.std()), 20)            # the lines of the grid
        self.assertGreater(float(rows.max()), 150)


if __name__ == "__main__":
    unittest.main()
