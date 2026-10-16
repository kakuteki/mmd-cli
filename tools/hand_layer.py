"""Bake anatomical hands onto a dance: the fingers' joints bend as hinges within their range, the DIP follows the PIP,
a finger pulls its neighbours a little, an open hand curls a little toward a relaxed hand and follows the wrist, a big
change of a finger's shape takes the time a dancer's finger takes for it, no finger turns faster than a hand can, the
joints of a finger move in their order round the change's middle, and the fingers lag the hand's motion and run on a
little when it stops, an open hand swinging back once as a relaxed finger does (not where the hand touches the face,
the body or the other arm; less where the arm stops on a beat, with --beats).  With --follow the fingers also reach each shape a little after the hand's own timing
through their own spring and damper (an open hand later than a held shape; off by default: dancers' fingers do not
trail the wrist so).  The choreography's held shapes (a pointing finger, a peace sign, a fist, a heart) keep their
fingertips within a few mm; the open hands do not: every open hand is curled alike, the stretched ones too (the report's
shape: open_still).

    python tools/hand_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--no-STEP ...] [--relax-gain 0.25]
                               [--speed-max 1900] [--order-scale 1] [--order-max 1.5] [--follow [--follow-scale 0.5]]
                               [--beats beats.json] [--no-contact] [--gravity] [--order-mode centre|delay]
                               [--zeta-open Z] [--as-v8] [--verbose]

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
   The thumb's MP has a second axis (Hollister 1995): its sideways bend is eased from 12 to 20 (passively 12 - 14,
   Kim 2014, Patel 2013; about 20 each way in active circumduction, Tanaka 2024).
2. reach: the hinges and the coupling undo shapes the trace made at the wrong joint (the thumbs of a heart bent 41
   degrees sideways at the MP, a pinch made at the index's PIP, a fist hooked at the DIP); each finger is fitted back
   to the input's outline (its outer joints and its tip, in the hand) by the joints that can move that way: a long
   finger's MP (flexion, sideways) and its PIP with the DIP inside the coupling's band, the thumb's CMC (radial and
   palmar abduction) and its MP and IP flexion; angles past the soft start of their range cost (REACH).  What the
   range cannot give stays lost: the heart's thumb tip ends some 8 mm from the trace's.
3. coupling: the deep flexor and the oblique retinacular ligament tie the DIP to the PIP (Leijnse 1997: one degree of
   freedom; DIP / PIP 0.76 Hahn 1995, 0.75-0.77 and the little finger 0.57 Mentzel 2011, 0.16-0.36 in a light grasp
   Kamper 2003, "the linkage varies greatly"): where the PIP bends (fully from 40 degrees, faded in from 20) the DIP is
   kept between the finger's least ratio (the slopes of Kamper 2003's grasps: index 0.32, middle 0.36, ring 0.16,
   little 0.25; slopes of whole grasps taken as the least ratio of a frame) and 1.0 times the PIP (no source: it only
   takes away a DIP bent past its PIP's angle) by a soft wall 4 degrees inside the band (after reach, it catches what
   the fit left outside).
4. enslave: a finger's MP is pulled toward its neighbours' by 0.05 of their difference (the adjacent fingers' passive
   coupling; Lang & Schieber 2004: 4 to 16 % of the moved finger's motion in the others, mostly the adjacent MCP).
5. relax: an open hand (the long fingers' mean MP + PIP + DIP at most 30 degrees, fading out by 70, none above 90)
   leans by --relax-gain (0.25) toward the relaxed hand Varghese 2020 measured (seated, the hand well supported, the
   forearm supinated - the palm up -, the wrist 15 - 20 degrees extended, completely relaxed: MCP 26-33, PIP 39-45,
   DIP 14-16, the index the least bent), moved with the wrist by the tenodesis (MP 0.30, PIP 0.43, DIP 0.16 degrees
   per degree of wrist extension, Su 2005, relaxed fingers; the wrist is taken within the +-60 degrees Su measured).
   It does not tell a hand the choreography stretches (a palm shown, a hand laid on the face) from a relaxed one: in
   Hibikase every open hand held still has its fingertips moved, the median 9 - 14 mm and the 95th percentile 16 - 23
   mm (the report's shape open_still).  A hand that touches the face, the chest, the waist or the other arm and hand
   (contact_weights, from the distances motor_layer uses) is not curled: the fingers lie on what they touch.
6. pace: a long finger's change of shape of 20 degrees or more (its MP + PIP + DIP moving one way) that is quicker
   than a dancer's takes the dancer's time, spread round its middle (pace: a centred box average, wide only over the
   change, as the speed step's), so the change keeps its time (no lag is added) and the holds keep their shape.  The
   time is the main sequence of the dancers' finger changes in FineDance's K-pop and street dances (PACE: the 10 - 90 %
   time c A^p, c 1.10 frames and p 0.35; about 3.5 frames for 28 degrees, 4.5 for 55, 5.7 for 110, 6.8 for 180), where
   the trace takes about 3 frames whatever the size and peaks at 1,850 deg/s for 160 degrees and more (the dancers' 930
   - 1,080).  Smaller changes are left (the capture cannot time them).  Two changes close together blend as a dancer's
   do (a fist opened at once again is not quite closed).  Not where the hand touches something.
7. order: within each change of a finger's shape its joints move out of step, by shares of the change's length
   (Carpinella 2011: closing a fist the MCP's speed peaks 11.4 % after the PIP's, opening the hand the PIP's 7.4 %
   after the MCP's; the DIP follows the PIP, Mentzel 2011), at most --order-max frames; holds are untouched.  The fingers
   are not staggered against each other: in a grasp the MCPs follow one time course (Santello 2002).  The stagger is
   laid round the change's middle (--order-mode centre: the joints' lags less their mean weighted by each joint's share
   of the change, so the finger as a whole changes when the input does; people's fingers do not trail the wrist by the
   analysts' a09, -0.01 / -0.04 frames in FineDance's K-pop, choreography and jazz).  --order-mode delay only delays the
   later joints, as v8 did (the a09 from the wrist to the finger then grows: v8 +0.36 / +0.31 against the trace's
   +0.01 / +0.16, the human baseline's measure).
8. follow (only with --follow): each finger reaches the shape the steps before give it (the equilibrium its muscles
   take it to) through the spring and the damper of step 9's body at the MP, every angle of its joints alike
   (follow_response: x'' + 2 zeta omega x' + omega^2 (x - shape) = 0, omega step 9's, between the open and the held
   hand, zeta ZETA's 0.85 for both, not the relaxed finger's): a change of shape comes about 2 zeta / omega = B / K
   later than the input's (the equilibrium point's lag: the damping over the stiffness) and is met without swinging
   past it.  On Rin's fingers B / K is 0.16 - 0.34
   frames in a held shape and 0.34 - 0.73 in an open hand (the thumb the least, the middle finger the most);
   --follow-scale (0.5) keeps half of it, as the nervous system times a shape's command to the wrist's (the fingers of
   a throw start to open 4 ms after the wrist starts to flex, Hore, Ritchie & Watts 1999; the wrist and the fingers
   moved together pull in phase, Dounskaia 2000): 2.6 - 5.6 ms in a held shape, 5.7 - 12 ms in an open hand, and the
   analysts' a09 from the wrist to the middle finger +0.53 / +0.54 frames on Hibikase's v8 (the report's wrist,
   手捩 in it).  The tenodesis of step 5 follows the wrist as late.  Not where the hand touches something (as relax).
   Off by default: in a style near Hibikase's people's fingers do not trail the wrist by the a09 measure (optically
   captured dancers, FineDance's 197 sequences at 30 fps: a median of +0.04 / +0.06 frames raw, +0.10 / +0.16 with the
   wrist and the finger through the same zero-phase 6 Hz low-pass, which takes out a sharp peak at 0 of what the two do
   on the same frames; K-pop-like and street dance 0 or below either way, -0.04 to -0.08 at 6 Hz; Chinese classical
   and folk dance +0.35 to +0.48 at 6 Hz; gestures at 120 Hz, BEAT: -3 / -1 ms raw, -11 / -5 ms without what is above
   30 Hz, the fingers ahead).  People's wrist joint holds no twist (FineDance puts the forearm's pronation in the
   elbow); with the wrist read as theirs (手捩 -> 手首) v8 reads +0.22 / +0.09 without the follow and +0.42 / +0.23
   with it (the report's a09_wrist_finger, 手捩 in the wrist: +0.30 / +0.41 and +0.53 / +0.54).  For a flowing style
   (Chinese classical or folk dance) the follow brings the hand toward the dancers'.
   On a beat hold (--beats: the arm's shoulder, elbow and wrist joints still for 4 frames or more from within 2
   frames of a beat, motor_layer's) the dancer hits the shape: the finger is KIME_STIFFNESS times as stiff (holding
   with some force, 2 to 4 times, Milner & Franklin 1998; a pinch co-contracted without force 1.9 - 5.3 times, Hoppner
   2017), from 3 frames before the hold (about 100 ms before an impact, Lacquaniti & Maioli 1989): step 9's lag
   quarters there (and the follow's halves).
9. passive: each finger is a body turning at its MP (the thumb at its MP) on a spring and a damper, driven by the
   hand's world angular acceleration about the joint's axis and the joint's world linear acceleration (finger_body,
   joint_forcing, passive_response).  The masses are Martin 2013's segments (via the research's cylinders), scaled to
   Rin's fingers (about 0.58 of a grown man's); the stiffness 1.0 N m/rad for a held shape (a finger stroking a
   surface, Kry & Pai 2006; 2 to 5 times a relaxed one, Milner & Franklin 1998) and 0.21 for the open hand (the upper
   end of a relaxed MCP, Kuo & Deshpande 2012), scaled as s^3; the damping ratio of a held shape 0.85 (co-contracted:
   no swing back, a pressed fingertip 0.83-1.15; the hand CG of Pollard & Zordan 2005 damps past critical), of the open
   hand the relaxed finger's own (ZETA_OPEN: Tsakonas et al. 2024's MP, index 0.562, middle 0.614, ring 0.591, little
   0.689; released from a bend it swings back past rest once by 5 - 12 % and settles; the thumb was not measured and
   keeps 0.85; --zeta-open sets every long finger's, 0.85 is v8's).  The lag goes to the MP, 0.35 of it to
   the PIP and 0.2 to the DIP (the thumb's MP and half to its IP), eased from 4 toward 10 degrees.  No study measured
   how far the fingers trail a moving hand (research B 3); the cap is ours: in purposeful arm movements the passive
   motion of the next joint out, the wrist, is often 1 - 5 degrees (Koshland 2000, which measured the wrist, not the
   fingers), and 5 degrees of a finger is seen (Jorg 2011).  Not where the hand touches something (as relax), stiffer
   on a beat hold (as follow).  Gravity is left out by default: the shape a dancer shows is held against it.
10. speed: a finger whose MP + PIP + DIP turns faster than --speed-max (1,900 deg/s: Date 2021's young adults, mean + 2
   SD of the fingertip's angular velocity in fast grip and release) is spread round the middle of its change (a
   centred box average, wide only there), so the change keeps its time; last of the timing steps, so that what the
   pace, the order, the follow and the lag add is held to the speed too.
11. rom: last, once (the soft limit is not idempotent), every joint is eased into its range (ROM, against the rest
   pose: the active means of Mohamed Ibrahim 2024 and the Japanese reference for the starts, mean + 2 SD or the
   reference + 10 for the caps; the MCP's sideways range by finger from Latz 2019: MP_SIDE).

The fingers' timing against the wrist: tools/motor_layer.py, before this layer, reads the fingers' turn in the hand
0.25 frames after the wrist's time (finger_delay) except where they snap, the arm holds or the hand touches; this layer
adds the order, the follow and the lag on top (the report's a09_wrist_finger measures what comes of both, by the
analysts' a09).  Not done here (the wrist's range is tools/anatomy_layer.py's): measured in the report only, the wrist
outside its circumduction ellipse (Gracia-Ibanez 2020) and, in a fist, beyond the fist's smaller palmar flexion and
ulnar deviation (Gehrmann 2008).

Everything else (the arms, the wrists, the trunk, the legs, every morph) is copied byte for byte; a joint's bone gets a
key on every frame (the linear curve, the physics bytes of the input's key in force), its key position kept.

The report (--report; in short on stdout) measures the input and the output alike: the range of motion (frames beyond
the start and the cap), the hinges' sideways bend and twist, DIP / PIP, the open hand's cascade, the largest steps, the
fingers' speed, the DIP's onset after the PIP's, the fingers held dead still while the hand moves, the wrist, the a09
lag from the wrist to the middle finger (a09_wrist_finger: the analysts' windowed cross-correlation of the angular
speeds, uncanny/a09_arcs/scripts/s04_timing.py; frames, + the finger later); and how far each joint moved (everywhere,
and in the held shapes away from their changes), how far each finger left the choreography's place in the hand (shape:
its outer joints and tip, mm, in the held shapes and in the open hands held still apart; "static" is the shape of each
frame before the timing steps, "output" the output), the steps' own figures (the frames where the hand touches
something and where the arm holds a beat, the fit's distances before and after, the follow's lag per finger and how far
it moved the MP, the passive lag per finger, its frequencies).

Do not use it with tools/anatomy_layer.py's --tenodesis (off by default): this layer has its own.

--as-v8 gives back the hands of v8 (main 59b28e6) byte for byte: --no-pace --order-mode delay --zeta-open 0.85.
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


def follow_response(target, omega, zeta, fps, substeps=8):
    """x [F, J] of joints that follow  x'' + 2 zeta omega x' + omega^2 (x - target) = 0  from rest at target[0], the
    target [F, J] taken as linear between frames, omega and zeta [J] or [F, J] (the frame's values through its
    interval).  The target itself is interpolated, not omega^2 times it: where omega changes from one frame to the next
    (a hand opening from a held shape), a forcing omega(t-1)^2 target would ask for (omega(t-1) / omega(t))^2 times it.
    Implicit Euler as passive_response: v' = (v + dt omega^2 (target - x)) / (1 + 2 zeta omega dt + omega^2 dt^2)"""
    target = np.asarray(target, dtype=float)
    F, J = target.shape
    w = np.broadcast_to(np.asarray(omega, dtype=float), (F, J))
    z = np.broadcast_to(np.asarray(zeta, dtype=float), (F, J))
    n = max(int(substeps), int(math.ceil(float(w.max(initial=0.0)) / (fps * 0.25))))
    dt = 1.0 / (fps * n)
    x, v = target[0].copy(), np.zeros(J)
    out = np.zeros((F, J))
    out[0] = x
    for t in range(1, F):
        u0, u1 = target[t - 1], target[t]
        wt, zt = w[t], z[t]
        k2 = wt * wt * dt
        den = 1.0 + 2.0 * zt * wt * dt + wt * wt * dt * dt
        for k in range(n):
            u = u0 + (u1 - u0) * ((k + 1) / n)
            v = (v + k2 * (u - x)) / den
            x = x + dt * v
        out[t] = x
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
STEPS = ("hinge", "reach", "coupling", "enslave", "relax", "pace", "order", "follow", "passive", "speed", "rom")
# the hinge joints (PIP, DIP, the thumb's IP and MP) bend in one plane: their sideways bend and their twist, read from
# the rest pose, eased from the start toward the cap (degrees).  The thumb's MP has a second axis (Hollister 1995): it
# moves sideways some 12 - 14 degrees passively (Kim 2014, Patel 2013) and about 20 each way in active circumduction
# (39 there and back, Tanaka 2024), so its sideways bend starts at 12 and is capped at 20
HINGE = {"side": (3.0, 8.0), "twist": (5.0, 12.0)}
HINGE_THUMB_MP = {"side": (12.0, 20.0), "twist": (5.0, 12.0)}
# DIP / PIP of the long fingers where the PIP bends more than COUPLING["from"] degrees: kept between low and high.  The
# low ends are the slopes of DIP on PIP in the lightest grasps (Kamper 2003, table 2: index 0.32, middle 0.36, ring
# 0.16, little 0.25; slopes of whole grasps, used here as the least ratio of a frame).  The high end has no source:
# the measured ratios reach 0.75 - 0.77 in a fist (Mentzel 2011, Hahn 1995: "the linkage varies greatly"); 1.0 only
# takes away a DIP bent past its PIP's angle
COUPLING = {"low": {"人指": 0.32, "中指": 0.36, "薬指": 0.16, "小指": 0.25}, "high": 1.0, "from": 20.0, "full": 40.0}
COUPLING_SOFT = 4.0              # degrees inside the band where the wall starts
# each long finger's MP is pulled toward each neighbour's MP by this share of their difference (the adjacent fingers'
# passive coupling)
ENSLAVE = 0.05
# the range of motion against the rest pose (the thumb's CMC: radial and palmar abduction against the index
# metacarpal, read absolutely): (soft start, cap) for each way, degrees.  The starts are the active means (Mohamed
# Ibrahim 2024) or the Japanese reference, the caps the mean + 2 SD or the reference + 10 (PIP: hyperextension 13 - 16
# on average, SD about 8)
ROM = {
    "mp": {"flex": ((25.0, 40.0), (90.0, 100.0)), "twist": ((15.0, 25.0), (15.0, 25.0))},
    "pip": {"flex": ((15.0, 30.0), (100.0, 110.0))},
    "dip": {"flex": ((10.0, 20.0), (80.0, 90.0))},
    "cmc": {"flex": ((10.0, 20.0), (60.0, 65.0)), "side": ((15.0, 25.0), (90.0, 95.0)), "twist": ((25.0, 35.0), (25.0, 35.0))},
    "tmp": {"flex": ((10.0, 25.0), (60.0, 65.0))},
    "ip": {"flex": ((15.0, 30.0), (80.0, 90.0))},
}
# the MCP's sideways range, finger by finger (Latz 2019, table 1, the wrist neutral: the mean for the start, the mean +
# 2 SD for the cap): (ulnar, radial).  The little finger goes far to the ulnar side (48.5 +- 17.0), the ring finger
# little to the radial side (8.1 +- 5.8).  The table's row for the middle finger repeats another row (research A 1.3)
# and is not used: the middle finger keeps 25 / 35 each way.  Read against the rest pose, as the other joints (Rin's
# rest puts the proximal phalanges 2 - 10 degrees off their metacarpals' lines)
MP_SIDE = {"人指": ((20.7, 44.1), (31.2, 50.8)), "中指": ((25.0, 35.0), (25.0, 35.0)),
           "薬指": ((28.0, 49.4), (8.1, 19.7)), "小指": ((48.5, 82.5), (14.8, 40.4))}
SPEED_MAX_DEG_S = 1900.0         # a finger's MP + PIP + DIP together, degrees per second
# the order of a finger's joints within a change of its shape, as shares of the change's length (frames, at most
# ORDER_MAX): closing, the MCP's speed peaks 11.4 % after the PIP's (Carpinella 2011) and the DIP follows the PIP
# (Mentzel 2011; the 10 % is ours); opening, the PIP peaks 7.4 % after the MCP (Carpinella 2011) and the DIP moves with
# the PIP.  --order-scale multiplies them
ORDER = {"close": {"mp": 0.114, "pip": 0.0, "dip": 0.10}, "open": {"mp": 0.0, "pip": 0.074, "dip": 0.074}}
ORDER_MAX = 1.5
ORDER_SPEED = 60.0               # degrees per second of a finger's MP + PIP + DIP: it is changing its shape
# the order's stagger is laid round the change's middle ("centre": the joints' lags less their mean weighted by each
# joint's share of the change, so the finger as a whole changes when the input does: people's fingers do not trail the
# wrist) or only delays the later joints ("delay", v8: the analysts' a09 from the wrist to the finger then grows)
ORDER_MODES = ("centre", "delay")
# the pace of a change of shape (pace): the dancers of FineDance (K-pop and street, the middle finger's MP + PIP + DIP,
# about 25,000 changes; _spike/out/stage6/finger_motion/, fm_changes.py) take a 10 - 90 % time that grows with the
# change's size A (degrees): the medians 3.8, 4.8, 6.0, 6.8 frames at 30 fps for 28, 55, 110, 180 degrees through the
# measure's 6 Hz low-pass, 3.5, 4.65, 5.9, 6.75 with the low-pass taken off, so c A^p with c 1.10 and p 0.35 (least
# squares on the logarithms).  The trace takes about 3 frames whatever the size (the changes of 160 degrees and more
# peak at 1,850 deg/s, the dancers' at 930 - 1,080).  A change under PACE["min"] degrees is left: the capture cannot
# time it (its 10 - 90 % time reads 2.3 - 3.1 frames, the low-pass's own 2.4).  A run of a finger's sum is a change while
# it moves more than PACE["step"] degrees a frame the same way
PACE = {"min": 20.0, "c": 1.10, "p": 0.35, "step": 0.2, "iterations": 4}
# a centred box average of half-width h adds h^2 / 3 to the variance of a change's speed profile, and a bell-shaped
# profile's 10 - 90 % time is about 2.563 of its standard deviation: h = PACE_H sqrt(T^2 - D^2) takes a 10 - 90 % time D
# to T
PACE_H = math.sqrt(3.0) / 2.563
# the relaxed hand: an open hand (the four fingers' mean MP + PIP + DIP under OPEN[0], none over OPEN[2]) is relaxed
# (fully at OPEN[0], not at all from OPEN[1]); it leans by RELAX_GAIN toward the relaxed hand Varghese 2020 measured
# (seated, "the hand well supported", the forearm supinated - the palm up -, the wrist at 15 - 20 degrees extension,
# "completely relaxed"; office workers' dominant hands, MCP, PIP, DIP), moved with the wrist by the tenodesis (Su 2005:
# degrees per degree of wrist extension, relaxed fingers, the wrist measured from 60 flexion to 60 extension and not
# carried past it) from that 17.5 degrees.  Every open hand is curled alike, the ones the choreography stretches too:
# the shape's measure counts them apart (open_still)
OPEN = (30.0, 70.0, 90.0)
RELAXED_HAND = {"人指": (27.1, 38.7, 13.8), "中指": (33.2, 40.7, 14.2), "薬指": (29.3, 44.8, 14.3), "小指": (26.2, 43.1, 16.1)}
RELAXED_WRIST = 17.5
TENODESIS = {"mp": 0.30, "pip": 0.43, "dip": 0.16}
TENODESIS_WRIST = 60.0           # degrees each way of the wrist that Su 2005 measured
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
# the damping ratio of a held shape: co-contracted, it trails and catches up without swinging back (a pressed
# fingertip 0.83 - 1.15, Kry & Pai 2006, Hajian & Howe 1997; the physical hands of the CG damp past critical, Pollard
# & Zordan 2005 about 1.7).  v8 gave the open hand the same 0.85
ZETA = {"held": 0.85, "open": 0.85}
# the open hand's damping ratio, finger by finger: relaxed fingers released from a bend (Tsakonas et al. 2024, 23
# people, the MP's flexion, the means of each finger's fits: the first swing past rest 5.0 - 11.8 %, the second 1.4 % or
# less).  The thumb was not measured and keeps ZETA["open"]
ZETA_OPEN = {"人指": 0.562, "中指": 0.614, "薬指": 0.591, "小指": 0.689}
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
# out (what the fingers touch holds them; Varghese 2020 and Su 2005 measured relaxed fingers pressing on nothing): a fingertip within
# the first distance (mm) of the eyes, of the line 上半身 - 首 (motor_layer's contact), of the line from the hips to 下半身,
# of the other forearm or hand, fully; none past the second.  Padded by CONTACT_PAD frames each way
CONTACT_MM = {"face": (70.0, 100.0), "chest": (60.0, 90.0), "waist": (80.0, 110.0), "other": (35.0, 60.0)}
CONTACT_PAD = 4
# the follow (--follow; off by default): each finger reaches the shape its muscles take it to through the passive
# body's spring and damper (its omega and zeta between the open and the held hand), so a change comes 2 zeta / omega
# (= B / K) late.  --follow-scale multiplies that time (omega divided by it).  When on, the scale keeps half of the
# body's B / K: a shape's command is timed to the wrist's (in a throw the fingers start to open 4 ms after the wrist
# starts to flex, Hore, Ritchie & Watts 1999; moving the wrist and the fingers together pulls them in phase, the more the
# faster, Dounskaia 2000, 2009), and half gives 2.6 - 5.6 ms in a held shape, 5.7 - 12 ms in an open hand on Rin's
# fingers; on Hibikase's v8 the analysts' a09 from the wrist to the middle finger then reads +0.53 / +0.54 frames (the
# report's wrist, 手捩 in it), under the elbow -> wrist +0.56 / +0.60 (a lighter part drags less, Lasseter 1987).  1 is
# the whole B / K (+0.74 / +0.68).  Off by default because in a style near Hibikase's people's fingers do not trail the
# wrist by that measure (FineDance, 197 optically captured sequences: K-pop-like and street dance 0 or below, raw and
# through a zero-phase 6 Hz low-pass; all styles +0.04 / +0.06 raw, +0.10 / +0.16 at 6 Hz; BEAT's gestures at 120 Hz
# -11 / -5 ms with what is above 30 Hz taken out, the fingers ahead;
# _spike/out/stage6/fingers/research/R2_human_mocap.md and _spike/out/stage6/review_fingers_lag/REVIEW.md)
FOLLOW_SCALE = 0.5
# a beat hold (--beats; motor_layer's): the joints of the shoulder, the elbow and the wrist all under HOLD_DEG_S for
# HOLD_MIN frames or more, the hold starting within KIME_BEAT frames of a beat.  There the dancer hits the shape: the
# finger's stiffness times KIME_STIFFNESS (holding with some force makes a finger 2 to 4 times as stiff as relaxed,
# Milner & Franklin 1998; a pinch co-contracted at the same force 1.9 - 2.2 times at 20 - 50 % MVC, 5.3 at 10 %,
# Hoppner 2017), from KIME_LEAD frames before the hold (the stiffness rises some 100 ms before an expected impact,
# Lacquaniti & Maioli 1989; ramped in over KIME_RAMP) to HOLD_EXIT frames before its end (ramped out over HOLD_RAMP);
# the follow's lag and the passive lag shrink there
HOLD_DEG_S, HOLD_MIN = 5.0, 4
KIME_BEAT, KIME_LEAD, KIME_RAMP, HOLD_EXIT, HOLD_RAMP = 2, 3, 4, 2, 3
KIME_STIFFNESS = 4.0


def default_params():
    p = {s: True for s in STEPS}
    p["follow"] = False             # off unless asked (--follow): see FOLLOW_SCALE and the module docstring, step 8
    p["contact"] = True
    p.update(relax_gain=RELAX_GAIN, speed_max=SPEED_MAX_DEG_S, order_max=ORDER_MAX, order_scale=1.0, gravity=False,
             stiffness=dict(STIFFNESS), zeta=dict(ZETA), passive_cap=PASSIVE_CAP, enslave_share=ENSLAVE,
             follow_scale=FOLLOW_SCALE, kime_stiffness=KIME_STIFFNESS, order_mode="centre", zeta_open=dict(ZETA_OPEN),
             pace_c=PACE["c"], pace_p=PACE["p"])
    return p


def as_v8(params):
    """the switches back to the hands of v8 (main 59b28e6): no pace, the order's stagger only delaying, the open hand
    damped as the held one (0.85); everything else as given"""
    p = dict(params)
    p.update(pace=False, order_mode="delay", zeta_open=None)
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
    """the hinge joints' sideways bend and twist eased toward their plane (HINGE; the thumb's MP: HINGE_THUMB_MP)"""
    for hand in hands.values():
        for j in hand.joints:
            if j.kind in ("pip", "dip", "ip") or (j.finger == THUMB and j.kind == "mp"):
                band = HINGE_THUMB_MP if (j.finger == THUMB and j.kind == "mp") else HINGE
                a = ang[j.bone]
                a[1] = soft_band(a[1], band["side"], band["side"])
                a[2] = soft_band(a[2], band["twist"], band["twist"])


def coupling(hands, ang):
    """the DIP of each long finger kept between COUPLING low and high times its PIP where the PIP bends (fully from
    COUPLING["full"] degrees, fading in from COUPLING["from"]); soft at both ends (the excess saturates)"""
    for hand in hands.values():
        for f, js in chains(hand).items():
            if f == THUMB or "pip" not in js or "dip" not in js:
                continue
            pip, dip = ang[js["pip"].bone][0], ang[js["dip"].bone][0]
            w = smoothstep(pip, COUPLING["from"], COUPLING["full"])
            lo, hi = COUPLING["low"][f] * pip, COUPLING["high"] * pip
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


def joint_limits(j, way):
    """((start, cap) of the negative side, (start, cap) of the positive side) of a joint's angle (ROM; the MCP's
    sideways range by finger: MP_SIDE), or None where it has no range"""
    if way == "side" and j.kind == "mp" and j.finger in MP_SIDE:
        return MP_SIDE[j.finger]
    return ROM[kind_of(j)].get(way)


def rom(hands, ang):
    """every joint's angles eased into its range (joint_limits: soft start, cap; identity below the start)"""
    for hand in hands.values():
        for j in hand.joints:
            for i, way in enumerate(("flex", "side", "twist")):
                lim = joint_limits(j, way)
                if lim is not None:
                    low, high = lim
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
                lim = joint_limits(j, ("flex", "side")[i])
                bounds.append(None if lim is None else (lim[0][0], lim[1][0]))
            low = COUPLING["low"].get(finger, 0.0)

            def residual(x):
                rows = {b: a.copy() for b, a in fixed.items()}
                for c, (j, i) in enumerate(free):
                    rows[j.bone][i] = x[:, c]
                d = (chain_points(seq, rows) - target) * MM_PER_UNIT
                r = [d.reshape(len(x), -1), (x - x0) * REACH["reg"]]
                if band and finger != THUMB:
                    pip, dip = x[:, 2], x[:, 3]
                    r.append((w_band * np.maximum(dip - (COUPLING["high"] * pip - COUPLING_SOFT), 0.0))[:, None])
                    r.append((w_band * np.maximum((low * pip + COUPLING_SOFT) - dip, 0.0))[:, None])
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
    """the relaxed hand: each joint of a relaxed hand leans toward Varghese 2020's relaxed hand moved by the wrist's
    angle, flexion += gain x r x (RELAXED_HAND + TENODESIS x (wrist extension - RELAXED_WRIST) - flexion), the wrist
    taken within +-TENODESIS_WRIST (Su 2005's range); touch: side -> 0 .. 1, the hand on something (contact_weights),
    where it does not lean"""
    out = {}
    for side, hand in hands.items():
        r = relaxedness(hand, ang)
        if r is None:
            continue
        if touch is not None and side in touch:
            r = r * (1.0 - touch[side])
        w = np.clip(wrist_ext[side], -TENODESIS_WRIST, TENODESIS_WRIST)
        for f, js in chains(hand).items():
            if f == THUMB or f not in RELAXED_HAND:
                continue
            for i, k in enumerate(("mp", "pip", "dip")):
                cur = ang[js[k].bone][0]
                target = RELAXED_HAND[f][i] + TENODESIS[k] * (w - RELAXED_WRIST)
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


def order(hands, ang, longest, scale=1.0, mode="centre"):
    """the joints of each long finger moved out of step within each change of its shape (a run where its MP + PIP +
    DIP closes, or opens, faster than ORDER_SPEED; a turn of the way starts a new change): every joint is read lag
    frames earlier, lag = ORDER[closing or opening][joint] x scale x the change's length in frames (at most `longest`),
    faded in and out over the change; holds are untouched.  mode "centre" takes from every joint's lag the mean of the
    lags weighted by the joints' shares of the change (the leading joint then moves a little early, the others a little
    late, and the finger's MP + PIP + DIP keeps the input's time); "delay" only delays (v8)"""
    if mode not in ORDER_MODES:
        raise ValueError("the order's mode is one of %s" % ", ".join(ORDER_MODES))
    report = {"changes": 0, "mode": mode}
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
                lam = {k: min(longest, ORDER[way][k] * scale * n) for k in bones}
                if mode == "centre":
                    lo_f, hi_f = max(0, a - 1), min(len(s) - 1, b + 1)
                    share = {k: abs(float(bones[k][0][hi_f] - bones[k][0][lo_f])) for k in bones}
                    total = sum(share.values())
                    mean = sum(share[k] * lam[k] for k in bones) / total if total > 1e-9 else 0.0
                    lam = {k: lam[k] - mean for k in bones}
                for k in bones:
                    lk = lam[k]
                    if mode == "delay" and lk <= 0.0 or abs(lk) <= 1e-12:
                        continue
                    # the lag held through the change and ramped in and out over ceil(|lag|) + 1 frames each side; where
                    # two changes' ramps meet, the larger lag (either way) holds
                    reach = int(np.ceil(abs(lk))) + 1
                    lo, hi = max(0, a - reach), min(len(s), b + reach + 1)
                    t = np.arange(lo, hi)
                    w = np.minimum(1.0, np.minimum(t - (a - reach), (b + reach) - t) / reach)
                    cand = lk * np.clip(w, 0.0, 1.0)
                    cur = lags[k][lo:hi]
                    lags[k][lo:hi] = np.maximum(cur, cand) if mode == "delay" else np.where(np.abs(cand) > np.abs(cur), cand, cur)
            for k, arr in bones.items():
                if lags[k].any():
                    for i in range(3):
                        arr[i] = time_shift(arr[i], lags[k])
    return report


def pace_time(amp, c=PACE["c"], p=PACE["p"]):
    """the 10 - 90 % time (frames at 30 fps) a dancer's finger takes for a change of its MP + PIP + DIP by amp degrees
    (PACE: FineDance's K-pop and street dances)"""
    return c * np.power(np.asarray(amp, dtype=float), p)


def monotone_changes(s, step=PACE["step"]):
    """[(a, b)] the frames from a to b over which s moves more than `step` a frame the same way (a turn ends a run)"""
    d = np.diff(s)
    out = []
    for sgn in (1.0, -1.0):
        out += [(a, b + 1) for a, b in runs(sgn * d > step)]
    return sorted(out)


def ten_ninety(s, a, b):
    """the 10 - 90 % time (frames, between the frames) of the change of s from frame a to frame b"""
    y = (s[a:b + 1] - s[a]) / (s[b] - s[a])
    y = np.maximum.accumulate(y)
    t = np.arange(a, b + 1, dtype=float)
    return float(np.interp(0.9, y, t) - np.interp(0.1, y, t))


def pace(hands, ang, touch=None, c=PACE["c"], p=PACE["p"]):
    """a long finger's change of shape of PACE["min"] degrees or more (MP + PIP + DIP, monotone_changes) quicker than
    pace_time gets it: every angle of the finger's joints is averaged over a centred window, half-width PACE_H sqrt(T^2
    - D^2) over the change and its reach (the widths smoothed as speed_limit's), so the change keeps its middle and the
    holds before and after keep their shape; repeated while a change is still short (at most PACE["iterations"]).
    touch: side -> 0 .. 1, the hand on something, where the fingers keep the input's time.  Returns side -> finger -> the
    changes, how many were paced, and their 10 - 90 % times before and after"""
    report = {}
    for side, hand in hands.items():
        rep = {}
        for f, js in chains(hand).items():
            if f == THUMB or not all(k in js for k in ("mp", "pip", "dip")):
                continue
            bones = [js[k].bone for k in ("mp", "pip", "dip")]
            F = len(ang[bones[0]][0])
            keep = np.ones(F) if touch is None or side not in touch else 1.0 - touch[side]
            s0 = sum(ang[b][0] for b in bones)
            big0 = [(a, b) for a, b in monotone_changes(s0) if abs(s0[b] - s0[a]) >= PACE["min"]]
            short0 = [(a, b) for a, b in big0 if ten_ninety(s0, a, b) < pace_time(abs(s0[b] - s0[a]), c, p) - 0.05]
            # a shape held between two changes is still reached: each change widens by at most half the hold on
            # either side of it (the input's changes of 5 degrees or more bound the holds)
            bounds = [(a, b) for a, b in monotone_changes(s0) if abs(s0[b] - s0[a]) >= 5.0]
            capf = np.full(F, np.inf)
            for i, (a, b) in enumerate(bounds):
                before = a - bounds[i - 1][1] if i else F
                after_ = bounds[i + 1][0] - b if i + 1 < len(bounds) else F
                amp0 = abs(s0[b] - s0[a])
                need = 0.0
                if amp0 >= PACE["min"]:
                    d0, t0_ = ten_ninety(s0, a, b), float(pace_time(amp0, c, p))
                    need = PACE_H * math.sqrt(max(0.0, t0_ * t0_ - d0 * d0))
                # a change that cannot take the dancer's time without eating the shape held next to it keeps the
                # input's time (the choreography's shape first)
                capf[a:b + 1] = np.inf if 0.5 * min(before, after_) >= need else 0.0
                if i + 1 < len(bounds):
                    capf[b + 1:bounds[i + 1][0]] = max(0.5, 0.5 * after_)        # the hold between them
            for _ in range(PACE["iterations"]):
                s = sum(ang[b][0] for b in bones)
                h = np.zeros(F)
                for a, b in monotone_changes(s):
                    amp = abs(s[b] - s[a])
                    if amp < PACE["min"]:
                        continue
                    d, target = ten_ninety(s, a, b), float(pace_time(amp, c, p))
                    if d < target - 0.05:
                        h[a:b + 1] = np.maximum(h[a:b + 1], min(PACE_H * math.sqrt(target * target - d * d),
                                                                float(capf[a:b + 1].min()) if np.isfinite(capf[a:b + 1].min()) else np.inf))
                if not h.any():
                    break
                reach = int(np.ceil(h.max())) + 1
                hd = np.array([h[max(0, t - reach):t + reach + 1].max() for t in range(F)])
                k = np.hanning(2 * reach + 3)[1:-1]
                hs = np.maximum(np.convolve(np.pad(hd, reach, mode="edge"), k / k.sum(), "valid"), h)
                # where the hand touches, the window narrows (a blend of the paced and the input's values would keep
                # the input's quick step and jump after it, where the touch fades within a change)
                hs = np.minimum(hs, capf) * keep
                if not hs.any():
                    break
                for bn in bones:
                    for i in range(3):
                        ang[bn][i] = box_average(ang[bn][i], hs)
            # the dancer meets the shape when the input does (a shape hit on the beat is there on the beat): the
            # widened change is moved earlier by how much later its 90 % point came, the hold after it untouched
            s1 = sum(ang[b][0] for b in bones)
            lag = np.zeros(F)
            for a, b in short0:
                amp = s0[b] - s0[a]
                sg = 1.0 if amp > 0 else -1.0
                lv = s0[a] + 0.9 * amp
                y0 = np.maximum.accumulate(sg * (s0[a:b + 1] - lv))
                t0 = a + float(np.interp(0.0, y0, np.arange(b + 1 - a)))
                lo, hi = max(0, a - 12), min(F - 1, b + 12)
                y1 = sg * (s1[lo:hi + 1] - lv)
                ks = np.where((y1[:-1] < 0.0) & (y1[1:] >= 0.0))[0]
                if not len(ks):
                    continue
                times = lo + ks + (0.0 - y1[ks]) / (y1[ks + 1] - y1[ks])
                late = float(times[np.argmin(np.abs(times - t0))] - t0)
                if late <= 0.0:
                    continue
                r = int(np.ceil(late)) + 1
                # full from before the widened change starts to its end; eased out within the hold after it (never
                # reading the next change into the hold)
                nxt = min([x for x, _ in bounds if x > b] + [F])
                start = a - int(np.ceil(pace_time(abs(amp), c, p))) - r
                out = max(1, min(2 * r, nxt - b - 1))
                t = np.arange(max(0, start - r), min(F, b + out + 1))
                w = np.clip(np.minimum((t - (start - r)) / r, (b + out - t) / out), 0.0, 1.0)
                cand = -late * w
                lag[t] = np.where(np.abs(cand) > np.abs(lag[t]), cand, lag[t])
            lag = lag * keep
            if lag.any():
                for bn in bones:
                    for i in range(3):
                        ang[bn][i] = time_shift(ang[bn][i], lag)
            s1 = sum(ang[b][0] for b in bones)
            after = [ten_ninety(s1, a, b) for a, b in monotone_changes(s1) if abs(s1[b] - s1[a]) >= PACE["min"]]
            rep[f] = {"changes": len(big0), "paced": len(short0),
                      "t10_90_before": stats([ten_ninety(s0, a, b) for a, b in big0]), "t10_90_after": stats(after)}
        report[side] = rep
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
    by_finger = params.get("zeta_open")
    if by_finger and finger in by_finger:
        zeta["open"] = float(by_finger[finger])          # the relaxed finger's own damping (ZETA_OPEN)
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


def kime_gain(params, kime, side, F):
    """the factor on omega per frame: sqrt(kime_stiffness) on a beat hold (kime: side -> 0 .. 1), 1 elsewhere"""
    if kime is None or side not in kime:
        return np.ones(F)
    return 1.0 + (math.sqrt(params["kime_stiffness"]) - 1.0) * kime[side]


def passive(hands, ang, loc, world, P, params, held, touch=None, kime=None):
    """the fingers' lag (radians -> degrees added to the flexion; the long fingers' MP, PIP, DIP by PASSIVE_SHARE, the
    thumb's MP and IP): each finger's body driven by the hand's world angular acceleration about its MP's axis and the
    MP's world linear acceleration (gravity only when asked: the dancer holds the shape she shows against it), the
    stiffness between the open and the held hand by `held` (0 .. 1 per frame) and up on a beat hold (kime: side -> 0
    .. 1), the lag eased toward PASSIVE_CAP"""
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
        if kime is not None and side in kime:
            omega = omega * kime_gain(params, kime, side, F)[:, None]
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


# ---- step 3b: the follow (the shape reached through the finger's spring and damper) -------------------------------

def follow(hands, ang, held, params, touch=None, kime=None):
    """each finger's angles (the long fingers' MP, PIP, DIP, the thumb's CMC, MP, IP; flexion, sideways and twist)
    reached through its own spring and damper at the MP: x'' + 2 zeta omega x' + omega^2 x = omega^2 u, u the shape the
    steps before give (the equilibrium its muscles take it to), from rest at frame 0, omega and zeta the passive body's
    (finger_body: between the open and the held hand by `held`, up on a beat hold by kime_gain), omega divided by
    params["follow_scale"].  A change of shape then comes about 2 zeta / omega (B / K) after the input's timing and is
    met without swinging past it (zeta 0.85).  touch: side -> 0 .. 1, the hand on something, where the fingers keep the
    input's timing (what they touch holds them).  Returns side -> finger -> the lag (frames) of the held and the open
    hand and how far the MP's flexion left the input's timing (degrees)"""
    report = {}
    scale = float(params.get("follow_scale", FOLLOW_SCALE))
    # the follow reaches the shape the dancer aims at without swinging past it: its damping is ZETA's (params["zeta"]),
    # not the relaxed finger's of the passive lag (ZETA_OPEN)
    zf = dict(params, zeta_open=None)
    for side, hand in hands.items():
        h = held[side]
        F = len(h)
        cs = chains(hand)
        gain = kime_gain(params, kime, side, F)
        cols, W, Z, rows = [], [], [], {}
        for finger, js in cs.items():
            if "mp" not in js or (finger != THUMB and "pip" not in js):
                continue
            b = finger_body(hand, finger, zf)
            w = (b.omega["open"] + (b.omega["held"] - b.omega["open"]) * h) * gain / scale
            z = b.zeta["open"] + (b.zeta["held"] - b.zeta["open"]) * h
            kinds = ("cmc", "mp", "ip") if finger == THUMB else ("mp", "pip", "dip")
            for k in kinds:
                if k in js:
                    for i in range(3):
                        if k == "mp" and i == 0:
                            rows[finger] = (len(cols), b)
                        cols.append((js[k].bone, i))
                        W.append(w)
                        Z.append(z)
        if not cols:
            continue
        U = np.stack([ang[bn][i] for bn, i in cols], axis=1)
        W, Z = np.stack(W, axis=1), np.stack(Z, axis=1)
        X = follow_response(U, W, Z, FPS)
        keep = np.ones(F) if touch is None or side not in touch else 1.0 - touch[side]
        out = U + keep[:, None] * (X - U)
        for c, (bn, i) in enumerate(cols):
            ang[bn][i] = out[:, c]
        rep = {}
        for finger, (c, b) in rows.items():
            rep[finger] = {"lag_frames_held": _r(2.0 * b.zeta["held"] / b.omega["held"] * scale * FPS, 3),
                           "lag_frames_open": _r(2.0 * b.zeta["open"] / b.omega["open"] * scale * FPS, 3),
                           "deviation_deg": stats(np.abs(out[:, c] - U[:, c]))}
        report[side] = rep
    return report


def rests(speeds, thr=HOLD_DEG_S, minlen=HOLD_MIN):
    """[(i, j)]: the runs of steps where every joint's speed (deg/s, per step t -> t+1) is under thr, still on [i, j),
    at least minlen long (motor_layer's and the analysts' rests)"""
    still = np.all(np.stack(speeds) < thr, axis=0)
    return [(a, b + 1) for a, b in runs(still) if b + 1 - a >= minlen]


def ramp_weight(n, pieces):
    """a weight per frame from (rise_start, rise_end, fall_start, fall_end) pieces (motor_layer's): 0 before rise_start,
    a smoothstep up to 1 at rise_end, 1 to fall_start, a smoothstep down to 0 at fall_end; the max over the pieces"""
    w = np.zeros(n)
    f = np.arange(n, dtype=float)
    for a, b, c, d in pieces:
        up = np.ones(n) if b <= a else smoothstep(f, a, b)
        down = np.ones(n) if d <= c else 1.0 - smoothstep(f, c, d)
        w = np.maximum(w, np.where((f < a) | (f > d), 0.0, np.minimum(up, down)))
    return w


def rotation_speed(q):
    """deg/s of the turn between consecutive frames of rotations q [F, 4] (the short way): [F - 1]"""
    dq = qmul(qconj(q[:-1]), q[1:])
    return np.degrees(2.0 * np.arctan2(np.linalg.norm(dq[:, :3], axis=1), np.abs(dq[:, 3]))) * FPS


def beat_holds(model, motion, F, sides, beats):
    """side -> (0 .. 1 per frame: the beat holds' weight, [[start, end]] of the holds), from the input's arm: the
    shoulder (肩 -> 腕), the elbow (腕 -> ひじ) and the wrist (ひじ -> 手首) joints' rotation speeds (motor_layer's schedules)"""
    P = _positions(model)
    arm = ("肩", "腕", "ひじ", "手首")
    names = [s + n for s in sides for n in arm if s + n in P]
    out = {s: (np.zeros(F), []) for s in sides}
    if not names:
        return out
    pose = fk.Pose(model, motion, names)
    R = {n: np.zeros((F, 4)) for n in names}
    for f in range(F):
        at = pose.at(f)
        for n in names:
            R[n][f] = at[n][1]
    t0, per = beats
    beat_frames = (t0 + np.arange(0, int((F / FPS - t0) / per) + 2) * per) * FPS
    for s in sides:
        if not all(s + n in R for n in arm):
            continue
        sp = [rotation_speed(qmul(qconj(R[s + a]), R[s + b])) for a, b in zip(arm[:-1], arm[1:])]
        pieces, holds = [], []
        for a, b in rests(sp):
            if len(beat_frames) and np.min(np.abs(beat_frames - a)) <= KIME_BEAT:
                end = max(a + 1, b - HOLD_EXIT)
                pieces.append((a - KIME_LEAD - KIME_RAMP, a - KIME_LEAD, max(a, end - HOLD_RAMP), end))
                holds.append([int(a), int(b)])
        out[s] = (ramp_weight(F, pieces), holds)
    return out


# ---- the a09 measure: the wrist's and the finger's timing ---------------------------------------------------------

def a09_parabola(y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if den != 0:
            return i + 0.5 * (a - c) / den
    return float(i)


def a09_lags(p, d, win=60, step=15, maxlag=6):
    """the analysts' a09 lags (uncanny/a09_arcs/scripts/s04_timing.py, copied): the windowed cross-correlation of two
    angular speeds p (the proximal joint) and d (the distal one), 2 s windows every 15 frames, the lag of the peak within
    +-6 frames refined by a parabola, windows where both move (the speed's SD over 20 deg/s) and the peak over 0.5; +:
    the distal joint later"""
    out = []
    for s in range(0, len(p) - win - 2 * maxlag, step):
        a = p[s + maxlag:s + maxlag + win]
        if a.std() < 20:
            continue
        cs = []
        for L in range(-maxlag, maxlag + 1):
            b = d[s + maxlag + L:s + maxlag + L + win]
            cs.append(np.nan if b.std() < 20 else np.corrcoef(a, b)[0, 1])
        cs = np.array(cs)
        if np.all(np.isnan(cs)):
            continue
        i = int(np.nanargmax(cs))
        if cs[i] < 0.5 or i in (0, len(cs) - 1):
            continue
        out.append(a09_parabola(np.nan_to_num(cs, nan=-1), i) - maxlag)
    return out


def a09_summary(lags):
    v = np.asarray(lags, dtype=float)
    if v.size == 0:
        return {"n": 0, "median": None}
    return {"n": int(v.size), "median": _r(np.median(v), 3), "mean": _r(v.mean(), 3),
            "share_later": _r(np.mean(v >= 0.5), 3), "share_earlier": _r(np.mean(v <= -0.5), 3),
            "share_zero": _r(np.mean(np.abs(v) < 0.5), 3)}


def a09_wrist_finger(loc, side, F):
    """the a09 lag from the wrist joint (手捩 x 手首 against ひじ) to the middle finger in the hand (中指０ .. 中指３
    against 手首) of the locals loc (the chains have no appended or IK bones), or None without them"""
    ident = np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
    if side + "手首" not in loc or side + "中指３" not in loc:
        return None
    wq = qmul(loc.get(side + "手捩", ident), loc[side + "手首"])
    fq = loc.get(side + "中指０", ident)
    for p in ("１", "２", "３"):
        fq = qmul(fq, loc.get(side + "中指" + p, ident))
    return a09_summary(a09_lags(rotation_speed(A.qnorm(wq)), rotation_speed(A.qnorm(fq))))


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


def layer(model, motion, params=None, pulp=None, log=None, beats=None):
    """the hands of `motion` made anatomical (see the module docstring); pulp: side -> the thumb's pulp side (from the
    mesh: pulp_from_mesh), else the palm's normal; beats: (the first beat's seconds, the period) for the beat holds"""
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
              for s, v in (pulp or {}).items()}, "beats": list(beats) if beats is not None else None, "steps": {}}
    kime = None
    if beats is not None and (p["follow"] or p["passive"]):
        held_beats = beat_holds(model, motion, F, [s for s in hands], beats)
        kime = {s: w for s, (w, _) in held_beats.items()}
        report["steps"]["beat_holds"] = {s: hs for s, (_, hs) in held_beats.items()}
        report["steps"]["beat_hold_frames"] = {s: int((w > 0.5).sum()) for s, w in kime.items()}
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
    if p.get("contact", True) and (p["relax"] or p["passive"] or p["follow"] or p.get("pace")):
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
    if p.get("pace"):
        report["steps"]["pace"] = pace(hands, ang, touch, p.get("pace_c", PACE["c"]), p.get("pace_p", PACE["p"]))
    if p["order"]:
        report["steps"]["order"] = order(hands, ang, p["order_max"], p["order_scale"], p.get("order_mode", "centre"))
    if p["follow"]:
        report["steps"]["follow"] = follow(hands, ang, held, p, touch, kime)
    sides = [s for s, _ in SIDES if s + "手首" in P and s in hands]
    world = hand_world(model, motion, F, sides) if sides else {}
    if p["passive"]:
        report["steps"]["passive"] = passive(hands, ang, loc, world, P, p, held, touch, kime)
    if p["speed"]:
        # after the lag and the order, so that what they add is held to the speed too
        report["steps"]["speed_spread_steps"] = speed_limit(hands, ang, p["speed_max"])
    if p["rom"]:
        rom(hands, ang)               # once, last: the soft limit is not idempotent
    out_loc = compose_all(hands, ang)
    out_motion = A.build(motion, None, out_loc, {b: keypos[b] for b in out_loc}, F)
    report["untouched"] = untouched(motion, out_motion, out_motion.labels)
    report["input"] = measure(hands, ang_in, loc, world, P, wrist)
    report["output"] = measure(hands, ang, out_loc, world, P, wrist, around=loc)
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

def measure(hands, ang, loc, world, P, wrist=None, around=None):
    """per side: the range of motion (frames beyond the start and the cap, each way), the hinge joints' sideways bend
    and twist, DIP / PIP, the open hand's cascade, the largest steps, the shape changes' speed and the DIP's onset
    after the PIP's, the fingers held dead still while the hand moves, the wrist (outside its circumduction ellipse;
    in a fist, beyond the fist's palmar flexion and ulnar deviation; the direction of its motion) and the a09 lag from
    the wrist to the middle finger (around: the locals of the bones the layer does not write, 手捩, 手首, 中指０)"""
    out = {}
    F = len(next(iter(ang.values()))[0]) if ang else 0
    for side, hand in hands.items():
        r = {"rom": {}, "hinge": {}, "coupling": {}}
        r["a09_wrist_finger"] = a09_wrist_finger(dict(around or {}, **loc), side, F)
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
            row = {}
            for i, way in enumerate(("flex", "side", "twist")):
                lim = joint_limits(j, way)
                if lim is None:
                    continue
                x = ang[j.bone][i]
                (ls, lc), (hs, hc) = lim
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
                                "under_low": int((ratio < COUPLING["low"][f]).sum()),
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
    outline) and the tip alone; everywhere, in the held shapes away from their changes (as change()) and in the open
    hands held as still (open_still: relax curls them all, the choreography's stretched hands too)"""
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
            still_open = ~h & ~near
            rows[finger] = {"outline_mm": {"all": stats(d.mean(axis=1)), "held_still": stats(d.mean(axis=1)[keep]),
                                           "open_still": stats(d.mean(axis=1)[still_open])},
                            "tip_mm": {"all": stats(d[:, -1]), "held_still": stats(d[keep, -1]),
                                       "open_still": stats(d[still_open, -1])}}
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
                     "dip_after_pip_p50": [a["dip_after_pip_frames"].get("p50"), b["dip_after_pip_frames"].get("p50")],
                     "a09_wrist_finger": [(a.get("a09_wrist_finger") or {}).get("median"),
                                          (b.get("a09_wrist_finger") or {}).get("median")]}
    return out


def read_beats(path):
    """(the first beat's seconds, the period) from a JSON with first_beat_seconds and period_seconds (motor_layer's)"""
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    t0, per = float(b["first_beat_seconds"]), float(b["period_seconds"])
    if not per > 0.0:
        raise ValueError("the beats' period_seconds must be above 0")
    return t0, per


def run(dance_path, model_path, out_path, report_path=None, params=None, log=None, beats_path=None):
    started = time.time()
    A.check_distinct(dance_path, model_path, out_path, report_path, beats_path)
    dance = vmd.load(dance_path)
    model = load_model(model_path)
    beats = read_beats(beats_path) if beats_path else None
    pulp = pulp_from_mesh(model_path) if model_path.lower().endswith(".pmx") else {}
    result = layer(model, dance, params, pulp=pulp, log=log, beats=beats)
    A.write_bytes(os.path.abspath(out_path), vmd.dumps(result.motion))
    report = dict({"in": os.path.abspath(dance_path), "model": os.path.abspath(model_path),
                   "out": os.path.abspath(out_path), "beats_file": beats_path and os.path.abspath(beats_path)},
                  **result.report)
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
        if s != "follow":
            ap.add_argument("--no-" + s, action="store_true", help="leave out the step %s" % s)
    ap.add_argument("--follow", action="store_true",
                    help="add the step follow: the fingers reach each shape through their spring and damper, a little "
                         "after the hand (off by default: dancers' fingers do not trail the wrist so)")
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
    ap.add_argument("--follow-scale", type=float, default=FOLLOW_SCALE,
                    help="with --follow, its lag (2 zeta / omega of each finger's spring and damper) times this (default "
                         "%g)" % FOLLOW_SCALE)
    ap.add_argument("--beats", help="JSON with first_beat_seconds and period_seconds (motor_layer's): the fingers are "
                                    "stiffer where the arm stops on a beat")
    ap.add_argument("--gravity", action="store_true", help="let gravity bend the fingers too (off: the dancer holds "
                                                            "the shape she shows against it)")
    ap.add_argument("--order-mode", choices=ORDER_MODES, default="centre",
                    help="the joints' stagger laid round the change's middle (centre, default) or only delaying (delay, v8)")
    ap.add_argument("--zeta-open", type=float, default=None,
                    help="the open hand's damping ratio for every long finger (default: the relaxed fingers' own, "
                         "Tsakonas 2024; 0.85 is v8's)")
    ap.add_argument("--open-stiffness", type=float, default=STIFFNESS["open"],
                    help="the open hand's stiffness at a grown finger's MP, N m/rad (default %g, the upper end of a relaxed "
                         "MCP; 0.42 gives the dancers' passive gain of FineDance and less a09 lag, and less motion)"
                         % STIFFNESS["open"])
    ap.add_argument("--as-v8", action="store_true",
                    help="the hands of v8 byte for byte: --no-pace --order-mode delay --zeta-open 0.85")
    ap.add_argument("--verbose", action="store_true", help="progress on stderr")
    a = ap.parse_args(argv)
    params = default_params()
    params.update({s: not getattr(a, "no_" + s) for s in STEPS if s != "follow"})
    params.update(relax_gain=a.relax_gain, speed_max=a.speed_max, order_scale=a.order_scale, order_max=a.order_max,
                  gravity=a.gravity, contact=not a.no_contact, follow=a.follow, follow_scale=a.follow_scale,
                  order_mode=a.order_mode)
    if a.zeta_open is not None:
        params["zeta_open"] = {f: a.zeta_open for f in LONG}
    if a.open_stiffness != STIFFNESS["open"]:
        params["stiffness"] = dict(params["stiffness"], open=a.open_stiffness)
    if a.as_v8:
        params = as_v8(params)
    log = (lambda msg: print(msg, file=sys.stderr, flush=True)) if a.verbose else None
    try:
        if not a.speed_max > 0.0:
            raise ValueError("--speed-max must be above 0")
        if not a.follow_scale > 0.0:
            raise ValueError("--follow-scale must be above 0 (without --follow the step is left out)")
        if a.order_scale < 0.0 or a.order_max < 0.0 or a.relax_gain < 0.0:
            raise ValueError("--order-scale, --order-max and --relax-gain must not be negative")
        if a.zeta_open is not None and not a.zeta_open > 0.0:
            raise ValueError("--zeta-open must be above 0")
        if not a.open_stiffness > 0.0:
            raise ValueError("--open-stiffness must be above 0")
        result = run(a.dance, a.model, a.out, a.report, params, log, a.beats)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
