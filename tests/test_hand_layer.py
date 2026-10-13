"""tools/hand_layer.py: the hands and the fingers made anatomical (the joints read in the hand's own frame, the range of
motion, the coupling of the joints and of the fingers, the relaxed hand and the fingers' passive lag), baked onto a
dance."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_pmx import APPEND_ROTATE, FIXED_AXIS, NORMAL, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("hand_layer", os.path.join(ROOT, "tools", "hand_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hand_layer = load_tool()
LAST = 60

# Sour's Rin's rest positions (model units) of the left arm and hand (White.pmx); the right side is the mirror image
LEFT = [("肩P", "上半身2", (0.23, 15.393, -0.222), {}),
        ("肩", "肩P", (0.23, 15.393, -0.222), {}),
        ("肩C", "肩", (0.911, 15.277, -0.248), {"flags": NORMAL | APPEND_ROTATE, "append": ("肩P", -1.0)}),
        ("腕", "肩C", (0.911, 15.277, -0.248), {}),
        ("腕捩", "腕", (1.909, 14.505, -0.259), {"flags": NORMAL | FIXED_AXIS, "axis": (0.7908, -0.6120, -0.0086)}),
        ("ひじ", "腕捩", (2.907, 13.732, -0.27), {}),
        ("手捩", "ひじ", (3.78, 13.071, -0.253), {"flags": NORMAL | FIXED_AXIS, "axis": (0.7970, -0.6038, 0.0151)}),
        ("手首", "手捩", (4.652, 12.41, -0.237), {}),
        ("親指０", "手首", (4.772, 12.225, -0.443), {"flags": NORMAL | TRANSLATE}),
        ("親指１", "親指０", (5.008, 11.945, -0.574), {}),
        ("親指２", "親指１", (5.11, 11.703, -0.637), {}),
        ("親指２先", "親指２", (5.296, 11.49, -0.789), {}),
        ("人指０", "手首", (4.854, 12.253, -0.387), {}),
        ("人指１", "人指０", (5.375, 11.884, -0.436), {}),
        ("人指２", "人指１", (5.64, 11.687, -0.43), {}),
        ("人指３", "人指２", (5.777, 11.554, -0.421), {}),
        ("人指３先", "人指３", (5.946, 11.456, -0.418), {}),
        ("中指０", "手首", (4.932, 12.265, -0.279), {}),
        ("中指１", "中指０", (5.41, 11.935, -0.261), {}),
        ("中指２", "中指１", (5.714, 11.691, -0.264), {}),
        ("中指３", "中指２", (5.87, 11.538, -0.264), {}),
        ("中指３先", "中指３", (6.053, 11.425, -0.263), {}),
        ("薬指０", "手首", (4.912, 12.26, -0.158), {}),
        ("薬指１", "薬指０", (5.387, 11.944, -0.1), {}),
        ("薬指２", "薬指１", (5.664, 11.723, -0.105), {}),
        ("薬指３", "薬指２", (5.795, 11.589, -0.111), {}),
        ("薬指３先", "薬指３", (5.973, 11.477, -0.127), {}),
        ("小指０", "手首", (4.892, 12.262, -0.038), {}),
        ("小指１", "小指０", (5.332, 11.951, 0.038), {}),
        ("小指２", "小指１", (5.544, 11.778, 0.03), {}),
        ("小指３", "小指２", (5.659, 11.661, 0.02), {}),
        ("小指３先", "小指３", (5.802, 11.57, 0.007), {})]
# the pulp side of the left thumb's distal phalanx, as the mesh of White.pmx gives it (the thickness axis of the
# vertices that hang on 左親指２, audit/nail_axes.py); the right one is its mirror image
THUMB_PULP_LEFT = (0.121, -0.533, 0.837)


def mirrored(kw):
    out = dict(kw)
    if "axis" in out:
        out["axis"] = (-out["axis"][0], out["axis"][1], out["axis"][2])
    return out


def model_bytes():
    w = Writer(bone=2)
    bones = [("全ての親", None, (0.0, 0.0, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("センター", "全ての親", (0.0, 7.847, 0.0), {"flags": NORMAL | TRANSLATE}),
             ("腰", "センター", (0.0, 11.726, 0.255), {}),
             ("下半身", "腰", (0.0, 12.225, -0.649), {}),
             ("上半身", "腰", (0.0, 12.225, -0.649), {}),
             ("上半身2", "上半身", (0.0, 13.798, -0.678), {}),
             ("首", "上半身2", (0.0, 15.646, -0.134), {}),
             ("頭", "首", (0.0, 16.243, 0.0), {}),
             ("両目", "頭", (0.0, 17.214, -0.562), {})]
    for side, sx in (("左", 1.0), ("右", -1.0)):
        for name, parent, (x, y, z), kw in LEFT:
            parent = parent if parent in ("上半身2",) else side + parent
            kw = dict(kw) if sx > 0 else mirrored(kw)
            if "append" in kw:
                kw["append"] = (side + kw["append"][0], kw["append"][1])
            bones.append((side + name, parent, (sx * x, y, z), kw))
    index = {name: i for i, (name, _, _, _) in enumerate(bones)}
    built = []
    for name, parent, position, kw in bones:
        kw = dict(kw)
        if "append" in kw:
            kw["append"] = (index[kw["append"][0]], kw["append"][1])
        built.append(w.bone(name, parent=-1 if parent is None else index[parent], position=position, **kw))
    return w.build(name="rin-hand", bones=built)


MODEL = pmx.loads(model_bytes())
PULP = {"左": np.array(THUMB_PULP_LEFT), "右": np.array(THUMB_PULP_LEFT) * np.array([-1.0, 1.0, 1.0])}
HANDS = hand_layer.hand_model(MODEL, pulp=PULP)
POS = {b.name: np.array(b.position, dtype=float) for b in MODEL.bones}


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def axis_angle(axis, degrees):
    a = unit(axis)
    h = math.radians(degrees) / 2.0
    return np.array([a[0] * math.sin(h), a[1] * math.sin(h), a[2] * math.sin(h), math.cos(h)])


def rotate(q, v):
    return np.array(fk.rotate(tuple(q), tuple(v)))


def palm_normal(side):
    """the palm's side of the hand at rest, worked out here on its own: perpendicular to the hand's long axis and to the
    line across the knuckles, on the side the fingers bend to (the left hand of the A pose has its palm down)"""
    d_h = unit(POS[side + "中指１"] - POS[side + "手首"])
    across = POS[side + "人指１"] - POS[side + "小指１"]
    n = unit(np.cross(d_h, across))
    return n if n[1] < 0 else -n


class ReadingTest(unittest.TestCase):
    """the joints of the hand read in the hand's own frame: flexion toward the palm (the pulp for the thumb), the side
    angle toward the thumb (the index for the thumb's joints), the twist about the segment"""

    def joint(self, side, bone):
        return next(j for j in HANDS[side].joints if j.bone == side + bone)

    def test_every_finger_has_three_joints_and_the_thumb_three(self):
        for side in ("左", "右"):
            kinds = [(j.finger, j.kind) for j in HANDS[side].joints]
            for f in ("人指", "中指", "薬指", "小指"):
                self.assertEqual([k for g, k in kinds if g == f], ["mp", "pip", "dip"])
            self.assertEqual([k for g, k in kinds if g == "親指"], ["cmc", "mp", "ip"])

    def test_the_rest_pose_reads_the_bend_of_the_bones(self):
        # the middle finger's PIP at rest: the angle between the proximal and the middle phalanx, toward the palm
        n = palm_normal("左")
        a = unit(POS["左中指２"] - POS["左中指１"])
        b = unit(POS["左中指３"] - POS["左中指２"])
        expected = math.degrees(math.acos(float(a @ b))) * np.sign(b @ n - (a @ n) * (a @ b))
        j = self.joint("左", "中指２")
        flex, side, tw = hand_layer.read_joint(j, np.array([[0.0, 0.0, 0.0, 1.0]]))
        self.assertAlmostEqual(math.hypot(float(flex[0]), float(side[0])), abs(expected), places=3)
        self.assertAlmostEqual(float(flex[0]), j.rest[0], places=6)
        self.assertAlmostEqual(float(tw[0]), 0.0, places=6)

    def test_a_turn_about_the_hinge_bends_toward_the_palm(self):
        for side in ("左", "右"):
            n = palm_normal(side)
            for bone in ("人指２", "中指３", "小指１"):
                j = self.joint(side, bone)
                q = axis_angle(j.axis, 30.0)
                flex, s, _ = hand_layer.read_joint(j, q[None])
                self.assertAlmostEqual(float(flex[0]) - j.rest[0], 30.0, places=4, msg=side + bone)
                self.assertAlmostEqual(float(s[0]), j.rest[1], places=4)
                tip = rotate(q, j.d)
                self.assertGreater(float(tip @ n), float(j.d @ n), side + bone)       # the segment came toward the palm

    def test_the_side_angle_is_positive_toward_the_thumb_on_both_hands(self):
        for side in ("左", "右"):
            j = self.joint(side, "中指１")
            thumb_side = unit(POS[side + "人指１"] - POS[side + "小指１"])
            # turn about the palm normal both ways: the finger moves toward the thumb or away from it
            for deg in (12.0, -12.0):
                q = axis_angle(palm_normal(side), deg)
                moved = rotate(q, j.d) - j.d
                _, s, _ = hand_layer.read_joint(j, q[None])
                if moved @ thumb_side > 0:
                    self.assertGreater(float(s[0]) - j.rest[1], 5.0)
                else:
                    self.assertLess(float(s[0]) - j.rest[1], -5.0)

    def test_compose_gives_back_the_rotation_read(self):
        rng = np.random.default_rng(3)
        for side in ("左", "右"):
            for j in HANDS[side].joints:
                axes = rng.normal(size=(40, 3))
                angles = rng.uniform(-70.0, 70.0, 40)
                q = np.array([axis_angle(a, d) for a, d in zip(axes, angles)])
                flex, s, tw = hand_layer.read_joint(j, q)
                back = hand_layer.compose_joint(j, flex, s, tw)
                back = back * np.sign(np.sum(back * q, axis=1))[:, None]          # q and -q are one rotation
                self.assertLess(np.abs(back - q).max(), 1e-9, j.bone)

    def test_the_right_hand_reads_its_mirror_pose_like_the_left(self):
        rng = np.random.default_rng(5)
        for bone in ("人指１", "薬指２", "小指３", "親指０", "親指１", "親指２"):
            jl, jr = self.joint("左", bone), self.joint("右", bone)
            for _ in range(10):
                q = axis_angle(rng.normal(size=3), rng.uniform(-50, 50))
                qm = np.array([q[0], -q[1], -q[2], q[3]])         # the mirror image in X
                a = [float(v[0]) for v in hand_layer.read_joint(jl, q[None])]
                b = [float(v[0]) for v in hand_layer.read_joint(jr, qm[None])]
                self.assertAlmostEqual(a[0], b[0], places=6, msg=bone)
                self.assertAlmostEqual(a[1], b[1], places=6, msg=bone)
                self.assertAlmostEqual(abs(a[2]), abs(b[2]), places=6, msg=bone)

    def test_the_thumb_bends_toward_its_pulp(self):
        for side in ("左", "右"):
            j = self.joint(side, "親指２")
            q = axis_angle(j.axis, 40.0)
            flex, _, _ = hand_layer.read_joint(j, q[None])
            self.assertAlmostEqual(float(flex[0]) - j.rest[0], 40.0, places=4)
            self.assertGreater(float(rotate(q, j.d) @ PULP[side]), float(j.d @ PULP[side]))

    def test_the_thumb_metacarpal_reads_radial_and_palmar_abduction(self):
        # JOA: radial abduction in the palm's plane from the index metacarpal, palmar abduction out of it
        for side in ("左", "右"):
            j = self.joint(side, "親指０")
            n = palm_normal(side)
            index_mc = unit(POS[side + "人指１"] - POS[side + "人指０"])
            t = unit(POS[side + "親指１"] - POS[side + "親指０"])
            palmar = math.degrees(math.asin(float(t @ n)))
            in_plane = unit(t - (t @ n) * n)
            ref = unit(index_mc - (index_mc @ n) * n)
            radial = math.degrees(math.acos(float(in_plane @ ref)))
            rad, pal, _ = hand_layer.read_joint(j, np.array([[0.0, 0.0, 0.0, 1.0]]))
            self.assertAlmostEqual(float(rad[0]), radial, places=3)
            self.assertAlmostEqual(float(pal[0]), palmar, places=3)
            # tilt the metacarpal toward the palm: palmar abduction grows
            q = axis_angle(np.cross(t, n), 20.0)
            _, pal2, _ = hand_layer.read_joint(j, q[None])
            self.assertAlmostEqual(float(pal2[0]) - palmar, 20.0, delta=0.5)


class PassiveTest(unittest.TestCase):
    """the fingers' passive lag: delta'' + 2 zeta omega delta' + omega^2 delta = forcing, from rest at frame 0"""

    W = 2.0 * math.pi * 6.0

    def run_(self, forcing, omega=None, zeta=0.5):
        forcing = np.asarray(forcing, dtype=float)
        n = forcing.shape[1]
        omega = np.full(n, self.W if omega is None else omega)
        return hand_layer.passive_response(forcing, omega, np.full(n, zeta), fps=30.0)

    def test_without_forcing_nothing_moves(self):
        d = self.run_(np.zeros((90, 3)))
        self.assertEqual(float(np.abs(d).max()), 0.0)

    def test_a_steady_forcing_settles_at_its_static_deflection(self):
        d = self.run_(np.full((150, 1), 100.0), zeta=0.7)
        self.assertAlmostEqual(float(d[-1, 0]), 100.0 / self.W ** 2, delta=0.01 * 100.0 / self.W ** 2)

    def test_after_a_push_the_finger_overshoots_and_settles(self):
        forcing = np.zeros((120, 1))
        forcing[10:16, 0] = -300.0                           # the hand brakes for 0.2 s
        d = self.run_(forcing, zeta=0.4)[:, 0]
        peak = int(np.argmin(d[:30]))
        self.assertLess(d[peak], -0.05)
        self.assertGreater(d[peak:peak + 15].max(), 0.0)     # it swings past its rest
        settle = 16 + int(math.ceil(4.0 / (0.4 * self.W) * 30.0)) + 2
        self.assertLess(np.abs(d[settle:]).max(), 0.05 * abs(d[peak]))

    def test_more_damping_overshoots_less(self):
        forcing = np.zeros((120, 1))
        forcing[10:16, 0] = -300.0
        light = self.run_(forcing, zeta=0.3)[:, 0]
        heavy = self.run_(forcing, zeta=0.9)[:, 0]
        self.assertGreater(light[16:].max(), heavy[16:].max())

    def test_a_stiff_joint_stays_stable_and_small(self):
        forcing = np.random.default_rng(2).normal(0.0, 200.0, (300, 2))
        d = self.run_(forcing, omega=2.0 * math.pi * 20.0, zeta=0.7)
        self.assertTrue(np.all(np.isfinite(d)))
        self.assertLess(np.abs(d).max(), 0.2)

    def test_a_very_stiff_well_damped_joint_stays_stable(self):
        # a small thumb held stiff: about 50 Hz at a damping ratio of 0.85 (explicit steps of 1/240 s diverge there)
        w = 2.0 * math.pi * 55.0
        forcing = np.random.default_rng(4).normal(0.0, 300.0, (600, 2))
        d = self.run_(forcing, omega=w, zeta=0.85)
        self.assertTrue(np.all(np.isfinite(d)))
        self.assertLess(np.abs(d).max(), 3.0 * 900.0 / w ** 2)
        step = self.run_(np.full((200, 1), 500.0), omega=w, zeta=0.85)
        self.assertAlmostEqual(float(step[-1, 0]), 500.0 / w ** 2, delta=0.02 * 500.0 / w ** 2)


class ForcingTest(unittest.TestCase):
    """what drives the lag: the hand's angular acceleration about the joint's axis, the joint's linear acceleration (and
    gravity) on the part beyond it, both in the world"""

    def test_the_hand_turning_faster_toward_flexion_leaves_the_finger_behind(self):
        F = 40
        t = np.arange(F) / 30.0
        axis = np.array([0.0, 0.0, 1.0])
        ang = 0.5 * 50.0 * t ** 2                             # 50 rad/s^2 about +Z
        R = np.stack([axis_angle(axis, math.degrees(a)) for a in ang])
        alpha = hand_layer.angular_acceleration(R, 30.0)
        self.assertAlmostEqual(float(np.median(alpha[2:-2] @ axis)), 50.0, delta=0.5)
        acc = np.zeros((F, 3))
        f = hand_layer.joint_forcing(alpha, acc, np.tile(axis, (F, 1)), np.tile([1.0, 0.0, 0.0], (F, 1)), r=0.03,
                                     rho=0.02, gravity=False)
        self.assertLess(float(np.median(f[2:-2])), -40.0)

    def test_a_joint_pushed_toward_the_palm_bends_the_finger_back(self):
        F = 20
        e = np.tile([1.0, 0.0, 0.0], (F, 1))                  # the finger along +X, the palm toward +Y: axis +Z
        axis = np.tile([0.0, 0.0, 1.0], (F, 1))
        acc = np.tile([0.0, 20.0, 0.0], (F, 1))               # the knuckle accelerates toward the palm
        f = hand_layer.joint_forcing(np.zeros((F, 3)), acc, axis, e, r=0.03, rho=0.02, gravity=False)
        self.assertAlmostEqual(float(f[0]), -20.0 * 0.03 / (0.03 ** 2 + 0.02 ** 2), places=6)

    def test_gravity_lets_a_relaxed_finger_droop(self):
        F = 5
        e = np.tile([1.0, 0.0, 0.0], (F, 1))
        axis = np.tile([0.0, 0.0, 1.0], (F, 1))              # flexion toward +Y
        still = np.zeros((F, 3))
        palm_up = hand_layer.joint_forcing(still, still, axis, e, r=0.03, rho=0.02, gravity=True)
        palm_down = hand_layer.joint_forcing(still, still, -axis, e, r=0.03, rho=0.02, gravity=True)
        self.assertLess(float(palm_up[0]), 0.0)               # palm up: the finger droops back, away from the palm
        self.assertGreater(float(palm_down[0]), 0.0)          # palm down: it droops into the palm


# ---- the layer on made-up dances ---------------------------------------------------------------------------------

def key(name, frame, q=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0)):
    return vmd.BoneKey(name, frame, tuple(position), fk.stored(tuple(float(v) for v in q)))


def untouched_keys(last=LAST, centre=True):
    """keys of bones the layer must not touch; centre moves the body (センター) between frames 0 and 30"""
    moved = (0.3, -0.4, 0.1) if centre else (0.0, -0.2, 0.1)
    return [key("センター", 0, position=(0.0, -0.2, 0.1)), key("センター", 30, position=moved),
            key("センター", last, position=moved),
            key("下半身", 0, axis_angle((1, 0, 0), 5.0)), key("下半身", last, axis_angle((1, 0, 0), 5.0)),
            key("左腕", 0, axis_angle((0, 0, 1), 20.0)), key("左腕", last, axis_angle((0, 0, 1), 20.0))]


def joint_of(side, bone):
    return next(j for j in HANDS[side].joints if j.bone == side + bone)


def flexed(side, bone, flex, side_deg=0.0, twist_deg=0.0):
    """the local rotation of a joint `flex` degrees from its rest bend (side and twist likewise; the thumb's CMC reads
    its angles absolutely)"""
    j = joint_of(side, bone)
    r0, r1 = (0.0, 0.0) if j.kind == "cmc" else j.rest
    return hand_layer.compose_joint(j, np.array([r0 + flex]), np.array([r1 + side_deg]), np.array([twist_deg]))[0]


SHAPES = {   # rest-relative flexion (MP, PIP, DIP) per long finger
    "open": {f: (0.0, 0.0, 0.0) for f in hand_layer.LONG},
    "fist": {f: (80.0, 95.0, 70.0) for f in hand_layer.LONG},
    "point": {"人指": (0.0, 0.0, 0.0), "中指": (80.0, 95.0, 70.0), "薬指": (80.0, 95.0, 70.0), "小指": (80.0, 95.0, 70.0)},
}


def shape_keys(side, frame, shape):
    out = []
    for f, (mp, pip, dip) in SHAPES[shape].items():
        for bone, a in (("１", mp), ("２", pip), ("３", dip)):
            out.append(key(side + f + bone, frame, flexed(side, f + bone, a)))
    return out


def hand_dance(shapes, last=LAST, arm=None, side="左", centre=True):
    """shapes: [(frame, shape)] keyed on the long fingers of one hand; arm: [(frame, degrees)] of 左腕 about Z"""
    keys = [k for k in untouched_keys(last, centre) if not (arm and k.name == "左腕")]
    for frame, shape in shapes:
        keys += shape_keys(side, frame, shape)
    for frame, deg in arm or []:
        keys.append(key("左腕", frame, axis_angle((0, 0, 1), deg)))
    return vmd.Motion(model_name="dancer", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 40, 0.0)])


def out_angles(motion, side, bone, last=LAST):
    """(flex, side, twist) of a joint in the motion, every frame, rest-relative as the layer reads them"""
    j = joint_of(side, bone)
    keys = fk.tracks_of(motion)[side + bone]
    frames = [k.frame for k in keys]
    q = np.array([fk.applied(fk.sample(keys, f, frames)[1]) for f in range(last + 1)])
    fl, sd, tw = hand_layer.read_joint(j, q)
    if j.kind != "cmc":
        fl, sd = fl - j.rest[0], sd - j.rest[1]
    return fl, sd, tw


def only(*steps):
    p = hand_layer.default_params()
    for s in hand_layer.STEPS:
        p[s] = s in steps
    return p


class OutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dance = hand_dance([(0, "open"), (20, "open"), (26, "fist"), (LAST, "fist")])
        cls.result = hand_layer.layer(MODEL, cls.dance, pulp=PULP)

    def test_every_key_is_a_finite_unit_rotation(self):
        # a swinging arm drives the stiffest joint (the thumb, about 50 Hz) hardest
        dance = hand_dance([(0, "open"), (LAST, "open")], arm=[(0, 20.0), (10, 80.0), (12, 20.0), (LAST, 20.0)])
        for motion in (self.result.motion, hand_layer.layer(MODEL, dance, pulp=PULP).motion):
            q = np.array([k.rotation for k in motion.bones])
            self.assertTrue(np.all(np.isfinite(q)))
            np.testing.assert_allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-5)

    def test_every_finger_bone_has_a_key_on_every_frame(self):
        tracks = fk.tracks_of(self.result.motion)
        for side in ("左", "右"):
            for j in HANDS[side].joints:
                self.assertEqual(sorted(k.frame for k in tracks[j.bone]), list(range(LAST + 1)), j.bone)

    def test_untouched_bones_and_morphs_are_byte_for_byte_the_same(self):
        names = ("センター", "下半身", "左腕")
        before = vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in self.dance.bones if k.name in names],
                                      morphs=list(self.dance.morphs)))
        after = vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in self.result.motion.bones if k.name in names],
                                     morphs=list(self.result.motion.morphs)))
        self.assertEqual(before, after)
        self.assertTrue(self.result.report["untouched"]["identical"])

    def test_with_every_step_off_the_fingers_are_the_input_s(self):
        out = hand_layer.layer(MODEL, self.dance, only(), pulp=PULP).motion
        for b in ("中指２", "小指３", "親指１"):
            a = out_angles(out, "左", b)
            keys = fk.tracks_of(self.dance).get("左" + b)
            if keys is None:
                np.testing.assert_allclose(a[0], 0.0, atol=1e-6)
                continue
            frames = [k.frame for k in keys]
            q = np.array([fk.applied(fk.sample(keys, f, frames)[1]) for f in range(LAST + 1)])
            j = joint_of("左", b)
            exp = hand_layer.read_joint(j, q)[0] - j.rest[0]
            np.testing.assert_allclose(a[0], exp, atol=1e-4)


class StaticTest(unittest.TestCase):
    """the shape in each frame: the hinge joints bend in their plane, DIP follows PIP, the range of motion"""

    def run_one(self, bone_angles, steps):
        keys = untouched_keys()
        for bone, (fl, sd, tw) in bone_angles.items():
            keys += [key("左" + bone, 0, flexed("左", bone, fl, sd, tw)), key("左" + bone, LAST, flexed("左", bone, fl, sd, tw))]
        dance = vmd.Motion(model_name="d", bones=keys)
        return hand_layer.layer(MODEL, dance, only(*steps), pulp=PULP).motion

    def test_a_pip_bent_sideways_comes_back_into_its_plane(self):
        # a hinge: no sideways bend of 10 degrees or a twist of 15 is left (the trace's pinch bends the PIP 22 degrees
        # sideways and twists it 45)
        out = self.run_one({"人指２": (40.0, 22.0, 45.0)}, ["hinge"])
        fl, sd, tw = out_angles(out, "左", "人指２")
        self.assertLess(np.abs(sd).max(), 10.0)
        self.assertLess(np.abs(tw).max(), 15.0)
        self.assertAlmostEqual(float(fl[0]), 40.0, delta=2.0)

    def test_a_small_sideways_bend_is_left(self):
        out = self.run_one({"人指２": (40.0, 2.0, 3.0)}, ["hinge"])
        fl, sd, tw = out_angles(out, "左", "人指２")
        self.assertAlmostEqual(float(sd[0]), 2.0, places=3)
        self.assertAlmostEqual(float(tw[0]), 3.0, places=3)

    def test_a_dip_left_straight_under_a_bent_pip_follows_it(self):
        # the deep flexor bends the DIP with the PIP: in a grasp at least about a quarter of it (DIP / PIP 0.16 to
        # 0.36 in Kamper 2003's grasps, 0.57 to 0.77 in a fist)
        out = self.run_one({"薬指２": (80.0, 0.0, 0.0), "薬指３": (0.0, 0.0, 0.0)}, ["coupling"])
        dip = out_angles(out, "左", "薬指３")[0]
        self.assertGreater(float(dip[0]), 0.25 * 80.0)

    def test_a_dip_bent_far_beyond_its_pip_comes_back(self):
        # DIP / PIP 1.7 (the trace's middle finger): no study shows the DIP bending past its PIP's angle
        out = self.run_one({"中指２": (50.0, 0.0, 0.0), "中指３": (85.0, 0.0, 0.0)}, ["coupling"])
        dip = out_angles(out, "左", "中指３")[0]
        self.assertLess(float(dip[0]), 1.05 * 50.0)

    def test_a_fist_that_couples_well_is_left(self):
        out = self.run_one({"中指２": (95.0, 0.0, 0.0), "中指３": (70.0, 0.0, 0.0)}, ["coupling", "rom"])
        self.assertAlmostEqual(float(out_angles(out, "左", "中指３")[0][0]), 70.0, places=3)
        self.assertAlmostEqual(float(out_angles(out, "左", "中指２")[0][0]), 95.0, places=3)

    def test_a_dip_beyond_its_range_is_eased_below_the_cap(self):
        out = self.run_one({"中指２": (100.0, 0.0, 0.0), "中指３": (116.0, 0.0, 0.0)}, ["rom"])
        dip = out_angles(out, "左", "中指３")[0]
        start, cap = hand_layer.ROM["dip"]["flex"][1]                    # the flexion side's (start, cap)
        self.assertLess(float(dip[0]), cap)
        self.assertGreater(float(dip[0]), start)


def finger_points(motion, side, finger, frame=30):
    """[3, 3] the finger's two outer joints and its tip in the wrist's frame (model units), by the model's own forward
    kinematics (not the layer's)"""
    names = [side + finger + p for p in (("１", "２", "２先") if finger == hand_layer.THUMB else ("２", "３", "３先"))]
    at = fk.Pose(MODEL, motion, [side + "手首"] + names).at(frame)
    pw, qw = at[side + "手首"]
    conj = (-qw[0], -qw[1], -qw[2], qw[3])
    return np.array([rotate(conj, np.subtract(at[n][0], pw)) for n in names])


def tip_in_hand(motion, side, finger, frame=30):
    return finger_points(motion, side, finger, frame)[-1]


MM = 0.08 * 1000.0              # millimetres per model unit (one unit is 8 cm)
FINGER_RADIUS_MM = 0.07 * MM    # about the half thickness of Rin's fingers (the audit's default radius, 5.6 mm)

# the trace's own shapes (v7, rest-relative degrees (flex, side, twist); the thumb's CMC absolutely): the middle finger
# of a fist hooked at the DIP (frame 7600), the thumbs of the two hands' heart (1983), the index of a pinch (2462)
HOOK = {"中指１": (87.9, 1.8, -0.3), "中指２": (68.1, 3.9, 0.0), "中指３": (115.7, 5.1, -0.3)}
HEART = {"親指０": (6.4, 36.5, 0.6), "親指１": (6.8, -40.8, 10.4), "親指２": (-2.3, -21.2, 17.7)}
PINCH = {"人指１": (35.0, 14.0, 1.6), "人指２": (46.1, 22.4, -40.7), "人指３": (45.3, 30.5, 3.3)}
# the ring finger curled with its DIP left straight (frame 4542, the left hand)
RING_STRAIGHT = {"薬指１": (47.5, 0.6, 0.7), "薬指２": (69.0, 4.3, 2.5), "薬指３": (3.3, 0.2, 0.2)}


class ReachTest(unittest.TestCase):
    """the hinges and the DIP's coupling change a shape the trace made at the wrong joint; the finger stays where the
    choreography put it, carried by the joints that can move that way (the MP of a long finger, the thumb's CMC), as
    far as their range allows"""

    def run_one(self, bone_angles, steps, frames=(0, LAST)):
        keys = untouched_keys(centre=False)
        for bone, (fl, sd, tw) in bone_angles.items():
            keys += [key("左" + bone, f, flexed("左", bone, fl, sd, tw)) for f in frames]
        dance = vmd.Motion(model_name="d", bones=keys)
        return dance, hand_layer.layer(MODEL, dance, only(*steps), pulp=PULP).motion

    def moved_mm(self, dance, out, finger):
        """how far each of the finger's outer joints and its tip moved (mm)"""
        return np.linalg.norm(finger_points(out, "左", finger) - finger_points(dance, "左", finger), axis=1) * MM

    def test_a_dip_hooked_past_its_pip_shares_the_bend_and_the_fist_stays_closed(self):
        dance, out = self.run_one(HOOK, ["hinge", "reach", "coupling", "rom"])
        pip, dip = out_angles(out, "左", "中指２")[0][30], out_angles(out, "左", "中指３")[0][30]
        self.assertLess(dip, 1.0 * pip + 1.0)                            # no study shows the DIP past its PIP
        self.assertLess(dip, hand_layer.ROM["dip"]["flex"][1][1])        # within the DIP's range
        moved = self.moved_mm(dance, out, "中指")
        self.assertLess(moved.max(), FINGER_RADIUS_MM)                   # every point within the finger's half thickness
        _, alone = self.run_one(HOOK, ["hinge", "coupling", "rom"])
        self.assertGreater(self.moved_mm(dance, alone, "中指")[-1], 2.0 * FINGER_RADIUS_MM)   # without it the tip leaves

    def test_the_heart_s_thumb_bends_in_its_plane_and_its_tip_follows_as_far_as_it_can(self):
        dance, out = self.run_one(HEART, ["hinge", "reach", "rom"])
        for bone in ("親指１", "親指２"):
            fl, sd, tw = out_angles(out, "左", bone)
            self.assertLess(abs(float(sd[30])), 10.0, bone)
            self.assertLess(abs(float(tw[30])), 15.0, bone)
        _, alone = self.run_one(HEART, ["hinge", "rom"])
        moved, moved_alone = self.moved_mm(dance, out, hand_layer.THUMB), self.moved_mm(dance, alone, hand_layer.THUMB)
        self.assertLess(moved[-1], 0.5 * moved_alone[-1])                # the tip: the trace bent the MP 41 degrees
        self.assertLess(moved.mean(), moved_alone.mean())                # sideways, past what the thumb's range can give

    def test_a_pinch_made_at_the_pip_moves_to_the_mp_and_the_tip_stays(self):
        dance, out = self.run_one(PINCH, ["hinge", "reach", "coupling", "rom"])
        for bone in ("人指２", "人指３"):
            fl, sd, tw = out_angles(out, "左", bone)
            self.assertLess(abs(float(sd[30])), 10.0, bone)
            self.assertLess(abs(float(tw[30])), 15.0, bone)
        mp_side = float(out_angles(out, "左", "人指１")[1][30])
        self.assertGreater(mp_side, PINCH["人指１"][1] + 3.0)            # the sideways bend went to the MP
        self.assertLess(mp_side, hand_layer.ROM["mp"]["side"][1][1])
        self.assertLess(self.moved_mm(dance, out, "人指").max(), FINGER_RADIUS_MM)

    def test_a_dip_left_straight_comes_into_the_band_and_the_tip_stays(self):
        dance, out = self.run_one(RING_STRAIGHT, ["hinge", "reach", "coupling", "rom"])
        pip, dip = out_angles(out, "左", "薬指２")[0][30], out_angles(out, "左", "薬指３")[0][30]
        self.assertGreater(dip, 0.3 * pip - 1.0)                         # the deep flexor bends the DIP with the PIP
        moved = self.moved_mm(dance, out, "薬指")
        _, alone = self.run_one(RING_STRAIGHT, ["hinge", "coupling", "rom"])
        self.assertLess(moved[-1], 0.5 * self.moved_mm(dance, alone, "薬指")[-1])
        self.assertLess(moved.max(), FINGER_RADIUS_MM)

    def test_the_fit_does_not_push_the_lost_bend_past_a_joint_s_range(self):
        # the heart's thumb cannot reach the trace's tip inside its range; the fit stops near the start of the range
        # (the IP's hyperextension from 15 degrees) instead of bending the IP back as far as the last step lets it
        dance, out = self.run_one(HEART, ["hinge", "reach", "rom"])
        start = hand_layer.ROM["ip"]["flex"][0][0]
        self.assertGreater(float(out_angles(out, "左", "親指２")[0][30]), -(start + 5.0))

    def test_the_report_measures_how_far_each_finger_left_the_choreography(self):
        steps = ["hinge", "reach", "coupling", "rom"]
        dance, out = self.run_one(HOOK, steps)
        rep = hand_layer.layer(MODEL, dance, only(*steps), pulp=PULP).report["shape"]["output"]["左"]
        alone = hand_layer.layer(MODEL, dance, only("hinge", "coupling", "rom"), pulp=PULP).report["shape"]["output"]["左"]
        moved = self.moved_mm(dance, out, "中指")
        self.assertAlmostEqual(rep["中指"]["tip_mm"]["held_still"]["max"], moved[-1], delta=0.05)
        self.assertAlmostEqual(rep["中指"]["outline_mm"]["held_still"]["max"], moved.mean(), delta=0.05)
        self.assertLess(rep["中指"]["tip_mm"]["held_still"]["max"], alone["中指"]["tip_mm"]["held_still"]["max"])
        self.assertAlmostEqual(rep["薬指"]["outline_mm"]["all"]["max"], 0.0, delta=1e-6)   # an untouched finger

    def test_a_shape_that_is_already_anatomical_is_left(self):
        fist = {"中指１": (80.0, 0.0, 0.0), "中指２": (95.0, 0.0, 0.0), "中指３": (70.0, 0.0, 0.0)}
        dance, out = self.run_one(fist, ["reach"])
        for bone, (fl, sd, tw) in fist.items():
            got = out_angles(out, "左", bone)
            np.testing.assert_allclose([float(got[0][30]), float(got[1][30])], [fl, sd], atol=0.01, err_msg=bone)

    def test_a_hand_closing_into_the_hook_moves_smoothly(self):
        # open at frame 20, the hooked fist from frame 26: every joint closes without turning back, and its speed
        # changes from frame to frame no more abruptly than the input's (a fit that jumps between two ways of
        # holding the tip would do both)
        keys = untouched_keys(centre=False)
        for bone, (fl, sd, tw) in HOOK.items():
            keys += [key("左" + bone, f, flexed("左", bone, 0.0)) for f in (0, 20)]
            keys += [key("左" + bone, f, flexed("左", bone, fl, sd, tw)) for f in (26, LAST)]
        dance = vmd.Motion(model_name="d", bones=keys)
        out = hand_layer.layer(MODEL, dance, only("hinge", "reach", "coupling", "rom"), pulp=PULP).motion
        for bone in HOOK:
            a_in = out_angles(dance, "左", bone)[0]
            a_out = out_angles(out, "左", bone)[0]
            self.assertGreater(np.diff(a_out).min(), -0.5, bone)
            self.assertLess(np.abs(np.diff(a_out, 2)).max(), 1.5 * np.abs(np.diff(a_in, 2)).max() + 1.0, bone)


class EnslaveTest(unittest.TestCase):
    """a finger's MP is pulled a little toward its neighbours' (the passive coupling of the adjacent fingers)"""

    def mp(self, shape):
        dance = hand_dance([(0, shape), (LAST, shape)])
        out = hand_layer.layer(MODEL, dance, only("enslave"), pulp=PULP).motion
        return {f: float(out_angles(out, "左", f + "１")[0][30]) for f in hand_layer.LONG}

    def test_a_pointing_index_bends_a_little_and_the_middle_finger_opens_a_little(self):
        # the others' MPs bent 80 degrees pull the pointing index's a little (Lang & Schieber 2004: the passive
        # coupling moves the other fingers by 4 to 16 % of a finger's motion), and it pulls the middle finger's back;
        # the ring and the little finger, between equals, stay
        got = self.mp("point")
        self.assertGreater(got["人指"], 2.0)
        self.assertLess(got["人指"], 0.16 * 80.0)
        self.assertLess(got["中指"], 80.0 - 2.0)
        self.assertGreater(got["中指"], 80.0 - 0.16 * 80.0)
        self.assertAlmostEqual(got["薬指"], 80.0, delta=0.05)
        self.assertAlmostEqual(got["小指"], 80.0, delta=0.05)

    def test_fingers_that_move_together_are_left(self):
        for shape in ("open", "fist"):
            got = self.mp(shape)
            for f in hand_layer.LONG:
                self.assertAlmostEqual(got[f], SHAPES[shape][f][0], delta=1e-6, msg=(shape, f))


class RelaxTest(unittest.TestCase):
    """an open hand that is not a fist or a pointing hand leans toward the relaxed hand held in the air (Varghese 2020:
    the index the least bent) and follows the wrist (the tenodesis), gently: it stays an open hand"""

    def sums(self, dance, frame=30):
        out = hand_layer.layer(MODEL, dance, only("relax"), pulp=PULP).motion
        return [sum(float(out_angles(out, "左", f + p)[0][frame]) for p in ("１", "２", "３")) for f in hand_layer.LONG]

    def test_a_flat_open_hand_curls_a_little_the_index_least(self):
        s = self.sums(hand_dance([(0, "open"), (LAST, "open")]))
        self.assertGreater(min(s), 8.0)                                  # no longer flat
        self.assertLess(max(s), 45.0)                                    # still an open hand
        self.assertEqual(int(np.argmin(s)), 0, s)                        # the index the least bent

    def test_the_relaxed_fingers_curl_more_with_the_wrist_bent_back(self):
        # tenodesis: wrist extension tightens the long flexors, palmar flexion lets the fingers open (Su 2005)
        keys = [k for k in untouched_keys()]
        keys += shape_keys("左", 0, "open") + shape_keys("左", LAST, "open")
        d_f = (0.7970, -0.6038, 0.0151)
        n = palm_normal("左")
        side_axis = np.cross(unit(POS["左中指１"] - POS["左手首"]), n)
        # the hand turned about the wrist's flexion axis: one way at frame 0, the other at LAST, through the middle
        for f, deg in ((0, -40.0), (LAST, 40.0)):
            keys.append(key("左手首", f, axis_angle(side_axis, deg)))
        dance = vmd.Motion(model_name="d", bones=keys)
        early, late = self.sums(dance, 3), self.sums(dance, LAST - 3)
        wrist = hand_layer.wrist_angles(MODEL, hand_layer.joint_locals(dance, ["左手捩", "左手首"], LAST + 1)[0], LAST + 1)["左"][0]
        more_bent = late if wrist[LAST - 3] < wrist[3] else early      # the frame with the wrist more extended
        less_bent = early if more_bent is late else late
        self.assertGreater(sum(more_bent), sum(less_bent) + 4.0)
        del d_f

    def test_a_hand_on_something_does_not_lean(self):
        # touch 1 (the hand on the face, the body or the other arm) leaves the open hand as it is; touch 0 curls it
        dance = hand_dance([(0, "open"), (LAST, "open")])
        names = [j.bone for h in HANDS.values() for j in h.joints]
        loc = hand_layer.joint_locals(dance, names, LAST + 1)[0]
        ext = {s: np.full(LAST + 1, 17.5) for s in HANDS}
        for t, moved in ((1.0, False), (0.0, True)):
            ang = hand_layer.read_all(HANDS, loc)
            before = {b: a.copy() for b, a in ang.items()}
            hand_layer.relax(HANDS, ang, ext, hand_layer.RELAX_GAIN, {s: np.full(LAST + 1, t) for s in HANDS})
            change = max(float(np.abs(ang[b] - before[b]).max()) for b in ang)
            if moved:
                self.assertGreater(change, 2.0)
            else:
                self.assertLess(change, 1e-9)

    def test_a_fist_and_a_pointing_finger_are_left(self):
        for shape, finger in (("fist", "中指"), ("point", "人指")):
            dance = hand_dance([(0, shape), (LAST, shape)])
            out = hand_layer.layer(MODEL, dance, only("relax"), pulp=PULP).motion
            exp = SHAPES[shape][finger]
            got = [float(out_angles(out, "左", finger + p)[0][30]) for p in ("１", "２", "３")]
            np.testing.assert_allclose(got, exp, atol=0.5, err_msg=shape)


class SpeedTest(unittest.TestCase):
    def test_a_one_frame_snap_is_spread_round_its_middle(self):
        dance = hand_dance([(0, "open"), (30, "open"), (31, "fist"), (LAST, "fist")])
        out = hand_layer.layer(MODEL, dance, only("speed"), pulp=PULP).motion
        s = sum(out_angles(out, "左", "中指" + p)[0] for p in ("１", "２", "３"))
        step = np.abs(np.diff(s))
        self.assertLess(step.max(), hand_layer.SPEED_MAX_DEG_S / 30.0 + 0.5)
        half = 0.5 * (s[0] + s[-1])
        cross = float(np.interp(half, s[20:45], np.arange(20, 45)))
        self.assertAlmostEqual(cross, 30.5, delta=0.6)                    # the change keeps its time
        self.assertAlmostEqual(float(s[10]), 0.0, places=4)               # far from it, nothing moved
        self.assertAlmostEqual(float(s[LAST]), 245.0, places=3)

    def test_a_change_within_the_speed_is_left(self):
        dance = hand_dance([(0, "open"), (20, "open"), (40, "fist"), (LAST, "fist")])
        out = hand_layer.layer(MODEL, dance, only("speed"), pulp=PULP).motion
        ref = hand_layer.layer(MODEL, dance, only(), pulp=PULP).motion
        np.testing.assert_allclose(out_angles(out, "左", "中指２")[0], out_angles(ref, "左", "中指２")[0], atol=1e-6)


class OrderTest(unittest.TestCase):
    """the joints of a finger do not start together: closing a fist the PIP leads (the MCP's peak 11 % of the motion
    later, Carpinella 2011) and the DIP follows the PIP (Mentzel 2011); opening the hand the MCP leads (the PIP's peak
    7 % later)"""

    @staticmethod
    def middle(x, a, b, frac=0.5):
        """the (sub-frame) time where x has gone frac of its way from frame a to frame b"""
        y = (x[a:b + 1] - x[a]) / (x[b] - x[a])
        return float(np.interp(frac, y, np.arange(a, b + 1)))

    def run_(self, shapes):
        out = hand_layer.layer(MODEL, hand_dance(shapes), only("order"), pulp=PULP).motion
        return [out_angles(out, "左", "中指" + p)[0] for p in ("１", "２", "３")]

    def test_closing_the_pip_leads_the_mcp_and_the_dip_follows(self):
        mp, pip, dip = self.run_([(0, "open"), (20, "open"), (30, "fist"), (LAST, "fist")])
        t_mp, t_pip, t_dip = (self.middle(x, 15, 40) for x in (mp, pip, dip))
        self.assertGreater(t_mp - t_pip, 0.4)
        self.assertLess(t_mp - t_pip, 2.0)
        self.assertGreater(t_dip - t_pip, 0.4)
        self.assertAlmostEqual(float(dip[45]), 70.0, places=3)           # the shape is met
        self.assertAlmostEqual(float(mp[10]), 0.0, places=3)             # and the hold before is untouched

    def test_opening_the_mcp_leads(self):
        mp, pip, dip = self.run_([(0, "fist"), (20, "fist"), (30, "open"), (LAST, "open")])
        t_mp, t_pip = self.middle(mp, 15, 40), self.middle(pip, 15, 40)
        self.assertGreater(t_pip - t_mp, 0.25)
        self.assertLess(t_pip - t_mp, 2.0)
        self.assertAlmostEqual(float(pip[45]), 0.0, places=3)

    def test_a_hand_that_opens_and_closes_again_at_once_closes_in_the_closing_order(self):
        # a fist opened over 3 frames and closed again over 6: two changes, not one (taken as one, from fist to fist,
        # the closing got the opening's order and the length of both)
        mp, pip, dip = self.run_([(0, "fist"), (20, "fist"), (23, "open"), (29, "fist"), (LAST, "fist")])
        t_mp, t_pip = self.middle(mp, 23, 34), self.middle(pip, 23, 34)
        self.assertGreater(t_mp - t_pip, 0.1)                            # closing: the PIP leads
        self.assertLess(t_mp - t_pip, 0.114 * 6 + 0.3)                   # by a share of the closing's own length


class LayerPassiveTest(unittest.TestCase):
    """the fingers lag the hand: they trail when it speeds up and run on when it stops, the open hand more than a fist"""

    def dev(self, shape, arm):
        dance = hand_dance([(0, shape), (LAST, shape)], arm=arm, centre=False)
        out = hand_layer.layer(MODEL, dance, only("passive"), pulp=PULP).motion
        ref = hand_layer.layer(MODEL, dance, only(), pulp=PULP).motion
        return out_angles(out, "左", "中指１")[0] - out_angles(ref, "左", "中指１")[0]

    def test_a_still_hand_keeps_its_fingers(self):
        d = self.dev("open", None)
        self.assertLess(np.abs(d).max(), 1e-6)

    def test_a_swing_that_stops_moves_the_fingers_and_they_settle(self):
        arm = [(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)]
        d = self.dev("open", arm)
        self.assertGreater(np.abs(d[18:36]).max(), 2.0)
        self.assertLess(np.abs(d[50:]).max(), 0.3)

    def test_a_fist_moves_less_than_an_open_hand(self):
        arm = [(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)]
        self.assertLess(np.abs(self.dev("fist", arm)).max(), 0.7 * np.abs(self.dev("open", arm)).max())

    def test_a_hand_on_something_does_not_trail(self):
        # where the hand touches (contact_weights 1), what it touches holds the fingers: no lag
        arm = [(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)]
        kept = hand_layer.contact_weights
        hand_layer.contact_weights = lambda model, motion, F, sides: {s: np.ones(F) for s in sides}
        try:
            d = self.dev("open", arm)
        finally:
            hand_layer.contact_weights = kept
        self.assertLess(np.abs(d).max(), 1e-6)

    def test_the_report_keeps_the_held_shape_apart_from_the_lag(self):
        # the shape of each frame (what the choreography holds) is measured before the timing: the lag moves the
        # fingers of the output, not the shape
        arm = [(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)]
        dance = hand_dance([(0, "open"), (LAST, "open")], arm=arm, centre=False)
        shape = hand_layer.layer(MODEL, dance, only("passive"), pulp=PULP).report["shape"]
        self.assertAlmostEqual(shape["static"]["左"]["中指"]["tip_mm"]["all"]["max"], 0.0, delta=1e-6)
        self.assertGreater(shape["output"]["左"]["中指"]["tip_mm"]["all"]["max"], 0.5)

    def test_the_lag_does_not_ring(self):
        # a dancer's fingers trail and catch up without swinging back and forth (the hand CG of Pollard & Zordan 2005
        # damps them past critical; Koshland 2000: the distal joints cancel the interaction torques)
        arm = [(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)]
        for shape in ("open", "fist"):
            d = self.dev(shape, arm)
            after = d[29:]                                   # the swing stopped at 28
            peak = np.abs(d[26:31]).max()
            # past the swing, no swing back the other way bigger than a tenth of the deviation at the stop
            sign = np.sign(d[np.argmax(np.abs(d[26:31])) + 26])
            self.assertLess(max(0.0, float((-sign * after).max())), 0.1 * peak + 1e-6, shape)


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dance = hand_dance([(0, "open"), (20, "open"), (21, "fist"), (LAST, "fist")],
                           arm=[(0, 20.0), (20, 20.0), (28, 80.0), (LAST, 80.0)])
        cls.result = hand_layer.layer(MODEL, dance, pulp=PULP)

    def test_the_input_and_the_output_are_measured_alike(self):
        rep = self.result.report
        for part in ("input", "output"):
            r = rep[part]["左"]
            for key_ in ("rom", "hinge", "coupling", "open_hand", "steps_deg_per_frame", "finger_speed_deg_s",
                         "dip_after_pip_frames", "frozen_while_hand_moves"):
                self.assertIn(key_, r, (part, key_))

    def test_the_snap_was_too_fast_before_and_is_not_after(self):
        rep = self.result.report
        self.assertGreater(rep["input"]["左"]["finger_speed_deg_s"]["over_1900"], 0)
        self.assertEqual(rep["output"]["左"]["finger_speed_deg_s"]["over_1900"], 0)

    def test_the_fingers_no_longer_hold_dead_still_while_the_hand_swings(self):
        rep = self.result.report
        before = rep["input"]["左"]["frozen_while_hand_moves"]
        after = rep["output"]["左"]["frozen_while_hand_moves"]
        self.assertGreater(before["frozen_frames"], after["frozen_frames"])

    def test_the_change_is_reported_per_joint(self):
        self.assertIn("held_still", self.result.report["change"]["左"]["左中指２"])

    def test_the_wrist_is_read_against_its_circumduction_ellipse(self):
        # Gracia-Ibanez 2020's dominant hand: 35 degrees of radial-ulnar and 73.2 of flexion-extension about (-8.2,
        # -1.8), the long axis 13.2 degrees toward the dart thrower's line.  At neutral flexion, 45 degrees of radial
        # deviation is outside, 10 inside; 60 of palmar flexion with 10 of ulnar deviation inside.
        inside = hand_layer.wrist_inside(np.array([10.0, 45.0, -10.0]), np.array([0.0, 0.0, 60.0]))
        np.testing.assert_array_equal(inside, [True, False, True])
        # the dart thrower's line is longer than the opposite one: 60 degrees along radial extension -> ulnar flexion
        # stays inside where 60 along radial flexion -> ulnar extension does not
        r = math.radians(45.0)
        dtm = hand_layer.wrist_inside(np.array([-60.0 * math.sin(r)]), np.array([60.0 * math.cos(r)]))
        odtm = hand_layer.wrist_inside(np.array([60.0 * math.sin(r)]), np.array([60.0 * math.cos(r)]))
        self.assertTrue(dtm[0])
        self.assertFalse(odtm[0])

    def test_the_report_counts_the_wrist_outside_its_ellipse(self):
        r = self.result.report["input"]["左"]["wrist"]
        for key_ in ("outside_ellipse", "fist_beyond_flexion", "frames"):
            self.assertIn(key_, r)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def read_json(path):
    with open(path, encoding="ascii") as fh:
        return json.load(fh)


class CommandTest(unittest.TestCase):
    def test_writes_the_dance_and_the_report(self):
        folder = tempfile.mkdtemp()
        try:
            dance_path, model_path = os.path.join(folder, "d.vmd"), os.path.join(folder, "m.pmx")
            with open(model_path, "wb") as fh:
                fh.write(model_bytes())
            vmd.dump(hand_dance([(0, "open"), (30, "fist"), (LAST, "fist")]), dance_path)
            out, rep = os.path.join(folder, "o.vmd"), os.path.join(folder, "r.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = hand_layer.main([dance_path, model_path, out, "--report", rep])
            self.assertEqual(code, 0, buf.getvalue())
            line = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertTrue(line["ok"])
            self.assertTrue(os.path.isfile(out))
            report = read_json(rep)
            self.assertIn("output", report)
            self.assertEqual(len(fk.tracks_of(vmd.load(out))["左中指２"]), LAST + 1)
        finally:
            shutil.rmtree(folder)

    def test_refuses_to_write_over_the_dance(self):
        folder = tempfile.mkdtemp()
        try:
            dance_path, model_path = os.path.join(folder, "d.vmd"), os.path.join(folder, "m.pmx")
            with open(model_path, "wb") as fh:
                fh.write(model_bytes())
            vmd.dump(hand_dance([(0, "open"), (LAST, "open")]), dance_path)
            before = read_bytes(dance_path)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = hand_layer.main([dance_path, model_path, dance_path])
            self.assertEqual(code, 2)
            self.assertEqual(read_bytes(dance_path), before)
        finally:
            shutil.rmtree(folder)

    def test_a_step_can_be_switched_off(self):
        folder = tempfile.mkdtemp()
        try:
            dance_path, model_path = os.path.join(folder, "d.vmd"), os.path.join(folder, "m.pmx")
            with open(model_path, "wb") as fh:
                fh.write(model_bytes())
            vmd.dump(hand_dance([(0, "open"), (LAST, "open")]), dance_path)
            out, rep = os.path.join(folder, "o.vmd"), os.path.join(folder, "r.json")
            with contextlib.redirect_stdout(io.StringIO()):
                code = hand_layer.main([dance_path, model_path, out, "--report", rep, "--no-relax", "--no-passive"])
            self.assertEqual(code, 0)
            report = read_json(rep)
            self.assertFalse(report["params"]["relax"])
            self.assertFalse(report["params"]["passive"])
        finally:
            shutil.rmtree(folder)


# ---- the real dance (skipped where it is not; MMD_CLI_TRACE and MMD_CLI_RIN point at them elsewhere) ---------------

MAIN_TREE = "C:/Users/kaga/Desktop/mmd-cli"           # the main working tree, where the real data lives


def real_file(*parts):
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    path = os.path.join(MAIN_TREE, *parts)
    return path if os.path.isfile(path) else None


def rin_path():
    rel = os.path.join("MikuMikuDance_v932x64", "UserFile", "Model", "Sour式鏡音リンVer.2.01", "White.pmx")
    for path in (os.environ.get("MMD_CLI_RIN"), os.path.join(os.path.expanduser("~"), "Desktop", rel)):
        if path and os.path.isfile(path):
            return path
    return None


TRACE = os.environ.get("MMD_CLI_TRACE") or real_file("_spike", "out", "hibikase", "variants", "dance_arms_open6_twist.vmd")
RIN = rin_path()
REAL = bool(TRACE) and os.path.isfile(TRACE) and RIN is not None


def crop(motion, first, last):
    """the motion between two frames as a motion of its own (a key on every frame, the linear curve)"""
    out = []
    for name, keys in fk.tracks_of(motion).items():
        frames = [k.frame for k in keys]
        for f in range(first, last + 1):
            p, r = fk.sample(keys, f, frames)
            out.append(vmd.BoneKey(keys[0].name, f - first, p, r, vmd.bone_interpolation(vmd.LINEAR_CURVE),
                                   raw_name=keys[0].raw_name))
    return vmd.Motion(model_name=motion.model_name, bones=out, morphs=list(motion.morphs))


@unittest.skipUnless(REAL, "the trace or Rin is not here")
class RealDanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pmx.load(RIN)
        cls.pulp = hand_layer.pulp_from_mesh(RIN)
        cls.dance = vmd.load(TRACE)

    def test_the_mesh_gives_the_thumbs_pulp_side(self):
        for side in ("左", "右"):
            self.assertIn(side, self.pulp)
            palm = hand_layer.hand_model(self.model)[side].palm
            self.assertGreater(float(self.pulp[side] @ palm), 0.2)       # toward the palm, not the nail

    def test_the_pointing_hands_at_52_s_keep_their_shape_and_stop_being_carved(self):
        # 1,535 - 1,585: both index fingers point up in front of the face while the arms move (the brief's 52 s;
        # before 1,535 the index is still curled in a fist)
        part = crop(self.dance, 1535, 1585)
        result = hand_layer.layer(self.model, part, pulp=self.pulp)
        for side in ("左", "右"):
            ch = result.report["change"][side]
            self.assertLess(ch[side + "人指２"]["held_still"]["p95"], 3.0, side)    # the pointing finger stays straight
            self.assertLess(ch[side + "人指３"]["held_still"]["p95"], 3.0, side)
            a, b = result.report["input"][side], result.report["output"][side]
            self.assertLess(b["frozen_while_hand_moves"]["share"], a["frozen_while_hand_moves"]["share"])
        self.assertTrue(result.report["untouched"]["identical"])

    def test_the_ring_finger_dip_no_longer_stays_straight_in_a_curl(self):
        # 717 - 760 (right): the ring finger's DIP straight (DIP / PIP 0.05) under a PIP bent 80 degrees and more
        part = crop(self.dance, 717, 760)
        result = hand_layer.layer(self.model, part, pulp=self.pulp)
        a = result.report["input"]["右"]["coupling"]["薬指"]
        b = result.report["output"]["右"]["coupling"]["薬指"]
        self.assertGreater(a["under_0.3"], 10)
        # left: the frames where the DIP follows a fast PIP late (the order step), not the held curl
        self.assertLess(b["under_0.3"], a["under_0.3"] / 4.0)

    def face_gap_mm(self, motion, first, last):
        """per frame, the nearest of the left hand's four fingertips to the eyes' midpoint and to the head (mm)"""
        names = ["左目", "右目", "頭"] + ["左" + f + "３先" for f in hand_layer.LONG]
        pose = fk.Pose(self.model, motion, names)
        out = []
        for f in range(first, last + 1):
            at = pose.at(f)
            eyes = (np.array(at["左目"][0]) + np.array(at["右目"][0])) / 2.0
            head = np.array(at["頭"][0])
            tips = [np.array(at["左" + x + "３先"][0]) for x in hand_layer.LONG]
            out.append(min(min(np.linalg.norm(t - eyes), np.linalg.norm(t - head)) for t in tips) * MM)
        return np.array(out)

    def test_a_hand_held_to_the_face_does_not_curl_into_it(self):
        # 7,505 - 7,550 (left): the hand comes to the chin, open, its fingertips 53 - 79 mm from the eyes (7,517 - 7,535).
        # The relaxed hand (Varghese 2020) and the tenodesis (Su 2005) were measured on free fingers; what the fingers
        # touch holds them, so the layer does not curl or swing them into the face
        part = crop(self.dance, 7505, 7550)
        before = self.face_gap_mm(part, 12, 30)
        after = self.face_gap_mm(hand_layer.layer(self.model, part, pulp=self.pulp).motion, 12, 30)
        self.assertGreater(float((after - before).min()), -2.0)
        params = hand_layer.default_params()
        params["contact"] = False                                         # the rule off: the curl goes into the face
        loose = self.face_gap_mm(hand_layer.layer(self.model, part, params, pulp=self.pulp).motion, 12, 30)
        self.assertLess(float((loose - before).min()), -2.0)


# ---- the promises no test held before (the review's mutants): the wrist's sides, the lag's direction and size, -----
# ---- the DIP's measured range, the bones the layer writes, the thumb's speed ------------------------------------


def flex_axis_of_the_wrist(side):
    """the axis a positive turn about which bends the hand toward the palm (worked out here from the bones)"""
    n = palm_normal(side)
    d_h = unit(POS[side + "中指１"] - POS[side + "手首"])
    axis = unit(np.cross(d_h, n))
    return axis if float(rotate(axis_angle(axis, 30.0), d_h) @ n) > float(d_h @ n) else -axis


def wrist_dance(side, keys_deg, axis):
    keys = untouched_keys(LAST, centre=False) + shape_keys(side, 0, "open") + shape_keys(side, LAST, "open")
    keys += [key(side + "手首", f, axis_angle(axis, d)) for f, d in keys_deg]
    return vmd.Motion(model_name="d", bones=keys)


class PromiseTest(unittest.TestCase):
    def test_the_wrist_reads_palmar_flexion_and_radial_deviation_by_their_own_sides(self):
        # judged here by where the hand goes: toward the palm is palmar flexion (+), toward the thumb radial (+)
        for side in ("左", "右"):
            fa = flex_axis_of_the_wrist(side)
            thumb_side = unit(POS[side + "人指１"] - POS[side + "小指１"])
            d_h = unit(POS[side + "中指１"] - POS[side + "手首"])
            n = palm_normal(side)
            ra = n if float((rotate(axis_angle(n, 20.0), d_h) - d_h) @ thumb_side) > 0 else -n
            for axis, sign_flex, sign_radial in ((fa, 1, 0), (-fa, -1, 0), (ra, 0, 1), (-ra, 0, -1)):
                m = wrist_dance(side, [(0, 25.0), (LAST, 25.0)], axis)
                loc = hand_layer.joint_locals(m, [side + "手捩", side + "手首"], LAST + 1)[0]
                flex, radial = hand_layer.wrist_angles(MODEL, loc, LAST + 1)[side]
                if sign_flex:
                    self.assertAlmostEqual(float(flex[10]), 25.0 * sign_flex, delta=1.0, msg=side)
                if sign_radial:
                    self.assertAlmostEqual(float(radial[10]), 25.0 * sign_radial, delta=1.0, msg=side)

    def test_the_fingers_trail_a_hand_that_starts_to_bend_and_run_on_when_it_stops(self):
        side = "左"
        m = wrist_dance(side, [(0, 0.0), (20, 0.0), (28, 40.0), (LAST, 40.0)], flex_axis_of_the_wrist(side))
        out = hand_layer.layer(MODEL, m, only("passive"), pulp=PULP).motion
        ref = hand_layer.layer(MODEL, m, only(), pulp=PULP).motion
        d = out_angles(out, side, "中指１")[0] - out_angles(ref, side, "中指１")[0]
        self.assertLess(float(d[20:24].min()), -0.3)          # the hand speeds up toward the palm: the fingers bend back
        self.assertLess(float(d[20:24].max()), 0.05)
        self.assertGreater(float(d[27:32].max()), 0.3)        # it stops: they run on toward the palm

    def test_the_lag_stays_a_few_degrees_however_hard_the_swing(self):
        # Koshland 2000: in purposeful movements the distal joints' passive motion is a few degrees; the layer eases
        # the lag toward 10 degrees at the MP
        arm = [(0, 0.0), (20, 0.0), (22, 110.0), (24, 0.0), (26, 110.0), (LAST, 110.0)]
        d = LayerPassiveTest().dev("open", arm)
        self.assertGreater(np.abs(d).max(), 3.0)
        self.assertLess(np.abs(d).max(), 10.0)

    def test_a_dip_bent_116_degrees_comes_below_the_measured_range(self):
        # the DIP's active flexion: 82-85 degrees on average (Mohamed Ibrahim 2024; mean + 2 SD about 90)
        out = StaticTest().run_one({"中指２": (100.0, 0.0, 0.0), "中指３": (116.0, 0.0, 0.0)}, ["rom"])
        self.assertLess(float(out_angles(out, "左", "中指３")[0][0]), 92.0)

    def test_only_the_finger_joints_are_rewritten(self):
        # every bone but the fingers' MP, PIP, DIP and the thumb's CMC, MP, IP keeps its keys byte for byte, the wrist
        # and the metacarpals next to them included
        keys = untouched_keys(LAST)
        for side in ("左", "右"):
            for b in ("手首", "手捩", "人指０", "中指０"):
                keys += [key(side + b, 0, axis_angle((1, 0, 0), 4.0)), key(side + b, 40, axis_angle((0, 1, 0), 9.0))]
            keys += shape_keys(side, 0, "open") + shape_keys(side, 25, "fist")
        dance = vmd.Motion(model_name="d", bones=keys)
        out = hand_layer.layer(MODEL, dance, pulp=PULP).motion
        joints = {j.bone for h in HANDS.values() for j in h.joints}

        def rest(m):
            return vmd.dumps(vmd.Motion(model_name="x", bones=[k for k in m.bones if k.name not in joints], morphs=list(m.morphs)))
        self.assertEqual(rest(dance), rest(out))

    def test_a_thumb_snap_is_held_to_the_speed_too(self):
        keys = untouched_keys(LAST)
        for f, (mp, ip) in ((0, (0.0, 0.0)), (30, (0.0, 0.0)), (31, (50.0, 75.0)), (LAST, (50.0, 75.0))):
            keys += [key("左親指１", f, flexed("左", "親指１", mp)), key("左親指２", f, flexed("左", "親指２", ip))]
        dance = vmd.Motion(model_name="d", bones=keys)
        out = hand_layer.layer(MODEL, dance, only("speed"), pulp=PULP).motion
        s = sum(out_angles(out, "左", b)[0] for b in ("親指１", "親指２"))
        self.assertLess(float(np.abs(np.diff(s)).max()), hand_layer.SPEED_MAX_DEG_S / 30.0 + 0.5)


if __name__ == "__main__":
    unittest.main()
