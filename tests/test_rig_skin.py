"""tools/rig_skin.py: the whole skeleton posed as MMD poses it (keys, appends, IK in the deform order) and the vertices
skinned as MMD skins them, checked against what is known independently: mmd_cli.fk for the chains without IK,
tools/leg_ik.py (checked on MMD's renders) for the legs, and the skinning formulas on vertices whose answer is plain
(a vertex on one bone moves with it, a twist blended linearly pulls the skin onto the axis by cos(half the twist),
SDEF turns it about its centre and keeps it off the axis)."""
import math
import os
import random
import struct
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, vmd
from tests.test_leg_ik import axis_angle, key, leg_ik, motion, rin_legs_bytes, rin_path
from tests.test_pmx import APPEND_ROTATE, APPEND_TRANSLATE, FIXED_AXIS, IK, NORMAL, TRANSLATE, Writer
from tests.test_pmx_spine import load_tool

rig_skin = load_tool("rig_skin")


def vertex_rec(w, position, kind, bones, weights=(), sdef=None, normal=(0.0, 1.0, 0.0)):
    raw = w.vertex(kind, bones, weights)
    head = struct.pack("<3f3f2f", *position, *normal, 0.0, 0.0)
    if kind == "SDEF":
        c, r0, r1 = sdef
        n_idx = len(bones) * w.sizes["bone"]
        body = raw[32:32 + 1 + n_idx + 4 * len(weights)]
        return head + body + struct.pack("<9f", *c, *r0, *r1) + raw[-4:]
    return head + raw[32:]


def arm_bytes(vertices=None, faces=(), extra_bones=()):
    """a straight arm along +x: root (0) -> shoulder (1, at the origin) -> elbow (2, x 2) -> twist (3, x 3, append x 0.5
    of 4) -> wrist (4, x 4) -> hand (5, x 4.5); bone 6 slides with bone 1 (append translate x 1).  `vertices(w)` gives
    the vertex records."""
    w = Writer(bone=2, vertex=2)
    bones = [w.bone("root", position=(0, 0, 0), flags=NORMAL | TRANSLATE),
             w.bone("shoulder", parent=0, position=(0, 0, 0), flags=NORMAL | TRANSLATE),
             w.bone("elbow", parent=1, position=(2, 0, 0)),
             w.bone("twist", parent=2, position=(3, 0, 0), flags=NORMAL | APPEND_ROTATE, append=(4, 0.5)),
             w.bone("wrist", parent=2, position=(4, 0, 0)),
             w.bone("hand", parent=4, position=(4.5, 0, 0)),
             w.bone("slider", parent=0, position=(0, 1, 0), flags=NORMAL | APPEND_TRANSLATE | APPEND_ROTATE, append=(1, 1.0))]
    bones += [b(w) for b in extra_bones]
    vs = vertices(w) if vertices else []
    mats = [w.material(faces=len(faces))] if faces else []
    return w.build(name="arm", bones=bones, vertices=vs, faces=[w.index(i, "vertex") for i in faces], materials=mats)


def tracks(*keys):
    return fk.tracks_of(motion(*keys))


def length(v):
    return float(np.linalg.norm(v))


class PoseTest(unittest.TestCase):
    def test_rest_is_the_model(self):
        m = rig_skin.Model.loads(arm_bytes())
        pose = rig_skin.solve(m, rig_skin.keys_at(m, {}, 0))
        for i, b in enumerate(m.bones):
            self.assertLess(length(pose.pos[i] - np.array(b.position)), 1e-9)
            self.assertLess(length(pose.rot[i] - np.array([0, 0, 0, 1.0])), 1e-9)

    def test_chains_without_ik_match_mmd_cli_fk(self):
        # random turns and slides on every bone: world places and turns as mmd_cli.fk gives them (appends included)
        rnd = random.Random(7)
        data = arm_bytes()
        model = pmx.loads(data)
        m = rig_skin.Model.loads(data)
        names = [b.name for b in model.bones]
        for trial in range(20):
            keys = []
            for n in names:
                q = axis_angle((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)), rnd.uniform(-170, 170))
                pos = (rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)) if n in ("root", "shoulder") else (0, 0, 0)
                keys.append(key(n, 0, q, pos))
            mo = motion(*keys)
            want = fk.Pose(model, mo, names).world(0)
            pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
            for i in range(len(names)):
                self.assertLess(length(pose.pos[i] - np.array(want[i][0])), 1e-9, names[i])
                q = np.array(want[i][1])
                self.assertLess(min(length(pose.rot[i] - q), length(pose.rot[i] + q)), 1e-9, names[i])

    def test_keys_between_frames_follow_fk_sample(self):
        mo = motion(key("elbow", 0, axis_angle((0, 0, 1), 10.0)), key("elbow", 10, axis_angle((0, 0, 1), 90.0)))
        model = pmx.loads(arm_bytes())
        m = rig_skin.Model.loads(arm_bytes())
        for f in (0, 3, 7, 10, 12):
            want = fk.Pose(model, mo, ["hand"]).at(f)["hand"][0]
            pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), f))
            self.assertLess(length(pose.pos[5] - np.array(want)), 1e-9)


class LegIkTest(unittest.TestCase):
    """the leg IK and toe IK of the model with Sour's Rin's leg rig, solved here inside the whole pose, against
    tools/leg_ik.py (its solve was checked on MMD's renders)"""

    def setUp(self):
        self.data = rin_legs_bytes()
        self.m = rig_skin.Model.loads(self.data)
        self.rig = leg_ik.LegRig.loads(self.data)

    def check(self, mo, frames=(0,)):
        want = leg_ik.solve(self.rig, mo, list(frames))
        idx = {b.name: i for i, b in enumerate(self.m.bones)}
        for k, f in enumerate(frames):
            pose = rig_skin.solve(self.m, rig_skin.keys_at(self.m, fk.tracks_of(mo), f))
            for side in ("左", "右"):
                for part, bone in (("hip", "足"), ("knee", "ひざ"), ("ankle", "足首"), ("toe", "つま先"), ("ex", "足先EX")):
                    self.assertLess(length(pose.pos[idx[side + bone]] - want[side][part][k]), 1e-6, (side, part, f))
                for part, bone in (("q_shin", "ひざ"), ("q_foot", "足首")):
                    q = want[side][part][k]
                    got = pose.rot[idx[side + bone]]
                    self.assertLess(min(length(got - q), length(got + q)), 1e-6, (side, part, f))
                # the D bones copy the solved turns
                for d, b in (("足D", "足"), ("ひざD", "ひざ"), ("足首D", "足首")):
                    a, c = pose.rot[idx[side + d]], pose.rot[idx[side + b]]
                    self.assertLess(min(length(a - c), length(a + c)), 1e-6)
            self.assertAlmostEqual(pose.ik[idx["左足ＩＫ"]]["reach"], float(want["左"]["reach"][k]), places=6)

    def test_reachable_and_unreachable_goals(self):
        self.check(motion(key("左足ＩＫ", 0, position=(0.0, 3.0, -1.0)), key("センター", 0, position=(0.0, -0.5, 0.0)),
                          key("右足ＩＫ", 0, position=(0.0, -3.0, 0.0))))

    def test_nearly_straight_leg_lags_as_mmd(self):
        for lift in (0.1, 0.25, 0.5):
            self.check(motion(key("左足ＩＫ", 0, position=(0.0, lift, 0.0))))

    def test_keyed_hip_swivel_toe_pitch_and_ankle_roll(self):
        self.check(motion(key("左足ＩＫ", 0, axis_angle((1, 0, 0), -30.0), position=(0.3, 2.0, -1.0)),
                          key("左足", 0, axis_angle((0, 1, 0), 40.0)), key("左足首", 0, axis_angle((0.1, -0.9, -0.8), 20.0)),
                          key("左足先EX", 0, axis_angle((1, 0, 0), 30.0)), key("腰", 0, axis_angle((0, 1, 0), 15.0)),
                          key("左ひざ", 0, axis_angle((0.3, 1.0, 0.2), 35.0)),           # dropped by the plane solve
                          key("右足ＩＫ", 0, axis_angle((0, 1, 0), 30.0), position=(-0.5, 0.5, 1.0))))

    def test_random_poses(self):
        rnd = random.Random(3)
        keys = []
        for f in range(12):
            keys.append(key("左足ＩＫ", f, axis_angle((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)), rnd.uniform(-60, 60)),
                            (rnd.uniform(-1.5, 1.5), rnd.uniform(0, 4), rnd.uniform(-2, 2))))
            keys.append(key("右足ＩＫ", f, position=(rnd.uniform(-1.5, 1.5), rnd.uniform(0, 4), rnd.uniform(-2, 2))))
            keys.append(key("センター", f, position=(0, rnd.uniform(-2, 0.5), 0)))
            keys.append(key("左足", f, axis_angle((0, 1, 0), rnd.uniform(-40, 40))))
        self.check(motion(*keys), frames=range(12))

    def test_loops_override(self):
        # more loops than the file holds: the nearly straight leg gets to its goal (the IK settings a model may be given)
        mo = motion(key("左足ＩＫ", 0, position=(0.0, 0.1, 0.0)))
        idx = {b.name: i for i, b in enumerate(self.m.bones)}
        keys = rig_skin.keys_at(self.m, fk.tracks_of(mo), 0)
        short = rig_skin.solve(self.m, keys).ik[idx["左足ＩＫ"]]["reach"]
        m2 = rig_skin.Model.loads(self.data, ik_loops={"左足ＩＫ": 400})
        reached = rig_skin.solve(m2, keys).ik[idx["左足ＩＫ"]]["reach"]
        self.assertGreater(short, 0.08)
        self.assertLess(reached, 0.002)


class ArmIkTest(unittest.TestCase):
    def test_free_link_points_its_target_at_the_goal(self):
        # a free one-link IK (Sour's Rin's 腕WIK: link 腕W, target 腕W先, the goal on the elbow): the link's target ends
        # on the line to the goal; with a unit angle of 90 degrees and 2 loops a turn of 150 degrees is still reached
        def extra(w):
            return [lambda w: w.bone("armW", parent=0, position=(0, 0, 0), layer=1),                       # 7 (above the shoulder)
                    lambda w: w.bone("armW_tip", parent=7, position=(2, 0, 0), layer=1),                    # 8
                    lambda w: w.bone("armWIK", parent=2, position=(2, 0, 0), layer=1, flags=NORMAL | TRANSLATE | IK,
                                     ik={"target": 8, "loops": 2, "angle": math.pi / 2, "links": [(7, None)]})]
        data = arm_bytes(extra_bones=extra(None))
        m = rig_skin.Model.loads(data)
        for deg in (30.0, 150.0):
            mo = motion(key("shoulder", 0, axis_angle((0, 0, 1), deg)))
            pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
            self.assertLess(length(pose.pos[8] - pose.pos[2]), 1e-6, deg)
            self.assertLess(pose.ik[9]["reach"], 1e-6)

    def test_unit_angle_limits_each_loop_of_a_free_link(self):
        # one loop of at most 90 degrees cannot turn the helper 150 degrees: it stops 60 degrees short of the elbow
        def extra(w):
            return [lambda w: w.bone("armW", parent=0, position=(0, 0, 0), layer=1),
                    lambda w: w.bone("armW_tip", parent=7, position=(2, 0, 0), layer=1),
                    lambda w: w.bone("armWIK", parent=2, position=(2, 0, 0), layer=1, flags=NORMAL | TRANSLATE | IK,
                                     ik={"target": 8, "loops": 1, "angle": math.pi / 2, "links": [(7, None)]})]
        m = rig_skin.Model.loads(arm_bytes(extra_bones=extra(None)))
        mo = motion(key("shoulder", 0, axis_angle((0, 0, 1), 150.0)))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        self.assertAlmostEqual(pose.ik[9]["reach"], 2 * 2 * math.sin(math.radians(60.0) / 2), places=6)

    def test_deform_order_is_the_layer_before_the_index(self):
        # bone 1 (layer 1) copies the turn of bone 2, an IK link solved by bone 4 (layer 0): MMD solves the IK first, so
        # the copy carries the solved turn although it comes first by index
        w = Writer(bone=2, vertex=2)
        bones = [w.bone("root", position=(0, 0, 0), flags=NORMAL | TRANSLATE),
                 w.bone("copy", parent=0, position=(1, 0, 0), layer=1, flags=NORMAL | APPEND_ROTATE, append=(2, 1.0)),
                 w.bone("thigh", parent=0, position=(0, 0, 0)),
                 w.bone("tip", parent=2, position=(0, -2, 0)),
                 w.bone("goal", parent=0, position=(0, -2, 0), flags=NORMAL | TRANSLATE | IK,
                        ik={"target": 3, "loops": 4, "angle": 2.0, "links": [(2, None)]})]
        m = rig_skin.Model.loads(w.build(bones=bones))
        mo = motion(key("goal", 0, position=(2.0, 2.0, 0.0)))          # the goal straight out to +x: a 90 degree turn
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        self.assertLess(pose.ik[4]["reach"], 1e-6)
        a, b = pose.rot[1], pose.rot[2]
        self.assertLess(min(length(a - b), length(a + b)), 1e-9)
        self.assertGreater(abs(b[3]), 0.0)
        self.assertLess(abs(b[3]), math.cos(math.radians(40)))        # the thigh did turn (some 90 degrees)

    def test_axis_limited_link_stays_inside_its_limit(self):
        # a link limited to X -0.5..0.5 rad, Y and Z 0 (a single axis): solved in its plane, never past the limit
        def extra(w):
            return [lambda w: w.bone("leg", parent=0, position=(0, 0, 5), layer=1),                                   # 7
                    lambda w: w.bone("foot", parent=7, position=(0, -2, 5), layer=1),                                 # 8
                    lambda w: w.bone("goal", parent=0, position=(0, -2, 5), layer=1, flags=NORMAL | TRANSLATE | IK,
                                     ik={"target": 8, "loops": 20, "angle": 1.0, "links": [(7, ((-0.5, 0, 0), (0.5, 0, 0)))]})]
        m = rig_skin.Model.loads(arm_bytes(extra_bones=extra(None)))
        mo = motion(key("goal", 0, position=(0, 2.0, -2.0)))            # asks for about 90 degrees
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        q = pose.local_rot[7]
        angle = 2 * math.atan2(math.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2), q[3])
        self.assertLessEqual(angle, 0.5 + 1e-6)
        self.assertLess(abs(q[1]) + abs(q[2]), 1e-9)


def ring(w, x, radius, bones, weights, kind, n=12, sdef=None):
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n
        p = (x, radius * math.cos(a), radius * math.sin(a))
        out.append(vertex_rec(w, p, kind, bones, weights, sdef=sdef))
    return out


class SkinTest(unittest.TestCase):
    def test_one_bone_vertex_moves_with_it(self):
        data = arm_bytes(vertices=lambda w: [vertex_rec(w, (3.0, 0.5, 0.0), "BDEF1", (2,))])
        m = rig_skin.Model.loads(data)
        mo = motion(key("elbow", 0, axis_angle((0, 0, 1), 90.0)), key("root", 0, position=(1, 2, 3)))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        p = rig_skin.skin(m, pose)[0]
        # the elbow at (2, 0, 0) + (1, 2, 3); the vertex 1 along and 0.5 up from it, turned 90 about z
        self.assertLess(length(p - np.array([3.0 - 0.5, 2.0 + 1.0, 3.0])), 1e-9)

    def test_linear_twist_pulls_the_ring_in_by_the_cosine_of_half_the_twist(self):
        # a ring half on the elbow, half on the wrist; the wrist twisted 120 degrees about the arm: linear blending puts the
        # ring at cos(60) = 0.5 of its radius; SDEF (centre on the axis) keeps the radius and turns the ring 60 degrees
        def vs(w):
            return (ring(w, 3.0, 0.4, (2, 4), (0.5,), "BDEF2")
                    + ring(w, 3.0, 0.4, (2, 4), (0.5,), "SDEF", sdef=((3.0, 0, 0), (3.0, 0, 0), (3.0, 0, 0))))
        m = rig_skin.Model.loads(arm_bytes(vertices=vs))
        mo = motion(key("wrist", 0, axis_angle((1, 0, 0), 120.0)))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        p = rig_skin.skin(m, pose)
        r_lin = np.linalg.norm(p[:12, 1:], axis=1)
        r_sdef = np.linalg.norm(p[12:, 1:], axis=1)
        self.assertTrue(np.allclose(r_lin, 0.4 * 0.5, atol=1e-9))
        self.assertTrue(np.allclose(r_sdef, 0.4, atol=1e-9))
        self.assertTrue(np.allclose(p[:, 0], 3.0, atol=1e-9))
        first = math.degrees(math.atan2(p[12, 2], p[12, 1]))
        self.assertAlmostEqual(first, 60.0, places=6)

    def test_bdef4_is_the_weighted_sum(self):
        def vs(w):
            return [vertex_rec(w, (3.0, 0.3, 0.1), "BDEF4", (1, 2, 4, 5), (0.1, 0.2, 0.3, 0.4))]
        m = rig_skin.Model.loads(arm_bytes(vertices=vs))
        mo = motion(key("shoulder", 0, axis_angle((0, 1, 0), 20.0)), key("elbow", 0, axis_angle((0, 0, 1), 50.0)),
                    key("wrist", 0, axis_angle((1, 0, 0), 70.0)), key("hand", 0, axis_angle((0, 1, 1), 30.0)))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        got = rig_skin.skin(m, pose)[0]
        v = m.points[0]                                  # (3, 0.3, 0.1) as float32
        want = np.zeros(3)
        for b, wt in zip((1, 2, 4, 5), m.w[0]):          # the weights as the file holds them (float32)
            want += wt * (pose.pos[b] + leg_ik.qrot(pose.rot[b], v - np.array(m.bones[b].position)))
        self.assertTrue(np.allclose(m.w[0], (0.1, 0.2, 0.3, 0.4), atol=1e-7))
        self.assertLess(length(got - want), 1e-9)

    def test_sdef_turns_by_its_weights(self):
        # SDEF 0.25 on the elbow, 0.75 on the wrist, the centre on the axis; the wrist twisted 120 degrees: the ring turns by
        # 0.75 x 120 = 90 degrees (the blend runs from the first bone's turn to the second's by the second's weight) and
        # keeps its radius
        def vs(w):
            return ring(w, 3.0, 0.4, (2, 4), (0.25,), "SDEF", sdef=((3.0, 0, 0), (3.0, 0, 0), (3.0, 0, 0)))
        m = rig_skin.Model.loads(arm_bytes(vertices=vs))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(motion(key("wrist", 0, axis_angle((1, 0, 0), 120.0)))), 0))
        p = rig_skin.skin(m, pose)
        self.assertTrue(np.allclose(np.linalg.norm(p[:, 1:], axis=1), 0.4, atol=1e-9))
        self.assertAlmostEqual(math.degrees(math.atan2(p[0, 2], p[0, 1])), 90.0, places=5)

    def test_sdef_bend_keeps_the_far_side(self):
        # an elbow ring with SDEF around the joint: bending 90 degrees about z, the vertices stay at the radius from the
        # joint's centre (linear blending pulls the inner side in)
        def vs(w):
            return ring(w, 2.0, 0.4, (1, 2), (0.5,), "SDEF", sdef=((2.0, 0, 0), (2.0, 0, 0), (2.0, 0, 0)))
        m = rig_skin.Model.loads(arm_bytes(vertices=vs))
        mo = motion(key("elbow", 0, axis_angle((0, 0, 1), 90.0)))
        pose = rig_skin.solve(m, rig_skin.keys_at(m, fk.tracks_of(mo), 0))
        p = rig_skin.skin(m, pose)
        self.assertTrue(np.allclose(np.linalg.norm(p - np.array([2.0, 0.0, 0.0]), axis=1), 0.4, atol=1e-9))


class SourRinTest(unittest.TestCase):
    """the real model, when this machine has it: the rest pose skins every vertex to where it is, and the legs agree
    with tools/leg_ik.py on a few frames of a made-up dance"""

    @classmethod
    def setUpClass(cls):
        with open(rin_path(), "rb") as f:
            cls.data = f.read()
        cls.m = rig_skin.Model.loads(cls.data)

    def test_rest_skins_in_place(self):
        # with no keys every vertex stays where the file has it, but for the feet: the toe IK's goal lies 0.0004 from
        # the toe's rest place, so the IK turns the ankles a little (as it does in MMD)
        pose = rig_skin.solve(self.m, rig_skin.keys_at(self.m, {}, 0))
        p = rig_skin.skin(self.m, pose)
        err = np.abs(p - self.m.points).max(axis=1)
        feet = {self.m.index(s + n) for s in ("左", "右") for n in ("足首", "つま先", "足首D", "足先EX")}
        on_feet = np.isin(self.m.idx, sorted(feet)) & (self.m.w > 0)
        self.assertLess(float(err[~on_feet.any(axis=1)].max()), 1e-5)
        self.assertLess(float(err.max()), 1e-3)
        self.assertGreater(float(err.max()), 1e-5)          # the toe IK did turn the ankles

    def test_legs_agree_with_leg_ik(self):
        mo = motion(key("左足ＩＫ", 0, position=(0.2, 1.5, -0.8)), key("右足ＩＫ", 0, axis_angle((0, 1, 0), 25.0), position=(-0.3, 0.1, 0.4)),
                    key("センター", 0, position=(0.1, -0.8, 0.2)), key("下半身", 0, axis_angle((1, 0, 0), 15.0)))
        want = leg_ik.solve(leg_ik.LegRig.loads(self.data), mo, [0])
        pose = rig_skin.solve(self.m, rig_skin.keys_at(self.m, fk.tracks_of(mo), 0))
        idx = {b.name: i for i, b in enumerate(self.m.bones)}
        for side in ("左", "右"):
            self.assertLess(length(pose.pos[idx[side + "足首"]] - want[side]["ankle"][0]), 1e-6)
            self.assertLess(length(pose.pos[idx[side + "足先EX"]] - want[side]["ex"][0]), 1e-6)

    def test_arm_w_follows_the_elbow(self):
        # 右腕W hangs from 右肩 and its IK (右腕WIK on 右ひじ) keeps 右腕W先 on the elbow whatever the arm does
        mo = motion(key("右腕", 0, axis_angle((0.2, 0.3, 1.0), 70.0)), key("右肩", 0, axis_angle((0, 0, 1), -10.0)),
                    key("右腕捩", 0, axis_angle((-0.79, -0.61, 0.0), 80.0)))
        pose = rig_skin.solve(self.m, rig_skin.keys_at(self.m, fk.tracks_of(mo), 0))
        idx = {b.name: i for i, b in enumerate(self.m.bones)}
        self.assertLess(length(pose.pos[idx["右腕W先"]] - pose.pos[idx["右ひじ"]]), 1e-4)


if __name__ == "__main__":
    unittest.main()
