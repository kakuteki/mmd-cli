"""Contacts that carry the body: which foot stands on the floor frame by frame, the standing feet put onto the floor and
held where they stand, and where no foot stands the body flying by gravity.

    python tools/contact_layer.py DANCE.vmd MODEL.pmx OUT.vmd --report r.json [--floor-y Y] [--no-ground] [--no-plant]
        [--no-drop] [--no-flight]

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
   down, HOLD_MIN frames or more) unless no foot is on the floor there and the pelvis falls like a flight (faster than half
   of gravity over the run, or faster than FALL_BOUND on a frame of it: floaty's judge of a hop).  A foot's runs closer
   than BRIDGE frames are joined where its shoe stays under BRIDGE_LIFT (the foot layer's bridge).
2. Ground: a standing foot over the floor is lowered (足ＩＫ's height: the foot's shape kept) until its shoe's lowest
   point is on the floor, eased in and out over EASE frames into the air around (never into the floor).
3. Reach: a standing leg must reach its goal with the knee bent REACH_KNEE_DEG (the foot layer's: people stand on no knee
   straighter than 5 degrees).  Where it cannot, a foot that bears weight (the only one standing, or the centre of mass's
   floor point more than NEED_CM outside the other foot's sole) gets the pelvis (センター) lowered until it reaches (at most
   DROP_MAX; spread and lessened as the foot layer's sink is, so that no frame on the floor has the pelvis fall faster than
   FALL_BOUND, or than the input where it already does); a free foot (a pointed foot resting) is lowered only as far as
   its leg reaches.
4. Plant: a standing foot that bears weight (alone on the floor, or with LOAD_SHARE or more of it: the lever of the centre
   of mass's floor point between the two feet) is held where it stands: the slide of its touching part is undone frame by
   frame (足ＩＫ's horizontal place), so it turns on its ball or its heel as the dance has it but does not travel; after it
   lifts, the correction goes back to none over its swing (a smoothstep), so that it lands where the dance puts it.
5. Flight: where no foot stands for AIR_MIN frames or more, the body's centre of mass falls by gravity (G): the pelvis's
   height (センター) changes over the flight and WINDOW frames each side (the push and the catch) by the least change, with
   its third differences weighed SMOOTH, that makes the centre of mass's second differences -G on the frames with air on
   both sides, keeps every frame on the floor no faster falling than FALL_BOUND (or the input) and every standing leg in
   reach.  A foot in the air goes up with the body as far as its leg would otherwise straighten past AIR_KNEE_DEG.
6. Between the frames: MMD draws 240 fps and interpolates the keys; where a shoe would dip into the floor between two
   frames both are raised by the dip (the foot layer's sub-frame check).

Written: 足ＩＫ (both feet, its place) and センター (its height), a key on every frame (a linear curve, the physics bytes of
the input's key in force); nothing else (the report's `untouched` reads it back).  With nothing to do the input comes
back as it is.  Coordinates are MMD's (Y up, the model facing -Z), units are MMD units (UNIT_CM centimetres).
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
FLIGHT_ACC = 61.25              # units/s^2 (half of gravity): no foot on the floor and the pelvis falling faster over the run
FALL_BOUND = 122.0              # units/s^2: the pelvis's downward acceleration where a foot holds the body up (the balance
                                # layer's DOWN_ACC_MAX, for the skirt); faster on a frame of a run with no foot down is a hop
FALL_TOL = 0.5                  # units/s^2: past a bound by more than this (as the balance layer's report counts)
BRIDGE = 2                      # frames: a standing foot lifted this long or less stays down ...
BRIDGE_LIFT = 0.1875            # units (1.5 cm): ... where its shoe stays this low (the foot layer's BRIDGE_LIFT)
EASE = 4                        # frames: a foot's lowering comes and goes over this many frames each way (the foot layer's)
TOUCH = 0.025                   # units (2 mm): the shoe's vertices this near its lowest touch (the foot layer's HOVER_TOUCH)
NEED_CM = 10.0                  # cm: the centre of mass's floor point this far outside the other foot's sole: this foot
                                # bears weight (the MV's free resting feet have it -5 to +0.5 cm, the feet of its wide
                                # stances -12 to -32 cm; people's single-support ZMP margin is -4.4 cm [-6.0, -2.2])
SOLE_TOUCH = 0.15               # units (1.2 cm): the vertices of a shoe this near the floor make its sole on it
LOAD_SHARE = 0.3                # a standing foot with this share of the weight (the lever of the centre of mass between the
                                # feet) or alone on the floor is held where it stands
REACH_KNEE_DEG = FL.REACH_KNEE_DEG   # degrees: the knee of a standing leg bent at least this much (people: none straighter
                                     # than 5 degrees on the floor; the foot layer's)
DROP_MAX = 1.0                  # units (8 cm): the most the pelvis goes down to let a standing leg reach the floor
DROP_WINDOW = 24                # frames each side of a lowering over which it comes and goes (smoothly, within the bound)
DROP_QP_ROUNDS = 400
JUDGE_MISS = 0.75               # units (6 cm): a foot MMD leaves this far or less from its goal is judged at the goal (a
                                # leg lagging or just out of reach: 159.7-163.9 and 197-198.7 s are 5.1 cm); further (a
                                # kick far out, 245.4 s: 27 cm) the foot is where MMD shows it
PLANT_SPEED = 30.0              # cm/s: a standing foot's touching part moving slower than this is held in place (the trace's
                                # drift and jitter: v10's standing feet move faster than 27 cm/s on 10 % of their frames,
                                # people's 7.9); faster is the dance sliding the foot (kept)
AIR_MIN = 4                     # frames with no foot standing: a flight (the balance layer's AIR_MIN)
WINDOW = 8                      # frames each side of a flight over which the pelvis may change
SMOOTH = 30.0                   # the weight of the change's third differences against the change itself
AIR_KNEE_DEG = 20.0             # degrees: a flying leg straightens to this before its foot goes up with the body
SUB_NEAR = 0.25                 # units: the intervals checked between the frames (either end this near the floor)
SUB_ROUNDS = 3
IK_MISS = 0.0125                 # units (1 mm): MMD's ankle this far from its goal has not reached it
LAND_TOL = 0.0125                # units (1 mm): a weight-bearing foot whose shoe MMD leaves higher than this gets more drop
PUSH_ROUNDS = 4                 # rounds of pushing the goal of a weight-bearing foot MMD leaves over the floor ...
PUSH_STEP = 0.15                # units: ... by at most this a round (the foot layer's push)
DROP_ROUNDS = 4                 # rounds of checking the lowered pelvis on MMD's IK (a nearly straight leg stops short)
FLIGHT_ROUNDS = 4               # rounds of solving the flight again on the centre of mass the changed dance moves ...
FLIGHT_RESID = 1.0              # units/s^2: ... until it falls within this of gravity on the frames with air on both sides


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


def bridge(stance, low, gap=BRIDGE, lift=BRIDGE_LIFT):
    """stance [F] with the gaps of `gap` frames or fewer between two standing runs filled where the shoe (low [F]) stays
    under `lift`"""
    out = np.array(stance, dtype=bool)
    for a, b in runs(~out):
        if a > 0 and b < len(out) - 1 and b - a + 1 <= gap and bool(np.all(low[a:b + 1] < lift)):
            out[a:b + 1] = True
    return out


def flight_frames(on, pelvis_y, fall, flight_acc=FLIGHT_ACC, bound=FALL_BOUND):
    """[F] frames of the runs with no foot on the floor (on: side -> [F]) whose pelvis falls like a flight: its parabola
    over the run and a frame each side falls faster than flight_acc, or a frame of those falls faster than bound"""
    F = len(pelvis_y)
    out = np.zeros(F, dtype=bool)
    none = np.logical_and.reduce([~np.asarray(m, dtype=bool) for m in on.values()])
    for a, b in runs(none):
        i0, i1 = max(a - 1, 0), min(b + 1, F - 1)
        if np.any(np.asarray(fall)[i0:i1 + 1] > bound + FALL_TOL):
            out[a:b + 1] = True
            continue
        if i1 - i0 >= 2:
            t = np.arange(i0, i1 + 1) / FPS
            if 2.0 * np.polyfit(t, pelvis_y[i0:i1 + 1], 2)[0] < -flight_acc:
                out[a:b + 1] = True
    return out


def eased_lowering(dy, stance, low, ease=EASE):
    """the lowering [F] (units, <= 0) of a foot: dy on its standing frames, carried into the frames around with a raised
    cosine over `ease` frames from the nearest standing frame (never more than the frame's own shoe height, low [F]: not
    into the floor)"""
    dy = np.where(stance, np.minimum(dy, 0.0), 0.0)
    env = FL.smooth_max_envelope(-dy, ease)
    out = np.where(stance, dy, -np.minimum(env, np.maximum(low, 0.0)))
    return out


def swing_blend(corr, stance, plant_from, F):
    """the planting correction [F, 2] after its standing runs: from the value on a run's last frame to none on the next
    run's first frame (a smoothstep over the frames between), or over 2 EASE frames after the last run; none before the
    first planted frame of a run"""
    out = np.array(corr, dtype=float)
    rr = runs(stance)
    for i, (a, b) in enumerate(rr):
        end = out[b].copy()
        if i + 1 < len(rr):
            nxt = rr[i + 1][0]
        else:
            nxt = min(F, b + 1 + 2 * EASE)
        n = nxt - b
        for t in range(b + 1, min(nxt, F)):
            out[t] = end * (1.0 - float(smoothstep((t - b) / float(n))))
    return out


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


def drop_profile(need, floor_frames, fall_down, allowed, F, window=None):
    """the pelvis's lowering z [F] (units, >= 0) and per window its rows: over each run of need [F] > 0 and `window`
    frames each side (merged where they meet), the least and smoothest z (z^2 plus SMOOTH times its third differences
    squared) that is at least `need`, never negative, and on the floor's frames (floor_frames [F]) keeps the pelvis's
    downward acceleration (fall_down [F], units/s^2, + down) within `allowed` [F]: z's second difference at most
    (allowed - fall_down) / FPS^2 (a lowered pelvis falls faster where z bends up).  A window that has no such z keeps
    the least violation the solve reached (solved False)"""
    window = DROP_WINDOW if window is None else window
    z = np.zeros(F)
    rows = []
    wins = []
    for a, b in runs(need > 0.0):
        w0, w1 = max(0, a - window), min(F - 1, b + window)
        if wins and w0 <= wins[-1][1] + 1:
            wins[-1] = (wins[-1][0], w1)
        else:
            wins.append((w0, w1))
    for w0, w1 in wins:
        n = w1 - w0 + 1
        D2, D3 = _diff_matrix(n, 2, w0, F), _diff_matrix(n, 3, w0, F)
        H = 2.0 * (np.eye(n) + SMOOTH * D3.T @ D3)
        A_in, b_in = [], []
        for k in range(n):
            t = w0 + k
            e = np.zeros(n)
            e[k] = 1.0
            A_in.append(e)
            b_in.append(max(float(need[t]), 0.0))
            if floor_frames[t] and 0 < t < F - 1:
                A_in.append(-D2[k])
                b_in.append(-max((float(allowed[t]) - float(fall_down[t])) / (FPS * FPS), 0.0))
        x, act, rounds, ok = solve_qp(H, np.zeros((0, n)), np.zeros(0), np.array(A_in), np.array(b_in),
                                      rounds=DROP_QP_ROUNDS, batch=16)
        z[w0:w1 + 1] = np.maximum(x, 0.0)
        rows.append({"window": [int(w0), int(w1)], "active": len(act), "rounds": rounds, "solved": bool(ok)})
    return z, rows


def flight_change(windows, air, floor_frames, com_y, pelvis_ys, fall_in, room, F):
    """the pelvis's change [F] (units) and per window its rows: the least change over each window (first, last) that makes
    the centre of mass's heights com_y [F] fall by gravity on the air frames with air on both sides (air [F]), keeps
    every frame on the floor (floor_frames [F]) of every height in pelvis_ys falling no faster than FALL_BOUND (or
    fall_in [F], the input's, where it is faster) and under `room` [F] (how far the pelvis may rise there, NaN for no
    bound), weighted SMOOTH on the third differences"""
    change = np.zeros(F)
    rows = []
    for w0, w1 in windows:
        n = w1 - w0 + 1
        idx = np.arange(w0, w1 + 1)
        D2, D3 = _diff_matrix(n, 2, w0, F), _diff_matrix(n, 3, w0, F)
        H = 2.0 * (np.eye(n) + SMOOTH * D3.T @ D3)
        eq_rows, eq_b, in_rows, in_b = [], [], [], []
        g = G / (FPS * FPS)
        for k, t in enumerate(idx):
            if t <= 0 or t >= F - 1:
                continue
            if air[t] and air[t - 1] and air[t + 1]:
                c2 = com_y[t + 1] - 2.0 * com_y[t] + com_y[t - 1]
                eq_rows.append(D2[k])
                eq_b.append(-g - c2)
            elif floor_frames[t]:
                allowed = (max(FALL_BOUND, fall_in[t]) + FALL_TOL * 0.5) / (FPS * FPS)
                lo = max(-allowed - (y[t + 1] - 2.0 * y[t] + y[t - 1]) for y in pelvis_ys)
                in_rows.append(D2[k])
                in_b.append(lo)
                if np.isfinite(room[t]):
                    e = np.zeros(n)
                    e[k] = -1.0
                    in_rows.append(e)
                    in_b.append(-max(room[t], 0.0))
        A_eq = np.array(eq_rows) if eq_rows else np.zeros((0, n))
        A_in = np.array(in_rows) if in_rows else np.zeros((0, n))
        x, act, rounds, ok = solve_qp(H, A_eq, np.array(eq_b), A_in, np.array(in_b))
        change[w0:w1 + 1] = x
        rows.append({"window": [int(w0), int(w1)], "equalities": len(eq_rows), "active": len(act), "rounds": rounds,
                     "solved": bool(ok)})
    return change, rows


# ---- the layer -------------------------------------------------------------------------------------------------------

def default_params():
    return {"floor_y": None, "ground": True, "plant": True, "drop": True, "flight": True}


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
    turn in the world (the toe IK starts on its goal, as the foot layer keys it): the foot moves as one piece"""

    def __init__(self, rig, motion, keys, sol, F):
        self.rig, self.motion, self.keys, self.sol, self.F = rig, motion, keys, sol, F
        self.frames = list(range(F))
        self.ci = rig.by_name["センター"]
        self.legs = [rig.sides[s].leg_ik for s in SIDES]
        self.ankles = [rig.sides[s].ankle for s in SIDES]
        self.parent_c = FL._parent_world_turn(rig, keys, self.ci)
        self.parent_ik = {}
        for s in SIDES:
            rot = keys[rig.sides[s].leg_ik][1]
            self.parent_ik[s] = qmul(sol[s]["q_ik"], qconj(FL.qnormalize_rows(np.asarray(rot, dtype=float))))

    def compose(self, offsets, centre_dy):
        """(the new keys, their solve)"""
        F = self.F
        new = dict(self.keys)
        for s in SIDES:
            pos, rot = self.keys[self.rig.sides[s].leg_ik]
            new[self.rig.sides[s].leg_ik] = (pos + qrot(qconj(self.parent_ik[s]), offsets[s]), rot)
        pos_c, rot_c = self.keys[self.ci]
        new[self.ci] = (pos_c + qrot(qconj(self.parent_c), np.stack([np.zeros(F), centre_dy, np.zeros(F)], 1)), rot_c)
        moved = IK.solve(self.rig, self.motion, self.frames, new)
        for s in SIDES:
            sd = self.rig.sides[s]
            pos, rot = self.keys[sd.ankle]
            changed = (np.abs(offsets[s]).max(axis=1) > 1e-9) | (np.abs(centre_dy) > 1e-9)
            local = FL.qnormalize_rows(qmul(qconj(moved[s]["q_shin"]), self.sol[s]["q_foot"]))
            new[sd.ankle] = (pos, np.where(changed[:, None], local, np.asarray(rot, dtype=float)))
        return new, IK.solve(self.rig, self.motion, self.frames, new)

    def written(self):
        return self.legs + [self.ci] + self.ankles

    def build(self, new):
        return FL.build(self.motion, {self.rig.bones[i].name: new[i] for i in self.written()}, self.F)


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
        v = np.linalg.norm(sl, axis=1) * UNIT_CM * FPS
        if F > 1:
            v[-1] = v[-2]
        speed[s] = v
        rise[s] = step_min(low_j[s]) * UNIT_CM * FPS
    # 1. the plan
    on = {s: low_j[s] < ON_FLOOR for s in SIDES}
    flying = flight_frames(on, hips_y, fall)
    stance, held = {}, {}
    for s in SIDES:
        cand = (~on[s]) & (low_j[s] < HOLD_MAX) & (speed[s] < HOLD_SPEED) & (rise[s] < HOLD_RISE) & ~flying
        h = np.zeros(F, dtype=bool)
        for a, b in runs(cand, HOLD_MIN):
            h[a:b + 1] = True
        held[s] = h
        stance[s] = bridge(on[s] | h, low_j[s])
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
        short = (stance[s] & (dy[s] < 0.0) & ~(room >= -1e-9)) |                 (stance[s] & (dy[s] >= 0.0) & (low[s] > LAND_TOL) & (low_j[s] < ON_FLOOR))
        if not short.any():
            continue
        nd = needed(s, np.flatnonzero(short))
        free = short & ~nd
        if free.any():
            as_far_as_it_reaches(s, free & (dy[s] < 0.0))
        bear = short & nd
        if bear.any() and p["drop"]:
            r = np.where(bear, np.where(np.isfinite(room), np.maximum(-room, np.maximum(low[s] - low_j[s], 0.0)), DROP_MAX), 0.0)
            need_drop = np.maximum(need_drop, np.minimum(r, DROP_MAX))
        elif bear.any():
            as_far_as_it_reaches(s, bear & (dy[s] < 0.0))
    comp = Composer(rig, motion, keys, sol, F)
    floor_frames = stance["左"] | stance["右"]
    allowed = np.maximum(FALL_BOUND, fall) + FALL_TOL * 0.5          # (the input's own where it is past the bound already)
    drop = np.zeros(F)
    drop_rows, drop_rounds, drop_windows = [], [], []
    if np.any(need_drop > 0.0):
        # the least smooth lowering that lets the weight-bearing legs reach, within the bound on the floor's frames, then
        # checked on MMD's IK: a nearly straight leg stops short of a goal it reaches on paper (the balance layer's 1.5 cm
        # slack), so a weight-bearing foot still over the floor gets that much more
        for rnd in range(DROP_ROUNDS):
            drop, drop_windows = drop_profile(np.minimum(need_drop, DROP_MAX), floor_frames, fall, allowed, F)
            offs = {s: np.stack([np.zeros(F), dy[s], np.zeros(F)], 1) for s in SIDES}
            _, trial = comp.compose(offs, -drop)
            more = np.zeros(F)
            for s in SIDES:
                lo_ = FL.shell_world(shoe.sides[s], trial[s])[:, :, 1].min(axis=1) - floor_y
                over = stance[s] & (lo_ > LAND_TOL) & (dy[s] + low_j[s] < ON_FLOOR)
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
                over = stance[s] & (lows[s] > LAND_TOL) & (drop > 0.0) & (dy[s] + low_j[s] < ON_FLOOR)
                if over.any():
                    dy[s] = np.where(over, dy[s] - np.minimum(lows[s], PUSH_STEP), dy[s])
                    pushed = True
            drop_rounds.append({"push_round": rnd, "frames_over": int(sum(int((stance[s] & (lows[s] > LAND_TOL) & (drop > 0.0)).sum()) for s in SIDES))})
            if not pushed:
                break
    dy_e = {s: eased_lowering(dy[s], stance[s], low[s]) for s in SIDES}
    # 4. plant: a standing foot that bears weight does not travel
    corr, plant_rows = {}, {}
    for s in SIDES:
        c = np.zeros((F, 2))
        rows = []
        if p["plant"]:
            slow = np.linalg.norm(slip[s], axis=1) * UNIT_CM * FPS < PLANT_SPEED
            for a, b in runs(stance[s]):
                p0 = a
                for t in range(p0, b):
                    c[t + 1] = c[t] - (slip[s][t] if slow[t] else 0.0)
                if b > p0:
                    rows.append({"s": [round(p0 / FPS, 2), round((b + 1) / FPS, 2)],
                                 "drift_cm": _r(float(np.linalg.norm(c[b])) * UNIT_CM, 2),
                                 "max_cm": _r(float(np.linalg.norm(c[p0:b + 1], axis=1).max()) * UNIT_CM, 2)})
            c = swing_blend(c, stance[s], None, F)
        corr[s] = c
        plant_rows[s] = rows
    # 5. flight: the pelvis's change, solved on the body's centre of mass as the changed dance moves it (the legs
    # straighten or fold where the feet do not go with the body: the centre of mass follows the pelvis by less than one)
    pelvis_ys = [y - drop for y in pel.values()]
    change = np.zeros(F)
    flight_rows = []
    flights = [(a, b) for a, b in runs(air) if b - a + 1 >= AIR_MIN]
    lift = {s: np.stack([corr[s][:, 0], dy_e[s], corr[s][:, 1]], 1) for s in SIDES}
    hips_low = {s: sol[s]["hip"] - np.stack([np.zeros(F), drop, np.zeros(F)], 1) for s in SIDES}
    goals = {s: sol[s]["goal_ankle"] + lift[s] for s in SIDES}
    air_room = {s: raise_room(hips_low[s], goals[s], knee_reach(*lengths[s], AIR_KNEE_DEG)) for s in SIDES}

    def offsets_of(ch):
        """the feet's offsets with the change ch of the pelvis: a foot in the air goes up with the body as far as its leg
        would straighten past AIR_KNEE_DEG"""
        cr, offs = {}, {}
        for s in SIDES:
            r = np.where(np.isfinite(air_room[s]), np.maximum(air_room[s], 0.0), 0.0)
            cr[s] = np.where(~stance[s], np.maximum(ch - r, 0.0), 0.0)
            offs[s] = lift[s] + np.stack([np.zeros(F), cr[s], np.zeros(F)], 1)
        return offs, cr
    wrows, resid = [], []
    if p["flight"] and flights:
        wins = []
        for a, b in flights:
            w0, w1 = max(1, a - WINDOW), min(F - 2, b + WINDOW)
            if wins and w0 <= wins[-1][1] + 1:
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
        base = com[:, 1] - drop
        com_out = None
        for it in range(FLIGHT_ROUNDS):
            change, wrows = flight_change(wins, air, floor_frames, base, pelvis_ys, fall_in, room, F)
            offs, _ = offsets_of(change)
            new, _ = comp.compose(offs, change - drop)
            com_out = body_com(model, comp.build(new), F)
            if com_out is None:                     # (no body: the hips stand for the centre of mass, moved with the pelvis)
                break
            r = down_acc(com_out[:, 1])[interior] - G
            resid.append(_r(float(np.abs(r).max()) if len(r) else 0.0, 2))
            if not len(r) or np.abs(r).max() < FLIGHT_RESID:
                break
            base = com_out[:, 1] - change
        for a, b in flights:
            row = {"s": [round(a / FPS, 2), round((b + 1) / FPS, 2)], "frames": b - a + 1,
                   "rise_cm": _r(float(change[a:b + 1].max()) * UNIT_CM, 2),
                   "fall_cm": _r(float(-change[a:b + 1].min()) * UNIT_CM, 2)}
            if a >= 1 and b + 2 <= F and b - a + 1 >= 3:
                tt = np.arange(b - a + 3) / FPS
                row["com_acc_before"] = _r(2.0 * np.polyfit(tt, com[a - 1:b + 2, 1] - drop[a - 1:b + 2], 2)[0], 1)
                if com_out is not None:
                    row["com_acc_after"] = _r(2.0 * np.polyfit(tt, com_out[a - 1:b + 2, 1], 2)[0], 1)
            flight_rows.append(row)
    offsets, carry = offsets_of(change)
    centre_dy = change - drop
    plan["sides"] = {s: {"stance": stance[s], "held": held[s], "on": on[s], "need": need[s], "share": share[s], "dy": dy_e[s],
                         "plant": corr[s], "carry": carry[s], "low": low[s], "low_judged": low_j[s], "speed": speed[s],
                         "plant_rows": plant_rows[s]} for s in SIDES}
    plan.update({"air": air, "flying": flying, "drop": drop, "change": change, "drop_rows": drop_rows,
                 "drop_rounds": drop_rounds, "drop_windows": drop_windows,
                 "flight_rows": {"flights": flight_rows, "windows": wrows, "rounds_resid": resid}, "fall_in": fall,
                 "com": com})
    moved = any(float(np.abs(offsets[s]).max()) > 1e-9 for s in SIDES) or float(np.abs(centre_dy).max()) > 1e-9
    if not moved:
        plan["sub_raise"] = {s: np.zeros(F) for s in SIDES}
        plan["written"] = []
        return motion, plan
    new, out_sol = comp.compose(offsets, centre_dy)
    # 6. between the frames: raise both frames of an interval whose shoe dips into the floor further than the input's did
    sub = {s: np.zeros(F) for s in SIDES}
    dip_in = {}
    written_idx = comp.written()
    for _ in range(SUB_ROUNDS if F > 1 else 0):
        near = np.zeros(F - 1, dtype=bool)
        for s in SIDES:
            lo_ = FL.shell_world(shoe.sides[s], out_sol[s])[:, :, 1].min(axis=1)
            near |= np.minimum(lo_[:-1], lo_[1:]) < floor_y + SUB_NEAR
        idx = np.flatnonzero(near)
        if not len(idx):
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
            break
        new, out_sol = comp.compose(offsets, centre_dy)
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


def pelvis_report(rig, before, after, stance, F):
    """the pelvis (下半身 and センター) before and after: the largest downward acceleration on the floor's frames (a foot
    standing in the plan) and the frames past FALL_BOUND there (after past it and faster than before by more than
    FALL_TOL), the change of height"""
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
                             "rounds": plan["drop_rounds"], "runs": plan["drop_rows"][:100]}
    rep["plant"] = {}
    for s in SIDES:
        sd = sides[s]
        c = np.linalg.norm(sd["plant"], axis=1) * UNIT_CM
        rows = sd["plant_rows"]
        rep["plant"][TAGS[s]] = {"frames_moved": int((c > 1e-4).sum()), "max_cm": _r(float(c.max()), 2),
                                 "runs": len(rows), "drift_over_3cm": sum(1 for r in rows if r["drift_cm"] > 3.0),
                                 "drift_over_10cm": sum(1 for r in rows if r["drift_cm"] > 10.0),
                                 "worst": sorted(rows, key=lambda r: -r["drift_cm"])[:20]}
    rep["flight"] = dict(plan["flight_rows"])
    rep["flight"]["count"] = len(rep["flight"]["flights"])
    rep["flight"]["carry_max_cm"] = {TAGS[s]: _r(float(sides[s]["carry"].max()) * UNIT_CM, 2) for s in SIDES}
    stance = sides["左"]["stance"] | sides["右"]["stance"]
    rep["pelvis"] = pelvis_report(rig, before, after, stance, F)
    rep["between_frames"] = {TAGS[s]: {"raised_frames": int((plan["sub_raise"][s] > 0.0).sum()),
                                       "max_raise_cm": _r(float(plan["sub_raise"][s].max()) * UNIT_CM, 2)} for s in SIDES}
    return rep


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
                                                 "flight": not args.no_flight})
    vmd.dump(out, args.out)
    back = vmd.load(args.out)
    F = plan["F"]
    rep = report_of(plan, rig, motion, back, F)
    rep["untouched"] = untouched(motion, back, plan["written"])
    rep["params"] = {"no_ground": args.no_ground, "no_plant": args.no_plant, "no_drop": args.no_drop, "no_flight": args.no_flight,
                     "floor_y": plan["floor_y"]}
    rep["seconds"] = round(time.time() - t0, 1)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps({"frames": F, "double_pct": rep["plan"]["double_pct"], "air_pct": rep["plan"]["air_pct"],
                      "lowered_frames": {k: v["lowered_frames"] for k, v in rep["ground"].items() if k in ("L", "R")},
                      "drop_max_cm": rep["ground"]["drop"]["max_cm"], "flights": rep["flight"]["count"],
                      "floor_past_bound_after": rep["pelvis"]["floor_past_bound_after"],
                      "untouched": rep["untouched"]["identical"], "seconds": rep["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
