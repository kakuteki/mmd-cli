"""tools/contact_layer.py: the feet that should stand on the floor stand on it and do not slide, and where no foot stands
the body flies by gravity.  Checked by what the figure does as MMD shows it, measured apart from the layer (the shoes
skinned by tools/sink_check.py, the legs by MMD's IK in tools/leg_ik.py, the centre of mass by tools/wb_dynamics.py): a
still foot held over the floor comes down onto it, a standing foot does not slide yet lands where the dance puts it, a
leg that cannot reach the floor it must stand on gets the pelvis lowered, a hover with both feet moving becomes a hop that
falls by gravity, a hop that already does is left alone, and nothing else moves."""
import contextlib
import io
import json
import math
import os
import shutil
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_foot_layer import CAP, SOLE, UPPER
from tests.test_pmx import APPEND_ROTATE, IK, NORMAL, TRANSLATE, Writer
from tests.test_pmx_spine import load_tool

contact_layer = load_tool("contact_layer")
sink_check = load_tool("sink_check")
wb_dynamics = load_tool("wb_dynamics")
balance_layer = load_tool("balance_layer")
leg_ik = contact_layer.IK

CM, FPS, G = 8.0, 30.0, 122.5
FLOOR = 0.111                   # the synthetic shoes' soles at rest
BENT = -1.2                     # センター this far down: the knees bent some 60 degrees, every goal near the body in reach
KNEE_LIMITS = ((-math.pi, 0.0, 0.0), (0.0, 0.0, 0.0))
ARM_Q = (0.0, 0.0, 0.3, math.sqrt(1.0 - 0.09))


def body_model_bytes():
    """a model with Sour's Rin's rest positions: the trunk, the head and the arms (what the centre of mass needs), the leg
    rig of tests.test_leg_ik (the leg IK on ひざ and 足, the toe IK on 足首, 腰キャンセル, the D bones, 足先EX) and a shoe on each
    foot (tests.test_foot_layer's sole, upper and toe cap)"""
    w = Writer(bone=2, vertex=2)
    rows = [("全ての親", None, (0.0, 0.1, 0.0), NORMAL | TRANSLATE, {}),
            ("センター", "全ての親", (0.0, 7.8468, 0.0), NORMAL | TRANSLATE, {}),
            ("グルーブ", "センター", (0.0, 8.0468, 0.0), NORMAL | TRANSLATE, {}),
            ("腰", "グルーブ", (0.0, 11.7255, 0.2554), NORMAL, {}),
            ("上半身", "腰", (0.0, 12.2248, -0.6493), NORMAL, {}),
            ("上半身2", "上半身", (0.0, 13.7985, -0.6784), NORMAL, {}),
            ("首", "上半身2", (0.0, 15.6456, -0.1343), NORMAL, {}),
            ("頭", "首", (0.0, 16.2431, 0.0), NORMAL, {}),
            ("頭先", "頭", (0.0, 18.7663, -0.1601), NORMAL, {}),
            ("下半身", "腰", (0.0, 12.2248, -0.6493), NORMAL, {})]
    for s, sx in (("左", 1.0), ("右", -1.0)):
        rows += [(s + "肩", "上半身2", (sx * 0.2296, 15.3934, -0.222), NORMAL, {}),
                 (s + "腕", s + "肩", (sx * 0.9114, 15.2768, -0.2484), NORMAL, {}),
                 (s + "ひじ", s + "腕", (sx * 2.9071, 13.7325, -0.27), NORMAL, {}),
                 (s + "手首", s + "ひじ", (sx * 4.6524, 12.4104, -0.2368), NORMAL, {}),
                 (s + "中指３", s + "手首", (sx * 5.8701, 11.5382, -0.2637), NORMAL, {}),
                 ("腰キャンセル" + s, "下半身", (sx * 0.9012, 10.6579, 0.0073), NORMAL | APPEND_ROTATE, {"append": ("腰", -1.0)}),
                 (s + "足", "腰キャンセル" + s, (sx * 0.9012, 10.6579, 0.0073), NORMAL, {}),
                 (s + "ひざ", s + "足", (sx * 1.0032, 6.2313, -0.0361), NORMAL, {}),
                 (s + "足首", s + "ひざ", (sx * 1.1205, 1.7452, 0.37), NORMAL, {}),
                 (s + "つま先", s + "足首", (sx * 1.0463, 0.1, -1.15), NORMAL, {}),
                 (s + "足IK親", "全ての親", (sx * 1.1205, 0.1, 0.37), NORMAL | TRANSLATE, {}),
                 (s + "足ＩＫ", s + "足IK親", (sx * 1.1205, 1.7452, 0.37), NORMAL | TRANSLATE | IK,
                  {"layer": 1, "ik": (s + "足首", 40, 2.0, [(s + "ひざ", KNEE_LIMITS), (s + "足", None)])}),
                 (s + "つま先ＩＫ", s + "足ＩＫ", (sx * 1.0462, 0.1, -1.1496), NORMAL | TRANSLATE | IK,
                  {"layer": 2, "ik": (s + "つま先", 3, 4.0, [(s + "足首", None)])}),
                 (s + "足D", "腰キャンセル" + s, (sx * 0.9012, 10.6579, 0.0073), NORMAL | APPEND_ROTATE,
                  {"layer": 2, "append": (s + "足", 1.0)}),
                 (s + "ひざD", s + "足D", (sx * 1.0032, 6.2313, -0.0361), NORMAL | APPEND_ROTATE,
                  {"layer": 2, "append": (s + "ひざ", 1.0)}),
                 (s + "足首D", s + "ひざD", (sx * 1.1205, 1.7452, 0.37), NORMAL | APPEND_ROTATE,
                  {"layer": 2, "append": (s + "足首", 1.0)}),
                 (s + "足先EX", s + "足首D", (sx * 1.0794, 0.2877, -0.3235), NORMAL, {"layer": 2})]
    index = {r[0]: i for i, r in enumerate(rows)}
    built = []
    for name, parent, position, flags, kw in rows:
        args = {"parent": -1 if parent is None else index[parent], "position": position, "flags": flags,
                "layer": kw.get("layer", 0)}
        if "append" in kw:
            args["append"] = (index[kw["append"][0]], kw["append"][1])
        if "ik" in kw:
            target, loops, angle, links = kw["ik"]
            args["ik"] = {"target": index[target], "loops": loops, "angle": angle,
                          "links": [(index[l], lim) for l, lim in links]}
        built.append(w.bone(name, **args))
    verts = []
    for side, sx in (("左", 1.0), ("右", -1.0)):
        ankle_d, ex = index[side + "足首D"], index[side + "足先EX"]
        for x, y, z, wex in SOLE + UPPER + [CAP]:
            raw = w.vertex("BDEF2", (ex, ankle_d), (wex,)) if wex > 0 else w.vertex("BDEF1", (ankle_d,))
            verts.append(struct.pack("<3f", sx * x, y, z) + raw[12:])
    return w.build(name="rin-body", bones=built, vertices=verts)


DATA = body_model_bytes()
MODEL = pmx.loads(DATA)
DOC = pmx_edit.loads(DATA)
RIG = leg_ik.LegRig.loads(DATA)
SHOE = contact_layer.FL.Shoe(RIG, DOC)
SIDES = ("左", "右")


def bkey(name, frame, position=(0.0, 0.0, 0.0), q=(0.0, 0.0, 0.0, 1.0)):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(q)),
                       vmd.bone_interpolation(vmd.LINEAR_CURVE))


def about(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    return tuple(a / n * math.sin(h) for a in axis) + (math.cos(h),)


def dance(F, centre=lambda t: (0.0, BENT, 0.0), left=lambda t: ((0.0, 0.0, 0.0), None),
          right=lambda t: ((0.0, 0.0, 0.0), None), arms=True):
    """F frames with a key on every frame: センター at centre(t) (offsets, units), each foot IK at left(t) / right(t) =
    (offset, turn or None), 足首 keyed so that each foot keeps its foot IK's turn in the world (the toe IK starting on its
    goal, as the foot layer leaves a dance); an arm key and two morph keys that the layer must copy as they are"""
    keys = [bkey("センター", t, centre(t)) for t in range(F)]
    for s, fn in (("左", left), ("右", right)):
        for t in range(F):
            pos, q = fn(t)
            keys.append(bkey(s + "足ＩＫ", t, pos, q if q is not None else (0.0, 0.0, 0.0, 1.0)))
    if arms:
        keys += [bkey("左腕", 0, q=ARM_Q), bkey("左腕", F - 1)]
    m = vmd.Motion(model_name="rin-body", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 9, 0.0)])
    sol = leg_ik.solve(RIG, m, range(F))
    for s in SIDES:
        local = leg_ik.qmul(leg_ik.qconj(sol[s]["q_shin"]), sol[s]["q_ik"])
        keys += [bkey(s + "足首", t, q=tuple(float(v) for v in local[t])) for t in range(F)]
    return vmd.Motion(model_name="rin-body", bones=keys, morphs=list(m.morphs))


def run(m, **params):
    return contact_layer.layer(MODEL, RIG, SHOE, m, params)


def shoes(m, F):
    """side -> the shoe's lowest point over the floor (cm) and the slowest touching vertex's slide (cm/s), as
    tools/sink_check.py skins the shoe on MMD's IK"""
    tr = sink_check.shoe_track(RIG, DOC, m, range(F))
    return {s: {"low": (tr[s]["low"] - FLOOR) * CM, "slide": tr[s]["slide"] * CM * FPS} for s in SIDES}


def world_y(m, F, name):
    keys = leg_ik.sample(RIG, m, range(F))
    st = leg_ik._State(RIG, keys)
    return np.asarray(st.world(RIG.by_name[name])[0])[:, 1]


def down_acc(y):
    a = np.zeros(len(y))
    a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS * FPS
    return a


def goal(m, F, s):
    return leg_ik.solve(RIG, m, range(F))[s]["goal_ankle"]


def com_y(m, F):
    """the centre of mass's height [F] (units) by tools/wb_dynamics.py's segments"""
    body = balance_layer.Body(MODEL, m, F)
    lm, _ = wb_dynamics.landmarks_from_body(body)
    return wb_dynamics.com(wb_dynamics.segments(lm))[:, 1]


def other_keys(m):
    return sorted((k.name, k.frame, k.position, k.rotation) for k in m.bones
                  if k.name not in ("センター", "左足ＩＫ", "右足ＩＫ", "左足首", "右足首"))


def foot_turn_change(a, b, F, s):
    """degrees [F]: how far foot s's turn in the world differs between the dances a and b (MMD's IK)"""
    qa, qb = leg_ik.solve(RIG, a, range(F))[s]["q_foot"], leg_ik.solve(RIG, b, range(F))[s]["q_foot"]
    return np.degrees(2.0 * np.arccos(np.clip(np.abs(np.sum(qa * qb, axis=1)), 0.0, 1.0)))


class GroundTest(unittest.TestCase):
    def test_a_still_foot_held_over_the_floor_comes_down_onto_it(self):
        # the right foot held 2 cm over the floor for frames 10-39 (still), high in the air before and after; the left
        # foot stands: the right shoe comes onto the floor, nothing else moves, the knee changes a little
        F = 50
        m = dance(F, right=lambda t: ((0.0, 0.25 if 10 <= t <= 39 else 1.5, 0.0), None))
        out, plan = run(m)
        a, b = shoes(m, F), shoes(out, F)
        self.assertGreater(float(a["右"]["low"][10:40].min()), 1.5)                  # the dance holds it 2 cm up
        self.assertLess(float(np.abs(b["右"]["low"][10:40]).max()), 0.1)              # on the floor
        self.assertLess(float(np.abs(b["左"]["low"]).max()), 0.05)                    # the standing foot as it was
        for s in SIDES:
            self.assertLess(float(np.abs(goal(out, F, "左") - goal(m, F, "左")).max()), 1e-5)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)
        self.assertLess(float(np.abs(b["右"]["low"][:5] - a["右"]["low"][:5]).max()), 1e-4)     # far from the run: the dance
        self.assertLess(float(np.abs(b["右"]["low"][45:] - a["右"]["low"][45:]).max()), 1e-4)
        kin = sink_check.knee_bend(leg_ik.solve(RIG, m, range(F))["右"])
        kout = sink_check.knee_bend(leg_ik.solve(RIG, out, range(F))["右"])
        self.assertLess(float(np.abs(kout - kin).max()), 10.0)
        for s in SIDES:
            self.assertLess(float(foot_turn_change(m, out, F, s).max()), 0.5)       # the feet keep their shape
        self.assertEqual(other_keys(out), other_keys(m))
        self.assertEqual([(k.name, k.frame, k.weight) for k in out.morphs], [(k.name, k.frame, k.weight) for k in m.morphs])

    def test_a_foot_moving_fast_over_the_floor_is_left_in_the_air(self):
        # the right foot 2 cm up but travelling 0.3 units a frame (72 cm/s): a step's swing, not a held foot
        F = 40
        m = dance(F, right=lambda t: ((0.0, 0.25, -0.3 * t + 6.0), None))
        out, plan = run(m)
        self.assertLess(float(np.abs(goal(out, F, "右") - goal(m, F, "右")).max()), 1e-5)

    def test_a_standing_foot_out_of_reach_that_bears_the_weight_gets_the_pelvis_lowered(self):
        # a wide stance: the left foot 4 units out on the floor, the body over the middle (the centre of mass far outside
        # the right foot alone); the centre rises from frame 10 to 25 until the left leg cannot reach its goal on the
        # floor and MMD leaves that shoe up.  The layer lowers the pelvis so that it stands, never faster than the
        # skirt's bound, and moves no foot
        F = 60

        def centre(t):
            u = min(max((t - 10) / 15.0, 0.0), 1.0)
            return (1.0, BENT + 0.9 * u * u * (3.0 - 2.0 * u), 0.0)
        m = dance(F, centre=centre, left=lambda t: ((4.0, 0.0, 0.0), None))
        out, plan = run(m)
        a, b = shoes(m, F), shoes(out, F)
        self.assertGreater(float(a["左"]["low"][35:].min()), 1.0)                     # the dance's shoe is off the floor
        self.assertLess(float(b["左"]["low"][35:].max()), 0.15)                       # standing now
        self.assertLess(float(np.abs(b["右"]["low"]).max()), 0.1)                     # the other foot stays on the floor ...
        self.assertGreater(float(b["右"]["low"].min()), float(a["右"]["low"].min()) - 0.01)   # ... no deeper than it was
        drop = world_y(m, F, "センター") - world_y(out, F, "センター")
        self.assertGreater(float(drop[40:].min()), 0.1)                               # lowered ...
        self.assertLess(float(drop.max()), 0.6)                                       # ... by about the shortfall
        self.assertGreater(float(drop.min()), -1e-6)                                  # never raised
        for name in ("センター", "下半身"):
            self.assertLess(float(down_acc(world_y(out, F, name)).max()), 122.0 + 0.5)
        for s in SIDES:
            g0, g1 = goal(m, F, s), goal(out, F, s)
            self.assertLess(float(np.abs(g1[:, [0, 2]] - g0[:, [0, 2]]).max()), 0.01)  # the feet stay where they stand (1 mm)

    def test_a_free_foot_out_of_reach_keeps_the_pelvis(self):
        # the body over the right foot, the left leg stretched out to the side with its shoe 2-3 cm up and its goal out of
        # reach: a pointed foot resting, not a support.  The pelvis stays; the left foot comes no lower than it reaches
        F = 40
        m = dance(F, centre=lambda t: (-1.12, BENT + 0.9, 0.0), left=lambda t: ((2.0, 0.2, 0.0), None))
        out, plan = run(m)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)
        b = shoes(out, F)
        self.assertGreater(float(b["左"]["low"].min()), -0.05)                         # never into the floor
        sol = leg_ik.solve(RIG, out, range(F))
        self.assertLess(float(sol["左"]["reach"].max()), 0.6)                          # the goal no further out of reach


class KickTest(unittest.TestCase):
    def test_a_leg_kicked_far_out_of_reach_is_not_brought_down(self):
        # the right foot's goal 3 cm over the floor but 6 units (48 cm) out to the side: MMD leaves the leg straight with
        # the shoe far up (a kick); the body is between the feet.  Not a foot over the floor: nothing changes
        F = 40
        m = dance(F, centre=lambda t: (0.0, BENT + 0.9, 0.0), right=lambda t: ((-6.0, 0.375, 0.0), None))
        sol = leg_ik.solve(RIG, m, range(F))
        self.assertGreater(float(sol["右"]["reach"].min()), contact_layer.JUDGE_MISS)    # (as built: far out of reach)
        out, plan = run(m)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)
        self.assertLess(float(np.abs(goal(out, F, "右") - goal(m, F, "右")).max()), 1e-5)


class PlantTest(unittest.TestCase):
    def test_a_foot_the_dance_slides_fast_along_the_floor_keeps_its_slide(self):
        # the left foot on the floor slides 0.2 units a frame (48 cm/s) over frames 10-19 while the right stands: the
        # dance slides it (not the trace's drift): kept
        F = 40
        m = dance(F, left=lambda t: ((0.0, 0.0, -0.2 * min(max(t - 10, 0), 10)), None))
        out, plan = run(m)
        self.assertLess(float(np.abs(goal(out, F, "左") - goal(m, F, "左")).max()), 1e-5)

    def test_a_standing_foot_does_not_slide_and_lands_where_the_dance_puts_it(self):
        # single support: the right foot high in the air until frame 25, on the floor after; the left foot on the floor
        # slides 0.08 units a frame (19 cm/s) from frame 5 to 25, lifts at 26, swings, and lands at frame 36 where the
        # dance puts it
        F = 50

        def left(t):
            if t <= 25:
                return (0.0, 0.0, -0.08 * min(max(t - 5, 0), 20)), None
            if t < 36:
                u = (t - 25) / 11.0
                return (0.0, 1.2 * math.sin(math.pi * u), -1.6 - 0.8 * u), None
            return (0.0, 0.0, -2.4), None
        m = dance(F, left=left, right=lambda t: ((0.0, 1.25 if t <= 25 else 0.0, 0.0), None))
        out, plan = run(m)
        b = shoes(out, F)
        self.assertLess(float(b["左"]["slide"][5:25].max()), 0.5)                     # cm/s: planted
        g0, g1 = goal(m, F, "左"), goal(out, F, "左")
        self.assertLess(float(np.abs(g1[:6] - g0[:6]).max()), 1e-5)                   # before the slide: as it was
        self.assertLess(float(np.abs(g1[36:] - g0[36:]).max()), 1e-5)                 # lands where the dance lands
        step = np.linalg.norm(np.diff(g1[25:37, [0, 2]], axis=0), axis=1)
        self.assertLess(float(step.max()), 0.5)                                       # the swing makes up for it smoothly

    def test_a_foot_turning_on_its_sole_is_not_moved(self):
        # the left foot flat on the floor, turned 3 degrees a frame about the vertical through a sole vertex: that vertex
        # stays (no slide), so the layer has nothing to undo
        F = 20
        pivot = np.array([0.75, 0.112, -0.7])
        ankle0 = np.array([1.1205, 1.7452, 0.37])

        def left(t):
            q = about((0.0, 1.0, 0.0), 3.0 * t)
            ankle = pivot - leg_ik.qrot(np.array(q), pivot - ankle0)
            d = ankle - ankle0
            return (float(d[0]), 0.0, float(d[2])), q
        m = dance(F, left=left, right=lambda t: ((0.0, 1.25, 0.0), None))
        self.assertLess(float(shoes(m, F)["左"]["slide"][:-1].max()), 0.5)             # the dance's turn does not slide
        out, plan = run(m)
        self.assertLess(float(np.abs(goal(out, F, "左") - goal(m, F, "左")).max()), 1e-3)


class FlightTest(unittest.TestCase):
    def hop(self, F=60, a=20, b=27, speed=0.25, lift=0.25, pelvis=None):
        """both feet on the floor, up `lift` units over frames a..b (travelling `speed` units a frame in x), down again
        further along; the pelvis travels with them at BENT, or at pelvis(t) (heights over BENT)"""
        def x(t):
            return speed * min(max(t - a + 1, 0), b - a + 1)

        def foot(t):
            return (x(t), lift if a <= t <= b else 0.0, 0.0), None
        return dance(F, centre=lambda t: (x(t), BENT + (pelvis(t) if pelvis else 0.0), 0.0), left=foot, right=foot)

    def test_a_hover_with_both_feet_moving_becomes_a_hop_that_falls_by_gravity(self):
        F, a, b = 60, 20, 27
        m = self.hop(F, a, b)
        out, plan = run(m)
        y = com_y(out, F)
        air = down_acc(y)[a + 1:b]                                                    # the frames with air on both sides
        self.assertLess(float(np.abs(air - G).max()), 4.0)                            # the centre of mass falls by gravity
        y0 = com_y(m, F)
        self.assertLess(float(np.abs(down_acc(y0)[a + 1:b]).max()), 2.0)              # the dance's did not
        for name in ("センター", "下半身"):
            yy = world_y(out, F, name)
            acc = down_acc(yy)
            floor = np.ones(F, bool)
            floor[a:b + 1] = False
            self.assertLess(float(acc[floor].max()), 122.0 + 0.5)                     # pushed and caught by the floor
        for s in SIDES:
            g0, g1 = goal(m, F, s), goal(out, F, s)
            self.assertLess(float(np.abs(g1[:a - 1, [0, 2]] - g0[:a - 1, [0, 2]]).max()), 1e-5)
            self.assertLess(float(np.abs(g1[b + 1:] - g0[b + 1:]).max()), 1e-5)       # lands where the dance lands
        d = world_y(out, F, "センター") - world_y(m, F, "センター")
        self.assertLess(float(np.abs(d[:a - 12]).max()), 1e-6)                        # the window of the push and the catch
        self.assertLess(float(np.abs(d[b + 13:]).max()), 1e-6)
        self.assertGreater(float(d[a:b + 1].max()), 0.2)                              # the body rises in the hop

    def test_the_frames_round_a_flight_keep_the_bound(self):
        # the dance's pelvis bobs 4 mm at 8 Hz, falling at the bound (122 units/s^2) every few frames, and a hover with
        # both feet moving over frames 20-27 becomes a hop: no frame off the flight falls faster than the bound, the frames
        # just outside the window of the change included
        F, a, b = 70, 25, 32
        w = math.sqrt(122.0 / 0.05)
        m = self.hop(F, a, b, pelvis=lambda t: 0.05 * math.cos(w * t / FPS))
        out, plan = run(m)
        for name in ("センター", "下半身"):
            acc = down_acc(world_y(out, F, name))
            off = np.ones(F, bool)
            off[a:b + 1] = False
            self.assertLess(float(acc[off][1:-1].max()), 122.0 + 0.5)

    def test_a_hop_that_already_falls_by_gravity_is_left_alone(self):
        # the pelvis pushed up (+80 units/s^2 for 6 frames), flying at -g over frames 20-27 and caught: in the air the
        # feet go up and down with the body (the legs keep their shape), so the centre of mass follows gravity there
        # already; the feet are slow over the floor (a hop in place)
        F, a, b = 60, 20, 27
        acc = np.zeros(F)
        acc[14:20] = 80.0
        acc[20:28] = -G
        acc[28:34] = (8 * G - 6 * 80.0) / 6.0
        y = np.zeros(F)
        for t in range(2, F):                       # the second difference centred on t - 1 is acc[t - 1] / FPS^2
            y[t] = 2.0 * y[t - 1] - y[t - 2] + acc[t - 1] / (FPS * FPS)

        def foot(t):
            return (0.0, (y[t] - y[a - 1] + 0.1) if a <= t <= b else 0.0, 0.0), None
        m = dance(F, centre=lambda t: (0.0, BENT + float(y[t]), 0.0), left=foot, right=foot)
        self.assertLess(float(np.abs(down_acc(com_y(m, F))[a + 1:b] - G).max()), 0.5)  # (the dance as built)
        out, plan = run(m)
        d = world_y(out, F, "センター") - world_y(m, F, "センター")
        self.assertLess(float(np.abs(d).max()), 0.05)                                 # under 4 mm

    def test_the_feet_of_a_flight_clear_the_floor(self):
        # a low hop: both feet 0.8 cm up over frames 20-27, travelling: in the flight both shoes are 1.6 cm and more up
        # (under that a shoe stands as the skirt's bound counts it, and the body is falling by gravity)
        F, a, b = 60, 20, 27
        m = self.hop(F, a, b, lift=0.1)
        out, plan = run(m)
        sh = shoes(out, F)
        for s in SIDES:
            self.assertGreater(float(sh[s]["low"][a:b + 1].min()), 1.6)

    def test_a_foot_eased_down_does_not_stand_where_the_dance_falls_fast(self):
        # the right foot held 2 cm up over frames 10-29 (brought down), then both feet off and travelling over frames 30-32
        # while the dance's pelvis falls at 200 units/s^2 (the air, faster than the bound): the easing of the right foot's
        # lowering does not bring its shoe under 1.6 cm there
        F = 50
        acc = np.zeros(F)
        acc[30:33] = -200.0
        acc[33:36] = 200.0
        y = np.zeros(F)
        for t in range(2, F):
            y[t] = 2.0 * y[t - 1] - y[t - 2] + acc[t - 1] / (FPS * FPS)

        def left(t):
            return (0.0, 0.375 if 30 <= t <= 32 else 0.0, 0.3 * min(max(t - 29, 0), 3)), None

        def right(t):
            if 10 <= t <= 29:
                return (0.0, 0.25, 0.0), None
            if 30 <= t <= 32:
                return (0.0, 0.25, 0.3 * (t - 29)), None
            return (0.0, 0.0, 0.9 if t > 32 else 0.0), None
        m = dance(F, centre=lambda t: (0.0, BENT + float(y[t]), 0.0), left=left, right=right)
        self.assertGreater(float(down_acc(world_y(m, F, "センター"))[30:33].max()), 150.0)    # (as built)
        out, plan = run(m)
        self.assertLess(float(np.abs(shoes(out, F)["右"]["low"][10:30]).max()), 0.1)          # brought down
        self.assertGreater(float(shoes(out, F)["右"]["low"][30:33].min()), 1.6)

    def test_a_hover_with_one_foot_still_becomes_a_step_on_it(self):
        # both feet 2 cm up over frames 20-27, the left still, the right travelling 0.3 units a frame: the left is the
        # standing foot (brought onto the floor), no hop is made
        F, a, b = 60, 20, 27
        m = dance(F, left=lambda t: ((0.0, 0.25 if a <= t <= b else 0.0, 0.0), None),
                  right=lambda t: ((0.0, 0.25 if a <= t <= b else 0.0, 0.3 * min(max(t - a + 1, 0), b - a + 1) - 2.0), None))
        out, plan = run(m)
        b_ = shoes(out, F)
        self.assertLess(float(np.abs(b_["左"]["low"][a:b + 1]).max()), 0.1)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)
        self.assertLess(float(np.abs(goal(out, F, "右") - goal(m, F, "右")).max()), 1e-5)


class DropProfileTest(unittest.TestCase):
    def test_the_lowering_keeps_the_bound_on_the_frames_just_outside_its_window(self):
        # a lowering of 0.5 units over frames 15-25 within 3 frames each side: the frames just outside (11 and 29) fall at
        # the bound already, so the lowering may not bend up there (its second difference reaches into the window)
        F = 40
        need = np.zeros(F)
        need[15:26] = 0.5
        fall = np.zeros(F)
        fall[[11, 29]] = 122.0
        allowed = np.maximum(122.0, fall) + 0.25
        z, rows = contact_layer.drop_profile(need, np.ones(F, bool), fall, allowed, F, window=3)
        self.assertTrue(all(r["solved"] for r in rows))
        self.assertGreater(float(z[15:26].min()), 0.5 - 1e-6)
        after = fall + np.r_[0.0, (z[2:] - 2.0 * z[1:-1] + z[:-2]) * FPS * FPS, 0.0]
        self.assertLess(float(after.max()), 122.0 + 0.5)


class FlightChangeTest(unittest.TestCase):
    def test_the_change_keeps_the_bound_on_the_frames_just_outside_its_window(self):
        # a flight over frames 18-22 of a still body, its window 15-25; the frames just outside (14 and 26) fall at the
        # bound already
        F = 40
        air = np.zeros(F, bool)
        air[18:23] = True
        pel = np.zeros(F)
        pel[[14, 26]] = 61.0 / (FPS * FPS)              # a bump each: those two frames fall at 122 units/s^2
        fall = down_acc(pel)
        self.assertAlmostEqual(float(fall[14]), 122.0, places=6)
        com = np.zeros(F)
        ch, rows = contact_layer.flight_change([(15, 25)], air, ~air, com, [pel], np.maximum(122.0, fall), np.full(F, np.nan), F)
        self.assertTrue(all(r["solved"] for r in rows))
        d2 = np.r_[0.0, (ch[2:] - 2.0 * ch[1:-1] + ch[:-2]) * FPS * FPS, 0.0]
        self.assertLess(float(np.abs(d2[19:22] + G).max()), 1e-6)                    # the air falls by gravity
        after = down_acc(pel + ch)
        off = ~air
        self.assertLess(float(after[off][1:-1].max()), 122.0 + 0.5)                   # off it, nowhere faster than the bound


class WholeTest(unittest.TestCase):
    def test_nothing_to_do_gives_the_dance_back(self):
        F = 30
        m = dance(F)
        out, plan = run(m)
        self.assertIs(out, m)

    def test_main_writes_the_dance_and_the_report(self):
        d = tempfile.mkdtemp()
        try:
            F = 50
            m = dance(F, right=lambda t: ((0.0, 0.25 if 10 <= t <= 39 else 1.5, 0.0), None))
            src, model, dst, rep = (os.path.join(d, n) for n in ("in.vmd", "m.pmx", "out.vmd", "r.json"))
            vmd.dump(m, src)
            with open(model, "wb") as f:
                f.write(DATA)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = contact_layer.main([src, model, dst, "--report", rep])
            self.assertEqual(rc, 0)
            out = vmd.load(dst)
            self.assertLess(float(np.abs(shoes(out, F)["右"]["low"][10:40]).max()), 0.1)
            with open(rep, encoding="utf-8") as f:
                r = json.load(f)
            for k in ("plan", "ground", "plant", "flight", "pelvis", "untouched"):
                self.assertIn(k, r)
            self.assertTrue(r["untouched"]["identical"])
            self.assertEqual(r["pelvis"]["floor_past_bound_after"], 0)
            with self.assertRaises(SystemExit):
                contact_layer.main([src, model, src])
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
