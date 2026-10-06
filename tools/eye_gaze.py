"""Give a dancer a natural gaze toward the camera (eye contact with the viewer): fixations that stay on the camera
while her head moves, and quick saccades, written as a 両目 track to load after the dance.

    python tools/eye_gaze.py DANCE.vmd CAMERA.vmd MODEL.pmx OUT.vmd [--report r.json] [--debug d.json]
                             [--debug-frames F ...] [--probe P.vmd] [--max-yaw 18] [--max-up 6] [--max-down 10]
                             [--max-pitch P (sets up and down to P)] [--seed 0]

Why: the dance of the MV keys 両目, 右目 and 左目 once each, on frame 0, for the whole 258 seconds: her eyes never
move.  On Sour's Rin 両目 turns both eyes (右目 and 左目 take its rotation by append, ratio 1), so one track does it.

Where the camera is, seen from her eyes (sights; mmd_cli/fk.py does the forward kinematics):

* The eye center is the midpoint of 右目 and 左目 in the world.  両目 itself is a handle above the head on Sour's
  Rin (height 19.37 against eyes at 17.21: aiming from it would tilt the gaze by 3.5 degrees at 35 units); its
  position is used only when the model lacks 右目 or 左目.
* The head frame is the world rotation of 両目's parent (頭).  The camera is fk.camera_position of the camera motion.
* The direction to the camera in the head frame, v = H^-1 (C - E), is read as yaw (positive toward the model's
  left, +X) and pitch (positive up), each relative to the eyes' rest gaze: the direction from 両目 to 両目先 (or to
  its tail) when it lies within FORWARD_TOLERANCE of -Z (on Sour's Rin it is exactly -Z), else -Z.

How the eyes move (plan: a small state machine, frame by frame):

* The eyes are either on the camera or neutral (along the head's forward direction).  The limits are --max-yaw to
  either side, --max-up and --max-down (6 up and 10 down by default: at +10 degrees the upper lid of Sour's Rin
  covers 17 % more of the iris, review 8; --max-pitch sets both to one value).  The camera is reachable when it is
  less than 90 degrees off the rest gaze and lies beyond the limits by at most GIVE_UP degrees.  A camera beyond a
  limit but reachable holds the eyes at that limit (each axis on its own).  The last part of each range is soft
  (soft(), review 8 R2): up to SOFT_FROM of a limit the eyes follow exactly, beyond it they approach the limit along
  tanh, so they slow down before it instead of stopping dead in the corner when the head swings; a camera exactly
  at the limit is looked at with 90.5 % of it.  The report says how far from the camera this leaves the eyes
  (soft_limit; those frames are in error_on_camera too).  Once it has been out of reach (beyond that, or behind her) for PATIENCE frames in a row,
  the eyes return to neutral instead of pinning at the limit; a shorter excursion, a nod with the beat, only holds
  the limit.  Neutral eyes come back once the camera is within COME_BACK degrees of the limits (a hysteresis, so
  that they do not flicker at the border).  On the MV's dance the camera is beyond the default limits on about 40 %
  of the frames in yaw and as many in pitch, mostly for a fraction of a second at a time, which without the
  patience made the eyes flip between the camera and neutral about once a second.
* Fixation: when a saccade lands on the camera, the eyes hold the camera's world position of that frame, and as
  the head moves they counter-rotate to keep pointing at it (like the vestibulo-ocular reflex).  The held point's
  yaw is followed through +-180 degrees, so when she spins and it passes behind her, eyes pinned at one limit stay
  there instead of jumping to the other (only a saccade takes them across).  When the camera
  has moved away from that point by more than SACCADE_THRESHOLD degrees (both after the clamp), or the camera cuts,
  or the camera becomes unreachable (or reachable again), a saccade follows after a reaction time of REACTION
  frames (drawn from the seed: 100 to 167 ms), but never sooner than MIN_FIXATION frames (200 ms) after the last
  one landed, the shortest fixation of a person looking around.  The cause is read again on every frame while the
  saccade waits: when it is gone (the camera came back within reach, the error fell back), the saccade does not
  happen; a cut stays a cause until its saccade.
* A saccade takes 2 frames, 3 when longer than LONG_SACCADE degrees (the main sequence, about 21 ms + 2.2 ms per
  degree, gives 43 ms for 10 degrees and 87 ms for 30), along a minimum-jerk profile.  Where it goes, the camera or
  neutral, is fixed when it starts (a change of mind waits for the next saccade); the camera's place is read again
  on every frame of it, clamped to the limits, so it lands exactly on the camera as it is then.
* Life: a slow drift (a random walk of up to DRIFT_STEP per frame and axis, kept within DRIFT_LIMIT) and a
  microsaccade every MICRO_INTERVAL frames that jumps back to within MICRO_SIZE of the center are added on top; well
  under a degree, and only from the seed (random.Random(seed).random()), so the same seed gives the same file.  The
  final angles are clamped to the limits again.
* A camera cut is a frame on which the camera moves more than CUT_JUMP units or turns its line of sight more than
  CUT_TURN degrees from the frame before (every cut of tools/make_camera.py moves it by 3 units or more).

What is written: a VMD that holds only the 両目 track, a key on every frame where the angles change (and the first
and last frame) with the linear curve, under the dance's model name.  Load it after the dance: it replaces the
dance's single 両目 key.  The rotation is made with mmd_cli.fk.stored, so it follows the one convention of
mmd_cli/fk.py (KEY_ROTATION_SIGNS).  Keys the dance has on 右目 or 左目 would add to it (the report lists them; the
MV's dance holds one zero key each).

The report (--report, and in short on stdout): the shares of frames on the camera (within SACCADE_THRESHOLD of it
and inside the limits), at a limit, neutral, in a saccade, and reacting (waiting out the reaction time after a cut
or a move, more than SACCADE_THRESHOLD off): they add up to 1.  The saccades with their causes and amplitudes, the
cuts.  --debug writes, for --debug-frames (default: every DEBUG_STEP-th frame), the camera's and the eye center's
world position, the head's forward direction, where the camera is (yaw, pitch), the eye's yaw and pitch and the
window angles written, the state and the remaining error.

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
MAX_YAW = 18.0                        # degrees the eyes turn sideways (default of --max-yaw)
MAX_UP, MAX_DOWN = 6.0, 10.0          # degrees they turn up and down (--max-up, --max-down; review 8, R1: at +10 the
                                      # upper lid of Sour's Rin covers 17 % more of the iris)
LIMIT_MAX = 45.0                      # degrees: the most a limit may be
SOFT_FROM = 0.6                       # share of a limit up to which the eyes follow exactly; beyond, tanh towards it
GIVE_UP = 12.0                        # degrees beyond a limit at which the eyes stop trying and go neutral
PATIENCE = 10                         # frames the camera must stay beyond GIVE_UP (or behind) before they do
COME_BACK = 8.0                       # degrees beyond the limits within which neutral eyes go back to the camera
SACCADE_THRESHOLD = 4.0               # degrees between where the eyes hold and the camera that start a saccade
LONG_SACCADE = 20.0                   # degrees: a longer saccade takes 3 frames instead of 2
REACTION = (3, 5)                     # frames from the cause to the start of the saccade (both included)
MIN_FIXATION = 6                      # frames from the landing of a saccade to the earliest start of the next
CUT_JUMP = 1.0                        # model units the camera moves in one frame on a cut
CUT_TURN = 5.0                        # degrees the camera's line of sight turns in one frame on a cut
DRIFT_STEP = 0.03                     # degrees per frame and axis, at most, of the fixation drift
DRIFT_LIMIT = 0.3                     # degrees: the drift stays within this on each axis
MICRO_INTERVAL = (15, 45)             # frames between microsaccades
MICRO_SIZE = 0.15                     # degrees: a microsaccade lands within this of the center
FORWARD_TOLERANCE = 20.0              # degrees off -Z within which 両目 -> 両目先 is taken as the rest gaze
DEBUG_STEP = 30
STATES = ("on_camera", "at_limit", "neutral", "in_saccade", "reacting")
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
        sight_line = tuple(a - b for a, b in zip(state.look_at, position))
        cut = previous is not None and (math.sqrt(sum((a - b) ** 2 for a, b in zip(position, previous[0]))) > CUT_JUMP
                                        or degrees_between(sight_line, previous[1]) > CUT_TURN)
        previous = (position, sight_line)
        out.append(Sight(frame, eye, head, position, cut))
    return out


def _seen(sight, point, forward, rest):
    """((yaw, pitch) of a world point seen from the eyes in the head's frame, relative to the rest gaze; whether it is
    behind, more than 90 degrees off the rest gaze)"""
    v = fk.rotate(fk.conjugate(sight.head), tuple(p - e for p, e in zip(point, sight.eye)))
    yaw, pitch = angles_of(v)
    yaw = (yaw - rest[0] + 180.0) % 360.0 - 180.0
    return (yaw, pitch - rest[1]), sum(a * b for a, b in zip(v, forward)) <= 0.0


# ---- how the eyes move ----------------------------------------------------------------------

@dataclass
class Look:
    frame: int
    yaw: float                      # the eye angles written, degrees from the rest gaze (+ to her left, + up)
    pitch: float
    state: str                      # one of STATES
    target: Tuple[float, float]     # where the camera is (yaw, pitch), not clamped
    error: float                    # degrees between the gaze written and the camera


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


def _clamp(angles, limits):
    return (min(max(angles[0], -limits.yaw), limits.yaw), min(max(angles[1], -limits.down), limits.up))


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


def _in_soft_part(angles, limits):
    yaw, pitch = angles
    return (abs(yaw) > SOFT_FROM * limits.yaw or pitch > SOFT_FROM * limits.up
            or -pitch > SOFT_FROM * limits.down)


def _excess(target, limits):
    """degrees by which a direction (yaw, pitch) lies beyond the limits (0 inside them)"""
    yaw, pitch = target
    return max(abs(yaw) - limits.yaw, pitch - limits.up, -pitch - limits.down, 0.0)


def _profile(t):
    """minimum jerk: the share of a saccade done at the time t in 0..1"""
    return t * t * t * (10.0 + t * (6.0 * t - 15.0))


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


def plan(seen, forward, limits=Limits(), seed=0, life=True):
    """(a Look per sight, the saccades): see the module docstring"""
    check_limits(limits)
    rest = angles_of(forward)
    drift = drift_track(len(seen), random.Random(2 * seed)) if life else [(0.0, 0.0)] * len(seen)
    reaction = random.Random(2 * seed + 1)
    looks, saccades = [], []
    mode, fixation, base, pending, saccade = None, None, (0.0, 0.0), None, None
    away, landed = 0, None          # frames in a row the camera has been out of reach; the frame of the last landing
    held_yaw = None                 # the held point's yaw on the frame before, followed through +-180 (not wrapped)
    for i, sight in enumerate(seen):
        target, behind = _seen(sight, sight.camera, forward, rest)
        excess = _excess(target, limits)
        if mode == "neutral":
            away = 0
            want = "camera" if not behind and excess <= COME_BACK else "neutral"
        else:
            away = 0 if not behind and excess <= GIVE_UP else away + 1
            want = "neutral" if away >= (1 if mode is None else PATIENCE) else "camera"
        on_camera = soften(target, limits)
        if mode is None:                                    # the first frame: the eyes are already where they want
            mode, landed = want, sight.frame
            base = on_camera if want == "camera" else (0.0, 0.0)
            fixation = sight.camera if want == "camera" else None
            held_yaw = target[0]
        elif saccade is None:
            if mode == "camera":
                # the held point's yaw is followed continuously: when she spins and it passes behind her, eyes pinned
                # at one limit stay there instead of jumping to the other (only a saccade moves them across)
                (yaw, pitch), _ = _seen(sight, fixation, forward, rest)
                held_yaw += (yaw - held_yaw + 180.0) % 360.0 - 180.0
                base = soften((held_yaw, pitch), limits)
            else:
                base = (0.0, 0.0)
            # the cause is read on every frame: a pending saccade whose cause is gone does not happen (a cut stays a
            # cause until its saccade)
            cause = None
            if want != mode:
                cause = "to_" + want
            elif mode == "camera" and (sight.cut or (pending is not None and pending[1] == "cut")):
                cause = "cut"
            elif mode == "camera" and _apart(base, on_camera) > SACCADE_THRESHOLD:
                cause = "refixation"
            if cause is None:
                pending = None
            elif pending is None:
                delay = REACTION[0] + int(reaction.random() * (REACTION[1] - REACTION[0] + 1))
                pending = (sight.frame + delay, cause)
            else:
                pending = (pending[0], cause)
            if pending is not None and sight.frame >= max(pending[0], landed + MIN_FIXATION):
                # where it goes is fixed now (the camera or neutral); the camera's place is read on every frame of it
                to = "neutral" if pending[1] == "to_neutral" else "camera"
                amplitude = _apart(base, on_camera if to == "camera" else (0.0, 0.0))
                saccade = {"frame": sight.frame, "frames": 2 if amplitude <= LONG_SACCADE else 3, "reason": pending[1],
                           "amplitude": amplitude, "origin": base, "to": to}
                saccades.append(saccade)
                pending = None
        moving = saccade is not None
        if moving:
            goal = on_camera if saccade["to"] == "camera" else (0.0, 0.0)
            step = sight.frame - saccade["frame"] + 1
            share = _profile(min(1.0, step / float(saccade["frames"])))
            origin = saccade["origin"]
            base = (origin[0] + (goal[0] - origin[0]) * share, origin[1] + (goal[1] - origin[1]) * share)
            if step >= saccade["frames"]:
                mode, landed = saccade["to"], sight.frame
                fixation = sight.camera if mode == "camera" else None
                held_yaw = target[0]
                saccade = None
        final = _clamp((base[0] + drift[i][0], base[1] + drift[i][1]), limits)
        if moving:
            state = "in_saccade"
        elif mode == "neutral":
            state = "neutral"
        elif excess > 0.0:
            state = "at_limit"
        elif _apart(base, target) <= SACCADE_THRESHOLD:
            state = "on_camera"
        else:
            state = "reacting"
        looks.append(Look(sight.frame, final[0] + 0.0, final[1] + 0.0, state, target, _apart(final, target)))
    return looks, [{"frame": s["frame"], "frames": s["frames"], "reason": s["reason"], "amplitude": s["amplitude"]}
                   for s in saccades]


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


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def dance_eye_keys(dance):
    """the keys the dance itself has on the eye bones, with the largest turn among them"""
    out = {}
    for name in (EYES,) + EYE_PAIR:
        keys = [k for k in dance.bones if k.name == name]
        out[name] = {"keys": len(keys),
                     "max_degrees": _r(max([math.degrees(2.0 * math.acos(min(1.0, abs(fk.normalized(k.rotation)[3]))))
                                            for k in keys] or [0.0]), 3)}
    return out


@dataclass
class Gaze:
    looks: List[Look]
    saccades: List[dict]
    cuts: List[int]
    motion: vmd.Motion
    report: dict
    sights: List[Sight]
    forward: Tuple[float, float, float]


def gaze(model, dance, camera, max_yaw=MAX_YAW, max_up=MAX_UP, max_down=MAX_DOWN, seed=0, life=True):
    """the 両目 motion for `dance` seen by `camera` on `model`, with the per-frame plan and the report"""
    limits = Limits(float(max_yaw), float(max_up), float(max_down))
    check_limits(limits)
    if not dance.bones:
        raise ValueError("the dance has no bone keys")
    eyes, center, parent = eye_bones(model)
    forward, forward_from = rest_forward(model, eyes)
    seen = sights(model, dance, camera)
    looks, saccades = plan(seen, forward, limits, seed, life)
    cuts = [s.frame for s in seen if s.cut]
    counts = {state: 0 for state in STATES}
    for look in looks:
        counts[look.state] += 1
    amplitudes = [s["amplitude"] for s in saccades]
    report = {
        "frames": [seen[0].frame, seen[-1].frame], "seed": seed,
        "limits": dict(limits.to_json(), soft_from=SOFT_FROM, give_up=GIVE_UP, come_back=COME_BACK),
        "eye": {"bone": EYES, "center": center, "head": parent, "forward": _vec(forward, 6), "forward_from": forward_from},
        "convention": {"key_rotation_signs": list(fk.KEY_ROTATION_SIGNS)},
        "counts": counts, "shares": {state: counts[state] / float(len(looks)) for state in STATES},
        "saccades": {"count": len(saccades), "by_reason": _count(s["reason"] for s in saccades),
                     "by_frames": {str(k): v for k, v in sorted(_count(s["frames"] for s in saccades).items())},
                     "amplitude": {"median": _r(_median(amplitudes), 3) if amplitudes else 0.0,
                                   "max": _r(max(amplitudes), 3) if amplitudes else 0.0},
                     "list": [{"frame": s["frame"], "frames": s["frames"], "reason": s["reason"],
                               "amplitude": _r(s["amplitude"], 3)} for s in saccades]},
        "cuts": cuts,
        "error_on_camera": _error_summary([look.error for look in looks if look.state == "on_camera"]),
        # how far from the camera the eyes are while the soft limit holds them short of it (the camera inside the
        # limits but past SOFT_FROM of one): these frames are part of error_on_camera too
        "soft_limit": {"from": SOFT_FROM,
                       "frames": sum(1 for look in looks if look.state == "on_camera" and _in_soft_part(look.target, limits)),
                       "error": _error_summary([look.error for look in looks
                                                if look.state == "on_camera" and _in_soft_part(look.target, limits)])},
        "dance_eye_keys": dance_eye_keys(dance),
    }
    return Gaze(looks, saccades, cuts, eye_motion(looks, dance.model_name), report, seen, forward)


def _error_summary(values):
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {"mean": _r(sum(values) / len(values), 3), "p95": _r(ordered[int(round(0.95 * (len(ordered) - 1)))], 3),
            "max": _r(ordered[-1], 3)}


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
            raise ValueError("%s and %s are the same file: DANCE, CAMERA, MODEL, OUT, --report, --debug and --probe "
                             "must all differ" % (seen[key], path))
        seen[key] = path


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


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
        probe_path=None, limits=Limits(), seed=0):
    """read, plan, write; the summary is what main prints"""
    started = time.time()
    check_limits(limits)
    check_distinct(dance_path, camera_path, model_path, out_path, report_path, debug_path, probe_path)
    dance_full, camera_full, model_full, out_full = (os.path.abspath(p) for p in (dance_path, camera_path, model_path, out_path))
    dance = vmd.load(dance_full)
    camera = vmd.load(camera_full)
    model = load_model(model_full)
    result = gaze(model, dance, camera, limits.yaw, limits.up, limits.down, seed)
    report = result.report
    rows = None
    if debug_path:
        last = report["frames"][1]
        rows = debug_rows(result, debug_frames if debug_frames else range(report["frames"][0], last + 1, DEBUG_STEP))
    write_bytes(out_full, vmd.dumps(result.motion))
    back = vmd.load(out_full)
    summary = {"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full, "frames": report["frames"],
               "keys": len(back.bones), "seed": seed, "limits": report["limits"],
               "eye": report["eye"], "convention": report["convention"], "cuts": len(report["cuts"]),
               "counts": report["counts"], "shares": {k: _r(v) for k, v in report["shares"].items()},
               "saccades": {k: report["saccades"][k] for k in ("count", "by_reason", "by_frames", "amplitude")},
               "error_on_camera": report["error_on_camera"], "soft_limit": report["soft_limit"]}
    if report_path:
        full = os.path.abspath(report_path)
        write_json(full, dict({"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full,
                               "keys": len(back.bones)}, **report))
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
    p.add_argument("--report", help="write the shares, the saccades and the cuts to this JSON")
    p.add_argument("--debug", help="write the geometry of some frames to this JSON")
    p.add_argument("--debug-frames", type=int, nargs="+", help="the frames for --debug (default every %d)" % DEBUG_STEP)
    p.add_argument("--probe", help="also write the convention probe (a short 両目 motion) to this .vmd")
    p.add_argument("--max-yaw", type=float, help="degrees the eyes turn sideways (default %g)" % MAX_YAW)
    p.add_argument("--max-up", type=float, help="degrees the eyes turn up (default %g)" % MAX_UP)
    p.add_argument("--max-down", type=float, help="degrees the eyes turn down (default %g)" % MAX_DOWN)
    p.add_argument("--max-pitch", type=float, help="sets --max-up and --max-down to one value (not with either of them)")
    p.add_argument("--seed", type=int, default=0, help="the drift, the microsaccades and the reaction times (default 0)")
    args = p.parse_args(argv)
    try:
        limits = resolve_limits(args.max_yaw, args.max_up, args.max_down, args.max_pitch)
        result = run(args.dance, args.camera, args.model, args.out, args.report, args.debug, args.debug_frames,
                     args.probe, limits, args.seed)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
