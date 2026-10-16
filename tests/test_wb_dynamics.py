"""tools/wb_dynamics.py: the whole body's centre of mass by segment masses, the base of support from the feet on the floor,
the zero moment point (the centre of pressure a flat floor would need) and the whole-body angular momentum about the COM.
The tests check the physics on bodies whose answer is known without the tool: a still body, a body swaying as one rigid
piece, a free fall, a spin about a principal axis, an inverted pendulum falling freely about its toe."""
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import vmd
from tests.test_balance_layer import MODEL, balance_layer, dance, key, model_bytes

import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    spec = importlib.util.spec_from_file_location("wb_dynamics", os.path.join(ROOT, "tools", "wb_dynamics.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wb = load_tool()

FPS = 30.0
U = 0.08                         # metres a model unit
G = 9.81

# Sour's Rin's rest landmarks (model units, White.pmx): the bones the tool reads
REST = {"vertex": (0.0, 18.7663, -0.1601), "cerv": (0.0, 15.6456, -0.1343), "xyph": (0.0, 13.7985, -0.6784),
        "omph": (0.0, 12.2248, -0.6493)}
for _s, _x in (("L", 1.0), ("R", -1.0)):
    REST.update({"hip_" + _s: (_x * 0.9012, 10.6579 if _s == "L" else 10.591, 0.0073),
                 "knee_" + _s: (_x * 1.0032, 6.2313, -0.0361), "ankle_" + _s: (_x * 1.1205, 1.7452, 0.37),
                 "toe_" + _s: (_x * 1.0462, 0.1, -1.1496), "shoulder_" + _s: (_x * 0.9114, 15.2768, -0.2484),
                 "elbow_" + _s: (_x * 2.9071, 13.7325, -0.27), "wrist_" + _s: (_x * 4.6524, 12.4104, -0.2368),
                 "mid3_" + _s: (_x * 5.8701, 11.5382, -0.2637)})


def still(F=60, rest=None):
    rest = REST if rest is None else rest
    return {k: np.tile(np.asarray(v, dtype=np.float64), (F, 1)) for k, v in rest.items()}


def symmetric_rest():
    """REST with every z put to 0 and the right side the left side's mirror: x -> -x and z -> -z are symmetries, so the
    vertical axis through the COM is a principal axis"""
    out = {}
    for k, v in REST.items():
        if k.endswith("_R"):
            continue
        x, y, z = v
        if k.endswith("_L"):
            out[k] = (x, y, 0.0)
            out[k[:-2] + "_R"] = (-x, y, 0.0)
        else:
            out[k] = (0.0, y, 0.0)
    return out


def rotate_y(lm, angles, about):
    """every landmark turned about the vertical through `about` (x, z) by angles [F] (radians)"""
    out = {}
    c, s = np.cos(angles), np.sin(angles)
    for k, p in lm.items():
        d = p.copy()
        d[:, 0] -= about[0]
        d[:, 2] -= about[1]
        out[k] = np.stack([c * d[:, 0] + s * d[:, 2] + about[0], p[:, 1], -s * d[:, 0] + c * d[:, 2] + about[1]], 1)
    return out


class MassModelTest(unittest.TestCase):
    def test_segments_cover_the_whole_body(self):
        total = sum(v["mass"] for v in wb.SEGMENTS.values())
        self.assertAlmostEqual(total, 99.99, places=2)
        self.assertEqual(len(wb.SEGMENTS), 16)

    def test_standing_com_on_the_midplane_at_a_human_height(self):
        com = wb.com(wb.segments(still()))
        self.assertLess(abs(com[0, 0]), 1e-3)
        # people stand with the COM at 54-58 % of their stature (the vertex); Rin's legs are long (her hips at 57 % of the
        # vertex's height, a person's at about 50 %), so hers is higher
        share = com[0, 1] / REST["vertex"][1]
        self.assertTrue(0.54 < share < 0.62, share)

    def test_arm_moved_out_moves_the_com_by_the_arm_share(self):
        base = still()
        moved = still()
        for k in ("elbow_L", "wrist_L", "mid3_L"):
            moved[k][:, 0] += 1.0                    # the forearm and hand go 8 cm out (the upper arm's far end too)
        dx = wb.com(wb.segments(moved))[0, 0] - wb.com(wb.segments(base))[0, 0]
        # upper arm: its COM at 57.54 % of the way to the elbow moves 0.5754; forearm and hand move 1 (2.55, 1.38, 0.56 %)
        want = (2.55 * 0.5754 + 1.38 + 0.56) / 99.99
        self.assertAlmostEqual(dx, want, places=6)

    def test_hand_com_along_the_hand(self):
        """de Leva's hand (0.56 %) has its COM 34.27 % of the way from the wrist to the middle finger's tip; the tool reads
        the middle finger's distal joint, HAND_TIP_SHARE of that way"""
        base, moved = still(), still()
        moved["mid3_L"][:, 0] += 1.0
        dx = wb.com(wb.segments(moved))[0, 0] - wb.com(wb.segments(base))[0, 0]
        self.assertAlmostEqual(dx, 0.56 * (0.3427 / wb.HAND_TIP_SHARE) / 99.99, places=7)
        self.assertTrue(0.8 < wb.HAND_TIP_SHARE < 0.95)


class FilterTest(unittest.TestCase):
    def test_slow_kept_fast_removed_no_lag(self):
        t = np.arange(300) / FPS
        slow = np.sin(2 * math.pi * 1.0 * t)
        fast = np.sin(2 * math.pi * 12.0 * t)
        ys, yf = wb.lowpass(slow[:, None], 6.0)[:, 0], wb.lowpass(fast[:, None], 6.0)[:, 0]
        inner = slice(45, 255)
        self.assertLess(np.abs(ys[inner] - slow[inner]).max(), 0.02)        # 1 Hz: kept, and on time (no lag)
        self.assertLess(np.abs(yf[inner]).max(), 0.1)                       # 12 Hz: gone

    def test_constant_and_line_kept_to_the_ends(self):
        x = np.stack([np.full(50, 3.0), np.linspace(0.0, 1.0, 50)], 1)
        np.testing.assert_allclose(wb.lowpass(x, 6.0), x, atol=1e-9)


class AngularVelocityTest(unittest.TestCase):
    def test_spin_about_the_vertical(self):
        w = 4.0                                      # rad/s
        t = np.arange(40) / FPS
        q = np.stack([np.zeros(40), np.sin(w * t / 2), np.zeros(40), np.cos(w * t / 2)], 1)
        om = wb.angular_velocity(q)
        np.testing.assert_allclose(om[1:-1], np.tile([0.0, w, 0.0], (38, 1)), atol=1e-9)

    def test_sign_flips_of_the_quaternion_do_not_matter(self):
        w = 2.0
        t = np.arange(20) / FPS
        q = np.stack([np.sin(w * t / 2), np.zeros(20), np.zeros(20), np.cos(w * t / 2)], 1)
        q[::3] *= -1.0
        np.testing.assert_allclose(wb.angular_velocity(q)[1:-1, 0], w, atol=1e-9)


class ZmpTest(unittest.TestCase):
    def test_still_body_presses_under_its_com(self):
        lm = still()
        d = wb.dynamics(lm, floor_y=0.111)
        c = wb.com(wb.segments(lm))
        ok = d["zmp_ok"]
        self.assertTrue(ok[5:-5].all())
        np.testing.assert_allclose(d["zmp"][ok], c[ok][:, [0, 2]] * U, atol=1e-9)
        np.testing.assert_allclose(d["force"][ok][:, 1], G, atol=1e-9)      # the floor holds the weight (per kg)

    def test_rigid_sway_moves_the_pressure_against_the_acceleration(self):
        """a body swaying sideways as one rigid piece, x = A sin(2 pi f t): the floor's push must accelerate it, so the
        centre of pressure goes ahead of the COM: p = c - (c_y - h) x'' / g (the cart-table, exactly, for a rigid
        translation)"""
        F, A, f, h = 150, 0.5, 1.0, 0.111
        t = np.arange(F) / FPS
        x = A * np.sin(2 * math.pi * f * t)
        lm = still(F)
        for k in lm:
            lm[k][:, 0] += x
        d = wb.dynamics(lm, floor_y=h, cutoff_hz=6.0)
        c = wb.com(wb.segments(lm)) * U
        acc = -A * U * (2 * math.pi * f) ** 2 * np.sin(2 * math.pi * f * t)
        want = c[:, 0] - (c[:, 1] - h * U) * acc / G
        inner = slice(30, F - 30)
        np.testing.assert_allclose(d["zmp"][inner, 0], want[inner], atol=0.002)     # 2 mm
        self.assertGreater(np.abs(want - c[:, 0])[inner].max(), 0.03)               # (and the shift is a real one)

    def test_a_forearm_swung_round_the_elbow(self):
        """(the review, 2026-10-17: a body whose one part moves, worked by hand) the body stands still but the left forearm
        and hand go round the still elbow in a level circle, u(t) = (cos wt, 0, sin wt): their COMs (de Leva: the forearm's
        at 45.59 % of elbow -> wrist, the hand's at 34.27 / 0.88 % of wrist -> 中指３) are pulled to the elbow by w^2 d, so the
        floor's push must lean that way: ZMP = COM + w^2 (y_elbow - h) sum(m d) u / g (their own spin about the vertical
        stays the same, so it adds nothing).  The ZMP circles 2 cm round a COM that circles 0.5 cm"""
        F, hz, h = 150, 1.5, 0.111
        w = 2 * math.pi * hz
        t = np.arange(F) / FPS
        lm = still(F)
        E = np.array(REST["elbow_L"])
        Lf = float(np.linalg.norm(np.array(REST["wrist_L"]) - E))
        Lh = float(np.linalg.norm(np.array(REST["mid3_L"]) - np.array(REST["wrist_L"])))
        u = np.stack([np.cos(w * t), np.zeros(F), np.sin(w * t)], 1)
        lm["wrist_L"] = E + Lf * u
        lm["mid3_L"] = E + (Lf + Lh) * u
        d = wb.dynamics(lm, floor_y=h, cutoff_hz=6.0)
        c = wb.com(wb.segments(lm)) * U
        md = (1.38 * 0.4559 * Lf + 0.56 * (Lf + (0.3427 / wb.HAND_TIP_SHARE) * Lh)) / 99.99 * U     # sum m d per kg (m)
        want = c[:, [0, 2]] + (w * w * (E[1] - h) * U * md / G) * u[:, [0, 2]]
        inner = slice(30, F - 30)
        np.testing.assert_allclose(d["zmp"][inner], want[inner], atol=0.001)                      # 1 mm
        self.assertGreater(np.linalg.norm(want - c[:, [0, 2]], axis=1)[inner].min(), 0.015)
        # the same body and floor 4 m higher (the floor's height term, h F / F_y, then 9 cm): the same ZMP
        up = {k: v + np.array([0.0, 50.0, 0.0]) for k, v in lm.items()}
        np.testing.assert_allclose(wb.dynamics(up, floor_y=h + 50.0, cutoff_hz=6.0)["zmp"][inner], d["zmp"][inner], atol=1e-6)

    def test_free_fall_presses_on_nothing(self):
        F = 40
        t = np.arange(F) / FPS
        lm = still(F)
        for k in lm:
            lm[k][:, 1] += 20.0 - 0.5 * G * t ** 2 / U
        d = wb.dynamics(lm, floor_y=0.111)
        inner = slice(12, F - 12)
        self.assertLess(np.abs(d["force"][inner]).max(), 0.05)
        self.assertFalse(d["zmp_ok"][inner].any())

    def test_spin_about_a_principal_axis(self):
        """a body with x -> -x and z -> -z symmetry turning at a steady rate about the vertical through its COM: its angular
        momentum points up and stays, so the floor presses under the COM; the segments' own turning adds to the point
        masses' (I = sum m r^2 + the segments' inertia)"""
        F, w = 90, 3.0
        lm0 = still(F, symmetric_rest())
        c0 = wb.com(wb.segments(lm0))[0]
        lm = rotate_y(lm0, w * np.arange(F) / FPS, (c0[0], c0[2]))
        rots = {k: np.stack([np.zeros(F), np.sin(w * np.arange(F) / FPS / 2), np.zeros(F), np.cos(w * np.arange(F) / FPS / 2)], 1)
                for k in wb.ROTATED}
        d = wb.dynamics(lm, rots=rots, floor_y=0.111)
        inner = slice(20, F - 20)
        L = d["angmom"][inner]                          # per kg (m^2/s)
        self.assertLess(np.abs(L[:, [0, 2]]).max(), 1e-6)
        self.assertLess(np.ptp(L[:, 1]), 1e-6 * max(1.0, abs(L[0, 1])))
        segs = wb.segments(lm0)
        point = sum(s["mass"] / 99.99 * ((s["com"][0, 0] - c0[0]) ** 2 + (s["com"][0, 2] - c0[2]) ** 2) for s in segs.values()) * U * U
        self.assertGreater(L[0, 1], point * w * 1.001)                       # the segments' own inertia adds
        self.assertLess(L[0, 1], point * w * 1.6)
        np.testing.assert_allclose(d["zmp"][inner], np.tile([c0[0] * U, c0[2] * U], (F - 40, 1)), atol=1e-6)

    def test_inverted_pendulum_falling_on_its_toe_presses_at_the_toe(self):
        """the whole body as one rigid piece pivoting about a line on the floor (the toes) with no torque there falls as
        an inverted pendulum, I_O theta'' = M g l sin(theta): the floor pushes only through the pivot, so the ZMP stays on
        it while the body falls (point masses only: the segments' own spin is part of the same rigid turn and switched off
        here so that I_O is the point masses' sum).  The COM stands 7 cm behind the toes: the body falls back about them"""
        F = 20
        lm0 = still(F)
        pivot_z = -1.15                                 # the toes' line (z), units; the pivot is at the floor
        segs = wb.segments(lm0)
        m = {k: s["mass"] / 99.99 for k, s in segs.items()}
        r = {k: (s["com"][0] - np.array([0.0, 0.111, pivot_z])) * U for k, s in segs.items()}
        I_O = sum(m[k] * (r[k][1] ** 2 + r[k][2] ** 2) for k in segs)
        c = sum(m[k] * r[k] for k in segs) / sum(m.values())
        l = math.hypot(c[1], c[2])
        th0 = math.atan2(-c[2], c[1])                   # the COM's lean forward of the pivot (towards -z)
        # integrate theta'' = (g l / I_O) sin(theta) finely (per unit mass: M = sum m)
        k_ = G * l * sum(m.values()) / I_O
        th, om = th0, 0.0
        sub = 200
        ths = []
        for _ in range(F):
            ths.append(th)
            for _ in range(sub):
                om += k_ * math.sin(th) / (FPS * sub)
                th += om / (FPS * sub)
        dth = np.array(ths) - th0                      # the turn about the pivot line (the x axis), forward
        lm = {}
        for k, p in lm0.items():
            y, z = p[:, 1] - 0.111, p[:, 2] - pivot_z
            cs, sn = np.cos(dth), np.sin(dth)
            lm[k] = np.stack([p[:, 0], y * cs + z * sn + 0.111, -y * sn + z * cs + pivot_z], 1)
        d = wb.dynamics(lm, floor_y=0.111, spin=False, cutoff_hz=None)
        inner = slice(3, F - 3)
        ok = d["zmp_ok"][inner]
        self.assertTrue(ok.all())
        np.testing.assert_allclose(d["zmp"][inner][:, 1], pivot_z * U, atol=0.003)   # 3 mm (the finite differences)
        lean = np.abs(d["com"][inner][:, 2] - pivot_z * U)
        self.assertGreater(lean[-1], lean[0] + 0.05)    # (and it does fall, away from the pivot, 5 cm and more)

    def test_inverted_pendulum_with_the_segments_own_turning(self):
        """the same fall with the segments' own inertia (their bones turn with the body; the legs, which have no bone
        here, by their long axis' turn): I_O counts each segment's own moment about the pivot line too, and the ZMP
        still stays on the pivot (the segments' angular momentum enters the moment with the right sign)"""
        F = 20
        lm0 = still(F)
        pivot = np.array([0.0, 0.111, -1.15])
        segs = wb.segments(lm0)
        total = sum(s["mass"] for s in segs.values())
        I_O, mc = 0.0, np.zeros(3)
        for name, s in segs.items():
            m = s["mass"] / total
            r = (s["com"][0] - pivot) * U
            e, L = s["axis"][0], s["length"][0] * U
            rt, rl = 0.5 * (s["r"][0] + s["r"][1]) / 100.0, s["r"][2] / 100.0
            own = L * L * (rt * rt * (1.0 - e[0] ** 2) + (rl * rl * e[0] ** 2 if s["rot"] else 0.0))
            I_O += m * (r[1] ** 2 + r[2] ** 2 + own)
            mc += m * r
        l = math.hypot(mc[1], mc[2])
        th0 = math.atan2(-mc[2], mc[1])
        k_ = G * l / I_O
        th, om, ths = th0, 0.0, []
        for _ in range(F):
            ths.append(th)
            for _ in range(200):
                om += k_ * math.sin(th) / (FPS * 200)
                th += om / (FPS * 200)
        dth = np.array(ths) - th0
        lm = {}
        for k, p in lm0.items():
            y, z = p[:, 1] - pivot[1], p[:, 2] - pivot[2]
            cs, sn = np.cos(dth), np.sin(dth)
            lm[k] = np.stack([p[:, 0], y * cs + z * sn + pivot[1], -y * sn + z * cs + pivot[2]], 1)
        # the bones turn by -dth about +x (y' = y cos + z sin is a turn by -dth in the y-z plane)
        q = np.stack([np.sin(-dth / 2), np.zeros(F), np.zeros(F), np.cos(-dth / 2)], 1)
        rots = {k: q for k in wb.ROTATED}
        d = wb.dynamics(lm, rots=rots, floor_y=0.111, cutoff_hz=None)
        inner = slice(3, F - 3)
        np.testing.assert_allclose(d["zmp"][inner][:, 1], pivot[2] * U, atol=0.0005)       # 0.5 mm (measured 0.14)
        # and leaving the segments' own turning out puts the ZMP off the pivot (it is a real part of this fall: 1.8 mm,
        # so a wrong sign of it would show twice that)
        d0 = wb.dynamics(lm, rots=rots, floor_y=0.111, cutoff_hz=None, spin=False)
        self.assertGreater(np.abs(d0["zmp"][inner][:, 1] - pivot[2] * U).max(), 0.001)


class SupportTest(unittest.TestCase):
    def setUp(self):
        self.feet = wb.RIN_FEET

    def test_two_flat_feet_one_polygon_round_both_soles(self):
        lm = still(3)
        sup = wb.support(lm, self.feet)
        hull = sup["hull"][1]
        self.assertTrue(sup["contact"]["L"][1] and sup["contact"]["R"][1])
        self.assertEqual(sup["part"]["L"][1], "flat")
        mid = np.array([0.0, 0.37 * U - 0.03])                                    # between the feet
        self.assertGreater(wb.polygon_margin(mid, hull), 0.0)
        ahead = np.array([0.0, -1.1496 * U - 0.10])                              # 10 cm in front of the toes (-z)
        self.assertTrue(-0.12 < wb.polygon_margin(ahead, hull) < -0.08)
        # the polygon reaches out past both shoes' outer edges (Rin's soles are 6.8 cm wide at the forefoot)
        xs = hull[:, 0] / U
        self.assertGreater(xs.max(), 1.4)
        self.assertLess(xs.min(), -1.4)

    def test_lifted_foot_does_not_support(self):
        lm = still(3)
        for k in ("ankle_L", "toe_L"):
            lm[k][:, 1] += 1.0                        # 8 cm up
        sup = wb.support(lm, self.feet)
        self.assertFalse(np.any(sup["contact"]["L"]))
        hull = sup["hull"][1]
        self.assertTrue(np.all(hull[:, 0] < 0.0))      # the right foot alone (-x)

    def test_heel_up_keeps_the_forefoot(self):
        lm = still(3)
        lm["ankle_L"][:, 1] += 0.5                     # 4 cm: the heel up, the toes on the floor
        sup = wb.support(lm, self.feet)
        self.assertTrue(np.all(sup["part"]["L"] == "fore"))
        heel = np.array([1.1205 * U, (0.37 + 0.5) * U])                     # where the heel was
        foot = wb.foot_polygon(lm, self.feet, "L", 1, "fore")
        self.assertLess(wb.polygon_margin(heel, foot), 0.0)
        self.assertGreater(wb.polygon_margin(np.array([1.08 * U, -0.9 * U]), foot), 0.0)   # the ball inside

    def test_toes_up_keeps_the_heel(self):
        lm = still(3)
        lm["toe_L"][:, 1] += 0.5                       # the toes 4 cm up, the heel on the floor
        sup = wb.support(lm, self.feet)
        self.assertTrue(np.all(sup["part"]["L"] == "heel"))
        self.assertTrue(np.all(sup["contact"]["L"]))
        foot = wb.foot_polygon(lm, self.feet, "L", 1, "heel")
        behind = np.array([1.1205 * U, (0.37 + 0.25) * U])                  # 2 cm behind the ankle
        self.assertGreater(wb.polygon_margin(behind, foot), 0.0)
        self.assertLess(wb.polygon_margin(np.array([1.08 * U, -0.9 * U]), foot), 0.0)      # the ball is off the floor

    def test_each_foot_on_its_own_rest_height(self):
        """a person's planted feet need not stand at the same height (FineDance 001: the left ball 1 cm over the right's
        when both are planted): the rest heights may be per foot"""
        lm = still(3)
        for k in ("ankle_L", "toe_L"):
            lm[k][:, 1] += 0.2                         # the left foot 1.6 cm over the right one, planted
        one = wb.support(lm, dict(self.feet, contact=0.15))
        self.assertFalse(np.any(one["contact"]["L"]))
        feet = dict(self.feet, contact=0.15, ankle_rest_y={"L": 1.7452 + 0.2, "R": 1.7452}, toe_rest_y={"L": 0.3, "R": 0.1})
        two = wb.support(lm, feet)
        self.assertTrue(np.all(two["contact"]["L"]) and np.all(two["part"]["L"] == "flat"))

    def test_pointed_foot_on_its_toe_tip(self):
        """a person's toe landmark is the ball (SMPL's foot joint); a pointed foot (tendu) touches with the toes' tip
        alone: with a tip landmark and a tip template the foot is on the floor there"""
        lm = still(3)
        lm["ankle_L"][:, 1] += 1.0
        lm["toe_L"][:, 1] += 0.6                       # the ball 5 cm up
        lm["tip_L"] = lm["toe_L"].copy()
        lm["tip_L"][:, 2] -= 0.8                       # the tip 6.4 cm ahead,
        lm["tip_L"][:, 1] = 0.111                      # on the floor
        lm["tip_R"] = lm["toe_R"].copy()
        lm["tip_R"][:, 1] = 0.111
        feet = dict(self.feet, tip=np.array([(0.015 * math.cos(a), 0.015 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)[:-1]]),
                    tip_floor_y=0.111)
        sup = wb.support(lm, feet)
        self.assertTrue(np.all(sup["contact"]["L"]))
        self.assertTrue(np.all(sup["part"]["L"] == "tip"))
        poly = wb.foot_polygon(lm, feet, "L", 1, "tip")
        self.assertGreater(wb.polygon_margin(lm["tip_L"][1, [0, 2]] * U, poly), 0.01)
        self.assertLess(wb.polygon_margin(lm["toe_L"][1, [0, 2]] * U, poly), 0.0)
        # without the tip template (Rin: her toe IK is the tip) the same foot is off the floor
        self.assertFalse(np.any(wb.support(lm, self.feet)["contact"]["L"]))

    def test_a_knee_or_a_hand_on_the_floor_supports(self):
        """dances kneel and put a hand down (FineDance has floor work): a knee joint within KNEE_FLOOR_M of the floor or
        a hand (the wrist or the middle finger) within HAND_FLOOR_M is part of the base of support"""
        lm = still(3)
        for k in ("ankle_L", "toe_L"):
            lm[k][:, 1] += 2.0                         # the left foot up
        lm["knee_L"][:, 1] = 0.111 + 0.05 / U          # the left knee down, 5 cm over the floor
        lm["knee_L"][:, 2] = -3.0                      # 24 cm ahead
        lm["mid3_R"][:, 1] = 0.111 + 0.01 / U          # the right hand's fingers on the floor
        lm["mid3_R"][:, 0] = -6.0
        sup = wb.support(lm, self.feet)
        hull = sup["hull"][1]
        self.assertGreater(wb.polygon_margin(lm["knee_L"][1, [0, 2]] * U, hull), 0.0)
        self.assertGreater(wb.polygon_margin(lm["mid3_R"][1, [0, 2]] * U, hull), 0.0)
        self.assertTrue(sup["other"][1])
        lm["knee_L"][:, 1] = 0.111 + 0.20 / U          # 20 cm up: not touching
        lm["mid3_R"][:, 1] = 0.111 + 0.20 / U
        sup = wb.support(lm, self.feet)
        self.assertLess(wb.polygon_margin(lm["knee_L"][1, [0, 2]] * U, sup["hull"][1]), 0.0)
        self.assertFalse(sup["other"][1])

    def test_the_shoes_own_sole(self):
        """Rin's soles as MMD bends them (the feet layer's skinned shoe: its lower shell's points in the world, per frame):
        a foot is on the floor where any of its points is within `contact` of the floor, and the base of support is the
        hull of those points (a foot on its ball with the toes bent up, whose toe IK is off the floor, still stands)"""
        F = 3
        lm = still(F)
        lm["toe_L"][:, 1] += 0.6                      # the toe IK 5 cm up (the toes bent up in MMD)
        u = np.linspace(-0.55, 1.55, 8)
        w = np.linspace(-0.4, 0.4, 3)
        grid = np.array([(1.12 + ww, 0.111, 0.37 - uu) for uu in u for ww in w])      # a flat sole, units
        heel_up = grid.copy()
        heel_up[:, 1] += np.clip((grid[:, 2] - (-0.6)) * 0.5, 0.0, None)               # the heel lifts, the ball and toes stay
        soles = {"L": np.tile(heel_up, (F, 1, 1)), "R": np.tile(grid * np.array([-1.0, 1.0, 1.0]), (F, 1, 1))}
        sup = wb.support(lm, self.feet, soles=soles)
        self.assertTrue(np.all(sup["contact"]["L"]))
        hull = sup["hull"][1]
        ball = np.array([1.12 * U, -0.9 * U])
        self.assertGreater(wb.polygon_margin(ball, hull), 0.0)
        heel = np.array([1.12 * U, 0.8 * U])
        right_heel = np.array([-1.12 * U, 0.8 * U])
        # the left heel is up: the hull's corner there comes from the right heel and the left ball, not the left heel
        self.assertLess(wb.polygon_margin(heel, hull), wb.polygon_margin(right_heel, hull))
        lifted = {"L": soles["L"] + np.array([0.0, 1.0, 0.0]), "R": soles["R"]}
        self.assertFalse(np.any(wb.support(lm, self.feet, soles=lifted)["contact"]["L"]))

    def test_outward_is_away_from_the_body(self):
        """a sole that lies outwards of the foot's line on both feet: the left one's to +x (the model's left), the right
        one's to -x"""
        feet = dict(self.feet, fore=np.array([(-0.02, 0.01), (0.0, 0.01), (0.0, 0.03), (-0.02, 0.03)]))
        lm = still(3)
        for s, sign in (("L", 1.0), ("R", -1.0)):
            poly = wb.foot_polygon(lm, feet, s, 1, "fore")
            toe_x = REST["toe_" + s][0] * U
            self.assertTrue(np.all(sign * (poly[:, 0] - toe_x) > 0.005), s)


class MeasureTest(unittest.TestCase):
    def one_leg(self, F, push=0.0):
        """standing on the right foot (the left 8 cm up), the body over the right forefoot; push: the whole body
        swings sideways x = push sin(2 pi t / 1 s) units"""
        lm = still(F)
        for k in ("ankle_L", "toe_L"):
            lm[k][:, 1] += 1.0
        c = wb.com(wb.segments(lm))[0]
        right = 0.5 * (np.array(REST["ankle_R"]) + np.array(REST["toe_R"]))
        x = (right[0] - c[0]) + push * np.sin(2 * math.pi * np.arange(F) / FPS)
        z = (right[2] - c[2])
        for k in lm:
            if k in ("ankle_R", "toe_R"):
                continue
            lm[k][:, 0] += x
            lm[k][:, 2] += z
        return lm

    def test_quiet_stance_on_one_foot_stays_inside(self):
        rep = wb.measure(self.one_leg(120), wb.RIN_FEET, floor_y=0.111)
        self.assertEqual(rep["zmp"]["outside_runs"], [])
        self.assertGreater(rep["zmp"]["inside_share"], 0.99)

    def test_swinging_on_one_foot_leaves_the_sole_and_says_when(self):
        rep = wb.measure(self.one_leg(120, push=0.6), wb.RIN_FEET, floor_y=0.111)
        runs = rep["zmp"]["outside_runs"]
        self.assertGreater(len(runs), 0)
        r = runs[0]
        self.assertIn("s", r)
        self.assertGreater(r["depth_cm"], 1.0)
        self.assertLess(rep["zmp"]["inside_share"], 0.9)
        json.dumps(rep)                                  # plain JSON

    def test_tilt_counts_the_floors_push(self):
        """a stretch outside the base of support tilts the body by the moment the floor cannot give: its push F_y (per kg)
        times the depth d, over the COM's height h squared, twice summed over the stretch (radians, then degrees).  The same
        COM 4 cm off the standing foot, once still and once pushed up at g / 2 (the body rising), against that sum computed
        here from the motion itself"""
        F = 20
        lm = self.one_leg(F)
        for k in lm:
            if k not in ("ankle_R", "toe_R"):
                lm[k][:, 0] += -1.0                                 # 8 cm sideways: the COM 4 cm off the standing foot
        t = np.arange(F) / FPS
        for a_up in (0.0, G / 2.0):
            body = {k: v.copy() for k, v in lm.items()}
            for k in body:
                if k not in ("ankle_R", "toe_R"):
                    body[k][:, 1] += 0.5 * a_up * t ** 2 / U
            rep, arr = wb.measure(body, wb.RIN_FEET, floor_y=0.111, cutoff_hz=None, arrays=True)
            run = max(rep["zmp"]["outside_runs"], key=lambda r: r["frames"])
            k0, k1 = run["first"], run["last"]
            d = -arr["margin"][k0:k1 + 1]
            h = arr["com"][k0:k1 + 1, 1] - 0.111 * U
            fy = arr["force"][k0:k1 + 1, 1]
            want = math.degrees(np.sum(np.cumsum(fy * d / h ** 2) / FPS) / FPS)
            self.assertAlmostEqual(run["tilt_deg"], want, delta=0.01 + 0.01 * want, msg=str(a_up))
            if a_up:
                # (the push is the weight and the lift of the COM: all but the standing foot and part of its shank rise)
                self.assertTrue(np.all(fy > G + 0.9 * a_up) and np.all(fy < G + a_up + 1e-9))

    def test_air_horizontal_acceleration(self):
        """in the air nothing pushes the body sideways: a hop with the body drifting at a steady speed has no horizontal
        COM acceleration; one that speeds up in the air is counted"""
        F = 60
        t = np.arange(F) / FPS
        base = still(F)
        air = (t >= 0.7) & (t <= 1.3)
        up = np.where(air, 0.5 * G * (t - 0.7) * (1.3 - t) / U, 0.0)       # a 0.6 s hop, 44 cm high at its top
        for drift, want_small in ((lambda tt: 0.5 * tt / U, True), (lambda tt: 1.5 * tt * tt / U, False)):
            lm = {k: v.copy() for k, v in base.items()}
            for k in lm:
                lm[k][:, 1] += up
                lm[k][:, 0] += drift(t)
            rep = wb.measure(lm, wb.RIN_FEET, floor_y=0.111)
            acc = rep["air"]["com_acc_h_m_s2"]["p50"]
            if want_small:
                self.assertLess(acc, 0.1)
            else:
                self.assertGreater(acc, 2.0)

    def test_air_reads_the_air_alone(self):
        """a push off the floor (3.3 m/s^2 sideways for 0.3 s, up to 1 m/s) that ends as the feet leave it: in the air the
        speed stays, and the push on the floor is not counted as an acceleration in the air (a low-pass would spread it
        +-4 frames into the air)"""
        F = 60
        t = np.arange(F) / FPS
        t0, a = 0.7, 1.0 / 0.3
        air = (t >= t0) & (t <= t0 + 0.2)              # a short hop (5 frames in the air), where the spread would show
        lm = still(F)
        up = np.where(air, 0.5 * G * (t - t0) * (t0 + 0.2 - t) / U, 0.0)
        push = np.where(t < t0 - 0.3, 0.0, np.where(t < t0, 0.5 * a * (t - (t0 - 0.3)) ** 2, 0.15 + (t - t0) * 1.0))
        for k in lm:
            lm[k][:, 1] += up
            lm[k][:, 0] += push / U
        rep = wb.measure(lm, wb.RIN_FEET, floor_y=0.111)
        self.assertEqual(rep["air"]["runs"], 1)
        self.assertLess(rep["air"]["stretches"][0]["com_acc_h_m_s2"], 0.05)
        self.assertLess(rep["air"]["stretches"][0]["angmom_change_per_s2"], 0.01)


class FollowTest(unittest.TestCase):
    """how much a body part follows the pelvis's horizontal motion: per frequency band (the power-weighted real part of
    the cross-spectrum over the pelvis's spectrum, Welch) and as one slope (its 6 Hz low-passed horizontal acceleration
    regressed on the pelvis's)"""

    def setUp(self):
        rng = np.random.default_rng(0)
        F = 900
        x = np.cumsum(rng.normal(size=(F, 2)), 0)
        x = wb.lowpass(x - wb.lowpass(x, 0.2), 8.0)                 # a pelvis wandering over 0.2-8 Hz
        self.pel = np.stack([x[:, 0], np.zeros(F), x[:, 1]], 1)
        self.F = F

    def test_rigid_still_and_opposite(self):
        for part, want in ((self.pel, 1.0), (np.zeros((self.F, 3)), 0.0), (-self.pel, -1.0)):
            r = wb.follow_response(part, self.pel)
            for band, v in r.items():
                self.assertAlmostEqual(v, want, places=6, msg=band)
            self.assertAlmostEqual(wb.follow_slope(part, self.pel), want, places=6)

    def test_a_low_pass_follows_slow_and_not_fast(self):
        r = wb.follow_response(wb.lowpass(self.pel, 1.0), self.pel)
        self.assertGreater(r["0.5-1Hz"], 0.6)
        self.assertLess(r["2-4Hz"], 0.1)
        self.assertLess(wb.follow_slope(wb.lowpass(self.pel, 1.0), self.pel), 0.2)


class MeasureFollowTest(unittest.TestCase):
    def test_measure_reports_how_the_parts_follow_the_pelvis(self):
        """with a pelvis landmark (people: the skeleton's pelvis joint; Rin: 下半身's origin) the report has, per part
        (the head, the chest = the upper trunk, the belly = the middle trunk, the arms, the whole COM), its response per
        band and its slope; a body swaying as one rigid piece follows by 1 everywhere"""
        F = 240
        t = np.arange(F) / FPS
        lm = still(F)
        x = 0.4 * np.sin(2 * math.pi * 3.0 * t) + 0.6 * np.sin(2 * math.pi * 0.7 * t)
        for k in lm:
            lm[k][:, 0] += x
        lm["pelvis"] = np.tile(np.array([0.0, 12.2248, -0.6493]), (F, 1))
        lm["pelvis"][:, 0] += x
        rep = wb.measure(lm, wb.RIN_FEET, floor_y=0.111)
        f = rep["follow"]
        for part in ("head", "chest", "belly", "arms", "com"):
            self.assertAlmostEqual(f[part]["slope"], 1.0, places=3, msg=part)
            self.assertAlmostEqual(f[part]["2-4Hz"], 1.0, places=3, msg=part)
        self.assertNotIn("follow", wb.measure(still(F), wb.RIN_FEET, floor_y=0.111))


class LandmarksTest(unittest.TestCase):
    def test_from_body_and_from_a_pack_agree(self):
        """the landmarks from the layer's body (FK of a VMD) and from an analysis pack's 26 bones are the same points"""
        motion = dance(left_lifts=[(20, 30, 40, 50, 2.0)], arms=True)
        body = balance_layer.Body(MODEL, motion)
        a = wb.landmarks_from_body(body)
        names = wb.PACK_BONES
        pos = np.stack([body.p(n) if body.has(n) else np.zeros((body.F, 3)) for n in names], 1)
        rot = np.stack([body.q(n) if body.has(n) else np.tile([0.0, 0.0, 0.0, 1.0], (body.F, 1)) for n in names], 1)
        b = wb.landmarks_from_pack(names, pos, rot, wb.rin_rest(MODEL))
        for k in a[0]:
            np.testing.assert_allclose(a[0][k], b[0][k], atol=1e-6, err_msg=k)
        for k in a[1]:
            np.testing.assert_allclose(a[1][k], b[1][k], atol=1e-9, err_msg=k)

    def test_body_com_close_to_the_layers(self):
        body = balance_layer.Body(MODEL, dance())
        lm, _ = wb.landmarks_from_body(body)
        c = wb.com(wb.segments(lm))
        # the layer puts the head's and the hands' far ends a little differently: within 5 mm on the floor
        np.testing.assert_allclose(c[:, [0, 2]], body.com()[:, [0, 2]], atol=0.5 / 8.0)


class CommandTest(unittest.TestCase):
    def test_measure_a_motion(self):
        tmp = tempfile.mkdtemp()
        try:
            dpath = os.path.join(tmp, "d.vmd")
            mpath = os.path.join(tmp, "m.pmx")
            rpath = os.path.join(tmp, "r.json")
            with open(dpath, "wb") as f:
                f.write(vmd.dumps(dance(left_lifts=[(20, 30, 60, 70, 2.0)])))
            with open(mpath, "wb") as f:
                f.write(model_bytes())
            rc = wb.main(["measure", dpath, mpath, "--report", rpath])
            self.assertEqual(rc, 0)
            with open(rpath, encoding="utf-8") as f:
                rep = json.load(f)
            for k in ("zmp", "com", "angmom", "air", "support", "params"):
                self.assertIn(k, rep)
        finally:
            shutil.rmtree(tmp)

    def test_measure_a_pack_as_the_motion(self):
        """an analysis pack (meta.json's bone names, bones_final.npz's pos and rot) measures as its motion does"""
        tmp = tempfile.mkdtemp()
        try:
            motion = dance(left_lifts=[(20, 30, 60, 70, 2.0)], arms=True)
            dpath, mpath = os.path.join(tmp, "d.vmd"), os.path.join(tmp, "m.pmx")
            with open(dpath, "wb") as f:
                f.write(vmd.dumps(motion))
            with open(mpath, "wb") as f:
                f.write(model_bytes())
            body = balance_layer.Body(MODEL, motion)
            names = wb.PACK_BONES
            pos = np.stack([body.p(n) if body.has(n) else np.zeros((body.F, 3)) for n in names], 1).astype(np.float32)
            rot = np.stack([body.q(n) if body.has(n) else np.tile([0.0, 0.0, 0.0, 1.0], (body.F, 1)) for n in names], 1).astype(np.float32)
            pack = os.path.join(tmp, "pack")
            os.makedirs(pack)
            with open(os.path.join(pack, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"bones": names}, f, ensure_ascii=False)
            np.savez_compressed(os.path.join(pack, "bones_final.npz"), pos=pos, rot=rot)
            r1, r2 = os.path.join(tmp, "r1.json"), os.path.join(tmp, "r2.json")
            self.assertEqual(wb.main(["measure", dpath, mpath, "--report", r1]), 0)
            self.assertEqual(wb.main(["measure-pack", pack, mpath, "--report", r2]), 0)
            with open(r1, encoding="utf-8") as f:
                a = json.load(f)
            with open(r2, encoding="utf-8") as f:
                b = json.load(f)
            self.assertAlmostEqual(a["zmp"]["inside_share"], b["zmp"]["inside_share"], places=3)
            self.assertAlmostEqual(a["com"]["height_m_p50"], b["com"]["height_m_p50"], places=4)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
