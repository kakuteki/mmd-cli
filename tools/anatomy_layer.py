"""Bake anatomical joints onto a dance: a hinge elbow, the twists on the twist bones, the trunk and the neck shared out
between their bones, the shoulder girdle's rhythm, and a soft range of motion, with the hands kept where they were.

    python tools/anatomy_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--key-frames TRACE.vmd]
                                  [--forearm-twist keep|handtw] [--upper-twist-share 1] [--tenodesis]
                                  [--no-split] [--no-girdle] [--no-rom] [--verbose]

Why (the audit and the research of 2026-10-10, stage3/audit/AUDIT.md and stage3/research/RESEARCH.md): the trace puts
its rotations where no body has them.  Its elbow bends to the side and upwards like a ball joint (75 % of the bent frames
more than 30 degrees off the elbow's own plane), the upper arm's roll hides in that bend and 腕捩 is never used, the neck
(首) never moves, the trunk turns on 上半身 alone, and the shoulder girdle (肩) does not follow the arm below 90 degrees of
elevation but rises 50 to 70 degrees above 120.  A few frames go beyond what a joint can do: the left shoulder drawn
back 72 degrees (3,882 - 3,899), the right one up to the ear (3,225 - 3,249), the left elbow bent back and out
(3,345 - 3,372, 5,007 - 5,044, 6,903 - 6,940).

The steps, in the research's order (5 章: first what does not change the pose, then the limits, then what is added):

1. Split without changing the pose (the world pose of the hands, the head and the chest stays; the report measures it).
   * Arm: the elbow becomes a hinge.  Its axis h is read from the model: perpendicular to the forearm (ひじ -> 手首) and to
     the elbow helper's local Z (ひじ補助, the model's own front-back axis of the elbow; +Z when the model has none), so
     that a positive turn about h bends the forearm to the front.  With the hand's wrist on the input's place, the
     elbow on the input's place and a pure hinge, the upper arm's roll is set; it goes on 腕捩 (--upper-twist-share of it,
     the rest stays on 腕 as a twist; 腕 keeps the swing from its rest direction).  The forearm's twist: by default
     手捩 keeps the input's key (fix_twist's guard of the cuff) and 手首 takes the rest; --forearm-twist handtw puts all
     of it on 手捩 and leaves 手首 a swing only.
   * Trunk: 上半身's rotation is split into a part that stays on 上半身 and a part moved onto 上半身2 (in front of what
     上半身2 already had, the breath).  Shares moved up: flexion 0.25, lateral bend 0.3, axial turn 0.4 (the research's
     A2: the lower thoracic spine takes most of the turn, the lumbar spine most of the bending).  The chest's world
     rotation is kept; its place moves a little (the pivot of 上半身2 is higher), the report says how much.
   * Neck: the part of 頭's rotation moved onto 首: turn 1/3, flexion 0.6, lateral bend 0.7 (C1-C2 take about 2/3 of the
     turn, the upper neck about 4 tenths of the extension, the side bend is spread over the levels; Ishii 2004,
     Zarate-Tejero 2023).  The head's world rotation is kept.
   A rotation of an upright segment is read as a swing of its up axis then a twist about Y; the swing's share is set by
   its direction (flexion about X, lateral bend about Z).
2. The shoulder girdle (肩) as a function of the arm's humerothoracic elevation HT (read on the input): Ludewig 2009's
   clavicle, elevation 0.05 deg/deg and retraction 0.06 (flexion) to 0.18 (abduction) deg/deg above HT 25, as a floor
   (the trace's girdle stays where it is higher: a shrug is the dance's), then soft limits: elevation and retraction,
   protraction 20 (the Japanese reference range) saturating to 25, depression 10 to 15.  In this model the girdle is the
   whole of 肩 (a visible slope of the shoulder), so the scapula's upward rotation (Braman 2009, 0.43 deg per degree of
   glenohumeral elevation) cannot be given its own bone; it is measured, not imitated.  The hand stays: the arm is solved
   again from the new root (two bones and a hinge).  Where the wrist is then out of reach, the girdle's change is backed
   off (the report counts the frames).
3. The range of motion, read from the geometry (never from the keys' X, Y, Z).  With the wrist's place and the hand's
   rotation fixed, the arm has one free turn: the elbow's place on the circle about the shoulder-wrist line (its
   swivel), and two readings of a bent elbow (bent to the front, or back past straight).  A dynamic program over the
   swivel (SWIVEL_STEP degrees) and the reading chooses, frame by frame, the cheapest path: the elbow's distance from
   where the split put it, soft penalties from the Japanese reference range to the research's cap (ARM_LIMITS: the
   humerus' rotation, pronation and supination, the elbow, the wrist) and steep ones beyond the cap, and the speed of
   the upper arm's roll and of the elbow's offset between frames.  So the excess is taken by the humerus' rotation
   against the forearm's twist (a straight arm), or by moving the elbow (a bent one), and only where it pays; the path
   is smoothed (SMOOTH_SIGMA frames) and stays exactly the split where nothing is beyond.  Where the arm is nearly
   straight the hinge plane is undefined, and the same program keeps the roll continuous.
   Not fixed, listed: an elbow bent beyond its cap (the wrist would have to move) and the neck and the trunk (beyond
   the research's caps on 0 to 0.1 % of the frames; fixing them would turn the face or the chest).  --key-frames: the
   trace's keys (左腕 / 右腕) where the shape changed are listed (the elbow moved, the girdle turned).
4. --tenodesis (off by default): where every finger of a hand holds still (RELAX_RUN frames, under RELAX_DEG a frame),
   the fingers follow the wrist like a relaxed hand (Su 2005, the end values joined by straight lines: per degree of
   wrist extension MP 0.30, PIP 0.43, DIP 0.16 degrees of flexion), about the stretch's mean, faded in and out.
5. Not touched: センター, 下半身, the legs and their IK, 肩P, the eyes, every other bone and every morph (byte for byte).

The report measures the input and the output: the world pose errors (hands, head, chest, eyes), the hands' distances
to the eyes and to the body, the girdle by HT bin against Ludewig and Braman, the arm's anatomical angles (beyond the
reference and beyond the cap), the elbow's plane, the twists' placement, the trunk's and the neck's shares, and the
listed key frames.
"""
import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

UNIT_CM = 8.0                   # one model unit is 8 cm (the analysis pack's README)
SIDES = (("左", 1.0), ("右", -1.0))
X_ = np.array([1.0, 0.0, 0.0])
U_ = np.array([0.0, 1.0, 0.0])
D_ = -U_
F_ = np.array([0.0, 0.0, -1.0])  # the model faces -Z
TRUNK_LO, TRUNK_UP, NECK, HEAD, PELVIS = "上半身", "上半身2", "首", "頭", "下半身"
ARM = ("肩P", "肩", "肩C", "腕", "腕捩", "ひじ", "手捩", "手首")
FINGERS = ("人指", "中指", "薬指", "小指")
JOINTS = (("１", "mp"), ("２", "pip"), ("３", "dip"))
TIPS = ("中指先", "中指３先", "中指３")
IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])

# ---- the numbers (sources: stage3/research/RESEARCH.md) -------------------------------------------------------
TRUNK_TO_UPPER = {"flex": 0.25, "lat": 0.3, "rot": 0.4}       # moved from 上半身 onto 上半身2 (5.1 A2)
HEAD_TO_NECK = {"flex": 0.6, "lat": 0.7, "rot": 1.0 / 3.0}    # moved from 頭 onto 首 (5.1 A3)
# (soft start = the Japanese reference range, cap = the research's proposal; where they were equal the cap is raised
# by 5 degrees to leave room for the saturation).  Degrees.  The humerus' rotation is by HT: (HT, start, cap).
ARM_LIMITS = {"external_rotation": ((0.0, 60.0, 110.0), (90.0, 90.0, 131.0), (180.0, 90.0, 131.0)),
              "internal_rotation": ((0.0, 80.0, 85.0), (90.0, 70.0, 81.0), (180.0, 70.0, 81.0)),
              "pronation": (90.0, 95.0), "supination": (90.0, 95.0),
              "elbow_flexion": (145.0, 152.5), "elbow_extension": (5.0, 18.0),
              "wrist_flexion": (90.0, 115.0), "wrist_extension": (70.0, 99.5),
              "wrist_radial": (25.0, 37.0), "wrist_ulnar": (55.0, 60.0)}
GIRDLE_LIMITS = {"elevation": (20.0, 25.0), "depression": (10.0, 15.0), "protraction": (20.0, 25.0),
                 "retraction": (20.0, 25.0)}
RHYTHM = {"start": 25.0, "elevation": 0.05, "retraction_flexion": 0.06, "retraction_abduction": 0.18}  # Ludewig 2009
TENODESIS = {"mp": 0.30, "pip": 0.43, "dip": 0.16}            # Su 2005, per degree of wrist extension
RELAX_DEG, RELAX_RUN, RELAX_FADE = 0.5, 10, 5

# ---- the arm's dynamic program --------------------------------------------------------------------------------
SWIVEL_STEP = 5.0               # degrees between the swivels tried
SIGMA_MOVE = 3.0                # degrees of the elbow's offset (seen from the shoulder) that cost 1
MOVE_CAP_DEG = 15.0             # beyond (about 5 cm of elbow), the offset costs (excess / MOVE_HARD_DEG)^2: an excess that
MOVE_HARD_DEG = 0.25            # would need the elbow moved further is left and listed
SIGMA_ROLL = 4.0                # degrees per frame of the upper arm's roll beyond the split's own that cost 1
SIGMA_OFFSET = 1.0              # degrees per frame of change of the elbow's offset that cost 1
HARD_DEG = 1.0                  # beyond a cap: (degrees / HARD_DEG)^2
FLEX_PREFERENCE = 0.02          # a tie goes to the elbow bent to the front
BENT = (15.0, 35.0)             # the elbow's bend over which the split's roll is trusted (a smoothstep)
PLANE_BLEND = (0.05, 0.1)       # degrees of bend: below, the roll is set by the swivel's plane (the hinge's own plane
                                # is undefined); above, the exact hinge (the wrist on its place)
REFINE_POINTS, REFINE_ROUNDS, REFINE_HALVINGS = 9, 2, 4   # the continuous search after the grid (see refine)
FOREARM_SHARE = 0.5             # --forearm-twist share: what 手捩 keeps, as tools/fix_twist.py (at most 45 degrees)
BACKOFF_PAD = 4                 # frames: a backed-off girdle is eased in and out
KEY_ELBOW_CM, KEY_GIRDLE_DEG = 2.0, 8.0   # a trace key is listed where the elbow moved or the girdle turned more
GIRDLE_HAND_SLACK_CM = 3.0      # how far a hand may slide along a straight arm so that the girdle can come back


def default_params():
    return {"split": True, "girdle": True, "rom": True, "tenodesis": False, "forearm_twist": "share",
            "upper_twist_share": 1.0, "trunk_shares": dict(TRUNK_TO_UPPER), "neck_shares": dict(HEAD_TO_NECK),
            "arm_limits": {k: v for k, v in ARM_LIMITS.items()}, "girdle_limits": dict(GIRDLE_LIMITS),
            "rhythm_gain": 1.0, "girdle_hand_slack_cm": GIRDLE_HAND_SLACK_CM}


# ---- vectors and quaternions (x, y, z, w), Hamilton, over arrays ----------------------------------------------

def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def dot(a, b):
    return np.sum(a * b, axis=-1)


def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def qrot(q, v):
    v = np.asarray(v, dtype=float)
    shape = np.broadcast_shapes(q.shape[:-1], v.shape[:-1])
    q, v = np.broadcast_to(q, shape + (4,)), np.broadcast_to(v, shape + (3,))
    u, w = q[..., :3], q[..., 3:4]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def qnorm(q):
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def aa(axis, angle):
    """the rotation by `angle` (radians) about the unit `axis`"""
    axis, angle = np.asarray(axis, dtype=float), np.asarray(angle, dtype=float)
    h = angle[..., None] / 2.0
    return np.concatenate([np.broadcast_to(axis, h.shape[:-1] + (3,)) * np.sin(h), np.cos(h)], axis=-1)


def wrap(a):
    """radians to -pi .. pi"""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def twist(q, axis):
    """the angle (radians, -pi .. pi) of the twist of q about the unit axis (q = swing * twist)"""
    return wrap(2.0 * np.arctan2(dot(q[..., :3], axis), q[..., 3]))


def qangle(q):
    return 2.0 * np.arccos(np.clip(np.abs(q[..., 3]), 0.0, 1.0))


def slerp(a, b, t):
    t = np.asarray(t, dtype=float)
    d = dot(a, b)
    b = np.where(d[..., None] < 0.0, -b, b)
    d = np.abs(d)
    theta = np.arccos(np.clip(d, -1.0, 1.0))
    s = np.sin(theta)
    near = s < 1e-6
    wa = np.where(near, 1.0 - t, np.sin((1.0 - t) * theta) / np.where(near, 1.0, s))
    wb = np.where(near, t, np.sin(t * theta) / np.where(near, 1.0, s))
    return qnorm(wa[..., None] * a + wb[..., None] * b)


def qpow(q, k):
    """q to the power k: the same axis, k times the angle (the short way)"""
    return slerp(np.broadcast_to(IDENTITY, q.shape), q, k)


def mat_to_quat(M):
    """rotation matrices [..., 3, 3] (columns = the images of the axes) -> quaternions"""
    m00, m11, m22 = M[..., 0, 0], M[..., 1, 1], M[..., 2, 2]
    w = np.sqrt(np.maximum(0.0, 1.0 + m00 + m11 + m22)) / 2.0
    x = np.sqrt(np.maximum(0.0, 1.0 + m00 - m11 - m22)) / 2.0
    y = np.sqrt(np.maximum(0.0, 1.0 - m00 + m11 - m22)) / 2.0
    z = np.sqrt(np.maximum(0.0, 1.0 - m00 - m11 + m22)) / 2.0
    x = np.copysign(x, M[..., 2, 1] - M[..., 1, 2])
    y = np.copysign(y, M[..., 0, 2] - M[..., 2, 0])
    z = np.copysign(z, M[..., 1, 0] - M[..., 0, 1])
    return qnorm(np.stack([x, y, z, w], axis=-1))


def frame(a, b):
    """the orthonormal frame [a, b', a x b'] (columns), b' = b made perpendicular to a"""
    a = np.broadcast_to(a, np.broadcast_shapes(np.shape(a), np.shape(b)))
    b = unit(b - dot(b, a)[..., None] * a)
    return np.stack([a, b, np.cross(a, b)], axis=-1)


def align(a1, b1, a2, b2):
    """the rotation taking a1 to a2 and the plane (a1, b1) to the plane (a2, b2), b1 to b2's side"""
    return mat_to_quat(frame(a2, b2) @ np.swapaxes(frame(a1, b1), -1, -2))


def arc(a, b):
    """the shortest rotation taking the unit vector a to the unit vector b"""
    a, b = np.broadcast_arrays(a, b)
    c = np.cross(a, b)
    w = 1.0 + dot(a, b)
    q = np.concatenate([c, w[..., None]], axis=-1)
    back = w < 1e-9
    if np.any(back):
        other = np.where(np.abs(a[..., :1]) < 0.9, X_, U_)
        q = np.where(back[..., None], np.concatenate([unit(np.cross(a, other)), np.zeros(w.shape + (1,))], -1), q)
    return qnorm(q)


def continuous(q):
    """the same rotations with the signs chosen so that one frame follows the last (axis 0 is time)"""
    q = q.copy()
    for t in range(1, len(q)):
        flip = dot(q[t], q[t - 1]) < 0.0
        q[t] = np.where(flip[..., None], -q[t], q[t])
    return q


def smoothstep(x, lo, hi):
    s = np.clip((np.asarray(x, dtype=float) - lo) / (hi - lo), 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def soft_limit(x, start, cap):
    """x where it is below `start`; above, a saturation towards `cap` that meets x with the same value and slope at the
    start and never reaches the cap (the Soft IK form, Nicholas)"""
    x = np.asarray(x, dtype=float)
    w = cap - start
    return np.where(x <= start, x, start + w * (1.0 - np.exp(-(np.maximum(x, start) - start) / w)))


def soft_band(x, low, high):
    """both sides: low = (start, cap) below zero as positive numbers, high = (start, cap) above"""
    return np.where(x >= 0.0, soft_limit(x, *high), -soft_limit(-x, *low))


def penalty(x, start, cap):
    """the arm's cost of an angle x above `start`: (share of the band)^2 inside it, steep beyond the cap"""
    e = np.maximum(x - start, 0.0) / (cap - start)
    over = np.maximum(x - cap, 0.0)
    return np.minimum(e, 1.0) ** 2 + 2.0 * np.maximum(e - 1.0, 0.0) + (over / HARD_DEG) ** 2


def gaussian(x, sigma):
    """x smoothed along axis 0 (the ends held)"""
    if sigma <= 0 or len(x) < 2:
        return x.copy()
    r = int(math.ceil(4 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.concatenate([np.repeat(x[:1], r, 0), x, np.repeat(x[-1:], r, 0)])
    return np.convolve(pad, k, mode="valid")


def runs(mask):
    """(start, end inclusive) of the runs of True"""
    m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]]).astype(int)
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0].tolist(), (np.where(d == -1)[0] - 1).tolist()))


def _r(x, n=2):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def stats(x):
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return {"max": None, "p95": None, "p50": None, "min": None}
    return {"max": _r(x.max()), "p95": _r(np.percentile(x, 95)), "p50": _r(np.median(x)), "min": _r(x.min())}


# ---- the model -------------------------------------------------------------------------------------------------

@dataclass
class Side:
    name: str
    sx: float
    d_sh: np.ndarray            # 肩 -> 腕 at rest
    d_u: np.ndarray             # 腕 -> ひじ
    d_f: np.ndarray             # ひじ -> 手首
    d_h: np.ndarray             # 手首 -> 中指１
    L_u: float
    L_f: float
    h: np.ndarray               # the elbow's hinge axis (a positive turn bends the forearm to the front m)
    m: np.ndarray               # the front of the forearm, perpendicular to it
    n: np.ndarray               # the palm's normal (palm side)
    r: np.ndarray               # the thumb's side of the hand, perpendicular to d_h and n
    rho: float                  # how far the hinge can straighten (cos of the smallest bend)
    phi: float                  # the hinge angle of the straightest arm
    ext_sign: float
    psign: float
    Aq: np.ndarray              # the hanging arm's rest turn: D_ -> d_u
    helper_z: np.ndarray        # the elbow helper's local Z as read (the source of m)
    fingers: dict               # finger name -> [(bone, joint, rest direction)]


def load_model(path):
    return pmd.load(path) if path.lower().endswith(".pmd") else pmx.load(path)


def rest_sides(model):
    by = {}
    for b in model.bones:
        by.setdefault(b.name, b)

    def P(n):
        return np.array(by[n].position, dtype=float)
    out = {}
    for s, sx in SIDES:
        need = [s + n for n in ("肩", "腕", "腕捩", "ひじ", "手捩", "手首", "中指１", "人指１", "小指１")]
        missing = [n for n in need if n not in by]
        if missing:
            raise ValueError("the model has no %s: the layer needs the arm from 肩 to the fingers" % ", ".join(missing))
        d_sh, d_u, d_f = unit(P(s + "腕") - P(s + "肩")), unit(P(s + "ひじ") - P(s + "腕")), unit(P(s + "手首") - P(s + "ひじ"))
        d_h = unit(P(s + "中指１") - P(s + "手首"))
        helper = by.get(s + "ひじ補助")
        z = np.array(helper.local_axes["z"], dtype=float) if helper is not None and helper.local_axes else np.array([0.0, 0.0, 1.0])
        z = unit(z)
        m = -unit(z - dot(z, d_f) * d_f)              # the local Z points back; the front is its opposite
        h = unit(np.cross(d_f, m))
        e3 = h
        alpha, gamma = float(d_u @ d_f), float(d_u @ m)
        rho, phi = math.hypot(alpha, gamma), math.atan2(gamma, alpha)
        rr = P(s + "人指１") - P(s + "小指１")
        n = unit(np.cross(d_h, rr)) * (-sx)
        n = unit(n - dot(n, d_h) * d_h)
        r_hat = unit(rr - dot(rr, d_h) * d_h)
        r_hat = unit(r_hat - dot(r_hat, n) * n)
        L = sx * X_
        fingers = {}
        for fn in FINGERS:
            chain = []
            for num, joint in JOINTS:
                b = s + fn + num
                nxt = [s + fn + "２", s + fn + "３", None][int("１２３".index(num))]
                if b not in by:
                    break
                if nxt is not None and nxt in by:
                    d = unit(P(nxt) - P(b))
                else:
                    tip = next((s + fn + t for t in ("先", "３先") if s + fn + t in by), None)
                    d = unit(P(tip) - P(b)) if tip else (chain[-1][2] if chain else d_h)
                chain.append((b, joint, d))
            if chain:
                fingers[fn] = chain
        out[s] = Side(s, sx, d_sh, d_u, d_f, d_h, float(np.linalg.norm(P(s + "ひじ") - P(s + "腕"))),
                      float(np.linalg.norm(P(s + "手首") - P(s + "ひじ"))), h, m, n, r_hat, rho, phi,
                      float(np.sign(np.cross(D_, F_) @ L)), float(np.sign(np.cross(d_f, r_hat) @ n)),
                      arc(D_, d_u), z, fingers)
        del e3
    return out


# ---- the input's world ------------------------------------------------------------------------------------------

def chain_names(model, sides):
    by = {b.name for b in model.bones}
    names = [n for n in ("腰", PELVIS, TRUNK_LO, TRUNK_UP, NECK, HEAD, "両目", "左目", "右目", "頭先") if n in by]
    for s, _ in SIDES:
        names += [s + n for n in ARM if s + n in by]
        for fn, chain in sides[s].fingers.items():
            names += [b for b, _, _ in chain]
        names += [s + t for t in TIPS if s + t in by]
    return names


class World:
    """the bones' world positions and rotations, every frame, with the model's parents and rest positions"""

    def __init__(self, model, motion, names, F, log=None):
        index = {}
        for b in model.bones:
            index.setdefault(b.name, b.index)
        bones = model.bones
        full = list(names)
        for n in names:                                  # the parents too (for the locals)
            p = bones[index[n]].parent
            if p is not None and bones[p].name not in full:
                full.append(bones[p].name)
        pose = fk.Pose(model, motion, full)
        idx = [i for _, i in pose.targets]
        self.names = full
        self.col = {n: j for j, n in enumerate(full)}
        self.pos = np.zeros((F, len(full), 3))
        self.rot = np.zeros((F, len(full), 4))
        t0 = time.time()
        for f in range(F):
            w = pose.world(f)
            for j, i in enumerate(idx):
                p, r = w[i]
                self.pos[f, j] = p
                self.rot[f, j] = r
            if log and f and f % 2000 == 0:
                log("fk %d / %d frames (%.0f s)" % (f, F, time.time() - t0))
        self.rest = {n: np.array(bones[index[n]].position, dtype=float) for n in full}
        self.parent = {n: (bones[bones[index[n]].parent].name if bones[index[n]].parent is not None else None) for n in full}

    def p(self, n):
        return self.pos[:, self.col[n]]

    def q(self, n):
        return self.rot[:, self.col[n]]

    def local(self, n):
        """(rotation relative to the parent, the key's own translation): conj(W_parent) W and what is left of the
        offset once the rest offset is taken away"""
        par = self.parent[n]
        if par is None or par not in self.col:
            return self.q(n).copy(), np.zeros_like(self.p(n))
        Wp, pp = self.q(par), self.p(par)
        loc = qmul(qconj(Wp), self.q(n))
        kp = qrot(qconj(Wp), self.p(n) - pp) - (self.rest[n] - self.rest[par])
        return loc, kp


def run_chain(world, order, local, keypos, base):
    """forward kinematics of the bones `order` (parents first) with the locals given; bones outside it are read from
    `base` (name -> (pos, rot)) or the input's world"""
    out = dict(base)
    for n in order:
        par = world.parent[n]
        if par in out:
            pp, Wp = out[par]
        else:
            pp, Wp = world.p(par), world.q(par)
        offset = qrot(Wp, world.rest[n] - world.rest[par] + keypos[n])
        out[n] = (pp + offset, qnorm(qmul(Wp, local[n])))
    return out


# ---- step 1: the trunk and the neck --------------------------------------------------------------------------

def upright_part(q, shares):
    """the part of an upright segment's rotation q given by the shares: the swing of its up axis (flexion about X,
    lateral bend about Z, the share by the swing's direction) and the twist about Y"""
    tw = twist(q, U_)
    T = aa(U_, tw)
    S = qmul(q, qconj(T))
    s_ang = qangle(S)
    s_ax = unit(np.where(S[..., 3:4] < 0, -S[..., :3], S[..., :3]))
    share = shares["flex"] * s_ax[..., 0] ** 2 + shares["lat"] * s_ax[..., 2] ** 2 + \
        0.5 * (shares["flex"] + shares["lat"]) * s_ax[..., 1] ** 2
    return qmul(aa(s_ax, share * s_ang), aa(U_, shares["rot"] * tw))


def split_axial(world, local, params):
    """(new locals of 上半身, 上半身2, 首, 頭) with the chest's and the head's world rotation kept"""
    out = {}
    lo, up = local[TRUNK_LO], local[TRUNK_UP]
    # the trunk's turn is read against the pelvis (下半身, 上半身's sibling under 腰): a trace may turn both by half a
    # turn on 腰's frame, and only the difference is the spine's
    pelvis = local[PELVIS] if PELVIS in local and world.parent.get(PELVIS) == world.parent.get(TRUNK_LO) else None
    rel = qmul(qconj(pelvis), lo) if pelvis is not None else lo
    keep = {k: 1.0 - v for k, v in params["trunk_shares"].items()}
    P1 = upright_part(rel, keep)                        # what stays on 上半身
    E = qmul(qconj(P1), rel)                            # what moves onto 上半身2
    P1 = qmul(pelvis, P1) if pelvis is not None else P1
    out[TRUNK_LO], out[TRUNK_UP] = qnorm(P1), qnorm(qmul(E, up))
    if NECK in local and HEAD in local:
        P = upright_part(local[HEAD], params["neck_shares"])
        out[NECK] = qnorm(qmul(local[NECK], P))
        out[HEAD] = qnorm(qmul(qconj(P), local[HEAD]))
    return out


def upright_angles(q):
    """flexion, lateral bend, axial turn (degrees) of an upright segment's rotation (the audit's reading)"""
    rot = twist(q, U_)
    up = qrot(q, U_)
    flex = np.degrees(np.arctan2(dot(up, F_), dot(up, U_)))
    lat = np.degrees(np.arctan2(dot(up, X_), dot(up, U_)))
    return flex, lat, np.degrees(rot) * np.sign(np.cross(U_, F_) @ X_)


# ---- step 2: the shoulder girdle ------------------------------------------------------------------------------

def girdle_angles(S, v):
    """elevation and protraction (degrees, against the rest) of the 肩 bone's direction v in the chest's frame"""
    e = np.degrees(np.arcsin(np.clip(v @ U_, -1, 1)) - math.asin(float(S.d_sh @ U_)))
    p = np.degrees(np.arcsin(np.clip(v @ F_, -1, 1)) - math.asin(float(S.d_sh @ F_)))
    return e, p


def girdle_direction(S, e, p):
    """the 肩 bone's direction with elevation e and protraction p (degrees against the rest)"""
    y = np.sin(np.radians(e) + math.asin(float(S.d_sh @ U_)))
    z = np.sin(np.radians(p) + math.asin(float(S.d_sh @ F_)))
    lat = np.sqrt(np.maximum(1.0 - y * y - z * z, 1e-9))
    return unit(np.stack([S.sx * lat, y, -z], axis=-1))


def humerothoracic(S, T, shoulder, elbow):
    """(elevation from hanging, degrees; share of abduction 0..1) of the upper arm in the chest's frame"""
    u = qrot(qconj(T), unit(elbow - shoulder))
    ht = np.degrees(np.arccos(np.clip(u @ D_, -1, 1)))
    lat, fwd = np.abs(u @ (S.sx * X_)), np.abs(u @ F_)
    ab = np.where(lat + fwd > 1e-6, lat / np.maximum(np.hypot(lat, fwd), 1e-9), 0.5)
    return ht, ab


def girdle_targets(S, e_in, p_in, ht, ab, params):
    g = params["rhythm_gain"]
    over = np.maximum(ht - RHYTHM["start"], 0.0)
    floor_e = g * RHYTHM["elevation"] * over
    floor_r = g * (RHYTHM["retraction_flexion"] + (RHYTHM["retraction_abduction"] - RHYTHM["retraction_flexion"]) * ab) * over
    e1 = np.maximum(e_in, floor_e)
    p1 = np.minimum(p_in, -floor_r)
    lim = params["girdle_limits"]

    def capped(e, p):
        return soft_band(e, lim["depression"], lim["elevation"]), soft_band(p, lim["retraction"], lim["protraction"])
    return capped(e_in, p_in), capped(e1, p1)


# ---- step 3: the arm --------------------------------------------------------------------------------------------

@dataclass
class ArmInput:
    ps: np.ndarray              # the shoulder joint (腕), after the girdle
    pw: np.ndarray              # the wrist (手首), the input's
    pe0: np.ndarray             # the elbow (ひじ), the input's
    T: np.ndarray               # the chest's world rotation
    H: np.ndarray               # the hand's world rotation, the input's
    fe: np.ndarray              # the forearm (elbow -> wrist) in the elbow's frame, unit: 手捩's key may turn it a
    Lf: np.ndarray              # little off d_f (the trace's keys are up to 3 degrees off the fixed axis); its length


def forearm_vector(S, world, s, local, keypos, keep):
    """(unit vector, length) of the elbow -> wrist offset in the elbow's frame, every frame: through 手捩's key when
    it is kept, else straight along d_f"""
    tw, wr, el = s + "手捩", s + "手首", s + "ひじ"
    v1 = world.rest[tw] - world.rest[el] + keypos[tw]
    v2 = world.rest[wr] - world.rest[tw] + keypos[wr]
    if keep:
        v = v1 + qrot(local[tw], v2)
    else:
        v = np.broadcast_to(S.L_f * S.d_f, v1.shape)
    n = np.linalg.norm(v, axis=-1)
    return v / n[:, None], n


def hinge_reach(S, fe, Lf):
    """(longest, shortest) shoulder-wrist distance a hinge arm reaches with the forearm `fe`, every frame"""
    c3 = dot(fe, S.h)
    pn = np.sqrt(np.maximum(1.0 - c3 ** 2, 0.0))
    ph = (fe - c3[..., None] * S.h) / np.maximum(pn, 1e-12)[..., None]
    k0 = c3 * float(S.d_u @ S.h)
    rho = pn * np.hypot(dot(ph, S.d_u), dot(np.cross(S.h, ph), S.d_u))
    longest = np.sqrt(S.L_u ** 2 + Lf ** 2 + 2 * S.L_u * Lf * (k0 + rho))
    shortest = np.sqrt(np.maximum(S.L_u ** 2 + Lf ** 2 + 2 * S.L_u * Lf * math.cos(math.radians(178.0)), 0.0))
    return longest * (1.0 - 1e-6), shortest


def swivel_base(ps, pw, pe0):
    """(the unit shoulder-wrist axis, its length, the unit direction from the axis to the input's elbow; a frame where
    the elbow lies on the axis takes the last good one)"""
    a = unit(pw - ps)
    D = np.linalg.norm(pw - ps, axis=-1)
    v = pe0 - ps
    perp = v - dot(v, a)[..., None] * a
    norm = np.linalg.norm(perp, axis=-1)
    q0 = perp / np.maximum(norm, 1e-12)[..., None]
    last = None
    for t in range(len(q0)):
        if norm[t] < 1e-7:
            if last is None:
                cand = np.cross(a[t], F_)
                if np.linalg.norm(cand) < 1e-6:
                    cand = np.cross(a[t], X_)
                q0[t] = unit(cand)
            else:
                q0[t] = unit(last - (last @ a[t]) * a[t])
        last = q0[t]
    return a, D, q0


def arm_states(S, A, a, D, q0, delta, branch, sl=slice(None)):
    """the arm for each frame of `sl` and each swivel delta (radians, [F, K]) and reading branch (+1 bent to the
    front, -1 bent back; [F, K]): the elbow on its circle, the hinge's angle, the upper arm's and the forearm's world
    rotations and the anatomical angles"""
    a, D, q0 = a[sl][:, None], D[sl][:, None], q0[sl][:, None]
    ps, pw, T, H = A.ps[sl][:, None], A.pw[sl][:, None], A.T[sl][:, None], A.H[sl][:, None]
    fe, Lf = A.fe[sl][:, None], A.Lf[sl][:, None]
    cosA = (S.L_u ** 2 + D ** 2 - Lf ** 2) / (2.0 * S.L_u * D)
    reach = np.abs(cosA[..., 0]) <= 1.0 + 1e-9
    cosA = np.clip(cosA, -1.0, 1.0)
    sinA = np.sqrt(1.0 - cosA ** 2)
    q = q0 * np.cos(delta)[..., None] + np.cross(a, q0) * np.sin(delta)[..., None]
    pe = ps + S.L_u * (cosA[..., None] * a + sinA[..., None] * q)
    u = unit(pe - ps)
    f = unit(pw - pe)
    cosb = np.clip(dot(u, f), -1.0, 1.0)
    beta = np.arccos(cosb)
    # the hinge: g(theta) = the forearm turned by theta about h; its angle to d_u must be the bend beta
    c3 = dot(fe, S.h)
    pn = np.sqrt(np.maximum(1.0 - c3 ** 2, 0.0))
    ph = (fe - c3[..., None] * S.h) / np.maximum(pn, 1e-12)[..., None]
    ph2 = np.cross(np.broadcast_to(S.h, ph.shape), ph)
    k0 = c3 * float(S.d_u @ S.h)
    gam, sig = dot(ph, S.d_u), dot(ph2, S.d_u)
    rho = pn * np.hypot(gam, sig)
    phi = np.arctan2(sig, gam)
    c = (cosb - k0) / rho
    solvable = c <= 1.0
    dlt = np.arccos(np.clip(c, -1.0, 1.0))
    theta = phi + branch * dlt
    g = c3[..., None] * S.h + pn[..., None] * (np.cos(theta)[..., None] * ph + np.sin(theta)[..., None] * ph2)
    R_exact = align(S.d_u, g, u, f)
    n_plane = unit(np.cross(q, a))
    R_plane = align(S.d_u, branch[..., None] * S.h, u, n_plane)
    w = smoothstep(np.degrees(beta), *PLANE_BLEND)
    R_up = slerp(R_plane, R_exact, w)
    R_el = qmul(R_up, aa(S.h, theta))
    wrist = pe + Lf[..., None] * qrot(R_el, fe)
    out = {"pe": pe, "u": u, "beta": beta, "theta": theta, "R_up": R_up, "R_el": R_el, "reach": reach,
           "solvable": solvable, "wrist_err": np.linalg.norm(wrist - pw, axis=-1)}
    out.update(arm_angles(S, T, R_up, R_el, H, u))
    out["elbow"] = branch * np.degrees(beta)
    return out


def arm_angles(S, T, R_up, R_el, H, u):
    """the anatomical angles (degrees) of an arm: the humerus' elevation (HT) and rotation (+ external), pronation (+),
    the wrist's flexion (+ palmar) and radial deviation (+)"""
    uc = qrot(qconj(T), u)
    ht = np.degrees(np.arccos(np.clip(uc @ D_, -1, 1)))
    hum = qmul(qmul(qconj(T), R_up), np.broadcast_to(S.Aq, R_up.shape))
    ext = np.degrees(twist(hum, D_)) * S.ext_sign
    qf = qmul(qconj(R_el), np.broadcast_to(H, R_el.shape))
    tf_ang = twist(qf, S.d_f)
    pron = np.degrees(tf_ang) * S.psign
    s_loc = qmul(qconj(aa(S.d_f, tf_ang)), qf)
    ch = qrot(s_loc, S.d_h)
    mh = unit(S.n - (S.n @ S.d_h) * S.d_h)
    k = np.cross(S.d_h, mh)
    wflex = np.degrees(np.arctan2(ch @ mh, ch @ S.d_h))
    wside = np.degrees(np.arcsin(np.clip(ch @ k, -1, 1))) * np.sign(k @ S.r)
    return {"ht": ht, "ext": ext, "pron": pron, "wflex": wflex, "wradial": wside}


def limit_band(table, ht):
    hs, st, cp = zip(*table)
    return np.interp(ht, hs, st), np.interp(ht, hs, cp)


ARM_ANGLES = ("external_rotation", "internal_rotation", "pronation", "supination", "elbow_flexion",
              "elbow_extension", "wrist_flexion", "wrist_extension", "wrist_radial", "wrist_ulnar")


def arm_pairs(st, lim):
    """(name, angle, soft start, cap) of every limited arm angle, each as a positive excursion"""
    es, ec = limit_band(lim["external_rotation"], st["ht"])
    is_, ic = limit_band(lim["internal_rotation"], st["ht"])
    return [("external_rotation", st["ext"], es, ec), ("internal_rotation", -st["ext"], is_, ic),
            ("pronation", st["pron"], *lim["pronation"]), ("supination", -st["pron"], *lim["supination"]),
            ("elbow_flexion", st["elbow"], *lim["elbow_flexion"]),
            ("elbow_extension", -st["elbow"], *lim["elbow_extension"]),
            ("wrist_flexion", st["wflex"], *lim["wrist_flexion"]),
            ("wrist_extension", -st["wflex"], *lim["wrist_extension"]),
            ("wrist_radial", st["wradial"], *lim["wrist_radial"]), ("wrist_ulnar", -st["wradial"], *lim["wrist_ulnar"])]


def arm_cost(st, lim, move_deg):
    """the unary cost of arm states and how far beyond the caps they are (degrees, summed)"""
    cost = (move_deg / SIGMA_MOVE) ** 2 + ((np.maximum(move_deg - MOVE_CAP_DEG, 0.0)) / MOVE_HARD_DEG) ** 2
    beyond = np.zeros_like(cost)
    beyond_ref = np.zeros_like(cost)
    for _, x, s, c in arm_pairs(st, lim):
        cost = cost + penalty(x, s, c)
        beyond = beyond + np.maximum(x - c, 0.0)
        beyond_ref = beyond_ref + np.maximum(x - s, 0.0)
    return cost, beyond, beyond_ref


def roll_between(R_prev, R_cur, axis):
    """[i, j]: the twist (radians) about axis[j] of R_cur[j] R_prev[i]^-1 (the roll of the upper arm from one frame's
    state i to the next frame's state j)"""
    vr, wr = R_prev[:, :3], R_prev[:, 3]
    vq, wq = R_cur[:, :3], R_cur[:, 3]
    W = np.outer(wr, wq) + vr @ vq.T
    A = dot(vq, axis)
    Ssum = np.outer(wr, A) - (vr @ axis.T) * wq[None, :] - vr @ np.cross(axis, vq).T
    return wrap(2.0 * np.arctan2(Ssum, W))


def roll_pair(R_a, R_b, axis):
    """the twist (radians) about `axis` of R_b R_a^-1, elementwise"""
    p = qmul(R_b, qconj(R_a))
    return wrap(2.0 * np.arctan2(dot(p[..., :3], axis), p[..., 3]))


def refine(S, A, a, D, q0, br, dl, rho, unary_of):
    """the dynamic program's swivel (on a grid of SWIVEL_STEP degrees) made continuous: rounds of a finer search about
    each frame's swivel against the same costs (the frame's own, and the steps to the frames on either side), odd and
    even frames in turn, the search's width halved every REFINE_ROUNDS rounds"""
    F = len(dl)
    if F < 2:
        return dl
    width = SWIVEL_STEP
    offsets = np.radians(np.linspace(-1.0, 1.0, REFINE_POINTS))
    for _ in range(REFINE_HALVINGS):
        for _ in range(REFINE_ROUNDS):
            for parity in (0, 1):
                cur = arm_states(S, A, a, D, q0, dl[:, None], br[:, None])
                R, u = cur["R_up"][:, 0], cur["u"][:, 0]
                off = (cur["pe"][:, 0] - arm_states(S, A, a, D, q0, np.zeros((F, 1)), br[:, None])["pe"][:, 0])
                idx = np.arange(parity, F, 2)
                cand = dl[idx][:, None] + width * offsets[None, :]
                bb = np.broadcast_to(br[idx][:, None], cand.shape)
                st = arm_states(S, A, a, D, q0, cand, bb, idx)
                cost, coff = unary_of(st, idx, bb)
                prev, nxt = idx - 1, idx + 1
                has_p, has_n = prev >= 0, nxt < F
                pi, ni = np.clip(prev, 0, F - 1), np.clip(nxt, 0, F - 1)
                r_in = roll_pair(R[pi][:, None], st["R_up"], st["u"])
                r_out = roll_pair(st["R_up"], R[ni][:, None], u[ni][:, None])
                d_in = np.degrees(np.linalg.norm(coff - off[pi][:, None] / S.L_u, axis=-1))
                d_out = np.degrees(np.linalg.norm(off[ni][:, None] / S.L_u - coff, axis=-1))
                cost = cost + has_p[:, None] * ((np.degrees(wrap(r_in - rho[idx][:, None])) / SIGMA_ROLL) ** 2
                                                + (d_in / SIGMA_OFFSET) ** 2)
                cost = cost + has_n[:, None] * ((np.degrees(wrap(r_out - rho[ni][:, None])) / SIGMA_ROLL) ** 2
                                                + (d_out / SIGMA_OFFSET) ** 2)
                dl[idx] = wrap(cand[np.arange(len(idx)), np.argmin(cost, axis=1)])
        width /= 2.0
    return dl


def solve_arm(S, A, params, log=None):
    """the swivel and the reading per frame (see the module docstring, step 3) and the final arm"""
    F = len(A.ps)
    a, D, q0 = swivel_base(A.ps, A.pw, A.pe0)
    K2 = int(round(360.0 / SWIVEL_STEP))
    grid = np.radians((np.arange(K2) - K2 // 2) * SWIVEL_STEP)
    deltas = np.concatenate([grid, grid])
    branches = np.concatenate([np.ones(K2), -np.ones(K2)])
    K = len(deltas)
    zero = K2 // 2
    lim = params["arm_limits"]
    rom = params["rom"]
    # the split's own arm (no swivel), both readings: the reference
    ref = arm_states(S, A, a, D, q0, np.zeros((F, 2)), np.tile([1.0, -1.0], (F, 1)))
    ref_pe = ref["pe"][:, 0]

    def unary_of(st, idx, br):
        off = (st["pe"] - ref_pe[idx][:, None]) / S.L_u
        move = np.degrees(np.linalg.norm(off, axis=-1))
        if rom:
            cost, _, _ = arm_cost(st, lim, move)
        else:
            # step 1 alone: the elbow stays (it may turn on its circle only where the arm is nearly straight) and is
            # read bent to the front wherever it is clearly bent
            cost = (move / SIGMA_MOVE) ** 2 + 1e3 * np.maximum(-st["elbow"] - 0.5, 0.0) ** 2 * \
                (np.degrees(st["beta"]) > 10.0)
        return cost + FLEX_PREFERENCE * (br < 0), off

    R_all = np.zeros((F, K, 4))
    u_all = np.zeros((F, K, 3))
    off_all = np.zeros((F, K, 3))
    unary = np.zeros((F, K))
    chunk = 1024
    for c0 in range(0, F, chunk):
        idx = np.arange(c0, min(F, c0 + chunk))
        n = len(idx)
        bb = np.broadcast_to(branches, (n, K))
        st = arm_states(S, A, a, D, q0, np.broadcast_to(deltas, (n, K)), bb, idx)
        cost, off = unary_of(st, idx, bb)
        R_all[idx], u_all[idx], off_all[idx], unary[idx] = st["R_up"], st["u"], off, cost
    bent = smoothstep(np.degrees(ref["beta"][:, 0]), *BENT)
    rho_all = np.zeros(F)
    t0 = time.time()
    total = unary[0].copy()
    back = np.zeros((F, K), dtype=np.int16)
    for t in range(1, F):
        roll = roll_between(R_all[t - 1], R_all[t], u_all[t])
        rho = roll_between(R_all[t - 1][zero:zero + 1], R_all[t][zero:zero + 1], u_all[t][zero:zero + 1])[0, 0]
        rho *= min(bent[t], bent[t - 1])
        rho_all[t] = rho
        trans = (np.degrees(wrap(roll - rho)) / SIGMA_ROLL) ** 2
        doff = np.degrees(np.linalg.norm(off_all[t][None, :, :] - off_all[t - 1][:, None, :], axis=-1))
        trans += (doff / SIGMA_OFFSET) ** 2
        tot = total[:, None] + trans
        b = np.argmin(tot, axis=0)
        back[t] = b
        total = tot[b, np.arange(K)] + unary[t]
        if log and t % 2000 == 0:
            log("arm %s: %d / %d frames (%.0f s)" % (S.name, t, F, time.time() - t0))
    path = np.zeros(F, dtype=int)
    path[-1] = int(np.argmin(total))
    for t in range(F - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    br = branches[path]
    dl = deltas[path].copy()
    del R_all, u_all, off_all, unary
    dl = refine(S, A, a, D, q0, br, dl, rho_all, unary_of)
    final = arm_states(S, A, a, D, q0, dl[:, None], br[:, None])
    final = {k: (v[:, 0] if v.ndim >= 2 else v) for k, v in final.items()}
    # the input read the anatomical way: the split's arm, the reading with less beyond the reference range per frame
    ref_cost, ref_beyond, ref_ref = arm_cost(ref, lim, np.zeros((F, 2)))
    pick = np.argmin(ref_ref + 1e-3 * np.arange(2)[None, :], axis=1)
    reading_in = {k: v[np.arange(F), pick] for k, v in ref.items() if v.ndim >= 2 and v.shape[1] == 2}
    reading_in["beyond"] = ref_beyond[np.arange(F), pick]
    _, out_beyond, _ = arm_cost({k: final[k] for k in ("ht", "ext", "pron", "elbow", "wflex", "wradial")}, lim, np.zeros(F))
    final["beyond"] = out_beyond
    final["delta"] = dl
    final["branch"] = br
    final["elbow_split"] = ref["pe"][:, 0]
    final["unreachable"] = ~ref["reach"]
    return final, reading_in


def arm_locals(S, C, final, local_in, params):
    """the locals of 腕, 腕捩, ひじ, 手捩, 手首 for the arm `final` hung from 肩C's world rotation C"""
    Qu = qmul(qconj(C), final["R_up"])
    tau = np.unwrap(twist(Qu, S.d_u))
    k = params["upper_twist_share"]
    swing = qmul(Qu, qconj(aa(S.d_u, tau)))
    out = {"腕": qnorm(qmul(swing, aa(S.d_u, (1.0 - k) * tau))), "腕捩": aa(S.d_u, k * tau),
           "ひじ": aa(S.h, final["theta"])}
    R_el = final["R_el"]
    H = final["H"]
    mode = params["forearm_twist"]
    if mode == "keep":
        out["手捩"] = local_in["手捩"]
    else:
        tf = twist(qmul(qconj(R_el), H), S.d_f)        # the forearm's whole twist, -pi .. pi
        if mode == "handtw":
            out["手捩"] = aa(S.d_f, np.unwrap(tf))
        else:
            # fix_twist's rule on the new twist: 手捩 keeps FOREARM_SHARE of it up to a quarter turn, then less, down
            # to nothing at a half turn (no jump where the twist passes half a turn); 手首 takes the rest
            deg = np.degrees(np.abs(tf))
            kept = FOREARM_SHARE * np.where(deg <= 90.0, deg, 180.0 - deg)
            out["手捩"] = aa(S.d_f, np.sign(tf) * np.radians(kept))
    out["手首"] = qnorm(qmul(qconj(qmul(R_el, out["手捩"])), H))
    swing_deg = np.degrees(qangle(swing))
    rep = {"armtw_twist_deg": stats(np.abs(np.degrees(wrap(k * tau)))),
           "arm_twist_deg": stats(np.abs(np.degrees(wrap((1.0 - k) * tau)))),
           "armtw_frames_over_90": int((np.abs(np.degrees(wrap(k * tau))) > 90.0).sum()),
           "armtw_frames_over_135": int((np.abs(np.degrees(wrap(k * tau))) > 135.0).sum()),
           "handtw_twist_deg": stats(np.abs(np.degrees(twist(out["手捩"], S.d_f)))),
           "wrist_twist_deg": stats(np.abs(np.degrees(twist(out["手首"], S.d_f)))),
           "arm_swing_max_deg": _r(swing_deg.max())}
    return out, rep


# ---- step 4: the relaxed hand ---------------------------------------------------------------------------------

def tenodesis(S, local, wflex):
    """new locals of the fingers where every finger holds still, and the report"""
    bones = [(b, joint, d) for chain in S.fingers.values() for b, joint, d in chain]
    if not bones:
        return {}, {"frames": 0}
    F = len(wflex)
    still = np.ones(F, dtype=bool)
    still[0] = False
    for b, _, _ in bones:
        q = local[b]
        step = np.degrees(qangle(qmul(q[1:], qconj(q[:-1]))))
        still[1:] &= step < RELAX_DEG
    ext = -wflex                                     # wrist extension (dorsiflexion) positive
    add = np.zeros(F)
    weight = np.zeros(F)
    stretches = []
    for s0, s1 in runs(still):
        if s1 - s0 + 1 < RELAX_RUN:
            continue
        seg = slice(s0, s1 + 1)
        idx = np.arange(s0, s1 + 1)
        ramp = np.minimum(smoothstep(idx - s0, 0, RELAX_FADE), smoothstep(s1 - idx, 0, RELAX_FADE))
        add[seg] = ext[seg] - ext[seg].mean()
        weight[seg] = ramp
        stretches.append([int(s0), int(s1)])
    out = {}
    for b, joint, d in bones:
        axis = unit(np.cross(d, S.n))
        ang = np.radians(TENODESIS[joint] * add * weight)
        out[b] = qnorm(qmul(local[b], aa(axis, ang)))
    used = weight > 0.5
    mp = [b for b, j, _ in bones if j == "mp"]
    slope = None
    if used.sum() > 3 and mp:
        b = mp[0]
        d = [dd for bb, _, dd in bones if bb == b][0]
        mh = unit(S.n - (S.n @ d) * d)

        def flex(q):
            c = qrot(q, d)
            return np.degrees(np.arctan2(c @ mh, c @ d))
        dmp = flex(out[b]) - flex(local[b])
        x = (add * weight)[used]
        if np.ptp(x) > 1e-6:
            slope = float(np.polyfit(x, dmp[used], 1)[0])
    return out, {"frames": int(used.sum()), "stretches": len(stretches), "slope_mp": _r(slope, 3),
                 "max_change_deg": _r(float(np.abs(TENODESIS["pip"] * add * weight).max()) if F else 0.0)}


# ---- the layer ----------------------------------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict


def key_frames_of(motion):
    """side -> the sorted frames of the motion's 左腕 / 右腕 keys (the trace's poses)"""
    tracks = fk.tracks_of(motion)
    out = {}
    for s, _ in SIDES:
        keys = tracks.get(s + "腕") or []
        if keys:
            out[s] = sorted({k.frame for k in keys})
    return out


def layer(model, motion, params=None, key_frames=None, log=None):
    p = default_params()
    p.update(params or {})
    if p["forearm_twist"] not in ("share", "keep", "handtw"):
        raise ValueError("--forearm-twist is share, keep or handtw, not %r" % (p["forearm_twist"],))
    if not 0.0 <= p["upper_twist_share"] <= 1.0:
        raise ValueError("--upper-twist-share is 0 to 1, not %r" % (p["upper_twist_share"],))
    started = time.time()
    if not motion.bones:
        raise ValueError("the dance has no bone keys")
    F = fk.last_frame(motion) + 1
    sides = rest_sides(model)
    for n in (TRUNK_LO, TRUNK_UP):
        if n not in {b.name for b in model.bones}:
            raise ValueError("the model has no %s" % n)
    names = chain_names(model, sides)
    W = World(model, motion, names, F, log)
    local, keypos = {}, {}
    for n in W.names:
        if W.parent[n] is not None and W.parent[n] in W.col:
            local[n], keypos[n] = W.local(n)
    new = {}
    # step 1: trunk and neck
    if p["split"]:
        new.update(split_axial(W, local, p))
    axial = [n for n in (TRUNK_LO, TRUNK_UP, NECK, HEAD, "両目", "左目", "右目", "頭先") if n in W.col and n in local]
    loc = dict(local)
    loc.update(new)
    world = run_chain(W, axial, loc, keypos, {})
    T = world[TRUNK_UP][1]
    report = {"params": {k: v for k, v in p.items() if k not in ("arm_limits", "girdle_limits")},
              "limits": {"arm": p["arm_limits"], "girdle": p["girdle_limits"], "rhythm": RHYTHM},
              "frames": F, "rest": {}, "girdle": {}, "arm": {}, "twist": {}, "tenodesis": {}}
    arm_final = {}
    for s, sx in SIDES:
        S = sides[s]
        report["rest"][s] = {"hinge_axis": S.h.tolist(), "forearm": S.d_f.tolist(), "upper_arm": S.d_u.tolist(),
                             "front": S.m.tolist(), "helper_local_z": S.helper_z.tolist(),
                             "hinge_tilt_from_frontal_deg": _r(math.degrees(math.asin(abs(float(S.h @ F_)))), 3),
                             "rest_bend_deg": _r(math.degrees(math.acos(float(S.d_u @ S.d_f))), 3),
                             "straightest_bend_deg": _r(math.degrees(math.acos(min(1.0, S.rho))), 3)}
        chain = [s + n for n in ARM if s + n in W.col]
        # step 2: the girdle
        sh = s + "肩"
        v_in = qrot(qconj(W.q(TRUNK_UP)), qrot(W.q(sh), S.d_sh))
        e_in, p_in = girdle_angles(S, v_in)
        ht, ab = humerothoracic(S, W.q(TRUNK_UP), W.p(s + "腕"), W.p(s + "ひじ"))
        # g in 0..2 walks the girdle from the input (0) to the capped input (1) and on to the capped rhythm (2)
        g = np.zeros(F)
        A_cap = A_full = np.broadcast_to(IDENTITY, (F, 4))
        if p["girdle"]:
            (e_c, p_c), (e_t, p_t) = girdle_targets(S, e_in, p_in, ht, ab, p)
            A_cap = arc(v_in, girdle_direction(S, e_c, p_c))      # in the chest's frame
            A_full = arc(v_in, girdle_direction(S, e_t, p_t))
            g = np.full(F, 2.0)
        loc_s = dict(loc)
        pw = W.p(s + "手首")
        fe, Lf = forearm_vector(S, W, s, local, keypos, p["forearm_twist"] == "keep")
        Dmax, Dmin = hinge_reach(S, fe, Lf)

        def girdle_turn(gg):
            gg = np.broadcast_to(np.asarray(gg, dtype=float), (F,))
            first = qpow(A_cap, np.clip(gg, 0.0, 1.0))
            return np.where((gg > 1.0)[:, None], slerp(A_cap, A_full, np.clip(gg - 1.0, 0.0, 1.0)), first)

        def shoulder_world(gg):
            Ar = girdle_turn(gg)
            Wsh = qmul(qmul(T, qmul(Ar, qconj(T))), W.q(sh))
            Lsh = qmul(qconj(run_chain(W, [s + "肩P"], loc_s, keypos, world)[s + "肩P"][1]), Wsh)
            loc2 = dict(loc_s)
            loc2[sh] = qnorm(Lsh)
            wc = run_chain(W, chain[:chain.index(s + "腕") + 1], loc2, keypos, world)
            return loc2[sh], wc

        backoff = 0
        slack = p["girdle_hand_slack_cm"] / UNIT_CM

        def deficit(gg):
            _, wm = shoulder_world(gg)
            dm = np.linalg.norm(pw - wm[s + "腕"][0], axis=-1)
            return np.maximum(np.maximum(dm - Dmax, Dmin - dm), 0.0)
        if p["girdle"]:
            # the cap may make a straight arm's hand slide (within the slack); the rhythm may not make it slide at all
            d1 = deficit(np.ones(F))
            limit = np.where(d1 <= slack, d1 + 1e-7, slack)

            def feasible(gg):
                return deficit(gg) <= np.where(gg > 1.0, limit, slack)
            bad = ~feasible(g)
            if bad.any():
                lo_ = np.where(d1 <= slack, 1.0, 0.0)
                hi_ = np.where(d1 <= slack, 2.0, 1.0)
                ok0 = deficit(np.zeros(F)) <= slack
                for _ in range(22):
                    mid = 0.5 * (lo_ + hi_)
                    good = feasible(np.where(bad, mid, 2.0))
                    lo_ = np.where(bad & good, mid, lo_)
                    hi_ = np.where(bad & ~good, mid, hi_)
                g = np.where(bad, np.where(ok0 | (d1 <= slack), lo_, 0.0), 2.0)
                cut = 2.0 - g
                r = BACKOFF_PAD
                dil = np.array([cut[max(0, t - r):t + r + 1].max() for t in range(F)])
                k = np.hanning(2 * r + 3)[1:-1]
                k /= k.sum()
                cut2 = np.convolve(np.concatenate([np.repeat(dil[:1], r), dil, np.repeat(dil[-1:], r)]), k, "valid")
                g = np.clip(2.0 - np.maximum(cut2, cut), 0.0, 2.0)
                backoff = int((g < 0.999).sum())
                report.setdefault("girdle_rhythm_reduced_frames", {})[s] = int(((g > 0.999) & (g < 1.999)).sum())
        Lsh, wc = shoulder_world(g)
        if p["girdle"]:
            loc[sh] = Lsh
            new[sh] = Lsh
        v_out = qrot(qconj(T), qrot(wc[sh][1], S.d_sh))
        e_out, p_out = girdle_angles(S, v_out)
        C = wc[s + "肩C"][1]
        # where the moved chest or girdle leaves the wrist out of the hinge arm's reach (a straight arm), the hand slides
        # along the arm's line by what is missing (the girdle's cap within the slack, the rhythm not at all)
        ps_new = wc[s + "腕"][0]
        dvec = pw - ps_new
        dn = np.linalg.norm(dvec, axis=-1)
        reach = np.clip(dn, Dmin, Dmax)
        pw_t = ps_new + dvec * (reach / np.maximum(dn, 1e-12))[:, None]
        hand_moved = np.linalg.norm(pw_t - pw, axis=-1) * UNIT_CM
        A = ArmInput(ps_new, pw_t, W.p(s + "ひじ"), T, W.q(s + "手首"), fe, Lf)
        # step 3: the arm
        final, reading_in = solve_arm(S, A, p, log)
        final["H"] = A.H
        arm_loc, twist_rep = arm_locals(S, C, final, {"手捩": local[s + "手捩"]}, p)
        for n, q in arm_loc.items():
            if n == "手捩" and p["forearm_twist"] == "keep":
                continue
            new[s + n] = q
            loc[s + n] = q
        arm_final[s] = (final, reading_in, A)
        # the report of the girdle and the arm
        report["girdle"][s] = girdle_report(e_in, p_in, e_out, p_out, ht, ab, backoff, W, wc, s, T)
        report["girdle"][s]["hand_slid_cm"] = stats(hand_moved)
        report["girdle"][s]["hand_slid_frames"] = int((hand_moved > 0.05).sum())
        report["arm"][s] = arm_report(final, reading_in, A, S, p["arm_limits"])
        report["twist"][s] = twist_rep
        # step 4
        if p["tenodesis"]:
            fl, trep = tenodesis(S, local, final["wflex"])
            new.update(fl)
            loc.update(fl)
            report["tenodesis"][s] = trep
    out_motion = build(motion, W, new, keypos, F)
    steps = {}
    for n, q in new.items():
        if F < 2:
            break
        s_in = np.degrees(qangle(qmul(local[n][1:], qconj(local[n][:-1]))))
        s_out = np.degrees(qangle(qmul(q[1:], qconj(q[:-1]))))
        steps[n] = {"in_p99": _r(np.percentile(s_in, 99), 1), "in_max": _r(s_in.max(), 1),
                    "out_p99": _r(np.percentile(s_out, 99), 1), "out_max": _r(s_out.max(), 1),
                    "new_jumps": int(((s_out > 10.0) & (s_out > 3.0 * np.maximum(s_in, 1.0))).sum())}
    report["steps_deg_per_frame"] = steps
    report.update(measure(model, motion, out_motion, W, sides, arm_final, F, key_frames, new, p))
    report["seconds"] = _r(time.time() - started, 1)
    return Result(out_motion, report)


# ---- the output ---------------------------------------------------------------------------------------------------

def build(motion, W, new, keypos, F):
    """every key of a bone the layer does not move, as it was; a key on every frame for the others (the linear curve,
    the physics bytes of the input's key in force)"""
    tracks = fk.tracks_of(motion)
    labels = set()
    out = []
    curves = {}
    for name, rot in new.items():
        keys = tracks.get(name) or tracks.get(fk.vmd_name(name)) or []
        label = keys[0].name if keys else fk.vmd_name(name)
        raw = keys[0].raw_name if keys else None
        labels |= {name, fk.vmd_name(name), label}
        frames = [k.frame for k in keys]
        ki = 0
        held = keys[0].interpolation if keys else None
        rot = continuous(qnorm(rot))
        kp = keypos.get(name)
        for f in range(F):
            while ki < len(keys) and frames[ki] <= f:
                held = keys[ki].interpolation
                ki += 1
            if held not in curves:
                curves[held] = vmd.bone_interpolation(vmd.LINEAR_CURVE, keep=held)
            q = fk.stored(tuple(float(v) for v in rot[f]))
            pos = tuple(float(v) for v in kp[f]) if kp is not None else (0.0, 0.0, 0.0)
            if keys:
                pos = tuple(float(v) for v in fk.sample(keys, f, frames)[0])
            out.append(vmd.BoneKey(label, f, pos, q, curves[held], raw_name=raw))
    bones = [k for k in motion.bones if k.name not in labels] + out
    m = vmd.Motion(model_name=motion.model_name, bones=bones, morphs=list(motion.morphs), cameras=list(motion.cameras),
                   lights=list(motion.lights), shadows=list(motion.shadows), show_iks=list(motion.show_iks))
    m.labels = labels
    return m


# ---- the measures -------------------------------------------------------------------------------------------------

def girdle_report(e_in, p_in, e_out, p_out, ht, ab, backoff, W, wc, s, T):
    bins = []
    for lo, hi in ((0, 30), (30, 60), (60, 90), (90, 120), (120, 150), (150, 181)):
        mk = (ht >= lo) & (ht < hi)
        mid = 0.5 * (lo + hi)
        row = {"ht": [lo, hi], "frames": int(mk.sum()),
               "ludewig_clavicle_elevation": _r(RHYTHM["elevation"] * max(mid - RHYTHM["start"], 0.0), 1),
               "braman_upward_rotation": _r(0.43 * mid / 1.43, 1)}
        if mk.any():
            row.update({"elevation_in_p50": _r(np.median(e_in[mk]), 1), "elevation_out_p50": _r(np.median(e_out[mk]), 1),
                        "protraction_in_p50": _r(np.median(p_in[mk]), 1), "protraction_out_p50": _r(np.median(p_out[mk]), 1)})
        bins.append(row)
    return {"elevation_in": stats(e_in), "elevation_out": stats(e_out), "protraction_in": stats(p_in),
            "protraction_out": stats(p_out), "backoff_frames": backoff, "by_ht": bins,
            "changed_deg": stats(np.hypot(e_out - e_in, p_out - p_in))}


def left_beyond(mask, pairs, limit=80):
    """the stretches still beyond a cap after the layer, each with the angles beyond and by how much (degrees), the
    largest first"""
    out = []
    for a, b in runs(mask):
        what = {}
        for name, x, _, c in pairs:
            over = float((x[a:b + 1] - c[a:b + 1] if np.ndim(c) else x[a:b + 1] - c).max())
            if over > 0.5:
                what[name] = _r(over, 1)
        out.append({"first": a, "last": b, "beyond": what})
    out.sort(key=lambda s: -max(s["beyond"].values(), default=0.0))
    return out[:limit]


def arm_report(final, reading_in, A, S, lim):
    def ab(x):
        return float(np.abs(x).max()) if len(x) else 0.0
    moved = np.linalg.norm(final["pe"] - final["elbow_split"], axis=-1) * UNIT_CM
    moved_in = np.linalg.norm(final["pe"] - A.pe0, axis=-1) * UNIT_CM
    rows = {}
    for key, label in (("ext", "external_rotation"), ("pron", "pronation"), ("elbow", "elbow"),
                       ("wflex", "wrist_flexion"), ("wradial", "wrist_radial")):
        rows[label] = {"in": stats(reading_in[key]), "out": stats(final[key])}
    beyond_in = reading_in["beyond"] > 0.5
    beyond_out = final["beyond"] > 0.5
    per = {}
    pin, pout = arm_pairs(reading_in, lim), arm_pairs(final, lim)
    for (name, xi, si, ci), (_, xo, so, co) in zip(pin, pout):
        per[name] = {"over_start_in": int((xi > si).sum()), "over_start_out": int((xo > so).sum()),
                     "over_cap_in": int((xi > ci + 0.5).sum()), "over_cap_out": int((xo > co + 0.5).sum()),
                     "max_over_cap_in": _r(max(float((xi - ci).max()), 0.0), 1),
                     "max_over_cap_out": _r(max(float((xo - co).max()), 0.0), 1)}
    big = []
    for a, b in runs(moved > 3.0):
        k = a + int(np.argmax(moved[a:b + 1]))
        big.append({"first": a, "last": b, "peak_frame": k, "peak_cm": _r(moved[k], 1)})
    big.sort(key=lambda x: -x["peak_cm"])
    return {"pronation_abs": {"in_max": _r(ab(reading_in["pron"])), "out_max": _r(ab(final["pron"]))},
            "angles": rows, "per_angle": per,
            "beyond_cap_frames_in": int(beyond_in.sum()), "beyond_cap_frames_out": int(beyond_out.sum()),
            "beyond_cap_stretches_out": left_beyond(beyond_out, pout),
            "elbow_moved_over_3cm": big[:30],
            "swivel_frames": int((np.abs(np.degrees(final["delta"])) > 0.5).sum()),
            "swivel_deg": stats(np.abs(np.degrees(final["delta"]))),
            "bent_back_frames": int((final["branch"] < 0).sum()),
            "elbow_moved_by_rom_cm": stats(moved), "elbow_moved_frames_over_1cm": int((moved > 1.0).sum()),
            "elbow_vs_input_cm": stats(moved_in),
            "unreachable_frames": int(final["unreachable"].sum()),
            "hinge_unsolvable_frames": int((~final["solvable"]).sum()),
            "wrist_error_cm": stats(final["wrist_err"] * UNIT_CM)}


def axial_shares(rot_lo, rot_up, whole, threshold):
    """the audit's share of the upper bone per component, where the whole moves more than `threshold` degrees"""
    out = {}
    a = upright_angles(rot_lo)
    b = upright_angles(rot_up)
    w = upright_angles(whole)
    for i, comp in enumerate(("flex", "lat", "rot")):
        m = np.abs(w[i]) > threshold
        if not m.any():
            out[comp] = {"frames": 0}
            continue
        share = np.abs(b[i][m]) / np.maximum(np.abs(a[i][m]) + np.abs(b[i][m]), 1e-9)
        out[comp] = {"frames": int(m.sum()), "upper_share_median": _r(np.median(share), 3),
                     "whole_max_deg": _r(np.abs(w[i]).max(), 1)}
    return out


def measure(model, motion, out, W, sides, arm_final, F, key_frames, new, p):
    names = [n for n in ("左手首", "右手首", "頭", TRUNK_UP, "両目", "左ひじ", "右ひじ", "首", TRUNK_LO, "下半身") if n in W.col]
    tips = {s: next((s + t for t in TIPS if s + t in W.col), s + "手首") for s, _ in SIDES}
    names += [t for t in tips.values() if t not in names]
    pose = fk.Pose(model, out, names)
    pos = np.zeros((F, len(names), 3))
    rot = np.zeros((F, len(names), 4))
    idx = [i for _, i in pose.targets]
    for f in range(F):
        w = pose.world(f)
        for j, i in enumerate(idx):
            pos[f, j], rot[f, j] = w[i]
    col = {n: j for j, n in enumerate(names)}
    err = {}
    for n in ("左手首", "右手首", "頭", TRUNK_UP, "両目"):
        if n not in col:
            continue
        dp = np.linalg.norm(pos[:, col[n]] - W.p(n), axis=-1) * UNIT_CM
        dq = np.degrees(qangle(qmul(qconj(W.q(n)), rot[:, col[n]])))
        err[n] = {"pos_cm": stats(dp), "rot_deg": stats(dq)}
    rep = {"pose_error": err}
    # the hands' distances to the eyes and to the body line (上半身 - 首)
    eyes_in = W.p("両目") if "両目" in W.col else W.p(HEAD)
    eyes_out = pos[:, col["両目"]] if "両目" in col else pos[:, col[HEAD]]
    dist = {}
    for s, _ in SIDES:
        t = tips[s]
        for what, a_in, a_out, b_in, b_out in (
                ("face", eyes_in, eyes_out, None, None),
                ("body", W.p(TRUNK_LO), pos[:, col[TRUNK_LO]], W.p(NECK) if NECK in W.col else W.p(HEAD),
                 pos[:, col[NECK]] if NECK in col else pos[:, col[HEAD]])):
            if b_in is None:
                d_in = np.linalg.norm(W.p(t) - a_in, axis=-1)
                d_out = np.linalg.norm(pos[:, col[t]] - a_out, axis=-1)
            else:
                d_in = seg_dist(W.p(t), a_in, b_in)
                d_out = seg_dist(pos[:, col[t]], a_out, b_out)
            near = d_in * UNIT_CM < 15.0
            ch = np.abs(d_out - d_in) * UNIT_CM
            dist[s + what] = {"min_in_cm": _r(d_in.min() * UNIT_CM), "min_out_cm": _r(d_out.min() * UNIT_CM),
                              "near_frames": int(near.sum()), "change_near_cm": stats(ch[near]), "change_cm": stats(ch)}
    rep["distances"] = dist
    # trunk and neck shares
    ax = {}
    if TRUNK_LO in col and TRUNK_UP in col and "下半身" in W.col:
        low = W.q("下半身")
        ax["trunk_in"] = axial_shares(qmul(qconj(low), W.q(TRUNK_LO)), qmul(qconj(W.q(TRUNK_LO)), W.q(TRUNK_UP)),
                                      qmul(qconj(low), W.q(TRUNK_UP)), 10.0)
        lo_o, up_o = rot[:, col[TRUNK_LO]], rot[:, col[TRUNK_UP]]
        ax["trunk_out"] = axial_shares(qmul(qconj(low), lo_o), qmul(qconj(lo_o), up_o), qmul(qconj(low), up_o), 10.0)
    if NECK in col:
        ax["neck_in"] = axial_shares(qmul(qconj(W.q(TRUNK_UP)), W.q(NECK)), qmul(qconj(W.q(NECK)), W.q(HEAD)),
                                     qmul(qconj(W.q(TRUNK_UP)), W.q(HEAD)), 15.0)
        n_o, h_o, c_o = rot[:, col[NECK]], rot[:, col[HEAD]], rot[:, col[TRUNK_UP]]
        ax["neck_out"] = axial_shares(qmul(qconj(c_o), n_o), qmul(qconj(n_o), h_o), qmul(qconj(c_o), h_o), 15.0)
        for which, c_, h_ in (("in", W.q(TRUNK_UP), W.q(HEAD)), ("out", c_o, h_o)):
            fl, la, ro = upright_angles(qmul(qconj(c_), h_))
            ax["neck_beyond_cap_frames_" + which] = int(((np.abs(ro) > 91) | (fl < -83) | (fl > 90) | (np.abs(la) > 64)).sum())
    rep["axial"] = ax
    # the trace's keys whose shape changed
    listed = []
    if key_frames:
        for s, _ in SIDES:
            if s not in arm_final or s not in key_frames:
                continue
            final, _, A = arm_final[s]
            e_cm = np.linalg.norm(pos[:, col[s + "ひじ"]] - W.p(s + "ひじ"), axis=-1) * UNIT_CM
            g = rep_girdle_change(W, out, s, sides[s], pos, rot, col, model, F)
            for f in key_frames[s]:
                if f >= F:
                    continue
                if e_cm[f] > KEY_ELBOW_CM or (g is not None and g[f] > KEY_GIRDLE_DEG):
                    listed.append({"side": s, "frame": int(f), "elbow_moved_cm": _r(e_cm[f], 1),
                                   "girdle_changed_deg": _r(g[f], 1) if g is not None else None,
                                   "external_rotation": [_r(arm_final[s][1]["ext"][f], 1), _r(final["ext"][f], 1)],
                                   "pronation": [_r(arm_final[s][1]["pron"][f], 1), _r(final["pron"][f], 1)],
                                   "elbow": [_r(arm_final[s][1]["elbow"][f], 1), _r(final["elbow"][f], 1)]})
    rep["key_changes"] = listed
    rep["key_changes_count"] = {s: sum(1 for x in listed if x["side"] == s) for s, _ in SIDES}
    labels = out.labels

    def kept(m):
        return [(k.raw_name, k.name, k.frame, k.position, k.rotation, k.interpolation) for k in m.bones if k.name not in labels]
    rep["untouched"] = {"identical": kept(motion) == kept(out), "keys": len(kept(motion)),
                        "written": sorted(new.keys()),
                        "morphs_identical": [(m.name, m.frame, m.weight) for m in motion.morphs]
                        == [(m.name, m.frame, m.weight) for m in out.morphs]}
    return rep


_GIRDLE_CACHE = {}


def rep_girdle_change(W, out, s, S, pos, rot, col, model, F):
    """degrees the 肩 bone's direction turned against the input, every frame (None without 肩 in the measure)"""
    sh = s + "肩"
    if sh not in W.col:
        return None
    pose = fk.Pose(model, out, [sh, TRUNK_UP])
    v = np.zeros((F, 3))
    for f in range(F):
        a = pose.at(f)
        v[f] = qrot(qconj(np.array(a[TRUNK_UP][1])), qrot(np.array(a[sh][1]), S.d_sh))
    v_in = qrot(qconj(W.q(TRUNK_UP)), qrot(W.q(sh), S.d_sh))
    return np.degrees(np.arccos(np.clip(dot(v, v_in), -1, 1)))


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(dot(p - a, ab) / np.maximum(dot(ab, ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[..., None] * ab), axis=-1)


# ---- files --------------------------------------------------------------------------------------------------------

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
            raise ValueError("%s and %s are the same file: the inputs, OUT and --report must all differ" % (seen[key], path))
        seen[key] = path


def short(report):
    out = {"pose_error_max": {n: [v["pos_cm"]["max"], v["rot_deg"]["max"]] for n, v in report["pose_error"].items()},
           "untouched_identical": report["untouched"]["identical"], "key_changes": report["key_changes_count"]}
    for s, _ in SIDES:
        if s in report["arm"]:
            a = report["arm"][s]
            out[s] = {"beyond_cap_frames": [a["beyond_cap_frames_in"], a["beyond_cap_frames_out"]],
                      "girdle_elevation_max": [report["girdle"][s]["elevation_in"]["max"], report["girdle"][s]["elevation_out"]["max"]],
                      "girdle_protraction_min": [report["girdle"][s]["protraction_in"]["min"], report["girdle"][s]["protraction_out"]["min"]],
                      "swivel_frames": a["swivel_frames"], "girdle_backoff_frames": report["girdle"][s]["backoff_frames"]}
    return out


def run(dance_path, model_path, out_path, report_path=None, key_frames_path=None, params=None, log=None):
    started = time.time()
    check_distinct(dance_path, model_path, out_path, report_path, key_frames_path)
    dance = vmd.load(dance_path)
    model = load_model(model_path)
    key_frames = key_frames_of(vmd.load(key_frames_path)) if key_frames_path else None
    result = layer(model, dance, params, key_frames, log)
    write_bytes(os.path.abspath(out_path), vmd.dumps(result.motion))
    report = dict({"in": os.path.abspath(dance_path), "model": os.path.abspath(model_path), "out": os.path.abspath(out_path),
                   "key_frames": key_frames_path and os.path.abspath(key_frames_path)}, **result.report)
    summary = dict({"out": os.path.abspath(out_path), "keys": len(result.motion.bones)}, **short(report))
    report["seconds"] = summary["seconds"] = _r(time.time() - started, 1)
    if report_path:
        write_bytes(os.path.abspath(report_path), (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        summary["report"] = os.path.abspath(report_path)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance", help="the dance motion (.vmd)")
    ap.add_argument("model", help="the model (.pmx or .pmd)")
    ap.add_argument("out", help="the dance with the layer (.vmd)")
    ap.add_argument("--report", help="write the measures of the input and the output to this JSON")
    ap.add_argument("--key-frames", help="a motion whose 左腕 / 右腕 keys are the trace's poses (listed where they change)")
    ap.add_argument("--forearm-twist", default="share", choices=("share", "keep", "handtw"),
                    help="share: fix_twist's rule on the new twist, 手捩 at most 45 degrees, 手首 the rest (default); "
                         "keep: 手捩 keeps the input's key, 手首 takes the rest; handtw: all of it on 手捩")
    ap.add_argument("--upper-twist-share", type=float, default=1.0,
                    help="the part of the upper arm's roll on 腕捩, the rest on 腕 (default 1)")
    ap.add_argument("--trunk-shares", help="flex,lat,rot moved from 上半身 onto 上半身2 (default 0.25,0.3,0.4)")
    ap.add_argument("--neck-shares", help="flex,lat,rot moved from 頭 onto 首 (default 0.6,0.7,0.333)")
    ap.add_argument("--girdle-elevation", help="start,cap of the girdle's elevation, degrees (default 20,25)")
    ap.add_argument("--girdle-retraction", help="start,cap of the girdle's retraction, degrees (default 20,25)")
    ap.add_argument("--hand-slack", type=float, default=GIRDLE_HAND_SLACK_CM,
                    help="cm a hand may slide along a straight arm so that the girdle can come back (default %g)"
                         % GIRDLE_HAND_SLACK_CM)
    ap.add_argument("--tenodesis", action="store_true", help="relaxed fingers follow the wrist (off by default)")
    ap.add_argument("--no-split", action="store_true", help="leave 上半身 / 上半身2 / 首 / 頭 as they are")
    ap.add_argument("--no-girdle", action="store_true", help="leave 肩 as it is")
    ap.add_argument("--no-rom", action="store_true", help="split the arm only, no range of motion")
    ap.add_argument("--verbose", action="store_true", help="progress on stderr")
    a = ap.parse_args(argv)
    params = default_params()
    params.update(forearm_twist=a.forearm_twist, upper_twist_share=a.upper_twist_share, tenodesis=a.tenodesis,
                  split=not a.no_split, girdle=not a.no_girdle, rom=not a.no_rom, girdle_hand_slack_cm=a.hand_slack)
    log = (lambda msg: print(msg, file=sys.stderr, flush=True)) if a.verbose else None
    try:
        for flag, key in ((a.trunk_shares, "trunk_shares"), (a.neck_shares, "neck_shares")):
            if flag:
                v = [float(x) for x in flag.split(",")]
                if len(v) != 3 or not all(0.0 <= x <= 1.0 for x in v):
                    raise ValueError("--%s is three shares 0 to 1: flex,lat,rot" % key.replace("_", "-"))
                params[key] = dict(zip(("flex", "lat", "rot"), v))
        for flag, key in ((a.girdle_elevation, "elevation"), (a.girdle_retraction, "retraction")):
            if flag:
                v = [float(x) for x in flag.split(",")]
                if len(v) != 2 or not 0.0 < v[0] < v[1]:
                    raise ValueError("--girdle-%s is start,cap with 0 < start < cap" % key)
                params["girdle_limits"] = dict(params["girdle_limits"], **{key: tuple(v)})
        result = run(a.dance, a.model, a.out, a.report, a.key_frames, params, log)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
