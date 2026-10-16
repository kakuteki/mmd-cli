"""Put the dancer's weight on the standing foot: while one foot is off the floor, センター carries the body over the other
foot, starting before the foot lifts (an anticipatory weight shift), and a foot that lands and takes the weight bends
its knee.  A lifted foot goes with the body (its IK moves on the floor plane by the shift); a foot on the floor stays
where it was traced.

    python tools/balance_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--arrays a.npz] [--r-bal 0.6]
                                  [--acc-max 1.0] [--lead 0.15] [--lag 0.05] [--drop-max 2.0] [--dip-deg 15] [--no-dip]
                                  [--mmd-ik tools/leg_ik.py]

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
   Two kinds of run are not pulled (the review of 2026-10-14):
     hover: the other foot never gets CLEAR_CM up.  The trace's feet hover 0.4-4 cm on two feet too (a05), so this is
       no evidence of standing on one foot, and the MV shows no lifted foot (the body slid sideways for no seen reason).
     transfer: a step onto the next foot.  At the run's middle the COM moves towards where the other foot lands at
       TRANSFER_V and more, its extrapolated centre of mass (XcoM = COM + v / w, Hof et al. 2005) past half the way
       there: the body falls onto the next foot, which catches it (the foot goes beyond the XcoM, Hof 2008); holding
       it over the foot it leaves would reverse that fall.
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
     (b) every foot IK's target within its leg's reach less REACH_TOL_CM (1.5 cm) after the hips move (or no farther
         than it already was), the hips allowed down for it: a leg at its reach stays straight (the hip goes round the
         ankle), so the drop for one leg is bounded by what bends the other leg, if it is on the floor, KNEE_GIVE_DEG
         more (at most --drop-max).  The 1.5 cm: MMD's IK (saba's solve; the feet layer's tools/leg_ik.py) leaves a foot
         on the floor more than 4 mm short of its target on most frames of the v7 dance with under 1 cm of two-bone
         slack, on 2-3 % with 1.5-4 cm.
     (c) each hip's adduction (the hip-to-ankle line out of 下半身's sagittal plane) under the reference range's upper
         proposal (22 degrees; stage 3 research: the Japanese reference 20) and its abduction under 45, or no farther
         than in the dance; each knee under 159 degrees (the upper proposal; the hip kept as far from the foot IK's
         target as the two-bone leg is at 159, or no nearer than it was), a lifted leg's also under the dance's + 5
         (LIFT_FOLD_DEG: where the carry has not come in yet, as in a kick up in 0.2 s, its shape is kept so).
     (d) never pointing away from the nearest pull: a minimum-jerk smoother rings about 5 % before and after a step;
         people do not move the COM the wrong way before a weight shift (the centre of pressure goes that way, not
         the COM).
   A lifted foot goes with the body (the carry, 6.): its leg's bounds act on (1 - carry) of the shift.
   Solved by ADMM (Boyd et al. 2011): one banded solve per round with a fixed matrix, the bounds projected per frame
   (Dykstra's projection for the intersection), tightened by SET_MARGIN (1 mm); the solve's smooth curve is then
   scaled down where it is still out of a bound by a smooth cover of what it lacks (the bounds are convex and hold 0;
   no per-frame fix, which folded the curve where a bound starts to act).  Moving センター translates the trunk and the
   head without turning them: the dancers' "translation strategy in the pelvis" (Krasnow et al. 2011; the trunk kept
   vertical, Mouchnino et al. 1991), against the naive "inclination strategy".
4. The hips then go down as far as the legs need to reach (the least smooth drop: the same solver, |y''| <= DROP_ACC_MAX,
   raised by the same smooth cover where the solve left it short).
5. Landings (--dip-deg, --no-dip): a foot that lands after a swing (a05: off the floor 4 frames, up 1.6 cm) and then
   takes the weight (the other foot lifts within DIP_WINDOW, or was already up) bends its knee by --dip-deg by DIP_PEAK
   and comes back by DIP_END (walking: 1-3 degrees at contact, 17 at 0.13 s; Winter 2009 Table A.1, a woman of 156 cm):
   the hips go down by what the two-bone leg needs for that bend, at most DIP_MAX_CM, only as far as the dance does not
   already bend the knee there (measured on the body already moved and dropped by 4., so the two add up).  A tap (the
   foot lands and lifts again while the other stays down) is left alone.
6. The carry: a lifted foot's IK moves on the floor plane by carry times センター's floor shift, so the lifted leg keeps
   the dance's shape against the pelvis (left in the world, a heel kicked up behind folded the knee to 164 degrees at
   195 s).  carry is 0 while the foot supports, 1 from CLEAR_CM up (smoothstep between), smoothed under itself over
   +-CARRY_HALF frames: 0 on every frame the foot supports, and it changes over about 0.4 s.  Its height and its turn
   are the dance's (the feet layer's).

Written: センター, a key on every frame (linear), its rotation as the dance had it; each carried foot IK, per-frame linear
keys from the last key before each carried span to the first key after it (its own interpolated value plus the carry on
the floor plane, its rotation as the dance had it).  Every other bone and key, every morph and the rest of the file are
the dance's own bytes; when nothing is to be done the dance comes back unchanged.

Report (--report; in short on stdout): a05_lateral_cm (the analysis's measure: in single support with the other foot
5 cm up and the standing foot on the floor, the COM's sideways distance from the standing foot's centre along 下半身's
side axis, + towards the lifted foot, before and after; after_holds: in single-support runs of 0.5 s and more), runs
(each single-support run: when, which foot, how high the other, its kind (pulled, hover, transfer), its need_share, the
distance to the sole's line before and after and the intended one, how far short and why: reach, hip range or
acceleration), centre (the shift, its 1-frame step, the added accelerations and the pressure move they need, the drop
and the dip), apa (how much of the shift is done when the foot lifts, and when it starts), reach (frames whose IK target
is out of the leg's reach, before and after; frames whose slack the layer took under REACH_TOL_CM), knee (flexion on the
floor, before and after; over 159 degrees), hip (adduction against the reference range, before and after), landings (the
knee's bend within 0.13 s after a landing, before and after), feet_carry (per foot: frames carried, the largest move, on
the floor 0), mmd_ik (with --mmd-ik: the new misses per round, what is left, the frames held back, the solver's md5),
untouched (the other bones' bytes), solver.
--arrays writes the per-frame curves (the shift, the COM before and after, the pull, the drop, the dip, the knees, the
carry, ...).
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
STILL_V_CM_S = 5.0              # cm/s: single support whose pelvis moves slower than this on the floor for STILL_MIN_S is
STILL_MIN_S = 0.3               # still, and pulled over the foot; elsewhere it moves (the human baseline's COM: v / w0 < 1.5 cm, a
                                # third of the foot's half width, so the XcoM stands within 1.5 cm of the COM; 0.3 s is about
                                # 1 / w0, the fall's time constant).  Human dancers standing still keep the COM 1.7 cm from
                                # the support's centre (FineDance; v8 3.4); moving, 8.0 cm [7.0, 9.4] (v8, which pulled every
                                # single support onto the foot, 5.9)
STILL_LEAD_S = 0.6              # a still stretch that starts inside its run is pulled from this long before it: carrying the
                                # body 9 cm at ACC_MAX (up, then down) takes 2 sqrt(0.09 / 1) = 0.6 s
SUPPORT_R_CM = 4.0              # a05's support of a foot: the capsule of this radius about the line from the heel point
                                # (ankle - 0.3 (toe - ankle)) to the toe; its centre half way
MOS_ML_MIN_CM = -4.2            # moving single support: the XcoM's sideways margin (SUPPORT_R_CM less the XcoM's sideways
                                # offset from the support's centre, towards the lifted foot along 下半身's side axis) kept at
                                # least this, human dancers' median (-4.2 [-6.1, -3.6]; v7 -8.9, v8 -5.4).  The median, not
                                # the lower quartile: the steps that fall onto the next foot (transfer) stay free and are a
                                # sixth of the moving frames at -19 cm, so with -6.1 the song's moving frames came to -6.9
                                # (COM 10.5 cm), outside the human quartiles
STANCE_WEIGHT = 30.0            # the pull on the XcoM to that bound where the dance is past it (as CATCH_WEIGHT)
# ---- the shift ---------------------------------------------------------------------------------------------------
ACC_MAX = 1.0                   # m/s^2 of added COM acceleration (about 9 cm of centre-of-pressure move)
TAU_S = 0.1                     # the minimum-jerk smoothness's time scale
LAM_IN = 0.02                   # the pull back to the dance where the pull is (relative to a full pull)
LAM_OUT = 0.5                   # and elsewhere: keeps a brief step's lean short (it does not start a second early)
DROP_MAX_CM = 2.0               # the hips may go down this far for the legs to reach
DROP_ACC_MAX = 0.5              # m/s^2: the drop's own acceleration (a slow give of the knees)
DROP_INSIDE_CM = 0.01           # the drop for the legs' reach aims this much inside REACH_TOL_CM
REACH_TOL_CM = 1.5              # a leg keeps this much slack, or as much as it had: MMD's IK (saba's solve, the feet
                                # layer's tools/leg_ik.py) leaves a foot on the floor more than 4 mm short of its IK
                                # target in 70-100 % of the v7 frames with under 1 cm of two-bone slack, 22-26 % at
                                # 1-1.5 cm, 2-3 % at 1.5-4 cm (the review's measure, NOTES 10/14)
ADMM_ITERS = 2000                # at most; it stops when the residuals are under the tolerances (v7: about 1,650)
ADMM_TOL_ACC = 0.02             # m/s^2
ADMM_TOL_REACH = 0.05           # cm
SET_MARGIN = 0.001              # m: the bounds are solved this much tighter, so the converged curve is inside the true ones
REACH_NO_WORSE_M = 0.0005       # m: "no worse than the dance" bounds allow this much, so the dance itself (no shift) is
RANGE_NO_WORSE_M = 0.002        # inside them, not on their edge (on the edge, the smallest miss of the solve could only be
RANGE_LINEAR_DEG = 0.5          # degrees: the thigh's range is solved this much inside (its linear bound missed by up to 0.3
                                # degrees where the shift turns the thigh 8 degrees, 195 s of the MV)
RANGE_NO_WORSE_DEG = 0.2        # undone by no shift at all).  A leg already past its reach: 0.5 mm (under the 1 mm of a
                                # new IK miss); a knee past 159 degrees: 2 mm along the hip-to-ankle line; a hip already
                                # past its range: 0.2 degrees of the thigh, more than the solve's miss (1.1 mm after 800
                                # rounds on v7)
FIX_HALF = 9                    # frames: the half-width of the smooth cover that brings an unconverged curve inside
# ---- the catch: a foot that lands catches the body (the extrapolated centre of mass, Hof et al. 2005, Hof 2008) ----
SOLE_HALF_W_CM = 4.65           # half the sole's width (young Japanese women's foot width 93.2 mm, AIST 1997-98)
CATCH_MARGIN_CM = 1.0           # at a landing the margin of stability (the landing foot's outer edge along the step minus
                                # the XcoM) is kept at least this: a step onto a foot placed beyond the XcoM (Hof 2008)
                                # needs >= 0; the 1 cm is for what the linear bound does not see (the knees solved again,
                                # the carried foot, the height bound): with 0 the MV kept 4 landings at -0.1 to -0.5 cm
CATCH_WEIGHT = 30.0             # the pull on the XcoM at a landing the dance does not catch (against LAM_OUT 0.5 per frame)
CATCH_FREE_S = 0.2              # the "never away from the nearest pull" half-plane is off this long after such a landing
XI_RHO = 1.0                    # the catch block's ADMM penalty relative to the per-frame sets' (convergence only)
IK_ROUNDS = 6                   # with MMD's IK at hand: the rounds of holding back where it would newly fall short
IK_MISS = 0.05                  # units (4 mm, a05's contact): an ankle this far from its foot IK's target misses it
IK_WORSE = 0.0125               # units (1 mm): and this much farther than in the dance: a new miss (the review's)
IK_HALF = 2                     # frames on each side of a new miss whose shift and dips are halved in a round
KEPT_MIN = 0.02                 # a foot carried 98 % and more: its leg sets no bound on the shift
FREE_M = 1.0e3                  # m: the radius (or slab side) of a bound that does not bound
CARRY_HALF = 6                  # frames: the half-width of the carry's smoothing (it changes over about 0.4 s)
# ---- the vertical: the pelvis never goes down faster than DOWN_ACC_MAX -------------------------------------------
G_MMD = 98.0                    # units/s^2: MMD's gravity as saba, three.js, MMDAgent-EX and babylon-mmd all have it (9.8 x
                                # 10; MMD's own default is not documented; the skirt research, question 4)
DOWN_ACC_MAX = 122.0            # units/s^2: the pelvis's downward acceleration, the dance's and the layer's together, at
                                # most this: the real g at 8 cm a unit (122.5).  A body the floor holds up cannot fall
                                # faster than gravity; human dancers' largest is 142 (a sequence's median, the human
                                # baseline), so this keeps the dance's bounces and jumps (78, for a skirt without its
                                # ceiling, made 38 dips on the beat shallower than 0.8 of the dance's and 15 jump tops 2 cm
                                # lower: the review of 2026-10-16).  The skirt keeps the underwear hidden by its ceiling
                                # (tools/pmx_skirt.py --ceiling 70, on main); --down-acc-max sets another bound
# ---- the centre's 1-frame spikes (a08) ---------------------------------------------------------------------------
SPIKE_T = 0.15                  # m/s: a step of センター's path whose speed is above (or below) both neighbours' by more than
                                # this is a 1-frame spike, a jolt or a hitch (a08: s2_spectrum.spikes, T_SPIKE of センター)
SPIKE_PER_MIN = 7.2             # left at most, a minute, the largest taken first: human dancers have 7.2 [2.9, 10.9] (the
                                # human baseline, FineDance K-pop / choreography / jazz, 62 sequences); the traced dance 49
SPIKE_KINK_SHARE = 0.95         # around a spike taken the path's kinks at most this share of SPIKE_T (the speed changes no
                                # more than the velocity does: |s(k) - s(k-1)| <= |v(k) - v(k-1)|)
DESPIKE_XZ_CM = 0.5             # a despiked frame moves at most this far on the floor (the legs' reach is solved before it)
DESPIKE_DOWN_CM = 1.5           # and at most this far down
DESPIKE_UP_CM = 0.75            # and up (and never past the legs' reach).  On the MV (on what the vertical fix leaves, 161
                                # spikes): 1 / 0.5 / 0.3 cm leave 47 (10.9 a minute), 1.5 / 0.75 / 0.5 leave 38 (8.8), 2 / 1 /
                                # 0.5 leave 40: what is left are the deepest bounces' one-frame turns
DESPIKE_SOFT = 100.0            # the kink bound's weight (against 1 for the change): where the box cannot meet it, smaller
DESPIKE_HALF = 10               # frames each side of a bounded kink that may move with it
DESPIKE_ROUNDS = 8
DESPIKE_ITERS = 1500
# ---- the landings ------------------------------------------------------------------------------------------------
DIP_DEG = 15.0                  # the knee's extra bend on a landing that takes the weight, from the heel (walking: 1-3 ->
DIP_PEAK_S = 0.13               # 17 degrees at 0.129 s after contact; Winter 2009 Table A.1, a woman of 156 cm)
DIP_DEG_FLAT = 12.0             # the foot flat (level walking 6 -> 18 degrees at 14 % of the cycle; De Pieri et al. 2022)
DIP_DEG_FORE = 9.0              # from the forefoot: the knee is already bent and the ankle takes more (toe walking 22 -> 30
                                # degrees, the ankle 11 degrees up, De Pieri et al. 2022; the weight acceptance of stair
                                # descent, about 0.13 s, 6 -> 15 degrees, the ankle 32, Markstrom et al. 2022; figures read)
PITCH_KIND_DEG = 4.0            # the toe-IK-to-ankle-IK line pitched this much from its rest: forefoot / heel first (the feet
                                # layer's HEEL_UP_DEG)
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
KNEE_MIN_DEG = 5.0              # a leg on the floor keeps its knee bent at least this much (the two-bone knee from the hip to
                                # the foot IK's target, a05's measure): human dancers never stand on a straighter knee (0 % of
                                # the frames on the floor, FineDance; the human baseline of 2026-10-15), the traced dance does
                                # on 6-8 % (where it puts the standing foot's target out of the leg's reach, and MMD leaves the
                                # foot short of it).  The hips go down for it within the drop's allowance
LIFT_FOLD_DEG = 5.0             # a lifted leg's knee folds at most this much past the dance's (195 s of the MV: the heel
                                # kicked up behind from 3 to 60 cm in 0.2 s, faster than the carry comes in; 150 -> 156)

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
            "dip_deg": DIP_DEG, "dip": False, "tau_s": TAU_S, "lam_in": LAM_IN, "lam_out": LAM_OUT, "clear_cm": CLEAR_CM,
            "catch": True, "vertical": True, "dip_deg_flat": DIP_DEG_FLAT, "dip_deg_fore": DIP_DEG_FORE,
            "down_acc_max": DOWN_ACC_MAX, "despike": True, "spike_per_min": SPIKE_PER_MIN, "pull_moving": False,
            "mos_ml_min_cm": MOS_ML_MIN_CM, "still_v_cm_s": STILL_V_CM_S, "still_min_s": STILL_MIN_S}


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


def xi_op(x, c):
    """the XcoM's part of a shift x [F, n] at the frames 1 .. F-2: x(t) + c (x(t+1) - x(t-1)) (c = FPS / (2 w0): the
    position plus the velocity over w0, by central differences)"""
    return x[1:-1] + c * (x[2:] - x[:-2])


def xi_op_t(z, c, F):
    """the adjoint of xi_op: z [F-2, n] -> [F, n]"""
    out = np.zeros((F,) + z.shape[1:])
    out[1:-1] += z
    out[2:] += c * z
    out[:-2] -= c * z
    return out


def admm(w, d, lam, project, acc_max, tau_s, iters=None, tol_x_cm=ADMM_TOL_REACH, gain=None, warm=None, xi=None):
    """x [F, n] (metres): min 1/2 sum w |g x - d|^2 + 1/2 sum lam |x|^2 + mu/2 |x'''|^2 (+ 1/2 sum xi_w |g Xi x - xi_e|^2)
    subject to |x''| <= acc_max (per frame), x = project(x) (a per-frame set, given by its projection) and, with xi,
    Xi x = xi_project(Xi x) on the rows xi_mask (Xi = xi_op: the XcoM's part of the shift; per-row sets); g = gain per
    frame (1).  ADMM (Boyd et al. 2011, over-relaxed 1.6) on the splitting [x'' ; x ; Xi x] = [za ; zx ; zc]: the
    x-step is one banded solve with a fixed matrix.  xi: {"c", "mask" [F-2] bool, "project" (per row on [F-2, n]),
    "w" [F-2], "e" [F-2, n]} or None.  warm: the state of an earlier solve of a nearby problem (info["_state"])."""
    iters = ADMM_ITERS if iters is None else iters
    F, n = d.shape
    lam = np.broadcast_to(np.asarray(lam, dtype=np.float64), (F,))
    g = np.ones(F) if gain is None else np.asarray(gain, dtype=np.float64)
    tf = tau_s * FPS
    scale = 1.0 + float(np.median(lam))
    mu = scale * tf ** 6
    rho = 1.0 if warm is None else warm["rho"]          # all blocks' penalties scale together (residual balancing)
    if xi is not None:
        c = float(xi["c"])
        xmask = np.asarray(xi["mask"], dtype=bool)
        gm = g[1:-1]
        xw = np.asarray(xi["w"], dtype=np.float64) * gm * gm
        xi_unit = XI_RHO                                 # the catch block's penalty against the others'
        stencil_xi = (-c, 1.0, c)

    def factor(r):
        stencils = [(mu, D3_STENCIL), (r * scale * tf ** 4, D2_STENCIL)]
        if xi is not None:
            stencils.append((xw + r * scale * xi_unit * xmask, stencil_xi))
        return band_factor(band_terms(F, w * g * g + lam + r * scale, stencils))
    L = factor(rho)
    amax = acc_max * DT * DT
    q = (w * g)[:, None] * d
    if xi is not None:
        q = q + xi_op_t((np.asarray(xi["w"], dtype=np.float64) * gm)[:, None] * np.asarray(xi["e"], dtype=np.float64), c, F)
    if warm is None:
        za = np.zeros((F - 2, n))
        ua = np.zeros_like(za)
        zx = project(np.zeros((F, n)))
        ux = np.zeros_like(zx)
        zc = np.zeros((F - 2, n)) if xi is None else xi["project"](np.zeros((F - 2, n)))
        uc = np.zeros((F - 2, n))
    else:
        za, ua, zx, ux = (warm[k].copy() for k in ("za", "ua", "zx", "ux"))
        zc = warm["zc"].copy() if "zc" in warm and xi is not None else (
            np.zeros((F - 2, n)) if xi is None else xi["project"](np.zeros((F - 2, n))))
        uc = warm["uc"].copy() if "uc" in warm and xi is not None else np.zeros((F - 2, n))
    alpha = 1.6
    res_a = res_x = res_c = None
    it = 0
    x = zx
    zx_seen = zx
    rescaled = 0
    for it in range(1, iters + 1):
        rho_a, rho_x = rho * scale * tf ** 4, rho * scale
        rhs = q + rho_a * d2t(za - ua, F) + rho_x * (zx - ux)
        if xi is not None:
            rhs = rhs + xi_op_t((rho * scale * xi_unit * xmask)[:, None] * (zc - uc), c, F)
        x = band_solve(L, rhs)
        ax = d2(x)
        ah = alpha * ax + (1.0 - alpha) * za
        va = ah + ua
        na = np.linalg.norm(va, axis=1)
        za = va * np.minimum(1.0, amax / np.maximum(na, 1e-18))[:, None]
        ua = va - za
        xh = alpha * x + (1.0 - alpha) * zx
        zx = project(xh + ux)
        ux = xh + ux - zx
        if xi is not None:
            cx = xi_op(x, c)
            ch = alpha * cx + (1.0 - alpha) * zc
            zc = np.where(xmask[:, None], xi["project"](ch + uc), ch + uc)
            uc = np.where(xmask[:, None], ch + uc - zc, 0.0)
        if it % 10 == 0:
            res_a = float(np.linalg.norm(ax - za, axis=1).max()) / (DT * DT)
            res_x = float(np.linalg.norm(x - zx, axis=1).max()) * 100.0
            res_c = 0.0 if xi is None or not xmask.any() else float(np.linalg.norm((cx - zc)[xmask], axis=1).max()) * 100.0
            if res_a < ADMM_TOL_ACC and res_x < tol_x_cm and res_c < tol_x_cm:
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
                uc /= k
                L = factor(rho)
                rescaled += 1
    # x itself (the banded solve's smooth curve), not its per-frame projection: putting each frame back into its set on
    # its own folds the curve where a bound starts to act (the review: 59.23 s, 3.57 m/s^2).  The callers solve with
    # bounds tightened by SET_MARGIN and bring x into the true bounds by a smooth cover (smooth_cover)
    info = {"iterations": it, "residual_acc_m_s2": None if res_a is None else round(res_a, 4),
            "residual_set_cm": None if res_x is None else round(res_x, 4),
            "residual_catch_cm": None if res_c is None else round(res_c, 4), "rho": rho,
            "_state": {"za": za, "ua": ua, "zx": zx, "ux": ux, "zc": zc, "uc": uc, "rho": rho}}
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


def solve_shift(w, d, gain, discs, slabs, acc_max, tau_s, lam_in, lam_out, iters=None, warm=None, catches=None):
    """センター's floor shift y [F, 2] (metres): the COM's shift gain * y pulled to d where w > 0 (held back by lam_in
    there, by lam_out elsewhere), minimum jerk, |y''| <= acc_max, y in every disc of `discs` [(centres [F, 2], radii
    [F])] and every slab of `slabs` [(m [F, 2], lo [F], hi [F])], never pointing away from the nearest pull.
    catches (catch_terms()): at each landing frame L the XcoM's shift gain_L (Xi y)_L along the step u_L at most hi_L
    (the landing foot still catches the body), and where the dance does not catch it, (Xi y)_L pulled to e_L"""
    F = len(w)
    has_catch = catches is not None and (np.any(catches["mask"]) or np.any(catches["w"] > 0))
    if F < 5 or (not np.any(w > 0) and not (catches is not None and np.any(catches["w"] > 0))):
        return np.zeros((F, 2)), {"iterations": 0}
    toward = toward_targets(d, int(round(1.5 * FPS)))
    if has_catch:
        toward[catches["free"]] = 0.0                   # a landing pulled back: the pull's direction is the catch's
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
    xi = None
    if has_catch:
        nrm, hi_c = catches["n"], catches["hi"]
        nn = np.linalg.norm(nrm, axis=1)
        # tightened as the other bounds; one that holds 0 (the dance catches) keeps holding it
        hi_t = np.where(hi_c >= 0.0, np.maximum(hi_c - SET_MARGIN * nn, 0.0), hi_c - SET_MARGIN * nn)

        def xi_project(v):
            s = np.sum(v * nrm, axis=1)
            over = np.maximum(s - hi_t, 0.0)
            return v - (over / np.maximum(nn * nn, 1e-18))[:, None] * nrm
        xi = {"c": catches["c"], "mask": catches["mask"], "project": xi_project, "w": catches["w"], "e": catches["e"]}
    y, info = admm(w, d, lam, project, acc_max, tau_s, iters, gain=gain, warm=warm, xi=xi)
    # into the true bounds: the shift scaled down by a smooth cover of what each frame lacks (the bounds hold 0 and are
    # convex, so a frame scaled under its own largest scale is inside; scaling keeps the direction, so the half-plane).
    # A catch bound reads three frames: the scale it asks for is put on its landing frame, where the cover is flat
    # (the running maximum over +-FIX_HALF), and checked again
    scale = np.ones(F)
    for c, r in discs:
        scale = np.minimum(scale, disc_scale(y, c, r))
    for m, lo, hi in slabs:
        scale = np.minimum(scale, slab_scale(y, m, lo, hi))
    cut = np.clip(smooth_cover(1.0 - scale, FIX_HALF), 0.0, 1.0)
    out = (1.0 - cut)[:, None] * y
    if has_catch:
        rows = np.flatnonzero(catches["mask"] & (catches["hi"] >= 0.0))     # a held-back landing needs the shift
        for _ in range(6):
            s = np.sum(xi_op(out, catches["c"])[rows] * catches["n"][rows], axis=1)
            hi_r = catches["hi"][rows]
            bad = s > hi_r + 1e-6
            if not bad.any():
                break
            need = np.zeros(F)
            need[rows[bad] + 1] = 1.0 - np.clip(np.maximum(hi_r[bad], 0.0) / s[bad], 0.0, 1.0)
            more = np.clip(smooth_cover(need, FIX_HALF), 0.0, 1.0)
            cut = 1.0 - (1.0 - cut) * (1.0 - more)
            out = (1.0 - cut)[:, None] * y
    info["bound_cut_max"] = round(float(cut.max()), 5)
    info["_cut"] = cut                                  # per frame (the layer moves it to its arrays)
    info["_raw"] = y
    return out, info


def solve_drop(need, acc_max, tau_s, iters=None, cap=None):
    """the hips' drop y [F] (metres), never under `need` (metres; 0 where nothing is needed) and, with `cap` [F], never
    over max(cap, need) (the most the other leg on the floor may bend; the smooth curve otherwise rounds over it between
    two needs): the least smooth curve (minimum jerk, |y''| <= acc_max)"""
    F = len(need)
    if F < 5 or not np.any(need > 0):
        return np.zeros(F), {"iterations": 0}
    lo = need[:, None]              # not tightened: a straight leg bends degrees for a millimetre more of drop
    hi = np.full((F, 1), np.inf) if cap is None else np.maximum(cap, need)[:, None]
    y, info = admm(np.zeros(F), np.zeros((F, 1)), 1.0, lambda v: np.clip(v, lo, hi), acc_max, tau_s, iters,
                   tol_x_cm=0.01)
    info.pop("_state", None)
    y = y[:, 0]
    raise_ = smooth_cover(np.maximum(need - y, 0.0), FIX_HALF)      # up to the need where the solve left it short
    info["need_raise_cm_max"] = round(float(raise_.max()) * 100.0, 4)
    return np.minimum(y + raise_, hi[:, 0]), info


# ---- the plan ---------------------------------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    arrays: dict = None         # per-frame curves (units unless named): shift [F, 3], com_before, com_after, pull, ...


def support_plan(body, p, com, low=None):
    """support (per foot), the single-support runs [(first, last, foot)], the pull's weight, its foot and the run's
    need_share per frame; `low` (per foot, units) the feet's lowest points to read the support off (the body's own when
    None: another motion's with --support-from).  In a run that is pulled, the frames where the dance's COM stands still
    (under STILL_V_CM_S for STILL_MIN_S) are pulled over the foot; the others (moving) are not pulled, their XcoM is held
    inside the human range instead (stance_terms); p["pull_moving"] pulls them all (the layer before 2026-10-15)"""
    F = body.F
    low = {s: body.height(s) for s in SIDES} if low is None else low
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
    # still where the pelvis or the COM stays slow (the COM moves with the leg that lifts, which a dancer standing still
    # does too, and alone would put the start of every single support among the moving frames; the pelvis alone misses
    # a still COM over hips that sway, 89.4 s of the MV)
    pel = 0.5 * (body.hip("左") + body.hip("右"))
    v_pel, vcom = np.zeros(F), np.zeros(F)
    if F >= 3:
        v_pel[1:-1] = np.linalg.norm(pel[2:, [0, 2]] - pel[:-2, [0, 2]], axis=1) * FPS / 2.0 * CM     # cm/s
        vcom[1:-1] = np.linalg.norm(com[2:, [0, 2]] - com[:-2, [0, 2]], axis=1) * FPS / 2.0 * CM
        for v in (v_pel, vcom):
            v[0], v[-1] = v[1], v[-2]
    min_still = max(1, int(round(p.get("still_min_s", STILL_MIN_S) * FPS)))
    still_lead = max(lead, int(round(STILL_LEAD_S * FPS)))
    still = np.zeros(F, bool)
    moving = np.zeros(F, bool)
    stance_foot = np.full(F, "", dtype=object)
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
        st = np.ones(b - a + 1, bool)
        if not p.get("pull_moving", False):
            st[:] = False
            for v in (v_pel, vcom):
                for r0, r1 in runs(v[a:b + 1] < p.get("still_v_cm_s", STILL_V_CM_S)):
                    if r1 - r0 + 1 >= min_still:
                        st[r0:r1 + 1] = True
        still[a:b + 1] |= st
        moving[a:b + 1] |= ~st
        stance_foot[a:b + 1] = s

        def put(t, v):
            if v > w[t]:
                w[t], foot[t], share[t] = v, s, need
        for r0, r1 in runs(st):                         # the pull on each still stretch, coming in before it
            pa, pb = a + r0, a + r1
            for t in range(pa, pb + 1):
                put(t, max(float(lift[s][t]), 0.5 * peak))
            # inside the run from STILL_LEAD_S before (the body must be over the foot when it stands still), before the
            # run's start --lead at most (the weight shift before the foot lifts)
            n_lead = lead if pa == a else min(still_lead, pa - a + lead)
            for j in range(1, n_lead + 1):
                t = pa - j
                if t <= prev_end or t < 0 or not sup[s][t]:
                    break
                put(t, peak * (1.0 - j / (n_lead + 1.0)))
            for j in range(1, lag + 1):
                t = pb + j
                if t >= next_start or t >= F or not sup[s][t]:
                    break
                put(t, peak * (1.0 - j / (lag + 1.0)))
    return {"low": low, "sup": sup, "single": single, "runs": ss, "w": w, "foot": foot, "share": share,
            "run_shares": shares, "run_kinds": kinds, "still": still, "moving": moving, "stance_foot": stance_foot,
            "vcom_cm_s": vcom}


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


def xcom(com):
    """the extrapolated centre of mass on the floor [F, 2] (units; Hof et al. 2005): the COM's floor point plus its
    velocity (central differences) over w0 = sqrt(g / the COM's height), and w0 [F] (1/s)"""
    F = len(com)
    v = np.zeros((F, 2))
    if F >= 3:
        v[1:-1] = (com[2:, [0, 2]] - com[:-2, [0, 2]]) * FPS / 2.0
        v[0], v[-1] = v[1], v[-2]
    w0 = np.sqrt(G / np.maximum(com[:, 1] * UNIT_M, 0.2))
    return com[:, [0, 2]] + v / w0[:, None], w0


def sole_reach(body, s, f, u, here):
    """how far (units) the sole of foot s at frame f reaches along u from `here` (its farthest corner: the heel-to-toe
    line widened by SOLE_HALF_W_CM on each side)"""
    heel, toe = body.sole(s)
    h, t = heel[f], toe[f]
    ax = t - h
    n = float(np.linalg.norm(ax))
    side = np.array([-ax[1], ax[0]]) / n * (SOLE_HALF_W_CM / CM) if n > 1e-9 else np.zeros(2)
    corners = np.array([h + side, h - side, t + side, t - side])
    return float(np.max((corners - here) @ u))


def landing_catches(body, com, plan):
    """the landings that end a single-support run (pulled or transfer; a hovering foot never really left the floor):
    per landing the frame (the other foot supports again), the stance and landing feet, the step's direction u on the
    floor (from the stance foot's centre to the landing foot's), the landing foot's outer edge along u, the XcoM along
    u and the margin of stability (edge - XcoM; Hof et al. 2005: the body is caught when it is >= 0)"""
    F = body.F
    xi, w0 = xcom(com)
    rows = []
    for i, ((a, b, s), kind) in enumerate(zip(plan["runs"], plan["run_kinds"])):
        if kind == "hover":
            continue
        o = "右" if s == "左" else "左"
        f = b + 1
        if f < 1 or f > F - 2 or not plan["sup"][o][f]:
            continue                                    # the song's end, or the stance foot left first (a hop)
        here = 0.5 * (body.ankle(s)[f] + body.toe(s)[f])[[0, 2]]
        there = 0.5 * (body.ankle(o)[f] + body.toe(o)[f])[[0, 2]]
        gap = float(np.linalg.norm(there - here))
        if gap < 1e-6:
            continue
        u = (there - here) / gap
        edge = sole_reach(body, o, f, u, here)
        along = float((xi[f] - here) @ u)
        rows.append({"run": i, "frame": f, "stance": s, "foot": o, "kind": kind, "u": u, "here": here, "edge": edge,
                     "xcom": along, "margin": edge - along, "w0": float(w0[f])})
    return rows


def catch_terms(F, catches, gain, run_starts, stance=None):
    """the catch's terms for solve_shift: per landing row (frame L, row L - 1 of xi_op) the half-plane
    gain_L u . (Xi y)_L <= margin - CATCH_MARGIN_CM (metres): where the dance catches the body it keeps catching it (the
    bound holds 0, the dance itself), where it does not the body is held back on the way until it does (the bound
    then needs a shift, and a pull of gain_L (Xi y)_L to (margin - CATCH_MARGIN_CM) u leads the solve there), with the
    "never away from the nearest pull" half-plane off from the run's start to CATCH_FREE_S after the landing.
    stance (stance_terms()): the moving single support's rows, the same kind of half-plane on the XcoM's sideways
    offset (a landing's row first where both fall on a frame)"""
    rows = F - 2
    w0s = [r["w0"] for r in catches] + ([] if stance is None else list(stance["w0"]))
    c = FPS / (2.0 * float(np.median(w0s))) if w0s else 1.0
    mask = np.zeros(rows, bool)
    n = np.zeros((rows, 2))
    hi = np.full(rows, FREE_M)
    w = np.zeros(rows)
    e = np.zeros((rows, 2))
    free = np.zeros(F, bool)
    for r in catches:
        k = r["frame"] - 1
        m = (r["margin"] * CM - CATCH_MARGIN_CM) / CM * UNIT_M                  # metres
        mask[k] = True
        n[k] = gain[r["frame"]] * r["u"]
        hi[k] = m
        if m < 0.0:
            w[k] = CATCH_WEIGHT
            e[k] = m * r["u"]
            free[max(0, run_starts[r["run"]]):min(F, r["frame"] + int(round(CATCH_FREE_S * FPS)) + 1)] = True
    if stance is not None:
        # where the dance keeps inside the bound it is a half-plane that holds 0 (it cannot make the problem harder);
        # where the dance is past it, a pull to it only: a hard bound there can ask the body to cross from one foot to
        # the other in two frames (feet 34 cm apart, the other foot lifting as the first one lands)
        ease = int(round(CATCH_FREE_S * FPS))
        for f, u, m in zip(stance["frames"], stance["u"], stance["hi"]):
            k = f - 1
            if mask[k] or w[k] > 0.0:
                continue
            n[k] = gain[f] * u
            if m < 0.0:
                w[k] = STANCE_WEIGHT
                e[k] = m * u
                free[max(0, f - ease):min(F, f + ease + 1)] = True
            else:
                mask[k] = True
                hi[k] = m
    return {"c": c, "mask": mask, "n": n, "hi": hi, "w": w, "e": e, "free": free}


def stance_lateral(body, com, foot):
    """per frame with a standing foot (foot[f] one of SIDES): the unit sideways direction towards the other foot
    (下半身's side axis, as a05) [F, 2], and the XcoM's and the COM's offsets along it from the standing foot's support
    centre (a05's capsule: the heel point ankle - 0.3 (toe - ankle) to the toe, half way), units; nan elsewhere"""
    F = body.F
    xi, w0 = xcom(com)
    fwd = body.facing()[:, [0, 2]]
    lat = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    A = {s: body.ankle(s)[:, [0, 2]] for s in SIDES}
    T = {s: body.toe(s)[:, [0, 2]] for s in SIDES}
    u = np.zeros((F, 2))
    X = np.full(F, np.nan)
    L = np.full(F, np.nan)
    foot = np.asarray(foot, dtype=object)
    for s, o in (("左", "右"), ("右", "左")):
        m = foot == s
        if not m.any():
            continue
        centre = 0.5 * ((A[s] - HEEL_BACK * (T[s] - A[s])) + T[s])
        sgn = np.sign(np.sum((0.5 * (A[o] + T[o]) - 0.5 * (A[s] + T[s])) * lat, axis=1))
        sgn[sgn == 0] = 1.0
        uu = lat * sgn[:, None]
        u[m] = uu[m]
        X[m] = np.sum((xi - centre) * uu, axis=1)[m]
        L[m] = np.sum((com[:, [0, 2]] - centre) * uu, axis=1)[m]
    return u, X, L, w0


def stance_terms(body, com, plan, mos_min_cm):
    """the moving single support's rows for solve_shift (merged by catch_terms): at each moving frame f of a pulled run
    the half-plane u_f . gain_f (Xi y)_f <= (SUPPORT_R_CM - mos_min_cm) - X_f (metres; X the dance's XcoM's sideways
    offset from the support's centre, u towards the lifted foot): the XcoM's sideways margin at least mos_min_cm.  Where
    the dance keeps inside it, it holds 0 (nothing to do); where it does not, the body is held back to it"""
    F = body.F
    frames = np.flatnonzero(plan["moving"] & (np.arange(F) >= 1) & (np.arange(F) <= F - 2))
    foot = np.where(plan["moving"], plan["stance_foot"], "")
    u, X, _, w0 = stance_lateral(body, com, foot)
    xhi = (SUPPORT_R_CM - mos_min_cm) / CM
    return {"frames": frames, "u": u[frames], "hi": (xhi - X[frames]) * UNIT_M, "w0": w0[frames], "x_hi": xhi}


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


def drop_allowance(body, plan, drop_max_cm, give_deg, actual=False, ref=None):
    """per leg and frame, how far (units) the hips may go down for that leg to reach its foot: the drop does not bend
    the leg it is for (that leg stays at its reach; the hip goes round the ankle), it bends the other leg if that one is
    on the floor, by at most give_deg more (a straight leg gives about 0.5 cm, one bent 40 degrees 2.9 cm); at most
    drop_max.  actual: count, for a leg whose target is out of reach, the way back into reach too (the standing knees'
    drop; the shift's reach bound keeps the plain one, which leaves the shift some room); ref: the body whose knees the
    give_deg is counted from (the dance's: the shift has bent the leg already)"""
    give = {}
    for s in SIDES:
        L1, L2 = body.legs_rest[s]
        if actual:
            # from where the hip is now (a target out of reach: first the way back into reach, which bends nothing)
            flex = (body if ref is None else ref).knee_flexion(s)
            bent = np.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * np.cos(np.radians(np.clip(flex + give_deg, 0.0, 180.0))))
            give[s] = np.where(plan["sup"][s], np.maximum(body.reach(s) - bent, 0.0), np.inf)
        else:
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
        R = np.maximum(body.leg_length(s) - REACH_TOL_CM / CM, np.linalg.norm(D, axis=1) + REACH_NO_WORSE_M / UNIT_M)
        r = np.sqrt(np.maximum(R * R - v2 * v2, 0.0))
        g = hip_share(carry, s, body.F)
        free = g < KEPT_MIN
        gg = np.maximum(g, KEPT_MIN)[:, None]
        centre = np.where(free[:, None], 0.0, D[:, [0, 2]] * UNIT_M / gg)
        radius = np.where(free, FREE_M, r * UNIT_M / gg[:, 0])
        discs.append((centre, radius))
    return discs


def thigh_sine(body, s):
    """sin of the hip's adduction [F]: the thigh (the hip to the knee the layer solves) out of 下半身's sagittal plane,
    + towards the other leg (Body.hip_adduction in degrees)"""
    thigh = body.knee(s) - body.hip(s)
    thigh /= np.maximum(np.linalg.norm(thigh, axis=1), 1e-9)[:, None]
    return np.clip(np.sum(thigh * body.medial(s), axis=1), -1.0, 1.0)


def range_slabs(body, carry=None):
    """per leg, the slab of センター floor shifts (metres) that keep the hip's adduction (the thigh out of 下半身's
    sagittal plane, towards the other leg: the hip to the knee as the layer solves the leg, as the report measures it)
    under HIP_ADDUCTION_DEG[1] and its abduction under HIP_ABDUCTION_DEG, or no farther than they were.  Linearized
    about the dance: the thigh's sine moved by 1 cm of センター along x and along z (the knee solved again, a carried
    foot going with the body), so the slab is J . y within the room left.  (The hip-to-ankle line, the earlier bound,
    is off the thigh where the knee points in: the thigh went to 24.7 degrees under it on the MV.)"""
    F = body.F
    sa = math.sin(math.radians(HIP_ADDUCTION_DEG[1] - RANGE_LINEAR_DEG))
    sb = math.sin(math.radians(HIP_ABDUCTION_DEG - RANGE_LINEAR_DEG))
    eps = math.sin(math.radians(RANGE_NO_WORSE_DEG))
    base = {s: thigh_sine(body, s) for s in SIDES}
    jac = {s: np.zeros((F, 2)) for s in SIDES}
    probe = 0.125                                       # units (1 cm)
    for j, axis in enumerate((0, 2)):
        sh = np.zeros((F, 3))
        sh[:, axis] = probe
        moved = body.moved(sh, carry)
        for s in SIDES:
            jac[s][:, j] = (thigh_sine(moved, s) - base[s]) / (probe * UNIT_M)   # per metre of shift
    slabs = []
    for s in SIDES:
        s0 = base[s]
        hi = np.maximum(sa, s0 + eps) - s0               # adduction: s0 + J . y <= max(sin 22, s0)
        lo = -np.maximum(sb, -s0 + eps) - s0             # abduction: s0 + J . y >= -max(sin 45, -s0)
        slabs.append((jac[s], lo, hi))
    return slabs


def knee_slabs(body, carry=None, low=None):
    """per leg, the half-plane of センター floor shifts (metres) that keep the hip at least as far from the IK target
    as the two-bone leg is at its knee limit, or no nearer than it was: (D - (1 - carry) y) . D / |D| >= that distance
    (linearized: |D'| >= D' . D / |D|).  The limit: KNEE_FLEXION_DEG[1] (159 degrees, the reference range's upper
    proposal); on a lifted leg also the dance's flexion + LIFT_FOLD_DEG (the carry keeps a lifted leg's shape once it
    is in; this keeps it while the carry is still coming in, as in a kick up from the floor in 0.2 s)"""
    slabs = []
    for s in SIDES:
        L1, L2 = body.legs_rest[s]
        flex0 = body.knee_flexion(s)
        lifted = (body.height(s) if low is None else low[s]) >= SUPPORT_H
        lim = np.where(lifted, np.minimum(KNEE_FLEXION_DEG[1], flex0 + LIFT_FOLD_DEG), KNEE_FLEXION_DEG[1])
        lim = np.maximum(lim, flex0)
        d_lim = np.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * np.cos(np.radians(lim)))
        D = body.ankle(s) - body.hip(s)
        n = np.maximum(np.linalg.norm(D, axis=1), 1e-9)
        u = D[:, [0, 2]] / n[:, None]
        hi = (n - np.minimum(n - RANGE_NO_WORSE_M / UNIT_M, d_lim)) * UNIT_M
        slabs.append((u * hip_share(carry, s, body.F)[:, None], np.full(body.F, -FREE_M), hi))
    return slabs


def knee_min_drop(body, plan, allowance):
    """the drop of the hips (units, per frame) that bends every leg in contact with the floor (its lowest point under
    CONTACT_EPS, 4 mm: a05's contact, the human baseline's) to KNEE_MIN_DEG (two-bone: the hip within that knee's
    hip-to-ankle distance of the foot IK's target), at most what the other leg allows (allowance)"""
    need = np.zeros(body.F)
    for s in SIDES:
        L1, L2 = body.legs_rest[s]
        dmin = math.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * math.cos(math.radians(KNEE_MIN_DEG + 0.5)))
        D = body.ankle(s) - body.hip(s)
        rh = np.linalg.norm(D[:, [0, 2]], axis=1)
        v = -D[:, 1]
        n = np.where(rh < dmin, v - np.sqrt(np.maximum(dmin * dmin - rh * rh, 0.0)), 0.0)
        n = np.where(plan["low"][s] < CONTACT_EPS, np.clip(n, 0.0, allowance[s]), 0.0)
        need = np.maximum(need, n)
    return need


def drop_needed(body, tol_cm=REACH_TOL_CM, before=None):
    """the least drop of the hips (units, per frame) for every IK target to be within its leg's reach (or no farther
    than in `before`), inf where no drop does it.  It aims DROP_INSIDE_CM inside the slack: the drop met it with equality,
    and the rounding put a frame of the MV 1e-9 over it"""
    need = np.zeros(body.F)
    for s in SIDES:
        D = body.ankle(s) - body.hip(s)
        R = body.leg_length(s) - (tol_cm + DROP_INSIDE_CM) / CM
        if before is not None:
            R = np.maximum(R, before.reach(s) + REACH_NO_WORSE_M / UNIT_M)   # as the reach discs allow
        rh = np.linalg.norm(D[:, [0, 2]], axis=1)
        v = -D[:, 1]
        ok = rh < R
        n = np.where(ok, v - np.sqrt(np.maximum(R * R - rh * rh, 0.0)), np.inf)
        need = np.maximum(need, n)
    return np.maximum(need, 0.0)


def down_acc(y):
    """the downward acceleration [F] (units/s^2, + down) of a height curve y [F] (units): its 30 fps second differences
    (0 on the first and the last frame)"""
    a = np.zeros(len(y))
    if len(y) >= 3:
        a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS * FPS
    return a


def lower_hull(g):
    """the lower convex hull of the points (t, g[t]) (t = 0 .. F-1), evaluated at every t"""
    g = np.asarray(g, dtype=np.float64)
    hull = []
    for t in range(len(g)):
        while len(hull) >= 2:
            a, b = hull[-2], hull[-1]
            if (g[b] - g[a]) * (t - a) >= (g[t] - g[a]) * (b - a):
                hull.pop()                              # b is not under the line from a to t
            else:
                break
        hull.append(t)
    return np.interp(np.arange(len(g)), hull, g[hull])


def vertical_fix(heights, cap=None):
    """the largest lowering z <= 0 [F] (units, added to every curve of `heights` [k, F]) after which none of them goes
    down faster than `cap` (units/s^2): the second differences must satisfy z'' >= b = (the largest of the curves'
    downward accelerations - cap) / FPS^2.  With B a curve whose second differences are b, z - B must be convex and
    under -B, so the largest such z is B + hull(-B), the lower convex hull: with g = -B, z = hull(g) - g.  Where the
    curves keep under the cap nothing changes; elsewhere the body goes down earlier and lower, along a stretch at the cap
    (a parabola) that leaves the dance and joins it again where g touches its hull: at the lowest points, which stay
    where and when they are (the arrival is not delayed; the fall starts earlier)"""
    cap = DOWN_ACC_MAX if cap is None else cap
    H = np.atleast_2d(np.asarray(heights, dtype=np.float64))
    F = H.shape[1]
    if F < 3:
        return np.zeros(F)
    a = np.max([down_acc(h) for h in H], axis=0)
    b = (a - cap) / (FPS * FPS)
    if not np.any(b[1:-1] > 0.0):
        return np.zeros(F)
    B = np.zeros(F)
    for t in range(1, F - 1):
        B[t + 1] = 2.0 * B[t] - B[t - 1] + b[t]
    g = -B
    z = lower_hull(g) - g
    return np.minimum(z, 0.0)


def despike_room(body, plan, before):
    """per frame (units): how far up and how far on the floor the despike may move the hips (body: as the layer has them
    now) before a leg on the floor reaches farther than REACH_TOL_CM short of its full length or, where the dance itself
    reaches farther, than the dance does (the reach report's bound).  The hip's distance to the target grows by u . e
    (u the unit from the target to the hip); split conservatively: half the room for the floor move, the rest upwards"""
    F = body.F
    up = np.full(F, DESPIKE_UP_CM / CM)
    xz = np.full(F, DESPIKE_XZ_CM / CM)
    for s in SIDES:
        D = body.hip(s) - body.ankle(s)
        dist = np.maximum(np.linalg.norm(D, axis=1), 1e-9)
        allow = np.maximum(body.leg_length(s) - REACH_TOL_CM / CM, before.reach(s) + REACH_NO_WORSE_M / UNIT_M) - 1e-4
        room = np.maximum(allow - dist, 0.0)
        u = D / dist[:, None]
        uh = np.linalg.norm(u[:, [0, 2]], axis=1)
        uy = np.maximum(u[:, 1], 1e-6)
        x_s = np.minimum(DESPIKE_XZ_CM / CM, 0.5 * room / np.maximum(uh, 1e-6))
        y_s = np.maximum(room - uh * x_s, 0.0) / uy
        sup = plan["sup"][s]
        xz = np.where(sup, np.minimum(xz, x_s), xz)
        up = np.where(sup, np.minimum(up, y_s), up)
    return up, xz


def despike_overreach(body, plan, before):
    """per frame: a leg on the floor reaches farther than the reach report allows (REACH_TOL_CM short of full length, or
    the dance's own reach where that is farther)"""
    over = np.zeros(body.F, bool)
    for s in SIDES:
        allow = np.maximum(body.leg_length(s) - REACH_TOL_CM / CM, before.reach(s) + REACH_NO_WORSE_M / UNIT_M)
        over |= body.reach(s) > allow
    return over


def speed_spikes(P):
    """a08's 1-frame spikes of a path P [F, 3] (units): the steps k (frame k -> k + 1) whose speed is above, or below,
    both neighbours' by more than SPIKE_T, and each one's excess over SPIKE_T (m/s)"""
    P = np.asarray(P, dtype=np.float64)
    if len(P) < 4:
        return np.zeros(0, dtype=int), np.zeros(0)
    s = np.linalg.norm(np.diff(P, axis=0), axis=1) * FPS * UNIT_M
    a, b = s[1:-1] - s[:-2], s[1:-1] - s[2:]
    hit = np.flatnonzero(((a > SPIKE_T) & (b > SPIKE_T)) | ((a < -SPIKE_T) & (b < -SPIKE_T)))
    return hit + 1, np.minimum(np.abs(a), np.abs(b))[hit] - SPIKE_T


def _windows(mask, half, lo, hi):
    """[(a, b)] the runs of mask widened by half each way, merged (two windows a frame apart share that frame's kink),
    inside [lo, hi]"""
    out = []
    for a, b in runs(mask):
        a, b = max(lo, a - half), min(hi, b + half)
        if out and a <= out[-1][1] + 2:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _despike_window(D2P, acc_lo, bound, a, b, r, y_lo, y_hi, xz, iters):
    """the least e [b - a + 1, 3] on the frames a..b (0 outside): the kinks of the frames a - 1 .. b + 1 that `bound`
    marks pulled into |P'' + e''| <= r (a soft bound, DESPIKE_SOFT: where the box below cannot meet it the kink is made
    smaller and left), every kink's downward part under the cap (acc_lo, hard), e_y in [y_lo, y_hi] and the floor move
    within xz (hard).  ADMM on [D e ; e] with D the window's second differences, a dense solve (a window is short)"""
    m = b - a + 1
    rows = np.arange(a - 1, b + 2)
    D = np.zeros((m + 2, m))
    for i, t in enumerate(rows):
        for j, c in ((t - 1, 1.0), (t, -2.0), (t + 1, 1.0)):
            if a <= j <= b:
                D[i, j - a] = c
    inner = (rows >= 1) & (rows <= len(D2P) - 2)
    rows_c = np.clip(rows, 0, len(D2P) - 1)
    base = D2P[rows_c]
    lo = np.where(inner, acc_lo[rows_c], -np.inf)
    ball = inner & bound[rows_c]
    keep = DESPIKE_SOFT / (DESPIKE_SOFT + 1.0)
    Minv = np.linalg.inv(2.0 * np.eye(m) + D.T @ D)
    z1, u1 = np.zeros((m + 2, 3)), np.zeros((m + 2, 3))
    z2, u2 = np.zeros((m, 3)), np.zeros((m, 3))
    for it in range(1, iters + 1):
        x = Minv @ (D.T @ (z1 - u1) + (z2 - u2))
        av = D @ x
        v = av + u1
        z1 = v.copy()
        w = base[ball] + v[ball]
        n = np.linalg.norm(w, axis=1)
        over = np.maximum(n - r, 0.0) / np.maximum(n, 1e-18)
        z1[ball] = v[ball] - (keep * over)[:, None] * w                # the prox of the kink's squared distance to r
        z1[:, 1] = np.maximum(z1[:, 1], lo)                            # the cap on the way down
        u1 = v - z1
        v2 = x + u2
        z2 = v2.copy()
        z2[:, 1] = np.clip(z2[:, 1], y_lo, y_hi)
        h = np.linalg.norm(z2[:, [0, 2]], axis=1)
        z2[:, [0, 2]] *= np.minimum(1.0, xz / np.maximum(h, 1e-18))[:, None]
        u2 = v2 - z2
        if it % 25 == 0 and max(float(np.abs(av - z1).max()), float(np.abs(x - z2).max())) < 2e-5:
            break
    return z2, it


def despike(P, heights, cap, per_min=SPIKE_PER_MIN, room_up=None, room_xz=None, iters=DESPIKE_ITERS):
    """the least change e [F, 3] (units) of センター's world path P [F, 3] that leaves at most per_min of its 1-frame
    spikes a minute (speed_spikes), the largest taken first, as far as small changes do it.  Around each spike taken the
    path's kinks on the step's two frames are pulled under SPIKE_KINK_SHARE SPIKE_T (the speed then changes less than
    SPIKE_T: the jolt, the hitch or the one-frame turn is spread over the frames round it); a frame goes down at most
    DESPIKE_DOWN_CM and up at most DESPIKE_UP_CM and room_up [F] (units: the legs' reach, despike_room), on the floor at
    most DESPIKE_XZ_CM and room_xz [F]; every curve of `heights` ([k, F], units: 下半身's and センター's, which move with it) still goes down no
    faster than `cap` (units/s^2).  Where that is not enough the spike is made smaller and left (the traced dance turns
    its deepest bounces round in one frame, up to 3 g: spreading those would reshape the bounce by centimetres).  Per
    window of DESPIKE_HALF frames round the kinks taken, ADMM (Boyd et al. 2011); in rounds"""
    P = np.asarray(P, dtype=np.float64)
    F = len(P)
    k0, _ = speed_spikes(P)
    keep = int(math.floor(per_min * F / FPS / 60.0 + 1e-9))
    info = {"before": int(len(k0)), "after": int(len(k0)), "keep": keep, "rounds": 0, "frames_bound": 0,
            "iterations": 0, "moved_cm_max": 0.0, "lowered_cm_max": 0.0, "raised_cm_max": 0.0}
    if F < 6 or len(k0) <= keep:
        return np.zeros((F, 3)), info
    r = SPIKE_KINK_SHARE * SPIKE_T / (FPS * UNIT_M)               # units per frame^2
    H = np.atleast_2d(np.asarray(heights, dtype=np.float64))
    acc_lo = np.full(F, -np.inf)
    acc_lo[1:-1] = np.max([-cap / (FPS * FPS) - d2(h) for h in H], axis=0)      # e_y'' at least this: the cap
    D2P = np.zeros((F, 3))
    D2P[1:-1] = d2(P)
    up = np.full(F, DESPIKE_UP_CM / CM) if room_up is None else np.clip(room_up, 0.0, DESPIKE_UP_CM / CM)
    y_lo = -DESPIKE_DOWN_CM / CM
    xz = np.full(F, DESPIKE_XZ_CM / CM) if room_xz is None else np.clip(room_xz, 0.0, DESPIKE_XZ_CM / CM)
    bound = np.zeros(F, bool)
    e = np.zeros((F, 3))
    for rnd in range(1, DESPIKE_ROUNDS + 1):
        k, ex = speed_spikes(P + e)
        if len(k) <= keep:
            break
        take = k[np.argsort(-ex, kind="stable")[:len(k) - keep]]
        new = np.zeros(F, bool)
        new[np.clip(take, 1, F - 2)] = True
        new[np.clip(take + 1, 1, F - 2)] = True
        if not np.any(new & ~bound):
            break                                       # what is left was taken already: as small as it gets
        bound |= new
        info["rounds"] = rnd
        e = np.zeros((F, 3))
        for a, b in _windows(bound, DESPIKE_HALF, 1, F - 2):
            e[a:b + 1], its = _despike_window(D2P, acc_lo, bound, a, b, r, y_lo, up[a:b + 1], xz[a:b + 1], iters)
            info["iterations"] = max(info["iterations"], its)
    info["after"] = int(len(speed_spikes(P + e)[0]))
    info["frames_bound"] = int(bound.sum())
    info["moved_cm_max"] = round(float(np.linalg.norm(e, axis=1).max()) * CM, 3)
    info["lowered_cm_max"] = round(float(max(0.0, -e[:, 1].min())) * CM, 3)
    info["raised_cm_max"] = round(float(max(0.0, e[:, 1].max())) * CM, 3)
    return e, info


def touchdowns(body, lows=None):
    """[(frame, foot)] of a05's touchdowns: on the floor again after GAP frames off it in which it rose SWING_MIN_H
    (the feet's heights `lows` per foot, the body's own when None)"""
    out = []
    for s in SIDES:
        low = body.height(s) if lows is None else lows[s]
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


def landing_kind(body, s, f):
    """how foot s comes down at frame f: 'fore' (toes down: the toe-IK-to-ankle-IK line pitched over PITCH_KIND_DEG from
    its rest, the heel up), 'heel' (toes up) or 'flat'"""
    d0 = body.rest[s + "つま先ＩＫ"] - body.rest[s + "足ＩＫ"]
    d = body.toe(s)[f] - body.ankle(s)[f]
    pitch = math.degrees(math.atan2(d[1], math.hypot(d[0], d[2]))) - math.degrees(math.atan2(d0[1], math.hypot(d0[0], d0[2])))
    return "fore" if pitch < -PITCH_KIND_DEG else ("heel" if pitch > PITCH_KIND_DEG else "flat")


def landing_dips(body, plan, p, cap=None):
    """the hips' drop (units, per frame) of the landings that take the weight, and the landings' list; cap [F] (0..1)
    scales each landing's depth by its least value over the landing's dip"""
    F = body.F
    other = {"左": "右", "右": "左"}
    window = int(round(DIP_WINDOW_S * FPS))
    peak_f, end_f = DIP_PEAK_S * FPS, DIP_END_S * FPS
    dip = np.zeros(F)
    rows = []
    for f, s in touchdowns(body, plan["low"]):
        o = other[s]
        lo = plan["low"]
        # takes the weight: the other foot is up at the landing or lifts within the window, before this foot lifts again
        b = min(F, f + window + 1)
        own_up = np.flatnonzero(lo[s][f:b] >= SUPPORT_H)
        own_end = f + int(own_up[0]) if len(own_up) else b
        takes = bool(np.any(lo[o][f:own_end] >= SUPPORT_H))
        kind = landing_kind(body, s, f)
        gain = {"fore": p.get("dip_deg_fore", DIP_DEG_FORE), "flat": p.get("dip_deg_flat", DIP_DEG_FLAT)}.get(kind, p["dip_deg"])
        row = {"frame": f, "s": round(f / FPS, 2), "foot": s, "takes_weight": takes, "depth_cm": 0.0, "kind": kind,
               "target_gain_deg": gain}
        if takes and p["dip"]:
            flex = body.knee_flexion(s)
            pk = min(F - 1, f + int(round(peak_f)))
            have = float(flex[f:pk + 1].max() - flex[f])
            target = min(float(flex[f]) + gain, KNEE_FLEXION_DEG[0])
            if target > float(flex[pk]) + 0.5 and have < gain - 0.5:
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
                    if cap is not None:
                        depth *= float(cap[f:min(F, f + int(math.ceil(end_f)) + 1)].min())
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

def layer(model, motion, params=None, log=None, ik_check=None, support_motion=None):
    """the dance with the weight on the standing foot (Result: motion, report, arrays).  ik_check: MMD's IK at hand, a
    function of a motion giving per side the distance (units, per frame) of the solved ankle from its foot IK's target
    (main() builds it from the feet layer's tools/leg_ik.py with --mmd-ik): the layer then solves its result again with
    it and, where a foot on the floor would newly fall short (over IK_MISS and IK_WORSE more than in the dance), halves
    its change around that frame and solves again, IK_ROUNDS times at most"""
    log = log or (lambda *_: None)
    p = params_default()
    p.update(params or {})
    t0 = time.time()
    body = Body(model, motion)
    F = body.F
    com0 = body.com()
    low = None
    if support_motion is not None:
        # which foot supports, read off another motion of the same dance (the feet layer's output: the feet layer puts
        # the feet on the floor, so its heights are the ones the picture shows)
        sb = Body(model, support_motion, frames=F)
        if fk.last_frame(support_motion) + 1 != F:
            raise ValueError("the support motion has %d frames, the dance %d" % (fk.last_frame(support_motion) + 1, F))
        low = {s: sb.height(s) for s in SIDES}
    plan = support_plan(body, p, com0, low=low)
    report = {"params": dict(p), "frames": F}
    plan.update({"r_bal_cm": p["r_bal_cm"], "acc_max": p["acc_max"]})
    w = plan["w"]
    allowance = drop_allowance(body, plan, p["drop_max_cm"], KNEE_GIVE_DEG)
    carry = {s: carry_factor(plan["low"][s], p) for s in SIDES}
    catches = landing_catches(body, com0, plan) if p.get("catch", True) else []
    stance = stance_terms(body, com0, plan, p["mos_ml_min_cm"]) if np.any(plan["moving"]) else None
    pulled = bool(np.any(w > 0)) or any(r["margin"] * CM < CATCH_MARGIN_CM for r in catches) or (
        stance is not None and bool(np.any(stance["hi"] < 0.0)))
    cterms = None
    if pulled:
        d = band_target(body, com0, plan, p["r_bal_cm"])
        k = com_response(body, com0, carry)
        discs = reach_discs(body, allowance, carry)
        slabs = range_slabs(body, carry)
        kslabs = knee_slabs(body, carry, plan["low"])
        if catches or stance is not None:
            cterms = catch_terms(F, catches, k, [a for a, _, _ in plan["runs"]], stance=stance)
    else:
        d, k = np.zeros((F, 2)), np.ones(F)
    radius = np.full(F, FREE_M)                         # the hold-back: |shift| under this (metres) per frame
    dip_cap = np.ones(F)                                # and the landings' dips scaled by this
    drop_hold = np.full(F, np.inf)                      # and the standing knees' drop under this (units)
    miss0 = ik_check(motion) if ik_check is not None else None
    ik_rows = []
    warm = None
    y = np.zeros((F, 2))
    for rnd in range(IK_ROUNDS + 1):
        x = np.zeros((F, 2))
        info = {"iterations": 0}
        cut = np.zeros(F)
        reach_tight = np.zeros(F, bool)
        range_tight = np.zeros(F, bool)
        knee_tight = np.zeros(F, bool)
        if pulled:
            held = radius < FREE_M
            hold = [(np.zeros((F, 2)), radius)] if held.any() else []
            log("solving the shift over %d frames (%d pull frames, %d held back)" % (F, int(np.sum(w > 0)), int(held.sum())))
            y, info = solve_shift(w, d, k, discs + hold, slabs + kslabs, p["acc_max"], p["tau_s"], p["lam_in"],
                                  p["lam_out"], warm=warm, catches=cterms)
            cut = info.pop("_cut", np.zeros(F))
            info.pop("_raw", None)
            warm = info.pop("_state", None)
            moving = np.linalg.norm(y, axis=1) > 1e-4
            edge = SET_MARGIN + 5e-4                    # the solve keeps SET_MARGIN inside the bounds
            for c, r in discs:                          # the shift stopped by a leg's reach: on its disc's edge
                reach_tight |= (np.linalg.norm(y - c, axis=1) > r - edge) & moving
            for group, tight in ((slabs, range_tight), (kslabs, knee_tight)):   # or by a hip's or knee's range
                for m, lo, hi in group:
                    s_ = np.sum(y * m, axis=1)
                    nm = np.linalg.norm(m, axis=1)
                    ok = nm > 1e-9
                    near = np.zeros(F, bool)
                    near[ok] = ((s_[ok] - lo[ok]) / nm[ok] < edge) | ((hi[ok] - s_[ok]) / nm[ok] < edge)
                    tight |= near & moving
            x = k[:, None] * y                          # the COM's shift (linearized), for the report
        plan["reach_tight"] = reach_tight
        plan["range_tight"] = range_tight
        plan["knee_tight"] = knee_tight
        shift = np.zeros((F, 3))
        shift[:, [0, 2]] = y / UNIT_M
        moved = body.moved(shift, carry)
        need = drop_needed(moved, before=body)
        # no standing knee straighter than KNEE_MIN_DEG, within what the other leg allows as the body now stands (the
        # shift onto a foot bends that leg already)
        allow_moved = drop_allowance(moved, plan, p["drop_max_cm"], KNEE_GIVE_DEG, actual=True, ref=body)
        # (held back where MMD's IK fell short: its solver bends a knee that starts nearly straight only so far, and the
        # drop bends the other standing knee too; the reach's own drop is never held back)
        need = np.maximum(need, np.minimum(knee_min_drop(moved, plan, allow_moved), drop_hold))
        finite = np.isfinite(need)
        allow_now = np.minimum(np.where(plan["sup"]["左"], allow_moved["左"], np.inf), np.where(plan["sup"]["右"], allow_moved["右"], np.inf))
        allow_now = np.minimum(allow_now, p["drop_max_cm"] / CM)          # the most the hips may go down on this frame
        allow_now = np.minimum(allow_now, drop_hold)
        need_m = np.where(finite, need, 0.0) * UNIT_M
        # and no deeper than the needs round about (a minimum-jerk curve between two needs rounds over both)
        drop, info["drop"] = solve_drop(need_m, DROP_ACC_MAX, p["tau_s"],
                                        cap=np.minimum(allow_now * UNIT_M, smooth_cover(need_m, FIX_HALF)))
        drop = drop / UNIT_M
        allow_any = np.maximum(allowance["左"], allowance["右"])
        drop_over = int(np.sum(need[finite] > allow_any[finite] + 1e-4))
        moved = body.moved(shift - np.stack([np.zeros(F), drop, np.zeros(F)], 1), carry)
        dip, landings = landing_dips(moved, plan, p, dip_cap)   # on the body already moved and dropped: they add up
        shift[:, 1] = -(drop + dip)
        # the pelvis and センター never go down faster than DOWN_ACC_MAX, the dance's motion and the layer's together:
        # lowered only, the lowest points kept (the layer moves both by the same height)
        vfix = vertical_fix([body.p(n)[:, 1] + shift[:, 1] for n in ("下半身", CENTRE)], cap=p["down_acc_max"]) \
            if p.get("vertical", True) else np.zeros(F)
        shift[:, 1] += vfix
        # センター's 1-frame jolts and hitches (a08's spikes) spread over the frames round them, down to the human count
        spikes, e_sp = None, np.zeros((F, 3))
        if p.get("despike", True):
            room_up, room_xz = despike_room(body.moved(shift, carry), plan, body)
            e_sp, spikes = despike(body.p(CENTRE) + shift, [body.p(n)[:, 1] + shift[:, 1] for n in ("下半身", CENTRE)],
                                   p["down_acc_max"], p["spike_per_min"], room_up=room_up, room_xz=room_xz)
            # the linear room is a guess: where a leg on the floor still reaches past its bound, the despike is taken
            # back there (scaled by a smooth cover of what is past, until none is)
            for _ in range(8):
                over = despike_overreach(body.moved(shift + e_sp, carry), plan, body) & \
                    np.any(np.abs(e_sp) > 0.0, axis=1)
                if not over.any():
                    break
                e_sp = e_sp * (1.0 - np.clip(smooth_cover(over.astype(float), 3), 0.0, 1.0))[:, None]
                e_sp[over] = 0.0
            shift += e_sp
            if p.get("vertical", True):
                # what the despike's solve left over the cap (it stops where the box cannot meet the kinks): lowered
                more = vertical_fix([body.p(n)[:, 1] + shift[:, 1] for n in ("下半身", CENTRE)], cap=p["down_acc_max"])
                shift[:, 1] += more
                vfix = vfix + more
        floor = shift.copy()
        floor[:, 1] = 0.0
        feet = {s: carry[s][:, None] * floor for s in SIDES}     # the carried feet's world move (units)
        if np.abs(shift).max() < 1e-6:
            out = motion
        else:
            out = write_centre(model, motion, body, shift)
            out = write_feet(out, body, feet)
        if ik_check is None:
            break
        miss1 = ik_check(out)
        new = np.zeros(F, bool)
        for s in SIDES:
            new |= plan["sup"][s] & (miss1[s] > IK_MISS) & (miss1[s] > miss0[s] + IK_WORSE)
        ik_rows.append({"round": rnd, "new_misses": int(new.sum()),
                        "frames": [round(f / FPS, 2) for f in np.flatnonzero(new)[:40]]})
        log("MMD's IK, round %d: %d new misses on the floor" % (rnd, int(new.sum())))
        if not new.any() or rnd == IK_ROUNDS:
            break
        near = np.zeros(F, bool)
        for f in np.flatnonzero(new):
            near[max(0, f - IK_HALF):f + IK_HALF + 1] = True
        radius[near] = np.minimum(radius[near], 0.5 * np.linalg.norm(y[near], axis=1))
        dip_cap[near] *= 0.5
        drop_hold[near] = np.minimum(drop_hold[near], 0.5 * drop[near])
    report["mmd_ik"] = {"checked": ik_check is not None, "rounds": len(ik_rows) - 1 if ik_rows else 0,
                        "per_round": ik_rows, "remaining": ik_rows[-1]["new_misses"] if ik_rows else None,
                        "held_back_frames": int(np.sum(radius < FREE_M)), "dip_capped_frames": int(np.sum(dip_cap < 1.0)),
                        "drop_held_frames": int(np.sum(np.isfinite(drop_hold)))}
    after = Body(model, out)
    report.update(measures(body, after, com0, plan, x, d, shift, drop, dip, landings, info, motion, out, drop_over,
                           unreachable=int(np.sum(~finite)), feet=feet, catches=catches, vfix=vfix,
                           bound=p["down_acc_max"], spikes=spikes, mos_min_cm=p["mos_ml_min_cm"], despike_e=e_sp))
    report["seconds"] = round(time.time() - t0, 2)
    foot_code = np.array([{"左": 1, "右": 2}.get(v, 0) for v in plan["foot"]], dtype=np.int8)
    arrays = {"shift": shift, "com_before": com0, "com_after": after.com(), "com_shift_m": x, "pull": w,
              "pull_foot": foot_code, "pull_target_m": d, "share": plan["share"], "com_response": k, "drop": drop,
              "dip": dip, "reach_tight": plan["reach_tight"], "range_tight": plan["range_tight"],
              "knee_tight": plan["knee_tight"], "bound_cut": cut,
              "drop_allowance_L": allowance["左"], "drop_allowance_R": allowance["右"],
              "low_L": plan["low"]["左"], "low_R": plan["low"]["右"], "carry_L": carry["左"], "carry_R": carry["右"],
              "foot_move_L": feet["左"], "foot_move_R": feet["右"], "vertical_fix": vfix, "drop_need": need,
              "despike": e_sp, "down_acc_pelvis_before": down_acc(body.p("下半身")[:, 1]),
              "down_acc_pelvis_after": down_acc(after.p("下半身")[:, 1])}
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


def catch_report(after, com1, catches):
    """the margins of stability at the landings (cm), before (the dance) and after (the same frames, feet and step
    direction, the moved body's XcoM)"""
    xi1, _ = xcom(com1)
    rows = []
    for r in catches:
        f = r["frame"]
        after_m = r["edge"] - float((xi1[f] - r["here"]) @ r["u"])
        rows.append({"frame": f, "s": round(f / FPS, 2), "stance": r["stance"], "kind": r["kind"],
                     "margin_cm": [round(r["margin"] * CM, 2), round(after_m * CM, 2)],
                     "held_back": bool(r["margin"] * CM < CATCH_MARGIN_CM)})
    b = np.array([r["margin_cm"][0] for r in rows])
    a = np.array([r["margin_cm"][1] for r in rows])
    summary = {"landings": len(rows), "before_under_0": int(np.sum(b < 0)), "after_under_0": int(np.sum(a < 0)),
               "newly_under_0": int(np.sum(a < np.minimum(b, 0.0) - 0.5)),
               "held_back": int(sum(r["held_back"] for r in rows)),
               "held_back_caught": int(sum(1 for r in rows if r["held_back"] and r["margin_cm"][1] >= -0.5)),
               "after_min_cm": round(float(a.min()), 2) if len(a) else None,
               "margin": "the landing foot's outer edge along the step minus the XcoM (COM + v / w0), cm; >= 0 caught"}
    return {"landings": rows, "summary": summary}


def vertical_report(before, after, vfix, bound=DOWN_ACC_MAX):
    """the pelvis's and センター's downward acceleration (units/s^2, 30 fps), the dance's and the result's, against the
    bound and MMD's gravity; a18's (グルーブ's height, central differences twice; the human baseline's measure); the
    lowering (cm) and its stretches: how deep, how long, and how far the top before each lowest point moved in time
    (frames, - earlier)"""
    rep = {"bound_units_s2": bound, "g_mmd_units_s2": G_MMD}
    for name, tag in (("下半身", "pelvis"), (CENTRE, "centre")):
        a0, a1 = down_acc(before.p(name)[:, 1]), down_acc(after.p(name)[:, 1])
        rep[tag] = {"dance_max": round(float(a0.max()), 1), "after_max": round(float(a1.max()), 1),
                    "dance_over_bound": int(np.sum(a0 > bound + 0.5)), "after_over_bound": int(np.sum(a1 > bound + 0.5)),
                    "dance_over_g": int(np.sum(a0 > G_MMD)), "after_over_g": int(np.sum(a1 > G_MMD)),
                    "at_6400_6406": [[round(float(v), 1) for v in a0[6400:6407]], [round(float(v), 1) for v in a1[6400:6407]]]
                    if len(a0) > 6406 else None}
    groove = "グルーブ" if before.has("グルーブ") else CENTRE
    if before.F >= 3:
        g0, g1 = (-np.gradient(np.gradient(b.p(groove)[:, 1]) * FPS) * FPS for b in (before, after))
        rep["a18"] = {"bone": groove, "down_max": [round(float(g0.max()), 1), round(float(g1.max()), 1)],
                      "over_98_pct": [round(100.0 * float(np.mean(g0 > G_MMD)), 3), round(100.0 * float(np.mean(g1 > G_MMD)), 3)]}
    low = -vfix * CM
    rep["frames_lowered"] = int(np.sum(low > 1e-4))
    rep["lowered_cm"] = q_stats(low[low > 1e-4], (0.5, 0.9, 0.99)) or {"max": 0.0}
    y0, y1 = before.p("下半身")[:, 1], after.p("下半身")[:, 1]
    spans = []
    for a, b in runs(low > 1e-4):
        top0 = a + int(np.argmax(y0[a:b + 1]))
        top1 = a + int(np.argmax(y1[a:b + 1]))
        spans.append({"first": a, "last": b, "s": [round(a / FPS, 2), round(b / FPS, 2)], "frames": b - a + 1,
                      "lowered_cm_max": round(float(low[a:b + 1].max()), 2), "top_moved_frames": top1 - top0,
                      "top_lowered_cm": round(float((y0[top0] - y1[top1]) * CM), 2)})
    rep["stretches"] = {"count": len(spans), "frames_median": int(np.median([r["frames"] for r in spans])) if spans else 0,
                        "deepest": sorted(spans, key=lambda r: -r["lowered_cm_max"])[:30]}
    rep["_spans"] = spans
    return rep


def stance_report(before, after, com0, com1, plan, mos_min_cm):
    """single support split as the human baseline splits it: the still frames (pulled) and the moving ones (the XcoM held
    inside the human range): the COM's and the XcoM's sideways offsets from the support's centre (cm, + towards the
    lifted foot) and the XcoM's sideways margin, the dance's and the result's medians"""
    st, mv = plan["still"], plan["moving"]
    foot = np.where(st | mv, plan["stance_foot"], "")
    _, X0, L0, _ = stance_lateral(before, com0, foot)
    _, X1, L1, _ = stance_lateral(after, com1, foot)
    xhi = SUPPORT_R_CM - mos_min_cm

    def med(v, m):
        return round(float(np.median(v[m])) * CM, 2) if m.any() else None
    rep = {"still_frames": int(st.sum()), "moving_frames": int(mv.sum()), "mos_ml_min_cm": mos_min_cm,
           "bound_cm": round(xhi, 2), "still_lateral_cm": {"before": med(L0, st), "after": med(L1, st)},
           "moving_lateral_cm": {"before": med(L0, mv), "after": med(L1, mv)},
           "moving_xcom_cm": {"before": med(X0, mv), "after": med(X1, mv),
                              "after_max": round(float(np.max(X1[mv])) * CM, 2) if mv.any() else None},
           "moving_mos_ml_cm": {"before": round(float(np.median(SUPPORT_R_CM - np.abs(X0[mv]) * CM)), 2) if mv.any() else None,
                                "after": round(float(np.median(SUPPORT_R_CM - np.abs(X1[mv]) * CM)), 2) if mv.any() else None},
           "moving_over_bound": [int(np.sum(X0[mv] * CM > xhi + 0.1)), int(np.sum(X1[mv] * CM > xhi + 0.1))]}
    return rep


def measures(before, after, com0, plan, x, d, shift, drop, dip, landings, info, motion, out, drop_over, unreachable,
             feet=None, catches=None, vfix=None, bound=DOWN_ACC_MAX, spikes=None, mos_min_cm=MOS_ML_MIN_CM, despike_e=None):
    F = before.F
    com1 = after.com()
    rep = {"catch": catch_report(after, com1, catches or [])}
    rep["stance"] = stance_report(before, after, com0, com1, plan, mos_min_cm)
    rep["vertical"] = vertical_report(before, after, np.zeros(F) if vfix is None else vfix, bound)
    rep["vertical"].pop("_spans", None)
    minutes = max(F / FPS / 60.0, 1e-9)
    n0, n1 = len(speed_spikes(before.p(CENTRE))[0]), len(speed_spikes(after.p(CENTRE))[0])
    rep["spikes"] = {"t_m_s": SPIKE_T, "per_min": [round(n0 / minutes, 2), round(n1 / minutes, 2)], "count": [n0, n1],
                     "despike": spikes}
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
    # the floor's added acceleration of the weight shift itself (the despike takes the dance's own jolts away: its
    # change is as sharp as they are, and is reported apart)
    de = np.zeros_like(shift) if despike_e is None else despike_e
    a2w = d2((shift - de) * UNIT_M) * FPS * FPS if F > 2 else np.zeros((0, 3))
    a2d = d2(de * UNIT_M) * FPS * FPS if F > 2 else np.zeros((0, 3))
    acc_h, acc_v = np.linalg.norm(a2w[:, [0, 2]], axis=1), np.abs(a2[:, 1])
    k = (com0[:, 1] * UNIT_M) / G
    rep["centre"] = {"shift_cm": q_stats(np.linalg.norm(sh[:, [0, 2]], axis=1)), "down_cm": q_stats(-sh[:, 1]),
                     "step_cm": q_stats(step, (0.5, 0.99)), "added_acc_m_s2": q_stats(acc_c),
                     "added_acc_h_m_s2": q_stats(acc_h), "added_acc_v_m_s2": q_stats(acc_v),
                     "despike_acc_h_m_s2": q_stats(np.linalg.norm(a2d[:, [0, 2]], axis=1)),
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
        eps = REACH_NO_WORSE_M / UNIT_M + 1e-5          # a leg already past it may go 0.5 mm farther
        reach["worse_frames_" + tag] = int(np.sum((ra > np.maximum(L, rb + eps))))
        # frames whose two-bone slack the layer took below REACH_TOL_CM (or below what the dance had)
        reach["slack_taken_frames_" + tag] = int(np.sum(ra > np.maximum(L - REACH_TOL_CM / CM, rb + eps)))
        on = plan["sup"][s]
        kb, ka = before.knee_flexion(s), after.knee_flexion(s)
        knee["on_floor_deg_" + tag] = {"before": q_stats(kb[on], (0.05, 0.5, 0.95)), "after": q_stats(ka[on], (0.05, 0.5, 0.95))}
        knee["change_deg_" + tag] = q_stats(np.abs(ka - kb), (0.5, 0.99))
        knee["over_%d_frames_%s" % (KNEE_FLEXION_DEG[0], tag)] = [int(np.sum(kb > KNEE_FLEXION_DEG[0])), int(np.sum(ka > KNEE_FLEXION_DEG[0]))]
        knee["over_%d_newly_%s" % (KNEE_FLEXION_DEG[1], tag)] = int(np.sum((ka > KNEE_FLEXION_DEG[1]) & (ka > kb + 0.5)))
        knee["max_deg_" + tag] = [round(float(kb.max()), 1), round(float(ka.max()), 1)]
        touch = plan["low"][s] < CONTACT_EPS                # a05's contact (4 mm), as the human baseline counts it
        knee.setdefault("straight_on_floor_frames", [0, 0])
        knee.setdefault("contact_frames", 0)
        knee["straight_on_floor_frames"][0] += int(np.sum(touch & (kb < KNEE_MIN_DEG)))
        knee["straight_on_floor_frames"][1] += int(np.sum(touch & (ka < KNEE_MIN_DEG)))
        knee["contact_frames"] += int(np.sum(touch))
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


def mmd_ik_check(module_path, model_path, frames):
    """(ik_check for layer(), a note for the report) from MMD's IK solver at module_path (the feet layer's
    tools/leg_ik.py: LegRig.load(pmx path), solve(rig, motion, frames) -> side -> {"reach": [F], ...})"""
    import hashlib
    if not model_path.lower().endswith(".pmx"):
        raise ValueError("--mmd-ik needs the model as .pmx (the IK links' limits are read from it)")
    if not os.path.isfile(module_path):
        raise ValueError("--mmd-ik: no file %s" % module_path)
    spec = importlib.util.spec_from_file_location("_balance_mmd_ik", module_path)
    lik = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lik)
    rig = lik.LegRig.load(model_path)

    def check(motion):
        sol = lik.solve(rig, motion, range(frames))
        return {s: np.asarray(sol[s]["reach"], dtype=np.float64) for s in SIDES}
    with open(module_path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    return check, {"module": os.path.abspath(module_path), "module_md5": md5}


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
    ap.add_argument("--dip", action="store_true", help="bend the knee on the landings that take the weight (off: human "
                                                     "dancers land already bent and add 0.3-1.6 degrees)")
    ap.add_argument("--no-dip", action="store_true", help="(the default) no knee bend on the landings")
    ap.add_argument("--no-catch", action="store_true", help="no bound or pull on the XcoM at the landings")
    ap.add_argument("--no-vertical", action="store_true", help="no bound on the pelvis's downward acceleration")
    ap.add_argument("--down-acc-max", type=float, default=DOWN_ACC_MAX,
                    help="units/s^2: the pelvis's downward acceleration at most (the real g, 122.5 at 8 cm a unit; 78 for a skirt "
                         "without its ceiling)")
    ap.add_argument("--no-despike", action="store_true", help="leave センター's 1-frame spikes (a08) as they are")
    ap.add_argument("--pull-moving", action="store_true", help="pull every single support over the foot, moving or still "
                                                              "(the layer before 2026-10-15)")
    ap.add_argument("--mos-ml-min", type=float, default=MOS_ML_MIN_CM,
                    help="cm: moving single support keeps the XcoM's sideways margin at least this (human dancers' median "
                         "-4.2, quartiles -6.1 and -3.6)")
    ap.add_argument("--spike-per-min", type=float, default=SPIKE_PER_MIN,
                    help="センター's 1-frame spikes left at most, a minute (human dancers 7.2)")
    ap.add_argument("--arrays", help="write the per-frame curves (.npz) for figures and checks")
    ap.add_argument("--support-from", help="read which foot is on the floor off this motion of the same dance (the feet "
                                           "layer's output on it); the dance given is the one moved")
    ap.add_argument("--mmd-ik", help="MMD's IK solver (the feet layer's tools/leg_ik.py): hold the layer back where a foot "
                                     "on the floor would newly fall short of its IK target as MMD solves it (.pmx only)")
    args = ap.parse_args(argv)
    try:
        check_distinct(args.dance, args.model, args.out, args.report, args.arrays, args.support_from)
        motion = vmd.load(args.dance)
        model = (pmd if args.model.lower().endswith(".pmd") else pmx).load(args.model)
        params = {"r_bal_cm": args.r_bal, "acc_max": args.acc_max, "lead_s": args.lead, "lag_s": args.lag,
                  "drop_max_cm": args.drop_max, "dip_deg": args.dip_deg, "dip": bool(args.dip and not args.no_dip), "catch": not args.no_catch,
                  "vertical": not args.no_vertical, "down_acc_max": args.down_acc_max, "despike": not args.no_despike,
                  "spike_per_min": args.spike_per_min, "pull_moving": args.pull_moving, "mos_ml_min_cm": args.mos_ml_min}
        ik_check, ik_note = None, None
        if args.mmd_ik:
            ik_check, ik_note = mmd_ik_check(args.mmd_ik, args.model, fk.last_frame(motion) + 1)
        support = vmd.load(args.support_from) if args.support_from else None
        result = layer(model, motion, params, ik_check=ik_check, support_motion=support)
        if ik_note:
            result.report["mmd_ik"].update(ik_note)
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
