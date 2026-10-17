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


_BODIES = {}


def body(data):
    """the tool's body of a model (one per model: its surfaces are built once)"""
    if data not in _BODIES:
        _BODIES[data] = retarget.Body.loads(data)
    return _BODIES[data]


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


# ---- the per-frame machinery ---------------------------------------------------------------------------------------------

def fk_values(m, name, frames):
    """(positions, rotations as applied) of a bone's keys as mmd_cli.fk samples them"""
    keys = fk.tracks_of(m).get(name)
    kf = [k.frame for k in keys]
    out = [fk.sample(keys, f, kf) for f in frames]
    return np.array([p for p, _ in out]), np.array([fk.applied(q) for _, q in out])


def same_turn(a, b):
    return np.abs(np.sum(np.asarray(a) * np.asarray(b), axis=-1))


class TrackTest(unittest.TestCase):
    """the keys of one bone: MMD's values between them, and a key added without changing the motion"""

    def keys(self):
        return [key("左腕", 0, position=(0.0, 0.0, 0.0)),
                key("左腕", 6, axis_angle((0.2, 1.0, 0.1), 50.0), position=(1.0, -2.0, 0.5)),
                key("左腕", 15, axis_angle((1.0, 0.0, 0.3), -80.0), position=(0.5, 1.0, 2.0), curve=(64, 0, 64, 127)),
                key("左腕", 22, axis_angle((0.0, 0.0, 1.0), 30.0), position=(0.0, 0.0, 0.0), curve=(10, 90, 100, 30))]

    def test_values_are_mmds(self):
        m = motion(*self.keys())
        tr = retarget.Track(m.bones)
        frames = list(range(-2, 26))
        p, q = tr.sample(np.array(frames))
        fp, fq = fk_values(m, "左腕", frames)
        np.testing.assert_allclose(p, fp, atol=1e-6)
        self.assertGreater(float(same_turn(q, fq).min()), 1 - 1e-9)

    def test_a_split_keeps_the_motion(self):
        m = motion(*self.keys())
        tr = retarget.Track(m.bones)
        for f in (3, 9, 12, 19):
            tr.split(f)
        self.assertEqual(list(tr.frames), [0, 3, 6, 9, 12, 15, 19, 22])
        frames = np.arange(0, 23)
        p, q = tr.sample(frames)
        fp, fq = fk_values(m, "左腕", list(frames))
        # straight segments split exactly; a curved one within the curve's 1/127 steps
        np.testing.assert_allclose(p[:7], fp[:7], atol=1e-9)
        np.testing.assert_allclose(p, fp, atol=0.03)
        self.assertGreater(float(same_turn(q, fq).min()), math.cos(math.radians(1.0) / 2))
        # and through the VMD the same values come back
        again = retarget.Track(tr.keys())
        p2, q2 = again.sample(frames)
        np.testing.assert_allclose(p2, p, atol=1e-5)

    def test_fitting_targets_adds_keys_only_where_they_are_needed(self):
        m = motion(key("左腕", 0), key("左腕", 30, axis_angle((0.0, 0.0, 1.0), 60.0)))
        tr = retarget.Track(m.bones)
        frames = np.arange(0, 31)
        _, base = tr.sample(frames)
        # a bump of up to 12 degrees about X between frames 10 and 20
        bump = np.where((frames >= 10) & (frames <= 20), np.sin(np.pi * (frames - 10) / 10.0), 0.0) * math.radians(12.0)
        want = retarget.qmul(retarget.qaxis(np.array([1.0, 0.0, 0.0]), bump), base)
        added = tr.fit_rotations(frames, want, tol_deg=0.5)
        _, got = tr.sample(frames)
        self.assertLess(float(np.degrees(retarget.qangle(retarget.qmul(retarget.qconj(want), got))).max()), 0.5)
        self.assertGreater(added, 0)
        self.assertLess(added, 12)
        self.assertEqual([f for f in tr.frames if f < 9 or f > 21], [0, 30])


# ---- the contacts ------------------------------------------------------------------------------------------------------

from tests.retarget_fixtures import RIN_SHOE, blob_centre  # noqa: E402

leg_ik = load_tool("leg_ik")
RIN_SHOE_DATA = humanoid_bytes(RIN, RIN_BLOBS, twist_axis=True, name="rin", shoe=RIN_SHOE)


def legs(data, m, frames):
    return leg_ik.solve(leg_ik.LegRig.loads(data), m, list(frames))


def foot_point(leg, offset):
    """world positions of a point given relative to the ankle at rest, carried by the solved foot"""
    return leg["ankle"] + leg_ik.qrot(leg["q_foot"], np.asarray(offset, dtype=np.float64))


class FeetTest(unittest.TestCase):
    """a foot that stands on the floor in the source stands still on the floor in the target, and the hips stay"""

    def test_a_toe_stand_reaches_the_floor_by_the_ankle_not_the_hips(self):
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        th = math.radians(10.0)
        rise = l * math.sin(th) - h * (1 - math.cos(th))
        q = axis_angle((1.0, 0.0, 0.0), -10.0)
        # the knees well bent: MMD's IK leaves a nearly straight leg short of its goal (tools/leg_ik.py, saba)
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, q, position=(0.0, rise, 0.0)), key("左足ＩＫ", 20, q, position=(0.0, rise, 0.0)),
                   key("右足ＩＫ", 0), key("右足ＩＫ", 20))
        src = legs(MIKU_DATA, m, range(0, 21))
        toe_s = foot_point(src["左"], np.subtract(MIKU["つま先"], MIKU["足首"]))
        self.assertLess(float(np.abs(toe_s[:, 1] - MIKU["つま先"][1]).max()), 1e-3)     # the source's toe is on its floor
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        toe_off = (RIN["足首"][0], RIN_SHOE["sole"], RIN["足首"][2] - RIN_SHOE["toe_ahead"])
        toe_off = np.subtract(toe_off, RIN["足首"])
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 21))["左"], toe_off)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 21))["左"], toe_off)
        self.assertGreater(float(before[:, 1].min()) - RIN_SHOE["sole"], 0.03)               # the mapping alone floats
        self.assertLess(float(np.abs(after[:, 1] - RIN_SHOE["sole"]).max()), 0.0125)        # on the floor within 1 mm
        out = {(k.name, k.frame): k for k in res.motion.bones}
        ref = {(k.name, k.frame): k for k in pure.motion.bones}
        for f in (0, 20):
            self.assertAlmostEqual(out[("左足ＩＫ", f)].position[1], ref[("左足ＩＫ", f)].position[1], places=4)   # the ankle's height
            np.testing.assert_allclose(out[("センター", f)].position, ref[("センター", f)].position, atol=1e-9)   # the hips
        self.assertEqual(res.report["feet"]["左"]["kinds"]["toe"], 1)

    def test_a_foot_pivoting_on_its_ball_keeps_the_targets_ball_still(self):
        ankle = np.array(MIKU["足首"])
        ball = np.array([MIKU["足先EX"][0], MIKU["つま先"][1], MIKU["足先EX"][2]])
        turns = [axis_angle((0.0, 1.0, 0.0), 4.0 * f) for f in range(0, 11)]
        goals = [ball - leg_ik.qrot(np.array(q), ball - ankle) for q in turns]
        heel = [(0.0, 0.0, 0.0, 1.0)] * 11
        for _ in range(5):                       # the source's own foot flat and turning on its ball, as MMD's IK puts it
            keys = [key("左足ＩＫ", f, q, position=tuple(g - ankle)) for f, (q, g) in enumerate(zip(turns, goals))]
            keys += [key("左足首", f, k) for f, k in enumerate(heel)]
            m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), *keys, key("右足ＩＫ", 0))
            sol = legs(MIKU_DATA, m, range(0, 11))["左"]
            b = foot_point(sol, ball - ankle)
            goals = [g + np.array([ball[0] - p[0], 0.0, ball[2] - p[2]]) for g, p in zip(goals, b)]
            heel = [tuple(retarget.qmul(retarget.qconj(sol["q_shin"][f]), np.array(q))) for f, q in enumerate(turns)]
        self.assertLess(float(np.linalg.norm(b[:, [0, 2]] - ball[[0, 2]], axis=1).max()), 0.005)
        ball_t = np.array([RIN["足先EX"][0], RIN_SHOE["sole"], RIN["足先EX"][2]]) - np.array(RIN["足首"])
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 11))["左"], ball_t)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 11))["左"], ball_t)

        def drift(p):
            return float(np.linalg.norm(p[:, [0, 2]] - p[0, [0, 2]], axis=1).max())
        self.assertGreater(drift(before), 0.1)
        self.assertLess(drift(after), 0.0125)
        self.assertLess(float(np.abs(after[:, 1] - RIN_SHOE["sole"]).max()), 0.0125)


def pivot_motion(rise, rate=24.0, n=21):
    """the whole figure turning about the vertical line through its left toe (全ての親 turning `rate` degrees a frame
    about that line), the left foot pitched 10 degrees down on its toe and `rise` over the source's floor (the trace
    leaves a turning foot over the floor): the toe stays where it is and the rest sweeps round it, a pivot; the knees
    well bent, the right foot swept round with the figure"""
    pitch = axis_angle((1.0, 0.0, 0.0), -10.0)
    base = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", n - 1, position=(0.0, -1.0, 0.0)),
            key("左足ＩＫ", 0, pitch, position=(0.0, rise, 0.0)), key("左足ＩＫ", n - 1, pitch, position=(0.0, rise, 0.0)),
            key("右足ＩＫ", 0), key("右足ＩＫ", n - 1)]
    toe = foot_point(legs(MIKU_DATA, motion(*base), [0])["左"], np.subtract(MIKU["つま先"], MIKU["足首"]))[0]
    turn = []
    for f in range(n):
        q = axis_angle((0.0, 1.0, 0.0), rate * f)
        p = toe - leg_ik.qrot(np.array(q), toe)
        turn.append(key("全ての親", f, q, position=(float(p[0]), 0.0, float(p[2]))))
    return motion(*turn, *base)


# the source's foot IK raised this much stands its toe on the floor pitched 10 degrees down
TOE_RISE_10 = ((MIKU["足首"][2] - MIKU["つま先"][2]) * math.sin(math.radians(10.0))
               - (MIKU["足首"][1] - MIKU["つま先"][1]) * (1 - math.cos(math.radians(10.0))))


class PivotTest(unittest.TestCase):
    """the whole figure turning on its left toe, which the trace leaves 1 cm over the floor: the target's toe is put on
    the floor by the foot's pitch and held where it is while the figure turns round it (on Rin's other proportions the
    mapping alone sweeps it round a circle along the floor); the hips are left as they are"""

    def test_a_pivoting_toe_goes_onto_the_floor_and_stays_put(self):
        m = pivot_motion(TOE_RISE_10 + 0.12)
        src = legs(MIKU_DATA, m, range(0, 21))
        toe_s = foot_point(src["左"], np.subtract(MIKU["つま先"], MIKU["足首"]))
        self.assertLess(float(np.abs(toe_s[:, 1] - MIKU["つま先"][1] - 0.12).max()), 2e-3)   # 1 cm up, all through
        self.assertLess(float(np.linalg.norm(toe_s[:, [0, 2]] - toe_s[0, [0, 2]], axis=1).max()), 2e-3)   # a pivot
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        toe_off = np.subtract((RIN["足首"][0], RIN_SHOE["sole"], RIN["足首"][2] - RIN_SHOE["toe_ahead"]), RIN["足首"])
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 21))["左"], toe_off)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 21))["左"], toe_off)
        self.assertGreater(float(before[:, 1].min()) - RIN_SHOE["sole"], 0.03)               # the mapping alone floats
        self.assertGreater(float(np.linalg.norm(before[:, [0, 2]] - before[0, [0, 2]], axis=1).max()), 0.1)   # and sweeps
        self.assertLess(float(np.abs(after[:, 1] - RIN_SHOE["sole"]).max()), 0.0125)        # on the floor within 1 mm
        drift = np.linalg.norm(after[:, [0, 2]] - np.mean(after[:, [0, 2]], axis=0), axis=1)
        self.assertLess(float(drift.max()), 0.0125)                                           # held where it is within 1 mm
        out = {(k.name, k.frame): k for k in res.motion.bones}
        ref = {(k.name, k.frame): k for k in pure.motion.bones}
        for f in (0, 20):
            np.testing.assert_allclose(out[("センター", f)].position, ref[("センター", f)].position, atol=1e-9)   # the hips


class CarriedTest(unittest.TestCase):
    """a foot carried low and fast along the floor while the other foot is up (a step: the trace's 198.9-199.3 s carries
    the right foot 1-2 cm over the floor) is left as the mapping puts it, not pressed onto the floor and dragged along it"""

    def test_a_foot_carried_low_and_fast_is_left_as_mapped(self):
        pitch = axis_angle((1.0, 0.0, 0.0), -10.0)
        rise = TOE_RISE_10 + 0.12                                         # the source's toe 1 cm over its floor
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, pitch, position=(0.0, rise, 0.0)), key("左足ＩＫ", 20, pitch, position=(3.0, rise, 0.0)),
                   key("右足ＩＫ", 0, position=(0.0, 1.0, 0.0)), key("右足ＩＫ", 20, position=(0.0, 1.0, 0.0)))   # 36 cm/s; right up
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["右"]["plants"], 0)                        # the other foot does not stand
        toe_off = np.subtract((RIN["足首"][0], RIN_SHOE["sole"], RIN["足首"][2] - RIN_SHOE["toe_ahead"]), RIN["足首"])
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 21))["左"], toe_off)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 21))["左"], toe_off)
        self.assertGreater(float(before[:, 1].min()) - RIN_SHOE["sole"], 0.03)
        np.testing.assert_allclose(after, before, atol=1e-3)

    def test_a_carried_shoe_keeps_the_sources_clearance(self):
        # the source carries its flat foot 4.5 mm over its floor (its shoe off the floor of main's contact_check, 4 mm);
        # the mapping scales the height to 3.9 mm, on that floor: the shoe is kept as high over the floor as the source's
        rise = 0.056
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, position=(0.0, rise, 0.0)), key("左足ＩＫ", 20, position=(3.0, rise, 0.0)),
                   key("右足ＩＫ", 0, position=(0.0, 1.0, 0.0)), key("右足ＩＫ", 20, position=(0.0, 1.0, 0.0)))
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE).motion
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        src = legs(MIKU_DATA, m, range(0, 21))["左"]
        pts, floor = retarget.sole_points(body(MIKU_DATA), "左")
        src_low = np.min(np.stack([foot_point(src, p)[:, 1] for p in pts.values()], axis=1), axis=1) - floor
        self.assertGreater(float(src_low.min()), 0.04)                                       # the source's shoe off the floor
        self.assertLess(float((lowest_sole(RIN_SHOE_DATA, RIN_SHOE, pure, range(0, 21)) - src_low).min()), -0.005)   # lower
        self.assertGreater(float((lowest_sole(RIN_SHOE_DATA, RIN_SHOE, res, range(0, 21)) - src_low).min()), -0.004)


class HoldTest(unittest.TestCase):
    """the hold along the floor of a standing foot changes only while the foot is off the floor: the left foot comes
    down from the air, slides into a stand on the floor (14 cm/s), stands drifting 5 cm/s (the hold keeps its middle),
    slides out and lifts; the right foot stands throughout.  On the floor next to the stand the target's foot moves as
    the mapping moves it (the hold's offset was taken in the air before it and is given back in the air after it), not
    eased in or out along the floor"""

    def test_the_hold_moves_the_foot_only_in_the_air(self):
        xs, x = [], -0.6
        for f in range(35):
            xs.append(x)
            x += 0.022 if 9 <= f < 24 else 0.06
        ys = [0.3 if (f <= 4 or f >= 30) else 0.0 for f in range(35)]
        keys = [key("左足ＩＫ", f, position=(xs[f], ys[f], 0.0)) for f in range(35)]
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 34, position=(0.0, -1.0, 0.0)), *keys,
                   key("右足ＩＫ", 0), key("右足ＩＫ", 34))
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["左"]["plants"], 1)
        ball = np.array([RIN["足先EX"][0], RIN_SHOE["sole"], RIN["足先EX"][2]]) - np.array(RIN["足首"])
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 35))["左"], ball)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 35))["左"], ball)
        held = after[12:22, [0, 2]]
        self.assertLess(float(np.linalg.norm(held - held.mean(axis=0), axis=1).max()), 0.0125)   # the stand is held
        for f in (5, 6, 7, 25, 26, 27, 28):                                  # steps on the floor before and after it
            step_t = after[f + 1, [0, 2]] - after[f, [0, 2]]
            step_m = before[f + 1, [0, 2]] - before[f, [0, 2]]
            self.assertLess(float(np.linalg.norm(step_t - step_m)), 0.012, f)


class DragTest(unittest.TestCase):
    """a foot low over the floor and moving while the other foot stands (it carries no weight: a small step, a drag) is
    left as the mapping puts it, not dragged along the floor"""

    def test_a_low_moving_foot_beside_a_standing_one_stays_off_the_floor(self):
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        th = math.radians(10.0)
        rise = l * math.sin(th) - h * (1 - math.cos(th)) + 0.12            # the source's toe 1 cm over its floor
        pitch = axis_angle((1.0, 0.0, 0.0), -10.0)
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, pitch, position=(0.0, rise, 0.0)), key("左足ＩＫ", 20, pitch, position=(1.0, rise, 0.0)),
                   key("右足ＩＫ", 0), key("右足ＩＫ", 20))
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["右"]["plants"], 1)                        # the other foot stands throughout
        toe_off = np.subtract((RIN["足首"][0], RIN_SHOE["sole"], RIN["足首"][2] - RIN_SHOE["toe_ahead"]), RIN["足首"])
        before = foot_point(legs(RIN_SHOE_DATA, pure.motion, range(0, 21))["左"], toe_off)
        after = foot_point(legs(RIN_SHOE_DATA, res.motion, range(0, 21))["左"], toe_off)
        self.assertGreater(float(before[:, 1].min()) - RIN_SHOE["sole"], 0.03)
        np.testing.assert_allclose(after, before, atol=1e-3)


class SpinPitchTest(unittest.TestCase):
    """the pivoting toe of PivotTest left 1.9 cm over the floor: Rin's shorter foot reaches it only pitched 25 degrees
    past the source's; the pitch changes at most TOUCH_PITCH_MAX from the source's and the ankle comes down the rest (a
    foot lifting off is not flicked down: the song's 86.07 s pitched 50 degrees for one frame)"""

    def test_a_moving_foots_pitch_stays_near_the_sources(self):
        m = pivot_motion(TOE_RISE_10 + 0.24)                               # the source's toe 1.9 cm over its floor
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        leg = legs(RIN_SHOE_DATA, res, range(0, 21))["左"]
        self.assertLess(float(np.abs(retarget.foot_pitch(leg["q_foot"]) - 10.0).max()), retarget.TOUCH_PITCH_MAX + 0.5)
        toe_off = np.subtract((RIN["足首"][0], RIN_SHOE["sole"], RIN["足首"][2] - RIN_SHOE["toe_ahead"]), RIN["足首"])
        self.assertLess(float(np.abs(foot_point(leg, toe_off)[:, 1] - RIN_SHOE["sole"]).max()), 0.0125)


RIN_SPRING = dict(RIN_SHOE, spring=0.15)          # the sole's front 4 of 12 rows turned up, the toe 1.2 cm
RIN_SPRING_DATA = humanoid_bytes(RIN, RIN_BLOBS, twist_axis=True, name="rin-spring", shoe=RIN_SPRING)
RIN_SHORT = dict(RIN_SHOE, toe_ahead=1.0)         # the toe 8 cm ahead of the ankle
RIN_SHORT_DATA = humanoid_bytes(RIN, RIN_BLOBS, twist_axis=True, name="rin-short", shoe=RIN_SHORT)


def lowest_sole(data, shoe, m, frames):
    """the lowest of the shoe's bottom vertices (the fixture's box, its toe spring) over the floor, per frame"""
    ax, ay, az = RIN["足首"]
    offs = []
    for i in range(12):
        for k in range(3):
            z = az + shoe["heel_back"] - (shoe["heel_back"] + shoe["toe_ahead"]) * i / 11.0
            y = shoe["sole"] + shoe.get("spring", 0.0) * max(0.0, (i - 7) / 4.0) ** 2
            offs.append(np.array([ax + shoe["half_width"] * (k - 1), y, z]) - np.array(RIN["足首"]))
    leg = legs(data, m, frames)["左"]
    return np.min(np.stack([foot_point(leg, o)[:, 1] for o in offs], axis=1), axis=1) - shoe["sole"]


class SpinShellTest(unittest.TestCase):
    """the pivoting toe of PivotTest on a shoe whose sole turns up at the toe: the shoe's lowest vertex goes onto the
    floor (not a point of the toe's tip at the floor's height, under which the turned-up sole would stay over it)"""

    def test_the_shoe_itself_reaches_the_floor(self):
        m = pivot_motion(TOE_RISE_10 + 0.12)
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SPRING_DATA), PURE).motion
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SPRING_DATA), {"hands": False, "clear": False}).motion
        self.assertGreater(float(lowest_sole(RIN_SPRING_DATA, RIN_SPRING, pure, range(0, 21)).min()), 0.03)
        self.assertLess(float(np.abs(lowest_sole(RIN_SPRING_DATA, RIN_SPRING, res, range(0, 21))).max()), 0.0125)


class PlantShellTest(unittest.TestCase):
    """a foot standing still on the floor stands on the shoe itself: a flat foot rolled sideways (Hibikase's flat feet
    roll 7 degrees in the median) on its lower edge, not on the middle of its sole with that edge 4 mm under the floor;
    a toe stand on a sole turned up at the toe on its lowest vertex, not on a point of the tip at the floor's height"""

    def test_a_rolled_flat_foot_stands_on_the_shoes_edge(self):
        roll = axis_angle((0.0, 0.0, 1.0), -8.0)                  # the outer (+x) edge of the left foot down
        base = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                key("左足ＩＫ", 0, roll), key("左足ＩＫ", 20, roll), key("右足ＩＫ", 0), key("右足ＩＫ", 20)]
        shin = legs(MIKU_DATA, motion(*base), [0])["左"]["q_shin"][0]
        ankle_key = tuple(retarget.qmul(retarget.qconj(shin), np.array(roll)))
        m = motion(*base, key("左足首", 0, ankle_key), key("左足首", 20, ankle_key))
        src = legs(MIKU_DATA, m, range(0, 21))["左"]
        turn = np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(src["q_foot"] * np.array(roll), axis=1)), 0, 1)))
        self.assertLess(float(turn.max()), 0.5)                    # the source's foot rolled as keyed
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["左"]["kinds"]["flat"], 1)
        low = lowest_sole(RIN_SHOE_DATA, RIN_SHOE, res.motion, range(0, 21))
        self.assertLess(float(np.abs(low).max()), 0.0125)                          # the shoe on the floor within 1 mm
        out = {(k.name, k.frame): k for k in res.motion.bones}
        ref = {(k.name, k.frame): k for k in pure.motion.bones}
        for f in (0, 20):
            np.testing.assert_allclose(out[("センター", f)].position, ref[("センター", f)].position, atol=1e-9)   # the hips

    def test_a_rolled_flat_foot_stands_level_on_its_sole(self):
        # the sole flat on the floor, as a foot standing at rest: its side axis level, its ankle at the rest height (the
        # analysis pack's a05 reads the floor from the ankle's and the toe's heights over their rest: a foot lifted onto
        # its rolled edge is a hovering foot there), every vertex of the sole on the floor; the foot's heading kept
        roll = axis_angle((0.0, 0.0, 1.0), -8.0)
        yaw = axis_angle((0.0, 1.0, 0.0), 30.0)
        turn = tuple(retarget.qmul(np.array(yaw), np.array(roll)))
        base = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                key("左足ＩＫ", 0, turn), key("左足ＩＫ", 20, turn), key("右足ＩＫ", 0), key("右足ＩＫ", 20)]
        shin = legs(MIKU_DATA, motion(*base), [0])["左"]["q_shin"][0]
        ankle_key = tuple(retarget.qmul(retarget.qconj(shin), np.array(turn)))
        m = motion(*base, key("左足首", 0, ankle_key), key("左足首", 20, ankle_key))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHOE_DATA), {"hands": False, "clear": False})
        leg = legs(RIN_SHOE_DATA, res.motion, range(0, 21))["左"]
        side = leg_ik.qrot(leg["q_foot"], np.array([1.0, 0.0, 0.0]))
        fwd = leg_ik.qrot(leg["q_foot"], np.array([0.0, 0.0, -1.0]))
        self.assertLess(float(np.abs(side[:, 1]).max()), math.sin(math.radians(0.5)))           # level across
        heading = np.degrees(np.arctan2(-fwd[:, 0], -fwd[:, 2]))
        np.testing.assert_allclose(heading, 30.0, atol=0.5)                                       # the heading kept
        self.assertLess(float(np.abs(leg["ankle"][:, 1] - RIN["足首"][1]).max()), 0.0125)          # the ankle at rest height
        offs = [np.array([RIN["足首"][0] + RIN_SHOE["half_width"] * (k - 1), RIN_SHOE["sole"],
                          RIN["足首"][2] + RIN_SHOE["heel_back"] - (RIN_SHOE["heel_back"] + RIN_SHOE["toe_ahead"]) * i / 11.0])
                - np.array(RIN["足首"]) for i in range(12) for k in range(3)]
        sole = (np.stack([foot_point(leg, o)[:, 1] for o in offs], axis=1) - RIN_SHOE["sole"]).reshape(21, 12, 3)
        self.assertLess(float(np.abs(sole.min(axis=(1, 2))).max()), 0.0125)                      # the shoe on the floor
        self.assertLess(float(np.abs(sole[:, :, 0] - sole[:, :, 2]).max()), 0.0125)               # its two edges level
        # (along the foot the source's own pitch is kept: -0.3 degrees here, the toe IK's)

    def test_a_toe_stand_the_target_cannot_reach_is_not_flicked_to_a_steep_foot(self):
        # the source on its toe with its ankle at its rest height (0.5 mm under it): Rin's foot cannot pitch onto its toe
        # without going under the floor, and pitched near vertical (63 degrees on this short shoe) its toe comes back up to
        # the floor; the song's 137.77 s pitched the left foot from 7.8 to 58.9 degrees for one frame that way
        q = axis_angle((1.0, 0.0, 0.0), -8.0)
        low = -0.006 / retarget.scale_of(body(MIKU_DATA), body(RIN_SHORT_DATA))
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, q, position=(0.0, low, 0.0)), key("左足ＩＫ", 20, q, position=(0.0, low, 0.0)),
                   key("右足ＩＫ", 0), key("右足ＩＫ", 20))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SHORT_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["左"]["kinds"]["toe"], 1)
        src = legs(MIKU_DATA, m, range(0, 21))["左"]
        leg = legs(RIN_SHORT_DATA, res.motion, range(0, 21))["左"]
        change = retarget.foot_pitch(leg["q_foot"]) - retarget.foot_pitch(src["q_foot"])
        self.assertLess(float(np.abs(change).max()), retarget.TOUCH_PITCH_MAX + 0.5)

    def test_a_toe_stand_on_a_turned_up_toe_stands_on_the_shoe(self):
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        th = math.radians(10.0)
        rise = l * math.sin(th) - h * (1 - math.cos(th))
        q = axis_angle((1.0, 0.0, 0.0), -10.0)
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", 20, position=(0.0, -1.0, 0.0)),
                   key("左足ＩＫ", 0, q, position=(0.0, rise, 0.0)), key("左足ＩＫ", 20, q, position=(0.0, rise, 0.0)),
                   key("右足ＩＫ", 0), key("右足ＩＫ", 20))
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_SPRING_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_SPRING_DATA), {"hands": False, "clear": False})
        self.assertEqual(res.report["feet"]["左"]["kinds"]["toe"], 1)
        self.assertGreater(float(lowest_sole(RIN_SPRING_DATA, RIN_SPRING, pure.motion, range(0, 21)).min()), 0.03)
        low = lowest_sole(RIN_SPRING_DATA, RIN_SPRING, res.motion, range(0, 21))
        self.assertLess(float(np.abs(low).max()), 0.0125)
        out = {(k.name, k.frame): k for k in res.motion.bones}
        ref = {(k.name, k.frame): k for k in pure.motion.bones}
        for f in (0, 20):
            self.assertAlmostEqual(out[("左足ＩＫ", f)].position[1], ref[("左足ＩＫ", f)].position[1], places=4)   # the ankle's height
            np.testing.assert_allclose(out[("センター", f)].position, ref[("センター", f)].position, atol=1e-9)   # the hips


def palm(data, rest, m, side, frames):
    w = world(data, m, [side + "手首", side + "中指１"], frames)
    return np.array([np.asarray(w[f][side + "手首"][0]) + 0.5 * (np.asarray(w[f][side + "中指１"][0]) - np.asarray(w[f][side + "手首"][0]))
                     for f in frames])


def sphere_distance(data, rest, blobs, bone, m, points, frames):
    """distance of points [F, 3] from the blob sphere on the bone, carried by the bone"""
    c0, r = blob_centre(rest, blobs, bone)
    w = world(data, m, [bone], frames)
    out = []
    for n, f in enumerate(frames):
        p, q = w[f][bone]
        c = np.asarray(p) + leg_ik.qrot(np.asarray(q), np.subtract(c0, rest[bone]))
        out.append(float(np.linalg.norm(points[n] - c)) - r)
    return np.array(out)


def arm_pose_keys(a, b, g):
    return [key("左腕", 0, tuple(retarget.qnorm(retarget.qmul(axis_angle((0.0, 0.0, 1.0), a), axis_angle((0.0, 1.0, 0.0), b))))),
            key("左ひじ", 0, axis_angle((0.0, 1.0, 0.0), g))]


class HandsTest(unittest.TestCase):
    """a hand on the head stays on the head; a hand far from the body is left alone"""

    def test_a_hand_on_the_head_stays_on_the_head(self):
        k = RIN_BLOBS[0][2] / MIKU_BLOBS[0][2]
        best = None
        for a in range(60, 171, 10):                 # raise the arm, swing it, bend the elbow: palms on the source's head
            for b in range(-60, 61, 20):
                for g in range(0, 151, 15):
                    m = motion(*arm_pose_keys(a, b, g))
                    d = sphere_distance(MIKU_DATA, MIKU, MIKU_BLOBS, "頭", m, palm(MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                    if abs(d - 0.05) > 0.08:
                        continue
                    pure = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
                    dp = sphere_distance(RIN_DATA, RIN, RIN_BLOBS, "頭", pure.motion, palm(RIN_DATA, RIN, pure.motion, "左", [0]), [0])[0]
                    miss = abs(dp - max(d, 0.0) * k)
                    if best is None or miss > best[0]:
                        best = (miss, d, a, b, g)
        self.assertGreater(best[0], 0.15)                # the mapping alone takes this hand off the head (or into it)
        m = motion(*arm_pose_keys(*best[2:]))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), {"feet": False, "clear": False})
        d_res = sphere_distance(RIN_DATA, RIN, RIN_BLOBS, "頭", res.motion, palm(RIN_DATA, RIN, res.motion, "左", [0]), [0])[0]
        self.assertLess(abs(d_res - max(best[1], 0.0) * k), 0.06)

    def test_a_hand_far_from_the_body_is_left_alone(self):
        m = motion(*arm_pose_keys(30, 0, 0))
        pure = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), {"feet": False})
        a = {(k.name, k.frame): k for k in pure.motion.bones}
        b = {(k.name, k.frame): k for k in res.motion.bones}
        self.assertEqual(set(a), set(b))
        for n in a:
            self.assertGreater(abs(float(np.dot(a[n].rotation, b[n].rotation))), 1 - 1e-9)


def arm_penetration(data, rest, blobs, m, frames, radii=(0.35, 0.3, 0.25)):
    """the deepest a target arm (capsules on its bones, the tool's default radii) goes into the hips' blob sphere"""
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
    """an arm that clears the source's hips but would go into the target's is kept out"""

    def test_an_arm_kept_out_of_the_hips(self):
        found = None
        for a in range(-60, -24, 2):
            for b in (-20, -10, 0, 10, 20):
                m = motion(*arm_pose_keys(a, b, 0))
                src = arm_penetration(MIKU_DATA, MIKU, MIKU_BLOBS, m, [0])
                pure = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), PURE)
                tgt = arm_penetration(RIN_DATA, RIN, RIN_BLOBS, pure.motion, [0])
                if src < -0.05 and 0.1 < tgt < 0.4:
                    found = (a, b, src, tgt)
                    break
            if found:
                break
        self.assertIsNotNone(found)
        m = motion(*arm_pose_keys(found[0], found[1], 0))
        res = retarget.layer(m, body(MIKU_DATA), body(RIN_DATA), {"feet": False, "hands": False})
        self.assertLess(arm_penetration(RIN_DATA, RIN, RIN_BLOBS, res.motion, [0]), 0.03)


# ---- the command and the source's fit ----------------------------------------------------------------------------------

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402


def toe_dance(rest, pitches=(0, 6, 12, 18, 24, 30, 36, 42), hold=6):
    """the left foot standing on its toe at each pitch for `hold` frames (the rise its own toe needs), the knees bent"""
    l = rest["足首"][2] - rest["つま先"][2]
    h = rest["足首"][1] - rest["つま先"][1]
    keys = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("右足ＩＫ", 0)]
    f = 0
    for p in pitches:
        th = math.radians(p)
        rise = l * math.sin(th) - h * (1 - math.cos(th))
        q = axis_angle((1.0, 0.0, 0.0), -p)
        keys.append(key("左足ＩＫ", f, q, position=(0.0, rise, 0.0)))
        keys.append(key("左足ＩＫ", f + hold - 1, q, position=(0.0, rise, 0.0)))
        f += hold
    return motion(*keys)


class CommandTest(unittest.TestCase):
    def files(self, d):
        paths = {}
        for name, data in (("miku.pmx", MIKU_DATA), ("rin.pmx", RIN_SHOE_DATA)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as f:
                f.write(data)
        return paths

    def test_run_writes_the_dance_and_its_report(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.files(d)
            dance = os.path.join(d, "dance.vmd")
            vmd.dump(dance_with_toes(), dance)
            out, rep = os.path.join(d, "out.vmd"), os.path.join(d, "r.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = retarget.main(["run", dance, p["miku.pmx"], p["rin.pmx"], out, "--report", rep])
            self.assertEqual(code, 0, buf.getvalue())
            self.assertTrue(json.loads(buf.getvalue())["ok"])
            m = vmd.load(out)
            self.assertTrue(any(k.name == "左腕" for k in m.bones))
            with open(rep, encoding="utf-8") as f:
                r = json.load(f)
            self.assertAlmostEqual(r["scale"], (RIN["足"][1] - RIN["足首"][1]) / (MIKU["足"][1] - MIKU["足首"][1]), places=6)
            self.assertIn("feet", r)

    def test_run_refuses_writing_over_its_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.files(d)
            dance = os.path.join(d, "dance.vmd")
            vmd.dump(dance_with_toes(), dance)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = retarget.main(["run", dance, p["miku.pmx"], p["rin.pmx"], dance])
            self.assertEqual(code, 2)

    def test_fit_tells_the_foot_the_dance_was_made_on(self):
        m = toe_dance(MIKU)
        res = retarget.fit(m, [("miku", body(MIKU_DATA)), ("rin", body(RIN_SHOE_DATA))])
        own = res["miku"]["toe"]["左"]
        other = res["rin"]["toe"]["左"]
        self.assertGreater(own["frames"], 20)
        self.assertLess(abs(own["height_signed_median_cm"]), 0.1)            # on its own floor where it stands on the toe
        self.assertGreater(abs(other["height_signed_median_cm"]), 1.0)       # Rin's shorter foot leaves its toe up
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        for row in (own, other):                                            # either body reads the same foot off the dance
            self.assertAlmostEqual(row["fit"]["l"], l, delta=0.05)
            self.assertAlmostEqual(row["fit"]["h"], h, delta=0.15)


def dance_with_toes():
    """the arms and centre of dance(), the left foot of toe_dance()"""
    m = dance()
    m.bones = [k for k in m.bones if k.name != "左足ＩＫ"] + [k for k in toe_dance(MIKU).bones if k.name == "左足ＩＫ"]
    return m


class ArmIkTest(unittest.TestCase):
    """the arm's IK puts the wrist where it is wanted, the elbow on the side it was, the hand's world turn kept; with or
    without twist bones between the joints"""

    def check(self, data):
        b = retarget.Body.loads(data)
        m = motion(key("左腕", 0, axis_angle((0.2, 0.3, 1.0), -30.0)), key("左腕捩", 0, axis_angle((1.0, -0.5, 0.0), 25.0)),
                   key("左ひじ", 0, axis_angle((0.0, 1.0, 0.0), 50.0)), key("左手首", 0, axis_angle((0.0, 0.0, 1.0), 20.0)))
        trk = retarget.tracks_of(m.bones)
        frames = np.arange(0, 1)
        ap = retarget.arm_pose(b, trk, frames, "左")
        S, E, W = ap["左腕"][0], ap["左ひじ"][0], ap["左手首"][0]
        hand = retarget.hand_world(b, trk, frames, "左")
        want = W + np.array([[-0.6, 0.9, -0.4]])
        Es, Ws = retarget.arm_ik(S, E, W, want)
        np.testing.assert_allclose(Ws, want, atol=1e-6)
        loc = retarget.arm_locals(b, trk, frames, "左", Es, Ws, hand[1])
        keys = [k for k in m.bones if k.name not in loc] + [key(n, 0, tuple(q[0])) for n, q in loc.items()]
        out = motion(*keys)
        w = world(data, out, ["左腕", "左ひじ", "左手首"], [0])[0]
        np.testing.assert_allclose(np.asarray(w["左手首"][0]), want[0], atol=1e-5)
        np.testing.assert_allclose(np.asarray(w["左ひじ"][0]), Es[0], atol=1e-5)
        self.assertGreater(abs(float(np.dot(np.asarray(w["左手首"][1]), hand[1][0]))), 1 - 1e-9)
        # the upper arm and the forearm keep their lengths: the wrist really moved by the arm, not by a stretch
        self.assertAlmostEqual(float(np.linalg.norm(np.subtract(w["左ひじ"][0], w["左腕"][0]))), float(np.linalg.norm(E - S)), places=6)

    def test_with_twist_bones(self):
        self.check(RIN_DATA)

    def test_without_twist_bones(self):
        self.check(humanoid_bytes(RIN, RIN_BLOBS, name="rin-no-twist", twists=False))


BIG_HEAD = (("頭", (0.0, 1.43, -0.35), 1.8, 400),) + tuple(RIN_BLOBS[1:])
BIG_HEAD_DATA = humanoid_bytes(RIN, BIG_HEAD, twist_axis=True, name="rin-big-head")


def upper_arm_in_head(data, rest, blobs, m, frames=(0,), radius=0.35):
    """the deepest the upper arm's half by the elbow (a capsule of the tool's default radius) goes into the head's sphere"""
    out = -1e9
    for f in frames:
        w = world(data, m, ["左腕", "左ひじ", "頭"], [f])[f]
        c0, R = blob_centre(rest, blobs, "頭")
        p, q = w["頭"]
        c = np.asarray(p) + leg_ik.qrot(np.asarray(q), np.subtract(c0, rest["頭"]))
        S, E = np.asarray(w["左腕"][0]), np.asarray(w["左ひじ"][0])
        out = max(out, max(radius + R - float(np.linalg.norm(S + t * (E - S) - c)) for t in np.linspace(0.5, 1.0, 11)))
    return out


class ClearUpperArmTest(unittest.TestCase):
    """an upper arm raised beside the head: clear of the source's head, into the target's (a bigger head) -> kept out
    by turning the whole arm about the shoulder"""

    def test_an_upper_arm_kept_out_of_the_head(self):
        best = None
        for a in range(90, 181, 6):
            for b in range(-60, 61, 10):
                m = motion(*arm_pose_keys(a, b, 0))
                s = upper_arm_in_head(MIKU_DATA, MIKU, MIKU_BLOBS, m)
                t = upper_arm_in_head(BIG_HEAD_DATA, RIN, BIG_HEAD, retarget.layer(m, body(MIKU_DATA), body(BIG_HEAD_DATA), PURE).motion)
                if s < -0.05 and (best is None or t > best[0]):
                    best = (t, a, b)
        self.assertGreater(best[0], 0.15)
        m = motion(*arm_pose_keys(best[1], best[2], 0))
        out = retarget.layer(m, body(MIKU_DATA), body(BIG_HEAD_DATA), {"feet": False, "hands": False}).motion
        self.assertLess(upper_arm_in_head(BIG_HEAD_DATA, RIN, BIG_HEAD, out), 0.03)

    def held_cases(self):
        """palms on the source's head whose mapped upper arm goes into the big head, each with the least depth any elbow
        position round its shoulder-wrist line would leave (measured on the sphere over 72 positions, from the mapping)"""
        k = BIG_HEAD[0][2] / MIKU_BLOBS[0][2]
        out = []
        for a in range(60, 181, 10):
            for b in range(-60, 61, 20):
                for g in range(0, 151, 15):
                    m = motion(*arm_pose_keys(a, b, g))
                    d = sphere_distance(MIKU_DATA, MIKU, MIKU_BLOBS, "頭", m, palm(MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                    if abs(d - 0.05) > 0.08:
                        continue
                    held = retarget.layer(m, body(MIKU_DATA), body(BIG_HEAD_DATA), {"feet": False, "clear": False}).motion
                    t = upper_arm_in_head(BIG_HEAD_DATA, RIN, BIG_HEAD, held)
                    if t <= 0.05:
                        continue
                    w = world(BIG_HEAD_DATA, held, ["左腕", "左ひじ", "左手首", "頭"], [0])[0]
                    S, E, W = (np.asarray(w[n][0]) for n in ("左腕", "左ひじ", "左手首"))
                    c0, R = blob_centre(RIN, BIG_HEAD, "頭")
                    c = np.asarray(w["頭"][0]) + leg_ik.qrot(np.asarray(w["頭"][1]), np.subtract(c0, RIN["頭"]))
                    u = unit(W - S)
                    along = float(np.dot(E - S, u))
                    radial = (E - S) - along * u
                    v1 = unit(radial)
                    v2 = np.cross(u, v1)
                    least = min(max(0.35 + R - float(np.linalg.norm(S + t_ * (Ek - S) - c)) for t_ in np.linspace(0.5, 1.0, 11))
                                for Ek in (S + along * u + np.linalg.norm(radial) * (math.cos(p) * v1 + math.sin(p) * v2)
                                           for p in np.linspace(0, 2 * math.pi, 72, endpoint=False)))
                    out.append((t, least, d * k, (a, b, g)))
        return out

    def test_a_held_hand_stays_when_the_elbow_alone_can_clear_the_head(self):
        cases = [c for c in self.held_cases() if c[1] < -0.02]
        self.assertTrue(cases)
        t, least, want, pose = max(cases)
        out = retarget.layer(motion(*arm_pose_keys(*pose)), body(MIKU_DATA), body(BIG_HEAD_DATA), {"feet": False}).motion
        d = sphere_distance(BIG_HEAD_DATA, RIN, BIG_HEAD, "頭", out, palm(BIG_HEAD_DATA, RIN, out, "左", [0]), [0])[0]
        self.assertLess(abs(d - max(want, 0.0)), 0.08)                            # the hand stays on the head
        self.assertLess(upper_arm_in_head(BIG_HEAD_DATA, RIN, BIG_HEAD, out), 0.03)  # the elbow turned the upper arm out

    def test_the_arm_leaves_the_head_when_no_elbow_position_can(self):
        cases = [c for c in self.held_cases() if c[1] > 0.1]
        self.assertTrue(cases)
        t, least, want, pose = max(cases)
        out = retarget.layer(motion(*arm_pose_keys(*pose)), body(MIKU_DATA), body(BIG_HEAD_DATA), {"feet": False}).motion
        self.assertLess(upper_arm_in_head(BIG_HEAD_DATA, RIN, BIG_HEAD, out), 0.03)  # no arm through the head, even for a touch


BIG_HIPS = tuple(RIN_BLOBS[:3]) + (("下半身", (0.0, -1.2, 0.4), 1.6, 300),)
BIG_HIPS_DATA = humanoid_bytes(RIN, BIG_HIPS, twist_axis=True, name="rin-big-hips")


class ClearNearHandTest(unittest.TestCase):
    """a palm near the source's hips but not on them (2 to 3 cm off), that the hand's relation alone leaves closer to the
    target's (bigger) hips: the hand comes no closer to them than the source's hand is to its own (scaled), as far as the
    hand's thickness, and no further"""

    def test_a_hand_near_the_hips_keeps_off_them(self):
        k = BIG_HIPS[3][2] / MIKU_BLOBS[3][2]
        hand_r = 0.25                                   # the tool's hand radius on a body without hand vertices
        best = None
        for a in range(-78, -41, 3):                 # the arm down, swung back, the elbow bent: the palm by the hips
            for b in (-50, -40, -30, -20, -10):
                for g in (50, 60, 70, 80, 90):
                    m = motion(*arm_pose_keys(a, b, g))
                    d = sphere_distance(MIKU_DATA, MIKU, MIKU_BLOBS, "下半身", m, palm(MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                    if not 0.2 <= d <= 0.35:
                        continue
                    rel = retarget.layer(m, body(MIKU_DATA), body(BIG_HIPS_DATA), {"feet": False, "clear": False}).motion
                    t = sphere_distance(BIG_HIPS_DATA, RIN, BIG_HIPS, "下半身", rel, palm(BIG_HIPS_DATA, RIN, rel, "左", [0]), [0])[0]
                    gap = min(hand_r, d * k) - t            # how much closer than that the relation puts the palm
                    if best is None or gap > best[0]:
                        best = (gap, d, (a, b, g))
        self.assertGreater(best[0], 0.06)
        out = retarget.layer(motion(*arm_pose_keys(*best[2])), body(MIKU_DATA), body(BIG_HIPS_DATA), {"feet": False}).motion
        t = sphere_distance(BIG_HIPS_DATA, RIN, BIG_HIPS, "下半身", out, palm(BIG_HIPS_DATA, RIN, out, "左", [0]), [0])[0]
        self.assertGreater(t, min(hand_r, best[1] * k) - 0.03)
        self.assertLess(t, best[1] * k + 0.1)


# ---- the parts and the fingers ----------------------------------------------------------------------------------------

RIBBON = (("リボン親", "頭", (0.0, 19.0, -0.1), False), ("リボン1", "リボン親", (0.9, 19.3, -0.1), True))
RIBBON_BLOBS = tuple(RIN_BLOBS) + (("リボン親", (0.0, 0.0, 0.0), 0.2, 40), ("左リボン1", (0.0, 0.0, 0.0), 0.4, 80))
RIBBON_DATA = humanoid_bytes(RIN, RIBBON_BLOBS, twist_axis=True, name="rin-ribbon", extra=RIBBON)


class PartsTest(unittest.TestCase):
    """a ribbon whose loops hang on bones under リボン親 (Sour's Rin: 左リボン1..3, 右リボン1..3 carry 299 of its 422
    vertices) is one part with them"""

    def test_a_ribbon_takes_the_bones_under_its_parent(self):
        s = retarget.surfaces(body(RIBBON_DATA))["ribbon"]
        loop = np.array([0.9, 19.3, -0.1]) - np.array(RIN["頭"])      # the left loop's centre in the head's rest frame
        self.assertLess(float(s.sdf(loop[None, :])[0]), -0.2)
        self.assertLess(float(s.sdf((loop * np.array([-1.0, 1.0, 1.0]))[None, :])[0]), -0.2)


def finger_tip(data, rest, m, side, frames):
    """the middle finger's tip (中指３ past 中指２ by 0.6 of their bone) where the dance's keys put it"""
    w = world(data, m, [side + "中指２", side + "中指３"], frames)
    out = []
    for f in frames:
        m3, m2 = np.asarray(w[f][side + "中指３"][0]), np.asarray(w[f][side + "中指２"][0])
        out.append(m3 + 0.6 * (m3 - m2))
    return np.array(out)


class CurledFingerTest(unittest.TestCase):
    """a middle finger bent at its knuckle: the hand is tested where the dance's finger keys put the finger, not where
    a straight finger would be"""

    def test_a_bent_finger_kept_out_of_the_hips(self):
        best = None
        for a in range(-78, -41, 6):
            for b in (-50, -30, -10):
                for g in (30, 60, 90):
                    for c in (-90, -60, 60, 90):
                        keys = arm_pose_keys(a, b, g) + [key("左中指１", 0, axis_angle((0.0, 0.0, 1.0), c))]
                        m = motion(*keys)
                        ds = sphere_distance(MIKU_DATA, MIKU, MIKU_BLOBS, "下半身", m, finger_tip(MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                        dp = sphere_distance(MIKU_DATA, MIKU, MIKU_BLOBS, "下半身", m, palm(MIKU_DATA, MIKU, m, "左", [0]), [0])[0]
                        if not (0.3 <= ds <= 0.6 and dp > ds + 0.2):  # the source's finger near its hips, its palm further
                            continue
                        pure = retarget.layer(m, body(MIKU_DATA), body(BIG_HIPS_DATA), PURE).motion
                        t = sphere_distance(BIG_HIPS_DATA, RIN, BIG_HIPS, "下半身", pure, finger_tip(BIG_HIPS_DATA, RIN, pure, "左", [0]), [0])[0]
                        if best is None or t < best[0]:
                            best = (t, ds, keys)
        self.assertLess(best[0], -0.1)                 # the copied turns put the bent finger into the bigger hips
        out = retarget.layer(motion(*best[2]), body(MIKU_DATA), body(BIG_HIPS_DATA), {"feet": False}).motion
        t = sphere_distance(BIG_HIPS_DATA, RIN, BIG_HIPS, "下半身", out, finger_tip(BIG_HIPS_DATA, RIN, out, "左", [0]), [0])[0]
        self.assertGreater(t, -0.03)
