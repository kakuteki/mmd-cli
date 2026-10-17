"""tools/retarget_check.py: the measures of a retargeted dance against its source, checked on small bodies where the answer
is known: a hand kept on the head counts as kept and one taken off it as lost; an arm in the hips is counted and one kept
out is not; a planted foot that slides or floats is counted and one held still on the floor is not."""
import math
import unittest

import numpy as np

from tests import test_retarget as T
from tests.retarget_fixtures import MIKU, RIN, axis_angle, key, motion
from tests.test_pmx_spine import load_tool

check = load_tool("retarget_check")


def head_touch_dance():
    """the source's left palm on its head (the pose the hands test finds), held over frames 0..9"""
    k = T.RIN_BLOBS[0][2] / T.MIKU_BLOBS[0][2]
    best = None
    for a in range(60, 171, 10):
        for b in range(-60, 61, 20):
            for g in range(0, 151, 15):
                m = motion(*T.arm_pose_keys(a, b, g))
                d = T.sphere_distance(T.MIKU_DATA, MIKU, T.MIKU_BLOBS, "頭", m, T.palm(T.MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                if abs(d - 0.05) > 0.08:
                    continue
                pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE)
                dp = T.sphere_distance(T.RIN_DATA, RIN, T.RIN_BLOBS, "頭", pure.motion, T.palm(T.RIN_DATA, RIN, pure.motion, "左", [0]), [0])[0]
                miss = abs(dp - max(d, 0.0) * k)
                if best is None or miss > best[0]:
                    best = (miss, a, b, g)
    keys = T.arm_pose_keys(*best[1:])
    return motion(*keys, *[key(k.name, 9, k.rotation) for k in keys])


class ContactsTest(unittest.TestCase):
    def test_a_hand_kept_on_the_head_is_kept_and_one_taken_off_is_lost(self):
        m = head_touch_dance()
        pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE).motion
        kept = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), {"feet": False, "clear": False}).motion
        a = check.measure(m, T.body(T.MIKU_DATA), pure, T.body(T.RIN_DATA))
        b = check.measure(m, T.body(T.MIKU_DATA), kept, T.body(T.RIN_DATA))
        ra, rb = a["contacts"]["左"]["head"], b["contacts"]["左"]["head"]
        self.assertEqual(ra["source_touch_frames"], 10)
        self.assertEqual(rb["source_touch_frames"], 10)
        self.assertLess(ra["kept_share"], 0.1)
        self.assertGreater(rb["kept_share"], 0.9)
        self.assertEqual(rb["lost_runs"], [])


class ArmsInBodyTest(unittest.TestCase):
    def test_an_arm_in_the_hips_is_counted_and_one_kept_out_is_not(self):
        found = None
        for a in range(-60, -24, 2):
            for b in (-20, -10, 0, 10, 20):
                m = motion(*T.arm_pose_keys(a, b, 0))
                src = T.arm_penetration(T.MIKU_DATA, MIKU, T.MIKU_BLOBS, m, [0])
                pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE)
                tgt = T.arm_penetration(T.RIN_DATA, RIN, T.RIN_BLOBS, pure.motion, [0])
                if src < -0.05 and 0.15 < tgt < 0.4:
                    found = (a, b)
                    break
            if found:
                break
        keys = T.arm_pose_keys(*found, 0)
        m = motion(*keys, *[key(k.name, 4, k.rotation) for k in keys])
        pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE).motion
        out = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), {"feet": False, "hands": False}).motion
        a = check.measure(m, T.body(T.MIKU_DATA), pure, T.body(T.RIN_DATA))["arms_in_body"]
        b = check.measure(m, T.body(T.MIKU_DATA), out, T.body(T.RIN_DATA))["arms_in_body"]
        self.assertEqual(a["target"]["左"]["frames_over_1cm"], 5)
        self.assertEqual(b["target"]["左"]["frames_over_1cm"], 0)
        self.assertEqual(a["source"]["左"]["frames_over_1cm"], 0)     # the source's own arm clears its hips


class PlantsTest(unittest.TestCase):
    def pivot(self):
        ankle = np.array(MIKU["足首"])
        ball = np.array([MIKU["足先EX"][0], MIKU["つま先"][1], MIKU["足先EX"][2]])
        turns = [axis_angle((0.0, 1.0, 0.0), 4.0 * f) for f in range(0, 11)]
        goals = [ball - T.leg_ik.qrot(np.array(q), ball - ankle) for q in turns]
        heel = [(0.0, 0.0, 0.0, 1.0)] * 11
        for _ in range(5):                       # the source's own foot flat and turning on its ball
            keys = [key("左足ＩＫ", f, q, position=tuple(g - ankle)) for f, (q, g) in enumerate(zip(turns, goals))]
            keys += [key("左足首", f, k) for f, k in enumerate(heel)]
            m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), *keys, key("右足ＩＫ", 0))
            sol = T.legs(T.MIKU_DATA, m, range(0, 11))["左"]
            bb = T.foot_point(sol, ball - ankle)
            goals = [g + np.array([ball[0] - p[0], 0.0, ball[2] - p[2]]) for g, p in zip(goals, bb)]
            heel = [tuple(T.retarget.qmul(T.retarget.qconj(sol["q_shin"][f]), np.array(q))) for f, q in enumerate(turns)]
        return m

    def test_a_sliding_plant_is_counted_and_a_held_one_is_not(self):
        m = self.pivot()
        held = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        # the same dance with its right foot (standing still, flat) dragged 0.02 units (1.6 mm) a frame along x
        tr = T.retarget.Track([k for k in held.bones if k.name == "右足ＩＫ"])
        pos, rot = tr.sample(np.arange(0, 11))
        drag = [T.vmd.BoneKey("右足ＩＫ", f, (pos[f][0] + 0.02 * f, pos[f][1], pos[f][2]), T.fk.stored(tuple(rot[f])))
                for f in range(0, 11)]
        slid = T.vmd.Motion(model_name=held.model_name, bones=[k for k in held.bones if k.name != "右足ＩＫ"] + drag)
        a = check.measure(m, T.body(T.MIKU_DATA), held, T.body(T.RIN_SHOE_DATA))["plants"]["左"]
        b = check.measure(m, T.body(T.MIKU_DATA), slid, T.body(T.RIN_SHOE_DATA))["plants"]["右"]
        self.assertEqual(a["plants"], 1)
        # the slowest touching vertex of the fixture's coarse shoe (12 x 3 x 4 vertices) lies up to 0.1 from the ball
        # the foot turns on: 40 degrees move it about 0.3 cm
        self.assertLess(a["slide_path_cm"]["max"], 0.4)
        self.assertLess(a["float_cm"]["max"], 0.1)
        self.assertGreater(b["slide_path_cm"]["max"], 1.2)
        self.assertEqual(b["plants_sliding_over_1cm"], 1)

    def test_a_toe_left_up_is_counted_as_floating(self):
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        th = math.radians(10.0)
        rise = l * math.sin(th) - h * (1 - math.cos(th))
        q = axis_angle((1.0, 0.0, 0.0), -10.0)
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("左足ＩＫ", 0, q, position=(0.0, rise, 0.0)),
                   key("左足ＩＫ", 9, q, position=(0.0, rise, 0.0)), key("右足ＩＫ", 0))
        pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), T.PURE).motion
        held = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        a = check.measure(m, T.body(T.MIKU_DATA), pure, T.body(T.RIN_SHOE_DATA))["plants"]["左"]
        b = check.measure(m, T.body(T.MIKU_DATA), held, T.body(T.RIN_SHOE_DATA))["plants"]["左"]
        self.assertEqual(a["toe_plants"], 1)
        self.assertGreater(a["toe_float_cm"]["p50"], 0.3)
        self.assertLess(b["toe_float_cm"]["max"], 0.1)


class CommandTest(unittest.TestCase):
    def test_the_command_writes_the_report(self):
        import io
        import json
        import os
        import tempfile
        from contextlib import redirect_stdout
        m = head_touch_dance()
        with tempfile.TemporaryDirectory() as d:
            paths = {}
            for name, data in (("miku.pmx", T.MIKU_DATA), ("rin.pmx", T.RIN_SHOE_DATA)):
                paths[name] = os.path.join(d, name)
                with open(paths[name], "wb") as f:
                    f.write(data)
            src = os.path.join(d, "src.vmd")
            T.vmd.dump(m, src)
            tgt = os.path.join(d, "tgt.vmd")
            T.vmd.dump(T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), T.PURE).motion, tgt)
            rep = os.path.join(d, "r.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main([src, paths["miku.pmx"], tgt, paths["rin.pmx"], "--report", rep])
            self.assertEqual(code, 0, buf.getvalue())
            with open(rep, encoding="utf-8") as f:
                r = json.load(f)
            self.assertIn("contacts", r)
            self.assertIn("summary", r)
            self.assertTrue(json.loads(buf.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
