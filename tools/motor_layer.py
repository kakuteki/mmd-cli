"""Bake torque-limited joint tracking with proximal-to-distal delays onto a dance: the arm's joints no longer all move and
stop on the same frame, and a hand runs on a little past a stop and settles.

    python tools/motor_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--beats beats.json]
                                [--key-frames TRACE.vmd] [--lead L] [--delay-scale 1] [--finger-delay 0.25]
                                [--substeps 16] [--world w.npz] [--preset default|strong] [--verbose]

Why (the analysis of 2026-10-07, a09): in the trace 91 to 100 % of the keys of the arm's joints sit on the same frame, the
joints' timing differs by 0 frames (95 % interval +-0.1), and the wrist stops after the upper arm before 0 to 8 % of the
arm's rests: "bringing all parts of the body into the pose at the same time ... will have a very robotic appearance"
(Neff & Fiume 2003).  The research of 2026-10-10 (stage2/research/RESEARCH.md) and the spike (stage2/spike) set the form:
a physical layer alone gives back the keys (DeepMimic, Yin 2002); what adds the person is (1) a proximal-to-distal shift
of the timing, (2) a softer, delayed tracking that starts a little late and runs a little past the stop (Neff & Fiume
2002: "This overshoot is often visually desirable") and (3) stiffness that rises where a pose must be met (Tan, Liu,
Turk 2011).  The spike found damping below 1 (0.45 to 0.6) raises the 3 to 6 Hz share and the speed dips that a02 found
too many already; damping 0.85 with the delays and the head aimed at the input's world rotation (its "soft_wh") was the
usable set.

The layer (numbers: the constants and default_params below):

* SIMULATED bones: 上半身, 上半身2, 首, 頭 and per side 肩, 腕, ひじ, 手首 (dynamic) and the fingers (kinematic, below).
  Everything else (センター, 下半身, 腰, the leg IK, 手捩, 腕捩, the eyes, 肩P / 肩C, ...) and every morph is copied byte
  for byte.  A simulated bone gets a key on every frame (the linear curve, the physics bytes of the input key in force).
* Each dynamic bone is a rigid body whose WORLD rotation has inertia.  A joint torque pulls it towards its target: the
  input's rotation relative to its simulated parent (the nearest simulated ancestor; bones between, such as 肩C or 手捩,
  keep their input local turn), read at the time t + lead - d(t).  The head's target is the input's WORLD rotation (the
  spike: aimed at the neck it swung 35 degrees more in the world in a fast turn, the gaze riding on it).
      tau = clip(Kp e + Kd (w_target - w_rel), tau_max) + ff I a_target,   Kp = I (s wn)^2, Kd = 2 zeta I s wn
  e is the rotation from the bone to its target, w the angular velocities (the target's, through the delay's slope,
  against the bone's relative to its parent), a_target the target's angular acceleration.  The torque limit binds the
  correction only, never the feed-forward (the research, 4.3 rule 3: a total limit of a small woman's strength rounds the
  fast swings).  The child keeps its world rotation until its joint turns it, so a parent's acceleration drags it and a
  parent's stop lets it run on; there is no reaction on the parent (a one-way chain).  Semi-implicit Euler, SUBSTEPS per
  frame at least, more when the stiffest bone's wn dt would pass STEP_WN_DT (Tan 2011: coarse explicit steps diverge).
* Delays d (frames, at 30 fps), proximal to distal and centred on the elbow so that the hand arrives about when the key
  says (the research, 4.2): 肩 and 腕 -0.5, ひじ 0, 手首 +0.5 in a fast stretch; doubled where the arm moves slowly (the
  input's upper arm under SLOW_DEG_S[0] deg/s at its fastest within SLOW_WINDOW frames, a smoothstep to SLOW_DEG_S[1]).
  The lead (the same for every arm bone, another for 上半身..頭) takes back the tracking's own lag: the layer runs once with
  lead 0, the lag of the wrists' world velocity against the input's (cross-correlation, parabola-refined) is measured,
  and it runs again with that lead.
* Fingers: the spike's dynamic fingers missed the shape at the trace's keys by 47 to 62 degrees (p95), the fingers
  changing shape in 2 frames.  Here they are kinematic: their input turn relative to the wrist, read FINGER_DELAY frames
  after the wrist's time (a short delay; 0 makes them pass through on the hand's own timing).  They need no mass.  Where
  the input's fingers (手首 -> 中指３) turn faster than FINGER_SNAP_DEG_S (a smoothstep; spread FINGER_SNAP_PAD frames),
  that short delay goes too: a snap rides the hand's own timing.  (On the input's own frame instead, the fingers would
  lead the wrist: the a09 lag wrist -> finger went to -0.54 frames on the right, the reversed order the research warns
  against.)
* Where a pose must be met, the arm's delays go to 0 and it stiffens (the research, 4.2):
  - a hold (the a09 rest: the shoulder, elbow and wrist joints all under 5 deg/s, HOLD_MIN frames or more): from
    HOLD_SETTLE frames after its start (the run-on and settling happen first) to HOLD_EXIT frames before its end, delay 0
    and s up by HOLD_STIFF.  The target stands still there, so the delay's change is not seen.
  - a beat hold (--beats: a hold starting within KIME_BEAT frames of a beat): from KIME_LEAD frames before its start,
    delay 0, s up by KIME_STIFF and ff up by KIME_FF, so the hand arrives with the beat.
  - a hand at the face or the body (the input's middle finger tip within CONTACT_FACE_MM of the eyes or CONTACT_BODY_MM
    of the line 上半身 - 首, smoothsteps, spread CONTACT_PAD frames): delay 0, ff -> 1, s up by CONTACT_STIFF: the input
    there.
* One-frame jumps of the input (a target turning JUMP_DEG or more in one frame, JUMP_RATIO times the median step of the
  JUMP_WINDOW frames each way, and either JUMP_BIG_DEG or JUMP_NEXT_RATIO times either step next to it; the spike: 右腕
  1,899 -> 1,900 by 91 degrees, 左手首 5,963 -> 5,964 by 145, the right fingers 3,888 -> 3,889): found first and passed
  through.  The target is a step there (no interpolation, no velocity), the bone and its
  simulated descendants are put onto their targets when their target time crosses the jump, and the keys of that bone and
  its descendants go back to the input's over the frames around it (FALLBACK_RAMP frames in and out).
* Not solved, not rounded: where a dynamic bone stays far from its target (UNSOLVED_DEG with the torque limit binding for
  UNSOLVED_RUN frames, or UNSOLVED_HARD_DEG at all), its keys and its descendants' go back to the input's there.  Then the
  hands in the world, in rounds (FLOOR_ROUNDS), each widening what it gives back by 2 frames:
  - the floor: where a hand's tip comes closer to the eyes (input within FLOOR_RANGE_MM) or to the body line (within
    FLOOR_BODY_RANGE_MM) than floor_of(the input's distance) (FLOOR_MM closer within FLOOR_KNEE_MM, a FLOOR_SLOPE share
    of the rest further out), that arm and 上半身..頭 go back to the input's around it;
  - a lost hand: where a wrist is more than DEVIATION_CM from the input's even at its best within frames f-1 .. f+3 (late
    is allowed), that arm goes back (from the second round with 上半身..頭).
  - a wrist more than DEVIATION_SAME_CM from the input's on the same frame is lost too (the review: at 6,393 the
    right wrist was 10.9 cm off, which the late-allowed measure did not see).
  Every stretch given back is first widened while the layer's wrist is more than EDGE_DEV_CM from the input's on the
  same frame (at most EDGE_EXTEND frames each way), so that its ramps blend two trajectories that are close.  Then, up to
  SEAM_ROUNDS times, every edge where the wrist's step from one frame to the next passes the input's step by more than
  SEAM_STEP_CM is mended: its ramp doubled (up to SEAM_RAMP_MAX); at that length, where the layer itself steps so, the
  edge moved past that frame; and a stretch that gives back an arm but still steps inside (the trunk above it moves)
  gives back 上半身..頭 too.  Without this, the 4-frame ramp at 6,393 made the right wrist step 10.7 cm in one frame
  where the input moved 3.0 (now 3.0 and 3.0).  The report lists every stretch given back (fallback), every edge's
  largest step over the input's with the layer's own step there (seams) and what is left after the last round
  (floor_residual).
* How much it runs on (the review of 2026-10-10): the run-on past a stop is about (1 - ff) x speed / wn x g(zeta), g
  0.41 at zeta 0.85 and 0.46 at 0.7.  With ff 0.8 and the elbow at 8 Hz and the wrist at 9 Hz the default is stiff,
  and the damping is not what keeps it small: 0.85 -> 0.7 gives 1.12 times as much, ff 0.8 -> 0.4 three times, 9 -> 5 Hz
  1.8 times.  On the screen the hand's run-on is set by the upper arm and the elbow (the arm is 40 cm, the hand 12).
  --preset strong (PRESETS) softens the upper arm and the elbow to 3.5 Hz and feeds forward less (0.85, 0.75; the
  wrist 5 Hz, 0.5).
* Mass, inertia and strength (de Leva 1996, Holzbaur 2007; the constants below).  As Kp and Kd scale with the
  inertia, the motion does not depend on it until the torque limit binds: mass and inertia act only through the limit
  on the angular acceleration (limit / inertia), and that binds on 0.1 to 0.3 % of the substeps of the shoulder and the
  upper arm on the MV and never on the elbow and the wrist.  The shoulder girdle's limit has NO source (the shoulder's
  abduction is borrowed); it is what marks 1,893 - 1,898 and 6,395 - 6,396 as not solved on the MV.  The body's height is measured on the
  bones (頭先 above the floor: 1 unit = 8 cm), the body mass and the joints' strength are those of Holzbaur's subject F1
  (157.5 cm, 49.9 kg) scaled by (height / 1.575)^3 (geometric similarity: mass and torque as length^3).  Each segment's
  mass is its de Leva share of the body, its centre of mass and radius of gyration (the mean of the sagittal and the
  transverse one; the bodies here are isotropic) are de Leva's shares of the segment's length on the model's bones.  A
  joint's inertia is that of all the dynamic segments it carries, about the joint, in the rest pose.

The report (--report; in short on stdout) measures the input and the output by the analysts' definitions (copied from
their scripts: uncanny/a09_arcs/scripts/s04_timing.py and s06_valleys.py, a02_spacing/s13_dips.py and s05_spectrum.py,
a04_beat/s02_events.py; the same as the spike's measure.py): a09 (the joints' lag by cross-correlation, which joint
stops last before a rest, the run-on past a stop and the settling), a02 (deep speed dips per second, the 3-6 Hz and
6-15 Hz shares of the velocity), a04 (--beats: the stops' and the hard decelerations' timing against the beat, and the
shift of each stop against the input's), the error at the trace's keys (--key-frames: the frames of the 腕 keys of the
trace before smoothing; else every frame), the hand-to-face and hand-to-body distances, the jumps, the stretches given
back, the leads, the torque-limit share and the untouched bones' bytes.
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

FPS = 30.0
UNIT_M = 0.08                   # one model unit is 8 cm (the analysis pack's README; Rin's 頭先 is then 1.50 m up)
UNIT_MM = 80.0

# ---- the bones ------------------------------------------------------------------------------------
TRUNK = ("上半身", "上半身2")
NECK, HEAD, HEAD_TIP = "首", "頭", "頭先"
SIDES = ("左", "右")
ARM = (("肩", "girdle"), ("腕", "upper"), ("ひじ", "elbow"), ("手首", "wrist"))
FINGERS = (("親指", ("０", "１", "２")), ("人指", ("１", "２", "３")), ("中指", ("１", "２", "３")),
           ("薬指", ("１", "２", "３")), ("小指", ("１", "２", "３")))
TIPS = ("中指先", "中指３", "手首")       # the hand's tip for the distances, in order of preference
EYES = ("左目", "右目")
AXIAL = ("trunk", "neck", "head")

# ---- the body (sources) ------------------------------------------------------------------------------
# Holzbaur KRS, Delp SL, Gold GE, Murray WM (2007) Moment-generating capacity of upper limb muscles in healthy adults.
# J Biomech 40:2442, doi:10.1016/j.jbiomech.2006.11.013, Table 1, subject F1 (24 years, 157.5 cm, 49.9 kg): isometric
# peak moments, N m.  Read in the original by the research (RESEARCH.md 2.3).
F1_HEIGHT_M, F1_MASS_KG = 1.575, 49.9
TORQUE_F1 = {"upper": 31.6,       # shoulder abduction (adduction is 43.0: the smaller one is taken)
             "elbow": 23.5,       # elbow flexion (extension 23.1)
             "wrist": 10.3,       # wrist flexion (extension 6.7)
             "girdle": 31.6}      # NO source for the shoulder girdle: the shoulder's abduction is assumed
# 上半身 .. 頭 have no source in the research: their correction is not limited.
# de Leva P (1996) Adjustments to Zatsiorsky-Seluyanov's segment inertia parameters. J Biomech 29:1223-1230, Table 4,
# females.  Read in the original (an 8-page PDF of the paper, 2026-10-10).  (mass % of the body, centre of mass % of the
# length from the FIRST end, radius of gyration % of the length: the mean of the sagittal and the transverse one)
DE_LEVA_F = {"head": (6.68, 48.41, (27.1 + 29.5) / 2.0),           # VERT -> CERV (the alternative endpoints)
             "upper_trunk": (15.45, 50.50, (46.6 + 31.4) / 2.0),   # CERV -> XYPH (the alternative endpoints)
             "middle_trunk": (14.65, 45.12, (43.3 + 35.4) / 2.0),  # XYPH -> OMPH
             "upper_arm": (2.55, 57.54, (27.8 + 26.0) / 2.0),      # SJC -> EJC
             "forearm": (1.38, 45.59, (26.1 + 25.7) / 2.0),        # EJC -> WJC
             "hand": (0.56, 34.27, (24.4 + 20.8) / 2.0)}           # WJC -> DAC3 (the middle finger's tip; alternative)
HEAD_TIP_FALLBACK = 0.155       # without 頭先: the vertex this share of 頭's height above 頭 (Rin: 2.52 / 16.24 units)
HAND_FALLBACK = 0.65            # without finger bones: the hand this share of the forearm long (de Leva 170.1 / 262.4)

# ---- the layer ----------------------------------------------------------------------------------------
SUBSTEPS = 16                   # per frame (480 Hz; the spike), at least
STEP_WN_DT = 0.25               # more substeps when the stiffest bone's wn * dt would pass this
SLOW_DEG_S = (200.0, 400.0)     # the upper arm's speed: slow below (delays doubled), fast above (RESEARCH 4.2: ~300)
SLOW_WINDOW = 15                # frames each way for the fastest speed around a frame
FINGER_DELAY = 0.25             # frames the fingers read after the wrist
FINGER_SNAP_DEG_S = (1000.0, 2000.0)  # the input's fingers (手首 -> 中指３) turning faster: on their own frame
FINGER_SNAP_PAD = 3             # frames each way
HOLD_DEG_S = 5.0                # a09: a joint is still under this
HOLD_MIN = 4                    # frames: a hold (the research, 2.0)
HOLD_SETTLE = 6                 # frames after a hold's start before it stiffens (1 degree within 5-7 frames, 4.2)
HOLD_EXIT = 2                   # frames before a hold's end it lets go again
HOLD_RAMP = 3
HOLD_STIFF = 0.5                # s up by this share
KIME_BEAT = 2                   # frames from a beat for a beat hold
KIME_LEAD = 3                   # frames before the beat hold it is stiff (RESEARCH 4.2: "決めの 3 フレーム前から")
KIME_RAMP = 4
KIME_STIFF = 0.5                # wn x 1.5 (RESEARCH 4.2)
KIME_FF = 0.2                   # beta + 0.2 (RESEARCH 4.2)
CONTACT_FACE_MM = (70.0, 100.0)  # the tip to the eyes: all contact below, none above (the input's least is 58 mm)
CONTACT_BODY_MM = (60.0, 90.0)   # the tip to the line 上半身 - 首 (Rin's chest is about 9 cm deep each way)
CONTACT_PAD = 4                 # frames (RESEARCH 4.2: "その前後 4 フレーム")
CONTACT_STIFF = 1.0
JUMP_DEG = 60.0                 # a jump turns at least this in one frame,
JUMP_RATIO = 3.0                # this many times the median step of the JUMP_WINDOW frames each way,
JUMP_WINDOW = 4
JUMP_BIG_DEG = 90.0             # and either this much or JUMP_NEXT_RATIO times either step next to it (the fingers
JUMP_NEXT_RATIO = 2.5           # change shape over 2 frames at up to 1,700 deg/s: that is no jump)
FALLBACK_RAMP = 4               # frames in and out of a stretch given back to the input
JUMP_HOLD = (1, 2)              # frames before and after a jump's interval that are wholly the input's
UNSOLVED_DEG = 10.0
UNSOLVED_RUN = 2                # frames
UNSOLVED_HARD_DEG = 45.0
DEVIATION_CM = 8.0              # a wrist further than this from the input's, late allowed (the layer's p95: 4 cm)
DEVIATION_SAME_CM = 12.0        # or further than this on the same frame (the review: 10.9 cm at 6,393, late allowed 2)
EDGE_DEV_CM = 3.0               # a stretch given back widens while the layer's wrist is further than this (same frame)
EDGE_EXTEND = 12                # frames each way at most
SEAM_STEP_CM = 3.0              # an edge whose wrist steps more than the input's by this (cm/frame) gets a longer ramp
SEAM_RAMP_MAX = 16              # frames (the layer's own excess away from the edges: p99 2.6, p99.9 4.9-5.5)
SEAM_ROUNDS = 6
FLOOR_MM = 8.0                 # the hand may come this much closer than the input had it, within FLOOR_KNEE_MM,
FLOOR_KNEE_MM = 100.0
FLOOR_SLOPE = 0.25              # and further out this share of the distance beyond the knee more
FLOOR_RANGE_MM = 200.0          # (the face; the body FLOOR_BODY_RANGE_MM): no floor further out
FLOOR_BODY_RANGE_MM = 150.0
FLOOR_PAD = 2
FLOOR_ROUNDS = 5
LEAD_LIMIT = 2.0
SONG = (600, 7600)              # the analysts' frames for a02 (on the MV's 7,743 frames; a shorter motion: all)
ACTIVE = (167, 7661)            # a04's dancing part and the trace's keys (the same)


# A stronger set (--preset strong): the upper arm and the elbow softer and less of their target's acceleration fed
# forward (the research's table 4.2, the review of 2026-10-10: the run-on is set by ff and wn, hardly by the damping).
# The review's run of about this set on the MV (its "research"): the hands' run-on past the stops 1.6 to 1.9 times the
# default's (median), no more 3-6 Hz and no more deep dips (a02); 14.4 % of the bone-frames given back.
PRESETS = {"default": {},
           "strong": {"girdle": {"fn": 4.0, "zeta": 0.85, "ff": 0.9},
                      "upper": {"fn": 3.5, "zeta": 0.85, "ff": 0.85},
                      "elbow": {"fn": 3.5, "zeta": 0.8, "ff": 0.75},
                      "wrist": {"fn": 5.0, "zeta": 0.75, "ff": 0.5}}}


def default_params(preset="default"):
    """the classes' natural frequency (Hz), damping ratio, share of the target acceleration fed forward and delays
    (frames: fast, slow).  The default is mostly the spike's soft_wh with the research's centred delays; a preset
    (PRESETS) changes some classes' fn, zeta and ff."""
    if preset not in PRESETS:
        raise ValueError("no preset %r (there are %s)" % (preset, ", ".join(sorted(PRESETS))))
    p = _base_params()
    for c, v in PRESETS[preset].items():
        p["classes"][c].update(v)
    p["preset"] = preset
    return p


def _base_params():
    return {"classes": {"trunk": {"fn": 6.0, "zeta": 0.85, "ff": 0.8, "delay": (0.0, 0.0)},
                        "neck": {"fn": 7.0, "zeta": 0.85, "ff": 0.8, "delay": (0.0, 0.0)},
                        "head": {"fn": 7.0, "zeta": 0.85, "ff": 0.8, "delay": (0.0, 0.0), "world": True},
                        "girdle": {"fn": 7.0, "zeta": 0.85, "ff": 0.8, "delay": (-0.5, -1.0)},
                        "upper": {"fn": 7.0, "zeta": 0.85, "ff": 0.8, "delay": (-0.5, -1.0)},
                        "elbow": {"fn": 8.0, "zeta": 0.85, "ff": 0.8, "delay": (0.0, 0.0)},
                        "wrist": {"fn": 9.0, "zeta": 0.85, "ff": 0.8, "delay": (0.5, 1.0)},
                        "finger": {"kinematic": True, "delay": None}},     # None: the wrist's
            "finger_delay": FINGER_DELAY, "delay_scale": 1.0, "torque_scale": 1.0, "lead": None,
            "substeps": SUBSTEPS, "slow": True, "holds": True, "kime": True, "contact": True, "floor": True,
            "unsolved": True, "jumps": True, "snap": True, "seams": True}


# ---- quaternions on numpy arrays (x, y, z, w), Hamilton, v' = q v q^-1 (mmd_cli.fk) -------------------

def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    out = np.array(q, dtype=np.float64, copy=True)
    out[..., :3] *= -1.0
    return out


def qnorm(q):
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def qrot(q, v):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], axis=-1)


def qlog(q):
    """rotation vectors (radians) of unit quaternions, the short way"""
    q = np.where(q[..., 3:4] < 0, -q, q)
    v = q[..., :3]
    s = np.linalg.norm(v, axis=-1)
    ang = 2.0 * np.arctan2(s, np.clip(q[..., 3], -1.0, 1.0))
    k = np.where(s > 1e-12, ang / np.maximum(s, 1e-12), 2.0)
    return v * k[..., None]


def qexp(r):
    a = np.linalg.norm(r, axis=-1)
    h = 0.5 * a
    k = np.where(a > 1e-12, np.sin(h) / np.maximum(a, 1e-12), 0.5)
    return np.concatenate([r * k[..., None], np.cos(h)[..., None]], axis=-1)


def qslerp(a, b, t):
    """a to b the short way, t in [0, 1] (arrays broadcast)"""
    d = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(d < 0, -b, b)
    return qnorm(qmul(a, qexp(qlog(qnorm(qmul(qconj(a), b))) * np.asarray(t, dtype=np.float64)[..., None])))


def qangle_deg(a, b):
    d = np.abs(np.sum(a * b, axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))


def continuous(q):
    """the same rotations with the sign of each chosen next to the one before (along the first axis)"""
    q = np.array(q, dtype=np.float64, copy=True)
    for t in range(1, len(q)):
        flip = np.sum(q[t] * q[t - 1], axis=-1) < 0
        q[t] = np.where(np.asarray(flip)[..., None], -q[t], q[t])
    return q


IDENT = np.array([0.0, 0.0, 0.0, 1.0])


# ---- small helpers ----------------------------------------------------------------------------------

def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def falling(x, lo, hi):
    return 1.0 - smoothstep((np.asarray(x, dtype=np.float64) - lo) / (hi - lo))


def max_filter(v, radius):
    out = np.array(v, dtype=np.float64, copy=True)
    for k in range(1, radius + 1):
        out[k:] = np.maximum(out[k:], v[:-k])
        out[:-k] = np.maximum(out[:-k], v[k:])
    return out


def ramp_weight(n, pieces):
    """a weight per frame from (rise_start, rise_end, fall_start, fall_end) pieces: 0 before rise_start, a smoothstep up
    to 1 at rise_end, 1 to fall_start, a smoothstep down to 0 at fall_end; the max over the pieces"""
    w = np.zeros(n)
    f = np.arange(n, dtype=np.float64)
    for a, b, c, d in pieces:
        up = np.ones(n) if b <= a else smoothstep((f - a) / (b - a))
        down = np.ones(n) if d <= c else 1.0 - smoothstep((f - c) / (d - c))
        piece = np.where(f < a, 0.0, np.where(f > d, 0.0, np.minimum(up, down)))
        w = np.maximum(w, piece)
    return w


def runs(mask):
    """[first, last] of the runs of True"""
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([start, i - 1])
            start = None
    return out


def _r(value, places=3):
    return None if value is None else round(float(value), places) + 0.0


# ---- the model and the motion -------------------------------------------------------------------------

class Skeleton:
    def __init__(self, model):
        self.bones = model.bones
        self.index = {}
        for b in self.bones:
            self.index.setdefault(b.name, b.index)
        for b in self.bones:
            if b.position is None:
                raise ValueError("bone %r has no rest position" % b.name)
        self.rest = np.array([b.position for b in self.bones], dtype=np.float64)

    def has(self, name):
        return name in self.index

    def i(self, name):
        return self.index[name]

    def parent(self, k):
        return self.bones[k].parent

    def append_of(self, k):
        """(parent, ratio, rotates, translates) of the bone's append, or None (mmd_cli.fk.Pose._appends)"""
        b = self.bones[k]
        a = b.append
        if a is None or a.get("parent") is None:
            return None
        rot, tr = bool(b.flags.get("append_rotate")), bool(b.flags.get("append_translate"))
        if not (rot or tr):
            return None
        return a["parent"], float(a["ratio"]), rot, tr

    def closure(self, ks):
        """the bones ks with all their ancestors and append parents, each after its parent and append parent"""
        need, stack = set(), list(ks)
        while stack:
            k = stack.pop()
            if k in need:
                continue
            need.add(k)
            if self.parent(k) is not None:
                stack.append(self.parent(k))
            a = self.append_of(k)
            if a is not None:
                stack.append(a[0])
        order, placed = [], set()

        def place(k, depth=0):
            if k in placed:
                return
            if depth > len(self.bones):
                raise ValueError("the bones of %r go round in a loop" % self.bones[k].name)
            if self.parent(k) is not None:
                place(self.parent(k), depth + 1)
            a = self.append_of(k)
            if a is not None:
                place(a[0], depth + 1)
            placed.add(k)
            order.append(k)
        for k in sorted(need):
            place(k)
        return order


def sample_keys(motion, skel, idx, frames):
    """bone index -> (positions [F, 3], rotations as applied [F, 4]) of the key values MMD shows on every frame
    (mmd_cli.fk.sample), for the bones with keys"""
    tracks = fk.tracks_of(motion)
    out = {}
    for k in idx:
        name = skel.bones[k].name
        keys = tracks.get(name) or tracks.get(fk.vmd_name(name))
        if not keys:
            continue
        kf = [kk.frame for kk in keys]
        P = np.zeros((frames, 3))
        R = np.zeros((frames, 4))
        for f in range(frames):
            p, r = fk.sample(keys, f, kf)
            P[f] = p
            R[f] = fk.applied(r)
        out[k] = (P, continuous(R))
    return out


def fk_all(skel, keys, order, frames):
    """world positions [F, 3] and rotations [F, 4] of the bones `order` (ancestors first) from key arrays (missing =
    rest): the rule of mmd_cli.fk.Pose.world, appends of rotation (q^ratio) and translation included"""
    ident = np.zeros((frames, 4))
    ident[:, 3] = 1.0
    zero = np.zeros((frames, 3))
    local = {}

    def loc(k):
        if k in local:
            return local[k]
        P, R = keys.get(k, (zero, ident))
        a = skel.append_of(k)
        if a is not None:
            pp, pr = loc(a[0])
            if a[2]:
                R = qmul(R, qexp(qlog(pr) * a[1]))
            if a[3]:
                P = P + a[1] * pp
        local[k] = (P, R)
        return local[k]
    wpos, wrot = {}, {}
    for k in order:
        P, R = loc(k)
        par = skel.parent(k)
        if par is None:
            wpos[k] = skel.rest[k] + P
            wrot[k] = R
        else:
            wpos[k] = wpos[par] + qrot(wrot[par], skel.rest[k] - skel.rest[par] + P)
            wrot[k] = qmul(wrot[par], R)
    return wpos, wrot


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


# ---- which bones, their classes, their bodies ------------------------------------------------------------

def simulated_bones(skel):
    """(name, class, side) of the simulated bones present, parents first.  A bone with an append is left out (it is
    an intermediate such as 肩C)"""
    out = []

    def add(name, cls, side):
        if skel.has(name) and skel.append_of(skel.i(name)) is None:
            out.append((name, cls, side))
    for n in TRUNK:
        add(n, "trunk", None)
    add(NECK, "neck", None)
    add(HEAD, "head", None)
    for s in SIDES:
        for n, cls in ARM:
            add(s + n, cls, s)
        for fname, parts in FINGERS:
            for p in parts:
                add(s + fname + p, "finger", s)
    return out


def point_names(skel):
    names = ["センター", "下半身", "腰", "上半身", "上半身2", NECK, HEAD, HEAD_TIP, "両目", "左足ＩＫ", "右足ＩＫ"] + list(EYES)
    for s in SIDES:
        names += [s + n for n in ("肩", "腕", "ひじ", "手首", "中指１", "中指２", "中指３", "中指先", "手捩", "腕捩")]
    return [n for n in names if skel.has(n)]


def body_of(skel):
    """height (m) on the bones, mass (kg) and the strength scale (Holzbaur's F1 by (height / 1.575)^3)"""
    if skel.has(HEAD_TIP):
        top = skel.rest[skel.i(HEAD_TIP)][1]
    elif skel.has(HEAD):
        top = skel.rest[skel.i(HEAD)][1] * (1.0 + HEAD_TIP_FALLBACK)
    else:
        top = float(skel.rest[:, 1].max())
    floor_ = 0.0
    for s in SIDES:
        for n in ("つま先", "足首"):
            if skel.has(s + n):
                floor_ = min(floor_, skel.rest[skel.i(s + n)][1])
    height = (top - floor_) * UNIT_M
    scale = (height / F1_HEIGHT_M) ** 3
    return {"height_m": height, "mass_kg": F1_MASS_KG * scale, "strength_scale": scale,
            "source": "height: 頭先 above the floor on the bones; mass and torque: Holzbaur 2007 F1 x (h / 1.575)^3"}


def segment_of(skel, name, cls, side):
    """(first end, second end, de Leva row) of the bone's own body, or None (the neck, the shoulder girdle and the
    fingers have none of their own: the head, the upper trunk and the hand carry them)"""
    def p(n):
        return skel.rest[skel.i(n)] if skel.has(n) else None
    if name == "上半身" and p("上半身2") is not None:
        return p("上半身2"), p("上半身"), "middle_trunk"
    if name == "上半身2" and p(NECK) is not None:
        return p(NECK), p("上半身2"), "upper_trunk"
    if name == HEAD:
        base = p(NECK) if p(NECK) is not None else p(HEAD)
        vertex = p(HEAD_TIP)
        if vertex is None:
            vertex = p(HEAD) + np.array([0.0, p(HEAD)[1] * HEAD_TIP_FALLBACK, 0.0])
        return vertex, base, "head"
    if cls == "upper" and p(side + "ひじ") is not None:
        return p(name), p(side + "ひじ"), "upper_arm"
    if cls == "elbow" and p(side + "手首") is not None:
        return p(name), p(side + "手首"), "forearm"
    if cls == "wrist":
        tip = p(side + "中指先")
        if tip is None and p(side + "中指３") is not None and p(side + "中指２") is not None:
            tip = p(side + "中指３") + 0.8 * (p(side + "中指３") - p(side + "中指２"))
        if tip is None and p(side + "ひじ") is not None:
            tip = p(name) + HAND_FALLBACK * (p(name) - p(side + "ひじ"))
        if tip is not None:
            return p(name), tip, "hand"
    return None


# ---- the plan: the input, the targets and the schedules ---------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    world_in: dict
    world_out: dict


class Plan:
    def __init__(self, model, motion, params, beats=None, key_frames=None, log=None):
        self.log = log or (lambda *_: None)
        self.p = params
        self.motion = motion
        self.skel = sk = Skeleton(model)
        self.sim = simulated_bones(sk)
        if not self.sim:
            raise ValueError("the model has none of the bones the layer moves (上半身, 腕, ひじ, 手首, ...)")
        self.names = [n for n, _, _ in self.sim]
        self.cls = [c for _, c, _ in self.sim]
        self.side = [s for _, _, s in self.sim]
        self.nb = nb = len(self.sim)
        self.bi = [sk.i(n) for n in self.names]
        simset = set(self.bi)
        # the simulated parent: the nearest simulated ancestor (-1: none; the frame is then the model parent's input)
        self.sp = []
        for k in self.bi:
            a = sk.parent(k)
            while a is not None and a not in simset:
                if sk.append_of(a) is not None and sk.append_of(a)[0] in simset:
                    raise ValueError("bone %r between simulated bones takes its turn from a simulated bone"
                                     % sk.bones[a].name)
                a = sk.parent(a)
            self.sp.append(self.bi.index(a) if a is not None else -1)
        self.mparent = [sk.parent(k) for k in self.bi]
        cp = params["classes"]
        self.kin = np.array([bool(cp[c].get("kinematic")) for c in self.cls])
        self.world = np.array([bool(cp[c].get("world")) for c in self.cls])
        for j in range(nb):
            if not self.kin[j] and self.sp[j] >= 0 and self.kin[self.sp[j]]:
                raise ValueError("a dynamic bone %r under a kinematic one" % self.names[j])
        self.children = {j: [c for c in range(nb) if self.sp[c] == j] for j in range(nb)}
        self.points = point_names(sk)
        self.order = sk.closure(self.bi + [sk.i(n) for n in self.points])
        self.F = fk.last_frame(motion) + 1
        if self.F < 3:
            raise ValueError("the motion is shorter than 3 frames")
        F = self.F
        self.log("sampling %d bones over %d frames" % (len(self.order), F))
        self.keys = sample_keys(motion, sk, self.order, F)
        wpos, wrot = fk_all(sk, self.keys, self.order, F)
        self.world_in = {sk.bones[k].name: (wpos[k], wrot[k]) for k in self.order}
        self.wrot_in = wrot
        ident = np.tile(IDENT, (F, 1))
        # the frame each target is read in, the input's local in it, the output parent's frame of the input (M)
        self.Rtf = np.zeros((F, nb, 4))
        self.Rroot = np.zeros((F, nb, 4))
        self.M = np.zeros((F, nb, 4))
        for j, k in enumerate(self.bi):
            par = self.bi[self.sp[j]] if self.sp[j] >= 0 else self.mparent[j]
            Rpar = wrot[par] if par is not None else ident
            self.Rroot[:, j] = continuous(Rpar)
            self.Rtf[:, j] = ident if self.world[j] else Rpar
            mp = self.mparent[j]
            Rmp = wrot[mp] if mp is not None else ident
            self.M[:, j] = qnorm(qmul(qconj(Rpar), Rmp))
        self.qt = qnorm(qmul(qconj(self.Rtf), np.stack([wrot[k] for k in self.bi], axis=1)))
        self.qt = continuous(self.qt)
        self.key_in = np.stack([self.keys[k][1] if k in self.keys else ident for k in self.bi], axis=1)
        self.pos_in = np.stack([self.keys[k][0] if k in self.keys else np.zeros((F, 3)) for k in self.bi], axis=1)
        self.body = body_of(sk)
        self.inertia()
        self.find_jumps()
        self.rates()
        self.beats = beats
        self.key_frames = key_frames
        self.schedules()

    # ---- the bodies ----
    def inertia(self):
        sk, nb = self.skel, self.nb
        mass = self.body["mass_kg"]
        seg = {}
        for j, (name, cls, side) in enumerate(self.sim):
            if self.kin[j]:
                continue
            s = segment_of(sk, name, cls, side)
            if s is None:
                continue
            a, b, row = s
            share, com_pct, r_pct = DE_LEVA_F[row]
            L = np.linalg.norm(b - a) * UNIT_M
            seg[j] = (share / 100.0 * mass, (a + com_pct / 100.0 * (b - a)) * UNIT_M, r_pct / 100.0 * L, row)
        self.segments = seg
        I = np.zeros(nb)
        for j in range(nb):
            if self.kin[j]:
                continue
            joint = sk.rest[self.bi[j]] * UNIT_M
            stack, tot = [j], 0.0
            while stack:
                c = stack.pop()
                if c in seg:
                    m, com, r, _ = seg[c]
                    tot += m * (float(np.sum((com - joint) ** 2)) + r * r)
                stack.extend(self.children[c])
            I[j] = max(tot, 1e-7)
        self.I = I
        scale = self.body["strength_scale"] * float(self.p.get("torque_scale", 1.0))
        self.tmax = np.array([TORQUE_F1[c] * scale if c in TORQUE_F1 else np.inf for c in self.cls])

    # ---- one-frame jumps of the targets ----
    def find_jumps(self):
        F, nb = self.F, self.nb
        steps = qangle_deg(self.qt[1:], self.qt[:-1])                      # [F-1, nb]: frame f -> f+1
        J = np.zeros((F - 1, nb), bool)
        if self.p.get("jumps", True):
            prev = np.vstack([np.zeros((1, nb)), steps[:-1]])
            nxt = np.vstack([steps[1:], np.zeros((1, nb))])
            around = np.zeros_like(steps)
            for f in np.nonzero((steps >= JUMP_DEG).any(axis=1))[0]:
                lo, hi = max(0, f - JUMP_WINDOW), min(len(steps), f + JUMP_WINDOW + 1)
                around[f] = np.median(np.delete(steps[lo:hi], f - lo, axis=0), axis=0)
            J = ((steps >= JUMP_DEG) & (steps >= JUMP_RATIO * around)
                 & ((steps >= JUMP_BIG_DEG) | (steps >= JUMP_NEXT_RATIO * np.maximum(prev, nxt))))
        self.J = J
        self.jumps = [{"bone": self.names[j], "frame": int(f), "deg": _r(steps[f, j], 1)}
                      for f, j in zip(*np.nonzero(J))]
        self.jumps.sort(key=lambda r: (r["frame"], r["bone"]))

    def rates(self):
        """the targets' angular velocity and acceleration (rad/s, rad/s/s, in the target's frame) per frame, the jumps
        left out (the side next to a jump uses the other side's step)"""
        F = self.F
        valid = (~self.J).astype(np.float64)[..., None]
        s = qlog(qnorm(qmul(self.qt[1:], qconj(self.qt[:-1])))) * valid        # [F-1, nb, 3]

        def average(steps, ok):
            num = np.zeros((F,) + steps.shape[1:])
            den = np.zeros((F,) + steps.shape[1:2] + (1,))
            num[1:] += steps
            den[1:] += ok
            num[:-1] += steps
            den[:-1] += ok
            return num / np.maximum(den, 1.0) * FPS
        self.wt = average(s, valid)
        self.at = average((self.wt[1:] - self.wt[:-1]) * valid, valid)
        Rr = self.Rroot
        sr = qlog(qnorm(qmul(Rr[1:], qconj(Rr[:-1]))))
        ones = np.ones(sr.shape[:2] + (1,))
        self.wroot = average(sr, ones)

    # ---- where the arm slows, holds, meets a beat or the face ----
    def joint_speeds(self, side):
        W = self.world_in
        out = {}
        for j, (a, b) in (("shoulder", (side + "肩", side + "腕")), ("elbow", (side + "腕", side + "ひじ")),
                          ("wrist", (side + "ひじ", side + "手首"))):
            if a in W and b in W:
                out[j] = angular_speed(rel(W, a, b))
        return out

    def schedules(self):
        F, nb, cp = self.F, self.nb, self.p["classes"]
        scale = float(self.p.get("delay_scale", 1.0))
        fast = np.zeros(nb)
        slow = np.zeros(nb)
        extra = np.zeros(nb)
        for j, c in enumerate(self.cls):
            d = cp[c].get("delay")
            if c == "finger" and d is None:
                d = cp["wrist"].get("delay", (0.0, 0.0))
            fd = float(self.p.get("finger_delay", 0.0)) if c == "finger" else 0.0
            fast[j], slow[j], extra[j] = (d[0] + fd) * scale, (d[1] + fd) * scale, fd * scale
        slowness = np.zeros((F, nb))
        hold = np.zeros((F, nb))
        kime = np.zeros((F, nb))
        contact = np.zeros((F, nb))
        snap = np.zeros((F, nb))
        self.holds, self.kimes, self.contacts, self.snaps = {}, {}, {}, {}
        beat_frames = None
        if self.beats is not None:
            t0, per = self.beats
            n = np.arange(0, int((F / FPS - t0) / per) + 2)
            beat_frames = (t0 + n * per) * FPS
        for s in SIDES:
            cols = [j for j in range(nb) if self.side[j] == s]
            if not cols:
                continue
            sp = self.joint_speeds(s)
            if "shoulder" in sp and self.p.get("slow", True):
                v = np.concatenate([sp["shoulder"], sp["shoulder"][-1:]])
                slowness[:, cols] = falling(max_filter(v, SLOW_WINDOW), *SLOW_DEG_S)[:, None]
            if len(sp) == 3:
                rs = rests(sp["shoulder"], sp["elbow"], sp["wrist"], HOLD_DEG_S, HOLD_MIN)
                pieces_h, pieces_k, kl = [], [], []
                for a, b in rs:
                    if b - a >= HOLD_SETTLE + 2 * HOLD_RAMP + HOLD_EXIT:
                        pieces_h.append((a + HOLD_SETTLE, a + HOLD_SETTLE + HOLD_RAMP, b - HOLD_EXIT - HOLD_RAMP,
                                         b - HOLD_EXIT))
                    if beat_frames is not None and np.min(np.abs(beat_frames - a)) <= KIME_BEAT:
                        end = max(a + 1, b - HOLD_EXIT)
                        pieces_k.append((a - KIME_LEAD - KIME_RAMP, a - KIME_LEAD, max(a, end - HOLD_RAMP), end))
                        kl.append([int(a), int(b)])
                self.holds[s] = [[int(a), int(b)] for a, b in rs]
                self.kimes[s] = kl
                if self.p.get("holds", True):
                    hold[:, cols] = ramp_weight(F, pieces_h)[:, None]
                if self.p.get("kime", True):
                    kime[:, cols] = ramp_weight(F, pieces_k)[:, None]
            tip = tip_of(self.world_in, s)
            if tip is not None and self.p.get("contact", True):
                c = np.zeros(F)
                for fn, limits in ((face_distance, CONTACT_FACE_MM), (body_distance, CONTACT_BODY_MM)):
                    dist = fn(self.world_in, tip)
                    if dist is not None:
                        c = np.maximum(c, falling(dist, *limits))
                c = max_filter(c, CONTACT_PAD)
                c = np.convolve(np.pad(c, 2, mode="edge"), np.ones(5) / 5.0, mode="valid")
                contact[:, cols] = c[:, None]
                self.contacts[s] = runs(c > 0.5)
            fcols = [j for j in cols if self.cls[j] == "finger"]
            if fcols and s + "手首" in self.world_in and s + "中指３" in self.world_in and self.p.get("snap", True):
                v = angular_speed(rel(self.world_in, s + "手首", s + "中指３"))
                v = np.concatenate([v, v[-1:]])
                g = smoothstep((v - FINGER_SNAP_DEG_S[0]) / (FINGER_SNAP_DEG_S[1] - FINGER_SNAP_DEG_S[0]))
                g = max_filter(g, FINGER_SNAP_PAD)
                g = np.convolve(np.pad(g, 2, mode="edge"), np.ones(5) / 5.0, mode="valid")
                snap[:, fcols] = g[:, None]
                self.snaps[s] = runs(g > 0.5)
        base = fast[None, :] + (slow - fast)[None, :] * slowness
        base = base - extra[None, :] * snap                     # a snap: the fingers on the wrist's own time
        off = np.maximum(np.maximum(hold, kime), contact)
        self.D = base * (1.0 - off)
        self.WS = 1.0 + np.maximum(np.maximum(HOLD_STIFF * hold, KIME_STIFF * kime), CONTACT_STIFF * contact)
        ff = np.array([cp[c].get("ff", 1.0) for c in self.cls])[None, :] * np.ones((F, 1))
        ff = ff + (np.minimum(1.0, ff + KIME_FF) - ff) * kime
        self.FF = ff + (1.0 - ff) * contact
        self.Dp = np.gradient(self.D, axis=0) if F > 1 else np.zeros_like(self.D)
        self.Dp = np.clip(self.Dp, -0.8, 0.8)
        self.snap = snap
        self.weights = {"slowness": slowness, "hold": hold, "kime": kime, "contact": contact, "snap": snap}



def floor_of(d_in):
    """the least distance (mm) the output may keep where the input keeps d_in"""
    return d_in - FLOOR_MM - FLOOR_SLOPE * np.maximum(0.0, d_in - FLOOR_KNEE_MM)


def face_point(W):
    if all(e in W for e in EYES):
        return 0.5 * (W[EYES[0]][0] + W[EYES[1]][0])
    return W[HEAD][0] if HEAD in W else None


def face_distance(W, tip):
    p = face_point(W)
    return None if p is None else np.linalg.norm(W[tip][0] - p, axis=1) * UNIT_MM


def body_distance(W, tip):
    if "上半身" not in W or NECK not in W:
        return None
    a, b = W["上半身"][0], W[NECK][0]
    ab = b - a
    p = W[tip][0]
    t = np.clip(np.sum((p - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1) * UNIT_MM


def tip_of(W, side):
    return next((side + t for t in TIPS if side + t in W), None)


# ---- the simulation ---------------------------------------------------------------------------------------

def target_at(plan, j_idx, tb):
    """the targets of the bones j_idx at their target times tb (step across a jump): (q, i0, fr)"""
    F = plan.F
    tb = np.clip(tb, 0.0, F - 1.0)
    i0 = np.minimum(np.floor(tb).astype(int), F - 2)
    fr = tb - i0
    jm = plan.J[i0, j_idx]
    frq = np.where(jm, (fr >= 0.5).astype(np.float64), fr)
    q = qslerp(plan.qt[i0, j_idx], plan.qt[i0 + 1, j_idx], frq)
    return q, i0, fr


def simulate(plan, leads):
    """run the dynamic bones; returns the local rotations [F, nb, 4] of every simulated bone relative to its output
    simulated parent (roots: the model parent's input frame), the tracking error (deg, the largest in each frame) and
    the share of substeps with the correction at its limit, per dynamic bone"""
    F, nb, p = plan.F, plan.nb, plan.p
    sub = int(p.get("substeps", SUBSTEPS))
    cp = p["classes"]
    dyn = [j for j in range(nb) if not plan.kin[j]]
    kin = [j for j in range(nb) if plan.kin[j]]
    nd = len(dyn)
    lead = np.array([leads["axial" if plan.cls[j] in AXIAL else "arm"] for j in range(nb)])
    local = np.zeros((F, nb, 4))
    err = np.zeros((F, nb))
    clip = np.zeros((F, nb))
    # kinematic bones: the target at the delayed time, on every frame
    frames = np.arange(F, dtype=np.float64)
    for j in kin:
        tb = frames + lead[j] - plan.D[:, j]
        q, _, _ = target_at(plan, np.full(F, j), tb)
        local[:, j] = q
    if nd:
        D = np.array(dyn)
        pos = {j: i for i, j in enumerate(dyn)}
        par = np.array([pos[plan.sp[j]] if plan.sp[j] >= 0 else -1 for j in dyn])
        has_par = par >= 0
        world = plan.world[D]
        I = plan.I[D]
        wn = 2.0 * np.pi * np.array([cp[plan.cls[j]]["fn"] for j in dyn])
        zeta = np.array([cp[plan.cls[j]]["zeta"] for j in dyn])
        Kp0, Kd0 = I * wn ** 2, 2.0 * zeta * I * wn
        tmax = plan.tmax[D]
        Dd, Dpd, WSd, FFd = plan.D[:, D], plan.Dp[:, D], plan.WS[:, D], plan.FF[:, D]
        Jd = plan.J[:, D]
        qt, wt, at = plan.qt[:, D], plan.wt[:, D], plan.at[:, D]
        Rroot, wroot = plan.Rroot[:, D], plan.wroot[:, D]
        leadd = lead[D]
        rows = np.arange(nd)
        desc = {i: [c for c in range(nd) if c != i and is_desc(par, c, i)] for i in range(nd)}
        # stability: the stiffest bone must not turn more than STEP_WN_DT radians of its own period in one step
        sub = max(sub, int(math.ceil(float(np.max(wn[None, :] * WSd)) / (STEP_WN_DT * FPS))))
        plan.substeps_used = sub
        dt = 1.0 / (FPS * sub)

        def targets(t):
            fi = min(int(t), F - 2)
            ft = t - fi
            d = Dd[fi] * (1 - ft) + Dd[fi + 1] * ft
            dd = Dpd[fi] * (1 - ft) + Dpd[fi + 1] * ft
            tb = np.clip(t + leadd - d, 0.0, F - 1.0)
            i0 = np.minimum(np.floor(tb).astype(int), F - 2)
            fr = tb - i0
            jm = Jd[i0, rows]
            frq = np.where(jm, (fr >= 0.5).astype(np.float64), fr)
            qtar = qslerp(qt[i0, rows], qt[i0 + 1, rows], frq)
            k = (1.0 - dd)[:, None]
            wtar = (wt[i0, rows] * (1 - fr)[:, None] + wt[i0 + 1, rows] * fr[:, None]) * k
            atar = (at[i0, rows] * (1 - fr)[:, None] + at[i0 + 1, rows] * fr[:, None]) * k * k
            Rr = qslerp(Rroot[fi], Rroot[fi + 1], np.full(nd, ft))
            Wr = wroot[fi] * (1 - ft) + wroot[fi + 1] * ft
            return tb, qtar, wtar, atar, Rr, Wr, fi, ft

        def parents(R, W, Rr, Wr):
            Rp = np.where(has_par[:, None], R[np.maximum(par, 0)], Rr)
            Wp = np.where(has_par[:, None], W[np.maximum(par, 0)], Wr)
            Rp = np.where(world[:, None], IDENT[None, :], Rp)
            Wp = np.where(world[:, None], 0.0, Wp)
            return Rp, Wp

        tb, qtar, wtar, atar, Rr, Wr, _, _ = targets(0.0)
        R = np.zeros((nd, 4))
        W = np.zeros((nd, 3))
        for i in range(nd):                           # parents first
            Rp, Wp = parents(R, W, Rr, Wr)
            R[i] = qnorm(qmul(Rp[i], qtar[i]))
            W[i] = Wp[i] + qrot(Rp[i], wtar[i])
        outR = np.zeros((F, nd, 4))
        outR[0] = R
        m_prev = np.floor(tb - 0.5).astype(int)
        nsteps = (F - 1) * sub
        started = time.time()
        for k in range(1, nsteps + 1):
            t = (k - 1) / sub
            tb, qtar, wtar, atar, Rr, Wr, fi, ft = targets(t)
            m = np.floor(tb - 0.5).astype(int)
            cross = (m > m_prev) & (m >= 0) & (m <= F - 2)
            m_prev = m
            if cross.any():
                hit = [i for i in np.nonzero(cross)[0] if Jd[m[i], i]]
                for i in hit:                         # a jump: onto the target, the descendants carried along
                    Rp, Wp = parents(R, W, Rr, Wr)
                    oldR, oldW = {i: R[i].copy()}, {i: W[i].copy()}
                    R[i] = qnorm(qmul(Rp[i], qtar[i]))
                    W[i] = Wp[i] + qrot(Rp[i], wtar[i])
                    for c in desc[i]:
                        pc = par[c]
                        if pc not in oldR:
                            continue
                        oldR[c], oldW[c] = R[c].copy(), W[c].copy()
                        turn = qmul(R[pc], qconj(oldR[pc]))
                        R[c] = qnorm(qmul(turn, R[c]))
                        W[c] = W[pc] + qrot(turn, W[c] - oldW[pc])
            Rp, Wp = parents(R, W, Rr, Wr)
            Rtar = qmul(Rp, qtar)
            e = qlog(qnorm(qmul(Rtar, qconj(R))))
            wrel_t = qrot(Rp, wtar)
            s = WSd[fi] * (1 - ft) + WSd[fi + 1] * ft
            fb = (Kp0 * s * s)[:, None] * e + (Kd0 * s)[:, None] * (wrel_t - (W - Wp))
            n = np.linalg.norm(fb, axis=1)
            over = n > tmax
            if over.any():
                fb[over] *= (tmax[over] / n[over])[:, None]
            ffv = FFd[fi] * (1 - ft) + FFd[fi + 1] * ft
            tau = fb + (ffv * I)[:, None] * qrot(Rp, atar)
            W = W + dt * tau / I[:, None]
            R = qnorm(qmul(qexp(W * dt), R))
            err[fi, D] = np.maximum(err[fi, D], np.degrees(np.linalg.norm(e, axis=1)))
            clip[fi, D] += over
            if k % sub == 0:
                outR[k // sub] = R
            if k % (sub * 2000) == 0:
                plan.log("  frame %d (%.0f s)" % (k // sub, time.time() - started))
        clip /= sub
        Rpo = np.where(has_par[None, :, None], outR[:, np.maximum(par, 0)], Rroot)
        local[:, D] = qnorm(qmul(qconj(Rpo), outR))
    return local, err, clip


def is_desc(par, c, i):
    a = par[c]
    while a >= 0:
        if a == i:
            return True
        a = par[a]
    return False


# ---- the layer ------------------------------------------------------------------------------------------------

def keys_of(plan, local):
    """the key rotations (as applied) for the local rotations relative to the simulated parents"""
    return continuous(qnorm(qmul(qconj(plan.M), local)))


def world_with(plan, key_rot):
    keys = dict(plan.keys)
    for j, k in enumerate(plan.bi):
        keys[k] = (plan.pos_in[:, j], key_rot[:, j])
    wpos, wrot = fk_all(plan.skel, keys, plan.order, plan.F)
    return {plan.skel.bones[k].name: (wpos[k], wrot[k]) for k in plan.order}


def lag_of(a, b, maxlag=6):
    """lag (frames, + = b later) of the vector signal b against a: cross-correlation, parabola-refined; None when flat"""
    if len(a) <= 2 * maxlag + 2 or float(np.sum(a * a)) < 1e-12:
        return None
    cs = []
    for L in range(-maxlag, maxlag + 1):
        cs.append(np.sum(a[:len(a) - L] * b[L:]) if L >= 0 else np.sum(a[-L:] * b[:len(b) + L]))
    cs = np.array(cs)
    i = int(np.argmax(cs))
    if i in (0, len(cs) - 1):
        return float(i - maxlag)
    x, y, z = cs[i - 1], cs[i], cs[i + 1]
    den = x - 2 * y + z
    return float(i - maxlag + (0.5 * (x - z) / den if den != 0 else 0.0))


def measure_lags(plan, world_out):
    lo, hi = song_range(plan.F)
    out = {}
    for group, names in (("arm", [s + "手首" for s in SIDES]), ("axial", [NECK, HEAD])):
        lags = []
        for n in names:
            if n in world_out:
                a = np.diff(plan.world_in[n][0][lo:hi], axis=0)
                b = np.diff(world_out[n][0][lo:hi], axis=0)
                lag = lag_of(a, b)
                if lag is not None:
                    lags.append(lag)
        out[group] = float(np.mean(lags)) if lags else 0.0
    return out


def song_range(F):
    return SONG if F > SONG[1] + 1 else (0, F)


def blend(plan, key_layer, weights):
    """key rotations: the layer's, given back to the input's by weights [F, nb]"""
    return continuous(qslerp(key_layer, plan.key_in, np.clip(weights, 0.0, 1.0)))


def subtree(plan, j):
    out, stack = [], [j]
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(plan.children[c])
    return sorted(out)


class Fallback:
    """the stretches given back to the input.  Each is a span of frames wholly the input's for some bones, with a ramp in
    and a ramp out (smoothsteps).  With seams on, a span is first widened while the layer's wrist (of a side whose wrist
    the span moves) is more than EDGE_DEV_CM from the input's on the same frame (at most EDGE_EXTEND frames each way),
    so that its ramps blend two trajectories that are close; and lengthen() mends every edge where the wrist's step
    from one frame to the next passes the input's by more than SEAM_STEP_CM (see there)."""

    def __init__(self, plan, key_layer, seams_on):
        self.plan, self.key_layer, self.seams_on = plan, key_layer, seams_on
        self.spans = []
        self.wrists = {}
        for s in SIDES:
            w = s + "手首"
            if w in plan.names:
                up, j = set(), plan.names.index(w)
                while j >= 0:
                    up.add(j)
                    j = plan.sp[j]
                self.wrists[s] = up
        self.dev, self.layer_steps = {}, {}
        if seams_on:
            world = world_with(plan, key_layer)
            for s in self.wrists:
                n = s + "手首"
                self.dev[s] = np.linalg.norm(world[n][0] - plan.world_in[n][0], axis=1) * UNIT_MM / 10.0
                self.layer_steps[s] = np.linalg.norm(np.diff(world[n][0], axis=0), axis=1) * UNIT_MM / 10.0
        self.key_rot = key_layer
        self.weights = np.zeros((plan.F, plan.nb))

    def sides_of(self, bones):
        return [s for s, up in self.wrists.items() if up & set(bones)]

    def add(self, reason, first, last, bones, detail, rnd=None):
        F = self.plan.F
        first, last = max(0, int(first)), min(F - 1, int(last))
        sp = {"reason": reason, "first": first, "last": last, "bones": list(bones), "detail": detail,
              "ramp_in": FALLBACK_RAMP, "ramp_out": FALLBACK_RAMP, "widened": [0, 0]}
        if rnd is not None:
            sp["round"] = rnd
        if self.seams_on:
            for s in self.sides_of(bones):
                d = self.dev[s]
                while sp["first"] > 0 and first - sp["first"] < EDGE_EXTEND and d[sp["first"] - 1] > EDGE_DEV_CM:
                    sp["first"] -= 1
                while sp["last"] < F - 1 and sp["last"] - last < EDGE_EXTEND and d[sp["last"] + 1] > EDGE_DEV_CM:
                    sp["last"] += 1
            sp["widened"] = [first - sp["first"], sp["last"] - last]
        self.spans.append(sp)

    def apply(self):
        plan = self.plan
        fb = np.zeros((plan.F, plan.nb))
        for sp in self.spans:
            a, b = sp["first"], sp["last"]
            w = ramp_weight(plan.F, [(a - sp["ramp_in"], a, b, b + sp["ramp_out"])])
            fb[:, sp["bones"]] = np.maximum(fb[:, sp["bones"]], w[:, None])
        self.weights = fb
        self.key_rot = blend(plan, self.key_layer, fb)
        return world_with(plan, self.key_rot)

    def seams(self, world_out):
        """per edge of every span (and side whose wrist it moves): the largest step of the output's wrist from one frame
        to the next within the ramp (and one frame either side) less the input's step there (cm); and the same inside
        the span ("inside": the arm is the input's there, a step comes from the bones above it)"""
        plan, F = self.plan, self.plan.F
        steps = {}
        for s in self.wrists:
            n = s + "手首"
            steps[s] = (np.linalg.norm(np.diff(plan.world_in[n][0], axis=0), axis=1) * UNIT_MM / 10.0,
                        np.linalg.norm(np.diff(world_out[n][0], axis=0), axis=1) * UNIT_MM / 10.0)
        out = []
        for i, sp in enumerate(self.spans):
            for edge, lo, hi in (("in", sp["first"] - sp["ramp_in"] - 1, sp["first"] + 1),
                                 ("inside", sp["first"] + 2, sp["last"] - 2),
                                 ("out", sp["last"] - 1, sp["last"] + sp["ramp_out"] + 1)):
                lo, hi = max(0, lo), min(F - 2, hi)
                if hi < lo:
                    continue
                sides = self.sides_of(sp["bones"])
                if edge == "inside":       # only the arms wholly given back there
                    sides = [s for s in sides if self.plan.names.index(s + "手首") in sp["bones"]]
                for s in sides:
                    si, so = steps[s][0][lo:hi + 1], steps[s][1][lo:hi + 1]
                    k = int(np.argmax(so - si))
                    x = {"span": i, "reason": sp["reason"], "edge": edge, "side": s, "frame": lo + k,
                         "ramp": sp.get("ramp_" + edge), "out_cm": _r(so[k], 2), "in_cm": _r(si[k], 2),
                         "excess_cm": _r(so[k] - si[k], 2)}
                    if s in self.layer_steps:
                        x["layer_cm"] = _r(self.layer_steps[s][lo + k], 2)
                    out.append(x)
        return out

    def lengthen(self, world_out):
        """for every edge that steps: a ramp twice as long (up to SEAM_RAMP_MAX); at that length, where the layer itself
        steps there, the edge moved past that frame (within EDGE_EXTEND more frames); a step inside a span that gives
        back only an arm gives back 上半身..頭 too.  False when nothing changed"""
        changed, done = False, set()
        axial = [j for j in range(self.plan.nb) if self.plan.cls[j] in AXIAL]
        for x in self.seams(world_out):
            if x["excess_cm"] <= SEAM_STEP_CM or (x["span"], x["edge"]) in done:
                continue
            sp = self.spans[x["span"]]
            done.add((x["span"], x["edge"]))
            if x["edge"] == "inside":
                if not set(axial) <= set(sp["bones"]):
                    sp["bones"] = sorted(set(sp["bones"]) | set(axial))
                    changed = True
                continue
            key = "ramp_" + x["edge"]
            side = 0 if x["edge"] == "in" else 1
            if sp[key] < SEAM_RAMP_MAX:
                sp[key] = min(SEAM_RAMP_MAX, sp[key] * 2)
                changed = True
            elif x.get("layer_cm", 0.0) - x["in_cm"] > SEAM_STEP_CM and sp["widened"][side] < 2 * EDGE_EXTEND:
                if side == 0 and x["frame"] - 1 < sp["first"]:
                    sp["widened"][0] += sp["first"] - max(0, x["frame"] - 1)
                    sp["first"] = max(0, x["frame"] - 1)
                    changed = True
                elif side == 1 and x["frame"] + 2 > sp["last"]:
                    sp["widened"][1] += min(self.plan.F - 1, x["frame"] + 2) - sp["last"]
                    sp["last"] = min(self.plan.F - 1, x["frame"] + 2)
                    changed = True
        return changed

    def report_spans(self):
        names = self.plan.names
        return [dict(sp, bones=[names[c] for c in sp["bones"]]) for sp in self.spans]


def seam_summary(seams):
    over = [x for x in seams if x["excess_cm"] > SEAM_STEP_CM]
    made = [x for x in over if x["out_cm"] - max(x["in_cm"], x.get("layer_cm", x["in_cm"])) > SEAM_STEP_CM]
    worst = sorted(seams, key=lambda x: -x["excess_cm"])[:12]
    return {"definition": "per edge of a stretch given back (in, out, and inside where the arm is wholly the input's): "
                          "the output wrist's largest step (cm/frame) within the ramp and one frame either side, less "
                          "the input's step on that frame; layer_cm is the layer's own step there (before giving back)",
            "edges": len(seams), "over_%g_cm" % SEAM_STEP_CM: len(over),
            "over_%g_cm_beyond_the_layer_too" % SEAM_STEP_CM: len(made),
            "max_excess_cm": max([x["excess_cm"] for x in seams], default=None),
            "worst": [{k: v for k, v in x.items() if k != "span"} for x in worst]}


def layer(model, motion, params=None, beats=None, key_frames=None, log=None):
    """the dance with the layer and the report (see the module docstring).  beats: (first beat seconds, period
    seconds); key_frames: side -> frames of the trace's keys (the error at the keys)"""
    params = params or default_params()
    started = time.time()
    plan = Plan(model, motion, params, beats, key_frames, log)
    F, nb = plan.F, plan.nb
    # pass 1 (lead 0) and pass 2 (the measured lags as the lead), unless a lead is given
    passes = []
    if params.get("lead") is None:
        leads = {"arm": 0.0, "axial": 0.0}
        local, err, clip = simulate(plan, leads)
        lag = measure_lags(plan, world_with(plan, keys_of(plan, local)))
        passes.append({"lead": dict(leads), "lag": {k: _r(v) for k, v in lag.items()}})
        leads = {k: float(np.clip(round(v, 2), -LEAD_LIMIT, LEAD_LIMIT)) for k, v in lag.items()}
    else:
        leads = {"arm": float(params["lead"]), "axial": float(params["lead"])}
    local, err, clip = simulate(plan, leads)
    key_layer = keys_of(plan, local)
    plan.log("simulated (%.0f s)" % (time.time() - started))
    # given back to the input: the jumps, what the layer could not follow, the floor; each stretch widened while the
    # layer's wrist is far from the input's at its edges, then its ramps lengthened until no seam steps
    seams_on = params.get("seams", True)
    fix = Fallback(plan, key_layer, seams_on)
    jump_zone = np.zeros((F, nb), bool)
    for jp in plan.jumps:
        j, f = plan.names.index(jp["bone"]), jp["frame"]
        bones = subtree(plan, j)
        a, b = f - JUMP_HOLD[0], f + 1 + JUMP_HOLD[1]
        jump_zone[max(0, a - FALLBACK_RAMP):b + FALLBACK_RAMP + 1, bones] = True
        fix.add("jump", a, b, bones, "%s %d -> %d: %.0f deg" % (jp["bone"], f, f + 1, jp["deg"]))
    if params.get("unsolved", True):
        for j in range(nb):
            if plan.kin[j]:
                continue
            bad = ((err[:, j] > UNSOLVED_DEG) & (clip[:, j] >= 0.5)) & ~jump_zone[:, j]
            hard = (err[:, j] > UNSOLVED_HARD_DEG) & ~jump_zone[:, j]
            mark = np.zeros(F, bool)
            for a, b in runs(bad):
                if b - a + 1 >= UNSOLVED_RUN:
                    mark[a:b + 1] = True
            mark |= hard
            for a, b in runs(mark):
                fix.add("unsolved", a, b, subtree(plan, j),
                        "%s: tracking error up to %.1f deg, the torque limit binding %.0f %% of the time"
                        % (plan.names[j], float(err[a:b + 1, j].max()), 100.0 * float(clip[a:b + 1, j].mean())))
    world_out = fix.apply()
    # the hands in the world: the floor at the face and the body, and a hand far from where the input has it; given
    # back around it, widening (and from the second round with 上半身..頭 too)
    residual = []
    checks = []
    if params.get("floor", True):
        checks.append(("floor", floor_violations, "%s hand closer to the face or the body than the floor"))
    if params.get("unsolved", True):
        checks.append(("unsolved", hand_deviation, "%s wrist more than " + "%g cm from the input (late allowed) or %g cm"
                       % (DEVIATION_CM, DEVIATION_SAME_CM) + " on the same frame"))
    axial = [j for j in range(nb) if plan.cls[j] in AXIAL]
    pad = FLOOR_PAD
    rounds = 0
    for rnd in range(FLOOR_ROUNDS if checks else 0):
        found = False
        for reason, check, text in checks:
            for s in SIDES:
                bad = check(plan, world_out, s)
                if bad is None or not bad.any():
                    continue
                found = True
                bones = {j for j in range(nb) if plan.side[j] == s}
                if reason == "floor" or rnd > 0:
                    bones |= set(axial)
                for a, b in runs(bad):
                    fix.add(reason, a - pad, b + pad, sorted(bones), text % s, rnd + 1)
        if not found:
            break
        rounds += 1
        world_out = fix.apply()
        pad += 2
    seam_rounds = 0
    while seams_on and seam_rounds < SEAM_ROUNDS and fix.lengthen(world_out):
        seam_rounds += 1
        world_out = fix.apply()
    for reason, check, _ in checks:
        for s in SIDES:
            bad = check(plan, world_out, s)
            if bad is not None and bad.any():
                residual += [{"reason": reason, "side": s, "first": a, "last": b} for a, b in runs(bad)]
    key_rot = fix.key_rot
    fb = fix.weights
    spans = fix.report_spans()
    out = build(plan, key_rot)
    info = {"leads": leads, "passes": passes, "err": err, "clip": clip, "fallback": fb, "spans": spans,
            "residual": residual, "seconds": time.time() - started, "check_rounds": rounds, "seam_rounds": seam_rounds,
            "seams": fix.seams(world_out)}
    report = report_of(plan, world_out, out, info)
    return Result(out, report, plan.world_in, world_out)


def floor_violations(plan, world_out, side):
    tip = tip_of(plan.world_in, side)
    if tip is None:
        return None
    bad = np.zeros(plan.F, bool)
    for fn, reach in ((face_distance, FLOOR_RANGE_MM), (body_distance, FLOOR_BODY_RANGE_MM)):
        d_in, d_out = fn(plan.world_in, tip), fn(world_out, tip)
        if d_in is None or d_out is None:
            continue
        bad |= (d_in < reach) & (d_out < floor_of(d_in))
    return bad


def hand_deviation(plan, world_out, side):
    """frames where the side's wrist is more than DEVIATION_CM from the input's, even at its best within frames
    f-1 .. f+3 of the output (late is allowed, not lost), or more than DEVIATION_SAME_CM on the same frame"""
    out = None
    for n in (side + "手首",):
        if n is None or n not in world_out:
            continue
        a, b = plan.world_in[n][0], world_out[n][0]
        F = plan.F
        best = np.full(F, np.inf)
        for d in range(-1, 4):
            lo, hi = max(0, -d), min(F, F - d)
            best[lo:hi] = np.minimum(best[lo:hi], np.linalg.norm(b[lo + d:hi + d] - a[lo:hi], axis=1))
        bad = best * UNIT_MM / 10.0 > DEVIATION_CM
        bad |= np.linalg.norm(b - a, axis=1) * UNIT_MM / 10.0 > DEVIATION_SAME_CM
        out = bad if out is None else out | bad
    return out


def build(plan, key_rot):
    """the output motion: every key of a bone the layer does not move, as it was; a key on every frame for the others"""
    tracks = fk.tracks_of(plan.motion)
    labels = set()
    new = []
    curves = {}
    for j, name in enumerate(plan.names):
        keys = tracks.get(name) or tracks.get(fk.vmd_name(name)) or []
        label = keys[0].name if keys else fk.vmd_name(name)
        raw = keys[0].raw_name if keys else None
        labels |= {name, fk.vmd_name(name), label}
        frames = [k.frame for k in keys]
        ki = 0
        held = keys[0].interpolation if keys else None
        for f in range(plan.F):
            while ki < len(keys) and frames[ki] <= f:
                held = keys[ki].interpolation
                ki += 1
            if held not in curves:
                curves[held] = vmd.bone_interpolation(vmd.LINEAR_CURVE, keep=held)
            q = fk.stored(tuple(float(v) for v in key_rot[f, j]))
            new.append(vmd.BoneKey(label, f, tuple(float(v) for v in plan.pos_in[f, j]), q, curves[held], raw_name=raw))
    plan.labels = labels
    bones = [k for k in plan.motion.bones if k.name not in labels] + new
    m = plan.motion
    return vmd.Motion(model_name=m.model_name, bones=bones, morphs=list(m.morphs), cameras=list(m.cameras),
                      lights=list(m.lights), shadows=list(m.shadows), show_iks=list(m.show_iks))


# ---- the analysts' measures (copied; see the module docstring) ---------------------------------------------

def rel(W, a, b):
    return continuous(qnorm(qmul(qconj(W[a][1]), W[b][1])))


def angular_speed(q, fps=FPS):
    return np.degrees(np.linalg.norm(qlog(qnorm(qmul(qconj(q[:-1]), q[1:]))), axis=-1)) * fps


def parabola(y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if den != 0:
            return i + 0.5 * (a - c) / den
    return float(i)


def xcorr_lags(p, d, win=60, step=15, maxlag=6):
    out = []
    for s in range(0, len(p) - win - 2 * maxlag, step):
        a = p[s + maxlag:s + maxlag + win]
        if a.std() < 20:
            continue
        cs = []
        for L in range(-maxlag, maxlag + 1):
            b = d[s + maxlag + L:s + maxlag + L + win]
            if b.std() < 20:
                cs.append(np.nan)
                continue
            cs.append(np.corrcoef(a, b)[0, 1])
        cs = np.array(cs)
        if np.all(np.isnan(cs)):
            continue
        i = int(np.nanargmax(cs))
        if cs[i] < 0.5 or i in (0, len(cs) - 1):
            continue
        out.append((s, parabola(np.nan_to_num(cs, nan=-1), i) - maxlag, float(cs[i])))
    return out


def rests(sh, el, wr, thr=5.0, minlen=3):
    still = (sh < thr) & (el < thr) & (wr < thr)
    out, i, n = [], 0, len(still)
    while i < n:
        if still[i]:
            j = i
            while j < n and still[j]:
                j += 1
            if j - i >= minlen:
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def summary(vals):
    v = np.array(vals, float)
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "median": _r(np.median(v)), "mean": _r(v.mean()),
            "share_zero": _r(np.mean(np.abs(v) < 0.5)), "share_pos": _r(np.mean(v >= 0.5)),
            "share_neg": _r(np.mean(v <= -0.5))}


BINS = [0.0, 0.25, 0.5, 0.75, 0.9]


def dips(s):
    n = len(s)
    moving = np.median(s[s > 0.05 * np.percentile(s, 90)])
    counts = np.zeros(len(BINS))
    for i in range(1, n - 1):
        if s[i] <= s[i - 1] and s[i] < s[i + 1]:
            j = i
            while j > 0 and s[j - 1] >= s[j]:
                j -= 1
            k = i
            while k < n - 1 and s[k + 1] >= s[k]:
                k += 1
            ref = min(s[j], s[k])
            if ref < moving:
                continue
            r = s[i] / ref
            b = np.searchsorted(BINS, r, side="right") - 1
            if r < 0.9:
                counts[b] += 1
    return counts / (n / FPS)


def band(v, lo=3.0, hi=6.0):
    x = v - v.mean(0)
    if len(x) < 128:
        return None
    win = np.hanning(128)
    acc = None
    for a in range(0, len(x) - 128 + 1, 64):
        pw = (np.abs(np.fft.rfft(x[a:a + 128] * win[:, None], axis=0)) ** 2).sum(1)
        acc = pw if acc is None else acc + pw
    f = np.fft.rfftfreq(128, 1 / FPS)
    return float(acc[(f >= lo) & (f < hi)].sum() / max(acc[1:].sum(), 1e-30))


def central_vel(p):
    v = np.zeros_like(p)
    v[1:-1] = (p[2:] - p[:-2]) * 15.0
    v[0] = (p[1] - p[0]) * 30.0
    v[-1] = (p[-1] - p[-2]) * 30.0
    return v


def _pmin(y, n):
    if n <= 0 or n >= len(y) - 1:
        return float(n)
    a, b, c = y[n - 1], y[n], y[n + 1]
    den = a - 2 * b + c
    return float(n) if abs(den) < 1e-12 else n + 0.5 * (a - c) / den


def stops_and_hits(p, active):
    v = central_vel(p)
    s = np.linalg.norm(v, axis=1)
    if not active.any():
        return np.array([]), np.array([]), np.array([])
    thr = np.percentile(s[active], 75)
    dec = -np.gradient(s) * 30.0
    smin, hit, strength = [], [], []
    n, Fn = 9, len(s)
    while n < Fn - 9:
        if not active[n]:
            n += 1
            continue
        pk = s[n - 8:n].max()
        if pk >= thr and s[n] < 0.25 * pk and s[n - 1] >= 0.25 * pk:
            m = n + int(np.argmin(s[n:n + 6]))
            smin.append(_pmin(s, m))
            lo = max(1, n - 8)
            h = lo + int(np.argmax(dec[lo:n + 1]))
            hit.append(_pmin(-dec, h))
            strength.append(dec[h])
            n += 4
        else:
            n += 1
    return np.array(smin), np.array(hit), np.array(strength)


def phase(tsec, beats):
    t = np.asarray(tsec, float)
    if len(t) == 0 or beats is None:
        return {"n": int(len(t))}
    t0, per = beats
    u = (t - t0) / per
    z1 = np.exp(2j * np.pi * u).mean()
    d8 = (((u * 2) + 0.5) % 1 - 0.5) * (per / 2) * 1000
    d4 = ((u + 0.5) % 1 - 0.5) * per * 1000
    lock = np.abs(d8) <= 50
    near = np.abs(d4) <= 107
    return {"n": int(len(t)), "circ_mean_beat_ms": _r(np.angle(z1) / (2 * np.pi) * per * 1000, 1),
            "R_beat": _r(abs(z1)), "within_50_of_8th": _r(lock.mean()),
            "beat107_median_ms": _r(np.median(d4[near]), 1) if near.any() else None}


JOINTS = [("torso", "下半身", "上半身2"), ("clav", "上半身2", "%s肩"), ("shoulder", "%s肩", "%s腕"),
          ("elbow", "%s腕", "%sひじ"), ("wrist", "%sひじ", "%s手首"), ("finger", "%s手首", "%s中指３")]
CHAIN = [j for j, _, _ in JOINTS]


def joint_q(W):
    out = {}
    for s in SIDES:
        for j, a, b in JOINTS:
            a, b = (a % s if "%" in a else a), (b % s if "%" in b else b)
            if a in W and b in W:
                out[(s, j)] = rel(W, a, b)
    if "上半身2" in W and HEAD in W:
        out[("C", "head")] = rel(W, "上半身2", HEAD)
    return out


def measure_a09(W, Win, Q, Qin, F):
    a09 = {"xcorr": {}, "rest_stops_own": {}, "overshoot": {}, "valleys": {}}
    for s in SIDES:
        js = [j for j in CHAIN if (s, j) in Q]
        if not {"shoulder", "elbow", "wrist"} <= set(js):
            continue
        sp = {j: angular_speed(Q[(s, j)]) for j in js}
        spi = {j: angular_speed(Qin[(s, j)]) for j in js}
        for a, b in zip(js[:-1], js[1:]):
            a09["xcorr"]["%s %s->%s" % (s, a, b)] = summary([lag for _, lag, _ in xcorr_lags(sp[a], sp[b])])
        rs = rests(sp["shoulder"], sp["elbow"], sp["wrist"])
        stops = {j: [] for j in js}
        for (i, _) in rs:
            off = {}
            for jt in js:
                lo = max(0, i - 15)
                idx = np.where(sp[jt][lo:i] > 15)[0]
                off[jt] = None if len(idx) == 0 else lo + int(idx[-1])
            if off["shoulder"] is not None:
                for jt in js:
                    if off[jt] is not None:
                        stops[jt].append(off[jt] - off["shoulder"])
        a09["rest_stops_own"][s] = {"rests": len(rs), **{j: summary(stops[j]) for j in ("elbow", "wrist", "finger")
                                                          if j in stops}}
        val = {j: valleys(sp[j]) for j in js}
        for p, d in (("shoulder", "elbow"), ("elbow", "wrist"), ("wrist", "finger")):
            if p in val and d in val:
                a09["valleys"]["%s %s->%s" % (s, p, d)] = valley_offsets(val[p], val[d])
        rs_in = rests(spi["shoulder"], spi["elbow"], spi["wrist"])
        for j in ("shoulder", "elbow", "wrist", "finger"):
            if j not in sp:
                continue
            ov, st, cens = [], [], []
            for (i, j_) in rs_in:
                h = i + 1
                wl = min(j_ - i, 20)
                if h < 6 or h + wl + 1 >= F:
                    continue
                qh = Qin[(s, j)][h]
                u = -qlog(qnorm(qmul(qconj(qh), Qin[(s, j)][h - 4])))
                if np.linalg.norm(u) < np.radians(3):
                    continue
                u = u / np.linalg.norm(u)
                seg = Q[(s, j)][h - 4:h + wl + 1]
                dev = qlog(qnorm(qmul(qconj(np.broadcast_to(qh, seg.shape)), seg)))
                proj = np.degrees(dev @ u)
                ang = np.degrees(np.linalg.norm(dev, axis=1))
                ov.append(max(0.0, float(proj[4:].max())))
                tail = ang[4:]
                bad = np.where(tail >= 1.0)[0]
                st.append(0 if len(bad) == 0 else int(bad[-1]) + 1)
                cens.append(len(bad) > 0 and bad[-1] == len(tail) - 1)
            a09["overshoot"]["%s %s" % (s, j)] = {
                "n": len(ov), "overshoot_deg_median": _r(np.median(ov), 2) if ov else None,
                "overshoot_deg_p90": _r(np.percentile(ov, 90), 2) if ov else None,
                "settle_frames_median": _r(np.median(st), 1) if st else None,
                "settle_frames_p90": _r(np.percentile(st, 90), 1) if st else None,
                "not_settled_in_hold_share": _r(np.mean(cens)) if cens else None}
    return a09


def valleys(v):
    out = []
    n = len(v)
    for i in range(1, n - 1):
        if not (v[i] <= v[i - 1] and v[i] < v[i + 1]):
            continue
        lo, hi = max(0, i - 12), min(n, i + 13)
        pk = max(v[lo:i].max(), v[i + 1:hi].max())
        if pk < 60 or v[i] > 0.3 * pk:
            continue
        out.append(parabola(v, i))
    return np.array(out)


def valley_offsets(prox, dist, maxoff=6):
    res = []
    for t in dist:
        d = prox - t
        k = np.argmin(np.abs(d)) if len(d) else None
        res.append(np.nan if k is None or abs(d[k]) > maxoff else t - prox[k])
    o = np.array(res)
    if len(o) == 0:
        return {"n": 0}
    ok = ~np.isnan(o)
    return {"n": int(len(o)), "same": _r(np.mean(ok & (np.abs(np.nan_to_num(o)) < 0.5))),
            "distal_later": _r(np.mean(ok & (np.nan_to_num(o) >= 0.5))),
            "distal_earlier": _r(np.mean(ok & (np.nan_to_num(o) <= -0.5)))}


def measure_a02(W):
    out = {}
    for lab, bn in (("R_wrist", "右手首"), ("L_wrist", "左手首"), ("head", HEAD)):
        if bn not in W:
            continue
        lo, hi = song_range(len(W[bn][0]))
        v = np.diff(W[bn][0][lo:hi], axis=0)
        if len(v) < 3:
            continue
        dd = dips(np.linalg.norm(v, axis=1))
        out[lab] = {"deep_dips_per_s": _r(dd[0] + dd[1]), "band3_6": _r(band(v), 4),
                    "band6_15": _r(band(v, 6.0, 15.01), 4)}
    return out


def measure_a04(W, Win, F, beats):
    active = np.zeros(F, bool)
    lo, hi = ACTIVE if F > ACTIVE[1] else (0, F)
    active[lo:hi] = True
    out = {"parts": {}}
    all_s, all_h, all_st = [], [], []
    for lab, bn in (("head", HEAD), ("chest", "上半身2"), ("L_wrist", "左手首"), ("R_wrist", "右手首"),
                    ("L_finger", "左中指３"), ("R_finger", "右中指３")):
        if bn not in W or F < 20:
            continue
        sm, ht, stn = stops_and_hits(W[bn][0], active)
        smi, _, _ = stops_and_hits(Win[bn][0], active)
        sh = []
        for t in smi:
            if len(sm):
                k = np.argmin(np.abs(sm - t))
                if abs(sm[k] - t) <= 3:
                    sh.append(sm[k] - t)
        run_on = []
        if lab.endswith("wrist") or lab.endswith("finger"):
            for t in smi:
                m = int(round(t))
                if m < 4 or m + 7 >= F:
                    continue
                u = Win[bn][0][m] - Win[bn][0][m - 3]
                if np.linalg.norm(u) < 1e-6:
                    continue
                u = u / np.linalg.norm(u)
                run_on.append(float(np.max((W[bn][0][m:m + 7] - Win[bn][0][m:m + 7]) @ u)) * UNIT_MM / 10.0)
        out["parts"][lab] = {"run_on_cm_after_input_stop_median": _r(np.median(run_on), 2) if run_on else None,
                             "run_on_cm_p90": _r(np.percentile(run_on, 90), 2) if run_on else None,
                             "stops": phase(sm / FPS, beats),
                             "matched_shift_ms_median": _r(np.median(sh) * 1000 / FPS, 1) if sh else None,
                             "matched_share": _r(len(sh) / max(1, len(smi)))}
        all_s.append(sm), all_h.append(ht), all_st.append(stn)
    if all_s:
        out["all_stops"] = phase(np.concatenate(all_s) / FPS, beats)
        strong = [h[s_ >= np.percentile(s_, 75)] for h, s_ in zip(all_h, all_st) if len(h)]
        out["strong_hits"] = phase(np.concatenate(strong) / FPS if strong else [], beats)
    return out


def measure_keys(W, Win, Q, Qin, F, key_frames):
    """the error at the trace's keys (the frames of each side's 腕 keys), and reached late: the smallest error to the
    key's pose within frames f-1 .. f+3"""
    out = {}
    lo, hi = ACTIVE if F > ACTIVE[1] else (0, F)
    for s in SIDES:
        if key_frames is not None and s in key_frames:
            fr = np.array(sorted(f for f in key_frames[s] if lo <= f < hi), int)
            what = "the trace's keys"
        else:
            fr = np.arange(lo, hi)
            what = "every frame"
        if len(fr) == 0:
            continue
        out[s] = {"frames": what, "n": int(len(fr))}
        fa = fr[(fr >= 1) & (fr + 3 < F)]
        for j in ("clav", "shoulder", "elbow", "wrist", "finger"):
            if (s, j) not in Q:
                continue
            a = qangle_deg(Qin[(s, j)][fr], Q[(s, j)][fr])
            rr = np.min(np.stack([qangle_deg(Qin[(s, j)][fa], Q[(s, j)][fa + d]) for d in range(-1, 4)]), axis=0) \
                if len(fa) else np.zeros(1)
            out[s][j + "_deg"] = {"median": _r(np.median(a), 2), "p95": _r(np.percentile(a, 95), 2), "max": _r(a.max(), 2),
                                  "reached_median": _r(np.median(rr), 2), "reached_p95": _r(np.percentile(rr, 95), 2)}
        for pt in (s + "手首", tip_of(W, s)):
            if pt is None or pt not in W:
                continue
            e = np.linalg.norm(W[pt][0][fr] - Win[pt][0][fr], axis=1) * UNIT_MM / 10.0
            rr = np.min(np.stack([np.linalg.norm(W[pt][0][fa + d] - Win[pt][0][fa], axis=1) for d in range(-1, 4)]),
                        axis=0) * UNIT_MM / 10.0 if len(fa) else np.zeros(1)
            out[s][pt + "_cm"] = {"median": _r(np.median(e), 2), "p95": _r(np.percentile(e, 95), 2),
                                  "max": _r(e.max(), 2), "max_frame": int(fr[int(np.argmax(e))]),
                                  "reached_median": _r(np.median(rr), 2), "reached_p95": _r(np.percentile(rr, 95), 2),
                                  "reached_max": _r(rr.max(), 2)}
    if ("C", "head") in Q:
        a = qangle_deg(Qin[("C", "head")], Q[("C", "head")])
        out["head_on_chest_deg"] = {"median": _r(np.median(a), 2), "p95": _r(np.percentile(a, 95), 2),
                                    "max": _r(a.max(), 2)}
    if HEAD in W:
        hw = qangle_deg(Win[HEAD][1], W[HEAD][1])
        out["head_world_deg"] = {"median": _r(np.median(hw), 2), "p95": _r(np.percentile(hw, 95), 2),
                                 "max": _r(hw.max(), 2), "max_frame": int(np.argmax(hw))}
    return out


def measure_proximity(W, Win):
    out = {}
    for s in SIDES:
        tip = tip_of(Win, s)
        if tip is None:
            continue
        r = {"tip": tip}
        for lab, fn in (("face", face_distance), ("body", body_distance)):
            d_in, d_out = fn(Win, tip), fn(W, tip)
            if d_in is None:
                continue
            near = d_in < 150.0
            diff = d_out - d_in
            worst = np.argsort(np.where(d_in < FLOOR_RANGE_MM, diff, np.inf))[:8]
            r[lab] = {"min_mm_in_out": [_r(d_in.min(), 1), _r(d_out.min(), 1)],
                      "frames_under_150mm_in": int(near.sum()),
                      "closer_by_10mm_frames": int(np.sum(near & (diff < -10.0))),
                      "change_mm_min_max_under_150": [_r(diff[near].min(), 1), _r(diff[near].max(), 1)] if near.any()
                      else None,
                      "under_80mm_frames_in_out": [int(np.sum(d_in < 80)), int(np.sum(d_out < 80))],
                      "closest_changes": [{"frame": int(f), "in_mm": _r(d_in[f], 1), "out_mm": _r(d_out[f], 1)}
                                          for f in worst if np.isfinite(diff[f]) and d_in[f] < FLOOR_RANGE_MM]}
        out[s] = r
    return out


def kime_arrivals(plan, W):
    """per beat hold, the frame the wrist first comes within 1 cm of the input's hold pose (from 6 frames before the
    hold), input and output"""
    out = []
    for s, holds in plan.kimes.items():
        n = s + "手首"
        if n not in W:
            continue
        for a, b in holds:
            target = plan.world_in[n][0][min(a + 1, plan.F - 1)]

            def first(track):
                for f in range(max(0, a - 6), min(plan.F, b + 1)):
                    if np.linalg.norm(track[f] - target) * UNIT_MM / 10.0 < 1.0:
                        return f
                return None
            fi, fo = first(plan.world_in[n][0]), first(W[n][0])
            out.append({"side": s, "hold": [a, b], "arrive_in": fi, "arrive_out": fo,
                        "shift": None if fi is None or fo is None else fo - fi})
    shifts = [x["shift"] for x in out if x["shift"] is not None]
    return {"count": len(out), "shift_frames_median": _r(np.median(shifts), 2) if shifts else None,
            "shift_frames_max": int(max(shifts, key=abs)) if shifts else None,
            "not_arrived": sum(1 for x in out if x["arrive_out"] is None), "list": out[:200]}


def merge_spans(spans):
    """the stretches given back, one per reason and set of bones, overlapping ones joined"""
    out = []
    for s in sorted(spans, key=lambda x: (x["reason"], tuple(x["bones"]), x["first"])):
        last = out[-1] if out else None
        if last and last["reason"] == s["reason"] and last["bones"] == s["bones"] and s["first"] <= last["last"] + 1:
            if s["last"] >= last["last"]:
                last["last"], last["ramp_out"] = s["last"], s.get("ramp_out")
            if s["detail"] not in last["detail"]:
                last["detail"] += "; " + s["detail"]
        else:
            out.append({k: v for k, v in s.items() if k not in ("round", "widened")})
    return sorted(out, key=lambda x: (x["first"], x["reason"]))


def report_of(plan, world_out, out, info):
    F = plan.F
    W, Win = world_out, plan.world_in
    Q, Qin = joint_q(W), joint_q(Win)
    rep = {"frames": [0, F - 1]}
    rep["params"] = json.loads(json.dumps(plan.p, default=list))
    rep["body"] = {k: (_r(v, 4) if isinstance(v, float) else v) for k, v in plan.body.items()}
    rep["bones"] = {}
    for j, n in enumerate(plan.names):
        rep["bones"][n] = {"class": plan.cls[j], "kinematic": bool(plan.kin[j]),
                           "simulated_parent": plan.names[plan.sp[j]] if plan.sp[j] >= 0 else None}
        if not plan.kin[j]:
            rep["bones"][n].update({"inertia_kgm2": _r(plan.I[j], 6),
                                    "torque_limit_nm": None if not np.isfinite(plan.tmax[j]) else _r(plan.tmax[j], 2),
                                    "alpha_max_rad_s2": None if not np.isfinite(plan.tmax[j])
                                    else _r(plan.tmax[j] / plan.I[j], 1),
                                    "torque_limit_share": _r(info["clip"][:, j].mean(), 5),
                                    "tracking_error_deg_p95": _r(np.percentile(info["err"][:, j], 95), 2),
                                    "tracking_error_deg_max": _r(info["err"][:, j].max(), 2)})
    rep["substeps"] = getattr(plan, "substeps_used", None)
    rep["segments"] = {plan.names[j]: {"mass_kg": _r(m, 4), "row": row} for j, (m, _, _, row) in plan.segments.items()}
    rep["lead"] = {"frames": {k: _r(v, 2) for k, v in info["leads"].items()}, "passes": info["passes"],
                   "lag_after": {k: _r(v) for k, v in measure_lags(plan, W).items()}}
    rep["jumps"] = plan.jumps
    rep["fallback"] = merge_spans(info["spans"])
    rep["seams"] = seam_summary(info["seams"])
    rep["rounds"] = {"checks": info["check_rounds"], "seams": info["seam_rounds"]}
    rep["fallback_frames"] = {"share_of_bone_frames": _r(float((info["fallback"] > 0.01).mean()), 4)}
    rep["floor_residual"] = info["residual"]
    rep["holds"] = {s: len(v) for s, v in plan.holds.items()}
    rep["beat_holds"] = kime_arrivals(plan, W) if plan.beats is not None else None
    rep["contact_stretches"] = plan.contacts
    rep["finger_snaps"] = plan.snaps
    rep["weights_share"] = {k: _r(float((v > 0.5).mean()), 4) for k, v in plan.weights.items()}
    rep["a09"] = {"input": measure_a09(Win, Win, Qin, Qin, F), "output": measure_a09(W, Win, Q, Qin, F)}
    rep["a02"] = {"input": measure_a02(Win), "output": measure_a02(W)}
    rep["a04"] = {"input": measure_a04(Win, Win, F, plan.beats), "output": measure_a04(W, Win, F, plan.beats)}
    rep["fidelity"] = measure_keys(W, Win, Q, Qin, F, plan.key_frames)
    rep["proximity"] = measure_proximity(W, Win)
    labels = plan.labels

    def kept(m):
        return [(k.raw_name, k.name, k.frame, k.position, k.rotation, k.interpolation)
                for k in m.bones if k.name not in labels]
    kin, kout = kept(plan.motion), kept(out)
    rep["untouched"] = {"bones": len({k[1] for k in kin}), "keys": len(kin), "identical": kin == kout,
                        "morphs_identical": [(m.name, m.frame, m.weight) for m in plan.motion.morphs]
                        == [(m.name, m.frame, m.weight) for m in out.morphs]}
    rep["seconds"] = _r(info["seconds"], 1)
    return rep


# ---- files ----------------------------------------------------------------------------------------------------

def write_bytes(path, data):
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


def read_beats(path):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    return float(b["first_beat_seconds"]), float(b["period_seconds"])


def read_key_frames(path):
    m = vmd.load(path)
    tracks = fk.tracks_of(m)
    out = {}
    for s in SIDES:
        keys = tracks.get(s + "腕") or []
        if keys:
            out[s] = sorted({k.frame for k in keys})
    return out


def short(report):
    """the few numbers printed on stdout"""
    def xc(which):
        x = report["a09"][which]["xcorr"]
        return {k: x[k].get("median") for k in sorted(x)}
    return {"preset": report["params"].get("preset"), "lead": report["lead"]["frames"], "jumps": len(report["jumps"]),
            "seams_max_excess_cm": report["seams"]["max_excess_cm"],
            "fallback": [[s["reason"], s["first"], s["last"]] for s in report["fallback"]][:40],
            "floor_residual": report["floor_residual"], "a09_lag_in": xc("input"), "a09_lag_out": xc("output"),
            "untouched_identical": report["untouched"]["identical"]}


def run(dance_path, model_path, out_path, report_path=None, beats_path=None, key_frames_path=None, params=None,
        log=None, world_path=None):
    started = time.time()
    check_distinct(dance_path, model_path, out_path, report_path, beats_path, key_frames_path, world_path)
    dance = vmd.load(dance_path)
    model = load_model(model_path)
    beats = read_beats(beats_path) if beats_path else None
    key_frames = read_key_frames(key_frames_path) if key_frames_path else None
    result = layer(model, dance, params, beats, key_frames, log)
    write_bytes(os.path.abspath(out_path), vmd.dumps(result.motion))
    if world_path:
        names = [n for n in result.world_in if n in result.world_out]
        np.savez_compressed(os.path.abspath(world_path), names=np.array(names),
                            pos_in=np.stack([result.world_in[n][0] for n in names], 1).astype(np.float32),
                            rot_in=np.stack([result.world_in[n][1] for n in names], 1).astype(np.float32),
                            pos_out=np.stack([result.world_out[n][0] for n in names], 1).astype(np.float32),
                            rot_out=np.stack([result.world_out[n][1] for n in names], 1).astype(np.float32))
    report = dict({"in": os.path.abspath(dance_path), "model": os.path.abspath(model_path),
                   "out": os.path.abspath(out_path), "beats": beats_path and os.path.abspath(beats_path),
                   "key_frames": key_frames_path and os.path.abspath(key_frames_path)}, **result.report)
    summary = dict({"out": os.path.abspath(out_path), "keys": len(result.motion.bones)}, **short(report))
    report["seconds"] = summary["seconds"] = _r(time.time() - started, 1)
    if report_path:
        write_bytes(os.path.abspath(report_path), (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        summary["report"] = os.path.abspath(report_path)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("model", help="the model (.pmx or .pmd)")
    p.add_argument("out", help="the dance with the layer (.vmd)")
    p.add_argument("--report", help="write the measures of the input and the output to this JSON")
    p.add_argument("--beats", help="JSON with first_beat_seconds and period_seconds: beat holds and a04's timing")
    p.add_argument("--key-frames", help="a motion whose 左腕 / 右腕 keys are the trace's keys (the error there)")
    p.add_argument("--preset", default="default", choices=sorted(PRESETS),
                   help="the strength: default, or strong (softer upper arm and elbow, less fed forward)")
    p.add_argument("--lead", type=float, help="frames the targets are read early (default: measured in a first pass)")
    p.add_argument("--delay-scale", type=float, default=1.0, help="scales every delay (default 1)")
    p.add_argument("--finger-delay", type=float, default=FINGER_DELAY,
                   help="frames the fingers read after the wrist (default %g; 0: on the hand's timing)" % FINGER_DELAY)
    p.add_argument("--substeps", type=int, default=SUBSTEPS, help="simulation steps per frame (default %d)" % SUBSTEPS)
    p.add_argument("--world", help="save the world positions and rotations, input and output, to this .npz")
    p.add_argument("--verbose", action="store_true", help="progress on stderr")
    a = p.parse_args(argv)
    params = default_params(a.preset)
    params.update(lead=a.lead, delay_scale=a.delay_scale, finger_delay=a.finger_delay, substeps=a.substeps)
    log = (lambda msg: print(msg, file=sys.stderr, flush=True)) if a.verbose else None
    try:
        if a.substeps < 1:
            raise ValueError("--substeps must be 1 or more")
        result = run(a.dance, a.model, a.out, a.report, a.beats, a.key_frames, params, log, a.world)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
