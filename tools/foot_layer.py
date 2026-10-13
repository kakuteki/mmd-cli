"""Feet that carry weight: the ankles, the feet and the toes of a dance made anatomical, and their contact with the floor.

    python tools/foot_layer.py DANCE.vmd MODEL.pmx OUT.vmd --report r.json [--floor-y 0.0] [--measure-only]

(the measuring half; the layer itself is described where it is defined, below.)

The feet are where MMD's IK puts them (tools/leg_ik.py, checked against MMD's renders).  The shoe is read from the
model's mesh: its sole is the bottom layer of the vertices skinned on the foot (足首D, 足先EX), each with its weight on
足先EX (the toes' bone, the ball of the foot), so that the sole bends with the toes as the skin does (linear blend).

Measures, per frame and foot (Measure):
* the sole's lowest point, and the lowest of its heel and of its forefoot (split at the widest gap along the foot);
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
CONTACT_ENTER = 0.03            # units above the trace's floor: a flat sole this low is on the floor
CONTACT_EXIT = 0.06             # ... and leaves it above this
HEEL_UP_DEG = 4.0               # a foot on the floor pitched toes-down more than this stands on its forefoot
# The pitch of the foot inside Sour's Rin's loafers: the line from the heel's seat (the top of the heel block, about
# 0.55 above the sole, behind the block's middle) to the ball (足先EX, the forefoot's sole 0.11 + 0.05) rises about
# 0.41 over 1.0 unit: 22-23 degrees (read from the mesh, tools: _spike/out/stage6/feet/s05_shoe.py).  A barefoot model
# has 0.  It shifts the anatomical ankle angle (plantarflexion inside the shoe) and the toes' (extension).
HEEL_PITCH_DEG = 23.0


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


def sole_world(o, leg):
    """the sole's points [F, N, 3] for one side's solved leg (leg_ik.solve), skinned linearly on the foot and the toes"""
    pa = leg["ankle"][:, None, :] + qrot(leg["q_foot"][:, None, :], (o.points - o.ankle)[None])
    pe = leg["ex"][:, None, :] + qrot(leg["q_ex"][:, None, :], (o.points - o.ex)[None])
    w = o.w_ex[None, :, None]
    return (1.0 - w) * pa + w * pe


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


# ---- the rest pose's anatomy ---------------------------------------------------------------------------------------

def rest_anatomy(rig, s, heel_pitch_deg=HEEL_PITCH_DEG):
    """(dorsiflexion at rest, toes' extension at rest), degrees: the shank's forward lean at rest (the knee ahead of the
    ankle) less the foot's pitch in the shoe; the toes lie on the shoe's toe box, extended by the same pitch"""
    side = rig.sides[s]
    knee = np.array(rig.bones[side.knee].position, dtype=float)
    ankle = np.array(rig.bones[side.ankle].position, dtype=float)
    shank = knee - ankle
    lean = math.degrees(math.atan2(-shank[2], shank[1]))           # the knee toward -Z (forward) leans forward
    return lean - heel_pitch_deg, heel_pitch_deg


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
        pitch, roll, yaw = world_pitch_roll(o, leg["q_foot"])
        flat_q, _ = unrolled(o, leg["q_foot"])
        flat_leg = dict(leg)
        flat_leg["q_foot"] = flat_q
        flat_leg["q_ex"] = qmul(flat_q, qmul(qconj(leg["q_foot"]), leg["q_ex"]))
        flat_leg["ex"] = leg["ankle"] + qrot(flat_q, qrot(qconj(leg["q_foot"]), leg["ex"] - leg["ankle"]))
        flat_y = sole_world(o, flat_leg)[:, :, 1]
        a, b, c = xzy_angles(leg["local_foot"])
        sign = 1.0 if s == "左" else -1.0
        rest_dorsi, rest_mtp = rest_anatomy(rig, s, heel_pitch_deg)
        q_toes = qmul(qconj(leg["q_foot"]), leg["q_ex"])                 # 足先EX against the foot: +X lifts the toes
        mtp = np.degrees(2.0 * np.arctan2(q_toes[:, 0], q_toes[:, 3]))
        mtp = (mtp + 180.0) % 360.0 - 180.0
        toes_fwd = qrot(leg["q_ex"], o.a0)
        toes_pitch = np.degrees(np.arcsin(np.clip(toes_fwd[:, 1], -1.0, 1.0)))   # the toe box against the floor
        out[s] = {
            "frames": np.array(frames), "low": y.min(axis=1), "heel_low": y[:, o.heel].min(axis=1),
            "fore_low": y[:, o.fore].min(axis=1), "flat_low": flat_y.min(axis=1),
            "flat_heel_low": flat_y[:, o.heel].min(axis=1), "flat_fore_low": flat_y[:, o.fore].min(axis=1),
            "pitch": pitch, "roll": roll, "yaw": yaw,
            "dorsi": np.degrees(a) + rest_dorsi, "inversion": -sign * np.degrees(b), "adduction": sign * np.degrees(c),
            "mtp": mtp + rest_mtp, "knee": -np.degrees(leg["knee_angle"]), "reach": leg["reach"],
            "ankle": leg["ankle"], "q_foot": leg["q_foot"], "q_ex": leg["q_ex"], "q_shin": leg["q_shin"],
            "heel_xz": world[:, o.heel][:, :, [0, 2]].mean(axis=1), "fore_xz": world[:, o.fore][:, :, [0, 2]].mean(axis=1),
            "trace_floor": o.floor, "floor": float(floor_y), "rest_dorsi": rest_dorsi, "rest_mtp": rest_mtp,
            "toes_pitch": toes_pitch,
        }
    return out


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
PART_TOL = 0.05                 # units: a part of the sole this much higher than the other is off the floor
TOES_FLAT_DEG = 8.0             # a toe box within this of level lies on the floor (on a raised heel: the toes bent)
REFERENCE = {                   # (soft start, cap) in degrees; the anatomical angles of measure_feet (see ROM below)
    "dorsiflexion": (20.0, 36.0), "plantarflexion": (45.0, 67.0), "inversion": (30.0, 36.0), "eversion": (20.0, 25.0),
    "mtp_extension": (60.0, 90.0)}


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
    hov = (f["flat_low"] - floor_y)[contact]
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
    # touch-downs and lift-offs
    heel_up = f["flat_heel_low"] - f["flat_fore_low"]
    tds, kinds, to_flat = [], {"heel": 0, "fore": 0, "flat": 0}, []
    for a, b in runs(contact):
        if a == 0:
            continue
        tds.append(a)
        dh0 = heel_up[a]
        kind = "fore" if dh0 > PART_TOL else ("heel" if dh0 < -PART_TOL else "flat")
        kinds[kind] += 1
        if kind == "fore":
            g = a
            while g <= b and heel_up[g] > PART_TOL:
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
        dh0 = heel_up[b]
        los["fore_last" if dh0 > PART_TOL else ("heel_last" if dh0 < -PART_TOL else "flat")] += 1
    out["liftoffs"] = los
    hu = contact & (heel_up > PART_TOL)
    out["heel_up_contact_frames"] = int(hu.sum())
    out["heel_up_toe_box_pitch_deg"] = stats(f["toes_pitch"][hu])
    out["heel_up_toe_box_flat_frames"] = int((hu & (np.abs(f["toes_pitch"]) < TOES_FLAT_DEG)).sum())
    # the anatomical angles
    loaded = contact
    rom = {}
    for name, x, m in (("dorsiflexion", f["dorsi"], None), ("plantarflexion", -f["dorsi"], None),
                       ("inversion", f["inversion"], None), ("eversion", -f["inversion"], None),
                       ("mtp_extension", f["mtp"], None)):
        start, cap = limits[name]
        rom[name] = {"beyond_reference": int((x > start).sum()), "beyond_cap": int((x > cap).sum()),
                     "beyond_cap_loaded": int(((x > cap) & loaded).sum()), "max": _r(float(x.max()), 1)}
    out["anatomy"] = rom
    out["adduction_abs_deg"] = stats(np.abs(f["adduction"]))
    out["steps"] = {"foot_deg_per_frame": stats(angle_steps(f["q_foot"])),
                    "toes_deg_per_frame": stats(angle_steps(qmul(qconj(f["q_foot"]), f["q_ex"]))),
                    "ankle_cm_per_frame": stats(np.linalg.norm(np.diff(f["ankle"], axis=0), axis=1) * UNIT_CM)}
    return out


def compare(f_in, f_out, contact):
    """how far the output's foot is from the input's: the foot's world turn (degrees) and the ankle's place (cm), in
    contact and in the air"""
    d = np.abs(np.sum(f_in["q_foot"] * f_out["q_foot"], axis=1))
    turn = np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))
    move = np.linalg.norm(f_out["ankle"] - f_in["ankle"], axis=1) * UNIT_CM
    return {"foot_turn_deg": {"contact": stats(turn[contact]), "air": stats(turn[~contact])},
            "ankle_move_cm": {"contact": stats(move[contact]), "air": stats(move[~contact])}}


# ---- the layer -----------------------------------------------------------------------------------------------------

LOAD_FULL = 0.03                # units above the trace's floor (the flat sole): the foot bears weight below this
LOAD_NONE = 0.30                # ... and none above (2.4 cm); between, a smoothstep: the roll is laid flat this way
ON_FLOOR = (0.03, 0.10)         # the band (units above the trace's floor) over which the sole is put onto the floor and
                                # the toes take a raised heel: below, on the floor; above, the floor shift alone
TWIST = (45.0, 70.0)            # adduction / abduction against the shank (soft start, cap), in the air only
EASE = 4                        # frames over which the flattening and the toes come and go
ROUNDS = 3                      # rounds of solving the legs again to put the sole on the floor
X_AXIS = np.array([1.0, 0.0, 0.0])


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


def default_params():
    return {"floor_y": 0.0, "load_full": LOAD_FULL, "load_none": LOAD_NONE, "on_floor": ON_FLOOR, "flatten": True,
            "rom": True, "toes": True, "limits": dict(REFERENCE), "twist": TWIST, "heel_pitch_deg": HEEL_PITCH_DEG,
            "rounds": ROUNDS}


def foot_targets(o, f, leg, rest_dorsi, rest_mtp, p, s):
    """the foot's world turn q_t [F, 4] and the toes' turn (degrees of extension added by 足先EX) for one side, and the
    loading weight w [F]: the roll laid flat as the foot takes weight, the ankle complex inside its range, the toes
    bent so that a raised heel stands on the ball with the toe box on the floor"""
    sign = 1.0 if s == "左" else -1.0
    e = f["flat_low"] - o.floor
    # the weights spread over EASE frames each way (a raised cosine): a fast foot crosses the height band in a frame or
    # two, but the roll is laid flat and the toes bend and relax over about 0.13 s
    w = smooth_max_envelope(1.0 - smoothstep(e, p["load_full"], p["load_none"]), EASE)
    v = 1.0 - smoothstep(e, *p["on_floor"])
    q = leg["q_foot"]
    if p["flatten"]:
        _, ang = unrolled(o, q)
        axis = qrot(q, o.a0)
        q = qmul(qaxis(axis, np.radians(w * ang)), q)
    if p["rom"]:
        lim = p["limits"]
        loc = qmul(qconj(leg["q_shin"]), q)
        a, b, c = xzy_angles(loc)
        dorsi = np.degrees(a) + rest_dorsi
        inv = -sign * np.degrees(b)
        add = sign * np.degrees(c)
        dorsi = soft_band(dorsi, lim["plantarflexion"], lim["dorsiflexion"])
        inv = soft_band(inv, lim["eversion"], lim["inversion"])
        add = w * add + (1.0 - w) * soft_band(add, p["twist"], p["twist"])     # no spinning of a loaded foot
        loc = xzy_quat(np.radians(dorsi - rest_dorsi), np.radians(-sign * inv), np.radians(sign * add))
        q = qmul(leg["q_shin"], loc)
    toes = np.zeros(len(q))
    if p["toes"]:
        pitch = np.degrees(np.arcsin(np.clip(qrot(q, o.a0)[:, 1], -1.0, 1.0)))
        room = max(0.0, p["limits"]["mtp_extension"][1] - rest_mtp)
        toes = smooth_max_envelope(v * soft_limit(np.clip(-pitch, 0.0, None), 0.6 * room, room), EASE)
    return qnormalize_rows(q), toes, w, v


def qnormalize_rows(q):
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def sole_at(o, ankle, q_foot, toes):
    """the sole's points [F, N, 3] for the ankle at `ankle`, the foot turned q_foot and the toes extended `toes` degrees"""
    q_ex = qmul(q_foot, qaxis(np.broadcast_to(X_AXIS, ankle.shape), np.radians(toes)))
    ex = ankle + qrot(q_foot, o.ex - o.ankle)
    return sole_world(o, {"ankle": ankle, "q_foot": q_foot, "ex": ex, "q_ex": q_ex})


def smooth_max_envelope(x, radius):
    """a smooth envelope over the positive values of x: each value spread to its neighbours with a raised cosine of
    `radius` frames, the largest kept (so a single frame's raise starts and ends gently)"""
    out = np.maximum(x, 0.0).copy()
    for k in range(1, radius + 1):
        g = 0.5 * (1.0 + math.cos(math.pi * k / (radius + 1)))
        out[k:] = np.maximum(out[k:], g * np.maximum(x[:-k], 0.0))
        out[:-k] = np.maximum(out[:-k], g * np.maximum(x[k:], 0.0))
    return out


def layer(rig, shoe, motion, params=None, log=None):
    """(the output motion, the plan per side) of the foot layer on `motion` (see the module docstring)"""
    p = default_params()
    p.update(params or {})
    floor_y = float(p["floor_y"])
    F = fk.last_frame(motion) + 1
    frames = list(range(F))
    keys = IK.sample(rig, motion, frames)
    sol = IK.solve(rig, motion, frames, keys)
    feet = feet_of(rig, shoe, sol, frames, floor_y, p["heel_pitch_deg"])
    plan = {}
    new_keys = dict(keys)
    for s, o in shoe.sides.items():
        side = rig.sides[s]
        rest_dorsi, rest_mtp = rest_anatomy(rig, s, p["heel_pitch_deg"])
        q_t, toes, w, v = foot_targets(o, feet[s], sol[s], rest_dorsi, rest_mtp, p, s)
        # heights: the trace's floor moved onto the visible floor (every frame by the same d1, so that a foot in the
        # air keeps its path), the sole of a foot on the floor exactly on it (v), nothing below it
        low0 = sole_at(o, sol[s]["ankle"], q_t, toes)[:, :, 1].min(axis=1)
        d1 = floor_y - o.floor
        target = v * floor_y + (1.0 - v) * (low0 + d1)
        target = target + smooth_max_envelope(floor_y - target, 3)
        dy = target - low0
        pos, rot = keys[side.leg_ik]
        new_keys[side.leg_ik] = (pos + np.stack([np.zeros(F), dy, np.zeros(F)], axis=1), rot)
        plan[s] = {"q_t": q_t, "toes": toes, "w": w, "v": v, "dy": dy, "d1": d1, "target_low": target}
    out_sol = IK.solve(rig, motion, frames, new_keys)
    # MMD's IK does not always put the ankle on its goal (a nearly straight leg lags behind a lifted goal): push the
    # goal on where the foot bears weight until the sole reaches its planned height; a frame that does not follow
    # (an unreachable goal) is left at its best and listed
    def lowest(s, sol_):
        pl = plan[s]
        return sole_at(shoe.sides[s], sol_[s]["ankle"], pl["q_t"], pl["toes"])[:, :, 1].min(axis=1)

    def set_dy(s, dy):
        side = rig.sides[s]
        pos, rot = keys[side.leg_ik]
        new_keys[side.leg_ik] = (pos + np.stack([np.zeros(F), dy, np.zeros(F)], axis=1), rot)

    for s, pl in plan.items():
        pl["miss"] = pl["target_low"] - lowest(s, out_sol)
        pl["stuck"] = np.zeros(F, dtype=bool)
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
    # the keys that make MMD's IK put the foot there: 足首 starts the toe IK already on the goal, つま先ＩＫ's goal
    # lies on the turned toe from the ankle MMD reaches, 足先EX bends the toes
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
                       "ankle": rig.bones[side.ankle].name, "ex": rig.bones[side.ex].name if side.ex is not None else None}
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

def measure_report(rig, shoe, motion, floor_y, frames=None, contact_from=None):
    """(measures, report, contacts) of a dance: measure_feet over every frame and summarize per side.  The contact
    frames are the motion's own (against the trace's floor) unless `contact_from` gives them (side -> mask), so that an
    output is judged on its input's contact."""
    if frames is None:
        frames = range(0, fk.last_frame(motion) + 1)
    m = measure_feet(rig, shoe, motion, frames, floor_y)
    rep, contacts = {}, {}
    for s, f in m.items():
        c = contact_from[s] if contact_from is not None else contact_mask(f["flat_low"], f["trace_floor"])
        contacts[s] = c
        rep[TAGS[s]] = summarize(f, c, floor_y)
    return m, rep, contacts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--report")
    ap.add_argument("--floor-y", type=float, default=0.0)
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()
    rig = IK.LegRig.load(args.model)
    shoe = Shoe.load(rig, args.model)
    motion = vmd.load(args.dance)
    off = rig.check_iks(motion)
    if off:
        raise SystemExit("the dance switches off %s: this layer solves them as on" % ", ".join(off))
    _, rep, _ = measure_report(rig, shoe, motion, args.floor_y)
    report = {"input": rep, "floor_y": args.floor_y, "heel_pitch_deg": HEEL_PITCH_DEG, "seconds": None}
    if not args.measure_only:
        raise SystemExit("the layer is not written yet: use --measure-only")
    report["seconds"] = round(time.time() - t0, 1)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    for tag, r in rep.items():
        print("%s contact %d/%d, penetration %d frames (deepest %s cm), roll in contact p50 %s p95 %s, touchdowns %s" % (
            tag, r["contact_frames"], r["frames"], r["penetration"]["frames"], r["penetration"]["deepest_cm"],
            r["roll_in_contact_deg"].get("p50"), r["roll_in_contact_deg"].get("p95"), r["touchdowns"]["first"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
