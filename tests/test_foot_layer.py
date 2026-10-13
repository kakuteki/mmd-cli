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

    def test_roll_past_the_subtalar_cap_stays_on_its_edge(self):
        # the shank leaning out 40 degrees over a foot the trace keeps level: inverting so much is past the cap, so the
        # foot keeps part of its roll and stands on its edge (the edge on the floor, the foot inside its range)
        lean = axis_angle((0, 0, 1), -40.0)                         # the thigh turned so that the shank leans out
        f_in, f_out, out, plan = run_layer(key("センター", 0, position=(0, -1.5, 0)), key("左足", 0, lean),
                                           key("左足ＩＫ", 0, position=(0.8, 0.0, 0.0)), floor_y=0.0)
        b = f_out["左"]
        cap = foot_layer.REFERENCE["inversion"][1]
        self.assertLess(abs(float(b["inversion"][0])), cap + 0.5)
        self.assertGreater(float(b["low"][0]), -foot_layer.PEN_TOL)

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
        # the foot comes down over 12 frames rolled 15 degrees and stands 8: no step bigger than the input's
        q = rolled("左", 15.0)
        keys = [key("センター", 0, position=(0, -0.8, 0)), key("左足首", 0, q),
                key("左足ＩＫ", 0, q, position=(0, 2.0, -0.5)), key("左足ＩＫ", 12, q), key("左足ＩＫ", 20, q)]
        f_in, f_out, out, plan = run_layer(*keys, frames=21)
        a, b = f_in["左"], f_out["左"]
        step_in = np.abs(np.diff(a["ankle"][:, 1]))
        step_out = np.abs(np.diff(b["ankle"][:, 1]))
        self.assertLess(float(step_out.max()), float(step_in.max()) + 0.02)
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


if __name__ == "__main__":
    unittest.main()
