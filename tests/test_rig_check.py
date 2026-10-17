"""tools/rig_check.py: the measures of a rig, each checked on a shape whose answer is known (a ring blended linearly
between two bones twisted by theta keeps cos(theta / 2) of its radius, a flat strip folded over itself turns its
triangles over, a point pushed into a ball lies inside it by the push), the inventory of what a model receives from
VMDs (names it lacks and how much motion they carry), and the leg IK's misses and how other loops change them."""
import json
import math
import os
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx_edit, vmd
from tests.test_leg_ik import axis_angle, key, leg_ik, motion, rin_legs_bytes
from tests.test_pmx import APPEND_ROTATE, FIXED_AXIS, NORMAL, TRANSLATE, Writer
from tests.test_pmx_spine import load_tool
from tests.test_rig_skin import vertex_rec

rig_check = load_tool("rig_check")
rig_skin = rig_check.SKIN


def tube(w, x0, x1, rings, radius, n, weight_of):
    """vertex records and faces of a tube along x: `rings` rings of n vertices from x0 to x1; weight_of(x) gives
    (kind, bones, weights) of a ring at x"""
    vs, faces = [], []
    for r in range(rings):
        x = x0 + (x1 - x0) * r / (rings - 1)
        kind, bones, weights = weight_of(x)
        for k in range(n):
            a = 2 * math.pi * k / n
            vs.append(vertex_rec(w, (x, radius * math.cos(a), radius * math.sin(a)), kind, bones, weights,
                                 normal=(0.0, math.cos(a), math.sin(a))))
    for r in range(rings - 1):
        for k in range(n):
            a, b = r * n + k, r * n + (k + 1) % n
            c, d = a + n, b + n
            faces += [a, c, b, b, c, d]
    return vs, faces


def twisted_arm(theta=None):
    """bones: root 0, upper 1 (x 0), lower 2 (x 2, a child of 1), end 3 (x 4); a tube from x 0.2 to 3.8 whose rings blend
    linearly from upper (x <= 1) to lower (x >= 3), half and half at x 2"""
    w = Writer(bone=2, vertex=2)
    bones = [w.bone("root", position=(0, 0, 0), flags=NORMAL | TRANSLATE),
             w.bone("upper", parent=0, position=(0, 0, 0)),
             w.bone("lower", parent=1, position=(2, 0, 0), flags=NORMAL | FIXED_AXIS, axis=(1.0, 0.0, 0.0)),
             w.bone("end", parent=2, position=(4, 0, 0))]

    def weight_of(x):
        s = min(1.0, max(0.0, (x - 1.0) / 2.0))
        if s <= 0.0:
            return "BDEF1", (1,), ()
        if s >= 1.0:
            return "BDEF1", (2,), ()
        return "BDEF2", (1, 2), (1.0 - s,)
    vs, faces = tube(w, 0.2, 3.8, 19, 0.3, 16, weight_of)
    data = w.build(name="tube", bones=bones, vertices=vs, faces=[w.index(i, "vertex") for i in faces],
                   materials=[w.material(name="skin", faces=len(faces))])
    return data


def pose_of(m, *keys):
    return rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(motion(*keys)), 0))


class SectionTest(unittest.TestCase):
    def test_linear_twist_blend_pinches_by_the_cosine_of_half_the_twist(self):
        m = rig_skin.Model.loads(twisted_arm())
        for theta in (0.0, 60.0, 120.0, 170.0):
            pose = pose_of(m, key("lower", 0, axis_angle((1, 0, 0), theta)))
            pts = rig_skin.skin(m, pose)
            prof = rig_check.section_profile(m.points, pts, np.array([0, 0, 0.0]), np.array([4, 0, 0.0]),
                                             pose.pos[1], pose.pos[3], bins=19)       # one ring a bin
            low = min(r for r in prof["median"] if r is not None)
            self.assertAlmostEqual(low, math.cos(math.radians(theta / 2)), places=6, msg=theta)
            if theta:
                self.assertAlmostEqual(prof["t_at_min"], 0.5, delta=0.06)

    def test_bend_does_not_read_as_a_pinch_away_from_the_joint(self):
        # the whole tube on one bone, bent at the root: every ring keeps its radius about the bent axis
        w = Writer(bone=2, vertex=2)
        bones = [w.bone("root", position=(0, 0, 0)), w.bone("upper", parent=0, position=(0, 0, 0)),
                 w.bone("end", parent=1, position=(4, 0, 0))]
        vs, faces = tube(w, 0.2, 3.8, 10, 0.3, 12, lambda x: ("BDEF1", (1,), ()))
        m = rig_skin.Model.loads(w.build(bones=bones, vertices=vs, faces=[w.index(i, "vertex") for i in faces],
                                         materials=[w.material(faces=len(faces))]))
        pose = pose_of(m, key("upper", 0, axis_angle((0, 0, 1), 70.0)))
        prof = rig_check.section_profile(m.points, rig_skin.skin(m, pose), np.zeros(3), np.array([4, 0, 0.0]),
                                         pose.pos[1], pose.pos[2], bins=9)
        self.assertTrue(all(abs(r - 1.0) < 1e-9 for r in prof["median"] if r is not None))


class AreaTest(unittest.TestCase):
    def test_area_ratio_and_flips_of_a_folded_strip(self):
        # a strip of 4 squares in the plane z 0, its far half turned 180 degrees about y over the near half: the turned
        # triangles keep their area and face the other way; a squeezed square halves its area
        rest = np.array([[x, y, 0.0] for x in (0, 1, 2, 3, 4) for y in (0, 1)])
        faces = np.array([[2 * i, 2 * i + 2, 2 * i + 1] for i in range(4)] + [[2 * i + 1, 2 * i + 2, 2 * i + 3] for i in range(4)])
        nrm = np.tile([0, 0, 1.0], (10, 1))
        folded = rest.copy()
        folded[8:, 0] = 2.0                                 # the last column (x 4) folded back over x 3 to x 2
        folded[8:, 2] = 0.1
        r = rig_check.area_ratios(rest, folded, faces)
        flips = rig_check.flipped(rest, folded, faces, nrm, nrm)
        self.assertTrue(np.allclose(r, 1.0, atol=0.01))      # turned over, not squeezed
        self.assertEqual(sorted(np.flatnonzero(flips).tolist()), [3, 7])     # the two triangles of the last square
        squeezed = rest.copy()
        squeezed[:, 1] *= 0.5
        self.assertTrue(np.allclose(rig_check.area_ratios(rest, squeezed, faces), 0.5))


class PenetrationTest(unittest.TestCase):
    def ball(self, centre, radius, n=24):
        """an icosphere-like ball made of latitude rings (faces outward) and its vertex normals"""
        pts, faces = [], []
        rings = n // 2
        for i in range(rings + 1):
            phi = math.pi * i / rings
            for k in range(n):
                th = 2 * math.pi * k / n
                pts.append((math.sin(phi) * math.cos(th), math.cos(phi), math.sin(phi) * math.sin(th)))
        for i in range(rings):
            for k in range(n):
                a, b = i * n + k, i * n + (k + 1) % n
                faces += [[a, b, a + n], [b, b + n, a + n]]
        p = np.array(pts)
        return centre + radius * p, np.array(faces), p

    def test_points_inside_and_outside_a_ball(self):
        surf, faces, normals = self.ball(np.array([0, 0, 0.0]), 1.0)
        q = np.array([[0.0, 0.0, 0.5], [0.0, 0.0, 1.5], [0.7, 0.0, 0.0], [0.0, -2.0, 0.0]])
        d = rig_check.signed_distance(q, surf, normals, faces)
        self.assertAlmostEqual(d[0], -0.5, delta=0.02)
        self.assertAlmostEqual(d[1], 0.5, delta=0.02)
        self.assertAlmostEqual(d[2], -0.3, delta=0.02)
        self.assertAlmostEqual(d[3], 1.0, delta=0.02)

    def test_inside_at_rest_is_not_a_new_penetration(self):
        surf, faces, normals = self.ball(np.array([0, 0, 0.0]), 1.0)
        rest = np.array([[0.0, 0.0, 0.9], [0.0, 0.0, 1.3], [0.0, 1.3, 0.0]])        # the first lies inside already
        now = np.array([[0.0, 0.0, 0.5], [0.0, 0.0, 0.8], [0.0, 1.05, 0.0]])
        rep = rig_check.penetration(rest, now, surf, normals, faces, surf, normals, depth=0.02)
        self.assertEqual(rep["inside"], 1)                 # the second only: the first was inside at rest, the third is out
        self.assertAlmostEqual(rep["max_depth"], 0.2, delta=0.02)


class PickTest(unittest.TestCase):
    def test_top_frames_apart(self):
        x = np.zeros(200)
        x[50], x[52], x[120], x[180] = 9.0, 8.5, 7.0, 6.0
        picked = rig_check.pick_frames({"elbow": x}, per=3, gap=10)
        self.assertEqual([f for f, _ in picked["elbow"]], [50, 120, 180])


class ReceiversTest(unittest.TestCase):
    def test_names_the_model_lacks_and_what_they_carry(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        mo = vmd.Motion(model_name="x", bones=[
            key("左足ＩＫ", 0, position=(0, 1, 0)),
            key("グルーブ先", 0), key("グルーブ先", 10),                               # missing, no motion
            key("左袖", 0, position=(0.35, 0, 0)),                                    # missing, moves
            key("左腕捩", 3, axis_angle((1, 0, 0), 40.0)), key("左腕捩", 9, axis_angle((1, 0, 0), -10.0))],
            morphs=[vmd.MorphKey("眉頭右", 6446, 1.0), vmd.MorphKey("眉頭右", 0, 0.0), vmd.MorphKey("base", 0, 0.0)])
        rep = rig_check.receivers(doc, {"dance": mo})
        r = rep["vmds"]["dance"]
        self.assertEqual(r["bones"]["左足ＩＫ"]["in_model"], True)
        self.assertEqual(r["bones"]["グルーブ先"]["in_model"], False)
        self.assertEqual(r["bones"]["グルーブ先"]["moves"], False)
        self.assertEqual(r["bones"]["左袖"]["moves"], True)
        self.assertAlmostEqual(r["bones"]["左腕捩"]["max_turn_deg"], 40.0, places=3)
        self.assertEqual(sorted(r["dropped_motion"]), ["左腕捩", "左袖"])
        self.assertEqual(r["dropped_morphs"], {"眉頭右": {"keys": 2, "max_weight": 1.0, "frames": [0, 6446]}})
        self.assertIn("base", r["morphs"])
        self.assertEqual(rep["semi_standard"]["全ての親"], True)
        self.assertEqual(rep["semi_standard"]["左腕捩1"], False)

    def test_long_bone_name_matches_by_its_first_15_bytes(self):
        w = Writer(bone=2)
        long_name = "とても長い骨の名前です"                  # 22 bytes in cp932
        doc = pmx_edit.loads(w.build(bones=[w.bone(long_name)]))
        mo = vmd.Motion(model_name="x", bones=[vmd.BoneKey(fk.vmd_name(long_name), 0, (0, 0, 0), (0, 0, 0, 1))])
        rep = rig_check.receivers(doc, {"m": mo})
        self.assertTrue(rep["vmds"]["m"]["bones"][fk.vmd_name(long_name)]["in_model"])


class IkReportTest(unittest.TestCase):
    def test_misses_and_other_loops(self):
        data = rin_legs_bytes()
        keys = [key("左足ＩＫ", 0, position=(0.0, 0.1, 0.0)),            # nearly straight: 40 loops leave it 0.085 short
                key("左足ＩＫ", 10, position=(0.0, -3.0, 0.0)),          # out of reach
                key("左足ＩＫ", 20, position=(0.0, 3.0, -1.0))]          # reached
        mo = motion(*keys)
        rep = rig_check.ik_report(leg_ik.LegRig.loads(data), mo, [0, 10, 20], alternatives={"loops400": {"loops": 400}})
        left = rep["model"]["左"]
        self.assertEqual(left["reachable_miss_gt_4mm"], 1)          # frame 0
        self.assertEqual(left["unreachable"], 1)                    # frame 10
        self.assertEqual(rep["loops400"]["左"]["reachable_miss_gt_4mm"], 0)
        self.assertEqual(rep["settings"]["左"]["leg_loops"], 40)


class SourRinTest(unittest.TestCase):
    """the measures on the real model when this machine has it: the rest pose measures nothing; the upper arm's skin
    (SDEF between 腕W and 腕捩) holds a twist of 腕捩; a twist put on the wrist (手首, as tools/fix_twist.py does) wrings
    the wrist's skin (BDEF between 手捩 and 手首)"""

    @classmethod
    def setUpClass(cls):
        from tests.test_leg_ik import rin_path
        cls.m = rig_skin.Model.load(rin_path())
        cls.parts = rig_check.Parts(cls.m)
        cls.rest_nrm = cls.m.normals / np.linalg.norm(cls.m.normals, axis=1, keepdims=True)
        B = {b.name: b for b in cls.m.bones}
        cls.arm_axis = np.array(B["右ひじ"].position) - np.array(B["右腕"].position)
        cls.fore_axis = np.array(B["右手首"].position) - np.array(B["右ひじ"].position)

    def measure(self, *keys):
        m = self.m
        pose = pose_of(m, *keys)
        pts = rig_skin.skin(m, pose)
        return rig_check.measure_frame(m, self.parts, pose, pts, rig_skin.normals(m, pose), self.rest_nrm)

    def test_rest_measures_nothing(self):
        rec = self.measure(key("センター", 0))
        for k, v in rec["sections"].items():
            self.assertAlmostEqual(v["min"], 1.0, delta=0.005, msg=k)
        for k, v in rec["joints"].items():
            self.assertGreater(v["area_min"], 0.99, k)
            self.assertEqual(v["flipped"], 0, k)
        for k, v in rec["penetration"].items():
            self.assertEqual(v["inside"], 0, k)

    def test_upper_arm_skin_holds_a_twist(self):
        rec = self.measure(key("右腕捩", 0, axis_angle(self.arm_axis, 120.0)))
        self.assertGreater(rec["sections"]["upper_arm_R"]["min"], 0.99)

    def test_wrist_twist_wrings_the_wrist(self):
        rec = self.measure(key("右手首", 0, axis_angle(self.fore_axis, 170.0)))
        self.assertLess(rec["sections"]["forearm_R"]["min"], 0.5)
        self.assertGreater(rec["sections"]["forearm_R"]["t_at_min"], 0.95)
        self.assertLess(rec["joints"]["wrist_R"]["area_min"], 0.1)
        self.assertGreater(rec["joints"]["wrist_R"]["flipped"], 0)
        self.assertAlmostEqual(rec["sections"]["forearm_L"]["min"], 1.0, delta=0.005)     # the other arm untouched


if __name__ == "__main__":
    unittest.main()
