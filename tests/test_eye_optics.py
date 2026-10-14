"""tools/eye_optics.py: the catchlights, the pupils and the vergence of the eyes, as one VMD after the dance, the face
and the gaze."""
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import struct
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


def look(first, last, aim=HAND_REST, hand="右"):
    """a look at a hand as tools/eye_gaze.py's report lists it (frames first to last, the point the eyes aim at on each)"""
    return {"first": first, "last": last, "seconds": round((last - first + 1) / 30.0, 3), "hand": hand, "metres": 0.3,
            "settle": first, "aim": [list(aim)] * (last - first + 1)}


def gaze_report(*looks, contacts=(), motion=None, on=None):
    """the parts of tools/eye_gaze.py's --report that eye_optics reads: the looks at a hand, the eye contacts and the
    md5 of the 両目 VMD it wrote (of `motion`, when given)"""
    rep = {"hands": {"count": len(looks), "frames": sum(L["last"] - L["first"] + 1 for L in looks), "list": list(looks)},
           "contacts": {"count": len(contacts), "list": [{"first": a, "last": b} for a, b in contacts]}}
    if motion is not None:
        rep["out_md5"] = hashlib.md5(vmd.dumps(motion)).hexdigest()
    if on is not None:                                      # the dance it was made on
        rep["in_md5"] = hashlib.md5(vmd.dumps(on)).hexdigest()
    return rep


def looks_of(*looks, contacts=()):
    return eye_optics.gaze_looks(gaze_report(*looks, contacts=contacts))


def keys_of(motion, name):
    return sorted((k for k in motion.bones if k.name == name), key=lambda k: k.frame)


def keys_of_morph(motion, name):
    return sorted((k for k in motion.morphs if k.name == name), key=lambda k: k.frame)


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


def light_on_screen(motion_list, frame, light_name, eye_name, side, morphs=None):
    """the light's centre minus the pupil's centre, seen from the front (X right, Y up), in model units; `morphs`
    {name: weight} move the light's quad before its bone turns it (the mean offset of its vertices)"""
    motion = eye_optics.merge(*motion_list)
    pose = fk.Pose(MODEL, motion, [light_name, eye_name])
    world = pose.at(frame)
    b = bone(light_name)
    quad_rest = tuple(p + t for p, t in zip(b.position, b.tail["offset"]))
    if morphs:
        doc = pmx_edit.loads(MODEL_BYTES)
        offsets = pmx_eyes.vertex_morphs(doc)
        mine = [v for v, vx in enumerate(doc.vertices) if vx.pairs() and vx.pairs()[0][0] == b.index]
        for name, w in morphs.items():
            shift = [sum(offsets[name].get(v, (0.0, 0.0, 0.0))[c] for v in mine) / len(mine) for c in range(3)]
            quad_rest = tuple(q + w * s for q, s in zip(quad_rest, shift))
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


class VergencePhaseTest(unittest.TestCase):
    """the vergence is in phase with the look at a hand: it starts a little ahead of the look (the eyes lead a target
    the hand moves, Erkelens 1989), opens from the look's last frame, and is 0 on every frame on the camera"""
    P = eye_optics.PARAMS["vergence"]

    def phase(self, demands, labels):
        return eye_optics.vergence_in_phase(demands, labels, 30.0, self.P["lead"], self.P["duration"], self.P["max_speed"])

    def test_converges_through_the_look_and_is_parallel_on_the_camera(self):
        labels = ["camera"] * 30 + ["free"] * 5 + ["hand"] * 30 + ["free"] * 10 + ["camera"] * 30
        demands = [0.0] * 35 + [5.0] * 30 + [0.0] * 40
        out = self.phase(demands, labels)
        first, last = 35, 64
        start = first - self.P["lead"] * 30.0
        self.assertTrue(all(v == 0.0 for v in out[:int(math.floor(start)) + 1]))
        self.assertGreater(out[first], 0.0)                         # already on its way on the look's first frame
        peak = max(range(len(out)), key=lambda i: out[i])
        self.assertTrue(first <= peak <= last, peak)
        self.assertAlmostEqual(max(out), 5.0, 6)
        self.assertEqual(max(v for v, lab in zip(out, labels) if lab == "camera"), 0.0)
        five = next(i for i, v in enumerate(out) if v >= 0.25)
        ninety_five = next(i for i, v in enumerate(out) if v >= 4.75)
        self.assertAlmostEqual((ninety_five - five) / 30.0, self.P["duration"], delta=1.5 / 30.0)
        self.assertGreater(out[last], 4.9)                          # opens from the look's last frame
        self.assertLess(out[last + 8], 2.0)
        self.assertTrue(all(b >= a for a, b in zip(out[:first], out[1:first + 1])))

    def test_a_look_between_two_looks_at_the_camera_rises_less_and_never_on_the_camera(self):
        labels = ["camera"] * 20 + ["hand"] * 6 + ["camera"] * 20
        demands = [0.0] * 20 + [5.0] * 6 + [0.0] * 20
        out = self.phase(demands, labels)
        self.assertEqual(max(v for v, lab in zip(out, labels) if lab == "camera"), 0.0)
        peak = max(range(len(out)), key=lambda i: out[i])
        self.assertTrue(20 <= peak <= 25, peak)
        self.assertGreater(max(out), 0.3)                           # a glance of 0.2 s: it only begins
        self.assertLess(max(out), 2.0)

    def test_a_look_of_0_3_seconds_is_converged_through_most_of_it(self):
        """the gaze's looks at a hand last 0.3 to 0.6 s (the MV v8's 52 s: 9 frames, 5.3 degrees an eye): the eyes are
        more than half way from the look's third frame to its last, and most of the vergence (degrees x frames) lies
        within the look, not after it (a person takes longer: about 0.33 s to 90 % for 10 to 12 degrees, Collewijn et
        al. 1995 Fig. 17; the shape is chosen to fit the short looks).  At 0.41 s (5 to 95 % 0.25 s, stage 5)
        the eyes passed 3 degrees on the look's last 4 frames only and 55 % of the vergence came after it"""
        labels = ["free"] * 20 + ["hand"] * 9 + ["free"] * 30
        top = 5.3
        out = self.phase([0.0] * 20 + [top] * 9 + [0.0] * 30, labels)
        a, b = 20, 28
        self.assertGreaterEqual(min(out[a + 2:b + 1]), 0.55 * top, out[a:b + 1])
        self.assertGreaterEqual(sum(out[a:b + 1]) / sum(out), 0.6)
        self.assertEqual(max(out[b + 10:]), 0.0)                    # parallel again within 0.33 s of the look's end

    def test_a_big_angle_keeps_under_the_top_speed(self):
        labels = ["free"] * 10 + ["hand"] * 60 + ["free"] * 60
        out = self.phase([0.0] * 10 + [11.6] * 60 + [0.0] * 60, labels)
        speed = max(abs(b - a) for a, b in zip(out, out[1:])) * 30.0
        self.assertLessEqual(speed, self.P["max_speed"] + 1e-6)
        self.assertGreater(speed, 30.0)                             # natural, not the screen experiments' 8 deg/s
        self.assertAlmostEqual(max(out), 11.6, 6)
        self.assertEqual(out[-1], 0.0)


class TargetTest(unittest.TestCase):
    """what the eyes look at, frame by frame: her hand on the looks tools/eye_gaze.py planned (its report), the camera
    where the gaze meets it or on the report's eye contacts, and nothing near elsewhere (stage 6: eye_optics found its
    own looks where a hand lay within 12 degrees of the gaze, and 96 % of the vergence of the MV v8 fell outside the
    gaze's looks, review gaze-v8 4.2)"""
    P = eye_optics.PARAMS["vergence"]

    def rows(self, n, camera=(30.0, 2.0)):
        return [{"camera": camera} for _ in range(n)]

    def test_only_the_looks_of_the_gaze_are_on_a_hand(self):
        rows = self.rows(10, camera=(2.0, 2.5)) + self.rows(40)            # on the camera 2.5 m off, then elsewhere
        metres, labels = eye_optics.fixation_targets(rows, self.P, [(15, 29, [0.35] * 15)])
        self.assertEqual(labels[:10], ["camera"] * 10)
        self.assertEqual(labels[15:30], ["hand"] * 15)
        self.assertEqual(metres[15:30], [0.35] * 15)
        self.assertEqual(set(labels[10:15] + labels[30:]), {"free"})
        self.assertEqual(set(metres[10:15] + metres[30:]), {None})
        _, labels = eye_optics.fixation_targets(rows, self.P)              # no looks: no hand
        self.assertNotIn("hand", labels)

    def test_an_eye_contact_of_the_report_is_on_the_camera_however_far_off_the_gaze_is(self):
        # the eyes follow the camera inside their contact zone: where it lies beyond, the gaze is off it by more than
        # camera_deg and she still looks at the viewer
        rows = self.rows(30)
        _, labels = eye_optics.fixation_targets(rows, self.P, [], contacts=[(5, 14)])
        self.assertEqual(labels[5:15], ["camera"] * 10)
        self.assertEqual(set(labels[:5] + labels[15:]), {"free"})

    def test_the_camera_wins_over_a_look_on_the_frames_the_gaze_meets_it(self):
        rows = self.rows(10) + self.rows(5, camera=(2.0, 2.5)) + self.rows(10)
        _, labels = eye_optics.fixation_targets(rows, self.P, [(0, 24, [0.3] * 25)])
        self.assertEqual(labels, ["hand"] * 10 + ["camera"] * 5 + ["hand"] * 10)

    def test_two_looks_a_short_gap_apart_are_one_unless_the_camera_is_between(self):
        gap = self.P["gap_frames"]
        rows = self.rows(16 + gap)
        looks = [(0, 7, [0.3] * 8), (8 + gap, 15 + gap, [0.2] * 8)]
        metres, labels = eye_optics.fixation_targets(rows, self.P, looks)
        self.assertEqual(labels, ["hand"] * (16 + gap))
        self.assertEqual(metres[8:8 + gap], [None] * gap)
        demand = eye_optics.vergence_demand(labels, metres, self.P)
        self.assertEqual(set(demand), {eye_optics.vergence_degrees(0.25, self.P["ipd_mm"])})   # the median of the aims
        _, labels = eye_optics.fixation_targets(rows, self.P, looks, contacts=[(9, 10)])
        self.assertEqual(labels[8:8 + gap], ["free", "camera", "camera"] + ["free"] * (gap - 3))
        rows = self.rows(17 + gap)
        _, labels = eye_optics.fixation_targets(rows, self.P, [(0, 7, [0.3] * 8), (9 + gap, 16 + gap, [0.2] * 8)])
        self.assertEqual(labels[8:9 + gap], ["free"] * (gap + 1))

    def test_only_a_hand_brings_the_eyes_together_by_the_geometric_angle(self):
        labels = ["camera", "camera", "hand", "hand", "free"]
        metres = [1.0, 1.0, 0.3, 0.3, 3.0]
        demand = eye_optics.vergence_demand(labels, metres, self.P)
        want = math.degrees(math.atan(61.5 / 2.0 / 300.0))           # no share of it: the eyes meet on the hand
        self.assertAlmostEqual(want, 5.852, 3)
        self.assertEqual(demand[:2] + demand[4:], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(demand[2], want, 9)
        self.assertAlmostEqual(demand[3], want, 9)

    def test_a_hand_nearer_than_15_cm_turns_the_eyes_as_one_at_15_cm(self):
        demand = eye_optics.vergence_demand(["hand"] * 4, [0.11, 0.12, 0.11, 0.12], self.P)
        self.assertAlmostEqual(demand[0], eye_optics.vergence_degrees(0.15, self.P["ipd_mm"]), 9)
        self.assertAlmostEqual(demand[0], 11.59, 2)


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

    def test_drawn_place_is_laid_on_the_iris_upright(self):
        n, y = (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)
        for view in ((0.0, 0.0, -1.0), (0.0, 0.0, 1.0)):                 # seen from in front, and from behind
            _, up = eye_optics.screen_basis(view)
            got = eye_optics.drawn_on_iris(0.1, 0.05, up, n, y)
            self.assertEqual(tuple(round(c, 9) for c in got), (0.1, 0.05, 0.0))   # +X across: not mirrored
        t = math.radians(30.0)                                           # an iris turned 30 degrees toward +X
        slanted = (math.sin(t), 0.0, -math.cos(t))
        _, up = eye_optics.screen_basis((0.0, 0.0, -1.0))
        got = eye_optics.drawn_on_iris(0.1, 0.05, up, slanted, y)
        self.assertAlmostEqual(got[0], 0.1 * math.cos(t), 9)            # shrinks across as the camera sees it
        self.assertAlmostEqual(got[1], 0.05, 9)
        self.assertAlmostEqual(eye_optics._dot(got, slanted), 0.0, 9)   # in the iris' plane

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
        self.assertEqual((rep["vergence"]["source"], rep["vergence"]["looks"]), ("none", 0))   # no gaze report given
        self.assertAlmostEqual(rep["model"]["share"], 0.55, 6)
        for part in ("vergence", "light", "fade", "pupil"):
            self.assertIn(part, rep)
        self.assertIn("p99", rep["vergence"]["step"])
        self.assertIn("p99", rep["light"]["key_step"])
        self.assertIn("p99", rep["light"]["offset_step"])
        self.assertEqual(rep["vergence"]["camera_max_degrees"], 0.0)
        for name in ("右HL２", "右HL", "左HL２", "左HL"):
            self.assertEqual(rep["light"]["rim"][name]["open_frames"], 91)
            self.assertEqual(rep["light"]["lids"][name], {"slid_frames": 0, "covered_frames": 0, "slid_max": 0.0,
                                                          "onto_iris_frames": 0, "behind_iris_frames": 0,
                                                          "beside_iris_frames": 0})
        self.assertIn("behind_rim_plane_frames", rep["light"])
        self.assertEqual(len(keys_of_morph(result.motion, "HL消")), 2)       # never on: the first and the last frame
        doc = pmx_edit.loads(MODEL_BYTES)
        names = [pmx_eyes.morph_name(doc, m) for m in doc.morphs]
        self.assertEqual(rep["keys"]["registered"], len(result.motion.morphs) + len(names) - 3)
        self.assertEqual(rep["keys"]["margin"], 20000 - rep["keys"]["registered"])

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

    def test_camera_behind_her_keeps_the_keys_small(self):
        g = gaze(90, {0: (10.0, 0.0)})
        result = run(g=g, c=camera(10.0, yaw=180.0), params=FRONT_LIGHT)
        for name in ("右HL２", "右HL", "左HL２", "左HL"):
            for k in keys_of(result.motion, name):
                self.assertLess(eye_optics._angle(k.rotation), 10.0)

    def test_a_fast_head_turn_to_the_side_does_not_flick_the_light(self):
        """the head swings 80 degrees away in 4 frames and back (the MV's 111.2 seconds, where the first version threw
        the light across the iris and back): as the camera sees it, the light moves under half an iris radius a frame
        while the head turns 20 degrees a frame, and the iris seen edge on hands it over to its drawn place"""
        head = {0: (0.0, 0.0), 30: (0.0, 0.0), 34: (80.0, 0.0), 40: (80.0, 0.0), 44: (0.0, 0.0), 90: (0.0, 0.0)}
        result = run(d=dance(90, head=head), c=camera(1.0), params=QUIET)
        self.assertGreater(max(result.trace["camera_aside"]), 0.6)
        for k, name in enumerate(result.trace["lights"]):
            steps = [math.hypot(b[k][0] - a[k][0], b[k][1] - a[k][1])
                     for a, b in zip(result.trace["screen"], result.trace["screen"][1:])]
            self.assertLess(max(steps), 0.5, name)
            self.assertAlmostEqual(result.report["light"]["screen_step_without_cuts"][name]["max"], max(steps), delta=1e-3)

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
        pushed = max(r["pushed_over_0.1"] for r in rep["rim"].values())
        self.assertGreater(pushed, 0.5)                       # held back by the rim more than 0.1 in most frames
        self.assertLessEqual(rep["disc_r"]["max"], reach + 1e-3)
        self.assertLessEqual(rep["open"]["disc_r"]["max"], reach + 1e-3)
        self.assertEqual(rep["open"]["light_frames"], 4 * 91)
        self.assertGreater(result.report["ride"]["height"]["min"], 0.0)   # every light in front of its iris' surface

    def test_a_dish_seen_at_a_slant_keeps_the_light_over_the_iris_the_camera_sees(self):
        """on a tilted dish the deep side seen at a slant shows off where the rim's plane puts it: a light held on that
        plane alone leaves the iris (the MV's 45.7 and 214 seconds); held where the camera's line meets the dish, it
        stays within the reach"""
        model = RideTest.tilted()
        g = gaze(30, {0: (-15.0, 0.0)})

        def go(seen):
            p = eye_optics.merge_params(eye_optics.PARAMS, {"light": {"seen": seen}, "pupil": {"unrest": {"amplitude": 0.0}}})
            return eye_optics.optics(model, dance(30), g, camera(1.0, yaw=30.0, last=30), p)
        reach = eye_optics.PARAMS["light"]["reach"]
        held, plane = go(True), go(False)
        self.assertEqual(held.report["light"]["camera_aside"]["frames_partly"], 0)
        self.assertTrue(all(uv is not None for row in held.trace["iris"] for uv in row))     # every light over its iris
        radii = [math.hypot(*uv) for row in held.trace["iris"] for uv in row]
        self.assertLessEqual(max(radii), reach + 2e-3)
        self.assertGreater(max(radii), reach - 0.01)                        # held at the reach, not further in
        off = sum(1 for row in plane.trace["iris"] for uv in row if uv is None)            # beside the iris
        self.assertGreater(off, 20)
        self.assertLessEqual(held.report["light"]["disc_r"]["max"], reach + 1e-3)

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

    def test_a_look_at_the_hand_brings_the_eyes_together_in_phase(self):
        away = tuple(f - r for f, r in zip(FAR, HAND_REST))
        hand = {0: away, 29: away, 30: (0.0, 0.0, 0.0), 89: (0.0, 0.0, 0.0), 90: away, 150: away}
        result = run(d=dance(150, hand=hand), g=gaze(150), c=camera(2.5, yaw=30.0, last=150), looks=looks_of(look(30, 89)))
        keys = keys_of(result.motion, "右目")
        frames = [k.frame for k in keys]

        def value(f):
            return yaw_of(fk.applied(fk.sample(keys, f, frames)[1]))
        p = eye_optics.PARAMS["vergence"]
        want = math.degrees(math.atan(61.5 / 2.0 / 300.0))           # the hand 30 cm in front: the geometric angle
        self.assertAlmostEqual(value(30 - 3), 0.0, delta=0.05)      # keys within 0.05 degrees
        self.assertGreater(value(31), 0.3)                          # already on its way as the hand arrives
        self.assertAlmostEqual(value(60), want, delta=0.05)
        self.assertAlmostEqual(value(89), want, delta=0.05)
        self.assertAlmostEqual(value(89 + 14), 0.0, delta=0.05)     # parallel again 0.45 s after the hand left
        self.assertLessEqual(max(abs(value(f + 1) - value(f)) for f in range(150)), p["max_speed"] / 30.0 + 0.1)
        rep = result.report["vergence"]
        self.assertEqual((rep["source"], rep["looks"], rep["labels"]["hand"]), ("gaze report", 1, 60))
        run_ = rep["hand_runs"][0]
        self.assertEqual((run_["first"], run_["last"], run_["hand"]), (30, 89, "右"))
        self.assertAlmostEqual(run_["median_m"], 0.30, delta=0.002)
        self.assertLess(run_["aim_off_gaze_degrees"], 1.0)          # the gaze straight ahead, on the hand
        self.assertAlmostEqual(run_["reached_within_degrees"], want, delta=0.01)
        self.assertLess(run_["reached_after_degrees"], want)
        self.assertTrue(30 <= run_["peak_frame"] <= 89)
        self.assertEqual(rep["share"]["hand"], 1.0 - rep["share"].get("free", 0.0))

    def test_a_hand_before_her_face_she_does_not_look_at_leaves_the_eyes_parallel(self):
        """the hand 30 cm straight before the eyes, on the gaze, for 2 seconds: without a look at it in the gaze's
        report the eyes stay parallel (a person fixates and converges on what she looks at, and sees a nearer object
        double; stage 5 converged on any hand within 12 degrees of the gaze, the MV's hands over her face included)"""
        away = tuple(f - r for f, r in zip(FAR, HAND_REST))
        hand = {0: away, 29: away, 30: (0.0, 0.0, 0.0), 89: (0.0, 0.0, 0.0), 90: away, 150: away}
        for looks in (None, looks_of()):
            result = run(d=dance(150, hand=hand), g=gaze(150), c=camera(2.5, yaw=30.0, last=150), looks=looks)
            self.assertEqual(max(result.trace["vergence"]), 0.0)
            self.assertNotIn("hand", result.report["vergence"]["labels"])
            for k in keys_of(result.motion, "右目") + keys_of(result.motion, "左目"):
                self.assertAlmostEqual(yaw_of(fk.applied(k.rotation)), 0.0, 9)

    def test_the_eyes_meet_at_the_distance_of_the_point_she_aims_at(self):
        # the gaze's report names the point 50 cm along the gaze: the eyes meet there, not on the hand 30 cm off that
        # lies on the gaze too
        away = tuple(f - r for f, r in zip(FAR, HAND_REST))
        hand = {0: away, 29: away, 30: (0.0, 0.0, 0.0), 89: (0.0, 0.0, 0.0), 90: away, 150: away}
        aim = (-0.05, 17.214, EYE_Z - 0.5 / 0.08)
        result = run(d=dance(150, hand=hand), g=gaze(150), c=camera(2.5, yaw=30.0, last=150),
                     looks=looks_of(look(30, 89, aim=aim)))
        want = math.degrees(math.atan(61.5 / 2.0 / 500.0))
        self.assertAlmostEqual(result.trace["vergence"][60], want, delta=0.01)
        self.assertAlmostEqual(result.report["vergence"]["hand_runs"][0]["median_m"], 0.5, delta=0.002)

    def test_the_vergence_peaks_on_a_short_look_at_the_hand_and_is_0_on_the_camera(self):
        """she looks at the camera, turns her eyes 10 degrees onto her hand 30 cm off for 10 frames, and back: the eyes
        converge on the hand and are parallel on every frame on the camera"""
        offset = (3.75 * math.sin(math.radians(10.0)) + 0.05, 0.0, 3.75 - 3.75 * math.cos(math.radians(10.0)))
        away = tuple(f - r for f, r in zip(FAR, HAND_REST))
        hand = {0: away, 39: away, 40: offset, 49: offset, 50: away, 90: away}
        g = gaze(90, {0: (0.0, 0.0), 40: (10.0, 0.0), 50: (0.0, 0.0)})
        aim = tuple(r + o for r, o in zip(HAND_REST, offset))
        result = run(d=dance(90, hand=hand), g=g, c=camera(1.0), looks=looks_of(look(40, 49, aim=aim)))
        labels, angle = result.trace["label"], result.trace["vergence"]
        self.assertEqual(labels[40:50], ["hand"] * 10)
        self.assertEqual(set(labels[:40] + labels[50:]), {"camera"})
        self.assertEqual(max(a for a, lab in zip(angle, labels) if lab == "camera"), 0.0)
        peak = max(range(len(angle)), key=lambda i: angle[i])
        self.assertTrue(40 <= peak <= 49, peak)
        self.assertGreater(max(angle), 1.0)
        self.assertEqual(result.report["vergence"]["camera_max_degrees"], 0.0)

    def test_a_look_beyond_the_frames_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            run(looks=looks_of(look(80, 95)))
        self.assertIn("80", str(ctx.exception))

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
    """MMD stops loading past 20,000 registered points of a model (its morphs' keys from every motion loaded, one per
    morph and frame, and one for each morph with no key on frame 0; bone keys are not counted): the first version's
    8,205 morph keys with the face's 11,745, the dance's and the frame-0 points crossed it.  Keys only where straight
    lines between them miss the values, and the tool refuses near the limit."""

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

    def test_the_pupil_keys_of_a_song_leave_room_under_the_limit(self):
        """the MV's length (7,743 frames) with its flares, choruses, loudness and the vergence's near response: the
        pupil's morph keys, with the face's 11,724 (face_v6d) and the model's 133 frame-0 points, stay 5,000 under
        the limit"""
        n = 7743
        p = eye_optics.PARAMS["pupil"]
        arousal = [0.5 + 0.5 * math.sin(i / 97.0) * math.sin(i / 13.0) for i in range(n)]
        near = [3.0 if (i // 450) % 4 == 1 and i % 450 < 30 else 0.0 for i in range(n)]
        pupil = eye_optics.pupil_track(n, [1334.0, 3605.0, 7236.0], arousal, [1800.0, 3857.0, 5966.0], near, p, seed=0)
        big, thin = eye_optics.pupil_weights(pupil["total"], 1.7057, -0.6098)
        frames = list(range(n))
        keys = (eye_optics._morph_keys("瞳大", frames, big) + eye_optics._morph_keys("瞳細", frames, thin)
                + eye_optics._morph_keys("HL消", frames, [0.0] * n))
        self.assertLess(len(keys), 20000 - 11724 - 133 - 5000)

    def test_registered_points_count_each_morph_and_frame_once_and_the_frame_0_points(self):
        a = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("a", 0, 0.0), vmd.MorphKey("a", 5, 1.0),
                                                 vmd.MorphKey("x", 3, 1.0)])            # x: not the model's
        b = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("a", 5, 0.5), vmd.MorphKey("b", 10, 1.0)])
        c = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("c", 0, 0.0), vmd.MorphKey("c", 20, 1.0)])
        # keys a0 a5 b10 c0 c20, and b and d without a key on frame 0
        self.assertEqual(eye_optics.registration_points(["a", "b", "c", "d"], [a, b, None, c]), 5 + 2)

    def test_too_many_points_with_the_face_are_refused(self):
        face = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("まばたき", f, 0.0) for f in range(19500)])
        with self.assertRaises(ValueError) as ctx:
            run(face=face)
        self.assertIn("20000", str(ctx.exception))


class LidTest(unittest.TestCase):
    """the face's closing morphs move the light quads themselves (the toy's まばたき lowers both upper lights: it
    closes both eyes), as Sour's Rin's drag her upper lights down with the lids"""

    @staticmethod
    def face(weights):
        return vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("まばたき", f, w) for f, w in sorted(weights.items())])

    def test_a_lowering_lid_drags_the_upper_light_as_the_model_does(self):
        """the toy's まばたき moves its upper lights (0, -0.17, 0.05) per unit, as Sour's Rin's drags hers down with the
        lid: kept (held in place, a lifted light shows in front of the lid); the trace gives the place MMD shows"""
        held = run(c=camera(1.0), face=self.face({0: 0.4, 90: 0.4}))
        free = run(c=camera(1.0), face=self.face({0: 0.0, 90: 0.0}))
        k = held.trace["lights"].index("左HL２")
        drop = free.trace["disc"][10][k][1] - held.trace["disc"][10][k][1]
        self.assertAlmostEqual(drop, 0.4 * 0.17 / 0.22, delta=0.03)              # in the iris' half heights
        lower = held.trace["lights"].index("左HL")                               # the morph leaves it
        self.assertAlmostEqual(held.trace["disc"][10][lower][1], free.trace["disc"][10][lower][1], delta=0.01)
        shown = light_on_screen([dance(), gaze(), held.motion], 10, "左HL２", "左目", 1.0, {"まばたき": 0.4})
        bare = light_on_screen([dance(), gaze(), free.motion], 10, "左HL２", "左目", 1.0)
        self.assertAlmostEqual(bare[1] - shown[1], 0.4 * 0.17, delta=0.005)

    @staticmethod
    def sideways_blink(offset=(-0.12, -0.05, 0.05)):
        """the toy with its まばたき dragging the upper lights sideways too (Sour's Rin's drags them down and along the
        lid): offset per unit weight"""
        doc = pmx_edit.loads(MODEL_BYTES)
        fmt = "<" + {1: "B", 2: "H", 4: "i"}[doc.sizes["vertex"]]
        for m in doc.morphs:
            if pmx_eyes.morph_name(doc, m) == "まばたき":
                moved = sorted(pmx_eyes.vertex_morphs(doc)["まばたき"])
                m.body = b"".join(struct.pack(fmt, v) + struct.pack("<3f", *offset) for v in moved)
                m.count = len(moved)
        return pmx_edit.dumps(doc)

    def test_the_dragged_light_still_stays_on_the_iris(self):
        """the iris' boundary holds the light as MMD shows it, the lid's drag included: the head turned 30 degrees
        pushes the lights to the edge, the lid held 0.4 shut drags the upper ones further out"""
        head = {0: (30.0, 0.0), 90: (30.0, 0.0)}
        model = self.sideways_blink()

        def go(weight):
            return eye_optics.optics(model, dance(90, head=head), gaze(), camera(1.0),
                                     eye_optics.merge_params(eye_optics.PARAMS, QUIET), face=self.face({0: weight, 90: weight}))
        held, free = go(0.4), go(0.0)
        reach = eye_optics.PARAMS["light"]["reach"]
        k = held.trace["lights"].index("左HL２")
        self.assertGreater(abs(free.trace["disc"][10][k][0]), 0.7)                   # the head's turn: near the edge
        self.assertLessEqual(max(math.hypot(*row[k]) for row in held.trace["disc"]), reach + 0.01)
        self.assertLess(held.trace["disc"][10][k][1], free.trace["disc"][10][k][1] - 0.05)   # still dragged down

    EDGE, LID_Z, DROP = 17.30, -1.0, 0.4          # the toy's upper lid: its edge at rest, its depth, まばたき's drop

    @classmethod
    def lidded(cls):
        """the toy with an upper lid over each iris (in front of the iris, behind the drawn upper light), that まばたき
        lowers with the upper lights"""
        data, _ = toy_bytes(extra_bones=[("右人指３先", -1, HAND_REST)], iris_z=-0.96, lid=(cls.EDGE, cls.LID_Z, cls.DROP))
        doc = pmx_edit.loads(data)
        pmx_eyes.build(doc, share=0.55)
        return pmx_edit.dumps(doc)

    @staticmethod
    def light_world(model_bytes, motion_list, frame, name, weight):
        """where MMD shows a light quad's centre: its bone's FK with the まばたき at `weight` on the quad"""
        model = pmx.loads(model_bytes)
        doc = pmx_edit.loads(model_bytes)
        b = next(x for x in model.bones if x.name == name)
        mine = [v for v, vx in enumerate(doc.vertices) if vx.pairs() and vx.pairs()[0][0] == b.index]
        blink = pmx_eyes.vertex_morphs(doc)["まばたき"]
        shift = [weight * sum(blink.get(v, (0.0, 0.0, 0.0))[c] for v in mine) / len(mine) for c in range(3)]
        lp, lr = fk.Pose(model, eye_optics.merge(*motion_list), [name]).at(frame)[name]
        rest = tuple(p + o + s for p, o, s in zip(b.position, b.tail["offset"], shift))
        return tuple(a + o for a, o in zip(lp, fk.rotate(lr, tuple(r - c for r, c in zip(rest, b.position)))))

    def test_a_light_the_formula_puts_just_under_a_lid_slides_below_its_edge(self):
        """まばたき 0.53 lowers the toy's lid to 17.088 and the gaze 15 degrees down leaves the upper lights up against
        it (formula A's lag): as the formula puts them they stand just over the lid's edge, in front of the lid (a
        light on the lid's skin, the MV's 167.2 seconds); slid back a little (under light.lid_slide) to where the lid
        leaves the iris uncovered, they stay below its edge and seen"""
        weight = 0.53
        model = self.lidded()
        g = gaze(90, {0: (0.0, -15.0)})
        result = eye_optics.optics(model, dance(), g, camera(1.0), eye_optics.merge_params(eye_optics.PARAMS, QUIET),
                                   face=self.face({0: weight, 90: weight}))
        edge = self.EDGE - self.DROP * weight
        for name in ("右HL２", "左HL２"):
            k = result.trace["lights"].index(name)
            for frame in (5, 45, 85):
                x, y, z = self.light_world(model, [dance(), g, result.motion], frame, name, weight)
                self.assertLess(y, edge - 0.005, (name, frame))
                self.assertTrue(0.0 <= result.trace["lid"][frame][k] < 1.0, (name, frame))   # slid back
                self.assertEqual(result.trace["sink"][frame][k], 0, (name, frame))          # at its drawn height
            self.assertGreater(result.report["light"]["lids"][name]["slid_frames"], 80)

    def test_a_light_the_formula_puts_well_under_a_lid_stays_under_it(self):
        """まばたき 0.6 lowers the lid further: the way out from under it is longer than light.lid_slide (a jump the
        viewer would see), so the lights stay where the formula puts them, brought down onto the iris behind the lid,
        which covers them as a reflection there would be covered"""
        model = self.lidded()
        g = gaze(90, {0: (0.0, -15.0)})
        result = eye_optics.optics(model, dance(), g, camera(1.0), eye_optics.merge_params(eye_optics.PARAMS, QUIET),
                                   face=self.face({0: 0.6, 90: 0.6}))
        edge = self.EDGE - self.DROP * 0.6
        for name in ("右HL２", "左HL２"):
            k = result.trace["lights"].index(name)
            self.assertEqual(result.trace["lid"][45][k], -1.0, name)
            self.assertEqual(result.trace["sink"][45][k], 1, name)
            x, y, z = self.light_world(model, [dance(), g, result.motion], 45, name, 0.6)
            self.assertGreater(y, edge)                                          # under the lid,
            self.assertGreater(z, self.LID_Z)                                    # behind it

    def test_a_lid_over_the_drawn_place_takes_the_light_down_under_it(self):
        """まばたき 1 lowers the lid over the upper lights' drawn places too, the whole way back covered: the lights
        stay where the formula puts them; at their drawn height they would stand in front of the lid, so they come
        down onto the iris, behind the lid, which covers them as it covers the iris"""
        model = self.lidded()
        result = eye_optics.optics(model, dance(), gaze(), camera(1.0), eye_optics.merge_params(eye_optics.PARAMS, QUIET),
                                   face=self.face({0: 1.0, 90: 1.0}))
        mdl = pmx.loads(model)
        iris = next(b for b in mdl.bones if b.name == "左目子")
        pose = fk.Pose(mdl, eye_optics.merge(dance(), gaze(), result.motion), ["左目子"])
        ip, iq = pose.at(45)["左目子"]
        on_iris = tuple(p + o for p, o in zip(ip, fk.rotate(iq, (0.0, 0.0, -0.96 - iris.position[2]))))
        normal = fk.rotate(iq, (0.0, 0.0, -1.0))
        k = result.trace["lights"].index("左HL２")
        self.assertEqual(result.trace["lid"][45][k], -1.0)                # covered all the way: where the formula puts it
        self.assertEqual(result.trace["sink"][45][k], 1)                  # brought down onto its iris
        spot = self.light_world(model, [dance(), gaze(), result.motion], 45, "左HL２", 1.0)
        height = sum((s - o) * c for s, o, c in zip(spot, on_iris, normal))
        self.assertLess(height, -0.96 - self.LID_Z)                       # behind the lid (0.04 in front of the iris)
        self.assertGreater(height, -0.01)
        self.assertGreater(result.report["light"]["lids"]["左HL２"]["onto_iris_frames"], 80)

class RideTest(unittest.TestCase):
    """each light rides on its iris at the height it was drawn at: its bone moves along the camera's line (keys with
    positions), so where the light shows does not change while it follows the iris' surface"""
    SLOPE = 0.4

    @classmethod
    def tilted(cls):
        """the toy with its irises tilted as Sour's Rin's are: the nasal side in front, z falling by SLOPE per unit
        toward the nose"""
        data, layout = toy_bytes(extra_bones=[("右人指３先", -1, HAND_REST)], iris_z=-0.96)
        doc = pmx_edit.loads(data)
        for side, s in (("右", -1.0), ("左", 1.0)):
            for v in layout["iris"][side]:
                x, y, z = doc.vertices[v].position()
                doc.vertices[v].head = struct.pack("<3f", x, y, z - cls.SLOPE * cls.nasal(x, s)) + doc.vertices[v].head[12:]
        pmx_eyes.build(doc, share=0.55)
        return pmx_edit.dumps(doc)

    @staticmethod
    def nasal(x, s):
        """how far toward the nose of the eye on side s (-1 right, +1 left) x lies from that iris' centre"""
        return (x - s * 0.507) * -s

    def height(self, model_bytes, motion_list, frame, name):
        """the light's height in front of the tilted iris (FK of the written keys, in the iris' rest frame)"""
        model = pmx.loads(model_bytes)
        b = next(x for x in model.bones if x.name == name)
        iris = next(x for x in model.bones if x.name == name[0] + "目子")
        pose = fk.Pose(model, eye_optics.merge(*motion_list), [name, iris.name])
        world = pose.at(frame)
        lp, lr = world[name]
        q = tuple(p + o for p, o in zip(lp, fk.rotate(lr, b.tail["offset"])))
        ip, ir = world[iris.name]
        r = tuple(a + o for a, o in zip(iris.position, fk.rotate(fk.conjugate(ir), tuple(c - d for c, d in zip(q, ip)))))
        s = -1.0 if name[0] == "右" else 1.0
        return (-0.96 - self.SLOPE * self.nasal(r[0], s)) - r[2]

    def test_a_sliding_light_keeps_its_height_over_a_tilted_iris(self):
        model = self.tilted()
        head = {0: (0.0, 0.0), 10: (0.0, 0.0), 40: (30.0, 0.0), 90: (30.0, 0.0)}
        d = dance(90, head=head)
        result = eye_optics.optics(model, d, gaze(), camera(1.0), eye_optics.merge_params(eye_optics.PARAMS, QUIET))
        moved = 0.0
        for name in ("右HL", "左HL"):                       # the lower lights (the upper ones lie over the pupil)
            k = result.trace["lights"].index(name)
            moved = max(moved, math.hypot(*(a - b for a, b in zip(result.trace["disc"][60][k], result.trace["disc"][5][k]))))
            rest = self.height(model, [d, gaze(), result.motion], 5, name)
            self.assertGreater(rest, 0.0)
            for f in (20, 30, 45, 60, 90):
                self.assertAlmostEqual(self.height(model, [d, gaze(), result.motion], f, name), rest, delta=0.004,
                                       msg=(name, f))
        self.assertGreater(moved, 0.2)                      # they did slide across their irises
        self.assertTrue(any(max(abs(c) for c in k.position) > 1e-3 for k in keys_of(result.motion, "左HL")))

    def test_riding_does_not_move_the_light_on_the_screen(self):
        model = self.tilted()
        head = {0: (0.0, 0.0), 10: (0.0, 0.0), 40: (30.0, 0.0), 90: (30.0, 0.0)}

        def go(ride):
            p = eye_optics.merge_params(eye_optics.PARAMS, {"light": {"ride": ride}, "pupil": {"unrest": {"amplitude": 0.0}}})
            return eye_optics.optics(model, dance(90, head=head), gaze(), camera(1.0), p)
        on, off = go(True), go(False)
        for f in (5, 30, 60):
            for k in range(4):
                a, b = on.trace["screen"][f][k], off.trace["screen"][f][k]
                self.assertAlmostEqual(a[0], b[0], delta=0.01)
                self.assertAlmostEqual(a[1], b[1], delta=0.01)
        self.assertFalse(any(max(abs(c) for c in k.position) > 0.0 for k in keys_of(off.motion, "左HL")))


class OverlapTest(unittest.TestCase):
    def test_face_keying_a_pupil_morph_is_refused(self):
        face = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("瞳大", 0, 0.5)])
        with self.assertRaises(ValueError) as ctx:
            eye_optics.check_overlaps({"face": face}, {"右目", "左目"}, {"瞳大", "瞳細", "HL消"})
        self.assertIn("瞳大", str(ctx.exception))

    def test_dance_frame_zero_eye_keys_are_fine(self):
        eye_optics.check_overlaps({"dance": dance()}, {"右目", "左目"}, {"瞳大"})


class GazeReportTest(unittest.TestCase):
    """the looks at a hand and the eye contacts come from tools/eye_gaze.py's --report of the same gaze VMD: a report
    of another gaze (its out_md5 differs) or one without the points the eyes aim at would put the vergence where she
    looks at nothing near, and is refused"""

    def test_the_looks_and_the_contacts_of_a_report(self):
        g = gaze()
        rep = gaze_report(look(30, 49), look(60, 69, aim=FAR, hand="左"), contacts=[(0, 20)], motion=g)
        got = eye_optics.gaze_looks(rep, vmd.dumps(g))
        self.assertEqual([(L["first"], L["last"], L["hand"]) for L in got["looks"]], [(30, 49, "右"), (60, 69, "左")])
        self.assertEqual(got["looks"][1]["aim"], [FAR] * 10)
        self.assertEqual(got["contacts"], [(0, 20)])

    def test_a_report_made_on_another_dance_is_refused(self):
        # the points aimed at are the hands of the dance the gaze was made on
        g = gaze()
        rep = gaze_report(look(30, 49), motion=g, on=dance(90))
        self.assertEqual(len(eye_optics.gaze_looks(rep, vmd.dumps(g), vmd.dumps(dance(90)))["looks"]), 1)
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(rep, vmd.dumps(g), vmd.dumps(dance(120)))
        self.assertIn("in_md5", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(gaze_report(look(30, 49), motion=g), vmd.dumps(g), vmd.dumps(dance(90)))
        self.assertIn("in_md5", str(ctx.exception))

    def test_a_report_of_another_gaze_is_refused(self):
        rep = gaze_report(look(30, 49), motion=gaze(90, {0: (5.0, 0.0)}))
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(rep, vmd.dumps(gaze()))
        self.assertIn("out_md5", str(ctx.exception))

    def test_a_report_without_the_md5_the_aims_or_the_looks_is_refused(self):
        older = gaze_report(look(30, 49))                                   # tools/eye_gaze.py of 03fae09 and before
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(older, vmd.dumps(gaze()))
        self.assertIn("out_md5", str(ctx.exception))
        aimless = gaze_report(look(30, 49), motion=gaze())
        del aimless["hands"]["list"][0]["aim"]
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(aimless, vmd.dumps(gaze()))
        self.assertIn("aim", str(ctx.exception))
        short = gaze_report(look(30, 49), motion=gaze())
        short["hands"]["list"][0]["aim"].pop()
        with self.assertRaises(ValueError):
            eye_optics.gaze_looks(short, vmd.dumps(gaze()))
        before_stage_6 = {"contacts": {"count": 0, "list": []}, "out_md5": hashlib.md5(vmd.dumps(gaze())).hexdigest()}
        with self.assertRaises(ValueError) as ctx:
            eye_optics.gaze_looks(before_stage_6, vmd.dumps(gaze()))
        self.assertIn("hands", str(ctx.exception))


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.paths = {}
        face = vmd.Motion(model_name="toy", morphs=[vmd.MorphKey("まばたき", 0, 0.0), vmd.MorphKey("まばたき", 40, 0.3)])
        # the camera 30 degrees off her gaze: no eye contact on the look at her hand
        for name, data in (("model.pmx", MODEL_BYTES), ("dance.vmd", vmd.dumps(dance())), ("gaze.vmd", vmd.dumps(gaze())),
                           ("camera.vmd", vmd.dumps(camera(2.5, yaw=30.0))), ("face.vmd", vmd.dumps(face))):
            path = os.path.join(self.tmp, name)
            with open(path, "wb") as f:
                f.write(data)
            self.paths[name] = path
        look_path = os.path.join(self.tmp, "look.json")
        with open(look_path, "w", encoding="utf-8") as f:
            json.dump({"flares": [1.0]}, f)
        self.paths["look"] = look_path
        # tools/eye_gaze.py's report of gaze.vmd: she looks at her hand, 30 cm before her eyes, on frames 30 to 49
        for name, rep in (("gaze_report.json", gaze_report(look(30, 49), motion=gaze(), on=dance())),
                          ("other_report.json", gaze_report(look(30, 49), motion=gaze(90, {0: (5.0, 0.0)}), on=dance())),
                          ("other_dance.json", gaze_report(look(30, 49), motion=gaze(), on=dance(120)))):
            path = os.path.join(self.tmp, name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rep, f)
            self.paths[name] = path

    def args(self, *extra, face=True, report="gaze_report.json"):
        p = self.paths
        return ([p["model.pmx"], p["dance.vmd"], p["gaze.vmd"], p["camera.vmd"], os.path.join(self.tmp, "out.vmd")]
                + (["--face", p["face.vmd"]] if face else []) + (["--gaze-report", p[report]] if report else [])
                + list(extra))

    def failure(self, argv):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = eye_optics.main(argv)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out.vmd")))
        return json.loads(printed.getvalue())["error"]["message"]

    def test_refuses_to_go_without_the_face_when_its_morphs_move_the_lights(self):
        """the toy's まばたき moves its upper lights (as Sour's Rin's closing morphs do): without the face VMD the
        lights would be kept off the lids and on the iris for a face that is not the one loaded with them"""
        self.assertIn("--face", self.failure(self.args(face=False)))

    def test_refuses_to_go_without_the_gaze_report_unless_told_the_eyes_stay_parallel(self):
        """where she looks at her hand is the gaze's plan (tools/eye_gaze.py --report): without it the eyes would not
        come together where she looks at one, and nothing would say so"""
        self.assertIn("--gaze-report", self.failure(self.args(report=None)))
        report = os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = eye_optics.main(self.args("--no-vergence", "--report", report, report=None))
        self.assertEqual(code, 0, printed.getvalue())
        motion = vmd.load(os.path.join(self.tmp, "out.vmd"))
        for k in keys_of(motion, "右目") + keys_of(motion, "左目"):
            self.assertAlmostEqual(yaw_of(fk.applied(k.rotation)), 0.0, 9)
        with open(report, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["vergence"]["source"], "none")
        os.remove(os.path.join(self.tmp, "out.vmd"))
        self.assertIn("--no-vergence", self.failure(self.args("--no-vergence")))      # not both

    def test_refuses_the_report_of_another_gaze(self):
        self.assertIn("out_md5", self.failure(self.args(report="other_report.json")))

    def test_refuses_the_report_of_a_gaze_made_on_another_dance(self):
        self.assertIn("in_md5", self.failure(self.args(report="other_dance.json")))

    def test_writes_the_motion_and_the_report(self):
        report = os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = eye_optics.main(self.args("--look", self.paths["look"], "--report", report))
        self.assertEqual(code, 0, printed.getvalue())
        self.assertTrue(json.loads(printed.getvalue())["ok"])
        motion = vmd.load(os.path.join(self.tmp, "out.vmd"))
        self.assertTrue(motion.bones and motion.morphs)
        with open(report, encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["pupil"]["flares_s"], [1.0])
        self.assertEqual((rep["vergence"]["source"], rep["vergence"]["looks"]), ("gaze report", 1))
        self.assertEqual(rep["in"]["gaze_report"], os.path.abspath(self.paths["gaze_report.json"]))
        self.assertGreater(max(yaw_of(fk.applied(k.rotation)) for k in keys_of(motion, "右目")), 5.0)

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
            code = eye_optics.main(self.args()[:4] + [self.paths["gaze.vmd"], "--face", self.paths["face.vmd"]])
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


# ---- the MV itself ----------------------------------------------------------------------------

SONG = os.environ.get("EYE_OPTICS_SONG")
SONG_KEYS = ("model", "dance", "gaze", "gaze_report", "face", "camera")
BOX = ((-1.4, 1.4), (16.2, 18.4), (-1.8, 0.4))       # about Sour's Rin's eyes: brows, lids, cheeks, fringe
LIDS = ("face", "目", "hair")
# where the stage 5 review's ray check of every frame found a light on a lid (POKE) or seen off the iris
POKED = [723, 2393, 4729, 4742, 5007, 5008, 5016, 5017, 5018, 5019, 5020, 5021, 5022, 6907]
OFF_IRIS = [1371, 1372, 1373, 1374, 4323, 4324, 4325, 4326, 4327, 6424, 6425, 6426, 6427, 6428, 6429, 6430, 6435, 6436,
            6437, 6748, 6749, 6750, 7617]


def song_paths():
    """the MV's inputs named by EYE_OPTICS_SONG (a JSON {"model", "dance", "gaze", "gaze_report", "face", "camera"}):
    SkipTest, with the reason, when it is not set; a set variable naming files that are not there fails instead"""
    if not SONG:
        raise unittest.SkipTest("EYE_OPTICS_SONG is not set: it names a JSON of the MV's inputs (model, dance, gaze, "
                                "gaze_report, face, camera), on hinata "
                                "C:/work/hibikase/stage6/eye_optics_v2/song_inputs.json")
    with open(SONG, encoding="utf-8") as f:
        paths = json.load(f)
    missing = ["%s %s" % (k, paths.get(k)) for k in SONG_KEYS if not paths.get(k) or not os.path.isfile(paths[k])]
    if missing:
        raise AssertionError("EYE_OPTICS_SONG (%s) names files that are not there: %s" % (SONG, "; ".join(missing)))
    return paths


def material_table(doc):
    """[(name, alpha, first face, face count)] of a pmx_edit document's materials"""
    from mmd_cli.formats.pmx import _Reader
    r = _Reader(doc.middle, doc.encoding)
    r.skip(r.i32() * doc.sizes["vertex"])
    for _ in range(r.i32()):
        r.text()
    out, start, texture = [], 0, doc.sizes["texture"]
    for _ in range(r.i32()):
        name = r.text()
        r.text()
        alpha = struct.unpack_from("<4f", doc.middle, r.pos)[3]
        r.skip(65 + 2 * texture)
        r.u8()
        if r.u8():
            r.u8()
        else:
            r.skip(texture)
        r.text()
        count = r.i32()
        out.append((name, alpha, start // 3, count // 3))
        start += count
    return out


class RayCheck:
    """where MMD shows each light quad of Sour's Rin against everything about her eyes, at a frame: the eye region
    skinned linearly by the bones' FK with the face's and the motion's morphs (physics left out), and rays from the
    camera (Moller and Trumbore).  A light pokes when nothing visible lies in front of its centre while the lids, the
    face or the hair cover the iris' rim plane behind it; it is off the iris when seen and its centre's ray meets no
    triangle of the iris.  (The stage 5 ray check, tools-independent: it reads only the files MMD reads.)"""

    def __init__(self, model_bytes, motion, morph_motions, camera):
        import numpy as np
        self.np = np
        doc = pmx_edit.loads(model_bytes)
        self.model = model = pmx.loads(model_bytes)
        self.mats = mats = material_table(doc)
        faces = np.array(pmx_eyes.middle_tables(doc)[0], dtype=np.int64).reshape(-1, 3)
        face_mat = np.zeros(len(faces), dtype=np.int64)
        for k, (_, _, first, count) in enumerate(mats):
            face_mat[first:first + count] = k
        rest = np.array([v.position() for v in doc.vertices], dtype=float)
        inside = np.all([(rest[:, c] >= BOX[c][0]) & (rest[:, c] <= BOX[c][1]) for c in range(3)], axis=0)
        keep = np.all(inside[faces], axis=1)
        self.sel = np.nonzero(inside)[0]
        local = {v: k for k, v in enumerate(self.sel)}
        bones, weights = [], []
        for v in self.sel:
            pairs = [(b, w) for b, w in doc.vertices[v].pairs() if w > 0.0][:4]
            total = sum(w for _, w in pairs) or 1.0
            bones.append([b for b, _ in pairs] + [0] * (4 - len(pairs)))
            weights.append([w / total for _, w in pairs] + [0.0] * (4 - len(pairs)))
        self.bones, self.weights = np.array(bones, dtype=np.int64), np.array(weights, dtype=float)
        self.rest = rest[self.sel]
        self.rest_bones = np.array([b.position for b in model.bones], dtype=float)
        keyed = {k.name for m in morph_motions for k in m.morphs}
        self.morphs = {}
        for name, offsets in pmx_eyes.vertex_morphs(doc).items():
            if name in keyed:
                arr = np.zeros_like(self.rest)
                for v, o in offsets.items():
                    if v in local:
                        arr[local[v]] = o
                if np.abs(arr).max() > 0.0:
                    self.morphs[name] = arr
        self.morph_motions = morph_motions
        visible = np.array([m[1] > 0.0 for m in mats])
        hl = next(k for k, m in enumerate(mats) if m[0] == "HL")
        iris = next(k for k, m in enumerate(mats) if m[0] == "瞳")
        to_local = np.vectorize(lambda v: local.get(int(v), -1))
        self.occluders = to_local(faces[keep & visible[face_mat] & (face_mat != hl)])
        self.lids = to_local(faces[keep & np.isin(face_mat, [k for k, m in enumerate(mats) if m[0] in LIDS])])
        self.iris_tris = to_local(faces[keep & (face_mat == iris)])
        self.quads = []
        for q in pmx_eyes.components([tuple(t) for t in faces[face_mat == hl]]):
            r0 = rest[q].mean(axis=0)
            self.quads.append((("R" if r0[0] < 0 else "L") + ("U" if r0[1] > 17.15 else "D"), [local[v] for v in q]))
        eye_idx, _ = pmx_eyes.find_eyes(doc)
        self.discs = {}
        iris_v = sorted({int(v) for t in faces[face_mat == iris] for v in t})
        for e in eye_idx:
            mine = [v for v in iris_v if pmx_eyes._eye_of(doc, v, eye_idx) == e]
            bone = max(doc.vertices[mine[0]].pairs(), key=lambda bw: bw[1])[0]
            pts = rest[mine]
            centre = np.array([(pts[:, 0].max() + pts[:, 0].min()) / 2, (pts[:, 1].max() + pts[:, 1].min()) / 2,
                               pts[:, 2].min()])
            self.discs["R" if centre[0] < 0 else "L"] = (bone, centre)
        self.pose = fk.Pose(model, motion, [b.name for b in model.bones])
        self.cams = fk.camera_keys(camera)

    def _rotate(self, q, v):
        np = self.np
        u, w = q[:, :3], q[:, 3:4]
        t = 2.0 * np.cross(u, v)
        return v + w * t + np.cross(u, t)

    def _hits(self, origin, target, tri):
        """the ray parameter (target at 1) of each triangle's hit, inf where it misses"""
        np = self.np
        d = target - origin
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        p = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = origin - tri[:, 0]
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        v = np.einsum("j,ij->i", d, q) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        return np.where(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9), t, np.inf)

    def frame(self, frame):
        """[(the quad's tag, seen, poke, off the iris)] at `frame`"""
        np = self.np
        x = self.rest.copy()
        for name, arr in self.morphs.items():
            w = 0.0
            for m in self.morph_motions:                      # a later motion's keys on the morph win
                keys = sorted((k for k in m.morphs if k.name == name), key=lambda k: k.frame)
                if keys:
                    before = [k for k in keys if k.frame <= frame]
                    after = [k for k in keys if k.frame > frame]
                    if not before:
                        w = keys[0].weight
                    elif not after or before[-1].frame == frame:
                        w = before[-1].weight
                    else:
                        a, b = before[-1], after[0]
                        w = a.weight + (b.weight - a.weight) * (frame - a.frame) / float(b.frame - a.frame)
            if w:
                x += w * arr
        world = self.pose.world(frame)
        P = np.array([world[i][0] for i in range(len(self.model.bones))], dtype=float)
        Q = np.array([world[i][1] for i in range(len(self.model.bones))], dtype=float)
        X = np.zeros_like(x)
        for k in range(4):
            b, w = self.bones[:, k], self.weights[:, k]
            X += w[:, None] * (P[b] + self._rotate(Q[b], x - self.rest_bones[b]))
        cam = np.array(fk.camera_position(fk.camera_at(self.cams, frame)), dtype=float)
        occluders, lids, iris = X[self.occluders], X[self.lids], X[self.iris_tris]
        out = []
        for tag, q in self.quads:
            centre = X[q].mean(axis=0)
            seen = not (self._hits(cam, centre, occluders) < 1.0 - 1e-6).any()
            bone, dc = self.discs[tag[0]]
            C = P[bone] + self._rotate(Q[bone:bone + 1], (dc - self.rest_bones[bone])[None])[0]
            normal = self._rotate(Q[bone:bone + 1], np.array([[0.0, 0.0, -1.0]]))[0]
            d = centre - cam
            hit = cam + d * float(np.dot(C - cam, normal) / np.dot(d, normal))
            poke = seen and bool((self._hits(cam, hit, lids) < 1.0 - 1e-6).any())
            off = seen and not np.isfinite(self._hits(cam, centre, iris)).any()
            out.append((tag, seen, poke, off))
        return out


class SongTest(unittest.TestCase):
    """the MV (hinata's inputs, named by EYE_OPTICS_SONG; skipped with the reason where it is not set): the 52 seconds'
    look at the fingers converges, the vergence is on the gaze's looks at a hand and never on the camera nor away from
    the looks, and no light shows on a lid or off the iris where the stage 5 review's ray check of every frame found
    them"""

    @classmethod
    def setUpClass(cls):
        paths = song_paths()
        with open(paths["model"], "rb") as f:
            cls.model_bytes = f.read()
        cls.dance, cls.face, cls.camera = (vmd.load(paths[k]) for k in ("dance", "face", "camera"))
        with open(paths["gaze"], "rb") as f:
            data = f.read()
        cls.gaze = vmd.loads(data)
        with open(paths["gaze_report"], encoding="utf-8") as f:
            cls.looks = eye_optics.gaze_looks(json.load(f), data)
        cls.result = eye_optics.optics(cls.model_bytes, cls.dance, cls.gaze, cls.camera,
                                       eye_optics.merge_params(eye_optics.PARAMS, {}), face=cls.face, looks=cls.looks)

    def test_the_52_seconds_look_at_the_fingers_converges_3_degrees_or_more(self):
        """the coordinator's sample (1567): the left hand's raised finger before her face, looked at by the gaze on
        1561 to 1569 (0.3 s): from its third frame on (the vergence takes 0.24 s, rising from the saccade onto the
        finger) and at 1567 the eyes are 3 degrees or more each"""
        look = [L for L in self.looks["looks"] if L["first"] <= 1567 <= L["last"]]
        self.assertEqual(len(look), 1, self.looks["looks"])
        verg = self.result.trace["vergence"]
        self.assertGreaterEqual(verg[1567], 3.0)
        self.assertGreaterEqual(min(verg[look[0]["first"] + 2:look[0]["last"] + 1]), 3.0, verg[1556:1580])

    def test_the_vergence_is_on_the_looks_and_never_on_the_camera(self):
        rep = self.result.report["vergence"]
        self.assertEqual(rep["source"], "gaze report")
        self.assertGreaterEqual(rep["share"]["hand"], 0.5)
        self.assertEqual(rep["camera_max_degrees"], 0.0)
        self.assertLessEqual(rep["step"]["max"], 2.0)

    def test_the_eyes_are_parallel_away_from_the_looks(self):
        """stage 5's geometric looks put 96 % of the vergence of the MV v8 outside the gaze's looks, up to 11.6 degrees
        an eye at 41, 130, 135, 153 and 249 s where her hand covers or nears her face (review gaze-v8 4.2)"""
        verg = self.result.trace["vergence"]
        near = set()
        for L in self.looks["looks"]:
            near.update(range(L["first"] - 3, L["last"] + 15))
        away = [(i, v) for i, v in enumerate(verg) if i not in near and v > 0.0]
        self.assertEqual(away, [])

    def test_no_light_on_a_lid_or_off_the_iris_where_the_review_found_them(self):
        check = RayCheck(self.model_bytes, eye_optics.merge(self.dance, self.gaze, self.result.motion),
                         [self.face, self.result.motion], self.camera)
        found = []
        for frame in POKED + OFF_IRIS:
            for tag, seen, poke, off in check.frame(frame):
                if poke or off:
                    found.append((frame, tag, "poke" if poke else "off the iris"))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
