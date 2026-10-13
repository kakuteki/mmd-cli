"""Bake anatomical hands onto a dance: the fingers' joints bend as hinges within their range, the DIP follows the PIP,
a finger pulls its neighbours a little, an open hand relaxes into the cascade and follows the wrist, no finger turns
faster than a hand can, the DIP moves just after the PIP, and the fingers lag the hand's motion and run on a little
when it stops.  The choreography's shapes (a pointing finger, a peace sign, a fist) stay.

    python tools/hand_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--no-STEP ...] [--relax-gain 1]
                               [--speed-max 1900] [--order-scale 1] [--order-max 1.5]
                               [--gravity] [--verbose]

Why (the audit of 2026-10-13, _spike/out/stage6/hands/NOTES.md and audit/): in the v7 dance the fingers hold dead still
while the hand swings (66 to 72 % of the frames where the wrist turns faster than 90 deg/s or the knuckles move faster
than 0.5 m/s, for up to 87 frames), every finger and every joint of a finger starts a shape change on the same frame
(90 to 99 %), a change can turn a finger 115 degrees in one frame (3,470 deg/s; a hand at full speed opens and closes at
1,350 to 1,450 deg/s, Date 2021), the open hand is flat (the four fingers within 10 degrees of each other on 77 to 88 %
of its frames), the ring finger's DIP stays straight under a PIP bent 45 to 100 degrees (359 / 851 frames) while the
middle finger's DIP bends up to 1.7 times its PIP (to 116 degrees), and the index finger's PIP bends sideways by up to
22 degrees and twists by 45 (a pinch made at the PIP instead of the MP).

The joints are read in the hand's own frame (read_joint; the model's bones at rest give each joint's axes): the long
fingers' MP, PIP and DIP bend toward the palm's normal (the side the fingers fold to), their side angle is positive
toward the thumb, their twist is about the segment; the thumb's MP and IP bend toward the pulp (the thumbnail's normal,
read from the mesh: pulp_from_mesh), and its CMC reads the metacarpal against the index metacarpal (JOA: radial
abduction in the palm's plane, palmar abduction out of it).  The angles are taken against the rest pose (Sour's Rin's
rest fingers look straight in the renders although their bones read DIP -13 and IP -17 degrees), the CMC absolutely.

The steps (STEPS, each can be switched off), in this order:

1. hinge: PIP, DIP and the thumb's MP and IP are hinges: their sideways bend and twist are eased (the soft limit of
   tools/anatomy_layer.py: identity under the start, saturating toward the cap) from 3 to 8 and from 5 to 12 degrees.
   (The thumb's MP has a second, small axis, Hollister 1995; it is held to the same band here.)
2. reach: the hinges and the coupling undo shapes the trace made at the wrong joint (the thumbs of a heart bent 41
   degrees sideways at the MP, a pinch made at the index's PIP, a fist hooked at the DIP); each finger is fitted back
   to the input's outline (its outer joints and its tip, in the hand) by the joints that can move that way: a long
   finger's MP (flexion, sideways) and its PIP with the DIP inside the coupling's band, the thumb's CMC (radial and
   palmar abduction) and its MP and IP flexion; angles past the soft start of their range cost (REACH).  What the
   range cannot give stays lost: the heart's thumb tip ends some 10 mm from the trace's.
3. coupling: the deep flexor and the oblique retinacular ligament tie the DIP to the PIP (Leijnse 1997: one degree of
   freedom; DIP / PIP 0.76 Hahn 1995, 0.75-0.77 and the little finger 0.57 Mentzel 2011, 0.16-0.36 in a light grasp
   Kamper 2003, "the linkage varies greatly"): where the PIP bends (fully from 40 degrees, faded in from 20) the DIP is
   kept between 0.3 and 1.0 times the PIP by a soft wall 4 degrees inside the band (after reach, it catches what the
   fit left outside).
4. enslave: a finger's MP is pulled toward its neighbours' by 0.05 of their difference (the adjacent fingers' passive
   coupling; Lang & Schieber 2004: 4 to 16 % of the moved finger's motion in the others, mostly the adjacent MCP).
5. relax: an open hand (the long fingers' mean MP + PIP + DIP at most 30 degrees, fading out by 70, none above 90)
   leans by --relax-gain (0.25) toward the relaxed hand held in the air (Varghese 2020, the wrist 15 - 20 degrees
   extended: MCP 26-33, PIP 39-45, DIP 14-16, the index the least bent) moved with the wrist by the tenodesis (MP
   0.30, PIP 0.43, DIP 0.16 degrees per degree of wrist extension, Su 2005; it acts on relaxed fingers only).
6. order: within each change of a finger's shape its joints move out of step, by shares of the change's length
   (Carpinella 2011: closing a fist the MCP's speed peaks 11.4 % after the PIP's, opening the hand the PIP's 7.4 %
   after the MCP's; the DIP follows the PIP, Mentzel 2011), at most --order-max frames; holds are untouched.  The fingers
   are not staggered against each other: in a grasp the MCPs follow one time course (Santello 2002).
7. passive: each finger is a body turning at its MP (the thumb at its MP) on a spring and a damper, driven by the
   hand's world angular acceleration about the joint's axis and the joint's world linear acceleration (finger_body,
   joint_forcing, passive_response).  The masses are Martin 2013's segments (via the research's cylinders), scaled to
   Rin's fingers (about 0.58 of a grown man's); the stiffness 1.0 N m/rad for a held shape (a finger stroking a
   surface, Kry & Pai 2006; 2 to 5 times a relaxed one, Milner & Franklin 1998) and 0.21 for the open hand (the upper
   end of a relaxed MCP, Kuo & Deshpande 2012), scaled as s^3; damping ratio 0.85 (no swing back: the hand CG of
   Pollard & Zordan 2005 damps past critical, a pressed fingertip 0.83-1.15).  The lag goes to the MP, 0.35 of it to
   the PIP and 0.2 to the DIP (the thumb's MP and half to its IP), eased from 4 toward 10 degrees (purposeful
   movements keep the distal joints' passive motion to a few degrees: Koshland 2000, Hore).  Gravity is left out by
   default: the shape a dancer shows is held against it.
8. speed: a finger whose MP + PIP + DIP turns faster than --speed-max (1,900 deg/s: Date 2021's young adults, mean + 2
   SD of the fingertip's angular velocity in fast grip and release) is spread round the middle of its change (a
   centred box average, wide only there), so the change keeps its time; last of the timing steps, so that what the
   order and the lag add is held to the speed too.
9. rom: last, once (the soft limit is not idempotent), every joint is eased into its range (ROM, against the rest pose:
   the active means of Mohamed Ibrahim 2024 and the Japanese reference for the starts, mean + 2 SD or the reference +
   10 for the caps).

Not done here (the fingers' delay against the wrist is the arm chain's timing, tools/motor_layer.py's finger_delay; the
wrist's range is tools/anatomy_layer.py's): measured in the report only, the wrist outside its circumduction ellipse
(Gracia-Ibanez 2020) and, in a fist, beyond the fist's smaller palmar flexion and ulnar deviation (Gehrmann 2008).

Everything else (the arms, the wrists, the trunk, the legs, every morph) is copied byte for byte; a joint's bone gets a
key on every frame (the linear curve, the physics bytes of the input's key in force), its key position kept.

The report (--report; in short on stdout) measures the input and the output alike: the range of motion (frames beyond
the start and the cap), the hinges' sideways bend and twist, DIP / PIP, the open hand's cascade, the largest steps, the
fingers' speed, the DIP's onset after the PIP's, the fingers held dead still while the hand moves, the wrist; and how
far each joint moved (everywhere, and in the held shapes away from their changes), how far each finger left the
choreography's place in the hand (shape: its outer joints and tip, mm; "static" is the shape of each frame before the
timing steps, "output" the output), the steps' own figures (the fit's distances before and after, the passive lag per
finger, its frequencies).
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time
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
    at frame 0, the forcing [F, J] (rad/s^2) taken as linear between frames.  omega and zeta are [J] or, changing with
    time, [F, J] (the frame's own values through its interval).  Implicit Euler (stable however stiff), at least
    `substeps` steps a frame and more where the stiffest joint's omega dt would pass 0.25 (the step's own damping
    stays small): v' = (v + dt (f - omega^2 d)) / (1 + 2 zeta omega dt + omega^2 dt^2), d' = d + dt v'"""
    forcing = np.asarray(forcing, dtype=float)
    F, J = forcing.shape
    w = np.broadcast_to(np.asarray(omega, dtype=float), (F, J))
    z = np.broadcast_to(np.asarray(zeta, dtype=float), (F, J))
    n = max(int(substeps), int(math.ceil(float(w.max(initial=0.0)) / (fps * 0.25))))
    dt = 1.0 / (fps * n)
    d, v = np.zeros(J), np.zeros(J)
    out = np.zeros((F, J))
    for t in range(1, F):
        a0, a1 = forcing[t - 1], forcing[t]
        wt, zt = w[t], z[t]
        den = 1.0 + 2.0 * zt * wt * dt + wt * wt * dt * dt
        for k in range(n):
            f = a0 + (a1 - a0) * ((k + 1) / n)
            v = (v + dt * (f - wt * wt * d)) / den
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
STEPS = ("hinge", "reach", "coupling", "enslave", "relax", "order", "passive", "speed", "rom")
# the hinge joints (PIP, DIP, the thumb's IP and MP) bend in one plane: their sideways bend and their twist, read from
# the rest pose, eased from the start toward the cap (degrees)
HINGE = {"side": (3.0, 8.0), "twist": (5.0, 12.0)}
# DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high
COUPLING = {"low": 0.3, "high": 1.0, "from": 20.0, "full": 40.0}
COUPLING_SOFT = 4.0              # degrees inside the band where the wall starts
# each long finger's MP is pulled toward each neighbour's MP by this share of their difference (the adjacent fingers'
# passive coupling)
ENSLAVE = 0.05
# the range of motion against the rest pose (the thumb's CMC: radial and palmar abduction against the index
# metacarpal, read absolutely): (soft start, cap) for each way, degrees
ROM = {
    "mp": {"flex": ((25.0, 40.0), (90.0, 100.0)), "side": ((25.0, 35.0), (25.0, 35.0)), "twist": ((15.0, 25.0), (15.0, 25.0))},
    "pip": {"flex": ((10.0, 25.0), (100.0, 110.0))},
    "dip": {"flex": ((10.0, 20.0), (80.0, 90.0))},
    "cmc": {"flex": ((10.0, 20.0), (60.0, 65.0)), "side": ((15.0, 25.0), (90.0, 95.0)), "twist": ((25.0, 35.0), (25.0, 35.0))},
    "tmp": {"flex": ((10.0, 25.0), (60.0, 65.0))},
    "ip": {"flex": ((15.0, 30.0), (80.0, 90.0))},
}
SPEED_MAX_DEG_S = 1900.0         # a finger's MP + PIP + DIP together, degrees per second
# the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most
# ORDER_MAX): closing, the MCP's speed peaks 11.4 % after the PIP's (Carpinella 2011) and the DIP follows the PIP
# (Mentzel 2011; the 10 % is ours); opening, the PIP peaks 7.4 % after the MCP (Carpinella 2011) and the DIP moves with
# the PIP.  --order-scale multiplies them
ORDER = {"close": {"mp": 0.114, "pip": 0.0, "dip": 0.10}, "open": {"mp": 0.0, "pip": 0.074, "dip": 0.074}}
ORDER_MAX = 1.5
ORDER_SPEED = 60.0               # degrees per second of a finger's MP + PIP + DIP: it is changing its shape
# the relaxed hand: an open hand (the four fingers' mean MP + PIP + DIP under OPEN[0], none over OPEN[2]) is relaxed
# (fully at OPEN[0], not at all from OPEN[1]); it leans by RELAX_GAIN toward the relaxed hand held in the air with the
# wrist 15 - 20 degrees extended (Varghese 2020: office workers' dominant hands, MCP, PIP, DIP), moved with the wrist by
# the tenodesis (Su 2005: degrees per degree of wrist extension) from that 17.5 degrees
OPEN = (30.0, 70.0, 90.0)
RELAXED_AIR = {"人指": (27.1, 38.7, 13.8), "中指": (33.2, 40.7, 14.2), "薬指": (29.3, 44.8, 14.3), "小指": (26.2, 43.1, 16.1)}
RELAXED_WRIST = 17.5
TENODESIS = {"mp": 0.30, "pip": 0.43, "dip": 0.16}
RELAX_GAIN = 0.25
# the passive lag: one body per finger turning at its MP (the thumb at its MP) against a spring and a damper
SEGMENT_MASS = {"人指": (19.1, 8.1, 6.0), "中指": (20.0, 9.6, 6.5), "薬指": (17.0, 8.9, 5.5), "小指": (10.8, 5.3, 4.3),
                "親指": (12.0, 6.0)}
REF_LENGTH_M = {"人指": 0.099, "中指": 0.109, "薬指": 0.102, "小指": 0.082, "親指": 0.06}
REF_INERTIA = {"人指": 9.5e-5, "中指": 1.26e-4, "薬指": 9.9e-5, "小指": 4.6e-5, "親指": 4.0e-5}
# N m/rad at the MP of a grown finger: a held shape (a finger stroking a surface, Kry & Pai 2006: about 1.0; a held
# finger is 2 to 5 times the relaxed one, Milner & Franklin 1998) and the open hand (the upper end of a relaxed MCP,
# Kuo & Deshpande 2012)
STIFFNESS = {"held": 1.0, "open": 0.21}
# the damping ratio: a dancer's fingers trail and catch up without swinging back (a pressed fingertip 0.83 - 1.15,
# Kry & Pai 2006, Hajian & Howe 1997; the physical hands of the CG damp past critical, Pollard & Zordan 2005 about 1.7)
ZETA = {"held": 0.85, "open": 0.85}
PASSIVE_SHARE = {"mp": 1.0, "pip": 0.35, "dip": 0.2, "tmp": 1.0, "ip": 0.5}
PASSIVE_CAP = (4.0, 10.0)                           # degrees: the lag is eased from the start toward the cap
ACC_SMOOTH = 1                                      # frames each way of the triangle that smooths the accelerations
# the active circumduction of the wrist as an ellipse (Gracia-Ibanez 2020, dominant hand): x radial (+) / ulnar
# deviation, y palmar flexion (+) / extension, degrees: the centre, the half axes (across, along) and the long axis's
# tilt from the flexion-extension line toward the dart thrower's line (radial extension <-> ulnar flexion)
WRIST_ELLIPSE = {"centre": (-8.2, -1.8), "half_axes": (35.0, 73.2), "tilt_deg": 13.2}
# a fist takes away palmar flexion and ulnar deviation (Gehrmann 2008: 0.73 and 0.89 of the free hand's); the free
# hand's active palmar flexion and ulnar deviation (Gracia-Ibanez 2020, table 1)
FIST_WRIST = {"flexion": 0.73 * 77.6, "ulnar": 0.89 * 33.4}
# where the hand touches the face, the body or the other arm and hand, the relaxed curl and the passive lag are left
# out (what the fingers touch holds them; Varghese 2020 and Su 2005 measured free, relaxed fingers): a fingertip within
# the first distance (mm) of the eyes, of the line 上半身 - 首 (motor_layer's contact), of the line from the hips to 下半身,
# of the other forearm or hand, fully; none past the second.  Padded by CONTACT_PAD frames each way
CONTACT_MM = {"face": (70.0, 100.0), "chest": (60.0, 90.0), "waist": (80.0, 110.0), "other": (35.0, 60.0)}
CONTACT_PAD = 4


def default_params():
    p = {s: True for s in STEPS}
    p["contact"] = True
    p.update(relax_gain=RELAX_GAIN, speed_max=SPEED_MAX_DEG_S, order_max=ORDER_MAX, order_scale=1.0, gravity=False,
             stiffness=dict(STIFFNESS), zeta=dict(ZETA), passive_cap=PASSIVE_CAP, enslave_share=ENSLAVE)
    return p


def wrist_inside(radial, flex):
    """True where the wrist (radial deviation, palmar flexion; degrees, arrays) lies within WRIST_ELLIPSE"""
    cx, cy = WRIST_ELLIPSE["centre"]
    a, b = WRIST_ELLIPSE["half_axes"]
    t = math.radians(WRIST_ELLIPSE["tilt_deg"])
    x, y = np.asarray(radial, dtype=float) - cx, np.asarray(flex, dtype=float) - cy
    along = -math.sin(t) * x + math.cos(t) * y        # the long axis points to ulnar flexion
    across = math.cos(t) * x + math.sin(t) * y
    return (along / b) ** 2 + (across / a) ** 2 <= 1.0


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
            # a soft wall inside the band (the soft limit's form): a DIP more than COUPLING_SOFT degrees inside the band
            # is left, one beyond it saturates toward the band's edge and never passes it
            new = -soft_limit(-dip, -(lo + COUPLING_SOFT), -lo)
            new = soft_limit(new, hi - COUPLING_SOFT, hi)
            ang[js["dip"].bone][0] = dip + w * (new - dip)


def enslave(hands, ang, k):
    """each long finger's MP flexion moved toward each adjacent finger's by k times their difference (computed from
    the angles before the step, so the fingers pull on each other at once)"""
    for hand in hands.values():
        cs = chains(hand)
        order_ = [f for f in LONG if f in cs and "mp" in cs[f]]
        before = {f: ang[cs[f]["mp"].bone][0].copy() for f in order_}
        for i, f in enumerate(order_):
            pull = np.zeros_like(before[f])
            for g in order_[max(0, i - 1):i] + order_[i + 1:i + 2]:
                pull = pull + k * (before[g] - before[f])
            ang[cs[f]["mp"].bone][0] = before[f] + pull


def rom(hands, ang):
    """every joint's angles eased into its range (ROM: soft start, cap; identity below the start)"""
    for hand in hands.values():
        for j in hand.joints:
            lim = ROM[kind_of(j)]
            for i, way in enumerate(("flex", "side", "twist")):
                if way in lim:
                    low, high = lim[way]
                    ang[j.bone][i] = soft_band(ang[j.bone][i], low, high)


# ---- step 1b: the finger where the choreography put it -----------------------------------------------------------

# the hinges and the coupling undo a shape the trace made at the wrong joint (the thumbs of a heart bent sideways at
# their MP, a pinch made at the index's PIP, a fist hooked at the DIP); the finger goes back to the input's outline,
# carried by the joints that can move that way: a long finger's MP (flexion and sideways) and its PIP with the DIP in
# the coupling's band, the thumb's CMC (radial and palmar abduction) and its MP and IP (flexion).  A least-squares fit
# per frame (Gauss-Newton, the Jacobian by central differences, a step kept only where it lowers the cost): the
# distances of the finger's joints and tip from the input's (mm), each free angle's change from the hinged shape (reg
# mm per degree: among equal fits the smallest change), the DIP past the soft wall of the band (band mm per degree,
# where the input's PIP bends: the band does not let go when the fit opens the PIP) and an angle past the soft start
# of its range (rom mm per degree; the cap is the last step's)
REACH = {"reg": 0.05, "band": 5.0, "rom": 1.0, "iterations": 16, "step_max": 15.0, "h": 0.01, "damping": 1e-6}
MM_PER_UNIT = UNIT_M * 1000.0


def reach_chain(hand, finger):
    """the finger's three joints from the base outward (the thumb: CMC, MP, IP), or None"""
    js = chains(hand).get(finger, {})
    kinds = ("cmc", "mp", "ip") if finger == THUMB else ("mp", "pip", "dip")
    return [js[k] for k in kinds] if all(k in js for k in kinds) else None


def chain_points(seq, rows):
    """[F, n, 3] the far end of each joint's segment (the next joints and the fingertip) from the chain's first joint,
    in the frame of that joint's parent (model units); rows: bone -> [3, F] the angles as the layer keeps them
    (rest-relative, the CMC absolutely)"""
    R, p, out = None, 0.0, []
    for j in seq:
        f, s, t = rows[j.bone]
        if j.kind != "cmc":
            f, s = f + j.rest[0], s + j.rest[1]
        q = compose_joint(j, f, s, t)
        R = q if R is None else qmul(R, q)
        p = p + qrot(R, j.d * j.length)
        out.append(p)
    return np.stack(out, axis=1)


def reach(hands, ang, ang_in, band=True, limits=True):
    """each finger brought back toward the input's outline (REACH); band: keep the DIP in the coupling's band, limits:
    the angles under the soft starts of their range.  Returns side -> finger -> the mean distance of the finger's
    joints and tip from the input's before and after (mm), the tip's after, and the frames where a free angle moved
    more than 1 degree"""
    report = {}
    for side, hand in hands.items():
        rep = {}
        for finger in LONG + (THUMB,):
            seq = reach_chain(hand, finger)
            if seq is None:
                continue
            free = [(seq[0], 0), (seq[0], 1), (seq[1], 0), (seq[2], 0)]
            target = chain_points(seq, {j.bone: ang_in[j.bone] for j in seq})
            fixed = {j.bone: ang[j.bone].copy() for j in seq}
            x0 = np.stack([fixed[j.bone][i] for j, i in free], axis=1)
            w_band = smoothstep(x0[:, 2], COUPLING["from"], COUPLING["full"]) * REACH["band"]
            bounds = []
            for j, i in free:
                lim = ROM[kind_of(j)].get(("flex", "side")[i])
                bounds.append(None if lim is None else (lim[0][0], lim[1][0]))

            def residual(x):
                rows = {b: a.copy() for b, a in fixed.items()}
                for c, (j, i) in enumerate(free):
                    rows[j.bone][i] = x[:, c]
                d = (chain_points(seq, rows) - target) * MM_PER_UNIT
                r = [d.reshape(len(x), -1), (x - x0) * REACH["reg"]]
                if band and finger != THUMB:
                    pip, dip = x[:, 2], x[:, 3]
                    r.append((w_band * np.maximum(dip - (COUPLING["high"] * pip - COUPLING_SOFT), 0.0))[:, None])
                    r.append((w_band * np.maximum((COUPLING["low"] * pip + COUPLING_SOFT) - dip, 0.0))[:, None])
                if limits:
                    for c, b in enumerate(bounds):
                        if b is not None:
                            r.append(REACH["rom"] * np.maximum(x[:, c] - b[1], 0.0)[:, None])
                            r.append(REACH["rom"] * np.maximum(-b[0] - x[:, c], 0.0)[:, None])
                return np.concatenate(r, axis=1)

            def outline(rows):
                d = np.linalg.norm(chain_points(seq, rows) - target, axis=2) * MM_PER_UNIT
                return d.mean(axis=1), d[:, -1]

            x = x0.copy()
            n = x.shape[1]
            res = residual(x)
            cost = np.sum(res * res, axis=1)
            before = outline(fixed)[0]
            for _ in range(REACH["iterations"]):
                J = np.empty(res.shape + (n,))
                for c in range(n):
                    e = np.zeros(n)
                    e[c] = REACH["h"]
                    J[:, :, c] = (residual(x + e) - residual(x - e)) / (2.0 * REACH["h"])
                JTJ = np.einsum("fmi,fmj->fij", J, J) + REACH["damping"] * np.eye(n)
                g = np.einsum("fmi,fm->fi", J, res)
                dx = np.clip(-np.linalg.solve(JTJ, g[..., None])[..., 0], -REACH["step_max"], REACH["step_max"])
                moved = False
                for scale in (1.0, 0.5, 0.25):
                    trial = x + scale * dx
                    r_t = residual(trial)
                    c_t = np.sum(r_t * r_t, axis=1)
                    better = c_t < cost - 1e-12
                    if better.any():
                        x = np.where(better[:, None], trial, x)
                        res = np.where(better[:, None], r_t, res)
                        cost = np.where(better, c_t, cost)
                        dx = np.where(better[:, None], 0.0, dx)
                        moved = True
                    if not np.abs(dx).max() > 1e-6:
                        break
                if not moved:
                    break
            for c, (j, i) in enumerate(free):
                ang[j.bone][i] = x[:, c]
            after, tip = outline({j.bone: ang[j.bone] for j in seq})
            rep[finger] = {"outline_mm_before": stats(before), "outline_mm_after": stats(after), "tip_mm_after": stats(tip),
                           "moved_frames": int((np.abs(x - x0).max(axis=1) > 1.0).sum())}
        report[side] = rep
    return report


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


def relax(hands, ang, wrist_ext, gain, touch=None):
    """the relaxed hand: each joint of a relaxed hand leans toward the relaxed hand in the air at the wrist's angle,
    flexion += gain x r x (RELAXED_AIR + TENODESIS x (wrist extension - RELAXED_WRIST) - flexion); touch: side -> 0 .. 1,
    the hand on something (contact_weights), where it does not lean"""
    out = {}
    for side, hand in hands.items():
        r = relaxedness(hand, ang)
        if r is None:
            continue
        if touch is not None and side in touch:
            r = r * (1.0 - touch[side])
        w = wrist_ext[side]
        for f, js in chains(hand).items():
            if f == THUMB or f not in RELAXED_AIR:
                continue
            for i, k in enumerate(("mp", "pip", "dip")):
                cur = ang[js[k].bone][0]
                target = RELAXED_AIR[f][i] + TENODESIS[k] * (w - RELAXED_WRIST)
                ang[js[k].bone][0] = cur + gain * r * (target - cur)
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


def order(hands, ang, longest, scale=1.0):
    """the joints of each long finger moved out of step within each change of its shape (a run where its MP + PIP +
    DIP closes, or opens, faster than ORDER_SPEED; a turn of the way starts a new change): every joint is read lag
    frames earlier, lag = ORDER[closing or opening][joint] x scale x the change's length in frames (at most `longest`),
    faded in and out over the change; holds are untouched"""
    report = {"changes": 0}
    for hand in hands.values():
        for f, js in chains(hand).items():
            if f == THUMB or not all(k in js for k in ("mp", "pip", "dip")):
                continue
            bones = {k: ang[js[k].bone] for k in ("mp", "pip", "dip")}
            s = sum(b[0] for b in bones.values())
            speed = np.gradient(s) * FPS
            lags = {k: np.zeros(len(s)) for k in bones}
            # a change closes or opens the finger: a hand that opens and at once closes again makes two changes, each
            # with its own way and length (cut where the way turns, as the measures' shape_changes cut)
            changes = [(a, b, "close") for a, b in runs(speed > ORDER_SPEED)] + \
                      [(a, b, "open") for a, b in runs(speed < -ORDER_SPEED)]
            for a, b, way in sorted(changes):
                n = b - a + 1
                report["changes"] += 1
                for k in bones:
                    lam = min(longest, ORDER[way][k] * scale * n)
                    if lam <= 0.0:
                        continue
                    # the lag held through the change and ramped in and out over ceil(lam) + 1 frames each side
                    reach = int(np.ceil(lam)) + 1
                    lo, hi = max(0, a - reach), min(len(s), b + reach + 1)
                    t = np.arange(lo, hi)
                    w = np.minimum(1.0, np.minimum(t - (a - reach), (b + reach) - t) / reach)
                    lags[k][lo:hi] = np.maximum(lags[k][lo:hi], lam * np.clip(w, 0.0, 1.0))
            for k, arr in bones.items():
                if lags[k].any():
                    for i in range(3):
                        arr[i] = time_shift(arr[i], lags[k])
    return report


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
        zeta[state] = params["zeta"][state]
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


def passive(hands, ang, loc, world, P, params, held, touch=None):
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
        if touch is not None and side in touch:
            delta = delta * (1.0 - touch[side])[:, None]
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


def contact_weights(model, motion, F, sides):
    """side -> 0 .. 1 per frame: a fingertip of the hand at the face, the chest, the waist or the other forearm and hand
    (CONTACT_MM, from the bones' positions under the input), padded by CONTACT_PAD frames and smoothed over 5"""
    P = _positions(model)
    tips = {s: [s + f + "３先" for f in LONG if s + f + "３先" in P] for s in sides}
    eyes = [n for n in ("左目", "右目") if n in P] or [n for n in ("頭",) if n in P]
    chest = ["上半身", "首"] if all(n in P for n in ("上半身", "首")) else []
    hips = [n for n in ("左足", "右足") if n in P] if "下半身" in P else []
    names = set(eyes) | set(chest) | set(hips) | ({"下半身"} if hips else set())
    for s in sides:
        names |= set(tips[s]) | {s + n for n in ("ひじ", "手首", "中指１") if s + n in P}
    out = {s: np.zeros(F) for s in sides}
    if not names:
        return out
    pose = fk.Pose(model, motion, sorted(names))
    W = {n: np.zeros((F, 3)) for n in names}
    for f in range(F):
        at = pose.at(f)
        for n in names:
            W[n][f] = at[n][0]
    mm = UNIT_M * 1000.0

    def to_line(p, a, b):
        ab = b - a
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
        return np.linalg.norm(p - (a + t[:, None] * ab), axis=1) * mm

    for s in sides:
        o = "右" if s == "左" else "左"
        c = np.zeros(F)
        for t in tips[s]:
            p = W[t]
            if eyes:
                c = np.maximum(c, 1.0 - smoothstep(np.linalg.norm(p - np.mean([W[e] for e in eyes], axis=0), axis=1) * mm,
                                                   *CONTACT_MM["face"]))
            if chest:
                c = np.maximum(c, 1.0 - smoothstep(to_line(p, W["上半身"], W["首"]), *CONTACT_MM["chest"]))
            if hips:
                c = np.maximum(c, 1.0 - smoothstep(to_line(p, np.mean([W[h] for h in hips], axis=0), W["下半身"]),
                                                   *CONTACT_MM["waist"]))
            for a, b in ((o + "ひじ", o + "手首"), (o + "手首", o + "中指１")):
                if a in W and b in W:
                    c = np.maximum(c, 1.0 - smoothstep(to_line(p, W[a], W[b]), *CONTACT_MM["other"]))
        padded = c.copy()
        for k in range(1, CONTACT_PAD + 1):
            padded[k:] = np.maximum(padded[k:], c[:-k])
            padded[:-k] = np.maximum(padded[:-k], c[k:])
        out[s] = np.convolve(np.pad(padded, 2, mode="edge"), np.ones(5) / 5.0, mode="valid")
    return out


def wrist_angles(model, loc, F):
    """side -> (palmar flexion, radial deviation) of the hand against the forearm (degrees, as
    tools/anatomy_layer.arm_angles reads them) from 手捩 and 手首's locals, or None where the model has no arm"""
    out = {}
    try:
        sides = A.rest_sides(model)
    except ValueError:
        sides = {}
    for side, _ in SIDES:
        S = sides.get(side)
        if S is None or side + "手捩" not in loc or side + "手首" not in loc:
            out[side] = None
            continue
        qf = qmul(loc[side + "手捩"], loc[side + "手首"])
        tf = twist(qf, S.d_f)
        s_loc = qmul(qconj(aa(S.d_f, tf)), qf)
        ch = qrot(s_loc, S.d_h)
        mh = unit(S.n - (S.n @ S.d_h) * S.d_h)
        k = np.cross(S.d_h, mh)
        flex = np.degrees(np.arctan2(ch @ mh, ch @ S.d_h))
        radial = np.degrees(np.arcsin(np.clip(ch @ k, -1, 1))) * np.sign(k @ S.r)
        out[side] = (flex, radial)
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
    if p["reach"]:
        report["steps"]["reach"] = reach(hands, ang, ang_in, band=p["coupling"], limits=p["rom"])
    if p["coupling"]:
        coupling(hands, ang)
    if p["enslave"]:
        enslave(hands, ang, p["enslave_share"])
    relaxed = {s: relaxedness(h, ang) for s, h in hands.items()}
    held = {s: (1.0 - r) if r is not None else np.ones(F) for s, r in relaxed.items()}
    wrist = wrist_angles(model, loc, F)
    touch = None
    if p.get("contact", True) and (p["relax"] or p["passive"]):
        touch = contact_weights(model, motion, F, [s for s in hands])
        report["steps"]["contact_frames"] = {s: int((c > 0.5).sum()) for s, c in touch.items()}
    if p["relax"]:
        ext = {s: (-w[0] if w is not None else np.zeros(F)) for s, w in wrist.items()}
        report["steps"]["relax_frames"] = {s: int((r > 0.5).sum()) for s, r in
                                           relax(hands, ang, ext, p["relax_gain"], touch).items()}
    # the shape the layer holds in each frame (the timing steps below move it in time): measured with the range applied
    static = {b: a.copy() for b, a in ang.items()}
    if p["rom"]:
        rom(hands, static)
    if p["order"]:
        report["steps"]["order"] = order(hands, ang, p["order_max"], p["order_scale"])
    sides = [s for s, _ in SIDES if s + "手首" in P and s in hands]
    world = hand_world(model, motion, F, sides) if sides else {}
    if p["passive"]:
        report["steps"]["passive"] = passive(hands, ang, loc, world, P, p, held, touch)
    if p["speed"]:
        # after the lag and the order, so that what they add is held to the speed too
        report["steps"]["speed_spread_steps"] = speed_limit(hands, ang, p["speed_max"])
    if p["rom"]:
        rom(hands, ang)               # once, last: the soft limit is not idempotent
    out_loc = compose_all(hands, ang)
    out_motion = A.build(motion, None, out_loc, {b: keypos[b] for b in out_loc}, F)
    report["untouched"] = untouched(motion, out_motion, out_motion.labels)
    report["input"] = measure(hands, ang_in, loc, world, P, wrist)
    report["output"] = measure(hands, ang, out_loc, world, P, wrist)
    report["change"] = change(hands, ang_in, ang, held)
    report["shape"] = {"static": shape_shift(hands, ang_in, static, held), "output": shape_shift(hands, ang_in, ang, held)}
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

def measure(hands, ang, loc, world, P, wrist=None):
    """per side: the range of motion (frames beyond the start and the cap, each way), the hinge joints' sideways bend
    and twist, DIP / PIP, the open hand's cascade, the largest steps, the shape changes' speed and the DIP's onset
    after the PIP's, the fingers held dead still while the hand moves, and the wrist (outside its circumduction
    ellipse; in a fist, beyond the fist's palmar flexion and ulnar deviation; the direction of its motion)"""
    out = {}
    for side, hand in hands.items():
        r = {"rom": {}, "hinge": {}, "coupling": {}}
        w = (wrist or {}).get(side)
        if w is not None:
            flex, radial = w
            sums = finger_sums(hand, ang)
            fist = np.all(np.stack([sums[f] for f in LONG if f in sums]) > 120.0, axis=0) if sums else np.zeros(len(flex), bool)
            d_f, d_r = np.diff(flex), np.diff(radial)
            moving = np.hypot(d_f, d_r) * FPS > 30.0
            line = np.mod(np.degrees(np.arctan2(d_r[moving], -d_f[moving])), 180.0)   # 0: flexion-extension, 90: deviation
            hist, _ = np.histogram(line, bins=[0, 22.5, 67.5, 112.5, 157.5, 180])
            r["wrist"] = {"frames": int(len(flex)), "outside_ellipse": int((~wrist_inside(radial, flex)).sum()),
                          "fist_frames": int(fist.sum()),
                          "fist_beyond_flexion": int((fist & (flex > FIST_WRIST["flexion"])).sum()),
                          "fist_beyond_ulnar": int((fist & (-radial > FIST_WRIST["ulnar"])).sum()),
                          "flexion": stats(flex), "radial": stats(radial),
                          "moving_frames": int(moving.sum()),
                          "direction": {"flexion_extension": int(hist[0] + hist[4]), "dart_thrower": int(hist[1]),
                                        "deviation": int(hist[2]), "opposite_dart_thrower": int(hist[3])}}
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


HELD_REACH = 4                   # frames each way the input's joint must be still for a frame to count as a held shape


def shape_shift(hands, ang_in, ang_out, held):
    """how far each finger moved from the input's place in the hand (mm): the mean of its outer joints and tip (the
    outline) and the tip alone; everywhere, and in the held shapes away from their changes (as change())"""
    out = {}
    for side, hand in hands.items():
        h = held[side] > 0.5
        rows = {}
        for finger in LONG + (THUMB,):
            seq = reach_chain(hand, finger)
            if seq is None:
                continue
            d = np.linalg.norm(chain_points(seq, {j.bone: ang_out[j.bone] for j in seq}) -
                               chain_points(seq, {j.bone: ang_in[j.bone] for j in seq}), axis=2) * MM_PER_UNIT
            moving = np.zeros(d.shape[0], dtype=bool)
            for j in seq:
                moving[1:] |= np.abs(np.diff(ang_in[j.bone][0])) >= 0.05
            near = np.array([moving[max(0, t - HELD_REACH):t + HELD_REACH + 2].any() for t in range(len(moving))])
            keep = h & ~near
            rows[finger] = {"outline_mm": {"all": stats(d.mean(axis=1)), "held_still": stats(d.mean(axis=1)[keep])},
                            "tip_mm": {"all": stats(d[:, -1]), "held_still": stats(d[keep, -1])}}
        out[side] = rows
    return out


def change(hands, ang_in, ang_out, held):
    """how far the layer moved each joint's flexion (degrees): everywhere, and where the hand holds a shape that is not
    an open hand (held > 0.5) and the input's joint is still within HELD_REACH frames each way (the choreography's
    shapes; the frames next to a change are left out, as the speed limit spreads a change into them)"""
    out = {}
    for side, hand in hands.items():
        rows = {}
        h = held[side] > 0.5
        for j in hand.joints:
            d = ang_out[j.bone][0] - ang_in[j.bone][0]
            moving = np.concatenate([[False], np.abs(np.diff(ang_in[j.bone][0])) >= 0.05])
            near = np.array([moving[max(0, t - HELD_REACH):t + HELD_REACH + 2].any() for t in range(len(moving))])
            rows[j.bone] = {"all": stats(np.abs(d)), "held_still": stats(np.abs(d[h & ~near]))}
        out[side] = rows
    return out


# ---- the command --------------------------------------------------------------------------------------------------

def load_model(path):
    return pmd.load(path) if path.lower().endswith(".pmd") else pmx.load(path)


def short(report):
    out = {"untouched_identical": report["untouched"]["identical"]}
    for side, _ in SIDES:
        if side not in report["output"]:
            continue
        a, b = report["input"][side], report["output"][side]
        out[side] = {"frozen_share": [a.get("frozen_while_hand_moves", {}).get("share"),
                                      b.get("frozen_while_hand_moves", {}).get("share")],
                     "finger_speed_over_1900": [a["finger_speed_deg_s"]["over_1900"], b["finger_speed_deg_s"]["over_1900"]],
                     "dip_after_pip_p50": [a["dip_after_pip_frames"].get("p50"), b["dip_after_pip_frames"].get("p50")]}
    return out


def run(dance_path, model_path, out_path, report_path=None, params=None, log=None):
    started = time.time()
    A.check_distinct(dance_path, model_path, out_path, report_path)
    dance = vmd.load(dance_path)
    model = load_model(model_path)
    pulp = pulp_from_mesh(model_path) if model_path.lower().endswith(".pmx") else {}
    result = layer(model, dance, params, pulp=pulp, log=log)
    A.write_bytes(os.path.abspath(out_path), vmd.dumps(result.motion))
    report = dict({"in": os.path.abspath(dance_path), "model": os.path.abspath(model_path),
                   "out": os.path.abspath(out_path)}, **result.report)
    summary = dict({"out": os.path.abspath(out_path), "keys": len(result.motion.bones)}, **short(report))
    report["seconds"] = summary["seconds"] = _r(time.time() - started, 1)
    if report_path:
        A.write_bytes(os.path.abspath(report_path), (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        summary["report"] = os.path.abspath(report_path)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance", help="the dance motion (.vmd)")
    ap.add_argument("model", help="the model (.pmx or .pmd; a .pmx's mesh gives the thumb's pulp side)")
    ap.add_argument("out", help="the dance with the layer (.vmd)")
    ap.add_argument("--report", help="write the measures of the input and the output to this JSON")
    for s in STEPS:
        ap.add_argument("--no-" + s, action="store_true", help="leave out the step %s" % s)
    ap.add_argument("--relax-gain", type=float, default=RELAX_GAIN,
                    help="the relaxed hand's cascade and tenodesis times this (default %g)" % RELAX_GAIN)
    ap.add_argument("--speed-max", type=float, default=SPEED_MAX_DEG_S,
                    help="degrees per second of a finger's MP + PIP + DIP, past which a change is spread (default %g)"
                         % SPEED_MAX_DEG_S)
    ap.add_argument("--order-scale", type=float, default=1.0,
                    help="the joints' lags within a change of shape times this (default 1; 0 moves them together)")
    ap.add_argument("--order-max", type=float, default=ORDER_MAX,
                    help="the longest lag of a joint within a change, frames (default %g)" % ORDER_MAX)
    ap.add_argument("--no-contact", action="store_true", help="relax and lag the fingers of a hand that touches the face, "
                                                               "the body or the other arm too")
    ap.add_argument("--gravity", action="store_true", help="let gravity bend the fingers too (off: the dancer holds "
                                                            "the shape she shows against it)")
    ap.add_argument("--verbose", action="store_true", help="progress on stderr")
    a = ap.parse_args(argv)
    params = default_params()
    params.update({s: not getattr(a, "no_" + s) for s in STEPS})
    params.update(relax_gain=a.relax_gain, speed_max=a.speed_max, order_scale=a.order_scale, order_max=a.order_max,
                  gravity=a.gravity, contact=not a.no_contact)
    log = (lambda msg: print(msg, file=sys.stderr, flush=True)) if a.verbose else None
    try:
        if not a.speed_max > 0.0:
            raise ValueError("--speed-max must be above 0")
        if a.order_scale < 0.0 or a.order_max < 0.0 or a.relax_gain < 0.0:
            raise ValueError("--order-scale, --order-max and --relax-gain must not be negative")
        result = run(a.dance, a.model, a.out, a.report, params, log)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
