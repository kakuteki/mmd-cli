"""tools/hand_layer.py: the hands and the fingers made anatomical (the joints read in the hand's own frame, the range of
motion, the coupling of the joints and of the fingers, the relaxed hand and the fingers' passive lag), baked onto a
dance."""
import importlib.util
import math
import os
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


if __name__ == "__main__":
    unittest.main()
