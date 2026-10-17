"""tools/touch_layer.py: the source's hand touches kept on Rin's body after the later layers, checked by what the bodies
do under the motions (mmd_cli.fk and tools/leg_ik.py, not the layer's own arithmetic): a hand a later layer moved off
the head is put back on it, a hand far from the body is left byte for byte, the bones other than the arms are the
input's byte for byte, an arm a later layer pushed into the hips comes out, and a hand on a thigh stays on the thigh
where MMD's leg IK puts it (not where the thigh's own keys would)."""
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.retarget_fixtures import MIKU, MIKU_BLOBS, RIN, RIN_BLOBS, axis_angle, blob_centre, humanoid_bytes, key, motion
from tests.test_pmx_spine import load_tool

touch_layer = load_tool("touch_layer")
retarget = touch_layer.RT
leg_ik = load_tool("leg_ik")

# the thighs: a sphere on each 足, on the bone's line a unit below the hip joint (the fixtures' legs hang straight)
THIGH = ("左足", (0.04, -1.0, -0.01), 0.9, 200)
RIN_LEGS = tuple(RIN_BLOBS) + (THIGH,)
MIKU_LEGS = tuple(MIKU_BLOBS) + (THIGH,)
RIN_DATA = humanoid_bytes(RIN, RIN_LEGS, twist_axis=True, name="rin")
MIKU_DATA = humanoid_bytes(MIKU, MIKU_LEGS, twist_axis=True, name="miku")
_BODIES = {}


def body(data):
    if data not in _BODIES:
        _BODIES[data] = retarget.Body.loads(data)
    return _BODIES[data]


def world(data, m, names, frames):
    model = pmx.loads(data)
    pose = fk.Pose(model, m, names)
    return {f: pose.at(f) for f in frames}


def palm(data, m, side, frames):
    w = world(data, m, [side + "手首", side + "中指１"], frames)
    return np.array([np.asarray(w[f][side + "手首"][0]) + 0.5 * (np.asarray(w[f][side + "中指１"][0]) - np.asarray(w[f][side + "手首"][0]))
                     for f in frames])


def sphere_distance(data, rest, blobs, bone, m, points, frames):
    """distance of points [F, 3] from the blob sphere on the bone, carried by the bone (no IK)"""
    c0, r = blob_centre(rest, blobs, bone)
    w = world(data, m, [bone], frames)
    out = []
    for n, f in enumerate(frames):
        p, q = w[f][bone]
        c = np.asarray(p) + leg_ik.qrot(np.asarray(q), np.subtract(c0, rest[bone]))
        out.append(float(np.linalg.norm(points[n] - c)) - r)
    return np.array(out)


_RIGS = {}


def thigh_centre(rest):
    """(the left thigh's sphere's centre at rest, its radius)"""
    return tuple(rest["足"][i] + THIGH[1][i] for i in range(3)), THIGH[2]


def thigh_distance(data, rest, m, points, frames, side="左"):
    """distance of points [F, 3] from the thigh's sphere where MMD's leg IK puts the thigh (tools/leg_ik.py)"""
    c0, r = thigh_centre(rest)
    if data not in _RIGS:
        _RIGS[data] = leg_ik.LegRig.loads(data)
    leg = leg_ik.solve(_RIGS[data], m, list(frames))[side]
    c = leg["hip"] + leg_ik.qrot(leg["q_thigh"], np.subtract(c0, rest["足"]))
    return np.linalg.norm(points - c, axis=1) - r


def arm_pose_keys(a, b, g, frame=0):
    return [key("左腕", frame, tuple(retarget.qnorm(retarget.qmul(axis_angle((0.0, 0.0, 1.0), a), axis_angle((0.0, 1.0, 0.0), b))))),
            key("左ひじ", frame, axis_angle((0.0, 1.0, 0.0), g))]


def turned(m, name, axis, degrees):
    """the motion with every key of `name` turned by `degrees` about `axis` after its own (a later layer's change)"""
    q = axis_angle(axis, degrees)
    out = []
    for k in m.bones:
        if k.name == name:
            r = retarget.qnorm(retarget.qmul(np.asarray(fk.applied(k.rotation)), np.asarray(q)))
            k = vmd.BoneKey(k.name, k.frame, tuple(k.position), fk.stored(tuple(float(v) for v in r)), k.interpolation)
        out.append(k)
    return vmd.Motion(model_name=m.model_name, bones=out, morphs=list(m.morphs))


def head_pose():
    """an arm pose whose palm lies on the source's head (5 mm off it), the one the plain mapping takes furthest off"""
    best = None
    for a in range(60, 171, 10):
        for b in range(-60, 61, 20):
            for g in range(0, 151, 15):
                m = motion(*arm_pose_keys(a, b, g))
                d = sphere_distance(MIKU_DATA, MIKU, MIKU_LEGS, "頭", m, palm(MIKU_DATA, m, "左", [0]), [0])[0]
                if abs(d - 0.05) > 0.08:
                    continue
                if best is None or abs(d - 0.05) < abs(best[0] - 0.05):
                    best = (d, (a, b, g))
    return best


class PutBackTest(unittest.TestCase):
    """a hand on the head that a later layer moved off it is put back where the source's hand is on its head"""

    def test_a_hand_moved_off_the_head_is_put_back(self):
        d, pose = head_pose()
        src = motion(*arm_pose_keys(*pose))
        rt = retarget.layer(src, body(MIKU_DATA), body(RIN_DATA), {"feet": False}).motion
        k = RIN_BLOBS[0][2] / MIKU_BLOBS[0][2]
        on = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", rt, palm(RIN_DATA, rt, "左", [0]), [0])[0]
        self.assertLess(abs(on - max(d, 0.0) * k), 0.06)                       # the retarget put it on the head
        moved = turned(rt, "左腕", (0.0, 0.0, 1.0), -12.0)                      # a later layer: the arm 12 degrees down
        off = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", moved, palm(RIN_DATA, moved, "左", [0]), [0])[0]
        self.assertGreater(abs(off - on), 0.2)
        res = touch_layer.layer(moved, src, body(MIKU_DATA), body(RIN_DATA))
        back = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", res.motion, palm(RIN_DATA, res.motion, "左", [0]), [0])[0]
        self.assertLess(abs(back - max(d, 0.0) * k), 0.06)
        self.assertGreater(res.report["左"]["moved_frames"], 0)


def wrist(data, m, frames):
    w = world(data, m, ["左手首"], frames)
    return np.array([np.asarray(w[f]["左手首"][0]) for f in frames])


class SmoothTest(unittest.TestCase):
    """the change is smoothed over the frames where the source's hand is only near a part (its trace shakes there: the
    change follows it frame by frame), and kept as it is where the source's hand touches (the touch's place)"""

    def near_pose(self, lo, hi):
        """an arm pose of the source whose palm lies lo .. hi units off its hips' sphere"""
        for a in range(-78, -41, 3):
            for b in (-50, -40, -30, -20, -10):
                for g in (30, 50, 60, 70, 80, 90):
                    m = motion(*arm_pose_keys(a, b, g))
                    d = sphere_distance(MIKU_DATA, MIKU, MIKU_LEGS, "下半身", m, palm(MIKU_DATA, m, "左", [0]), [0])[0]
                    if lo <= d <= hi:
                        return d, (a, b, g)
        return None

    def shaken(self, pose, last=20, deg=1.5):
        """the pose with the source's upper arm shaken by +-deg degrees every other frame (a trace's jitter)"""
        a, b, g = pose
        keys = []
        for f in range(last + 1):
            keys += arm_pose_keys(a + (deg if f % 2 else -deg), b, g, frame=f)
        return motion(*keys)

    def test_a_near_hand_s_shake_is_smoothed(self):
        found = self.near_pose(0.25, 0.45)
        self.assertIsNotNone(found)
        d, pose = found
        src = self.shaken(pose)
        rt = retarget.layer(motion(*arm_pose_keys(*pose), *arm_pose_keys(*pose, frame=20)), body(MIKU_DATA), body(RIN_DATA),
                            {"feet": False}).motion
        frames = list(range(2, 19))
        rough = touch_layer.layer(rt, src, body(MIKU_DATA), body(RIN_DATA), {"smooth_frames": 0.0}).motion
        smooth = touch_layer.layer(rt, src, body(MIKU_DATA), body(RIN_DATA)).motion
        acc = [float(np.linalg.norm(np.diff(wrist(RIN_DATA, m, frames), n=2, axis=0), axis=1).max()) for m in (rough, smooth)]
        self.assertGreater(acc[0], 0.01)                                   # (the shake reaches the output unsmoothed)
        self.assertLess(acc[1], 0.6 * acc[0])

    def test_a_touch_keeps_its_place(self):
        d, pose = head_pose()
        src = self.shaken(pose, deg=0.5)
        rt = retarget.layer(motion(*arm_pose_keys(*pose), *arm_pose_keys(*pose, frame=20)), body(MIKU_DATA), body(RIN_DATA),
                            {"feet": False}).motion
        moved = turned(rt, "左腕", (0.0, 0.0, 1.0), -12.0)
        frames = list(range(0, 21))
        rough = touch_layer.layer(moved, src, body(MIKU_DATA), body(RIN_DATA), {"smooth_frames": 0.0}).motion
        smooth = touch_layer.layer(moved, src, body(MIKU_DATA), body(RIN_DATA)).motion
        a = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", rough, palm(RIN_DATA, rough, "左", frames), frames)
        b = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", smooth, palm(RIN_DATA, smooth, "左", frames), frames)
        self.assertLess(float(np.abs(a - b).max()), 0.01)


class LeaveTest(unittest.TestCase):
    """a hand far from the body and every bone but the arms are left as they were, byte for byte"""

    def test_a_hand_far_from_the_body_is_left_byte_for_byte(self):
        src = motion(*arm_pose_keys(30, 0, 0), *arm_pose_keys(20, 10, 30, frame=10))
        dance = turned(retarget.layer(src, body(MIKU_DATA), body(RIN_DATA), {"feet": False}).motion, "左腕", (0.0, 0.0, 1.0), 5.0)
        # a file's turns are seldom unit quaternions to the last bit: the keys left are the file's own, not made again
        dance = vmd.Motion(model_name=dance.model_name, morphs=list(dance.morphs), bones=[
            vmd.BoneKey(k.name, k.frame, k.position, tuple(float(v) * 1.0003 for v in k.rotation), k.interpolation)
            if k.name in ("左腕", "左ひじ", "左手首") else k for k in dance.bones])
        res = touch_layer.layer(dance, src, body(MIKU_DATA), body(RIN_DATA))
        self.assertEqual(vmd.dumps(res.motion), vmd.dumps(dance))

    def test_the_bones_other_than_the_arms_and_the_morphs_are_the_inputs(self):
        d, pose = head_pose()
        src = motion(*arm_pose_keys(*pose), key("上半身", 0), key("上半身", 10, axis_angle((1.0, 0.0, 0.0), 8.0)),
                     key("センター", 0, position=(0.0, -0.3, 0.0)), key("右腕", 0, axis_angle((0.0, 0.0, 1.0), 20.0)),
                     morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 10, 0.0)])
        rt = retarget.layer(src, body(MIKU_DATA), body(RIN_DATA), {"feet": False}).motion
        dance = turned(rt, "左腕", (0.0, 0.0, 1.0), -12.0)
        res = touch_layer.layer(dance, src, body(MIKU_DATA), body(RIN_DATA))
        arm = {"左腕", "左ひじ", "左手首", "右腕", "右ひじ", "右手首"}

        def rest(m):
            return vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in m.bones if k.name not in arm], morphs=list(m.morphs)))
        self.assertEqual(rest(res.motion), rest(dance))
        self.assertNotEqual(vmd.dumps(res.motion), vmd.dumps(dance))       # (the left arm did change)


def hips_penetration(data, rest, blobs, m, frames, radii=(0.35, 0.3, 0.25)):
    """the deepest the left arm (capsules on its bones, the tool's default radii) goes into the hips' blob sphere"""
    names = ["左腕", "左ひじ", "左手首", "左中指３"]
    w = world(data, m, names + ["下半身"], frames)
    c0, R = blob_centre(rest, blobs, "下半身")
    deep = -1e9
    for f in frames:
        p, q = w[f]["下半身"]
        c = np.asarray(p) + leg_ik.qrot(np.asarray(q), np.subtract(c0, rest["下半身"]))
        pts = [np.asarray(w[f][n][0]) for n in names]
        for (a, b), r in zip(zip(pts[:-1], pts[1:]), radii):
            for t in np.linspace(0, 1, 15):
                deep = max(deep, r + R - float(np.linalg.norm(a + t * (b - a) - c)))
    return deep


class ClearTest(unittest.TestCase):
    """an arm a later layer pushed into the hips comes out of them"""

    def test_an_arm_pushed_into_the_hips_comes_out(self):
        found = None
        for a in range(-60, -24, 2):                    # an arm clear of the target's hips, which 6 degrees more puts in
            for b in (-20, -10, 0, 10, 20):
                m = motion(*arm_pose_keys(a, b, 0))
                rt = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), {"feet": False}).motion
                if hips_penetration(RIN_DATA, RIN, RIN_LEGS, rt, [0]) > -0.05:
                    continue
                pushed = turned(rt, "左腕", (0.0, 0.0, 1.0), -6.0)
                deep = hips_penetration(RIN_DATA, RIN, RIN_LEGS, pushed, [0])
                if 0.1 < deep < 0.4:
                    found = (m, pushed)
                    break
            if found:
                break
        self.assertIsNotNone(found)
        res = touch_layer.layer(found[1], found[0], body(MIKU_DATA), body(RIN_DATA))
        self.assertLess(hips_penetration(RIN_DATA, RIN, RIN_LEGS, res.motion, [0]), 0.03)


class ThighTest(unittest.TestCase):
    """a hand on a thigh of a crouching body (the knees bent by the leg IK, the thigh's own key at rest) stays on the
    thigh where the IK puts it when a later layer keys the thigh itself (MMD's IK sets the thigh's turn: the key does not
    move it); read by the thigh's key the layer would carry the hand away with a thigh that does not move"""

    def crouch(self, extra=()):
        keys = [key("センター", 0, position=(0.0, -2.5, 0.0)), key("左足ＩＫ", 0), key("右足ＩＫ", 0)]
        return keys + list(extra)

    def test_a_hand_on_a_thigh_stays_on_the_thigh_the_ik_poses(self):
        best = None
        legs_only = motion(*self.crouch())
        c0, r = thigh_centre(RIN)
        leg = leg_ik.solve(leg_ik.LegRig.loads(RIN_DATA), legs_only, [0])["左"]
        centre = leg["hip"][0] + leg_ik.qrot(leg["q_thigh"][0], np.subtract(c0, RIN["足"]))
        for a in range(-70, -29, 4):                    # the arm down and forward: the palm on the thigh's front
            for b in range(-70, -9, 6):
                for g in (0, 15, 30, 45, 60):
                    m = motion(*self.crouch(arm_pose_keys(a, b, g)))
                    d = float(np.linalg.norm(palm(RIN_DATA, m, "左", [0])[0] - centre)) - r
                    if abs(d - 0.05) < 0.06 and (best is None or abs(d - 0.05) < abs(best[0] - 0.05)):
                        best = (d, (a, b, g))
        self.assertIsNotNone(best)
        d, pose = best
        src = motion(*self.crouch(arm_pose_keys(*pose)))
        # a later layer keys the thighs (turned 30 degrees forward): the IK still puts them where they were
        later = motion(*self.crouch(arm_pose_keys(*pose) + [key("左足", 0, axis_angle((1.0, 0.0, 0.0), 30.0))]))
        a0 = leg_ik.solve(leg_ik.LegRig.loads(RIN_DATA), src, [0])["左"]["q_thigh"][0]
        a1 = leg_ik.solve(leg_ik.LegRig.loads(RIN_DATA), later, [0])["左"]["q_thigh"][0]
        self.assertLess(math.degrees(2 * math.acos(min(1.0, abs(float(np.dot(a0, a1)))))), 1.0)
        res = touch_layer.layer(later, src, body(RIN_DATA), body(RIN_DATA))
        t = thigh_distance(RIN_DATA, RIN, res.motion, palm(RIN_DATA, res.motion, "左", [0]), [0])[0]
        self.assertLess(abs(t - max(d, 0.0)), 0.06)
        fk_read = touch_layer.layer(later, src, body(RIN_DATA), body(RIN_DATA), {"ik_thighs": False})
        t_fk = thigh_distance(RIN_DATA, RIN, fk_read.motion, palm(RIN_DATA, fk_read.motion, "左", [0]), [0])[0]
        self.assertGreater(abs(t_fk - max(d, 0.0)), 0.15)                 # (read by the key, the hand leaves the thigh)


class CommandTest(unittest.TestCase):
    def test_run_writes_the_dance_and_its_report(self):
        d, pose = head_pose()
        src = motion(*arm_pose_keys(*pose))
        rt = retarget.layer(src, body(MIKU_DATA), body(RIN_DATA), {"feet": False}).motion
        dance = turned(rt, "左腕", (0.0, 0.0, 1.0), -12.0)
        with tempfile.TemporaryDirectory() as tmp:
            paths = {n: os.path.join(tmp, n) for n in ("miku.pmx", "rin.pmx", "src.vmd", "dance.vmd", "out.vmd", "r.json")}
            for n, data in (("miku.pmx", MIKU_DATA), ("rin.pmx", RIN_DATA)):
                with open(paths[n], "wb") as f:
                    f.write(data)
            vmd.dump(src, paths["src.vmd"])
            vmd.dump(dance, paths["dance.vmd"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = touch_layer.main([paths["dance.vmd"], paths["src.vmd"], paths["miku.pmx"], paths["rin.pmx"], paths["out.vmd"],
                                       "--report", paths["r.json"]])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(buf.getvalue().strip().splitlines()[-1])["ok"])
            out = vmd.load(paths["out.vmd"])
            back = sphere_distance(RIN_DATA, RIN, RIN_LEGS, "頭", out, palm(RIN_DATA, out, "左", [0]), [0])[0]
            k = RIN_BLOBS[0][2] / MIKU_BLOBS[0][2]
            self.assertLess(abs(back - max(d, 0.0) * k), 0.06)
            with open(paths["r.json"], encoding="utf-8") as f:
                rep = json.load(f)
            self.assertIn("左", rep)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(touch_layer.main([paths["dance.vmd"], paths["src.vmd"], paths["miku.pmx"], paths["rin.pmx"],
                                                   paths["dance.vmd"]]), 2)     # never over its input


if __name__ == "__main__":
    unittest.main()
