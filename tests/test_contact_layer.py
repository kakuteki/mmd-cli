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


def body_model_bytes(loops=40):
    """a model with Sour's Rin's rest positions: the trunk, the head and the arms (what the centre of mass needs), the leg
    rig of tests.test_leg_ik (the leg IK on ひざ and 足, the toe IK on 足首, 腰キャンセル, the D bones, 足先EX) and a shoe on each
    foot (tests.test_foot_layer's sole, upper and toe cap).  `loops`: the leg IK's loops (v7's recipe: 400)"""
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
                  {"layer": 1, "ik": (s + "足首", loops, 2.0, [(s + "ひざ", KNEE_LIMITS), (s + "足", None)])}),
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
# the same body with the leg IK of v7's recipe (pmx_rig --leg-ik-loops 400): MMD's leg reaches its goal and a knee at the
# end of its reach is straight (the 40 loops' lag hid the snaps)
DATA400 = body_model_bytes(loops=400)
MODEL400 = pmx.loads(DATA400)
DOC400 = pmx_edit.loads(DATA400)
RIG400 = leg_ik.LegRig.loads(DATA400)
SHOE400 = contact_layer.FL.Shoe(RIG400, DOC400)
rig_check = load_tool("rig_check")


def bkey(name, frame, position=(0.0, 0.0, 0.0), q=(0.0, 0.0, 0.0, 1.0)):
    return vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(q)),
                       vmd.bone_interpolation(vmd.LINEAR_CURVE))


def about(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    return tuple(a / n * math.sin(h) for a in axis) + (math.cos(h),)


def dance(F, centre=lambda t: (0.0, BENT, 0.0), left=lambda t: ((0.0, 0.0, 0.0), None),
          right=lambda t: ((0.0, 0.0, 0.0), None), arms=True, rig=None):
    """F frames with a key on every frame: センター at centre(t) (offsets, units), each foot IK at left(t) / right(t) =
    (offset, turn or None), 足首 keyed so that each foot keeps its foot IK's turn in the world (the toe IK starting on its
    goal, as the foot layer leaves a dance, on `rig`'s solve: RIG when not given); an arm key and two morph keys that the
    layer must copy as they are"""
    rig = RIG if rig is None else rig
    keys = [bkey("センター", t, centre(t)) for t in range(F)]
    for s, fn in (("左", left), ("右", right)):
        for t in range(F):
            pos, q = fn(t)
            keys.append(bkey(s + "足ＩＫ", t, pos, q if q is not None else (0.0, 0.0, 0.0, 1.0)))
    if arms:
        keys += [bkey("左腕", 0, q=ARM_Q), bkey("左腕", F - 1)]
    m = vmd.Motion(model_name="rin-body", bones=keys, morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 9, 0.0)])
    sol = leg_ik.solve(rig, m, range(F))
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
        self.assertGreater(float(b["左"]["low"].min()), -0.1)                         # never 1 mm into the floor
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

    def test_a_leg_out_of_reach_for_a_moment_keeps_the_pelvis(self):
        # the same wide stance, but the centre bobs up for a few frames only (the left leg out of reach on 3 of them, as
        # a landing's leg reaching for the floor): not lowered for that
        F = 50

        def centre(t):
            u = max(0.0, 1.0 - abs(t - 25) / 4.0)
            return (1.0, BENT + 0.4 + 0.5 * u, 0.0)
        m = dance(F, centre=centre, left=lambda t: ((4.0, 0.0, 0.0), None))
        short = int((shoes(m, F)["左"]["low"] > 0.4).sum())
        self.assertGreater(short, 1)                                                  # (as built: the shoe up a moment)
        self.assertLess(short, contact_layer.REACH_MIN)
        out, plan = run(m)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_lowering_for_a_long_stance_leaves_a_later_moment_alone(self):
        # the wide stance out of reach over frames 15-35 (lowered for it), and later a bob of a few frames (75): the check
        # of the lowering on MMD's IK does not lower the body at that moment too
        F = 110

        def centre(t):
            long_ = 0.9 if 15 <= t <= 35 else 0.0
            u = max(0.0, 1.0 - abs(t - 80) / 4.0)
            return (1.0, BENT + max(long_, 0.4 + 0.5 * u if 76 <= t <= 84 else 0.0), 0.0)
        m = dance(F, centre=centre, left=lambda t: ((4.0, 0.0, 0.0), None))
        out, plan = run(m)
        d = world_y(m, F, "センター") - world_y(out, F, "センター")
        self.assertGreater(float(d[20:31].min()), 0.1)                                 # the long stance lowered
        self.assertLess(float(np.abs(d[70:]).max()), 1e-6)                             # the moment left alone

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


def floor_steps(sh, s, a, b):
    """the slide (cm) contact_check counts on the frames a..b of a side: the slowest touching vertex's step to the next
    frame where the shoe is within 4 mm of the floor on both"""
    lo, sl = sh[s]["low"], sh[s]["slide"] / FPS
    both = (lo[a:b] < 0.4) & (lo[a + 1:b + 1] < 0.4)
    return float(np.sum(sl[a:b][both]))


class SwingTest(unittest.TestCase):
    """a foot the dance moves fast just over the floor next to a standing run is not pressed onto the floor (v11feet,
    2026-10-17: after the retarget the layer's easing into the swing, its bridge over a short lift and its carry of the
    feet with a flight's change put such feet on the floor, where they slid: 153 cm a minute of the song's)"""

    def test_a_fast_swing_before_a_held_run_is_not_eased_onto_the_floor(self):
        # the right foot stands; the left travels 0.25 units a frame (60 cm/s) 6 mm over the floor until frame 11 and is
        # held still 2 cm up from frame 12 (lowered onto the floor there): the swing before it keeps its height
        F, k = 30, 12

        def left(t):
            return ((0.0, 0.075, -0.25 * t), None) if t < k else ((0.0, 0.25, -0.25 * (k - 1)), None)
        m = dance(F, left=left)
        out, plan = run(m)
        a, b = shoes(m, F), shoes(out, F)
        self.assertGreater(float(a["左"]["low"][:k].min()), 0.45)                     # the dance's swing is off the floor
        self.assertLess(float(np.abs(b["左"]["low"][k + 2:]).max()), 0.1)             # the held run comes down
        # the swing stays off it (its last frame, where the foot stops, comes down with the run: a landing, no slide)
        self.assertGreater(float(b["左"]["low"][:k - 1].min()), 0.4)
        self.assertLess(floor_steps(b, "左", 0, k), 0.5)

    def test_a_short_lift_of_a_foot_moving_fast_is_not_bridged(self):
        # the left foot stands until frame 9, travels 0.3 units a frame (72 cm/s) 1 cm up over frames 10-11, and stands
        # from frame 12; the right foot stands: the lift is the dance's quick step, not the trace's jitter
        F = 30

        def left(t):
            if t < 10:
                return (0.0, 0.0, 0.0), None
            if t < 12:
                return (0.0, 0.125, -0.3 * (t - 9)), None
            return (0.0, 0.0, -0.9), None
        m = dance(F, left=left)
        out, plan = run(m)
        b = shoes(out, F)
        self.assertFalse(bool(plan["sides"]["左"]["stance"][10:12].any()))
        self.assertGreater(float(b["左"]["low"][10:12].min()), 0.4)

    def test_a_still_lift_is_still_bridged(self):
        # the same lift without the travel: the trace's jitter of a standing foot, bridged
        F = 30
        m = dance(F, left=lambda t: ((0.0, 0.125 if 10 <= t < 12 else 0.0, 0.0), None))
        out, plan = run(m)
        self.assertTrue(bool(plan["sides"]["左"]["stance"][10:12].all()))


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

    def test_a_foot_coming_down_slowly_stands_where_the_dance_puts_it_down(self):
        # the right foot high until frame 6, 3 cm up at frame 10, then coming down slowly onto the floor over frames 10-25
        # while drifting 0.04 units a frame (10 cm/s) toward -z, on the floor and still after; the left foot in the air.
        # The right foot stands from frame 10 on (held, brought down) and stands where the dance puts it down (its first
        # frame on the floor), not where it was first held (the song's 237.9 s: 8.7 cm away for 3 s)
        F = 50

        def right(t):
            if t <= 6:
                return (0.0, 1.5, 0.0), None
            if t < 10:
                return (0.0, 1.5 + (0.375 - 1.5) * (t - 6) / 4.0, 0.0), None
            if t <= 25:
                return (0.0, 0.375 * (1.0 - (t - 10) / 16.0), -0.04 * (t - 10)), None
            return (0.0, 0.0, -0.64), None
        m = dance(F, left=lambda t: ((0.0, 1.25, 0.0), None), right=right)
        a = shoes(m, F)
        down = int(np.flatnonzero(a["右"]["low"] < 0.4)[0])
        self.assertGreater(down, 20)                                                  # (as built: down late in the hold)
        out, plan = run(m)
        g0, g1 = goal(m, F, "右"), goal(out, F, "右")
        self.assertLess(float(np.abs(g1[down, [0, 2]] - g0[down, [0, 2]]).max()), 0.01)    # put down where the dance does
        b = shoes(out, F)
        self.assertLess(float(np.abs(b["右"]["low"][12:down]).max()), 0.1)             # standing from the hold on ...
        self.assertLess(float(np.abs(b["右"]["low"][down:]).max()), 0.4)               # (on the floor as the dance has it)
        self.assertLess(float(b["右"]["slide"][12:F - 1].max()), 0.5)                  # ... without sliding (cm/s)

    def test_a_standing_foot_the_body_moves_away_from_slides_before_its_knee_changes_much(self):
        # single support on the left foot, which the dance slides slowly (0.08 units a frame, 19 cm/s) along -z for 40
        # frames together with the body: held where it first stood, the leg would straighten some 19 degrees as the body
        # goes 3.2 units away (the song's 70.4-71.2 s: 35 degrees and MMD's leg 2.3 cm short of its goal).  The layer
        # holds it while the knee stays within KNEE_GIVE of the dance's, then lets it slide
        F = 60

        def z(t):
            return -0.08 * min(max(t - 10, 0), 40)
        m = dance(F, centre=lambda t: (0.0, BENT, z(t)), left=lambda t: ((0.0, 0.0, z(t)), None),
                  right=lambda t: ((0.0, 1.25, z(t)), None))
        out, plan = run(m)
        k0 = sink_check.knee_bend(leg_ik.solve(RIG, m, range(F))["左"])
        sol = leg_ik.solve(RIG, out, range(F))
        k1 = sink_check.knee_bend(sol["左"])
        self.assertLess(float(np.abs(k1 - k0).max()), contact_layer.KNEE_GIVE + 1.0)
        self.assertLess(float(sol["左"]["reach"].max()), contact_layer.IK_MISS)         # MMD's leg reaches its goal
        b = shoes(out, F)
        self.assertLess(float(b["左"]["slide"][10:20].max()), 0.5)                     # held at first (cm/s)

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
        # (under that a shoe stands as the skirt's bound counts it, and the body is falling by gravity).  (With the glide,
        # the default since v11feet, a run so low under a level pelvis stands on its lower foot instead: the test above.)
        F, a, b = 60, 20, 27
        m = self.hop(F, a, b, lift=0.1)
        out, plan = run(m, glide=False)
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

    def test_a_leg_kicked_for_a_frame_in_a_flight_does_not_jolt_the_pelvis(self):
        # the hop above with the left foot kicked up 2.4 units on frame 23 only (a trace's one-frame jump of a limb): the
        # centre of mass falls by gravity over the flight, and the pelvis does not take the kick up (no step of its
        # height's speed above or below both neighbours by more than 0.15 m/s inside the flight: a08's one-frame spike)
        F, a, b = 60, 20, 27

        def x(t):
            return 0.25 * min(max(t - a + 1, 0), b - a + 1)

        def left(t):
            return (x(t), (0.25 + (2.4 if t == 23 else 0.0)) if a <= t <= b else 0.0, 0.0), None

        def right(t):
            return (x(t), 0.25 if a <= t <= b else 0.0, 0.0), None
        m = dance(F, centre=lambda t: (x(t), BENT, 0.0), left=left, right=right)
        out, plan = run(m)
        v = np.diff(world_y(out, F, "センター")) * FPS * CM / 100.0          # m/s, the step from frame t to t + 1
        for i in range(a + 1, b - 1):                       # (the steps with flight steps each side)
            up, dn = v[i] - v[i - 1], v[i] - v[i + 1]
            self.assertFalse(up * dn > 0.0 and min(abs(up), abs(dn)) > 0.15, "a one-frame spike at step %d" % i)
        y = com_y(out, F)
        acc = 2.0 * np.polyfit(np.arange(a, b + 1) / FPS, y[a:b + 1], 2)[0]
        self.assertLess(abs(-acc - G), 0.1 * G)

    def test_a_still_foot_just_over_the_floor_while_the_body_sinks_fast_is_a_standing_foot(self):
        # the right foot held still 2 cm up over frames 20-24 while the left is up in the air and the pelvis sinks at 70
        # units/s^2 there (0.57 g, a quick squat, caught after: supported, not a fall): the right foot stands (brought
        # down), no hop is made (the song's 127.8-128.1 s: the pelvis was raised 6 cm into a hop of 11 frames over a foot
        # held 2.7 cm up, as the dance's pelvis fell faster than half of gravity there)
        F = 60
        acc = np.zeros(F)
        acc[20:25] = -70.0
        acc[25:30] = 70.0
        y = np.zeros(F)
        for t in range(2, F):
            y[t] = 2.0 * y[t - 1] - y[t - 2] + acc[t - 1] / (FPS * FPS)
        m = dance(F, centre=lambda t: (0.0, BENT + float(y[t]), 0.0),
                  left=lambda t: ((0.0, 2.0, 0.0), None),
                  right=lambda t: ((0.0, 0.25 if 20 <= t <= 24 else 0.0, 0.0), None))
        fit = -2.0 * np.polyfit(np.arange(19, 26) / FPS, world_y(m, F, "下半身")[19:26], 2)[0]
        self.assertGreater(float(fit), G / 2.0)                                     # (as built: faster than half of g)
        self.assertGreater(float(shoes(m, F)["右"]["low"][20:25].min()), 1.5)       # (and the foot 2 cm up)
        out, plan = run(m)
        self.assertLess(float(np.abs(shoes(out, F)["右"]["low"][20:25]).max()), 0.1)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_still_foot_just_over_the_floor_under_a_pelvis_that_turns_in_a_frame_is_a_standing_foot(self):
        # the right foot held still 2 cm up over frames 20-31 while the left is up in the air; the pelvis rises 0.08 units a
        # frame and falls at the same speed after frame 26 (a trace's keys: it turns over one frame, faster than gravity
        # there): the right foot stands, no hop is made, and where it now stands the pelvis falls no faster than the
        # skirt's bound (lowered a few millimetres at the turn; the song's 75.4-75.8 s: the pelvis turned so at 151
        # units/s^2 and the run became a 12-frame hop 9.4 cm higher than the dance)
        F = 60

        def h(t):
            return 0.08 * max(0.0, 6.0 - abs(t - 26)) if 20 <= t <= 32 else 0.0
        m = dance(F, centre=lambda t: (0.0, BENT + h(t), 0.0), left=lambda t: ((0.0, 2.0, 0.0), None),
                  right=lambda t: ((0.0, 0.25 if 20 <= t <= 31 else 0.0, 0.0), None))
        y = world_y(m, F, "下半身")
        self.assertGreater(float(down_acc(y)[26]), 122.5)                           # (as built: the turn, faster than g)
        fit = -2.0 * np.polyfit(np.arange(19, 33) / FPS, y[19:33], 2)[0]
        self.assertLess(float(fit), 122.0)                                          # (the run as a whole: slower than g)
        out, plan = run(m)
        self.assertLess(float(np.abs(shoes(out, F)["右"]["low"][20:32]).max()), 0.1)
        d = world_y(out, F, "センター") - world_y(m, F, "センター")
        self.assertLess(float(np.abs(d).max()), 0.05)                                # under 4 mm
        for name in ("センター", "下半身"):
            self.assertLess(float(down_acc(world_y(out, F, name))[19:33].max()), 122.0 + 0.5)

    def test_a_hover_with_both_feet_gliding_just_over_the_floor_stands_on_the_lower(self):
        # both feet 1 cm (left) and 1.2 cm (right) up over frames 20-27, travelling 0.25 units a frame, the pelvis level
        # (no fall: the dance holds the body up there).  Lower than a shoe the skirt's bound counts as standing
        # (AIR_CLEAR): the lower foot is the dance's support gliding along the floor (v11feet 2026-10-17: after the
        # retarget the song's hovers made hops 55 times, the air 12 a minute against people's 1.3 [0, 2.9]); no hop is made
        F, a, b = 60, 20, 27

        def foot(lift):
            def f(t):
                x = 0.25 * min(max(t - a + 1, 0), b - a + 1)
                return (x, lift if a <= t <= b else 0.0, 0.0), None
            return f
        m = dance(F, centre=lambda t: (0.25 * min(max(t - a + 1, 0), b - a + 1), BENT, 0.0), left=foot(0.125), right=foot(0.15))
        out, plan = run(m)
        b_ = shoes(out, F)
        self.assertTrue(bool(plan["sides"]["左"]["stance"][a:b + 1].all()))
        self.assertEqual(plan["flight_rows"]["flights"], [])
        self.assertLess(float(np.abs(b_["左"]["low"][a:b + 1]).max()), 0.1)              # the lower foot on the floor
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)
        self.assertGreater(float(b_["右"]["low"][a:b + 1].min()), 0.4)                   # the other stays up

    def test_a_low_hover_whose_pelvis_falls_past_the_bound_on_a_frame_stays_a_hop(self):
        # the same feet, the pelvis dropping 1.5 cm in one frame in the middle of the run (past the skirt's bound): a hop,
        # not a glide (a floor frame may not fall that fast)
        F, a, b = 60, 20, 27

        def foot(lift):
            def f(t):
                x = 0.25 * min(max(t - a + 1, 0), b - a + 1)
                return (x, lift if a <= t <= b else 0.0, 0.0), None
            return f
        m = dance(F, centre=lambda t: (0.25 * min(max(t - a + 1, 0), b - a + 1), BENT - (0.1875 if t >= 24 else 0.0), 0.0),
                  left=foot(0.125), right=foot(0.15))
        out, plan = run(m)
        self.assertFalse(bool(plan["sides"]["左"]["stance"][a:b + 1].any()))

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

    def test_a_turn_over_still_feet_is_brought_within_the_bound_by_a_small_lowering(self):
        # the trace's pelvis at 40.0-40.4 s of Hibikase (16.6 cm up in 7 frames, turned in one frame at 281 units/s^2)
        # over both feet held still 3 cm up: the feet stand and the turn comes within the skirt's bound by a lowering
        # at the turn of under 2 cm (mv_inspect counts a jump's top 2 cm and more under the dance's; the lowering as
        # smooth as a weight-bearing one was 2.88 cm, the least the bound needs some 1.3)
        Y = [83.2, 85.8, 88.2, 90.5, 92.9, 95.5, 98.1, 99.8, 99.0, 97.2, 95.4, 93.7, 93.0]
        F, a = 56, 18
        m = dance(F, centre=lambda t: (0.0, -0.6 + (Y[min(max(t - a, 0), 12)] - 99.8) / CM, 0.0),
                  left=lambda t: ((0.0, 0.375, 0.0), None), right=lambda t: ((0.0, 0.375, 0.0), None))
        self.assertGreater(float(down_acc(world_y(m, F, "センター")).max()), 250.0)    # (as built: the turn)
        self.assertGreater(float(shoes(m, F)["左"]["low"][10:46].min()), 2.5)          # (and the feet 3 cm up)
        out, plan = run(m)
        st = plan["sides"]["左"]["stance"] & plan["sides"]["右"]["stance"]
        self.assertTrue(bool(st[a:a + 13].all()))                                     # a step on both feet
        for name in ("センター", "下半身"):
            self.assertLess(float(down_acc(world_y(out, F, name))[st].max()), 122.0 + 0.5)
        d = (world_y(m, F, "センター") - world_y(out, F, "センター")) * CM
        self.assertLess(float(d.max()), 2.0)
        self.assertGreater(float(d.min()), -1e-6)

    def test_the_least_lowering_at_a_turn_holds_where_a_need_nearby_joins_its_window(self):
        # the same turn with a weight-bearing need 1 cm deep 20 frames after it (the song's 41.7 s after 40.13 s): the
        # windows join, and the lowering at the turn stays the least one (a weight per window brought back 2.85 cm)
        F = 80
        fall = np.zeros(F)
        fall[30] = 281.0
        fall[29], fall[31] = 101.0, 112.0
        strict = np.zeros(F, bool)
        strict[30] = True
        allowed = np.maximum(122.0, fall) + 0.25
        allowed = np.where(strict, 122.25, allowed)
        need0 = np.zeros(F)
        z0, _ = contact_layer.drop_profile(need0, np.ones(F, bool), fall, allowed, F, strict=strict,
                                           strict_smooth=contact_layer.STRICT_SMOOTH)
        need = np.zeros(F)
        need[50:53] = 1.0 / CM
        z1, rows = contact_layer.drop_profile(need, np.ones(F, bool), fall, allowed, F, strict=strict,
                                              strict_smooth=contact_layer.STRICT_SMOOTH)
        self.assertEqual(len(rows), 1)                                                # (as built: one window)
        self.assertLess(abs(float(z1[25:36].max()) - float(z0[25:36].max())) * CM, 0.1)
        self.assertGreater(float(z1[50:53].min()) * CM, 1.0 - 1e-6)


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


class FrameRaiseTest(unittest.TestCase):
    def test_a_frame_the_layer_leaves_deeper_in_the_floor_than_the_input_is_raised(self):
        # the shoes' lowest points over the floor (units) as the layer leaves them and as the input had them: a frame
        # deeper than the input by more than a quarter of PEN_TOL (0.4 mm) is raised by that and a quarter more (a push
        # that overshoots: the song's 252.4 s, 1.04 mm under the floor); the input's own depth stays
        tol = contact_layer.FL.PEN_TOL
        out = np.array([0.0, -0.2 * tol, -2.0 * tol, -3.0 * tol, 0.01])
        inp = np.array([0.0, 0.0, 0.0, -2.5 * tol, 0.01])
        up = contact_layer.frame_raise(out, inp)
        self.assertEqual([float(v) for v in up[[0, 1, 4]]], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(float(up[2]), 2.25 * tol, places=12)
        self.assertAlmostEqual(float(up[3]), 0.75 * tol, places=12)


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


def run400(m, **params):
    return contact_layer.layer(MODEL400, RIG400, SHOE400, m, params)


def rest_of(rig, name):
    return np.array(rig.bones[rig.by_name[name]].position, dtype=float)


def goal_offset(rig, s, centre, ratio, direction):
    """the 足ＩＫ offset that puts side s's goal `ratio` of the leg's reach (rig_check's max_reach) from its hip along
    `direction`, the hip moved by the センター offset `centre` (the bodies here have no turns above the legs)"""
    hip = rest_of(rig, s + "足") + np.asarray(centre, dtype=float)
    d = np.asarray(direction, dtype=float)
    goal = hip + ratio * rig_check.max_reach(rig, s) * d / np.linalg.norm(d)
    return tuple(float(v) for v in goal - rest_of(rig, s + "足首"))


def knee_jumps(rig, m, F):
    """(side -> rig_check ik's knee jump events, the legs as MMD's IK solves them)"""
    sol = leg_ik.solve(rig, m, range(F))
    nums = rig_check._ik_numbers(rig, sol)
    return {s: nums[s]["knee_jump_events"] for s in SIDES}, sol


def bend_of(sol, s):
    return np.degrees(-sol[s]["knee_angle"])


def pitch_of(sol, s):
    """the foot's pitch against the floor [F] (degrees, + toes up, - the heel up), as the foot layer reads it"""
    return contact_layer.FL.world_pitch_roll(SHOE400.sides[s], sol[s]["q_foot"])[0]


class KneeTest(unittest.TestCase):
    """the knee near the end of its reach (v7's leg IK reaches its goal): MMD's IK snaps a knee straight on the frame its
    goal comes to the leg's reach, and a goal at the reach for a frame or two straightens it for those frames only (the
    review of rig, 2026-10-17: 45 -> 70 jumps on main's chain, the song's 2226 a left knee 23 -> 4 -> 37 degrees).  Measured
    by rig_check ik (a frame more than 10 degrees off the line through its neighbours)"""

    def test_a_swing_leg_snapping_straight_in_the_air_comes_round_to_its_reach(self):
        # the right leg swings forward and down in the air (its shoe 15 cm and more over the floor), its goal going from
        # 0.85 of the leg's reach to 1.05 in steps of 0.05 a frame and back: MMD's IK snaps the knee straight on the
        # first frame at the reach (15 degrees off the line through its neighbours).  The layer bends that frame to
        # within KNEE_POP_DEG of the line: no jump, no goal moved outside the band near the reach, the ankle no further
        # than that band from the dance's goal where the leg reaches it
        F = 40
        ratios = [0.85] * 12 + [0.90, 0.95, 1.00] + [1.05] * 6 + [1.00, 0.95, 0.90] + [0.85] * 16
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre, right=lambda t: (goal_offset(RIG400, "右", centre, ratios[t], ahead), None),
                  rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreaterEqual(len(ev0["右"]), 2)                                       # (as built: the two snaps)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        band = contact_layer.KNEE_NEAR * rig_check.max_reach(RIG400, "右")
        g0, g1 = sol0["右"]["goal_ankle"], sol1["右"]["goal_ankle"]
        outside = np.array(ratios) < 1.0 - contact_layer.KNEE_NEAR
        self.assertLess(float(np.abs(g1[outside] - g0[outside]).max()), 1e-6)
        reached = np.array(ratios) <= 1.0
        self.assertLess(float(np.linalg.norm(sol1["右"]["ankle"] - g0, axis=1)[reached].max()), band)
        self.assertGreater(float(np.linalg.norm(g1 - g0, axis=1).max()), 0.01)        # (it did move the goal)
        self.assertLess(float(np.abs(sol1["左"]["goal_ankle"] - sol0["左"]["goal_ankle"]).max()), 1e-6)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_swing_leg_snapping_straight_beyond_its_reach_keeps_its_foot_turned_as_it_was(self):
        # as above but the goal goes 0.95 -> 1.03 of the reach in a frame (MMD's leg straight, its ankle short of the goal):
        # that frame's goal is brought into the reach, and its toe IK's goal moves with MMD's ankle, not with the goal, so
        # that the foot keeps its turn in the world (つま先ＩＫ is a child of 足ＩＫ: left alone, the foot would turn to it)
        F = 40
        ratios = [0.85] * 12 + [0.90, 0.95] + [1.03] * 7 + [0.95, 0.90] + [0.85] * 17
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre, right=lambda t: (goal_offset(RIG400, "右", centre, ratios[t], ahead), None),
                  rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(float(sol0["右"]["reach"][14]) * CM, 1.0)                    # (as built: 2 cm short there)
        self.assertGreaterEqual(len(ev0["右"]), 2)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        moved = np.linalg.norm(sol1["右"]["goal_ankle"] - sol0["右"]["goal_ankle"], axis=1)
        self.assertGreater(float(moved[14]) * CM, 1.0)                                # the goal brought in ...
        dq = np.abs(np.sum(sol1["右"]["q_foot"] * sol0["右"]["q_foot"], axis=1))
        self.assertLess(float(np.degrees(2.0 * np.arccos(np.clip(dq, 0.0, 1.0))).max()), 1.0)   # ... the foot as it was
        dt = np.linalg.norm((sol1["右"]["goal_toe"] - sol0["右"]["goal_toe"]) - (sol1["右"]["ankle"] - sol0["右"]["ankle"]),
                            axis=1)
        self.assertLess(float(dt.max()) * CM, 0.1)

    def test_a_swing_leg_straight_for_one_frame_bends_like_the_frames_round_it(self):
        # the right leg in the air at 0.95 of its reach, at the reach on frame 20 alone (a trace's one-frame jump): the knee
        # straight on that frame, 31 degrees off its neighbours.  The layer bends it there to within KNEE_POP_DEG of the
        # line through its neighbours and moves no other frame
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, 1.0 if t == 20 else 0.95, ahead), None), rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 20.0)                      # (as built)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        k = bend_of(sol1, "右")
        self.assertLess(0.5 * (k[19] + k[21]) - k[20], contact_layer.KNEE_POP_DEG + 0.5)
        g0, g1 = sol0["右"]["goal_ankle"], sol1["右"]["goal_ankle"]
        other = np.arange(F) != 20
        self.assertLess(float(np.abs(g1[other] - g0[other]).max()), 1e-6)

    def test_a_standing_leg_straight_on_its_last_frame_before_it_lifts_rises_onto_its_toes(self):
        # the left foot on the floor out to the side (its leg at 0.96 of the reach), pushed 9 cm further out on frame 20
        # (the leg at its reach, straight: 27 degrees off its neighbours) and lifted from frame 21; the right foot stands
        # under the body.  On frame 20 the layer turns the left foot onto its toes (the heel up, the toes where they were)
        # until its knee is within KNEE_POP_DEG of the line through its neighbours: no jump, the shoe still on the floor,
        # the pelvis and the right leg as they were (the song's 2226: the left foot's last frame before it lifts)
        F = 30
        L = rig_check.max_reach(RIG400, "左")
        foot = rest_of(RIG400, "左足首") + np.array([2.5, 0.0, 0.0])
        hip_xz = rest_of(RIG400, "左足") + np.array([0.5, 0.0, 0.0])
        flat = np.hypot(foot[0] - hip_xz[0], foot[2] - hip_xz[2])
        up = math.sqrt((0.96 * L) ** 2 - flat ** 2)
        centre = (0.5, foot[1] + up - rest_of(RIG400, "左足")[1], 0.0)
        push = math.sqrt(L * L - up * up - (foot[2] - hip_xz[2]) ** 2) - (foot[0] - hip_xz[0])

        def left(t):
            if t < 20:
                return (2.5, 0.0, 0.0), None
            return (2.5 + push, min(0.35 * (t - 20), 1.05), 0.0), None
        m = dance(F, centre=lambda t: centre, left=left, rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["左"]), 20.0)                      # (as built: frame 20 straight)
        tr0 = sink_check.shoe_track(RIG400, DOC400, m, range(F))
        self.assertLess(float(np.abs(tr0["左"]["low"][:21] - FLOOR).max()) * CM, 0.05)   # (on the floor to frame 20)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["左"]["stance"][20]))                        # (a standing foot there)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["左"], [])
        k = bend_of(sol1, "左")
        self.assertLess(0.5 * (k[19] + k[21]) - k[20], contact_layer.KNEE_POP_DEG + 0.5)
        self.assertLess(float(pitch_of(sol1, "左")[20] - pitch_of(sol0, "左")[20]), -3.0)   # the heel up
        tr = sink_check.shoe_track(RIG400, DOC400, out, range(F))
        self.assertLess(abs(float(tr["左"]["low"][20]) - FLOOR) * CM, 0.1)            # the toes on the floor
        self.assertLess(float(np.linalg.norm(sol1["左"]["goal_toe"][20] - sol0["左"]["goal_toe"][20])) * CM, 0.5)
        g0, g1 = sol0["左"]["goal_ankle"], sol1["左"]["goal_ankle"]
        self.assertLess(float(np.abs(g1[:20] - g0[:20]).max()), 1e-6)
        self.assertLess(float(np.abs(sol1["右"]["goal_ankle"] - sol0["右"]["goal_ankle"]).max()), 1e-6)
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_foot_on_its_toes_a_frame_before_it_lifts_keeps_its_heel_up_until_it_does(self):
        # the take-off above with the push on frame 19 alone (back at 0.96 of the reach on frame 20, lifted from 21): frame
        # 19 rises onto the toes, and frame 20, the last before the lift, stays on them (the heel does not come down for a
        # frame between the push and the lift)
        F = 30
        L = rig_check.max_reach(RIG400, "左")
        foot = rest_of(RIG400, "左足首") + np.array([2.5, 0.0, 0.0])
        hip_xz = rest_of(RIG400, "左足") + np.array([0.5, 0.0, 0.0])
        flat = np.hypot(foot[0] - hip_xz[0], foot[2] - hip_xz[2])
        up = math.sqrt((0.96 * L) ** 2 - flat ** 2)
        centre = (0.5, foot[1] + up - rest_of(RIG400, "左足")[1], 0.0)
        push = math.sqrt(L * L - up * up - (foot[2] - hip_xz[2]) ** 2) - (foot[0] - hip_xz[0])

        def left(t):
            if t == 19:
                return (2.5 + push, 0.0, 0.0), None
            return (2.5, min(0.35 * max(t - 20, 0), 1.05), 0.0), None
        m = dance(F, centre=lambda t: centre, left=left, rig=RIG400)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["左"]["stance"][19]) and bool(plan["sides"]["左"]["stance"][20]))
        self.assertFalse(bool(plan["sides"]["左"]["stance"][21]))                      # (as built: it lifts at 21)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["左"], [])
        _, sol0 = knee_jumps(RIG400, m, F)
        turn = pitch_of(sol1, "左") - pitch_of(sol0, "左")
        self.assertLess(float(turn[19]), -3.0)                                       # on the toes at the push ...
        self.assertLess(float(turn[20]), float(turn[19]) + 0.01)                     # ... and still at the last frame
        tr = sink_check.shoe_track(RIG400, DOC400, out, range(F))
        # the toes on the floor as the layer counts it (the turn between frames 18 and 19 dips the shoe's front a little
        # into the floor as MMD draws it in between, and 7. raises both frames by that, about a millimetre)
        self.assertLess(float(np.abs(tr["左"]["low"][18:21] - FLOOR).max()), contact_layer.ON_FLOOR)

    def test_a_leg_reaching_forward_straight_onto_the_floor_lands_on_its_heel(self):
        # the right foot comes down in front of the body onto the floor at frame 20 with the leg at its reach (straight),
        # and the body comes forward over it after (the knee bends): 15 degrees off the line through its neighbours.  On
        # frame 20 the layer turns the foot toes up about its heel (a heel strike: the hip behind the foot), not onto its
        # toes, until the knee is within KNEE_POP_DEG of that line; the shoe stays on the floor
        F = 34
        L = rig_check.max_reach(RIG400, "右")
        hip0 = rest_of(RIG400, "右足") + np.array([0.0, BENT, 0.0])
        ankle0 = rest_of(RIG400, "右足首")
        up = hip0[1] - ankle0[1]
        dx = ankle0[0] - hip0[0]
        ahead = math.sqrt(L * L - up * up - dx * dx)
        land = (0.0, 0.0, hip0[2] - ahead - ankle0[2])

        def right(t):
            if t < 20:
                return (0.0, 0.1 * (20 - t), land[2]), None
            return land, None

        def centre(t):
            return (0.0, BENT, -0.3 * min(max(t - 20, 0), 4))
        m = dance(F, centre=centre, right=right, rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 10.0)                      # (as built)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["右"]["stance"][20]))
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        k = bend_of(sol1, "右")
        self.assertLess(0.5 * (k[19] + k[21]) - k[20], contact_layer.KNEE_POP_DEG + 0.5)
        self.assertGreater(float(pitch_of(sol1, "右")[20] - pitch_of(sol0, "右")[20]), 0.5)  # the toes up
        tr = sink_check.shoe_track(RIG400, DOC400, out, range(F))
        self.assertLess(abs(float(tr["右"]["low"][20]) - FLOOR) * CM, 0.1)            # the heel on the floor
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_foot_landing_beyond_its_reach_moves_in_and_keeps_its_turn(self):
        # the right foot comes down in front of the body (its leg at 0.95 of the reach in the air) onto a goal on the floor
        # 3 % beyond the reach on frames 20 and 21 (MMD leaves the foot short of it in the air, the knee straight), and the
        # body comes forward over it from frame 22: the plan stands the foot there (judged at its goal), but its foot is
        # not on the floor, so the layer brings the goal in as a swing foot's (no turn of the foot, its turn in the world
        # kept) there: no jump (frame 22, on the floor and reached, may turn a little for the frames before it)
        F = 34
        L = rig_check.max_reach(RIG400, "右")
        hip0 = rest_of(RIG400, "右足") + np.array([0.0, BENT, 0.0])
        ankle0 = rest_of(RIG400, "右足首")
        up = hip0[1] - ankle0[1]
        dx = ankle0[0] - hip0[0]
        ahead = math.sqrt((1.03 * L) ** 2 - up * up - dx * dx)
        land = (0.0, 0.0, hip0[2] - ahead - ankle0[2])
        down = ankle0 + np.array(land) - hip0

        def right(t):
            if t < 20:
                return goal_offset(RIG400, "右", (0.0, BENT, 0.0), 0.95, down), None
            return land, None

        def centre(t):
            return (0.0, BENT, -0.5 * min(max(t - 21, 0), 4))
        m = dance(F, centre=centre, right=right, rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(float(sol0["右"]["reach"][20]) * CM, 1.0)                    # (as built: short of the goal)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 10.0)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["右"]["stance"][20]) and bool(plan["sides"]["右"]["stance"][21]))
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        self.assertEqual([float(x) for x in plan["knee"]["右"]["turn_deg"][20:22]], [0.0, 0.0])
        self.assertGreater(float(plan["knee"]["右"]["moved"][20:22].min()) * CM, 0.5)       # brought in on both
        dq = np.abs(np.sum(sol1["右"]["q_foot"] * sol0["右"]["q_foot"], axis=1))
        self.assertLess(float(np.degrees(2.0 * np.arccos(np.clip(dq, 0.0, 1.0)))[:22].max()), 1.0)
        tr = sink_check.shoe_track(RIG400, DOC400, out, range(F))
        self.assertGreater(float(tr["右"]["low"].min()) - FLOOR, -contact_layer.FL.PEN_TOL)   # never into the floor

    def test_a_foot_ahead_of_the_body_straight_on_its_last_frame_lifts_a_frame_early(self):
        # the right foot on the floor ahead of the body (its leg at 0.96 of the reach), pushed further ahead on frame 20 (the
        # leg straight) and lifted from frame 21; the left foot stands under the body.  Onto its toes (the push-off) would
        # take the ankle further from the hip, onto its heel is no push-off: the foot lifts a frame early instead (its goal
        # brought toward the hip, its turn kept)
        F = 30
        L = rig_check.max_reach(RIG400, "右")
        hip0 = rest_of(RIG400, "右足") + np.array([0.0, BENT, 0.0])
        ankle0 = rest_of(RIG400, "右足首")
        up = hip0[1] - ankle0[1]
        dx = ankle0[0] - hip0[0]

        def at(ratio):
            return hip0[2] - math.sqrt((ratio * L) ** 2 - up * up - dx * dx) - ankle0[2]

        def right(t):
            if t < 20:
                return (0.0, 0.0, at(0.96)), None
            return (0.0, min(0.35 * (t - 20), 1.05), at(1.0)), None
        m = dance(F, right=right, rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 10.0)                      # (as built: frame 20 straight)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["右"]["stance"][20]))
        self.assertFalse(bool(plan["sides"]["右"]["stance"][21]))
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        self.assertEqual(float(plan["knee"]["右"]["turn_deg"][20]), 0.0)
        dq = np.abs(np.sum(sol1["右"]["q_foot"] * sol0["右"]["q_foot"], axis=1))
        self.assertLess(float(np.degrees(2.0 * np.arccos(np.clip(dq, 0.0, 1.0))).max()), 1.0)
        tr = sink_check.shoe_track(RIG400, DOC400, out, range(F))
        self.assertGreater(float(tr["右"]["low"][20] - FLOOR) * CM, 0.4)               # lifted on frame 20
        self.assertLess(float(np.abs(world_y(out, F, "センター") - world_y(m, F, "センター")).max()), 1e-6)

    def test_a_standing_leg_held_straight_keeps_its_foot(self):
        # both feet on the floor under a pelvis high enough that the left leg stands at 0.999 of its reach (2 degrees from
        # its end) for 30 frames: no knee pops, so the layer leaves the dance as it is (a straight standing leg is not
        # bent for no jump: that would raise its heel)
        F = 30
        L = rig_check.max_reach(RIG400, "左")
        foot = rest_of(RIG400, "左足首")
        hip = rest_of(RIG400, "左足")
        flat = np.hypot(foot[0] - hip[0], foot[2] - hip[2])
        centre = (0.0, foot[1] + math.sqrt((0.999 * L) ** 2 - flat ** 2) - hip[1], 0.0)
        m = dance(F, centre=lambda t: centre, rig=RIG400)
        self.assertLess(float(bend_of(leg_ik.solve(RIG400, m, range(F)), "左").max()), 4.0)   # (as built: straight)
        out, plan = run400(m)
        self.assertIs(out, m)

    def test_a_fast_bend_far_from_the_reach_is_left_as_the_dance_has_it(self):
        # the right leg in the air at 0.6 of its reach, at 0.8 on frame 20 (the knee unbends 35 degrees for a frame, far
        # from straight: a quick move of the dance, not the IK's snap at the reach): left alone
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, 0.8 if t == 20 else 0.6, ahead), None), rig=RIG400)
        ev0, _ = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 20.0)                      # (as built)
        out, plan = run400(m)
        self.assertIs(out, m)

    def test_a_turn_is_held_on_to_the_nearer_end_of_its_run_only(self):
        # carry_to_edges on standing runs with the air round them: a turn two frames before a long run's end is held on to
        # that end (the foot lifts after it), one two frames after its start back to the start (the foot lands there); a
        # short run's turn on its last frame (a take-off, the song's 2226 on a run of 3) is not carried back to its first
        # frames, nor a turn in the middle of a long run anywhere
        st = np.zeros(30, dtype=bool)
        st[2:14] = True                     # a long run, 2..13
        st[18:21] = True                    # a short one, 18..20
        turn = np.zeros(30)
        turn[11], turn[4], turn[8], turn[20] = 5.0, -3.0, 7.0, 4.0
        out = contact_layer.carry_to_edges(turn, st, edge=3)
        self.assertEqual([float(x) for x in out[11:14]], [5.0, 5.0, 5.0])
        self.assertEqual([float(x) for x in out[2:5]], [-3.0, -3.0, -3.0])
        self.assertEqual([float(x) for x in out[5:11]], [0.0, 0.0, 0.0, 7.0, 0.0, 0.0])
        self.assertEqual([float(x) for x in out[18:21]], [0.0, 0.0, 4.0])

    def test_a_held_turn_stops_at_a_frame_that_does_not_take_it(self):
        # carry_to_edges with allow: a turn held on toward a run's end goes no further than the first frame that refuses it
        # (the knee step refuses a turn that would take the ankle further from the hip there: the song's 2371-2372, a
        # right foot's 2 degrees onto its toes held on from 2370 straightened its knee by 0.4 and 1.4 degrees)
        st = np.zeros(20, dtype=bool)
        st[2:12] = True                     # a run 2..11, the foot lifting after 11
        turn = np.zeros(20)
        turn[9] = 5.0
        refused = []

        def allow(t, d):
            refused.append(t)
            return t != 10
        out = contact_layer.carry_to_edges(turn, st, edge=3, allow=allow)
        self.assertEqual([float(x) for x in out[8:12]], [0.0, 5.0, 0.0, 0.0])
        self.assertEqual(refused, [10])                                               # (11 is not asked: the carry stopped)
        out = contact_layer.carry_to_edges(turn, st, edge=3, allow=lambda t, d: True)
        self.assertEqual([float(x) for x in out[8:12]], [0.0, 5.0, 5.0, 5.0])

    def test_the_band_is_a_part_of_the_leg(self):
        # knee_targets on one leg and on the same leg 1.6 times as long with the distances 1.6 times as long: the same
        # bends and 1.6 times the distances (the band near the reach is a part of the leg's reach)
        rng = np.random.default_rng(3)
        L1, L2, rest_deg = 4.43, 4.51, 5.74
        L = math.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * math.cos(math.radians(rest_deg)))
        D = L * np.clip(0.97 + 0.03 * rng.standard_normal(200), 0.5, 1.1)
        a = contact_layer.knee_targets(D, L1, L2, rest_deg)
        b = contact_layer.knee_targets(1.6 * D, 1.6 * L1, 1.6 * L2, rest_deg)
        self.assertGreater(float(np.abs(a["target"] - D).max()), 0.01)                # (something to do)
        self.assertLess(float(np.abs(b["target"] - 1.6 * a["target"]).max()), 1e-9)
        self.assertLess(float(np.abs(b["bend"] - a["bend"]).max()), 1e-6)

    # (the review of kneepop, 2026-10-17: what the step's doc promises and no test held: the band's edge, the bend no
    # further than it, the lesser of the two turns, the plan on the dance as 1.-5. leave it)

    def test_a_quick_bend_just_short_of_the_band_is_left_as_the_dance_has_it(self):
        # the right leg in the air at 0.90 of its reach, at 0.94 on frame 20: the knee unbends some 12 degrees for a frame
        # (a jump as rig_check counts it), but the leg stays short of the band at the end of its reach (the last 5 % of
        # it): a quick move of the dance, not the IK's snap, left as it is
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, 0.94 if t == 20 else 0.90, ahead), None), rig=RIG400)
        ev0, _ = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["右"]), 10.0)                      # (as built)
        out, plan = run400(m)
        self.assertIs(out, m)

    def test_a_straight_frame_is_bent_no_further_than_the_band_edge(self):
        # the right leg in the air at 0.90 of its reach (the knee bent some 46 degrees), at the reach on frame 20 (straight):
        # the layer bends that frame only as far as the knee's bend at the band's edge (its goal brought to 0.95 of the
        # reach, no nearer the hip), so a jump stays there; the other frames are the dance's
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        L = rig_check.max_reach(RIG400, "右")
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, 1.0 if t == 20 else 0.90, ahead), None), rig=RIG400)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        D = np.linalg.norm(sol1["右"]["goal_ankle"] - sol1["右"]["hip"], axis=1)
        self.assertLess(abs(float(D[20]) / L - 0.95), 0.001)                           # to the band's edge, no further
        self.assertGreater(max(e["deg"] for e in ev1["右"]), 10.0)                      # (so the jump stays, smaller)
        _, sol0 = knee_jumps(RIG400, m, F)
        other = np.arange(F) != 20
        self.assertLess(float(np.abs(sol1["右"]["goal_ankle"] - sol0["右"]["goal_ankle"])[other].max()), 1e-6)

    def test_the_lesser_of_the_two_turns_is_taken(self):
        # knee_turn on a flat sole along -Z (its front at z -1, its back at +1), the ankle 1 over it and 0.5 behind its
        # middle, the hip 8 over the ankle: 0.0625 nearer needs some 2.4 degrees onto the toes (the ankle rises 1.5 a
        # radian about the front) or 7.2 onto the heel (0.5 a radian about the back), and the toes are taken.  The hip 6
        # over and 5.3 behind instead: some 7.7 onto the toes (the ankle goes forward, away from it) or 3.5 onto the heel,
        # and the heel is taken
        shell = np.array([[x, 0.0, z] for x in (-0.3, 0.3) for z in (-1.0, -0.5, 0.0, 0.5, 1.0)])
        front, back = np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])
        axis = np.array([-1.0, 0.0, 0.0])                       # (+ about it lowers the toes: the heel at +z goes up)
        goal = np.array([0.0, 1.0, 0.5])
        up_toes = contact_layer.foot_turned(front, axis, np.array([math.radians(5.0)]), goal, shell)[0][0]
        self.assertGreater(float(up_toes[1]), float(goal[1]))                         # (as built: the ankle rises onto the toes)
        d, ok = contact_layer.knee_turn(goal + np.array([0.0, 8.0, 0.0]), goal, 8.0 - 0.0625, front, back, axis, shell)
        self.assertTrue(ok)
        self.assertGreater(d, 1.5)
        self.assertLess(d, 3.5)
        d, ok = contact_layer.knee_turn(goal + np.array([0.0, 6.0, 5.3]), goal, 8.0 - 0.0625, front, back, axis, shell)
        self.assertTrue(ok)
        self.assertLess(d, -2.5)
        self.assertGreater(d, -4.5)

    def test_a_knee_a_little_straighter_than_its_neighbours_is_no_jump_and_is_left_alone(self):
        # the take-off of test_a_standing_leg_straight_on_its_last_frame_before_it_lifts_rises_onto_its_toes with a
        # smaller push on frame 20 (the leg at 0.968 of its reach, not at it): the knee there is some 8.5 degrees
        # straighter than the line through its neighbours, which rig_check does not count as a jump.  The knee step
        # leaves it: turning the foot onto its toes for it would flick the foot where no knee jumps (the review of
        # kneepop: the song's 249.9 s, a right foot turned 13 degrees for an 8.7-degree kink, the foot's pitch then 13
        # degrees off the line through its neighbours)
        F = 30
        L = rig_check.max_reach(RIG400, "左")
        foot = rest_of(RIG400, "左足首") + np.array([2.5, 0.0, 0.0])
        hip_xz = rest_of(RIG400, "左足") + np.array([0.5, 0.0, 0.0])
        flat = np.hypot(foot[0] - hip_xz[0], foot[2] - hip_xz[2])
        up = math.sqrt((0.96 * L) ** 2 - flat ** 2)
        centre = (0.5, foot[1] + up - rest_of(RIG400, "左足")[1], 0.0)
        push = math.sqrt((0.968 * L) ** 2 - up * up - (foot[2] - hip_xz[2]) ** 2) - (foot[0] - hip_xz[0])

        def left(t):
            if t < 20:
                return (2.5, 0.0, 0.0), None
            return (2.5 + push, min(0.35 * (t - 20), 1.05), 0.0), None
        m = dance(F, centre=lambda t: centre, left=left, rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        k = bend_of(sol0, "左")
        self.assertGreater(0.5 * (k[19] + k[21]) - k[20], contact_layer.KNEE_POP_DEG + 1.0)   # (as built: a kink ...)
        self.assertEqual(ev0["左"], [])                                                       # (... no jump)
        out, plan = run400(m)
        out_nk, _ = run400(m, knee=False)
        self.assertEqual(float(np.abs(plan["knee"]["左"]["turn_deg"]).max()), 0.0)
        self.assertEqual(vmd.dumps(out), vmd.dumps(out_nk))

    def test_a_frame_left_straight_next_to_a_bent_one_is_bent_too(self):
        # the right leg in the air unbending fast into a reach it then holds beyond (0.87, 0.89, 0.98 of the reach, then
        # 1.03: the knee 54, 49, 18, then straight): the jump is frame 18, bent more than the line through its neighbours.
        # Bending frame 19 for it leaves frame 20 straight between a bent frame and straight ones, a jump the input did not
        # have (the song's 196.97 s); the step bends the frames such a bending makes jump too, and leaves no jump
        F = 40
        ratios = [0.87] * 18 + [0.89, 0.98] + [1.03] * 20
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre, right=lambda t: (goal_offset(RIG400, "右", centre, ratios[t], ahead), None),
                  rig=RIG400)
        ev0, _ = knee_jumps(RIG400, m, F)
        self.assertEqual([e["peak"] for e in ev0["右"]], [18])                       # (as built: the jump is frame 18)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        self.assertGreater(float(bend_of(sol1, "右")[20]), 1.0)                        # (frame 20 bent too)

    def test_a_standing_foot_in_the_middle_of_its_run_is_not_turned_for_one_frame(self):
        # the take-off's stance without the lift: the left foot pushed out to the leg's reach on frame 20 alone and back
        # on the floor where it was from 21 (a frame of the trace's jitter in the middle of a stand): the knee straight for
        # that frame, a jump.  Turning the foot onto its toes or its heel there would raise the heel (or the toes) for one
        # frame and set it down again, a flick of the foot in the middle of a stand (the review of kneepop: retarget's
        # 251.0 s, a right foot's heel up 8 and 10 degrees on every other frame); the knee step turns a standing foot only
        # by a lift or a landing, and leaves this one
        F = 40
        L = rig_check.max_reach(RIG400, "左")
        foot = rest_of(RIG400, "左足首") + np.array([2.5, 0.0, 0.0])
        hip_xz = rest_of(RIG400, "左足") + np.array([0.5, 0.0, 0.0])
        flat = np.hypot(foot[0] - hip_xz[0], foot[2] - hip_xz[2])
        up = math.sqrt((0.96 * L) ** 2 - flat ** 2)
        centre = (0.5, foot[1] + up - rest_of(RIG400, "左足")[1], 0.0)
        push = math.sqrt(L * L - up * up - (foot[2] - hip_xz[2]) ** 2) - (foot[0] - hip_xz[0])
        m = dance(F, centre=lambda t: centre, left=lambda t: ((2.5 + (push if t == 20 else 0.0), 0.0, 0.0), None),
                  rig=RIG400)
        ev0, _ = knee_jumps(RIG400, m, F)
        self.assertGreater(max(e["deg"] for e in ev0["左"]), 10.0)                      # (as built: a jump)
        out, plan = run400(m)
        self.assertTrue(bool(plan["sides"]["左"]["stance"][15:26].all()))             # (standing round it)
        self.assertEqual(float(np.abs(plan["knee"]["左"]["turn_deg"]).max()), 0.0)
        _, sol0 = knee_jumps(RIG400, m, F)
        _, sol1 = knee_jumps(RIG400, out, F)
        self.assertLess(float(np.abs(pitch_of(sol1, "左") - pitch_of(sol0, "左")).max()), 0.1)

    def test_the_knee_step_reads_the_dance_as_the_steps_before_leave_it(self):
        # the wide stance of GroundTest whose pelvis rises until the left leg cannot reach its goal on the floor, with v7's
        # leg IK: the layer lowers the pelvis (3.) so that the leg reaches its goal, and its knee straightens over more
        # frames than the input's (some 5 degrees apart on frames 18-21).  The knee step reads the legs as 1.-5. leave them
        # (the bends its report starts from are those of the layer's dance without the step, not the input's) and finds
        # nothing to do
        F = 60

        def centre(t):
            u = min(max((t - 10) / 15.0, 0.0), 1.0)
            return (1.0, BENT + 0.9 * u * u * (3.0 - 2.0 * u), 0.0)
        m = dance(F, centre=centre, left=lambda t: ((4.0, 0.0, 0.0), None), rig=RIG400)
        geo = contact_layer.knee_geometry(RIG400, "左")

        def bends(mo):
            sol = leg_ik.solve(RIG400, mo, range(F))
            return contact_layer.knee_bend(np.linalg.norm(sol["左"]["goal_ankle"] - sol["左"]["hip"], axis=1), *geo)
        out_nk, _ = run400(m, knee=False)
        k_in, k_nk = bends(m), bends(out_nk)
        self.assertGreater(float(np.abs(k_nk - k_in).max()), 3.0)                       # (as built: 3. bends the leg)
        out, plan = run400(m)
        self.assertLess(float(np.abs(np.asarray(plan["knee"]["左"]["bend0"]) - k_nk).max()), 0.05)
        self.assertEqual(int(np.sum(plan["knee"]["左"]["even"])), 0)
        self.assertEqual(vmd.dumps(out), vmd.dumps(out_nk))

    # (the review of integ, 2026-10-17: what the step's doc says and no test held: a snap is bent to 6 degrees off the
    # line through its neighbours and no further, and a change of the hip's distance to the goal under a millimetre is
    # none.  KNEE_POP_DEG 3 and KNEE_TOL 0 passed every test before these two)

    def test_a_snap_is_bent_to_six_degrees_off_its_neighbours_line_and_no_further(self):
        # the one-frame snap of test_a_swing_leg_straight_for_one_frame_bends_like_the_frames_round_it (the right leg in the
        # air at 0.95 of its reach, at the reach on frame 20: some 30 degrees off the line through its neighbours).  The
        # layer bends that frame to 6 degrees off that line, 4 under rig_check's count of a jump, and no further: the least
        # change of the dance (the frame stays straighter than its neighbours by those 6 degrees), neither laid onto the line
        # nor left near 10 degrees, where a later layer's centimetre would make it a jump again
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, 1.0 if t == 20 else 0.95, ahead), None), rig=RIG400)
        _, sol0 = knee_jumps(RIG400, m, F)
        k = bend_of(sol0, "右")
        self.assertGreater(0.5 * (k[19] + k[21]) - k[20], 20.0)                        # (as built: a snap)
        out, plan = run400(m)
        _, sol1 = knee_jumps(RIG400, out, F)
        k = bend_of(sol1, "右")
        off = 0.5 * (k[19] + k[21]) - k[20]
        self.assertGreater(off, 5.5)
        self.assertLess(off, 6.5)

    def test_a_change_of_the_reach_under_a_millimetre_is_not_made(self):
        # the right leg in the air with its knee bent 19 degrees, unbending to 6 on frame 18 and to its reach on frame 19
        # (straight: 11 degrees off the line through its neighbours, a jump), bent 19 again from frame 20.  Bending frame 19
        # to 6 degrees off its neighbours' line leaves frame 18 7 degrees straighter than its own, which would bend it 1
        # degree more: 0.7 mm of the hip's distance to the goal, less than MMD's IK tells (1 mm).  The layer moves frame
        # 19's goal (some 3.5 mm) and leaves frame 18's and every other frame's as the dance has them
        F = 40
        centre = (0.0, BENT, 0.0)
        ahead = (-0.25, -0.6, -0.76)
        L1, L2, rest_deg, _ = contact_layer.knee_geometry(RIG400, "右")
        L = rig_check.max_reach(RIG400, "右")
        bends = [19.0] * 18 + [6.0, 0.0] + [19.0] * 20

        def ratio(b):
            return float(contact_layer.knee_distance(b, L1, L2, rest_deg)) / L
        m = dance(F, centre=lambda t: centre,
                  right=lambda t: (goal_offset(RIG400, "右", centre, ratio(bends[t]), ahead), None), rig=RIG400)
        ev0, sol0 = knee_jumps(RIG400, m, F)
        self.assertEqual([e["peak"] for e in ev0["右"]], [19])                          # (as built: the jump is frame 19)
        need = float(contact_layer.knee_distance(6.0, L1, L2, rest_deg) - contact_layer.knee_distance(7.0, L1, L2, rest_deg))
        self.assertGreater(need * CM * 10.0, 0.3)                                        # (as built: frame 18's, in mm: some ...
        self.assertLess(need * CM * 10.0, 0.9)                                           # ... and under a millimetre)
        out, plan = run400(m)
        ev1, sol1 = knee_jumps(RIG400, out, F)
        self.assertEqual(ev1["右"], [])
        moved = np.linalg.norm(sol1["右"]["goal_ankle"] - sol0["右"]["goal_ankle"], axis=1) * CM * 10.0   # (mm)
        self.assertGreater(float(moved[19]), 2.0)
        self.assertLess(float(np.delete(moved, 19).max()), 1e-4)


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
