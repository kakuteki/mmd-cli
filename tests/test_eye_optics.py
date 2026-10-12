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
from tests.test_pmx_eyes import EYE_Z, toy_bytes, turn

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
QUIET = {"pupil": {"unrest": {"amplitude": 0.0}}}


def toy_model():
    data, _ = toy_bytes(extra_bones=[("右人指３先", -1, (-0.05, 17.214, EYE_Z - 3.75))], iris_z=-0.96)
    doc = pmx_edit.loads(data)
    pmx_eyes.build(doc, share=0.55)
    raw = pmx_edit.dumps(doc)
    return raw


MODEL_BYTES = toy_model()


def dance(last=90, head=None, hand=None):
    """a dance of the toy: the head turned by {frame: (yaw, pitch)}, the hand's offset from its rest {frame: (x, y, z)}
    (its rest is 30 cm in front of the eyes; the default keeps it by her side)"""
    keys = [vmd.BoneKey("右目", 0, fk.ZERO, fk.IDENTITY), vmd.BoneKey("左目", 0, fk.ZERO, fk.IDENTITY)]
    for frame, (yaw, pitch) in sorted((head or {0: (0.0, 0.0), last: (0.0, 0.0)}).items()):
        keys.append(vmd.BoneKey("頭", frame, fk.ZERO, fk.stored(turn(yaw, pitch))))
    away = tuple(f - r for f, r in zip(FAR, (-0.05, 17.214, EYE_Z - 3.75)))
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
    keys = sorted((k for k in motion.morphs if k.name == name), key=lambda k: k.frame)
    before = [k for k in keys if k.frame <= frame]
    return before[-1].weight if before else 0.0


def yaw_of(q):
    """the yaw (toward +X) a rotation (as applied) gives the rest gaze"""
    v = fk.rotate(q, (0.0, 0.0, -1.0))
    return math.degrees(math.atan2(v[0], -v[2]))


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


class FilterTest(unittest.TestCase):
    def test_damped_step_takes_its_time_without_overshoot(self):
        values = [0.0] * 10 + [1.0] * 80
        out = eye_optics.damped(values, 30.0, 0.1)
        self.assertEqual(out[:11], [0.0] * 11)
        rise = next(i for i, v in enumerate(out) if v >= 0.9) - next(i for i, v in enumerate(out) if v >= 0.1)
        self.assertGreaterEqual(rise / 30.0, 0.25)                    # the coordinator: 0.2 to 0.3 s or more
        self.assertTrue(all(b >= a for a, b in zip(out, out[1:])))
        self.assertLessEqual(max(out), 1.0)
        self.assertGreater(out[-1], 0.999)

    def test_rate_limit_keeps_slow_moves_and_spreads_jumps(self):
        slow = [(0.5 * i, 0.0) for i in range(20)]
        self.assertEqual(eye_optics.rate_limited(slow, 1.0), slow)
        jump = [(0.0, 0.0)] * 5 + [(10.0, 0.0)] * 20
        out = eye_optics.rate_limited(jump, 1.0)
        steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(out, out[1:])]
        self.assertLessEqual(max(steps), 1.0 + 1e-9)
        self.assertAlmostEqual(out[-1][0], 10.0)

    def test_smoothing_keeps_constants_and_never_steps_further(self):
        seq = [(0.0, 0.0)] * 5 + [(float(i), -0.5 * i) for i in range(10)] + [(9.0, -4.5)] * 5
        out = eye_optics.smoothed(seq)
        self.assertEqual(len(out), len(seq))
        self.assertEqual(out[0], (0.0, 0.0))
        self.assertEqual(out[-1], (9.0, -4.5))

        def most(s):
            return max(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(s, s[1:]))
        self.assertLessEqual(most(out), most(seq) + 1e-9)

    def test_soft_cap(self):
        for size in (0.0, 1.0, 4.0, 4.8, 6.0, 8.0, 20.0, 400.0):
            out = eye_optics.soft_cap((size * 0.6, -size * 0.8), 8.0)
            n = math.hypot(*out)
            self.assertLessEqual(n, 8.0)
            if size <= 4.8:
                self.assertAlmostEqual(n, size, 9)
        a, b = eye_optics.soft_cap((6.0, 0.0), 8.0), eye_optics.soft_cap((7.0, 0.0), 8.0)
        self.assertGreater(b[0], a[0])

    def test_fade(self):
        angles = [30.0] * 5 + [70.0] * 30 + [30.0] * 30
        out = eye_optics.fade_track(angles, 45.0, 55.0, 0.1)
        self.assertEqual(out[:5], [0.0] * 5)
        self.assertEqual(out[34], 1.0)
        self.assertEqual(out[-1], 0.0)
        self.assertLessEqual(max(abs(b - a) for a, b in zip(out, out[1:])), 0.1 + 1e-9)
        mid = eye_optics.fade_track([50.0], 45.0, 55.0, 1.0)
        self.assertAlmostEqual(mid[0], 0.5)


class TargetTest(unittest.TestCase):
    P = eye_optics.PARAMS["vergence"]

    def rows(self, n, camera=(30.0, 2.0), hands=()):
        return [{"camera": camera, "hands": list(hands)} for _ in range(n)]

    def test_camera_hand_and_free(self):
        rows = self.rows(10, camera=(2.0, 2.5))                           # looking at the camera, 2.5 m off
        rows += self.rows(15, hands=[(3.0, 0.35)])                        # a hand 3 degrees off the gaze, 35 cm off
        rows += self.rows(4, hands=[(3.0, 0.35)])
        rows += self.rows(4)                                               # (a gap)
        rows += self.rows(5, hands=[(3.0, 0.35)])                         # too short
        rows += self.rows(10, hands=[(3.0, 0.12)])                        # too near to look at
        rows += self.rows(10, hands=[(25.0, 0.35)])                       # too far off the gaze
        metres, labels = eye_optics.fixation_targets(rows, self.P)
        self.assertEqual(labels[:10], ["camera"] * 10)
        self.assertEqual(metres[:10], [2.5] * 10)
        self.assertEqual(labels[10:29], ["hand"] * 19)
        self.assertEqual(metres[10:29], [0.35] * 19)
        self.assertEqual(set(labels[29:]), {"free"})
        self.assertEqual(set(metres[29:]), {self.P["free_m"]})

    def test_camera_wins_over_a_hand_further_off_its_line(self):
        rows = self.rows(20, camera=(1.0, 2.5), hands=[(5.0, 0.4)])
        _, labels = eye_optics.fixation_targets(rows, self.P)
        self.assertEqual(set(labels), {"camera"})


class LightSwingTest(unittest.TestCase):
    def test_rest_head_has_no_swing(self):
        out = eye_optics.light_swing([fk.IDENTITY], eye_optics.toward_light((-0.5, -1.0, 0.5)), 0.75)
        self.assertEqual(out, [(0.0, 0.0)])

    def test_turning_the_head_moves_the_light_the_other_way(self):
        light = eye_optics.toward_light((-0.5, -1.0, 0.5))
        heads = [turn(10.0, 0.0), turn(-10.0, 0.0), turn(0.0, 10.0)]
        out = eye_optics.light_swing(heads, light, 0.75)
        self.assertLess(out[0][0], 0.0)                 # the head to her left: the light to her right in the head
        self.assertGreater(out[1][0], 0.0)
        self.assertLess(out[2][1], 0.0)                 # the head up: the light lower in the head

        def half(v):
            n = math.sqrt(sum(c * c for c in v))
            return tuple(c / n for c in v)
        n0 = half(tuple(a + b for a, b in zip(light, (0.0, 0.0, -1.0))))
        l1 = fk.rotate(fk.conjugate(heads[0]), light)
        n1 = half(tuple(a + b for a, b in zip(l1, (0.0, 0.0, -1.0))))
        self.assertAlmostEqual(out[0][0], math.degrees(0.75 * (n1[0] - n0[0])), 9)
        self.assertAlmostEqual(out[0][1], math.degrees(0.75 * (n1[1] - n0[1])), 9)


class PupilTest(unittest.TestCase):
    P = eye_optics.PARAMS["pupil"]

    def test_reflex_shape(self):
        r = self.P["reflex"]
        shape = [eye_optics.reflex_shape(i / 30.0, r["rise"], r["redilate"]) for i in range(0, 600)]
        self.assertEqual(shape[0], 0.0)
        self.assertLess(shape[1], 0.05)                                   # starts gently
        peak = max(range(len(shape)), key=lambda i: shape[i])
        self.assertAlmostEqual(shape[peak], 1.0, 3)
        self.assertTrue(0.4 <= peak / 30.0 <= 0.9, peak / 30.0)           # most constricted 0.4 to 0.9 s after the onset
        five_six = shape[int(5.5 * 30)]
        self.assertLess(five_six, 0.15)                                   # 90 % back in 5 to 6 s (Pilley & Thompson)
        second = [shape[i + 1] - 2 * shape[i] + shape[i - 1] for i in range(1, 599)]
        self.assertLess(max(abs(v) for v in second), 0.05)

    def test_flare_constricts_after_the_latency_and_comes_back(self):
        n = 330
        track = eye_optics.pupil_track(n, [30.0], None, [], [0.0] * n,
                                       eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.0}}), seed=0)
        total = track["total"]
        latency = int(round(self.P["reflex"]["latency"] * 30.0))
        self.assertTrue(all(v == 0.0 for v in total[:30 + latency]))
        low = min(range(n), key=lambda i: total[i])
        self.assertAlmostEqual(total[low], -self.P["reflex"]["amplitude"], 3)
        self.assertLess(total[-1], 0.0)
        self.assertGreater(total[-1], -0.2 * self.P["reflex"]["amplitude"])
        self.assertLess(max(abs(b - a) for a, b in zip(total, total[1:])), 0.25 * self.P["reflex"]["amplitude"])

    def test_loud_music_dilates_slowly(self):
        n = 450
        loud = [0.0] * 60 + [1.0] * 150 + [0.0] * 240
        track = eye_optics.pupil_track(n, [], loud, [], [0.0] * n,
                                       eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.0}}), seed=0)
        a = track["arousal"]
        self.assertLess(a[59], a[209])
        rise = next(i for i in range(60, n) if a[i] - a[59] >= 0.63 * (a[209] - a[59])) - 60
        self.assertTrue(20 <= rise <= 45, rise)                          # about the rise time (1 s)
        fall = next(i for i in range(210, n) if a[209] - a[i] >= 0.63 * (a[209] - a[59])) - 210
        self.assertGreater(fall, rise)                                    # it falls more slowly than it rose

    def test_unrest_is_small_smooth_and_seeded(self):
        n = 900
        p = eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.02}})
        a = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=3)["total"]
        b = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=3)["total"]
        c = eye_optics.pupil_track(n, [], None, [], [0.0] * n, p, seed=4)["total"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        rms = math.sqrt(sum(v * v for v in a) / n)
        self.assertTrue(0.01 <= rms <= 0.03, rms)
        self.assertLess(max(abs(y - x) for x, y in zip(a, a[1:])), 0.005)

    def test_near_point_constricts(self):
        n = 60
        near = [0.0] * 20 + [3.0] * 40
        total = eye_optics.pupil_track(n, [], None, [], near,
                                       eye_optics.merge_params(self.P, {"unrest": {"amplitude": 0.0}}), seed=0)["total"]
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
    def test_still_head_looking_at_a_camera_one_metre_away(self):
        result = run(c=camera(1.0))
        m = result.motion
        names = {k.name for k in m.bones}
        self.assertEqual(names, {"右目", "左目", "右HL２", "右HL", "左HL２", "左HL"})
        self.assertEqual({k.name for k in m.morphs}, {"瞳大", "瞳細", "HL消"})
        want = eye_optics.vergence_degrees(1.0, 61.7)
        right = keys_of(m, "右目")
        self.assertAlmostEqual(yaw_of(fk.applied(right[-1].rotation)), want, 2)
        self.assertLess(right[-1].rotation[1], 0.0)
        self.assertAlmostEqual(yaw_of(fk.applied(keys_of(m, "左目")[-1].rotation)), -want, 2)
        for name in ("右HL２", "右HL"):                                    # the light: its share of the vergence only
            self.assertAlmostEqual(yaw_of(fk.applied(keys_of(m, name)[-1].rotation)), 0.55 * want, 2)
        self.assertEqual(morph_at(m, "HL消", 90), 0.0)
        self.assertEqual(morph_at(m, "瞳大", 90), 0.0)
        near = eye_optics.PARAMS["pupil"]["near"]["per_dioptre"] * (1.0 / 1.0 - 1.0 / 3.0)   # the near response only
        self.assertAlmostEqual(morph_at(m, "瞳細", 90), near / 0.67, 4)
        rep = result.report
        self.assertEqual(rep["vergence"]["labels"], {"camera": 91})
        self.assertAlmostEqual(rep["model"]["share"], 0.55, 6)

    def test_hand_in_front_brings_the_eyes_together_smoothly(self):
        away = tuple(f - r for f, r in zip(FAR, (-0.05, 17.214, EYE_Z - 3.75)))
        hand = {0: away, 29: away, 30: (0.0, 0.0, 0.0), 69: (0.0, 0.0, 0.0), 70: away, 120: away}
        result = run(d=dance(120, hand=hand), g=gaze(120), c=camera(2.5, yaw=30.0, last=120))
        yaws = [yaw_of(fk.applied(k.rotation)) for k in keys_of(result.motion, "右目")]
        frames = [k.frame for k in keys_of(result.motion, "右目")]
        at = dict(zip(frames, yaws))

        def value(f):
            return at[max(x for x in frames if x <= f)]
        near, far = eye_optics.vergence_degrees(0.3, 61.7), eye_optics.vergence_degrees(3.0, 61.7)
        self.assertAlmostEqual(value(29), far, 2)
        self.assertGreater(value(69), near - 0.1)
        ten = next(f for f in range(30, 70) if value(f) >= far + 0.1 * (near - far))
        ninety = next(f for f in range(30, 70) if value(f) >= far + 0.9 * (near - far))
        self.assertGreaterEqual((ninety - ten) / 30.0, 0.2)
        steps = [abs(value(f + 1) - value(f)) for f in range(120)]
        self.assertLess(max(steps), 1.5)
        self.assertEqual(result.report["vergence"]["labels"]["hand"], 40)

    def test_fast_head_turn_moves_the_added_light_at_most_a_degree_a_frame(self):
        head = {0: (0.0, 0.0), 30: (0.0, 0.0), 36: (40.0, 0.0), 90: (40.0, 0.0)}
        result = run(d=dance(90, head=head), g=gaze(90, {30: (0.0, 0.0)}))
        light = result.report["light"]
        self.assertLessEqual(light["added_step"]["max"], 1.0 + 1e-6)
        self.assertLessEqual(light["added"]["max"], eye_optics.PARAMS["light"]["cap"] + 1e-6)
        q0 = keys_of(result.motion, "左HL２")[-1].rotation
        self.assertLess(yaw_of(fk.applied(q0)), -1.0)               # the head went to her left: the light to her right
        keys = keys_of(result.motion, "左HL２")
        frames = [k.frame for k in keys]
        yaws = {k.frame: yaw_of(fk.applied(k.rotation)) for k in keys}

        def value(f):
            return yaws[max(x for x in frames if x <= f)]
        steps = [value(f + 1) - value(f) for f in range(90)]
        bends = [abs(b - a) for a, b in zip(steps, steps[1:])]
        self.assertLess(max(bends), 0.5)                            # the corners of the limited way are rounded

    def test_light_behind_fades_the_highlights(self):
        head = {0: (0.0, 0.0), 20: (0.0, 0.0), 40: (0.0, -75.0), 120: (0.0, -75.0)}
        result = run(d=dance(120, head=head), g=gaze(120), c=camera(2.5, last=120))
        self.assertEqual(morph_at(result.motion, "HL消", 10), 0.0)
        self.assertAlmostEqual(morph_at(result.motion, "HL消", 120), 1.0, 6)
        fade = result.report["fade"]
        self.assertLessEqual(fade["step"]["max"], eye_optics.PARAMS["light"]["fade_step"] + 1e-9)

    def test_flare_reaches_the_pupil_morph(self):
        result = run(d=dance(150), g=gaze(150), c=camera(2.5, last=150), flares=[1.0])
        before = morph_at(result.motion, "瞳細", 30)          # the near response to the camera 2.5 m away, alone
        self.assertEqual(morph_at(result.motion, "瞳細", 36), before)       # nothing before the latency (0.25 s)
        thin = max(morph_at(result.motion, "瞳細", f) for f in range(151))
        want = eye_optics.PARAMS["pupil"]["reflex"]["amplitude"] / 0.67
        self.assertAlmostEqual(thin - before, want, 2)
        for channel in ("瞳大", "瞳細"):
            self.assertIn("max", result.report["pupil"]["steps"][channel])

    def test_light_gain_is_the_human_corneas_scaled_by_the_models_iris(self):
        rep = run().report
        h = pmx_eyes.HUMAN
        scale = pmx_eyes.model_scale(pmx_edit.loads(MODEL_BYTES))["scale"]
        self.assertAlmostEqual(rep["light"]["gain"], h["cornea_radius"] / h["pupil"] * scale, 6)
        forced = run(params={"light": {"gain": 0.75}, "pupil": {"unrest": {"amplitude": 0.0}}}).report
        self.assertEqual(forced["light"]["gain"], 0.75)

    def test_report_has_the_step_measures(self):
        rep = run().report
        for part in ("vergence", "light", "fade", "pupil"):
            self.assertIn(part, rep)
        self.assertIn("p99", rep["vergence"]["step"])
        self.assertIn("p99", rep["light"]["added_step"])
        self.assertIn("p99", rep["light"]["bone_step"])


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
        out = json.loads(printed.getvalue())
        self.assertTrue(out["ok"])
        motion = vmd.load(os.path.join(self.tmp, "out.vmd"))
        self.assertTrue(motion.bones and motion.morphs)
        with open(report, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["pupil"]["flares_s"], [1.0])

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
        self.assertEqual(rep["params"]["vergence"]["free_m"], eye_optics.PARAMS["vergence"]["free_m"])

    def test_unknown_param_is_refused(self):
        params = os.path.join(self.tmp, "p.json")
        with open(params, "w", encoding="utf-8") as f:
            json.dump({"vergence": {"ipd": 70.0}}, f)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(eye_optics.main(self.args("--params", params)), 2)
        self.assertIn("ipd", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
