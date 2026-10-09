"""Give a dancer eyes that look on their own: fixations on where her face is going, saccades that lead the head's
fast turns, and eye contact with the camera planned where the camera stays within reach, written as a 両目 track to
load after the dance.

    python tools/eye_gaze.py DANCE.vmd CAMERA.vmd MODEL.pmx OUT.vmd [--report r.json] [--debug d.json]
                             [--debug-frames F ...] [--probe P.vmd] [--max-yaw 18] [--max-up 6] [--max-down 10]
                             [--max-pitch P (sets up and down to P)] [--seed 0] [--cues CUES.json] [--chorus S ...]

Why: the dance of the MV keys 両目, 右目 and 左目 once each, on frame 0: her eyes never move.  On Sour's Rin 両目
turns both eyes (右目 and 左目 take its rotation by append, ratio 1), so one track does it.  The first version of this
tool (until 2026-10) made the eyes follow the camera and nothing else: the analysis of the MV v2 (uncanny/a07, a13,
a20) found them at the edge of their range 59 % of the time (up to 4 s on end), 15 degrees or more off the middle
42 %, carried by the head in 93 % of the large gaze changes, ahead of the head in 4 % of its fast turns, and in eye
contacts of 0.30 s (median) that came and went 51 times a minute with no relation to the song.  This version plans
the gaze as a person's: the eyes move first, look where the face goes, and look at the viewer at chosen moments.

Where the camera is, seen from her eyes (sights; mmd_cli/fk.py does the forward kinematics):

* The eye center is the midpoint of 右目 and 左目 in the world.  両目 itself is a handle above the head on Sour's
  Rin (height 19.37 against eyes at 17.21: aiming from it would tilt the gaze by 3.5 degrees at 35 units); its
  position is used only when the model lacks 右目 or 左目.
* The head frame is the world rotation of 両目's parent (頭).  The camera is fk.camera_position of the camera motion.
* A direction v in the head frame is read as yaw (positive toward the model's left, +X) and pitch (positive up),
  each relative to the eyes' rest gaze: the direction from 両目 to 両目先 (or to its tail) when it lies within
  FORWARD_TOLERANCE of -Z (on Sour's Rin it is exactly -Z), else -Z.
* A camera cut is a frame on which the camera moves more than CUT_JUMP units or turns its line of sight more than
  CUT_TURN degrees from the frame before.

How the eyes move (plan: the whole song is known, so the plan looks ahead):

* The limits are --max-yaw to either side, --max-up and --max-down (6 up and 10 down by default: at +10 degrees the
  upper lid of Sour's Rin covers 17 % more of the iris, review 8).  Every angle written goes through soften() (the
  last part of each range approached along tanh) and is clamped to the limits.  Two zones inside them: the free
  zone (FREE_SHARE of each limit: 12, 4 and 7 degrees by default), where a fixation may hold the eyes, and the
  contact zone (CONTACT_SHARE: 16, 5.3 and 8.9), inside the 90 % lines the analysis counts as the edge.
* Fixations (state free).  The eyes hold a point in the world (a direction: far away) and counter-rotate as the head
  moves (the vestibulo-ocular reflex).  The point is where the face is going: of the head's forward averaged over
  the next 0, 4, 8, 12 or 18 frames from the landing, the one that stays inside the free zone longest (at most
  HOLD_MAX frames), kept AVOID degrees off the camera.  When the point will be out of the free zone LOOK_AHEAD
  frames from now (or behind her), the eyes move on (a recentre saccade) unless it is back inside within RETURN
  frames (a nod with the beat) and still inside the limits.  A fixation lasts at least MIN_FIXATION frames.  After
  GLANCE frames (drawn from the seed) of one fixation, a glance: a saccade to a new point a few degrees off the face's
  way.  The analysis measured why the point must follow the face: the head turns its forward by 10 degrees in 0.2 s
  (median), so a point held on its own leaves the eyes' range in 5 frames.
* Leads (a20, Lasseter: "the eyes move first, a few frames before the head").  A fast turn is a run of the head
  forward's yaw rate (in the world) above TURN_SPEED for 2 frames or more; its onset is the first of the 15 frames
  before at 30 % of the peak.  LEAD frames before the onset (2 to 4, from the seed) the eyes jump the way of the
  turn: toward where the face will be when the turn has gone furthest (within 20 frames), at most LEAD_SHARE of the
  yaw limit off the middle and at least LEAD_STEP degrees beyond where they are (capped by that).  Until the onset
  they keep that angle in the head (state lead: a person's gaze shift holds the reflex off); from the onset they hold
  that point in the world, so the head turns toward where the eyes already are.  For QUIET frames before a lead no
  other saccade starts, and for GUARD frames after the onset a recentre only when the limits are passed.
* Eye contact (state contact) is planned first, on the whole song.  The camera is within reach on a frame when the
  eyes, held inside the contact zone, would be within CONTACT_ERROR of it (and it is not behind her); gaps of
  CONTACT_GAP frames or less are closed (the analysis joins them too).  No contact from END_CLEAR frames before a
  cut to CUT_CLEAR after it: she cannot see the edit, and searching for the camera at every cut was one of the
  analysis' findings.  Every run of CONTACT_MIN frames or more becomes a contact, cut to CONTACT_MAX with an anchor
  of the song two thirds in when it is longer; runs of CONTACT_MID frames or more become contacts only near an anchor
  (ANCHOR_NEAR frames), the longest first and CONTACT_SPARE fewer than the long ones, so that the median contact is
  a long one.  The anchors are the ends of the lyric lines and the starts of the hooks of --cues and the heads of
  the choruses (--chorus, seconds).  A small shift of a cue (textlight moves four lines by 0.3 to 0.9 s) moves a
  contact by as much at most: a contact is found by the camera's reach and only placed by its anchor.  A contact
  starts with a saccade that lands by its first frame and ends with a look away (a saccade to a point off the face's
  way).  Its eyes follow the camera inside the contact zone (contact_angles).
* Outside the contacts the gaze keeps KEEP_OFF degrees off the camera on every frame, saccades on their way too: a
  pass over the camera would count as a one-frame eye contact.
* A saccade takes main_sequence_frames(A) frames: D = 21 + 2.2 A ms rounded to frames (at least one: under 13.5
  degrees one frame, under 28.7 two, then three), along a minimum-jerk profile from where the eyes were to where
  the target is on each frame of it (a point in the world, the camera, or a lead's angle in the head).  A move under
  MIN_SACCADE is no saccade: the fixation alone moves.
* Life: a slow drift (a random walk of up to DRIFT_STEP per frame and axis, kept within DRIFT_LIMIT) and a
  microsaccade every MICRO_INTERVAL frames that jumps back to within MICRO_SIZE of the center are added on top; well
  under a degree.  Everything random comes from the seed (random.Random), so the same seed gives the same file.

What is written: a VMD that holds only the 両目 track, a key on every frame where the angles change (and the first
and last frame) with the linear curve, under the dance's model name.  Load it after the dance: it replaces the
dance's single 両目 key.  The rotation is made with mmd_cli.fk.stored, so it follows the one convention of
mmd_cli/fk.py (KEY_ROTATION_SIGNS).  Keys the dance has on 右目 or 左目 would add to it (the report lists them).

The report (--report, and in short on stdout): the shares of frames in each state (contact, free, lead, in_saccade;
they add up to 1), the saccades (their reasons: contact, look_away, lead, recentre, glance; the list has frame,
frames, reason and amplitude like the first version's, so the analysis' scripts read it), the contacts (first and
last frame, seconds, the anchor they hold), the anchors, the cuts, the error on the camera during the contacts, and
measures: the target numbers of the analysis computed on the plan, by the analysts' definitions (eye_measures,
contact_measures, lead_measure, carried_measure; README: eye_gaze.py).  --debug writes, for --debug-frames
(default: every DEBUG_STEP-th frame), the geometry of those frames.

--probe P.vmd also writes a short 両目 motion to check the convention on a render: frames 0-29 rest, 30-59 window Y
+15, 60-89 Y -15, 90-119 X +10, 120-149 X -10, rest again on 150.  The summary says which way each should look if
the convention of mmd_cli/fk.py is right.
"""
import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk, mathutil  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

EYES = "両目"
EYE_TIP = "両目先"
EYE_PAIR = ("右目", "左目")
FPS = 30.0
MAX_YAW = 18.0                        # degrees the eyes turn sideways (default of --max-yaw)
MAX_UP, MAX_DOWN = 6.0, 10.0          # degrees they turn up and down (--max-up, --max-down; review 8, R1: at +10 the
                                      # upper lid of Sour's Rin covers 17 % more of the iris)
LIMIT_MAX = 45.0                      # degrees: the most a limit may be
SOFT_FROM = 0.6                       # share of a limit up to which the eyes follow exactly; beyond, tanh towards it
EDGE = 0.9                            # share of a limit from which the analysis counts the eyes as at the edge
FREE_SHARE = (2.0 / 3.0, 2.0 / 3.0, 0.7)      # the free zone, shares of the yaw, up and down limits (12, 4, 7)
CONTACT_SHARE = (0.889, 0.883, 0.89)          # the contact zone (16, 5.3, 8.9: inside the EDGE lines)
CONTACT_ERROR = 3.5                   # degrees off the camera at most for a frame to be within reach (a13 counts 4)
CONTACT_GAP = 2                       # frames out of reach that do not break a run (a13 joins gaps of 2)
CONTACT_MIN = 48                      # frames: a run this long is always a contact (1.6 s)
CONTACT_MID = 30                      # frames: a run this long is a contact near an anchor of the song
CONTACT_SPARE = 2                     # the shorter contacts are this many fewer than the long ones
CONTACT_MAX = 150                     # frames: a contact lasts at most this (5 s)
ANCHOR_NEAR = 30                      # frames from a run within which an anchor counts (1 s)
END_CLEAR, CUT_CLEAR = 2, 6           # frames before and after a cut without a contact
LOOK_AHEAD = 2                        # frames ahead at which a fixation's point is checked against the free zone
RETURN = 4                            # frames within which a point back inside the free zone needs no saccade
MIN_FIXATION = 6                      # frames from the landing of a saccade to the earliest recentre or glance (200 ms)
HOLD_MAX = 45                         # frames: how far ahead a new fixation's point is tried
WINDOWS = (0, 4, 8, 12, 18)           # frames of the head's forward averaged for a new fixation's point
GLANCE = (15, 48)                     # frames of one fixation before a glance (both included)
GLANCE_OFF = ((-4.0, 4.0), (-3.0, 1.5))   # degrees off the face's way of a glance or a look away: yaw, pitch
AVOID = 6.0                           # degrees off the camera at which a new fixation's point is put
KEEP_OFF = 5.0                        # degrees off the camera the gaze keeps outside the contacts
TURN_SPEED = 150.0                    # deg/s of the head's yaw that make a fast turn
LEAD = (2, 4)                         # frames before a fast turn's onset at which the eyes jump (both included)
LEAD_SHARE = 13.0 / 18.0              # a lead lands at most this share of the yaw limit off the middle
LEAD_STEP = 6.0                       # degrees beyond where the eyes are that a lead goes at least
QUIET = 8                             # frames before a lead in which no other saccade starts
GUARD = 3                             # frames after a fast turn's onset in which a recentre waits for the limits
MIN_SACCADE = 0.5                     # degrees: a smaller move is no saccade, only the fixation moves
CUT_JUMP = 1.0                        # model units the camera moves in one frame on a cut
CUT_TURN = 5.0                        # degrees the camera's line of sight turns in one frame on a cut
DRIFT_STEP = 0.03                     # degrees per frame and axis, at most, of the fixation drift
DRIFT_LIMIT = 0.3                     # degrees: the drift stays within this on each axis
MICRO_INTERVAL = (15, 45)             # frames between microsaccades
MICRO_SIZE = 0.15                     # degrees: a microsaccade lands within this of the center
FORWARD_TOLERANCE = 20.0              # degrees off -Z within which 両目 -> 両目先 is taken as the rest gaze
DEBUG_STEP = 30
STATES = ("contact", "free", "lead", "in_saccade")
REASONS = ("contact", "look_away", "lead", "recentre", "glance")
# the analysis' measures: a07 (edge, large gaze changes), a13 (eccentricity, eye contact), a20 (leads)
CONTACT_SEEN = 4.0                    # degrees: the analysis counts the gaze within this of the camera as eye contact
CONTACT_JOIN = 2                      # frames: gaps it joins
LARGE_WINDOW, LARGE_CHANGE = 15, 20.0     # a large gaze change: more than 20 degrees in the world within 15 frames
LEAD_TURN, LEAD_MIN_FRAMES, LEAD_SEEN = 200.0, 3, 3.0    # a20: yaw rate, frames, degrees of the eyes ahead
LEAD_MARGINS = (330, 172)             # a20 left out turns in the first 330 and the last 172 frames of the song
# (first frame, last frame, window angles of 両目): the probe
PROBE = ((0, 29, (0.0, 0.0, 0.0)), (30, 59, (0.0, 15.0, 0.0)), (60, 89, (0.0, -15.0, 0.0)),
         (90, 119, (10.0, 0.0, 0.0)), (120, 149, (-10.0, 0.0, 0.0)), (150, 150, (0.0, 0.0, 0.0)))


def _r(value, places=4):
    return round(float(value), places) + 0.0


def _vec(values, places=4):
    return [_r(v, places) for v in values]


# ---- directions -----------------------------------------------------------------------------

def angles_of(v):
    """(yaw, pitch) in degrees of a direction: yaw toward +X (the model's left), pitch up, (0, 0) along -Z"""
    x, y, z = v
    return math.degrees(math.atan2(x, -z)), math.degrees(math.atan2(y, math.hypot(x, z)))


def direction_of(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return (math.cos(p) * math.sin(y), math.sin(p), -math.cos(p) * math.cos(y))


def degrees_between(a, b):
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


def _apart(a, b):
    """degrees between two (yaw, pitch) directions"""
    return degrees_between(direction_of(*a), direction_of(*b))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def eye_rotation(yaw, pitch):
    """the rotation, as applied in the head's frame, that turns the rest gaze by `yaw` (to the model's left, +X) and
    `pitch` (up): pitch about X first, then yaw about the head's vertical (exact for a rest gaze along -Z)"""
    return fk.multiply(_about((0.0, 1.0, 0.0), -yaw), _about((1.0, 0.0, 0.0), pitch))


# ---- where the camera is, seen from her eyes ------------------------------------------------

@dataclass
class Sight:
    frame: int
    eye: Tuple[float, float, float]             # the eye center in the world
    head: Tuple[float, float, float, float]     # the world rotation of the eyes' parent (as applied)
    camera: Tuple[float, float, float]          # the camera in the world
    cut: bool                                   # the camera cut on this frame


def _by_name(model):
    out = {}
    for bone in model.bones:
        out.setdefault(bone.name, bone)
    return out


def eye_bones(model):
    """(the 両目 bone, the names whose positions make the eye center, the name of 両目's parent or None)"""
    by = _by_name(model)
    eyes = by.get(EYES)
    if eyes is None:
        raise ValueError("the model has no %s bone: there is nothing to turn the eyes with" % EYES)
    center = [name for name in EYE_PAIR if name in by]
    if len(center) != len(EYE_PAIR):
        center = [EYES]
    parent = model.bones[eyes.parent].name if eyes.parent is not None else None
    return eyes, center, parent


def rest_forward(model, eyes):
    """(the rest gaze as a unit vector, where it came from): 両目 -> 両目先 (or 両目's tail) when it lies within
    FORWARD_TOLERANCE of -Z, else -Z"""
    candidates = []
    tip = _by_name(model).get(EYE_TIP)
    if tip is not None and tip.position is not None and eyes.position is not None:
        candidates.append((tuple(t - e for t, e in zip(tip.position, eyes.position)), EYE_TIP))
    tail = eyes.tail or {}
    if tail.get("bone") is not None and model.bones[tail["bone"]].position is not None and eyes.position is not None:
        candidates.append((tuple(t - e for t, e in zip(model.bones[tail["bone"]].position, eyes.position)), "tail"))
    elif tail.get("offset") is not None:
        candidates.append((tuple(tail["offset"]), "tail"))
    for v, label in candidates:
        n = math.sqrt(sum(c * c for c in v))
        if n > 1e-6:
            unit = tuple(c / n + 0.0 for c in v)
            if degrees_between(unit, (0.0, 0.0, -1.0)) <= FORWARD_TOLERANCE:
                return unit, label
    return (0.0, 0.0, -1.0), "-Z"


def sights(model, dance, camera, first=0, last=None):
    """per frame from `first` to `last` (the dance's last bone key), where the eyes are, how the head is turned, where
    the camera is and whether it cut"""
    _, center, parent = eye_bones(model)
    names = list(center) + ([parent] if parent is not None and parent not in center else [])
    if last is None:
        last = fk.last_frame(dance)
    track = fk.world_track(model, dance, names, first, last)
    keys = fk.camera_keys(camera)
    frames = [k.frame for k in keys]
    out, previous = [], None
    for i, frame in enumerate(range(first, last + 1)):
        points = [track[name][i][0] for name in center]
        eye = tuple(sum(p[c] for p in points) / len(points) for c in range(3))
        head = track[parent][i][1] if parent is not None else fk.IDENTITY
        state = fk.camera_at(keys, frame, frames)
        position = fk.camera_position(state)
        sight_line = fk.camera_direction(state)             # from the angles: a camera turning on the spot cuts too
        cut = previous is not None and (math.sqrt(sum((a - b) ** 2 for a, b in zip(position, previous[0]))) > CUT_JUMP
                                        or degrees_between(sight_line, previous[1]) > CUT_TURN)
        previous = (position, sight_line)
        out.append(Sight(frame, eye, head, position, cut))
    return out


def _head_angles(sight, direction, rest):
    """((yaw, pitch) of a world direction in the head's frame, relative to the rest gaze; whether it is behind, more
    than 90 degrees off the rest gaze)"""
    v = fk.rotate(fk.conjugate(sight.head), direction)
    yaw, pitch = angles_of(v)
    yaw = (yaw - rest[0] + 180.0) % 360.0 - 180.0
    return (yaw, pitch - rest[1]), sum(a * b for a, b in zip(v, direction_of(*rest))) <= 0.0


def _seen(sight, point, forward, rest):
    """((yaw, pitch) of a world point seen from the eyes in the head's frame, relative to the rest gaze; whether it is
    behind, more than 90 degrees off the rest gaze)"""
    v = fk.rotate(fk.conjugate(sight.head), tuple(p - e for p, e in zip(point, sight.eye)))
    yaw, pitch = angles_of(v)
    yaw = (yaw - rest[0] + 180.0) % 360.0 - 180.0
    return (yaw, pitch - rest[1]), sum(a * b for a, b in zip(v, forward)) <= 0.0


def _world(sight, angles, rest):
    """the world direction seen at `angles` (from the rest gaze) in the head's frame of `sight`"""
    return fk.rotate(sight.head, direction_of(angles[0] + rest[0], angles[1] + rest[1]))


# ---- limits and zones -----------------------------------------------------------------------

@dataclass
class Look:
    frame: int
    yaw: float                      # the eye angles written, degrees from the rest gaze (+ to her left, + up)
    pitch: float
    state: str                      # one of STATES
    target: Tuple[float, float]     # where the camera is (yaw, pitch), not clamped
    error: float                    # degrees between the gaze written and the camera
    mode: str = "free"              # what the eyes hold after this frame: "camera" or "free"
    base: Tuple[float, float] = (0.0, 0.0)     # the eye angles before the drift is added


@dataclass(frozen=True)
class Limits:
    """how far the eyes turn from the rest gaze, in degrees: sideways (both ways), up, down (all positive)"""
    yaw: float = MAX_YAW
    up: float = MAX_UP
    down: float = MAX_DOWN

    def to_json(self):
        return {"yaw": self.yaw, "up": self.up, "down": self.down}


def check_limits(limits):
    for name, value in (("--max-yaw", limits.yaw), ("--max-up", limits.up), ("--max-down", limits.down)):
        if not 0.0 < value <= LIMIT_MAX:
            raise ValueError("%s is how far the eyes turn, above 0 and at most %g degrees, not %r" % (name, LIMIT_MAX, value))


def _zone(limits, shares):
    return Limits(limits.yaw * shares[0], limits.up * shares[1], limits.down * shares[2])


def free_zone(limits):
    """where a fixation may hold the eyes (FREE_SHARE of the limits)"""
    return _zone(limits, FREE_SHARE)


def contact_zone(limits):
    """where a contact may hold the eyes (CONTACT_SHARE of the limits, inside the EDGE lines)"""
    return _zone(limits, CONTACT_SHARE)


def _clamp(angles, limits):
    return (min(max(angles[0], -limits.yaw), limits.yaw), min(max(angles[1], -limits.down), limits.up))


def _inside(angles, zone):
    return abs(angles[0]) <= zone.yaw and -zone.down <= angles[1] <= zone.up


def _excess(angles, zone):
    """degrees by which a direction (yaw, pitch) lies beyond a zone (0 inside it)"""
    yaw, pitch = angles
    return max(abs(yaw) - zone.yaw, pitch - zone.up, -pitch - zone.down, 0.0)


def soft(value, limit):
    """the eye angle for a wanted angle `value` against `limit` (review 8, R2): the same up to SOFT_FROM of the limit,
    beyond it limit * (SOFT_FROM + (1 - SOFT_FROM) tanh((x - SOFT_FROM) / (1 - SOFT_FROM))) with x = |value| / limit.
    It joins with slope 1 (C1), keeps rising, and approaches the limit: a camera exactly at the limit is looked at
    with 90.5 % of it, one 1.4 times as far with 98.6 %, one 3 times as far with 99.9995 %; far beyond that tanh is
    1.0 in floating point and the eyes are at the limit, never past it."""
    x = abs(value) / limit
    if x <= SOFT_FROM:
        return value
    span = 1.0 - SOFT_FROM
    out = limit * (SOFT_FROM + span * math.tanh((x - SOFT_FROM) / span))
    return out if value > 0 else -out


def soften(angles, limits):
    """soft() on each axis: yaw against limits.yaw, pitch against limits.up above and limits.down below"""
    yaw, pitch = angles
    return soft(yaw, limits.yaw), soft(pitch, limits.up if pitch > 0 else limits.down)


def contact_angles(camera, limits):
    """the eye angles that look at the camera (yaw, pitch) during a contact: softened, then held in the contact zone"""
    zone = contact_zone(limits)
    yaw, pitch = soften(camera, limits)
    return min(max(yaw, -zone.yaw), zone.yaw), min(max(pitch, -zone.down), zone.up)


def keep_off(angles, camera, degrees, limits):
    """angles moved away from the camera's angles until they are `degrees` off it, inside the limits: straight away
    when that stays inside, else the nearest of the other ways round the camera that does (or the farthest)"""
    dy, dp = angles[0] - camera[0], angles[1] - camera[1]
    d = math.hypot(dy, dp)
    if d >= degrees:
        return angles
    base = math.atan2(dp, dy) if d > 1e-9 else -math.pi / 2.0
    best = None
    for k in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6):
        a = base + k * math.pi / 6.0
        cand = _clamp((camera[0] + degrees * math.cos(a), camera[1] + degrees * math.sin(a)), limits)
        sep = math.hypot(cand[0] - camera[0], cand[1] - camera[1])
        if sep >= degrees - 1e-9:
            return cand
        if best is None or sep > best[0]:
            best = (sep, cand)
    return best[1]


def _profile(t):
    """minimum jerk: the share of a saccade done at the time t in 0..1"""
    return t * t * t * (10.0 + t * (6.0 * t - 15.0))


def main_sequence_frames(amplitude):
    """frames a saccade of `amplitude` degrees takes: D = 21 + 2.2 A ms (Carpenter 1988) in frames, at least one"""
    return max(1, int(round((21.0 + 2.2 * amplitude) / (1000.0 / FPS))))


def drift_track(frames, rng):
    """(yaw, pitch) offsets of the fixation drift and the microsaccades for each frame, from rng.random() alone"""
    out, dy, dp = [], 0.0, 0.0
    low, high = MICRO_INTERVAL
    next_micro = low + rng.random() * (high - low)
    for frame in range(frames):
        if frame >= next_micro:
            radius, turn = MICRO_SIZE * math.sqrt(rng.random()), 2.0 * math.pi * rng.random()
            dy, dp = radius * math.cos(turn), radius * math.sin(turn)
            next_micro = frame + low + rng.random() * (high - low)
        else:
            dy = min(max(dy + (2.0 * rng.random() - 1.0) * DRIFT_STEP, -DRIFT_LIMIT), DRIFT_LIMIT)
            dp = min(max(dp + (2.0 * rng.random() - 1.0) * DRIFT_STEP, -DRIFT_LIMIT), DRIFT_LIMIT)
        out.append((dy, dp))
    return out


def _runs(mask):
    """[(first, last)] of the runs of True"""
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


# ---- the plan: contacts, fast turns, fixations ------------------------------------------------

def reachable(cameras, limits):
    """per frame whether the camera ((yaw, pitch), behind) is within reach of a contact: within CONTACT_ERROR of the
    eyes held at contact_angles"""
    return [not behind and _apart(contact_angles(angles, limits), angles) <= CONTACT_ERROR for angles, behind in cameras]


def contact_runs(reach, cuts, anchors):
    """[(first, last)] frame indices of the contacts, from `reach` (a bool per frame), the cut indices and the anchor
    indices: see the module docstring"""
    n = len(reach)
    ok = list(reach)
    for a, b in _runs([not v for v in ok]):
        if b - a + 1 <= CONTACT_GAP and a > 0 and b < n - 1:
            for i in range(a, b + 1):
                ok[i] = True
    for c in cuts:
        for i in range(max(0, c - END_CLEAR), min(n, c + CUT_CLEAR)):
            ok[i] = False
    long_, mid = [], []
    for a, b in _runs(ok):
        length = b - a + 1
        if length >= CONTACT_MIN:
            if length > CONTACT_MAX:
                inner = [t for t in anchors if a <= t <= b]
                s = min(max(a, inner[0] - 2 * CONTACT_MAX // 3), b - CONTACT_MAX + 1) if inner else a
                a, b = s, s + CONTACT_MAX - 1
            long_.append((a, b))
        elif length >= CONTACT_MID and any(a - ANCHOR_NEAR <= t <= b + ANCHOR_NEAR for t in anchors):
            mid.append((-length, a, b))
    mid.sort()
    keep = max(0, len(long_) - CONTACT_SPARE)
    return sorted(long_ + [(a, b) for _, a, b in mid[:keep]])


def fast_turns(seen, forward):
    """(the head's forward in the world per frame, [(onset, the frame the turn goes furthest by, its sign)]): see the
    module docstring (Leads)"""
    fw = [fk.rotate(s.head, forward) for s in seen]
    yaw = [math.degrees(math.atan2(f[0], -f[2])) for f in fw]
    step = [0.0] + [(yaw[i] - yaw[i - 1] + 180.0) % 360.0 - 180.0 for i in range(1, len(yaw))]
    rate = [v * FPS for v in step]
    turns = []
    for a, b in _runs([abs(v) > TURN_SPEED for v in rate]):
        if b - a + 1 < 2:
            continue
        sign = 1.0 if sum(rate[a:b + 1]) > 0 else -1.0
        peak = max(sign * v for v in rate[a:b + 1])
        onset = next(i for i in range(max(1, a - 15), b + 1) if sign * rate[i] > 0.3 * peak)
        far, best, total = onset, 0.0, 0.0
        for i in range(onset + 1, min(len(yaw), onset + 21)):
            total += sign * step[i]
            if total > best:
                far, best = i, total
        turns.append((onset, far, sign))
    return fw, turns


def _hold(seen, i, direction, rest, zone, camera_dirs):
    """frames from i on (at most HOLD_MAX) that a world direction stays inside the zone and KEEP_OFF off the camera"""
    n, k = len(seen), 0
    while i + k < n and k < HOLD_MAX:
        angles, behind = _head_angles(seen[i + k], direction, rest)
        if behind or not _inside(angles, zone) or degrees_between(direction, camera_dirs[i + k]) < KEEP_OFF:
            break
        k += 1
    return k


def _off_camera(seen, i, angles, rest, camera_dirs):
    """the world direction at `angles` in the head of frame i, moved to AVOID degrees off the camera if nearer"""
    d = _world(seen[i], angles, rest)
    if degrees_between(d, camera_dirs[i]) >= AVOID:
        return d
    c, _ = _head_angles(seen[i], camera_dirs[i], rest)
    dy, dp = angles[0] - c[0], angles[1] - c[1]
    norm = math.hypot(dy, dp)
    if norm < 1e-9:
        dy, dp, norm = 0.0, -1.0, 1.0
    return _world(seen[i], (c[0] + dy * AVOID / norm, c[1] + dp * AVOID / norm), rest)


def free_point(seen, i, fw, rest, zone, offset, camera_dirs):
    """the world direction of a new fixation landing on frame i: see the module docstring (Fixations)"""
    n, best = len(seen), None
    for w in WINDOWS:
        j = min(n - 1, i + w)
        mean = _unit(tuple(sum(fw[k][c] for k in range(i, j + 1)) for c in range(3)))
        angles, _ = _head_angles(seen[i], mean, rest)
        angles = (min(max(angles[0] + offset[0], -zone.yaw), zone.yaw), min(max(angles[1] + offset[1], -zone.down), zone.up))
        d = _off_camera(seen, i, angles, rest, camera_dirs)
        hold = _hold(seen, i, d, rest, zone, camera_dirs)
        if best is None or hold > best[0]:
            best = (hold, d)
    return best[1]


def plan(seen, forward, limits=Limits(), seed=0, life=True, anchors=()):
    """(a Look per sight, the saccades, the contacts as (first, last) frame indices, the leads planned): see the module
    docstring.  `anchors` are frame indices."""
    check_limits(limits)
    rest = angles_of(forward)
    n = len(seen)
    free = free_zone(limits)
    rng = random.Random(2 * seed + 1)
    drift = drift_track(n, random.Random(2 * seed)) if life else [(0.0, 0.0)] * n
    cameras = [_seen(s, s.camera, forward, rest) for s in seen]
    camera_dirs = [_unit(tuple(c - e for c, e in zip(s.camera, s.eye))) for s in seen]
    cuts = [i for i, s in enumerate(seen) if s.cut]
    contacts = contact_runs(reachable(cameras, limits), cuts, sorted(anchors))
    contact_end, contact_len = [None] * n, [0] * n
    for a, b in contacts:
        for i in range(a, b + 1):
            contact_end[i], contact_len[i] = b, b - a + 1
    fw, turns = fast_turns(seen, forward)
    leads = []                      # [first frame it may start, last frame it may start, onset, far, sign]
    for onset, far, sign in turns:
        start = onset - rng.randint(*LEAD)
        if start >= 1 and not any(contact_end[k] is not None for k in range(max(0, start - QUIET), min(n, onset + 1))):
            leads.append([start, onset - 1, onset, far, sign])
    looks, saccades = [], []
    mode, point, held = "free", fw[0], None       # held: (angles in the head, the frame they become a world point)
    saccade, landed, lead_i, guard_until, reason_now = None, 0, 0, -1, None
    glance_at = rng.randint(*GLANCE)
    for i, s in enumerate(seen):
        while lead_i < len(leads) and leads[lead_i][1] < i:
            lead_i += 1
        upcoming = leads[lead_i] if lead_i < len(leads) else None
        if held is not None and i >= held[1]:
            point, held = _world(s, held[0], rest), None
        want = None
        if saccade is None:
            nxt = i + 1 if i + 1 < n else i
            if contact_end[nxt] is not None and mode != "camera" and contact_end[nxt] - nxt + 1 >= contact_len[nxt] - 3:
                want = ("camera", None, "contact")
            elif mode == "camera" and contact_end[i] is None:
                want = ("free", None, "look_away")
            elif mode == "free" and upcoming is not None and upcoming[0] <= i:
                want = ("free", upcoming, "lead")
                lead_i += 1
            elif mode == "free" and held is None and i - landed >= MIN_FIXATION:
                j = min(n - 1, i + LOOK_AHEAD)
                ahead, behind = _head_angles(seen[j], point, rest)
                quiet = i <= guard_until or (upcoming is not None and upcoming[0] - i <= QUIET)
                if quiet:
                    if behind or _excess(ahead, limits) > 0.0:
                        want = ("free", None, "recentre")
                elif behind or not _inside(ahead, free):
                    back = any(_inside(_head_angles(seen[min(n - 1, j + k)], point, rest)[0], free)
                               for k in range(1, RETURN + 1))
                    if not back or _excess(ahead, limits) > 0.0:
                        want = ("free", None, "recentre")
                elif degrees_between(point, camera_dirs[j]) < KEEP_OFF:
                    want = ("free", None, "recentre")
                elif i - landed >= glance_at:
                    want = ("free", None, "glance")
        if want is not None:
            to, lead, reason = want
            origin = looks[-1].base if looks else (0.0, 0.0)
            goal_point, goal_held = None, None
            if to == "camera":
                goal = contact_angles(cameras[i][0], limits)
            elif lead is not None:
                _, _, onset, far, sign = lead
                angles, _ = _head_angles(s, fw[far], rest)
                cap = LEAD_SHARE * limits.yaw
                k = min(1.0, cap / max(1e-9, math.hypot(*angles)))
                angles = (angles[0] * k, max(-free.down, min(free.up, angles[1] * k)))
                yaw = sign * max(sign * angles[0], min(cap, sign * origin[0] + LEAD_STEP))
                goal = (yaw, angles[1])
                goal_held = (goal, onset)
                guard_until = onset + GUARD
            else:
                offset = (0.0, 0.0)
                if reason in ("glance", "look_away"):
                    offset = (rng.uniform(*GLANCE_OFF[0]), rng.uniform(*GLANCE_OFF[1]))
                goal_point = free_point(seen, min(n - 1, i + 1), fw, rest, free, offset, camera_dirs)
                goal = _head_angles(s, goal_point, rest)[0]
            amplitude = _apart(origin, soften(goal, limits))
            if amplitude >= MIN_SACCADE and looks:          # on the first frame the eyes are already where they want
                saccade = {"frame": s.frame, "i": i, "frames": main_sequence_frames(amplitude), "reason": reason,
                           "amplitude": amplitude, "origin": origin, "to": to, "point": goal_point, "held": goal_held}
                saccades.append(saccade)
            else:
                mode, point, held, landed = to, goal_point, goal_held, i
                if held is not None and i >= held[1]:
                    point, held = _world(s, held[0], rest), None
                glance_at = rng.randint(*GLANCE)
        if saccade is not None:
            if saccade["to"] == "camera":
                goal = contact_angles(cameras[i][0], limits)
            elif saccade["held"] is not None:
                goal = saccade["held"][0]
            else:
                goal = _head_angles(s, saccade["point"], rest)[0]
            step = i - saccade["i"] + 1
            share = _profile(min(1.0, step / float(saccade["frames"])))
            o, g = saccade["origin"], soften(goal, limits)
            base = (o[0] + (g[0] - o[0]) * share, o[1] + (g[1] - o[1]) * share)
            state, reason_now = "in_saccade", saccade["reason"]
            if step >= saccade["frames"]:
                mode, point, held, landed = saccade["to"], saccade["point"], saccade["held"], i
                if held is not None and i >= held[1]:
                    point, held = _world(s, held[0], rest), None
                glance_at = rng.randint(*GLANCE)
                saccade = None
        elif mode == "camera":
            base, state = contact_angles(cameras[i][0], limits), "contact"
        elif held is not None:
            base, state = soften(held[0], limits), "lead"
        else:
            base, state = soften(_head_angles(s, point, rest)[0], limits), "free"
        if not (state == "contact" or (state == "in_saccade" and reason_now in ("contact", "look_away"))):
            base = keep_off(base, cameras[i][0], KEEP_OFF, limits)
        final = _clamp((base[0] + drift[i][0], base[1] + drift[i][1]), limits)
        looks.append(Look(s.frame, final[0] + 0.0, final[1] + 0.0, state, cameras[i][0], _apart(final, cameras[i][0]),
                          mode, base))
    out = [{"frame": c["frame"], "frames": c["frames"], "reason": c["reason"], "amplitude": c["amplitude"]} for c in saccades]
    return looks, out, contacts, leads


# ---- the measures of the analysis -----------------------------------------------------------

def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def eye_measures(angles, limits):
    """a07 / a13: the share of frames with the eyes (yaw, pitch from the rest gaze) at the edge (EDGE of a limit on
    some axis), the longest stay there in seconds, and the share 15 degrees or more off the middle"""
    edge = [max(abs(y) / limits.yaw, p / limits.up if p > 0 else -p / limits.down) >= EDGE for y, p in angles]
    longest = max([b - a + 1 for a, b in _runs(edge)] or [0])
    far = [degrees_between(direction_of(y, p), (0.0, 0.0, -1.0)) >= 15.0 for y, p in angles]
    n = float(len(angles))
    return {"edge_share": _r(sum(edge) / n), "edge_longest_s": _r(longest / FPS, 3), "eccentric_15_share": _r(sum(far) / n)}


def contact_measures(errors):
    """a13: eye contact is the gaze within CONTACT_SEEN of the camera, gaps of CONTACT_JOIN frames joined: the share of
    frames, the episodes, their median and longest length in seconds"""
    merged = []
    for a, b in _runs([e <= CONTACT_SEEN for e in errors]):
        if merged and a - merged[-1][1] - 1 <= CONTACT_JOIN:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    lengths = [(b - a + 1) / FPS for a, b in merged]
    return {"share": _r(sum(1 for e in errors if e <= CONTACT_SEEN) / float(len(errors))), "episodes": len(merged),
            "episode_median_s": _r(_median(lengths), 3), "longest_s": _r(max(lengths or [0.0]), 3)}


def _unwrap(values):
    out, last = [], None
    for v in values:
        if last is not None:
            v = last + (v - last + 180.0) % 360.0 - 180.0
        out.append(v)
        last = v
    return out


def lead_measure(head_yaw, gaze_yaw, margins=LEAD_MARGINS):
    """a20: the fast turns of the head (its yaw rate above LEAD_TURN deg/s for LEAD_MIN_FRAMES frames or more, outside
    the margins at the start and the end) and those the eyes lead: the eye in the head (gaze yaw minus head yaw)
    moves more than LEAD_SEEN degrees the way of the turn in the 6 frames before its onset (the first of the 15
    frames before at 30 % of the peak).  Yaws in degrees, in the world."""
    yh, yg = _unwrap(head_yaw), _unwrap(gaze_yaw)
    n = len(yh)
    rate = [0.0] + [(yh[i] - yh[i - 1]) * FPS for i in range(1, n)]
    turns = led = 0
    for a, b in _runs([abs(v) > LEAD_TURN for v in rate]):
        if b - a + 1 < LEAD_MIN_FRAMES or a < margins[0] or b > n - 1 - margins[1] or a < 15:
            continue
        sign = 1.0 if sum(rate[a:b + 1]) / (b - a + 1) > 0 else -1.0
        window = [sign * rate[i] for i in range(a - 15, b + 1)]
        peak = max(window)
        onset = a - 15 + next(k for k, v in enumerate(window) if v > 0.3 * peak)
        turns += 1
        if sign * ((yg[onset] - yh[onset]) - (yg[onset - 6] - yh[onset - 6])) > LEAD_SEEN:
            led += 1
    return {"turns": turns, "led": led, "share": _r(led / float(turns), 3) if turns else 0.0}


def carried_measure(gazes, saccades):
    """a07: the large changes of the gaze in the world (more than LARGE_CHANGE degrees within LARGE_WINDOW frames, one
    per run, at its largest window) and how many the head carried: less than half of the window's path inside the
    listed saccades (a frame's step counts when the saccade covers either end).  `gazes` are world directions"""
    n = len(gazes)
    moving = [False] * n
    for s in saccades:
        for i in range(s["frame"], min(n, s["frame"] + s["frames"])):
            moving[i] = True
    steps = [degrees_between(gazes[i], gazes[i + 1]) for i in range(n - 1)]
    w = LARGE_WINDOW
    change = [degrees_between(gazes[i], gazes[i + w]) for i in range(n - w)]
    events = carried = 0
    for a, b in _runs([c > LARGE_CHANGE for c in change]):
        k = max(range(a, b + 1), key=lambda i: (change[i], -i))
        frames = range(k, k + w)
        path = sum(steps[f] for f in frames)
        by_saccade = sum(steps[f] for f in frames if moving[f] or moving[f + 1])
        events += 1
        carried += by_saccade < 0.5 * path
    return {"events": events, "saccade_made": events - carried, "head_carried": carried,
            "share": _r(carried / float(events), 3) if events else 0.0}


def plan_measures(seen, looks, saccades, forward, limits):
    """the measures of the analysis computed on the plan (the world gaze from the head's rotation and the eye angles)"""
    rest = angles_of(forward)
    gazes = [_world(s, (look.yaw, look.pitch), rest) for s, look in zip(seen, looks)]
    yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
    out = eye_measures([(look.yaw, look.pitch) for look in looks], limits)
    out["contact"] = contact_measures([look.error for look in looks])
    margins = LEAD_MARGINS if len(seen) > 2 * sum(LEAD_MARGINS) else (15, 0)
    out["lead"] = lead_measure([yaw(fk.rotate(s.head, forward)) for s in seen], [yaw(g) for g in gazes], margins)
    out["head_carried"] = carried_measure(gazes, saccades)
    out["saccades_per_second"] = _r(len(saccades) / (len(seen) / FPS), 3)
    return out


# ---- the song -------------------------------------------------------------------------------

def song_anchors(cues=None, chorus=(), fps=FPS):
    """the frames of the song's anchors: the ends of the lyric lines and the starts of the hooks of a cues file (the
    JSON of tools/mv_text.py: "cues" with "start", "end" in seconds and "style" "lyric" or "hook") and the heads of
    the choruses (seconds)"""
    out = set()
    for cue in (cues or {}).get("cues", []):
        if cue.get("style") == "lyric":
            out.add(int(round(float(cue["end"]) * fps)))
        elif cue.get("style") == "hook":
            out.add(int(round(float(cue["start"]) * fps)))
    for seconds in chorus:
        out.add(int(round(float(seconds) * fps)))
    return sorted(out)


# ---- the motion and the report --------------------------------------------------------------

def eye_motion(looks, model_name):
    """the 両目 track: a key on the first and the last frame and wherever the angles change, linear curves"""
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    values = [(round(look.yaw, 6), round(look.pitch, 6)) for look in looks]
    keys = []
    for i, look in enumerate(looks):
        if 0 < i < len(looks) - 1 and values[i - 1] == values[i] == values[i + 1]:
            continue
        keys.append(vmd.BoneKey(EYES, look.frame, fk.ZERO, fk.stored(eye_rotation(look.yaw, look.pitch)), straight))
    return vmd.Motion(model_name=model_name, bones=keys)


def probe_motion(model_name):
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    keys = []
    for start, end, ui in PROBE:
        for frame in sorted({start, end}):
            keys.append(vmd.BoneKey(EYES, frame, fk.ZERO, mathutil.ui_to_quat(*ui), straight))
    return vmd.Motion(model_name=model_name, bones=keys)


def describe(yaw, pitch):
    """which way a gaze of (yaw, pitch) from the rest looks, in words"""
    parts = []
    if yaw > 0.5:
        parts.append("to her left (+X), the viewer's right with the camera in front")
    elif yaw < -0.5:
        parts.append("to her right (-X), the viewer's left with the camera in front")
    if pitch > 0.5:
        parts.append("up")
    elif pitch < -0.5:
        parts.append("down")
    return " and ".join(parts) if parts else "straight ahead"


def probe_segments(forward):
    """each piece of the probe with the way the eyes should look under the convention of mmd_cli/fk.py"""
    rest = angles_of(forward)
    out = []
    for start, end, ui in PROBE:
        yaw, pitch = angles_of(fk.rotate(fk.applied(mathutil.ui_to_quat(*ui)), forward))
        yaw, pitch = yaw - rest[0], pitch - rest[1]
        out.append({"frames": [start, end], "window": list(ui), "gaze": [_r(yaw, 3), _r(pitch, 3)], "looks": describe(yaw, pitch)})
    return out


def _count(items):
    out = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def dance_eye_keys(dance):
    """the keys the dance itself has on the eye bones, with the largest turn among them"""
    out = {}
    for name in (EYES,) + EYE_PAIR:
        keys = [k for k in dance.bones if k.name == name]
        out[name] = {"keys": len(keys),
                     "max_degrees": _r(max([math.degrees(2.0 * math.acos(min(1.0, abs(fk.normalized(k.rotation)[3]))))
                                            for k in keys] or [0.0]), 3)}
    return out


def _error_summary(values):
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {"mean": _r(sum(values) / len(values), 3), "p95": _r(ordered[int(round(0.95 * (len(ordered) - 1)))], 3),
            "max": _r(ordered[-1], 3)}


@dataclass
class Gaze:
    looks: List[Look]
    saccades: List[dict]
    cuts: List[int]
    motion: vmd.Motion
    report: dict
    sights: List[Sight]
    forward: Tuple[float, float, float]
    contacts: List[Tuple[int, int]]


def gaze(model, dance, camera, max_yaw=MAX_YAW, max_up=MAX_UP, max_down=MAX_DOWN, seed=0, life=True, anchors=()):
    """the 両目 motion for `dance` seen by `camera` on `model`, with the per-frame plan and the report; `anchors` are
    frames of the song (song_anchors)"""
    limits = Limits(float(max_yaw), float(max_up), float(max_down))
    check_limits(limits)
    if not dance.bones:
        raise ValueError("the dance has no bone keys")
    eyes, center, parent = eye_bones(model)
    forward, forward_from = rest_forward(model, eyes)
    seen = sights(model, dance, camera)
    first = seen[0].frame
    marks = sorted({a - first for a in anchors if 0 <= a - first < len(seen)})
    looks, saccades, contacts, leads = plan(seen, forward, limits, seed, life, marks)
    cuts = [s.frame for s in seen if s.cut]
    counts = {state: 0 for state in STATES}
    for look in looks:
        counts[look.state] += 1
    amplitudes = [s["amplitude"] for s in saccades]
    contact_frames = sum(b - a + 1 for a, b in contacts)

    def anchor_of(a, b):
        near = [m for m in marks if a - ANCHOR_NEAR <= m <= b + ANCHOR_NEAR]
        return near[0] + first if near else None
    report = {
        "frames": [seen[0].frame, seen[-1].frame], "seed": seed,
        "limits": dict(limits.to_json(), soft_from=SOFT_FROM),
        "zones": {"free": free_zone(limits).to_json(), "contact": contact_zone(limits).to_json(),
                  "contact_error": CONTACT_ERROR},
        "eye": {"bone": EYES, "center": center, "head": parent, "forward": _vec(forward, 6), "forward_from": forward_from},
        "convention": {"key_rotation_signs": list(fk.KEY_ROTATION_SIGNS)},
        "counts": counts, "shares": {state: counts[state] / float(len(looks)) for state in STATES},
        "saccades": {"count": len(saccades), "per_second": _r(len(saccades) / (len(seen) / FPS), 3),
                     "by_reason": _count(s["reason"] for s in saccades),
                     "by_frames": {str(k): v for k, v in sorted(_count(s["frames"] for s in saccades).items())},
                     "amplitude": {"median": _r(_median(amplitudes), 3) if amplitudes else 0.0,
                                   "max": _r(max(amplitudes), 3) if amplitudes else 0.0},
                     "list": [{"frame": s["frame"], "frames": s["frames"], "reason": s["reason"],
                               "amplitude": _r(s["amplitude"], 3)} for s in saccades]},
        "contacts": {"count": len(contacts), "frames": contact_frames, "share": _r(contact_frames / float(len(seen))),
                     "list": [{"first": a + first, "last": b + first, "seconds": _r((b - a + 1) / FPS, 3),
                               "anchor": anchor_of(a, b)} for a, b in contacts]},
        "anchors": [m + first for m in marks],
        "leads": {"fast_turns": len(fast_turns(seen, forward)[1]), "planned": len(leads),
                  "made": sum(1 for s in saccades if s["reason"] == "lead")},
        "cuts": cuts,
        "error_on_camera": _error_summary([look.error for look in looks if look.state == "contact"]),
        "measures": plan_measures(seen, looks, saccades, forward, limits),
        "dance_eye_keys": dance_eye_keys(dance),
    }
    return Gaze(looks, saccades, cuts, eye_motion(looks, dance.model_name), report, seen, forward, contacts)


def debug_rows(result, frames):
    """the --debug rows for the frames asked for (those inside the dance)"""
    first = result.sights[0].frame
    rows = []
    for frame in sorted(set(frames)):
        i = frame - first
        if not 0 <= i < len(result.looks):
            continue
        sight, look = result.sights[i], result.looks[i]
        stored = fk.stored(eye_rotation(look.yaw, look.pitch))
        rows.append({"frame": frame, "camera": _vec(sight.camera), "eye_center": _vec(sight.eye),
                     "head_forward": _vec(fk.rotate(sight.head, result.forward)),
                     "to_camera": {"yaw": _r(look.target[0], 3), "pitch": _r(look.target[1], 3)},
                     "eye": {"yaw": _r(look.yaw, 3), "pitch": _r(look.pitch, 3)},
                     "window": _vec(mathutil.quat_to_ui(stored), 3), "state": look.state, "error": _r(look.error, 3)})
    return rows


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


def write_json(path, data, indent=1):
    write_bytes(path, (json.dumps(data, ensure_ascii=True, indent=indent) + "\n").encode("ascii"))


def check_distinct(*paths):
    """the inputs and the files written must all differ: no input is ever written over"""
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, CAMERA, MODEL, OUT, --report, --debug, --probe and "
                             "--cues must all differ" % (seen[key], path))
        seen[key] = path


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def load_cues(path):
    """the cues JSON (a dict with "cues"); ValueError when it is not one"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("cues"), list):
        raise ValueError("%s holds no \"cues\" list" % path)
    return data


def resolve_limits(max_yaw=None, max_up=None, max_down=None, max_pitch=None):
    """the limits from the options: --max-pitch sets up and down together and goes with neither of them"""
    if max_pitch is not None:
        if max_up is not None or max_down is not None:
            raise ValueError("--max-pitch sets both --max-up and --max-down: give it or them, not both")
        max_up = max_down = max_pitch
    limits = Limits(MAX_YAW if max_yaw is None else float(max_yaw), MAX_UP if max_up is None else float(max_up),
                    MAX_DOWN if max_down is None else float(max_down))
    check_limits(limits)
    return limits


def run(dance_path, camera_path, model_path, out_path, report_path=None, debug_path=None, debug_frames=None,
        probe_path=None, limits=Limits(), seed=0, cues_path=None, chorus=()):
    """read, plan, write; the summary is what main prints"""
    started = time.time()
    check_limits(limits)
    check_distinct(dance_path, camera_path, model_path, out_path, report_path, debug_path, probe_path, cues_path)
    dance_full, camera_full, model_full, out_full = (os.path.abspath(p) for p in (dance_path, camera_path, model_path, out_path))
    cues = load_cues(os.path.abspath(cues_path)) if cues_path else None
    dance = vmd.load(dance_full)
    camera = vmd.load(camera_full)
    model = load_model(model_full)
    result = gaze(model, dance, camera, limits.yaw, limits.up, limits.down, seed, anchors=song_anchors(cues, chorus))
    report = result.report
    rows = None
    if debug_path:
        last = report["frames"][1]
        rows = debug_rows(result, debug_frames if debug_frames else range(report["frames"][0], last + 1, DEBUG_STEP))
    write_bytes(out_full, vmd.dumps(result.motion))
    back = vmd.load(out_full)
    summary = {"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full, "frames": report["frames"],
               "keys": len(back.bones), "seed": seed, "limits": report["limits"], "zones": report["zones"],
               "eye": report["eye"], "convention": report["convention"], "cuts": len(report["cuts"]),
               "anchors": len(report["anchors"]), "counts": report["counts"],
               "shares": {k: _r(v) for k, v in report["shares"].items()},
               "saccades": {k: report["saccades"][k] for k in ("count", "per_second", "by_reason", "by_frames", "amplitude")},
               "contacts": {k: report["contacts"][k] for k in ("count", "frames", "share")},
               "leads": report["leads"], "measures": report["measures"], "error_on_camera": report["error_on_camera"]}
    if cues_path:
        summary["cues"] = os.path.abspath(cues_path)
    if report_path:
        full = os.path.abspath(report_path)
        extra = {"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full, "keys": len(back.bones),
                 "cues": os.path.abspath(cues_path) if cues_path else None, "chorus": [float(c) for c in chorus]}
        write_json(full, dict(extra, **report))
        summary["report"] = full
    if debug_path:
        full = os.path.abspath(debug_path)
        write_json(full, {"in": dance_full, "camera": camera_full, "forward": report["eye"]["forward"], "frames": rows})
        summary["debug"] = full
    if probe_path:
        full = os.path.abspath(probe_path)
        write_bytes(full, vmd.dumps(probe_motion(dance.model_name)))
        summary["probe"] = {"out": full, "segments": probe_segments(result.forward)}
    summary["seconds"] = _r(time.time() - started, 2)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("camera", help="the camera motion (.vmd)")
    p.add_argument("model", help="the model (.pmx or .pmd) with the bones 両目, 右目, 左目")
    p.add_argument("out", help="the 両目 motion to write (.vmd), to load after the dance")
    p.add_argument("--report", help="write the plan, the saccades, the contacts and the measures to this JSON")
    p.add_argument("--debug", help="write the geometry of some frames to this JSON")
    p.add_argument("--debug-frames", type=int, nargs="+", help="the frames for --debug (default every %d)" % DEBUG_STEP)
    p.add_argument("--probe", help="also write the convention probe (a short 両目 motion) to this .vmd")
    p.add_argument("--max-yaw", type=float, help="degrees the eyes turn sideways (default %g)" % MAX_YAW)
    p.add_argument("--max-up", type=float, help="degrees the eyes turn up (default %g)" % MAX_UP)
    p.add_argument("--max-down", type=float, help="degrees the eyes turn down (default %g)" % MAX_DOWN)
    p.add_argument("--max-pitch", type=float, help="sets --max-up and --max-down to one value (not with either of them)")
    p.add_argument("--seed", type=int, default=0, help="the drift, the microsaccades, the glances, the leads (default 0)")
    p.add_argument("--cues", help="the MV's cues JSON: the ends of the lyric lines and the hooks are anchors for contacts")
    p.add_argument("--chorus", type=float, nargs="+", default=[], help="the heads of the choruses in seconds (anchors)")
    args = p.parse_args(argv)
    try:
        limits = resolve_limits(args.max_yaw, args.max_up, args.max_down, args.max_pitch)
        result = run(args.dance, args.camera, args.model, args.out, args.report, args.debug, args.debug_frames,
                     args.probe, limits, args.seed, args.cues, args.chorus)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
