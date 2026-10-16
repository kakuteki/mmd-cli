"""Feet that carry weight: the ankles, the feet and the toes of a dance made anatomical, and their contact with the floor.

    python tools/foot_layer.py DANCE.vmd MODEL.pmx OUT.vmd --report r.json [--floor-y Y] [--toes anatomical|v1]
        [--toe-reach-cm CM] [--landing human|off] [--measure-only]

The floor is at the height of the rest pose's soles unless --floor-y gives another (the trace's floor: the tracer stood
the model there, so the dance is not moved down; 0.111 for Sour's Rin).  tools/make_stage.py's floor lies at y 0, under
those soles by 0.111 (9 mm): raise the floor to them, or give --floor-y 0 to lower every foot by that much (the legs
then reach 9 mm further, and where the pelvis is low already they fall short; the report counts it as unreached).

(the measuring half; the layer itself is described where it is defined, below.)

The feet are where MMD's IK puts them (tools/leg_ik.py, checked against MMD's renders).  The shoe is read from the
model's mesh: its sole is the bottom layer of the vertices skinned on the foot (足首D, 足先EX), each with its weight on
足先EX (the toes' bone, the ball of the foot), so that the sole bends with the toes as the skin does (linear blend); its
lower shell (SHELL_BAND) adds the toe cap's front edge and the heel's back, which go lowest when the foot is pitched.

Measures, per frame and foot (Measure):
* the shoe's lowest point (its lower shell), and the lowest of the sole's heel and of its forefoot (split at the widest
  gap along the foot);
* the foot's world pitch (+ toes up) and roll (+ the lateral edge down, i.e. turned like an inversion) against the
  floor, and its yaw;
* the anatomical angles of the ankle complex against the shank, in the joint coordinate system of the ISB (Wu et al.
  2002): the turn of 足首 against ひざ after the IK (the foot's local turn, identity at the model's rest), split X
  (about the knee's hinge, the shank's medio-lateral axis: dorsiflexion +) - Z (the floating axis, front-back:
  inversion +) - Y (the foot's vertical: adduction +), the right side mirrored.  Dorsiflexion is reported in the
  anatomical sense: plus the rest pose's own angle, the shank's lean at rest less the pitch of the foot inside the
  heeled shoe (HEEL_PITCH_DEG, an estimate from the mesh, see the constant).  The toes (MTP): 足先EX's turn about the
  foot's lateral axis (+ extension) plus the toes' extension inside the shoe at rest (the same pitch);
* contact: the foot is on the floor where its sole, laid flat by removing its roll, comes within CONTACT_ENTER of the
  trace's floor (the rest pose's sole: the tracer stood the model there), and leaves at CONTACT_EXIT (hysteresis);
  touch-downs (air to contact: which part comes first, how many frames until the whole sole is down) and lift-offs
  (which part leaves last); heel-up contact (the forefoot down, the heel raised);
* penetration (the lowest point below the floor), hovering in contact (the flat sole above the floor), sliding in
  contact (the path of the loaded part along the floor);
* the per-frame steps (the foot's turn, the ankle's move, the toes' turn).

Coordinates are MMD's (X to the model's left, Y up, the model facing -Z), units are MMD units (UNIT_CM centimetres).
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
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_foot_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IK = _tool("leg_ik")
qmul, qconj, qrot, qaxis, unit = IK.qmul, IK.qconj, IK.qrot, IK.qaxis, IK.unit

UNIT_CM = 8.0
FPS = 30.0
SIDES = ("左", "右")
TAGS = {"左": "L", "右": "R"}
SOLE_BAND = 0.03                # units above the lowest vertex that still count as the sole's bottom layer
SHELL_BAND = 0.35               # units above it that the shoe's lower shell takes: the toe cap's front edge and the heel's
                                # back, which go lowest when the foot is pitched (Rin's cap is 0.6 cm under the sole's
                                # bottom layer at 40 degrees toes-down, 0.9 cm at 60)
TIP_WEIGHT = 0.8                # the toe cap: the shoe's lower shell weighted this much or more on 足先EX
BALL_WEIGHT = (0.1, 0.55)       # the ball: the sole's bottom weighted between these on 足先EX (under the MTP's line)
CONTACT_ENTER = 0.03            # units above the trace's floor: a flat sole this low is on the floor
CONTACT_EXIT = 0.06             # ... and leaves it above this
HEEL_UP_DEG = 4.0               # a foot on the floor pitched toes-down more than this stands on its forefoot
# The pitch of the foot inside Sour's Rin's loafers, asin(h / L) (the stage-6 research, 4: h the heel's sole above the
# forefoot's, L the heel's contact to the metatarsal heads): the heel block stands 0.39 (the mesh: its width changes at
# y 0.5) to 0.5 (a side render of the rest pose) above the sole, the forefoot's sole is about 0.05 thick, and the
# heel's back (z 0.95) lies 1.27 behind 足先EX (the ball): 16 to 21 degrees, taken as 20 (the size is this estimate
# from the mesh, not from a source).  A barefoot model has 0.  It shifts the anatomical ankle angle (plantarflexion
# inside the shoe) and the toes' (extension): the direction is what Hansen & Childress 2004 found for heeled shoes (10
# women walking in heels of 37 and 71 mm: "an overall shift in the direction of plantar flexion").
HEEL_PITCH_DEG = 20.0


def smoothstep(x, lo, hi):
    s = np.clip((np.asarray(x, dtype=float) - lo) / (hi - lo), 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def runs(mask):
    """(start, end inclusive) of the runs of True"""
    m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1).tolist(), (np.flatnonzero(d == -1) - 1).tolist()))


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def stats(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "p5": _r(np.percentile(x, 5)), "p50": _r(np.percentile(x, 50)),
            "p95": _r(np.percentile(x, 95)), "p99": _r(np.percentile(x, 99)), "min": _r(x.min()), "max": _r(x.max())}


def quat_matrix(q):
    """rotation matrices [..., 3, 3] of unit quaternions (x, y, z, w)"""
    x, y, z, w = (q[..., i] for i in range(4))
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)


def xzy_angles(q):
    """(a, b, c) radians with the rotation of q = Rx(a) Rz(b) Ry(c) (intrinsic X, then the new Z, then the new Y)"""
    m = quat_matrix(q)
    a = np.arctan2(m[..., 2, 1], m[..., 1, 1])
    b = np.arcsin(np.clip(-m[..., 0, 1], -1.0, 1.0))
    c = np.arctan2(m[..., 0, 2], m[..., 0, 0])
    return a, b, c


# ---- the shoe ------------------------------------------------------------------------------------------------------

class SoleSide:
    """the sole of one shoe at rest: points [N, 3], their weight on the toes' bone w_ex [N], the heel / forefoot
    split, the foot's rest axes (forward a0 along the sole toward the toes, up n0, lateral l0 to the foot's outside),
    the ankle's and the toes' bone's rest positions, the trace's floor (the lowest point at rest)"""


class Shoe:
    def __init__(self, rig, doc, sides=SIDES):
        names = [b.name for b in rig.bones]
        self.sides = {}
        for s in sides:
            side = rig.sides[s]
            foot = {side.ankle}
            if side.ankle_d is not None:
                foot.add(side.ankle_d)
            ex = side.ex
            on = []
            for v in doc.vertices:
                pairs = {}
                for b, w in v.pairs():
                    pairs[b] = pairs.get(b, 0.0) + w
                total = sum(w for b, w in pairs.items() if b in foot or b == ex)
                if total < 0.999:
                    continue
                p = v.position()
                if (p[0] > 0.0) != (s == "左"):
                    continue
                on.append((p, pairs.get(ex, 0.0) if ex is not None else 0.0))
            if not on:
                raise ValueError("no vertex of the %s shoe is skinned on %s足首 / 足首D / 足先EX alone" % (s, s))
            pts = np.array([p for p, _ in on])
            w_ex = np.array([w for _, w in on])
            low = pts[:, 1].min()
            keep = pts[:, 1] < low + SOLE_BAND
            o = SoleSide()
            o.name = s
            o.points, o.w_ex = pts[keep], w_ex[keep]
            shell = pts[:, 1] < low + SHELL_BAND
            o.shell, o.w_shell = pts[shell], w_ex[shell]
            o.floor = float(low)
            o.ankle = np.array(rig.bones[side.ankle].position, dtype=float)
            o.ex = np.array(rig.bones[ex].position, dtype=float) if ex is not None else o.ankle.copy()
            # the forward axis: the sole's long axis in the floor plane, toward the toe bone
            xz = o.points[:, [0, 2]] - o.points[:, [0, 2]].mean(axis=0)
            _, _, vt = np.linalg.svd(xz, full_matrices=False)
            fwd = np.array([vt[0, 0], 0.0, vt[0, 1]])
            toe = np.array(rig.bones[side.toe].position, dtype=float)
            if np.dot(fwd, toe - o.ankle) < 0.0:
                fwd = -fwd
            o.a0 = unit(fwd)
            o.n0 = np.array([0.0, 1.0, 0.0])
            lat = np.cross(o.a0, o.n0)           # left foot facing -Z: (0,0,-1) x (0,1,0) = (1,0,0), the outside
            o.l0 = unit(lat if s == "左" else -lat)
            # heel and forefoot: split at the widest gap along the foot
            t = (o.points - o.ankle) @ o.a0
            order = np.sort(t)
            gaps = np.diff(order)
            k = int(np.argmax(gaps)) if len(gaps) else 0
            cut = 0.5 * (order[k] + order[k + 1]) if len(gaps) else 0.0
            o.fore = t > cut
            o.heel = ~o.fore
            o.toe = toe
            self.sides[s] = o
        self.names = names

    @classmethod
    def load(cls, rig, path):
        return cls(rig, pmx_edit.load(path))


def skin(o, leg, points, w_ex):
    """`points` [N, 3] of one shoe at rest, weighted w_ex [N] on the toes' bone, for one side's solved leg
    (leg_ik.solve): [F, N, 3], skinned linearly on the foot and the toes as MMD does"""
    pa = leg["ankle"][:, None, :] + qrot(leg["q_foot"][:, None, :], (points - o.ankle)[None])
    pe = leg["ex"][:, None, :] + qrot(leg["q_ex"][:, None, :], (points - o.ex)[None])
    w = w_ex[None, :, None]
    return (1.0 - w) * pa + w * pe


def sole_world(o, leg):
    """the sole's points [F, N, 3] (its bottom layer) for one side's solved leg"""
    return skin(o, leg, o.points, o.w_ex)


def shell_world(o, leg):
    """the shoe's lower shell [F, N, 3] for one side's solved leg: its lowest point is the shoe's, at any pitch"""
    return skin(o, leg, o.shell, o.w_shell)


def foot_axes(o, q_foot):
    """the foot's world forward, up and lateral axes [F, 3] (the 足首 frame)"""
    return qrot(q_foot, o.a0), qrot(q_foot, o.n0), qrot(q_foot, o.l0)


def world_pitch_roll(o, q_foot):
    """the foot's pitch (+ toes up) and roll (+ the lateral edge down), degrees, against the floor"""
    a, n, lat = foot_axes(o, q_foot)
    pitch = np.degrees(np.arcsin(np.clip(a[:, 1], -1.0, 1.0)))
    roll = -np.degrees(np.arcsin(np.clip(lat[:, 1], -1.0, 1.0)))     # the outside edge falling: + (inversion-like)
    yaw = np.degrees(np.arctan2(-a[:, 0], -a[:, 2]))
    return pitch, roll, yaw


def unrolled(o, q_foot):
    """the foot's world turns with the roll about its forward axis removed (the sole laid flat across)"""
    a, n, lat = foot_axes(o, q_foot)
    up = np.array([0.0, 1.0, 0.0])
    # the flat lateral: horizontal and perpendicular to forward, on the foot's outside
    flat_lat = np.cross(a, up) * (1.0 if o.name == "左" else -1.0)
    norm = np.linalg.norm(flat_lat, axis=1, keepdims=True)
    ok = norm[:, 0] > 1e-6
    flat_lat = flat_lat / np.where(norm > 1e-6, norm, 1.0)
    # the turn about a that brings lat onto flat_lat
    cosang = np.clip(np.sum(lat * flat_lat, axis=1), -1.0, 1.0)
    sinang = np.sum(np.cross(lat, flat_lat) * a, axis=1)
    ang = np.arctan2(sinang, cosang)
    turn = qaxis(a, np.where(ok, ang, 0.0))
    return qmul(turn, q_foot), np.degrees(np.where(ok, ang, 0.0))


# ---- the ankle complex's angles -------------------------------------------------------------------------------------

def ankle_angles(o, ankle, knee, q_shin, q_foot):
    """(dorsiflexion against the shank as the bones stand, inversion, adduction) in degrees, from the geometry (so that a
    foot twisted far from the knee does not mix one angle into another, as Euler angles of the 足首 turn do):
    dorsiflexion = 90 - the angle between the shank (ankle to knee) and the foot's forward axis; inversion = the foot's
    up axis leaning out of the plane of the shank and the foot, toward the foot's outside (its outer edge down, the
    sole turned in); adduction = the foot's forward axis turned about the shank from the knee's forward, toward the
    inside.  The joint coordinate system of the ISB for the ankle (Wu et al. 2002) in spirit: flexion about the
    medio-lateral axis, inversion about the floating front-back axis, rotation about the vertical."""
    side_sign = 1.0 if o.name == "左" else -1.0
    sv = unit(knee - ankle)
    a, n, _ = foot_axes(o, q_foot)
    dorsi = 90.0 - np.degrees(np.arccos(np.clip(np.sum(sv * a, axis=-1), -1.0, 1.0)))
    # the roll about the foot's own axis from the neutral roll of that axis: the up axis that lies in the plane of the
    # shank and the foot, on the shank's side (an angle over -180..180, so that a foot rolled past 90 is not read back
    # as less and a correction never turns the wrong way)
    n0 = unit(sv - np.sum(sv * a, axis=-1, keepdims=True) * a)
    inv = side_sign * np.degrees(np.arctan2(np.sum(n * np.cross(a, n0), axis=-1), np.sum(n * n0, axis=-1)))
    k = qrot(q_shin, np.array([0.0, 0.0, -1.0]))
    kp = unit(k - np.sum(k * sv, axis=-1, keepdims=True) * sv)
    ap = unit(a - np.sum(a * sv, axis=-1, keepdims=True) * sv)
    ang = np.degrees(np.arctan2(np.sum(np.cross(kp, ap) * sv, axis=-1), np.clip(np.sum(kp * ap, axis=-1), -1.0, 1.0)))
    return dorsi, inv, side_sign * ang


def rest_anatomy(rig, o, heel_pitch_deg=HEEL_PITCH_DEG):
    """the rest pose's (dorsiflexion as the bones stand, inversion, adduction) and the toes' extension in the shoe: the
    angles are reported against these, plus the anatomical part of the rest: the ankle is plantarflexed in the heeled
    shoe by its pitch (dorsiflexion = the shank's lean at rest - the pitch) and the toes, lying on the toe box, are
    extended by the same pitch"""
    side = rig.sides[o.name]
    knee = np.array(rig.bones[side.knee].position, dtype=float)[None]
    ankle = np.array(rig.bones[side.ankle].position, dtype=float)[None]
    ident = np.array([[0.0, 0.0, 0.0, 1.0]])
    d, i, a = ankle_angles(o, ankle, knee, ident, ident)
    return {"dorsi_bones": float(d[0]), "inversion": float(i[0]), "adduction": float(a[0]),
            "dorsi": float(d[0]) - heel_pitch_deg, "mtp": heel_pitch_deg}


# ---- measuring -----------------------------------------------------------------------------------------------------

def measure_feet(rig, shoe, motion, frames, floor_y=0.0, heel_pitch_deg=HEEL_PITCH_DEG):
    """side -> per-frame arrays of the feet (see the module docstring) for `frames` (consecutive)"""
    frames = list(frames)
    return feet_of(rig, shoe, IK.solve(rig, motion, frames), frames, floor_y, heel_pitch_deg)


def feet_of(rig, shoe, sol, frames, floor_y=0.0, heel_pitch_deg=HEEL_PITCH_DEG):
    """measure_feet from a solve (leg_ik.solve) already made"""
    out = {}
    for s, o in shoe.sides.items():
        leg = sol[s]
        world = sole_world(o, leg)
        y = world[:, :, 1]
        low = shell_world(o, leg)[:, :, 1].min(axis=1)
        pitch, roll, yaw = world_pitch_roll(o, leg["q_foot"])
        flat_q, _ = unrolled(o, leg["q_foot"])
        flat_leg = dict(leg)
        flat_leg["q_foot"] = flat_q
        flat_leg["q_ex"] = qmul(flat_q, qmul(qconj(leg["q_foot"]), leg["q_ex"]))
        flat_leg["ex"] = leg["ankle"] + qrot(flat_q, qrot(qconj(leg["q_foot"]), leg["ex"] - leg["ankle"]))
        flat_y = sole_world(o, flat_leg)[:, :, 1]
        flat_low = shell_world(o, flat_leg)[:, :, 1].min(axis=1)
        rest = rest_anatomy(rig, o, heel_pitch_deg)
        dorsi_b, inv, add = ankle_angles(o, leg["ankle"], leg["knee"], leg["q_shin"], leg["q_foot"])
        rest_dorsi, rest_mtp = rest["dorsi"], rest["mtp"]
        q_toes = qmul(qconj(leg["q_foot"]), leg["q_ex"])                 # 足先EX against the foot: +X lifts the toes
        mtp = np.degrees(2.0 * np.arctan2(q_toes[:, 0], q_toes[:, 3]))
        mtp = (mtp + 180.0) % 360.0 - 180.0
        toes_fwd = qrot(leg["q_ex"], o.a0)
        toes_pitch = np.degrees(np.arcsin(np.clip(toes_fwd[:, 1], -1.0, 1.0)))   # the toe box against the floor
        tip_m = o.w_shell >= TIP_WEIGHT
        ball_m = (o.w_ex >= BALL_WEIGHT[0]) & (o.w_ex <= BALL_WEIGHT[1])
        tip_low = skin(o, leg, o.shell[tip_m], o.w_shell[tip_m])[:, :, 1].min(axis=1)
        ball_low = skin(o, leg, o.points[ball_m], o.w_ex[ball_m])[:, :, 1].min(axis=1)
        out[s] = {
            "frames": np.array(frames), "low": low, "heel_low": y[:, o.heel].min(axis=1),
            "fore_low": y[:, o.fore].min(axis=1), "flat_low": flat_low,
            "flat_heel_low": flat_y[:, o.heel].min(axis=1), "flat_fore_low": flat_y[:, o.fore].min(axis=1),
            "pitch": pitch, "roll": roll, "yaw": yaw,
            "dorsi": dorsi_b - rest["dorsi_bones"] + rest_dorsi, "inversion": inv - rest["inversion"],
            "adduction": add - rest["adduction"],
            "mtp": mtp + rest_mtp, "reach": leg["reach"],
            "ankle": leg["ankle"], "knee": leg["knee"], "hip": leg["hip"], "q_foot": leg["q_foot"], "q_ex": leg["q_ex"],
            "q_shin": leg["q_shin"], "knee_bend": -np.degrees(leg["knee_angle"]),
            "heel_xz": world[:, o.heel][:, :, [0, 2]].mean(axis=1), "fore_xz": world[:, o.fore][:, :, [0, 2]].mean(axis=1),
            "trace_floor": o.floor, "floor": float(floor_y), "rest_dorsi": rest_dorsi, "rest_mtp": rest_mtp,
            "toes_pitch": toes_pitch, "tip_low": tip_low, "ball_low": ball_low,
        }
    return out


TOE_SLIDE = (30.0, 80.0)        # cm/s: a pointed foot moving faster than the first is less and less taken to touch the
                                # floor with the trace model's toe, faster than the second not at all (a toe on the
                                # floor stays or slides slowly; a step's swing skims past)


def foot_speed(f, vertical=False):
    """the foot's horizontal speed [F] in cm/s (the middle of its heel and forefoot), the larger of the steps into and
    out of each frame; with vertical, the ankle's rise and fall counted in too (a foot coming down to land is not
    still)"""
    xz = 0.5 * (f["heel_xz"] + f["fore_xz"])
    step = np.linalg.norm(np.diff(xz, axis=0), axis=1)
    if vertical:
        step = np.hypot(step, np.diff(f["ankle"][:, 1]))
    step = step * FPS * UNIT_CM
    v = np.zeros(len(xz))
    if len(step):
        v[1:] = step
        v[:-1] = np.maximum(v[:-1], step)
    return v


def trace_height(f, o, extra=0.0, key="flat_low"):
    """the flat sole's lowest point over the trace's floor [F] (units), as the trace's own model stood: a model whose
    foot reached `extra` units further from the ankle to the toe had its toe that much times sin(the toes-down pitch)
    lower, on the floor where this one's stops short.  Only for a foot moving slower than TOE_SLIDE.  0 for the dance's
    own model."""
    gate = 1.0 - smoothstep(foot_speed(f), *TOE_SLIDE)
    return f[key] - o.floor - extra * gate * np.sin(np.radians(np.clip(-f["pitch"], 0.0, 90.0)))


def toe_extra_estimate(f, o):
    """(the median, the number of frames) of trace_height's `extra` that would put this foot's still pitched frames on
    the floor: frames moving less than 15 cm/s, pitched 15 to 70 degrees toes-down, 0.3 to 6 cm over the trace's floor.
    A trace made for a model with a longer foot leaves such frames over the floor in proportion to sin(pitch)."""
    e = f["flat_low"] - o.floor
    speed = foot_speed(f)
    sinp = np.sin(np.radians(np.clip(-f["pitch"], 0.0, 90.0)))
    m = (speed < 15.0) & (-f["pitch"] >= 15.0) & (-f["pitch"] <= 70.0) & (e * UNIT_CM > 0.3) & (e * UNIT_CM < 6.0)
    return (float(np.median(e[m] / sinp[m])) if m.any() else None), int(m.sum())


def contact_mask(flat_low, trace_floor, enter=CONTACT_ENTER, exit_=CONTACT_EXIT):
    """the foot on the floor, with hysteresis: enters at trace_floor + enter, leaves above trace_floor + exit"""
    on = np.zeros(len(flat_low), dtype=bool)
    state = False
    for i, h in enumerate(flat_low):
        if state:
            state = h <= trace_floor + exit_
        else:
            state = h <= trace_floor + enter
        on[i] = state
    return on


PEN_TOL = 0.005                 # units: deeper than this below the floor is a penetration (0.4 mm)
PLANE_DEPTH = 0.02              # the floor's dark plane lies this far below its lines (tools/make_stage.py)
TOES_FLAT_DEG = 8.0             # a toe box within this of level lies on the floor (on a raised heel: the toes bent)
# (soft start, cap) in degrees, the anatomical angles of measure_feet; the sources are _spike/out/stage6/feet/RESEARCH.md
# and the stage-3 research (the Japanese reference range = JOA):
#   dorsiflexion: JOA 20; unloaded young women 23.9 +- 6.2 (Moromizato 2016; + 2 SD = 36); loaded, the weight-bearing
#     lunge 38.8 to 43.2 (Konor 2012, the midfoot included): LOADED_DORSI_CAP for a foot on the floor;
#   plantarflexion: JOA 45, young women 54.1 +- 6.6 (Moromizato; + 2 SD = 67); trained female ballet dancers (15,
#     21 +- 3 years) 77 +- 2.5 non-weight-bearing by goniometer and 83 +- 2.2 weight-bearing en pointe (Russell 2010,
#     the abstract; the midfoot included, which this one-piece foot stands for): 50 to 75, a dancer's range chosen to
#     keep the choreography's pointed feet (far past JOA's 45; the coordinator's choice);
#   inversion / eversion: JOA 30 / 20, Boone & Azen 36.2 / 19.2, Roaas & Andersson 27.7 / 27.6: 36 / 25 as caps;
#   toes (MTP) extension, the shoe's own pitch included: walking 37 to 42 (Halstead 2006, Nawoczenski 1999), the top
#     of a heel raise 40 to 58 (Houck 2009, Nawoczenski 1999), dancers' releve 50 to 90 barefoot (Veirs 2023, Kulig &
#     Rowley 2018), less in shoes (45 to 50 in soft ones, Bojsen-Moller & Lamoreux 1979): 50 to 70.
REFERENCE = {
    "dorsiflexion": (20.0, 36.0), "plantarflexion": (50.0, 75.0), "inversion": (30.0, 36.0), "eversion": (20.0, 25.0),
    "mtp_extension": (50.0, 70.0)}
LOADED_DORSI_CAP = 40.0


def angle_steps(q):
    """degrees turned from each frame to the next [F-1]"""
    d = np.abs(np.sum(q[1:] * q[:-1], axis=1))
    return np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))


def summarize(f, contact, floor_y, limits=None):
    """the report of one foot's measures `f` (measure_feet) with its contact frames `contact` against the visible floor
    `floor_y`: contact, penetration, hovering, roll and sliding in contact, touch-downs, lift-offs, heel-up contact, the
    anatomical angles beyond their reference and their cap, the per-frame steps"""
    limits = limits or REFERENCE
    F = len(contact)
    out = {"frames": F, "contact_frames": int(contact.sum()), "contact_runs": len(runs(contact))}
    low = f["low"]
    pen = low < floor_y - PEN_TOL
    out["penetration"] = {"frames": int(pen.sum()), "below_plane_frames": int((low < floor_y - PLANE_DEPTH).sum()),
                          "deepest_cm": _r(max(0.0, float(floor_y - low.min())) * UNIT_CM, 2),
                          "runs": len(runs(pen))}
    hov = (f["low"] - floor_y)[contact]                 # the sole's lowest point as it is (a foot kept on its edge counts)
    out["hover_in_contact_cm"] = stats(hov * UNIT_CM)
    out["hover_in_contact_over_5mm"] = int((hov * UNIT_CM > 0.5).sum())
    roll = np.abs(f["roll"][contact])
    out["roll_in_contact_deg"] = stats(roll)
    out["roll_in_contact_over"] = {"5": int((roll > 5).sum()), "10": int((roll > 10).sum()), "20": int((roll > 20).sum())}
    # sliding: per frame the smaller horizontal move of the heel and of the forefoot (a pivot about either is not a slide)
    dh = np.linalg.norm(np.diff(f["heel_xz"], axis=0), axis=1)
    dfo = np.linalg.norm(np.diff(f["fore_xz"], axis=0), axis=1)
    step = np.minimum(dh, dfo)
    slides = []
    for a, b in runs(contact):
        if b > a:
            slides.append(float(step[a:b].sum()) * UNIT_CM)
    slides = np.array(slides)
    out["slide_per_contact_cm"] = stats(slides)
    out["slide_contacts_over"] = {"1cm": int((slides > 1).sum()), "3cm": int((slides > 3).sum()),
                                  "10cm": int((slides > 10).sum())}
    # touch-downs and lift-offs, by the foot's pitch (the toes bent flat under a raised heel do not change it)
    pitch = f["pitch"]
    tds, kinds, to_flat = [], {"heel": 0, "fore": 0, "flat": 0}, []
    for a, b in runs(contact):
        if a == 0:
            continue
        tds.append(a)
        kind = "fore" if pitch[a] < -HEEL_UP_DEG else ("heel" if pitch[a] > HEEL_UP_DEG else "flat")
        kinds[kind] += 1
        if kind == "fore":
            g = a
            while g <= b and pitch[g] < -HEEL_UP_DEG:
                g += 1
            to_flat.append(g - a if g <= b else None)
    flats = [t for t in to_flat if t is not None]
    out["touchdowns"] = {"count": len(tds), "first": kinds,
                         "fore_frames_to_heel_down": stats(flats),
                         "fore_heel_down_within_1_frame": int(sum(1 for t in flats if t <= 1)),
                         "fore_heel_stays_up": int(sum(1 for t in to_flat if t is None))}
    los = {"heel_last": 0, "fore_last": 0, "flat": 0}
    for a, b in runs(contact):
        if b == F - 1:
            continue
        los["fore_last" if pitch[b] < -HEEL_UP_DEG else ("heel_last" if pitch[b] > HEEL_UP_DEG else "flat")] += 1
    out["liftoffs"] = los
    hu = contact & (pitch < -HEEL_UP_DEG)
    out["heel_up_contact_frames"] = int(hu.sum())
    out["heel_up_toe_box_pitch_deg"] = stats(f["toes_pitch"][hu])
    out["heel_up_toe_box_flat_frames"] = int((hu & (np.abs(f["toes_pitch"]) < TOES_FLAT_DEG)).sum())
    # the anatomical angles
    loaded = contact
    rom = {}
    for name, x in (("dorsiflexion", f["dorsi"]), ("plantarflexion", -f["dorsi"]), ("inversion", f["inversion"]),
                    ("eversion", -f["inversion"]), ("mtp_extension", f["mtp"])):
        start, cap = limits[name]
        if name == "dorsiflexion":                      # a foot on the floor may go to the weight-bearing lunge's
            cap = np.where(loaded, max(cap, LOADED_DORSI_CAP), cap)
        rom[name] = {"beyond_reference": int((x > start).sum()), "beyond_cap": int((x > cap).sum()),
                     "beyond_cap_loaded": int(((x > cap) & loaded).sum()), "max": _r(float(x.max()), 1),
                     "beyond_cap_runs": [[int(a), int(b)] for a, b in runs(x > cap)][:20]}
    out["anatomy"] = rom
    out["adduction_abs_deg"] = stats(np.abs(f["adduction"]))
    out["steps"] = {"foot_deg_per_frame": stats(angle_steps(f["q_foot"])),
                    "toes_deg_per_frame": stats(angle_steps(qmul(qconj(f["q_foot"]), f["q_ex"]))),
                    "ankle_cm_per_frame": stats(np.linalg.norm(np.diff(f["ankle"], axis=0), axis=1) * UNIT_CM)}
    return out


def compare(f_in, f_out, contact):
    """how far the output's foot is from the input's: the foot's world turn (degrees) and the ankle's place (cm), in
    contact and in the air; what the layer adds to a frame's step: the foot's turn beyond the input's (degrees) and the
    ankle's roughness of height beyond the input's (cm: the second difference of its height, |output| - |input|, so a pop
    counts and a jitter of the input that the layer takes out does not).  Frames are named by the frame a step arrives at
    (the roughness by its middle frame)."""
    d = np.abs(np.sum(f_in["q_foot"] * f_out["q_foot"], axis=1))
    turn = np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))
    move = np.linalg.norm(f_out["ankle"] - f_in["ankle"], axis=1) * UNIT_CM
    over = angle_steps(f_out["q_foot"]) - angle_steps(f_in["q_foot"])          # the layer's own one-frame turns
    worst = np.argsort(-over)[:5]
    rough = (np.abs(np.diff(f_out["ankle"][:, 1], 2)) - np.abs(np.diff(f_in["ankle"][:, 1], 2))) * UNIT_CM
    worst_h = np.argsort(-rough)[:5]
    return {"foot_turn_deg": {"contact": stats(turn[contact]), "air": stats(turn[~contact])},
            "ankle_move_cm": {"contact": stats(move[contact]), "air": stats(move[~contact])},
            "step_over_input_deg": {"over_10": int((over > 10).sum()), "over_20": int((over > 20).sum()),
                                    "worst": [[int(i) + 1, _r(float(over[i]), 1)] for i in worst]},
            "height_roughness_over_input_cm": {"over_1": int((rough > 1.0).sum()), "over_2": int((rough > 2.0).sum()),
                                               "p99": _r(float(np.percentile(rough, 99)), 2) if len(rough) else None,
                                               "worst": [[int(i) + 1, _r(float(rough[i]), 2)] for i in worst_h]}}


def toe_summary(f, contact, floor_y):
    """the report of one foot's toes (the bend of 足先EX, + extension, against the shoe's own shape) with its contact
    frames `contact` against the visible floor `floor_y`:
    * push_off: the lift-offs (the last frame of a contact run) from the ball (the heel up), from the rigid tip of the
      shoe (its tip on the floor, its ball 0.8 cm or more up: the toes not bent) or flat, and the bend at a lift-off
      with the heel up;
    * on_the_tip_frames: frames on the floor with the heel up and the toe box tipped more than TOES_FLAT_DEG down;
    * bent_up_in_the_air: a bend of 5 or more with the shoe a centimetre or more up, split into the frames nearer the
      next landing than the last lift-off (bent before the forefoot is down) and the others (the return after a lift);
    * tip_up_on_the_floor: the toes bent (3 or more) with the ball on the floor and the tip over 0.5 cm up;
    * still_pointed_hover: runs of 3 frames or more of a still foot (under 15 cm/s) pointed more than 10 degrees down
      whose tip hovers 0.25 to 2.5 cm over the floor, the ball higher (the trace's model's longer toes touched there);
    * the bend's range and its step from frame to frame."""
    n = len(contact)
    k = f["mtp"] - f["rest_mtp"]
    tip, ball = (f["tip_low"] - floor_y) * UNIT_CM, (f["ball_low"] - floor_y) * UNIT_CM
    low = (f["low"] - floor_y) * UNIT_CM
    pitch, box = f["pitch"], f["toes_pitch"]
    kinds, bends = {"ball": 0, "tip": 0, "flat": 0}, []
    for a, b in runs(contact):
        if b >= n - 1:
            continue
        if tip[b] < 0.3 and ball[b] > 0.8:
            kinds["tip"] += 1
        elif pitch[b] < -HEEL_UP_DEG:
            kinds["ball"] += 1
        else:
            kinds["flat"] += 1
        if pitch[b] < -HEEL_UP_DEG:
            bends.append(float(k[b]))
    up = (low >= 1.0) & (k >= 5.0)
    index = np.arange(n)
    last, following = np.full(n, -10 ** 9), np.full(n, 10 ** 9)
    at = -10 ** 9
    for i in range(n):
        at = i if contact[i] else at
        last[i] = at
    at = 10 ** 9
    for i in range(n - 1, -1, -1):
        at = i if contact[i] else at
        following[i] = at
    before = up & ((following - index) < (index - last))
    lifted = (ball < 0.3) & (tip > 0.5) & (k > 3.0)
    hover = (~np.asarray(contact)) & (pitch < -10.0) & (foot_speed(f) < 15.0) & (tip > 0.25) & (tip < 2.5) & (ball > tip)
    hr = [(a, b) for a, b in runs(hover) if b - a + 1 >= 3]
    return {"push_off": {"count": sum(kinds.values()), "from": kinds, "bend_at_heel_up_toe_off": stats(bends)},
            "on_the_tip_frames": int((np.asarray(contact) & (pitch < -HEEL_UP_DEG) & (box < -TOES_FLAT_DEG)).sum()),
            "bent_up_in_the_air": {"frames": int(up.sum()), "before_a_landing": int(before.sum()),
                                   "after_a_lift_off": int((up & ~before).sum())},
            "tip_up_on_the_floor": {"frames": int(lifted.sum()), "runs": len(runs(lifted)),
                                    "tip_max_cm": _r(float(tip[lifted].max()) if lifted.any() else 0.0, 2)},
            "still_pointed_hover": {"frames": int(sum(b - a + 1 for a, b in hr)), "runs": len(hr),
                                    "tip_cm": stats(np.concatenate([tip[a:b + 1] for a, b in hr]) if hr else [])},
            "bend_deg": stats(k), "bend_step_deg": stats(np.abs(np.diff(k)))}


# ---- the layer -----------------------------------------------------------------------------------------------------

LOAD_FULL = 0.03                # units above the trace's floor (the flat sole): the foot bears weight below this
LOAD_NONE = 0.30                # ... and none above (2.4 cm); between, a smoothstep: the roll is laid flat this way
ON_FLOOR = (0.03, 0.10)         # the band (units above the trace's floor) over which the sole is put onto the floor and
                                # the toes take a raised heel: below, on the floor; above, the floor shift alone
EASE = 4                        # frames over which the flattening and the toes come and go
LOAD_D0 = 1.0                   # units added to a foot's distance from the pelvis in the load share (8 cm)
LOAD_SHARE = (0.15, 0.45)       # a foot bearing less of the weight than the first keeps its roll and its toes; more
                                # than the second: laid flat, the toes bent under a raised heel
ROLL_DORSI = (45.0, 60.0)       # |dorsiflexion| over which the roll against the shank fades out of the corrections
AXIS_DORSI = (70.0, 80.0)       # |dorsiflexion| (as the bones stand) over which the dorsiflexion's correction fades out:
                                # the foot points along the shank within 20 to 10 degrees, and the plane of the two,
                                # about whose normal the foot is turned, is lost
SHANK_SWING = 25.0              # degrees a frame: a shank turning faster takes no range correction of the foot
ROLL_JUMP, FOOT_STILL = 40.0, 15.0   # degrees a frame: a roll that jumps more while the foot turns less is a jump of
                                     # the shank (the reference), not of the foot
FLAT_PITCH = (30.0, 60.0)       # degrees of pitch from the floor: a sole steeper than the first is laid flat less and
                                # less, steeper than the second (a foot pointed down at the floor) keeps its roll
ROUNDS = 3                      # rounds of solving the legs again to put the sole on the floor
SUB = 8                         # MMD draws 240 fps from the 30 fps keys and interpolates them in between: the frames
                                # between two keys are checked at 1/SUB
SUB_NEAR = 0.25                 # units: an interval is checked where either end's planned lowest point is this near the
                                # floor
SUB_ROUNDS = 3                  # rounds of raising both frames of an interval whose shoe dips below the floor
BRIDGE = 2                      # frames: a standing foot lifted for this long or less (the trace's jitter) stays down,
BRIDGE_LIFT = 0.1875            # ... when its shoe stays this low (units, 1.5 cm): a real quick step goes higher
X_AXIS = np.array([1.0, 0.0, 0.0])
# The toes (足先EX), toe_model "anatomical" (toe_bend; "v1" is the merged layer: the toes bent by the weight on a raised
# heel, eased over EASE frames each way).  The sources are in _spike/out/stage6/toes/RESEARCH.md.
TOE_MODELS = ("anatomical", "v1")
TOE_FLEX_CAP = 20.0             # degrees the toes bend down against the foot at most (足先EX toward flexion).  Sour's
                                # Rin's shoe bends with 足先EX over its front half (the weights ramp from 0.06
                                # at the vamp to 1 at the tip): in MMD's renders a bend of 8 hardly shows, 15 carries the
                                # line of a pointed foot on, 20 begins to droop, 30 hangs like rubber (stage 6, toes,
                                # probe2) - the cap is that choice, not a source's number.  At 20 the toes, which lie on the
                                # toe box extended by the shoe's own pitch at rest (HEEL_PITCH_DEG), are in the line of the
                                # metatarsals (MTP 0).
TOE_LOAD_TAU = 1.0              # frames: the weight comes onto the ball through two first-order lags of this (critically
                                # damped: from naught, half in 1.7 frames = 56 ms, 90 % in 3.9 = 130 ms).  In a run the
                                # forefoot lands and the toes come down flat in the first 20 to 35 % of a 0.22 to 0.37 s
                                # contact (Welte 2021, McDonald 2016: some 50 to 130 ms); the force of a landing peaks 40
                                # to 90 ms after the touch (stage-6 feet research, 5-2)
TOE_RELEASE_TAU = 2.0           # frames: after the toe-off the toe box returns to the shoe's own shape (first order): a
                                # 30 degree bend comes back at 350 deg/s at first, about the fastest an MTP turns at a
                                # push-off (312 deg/s rising in walking, Sichting 2020; 293 to 342 deg/s down at the end of
                                # a take-off in shoes, Duchene 2026)
TOE_REACH = 0.3125              # units (2.5 cm), when asked (--toe-reach-cm; off by default): a still pointed foot whose
                                # shoe hovers lower than this over the floor reaches it with its toes (the trace's model's
                                # longer toes were on the floor there).  Off by default: a loafer's sole does not bend 15
                                # to 20 degrees under a light touch, and the coordinator chose to leave these hovers (the
                                # first 18.5 s of the right foot would hold its toe box bent down 17 to 20 degrees)
TOE_REACH_SPEED = (10.0, 20.0)  # cm/s: a foot moving faster than the first reaches less and less, faster than the second
                                # not at all (a resting toe stays; a step's swing skims past)
TOE_REACH_RISE = (1.0, 3.0)     # cm/s up: a foot rising off the floor (after a toe-off) does not reach back for it
TOE_REACH_PITCH = (5.0, 10.0)   # degrees toes-down: a level foot over the floor does not reach, a pointed one does
TOE_REACH_TAU = 2.0             # frames: the reach comes and goes this smoothly (a first order run both ways)


def soft_limit(x, start, cap):
    """x below `start`; above, a saturation toward `cap` with the same value and slope at the start, never reaching the
    cap (the Soft IK form, as tools/anatomy_layer.py)"""
    x = np.asarray(x, dtype=float)
    w = cap - start
    return np.where(x <= start, x, start + w * (1.0 - np.exp(-(np.maximum(x, start) - start) / w)))


def soft_band(x, low, high):
    """both sides: `low` = (start, cap) below zero as positive numbers, `high` = (start, cap) above"""
    x = np.asarray(x, dtype=float)
    return np.where(x >= 0.0, soft_limit(x, *high), -soft_limit(-x, *low))


def xzy_quat(a, b, c):
    """the turn Rx(a) Rz(b) Ry(c) (radians; xzy_angles' inverse)"""
    F = np.shape(a)
    ex = qaxis(np.broadcast_to(X_AXIS, F + (3,)), a)
    ez = qaxis(np.broadcast_to(np.array([0.0, 0.0, 1.0]), F + (3,)), b)
    ey = qaxis(np.broadcast_to(np.array([0.0, 1.0, 0.0]), F + (3,)), c)
    return qmul(qmul(ex, ez), ey)


def continuous(q):
    """the same turns with the signs chosen so that each frame follows the last"""
    q = q.copy()
    for t in range(1, len(q)):
        if np.dot(q[t], q[t - 1]) < 0.0:
            q[t] = -q[t]
    return q


def trace_floor(shoe):
    """the trace's floor: where the rest pose's soles stand (the tracer stood the model there), the two sides' mean"""
    return float(np.mean([o.floor for o in shoe.sides.values()]))


# ---- the hover (floaty, 2026-10-17) -----------------------------------------------------------------------------------
# No foot on the floor while the lower one is just over it (the trace's keys sit on a 0.3 unit grid: 2.4 cm; the
# dance's model has longer feet, so Rin's pointed feet stop short of the floor) and the pelvis does not fall: the body
# is held by nothing.  a05 s11's 'hover support' (no foot within 0.4 cm, one within 4 cm) is 8 % of the song in the MV
# (v9, balance-v3; 10 % in the trace) and 1.4 % [0.5, 2.2] in people (FineDance's near kinds, 62 sequences), runs of 6
# frames or more 9.3 a minute against 0 [0, 1.2] (_spike/out/stage6/floaty/NOTES.md).  There the whole figure is
# lowered (the centre and both leg IKs by the same height: every joint's angle kept) until the lower shoe stands on
# the floor, the sink eased in and out over HOVER_EASE frames (lengthened, then lessened, where it would take the
# pelvis's fall past HOVER_ACC_BOUND, the balance layer's bound).  Putting the lower foot down alone straightened the
# knees (by up to 30 degrees in the song: a bent stance on the toes made straight), as the trace's longer feet would;
# so in the run the feet keep the dance's shape (no laying flat, no toes bent onto the floor, no heel turned: the
# layer takes them as in the air there), the sink alone brings the lower shoe down.  A run whose pelvis falls at least
# HOVER_FLIGHT_ACC over the run (a hop: in flight the body falls at gravity, 122.5 units/s^2 at 8 cm a unit), or
# faster than HOVER_ACC_BOUND on any frame of it (a hop whose take-off and landing in the run flatten the fit), keeps
# its height, and so does a run shorter than HOVER_MIN_RUN (a hover of a frame or two between steps: people have 1.4 %
# of such frames, runs of 6 frames or more not at all).  Only the frames where the lower shoe is held are taken: where
# it travels along the floor faster than HOVER_GLIDE it is a step's swing skimming the floor (the trace model's toe
# would not have stood there either), and the sink would drag the toe along the floor.
HOVER_MAX = 0.5                 # units over the trace's floor (4 cm, a05 s11's band): the lower shoe this low counts as hovering
HOVER_FLIGHT_ACC = 61.25        # units/s^2 down (half of gravity): a run whose pelvis falls faster is a flight
HOVER_MIN_RUN = 4               # frames: a shorter hover is left as it is
HOVER_FOOT_SPEED = 2.5          # units/s (20 cm/s): a run whose lower shoe moves up or down faster than this (the median
                                # over the run) is a foot on its way to or from the floor - a step's touch or lift, which the
                                # landing takes - not one held over it (the song's hovers: 8 cm/s, 91 % under 20)
HOVER_TRANSIT = 0.15            # units (1.2 cm): a run whose lower shoe only rises (or only falls, within 1 mm a frame) by
                                # more than this is a foot passing through the band at a lift-off or a touch, not held
                                # (the song's hovers come back: their net change is under 0.9 cm but for one landing)
HOVER_EASE = 6                  # frames: the sink comes and goes over this many frames each way (a raised cosine)
HOVER_SMOOTH = 3                # frames: the half width of the Hann window that smooths the sink inside a run
HOVER_ACC_BOUND = 122.0         # units/s^2: the pelvis's downward acceleration (下半身's and センター's: pelvis_fall) the sink
                                # may not take a frame past (a frame already past it in the input keeps its own): the
                                # balance layer's DOWN_ACC_MAX, gravity at 8 cm a unit, which it holds the floor's frames to
                                # for the skirt (a pelvis falling faster throws it up; HANDOVER 2026-10-16).  130 on the hips'
                                # mean (before the review of 2026-10-17) took 33 frames of the song on the floor to 123-131.5
                                # (tools/sink_check.py), 213.17-213.33 s among them, just before the turn at 213.4 s.  It is
                                # also the flight's: a run whose pelvis falls faster than it on any frame (or the frame on
                                # each side) is a hop, held by no floor (213.5 s: 6 cm up and down, falling at 133-193
                                # units/s^2 on three frames, yet flatter than half of gravity over the run, its take-off
                                # and landing in it; it had been lowered onto the floor)
HOVER_ACC_TOL = 0.5             # units/s^2: past a bound by more than this (as the balance layer's report counts)
HOVER_GLIDE = TOE_SLIDE[0]      # cm/s (30): a frame whose lower shoe's forefoot moves along the floor faster than this is a
                                # step's swing skimming the floor, not a foot held over it: the speed under which the layer
                                # takes a pointed foot as standing on the trace model's toe (TOE_SLIDE: a toe on the floor
                                # stays or slides slowly).  Sunk, such frames dragged the toe along the floor (before the
                                # review of 2026-10-17 the toe of 28 of the song's 46 sunk runs slid faster than this, the
                                # run's median, up to 50-200 cm/s: tools/sink_check.py): a05's slides of 10 cm and longer
                                # 21.9 -> 29.5 a minute, the slide path 706 -> 899 cm a minute (people 11.3 [7.7, 16.8] and
                                # 455 [352, 528], FineDance's near kinds)


def hover_runs(e, pelvis_y, on_floor=ON_FLOOR, low_max=HOVER_MAX, flight_acc=HOVER_FLIGHT_ACC, min_run=HOVER_MIN_RUN,
               foot_speed=HOVER_FOOT_SPEED, fall=None, fall_bound=HOVER_ACC_BOUND, glide=None, glide_max=HOVER_GLIDE):
    """[(a, b)] (inclusive) runs of min_run frames or more where neither shoe is on the floor (e: side -> the shoe's
    lowest point over the trace's floor [F] units, both over on_floor[1]) but the lower one is under low_max and held
    there (its height moves slower than foot_speed, the run's median, and does not only rise or only fall by more than
    HOVER_TRANSIT), and the pelvis's height (pelvis_y [F]) does not fall at flight_acc over the run (a quadratic through
    the run and a frame on each side), nor (fall [F]: the pelvis's downward acceleration, pelvis_fall) faster than
    fall_bound on any of those frames.  Frames where the lower shoe travels along the floor (glide [F]: its forefoot's
    horizontal speed, cm/s, fore_speed) faster than glide_max are not held: they end a run"""
    sides = list(e)
    lo = np.minimum(e[sides[0]], e[sides[1]])
    speed = np.abs(np.gradient(lo)) * FPS if len(lo) > 1 else np.zeros(len(lo))
    out = []
    held = (lo > on_floor[1]) & (lo < low_max)
    if glide is not None:
        held &= np.asarray(glide) <= glide_max
    for a, b in runs(held):
        if b - a + 1 < min_run or np.median(speed[a:b + 1]) > foot_speed:
            continue
        step = np.diff(lo[a:b + 1])
        tol = 0.1 / UNIT_CM
        if abs(lo[b] - lo[a]) > HOVER_TRANSIT and (np.all(step > -tol) or np.all(step < tol)):
            continue
        i0, i1 = max(a - 1, 0), min(b + 1, len(lo) - 1)
        if fall is not None and np.any(np.asarray(fall)[i0:i1 + 1] > fall_bound + HOVER_ACC_TOL):
            continue
        if i1 - i0 >= 2:
            t = np.arange(i0, i1 + 1) / FPS
            if 2.0 * np.polyfit(t, pelvis_y[i0:i1 + 1], 2)[0] < -flight_acc:
                continue
        out.append((int(a), int(b)))
    return out


def hann_smooth(x, half):
    """x [F] smoothed by a Hann window of `half` frames each way (the ends held)"""
    x = np.asarray(x, dtype=float)
    if half <= 0:
        return x
    w = np.hanning(2 * half + 3)[1:-1]
    w = w / w.sum()
    pad = np.concatenate([np.full(half, x[0]), x, np.full(half, x[-1])])
    return np.convolve(pad, w, mode="valid")


def hover_sink_profile(gap, runs_, acc0, ease=HOVER_EASE, smooth=HOVER_SMOOTH, bound=HOVER_ACC_BOUND):
    """(the sink [F] (units, >= 0), the frames still past the bound, the radius and the scale used per run): in each run
    the lower shoe's gap [F] over the floor, spread over `ease` frames each way (a raised cosine) and smoothed (a Hann
    window of `smooth` frames each way); where the sink takes the pelvis's downward acceleration (acc0 [F]: the input's,
    units/s^2) past `bound` (or past the input's own where that is already past it), the runs about that frame are
    spread further (3 frames more, up to 4 times), then their sink lessened (by a fifth at a time, down to nothing)"""
    F = len(gap)
    radius = [ease] * len(runs_)
    scale = [1.0] * len(runs_)
    allowed = np.maximum(bound, -acc0) + HOVER_ACC_TOL
    bad = np.zeros(F, dtype=bool)
    s = np.zeros(F)
    for it in range(40):
        s = np.zeros(F)
        for i, (a, b) in enumerate(runs_):
            if scale[i] <= 0.0:
                continue
            g = np.zeros(F)
            g[a:b + 1] = scale[i] * gap[a:b + 1]
            s = np.maximum(s, smooth_max_envelope(g, radius[i]))
        # (smoothed as a whole: no corner where two runs' sinks meet or where the gap steps from a frame to the next, which
        # would show as a one-frame spike of the centre; the few millimetres the smoothing leaves under the gap in a run
        # are the lower foot's to take, its height held on the floor)
        s = np.maximum(hann_smooth(s, smooth), 0.0)
        acc_s = np.zeros(F)
        acc_s[1:-1] = (s[2:] - 2.0 * s[1:-1] + s[:-2]) * FPS ** 2
        bad = acc0 - acc_s < -allowed
        if not bad.any():
            break
        for i, (a, b) in enumerate(runs_):
            if scale[i] > 0.0 and bad[max(0, a - radius[i] - smooth - 2):min(F, b + radius[i] + smooth + 3)].any():
                if radius[i] < ease + 12:
                    radius[i] += 3
                else:
                    scale[i] = round(scale[i] - 0.2, 6) if scale[i] > 0.2 + 1e-9 else 0.0
    return s, int(bad.sum()), radius, scale


def fore_speed(f):
    """the forefoot's horizontal speed [F] (cm/s: the middle of the sole's forefoot, what a pointed foot stands on), the
    larger of the steps into and out of each frame"""
    xz = np.asarray(f["fore_xz"], dtype=float)
    step = np.linalg.norm(np.diff(xz, axis=0), axis=1) * FPS * UNIT_CM
    v = np.zeros(len(xz))
    if len(step):
        v[1:] = step
        v[:-1] = np.maximum(v[:-1], step)
    return v


def pelvis_fall(rig, keys):
    """the pelvis's downward acceleration [F] (units/s^2, + down; 30 fps second differences, 0 at the ends): the larger of
    下半身's and センター's world heights' (the bones the balance layer bounds; the sink moves both alike), from keys of
    IK.sample (both are above the legs' IK)"""
    state = IK._State(rig, keys)
    F = len(next(iter(keys.values()))[0])
    out = np.full(F, -np.inf)
    for name in ("下半身", "センター"):
        if name in rig.by_name:
            y = np.asarray(state.world(rig.by_name[name])[0])[:, 1]
            a = np.zeros(F)
            if F >= 3:
                a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS ** 2
            out = np.maximum(out, a)
    return np.where(np.isfinite(out), out, 0.0)


def _parent_world_turn(rig, keys, index):
    """the world turn [F, 4] of bone `index`'s parent from the sampled turns of its ancestors (keys of IK.sample)"""
    chain = []
    i = rig.bones[index].parent
    while i is not None:
        chain.append(i)
        i = rig.bones[i].parent
    F = len(next(iter(keys.values()))[0])
    q = np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
    for i in reversed(chain):
        if i in keys:
            q = qmul(q, qnormalize_rows(np.asarray(keys[i][1], dtype=float)))
    return q


def sink_motion(rig, motion, keys, sol, sink, F):
    """`motion` with the centre and both leg IKs lowered by sink [F] units in the world (keys on every frame for them)"""
    d = np.stack([np.zeros(F), -np.asarray(sink, dtype=float), np.zeros(F)], axis=1)
    ci = rig.by_name["センター"]
    pos_c, rot_c = keys[ci]
    written = {rig.bones[ci].name: (pos_c + qrot(qconj(_parent_world_turn(rig, keys, ci)), d), rot_c)}
    for s, side in rig.sides.items():
        pos, rot = keys[side.leg_ik]
        parent = qmul(sol[s]["q_ik"], qconj(qnormalize_rows(np.asarray(rot, dtype=float))))
        written[rig.bones[side.leg_ik].name] = (pos + qrot(qconj(parent), d), rot)
    return build(motion, written, F)


def default_params():
    return {"floor_y": None, "load_full": LOAD_FULL, "load_none": LOAD_NONE, "on_floor": ON_FLOOR, "flatten": True,
            "rom": True, "toes": True, "limits": dict(REFERENCE), "heel_pitch_deg": HEEL_PITCH_DEG,
            "rounds": ROUNDS, "load_share": LOAD_SHARE, "flat_pitch": FLAT_PITCH, "loaded_dorsi_cap": LOADED_DORSI_CAP,
            "trace_toe_extra": 0.0, "toe_model": "anatomical", "toe_reach": 0.0,
            "landing": True, "reach_knee": REACH_KNEE_DEG, "skim": True, "hover": None, "hover_glide": HOVER_GLIDE}


# ---- the landing (feet-landing, 2026-10-16) ---------------------------------------------------------------------------
# The sources and the measures are in _spike/out/stage6/feet_landing/NOTES.md and _spike/out/stage6/feet/RESEARCH.md (5).
# The human baseline (FineDance, the K-pop / choreography / jazz sequences, 62, the per-sequence medians' median): at a
# touchdown the ankle stands 3.1 cm [2.6, 3.5] over a flat foot's (96 % land toes first), comes down 2.0 cm [1.4, 2.5] in
# the next 0.2 s while the pelvis sinks 1.17 cm, so the hip joint's distance to the ankle hardly changes (-0.05 cm
# [-0.44, 0]) and the knee bends 0.3 degrees more; the heel is down a median 3 frames (0.1 s) after the touch, 61 % of
# them within 6 frames.  The research: in an ordinary landing the heel comes down some 40 ms after the forefoot (Puddle &
# Maulder 2013), the ankle dorsiflexing 9.8 degrees from the toe's touch to the heel's and 10 more by 150 ms (Fukano &
# Fukubayashi 2014); 7 of 11 landers put the heel down after the metatarsal heads, 4 absorbed the landing on the forefoot
# alone (Gross & Nelson 1988).  The MV's dance lands with the foot IK stopped on the floor, so the whole sink goes into
# the knee (7 degrees in 0.2 s).
LANDING_WINDOW = 6              # frames (0.2 s) after a touchdown over which the heel comes down with the pelvis
LANDING_GAP = 4                 # frames off the floor before a touchdown (the human baseline's a05)
LANDING_LEAD = EASE             # frames before the touch over which the forefoot is pointed down (eased, a raised cosine)
# The human baseline found no frame of a planted human leg straighter than 5 degrees (a05's knee: the hip joint's
# distance to the ankle, the law of cosines); the MV's are where the dance put the standing foot's goal out of the leg's
# reach (MMD leaves that foot over the floor).  Such a foot rises onto its ball until the knee bends REACH_KNEE_DEG (5 and
# a margin; the rest pose of Sour's Rin reads 5.7).
REACH_KNEE_DEG = 5.5
# A foot that the dance moves over the floor faster than the first speed (cm/s) is less and less, faster than the second
# not at all, put onto the floor where the dance has its sole off it (over CONTACT_ENTER): a swing that skims the floor
# is not pressed into a slide along it (the foot layer made a third of the slides it added so).
SKIM_SPEED = (5.0, 15.0)
# The most the landing's heel comes down in a frame (degrees): the cap (some 25 degrees) over 5 frames, about the
# humans' 0.1 s median from the touch to the heel down and inside the 0.2 s that 61 % of them take.
HEEL_DROP_DEG = 5.0
SKIM_LIFT = (CONTACT_EXIT, CONTACT_EXIT + 0.005)  # (over the contact's hysteresis: a foot the dance keeps on the floor
                                                   # is not taken for a skimming one; the review's hovers, 2026-10-16)


def toes_down_axis(o, q_foot):
    """the horizontal axis [F, 3] about which a positive turn points the foot's toes down (heel up)"""
    a = qrot(q_foot, o.a0)
    ax = np.cross(np.array([0.0, 1.0, 0.0]), a)
    n = np.linalg.norm(ax, axis=1, keepdims=True)
    return np.where(n > 1e-6, ax / np.maximum(n, 1e-6), np.array([1.0, 0.0, 0.0]))


def about_ball(ankle, ball, axis, deg):
    """the ankle [F, 3] when the foot turns `deg` degrees about `axis` through the ball"""
    return ball + qrot(qaxis(axis, np.radians(deg)), ankle - ball)


def least_turn(f, lo, hi, rounds=30):
    """per frame the least turn in [lo, hi] (degrees, arrays) at which f(turn) <= 0, by bisection (f falling on it); hi
    where even hi does not"""
    a, c = np.array(lo, dtype=float), np.array(hi, dtype=float)
    ok = f(c) <= 0.0
    for _ in range(rounds):
        mid = 0.5 * (a + c)
        below = f(mid) <= 0.0
        c = np.where(below, mid, c)
        a = np.where(below, a, mid)
    return np.where(ok, c, hi)


def knee_reach(L1, L2, knee_deg):
    """the hip joint's distance to the ankle of a two-bone leg bent knee_deg degrees"""
    return math.sqrt(L1 * L1 + L2 * L2 + 2.0 * L1 * L2 * math.cos(math.radians(knee_deg)))


def heel_turn(rig, o, leg, q_t, v, loaded, p):
    """(the turn [F] in degrees about the ball that points the foot down and raises its heel, the ball [F, 3], the axis
    [F, 3]) for one side from a solve of the planned feet (leg: hip, ankle, ex, knee, q_shin) and the plan's on-floor
    weight v and load:
    * landing: at a loaded touchdown (a run of frames on the floor after LANDING_GAP off it) the heel is up by as much as
      keeps the hip joint's distance to the ankle at the shortest it comes to in the next LANDING_WINDOW frames, and
      comes down frame by frame as the pelvis sinks (never back up), down when the pelvis is lowest; eased in over
      LANDING_LEAD frames before the touch;
    * reach: a foot on the floor whose leg cannot bend its knee REACH_KNEE_DEG to reach it rises onto its ball until it
      can, eased over EASE frames each way.
    Both stop where the ankle stands highest over the ball and at the soft start of the plantarflexion's range."""
    F = len(v)
    hip, ankle, ball = leg["hip"], leg["ankle"], leg["ex"]
    axis = toes_down_axis(o, q_t)
    u = ankle - ball
    back = -np.sum(u * qrot(q_t, o.a0) * np.array([1.0, 0.0, 1.0]), axis=1)    # the ankle behind the ball, horizontally
    peak = np.degrees(np.arctan2(np.maximum(back, 0.0), np.maximum(u[:, 1], 1e-6)))
    rest = rest_anatomy(rig, o, p["heel_pitch_deg"])
    d_b, _, _ = ankle_angles(o, ankle, leg["knee"], leg["q_shin"], q_t)
    plantar = -(d_b - rest["dorsi_bones"] + rest["dorsi"])
    hi = np.clip(np.minimum(peak, p["limits"]["plantarflexion"][0] - plantar), 0.0, None)
    zero = np.zeros(F)

    def dist(deg, idx):
        return np.linalg.norm(hip[idx] - about_ball(ankle[idx], ball[idx], axis[idx], deg), axis=1)

    d0 = np.linalg.norm(hip - ankle, axis=1)
    land = np.zeros(F)
    if p.get("landing", True):
        down = np.asarray(v) >= 0.5
        prev_end = -10 ** 9
        for a, b in runs(down):
            gap = a - prev_end - 1
            prev_end = b
            if a == 0 or gap < LANDING_GAP:
                continue
            w = np.arange(a, min(b, a + LANDING_WINDOW, F - 1) + 1)
            target = d0[w].min()
            need = least_turn(lambda deg: dist(deg, w) - target, zero[w], hi[w])
            need = np.minimum.accumulate(need) * float(np.max(loaded[w]))
            land[w] = np.maximum(land[w], need)
            for j in range(1, LANDING_LEAD + 1):
                if a - j < 0:
                    break
                g = 0.5 * (1.0 + math.cos(math.pi * j / (LANDING_LEAD + 1)))
                land[a - j] = max(land[a - j], g * need[0])
        # (review_feet_landing) the heel comes down at most HEEL_DROP_DEG a frame: where the sink is more than turning
        # about the ball can take, the turn stays at its cap until the pelvis is lowest and would fall to 0 in one
        # frame (in the song 68 frames of 10 to 30 degrees)
        for t in range(1, F):
            land[t] = max(land[t], land[t - 1] - HEEL_DROP_DEG)
    reach = np.zeros(F)
    knee = p.get("reach_knee", 0.0)
    if p.get("landing", True) and knee > 0.0:
        side = rig.sides[o.name]
        hip0, knee0, ankle0 = (np.array(rig.bones[i].position, dtype=float) for i in (side.thigh, side.knee, side.ankle))
        target = knee_reach(float(np.linalg.norm(knee0 - hip0)), float(np.linalg.norm(ankle0 - knee0)), knee)
        idx = np.flatnonzero((np.asarray(v) >= 0.5) & (d0 > target))
        if len(idx):
            reach[idx] = least_turn(lambda deg: dist(deg, idx) - target, zero[idx], hi[idx])
        reach = smooth_max_envelope(reach, EASE)
    return np.minimum(np.maximum(land, reach), hi), ball, axis


def load_shares(shoe, feet, sol, p):
    """side -> the share of the body's weight on each foot [F], 0..1: a foot near the floor (the height band) bears it in
    proportion to its nearness to the pelvis seen from above (1 / (distance + LOAD_D0)^2), the two summing to 1 when
    either is down.  A foot that only touches the floor away from the body (a pointed toe out to the side) bears
    little; a single foot on the floor bears all."""
    hips = 0.5 * (sol["左"]["hip"] + sol["右"]["hip"])
    near, g = {}, {}
    for s, o in shoe.sides.items():
        f = feet[s]
        e = trace_height(f, o, p["trace_toe_extra"])
        near[s] = 1.0 - smoothstep(e, p["load_full"], p["load_none"])
        centre = 0.5 * (f["heel_xz"] + f["fore_xz"])
        d = np.linalg.norm(centre - hips[:, [0, 2]], axis=1)
        g[s] = near[s] / (d + LOAD_D0) ** 2
    total = sum(g.values())
    return {s: np.where(total > 1e-9, g[s] / np.maximum(total, 1e-9), 0.0) for s in g}, near


def roll_reliable(inv, dorsi, q_foot):
    """0..1 per frame: how far the roll against the shank can be trusted.  It is read about the foot's axis from the
    shank, so it means nothing when the foot points along the shank (|dorsiflexion| toward 90: ROLL_DORSI), and it
    jumps when the shank swings past the foot (a leg folded 140 degrees in a kick) while the foot itself hardly turns:
    a frame whose roll moves more than ROLL_JUMP degrees while the foot turns less than FOOT_STILL is such a jump, and
    it and its neighbours (EASE frames, a raised cosine) are left as the input has them."""
    r = 1.0 - smoothstep(np.abs(dorsi), *ROLL_DORSI)
    d_inv = np.abs((np.diff(inv) + 180.0) % 360.0 - 180.0)
    still = angle_steps(q_foot) < FOOT_STILL
    jump = np.zeros(len(inv))
    jump[1:] = np.maximum(jump[1:], (d_inv > ROLL_JUMP) & still)
    jump[:-1] = np.maximum(jump[:-1], (d_inv > ROLL_JUMP) & still)
    return r * (1.0 - smooth_max_envelope(jump, EASE))


def spread(x, radius=None):
    """a correction spread over the neighbouring frames (each side's largest kept, raised cosine of EASE frames): a
    range passed for one or two frames (the peak of a kick) is corrected without the foot snapping in and out"""
    radius = EASE if radius is None else radius
    return smooth_max_envelope(np.maximum(x, 0.0), radius) - smooth_max_envelope(np.maximum(-x, 0.0), radius)


def trusted(x, ok):
    """a correction x [F] spread over its neighbours (spread) where it can be trusted: ok [F] 0..1 per frame.  The
    corrections of frames not trusted are dropped first (what was read there must not reach the frames around them),
    then the spread is faded out around those frames (EASE frames, a raised cosine), so the foot eases back to the
    input's there."""
    return spread(x * ok) * (1.0 - smooth_max_envelope(1.0 - ok, EASE))


def turn_about(axis, deg, q):
    """q turned further by `deg` degrees about the world axis `axis` [F, 3]"""
    return qmul(qaxis(unit(axis), np.radians(deg)), q)


def floor_weight(f, o, p):
    """the on-floor weight v [F] of one foot (0..1): the flat sole within the ON_FLOOR band over the trace's floor, the
    trace's one- or two-frame lifts of a low shoe bridged, and with p["landing"] and p["skim"] a foot that the dance moves
    fast with its sole off the floor (SKIM_SPEED, SKIM_LIFT) not put onto it"""
    e = trace_height(f, o, p["trace_toe_extra"])
    lift = trace_height(f, o, p["trace_toe_extra"], key="low")    # the shoe itself, not laid flat
    v = bridge(1.0 - smoothstep(e, *p["on_floor"]), BRIDGE, lift < BRIDGE_LIFT)
    if p.get("landing", True) and p.get("skim", True):
        v = v * (1.0 - smoothstep(foot_speed(f), *SKIM_SPEED) * smoothstep(e, *SKIM_LIFT))
    return v


def foot_targets(o, f, leg, rest, share, near, p, floor_y=None, heel=None, hover_hold=None, shape_v=None):
    """(the foot's world turn q_t [F, 4], the toes' extension added by 足先EX (degrees), the roll laid flat w, the
    on-floor weight of the height v, that of the shape) for one side: the roll laid flat as the foot takes weight (by
    its share of the body's weight and only while its sole faces the floor), the ankle complex inside its range, the
    heel raised by `heel` [F] degrees about the ball (heel_turn; none when not given), the toes bent so that a loaded
    raised heel stands on the ball with the toe box on the floor (floor_weight).
    Where the figure was lowered over a hover (hover_runs): `shape_v` [F] is the on-floor weight the shape is judged by
    (that of the feet before the sink, so that a foot the sink brings onto the floor keeps the dance's shape: no roll
    laid flat, no toes bent, no heel turned, as the layer before), and `hover_hold` [F] holds the height of a hover
    run's lower foot on the floor."""
    side_sign = 1.0 if o.name == "左" else -1.0
    v = floor_weight(f, o, p)
    v_height = v if hover_hold is None else np.maximum(v, hover_hold)
    if shape_v is not None:
        v = np.asarray(shape_v, dtype=float)
    q = leg["q_foot"]
    pitch = np.degrees(np.arcsin(np.clip(qrot(q, o.a0)[:, 1], -1.0, 1.0)))
    loaded = smoothstep(share, *p["load_share"])
    # the weights spread over EASE frames each way (a raised cosine): a fast foot crosses the height band in a frame or
    # two, but the roll is laid flat and the toes bend and relax over about 0.13 s
    w = smooth_max_envelope(near * loaded * (1.0 - smoothstep(np.abs(pitch), *p["flat_pitch"])), EASE)
    if p["flatten"]:
        _, ang = unrolled(o, q)
        turn = w * ang
        if p["rom"]:
            # laying flat turns the foot about its own forward axis, so the roll against the shank (the subtalar
            # joint's inversion and eversion) moves with it one for one.  Where that roll is read with trust the range's
            # correction below holds it inside the subtalar caps; where it is not (roll_reliable: the foot near the
            # shank's line, or its reading jumping) that correction does not come back to it.  So the laying flat itself
            # stops at the caps (the foot stays on that edge as far as the joint cannot take): a turn back toward the
            # middle of the range is kept whole, and the foot is never turned past flat to the other side
            lim = p["limits"]
            _, inv0, _ = ankle_angles(o, leg["ankle"], leg["knee"], leg["q_shin"], q)
            inv0 = inv0 - rest["inversion"]
            change = side_sign * turn
            held = np.clip(inv0 + change, -lim["eversion"][1], lim["inversion"][1]) - inv0
            turn = side_sign * np.clip(held, np.minimum(change, 0.0), np.maximum(change, 0.0))
        q = turn_about(qrot(q, o.a0), turn, q)
    if p["rom"]:
        lim = p["limits"]
        ankle, knee = leg["ankle"], leg["knee"]
        sv = unit(knee - ankle)
        d_b, inv, add = ankle_angles(o, ankle, knee, leg["q_shin"], q)
        dorsi = d_b - rest["dorsi_bones"] + rest["dorsi"]
        start, cap = lim["dorsiflexion"]
        dcap = cap + v * max(0.0, p["loaded_dorsi_cap"] - cap)             # a loaded foot dorsiflexes further
        dd = np.where(dorsi >= 0.0, soft_limit(dorsi, start, dcap), -soft_limit(-dorsi, *lim["plantarflexion"])) - dorsi
        # left as the input has it (trusted): the dorsiflexion where the shank itself swings faster than SHANK_SWING a
        # frame (a leg folded in a kick, MMD's knee turning round: holding the foot inside the range would whip it with
        # the shank) and where the foot points along the shank (AXIS_DORSI: the axis of the turn is lost); the roll
        # where its reference is lost (roll_reliable; it is turned about the foot's own axis, so a fast shank does not
        # swing it).  Such frames' own corrections are dropped before the spread (what is read there means nothing and
        # must not reach the frames around), and the spread is faded out around them.
        swing = np.zeros(len(sv))
        swing[1:] = np.degrees(np.arccos(np.clip(np.sum(sv[1:] * sv[:-1], axis=1), -1.0, 1.0)))
        fast = (swing > SHANK_SWING).astype(float)
        fast[:-1] = np.maximum(fast[:-1], fast[1:])
        a = qrot(q, o.a0)
        q = turn_about(np.cross(sv, a), -trusted(dd, 1.0 - np.maximum(fast, smoothstep(np.abs(d_b), *AXIS_DORSI))), q)
        # (about the shank x foot normal: + lowers the dorsiflexion)
        d_b, inv, add = ankle_angles(o, ankle, knee, leg["q_shin"], q)
        inv = inv - rest["inversion"]
        di = soft_band(inv, lim["eversion"], lim["inversion"]) - inv
        ok = roll_reliable(inv, d_b, leg["q_foot"])                      # d_b: 90 - the angle of the foot to the shank
        q = turn_about(qrot(q, o.a0), side_sign * trusted(di, ok), q)   # about the foot's forward axis
    if heel is not None and np.any(heel > 0.0):
        q = qnormalize_rows(turn_about(toes_down_axis(o, q), heel, q))
    toes = np.zeros(len(q))
    if p["toes"]:
        if p.get("toe_model", "anatomical") == "v1":           # (the merged layer's, to the bit: q as it stands)
            pitch = np.degrees(np.arcsin(np.clip(qrot(q, o.a0)[:, 1], -1.0, 1.0)))
            room = max(0.0, p["limits"]["mtp_extension"][1] - rest["mtp"])
            toes = smooth_max_envelope(v * loaded * soft_limit(np.clip(-pitch, 0.0, None), 0.6 * room, room), EASE)
        else:
            toes = toe_bend(o, f, leg, qnormalize_rows(q), rest, v, loaded, p, o.floor if floor_y is None else floor_y)
    return qnormalize_rows(q), toes, w, v_height, v


def run_cummax(x, down):
    """x [F] made non-decreasing through each run of `down` frames (the largest so far in the run), 0 off them"""
    out = np.zeros(len(x))
    for a, b in runs(down):
        out[a:b + 1] = np.maximum.accumulate(np.asarray(x[a:b + 1], dtype=float))
    return out


def damped_up(x, tau, substeps=8):
    """x [F] followed where it rises by two first-order lags of `tau` frames in a row (critically damped: a step is
    taken 26 % in a frame, 59 % in two, 80 % in three), integrated in `substeps` steps a frame so that the frames get
    the continuous response; where it falls, at once.  From its first value: a foot that is already on its ball when
    the dance starts is not eased onto it."""
    x = np.asarray(x, dtype=float)
    out = np.empty(len(x))
    k = 1.0 - math.exp(-1.0 / (tau * substeps)) if tau > 0 else 1.0
    a = b = float(x[0]) if len(x) else 0.0
    for t, value in enumerate(x):
        if value <= b:
            a = b = value
        else:
            for _ in range(substeps if tau > 0 else 1):
                a += (value - a) * k
                b += (a - b) * k
        out[t] = b
    return out


def release(b, air, down, tau):
    """the bend [F]: b on the frames on the floor (down); off the floor, the shape in the air `air` and what the toes had
    beyond it on the last frame on the floor, going with a first order of `tau` frames; before the first, `air`"""
    out = np.array(air, dtype=float)
    last = None
    for t in range(len(out)):
        if down[t]:
            out[t] = b[t]
            last = t
        elif last is not None:
            out[t] = air[t] + (out[last] - air[last]) * math.exp(-(t - last) / tau)
    return out


def smooth_both_ways(x, tau):
    """x [F] through a first-order filter of `tau` frames run forward, then backward: no lag, a step spread each way"""
    k = 1.0 - math.exp(-1.0 / tau)
    y = np.array(x, dtype=float)
    for t in range(1, len(y)):
        y[t] = y[t - 1] + (y[t] - y[t - 1]) * k
    for t in range(len(y) - 2, -1, -1):
        y[t] = y[t + 1] + (y[t] - y[t + 1]) * k
    return y


def shell_low(o, ankle, q_foot, toes):
    """the lowest point [F] of the shoe's lower shell for the ankle at `ankle`, the foot turned q_foot, the toes `toes`"""
    return shell_at(o, ankle, q_foot, toes)[:, :, 1].min(axis=1)


def toes_touching(o, ankle, q_foot, hi, lo, floor_y, rounds=30):
    """per frame the bend between `hi` (the shoe's lowest point above floor_y) and `lo` (more bent down, at or below it)
    at which the lowest point comes onto floor_y: the bisection, kept on the side above the floor"""
    a, c = np.array(lo, dtype=float), np.array(hi, dtype=float)
    for _ in range(rounds):
        mid = 0.5 * (a + c)
        below = shell_low(o, ankle, q_foot, mid) < floor_y
        a = np.where(below, mid, a)
        c = np.where(below, c, mid)
    return c


def toe_bend(o, f, leg, q, rest, v, loaded, p, floor_y):
    """the toes' bend [F] (degrees, + extension, the turn of 足先EX against the foot) of the anatomical model for one foot
    turned q (after the roll and the range), on the floor by v, bearing weight by loaded:
    * on the floor the floor bends them: a foot on its ball has the toe box lying on the floor (the extension the foot's
      pitch asks, up to the cap of the MTP's extension as before).  Once a foot bears weight in a run of frames on the
      floor it stays on its ball until that run ends (a foot pushes off from the ball, it does not climb onto the rigid
      tip of a loafer as the weight leaves it); the weight coming on is taken smoothly (damped_up, TOE_LOAD_TAU), the
      heel coming down brings the toes down with it at once (the tip does not stay up off the floor);
    * nothing is bent before the forefoot is on the floor: in the air the toe box keeps the shoe's own shape, and after
      the toe-off it returns to it with TOE_RELEASE_TAU.  (No measured angle of relaxed or pointed toes in the air was
      found; walking keeps the hallux extended through the swing, Nester 2014, and pointe holds the toes in line with the
      metatarsals - inside a loafer, whose outside differs from the toes inside by 4 to 8 degrees: Bishop 2011,
      Ferguson 2026.  A toe box bending in the air on its own is what the merged layer showed before a landing);
    * a still pointed foot whose shoe hovers less than p["toe_reach"] over the floor reaches it with its toes (bent down
      until the shoe's lowest point is on the floor, up to TOE_FLEX_CAP), the ankle where it is;
    * never bent down into the floor: the bend toward flexion stops where the shoe's lowest point meets it, the ankle
      where the trace has it (the layer's heights move a foot off the floor only by the shift of the floor)."""
    pitch = np.degrees(np.arcsin(np.clip(qrot(q, o.a0)[:, 1], -1.0, 1.0)))
    room = max(0.0, p["limits"]["mtp_extension"][1] - rest["mtp"])
    flat = soft_limit(np.clip(-pitch, 0.0, None), 0.6 * room, room)          # the toe box laid on the floor
    down = np.asarray(v) >= 0.5
    gate = damped_up(run_cummax(np.asarray(v) * np.asarray(loaded), down), TOE_LOAD_TAU)
    air = np.zeros(len(q))                                                    # the shoe's own shape
    # the floor bends them as far as the foot is on it (v, the band of heights over the floor): a foot rising out of the
    # band at a lift-off lets its toes go with the lowering the heights let go by the same v (bent but only partly
    # lowered, the shoe would float with its toes bent up)
    b = release(np.asarray(v) * gate * flat, air, down, TOE_RELEASE_TAU)
    # where the foot is off the floor the layer leaves its height to the trace (but for the floor's shift)
    ankle = leg["ankle"] + np.array([0.0, floor_y - o.floor, 0.0])
    off = ~down
    if p.get("toe_reach", 0.0) > 0.0 and off.any():
        gap = shell_low(o, ankle, q, b) - floor_y
        y = f["ankle"][:, 1]
        rise = np.zeros(len(y))                                   # cm/s up, the larger of the steps into and out of a frame
        if len(y) > 1:
            step = np.diff(y) * FPS * UNIT_CM
            rise[1:] = step
            rise[:-1] = np.maximum(rise[:-1], step)
        weight = (off & (gap > 0.0)) * (1.0 - smoothstep(foot_speed(f, vertical=True), *TOE_REACH_SPEED)) \
            * (1.0 - smoothstep(rise, *TOE_REACH_RISE)) \
            * smoothstep(-pitch, *TOE_REACH_PITCH) * (1.0 - smoothstep(gap, 0.8 * p["toe_reach"], p["toe_reach"]))
        idx = np.flatnonzero(weight > 0.0)
        reach = np.zeros(len(b))
        if len(idx):
            lo = np.minimum(np.full(len(idx), -TOE_FLEX_CAP), b[idx])
            low_lo = shell_low(o, ankle[idx], q[idx], lo)
            r = np.where(low_lo <= floor_y, toes_touching(o, ankle[idx], q[idx], b[idx], lo, floor_y), lo)
            reach[idx] = weight[idx] * (r - b[idx])
        b = b + smooth_both_ways(reach, TOE_REACH_TAU)
    b = np.clip(b, -TOE_FLEX_CAP, room)
    # never bent down into the floor off it (the frames on it are put on the floor by the heights)
    low = shell_low(o, ankle, q, b)
    sunk = off & (b < 0.0) & (low < floor_y)
    if sunk.any():
        idx = np.flatnonzero(sunk)
        hi = np.zeros(len(idx))
        ok = shell_low(o, ankle[idx], q[idx], hi) >= floor_y
        b[idx] = np.where(ok, toes_touching(o, ankle[idx], q[idx], hi, b[idx], floor_y), 0.0)
    return b


def qnormalize_rows(q):
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def shell_at(o, ankle, q_foot, toes):
    """the shoe's lower shell [F, N, 3] for the ankle at `ankle`, the foot turned q_foot and the toes extended `toes`
    degrees"""
    q_ex = qmul(q_foot, qaxis(np.broadcast_to(X_AXIS, ankle.shape), np.radians(toes)))
    ex = ankle + qrot(q_foot, o.ex - o.ankle)
    return shell_world(o, {"ankle": ankle, "q_foot": q_foot, "ex": ex, "q_ex": q_ex})


def bridge(v, gap, low=None):
    """the on-floor weights v [F] with the dips of `gap` frames or fewer between two frames on the floor (v >= 0.5) filled
    to the lower of the two, where the shoe stays low through the dip (low [F] booleans; all, when not given)"""
    v = np.array(v, dtype=float)
    down = v >= 0.5
    for a, b in runs(~down):
        if a > 0 and b < len(v) - 1 and b - a + 1 <= gap and (low is None or bool(np.all(low[a:b + 1]))):
            v[a:b + 1] = np.maximum(v[a:b + 1], min(v[a - 1], v[b + 1]))
    return v


def eased_correction(c, v, radius, back=True):
    """the height a foot is moved by to put its sole on the floor, c [F] (units; v times the gap), as it is where the
    foot is down (v >= 0.5: the height then follows the floor exactly, the trace's jitter taken out) and carried into
    the frames around them from the nearest down frame with a raised cosine over `radius` frames: the foot is lowered
    before it lands and let go after it lifts, by no more than its landing or lift-off frame needs.  A frame in the air
    keeps the larger of that and its own (the height band near the floor).  back=False carries it only forward (let go
    after a lift-off, nothing taken before a landing: the anatomical toes bend when the forefoot is down, and the
    foot comes down onto its ball after its toes touch, at the trace's landing)."""
    c = np.asarray(c, dtype=float)
    down = np.asarray(v) >= 0.5
    envelope = smooth_max_envelope if back else forward_envelope
    pos = envelope(np.where(down, np.maximum(c, 0.0), 0.0), radius)
    neg = envelope(np.where(down, np.maximum(-c, 0.0), 0.0), radius)
    carried = np.where(neg > pos, -neg, pos)
    air = np.where(np.abs(carried) > np.abs(c), carried, c)
    out = np.where(down, c, air)
    if not back:
        # let go monotonically: a lift-off's last frame on the floor that is only partly down (0.5 <= v < 1) takes v of
        # its gap, less than the frame after it carries from the full frame before (the raised cosine of two frames):
        # the foot would rise, then dip back toward the floor it left.  A frame letting go keeps no more than the frame
        # before it.
        letgo = ~down & (np.abs(carried) > np.abs(c))
        for t in range(1, len(out)):
            if letgo[t] and out[t] * out[t - 1] > 0.0 and abs(out[t]) > abs(out[t - 1]):
                out[t] = out[t - 1]
    return out


def slerp_rows(q0, q1, t):
    """unit quaternions [N, 4] turned from q0 toward q1 by the share t [N] along the shorter way (MMD's interpolation of
    a turn on a linear curve)"""
    d = np.sum(q0 * q1, axis=1)
    q1 = np.where(d[:, None] < 0.0, -q1, q1)
    d = np.clip(np.abs(d), -1.0, 1.0)
    theta = np.arccos(d)
    sin = np.sin(theta)
    small = sin < 1e-6
    safe = np.where(small, 1.0, sin)
    w0 = np.where(small, 1.0 - t, np.sin((1.0 - t) * theta) / safe)
    w1 = np.where(small, t, np.sin(t * theta) / safe)
    return qnormalize_rows(w0[:, None] * q0 + w1[:, None] * q1)


def between_keys(rig, motion, keys, written, sub_t):
    """the rig's keys at the frames sub_t between whole frames: the bones the layer writes (`written`, bone indices, a
    key on every frame in `keys`) interpolated between their keys as MMD does on a linear curve (the place along the
    line, the turn along the shorter arc), the rest sampled from the dance with its own curves"""
    out = IK.sample(rig, motion, sub_t)
    lo = np.floor(sub_t).astype(int)
    fr = sub_t - lo
    for index in written:
        pos, rot = keys[index]
        rot = continuous(qnormalize_rows(np.asarray(rot, dtype=float)))
        out[index] = (pos[lo] * (1.0 - fr)[:, None] + pos[lo + 1] * fr[:, None], slerp_rows(rot[lo], rot[lo + 1], fr))
    return out


def sinks_between(rig, shoe, motion, keys, written, intervals, floor_y):
    """side -> how far the shoe dips below the floor between the frames t and t + 1 of each interval t in `intervals`
    [N] (units; negative: it stays above), checked at the SUB - 1 frames in between"""
    idx = np.asarray(intervals, dtype=int)
    if not len(idx):
        return {s: np.zeros(0) for s in shoe.sides}
    sub_t = (idx[:, None] + np.arange(1, SUB)[None, :] / float(SUB)).ravel()
    sol = IK.solve(rig, motion, sub_t, between_keys(rig, motion, keys, written, sub_t))
    out = {}
    for s, o in shoe.sides.items():
        low = shell_world(o, sol[s])[:, :, 1].min(axis=1).reshape(len(idx), SUB - 1).min(axis=1)
        out[s] = floor_y - low
    return out


def forward_envelope(x, radius):
    """smooth_max_envelope spread only to the following frames"""
    out = np.maximum(x, 0.0).copy()
    for k in range(1, radius + 1):
        g = 0.5 * (1.0 + math.cos(math.pi * k / (radius + 1)))
        out[k:] = np.maximum(out[k:], g * np.maximum(x[:-k], 0.0))
    return out


def smooth_max_envelope(x, radius):
    """a smooth envelope over the positive values of x: each value spread to its neighbours with a raised cosine of
    `radius` frames, the largest kept (so a single frame's raise starts and ends gently)"""
    out = np.maximum(x, 0.0).copy()
    for k in range(1, radius + 1):
        g = 0.5 * (1.0 + math.cos(math.pi * k / (radius + 1)))
        out[k:] = np.maximum(out[k:], g * np.maximum(x[:-k], 0.0))
        out[:-k] = np.maximum(out[:-k], g * np.maximum(x[k:], 0.0))
    return out


def leg_lengths(rig, shoe):
    """side -> the leg's length (hip to knee to ankle at rest, units)"""
    out = {}
    for s in shoe.sides:
        side = rig.sides[s]
        h0, k0, a0 = (np.array(rig.bones[i].position, dtype=float) for i in (side.thigh, side.knee, side.ankle))
        out[s] = float(np.linalg.norm(k0 - h0) + np.linalg.norm(a0 - k0))
    return out


def judged_feet(rig, shoe, sol, frames, floor_y, p, leg_length):
    """the feet (feet_of) as the layer judges them: with the landing (p["landing"], p["reach_knee"]) where the dance puts
    them, at their goals where the leg does not reach (MMD leaves such a foot over the floor, and a foot the dance stands
    on the floor would be taken for one in the air); else as MMD's IK puts them"""
    if p.get("landing", True) and p.get("reach_knee", 0.0) > 0.0:
        at_goal = {}
        for s, leg in sol.items():
            # only where the goal lies out of the leg's reach (MMD's lag behind a reachable goal is the pushes' to mend:
            # judging such a frame at its goal took feet standing on the floor for lifted ones, 48.3 s)
            short = (np.linalg.norm(leg["goal_ankle"] - leg["hip"], axis=1) > leg_length[s] - 1e-4)[:, None]
            d = np.where(short, leg["goal_ankle"] - leg["ankle"], 0.0)
            at_goal[s] = dict(leg, ankle=leg["ankle"] + d, ex=leg["ex"] + d, toe=leg["toe"] + d)
        return feet_of(rig, shoe, at_goal, frames, floor_y, p["heel_pitch_deg"])
    return feet_of(rig, shoe, sol, frames, floor_y, p["heel_pitch_deg"])


def layer(rig, shoe, motion, params=None, log=None):
    """(the output motion, the plan per side) of the foot layer on `motion`.

    Per frame and foot, from the feet as MMD's IK puts them:
    * the load: a foot near the floor bears the body's weight in proportion to its nearness to the pelvis seen from
      above (load_shares); a loaded foot whose sole faces the floor has its roll laid flat (the sole flat across the
      floor, the subtalar joint taking the shank's lean), eased in and out over EASE frames, as far as the subtalar
      joint takes it (the laying flat stops at the subtalar caps: where the roll against the shank is not read with
      trust, roll_reliable, the range's correction does not come back to it);
    * the range: the ankle complex's angles held inside REFERENCE by a soft limit (a foot on the floor may dorsiflex to
      LOADED_DORSI_CAP), except where the shank swings faster than SHANK_SWING a frame or the roll's reference cannot
      be trusted (roll_reliable): there the input's foot stays;
    * the toes: a loaded foot with its heel raised stands on the ball, 足先EX extending the toes so that the toe box
      lies on the floor (up to the cap of the MTP's extension).  params["toe_model"] "anatomical" (the default,
      toe_bend): the floor bends them as the forefoot takes the weight, a foot once on its ball stays on it until it
      leaves, the toe box returns to the shoe's shape after the toe-off and keeps it in the air; params["toe_reach"]
      (units, 0 by default) lets a still pointed foot just over the floor reach it with its toes.  "v1": the merged
      layer (the bend eased over EASE frames each way by the weight, the heights eased before a landing too);
    * the height: the trace's floor moved onto the floor (params["floor_y"]; by default the trace's own: no shift),
      the shoe of a foot on the floor (the ON_FLOOR band; judged as the trace's model stood with
      params["trace_toe_extra"], 0 by default) exactly on it, a standing foot's lift of BRIDGE frames or fewer bridged
      while the shoe itself stays under BRIDGE_LIFT, the correction carried into the frames around a contact over EASE
      frames (put down before the landing, let go after the lift-off: eased_correction; with the anatomical toes only
      after the lift-off: the foot comes down onto its ball after the touch, at the trace's landing), nothing below
      the floor.
      MMD's IK is solved again and the foot IK's goal pushed on where the ankle lags behind it (ROUNDS); the frames
      that do not follow are left at their best and listed (miss);
    * twice: the range is checked again against the shank that MMD reaches with the new heights, and (params["landing"],
      the default) the heel raised about the ball where that solve lands with a sinking pelvis or stands out of the
      leg's reach (heel_turn; 足ＩＫ's horizontal place then moves with the ankle so that the ball stays put), a foot
      skimming the floor in the dance left off it (SKIM_SPEED), the shoe placed at the input's goal where its leg does
      not reach and such a goal not pushed further; params["landing"] False is the layer before these (c012c32);
    * between the frames: the keys solved at 1/SUB frames as MMD interpolates them, both frames of an interval whose
      shoe dips below the floor raised by the dip (SUB_ROUNDS).
    The keys, on every frame (build): 足ＩＫ's height (its horizontal place but for the heel's turn and its turn as the
    input has them),
    つま先ＩＫ's goal on the turned toe, 足首's turn (the start of the toe IK), 足先EX's bend.  Nothing else changes."""
    p = default_params()
    p.update(params or {})
    floor_y = trace_floor(shoe) if p["floor_y"] is None else float(p["floor_y"])
    F = fk.last_frame(motion) + 1
    frames = list(range(F))
    keys = IK.sample(rig, motion, frames)
    sol = IK.solve(rig, motion, frames, keys)
    lowered = np.zeros(F)
    held = None
    pre_shares = pre_near = pre_v = None
    sink_info = {"runs": [], "acc_past_bound_frames": 0, "radius": [], "scale": []}
    on = p.get("hover")
    if (p.get("landing", True) if on is None else on) and len(shoe.sides) == 2 and "センター" in rig.by_name:
        # (None: with the landing) the figure held by nothing lowered onto the floor (hover_runs, hover_sink_profile)
        f0 = judged_feet(rig, shoe, sol, frames, floor_y, p, leg_lengths(rig, shoe))
        e = {s: trace_height(f0[s], o, p["trace_toe_extra"], key="low") for s, o in shoe.sides.items()}
        pelvis_y = np.mean([sol[s]["hip"][:, 1] for s in shoe.sides], axis=0)
        fall = pelvis_fall(rig, keys)
        two = list(shoe.sides)
        glide = np.where(e[two[0]] <= e[two[1]], fore_speed(f0[two[0]]), fore_speed(f0[two[1]]))    # (the lower shoe's)
        rr = hover_runs(e, pelvis_y, p["on_floor"], fall=fall, glide=glide, glide_max=p.get("hover_glide", HOVER_GLIDE))
        if rr:
            acc0 = -fall                    # (up +, as hover_sink_profile takes it)
            gap = np.minimum(*[e[s] for s in shoe.sides])
            lowered, past, radius, scale = hover_sink_profile(gap, rr, acc0)
            sink_info = {"runs": rr, "acc_past_bound_frames": past, "radius": radius, "scale": scale}
            # the shape is judged on the feet before the sink (shape_v, and the shares and nearness of the weight)
            pre_shares, pre_near = load_shares(shoe, f0, sol, p)
            pre_v = {s: floor_weight(f0[s], o, p) for s, o in shoe.sides.items()}
            sides = list(shoe.sides)
            lower = e[sides[0]] <= e[sides[1]]
            held = {s: np.zeros(F) for s in sides}
            for (a, b), k in zip(rr, scale):
                if k > 0.0:
                    held[sides[0]][a:b + 1] = lower[a:b + 1]
                    held[sides[1]][a:b + 1] = ~lower[a:b + 1]
            motion = sink_motion(rig, motion, keys, sol, lowered, F)
            keys = IK.sample(rig, motion, frames)
            sol = IK.solve(rig, motion, frames, keys)
    leg_length = {}
    for s in shoe.sides:
        side = rig.sides[s]
        h0, k0, a0 = (np.array(rig.bones[i].position, dtype=float) for i in (side.thigh, side.knee, side.ankle))
        leg_length[s] = float(np.linalg.norm(k0 - h0) + np.linalg.norm(a0 - k0))
    feet = judged_feet(rig, shoe, sol, frames, floor_y, p, leg_length)
    shares, near = load_shares(shoe, feet, sol, p)
    if held is not None:
        shares, near = pre_shares, pre_near
    new_keys = dict(keys)
    plan = {}

    def lowest(s, sol_):
        pl = plan[s]
        return shell_at(shoe.sides[s], sol_[s]["ankle"], pl["q_t"], pl["toes"])[:, :, 1].min(axis=1)

    heel = {s: None for s in shoe.sides}           # the heel raised about the ball (degrees, heel_turn), pass 2
    shift = {s: np.zeros((F, 3)) for s in shoe.sides}   # ... and the ankle's horizontal move that keeps the ball put
    key_shift = {s: np.zeros((F, 3)) for s in shoe.sides}

    def set_dy(s, dy):
        side = rig.sides[s]
        pos, rot = keys[side.leg_ik]
        new_keys[side.leg_ik] = (pos + key_shift[s] + np.stack([np.zeros(F), dy, np.zeros(F)], axis=1), rot)

    # two passes: the targets against the input's shank, the heights, a solve; then the targets again against the
    # shank that solve gives (a changed goal can swing MMD's knee elsewhere where the leg is nearly straight), and the
    # heel raised about the ball where that solve lands with a sinking pelvis or stands out of reach (heel_turn), the
    # heights again
    shank = sol
    for it in range(2):
        for s, o in shoe.sides.items():
            leg = dict(sol[s])
            for k in ("ankle", "knee", "q_shin"):
                leg[k] = shank[s][k]
            rest = rest_anatomy(rig, o, p["heel_pitch_deg"])
            q_t, toes, w, v, v_shape = foot_targets(o, feet[s], leg, rest, shares[s], near[s], p, floor_y, heel[s],
                                                    None if held is None else held[s],
                                                    None if held is None else pre_v[s] * (1.0 - held[s]))
            # heights: the trace's floor moved onto the visible floor (every frame by the same d1, so that a foot in
            # the air keeps its path), the shoe of a foot on the floor exactly on it (v), that correction eased into
            # the frames around (eased_correction), nothing below the floor
            # (with the landing: the shoe at the input's goal where its leg does not reach it, so that the goal is not
            # lowered by MMD's shortfall and run further out of reach)
            base = sol[s]["ankle"]
            if p.get("landing", True) and p.get("reach_knee", 0.0) > 0.0:
                base = np.where((sol[s]["reach"] > 1e-3)[:, None], sol[s]["goal_ankle"], base)
            low0 = shell_at(o, base + shift[s], q_t, toes)[:, :, 1].min(axis=1)
            d1 = floor_y - o.floor
            gap = floor_y - low0 - d1                     # what putting the sole on the floor adds to the shift
            anatomical = p.get("toe_model", "anatomical") != "v1"
            dy = d1 + eased_correction(v * gap, v, EASE, back=not anatomical)
            sink = smooth_max_envelope(floor_y - (low0 + dy), 3)              # nothing below the floor
            if anatomical:                                                     # (a foot on it stays exactly on it)
                sink = np.where(v >= 0.5, np.maximum(floor_y - (low0 + dy), 0.0), sink)
            dy = dy + sink
            target = low0 + dy
            plan[s] = {"q_t": q_t, "toes": toes, "w": w, "v": v, "v_shape": v_shape, "dy": target - low0, "d1": d1,
                       "target_low": target,
                       "share": shares[s], "floor_y": floor_y}
            set_dy(s, plan[s]["dy"])
        out_sol = IK.solve(rig, motion, frames, new_keys)
        # MMD's IK does not always put the ankle on its goal (a nearly straight leg lags behind a lifted goal): push
        # the goal on where the foot is on the floor until the sole reaches its planned height; a frame that does not
        # follow (an unreachable goal) is left at its best and listed (miss)
        for s, pl in plan.items():
            pl["miss"] = pl["target_low"] - lowest(s, out_sol)
            pl["stuck"] = np.zeros(F, dtype=bool)
        if p.get("landing", True) and p.get("reach_knee", 0.0) > 0.0:
            # (with the landing: a goal out of the leg's reach is not pushed: lowering it only runs it further away)
            for s, pl in plan.items():
                pl["stuck"] |= np.linalg.norm(out_sol[s]["goal_ankle"] - out_sol[s]["hip"], axis=1) > leg_length[s] - 1e-4
        for _ in range(int(p["rounds"])):
            tried = {}
            for s, pl in plan.items():
                push = (pl["v"] > 0.0) & ~pl["stuck"] & (np.abs(pl["miss"]) > 1e-3)
                if push.any():
                    tried[s] = (push, np.where(push, pl["dy"] + np.clip(pl["miss"], -0.15, 0.15), pl["dy"]))
                    set_dy(s, tried[s][1])
            if not tried:
                break
            try_sol = IK.solve(rig, motion, frames, new_keys)
            for s, (push, dy) in tried.items():
                pl = plan[s]
                miss = pl["target_low"] - lowest(s, try_sol)
                better = push & (np.abs(miss) < np.abs(pl["miss"]) - 1e-5)
                pl["stuck"] |= push & ~better
                pl["dy"] = np.where(better, dy, pl["dy"])
                pl["miss"] = np.where(better, miss, pl["miss"])
                set_dy(s, pl["dy"])
        out_sol = IK.solve(rig, motion, frames, new_keys)
        shank = out_sol
        if it == 0 and p.get("landing", True):
            for s, o in shoe.sides.items():
                pl = plan[s]
                # the planned foot at its goal (where the leg does not reach, MMD's ankle stops short of it)
                leg = dict(out_sol[s])
                leg["ankle"] = out_sol[s]["goal_ankle"]
                leg["ex"] = out_sol[s]["ex"] + (out_sol[s]["goal_ankle"] - out_sol[s]["ankle"])
                turn, ball, axis = heel_turn(rig, o, leg, pl["q_t"], pl["v_shape"], smoothstep(pl["share"], *p["load_share"]),
                                             p)
                if not np.any(turn > 0.0):
                    continue
                heel[s] = turn
                moved = about_ball(leg["ankle"], ball, axis, turn) - leg["ankle"]
                moved[:, 1] = 0.0                       # the height is the heights' (the shoe put on the floor)
                shift[s] = moved
                side = rig.sides[s]
                parent = qmul(sol[s]["q_ik"], qconj(qnormalize_rows(np.asarray(keys[side.leg_ik][1], dtype=float))))
                key_shift[s] = qrot(qconj(parent), moved)
    for s in plan:
        plan[s]["sink"] = lowered
        plan[s]["sink_info"] = sink_info
        plan[s]["heel"] = heel[s] if heel[s] is not None else np.zeros(F)
        plan[s]["shift"] = shift[s]

    def make_keys(out_sol):
        # the keys that make MMD's IK put the foot there: 足首 starts the toe IK already on the goal, つま先ＩＫ's
        # goal lies on the turned toe from the ankle MMD reaches, 足先EX bends the toes
        for s, o in shoe.sides.items():
            side = rig.sides[s]
            pl = plan[s]
            leg = out_sol[s]
            local = continuous(qnormalize_rows(qmul(qconj(leg["q_shin"]), pl["q_t"])))
            t0 = np.array(rig.bones[side.toe].position) - np.array(rig.bones[side.ankle].position)
            target = leg["ankle"] + qrot(pl["q_t"], t0)
            d0 = np.array(rig.bones[side.toe_ik].position) - np.array(rig.bones[side.leg_ik].position)
            toe_key = qrot(qconj(leg["q_ik"]), target - leg["goal_ankle"]) - d0
            new_keys[side.ankle] = (keys[side.ankle][0], local)
            new_keys[side.toe_ik] = (toe_key, keys[side.toe_ik][1])
            toes_q = qaxis(np.broadcast_to(X_AXIS, (F, 3)), np.radians(pl["toes"]))
            if side.ex is not None:
                new_keys[side.ex] = (keys[side.ex][0], toes_q)
            pl["names"] = {"leg_ik": rig.bones[side.leg_ik].name, "toe_ik": rig.bones[side.toe_ik].name,
                           "ankle": rig.bones[side.ankle].name,
                           "ex": rig.bones[side.ex].name if side.ex is not None else None,
                           "centre": "センター" if np.any(lowered > 0.0) else None}

    make_keys(out_sol)
    written_idx = [i for s in plan for i in (rig.sides[s].leg_ik, rig.sides[s].toe_ik, rig.sides[s].ankle,
                                               rig.sides[s].ex) if i is not None]
    # between the frames: MMD draws 240 fps and interpolates the keys there, so a foot turning on the floor from one
    # frame to the next (from its outer edge to its inner edge, say) can dip into the floor half way although both
    # frames stand on it.  Where it does, both frames of the interval are raised by the dip (the place of 足ＩＫ is
    # interpolated along a line, so the whole interval rises with them) and the keys made again (SUB_ROUNDS rounds).
    for pl in plan.values():
        pl["sub_raise"] = np.zeros(F)
    for _ in range(SUB_ROUNDS if F > 1 else 0):
        near = np.zeros(F - 1, dtype=bool)
        for pl in plan.values():
            tl = pl["target_low"] + pl["sub_raise"]
            near |= np.minimum(tl[:-1], tl[1:]) < floor_y + SUB_NEAR
        intervals = np.flatnonzero(near)
        sinks = sinks_between(rig, shoe, motion, new_keys, written_idx, intervals, floor_y)
        raised = False
        for s, d in sinks.items():
            up = np.zeros(F)
            dip = np.where(d > 0.25 * PEN_TOL, d + 0.25 * PEN_TOL, 0.0)
            np.maximum.at(up, intervals, dip)
            np.maximum.at(up, intervals + 1, dip)
            if up.any():
                raised = True
                plan[s]["sub_raise"] = plan[s]["sub_raise"] + up
                plan[s]["dy"] = plan[s]["dy"] + up
                set_dy(s, plan[s]["dy"])
        if not raised:
            break
        out_sol = IK.solve(rig, motion, frames, new_keys)
        make_keys(out_sol)
    written = {}
    for s, pl in plan.items():
        side = rig.sides[s]
        for index in (side.leg_ik, side.toe_ik, side.ankle) + ((side.ex,) if side.ex is not None else ()):
            written[rig.bones[index].name] = new_keys[index]
    return build(motion, written, F), plan


def build(motion, written, F):
    """every key of a bone the layer does not write, as it was; a key on every frame for the others (the linear curve,
    the physics bytes of the input's key in force, as tools/anatomy_layer.py)"""
    tracks = fk.tracks_of(motion)
    labels = set()
    out = []
    curves = {}
    for name, (pos, rot) in written.items():
        ks = tracks.get(name) or tracks.get(fk.vmd_name(name)) or []
        label = ks[0].name if ks else fk.vmd_name(name)
        raw = ks[0].raw_name if ks else None
        labels |= {name, fk.vmd_name(name), label}
        frames = [k.frame for k in ks]
        ki = 0
        held = ks[0].interpolation if ks else None
        rot = continuous(qnormalize_rows(np.asarray(rot, dtype=float)))
        for f in range(F):
            while ki < len(ks) and frames[ki] <= f:
                held = ks[ki].interpolation
                ki += 1
            if held not in curves:
                curves[held] = vmd.bone_interpolation(vmd.LINEAR_CURVE, keep=held)
            q = fk.stored(tuple(float(v) for v in rot[f]))
            out.append(vmd.BoneKey(label, f, tuple(float(v) for v in pos[f]), q, curves[held], raw_name=raw))
    bones = [k for k in motion.bones if k.name not in labels] + out
    return vmd.Motion(model_name=motion.model_name, bones=bones, morphs=list(motion.morphs),
                      cameras=list(motion.cameras), lights=list(motion.lights), shadows=list(motion.shadows),
                      show_iks=list(motion.show_iks))


# ---- the command ---------------------------------------------------------------------------------------------------

def between_report(rig, shoe, motion, floor_y, near=SUB_NEAR):
    """side tag -> the shoe between the frames as MMD draws it (SUB a frame, the keys interpolated by their own curves):
    the intervals checked (either end's lowest point within `near` of the floor), those dipping below the floor more
    than PEN_TOL, the deepest dip (cm) and the worst ones [the 1/SUB frame of the deepest, cm]"""
    F = fk.last_frame(motion) + 1
    empty = {"checked": 0, "below": 0, "deepest_cm": 0.0, "worst": []}
    if F < 2:
        return {TAGS[s]: dict(empty) for s in shoe.sides}
    sol = IK.solve(rig, motion, range(F))
    near_side = {}
    for s, o in shoe.sides.items():
        low = shell_world(o, sol[s])[:, :, 1].min(axis=1)
        near_side[s] = np.minimum(low[:-1], low[1:]) < floor_y + near
    idx = np.flatnonzero(np.logical_or.reduce(list(near_side.values())))
    if not len(idx):
        return {TAGS[s]: dict(empty) for s in shoe.sides}
    sub_t = (idx[:, None] + np.arange(1, SUB)[None, :] / float(SUB)).ravel()
    ssol = IK.solve(rig, motion, sub_t)
    out = {}
    for s, o in shoe.sides.items():
        mine = near_side[s][idx]
        dip = floor_y - shell_world(o, ssol[s])[:, :, 1].min(axis=1).reshape(len(idx), SUB - 1)
        deepest = dip.max(axis=1)
        deepest = np.where(mine, deepest, -np.inf)
        order = np.argsort(-deepest)[:5]
        out[TAGS[s]] = {"checked": int(mine.sum()), "below": int((deepest > PEN_TOL).sum()),
                        "deepest_cm": _r(max(0.0, float(deepest.max())) * UNIT_CM, 2),
                        "worst": [[_r(float(idx[i] + (1 + int(np.argmax(dip[i]))) / float(SUB)), 3),
                                   _r(float(deepest[i]) * UNIT_CM, 2)] for i in order if np.isfinite(deepest[i])
                                  and deepest[i] > 0.0]}
    return out


def measure_report(rig, shoe, motion, floor_y, frames=None, contact_from=None, toe_extra=0.0):
    """(measures, report, contacts) of a dance: measure_feet over every frame and summarize per side.  The contact
    frames are the motion's own (against the trace's floor, with the trace model's toe: trace_height) unless
    `contact_from` gives them (side -> mask), so that an output is judged on its input's contact."""
    if frames is None:
        frames = range(0, fk.last_frame(motion) + 1)
    m = measure_feet(rig, shoe, motion, frames, floor_y)
    rep, contacts = {}, {}
    for s, f in m.items():
        o = shoe.sides[s]
        c = contact_from[s] if contact_from is not None else contact_mask(trace_height(f, o, toe_extra) + o.floor,
                                                                          o.floor)
        contacts[s] = c
        rep[TAGS[s]] = summarize(f, c, floor_y)
        est, n = toe_extra_estimate(f, o)
        rep[TAGS[s]]["trace_toe_extra_estimate_cm"] = {"cm": _r(est * UNIT_CM, 2) if est is not None else None,
                                                       "frames": n}
    return m, rep, contacts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--report")
    ap.add_argument("--floor-y", type=float, default=None,
                    help="the visible floor's height (MMD units); the rest pose's soles (the trace's floor) if not given")
    ap.add_argument("--trace-toe-cm", type=float, default=0.0,
                    help="how much further the trace's model's foot reached from the ankle to the toe (cm): its pointed "
                         "toe touched the floor where this model's stops short; the report's "
                         "trace_toe_extra_estimate_cm measures it from the dance")
    ap.add_argument("--toes", choices=TOE_MODELS, default="anatomical",
                    help="the toes (足先EX): anatomical (the floor bends them, a foot on its ball stays on it until it "
                         "leaves, they return over TOE_RELEASE_TAU after it, nothing bent in the air) or v1 (the merged "
                         "layer's output, unchanged)")
    ap.add_argument("--toe-reach-cm", type=float, default=0.0,
                    help="a still pointed foot whose shoe hovers less than this over the floor reaches it with its toes, "
                         "bent down up to TOE_FLEX_CAP (anatomical; 0, the default, for none; 2.5 is TOE_REACH)")
    ap.add_argument("--landing", choices=("human", "heel", "off"), default=None,
                    help="human (the default): a loaded touchdown with a sinking pelvis comes down on the forefoot and "
                         "lowers its heel as the pelvis sinks, a standing leg out of reach rises onto its ball, a foot "
                         "skimming the floor in the dance is not pressed onto it; heel: the touchdown's heel alone; "
                         "off: the layer before them (c012c32), "
                         "byte for byte")
    ap.add_argument("--hover", choices=("sink", "off"), default=None,
                    help="sink (the default with --landing human or heel): where no foot is on the floor but the lower shoe "
                         "hovers under HOVER_MAX over it and the pelvis does not fall as in a flight, the whole figure "
                         "(centre and leg IKs) is lowered onto the floor (hover_runs); off (the default with --landing "
                         "off): left as the dance has it")
    ap.add_argument("--hover-glide", type=float, default=HOVER_GLIDE, metavar="CM_S",
                    help="the sink takes only the frames whose lower shoe moves along the floor slower than this (cm/s, "
                         "%(default)s: TOE_SLIDE's, under which a pointed foot is taken to stand on the trace model's toe); "
                         "a step's swing skimming the floor faster is left over it, lowered it would slide along the floor "
                         "(a large value lowers those too)")
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()
    if not args.measure_only:
        if not args.out:
            raise SystemExit("OUT.vmd is needed unless --measure-only")
        if os.path.abspath(args.out) == os.path.abspath(args.dance):
            raise SystemExit("OUT.vmd is the dance itself: write the layer's dance elsewhere")
    rig = IK.LegRig.load(args.model)
    shoe = Shoe.load(rig, args.model)
    motion = vmd.load(args.dance)
    off = rig.check_iks(motion)
    if off:
        raise SystemExit("the dance switches off %s: this layer solves them as on" % ", ".join(off))
    floor_y = trace_floor(shoe) if args.floor_y is None else args.floor_y
    extra = args.trace_toe_cm / UNIT_CM
    landing_warning = None
    if args.landing is None:
        args.landing = "human"
        if not after_a_foot_layer(motion):
            # the order C (feet -> balance -> feet) runs this layer twice; its first run, before the balance layer, wants
            # --landing off (with the heel there the balance layer sets the pelvis elsewhere and the landing's sink
            # leaves the human range, feet_landing NOTES).  A dance that no foot layer has written yet may be that run.
            landing_warning = ("no --landing given on a dance that no foot layer has written (its toes have no key on "
                               "every frame): if this is the first foot layer of the order C, before the balance layer, "
                               "give --landing off")
            print("WARNING: " + landing_warning, file=sys.stderr)
    m_in, rep, contacts = measure_report(rig, shoe, motion, floor_y, toe_extra=extra)
    report = {"input": rep, "floor_y": floor_y, "trace_floor": trace_floor(shoe), "trace_toe_cm": args.trace_toe_cm,
              "heel_pitch_deg": HEEL_PITCH_DEG, "toe_model": args.toes, "landing_model": args.landing,
              "landing_warning": landing_warning,
              "hover": (args.hover or ("off" if args.landing == "off" else "sink")), "hover_glide_cm_s": args.hover_glide,
              "toe_reach_cm": max(0.0, args.toe_reach_cm),
              "seconds": None}
    report["toes"] = {"input": {TAGS[s]: toe_summary(m_in[s], contacts[s], floor_y) for s in m_in}}
    if not args.measure_only:
        out, plan = layer(rig, shoe, motion, {"floor_y": floor_y, "trace_toe_extra": extra, "toe_model": args.toes,
                                              "toe_reach": max(0.0, args.toe_reach_cm) / UNIT_CM,
                                              "landing": args.landing != "off",
                                              "reach_knee": REACH_KNEE_DEG if args.landing == "human" else 0.0,
                                              "skim": args.landing == "human",
                                              "hover": (args.hover or ("off" if args.landing == "off" else "sink")) == "sink",
                                              "hover_glide": args.hover_glide})
        vmd.dump(out, args.out)
        back = vmd.load(args.out)                       # judge what was written, read back
        m_out, rep_out, _ = measure_report(rig, shoe, back, floor_y, contact_from=contacts)
        report["output"] = rep_out
        report["toes"]["output"] = {TAGS[s]: toe_summary(m_out[s], contacts[s], floor_y) for s in m_out}
        report["change"] = {TAGS[s]: compare(m_in[s], m_out[s], contacts[s]) for s in m_in}
        info = next(iter(plan.values()))["sink_info"]
        sk = next(iter(plan.values()))["sink"]
        report["hover_sink"] = {"runs": len(info["runs"]), "run_frames": int(sum(b - a + 1 for a, b in info["runs"])),
                                "sunk_frames": int((sk > 1e-4).sum()), "max_cm": _r(float(sk.max()) * UNIT_CM, 2),
                                "acc_past_bound_frames": info["acc_past_bound_frames"],
                                "runs_lessened": int(sum(1 for k in info["scale"] if k < 1.0)),
                                "runs_dropped": int(sum(1 for k in info["scale"] if k <= 0.0)),
                                "runs_s": [[_r(a / FPS, 2), _r((b + 1) / FPS, 2)] for a, b in info["runs"]][:200]}
        report["unreached"] = {TAGS[s]: {"frames": int((np.abs(pl["miss"]) > 0.025).sum()),
                                         "worst_cm": _r(float(np.abs(pl["miss"]).max()) * UNIT_CM, 2)}
                               for s, pl in plan.items()}
        report["untouched"] = untouched(motion, back, plan)
        report["landing"] = {TAGS[s]: {"heel_raised_frames": int((pl["heel"] > 0.0).sum()),
                                       "heel_turn_max_deg": _r(float(pl["heel"].max()), 2),
                                       "ankle_shift_max_cm": _r(float(np.linalg.norm(pl["shift"], axis=1).max()) * UNIT_CM, 2)}
                             for s, pl in plan.items()}
        report["between_frames"] = {
            "input": between_report(rig, shoe, motion, floor_y), "output": between_report(rig, shoe, back, floor_y),
            "layer": {TAGS[s]: {"raised_frames": int((pl["sub_raise"] > 0.0).sum()),
                                "max_raise_cm": _r(float(pl["sub_raise"].max()) * UNIT_CM, 2)} for s, pl in plan.items()}}
    report["seconds"] = round(time.time() - t0, 1)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    print("floor y %.4f (the trace's %.4f)" % (floor_y, report["trace_floor"]))
    for which in ("input", "output"):
        for tag, r in report.get(which, {}).items():
            print("%s %s: contact %d/%d, penetration %d frames (deepest %s cm), hover in contact p50 %s cm, roll in "
                  "contact p50 %s p95 %s" % (
                      which, tag, r["contact_frames"], r["frames"], r["penetration"]["frames"],
                      r["penetration"]["deepest_cm"], r["hover_in_contact_cm"].get("p50"),
                      r["roll_in_contact_deg"].get("p50"), r["roll_in_contact_deg"].get("p95")))
    for which, per in report["toes"].items():
        for tag, t in per.items():
            print("toes %s %s: push-offs %s, bend at a heel-up toe-off p50 %s, on the rigid tip %d frames, bent up in the "
                  "air %d (before a landing %d), tip up on the floor %d, still pointed hover %d frames" % (
                      which, tag, t["push_off"]["from"], t["push_off"]["bend_at_heel_up_toe_off"].get("p50"),
                      t["on_the_tip_frames"], t["bent_up_in_the_air"]["frames"],
                      t["bent_up_in_the_air"]["before_a_landing"], t["tip_up_on_the_floor"]["frames"],
                      t["still_pointed_hover"]["frames"]))
    if "untouched" in report:
        print("untouched bones identical: %s" % report["untouched"]["identical"])
    return 0


def after_a_foot_layer(motion):
    """True when a foot layer has written the dance already: its toes' bone (足先EX) holds a key on (nearly) every frame,
    as build writes it"""
    F = fk.last_frame(motion) + 1
    tracks = fk.tracks_of(motion)
    n = max(len(tracks.get(s + "足先EX", []) or tracks.get(fk.vmd_name(s + "足先EX"), []) or []) for s in SIDES)
    return F > 1 and n >= 0.9 * F


def untouched(before, after, plan):
    """the bones the layer does not write: their keys byte for byte the same"""
    written = set()
    for pl in plan.values():
        for n in pl["names"].values():
            if n:
                written |= {n, fk.vmd_name(n)}

    def rows(m):
        return sorted((k.name, k.frame, k.position, k.rotation, bytes(k.interpolation)) for k in m.bones
                      if k.name not in written)
    a, b = rows(before), rows(after)
    return {"identical": a == b, "keys": len(a), "written": sorted(written),
            "morphs_identical": [(k.name, k.frame, k.weight) for k in before.morphs] ==
                                [(k.name, k.frame, k.weight) for k in after.morphs]}


if __name__ == "__main__":
    sys.exit(main())
