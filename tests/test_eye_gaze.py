"""tools/eye_gaze.py: a natural gaze toward the camera (fixations, saccades) as a 両目 track to load after the dance."""
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
from unittest import mock

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


def head_turn(degrees_by_frame, axis="y"):
    """a still dance (keys at 0 and LAST) whose head turns by the window angles given as {frame: degrees}"""
    keys = [vmd.BoneKey("全ての親", 0, (0.0, 0.0, 0.0), fk.IDENTITY), vmd.BoneKey("全ての親", LAST, (0.0, 0.0, 0.0), fk.IDENTITY),
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


def cut_at_60(before, after):
    """a camera at window Y `before` until frame 59 that cuts to Y `after` on frame 60"""
    return camera(cam(0, (0.0, before, 0.0)), cam(59, (0.0, before, 0.0)), cam(60, (0.0, after, 0.0)),
                  cam(LAST, (0.0, after, 0.0)))


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


class WhereSheLooksTest(unittest.TestCase):
    def test_a_camera_straight_ahead_gives_zero_angles(self):
        result = run_gaze()
        self.assertEqual(len(result.looks), LAST + 1)
        for look in result.looks:
            # 17.2 as float32 in the model is 7.6e-7 above the camera's 17.2: a pitch of 1.5e-6 degrees
            self.assertAlmostEqual(look.yaw, 0.0, places=4)
            self.assertAlmostEqual(look.pitch, 0.0, places=4)
            self.assertEqual(look.state, "on_camera")
        key = [k for k in result.motion.bones if k.frame == 0][0]
        self.assertEqual(key.name, "両目")
        self.assertAlmostEqual(abs(key.rotation[3]), 1.0, places=9)

    def test_a_camera_on_the_plus_x_side_turns_the_eyes_to_her_left(self):
        yaw, pitch = expected_yaw((0.0, 10.0, 0.0))
        self.assertGreater(yaw, 9.0)
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 10.0, 0.0)), cam(LAST, (0.0, 10.0, 0.0))))
        look = result.looks[30]
        self.assertAlmostEqual(look.yaw, yaw, places=4)                 # + : toward +X, the model's left
        self.assertAlmostEqual(look.pitch, pitch, places=4)
        # the written key, applied by the convention of mmd_cli/fk.py, turns the gaze onto the camera
        key = [k for k in result.motion.bones if k.frame == 0][0]        # still: keys on the first and last frame
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
                self.assertEqual(look.state, "on_camera")

    def test_a_camera_behind_her_leaves_the_eyes_neutral(self):
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 180.0, 0.0)), cam(LAST, (0.0, 180.0, 0.0))))
        self.assertEqual({look.state for look in result.looks}, {"neutral"})
        self.assertEqual({(look.yaw, look.pitch) for look in result.looks}, {(0.0, 0.0)})


class FixationTest(unittest.TestCase):
    def test_the_eyes_keep_pointing_at_the_camera_while_the_head_turns(self):
        dance = head_turn({0: 0.0, 60: 12.0, 120: -6.0})
        result = run_gaze(dance=dance)
        sights = eye_gaze.sights(MODEL, dance, IN_FRONT)
        heads = fk.world_track(MODEL, dance, ["頭"])["頭"]
        for look, sight, (_, head) in zip(result.looks, sights, heads):
            gaze = fk.rotate(head, fk.rotate(eye_gaze.eye_rotation(look.yaw, look.pitch), FORWARD))
            to_camera = tuple(c - e for c, e in zip(sight.camera, sight.eye))
            self.assertLess(degrees_between(gaze, to_camera), 0.3, look.frame)
        # the head turned by 12 degrees at frame 60 (to her left under the default convention), the eyes against it
        head_x = fk.rotate(heads[60][1], FORWARD)[0]
        self.assertGreater(abs(head_x), math.sin(math.radians(11.0)))
        self.assertLess(result.looks[60].yaw * head_x, 0.0)
        self.assertGreater(abs(result.looks[60].yaw), 10.0)
        self.assertEqual(result.saccades, [])

    def test_a_head_turned_away_returns_the_eyes_to_neutral(self):
        result = run_gaze(dance=head_turn({0: 90.0}))
        self.assertEqual({look.state for look in result.looks}, {"neutral"})
        self.assertEqual({(look.yaw, look.pitch) for look in result.looks}, {(0.0, 0.0)})

    def test_a_head_turning_away_holds_the_limit_then_lets_go(self):
        result = run_gaze(dance=head_turn({0: 0.0, 40: 60.0}))
        yaws = [look.yaw for look in result.looks]
        self.assertLessEqual(max(abs(y) for y in yaws), eye_gaze.MAX_YAW + 1e-9)
        self.assertIn("at_limit", {look.state for look in result.looks})
        self.assertEqual([s["reason"] for s in result.saccades], ["to_neutral"])
        self.assertEqual(result.looks[-1].state, "neutral")
        self.assertEqual((result.looks[-1].yaw, result.looks[-1].pitch), (0.0, 0.0))
        # it lets go only once the camera has stayed GIVE_UP beyond the limit for PATIENCE frames, and then after
        # the reaction time
        start = result.saccades[0]["frame"]
        trigger = min(look.frame for look in result.looks if abs(look.target[0]) > eye_gaze.MAX_YAW + eye_gaze.GIVE_UP)
        self.assertGreaterEqual(start - trigger, eye_gaze.PATIENCE - 1 + eye_gaze.REACTION[0])
        self.assertLessEqual(start - trigger, eye_gaze.PATIENCE - 1 + eye_gaze.REACTION[1])

    def test_a_saccade_whose_cause_is_gone_when_it_is_due_does_not_happen(self):
        # out of reach for exactly PATIENCE frames (32..41), so the eyes decide to let go on 41; the camera is back
        # in reach on 42, before the reaction time is over: nothing moves
        p = eye_gaze.PATIENCE
        result = run_gaze(dance=head_turn({0: 0.0, 30: 0.0, 32: 50.0, 31 + p: 50.0, 33 + p: 0.0}))
        far = [look.frame for look in result.looks if abs(look.target[0]) > eye_gaze.MAX_YAW + eye_gaze.GIVE_UP]
        self.assertEqual(far, list(range(32, 32 + p)))
        self.assertEqual(result.saccades, [])
        self.assertNotIn("neutral", {look.state for look in result.looks})

    def test_every_saccade_lands_where_it_set_out_for(self):
        # a restless head (a new random angle every 7 frames, often out of reach) and a camera that cuts: whatever the
        # eyes want on the frame a saccade lands, it lands where it was going (neutral only for to_neutral)
        import random
        rng = random.Random(7)
        keys = [vmd.BoneKey("全ての親", 0, (0.0, 0.0, 0.0), fk.IDENTITY), vmd.BoneKey("全ての親", 600, (0.0, 0.0, 0.0), fk.IDENTITY)]
        for frame in range(0, 601, 7):
            keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(rng.uniform(-25, 25), rng.uniform(-60, 60), 0.0)))
        cams = []
        for start in range(0, 600, 90):
            rot = (rng.uniform(-10, 10), rng.uniform(-20, 20), 0.0)
            cams += [cam(start, rot), cam(start + 89, rot)]
        landings = 0
        for seed in range(5):
            result = run_gaze(dance=vmd.Motion(model_name="dancer", bones=keys), cam_motion=camera(*cams), life=True, seed=seed)
            reasons = {s["reason"] for s in result.saccades}
            self.assertTrue({"to_neutral", "to_camera", "cut"} <= reasons, reasons)
            for s in result.saccades:
                after = s["frame"] + s["frames"]
                if after < len(result.looks):
                    landings += 1
                    self.assertEqual(result.looks[after].state == "neutral", s["reason"] == "to_neutral", (seed, s))
        self.assertGreater(landings, 30)                # 45 with a patience of 20 (more than 50 with 10)

    def test_eyes_pinned_at_a_limit_do_not_jump_sides_when_she_spins(self):
        # a fast spin to 200 degrees and back (100 degrees a key, 50 a frame): the camera passes behind her, its
        # yaw wraps from -180 to +180, and the eyes must stay at the limit they were at (a jump is a saccade)
        result = run_gaze(dance=head_turn({0: 0.0, 30: 0.0, 32: 100.0, 34: 200.0, 36: 100.0, 38: 0.0}))
        far = [look for look in result.looks if abs(look.target[0]) > eye_gaze.MAX_YAW + eye_gaze.GIVE_UP]
        self.assertEqual([look.frame for look in far], list(range(31, 38)))
        self.assertGreater(max(look.target[0] for look in far), 150.0)            # both sides of 180 are seen
        self.assertLess(min(look.target[0] for look in far), -150.0)
        self.assertEqual(len({look.yaw > 0 for look in far}), 1)                   # one side all through
        for look in far:
            self.assertTrue(0.99 * eye_gaze.MAX_YAW < abs(look.yaw) <= eye_gaze.MAX_YAW, look)  # at or near the limit
        self.assertLess(max(abs(a.yaw - b.yaw) for a, b in zip(far, far[1:])), 0.5)
        self.assertEqual(result.saccades, [])
        self.assertAlmostEqual(result.looks[38].yaw, 0.0, places=4)

    def test_a_look_away_of_half_a_second_only_holds_the_limit(self):
        # review 8, R3: 15 frames out of reach (a nod or a turn with the beat) is no reason to give up; with a patience
        # of 10 the eyes went neutral and came back, 42 round trips on the song
        self.assertEqual(eye_gaze.PATIENCE, 20)
        result = run_gaze(dance=head_turn({0: 0.0, 30: 0.0, 31: 60.0, 45: 60.0, 46: 0.0}))
        far = [look.frame for look in result.looks if abs(look.target[0]) > eye_gaze.MAX_YAW + eye_gaze.GIVE_UP]
        self.assertEqual(far, list(range(31, 46)))
        self.assertNotIn("neutral", {look.state for look in result.looks})
        self.assertEqual(result.saccades, [])

    def test_a_short_excursion_out_of_reach_only_holds_the_limit(self):
        # a quick look away: 50 degrees (out of reach) for fewer frames than PATIENCE, then back
        swing = {0: 0.0, 30: 0.0, 32: 50.0, 30 + eye_gaze.PATIENCE - 2: 50.0, 30 + eye_gaze.PATIENCE: 0.0}
        result = run_gaze(dance=head_turn(swing))
        self.assertGreater(max(abs(look.target[0]) for look in result.looks), eye_gaze.MAX_YAW + eye_gaze.GIVE_UP)
        self.assertNotIn("neutral", {look.state for look in result.looks})
        self.assertEqual(result.saccades, [])
        self.assertTrue(0.99 * eye_gaze.MAX_YAW < max(abs(look.yaw) for look in result.looks) <= eye_gaze.MAX_YAW)


class SaccadeTest(unittest.TestCase):
    def check_one_saccade(self, before, after, frames):
        result = run_gaze(cam_motion=cut_at_60(before, after))
        old, new = (eye_gaze.soft(expected_yaw((0.0, y, 0.0))[0], eye_gaze.MAX_YAW) for y in (before, after))
        self.assertEqual(result.cuts, [60])
        self.assertEqual(len(result.saccades), 1)
        saccade = result.saccades[0]
        self.assertEqual((saccade["reason"], saccade["frames"]), ("cut", frames))
        start = saccade["frame"]
        self.assertGreaterEqual(start - 60, eye_gaze.REACTION[0])
        self.assertLessEqual(start - 60, eye_gaze.REACTION[1])
        yaws = [look.yaw for look in result.looks]
        for f in range(0, start):                                   # held on the old place until the saccade
            self.assertAlmostEqual(yaws[f], old, places=3, msg=f)
        for f in range(start + frames - 1, LAST + 1):               # on the new camera from the landing on
            self.assertAlmostEqual(yaws[f], new, places=3, msg=f)
        between = [f for f in range(LAST + 1) if min(abs(yaws[f] - old), abs(yaws[f] - new)) > 0.01]
        self.assertEqual(between, list(range(start, start + frames - 1)))
        self.assertEqual([look.state for look in result.looks[start:start + frames]], ["in_saccade"] * frames)
        self.assertEqual({look.state for look in result.looks[60:start]}, {"reacting"})
        return result

    def test_a_camera_cut_gives_one_quick_saccade(self):
        self.check_one_saccade(-8.0, 8.0, 2)

    def test_a_long_saccade_takes_three_frames(self):
        self.check_one_saccade(-14.0, 14.0, 3)

    def test_a_saccade_follows_the_minimum_jerk_profile(self):
        result = run_gaze(cam_motion=cut_at_60(-14.0, 14.0))
        old, new = (eye_gaze.soft(expected_yaw((0.0, y, 0.0))[0], eye_gaze.MAX_YAW) for y in (-14.0, 14.0))
        self.assertLess(abs(new), expected_yaw((0.0, 14.0, 0.0))[0])               # 14.3 is in the soft part
        start = result.saccades[0]["frame"]
        shares = [(result.looks[start + k].yaw - old) / (new - old) for k in range(3)]
        for share, t in zip(shares, (1 / 3.0, 2 / 3.0, 1.0)):
            self.assertAlmostEqual(share, 10 * t ** 3 - 15 * t ** 4 + 6 * t ** 5, places=6)

    def test_a_new_saccade_waits_for_the_shortest_fixation(self):
        # two cuts 8 frames apart: the first saccade has landed by frame 66, the second cut comes on 68
        keys = camera(cam(0, (0.0, -8.0, 0.0)), cam(59, (0.0, -8.0, 0.0)), cam(60, (0.0, 8.0, 0.0)), cam(67, (0.0, 8.0, 0.0)),
                      cam(68, (0.0, -6.0, 0.0)), cam(LAST, (0.0, -6.0, 0.0)))
        result = run_gaze(cam_motion=keys)
        self.assertEqual(result.cuts, [60, 68])
        first, second = result.saccades
        landed = first["frame"] + first["frames"] - 1
        self.assertLessEqual(landed, 66)
        self.assertGreaterEqual(second["frame"] - landed, eye_gaze.MIN_FIXATION)
        with mock.patch.object(eye_gaze, "MIN_FIXATION", 20):
            result = run_gaze(cam_motion=keys)
        first, second = result.saccades
        self.assertEqual(second["frame"] - (first["frame"] + first["frames"] - 1), 20)
        self.assertEqual(second["reason"], "cut")
        self.assertAlmostEqual(result.looks[-1].yaw, expected_yaw((0.0, -6.0, 0.0))[0], places=3)

    def test_a_cut_that_does_not_move_the_eyes_only_moves_the_fixation(self):
        # review 8, F1: both cameras lie beyond the yaw limit on the same side, so the eyes stay near the limit
        # across the cut.  That is no saccade (the move is under MIN_SACCADE); the held point still moves to the new
        # camera, which the eyes then find exactly when her head turns towards it
        self.assertEqual(eye_gaze.MIN_SACCADE, 0.5)
        before, after = expected_yaw((0.0, 25.0, 0.0))[0], expected_yaw((0.0, 28.0, 0.0))[0]
        self.assertLess(abs(eye_gaze.soft(after, 18.0) - eye_gaze.soft(before, 18.0)), eye_gaze.MIN_SACCADE)
        if fk.KEY_ROTATION_SIGNS != (1.0, 1.0, 1.0):
            self.skipTest("the head turn below is to her left under the default convention")
        dance = head_turn({0: 0.0, 80: 0.0, 100: 25.0})             # turns to her left, towards the camera
        result = run_gaze(dance=dance, cam_motion=cut_at_60(25.0, 28.0))
        self.assertEqual(result.cuts, [60])
        self.assertEqual(result.saccades, [])
        self.assertEqual(result.report["reanchored"], {"count": 1, "by_reason": {"cut": 1}})
        self.assertEqual(result.looks[-1].state, "on_camera")
        self.assertLess(result.looks[-1].error, 0.2)               # on the new camera, not the old one (3 degrees off)

    def test_a_cut_keeps_its_name_when_the_eyes_nearly_give_up_while_it_waits(self):
        # review 8, F2 (cut 1334 of the song): the head is turned away when the camera cuts; the patience runs out
        # one frame later (the eyes decide to let go), and one frame after that the head is back.  The saccade that
        # follows is the cut's, and is named so
        p = eye_gaze.PATIENCE
        dance = head_turn({0: 0.0, 60 - p + 1: 0.0, 60 - p + 2: 60.0, 61: 60.0, 62: 0.0})
        result = run_gaze(dance=dance, cam_motion=cut_at_60(-5.0, 5.0))
        far = [look.frame for look in result.looks if abs(look.target[0]) > eye_gaze.MAX_YAW + eye_gaze.GIVE_UP]
        self.assertEqual(far, list(range(60 - p + 2, 62)))                    # p frames, the last one is 61
        self.assertEqual(result.cuts, [60])
        self.assertEqual([s["reason"] for s in result.saccades], ["cut"])
        self.assertTrue(60 + eye_gaze.REACTION[0] <= result.saccades[0]["frame"] <= 60 + eye_gaze.REACTION[1])

    def test_a_camera_that_only_turns_is_a_cut_too(self):
        # review 8, F4: a camera at distance 0 turns 40 degrees on one frame without moving; that is a cut (by
        # CUT_TURN, the line of sight), though the eyes need not move (it stays where it was: no saccade)
        spot = (0.0, 17.2, -30.0)
        keys = camera(cam(0, (0.0, 0.0, 0.0), 0.0, spot), cam(59, (0.0, 0.0, 0.0), 0.0, spot),
                      cam(60, (0.0, 40.0, 0.0), 0.0, spot), cam(LAST, (0.0, 40.0, 0.0), 0.0, spot))
        result = run_gaze(cam_motion=keys)
        self.assertEqual(result.cuts, [60])
        self.assertEqual(result.saccades, [])
        self.assertEqual(result.report["reanchored"], {"count": 1, "by_reason": {"cut": 1}})

    def test_a_slowly_moving_camera_is_followed_by_refixations(self):
        keys = [cam(0, (0.0, -12.0, 0.0)), cam(LAST, (0.0, 12.0, 0.0))]
        result = run_gaze(cam_motion=camera(*keys))
        self.assertEqual(result.cuts, [])
        reasons = [s["reason"] for s in result.saccades]
        self.assertGreaterEqual(len(reasons), 3)
        self.assertEqual(set(reasons), {"refixation"})
        for s in result.saccades:
            self.assertGreater(s["amplitude"], eye_gaze.SACCADE_THRESHOLD)
            self.assertLess(s["amplitude"], eye_gaze.SACCADE_THRESHOLD + 2.0)
        # between saccades the eyes stay within a few degrees of the camera
        self.assertLess(max(look.error for look in result.looks), eye_gaze.SACCADE_THRESHOLD + 2.0)


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
        self.assertGreater(eye_gaze.soft(60.0, 18.0), 17.99)
        # far beyond, tanh is 1.0 in floating point: the eyes are then at the limit, never past it
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

    def test_a_camera_in_the_soft_part_is_looked_at_a_little_short_and_the_report_says_by_how_much(self):
        yaw = expected_yaw((0.0, 15.0, 0.0))[0]
        self.assertTrue(0.6 * eye_gaze.MAX_YAW < yaw < eye_gaze.MAX_YAW)
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 15.0, 0.0)), cam(LAST, (0.0, 15.0, 0.0))))
        short = yaw - eye_gaze.soft(yaw, eye_gaze.MAX_YAW)
        self.assertGreater(short, 0.3)
        for look in result.looks:
            self.assertAlmostEqual(look.yaw, eye_gaze.soft(yaw, eye_gaze.MAX_YAW), places=6)
            self.assertEqual(look.state, "on_camera")
        soft_part = result.report["soft_limit"]
        self.assertEqual(soft_part["from"], eye_gaze.SOFT_FROM)
        self.assertEqual(soft_part["frames"], LAST + 1)
        self.assertAlmostEqual(soft_part["error"]["max"], short, places=2)
        self.assertAlmostEqual(soft_part["pull"]["max"], short, places=2)                  # here all of it
        self.assertAlmostEqual(result.report["error_on_camera"]["max"], short, places=2)    # it is in the error too
        # with life on, the drift adds to the error but not to what the soft limit itself takes away
        lively = run_gaze(cam_motion=camera(cam(0, (0.0, 15.0, 0.0)), cam(LAST, (0.0, 15.0, 0.0))), life=True)
        self.assertAlmostEqual(lively.report["soft_limit"]["pull"]["mean"], short, places=2)
        self.assertNotAlmostEqual(lively.report["soft_limit"]["error"]["max"], short, places=2)


class LimitTest(unittest.TestCase):
    def test_yaw_beyond_the_limit_is_held_near_the_limit(self):
        yaw = expected_yaw((0.0, 25.0, 0.0))[0]
        self.assertTrue(eye_gaze.MAX_YAW < yaw < eye_gaze.MAX_YAW + eye_gaze.GIVE_UP)
        result = run_gaze(cam_motion=camera(cam(0, (0.0, 25.0, 0.0)), cam(LAST, (0.0, 25.0, 0.0))))
        self.assertEqual({look.state for look in result.looks}, {"at_limit"})
        self.assertEqual({round(look.yaw, 9) for look in result.looks}, {round(eye_gaze.soft(yaw, eye_gaze.MAX_YAW), 9)})
        self.assertTrue(0.98 * eye_gaze.MAX_YAW < result.looks[0].yaw < eye_gaze.MAX_YAW)

    def test_pitch_beyond_the_limit_is_held_near_the_limit(self):
        pitch = expected_yaw((10.0, 0.0, 0.0))[1]
        self.assertTrue(eye_gaze.MAX_UP < pitch < eye_gaze.MAX_UP + eye_gaze.GIVE_UP)
        result = run_gaze(cam_motion=camera(cam(0, (10.0, 0.0, 0.0)), cam(LAST, (10.0, 0.0, 0.0))))
        self.assertEqual({look.state for look in result.looks}, {"at_limit"})
        self.assertEqual(len({look.pitch for look in result.looks}), 1)
        # the model's float32 positions move the pitch by about 1e-6 degrees: compared to 6 places
        self.assertAlmostEqual(result.looks[0].pitch, eye_gaze.soft(pitch, eye_gaze.MAX_UP), places=6)
        self.assertTrue(0.98 * eye_gaze.MAX_UP < result.looks[0].pitch < eye_gaze.MAX_UP)

    def test_up_and_down_have_their_own_limits(self):
        # review 8, R1: at +10 the upper lid of Sour's Rin covers 17 % more of the iris, so the eyes look up less
        # far than down (defaults: up 6, down 10)
        self.assertEqual((eye_gaze.MAX_UP, eye_gaze.MAX_DOWN), (6.0, 10.0))
        above = run_gaze(cam_motion=camera(cam(0, (10.0, 0.0, 0.0)), cam(LAST, (10.0, 0.0, 0.0))))
        self.assertTrue(all(0.9 * eye_gaze.MAX_UP <= look.pitch <= eye_gaze.MAX_UP for look in above.looks))
        pitch = expected_yaw((-8.0, 0.0, 0.0))[1]
        self.assertTrue(-eye_gaze.MAX_DOWN < pitch < -eye_gaze.MAX_UP)
        below = run_gaze(cam_motion=camera(cam(0, (-8.0, 0.0, 0.0)), cam(LAST, (-8.0, 0.0, 0.0))))
        self.assertEqual({look.state for look in below.looks}, {"on_camera"})
        self.assertTrue(all(look.pitch < -eye_gaze.MAX_UP for look in below.looks))
        # other limits: up 3, down 12
        result = run_gaze(cam_motion=camera(cam(0, (10.0, 0.0, 0.0)), cam(LAST, (10.0, 0.0, 0.0))), max_up=3.0, max_down=12.0)
        self.assertTrue(all(look.pitch <= 3.0 for look in result.looks))

    def test_other_limits_are_respected_with_life_on(self):
        moving = camera(cam(0, (-15.0, -40.0, 0.0)), cam(40, (12.0, 30.0, 0.0)), cam(80, (-5.0, 10.0, 0.0)),
                        cam(LAST, (15.0, -20.0, 0.0)))
        dance = head_turn({0: 0.0, 30: 25.0, 70: -30.0, 110: 10.0})
        for max_yaw, max_up, max_down in ((18.0, 6.0, 10.0), (8.0, 4.0, 3.0), (30.0, 20.0, 25.0)):
            result = run_gaze(dance=dance, cam_motion=moving, life=True, max_yaw=max_yaw, max_up=max_up, max_down=max_down)
            self.assertLessEqual(max(abs(look.yaw) for look in result.looks), max_yaw + 1e-9)
            self.assertLessEqual(max(look.pitch for look in result.looks), max_up + 1e-9)
            self.assertGreaterEqual(min(look.pitch for look in result.looks), -max_down - 1e-9)
            for key in result.motion.bones:
                gaze = fk.rotate(fk.applied(key.rotation), FORWARD)
                yaw = math.degrees(math.atan2(gaze[0], -gaze[2]))
                pitch = math.degrees(math.atan2(gaze[1], math.hypot(gaze[0], gaze[2])))
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
        self.assertEqual({look.state for look in result.looks}, {"on_camera"})

    def test_the_same_seed_gives_the_same_motion_and_another_seed_another(self):
        dance = head_turn({0: 0.0, 60: 30.0, 120: 0.0})
        moving = camera(cam(0, (0.0, -5.0, 0.0)), cam(59, (0.0, -5.0, 0.0)), cam(60, (0.0, 8.0, 0.0)), cam(LAST))
        a = run_gaze(dance=dance, cam_motion=moving, life=True, seed=4)
        b = run_gaze(dance=dance, cam_motion=moving, life=True, seed=4)
        c = run_gaze(dance=dance, cam_motion=moving, life=True, seed=5)
        self.assertEqual(vmd.dumps(a.motion), vmd.dumps(b.motion))
        self.assertNotEqual(vmd.dumps(a.motion), vmd.dumps(c.motion))
        self.assertEqual([s["reason"] for s in a.saccades], [s["reason"] for s in c.saccades])


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

    def test_round_trips_to_neutral_and_the_short_ones_are_counted(self):
        # out of reach for 50 frames (21..70): a round trip with about 25 frames in neutral; for 30 frames (21..50): one
        # with less than SHORT_STAY (0.5 s) in neutral
        self.assertEqual(eye_gaze.SHORT_STAY, 15)
        aside = camera(cam(0, (0.0, 8.0, 0.0)), cam(LAST, (0.0, 8.0, 0.0)))     # off centre: coming back is a saccade
        for last_far, short in ((70, 0), (50, 1)):
            result = run_gaze(dance=head_turn({0: 0.0, 20: 0.0, 21: 60.0, last_far: 60.0, last_far + 1: 0.0}),
                              cam_motion=aside)
            self.assertEqual([s["reason"] for s in result.saccades], ["to_neutral", "to_camera"], last_far)
            trips = result.report["round_trips"]
            self.assertEqual((trips["count"], trips["short"]), (1, short), last_far)
            stay = sum(1 for look in result.looks if look.state == "neutral")
            self.assertEqual(trips["neutral_frames"], [stay])
            self.assertEqual(stay <= eye_gaze.SHORT_STAY, bool(short))
        self.assertEqual(run_gaze().report["round_trips"], {"count": 0, "short": 0, "neutral_frames": []})

    def test_time_near_each_limit_is_reported(self):
        # within 10 % of a limit, on the eye angle before the drift
        above = run_gaze(cam_motion=camera(cam(0, (10.0, 0.0, 0.0)), cam(LAST, (10.0, 0.0, 0.0))), life=True)
        self.assertEqual(above.report["near_limit"], {"up": 1.0, "down": 0.0, "side": 0.0, "any": 1.0})
        side = run_gaze(cam_motion=camera(cam(0, (0.0, -25.0, 0.0)), cam(LAST, (0.0, -25.0, 0.0))))
        self.assertEqual(side.report["near_limit"], {"up": 0.0, "down": 0.0, "side": 1.0, "any": 1.0})
        ahead = run_gaze(life=True)
        self.assertEqual(ahead.report["near_limit"], {"up": 0.0, "down": 0.0, "side": 0.0, "any": 0.0})
        half = run_gaze(cam_motion=cut_at_60(0.0, -25.0))                         # at the side limit after the cut
        self.assertTrue(0.4 < half.report["near_limit"]["side"] < 0.6)

    def test_frames_that_do_not_change_get_no_key(self):
        result = run_gaze(life=False)
        self.assertEqual([k.frame for k in result.motion.bones], [0, LAST])

    def test_the_shares_add_up_to_one(self):
        result = run_gaze(dance=head_turn({0: 0.0, 40: 60.0}), cam_motion=cut_at_60(-8.0, 8.0), life=True)
        counts = result.report["counts"]
        self.assertEqual(sum(counts.values()), LAST + 1)
        self.assertEqual(set(counts), {"on_camera", "at_limit", "neutral", "in_saccade", "reacting"})
        self.assertAlmostEqual(sum(result.report["shares"].values()), 1.0, places=9)


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
        for path, data in ((self.dance, vmd.dumps(head_turn({0: 0.0, 60: 30.0, 120: 0.0}))),
                           (self.camera, vmd.dumps(cut_at_60(-6.0, 6.0))),
                           (self.model, rin_like_bytes())):
            with open(path, "wb") as f:
                f.write(data)

    def test_writes_the_eyes_the_report_and_the_debug(self):
        out = os.path.join(self.folder, "sub", "eyes.vmd")
        report, debug = os.path.join(self.folder, "r.json"), os.path.join(self.folder, "d.json")
        code, result = run([self.dance, self.camera, self.model, out, "--report", report, "--debug", debug, "--seed", "3"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["out"], os.path.abspath(out))
        back = vmd.load(out)
        self.assertEqual(result["keys"], len(back.bones))
        self.assertEqual({k.name for k in back.bones}, {"両目"})
        self.assertEqual(back.model_name, "dancer")
        self.assertEqual(result["frames"], [0, LAST])
        self.assertEqual(result["cuts"], 1)
        self.assertAlmostEqual(sum(result["shares"].values()), 1.0, places=3)
        self.assertEqual(result["seed"], 3)
        self.assertEqual(result["convention"], {"key_rotation_signs": list(fk.KEY_ROTATION_SIGNS)})
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertEqual(full["counts"], result["counts"])
        self.assertEqual(sum(full["counts"].values()), LAST + 1)
        self.assertEqual(full["cuts"], [60])
        self.assertEqual(len(full["saccades"]["list"]), full["saccades"]["count"])
        self.assertEqual(full["reanchored"], result["reanchored"])
        self.assertEqual(set(full["reanchored"]), {"count", "by_reason"})
        self.assertEqual(full["round_trips"], result["round_trips"])
        self.assertEqual(set(result["near_limit"]), {"up", "down", "side", "any"})
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
        self.assertEqual(set(result["soft_limit"]), {"from", "frames", "error", "pull"})
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
        for argv in ([self.dance, self.camera, self.model, self.dance],
                     [self.dance, self.camera, self.model, out, "--report", self.camera],
                     [self.dance, self.camera, self.model, out, "--probe", self.model],
                     [self.dance, self.camera, self.model, out, "--report", os.path.join(self.folder, "r.json"),
                      "--debug", os.path.join(self.folder, "r.json")],
                     [self.dance, self.camera, self.model, out, "--max-yaw", "0"],
                     [self.dance, self.camera, self.model, out, "--max-pitch", "60"],
                     [self.dance, self.camera, self.model, out, "--max-down", "0"],
                     [self.dance, self.camera, self.model, out, "--max-pitch", "8", "--max-up", "4"],   # one or the other
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


REAL_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_smooth_twist.vmd")
REAL_CAMERA = real_file("_spike", "out", "hibikase", "variants", "camera_D_generated.vmd")
FINAL_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_smooth_dn_twist.vmd")
HANDHELD = real_file("_spike", "out", "hibikase", "variants", "camera_D_handheld.vmd")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"


@unittest.skipUnless(REAL_DANCE and REAL_CAMERA and os.path.isfile(RIN), "the dance, the camera or Sour's Rin is not here")
class RealSongTest(unittest.TestCase):
    def test_the_whole_song(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out, report = os.path.join(folder, "eyes.vmd"), os.path.join(folder, "r.json")
        started = time.time()
        code, result = run([REAL_DANCE, REAL_CAMERA, RIN, out, "--report", report])
        seconds = time.time() - started
        self.assertEqual(code, 0, result)
        self.assertLess(seconds, 60.0)
        back = vmd.load(out)
        self.assertEqual({k.name for k in back.bones}, {"両目"})
        self.assertGreater(len(back.bones), 1000)
        self.assertEqual(back.model_name, vmd.load(REAL_DANCE).model_name)
        self.assertEqual(result["frames"], [0, 7742])
        self.assertEqual(result["cuts"], 20)                         # camera_D cuts 21 shots
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertEqual(sum(full["counts"].values()), 7743)
        self.assertAlmostEqual(sum(full["shares"].values()), 1.0, places=9)
        self.assertEqual(full["eye"]["forward"], [0.0, 0.0, -1.0])
        for key in back.bones:
            gaze = fk.rotate(fk.applied(key.rotation), FORWARD)
            self.assertLessEqual(abs(math.degrees(math.atan2(gaze[0], -gaze[2]))), eye_gaze.MAX_YAW + 1e-3)
            pitch = math.degrees(math.asin(max(-1.0, min(1.0, gaze[1]))))
            self.assertLessEqual(pitch, eye_gaze.MAX_UP + 1e-3)
            self.assertGreaterEqual(pitch, -eye_gaze.MAX_DOWN - 1e-3)


@unittest.skipUnless(FINAL_DANCE and HANDHELD and os.path.isfile(RIN), "the final dance, the handheld camera or Rin is not here")
class FinalSongTest(unittest.TestCase):
    def test_the_final_dance_with_the_handheld_camera(self):
        # the handheld camera has a key on every frame and shakes by about 0.3 degrees: the same 20 cuts, and the
        # shake starts no saccades (review 8)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        out, report = os.path.join(folder, "eyes.vmd"), os.path.join(folder, "r.json")
        started = time.time()
        code, result = run([FINAL_DANCE, HANDHELD, RIN, out, "--report", report])
        self.assertEqual(code, 0, result)
        self.assertLess(time.time() - started, 60.0)
        self.assertEqual((result["frames"], result["cuts"]), ([0, 7742], 20))
        with open(report, encoding="ascii") as f:
            full = json.load(f)
        self.assertEqual(sum(full["counts"].values()), 7743)
        self.assertLess(full["saccades"]["count"], 100)                          # 132 before review 8
        self.assertLess(full["round_trips"]["count"], 25)                        # 46 before review 8
        for key in vmd.load(out).bones:
            yaw, pitch = eye_gaze.angles_of(fk.rotate(fk.applied(key.rotation), FORWARD))
            self.assertLessEqual(abs(yaw), eye_gaze.MAX_YAW + 1e-3)
            self.assertTrue(-eye_gaze.MAX_DOWN - 1e-3 <= pitch <= eye_gaze.MAX_UP + 1e-3, (key.frame, pitch))


if __name__ == "__main__":
    unittest.main()
