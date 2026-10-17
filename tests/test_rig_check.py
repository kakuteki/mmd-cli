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
PMX_RIG = load_tool("pmx_rig")


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


class SummaryTest(unittest.TestCase):
    def test_the_worst_of_the_picked_frames(self):
        # per yardstick and model: the lowest section, the lowest area, the most triangles under half, the most flipped
        rep = {"m": {10: {"sections": {"forearm_R": {"min": 0.9}}, "joints": {"wrist_R": {"area_min": 0.3, "under_half": 2, "flipped": 0}}},
                     20: {"sections": {"forearm_R": {"min": 0.4}}, "joints": {"wrist_R": {"area_min": 0.6, "under_half": 7, "flipped": 3}}}}}
        picked = {"hand_twist_R": [(10, 170.0), (20, 160.0)], "wrist_bend_R": [(10, 88.0), (20, 80.0)]}
        rows = {(r["yardstick"], r["measure"]): r["value"] for r in rig_check.summary(rep, picked)}
        self.assertEqual(rows[("hand_twist_R", "section_min")], 0.4)
        self.assertEqual(rows[("wrist_bend_R", "area_min")], 0.3)
        self.assertEqual(rows[("wrist_bend_R", "under_half")], 7)
        self.assertEqual(rows[("wrist_bend_R", "flipped")], 3)


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

    def test_least_bend_keeps_the_knee_off_its_rest_bend(self):
        # the out-of-reach goal straightens the leg to the knee's limit; a limit of a least bend of 5 degrees keeps 5
        # degrees there, and costs a reachable goal at most the reach between the two (2.2 mm here)
        data = rin_legs_bytes()
        rig = leg_ik.LegRig.loads(data)
        mo = motion(key("左足ＩＫ", 0, position=(0.0, -3.0, 0.0)), key("左足ＩＫ", 1, position=(0.0, 0.1, 0.0)))
        rep = rig_check.ik_report(rig, mo, [0, 1], alternatives={"soft": {"loops": 400, "least_bend": 5.0}})
        self.assertEqual(rep["model"]["左"]["knee_at_least_bend"], 1)            # frame 0 at the limit (bend 0)
        soft = leg_ik.solve(rig_check._with_settings(rig, 400, None, 5.0), mo, [0, 1])["左"]
        self.assertAlmostEqual(math.degrees(-soft["knee_angle"][0]), 5.0, places=6)
        r0 = rig_check.max_reach(rig, "左")
        r5 = rig_check.max_reach(rig_check._with_settings(rig, least_bend=5.0), "左")
        self.assertLess(r5, r0)
        self.assertLess(r0 - r5, 0.035)                    # 0.028 units (2.2 mm) on these legs
        self.assertLess(float(soft["reach"][1]), 0.002)                          # the lifted foot is reached

    def test_a_one_frame_pop_of_the_knee_is_one_event(self):
        # the foot lifted 0.2 (the knee bent some 19 degrees) and, for one frame, pulled 0.3 past the leg's reach: the
        # knee straightens for that frame and bends again.  Lifted 0.3 (some 25 degrees) the frames before and after
        # count as jumps too (each is more than 10 degrees off the line through its neighbours): still one event
        data = rin_legs_bytes()
        rig = leg_ik.LegRig.loads(data)
        for lift, frames in ((0.2, [2]), (0.3, [1, 2, 3])):
            mo = motion(*[key("左足ＩＫ", f, position=(0.0, lift if f != 2 else -0.3, 0.0)) for f in range(5)])
            rep = rig_check.ik_report(rig, mo, range(5), alternatives={"loops400": {"loops": 400}})
            left = rep["loops400"]["左"]
            self.assertEqual(left["knee_jump_frames"], frames, lift)
            self.assertEqual(left["knee_jumps"], len(frames))
            self.assertEqual(left["knee_jump_event_count"], 1)
            ev = left["knee_jump_events"][0]
            self.assertEqual((ev["first"], ev["last"], ev["peak"]), (frames[0], frames[-1], 2))
            self.assertLess(ev["bends"][1], 0.5)                         # straight at the pop (the rest bend: 0)
            self.assertGreater(ev["bends"][0], 15.0)
            self.assertGreater(ev["deg"], 15.0)
            self.assertGreater(ev["reach_ratio"], 1.0)                   # the goal past the leg's reach
            self.assertAlmostEqual(ev["ankle_up_cm"], -0.3 * rig_check.UNIT_CM, places=3)
            self.assertEqual(rep["loops400"]["右"]["knee_jump_event_count"], 0)


class PhysicsTest(unittest.TestCase):
    def body(self, shape, size, pos, rot=(0.0, 0.0, 0.0), group=0, mask=0xFFFF, mode=1, damping=0.999):
        return pmx_edit.RigidBody(group, mask, shape, tuple(size), tuple(pos), tuple(math.radians(r) for r in rot), 0.5,
                                  damping, damping, 0.0, 0.0, mode)

    def test_frame_turns_y_by_yaw_pitch_roll(self):
        # roll -90 degrees about z lays a capsule's Y along +X; then pitch and yaw act on that
        c, R = rig_check.body_frame(self.body(2, (0.5, 2, 0), (1, 2, 3), (0, 0, -90)))
        self.assertTrue(np.allclose(R @ [0, 1, 0], [1, 0, 0], atol=1e-12))
        _, R2 = rig_check.body_frame(self.body(2, (0.5, 2, 0), (0, 0, 0), (0, 90, -90)))
        self.assertTrue(np.allclose(R2 @ [0, 1, 0], [0, 0, -1], atol=1e-12))    # then yaw 90 swings +X to -Z
        # pitch before yaw: pitch 30 tips Y towards +Z (0, cos 30, sin 30), then yaw 90 swings that +Z to +X
        _, R3 = rig_check.body_frame(self.body(2, (0.5, 2, 0), (0, 0, 0), (30, 90, 0)))
        self.assertTrue(np.allclose(R3 @ [0, 1, 0], [0.5, math.cos(math.radians(30)), 0.0], atol=1e-12))

    def test_gaps(self):
        a = self.body(0, (1, 0, 0), (0, 0, 0))
        self.assertAlmostEqual(rig_check.gap(a, self.body(0, (1, 0, 0), (3, 0, 0))), 1.0)
        cap = self.body(2, (0.5, 2, 0), (0, 0, 0))                       # ends at y -1 and 1
        self.assertAlmostEqual(rig_check.gap(cap, self.body(0, (0.5, 0, 0), (0, 2, 0))), 0.0, places=9)
        self.assertAlmostEqual(rig_check.gap(cap, self.body(0, (0.5, 0, 0), (1.2, 0.3, 0))), 0.2, places=9)
        self.assertAlmostEqual(rig_check.gap(cap, self.body(2, (0.5, 2, 0), (1.8, 0, 0), (0, 0, 90))), -0.2, places=9)   # crossing ends 0.8 apart
        box = self.body(1, (1, 0.5, 0.25), (0, 0, 0))
        self.assertAlmostEqual(rig_check.gap(box, self.body(0, (0.25, 0, 0), (0, 1.0, 0))), 0.25, places=9)
        self.assertAlmostEqual(rig_check.gap(box, self.body(0, (0.25, 0, 0), (0, 0.6, 0))), -0.15, places=9)

    def test_collide_reads_both_masks(self):
        a = self.body(0, (1, 0, 0), (0, 0, 0), group=2, mask=0xFFF8)        # not groups 0, 1, 2
        self.assertFalse(rig_check.collide(a, self.body(0, (1, 0, 0), (0, 0, 0), group=0)))
        self.assertTrue(rig_check.collide(a, self.body(0, (1, 0, 0), (0, 0, 0), group=3)))
        self.assertFalse(rig_check.collide(a, self.body(0, (1, 0, 0), (0, 0, 0), group=3, mask=0xFFFB)))   # it lets 2 not through

    def test_report_lists_overlaps_of_colliding_pairs_and_the_nearest_body(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        hair = self.body(2, (0.3, 1.0, 0), (0.0, 1.0, 0.0), group=2, mask=0xFFFF, mode=1)
        head = self.body(0, (1.0, 0, 0), (0.0, 2.0, 0.0), group=0, mode=0)
        far = self.body(0, (0.2, 0, 0), (5.0, 0, 0), group=2, mask=0xFFF8, mode=1)    # collides with no body
        for n, b in (("髪_1", hair), ("頭", head), ("飾り_1", far)):
            doc.rigid_bodies.append(pmx_edit.new_rigid(doc, n, n, 0, b))
        pmx_edit.set_joints(doc, [pmx_edit.Joint("髪_1", "", 0, 1, 0, (0.0, 1.5, 0.0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
                                                 (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0))])
        rep = rig_check.physics_report(doc, gravities=(98.0,))
        self.assertEqual([(o["a"], o["b"]) for o in rep["overlaps_at_rest"]], [("髪_1", "頭")])
        self.assertAlmostEqual(rep["overlaps_at_rest"][0]["depth"], 0.3 + 1.0 - 0.5, places=4)
        self.assertEqual(rep["dynamic_nearest_body"]["飾り_1"]["collides"], False)
        hz = rep["families"]["髪"]["pendulum_hz"]["98.0"][0]
        self.assertAlmostEqual(hz, math.sqrt(98.0 / 0.5) / (2 * math.pi), places=3)
        self.assertAlmostEqual(rep["families"]["髪"]["decay_s"][0], -1.0 / math.log(0.001), places=4)


def rich_model():
    """a small model with something in every part: 3 bones (one an IK), 4 vertices on 2 triangles of one material, a
    vertex morph, the display frames Root and 表情, 2 rigid bodies and a joint between them"""
    w = Writer(bone=2, vertex=2, morph=2, rigid=2)
    bones = [w.bone("root", position=(0, 0, 0), flags=NORMAL | TRANSLATE),
             w.bone("arm", parent=0, position=(0, 1, 0)),
             w.bone("armIK", parent=0, position=(0, 2, 0), flags=NORMAL | TRANSLATE | 0x0020,
                    ik={"target": 1, "loops": 40, "angle": 2.0, "links": [(1, ((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0)))]})]
    vs = [vertex_rec(w, (0.0, 0.0, 0.0), "BDEF1", (0,)), vertex_rec(w, (1.0, 0.0, 0.0), "BDEF2", (0, 1), (0.5,)),
          vertex_rec(w, (0.0, 1.0, 0.0), "BDEF2", (0, 1), (0.25,)), vertex_rec(w, (1.0, 1.0, 0.0), "BDEF1", (1,))]
    faces = [0, 1, 2, 2, 1, 3]
    morph = w.text("あ") + w.text("a") + bytes([3, 1]) + struct.pack("<i", 1) + w.index(2, "vertex") + struct.pack("<3f", 0, 0.1, 0)
    frames = [w.frame("Root", "Root", special=True, items=[("bone", 0)]), w.frame("表情", "Exp", special=True, items=[("morph", 0)])]
    data = w.build(bones=bones, vertices=vs, faces=[w.index(i, "vertex") for i in faces], materials=[w.material(name="skin", faces=6)],
                   morphs=[morph], frames=frames)
    doc = pmx_edit.loads(data)
    for name, bone, y in (("体", 0, 0.0), ("髪", 1, 1.0)):
        doc.rigid_bodies.append(pmx_edit.new_rigid(doc, name, name, bone, pmx_edit.RigidBody(
            0, 0xFFFF, 0, (0.2, 0.0, 0.0), (0.0, y, 0.0), (0.0, 0.0, 0.0), 1.0, 0.5, 0.5, 0.0, 0.5, 0 if bone == 0 else 1)))
    pmx_edit.set_joints(doc, [pmx_edit.Joint("髪", "hair", 0, 0, 1, (0.0, 0.5, 0.0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
                                             (-0.1, 0, 0), (0.1, 0, 0), (0, 0, 0), (0, 0, 0))])
    return pmx_edit.dumps(doc)


class DiffTest(unittest.TestCase):
    """rig_check.pmx_diff: every part of two PMX files compared, the changes named (the copy's recipe must be all
    that differs from the model it was made from)"""

    def test_a_model_against_itself_differs_in_nothing(self):
        rep = rig_check.pmx_diff(pmx_edit.loads(rich_model()), pmx_edit.loads(rich_model()))
        self.assertTrue(rep["same"])
        self.assertEqual(rep["changed_sections"], [])
        self.assertEqual(rep["counts"]["a"], rep["counts"]["b"])
        self.assertEqual(rep["counts"]["a"]["vertices"], 4)

    def test_each_kind_of_change_is_found_and_nothing_else(self):
        a, b = pmx_edit.loads(rich_model()), pmx_edit.loads(rich_model())
        b.bones[2].ik_loops = 400                                           # an IK's loops
        b.bones[1].position = (0.0, 1.5, 0.0)                               # a bone moved
        b.bones.append(pmx_edit.new_bone("追加", "added", (1.0, 2.0, 3.0), parent=1))
        b.vertices[2].set_weights([(0, 0.6), (1, 0.4)])                     # weights (BDEF2 0.25 / 0.75 before)
        head = bytearray(b.vertices[3].head)
        struct.pack_into("<f", head, 4, 1.25)                               # a vertex moved (y)
        b.vertices[3].head = bytes(head)
        b.morphs.append(pmx_edit.Morph(b.morphs[0].head, 1, 0, b""))
        b.frames[1].items.append((1, 1))
        g = pmx_edit.geometry(b)
        g.materials[0].diffuse = (1.0, 0.0, 0.0, 1.0)
        pmx_edit.set_geometry(b, g)
        rb = pmx_edit.rigid_body(b.rigid_bodies[1])
        rb.linear_damping = 0.9
        pmx_edit.set_rigid_body(b.rigid_bodies[1], rb)
        j = pmx_edit.joints(b)
        j[0].spring_rotate = (1.0, 0.0, 0.0)
        j.append(pmx_edit.Joint("追加", "", 0, 0, 1, (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)))
        pmx_edit.set_joints(b, j)
        rep = rig_check.pmx_diff(a, b)
        self.assertFalse(rep["same"])
        self.assertEqual(sorted(rep["changed_sections"]), ["bones", "display_frames", "joints", "materials", "morphs",
                                                           "rigid_bodies", "vertices"])
        bones = rep["bones"]
        self.assertEqual([x["name"] for x in bones["added"]], ["追加"])
        self.assertEqual(bones["added"][0]["parent"], "arm")
        changed = {x["name"]: x["fields"] for x in bones["changed"]}
        self.assertEqual(sorted(changed), ["arm", "armIK"])
        self.assertEqual(changed["armIK"], {"ik_loops": [40, 400]})
        self.assertEqual(sorted(changed["arm"]), ["position"])
        v = rep["vertices"]
        self.assertEqual((v["weights_changed"], v["position_changed"], v["normal_changed"], v["uv_changed"]), (1, 1, 0, 0))
        self.assertEqual(v["weight_changes"][0]["vertex"], 2)
        self.assertEqual(v["weight_changes"][0]["material"], "skin")
        self.assertEqual(v["weight_changes"][0]["a"], [["arm", 0.75], ["root", 0.25]])
        self.assertEqual(v["weight_changes"][0]["b"], [["root", 0.6], ["arm", 0.4]])
        self.assertEqual(v["position_changes"][0]["vertex"], 3)
        self.assertAlmostEqual(v["position_changes"][0]["moved"], 0.25, places=6)
        self.assertAlmostEqual(v["bone_weight_sums"]["root"][1] - v["bone_weight_sums"]["root"][0], 0.35, places=5)
        self.assertEqual([m["name"] for m in rep["morphs"]["added"]], ["あ"])
        self.assertEqual(rep["morphs"]["changed"], [])
        self.assertEqual(rep["display_frames"]["changed"], [{"frame": "表情", "added": [["morph", "あ"]], "removed": []}])
        self.assertEqual(rep["materials"]["changed"], [{"material": "skin", "fields": {"diffuse": [[0.5, 0.5, 0.5, 0.5], [1.0, 0.0, 0.0, 1.0]]}}])
        self.assertTrue(rep["faces"]["same"])
        self.assertEqual(rep["rigid_bodies"]["changed"], [{"rigid_body": "髪", "fields": {"linear_damping": [0.5, 0.9]}}])
        self.assertEqual(rep["joints"]["changed"], [{"joint": "髪", "fields": {"spring_rotate": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]}}])
        self.assertEqual((rep["joints"]["added"], rep["joints"]["removed"]), (["追加"], []))
        self.assertEqual((rep["rigid_bodies"]["added"], rep["materials"]["added"]), ([], []))
        self.assertTrue(rep["soft_bodies"]["same"])

    def test_a_recipe_of_pmx_rig_is_all_that_differs(self):
        from tests.test_pmx_rig import brow_model, wrist_model
        for data, recipe, added_bones, added_morphs in (
                (wrist_model(), {"joint_helpers": ["wrist"], "leg_ik_loops": None}, ["右手首補助", "左手首補助"], []),
                (brow_model(), {"inner_brow": 0.1}, [], ["眉頭右", "眉頭左"])):
            recipe = {k: v for k, v in recipe.items() if v is not None}
            doc = pmx_edit.loads(data)
            out = PMX_RIG.apply(doc, recipe)
            rep = rig_check.pmx_diff(pmx_edit.loads(data), pmx_edit.loads(pmx_edit.dumps(doc)))
            self.assertEqual([x["name"] for x in rep["bones"]["added"]], added_bones)
            self.assertEqual(rep["bones"]["changed"], [])
            self.assertEqual([x["name"] for x in rep["morphs"]["added"]], added_morphs)
            self.assertEqual(rep["vertices"]["position_changed"], 0)
            self.assertEqual(rep["vertices"]["weights_changed"], sum(h["vertices"] for h in out["helpers"]))
            self.assertFalse({"materials", "faces", "rigid_bodies", "joints", "soft_bodies", "header"} & set(rep["changed_sections"]))

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            pa, pb, out = os.path.join(d, "a.pmx"), os.path.join(d, "b.pmx"), os.path.join(d, "r.json")
            doc = pmx_edit.loads(rich_model())
            with open(pa, "wb") as f:
                f.write(pmx_edit.dumps(doc))
            doc.bones[2].ik_loops = 7
            with open(pb, "wb") as f:
                f.write(pmx_edit.dumps(doc))
            self.assertEqual(rig_check.main(["diff", pa, pb, "--out", out]), 0)
            with open(out, encoding="utf-8") as f:
                rep = json.load(f)
            self.assertEqual(rep["changed_sections"], ["bones"])
            self.assertEqual(len(rep["md5"]["a"]), 32)


class DeltaTest(unittest.TestCase):
    """rig_check.skin_delta: two models with the same vertices posed and skinned on the same frames, the vertices that
    land elsewhere, per material and along the limbs"""

    def setUp(self):
        from tests.test_pmx_rig import wrist_model
        self.data = wrist_model()
        doc = pmx_edit.loads(self.data)
        PMX_RIG.apply(doc, {"joint_helpers": ["wrist"]})
        self.out = pmx_edit.dumps(doc)

    def test_only_the_reweighted_vertices_land_elsewhere(self):
        # the wrist helper re-weights the three rings at the right wrist (x 1.8 to 2.0); a wrist twisted 170 degrees moves
        # them (the half and half ring from 0.3 cos 85 off the axis to 0.3), not the vertex on 右中指０; the same model
        # moves nothing
        models = {"v10": rig_skin.Model.loads(self.data), "same": rig_skin.Model.loads(self.data),
                  "v7": rig_skin.Model.loads(self.out)}
        rep = rig_check.skin_delta(models, motion(key("右手首", 0, axis_angle((1, 0, 0), 170.0))), [0])
        self.assertEqual(rep["same"]["0"]["moved"], 0)
        got = rep["v7"]["0"]
        self.assertEqual(got["moved"], 36)
        self.assertNotIn(36, got["vertices"])
        # the half and half ring moves straight out, from 0.3 cos 85 to 0.3 (both 85 degrees round): the most
        self.assertAlmostEqual(got["max_cm"], 0.3 * (1 - math.cos(math.radians(85))) * rig_check.UNIT_CM, places=4)
        places = got["places"]["forearm_R"]
        self.assertAlmostEqual(places["t_min"], 0.9, places=6)
        self.assertAlmostEqual(places["t_max"], 1.0, places=6)
        self.assertEqual(places["vertices"], 36)
        self.assertEqual(got["materials"], {"(none)": {"moved": 36, "max_cm": got["max_cm"]}})

    def test_rest_moves_nothing(self):
        models = {"v10": rig_skin.Model.loads(self.data), "v7": rig_skin.Model.loads(self.out)}
        rep = rig_check.skin_delta(models, motion(key("右ひじ", 0)), [0])
        self.assertEqual(rep["v7"]["0"]["moved"], 0)


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

    def test_angles_of_a_known_pose(self):
        # the right wrist twisted 120 degrees about the forearm and the left elbow bent 90 degrees from rest in the arm's
        # plane: the yardsticks read them back (the hand's twist against the elbow, the wrist's against 手捩)
        import tempfile
        from tests.test_leg_ik import rin_path
        B = {b.name: b for b in self.m.bones}
        rest_l = np.array(B["左手首"].position) - np.array(B["左ひじ"].position)
        rest_u = np.array(B["左ひじ"].position) - np.array(B["左腕"].position)
        n = np.cross(rest_u, rest_l)
        n = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else np.array([0.0, 0.0, 1.0])
        bend0 = math.degrees(math.acos(np.dot(rest_u, rest_l) / np.linalg.norm(rest_u) / np.linalg.norm(rest_l)))
        mo = motion(key("右手首", 0, axis_angle(self.fore_axis, 120.0)), key("左ひじ", 0, axis_angle(tuple(n), 90.0)))
        ang = rig_check.dance_angles(rin_path(), mo)
        self.assertAlmostEqual(float(ang["hand_twist_R"][0]), 120.0, delta=0.5)
        self.assertAlmostEqual(float(ang["wrist_twist_R"][0]), 120.0, delta=0.5)
        self.assertLess(float(ang["hand_twist_L"][0]), 0.5)
        self.assertAlmostEqual(float(ang["elbow_bend_L"][0]), bend0 + 90.0, delta=1.0)

    def test_wrist_twist_wrings_the_wrist(self):
        rec = self.measure(key("右手首", 0, axis_angle(self.fore_axis, 170.0)))
        self.assertLess(rec["sections"]["forearm_R"]["min"], 0.5)
        self.assertGreater(rec["sections"]["forearm_R"]["t_at_min"], 0.95)
        self.assertLess(rec["joints"]["wrist_R"]["area_min"], 0.1)
        self.assertGreater(rec["joints"]["wrist_R"]["flipped"], 0)
        self.assertAlmostEqual(rec["sections"]["forearm_L"]["min"], 1.0, delta=0.005)     # the other arm untouched


if __name__ == "__main__":
    unittest.main()
