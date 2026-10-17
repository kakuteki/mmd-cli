"""tools/foot_layer.py: the feet measured as MMD shows them (the sole from the mesh, the angles of the ankle complex, the
contact with the floor), and the layer that makes them carry weight anatomically.  Checked by what the feet do: a
rolled foot is measured rolled and laid flat on the floor by the layer, the ball and the toes take a raised heel, the
sole neither sinks into nor hovers over the floor while loaded, the air keeps the dance's foot, nothing else moves."""
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
from tests.test_leg_ik import REST, axis_angle, key, rest, rin_legs_bytes  # noqa: F401
from tests.test_pmx import Writer
from tests.test_pmx_spine import load_tool

foot_layer = load_tool("foot_layer")
leg_ik = foot_layer.IK

# the left shoe's sole at rest (Sour's Rin's sizes: the heel block and the forefoot, the toe box on 足先EX); the
# right shoe mirrors x.  (x, y, z, weight on 足先EX)
SOLE = [(0.95, 0.111, 0.55, 0.0), (1.25, 0.111, 0.55, 0.0), (0.95, 0.111, 0.9, 0.0), (1.25, 0.111, 0.9, 0.0),
        (0.75, 0.112, -0.3, 0.1), (1.45, 0.112, -0.3, 0.1), (0.75, 0.112, -0.7, 0.5), (1.45, 0.112, -0.7, 0.5),
        (0.95, 0.13, -1.0, 0.87), (1.2, 0.13, -1.0, 0.87)]
UPPER = [(1.12, 0.6, 0.2, 0.0), (1.1, 0.45, -0.8, 0.6)]       # the shoe's upper: not the sole
CAP = (1.07, 0.16, -1.16, 0.87)    # the toe cap's front edge (Rin's: z -1.16, y 0.16): above the sole, lowest when pointed


def shoe_model_bytes():
    """the leg rig of tests.test_leg_ik with a sole (and two upper vertices) on each foot"""
    def vertices(w, index):
        out = []
        for side, sx in (("左", 1.0), ("右", -1.0)):
            ankle_d, ex = index[side + "足首D"], index[side + "足先EX"]
            for x, y, z, wex in SOLE + UPPER + [CAP]:
                raw = w.vertex("BDEF2", (ex, ankle_d), (wex,)) if wex > 0 else w.vertex("BDEF1", (ankle_d,))
                out.append(struct.pack("<3f", sx * x, y, z) + raw[12:])
        return out
    return rin_legs_bytes(vertices)


DATA = shoe_model_bytes()
RIG = leg_ik.LegRig.loads(DATA)
SHOE = foot_layer.Shoe(RIG, pmx_edit.loads(DATA))


def motion(*keys):
    return vmd.Motion(model_name="rin-legs", bones=list(keys))


def measure(*keys, frames=(0,), floor_y=0.0):
    return foot_layer.measure_feet(RIG, SHOE, motion(*keys), list(frames), floor_y)


def shoe_point(f, t, p, side="左"):
    """the world place at frame t of a shoe vertex p = (x, y, z, weight on 足先EX) of the left shoe (mirrored for the
    right), skinned as MMD does from measured bones (independent of foot_layer's own skinning)"""
    sx = 1.0 if side == "左" else -1.0
    a0, e0 = rest("足首", side), rest("足先EX", side)
    v = np.array([sx * p[0], p[1], p[2]])
    ankle, qf, qe = f["ankle"][t], f["q_foot"][t], f["q_ex"][t]
    ex = ankle + leg_ik.qrot(qf, e0 - a0)
    return (1.0 - p[3]) * (ankle + leg_ik.qrot(qf, v - a0)) + p[3] * (ex + leg_ik.qrot(qe, v - e0))


class ShoeTest(unittest.TestCase):
    def test_sole_found_and_split(self):
        for s, sx in (("左", 1.0), ("右", -1.0)):
            o = SHOE.sides[s]
            self.assertEqual(len(o.points), len(SOLE))                       # the upper is not the sole
            self.assertAlmostEqual(o.floor, 0.111, 5)
            self.assertEqual(int(o.heel.sum()), 4)
            self.assertEqual(int(o.fore.sum()), 6)
            self.assertGreater(-o.a0[2], 0.99)                                # forward is -Z
            self.assertGreater(o.l0[0] * sx, 0.99)                            # lateral is the foot's outside
            self.assertAlmostEqual(float(o.w_ex.max()), 0.87, 5)


class MeasureTest(unittest.TestCase):
    def test_rest(self):
        m = measure(key("左足ＩＫ", 0))
        for s in ("左", "右"):
            f = m[s]
            self.assertAlmostEqual(float(f["low"][0]), 0.111, 4)
            self.assertAlmostEqual(float(f["pitch"][0]), 0.0, delta=0.02)    # the toe IK's goal is 0.0004 off its bone
            self.assertAlmostEqual(float(f["roll"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["inversion"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["adduction"][0]), 0.0, delta=0.02)
            self.assertAlmostEqual(float(f["dorsi"][0]), f["rest_dorsi"], delta=0.02)
            self.assertAlmostEqual(float(f["mtp"][0]), f["rest_mtp"], 3)
        # the rest's own anatomy: the shank leans forward 5.2 degrees, the heel pitches the foot down in the shoe
        self.assertAlmostEqual(m["左"]["rest_dorsi"], 5.18 - foot_layer.HEEL_PITCH_DEG, 1)

    def test_roll_of_the_ankle_key_is_measured_as_inversion(self):
        # the foot turned about its own forward axis so that its outside edge falls: 足ＩＫ turned (the toe goal swings)
        # and 足首 keyed by the same turn (the toe IK then has nothing to do): inversion on both sides
        for s, sign in (("左", 1.0), ("右", -1.0)):
            a0 = tuple(SHOE.sides[s].a0)
            q = axis_angle(a0, sign * 12.0)
            f = measure(key(s + "足ＩＫ", 0, q), key(s + "足首", 0, q))[s]
            self.assertAlmostEqual(float(f["roll"][0]), 12.0, delta=0.05)
            self.assertAlmostEqual(float(f["inversion"][0]), 12.0, delta=0.05)
            self.assertAlmostEqual(float(f["adduction"][0]), 0.0, delta=0.05)
            self.assertLess(float(f["low"][0]), float(f["flat_low"][0]) - 0.02)    # the outside edge dips
            self.assertAlmostEqual(float(f["flat_low"][0]), 0.111, delta=0.005)     # laid flat: on the trace's floor

    def test_pitch_and_dorsiflexion(self):
        # the foot IK turned 20 degrees toes-up about X: the foot dorsiflexes 20 against an unmoved shank
        m = measure(key("センター", 0, position=(0, -1.0, 0)), key("左足ＩＫ", 0, axis_angle((1, 0, 0), 20.0)))["左"]
        self.assertAlmostEqual(float(m["pitch"][0]), 20.0, delta=0.5)
        self.assertGreater(float(m["dorsi"][0]) - m["rest_dorsi"], 15.0)        # the shank leans too: not exactly 20

    def test_toes_key_is_extension(self):
        m = measure(key("左足ＩＫ", 0, position=(0, 1.0, 0)), key("左足先EX", 0, axis_angle((1, 0, 0), 25.0)))["左"]
        self.assertAlmostEqual(float(m["mtp"][0]) - m["rest_mtp"], 25.0, places=3)

    def test_pointed_foot_stands_lowest_on_its_toe_cap(self):
        # pointed 45 degrees toes-down in the air: the toe cap's front edge, above the sole at rest, is the shoe's lowest
        f = measure(key("左足ＩＫ", 0, axis_angle((1, 0, 0), -45.0), position=(0, 2.0, 0)))["左"]
        cap = shoe_point(f, 0, CAP)[1]
        sole = min(shoe_point(f, 0, p)[1] for p in SOLE)
        self.assertLess(cap, sole - 0.05)
        self.assertAlmostEqual(float(f["low"][0]), cap, delta=1e-4)

    def test_contact_mask_hysteresis(self):
        # enters at or below 0.111 + 0.03, leaves above 0.111 + 0.06
        h = np.array([0.5, 0.2, 0.15, 0.13, 0.15, 0.165, 0.18, 0.15, 0.112])
        on = foot_layer.contact_mask(h, 0.111)
        self.assertEqual(on.tolist(), [False, False, False, True, True, True, False, False, True])


def fake_foot(F, floor=0.0):
    """measure_feet's arrays for one foot standing flat on `floor`, not moving"""
    q = np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
    z = np.zeros(F)
    return {"low": z + floor, "flat_low": z + floor, "flat_heel_low": z + floor, "flat_fore_low": z + floor,
            "heel_low": z + floor, "fore_low": z + floor, "roll": z.copy(), "pitch": z.copy(), "dorsi": z.copy(),
            "inversion": z.copy(), "adduction": z.copy(), "mtp": z.copy(), "toes_pitch": z.copy(),
            "heel_xz": np.zeros((F, 2)), "fore_xz": np.tile([0.0, -1.5], (F, 1)), "ankle": np.zeros((F, 3)),
            "q_foot": q, "q_ex": q.copy()}


class ToeExtraTest(unittest.TestCase):
    def test_estimate_from_still_pointed_frames(self):
        # 30 still frames pointed 40 degrees toes-down hovering 0.5 sin(40) over the trace's floor (a trace model's foot
        # 0.5 longer), 10 flat frames on the floor (not counted): the estimate is 0.5
        F = 40
        f = fake_foot(F, floor=0.111)
        f["pitch"] = np.where(np.arange(F) >= 10, -40.0, 0.0)
        f["flat_low"] = 0.111 + np.where(f["pitch"] < 0.0, 0.5 * math.sin(math.radians(40.0)), 0.0)
        est, n = foot_layer.toe_extra_estimate(f, SHOE.sides["左"])
        self.assertEqual(n, 30)
        self.assertAlmostEqual(est, 0.5, 6)
        # and trace_height puts those frames on the floor with it
        h = foot_layer.trace_height(f, SHOE.sides["左"], 0.5)
        self.assertLess(float(np.abs(h).max()), 1e-6)


class SpreadTest(unittest.TestCase):
    def test_a_short_correction_is_spread_over_its_neighbours(self):
        # a correction of two frames (the peak of a kick past the range) comes in and goes out over EASE frames each
        # way, its peak kept, its sign kept, the far frames untouched
        x = np.zeros(21)
        x[10:12] = [-10.0, -8.0]
        x[2] = 3.0
        y = foot_layer.spread(x)
        self.assertEqual(float(y[10]), -10.0)
        self.assertTrue(np.all(np.abs(np.diff(y[5:17])) < 6.5))           # no snap: at most 0.65 of the peak a frame
        self.assertTrue(np.all(y[6:16] < 0.0))
        self.assertEqual(float(y[16]), 0.0)
        self.assertGreater(float(y[1]), 0.0)                               # the other sign stays separate
        self.assertEqual(float(y[2]), 3.0)


class SummaryTest(unittest.TestCase):
    def test_compare_counts_the_height_roughness_the_layer_adds(self):
        # the output's ankle follows the input's but pops 0.3 (2.4 cm) up at frame 4: the second difference of its height
        # grows by 4.8 cm there and 2.4 cm on each side
        f_in, f_out = fake_foot(10), fake_foot(10)
        f_in["ankle"][:, 1] = np.linspace(2.0, 1.1, 10)
        f_out["ankle"][:, 1] = f_in["ankle"][:, 1]
        f_out["ankle"][4, 1] += 0.3
        r = foot_layer.compare(f_in, f_out, np.ones(10, dtype=bool))["height_roughness_over_input_cm"]
        self.assertEqual(r["over_1"], 3)
        self.assertEqual(r["over_2"], 3)
        self.assertEqual(r["worst"][0][0], 4)
        self.assertAlmostEqual(r["worst"][0][1], 4.8, 2)
        # a layer that takes out the input's own jitter adds none: the input pops, the output does not
        f_in["ankle"][6, 1] += 0.3
        f_out["ankle"][:, 1] = np.linspace(2.0, 1.1, 10)
        r = foot_layer.compare(f_in, f_out, np.ones(10, dtype=bool))["height_roughness_over_input_cm"]
        self.assertEqual(r["over_1"], 0)

    def test_penetration_and_hover(self):
        f = fake_foot(10)
        f["low"][3:5] = [-0.01, -0.05]                  # 0.4 and 4 mm too low; the second also below the dark plane
        f["low"][6:8] = 0.111                           # in contact but hovering 8.9 mm
        r = foot_layer.summarize(f, np.ones(10, dtype=bool), 0.0)
        self.assertEqual(r["penetration"]["frames"], 2)
        self.assertEqual(r["penetration"]["below_plane_frames"], 1)
        self.assertAlmostEqual(r["penetration"]["deepest_cm"], 0.4, 3)
        self.assertEqual(r["hover_in_contact_over_5mm"], 2)

    def test_slide_and_pivot(self):
        f = fake_foot(21)
        f["heel_xz"][10:, 0] = np.linspace(0.0, 0.5, 11)        # frames 10..20: the whole foot slides 0.5 sideways
        f["fore_xz"][10:, 0] = np.linspace(0.0, 0.5, 11)
        r = foot_layer.summarize(f, np.ones(21, dtype=bool), 0.0)
        self.assertAlmostEqual(r["slide_per_contact_cm"]["max"], 4.0, 3)
        g = fake_foot(21)
        ang = np.radians(np.linspace(0, 40, 21))                  # a pivot on the ball: the heel swings, the ball stays
        g["heel_xz"] = np.stack([1.5 * np.sin(ang), -1.5 + 1.5 * np.cos(ang)], axis=1)
        r = foot_layer.summarize(g, np.ones(21, dtype=bool), 0.0)
        self.assertLess(r["slide_per_contact_cm"]["max"], 1e-9)

    def test_touchdown_kinds_and_heel_drop(self):
        F = 40
        f = fake_foot(F)
        contact = np.zeros(F, dtype=bool)
        contact[10:20] = True                           # forefoot first (pitched toes-down), the heel down 3 frames later
        f["pitch"][10:13] = [-12.0, -8.0, -5.0]
        contact[25:35] = True                           # flat
        r = foot_layer.summarize(f, contact, 0.0)
        self.assertEqual(r["touchdowns"]["count"], 2)
        self.assertEqual(r["touchdowns"]["first"], {"heel": 0, "fore": 1, "flat": 1})
        self.assertEqual(r["touchdowns"]["fore_frames_to_heel_down"]["max"], 3)
        self.assertEqual(r["touchdowns"]["fore_heel_down_within_1_frame"], 0)
        self.assertEqual(r["liftoffs"]["flat"], 2)

    def test_anatomy_beyond(self):
        # the caps: dorsiflexion 36 in the air and 40 on the floor (the weight-bearing lunge), plantarflexion 75,
        # inversion 36, eversion 25; the soft starts 20, 50, 30, 20
        f = fake_foot(6)
        f["dorsi"][:] = [0, 25, 45, -55, -80, 38]
        f["inversion"][:] = [0, 33, 40, -22, -30, 0]
        contact = np.array([True, True, True, True, True, False])
        r = foot_layer.summarize(f, contact, 0.0)
        a = r["anatomy"]
        self.assertEqual((a["dorsiflexion"]["beyond_reference"], a["dorsiflexion"]["beyond_cap"]), (3, 2))
        self.assertEqual(a["dorsiflexion"]["beyond_cap_loaded"], 1)
        self.assertEqual((a["plantarflexion"]["beyond_reference"], a["plantarflexion"]["beyond_cap"]), (2, 1))
        self.assertEqual((a["inversion"]["beyond_reference"], a["inversion"]["beyond_cap"]), (2, 1))
        self.assertEqual((a["eversion"]["beyond_reference"], a["eversion"]["beyond_cap"]), (2, 1))


def rolled(s, deg):
    """the turn about the foot's own forward axis that drops its outside edge by `deg` (an inversion)"""
    return axis_angle(tuple(SHOE.sides[s].a0), (1.0 if s == "左" else -1.0) * deg)


def run_layer(*keys, frames=1, **params):
    """(input measures, output measures, output motion, plan) for a motion of `frames` frames"""
    m_in = motion(*keys)
    if fk.last_frame(m_in) < frames - 1:
        m_in.bones.append(key("センター", frames - 1))
    out, plan = foot_layer.layer(RIG, SHOE, m_in, params)
    f_in = foot_layer.measure_feet(RIG, SHOE, m_in, range(frames))
    f_out = foot_layer.measure_feet(RIG, SHOE, out, range(frames))
    return f_in, f_out, out, plan


def turn_between(qa, qb):
    return np.degrees(2.0 * np.arccos(np.clip(np.abs(np.sum(qa * qb, axis=-1)), -1.0, 1.0)))


class LayerTest(unittest.TestCase):
    def test_loaded_rolled_foot_is_laid_flat_on_the_floor(self):
        # the knees bent (センター down) so that the legs reach the floor 0.111 below the trace's
        q = rolled("左", 15.0)
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q), key("左足首", 0, q),
                                           key("センター", 0, position=(0, -0.8, 0)), floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(a["roll"][0]), 10.0)                                 # the input stands rolled
        self.assertLess(abs(float(b["roll"][0])), 0.5)
        self.assertAlmostEqual(float(b["low"][0]), 0.0, delta=0.002)               # on the visible floor
        self.assertAlmostEqual(float(b["pitch"][0]), float(a["pitch"][0]), delta=0.3)
        self.assertAlmostEqual(float(b["yaw"][0]), float(a["yaw"][0]), delta=0.3)
        self.assertLess(np.linalg.norm(b["ankle"][0, [0, 2]] - a["ankle"][0, [0, 2]]), 0.01)   # not slid
        # the right foot (untouched in the input) is moved down onto the floor too
        self.assertAlmostEqual(float(f_out["右"]["low"][0]), 0.0, delta=0.002)

    def test_mmd_ik_reproduces_the_planned_foot(self):
        q = rolled("左", 12.0)
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0.3, 0.0, -0.2)), key("左足首", 0, q),
                                           key("センター", 0, position=(0, -0.6, 0)))
        self.assertLess(float(turn_between(f_out["左"]["q_foot"][0], plan["左"]["q_t"][0])), 0.05)
        self.assertLess(float(turn_between(f_out["右"]["q_foot"][0], plan["右"]["q_t"][0])), 0.05)

    def test_foot_in_the_air_keeps_its_turn(self):
        # lifted 3 units, pointed 30 degrees and rolled 10: inside the range, far from the floor: only the floor shift
        q = fk.multiply(axis_angle((1, 0, 0), -30.0), rolled("左", 10.0))
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, 3.0, -1.0)), key("左足首", 0, q),
                                           key("センター", 0, position=(0, -1.0, 0)), floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertLess(float(turn_between(a["q_foot"][0], b["q_foot"][0])), 0.3)
        self.assertAlmostEqual(float(b["ankle"][0, 1] - a["ankle"][0, 1]), -0.111, delta=0.003)

    def test_nothing_below_the_floor(self):
        # the trace's foot pitched toes-down 12 degrees with its ankle at the floor's height: the toes sink in
        q = axis_angle((1, 0, 0), -12.0)
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q), key("センター", 0, position=(0, -0.8, 0)), floor_y=0.0)
        self.assertLess(float(f_in["左"]["low"][0]), -0.05)
        self.assertGreater(float(f_out["左"]["low"][0]), -foot_layer.PEN_TOL)

    def test_roll_past_the_subtalar_cap_is_turned_back_inside_it(self):
        # (replaces test_roll_past_the_subtalar_cap_stays_on_its_edge, whose input never came near the cap: inversion -5
        # in, 1.7 out, so that turning the correction the wrong way passed it)  In the air, away from the floor and the
        # load, the foot rolled about its own axis past each cap: 50 degrees outer edge down (an inversion of some 75
        # against the shank) and 40 degrees inner edge down (an eversion of some 62).  Each is turned back about the
        # foot's own axis into its range, on the side it was rolled to (not through flat to the other side); its pitch
        # is kept.
        for deg, name, sign in ((50.0, "inversion", 1.0), (-40.0, "eversion", -1.0)):
            q = rolled("左", deg)
            f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, 3.0, -1.0)), key("左足首", 0, q),
                                               key("センター", 0, position=(0, -1.0, 0)))
            a, b = f_in["左"], f_out["左"]
            start, cap = foot_layer.REFERENCE[name]
            self.assertGreater(sign * float(a["inversion"][0]), cap + 10.0)          # the input is well past the cap
            self.assertLessEqual(sign * float(b["inversion"][0]), cap + 0.01)        # the output inside it
            self.assertGreater(sign * float(b["inversion"][0]), start)               # by the soft limit, not flattened
            self.assertAlmostEqual(float(b["pitch"][0]), float(a["pitch"][0]), delta=0.5)

    def test_laying_the_roll_flat_does_not_pass_the_subtalar_cap(self):
        # a wide, deep stance (the feet 6 units out to the sides, the pelvis down 5): the shank leans in so far that the
        # foot, laid flat on the floor, would invert some 45 degrees against it, past the cap 36; and the ankle is so
        # dorsiflexed that the roll against the shank is not read with trust (roll_reliable), so the cap's correction
        # does not come back to it.  The laying flat itself stops at the cap: the foot stays inside its range, still
        # partly on its edge (review 3; inversion 10 -> 35.8, the roll 33 -> 13)
        keys = (key("左足ＩＫ", 0, position=(6.0, 0, 0)), key("右足ＩＫ", 0, position=(-6.0, 0, 0)),
                key("センター", 0, position=(0, -5.0, 0)))
        f_in, f_out, out, plan = run_layer(*keys)
        cap = foot_layer.REFERENCE["inversion"][1]
        for s in ("左", "右"):
            self.assertLess(abs(float(f_in[s]["inversion"][0])), cap)                # the input is inside the range
            self.assertLess(abs(float(f_out[s]["inversion"][0])), cap + 0.5)

    def test_rolled_foot_in_a_deep_squat_is_laid_flat_where_the_subtalar_joint_takes_it(self):
        # a squat (the pelvis down 3, the feet back 0.8) deep enough that the roll against the shank is read with
        # little trust (the bone dorsiflexion 54, inside the fade 45-60), the left foot loaded and rolled 15 degrees onto
        # its outer edge: laying it flat turns the subtalar joint back toward the middle of its range (inversion 36 ->
        # some 15), so it is laid flat all the same.  Only a laying flat that would pass the caps stops at them
        # (test_laying_the_roll_flat_does_not_pass_the_subtalar_cap); a fade by the trust alone left this foot rolled
        # 14.5 degrees and its subtalar joint at 28
        q = rolled("左", 15.0)
        keys = (key("左足ＩＫ", 0, q, position=(0, 0, 0.8)), key("左足首", 0, q), key("右足ＩＫ", 0, position=(0, 0, 0.8)),
                key("センター", 0, position=(0, -3.0, 0)))
        f_in, f_out, out, plan = run_layer(*keys, floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(a["roll"][0]), 20.0)                                  # the input stands rolled
        self.assertLess(abs(float(b["roll"][0])), 2.0)
        self.assertLess(float(b["inversion"][0]), float(a["inversion"][0]) - 10.0)    # back toward the middle
        self.assertAlmostEqual(float(b["low"][0]), 0.0, delta=0.003)

    def test_loaded_foot_dorsiflexes_further_than_a_lifted_one(self):
        # the deep squat of test_deep_squat_lifts_the_heel_past_the_loaded_dorsiflexion at frame 0 (the feet flat on the
        # floor, loaded), and the same pose lifted 1 unit from frame 10 on (the feet in the air): the same ankle angle in,
        # but the loaded foot may go to the weight-bearing lunge's 40 degrees, the lifted one only to 36
        keys = [key("センター", 0, position=(0, -3.5, 0)), key("左足ＩＫ", 0, position=(0, 0, 1.2)),
                key("右足ＩＫ", 0, position=(0, 0, 1.2)), key("センター", 10, position=(0, -2.5, 0)),
                key("左足ＩＫ", 10, position=(0, 1.0, 1.2)), key("右足ＩＫ", 10, position=(0, 1.0, 1.2)),
                key("センター", 20, position=(0, -2.5, 0)), key("左足ＩＫ", 20, position=(0, 1.0, 1.2)),
                key("右足ＩＫ", 20, position=(0, 1.0, 1.2))]
        f_in, f_out, out, plan = run_layer(*keys, frames=21)
        a, b = f_in["左"], f_out["左"]
        self.assertAlmostEqual(float(a["dorsi"][0]), float(a["dorsi"][15]), delta=0.1)   # the same angle in
        self.assertGreater(float(b["dorsi"][0]), float(b["dorsi"][15]) + 1.0)

    def test_raised_heel_stands_on_the_ball_with_the_toes_flat(self):
        # the foot pitched 25 degrees toes-down with its rigid tip on the trace's floor (the trace's tiptoe)
        q = axis_angle((1, 0, 0), -25.0)
        center = key("センター", 0, position=(0, -0.8, 0))
        probe = measure(key("左足ＩＫ", 0, q), center)["左"]
        lift = 0.111 - float(probe["low"][0])
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, lift, 0)), center, floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertAlmostEqual(float(a["low"][0]), 0.111, delta=0.03)               # near the trace's floor
        self.assertLess(float(a["toes_pitch"][0]), -20.0)                              # the input stands on the tip
        self.assertLess(abs(float(b["toes_pitch"][0])), 3.0)                           # the toe box lies flat
        self.assertAlmostEqual(float(b["mtp"][0] - b["rest_mtp"]), -float(b["pitch"][0]), delta=3.0)
        self.assertAlmostEqual(float(b["low"][0]), 0.0, delta=0.003)
        self.assertLess(float(b["pitch"][0]), -15.0)                                   # the heel stays raised

    def test_rom_caps_an_overpointed_foot_in_the_air(self):
        q = axis_angle((1, 0, 0), -120.0)
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, 3.0, 0)), key("左足首", 0, q),
                                           key("センター", 0, position=(0, -1.0, 0)))
        cap = foot_layer.REFERENCE["plantarflexion"][1]
        self.assertGreater(float(-f_in["左"]["dorsi"][0]), cap)
        self.assertLess(float(-f_out["左"]["dorsi"][0]), cap)

    def test_other_bones_untouched(self):
        q = rolled("左", 15.0)
        m_in = motion(key("左足ＩＫ", 0, q), key("左足首", 0, q), key("センター", 0, position=(0.1, -0.5, 0.2)),
                      key("下半身", 0, axis_angle((0, 1, 0), 10.0)), key("左足", 0, axis_angle((0, 1, 0), 5.0)))
        out, _ = foot_layer.layer(RIG, SHOE, m_in, {})
        written = {"左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ", "左足首", "右足首", "左足先EX", "右足先EX"}
        before = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in m_in.bones if k.name not in written)
        after = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in out.bones if k.name not in written)
        self.assertEqual(before, after)
        self.assertEqual({k.name for k in out.bones} - {k.name for k in m_in.bones}, written - {k.name for k in m_in.bones})

    def test_deep_squat_lifts_the_heel_past_the_loaded_dorsiflexion(self):
        # a squat so deep (the pelvis down 3.5, the feet flat and back 1.2: 46 degrees) that the flat foot would
        # dorsiflex past the weight-bearing lunge's 40 degrees: the heel comes up, the forefoot stays on the floor
        keys = (key("センター", 0, position=(0, -3.5, 0)), key("左足ＩＫ", 0, position=(0, 0, 1.2)),
                key("右足ＩＫ", 0, position=(0, 0, 1.2)))
        f_in, f_out, out, plan = run_layer(*keys, floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(a["dorsi"][0]), foot_layer.LOADED_DORSI_CAP + 3.0)
        self.assertLess(float(b["dorsi"][0]), foot_layer.LOADED_DORSI_CAP)            # (a cap of 80 would give 41)
        self.assertLess(float(b["pitch"][0]), -3.0)                                    # the heel raised
        self.assertAlmostEqual(float(b["low"][0]), 0.0, delta=0.003)                   # the forefoot on the floor

    def test_unloaded_touch_keeps_its_roll_and_toes(self):
        # the left foot touches the floor far out to the side (a pointed toe out, the weight on the right foot under
        # the body): it keeps its roll and its toes are not bent; it still neither sinks nor hovers
        q = fk.multiply(axis_angle((1, 0, 0), -20.0), rolled("左", 12.0))
        center = key("センター", 0, position=(0, -1.6, 0))
        probe = measure(key("左足ＩＫ", 0, q, position=(3.5, 0.0, 0.0)), key("左足首", 0, q), center)["左"]
        lift = 0.111 - float(probe["low"][0])
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(3.5, lift, 0.0)), key("左足首", 0, q), center,
                                           floor_y=0.0)
        a, b = f_in["左"], f_out["左"]
        self.assertLess(float(plan["左"]["share"][0]), 0.2)
        self.assertGreater(float(plan["右"]["share"][0]), 0.8)
        self.assertAlmostEqual(float(b["roll"][0]), float(a["roll"][0]), delta=1.0)
        self.assertLess(float(b["mtp"][0] - b["rest_mtp"]), 2.0)
        self.assertAlmostEqual(float(b["low"][0]), 0.0, delta=0.003)

    def test_twisted_foot_is_measured_as_twist(self):
        # the leg at rest (its shank nearly upright), the foot turned 70 degrees about the vertical (toes out) by the
        # foot IK and by 足首 alike: no dorsiflexion nor inversion appears
        q = axis_angle((0, 1, 0), -70.0)
        f = measure(key("左足ＩＫ", 0, q), key("左足首", 0, q))["左"]
        self.assertAlmostEqual(float(f["adduction"][0]), -70.0, delta=1.5)          # abduction
        # the rest's shank leans 5.2 degrees forward: across a foot turned 70 degrees that lean is mostly sideways,
        # an inversion of at most 5.2 sin 70 = 4.9 degrees
        self.assertLess(abs(float(f["inversion"][0])), 5.0)
        self.assertLess(abs(float(f["dorsi"][0] - f["rest_dorsi"])), 5.0)

    def test_landing_is_smooth(self):
        # the foot comes down over 12 frames rolled 15 degrees and stands 8: no step bigger than the input's but for the
        # putting down, eased over the frames before the landing (a few mm here)
        q = rolled("左", 15.0)
        keys = [key("センター", 0, position=(0, -0.8, 0)), key("左足首", 0, q),
                key("左足ＩＫ", 0, q, position=(0, 2.0, -0.5)), key("左足ＩＫ", 12, q), key("左足ＩＫ", 20, q)]
        f_in, f_out, out, plan = run_layer(*keys, frames=21)
        a, b = f_in["左"], f_out["左"]
        step_in = np.abs(np.diff(a["ankle"][:, 1]))
        step_out = np.abs(np.diff(b["ankle"][:, 1]))
        self.assertLess(float(step_out.max()), float(step_in.max()) + 0.04)
        turn_out = foot_layer.angle_steps(b["q_foot"])
        self.assertLess(float(turn_out.max()), float(a["roll"][0]) / 3.0 + 0.5)       # laid flat over 3 frames or more
        self.assertLess(abs(float(b["roll"][14])), 0.5)                                # flat once it stands
        self.assertGreater(abs(float(b["roll"][0])), 14.0)                             # untouched high up

    def test_foot_along_the_shank_is_not_whipped(self):
        # the trace's foot in the air with its toes up along the shank (dorsiflexed some 65 degrees, past any range, as
        # at the top of a kick that folds the knee), wobbling 4 degrees about that line: the plane of the shank and the
        # foot, about whose normal a dorsiflexion is undone, turns round with the wobble, so undoing it there would
        # swing the foot round frame by frame.  The output turns no faster than the input.
        keys = []
        for t in range(13):
            phi = math.radians(40.0 * t)
            q = fk.multiply(axis_angle((math.cos(phi), 0.0, math.sin(phi)), 4.0), axis_angle((1, 0, 0), 90.0))
            keys += [key("左足ＩＫ", t, q), key("左足首", t, q)]
        f_in, f_out, out, plan = run_layer(*keys, frames=13)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(a["dorsi"].min()), 55.0)
        over = foot_layer.angle_steps(b["q_foot"]) - foot_layer.angle_steps(a["q_foot"])
        self.assertLess(float(over.max()), 2.0)

    def test_pointed_toe_cap_is_not_sunk(self):
        # the trace's foot pointed 45 degrees toes-down with the bottom of its sole just on the trace's floor: the toe cap,
        # further forward, lies below it.  On the floor no part of the shoe goes below the floor.
        q = axis_angle((1, 0, 0), -45.0)
        center = key("センター", 0, position=(0, -0.8, 0))
        probe = measure(key("左足ＩＫ", 0, q), center)["左"]
        sole = min(shoe_point(probe, 0, p)[1] for p in SOLE)
        lift = 0.111 + 0.01 - sole
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, lift, 0)), center, floor_y=0.0)
        self.assertLess(shoe_point(f_in["左"], 0, CAP)[1], 0.111 - 0.05)                # below the trace's floor
        b = f_out["左"]
        points = [shoe_point(b, 0, p)[1] for p in SOLE + UPPER + [CAP]]
        self.assertGreater(min(points), -foot_layer.PEN_TOL)
        self.assertAlmostEqual(min(points), 0.0, delta=0.003)                            # on the floor, not above it

    def test_untrusted_frames_do_not_spread_into_their_neighbours(self):
        # the foot lifted in the air, pitched 15 degrees down and rolled 10 (inside every range), but for three frames
        # turned with its toes up along the shank, 6 degrees off it, where its roll and its dorsiflexion against the
        # shank cannot be read (the roll reads some 90 degrees).  What is read there must not be "corrected" into the
        # frames around them, which need nothing: the output's foot is the input's on every frame.
        lift, centre = (0, 3.0, -1.0), key("センター", 0, position=(0, -1.0, 0))
        leg = leg_ik.solve(RIG, motion(key("左足ＩＫ", 0, position=lift), centre), [0])["左"]
        sv = (leg["knee"][0] - leg["ankle"][0]) / np.linalg.norm(leg["knee"][0] - leg["ankle"][0])
        a0 = SHOE.sides["左"].a0
        along = axis_angle(tuple(np.cross(a0, sv)), math.degrees(math.acos(float(np.dot(a0, sv)))))
        up = fk.multiply(axis_angle(tuple(np.cross(sv, (1.0, 0.0, 0.0))), 6.0), along)
        down = fk.multiply(axis_angle((1, 0, 0), -15.0), rolled("左", 10.0))
        keys = [centre]
        for t in range(13):
            q = up if 5 <= t <= 7 else down
            keys += [key("左足ＩＫ", t, q, position=lift), key("左足首", t, q)]
        f_in, f_out, out, plan = run_layer(*keys, frames=13)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(a["low"].min()), 2.0)                                # in the air
        self.assertGreater(abs(float(a["inversion"][6])), 60.0)                        # the roll read there
        self.assertLess(float(turn_between(a["q_foot"], b["q_foot"]).max()), 1.0)

    def pointed_over_the_floor(self, above):
        """keys of the left foot pointed 40 degrees toes-down with the shoe's lowest point `above` units over the trace's
        floor, the knees bent (センター down 1.2) so that the leg can still reach down"""
        q = axis_angle((1, 0, 0), -40.0)
        center = key("センター", 0, position=(0, -1.2, 0))
        probe = measure(key("左足ＩＫ", 0, q, position=(0, 0.5, -0.3)), center)["左"]
        lift = 0.5 + 0.111 + above - float(probe["low"][0])
        return key("左足ＩＫ", 0, q, position=(0, lift, -0.3)), center

    def test_pointed_foot_that_touches_in_the_trace_is_put_on_the_floor(self):
        # the trace's model had a foot longer by `trace_toe_extra` (its pointed toe reached the floor where this shoe stops
        # short by that much times sin(pitch)): such a foot touches the floor in the trace, so it is put on the floor
        extra = 0.5
        above = extra * math.sin(math.radians(40.0))
        keys = self.pointed_over_the_floor(above)
        f_in, f_out, out, plan = run_layer(*keys, trace_toe_extra=extra)
        self.assertAlmostEqual(float(f_in["左"]["low"][0]), 0.111 + above, delta=0.003)
        self.assertAlmostEqual(float(f_out["左"]["low"][0]), 0.111, delta=0.003)          # on the trace's floor
        # without it (another model's trace, or the same model's) the foot is in the air: it stays where it is
        f_in, f_out, out, plan = run_layer(*keys)
        self.assertAlmostEqual(float(f_out["左"]["low"][0]), 0.111 + above, delta=0.003)

    def test_pointed_foot_above_the_trace_models_reach_stays_in_the_air(self):
        extra = 0.5
        above = extra * math.sin(math.radians(40.0)) + 0.3              # 2.4 cm over where the trace's toe would be
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(above), trace_toe_extra=extra)
        self.assertAlmostEqual(float(f_out["左"]["low"][0]), float(f_in["左"]["low"][0]), delta=0.003)

    def test_pointed_foot_swinging_past_stays_in_the_air(self):
        # the same height, but the foot swings past (5 cm a frame, 150 cm/s): a toe on the floor does not move so; it is
        # a step's swing skimming the floor and stays in the air
        extra = 0.5
        above = extra * math.sin(math.radians(40.0))
        ik, center = self.pointed_over_the_floor(above)
        x, y, z = ik.position
        keys = [center] + [key("左足ＩＫ", t, axis_angle((1, 0, 0), -40.0), position=(x, y, z - 0.625 * (t - 3)))
                           for t in range(7)]
        f_in, f_out, out, plan = run_layer(*keys, frames=7, trace_toe_extra=extra)
        self.assertAlmostEqual(float(f_in["左"]["low"][3]), 0.111 + above, delta=0.003)
        self.assertAlmostEqual(float(f_out["左"]["low"][3]), float(f_in["左"]["low"][3]), delta=0.003)

    def heel_up_keys(self, pitch, lifts):
        """keys of the left foot pitched `pitch` degrees toes-down, its shoe's lowest point on the trace's floor raised by
        lifts[t] units at frame t, the knees bent (センター down 1.2), the right foot lifted out of the way (the left one
        bears the weight)"""
        q = axis_angle((1, 0, 0), -pitch)
        center = key("センター", 0, position=(0, -1.2, 0))
        right = key("右足ＩＫ", 0, position=(0, 2.5, 0.8))
        probe = measure(key("左足ＩＫ", 0, q, position=(0, 0.5, -0.3)), center, right)["左"]
        base = 0.5 + 0.111 - float(probe["low"][0])
        return [center, right] + [key("左足ＩＫ", t, q, position=(0, base + h, -0.3)) for t, h in enumerate(lifts)]

    def test_heel_up_landing_settles_onto_the_ball_without_a_jump(self):
        # the foot comes down on its tip (pitched 38 degrees) and stays: loaded, its toes bend and the ankle lowers 2.7 cm
        # until the ball stands on the floor.  The merged layer (toe_model v1) eases that over the frames before the
        # landing, its toes bent up in the air: it adds less than 1 cm a frame to the ankle's own motion (all of it in the
        # landing's frame was 2.9 cm).  (The anatomical toes settle after the touch: ToeModelTest.)
        lifts = [0.5, 0.4, 0.3, 0.2, 0.1, 0.03, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(38.0, lifts), frames=len(lifts), toe_model="v1")
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(b["mtp"][-1] - b["rest_mtp"]), 20.0)                 # the toes bent in the end
        self.assertLess(float(b["ankle"][-1, 1]), float(a["ankle"][-1, 1]) - 0.1)      # the ankle lowered onto the ball
        added = np.abs(np.diff(b["ankle"][:, 1]) - np.diff(a["ankle"][:, 1]))
        self.assertLess(float(added.max()), 0.125)

    def test_foot_lifting_into_a_kick_is_let_go(self):
        # standing on the ball (pitched 30 degrees, lowered onto it), then lifted 4 cm a frame: after the lift-off the
        # foot follows the dance; around it the layer's height change is never more than it was while the foot stood,
        # and it is gone EASE frames after
        lifts = [0.0] * 5 + [0.5 * k for k in range(1, 10)]
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(30.0, lifts), frames=len(lifts))
        dy = f_out["左"]["ankle"][:, 1] - f_in["左"]["ankle"][:, 1]
        standing = float(np.abs(dy[:5]).max())
        self.assertGreater(standing, 0.05)                                            # it was lowered onto the ball
        self.assertLess(float(np.abs(dy[5:]).max()), standing + 0.01)
        self.assertLess(float(np.abs(dy[5 + foot_layer.EASE:]).max()), 0.01)

    def test_one_frame_lift_of_a_standing_foot_is_bridged(self):
        # standing on the ball (pitched 30 degrees), the trace lifts the foot 1 cm for a single frame: no pop
        lifts = [0.0] * 11
        lifts[5] = 0.125
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(30.0, lifts), frames=len(lifts))
        y = f_out["左"]["ankle"][:, 1]
        self.assertLess(abs(float(y[5] - 0.5 * (y[4] + y[6]))), 0.03)

    def test_nothing_below_the_floor_between_the_frames(self):
        # MMD draws 240 fps and interpolates the keys between two frames.  A foot touching the floor out to the side
        # (unloaded: it keeps its roll) on its outer edge at frame 4 and on its inner edge at frame 5, 40 degrees each
        # way: half way, turned flat about the same ankle, its sole would sink 1.2 cm into the floor.  Checked at the
        # 1/8 frames as MMD interpolates them, the shoe stays on or above the floor there too.
        center = key("センター", 0, position=(0, -1.6, 0))

        def on_floor(q):
            lift = 0.0
            for _ in range(4):
                probe = measure(key("左足ＩＫ", 0, q, position=(3.5, lift, 0.0)), key("左足首", 0, q), center)["左"]
                lift += 0.111 - float(probe["low"][0])
            return lift
        keys = [center]
        for t in range(10):
            q = rolled("左", 40.0 if t <= 4 else -40.0)
            keys += [key("左足ＩＫ", t, q, position=(3.5, on_floor(q), 0.0)), key("左足首", t, q)]
        m_in = motion(*keys)
        out, plan = foot_layer.layer(RIG, SHOE, m_in, {})
        self.assertLess(float(plan["左"]["share"][4]), 0.2)                       # unloaded: it keeps its roll
        sub = np.arange(4.0, 5.0001, 0.125)
        lows = {}
        for tag, m in (("in", m_in), ("out", out)):
            sol = leg_ik.solve(RIG, m, sub)
            lows[tag] = foot_layer.shell_world(SHOE.sides["左"], sol["左"])[:, :, 1].min(axis=1)
        self.assertLess(float(lows["in"].min()), 0.111 - 0.1)                      # the input sinks half way
        self.assertGreater(float(lows["out"].min()), 0.111 - foot_layer.PEN_TOL)  # the output does not

    def test_a_real_quick_lift_is_not_bridged(self):
        # standing flat, the foot for a single frame rolled 55 degrees about its own axis and lifted so that, laid flat,
        # its sole would be only 1.4 cm up (the bridging's old measure), while the shoe itself rises some 7 cm (rolling it
        # about the ankle swings the sole up): a real quick step, not the trace's jitter, so it is not put down on the
        # floor - the ankle keeps its height and the toes are not bent (its roll is still eased flat with the frames
        # around, as any roll of a foot near loaded frames)
        center = key("センター", 0, position=(0, -1.2, 0))
        q = rolled("左", 55.0)
        lift = 0.0
        for _ in range(4):                                  # the leg's IK is not linear: find the lift by a few probes
            probe = measure(key("左足ＩＫ", 0, q, position=(0, lift, 0)), key("左足首", 0, q), center)["左"]
            lift += 0.111 + 0.175 - float(probe["flat_low"][0])
        keys = [center]
        for t in range(11):
            if t == 5:
                keys += [key("左足ＩＫ", t, q, position=(0, lift, 0)), key("左足首", t, q)]
            else:
                keys += [key("左足ＩＫ", t), key("左足首", t)]
        f_in, f_out, out, plan = run_layer(*keys, frames=11)
        a, b = f_in["左"], f_out["左"]
        self.assertAlmostEqual(float(a["flat_low"][5]) - 0.111, 0.175, delta=0.01)
        self.assertGreater(float(a["low"][5]) - 0.111, 0.4)                       # the shoe itself well up
        self.assertAlmostEqual(float(b["ankle"][5, 1]), float(a["ankle"][5, 1]), delta=0.01)   # not put down
        self.assertGreater(float(b["low"][5]) - 0.111, 0.1)
        self.assertLess(float(b["mtp"][5] - b["rest_mtp"]), 2.0)                  # nor stood on its ball

    def test_default_floor_is_the_traces(self):
        # no floor given: the floor is the trace's (where the rest pose's soles stand, 0.111 here), so nothing is moved
        # down: the foot in the air keeps its height, the loaded rolled foot is laid flat with its sole on that floor
        q = rolled("左", 15.0)
        air = fk.multiply(axis_angle((1, 0, 0), -30.0), rolled("右", 10.0))
        f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q), key("左足首", 0, q),
                                           key("右足ＩＫ", 0, air, position=(0, 3.0, -1.0)), key("右足首", 0, air),
                                           key("センター", 0, position=(0, -0.8, 0)))
        self.assertAlmostEqual(float(plan["左"]["floor_y"]), 0.111, 5)
        self.assertGreater(float(f_in["左"]["roll"][0]), 10.0)
        self.assertLess(abs(float(f_out["左"]["roll"][0])), 0.5)
        self.assertAlmostEqual(float(f_out["左"]["low"][0]), 0.111, delta=0.002)
        self.assertAlmostEqual(float(f_out["右"]["ankle"][0, 1] - f_in["右"]["ankle"][0, 1]), 0.0, delta=0.003)


def bend(f):
    """the toes' bend added by 足先EX [F] (degrees, + extension: the toe box turned up against the foot)"""
    return f["mtp"] - f["rest_mtp"]


class ToeModelTest(unittest.TestCase):
    """the toes (足先EX) of the anatomical model (toe_model "anatomical"): the floor bends them, the air does not; once on
    its ball a foot stays on it until it leaves; after the toe-off they return over a time; in the air they follow the
    ankle a little; a still pointed foot just over the floor reaches it with its toes.  "v1" is the merged layer."""

    heel_up_keys = LayerTest.heel_up_keys
    pointed_over_the_floor = LayerTest.pointed_over_the_floor

    def test_v1_reproduces_the_merged_layer(self):
        # the keys the merged layer (4ce0cf5) wrote on two scenes, recorded: a heel-up landing that settles onto the ball
        # (its toes bent up from 3 cm over the floor on), and standing on the ball then lifted into a kick
        landing = self.heel_up_keys(38.0, [0.5, 0.4, 0.3, 0.2, 0.1, 0.03] + [0.0] * 9)
        kick = self.heel_up_keys(30.0, [0.0] * 5 + [0.5 * k for k in range(1, 10)])
        expected = {
            "landing": ([1.057019, 0.922065, 0.730555, 0.517442, 0.325932, 0.220978] + [0.221012] * 9,
                        [0.0, 3.49222, 12.63495, 23.936, 33.07874, 36.57095] + [36.57052] * 9),
            "kick": ([0.234739] * 5 + [0.760424, 1.327668, 1.910785, 2.478029, 3.003713, 3.503713, 4.003713, 4.503713,
                                       5.003713],
                     [29.9764] * 5 + [27.11391, 19.61981, 10.35659, 2.86249] + [0.0] * 5)}
        for name, keys in (("landing", landing), ("kick", kick)):
            out, plan = foot_layer.layer(RIG, SHOE, motion(*keys), {"toe_model": "v1"})
            ik = sorted((k.frame, k.position[1]) for k in out.bones if k.name == "左足ＩＫ")
            ex = sorted((k.frame, k.rotation) for k in out.bones if k.name == "左足先EX")
            heights, toes = expected[name]
            self.assertEqual(len(ik), len(heights))
            for (_, y), want in zip(ik, heights):
                self.assertAlmostEqual(y, want, delta=2e-5)
            for (_, q), want in zip(ex, toes):
                self.assertAlmostEqual(math.degrees(2.0 * math.atan2(q[0], q[3])), want, delta=2e-3)

    def test_toes_do_not_bend_up_before_the_forefoot_lands(self):
        # the heel-up landing: the foot comes down on its tip (pitched 38 degrees) and stays, loaded.  The toes bend when
        # the floor bends them: while the shoe is still a centimetre or more over the floor they keep their shape in the
        # air (the merged layer bent them 3.5 to 33 degrees there, from 3 cm up); standing, the toe box lies on the floor
        lifts = [0.5, 0.4, 0.3, 0.2, 0.1, 0.03] + [0.0] * 9
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(38.0, lifts), frames=len(lifts), toe_model="anatomical")
        b = f_out["左"]
        up = (b["low"] - 0.111) * foot_layer.UNIT_CM >= 1.0
        self.assertGreater(int(up.sum()), 2)
        self.assertLess(float(bend(b)[up].max()), 0.5)
        self.assertGreater(float(bend(b)[-1]), 20.0)                                   # on the ball in the end
        self.assertLess(abs(float(b["toes_pitch"][-1])), 3.0)

    def test_landing_on_the_tip_settles_onto_the_ball_after_the_touch(self):
        # the same landing (the tip down at frame 5, pitched 38 degrees, loaded): nothing is added before the touch (the
        # trace's landing keeps its time), and the ankle comes down onto the ball after it, as the toes are pressed
        # flat: over three frames or more, the largest frame taking less than half of it, each frame less than the last
        # (no second push)
        lifts = [0.5, 0.4, 0.3, 0.2, 0.1, 0.03] + [0.0] * 9
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(38.0, lifts), frames=len(lifts), toe_model="anatomical")
        a, b = f_in["左"], f_out["左"]
        added = np.diff(b["ankle"][:, 1]) - np.diff(a["ankle"][:, 1])        # added[t - 1]: from frame t - 1 to t
        touch = 5
        self.assertLess(float(np.abs(added[:touch - 1]).max()), 1e-4)            # nothing before the touch
        total = float(b["ankle"][-1, 1] - a["ankle"][-1, 1])
        self.assertLess(total, -0.25)                                             # 2 cm or more onto the ball
        down = -added[touch - 1:]
        self.assertGreaterEqual(int((down > 0.15 * -total).sum()), 3)
        self.assertLess(float(down.max()), 0.5 * -total)
        self.assertTrue(np.all(np.diff(down) <= 1e-4))

    def test_toes_come_down_with_the_heel(self):
        # standing on the ball (pitched 30 degrees, loaded), then the heel comes down to the floor over two frames and the
        # foot stands flat: the toe box comes down with the heel, so the tip does not stay up off the floor (the merged
        # layer kept the toes bent for four frames after, the tip up to 2 cm over the floor in the dance)
        q30, flat = axis_angle((1, 0, 0), -30.0), (0.0, 0.0, 0.0, 1.0)
        center = key("センター", 0, position=(0, -1.2, 0))
        right = key("右足ＩＫ", 0, position=(0, 2.5, 0.8))
        probe = measure(key("左足ＩＫ", 0, q30, position=(0, 0.5, -0.3)), center, right)["左"]
        base = 0.5 + 0.111 - float(probe["low"][0])
        keys = [center, right]
        for t in range(14):
            if t <= 5:
                keys.append(key("左足ＩＫ", t, q30, position=(0, base, -0.3)))
            elif t >= 8:
                keys.append(key("左足ＩＫ", t, flat, position=(0, 0.0, -0.3)))
        f_in, f_out, out, plan = run_layer(*keys, frames=14, toe_model="anatomical")
        b = f_out["左"]
        self.assertGreater(float(bend(b)[3]), 20.0)                                    # on the ball first
        for t in range(9, 14):                                                          # flat on the floor after
            self.assertLess(abs(float(b["pitch"][t])), 2.0)
            self.assertLess(abs(float(bend(b)[t])), 1.0)
            self.assertLess(float(b["low"][t]) - 0.111, 0.01)

    def push_off_keys(self):
        """the left foot on its ball (pitched 25 degrees, its rigid tip on the trace's floor in the trace), the right foot
        flat on the floor; the pelvis moves from between them onto the right foot (frames 3 to 10: the left foot's share
        of the weight falls from a half to some 5 %), then the left foot is lifted from frame 14"""
        q = axis_angle((1, 0, 0), -25.0)
        keys = [key("センター", 0, position=(0, -1.2, 0)), key("センター", 3, position=(0, -1.2, 0)),
                key("センター", 10, position=(-2.0, -1.2, 0)), key("センター", 22, position=(-2.0, -1.2, 0)),
                key("右足ＩＫ", 0, position=(-1.0, 0.0, 0.0)), key("右足ＩＫ", 22, position=(-1.0, 0.0, 0.0))]
        probe = measure(key("左足ＩＫ", 0, q, position=(1.0, 0.5, 0.0)), key("センター", 0, position=(0, -1.2, 0)))["左"]
        base = 0.5 + 0.111 - float(probe["low"][0])
        keys += [key("左足ＩＫ", 0, q, position=(1.0, base, 0.0)), key("左足ＩＫ", 13, q, position=(1.0, base, 0.0)),
                 key("左足ＩＫ", 22, q, position=(1.0, base + 3.0, 0.0))]
        return keys

    def test_a_foot_on_its_ball_stays_on_it_until_it_leaves(self):
        # the weight moves onto the other foot while the left foot stands on its ball; it pushes off from the ball as a
        # foot does (the toes flat on the floor until they leave), not rolling up onto the rigid tip of the shoe, which a
        # foot in loafers cannot stand on: the toe box stays on the floor and the ankle does not rise until the lift (the
        # merged layer straightened the toes as the share fell: the toe box tipped 25 degrees down onto its rigid tip and
        # the ankle rose 1.8 cm while the foot stood)
        f_in, f_out, out, plan = run_layer(*self.push_off_keys(), frames=23, toe_model="anatomical")
        self.assertGreater(float(plan["左"]["share"][2]), 0.4)
        self.assertLess(float(plan["左"]["share"][12]), 0.1)
        b = f_out["左"]
        for t in range(0, 14):
            self.assertLess(abs(float(b["toes_pitch"][t])), 3.0)
            self.assertAlmostEqual(float(b["ankle"][t, 1]), float(b["ankle"][2, 1]), delta=0.03)

    def test_toes_return_over_a_time_after_the_toe_off(self):
        # lifted off the ball (frame 14 on): the toes are not snapped back in the first frame (a joint does not turn 25
        # degrees in 33 ms of its own) and are back near their shape in the air a quarter second (8 frames) later
        f_in, f_out, out, plan = run_layer(*self.push_off_keys(), frames=23, toe_model="anatomical")
        k = bend(f_out["左"])
        last, end = 13, float(bend(f_out["左"])[-1])               # the last frame on the floor; 9 frames after it
        span = float(k[last]) - end
        self.assertGreater(float(k[last]), 15.0)                                       # on the ball until it leaves
        self.assertGreater(float(k[last + 1]) - end, 0.4 * span)                       # not snapped back
        self.assertLess(abs(float(k[last + 8]) - end), 0.15 * span)                    # mostly back by 0.27 s
        self.assertTrue(np.all(np.diff(k[last:]) < 0.5))                               # one way, no bounce

    def test_toe_box_keeps_the_shoes_shape_in_the_air(self):
        # in the air, away from the floor, the toe box keeps the shoe's own shape whether the foot is level, pointed or
        # flexed (no measured angle of relaxed or pointed toes in the air was found, and a loafer hides the toes: what
        # bends the shoe is the floor)
        for pitch in (20.0, 0.0, -30.0, -55.0):
            q = axis_angle((1, 0, 0), pitch)
            f_in, f_out, out, plan = run_layer(key("左足ＩＫ", 0, q, position=(0, 3.0, -1.0)), key("左足首", 0, q),
                                               key("センター", 0, position=(0, -1.0, 0)), toe_model="anatomical")
            self.assertGreater(float(f_out["左"]["low"][0]) - 0.111, 1.0)                # in the air
            self.assertLess(abs(float(bend(f_out["左"])[0])), 0.5)

    def test_still_pointed_foot_just_over_the_floor_reaches_it_with_its_toes(self):
        # a still foot pointed 40 degrees whose tip stops 0.8 cm over the floor (the trace's model had longer toes): its
        # toes bend down so that the shoe's tip is on the floor; the ankle and the foot do not move
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(0.1), toe_model="anatomical",
                                           toe_reach=foot_layer.TOE_REACH)
        a, b = f_in["左"], f_out["左"]
        self.assertAlmostEqual(float(a["low"][0]), 0.111 + 0.1, delta=0.003)
        self.assertAlmostEqual(float(b["low"][0]), 0.111, delta=0.005)
        self.assertLess(float(bend(b)[0]), -3.0)
        self.assertGreater(float(bend(b)[0]), -foot_layer.TOE_FLEX_CAP - 1e-6)
        self.assertLess(float(np.linalg.norm(b["ankle"][0] - a["ankle"][0])), 0.005)
        self.assertLess(float(turn_between(a["q_foot"][0], b["q_foot"][0])), 0.3)

    def test_the_reach_is_off_by_default(self):
        # without asking for it the still pointed foot 0.8 cm over the floor keeps its hover and its shoe's shape
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(0.1))
        self.assertAlmostEqual(float(f_out["左"]["low"][0]), float(f_in["左"]["low"][0]), delta=0.003)
        self.assertLess(abs(float(bend(f_out["左"])[0])), 0.5)

    def test_pointed_foot_far_over_the_floor_does_not_reach(self):
        # 4 cm over the floor: out of the toes' reach; they keep their shape in the air and the shoe stays where it was
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(0.5), toe_model="anatomical",
                                           toe_reach=foot_layer.TOE_REACH)
        a, b = f_in["左"], f_out["左"]
        self.assertGreater(float(b["low"][0]) - 0.111, 0.4)
        self.assertLess(abs(float(bend(b)[0])), 0.5)

    def test_pointed_foot_swinging_past_does_not_reach(self):
        # the same 0.8 cm over the floor, but swinging past at 150 cm/s: a step's swing, not a resting toe
        ik, center = self.pointed_over_the_floor(0.1)
        x, y, z = ik.position
        keys = [center] + [key("左足ＩＫ", t, axis_angle((1, 0, 0), -40.0), position=(x, y, z - 0.625 * (t - 3)))
                           for t in range(7)]
        f_in, f_out, out, plan = run_layer(*keys, frames=7, toe_model="anatomical", toe_reach=foot_layer.TOE_REACH)
        self.assertGreater(float(f_out["左"]["low"][3]) - 0.111, 0.05)

    def test_the_reach_stops_at_its_cap(self):
        # 1.6 cm over the floor, pointed 40 degrees: the tip would need some 28 degrees of the toes; they bend as far as
        # TOE_FLEX_CAP and the rest of the hover stays (the ankle and the foot do not move to close it)
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(0.2), toe_model="anatomical",
                                           toe_reach=foot_layer.TOE_REACH)
        a, b = f_in["左"], f_out["左"]
        self.assertAlmostEqual(float(bend(b)[0]), -foot_layer.TOE_FLEX_CAP, delta=0.5)
        self.assertGreater(float(b["low"][0]) - 0.111, 0.01)
        self.assertLess(float(np.linalg.norm(b["ankle"][0] - a["ankle"][0])), 0.005)

    def test_the_reach_fades_out_as_a_share_of_its_cap(self):
        # between 0.8 and 1 times the reach over the floor the reach fades out.  2.25 cm over it, pointed 40 degrees, the
        # floor is beyond the cap (more than TOE_FLEX_CAP would be needed): the toes bend by the fading share of the cap,
        # what the full reach would bend times that share - not that share of the bend the floor would need beyond the
        # cap (in the dance with the reach asked for, that bent up to 13 degrees further, on 212 frames more than one)
        reach = foot_layer.TOE_REACH
        f_in, f_out, out, plan = run_layer(*self.pointed_over_the_floor(0.9 * reach), toe_model="anatomical",
                                           toe_reach=reach)
        share = 1.0 - float(foot_layer.smoothstep(float(f_in["左"]["low"][0]) - 0.111, 0.8 * reach, reach))
        self.assertGreater(share, 0.3)
        self.assertLess(share, 0.7)
        self.assertAlmostEqual(float(bend(f_out["左"])[0]), -share * foot_layer.TOE_FLEX_CAP, delta=0.5)

    def test_the_reach_never_bends_the_toes_into_the_floor(self):
        # a still pointed foot 1.2 cm over the floor comes down slowly (7 cm/s) to 0.7 cm and stays: the reach is eased
        # in and out over frames, so it carries the deeper bend of the higher frames onto the lower ones; there the bend
        # stops where the shoe's tip meets the floor, and the ankle stays where the trace has it (bent into the floor, the
        # heights would lift the foot out of it: 1.8 mm here)
        q = axis_angle((1, 0, 0), -40.0)
        center = key("センター", 0, position=(0, -1.2, 0))
        probe = measure(key("左足ＩＫ", 0, q, position=(0, 0.5, -0.3)), center)["左"]
        keys = [center]
        for t in range(18):
            above = max(0.0875, 0.15 - 0.03 * max(0, t - 7))
            keys.append(key("左足ＩＫ", t, q, position=(0, 0.5 + 0.111 + above - float(probe["low"][0]), -0.3)))
        f_in, f_out, out, plan = run_layer(*keys, frames=18, toe_model="anatomical", toe_reach=foot_layer.TOE_REACH)
        a, b = f_in["左"], f_out["左"]
        self.assertLess(float(bend(b)[12]), -8.0)                                    # reaching
        self.assertLess(float(np.abs(b["ankle"][:, 1] - a["ankle"][:, 1]).max()), 0.002)
        self.assertGreater(float(b["low"].min()), 0.111 - foot_layer.PEN_TOL)
        sub = np.arange(0.0, 17.0 + 1e-9, 0.125)
        low = foot_layer.shell_world(SHOE.sides["左"], leg_ik.solve(RIG, out, sub)["左"])[:, :, 1].min(axis=1)
        self.assertGreater(float(low.min()), 0.111 - foot_layer.PEN_TOL)

    def test_a_foot_rising_off_its_ball_leaves_the_frames_on_the_floor_on_it(self):
        # standing on the ball (pitched 30 degrees, lowered onto it), then rising slowly (0.24 cm a frame): the lowering
        # is let go over the frames after the lift and the toes return, so the tip of the first frames in the air would
        # go under the floor and is raised; that raise does not reach back into the frames still on the floor (they stay
        # exactly on it, not lifted off it)
        lifts = [0.0] * 6 + [0.03 * k for k in range(1, 9)]
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(30.0, lifts), frames=len(lifts), toe_model="anatomical")
        b = f_out["左"]
        for t in range(7):                                                       # (frame 6 is 0.24 cm up: on the floor)
            self.assertAlmostEqual(float(b["low"][t]), 0.111, delta=0.003)
        self.assertGreater(float(b["low"].min()), 0.111 - foot_layer.PEN_TOL)
        # its toes go with the foot rising out of the band of heights over the floor (the floor bends them as far as the
        # foot is on it): not bent up in a shoe that is only partly let down
        k = bend(b)
        self.assertLess(float(k[7]), 0.75 * float(k[6]))

    def test_a_foot_leaving_from_its_ball_does_not_tap_the_floor_again(self):
        # standing on the ball (pitched 40 degrees, loaded), then lifted at a toe-off as the dance does (the trace's
        # tip 0.5, 1.1, 2, 2.5, 2.8 cm over the floor): the frame leaving the floor is still in the band (on the floor
        # by about a half), so the layer lets the lowering go by a half there; the frames after it must not take more of
        # it back (the raised cosine carries 65 % from the full frame two before): the shoe does not come back down to
        # the floor a frame later (0.92 -> 0.36 cm, the song's left 2309: 1.08 -> 0.11 cm).  The toes returning in the
        # air may still lower it a little (under 2.4 mm)
        lifts = [0.0] * 6 + [0.06, 0.14, 0.25, 0.31, 0.35]
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(40.0, lifts), frames=len(lifts), toe_model="anatomical")
        b = f_out["左"]
        self.assertGreater(float(bend(b)[5]), 20.0)                                    # on the ball before the lift
        self.assertGreater(float(plan["左"]["v"][6]), 0.5)                            # the leaving frame: partly down
        self.assertLess(float(plan["左"]["v"][6]), 0.9)
        low = b["low"]
        for t in range(6, len(lifts) - 1):
            self.assertGreater(float(low[t + 1]), float(low[t]) - 0.03)

    def test_a_foot_rising_off_the_floor_does_not_reach_back_for_it(self):
        # the same slow rise with the reach asked for: a foot pointed 30 degrees just over the floor and slower than the
        # reach's speed, but rising: its toes are not bent down toward the floor it is leaving
        lifts = [0.0] * 6 + [0.03 * k for k in range(1, 9)]
        f_in, f_out, out, plan = run_layer(*self.heel_up_keys(30.0, lifts), frames=len(lifts), toe_model="anatomical",
                                           toe_reach=foot_layer.TOE_REACH)
        self.assertGreater(float(bend(f_out["左"])[7:].min()), -0.5)

    def test_a_new_touch_starts_without_the_last_ones_weight(self):
        # the left foot on its ball bearing the weight (the right one lifted), lifted for three frames, then touching the
        # floor out to the side on its tip while the right foot stands under the body: the new touch bears little, so
        # its toes are not bent (the weight of the last contact does not carry into the next one)
        q = axis_angle((1, 0, 0), -30.0)
        center = key("センター", 0, position=(0, -1.2, 0))
        probe = measure(key("左足ＩＫ", 0, q, position=(0, 0.5, -0.3)), center)["左"]
        base = 0.5 + 0.111 - float(probe["low"][0])
        keys = [center, key("右足ＩＫ", 0, position=(0, 2.5, 0.8)), key("右足ＩＫ", 6, position=(0, 2.5, 0.8)),
                key("右足ＩＫ", 8, position=(0, 0.0, 0.0)), key("右足ＩＫ", 16, position=(0, 0.0, 0.0))]
        side = measure(key("左足ＩＫ", 0, q, position=(3.5, 0.5, -0.3)), center)["左"]
        out_base = 0.5 + 0.111 - float(side["low"][0])
        for t in range(17):
            if t <= 5:
                keys.append(key("左足ＩＫ", t, q, position=(0, base, -0.3)))
            elif t <= 8:
                keys.append(key("左足ＩＫ", t, q, position=(1.2 * (t - 5), base + 0.6, -0.3)))
            else:
                keys.append(key("左足ＩＫ", t, q, position=(3.5, out_base, -0.3)))
        f_in, f_out, out, plan = run_layer(*keys, frames=17, toe_model="anatomical")
        self.assertGreater(float(bend(f_out["左"])[3]), 20.0)                       # on its ball first
        self.assertLess(float(plan["左"]["share"][12]), 0.15)                         # the new touch bears little
        for t in range(9, 17):
            self.assertLess(float(bend(f_out["左"])[t]), 1.0)

    def test_toes_stay_in_their_range_and_above_the_floor(self):
        # every scene above: the bend inside the toes' range (extension up to the cap less the shoe's own, flexion up to
        # TOE_FLEX_CAP), the shoe never under the floor, also between the frames as MMD draws them
        room = foot_layer.REFERENCE["mtp_extension"][1] - foot_layer.HEEL_PITCH_DEG
        scenes = [self.heel_up_keys(38.0, [0.5, 0.4, 0.3, 0.2, 0.1, 0.03] + [0.0] * 9), self.push_off_keys(),
                  list(self.pointed_over_the_floor(0.1))]
        for keys in scenes:
            m_in = motion(*keys)
            F = fk.last_frame(m_in) + 1
            out, plan = foot_layer.layer(RIG, SHOE, m_in, {"toe_model": "anatomical", "toe_reach": foot_layer.TOE_REACH})
            f = foot_layer.measure_feet(RIG, SHOE, out, range(F))["左"]
            self.assertLess(float(bend(f).max()), room + 1e-6)
            self.assertGreater(float(bend(f).min()), -foot_layer.TOE_FLEX_CAP - 1e-6)
            self.assertGreater(float(f["low"].min()), 0.111 - foot_layer.PEN_TOL)
            if F > 1:
                sub = np.arange(0.0, F - 1 + 1e-9, 0.125)
                sol = leg_ik.solve(RIG, out, sub)
                low = foot_layer.shell_world(SHOE.sides["左"], sol["左"])[:, :, 1].min(axis=1)
                self.assertGreater(float(low.min()), 0.111 - foot_layer.PEN_TOL)

    def test_anatomical_toes_touch_only_the_feet(self):
        q = rolled("左", 15.0)
        m_in = motion(key("左足ＩＫ", 0, q), key("左足首", 0, q), key("センター", 0, position=(0.1, -0.5, 0.2)),
                      key("下半身", 0, axis_angle((0, 1, 0), 10.0)), key("左足", 0, axis_angle((0, 1, 0), 5.0)))
        out, _ = foot_layer.layer(RIG, SHOE, m_in, {"toe_model": "anatomical"})
        written = {"左足ＩＫ", "右足ＩＫ", "左つま先ＩＫ", "右つま先ＩＫ", "左足首", "右足首", "左足先EX", "右足先EX"}
        before = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in m_in.bones if k.name not in written)
        after = sorted((k.name, k.frame, k.position, k.rotation, k.interpolation) for k in out.bones if k.name not in written)
        self.assertEqual(before, after)


LEG_L1 = float(np.linalg.norm(rest("ひざ") - rest("足")))
LEG_L2 = float(np.linalg.norm(rest("足首") - rest("ひざ")))


def knee_from_reach(f):
    """the knee's bend [F] (degrees, 0 straight) as the human baseline's a05 reads it: the hip joint's distance to the
    ankle and the law of cosines (a leg that does not reach is straight)"""
    d = np.minimum(np.linalg.norm(f["ankle"] - f["hip"], axis=1), LEG_L1 + LEG_L2)
    c = np.clip((LEG_L1 ** 2 + LEG_L2 ** 2 - d ** 2) / (2.0 * LEG_L1 * LEG_L2), -1.0, 1.0)
    return 180.0 - np.degrees(np.arccos(c))


def ball_xz(f, side="左"):
    """the ball's (足先EX's) place on the floor [F, 2] of measured feet"""
    e = f["ankle"] + leg_ik.qrot(f["q_foot"], rest("足先EX", side) - rest("足首", side))
    return e[:, [0, 2]]


def goal_of(out, frames, side="左"):
    """the foot IK's goal [F, 3] in the layer's output (where a05 reads the ankle)"""
    return leg_ik.solve(RIG, out, range(frames))[side]["goal_ankle"]


# the layer before the landing (c012c32) on LandingTest's sinking landing: the left foot IK's height and 足首's local
# X turn (degrees), frames 0, 3, .. 18 (recorded with _spike/out/stage6/feet_landing/scripts/record_off.py)
LANDING_OFF_HEIGHTS = [0.6, 0.3, 0.000563, 0.000251, 0.000152, 0.000152, 0.000152]
LANDING_OFF_PITCH = [34.5014, 31.1104, 27.4185, 28.3719, 29.3078, 29.3078, 29.3078]


class LandingTest(unittest.TestCase):
    """the landing (feet-landing, 2026-10-16): a foot that lands while the pelvis sinks comes down on its forefoot and
    lowers its heel as the pelvis sinks, so the knee does not take the sink (the humans' knee bends 0.7 degrees in the
    0.2 s after a touchdown, the MV's 7); a standing leg that cannot reach its goal rises onto its ball; a foot skimming
    the floor in the dance is not pressed onto it.  landing=False is the layer before them."""

    TD = 6

    def landing_keys(self, sink):
        """the left foot comes down flat onto the floor at frame TD and stays while the pelvis sinks `sink` units over
        the next 6 frames (the knees bent, センター down 1.2 before); the right foot is lifted out of the way"""
        return [key("センター", 0, position=(0, -1.2, 0)), key("センター", self.TD, position=(0, -1.2, 0)),
                key("センター", self.TD + 6, position=(0, -1.2 - sink, 0)), key("センター", 18, position=(0, -1.2 - sink, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8)),
                key("左足ＩＫ", 0, position=(0, 0.6, 0.0)), key("左足ＩＫ", self.TD), key("左足ＩＫ", 18)]

    def test_the_heel_comes_down_as_the_pelvis_sinks(self):
        f_in, f_out, out, plan = run_layer(*self.landing_keys(0.15), frames=19)
        a, b = f_in["左"], f_out["左"]
        td = self.TD
        k_in, k_out = knee_from_reach(a), knee_from_reach(b)
        self.assertGreater(float(k_in[td:td + 7].max() - k_in[td]), 3.0)       # the dance's knee takes the sink
        self.assertLess(float(k_out[td:td + 7].max() - k_out[td]), 1.0)
        self.assertLess(float(b["pitch"][td]), -3.0)                          # on the forefoot at the touch
        self.assertGreater(float(b["pitch"][-1]), -1.0)                        # flat once the pelvis is down
        self.assertTrue(np.all(np.diff(b["pitch"][td:]) >= -0.05))             # the heel only comes down
        self.assertLess(float(np.abs(np.diff(b["pitch"])).max()), 8.0)         # no snap
        on = b["low"][td:]
        self.assertLess(float(np.abs(on - 0.111).max()), 0.003)                # on the floor, never in it
        self.assertGreater(float(b["low"].min()), 0.111 - foot_layer.PEN_TOL)
        ball = ball_xz(b)[td:]
        self.assertLess(float(np.linalg.norm(ball - ball[0], axis=1).max()), 0.03)   # it pivots on the ball, no slide

    def test_a_deep_sink_lowers_the_heel_without_a_slam(self):
        # (review_feet_landing) the pelvis sinks 2.4 cm, more than turning the foot about the ball can take (the ankle
        # rises 1.2 cm at most): the heel is up as far as it goes, and still comes down over frames, not in one; the
        # ball stays where it landed (the ankle's horizontal move goes with the turn)
        # (in the song the pelvis often comes down late in the 0.2 s: here over the last 2 of its 6 frames)
        keys = self.landing_keys(0.3)
        keys.insert(2, key("センター", self.TD + 4, position=(0, -1.2, 0)))
        f_in, f_out, out, plan = run_layer(*keys, frames=19)
        b = f_out["左"]
        td = self.TD
        self.assertLess(float(b["pitch"][td]), -15.0)                                # well up at the touch
        self.assertGreater(float(b["pitch"][-1]), -1.0)                              # down in the end
        self.assertLess(float(np.abs(np.diff(b["pitch"])).max()), 8.0)               # no slam
        ball = ball_xz(b)[td:]
        self.assertLess(float(np.linalg.norm(ball - ball[0], axis=1).max()), 0.03)   # it pivots on the ball

    def test_the_command_lands_like_a_human_unless_told_off(self):
        # (review_feet_landing) the default is human: without --landing the command writes what --landing human writes,
        # which raises the heel at the sinking landing; --landing off writes something else
        folder = tempfile.mkdtemp()
        try:
            src, model = os.path.join(folder, "in.vmd"), os.path.join(folder, "m.pmx")
            vmd.dump(motion(*self.landing_keys(0.15)), src)
            with open(model, "wb") as fh:
                fh.write(DATA)
            outs = {}
            for tag, extra in (("default", []), ("human", ["--landing", "human"]), ("off", ["--landing", "off"])):
                out, rep = os.path.join(folder, tag + ".vmd"), os.path.join(folder, tag + ".json")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(foot_layer.main([src, model, out, "--report", rep] + extra), 0)
                with open(out, "rb") as fh, open(rep, encoding="utf-8") as fr:
                    outs[tag] = (fh.read(), json.load(fr))
            self.assertEqual(outs["default"][0], outs["human"][0])
            self.assertNotEqual(outs["default"][0], outs["off"][0])
            self.assertEqual(outs["default"][1]["landing_model"], "human")
            self.assertGreater(outs["default"][1]["landing"]["L"]["heel_raised_frames"], 0)
            self.assertEqual(outs["off"][1]["landing"]["L"]["heel_raised_frames"], 0)
        finally:
            shutil.rmtree(folder)

    def test_the_heel_does_not_rise_again_when_the_pelvis_bounces(self):
        # (review_feet_landing) the pelvis sinks over 3 frames and comes half back up over the next 3: the heel comes
        # down with the sink and stays down (it does not rise again with the bounce)
        td = self.TD
        keys = [key("センター", 0, position=(0, -1.2, 0)), key("センター", td, position=(0, -1.2, 0)),
                key("センター", td + 3, position=(0, -1.35, 0)), key("センター", td + 6, position=(0, -1.27, 0)),
                key("センター", 18, position=(0, -1.27, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8)),
                key("左足ＩＫ", 0, position=(0, 0.6, 0.0)), key("左足ＩＫ", td), key("左足ＩＫ", 18)]
        _, f_out, _, plan = run_layer(*keys, frames=19)
        heel = plan["左"]["heel"]
        self.assertGreater(float(heel[td]), 2.0)
        self.assertTrue(np.all(np.diff(heel[td:]) <= 1e-6))

    def test_a_landing_without_a_sink_is_left_as_it_was(self):
        f_in, f_out, out, plan = run_layer(*self.landing_keys(0.0), frames=19)
        _, f_old, _, _ = run_layer(*self.landing_keys(0.0), frames=19, landing=False)
        self.assertLess(float(np.abs(f_out["左"]["pitch"] - f_old["左"]["pitch"]).max()), 0.05)
        self.assertLess(float(np.abs(f_out["左"]["ankle"] - f_old["左"]["ankle"]).max()), 1e-4)

    def test_landing_off_writes_the_layer_before(self):
        # the keys the layer wrote before the landing (c012c32) on the sinking landing, recorded: the left foot IK's
        # height and 足首's pitch, every third frame
        out, plan = foot_layer.layer(RIG, SHOE, motion(*self.landing_keys(0.15)), {"landing": False})
        ik = sorted((k.frame, k.position) for k in out.bones if k.name == "左足ＩＫ")
        ankle = sorted((k.frame, k.rotation) for k in out.bones if k.name == "左足首")
        heights = [y for f, (x, y, z) in ik if f % 3 == 0]
        pitch = [math.degrees(2.0 * math.atan2(q[0], q[3])) for f, q in ankle if f % 3 == 0]
        self.assertEqual(len(ik), 19)
        for got, want in zip(heights, LANDING_OFF_HEIGHTS):
            self.assertAlmostEqual(got, want, delta=2e-5)
        for got, want in zip(pitch, LANDING_OFF_PITCH):
            self.assertAlmostEqual(got, want, delta=2e-3)
        self.assertTrue(all(abs(x) < 1e-9 and abs(z) < 1e-9 for f, (x, y, z) in ik))

    def test_a_standing_leg_out_of_reach_rises_onto_its_ball(self):
        # the pelvis 0.04 over the rest pose's, the left foot flat on the floor under it: the leg cannot reach its goal
        # (a05 reads a straight knee; MMD leaves the foot 3 mm over the floor).  It rises onto its ball until the leg
        # reaches with the knee bent 5 degrees or more (a05's reading), the ball where it stood, the shoe on the floor.
        # (Sour's Rin's ankle stands 11.7 cm over the ball and 5.5 cm behind it: turning the foot about the ball raises
        # the ankle 1.2 cm at most, at some 25 degrees, and moves it forward toward the hip: a goal far out of reach
        # comes nearer by about that much and no more.)
        keys = [key("センター", 0, position=(0, 0.04, 0)), key("センター", 7, position=(0, 0.04, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8))]
        f_in, f_out, out, plan = run_layer(*keys, frames=8)
        _, f_old, out_old, _ = run_layer(*keys, frames=8, landing=False)
        a, b = f_in["左"], f_out["左"]
        goal, goal_old = goal_of(out, 8), goal_of(out_old, 8)
        self.assertLess(float(knee_from_reach(dict(f_old["左"], ankle=goal_old)).max()), 1.0)
        self.assertGreater(float(f_old["左"]["low"].min()), 0.111 + 0.02)                 # it hovered before
        self.assertGreater(float(knee_from_reach(dict(b, ankle=goal)).min()), 5.0)
        self.assertLess(float(np.linalg.norm(b["ankle"] - goal, axis=1).max()), 0.025)    # MMD reaches it
        self.assertLess(float(b["pitch"].max()), -1.0)                                    # the heel up
        self.assertLess(float(np.abs(b["low"] - 0.111).max()), 0.003)                     # on the floor
        self.assertLess(float(np.linalg.norm(ball_xz(b) - ball_xz(a), axis=1).max()), 0.03)

    def test_a_foot_stood_far_out_of_reach_is_judged_where_the_dance_stands_it(self):
        # the pelvis 0.4 (3.2 cm) over the rest pose's, the left foot's goal flat on the floor: MMD leaves the shoe some
        # 3 cm over it, and the layer before took the foot for one in the air (as at 197 s of the song).  Judged at its
        # goal, it is on the floor: it rises onto its ball as far as it goes (some 25 degrees), which brings the shoe
        # some 0.9 cm nearer the floor
        keys = [key("センター", 0, position=(0, 0.4, 0)), key("センター", 7, position=(0, 0.4, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8))]
        _, f_out, _, plan = run_layer(*keys, frames=8)
        _, f_old, _, _ = run_layer(*keys, frames=8, landing=False)
        old, new = f_old["左"]["low"] - 0.111, f_out["左"]["low"] - 0.111
        self.assertGreater(float(old.min()), 0.25)
        self.assertLess(float(new.max()), float(old.min()) - 0.1)
        self.assertGreater(float(plan["左"]["heel"].min()), 15.0)

    def test_a_standing_leg_in_reach_keeps_its_heel_down(self):
        keys = [key("センター", 0, position=(0, -0.3, 0)), key("センター", 7, position=(0, -0.3, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8))]
        f_in, f_out, out, plan = run_layer(*keys, frames=8)
        self.assertGreater(float(f_out["左"]["pitch"].min()), -0.5)

    def test_a_foot_skimming_the_floor_is_not_pressed_onto_it(self):
        # the left foot glides 30 cm/s sideways with its flat sole 5.4 mm over the floor (over the contact's hysteresis:
        # the dance's own swing, not a touch): it keeps that height; the same foot standing still there is put (most of
        # the way) onto the floor
        lift = 0.068
        moving = [key("センター", 0, position=(0, -1.2, 0)), key("右足ＩＫ", 0, position=(0, 0.0, 0.8))] + \
            [key("左足ＩＫ", t, position=(0.125 * t, lift, 0.0)) for t in range(13)]
        still = [key("センター", 0, position=(0, -1.2, 0)), key("右足ＩＫ", 0, position=(0, 0.0, 0.8))] + \
            [key("左足ＩＫ", t, position=(0.0, lift, 0.0)) for t in range(13)]
        _, f_move, _, _ = run_layer(*moving, frames=13)
        _, f_still, _, _ = run_layer(*still, frames=13)
        self.assertGreater(float(f_move["左"]["low"][3:10].min()), 0.111 + 0.8 * lift)
        self.assertLess(float(f_still["左"]["low"][3:10].max()), 0.111 + 0.6 * lift)


class SkimTest(unittest.TestCase):
    """a foot the dance moves fast just over the floor is not pressed onto it, in either run of the order C (v11feet,
    2026-10-17: after the retarget, which carries a shoe as high over the floor as the source's, the first foot layer,
    --landing off, put such shoes onto the floor and they slid along it: the song's slide 380 -> 604 cm a minute, 160 of
    it on feet the input had over the floor, most of them faster than 30 cm/s and 3 to 4 mm up)"""

    def gliding(self, lift, step=0.125):
        """the left foot gliding `step` units a frame sideways (0.125: 30 cm/s), its flat sole `lift` over the floor"""
        return [key("センター", 0, position=(0, -1.2, 0)), key("右足ＩＫ", 0, position=(0, 0.0, 0.8))] + \
            [key("左足ＩＫ", t, position=(step * t, lift, 0.0)) for t in range(13)]

    def test_the_first_foot_layer_leaves_a_gliding_foot_over_the_floor(self):
        lift = 0.068                                                          # 5.4 mm
        _, f_new, _, _ = run_layer(*self.gliding(lift), frames=13, landing=False)
        _, f_old, _, _ = run_layer(*self.gliding(lift), frames=13, landing=False, skim=False)
        self.assertGreater(float(f_new["左"]["low"][3:10].min()), 0.111 + 0.8 * lift)
        self.assertLess(float(f_old["左"]["low"][3:10].max()), 0.111 + 0.6 * lift)     # (the layer before pressed it)

    def test_a_foot_gliding_under_the_contacts_hysteresis_is_left_over_the_floor(self):
        lift = 0.035                                                          # 2.8 mm, under CONTACT_EXIT (4.8 mm)
        for landing in (True, False):
            _, f, _, _ = run_layer(*self.gliding(lift), frames=13, landing=landing)
            self.assertGreater(float(f["左"]["low"][3:10].min()), 0.111 + 0.8 * lift, landing)

    def test_a_still_foot_just_over_the_floor_is_put_onto_it(self):
        lift = 0.035
        for landing in (True, False):
            _, f, _, _ = run_layer(*self.gliding(lift, step=0.0), frames=13, landing=landing)
            self.assertLess(float(f["左"]["low"][3:10].max()), 0.111 + 0.3 * lift, landing)


class CommandTest(unittest.TestCase):
    def write_inputs(self, folder):
        src, model = os.path.join(folder, "in.vmd"), os.path.join(folder, "m.pmx")
        q = rolled("左", 15.0)
        vmd.dump(motion(key("左足ＩＫ", 0, q), key("左足首", 0, q), key("センター", 0, position=(0, -0.8, 0)),
                        key("センター", 3, position=(0, -0.8, 0))), src)
        with open(model, "wb") as fh:
            fh.write(DATA)
        return src, model

    def test_writes_the_dance_and_reports_it_against_the_traces_floor(self):
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            out, rep = os.path.join(folder, "out.vmd"), os.path.join(folder, "r.json")
            with contextlib.redirect_stdout(io.StringIO()):
                code = foot_layer.main([src, model, out, "--report", rep])
            self.assertEqual(code, 0)
            with open(rep, encoding="utf-8") as fh:
                r = json.load(fh)
            self.assertAlmostEqual(r["floor_y"], 0.111, 5)                 # none given: the trace's floor
            self.assertTrue(r["untouched"]["identical"])
            self.assertGreater(r["input"]["L"]["roll_in_contact_deg"]["max"], 10.0)
            self.assertLess(r["output"]["L"]["roll_in_contact_deg"]["max"], 0.5)
            self.assertEqual(r["output"]["L"]["penetration"]["frames"], 0)
            self.assertLess(r["output"]["L"]["hover_in_contact_cm"]["max"], 0.02)
            self.assertEqual(len({k.frame for k in vmd.load(out).bones if k.name == "左足首"}), 4)
            self.assertEqual(r["trace_toe_cm"], 0.0)
            self.assertIn("trace_toe_extra_estimate_cm", r["input"]["L"])
            with contextlib.redirect_stdout(io.StringIO()):
                foot_layer.main([src, model, out, "--report", rep, "--trace-toe-cm", "4.0"])
            with open(rep, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["trace_toe_cm"], 4.0)
        finally:
            shutil.rmtree(folder)

    def test_report_checks_between_the_frames(self):
        # the report measures the shoe at the 1/8 frames MMD draws, on the written dance read back
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            out, rep = os.path.join(folder, "out.vmd"), os.path.join(folder, "r.json")
            with contextlib.redirect_stdout(io.StringIO()):
                foot_layer.main([src, model, out, "--report", rep])
            with open(rep, encoding="utf-8") as fh:
                r = json.load(fh)
            between = r["between_frames"]
            self.assertGreater(between["output"]["L"]["checked"], 0)
            self.assertEqual(between["output"]["L"]["below"], 0)
            self.assertIn("raised_frames", between["layer"]["L"])
        finally:
            shutil.rmtree(folder)

    def test_toes_option_and_their_report(self):
        # --toes picks the toes' model (anatomical by default, v1 the merged layer's), --toe-reach-cm the reach (off by
        # default); the report has the toes' measures of the input and of the output read back
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            for extra, mode, reach in (([], "anatomical", 0.0), (["--toes", "v1"], "v1", 0.0),
                                       (["--toe-reach-cm", "2.5"], "anatomical", 2.5)):
                out, rep = os.path.join(folder, "out.vmd"), os.path.join(folder, "r.json")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(foot_layer.main([src, model, out, "--report", rep] + extra), 0)
                with open(rep, encoding="utf-8") as fh:
                    r = json.load(fh)
                self.assertEqual(r["toe_model"], mode)
                self.assertEqual(r["toe_reach_cm"], reach)
                for which in ("input", "output"):
                    t = r["toes"][which]["L"]
                    for k in ("push_off", "on_the_tip_frames", "bent_up_in_the_air", "tip_up_on_the_floor",
                              "still_pointed_hover", "bend_deg", "bend_step_deg"):
                        self.assertIn(k, t)
                self.assertTrue(r["untouched"]["identical"])
        finally:
            shutil.rmtree(folder)

    def test_warns_when_the_first_foot_layer_has_no_landing_given(self):
        # the order C runs the foot layer twice and its first run (on a dance no foot layer has written) wants
        # --landing off: without --landing there it warns (stderr and the report); with it, or on the layer's own
        # output (the second run), it does not
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            out, rep = os.path.join(folder, "out.vmd"), os.path.join(folder, "r.json")
            out2 = os.path.join(folder, "out2.vmd")
            for args, warned, mode in (([src, model, out], True, "human"),
                                       ([src, model, out, "--landing", "off"], False, "off"),
                                       ([out, model, out2], False, "human")):
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    self.assertEqual(foot_layer.main(args + ["--report", rep]), 0)
                with open(rep, encoding="utf-8") as fh:
                    r = json.load(fh)
                self.assertEqual(r["landing_model"], mode)
                self.assertEqual(r["landing_warning"] is not None, warned)
                self.assertEqual("WARNING" in err.getvalue(), warned)
        finally:
            shutil.rmtree(folder)

    def test_skim_option(self):
        # --skim on (the default, also with --landing off) leaves a foot moving fast just over the floor there; off: the
        # layer before (with --landing off, c012c32's)
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            out, rep = os.path.join(folder, "out.vmd"), os.path.join(folder, "r.json")
            for extra, skim in (([], "on"), (["--landing", "off"], "on"), (["--landing", "off", "--skim", "off"], "off")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(foot_layer.main([src, model, out, "--report", rep] + extra), 0)
                with open(rep, encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["skim"], skim)
        finally:
            shutil.rmtree(folder)

    def test_refuses_to_write_over_the_dance(self):
        folder = tempfile.mkdtemp()
        try:
            src, model = self.write_inputs(folder)
            with open(src, "rb") as fh:
                before = fh.read()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                foot_layer.main([src, model, src])
            with open(src, "rb") as fh:
                self.assertEqual(fh.read(), before)
        finally:
            shutil.rmtree(folder)


RIN_PATHS = ("C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx",
             "C:/Users/nayta/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx")


def rin_path():
    for p in RIN_PATHS:
        if os.path.isfile(p):
            return p
    raise unittest.SkipTest("Sour's Rin (White.pmx) is in none of %s" % (RIN_PATHS,))


class SourRinShoeTest(unittest.TestCase):
    def test_rin_sole(self):
        path = rin_path()
        rig = leg_ik.LegRig.load(path)
        shoe = foot_layer.Shoe.load(rig, path)
        for s, sx in (("左", 1.0), ("右", -1.0)):
            o = shoe.sides[s]
            self.assertAlmostEqual(o.floor, 0.111, 2)
            self.assertGreater(len(o.points), 30)
            # the heel block lies behind the ankle, the forefoot in front of the ball
            heel_t = ((o.points[o.heel] - o.ankle) @ o.a0)
            fore_t = ((o.points[o.fore] - o.ankle) @ o.a0)
            self.assertLess(heel_t.max(), 0.0)
            self.assertGreater(fore_t.min(), 0.4)
            self.assertGreater(o.l0[0] * sx, 0.95)


class HoverSupportTest(unittest.TestCase):
    """floaty (2026-10-17): no foot on the floor, yet the lower one just over it and the pelvis not falling: the body is held
    by nothing (a05 s11's 'hover support': the MV 8 % of the song, people 1.4 % [0.5, 2.2] of FineDance's near kinds).
    The whole figure is lowered until the lower shoe stands on the floor (every joint's angle kept: putting the foot down
    alone straightened the knees); a real hop (the pelvis falling at gravity) keeps its height."""
    F = 30
    HOVER = range(10, 20)

    def keys(self, lift, pelvis=None, base=-1.2):
        """both feet flat, their soles `lift` units over the trace's floor (0.111) in HOVER and on it elsewhere, the right
        foot 0.2 higher than the left (clearly off the floor); the pelvis (センター) at base + pelvis[t]"""
        out = []
        for t in range(self.F):
            h = lift if t in self.HOVER else 0.0
            out += [key("左足ＩＫ", t, position=(0, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.2 if h else 0.0), 0)),
                    key("センター", t, position=(0, base + (pelvis[t] if pelvis is not None else 0.0), 0))]
        return out

    def legs(self, m):
        sol = leg_ik.solve(RIG, m, range(self.F))
        bend = {}
        for s in ("左", "右"):
            u, v = sol[s]["hip"] - sol[s]["knee"], sol[s]["ankle"] - sol[s]["knee"]
            c = np.sum(u * v, axis=1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
            bend[s] = 180.0 - np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))
        return sol, bend

    def test_a_figure_hovering_with_the_pelvis_held_is_lowered_onto_the_floor(self):
        m_in = motion(*self.keys(0.1875))                                        # 1.5 cm over the floor, 10 frames
        f_in, f_out, out, plan = run_layer(*self.keys(0.1875), frames=self.F)
        s_in, b_in = self.legs(m_in)
        s_out, b_out = self.legs(out)
        for t in range(12, 18):                 # (the sink is eased in and out at the run's ends)
            self.assertGreater(float(f_in["左"]["low"][t]) - 0.111, 0.15)
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)      # the lower shoe on the floor
            if 14 <= t <= 16:                   # (next to the touches the floor's corrections spread into the air)
                self.assertAlmostEqual(float(f_out["右"]["low"][t] - f_out["左"]["low"][t]), 0.2, delta=0.02)   # the other above it
            drop = 0.5 * float(s_in["左"]["hip"][t, 1] + s_in["右"]["hip"][t, 1] - s_out["左"]["hip"][t, 1] - s_out["右"]["hip"][t, 1])
            self.assertAlmostEqual(drop, 0.1875, delta=0.03)                      # the pelvis lowered with it
            for s in ("左", "右"):
                self.assertLess(abs(float(b_out[s][t] - b_in[s][t])), 1.5)        # the knees keep their bend
        self.assertEqual(len(plan["左"]["sink_info"]["runs"]), 1)

    def test_the_sink_comes_and_goes_gently(self):
        f_in, f_out, out, plan = run_layer(*self.keys(0.1875), frames=self.F)
        s = plan["左"]["sink"]
        acc = np.diff(s, 2) * 30.0 ** 2
        self.assertLess(float(np.abs(acc).max()), 50.0)                           # units/s^2 added to the pelvis
        self.assertLess(float(s[0]), 1e-6)
        self.assertLess(float(s[-1]), 1e-6)

    def test_a_hop_keeps_its_height(self):
        # the pelvis rises and falls over the 10 frames as a body in flight does (122.5 units/s^2: gravity at 8 cm a unit;
        # 2 units up at the top, from a deep bend so that the legs still reach)
        n = np.arange(self.F)
        t = (n - 14.5) / 30.0
        arc = np.where((n >= 9) & (n <= 20), 0.5 * 122.5 * ((5.5 / 30.0) ** 2 - t ** 2), 0.0)
        f_in, f_out, out, plan = run_layer(*self.keys(0.1875, pelvis=arc, base=-3.2), frames=self.F)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])
        for t in range(12, 18):
            self.assertGreater(float(f_out["左"]["low"][t]) - 0.111, 0.15)        # not put down on the floor

    def test_a_foot_clearly_up_is_not_pulled_down(self):
        f_in, f_out, out, plan = run_layer(*self.keys(0.6), frames=self.F)        # 4.8 cm: a step, not a hover
        for t in self.HOVER:
            self.assertGreater(float(f_out["左"]["low"][t]) - 0.111, 0.5)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])

    def test_off_is_the_layer_before(self):
        keys = self.keys(0.1875)
        a, _ = foot_layer.layer(RIG, SHOE, motion(*keys), {"hover": False})
        b = foot_layer.measure_feet(RIG, SHOE, a, range(self.F))
        for t in self.HOVER:
            self.assertGreater(float(b["左"]["low"][t]) - 0.111, 0.15)

    def test_a_hover_of_two_frames_is_left(self):
        keys = []
        for t in range(self.F):
            h = 0.1875 if t in (14, 15) else 0.0
            keys += [key("左足ＩＫ", t, position=(0, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.2 if h else 0.0), 0)),
                     key("センター", t, position=(0, -1.2, 0))]
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])
        self.assertLess(float(np.abs(plan["左"]["sink"]).max()), 1e-9)

    def pelvis_fall(self, m):
        """the downward acceleration [F] (units/s^2, + down) of 下半身 and of センター (the larger), as forward kinematics
        puts them (mmd_cli.fk: both above the legs' IK)"""
        pose = fk.Pose(pmx.loads(DATA), m, ["下半身", "センター"])
        worlds = [pose.at(t) for t in range(self.F)]
        out = np.zeros(self.F)
        for name in ("下半身", "センター"):
            y = np.array([w[name][0][1] for w in worlds])
            a = np.zeros(self.F)
            a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * 30.0 ** 2
            out = np.maximum(out, a)
        return out

    def test_the_sink_does_not_take_the_pelvis_fall_past_the_bound(self):
        # the dance's pelvis already falls at the balance layer's bound (122 units/s^2) for the 6 frames before the hover,
        # then stays, the feet on the floor: the sink may not add to that fall.  The bound is gravity at Rin's size (9.8
        # m/s^2 at 8 cm a unit, 122.5): faster than it the skirt flies up (HANDOVER 2026-10-16, the skirt and the balance
        # layer), and no floor holds a body falling faster
        g = 9.8 / 0.08
        fall = np.array([-0.5 * 122.0 * ((min(max(t, 4), 10) - 4) / 30.0) ** 2 for t in range(self.F)])
        m_in = motion(*self.keys(0.1875, pelvis=fall))
        f_in, f_out, out, plan = run_layer(*self.keys(0.1875, pelvis=fall), frames=self.F)
        a_in, a_out = self.pelvis_fall(m_in), self.pelvis_fall(out)
        self.assertGreater(float(a_in.max()), 120.0)                               # the input does fall at about the bound
        self.assertTrue(np.all(a_out <= np.maximum(g, a_in) + 0.5), (a_in.round(1), a_out.round(1)))
        self.assertGreater(float(plan["左"]["sink"].max()), 0.1)                   # (the run is still lowered)
        self.assertEqual(plan["左"]["sink_info"]["acc_past_bound_frames"], 0)

    def test_a_hop_whose_fall_lies_inside_the_run_keeps_its_height(self):
        # both feet 2.4 cm up for 10 frames and the pelvis hops in them (the song's 213.5 s, base2: a dip, 6 cm up and
        # down, falling at 190 units/s^2 on three frames): over the whole run its curve is flatter than half of gravity
        # (the take-off and the landing are in it), yet it falls faster than gravity: a flight, not a figure held up
        hop = np.array([-0.95, -1.73, -1.14, 1.22, 3.73, 4.53, 3.65, 1.57, -1.27]) / 8.0
        pel = np.zeros(self.F)
        pel[10:19] = hop
        keys = []
        for t in range(self.F):
            h = 0.3 if 10 <= t <= 19 else 0.0
            keys += [key("左足ＩＫ", t, position=(0, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.05 if h else 0.0), 0)),
                     key("センター", t, position=(0, -1.2 + pel[t], 0))]
        self.assertGreater(float(self.pelvis_fall(motion(*keys)).max()), 150.0)
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])
        for t in range(11, 19):
            self.assertGreater(float(f_out["左"]["low"][t]) - 0.111, 0.25)        # the hop keeps the feet up

    def test_a_pointed_hovering_foot_keeps_its_shape(self):
        # both feet pointed 40 degrees toes-down (on the toes, as the trace's longer feet stood), their tips 1.5 cm over the
        # floor: the figure comes down, the feet keep their pitch and the toes are not bent onto the floor, the knees keep
        # their bend (standing it on the ball would lower the ankle and straighten the knee)
        q = axis_angle((1, 0, 0), -40.0)
        center = key("センター", 0, position=(0, -1.2, 0))
        probe = measure(key("左足ＩＫ", 0, q, position=(0, 1.0, 0)), key("左足首", 0, q), center)["左"]
        lift0 = 1.0 + 0.111 - float(probe["low"][0])                  # the IK height that puts the tip on the floor
        keys = [center]
        for t in range(self.F):
            h = 0.1875 if t in self.HOVER else 0.0
            keys += [key("左足ＩＫ", t, q, position=(0, lift0 + h, 0)), key("左足首", t, q),
                     key("右足ＩＫ", t, q, position=(0, lift0 + h + 0.2, 0)), key("右足首", t, q)]
        m_in = motion(*keys)
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        off, _ = foot_layer.layer(RIG, SHOE, m_in, {"hover": False})          # the layer as it was: the run in the air
        f_off = foot_layer.measure_feet(RIG, SHOE, off, range(self.F))
        s_in, b_in = self.legs(m_in)
        s_out, b_out = self.legs(out)
        self.assertEqual(len(plan["左"]["sink_info"]["runs"]), 1)
        for t in range(13, 17):
            self.assertGreater(float(f_off["左"]["low"][t]) - 0.111, 0.15)        # (without the sink: over the floor)
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)      # the tip on the floor
            self.assertAlmostEqual(float(f_out["左"]["pitch"][t]), float(f_off["左"]["pitch"][t]), delta=1.0)
            self.assertLess(abs(float(f_out["左"]["mtp"][t] - f_off["左"]["mtp"][t])), 1.0)   # the toes as in the air
            for s_ in ("左", "右"):
                self.assertLess(abs(float(b_out[s_][t] - b_in[s_][t])), 1.5)

    def test_a_gap_that_steps_from_frame_to_frame_makes_no_spike_of_the_centre(self):
        # the lower shoe 1.2 and 2.0 cm over the floor on alternate frames (the trace's 0.3 unit grid): the pelvis is lowered
        # smoothly (no one-frame spike), the lower shoe still held on the floor
        keys = []
        for t in range(self.F):
            h = (0.15 if t % 2 else 0.25) if t in self.HOVER else 0.0
            keys += [key("左足ＩＫ", t, position=(0, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.2 if h else 0.0), 0)),
                     key("センター", t, position=(0, -1.2, 0))]
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        acc = np.diff(plan["左"]["sink"], 2) * 30.0 ** 2
        self.assertLess(float(np.abs(acc).max()), 60.0)
        for t in range(12, 18):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)

    def run_of(self, lifts, other=2.5):
        """runs of a left foot whose sole is lifts[t] units over the trace's floor, the right one `other` up, the pelvis held"""
        keys = [key("センター", 0, position=(0, -1.2, 0)), key("右足ＩＫ", 0, position=(0, other, 0.8))]
        keys += [key("左足ＩＫ", t, position=(0, h, 0)) for t, h in enumerate(lifts)]
        return run_layer(*keys, frames=len(lifts))

    def test_a_foot_rising_through_the_band_at_a_lift_off_is_not_a_hover(self):
        # 0.6 cm a frame (18 cm/s, slower than HOVER_FOOT_SPEED) from the floor up through 4 cm: a step's lift, not held
        lifts = [0.0] * 5 + [0.075 * k for k in range(1, 9)] + [0.6] * 5
        f_in, f_out, out, plan = self.run_of(lifts)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])

    def test_a_foot_coming_down_fast_is_not_a_hover(self):
        # 0.8 cm a frame (24 cm/s) from 5.6 cm onto the floor: a touch
        lifts = [0.7 - 0.1 * k for k in range(8)] + [0.0] * 8
        f_in, f_out, out, plan = self.run_of(lifts)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])

    def test_a_goal_out_of_reach_is_not_a_hover(self):
        # the pelvis 3.2 cm over the rest pose's, the left foot's goal flat on the floor: MMD leaves the shoe some 3 cm
        # over it, but the dance stands it on the floor (LandingTest: it rises onto its ball): not lowered
        keys = [key("センター", 0, position=(0, 0.4, 0)), key("センター", 9, position=(0, 0.4, 0)),
                key("右足ＩＫ", 0, position=(0, 2.5, 0.8))]
        f_in, f_out, out, plan = run_layer(*keys, frames=10)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])

    def glide_keys(self, step, first=8, last=21, up=None):
        """both feet 1.5 cm over the floor (frames `up`, HOVER when not given), the pelvis held, the lower (left) one
        travelling `step` units a frame sideways from frame `first` to `last`"""
        up = self.HOVER if up is None else up
        keys = []
        for t in range(self.F):
            h = 0.1875 if t in up else 0.0
            x = step * (min(max(t, first), last) - first)
            keys += [key("左足ＩＫ", t, position=(x, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.2 if h else 0.0), 0)),
                     key("センター", t, position=(0, -1.2, 0))]
        return keys

    def test_a_foot_gliding_over_the_floor_is_not_sunk_onto_it(self):
        # both feet 1.5 cm over the floor for 10 frames, the pelvis held, but the lower one travels 45 cm/s sideways (a
        # step's swing skimming the floor: the layer takes a pointed foot as on the trace model's toe only below 30 cm/s,
        # TOE_SLIDE): lowering the figure would drag it along the floor (the song's sunk runs slid their toe at 50-200
        # cm/s, a05's slides 10 cm and longer 21.9 -> 29.5 a minute, people 11.3 [7.7, 16.8]); the same hover standing
        # still is lowered (test_a_figure_hovering_...)
        keys = self.glide_keys(0.1875)
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        self.assertEqual(plan["左"]["sink_info"]["runs"], [])
        for t in range(12, 18):
            self.assertGreater(float(f_out["左"]["low"][t]) - 0.111, 0.15)        # left over the floor as the dance has it
        # hover_glide (--hover-glide) sets the speed: set over the foot's 45 cm/s, it lowers the gliding foot onto the floor
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F, hover_glide=1000.0)
        self.assertEqual(len(plan["左"]["sink_info"]["runs"]), 1)
        for t in range(13, 17):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)

    def test_a_toe_drifting_slowly_is_lowered(self):
        # the same hover, the lower foot drifting 20 cm/s (0.7 cm a frame: a toe on the floor slides that slowly, people's
        # contact steps slip faster than 20 cm/s in 5 % of them): lowered onto the floor like a held one
        f_in, f_out, out, plan = run_layer(*self.glide_keys(0.0833), frames=self.F)
        self.assertEqual(len(plan["左"]["sink_info"]["runs"]), 1)
        for t in range(13, 17):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)

    def test_a_pointed_foot_turning_on_its_tip_is_lowered(self):
        # both feet pointed 40 degrees toes-down, their tips 1.5 cm over the floor, the left one turning 24 degrees a frame
        # about the vertical through its tip (a turn on the toes: the tip stays, the rest of the foot swings round it, its
        # forefoot at 40 cm/s): the tip does not travel, so the figure is lowered onto it as onto a still one
        q0 = np.array(axis_angle((1, 0, 0), -40.0))
        center = key("センター", 0, position=(0, -1.2, 0))
        probe = measure(key("左足ＩＫ", 0, tuple(q0), position=(0, 1.0, 0)), key("左足首", 0, tuple(q0)), center)["左"]
        lift0 = 1.0 + 0.111 - float(probe["low"][0])
        ankle0, cap = rest("足首"), np.array(CAP[:3])
        keys = [center]
        for t in range(self.F):
            h = 0.1875 if t in self.HOVER else 0.0
            tip = ankle0 + np.array([0.0, lift0 + h, 0.0]) + leg_ik.qrot(q0, cap - ankle0)
            q = leg_ik.qmul(np.array(axis_angle((0, 1, 0), 24.0 * (min(max(t, 8), 21) - 8))), q0)
            ankle = tip - leg_ik.qrot(q, cap - ankle0)
            keys += [key("左足ＩＫ", t, tuple(q), position=tuple(ankle - ankle0)), key("左足首", t, tuple(q)),
                     key("右足ＩＫ", t, tuple(q0), position=(0, lift0 + h + 0.2, 0)), key("右足首", t, tuple(q0))]
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        fore = np.linalg.norm(np.diff(f_in["左"]["fore_xz"], axis=0), axis=1) * 30.0 * 8.0
        self.assertGreater(float(np.median(fore[10:19])), 30.0)                   # (its forefoot does move fast, cm/s)
        self.assertEqual(len(plan["左"]["sink_info"]["runs"]), 1)
        for t in range(13, 17):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)      # the tip on the floor

    def test_the_touching_part_that_holds_still_sets_the_speed(self):
        # a flat shoe turning 6 degrees a frame about the vertical through a forefoot point of its sole (a turn on the ball,
        # the bones' turns given directly): its heel, the lowest at rest, sweeps round at some 35 cm/s, but the part on the
        # ball holds still, so the shoe does not travel along the floor
        F = 8
        sol = leg_ik.solve(RIG, motion(key("センター", 0, position=(0, -1.2, 0)), key("センター", F - 1, position=(0, -1.2, 0))),
                           range(F))
        o = SHOE.sides["左"]
        ankle0, ex0 = rest("足首"), rest("足先EX")
        ball = np.array(SOLE[6][:3])
        q = np.array([axis_angle((0, 1, 0), 6.0 * t) for t in range(F)])
        ankle = ball[None] - leg_ik.qrot(q, (ball - ankle0)[None])
        leg = dict(sol["左"], ankle=ankle, q_foot=q, ex=ankle + leg_ik.qrot(q, (ex0 - ankle0)[None]), q_ex=q)
        v = foot_layer.touch_speed(o, leg)
        heel = np.array(SOLE[0][:3])
        sweep = np.linalg.norm((heel - ball)[[0, 2]]) * np.radians(6.0) * 30.0 * 8.0
        self.assertGreater(sweep, 30.0)
        self.assertLess(float(v.max()), 1.0)

    def test_a_held_piece_is_judged_with_its_whole_hover(self):
        # both feet 1.5 cm up from frame 4 to 27, the lower one still until frame 8 and then travelling 45 cm/s; the pelvis
        # bobs 2.2 cm over frames 3-8 (80 units/s^2 at the top: a body held up can do that) and then stays.  Whether the
        # hover is a flight is judged on the whole hover (not a flight), not on the held frames alone (whose own curve, the
        # bob, is steeper than half of gravity): the held frames are lowered
        n = np.arange(self.F)
        bob = np.where((n >= 3) & (n <= 8), 0.5 * 80.0 * ((2.5 / 30.0) ** 2 - ((n - 5.5) / 30.0) ** 2), 0.0)
        keys = []
        for t in range(self.F):
            h = 0.1875 if 4 <= t <= 27 else 0.0
            x = 0.1875 * max(0, t - 8)
            keys += [key("左足ＩＫ", t, position=(x, h, 0)), key("右足ＩＫ", t, position=(0, h + (0.2 if h else 0.0), 0)),
                     key("センター", t, position=(0, -1.2 + bob[t], 0))]
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        rr = plan["左"]["sink_info"]["runs"]
        self.assertEqual(len(rr), 1)
        self.assertEqual(rr[0][0], 4)
        for t in range(4, 7):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.03)

    def test_only_the_held_part_of_a_hover_is_lowered(self):
        # both feet 1.5 cm up from frame 4 to 27, the lower one still until frame 14 and then travelling 45 cm/s (the song's
        # 26.0 s: the toe held for 12 frames, then sliding off at 80-200 cm/s): the held part is lowered onto the floor, the
        # travelling part comes back up to the dance's height once the sink has eased out
        keys = self.glide_keys(0.1875, first=14, last=self.F, up=range(4, 28))
        f_in, f_out, out, plan = run_layer(*keys, frames=self.F)
        rr = plan["左"]["sink_info"]["runs"]
        self.assertEqual(len(rr), 1)
        self.assertLessEqual(rr[0][0], 5)
        self.assertIn(rr[0][1], (13, 14))
        for t in range(6, 12):
            self.assertLess(abs(float(f_out["左"]["low"][t]) - 0.111), 0.02)      # held: on the floor
        for t in range(23, 27):
            self.assertGreater(float(f_out["左"]["low"][t]) - 0.111, 0.15)        # travelling: as the dance has it


if __name__ == "__main__":
    unittest.main()
