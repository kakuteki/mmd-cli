"""tools/eye_gaze.py: eyes that look on their own (fixations on where the face goes, saccades that lead the head's
turns, eye contact planned where the camera stays within reach) as a 両目 track to load after the dance."""
import contextlib
import importlib.util
import io
import json
import math
import os
import random
import shutil
import tempfile
import time
import unittest

from mmd_cli import fk, mathutil, motion_edit
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, NORMAL, TAIL_IS_BONE, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("eye_gaze", os.path.join(ROOT, "tools", "eye_gaze.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eye_gaze = load_tool()
LAST = 120
EYE_CENTER = (0.0, 17.2, -0.56)
FORWARD = (0.0, 0.0, -1.0)
LIMITS = eye_gaze.Limits()


def rin_like_bytes(tip=(0.0, 19.4, -0.83)):
    """a body, a neck and a head with the eye bones laid out as on Sour's Rin: 両目 a handle above the head with its
    tip (両目先) straight ahead unless `tip` says otherwise, the eyes lower, each turning with 両目 (append ratio 1)"""
    w = Writer(bone=2)
    bones = [("全ての親", -1, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", 0, (0.0, 8.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("上半身", 1, (0.0, 12.0, 0.0), {}),
             ("首", 2, (0.0, 15.5, 0.0), {}),
             ("頭", 3, (0.0, 16.2, 0.0), {}),
             ("両目", 4, (0.0, 19.4, -0.26), {"flags": NORMAL | TAIL_IS_BONE, "tail": 8}),
             ("左目", 4, (0.41, 17.2, -0.56), {"flags": NORMAL | APPEND_ROTATE, "append": (5, 1.0)}),
             ("右目", 4, (-0.41, 17.2, -0.56), {"flags": NORMAL | APPEND_ROTATE, "append": (5, 1.0)}),
             ("両目先", 5, tuple(tip), {})]
    return w.build(name="rin-like", bones=[w.bone(n, parent=p, position=pos, **kw) for n, p, pos, kw in bones])


MODEL = pmx.loads(rin_like_bytes())


def head_turn(degrees_by_frame, axis="y", last=LAST):
    """a still dance (keys at 0 and `last`) whose head turns by the window angles given as {frame: degrees}"""
    keys = [vmd.BoneKey("全ての親", 0, (0.0, 0.0, 0.0), fk.IDENTITY), vmd.BoneKey("全ての親", last, (0.0, 0.0, 0.0), fk.IDENTITY),
            vmd.BoneKey("両目", 0, (0.0, 0.0, 0.0), fk.IDENTITY)]
    for frame, degrees in sorted(degrees_by_frame.items()):
        ui = (0.0, degrees, 0.0) if axis == "y" else (degrees, 0.0, 0.0)
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(*ui)))
    return vmd.Motion(model_name="dancer", bones=keys)


STILL = head_turn({0: 0.0})


def cam(frame, rot=(0.0, 0.0, 0.0), distance=30.0, look_at=(0.0, 17.2, 0.0)):
    return motion_edit.camera_key_from_ui({"pos": look_at, "distance": distance, "rot": rot, "fov": 30, "perspective": True},
                                          frame=frame)


def camera(*keys):
    return vmd.Motion.for_camera(cameras=list(keys))


IN_FRONT = camera(cam(0), cam(LAST))
BEHIND = camera(cam(0, (0.0, 180.0, 0.0)), cam(LAST, (0.0, 180.0, 0.0)))


def direction(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return (math.cos(p) * math.sin(y), math.sin(p), -math.cos(p) * math.cos(y))


def degrees_between(a, b):
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


def expected_yaw(camera_rot, distance=30.0, look_at=(0.0, 17.2, 0.0)):
    state = fk.CameraState(0, look_at, distance, camera_rot, 30.0)
    c = fk.camera_position(state)
    v = tuple(a - b for a, b in zip(c, EYE_CENTER))
    return math.degrees(math.atan2(v[0], -v[2])), math.degrees(math.atan2(v[1], math.hypot(v[0], v[2])))


def run_gaze(dance=STILL, cam_motion=IN_FRONT, life=False, **kw):
    return eye_gaze.gaze(MODEL, dance, cam_motion, life=life, **kw)


def world_gaze(sight, look):
    """the gaze of a look in the world"""
    return fk.rotate(sight.head, fk.rotate(eye_gaze.eye_rotation(look.yaw, look.pitch), FORWARD))


def restless(seed, last=600):
    """a head that turns to a new random angle every 7 frames (often fast, often away from the camera) and a camera
    that cuts every 90 frames"""
    rng = random.Random(seed)
    keys = [vmd.BoneKey("全ての親", 0, (0.0, 0.0, 0.0), fk.IDENTITY), vmd.BoneKey("全ての親", last, (0.0, 0.0, 0.0), fk.IDENTITY)]
    for frame in range(0, last + 1, 7):
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(rng.uniform(-15, 15), rng.uniform(-50, 50), 0.0)))
    cams = []
    for start in range(0, last, 90):
        rot = (rng.uniform(-6, 6), rng.uniform(-15, 15), 0.0)
        cams += [cam(start, rot), cam(start + 89, rot)]
    return vmd.Motion(model_name="dancer", bones=keys), camera(*cams)


class WhereSheLooksTest(unittest.TestCase):
    def test_a_camera_straight_ahead_is_looked_at_with_zero_angles(self):
        result = run_gaze()
        self.assertEqual(len(result.looks), LAST + 1)
        for look in result.looks:
            # 17.2 as float32 in the model is 7.6e-7 above the camera's 17.2: a pitch of 1.5e-6 degrees
            self.assertAlmostEqual(look.yaw, 0.0, places=4)
            self.assertAlmostEqual(look.pitch, 0.0, places=4)
            self.assertEqual(look.state, "contact")
        self.assertEqual(result.saccades, [])
        self.assertEqual(result.contacts, [(0, LAST)])
        key = [k for k in result.motion.bones if k.frame == 0][0]
        self.assertEqual(key.name, "両目")
        self.assertAlmostEqual(abs(key.rotation[3]), 1.0, places=9)

    def test_a_camera_on_the_plus_x_side_turns_the_eyes_to_her_left(self):
        yaw, pitch = expected_yaw((0.0, 10.0, 0.0))
        self.assertGreater(yaw, 9.0)
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 10.0, 0.0)), cam(LAST, (0.0, 10.0, 0.0))))
        look = result.looks[30]
        self.assertEqual(look.state, "contact")
        self.assertAlmostEqual(look.yaw, yaw, places=4)                 # + : toward +X, the model's left
        self.assertAlmostEqual(look.pitch, pitch, places=4)
        # the written key, applied by the convention of mmd_cli/fk.py, turns the gaze onto the camera
        key = [k for k in result.motion.bones if k.frame == 30 or k.frame == 0][0]
        gaze = fk.rotate(fk.applied(key.rotation), FORWARD)
        self.assertLess(degrees_between(gaze, direction(yaw, pitch)), 0.01)
        self.assertGreater(gaze[0], 0.1)
        if fk.KEY_ROTATION_SIGNS == (1.0, 1.0, 1.0):
            # under the default convention the window shows yaw as Y and pitch as X
            ui = mathutil.quat_to_ui(key.rotation)
            self.assertAlmostEqual(ui[1], yaw, places=3)
            self.assertAlmostEqual(ui[0], pitch, places=3)

    def test_a_camera_above_turns_the_eyes_up(self):
        yaw, pitch = expected_yaw((3.0, 0.0, 0.0))
        self.assertGreater(pitch, 2.5)
        result = run_gaze(cam_motion=camera(cam(0, (3.0, 0.0, 0.0)), cam(LAST, (3.0, 0.0, 0.0))))
        self.assertAlmostEqual(result.looks[10].pitch, pitch, places=4)
        self.assertAlmostEqual(result.looks[10].yaw, 0.0, places=6)
        key = [k for k in result.motion.bones if k.frame == LAST][0]
        self.assertGreater(fk.rotate(fk.applied(key.rotation), FORWARD)[1], math.sin(math.radians(2.5)))

    def test_a_rest_gaze_that_is_not_straight_ahead_is_where_the_angles_start(self):
        # review 8, F5: 両目先 10 degrees above 両目, so the eyes at rest look 10 degrees up.  A camera on that line needs
        # no turn at all; one 5 degrees below it needs a pitch of -5
        up = math.radians(10.0)
        model = pmx.loads(rin_like_bytes(tip=(0.0, 19.4 + 0.57 * math.sin(up), -0.26 - 0.57 * math.cos(up))))
        for below, pitch in ((0.0, 0.0), (5.0, -5.0)):
            a = math.radians(10.0 - below)
            look_at = (0.0, 17.2 + 30.0 * math.sin(a), -0.56 - 30.0 * math.cos(a) + 30.0)    # camera at angles 0, d 30
            result = eye_gaze.gaze(model, STILL, camera(cam(0, distance=30.0, look_at=look_at),
                                                        cam(LAST, distance=30.0, look_at=look_at)), life=False)
            self.assertEqual(result.report["eye"]["forward_from"], "両目先")
            self.assertAlmostEqual(result.report["eye"]["forward"][1], math.sin(up), places=4)
            for look in result.looks:
                self.assertAlmostEqual(look.yaw, 0.0, places=4)
                self.assertAlmostEqual(look.pitch, pitch, places=3)
                self.assertEqual(look.state, "contact")

    def test_a_camera_behind_her_gets_no_contact_and_the_eyes_stay_near_the_middle(self):
        result = run_gaze(cam_motion=BEHIND, life=True)
        self.assertEqual(result.contacts, [])
        self.assertNotIn("contact", {look.state for look in result.looks})
        free = eye_gaze.free_zone(LIMITS)
        for look in result.looks:
            self.assertLessEqual(abs(look.yaw), free.yaw + eye_gaze.DRIFT_LIMIT + 1e-9)
            self.assertLessEqual(look.pitch, free.up + eye_gaze.DRIFT_LIMIT + 1e-9)
            self.assertGreaterEqual(look.pitch, -free.down - eye_gaze.DRIFT_LIMIT - 1e-9)

    def test_a_camera_out_of_reach_is_not_stared_at_from_the_corner(self):
        # the camera 25 degrees to her left: beyond the limit by more than a contact can make up.  The old tool held the
        # eyes at the limit (a sidelong look); now they stay on where her face points
        yaw = expected_yaw((0.0, 25.0, 0.0))[0]
        self.assertGreater(yaw - eye_gaze.contact_zone(LIMITS).yaw, eye_gaze.CONTACT_ERROR)
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 25.0, 0.0)), cam(LAST, (0.0, 25.0, 0.0))))
        self.assertEqual(result.contacts, [])
        self.assertLess(max(abs(look.yaw) for look in result.looks), 0.9 * LIMITS.yaw)


class FixationTest(unittest.TestCase):
    def test_a_contact_keeps_the_eyes_on_the_camera_while_the_head_turns(self):
        dance = head_turn({0: 0.0, 60: 12.0, 120: -6.0})
        result = run_gaze(dance=dance)
        self.assertEqual(result.contacts, [(0, LAST)])
        heads = fk.world_track(MODEL, dance, ["頭"])["頭"]
        for look, sight in zip(result.looks, result.sights):
            to_camera = tuple(c - e for c, e in zip(sight.camera, sight.eye))
            self.assertLess(degrees_between(world_gaze(sight, look), to_camera), 0.3, look.frame)
        # the head turned by 12 degrees at frame 60 (to her left under the default convention), the eyes against it
        head_x = fk.rotate(heads[60][1], FORWARD)[0]
        self.assertGreater(abs(head_x), math.sin(math.radians(11.0)))
        self.assertLess(result.looks[60].yaw * head_x, 0.0)
        self.assertGreater(abs(result.looks[60].yaw), 10.0)
        self.assertEqual(result.saccades, [])

    def test_between_saccades_a_free_gaze_holds_a_point_in_the_world(self):
        # the camera behind her, the head turning 30 degrees over 120 frames: the eyes counter-rotate and the gaze
        # stays put in the world between saccades (the vestibulo-ocular reflex), and jumps on at each saccade
        dance = head_turn({0: 0.0, 120: 30.0})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        still = 0
        for i in range(1, len(result.looks)):
            if i in moving or result.looks[i].state != "free" or result.looks[i - 1].state != "free":
                continue
            a = world_gaze(result.sights[i - 1], result.looks[i - 1])
            b = world_gaze(result.sights[i], result.looks[i])
            self.assertLess(degrees_between(a, b), 0.05, i)
            still += 1
        self.assertGreater(still, 80)
        self.assertGreater(len(result.saccades), 0)

    def test_the_eyes_move_on_before_they_leave_the_free_zone(self):
        # a slow turn of 40 degrees: each saccade goes the way the head turns and the eyes never pass the free zone
        dance = head_turn({0: 0.0, 120: 40.0})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        free = eye_gaze.free_zone(LIMITS)
        self.assertLessEqual(max(abs(look.yaw) for look in result.looks), free.yaw + 1e-6)
        self.assertGreaterEqual(len(result.saccades), 2)
        for s in result.saccades:
            self.assertIn(s["reason"], ("recentre", "glance"))
            if s["reason"] == "recentre":
                after = result.looks[s["frame"] + s["frames"] - 1].base[0]
                before = result.looks[s["frame"] - 1].base[0]
                self.assertGreater(after, before, s)            # toward her left, the way she turns


class LeadTest(unittest.TestCase):
    """a20 (a): before a fast turn of the head the eyes jump the way it will turn, 2 to 4 frames ahead of it"""

    def fast_turn(self, degrees=60.0, seed=0):
        dance = head_turn({0: 0.0, 60: 0.0, 66: degrees})          # 10 degrees a frame: 300 deg/s from frame 61
        return run_gaze(dance=dance, cam_motion=BEHIND, seed=seed)

    def test_a_saccade_leads_a_fast_turn(self):
        for seed in range(4):
            result = self.fast_turn(seed=seed)
            leads = [s for s in result.saccades if s["reason"] == "lead"]
            self.assertEqual(len(leads), 1, result.saccades)
            onset = 61
            self.assertTrue(onset - eye_gaze.LEAD[1] <= leads[0]["frame"] <= onset - eye_gaze.LEAD[0], leads)
            # the a20 measure: the eye in the head moves more than 3 degrees the way of the turn in the 6 frames
            # before the head starts
            self.assertGreater(result.looks[onset].yaw - result.looks[onset - 6].yaw, 3.0)
            # nothing else moves the eyes in the frames before the lead
            others = [s for s in result.saccades if s["reason"] != "lead" and onset - eye_gaze.QUIET - 4 <= s["frame"] < onset]
            self.assertEqual(others, [])

    def test_the_lead_waits_head_still_then_holds_its_point_while_the_head_comes(self):
        result = self.fast_turn()
        lead = [s for s in result.saccades if s["reason"] == "lead"][0]
        landed = lead["frame"] + lead["frames"] - 1
        # until the head starts the eyes keep their angle in the head
        for i in range(landed, 61):
            self.assertAlmostEqual(result.looks[i].base[0], result.looks[landed].base[0], places=6)
        for i in range(landed + 1, 61):
            self.assertEqual(result.looks[i].state, "lead")
        # then the gaze stays on that point in the world while the head turns toward it (counter-rotation; to 0.1
        # degree: the soft limit bends angles past 60 % of the range a little)
        a = world_gaze(result.sights[61], result.looks[61])
        b = world_gaze(result.sights[62], result.looks[62])
        self.assertLess(degrees_between(a, b), 0.1)
        self.assertLess(result.looks[62].base[0], result.looks[61].base[0])

    def test_the_lead_lands_where_the_face_will_point_within_the_limit(self):
        result = self.fast_turn(degrees=60.0)
        lead = [s for s in result.saccades if s["reason"] == "lead"][0]
        landed = result.looks[lead["frame"] + lead["frames"] - 1].base
        # capped (60 degrees is far ahead), then through the soft limit like every angle
        self.assertAlmostEqual(landed[0], eye_gaze.soft(eye_gaze.LEAD_SHARE * LIMITS.yaw, LIMITS.yaw), places=6)
        self.assertLess(landed[0], 0.9 * LIMITS.yaw)                                    # never at the edge


class ContactPlanTest(unittest.TestCase):
    """the contacts are planned on the whole song first: where the camera stays within reach long enough"""

    def mask(self, n, *spans):
        out = [False] * n
        for a, b in spans:
            for i in range(a, b):
                out[i] = True
        return out

    def test_only_runs_of_contact_min_frames_or_more(self):
        m = eye_gaze.CONTACT_MIN
        reach = self.mask(400, (10, 10 + m), (100, 100 + m - 1), (200, 230))
        self.assertEqual(eye_gaze.contact_runs(reach, [], []), [(10, 10 + m - 1)])

    def test_shorter_runs_need_an_anchor_and_stay_fewer_than_the_long_ones(self):
        m = eye_gaze.CONTACT_MIN
        reach = self.mask(800, (10, 10 + m), (100, 100 + m), (200, 200 + m), (300, 335), (400, 432), (500, 535))
        self.assertEqual(len(eye_gaze.contact_runs(reach, [], [])), 3)
        # an anchor within ANCHOR_NEAR of two short runs (none near the third): only 3 - CONTACT_SPARE of them are
        # kept, the longer first
        anchors = [320, 420, 535 + eye_gaze.ANCHOR_NEAR + 1]
        runs = eye_gaze.contact_runs(reach, [], anchors)
        self.assertEqual(len(runs), 3 + min(2, 3 - eye_gaze.CONTACT_SPARE))
        self.assertIn((300, 334), runs)
        self.assertNotIn((400, 431), runs)
        self.assertNotIn((500, 534), runs)                                # its anchor is too far
        two_long = self.mask(800, (10, 10 + m), (100, 100 + m), (300, 335))
        self.assertEqual(eye_gaze.contact_runs(two_long, [], [320]), [(10, 10 + m - 1), (100, 100 + m - 1)])

    def test_a_long_run_is_cut_to_contact_max_with_the_anchor_two_thirds_in(self):
        big = eye_gaze.CONTACT_MAX
        reach = self.mask(1000, (0, 900))
        self.assertEqual(eye_gaze.contact_runs(reach, [], []), [(0, big - 1)])
        (a, b), = eye_gaze.contact_runs(reach, [], [500])
        self.assertEqual(b - a + 1, big)
        self.assertEqual(500 - a, 2 * big // 3)

    def test_no_contact_across_a_cut_nor_just_before_or_after_one(self):
        reach = self.mask(300, (0, 300))
        runs = eye_gaze.contact_runs(reach, [150], [])
        self.assertEqual(runs, [(0, 150 - eye_gaze.END_CLEAR - 1), (150 + eye_gaze.CUT_CLEAR, 299)])

    def test_gaps_of_two_frames_are_closed_three_are_not(self):
        m = eye_gaze.CONTACT_MIN
        self.assertEqual(eye_gaze.contact_runs(self.mask(200, (0, 30), (32, 32 + m - 30)), [], []), [(0, 31 + m - 30)])
        self.assertEqual(eye_gaze.contact_runs(self.mask(200, (0, 30), (33, 33 + m - 30)), [], []), [])

    def test_reach_is_the_contact_error_inside_the_contact_zone(self):
        zone = eye_gaze.contact_zone(LIMITS)
        self.assertLess(zone.yaw, 0.9 * LIMITS.yaw)
        self.assertLess(zone.up, 0.9 * LIMITS.up)
        self.assertLess(zone.down, 0.9 * LIMITS.down)
        inside = eye_gaze.contact_angles((zone.yaw + eye_gaze.CONTACT_ERROR - 0.5, 0.0), LIMITS)
        self.assertAlmostEqual(inside[0], zone.yaw, places=9)
        self.assertEqual(eye_gaze.reachable([((zone.yaw + 3.0, 0.0), False), ((zone.yaw + 4.0, 0.0), False),
                                             ((0.0, 0.0), True)], LIMITS), [True, False, False])


class ContactTest(unittest.TestCase):
    def test_a_camera_within_reach_too_briefly_gets_no_contact(self):
        # her head faces the camera only from frame 40 to 70 (31 frames), turned 40 degrees away otherwise
        dance = head_turn({0: 40.0, 38: 40.0, 40: 0.0, 70: 0.0, 72: 40.0})
        self.assertEqual(run_gaze(dance=dance).contacts, [])
        long_ = head_turn({0: 40.0, 18: 40.0, 20: 0.0, 90: 0.0, 92: 40.0})
        result = run_gaze(dance=long_)
        self.assertEqual(len(result.contacts), 1)
        a, b = result.contacts[0]
        self.assertGreaterEqual(b - a + 1, eye_gaze.CONTACT_MIN)
        # it starts with a saccade onto the camera that lands by the contact's first frame, and ends with a look away
        reasons = [s["reason"] for s in result.saccades]
        self.assertIn("contact", reasons)
        self.assertIn("look_away", reasons)
        start = [s for s in result.saccades if s["reason"] == "contact"][0]
        self.assertLessEqual(start["frame"] + start["frames"] - 1, a)
        for i in range(a, b + 1):
            self.assertLessEqual(result.looks[i].error, eye_gaze.CONTACT_ERROR + 0.5, i)

    def test_outside_the_contacts_the_gaze_keeps_off_the_camera(self):
        # a pass over the camera on the way would count as a one-frame eye contact (a13's measure)
        for seed in range(3):
            dance, cams = restless(seed)
            result = run_gaze(dance=dance, cam_motion=cams, life=True, seed=seed)
            inside = set()
            for a, b in result.contacts:
                inside.update(range(a - 3, b + 4))
            for i, look in enumerate(result.looks):
                if i not in inside:
                    self.assertGreater(look.error, eye_gaze.KEEP_OFF - 0.5, (seed, i, look))


class SaccadeTest(unittest.TestCase):
    def test_the_length_follows_the_main_sequence(self):
        # D = 21 + 2.2 A ms rounded to frames of 30 fps, at least one
        for amplitude, frames in ((0.6, 1), (5.0, 1), (13.0, 1), (14.0, 2), (28.0, 2), (29.0, 3), (40.0, 3), (45.0, 4)):
            self.assertEqual(eye_gaze.main_sequence_frames(amplitude), frames, amplitude)
        for seed in range(3):
            dance, cams = restless(seed)
            for s in run_gaze(dance=dance, cam_motion=cams, seed=seed).saccades:
                self.assertEqual(s["frames"], eye_gaze.main_sequence_frames(s["amplitude"]), s)

    def test_a_saccade_follows_the_minimum_jerk_profile(self):
        # the lead of a fast turn goes to a fixed angle in the head: its frames are exactly the profile
        # (a wide yaw limit makes the lead long enough to take 2 frames or more)
        dance = head_turn({0: 0.0, 60: 0.0, 66: 60.0})
        for seed in range(6):
            result = run_gaze(dance=dance, cam_motion=BEHIND, seed=seed, max_yaw=40.0)
            lead = [s for s in result.saccades if s["reason"] == "lead"][0]
            if lead["frames"] < 2:
                continue
            start, n = lead["frame"], lead["frames"]
            old, new = result.looks[start - 1].base[0], result.looks[start + n - 1].base[0]
            for k in range(1, n + 1):
                t = k / float(n)
                share = (result.looks[start + k - 1].base[0] - old) / (new - old)
                self.assertAlmostEqual(share, 10 * t ** 3 - 15 * t ** 4 + 6 * t ** 5, places=6)
            return
        self.fail("no lead of 2 frames or more in 6 seeds")

    def test_free_saccades_wait_for_the_shortest_fixation(self):
        for seed in range(3):
            dance, cams = restless(seed)
            result = run_gaze(dance=dance, cam_motion=cams, seed=seed)
            for before, after in zip(result.saccades, result.saccades[1:]):
                if after["reason"] in ("recentre", "glance"):
                    landed = before["frame"] + before["frames"] - 1
                    self.assertGreaterEqual(after["frame"] - landed, eye_gaze.MIN_FIXATION, (before, after))

    def test_every_saccade_lands_where_it_set_out_for(self):
        landings = 0
        for seed in range(4):
            dance, cams = restless(seed)
            result = run_gaze(dance=dance, cam_motion=cams, life=True, seed=seed)
            reasons = {s["reason"] for s in result.saccades}
            self.assertTrue({"recentre", "lead"} <= reasons, reasons)
            for s in result.saccades:
                last = s["frame"] + s["frames"] - 1
                if last + 1 < len(result.looks):
                    landings += 1
                    self.assertEqual(result.looks[last].mode == "camera", s["reason"] == "contact", (seed, s))
        self.assertGreater(landings, 100)


class SoftLimitTest(unittest.TestCase):
    """review 8, R2: the last part of the range is approached along tanh, so the eyes do not stop dead at a limit"""

    def test_the_same_up_to_the_soft_part_then_tanh_towards_the_limit(self):
        self.assertEqual(eye_gaze.SOFT_FROM, 0.6)
        for value in (0.0, 5.0, -5.0, 10.8, -10.8):
            self.assertEqual(eye_gaze.soft(value, 18.0), value)
        self.assertAlmostEqual(eye_gaze.soft(18.0, 18.0), 18.0 * (0.6 + 0.4 * math.tanh(1.0)), places=12)   # 90.5 %
        self.assertAlmostEqual(eye_gaze.soft(-18.0, 18.0), -eye_gaze.soft(18.0, 18.0), places=12)
        values = [eye_gaze.soft(v / 10.0, 18.0) for v in range(0, 541)]                  # up to 3 times the limit
        self.assertTrue(all(b > a for a, b in zip(values, values[1:])))                  # rises all the way
        self.assertLess(max(values), 18.0)                                               # short of the limit
        self.assertEqual(eye_gaze.soft(150.0, 18.0), 18.0)
        self.assertEqual(eye_gaze.soft(-1e6, 18.0), -18.0)
        h = 1e-6
        self.assertAlmostEqual((eye_gaze.soft(10.8 + h, 18.0) - eye_gaze.soft(10.8, 18.0)) / h, 1.0, places=4)   # C1

    def test_up_and_down_soften_against_their_own_limits(self):
        limits = eye_gaze.Limits(18.0, 6.0, 10.0)
        self.assertEqual(eye_gaze.soften((5.0, 3.0), limits), (5.0, 3.0))
        self.assertAlmostEqual(eye_gaze.soften((0.0, 6.0), limits)[1], eye_gaze.soft(6.0, 6.0), places=12)
        self.assertAlmostEqual(eye_gaze.soften((0.0, -6.0), limits)[1], -6.0, places=12)          # inside 0.6 x 10
        self.assertAlmostEqual(eye_gaze.soften((0.0, -10.0), limits)[1], -eye_gaze.soft(10.0, 10.0), places=12)


class LimitTest(unittest.TestCase):
    def test_up_and_down_have_their_own_limits(self):
        # review 8, R1: at +10 the upper lid of Sour's Rin covers 17 % more of the iris, so the eyes look up less
        # far than down (defaults: up 6, down 10)
        self.assertEqual((eye_gaze.MAX_YAW, eye_gaze.MAX_UP, eye_gaze.MAX_DOWN), (18.0, 6.0, 10.0))
        pitch = expected_yaw((-8.0, 0.0, 0.0))[1]
        self.assertTrue(-eye_gaze.contact_zone(LIMITS).down < pitch < -eye_gaze.MAX_UP)
        below = run_gaze(cam_motion=camera(cam(0, (-8.0, 0.0, 0.0)), cam(LAST, (-8.0, 0.0, 0.0))))
        self.assertEqual({look.state for look in below.looks}, {"contact"})
        self.assertTrue(all(look.pitch < -eye_gaze.MAX_UP for look in below.looks))
        above = run_gaze(cam_motion=camera(cam(0, (10.0, 0.0, 0.0)), cam(LAST, (10.0, 0.0, 0.0))))  # 9.6 up: out of reach
        self.assertEqual(above.contacts, [])
        # other limits: up 3 (a camera 2.9 up is still reached), down 12
        result = run_gaze(cam_motion=camera(cam(0, (3.0, 0.0, 0.0)), cam(LAST, (3.0, 0.0, 0.0))), max_up=3.0, max_down=12.0)
        self.assertEqual(len(result.contacts), 1)
        self.assertTrue(all(look.pitch <= 3.0 * 0.9 for look in result.looks))

    def test_other_limits_are_respected_with_life_on(self):
        dance, cams = restless(5, last=300)
        for max_yaw, max_up, max_down in ((18.0, 6.0, 10.0), (8.0, 4.0, 3.0), (30.0, 20.0, 25.0)):
            result = run_gaze(dance=dance, cam_motion=cams, life=True, max_yaw=max_yaw, max_up=max_up, max_down=max_down)
            self.assertLessEqual(max(abs(look.yaw) for look in result.looks), max_yaw + 1e-9)
            self.assertLessEqual(max(look.pitch for look in result.looks), max_up + 1e-9)
            self.assertGreaterEqual(min(look.pitch for look in result.looks), -max_down - 1e-9)
            for key in result.motion.bones:
                yaw, pitch = eye_gaze.angles_of(fk.rotate(fk.applied(key.rotation), FORWARD))
                self.assertLessEqual(abs(yaw), max_yaw + 1e-3)
                self.assertLessEqual(pitch, max_up + 1e-3)
                self.assertGreaterEqual(pitch, -max_down - 1e-3)

    def test_limits_outside_0_to_45_are_errors(self):
        for max_yaw, max_up, max_down in ((0.0, 6.0, 10.0), (18.0, -1.0, 10.0), (18.0, 6.0, 0.0), (50.0, 6.0, 10.0),
                                          (18.0, 46.0, 10.0), (18.0, 6.0, 46.0)):
            with self.assertRaises(ValueError):
                run_gaze(max_yaw=max_yaw, max_up=max_up, max_down=max_down)


class LifeTest(unittest.TestCase):
    def test_drift_and_microsaccades_stay_well_under_a_degree(self):
        result = run_gaze(life=True)
        yaws = [look.yaw for look in result.looks]
        pitches = [look.pitch for look in result.looks]
        self.assertLessEqual(max(abs(v) for v in yaws + pitches), eye_gaze.DRIFT_LIMIT + 1e-9)
        self.assertLess(eye_gaze.DRIFT_LIMIT, 0.5)
        self.assertGreater(len({round(v, 6) for v in yaws}), LAST // 2)            # it moves
        self.assertEqual({look.state for look in result.looks}, {"contact"})

    def test_the_same_seed_gives_the_same_motion_and_another_seed_another(self):
        dance, cams = restless(1, last=300)
        a = run_gaze(dance=dance, cam_motion=cams, life=True, seed=4)
        b = run_gaze(dance=dance, cam_motion=cams, life=True, seed=4)
        c = run_gaze(dance=dance, cam_motion=cams, life=True, seed=5)
        self.assertEqual(vmd.dumps(a.motion), vmd.dumps(b.motion))
        self.assertEqual(a.report, b.report)
        self.assertNotEqual(vmd.dumps(a.motion), vmd.dumps(c.motion))


class MeasureTest(unittest.TestCase):
    """the target numbers of the analysis (a07, a13, a20), measured on a plan or on a written motion"""

    def test_edge_and_eccentricity(self):
        # 10 frames at the yaw limit, 5 near the up limit, the rest in the middle
        angles = [(17.0, 0.0)] * 10 + [(0.0, 0.0)] * 20 + [(0.0, 5.5)] * 5 + [(2.0, 1.0)] * 65
        m = eye_gaze.eye_measures(angles, LIMITS)
        self.assertAlmostEqual(m["edge_share"], 15 / 100.0, places=4)
        self.assertAlmostEqual(m["edge_longest_s"], 10 / 30.0, places=3)
        self.assertAlmostEqual(m["eccentric_15_share"], 10 / 100.0, places=4)

    def test_contact_episodes_join_gaps_of_two_frames(self):
        errors = [1.0] * 60 + [9.0] * 2 + [1.0] * 30 + [9.0] * 3 + [1.0] * 5 + [9.0] * 100
        m = eye_gaze.contact_measures(errors)
        self.assertEqual(m["episodes"], 2)
        self.assertAlmostEqual(m["episode_median_s"], (92 / 30.0 + 5 / 30.0) / 2.0, places=3)
        self.assertAlmostEqual(m["share"], 95 / 200.0, places=4)

    def test_the_lead_measure_of_a20(self):
        # head yaw: still, then 300 deg/s for 6 frames; the eye in the head 8 degrees the way of the turn from 3
        # frames before it, or not at all
        head = [0.0] * 60 + [10.0 * k for k in range(1, 7)] + [60.0] * 60
        lead = [0.0] * 57 + [8.0] * (len(head) - 57)
        none = [0.0] * len(head)
        self.assertEqual(eye_gaze.lead_measure(head, [h + e for h, e in zip(head, lead)], margins=(15, 0)),
                         {"turns": 1, "led": 1, "share": 1.0})
        self.assertEqual(eye_gaze.lead_measure(head, [h + e for h, e in zip(head, none)], margins=(15, 0)),
                         {"turns": 1, "led": 0, "share": 0.0})

    def test_large_gaze_changes_made_by_saccades_or_carried_by_the_head(self):
        # the gaze turns 30 degrees in the world over 10 frames: once inside a listed saccade, once without one
        gaze = [direction(0.0, 0.0)] * 20 + [direction(3.0 * k, 0.0) for k in range(1, 11)] + [direction(30.0, 0.0)] * 30
        listed = [{"frame": 20, "frames": 10}]
        self.assertEqual(eye_gaze.carried_measure(gaze, listed)["head_carried"], 0)
        self.assertEqual(eye_gaze.carried_measure(gaze, [])["head_carried"], 1)


class OutputTest(unittest.TestCase):
    def test_only_the_eyes_track_with_linear_curves_and_the_dance_model_name(self):
        result = run_gaze(dance=head_turn({0: 0.0, 60: 12.0, 120: -6.0}), life=True)
        m = result.motion
        self.assertEqual(m.model_name, "dancer")
        self.assertEqual({k.name for k in m.bones}, {"両目"})
        self.assertEqual((m.morphs, m.cameras), ([], []))
        frames = [k.frame for k in m.bones]
        self.assertEqual(frames, sorted(set(frames)))
        self.assertEqual((frames[0], frames[-1]), (0, LAST))
        for k in m.bones:
            self.assertEqual(vmd.bone_curves(k.interpolation), {c: vmd.LINEAR_CURVE for c in vmd.BONE_CHANNELS})
            self.assertEqual(k.position, (0.0, 0.0, 0.0))

    def test_frames_that_do_not_change_get_no_key(self):
        result = run_gaze(life=False)
        self.assertEqual([k.frame for k in result.motion.bones], [0, LAST])

    def test_the_shares_add_up_to_one(self):
        dance, cams = restless(2, last=300)
        result = run_gaze(dance=dance, cam_motion=cams, life=True)
        counts = result.report["counts"]
        self.assertEqual(sum(counts.values()), 301)
        self.assertEqual(set(counts), set(eye_gaze.STATES))
        self.assertAlmostEqual(sum(result.report["shares"].values()), 1.0, places=9)

    def test_the_report_holds_the_contacts_the_saccades_and_the_measures(self):
        long_ = head_turn({0: 40.0, 18: 40.0, 20: 0.0, 90: 0.0, 92: 40.0})
        report = run_gaze(dance=long_, anchors=[60]).report
        self.assertEqual(report["contacts"]["count"], 1)
        first = report["contacts"]["list"][0]
        self.assertEqual(set(first), {"first", "last", "seconds", "anchor"})
        self.assertEqual(first["anchor"], 60)
        self.assertEqual(len(report["saccades"]["list"]), report["saccades"]["count"])
        self.assertEqual(set(report["saccades"]["list"][0]), {"frame", "frames", "reason", "amplitude"})
        self.assertEqual(set(report["measures"]), {"edge_share", "edge_longest_s", "eccentric_15_share", "contact",
                                                   "lead", "head_carried", "saccades_per_second"})


class AnchorTest(unittest.TestCase):
    def test_the_song_gives_line_ends_hooks_and_chorus_heads(self):
        cues = {"cues": [{"id": "lyric00", "start": 1.0, "end": 2.5, "style": "lyric"},
                         {"id": "hook1", "start": 3.0, "end": 3.9, "style": "hook"},
                         {"id": "title", "start": 0.0, "end": 9.0},
                         {"id": "lyric01", "start": 2.5, "end": 4.0, "style": "lyric"}]}
        self.assertEqual(eye_gaze.song_anchors(cues, chorus=[2.0]), [60, 75, 90, 120])
        self.assertEqual(eye_gaze.song_anchors(None), [])

    def test_a_shifted_line_moves_its_contact_by_little_or_not_at_all(self):
        # textlight will move 4 lines by 0.3 to 0.9 s: the plan must not depend on the exact frame of an anchor
        long_ = head_turn({0: 40.0, 8: 40.0, 10: 0.0, 190: 0.0, 192: 40.0}, last=200)
        cams = camera(cam(0), cam(200))
        a = run_gaze(dance=long_, cam_motion=cams, anchors=[90]).contacts
        b = run_gaze(dance=long_, cam_motion=cams, anchors=[90 + 27]).contacts
        self.assertEqual(len(a), len(b))
        self.assertLessEqual(abs(a[0][0] - b[0][0]), 27)


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = eye_gaze.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.dance = os.path.join(self.folder, "dance.vmd")
        self.camera = os.path.join(self.folder, "camera.vmd")
        self.model = os.path.join(self.folder, "model.pmx")
        self.cues = os.path.join(self.folder, "cues.json")
        cut = camera(cam(0, (0.0, -6.0, 0.0)), cam(59, (0.0, -6.0, 0.0)), cam(60, (0.0, 6.0, 0.0)), cam(LAST, (0.0, 6.0, 0.0)))
        for path, data in ((self.dance, vmd.dumps(head_turn({0: 0.0, 60: 30.0, 120: 0.0}))),
                           (self.camera, vmd.dumps(cut)), (self.model, rin_like_bytes()),
                           (self.cues, json.dumps({"cues": [{"start": 0.5, "end": 1.5, "style": "lyric"}]}).encode("ascii"))):
            with open(path, "wb") as f:
                f.write(data)

    def test_writes_the_eyes_the_report_and_the_debug(self):
        out = os.path.join(self.folder, "sub", "eyes.vmd")
        report, debug = os.path.join(self.folder, "r.json"), os.path.join(self.folder, "d.json")
        code, result = run([self.dance, self.camera, self.model, out, "--report", report, "--debug", debug, "--seed", "3",
                            "--cues", self.cues, "--chorus", "2.0"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["out"], os.path.abspath(out))
        back = vmd.load(out)
        self.assertEqual(result["keys"], len(back.bones))
        self.assertEqual({k.name for k in back.bones}, {"両目"})
        self.assertEqual(back.model_name, "dancer")
        self.assertEqual(result["frames"], [0, LAST])
        self.assertEqual(result["cuts"], 1)
        self.assertEqual(result["anchors"], 2)
        self.assertAlmostEqual(sum(result["shares"].values()), 1.0, places=3)
        self.assertEqual(result["seed"], 3)
        self.assertEqual(result["convention"], {"key_rotation_signs": list(fk.KEY_ROTATION_SIGNS)})
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertEqual(full["counts"], result["counts"])
        self.assertEqual(sum(full["counts"].values()), LAST + 1)
        self.assertEqual(full["cuts"], [60])
        self.assertEqual(full["anchors"], [45, 60])
        self.assertEqual(len(full["saccades"]["list"]), full["saccades"]["count"])
        self.assertEqual(full["measures"], result["measures"])
        self.assertEqual(full["eye"]["center"], ["右目", "左目"])
        self.assertEqual(full["eye"]["forward"], [0.0, 0.0, -1.0])
        with open(debug, encoding="ascii") as f:
            rows = json.load(f)["frames"]
        self.assertEqual([row["frame"] for row in rows], [0, 30, 60, 90, 120])
        row = rows[0]
        self.assertEqual(sorted(row), sorted(["frame", "camera", "eye_center", "head_forward", "to_camera", "eye", "window",
                                              "state", "error"]))
        self.assertAlmostEqual(row["eye_center"][1], 17.2, places=3)
        self.assertAlmostEqual(row["head_forward"][2], -1.0, places=3)
        self.assertEqual(os.listdir(os.path.dirname(out)), ["eyes.vmd"])

    def test_up_and_down_limits_and_the_pitch_shortcut(self):
        out = os.path.join(self.folder, "o.vmd")
        code, result = run([self.dance, self.camera, self.model, out])
        self.assertEqual(code, 0, result)
        self.assertEqual({k: result["limits"][k] for k in ("yaw", "up", "down")}, {"yaw": 18.0, "up": 6.0, "down": 10.0})
        self.assertEqual(result["limits"]["soft_from"], 0.6)
        code, result = run([self.dance, self.camera, self.model, out, "--max-up", "4", "--max-down", "12", "--max-yaw", "20"])
        self.assertEqual(code, 0, result)
        self.assertEqual({k: result["limits"][k] for k in ("yaw", "up", "down")}, {"yaw": 20.0, "up": 4.0, "down": 12.0})
        code, result = run([self.dance, self.camera, self.model, out, "--max-pitch", "8"])
        self.assertEqual(code, 0, result)
        self.assertEqual({k: result["limits"][k] for k in ("up", "down")}, {"up": 8.0, "down": 8.0})

    def test_debug_frames_can_be_chosen(self):
        debug = os.path.join(self.folder, "d.json")
        code, result = run([self.dance, self.camera, self.model, os.path.join(self.folder, "o.vmd"), "--debug", debug,
                            "--debug-frames", "61", "5", "999"])
        self.assertEqual(code, 0, result)
        with open(debug, encoding="ascii") as f:
            self.assertEqual([row["frame"] for row in json.load(f)["frames"]], [5, 61])

    def test_the_probe_and_what_it_should_show(self):
        probe = os.path.join(self.folder, "probe.vmd")
        code, result = run([self.dance, self.camera, self.model, os.path.join(self.folder, "o.vmd"), "--probe", probe])
        self.assertEqual(code, 0, result)
        back = vmd.load(probe)
        self.assertEqual({k.name for k in back.bones}, {"両目"})
        self.assertEqual(back.model_name, "dancer")
        ui = {k.frame: tuple(round(v, 3) for v in mathutil.quat_to_ui(k.rotation)) for k in back.bones}
        self.assertEqual(ui[0], (0.0, 0.0, 0.0))
        self.assertEqual(ui[29], (0.0, 0.0, 0.0))
        self.assertEqual((ui[30], ui[59]), ((0.0, 15.0, 0.0), (0.0, 15.0, 0.0)))
        self.assertEqual((ui[60], ui[89]), ((0.0, -15.0, 0.0), (0.0, -15.0, 0.0)))
        self.assertEqual((ui[90], ui[119]), ((10.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
        self.assertEqual((ui[120], ui[149]), ((-10.0, 0.0, 0.0), (-10.0, 0.0, 0.0)))
        self.assertEqual(ui[150], (0.0, 0.0, 0.0))
        segments = result["probe"]["segments"]
        self.assertEqual([s["frames"] for s in segments], [[0, 29], [30, 59], [60, 89], [90, 119], [120, 149], [150, 150]])
        if fk.KEY_ROTATION_SIGNS == (1.0, 1.0, 1.0):
            looks = [s["looks"] for s in segments]
            self.assertEqual(looks[0], "straight ahead")
            self.assertTrue(looks[1].startswith("to her left"), looks[1])
            self.assertIn("viewer's right", looks[1])
            self.assertTrue(looks[2].startswith("to her right"), looks[2])
            self.assertEqual((looks[3], looks[4]), ("up", "down"))

    def test_errors_exit_2_before_anything_is_written(self):
        out = os.path.join(self.folder, "o.vmd")
        with open(self.dance, "rb") as f:
            original = f.read()
        no_camera = os.path.join(self.folder, "no_camera.vmd")
        with open(no_camera, "wb") as f:
            f.write(original)
        bad_cues = os.path.join(self.folder, "bad.json")
        with open(bad_cues, "wb") as f:
            f.write(b"{not json")
        for argv in ([self.dance, self.camera, self.model, self.dance],
                     [self.dance, self.camera, self.model, out, "--report", self.camera],
                     [self.dance, self.camera, self.model, out, "--probe", self.model],
                     [self.dance, self.camera, self.model, out, "--report", os.path.join(self.folder, "r.json"),
                      "--debug", os.path.join(self.folder, "r.json")],
                     [self.dance, self.camera, self.model, out, "--max-yaw", "0"],
                     [self.dance, self.camera, self.model, out, "--max-pitch", "60"],
                     [self.dance, self.camera, self.model, out, "--max-down", "0"],
                     [self.dance, self.camera, self.model, out, "--max-pitch", "8", "--max-up", "4"],   # one or the other
                     [self.dance, self.camera, self.model, out, "--cues", os.path.join(self.folder, "none.json")],
                     [self.dance, self.camera, self.model, out, "--cues", bad_cues],
                     [self.dance, self.camera, self.model, out, "--cues", out],                       # cues is the output
                     [self.dance, self.dance, self.model, out],                       # the camera is the dance
                     [self.dance, no_camera, self.model, out],                        # no camera keys
                     [self.dance, self.camera, self.dance, out],                      # not a model
                     [os.path.join(self.folder, "none.vmd"), self.camera, self.model, out]):
            code, result = run(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
            self.assertFalse(os.path.exists(out), argv)
            self.assertFalse(os.path.exists(os.path.join(self.folder, "r.json")), argv)
        with open(self.dance, "rb") as f:
            self.assertEqual(f.read(), original)

    def test_a_model_without_the_eye_bones_is_an_error(self):
        w = Writer()
        with open(self.model, "wb") as f:
            f.write(w.build(bones=[w.bone("頭")]))
        code, result = run([self.dance, self.camera, self.model, os.path.join(self.folder, "o.vmd")])
        self.assertEqual(code, 2)
        self.assertIn("両目", result["error"]["message"])


def real_file(*parts):
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    return None


MV_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_final_dn6_twist.vmd")
HANDHELD = real_file("_spike", "out", "hibikase", "variants", "camera_D_handheld.vmd")
MV_CUES = real_file("_spike", "out", "hibikase", "mv", "production", "cues_mv.json")
OLD_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_smooth_twist.vmd")
OLD_CAMERA = real_file("_spike", "out", "hibikase", "variants", "camera_D_generated.vmd")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"
CHORUS = ["60.02", "128.59", "198.87"]       # the heads of the three choruses (a15: beats 140, 300, 464 at 140 BPM)


def measured_from_files(dance_path, camera_path, out_path, report):
    """the target numbers measured again from the files: the dance with the written 両目 track in place of its own
    through the forward kinematics, not from the plan"""
    model = pmx.load(RIN)
    dance, gaze_motion = vmd.load(dance_path), vmd.load(out_path)
    motion = vmd.Motion(model_name=dance.model_name, bones=[k for k in dance.bones if k.name != "両目"] + list(gaze_motion.bones))
    track = fk.world_track(model, motion, ["頭", "左目", "右目"], 0, 7742)
    keys = fk.camera_keys(vmd.load(camera_path))
    frames = [k.frame for k in keys]
    heads, gazes, angles, errors = [], [], [], []
    for f in range(7743):
        head, left, right = track["頭"][f][1], track["左目"][f], track["右目"][f]
        gaze = fk.rotate(left[1], FORWARD)
        center = tuple((a + b) / 2.0 for a, b in zip(left[0], right[0]))
        to_camera = tuple(c - e for c, e in zip(fk.camera_position(fk.camera_at(keys, f, frames)), center))
        heads.append(head)
        gazes.append(gaze)
        angles.append(eye_gaze.angles_of(fk.rotate(fk.conjugate(head), gaze)))
        errors.append(eye_gaze.degrees_between(gaze, to_camera))
    yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
    out = eye_gaze.eye_measures(angles, LIMITS)
    out["contact"] = eye_gaze.contact_measures(errors)
    out["lead"] = eye_gaze.lead_measure([yaw(fk.rotate(h, FORWARD)) for h in heads], [yaw(g) for g in gazes])
    out["head_carried"] = eye_gaze.carried_measure(gazes, report["saccades"]["list"])
    return out


@unittest.skipUnless(MV_DANCE and HANDHELD and MV_CUES and os.path.isfile(RIN), "the MV's dance, camera, cues or Rin is not here")
class RealSongTest(unittest.TestCase):
    """the MV's dance (dance_final_dn6_twist) and camera (camera_D_handheld): the target numbers of the stage-1 fix,
    measured from the written file.  Before it (the old tool, v2): eyes led 4 % of the fast turns, at the edge 59 %
    of the frames and up to 4 s on end, 15 degrees or more off the middle 42 %, eye contacts of 0.30 s (median), 93 %
    of the large gaze changes carried by the head, 0.33 saccades a second"""

    def test_the_whole_song_meets_the_targets(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out, report_path = os.path.join(folder, "eyes.vmd"), os.path.join(folder, "r.json")
        started = time.time()
        code, result = run([MV_DANCE, HANDHELD, RIN, out, "--report", report_path, "--cues", MV_CUES, "--chorus"] + CHORUS)
        self.assertEqual(code, 0, result)
        self.assertLess(time.time() - started, 60.0)
        self.assertEqual((result["frames"], result["cuts"]), ([0, 7742], 20))
        with open(report_path, encoding="ascii") as f:
            report = json.load(f)
        self.assertEqual(sum(report["counts"].values()), 7743)
        back = vmd.load(out)
        self.assertEqual({k.name for k in back.bones}, {"両目"})
        self.assertEqual(back.model_name, vmd.load(MV_DANCE).model_name)
        for key in back.bones:
            yaw, pitch = eye_gaze.angles_of(fk.rotate(fk.applied(key.rotation), FORWARD))
            self.assertLessEqual(abs(yaw), eye_gaze.MAX_YAW + 1e-3)
            self.assertTrue(-eye_gaze.MAX_DOWN - 1e-3 <= pitch <= eye_gaze.MAX_UP + 1e-3, (key.frame, pitch))
        m = measured_from_files(MV_DANCE, HANDHELD, out, report)
        self.assertGreaterEqual(m["lead"]["share"], 0.5, m["lead"])
        self.assertLessEqual(m["edge_share"], 0.15)
        self.assertLess(m["edge_longest_s"], 1.0)
        self.assertLess(m["eccentric_15_share"], 0.10)
        self.assertGreaterEqual(m["contact"]["episode_median_s"], 1.5, m["contact"])
        self.assertLessEqual(m["head_carried"]["share"], 0.20, m["head_carried"])
        rate = len(report["saccades"]["list"]) / (7743 / 30.0)
        self.assertTrue(1.0 <= rate <= 4.0, rate)
        # the plan's own measures say the same as the files
        self.assertAlmostEqual(report["measures"]["edge_share"], m["edge_share"], places=2)
        self.assertAlmostEqual(report["measures"]["contact"]["episode_median_s"], m["contact"]["episode_median_s"], places=1)
        self.assertEqual(report["measures"]["lead"]["turns"], m["lead"]["turns"])


@unittest.skipUnless(OLD_DANCE and OLD_CAMERA and os.path.isfile(RIN), "the older dance, its camera or Rin is not here")
class OlderSongTest(unittest.TestCase):
    """an earlier dance of the same song with the camera before the handheld shake: no cues, so no anchors (only the
    long contacts); the limits hold and the eyes still lead and stay off the edge"""

    def test_the_older_dance_without_cues(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out, report_path = os.path.join(folder, "eyes.vmd"), os.path.join(folder, "r.json")
        code, result = run([OLD_DANCE, OLD_CAMERA, RIN, out, "--report", report_path])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["frames"], result["cuts"], result["anchors"]), ([0, 7742], 20, 0))
        with open(report_path, encoding="ascii") as f:
            report = json.load(f)
        m = measured_from_files(OLD_DANCE, OLD_CAMERA, out, report)
        self.assertGreaterEqual(m["lead"]["share"], 0.5, m["lead"])
        self.assertLessEqual(m["edge_share"], 0.15)
        self.assertLess(m["edge_longest_s"], 1.0)
        self.assertLessEqual(m["head_carried"]["share"], 0.20)
        for s in [c for c in report["contacts"]["list"]]:
            self.assertGreaterEqual(s["last"] - s["first"] + 1, eye_gaze.CONTACT_MIN)


if __name__ == "__main__":
    unittest.main()
