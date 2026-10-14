"""tools/eye_gaze.py: eyes that look on their own (fixations on where the face goes, saccades that lead the head's
turns, eye contact planned where the camera stays within reach) as a 両目 track to load after the dance."""
import contextlib
import hashlib
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
from mmd_cli.formats import pmx, pmx_edit, vmd
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


# the hands, laid out as Sour's Rin's: the wrist, which a dance moves by its translation here, and the finger tips on it
# (the points tools/eye_gaze.py looks at), as offsets from the wrist on her left (mirrored on her right)
WRISTS = {"右": (-4.652, 12.41, -0.237), "左": (4.652, 12.41, -0.237)}
TIPS = (("人指３先", (1.294, -0.954, -0.181)), ("中指３先", (1.401, -0.985, -0.026)), ("親指２先", (0.644, -0.92, -0.552)),
        ("小指３先", (1.15, -0.84, 0.244)))
# a hand that points up: the index finger raised 1.6 units (13 cm) above the wrist, the other fingers curled before the
# palm (the MV's 52 s)
POINTING = (("人指３先", (0.25, 1.6, -0.25)), ("中指３先", (0.55, 0.45, -0.4)), ("親指２先", (0.3, 0.5, -0.5)),
            ("小指３先", (0.5, 0.35, -0.3)))


def rin_like_bytes(tip=(0.0, 19.4, -0.83), hands=False, fingers=TIPS):
    """a body, a neck and a head with the eye bones laid out as on Sour's Rin: 両目 a handle above the head with its
    tip (両目先) straight ahead unless `tip` says otherwise, the eyes lower, each turning with 両目 (append ratio 1);
    with `hands` the wrists (translatable, on 上半身) and their finger tips (`fingers`: offsets from the left wrist)"""
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
    if hands:
        for side, s in (("右", -1.0), ("左", 1.0)):
            wx, wy, wz = WRISTS[side]
            wrist = len(bones)
            bones.append((side + "手首", 2, (wx, wy, wz), {"flags": NORMAL | TRANSLATE}))
            for name, (dx, dy, dz) in fingers:
                bones.append((side + name, wrist, (wx + s * dx, wy + dy, wz + dz), {}))
    return w.build(name="rin-like", bones=[w.bone(n, parent=p, position=pos, **kw) for n, p, pos, kw in bones])


MODEL = pmx.loads(rin_like_bytes())
HANDED = pmx.loads(rin_like_bytes(hands=True))


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


def world_steps_outside_saccades(result, first=0, keep=lambda i: True):
    """degrees the gaze moves in the world from frame i to i + 1 (i from `first`, and keep(i)), for the steps that
    touch no saccade frame; from the angles before the life (drift and microsaccades) is added"""
    moving = set()
    for s in result.saccades:
        moving.update(range(s["frame"], s["frame"] + s["frames"]))
    gazes = [fk.rotate(s.head, fk.rotate(eye_gaze.eye_rotation(*look.base), FORWARD))
             for s, look in zip(result.sights, result.looks)]
    return [degrees_between(gazes[i], gazes[i + 1]) for i in range(first, len(gazes) - 1)
            if i not in moving and i + 1 not in moving and keep(i)]


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


UNIT_M = 0.08                               # metres in a unit of the model (Sour's Rin: 1 unit = 8 cm)


def hand_rest(side):
    """where the hand's look point is at rest (the tool's own hand_points on a still dance, not a copy of its rule)"""
    return eye_gaze.hand_points(HANDED, head_turn({0: 0.0}, last=1))[side][0]


def hand_aim_rest(side):
    """where the eyes aim on the hand at rest (the tool's own hand_aims on a still dance): on the open hand of the
    model, the middle finger's tip, 7 cm below and to the outside of the look point"""
    return eye_gaze.hand_aims(HANDED, head_turn({0: 0.0}, last=1))[side][0]


def ahead(yaw, pitch, metres):
    """the world point `metres` from the eye center in the direction (yaw, pitch) of the head at rest"""
    return tuple(e + d * metres / UNIT_M for e, d in zip(EYE_CENTER, direction(yaw, pitch)))


def hand_dance(points, side="右", head=None, axis="y", last=LAST, at=hand_rest):
    """a still dance whose hand `side` is at points {frame: world point, or None for by her side}, straight between
    keys, and whose head turns by {frame: degrees} about `axis`; the point is where `at` puts the hand at rest (its
    look point, or with hand_aim_rest where the eyes aim on it)"""
    keys = list(head_turn(head or {0: 0.0}, axis=axis, last=last).bones)
    rest = at(side)
    for frame, point in sorted(points.items()):
        move = (0.0, 0.0, 0.0) if point is None else tuple(p - r for p, r in zip(point, rest))
        keys.append(vmd.BoneKey(side + "手首", frame, move, fk.IDENTITY))
    return vmd.Motion(model_name="dancer", bones=keys)


def run_hands(dance, cam_motion=BEHIND, **kw):
    return eye_gaze.gaze(HANDED, dance, cam_motion, life=False, **kw)


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

    def test_a_quick_sway_is_countered_by_the_eyes(self):
        # the head sways 3 degrees either way twice a second (the camera behind her): between saccades (a glance may
        # come) the eyes turn against all of it, so the gaze stays put in the world (the vestibulo-ocular reflex: a
        # gain of about 1 at 0.5 to 5 Hz in a person; review gaze-smooth 1.10), and no recentre is needed.  A gain
        # of 0.6 would leave 40 % of the head's path in the gaze
        sway = {f: (3.0 if (f // 8) % 2 else -3.0) for f in range(0, LAST + 1, 8)}
        dance = head_turn(sway)
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        heads = [fk.rotate(s.head, FORWARD) for s in result.sights]
        gazes = [world_gaze(s, look) for s, look in zip(result.sights, result.looks)]
        yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
        frames = [i for i in range(21, len(heads)) if i not in moving and i - 1 not in moving]
        head_path = sum(abs(yaw(heads[i]) - yaw(heads[i - 1])) for i in frames)
        gaze_path = sum(abs(yaw(gazes[i]) - yaw(gazes[i - 1])) for i in frames)
        self.assertGreater(head_path, 40.0)
        self.assertLess(gaze_path, 0.1 * head_path)
        self.assertEqual([s for s in result.saccades if s["reason"] == "recentre"], [])

    def test_between_saccades_the_gaze_stays_put_in_the_world(self):
        # review gaze-smooth 1.6: a person cannot glide the eyes slowly between still targets.  With the head still,
        # or turning slowly (10 deg/s), the gaze outside saccades moves less than 0.1 degree a frame (3 deg/s); the
        # eyes keep up with a turn by saccades, not by sliding with the head (stage 5 first slid them at 8 % of the
        # gap a frame, and the gaze flowed with the head)
        for dance in (head_turn({0: 0.0}), head_turn({0: 0.0, 30: 0.0, 90: 20.0}), head_turn({0: 0.0, 20: 0.0, 110: 15.0}, axis="x")):
            result = run_gaze(dance=dance, cam_motion=BEHIND)
            steps = world_steps_outside_saccades(result)
            self.assertGreater(len(steps), 60)
            self.assertLess(max(steps), 0.1)

    def test_a_head_that_moves_on_gets_a_saccade_the_way_it_went(self):
        # the head turns 40 degrees in 10 frames (120 deg/s, not a fast turn) and stays: the eyes hold the gaze, run
        # out of range, and a recentre saccade takes them the way the head went; between saccades the gaze stays put
        dance = head_turn({0: 0.0, 40: 0.0, 50: 40.0})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        recentres = [s for s in result.saccades if s["reason"] == "recentre"]
        self.assertTrue(1 <= len(recentres) <= 2, result.saccades)
        s = recentres[0]
        landed = s["frame"] + s["frames"] - 1
        before, after = result.looks[s["frame"] - 1].base[0], result.looks[landed].base[0]
        self.assertGreater(after - before, 3.0, s)                     # toward her left, the way she turned
        for look in result.looks:
            self.assertLess(abs(look.base[0]), eye_gaze.EDGE * LIMITS.yaw, look)       # short of the edge
        # between saccades the gaze stays put until the eyes are pressed against their wall (beyond the free zone),
        # where the head carries the rest of it
        free = eye_gaze.free_zone(LIMITS)
        inside = lambda i: abs(result.looks[i].base[0]) <= free.yaw and abs(result.looks[i + 1].base[0]) <= free.yaw
        steps = world_steps_outside_saccades(result, keep=inside)
        self.assertGreater(len(steps), 60)
        self.assertLess(max(steps), 0.1)
        # once the head has stopped (frame 50) and the last saccade has landed, the eyes are within GAP of the middle
        last = max(t["frame"] + t["frames"] for t in result.saccades)
        self.assertLess(abs(result.looks[max(last, 60)].base[0]), eye_gaze.GAP)

    def test_a_beat_nod_is_countered_up_and_down(self):
        # the head nods 8 degrees up and down twice a second for 7 seconds: the eyes turn against all of it, up and
        # down (a person's gain is about 1 vertically too at 0.4 to 4 Hz; review gaze-smooth 1.10), so the gaze
        # stays put; where the eyes reach their wall (6 up, 10 down are small) the rest of the nod carries the gaze.
        # Stage 5 first countered half of it (gain 0.5) and the gaze rode the nods.  No saccade back and forth
        nod = {int(round(7.5 * k)): (8.0 if k % 2 else -8.0) for k in range(0, 29)}
        dance = head_turn(nod, axis="x", last=210)
        result = eye_gaze.gaze(MODEL, dance, camera(cam(0, (0.0, 180.0, 0.0)), cam(210, (0.0, 180.0, 0.0))), life=False)
        self.assertEqual([s for s in result.saccades if s["reason"] != "glance"], [])
        heads = [fk.rotate(s.head, FORWARD) for s in result.sights]
        pitch = lambda v: math.degrees(math.atan2(v[1], math.hypot(v[0], v[2])))
        head_range = max(pitch(h) for h in heads[30:]) - min(pitch(h) for h in heads[30:])
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        off_wall = [i for i in range(30, len(heads)) if i not in moving and
                    -eye_gaze.WALL_SEEN * LIMITS.down < result.looks[i].base[1] < eye_gaze.WALL_SEEN * LIMITS.up]
        self.assertGreater(len(off_wall), 60)
        gaze = [pitch(world_gaze(result.sights[i], result.looks[i])) for i in off_wall]
        self.assertGreater(head_range, 14.0)
        self.assertLess(max(gaze) - min(gaze), 0.3 * head_range, (head_range, max(gaze) - min(gaze)))

    def test_a_beat_nod_that_presses_the_eyes_to_their_wall_moves_nothing(self):
        # stage 6: the head nods 10 degrees up and down twice a second (80 deg/s).  Countered, the eyes go beyond their
        # free zone up and down on every nod, but the head lets go of them before a press has lasted long enough for a
        # saccade off the wall (a nod with the beat comes back: a saccade on every nod would make the iris bob; review
        # gaze-v8, 5.4 (1)).  Only glances
        nod = {int(round(7.5 * k)): (10.0 if k % 2 else -10.0) for k in range(0, 29)}
        dance = head_turn(nod, axis="x", last=210)
        result = eye_gaze.gaze(MODEL, dance, camera(cam(0, (0.0, 180.0, 0.0)), cam(210, (0.0, 180.0, 0.0))), life=False)
        free = eye_gaze.free_zone(LIMITS)
        beyond = [i for i, look in enumerate(result.looks) if look.base[1] > free.up or look.base[1] < -free.down]
        self.assertGreater(len(beyond), 30, len(beyond))              # the nods press the eyes beyond the free zone
        self.assertEqual([s for s in result.saccades if s["reason"] != "glance"], [])

    def test_eyes_held_low_by_a_head_that_settled_up_come_back_soon(self):
        # stage 6: the head tips 7.5 degrees up in 10 frames and stays (the camera behind her).  Holding the gaze, the
        # eyes would turn 7.5 degrees down, three quarters of their range below: the iris low in the eye (on 2955 to
        # 2967 of the MV v7 it stayed so for 0.4 s, the gap to the face's way under 8 degrees).  Pressed beyond the
        # free zone with the face's way well above, a saccade off the wall takes them the way the head went within
        # half a second of its settling (seed 0 glances only at 62), and they stay near the middle
        dance = head_turn({0: 0.0, 30: 0.0, 40: 7.5}, axis="x")
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        pitch = lambda v: math.degrees(math.atan2(v[1], math.hypot(v[0], v[2])))
        self.assertAlmostEqual(pitch(fk.rotate(result.sights[45].head, FORWARD)), 7.5, places=3)    # tipped up
        back = [s for s in result.saccades if s["reason"] == "wall"]
        self.assertTrue(back and 30 <= back[0]["frame"] <= 55, result.saccades)
        landed = back[0]["frame"] + back[0]["frames"] - 1
        self.assertGreater(result.looks[landed].base[1] - result.looks[back[0]["frame"] - 1].base[1], 3.0)   # up
        self.assertLess(max(abs(look.base[1]) for look in result.looks[max(landed + 1, 45):91]), 2.0)

    def test_the_same_turn_sideways_keeps_the_gaze_where_it_was(self):
        # the same 7.5 degrees sideways are 42 % of the eyes' range, inside the free zone: they keep the gaze
        dance = head_turn({0: 0.0, 30: 0.0, 40: 7.5})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        self.assertEqual([s for s in result.saccades if s["reason"] in ("recentre", "wall", "quick")], [])
        self.assertAlmostEqual(result.looks[55].base[0], -7.5, delta=0.3)

    def test_a_fast_shake_that_comes_back_is_countered(self):
        # the head shakes 12 degrees and back at 180 deg/s, twice: fast, but no gaze shift (it comes back), so the
        # eyes turn against all of it (a person's gain stays near 1 at 2 to 6 Hz; review gaze-smooth 1.10), as they
        # do every turn of the head (stage 6).  Stage 5 first held it off by the head's speed alone
        shake = head_turn({0: 0.0, 40: 0.0, 42: 12.0, 44: 0.0, 46: 12.0, 48: 0.0})
        result = run_gaze(dance=shake, cam_motion=BEHIND)
        self.assertGreaterEqual(len(eye_gaze.fast_turns(result.sights, FORWARD)[1]), 1)     # fast enough to be a turn
        heads = [fk.rotate(s.head, FORWARD) for s in result.sights]
        gazes = [world_gaze(s, look) for s, look in zip(result.sights, result.looks)]
        yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        frames = [i for i in range(40, 50) if i not in moving and i - 1 not in moving]
        head_path = sum(abs(yaw(heads[i]) - yaw(heads[i - 1])) for i in frames)
        gaze_path = sum(abs(yaw(gazes[i]) - yaw(gazes[i - 1])) for i in frames)
        self.assertGreater(head_path, 30.0)
        self.assertLess(gaze_path, 0.1 * head_path)

    def test_in_a_sustained_fast_turn_the_reflex_counters_the_head_and_a_quick_phase_goes_its_way(self):
        # stage 6 (the coordinator, after the remeasure of the MV v7: the head carried the gaze in 57 % of a07's
        # large gaze changes): the reflex is off only while the eyes jump.  The head turns 60 degrees at 300 deg/s
        # and at once comes back 18 at 135 deg/s.  From the onset the eyes turn against the head, all of it up to
        # MAX_STEP a frame (the head's 10 degrees a frame is more); at the back of the free zone a quick phase takes
        # them the way of the turn, not sooner than QUICK_AFTER frames after the lead's landing.  Stage 5 held the
        # reflex off inside the turn: the eyes stayed where the lead put them and the head carried the gaze.  The
        # head turns 90 degrees at 300 deg/s here, then comes back 18 at 135 deg/s and stands
        dance = head_turn({0: 0.0, 60: 0.0, 69: 90.0, 73: 72.0, LAST: 72.0})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
        heads = [yaw(fk.rotate(s.head, FORWARD)) for s in result.sights]
        free = eye_gaze.free_zone(LIMITS)
        countered = 0
        for i in range(62, 70):
            a, b = result.looks[i - 1].base[0], result.looks[i].base[0]
            if i not in moving and i - 1 not in moving and abs(a) <= free.yaw and abs(b) <= free.yaw:
                self.assertAlmostEqual(a - b, min(heads[i] - heads[i - 1], eye_gaze.MAX_STEP), delta=0.05)
                countered += 1
        self.assertGreaterEqual(countered, 2)
        quick = [s for s in result.saccades if s["reason"] == "quick"]
        self.assertTrue(quick and 61 <= quick[0]["frame"] <= 69, result.saccades)
        before = result.saccades[result.saccades.index(quick[0]) - 1]
        self.assertEqual(before["reason"], "lead")
        self.assertGreaterEqual(quick[0]["frame"] - (before["frame"] + before["frames"] - 1), 4)      # 0.13 s
        landed = quick[0]["frame"] + quick[0]["frames"] - 1
        self.assertGreater(result.looks[landed].base[0] - result.looks[quick[0]["frame"] - 1].base[0], 5.0)
        # between saccades, with the eyes inside the free zone and the head under MAX_STEP a frame (from frame 70),
        # the gaze stays put in the world
        inside = lambda i: max(abs(result.looks[i].base[0]), abs(result.looks[i + 1].base[0])) <= free.yaw
        steps = world_steps_outside_saccades(result, first=70, keep=inside)
        self.assertGreater(len(steps), 20)
        self.assertLess(max(steps), 0.1)

    def test_a_long_spin_beats_with_quick_phases_its_way(self):
        # a spin of 2 s at 600 deg/s (review gaze-smooth Q5): countered, the eyes reach the back wall in 3 frames (8
        # degrees a frame, the head's 20 is more), and quick phases take them the way of the spin again and again,
        # QUICK_AFTER to QUICK_AFTER + QUICK_SPREAD frames after each landing (drawn for each, so they do not beat
        # at one rhythm), never to the edge; outside saccades they turn at most MAX_STEP a frame
        spin = head_turn(dict([(0, 0.0), (30, 0.0)] + [(30 + 5 * k, 100.0 * k) for k in range(1, 13)]), last=LAST)
        result = run_gaze(dance=spin, cam_motion=BEHIND)
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        steps = [abs(result.looks[i].base[0] - result.looks[i - 1].base[0]) for i in range(32, 91)
                 if i not in moving and i - 1 not in moving]
        self.assertGreater(len(steps), 20)
        self.assertLessEqual(max(steps), eye_gaze.MAX_STEP + 1e-6)
        quick = [s for s in result.saccades if s["reason"] == "quick" and 32 <= s["frame"] <= 85]
        self.assertGreaterEqual(len(quick), 5, result.saccades)
        waits = []
        for s in quick:
            k = result.saccades.index(s)
            before = result.saccades[k - 1]
            waits.append(s["frame"] - (before["frame"] + before["frames"] - 1))
            landed = s["frame"] + s["frames"] - 1
            self.assertGreater(result.looks[landed].base[0] - result.looks[s["frame"] - 1].base[0], 10.0, s)
        self.assertTrue(all(4 <= w <= 9 for w in waits),                   # 0.13 to 0.3 s: a slow phase of a person's OKN is 0.26 s
                        waits)
        self.assertGreaterEqual(len(set(waits)), 3, waits)
        self.assertLess(max(abs(look.base[0]) for look in result.looks), eye_gaze.EDGE * LIMITS.yaw)


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
            # it takes two frames or more and has landed LEAD frames before the head starts (stage 5: brought
            # forward so that the longer saccade still ends before the head moves)
            self.assertGreaterEqual(leads[0]["frames"], 2)
            landed = leads[0]["frame"] + leads[0]["frames"] - 1
            self.assertTrue(onset - eye_gaze.LEAD[1] <= landed <= onset - eye_gaze.LEAD[0], leads)
            # the a20 measure: the eye in the head moves more than 3 degrees the way of the turn in the 6 frames
            # before the head starts
            self.assertGreater(result.looks[onset].yaw - result.looks[onset - 6].yaw, 3.0)
            # nothing else moves the eyes in the frames before the lead
            others = [s for s in result.saccades if s["reason"] != "lead" and onset - eye_gaze.QUIET - 6 <= s["frame"] < onset]
            self.assertEqual(others, [])

    def test_the_lead_waits_head_still_then_the_reflex_counters_the_turn(self):
        result = self.fast_turn()
        lead = [s for s in result.saccades if s["reason"] == "lead"][0]
        landed = lead["frame"] + lead["frames"] - 1
        # until the head starts the eyes keep their angle in the head
        for i in range(landed, 61):
            self.assertAlmostEqual(result.looks[i].base[0], result.looks[landed].base[0], places=6)
        for i in range(landed + 1, 61):
            self.assertEqual(result.looks[i].state, "lead")
        # from the onset (the head at 300 deg/s, a sustained turn of 60 degrees) the reflex counters it, MAX_STEP a
        # frame (stage 6, the coordinator: the reflex is off only while the eyes jump, until they land; stage 5 held
        # it off through the turn and the head carried the gaze): on the onset the gaze becomes a point in the world
        # where the lead put it, and from the next frame the eyes turn back against the head
        self.assertEqual(result.looks[61].state, "free")
        for i in (62, 63):
            self.assertAlmostEqual(result.looks[i - 1].base[0] - result.looks[i].base[0], eye_gaze.MAX_STEP, places=6)
        # pressed against the back of their range, the eyes do not stay there: the next saccade (a quick phase in
        # the turn, or off the wall after it) takes them the way of the turn again
        after = [s for s in result.saccades if s["frame"] > landed][0]
        self.assertIn(after["reason"], ("quick", "wall"), result.saccades)
        self.assertLessEqual(after["frame"], 70, result.saccades)
        self.assertGreater(result.looks[after["frame"] + after["frames"] - 1].base[0],
                           result.looks[after["frame"] - 1].base[0] + 5.0)
        # once the turn is over the gaze stays put where it arrived (review gaze-smooth 1.10)
        steps = world_steps_outside_saccades(result, first=68)
        self.assertGreater(len(steps), 30)
        self.assertLess(max(steps), 0.1)

    def test_a_lead_never_jumps_back_against_its_turn(self):
        # review gaze-v8 (3.5): eyes already beyond the lead's cap the way of the turn were taken 2 degrees back by the
        # lead, and the quick phase after it went 15 to 25 degrees forward: a reversal (22 times in the MV v8).  Here
        # the head turns to her right at 60 deg/s, so the countered eyes are pressed to her left, then turns fast to
        # her left: the lead keeps them where they are or takes them further its way
        dance = head_turn({0: 0.0, 20: 0.0, 45: -50.0, 50: -50.0, 56: 10.0, LAST: 10.0})
        result = run_gaze(dance=dance, cam_motion=BEHIND)
        onset = 51
        cap = eye_gaze.LEAD_SHARE * LIMITS.yaw
        self.assertGreater(result.looks[onset - 8].base[0], cap, [round(look.base[0], 1) for look in result.looks[30:56]])
        for s in result.saccades:
            if onset - 12 <= s["frame"] <= onset:
                before = result.looks[s["frame"] - 1].base[0]
                after = result.looks[s["frame"] + s["frames"] - 1].base[0]
                self.assertGreaterEqual(after - before, -0.01, (s, before, after))

    def test_a_turn_with_a_dip_gets_one_lead(self):
        # the head turns 30 degrees, slows for a frame, and turns 30 more: two runs above TURN_SPEED with the same
        # onset.  One lead, not two saccades two frames apart (68 % of the jumps that followed a landing within 3
        # frames in the MV v6d were such pairs)
        dance = head_turn({0: 0.0, 60: 0.0, 63: 30.0, 64: 31.0, 67: 60.0})
        seen = run_gaze(dance=dance, cam_motion=BEHIND).sights
        turns = eye_gaze.fast_turns(seen, FORWARD)[1]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0][0], turns[1][0])                       # the same onset
        for seed in range(6):
            leads = eye_gaze.plan(seen, FORWARD, LIMITS, seed, False)[3]
            self.assertEqual(len(leads), 1, (seed, leads))
            result = run_gaze(dance=dance, cam_motion=BEHIND, seed=seed)
            self.assertEqual(len([s for s in result.saccades if s["reason"] == "lead"]), 1, (seed, result.saccades))

    def test_the_lead_lands_where_the_face_will_point_within_the_limit(self):
        for degrees in (60.0, -60.0, 40.0):
            result = self.fast_turn(degrees=degrees)
            lead = [s for s in result.saccades if s["reason"] == "lead"][0]
            before = result.looks[lead["frame"] - 1].base
            landed = result.looks[lead["frame"] + lead["frames"] - 1].base
            # the way of the turn, several degrees beyond where the eyes were, never at the edge
            way = 1.0 if degrees > 0 else -1.0
            self.assertGreater(way * (landed[0] - before[0]), 5.0, (degrees, before, landed))
            self.assertLess(abs(landed[0]), eye_gaze.EDGE * LIMITS.yaw, degrees)


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
        error = eye_gaze.CONTACT_ERROR
        self.assertEqual(eye_gaze.reachable([((zone.yaw + error - 0.5, 0.0), False), ((zone.yaw + error + 0.5, 0.0), False),
                                             ((0.0, 0.0), True)], LIMITS), [True, False, False])


def swings(seed, last=400):
    """a head that looks away (25 to 45 degrees) and back toward the camera in front, again and again, at different
    speeds, so that contacts are planned with many ways in"""
    rng = random.Random(seed)
    keys = [vmd.BoneKey("全ての親", 0, (0.0, 0.0, 0.0), fk.IDENTITY), vmd.BoneKey("全ての親", last, (0.0, 0.0, 0.0), fk.IDENTITY)]
    frame = 0
    while frame < last:
        away = (rng.uniform(25, 45) * rng.choice((-1, 1)), rng.uniform(-10, 10))
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(away[1], away[0], 0.0)))
        frame += rng.randint(15, 30)
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(away[1], away[0], 0.0)))
        frame += rng.randint(2, 9)
        face = (rng.uniform(-6, 6), rng.uniform(-4, 4))
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(face[1], face[0], 0.0)))
        frame += rng.randint(55, 80)
        keys.append(vmd.BoneKey("頭", frame, (0.0, 0.0, 0.0), mathutil.ui_to_quat(face[1], face[0], 0.0)))
        frame += rng.randint(2, 9)
    return vmd.Motion(model_name="dancer", bones=[k for k in keys if k.frame <= last])


class ContactTest(unittest.TestCase):
    def test_each_contact_has_one_saccade_in_and_one_out(self):
        # one saccade into each contact and one look away: once on the camera the eyes wait there for a contact due
        # within QUIET + 4 frames.  The saccade in was sized by the camera on the contact's first frame but made with
        # the camera of its own first frame, so it could land early, and the eyes looked away and back within 4
        # frames (frames 3240 and 6680 of the MV v6d, stage 5)
        soon = eye_gaze.QUIET + eye_gaze.saccade_frames(float("inf"))
        for seed in (53, 7, 21):
            result = eye_gaze.gaze(MODEL, swings(seed), camera(cam(0), cam(400)), life=False, seed=seed)
            self.assertGreaterEqual(len(result.contacts), 3, seed)
            ins = [s for s in result.saccades if s["reason"] == "contact"]
            outs = [s for s in result.saccades if s["reason"] == "look_away"]
            self.assertEqual(len(ins), len(result.contacts), (seed, ins, result.contacts))
            self.assertLessEqual(len(outs), len(result.contacts), seed)
            for (a, b), s in zip(result.contacts, ins):
                landed = s["frame"] + s["frames"] - 1
                self.assertGreaterEqual(landed, a - soon, (seed, a, s))
                for look in result.looks[landed:a + 1]:
                    self.assertEqual(look.mode, "camera", (seed, a, s, look))

    def test_no_saccade_just_before_the_one_into_a_contact(self):
        # as the head swings to the camera the eyes used to recentre and jump onto the camera 2 or 3 frames later
        # (64 such pairs in 80 of these scenes): with a contact due they wait for it
        for seed in (0, 1, 6):
            result = eye_gaze.gaze(MODEL, swings(seed), camera(cam(0), cam(400)), life=False, seed=seed)
            for before, after in zip(result.saccades, result.saccades[1:]):
                if after["reason"] == "contact":
                    self.assertGreater(after["frame"] - (before["frame"] + before["frames"] - 1), 3, (seed, before, after))

    def test_a_camera_within_reach_too_briefly_gets_no_contact(self):
        # her head faces the camera only from frame 40 to 70 (31 frames), turned 40 degrees away otherwise
        dance = head_turn({0: 40.0, 38: 40.0, 40: 0.0, 70: 0.0, 72: 40.0})
        self.assertEqual(run_gaze(dance=dance).contacts, [])
        # (the head turns to the camera at 300 deg/s: faster than MAX_STEP a frame, the eyes would follow the camera a
        # frame late, as they do on the song's few head snaps during a contact)
        long_ = head_turn({0: 40.0, 16: 40.0, 20: 0.0, 90: 0.0, 92: 40.0})
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
            for s in result.saccades:
                if s["reason"] in ("contact", "look_away"):
                    inside.update(range(s["frame"], s["frame"] + s["frames"]))
            for i, look in enumerate(result.looks):
                if i not in inside:
                    self.assertGreater(look.error, eye_gaze.KEEP_OFF - 0.5, (seed, i, look))

    def assert_no_jump_and_kept_off(self, result):
        moving = set()
        for s in result.saccades:
            moving.update(range(s["frame"], s["frame"] + s["frames"]))
        for i in range(1, len(result.looks)):
            if i not in moving:
                a, b = result.looks[i - 1].base, result.looks[i].base
                self.assertLessEqual(math.hypot(b[0] - a[0], b[1] - a[1]), eye_gaze.MAX_STEP + 1e-6, i)
        for look in result.looks:
            self.assertGreater(look.error, eye_gaze.KEEP_OFF - 0.5, look)

    def test_a_camera_coming_near_the_gaze_moves_the_eyes_away(self):
        # the camera sweeps across her face in about 20 frames (too short for a contact): once the shortest fixation
        # is over, the eyes move away with a saccade before the camera reaches the gaze (reason "away")
        cams = camera(cam(0, (0.0, -40.0, 0.0)), cam(30, (0.0, -40.0, 0.0)), cam(70, (0.0, 40.0, 0.0)),
                      cam(LAST, (0.0, 40.0, 0.0)))
        result = run_gaze(cam_motion=cams)
        self.assertEqual(result.contacts, [])
        self.assert_no_jump_and_kept_off(result)
        self.assertIn("away", {s["reason"] for s in result.saccades})

    def test_a_camera_passing_over_the_gaze_is_a_saccade_not_a_flip(self):
        # the camera crosses the gaze 7 frames into the song, before the shortest fixation lets the eyes move on.
        # Keeping the gaze 5 degrees off it, the kept point would flip to the other side of the camera in one frame
        # as it passes the middle (10 degrees with no easing, as on frame 1763 of the MV v6d before stage 5); the
        # eyes move away with a saccade instead
        cams = camera(cam(0, (0.0, -14.0, 0.0)), cam(14, (0.0, 14.0, 0.0)), cam(20, (0.0, 60.0, 0.0)),
                      cam(LAST, (0.0, 60.0, 0.0)))
        result = run_gaze(cam_motion=cams)
        self.assertEqual(result.contacts, [])
        self.assert_no_jump_and_kept_off(result)
        away = [s for s in result.saccades if s["reason"] == "away"]
        self.assertTrue(away and away[0]["frame"] < eye_gaze.MIN_FIXATION, result.saccades)

    def test_a_head_snap_during_a_contact_is_followed_at_most_max_step_a_frame(self):
        # the head snaps 10 degrees in one frame while she looks at the camera: the eyes follow the camera at most
        # MAX_STEP a frame and are back on it the frame after
        result = run_gaze(dance=head_turn({0: 0.0, 60: 0.0, 61: 10.0, LAST: 10.0}))
        self.assertEqual(result.contacts, [(0, LAST)])
        a, b, c = result.looks[60], result.looks[61], result.looks[62]
        self.assertAlmostEqual(math.hypot(b.base[0] - a.base[0], b.base[1] - a.base[1]), eye_gaze.MAX_STEP, places=6)
        self.assertGreater(b.error, 1.0)
        self.assertLess(c.error, 0.3)


class HandTest(unittest.TestCase):
    """stage 6 (the request: "near things bring the eyes together"; the MV's 52 seconds, fingers before her face and
    the eyes parallel): the eyes choose her hand as their target where it holds still or moves slowly near before her
    face and within their reach, jump onto it, follow it, and jump off it when it goes"""

    def hand_on(self, result, i):
        """degrees between the gaze written on frame i and where the eyes aim on the hand (the tip of its longest
        finger, review gaze-v8), seen from the eyes"""
        sight, look = result.sights[i], result.looks[i]
        point = result.hand_aims["右"][i]
        return degrees_between(world_gaze(sight, look), tuple(p - e for p, e in zip(point, sight.eye)))

    def test_a_hand_held_before_her_face_is_looked_at(self):
        # the tip of her middle finger held 30 cm before her face (the look point that chooses the look, the middle of
        # the hand, is 7 cm above and inside it): the eyes are on the finger's tip
        point = ahead(-6.0, -4.0, 0.30)
        result = run_hands(hand_dance({0: None, 39: None, 40: point, 79: point, 80: None}, at=hand_aim_rest))
        hands = result.report["hands"]["list"]
        self.assertEqual(len(hands), 1, hands)
        self.assertEqual(hands[0]["hand"], "右")
        self.assertTrue(abs(hands[0]["first"] - 40) <= 1 and abs(hands[0]["last"] - 79) <= 1, hands)
        self.assertAlmostEqual(hands[0]["metres"], 0.30, delta=0.01)
        into = [s for s in result.saccades if s["reason"] == "hand"]
        self.assertEqual(len(into), 1, result.saccades)
        landed = into[0]["frame"] + into[0]["frames"] - 1
        self.assertTrue(38 <= landed <= 41, into)
        for i in range(landed + 1, 79):
            self.assertEqual(result.looks[i].state, "hand", i)
            self.assertLess(self.hand_on(result, i), 0.5, i)
        # she looks away from it as it goes, with a saccade that starts by 3 frames after
        after = [s for s in result.saccades if s["frame"] >= 79]
        self.assertTrue(after and after[0]["frame"] <= 82 and after[0]["reason"] == "hand_away", result.saccades)
        self.assertGreater(self.hand_on(result, after[0]["frame"] + after[0]["frames"] - 1), 3.0)
        self.assertEqual(result.report["counts"]["hand"], sum(1 for look in result.looks if look.state == "hand"))

    def test_a_raised_finger_draws_the_eyes_up_to_it(self):
        # the MV's 52 s: her index finger raised before her face, the other fingers curled before the palm.  Aimed at
        # the middle of the hand (stage 6 first), the eyes looked down at the cuff, 24 degrees off the finger's tip,
        # 6 to 9 degrees down in the head (review gaze-v8).  They aim at the tip of the finger furthest from the wrist:
        # it is above their reach, so they go up as far as they reach and the gaze runs along the raised finger
        model = pmx.loads(rin_like_bytes(hands=True, fingers=POINTING))
        wrist = ahead(-4.0, -14.0, 0.33)                     # the wrist low before her face, the finger up past her eyes
        move = tuple(w - r for w, r in zip(wrist, WRISTS["右"]))
        keys = list(head_turn({0: 0.0}).bones) + [vmd.BoneKey("右手首", f, m, fk.IDENTITY) for f, m in
                                                  ((0, fk.ZERO), (39, fk.ZERO), (40, move), (79, move), (80, fk.ZERO))]
        result = eye_gaze.gaze(model, vmd.Motion(model_name="dancer", bones=keys), BEHIND, life=False)
        self.assertEqual(len(result.report["hands"]["list"]), 1, result.report["hands"])
        mirror = lambda d: (-d[0], d[1], d[2])
        offsets = {name: mirror(d) for name, d in POINTING}
        finger = lambda k: tuple(w + k * d for w, d in zip(wrist, offsets["人指３先"]))     # wrist to the raised tip
        curled = tuple(w + d for w, d in zip(wrist, offsets["中指３先"]))
        into = [s for s in result.saccades if s["reason"] == "hand"]
        self.assertEqual(len(into), 1, result.saccades)
        landed = into[0]["frame"] + into[0]["frames"] - 1
        up = eye_gaze.contact_zone(LIMITS).up
        for i in range(landed + 1, 79):
            sight, look = result.sights[i], result.looks[i]
            self.assertEqual(look.state, "hand", i)
            self.assertGreater(look.base[1], up - 0.5, i)                # up toward the finger, as far as they reach
            g = world_gaze(sight, look)
            toward = lambda p: tuple(a - e for a, e in zip(p, sight.eye))
            # on the raised finger and well off the curled fingers before the palm
            self.assertLess(min(degrees_between(g, toward(finger(k / 10.0))) for k in range(0, 11)), 1.5, i)
            self.assertGreater(degrees_between(g, toward(curled)), 5.0, i)

    def test_the_eyes_follow_a_hand_that_moves_slowly_ahead_of_it(self):
        # the hand moves 16 degrees across before her face in 2 seconds: the eyes follow it with no saccade (a person
        # tracks the hand she moves herself smoothly, the eyes a little ahead of it)
        a, b = ahead(-12.0, -4.0, 0.30), ahead(4.0, -2.0, 0.30)
        result = run_hands(hand_dance({0: None, 29: None, 30: a, 90: b, 91: None}, at=hand_aim_rest))
        hands = result.report["hands"]["list"]
        self.assertEqual(len(hands), 1, hands)
        self.assertTrue(abs(hands[0]["first"] - 30) <= 1 and abs(hands[0]["last"] - 90) <= 1, hands)
        starts = [s["frame"] for s in result.saccades if 33 <= s["frame"] <= 88]
        self.assertEqual(starts, [], result.saccades)
        rest = eye_gaze.angles_of(FORWARD)
        for i in range(34, 88):
            self.assertLess(self.hand_on(result, i), 1.5, i)
            step = math.hypot(result.looks[i].base[0] - result.looks[i - 1].base[0],
                              result.looks[i].base[1] - result.looks[i - 1].base[1])
            self.assertLess(step, 0.6, i)
            # ahead of the hand: on the side it moves to (her left, +yaw)
            aim, _ = eye_gaze._seen(result.sights[i], result.hand_aims["右"][i], FORWARD, rest)
            self.assertGreater(result.looks[i].base[0], aim[0], i)

    def test_a_hand_that_waves_fast_before_her_face_is_not_looked_at(self):
        # 24 degrees across and back every 6 frames for 2 seconds (240 deg/s): too fast to follow
        points = {0: None, 29: None}
        for k, frame in enumerate(range(30, 91, 3)):
            points[frame] = ahead(-12.0 if k % 2 else 12.0, -2.0, 0.30)
        points[91] = None
        result = run_hands(hand_dance(points))
        self.assertEqual(result.report["hands"]["list"], [])
        self.assertNotIn("hand", {look.state for look in result.looks})

    def test_a_hand_out_of_reach_too_far_or_too_near_is_not_looked_at(self):
        # at her chest (35 degrees below the eyes: they turn 10 at most), at arm's length and more (90 cm), and on her
        # face (12 cm: a hand over the eyes is no target to look at)
        for point in (ahead(-4.0, -35.0, 0.30), ahead(-4.0, -2.0, 0.90), ahead(-4.0, -2.0, 0.12)):
            result = run_hands(hand_dance({0: None, 39: None, 40: point, 79: point, 80: None}))
            self.assertEqual(result.report["hands"]["list"], [], point)

    def test_a_brief_visit_is_not_a_look(self):
        # a hand held before her face for 8 frames (0.27 s) is passed by, not looked at: a person's look at a gesture
        # lasts 0.46 s on average (Gullberg & Holmqvist 2006), and 5 of the 9 looks of the MV v8 that put the eyes on
        # the hand for only 2 to 4 frames between two large jumps looked like the eyes darting there and back (review
        # gaze-v8).  Held 10 frames, it is looked at
        point = ahead(-6.0, -4.0, 0.30)
        for last, looked in ((43, 0), (48, 0), (50, 1)):
            result = run_hands(hand_dance({0: None, 39: None, 40: point, last: point, last + 1: None}, at=hand_aim_rest))
            self.assertEqual(len(result.report["hands"]["list"]), looked, (last, result.report["hands"]["list"]))

    def test_a_hand_held_out_toward_the_camera_is_not_looked_at(self):
        # the camera is in reach of the eyes for 40 frames only (no contact) and her hand is held on its line: she
        # shows the hand to the viewer (the MV's 24.9 and 43 seconds); looking at it would cross the eyes at the viewer
        cams = camera(cam(0, (0.0, 40.0, 0.0)), cam(30, (0.0, 40.0, 0.0)), cam(31, (0.0, 8.0, 0.0)), cam(70, (0.0, 8.0, 0.0)),
                      cam(71, (0.0, 40.0, 0.0)), cam(LAST, (0.0, 40.0, 0.0)))
        yaw, pitch = expected_yaw((0.0, 8.0, 0.0))
        point = ahead(yaw, pitch, 0.35)
        result = run_hands(hand_dance({0: None, 33: None, 34: point, 67: point, 68: None}), cam_motion=cams)
        self.assertEqual(result.contacts, [])
        self.assertEqual(result.report["hands"]["list"], [])

    def test_a_palm_shown_to_the_viewer_is_not_looked_at(self):
        # the MV's 120.6 and 178.4 s: hands raised before her face with the palms turned to the viewer, a gesture to
        # the viewer; looking at it, her eyes dropped to the backs of her own hands (review gaze-v8).  The model's palm
        # faces down at rest: filmed from below (the camera 70 degrees down, out of the eyes' reach) the palm of the
        # hand held before her face faces the camera and is not looked at; filmed from behind it is
        point = ahead(-6.0, -4.0, 0.30)
        dance = hand_dance({0: None, 39: None, 40: point, 79: point, 80: None}, at=hand_aim_rest)
        below = camera(cam(0, (-70.0, 0.0, 0.0)), cam(LAST, (-70.0, 0.0, 0.0)))
        self.assertLess(fk.camera_position(fk.camera_at(fk.camera_keys(below), 40, [0, LAST]))[1], 0.0)   # below her
        result = run_hands(dance, cam_motion=below)
        self.assertEqual(result.contacts, [])
        self.assertEqual(result.report["hands"]["list"], [])
        self.assertEqual(len(run_hands(dance).report["hands"]["list"]), 1)

    def test_an_eye_contact_wins_over_her_hand(self):
        point = ahead(-8.0, -2.0, 0.30)
        result = run_hands(hand_dance({0: None, 39: None, 40: point, 79: point, 80: None}), cam_motion=IN_FRONT)
        self.assertEqual(result.contacts, [(0, LAST)])
        self.assertEqual(result.report["hands"]["list"], [])

    def test_a_lead_wins_over_her_hand(self):
        # the head turns 60 degrees fast from frame 61 while the hand is held before her face (40 to 100): the eyes
        # still lead the turn, and they leave the hand for it
        point = ahead(-6.0, -2.0, 0.30)
        result = run_hands(hand_dance({0: None, 39: None, 40: point, 100: point, 101: None},
                                      head={0: 0.0, 60: 0.0, 66: 60.0}))
        leads = [s for s in result.saccades if s["reason"] == "lead"]
        self.assertEqual(len(leads), 1, result.saccades)
        for h in result.report["hands"]["list"]:
            self.assertLess(h["last"], leads[0]["frame"], h)

    def test_a_model_without_hands_looks_at_none(self):
        result = run_gaze(cam_motion=BEHIND)
        self.assertEqual(result.report["hands"], {"count": 0, "frames": 0, "share": 0.0, "list": []})
        self.assertEqual(result.hand_points, {})

    def test_the_eyes_are_where_the_hand_stops_before_it_does(self):
        # the hand swings in from her side at 170 deg/s and stops before her face: the eyes jump to where it will stop
        # and are there before it (a person's eyes lead the hand she moves to its target), then hold on it with no
        # second jump
        stop = ahead(-6.0, -4.0, 0.30)
        points = {0: None, 29: None, 30: ahead(-40.0, -4.0, 0.30), 36: stop, 76: stop, 77: None}
        result = run_hands(hand_dance(points, at=hand_aim_rest))
        hands = result.report["hands"]["list"]
        self.assertEqual(len(hands), 1, hands)
        into = [s for s in result.saccades if s["reason"] == "hand"]
        self.assertEqual(len(into), 1, result.saccades)
        landed = into[0]["frame"] + into[0]["frames"] - 1
        self.assertLess(landed, 36)                                         # before the hand stops
        sight, look = result.sights[landed], result.looks[landed]
        self.assertLess(degrees_between(world_gaze(sight, look), tuple(p - e for p, e in zip(stop, sight.eye))), 1.0)
        for i in range(landed, 76):
            self.assertLess(self.hand_on(result, i) if i >= 36 else 0.0, 0.5, i)

    def test_the_report_names_the_point_the_eyes_aim_at_on_each_frame_of_a_look(self):
        # tools/eye_optics.py brings the eyes together on the looks of this report, at the distance of the point they
        # aim at (stage 6: it found its own looks where a hand lay within 12 degrees of the gaze, 96 % of its vergence
        # where she looked at no hand, review gaze-v8 6.7): until the hand stops, where it will stop (the eyes are
        # there before it); then the tip of its longest finger, where the gaze is
        stop = ahead(-6.0, -4.0, 0.30)
        points = {0: None, 29: None, 30: ahead(-40.0, -4.0, 0.30), 36: stop, 76: stop, 77: None}
        result = run_hands(hand_dance(points, at=hand_aim_rest))
        look = result.report["hands"]["list"][0]
        aim = look["aim"]
        self.assertEqual(len(aim), look["last"] - look["first"] + 1)
        self.assertLess(look["first"], 36)                                   # the look starts as the hand swings in
        for k, p in enumerate(aim):
            self.assertLess(math.dist(p, stop), 1e-3, look["first"] + k)
        tips = result.hand_aims["右"]
        for i in range(look["first"] + 1, look["last"] + 1):
            sight, seen = result.sights[i], result.looks[i]
            point = aim[i - look["first"]]
            if i >= 37:
                self.assertLess(math.dist(point, tips[min(look["last"], i + 1)]), 1e-3, i)     # the tip, one frame on
            if seen.state == "hand":
                toward = tuple(p - e for p, e in zip(point, sight.eye))
                self.assertLess(degrees_between(world_gaze(sight, seen), toward), 0.5, i)
        self.assertEqual(json.loads(json.dumps(result.report["hands"]))["list"][0]["aim"], aim)   # plain numbers

    def test_a_hand_that_moves_on_faster_than_the_eyes_follow_gets_a_catch_up_saccade(self):
        # held, then 16 degrees across in 3 frames (160 deg/s, over the 100 the gaze follows a hand) and held again:
        # the eyes fall behind and one saccade catches them up, not right after the first (CATCH_UP_AFTER frames)
        a, b = ahead(-14.0, -4.0, 0.30), ahead(2.0, -4.0, 0.30)
        result = run_hands(hand_dance({0: None, 29: None, 30: a, 60: a, 63: b, 100: b, 101: None}, at=hand_aim_rest))
        hands = result.report["hands"]["list"]
        self.assertEqual(len(hands), 1, hands)
        into = [s for s in result.saccades if s["reason"] == "hand"]
        self.assertEqual(len(into), 2, result.saccades)
        first_landed = into[0]["frame"] + into[0]["frames"] - 1
        self.assertGreaterEqual(into[1]["frame"] - first_landed, 3)        # not right after a landing (0.1 s)
        self.assertTrue(60 <= into[1]["frame"] <= 66, into)
        for i in range(70, 99):
            self.assertLess(self.hand_on(result, i), 0.5, i)


def load_named(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HandVergenceTest(unittest.TestCase):
    """tools/eye_optics.py brings the eyes together on the looks at a hand this tool plans, read from its --report: on
    the hand she looks at, 14 degrees off her face's way, it does; on a hand held 6 degrees off her gaze for 0.27 s,
    which she passes by (no look), the eyes stay parallel (stage 5 brought them together on any hand within 12 degrees
    of the gaze, whether she looked at it or not: 96 % of the vergence of the MV v8 fell outside her looks, review
    gaze-v8 6.7)"""

    @classmethod
    def setUpClass(cls):
        from tests.test_pmx_eyes import EYE_Z, toy_bytes
        cls.pmx_eyes, cls.eye_optics = load_named("pmx_eyes"), load_named("eye_optics")
        wrist, tip = (-4.65, 12.41, -0.24), (-6.05, 11.42, -0.26)
        hand_tip = tuple(w + 0.5 * (t - w) / math.dist(wrist, tip) for w, t in zip(wrist, tip))     # 手先, 4 cm on
        data, _ = toy_bytes(extra_bones=[("右手首", -1, wrist), ("右中指３先", -1, tip), ("右手先", -1, hand_tip)],
                            iris_z=-0.96)
        doc = pmx_edit.loads(data)
        cls.pmx_eyes.build(doc, share=0.55)
        cls.model_bytes = pmx_edit.dumps(doc)
        cls.model = pmx.loads(cls.model_bytes)
        cls.eye = (0.0, 17.214, EYE_Z)

        def key(frame):
            return motion_edit.camera_key_from_ui({"pos": cls.eye, "distance": 2500.0 / 80.0, "rot": (0.0, 60.0, 0.0),
                                                   "fov": 30, "perspective": True}, frame=frame)
        cls.cams = vmd.Motion.for_camera(cameras=[key(0), key(120)])
        cls.quiet = cls.eye_optics.merge_params(cls.eye_optics.PARAMS, {"pupil": {"unrest": {"amplitude": 0.0}}})

    def dance(self, yaw, pitch, first, last):
        """the toy's right hand held 30 cm before her eyes at (yaw, pitch) from frame `first` to `last`, by her side
        before and after"""
        rest = eye_gaze.hand_points(self.model, head_turn({0: 0.0}, last=1))["右"][0]      # the look point at rest
        point = tuple(e + d * 0.30 / UNIT_M for e, d in zip(self.eye, direction(yaw, pitch)))
        move = tuple(p - r for p, r in zip(point, rest))
        keys = [vmd.BoneKey("右目", 0, fk.ZERO, fk.IDENTITY), vmd.BoneKey("左目", 0, fk.ZERO, fk.IDENTITY),
                vmd.BoneKey("頭", 0, fk.ZERO, fk.IDENTITY), vmd.BoneKey("頭", 120, fk.ZERO, fk.IDENTITY)]
        for frame, m in ((0, fk.ZERO), (first - 1, fk.ZERO), (first, move), (last, move), (last + 1, fk.ZERO),
                         (120, fk.ZERO)):
            keys += [vmd.BoneKey(name, frame, m, fk.IDENTITY) for name in ("右手首", "右中指３先", "右手先")]
        return vmd.Motion(model_name="toy", bones=keys)

    def test_eye_optics_converges_on_the_hand_she_looks_at(self):
        dance = self.dance(-14.0, -2.0, 40, 79)
        result = eye_gaze.gaze(self.model, dance, self.cams, life=False)
        self.assertEqual([(h["first"], h["last"]) for h in result.report["hands"]["list"]], [(41, 79)])   # 40: it arrives
        optics = self.eye_optics.optics(self.model_bytes, dance, result.motion, self.cams, self.quiet,
                                        looks=self.eye_optics.gaze_looks(result.report))
        verg, labels = optics.trace["vergence"], optics.trace["label"]
        aim = result.report["hands"]["list"][0]["aim"][20]
        want = math.degrees(math.atan(61.5 / 2.0 / (math.dist(aim, self.eye) * UNIT_M * 1000.0)))   # the eyes meet at its tip
        self.assertEqual(set(labels[41:80]), {"hand"})
        self.assertGreater(min(verg[52:80]), 0.95 * want, verg[40:80])
        self.assertLess(max(verg[:38]), 0.05)

    def test_eye_optics_leaves_the_eyes_parallel_on_a_hand_she_passes_by(self):
        dance = self.dance(-6.0, -2.0, 40, 47)
        result = eye_gaze.gaze(self.model, dance, self.cams, life=False)
        self.assertEqual(result.report["hands"]["list"], [])
        hand = eye_gaze.hand_points(self.model, dance)["右"]
        off = [degrees_between(world_gaze(s, look), tuple(p - e for p, e in zip(hand[s.frame], s.eye)))
               for s, look in zip(result.sights, result.looks)]
        self.assertLess(max(off[40:48]), 12.0)                    # within the cone that brought stage 5's eyes together
        optics = self.eye_optics.optics(self.model_bytes, dance, result.motion, self.cams, self.quiet,
                                        looks=self.eye_optics.gaze_looks(result.report))
        self.assertEqual(max(optics.trace["vergence"]), 0.0)

    def test_the_command_reads_the_report_the_gaze_wrote(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        face = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("まばたき", 0, 0.0)])
        paths = {}
        for name, data in (("model.pmx", self.model_bytes), ("dance.vmd", vmd.dumps(self.dance(-14.0, -2.0, 40, 79))),
                           ("camera.vmd", vmd.dumps(self.cams)), ("face.vmd", vmd.dumps(face))):
            paths[name] = os.path.join(folder, name)
            with open(paths[name], "wb") as f:
                f.write(data)
        gaze_path, report, trace = (os.path.join(folder, n) for n in ("gaze.vmd", "gaze.json", "trace.json"))
        code, result = run([paths["dance.vmd"], paths["camera.vmd"], paths["model.pmx"], gaze_path, "--report", report])
        self.assertEqual(code, 0, result)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = self.eye_optics.main([paths["model.pmx"], paths["dance.vmd"], gaze_path, paths["camera.vmd"],
                                         os.path.join(folder, "optics.vmd"), "--face", paths["face.vmd"],
                                         "--gaze-report", report, "--trace", trace])
        self.assertEqual(code, 0, printed.getvalue())
        with open(trace, encoding="utf-8") as f:
            verg = json.load(f)["vergence"]
        self.assertGreater(min(verg[52:80]), 5.0)
        self.assertLess(max(verg[:38] + verg[110:]), 0.05)          # parallel before the look and a second after it


class SaccadeTest(unittest.TestCase):
    def test_no_saccade_is_a_single_frame(self):
        # stage 5: a one-frame jump reads as a teleport at 30 fps.  The coordinator's lengths (2026-10-13, after the
        # research of stage 5: the main sequence D = 21 + 2.2 A ms puts 5 to 15 degrees in 1 to 2 frames, and eyes
        # 2.5 to 4 times slower look sluggish, Pejsa 2013): under 15 degrees 2 frames, 15 to 35 degrees 3, beyond 4
        for amplitude, frames in ((0.6, 2), (5.0, 2), (14.9, 2), (15.0, 3), (29.0, 3), (35.0, 3), (35.1, 4), (40.0, 4)):
            self.assertEqual(eye_gaze.saccade_frames(amplitude), frames, amplitude)
        for seed in range(3):
            dance, cams = restless(seed)
            for s in run_gaze(dance=dance, cam_motion=cams, seed=seed).saccades:
                self.assertEqual(s["frames"], eye_gaze.saccade_frames(s["amplitude"]), s)
                self.assertGreaterEqual(s["frames"], 2, s)

    def test_outside_saccades_the_eyes_turn_at_most_max_step_a_frame(self):
        # the head of `restless` snaps 15 to 50 degrees in 7 frames: counter-rotating all of it would move the eyes
        # up to 10 degrees a frame with no saccade.  Outside saccades they turn at most 8 degrees a frame (the rest
        # is carried by the head)
        runs = [(restless(seed), seed) for seed in range(3)]
        # and a head that snaps 60 degrees in one frame (a flick, too short for a fast turn's lead)
        runs.append(((head_turn({0: 0.0, 40: 0.0, 41: 60.0, LAST: 60.0}), BEHIND), 0))
        for (dance, cams), seed in runs:
            result = run_gaze(dance=dance, cam_motion=cams, seed=seed)
            moving = set()
            for s in result.saccades:
                moving.update(range(s["frame"], s["frame"] + s["frames"]))
            for i in range(1, len(result.looks)):
                if i not in moving:
                    a, b = result.looks[i - 1].base, result.looks[i].base
                    self.assertLessEqual(math.hypot(b[0] - a[0], b[1] - a[1]), 8.0 + 1e-6, (seed, i))
        # on the flick the eyes turn the 8 degrees they may and the head carries the rest: no saccade then
        flick = run_gaze(dance=head_turn({0: 0.0, 40: 0.0, 41: 60.0, LAST: 60.0}), cam_motion=BEHIND)
        self.assertEqual([s for s in flick.saccades if 38 <= s["frame"] <= 45], [])
        self.assertAlmostEqual(flick.looks[40].base[0] - flick.looks[41].base[0], 8.0, places=6)

    def test_a_saccade_lands_without_a_jump_while_the_head_turns(self):
        # the goal of a recentre, glance or look-away is where the face's way is on each frame of it (in the head):
        # a goal held still in the world swings across the eyes' range while the head turns 20 degrees a frame (a
        # spin: 600 deg/s for 2 s), and the saccade ends with a jump.  Each step stays within the minimum-jerk share
        # (58 % of the amplitude in the middle of 3 frames) and what the face's way moves that frame (up to 11
        # degrees a frame where the head of `restless` snaps 50 degrees in 7 frames)
        spin = head_turn(dict([(0, 0.0), (30, 0.0)] + [(30 + 5 * k, 100.0 * k) for k in range(1, 13)]), last=LAST)
        runs = [restless(seed) + (seed,) for seed in range(3)] + [(spin, BEHIND, 0)]
        for dance, cams, seed in runs:
            result = run_gaze(dance=dance, cam_motion=cams, seed=seed)
            face = eye_gaze.face_ways(result.sights, eye_gaze.fast_turns(result.sights, FORWARD)[0],
                                      eye_gaze.angles_of(FORWARD))
            for s in result.saccades:
                if s["reason"] in ("recentre", "glance", "away", "look_away"):
                    frames = range(s["frame"], min(len(result.looks), s["frame"] + s["frames"]))   # the song may end first
                    for k in frames:
                        a, b = result.looks[k - 1].base, result.looks[k].base
                        step = math.hypot(b[0] - a[0], b[1] - a[1])
                        moved = math.hypot(face[k][0] - face[k - 1][0], face[k][1] - face[k - 1][1])
                        self.assertLessEqual(step, 0.59 * s["amplitude"] + moved + 0.5, (seed, s, k))
                    self.assertLess(max(abs(result.looks[k].base[0]) for k in frames), eye_gaze.EDGE * LIMITS.yaw, (seed, s))

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
        # recentres and glances wait MIN_FIXATION frames or more after a landing; quick phases and saccades off the
        # wall QUICK_AFTER or more (stage 6)
        waits = {"recentre": eye_gaze.MIN_FIXATION, "glance": eye_gaze.MIN_FIXATION, "quick": 4, "wall": 4}
        for seed in range(3):
            dance, cams = restless(seed)
            result = run_gaze(dance=dance, cam_motion=cams, seed=seed)
            for before, after in zip(result.saccades, result.saccades[1:]):
                if after["reason"] in waits:
                    landed = before["frame"] + before["frames"] - 1
                    self.assertGreaterEqual(after["frame"] - landed, waits[after["reason"]], (before, after))

    def test_the_shortest_fixation_can_be_chosen(self):
        # stage 5: 9 to 12 frames by default (the stage-1 tool had 6, and 57 % of its fixations stopped there)
        counts = {10: 0, 16: 0}
        for seed in range(2):
            dance, cams = restless(seed)
            ten = run_gaze(dance=dance, cam_motion=cams, seed=seed)
            longer = run_gaze(dance=dance, cam_motion=cams, seed=seed, min_fixation=16)
            self.assertEqual(longer.report["min_fixation"], 16)
            self.assertTrue(9 <= ten.report["min_fixation"] <= 12, ten.report["min_fixation"])
            gaps = []
            for before, after in zip(longer.saccades, longer.saccades[1:]):
                if after["reason"] in ("recentre", "glance"):
                    gaps.append(after["frame"] - (before["frame"] + before["frames"] - 1))
            self.assertGreaterEqual(min(gaps), 16)
            self.assertLessEqual(len(longer.saccades), len(ten.saccades))
            counts[10] += len(ten.saccades)
            counts[16] += len(longer.saccades)
        self.assertLess(counts[16], counts[10])
        with self.assertRaises(ValueError):
            run_gaze(min_fixation=0)

    def test_fixations_do_not_pile_up_at_the_shortest(self):
        # each fixation's earliest recentre or glance is drawn from MIN_FIXATION .. MIN_FIXATION + FIXATION_SPREAD
        # frames (the seed): with one fixed shortest length, fixations whose gap had opened earlier all ended on it
        # (review eye, finding 2: 57 % of them at 6 frames; with 10 frames and no spread 24 % stopped at 10)
        spread = eye_gaze.FIXATION_SPREAD
        # the head turns on and on at 24 deg/s (no fast turn), so the gaze is always behind where the face goes and
        # each fixation ends at the earliest it may (faster, the head presses the eyes to their wall before the
        # shortest fixation is over, and a saccade off the wall comes first: stage 6)
        keys = {f: 0.8 * f for f in range(0, 301, 10)}
        dance = head_turn(keys, last=300)
        lengths = []
        for seed in range(2):
            result = eye_gaze.gaze(MODEL, dance, camera(cam(0, (0.0, 180.0, 0.0)), cam(300, (0.0, 180.0, 0.0))),
                                   life=False, seed=seed)
            for before, after in zip(result.saccades, result.saccades[1:]):
                if after["reason"] == "recentre":
                    lengths.append(after["frame"] - (before["frame"] + before["frames"] - 1))
        self.assertGreater(len(lengths), 15)
        self.assertGreaterEqual(min(lengths), eye_gaze.MIN_FIXATION)
        early = [n for n in lengths if n <= eye_gaze.MIN_FIXATION + spread]
        self.assertGreater(len(early), 0.8 * len(lengths))
        self.assertGreaterEqual(len(set(early)), 4)
        self.assertLess(early.count(eye_gaze.MIN_FIXATION) / float(len(early)), 0.4)

    def test_a_nod_that_comes_back_within_sustain_frames_moves_nothing(self):
        # the head turns 14 degrees and back at 140 deg/s (no fast turn): the eyes turn against it, out to more
        # than GAP degrees from where the face points, but they are back within SUSTAIN frames, so no saccade
        nod = head_turn({0: 0.0, 40: 0.0, 43: 14.0, 45: 14.0, 48: 0.0})
        for seed in range(3):
            result = run_gaze(dance=nod, cam_motion=BEHIND, seed=seed)
            self.assertEqual([s for s in result.saccades if s["reason"] == "recentre"], [], seed)
            self.assertGreater(max(abs(look.base[0]) for look in result.looks), eye_gaze.GAP)

    def test_a_long_fixation_ends_with_a_glance(self):
        # a still head and nowhere to look: the eyes move on their own every GLANCE frames, a few degrees
        result = run_gaze(dance=head_turn({0: 0.0}, last=300), cam_motion=camera(cam(0, (0.0, 180.0, 0.0)),
                                                                                   cam(300, (0.0, 180.0, 0.0))))
        self.assertGreaterEqual(len(result.saccades), 300 // eye_gaze.GLANCE[1])
        self.assertEqual({s["reason"] for s in result.saccades}, {"glance"})
        for before, after in zip(result.saccades, result.saccades[1:]):
            landed = before["frame"] + before["frames"] - 1
            self.assertTrue(eye_gaze.GLANCE[0] <= after["frame"] - landed <= eye_gaze.GLANCE[1], (before, after))
        for s in result.saccades:
            self.assertLess(s["amplitude"], 2 * math.hypot(4.0, 3.0) + 1e-6)

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
        # the same up to half the limit and more, then bending smoothly (no kink) toward the limit without reaching
        # it: a camera at the limit is looked at with about 90 % of it, far beyond the eyes stop at the limit
        for value in (0.0, 5.0, -5.0, 9.0, -9.0):
            self.assertEqual(eye_gaze.soft(value, 18.0), value)
        self.assertTrue(0.85 * 18.0 < eye_gaze.soft(18.0, 18.0) < 0.95 * 18.0)
        self.assertAlmostEqual(eye_gaze.soft(-18.0, 18.0), -eye_gaze.soft(18.0, 18.0), places=12)
        values = [eye_gaze.soft(v / 10.0, 18.0) for v in range(0, 541)]                  # up to 3 times the limit
        self.assertTrue(all(b > a for a, b in zip(values, values[1:])))                  # rises all the way
        self.assertLess(max(values), 18.0)                                               # short of the limit
        self.assertGreater(values[-1], 0.999 * 18.0)
        self.assertEqual(eye_gaze.soft(150.0, 18.0), 18.0)
        self.assertEqual(eye_gaze.soft(-1e6, 18.0), -18.0)
        slopes = [(b - a) / 0.1 for a, b in zip(values, values[1:])]
        self.assertLess(max(abs(b - a) for a, b in zip(slopes, slopes[1:])), 0.02)      # C1: the slope never jumps
        self.assertAlmostEqual(slopes[0], 1.0, places=9)

    def test_saccades_head_for_the_face_s_way_off_the_camera(self):
        free = eye_gaze.free_zone(LIMITS)
        far = (0.0, 180.0)
        self.assertEqual(eye_gaze.face_target((3.0, -1.0), (0.0, 0.0), far, free), (3.0, -1.0))
        self.assertEqual(eye_gaze.face_target((3.0, -1.0), (2.0, 1.0), far, free), (5.0, 0.0))        # a glance's offset
        self.assertEqual(eye_gaze.face_target((30.0, -20.0), (0.0, 0.0), far, free), (free.yaw, -free.down))
        # a camera 3 degrees off the face's way: the target is AVOID degrees off it, on the far side
        t = eye_gaze.face_target((0.0, 0.0), (0.0, 0.0), (3.0, 0.0), free)
        self.assertAlmostEqual(t[0], 3.0 - eye_gaze.AVOID, places=9)
        self.assertAlmostEqual(t[1], 0.0, places=9)

    def test_a_fixation_is_pressed_against_the_wall_short_of_the_edge(self):
        # stage 5: beyond the free zone a fixation's angle approaches its wall along tanh (slope 1 where it starts),
        # so a gaze held through a sway stops short of the 90 % lines the analysis counts as the edge
        free = eye_gaze.free_zone(LIMITS)
        self.assertEqual(eye_gaze.pressed((5.0, -3.0), LIMITS), (5.0, -3.0))
        last = free.yaw
        for far in (13.0, 20.0, 40.0, 400.0):
            yaw, _ = eye_gaze.pressed((far, 0.0), LIMITS)
            self.assertTrue(last < yaw < eye_gaze.EDGE * LIMITS.yaw, (far, yaw))
            last = yaw
            self.assertAlmostEqual(eye_gaze.pressed((-far, 0.0), LIMITS)[0], -yaw, places=12)
        self.assertLess(eye_gaze.pressed((0.0, 30.0), LIMITS)[1], eye_gaze.EDGE * LIMITS.up)
        self.assertGreater(eye_gaze.pressed((0.0, -30.0), LIMITS)[1], -eye_gaze.EDGE * LIMITS.down)
        h = 1e-6
        slope = (eye_gaze.pressed((free.yaw + h, 0.0), LIMITS)[0] - eye_gaze.pressed((free.yaw, 0.0), LIMITS)[0]) / h
        self.assertAlmostEqual(slope, 1.0, places=4)

    def test_up_and_down_soften_against_their_own_limits(self):
        limits = eye_gaze.Limits(18.0, 6.0, 10.0)
        self.assertEqual(eye_gaze.soften((5.0, 3.0), limits), (5.0, 3.0))
        self.assertAlmostEqual(eye_gaze.soften((0.0, 6.0), limits)[1], eye_gaze.soft(6.0, 6.0), places=12)
        self.assertAlmostEqual(eye_gaze.soften((0.0, -5.0), limits)[1], -5.0, places=12)          # inside half of 10
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

    def lead_of(self, head, eye, margins=(15, 0)):
        return eye_gaze.lead_measure(head, [h + e for h, e in zip(head, eye)], margins=margins)

    def test_the_a20_definition_is_held_by_numbers(self):
        # review eye, finding 6: the real-song test measures with lead_measure itself, so a change of its definition
        # (s17b.py of a20) would pass unseen.  Each number of the definition is held here.
        fast = [0.0] * 60 + [10.0 * k for k in range(1, 7)] + [60.0] * 60          # 300 deg/s on frames 60..65
        steps = lambda first, size: [0.0] * first + [size] * (len(fast) - first)
        # the window: the 6 frames before the onset (60), eye-in-head at 60 minus at 54
        self.assertEqual(self.lead_of(fast, steps(55, 8.0))["led"], 1)
        self.assertEqual(self.lead_of(fast, steps(54, 8.0))["led"], 0)        # moved before the window
        # more than 3 degrees
        self.assertEqual(self.lead_of(fast, steps(57, 3.0))["led"], 0)
        self.assertEqual(self.lead_of(fast, steps(57, 3.2))["led"], 1)
        # above 200 deg/s, for 3 frames or more
        for per_frame, turns in ((198.0 / 30.0, 0), (204.0 / 30.0, 1)):
            head = [0.0] * 60 + [per_frame * k for k in range(1, 7)] + [6 * per_frame] * 60
            self.assertEqual(self.lead_of(head, [0.0] * len(head))["turns"], turns, per_frame)
        two = [0.0] * 60 + [10.0, 20.0] + [20.0] * 60
        self.assertEqual(self.lead_of(two, [0.0] * len(two))["turns"], 0)
        three = [0.0] * 60 + [10.0, 20.0, 30.0] + [30.0] * 60
        self.assertEqual(self.lead_of(three, [0.0] * len(three))["turns"], 1)
        # the onset: the first of the 15 frames before at 30 % of the peak.  A slow start at 75 deg/s (25 % of 300)
        # is not the onset, so an eye that moves on frame 57 leads
        ramp = [0.0] * 50 + [2.5 * k for k in range(1, 11)] + [25.0 + 10.0 * k for k in range(1, 7)] + [85.0] * 60
        self.assertEqual(self.lead_of(ramp, steps(57, 8.0)), {"turns": 1, "led": 1, "share": 1.0})
        # the margins of the song (a20 left out turns in the first 330 and the last 172 frames)
        self.assertEqual(eye_gaze.LEAD_MARGINS, (330, 172))
        self.assertEqual(self.lead_of(fast, steps(57, 8.0), margins=eye_gaze.LEAD_MARGINS)["turns"], 0)

    def test_the_smoothness_measures(self):
        # per-frame turns of the eye in the head (max and 99th percentile, all and outside the listed saccades) and
        # the median fixation (landing to the next saccade)
        angles = [(0.0, 0.0)] * 10 + [(5.0, 0.0), (10.0, 0.0)] + [(10.0, 0.0)] * 30 + [(6.0, 0.0), (10.0, 0.0)] + \
                 [(10.0, 0.0)] * 20
        saccades = [{"frame": 10, "frames": 2}, {"frame": 52, "frames": 2}]
        m = eye_gaze.smooth_measures(angles, saccades)
        self.assertAlmostEqual(m["eye_steps"]["max"], 5.0, places=6)
        self.assertAlmostEqual(m["eye_steps"]["outside_saccades_max"], 4.0, places=6)     # 42 -> 43 is not listed
        self.assertAlmostEqual(m["fixation_median_s"], (52 - 11) / 30.0, places=3)
        # the reversals are the eyes' own jumps going back (review gaze-smooth 2.4): a saccade of more than 3 degrees
        # followed, within 10 frames of its landing, by one of more than 3 the opposite way.  The eye going 4 degrees
        # out and back on 41 -> 42 -> 43 outside the saccades (a nod countered) is none
        self.assertEqual(m["reversals_per_second"], 0.0)

        def jumps(size, wait, second=-1.0):
            eye = [(0.0, 0.0)] * 10 + [(size / 2.0, 0.0), (size, 0.0)] + [(size, 0.0)] * wait
            back = size + second * size
            eye += [((size + back) / 2.0, 0.0), (back, 0.0)] + [(back, 0.0)] * 30
            return eye_gaze.smooth_measures(eye, [{"frame": 10, "frames": 2}, {"frame": 12 + wait, "frames": 2}])

        m = jumps(6.0, 9)                                       # back 10 frames after the landing (frame 11 -> 21)
        self.assertAlmostEqual(m["reversals_per_second"], 1 / (53 / 30.0), places=4)
        self.assertEqual(jumps(6.0, 10)["reversals_per_second"], 0.0)                 # 11 frames: a new fixation
        self.assertEqual(jumps(3.0, 4)["reversals_per_second"], 0.0)                  # 3 degrees: not more than 3
        self.assertGreater(jumps(3.2, 4)["reversals_per_second"], 0.0)
        self.assertEqual(jumps(6.0, 4, second=1.0)["reversals_per_second"], 0.0)      # on the same way

    def test_the_world_gaze_measures_are_held_by_numbers(self):
        # review gaze-smooth 1.3 to 1.6, on the eye angles without the drift.  The head turns 2 degrees a frame (it
        # would carry a resting eye's gaze at 60 deg/s) for 30 frames, then stands still for 30; the eye counters a
        # share k of the turn, then glides on its own
        def run(k, glide, axis=0, saccades=(), contacts=()):
            heads, angles = [], []
            for f in range(61):
                h = 2.0 * min(f, 30)
                heads.append(eye_gaze.eye_rotation(h, 0.0) if axis == 0 else eye_gaze.eye_rotation(0.0, h))
                e = -k * h + glide * max(0, f - 30)
                angles.append((e, 0.0) if axis == 0 else (0.0, e))
            return eye_gaze.world_measures(heads, angles, list(saccades), list(contacts))

        m = run(1.0, 0.0)
        self.assertEqual((m["steady_steps"], m["still_steps"]), (30, 30))
        self.assertAlmostEqual(m["gain_yaw"], 1.0, places=3)
        self.assertIsNone(m["gain_pitch"])                                   # the head never nods
        self.assertEqual((m["steady_share"], m["flow_share"]), (1.0, 0.0))
        m = run(0.9, 0.09)                       # the gaze moves 6 deg/s with the head, 0.09 degrees a frame alone
        self.assertAlmostEqual(m["gain_yaw"], 0.9, places=3)
        self.assertEqual((m["steady_share"], m["flow_share"]), (1.0, 0.0))
        m = run(0.8, 0.11)                       # 12 deg/s and 0.11 degrees a frame
        self.assertAlmostEqual(m["gain_yaw"], 0.8, places=3)
        self.assertEqual((m["steady_share"], m["flow_share"]), (0.0, 1.0))
        m = run(0.5, 0.0, axis=1)                # a nod countered by half
        self.assertAlmostEqual(m["gain_pitch"], 0.5, places=3)
        self.assertIsNone(m["gain_yaw"])
        # the steps touching a listed saccade's frames are left out, and the still ones touching a contact
        m = run(1.0, 0.0, saccades=[{"frame": 10, "frames": 2}], contacts=[(40, 49)])
        self.assertEqual((m["steady_steps"], m["still_steps"]), (27, 19))
        # the head's speed bands: 15.3 deg/s is in both, 14 only the still one, 117 only the steady one, 121.5 neither;
        # the steady steps split as the remeasure of stage 6 splits its W2, the head at 15 to 60 and 60 to 120 deg/s
        for per_frame, steady, still, slow, fast in ((0.51, 30, 60, 30, 0), (14.0 / 30.0, 0, 60, 0, 0),
                                                     (4.05, 0, 30, 0, 0), (3.9, 30, 30, 0, 30), (1.9, 30, 30, 30, 0),
                                                     (2.1, 30, 30, 0, 30)):
            heads = [eye_gaze.eye_rotation(per_frame * min(f, 30), 0.0) for f in range(61)]
            angles = [(-per_frame * min(f, 30), 0.0) for f in range(61)]
            m = eye_gaze.world_measures(heads, angles, [])
            self.assertEqual((m["steady_steps"], m["still_steps"]), (steady, still), per_frame)
            bands = m["steady_by_head"]
            self.assertEqual((bands["15_60"]["steps"], bands["60_120"]["steps"]), (slow, fast), per_frame)
        # the head at 90 deg/s for 30 frames: the eye counters all of it on the first 15, then 80 % (the gaze moves
        # 18 deg/s): half the steps of the 60 to 120 band are steady
        heads = [eye_gaze.eye_rotation(3.0 * min(f, 30), 0.0) for f in range(61)]
        angles = [(-3.0 * min(f, 15) - 2.4 * max(0, min(f, 30) - 15), 0.0) for f in range(61)]
        bands = eye_gaze.world_measures(heads, angles, [])["steady_by_head"]
        self.assertEqual(bands["60_120"], {"steps": 30, "share": 0.5})
        self.assertEqual(bands["15_60"], {"steps": 0, "share": 0.0})

    def test_the_frames_at_the_wall(self):
        # the eyes at WALL_SEEN of a limit or beyond, sideways and up or down; a fixation pressed against its wall
        # is there
        w = eye_gaze.WALL_SEEN
        angles = [(w * 18.0 + 0.01, 0.0), (w * 18.0 - 0.01, 0.0), (-w * 18.0 - 0.01, 0.0), (0.0, w * 6.0 + 0.01),
                  (0.0, -w * 10.0 - 0.01), (0.0, -w * 10.0 + 0.01), (0.0, 0.0), (0.0, 0.0)]
        self.assertEqual(eye_gaze.wall_measures(angles, LIMITS), {"yaw": 2 / 8.0, "pitch": 2 / 8.0})
        self.assertLess(w, eye_gaze.WALL)
        pressed = eye_gaze.pressed((400.0, -400.0), LIMITS)
        self.assertEqual(eye_gaze.wall_measures([pressed], LIMITS), {"yaw": 1.0, "pitch": 1.0})

    def test_large_gaze_changes_made_by_saccades_or_carried_by_the_head(self):
        # the gaze turns 30 degrees in the world over 10 frames: once inside a listed saccade, once without one
        gaze = [direction(0.0, 0.0)] * 20 + [direction(3.0 * k, 0.0) for k in range(1, 11)] + [direction(30.0, 0.0)] * 30
        listed = [{"frame": 20, "frames": 10}]
        self.assertEqual(eye_gaze.carried_measure(gaze, listed)["head_carried"], 0)
        self.assertEqual(eye_gaze.carried_measure(gaze, [])["head_carried"], 1)

    def test_large_gaze_changes_split_by_the_eyes_own_motion(self):
        # review eye, finding 1: the list's split counts a whole step as the saccade's when a saccade touches either
        # end.  a13's v_sac splits without the list: the part of the gaze's step the eye in the head makes the same
        # way.  The same 30-degree turn: the eye moves in a still head (made by the eye), or the eye rests in a
        # turning head (carried), whatever the list says
        yaws = [0.0] * 20 + [3.0 * k for k in range(1, 11)] + [30.0] * 30
        gaze = [direction(y, 0.0) for y in yaws]
        listed = [{"frame": 20, "frames": 10}]
        still = [fk.IDENTITY] * len(yaws)
        turning = [eye_gaze.eye_rotation(y, 0.0) for y in yaws]
        by_eye = eye_gaze.carried_measure(gaze, listed, heads=still)["by_eye_motion"]
        self.assertEqual((by_eye["events"], by_eye["head_carried"]), (1, 0))
        carried = eye_gaze.carried_measure(gaze, listed, heads=turning)
        self.assertEqual(carried["head_carried"], 0)                          # the list's split says made
        self.assertEqual(carried["by_eye_motion"]["head_carried"], 1)          # the eye did not move
        self.assertNotIn("by_eye_motion", eye_gaze.carried_measure(gaze, listed))


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
                                                   "lead", "head_carried", "saccades_per_second", "eye_steps",
                                                   "fixation_median_s", "reversals_per_second", "world_gaze",
                                                   "wall_share"})
        self.assertEqual(set(report["measures"]["world_gaze"]), {"gain_yaw", "gain_pitch", "steady_steps",
                                                                 "steady_share", "steady_by_head", "still_steps",
                                                                 "flow_share"})
        self.assertEqual(set(report["measures"]["world_gaze"]["steady_by_head"]), {"15_60", "60_120"})
        self.assertEqual(report["zones"]["wall"], {k: round(v, 4) for k, v in report["zones"]["wall"].items()})
        self.assertEqual(set(report["measures"]["eye_steps"]), {"max", "p99", "outside_saccades_max",
                                                                "outside_saccades_p99"})


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
                            "--cues", self.cues, "--chorus", "2.0", "--min-fixation", "9"])
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
        self.assertEqual(result["min_fixation"], 9)
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

    def test_the_report_names_the_motion_it_describes_by_its_md5(self):
        # tools/eye_optics.py reads the looks at a hand from this report and refuses a report of another gaze
        out, report = os.path.join(self.folder, "eyes.vmd"), os.path.join(self.folder, "r.json")
        code, result = run([self.dance, self.camera, self.model, out, "--report", report])
        self.assertEqual(code, 0, result)
        with open(out, "rb") as f:
            written = hashlib.md5(f.read()).hexdigest()
        with open(self.dance, "rb") as f:
            read = hashlib.md5(f.read()).hexdigest()
        with open(report, encoding="ascii") as f:
            rep = json.load(f)
        self.assertEqual((rep["out_md5"], rep["in_md5"]), (written, read))

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
                     [self.dance, self.camera, self.model, out, "--min-fixation", "0"],
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
    """a file of the real song under _spike/ of this tree, of a tree up to 3 folders above it (a worktree), or of
    MMD_CLI_DATA (a copy of the tree kept away from the data, such as a mutation's; review gaze-smooth 3.2)"""
    folders, folder = [], ROOT
    for _ in range(4):
        folders.append(folder)
        folder = os.path.dirname(folder)
    if os.environ.get("MMD_CLI_DATA"):
        folders.append(os.environ["MMD_CLI_DATA"])
    for folder in folders:
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
    return None


def rin_path():
    """Sour's Rin: MMD_CLI_RIN when set, else the model folder of MMD under the user's Desktop (review gaze-smooth
    13: a fixed path of one machine skipped the real tests on another without a word)"""
    rel = os.path.join("MikuMikuDance_v932x64", "UserFile", "Model", "Sour式鏡音リンVer.2.01", "White.pmx")
    for path in (os.environ.get("MMD_CLI_RIN"), os.path.join(os.path.expanduser("~"), "Desktop", rel)):
        if path and os.path.isfile(path):
            return path
    return None


MV_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_final_dn6_twist.vmd")
HANDHELD = real_file("_spike", "out", "hibikase", "variants", "camera_D_handheld.vmd")
MV_CUES = real_file("_spike", "out", "hibikase", "mv", "production", "cues_mv.json")
OLD_DANCE = real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_smooth_twist.vmd")
OLD_CAMERA = real_file("_spike", "out", "hibikase", "variants", "camera_D_generated.vmd")
RIN = rin_path()
CHORUS = ["60.02", "128.59", "198.87"]       # the heads of the three choruses (a15: beats 140, 300, 464 at 140 BPM)


def measured_from_files(dance_path, camera_path, out_path, report):
    """the target numbers measured again from the files: the dance with the written 両目 track in place of its own
    through the forward kinematics, not from the plan.  The world gaze's steadiness is measured on the angles with
    the drift and the microsaccades of the seed (0) taken off again, as the plan does (review gaze-smooth 1.6)"""
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
    out["head_carried"] = eye_gaze.carried_measure(gazes, report["saccades"]["list"], heads=heads)
    out.update(eye_gaze.smooth_measures(angles, report["saccades"]["list"]))
    life = eye_gaze.drift_track(len(angles), random.Random(0))
    still = [(y - d[0], p - d[1]) for (y, p), d in zip(angles, life)]
    contacts = [(c["first"], c["last"]) for c in report["contacts"]["list"]]
    out["world_gaze"] = eye_gaze.world_measures(heads, still, report["saccades"]["list"], contacts)
    out["wall_share"] = eye_gaze.wall_measures(angles, LIMITS)
    return out


@unittest.skipUnless(MV_DANCE and HANDHELD and MV_CUES and RIN, "the MV's dance, camera, cues or Rin is not here "
                     "(MMD_CLI_DATA: a folder holding _spike/; MMD_CLI_RIN: White.pmx)")
class RealSongTest(unittest.TestCase):
    """the MV's dance (dance_final_dn6_twist) and camera (camera_D_handheld): the target numbers of the stage-1 fix
    and of stage 5, measured from the written file.  Before stage 1 (v2): eyes led 4 % of the fast turns, at the edge
    59 % of the frames and up to 4 s on end, 15 degrees or more off the middle 42 %, eye contacts of 0.30 s (median).
    Before stage 5 (the stage-1 tool): 2.98 saccades a second, 487 of them one frame long, fixations of 0.20 s
    (median, 57 % at the shortest), eye steps up to 31 degrees a frame outside saccades, 0.76 reversals a second (of
    saccades going back; 1.73 of per-frame steps).  The first form of stage 5 (2642bbe) had those down to 1.05, none,
    0.70 s, 8 and 0.07, but let the gaze flow with the head between saccades (review gaze-smooth): with the head at
    15 to 120 deg/s the gaze stayed under 10 deg/s on 15 % of the steps (the stage-1 tool 88 %), and with the head
    under 20 deg/s it moved more than 0.1 degree a frame on 73 % (1 %).  The fix keeps the gaze in the world (66 %
    and 13 %) with 1.43 saccades a second and fixations of 0.47 s.  The head carries a07's large gaze changes 62 %
    by the list's split and 82 % by v_sac (2.7 % and 37 % before stage 5); a target of stage 1, not of stage 5.
    Stage 6 keeps the reflex on in the fast turns, with quick phases: 32 % and 70 %, the gaze put with the head at
    60 to 120 deg/s on 63 % of the steps, 1.80 saccades a second (0.33 of them quick phases), fixations of 0.40 s,
    0.17 reversals a second, 2 looks at a hand"""

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
        # the targets kept from stage 1
        self.assertGreaterEqual(m["lead"]["share"], 0.5, m["lead"])
        self.assertLessEqual(m["edge_share"], 0.15)
        self.assertLess(m["edge_longest_s"], 1.0)
        self.assertLess(m["eccentric_15_share"], 0.10)
        self.assertGreaterEqual(m["contact"]["episode_median_s"], 1.5, m["contact"])
        # stage 5 (the coordinator's acceptance of the review fix): fewer saccades, none of one frame, long fixations
        # (median), at most 8 degrees a frame outside saccades, few reversals (0.05 a second, the stage-1 tool 0.76)
        saccades = report["saccades"]["list"]
        rate = len(saccades) / (7743 / 30.0)
        # stage 6: the quick phases of the sustained fast turns come on top of the 1.6 (the coordinator: the
        # saccades that are added must be those); the stage-1 tool had 2.98 a second
        others = len([s for s in saccades if s["reason"] != "quick"]) / (7743 / 30.0)
        self.assertTrue(0.5 <= others <= 1.6, others)
        self.assertLessEqual(rate, 2.0)
        self.assertEqual([s for s in saccades if s["frames"] < 2], [])
        # the median fixation: 0.4 s or more in stage 5; 0.33 s or more from stage 6 (the coordinator, 2026-10-14: a
        # lead no longer jumps back against its turn, which took the median to 0.367 s; a person's free viewing of a
        # scene fixates 330 ms on average, Rayner 1998 table 1, and the stage-1 tool's 0.20 s is what is kept off)
        self.assertGreaterEqual(m["fixation_median_s"], 0.33, m)
        self.assertLessEqual(m["eye_steps"]["outside_saccades_max"], 8.0 + 0.005, m["eye_steps"])
        # inside saccades: a 35-degree saccade in 3 frames moves 58 % of it in its middle frame
        self.assertLess(m["eye_steps"]["max"], 0.59 * 35.0 + 1.0, m["eye_steps"])
        self.assertLess(m["reversals_per_second"], 0.2, m)
        # the gaze stays put in the world between saccades (review gaze-smooth 3.4): with the head at 15 to 120
        # deg/s it moves under 10 deg/s on 60 % of the steps or more, with the head under 20 deg/s more than 0.1
        # degree a frame on 20 % or fewer; the eyes counter most of the head's turn sideways and up and down
        world = m["world_gaze"]
        self.assertGreater(min(world["steady_steps"], world["still_steps"]), 1000, world)
        self.assertGreaterEqual(world["steady_share"], 0.6, world)
        self.assertLessEqual(world["flow_share"], 0.2, world)
        self.assertGreaterEqual(world["gain_yaw"], 0.75, world)
        self.assertGreaterEqual(world["gain_pitch"], 0.5, world)
        # stage 6 (the remeasure of the MV v7: the reflex held off through the sustained fast turns let the head carry
        # the gaze): with the head at 60 to 120 deg/s the gaze stays put on 60 % of the steps or more (v7: 54 %), and
        # the head carries few of a07's large gaze changes (v7: 57 %; stage 1's target was a few %)
        self.assertGreaterEqual(world["steady_by_head"]["60_120"]["share"], 0.6, world)
        self.assertLessEqual(m["head_carried"]["share"], 0.35, m["head_carried"])
        # stage 6: she looks at her hands somewhere in the song, each look 0.3 s or more (review gaze-v8, 6: a change of
        # the looks' choice passed every test)
        looks = report["hands"]["list"]
        self.assertGreaterEqual(len(looks), 1, report["hands"])
        self.assertTrue(all(h["last"] - h["first"] + 1 >= 9 for h in looks), looks)
        # the plan's own measures say the same as the files
        self.assertAlmostEqual(report["measures"]["edge_share"], m["edge_share"], places=2)
        self.assertAlmostEqual(report["measures"]["contact"]["episode_median_s"], m["contact"]["episode_median_s"], places=1)
        self.assertEqual(report["measures"]["lead"]["turns"], m["lead"]["turns"])
        self.assertAlmostEqual(report["measures"]["eye_steps"]["outside_saccades_max"],
                               m["eye_steps"]["outside_saccades_max"], places=0)
        self.assertAlmostEqual(report["measures"]["head_carried"]["by_eye_motion"]["share"],
                               m["head_carried"]["by_eye_motion"]["share"], places=1)
        for name in ("steady_share", "flow_share", "gain_yaw", "gain_pitch"):
            self.assertAlmostEqual(report["measures"]["world_gaze"][name], world[name], places=2)
        self.assertEqual(report["measures"]["wall_share"], m["wall_share"])


@unittest.skipUnless(OLD_DANCE and OLD_CAMERA and RIN, "the older dance, its camera or Rin is not here "
                     "(MMD_CLI_DATA: a folder holding _spike/; MMD_CLI_RIN: White.pmx)")
class OlderSongTest(unittest.TestCase):
    """an earlier dance of the same song with the camera before the handheld shake: no cues, so no anchors (only the
    long contacts); the limits hold, the eyes still lead and stay off the edge, and the gaze stays put in the world
    between saccades (with the head at 15 to 120 deg/s the gaze under 10 deg/s on 66 % of the steps, with the head
    under 20 deg/s moving more than 0.1 degree a frame on 13 %)"""

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
        self.assertEqual([s for s in report["saccades"]["list"] if s["frames"] < 2], [])
        self.assertLessEqual(m["eye_steps"]["outside_saccades_max"], 8.0 + 0.005, m["eye_steps"])
        others = [s for s in report["saccades"]["list"] if s["reason"] != "quick"]
        self.assertLessEqual(len(others) / (7743 / 30.0), 1.6)
        self.assertLessEqual(len(report["saccades"]["list"]) / (7743 / 30.0), 2.0)
        for s in [c for c in report["contacts"]["list"]]:
            self.assertGreaterEqual(s["last"] - s["first"] + 1, eye_gaze.CONTACT_MIN)
        self.assertGreaterEqual(m["world_gaze"]["steady_share"], 0.6, m["world_gaze"])
        self.assertLessEqual(m["world_gaze"]["flow_share"], 0.2, m["world_gaze"])
        self.assertGreaterEqual(m["world_gaze"]["steady_by_head"]["60_120"]["share"], 0.6, m["world_gaze"])
        self.assertLessEqual(m["head_carried"]["share"], 0.35, m["head_carried"])


if __name__ == "__main__":
    unittest.main()
