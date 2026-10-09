"""Make a face motion move more like a person's: rewrite the morph keys of the expressions, the blinks and the mouth,
and tie them to the dance, the gaze, the sound and the lyrics.  The body is not touched (no bone key is written).

    python tools/face_life.py FACE.vmd DANCE.vmd GAZE.vmd MODEL.pmx OUT.vmd [--audio SONG] [--cues cues.json]
                              [--report r.json] [--seed 0]

FACE is the face motion to rewrite (the KAZUSA "Face&Lips" of the MV: expressions, まばたき, あいうえお), DANCE the dance
it is loaded after, GAZE the 両目 motion loaded after both (tools/eye_gaze.py), MODEL the model (its morph names, and
its bones for the forward kinematics of the head).  --audio is the song (read with ffmpeg; the voice), --cues the text
cues of the MV (the lyric lines).  OUT is a face motion to load in place of FACE.  The same seed gives the same file.

Why (the analyses a10, a11 and a12 of the MV v2): the face held two expressions for 8 to 11 seconds each, completely
still most of that time, and switched brows, eyes and mouth together in 5 frames; every blink was the same 5-frame
template at times tied to nothing, and between blinks the lid crept down for want of a key holding it; the mouth opened
fully on every vowel (98.7 % of the keys 1.0) and snapped between shapes in 1 or 2 frames.

What is done (the numbers are the constants below):

* Wake-up (intro).  When the eyes of FACE open later than LEAD frames before the body starts to move (the first frame
  the head moves, from the dance), the wake-up (every key from WAKE_BEFORE frames before the eyes open to WAKE_AFTER
  after) moves earlier so that they are open LEAD frames before it, and they open over WAKE_OPEN frames.
* Expressions (EXPRESSIONS, the seven of a11).  A change of WEIGHT made in SNAP frames or less is stretched: a rise
  from nothing over ONSET_FRAMES, a fall to nothing over OFFSET_FRAMES, any other over CHANGE_FRAMES (drawn per
  change from the seed), about the same middle.  Changes within TOGETHER frames of each other, of any morphs, are one
  change of the face: they share the lengths, the brows start first, the mouth DELAY["mouth"] frames later, the eyes
  DELAY["eye"] later, and the whole change moves by up to ALIGN frames so that it starts ALIGN_LEAD frames before the
  fastest turn of the head it can reach (a local peak, ALIGN_RATIO above the median speed of the second around it).
  A slower change next to a stretched one (the slow crawl from 0 to about 0.1 before some changes, a11) gives way to
  it.  While an expression holds or drifts slowly (keys more than SLOW frames apart), its weight follows
  1 - WAVE[part] * r: r is one envelope for the face, low (intense) where a phrase is sung and high (relaxed) after it
  and between phrases, with a key every ENVELOPE_STEP frames, so the face never holds still.  The smile reaches the
  mouth: 口角上げ follows 笑い at CORNERS_UP of its weight, and 口角下げ follows 真面目 at CORNERS_DOWN (only when
  the model has those morphs).
* Blinks (まばたき).  The motion's own blinks are taken out (blink_pulses: read from the まばたき keys alone) and the
  lid between them is held at the level it had (a switch of that level, hidden in an old blink, happens over
  BASE_SWITCH frames; a quick change of it with an expression is stretched like the expression; it never closes slowly
  for more than CREEP_LONGEST frames, which a10 would count as the creep); what still shuts the eyes then (the long
  closures, closure = まばたき + 笑い >= CLOSED as a10) stays.  New blinks are
  placed at the start of quick large gaze shifts (GAZE_SHIFT degrees in GAZE_SHIFT_FRAMES frames, head and eyes in the
  world) with the chance P_GAZE, at the start of large saccades (BIG_SACCADE degrees, from the gaze motion) with
  P_SACCADE, in the breath after a phrase ends with P_PHRASE, and elsewhere after log-normal waits (FILL_MEDIAN,
  FILL_SIGMA, and with LONG_PAUSE_CHANCE a pause of LONG_PAUSE seconds), never two within MIN_BETWEEN frames.  Each
  blink closes in CLOSING_FRAMES, stays shut HOLD_FRAMES and opens in OPENING_FRAMES (drawn per blink; the opening
  slows down at its end); its peak makes まばたき + 笑い = 1.  The upper lid follows the gaze: LID_DOWN per degree
  the eyes look down, LID_UP less per degree up, from one fixation to the next (it moves with the saccade).
* Mouth (あいうえお).  The frame on which each vowel is fully open (an onset, tools/lip_timing.py) is kept.  The
  height of each sung vowel (a key of 1.0) is GAIN times as high, more for a loud and long note (the voice: the
  power of the centre of the stereo picture in VOICE_BAND), at least SMALL_FLOOR for い and う, FINAL_FLOOR for the
  last vowel of a phrase.  A change to another vowel takes CROSSFADE frames and ends with the old vowel gone, a
  closing of the lips between two vowels closes in CLOSE_FRAMES and opens in OPEN_FRAMES frames ending on the onset
  (its middle moves by up to a frame when the lips shut right before the onset), the opening of a phrase from a shut
  mouth and a quick closing after it are eased (MMD draws morphs straight between keys, so every frame of these is a
  key), and a held vowel eases off by HOLD_RELAX.  The vowels never add up to more than 1.  Where nothing is sung the
  mouth breathes (あ between BREATH[0] and BREATH[1], up to BREATH[2] when the dance is intense, a cycle of
  BREATH_PERIOD seconds, never above BREATH_CAP), and where the voice stops for 100 ms or more between two vowels
  with at least 4 frames to spare before the next opening, it opens to JOIN_BREATH for a short breath.  No onset
  moves and none is added (the report counts them), except that the wake-up carries its own.
* The dance's own face keys (the MV's dance keys まばたき on a few frames of the intro) would be merged into the face
  when MMD loads both: OUT holds a key of its own on each of those frames, so that its tracks win.

The report (--report, and in short on stdout) gives, for the expressions, the blinks and the mouth, the measures of
the analyses a11, a10 and a12 before (FACE) and after (OUT).
"""
import argparse
import bisect
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

FPS = 30.0
EXPRESSIONS = ("真面目", "困る", "にこり", "怒り", "下", "笑い", "にやり")
PART = {"真面目": "brow", "困る": "brow", "にこり": "brow", "怒り": "brow", "下": "brow", "笑い": "eye",
        "にやり": "mouth", "口角上げ": "mouth", "口角下げ": "mouth"}
CORNERS_UP = ("口角上げ", "笑い", 0.6)          # (morph, the morph it follows, share of its weight)
CORNERS_DOWN = ("口角下げ", "真面目", 0.2)
ACTIVE = 0.05                   # weight above which an expression counts as shown (a11)
SNAP = 9                        # frames: a change this quick or quicker is stretched
ONSET_FRAMES = (12, 16)         # frames of a rise from nothing (both ends included)
OFFSET_FRAMES = (14, 18)        # of a fall to nothing
CHANGE_FRAMES = (10, 14)        # of any other change
TOGETHER = 4                    # frames: changes of different morphs this close are one change of the face
DELAY = {"brow": (0, 0), "mouth": (1, 2), "eye": (3, 4)}      # frames each part starts after the brows
ALIGN = 9                       # frames a change may move toward the fastest turn of the head
ALIGN_RATIO = 1.5
ALIGN_LEAD = 2                  # frames the face starts changing before the head turns fastest
WAVE = {"brow": 0.15, "eye": 0.12, "mouth": 0.25}            # how far the envelope lowers a held weight
ENVELOPE_STEP = (35, 70)        # frames between the keys of the envelope
ENVELOPE_MIN_STEP = 0.15        # the envelope changes by at least this from one key to the next
SLOW = 20                       # frames: a change between two keys this far apart is a drift, and is waved too

BLINK, SMILE = "まばたき", "笑い"
CLOSED = 0.8                    # closure (まばたき + 笑い) at which the eye counts as shut (a10)
STEEP = 0.05                    # per-frame change of the closure that counts as the lid moving (a10)
SHORT_CLOSURE = 4               # closed frames: up to this a closure is a blink, longer ones are kept (a10)
CLOSING_FRAMES = (2, 3)
HOLD_FRAMES = (0, 1)
OPENING_FRAMES = (5, 6)
CLOSING = {2: (0.5,), 3: (0.3, 0.75)}                         # the lid between open (0) and shut (1)
OPENING = {5: (0.62, 0.36, 0.18, 0.07), 6: (0.7, 0.45, 0.27, 0.14, 0.05)}
P_GAZE, P_SACCADE, P_PHRASE = 0.75, 0.7, 0.55
GAZE_SHIFT, GAZE_SHIFT_FRAMES = 33.0, 9                       # degrees in frames (a10, Evinger et al. 1994)
BIG_SACCADE = 20.0
SACCADE_SPEED = 1.5             # degrees per frame of the eyes in the head and in the world on a saccade frame
SACCADE_LONGEST = 5             # frames: a faster stretch than this is no saccade
PHRASE_PAUSE = 15               # frames between two vowel onsets that end a phrase for the blinks (a10)
PHRASE_BLINK = (5, 9)           # frames after the last vowel of a phrase the blink starts
MIN_BETWEEN = 12                # frames between the starts of two blinks
FILL_MEDIAN, FILL_SIGMA = 3.4, 0.5                            # seconds, log-normal
LONG_PAUSE_CHANCE, LONG_PAUSE = 0.12, (6.0, 10.0)
KEEP_CLEAR = 15                 # frames around the long closures and after the eyes open without new blinks
BASE_SWITCH = 8                 # frames over which the lid level changes where an old blink hid the change
CREEP_LONGEST = 9               # frames: the lid never closes slowly for longer (a10 counts 10 and more as a creep)
LID_DOWN, LID_UP = 0.01, 0.005  # まばたき per degree the eyes look down / up

VOWELS = ("あ", "い", "う", "え", "お")
SMALL_VOWELS = ("い", "う")
GAIN = (0.6, 1.0)
SMALL_FLOOR = 0.8
FINAL_FLOOR = 0.9               # the last vowel of a phrase (a held note) is at least this
SUNG = 0.99                     # an onset key at least this high is a sung vowel and gets a gain
PHRASE_GAP = 24                 # frames between onsets that end a phrase for the mouth (tools/lip_timing.py)
CROSSFADE = 3
HOLD_RELAX, HOLD_TAU = 0.08, 12.0                             # a held vowel eases off by this much, frames
CLOSE_FRAMES = 3
OPEN_FRAMES = (2, 3)
BREATH = (0.03, 0.08, 0.20)
BREATH_PERIOD = (1.6, 2.6)
JOIN_BREATH = 0.25              # under lip_timing's MIN_WEIGHT, so a breath is no onset
JOIN_GAP = (10, 90)             # frames between two onsets where a breath may go
JOIN_INTO = 3                   # frames from the breath to the next vowel's onset
BREATH_CAP = 0.29               # a breath never takes あ to lip_timing's MIN_WEIGHT (0.3): it makes no onset
JOIN_PAUSE_DB, JOIN_PAUSE_BINS = 6.0, 10
VOICE_BAND = (300.0, 3500.0)
SAMPLE_RATE, HOP, WINDOW = 16000, 160, 1024
AUDIO_T0 = WINDOW / 2.0 / SAMPLE_RATE                         # seconds: the centre of the first window
SHOWN = 0.1875                  # frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py, a12)

LEAD = 15                       # frames the eyes are open before the body moves
WAKE_BEFORE, WAKE_AFTER, WAKE_OPEN = 15, 45, 10
BODY_MOVES = (1.0, 0.05)        # degrees / model units the head has moved from frame 0 when the body starts
MEASURE_SEED = 1234             # the circular shifts of the chance levels
SHIFTS = 2000


@dataclass
class Inputs:
    face: vmd.Motion                    # the face motion to rewrite
    frames: int                         # frames of the song (0 .. frames - 1)
    head: np.ndarray                    # [F, 4] world rotation of 頭 (as applied, mmd_cli/fk.py)
    eyes: np.ndarray                    # [F, 4] local rotation of 両目 in the head (as applied)
    body_start: Optional[int] = None    # the first frame the body moves
    voice: Optional[np.ndarray] = None  # centre power in VOICE_BAND every 10 ms (frame i at i / 100 + AUDIO_T0 s)
    lines: List[tuple] = field(default_factory=list)          # the lyric lines (start, end) in seconds
    morphs: Optional[set] = None        # the model's morph names (None: take every morph as there)
    dance_morph_keys: List[tuple] = field(default_factory=list)   # (name, frame) of the dance's morph keys
    head_pos: Optional[np.ndarray] = None   # [F, 3] world position of 頭 (for how intense the dance is)


@dataclass
class Result:
    motion: vmd.Motion
    report: dict


def _r(value, places=3):
    return round(float(value), places) + 0.0


def load_lip_timing():
    """tools/lip_timing.py, loaded from its file (tools/ is not a package)"""
    spec = importlib.util.spec_from_file_location("lip_timing", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                            "lip_timing.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lip_timing = load_lip_timing()


# ---- tracks ---------------------------------------------------------------------------------

def morph_keys(motion):
    """name -> [(frame, weight)] sorted by frame, the later key of a frame winning (as MMD)"""
    out = {}
    for k in motion.morphs:
        out.setdefault(k.name, {})[k.frame] = float(k.weight)
    return {name: sorted(d.items()) for name, d in out.items()}


def track(keys, frames):
    """the weight on every frame, straight between keys and held outside them (as MMD draws a morph)"""
    if not keys:
        return np.zeros(frames)
    return np.interp(np.arange(frames), [f for f, _ in keys], [w for _, w in keys])


def bake(values, places=6):
    """[(frame, weight)] of a per-frame curve without the keys that lie on the line of their neighbours"""
    v = np.round(np.asarray(values, float), places)
    n = len(v)
    if n <= 2:
        return [(i, float(v[i])) for i in range(n)]
    bend = np.abs(v[:-2] - 2.0 * v[1:-1] + v[2:]) > 10.0 ** -places
    keep = [0] + [i + 1 for i in np.where(bend)[0]] + [n - 1]
    return [(int(i), float(v[i])) for i in keep]


def runs(mask):
    """[(start, end inclusive)] of the True stretches"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0].tolist(), (np.where(d == -1)[0] - 1).tolist()))


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# ---- rotations (numpy, Hamilton, v' = q v q^-1 as mmd_cli/fk.py) -------------------------------

def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qrot(q, v):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    v = np.broadcast_to(v, q.shape[:-1] + (3,))
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], axis=-1)


FORWARD = np.array([0.0, 0.0, -1.0])


def _angles_between(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip((a * b).sum(axis=-1), -1.0, 1.0)))


def turn_speed(q):
    """degrees per frame a rotation track turns (first frame 0)"""
    dots = np.clip(np.abs((q[1:] * q[:-1]).sum(axis=1)), 0.0, 1.0)
    return np.concatenate([[0.0], 2.0 * np.degrees(np.arccos(dots))])


def gaze_world(head, eyes):
    return qrot(qmul(head, eyes), FORWARD)


def gaze_shifts(head, eyes, degrees=GAZE_SHIFT, frames=GAZE_SHIFT_FRAMES):
    """frames where the gaze in the world (head and eyes) starts turning by `degrees` within `frames` (a10: the peaks
    of the change over the window, at least `frames` apart)"""
    g = gaze_world(head, eyes)
    n = len(g)
    if n <= frames + 2:
        return []
    change = np.concatenate([_angles_between(g[:-frames], g[frames:]), np.zeros(frames)])
    peaks = [f for f in range(1, n - 1) if change[f] >= degrees and change[f] >= change[f - 1] and change[f] > change[f + 1]]
    keep = []
    for f in peaks:
        if keep and f - keep[-1] < frames:
            if change[f] > change[keep[-1]]:
                keep[-1] = f
        else:
            keep.append(f)
    return keep


def saccades(head, eyes, speed=SACCADE_SPEED, longest=SACCADE_LONGEST):
    """the saccades of a gaze motion, from its rotations alone: stretches of at most `longest` frames on which the eyes
    turn by `speed` degrees a frame or more in the head, and their own move does not cancel the move the head gives
    the gaze (a counter-rotation does, fully or in part): it goes the same way, or is more than twice as large, or is
    at least as large and leaves the gaze in the world moving by half of it.  On the MV's gaze this finds 64 of the 84
    saccades its report lists, and 64 of the 95 it finds are on that list.  [{start, end, amplitude}]"""
    d_in = qrot(eyes, FORWARD)
    v_in = np.concatenate([[0.0], _angles_between(d_in[:-1], d_in[1:])])
    now = qrot(head[1:], d_in[1:])
    kept = qrot(head[1:], d_in[:-1])                  # the eyes as on the frame before, the head as now
    own, by_head = now - kept, kept - qrot(head[:-1], d_in[:-1])
    n_own, n_head = np.linalg.norm(own, axis=1), np.linalg.norm(by_head, axis=1)
    moving = np.linalg.norm(own + by_head, axis=1)
    free = (((own * by_head).sum(axis=1) >= 0) | (n_head < 0.5 * n_own)
            | ((n_own >= n_head) & (moving >= 0.5 * n_own)))
    out = []
    for s, e in runs((v_in >= speed) & np.concatenate([[False], free])):
        if e - s + 1 > longest or s == 0:
            continue
        amplitude = float(_angles_between(d_in[s - 1], d_in[e]))
        if amplitude >= 2.0:
            out.append({"start": int(s), "end": int(e), "amplitude": amplitude})
    return out


def eye_pitch(eyes):
    """degrees the eyes look up (+) or down (-) in the head"""
    d = qrot(eyes, FORWARD)
    return np.degrees(np.arcsin(np.clip(d[:, 1] / np.linalg.norm(d, axis=1), -1.0, 1.0)))


def body_start(head_rot, head_pos=None, moves=BODY_MOVES):
    """the first frame on which the head has turned or moved away from where it is on frame 0"""
    turned = _angles_between(qrot(head_rot, FORWARD), qrot(head_rot[:1], FORWARD)[0]) > moves[0]
    if head_pos is not None:
        turned |= np.linalg.norm(head_pos - head_pos[0], axis=1) > moves[1]
    hit = np.where(turned)[0]
    return int(hit[0]) if len(hit) else None


def intensity(head, head_pos=None, seconds=2.0):
    """how hard she dances, 0..1 per frame: the head's turning (and moving) speed, averaged over `seconds`, against
    its 90th percentile"""
    parts = [turn_speed(head)]
    if head_pos is not None:
        parts.append(np.concatenate([[0.0], np.linalg.norm(np.diff(head_pos, axis=0), axis=1)]))
    total = np.zeros(len(head))
    for p in parts:
        scale = np.percentile(p, 90)
        total += p / scale if scale > 0 else 0.0
    total /= len(parts)
    n = max(1, int(seconds * FPS))
    smooth = np.convolve(total, np.ones(n) / n, mode="same")
    return np.clip(smooth, 0.0, 1.0)


# ---- blinks (a10's definitions) ---------------------------------------------------------------

def episodes(closure, start):
    """the closures (closure >= CLOSED) from `start`: t0 / t1 first and last shut frame, cs the frame before the steep
    closing, oe the frame the steep opening ends"""
    c = closure
    n = len(c)
    out = []
    f = start
    while f < n:
        if c[f] >= CLOSED:
            t0 = f
            while f + 1 < n and c[f + 1] >= CLOSED:
                f += 1
            t1 = f
            cs = t0
            while cs - 1 >= 0 and c[cs] - c[cs - 1] > STEEP:
                cs -= 1
            oe = t1
            while oe + 1 < n and c[oe] - c[oe + 1] > STEEP:
                oe += 1
            out.append({"t0": t0, "t1": t1, "cs": cs, "oe": oe, "closed": t1 - t0 + 1, "closing": t0 - cs,
                        "opening": oe - t1})
        f += 1
    return out


def blink_profile(closing, hold, opening):
    """the lid from the frame before the closing (0) to the frame the opening ends (0): 1 is shut"""
    return [0.0] + list(CLOSING[closing]) + [1.0] * (1 + hold) + list(OPENING[opening]) + [0.0]


def creep_runs(b, start):
    """a10: stretches of 10 frames or more on which まばたき rises slowly (by more than 0, at most STEEP a frame)"""
    step = np.diff(b, prepend=b[0])
    mask = (step > 1e-5) & (step <= STEEP)
    mask[:start] = False
    return [(s, e) for s, e in runs(mask) if e - s + 1 >= 10]


# ---- the plan -------------------------------------------------------------------------------

def plan(inp, seed=0):
    """the new face motion and the report"""
    rng = random.Random(seed)
    frames = inp.frames
    original = morph_keys(inp.face)
    keys = {name: list(v) for name, v in original.items()}
    has = (lambda name: True) if inp.morphs is None else (lambda name: name in inp.morphs)
    onsets = lip_timing.onsets(inp.face) if any(v in keys for v in VOWELS) else []
    phrases = lip_timing.phrases(onsets, PHRASE_GAP) if onsets else []
    speed = turn_speed(inp.head)
    start = inp.body_start
    keys, intro = wake_up(keys, frames, start)
    env = envelope([(p.start, p.end) for p in phrases], frames, rng)
    expressions, events = rewrite_expressions(keys, env, speed, frames, rng, has)
    smile = track(expressions.get(SMILE, keys.get(SMILE, [])), frames)
    blink, blink_info = rewrite_blinks(keys, frames, smile, inp, onsets, intro, events, rng)
    vowels, mouth_info = rewrite_mouth(keys, frames, onsets, phrases, inp, rng)
    new = dict(keys)
    new.update(expressions)
    if blink is not None:
        new[BLINK] = blink
    new.update(vowels)
    morphs = []
    for name in list(original) + [n for n in new if n not in original]:
        for frame, weight in shadowed(new[name], name, inp.dance_morph_keys, frames):
            morphs.append(vmd.MorphKey(name, frame, weight))
    motion = vmd.Motion(model_name=inp.face.model_name, morphs=morphs)
    intro["eyes_open"] = first_open(track(new.get(BLINK, []), frames), intro)
    listed = blink_info.pop("list")
    blink_report = dict(blink_info)
    blink_report["before"] = measure_blinks(original, frames, inp, onsets, original_wake(original, frames))
    blink_report["new"] = dict(measure_blinks(new, frames, inp, onsets, intro["eyes_open"]), list=listed)
    report = {
        "frames": [0, frames - 1], "seed": seed, "intro": intro,
        "expression": {"before": measure_expressions(original, frames, speed),
                       "new": measure_expressions(new, frames, speed), "changes": len(events),
                       "moved_to_head": sum(1 for e in events if e["shift"] != 0)},
        "blink": blink_report,
        "mouth": dict(mouth_info, **measure_mouth(original, new, frames, inp, intro)),
    }
    return Result(motion, report)


def first_open(b, intro):
    """the first frame after the closed start on which まばたき is below 0.5"""
    below = np.where(b < 0.5)[0]
    return int(below[0]) if len(below) else None


def original_wake(keys, frames):
    b = track(keys.get(BLINK, []), frames) + track(keys.get(SMILE, []), frames)
    below = np.where(b < CLOSED)[0]
    return int(below[0]) if len(below) else 0


def shadowed(keys, name, dance_keys, frames):
    """the keys plus one on every frame the dance keys this morph on and these keys do not, with this track's value
    there (MMD replaces a key of the dance by a key of the face motion on the same frame only)"""
    frames_here = {f for f, _ in keys}
    extra = sorted({f for n, f in dance_keys if n == name and f not in frames_here})
    if not extra:
        return keys
    values = np.interp(extra, [f for f, _ in keys], [w for _, w in keys])
    return sorted(list(keys) + [(int(f), float(v)) for f, v in zip(extra, values)])


# ---- wake-up --------------------------------------------------------------------------------

def wake_up(keys, frames, start):
    """move the opening of the eyes at the start (and every key around it) to LEAD frames before the body starts"""
    info = {"body_start": start, "moved_by": 0, "eyes_open_before": None}
    b = keys.get(BLINK)
    if not b:
        return keys, info
    closure = track(b, frames) + track(keys.get(SMILE, []), frames)
    if closure[0] < CLOSED:
        return keys, info
    below = np.where(closure < CLOSED)[0]
    if not len(below):
        return keys, info
    opened = int(below[0])
    info["eyes_open_before"] = opened
    frames_b = [f for f, _ in b]
    i_end = bisect.bisect_left(frames_b, opened)            # the first key at or after the opening
    i_start = i_end - 1                                      # the last key still shut
    if start is None or i_start < 0 or i_end >= len(b):
        return keys, info
    open_start, open_end = b[i_start][0], b[i_end][0]
    target = start - LEAD
    shift = target - open_end
    lo, hi = open_start - WAKE_BEFORE, open_end + WAKE_AFTER
    if shift >= 0 or lo + shift < 1:
        info["opening"] = (open_start, open_end)
        return keys, info
    out = {}
    for name, ks in keys.items():
        moved = {}
        for f, w in ks:
            if lo <= f <= hi:
                moved[f + shift] = w
        kept = {f: w for f, w in ks if not lo <= f <= hi}
        kept.update(moved)
        out[name] = sorted(kept.items())
    nb = dict(out[BLINK])
    nb.pop(open_start + shift, None)
    nb[target - WAKE_OPEN] = b[i_start][1]
    out[BLINK] = sorted(nb.items())
    info.update(moved_by=int(shift), opening=(target - WAKE_OPEN, target), window=(lo, hi))
    return out, info


# ---- expressions ----------------------------------------------------------------------------

def envelope(phrases, frames, rng):
    """[(frame, r)]: 0 = intense, 1 = relaxed.  Low where a phrase starts, high after it ends, a wave in between"""
    anchors = []
    for p0, p1 in phrases:
        anchors.append((p0 - 4, rng.uniform(0.0, 0.25), "start"))
        anchors.append((p1 + 6, rng.uniform(0.65, 1.0), "end"))
    anchors.sort()
    edges = [(0, rng.uniform(0.4, 0.8), "gap")] + anchors + [(frames - 1, rng.uniform(0.4, 0.8), "gap")]
    points = []
    for (f0, r0, k0), (f1, r1, _) in zip(edges, edges[1:]):
        points.append((f0, r0))
        inside = k0 == "start"
        high = not inside
        f = f0 + rng.randint(*ENVELOPE_STEP)
        while f < f1 - ENVELOPE_STEP[0] // 2:
            if inside:
                r = rng.uniform(0.3, 0.6) if high else rng.uniform(0.0, 0.3)
            else:
                r = rng.uniform(0.5, 1.0) if high else rng.uniform(0.2, 0.5)
            points.append((f, r))
            high = not high
            f += rng.randint(*ENVELOPE_STEP)
    points.append(edges[-1][:2])
    out = []
    for f, r in sorted(points):
        f = int(min(max(f, 0), frames - 1))
        if out and f - out[-1][0] < 8:
            continue
        if out and abs(r - out[-1][1]) < ENVELOPE_MIN_STEP:
            r = out[-1][1] + (ENVELOPE_MIN_STEP if out[-1][1] < 0.5 else -ENVELOPE_MIN_STEP)
        out.append((f, float(min(max(r, 0.0), 1.0))))
    return out


def ramps_of(keys):
    """[[f0, v0, f1, v1]] the changes between neighbouring keys, a run of quick ones going the same way as one"""
    out = []
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if abs(v1 - v0) <= 1e-9:
            continue
        if out:
            p = out[-1]
            if p[2] == f0 and (v1 - v0) * (p[3] - p[1]) > 0 and p[2] - p[0] <= SNAP and f1 - f0 <= SNAP:
                p[2], p[3] = f1, v1
                continue
        out.append([f0, v0, f1, v1])
    return out


def _kind(v0, v1):
    if v0 <= ACTIVE < v1:
        return "onset"
    if v1 <= ACTIVE < v0:
        return "offset"
    return "change"


def rewrite_expressions(keys, env, speed, frames, rng, has):
    """the new keys of the expression morphs (and of the mouth corners that follow 笑い and 真面目), the changes"""
    sources = {name: keys[name] for name in EXPRESSIONS if name in keys and has(name)}
    for name, follows, share in (CORNERS_UP, CORNERS_DOWN):
        if follows in sources and has(name):
            sources[name] = [(f, w * share) for f, w in sources[follows]]
    ramps = {name: ramps_of(ks) for name, ks in sources.items()}
    snaps = sorted(((r[0] + r[2]) / 2.0, name, i) for name, rs in ramps.items() for i, r in enumerate(rs)
                   if r[2] - r[0] <= SNAP)
    events = []
    for center, name, i in snaps:
        if events and center - events[-1]["first"] <= TOGETHER:
            events[-1]["members"].append((name, i))
            continue
        events.append({"first": center, "members": [(name, i)]})
    plans = {}
    for event in events:
        centers = [(ramps[n][i][0] + ramps[n][i][2]) / 2.0 for n, i in event["members"]]
        center = float(np.mean(centers))
        lengths = {"onset": rng.randint(*ONSET_FRAMES), "offset": rng.randint(*OFFSET_FRAMES),
                   "change": rng.randint(*CHANGE_FRAMES)}
        delays = {part: rng.randint(*span) for part, span in DELAY.items()}
        shift = align_shift(center, speed)
        event.update(center=center, shift=shift)
        for name, i in event["members"]:
            r = ramps[name][i]
            length = lengths[_kind(r[1], r[3])]
            middle = (r[0] + r[2]) / 2.0 + shift + delays[PART[name]]
            s = int(round(middle - length / 2.0))
            plans[(name, i)] = [s, s + length, False]
    out = {}
    for name, rs in ramps.items():
        placed = []
        for i, r in enumerate(rs):
            span = plans.get((name, i), [r[0], r[2], True])
            placed.append([span[0], span[1], span[2], r[1], r[3], r[0], r[2]])
        out[name] = modulate(sources[name], resolve(placed, frames), env, PART[name], frames)
    return out, events


def resolve(placed, frames):
    """make the changes of one morph follow each other.  [start, end, slow, from, to, original start, original end]:
    a slow change (kept where it was) that met a stretched one gives way to it (it ends where that one starts, or
    starts where it ends), two stretched changes that overlap meet in the middle"""
    for a, b in zip(placed, placed[1:]):
        touching = a[6] == b[5]
        if a[2] and not b[2] and (touching or b[0] < a[1]):
            if b[0] > a[0] + 1:
                a[1] = b[0]
            else:
                b[0] = a[1]
        elif b[2] and not a[2] and (touching or b[0] < a[1]):
            if a[1] < b[1] - 1:
                b[0] = a[1]
            else:
                a[1] = b[0]
        elif b[0] < a[1]:
            meet = int(round((a[1] + b[0]) / 2.0))
            a[1], b[0] = meet, meet
        if b[1] <= b[0]:
            b[1] = b[0] + 1
    previous = 0
    for p in placed:
        p[0] = min(max(p[0], previous), frames - 2)
        p[1] = min(max(p[1], p[0] + 1), frames - 1)
        previous = p[1]
    return [p[:5] for p in placed]


def align_shift(center, speed, length=13.0):
    """frames to move a change of the face (about `length` frames long) so that it starts ALIGN_LEAD frames before
    the fastest turn of the head that it can reach by moving at most ALIGN frames: a local peak at least ALIGN_RATIO
    times the median speed of the second around it and above the median of the song (0 without one)"""
    start = center - length / 2.0
    lo = max(1, int(math.ceil(start + ALIGN_LEAD - ALIGN)))
    hi = min(len(speed) - 2, int(math.floor(start + ALIGN_LEAD + ALIGN)))
    if hi <= lo:
        return 0
    peak = lo + int(np.argmax(speed[lo:hi + 1]))
    if not (speed[peak] >= speed[peak - 1] and speed[peak] >= speed[peak + 1]):
        return 0
    around = speed[max(0, peak - 30):peak + 31]
    if speed[peak] < ALIGN_RATIO * max(np.median(around), 1e-6) or speed[peak] < np.median(speed):
        return 0
    return int(round(peak - ALIGN_LEAD - start))


def modulate(source, placed, env, part, frames):
    """the keys of one morph: each change at its new frames, and the weight between changes lowered along the envelope
    (delayed like the part), so that it never holds still"""
    amount = WAVE[part]
    delay = DELAY[part][0]
    ef = np.array([f for f, _ in env], float) + delay
    er = np.array([r for _, r in env], float)

    def factor(f):
        return 1.0 - amount * float(np.interp(f, ef, er))

    first_value = source[0][1] if source else 0.0
    points = []                            # (frame, base weight)
    if not placed:
        points = [(0, first_value), (frames - 1, first_value)]
    else:
        points.append((0, placed[0][3]))
        for p in placed:
            points.append((p[0], p[3]))
            points.append((p[1], p[4]))
        points.append((frames - 1, placed[-1][4]))
    clean = {}
    for f, w in points:
        clean[int(f)] = w                  # a change starting where the last ended has the same weight there
    seq = sorted(clean.items())
    out = {}
    for (f0, w0), (f1, w1) in zip(seq, seq[1:]):
        out[f0] = w0 * factor(f0) if w0 > ACTIVE else w0
        if (abs(w1 - w0) <= 1e-9 or f1 - f0 > SLOW) and max(w0, w1) > ACTIVE:     # a hold, or a slow drift
            for f in ef:
                f = int(round(f))
                if f0 < f < f1:
                    w = w0 + (w1 - w0) * (f - f0) / float(f1 - f0)
                    out[f] = w * factor(f) if w > ACTIVE else w
    f_last, w_last = seq[-1]
    out[f_last] = w_last * factor(f_last) if w_last > ACTIVE else w_last
    return [(f, float(min(max(w, 0.0), 1.0))) for f, w in sorted(out.items())]


# ---- blinks ---------------------------------------------------------------------------------

def rewrite_blinks(keys, frames, smile, inp, onsets, intro, events, rng):
    """the new まばたき keys and what was done"""
    b_keys = keys.get(BLINK)
    if not b_keys:
        return None, {"list": []}
    b0 = track(b_keys, frames)
    s0 = track(keys.get(SMILE, []), frames)
    closure = b0 + s0
    opened = int(np.argmax(closure < CLOSED)) if (closure < CLOSED).any() else frames
    raw = base_track(b_keys, [], frames, intro, events, stretch=False)
    longs = episodes(raw + s0, opened)                  # what still shuts the eyes without the old blinks is kept
    base = base_track(b_keys, longs, frames, intro, events)
    pitch = eye_pitch(inp.eyes)
    sacc = saccades(inp.head, inp.eyes)
    base = base + lid_offset(pitch, sacc, frames) * (base < CLOSED)
    base = np.clip(base, 0.0, 1.0)
    clear = np.zeros(frames, bool)
    clear[:min(frames, opened + KEEP_CLEAR)] = True
    for e in longs:
        clear[max(0, e["cs"] - KEEP_CLEAR):e["oe"] + KEEP_CLEAR + 1] = True
    candidates = []
    for f in gaze_shifts(inp.head, inp.eyes):
        if rng.random() < P_GAZE:
            candidates.append((f + rng.randint(0, 1), "gaze_shift"))
    for s in sacc:
        if s["amplitude"] >= BIG_SACCADE and rng.random() < P_SACCADE:
            candidates.append((s["start"] - 1 + rng.randint(0, 1), "saccade"))
    starts = [o.frame for o in onsets]
    for a, z in zip(starts, starts[1:]):
        if z - a >= PHRASE_PAUSE and rng.random() < P_PHRASE:
            f = a + rng.randint(*PHRASE_BLINK)
            if f + 10 <= z:
                candidates.append((f, "phrase_end"))
    chosen = []
    for f, cause in sorted(candidates):
        if 0 <= f < frames - 12 and not clear[f] and (not chosen or f - chosen[-1][0] >= MIN_BETWEEN):
            chosen.append((f, cause))
    chosen = fill_blinks(chosen, clear, frames, rng)
    b = base.copy()
    out = []
    for f, cause in chosen:
        closing, hold = rng.choice(CLOSING_FRAMES), (1 if rng.random() < 0.4 else 0)
        opening = rng.choice(OPENING_FRAMES)
        prof = blink_profile(closing, hold, opening)
        for i, p in enumerate(prof):
            g = f + i
            if g >= frames:
                break
            peak = max(base[g], 1.0 - smile[g])
            b[g] = max(b[g], base[g] + (peak - base[g]) * p)
        out.append({"start": int(f), "cause": cause, "closing": closing, "hold": hold, "opening": opening})
    info = {"old_blinks": len(blink_pulses(b_keys, intro)), "long_closures_kept": len(longs), "list": out,
            "by_cause": {c: sum(1 for x in out if x["cause"] == c) for c in ("gaze_shift", "saccade", "phrase_end", "fill")},
            "saccades_found": len(sacc), "big_saccades": sum(1 for s in sacc if s["amplitude"] >= BIG_SACCADE)}
    return bake(b), info


def fill_blinks(chosen, clear, frames, rng):
    """add blinks where none came for a log-normal wait (sometimes a long pause)"""
    out = list(chosen)
    taken = sorted(f for f, _ in out)
    t = int(np.argmax(~clear)) if (~clear).any() else frames
    while t < frames - 20:
        if rng.random() < LONG_PAUSE_CHANCE:
            wait = rng.uniform(*LONG_PAUSE)
        else:
            wait = math.exp(rng.gauss(math.log(FILL_MEDIAN), FILL_SIGMA))
        nxt = t + int(round(wait * FPS))
        i = bisect.bisect_right(taken, t)
        if i < len(taken) and taken[i] <= nxt:
            t = taken[i]
            continue
        f = nxt
        while f < frames - 20 and clear[f]:
            f += 1
        if f >= frames - 20:
            break
        if all(abs(f - g) >= MIN_BETWEEN for g in taken):
            bisect.insort(taken, f)
            out.append((f, "fill"))
        t = f
    return sorted(out)


def base_track(b_keys, longs, frames, intro, events, stretch=True):
    """the lid without the old blinks: each level held until the next, a level change hidden in an old blink made over
    BASE_SWITCH frames, a quick change with the expressions stretched like them (the eyes' delay), the opening at the
    start eased"""
    kf = np.array([f for f, _ in b_keys])
    kw = np.array([w for _, w in b_keys])
    remove, post = set(), {}
    for j0, j1 in blink_pulses(b_keys, intro):
        remove.update(range(j0, j1 + 1))
        if j0 - 1 >= 0 and kf[j0] - kf[j0 - 1] <= 2:
            remove.add(j0 - 1)
        if j1 + 1 < len(kf):
            post[j1 + 1] = int(kf[j0])
    protected = np.zeros(frames + 1, bool)
    for e in longs:
        protected[max(0, e["cs"] - 2):e["oe"] + 3] = True
    keep = [i for i in range(len(kf)) if i not in remove]
    points = []
    centers = [(e["center"], e["shift"]) for e in events]
    opening = intro.get("opening")
    for n, i in enumerate(keep):
        f, w = int(kf[i]), float(kw[i])
        if n == 0:
            points.append((f, w))
            continue
        pf, pw = points[-1]
        if i in post:
            if abs(w - pw) > 1e-9:
                sw = post[i]
                points.append((max(pf, sw - BASE_SWITCH // 2), pw))
                points.append((max(pf + 1, sw + BASE_SWITCH // 2), w))
            else:
                points.append((f, w))
            continue
        quick = stretch and 0 < f - pf <= SNAP and abs(w - pw) > 1e-9 and not protected[min(f, frames)]
        if opening is not None and (pf, f) == tuple(opening):
            quick = False
        if quick:
            middle = (pf + f) / 2.0
            shift = 0
            for c, s in centers:
                if abs(c - middle) <= TOGETHER + 2:
                    shift = s
                    break
            middle += shift + DELAY["eye"][0]
            length = CHANGE_FRAMES[0] + 2
            s0 = int(round(middle - length / 2.0))
            s0 = max(s0, pf)
            if s0 > pf:
                points.append((s0, pw))
            points.append((s0 + length, w))
        else:
            points.append((f, w))
    clean = {}
    for f, w in points:
        clean[int(f)] = w
    seq = sorted(clean.items())
    held = [seq[0]]
    for f1, w1 in seq[1:]:
        f0, w0 = held[-1]
        if w1 > w0 and f1 - f0 > CREEP_LONGEST and (w1 - w0) / (f1 - f0) <= STEEP:
            held.append((f1 - CREEP_LONGEST, w0))       # a slow lowering of the lid is what a10 calls a creep
        held.append((f1, w1))
    seq = held
    xs = np.array([f for f, _ in seq], float)
    ys = np.array([w for _, w in seq], float)
    base = np.interp(np.arange(frames), xs, ys)
    if opening is not None:
        a, z = opening
        if 0 <= a < z < frames:
            top, bottom = base[a], base[z]
            x = (np.arange(a, z + 1) - a) / float(z - a)
            base[a:z + 1] = bottom + (top - bottom) * (1.0 - smoothstep(x))
    return base


PULSE_LONGEST = 3               # frames a blink's shut keys span at most (KAZUSA: 1; the long closures: 4 and more)
PULSE_HEIGHT = 0.15             # how far a blink's peak stands above the keys on either side


def blink_pulses(b_keys, intro):
    """[(first, last)] key indices of the old blinks, read from the まばたき keys alone: a run of keys of one weight
    over at most PULSE_LONGEST frames, with a lower key at most 2 frames before and 3 after it (the wake-up at the
    start is none)"""
    kf = [f for f, _ in b_keys]
    kw = [w for _, w in b_keys]
    opening = intro.get("opening") or (-1, -1)
    out = []
    i = 0
    while i < len(kf):
        j = i
        while j + 1 < len(kf) and abs(kw[j + 1] - kw[i]) < 1e-6:
            j += 1
        if (0 < i and j + 1 < len(kf) and kf[j] - kf[i] <= PULSE_LONGEST and kf[i] - kf[i - 1] <= 2
                and kf[j + 1] - kf[j] <= 3 and kw[i] - max(kw[i - 1], kw[j + 1]) >= PULSE_HEIGHT
                and kf[i] > opening[1]):
            out.append((i, j))
        i = j + 1
    return out


def lid_offset(pitch, sacc, frames):
    """まばたき added for where the eyes look, one value per fixation (the median pitch between two saccades),
    changing with each saccade"""
    edges = [0] + [s["start"] for s in sacc] + [frames]
    out = np.zeros(frames)
    previous = None
    for a, z in zip(edges, edges[1:]):
        if z <= a:
            continue
        settle = min(z, a + 3) if a > 0 else a
        p = float(np.median(pitch[settle:z])) if z > settle else float(pitch[a])
        value = LID_DOWN * max(0.0, -p) - LID_UP * max(0.0, p)
        out[a:z] = value
        if previous is not None and a > 0:
            n = min(3, z - a)
            out[a:a + n] = previous + (value - previous) * (np.arange(1, n + 1) / 3.0)
        previous = value
    return out


# ---- mouth ----------------------------------------------------------------------------------

def voice_power(path):
    """the power of the centre of the stereo picture (mid minus side) in VOICE_BAND every 10 ms, read with ffmpeg"""
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    del raw
    n = (len(x) - WINDOW) // HOP
    if n <= 0:
        raise ValueError("the sound %s is too short" % path)
    freqs = np.fft.rfftfreq(WINDOW, 1.0 / SAMPLE_RATE)
    band = (freqs >= VOICE_BAND[0]) & (freqs < VOICE_BAND[1])
    hann = np.hanning(WINDOW).astype(np.float32)
    out = np.zeros(n, np.float64)
    for s0 in range(0, n, 1000):
        s1 = min(n, s0 + 1000)
        idx = (np.arange(s0, s1) * HOP)[:, None] + np.arange(WINDOW)[None, :]
        left, right = x[:, 0][idx] * hann, x[:, 1][idx] * hann
        mid = np.fft.rfft(0.5 * (left + right), axis=1)[:, band]
        side = np.fft.rfft(0.5 * (left - right), axis=1)[:, band]
        pm = mid.real ** 2 + mid.imag ** 2
        ps = side.real ** 2 + side.imag ** 2
        out[s0:s1] = np.maximum(pm - ps, 0.0).sum(axis=1)
    return out


def _seconds(frame):
    return (frame + SHOWN) / FPS


def _voice_at(voice, t0, t1):
    i0 = max(0, int(math.floor((t0 - AUDIO_T0) * 100.0)))
    i1 = min(len(voice), int(math.ceil((t1 - AUDIO_T0) * 100.0)) + 1)
    if i1 <= i0:
        return None
    return float(np.mean(np.log10(voice[i0:i1] + 1e-9)))


def _rank(values):
    v = np.asarray(values, float)
    if len(v) <= 1:
        return np.ones(len(v))
    order = np.argsort(np.argsort(v, kind="stable"), kind="stable")
    return order / float(len(v) - 1)


def gains(onsets, phrases, voice):
    """the height factor of each onset (1 for the ones that are no sung key of 1.0)"""
    last = {p.end for p in phrases}
    sung = [i for i, o in enumerate(onsets) if o.weight >= SUNG]
    out = [1.0] * len(onsets)
    if not sung:
        return out
    frames_all = [o.frame for o in onsets]
    lengths = []
    for i in sung:
        f = onsets[i].frame
        nxt = next((g for g in frames_all if g > f), f + 15)
        lengths.append(min(nxt - f, 15))
    score = _rank(lengths)
    if voice is not None:
        loud = []
        for i in sung:
            t = _seconds(onsets[i].frame)
            v = _voice_at(voice, t + 0.03, t + 0.25)
            loud.append(-99.0 if v is None else v)
        score = 0.5 * score + 0.5 * _rank(loud)
    for i, sc in zip(sung, score):
        g = GAIN[0] + (GAIN[1] - GAIN[0]) * float(sc)
        if VOWELS[("aiueo").index(onsets[i].vowel)] in SMALL_VOWELS:
            g = max(g, SMALL_FLOOR)
        if onsets[i].frame in last:
            g = max(g, FINAL_FLOOR)
        out[i] = g
    return out


def rewrite_mouth(keys, frames, onsets, phrases, inp, rng):
    """the new keys of あいうえお and what was done"""
    present = [v for v in VOWELS if v in keys]
    if not present or not onsets:
        return {}, {"onsets": len(onsets)}
    X0 = np.stack([track(keys.get(v, []), frames) for v in VOWELS], axis=1)
    g = gains(onsets, phrases, inp.voice)
    X = X0.copy()
    by_vowel = {}
    for i, o in enumerate(onsets):
        by_vowel.setdefault("aiueo".index(o.vowel), []).append((o.frame, g[i]))
    for col, pts in by_vowel.items():
        G = np.full(frames, pts[0][1])
        for (fa, ga), (fb, gb) in zip(pts, pts[1:]):
            dip = fa + int(np.argmin(X0[fa:fb + 1, col]))
            G[fa:dip] = ga
            G[dip] = min(ga, gb)
            G[dip + 1:] = gb
        X[:, col] *= G
    X1 = X.copy()
    S1 = X1.sum(axis=1)
    counts = {"crossfades": 0, "closures": 0, "closures_center_moved": 0, "phrase_starts": 0, "phrase_ends": 0}
    for k, (oa, ob) in enumerate(zip(onsets, onsets[1:])):
        a, b = oa.frame, ob.frame
        if b - a >= PHRASE_GAP or b <= a:
            continue
        shut = [f for f in range(a + 1, b) if S1[f] < 0.05]
        if shut:
            c0, c1 = shut[0], shut[-1]
            center = (c0 + c1) / 2.0
            opening = int(min(max(b - math.floor(center), OPEN_FRAMES[0]), OPEN_FRAMES[1]))
            shut_end = b - opening
            shut_start = min(c0, shut_end)
            closing = min(CLOSE_FRAMES, shut_start - a - 1)
            if closing < 1:
                continue
            if abs((shut_start + shut_end) / 2.0 - center) > 0.5:
                counts["closures_center_moved"] += 1
            cs = shut_start - closing
            src = X1[cs].copy()
            for f in range(cs + 1, shut_start + 1):
                X[f] = src * (1.0 - smoothstep((f - cs) / float(closing)))
            X[shut_start:shut_end + 1] = 0.0
            dst = X1[b].copy()
            for f in range(shut_end + 1, b):
                X[f] = dst * smoothstep((f - shut_end) / float(opening))
            counts["closures"] += 1
        elif oa.vowel != ob.vowel:
            dx = CROSSFADE if b - a >= CROSSFADE + 2 else max(1, b - a - 1)
            col_a = "aiueo".index(oa.vowel)
            held = [f for f in range(a, b) if X1[f, col_a] >= 0.99 * X1[a, col_a]]
            original = b - (held[-1] if held else a)
            if original >= dx and X1[b, col_a] <= 0.01:
                continue
            dx = max(dx, min(original, b - a - 1))
            s = b - dx
            src, dst = X1[s].copy(), X1[b].copy()
            dst[col_a] = 0.0                       # on the onset the old vowel is gone
            X[b] = dst
            for f in range(s + 1, b):
                e = smoothstep((f - s) / float(dx))
                X[f] = src * (1.0 - e) + dst * e
            counts["crossfades"] += 1
    first_of = {p.start for p in phrases}
    last_of = {p.end for p in phrases}
    for o in onsets:
        b = o.frame
        if b in first_of:
            shut = [f for f in range(max(0, b - 8), b) if S1[f] < 0.05]
            if shut:
                r0 = min(shut[-1], b - 2)
                if r0 >= 0 and S1[r0] < 0.05:
                    src, dst = X[r0].copy(), X[b].copy()
                    for f in range(r0 + 1, b):
                        X[f] = src + (dst - src) * smoothstep((f - r0) / float(b - r0))
                    counts["phrase_starts"] += 1
        if b in last_of:
            z = b + 1
            while z < frames and S1[z] >= 0.05 and z - b < 40:
                z += 1
            if z < frames and S1[z] < 0.05 and z - b >= 2:
                top = z - 1
                while top > b and S1[top] < 0.5 * S1[b]:
                    top -= 1
                if z - top < 4:
                    s = max(b, z - 4)
                    src = X[s].copy()
                    for f in range(s + 1, z):
                        X[f] = src * (1.0 - smoothstep((f - s) / float(z - s)))
                    counts["phrase_ends"] += 1
    nxt = [o.frame for o in onsets[1:]] + [frames]
    for o, z in zip(onsets, nxt):
        col = "aiueo".index(o.vowel)
        h = X[o.frame, col]
        f = o.frame + 1
        while f < min(z, frames) and abs(X[f, col] - h) < 1e-9 and h > 0:
            X[f, col] = h * (1.0 - HOLD_RELAX * (1.0 - math.exp(-(f - o.frame) / HOLD_TAU)))
            f += 1
            counts["held_frames_relaxed"] = counts.get("held_frames_relaxed", 0) + 1
    S = X.sum(axis=1)
    over = S > 1.0
    X[over] /= S[over][:, None]
    counts["breaths_between"] = join_breaths(X, onsets, inp.voice, frames)
    counts["breath_frames"] = breathe(X, onsets, phrases, inp, frames, rng)
    S = X.sum(axis=1)
    over = S > 1.0
    X[over] /= S[over][:, None]
    out = {v: bake(X[:, i]) for i, v in enumerate(VOWELS) if v in keys or X[:, i].any()}
    gs = [x for x, o in zip(g, onsets) if o.weight >= SUNG]
    info = dict(counts, onsets=len(onsets), gain={"min": _r(min(gs)), "median": _r(np.median(gs)), "max": _r(max(gs))}
                if gs else None)
    return out, info


def join_breaths(X, onsets, voice, frames):
    """a short open breath where the voice stops for 100 ms or more between two vowels"""
    if voice is None:
        return 0
    db = 10.0 * np.log10(voice + 1e-12)
    done = 0
    for oa, ob in zip(onsets, onsets[1:]):
        a, b = oa.frame, ob.frame
        if not JOIN_GAP[0] <= b - a <= JOIN_GAP[1]:
            continue
        t0, t1 = _seconds(a + 2), _seconds(b)
        i0, i1 = int((t0 - AUDIO_T0) * 100), int((t1 - AUDIO_T0) * 100)
        lo, hi = int((_seconds(a - 90) - AUDIO_T0) * 100), int((_seconds(b + 90) - AUDIO_T0) * 100)
        if i1 - i0 < JOIN_PAUSE_BINS or i0 < 0 or i1 >= len(db):
            continue
        median = float(np.median(db[max(0, lo):min(len(db), hi)]))
        low = db[i0:i1] < median - JOIN_PAUSE_DB
        best = max(runs(low), key=lambda r: r[1] - r[0], default=None)
        if best is None or best[1] - best[0] + 1 < JOIN_PAUSE_BINS:
            continue
        quiet = AUDIO_T0 + (i0 + best[0]) / 100.0
        s = max(a + 3, int(round(quiet * FPS - SHOWN)))
        z = b - JOIN_INTO                              # from here the mouth goes on to the next vowel
        if z - s < 4:
            continue
        shape = np.zeros(5)
        shape[0] = JOIN_BREATH
        rise = min(4, z - s)
        for f in range(s, s + rise + 1):
            w = smoothstep((f - s) / float(rise))
            X[f] = (1.0 - w) * X[f] + w * shape
        X[s + rise:z + 1] = shape
        dst = X[b].copy()
        for f in range(z + 1, b):
            e = smoothstep((f - z) / float(b - z))
            X[f] = (1.0 - e) * shape + e * dst
        done += 1
    return done


def breathe(X, onsets, phrases, inp, frames, rng):
    """あ rising and falling slowly where nothing is sung"""
    singing = np.zeros(frames, bool)
    for p in phrases:
        singing[max(0, p.start - 15):min(frames, p.end + 21)] = True
    for start, end in inp.lines:
        singing[max(0, int(start * FPS) - 6):min(frames, int(end * FPS) + 7)] = True
    for o in onsets:
        singing[max(0, o.frame - 10):min(frames, o.frame + 11)] = True
    n = 15
    mask = np.convolve((~singing).astype(float), np.ones(n) / n, mode="same")
    mask[singing] = 0.0
    hard = intensity(inp.head, inp.head_pos)
    phase = np.zeros(frames)
    p, f = 0.0, 0
    period = rng.uniform(*BREATH_PERIOD) * FPS
    while f < frames:
        phase[f] = p
        p += 2.0 * math.pi / period
        if p >= 2.0 * math.pi:
            p -= 2.0 * math.pi
            period = rng.uniform(*BREATH_PERIOD) * FPS
        f += 1
    top = BREATH[1] + (BREATH[2] - BREATH[1]) * hard
    breath = BREATH[0] + (top - BREATH[0]) * (0.5 - 0.5 * np.cos(phase))
    low = X[:, 0] < BREATH_CAP
    X[low, 0] = np.minimum(X[low, 0] + (mask * breath)[low], BREATH_CAP)
    return int((mask > 0).sum())


# ---- measures (the definitions of a11, a10 and a12) ------------------------------------------

def _dist(values):
    if not len(values):
        return None
    v = np.asarray(values, float)
    return {"n": int(len(v)), "median": _r(np.median(v)), "p10": _r(np.percentile(v, 10)), "p90": _r(np.percentile(v, 90)),
            "min": _r(v.min()), "max": _r(v.max())}


def measure_expressions(keys, frames, speed):
    """a11: per morph the share of the shown time on which the weight is held (between two keys of one weight) and the
    longest hold; the frames of every change between keys; the changes of the face and the head around them"""
    per, ramps, transitions, starts, t_starts = {}, [], [], [], []
    for name in EXPRESSIONS:
        ks = keys.get(name, [])
        w = track(ks, frames)
        active = int((w > ACTIVE).sum())
        holds = [(f1 - f0) for (f0, w0), (f1, w1) in zip(ks, ks[1:]) if abs(w1 - w0) <= 1e-6 and w0 > ACTIVE]
        still = (np.abs(np.diff(w, prepend=w[0])) < 1e-6) & (w > ACTIVE)
        still_runs = [e - s + 1 for s, e in runs(still)]
        moved = np.abs(np.concatenate([w[30:], np.repeat(w[-1:], 30)]) - w)       # change over the next second
        flat = (moved < 0.01) & (w > ACTIVE)
        per[name] = {"keys": len(ks), "active_frames": active,
                     "flat_1s_share_of_active": _r(flat.sum() / active, 3) if active else 0.0,
                     "plateau_share_of_active": _r(sum(holds) / active, 3) if active else 0.0,
                     "longest_plateau_s": _r(max(holds, default=0) / FPS, 2),
                     "still_share_of_active": _r(still.sum() / active, 3) if active else 0.0,
                     "longest_still_s": _r(max(still_runs, default=0) / FPS, 2)}
        run = None
        for (f0, w0), (f1, w1) in zip(ks, ks[1:]):
            if abs(w1 - w0) > 1e-6:
                ramps.append(f1 - f0)
                starts.append(f0)
                way = 1 if w1 > w0 else -1
                if run is not None and run[2] == way and run[1] == f0:
                    run[1], run[3] = f1, run[3] + abs(w1 - w0)
                else:
                    if run is not None and run[3] >= 0.2:
                        transitions.append(run[1] - run[0])
                        t_starts.append(run[0])
                    run = [f0, f1, way, abs(w1 - w0)]
            else:
                if run is not None and run[3] >= 0.2:
                    transitions.append(run[1] - run[0])
                    t_starts.append(run[0])
                run = None
        if run is not None and run[3] >= 0.2:
            transitions.append(run[1] - run[0])
            t_starts.append(run[0])

    def clustered(points):
        out_ = []
        for f in sorted(set(points)):
            if not out_ or f - out_[-1] > 3:
                out_.append(f)
        return out_
    changes = clustered(starts)
    events = clustered(t_starts)
    together = {}
    for f in events:
        n = sum(1 for s in t_starts if abs(s - f) <= 1)
        together[str(n)] = together.get(str(n), 0) + 1
    out = {"per_morph": per, "ramp_frames": _dist(ramps), "transition_frames": _dist(transitions),
           "share_ramps_le_5": _r(np.mean(np.array(ramps) <= 5), 3) if ramps else None,
           "changes_a11": len(changes), "transitions": len(events), "morphs_starting_together": together}
    if events:
        rng = np.random.default_rng(MEASURE_SEED)
        ev = np.array(events)

        def around(e):
            return float(np.mean([speed[max(0, f - 6):f + 7].mean() for f in e]))
        observed = around(ev)
        null = [around((ev + rng.integers(0, frames)) % frames) for _ in range(SHIFTS)]
        out["head_speed_around_changes"] = {"observed_deg_s": _r(observed * FPS, 1), "chance_deg_s": _r(np.mean(null) * FPS, 1),
                                            "ratio": _r(observed / max(np.mean(null), 1e-9), 3),
                                            "p_higher": _r(np.mean(np.array(null) >= observed), 4)}
    return out


def _coincide(ev, ref, before, after):
    ref = np.sort(np.asarray(ref))
    hit = []
    for f in ev:
        i = np.searchsorted(ref, f - before)
        hit.append(i < len(ref) and ref[i] <= f + after)
    return float(np.mean(hit)) if hit else float("nan")


def _shift_test(ev, ref, span, before, after, rng):
    a, z = span
    ev = np.asarray([f for f in ev if a <= f <= z])
    if not len(ev) or not len(ref):
        return {"n": int(len(ev))}
    length = z - a + 1
    observed = _coincide(ev, ref, before, after)
    null = np.array([_coincide(np.sort((ev - a + rng.integers(30, length - 30)) % length + a), ref, before, after)
                     for _ in range(SHIFTS)])
    return {"n": int(len(ev)), "observed": _r(observed), "chance_mean": _r(null.mean()),
            "chance_p2.5": _r(np.percentile(null, 2.5)), "chance_p97.5": _r(np.percentile(null, 97.5)),
            "p_greater": _r((null >= observed).mean(), 4)}


def measure_blinks(keys, frames, inp, onsets, opened):
    """a10: the closures, the creep of the lid, the shapes, the intervals and the ties to the gaze and the phrases"""
    b = track(keys.get(BLINK, []), frames)
    s = track(keys.get(SMILE, []), frames)
    opened = int(opened or 0)
    eps = episodes(b + s, opened)
    blinks = [e for e in eps if e["closed"] <= SHORT_CLOSURE]
    t_all = np.array([e["t0"] for e in eps])
    seconds = (frames - opened) / FPS
    ibi = np.diff(t_all) / FPS
    out = {"episodes": len(eps), "blinks": len(blinks), "long_closures": len(eps) - len(blinks),
           "rate_per_min": _r(len(eps) / seconds * 60.0, 2) if seconds > 0 else None}
    cr = creep_runs(b, opened)
    out["creep"] = {"runs": len(cr), "frames": int(sum(e - s0 + 1 for s0, e in cr))}
    shapes = {}
    lengths = []
    for e in blinks:
        k = "%d-%d-%d" % (e["closing"], e["closed"], e["opening"])
        shapes[k] = shapes.get(k, 0) + 1
        lengths.append(e["oe"] - e["cs"])
    out["shapes"] = dict(sorted(shapes.items(), key=lambda kv: -kv[1]))
    out["frames_closing_start_to_open"] = _dist(lengths)
    if len(ibi) > 2:
        m = ibi.mean()
        out["ibi"] = {"n": int(len(ibi)), "median": _r(np.median(ibi), 2), "max": _r(ibi.max(), 2),
                      "cv": _r(ibi.std(ddof=1) / m, 2), "skew": _r(((ibi - m) ** 3).mean() / ibi.std() ** 3, 2),
                      "share_gt_5s": _r((ibi > 5.0).mean(), 3), "share_lt_0.5s": _r((ibi < 0.5).mean(), 3)}
    rng = np.random.default_rng(MEASURE_SEED)
    span = (opened + 30, frames - 40)
    if len(t_all) and span[1] - span[0] > 100:
        out["gaze_shift_33"] = _shift_test(gaze_shifts(inp.head, inp.eyes), t_all, span, 3, GAZE_SHIFT_FRAMES, rng)
        big = [x["start"] for x in saccades(inp.head, inp.eyes) if x["amplitude"] >= BIG_SACCADE]
        out["big_saccade"] = _shift_test(big, t_all, span, 3, GAZE_SHIFT_FRAMES, rng)
        starts = np.array([o.frame for o in onsets])
        if len(starts) > 4:
            gap = np.diff(starts)
            ends = starts[:-1][gap >= PHRASE_PAUSE]
            sung = (int(starts[3]), int(starts[-1]))
            out["phrase_end_15"] = _shift_test(ends, t_all, sung, 15, 15, rng)
    return out


def _vowel_matrix(keys, frames):
    return np.stack([track(keys.get(v, []), frames) for v in VOWELS], axis=1)


def _onsets_of(keys):
    motion = vmd.Motion(morphs=[vmd.MorphKey(n, f, w) for n in VOWELS for f, w in keys.get(n, [])])
    try:
        return lip_timing.onsets(motion)
    except ValueError:
        return []


def _mouth_shape(keys, frames, lines):
    X = _vowel_matrix(keys, frames)
    S = X.sum(axis=1)
    ons = _onsets_of(keys)
    sung = np.zeros(frames, bool)
    for start, end in lines:
        sung[max(0, int(round(start * FPS))):min(frames, int(round(end * FPS)) + 1)] = True
    dX = np.concatenate([[1.0], np.abs(np.diff(X, axis=0)).sum(axis=1)])
    out = {"onsets": len(ons), "onset_weight_eq1": _r(np.mean([o.weight >= 0.999 for o in ons]), 3) if ons else None,
           "sum_max": _r(S.max(), 4), "frames_sum_over_1": int((S > 1.0001).sum())}
    peaks = {(o.frame, o.vowel): o.weight for o in ons}
    over, xfade, closures = [], [], []
    for oa, ob in zip(ons, ons[1:]):
        a, b = oa.frame, ob.frame
        if b - a >= PHRASE_GAP or b <= a:
            continue
        cb = "aiueo".index(ob.vowel)
        if oa.vowel != ob.vowel and S[a:b + 1].min() >= 0.05:
            over.append(S[a:b + 1].max() > 1.05)
            quiet = np.where(X[a:b + 1, cb] <= 0.02 * peaks[(b, ob.vowel)])[0]      # the new vowel's rise
            xfade.append((b - a) - (quiet.max() if len(quiet) else 0))
        shut = [f for f in range(a + 1, b) if S[f] < 0.05]
        if shut and b - a <= 30:
            g, c = shut[-1], shut[0]
            p = c - 1
            while p > a and S[p] < 0.95 * S[a]:
                p -= 1
            closures.append((c - p, g - c + 1, b - g))
    out["diff_vowel_over_1.05"] = _r(np.mean(over), 3) if over else None
    out["crossfade_frames"] = _dist(xfade)
    if xfade:
        out["crossfade_hist"] = {str(k): int(sum(1 for x in xfade if x == k)) for k in range(0, 8)}
    out["closures"] = {"n": len(closures), "closing": _dist([c[0] for c in closures]),
                       "shut": _dist([c[1] for c in closures]), "opening": _dist([c[2] for c in closures]),
                       "closing_1_frame": int(sum(1 for c in closures if c[0] == 1)),
                       "opening_1_frame": int(sum(1 for c in closures if c[2] == 1))}
    if sung.any():
        out["still_share_in_lines"] = _r((dX < 1e-6)[sung].mean(), 3)
    outside = ~sung
    still = (dX < 1e-6) & outside
    out["outside_still_share"] = _r(still.sum() / max(1, outside.sum()), 3)
    out["outside_longest_still_s"] = _r(max((e - s + 1 for s, e in runs(still)), default=0) / FPS, 2)
    return out, ons


def line_lags(onsets, voice, lines):
    """a12 (s11): per lyric line, ms from the onsets to the steepest rise of the averaged log centre power"""
    if voice is None or not lines:
        return None
    logv = np.log10(voice + 1e-6)
    t_aud = np.arange(len(voice)) / 100.0 + AUDIO_T0
    lags = np.arange(-40, 41) / 100.0
    out = []
    for start, end in lines:
        ts = np.array([_seconds(o.frame) for o in onsets if start - 0.1 <= _seconds(o.frame) <= end])
        if len(ts) < 4:
            continue
        rows = []
        for t in ts:
            v = np.interp(t + lags, t_aud, logv)
            seg = (t_aud > t - 1.5) & (t_aud < t + 1.5)
            rows.append((v - logv[seg].mean()) / (logv[seg].std() + 1e-9))
        avg = np.mean(rows, axis=0)
        d = np.diff(avg)
        tl = lags[:-1] + 0.005
        sel = (tl > -0.15) & (tl < 0.25)
        strength = float(avg[(lags > -0.15) & (lags < 0.3)].max() - avg[(lags > -0.15) & (lags < 0.3)].min())
        if strength < 0.4:
            continue
        out.append(round(1000.0 * float(tl[sel][int(np.argmax(d[sel]))])))
    return {"lines": len(out), "median": float(np.median(out)), "p25": float(np.percentile(out, 25)),
            "p75": float(np.percentile(out, 75)), "min": float(min(out)), "max": float(max(out))} if out else None


def measure_mouth(original, new, frames, inp, intro):
    before, ons0 = _mouth_shape(original, frames, inp.lines)
    after, ons1 = _mouth_shape(new, frames, inp.lines)
    old = {(o.frame, o.vowel) for o in ons0}
    now = {(o.frame, o.vowel) for o in ons1}
    lo, hi = intro.get("window") or (1, 0)
    shift = intro.get("moved_by", 0)
    woke = {(f, v) for f, v in old - now if lo <= f <= hi and (f + shift, v) in now}
    after["onsets_moved"] = len(old - now - woke)
    after["onsets_moved_with_the_wake_up"] = len(woke)
    after["onsets_added"] = len(now - old - {(f + shift, v) for f, v in woke})
    sung0 = [o for o in ons0 if o.weight >= SUNG]
    in_lines = [o for o in ons1 if any(s - 0.3 <= _seconds(o.frame) <= e + 0.3 for s, e in inp.lines)]
    sung0 = [o for o in sung0 if any(s - 0.3 <= _seconds(o.frame) <= e + 0.3 for s, e in inp.lines)]
    lag = {"before": line_lags(sung0, inp.voice, inp.lines), "new": line_lags(in_lines, inp.voice, inp.lines)}
    return {"before": before, "new": after, "lag_ms": lag}


# ---- reading the inputs ---------------------------------------------------------------------

def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def eye_track(dance, gaze, frames):
    """the local rotation of 両目 per frame (as applied): the gaze motion's keys, or the dance's without them"""
    keys = sorted((k for k in gaze.bones if k.name == "両目"), key=lambda k: k.frame)
    if not keys:
        keys = sorted((k for k in dance.bones if k.name == "両目"), key=lambda k: k.frame)
    out = np.zeros((frames, 4))
    out[:, 3] = 1.0
    if not keys:
        return out
    frames_k = [k.frame for k in keys]
    for f in range(frames):
        _, q = fk.sample(keys, f, frames_k)
        out[f] = fk.applied(q)
    return out


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        cues = json.load(f).get("cues", [])
    out = []
    for c in cues:
        style = c.get("style") or (c.get("lines") or [{}])[0].get("style")
        if style == "lyric" or str(c.get("id", "")).startswith("lyric"):
            out.append((float(c["start"]), float(c["end"])))
    return sorted(out)


def load(face_path, dance_path, gaze_path, model_path, audio_path=None, cues_path=None):
    face = vmd.load(face_path)
    gaze = vmd.load(gaze_path)
    model = load_model(model_path)
    dance = vmd.load(dance_path)
    frames = fk.last_frame(dance) + 1
    names = [b.name for b in model.bones]
    if "頭" not in names:
        raise ValueError("the model has no bone 頭: the head cannot be followed")
    head_track = fk.world_track(model, dance, ["頭"], 0, frames - 1)["頭"]
    head = np.array([q for _, q in head_track], float)
    head_pos = np.array([p for p, _ in head_track], float)
    eyes = eye_track(dance, gaze, frames)
    dance_keys = sorted({(k.name, k.frame) for k in dance.morphs})
    del dance
    voice = voice_power(audio_path) if audio_path else None
    lines = read_lines(cues_path) if cues_path else []
    return Inputs(face=face, frames=frames, head=head, eyes=eyes, body_start=body_start(head, head_pos), voice=voice,
                  lines=lines, morphs={m.name for m in model.morphs}, dance_morph_keys=dance_keys, head_pos=head_pos)


# ---- the command ----------------------------------------------------------------------------

def write_bytes(path, data):
    """write next to the target and move over it, so a failure leaves the old file as it was"""
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
        k = os.path.normcase(os.path.abspath(path))
        if k in seen:
            raise ValueError("%s and %s are the same file: the inputs, OUT and --report must all differ" % (seen[k], path))
        seen[k] = path


def summary_of(report):
    e, b, m = report["expression"], report["blink"], report["mouth"]
    pick = lambda d, *ks: {k: d.get(k) for k in ks}  # noqa: E731
    return {"intro": report["intro"],
            "expression": {w: dict(pick(e[w], "ramp_frames", "transition_frames"),
                                   plateau_share={n: r["plateau_share_of_active"] for n, r in e[w]["per_morph"].items()},
                                   longest_plateau_s={n: r["longest_plateau_s"] for n, r in e[w]["per_morph"].items()})
                           for w in ("before", "new")},
            "blink": {w: pick(b[w], "blinks", "rate_per_min", "creep", "shapes", "ibi", "gaze_shift_33", "phrase_end_15")
                      for w in ("before", "new")},
            "mouth": {w: pick(m[w], "onset_weight_eq1", "sum_max", "diff_vowel_over_1.05", "crossfade_frames",
                              "closures", "outside_still_share", "onsets_moved") for w in ("before", "new")},
            "lag_ms": m["lag_ms"]}


def run(face_path, dance_path, gaze_path, model_path, out_path, audio_path=None, cues_path=None, report_path=None, seed=0):
    started = time.time()
    check_distinct(face_path, dance_path, gaze_path, model_path, out_path, report_path, audio_path, cues_path)
    paths = [os.path.abspath(p) for p in (face_path, dance_path, gaze_path, model_path, out_path)]
    inp = load(paths[0], paths[1], paths[2], paths[3], audio_path and os.path.abspath(audio_path),
               cues_path and os.path.abspath(cues_path))
    result = plan(inp, seed)
    write_bytes(paths[4], vmd.dumps(result.motion))
    back = vmd.load(paths[4])
    files = {"face": paths[0], "dance": paths[1], "gaze": paths[2], "model": paths[3], "out": paths[4],
             "audio": audio_path and os.path.abspath(audio_path), "cues": cues_path and os.path.abspath(cues_path)}
    summary = dict(files, keys=len(back.morphs), seed=seed, **summary_of(result.report))
    if report_path:
        full = os.path.abspath(report_path)
        write_bytes(full, (json.dumps(dict(files, keys=len(back.morphs), **result.report), ensure_ascii=True, indent=1)
                           + "\n").encode("ascii"))
        summary["report"] = full
    summary["seconds"] = _r(time.time() - started, 1)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("face", help="the face motion to rewrite (.vmd: expressions, まばたき, あいうえお)")
    p.add_argument("dance", help="the dance motion it is loaded after (.vmd): the head, and its own face keys")
    p.add_argument("gaze", help="the gaze motion (.vmd with 両目, tools/eye_gaze.py)")
    p.add_argument("model", help="the model (.pmx or .pmd): its bones and morph names")
    p.add_argument("out", help="the face motion to write (.vmd), to load in place of FACE")
    p.add_argument("--audio", help="the song (read with ffmpeg): the loudness of the voice and its pauses")
    p.add_argument("--cues", help="the text cues of the MV (.json): the lyric lines")
    p.add_argument("--report", help="write the measures before and after and what was done to this JSON")
    p.add_argument("--seed", type=int, default=0, help="the random draws (default 0)")
    args = p.parse_args(argv)
    try:
        result = run(args.face, args.dance, args.gaze, args.model, args.out, args.audio, args.cues, args.report, args.seed)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
