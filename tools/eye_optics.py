"""Move the lights in the eyes, the pupils and the eyes' vergence as a person's do, written as one VMD to load after the
dance, the face and the gaze.

    python tools/eye_optics.py MODEL.pmx DANCE.vmd GAZE.vmd CAMERA.vmd OUT.vmd [--face FACE.vmd] [--look LOOK.json]
                               [--flares S ...] [--audio SONG] [--chorus S ...] [--params P.json] [--report r.json]
                               [--seed 0] [--trace t.json]

MODEL is the model made by tools/pmx_eyes.py (its catchlight bones); GAZE the 両目 track of tools/eye_gaze.py, merged
over the dance as MMD merges a later motion (its keys replace the dance's on the same bone and frame).  Every frame of
the dance is computed.  The numbers are PARAMS, each replaceable with --params (a JSON of the same shape; an unknown
key is refused); they are those of stage 5's research (`_spike/out/stage5/research/RESEARCH.md`, cited by section).

The light (the catchlight bones; RESEARCH 1.4, formula A):

* A light is the mirror image of a light source in the cornea.  Seen by the camera, its centre lies off the pupil's
  centre by  R proj(H) - K proj(g)  (R = 7.72 mm the cornea's radius, K = 4.67 mm from the entrance pupil back to the
  cornea's centre of curvature, H the half-way direction between the way to the light and the way to the camera,
  g the eye's axis, proj the part across the line of sight): in iris radii (5.91 mm)  1.31 proj(H) - 0.79 proj(g).
  Neither the head's turn nor its roll nor the eye's torsion enter it: only the eye's axis in the world, the light and
  the camera.
* The light source is MMD's (light.direction, the window's numbers: where the light goes; the default -0.5 -1 0.5
  comes from above, in front, on her left); the camera is the camera motion's, seen from each eye's pupil.
* The model's lights were drawn for the eye at rest, looking at a camera straight in front.  Each light keeps that
  drawn offset and moves by the change of the formula from that rest view (both lights of an eye by the same change:
  they keep their spacing, RESEARCH 1.8), the offsets scaled to the model's iris (its half width across X, half
  height across Y; Sour's Rin's iris is an ellipse, 0.1625 by 0.222).
* Each light bone (pmx_eyes: the pivot the pupil's depth behind the light) turns with 両目 by its append (pmx_eyes'
  share, formula A across); every frame its key adds the turn (light_turn) that brings its light from where the append
  alone puts it onto the camera's line through that point: damped least squares over the two turns across the bone,
  a few Gauss-Newton steps, so that seen from the front it lands on the line and seen side on (where a turn hardly
  moves the light across the line of sight) the turn stays small instead of swinging the light round.  No smoothing
  and no delay of its own: the same frame as the pupil (RESEARCH 0.2, items 2 to 4).  The key has no roll of its own.
* The change from the drawn place is held under light.cap iris radii (soft: unchanged up to 60 % of it, tanh beyond):
  a light reaches the limbus about one iris radius from the pupil's centre, where it leaves the cornea.
* When the camera sees her face from the side or behind (more than light.side[0] degrees off the face's forward, both
  eyes' mean) the line through the light no longer meets the eye from the front: the turn gives way, by light.side[1]
  degrees wholly, to the bone's append alone (the light painted on the iris again; the eye is hardly seen there).
* The light leaves the cornea when the light source lies more than 90 to 100 degrees from the camera (RESEARCH 1.6;
  the coordinator's rule): the morph HL消 (the light material's opacity) goes from 0 at light.hide[0] to 1 at
  light.hide[1] degrees between the light and the camera seen from the eyes, each frame on its own.  (The research's
  wider rule, H more than 46 to 50 degrees off the eye's axis, would also hide it whenever the eye turns away from the
  light; the report counts those frames as frames_beyond_cornea.)

The pupil (morphs 瞳大 and 瞳細 of Sour's Rin: with 瞳1off at 1 the navy pupil; 瞳大 widens only it, to (1 + 1.73 w) of
its radius, 瞳細 narrows only it, to (1 - 0.67 w); the factors are measured on the model's own morphs; 瞳小 would
shrink the whole iris and is not used).  r, the change of the pupil's diameter against the model's own, sums

* the light reflex at each flare of the MV's look (--look's "flares", seconds, and --flares; RESEARCH 2.1): from
  reflex.latency after the flare, for reflex.hold seconds, the pupil is pulled narrower with the time constant
  reflex.constrict (0.3 s), then widens again with reflex.redilate (2.4 s, 90 % back in 5.5 s): most narrow about
  1 s after the flare (latency 0.25 + hold 0.75; the reflex outlasts a 0.4-second flash), scaled so that one flare
  narrows it by reflex.peak (12 %);
* arousal: the song's loudness (--audio, RMS read with ffmpeg, 0 at its arousal.low and 1 at its arousal.high
  percentile) followed with arousal.rise on the way up and arousal.fall on the way down, arousal.amplitude from the
  quietest to the loudest about its median (music: 1 to 2 %, RESEARCH 2.2);
* at the head of each chorus (--chorus, seconds) a dilation of chorus.amplitude shaped as the pupil's response to an
  event, h(t) = (t / t_max)^n e^(n (1 - t / t_max)), n 10.1, t_max chorus.peak (0.93 s; Hoeks & Levelt via Wierda 2012);
* the near response: near.per_dioptre narrower for each dioptre of the vergence's demand (small; RESEARCH 2.4);
* unrest: unrest.waves sines between unrest.low_hz and high_hz (under 2 Hz) with random phases (from --seed),
  unrest.amplitude RMS together (RESEARCH 2.3: small while awake and busy).
r is kept in pupil.range; r > 0 is 瞳大 r / 1.73, r < 0 瞳細 -r / 0.67.

The vergence (keys on 右目 and 左目, after their append from 両目; RESEARCH 3.2 and 0.2 item 9):

* The eyes converge on her hands only, not on the camera, however near (large eyes look cross-eyed; a person's line of
  sight lies about 6 degrees nasal of the eye's axis anyway).  A hand is looked at (fixation_targets) when one of its
  points (vergence.hand_points) lies within hand_deg of the gaze (both eyes' mean, in the world), between near_m and
  hand_m away, for hand_frames frames on end; the camera, within camera_deg of the gaze, wins when it is nearer the gaze
  for its tolerance.
* The demand during a run on a hand is gain x atan((ipd / 2) / distance) per eye, the distance the run's median
  (ipd 61.5 mm, Murray 2017; gain 0.75: below the geometric angle, as RESEARCH 0.2 asks); elsewhere 0.
* It follows the demand (vergence_track) vergence.latency (0.24 s) after each change, along a minimum-jerk curve whose
  5 to 95 % time is vergence.duration (0.38 s) or longer, so its top speed stays under max_speed (8 deg/s; Tyler 2015).
* Each eye then turns from the gaze onto the point at that distance along it (right eye -X, left eye +X: inward is
  +yaw for the right eye and -yaw for the left, as the coordinator's vergence probe keys them).

The eyes' fine motion (drift, microsaccades) is tools/eye_gaze.py's; this tool does not change the gaze.  The VMD keys
every frame where a value changes, with linear curves, under the dance's model name.  The face's and the dance's keys
on the same bones and morphs would mix with these: they are refused, except keys on frame 0 that rest (identity, 0).
"""
import argparse
import copy
import json
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402
import pmx_eyes  # noqa: E402

FPS = 30.0
SHOWN = 0.1875                  # frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py; tools/face_life.py)
FORWARD = (0.0, 0.0, -1.0)
UP = (0.0, 1.0, 0.0)
BIG, THIN, HIDE = "瞳大", "瞳細", "HL消"
CUT_JUMP, CUT_TURN = 1.0, 5.0   # a camera cut: it moves more than this (units) or turns more (degrees) in a frame
MIN_JERK_5_95 = 0.6162          # the 5 to 95 % time of a minimum-jerk move, as a share of its whole time
MIN_JERK_TOP = 1.875            # its top speed, times step / time

PARAMS = {
    "light": {
        "cornea_radius_mm": 7.72,            # R (Navarro, via Barsingerhorn 2017)
        "pupil_to_centre_mm": 4.67,          # K: entrance pupil to the cornea's centre of curvature (RESEARCH 1.1)
        "iris_radius_mm": 5.91,              # the visible iris (Aguirre 2019)
        "direction": [-0.5, -1.0, 0.5],      # MMD's light, as its window shows it (where the light goes)
        "hide": [90.0, 100.0],               # degrees between the light and the camera: HL消 0 .. 1 (RESEARCH 1.6)
        "cap": 1.0,                          # iris radii the light moves off its drawn place at most (soft)
        "side": [60.0, 80.0],                # degrees the camera lies off the face's forward: the solve gives way
        "damping": 0.15,                     # light_turn's damping, a share of the bone's depth
    },
    "vergence": {
        "ipd_mm": 61.5,                      # women's mean (Murray 2017)
        "unit_mm": 80.0,                     # one model unit
        "gain": 0.75,                        # the share of the geometric angle (below it, RESEARCH 0.2 item 9)
        "near_m": 0.15,                      # a hand nearer than this is not looked at
        "hand_m": 0.6,
        "hand_deg": 12.0,
        "hand_frames": 6,
        "hand_points": ["人指３先", "中指３先", "親指２先", "手先"],
        "camera_deg": 4.0,                   # tools/eye_gaze.py counts a gaze this near the camera as eye contact
        "camera_frames": 3,
        "latency": 0.24,                     # seconds (Tyler 2015, 2-degree steps)
        "duration": 0.38,                    # seconds, 5 to 95 %
        "max_speed": 8.0,                    # degrees a second
    },
    "pupil": {
        "iris_mm": 11.82,                    # the visible iris' diameter, to give the pupil in mm
        "reflex": {"peak": 0.12, "latency": 0.25, "hold": 0.75, "constrict": 0.3, "redilate": 2.4},
        "arousal": {"amplitude": 0.015, "rise": 1.0, "fall": 3.0, "low": 10.0, "high": 90.0},
        "chorus": {"amplitude": 0.015, "peak": 0.93, "n": 10.1},
        "near": {"per_dioptre": 0.01},
        "unrest": {"amplitude": 0.01, "low_hz": 0.1, "high_hz": 0.7, "waves": 6},
        "range": [-0.35, 0.5],
    },
}


def merge_params(base, override, path="params"):
    """a copy of `base` with the values of `override` (the same shape; ValueError on a key `base` lacks)"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key not in out:
            raise ValueError("%s has no %r (it has %s)" % (path, key, ", ".join(sorted(out))))
        if isinstance(out[key], dict):
            if not isinstance(value, dict):
                raise ValueError("%s.%s is a group of values, not %r" % (path, key, value))
            out[key] = merge_params(out[key], value, path + "." + key)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ---- vectors --------------------------------------------------------------------------------

def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 0.0 else tuple(v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(a, k):
    return tuple(k * x for x in a)


def _degrees_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))))


def _between(a, b):
    """the shortest rotation taking the unit vector a onto the unit vector b"""
    d = _dot(a, b)
    if d < -0.999999:
        axis = _unit(_cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)))
        return (axis[0], axis[1], axis[2], 0.0)
    c = _cross(a, b)
    return fk.normalized((c[0], c[1], c[2], 1.0 + d))


def _angle(q):
    return math.degrees(2.0 * math.acos(min(1.0, abs(fk.normalized(q)[3]))))


# ---- vergence -------------------------------------------------------------------------------

def vergence_degrees(distance_m, ipd_mm):
    """the turn of each eye toward a point straight ahead: atan((ipd / 2) / distance)"""
    return math.degrees(math.atan((ipd_mm / 2.0) / (distance_m * 1000.0)))


def vergence_turns(gaze, distance, half):
    """(right, left): the rotations (as applied, after the gaze, in the head's frame) that turn each eye from the gaze
    `gaze` onto the point `distance` along it; the right eye sits at -half on X, the left at +half (model units)"""
    g = _unit(gaze)
    target = tuple(distance * c for c in g)
    return tuple(_between(g, _unit(tuple(t - e for t, e in zip(target, (x, 0.0, 0.0))))) for x in (-half, half))


def _runs(mask):
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


def fixation_targets(rows, params):
    """(metres, labels) per frame: what the eyes look at.  A row is {"camera": (degrees off the gaze, metres),
    "hands": [(degrees off the gaze, metres), ...]}; see the module docstring."""
    p = params
    cam_ok = [r["camera"][0] <= p["camera_deg"] for r in rows]
    hand = []
    for r in rows:
        fit = [h[:2] for h in r["hands"] if h[0] <= p["hand_deg"] and p["near_m"] <= h[1] <= p["hand_m"]]
        hand.append(min(fit) if fit else None)
    labels = []
    for i, r in enumerate(rows):
        options = []
        if cam_ok[i]:
            options.append((r["camera"][0] / p["camera_deg"], "camera"))
        if hand[i] is not None:
            options.append((hand[i][0] / p["hand_deg"], "hand"))
        labels.append(min(options)[1] if options else "free")
    for a, b in _runs([lab == "hand" for lab in labels]):
        if b - a + 1 < p["hand_frames"]:
            for i in range(a, b + 1):
                labels[i] = "camera" if cam_ok[i] else "free"
    for a, b in _runs([lab == "camera" for lab in labels]):
        if b - a + 1 < p["camera_frames"]:
            for i in range(a, b + 1):
                labels[i] = "free"
    metres = []
    for i, r in enumerate(rows):
        metres.append(r["camera"][1] if labels[i] == "camera" else hand[i][1] if labels[i] == "hand" else None)
    return metres, labels


def _median(values):
    s = sorted(values)
    n = len(s)
    return 0.0 if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def vergence_demand(labels, metres, params):
    """degrees per eye wanted per frame: gain x atan((ipd / 2) / distance) through each run on a hand (its median
    distance), 0 elsewhere (the camera and things far away are looked at with the eyes parallel)"""
    out = [0.0] * len(labels)
    for a, b in _runs([lab == "hand" for lab in labels]):
        d = params["gain"] * vergence_degrees(_median(metres[a:b + 1]), params["ipd_mm"])
        for i in range(a, b + 1):
            out[i] = d
    return out


def _min_jerk(s):
    s = min(1.0, max(0.0, s))
    return s * s * s * (10.0 + s * (6.0 * s - 15.0))


def vergence_track(demands, fps, latency, duration, max_speed):
    """the vergence per frame: each change of the demand starts, `latency` seconds later, a minimum-jerk move from
    where the vergence is then to the new demand, whose 5 to 95 % time is `duration` or longer so that its top speed
    stays under `max_speed` (degrees a second); a change during a move starts the next move from there"""
    if not demands:
        return []
    moves = []                                   # (start in frames, from, to, length in frames)

    def value(t):
        for t0, v0, v1, length in reversed(moves):
            if t >= t0:
                return v0 + (v1 - v0) * _min_jerk((t - t0) / length)
        return demands[0]
    for i in range(1, len(demands)):
        if demands[i] != demands[i - 1]:
            t0 = i + latency * fps
            v0 = value(t0)
            step = abs(demands[i] - v0)
            seconds = max(duration / MIN_JERK_5_95, MIN_JERK_TOP * step / max_speed)
            moves.append((t0, v0, demands[i], seconds * fps))
    return [value(float(f)) + 0.0 for f in range(len(demands))]


# ---- the light ------------------------------------------------------------------------------

def toward_light(direction):
    """the unit vector toward MMD's light from the window's direction (where the light goes)"""
    return tuple(-c for c in _unit(direction))


def screen_basis(view):
    """(right, up): the screen's axes for a camera seen along `view` (the unit vector from the eye to the camera),
    with the world's +Y as up (a camera straight in front gives +X and +Y)"""
    right = _cross(view, UP)
    if math.sqrt(_dot(right, right)) < 1e-9:
        right = _cross(view, (0.0, 0.0, 1.0))
    right = _unit(right)
    return right, _cross(right, view)


def light_offset(half, axis, view, cornea, lag):
    """the light's centre minus the pupil's on the screen, in iris radii (right, up): cornea proj(half) - lag proj(axis),
    `half` the half-way direction between the light and the camera, `axis` the eye's, `view` toward the camera"""
    right, up = screen_basis(view)
    return (cornea * _dot(half, right) - lag * _dot(axis, right), cornea * _dot(half, up) - lag * _dot(axis, up))


def _across(v, view):
    return _sub(v, _scale(view, _dot(v, view)))


def _about_vector(w):
    """the rotation of the rotation vector w (radians)"""
    a = math.sqrt(_dot(w, w))
    if a < 1e-15:
        return fk.IDENTITY
    s = math.sin(a / 2.0) / a
    return fk.normalized((w[0] * s, w[1] * s, w[2] * s, math.cos(a / 2.0)))


def light_turn(pivot, depth, radial, target, view, damping=0.15, steps=4):
    """the turn (a rotation in the world, about `pivot`) that brings the point pivot + depth radial onto the camera's
    line through `target` (seen along `view`): damped least squares over the two turns across `radial`, `damping`
    times depth as the damping, a few Gauss-Newton steps.  Seen from the front it lands on the line; seen side on,
    where a turn hardly moves the light across the line of sight, the damping keeps the turn small."""
    lam = (damping * depth) ** 2
    total = fk.IDENTITY
    r = _unit(radial)
    for _ in range(steps):
        a = _cross(r, view)
        if math.sqrt(_dot(a, a)) < 1e-9:
            a = _cross(r, UP)
        a = _unit(a)
        b = _cross(r, a)
        ja, jb = _across(_scale(_cross(a, r), depth), view), _across(_scale(_cross(b, r), depth), view)
        e = _across(_sub(target, _add(pivot, _scale(r, depth))), view)
        aa, ab, bb = _dot(ja, ja) + lam, _dot(ja, jb), _dot(jb, jb) + lam
        ea, eb = _dot(ja, e), _dot(jb, e)
        det = aa * bb - ab * ab
        if det <= 0.0:
            break
        x, y = (bb * ea - ab * eb) / det, (aa * eb - ab * ea) / det
        step = _about_vector(_add(_scale(a, x), _scale(b, y)))
        total = fk.multiply(step, total)
        r = fk.rotate(step, r)
        if abs(x) + abs(y) < 1e-12:
            break
    return total


def _smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def hide_track(angles, start, end):
    """HL消 per frame from the angle between the light and the camera: 0 at `start`, 1 at `end`, smoothstep between"""
    return [_smoothstep((a - start) / (end - start)) + 0.0 for a in angles]


SOFT_FROM = 0.6                 # share of a cap up to which soft_cap passes values unchanged


def soft_cap(vec, cap):
    """the 2-vector with its length kept under cap: unchanged up to SOFT_FROM of it, along tanh beyond"""
    n = math.hypot(*vec)
    if n <= SOFT_FROM * cap or n == 0.0:
        return tuple(vec)
    span = 1.0 - SOFT_FROM
    k = cap * (SOFT_FROM + span * math.tanh((n / cap - SOFT_FROM) / span)) / n
    return tuple(c * k for c in vec)


# ---- the pupil ------------------------------------------------------------------------------

def _first_order(targets, fps, narrowing, widening):
    """a follower of the targets with the time constant `narrowing` on the way down and `widening` on the way up;
    each frame moves toward that frame's target"""
    out, x = [], 0.0
    for t in targets:
        tau = narrowing if t < x else widening
        x += (t - x) * (1.0 - math.exp(-1.0 / (tau * fps)))
        out.append(x)
    return out


def _reflex_drive(n, flares, fps, latency, hold):
    """-1 through `hold` seconds from each flare's onset (`latency` after it), 0 elsewhere (frames after the onset)"""
    out = [0.0] * n
    for at in flares:
        onset = at + latency * fps
        for i in range(max(0, int(math.floor(onset)) + 1), min(n, int(math.floor(onset + hold * fps)) + 1)):
            out[i] = -1.0
    return out


def reflex_track(n, flares, fps, rx):
    """the pupil's change from the light reflex per frame (0 or below): see the module docstring.  `flares` are
    frames (floats)."""
    one = _first_order(_reflex_drive(int(10 * fps), [0.0], fps, rx["latency"], rx["hold"]), fps, rx["constrict"],
                       rx["redilate"])
    k = rx["peak"] / -min(one)
    drive = _reflex_drive(n, flares, fps, rx["latency"], rx["hold"])
    return [v * k + 0.0 for v in _first_order(drive, fps, rx["constrict"], rx["redilate"])]


def event_shape(t, peak, power):
    """the pupil's response to an event: (t / peak)^power e^(power (1 - t / peak)), 1 at t = peak, 0 at and before 0"""
    if t <= 0.0:
        return 0.0
    x = t / peak
    return math.exp(power * (math.log(x) + 1.0 - x))


def _follow(values, rise_frames, fall_frames):
    """a first-order follower with one time constant on the way up and another on the way down"""
    out, x = [], values[0] if values else 0.0
    for v in values:
        k = 1.0 / (rise_frames if v > x else fall_frames)
        x += (v - x) * (1.0 - math.exp(-k))
        out.append(x)
    return out


def pupil_track(n, flares, arousal, chorus, near, params, seed=0, fps=FPS):
    """the change of the pupil's diameter against the model's own, per frame, with its parts: {"total", "reflex",
    "arousal", "chorus", "near", "unrest"}.  `flares` and `chorus` are frames (floats), `arousal` the loudness per
    frame from 0 to 1 (or None), `near` the vergence's demand in dioptres per frame."""
    p = params
    reflex = reflex_track(n, flares, fps, p["reflex"])
    ar = p["arousal"]
    if arousal:
        env = _follow(list(arousal[:n]) + [arousal[-1]] * max(0, n - len(arousal)), ar["rise"] * fps, ar["fall"] * fps)
        lo, hi = min(env), max(env)
        mid = _median(env)
        span = (hi - lo) if hi > lo else 1.0
        arousal_part = [ar["amplitude"] * (v - mid) / span for v in env]
    else:
        arousal_part = [0.0] * n
    ch = p["chorus"]
    chorus_part = [0.0] * n
    for at in chorus:
        for i in range(max(0, int(math.floor(at)) + 1), n):
            chorus_part[i] += ch["amplitude"] * event_shape((i - at) / fps, ch["peak"], ch["n"])
    near_part = [-p["near"]["per_dioptre"] * max(0.0, d) for d in near]
    un = p["unrest"]
    rng = random.Random(seed)
    waves = [(rng.uniform(un["low_hz"], un["high_hz"]), rng.uniform(0.0, 2.0 * math.pi)) for _ in range(int(un["waves"]))]
    each = un["amplitude"] * math.sqrt(2.0 / len(waves)) if waves else 0.0
    unrest = [sum(each * math.sin(2.0 * math.pi * f * i / fps + ph) for f, ph in waves) + 0.0 for i in range(n)]
    low, high = p["range"]
    total = [min(high, max(low, a + b + c + d + e)) + 0.0
             for a, b, c, d, e in zip(reflex, arousal_part, chorus_part, near_part, unrest)]
    return {"total": total, "reflex": reflex, "arousal": arousal_part, "chorus": chorus_part, "near": near_part,
            "unrest": unrest}


def pupil_weights(change, big, thin):
    """(瞳大, 瞳細) per frame for the diameter changes: the radius goes to (1 + big w) with 瞳大 and (1 + thin w) with
    瞳細 (thin < 0)"""
    wb = [min(1.0, max(0.0, r / big)) + 0.0 if r > 0.0 else 0.0 for r in change]
    wt = [min(1.0, max(0.0, r / thin)) + 0.0 if r < 0.0 else 0.0 for r in change]
    return wb, wt


def pupil_scales(doc, big=BIG, thin=THIN, iris_material=pmx_eyes.IRIS_MATERIAL):
    """{"big", "thin"}: the change of the pupil's radius per unit weight of the two morphs, measured on the model (the
    median over the outer half of the pupil's vertices of the offset along the radius, across the line of sight, over
    the radius), and "ratio", the pupil's width over the iris' (the material iris_material) when the model has it"""
    morphs = pmx_eyes.vertex_morphs(doc)
    if big not in morphs or thin not in morphs:
        raise ValueError("the model lacks the pupil morphs %s / %s" % (big, thin))
    eyes, _ = pmx_eyes.find_eyes(doc)
    out = {}
    side = {v: pmx_eyes._eye_of(doc, v, eyes) for v in morphs[big]}
    centre = {}
    for e in eyes:
        pts = [doc.vertices[v].position() for v in morphs[big] if side[v] == e]
        centre[e] = tuple(sum(p[c] for p in pts) / len(pts) for c in range(3))
    radii = {}
    for v in morphs[big]:
        p, c = doc.vertices[v].position(), centre[side[v]]
        radii[v] = (p[0] - c[0], p[1] - c[1])
    top = max(math.hypot(*r) for r in radii.values())
    for key, name in (("big", big), ("thin", thin)):
        ratios = []
        for v, off in morphs[name].items():
            if v not in radii:
                continue
            r = radii[v]
            n = math.hypot(*r)
            if n >= 0.5 * top:
                ratios.append((off[0] * r[0] + off[1] * r[1]) / (n * n))
        if not ratios:
            raise ValueError("%s moves none of the pupil's vertices" % name)
        out[key] = _median(ratios)
    tri = pmx_eyes.material_triangles(doc, iris_material)
    if tri:
        iris = {v for t in tri for v in t}
        e = eyes[0]
        xs = [doc.vertices[v].position()[0] for v in iris if pmx_eyes._eye_of(doc, v, eyes) == e]
        ps = [doc.vertices[v].position()[0] for v in morphs[big] if side[v] == e]
        if xs and ps and max(xs) > min(xs):
            out["ratio"] = (max(ps) - min(ps)) / (max(xs) - min(xs))
    return out


def eye_geometry(doc, pupil_morph=pmx_eyes.PUPIL_MORPH, iris_material=pmx_eyes.IRIS_MATERIAL):
    """per eye index: {"pupil": the rest centre of the pupil morph's vertices, "iris": (half width across X, half
    height across Y) of the iris material}"""
    eyes, _ = pmx_eyes.find_eyes(doc)
    pupil = pmx_eyes.vertex_morphs(doc).get(pupil_morph) or {}
    iris = sorted({v for t in pmx_eyes.material_triangles(doc, iris_material) or [] for v in t})
    out = {}
    for e in eyes:
        pts = [doc.vertices[v].position() for v in pupil if pmx_eyes._eye_of(doc, v, eyes) == e]
        if not pts:
            raise ValueError("%s moves no vertex of %s: the pupil's centre is taken from it" % (pupil_morph, doc.bones[e].name))
        mine = [doc.vertices[v].position() for v in iris if pmx_eyes._eye_of(doc, v, eyes) == e]
        if not mine:
            raise ValueError("the model has no %s material on %s: the light's offsets are in iris radii"
                             % (iris_material, doc.bones[e].name))
        xs, ys = [p[0] for p in mine], [p[1] for p in mine]
        out[e] = {"pupil": tuple(sum(p[c] for p in pts) / len(pts) for c in range(3)),
                  "iris": ((max(xs) - min(xs)) / 2.0, (max(ys) - min(ys)) / 2.0)}
    return out


# ---- measures -------------------------------------------------------------------------------

def _pct(values, q):
    s = sorted(values)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(round(q / 100.0 * (len(s) - 1))))]


def _r(value, places=4):
    return round(float(value), places) + 0.0


def step_stats(values, skip=()):
    """the change from one frame to the next (the length for vectors): its largest and its 99th percentile, leaving
    out the steps into the frames of `skip`"""
    if len(values) < 2:
        return {"max": 0.0, "p99": 0.0}
    skip = set(skip)
    steps = []
    for i in range(1, len(values)):
        if i in skip:
            continue
        u, v = values[i - 1], values[i]
        if isinstance(u, (tuple, list)):
            steps.append(math.sqrt(sum((b - a) ** 2 for a, b in zip(u, v))))
        else:
            steps.append(abs(v - u))
    if not steps:
        return {"max": 0.0, "p99": 0.0}
    return {"max": _r(max(steps), 5), "p99": _r(_pct(steps, 99), 5)}


def summary(values):
    if not values:
        return {}
    return {"min": _r(min(values)), "median": _r(_pct(values, 50)), "p95": _r(_pct(values, 95)), "max": _r(max(values))}


# ---- the motions ----------------------------------------------------------------------------

def merge(*motions):
    """the bone keys of motions loaded one after another: a later motion's keys replace the earlier ones of the same
    bone on the same frame"""
    by = {}
    for m in motions:
        mine = {}
        for k in m.bones:
            mine.setdefault(k.name, []).append(k)
        for name, keys in mine.items():
            frames = {k.frame for k in keys}
            by[name] = [k for k in by.get(name, []) if k.frame not in frames] + keys
    return vmd.Motion(model_name=motions[0].model_name, bones=[k for keys in by.values() for k in keys])


def check_overlaps(motions, bones, morphs):
    """ValueError when one of `motions` ({label: Motion}) keys a bone of `bones` or a morph of `morphs` beyond a
    resting key on frame 0 (identity, weight 0): MMD would mix them with this tool's keys"""
    problems = []
    for label, m in motions.items():
        for k in m.bones:
            if k.name in bones and not (k.frame == 0 and _angle(k.rotation) < 1e-4 and max(abs(c) for c in k.position) < 1e-6):
                problems.append("%s keys bone %s on frame %d" % (label, k.name, k.frame))
        for k in m.morphs:
            if k.name in morphs and not (k.frame == 0 and abs(k.weight) < 1e-9):
                problems.append("%s keys morph %s on frame %d" % (label, k.name, k.frame))
    if problems:
        raise ValueError("these keys would mix with eye_optics': %s%s" % ("; ".join(problems[:6]),
                                                                          " ..." if len(problems) > 6 else ""))


def _bone_keys(name, frames, rotations):
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    stored = [tuple(round(c, 6) for c in fk.stored(fk.normalized(q))) for q in rotations]
    out = []
    for i, (f, q) in enumerate(zip(frames, stored)):
        if 0 < i < len(stored) - 1 and stored[i - 1] == q == stored[i + 1]:
            continue
        out.append(vmd.BoneKey(name, f, fk.ZERO, q, straight))
    return out


def _morph_keys(name, frames, weights):
    values = [round(w, 6) + 0.0 for w in weights]
    out = []
    for i, (f, w) in enumerate(zip(frames, values)):
        if 0 < i < len(values) - 1 and values[i - 1] == w == values[i + 1]:
            continue
        out.append(vmd.MorphKey(name, f, w))
    return out


# ---- everything -----------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    trace: dict = None          # per frame: what --trace writes


def _catchlights(model, handle, eyes):
    out = []
    names = {model.bones[e].name: e for e in eyes}
    sides = {v: k for k, v in pmx_eyes.SIDE_EN.items()}
    for b in model.bones:
        if not (b.name_en or "").startswith(pmx_eyes.EN_PREFIX):
            continue
        if not (b.append and b.append.get("parent") == handle and b.flags.get("append_rotate")):
            raise ValueError("the catchlight bone %s does not turn with %s by append" % (b.name, model.bones[handle].name))
        tag = b.name_en[len(pmx_eyes.EN_PREFIX):].split("_")
        side = sides.get(tag[1] if len(tag) > 1 else "")
        target = next((n for n in names if side and n.startswith(side)), None)
        if target is None:
            raise ValueError("cannot tell which eye the catchlight bone %s (%s) belongs to" % (b.name, b.name_en))
        tail = b.tail.get("offset") if b.tail else None
        depth = math.sqrt(_dot(tail, tail)) if tail else 0.0
        if depth <= 0.0:
            raise ValueError("the catchlight bone %s has no tail offset to its light (pmx_eyes sets it)" % b.name)
        out.append({"name": b.name, "index": b.index, "eye": target, "eye_index": names[target],
                    "share": float(b.append["ratio"]), "pivot": tuple(b.position), "depth": depth,
                    "rest": _add(b.position, tuple(tail))})
    if not out:
        raise ValueError("the model has no catchlight bones: make it with tools/pmx_eyes.py first")
    return out


def _cuts(cameras):
    out = set()
    for i in range(1, len(cameras)):
        (p0, d0), (p1, d1) = cameras[i - 1], cameras[i]
        if math.sqrt(_dot(_sub(p1, p0), _sub(p1, p0))) > CUT_JUMP or _degrees_between(d0, d1) > CUT_TURN:
            out.add(i)
    return out


def optics(model_bytes, dance, gaze, camera, params=None, flares=(), arousal=None, chorus=(), seed=0):
    """the eye optics motion and its report for the model (the bytes of a PMX made by pmx_eyes), the dance, the gaze
    (両目) and the camera; `flares` and `chorus` in seconds, `arousal` the loudness per frame from 0 to 1"""
    p = merge_params(PARAMS, {}) if params is None else params
    doc = pmx_edit.loads(model_bytes)
    model = pmx.loads(model_bytes)
    eye_idx, handle = pmx_eyes.find_eyes(doc)
    eyes = [model.bones[e].name for e in eye_idx]
    heads = {model.bones[e].parent for e in eye_idx}
    if len(heads) != 1 or None in heads:
        raise ValueError("the eyes %s do not share one parent" % "/".join(eyes))
    head_index = heads.pop()
    head = model.bones[head_index].name
    lights = _catchlights(model, handle, eye_idx)
    geometry = eye_geometry(doc)
    scales = pupil_scales(doc)
    names = {b.name for b in model.bones}
    vp, lp, pp = p["vergence"], p["light"], p["pupil"]
    hands = [s + h for s in ("右", "左") for h in vp["hand_points"] if s + h in names]
    motion = merge(dance, gaze)
    if not motion.bones:
        raise ValueError("the dance and the gaze have no bone keys")
    last = max(fk.last_frame(dance), fk.last_frame(gaze))
    frames = list(range(0, last + 1))
    n = len(frames)
    track = fk.world_track(model, motion, [head] + eyes + hands, 0, last)
    handle_track = fk.tracks_of(motion).get(model.bones[handle].name) or fk.tracks_of(motion).get(
        fk.vmd_name(model.bones[handle].name))
    handle_frames = [k.frame for k in handle_track] if handle_track else None
    cam_keys = fk.camera_keys(camera)
    cam_frames = [k.frame for k in cam_keys]
    unit_m = vp["unit_mm"] / 1000.0
    half = vp["ipd_mm"] / 2.0 / vp["unit_mm"]
    head_world, gaze_head, rows, cameras = [], [], [], []
    for i in range(n):
        hp, hr = track[head][i]
        inv = fk.conjugate(hr)
        per_eye = [fk.rotate(fk.multiply(inv, track[e][i][1]), FORWARD) for e in eyes]
        g_h = _unit(_add(*per_eye))
        g_w = fk.rotate(hr, g_h)
        centre = _scale(_add(track[eyes[0]][i][0], track[eyes[1]][i][0]), 0.5)
        state = fk.camera_at(cam_keys, frames[i], cam_frames)
        c = fk.camera_position(state)
        to_cam = _sub(c, centre)
        row = {"camera": (_degrees_between(g_w, to_cam), math.sqrt(_dot(to_cam, to_cam)) * unit_m), "hands": []}
        for h in hands:
            to_hand = _sub(track[h][i][0], centre)
            row["hands"].append((_degrees_between(g_w, to_hand), math.sqrt(_dot(to_hand, to_hand)) * unit_m, h))
        rows.append(row)
        head_world.append((hp, hr))
        gaze_head.append(g_h)
        cameras.append((c, fk.camera_direction(state)))
    cuts = _cuts(cameras)
    # vergence
    metres, labels = fixation_targets(rows, vp)
    demand = vergence_demand(labels, metres, vp)
    angle = vergence_track(demand, FPS, vp["latency"], vp["duration"], vp["max_speed"])
    turns = []
    for g, a in zip(gaze_head, angle):
        turns.append(vergence_turns(g, half / math.tan(math.radians(a)), half) if a > 1e-9 else (fk.IDENTITY, fk.IDENTITY))
    # the light
    light = toward_light(lp["direction"])
    cornea = lp["cornea_radius_mm"] / lp["iris_radius_mm"]
    lag = lp["pupil_to_centre_mm"] / lp["iris_radius_mm"]
    rest_half = _unit(_add(light, FORWARD))
    rest_offset = light_offset(rest_half, FORWARD, FORWARD, cornea, lag)
    head_rest = model.bones[head_index].position
    eye_rest = {e: model.bones[e].position for e in eye_idx}
    side_of = {e: k for k, e in enumerate(eye_idx)}
    drawn = {}
    for c in lights:
        geo = geometry[c["eye_index"]]
        d = _sub(c["rest"], geo["pupil"])
        drawn[c["name"]] = (d[0] / geo["iris"][0], d[1] / geo["iris"][1])
    keys_q = {c["name"]: [] for c in lights}
    offsets = {c["name"]: [] for c in lights}
    off_camera, off_axis, sideways = [], [], []
    for i in range(n):
        hp, hr = head_world[i]
        inv = fk.conjugate(hr)
        q_handle = fk.applied(fk.sample(handle_track, frames[i], handle_frames)[1]) if handle_track else fk.IDENTITY
        cam = cameras[i][0]
        face = fk.rotate(hr, FORWARD)
        per_eye = {}
        alphas, axes_off, sides = [], [], []
        for e in eye_idx:
            k = side_of[e]
            eye_world_pos = track[eyes[k]][i][0]
            eye_local = fk.multiply(turns[i][k], fk.multiply(inv, track[eyes[k]][i][1]))   # the vergence key on top
            eye_world_rot = fk.multiply(hr, eye_local)
            pupil = _add(eye_world_pos, fk.rotate(eye_world_rot, _sub(geometry[e]["pupil"], eye_rest[e])))
            axis = fk.rotate(eye_world_rot, FORWARD)
            view = _unit(_sub(cam, pupil))
            h = _unit(_add(light, view))
            now = light_offset(h, axis, view, cornea, lag)
            moved = soft_cap((now[0] - rest_offset[0], now[1] - rest_offset[1]), lp["cap"])
            per_eye[e] = (pupil, view, moved)
            alphas.append(_degrees_between(light, view))
            axes_off.append(_degrees_between(h, axis))
            sides.append(_degrees_between(view, face))
        off_camera.append(sum(alphas) / len(alphas))
        off_axis.append(sum(axes_off) / len(axes_off))
        side = _smoothstep((sum(sides) / len(sides) - lp["side"][0]) / (lp["side"][1] - lp["side"][0]))
        sideways.append(side)
        for c in lights:
            pupil, view, moved = per_eye[c["eye_index"]]
            geo = geometry[c["eye_index"]]
            dx, dy = drawn[c["name"]]
            ox, oy = dx + moved[0], dy + moved[1]
            fallback = fk.power(q_handle, c["share"])
            key = fk.IDENTITY
            if side < 1.0:
                right, up = screen_basis(view)
                target = _add(pupil, _add(_scale(right, ox * geo["iris"][0]), _scale(up, oy * geo["iris"][1])))
                pivot = _add(hp, fk.rotate(hr, _sub(c["pivot"], head_rest)))
                radial = fk.rotate(fk.multiply(hr, fallback), FORWARD)     # where the append alone points the light
                turn = light_turn(pivot, c["depth"], radial, target, view, lp["damping"])
                key = fk.multiply(inv, fk.multiply(turn, hr))               # the same turn in the head's frame
                if side > 0.0:
                    key = fk.slerp(key, fk.IDENTITY, side)
            keys_q[c["name"]].append(key)
            offsets[c["name"]].append((ox, oy))
    hide = hide_track(off_camera, lp["hide"][0], lp["hide"][1])
    # the pupil
    near = [1.0 / (half * unit_m / math.tan(math.radians(a))) if a > 1e-9 else 0.0 for a in angle]
    flare_frames = [t * FPS - SHOWN for t in flares]
    chorus_frames = [t * FPS - SHOWN for t in chorus]
    pupil = pupil_track(n, flare_frames, arousal, chorus_frames, near, pp, seed)
    big, thin = pupil_weights(pupil["total"], scales["big"], scales["thin"])
    # the motion
    keys = []
    for k, e in enumerate(eyes):
        keys += _bone_keys(e, frames, [t[k] for t in turns])
    for c in lights:
        keys += _bone_keys(c["name"], frames, keys_q[c["name"]])
    morphs = _morph_keys(BIG, frames, big) + _morph_keys(THIN, frames, thin) + _morph_keys(HIDE, frames, hide)
    out = vmd.Motion(model_name=dance.model_name, bones=keys, morphs=morphs)
    # the report
    counts = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    hand_runs = []
    for a, b in _runs([lab == "hand" for lab in labels]):
        best = min((h for i in range(a, b + 1) for h in rows[i]["hands"]), key=lambda h: h[0])
        hand_runs.append({"first": frames[a], "last": frames[b], "seconds": _r((b - a + 1) / FPS, 3),
                          "median_m": _r(_median(metres[a:b + 1]), 3), "point": best[2],
                          "demand_degrees": _r(demand[a], 3), "reached_degrees": _r(max(angle[a:min(n, b + 30)]), 3)})
    first = lights[0]["name"]
    key_angles = [_angle(q) for q in keys_q[first]]
    moved = [math.hypot(o[0] - drawn[first][0], o[1] - drawn[first][1]) for o in offsets[first]]
    mm0 = pp["iris_mm"] * scales.get("ratio", 0.25)
    geo0 = geometry[eye_idx[0]]
    report = {
        "frames": [frames[0], frames[-1]], "seed": seed, "params": p,
        "model": {"head": head, "eyes": eyes, "handle": model.bones[handle].name, "share": lights[0]["share"],
                  "catchlights": [{k: c[k] for k in ("name", "eye", "share", "depth")} for c in lights],
                  "iris_radius": [_r(v, 5) for v in geo0["iris"]],
                  "pupil_scales": {k: _r(v, 4) for k, v in scales.items()},
                  "pupil_mm": _r(mm0, 3), "half_ipd_units": _r(half, 5)},
        "vergence": {"labels": counts, "hand_runs": hand_runs, "degrees": summary(angle), "demand": summary(demand),
                     "step": step_stats(angle)},
        "light": {"cornea": cornea, "lag": lag, "rest_offset": [_r(v) for v in rest_offset],
                  "drawn": {k: [_r(v) for v in d] for k, d in drawn.items()},
                  "moved": summary(moved), "cuts": len(cuts),
                  "offset_step": step_stats(offsets[first]), "offset_step_without_cuts": step_stats(offsets[first], cuts),
                  "key_step": step_stats(key_angles), "key_step_without_cuts": step_stats(key_angles, cuts),
                  "camera_aside": {"frames_partly": sum(1 for s in sideways if s > 0.0),
                                   "frames_fully": sum(1 for s in sideways if s >= 1.0)},
                  "bone": first},
        "fade": {"light_off_camera": summary(off_camera), "frames_on": sum(1 for h in hide if h > 0.0),
                 "frames_half": sum(1 for h in hide if h >= 0.5), "frames_full": sum(1 for h in hide if h >= 0.999),
                 "step": step_stats(hide), "step_without_cuts": step_stats(hide, cuts),
                 "half_off_axis": summary(off_axis),
                 "frames_beyond_cornea": sum(1 for a in off_axis if a > 48.0)},
        "pupil": {"flares_s": list(flares), "chorus_s": list(chorus), "relative": summary(pupil["total"]),
                  "mm": summary([mm0 * (1.0 + r) for r in pupil["total"]]),
                  "parts": {k: {"min": _r(min(v)), "max": _r(max(v))} for k, v in pupil.items() if k != "total"},
                  "steps": {"relative": step_stats(pupil["total"]), BIG: step_stats(big), THIN: step_stats(thin),
                            "mm": step_stats([mm0 * r for r in pupil["total"]])},
                  "weights": {BIG: _r(max(big)), THIN: _r(max(thin))}},
        "keys": {"bones": len(keys), "morphs": len(morphs)},
    }
    trace = {"frames": frames, "label": labels, "vergence": [_r(a, 4) for a in angle],
             "light": [[_r(o[0], 4), _r(o[1], 4)] for o in offsets[first]], "hide": [_r(h, 4) for h in hide],
             "pupil": [_r(r, 5) for r in pupil["total"]], "camera_aside": [_r(s, 4) for s in sideways],
             "light_off_camera": [_r(a, 2) for a in off_camera], "half_off_axis": [_r(a, 2) for a in off_axis],
             "eye_centre": [[_r(c, 4) for c in _scale(_add(track[eyes[0]][i][0], track[eyes[1]][i][0]), 0.5)]
                            for i in range(n)],
             "camera": [[_r(c, 4) for c in cameras[i][0]] for i in range(n)], "cuts": sorted(cuts),
             "light_bone": first}
    return Result(out, report, trace)


# ---- the song -------------------------------------------------------------------------------

def loudness(path, n, fps=FPS, rate=8000, window=0.2, low=10.0, high=90.0, smooth=0.5):
    """the song's loudness per frame from 0 (its `low` percentile) to 1 (its `high` percentile): RMS over `window`
    seconds about each frame's time in dB, then a moving mean over `smooth` seconds; read with ffmpeg"""
    import numpy as np
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    if len(x) < rate:
        raise ValueError("the sound %s is too short" % path)
    width = int(window * rate / 2)
    csum = np.concatenate([[0.0], np.cumsum(x * x)])
    db = np.zeros(n)
    for i in range(n):
        centre = int(round((i + SHOWN) / fps * rate))
        a, b = max(0, centre - width), min(len(x), centre + width)
        power = (csum[b] - csum[a]) / max(1, b - a) if b > a else 0.0
        db[i] = 10.0 * math.log10(max(power, 1e-12))
    lo, hi = np.percentile(db, low), np.percentile(db, high)
    a = np.clip((db - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    k = max(1, int(round(smooth * fps)))
    kernel = np.ones(k) / k
    a = np.convolve(np.concatenate([[a[0]] * (k // 2), a, [a[-1]] * (k - 1 - k // 2)]), kernel, mode="valid")
    return [float(v) for v in a[:n]], {"low_db": _r(lo, 2), "high_db": _r(hi, 2)}


# ---- the command ----------------------------------------------------------------------------

def _write(path, data):
    folder = os.path.dirname(os.path.abspath(path))
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
            raise ValueError("%s and %s are the same file: the inputs and the files written must all differ" % (seen[key], path))
        seen[key] = path


def run(model_path, dance_path, gaze_path, camera_path, out_path, face_path=None, look_path=None, flares=(),
        audio_path=None, chorus=(), params_path=None, report_path=None, seed=0, trace_path=None):
    started = time.time()
    check_distinct(model_path, dance_path, gaze_path, camera_path, out_path, face_path, look_path, audio_path, params_path,
                   report_path, trace_path)
    if params_path:
        with open(params_path, encoding="utf-8") as f:
            params = merge_params(PARAMS, json.load(f))
    else:
        params = merge_params(PARAMS, {})
    all_flares = sorted(set(float(t) for t in flares))
    if look_path:
        with open(look_path, encoding="utf-8") as f:
            look = json.load(f)
        all_flares = sorted(set(float(t) for t in look.get("flares", [])) | set(all_flares))
    with open(model_path, "rb") as f:
        model_bytes = f.read()
    dance = vmd.load(dance_path)
    gaze = vmd.load(gaze_path)
    camera = vmd.load(camera_path)
    model = pmx.loads(model_bytes)
    eye_names = {"右目", "左目"} | {b.name for b in model.bones if (b.name_en or "").startswith(pmx_eyes.EN_PREFIX)}
    motions = {"dance": dance, "gaze": gaze}
    if face_path:
        motions["face"] = vmd.load(face_path)
    check_overlaps(motions, eye_names, {BIG, THIN, HIDE})
    arousal, loud = None, None
    if audio_path:
        n = max(fk.last_frame(dance), fk.last_frame(gaze)) + 1
        ap = params["pupil"]["arousal"]
        arousal, loud = loudness(audio_path, n, low=ap["low"], high=ap["high"])
    result = optics(model_bytes, dance, gaze, camera, params, all_flares, arousal, [float(c) for c in chorus], seed)
    _write(out_path, vmd.dumps(result.motion))
    back = vmd.load(out_path)
    report = dict(result.report)
    report["in"] = {"model": os.path.abspath(model_path), "dance": os.path.abspath(dance_path),
                    "gaze": os.path.abspath(gaze_path), "camera": os.path.abspath(camera_path),
                    "face": os.path.abspath(face_path) if face_path else None,
                    "look": os.path.abspath(look_path) if look_path else None,
                    "audio": os.path.abspath(audio_path) if audio_path else None}
    report["out"] = os.path.abspath(out_path)
    report["written"] = {"bones": len(back.bones), "morphs": len(back.morphs)}
    if loud:
        report["pupil"]["loudness"] = loud
    report["seconds"] = _r(time.time() - started, 2)
    if report_path:
        _write(report_path, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if trace_path:
        _write(trace_path, (json.dumps(result.trace, ensure_ascii=False) + "\n").encode("utf-8"))
        report["trace"] = os.path.abspath(trace_path)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", help="the model made by tools/pmx_eyes.py (.pmx)")
    ap.add_argument("dance", help="the dance (.vmd)")
    ap.add_argument("gaze", help="the 両目 track of tools/eye_gaze.py (.vmd), loaded after the dance")
    ap.add_argument("camera", help="the camera motion (.vmd)")
    ap.add_argument("out", help="the eye optics motion to write (.vmd), to load after the dance, the face and the gaze")
    ap.add_argument("--face", help="the face motion: refused when it keys the pupil or light morphs")
    ap.add_argument("--look", help="the MV's look JSON: its \"flares\" (seconds) narrow the pupils")
    ap.add_argument("--flares", type=float, nargs="+", default=[], help="more flare times in seconds")
    ap.add_argument("--audio", help="the song (read with ffmpeg): its loudness widens the pupils")
    ap.add_argument("--chorus", type=float, nargs="+", default=[], help="the heads of the choruses in seconds")
    ap.add_argument("--params", help="a JSON of PARAMS' shape with the values to change")
    ap.add_argument("--report", help="write the measures to this JSON")
    ap.add_argument("--seed", type=int, default=0, help="the pupil's unrest (default 0)")
    ap.add_argument("--trace", help="write the values of every frame (target, vergence, light offset, HL消, pupil, the "
                                    "eyes' centre and the camera) to this JSON")
    a = ap.parse_args(argv)
    try:
        report = run(a.model, a.dance, a.gaze, a.camera, a.out, a.face, a.look, a.flares, a.audio, a.chorus, a.params,
                     a.report, a.seed, a.trace)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    short = {"ok": True, "out": report["out"], "frames": report["frames"], "keys": report["keys"],
             "vergence": {k: report["vergence"][k] for k in ("labels", "degrees", "step")},
             "light": {k: report["light"][k] for k in ("moved", "offset_step_without_cuts", "key_step_without_cuts", "cuts")},
             "fade": {k: report["fade"][k] for k in ("frames_on", "frames_full", "step_without_cuts")},
             "pupil": {k: report["pupil"][k] for k in ("relative", "mm", "steps")}, "seconds": report["seconds"]}
    if a.report:
        short["report"] = os.path.abspath(a.report)
    print(json.dumps(short, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
