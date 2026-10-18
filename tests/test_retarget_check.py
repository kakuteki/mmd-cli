"""tools/retarget_check.py: the measures of a retargeted dance against its source, checked on small bodies where the answer
is known: a hand kept on the head counts as kept and one taken off it as lost; an arm in the hips is counted and one kept
out is not; a planted foot that slides or floats is counted and one held still on the floor is not."""
import math
import unittest

import numpy as np

from tests import test_retarget as T
from tests.retarget_fixtures import MIKU, RIN, axis_angle, blob_centre, humanoid_bytes, key, motion
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


def turned(m, bone, axis, degrees, frames):
    """the motion with `bone`'s turn on every frame of `frames` turned further by `degrees` about `axis` (its parent's
    frame), keyed on each of those frames"""
    tr = check.RT.Track([k for k in m.bones if k.name == bone])
    _, rot = tr.sample(np.asarray(frames))
    q = check.RT.qaxis(np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis), np.radians(degrees))
    keys = [key(bone, int(f), tuple(float(v) for v in check.RT.qmul(q, r))) for f, r in zip(frames, rot)]
    return motion(*[k for k in m.bones if k.name != bone], *keys)


def shifted(m, bone, dy=0.0, scale=1.0, frames=0):
    """the motion with `bone`'s key positions scaled by `scale` and raised by dy, and every key `frames` later"""
    out = []
    for k in m.bones:
        p = k.position
        if k.name == bone:
            p = (p[0] * scale, p[1] * scale + dy, p[2] * scale)
        out.append(T.vmd.BoneKey(k.name, k.frame + frames, p, k.rotation, k.interpolation, raw_name=k.raw_name))
    return T.vmd.Motion(model_name=m.model_name, bones=out)


def long_dance(last=150, seed=7):
    """5 s: the trunk, the arms, the left elbow, the head and the centre keyed every 10 frames at random, the left foot
    stepping 1.5 units (12 cm) along x and back every 30 frames (standing still 20 of them), the right foot standing"""
    rng = np.random.default_rng(seed)
    keys = []
    for f in range(0, last + 1, 10):
        keys += [key("上半身", f, axis_angle((0.0, 1.0, 0.0), float(rng.uniform(-30, 30)))),
                 key("左腕", f, axis_angle((0.0, 0.0, 1.0), float(rng.uniform(-50, 30)))),
                 key("右腕", f, axis_angle((0.0, 0.0, 1.0), float(rng.uniform(-30, 50)))),
                 key("左ひじ", f, axis_angle((0.0, 1.0, 0.0), float(rng.uniform(0, 70)))),
                 key("頭", f, axis_angle((0.0, 1.0, 0.0), float(rng.uniform(-25, 25)))),
                 key("センター", f, position=(float(rng.uniform(-0.3, 0.3)), float(rng.uniform(-1.2, -0.6)), float(rng.uniform(-0.3, 0.3))))]
    x = 0.0
    for f in range(0, last + 1, 30):
        keys += [key("左足ＩＫ", f, position=(x, 0.0, 0.0)), key("左足ＩＫ", min(f + 20, last), position=(x, 0.0, 0.0))]
        x = 1.5 - x
    keys.append(key("右足ＩＫ", 0))
    return motion(*keys)


def jump_dance(last=60, jump=(30, 37), up=0.5):
    """the centre down 1 unit, both feet standing, and both feet up by `up` (4 cm) over the frames `jump` (None: no jump)"""
    keys = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", last, position=(0.0, -1.0, 0.0))]
    for s in ("左足ＩＫ", "右足ＩＫ"):
        keys += [key(s, 0), key(s, last)]
        if jump:
            keys += [key(s, jump[0] - 1), key(s, jump[0], position=(0.0, up, 0.0)), key(s, jump[1], position=(0.0, up, 0.0)),
                     key(s, jump[1] + 1)]
    return motion(*keys)


class ContactsTest(unittest.TestCase):
    def test_a_hand_turned_off_the_head_makes_a_lost_run(self):
        # the retarget's hand on the head, then the target's arm lowered 30 degrees: the touch is lost on every frame
        m = head_touch_dance()
        kept = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), {"feet": False, "clear": False}).motion
        off = turned(kept, "左腕", (0.0, 0.0, 1.0), -30.0, range(0, 10))
        r = check.measure(m, T.body(T.MIKU_DATA), off, T.body(T.RIN_DATA))
        head = r["contacts"]["左"]["head"]
        self.assertEqual(head["source_touch_frames"], 10)
        self.assertEqual(head["kept_frames"], 0)
        self.assertEqual(head["lost_runs"], [[0, 9]])
        self.assertEqual(r["summary"]["contacts_lost_runs"], sum(len(p["lost_runs"]) for s in r["contacts"].values() for p in s.values()))
        self.assertGreaterEqual(r["summary"]["contacts_lost_runs"], 1)

    def test_the_summary_share_is_the_parts_kept_frames_over_their_touches(self):
        m = head_touch_dance()
        for params in (T.PURE, {"feet": False, "clear": False}):
            out = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), params).motion
            r = check.measure(m, T.body(T.MIKU_DATA), out, T.body(T.RIN_DATA))
            rows = [p for s in r["contacts"].values() for p in s.values()]
            touch, kept = sum(p["source_touch_frames"] for p in rows), sum(p["kept_frames"] for p in rows)
            self.assertEqual(r["summary"]["contact_frames"], touch)
            self.assertAlmostEqual(r["summary"]["contacts_kept_share"], round(kept / touch, 4))

    def test_a_held_touch_is_a_resting_run_and_a_short_one_is_not(self):
        m = head_touch_dance()
        kept = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), {"feet": False, "clear": False}).motion
        r = check.measure(m, T.body(T.MIKU_DATA), kept, T.body(T.RIN_DATA))
        runs_ = r["contacts"]["左"]["head"]["runs"]
        self.assertEqual([(x["first"], x["last"], x["frames"]) for x in runs_], [(0, 9, 10)])
        self.assertTrue(runs_[0]["resting"])
        self.assertLess(runs_[0]["speed_cm_s"], 1.0)
        self.assertEqual(runs_[0]["kept_frames"], 10)
        # the hand point lies on the head's blob (a sphere of vertices): its nearest vertex is about its distance away
        self.assertLess(abs(runs_[0]["source_mesh_cm"] - max(runs_[0]["source_cm"]["p50"], 0.0)), 1.5)
        self.assertEqual(r["summary"]["contact_runs"], sum(len(p["runs"]) for s in r["contacts"].values() for p in s.values()))
        self.assertEqual(r["summary"]["contact_frames_resting"], 10)
        self.assertEqual(r["summary"]["contacts_kept_share_resting"], 1.0)
        short = check.measure(m, T.body(T.MIKU_DATA), kept, T.body(T.RIN_DATA), last=1)["contacts"]["左"]["head"]["runs"]
        self.assertEqual([(x["first"], x["last"]) for x in short], [(0, 1)])
        self.assertFalse(short[0]["resting"])

    def test_a_run_rests_when_it_is_long_and_slow(self):
        self.assertTrue(check.resting(check.RESTING_MIN, check.RESTING_SPEED - 1.0))
        self.assertFalse(check.resting(check.RESTING_MIN - 1, 0.0))                # too short
        self.assertFalse(check.resting(30, check.RESTING_SPEED + 1.0))             # too fast: the hand passes by

    def test_the_resting_share_counts_the_resting_runs_kept_frames(self):
        m = head_touch_dance()
        pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE).motion
        r = check.measure(m, T.body(T.MIKU_DATA), pure, T.body(T.RIN_DATA))
        runs_ = [x for s in r["contacts"].values() for p in s.values() for x in p["runs"] if x["resting"]]
        self.assertEqual(r["summary"]["contact_frames_resting"], sum(x["frames"] for x in runs_))
        self.assertEqual(r["summary"]["contacts_kept_share_resting"], round(sum(x["kept_frames"] for x in runs_) / sum(x["frames"] for x in runs_), 4))
        self.assertLess(r["summary"]["contacts_kept_share_resting"], 0.1)

    def test_a_run_speed_is_the_points_speed_in_the_parts_frame(self):
        local = np.zeros((12, 3))
        local[:, 0] = 0.1 * np.arange(12)                  # 0.1 unit a frame: 0.8 cm x 30 = 24 cm/s
        self.assertAlmostEqual(check.run_speed(local, 3, 8), 24.0, places=6)
        local[6:, 0] = local[6, 0]                          # still from frame 6
        self.assertAlmostEqual(check.run_speed(local, 6, 11), 0.0, places=6)

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
        self.assertEqual(a["target"]["左"]["part_frames_over_1cm"]["hips"], 5)
        self.assertEqual(b["target"]["左"]["frames_over_1cm"], 0)
        self.assertEqual(a["source"]["左"]["frames_over_1cm"], 0)     # the source's own arm clears its hips

    def test_a_body_without_finger_bones_is_measured_with_its_hands_at_the_wrists(self):
        # mv_inspect's 体の触れ on a body without the middle finger (tests/mvi_fixtures' Rin) failed on the missing bones:
        # its hand is measured at the wrist, and a forearm in the hips is still counted
        data = humanoid_bytes(RIN, T.RIN_BLOBS, twist_axis=True, name="rin-no-fingers", fingers=False)
        body = check.RT.Body.loads(data)
        c0, R = blob_centre(RIN, T.RIN_BLOBS, "下半身")
        found = None
        for a in range(-70, -20, 2):
            for b in (-30, -20, -10, 0, 10, 20, 30):
                m = motion(*T.arm_pose_keys(a, b, 0))
                w = T.world(data, m, ["左ひじ", "左手首"], [0])[0]
                e, h = np.asarray(w["左ひじ"][0]), np.asarray(w["左手首"][0])
                deep = max(0.3 + R - float(np.linalg.norm(e + t * (h - e) - np.asarray(c0))) for t in np.linspace(0, 1, 15))
                if 0.2 < deep < 0.5:
                    found = m
                    break
            if found:
                break
        self.assertIsNotNone(found)
        frames = np.arange(0, 1)
        rows = check.arms_in(check.Pose(body, found, frames), body, check.parts_of(body))
        self.assertEqual(rows["左"]["frames_over_1cm"], 1)
        self.assertGreater(rows["左"]["part_frames_over_1cm"]["hips"], 0)
        self.assertEqual(rows["右"]["frames_over_1cm"], 0)
        rep = check.measure(found, body, found, body)                       # a dance against itself: no finger bones
        self.assertEqual(rep["summary"]["contact_frames"], 0)

    def test_the_source_is_measured_by_the_same_rule(self):
        # a dance measured against itself: the source's hand on its head is counted apart just as the target's is
        m = head_touch_dance()
        a = check.measure(m, T.body(T.MIKU_DATA), m, T.body(T.MIKU_DATA))["arms_in_body"]
        self.assertGreater(a["target"]["左"]["touched_part_frames_over_1cm"], 0)
        for k in ("frames_over_0.5cm", "frames_over_1cm", "touched_part_frames_over_1cm", "deepest_cm"):
            self.assertEqual(a["source"]["左"][k], a["target"]["左"][k], k)
        # the hand on the head the source touches is excused: with the source's touches the arm's deepest point a frame
        # is never deeper than without them, and on the touching frames shallower (the hand is the deepest in the head)
        src = T.body(T.MIKU_DATA)
        pose = check.Pose(src, m, np.arange(0, 10))
        parts = check.parts_of(src)
        ds = check.part_distances(pose, parts, check.hand_points(pose, "左"))
        touching = {"左": {p: np.minimum(v["palm"], v["tip"]) < check.TOUCH for p, v in ds.items()}}
        excused = check.arms_in(pose, src, parts, touching)["左"]["_deep"]
        counted = check.arms_in(pose, src, parts, None)["左"]["_deep"]
        self.assertTrue(np.all(excused <= counted + 1e-9))
        self.assertGreater(float(np.max(counted - excused)), 0.05)


class PartsTest(unittest.TestCase):
    def test_a_ribbon_takes_the_bones_under_its_parent(self):
        part = check.parts_of(T.body(T.RIBBON_DATA))["ribbon"]
        loop = np.array([0.9, 19.3, -0.1]) - np.array(RIN["頭"])
        self.assertLess(float(part.distance(loop[None, :])[0]), -0.2)
        self.assertLess(float(part.distance((loop * np.array([-1.0, 1.0, 1.0]))[None, :])[0]), -0.2)


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

    def test_a_planted_foot_lifted_or_sunk_is_counted_on_every_frame(self):
        # the held toe stand of the test above, the target's left foot raised 2 cm or lowered 2 cm: it floats over 1 cm
        # on all its plant's frames, or goes under the floor on all of them
        l = MIKU["足首"][2] - MIKU["つま先"][2]
        h = MIKU["足首"][1] - MIKU["つま先"][1]
        th = math.radians(10.0)
        rise = l * math.sin(th) - h * (1 - math.cos(th))
        q = axis_angle((1.0, 0.0, 0.0), -10.0)
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("左足ＩＫ", 0, q, position=(0.0, rise, 0.0)),
                   key("左足ＩＫ", 9, q, position=(0.0, rise, 0.0)), key("右足ＩＫ", 0))
        held = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        up = check.measure(m, T.body(T.MIKU_DATA), shifted(held, "左足ＩＫ", dy=0.25), T.body(T.RIN_SHOE_DATA))
        down = check.measure(m, T.body(T.MIKU_DATA), shifted(held, "左足ＩＫ", dy=-0.25), T.body(T.RIN_SHOE_DATA))
        a, b = up["plants"]["左"], down["plants"]["左"]
        self.assertEqual((a["plants"], a["frames"], a["toe_plants"]), (1, 10, 1))
        self.assertEqual(a["float_over_1cm_pct"], 100.0)
        self.assertEqual(a["toe_float_over_1cm_pct"], 100.0)
        self.assertEqual(a["under_floor_frames"], 0)
        self.assertEqual(b["float_over_1cm_pct"], 0.0)
        self.assertEqual(b["under_floor_frames"], 10)
        self.assertEqual(up["summary"]["toe_float_over_1cm_pct"], 100.0)        # the right foot has no toe plant
        self.assertGreater(up["summary"]["plant_float_over_1cm_pct"], 0.0)
        self.assertEqual(down["summary"]["plant_under_floor_frames"], 10)

    def test_a_foot_moving_fast_at_its_rest_height_is_not_a_plant(self):
        m = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("左足ＩＫ", 0), key("左足ＩＫ", 9, position=(0.9, 0.0, 0.0)),
                   key("右足ＩＫ", 0))
        src = T.body(T.MIKU_DATA)
        found = check.source_plants(check.Pose(src, m, np.arange(0, 10)), src)
        self.assertEqual(found["左"], [])
        self.assertEqual(len(found["右"]), 1)

    def test_a_shoe_sliding_on_the_floor_off_the_sources_plants_is_counted(self):
        # the source's left foot 4 cm up (no plant), the target's dragged along the floor 1.6 mm a frame: 9 steps in a
        # third of a second, 259 cm a minute, all of it elsewhere than on the source's plants; the right foot stands
        src = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("左足ＩＫ", 0, position=(0.0, 0.5, 0.0)),
                     key("左足ＩＫ", 9, position=(0.0, 0.5, 0.0)), key("右足ＩＫ", 0))
        tgt = motion(key("センター", 0, position=(0.0, -1.0, 0.0)), key("左足ＩＫ", 0), key("左足ＩＫ", 9, position=(0.18, 0.0, 0.0)),
                     key("右足ＩＫ", 0))
        r = check.measure(src, T.body(T.RIN_SHOE_DATA), tgt, T.body(T.RIN_SHOE_DATA))
        left = r["plants"]["左"]["floor_slide_cm_per_min"]
        self.assertEqual(r["plants"]["左"]["plants"], 0)
        self.assertEqual(left["in_source_plants"], 0.0)
        self.assertGreater(left["elsewhere"], 200.0)
        self.assertLess(left["elsewhere"], 300.0)
        right = r["plants"]["右"]["floor_slide_cm_per_min"]
        self.assertLess(right["in_source_plants"] + right["elsewhere"], 1.0)
        self.assertAlmostEqual(r["summary"]["floor_slide_off_plants_cm_per_min"], left["elsewhere"] + right["elsewhere"], places=1)


class FloorSlideOnPlantTest(unittest.TestCase):
    def test_a_shoe_dragged_on_the_sources_plant_slides_there(self):
        # PlantsTest's pivot: the source's left foot turning on its ball, its right foot standing; the retarget holds both,
        # then the right foot is dragged 1.6 mm a frame along x: its slide is on the source's plant, the held left foot's
        # is small (the fixture's coarse shoe: the slowest touching vertex lies up to 0.1 units from the ball)
        m = PlantsTest.pivot(PlantsTest())
        held = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), {"hands": False, "clear": False}).motion
        tr = T.retarget.Track([k for k in held.bones if k.name == "右足ＩＫ"])
        pos, rot = tr.sample(np.arange(0, 11))
        drag = [T.vmd.BoneKey("右足ＩＫ", f, (pos[f][0] + 0.02 * f, pos[f][1], pos[f][2]), T.fk.stored(tuple(rot[f])))
                for f in range(0, 11)]
        slid = T.vmd.Motion(model_name=held.model_name, bones=[k for k in held.bones if k.name != "右足ＩＫ"] + drag)
        r = check.measure(m, T.body(T.MIKU_DATA), slid, T.body(T.RIN_SHOE_DATA))["plants"]
        self.assertGreater(r["右"]["floor_slide_cm_per_min"]["in_source_plants"], 150.0)
        self.assertLess(r["右"]["floor_slide_cm_per_min"]["elsewhere"], 1.0)
        self.assertLess(r["左"]["floor_slide_cm_per_min"]["in_source_plants"], 80.0)


class ChoreTest(unittest.TestCase):
    """the choreography a retarget must keep, on dances whose change is known"""

    def measure(self, src, tgt, data=None):
        b = T.body(data or T.RIN_SHOE_DATA)
        return check.measure(src, b, tgt, b)

    def test_a_dance_against_itself_keeps_everything(self):
        m = long_dance()
        r = self.measure(m, m)
        ch, s = r["chore"], r["summary"]
        self.assertEqual(s["chore_timing_lag0_share_min"], 1.0)
        for side in ("左", "右"):
            self.assertLess(ch["hand_directions"][side]["deg"]["max"], 1e-3)
        self.assertLess(ch["head_turn_deg"]["max"], 1e-3)
        self.assertLess(ch["chest_turn_deg"]["max"], 1e-3)
        self.assertEqual(ch["legs_ratio"], 1.0)
        self.assertGreaterEqual(ch["steps"]["左"]["steps"], 3)
        self.assertAlmostEqual(ch["steps"]["左"]["length_ratio"]["p50"], 1.0, places=4)
        self.assertLess(ch["steps"]["左"]["direction_deg"]["max"], 1e-3)

    def test_the_hands_are_read_in_the_chests_frame(self):
        # the target's trunk turned 30 degrees with everything on it: the hands point the same way from the shoulders in
        # the chest's frame, while the chest and the head turn 30 degrees in the world
        m = long_dance()
        r = self.measure(m, turned(m, "上半身", (0.0, 1.0, 0.0), 30.0, range(0, 151)))
        ch = r["chore"]
        for side in ("左", "右"):
            self.assertLess(ch["hand_directions"][side]["deg"]["max"], 1e-3)
        self.assertAlmostEqual(ch["chest_turn_deg"]["p50"], 30.0, places=3)
        self.assertAlmostEqual(ch["head_turn_deg"]["p50"], 30.0, places=3)

    def test_a_later_dance_shows_its_lag(self):
        m = long_dance()
        r = self.measure(m, shifted(m, "", frames=2))
        t = r["chore"]["timing"]
        for n in ("左手首", "頭", "センター"):
            self.assertEqual(t[n]["lag_p50"], 2.0, n)
            self.assertLess(t[n]["lag0_share"], 0.2, n)
        self.assertLess(r["summary"]["chore_timing_lag0_share_min"], 0.2)

    def test_an_arm_turned_shows_in_its_hands_direction(self):
        m = long_dance()
        r = self.measure(m, turned(m, "左腕", (0.0, 0.0, 1.0), 20.0, range(0, 151)))
        hd = r["chore"]["hand_directions"]
        self.assertGreater(hd["左"]["deg"]["p50"], 12.0)
        self.assertLess(hd["左"]["deg"]["max"], 20.01)
        self.assertLess(hd["右"]["deg"]["max"], 1e-3)
        self.assertAlmostEqual(r["summary"]["chore_hand_direction_p90_deg"], hd["左"]["deg"]["p90"], places=3)

    def test_shorter_steps_show_in_their_ratio(self):
        m = long_dance()
        r = self.measure(m, shifted(m, "左足ＩＫ", scale=0.5))
        st = r["chore"]["steps"]["左"]
        self.assertAlmostEqual(st["length_ratio"]["p50"], 0.5, places=3)
        self.assertLess(st["direction_deg"]["max"], 1e-3)

    def test_a_jump_is_matched_and_a_missing_or_new_one_is_seen(self):
        jump, flat = jump_dance(), jump_dance(jump=None)
        same = self.measure(jump, jump)["chore"]["jumps"]
        self.assertEqual((same["source"], same["matched"], same["target_only"]), (1, 1, []))
        self.assertEqual(same["rows"][0]["target_peak_shift"], 0)
        gone = self.measure(jump, flat)["chore"]["jumps"]
        self.assertEqual((gone["source"], gone["matched"]), (1, 0))
        new = self.measure(flat, jump)["chore"]["jumps"]
        self.assertEqual((new["source"], new["matched"], len(new["target_only"])), (0, 0, 1))


def stepping(jump_at=None, dx=1.2, up=0.0, last=12):
    """the centre down 1 unit, the right foot standing, the left foot `up` units over the floor at x 0 and, from frame
    jump_at to the next (None: never), moved dx along x (1.2: 9.6 cm in one frame)"""
    keys = [key("センター", 0, position=(0.0, -1.0, 0.0)), key("センター", last, position=(0.0, -1.0, 0.0)), key("右足ＩＫ", 0),
            key("右足ＩＫ", last), key("左足ＩＫ", 0, position=(0.0, up, 0.0))]
    if jump_at is None:
        keys.append(key("左足ＩＫ", last, position=(0.0, up, 0.0)))
    else:
        keys += [key("左足ＩＫ", jump_at, position=(0.0, up, 0.0)), key("左足ＩＫ", jump_at + 1, position=(dx, up, 0.0)),
                 key("左足ＩＫ", last, position=(dx, up, 0.0))]
    return motion(*keys)


class PopsTest(unittest.TestCase):
    """a shoe near the floor that jumps along it in one frame where the source's foot does not (review_integ 2026-10-17:
    the retarget gave a turning foot's hold back in one frame, the song's 128.0 s 13.7 cm with the shoe 1 cm up, and the
    later layers put that frame on the floor)"""

    def measure(self, src, tgt):
        b = T.body(T.RIN_SHOE_DATA)
        return check.measure(src, b, tgt, b)

    def test_a_jump_along_the_floor_the_source_does_not_make_is_counted(self):
        r = self.measure(stepping(), stepping(jump_at=5))
        p = r["plants"]["左"]["pops"]
        self.assertEqual(len(p["rows"]), 1)
        row = p["rows"][0]
        self.assertEqual(row["frame"], 5)
        self.assertAlmostEqual(row["step_cm"], 9.6, delta=0.3)
        self.assertLess(row["source_step_cm"], 0.1)
        self.assertTrue(row["own"])
        self.assertEqual((p["count"], p["own"]), (1, 1))
        self.assertEqual(r["plants"]["右"]["pops"]["count"], 0)
        self.assertEqual(r["summary"]["pops_not_in_source"], 1)

    def test_the_sources_own_jump_is_not_the_targets(self):
        m = stepping(jump_at=5)
        r = self.measure(m, m)
        p = r["plants"]["左"]["pops"]
        self.assertEqual(p["count"], 1)
        self.assertFalse(p["rows"][0]["own"])
        self.assertAlmostEqual(p["rows"][0]["source_step_cm"], 9.6, delta=0.3)
        self.assertEqual(r["summary"]["pops_not_in_source"], 0)

    def test_a_source_body_made_from_a_spec_reads_its_own_shoe(self):
        # the song's source body is a .json spec on a model (tools/retarget.Body.from_spec): it keeps the model's mesh, so
        # the source's move is its own shoe's, as the target's is
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "rin.pmx"), "wb") as f:
                f.write(T.RIN_SHOE_DATA)
            with open(os.path.join(d, "body.json"), "w", encoding="utf-8") as f:
                json.dump({"model": "rin.pmx", "rest": {}}, f)
            src = check.RT.Body.load(os.path.join(d, "body.json"))
            self.assertIsNotNone(getattr(src, "doc", None))
            m = stepping(jump_at=5)
            r = check.measure(m, src, m, T.body(T.RIN_SHOE_DATA))
            row = r["plants"]["左"]["pops"]["rows"][0]
            self.assertAlmostEqual(row["source_step_cm"], row["step_cm"], delta=0.05)
            self.assertFalse(row["own"])

    def test_a_jump_high_over_the_floor_or_a_short_one_is_not_a_pop(self):
        for tgt in (stepping(jump_at=5, up=0.5), stepping(jump_at=5, dx=0.75)):       # 4 cm up; a 6 cm step
            r = self.measure(stepping(), tgt)
            self.assertEqual(r["plants"]["左"]["pops"]["rows"], [])
            self.assertEqual(r["summary"]["pops_not_in_source"], 0)


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
