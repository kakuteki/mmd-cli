"""Bake anatomical hands onto a dance (work in progress: the reading of the hand's joints).

    python tools/hand_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json]
"""
import importlib.util
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402,F401
from mmd_cli.formats import pmd, pmx, pmx_edit, vmd  # noqa: E402,F401


def _tool(name):
    spec = importlib.util.spec_from_file_location("_hand_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _tool("anatomy_layer")          # the numpy quaternions (x, y, z, w, Hamilton) and the soft limit
unit, dot, qmul, qconj, qrot, aa, arc, twist = A.unit, A.dot, A.qmul, A.qconj, A.qrot, A.aa, A.arc, A.twist

SIDES = (("左", 1.0), ("右", -1.0))
LONG = ("人指", "中指", "薬指", "小指")
THUMB = "親指"
LONG_CHAIN = (("０", None), ("１", "mp"), ("２", "pip"), ("３", "dip"), ("３先", None))
THUMB_CHAIN = (("０", "cmc"), ("１", "mp"), ("２", "ip"), ("２先", None))
PULP_MIN_VERTICES = 20          # the thumb's pulp side is read from the mesh when this many vertices hang on 親指２
PULP_WEIGHT = 0.6               # (a vertex hangs on a bone when its weight there is at least this)


@dataclass
class Joint:
    """one joint of the hand.  bone: the bone whose local rotation is the joint (its parent is the segment before).
    The reading's basis, in the parent's frame at rest: dp the parent segment (for the thumb's CMC: the index
    metacarpal in the palm's plane), n the flexion side perpendicular to dp (the palm, the thumb's pulp; for the CMC the
    radial side in the palm's plane), s the side angle's positive side perpendicular to both (toward the thumb; for the
    thumb's joints toward the index; for the CMC the palm).  d: the joint's own segment at rest (bone -> its child)."""
    side: str
    finger: str
    kind: str
    bone: str
    d: np.ndarray
    dp: np.ndarray
    n: np.ndarray
    s: np.ndarray
    axis: np.ndarray            # a positive turn about it bends the segment toward n (dp x n)
    rest: tuple                 # (flex, side) of the rest pose, degrees
    length: float               # the joint's own segment, model units


@dataclass
class Hand:
    side: str
    sx: float
    palm: np.ndarray            # the palm's normal (the side the fingers bend to)
    radial: np.ndarray          # across the knuckles toward the thumb, in the palm's plane
    joints: list = field(default_factory=list)


def _positions(model):
    out = {}
    for b in model.bones:
        out.setdefault(b.name, np.array(b.position, dtype=float))
    return out


def _basis(dp, n, toward):
    n = unit(n - dot(n, dp) * dp)
    axis = unit(np.cross(dp, n))
    s = axis if float(axis @ toward) >= 0.0 else -axis
    return n, s, axis


def _reading(d, dp, n, s):
    return (math.degrees(math.atan2(float(d @ n), float(d @ dp))), math.degrees(math.asin(max(-1.0, min(1.0, float(d @ s))))))


def hand_model(model, pulp=None):
    """side -> Hand: the joints of the four long fingers and the thumb read from the rest positions.  pulp: side -> the
    thumb's pulp side (a vector; from the mesh, see pulp_from_mesh); without it the palm's normal is used"""
    P = _positions(model)
    out = {}
    for side, sx in SIDES:
        need = [side + n for n in ("手首", "人指１", "中指１", "小指１")]
        missing = [n for n in need if n not in P]
        if missing:
            raise ValueError("the model has no %s: the hand layer needs the wrist and the knuckles" % ", ".join(missing))
        d_h = unit(P[side + "中指１"] - P[side + "手首"])
        across = P[side + "人指１"] - P[side + "小指１"]
        palm = unit(np.cross(d_h, across)) * (-sx)
        palm = unit(palm - dot(palm, d_h) * d_h)
        radial = unit(across - dot(across, palm) * palm)
        hand = Hand(side, sx, palm, radial)
        for f in LONG:
            names = [(side + f + p, k) for p, k in LONG_CHAIN]
            if any(n not in P for n, _ in names[1:4]):
                continue
            chain = [(n, k) for n, k in names if n in P]
            for i, (b, kind) in enumerate(chain):
                if kind is None or i == 0 or i + 1 >= len(chain):
                    continue
                parent = chain[i - 1][0]
                dp = unit(P[b] - P[parent])
                d = unit(P[chain[i + 1][0]] - P[b])
                n, s, axis = _basis(dp, palm, radial)
                hand.joints.append(Joint(side, f, kind, b, d, dp, n, s, axis, _reading(d, dp, n, s),
                                         float(np.linalg.norm(P[chain[i + 1][0]] - P[b]))))
        t = [side + THUMB + p for p, _ in THUMB_CHAIN]
        if all(n in P for n in t[:3]) and side + "人指０" in P:
            tip = t[3] if t[3] in P else None
            pv = pulp.get(side) if pulp else None
            pv = unit(np.asarray(pv, dtype=float)) if pv is not None else palm
            toward_index = P[side + "人指１"] - P[t[1]]
            # the CMC: the thumb's metacarpal against the index metacarpal (JOA: radial abduction in the palm's plane,
            # palmar abduction out of it)
            m2 = unit(P[side + "人指１"] - P[side + "人指０"])
            e1 = unit(m2 - dot(m2, palm) * palm)
            r_in = unit(radial - dot(radial, e1) * e1)
            d = unit(P[t[1]] - P[t[0]])
            axis = unit(np.cross(e1, r_in))
            hand.joints.append(Joint(side, THUMB, "cmc", t[0], d, e1, r_in, palm, axis, _reading(d, e1, r_in, palm),
                                     float(np.linalg.norm(P[t[1]] - P[t[0]]))))
            for i, kind in ((1, "mp"), (2, "ip")):
                child = t[i + 1] if i + 1 < 3 or tip else None
                if child is None:
                    break
                dp = unit(P[t[i]] - P[t[i - 1]])
                d = unit(P[child] - P[t[i]])
                n, s, axis = _basis(dp, pv, toward_index)
                hand.joints.append(Joint(side, THUMB, kind, t[i], d, dp, n, s, axis, _reading(d, dp, n, s),
                                         float(np.linalg.norm(P[child] - P[t[i]]))))
        out[side] = hand
    return out


def read_joint(j, q):
    """(flex, side, twist) in degrees of the joint's local rotations q [N, 4]: the segment's direction c = q d read in
    the basis (dp, n, s): flex = atan2(c.n, c.dp), side = asin(c.s); twist about the segment's rest axis d (q = swing
    twist, the twist first)"""
    q = np.asarray(q, dtype=float)
    c = qrot(q, j.d)
    flex = np.degrees(np.arctan2(c @ j.n, c @ j.dp))
    side = np.degrees(np.arcsin(np.clip(c @ j.s, -1.0, 1.0)))
    return flex, side, np.degrees(twist(q, j.d))


def compose_joint(j, flex, side, tw):
    """the local rotations that read (flex, side, twist): the inverse of read_joint"""
    f, s, t = (np.radians(np.asarray(v, dtype=float)) for v in (flex, side, tw))
    c = np.cos(s)[..., None] * (np.cos(f)[..., None] * j.dp + np.sin(f)[..., None] * j.n) + np.sin(s)[..., None] * j.s
    return A.qnorm(qmul(arc(np.broadcast_to(j.d, c.shape), unit(c)), aa(j.d, t)))


def pulp_from_mesh(path, palm=None):
    """side -> the pulp side of the thumb's distal phalanx: the axis of least spread of the vertices that hang on 親指２
    (the thumbnail's normal), turned toward the palm.  A side with fewer than PULP_MIN_VERTICES such vertices is left
    out.  palm: side -> the palm's normal (else read from the model's bones)"""
    doc = pmx_edit.load(path)
    names = [b.name for b in doc.bones]
    index = {n: i for i, n in enumerate(names)}
    if palm is None:
        hands = hand_model(pmx.load(path)) if path.lower().endswith(".pmx") else hand_model(pmd.load(path))
        palm = {s: h.palm for s, h in hands.items()}
    pos = None
    out = {}
    for side, _ in SIDES:
        b = index.get(side + THUMB + "２")
        if b is None:
            continue
        vi = [k for k, v in enumerate(doc.vertices) if any(bb == b and w >= PULP_WEIGHT for bb, w in v.pairs())]
        if len(vi) < PULP_MIN_VERTICES:
            continue
        if pos is None:
            pos = np.array([v.position() for v in doc.vertices])
        X = pos[vi] - pos[vi].mean(axis=0)
        _, _, vt = np.linalg.svd(X, full_matrices=False)
        thick = vt[2]
        out[side] = thick if float(thick @ palm[side]) >= 0.0 else -thick
    return out


# ---- the fingers' passive lag ------------------------------------------------------------------------------------

GRAVITY = np.array([0.0, -9.80665, 0.0])          # m/s^2 in the model's axes (Y up)


def passive_response(forcing, omega, zeta, fps, substeps=8):
    """delta [F, J] (radians) of joints that follow  delta'' + 2 zeta omega delta' + omega^2 delta = forcing  from rest
    at frame 0, the forcing [F, J] (rad/s^2) taken as linear between frames; semi-implicit Euler, `substeps` per frame.
    omega and zeta are [J] or, changing with time, [F, J] (the frame's own values through its interval)"""
    forcing = np.asarray(forcing, dtype=float)
    F, J = forcing.shape
    w = np.broadcast_to(np.asarray(omega, dtype=float), (F, J))
    z = np.broadcast_to(np.asarray(zeta, dtype=float), (F, J))
    dt = 1.0 / (fps * substeps)
    d, v = np.zeros(J), np.zeros(J)
    out = np.zeros((F, J))
    for t in range(1, F):
        a0, a1 = forcing[t - 1], forcing[t]
        wt, zt = w[t], z[t]
        for k in range(substeps):
            f = a0 + (a1 - a0) * ((k + 1) / substeps)
            v = v + dt * (f - 2.0 * zt * wt * v - wt * wt * d)
            d = d + dt * v
        out[t] = d
    return out


def angular_velocity(R, fps):
    """the world angular velocity (rad/s) between frames t and t+1 of world rotations R [F, 4]: [F - 1, 3]"""
    dq = qmul(R[1:], qconj(R[:-1]))
    dq = np.where(dq[:, 3:4] < 0.0, -dq, dq)
    s = np.linalg.norm(dq[:, :3], axis=1)
    ang = 2.0 * np.arctan2(s, dq[:, 3])
    axis = dq[:, :3] / np.maximum(s, 1e-12)[:, None]
    return axis * (ang * fps)[:, None]


def angular_acceleration(R, fps):
    """the world angular acceleration (rad/s^2) at each frame of world rotations R [F, 4]: [F, 3] (the ends repeat
    their neighbours)"""
    w = angular_velocity(R, fps)
    out = np.zeros((len(R), 3))
    if len(R) >= 3:
        out[1:-1] = (w[1:] - w[:-1]) * fps
        out[0], out[-1] = out[1], out[-2]
    return out


def point_acceleration(p, fps):
    """the acceleration [F, 3] of points p [F, 3] (second differences; the ends repeat their neighbours)"""
    out = np.zeros_like(p, dtype=float)
    if len(p) >= 3:
        out[1:-1] = (p[2:] - 2.0 * p[1:-1] + p[:-2]) * fps * fps
        out[0], out[-1] = out[1], out[-2]
    return out


def joint_forcing(alpha, acc, axis, e, r=None, rho=None, gravity=True, coeff=None):
    """the forcing (rad/s^2) on a joint's flexion from the motion of the frame it hangs in: the hand's world angular
    acceleration alpha [F, 3] about the joint's world flexion axis [F, 3], and the joint's world linear acceleration acc
    [F, 3] (m/s^2; gravity taken away when asked) on the part beyond it, its centre of mass r metres out along the unit
    direction e [F, 3], its radius of gyration about that centre rho: -(alpha . axis) - r / (r^2 + rho^2) (e x (acc - g))
    . axis (coeff, when given, is r / (r^2 + rho^2) = M r / I).  Positive bends the part toward the palm (flexion)."""
    a = np.asarray(acc, dtype=float) - (GRAVITY if gravity else 0.0)
    c = coeff if coeff is not None else r / (r * r + rho * rho)
    return -dot(alpha, axis) - c * dot(np.cross(e, a), axis)


# ---- the numbers (sources: _spike/out/stage6/hands/research, the module docstring) ------------------------------

FPS = 30.0
UNIT_M = 0.08                    # one model unit is 8 cm (the analysis pack's README)
STEPS = ("hinge", "coupling", "rom", "relax", "speed", "order", "passive")
# the hinge joints (PIP, DIP, the thumb's IP and MP) bend in one plane: their sideways bend and their twist, read from
# the rest pose, eased from the start toward the cap (degrees)
HINGE = {"side": (3.0, 8.0), "twist": (5.0, 12.0)}
# DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high
COUPLING = {"low": 0.5, "high": 1.15, "from": 20.0, "full": 40.0}
# the range of motion against the rest pose (the thumb's CMC: radial and palmar abduction against the index
# metacarpal, read absolutely): (soft start, cap) for each way, degrees
ROM = {
    "mp": {"flex": ((25.0, 45.0), (90.0, 100.0)), "side": ((25.0, 35.0), (25.0, 35.0)), "twist": ((15.0, 25.0), (15.0, 25.0))},
    "pip": {"flex": ((5.0, 15.0), (100.0, 110.0))},
    "dip": {"flex": ((5.0, 10.0), (80.0, 90.0))},
    "cmc": {"flex": ((10.0, 20.0), (60.0, 65.0)), "side": ((15.0, 25.0), (90.0, 95.0)), "twist": ((25.0, 35.0), (25.0, 35.0))},
    "tmp": {"flex": ((10.0, 20.0), (60.0, 65.0))},
    "ip": {"flex": ((10.0, 20.0), (80.0, 90.0))},
}
SPEED_MAX_DEG_S = 1900.0         # a finger's MP + PIP + DIP together, degrees per second
DIP_LAG_FRAMES = 0.75            # the DIP follows the PIP this many frames late while they move
ORDER_SPEED = (60.0, 240.0)      # degrees per second of the PIP or the DIP over which the lag fades in
# the relaxed hand: an open hand (the four fingers' mean MP + PIP + DIP under OPEN[0], none over OPEN[2]) is relaxed
# (fully at OPEN[0], not at all from OPEN[1]); it takes the cascade (degrees of MP, PIP, DIP added per finger) and the
# wrist's tenodesis (degrees per degree of wrist extension against the hold's mean), times RELAX_GAIN
OPEN = (30.0, 70.0, 90.0)
CASCADE = {"人指": (0.0, 0.0, 0.0), "中指": (3.0, 4.0, 2.0), "薬指": (6.0, 8.0, 4.0), "小指": (9.0, 12.0, 6.0)}
TENODESIS = {"mp": 0.30, "pip": 0.43, "dip": 0.16}
RELAX_GAIN = 1.0
# the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper
SEGMENT_MASS = {"人指": (19.1, 8.1, 6.0), "中指": (20.0, 9.6, 6.5), "薬指": (17.0, 8.9, 5.5), "小指": (10.8, 5.3, 4.3),
                "親指": (12.0, 6.0)}
REF_LENGTH_M = {"人指": 0.099, "中指": 0.109, "薬指": 0.102, "小指": 0.082, "親指": 0.06}
REF_INERTIA = {"人指": 9.5e-5, "中指": 1.26e-4, "薬指": 9.9e-5, "小指": 4.6e-5, "親指": 4.0e-5}
STIFFNESS = {"held": 0.67, "open": 0.21}           # N m/rad at the MP of a grown finger
DAMPING = 0.005                                     # N m s/rad
PASSIVE_SHARE = {"mp": 1.0, "pip": 0.35, "dip": 0.2, "tmp": 1.0, "ip": 0.5}
PASSIVE_CAP = (6.0, 15.0)                           # degrees: the lag is eased from the start toward the cap
ACC_SMOOTH = 1                                      # frames each way of the triangle that smooths the accelerations


def default_params():
    p = {s: True for s in STEPS}
    p.update(relax_gain=RELAX_GAIN, speed_max=SPEED_MAX_DEG_S, dip_lag=DIP_LAG_FRAMES, gravity=False,
             stiffness=dict(STIFFNESS), damping=DAMPING, passive_cap=PASSIVE_CAP)
    return p


soft_limit, soft_band, smoothstep, runs = A.soft_limit, A.soft_band, A.smoothstep, A.runs


def _r(x, n=2):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def stats(x):
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "max": _r(x.max()), "p99": _r(np.percentile(x, 99)), "p95": _r(np.percentile(x, 95)),
            "p50": _r(np.median(x)), "min": _r(x.min())}


def kind_of(j):
    """the joint's kind for the tables: the thumb's MP is "tmp" (the long fingers' is "mp")"""
    return "tmp" if (j.finger == THUMB and j.kind == "mp") else j.kind


# ---- the input ----------------------------------------------------------------------------------------------------

def joint_locals(motion, names, F):
    """name -> [F, 4] the local rotations as applied (identity where the bone has no key), and name -> [F, 3] the key
    positions (zero without keys)"""
    tracks = fk.tracks_of(motion)
    rot, pos = {}, {}
    for n in names:
        keys = tracks.get(n) or tracks.get(fk.vmd_name(n))
        q = np.zeros((F, 4))
        q[:, 3] = 1.0
        p = np.zeros((F, 3))
        if keys:
            frames = [k.frame for k in keys]
            for f in range(F):
                pp, qq = fk.sample(keys, f, frames)
                q[f], p[f] = fk.applied(qq), pp
        rot[n], pos[n] = q, p
    return rot, pos


def read_all(hands, loc):
    """bone -> [flex, side, twist] (an array [3, F], degrees): against the rest pose, the thumb's CMC absolutely"""
    out = {}
    for hand in hands.values():
        for j in hand.joints:
            f, s, t = read_joint(j, loc[j.bone])
            if j.kind != "cmc":
                f, s = f - j.rest[0], s - j.rest[1]
            out[j.bone] = np.stack([f, s, t])
    return out


def compose_all(hands, ang):
    out = {}
    for hand in hands.values():
        for j in hand.joints:
            f, s, t = ang[j.bone]
            if j.kind != "cmc":
                f, s = f + j.rest[0], s + j.rest[1]
            out[j.bone] = compose_joint(j, f, s, t)
    return out


def chains(hand):
    """finger -> {kind: joint}"""
    out = {}
    for j in hand.joints:
        out.setdefault(j.finger, {})[j.kind] = j
    return out


# ---- step 1: the shape in each frame ------------------------------------------------------------------------------

def hinge(hands, ang):
    """the hinge joints' sideways bend and twist eased toward their plane (HINGE)"""
    for hand in hands.values():
        for j in hand.joints:
            if j.kind in ("pip", "dip", "ip") or (j.finger == THUMB and j.kind == "mp"):
                a = ang[j.bone]
                a[1] = soft_band(a[1], HINGE["side"], HINGE["side"])
                a[2] = soft_band(a[2], HINGE["twist"], HINGE["twist"])


def coupling(hands, ang):
    """the DIP of each long finger kept between COUPLING low and high times its PIP where the PIP bends (fully from
    COUPLING["full"] degrees, fading in from COUPLING["from"]); soft at both ends (the excess saturates)"""
    for hand in hands.values():
        for f, js in chains(hand).items():
            if f == THUMB or "pip" not in js or "dip" not in js:
                continue
            pip, dip = ang[js["pip"].bone][0], ang[js["dip"].bone][0]
            w = smoothstep(pip, COUPLING["from"], COUPLING["full"])
            lo, hi = COUPLING["low"] * pip, COUPLING["high"] * pip
            below = np.maximum(lo - dip, 0.0)
            above = np.maximum(dip - hi, 0.0)
            # a soft wall: an excess e is brought to 4 (1 - exp(-e / 4)) degrees past the band
            new = np.where(below > 0, lo - 4.0 * (1.0 - np.exp(-below / 4.0)), dip)
            new = np.where(above > 0, hi + 4.0 * (1.0 - np.exp(-above / 4.0)), new)
            ang[js["dip"].bone][0] = dip + w * (new - dip)


def rom(hands, ang):
    """every joint's angles eased into its range (ROM: soft start, cap; identity below the start)"""
    for hand in hands.values():
        for j in hand.joints:
            lim = ROM[kind_of(j)]
            for i, way in enumerate(("flex", "side", "twist")):
                if way in lim:
                    low, high = lim[way]
                    ang[j.bone][i] = soft_band(ang[j.bone][i], low, high)


# ---- step 2: the relaxed hand -------------------------------------------------------------------------------------

def finger_sums(hand, ang):
    return {f: sum(ang[js[k].bone][0] for k in ("mp", "pip", "dip")) for f, js in chains(hand).items() if f != THUMB}


def relaxedness(hand, ang):
    """0 .. 1 per frame: an open hand (the long fingers' mean MP + PIP + DIP at most OPEN[0] gives 1, OPEN[1] and over
    gives 0), none of them bent over OPEN[2] (a pointing or a peace hand is not relaxed)"""
    sums = finger_sums(hand, ang)
    if not sums:
        return None
    s = np.stack(list(sums.values()))
    r = 1.0 - smoothstep(s.mean(axis=0), OPEN[0], OPEN[1])
    return r * (1.0 - smoothstep(s.max(axis=0), OPEN[2], OPEN[2] + 30.0))


def relax(hands, ang, wrist_ext, gain):
    """the cascade and the tenodesis on the relaxed hand: added flexion = gain x r x (CASCADE + TENODESIS x (wrist
    extension - its mean over the relaxed stretch))"""
    out = {}
    for side, hand in hands.items():
        r = relaxedness(hand, ang)
        if r is None:
            continue
        w = wrist_ext[side]
        base = np.zeros_like(w)
        for a, b in runs(r > 0.0):
            seg = slice(a, b + 1)
            base[seg] = np.average(w[seg], weights=r[seg] + 1e-9)
        for f, js in chains(hand).items():
            if f == THUMB:
                continue
            for i, k in enumerate(("mp", "pip", "dip")):
                add = gain * r * (CASCADE[f][i] + TENODESIS[k] * (w - base))
                ang[js[k].bone][0] = ang[js[k].bone][0] + add
        out[side] = r
    return out


# ---- step 3: the timing ---------------------------------------------------------------------------------------

def box_average(x, h):
    """the mean of x over [t - h, t + h] (x linear between frames, held at the ends) for every frame t, h >= 0 per
    frame (fractional); h = 0 gives x"""
    F = len(x)
    pad = int(np.ceil(h.max())) + 2 if len(h) else 2
    xp = np.concatenate([np.full(pad, x[0]), x, np.full(pad, x[-1])])
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (xp[1:] + xp[:-1]))])     # the integral from the padded start
    t = np.arange(F) + pad
    lo, hi = t - h, t + h
    i_lo, i_hi = np.interp(lo, np.arange(len(cum)), cum), np.interp(hi, np.arange(len(cum)), cum)
    return np.where(h > 1e-9, (i_hi - i_lo) / np.maximum(2.0 * h, 1e-9), x)


def speed_limit(hands, ang, vmax):
    """a finger whose MP + PIP + DIP flexion (the thumb: its three joints) turns faster than vmax degrees per second
    is spread round the middle of the change: every angle of the finger is averaged over a window wide enough for the
    change (2h frames for a step of 2h vmax / FPS), narrowing to nothing away from it"""
    v = vmax / FPS
    report = {}
    for side, hand in hands.items():
        for f, js in chains(hand).items():
            bones = [j.bone for j in js.values()]
            for _ in range(4):
                flex = sum(np.abs(np.diff(ang[b][0])) for b in bones)
                need = np.maximum(flex / v - 1.0, 0.0) / 2.0 + (flex > v) * 0.5   # per step t -> t+1
                if not (flex > v * 1.0001).any():
                    break
                h = np.zeros(len(flex) + 1)
                h[:-1] = np.maximum(h[:-1], need)
                h[1:] = np.maximum(h[1:], need)
                reach = int(np.ceil(h.max())) + 1
                hd = np.array([h[max(0, t - reach):t + reach + 1].max() for t in range(len(h))])
                k = np.hanning(2 * reach + 3)[1:-1]
                hs = np.convolve(np.pad(hd, reach, mode="edge"), k / k.sum(), "valid")
                hs = np.maximum(hs, h)
                for b in bones:
                    for i in range(3):
                        ang[b][i] = box_average(ang[b][i], hs)
                report[side + f] = report.get(side + f, 0) + int((need > 0).sum())
    return report


def time_shift(x, lag):
    """x read lag[t] frames earlier at every frame t (linear between frames, held before the start)"""
    t = np.arange(len(x)) - lag
    return np.interp(t, np.arange(len(x)), x)


def order(hands, ang, lag):
    """the DIP follows its PIP `lag` frames late while the two move (faded in by ORDER_SPEED; a hold is untouched)"""
    for hand in hands.values():
        for f, js in chains(hand).items():
            if f == THUMB or "pip" not in js or "dip" not in js:
                continue
            pip, dip = ang[js["pip"].bone], ang[js["dip"].bone]
            sp = np.maximum(np.abs(np.gradient(pip[0])), np.abs(np.gradient(dip[0]))) * FPS
            a = smoothstep(sp, *ORDER_SPEED)
            reach = int(np.ceil(lag)) + 2
            a = np.array([a[max(0, t - reach):t + reach + 1].max() for t in range(len(a))])
            for i in range(3):
                dip[i] = time_shift(dip[i], lag * a)


# ---- step 4: the passive lag --------------------------------------------------------------------------------------

@dataclass
class Body:
    """one finger as a body turning at its first joint (the MP; the thumb's MP), from the model's segment lengths and
    the reference finger's mass shares (SEGMENT_MASS): coeff = M r / I (1/m: what a linear acceleration of the joint
    does to the angle), omega for the held and the open hand (rad/s, the reference stiffness scaled with the finger:
    stiffness ~ s^3, inertia ~ s^5), zeta from the reference finger"""
    finger: str
    joint: Joint
    coeff: float
    omega: dict
    zeta: dict
    scale: float


def finger_body(hand, finger, params):
    js = chains(hand)[finger]
    seq = [js[k] for k in (("mp", "ip") if finger == THUMB else ("mp", "pip", "dip")) if k in js]
    lengths = np.array([j.length for j in seq]) * UNIT_M
    masses = np.array(SEGMENT_MASS[finger][:len(seq)], dtype=float) * 1e-3
    s = float(lengths.sum() / REF_LENGTH_M[finger])
    m = masses * s ** 3
    x = np.cumsum(lengths) - lengths / 2.0
    I = float(np.sum(m * (x * x + lengths * lengths / 12.0)))
    coeff = float(np.sum(m * x)) / I
    omega, zeta = {}, {}
    for state, k_ref in params["stiffness"].items():
        omega[state] = math.sqrt(k_ref * s ** 3 / I)
        zeta[state] = params["damping"] / (2.0 * math.sqrt(k_ref * REF_INERTIA[finger]))
    return Body(finger, seq[0], coeff, omega, zeta, s)


def hand_world(model, motion, F, sides):
    """side -> (the wrist's world positions [F, 3] in model units, its world rotations [F, 4])"""
    names = [s + "手首" for s in sides]
    pose = fk.Pose(model, motion, names)
    idx = [i for _, i in pose.targets]
    pos = np.zeros((F, len(names), 3))
    rot = np.zeros((F, len(names), 4))
    for f in range(F):
        w = pose.world(f)
        for c, i in enumerate(idx):
            pos[f, c], rot[f, c] = w[i][0], w[i][1]
    return {s: (pos[:, c], A.continuous(rot[:, c])) for c, s in enumerate(sides)}


def smooth_frames(x, reach):
    """x [F, ...] smoothed along time by a triangle `reach` frames each way (the ends held)"""
    if reach <= 0:
        return x
    k = np.concatenate([np.arange(1, reach + 2), np.arange(reach, 0, -1)]).astype(float)
    k /= k.sum()
    xp = np.concatenate([np.repeat(x[:1], reach, axis=0), x, np.repeat(x[-1:], reach, axis=0)], axis=0)
    flat = xp.reshape(len(xp), -1)
    out = np.stack([np.convolve(flat[:, i], k, "valid") for i in range(flat.shape[1])], axis=1)
    return out.reshape((len(x),) + x.shape[1:])


def passive(hands, ang, loc, world, P, params, held):
    """the fingers' lag (radians -> degrees added to the flexion; the long fingers' MP, PIP, DIP by PASSIVE_SHARE, the
    thumb's MP and IP): each finger's body driven by the hand's world angular acceleration about its MP's axis and the
    MP's world linear acceleration (gravity only when asked: the dancer holds the shape she shows against it), the
    stiffness between the open and the held hand by `held` (0 .. 1 per frame), the lag eased toward PASSIVE_CAP"""
    report = {}
    for side, hand in hands.items():
        if side not in world:
            continue
        wpos, wrot = world[side]
        alpha = smooth_frames(angular_acceleration(wrot, FPS), ACC_SMOOTH)
        bodies = [finger_body(hand, f, params) for f in chains(hand)
                  if ("pip" in chains(hand)[f] or f == THUMB) and "mp" in chains(hand)[f]]
        F = len(wpos)
        forcing = np.zeros((F, len(bodies)))
        omega = np.zeros((F, len(bodies)))
        zeta = np.zeros((F, len(bodies)))
        h = held[side]
        for c, b in enumerate(bodies):
            j = b.joint
            parent = j.bone[:-1] + "０"            # 人指０ (the metacarpal bone) or 親指０ (the thumb's metacarpal)
            # the MP joint in the hand's frame (through the metacarpal bone's own turn) and in the world
            par = parent if parent in loc else None
            Rp = loc[par] if par is not None else np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
            base = P[par] - P[side + "手首"] if par is not None else np.zeros(3)
            p_hand = base + qrot(Rp, P[j.bone] - (P[par] if par is not None else P[side + "手首"]))
            p_world = (wpos + qrot(wrot, p_hand)) * UNIT_M
            acc = smooth_frames(point_acceleration(p_world, FPS), ACC_SMOOTH)
            Rpw = qmul(wrot, Rp)
            axis = qrot(Rpw, j.axis)
            e = qrot(qmul(Rpw, loc[j.bone]), j.d)
            forcing[:, c] = joint_forcing(alpha, acc, axis, e, gravity=params["gravity"], coeff=b.coeff)
            omega[:, c] = b.omega["open"] + (b.omega["held"] - b.omega["open"]) * h
            zeta[:, c] = b.zeta["open"] + (b.zeta["held"] - b.zeta["open"]) * h
        delta = np.degrees(passive_response(forcing, omega, zeta, FPS))
        cap = params["passive_cap"]
        delta = soft_band(delta, cap, cap)
        rep = {}
        for c, b in enumerate(bodies):
            js = chains(hand)[b.finger]
            for k, share in PASSIVE_SHARE.items():
                kk = "mp" if k == "tmp" else k
                if (b.finger == THUMB) != (k in ("tmp", "ip")) or kk not in js:
                    continue
                ang[js[kk].bone][0] = ang[js[kk].bone][0] + share * delta[:, c]
            rep[b.finger] = {"lag_deg": stats(np.abs(delta[:, c])), "f_held_hz": _r(b.omega["held"] / (2 * math.pi), 1),
                             "f_open_hz": _r(b.omega["open"] / (2 * math.pi), 1), "zeta_held": _r(b.zeta["held"], 2),
                             "zeta_open": _r(b.zeta["open"], 2), "scale": _r(b.scale, 3), "coeff_per_m": _r(b.coeff, 1)}
        report[side] = rep
    return report


def wrist_extension(model, loc, F):
    """side -> the wrist's extension (degrees, palmar flexion negative) against the forearm, from 手捩 and 手首's locals
    (as tools/anatomy_layer.arm_angles reads it); zeros where the model has no arm"""
    out = {}
    try:
        sides = A.rest_sides(model)
    except ValueError:
        sides = {}
    for side, _ in SIDES:
        S = sides.get(side)
        if S is None or side + "手捩" not in loc or side + "手首" not in loc:
            out[side] = np.zeros(F)
            continue
        qf = qmul(loc[side + "手捩"], loc[side + "手首"])
        tf = twist(qf, S.d_f)
        s_loc = qmul(qconj(aa(S.d_f, tf)), qf)
        ch = qrot(s_loc, S.d_h)
        mh = unit(S.n - (S.n @ S.d_h) * S.d_h)
        out[side] = -np.degrees(np.arctan2(ch @ mh, ch @ S.d_h))
    return out


# ---- the layer ----------------------------------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict


def layer(model, motion, params=None, pulp=None, log=None):
    """the hands of `motion` made anatomical (see the module docstring); pulp: side -> the thumb's pulp side (from the
    mesh: pulp_from_mesh), else the palm's normal"""
    p = default_params()
    p.update(params or {})
    if not motion.bones:
        raise ValueError("the dance has no bone keys")
    F = fk.last_frame(motion) + 1
    hands = hand_model(model, pulp=pulp)
    P = _positions(model)
    names = [j.bone for h in hands.values() for j in h.joints]
    extra = [s + f + "０" for s, _ in SIDES for f in LONG if s + f + "０" in P]
    extra += [s + n for s, _ in SIDES for n in ("手捩", "手首") if s + n in P]
    loc, keypos = joint_locals(motion, names + extra, F)
    ang_in = read_all(hands, loc)
    ang = {b: a.copy() for b, a in ang_in.items()}
    report = {"params": {k: v for k, v in p.items()}, "frames": F, "pulp": {s: (v.tolist() if v is not None else None)
              for s, v in (pulp or {}).items()}, "steps": {}}
    if p["hinge"]:
        hinge(hands, ang)
    if p["coupling"]:
        coupling(hands, ang)
    if p["rom"]:
        rom(hands, ang)
    relaxed = {s: relaxedness(h, ang) for s, h in hands.items()}
    held = {s: (1.0 - r) if r is not None else np.ones(F) for s, r in relaxed.items()}
    if p["relax"]:
        report["steps"]["relax_frames"] = {s: int((r > 0.5).sum()) for s, r in
                                           relax(hands, ang, wrist_extension(model, loc, F), p["relax_gain"]).items()}
    if p["speed"]:
        report["steps"]["speed_spread_steps"] = speed_limit(hands, ang, p["speed_max"])
    if p["order"]:
        order(hands, ang, p["dip_lag"])
    sides = [s for s, _ in SIDES if s + "手首" in P and s in hands]
    world = hand_world(model, motion, F, sides) if sides else {}
    if p["passive"]:
        report["steps"]["passive"] = passive(hands, ang, loc, world, P, p, held)
    if p["rom"]:
        rom(hands, ang)
    out_loc = compose_all(hands, ang)
    out_motion = A.build(motion, None, out_loc, {b: keypos[b] for b in out_loc}, F)
    report["untouched"] = untouched(motion, out_motion, out_motion.labels)
    report["input"] = measure(hands, ang_in, loc, world, P)
    report["output"] = measure(hands, ang, out_loc, world, P)
    report["change"] = change(hands, ang_in, ang, held)
    return Result(out_motion, report)


def untouched(before, after, labels):
    a = [k for k in before.bones if k.name not in labels]
    b = [k for k in after.bones if k.name not in labels]
    same = vmd.dumps(vmd.Motion(model_name="x", bones=a)) == vmd.dumps(vmd.Motion(model_name="x", bones=b))
    morphs = vmd.dumps(vmd.Motion(model_name="x", morphs=list(before.morphs))) == \
        vmd.dumps(vmd.Motion(model_name="x", morphs=list(after.morphs)))
    return {"identical": bool(same and morphs), "bones_identical": bool(same), "morphs_identical": bool(morphs),
            "keys_kept": len(b)}


# ---- the measures -------------------------------------------------------------------------------------------------

def measure(hands, ang, loc, world, P):
    """per side: the range of motion (frames beyond the start and the cap, each way), the hinge joints' sideways bend
    and twist, DIP / PIP, the open hand's cascade, the largest steps, the shape changes' speed and the DIP's onset
    after the PIP's, and the fingers held dead still while the hand moves"""
    out = {}
    for side, hand in hands.items():
        r = {"rom": {}, "hinge": {}, "coupling": {}}
        for j in hand.joints:
            lim = ROM[kind_of(j)]
            row = {}
            for i, way in enumerate(("flex", "side", "twist")):
                if way not in lim:
                    continue
                x = ang[j.bone][i]
                (ls, lc), (hs, hc) = lim[way]
                row[way] = {"beyond_start": int(((x > hs) | (x < -ls)).sum()), "beyond_cap": int(((x > hc) | (x < -lc)).sum()),
                            "max_beyond_cap": _r(max(0.0, float(np.max(np.maximum(x - hc, -lc - x)))))}
            r["rom"][j.bone] = row
            if j.kind in ("pip", "dip", "ip") or kind_of(j) == "tmp":
                r["hinge"][j.bone] = {"side_over_10": int((np.abs(ang[j.bone][1]) > 10).sum()),
                                      "twist_over_15": int((np.abs(ang[j.bone][2]) > 15).sum())}
        for f, js in chains(hand).items():
            if f == THUMB or "pip" not in js:
                continue
            pip, dip = ang[js["pip"].bone][0], ang[js["dip"].bone][0]
            bent = pip > 30.0
            ratio = dip[bent] / pip[bent]
            r["coupling"][f] = {"dip_over_pip": stats(ratio), "under_0.3": int((ratio < 0.3).sum()),
                                "over_1.3": int((ratio > 1.3).sum())}
        sums = finger_sums(hand, ang)
        rel = relaxedness(hand, ang)
        if sums and rel is not None:
            s = np.stack([sums[f] for f in LONG if f in sums])
            op = rel > 0.5
            order_ok = np.all(np.diff(s, axis=0) >= -2.0, axis=0)
            r["open_hand"] = {"frames": int(op.sum()), "cascade_share": _r(order_ok[op].mean(), 3) if op.any() else None,
                              "spread_p50": _r(np.median((s.max(axis=0) - s.min(axis=0))[op])) if op.any() else None,
                              "within_10_share": _r(((s.max(axis=0) - s.min(axis=0)) < 10)[op].mean(), 3) if op.any() else None}
        step = np.zeros(len(next(iter(ang.values()))[0]) - 1)
        steps = {}
        for j in hand.joints:
            q = loc[j.bone]
            st = np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(q[1:] * q[:-1], axis=1)), 0, 1)))
            step = np.maximum(step, st)
            steps[j.bone] = {"p99": _r(np.percentile(st, 99)), "max": _r(st.max())}
        r["steps_deg_per_frame"] = steps
        speed = []
        lags = []
        for f, js in chains(hand).items():
            if f == THUMB:
                continue
            sig = sums[f]
            sp = np.abs(np.diff(sig)) * FPS
            speed.append(sp)
            pip, dip = ang[js["pip"].bone][0], ang[js["dip"].bone][0]
            for a, b in shape_changes(sig):
                o_p, o_d = onset(pip, a, b), onset(dip, a, b)
                if o_p is not None and o_d is not None:
                    lags.append(o_d - o_p)
        speed = np.concatenate(speed) if speed else np.zeros(0)
        r["finger_speed_deg_s"] = {"p99": _r(np.percentile(speed, 99)) if speed.size else None,
                                   "max": _r(speed.max()) if speed.size else None,
                                   "over_1900": int((speed > SPEED_MAX_DEG_S + 1e-6).sum())}
        r["dip_after_pip_frames"] = {**stats(lags), "share_zero(<=0.1)": _r((np.abs(lags) <= 0.1).mean(), 3) if lags else None}
        if side in world:
            wrot = world[side][1]
            wsp = np.degrees(np.linalg.norm(angular_velocity(wrot, FPS), axis=1))
            wpos = world[side][0] * UNIT_M
            lsp = np.linalg.norm(np.diff(wpos, axis=0), axis=1) * FPS
            moving = (wsp > 90.0) | (lsp > 0.5)
            frozen = moving & (step < 0.05)
            rs = runs(frozen)
            r["frozen_while_hand_moves"] = {"moving_frames": int(moving.sum()), "frozen_frames": int(frozen.sum()),
                                            "share": _r(frozen.sum() / max(1, moving.sum()), 3),
                                            "longest": max([b - a + 1 for a, b in rs], default=0)}
        out[side] = r
    return out


def shape_changes(sig, min_change=20.0, still=1.0):
    """monotone runs of a finger's MP + PIP + DIP that change it by at least min_change degrees: [(start, end)]"""
    d = np.diff(sig)
    out = []
    for sgn in (1.0, -1.0):
        for a, b in runs(sgn * d > still):
            if abs(sig[b + 1] - sig[a]) >= min_change:
                out.append((a, b + 1))
    return sorted(out)


def onset(x, a, b, share=0.1):
    """the (sub-frame) time in [a, b] where x has moved `share` of its change over [a, b]; None for no change"""
    ch = x[b] - x[a]
    if abs(ch) < 5.0:
        return None
    y = (x[a:b + 1] - x[a]) / ch
    i = int(np.argmax(y >= share))
    if i == 0:
        return float(a)
    return a + i - 1 + (share - y[i - 1]) / max(y[i] - y[i - 1], 1e-9)


def change(hands, ang_in, ang_out, held):
    """how far the layer moved each joint's flexion (degrees): everywhere, and where the hand holds a shape that is not
    an open hand (held > 0.5) and the input's fingers are still (the choreography's shapes)"""
    out = {}
    for side, hand in hands.items():
        rows = {}
        h = held[side] > 0.5
        for j in hand.joints:
            d = ang_out[j.bone][0] - ang_in[j.bone][0]
            still = np.concatenate([[True], np.abs(np.diff(ang_in[j.bone][0])) < 0.05])
            rows[j.bone] = {"all": stats(np.abs(d)), "held_still": stats(np.abs(d[h & still]))}
        out[side] = rows
    return out
