"""tools/motion_fk.py: the world paths of a few bones of a dance (FK) and their speed and acceleration."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import time
import unittest

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import IK, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("motion_fk", os.path.join(ROOT, "tools", "motion_fk.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


motion_fk = load_tool()
LAST = 40
RADIUS = 4.5                    # the wrist's distance from the body's vertical axis


def arm_bytes():
    """a body with a right arm (the wrist 4.5 from the axis of 上半身) and a leg under a leg IK"""
    w = Writer(bone=2)
    ik = {"target": 6, "loops": 40, "angle": 2.0, "links": [(5, None), (4, None)]}
    bones = [("全ての親", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("上半身", 0, (0.0, 12.0, 0.0), {}),
             ("右腕", 1, (-1.5, 14.0, 0.0), {}),
             ("右手首", 2, (-RADIUS, 12.5, 0.0), {}),
             ("右足", 0, (-1.0, 10.0, 0.0), {}),
             ("右ひざ", 4, (-1.0, 6.0, 0.0), {}),
             ("右足首", 5, (-1.0, 1.0, 0.0), {}),
             ("右足ＩＫ", 0, (-1.0, 1.0, 0.0), {"flags": NORMAL | TRANSLATE | IK, "ik": ik}),
             ("頭", 1, (0.0, 16.0, 0.0), {})]
    return w.build(name="arm", bones=[w.bone(n, parent=p, position=pos, **kw) for n, p, pos, kw in bones])


MODEL = pmx.loads(arm_bytes())


def about_y(degrees):
    half = math.radians(degrees) / 2.0
    return (0.0, math.sin(half), 0.0, math.cos(half))


def turning_dance():
    """上半身 turns 90 degrees about Y at a steady pace over frames 0..30, then holds until LAST"""
    return vmd.Motion(model_name="dancer", bones=[
        vmd.BoneKey("上半身", 0, (0.0, 0.0, 0.0), about_y(0.0)), vmd.BoneKey("上半身", 30, (0.0, 0.0, 0.0), about_y(90.0)),
        vmd.BoneKey("全ての親", LAST, (0.0, 0.0, 0.0), fk.IDENTITY)])


class MeasureTest(unittest.TestCase):
    def test_a_steady_turn_gives_a_steady_speed_and_a_jolt_where_it_stops(self):
        result = motion_fk.measure(MODEL, turning_dance(), ["右手首"])
        self.assertEqual(result["frames"], [0, LAST])
        path = result["paths"]["右手首"]
        self.assertEqual(len(path), LAST + 1)
        step = 2.0 * RADIUS * math.sin(math.radians(3.0) / 2.0)             # the chord of 3 degrees a frame
        speeds = motion_fk.speeds(path)
        self.assertEqual(len(speeds), LAST)
        for s in speeds[:30]:
            self.assertAlmostEqual(s, step, places=6)
        self.assertEqual(max(speeds[30:]), 0.0)
        stats = result["bones"]["右手首"]
        self.assertAlmostEqual(stats["speed"]["max"], step, places=6)
        self.assertAlmostEqual(stats["speed"]["mean"], step * 30 / LAST, places=6)
        # along the arc the second difference is the bend of a 3 degree chord; where the turn stops it is the whole step
        bend = 2.0 * RADIUS * (1.0 - math.cos(math.radians(3.0)))
        accelerations = motion_fk.accelerations(path)
        self.assertEqual(len(accelerations), LAST - 1)
        self.assertAlmostEqual(accelerations[10], bend, places=6)
        self.assertAlmostEqual(stats["acceleration"]["max"], step, places=6)

    def test_the_paths_are_the_forward_kinematics_of_the_bones(self):
        result = motion_fk.measure(MODEL, turning_dance(), ["右手首", "頭"])
        track = fk.world_track(MODEL, turning_dance(), ["右手首", "頭"])
        for name in ("右手首", "頭"):
            for frame in (0, 15, 30, LAST):
                for a, b in zip(result["paths"][name][frame], track[name][frame][0]):
                    self.assertAlmostEqual(a, b, places=9)
        # the head sits on the turning axis: it does not move
        self.assertEqual(result["bones"]["頭"]["speed"]["max"], 0.0)

    def test_bones_under_an_ik_are_flagged(self):
        result = motion_fk.measure(MODEL, turning_dance(), ["右手首", "右足首", "右ひざ", "右足"])
        flags = {name: stats["ik_affected"] for name, stats in result["bones"].items()}
        self.assertEqual(flags, {"右手首": False, "右足首": True, "右ひざ": True, "右足": True})

    def test_percentile_and_mean_of_nothing(self):
        self.assertEqual(motion_fk.summary([]), {"mean": 0.0, "p99": 0.0, "max": 0.0})
        values = list(range(101))
        self.assertEqual(motion_fk.summary(values), {"mean": 50.0, "p99": 99.0, "max": 100.0})


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = motion_fk.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        self.model = os.path.join(self.folder, "arm.pmx")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(turning_dance()))
        with open(self.model, "wb") as f:
            f.write(arm_bytes())

    def test_prints_the_measures_and_writes_the_paths(self):
        out = os.path.join(self.folder, "sub", "paths.json")
        code, result = run([self.dance, self.model, "--bones", "右手首", "右足首", "--out", out])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["frames"], [0, LAST])
        self.assertEqual(sorted(result["bones"]), ["右手首", "右足首"])
        self.assertEqual(set(result["bones"]["右手首"]), {"speed", "acceleration", "ik_affected"})
        self.assertIn("IK", result["note"])
        self.assertEqual(result["unit"], {"position": "model units", "speed": "model units per frame",
                                          "acceleration": "model units per frame^2"})
        self.assertEqual(result["out"], os.path.abspath(out))
        with open(out, encoding="ascii") as f:
            saved = json.load(f)
        self.assertEqual(len(saved["paths"]["右手首"]), LAST + 1)
        self.assertEqual(saved["bones"], result["bones"])
        self.assertEqual(saved["paths"]["右手首"][0], [-RADIUS, 12.5, 0.0])

    def test_the_default_bones_are_the_wrists_and_the_head(self):
        w = Writer(bone=2)
        with open(self.model, "wb") as f:
            f.write(w.build(bones=[w.bone("右手首"), w.bone("左手首"), w.bone("頭")]))
        code, result = run([self.dance, self.model])
        self.assertEqual(code, 0, result)
        self.assertEqual(list(result["bones"]), ["右手首", "左手首", "頭"])
        self.assertNotIn("out", result)

    def test_errors_exit_2(self):
        for argv in ([self.dance, self.model, "--bones", "左手首"],
                     [self.dance, self.model, "--out", self.dance],
                     [self.dance, self.dance],
                     [os.path.join(self.folder, "none.vmd"), self.model]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
        with open(self.dance, "rb") as f:
            self.assertEqual(vmd.loads(f.read()).bones[1].frame, 30)


def real_file(*parts):
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    return None


REAL_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_smooth_twist.vmd")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"


@unittest.skipUnless(REAL_DANCE and os.path.isfile(RIN), "the dance or Sour's Rin is not here")
class RealSongTest(unittest.TestCase):
    def test_the_hands_and_the_head_of_the_whole_song(self):
        started = time.time()
        code, result = run([REAL_DANCE, RIN])
        self.assertEqual(code, 0, result)
        self.assertLess(time.time() - started, 60.0)
        self.assertEqual(result["frames"], [0, 7742])
        for name in ("右手首", "左手首", "頭"):
            stats = result["bones"][name]
            self.assertFalse(stats["ik_affected"], name)
            self.assertGreater(stats["speed"]["max"], 0.0)
            self.assertLessEqual(stats["speed"]["p99"], stats["speed"]["max"])
            self.assertLessEqual(stats["acceleration"]["p99"], stats["acceleration"]["max"])


if __name__ == "__main__":
    unittest.main()
