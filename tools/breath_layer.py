"""Layer breathing, an inhale before each sung line and a moving hold onto a baked dance, without changing its
choreography or where its feet are.

    python tools/breath_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--cues cues.json] [--report r.json] [--seed 0]
                                 [--strength 1.0]

Why (the analysis of 2026-10-07, a01 / a06 / a20): the dance of the MV holds its poses at a speed of exactly 0 and never
breathes.  The torso stands bit-for-bit still on 5.7 % of the dance (a20: センター and 上半身2 move less than 0.5 cm/s and
上半身2 turns less than 1 deg/s), the first 5.3 s and the last 2.7 s the whole upper body does, there is no inhale before
the 48 sung lines, and the keys are on a 6-degree grid, too coarse to write a breath.  A person trying to stand still
moves the head 3.9 to 14 mm/s (a01) and breathes 12 to 18 times a minute (period 3.3 to 5 s), the upper chest rising and
moving forward 3 to 5 mm per quiet breath (De Groote 1997); a singer breathes in during the 0.5 to 0.7 s before a phrase
(Salomoni 2016: 0.7 s on average).  Animators call the remedy a moving hold.

What is added (all small turns in each bone's own frame, after the key's rotation: q' = q * d):

* LAYERED bones only: 上半身, 上半身2, 首, 左肩, 右肩, 左腕, 右腕.  センター, the leg and toe IK, 下半身, 頭 and everything
  else are copied byte for byte, so the feet stay where they were traced (moving センター would shift the weight onto a
  foot: that is the second stage of the plan, not this one).  A layered bone gets a key on every frame of the motion
  (frame 0 to its last bone key) with the linear curve; the key's physics bytes (2 and 3 of the 64) are those of the
  original key in force on that frame.
* Breathing: one breath signal b(t), 0 breathed out, about 1 breathed in.  It opens the chest (上半身2 about its X axis,
  + leaning back, CHEST_BREATH degrees per unit: the neck base 15 cm above moves 3 to 4 mm, a06) and lifts the shoulders
  (左肩 / 右肩 about Z, SHOULDER_BREATH degrees: 3 mm at the arm joint of Sour's Rin, whose shoulder bone is 55 mm).  The
  upper arm is turned back by the same amount (through whatever lies between 肩 and 腕, such as 肩C), so the arm keeps
  its direction against the chest and the hand only rises with the shoulder joint, by millimetres; it is not swung.
  The neck takes back NECK_COUNTER of the chest's turn, so the head nods less than the chest opens.
  b(t) is a chain of breaths, each an inhale from a trough to a peak and an exhale back down, every piece a smoothstep
  (zero slope at each turning point: C1):
  - a line inhale before each sung line (--cues: the cues of style "lyric", their start and end in seconds): LINE_INHALE
    seconds long, peaking LINE_LEAD after the cue's start (the cues start about 0.09 s before the voice, a19), LINE_AMP
    times a quiet breath; then one slow exhale over the line until the next inhale or the line's end.  An inhale that
    would start less than MIN_GAP after the previous peak starts there; one left shorter than MIN_INHALE is dropped.
    Every time follows the cue's time continuously, so moving a cue by 0.3 s moves its inhale by 0.3 s.
  - before the first move (the head moving MOVE_SPEED mm/s or more for MOVE_RUN frames, at least ANTICIPATE_MIN
    seconds into the song): an inhale peaking ANTICIPATE_LEAD before it, and a small sink of the upper body (上半身
    bending forward by SINK degrees just before the move and back up into it): the anticipation of a person about to
    start.
  - everywhere else, quiet breaths fill the gaps between those: periods drawn from REST_PERIOD, shortened and deepened
    by the exertion (below) up to AFTER_PERIOD and AFTER_AMP, each depth and inhale share drawn from the seed, the gap
    divided into whole breaths so that the last one ends where the next line or anticipation begins.
* The moving hold: the trunk sways on a slow closed orbit, rolling to the sides (about Z) and twisting (about Y), half in
  上半身 and half in 上半身2, the neck taking back HEAD_ROLL_COUNTER of the roll.  The orbit is an ellipse with semi-axes
  SWAY_ROLL and SWAY_YAW degrees that it runs around at SWAY_HZ, all three wandering slowly (smooth value noise with knots
  every SWAY_KNOT seconds, from the seed).  Going round an orbit, rather than to and fro, the chest never stops turning:
  at least SWAY_HZ * 2 pi * the shorter semi-axis, about 1.1 deg/s, and the breath's opening is at right angles to it, so
  the two never cancel.  To and fro (a breath alone, or a sine) it would stop twice a cycle, and a20's measure would find
  a frozen torso there.
* Where the dance itself moves, the layer fades: a quietness q(t) is 1 where the chest turns less than QUIET_TURN[0]
  deg/s and the head moves less than QUIET_HEAD[0] mm/s (both averaged over QUIET_WINDOW frames), 0 above QUIET_TURN[1] or
  QUIET_HEAD[1], a smoothstep between; it is spread QUIET_WINDOW frames both ways (a max filter) and then smoothed over as
  much, so that it is fully 1 throughout every hold and the fades happen in the moving frames next to it.  The sway is
  scaled by SWAY_FLOOR + (1 - SWAY_FLOOR) q and the breath by BREATH_FLOOR + (1 - BREATH_FLOOR) q: in the big motions
  (97 % of the MV, a06) it is a trace, in the holds it is whole.
* The exertion e(t), for the depth and rate of the quiet breaths: 1 - q(t) averaged backwards with a time constant of
  EXERTION_TAU seconds (times 1.5, at most 1).  After four minutes of dancing the last hold breathes deeper and faster.
* A hand at the face: for each side, where the hand's tip (中指３, else 手首) is within CONTACT_CM of the eyes (a
  smoothstep from the first to the second number of centimetres, spread and smoothed over CONTACT_WINDOW frames), the
  shoulder's breath on that side and the neck's counter-turns fade to 0.  The hand and the face then both ride the chest
  rigidly and their distance does not change.
* A last check: the a20 measure is computed on the result (forward kinematics, mmd_cli.fk); a frame still frozen (the
  dance's own motion cancelling the layer) gets the whole sway, times FIX_BOOST, over FIX_SPREAD frames around it, and
  the check runs again, FIX_ROUNDS times at most.  The report says how many rounds it took and what remains.

The seed (random.Random(seed).random(): the same on every platform and Python) draws every period, depth, inhale share
and the noise of the orbit: the same input, cues, seed and strength give the same bytes.  --strength scales every angle.

The report (--report, and in short on stdout), each measure before and after:
* torso_frozen: a20's measure; frames (whole motion, frames 1..last) and dance_share (frames DANCE_PART, a20's 10 to
  253 s, when the motion is that long, else all frames).
* head_in_holds: a01's head speed (the fastest of 頭, 左目, 右目, mm/s) on the frames where the input's head stood still
  (under 1 mm/s): p05, median, p95 and the share in 3 to 9 mm/s.
* lines: count, inhales placed, and per line what the layer alone adds in a06's measure D (the mean of the last 0.2 s
  before the line minus the mean 1.0 to 0.83 s before it): the shoulder joints' height in the chest's frame (mm) and the
  chest's opening against 上半身 (deg); and a06's D of the whole motion (the dance and the layer), before and after.
* contacts: on the frames where a hand's tip is within 15 cm of the eyes (hand_face) or of 下半身 (hand_hip) in the
  input, the largest change of that distance (mm).
* intro (the first move and the breaths before it), breaths (counts), bones (keys before and after, the largest turn
  added), untouched (the bones copied and whether they are byte for byte the input's), fix_rounds.
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

FPS = 30.0
UNIT_MM = 80.0                          # one model unit is about 8 cm (Sour's Rin is 1.5 m tall at about 19 units)
CENTER, SPINE, CHEST, NECK, HEAD = "センター", "上半身", "上半身2", "首", "頭"
LOWER = "下半身"
EYES = ("左目", "右目")
# shoulder, arm, hand tips in order of preference, the sign of the turn about Z that lifts the arm joint
SIDES = (("左肩", "左腕", ("左中指３", "左手首"), 1.0), ("右肩", "右腕", ("右中指３", "右手首"), -1.0))
LAYERED = (SPINE, CHEST, NECK, "左肩", "右肩", "左腕", "右腕")
REQUIRED = (CENTER, SPINE, CHEST, HEAD)

CHEST_BREATH = 1.2                      # degrees the chest opens (leans back) for a quiet breath (a06: 1 to 1.5)
SHOULDER_BREATH = 3.0                   # degrees the shoulders turn up for it (a06: 3 mm at the arm joint is 3.1)
NECK_COUNTER = 0.5                      # share of the chest's breath the neck takes back
REST_PERIOD = (3.3, 5.0)                # seconds of a quiet breath (12 to 18 a minute)
INHALE_SHARE = (0.36, 0.44)             # share of a quiet breath spent breathing in
REST_DEPTH = (0.85, 1.15)               # depth of a quiet breath (1 = CHEST_BREATH and SHOULDER_BREATH)
SHORT_BREATH = 2.5                      # seconds: a breath squeezed into a shorter gap is shallower in proportion
MIN_BREATH = 1.2                        # seconds: a shorter gap gets no breath
AFTER_PERIOD = 0.35                     # the share a breath is shortened by at full exertion
AFTER_AMP = 0.6                         # and the share it is deepened by
EXERTION_TAU = 6.0                      # seconds of the backward average of the motion that makes the exertion
LINE_INHALE = 0.6                       # seconds of the inhale before a line (Salomoni 2016: 0.5 to 0.7)
LINE_LEAD = 0.0                         # seconds from the cue's start to the top of that inhale
LINE_AMP = 1.4                          # depth of a line inhale
LINE_EXHALE_MIN = 1.0                   # seconds: a line without a later end breathes out over at least this
MIN_GAP = 0.25                          # seconds from one peak to the next inhale's start, at least
MIN_INHALE = 0.2                        # seconds: a shorter inhale is dropped
MOVE_SPEED = 5.0                        # mm/s of the head that is a move
MOVE_RUN = 10                           # frames the head must keep moving
ANTICIPATE_MIN = 1.5                    # seconds into the song the first move must be for an anticipation
ANTICIPATE_LEAD = 0.3                   # seconds from the top of the anticipation's inhale to the move
ANTICIPATE_INHALE = 0.7                 # seconds of that inhale
ANTICIPATE_AMP = 1.3
ANTICIPATE_EXHALE = 0.8                 # seconds it breathes out into the move
SINK = 0.8                              # degrees the upper body bends forward in the anticipation
SINK_FRAMES = (14, 3, 10)               # frames: the sink starts 14 before the move, is deepest 3 before, gone 10 after
SWAY_ROLL = (0.74, 0.86)                # degrees: semi-axis of the orbit to the sides
SWAY_YAW = (0.80, 1.00)                 # degrees: semi-axis of the twist
SWAY_HZ = (0.25, 0.33)                  # rounds per second
SWAY_KNOT = 3.0                         # seconds between the knots of the orbit's noise
SWAY_SPINE_SHARE = 0.5                  # share of the sway in 上半身 (the rest in 上半身2)
HEAD_ROLL_COUNTER = 0.4                 # share of the trunk's roll the neck takes back
SWAY_FLOOR = 0.25                       # the sway's scale in a big motion
BREATH_FLOOR = 0.45                     # the breath's scale in a big motion
QUIET_TURN = (3.0, 15.0)                # deg/s of the chest: quiet below the first, moving above the second
QUIET_HEAD = (30.0, 150.0)              # mm/s of the head
QUIET_WINDOW = 9                        # frames
CONTACT_CM = (6.0, 14.0)                # cm from a hand's tip to the eyes: no shoulder breath below, all of it above
CONTACT_WINDOW = 6                      # frames
CONTACT_REPORT_CM = 15.0
FROZEN = (0.5, 0.5, 1.0)                # a20: cm/s of センター, cm/s of 上半身2, deg/s of 上半身2
DANCE_PART = (300, 7599)                # a20's dance part (frames)
FIX_ROUNDS = 4
FIX_BOOST = 1.4
FIX_SPREAD = 10                         # frames
HOLD_HEAD = 1.0                         # mm/s: the input's head stands still below this (a01)
IDENTITY = fk.IDENTITY


def _r(value, places=4):
    return round(float(value), places) + 0.0


# ---- small helpers --------------------------------------------------------------------------

def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def falling(x, lo, hi):
    """1 at or below lo, 0 at or above hi, a smoothstep between"""
    return 1.0 - smoothstep((x - lo) / (hi - lo))


def turn(rx, ry, rz):
    """the quaternion of the rotation vector (rx, ry, rz) in degrees"""
    angle = math.sqrt(rx * rx + ry * ry + rz * rz)
    if angle == 0.0:
        return IDENTITY
    s = math.sin(math.radians(angle) / 2.0) / angle
    return (rx * s, ry * s, rz * s, math.cos(math.radians(angle) / 2.0))


def angle_of(q):
    """degrees of the turn of the unit quaternion q (atan2: exact for small turns)"""
    return math.degrees(2.0 * math.atan2(math.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2), abs(q[3])))


def rotation_vector(q):
    """the rotation vector of q in degrees (the short way)"""
    if q[3] < 0.0:
        q = tuple(-v for v in q)
    n = math.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    a = math.degrees(2.0 * math.atan2(n, q[3]))
    return tuple(a * v / n for v in q[:3])


def max_filter(values, radius):
    n = len(values)
    return [max(values[max(0, i - radius):min(n, i + radius + 1)]) for i in range(n)]


def min_filter(values, radius):
    n = len(values)
    return [min(values[max(0, i - radius):min(n, i + radius + 1)]) for i in range(n)]


def smooth(values, radius):
    """a moving average with a raised-cosine window of `radius` frames each way (ends held)"""
    if radius <= 0:
        return list(values)
    weights = [0.5 + 0.5 * math.cos(math.pi * k / (radius + 1)) for k in range(-radius, radius + 1)]
    n = len(values)
    out = []
    for i in range(n):
        acc = total = 0.0
        for k, w in zip(range(-radius, radius + 1), weights):
            acc += w * values[min(n - 1, max(0, i + k))]
            total += w
        out.append(acc / total)
    return out


def value_noise(rng, frames, knot, lo, hi):
    """a smooth random curve between lo and hi: knots every `knot` frames, a smoothstep between them"""
    knots = [lo + (hi - lo) * rng.random() for _ in range(frames // knot + 2)]
    out = []
    for f in range(frames):
        i, r = divmod(f, knot)
        out.append(knots[i] + (knots[i + 1] - knots[i]) * smoothstep(r / float(knot)))
    return out


def speeds(track, scale=1.0):
    """per frame the step from the frame before (frame 0: 0), times FPS and scale"""
    out = [0.0]
    for f in range(1, len(track)):
        out.append(math.dist(track[f - 1][0], track[f][0]) * FPS * scale)
    return out


def turn_speeds(track):
    out = [0.0]
    for f in range(1, len(track)):
        out.append(angle_of(fk.multiply(fk.conjugate(track[f - 1][1]), track[f][1])) * FPS)
    return out


def in_frame(rotation, origin, point):
    return fk.rotate(fk.conjugate(rotation), tuple(p - o for p, o in zip(point, origin)))


def percentile(values, share):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * share
    i = int(math.floor(k))
    j = min(i + 1, len(ordered) - 1)
    return ordered[i] + (ordered[j] - ordered[i]) * (k - i)


# ---- the cues -------------------------------------------------------------------------------

def lines_from_cues(data):
    """(start, end) in seconds of the sung lines of a cue file (tools/mv_text.py): the cues whose style is "lyric",
    sorted by start"""
    cues = data.get("cues", []) if isinstance(data, dict) else data
    out = []
    for cue in cues:
        if cue.get("style") == "lyric":
            start = float(cue["start"])
            end = float(cue.get("end", start))
            out.append((start, max(start, end)))
    return sorted(out)


# ---- the breath signal ------------------------------------------------------------------------

@dataclass
class Breath:
    start: float                        # seconds: the inhale starts (a trough)
    peak: float                         # seconds: breathed in
    depth: float
    exhale_end: float                   # seconds: breathed out (if nothing comes first)
    kind: str                           # "line", "anticipation" or "rest"


def exertion(quiet):
    """1 - quiet averaged backwards with EXERTION_TAU, times 1.5, at most 1"""
    a = 1.0 - math.exp(-1.0 / (EXERTION_TAU * FPS))
    level, out = 0.0, []
    for q in quiet:
        level += a * ((1.0 - q) - level)
        out.append(min(1.0, 1.5 * level))
    return out


def schedule(seconds, lines, first_move, effort, deepen, depth_scale, rng):
    """the breaths of the song: line inhales, the anticipation and quiet breaths in the gaps between them.  effort(t)
    shortens the quiet breaths, deepen(t) (the exertion where the dance is quiet) deepens them, depth_scale(t) scales
    every breath by how still the dance is"""
    fixed = []
    last_peak = -1e9
    for start, end in lines:
        peak = start + LINE_LEAD
        inhale = max(peak - LINE_INHALE, last_peak + MIN_GAP)
        if peak - inhale < MIN_INHALE:
            continue
        fixed.append(Breath(inhale, peak, LINE_AMP, max(end, peak + LINE_EXHALE_MIN), "line"))
        last_peak = peak
    if first_move is not None:
        peak = first_move / FPS - ANTICIPATE_LEAD
        inhale = peak - ANTICIPATE_INHALE
        clash = any(b.start - 0.2 < peak + ANTICIPATE_EXHALE and inhale < b.exhale_end for b in fixed)
        if inhale > 0.0 and not clash:
            fixed.append(Breath(inhale, peak, ANTICIPATE_AMP, peak + ANTICIPATE_EXHALE, "anticipation"))
    fixed.sort(key=lambda b: b.peak)
    breaths, t = [], 0.0
    for nxt in fixed + [None]:
        gap_end = seconds if nxt is None else nxt.start
        breaths += rest_breaths(t, gap_end, effort, deepen, rng)
        if nxt is not None:
            breaths.append(nxt)
            t = max(t, nxt.exhale_end)
    for b in breaths:
        b.depth *= depth_scale(b.peak)
    return breaths


def rest_breaths(t0, t1, effort, deepen, rng):
    """quiet breaths filling t0..t1 exactly: one after the other, each of a period drawn from REST_PERIOD and shortened
    by the exertion where it starts; what is left at the end (less than one and a half periods) is the last breath"""
    out, t = [], t0
    while t1 - t >= MIN_BREATH:
        period = (REST_PERIOD[0] + (REST_PERIOD[1] - REST_PERIOD[0]) * rng.random()) * (1.0 - AFTER_PERIOD * effort(t))
        length = t1 - t if t1 - t < 1.5 * period else period
        share = INHALE_SHARE[0] + (INHALE_SHARE[1] - INHALE_SHARE[0]) * rng.random()
        depth = (REST_DEPTH[0] + (REST_DEPTH[1] - REST_DEPTH[0]) * rng.random()) * (1.0 + AFTER_AMP * deepen(t))
        depth *= min(1.0, length / SHORT_BREATH)
        out.append(Breath(t, t + share * length, depth, t + length, "rest"))
        t += length
    return out


def breath_curve(breaths, frames):
    """b per frame: a smoothstep from turning point to turning point (zero slope at each)"""
    points = []
    for i, b in enumerate(breaths):
        start_value = 0.0 if not points else value_at(points, b.start)
        if points and points[-1][0] > b.start:
            points = [p for p in points if p[0] < b.start]
        points.append((b.start, start_value))
        points.append((b.peak, b.depth))
        nxt = breaths[i + 1].start if i + 1 < len(breaths) else None
        if nxt is not None and nxt < b.exhale_end:
            x = (nxt - b.peak) / (b.exhale_end - b.peak)
            points.append((nxt, b.depth * (1.0 - smoothstep(x))))
        else:
            points.append((b.exhale_end, 0.0))
    return [value_at(points, f / FPS) for f in range(frames)]


def value_at(points, t):
    if not points:
        return 0.0
    times = [p[0] for p in points]
    i = bisect.bisect_right(times, t)
    if i == 0:
        return points[0][1]
    if i == len(points):
        return points[-1][1]
    (ta, va), (tb, vb) = points[i - 1], points[i]
    if tb <= ta:
        return vb
    return va + (vb - va) * smoothstep((t - ta) / (tb - ta))


# ---- reading the input ------------------------------------------------------------------------

def check_model(model):
    names = {b.name for b in model.bones}
    missing = [n for n in REQUIRED if n not in names]
    if missing:
        raise ValueError("the model has no bone named %s (the layer needs %s)" % (", ".join(missing), ", ".join(REQUIRED)))
    return names


def sides_of(model, names):
    """(shoulder, arm, the arm's parent, tip, lift sign) of the sides the model has"""
    by_name = {b.name: b for b in model.bones}
    out = []
    for shoulder, arm, tips, sign in SIDES:
        if shoulder in names and arm in names:
            parent = by_name[arm].parent
            tip = next((t for t in tips if t in names), None)
            out.append((shoulder, arm, model.bones[parent].name if parent is not None else shoulder, tip, sign))
    return out


def watch_names(names, sides):
    out = [CENTER, SPINE, CHEST, HEAD] + [e for e in EYES if e in names]
    if LOWER in names:
        out.append(LOWER)
    for shoulder, arm, parent, tip, _ in sides:
        for n in (shoulder, parent, arm, tip):
            if n and n not in out:
                out.append(n)
    return out


def eye_point(track, f):
    if all(e in track for e in EYES):
        a, b = track[EYES[0]][f][0], track[EYES[1]][f][0]
        return tuple((x + y) / 2.0 for x, y in zip(a, b))
    return track[HEAD][f][0]


def head_speeds(track):
    parts = [speeds(track[n], UNIT_MM) for n in (HEAD,) + EYES if n in track]
    return [max(v) for v in zip(*parts)]


def quietness(track, frames):
    """q per frame (see the module docstring)"""
    turn_ = turn_speeds(track[CHEST])
    head = head_speeds(track)
    raw = []
    for f in range(frames):
        lo, hi = max(1, f - QUIET_WINDOW // 2), min(frames - 1, f + QUIET_WINDOW // 2 + 1)
        if hi < lo:
            raw.append(1.0)
            continue
        t = sum(turn_[lo:hi + 1]) / (hi - lo + 1)
        h = sum(head[lo:hi + 1]) / (hi - lo + 1)
        raw.append(falling(t, *QUIET_TURN) * falling(h, *QUIET_HEAD))
    return raw, smooth(max_filter(raw, QUIET_WINDOW), QUIET_WINDOW)


def first_move(track, frames):
    """the first frame from which the head moves MOVE_SPEED mm/s or more for MOVE_RUN frames (forward steps), or None"""
    head = head_speeds(track)
    run = 0
    for f in range(frames - 1):
        if head[f + 1] >= MOVE_SPEED:
            run += 1
            if run >= MOVE_RUN:
                m = f - MOVE_RUN + 1
                return m if m >= ANTICIPATE_MIN * FPS else None
        else:
            run = 0
    return None


def contact_weights(track, sides, frames):
    """per side, 1 where the hand is away from the face, fading to 0 within CONTACT_CM"""
    out = {}
    for shoulder, _, _, tip, _ in sides:
        if tip is None:
            out[shoulder] = [1.0] * frames
            continue
        w = [1.0 - falling(math.dist(track[tip][f][0], eye_point(track, f)) * UNIT_MM / 10.0, *CONTACT_CM)
             for f in range(frames)]
        out[shoulder] = smooth(min_filter(w, CONTACT_WINDOW), CONTACT_WINDOW)
    return out


# ---- the layer --------------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict


class Plan:
    """the per-frame signals of the layer, the input it goes onto (sampled and in the world, once) and the output"""

    def __init__(self, model, motion, lines, seed, strength):
        self.model, self.motion, self.strength = model, motion, float(strength)
        names = check_model(model)
        self.sides = sides_of(model, names)
        self.has_neck = NECK in names
        present = {SPINE, CHEST} | ({NECK} if self.has_neck else set())
        for shoulder, arm, _, _, _ in self.sides:
            present |= {shoulder, arm}
        self.layered = [n for n in LAYERED if n in present]
        self.arms = {arm: (shoulder, parent) for shoulder, arm, parent, _, _ in self.sides}
        self.last = fk.last_frame(motion)
        self.frames = self.last + 1
        self.watch = watch_names(names, self.sides)
        self.chain = chain_of(model, self.watch)
        self.before = fk.world_track(model, motion, [n for n, _ in self.chain], 0, self.last)
        self.raw_quiet, self.quiet = quietness(self.before, self.frames)
        self.effort = exertion(self.raw_quiet)
        self.first_move = first_move(self.before, self.frames)
        self.contact = contact_weights(self.before, self.sides, self.frames)
        self.sample_layered()
        self.prepare_composition()
        rng = random.Random(seed)
        self.sway_sign = 1.0 if rng.random() < 0.5 else -1.0
        phase = 2.0 * math.pi * rng.random()
        knot = max(1, int(round(SWAY_KNOT * FPS)))
        roll = value_noise(rng, self.frames, knot, *SWAY_ROLL)
        yaw = value_noise(rng, self.frames, knot, *SWAY_YAW)
        hz = value_noise(rng, self.frames, knot, *SWAY_HZ)
        self.orbit = []
        for f in range(self.frames):
            self.orbit.append((roll[f] * math.cos(phase), yaw[f] * math.sin(phase)))
            phase += self.sway_sign * 2.0 * math.pi * hz[f] / FPS
        self.lines = list(lines)

        def at(values, t):
            return values[min(self.frames - 1, max(0, int(round(t * FPS))))]

        self.breaths = schedule(self.frames / FPS, self.lines, self.first_move,
                                lambda t: at(self.effort, t),
                                lambda t: at(self.effort, t) * at(self.quiet, t),
                                lambda t: BREATH_FLOOR + (1.0 - BREATH_FLOOR) * at(self.quiet, t), rng)
        self.breath = breath_curve(self.breaths, self.frames)
        self.sink = [0.0] * self.frames
        if any(b.kind == "anticipation" for b in self.breaths):
            m = self.first_move
            a, b_, c = SINK_FRAMES
            for f in range(max(0, m - a), min(self.frames, m + c + 1)):
                if f <= m - b_:
                    self.sink[f] = smoothstep((f - (m - a)) / float(a - b_))
                else:
                    self.sink[f] = 1.0 - smoothstep((f - (m - b_)) / float(b_ + c))
        self.boost = [1.0] * self.frames
        self.raise_ = [0.0] * self.frames

    def sample_layered(self):
        """per layered bone: its label and raw name, and per frame the key value MMD shows (position, rotation as
        applied) and the 64 bytes to write (the linear curve with the physics bytes of the key in force)"""
        tracks = fk.tracks_of(self.motion)
        self.samples = {}
        curves = {}
        for name in self.layered:
            keys = tracks.get(name) or tracks.get(fk.vmd_name(name)) or []
            frames = [k.frame for k in keys]
            rows = []
            for f in range(self.frames):
                if keys:
                    position, stored = fk.sample(keys, f, frames)
                    held = keys[max(0, bisect.bisect_right(frames, f) - 1)].interpolation
                else:
                    position, stored, held = (0.0, 0.0, 0.0), IDENTITY, None
                if held not in curves:
                    curves[held] = vmd.bone_interpolation(vmd.LINEAR_CURVE, keep=held)
                rows.append((tuple(position), fk.applied(stored), curves[held]))
            label = keys[0].name if keys else fk.vmd_name(name)
            self.samples[name] = (label, keys[0].raw_name if keys else None, rows, len(keys))

    def prepare_composition(self):
        """the bones of the chain the layer moves (a layered bone or one below it), each with its local turn and offset
        against its parent in the input, per frame; and for each arm the turn X from its shoulder to its parent"""
        layered = set(self.layered)
        self.affected = set()
        for name, parent in self.chain:
            if name in layered or parent in self.affected:
                self.affected.add(name)
        self.local = {}
        for name, parent in self.chain:
            if name not in self.affected:
                continue
            rows = []
            for (pp, wp), (pb, wb) in zip(self.before[parent], self.before[name]):
                inv = fk.conjugate(wp)
                rows.append((fk.multiply(inv, wb), fk.rotate(inv, tuple(b - p for b, p in zip(pb, pp)))))
            self.local[name] = rows
        self.arm_x = {}
        for arm, (shoulder, parent) in self.arms.items():
            self.arm_x[arm] = [fk.multiply(fk.conjugate(s[1]), p[1]) for s, p in zip(self.before[shoulder], self.before[parent])]

    def delta(self, f):
        """the turns (as applied) added at frame f: each layered bone's own (q' = q d), the arms' as the turn put in
        front of their key (q' = d q) that takes their shoulder's back"""
        k = self.strength
        q = max(self.quiet[f], self.raise_[f])
        gs = (SWAY_FLOOR + (1.0 - SWAY_FLOOR) * q) * self.boost[f]
        roll, yaw = (v * gs * k for v in self.orbit[f])
        b = self.breath[f] * k
        near = min([w[f] for w in self.contact.values()] or [1.0])
        chest_open = CHEST_BREATH * b
        out = {SPINE: turn(-SINK * self.sink[f] * k, yaw * SWAY_SPINE_SHARE, roll * SWAY_SPINE_SHARE),
               CHEST: turn(chest_open, yaw * (1.0 - SWAY_SPINE_SHARE), roll * (1.0 - SWAY_SPINE_SHARE))}
        if self.has_neck:
            out[NECK] = turn(-NECK_COUNTER * chest_open * near, 0.0, -HEAD_ROLL_COUNTER * roll * near)
        for shoulder, arm, _, _, sign in self.sides:
            d = turn(0.0, 0.0, sign * SHOULDER_BREATH * b * self.contact[shoulder][f])
            out[shoulder] = d
            x = self.arm_x[arm][f]
            out[arm] = fk.multiply(fk.multiply(fk.conjugate(x), fk.conjugate(d)), x)
        return out

    def deltas(self):
        return [self.delta(f) for f in range(self.frames)]

    def compose(self, deltas):
        """the world pose of every bone of the chain with the layer: the input's, re-posed from the top of the
        layered bones down (only the layered bones' local turns change)"""
        after = {}
        for name, parent in self.chain:
            if name not in self.affected:
                after[name] = self.before[name]
                continue
            up, rows, out = after[parent], self.local[name], []
            front = name in self.arms
            layered = name in self.samples
            for f in range(self.frames):
                pp, wp = up[f]
                local, offset = rows[f]
                if layered:
                    d = deltas[f][name]
                    local = fk.multiply(d, local) if front else fk.multiply(local, d)
                w = fk.normalized(fk.multiply(wp, local))
                out.append((tuple(p + o for p, o in zip(pp, fk.rotate(wp, offset))), w))
            after[name] = out
        return after

    def build(self, deltas):
        """the output motion"""
        self.added = {name: 0.0 for name in self.layered}
        new = []
        for name in self.layered:
            label, raw, rows, _ = self.samples[name]
            front = name in self.arms
            worst = 0.0
            for f, (position, q, interpolation) in enumerate(rows):
                d = deltas[f][name]
                q_new = fk.normalized(fk.multiply(d, q) if front else fk.multiply(q, d))
                if sum(a * b for a, b in zip(q_new, q)) < 0.0:
                    q_new = tuple(-v for v in q_new)                        # the stored sign of the key's own
                worst = max(worst, angle_of(d))
                new.append(vmd.BoneKey(label, f, position, fk.stored(q_new), interpolation, raw_name=raw))
            self.added[name] = worst
        labels = self.labels()
        bones = [k for k in self.motion.bones if k.name not in labels] + new
        return vmd.Motion(model_name=self.motion.model_name, bones=bones, morphs=list(self.motion.morphs),
                          cameras=list(self.motion.cameras), lights=list(self.motion.lights),
                          shadows=list(self.motion.shadows), show_iks=list(self.motion.show_iks))

    def labels(self):
        out = set()
        for name in self.layered:
            out |= {name, fk.vmd_name(name), self.samples[name][0]}
        return out


def chain_of(model, names):
    """(name, parent's name) of `names` and all their ancestors, each after its parent"""
    by_name = {}
    for bone in model.bones:
        by_name.setdefault(bone.name, bone)
    order, placed = [], set()
    for name in names:
        path, bone = [], by_name[name]
        while bone is not None and bone.name not in placed:
            path.append(bone)
            bone = model.bones[bone.parent] if bone.parent is not None else None
        for bone in reversed(path):
            placed.add(bone.name)
            order.append((bone.name, model.bones[bone.parent].name if bone.parent is not None else None))
    return order


def frozen_frames(track):
    """a20's frozen torso: the frames (1..last) where センター and 上半身2 move less than FROZEN[0], FROZEN[1] cm/s and
    上半身2 turns less than FROZEN[2] deg/s"""
    center, chest = speeds(track[CENTER], UNIT_MM / 10.0), speeds(track[CHEST], UNIT_MM / 10.0)
    turn_ = turn_speeds(track[CHEST])
    return [f for f in range(1, len(center)) if center[f] < FROZEN[0] and chest[f] < FROZEN[1] and turn_[f] < FROZEN[2]]


def breathe(model, motion, lines=(), seed=0, strength=1.0):
    """the dance with the layer (see the module docstring) and the report"""
    if strength < 0.0:
        raise ValueError("--strength must not be negative")
    plan = Plan(model, motion, lines, seed, strength)
    deltas = plan.deltas()
    after = plan.compose(deltas)
    rounds = 0
    while rounds < FIX_ROUNDS and strength > 0.0:
        frozen = frozen_frames(after)
        if not frozen:
            break
        rounds += 1
        mark = [0.0] * plan.frames
        for f in frozen:
            for g in range(max(0, f - FIX_SPREAD), min(plan.frames, f + FIX_SPREAD + 1)):
                mark[g] = 1.0
        mark = smooth(mark, FIX_SPREAD // 2)
        plan.raise_ = [max(a, b) for a, b in zip(plan.raise_, mark)]
        plan.boost = [b * (1.0 + (FIX_BOOST - 1.0) * m) for b, m in zip(plan.boost, mark)]
        deltas = plan.deltas()
        after = plan.compose(deltas)
    out = plan.build(deltas)
    return Result(out, report_of(plan, out, after, rounds))


# ---- the report -------------------------------------------------------------------------------

def frozen_summary(track, frames):
    frozen = frozen_frames(track)
    lo, hi = DANCE_PART
    if frames - 1 >= hi:
        part = [f for f in frozen if lo <= f <= hi]
        share = len(part) / float(hi - lo + 1)
    else:
        share = len(frozen) / float(max(1, frames - 1))
    runs, start = [], None
    for i, f in enumerate(frozen):
        if start is None:
            start = f
        if i + 1 == len(frozen) or frozen[i + 1] != f + 1:
            if f - start + 1 >= 3:
                runs.append([start, f])
            start = None
    return {"frames": len(frozen), "dance_share": _r(share), "runs_of_3_or_more": runs[:40]}


def speed_summary(values):
    return {"p05": _r(percentile(values, 0.05), 2), "median": _r(percentile(values, 0.5), 2),
            "p95": _r(percentile(values, 0.95), 2),
            "share_3_to_9": _r(sum(1 for v in values if 3.0 <= v <= 9.0) / float(max(1, len(values))), 3)}


def shoulder_height(track, f, sides):
    hs = [in_frame(track[CHEST][f][1], track[CHEST][f][0], track[arm][f][0])[1] * UNIT_MM for _, arm, _, _, _ in sides]
    return sum(hs) / len(hs) if hs else 0.0


def chest_pitch(track, f):
    rel = fk.multiply(fk.conjugate(track[SPINE][f][1]), track[CHEST][f][1])
    return rotation_vector(rel)[0]


def a06_d(values, t0):
    return sum(values[t0 - 6:t0]) / 6.0 - sum(values[t0 - 30:t0 - 24]) / 6.0


def report_of(plan, out, after, rounds):
    """the measures before and after (the after pose is the composed one; tests check it against mmd_cli.fk on the
    written motion)"""
    before = plan.before
    frames = plan.frames
    head_b, head_a = head_speeds(before), head_speeds(after)
    holds = [f for f in range(1, frames) if head_b[f] < HOLD_HEAD]
    report = {"frames": [0, plan.last], "strength": _r(plan.strength),
              "torso_frozen": {"definition": "a20: センター and 上半身2 under 0.5 cm/s and 上半身2 under 1 deg/s",
                               "before": frozen_summary(before, frames), "after": frozen_summary(after, frames)},
              "fix_rounds": rounds,
              "head_in_holds": {"frames": len(holds), "before": speed_summary([head_b[f] for f in holds]),
                                "after": speed_summary([head_a[f] for f in holds])}}
    # lines
    sh_b = [shoulder_height(before, f, plan.sides) for f in range(frames)]
    sh_a = [shoulder_height(after, f, plan.sides) for f in range(frames)]
    cp_b = [chest_pitch(before, f) for f in range(frames)]
    cp_a = [chest_pitch(after, f) for f in range(frames)]
    starts = [int(round(s * FPS)) for s, _ in plan.lines]
    starts = [t for t in starts if 30 <= t < frames]
    lift = [a06_d([a - b for a, b in zip(sh_a, sh_b)], t) for t in starts]
    open_ = [a06_d([a - b for a, b in zip(cp_a, cp_b)], t) for t in starts]
    line = {"count": len(plan.lines), "inhales": sum(1 for b in plan.breaths if b.kind == "line"),
            "measured": len(starts)}
    if starts:
        line.update({"layer_shoulder_mm": {"min": _r(min(lift), 2), "median": _r(percentile(lift, 0.5), 2)},
                     "layer_chest_deg": {"min": _r(min(open_), 3), "median": _r(percentile(open_, 0.5), 3)},
                     "layer_both_up": sum(1 for a, b in zip(lift, open_) if a > 0.0 and b > 0.0),
                     "a06_shoulder_mm": {"before": _r(sum(a06_d(sh_b, t) for t in starts) / len(starts), 2),
                                         "after": _r(sum(a06_d(sh_a, t) for t in starts) / len(starts), 2)},
                     "a06_chest_deg": {"before": _r(sum(a06_d(cp_b, t) for t in starts) / len(starts), 2),
                                       "after": _r(sum(a06_d(cp_a, t) for t in starts) / len(starts), 2)}})
    report["lines"] = line
    # contacts
    contacts = {}
    for label, target in (("hand_face", None), ("hand_hip", LOWER)):
        if target is not None and target not in before:
            continue
        worst, count = 0.0, 0
        for _, _, _, tip, _ in plan.sides:
            if tip is None:
                continue
            for f in range(frames):
                pb = eye_point(before, f) if target is None else before[target][f][0]
                pa = eye_point(after, f) if target is None else after[target][f][0]
                db = math.dist(before[tip][f][0], pb) * UNIT_MM
                if db < CONTACT_REPORT_CM * 10.0:
                    count += 1
                    worst = max(worst, abs(math.dist(after[tip][f][0], pa) * UNIT_MM - db))
        contacts[label] = {"frames": count, "max_change_mm": _r(worst, 2)}
    report["contacts"] = contacts
    kinds = {}
    for b in plan.breaths:
        kinds[b.kind] = kinds.get(b.kind, 0) + 1
    rest = [b for b in plan.breaths if b.kind == "rest"]
    lengths = [b.exhale_end - b.start for b in rest]
    report["breaths"] = {"by_kind": kinds,
                         "rest_seconds": [_r(min(lengths), 2), _r(max(lengths), 2)] if lengths else []}
    m = plan.first_move
    report["intro"] = {"first_move_frame": m,
                       "anticipation": any(b.kind == "anticipation" for b in plan.breaths),
                       "breaths_before": sum(1 for b in plan.breaths if m is not None and b.peak < m / FPS)}
    report["bones"] = {name: {"keys_before": plan.samples[name][3], "keys_after": plan.frames,
                              "max_added_deg": _r(plan.added[name], 3)} for name in plan.layered}
    labels = plan.labels()

    def kept(motion):
        return [(k.raw_name, k.name, k.frame, k.position, k.rotation, k.interpolation)
                for k in motion.bones if k.name not in labels]

    kin, kout = kept(plan.motion), kept(out)
    report["untouched"] = {"bones": len({k[1] for k in kin}), "keys": len(kin), "identical": kin == kout}
    return report


# ---- files ------------------------------------------------------------------------------------

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
            raise ValueError("%s and %s are the same file: DANCE, MODEL, OUT, --cues and --report must all differ"
                             % (seen[key], path))
        seen[key] = path


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def run(dance_path, model_path, out_path, cues_path=None, report_path=None, seed=0, strength=1.0):
    """read, layer, write; the summary is what main prints"""
    started = time.time()
    check_distinct(dance_path, model_path, out_path, cues_path, report_path)
    dance_full, model_full, out_full = (os.path.abspath(p) for p in (dance_path, model_path, out_path))
    dance = vmd.load(dance_full)
    model = load_model(model_full)
    lines = []
    if cues_path:
        with open(cues_path, encoding="utf-8") as f:
            lines = lines_from_cues(json.load(f))
    result = breathe(model, dance, lines, seed, strength)
    write_bytes(out_full, vmd.dumps(result.motion))
    back = vmd.load(out_full)
    report = result.report
    summary = {"in": dance_full, "model": model_full, "out": out_full, "keys": len(back.bones), "seed": seed,
               "frames": report["frames"], "torso_frozen": {k: {"frames": v["frames"], "dance_share": v["dance_share"]}
                                                            for k, v in report["torso_frozen"].items() if k != "definition"},
               "head_in_holds": report["head_in_holds"], "lines": {k: report["lines"][k] for k in ("count", "inhales")},
               "contacts": report["contacts"], "untouched_identical": report["untouched"]["identical"],
               "fix_rounds": report["fix_rounds"]}
    report = dict({"in": dance_full, "model": model_full, "out": out_full,
                   "cues": os.path.abspath(cues_path) if cues_path else None, "seed": seed}, **report)
    report["seconds"] = summary["seconds"] = _r(time.time() - started, 2)
    if report_path:
        full = os.path.abspath(report_path)
        write_bytes(full, (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        summary["report"] = full
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd), keyed on every frame where it moves")
    p.add_argument("model", help="the model (.pmx or .pmd) with センター, 上半身, 上半身2 and 頭")
    p.add_argument("out", help="the dance with the layer (.vmd)")
    p.add_argument("--cues", help="the text cues (tools/mv_text.py JSON): an inhale before every cue of style lyric")
    p.add_argument("--report", help="write the measures before and after to this JSON")
    p.add_argument("--seed", type=int, default=0, help="the breaths' periods and depths and the sway (default 0)")
    p.add_argument("--strength", type=float, default=1.0, help="scales every turn of the layer (default 1)")
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.model, args.out, args.cues, args.report, args.seed, args.strength)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
