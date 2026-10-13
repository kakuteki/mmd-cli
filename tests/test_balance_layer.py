"""tools/balance_layer.py: the weight goes onto the standing foot (センター moves the body over it, before the other foot
lifts) and the knee bends on a landing that takes the weight; the feet's IK keys are not touched."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, IK, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CM = 8.0                        # cm per model unit
FPS = 30.0


def load_tool():
    spec = importlib.util.spec_from_file_location("balance_layer", os.path.join(ROOT, "tools", "balance_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


balance_layer = load_tool()

# Sour's Rin's rest positions (model units) of the bones the layer reads
SIDE = {"左": 1.0, "右": -1.0}


def model_bytes():
    w = Writer(bone=2)
    bones = [("全ての親", None, (0.0, 0.1, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.8468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("グルーブ", "センター", (0.0, 8.0468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("腰", "グルーブ", (0.0, 11.7255, 0.2554), {}),
             ("上半身", "腰", (0.0, 12.2248, -0.6493), {}),
             ("上半身2", "上半身", (0.0, 13.7985, -0.6784), {}),
             ("首", "上半身2", (0.0, 15.6456, -0.1343), {}),
             ("頭", "首", (0.0, 16.2431, 0.0), {}),
             ("頭先", "頭", (0.0, 18.7663, -0.1601), {}),
             ("左目", "頭", (0.4101, 17.2143, -0.562), {}),
             ("右目", "頭", (-0.4101, 17.2143, -0.562), {}),
             ("下半身", "腰", (0.0, 12.2248, -0.6493), {})]
    for s, sx in SIDE.items():
        bones += [(s + "肩", "上半身2", (sx * 0.2296, 15.3934, -0.222), {}),
                  (s + "腕", s + "肩", (sx * 0.9114, 15.2768, -0.2484), {}),
                  (s + "ひじ", s + "腕", (sx * 2.9071, 13.7325, -0.27), {}),
                  (s + "手首", s + "ひじ", (sx * 4.6524, 12.4104, -0.2368), {}),
                  (s + "中指３", s + "手首", (sx * 5.8701, 11.5382, -0.2637), {})]
    for s, sx, hy in (("左", 1.0, 10.6579), ("右", -1.0, 10.591)):
        bones += [("腰キャンセル" + s, "下半身", (sx * 0.9012, hy, 0.0073), {"flags": NORMAL | APPEND_ROTATE, "append": "腰"}),
                  (s + "足", "腰キャンセル" + s, (sx * 0.9012, hy, 0.0073), {}),
                  (s + "ひざ", s + "足", (sx * 1.0032, 6.2313, -0.0361), {}),
                  (s + "足首", s + "ひざ", (sx * 1.1205, 1.7452, 0.37), {}),
                  (s + "つま先", s + "足首", (sx * 1.0463, 0.1, -1.15), {}),
                  (s + "足IK親", "全ての親", (sx * 1.1205, 0.1, 0.37), {"flags": NORMAL | TRANSLATE}),
                  (s + "足ＩＫ", s + "足IK親", (sx * 1.1205, 1.7452, 0.37),
                   {"flags": NORMAL | TRANSLATE | IK, "ik": (s + "足首", [(s + "ひざ", ((-math.pi, 0, 0), (0, 0, 0))), (s + "足", None)])}),
                  (s + "つま先ＩＫ", s + "足ＩＫ", (sx * 1.0462, 0.1, -1.1496),
                   {"flags": NORMAL | TRANSLATE | IK, "ik": (s + "つま先", [(s + "足首", None)])})]
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"]], -1.0)
        if "ik" in kw:
            target, links = kw["ik"]
            kw["ik"] = {"target": index[target], "loops": 40, "angle": 2.0,
                        "links": [(index[n], lim) for n, lim in links]}
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-like", bones=built)


MODEL = pmx.loads(model_bytes())


def key(name, frame, position=(0.0, 0.0, 0.0), q=(0.0, 0.0, 0.0, 1.0)):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(q)),
                       vmd.bone_interpolation(vmd.LINEAR_CURVE))


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def foot_track(name, last, base, lifts):
    """per-frame keys of a foot IK: at `base` (x, y, z offsets, units) and raised by each (start, up, down, end, height)
    lift (a smoothstep up from start to up, held, down from down to end)"""
    keys = []
    for f in range(last + 1):
        h = 0.0
        for a, b, c, d, height in lifts:
            if a <= f <= d:
                h = max(h, height * min(smooth((f - a) / max(b - a, 1)), 1.0 - smooth((f - c) / max(d - c, 1))))
        keys.append(key(name, f, (base[0], base[1] + h, base[2])))
    return keys


def dance(last=119, spread=1.0, centre=(0.0, -0.6, 0.0), left_lifts=(), right_lifts=(), arms=False, centre_keys=None):
    """feet `spread` units out from rest (both sides), センター still at `centre` (as a trace keeps it between the feet),
    the lifts of each foot; morphs and an arm key that the layer must copy byte for byte"""
    bones = []
    bones += foot_track("左足ＩＫ", last, (spread, 0.0, 0.0), left_lifts)
    bones += foot_track("右足ＩＫ", last, (-spread, 0.0, 0.0), right_lifts)
    if centre_keys is None:
        bones += [key("センター", 0, centre), key("センター", last, centre)]
    else:
        bones += centre_keys
    bones += [key("上半身", 0), key("上半身", last, q=(0.05, 0.0, 0.0, math.sqrt(1 - 0.0025)))]
    if arms:
        bones += [key("左腕", 0, q=(0.0, 0.0, 0.3, math.sqrt(1 - 0.09))), key("左腕", last)]
    morphs = [vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)]
    return vmd.Motion(model_name="dancer", bones=bones, morphs=morphs)


def centre_offsets(motion_in, motion_out, last):
    """per frame, the world move of センター (units) between the two motions"""
    a = fk.world_track(MODEL, motion_in, ["センター"], 0, last)["センター"]
    b = fk.world_track(MODEL, motion_out, ["センター"], 0, last)["センター"]
    return np.array([np.subtract(pb, pa) for (pa, _), (pb, _) in zip(a, b)])


def others(motion):
    return vmd.dumps(vmd.Motion(model_name=motion.model_name, bones=[k for k in motion.bones if k.name != "センター"],
                                morphs=motion.morphs))


LIFT_RIGHT_STANDS = [(40, 50, 80, 90, 2.5)]          # the left foot up 20 cm from 1.33 s to 3 s: the right foot stands


class BodyTest(unittest.TestCase):
    """the body's centre of mass and the legs, which everything else reads"""

    def test_rest_com_on_the_midline_at_a_plausible_height(self):
        motion = dance()
        body = balance_layer.Body(MODEL, motion)
        com = body.com()
        self.assertLess(abs(com[60, 0]), 0.05)                     # symmetric: on the midline (0.4 cm)
        self.assertTrue(9.0 < com[60, 1] < 11.5, com[60, 1])        # near the hips (72 - 92 cm)

    def test_arm_sideways_moves_the_com_by_its_share(self):
        still = balance_layer.Body(MODEL, dance()).com()
        raised = balance_layer.Body(MODEL, dance(arms=True)).com()
        dx = raised[0, 0] - still[0, 0]
        # the left arm turned 35 degrees about Z: the arm's 4.5 % of the mass moves; the COM goes a few mm, not cm
        self.assertGreater(abs(dx), 0.005)
        self.assertLess(abs(dx), 0.15)

    def test_knee_from_the_leg_lengths(self):
        body = balance_layer.Body(MODEL, dance())
        flex = body.knee_flexion("左")
        # センター 0.6 units down: the knees bend (the rest pose is 5.3 degrees)
        self.assertTrue(15.0 < flex[60] < 60.0, flex[60])
        straight = balance_layer.Body(MODEL, dance(centre=(0.0, 0.0, 0.0), spread=0.0))
        self.assertLess(straight.knee_flexion("左")[60], 8.0)


class WeightShiftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.last = 119
        cls.motion = dance(last=cls.last, left_lifts=LIFT_RIGHT_STANDS)
        cls.result = balance_layer.layer(MODEL, cls.motion)
        cls.out = cls.result.motion
        cls.report = cls.result.report
        cls.shift = centre_offsets(cls.motion, cls.out, cls.last)

    def test_body_goes_over_the_standing_foot(self):
        before = balance_layer.Body(MODEL, self.motion)
        after = balance_layer.Body(MODEL, self.out)
        foot = 0.5 * (before.ankle("右") + before.toe("右"))[:, [0, 2]]
        lat_before = np.abs(before.com()[55:80, 0] - foot[55:80, 0]) * CM
        lat_after = np.abs(after.com()[55:80, 0] - foot[55:80, 0]) * CM
        self.assertGreater(lat_before.min(), 12.0)          # the trace's body hangs between the feet
        self.assertLess(lat_after.max(), 3.0)               # over the standing foot while the other is up
        self.assertLess(self.shift[60, 0], -1.2)            # センター went to the right (-X), 10 cm and more

    def test_shift_starts_before_the_foot_lifts(self):
        x = -self.shift[:, 0]
        plateau = np.median(x[60:75])
        lift = 41                                            # the left foot's first frame above the floor
        self.assertGreater(x[lift], 0.5 * plateau)           # mostly done when the foot leaves the floor
        first = int(np.flatnonzero(x > 0.1 * plateau)[0])
        self.assertLessEqual(first, lift - 3)                # began at least 0.1 s before

    def test_shift_returns_after_the_foot_lands(self):
        """back by the end (1 s after the landing) and not begun a second before the lift (a 17 cm move at the bounded
        acceleration takes about 0.8 s)"""
        x = np.abs(self.shift[:, 0])
        self.assertLess(x[self.last], 0.01)
        self.assertLess(x[:10].max(), 0.01)

    def test_smooth_no_one_frame_jump(self):
        step = np.linalg.norm(np.diff(self.shift, axis=0), axis=1) * CM
        self.assertLess(step.max(), 1.5)
        # the COM's added acceleration on the floor stays under the bound (the pressure under the foot can make it)
        added = (balance_layer.Body(MODEL, self.out).com() - balance_layer.Body(MODEL, self.motion).com())[:, [0, 2]]
        acc = np.linalg.norm(added[2:] - 2 * added[1:-1] + added[:-2], axis=1) * 0.08 * FPS * FPS
        self.assertLess(acc.max(), balance_layer.ACC_MAX * 1.1)
        # and the hips' drop (for the legs' reach; no landing takes weight here) is slower still
        down = self.shift[:, 1]
        acc_y = np.abs(down[2:] - 2 * down[1:-1] + down[:-2]) * 0.08 * FPS * FPS
        self.assertLess(acc_y.max(), balance_layer.DROP_ACC_MAX * 1.1)

    def test_feet_and_everything_else_untouched(self):
        self.assertEqual(others(self.motion), others(self.out))
        self.assertTrue(self.report["untouched"]["identical"])
        names = {k.name for k in self.out.bones if k.name == "センター"}
        self.assertEqual(names, {"センター"})

    def test_legs_reach_their_feet(self):
        after = balance_layer.Body(MODEL, self.out)
        for s in ("左", "右"):
            reach = np.linalg.norm(after.ankle(s) - after.hip(s), axis=1)
            self.assertLessEqual(reach.max(), after.leg_length(s) + 1e-6)

    def test_report_measures_a05(self):
        a05 = self.report["a05_lateral_cm"]
        self.assertGreater(a05["before"]["median"], 12.0)
        self.assertLess(a05["after"]["median"], 3.0)
        self.assertEqual(a05["before"]["frames"], a05["after"]["frames"])
        self.assertIn("runs", self.report)

    def test_deterministic(self):
        again = balance_layer.layer(MODEL, self.motion).motion
        self.assertEqual(vmd.dumps(again), vmd.dumps(self.out))


class ShortStepTest(unittest.TestCase):
    def test_brief_step_moves_part_way_only(self):
        """a 0.2 s step cannot carry the body all the way over (the added acceleration is bounded); it goes part way"""
        last = 89
        motion = dance(last=last, left_lifts=[(40, 43, 44, 47, 1.0)])
        out = balance_layer.layer(MODEL, motion).motion
        shift = centre_offsets(motion, out, last)
        far = np.abs(shift[:, 0]).max() * CM
        self.assertGreater(far, 1.0)                          # it does lean onto the standing foot
        self.assertLess(far, 12.0)                            # but not the whole 17 cm in a fifth of a second
        lean = np.flatnonzero(np.abs(shift[:, 0]) * CM > 0.5)
        self.assertGreater(lean[0], 41 - 20)                  # and not for a second around it
        self.assertLess(lean[-1], 46 + 25)


class ReachTest(unittest.TestCase):
    def test_wide_stance_low_foot_stops_at_the_reach(self):
        """feet 70 cm apart, the left foot only 6 cm up: the body cannot get over the right foot with the left leg still
        reaching its foot; the layer goes as far as the leg allows and says so"""
        last = 119
        motion = dance(last=last, spread=3.3, centre=(0.0, -1.2, 0.0), left_lifts=[(40, 50, 80, 90, 0.75)])
        result = balance_layer.layer(MODEL, motion)
        after = balance_layer.Body(MODEL, result.motion)
        for s in ("左", "右"):
            reach = np.linalg.norm(after.ankle(s) - after.hip(s), axis=1)
            before = np.linalg.norm(balance_layer.Body(MODEL, motion).ankle(s) - balance_layer.Body(MODEL, motion).hip(s), axis=1)
            self.assertTrue(np.all(reach <= np.maximum(after.leg_length(s), before) + 1e-6))
        short = [r for r in result.report["runs"] if r["short_of_target_cm"] > 3.0]
        self.assertTrue(short, "the run that the reach stops must be named")
        self.assertIn("reach", short[0]["limited_by"])


class LandingTest(unittest.TestCase):
    def test_knee_gives_on_a_landing_that_takes_the_weight(self):
        """the left foot steps (up and down); as it lands the right foot lifts: the left leg takes the weight and its knee
        bends more within 0.15 s, then comes back"""
        last = 149
        motion = dance(last=last, left_lifts=[(30, 36, 44, 50, 1.5)], right_lifts=[(52, 60, 100, 108, 2.0)])
        result = balance_layer.layer(MODEL, motion)
        before = balance_layer.Body(MODEL, motion).knee_flexion("左")
        after = balance_layer.Body(MODEL, result.motion).knee_flexion("左")
        land = 50
        gain_before = before[land:land + 5].max() - before[land]
        gain_after = after[land:land + 5].max() - after[land]
        self.assertGreater(gain_after - gain_before, 6.0)
        self.assertLess(abs((after - before)[land + 20]), 3.0)      # back within 0.7 s
        self.assertTrue(result.report["landings"]["dipped"] >= 1)

    def test_toe_tap_gets_no_dip(self):
        """the left foot taps the floor and lifts again while the right foot stays down: no weight to take"""
        last = 119
        motion = dance(last=last, left_lifts=[(20, 26, 40, 46, 1.5), (49, 55, 70, 76, 1.5)])
        result = balance_layer.layer(MODEL, motion)
        self.assertEqual(result.report["landings"]["dipped"], 0)


class NothingToDoTest(unittest.TestCase):
    def test_both_feet_down_gives_the_input_back(self):
        motion = dance(last=59)
        result = balance_layer.layer(MODEL, motion)
        self.assertEqual(vmd.dumps(result.motion), vmd.dumps(motion))

    def test_already_balanced_is_left_alone(self):
        """the dance itself puts the body over the right foot before the left lifts"""
        last = 119
        over = [key("センター", f, (-2.5 * min(smooth((f - 10) / 25.0), 1.0 - smooth((f - 95) / 20.0)), -0.6, 0.0))
                for f in range(last + 1)]
        motion = dance(last=last, left_lifts=LIFT_RIGHT_STANDS, centre_keys=over)
        body = balance_layer.Body(MODEL, motion)
        heel, toe = body.sole("右")
        line_x = 0.5 * (heel[:, 0] + toe[:, 0])
        self.assertLess(np.abs(body.com()[36:95, 0] - line_x[36:95]).max() * CM, 1.0)    # the fixture is balanced
        result = balance_layer.layer(MODEL, motion)
        shift = centre_offsets(motion, result.motion, last)
        self.assertLess(np.abs(shift).max() * CM, 1.0)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.model = os.path.join(self.dir, "m.pmx")
        with open(self.model, "wb") as f:
            f.write(model_bytes())
        self.dance = os.path.join(self.dir, "d.vmd")
        vmd.dump(dance(left_lifts=LIFT_RIGHT_STANDS), self.dance)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_writes_motion_and_report(self):
        out = os.path.join(self.dir, "o.vmd")
        rep = os.path.join(self.dir, "r.json")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, self.model, out, "--report", rep])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out))
        with open(rep, encoding="utf-8") as f:
            report = json.load(f)
        self.assertIn("a05_lateral_cm", report)
        line = json.loads(printed.getvalue().strip().splitlines()[-1])
        self.assertTrue(line["ok"])
        printed.getvalue().encode("cp932")                    # the terminal is cp932

    def test_same_path_refused(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, self.model, self.dance])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(printed.getvalue().strip().splitlines()[-1])["ok"])

    def test_model_without_the_feet_refused(self):
        w = Writer(bone=2)
        bare = w.build(name="no feet", bones=[w.bone("センター", flags=NORMAL | TRANSLATE)])
        path = os.path.join(self.dir, "bare.pmx")
        with open(path, "wb") as f:
            f.write(bare)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = balance_layer.main([self.dance, path, os.path.join(self.dir, "o.vmd")])
        self.assertEqual(code, 2)
        self.assertIn("足ＩＫ", json.loads(printed.getvalue().strip().splitlines()[-1])["error"]["message"])


# ---- the MV itself ----------------------------------------------------------------------------------

SONG = os.environ.get("BALANCE_SONG")


def song_paths():
    """the MV's inputs named by BALANCE_SONG (a JSON {"model", "dance"}): SkipTest, with the reason, when it is not set;
    a set variable naming files that are not there fails instead"""
    if not SONG:
        raise unittest.SkipTest("BALANCE_SONG is not set: it names a JSON of the MV's inputs (model, dance), on hinata "
                                "C:/work/hibikase/stage6/balance/song_inputs.json")
    with open(SONG, encoding="utf-8") as f:
        paths = json.load(f)
    missing = ["%s %s" % (k, paths.get(k)) for k in ("model", "dance") if not paths.get(k) or not os.path.isfile(paths[k])]
    if missing:
        raise AssertionError("BALANCE_SONG (%s) names files that are not there: %s" % (SONG, "; ".join(missing)))
    return paths


class SongTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = song_paths()
        cls.model = pmx.load(paths["model"])
        cls.motion = vmd.load(paths["dance"])
        cls.result = balance_layer.layer(cls.model, cls.motion)
        cls.report = cls.result.report

    def test_weight_on_the_standing_foot(self):
        a05 = self.report["a05_lateral_cm"]
        self.assertGreater(a05["before"]["median"], 9.0)
        self.assertLess(a05["after"]["median"], a05["before"]["median"] / 2.0)
        self.assertLess(a05["after_holds"]["median"], 3.0)

    def test_feet_untouched_and_smooth(self):
        self.assertTrue(self.report["untouched"]["identical"])
        self.assertLess(self.report["centre"]["step_cm"]["max"], 1.5)

    def test_reach_not_worse(self):
        for s in ("L", "R"):
            self.assertEqual(self.report["reach"]["worse_frames_" + s], 0)


if __name__ == "__main__":
    unittest.main()
