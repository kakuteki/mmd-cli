"""Put the dancer's weight on the standing foot: while one foot is off the floor, センター carries the body over the other
foot, starting before the foot lifts (an anticipatory weight shift), and a foot that lands and takes the weight bends
its knee.  The feet's IK keys are not touched (the feet stay where they were traced).

    python tools/balance_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--arrays a.npz] [--r-bal 0.6]
                                  [--acc-max 1.0] [--lead 0.15] [--lag 0.05] [--drop-max 2.0] [--dip-deg 15] [--no-dip]

Why (the analysis a05 of 2026-10-07, REPORT 4.1): the traced dance keeps the body between the feet while one foot is up;
the centre of mass (COM) is 10.8 cm (v7: 11.3) from the standing foot's centre, sideways.  People standing on one foot
keep the centre of pressure, the COM's mean floor point, 3 mm inside the foot's long axis (sway SD 6 mm; Haba & Iwatsuki
2023, Janura et al. 2019).  The body hangs between the feet like a puppet.  And a foot that lands does not bend its knee.

How:
1. The body (Body): forward kinematics of the bones (tools/motor_layer.py's numpy FK, mmd_cli.fk's rule), the COM by the
   segment masses of de Leva 1996 Table 4, females (head VERT-CERV, trunk in three parts, arm, forearm, hand WJC-DAC3,
   thigh, shank KJC-AJC, foot HEEL-TTIP; 99.99 % of the body), the legs as two bones (thigh and shank from the model's
   rest lengths) solved to the foot IK's target (the knee bends towards 下半身's front, turned out towards the foot's
   front as far as the foot lies flat and points that way; a target out of reach is met by a straight leg pointing at
   it).  A foot supports while its lowest point (the ankle or the toe over its rest height) is under SUPPORT_H (1.6 cm,
   a05's FLY).
2. The target: in single support (one foot supports, the other not) the COM's floor point in a band of --r-bal about the
   standing sole's line (heel to toe).  The pull's weight grows with the other foot's height (from 1.6 to CLEAR_CM),
   ramps up over --lead before that foot lifts and down over --lag after it lands.  How far a run is pulled depends on
   its length T (need_share): on the linear inverted pendulum a COM at rest an offset e outside the foot drifts
   e (cosh(w T) - 1) (w = sqrt(g / COM height), 1/w = 0.29 s for Rin): a 0.2 s step drifts 0.23 e and the next foot
   catches it, from about 0.4 s on the body would fall, so the run is pulled min(1, cosh(w T) - 1) of the way.
3. The shift y (センター's move on the floor, every frame) minimizes
       sum w |k y - d|^2 + lam |y|^2 + mu |y'''|^2
   (d: the COM's way to the band times the run's share; k: how far the COM follows センター, measured on the body with
   the knees re-solved, about 0.85; lam LAM_IN where the pull is, LAM_OUT elsewhere, so a brief step's lean stays short;
   mu: a minimum-jerk smoothness of TAU, Flash & Hogan 1985) subject to
     (a) |y''| <= --acc-max.  The body moves its COM by moving its centre of pressure (the linear inverted pendulum:
         x'' = (g / height) (x - p)); 1 m/s^2 needs it about 9 cm off.  People shifting the weight to lift a leg push
         it 3.8-6.3 cm towards the lifting leg and start 0.32-0.44 s (lifting a leg) to about 0.6 s (a step) before
         the foot leaves, and are still about 2 cm short of the standing foot when it does (Hussein et al. 2013,
         Mouchnino & Blouin 2013); dancers get there in one go (Mouchnino et al. 1992).
     (b) every foot IK's target within its leg's reach after the hips move (or no farther than it already was), the
         hips allowed down for it: a leg at its reach stays straight (the hip goes round the ankle), so the drop for one
         leg is bounded by what bends the other leg, if it is on the floor, KNEE_GIVE_DEG more (at most --drop-max).
     (c) each hip's adduction (the hip-to-ankle line out of 下半身's sagittal plane) under the reference range's upper
         proposal (22 degrees; stage 3 research: the Japanese reference 20) and its abduction under 45, or no farther
         than in the dance.
     (d) never pointing away from the nearest pull: a minimum-jerk smoother rings about 5 % before and after a step;
         people do not move the COM the wrong way before a weight shift (the centre of pressure goes that way, not
         the COM).
   Solved by ADMM (Boyd et al. 2011): one banded solve per round with a fixed matrix, the bounds projected per frame
   (Dykstra's projection for the intersection).  Moving センター translates the trunk and the head without turning them:
   the dancers' "translation strategy in the pelvis" (Krasnow et al. 2011; the trunk kept vertical, Mouchnino et al.
   1991), against the naive "inclination strategy".
4. The hips then go down as far as the legs need to reach (the least smooth drop: the same solver, |y''| <= DROP_ACC_MAX).
5. Landings (--dip-deg, --no-dip): a foot that lands after a swing (a05: off the floor 4 frames, up 1.6 cm) and then
   takes the weight (the other foot lifts within DIP_WINDOW, or was already up) bends its knee by --dip-deg by DIP_PEAK
   and comes back by DIP_END (walking: 1-3 degrees at contact, 17 at 0.13 s; Winter 2009 Table A.1, a woman of 156 cm):
   the hips go down by what the two-bone leg needs for that bend, at most DIP_MAX_CM, only as far as the dance does not
   already bend the knee there (measured on the body already moved and dropped by 4., so the two add up).  A tap (the
   foot lands and lifts again while the other stays down) is left alone.

Written: センター only, a key on every frame (linear), its rotation as the dance had it.  Every other bone, every morph and
the rest of the file are the dance's own bytes; when nothing is to be done the dance comes back unchanged.

Report (--report; in short on stdout): a05_lateral_cm (the analysis's measure: in single support with the other foot
5 cm up and the standing foot on the floor, the COM's sideways distance from the standing foot's centre along 下半身's
side axis, + towards the lifted foot, before and after; after_holds: in single-support runs of 0.5 s and more), runs
(each single-support run: when, which foot, how high the other, its need_share, the distance to the sole's line before
and after and the intended one, how far short and why: reach, hip range or acceleration), centre (the shift, its 1-frame
step, the added accelerations and the pressure move they need, the drop and the dip), apa (how much of the shift is done
when the foot lifts, and when it starts), reach (frames whose IK target is out of the leg's reach, before and after),
knee (flexion on the floor, before and after), hip (adduction against the reference range, before and after), landings
(the knee's bend within 0.13 s after a landing, before and after), untouched (the other bones' bytes), solver.
--arrays writes the per-frame curves (the shift, the COM before and after, the pull, the drop, the dip, the knees, ...).
"""
import argparse
import importlib.util
import io
import json
import math
import os
import sys
import time
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_balance_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _tool("motor_layer")

FPS = 30.0
DT = 1.0 / FPS
UNIT_M = 0.08                   # one model unit is 8 cm (the analysis pack)
CM = 8.0                        # cm per unit
G = 9.81
SIDES = ("左", "右")
CENTRE = "センター"

# ---- what supports, what pulls ----------------------------------------------------------------------------------
SUPPORT_H = 0.2                 # units (1.6 cm, a05's FLY): a foot this low carries weight
CONTACT_EPS = 0.05              # units (4 mm, a05): a foot on the floor (the a05 measure, the landings)
CLEAR_CM = 5.0                  # the other foot this high: the full pull (a05's single support: 5 cm)
R_BAL_CM = 0.6                  # the band about the standing sole's line: people standing on one foot keep the centre of
                                # pressure -0.32 +- 0.55 cm from the foot's long axis (Haba & Iwatsuki 2023, Table 1; sway
                                # SD 0.6 cm, Janura et al. 2019).  On the MV the band's width is what moves the held
                                # stances most (1.5 cm: median 3.3 cm left in runs of 0.5 s and more, 0.5 cm: 2.6)
LEAD_S = 0.15                   # the pull ramps up this long before the foot lifts
LAG_S = 0.05                    # and down this long after it lands
TRANSFER_V = 0.2                # m/s: a run whose COM moves this fast towards where the other foot lands, its XcoM past
                                # half the way there, is a step onto that foot and is not pulled (the review's criterion)
# ---- the shift ---------------------------------------------------------------------------------------------------
ACC_MAX = 1.0                   # m/s^2 of added COM acceleration (about 9 cm of centre-of-pressure move)
TAU_S = 0.1                     # the minimum-jerk smoothness's time scale
LAM_IN = 0.02                   # the pull back to the dance where the pull is (relative to a full pull)
LAM_OUT = 0.5                   # and elsewhere: keeps a brief step's lean short (it does not start a second early)
DROP_MAX_CM = 2.0               # the hips may go down this far for the legs to reach
DROP_ACC_MAX = 0.5              # m/s^2: the drop's own acceleration (a slow give of the knees)
REACH_TOL_CM = 0.3              # a leg keeps this much slack (the IK's last few mm)
ADMM_ITERS = 800
ADMM_TOL_ACC = 0.02             # m/s^2
ADMM_TOL_REACH = 0.05           # cm
SET_MARGIN = 0.001              # m: the bounds are solved this much tighter, so the converged curve is inside the true ones
FIX_HALF = 9                    # frames: the half-width of the smooth cover that brings an unconverged curve inside
KEPT_MIN = 0.02                 # a foot carried 98 % and more: its leg sets no bound on the shift
FREE_M = 1.0e3                  # m: the radius (or slab side) of a bound that does not bound
CARRY_HALF = 6                  # frames: the half-width of the carry's smoothing (it changes over about 0.4 s)
# ---- the landings ------------------------------------------------------------------------------------------------
DIP_DEG = 15.0                  # the knee's extra bend on a landing that takes the weight (walking: 1-3 -> 17 degrees,
DIP_PEAK_S = 0.13               # at 0.129 s after contact; Winter 2009 Table A.1, a woman of 156 cm, research C1)
DIP_END_S = 0.4
DIP_MAX_CM = 2.0                # (2 cm in 0.13 s: the hips accelerate at most about 6 m/s^2)
DIP_WINDOW_S = 0.3              # the other foot lifts within this after the landing: the landing takes the weight
GAP = 4                         # a05's swing: at least 4 frames off the floor...
SWING_MIN_H = 0.2               # ...in which the foot rose at least 1.6 cm
# ---- the reference ranges (stage 3 research, the Japanese reference ROM 1995 / 2022 and the upper proposal) -----
HIP_ADDUCTION_DEG = (20.0, 22.0)
HIP_ABDUCTION_DEG = 45.0
KNEE_FLEXION_DEG = (130.0, 159.0)
KNEE_GIVE_DEG = 12.0            # the reach's drop bends a leg on the floor by at most this much more

# de Leva P (1996) J Biomech 29:1223-1230, Table 4, females: mass %, CM % from the first end (read in the original:
# _spike/out/stage2/motor/work/deleva1996_table4_text.txt; the head, upper trunk, middle trunk, arm rows are the ones of
# tools/motor_layer.py's DE_LEVA_F)
SEGMENTS = {"head": (6.68, 48.41), "upper_trunk": (15.45, 50.50), "middle_trunk": (14.65, 45.12),
            "lower_trunk": (12.47, 49.20), "upper_arm": (2.55, 57.54), "forearm": (1.38, 45.59), "hand": (0.56, 34.27),
            "thigh": (14.78, 36.12), "shank": (4.81, 43.52), "foot": (1.29, 40.14)}
HEEL_BACK = 0.3                 # the heel this share of the ankle-to-toe line behind the ankle (a05)

REQUIRED = [CENTRE, "下半身", "上半身", "上半身2", "首", "頭"] + [s + n for s in SIDES for n in (
    "腕", "ひじ", "手首", "足", "ひざ", "足首", "足ＩＫ", "つま先ＩＫ")]
OPTIONAL = ["頭先", "左中指先", "右中指先", "左中指３", "右中指３", "左中指２", "右中指２", "グルーブ", "腰"]


def params_default():
    return {"r_bal_cm": R_BAL_CM, "acc_max": ACC_MAX, "lead_s": LEAD_S, "lag_s": LAG_S, "drop_max_cm": DROP_MAX_CM,
            "dip_deg": DIP_DEG, "dip": True, "tau_s": TAU_S, "lam_in": LAM_IN, "lam_out": LAM_OUT, "clear_cm": CLEAR_CM}


# ---- the body ---------------------------------------------------------------------------------------------------

class Body:
    """the bones' world positions over the frames of `motion` (FK), the COM, the legs solved as two bones; moved(shift)
    gives the same body with everything under センター moved by shift [F, 3] (units, world)"""

    def __init__(self, model, motion, frames=None):
        sk = M.Skeleton(model)
        missing = [n for n in REQUIRED if not sk.has(n)]
        if missing:
            raise ValueError("the model has no %s: the layer needs the trunk, the arms and the legs with their foot IK"
                             % ", ".join(missing))
        self.sk = sk
        self.F = (fk.last_frame(motion) + 1) if frames is None else frames
        names = REQUIRED + [n for n in OPTIONAL if sk.has(n)]
        order = sk.closure([sk.i(n) for n in names])
        keys = M.sample_keys(motion, sk, order, self.F)
        wpos, wrot = M.fk_all(sk, keys, order, self.F)
        self._pos = {sk.bones[k].name: wpos[k] for k in order}
        self._rot = {sk.bones[k].name: wrot[k] for k in order}
        self.order_names = [sk.bones[k].name for k in order]
        centre = sk.i(CENTRE)
        self.under = set()
        for k in order:
            a = k
            while a is not None:
                if a == centre:
                    self.under.add(sk.bones[k].name)
                    break
                a = sk.parent(a)
        self.shift = np.zeros((self.F, 3))
        self.carry = None                               # side -> [F]: how much of the floor shift its foot IK takes
        self.below_ik = {}
        for s in SIDES:
            ik = sk.i(s + "足ＩＫ")
            self.below_ik[s] = set()
            for k in order:
                a = k
                while a is not None:
                    if a == ik:
                        self.below_ik[s].add(sk.bones[k].name)
                        break
                    a = sk.parent(a)
        self.rest = {n: sk.rest[sk.i(n)] for n in names}
        self._legs = {}
        self.legs_rest = {}
        for s in SIDES:
            h, k, a = (self.rest[s + n] for n in ("足", "ひざ", "足首"))
            self.legs_rest[s] = (float(np.linalg.norm(k - h)), float(np.linalg.norm(a - k)))
        self.ankle_rest_y = {s: float(self.rest[s + "足ＩＫ"][1]) for s in SIDES}
        self.toe_rest_y = {s: float(self.rest[s + "つま先ＩＫ"][1]) for s in SIDES}

    def moved(self, shift, carry=None):
        """the body with everything under センター moved by shift [F, 3] (units, world) and each foot IK (with what hangs
        on it) moved by carry[side] [F] times the shift's floor part"""
        other = object.__new__(Body)
        other.__dict__.update(self.__dict__)
        other.shift = np.asarray(shift, dtype=np.float64)
        other.carry = carry
        other._legs = {}
        return other

    def has(self, name):
        return name in self._pos

    def p(self, name):
        if name in self.under:
            return self._pos[name] + self.shift
        if self.carry is not None:
            for s, names in self.below_ik.items():
                if name in names and s in self.carry:
                    floor = self.shift.copy()
                    floor[:, 1] = 0.0
                    return self._pos[name] + self.carry[s][:, None] * floor
        return self._pos[name]

    def q(self, name):
        return self._rot[name]

    # the legs
    def hip(self, s):
        return self.p(s + "足")

    def ankle(self, s):
        """the foot IK's target"""
        return self.p(s + "足ＩＫ")

    def toe(self, s):
        return self.p(s + "つま先ＩＫ")

    def leg_length(self, s):
        return sum(self.legs_rest[s])

    def _leg(self, s):
        if s in self._legs:
            return self._legs[s]
        L1, L2 = self.legs_rest[s]
        H, A, T = self.hip(s), self.ankle(s), self.toe(s)
        d = A - H
        dist = np.linalg.norm(d, axis=1)
        u = d / np.maximum(dist, 1e-9)[:, None]
        dd = np.minimum(dist, L1 + L2 - 1e-9)
        a = (L1 ** 2 - L2 ** 2 + dd ** 2) / (2.0 * dd)
        h = np.sqrt(np.maximum(L1 ** 2 - a ** 2, 0.0))
        # the knee is a hinge about 下半身's side axis (MMD's IK turns the thigh from the rest pose, knee forward): it
        # bends towards side x (hip -> ankle), forward for a standing leg, up for a leg kicked forward, down for one
        # lifted behind; turned out towards the foot's front as far as the foot lies flat and points the pelvis's way
        # (a pointed foot does not steer it); a little of the pelvis's front keeps it defined for a leg straight out to
        # the side.  So its side never flips from one frame to the next.
        facing = self.facing()
        side = M.qrot(self.q("下半身"), np.broadcast_to(np.array([1.0, 0.0, 0.0]), (self.F, 3)))
        hinge = np.cross(side, u)
        foot = T - A
        flat = np.hypot(foot[:, 0], foot[:, 2]) / np.maximum(np.linalg.norm(foot, axis=1), 1e-9)
        foot[:, 1] = 0.0
        foot /= np.maximum(np.linalg.norm(foot, axis=1), 1e-9)[:, None]
        agree = np.maximum(np.sum(foot * facing, axis=1), 0.0)
        fwd = hinge + (flat * agree)[:, None] * foot + 0.1 * facing
        n = fwd - np.sum(fwd * u, axis=1)[:, None] * u
        n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
        knee = H + a[:, None] * u + h[:, None] * n
        reached = H + u * np.minimum(dist, L1 + L2)[:, None]
        cosk = np.clip((L1 ** 2 + L2 ** 2 - dd ** 2) / (2.0 * L1 * L2), -1.0, 1.0)
        flex = 180.0 - np.degrees(np.arccos(cosk))
        self._legs[s] = (knee, reached, T + (reached - A), flex, dist)
        return self._legs[s]

    def knee(self, s):
        return self._leg(s)[0]

    def ankle_reached(self, s):
        return self._leg(s)[1]

    def knee_flexion(self, s):
        """degrees, 0 = straight, from the hip-to-ankle distance (law of cosines; a straight leg past its reach is 0)"""
        return self._leg(s)[3]

    def reach(self, s):
        """the hip-to-target distance (units)"""
        return self._leg(s)[4]

    def facing(self):
        """下半身's front on the floor (unit, [F, 3], y 0)"""
        f = M.qrot(self.q("下半身"), np.broadcast_to(np.array([0.0, 0.0, -1.0]), (self.F, 3))).copy()
        f[:, 1] = 0.0
        return f / np.maximum(np.linalg.norm(f, axis=1), 1e-9)[:, None]

    def height(self, s):
        """the foot's lowest point over its rest height (units): the ankle (foot IK) or the toe (toe IK)"""
        return np.minimum(self.ankle(s)[:, 1] - self.ankle_rest_y[s], self.toe(s)[:, 1] - self.toe_rest_y[s])

    def sole(self, s):
        """(heel, toe) of the foot on the floor plane, [F, 2] each (x, z)"""
        A, T = self.ankle(s)[:, [0, 2]], self.toe(s)[:, [0, 2]]
        return A - HEEL_BACK * (T - A), T

    def _hand_tip(self, s):
        if self.has(s + "中指先"):
            return self.p(s + "中指先")
        if self.has(s + "中指３") and self.has(s + "中指２"):
            return self.p(s + "中指３") + 0.8 * (self.p(s + "中指３") - self.p(s + "中指２"))
        if self.has(s + "中指３"):
            return self.p(s + "中指３")
        return self.p(s + "手首") + M.HAND_FALLBACK * (self.p(s + "手首") - self.p(s + "ひじ"))

    def _vertex(self):
        if self.has("頭先"):
            return self.p("頭先")
        up = np.array([0.0, self.rest["頭"][1] * M.HEAD_TIP_FALLBACK, 0.0])
        return self.p("頭") + M.qrot(self.q("頭"), np.broadcast_to(up, (self.F, 3)))

    def com(self):
        """the centre of mass [F, 3] (units)"""
        P = self.p
        hipm = 0.5 * (self.hip("左") + self.hip("右"))
        cerv, xyph, omph, vert = P("首"), P("上半身2"), P("上半身"), self._vertex()

        def at(row, a, b):
            share, pct = SEGMENTS[row]
            return share, a + (pct / 100.0) * (b - a)
        parts = [at("head", vert, cerv), at("upper_trunk", cerv, xyph), at("middle_trunk", xyph, omph),
                 at("lower_trunk", omph, hipm)]
        for s in SIDES:
            parts += [at("upper_arm", P(s + "腕"), P(s + "ひじ")), at("forearm", P(s + "ひじ"), P(s + "手首")),
                      at("hand", P(s + "手首"), self._hand_tip(s))]
            knee, ankle, toe = self.knee(s), self.ankle_reached(s), self._leg(s)[2]
            heel = ankle - HEEL_BACK * (toe - ankle)
            parts += [at("thigh", self.hip(s), knee), at("shank", knee, ankle), at("foot", heel, toe)]
        total = sum(w for w, _ in parts)
        return sum(w * p for w, p in parts) / total

    def medial(self, s):
        """the unit vector from leg s towards the other, in 下半身's frame [F, 3]"""
        side = M.qrot(self.q("下半身"), np.broadcast_to(np.array([1.0, 0.0, 0.0]), (self.F, 3)))
        return -side if s == "左" else side             # the model's left is +X

    def hip_adduction(self, s):
        """degrees: the thigh's angle out of 下半身's sagittal plane, + towards the other leg (adduction)"""
        medial = self.medial(s)
        thigh = self.knee(s) - self.hip(s)
        thigh /= np.maximum(np.linalg.norm(thigh, axis=1), 1e-9)[:, None]
        return np.degrees(np.arcsin(np.clip(np.sum(thigh * medial, axis=1), -1.0, 1.0)))


# ---- small helpers ----------------------------------------------------------------------------------------------

def runs(mask):
    """[(first, last)] of the runs of True"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    dm = np.diff(m.astype(np.int8))
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(dm == 1), np.flatnonzero(dm == -1) - 1)]


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def q_stats(v, qs=(0.5, 0.9, 0.99)):
    v = np.asarray(v, dtype=np.float64)
    if not len(v):
        return None
    out = {("p%02d" % int(round(q * 100)) if q < 1 else "max"): round(float(np.quantile(v, q)), 3) for q in qs}
    out["max"] = round(float(v.max()), 3)
    return out


# ---- the banded solve -------------------------------------------------------------------------------------------

def band_terms(F, diag, stencils):
    """the lower bands B[k][i] = A[i, i-k] of A = diag(diag) + sum over (weights per row, stencil) of D^T W D"""
    p = max(len(s) for _, s in stencils) - 1
    B = [np.zeros(F) for _ in range(p + 1)]
    B[0] += diag
    for wrow, s in stencils:
        m = len(s)
        R = F - m + 1
        wrow = np.broadcast_to(np.asarray(wrow, dtype=np.float64), (R,))
        for u in range(m):
            for v in range(u + 1):
                B[u - v][u:u + R] += wrow * s[u] * s[v]
    return B


def band_factor(B):
    """the Cholesky factor of a banded symmetric positive definite matrix, in the same band layout"""
    p = len(B) - 1
    n = len(B[0])
    A = [b.tolist() for b in B]
    L = [[0.0] * n for _ in range(p + 1)]
    for i in range(n):
        for k in range(min(p, i), 0, -1):
            j = i - k
            s = A[k][i]
            for m in range(max(0, i - p), j):
                s -= L[i - m][i] * L[j - m][j]
            L[k][i] = s / L[0][j]
        s = A[0][i]
        for k in range(1, min(p, i) + 1):
            s -= L[k][i] * L[k][i]
        if s <= 0.0:
            raise ValueError("the shift's system is not positive definite (row %d)" % i)
        L[0][i] = math.sqrt(s)
    return L


def band_solve(L, rhs):
    p = len(L) - 1
    n = len(L[0])
    out = np.zeros_like(rhs, dtype=np.float64)
    L0 = L[0]
    for c in range(rhs.shape[1]):
        b = rhs[:, c].tolist()
        y = [0.0] * n
        for i in range(n):
            s = b[i]
            for k in range(1, min(p, i) + 1):
                s -= L[k][i] * y[i - k]
            y[i] = s / L0[i]
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            s = y[i]
            for k in range(1, min(p, n - 1 - i) + 1):
                s -= L[k][i + k] * x[i + k]
            x[i] = s / L0[i]
        out[:, c] = x
    return out


D2_STENCIL = (1.0, -2.0, 1.0)
D3_STENCIL = (-1.0, 3.0, -3.0, 1.0)


def d2(x):
    return x[2:] - 2.0 * x[1:-1] + x[:-2]


def d2t(y, F):
    out = np.zeros((F,) + y.shape[1:])
    out[:-2] += y
    out[1:-1] -= 2.0 * y
    out[2:] += y
    return out


def proj_disc(x, c, r):
    dv = x - c
    n = np.linalg.norm(dv, axis=1)
    out = x.copy()
    m = n > r
    out[m] = c[m] + dv[m] * (r[m] / np.maximum(n[m], 1e-15))[:, None]
    return out


def proj_half(x, u):
    """onto x . u >= 0 (per frame; rows of u that are 0 do not constrain)"""
    s = np.sum(x * u, axis=1)
    out = x.copy()
    m = s < 0
    out[m] = x[m] - s[m, None] * u[m]
    return out


def toward_targets(d, reach_frames):
    """per frame, the unit direction of the nearest pull target (by time, within reach_frames; 0 beyond): the shift
    may not point away from it (no swing the wrong way before a weight shift, no overshoot past the dance after it)"""
    F = len(d)
    n = np.linalg.norm(d, axis=1)
    has = np.flatnonzero(n > 1e-4)
    out = np.zeros((F, 2))
    if not len(has):
        return out
    idx = np.searchsorted(has, np.arange(F))
    left = has[np.clip(idx - 1, 0, len(has) - 1)]
    right = has[np.clip(idx, 0, len(has) - 1)]
    t = np.arange(F)
    near = np.where(np.abs(t - left) <= np.abs(right - t), left, right)
    ok = np.abs(near - t) <= reach_frames
    out[ok] = d[near[ok]] / n[near[ok], None]
    return out


def admm(w, d, lam, project, acc_max, tau_s, iters=ADMM_ITERS, tol_x_cm=ADMM_TOL_REACH, gain=None):
    """x [F, n] (metres): min 1/2 sum w |g x - d|^2 + 1/2 sum lam |x|^2 + mu/2 |x'''|^2 subject to |x''| <= acc_max (per
    frame) and x = project(x) (a per-frame set, given by its projection); g = gain per frame (1).  ADMM (Boyd et al.
    2011, over-relaxed 1.6) on the splitting [x'' ; x] = [za ; zx]: the x-step is one banded solve with a fixed
    matrix."""
    F, n = d.shape
    lam = np.broadcast_to(np.asarray(lam, dtype=np.float64), (F,))
    g = np.ones(F) if gain is None else np.asarray(gain, dtype=np.float64)
    tf = tau_s * FPS
    scale = 1.0 + float(np.median(lam))
    mu = scale * tf ** 6
    rho = 1.0                                           # both blocks' penalties scale together (residual balancing)

    def factor(r):
        return band_factor(band_terms(F, w * g * g + lam + r * scale, [(mu, D3_STENCIL), (r * scale * tf ** 4, D2_STENCIL)]))
    L = factor(rho)
    amax = acc_max * DT * DT
    q = (w * g)[:, None] * d
    za = np.zeros((F - 2, n))
    ua = np.zeros_like(za)
    zx = project(np.zeros((F, n)))
    ux = np.zeros_like(zx)
    alpha = 1.6
    res_a = res_x = None
    it = 0
    x = zx
    zx_seen = zx
    rescaled = 0
    for it in range(1, iters + 1):
        rho_a, rho_x = rho * scale * tf ** 4, rho * scale
        x = band_solve(L, q + rho_a * d2t(za - ua, F) + rho_x * (zx - ux))
        ax = d2(x)
        ah = alpha * ax + (1.0 - alpha) * za
        va = ah + ua
        na = np.linalg.norm(va, axis=1)
        za = va * np.minimum(1.0, amax / np.maximum(na, 1e-18))[:, None]
        ua = va - za
        xh = alpha * x + (1.0 - alpha) * zx
        zx = project(xh + ux)
        ux = xh + ux - zx
        if it % 10 == 0:
            res_a = float(np.linalg.norm(ax - za, axis=1).max()) / (DT * DT)
            res_x = float(np.linalg.norm(x - zx, axis=1).max()) * 100.0
            if res_a < ADMM_TOL_ACC and res_x < tol_x_cm:
                break
        if it % 50 == 0:
            # residual balancing (Boyd et al. 2011, 3.4.1): the constraints' miss against how much z still moves
            r = float(np.linalg.norm(x - zx))
            s = float(np.linalg.norm(zx - zx_seen)) / 50.0
            zx_seen = zx
            k = 2.0 if r > 10.0 * s else (0.5 if s > 10.0 * r else 1.0)
            if k != 1.0 and rescaled < 12:
                rho *= k
                ua /= k
                ux /= k
                L = factor(rho)
                rescaled += 1
    # x itself (the banded solve's smooth curve), not its per-frame projection: putting each frame back into its set on
    # its own folds the curve where a bound starts to act (the review: 59.23 s, 3.57 m/s^2).  The callers solve with
    # bounds tightened by SET_MARGIN and bring x into the true bounds by a smooth cover (smooth_cover)
    info = {"iterations": it, "residual_acc_m_s2": None if res_a is None else round(res_a, 4),
            "residual_set_cm": None if res_x is None else round(res_x, 4), "rho": rho}
    return x, info


def smooth_cover(v, half):
    """a smooth curve never under v >= 0 (per frame): the running maximum over +-half frames, averaged by a raised
    cosine of the same half-width (each frame's average reads only maxima of windows that hold the frame itself)"""
    v = np.asarray(v, dtype=np.float64)
    F = len(v)
    if F == 0 or not np.any(v > 0):
        return np.zeros(F)
    pad = np.concatenate([np.full(half, v[0]), v, np.full(half, v[-1])])
    m = np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1).max(axis=1)
    k = 0.5 * (1.0 + np.cos(math.pi * np.arange(-half, half + 1) / (half + 1.0)))
    k /= k.sum()
    mp = np.concatenate([np.full(half, m[0]), m, np.full(half, m[-1])])
    return np.convolve(mp, k, mode="valid")


def disc_scale(x, c, r):
    """per frame, the largest a in [0, 1] with |a x - c| <= r (the disc holds 0)"""
    out = np.ones(len(x))
    out_m = np.linalg.norm(x - c, axis=1) > r
    if not out_m.any():
        return out
    xx = np.sum(x * x, axis=1)
    xc = np.sum(x * c, axis=1)
    cc = np.sum(c * c, axis=1) - r * r
    root = (xc + np.sqrt(np.maximum(xc * xc - xx * cc, 0.0))) / np.maximum(xx, 1e-30)
    out[out_m] = np.where(cc[out_m] > 0.0, 0.0, np.clip(root[out_m], 0.0, 1.0))
    return out


def slab_scale(x, m, lo, hi):
    """per frame, the largest a in [0, 1] with lo <= a x . m <= hi (lo <= 0 <= hi)"""
    s = np.sum(x * m, axis=1)
    out = np.ones(len(x))
    up, down = s > hi, s < lo
    out[up] = np.clip(np.maximum(hi[up], 0.0) / s[up], 0.0, 1.0)
    out[down] = np.clip(np.minimum(lo[down], 0.0) / s[down], 0.0, 1.0)
    return out


def proj_slab(x, m, lo, hi):
    """onto lo <= x . m <= hi (per frame; m need not be a unit vector)"""
    mm = np.maximum(np.sum(m * m, axis=1), 1e-18)
    s = np.sum(x * m, axis=1)
    over = np.maximum(s - hi, 0.0) - np.maximum(lo - s, 0.0)
    return x - (over / mm)[:, None] * m


def solve_shift(w, d, gain, discs, slabs, acc_max, tau_s, lam_in, lam_out, iters=ADMM_ITERS):
    """センター's floor shift y [F, 2] (metres): the COM's shift gain * y pulled to d where w > 0 (held back by lam_in
    there, by lam_out elsewhere), minimum jerk, |y''| <= acc_max, y in every disc of `discs` [(centres [F, 2], radii
    [F])] and every slab of `slabs` [(m [F, 2], lo [F], hi [F])], never pointing away from the nearest pull"""
    F = len(w)
    if F < 5 or not np.any(w > 0):
        return np.zeros((F, 2)), {"iterations": 0}
    toward = toward_targets(d, int(round(1.5 * FPS)))
    # solved inside bounds tightened by SET_MARGIN (each still holds 0, the dance itself)
    sets = []
    for c, r in discs:
        rt = np.maximum(r - SET_MARGIN, np.minimum(r, np.linalg.norm(c, axis=1)))
        sets.append(lambda v, c=c, r=rt: proj_disc(v, c, r))
    for m, lo, hi in slabs:
        mn = np.linalg.norm(m, axis=1)
        lt, ht = np.minimum(lo + SET_MARGIN * mn, 0.0), np.maximum(hi - SET_MARGIN * mn, 0.0)
        sets.append(lambda v, m=m, lo=lt, hi=ht: proj_slab(v, m, lo, hi))
    sets.append(lambda v: proj_half(v, toward))

    def project(v, rounds=30):
        y = v.copy()
        inc = [np.zeros_like(v) for _ in sets]
        for _ in range(rounds):
            for j, proj in enumerate(sets):
                z = proj(y + inc[j])
                inc[j] = y + inc[j] - z
                y = z
        return y
    lam = np.where(w > 0, lam_in, lam_out)
    y, info = admm(w, d, lam, project, acc_max, tau_s, iters, gain=gain)
    # into the true bounds: the shift scaled down by a smooth cover of what each frame lacks (the bounds hold 0 and are
    # convex, so a frame scaled under its own largest scale is inside; scaling keeps the direction, so the half-plane)
    scale = np.ones(F)
    for c, r in discs:
        scale = np.minimum(scale, disc_scale(y, c, r))
    for m, lo, hi in slabs:
        scale = np.minimum(scale, slab_scale(y, m, lo, hi))
    cut = np.clip(smooth_cover(1.0 - scale, FIX_HALF), 0.0, 1.0)
    info["bound_cut_max"] = round(float(cut.max()), 5)
    return (1.0 - cut)[:, None] * y, info


def solve_drop(need, acc_max, tau_s, iters=ADMM_ITERS):
    """the hips' drop y [F] (metres), never under `need` (metres; 0 where nothing is needed): the least smooth curve
    (minimum jerk, |y''| <= acc_max)"""
    F = len(need)
    if F < 5 or not np.any(need > 0):
        return np.zeros(F), {"iterations": 0}
    lo = need[:, None]              # not tightened: a straight leg bends degrees for a millimetre more of drop
    y, info = admm(np.zeros(F), np.zeros((F, 1)), 1.0, lambda v: np.maximum(v, lo), acc_max, tau_s, iters,
                   tol_x_cm=0.01)
    y = y[:, 0]
    raise_ = smooth_cover(np.maximum(need - y, 0.0), FIX_HALF)      # up to the need where the solve left it short
    info["need_raise_cm_max"] = round(float(raise_.max()) * 100.0, 4)
    return y + raise_, info


# ---- the plan ---------------------------------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    arrays: dict = None         # per-frame curves (units unless named): shift [F, 3], com_before, com_after, pull, ...


def support_plan(body, p, com):
    """support (per foot), the single-support runs [(first, last, foot)], the pull's weight, its foot and the run's
    need_share per frame"""
    F = body.F
    low = {s: body.height(s) for s in SIDES}
    sup = {s: low[s] < SUPPORT_H for s in SIDES}
    other = {"左": "右", "右": "左"}
    single = {s: sup[s] & ~sup[other[s]] for s in SIDES}
    lift = {s: smoothstep((low[other[s]] * CM - SUPPORT_H * CM) / max(p["clear_cm"] - SUPPORT_H * CM, 1e-6)) for s in SIDES}
    ss = sorted([(a, b, s) for s in SIDES for a, b in runs(single[s])])
    w = np.zeros(F)
    foot = np.full(F, "", dtype=object)
    share = np.zeros(F)
    shares = []
    kinds = []
    lead, lag = int(round(p["lead_s"] * FPS)), int(round(p["lag_s"] * FPS))
    for i, (a, b, s) in enumerate(ss):
        prev_end = ss[i - 1][1] if i else -10 ** 9
        next_start = ss[i + 1][0] if i + 1 < len(ss) else 10 ** 9
        peak = float(np.max(lift[s][a:b + 1]))
        need = need_share(b - a + 1, float(com[(a + b) // 2, 1]) * UNIT_M)
        shares.append(need)
        if float(np.max(low[other[s]][a:b + 1])) * CM < p["clear_cm"]:
            # the other foot only hovers (never CLEAR_CM up): the trace's feet hover 0.4-4 cm on two feet too (a05), so
            # this is no evidence of standing on one foot, and the MV shows no lifted foot: no weight shift is asked for
            kinds.append("hover")
            continue
        if travels(body, com, a, b, s):
            kinds.append("transfer")
            continue
        kinds.append("pulled")

        def put(t, v):
            if v > w[t]:
                w[t], foot[t], share[t] = v, s, need
        for t in range(a, b + 1):
            put(t, max(float(lift[s][t]), 0.5 * peak))
        for j in range(1, lead + 1):
            t = a - j
            if t <= prev_end or t < 0 or not sup[s][t]:
                break
            put(t, peak * (1.0 - j / (lead + 1.0)))
        for j in range(1, lag + 1):
            t = b + j
            if t >= next_start or t >= F or not sup[s][t]:
                break
            put(t, peak * (1.0 - j / (lag + 1.0)))
    return {"low": low, "sup": sup, "single": single, "runs": ss, "w": w, "foot": foot, "share": share,
            "run_shares": shares, "run_kinds": kinds}


def travels(body, com, a, b, s):
    """True when the single-support run [a, b] on foot s is a step onto the next foot: at the run's middle the trace's COM
    moves away from the standing foot, towards where the other foot lands, at TRANSFER_V and more, and its extrapolated
    centre of mass (XcoM = COM + v / w, Hof et al. 2005) is past half the way there.  The body then falls onto the next
    foot, which catches it (the foot is placed beyond the XcoM, Hof 2008); holding it over the foot it leaves would mean
    reversing that fall"""
    F = body.F
    o = "右" if s == "左" else "左"
    m = (a + b) // 2
    land = min(F - 1, b + 1)
    here = 0.5 * (body.ankle(s)[m] + body.toe(s)[m])[[0, 2]]
    there = 0.5 * (body.ankle(o)[land] + body.toe(o)[land])[[0, 2]]
    gap = float(np.linalg.norm(there - here))
    if gap < 1e-6:
        return False
    u = (there - here) / gap
    i0, i1 = max(a, m - 2), min(b, m + 2)
    if i1 <= i0:
        i0, i1 = max(0, m - 1), min(F - 1, m + 1)
    if i1 <= i0:
        return False
    v = float((com[i1, [0, 2]] - com[i0, [0, 2]]) @ u) * UNIT_M * FPS / (i1 - i0)      # m/s
    e = float((com[m, [0, 2]] - here) @ u) * UNIT_M
    w = math.sqrt(G / max(float(com[m, 1]) * UNIT_M, 0.2))
    return v >= TRANSFER_V and e + v / w >= 0.5 * gap * UNIT_M


def need_share(frames, com_height_m):
    """how much of the way onto the standing foot a single-support run of `frames` needs: a COM at rest an offset e
    outside the foot, with the pressure at the foot's edge, drifts e (cosh(w T) - 1) in the run (w = sqrt(g / height),
    the linear inverted pendulum).  A brief step (0.2 s: 0.23 e) is caught by the next foot; from about 0.4 s on the
    body would fall (1 e and more), so the weight must be over the foot: min(1, cosh(w T) - 1)"""
    w = math.sqrt(G / max(com_height_m, 0.2))
    return min(1.0, math.cosh(w * frames / FPS) - 1.0)


def band_target(body, com, plan, r_bal_cm):
    """d [F, 2] (metres): from the COM's floor point to the nearest point of the standing sole's band, on pull frames,
    times the run's need_share"""
    F = body.F
    d = np.zeros((F, 2))
    rb = r_bal_cm / CM
    soles = {s: body.sole(s) for s in SIDES}
    q = com[:, [0, 2]]
    for s in SIDES:
        m = plan["foot"] == s
        if not m.any():
            continue
        heel, toe = soles[s][0][m], soles[s][1][m]
        ab = toe - heel
        t = np.clip(np.sum((q[m] - heel) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
        n = heel + t[:, None] * ab
        dv = q[m] - n
        dist = np.linalg.norm(dv, axis=1)
        far = dist > rb
        out = np.zeros_like(dv)
        out[far] = (n[far] + dv[far] * (rb / dist[far])[:, None]) - q[m][far]
        d[m] = out
    return d * UNIT_M * plan["share"][:, None]


def com_response(body, com0, carry=None):
    """how far the COM's floor point follows センター's floor move, per frame (the knees re-solved; the feet on the floor
    stay, a lifted foot goes with the body by its carry)"""
    F = body.F
    k = np.zeros(F)
    probe = 0.125                                           # units (1 cm)
    for axis in (0, 2):
        sh = np.zeros((F, 3))
        sh[:, axis] = probe
        c = body.moved(sh, carry).com()
        k += (c[:, axis] - com0[:, axis]) / probe
    return np.clip(0.5 * k, 0.5, 1.0)


def carry_factor(low, p):
    """[F]: how much of センター's floor shift a foot's IK takes: 0 while the foot supports (under SUPPORT_H), 1 from
    CLEAR_CM up (a lifted foot goes with the body, so the lifted leg keeps the dance's shape against the pelvis), a
    smoothstep between; then smoothed under itself (the running minimum over +-CARRY_HALF frames averaged by a raised
    cosine), so it is 0 on every frame the foot supports and changes smoothly"""
    clear = p["clear_cm"] / CM
    raw = smoothstep((low - SUPPORT_H) / max(clear - SUPPORT_H, 1e-6))
    c = np.clip(1.0 - smooth_cover(1.0 - raw, CARRY_HALF), 0.0, 1.0)
    c[low < SUPPORT_H] = 0.0
    return c


def knee_give(L1, L2, flex_deg, give_deg):
    """how much nearer (units) the hip comes to the ankle when the knee bends from flex_deg by give_deg"""
    def dist(th):
        return np.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * np.cos(np.radians(np.clip(th, 0.0, 180.0))))
    return np.maximum(dist(flex_deg) - dist(flex_deg + give_deg), 0.0)


def drop_allowance(body, plan, drop_max_cm, give_deg):
    """per leg and frame, how far (units) the hips may go down for that leg to reach its foot: the drop does not bend
    the leg it is for (that leg stays at its reach; the hip goes round the ankle), it bends the other leg if that one is
    on the floor, by at most give_deg more (a straight leg gives about 0.5 cm, one bent 40 degrees 2.9 cm); at most
    drop_max"""
    give = {}
    for s in SIDES:
        L1, L2 = body.legs_rest[s]
        give[s] = np.where(plan["sup"][s], knee_give(L1, L2, body.knee_flexion(s), give_deg), np.inf)
    cap = drop_max_cm / CM
    return {"左": np.minimum(cap, give["右"]), "右": np.minimum(cap, give["左"])}


def hip_share(carry, s, F):
    """1 - carry: how much of センター's floor shift moves leg s's hip against its foot"""
    return np.ones(F) if carry is None or s not in carry else 1.0 - carry[s]


def reach_discs(body, allowance, carry=None):
    """per leg, the disc of センター floor shifts (metres) that keep its IK target within reach with the hips also down
    by up to allowance[leg] (units, per frame); a target already out of reach: no farther than it was.  A carried foot
    moves with the hip by its carry: the hip moves against it by (1 - carry) y, so the disc grows by 1 / (1 - carry)"""
    discs = []
    for s in SIDES:
        D = body.ankle(s) - body.hip(s)
        v = -D[:, 1]                                       # the hip's height over the target
        v2 = v - np.clip(v, 0.0, allowance[s])
        R = np.maximum(body.leg_length(s) - REACH_TOL_CM / CM, np.linalg.norm(D, axis=1))
        r = np.sqrt(np.maximum(R * R - v2 * v2, 0.0))
        g = hip_share(carry, s, body.F)
        free = g < KEPT_MIN
        gg = np.maximum(g, KEPT_MIN)[:, None]
        centre = np.where(free[:, None], 0.0, D[:, [0, 2]] * UNIT_M / gg)
        radius = np.where(free, FREE_M, r * UNIT_M / gg[:, 0])
        discs.append((centre, radius))
    return discs


def range_slabs(body, carry=None):
    """per leg, the slab of センター floor shifts (metres) that keep the hip's adduction (the hip-to-ankle line out of
    下半身's sagittal plane, towards the other leg) under HIP_ADDUCTION_DEG[1] and its abduction under
    HIP_ABDUCTION_DEG, or no farther than they were (linearized: the line's length kept); a carried foot's leg by
    (1 - carry) of the shift"""
    slabs = []
    sa, sb = math.sin(math.radians(HIP_ADDUCTION_DEG[1])), math.sin(math.radians(HIP_ABDUCTION_DEG))
    for s in SIDES:
        D = body.ankle(s) - body.hip(s)
        n = np.linalg.norm(D, axis=1)
        m = body.medial(s)
        dm = np.sum(D * m, axis=1)                      # the line's medial part: n sin(adduction)
        # adduction: (D - y) . m <= max(sa n, dm)   ->  y . m >= dm - max(sa n, dm)
        lo = dm - np.maximum(sa * n, dm)
        # abduction: -(D - y) . m <= max(sb n, -dm)  ->  y . m <= dm + max(sb n, -dm)
        hi = dm + np.maximum(sb * n, -dm)
        slabs.append((m[:, [0, 2]] * hip_share(carry, s, body.F)[:, None], lo * UNIT_M, hi * UNIT_M))
    return slabs


def knee_slabs(body, carry=None):
    """per leg, the half-plane of センター floor shifts (metres) that keep the hip at least as far from the IK target
    as the two-bone leg is at KNEE_FLEXION_DEG[1] (159 degrees, the reference range's upper proposal), or no nearer
    than it was: (D - (1 - carry) y) . D / |D| >= that distance (linearized: |D'| >= D' . D / |D|)"""
    slabs = []
    for s in SIDES:
        L1, L2 = body.legs_rest[s]
        d_min = math.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * math.cos(math.radians(KNEE_FLEXION_DEG[1])))
        D = body.ankle(s) - body.hip(s)
        n = np.maximum(np.linalg.norm(D, axis=1), 1e-9)
        u = D[:, [0, 2]] / n[:, None]
        hi = (n - np.minimum(n, d_min)) * UNIT_M
        slabs.append((u * hip_share(carry, s, body.F)[:, None], np.full(body.F, -FREE_M), hi))
    return slabs


def drop_needed(body, tol_cm=REACH_TOL_CM, before=None):
    """the least drop of the hips (units, per frame) for every IK target to be within its leg's reach (or no farther
    than in `before`), inf where no drop does it"""
    need = np.zeros(body.F)
    for s in SIDES:
        D = body.ankle(s) - body.hip(s)
        R = body.leg_length(s) - tol_cm / CM
        if before is not None:
            R = np.maximum(R, before.reach(s))
        rh = np.linalg.norm(D[:, [0, 2]], axis=1)
        v = -D[:, 1]
        ok = rh < R
        n = np.where(ok, v - np.sqrt(np.maximum(R * R - rh * rh, 0.0)), np.inf)
        need = np.maximum(need, n)
    return np.maximum(need, 0.0)


def touchdowns(body):
    """[(frame, foot)] of a05's touchdowns: on the floor again after GAP frames off it in which it rose SWING_MIN_H"""
    out = []
    for s in SIDES:
        low = body.height(s)
        cont = low < CONTACT_EPS
        rr = runs(cont)
        for (a0, b0), (a1, b1) in zip(rr[:-1], rr[1:]):
            if a1 - b0 - 1 >= GAP and low[b0 + 1:a1].max() >= SWING_MIN_H:
                out.append((a1, s))
    return sorted(out)


def dip_bump(F, at, peak_f, end_f):
    """0 .. 1 .. 0 from frame `at`: sin^2 up to at + peak_f, cos^2 down to at + end_f (smooth at both ends and the top)"""
    t = np.arange(F) - at
    up = np.sin(0.5 * math.pi * np.clip(t / peak_f, 0.0, 1.0)) ** 2
    down = np.cos(0.5 * math.pi * np.clip((t - peak_f) / (end_f - peak_f), 0.0, 1.0)) ** 2
    return np.where(t < 0, 0.0, np.where(t <= peak_f, up, np.where(t <= end_f, down, 0.0)))


def landing_dips(body, plan, p):
    """the hips' drop (units, per frame) of the landings that take the weight, and the landings' list"""
    F = body.F
    other = {"左": "右", "右": "左"}
    window = int(round(DIP_WINDOW_S * FPS))
    peak_f, end_f = DIP_PEAK_S * FPS, DIP_END_S * FPS
    dip = np.zeros(F)
    rows = []
    for f, s in touchdowns(body):
        o = other[s]
        lo = plan["low"]
        # takes the weight: the other foot is up at the landing or lifts within the window, before this foot lifts again
        b = min(F, f + window + 1)
        own_up = np.flatnonzero(lo[s][f:b] >= SUPPORT_H)
        own_end = f + int(own_up[0]) if len(own_up) else b
        takes = bool(np.any(lo[o][f:own_end] >= SUPPORT_H))
        row = {"frame": f, "s": round(f / FPS, 2), "foot": s, "takes_weight": takes, "depth_cm": 0.0}
        if takes and p["dip"]:
            flex = body.knee_flexion(s)
            pk = min(F - 1, f + int(round(peak_f)))
            have = float(flex[f:pk + 1].max() - flex[f])
            target = min(float(flex[f]) + p["dip_deg"], KNEE_FLEXION_DEG[0])
            if target > float(flex[pk]) + 0.5 and have < p["dip_deg"] - 0.5:
                L1, L2 = body.legs_rest[s]
                dist = math.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * math.cos(math.radians(target)))
                H, A = body.hip(s)[pk], body.ankle(s)[pk]
                rh = float(np.hypot(*(A - H)[[0, 2]]))
                v = float(H[1] - A[1])
                if dist > rh and v > 0:
                    # the whole depth this landing needs at its top, less what the dips before it already give there
                    # (added, not the larger of the two: the larger of two smooth bumps has a corner where they cross)
                    total = float(np.clip(v - math.sqrt(dist * dist - rh * rh), 0.0, DIP_MAX_CM / CM))
                    depth = max(0.0, total - float(dip[pk]))
                    if depth > 0:
                        dip = dip + depth * dip_bump(F, f, peak_f, end_f)
                        row["depth_cm"] = round(depth * CM, 2)
                        row["knee_have_deg"] = round(have, 2)
        rows.append(row)
    return dip, rows


# ---- the measures -----------------------------------------------------------------------------------------------

def a05_lateral(body, com):
    """a05 (s15_lateral.py): frames with one foot on the floor (4 mm) and the other 5 cm up: the COM's sideways distance
    from the standing foot's centre along 下半身's side axis, + towards the lifted foot (cm); and the frames"""
    fwd = body.facing()[:, [0, 2]]
    lat = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    low = {s: body.height(s) for s in SIDES}
    cont = {s: low[s] < CONTACT_EPS for s in SIDES}
    fc = {s: (0.5 * (body.ankle(s) + body.toe(s)))[:, [0, 2]] for s in SIDES}
    offs, frames = [], []
    for s, o in (("左", "右"), ("右", "左")):
        m = cont[s] & ~cont[o] & (low[o] * CM >= 5.0)
        for f in np.flatnonzero(m):
            sgn = np.sign((fc[o][f] - fc[s][f]) @ lat[f]) or 1.0
            offs.append(float((com[f, [0, 2]] - fc[s][f]) @ lat[f] * sgn * CM))
            frames.append(int(f))
    order = np.argsort(frames, kind="stable")
    return np.array(offs)[order], np.array(frames, dtype=int)[order]


def lateral_summary(offs):
    if not len(offs):
        return {"frames": 0}
    return {"frames": int(len(offs)), "median": round(float(np.median(offs)), 2),
            "q(10,25,75,90)": [round(float(v), 2) for v in np.quantile(offs, [.1, .25, .75, .9])],
            "share_0_to_3": round(float(np.mean((offs >= 0) & (offs <= 3))), 3),
            "share_abs_le_3": round(float(np.mean(np.abs(offs) <= 3)), 3),
            "share_gt_5": round(float(np.mean(offs > 5)), 3)}


def band_distance(body, com, foot):
    """cm from the COM's floor point to the standing sole's line, per frame (nan where no foot)"""
    out = np.full(body.F, np.nan)
    q = com[:, [0, 2]]
    for s in SIDES:
        m = foot == s
        if not m.any():
            continue
        heel, toe = (x[m] for x in body.sole(s))
        ab = toe - heel
        t = np.clip(np.sum((q[m] - heel) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
        out[m] = np.linalg.norm(q[m] - (heel + t[:, None] * ab), axis=1) * CM
    return out


# ---- the layer --------------------------------------------------------------------------------------------------

def layer(model, motion, params=None, log=None):
    log = log or (lambda *_: None)
    p = params_default()
    p.update(params or {})
    t0 = time.time()
    body = Body(model, motion)
    F = body.F
    com0 = body.com()
    plan = support_plan(body, p, com0)
    report = {"params": dict(p), "frames": F}
    plan.update({"r_bal_cm": p["r_bal_cm"], "acc_max": p["acc_max"]})
    w = plan["w"]
    x = np.zeros((F, 2))
    k = np.ones(F)
    info = {"iterations": 0}
    reach_tight = np.zeros(F, bool)
    range_tight = np.zeros(F, bool)
    knee_tight = np.zeros(F, bool)
    allowance = drop_allowance(body, plan, p["drop_max_cm"], KNEE_GIVE_DEG)
    carry = {s: carry_factor(plan["low"][s], p) for s in SIDES}
    if np.any(w > 0):
        d = band_target(body, com0, plan, p["r_bal_cm"])
        k = com_response(body, com0, carry)
        discs = reach_discs(body, allowance, carry)
        slabs = range_slabs(body, carry)
        kslabs = knee_slabs(body, carry)
        log("solving the shift over %d frames (%d pull frames)" % (F, int(np.sum(w > 0))))
        y, info = solve_shift(w, d, k, discs, slabs + kslabs, p["acc_max"], p["tau_s"], p["lam_in"], p["lam_out"])
        moving = np.linalg.norm(y, axis=1) > 1e-4
        edge = SET_MARGIN + 5e-4                        # the solve keeps SET_MARGIN inside the bounds
        for c, r in discs:                              # the shift stopped by a leg's reach: on its disc's edge
            reach_tight |= (np.linalg.norm(y - c, axis=1) > r - edge) & moving
        for group, tight in ((slabs, range_tight), (kslabs, knee_tight)):   # or by a hip's or knee's range
            for m, lo, hi in group:
                s_ = np.sum(y * m, axis=1)
                nm = np.linalg.norm(m, axis=1)
                ok = nm > 1e-9
                near = np.zeros(F, bool)
                near[ok] = ((s_[ok] - lo[ok]) / nm[ok] < edge) | ((hi[ok] - s_[ok]) / nm[ok] < edge)
                tight |= near & moving
        x = k[:, None] * y                              # the COM's shift (linearized), for the report
    else:
        d = np.zeros((F, 2))
        y = np.zeros((F, 2))
    plan["reach_tight"] = reach_tight
    plan["range_tight"] = range_tight
    plan["knee_tight"] = knee_tight
    shift = np.zeros((F, 3))
    shift[:, [0, 2]] = y / UNIT_M
    moved = body.moved(shift, carry)
    need = drop_needed(moved, before=body)
    finite = np.isfinite(need)
    drop, info["drop"] = solve_drop(np.where(finite, need, 0.0) * UNIT_M, DROP_ACC_MAX, p["tau_s"])
    drop = drop / UNIT_M
    allow_any = np.maximum(allowance["左"], allowance["右"])
    drop_over = int(np.sum(need[finite] > allow_any[finite] + 1e-4))
    moved = body.moved(shift - np.stack([np.zeros(F), drop, np.zeros(F)], 1), carry)
    dip, landings = landing_dips(moved, plan, p)        # on the body already moved and dropped: the two add up
    shift[:, 1] = -(drop + dip)
    floor = shift.copy()
    floor[:, 1] = 0.0
    feet = {s: carry[s][:, None] * floor for s in SIDES}     # the carried feet's world move (units)
    if np.abs(shift).max() < 1e-6:
        out = motion
    else:
        out = write_centre(model, motion, body, shift)
        out = write_feet(out, body, feet)
    after = Body(model, out)
    report.update(measures(body, after, com0, plan, x, d, shift, drop, dip, landings, info, motion, out, drop_over,
                           unreachable=int(np.sum(~finite)), feet=feet))
    report["seconds"] = round(time.time() - t0, 2)
    foot_code = np.array([{"左": 1, "右": 2}.get(v, 0) for v in plan["foot"]], dtype=np.int8)
    arrays = {"shift": shift, "com_before": com0, "com_after": after.com(), "com_shift_m": x, "pull": w,
              "pull_foot": foot_code, "pull_target_m": d, "share": plan["share"], "com_response": k, "drop": drop,
              "dip": dip, "reach_tight": plan["reach_tight"], "range_tight": plan["range_tight"],
              "knee_tight": plan["knee_tight"], "drop_allowance_L": allowance["左"], "drop_allowance_R": allowance["右"],
              "low_L": plan["low"]["左"], "low_R": plan["low"]["右"], "carry_L": carry["左"], "carry_R": carry["右"],
              "foot_move_L": feet["左"], "foot_move_R": feet["右"]}
    for s, tag in (("左", "L"), ("右", "R")):
        arrays["knee_before_" + tag] = body.knee_flexion(s)
        arrays["knee_after_" + tag] = after.knee_flexion(s)
        arrays["reach_before_" + tag] = body.reach(s)
        arrays["reach_after_" + tag] = after.reach(s)
        arrays["adduction_before_" + tag] = body.hip_adduction(s)
        arrays["adduction_after_" + tag] = after.hip_adduction(s)
        arrays["ankle_" + tag] = body.ankle(s)
        arrays["toe_" + tag] = body.toe(s)
    return Result(out, report, arrays)


def write_centre(model, motion, body, shift):
    """the dance with センター's keys on every frame: its own value plus the world shift (units) in its parent's frame"""
    sk = body.sk
    ci = sk.i(CENTRE)
    parent = sk.parent(ci)
    F = body.F
    if parent is None:
        Rp = np.tile(M.IDENT, (F, 1))
    else:
        Rp = body.q(sk.bones[parent].name)
    local = M.qrot(M.qconj(Rp), shift)
    tracks = fk.tracks_of(motion)
    keys = tracks.get(CENTRE) or tracks.get(fk.vmd_name(CENTRE)) or []
    frames = [kk.frame for kk in keys]
    raw = keys[0].raw_name if keys else None
    label = keys[0].name if keys else CENTRE
    linear = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    new = []
    for f in range(F):
        if keys:
            pos, rot = fk.sample(keys, f, frames)
        else:
            pos, rot = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
        pnew = tuple(float(a) + float(b) for a, b in zip(pos, local[f]))
        new.append(vmd.BoneKey(label, f, pnew, tuple(float(v) for v in rot), linear, raw_name=raw))
    kept = [kk for kk in motion.bones if kk.name != label]
    return vmd.Motion(model_name=motion.model_name, bones=kept + new, morphs=motion.morphs, cameras=motion.cameras,
                      lights=motion.lights, shadows=motion.shadows, show_iks=motion.show_iks)


def write_feet(motion, body, feet):
    """the dance with each carried foot IK moved by feet[side] [F, 3] (units, world; 0 on the floor): per-frame linear
    keys from the last key before each moved span to the first key after it, the rest of the track byte for byte (so
    the feet on the floor, their heights and turns stay the dance's)"""
    sk = body.sk
    F = body.F
    bones = list(motion.bones)
    tracks = fk.tracks_of(motion)
    for s in SIDES:
        move = feet[s]
        if np.abs(move).max() < 1e-9:
            continue
        name = s + "足ＩＫ"
        parent = sk.parent(sk.i(name))
        Rp = np.tile(M.IDENT, (F, 1)) if parent is None else body.q(sk.bones[parent].name)
        local = M.qrot(M.qconj(Rp), move)
        keys = sorted(tracks.get(name) or tracks.get(fk.vmd_name(name)) or [], key=lambda kk: kk.frame)
        frames = [kk.frame for kk in keys]
        raw = keys[0].raw_name if keys else None
        label = keys[0].name if keys else name
        redo = np.zeros(F, bool)
        for a, b in runs(np.linalg.norm(move, axis=1) > 1e-9):
            before = [fr for fr in frames if fr <= a - 1]
            after = [fr for fr in frames if fr >= b + 1]
            first = before[-1] + 1 if before else max(0, a - 1)
            last = after[0] if after else min(F - 1, b + 1)
            redo[first:last + 1] = True
        linear = vmd.bone_interpolation(vmd.LINEAR_CURVE)
        new = [kk for kk in keys if kk.frame >= F or not redo[kk.frame]]
        for f in np.flatnonzero(redo):
            if keys:
                pos, rot = fk.sample(keys, int(f), frames)
            else:
                pos, rot = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
            pnew = tuple(float(a) + float(b) for a, b in zip(pos, local[f]))
            new.append(vmd.BoneKey(label, int(f), pnew, tuple(float(v) for v in rot), linear, raw_name=raw))
        new.sort(key=lambda kk: kk.frame)
        bones = [kk for kk in bones if kk.name != label] + new
    return vmd.Motion(model_name=motion.model_name, bones=bones, morphs=motion.morphs, cameras=motion.cameras,
                      lights=motion.lights, shadows=motion.shadows, show_iks=motion.show_iks)


def measures(before, after, com0, plan, x, d, shift, drop, dip, landings, info, motion, out, drop_over, unreachable,
             feet=None):
    F = before.F
    com1 = after.com()
    rep = {}
    ob, fr = a05_lateral(before, com0)
    oa, fr2 = a05_lateral(after, com1)
    run_len = np.zeros(F, int)
    for a, b, s in plan["runs"]:
        run_len[a:b + 1] = b - a + 1
    holds = run_len[fr] >= 15 if len(fr) else np.zeros(0, bool)
    rep["a05_lateral_cm"] = {"before": lateral_summary(ob), "after": lateral_summary(oa),
                             "before_holds": lateral_summary(ob[holds]) if len(fr) else {"frames": 0},
                             "after_holds": lateral_summary(oa[holds]) if len(fr) else {"frames": 0},
                             "holds": "single-support runs of 15 frames (0.5 s) and more"}
    # the runs
    foot = plan["foot"]
    dist_after = band_distance(after, com1, foot)
    dist_before = band_distance(before, com0, foot)
    acc = np.zeros((F, 2))                              # the COM's added acceleration on the floor (m/s^2)
    if F >= 3:
        acc[1:-1] = d2((com1 - com0)[:, [0, 2]] * UNIT_M) * FPS * FPS
    rows = []
    for (a, b, s), need, kind in zip(plan["runs"], plan["run_shares"], plan["run_kinds"]):
        o = "右" if s == "左" else "左"
        lift = float(plan["low"][o][a:b + 1].max() * CM)
        seg = slice(a, b + 1)
        da, db = dist_after[seg], dist_before[seg]
        rb = plan["r_bal_cm"]
        if kind != "pulled":
            rows.append({"first": a, "last": b, "s": [round(a / FPS, 2), round(b / FPS, 2)], "frames": b - a + 1,
                         "foot": s, "other_up_cm": round(lift, 1), "kind": kind,
                         "shift_cm_max": round(float(np.linalg.norm(shift[seg][:, [0, 2]], axis=1).max() * CM), 2)})
            continue
        if np.isfinite(da).any() and np.isfinite(db).any():
            before_cm = float(np.nanmedian(db))
            intended = rb + (1.0 - need) * max(0.0, before_cm - rb)
            short = float(np.nanmedian(da)) - intended
        else:
            intended, short = None, 0.0
        limited = []
        if short > 1.0:
            want = np.linalg.norm(d[seg], axis=1)
            got = np.linalg.norm(x[seg], axis=1)
            frac = float(np.median(got / np.maximum(want, 1e-9)))
            # what stopped it: a leg's reach (the shift on the edge of a reach disc in or just before the run), or the
            # acceleration bound (the added acceleration at its bound in the run or the half second before)
            if np.any(plan["reach_tight"][max(0, a - 5):b + 1]):
                limited.append("reach")
            if np.any(plan["range_tight"][max(0, a - 5):b + 1]):
                limited.append("hip range")
            if np.any(np.linalg.norm(acc[max(0, a - 15):b + 1], axis=1) > 0.95 * plan["acc_max"]):
                limited.append("acceleration")
            if not limited:
                limited.append("pull %.2f" % frac)
        rows.append({"first": a, "last": b, "s": [round(a / FPS, 2), round(b / FPS, 2)], "frames": b - a + 1,
                     "foot": s, "other_up_cm": round(lift, 1), "kind": kind, "need_share": round(need, 3),
                     "intended_cm": None if intended is None else round(intended, 2),
                     "band_distance_cm_before": round(float(np.nanmedian(db)), 2) if np.isfinite(db).any() else None,
                     "band_distance_cm_after": round(float(np.nanmedian(da)), 2) if np.isfinite(da).any() else None,
                     "short_of_target_cm": round(max(short, 0.0), 2), "limited_by": limited})
    rep["runs"] = rows
    pulled = [r for r in rows if r["kind"] == "pulled"]
    rep["runs_summary"] = {"count": len(rows), "kinds": {k: sum(1 for r in rows if r["kind"] == k) for k in sorted({r["kind"] for r in rows})},
                           "short_over_3cm": sum(1 for r in pulled if r["short_of_target_cm"] > 3.0),
                           "short_over_3cm_by_reach": sum(1 for r in pulled if r["short_of_target_cm"] > 3.0 and "reach" in r["limited_by"]),
                           "short_over_3cm_holds": sum(1 for r in pulled if r["short_of_target_cm"] > 3.0 and r["frames"] >= 15),
                           "not_pulled_shift_cm_max": round(max([r["shift_cm_max"] for r in rows if r["kind"] != "pulled"] or [0.0]), 2)}
    # the centre
    sh = shift * CM
    step = np.linalg.norm(np.diff(sh, axis=0), axis=1) if F > 1 else np.zeros(0)
    a2 = d2(shift * UNIT_M) * FPS * FPS if F > 2 else np.zeros((0, 3))
    acc_c = np.linalg.norm(a2, axis=1)
    acc_h, acc_v = np.linalg.norm(a2[:, [0, 2]], axis=1), np.abs(a2[:, 1])
    k = (com0[:, 1] * UNIT_M) / G
    rep["centre"] = {"shift_cm": q_stats(np.linalg.norm(sh[:, [0, 2]], axis=1)), "down_cm": q_stats(-sh[:, 1]),
                     "step_cm": q_stats(step, (0.5, 0.99)), "added_acc_m_s2": q_stats(acc_c),
                     "added_acc_h_m_s2": q_stats(acc_h), "added_acc_v_m_s2": q_stats(acc_v),
                     "com_added_acc_m_s2": q_stats(np.linalg.norm(acc, axis=1)),
                     "pressure_move_cm": q_stats(np.linalg.norm(acc, axis=1) * k * 100.0),
                     "reach_drop_cm": q_stats(drop * CM), "landing_dip_cm": q_stats(dip * CM),
                     "reach_drop_over_max_frames": drop_over, "unreachable_by_any_drop_frames": unreachable}
    # the anticipation: per run of 9 frames and more with a shift of 1 cm and more
    apa = []
    for a, b, s in plan["runs"]:
        if b - a + 1 < 9:
            continue
        mid = (a + b) // 2
        n = np.linalg.norm(x[mid])
        if n < 0.01:
            continue
        prof = x @ (x[mid] / n)
        onset = next((j for j in range(0, 60) if a - j < 0 or prof[a - j] < 0.1 * prof[mid]), None)
        apa.append((float(prof[a] / prof[mid]), onset))
    if apa:
        rep["apa"] = {"runs": len(apa), "share_done_at_lift(25,50,75)": [round(float(v), 2) for v in np.quantile([u for u, _ in apa], [.25, .5, .75])],
                      "start_before_lift_s(25,50,75)": [round(float(v), 3) for v in np.quantile([o / FPS for _, o in apa if o is not None], [.25, .5, .75])]}
    else:
        rep["apa"] = {"runs": 0}
    # reach, knees, hips
    reach, knee, hip = {}, {}, {}
    for s, tag in (("左", "L"), ("右", "R")):
        L = before.leg_length(s)
        rb, ra = before.reach(s), after.reach(s)
        reach["unreachable_frames_" + tag] = [int(np.sum(rb - L > CONTACT_EPS)), int(np.sum(ra - L > CONTACT_EPS))]
        reach["worse_frames_" + tag] = int(np.sum((ra > np.maximum(L, rb) + 1e-6)))
        on = plan["sup"][s]
        kb, ka = before.knee_flexion(s), after.knee_flexion(s)
        knee["on_floor_deg_" + tag] = {"before": q_stats(kb[on], (0.05, 0.5, 0.95)), "after": q_stats(ka[on], (0.05, 0.5, 0.95))}
        knee["change_deg_" + tag] = q_stats(np.abs(ka - kb), (0.5, 0.99))
        knee["over_%d_frames_%s" % (KNEE_FLEXION_DEG[0], tag)] = [int(np.sum(kb > KNEE_FLEXION_DEG[0])), int(np.sum(ka > KNEE_FLEXION_DEG[0]))]
        knee["over_%d_newly_%s" % (KNEE_FLEXION_DEG[1], tag)] = int(np.sum((ka > KNEE_FLEXION_DEG[1]) & (ka > kb + 0.5)))
        knee["max_deg_" + tag] = [round(float(kb.max()), 1), round(float(ka.max()), 1)]
        hb, ha = before.hip_adduction(s), after.hip_adduction(s)
        hip["adduction_deg_" + tag] = {"before": q_stats(hb, (0.5, 0.99)), "after": q_stats(ha, (0.5, 0.99))}
        hip["over_%d_frames_%s" % (HIP_ADDUCTION_DEG[0], tag)] = [int(np.sum(hb > HIP_ADDUCTION_DEG[0])), int(np.sum(ha > HIP_ADDUCTION_DEG[0]))]
        hip["over_%d_frames_%s" % (HIP_ADDUCTION_DEG[1], tag)] = [int(np.sum(hb > HIP_ADDUCTION_DEG[1])), int(np.sum(ha > HIP_ADDUCTION_DEG[1]))]
        hip["over_%d_newly_%s" % (HIP_ADDUCTION_DEG[1], tag)] = int(np.sum((ha > HIP_ADDUCTION_DEG[1]) & (ha > hb + 0.5)))
    rep["reach"], rep["knee"], rep["hip"] = reach, knee, hip
    # the landings
    gains = {"before": [], "after": []}
    for row in landings:
        f, s = row["frame"], row["foot"]
        for tag, bd in (("before", before), ("after", after)):
            fl = bd.knee_flexion(s)
            gains[tag].append(float(fl[f:min(F, f + 5)].max() - fl[f]))
    takes = [r for r in landings if r["takes_weight"]]
    rep["landings"] = {"count": len(landings), "take_weight": len(takes), "dipped": sum(1 for r in landings if r["depth_cm"] > 0),
                       "knee_gain_0.13s_deg": {t: q_stats(np.array(v), (0.25, 0.5, 0.75)) if v else None for t, v in gains.items()},
                       "share_gain_ge_10deg": {t: round(float(np.mean(np.array(v) >= 10.0)), 3) if v else None for t, v in gains.items()},
                       "dips": [r for r in landings if r["depth_cm"] > 0][:400]}
    # the carried feet: moved on the floor plane only, not on the floor
    feet = feet or {}
    carried = set()
    for s in SIDES:
        if s in feet and np.abs(feet[s]).max() >= 1e-9:
            carried |= {s + "足ＩＫ", fk.vmd_name(s + "足ＩＫ")}
    rep["feet_carry"] = {}
    for s in SIDES:
        mv = feet.get(s, np.zeros((F, 3)))
        n = np.linalg.norm(mv, axis=1)
        on = plan["sup"][s]
        rep["feet_carry"][s] = {"frames": int(np.sum(n > 1e-6)), "max_cm": round(float(n.max() * CM), 2),
                                "on_floor_cm_max": round(float(n[on].max() * CM), 6) if on.any() else 0.0,
                                "height_cm_max": round(float(np.abs(mv[:, 1]).max() * CM), 6)}
    # untouched bytes: every bone but センター and the carried foot IKs
    skip = {CENTRE} | carried

    def others(m):
        return vmd.dumps(vmd.Motion(model_name=m.model_name, bones=[kk for kk in m.bones if kk.name not in skip],
                                    morphs=m.morphs, cameras=m.cameras, lights=m.lights, shadows=m.shadows,
                                    show_iks=m.show_iks))
    rep["untouched"] = {"identical": others(motion) == others(out),
                        "bones": len({kk.name for kk in motion.bones if kk.name not in skip}),
                        "written": sorted(skip)}
    rep["solver"] = info
    return rep


# ---- the command ------------------------------------------------------------------------------------------------

def write_bytes(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


def check_distinct(*paths):
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, MODEL, OUT and --report must all differ" % (seen[key], path))
        seen[key] = path


def short_line(report):
    a05 = report["a05_lateral_cm"]
    return {"a05_median_cm": [a05["before"].get("median"), a05["after"].get("median")],
            "a05_holds_median_cm": [a05["before_holds"].get("median"), a05["after_holds"].get("median")],
            "shift_cm_max": report["centre"]["shift_cm"]["max"] if report["centre"]["shift_cm"] else 0.0,
            "step_cm_max": report["centre"]["step_cm"]["max"] if report["centre"]["step_cm"] else 0.0,
            "runs_short_over_3cm": report["runs_summary"]["short_over_3cm"],
            "landings_dipped": report["landings"]["dipped"], "untouched_identical": report["untouched"]["identical"],
            "seconds": report.get("seconds")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance", help="the dance (.vmd)")
    ap.add_argument("model", help="the model (.pmx or .pmd) the dance is for")
    ap.add_argument("out", help="the dance with the weight on the standing foot (.vmd)")
    ap.add_argument("--report", help="write the full report (JSON)")
    ap.add_argument("--r-bal", type=float, default=R_BAL_CM, help="cm: the band about the standing sole's line")
    ap.add_argument("--acc-max", type=float, default=ACC_MAX, help="m/s^2: the added acceleration of the COM")
    ap.add_argument("--lead", type=float, default=LEAD_S, help="s: the pull starts this long before the foot lifts")
    ap.add_argument("--lag", type=float, default=LAG_S, help="s: and ends this long after it lands")
    ap.add_argument("--drop-max", type=float, default=DROP_MAX_CM, help="cm: the hips may go down for the legs' reach")
    ap.add_argument("--dip-deg", type=float, default=DIP_DEG, help="degrees: the knee's bend on a landing")
    ap.add_argument("--no-dip", action="store_true", help="no knee bend on the landings")
    ap.add_argument("--arrays", help="write the per-frame curves (.npz) for figures and checks")
    args = ap.parse_args(argv)
    try:
        check_distinct(args.dance, args.model, args.out, args.report, args.arrays)
        motion = vmd.load(args.dance)
        model = (pmd if args.model.lower().endswith(".pmd") else pmx).load(args.model)
        params = {"r_bal_cm": args.r_bal, "acc_max": args.acc_max, "lead_s": args.lead, "lag_s": args.lag,
                  "drop_max_cm": args.drop_max, "dip_deg": args.dip_deg, "dip": not args.no_dip}
        result = layer(model, motion, params)
        write_bytes(os.path.abspath(args.out), vmd.dumps(result.motion))
        report = dict(result.report, dance=os.path.abspath(args.dance), model=os.path.abspath(args.model),
                      out=os.path.abspath(args.out))
        if args.report:
            write_bytes(os.path.abspath(args.report), (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        if args.arrays:
            buf = io.BytesIO()
            np.savez_compressed(buf, **result.arrays)
            write_bytes(os.path.abspath(args.arrays), buf.getvalue())
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True, "out": os.path.abspath(args.out)}, **short_line(result.report)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
