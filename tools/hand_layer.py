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
    at frame 0, the forcing [F, J] (rad/s^2) taken as linear between frames; semi-implicit Euler, `substeps` per frame"""
    forcing = np.asarray(forcing, dtype=float)
    F, J = forcing.shape
    w, z = np.asarray(omega, dtype=float), np.asarray(zeta, dtype=float)
    dt = 1.0 / (fps * substeps)
    d, v = np.zeros(J), np.zeros(J)
    out = np.zeros((F, J))
    for t in range(1, F):
        a0, a1 = forcing[t - 1], forcing[t]
        for k in range(substeps):
            f = a0 + (a1 - a0) * ((k + 1) / substeps)
            v = v + dt * (f - 2.0 * z * w * v - w * w * d)
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


def joint_forcing(alpha, acc, axis, e, r, rho, gravity=True):
    """the forcing (rad/s^2) on a joint's flexion from the motion of the frame it hangs in: the hand's world angular
    acceleration alpha [F, 3] about the joint's world flexion axis [F, 3], and the joint's world linear acceleration acc
    [F, 3] (m/s^2; gravity taken away when asked) on the part beyond it, its centre of mass r metres out along the unit
    direction e [F, 3], its radius of gyration about that centre rho: -(alpha . axis) - r / (r^2 + rho^2) (e x (acc - g))
    . axis.  Positive bends the part toward the palm (flexion)."""
    a = np.asarray(acc, dtype=float) - (GRAVITY if gravity else 0.0)
    return -dot(alpha, axis) - (r / (r * r + rho * rho)) * dot(np.cross(e, a), axis)
