"""Contacts that carry the body: which foot stands on the floor frame by frame, the standing feet put onto the floor and
held where they stand, and where no foot stands the body flying by gravity.

    python tools/contact_layer.py DANCE.vmd MODEL.pmx OUT.vmd --report r.json [--floor-y Y] [--no-ground] [--no-plant]
        [--no-drop] [--no-flight] [--no-knee]

Why (2026-10-17, _spike/out/stage6/contact/NOTES.md): the trace's dance keeps feet just over the floor that a person would
stand on.  People (FineDance's K-pop, choreography and jazz sequences, 62, the human baseline's a05 with their 1.2 cm
contact) have both feet on the floor 57.7 % [45.5, 65.0] of the frames, one 41.0 %, none 1.5 %; the MV (v10) 30.0, 63.8
and 6.2 %.  A person's standing foot moves along the floor slower than 7.9 cm/s [5.9, 11.8] on 90 % of its frames, the
MV's 27.1.  A person holds a foot still 0.4 to 4 cm over the floor on 0.82 % [0.35, 2.1] of the feet's frames, the MV on
7.73 % (pointed feet resting where the trace's longer-footed model had its toe on the floor, and in wide stances feet the
body leans on).  Runs of 4 to 6 frames with no foot on the floor: people 1.8 a minute, the MV 8.4; 7 to 12 frames: 0.33
and 6.0; there a person's pelvis falls at about gravity (-99 units/s^2 the median of their runs of 4 frames and more, -108
where both feet move fast over the floor), the MV's at -64.

Order: after the last foot layer (tools/foot_layer.py), before the upper body's (tools/wb_layer.py).  Before the foot
layer, a pointed foot this layer puts on the floor is remade by it as a loaded foot on the floor (the toes bent up, the
heel down), its ankle comes down and the knee straightens (the floaty work's first try: up to 30-34 degrees).  After it,
moving 足ＩＫ moves the whole foot as the foot layer shaped it (つま先ＩＫ hangs on 足ＩＫ; 足首 and 足先EX keep their keys).

The input as MMD shows it (tools/leg_ik.py; the shoe's lower shell of tools/foot_layer.py skinned on the solve), per foot:
its shoe's lowest point over the floor (at the foot IK's goal where the leg does not reach it, as the foot layer judges
a foot), the slowest of its touching vertices (within TOUCH of the lowest) moving along the floor to the next frame (a
foot turning on its ball, its toe or its heel does not move there), the lowest point's rise or fall.

1. The plan: a foot stands where its shoe is within ON_FLOOR of the floor, and where it is held still over it (under
   HOLD_MAX, its touching part slower than HOLD_SPEED along the floor and its lowest point slower than HOLD_RISE up or
   down, HOLD_MIN frames or more) unless no foot is on the floor there and the pelvis's parabola over the run and a frame
   each side falls faster than FLIGHT_FIT (0.8 of gravity: a flight).  People (FineDance's near kinds, a05's 1.2 cm
   contact, scripts/c03_lowhops.py): of their runs of 4 to 12 frames with no foot on the floor, those with a foot held so
   fall that fast in 6 % (79 runs; slower than half of gravity in 72 %), those without one in 67 % (350; 88 % faster than
   half): a foot held still just over the floor is the standing foot of a supported move.  A single frame faster than
   gravity is in 15 % of the former (the turn of the trace's keys: the song's 75.4-75.8 s turned at 151 units/s^2 over a
   foot held 1.3-2.5 cm up and became a 12-frame hop 9.4 cm higher than the dance), so it is no sign; where such a frame
   comes to stand on the floor, the pelvis is eased under FALL_BOUND there (the skirt's bound; 3. below).  A foot's runs
   closer than BRIDGE frames are joined where its shoe stays under BRIDGE_LIFT (the foot layer's bridge).
2. Ground: a standing foot over the floor is lowered (足ＩＫ's height: the foot's shape kept) until its shoe's lowest
   point is on the floor, eased in and out over EASE frames into the air around (never into the floor).
3. Reach: a standing leg must reach its goal with the knee bent REACH_KNEE_DEG (the foot layer's: people stand on no knee
   straighter than 5 degrees).  Where it cannot, a foot that bears weight (the only one standing, or the centre of mass's
   floor point more than NEED_CM outside the other foot's sole) gets the pelvis (センター) lowered until it reaches (at most
   DROP_MAX; spread and lessened as the foot layer's sink is, so that no frame on the floor has the pelvis fall faster than
   FALL_BOUND, or than the input where it already does); a free foot (a pointed foot resting) is lowered only as far as
   its leg reaches.  A frame the input had in the air (both shoes 1.6 cm up and more, AIR_MIN frames running: the skirt's
   bound left it free) that now stands and falls faster than FALL_BOUND gets the pelvis lowered by the same solve until
   it does not (the turns of the trace's keys over a still foot: the song's 18.73, 40.13, 61.87 and 75.53 s; the trace
   turns at up to 356 units/s^2 there, which no floor can hold), by the least lowering that does: within STRICT_NEAR
   frames of such a turn the solve weighs smoothness by STRICT_SMOOTH (review 2026-10-17: with SMOOTH the lowering was
   4.2 and 2.9 cm at 18.73 and 40.13 s, the jump's top at 40.03 s 2.9 cm under the dance's; now 2.3 and 1.6 cm).
4. Plant: a standing foot is held where the dance puts it down (the first frame of its run on the floor; the run's
   lowest if it never is): the slow slide (under PLANT_SPEED) of its touching part is undone frame by frame from there,
   forward and back (足ＩＫ's horizontal place), so it turns on its ball or its heel as the dance has it but does not
   travel, as long as its knee stays within KNEE_GIVE of the leg's without the hold (and bent REACH_KNEE_DEG): further,
   the body is going away from it as the dance has it, and the foot slides with it (the song's 70.4-71.2 s held a foot
   11 cm from the dance's, the knee 35 degrees straighter and MMD's leg 2.3 cm short).  Between its runs the correction
   goes from one run's to the next's over the swing (a smoothstep), so that it lands where the dance puts it.
5. Flight: where no foot stands for AIR_MIN frames or more, the body's centre of mass falls as a body in the air does,
   at one rate over the flight: the dance's own (its parabola there) kept within FLIGHT_BAND (FLIGHT_FIT to gravity G:
   slower comes to FLIGHT_FIT, faster to G).  The pelvis's height (センター) changes over the flight and WINDOW frames
   each side (the push and the catch) by the least change, with its third differences weighed SMOOTH, that makes the
   second differences of the centre of mass that fall on the frames with air on both sides, keeps every frame on the
   floor no faster falling than FALL_BOUND (or the input) and every standing leg in reach.  The centre of mass there is the pelvis's height and its limbs' part over it smoothed (LIMB_SMOOTH): a
   limb's quick move (the trace's one-frame jumps) stays the dance's instead of the pelvis taking it up as a jolt.  A foot in the air goes with the body
   (the leg keeps the dance's shape: people's feet clear the floor more in longer flights, 3.3 cm the median of the
   highest in runs of 4 to 6 frames, 5.2 in 7 to 12), easing in over CARRY_RAMP frames from the floor.
6. The knee at the end of its reach, on the dance as 1.-5. leave it (kneepop, 2026-10-17): near the end of a leg's reach
   (the hip's distance to the goal within KNEE_NEAR of rig_check's max_reach) a converged leg IK (v7's 400 loops) puts the
   knee straight on a frame whose goal is a centimetre or two further than its neighbours' (the trace's take-offs and
   landings, the snap into a kick).  There, on the legs' formula (a two-bone leg's bend from the distance), round each
   frame that jumps as rig_check counts it (more than KNEE_JUMP_DEG off the line through its neighbours; a smaller kink is
   left: a standing foot turned for it is a jump of the foot instead) every frame straighter than the line through its
   neighbours by more than KNEE_POP_DEG is bent to within it (even_pops, to a fixed
   point; never past the band's edge, never straighter): a swing leg's goal comes toward the hip by what is too long (its
   toe IK's goal with MMD's ankle: a goal beyond the reach moves further than the ankle, and the foot keeps its turn); a
   standing foot turns onto its toes about the front of its shoe's touching part, or onto its heel about its back
   (whichever needs the lesser turn, at most KNEE_PITCH_MAX), the shoe's lowest point where it was (the toes stay on the
   floor; a take-off rises onto them, a leg reaching forward lands on its heel), held on to the run's end within
   KNEE_EDGE frames of a lift or a landing, and only there (edge_turns: a turn in the middle of a stand would raise the heel
   for a frame and set it down again; such a knee is left).  The pelvis does not move.
7. The frames and between them: a frame whose shoe the layer leaves deeper in the floor than the input (a push that
   overshoots) is raised by the excess; MMD draws 240 fps and interpolates the keys, so where a shoe would dip into the
   floor between two frames further than the input's did, both are raised by the dip (the foot layer's sub-frame check).

Written: 足ＩＫ (both feet, its place) and センター (its height), a key on every frame (a linear curve, the physics bytes of
the input's key in force), 足首 (the foot's turn kept or turned), and つま先ＩＫ (its place) where 6. turns a standing foot
or brings a goal in from beyond the reach; nothing else (the report's `untouched` reads it back).  With nothing to do the
input comes back as it is.  Coordinates are MMD's (Y up, the model facing -Z), units are MMD units (UNIT_CM centimetres).
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_contact_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FL = _tool("foot_layer")
IK = FL.IK
qmul, qconj, qrot = IK.qmul, IK.qconj, IK.qrot

UNIT_CM = 8.0
FPS = 30.0
G = 122.5                       # units/s^2: gravity (9.8 m/s^2) at 8 cm a unit
SIDES = ("左", "右")
TAGS = {"左": "L", "右": "R"}

ON_FLOOR = 0.05                 # units (4 mm, a05's contact): a shoe this low stands on the floor
HOLD_MAX = 0.5                  # units (4 cm, a05 s11's band): a still shoe lower than this is held over the floor ...
HOLD_SPEED = 30.0               # cm/s: ... its touching part moving along the floor slower than this (the foot layer's
                                # TOE_SLIDE and HOVER_GLIDE: a toe on the floor stays or slides slowly, a swing skims past)
HOLD_RISE = 20.0                # cm/s: ... its lowest point rising or falling slower than this, the smaller of the steps
                                # into and out of the frame (the foot layer's HOVER_FOOT_SPEED: faster is a touch or a lift)
HOLD_MIN = 4                    # frames: a shorter hold is a foot passing by
FLIGHT_FIT = 0.8 * G            # units/s^2: no foot on the floor and the pelvis's parabola over the run and a frame each side
                                # falling faster than this is a flight even over a foot held still (people: 6 % of their runs
                                # with a held foot, 67 % of those without; scripts/c03_lowhops.py)
FLIGHT_BAND = (FLIGHT_FIT, G)   # units/s^2 down: a flight's centre of mass falls at the dance's own rate (its parabola over
                                # the flight) kept within this: slower comes to FLIGHT_FIT, faster (no body falls through the
                                # air faster) to G.  People's centre of mass in their air runs (floaty's: both feet 2.5 cm
                                # up for 4 frames and more; de Leva on the SMPL-X joints) falls at 109 [103, 118] units/s^2
                                # (FineDance's near kinds, 43 with air; 110 in the middle frames of runs of 10 to 14), their
                                # pelvis at 108 [95, 119], mv_inspect's gravity.air_acc_median.  (v11feet 2026-10-17: with G
                                # for every flight the song's pelvis fell at 132 there, its centre of mass at 121, the dance's
                                # limbs rising over its pelvis in the air by 11, people's by 0; _spike/out/stage6/v11feet/
                                # scripts/air_com.py, air_com2.py)
FALL_BOUND = 122.0             # units/s^2: the pelvis's downward acceleration where a foot holds the body up (the balance
                                # layer's DOWN_ACC_MAX, for the skirt); faster on a frame of a run with no foot down is a hop
FALL_TOL = 0.5                  # units/s^2: past a bound by more than this (as the balance layer's report counts)
BRIDGE = 2                      # frames: a standing foot lifted this long or less stays down ...
BRIDGE_LIFT = 0.1875            # units (1.5 cm): ... where its shoe stays this low (the foot layer's BRIDGE_LIFT)
EASE = 4                        # frames: a foot's lowering comes and goes over this many frames each way (the foot layer's)
TOUCH = 0.025                   # units (2 mm): the shoe's vertices this near its lowest touch (the foot layer's HOVER_TOUCH)
SWING_CLEAR = ON_FLOOR + 0.0125 # units (5 mm): a foot not standing whose touching part moves along the floor faster than
                                # PLANT_SPEED is not brought lower than this (nor below its own height in the dance) by the
                                # lowering eased round a standing run, nor by the body's change round a flight it goes with;
                                # and a lift of BRIDGE frames bridges only a foot slower than that (v11feet 2026-10-17: after
                                # the retarget, which carries a shoe as high over the floor as the source's, these put the
                                # song's swings on the floor, where they slid: 153 cm a minute, 621 in all; 272 without)
GLIDE_MAX = 0.25                # units (2 cm): in a run of AIR_MIN frames and more with no foot standing whose pelvis does
                                # not fall as in a flight (its parabola over the run and a frame each side slower than
                                # FLIGHT_FIT, no frame faster than FALL_BOUND), the lower foot stands where its shoe is lower
                                # than this (tools/retarget.py's TOUCH_FLOOR: a source foot this low turning or still is on
                                # the floor there): the dance's support gliding along the floor, not a hover.  (v11feet
                                # 2026-10-17: after the retarget and the swings kept off the floor, the layer made 55 of the
                                # song's hovers hops; mv_inspect's air 12 a minute, people's 1.3 [0, 2.9].  With the glide under
                                # 1.6 cm (the skirt's AIR_CLEAR) 4.6, hover 2.4 %; under 2 cm 2.7 and 2.0 % (people's 1.4
                                # [0.55, 2.2]), contact_check's slide 297 -> 316 cm a minute: the source's 334, the retarget's
                                # 315)
NEED_CM = 10.0                  # cm: the centre of mass's floor point this far outside the other foot's sole: this foot
                                # bears weight (the MV's free resting feet have it -5 to +0.5 cm, the feet of its wide
                                # stances -12 to -32 cm; people's single-support ZMP margin is -4.4 cm [-6.0, -2.2])
SOLE_TOUCH = 0.15               # units (1.2 cm): the vertices of a shoe this near the floor make its sole on it
KNEE_GIVE = 10.0                # degrees: a held foot's knee stays within this of the leg's without the hold; further the
                                # foot slides as the dance has it (the knee change tools/sink_check.py and
                                # tools/contact_check.py count is 10 degrees and more)
REACH_KNEE_DEG = FL.REACH_KNEE_DEG   # degrees: the knee of a standing leg bent at least this much (people: none straighter
                                     # than 5 degrees on the floor; the foot layer's)
DROP_MAX = 1.0                  # units (8 cm): the most the pelvis goes down to let a standing leg reach the floor
REACH_MIN = 9                   # frames (0.3 s): a weight-bearing foot standing out of reach this long gets the pelvis lowered
DROP_WINDOW = 24                # frames each side of a lowering over which it comes and goes (smoothly, within the bound)
DROP_QP_ROUNDS = 400
JUDGE_MISS = 0.75               # units (6 cm): a foot MMD leaves this far or less from its goal is judged at the goal (a
                                # leg lagging or just out of reach: 159.7-163.9 and 197-198.7 s are 5.1 cm); further (a
                                # kick far out, 245.4 s: 27 cm) the foot is where MMD shows it
PLANT_SPEED = 30.0              # cm/s: a standing foot's touching part moving slower than this is held in place (the trace's
                                # drift and jitter: v10's standing feet move faster than 27 cm/s on 10 % of their frames,
                                # people's 7.9); faster is the dance sliding the foot (kept)
PLANT_POP = 2                   # steps: a standing foot's moves faster than PLANT_SPEED in a run of this many or fewer, with a
                                # slower step of the same stand on each side, are a jump, not a slide, and are held too (v11feet
                                # 2026-10-17: the song's 242.1 s right foot, turned some 90 degrees in a frame by the trace, came
                                # out of the foot layers with its shoe 11 cm along the floor in that frame)
PLANT_SPIKE = (2.0, 5.0)        # (times, cm): and a standing foot's step longer than the first times the longer of its two
                                # neighbours and than the second is a jump inside a slide: it is brought to the neighbours'
                                # pace (the song's 242.1 s: 11.35 cm between steps of 1.7 and 1.9)
AIR_MIN = 4                     # frames with no foot standing: a flight (the balance layer's AIR_MIN)
WINDOW = 8                      # frames each side of a flight over which the pelvis may change
SMOOTH = 30.0                   # the weight of the change's third differences against the change itself
AIR_CLEAR = 0.2 + 0.0125        # units (1.6 cm and 1 mm): a shoe lower than 1.6 cm stands, as the skirt's bound counts it (the
                                # balance layer's support, tools/sink_check.py's SUPPORT_CM)
CARRY_RAMP = 2                  # frames: a foot leaving the floor goes with the body's change by half on its first frame off
                                # it and fully from the second (the same before a landing)
LIMB_SMOOTH = (1, 4, 6, 4, 1)   # the weights the limbs' part of the centre of mass (its height over the pelvis) is smoothed
                                # with for the flight's parabola (binomial: none of a one-frame jump's 15 Hz passes)
PAD = 2                         # frames pinned to no change each side of a window of the pelvis's solves
SUB_NEAR = 0.25                 # units: the intervals checked between the frames (either end this near the floor)
SUB_ROUNDS = 3
IK_MISS = 0.0125                 # units (1 mm): MMD's ankle this far from its goal has not reached it
LAND_TOL = 0.0125                # units (1 mm): a weight-bearing foot whose shoe MMD leaves higher than this gets more drop
PUSH_ROUNDS = 4                 # rounds of pushing the goal of a weight-bearing foot MMD leaves over the floor ...
PUSH_STEP = 0.15                # units: ... by at most this a round (the foot layer's push)
DROP_ROUNDS = 4                 # rounds of checking the lowered pelvis on MMD's IK (a nearly straight leg stops short)
FLIGHT_ROUNDS = 4               # rounds of solving the flight again on the centre of mass the changed dance moves ...
FLIGHT_RESID = 1.0              # units/s^2: ... until it falls within this of its flight's fall (FLIGHT_BAND) on the frames
                                # with air on both sides
STRICT_SMOOTH = 3.0             # the weight of the third differences of a lowering within STRICT_NEAR frames of a turn it
STRICT_NEAR = 8                 # brings within the bound (strict frames) with no need there: the least lowering, not a wide
                                # one (the song's 40.13 s: 2.88 cm with SMOOTH, 1.55 with this, 1.29 the least; mv_inspect
                                # counts a jump's top 2 cm and more under the dance's).  Per frame, not per window: a need
                                # nearby merges the windows
# 6. the knee at the end of its reach (the review of rig, 2026-10-17: with the leg IK's 400 loops of v7's recipe MMD's leg
# reaches its goal, and the knee jumps on main's chain went 45 -> 70, rig_check's count of a frame more than 10 degrees off
# the line through its neighbours: the song's 2226 a left knee 23 -> 4 -> 37 degrees.  Near the end of the reach the knee's
# bend is most sensitive to the hip's distance to the goal (Sour's Rin: 32 degrees a centimetre at the end, 7 at 20
# degrees), so a goal a centimetre or two further for a frame straightens it for that frame).  The band is a part of the
# leg's reach (rig_check's max_reach: the knee at the least bend of its IK limit), so that it holds for any body and dance.
# (Drawing every goal softly into the reach from 2 cm short of it, the review's other proposal, took the song's jumps on the
# legs' formula 75 -> 47 against this step's 32, and with this step to 30, moving some 270 frames of the swinging legs and
# kicks far out of reach up to 30 cm: kneepop's NOTES, 2026-10-17.)
KNEE_NEAR = 0.05                # of the reach: the band at its end (Rin's knee bent 31 degrees and less) where a frame or two
                                # straighter than the frames round them are bent like them
KNEE_POP_DEG = 6.0              # degrees: there a frame's bend comes within this of the line through its neighbours, and no
                                # neighbour's further than this the other way (rig_check counts a jump at 10.  On the song's
                                # legs' formula: 75 -> 32 jumps with the first side, 29 with both; 4 moves twice the frames
                                # for no fewer, 8 half the frames for the same but leaves them nearer 10)
KNEE_JUMP_DEG = 10.0            # degrees: rig_check ik's jump, a frame further than this off the line through its neighbours.
                                # Only such a frame and the frames KNEE_JUMP_NEAR round it are bent (the review of kneepop,
                                # 2026-10-17: bending every kink past KNEE_POP_DEG changed 56 of the song's 99 places where
                                # no knee jumped, and a standing foot turned for one became the foot's own jump: 249.9 s, a
                                # right foot 13 degrees onto its toes for a knee 8.7 degrees off its line, the foot's pitch
                                # then 13 degrees off the line through its neighbours)
KNEE_JUMP_NEAR = 1              # frames
KNEE_ROUNDS = 40                # rounds of evening out (a pop of two frames halves its gap a round)
KNEE_PITCH_MAX = 30.0           # degrees: the most a standing foot turns onto its toes or its heel for its knee
KNEE_PITCH_STEP = 0.25          # degrees: the turns tried
KNEE_EDGE = 3                   # frames at either end of a standing run: a turn there is held on to the end of the run (the
                                # heel does not come down again before the foot lifts, nor rise again after it lands)
KNEE_TOL = IK_MISS               # units (1 mm): a smaller change of the hip's distance to the goal is none (MMD's IK tells no less)
KNEE_TOE_TOL = 1e-4             # units: a goal MMD's ankle is nearer than this to is reached (its toe IK's goal moves with it)
KNEE_PLAN_ROUNDS = 8            # rounds of the targets on the distances the changes so far leave (a turn held on to a run's
                                # end bends that frame more, and the frame before may then need more)


def runs(mask, n=1):
    """[(a, b)] inclusive runs of True of n frames or more"""
    m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]]).astype(np.int8)
    d = np.diff(m)
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1) if b - a + 1 >= n]


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def smoothstep(x):
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def down_acc(y):
    """the downward acceleration [F] (units/s^2, + down) of heights y: 30 fps second differences, 0 at the ends"""
    y = np.asarray(y, dtype=float)
    a = np.zeros(len(y))
    if len(y) >= 3:
        a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS * FPS
    return a


def step_min(x):
    """per frame the smaller of the steps into and out of it (|x[t] - x[t-1]|, |x[t+1] - x[t]|; one at the ends)"""
    x = np.asarray(x, dtype=float)
    F = len(x)
    if F < 2:
        return np.zeros(F)
    d = np.abs(np.diff(x))
    out = np.empty(F)
    out[0], out[-1] = d[0], d[-1]
    out[1:-1] = np.minimum(d[:-1], d[1:])
    return out


def touch_slip(w, touch=TOUCH):
    """[F, 2] the horizontal move (x, z; units) to the next frame of the touching vertex (within `touch` of the shoe's
    lowest) that moves least, from the shoe's vertices w [F, N, 3]; 0 on the last frame"""
    F = len(w)
    out = np.zeros((F, 2))
    if F > 1:
        y = w[:-1, :, 1]
        near = y <= y.min(axis=1, keepdims=True) + touch
        d = (w[1:] - w[:-1])[:, :, [0, 2]]
        n = np.where(near, np.linalg.norm(d, axis=2), np.inf)
        k = n.argmin(axis=1)
        out[:-1] = d[np.arange(F - 1), k]
    return out


def knee_reach(L1, L2, knee_deg):
    return FL.knee_reach(L1, L2, knee_deg)


def leg_lengths(rig, side):
    sd = rig.sides[side]
    h0, k0, a0 = (np.array(rig.bones[i].position, dtype=float) for i in (sd.thigh, sd.knee, sd.ankle))
    return float(np.linalg.norm(k0 - h0)), float(np.linalg.norm(a0 - k0))


def raise_room(hip, goal, reach):
    """per frame [F] how far the hip may go up (units; negative: it must come down) before its distance to the goal
    passes `reach` (NaN where the goal lies further than `reach` along the floor: no height reaches it)"""
    h2 = np.sum((hip - goal)[:, [0, 2]] ** 2, axis=1)
    ok = h2 <= reach * reach
    v = np.sqrt(np.maximum(reach * reach - h2, 0.0))
    room = v - (hip[:, 1] - goal[:, 1])
    return np.where(ok, room, np.nan)


def bridge(stance, low, gap=BRIDGE, lift=BRIDGE_LIFT, speed=None):
    """stance [F] with the gaps of `gap` frames or fewer between two standing runs filled where the shoe (low [F]) stays
    under `lift` and (speed [F], cm/s: its touching part along the floor, when given) slower than PLANT_SPEED: the
    trace's jitter of a standing foot, not a quick step"""
    out = np.array(stance, dtype=bool)
    for a, b in runs(~out):
        if a > 0 and b < len(out) - 1 and b - a + 1 <= gap and bool(np.all(low[a:b + 1] < lift)) and                 (speed is None or bool(np.all(np.asarray(speed)[a:b + 1] < PLANT_SPEED))):
            out[a:b + 1] = True
    return out


def flight_frames(on, pelvis_y, flight_acc=FLIGHT_FIT):
    """[F] frames of the runs with no foot on the floor (on: side -> [F]) whose pelvis (heights pelvis_y [F]) falls like a
    flight: its parabola over the run and a frame each side falls faster than flight_acc"""
    pelvis_y = np.asarray(pelvis_y, dtype=float)
    F = len(pelvis_y)
    out = np.zeros(F, dtype=bool)
    none = np.logical_and.reduce([~np.asarray(m, dtype=bool) for m in on.values()])
    for a, b in runs(none):
        i0, i1 = max(a - 1, 0), min(b + 1, F - 1)
        if i1 - i0 >= 2:
            t = np.arange(i0, i1 + 1) / FPS
            if 2.0 * np.polyfit(t, pelvis_y[i0:i1 + 1], 2)[0] < -flight_acc:
                out[a:b + 1] = True
    return out


def eased_lowering(dy, stance, low, ease=EASE, speed=None):
    """the lowering [F] (units, <= 0) of a foot: dy on its standing frames, carried into the frames around with a raised
    cosine over `ease` frames from the nearest standing frame (never more than the frame's own shoe height, low [F]: not
    into the floor; with speed [F] (cm/s, its touching part along the floor), a frame faster than PLANT_SPEED no lower
    than SWING_CLEAR: a swing is not pressed onto the floor)"""
    dy = np.where(stance, np.minimum(dy, 0.0), 0.0)
    env = FL.smooth_max_envelope(-dy, ease)
    room = np.maximum(low, 0.0)
    if speed is not None:
        room = np.where(np.asarray(speed) > PLANT_SPEED, np.maximum(low - SWING_CLEAR, 0.0), room)
    return np.where(stance, dy, -np.minimum(env, room))


def swing_blend(corr, stance, F):
    """the planting correction [F, 2] between its standing runs: from the value on a run's last frame to the value on the
    next run's first frame (a smoothstep over the frames between), from none over 2 EASE frames before the first run and
    to none over 2 EASE frames after the last"""
    out = np.array(corr, dtype=float)
    rr = runs(stance)
    if not rr:
        return out
    a0 = rr[0][0]
    s0 = a0 - 2 * EASE
    for t in range(max(0, s0), a0):
        out[t] = out[a0] * float(smoothstep((t - s0) / float(a0 - s0)))
    for i, (a, b) in enumerate(rr):
        end = out[b].copy()
        if i + 1 < len(rr):
            nxt = rr[i + 1][0]
            start = out[nxt].copy()
        else:
            nxt = min(F, b + 1 + 2 * EASE)
            start = np.zeros(2)
        n = nxt - b
        for t in range(b + 1, min(nxt, F)):
            u = float(smoothstep((t - b) / float(n)))
            out[t] = end * (1.0 - u) + start * u
    return out


def held_share(step, stance, n=PLANT_POP, spike=PLANT_SPIKE):
    """[F] how much of each step (frame t to t + 1, step [F] in cm) of a standing foot (stance [F]) the plant undoes: all of
    a step slower than PLANT_SPEED a frame and of a lone jump (lone_pops), the excess over its neighbours' pace of a step
    longer than spike[0] times both and than spike[1] cm (a jump inside a slide), none of the rest (the dance's slide)"""
    step = np.asarray(step, dtype=float)
    slow = step * FPS < PLANT_SPEED
    share = (slow | lone_pops(~slow, stance, n)).astype(float)
    F = len(step)
    on = np.zeros(F, dtype=bool)
    on[:-1] = np.asarray(stance[:-1], dtype=bool) & np.asarray(stance[1:], dtype=bool)
    if F >= 3:
        level = np.zeros(F)
        level[1:-1] = np.maximum(step[:-2], step[2:])
        jump = on & (share < 1.0) & (step > spike[1]) & (step > spike[0] * level)
        jump[0] = jump[-1] = False
        share = np.where(jump, 1.0 - level / np.maximum(step, 1e-9), share)
    return share


def lone_pops(fast, stance, n=PLANT_POP):
    """[F] the steps (frame t to t + 1) of a standing foot (stance [F]) that are fast (fast [F]) in a run of n or fewer
    with a slow step of the same stand on each side: a jump of a frame or two, not the dance sliding the foot"""
    fast = np.asarray(fast, dtype=bool)
    stance = np.asarray(stance, dtype=bool)
    F = len(fast)
    on = np.zeros(F, dtype=bool)
    on[:-1] = stance[:-1] & stance[1:]
    out = np.zeros(F, dtype=bool)
    for a, b in runs(fast & on):
        if b - a + 1 <= n and a >= 1 and b + 1 < F and on[a - 1] and on[b + 1] and not fast[a - 1] and not fast[b + 1]:
            out[a:b + 1] = True
    return out


def plant_band(e, L1, L2, give=KNEE_GIVE, straightest=None):
    """per frame (r_lo, r_hi) [F]: the band of the hip's distance to a held foot's goal whose knee stays within `give`
    degrees of the knee without the hold (e [F, 3]: the hip less that goal) and bent `straightest` degrees (REACH_KNEE_DEG)
    or more; the distance without the hold is always inside"""
    straightest = REACH_KNEE_DEG if straightest is None else straightest
    r = np.linalg.norm(e, axis=1)
    c = np.clip((r * r - L1 * L1 - L2 * L2) / (2.0 * L1 * L2), -1.0, 1.0)
    knee = np.degrees(np.arccos(c))                     # (0: straight, as FL.knee_reach counts the bend)

    def reach(deg):
        return np.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * np.cos(np.radians(deg)))
    r_hi = np.maximum(reach(np.maximum(knee - give, straightest)), r)
    r_lo = np.minimum(reach(np.minimum(knee + give, 180.0)), r)
    return r_lo, r_hi


def held_within(c, e, r_lo, r_hi):
    """(the hold, limited): the most of a foot's hold c [2] (x, z; units: its goal moved so) toward none that keeps the
    hip's distance to the goal (e [3]: the hip less the goal without the hold) within [r_lo, r_hi]"""
    c = np.asarray(c, dtype=float)
    d = np.array([c[0], 0.0, c[1]])
    A = float(d @ d)
    if A < 1e-18:
        return c, False
    B = -2.0 * float(e @ d)
    C = float(e @ e)
    lam = 1.0
    disc = B * B - 4.0 * A * (C - r_hi * r_hi)
    if disc >= 0.0:
        lam = min(lam, (-B + math.sqrt(disc)) / (2.0 * A))
    disc = B * B - 4.0 * A * (C - r_lo * r_lo)
    if disc > 0.0:
        mu = (-B - math.sqrt(disc)) / (2.0 * A)
        if mu >= 0.0:
            lam = min(lam, mu)
    lam = max(lam, 0.0)
    return lam * c, lam < 1.0 - 1e-9


def frame_raise(low_out, low_in, tol=None):
    """[F] (units, >= 0): how far to raise a foot whose shoe (its lowest point over the floor, low_out [F]) the layer
    leaves deeper in the floor than the input had it (low_in [F]) by more than a quarter of tol (FL.PEN_TOL): by that
    much and a quarter of tol more"""
    tol = FL.PEN_TOL if tol is None else tol
    excess = np.maximum(-np.asarray(low_out, dtype=float), 0.0) - np.maximum(-np.asarray(low_in, dtype=float), 0.0)
    return np.where(excess > 0.25 * tol, excess + 0.25 * tol, 0.0)


def limb_smoothed(com_y, pelvis_y, weights=LIMB_SMOOTH):
    """the centre of mass's height [F] with its limbs' part (its height over the pelvis's) smoothed by `weights`"""
    pelvis_y = np.asarray(pelvis_y, dtype=float)
    k = np.asarray(com_y, dtype=float) - pelvis_y
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    h = len(w) // 2
    if len(k) <= 2 * h:
        return pelvis_y + k
    kp = np.concatenate([np.full(h, k[0]), k, np.full(h, k[-1])])
    return pelvis_y + np.convolve(kp, w, mode="valid")


# ---- the knee at the end of its reach ---------------------------------------------------------------------------------

def knee_geometry(rig, side):
    """(thigh, shank, the knee's bend at rest between them, the least bend of its IK limit) of one leg (units, degrees): a
    bend is the knee's turn from rest, as rig_check ik counts it (Sour's Rin: 4.43, 4.51, 5.7 and 0)"""
    sd = rig.sides[side]
    h0, k0, a0 = (np.array(rig.bones[i].position, dtype=float) for i in (sd.thigh, sd.knee, sd.ankle))
    u, v = k0 - h0, a0 - k0
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))
    return (float(np.linalg.norm(u)), float(np.linalg.norm(v)), math.degrees(math.acos(min(max(c, -1.0), 1.0))),
            max(0.0, -math.degrees(sd.knee_hi)))


def knee_distance(bend, L1, L2, rest_deg):
    """the hip's distance to the ankle of a two-bone leg whose knee is turned `bend` degrees from its rest bend"""
    return np.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * np.cos(np.radians(rest_deg + np.asarray(bend, dtype=float))))


def knee_bend(D, L1, L2, rest_deg, least_deg=0.0):
    """the knee's bend from rest (degrees) of a two-bone leg whose IK reaches the hip's distance D to its goal (the least
    bend at the reach and beyond)"""
    c = (np.asarray(D, dtype=float) ** 2 - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    return np.clip(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))) - rest_deg, least_deg, 180.0 - rest_deg)


def even_pops(bend, cap, pop_deg=None, rounds=None, both=True, only=None):
    """the bends [F] (degrees) with every frame bent less than `cap` (the band at the end of the reach) and straighter than
    the line through its neighbours by more than pop_deg raised to that line less pop_deg (no further than cap, never
    lowered), to a fixed point: a frame or two straight between bent ones come within pop_deg of the frames round them.
    both: also raised so that a neighbour is not more bent than the line through its own neighbours by more than pop_deg
    (a knee snapping straight from a bend held: the frame it snaps on bends toward the frames before; rig_check counts a
    jump either way).  only [F]: the frames that may be raised (None: all), and with them the frames that the raising
    makes jump in turn (near_jumps of the bends so far: a frame raised next to a straight one leaves that one a jump)"""
    pop_deg = KNEE_POP_DEG if pop_deg is None else pop_deg
    rounds = KNEE_ROUNDS if rounds is None else rounds
    b = np.array(bend, dtype=float)
    if len(b) < 3:
        return b
    may = np.ones(len(b), dtype=bool) if only is None else np.array(only, dtype=bool)
    # the straight frames first, to their fixed point; then both ways (a frame straight between bent ones makes its
    # neighbours look more bent than their own neighbours' line until it is raised: those are not raised for it)
    for sides in ((False,), (False, True)) if both and len(b) >= 4 else ((False,),):
        for _ in range(rounds):
            if only is not None:
                may |= near_jumps(b)
            need = np.full(len(b), -np.inf)
            need[1:-1] = 0.5 * (b[:-2] + b[2:]) - pop_deg
            if True in sides:
                need[2:] = np.maximum(need[2:], 2.0 * (b[1:-1] - pop_deg) - b[:-2])
                need[:-2] = np.maximum(need[:-2], 2.0 * (b[1:-1] - pop_deg) - b[2:])
            new = np.where((b < cap) & may, np.maximum(b, np.minimum(cap, need)), b)
            done = float(np.max(new - b)) < 1e-6
            b = new
            if done:
                break
    return b


def near_jumps(bend, deg=None, near=None):
    """[F] the frames of a knee's jumps as rig_check ik counts them (more than `deg` off the line through their
    neighbours) and the frames `near` round them: the frames the knee step may bend"""
    deg = KNEE_JUMP_DEG if deg is None else deg
    near = KNEE_JUMP_NEAR if near is None else near
    out = np.zeros(len(bend), dtype=bool)
    for f in knee_jump_frames(bend, deg):
        out[max(0, f - near):f + near + 1] = True
    return out


def knee_targets(D, L1, L2, rest_deg, least_deg=0.0, near=None, pop_deg=None, only=None):
    """one leg's hip-to-goal distances D [F] (units): {"target": the distance its knee is to have [F] (never longer than D),
    "bend0": the bends of D [F], "bend": the target's [F] (degrees from rest), "even": the frames bent like the frames round
    them [F], "reach", "cap": the bend at the band's edge}.  In the band near x the reach at its end, a frame or two
    straighter than the line through the frames round them by more than pop_deg are bent to within pop_deg of it, and so
    are the frames round one more bent than that line (even_pops: a knee straight for a frame, or snapping straight, at the
    IK's end of the reach); nothing else changes.  only [F]: the frames that may be bent (None: all)"""
    near = KNEE_NEAR if near is None else near
    D = np.asarray(D, dtype=float)
    L = float(knee_distance(least_deg, L1, L2, rest_deg))
    bend0 = knee_bend(D, L1, L2, rest_deg, least_deg)
    cap = float(knee_bend(L * (1.0 - near), L1, L2, rest_deg, least_deg))
    b = even_pops(bend0, cap, pop_deg, only=only)
    raised = b > bend0 + 1e-9
    target = np.minimum(np.where(raised, knee_distance(b, L1, L2, rest_deg), D), D)
    return {"target": target, "bend0": bend0, "bend": np.where(raised, b, bend0), "even": raised, "reach": L, "cap": cap}


# ---- the pelvis in the air: a small quadratic programme -------------------------------------------------------------

def _diff_matrix(n, order, first=None, F=None):
    """the matrix [n, n] of the centred differences of `order` (2: x[t+1] - 2 x[t] + x[t-1]; 3: x[t+2] - 3 x[t+1] +
    3 x[t] - x[t-1]) of a vector x of n values with zeros beyond its ends.  With the window's first frame and the
    dance's length F: a row whose differences reach past the dance's first or last frame is left out (zeros: nothing is
    pinned beyond the dance's ends)"""
    M = np.zeros((n, n))
    coef = {2: {-1: 1.0, 0: -2.0, 1: 1.0}, 3: {-1: -1.0, 0: 3.0, 1: -3.0, 2: 1.0}}[order]
    for t in range(n):
        if first is not None and (first + t + min(coef) < 0 or first + t + max(coef) > F - 1):
            continue
        for k, c in coef.items():
            if 0 <= t + k < n:
                M[t, t + k] = c
    return M


def solve_qp(H, A_eq, b_eq, A_in, b_in, rounds=60, batch=1):
    """the least 0.5 x' H x with A_eq x = b_eq and A_in x >= b_in, by active sets (H positive definite, a few hundred
    variables at most), adding up to `batch` of the most violated inequalities a round.  (x, the active inequalities,
    the rounds taken, ok)"""
    n = H.shape[0]
    active = []
    ok = False
    x = np.zeros(n)
    for r in range(rounds):
        rows = [A_eq] + ([A_in[active]] if active else [])
        rhs = [b_eq] + ([b_in[active]] if active else [])
        A = np.concatenate(rows, 0) if rows else np.zeros((0, n))
        b = np.concatenate(rhs, 0) if rhs else np.zeros(0)
        m = len(b)
        K = np.zeros((n + m, n + m))
        K[:n, :n] = H
        K[:n, n:] = -A.T
        K[n:, :n] = A
        rhs_full = np.concatenate([np.zeros(n), b])
        try:
            sol = np.linalg.solve(K, rhs_full)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(K, rhs_full, rcond=None)[0]
        x, lam = sol[:n], sol[n:]
        lam_in = lam[len(b_eq):]
        if active and np.any(lam_in < -1e-12):
            del active[int(np.argmin(lam_in))]
            continue
        g = A_in @ x - b_in if len(b_in) else np.zeros(0)
        bad = [i for i in np.argsort(g) if g[i] < -1e-12 and i not in active]
        if not bad:
            ok = True
            return x, active, r + 1, ok
        active.extend(int(i) for i in bad[:batch])
    return x, active, rounds, ok


def drop_profile(need, floor_frames, fall_down, allowed, F, window=None, strict=None, strict_smooth=None):
    """the pelvis's lowering z [F] (units, >= 0) and per window its rows: over each run of need [F] > 0 or of strict [F]
    and `window` frames each side (merged where they meet), the least and smoothest z (z^2 plus SMOOTH times its third
    differences squared; strict_smooth times those within STRICT_NEAR frames of a strict frame with no need there, SMOOTH
    when not given) that is at least `need`, never negative, and keeps the pelvis's downward acceleration (fall_down [F],
    units/s^2, + down) within `allowed` [F]: z's second difference at most (allowed - fall_down) / FPS^2 (a lowered pelvis
    falls faster where z bends up), or 0 where the input is past it already, except on the strict frames, which it brings
    within (z bends down there).  A window that has no such z keeps the least violation the solve reached (solved False)"""
    window = DROP_WINDOW if window is None else window
    strict = np.zeros(F, dtype=bool) if strict is None else np.asarray(strict, dtype=bool)
    weight_of = np.full(F, SMOOTH)
    if strict_smooth is not None and strict.any():
        near = np.convolve(strict.astype(float), np.ones(2 * STRICT_NEAR + 1), mode="same") > 0.5
        needy = np.convolve((np.asarray(need) > 0.0).astype(float), np.ones(2 * STRICT_NEAR + 1), mode="same") > 0.5
        weight_of = np.where(near & ~needy, float(strict_smooth), SMOOTH)
    z = np.zeros(F)
    rows = []
    wins = []
    for a, b in runs((need > 0.0) | strict):
        w0, w1 = max(0, a - window), min(F - 1, b + window)
        if wins and w0 - PAD <= wins[-1][1] + PAD + 1:     # (padded ranges that meet are solved together: each window's
            wins[-1] = (wins[-1][0], w1)                    # pinned frames would write naught over the other's own)
        else:
            wins.append((w0, w1))
    for w0, w1 in wins:
        # (the window and PAD frames each side pinned to 0: the frames just outside it are bound too, their second
        # differences reach into it)
        p0, p1 = max(0, w0 - PAD), min(F - 1, w1 + PAD)
        n = p1 - p0 + 1
        D2, D3 = _diff_matrix(n, 2, p0, F), _diff_matrix(n, 3, p0, F)
        w = weight_of[p0:p1 + 1]
        H = 2.0 * (np.eye(n) + D3.T @ (w[:, None] * D3))
        A_eq, b_eq, A_in, b_in = [], [], [], []
        for k in range(n):
            t = p0 + k
            e = np.zeros(n)
            e[k] = 1.0
            if t < w0 or t > w1:
                A_eq.append(e)
                b_eq.append(0.0)
            else:
                A_in.append(e)
                b_in.append(max(float(need[t]), 0.0))
            if 0 < t < F - 1:                    # (every frame: in the air too, no faster than the dance's own fall)
                lim = (float(allowed[t]) - float(fall_down[t])) / (FPS * FPS)
                A_in.append(-D2[k])
                b_in.append(-(lim if strict[t] else max(lim, 0.0)))
        x, act, rounds, ok = solve_qp(H, np.array(A_eq) if A_eq else np.zeros((0, n)), np.array(b_eq), np.array(A_in),
                                      np.array(b_in), rounds=DROP_QP_ROUNDS, batch=16)
        z[p0:p1 + 1] = np.maximum(x, 0.0)
        rows.append({"window": [int(w0), int(w1)], "active": len(act), "rounds": rounds, "solved": bool(ok)})
    return z, rows


def flight_change(windows, air, floor_frames, com_y, pelvis_ys, fall_in, room, F, target=None):
    """the pelvis's change [F] (units) and per window its rows: the least change over each window (first, last) that makes
    the centre of mass's heights com_y [F] fall at target [F] (units/s^2 down; gravity where None) on the air frames with
    air on both sides (air [F]), keeps every frame on the floor (floor_frames [F]) of every height in pelvis_ys falling no
    faster than FALL_BOUND (or fall_in [F], the input's, where it is faster) and under `room` [F] (how far the pelvis may
    rise there, NaN for no bound), weighted SMOOTH on the third differences"""
    change = np.zeros(F)
    rows = []
    for w0, w1 in windows:
        p0, p1 = max(0, w0 - PAD), min(F - 1, w1 + PAD)
        n = p1 - p0 + 1
        idx = np.arange(p0, p1 + 1)
        D2, D3 = _diff_matrix(n, 2, p0, F), _diff_matrix(n, 3, p0, F)
        H = 2.0 * (np.eye(n) + SMOOTH * D3.T @ D3)
        eq_rows, eq_b, in_rows, in_b = [], [], [], []
        for k, t in enumerate(idx):
            g = (G if target is None else float(target[t])) / (FPS * FPS)
            if t < w0 or t > w1:                # (pinned: the frames just outside the window, bound below)
                e = np.zeros(n)
                e[k] = 1.0
                eq_rows.append(e)
                eq_b.append(0.0)
            if t <= 0 or t >= F - 1:
                continue
            if air[t] and air[t - 1] and air[t + 1] and w0 <= t <= w1:
                c2 = com_y[t + 1] - 2.0 * com_y[t] + com_y[t - 1]
                eq_rows.append(D2[k])
                eq_b.append(-g - c2)
            else:
                # every other frame of the window (the floor's, a flight's first and last, a short air): the pelvis falls
                # no faster than the bound or the dance's own fall there
                allowed = (max(FALL_BOUND, fall_in[t]) + FALL_TOL * 0.5) / (FPS * FPS)
                lo = max(-allowed - (y[t + 1] - 2.0 * y[t] + y[t - 1]) for y in pelvis_ys)
                in_rows.append(D2[k])
                in_b.append(lo)
                if floor_frames[t] and np.isfinite(room[t]):
                    e = np.zeros(n)
                    e[k] = -1.0
                    in_rows.append(e)
                    in_b.append(-max(room[t], 0.0))
        A_eq = np.array(eq_rows) if eq_rows else np.zeros((0, n))
        A_in = np.array(in_rows) if in_rows else np.zeros((0, n))
        x, act, rounds, ok = solve_qp(H, A_eq, np.array(eq_b), A_in, np.array(in_b))
        change[p0:p1 + 1] = x
        rows.append({"window": [int(w0), int(w1)], "equalities": len(eq_rows), "active": len(act), "rounds": rounds,
                     "solved": bool(ok)})
    return change, rows


# ---- the layer -------------------------------------------------------------------------------------------------------

def default_params():
    return {"floor_y": None, "ground": True, "plant": True, "drop": True, "flight": True, "knee": True, "glide": True,
            "flight_band": True}


def body_com(model, motion, F):
    """the centre of mass [F, 3] (units) by tools/balance_layer.py's Body (de Leva's 16 segments, as tools/wb_dynamics.py),
    or None when the model has not the body that needs"""
    if model is None:
        return None
    bl = _tool("balance_layer")
    try:
        body = bl.Body(model, motion, F)
    except ValueError:
        return None
    return body.com()


def sole_hull(w, floor_y):
    """the convex hull [k, 2] (x, z) of a shoe's vertices w [N, 3] within SOLE_TOUCH of the floor, or of its lowest
    SOLE_TOUCH when none is that low (the part that will touch)"""
    y = w[:, 1]
    near = y <= max(floor_y, float(y.min())) + SOLE_TOUCH
    return _hull(w[near][:, [0, 2]])


def _hull(pts):
    pts = np.unique(np.round(np.asarray(pts, dtype=float), 9), axis=0)
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in pts[::-1]:
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])


def outside(p, poly):
    """how far (units, >= 0) the point p [2] lies outside the convex polygon poly [k, 2] (0 inside)"""
    poly = np.asarray(poly, dtype=float)
    if len(poly) == 0:
        return float("inf")
    if len(poly) == 1:
        return float(np.linalg.norm(p - poly[0]))

    def seg(a, b):
        ab = b - a
        t = np.clip(np.dot(p - a, ab) / max(float(np.dot(ab, ab)), 1e-18), 0.0, 1.0)
        return float(np.linalg.norm(p - (a + t * ab)))
    if len(poly) == 2:
        return seg(poly[0], poly[1])
    k = len(poly)
    cr = [(poly[(i + 1) % k][0] - poly[i][0]) * (p[1] - poly[i][1]) - (poly[(i + 1) % k][1] - poly[i][1]) * (p[0] - poly[i][0])
          for i in range(k)]
    if all(c >= 0 for c in cr) or all(c <= 0 for c in cr):
        return 0.0
    return min(seg(poly[i], poly[(i + 1) % k]) for i in range(k))


class Composer:
    """the layer's keys on top of a dance's (keys: IK.sample's; sol: its solve): 足ＩＫ moved by world offsets [F, 3] per
    side, センター by a world height [F], and 足首 turned on the frames where a leg moved so that its foot keeps the input's
    turn in the world (the toe IK starts on its goal, as the foot layer keys it): the foot moves as one piece.  The knee
    step also turns a standing foot (its world turn) and puts つま先ＩＫ's goal at a given place from 足ＩＫ's"""

    def __init__(self, rig, motion, keys, sol, F):
        self.rig, self.motion, self.keys, self.sol, self.F = rig, motion, keys, sol, F
        self.frames = list(range(F))
        self.ci = rig.by_name["センター"]
        self.legs = [rig.sides[s].leg_ik for s in SIDES]
        self.ankles = [rig.sides[s].ankle for s in SIDES]
        self.toe_iks = [rig.sides[s].toe_ik for s in SIDES]
        self.with_toes = False
        self.parent_c = FL._parent_world_turn(rig, keys, self.ci)
        self.parent_ik = {}
        for s in SIDES:
            rot = keys[rig.sides[s].leg_ik][1]
            self.parent_ik[s] = qmul(sol[s]["q_ik"], qconj(FL.qnormalize_rows(np.asarray(rot, dtype=float))))

    def compose(self, offsets, centre_dy, turns=None, toes=None):
        """(the new keys, their solve).  turns: side -> world turns [F, 4] of the foot (the identity where none); toes: side
        -> つま先ＩＫ's goal less 足ＩＫ's [F, 3] in the world (NaN rows: つま先ＩＫ's key as it was, its goal moving with
        足ＩＫ)"""
        F = self.F
        new = dict(self.keys)
        for s in SIDES:
            sd = self.rig.sides[s]
            pos, rot = self.keys[sd.leg_ik]
            new[sd.leg_ik] = (pos + qrot(qconj(self.parent_ik[s]), offsets[s]), rot)
            t = None if toes is None else toes.get(s)
            if t is not None and np.isfinite(t).all(axis=1).any():
                put = np.isfinite(t).all(axis=1)
                d0 = np.array(self.rig.bones[sd.toe_ik].position) - np.array(self.rig.bones[sd.leg_ik].position)
                key = qrot(qconj(self.sol[s]["q_ik"]), np.where(put[:, None], t, 0.0)) - d0
                tpos, trot = self.keys[sd.toe_ik]
                new[sd.toe_ik] = (np.where(put[:, None], key, tpos), trot)
                self.with_toes = True
        pos_c, rot_c = self.keys[self.ci]
        new[self.ci] = (pos_c + qrot(qconj(self.parent_c), np.stack([np.zeros(F), centre_dy, np.zeros(F)], 1)), rot_c)
        moved = IK.solve(self.rig, self.motion, self.frames, new)
        for s in SIDES:
            sd = self.rig.sides[s]
            pos, rot = self.keys[sd.ankle]
            t = None if turns is None else turns.get(s)
            turned = np.zeros(F, dtype=bool) if t is None else (np.abs(np.asarray(t)[:, :3]).max(axis=1) > 1e-12)
            changed = (np.abs(offsets[s]).max(axis=1) > 1e-9) | (np.abs(centre_dy) > 1e-9) | turned
            foot = self.sol[s]["q_foot"]
            if turned.any():
                foot = np.where(turned[:, None], qmul(t, foot), foot)
            local = FL.qnormalize_rows(qmul(qconj(moved[s]["q_shin"]), foot))
            new[sd.ankle] = (pos, np.where(changed[:, None], local, np.asarray(rot, dtype=float)))
        return new, IK.solve(self.rig, self.motion, self.frames, new)

    def written(self):
        return self.legs + [self.ci] + self.ankles + (self.toe_iks if self.with_toes else [])

    def build(self, new):
        return FL.build(self.motion, {self.rig.bones[i].name: new[i] for i in self.written()}, self.F)


def foot_pivots(o, w, q_foot, touch=TOUCH):
    """(the front, the back [F, 3]) of the part of the shoe that touches (its lower shell's vertices w [F, N, 3] within
    `touch` of its lowest) along the foot's forward axis on the floor (q_foot [F, 4]: the foot's world turns)"""
    a = qrot(q_foot, o.a0)
    a = a * np.array([1.0, 0.0, 1.0])
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)
    y = w[:, :, 1]
    near = y <= y.min(axis=1, keepdims=True) + touch
    along = np.einsum("fnk,fk->fn", w, a)
    idx = np.arange(len(w))
    front = np.where(near, along, -np.inf).argmax(axis=1)
    back = np.where(near, along, np.inf).argmin(axis=1)
    return w[idx, front], w[idx, back]


def foot_turned(c, axis, angles, goal, shell):
    """(the goals [n, 3], the turns [n, 4]) of a standing foot turned by each of `angles` (radians, + onto the toes) about
    `axis` through the point c, its goal (足ＩＫ) at `goal` and its shoe's lower shell at `shell` [N, 3] before: the foot
    then lowered or raised so that the shoe's lowest point stays where it was (the toes or the heel on the floor)"""
    q = IK.qaxis(np.broadcast_to(np.asarray(axis, dtype=float), (len(angles), 3)), np.asarray(angles, dtype=float))
    low0 = float(shell[:, 1].min())
    rel = shell - c
    low = c[1] + qrot(q[:, None, :], rel[None, :, :])[:, :, 1].min(axis=1)
    goals = c + qrot(q, goal - c)
    goals[:, 1] += low0 - low
    return goals, q


def carry_to_edges(turn, stance, edge=None, allow=None):
    """the turns [F] (degrees, signed) with a turn within `edge` frames of a standing run's end, and nearer its end than its
    start, held on to that end where the foot lifts after it (and one nearer its start held back to the start where the
    foot lands before it): the larger of the same sign carried over, as far as allow(frame, turn) lets it (a frame that
    does not take it stops the carry)"""
    edge = KNEE_EDGE if edge is None else edge
    out = np.array(turn, dtype=float)
    F = len(out)

    def take(t, src):
        if abs(out[src]) > abs(out[t]) and out[src] * out[t] >= 0.0:
            if allow is not None and not allow(t, out[src]):
                return False
            out[t] = out[src]
        return True
    for a, b in runs(stance):
        if b < F - 1:                                   # the foot lifts after b
            for t in range(max(a, b - edge + 1) + 1, b + 1):
                src = t - 1
                if b - src < src - a and not take(t, src):
                    break
        if a > 0:                                       # the foot lands at a
            for t in range(min(b, a + edge - 1) - 1, a - 1, -1):
                src = t + 1
                if src - a < b - src and not take(t, src):
                    break
    return out


def edge_turns(turn, stance, edge=None):
    """the turns [F] of a standing foot kept only as a block that reaches the end of its run where it lifts (a push-off
    holds the heel up until the foot leaves the floor) or its start where it lands (a heel strike keeps the toes up from
    the landing), within `edge` frames of it; a turn in the middle of a run, or one cut off from the run's end, would raise
    the heel (or the toes) for a frame and set it down again, a flick of the foot, and is left out (the review of kneepop,
    2026-10-17: retarget's 251.0 s, a heel up 8 and 10 degrees on every other frame of a stand)"""
    edge = KNEE_EDGE if edge is None else edge
    turn = np.asarray(turn, dtype=float)
    F = len(turn)
    out = np.zeros(F)
    for a, b in runs(stance):
        if b < F - 1:                                   # the foot lifts after b
            t = b
            while t >= max(a, b - edge + 1) and abs(turn[t]) > 1e-9:
                out[t] = turn[t]
                t -= 1
        if a > 0:                                       # the foot lands at a
            t = a
            while t <= min(b, a + edge - 1) and abs(turn[t]) > 1e-9:
                out[t] = turn[t]
                t += 1
    return out


def knee_turn(hip, goal, target, c_front, c_back, axis, shell, sign=0.0, least=0.0, steps=None):
    """(the least turn (degrees: + onto the toes about c_front, - onto the heel about c_back; `sign` keeps one of them) of a
    standing foot, no smaller than `least` (degrees, of that sign), that brings the hip's distance to its goal to `target`,
    whether one does): the turn that brings it nearest where none does, 0 where no turn brings it nearer"""
    steps = np.radians(np.arange(0.0, KNEE_PITCH_MAX + 1e-9, KNEE_PITCH_STEP)) if steps is None else steps
    options = []                                # (the turn, reaches the target, the distance it brings, the sign)
    for sg, c in ((1.0, c_front), (-1.0, c_back)):
        if sign and sg != sign:
            continue
        st = steps[steps >= math.radians(abs(least)) - 1e-12] if sign else steps
        goal_t, _ = foot_turned(c, axis, sg * st, goal, shell)
        d = np.linalg.norm(hip - goal_t, axis=1)
        ok = np.flatnonzero(d <= target + 1e-6)
        j = int(ok[0]) if len(ok) else int(np.argmin(d))
        options.append((float(st[j]), bool(len(ok)), float(d[j]), sg))
    reached = [x for x in options if x[1]]
    pick = min(reached, key=lambda x: x[0]) if reached else min(options, key=lambda x: x[2])
    return pick[3] * math.degrees(pick[0]), bool(reached)


def knee_plan(rig, shoe, sol, stance):
    """(side -> world offsets [F, 3] to add to its 足ＩＫ, side -> world turns [F, 4] of its foot, side -> つま先ＩＫ's goal
    less 足ＩＫ's [F, 3] (NaN: as it was), the plan) of the knee step on `sol`, the solve of the composed dance (6. in the
    module's doc).  Per side knee_targets on the hip's distance to the goal.  A swing frame's goal moves toward the hip by
    what is too long, its toe IK's goal by as much as MMD's ankle (a goal beyond the reach moves further than the ankle: the
    foot keeps its turn).  A standing foot turns about the front of the part of its shoe that touches (onto its toes) or
    about its back (onto its heel), by the least turn of the two (knee_turn) that brings the distance down to the target
    (its last frame before it lifts onto its toes only: a push-off), the shoe's lowest point kept where it was, held on to
    the end of the run within KNEE_EDGE frames of a lift or a landing (carry_to_edges) as long as it does not straighten the
    knee there: its toes (or heel) stay on the floor where they stand.  A standing foot whose goal MMD's ankle does not reach (by IK_MISS: its foot is not where the plan
    stands it, but short of it in the air), or that no turn brings to its target on the first or the last frame of its
    run (it then lands a frame late, or lifts a frame early), moves as a swing foot does.  A turn held on bends that frame
    more, so the targets are found again on the distances the changes leave, KNEE_PLAN_ROUNDS times at most (only ever
    bending more).  Only the frames of the knee's jumps on the dance as it comes (near_jumps: rig_check's count) and the
    frames KNEE_JUMP_NEAR round them are bent, and a standing foot is turned only within KNEE_EDGE frames of a lift or a
    landing (edge_turns; a standing frame whose turn is left out keeps its own goal)"""
    F = len(stance[SIDES[0]])
    offsets, turns, toes, plan = {}, {}, {}, {}
    steps = np.radians(np.arange(0.0, KNEE_PITCH_MAX + 1e-9, KNEE_PITCH_STEP))
    for s in SIDES:
        L1, L2, rest_deg, least = knee_geometry(rig, s)
        leg = sol[s]
        hip, g, t_goal = leg["hip"], leg["goal_ankle"], leg["goal_toe"]
        D = np.linalg.norm(g - hip, axis=1)
        only = near_jumps(knee_bend(D, L1, L2, rest_deg, least))
        # the frames whose foot moves as a swing foot's: the swing, and a standing foot MMD leaves short of its goal
        free = ~np.asarray(stance[s], dtype=bool) | (leg["reach"] > IK_MISS)
        goal = g.copy()
        deg = np.zeros(F)
        pivots = None
        first = None
        rounds = 0
        for rounds in range(1, KNEE_PLAN_ROUNDS + 1):
            Dr = np.linalg.norm(goal - hip, axis=1)
            kt = knee_targets(Dr, L1, L2, rest_deg, least, only=only)
            first = kt if first is None else first
            excess = Dr - kt["target"]
            need = excess > KNEE_TOL
            if not need.any():
                break
            on = need & ~free
            if on.any():
                if pivots is None:
                    o = shoe.sides[s]
                    w = FL.shell_world(o, leg)
                    pivots = foot_pivots(o, w, leg["q_foot"]) + (FL.toes_down_axis(o, leg["q_foot"]), w)
                front, back, axis, w = pivots
                for t in np.flatnonzero(on):
                    lifts = t < F - 1 and free[t + 1]           # (its last frame before it lifts: a push-off, onto the toes)
                    d_t, ok = knee_turn(hip[t], g[t], kt["target"][t], front[t], back[t], axis[t], w[t],
                                        sign=float(np.sign(deg[t])) or (1.0 if lifts else 0.0), least=abs(deg[t]),
                                        steps=steps)
                    edge = (t == 0 or free[t - 1]) or (t == F - 1 or free[t + 1])
                    if not ok and edge and deg[t] == 0.0:
                        free[t] = True      # (no turn brings it there on the frame it lifts off or lands on: it moves,
                                            # lifting a frame early or landing a frame late)
                    else:
                        deg[t] = d_t
                st = ~free

                def straighter(t, d, Dr=Dr):        # (a turn held on that would take the ankle further from the hip there)
                    c = front[t] if d > 0.0 else back[t]
                    return np.linalg.norm(hip[t] - foot_turned(c, axis[t], np.array([math.radians(d)]), g[t], w[t])[0][0]) <= Dr[t] + 1e-9
                deg = edge_turns(np.where(st, carry_to_edges(deg, st, allow=straighter), 0.0), st)
                goal[st] = g[st]                    # (a standing foot's goal is where its turn puts it, or its own)
                for t in np.flatnonzero(np.abs(deg) > 1e-9):
                    goal[t] = foot_turned(front[t] if deg[t] > 0.0 else back[t], axis[t], np.array([math.radians(deg[t])]),
                                          g[t], w[t])[0][0]
            sw = need & free
            goal[sw] = goal[sw] + (hip - goal)[sw] / Dr[sw, None] * excess[sw, None]
        st = ~free
        off = goal - g
        turn = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (F, 1))
        toe = np.full((F, 3), np.nan)
        # the toe IK's goal goes where MMD's ankle goes (the new goal is in reach), not where the goal goes (つま先ＩＫ a
        # child of 足ＩＫ, as the foot layer keys it; another rig's toe goal is left to follow its own parent)
        hangs = rig.bones[rig.sides[s].toe_ik].parent == rig.sides[s].leg_ik
        moved = np.linalg.norm(off, axis=1) > 1e-12
        swing = moved & free
        gap = g - leg["ankle"]
        far = swing & (np.linalg.norm(gap, axis=1) > KNEE_TOE_TOL) & hangs
        toe[far] = (t_goal - g + gap)[far]
        standing = np.abs(deg) > 1e-9
        if standing.any():
            front, back, axis, w = pivots
            for t in np.flatnonzero(standing):
                q = IK.qaxis(axis[t], math.radians(deg[t]))
                turn[t] = q
                if hangs:
                    toe[t] = qrot(q, t_goal[t] - g[t])
        D_out = np.linalg.norm(goal - hip, axis=1)
        offsets[s], turns[s], toes[s] = off, turn, toe
        plan[s] = {"target": D_out, "bend0": first["bend0"], "bend": knee_bend(D_out, L1, L2, rest_deg, least),
                   "even": D_out < D - 1e-9, "reach": first["reach"], "cap": first["cap"], "excess": D - D_out,
                   "turn_deg": deg, "moved": np.linalg.norm(off, axis=1), "swing": swing, "standing": standing,
                   "toe_written": np.isfinite(toe).all(axis=1), "rounds": rounds}
    return offsets, turns, toes, plan


def layer(model, rig, shoe, motion, params=None):
    """(the output motion, the plan) of the contact layer on `motion` (see the module's doc).  model: formats.pmx Model
    (the body for the centre of mass; None: the hips stand for it), rig: leg_ik.LegRig, shoe: foot_layer.Shoe"""
    p = default_params()
    p.update(params or {})
    floor_y = FL.trace_floor(shoe) if p["floor_y"] is None else float(p["floor_y"])
    F = fk.last_frame(motion) + 1
    frames = list(range(F))
    keys = IK.sample(rig, motion, frames)
    sol = IK.solve(rig, motion, frames, keys)
    state = IK._State(rig, keys)
    pel = {n: np.asarray(state.world(rig.by_name[n])[0])[:, 1] for n in ("下半身", "センター") if n in rig.by_name}
    fall = np.max([down_acc(y) for y in pel.values()], axis=0)
    hips_y = np.mean([sol[s]["hip"][:, 1] for s in SIDES], axis=0)
    com = body_com(model, motion, F)
    if com is None:
        com = 0.5 * (sol["左"]["hip"] + sol["右"]["hip"])
    plan = {"F": F, "floor_y": floor_y, "sides": {}}
    judged, low, low_j, speed, rise, slip, lengths = {}, {}, {}, {}, {}, {}, {}
    for s in SIDES:
        o, leg = shoe.sides[s], sol[s]
        w = FL.shell_world(o, leg)
        L1, L2 = leg_lengths(rig, s)
        lengths[s] = (L1, L2)
        # judged at its goal where MMD's IK leaves the ankle off it by a little (a goal just out of the leg's reach, or a
        # nearly straight leg lagging behind its goal): what the dance puts there, and what a lowered pelvis or a push
        # will make of it; a foot left further off (a kick far out) is where MMD shows it
        short = (leg["reach"] > IK_MISS) & (leg["reach"] <= JUDGE_MISS)
        wj = w + np.where(short[:, None, None], (leg["goal_ankle"] - leg["ankle"])[:, None, :], 0.0)
        judged[s] = wj
        low[s] = w[:, :, 1].min(axis=1) - floor_y
        low_j[s] = wj[:, :, 1].min(axis=1) - floor_y
        sl = touch_slip(w)
        # where the leg does not reach its goal (the toe IK then turns MMD's foot toward its own goal as the hip moves):
        # the foot goes where its goal goes
        if F > 1:
            gm = np.diff(leg["goal_ankle"][:, [0, 2]], axis=0)
            either = short[:-1] | short[1:]
            sl[:-1] = np.where(either[:, None], gm, sl[:-1])
        slip[s] = sl
        v = np.linalg.norm(sl, axis=1) * UNIT_CM * FPS                  # (the step to the next frame)
        if F > 1:
            v[-1] = v[-2]
            v[1:] = np.minimum(v[1:], v[:-1])                           # the smaller of the steps into and out of a frame
        speed[s] = v
        rise[s] = step_min(low_j[s]) * UNIT_CM * FPS
    # 1. the plan
    on = {s: low_j[s] < ON_FLOOR for s in SIDES}
    flying = flight_frames(on, hips_y)
    stance, held = {}, {}
    for s in SIDES:
        cand = (~on[s]) & (low_j[s] < HOLD_MAX) & (speed[s] < HOLD_SPEED) & (rise[s] < HOLD_RISE) & ~flying
        h = np.zeros(F, dtype=bool)
        for a, b in runs(cand, HOLD_MIN):
            h[a:b + 1] = True
        held[s] = h
        stance[s] = bridge(on[s] | h, low_j[s], speed=speed[s])
    air = ~stance["左"] & ~stance["右"]
    # the glide (GLIDE_MAX): a run with no foot standing under a pelvis that does not fall as in a flight stands on its
    # lower foot where that shoe is just over the floor
    glide = {s: np.zeros(F, dtype=bool) for s in SIDES}
    if p.get("glide", True):
        lower = low_j["左"] <= low_j["右"]
        for a, b in runs(air, AIR_MIN):
            i0, i1 = max(a - 1, 0), min(b + 1, F - 1)
            if np.any(fall[i0:i1 + 1] > FALL_BOUND + FALL_TOL):
                continue                                            # a hop (no floor holds that fall)
            if i1 - i0 >= 2 and 2.0 * np.polyfit(np.arange(i0, i1 + 1) / FPS, hips_y[i0:i1 + 1], 2)[0] < -FLIGHT_FIT:
                continue                                            # a flight
            for s, m in (("左", lower), ("右", ~lower)):
                glide[s][a:b + 1] = m[a:b + 1] & (low_j[s][a:b + 1] < GLIDE_MAX)
        for s in SIDES:
            stance[s] = stance[s] | glide[s]
        air = ~stance["左"] & ~stance["右"]
    # the weight: the lever of the centre of mass's floor point between the standing feet's soles (share), and where a
    # standing leg cannot reach, whether the body needs that foot (the only one standing, or the centre of mass's floor
    # point more than NEED_CM outside the other foot's sole)
    centre_xz = com[:, [0, 2]]
    cen = {s: judged[s][:, :, [0, 2]].mean(axis=1) for s in SIDES}
    share = {}
    for s, o_ in (("左", "右"), ("右", "左")):
        ds = np.linalg.norm(centre_xz - cen[s], axis=1)
        do = np.linalg.norm(centre_xz - cen[o_], axis=1)
        share[s] = np.where(stance[s], np.where(stance[o_], do / np.maximum(ds + do, 1e-9), 1.0), 0.0)
    need = {s: np.zeros(F, dtype=bool) for s in SIDES}
    judged_need = {s: np.zeros(F, dtype=bool) for s in SIDES}
    other = {"左": "右", "右": "左"}

    def needed(s, frames_):
        o_ = other[s]
        for t in frames_:
            if not judged_need[s][t]:
                need[s][t] = (not stance[o_][t]) or outside(centre_xz[t], sole_hull(judged[o_][t], floor_y)) * UNIT_CM > NEED_CM
                judged_need[s][t] = True
        return need[s]
    # 2. ground: a standing foot over the floor comes down onto it
    dy = {s: (np.where(stance[s] & (low_j[s] >= ON_FLOOR), -low_j[s], 0.0) if p["ground"] else np.zeros(F)) for s in SIDES}
    # 3. reach: a standing leg reaches its (lowered) goal with the knee bent REACH_KNEE_DEG; a foot that bears weight gets
    # the pelvis lowered for it, a free one comes down only as far as its leg reaches
    reach_keep = {s: knee_reach(*lengths[s], REACH_KNEE_DEG) for s in SIDES}

    def as_far_as_it_reaches(s, mask, hip=None):
        hip = sol[s]["hip"] if hip is None else hip
        room0 = raise_room(hip, sol[s]["goal_ankle"], reach_keep[s])
        can = np.where(np.isfinite(room0), np.maximum(room0, 0.0), 0.0)
        dy[s] = np.where(mask, -np.minimum(-dy[s], can), dy[s])
    need_drop = np.zeros(F)
    for s in SIDES:
        g = sol[s]["goal_ankle"] + np.stack([np.zeros(F), dy[s], np.zeros(F)], 1)
        room = raise_room(sol[s]["hip"], g, reach_keep[s])
        # a lowered foot whose leg will not reach (with the knee bent REACH_KNEE_DEG), and a foot whose goal is on the
        # floor but MMD leaves it over it (the leg lagging, or just out of reach)
        short = (stance[s] & (dy[s] < 0.0) & ~(room >= -1e-9)) |                 (stance[s] & (dy[s] >= 0.0) & (low[s] > ON_FLOOR) & (low_j[s] < ON_FLOOR))
        if not short.any():
            continue
        nd = needed(s, np.flatnonzero(short))
        free = short & ~nd
        if free.any():
            as_far_as_it_reaches(s, free & (dy[s] < 0.0))
        bear = short & nd
        # only a foot that stands out of reach for REACH_MIN frames and more: a landing's or a take-off's leg reaching
        # for the floor a frame or two late is the dance's (lowering the body for it lands the foot early)
        held_long = np.zeros(F, dtype=bool)
        for a, b in runs(bear, REACH_MIN):
            held_long[a:b + 1] = True
        if (bear & ~held_long).any():
            as_far_as_it_reaches(s, bear & ~held_long & (dy[s] < 0.0))
        bear = held_long
        if bear.any() and p["drop"]:
            r = np.where(bear, np.where(np.isfinite(room), np.maximum(-room, np.maximum(low[s] - low_j[s], 0.0)), DROP_MAX), 0.0)
            need_drop = np.maximum(need_drop, np.minimum(r, DROP_MAX))
        elif bear.any():
            as_far_as_it_reaches(s, bear & (dy[s] < 0.0))
    comp = Composer(rig, motion, keys, sol, F)
    floor_frames = stance["左"] | stance["右"]
    allowed = np.maximum(FALL_BOUND, fall) + FALL_TOL * 0.5          # (the input's own where it is past the bound already)
    # the frames the input had in the air (both shoes AIR_CLEAR up, AIR_MIN frames running: the skirt's bound left them
    # free) that now stand and fall faster than the bound: brought within it
    up = np.logical_and.reduce([low[s] >= AIR_CLEAR - 0.0125 for s in SIDES])
    input_air = np.zeros(F, dtype=bool)
    for a, b in runs(up, AIR_MIN):
        input_air[a:b + 1] = True
    strict = floor_frames & input_air & (fall > FALL_BOUND + FALL_TOL)
    allowed = np.where(strict, FALL_BOUND + FALL_TOL * 0.5, allowed)
    drop = np.zeros(F)
    drop_rows, drop_rounds, drop_windows = [], [], []
    if np.any(need_drop > 0.0) or strict.any():
        # the least smooth lowering that lets the weight-bearing legs reach, within the bound on the floor's frames, then
        # checked on MMD's IK: a nearly straight leg stops short of a goal it reaches on paper (the balance layer's 1.5 cm
        # slack), so a weight-bearing foot still over the floor gets that much more
        target = need_drop > 0.0                # (the weight-bearing feet standing out of reach REACH_MIN frames and more)
        for rnd in range(DROP_ROUNDS):
            drop, drop_windows = drop_profile(np.minimum(need_drop, DROP_MAX), floor_frames, fall, allowed, F, strict=strict,
                                              strict_smooth=STRICT_SMOOTH)
            offs = {s: np.stack([np.zeros(F), dy[s], np.zeros(F)], 1) for s in SIDES}
            _, trial = comp.compose(offs, -drop)
            more = np.zeros(F)
            for s in SIDES:
                lo_ = FL.shell_world(shoe.sides[s], trial[s])[:, :, 1].min(axis=1) - floor_y
                over = target & stance[s] & (lo_ > LAND_TOL) & (dy[s] + low_j[s] < ON_FLOOR)
                if over.any():
                    nd = needed(s, np.flatnonzero(over))
                    more = np.maximum(more, np.where(over & nd, lo_, 0.0))
            drop_rounds.append({"round": rnd, "frames_over": int((more > 0.0).sum()), "max_cm": _r(float(more.max()) * UNIT_CM, 2)})
            if not np.any(more > 0.0) or rnd == DROP_ROUNDS - 1:
                break
            need_drop = np.minimum(np.where(more > 0.0, np.maximum(need_drop, drop) + more, need_drop), DROP_MAX)
        drop_rows = [{"s": [round(a / FPS, 2), round((b + 1) / FPS, 2)], "need_cm": _r(float(need_drop[a:b + 1].max()) * UNIT_CM, 2),
                      "drop_cm": _r(float(drop[a:b + 1].max()) * UNIT_CM, 2),
                      "short_cm": _r(float(np.max(need_drop[a:b + 1] - drop[a:b + 1])) * UNIT_CM, 2)}
                     for a, b in runs(need_drop > 0.0)]
        # a weight-bearing foot whose drop was lessened: lowered only as far as the lowered hips let its leg reach
        for s in SIDES:
            hip = sol[s]["hip"] - np.stack([np.zeros(F), drop, np.zeros(F)], 1)
            g = sol[s]["goal_ankle"] + np.stack([np.zeros(F), dy[s], np.zeros(F)], 1)
            room = raise_room(hip, g, reach_keep[s])
            bad = stance[s] & (dy[s] < 0.0) & ~(room >= -1e-6)
            if bad.any():
                as_far_as_it_reaches(s, bad, hip)
        # MMD's IK still stops a nearly straight leg short of a goal it reaches: push the goal on by what is left (the
        # foot layer's push, at most PUSH_STEP a round), keeping a frame's push only where it brings the shoe down
        best = None
        for rnd in range(PUSH_ROUNDS):
            offs = {s: np.stack([np.zeros(F), dy[s], np.zeros(F)], 1) for s in SIDES}
            _, trial = comp.compose(offs, -drop)
            lows = {s: FL.shell_world(shoe.sides[s], trial[s])[:, :, 1].min(axis=1) - floor_y for s in SIDES}
            if best is not None:
                for s in SIDES:
                    worse = lows[s] > best[1][s] + 1e-6
                    dy[s] = np.where(worse, best[0][s], dy[s])
                    lows[s] = np.where(worse, best[1][s], lows[s])
            best = ({s: dy[s].copy() for s in SIDES}, lows)
            pushed = False
            for s in SIDES:
                over = target & stance[s] & (lows[s] > LAND_TOL) & (dy[s] + low_j[s] < ON_FLOOR)
                if over.any():
                    dy[s] = np.where(over, dy[s] - np.minimum(lows[s], PUSH_STEP), dy[s])
                    pushed = True
            drop_rounds.append({"push_round": rnd, "frames_over": int(sum(int((target & stance[s] & (lows[s] > LAND_TOL)).sum()) for s in SIDES))})
            if not pushed:
                break
    dy_e = {s: eased_lowering(dy[s], stance[s], low[s], speed=speed[s]) for s in SIDES}
    # (a frame the dance falls through faster than the bound is the air: the easing does not bring a shoe down into the
    # band the skirt's bound counts as standing there)
    fast_fall = fall > FALL_BOUND + FALL_TOL
    for s in SIDES:
        floor_at = np.minimum(np.maximum(low[s], 0.0), AIR_CLEAR)
        keep = fast_fall & ~stance[s] & (low[s] + dy_e[s] < floor_at)
        dy_e[s] = np.where(keep, floor_at - low[s], dy_e[s])
    # 4. plant: a standing foot does not travel: held where the dance puts it down, both ways from there, while its knee
    # stays within KNEE_GIVE of the leg's without the hold
    hips_low = {s: sol[s]["hip"] - np.stack([np.zeros(F), drop, np.zeros(F)], 1) for s in SIDES}
    corr, plant_rows = {}, {}
    for s in SIDES:
        c = np.zeros((F, 2))
        rows = []
        if p["plant"]:
            # the share of each step undone: the slow ones and the jumps (held_share: PLANT_POP, PLANT_SPIKE)
            undo = held_share(np.linalg.norm(slip[s], axis=1) * UNIT_CM, stance[s])
            e = hips_low[s] - (sol[s]["goal_ankle"] + np.stack([np.zeros(F), dy_e[s], np.zeros(F)], 1))
            r_lo, r_hi = plant_band(e, *lengths[s])
            for a, b in runs(stance[s]):
                put = np.flatnonzero(on[s][a:b + 1])
                k0 = a + (int(put[0]) if len(put) else int(np.argmin(low_j[s][a:b + 1])))
                limited = 0
                for t in range(k0, b):
                    c[t + 1], lim = held_within(c[t] - undo[t] * slip[s][t], e[t + 1], r_lo[t + 1], r_hi[t + 1])
                    limited += int(lim)
                for t in range(k0, a, -1):
                    c[t - 1], lim = held_within(c[t] + undo[t - 1] * slip[s][t - 1], e[t - 1], r_lo[t - 1], r_hi[t - 1])
                    limited += int(lim)
                if b > a:
                    n = np.linalg.norm(c[a:b + 1], axis=1) * UNIT_CM
                    rows.append({"s": [round(a / FPS, 2), round((b + 1) / FPS, 2)], "put_s": round(k0 / FPS, 2),
                                 "start_cm": _r(float(n[0]), 2), "end_cm": _r(float(n[-1]), 2), "max_cm": _r(float(n.max()), 2),
                                 "limited_frames": limited})
            c = swing_blend(c, stance[s], F)
        corr[s] = c
        plant_rows[s] = rows
    # 5. flight: the pelvis's change, solved on the body's centre of mass as the changed dance moves it (the legs
    # straighten or fold where the feet do not go with the body: the centre of mass follows the pelvis by less than one)
    pelvis_ys = [y - drop for y in pel.values()]
    change = np.zeros(F)
    flight_rows = []
    flights = [(a, b) for a, b in runs(air) if b - a + 1 >= AIR_MIN]
    lift = {s: np.stack([corr[s][:, 0], dy_e[s], corr[s][:, 1]], 1) for s in SIDES}
    goals = {s: sol[s]["goal_ankle"] + lift[s] for s in SIDES}
    away = {}
    for s in SIDES:                     # 0 on the floor, CARRY_RAMP frames off it and further: 1
        k = np.full(F, 10 ** 6, dtype=float)
        idx = np.flatnonzero(stance[s])
        if len(idx):
            pos = np.searchsorted(idx, np.arange(F))
            left = np.where(pos > 0, np.arange(F) - idx[np.maximum(pos - 1, 0)], 10 ** 6)
            right = np.where(pos < len(idx), idx[np.minimum(pos, len(idx) - 1)] - np.arange(F), 10 ** 6)
            k = np.minimum(left, right).astype(float)
        away[s] = np.minimum(k / CARRY_RAMP, 1.0)

    flying_frames = np.zeros(F, dtype=bool)
    for a, b in flights:
        flying_frames[a:b + 1] = True

    def offsets_of(ch):
        """the feet's offsets with the change ch of the pelvis: a foot in the air goes with the body (the leg keeps the
        dance's shape), from half on its first frame off the floor (and its last before landing) to all, never into the
        floor; in a flight both shoes clear the floor by AIR_CLEAR (a flight is the air: the skirt's bound counts a shoe
        lower than that as standing)"""
        cr, offs = {}, {}
        for s in SIDES:
            cr[s] = np.where(~stance[s], away[s] * ch, 0.0)
            room = np.where(speed[s] > PLANT_SPEED, np.maximum(low[s] + dy_e[s] - SWING_CLEAR, 0.0),
                            np.maximum(low[s] + dy_e[s] - FL.PEN_TOL, 0.0))     # (a swing is not carried onto the floor)
            cr[s] = np.maximum(cr[s], -room)
            h = low[s] + dy_e[s] + cr[s]
            cr[s] = np.where(flying_frames & (h < AIR_CLEAR), cr[s] + (AIR_CLEAR - h), cr[s])
            offs[s] = lift[s] + np.stack([np.zeros(F), cr[s], np.zeros(F)], 1)
        return offs, cr
    wrows, resid = [], []
    if p["flight"] and flights:
        wins = []
        for a, b in flights:
            w0, w1 = max(1, a - WINDOW), min(F - 2, b + WINDOW)
            # (windows whose padded ranges meet are solved together: one window's pinned frames written over the other's
            # own change broke the bound on the floor between them, the song's 63.2 s at 136 units/s^2, v11feet)
            if wins and w0 - PAD <= wins[-1][1] + PAD + 1:
                wins[-1] = (wins[-1][0], w1)
            else:
                wins.append((w0, w1))
        room = np.full(F, np.inf)
        for s in SIDES:
            r = raise_room(hips_low[s], goals[s], reach_keep[s])
            r = np.where(np.isfinite(r), r, 0.0)
            room = np.where(stance[s], np.minimum(room, r), room)
        room = np.where(np.isfinite(room), room, np.nan)
        fall_in = allowed - FALL_TOL * 0.5                              # (flight_change adds its own margin)
        in_flight = np.zeros(F, dtype=bool)
        for a, b in flights:
            in_flight[a:b + 1] = True
        interior = np.zeros(F, dtype=bool)
        interior[1:-1] = in_flight[1:-1] & in_flight[:-2] & in_flight[2:]
        ref = pelvis_ys[0]                          # the pelvis's height (lowered by the drop)
        base = limb_smoothed(com[:, 1] - drop, ref)
        target = np.full(F, G)                      # each flight's fall: the dance's own within FLIGHT_BAND
        if p.get("flight_band", True):
            for a, b in flights:
                if b - a + 1 >= 3:
                    own = -2.0 * np.polyfit(np.arange(a, b + 1) / FPS, base[a:b + 1], 2)[0]
                    target[a:b + 1] = min(max(own, FLIGHT_BAND[0]), FLIGHT_BAND[1])
        com_out = None
        for it in range(FLIGHT_ROUNDS):
            change, wrows = flight_change(wins, in_flight, floor_frames, base, pelvis_ys, fall_in, room, F, target=target)
            offs, _ = offsets_of(change)
            new, _ = comp.compose(offs, change - drop)
            com_out = body_com(model, comp.build(new), F)
            if com_out is None:                     # (no body: the hips stand for the centre of mass, moved with the pelvis)
                break
            smooth_out = limb_smoothed(com_out[:, 1], ref + change)
            r = down_acc(smooth_out)[interior] - target[interior]
            resid.append(_r(float(np.abs(r).max()) if len(r) else 0.0, 2))
            if not len(r) or np.abs(r).max() < FLIGHT_RESID:
                break
            base = smooth_out - change
        for a, b in flights:
            row = {"s": [round(a / FPS, 2), round((b + 1) / FPS, 2)], "frames": b - a + 1,
                   "rise_cm": _r(float(change[a:b + 1].max()) * UNIT_CM, 2),
                   "fall_cm": _r(float(-change[a:b + 1].min()) * UNIT_CM, 2), "com_acc_target": _r(-float(target[a]), 1)}
            if a >= 1 and b + 2 <= F and b - a + 1 >= 3:
                tt = np.arange(b - a + 3) / FPS
                row["com_acc_before"] = _r(2.0 * np.polyfit(tt, com[a - 1:b + 2, 1] - drop[a - 1:b + 2], 2)[0], 1)
                if com_out is not None:
                    row["com_acc_after"] = _r(2.0 * np.polyfit(tt, com_out[a - 1:b + 2, 1], 2)[0], 1)
            flight_rows.append(row)
    offsets, carry = offsets_of(change)
    centre_dy = change - drop
    plan["sides"] = {s: {"stance": stance[s], "held": held[s], "glide": glide[s], "on": on[s], "need": need[s], "share": share[s],
                         "dy": dy_e[s],
                         "plant": corr[s], "carry": carry[s], "low": low[s], "low_judged": low_j[s], "speed": speed[s],
                         "plant_rows": plant_rows[s]} for s in SIDES}
    plan.update({"air": air, "flying": flying, "strict": strict, "drop": drop, "change": change, "drop_rows": drop_rows,
                 "drop_rounds": drop_rounds, "drop_windows": drop_windows,
                 "flight_rows": {"flights": flight_rows, "windows": wrows, "rounds_resid": resid}, "fall_in": fall,
                 "com": com})
    moved = any(float(np.abs(offsets[s]).max()) > 1e-9 for s in SIDES) or float(np.abs(centre_dy).max()) > 1e-9
    # 6. the knee at the end of its reach, on the dance as the steps above leave it (the hip's distance to the goal is
    # final there: the knee step moves no pelvis)
    turns = toes = None
    plan["knee"] = {}
    if p["knee"]:
        before = comp.compose(offsets, centre_dy)[1] if moved else sol
        k_off, k_turn, k_toe, plan["knee"] = knee_plan(rig, shoe, before, stance)
        if any(float(np.abs(k_off[s]).max()) > 1e-9 for s in SIDES):
            offsets = {s: offsets[s] + k_off[s] for s in SIDES}
            turns, toes = k_turn, k_toe
            moved = True
    if not moved:
        plan["sub_raise"] = {s: np.zeros(F) for s in SIDES}
        plan["written"] = []
        return motion, plan
    new, out_sol = comp.compose(offsets, centre_dy, turns, toes)
    # 7. the frames and between them: a frame whose shoe the layer leaves deeper in the floor than the input's (a push that
    # overshoots) is raised by the excess, and both frames of an interval whose shoe dips into the floor further than the
    # input's did between them
    sub = {s: np.zeros(F) for s in SIDES}
    dip_in = {}
    written_idx = comp.written()
    for _ in range(SUB_ROUNDS if F > 1 else 0):
        framed = False
        for s in SIDES:
            up = frame_raise(FL.shell_world(shoe.sides[s], out_sol[s])[:, :, 1].min(axis=1) - floor_y, low[s])
            if up.any():
                framed = True
                sub[s] += up
                offsets[s][:, 1] += up
        if framed:
            new, out_sol = comp.compose(offsets, centre_dy, turns, toes)
        near = np.zeros(F - 1, dtype=bool)
        for s in SIDES:
            lo_ = FL.shell_world(shoe.sides[s], out_sol[s])[:, :, 1].min(axis=1)
            near |= np.minimum(lo_[:-1], lo_[1:]) < floor_y + SUB_NEAR
        idx = np.flatnonzero(near)
        if not len(idx):
            if framed:
                continue
            break
        todo = np.array([i for i in idx if int(i) not in dip_in], dtype=int)
        if len(todo):
            got = FL.sinks_between(rig, shoe, motion, keys, written_idx, todo, floor_y)
            for j, i in enumerate(todo):
                dip_in[int(i)] = {s: float(got[s][j]) for s in SIDES}
        sinks = FL.sinks_between(rig, shoe, motion, new, written_idx, idx, floor_y)
        raised = False
        for s, dip in sinks.items():
            before = np.array([max(dip_in[int(i)][s], 0.0) for i in idx])
            excess = dip - before
            up = np.zeros(F)
            d_ = np.where(excess > 0.25 * FL.PEN_TOL, excess + 0.25 * FL.PEN_TOL, 0.0)
            np.maximum.at(up, idx, d_)
            np.maximum.at(up, idx + 1, d_)
            if up.any():
                raised = True
                sub[s] += up
                offsets[s][:, 1] += up
        if not raised:
            if framed:
                continue
            break
        new, out_sol = comp.compose(offsets, centre_dy, turns, toes)
    plan["sub_raise"] = sub
    plan["written"] = sorted(rig.bones[i].name for i in written_idx)
    return comp.build(new), plan


# ---- the command -----------------------------------------------------------------------------------------------------

def untouched(before, after, written):
    names = set()
    for n in written:
        names |= {n, fk.vmd_name(n)}

    def rows(m):
        return sorted((k.name, k.frame, k.position, k.rotation, bytes(k.interpolation)) for k in m.bones if k.name not in names)
    a, b = rows(before), rows(after)
    return {"identical": a == b, "keys": len(a), "written": sorted(written),
            "morphs_identical": [(k.name, k.frame, k.weight) for k in before.morphs] == [(k.name, k.frame, k.weight) for k in after.morphs]}


def pelvis_report(rig, before, after, stance, F, drop=None, change=None):
    """the pelvis (下半身 and センター) before and after: the largest downward acceleration on the floor's frames (a foot
    standing in the plan) and the frames past FALL_BOUND there (after past it and faster than before by more than
    FALL_TOL) with what the lowering (drop) and the flight's change added there, the change of height"""
    out = {}
    ys = {}
    for tag, m in (("before", before), ("after", after)):
        keys = IK.sample(rig, m, range(F))
        st = IK._State(rig, keys)
        ys[tag] = {n: np.asarray(st.world(rig.by_name[n])[0])[:, 1] for n in ("下半身", "センター") if n in rig.by_name}
    fb = np.max([down_acc(y) for y in ys["before"].values()], axis=0)
    fa = np.max([down_acc(y) for y in ys["after"].values()], axis=0)
    out["floor_max_before"] = _r(float(fb[stance].max()) if stance.any() else 0.0, 1)
    out["floor_max_after"] = _r(float(fa[stance].max()) if stance.any() else 0.0, 1)
    past = stance & (fa > FALL_BOUND + FALL_TOL) & (fa > fb + FALL_TOL)
    out["floor_past_bound_after"] = int(past.sum())
    out["floor_past_bound_frames"] = [int(t) for t in np.flatnonzero(past)[:50]]
    if drop is not None and change is not None:
        rows = []
        for t in np.flatnonzero(past)[:50]:
            if 0 < t < F - 1:
                dd = (drop[t + 1] - 2.0 * drop[t] + drop[t - 1]) * FPS * FPS
                dc = -(change[t + 1] - 2.0 * change[t] + change[t - 1]) * FPS * FPS
                rows.append({"frame": int(t), "s": _r(t / FPS, 2), "before": _r(fb[t], 1), "after": _r(fa[t], 1),
                             "by_drop": _r(dd, 1), "by_flight": _r(dc, 1)})
        out["floor_past_bound_rows"] = rows
    d = ys["after"]["センター"] - ys["before"]["センター"]
    out["centre_change_cm"] = {"max_up": _r(float(d.max()) * UNIT_CM, 2), "max_down": _r(float(-d.min()) * UNIT_CM, 2),
                               "frames": int((np.abs(d) > 1e-6).sum())}
    return out


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def report_of(plan, rig, before, after, F):
    sides = plan["sides"]
    minutes = F / FPS / 60.0
    rep = {"frames": F, "floor_y": plan["floor_y"]}
    rep["plan"] = {}
    for s in SIDES:
        sd = sides[s]
        rep["plan"][TAGS[s]] = {"stance_frames": int(sd["stance"].sum()), "on_frames": int(sd["on"].sum()),
                                "held_frames": int(sd["held"].sum()), "held_runs": len(runs(sd["held"])),
                                "glide_frames": int(sd["glide"].sum()), "glide_runs": len(runs(sd["glide"])),
                                "need_frames": int((sd["need"] & sd["stance"]).sum())}
    st = sides["左"]["stance"].astype(int) + sides["右"]["stance"].astype(int)
    rep["plan"]["double_pct"] = _r(100.0 * float(np.mean(st == 2)), 2)
    rep["plan"]["single_pct"] = _r(100.0 * float(np.mean(st == 1)), 2)
    rep["plan"]["air_pct"] = _r(100.0 * float(np.mean(st == 0)), 2)
    air_runs = runs(plan["air"])
    rep["plan"]["air_runs_per_min"] = {k: _r(sum(1 for a, b in air_runs if lo <= b - a + 1 <= hi) / minutes, 2)
                                       for k, (lo, hi) in {"1-3": (1, 3), "4-6": (4, 6), "7-12": (7, 12), "13+": (13, 10 ** 9)}.items()}
    rep["plan"]["flying_frames_in_input"] = int(plan["flying"].sum())
    rep["ground"] = {}
    for s in SIDES:
        sd = sides[s]
        dy = sd["dy"]
        rr = runs(sd["held"])
        rep["ground"][TAGS[s]] = {"lowered_frames": int((dy < -1e-6).sum()), "max_cm": _r(float(-dy.min()) * UNIT_CM, 2),
                                  "held_runs_s": [[round(a / FPS, 2), round((b + 1) / FPS, 2),
                                                   _r(float(np.median(sd["low_judged"][a:b + 1])) * UNIT_CM, 2),
                                                   bool(np.any(sd["need"][a:b + 1]))] for a, b in rr][:200]}
    rep["ground"]["drop"] = {"frames": int((plan["drop"] > 1e-6).sum()), "max_cm": _r(float(plan["drop"].max()) * UNIT_CM, 2),
                             "windows": len(plan["drop_windows"]),
                             "windows_unsolved": sum(1 for w in plan["drop_windows"] if not w["solved"]),
                             "rounds": plan["drop_rounds"], "runs": plan["drop_rows"][:100],
                             "bound_frames": int(plan["strict"].sum()),
                             "bound_frames_s": [round(t / FPS, 2) for t in np.flatnonzero(plan["strict"])][:100]}
    rep["plant"] = {}
    for s in SIDES:
        sd = sides[s]
        c = np.linalg.norm(sd["plant"], axis=1) * UNIT_CM
        rows = sd["plant_rows"]
        rep["plant"][TAGS[s]] = {"frames_moved": int((c > 1e-4).sum()), "max_cm": _r(float(c.max()), 2),
                                 "runs": len(rows), "held_over_3cm": sum(1 for r in rows if r["max_cm"] > 3.0),
                                 "held_over_10cm": sum(1 for r in rows if r["max_cm"] > 10.0),
                                 "limited_frames": sum(r["limited_frames"] for r in rows),
                                 "worst": sorted(rows, key=lambda r: -r["max_cm"])[:20]}
    rep["flight"] = dict(plan["flight_rows"])
    rep["flight"]["count"] = len(rep["flight"]["flights"])
    rep["flight"]["carry_max_cm"] = {TAGS[s]: _r(float(sides[s]["carry"].max()) * UNIT_CM, 2) for s in SIDES}
    stance = sides["左"]["stance"] | sides["右"]["stance"]
    rep["pelvis"] = pelvis_report(rig, before, after, stance, F, plan["drop"], plan["change"])
    rep["between_frames"] = {TAGS[s]: {"raised_frames": int((plan["sub_raise"][s] > 0.0).sum()),
                                       "max_raise_cm": _r(float(plan["sub_raise"][s].max()) * UNIT_CM, 2)} for s in SIDES}
    rep["knee"] = knee_report(plan.get("knee") or {})
    return rep


def knee_jump_frames(bend, deg=10.0):
    """the frames [k] of bends [F] more than `deg` off the line through their neighbours (rig_check ik's jump frames)"""
    b = np.asarray(bend, dtype=float)
    if len(b) < 3:
        return np.zeros(0, dtype=int)
    return np.flatnonzero(np.abs(b[1:-1] - 0.5 * (b[:-2] + b[2:])) > deg) + 1


def knee_report(kp):
    """the knee step's plan per side: the frames bent like the frames round them, the swing goals moved, the standing feet
    turned (onto the toes +, the heel -), the toe IK goals put, the jump frames of the legs' formula before and after"""
    out = {}
    for s, k in kp.items():
        ev = np.asarray(k["even"])
        rows = []
        for a, b in runs(ev):
            rows.append({"s": [round(a / FPS, 2), round((b + 1) / FPS, 2)], "frames": [int(a), int(b)],
                         "bend_before": [_r(float(x), 1) for x in k["bend0"][max(a - 1, 0):b + 2]],
                         "bend_after": [_r(float(x), 1) for x in k["bend"][max(a - 1, 0):b + 2]],
                         "goal_cm": _r(float(np.max(k["moved"][a:b + 1])) * UNIT_CM, 2),
                         "turn_deg": _r(float(k["turn_deg"][a:b + 1][np.argmax(np.abs(k["turn_deg"][a:b + 1]))]), 2)})
        out[TAGS[s]] = {"evened_frames": int(ev.sum()), "swing_frames": int(np.sum(k["swing"])),
                        "standing_frames": int(np.sum(k["standing"])), "toe_frames": int(np.sum(k["toe_written"])),
                        "goal_cm_max": _r(float(np.max(k["moved"])) * UNIT_CM, 2),
                        "turn_deg_max": _r(float(np.max(np.abs(k["turn_deg"]))), 2),
                        "jump_frames_before": int(len(knee_jump_frames(k["bend0"]))),
                        "jump_frames_after": int(len(knee_jump_frames(k["bend"]))),
                        "bend_at_reach_edge_deg": _r(k["cap"], 2), "runs": rows[:200]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--report")
    ap.add_argument("--floor-y", type=float, default=None,
                    help="the floor's height (MMD units); the rest pose's soles (the trace's floor, the foot layer's) if not given")
    ap.add_argument("--no-ground", action="store_true", help="do not lower the standing feet held over the floor")
    ap.add_argument("--no-plant", action="store_true", help="let the standing feet slide as the dance has them")
    ap.add_argument("--no-drop", action="store_true", help="never lower the pelvis for a leg that cannot reach")
    ap.add_argument("--no-flight", action="store_true", help="leave the pelvis's height in the air as the dance has it")
    ap.add_argument("--no-knee", action="store_true", help="leave a knee straight for a frame or two at its reach as it is")
    ap.add_argument("--no-glide", action="store_true",
                    help="leave a run with no foot standing under a pelvis that does not fall as in a flight to the flight "
                         "(the layer before v11feet) instead of standing it on its lower foot just over the floor")
    ap.add_argument("--exact-gravity", action="store_true",
                    help="make every flight's centre of mass fall by gravity (the layer before v11feet) instead of at the "
                         "dance's own rate kept within FLIGHT_BAND (0.8 of gravity to gravity)")
    args = ap.parse_args(argv)
    if os.path.abspath(args.out) == os.path.abspath(args.dance):
        raise SystemExit("OUT.vmd is the dance itself: write the layer's dance elsewhere")
    t0 = time.time()
    with open(args.model, "rb") as f:
        data = f.read()
    rig = IK.LegRig.loads(data)
    shoe = FL.Shoe(rig, pmx_edit.loads(data))
    model = pmx.loads(data) if not args.model.lower().endswith(".pmd") else load_model(args.model)
    motion = vmd.load(args.dance)
    off = rig.check_iks(motion)
    if off:
        raise SystemExit("the dance switches off %s: this layer solves them as on" % ", ".join(off))
    out, plan = layer(model, rig, shoe, motion, {"floor_y": args.floor_y, "ground": not args.no_ground,
                                                 "plant": not args.no_plant, "drop": not args.no_drop,
                                                 "flight": not args.no_flight, "knee": not args.no_knee,
                                                 "glide": not args.no_glide, "flight_band": not args.exact_gravity})
    vmd.dump(out, args.out)
    back = vmd.load(args.out)
    F = plan["F"]
    rep = report_of(plan, rig, motion, back, F)
    rep["untouched"] = untouched(motion, back, plan["written"])
    rep["params"] = {"no_ground": args.no_ground, "no_plant": args.no_plant, "no_drop": args.no_drop, "no_flight": args.no_flight,
                     "no_knee": args.no_knee, "no_glide": args.no_glide, "exact_gravity": args.exact_gravity,
                     "floor_y": plan["floor_y"]}
    rep["seconds"] = round(time.time() - t0, 1)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps({"frames": F, "double_pct": rep["plan"]["double_pct"], "air_pct": rep["plan"]["air_pct"],
                      "lowered_frames": {k: v["lowered_frames"] for k, v in rep["ground"].items() if k in ("L", "R")},
                      "drop_max_cm": rep["ground"]["drop"]["max_cm"], "flights": rep["flight"]["count"],
                      "floor_past_bound_after": rep["pelvis"]["floor_past_bound_after"],
                      "knee_evened": {k: v["evened_frames"] for k, v in rep["knee"].items()},
                      "untouched": rep["untouched"]["identical"], "seconds": rep["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
