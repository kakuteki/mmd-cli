"""tools/wb_layer.py: the chest and the head do not ride the hips' quick sideways and fore-and-aft moves (people keep them
steady over a pelvis that moves faster than 1.5 Hz; the traced dance carries the whole upper body with センター).  The
spine bends against the pelvis's quick part and the head keeps its turn in the world; slow moves still carry them."""
import importlib.util
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_balance_layer import MODEL, key, model_bytes
from tests.test_pmx import APPEND_ROTATE, IK, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 30.0
CM = 8.0


def load_tool():
    spec = importlib.util.spec_from_file_location("wb_layer", os.path.join(ROOT, "tools", "wb_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wl = load_tool()
SIDE = {"左": 1.0, "右": -1.0}


def spine_model_bytes():
    """Sour's Rin's bones as tools/pmx_spine.py leaves them: 上半身 -> 腰椎上部 -> 上半身2 -> 胸椎上部 -> 首 -> 頭"""
    w = Writer(bone=2)
    bones = [("全ての親", None, (0.0, 0.1, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.8468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("グルーブ", "センター", (0.0, 8.0468, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("腰", "グルーブ", (0.0, 11.7255, 0.2554), {}),
             ("上半身", "腰", (0.0, 12.2248, -0.6493), {}),
             ("腰椎上部", "上半身", (0.0, 12.95, -0.6627), {}),
             ("上半身2", "腰椎上部", (0.0, 13.7985, -0.6784), {}),
             ("胸椎上部", "上半身2", (0.0, 14.85, -0.3687), {}),
             ("首", "胸椎上部", (0.0, 15.6456, -0.1343), {}),
             ("頭", "首", (0.0, 16.2431, 0.0), {}),
             ("頭先", "頭", (0.0, 18.7663, -0.1601), {}),
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
    return w.build(name="rin-spine-like", bones=built)


SPINE = pmx.loads(spine_model_bytes())


def sway(last=179, amp=0.19, hz=3.0, slow_amp=0.0, slow_hz=0.3, axis=0, head_turn=False):
    """センター sways along `axis` (0 x: sideways, 2 z: fore and aft) by amp sin(2 pi hz t) (+ a slow sway) units, a key
    on every frame; the feet planted; the upper body keyed still (so the trace carries it with センター); a morph and
    an arm key to keep byte for byte.  head_turn: the head also turns (a dance's own head move) 20 degrees about Y"""
    t = np.arange(last + 1) / FPS
    x = amp * np.sin(2 * math.pi * hz * t) + slow_amp * np.sin(2 * math.pi * slow_hz * t)
    bones = []
    for f in range(last + 1):
        pos = [0.0, -0.6, 0.0]
        pos[axis] += float(x[f])
        bones.append(key("センター", f, tuple(pos)))
    for s, sx in (("左", 1.0), ("右", -1.0)):
        bones += [key(s + "足ＩＫ", 0, (sx * 1.0, 0.0, 0.0)), key(s + "足ＩＫ", last, (sx * 1.0, 0.0, 0.0))]
    bones += [key("上半身", 0), key("上半身", last, q=(0.05, 0.0, 0.0, math.sqrt(1 - 0.0025)))]
    bones += [key("左腕", 0, q=(0.0, 0.0, 0.3, math.sqrt(1 - 0.09))), key("左腕", last)]
    if head_turn:
        h = math.radians(20.0) / 2.0
        bones += [key("頭", 0), key("頭", last, q=(0.0, math.sin(h), 0.0, math.cos(h)))]
    morphs = [vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)]
    return vmd.Motion(model_name="dancer", bones=bones, morphs=morphs)


def world(model, motion, names, last):
    tr = fk.world_track(model, motion, names, 0, last)
    return {n: (np.array([p for p, _ in tr[n]]), np.array([q for _, q in tr[n]])) for n in names}


def amplitude(x, hz, inner):
    """the amplitude of the hz sine in x [F] over the frames `inner` (least squares on sin, cos, 1)"""
    t = np.arange(len(x))[inner] / FPS
    A = np.stack([np.sin(2 * math.pi * hz * t), np.cos(2 * math.pi * hz * t), np.ones(len(t))], 1)
    c, *_ = np.linalg.lstsq(A, x[inner], rcond=None)
    return float(math.hypot(c[0], c[1]))


def angle_deg(q1, q2):
    d = np.abs(np.sum(q1 * q2, axis=1))
    return np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))


class ShimmyTest(unittest.TestCase):
    """the hips shimmy sideways at 3 Hz by 1.5 cm"""

    @classmethod
    def setUpClass(cls):
        cls.last = 179
        cls.motion = sway(cls.last)
        cls.result = wl.layer(SPINE, cls.motion)
        cls.out = cls.result.motion
        names = ["下半身", "上半身2", "胸椎上部", "頭", "頭先"]
        cls.before = world(SPINE, cls.motion, names, cls.last)
        cls.after = world(SPINE, cls.out, names, cls.last)
        cls.inner = slice(40, cls.last - 40)

    def amp(self, which, name, axis=0):
        return amplitude(which[name][0][:, axis], 3.0, self.inner)

    def test_head_stays_while_the_hips_shimmy(self):
        pel = self.amp(self.before, "下半身")
        self.assertGreater(pel, 0.15)
        self.assertGreater(self.amp(self.before, "頭"), 0.95 * pel)          # the trace carries the head along
        # people's head follows the pelvis's 2-4 Hz motion by 0.2-0.3 (FineDance near, 62 sequences); the chest by 0.7
        self.assertLess(self.amp(self.after, "頭"), 0.45 * pel)
        self.assertGreater(self.amp(self.after, "頭"), 0.1 * pel)            # not held dead still (nor thrown the other way)
        chest = self.amp(self.after, "胸椎上部")
        self.assertTrue(0.6 * pel < chest < 0.85 * pel, chest / pel)

    def test_hips_unchanged(self):
        np.testing.assert_allclose(self.after["下半身"][0], self.before["下半身"][0], atol=1e-9)

    def test_head_keeps_its_turn_in_the_world(self):
        a = angle_deg(self.before["頭"][1], self.after["頭"][1])
        self.assertLess(a.max(), 0.2)

    def test_the_bend_is_small(self):
        a = angle_deg(self.before["胸椎上部"][1], self.after["胸椎上部"][1])
        self.assertLess(a.max(), 6.0)
        self.assertGreater(a.max(), 0.5)

    def test_only_the_spine_and_the_head_are_written(self):
        written = set(self.result.report["written"])
        self.assertEqual(written, {"腰椎上部", "上半身2", "胸椎上部", "頭"})
        keep = lambda m: vmd.dumps(vmd.Motion(model_name=m.model_name, bones=[k for k in m.bones if k.name not in written],
                                              morphs=m.morphs))       # noqa: E731
        self.assertEqual(keep(self.motion), keep(self.out))

    def test_report_names_the_response(self):
        rep = self.result.report
        r = rep["response"]
        self.assertGreater(r["head"]["before"]["2-4Hz"], 0.9)
        self.assertLess(r["head"]["after"]["2-4Hz"], 0.45)
        self.assertIn("tilt_deg", rep)
        json.dumps(rep)


class SlowSwayTest(unittest.TestCase):
    def test_slow_sway_carries_the_upper_body(self):
        last = 239
        motion = sway(last, amp=0.0, slow_amp=1.25, slow_hz=0.3)        # 10 cm at 0.3 Hz
        out = wl.layer(SPINE, motion).motion
        b = world(SPINE, motion, ["下半身", "頭"], last)
        a = world(SPINE, out, ["下半身", "頭"], last)
        inner = slice(50, last - 50)
        self.assertGreater(amplitude(a["頭"][0][:, 0], 0.3, inner), 0.9 * amplitude(b["下半身"][0][:, 0], 0.3, inner))


class ForeAftTest(unittest.TestCase):
    def test_fore_and_aft_too(self):
        last = 179
        motion = sway(last, axis=2)
        out = wl.layer(SPINE, motion).motion
        b = world(SPINE, motion, ["下半身", "頭"], last)
        a = world(SPINE, out, ["下半身", "頭"], last)
        inner = slice(40, last - 40)
        self.assertLess(amplitude(a["頭"][0][:, 2], 3.0, inner), 0.45 * amplitude(b["下半身"][0][:, 2], 3.0, inner))


class OwnHeadTurnTest(unittest.TestCase):
    def test_the_dances_head_turn_is_kept(self):
        last = 179
        motion = sway(last, head_turn=True)
        out = wl.layer(SPINE, motion).motion
        b = world(SPINE, motion, ["頭"], last)
        a = world(SPINE, out, ["頭"], last)
        self.assertLess(angle_deg(b["頭"][1], a["頭"][1]).max(), 0.2)


class BoundTest(unittest.TestCase):
    def test_a_jolt_bends_no_more_than_the_bound(self):
        last = 119
        bones = []
        for f in range(last + 1):
            bones.append(key("センター", f, (2.5 if f >= 60 else 0.0, -0.6, 0.0)))        # 20 cm in one frame
        for s, sx in (("左", 1.0), ("右", -1.0)):
            bones += [key(s + "足ＩＫ", 0, (sx * 1.0, 0.0, 0.0)), key(s + "足ＩＫ", last, (sx * 1.0, 0.0, 0.0))]
        motion = vmd.Motion(model_name="dancer", bones=bones, morphs=[])
        res = wl.layer(SPINE, motion)
        b = world(SPINE, motion, ["上半身2", "胸椎上部"], last)
        a = world(SPINE, res.motion, ["上半身2", "胸椎上部"], last)
        total = angle_deg(b["胸椎上部"][1], a["胸椎上部"][1])
        self.assertLessEqual(total.max(), wl.MAX_BEND_DEG + 0.05)
        self.assertGreater(res.report["tilt_deg"]["bounded_frames"], 0)


class PlainModelTest(unittest.TestCase):
    def test_without_the_spine_bones_bends_the_two_trunk_bones(self):
        last = 179
        motion = sway(last)
        res = wl.layer(MODEL, motion)
        self.assertEqual(set(res.report["written"]), {"上半身", "上半身2", "頭"})
        b = world(MODEL, motion, ["下半身", "頭"], last)
        a = world(MODEL, res.motion, ["下半身", "頭"], last)
        inner = slice(40, last - 40)
        self.assertLess(amplitude(a["頭"][0][:, 0], 3.0, inner), 0.45 * amplitude(b["下半身"][0][:, 0], 3.0, inner))


class NothingToDoTest(unittest.TestCase):
    def test_still_dance_comes_back_unchanged(self):
        last = 59
        bones = [key("センター", 0, (0.0, -0.6, 0.0)), key("センター", last, (0.0, -0.6, 0.0))]
        motion = vmd.Motion(model_name="dancer", bones=bones, morphs=[])
        self.assertEqual(vmd.dumps(wl.layer(SPINE, motion).motion), vmd.dumps(motion))


SONG = os.environ.get("BALANCE_SONG")


class SongTest(unittest.TestCase):
    """the MV (BALANCE_SONG, the JSON of tests/test_balance_layer.py: its model and dance): the head and the chest follow
    the pelvis's quick moves within people's quartiles (FineDance K-pop / choreography / jazz, 62 sequences: the head's
    slope 0.29 [0.13, 0.42], the chest's 0.70 [0.56, 0.80], the belly's 0.96 [0.86, 1.05]; the traced dance 0.89, 0.93,
    0.98), the bend within its bound, the head's world turn kept"""

    @classmethod
    def setUpClass(cls):
        if not SONG:
            raise unittest.SkipTest("BALANCE_SONG is not set: it names a JSON of the MV's inputs (model, dance), on hinata "
                                    "C:/work/hibikase/stage6/balance/scripts/song_inputs.json")
        with open(SONG, encoding="utf-8") as f:
            paths = json.load(f)
        missing = [k for k in ("model", "dance") if not paths.get(k) or not os.path.isfile(paths[k])]
        if missing:
            raise AssertionError("BALANCE_SONG (%s) names files that are not there: %s" % (SONG, missing))
        model, dance = pmx.load(paths["model"]), vmd.load(paths["dance"])
        cls.result = wl.layer(model, dance)
        cls.report = cls.result.report
        # the review's measures of what the layer does not aim at (tools/upper_body_check.py), before and after
        spec = importlib.util.spec_from_file_location("upper_body_check", os.path.join(ROOT, "tools", "upper_body_check.py"))
        ub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ub)
        F = fk.last_frame(dance) + 1
        before, after = ub.from_motion(model, dance, F), ub.from_motion(model, cls.result.motion, F)
        cls.check = ub.compare(before, after, ub.dance_range(before))

    def test_head_and_chest_as_people_follow_the_pelvis(self):
        r = self.report["response"]
        self.assertGreater(r["head"]["before"]["slope"], 0.8)
        self.assertTrue(0.13 <= r["head"]["after"]["slope"] <= 0.42, r["head"]["after"])
        self.assertTrue(0.56 <= r["chest"]["after"]["slope"] <= 0.80, r["chest"]["after"])
        self.assertGreater(r["belly"]["after"]["slope"], 0.86)

    def test_bend_bounded_and_head_kept(self):
        t = self.report["tilt_deg"]
        self.assertLessEqual(t["bend_deg_max"], wl.MAX_BEND_DEG + 1e-6)
        self.assertLess(t["bend_deg"]["p50"], 2.0)
        self.assertLess(self.report["head_turn_change_deg_max"], 0.01)
        self.assertEqual(len(self.report["written"]), 4)

    def test_what_the_layer_does_not_aim_at(self):
        """measured apart from the layer's own follow (tools/upper_body_check.py, the review of 2026-10-17; people:
        FineDance K-pop / choreography / jazz, 62 sequences, median [quartiles]): the trunk's and the neck's turns stay
        under people's upper quartiles (the chest on the hips p99 218 [181, 267] deg/s, the head on the neck 294 [238,
        333]; the layer gives about 224 and 305, gain 2 with a 30 degree bound 273 and 375), the head's follow in 2 s
        windows within people's quartiles (0.16 [0.01, 0.35]; 0.27, gain 2 -0.62, a 0.5 Hz cutoff 0.50), a hand at the
        face stays within 1.5 cm of where it was against the face (1.0; gain 2 2.1), and the head's stops do not get
        sharper (people 71 ms, the trace about 46)"""
        b, a = self.check["before"], self.check["after"]
        self.assertLessEqual(a["bend"]["chest_on_hips"]["speed_deg_s"]["p99"], 267.0)
        self.assertLessEqual(a["bend"]["head_on_neck"]["speed_deg_s"]["p99"], 333.0)
        self.assertTrue(0.009 <= a["local"]["weighted"]["p50"] <= 0.347, a["local"]["weighted"])
        self.assertLessEqual(self.check["face"]["change_cm"]["max"], 1.5)
        self.assertGreaterEqual(a["stops"]["t80_20_ms"]["p50"], b["stops"]["t80_20_ms"]["p50"])


class CommandTest(unittest.TestCase):
    def test_command(self):
        tmp = tempfile.mkdtemp()
        try:
            d, m, o, r = (os.path.join(tmp, n) for n in ("d.vmd", "m.pmx", "o.vmd", "r.json"))
            with open(d, "wb") as f:
                f.write(vmd.dumps(sway(119)))
            with open(m, "wb") as f:
                f.write(spine_model_bytes())
            self.assertEqual(wl.main([d, m, o, "--report", r]), 0)
            self.assertTrue(os.path.isfile(o))
            with open(r, encoding="utf-8") as f:
                rep = json.load(f)
            self.assertIn("response", rep)
            a = os.path.join(tmp, "a.npz")
            self.assertEqual(wl.main([d, m, o, "--arrays", a]), 0)
            with np.load(a) as z:
                self.assertEqual(z["bend_deg"].shape, (120,))
                self.assertEqual(z["pelvis_quick_cm"].shape, (120, 2))
                self.assertGreater(z["bend_deg"].max(), 0.5)
            self.assertEqual(wl.main([d, d, o]), 2)                  # the same file twice
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
