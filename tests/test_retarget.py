"""tools/retarget.py: the traced dance moved from the body it was traced on (the source) to another body (the target),
checked by what the two bodies do under the motions (mmd_cli.fk and tools/leg_ik.py, not the tool's own arithmetic):
the same body gives the same motion back; the arms point where the source's point although they rest at another angle;
a twist turns about the target's own arm; the translations scale with the legs and the legs keep their directions;
every key stays on its frame; bones the target lacks pass through and are reported."""
import math
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.retarget_fixtures import MIKU, MIKU_BLOBS, RIN, RIN_BLOBS, axis_angle, humanoid_bytes, key, motion
from tests.test_pmx_spine import load_tool

retarget = load_tool("retarget")

RIN_DATA = humanoid_bytes(RIN, RIN_BLOBS, twist_axis=True, name="rin")
MIKU_DATA = humanoid_bytes(MIKU, MIKU_BLOBS, twist_axis=True, name="miku")
PURE = {"feet": False, "hands": False, "clear": False}


def body(data):
    return retarget.Body.loads(data)


def world(data, m, names, frames):
    model = pmx.loads(data)
    pose = fk.Pose(model, m, names)
    return {f: pose.at(f) for f in frames}


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def direction(w, a, b):
    return unit(np.asarray(w[b][0]) - np.asarray(w[a][0]))


def angle_deg(u, v):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(u, v))))))


def dance():
    """arms, a twist, the trunk, the centre and the feet moving over 0..20"""
    return motion(
        key("左腕", 0), key("左腕", 10, axis_angle((0.3, 0.2, 1.0), -40.0)), key("左腕", 20, axis_angle((1.0, 0.0, 0.2), 70.0)),
        key("左ひじ", 0), key("左ひじ", 10, axis_angle((0.0, 1.0, 0.1), 60.0)), key("左ひじ", 20, axis_angle((0.0, 1.0, 0.0), 20.0)),
        key("左腕捩", 0), key("左腕捩", 20, axis_angle(direction_of(MIKU, "腕", "ひじ"), 50.0)),
        key("左手首", 0), key("左手首", 10, axis_angle((0.0, 0.0, 1.0), 30.0)),
        key("右腕", 0, axis_angle((0.0, 0.0, 1.0), 30.0)), key("右腕", 15, axis_angle((0.2, 1.0, 0.0), 50.0)),
        key("上半身", 0), key("上半身", 20, axis_angle((1.0, 0.0, 0.0), 15.0)),
        key("センター", 0), key("センター", 10, position=(0.3, -1.0, 0.5)), key("センター", 20, position=(-0.6, 0.4, 1.2)),
        key("左足ＩＫ", 0), key("左足ＩＫ", 10, position=(0.2, 0.5, -0.3)), key("左足ＩＫ", 20, position=(0.0, 0.0, 0.9)),
        key("右足ＩＫ", 0), key("右足ＩＫ", 12, position=(-0.4, 0.0, 0.2)))


def direction_of(rest, a, b):
    return tuple(unit(np.asarray(rest[b]) - np.asarray(rest[a])))


class PureMappingTest(unittest.TestCase):
    """the mapping alone (no contacts): rotations with the rest poses' difference, translations by the legs' ratio"""

    def test_the_same_body_gives_the_same_motion(self):
        m = dance()
        res = retarget.layer(m, body(RIN_DATA), body(RIN_DATA), PURE)
        before = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in m.bones)
        after = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in res.motion.bones)
        self.assertEqual(len(before), len(after))
        for b, a in zip(before, after):
            self.assertEqual(b[:2], a[:2])
            np.testing.assert_allclose(b[2], a[2], atol=1e-6)
            self.assertGreater(abs(float(np.dot(b[3], a[3]))), 1 - 1e-9)
            self.assertEqual(b[4], a[4])

    def test_the_arms_point_where_the_sources_point(self):
        m = dance()
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        names = ["左腕", "左ひじ", "左手首", "左中指１", "右腕", "右ひじ"]
        src = world(MIKU_DATA, m, names, range(0, 21))
        tgt = world(RIN_DATA, res.motion, names, range(0, 21))
        worst = 0.0
        for f in range(0, 21):
            for a, b in (("左腕", "左ひじ"), ("左ひじ", "左手首"), ("左手首", "左中指１"), ("右腕", "右ひじ")):
                worst = max(worst, angle_deg(direction(src[f], a, b), direction(tgt[f], a, b)))
        self.assertLess(worst, 0.05)
        # and without the correction they would not: Rin's arms rest 8 degrees lower
        plain = world(RIN_DATA, m, names, [0])
        self.assertGreater(angle_deg(direction(src[0], "左腕", "左ひじ"), direction(plain[0], "左腕", "左ひじ")), 6.0)

    def test_a_twist_turns_about_the_targets_own_arm(self):
        m = motion(key("左腕捩", 0, axis_angle(direction_of(MIKU, "腕", "ひじ"), 70.0)),
                   key("左ひじ", 0, axis_angle((0.0, 1.0, 0.0), 80.0)))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        names = ["左腕", "左ひじ", "左手首"]
        src = world(MIKU_DATA, m, names, [0])[0]
        tgt = world(RIN_DATA, res.motion, names, [0])[0]
        self.assertLess(angle_deg(direction(src, "左ひじ", "左手首"), direction(tgt, "左ひじ", "左手首")), 0.05)
        # the upper arm does not swing off the source's (the twist turns about it)
        self.assertLess(angle_deg(direction(tgt, "左腕", "左ひじ"), direction(src, "左腕", "左ひじ")), 0.05)

    def test_translations_scale_with_the_legs(self):
        m = dance()
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        s = ((RIN["足"][1] - RIN["足首"][1]) / (MIKU["足"][1] - MIKU["足首"][1]))
        self.assertAlmostEqual(res.report["scale"], s, places=6)
        out = {(k.name, k.frame): k for k in res.motion.bones}
        np.testing.assert_allclose(out[("センター", 10)].position, np.multiply((0.3, -1.0, 0.5), s), atol=1e-6)
        np.testing.assert_allclose(out[("センター", 20)].position, np.multiply((-0.6, 0.4, 1.2), s), atol=1e-6)
        # the foot IK: scaled, and moved sideways once so that the legs keep the source's spread
        kx = s * (MIKU["足首"][0] - MIKU["足"][0]) - (RIN["足首"][0] - RIN["足"][0])
        np.testing.assert_allclose(out[("左足ＩＫ", 10)].position, (0.2 * s + kx, 0.5 * s, -0.3 * s), atol=1e-6)
        np.testing.assert_allclose(out[("右足ＩＫ", 12)].position, (-0.4 * s - kx, 0.0, 0.2 * s), atol=1e-6)

    def test_the_legs_keep_the_sources_spread(self):
        m = motion(key("センター", 0), key("左足ＩＫ", 0), key("右足ＩＫ", 0, position=(-0.5, 0.0, 0.0)))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        names = ["左足", "左足ＩＫ", "右足", "右足ＩＫ"]
        src = world(MIKU_DATA, m, names, [0])[0]
        tgt = world(RIN_DATA, res.motion, names, [0])[0]
        for s in ("左", "右"):
            a = np.subtract(src[s + "足ＩＫ"][0], src[s + "足"][0])
            b = np.subtract(tgt[s + "足ＩＫ"][0], tgt[s + "足"][0])
            self.assertAlmostEqual(a[0] / -a[1], b[0] / -b[1], places=4)

    def test_every_key_stays_on_its_frame(self):
        m = dance()
        m.morphs = [vmd.MorphKey("あ", 3, 0.5)]
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        before = {(k.name, k.frame) for k in m.bones}
        after = {(k.name, k.frame) for k in res.motion.bones}
        self.assertLessEqual(before, after)
        # the only keys added: frame 0 of corrected bones the dance does not key (their rest turned), reported
        extra = sorted(after - before)
        self.assertEqual(extra, sorted((n, 0) for n in res.report["added_rest_keys"]))
        self.assertTrue(all(n not in {k.name for k in m.bones} for n, _ in extra))
        self.assertEqual([(k.name, k.frame, k.weight) for k in res.motion.morphs], [("あ", 3, 0.5)])
        inter = {(k.name, k.frame): k.interpolation for k in m.bones}
        for k in res.motion.bones:
            if (k.name, k.frame) in inter:
                self.assertEqual(k.interpolation, inter[(k.name, k.frame)])

    def test_bones_the_target_lacks_pass_through_and_are_reported(self):
        m = dance()
        m.bones.append(key("左髪１", 5, axis_angle((1.0, 0.0, 0.0), 10.0)))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        kept = [k for k in res.motion.bones if k.name == "左髪１"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].rotation, m.bones[-1].rotation)
        self.assertIn("左髪１", res.report["missing_bones"])


if __name__ == "__main__":
    unittest.main()
