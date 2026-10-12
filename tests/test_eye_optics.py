"""tools/eye_optics.py: the catchlights, the pupils and the vergence of the eyes, as one VMD after the dance, the face
and the gaze."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest

from mmd_cli import fk, motion_edit
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx_eyes import EYE_Z, PUPIL_Z, toy_bytes, turn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pmx_eyes = load_tool("pmx_eyes")
eye_optics = load_tool("eye_optics")

EYE = (0.0, 17.214, EYE_Z)
FAR = (-6.0, 12.0, 0.0)                 # where the toy's hand rests: by her side
HAND_REST = (-0.05, 17.214, EYE_Z - 3.75)
QUIET = {"pupil": {"unrest": {"amplitude": 0.0}}}
FRONT_LIGHT = {"light": {"direction": [0.0, 0.0, 1.0]}, "pupil": {"unrest": {"amplitude": 0.0}}}


def toy_model():
    data, _ = toy_bytes(extra_bones=[("右人指３先", -1, HAND_REST)], iris_z=-0.96)
    doc = pmx_edit.loads(data)
    pmx_eyes.build(doc, share=0.55)
    return pmx_edit.dumps(doc)


MODEL_BYTES = toy_model()
MODEL = pmx.loads(MODEL_BYTES)


def dance(last=90, head=None, hand=None, roll=None):
    """a dance of the toy: the head turned by {frame: (yaw, pitch)} (or rolled by {frame: degrees}), the hand's
    offset from its rest {frame: (x, y, z)} (its rest is 30 cm in front of the eyes; by default it stays by her side)"""
    keys = [vmd.BoneKey("右目", 0, fk.ZERO, fk.IDENTITY), vmd.BoneKey("左目", 0, fk.ZERO, fk.IDENTITY)]
    if roll:
        for frame, degrees in sorted(roll.items()):
            h = math.radians(degrees) / 2.0
            keys.append(vmd.BoneKey("頭", frame, fk.ZERO, fk.stored((0.0, 0.0, math.sin(h), math.cos(h)))))
    else:
        for frame, (yaw, pitch) in sorted((head or {0: (0.0, 0.0), last: (0.0, 0.0)}).items()):
            keys.append(vmd.BoneKey("頭", frame, fk.ZERO, fk.stored(turn(yaw, pitch))))
    away = tuple(f - r for f, r in zip(FAR, HAND_REST))
    for frame, offset in sorted((hand or {0: away, last: away}).items()):
        keys.append(vmd.BoneKey("右人指３先", frame, offset, fk.IDENTITY))
    return vmd.Motion(model_name="toy", bones=keys)


def gaze(last=90, angles=None):
    """a 両目 track: {frame: (yaw, pitch)} in the head (eye_gaze's convention), every frame keyed"""
    angles = angles or {}
    keys, current = [], (0.0, 0.0)
    for frame in range(last + 1):
        current = angles.get(frame, current)
        keys.append(vmd.BoneKey("両目", frame, fk.ZERO, fk.stored(turn(*current))))
    return vmd.Motion(model_name="toy", bones=keys)


def camera(distance_m=1.0, yaw=0.0, last=90):
    def key(frame):
        return motion_edit.camera_key_from_ui({"pos": EYE, "distance": distance_m * 1000.0 / 80.0, "rot": (0.0, yaw, 0.0),
                                               "fov": 30, "perspective": True}, frame=frame)
    return vmd.Motion.for_camera(cameras=[key(0), key(last)])


def run(d=None, g=None, c=None, params=None, **kw):
    return eye_optics.optics(MODEL_BYTES, d or dance(), g or gaze(), c or camera(),
                             eye_optics.merge_params(eye_optics.PARAMS, params or QUIET), **kw)


def keys_of(motion, name):
    return sorted((k for k in motion.bones if k.name == name), key=lambda k: k.frame)


def morph_at(motion, name, frame):
    """a morph's weight at a frame as MMD shows it: straight between keys, held before the first and after the last"""
    keys = sorted((k for k in motion.morphs if k.name == name), key=lambda k: k.frame)
    before = [k for k in keys if k.frame <= frame]
    after = [k for k in keys if k.frame > frame]
    if not before:
        return keys[0].weight if keys else 0.0
    a = before[-1]
    if a.frame == frame or not after:
        return a.weight
    b = after[0]
    return a.weight + (b.weight - a.weight) * (frame - a.frame) / float(b.frame - a.frame)


def yaw_of(q):
    """the yaw (toward +X) a rotation (as applied) gives the rest gaze"""
    v = fk.rotate(q, (0.0, 0.0, -1.0))
    return math.degrees(math.atan2(v[0], -v[2]))


def bone(name):
    return next(b for b in MODEL.bones if b.name == name)


def light_on_screen(motion_list, frame, light_name, eye_name, side):
    """the light's centre minus the pupil's centre, seen from the front (X right, Y up), in model units"""
    motion = eye_optics.merge(*motion_list)
    pose = fk.Pose(MODEL, motion, [light_name, eye_name])
    world = pose.at(frame)
    b = bone(light_name)
    quad_rest = tuple(p + t for p, t in zip(b.position, b.tail["offset"]))
    lp, lr = world[light_name]
    q = tuple(p + o for p, o in zip(lp, fk.rotate(lr, tuple(a - c for a, c in zip(quad_rest, b.position)))))
    e = bone(eye_name)
    pupil_rest = (side * 0.507, 17.143, PUPIL_Z)
    ep, er = world[eye_name]
    c = tuple(p + o for p, o in zip(ep, fk.rotate(er, tuple(a - p0 for a, p0 in zip(pupil_rest, e.position)))))
    return q[0] - c[0], q[1] - c[1]


class VergenceGeometryTest(unittest.TestCase):
    def test_angle_per_eye_is_that_of_the_coordinators_probe(self):
        for metres, want in ((3.0, 0.589), (0.5, 3.531), (0.3, 5.871), (0.15, 11.622)):
            self.assertAlmostEqual(eye_optics.vergence_degrees(metres, 61.7), want, 3)

    def test_each_eye_turns_inward_onto_the_point(self):
        half = 61.7 / 2.0 / 80.0
        right, left = eye_optics.vergence_turns((0.0, 0.0, -1.0), 3.75, half)
        self.assertAlmostEqual(yaw_of(right), 5.871, 2)              # the right eye (-X) turns toward +X
        self.assertAlmostEqual(yaw_of(left), -5.871, 2)
        stored = fk.stored(right)                                    # as the coordinator's vergence_probe.vmd keys it
        self.assertAlmostEqual(stored[1], -0.05121, 4)
        self.assertAlmostEqual(stored[3], 0.99869, 4)

    def test_off_axis_point_is_met_by_both_eyes(self):
        half = 0.4
        g = (math.sin(math.radians(20.0)), 0.0, -math.cos(math.radians(20.0)))
        right, left = eye_optics.vergence_turns(g, 5.0, half)
        target = tuple(5.0 * c for c in g)
        for q, x in ((right, -half), (left, half)):
            seen = fk.rotate(q, g)
            want = tuple(t - e for t, e in zip(target, (x, 0.0, 0.0)))
            n = math.sqrt(sum(c * c for c in want))
            self.assertAlmostEqual(sum(a * b / n for a, b in zip(seen, want)), 1.0, 9)


class VergenceTimeTest(unittest.TestCase):
    P = eye_optics.PARAMS["vergence"]

    def track(self, demands):
        return eye_optics.vergence_track(demands, 30.0, self.P["latency"], self.P["duration"], self.P["max_speed"])

    def test_a_small_step_waits_then_takes_its_time(self):
        out = self.track([0.0] * 30 + [2.0] * 90)
        start = 30 + self.P["latency"] * 30.0
        self.assertTrue(all(v == 0.0 for v in out[:int(math.floor(start)) + 1]))
        five = next(i for i, v in enumerate(out) if v >= 0.1)
        ninety_five = next(i for i, v in enumerate(out) if v >= 1.9)
        self.assertAlmostEqual((ninety_five - five) / 30.0, self.P["duration"], delta=1.5 / 30.0)
        self.assertAlmostEqual(out[-1], 2.0, 9)
        self.assertTrue(all(b >= a for a, b in zip(out, out[1:])))

    def test_a_big_step_keeps_under_the_top_speed(self):
        out = self.track([0.0] * 10 + [6.0] * 120 + [0.0] * 120)
        speed = max(abs(b - a) for a, b in zip(out, out[1:])) * 30.0
        self.assertLessEqual(speed, self.P["max_speed"] + 1e-6)
        self.assertAlmostEqual(max(out), 6.0, 6)
        self.assertAlmostEqual(out[-1], 0.0, 9)

    def test_a_change_during_a_move_carries_on_from_where_it_is(self):
        out = self.track([0.0] * 10 + [4.0] * 12 + [0.0] * 100)
        steps = [abs(b - a) for a, b in zip(out, out[1:])]
        self.assertLess(max(steps), self.P["max_speed"] / 30.0 + 1e-6)
        self.assertAlmostEqual(out[-1], 0.0, 9)


class TargetTest(unittest.TestCase):
    P = eye_optics.PARAMS["vergence"]

    def rows(self, n, camera=(30.0, 2.0), hands=()):
        return [{"camera": camera, "hands": list(hands)} for _ in range(n)]

    def test_camera_hand_and_free(self):
        rows = self.rows(10, camera=(2.0, 2.5))                           # looking at the camera, 2.5 m off
        rows += self.rows(15, hands=[(3.0, 0.35)])                        # a hand 3 degrees off the gaze, 35 cm off
        rows += self.rows(4, hands=[(3.0, 0.35)])
        rows += self.rows(4)                                               # (a gap)
        rows += self.rows(self.P["hand_frames"] - 1, hands=[(3.0, 0.35)])  # too short
        rows += self.rows(10, hands=[(3.0, 0.10)])                        # too near to look at
        rows += self.rows(10, hands=[(25.0, 0.35)])                       # too far off the gaze
        metres, labels = eye_optics.fixation_targets(rows, self.P)
        self.assertEqual(labels[:10], ["camera"] * 10)
        self.assertEqual(labels[10:29], ["hand"] * 19)
        self.assertEqual(metres[10:29], [0.35] * 19)
        self.assertEqual(set(labels[29:]), {"free"})

    def test_camera_wins_over_a_hand_further_off_its_line(self):
        rows = self.rows(20, camera=(1.0, 2.5), hands=[(8.0, 0.4)])
        _, labels = eye_optics.fixation_targets(rows, self.P)
        self.assertEqual(set(labels), {"camera"})

    def test_only_a_hand_brings_the_eyes_together(self):
        labels = ["camera", "camera", "hand", "hand", "free"]
        metres = [1.0, 1.0, 0.3, 0.3, 3.0]
        demand = eye_optics.vergence_demand(labels, metres, self.P)
        want = self.P["gain"] * eye_optics.vergence_degrees(0.3, self.P["ipd_mm"])
        self.assertEqual(demand, [0.0, 0.0, want, want, 0.0])


class LightGeometryTest(unittest.TestCase):
    def test_light_source_term_of_the_research_table(self):
        v = (0.0, 0.0, -1.0)
        for alpha, want in ((30.0, 0.34), (45.0, 0.50), (90.0, 0.92)):
            a = math.radians(alpha)
            light = (math.sin(a), 0.0, -math.cos(a))
            h = eye_optics._unit(tuple(x + y for x, y in zip(light, v)))
            x, y = eye_optics.light_offset(h, v, v, 1.31, 0.79)
            self.assertAlmostEqual(math.hypot(x, y), want, delta=0.01)
            self.assertGreater(x, 0.0)                               # toward the light's side
            self.assertAlmostEqual(y, 0.0, 9)

    def test_gaze_term_lags_opposite_to_the_gaze(self):
        v = (0.0, 0.0, -1.0)
        t = math.radians(10.0)
        g = (math.sin(t), 0.0, -math.cos(t))                         # the eye 10 degrees toward +X (screen right)
        x, y = eye_optics.light_offset(v, g, v, 1.31, 0.79)
        self.assertAlmostEqual(x, -0.79 * math.sin(t), 9)
        self.assertAlmostEqual(y, 0.0, 9)

    def test_screen_axes_of_a_camera_in_front(self):
        x, y = eye_optics.screen_basis((0.0, 0.0, -1.0))
        self.assertEqual(tuple(round(c, 9) for c in x), (1.0, 0.0, 0.0))    # the viewer's right is her left, +X
        self.assertEqual(tuple(round(c, 9) for c in y), (0.0, 1.0, 0.0))

    @staticmethod
    def miss(pivot, depth, radial, turn, target, view):
        """how far, across the line of sight, the turned point lies from the target"""
        p = eye_optics._add(pivot, eye_optics._scale(fk.rotate(turn, radial), depth))
        d = eye_optics._sub(p, target)
        return math.sqrt(sum(c * c for c in eye_optics._sub(d, eye_optics._scale(view, eye_optics._dot(d, view)))))

    def test_turn_brings_the_light_onto_the_line_of_sight(self):
        pivot, depth, radial = (0.1, 0.2, 0.3), 0.4, (0.0, 0.0, -1.0)
        view = eye_optics._unit((0.2, 0.1, -1.0))
        target = (0.13, 0.25, -0.12)
        start = self.miss(pivot, depth, radial, fk.IDENTITY, target, view)
        turn = eye_optics.light_turn(pivot, depth, radial, target, view, damping=0.0)
        self.assertLess(self.miss(pivot, depth, radial, turn, target, view), 1e-6 * max(1.0, start))
        damped = eye_optics.light_turn(pivot, depth, radial, target, view, damping=0.15)
        self.assertLess(self.miss(pivot, depth, radial, damped, target, view), 0.1 * start)

    def test_turn_is_none_on_the_line_and_bounded_side_on(self):
        pivot, depth, radial = (0.0, 0.0, 0.0), 0.4, (0.0, 0.0, -1.0)
        view = (0.0, 0.0, -1.0)
        on = eye_optics.light_turn(pivot, depth, radial, (0.0, 0.0, -0.9), view, damping=0.15)
        self.assertLess(eye_optics._angle(on), 1e-9)
        side = (1.0, 0.0, 0.0)                                       # the camera sees the light side on
        far = eye_optics.light_turn(pivot, depth, radial, (0.0, 0.3, -0.4), side, damping=0.15)
        self.assertLess(eye_optics._angle(far), 60.0)

    def test_keep_on_iris_passes_up_to_the_knee_and_never_beyond_the_reach(self):
        f = eye_optics.keep_on_iris
        self.assertEqual(f((0.3, 0.4), 0.5, 0.9), (0.3, 0.4))                  # inside: unchanged
        self.assertAlmostEqual(math.hypot(*f((0.53, 0.0), 0.5, 0.9)), 0.53, 9)   # up to 60 % of the reach too
        before = 0.0
        for r in (0.5, 0.6, 0.7, 0.9, 1.2, 2.0, 10.0):
            out = f((r * 0.6, -r * 0.8), 0.5, 0.9)
            n = math.hypot(*out)
            self.assertLessEqual(n, 0.9)
            self.assertGreaterEqual(n, before)                                 # it keeps its order
            self.assertAlmostEqual(out[0] / out[1], -0.75, 9)                  # along the same direction
            before = n
        self.assertAlmostEqual(math.hypot(*f((0.55, 0.0), 0.5, 0.9)), 0.55, 4)   # smooth past the knee (0.54)
        self.assertAlmostEqual(math.hypot(*f((1.0, 0.0), 0.95, 0.9)), 0.95, 9)   # drawn beyond the reach: held there

    def test_disc_coordinates_along_the_camera_ray(self):
        centre, x, y, n = (0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)
        cam = (0.0, 0.0, -11.0)
        u, v = eye_optics.disc_coordinates(cam, (0.08, -0.11, -1.0), centre, x, y, n, 0.16, 0.22)
        self.assertAlmostEqual(u, 0.5, 9)
        self.assertAlmostEqual(v, -0.5, 9)
        u, v = eye_optics.disc_coordinates(cam, (0.08, 0.0, -2.0), centre, x, y, n, 0.16, 0.22)
        self.assertAlmostEqual(u, 0.08 * 10.0 / 9.0 / 0.16, 9)                 # in front of the disc: projected back
        self.assertIsNone(eye_optics.disc_coordinates((5.0, 0.0, -1.0), (0.0, 0.1, -1.0), centre, x, y, n, 0.16, 0.22))
        # seen nearly edge on (85 degrees off its normal) or from behind, the iris is not seen: no place on it
        edge = (10.0 * math.sin(math.radians(85.0)), 0.0, -1.0 - 10.0 * math.cos(math.radians(85.0)))
        self.assertIsNone(eye_optics.disc_coordinates(edge, (0.0, 0.0, -1.01), centre, x, y, n, 0.16, 0.22))
        self.assertIsNone(eye_optics.disc_coordinates((0.0, 0.0, 9.0), (0.0, 0.0, -1.01), centre, x, y, n, 0.16, 0.22))
        slant = (10.0 * math.sin(math.radians(60.0)), 0.0, -1.0 - 10.0 * math.cos(math.radians(60.0)))
        self.assertIsNotNone(eye_optics.disc_coordinates(slant, (0.0, 0.0, -1.01), centre, x, y, n, 0.16, 0.22))

    def test_hide_is_a_function_of_the_frame(self):
        out = eye_optics.hide_track([30.0, 47.0, 48.0, 49.0, 60.0, 30.0], 46.0, 50.0)
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[4], 1.0)
        self.assertEqual(out[5], 0.0)                                # no filter: it comes back at once
        self.assertAlmostEqual(out[2], 0.5)
        self.assertTrue(0.0 < out[1] < out[2] < out[3] < 1.0)


class PupilTest(unittest.TestCase):
    P = eye_optics.PARAMS["pupil"]

    def quiet(self, **change):
        p = eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.0}})
        return eye_optics.merge_params(p, change)

    def test_reflex_waits_narrows_fast_and_comes_back_slowly(self):
        n = 600
        r = eye_optics.reflex_track(n, [30.0], 30.0, self.P["reflex"])
        rx = self.P["reflex"]
        onset = 30 + rx["latency"] * 30.0
        self.assertTrue(all(v == 0.0 for v in r[:int(math.floor(onset)) + 1]))
        low = min(range(n), key=lambda i: r[i])
        self.assertAlmostEqual(r[low], -rx["peak"], 6)
        self.assertTrue(0.3 <= (low - onset) / 30.0 <= 1.0, (low - onset) / 30.0)   # most narrow within about 1 s
        back = next(i for i in range(low, n) if r[i] >= 0.1 * r[low])               # 90 % back
        self.assertTrue(4.5 <= (back - low) / 30.0 <= 7.0, (back - low) / 30.0)     # 5 to 6 s (Pilley & Thompson)
        narrowing = max(abs(b - a) for a, b in zip(r[:low], r[1:low + 1]))
        widening = max(abs(b - a) for a, b in zip(r[low:], r[low + 1:]))
        self.assertGreater(narrowing, 2.5 * widening)                                # widening about 3 times slower

    def test_flare_in_the_track(self):
        track = eye_optics.pupil_track(330, [30.0], None, [], [0.0] * 330, self.quiet(), seed=0)
        self.assertAlmostEqual(min(track["total"]), -self.P["reflex"]["peak"], 6)

    def test_music_moves_the_pupil_by_a_percent_or_two(self):
        n = 450
        loud = [0.0] * 60 + [1.0] * 150 + [0.0] * 240
        track = eye_optics.pupil_track(n, [], loud, [], [0.0] * n, self.quiet(), seed=0)
        a = track["arousal"]
        self.assertLessEqual(max(a) - min(a), 0.02 + 1e-9)
        self.assertGreater(max(a) - min(a), 0.005)
        rise = next(i for i in range(60, n) if a[i] - a[59] >= 0.63 * (a[209] - a[59])) - 60
        self.assertTrue(20 <= rise <= 45, rise)
        fall = next(i for i in range(210, n) if a[209] - a[i] >= 0.63 * (a[209] - a[59])) - 210
        self.assertGreater(fall, rise)

    def test_chorus_dilation_peaks_after_about_a_second(self):
        n = 200
        track = eye_optics.pupil_track(n, [], None, [30.0], [0.0] * n, self.quiet(), seed=0)
        c = track["chorus"]
        top = max(range(n), key=lambda i: c[i])
        self.assertAlmostEqual((top - 30) / 30.0, self.P["chorus"]["peak"], delta=0.05)
        self.assertAlmostEqual(c[top], self.P["chorus"]["amplitude"], 3)
        self.assertLessEqual(self.P["chorus"]["amplitude"], 0.02)

    def test_unrest_is_small_slow_and_seeded(self):
        n = 900
        p = eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.01}})
        a = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=3)["total"]
        b = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=3)["total"]
        c = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=4)["total"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        rms = math.sqrt(sum(v * v for v in a) / n)
        self.assertTrue(0.005 <= rms <= 0.015, rms)
        self.assertLessEqual(self.P["unrest"]["high_hz"], 2.0)       # nothing faster than 2 Hz (Gingras 2015)
        bound = 0.01 * math.sqrt(2.0 / self.P["unrest"]["waves"]) * self.P["unrest"]["waves"] * 2 * math.pi * 2.0 / 30.0
        self.assertLess(max(abs(y - x) for x, y in zip(a, a[1:])), bound)

    def test_near_point_narrows_a_little(self):
        n = 60
        near = [0.0] * 20 + [3.0] * 40
        total = eye_optics.pupil_track(n, [], None, [], near, self.quiet(), seed=0)["total"]
        self.assertEqual(total[0], 0.0)
        self.assertAlmostEqual(total[-1], -3.0 * self.P["near"]["per_dioptre"], 6)

    def test_weights(self):
        big, thin = eye_optics.pupil_weights([0.173, 0.0, -0.067], 1.73, -0.67)
        self.assertEqual([round(v, 6) for v in big], [0.1, 0.0, 0.0])
        self.assertEqual([round(v, 6) for v in thin], [0.0, 0.0, 0.1])

    def test_scales_from_the_model(self):
        doc = pmx_edit.loads(MODEL_BYTES)
        scales = eye_optics.pupil_scales(doc, "瞳大", "瞳細")
        self.assertAlmostEqual(scales["big"], 1.73, 3)
        self.assertAlmostEqual(scales["thin"], -0.67, 3)


class OpticsTest(unittest.TestCase):
    def test_the_written_tracks(self):
        result = run(c=camera(1.0))
        m = result.motion
        self.assertEqual({k.name for k in m.bones}, {"右目", "左目", "右HL２", "右HL", "左HL２", "左HL"})
        self.assertEqual({k.name for k in m.morphs}, {"瞳大", "瞳細", "HL消"})
        rep = result.report
        self.assertEqual(rep["vergence"]["labels"], {"camera": 91})
        self.assertAlmostEqual(rep["model"]["share"], 0.55, 6)
        for part in ("vergence", "light", "fade", "pupil"):
            self.assertIn(part, rep)
        self.assertIn("p99", rep["vergence"]["step"])
        self.assertIn("p99", rep["light"]["key_step"])
        self.assertIn("p99", rep["light"]["offset_step"])

    def test_a_near_camera_does_not_cross_the_eyes(self):
        result = run(c=camera(0.6))
        for k in keys_of(result.motion, "右目"):
            self.assertAlmostEqual(yaw_of(fk.applied(k.rotation)), 0.0, 6)

    def test_light_in_front_stays_where_it_was_drawn(self):
        result = run(c=camera(10.0), params=FRONT_LIGHT)
        motions = [dance(), gaze(), result.motion]
        before = light_on_screen([dance(), gaze()], 10, "左HL２", "左目", 1.0)    # without eye_optics: painted on
        after = light_on_screen(motions, 10, "左HL２", "左目", 1.0)
        self.assertAlmostEqual(after[0], before[0], delta=0.002)       # the camera is 0.2 degrees off the eye's axis
        self.assertAlmostEqual(after[1], before[1], delta=0.002)
        self.assertEqual(morph_at(result.motion, "HL消", 10), 0.0)

    def test_eye_turned_leaves_the_light_behind_by_the_research_lag(self):
        g = gaze(90, {0: (10.0, 0.0)})
        result = run(g=g, c=camera(10.0), params=FRONT_LIGHT)
        rest = light_on_screen([dance(), gaze(), run(c=camera(10.0), params=FRONT_LIGHT).motion], 10, "左HL２", "左目", 1.0)
        moved = light_on_screen([dance(), g, result.motion], 10, "左HL２", "左目", 1.0)
        iris_x = result.report["model"]["iris_radius"][0]
        want = -0.79 * iris_x * math.sin(math.radians(10.0))
        self.assertAlmostEqual(moved[0] - rest[0], want, delta=0.004)
        self.assertAlmostEqual(moved[1] - rest[1], 0.0, delta=0.004)

    def test_head_roll_does_not_turn_the_light_about_the_pupil(self):
        level = run(c=camera(10.0), params=FRONT_LIGHT)
        rolled_dance = dance(roll={0: 25.0, 90: 25.0})
        rolled = run(d=rolled_dance, c=camera(10.0), params=FRONT_LIGHT)
        a = light_on_screen([dance(), gaze(), level.motion], 10, "左HL２", "左目", 1.0)
        b = light_on_screen([rolled_dance, gaze(), rolled.motion], 10, "左HL２", "左目", 1.0)
        self.assertAlmostEqual(a[0], b[0], delta=0.003)
        self.assertAlmostEqual(a[1], b[1], delta=0.003)

    def test_light_follows_a_fast_head_turn_in_the_same_frame(self):
        head = {0: (0.0, 0.0), 30: (0.0, 0.0), 34: (30.0, 0.0), 90: (30.0, 0.0)}
        result = run(d=dance(90, head=head), c=camera(10.0), params=FRONT_LIGHT)
        rep = result.report["light"]
        self.assertGreater(rep["key_step"]["max"], 3.0)             # no rate limit, no smoothing
        rest = light_on_screen([dance(), gaze(), run(c=camera(10.0), params=FRONT_LIGHT).motion], 10, "左HL２", "左目", 1.0)
        for frame in (31, 32, 33, 60):
            seen = light_on_screen([dance(90, head=head), gaze(), result.motion], frame, "左HL２", "左目", 1.0)
            self.assertAlmostEqual(seen[1], rest[1], delta=0.01)

    def test_light_behind_the_eye_is_hidden(self):
        def at(alpha, g=None):
            a = math.radians(alpha)
            p = {"light": {"direction": [-math.sin(a), 0.0, math.cos(a)]}, "pupil": {"unrest": {"amplitude": 0.0}}}
            return morph_at(run(g=g, c=camera(10.0), params=p).motion, "HL消", 10)
        self.assertEqual(at(80.0), 0.0)
        self.assertEqual(at(105.0), 1.0)
        # the coordinator's rule is the light against the camera: an eye turned away keeps its light
        self.assertEqual(at(70.0, gaze(90, {0: (-25.0, 0.0)})), 0.0)

    def test_camera_behind_her_leaves_the_light_painted_on_the_iris(self):
        g = gaze(90, {0: (10.0, 0.0)})
        result = run(g=g, c=camera(10.0, yaw=180.0), params=FRONT_LIGHT)
        share = bone("左HL２").append["ratio"]
        want = fk.power(turn(10.0, 0.0), 1.0 - share)        # with the append: the whole turn of the eye
        for k in keys_of(result.motion, "左HL２"):
            got = fk.applied(k.rotation)
            self.assertLess(eye_optics._angle(fk.multiply(fk.conjugate(want), got)), 0.06)

    def test_at_rest_each_light_sits_on_its_drawn_place_of_the_iris(self):
        result = run(c=camera(10.0), params=FRONT_LIGHT)
        drawn = result.report["light"]["drawn"]
        self.assertEqual(result.trace["lights"], ["右HL２", "右HL", "左HL２", "左HL"])
        for k, name in enumerate(result.trace["lights"]):
            u, v = result.trace["disc"][10][k]
            self.assertAlmostEqual(u, drawn[name][0], delta=0.01, msg=name)
            self.assertAlmostEqual(v, drawn[name][1], delta=0.01, msg=name)
        # the toy's lights: centroids (+-0.45, 17.24) and (+-0.62, 17.04) on irises 0.16 by 0.22 about (+-0.507, 17.143)
        self.assertAlmostEqual(drawn["左HL２"][0], (0.45 - 0.507) / 0.16, 3)
        self.assertAlmostEqual(drawn["左HL"][1], (17.04 - 17.143) / 0.22, 3)

    def test_lights_stay_on_the_iris_seen_at_a_slant(self):
        head = {0: (30.0, 0.0), 90: (30.0, 0.0)}
        result = run(d=dance(90, head=head), c=camera(1.0))
        reach = eye_optics.PARAMS["light"]["reach"]
        radii = [math.hypot(*uv) for row in result.trace["disc"] for uv in row]
        self.assertLessEqual(max(radii), reach + 1e-3)
        self.assertGreater(max(radii), reach - 0.06)          # the slant pushes a light out to the iris' edge
        rep = result.report["light"]
        self.assertGreater(rep["edge_frames"], 0)
        self.assertLessEqual(rep["disc_r"]["max"], reach + 1e-3)
        self.assertGreater(rep["ahead"]["min"], 0.0)            # every light in front of its iris' rim
        self.assertEqual(rep["behind_frames"], 0)

    def test_a_small_cap_holds_the_light(self):
        g = gaze(90, {0: (15.0, 0.0)})
        p = {"light": {"direction": [0.0, 0.0, 1.0], "cap": 0.1}, "pupil": {"unrest": {"amplitude": 0.0}}}
        result = run(g=g, c=camera(10.0), params=p)                    # the lag alone is 0.79 sin 15 = 0.20
        # the cap holds the move as the camera sees it; on the toy's iris, turned 15 degrees with the eye, that is
        # 1 / cos 15 as much across the iris itself (the report measures the light on the iris)
        self.assertLessEqual(result.report["light"]["moved"]["max"], 0.1 / math.cos(math.radians(15.0)) + 1e-3)
        self.assertGreater(result.report["light"]["moved"]["max"], 0.09)

    def test_light_stays_on_its_iris_and_its_key_bounded(self):
        head = {0: (0.0, 0.0), 30: (0.0, 0.0), 40: (25.0, 10.0), 90: (25.0, 10.0)}
        g = gaze(90, {0: (-18.0, -10.0)})
        result = run(d=dance(90, head=head), g=g, c=camera(3.0, yaw=-15.0))
        self.assertEqual(result.report["light"]["camera_aside"]["frames_partly"], 0)
        drawn = result.report["light"]["drawn"]
        reach = eye_optics.PARAMS["light"]["reach"]
        for k, name in enumerate(result.trace["lights"]):
            limit = max(reach, math.hypot(*drawn[name]))
            self.assertLessEqual(max(math.hypot(*row[k]) for row in result.trace["disc"]), limit + 1e-3, name)
        near = run(d=dance(90, head=head), g=g, c=camera(3.0, yaw=-15.0),
                   params={"light": {"reach": 0.4}, "pupil": {"unrest": {"amplitude": 0.0}}})
        first = near.trace["lights"][0]
        limit = max(0.4, math.hypot(*drawn[first]))                   # drawn further out than 0.4: held there
        radii = [math.hypot(*row[0]) for row in near.trace["disc"]]
        # the key of this 19-degree turn is just past the knee of its soft cap (18 degrees): a hair short of its target
        self.assertLessEqual(max(radii), limit + 0.01)
        self.assertGreater(max(radii), limit - 0.01)                  # the scene does push it that far
        cap = eye_optics.PARAMS["light"]["key_cap"]
        for name in ("右HL２", "右HL", "左HL２", "左HL"):
            for k in keys_of(result.motion, name):
                self.assertLessEqual(eye_optics._angle(k.rotation), cap + 1e-3)

    def test_soft_cap(self):
        for size in (0.0, 0.3, 0.6, 0.9, 1.5, 40.0):
            out = eye_optics.soft_cap((size * 0.6, -size * 0.8), 1.0)
            self.assertLessEqual(math.hypot(*out), 1.0)
            if size <= 0.6:
                self.assertAlmostEqual(math.hypot(*out), size, 9)
        self.assertGreater(eye_optics.soft_cap((0.9, 0.0), 1.0)[0], eye_optics.soft_cap((0.8, 0.0), 1.0)[0])

    def test_hand_in_front_brings_the_eyes_together_slowly(self):
        away = tuple(f - r for f, r in zip(FAR, HAND_REST))
        hand = {0: away, 29: away, 30: (0.0, 0.0, 0.0), 89: (0.0, 0.0, 0.0), 90: away, 150: away}
        result = run(d=dance(150, hand=hand), g=gaze(150), c=camera(2.5, yaw=30.0, last=150))
        keys = keys_of(result.motion, "右目")
        frames = [k.frame for k in keys]

        def value(f):
            return yaw_of(fk.applied(fk.sample(keys, f, frames)[1]))
        p = eye_optics.PARAMS["vergence"]
        want = p["gain"] * eye_optics.vergence_degrees(0.3, p["ipd_mm"])
        self.assertAlmostEqual(value(30 + 7), 0.0, delta=0.05)      # 0.24 s before it starts (keys within 0.05 deg)
        self.assertAlmostEqual(value(89), want, delta=0.05)
        self.assertLessEqual(max(abs(value(f + 1) - value(f)) for f in range(150)), p["max_speed"] / 30.0 + 1e-3)
        self.assertEqual(result.report["vergence"]["labels"]["hand"], 60)

    def test_flare_reaches_the_pupil_morph(self):
        result = run(d=dance(150), g=gaze(150), c=camera(2.5, last=150), flares=[1.0])
        thin = max(morph_at(result.motion, "瞳細", f) for f in range(151))
        self.assertAlmostEqual(thin, eye_optics.PARAMS["pupil"]["reflex"]["peak"] / 0.67, 2)
        self.assertEqual(morph_at(result.motion, "瞳細", 36), 0.0)

    def test_light_gain_comes_from_the_research_cornea(self):
        rep = run().report
        self.assertAlmostEqual(rep["light"]["cornea"], 7.72 / 5.91, 6)
        self.assertAlmostEqual(rep["light"]["lag"], 4.67 / 5.91, 6)


class KeyTest(unittest.TestCase):
    """MMD refuses more than 20,000 registered points (a dialog on loading the first version's 8,205 morph keys over
    the face's 11,745): keys only where straight lines between them miss the values"""

    def test_morph_keys_follow_the_values_within_the_tolerance(self):
        values = [0.1 * math.sin(i / 20.0) + 0.0005 * math.sin(i * 1.7) for i in range(600)]
        keys = eye_optics._morph_keys("瞳大", list(range(600)), values, 0.001)
        self.assertLess(len(keys), 200)
        frames = [k.frame for k in keys]
        self.assertEqual(frames[0], 0)
        self.assertEqual(frames[-1], 599)
        for f in range(600):
            i = max(j for j, x in enumerate(frames) if x <= f)
            if frames[i] == f:
                v = keys[i].weight
            else:
                a, b = keys[i], keys[i + 1]
                v = a.weight + (b.weight - a.weight) * (f - a.frame) / (b.frame - a.frame)
            self.assertLessEqual(abs(v - values[f]), 0.001 + 1e-6)

    def test_bone_keys_follow_the_turns_within_the_tolerance(self):
        turns = [eye_optics.eye_rotation(10.0 * math.sin(i / 15.0), 3.0 * math.cos(i / 25.0)) for i in range(400)]
        turns[200] = eye_optics.eye_rotation(12.0, 0.0)               # a jump
        keys = eye_optics._bone_keys("右HL２", list(range(400)), turns, 0.05)
        self.assertLess(len(keys), 300)
        frames = [k.frame for k in keys]
        for f in range(400):
            got = fk.applied(fk.sample(keys, f, frames)[1])
            self.assertLessEqual(eye_optics._angle(fk.multiply(fk.conjugate(got), turns[f])), 0.05 + 1e-3)

    def test_written_motion_stays_far_under_the_limit(self):
        result = run(d=dance(300), g=gaze(300, {f: (5.0 * math.sin(f / 9.0), 0.0) for f in range(301)}),
                     c=camera(2.5, last=300), flares=[2.0])
        self.assertLess(len(result.motion.morphs), 300)


class OverlapTest(unittest.TestCase):
    def test_face_keying_a_pupil_morph_is_refused(self):
        face = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("瞳大", 0, 0.5)])
        with self.assertRaises(ValueError) as ctx:
            eye_optics.check_overlaps({"face": face}, {"右目", "左目"}, {"瞳大", "瞳細", "HL消"})
        self.assertIn("瞳大", str(ctx.exception))

    def test_dance_frame_zero_eye_keys_are_fine(self):
        eye_optics.check_overlaps({"dance": dance()}, {"右目", "左目"}, {"瞳大"})


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.paths = {}
        for name, data in (("model.pmx", MODEL_BYTES), ("dance.vmd", vmd.dumps(dance())), ("gaze.vmd", vmd.dumps(gaze())),
                           ("camera.vmd", vmd.dumps(camera()))):
            path = os.path.join(self.tmp, name)
            with open(path, "wb") as f:
                f.write(data)
            self.paths[name] = path
        look = os.path.join(self.tmp, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"flares": [1.0]}, f)
        self.paths["look"] = look

    def args(self, *extra):
        p = self.paths
        return [p["model.pmx"], p["dance.vmd"], p["gaze.vmd"], p["camera.vmd"], os.path.join(self.tmp, "out.vmd")] + list(extra)

    def test_writes_the_motion_and_the_report(self):
        report = os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = eye_optics.main(self.args("--look", self.paths["look"], "--report", report))
        self.assertEqual(code, 0, printed.getvalue())
        self.assertTrue(json.loads(printed.getvalue())["ok"])
        motion = vmd.load(os.path.join(self.tmp, "out.vmd"))
        self.assertTrue(motion.bones and motion.morphs)
        with open(report, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["pupil"]["flares_s"], [1.0])

    def test_trace_has_every_frame(self):
        trace = os.path.join(self.tmp, "t.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(eye_optics.main(self.args("--trace", trace)), 0)
        with open(trace, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["frames"]), 91)
        for key in ("label", "vergence", "light", "hide", "pupil", "camera_aside", "disc", "ahead"):
            self.assertEqual(len(data[key]), 91, key)
        self.assertEqual(len(data["disc"][0]), len(data["lights"]))

    def test_refuses_an_output_over_an_input(self):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = eye_optics.main(self.args()[:4] + [self.paths["gaze.vmd"]])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(printed.getvalue())["ok"])

    def test_params_file_overrides_the_defaults(self):
        params = os.path.join(self.tmp, "p.json")
        with open(params, "w", encoding="utf-8") as f:
            json.dump({"vergence": {"ipd_mm": 70.0}, "pupil": {"unrest": {"amplitude": 0.0}}}, f)
        report = os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(eye_optics.main(self.args("--params", params, "--report", report)), 0)
        with open(report, encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["params"]["vergence"]["ipd_mm"], 70.0)
        self.assertEqual(rep["params"]["vergence"]["gain"], eye_optics.PARAMS["vergence"]["gain"])

    def test_unknown_param_is_refused(self):
        params = os.path.join(self.tmp, "p.json")
        with open(params, "w", encoding="utf-8") as f:
            json.dump({"vergence": {"ipd": 70.0}}, f)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(eye_optics.main(self.args("--params", params)), 2)
        self.assertIn("ipd", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
