"""Move the lights in the eyes, the pupils and the eyes' vergence as a person's do, written as one VMD to load after the
dance, the face and the gaze.

    python tools/eye_optics.py MODEL.pmx DANCE.vmd GAZE.vmd CAMERA.vmd OUT.vmd [--face FACE.vmd] [--look LOOK.json]
                               [--flares S ...] [--audio SONG] [--chorus S ...] [--params P.json] [--report r.json]
                               [--seed 0]

MODEL is the model made by tools/pmx_eyes.py (its catchlight bones); GAZE the 両目 track of tools/eye_gaze.py, merged
over the dance as MMD merges a later motion (its keys replace the dance's on the same bone and frame).  Every frame of
the dance is computed; everything is smooth (the step measures of the report say how much each channel changes in
one frame at most and at the 99th percentile).  The numbers are PARAMS, each replaceable with --params (a JSON of the
same shape; an unknown key is refused).  They are estimates for a human eye until stage 5's research gives its own.

The light (the catchlight bones, keyed in the head's frame, after their append):

* pmx_eyes makes each light follow the gaze (両目) by append with a share k (a human eye's d / d_p = 5.7 / 10.4 =
  0.55, its lag 0.45 scaled by the model's iris: Sour's Rin 0.69; the report's model.share is read back from the
  model).  Turning the eye carries the light only that far.
* The rest of a corneal reflection's motion comes from the light: the light shines where the cornea's normal is the
  half-way direction n between the direction to the light and to the viewer.  The light is MMD's (light.direction,
  the window's numbers: where the light goes; MMD's default -0.5 -1 0.5 comes from above, in front, on her left).  The
  viewer is taken in front of her face (the head's -Z): in the MV the camera keeps to her face (seen from the head it
  lies 13 degrees off the face's forward in the median) and its cuts would make the light jump.  So n depends on the
  head's turn against the light only, and the light moves with the head's speed.  With n0 its direction with the head
  at rest, the light's way on the cornea is r_c (n - n0) (r_c = 7.8 mm, the cornea's radius), which the pupil would
  make turning by r_c / d_p = 0.75 times (n - n0) radians on a human eye, scaled like the share by the model's iris
  (pmx_eyes.model_scale; Sour's Rin 0.52) so that the light crosses the same part of the iris: light.gain, or that
  when it is null.  The bone turns that far (yaw toward +X by gain (n - n0).x, pitch up by gain (n - n0).y; the
  bone's pivot lies the pupil's depth behind the light, pmx_eyes).
* The added turn is held under light.cap degrees (soft: unchanged up to 60 % of it, tanh beyond; at the cap Sour's Rin's
  upper light has moved 0.06 of the iris' 0.16 half width), changed by at most light.max_step degrees a frame (the
  coordinator: no jump over a degree), then smoothed with a 1 4 6 4 1 window (which never steps further).
* Each light also takes the share k of its eye's vergence turn in its key (its append is from 両目, which the
  vergence keys do not turn).
* When n leaves the cornea seen from the eye's line of sight (the cornea's edge lies about 48 degrees off its axis),
  the light fades: the morph HL消 (the HL material's opacity) goes from 0 at light.fade[0] degrees between n and the
  line of sight to 1 at light.fade[1], at most light.fade_step a frame.  With the viewer in front, that is the light
  coming from behind the eye's plane (90 to 110 degrees off the line of sight).

The pupil (morphs 瞳大 and 瞳細 of Sour's Rin: with 瞳1off at 1 the navy pupil; 瞳大 widens it to (1 + 1.73 w) of its
radius, 瞳細 narrows it to (1 - 0.67 w); the factors are measured on the model's own morphs):

* r, the change of the pupil's diameter against the model's own (0 = as the model is made), sums
  - the light reflex at each flare of the MV's look (--look's "flares", seconds, and --flares): after reflex.latency
    the pupil narrows by reflex.amplitude, most narrow reflex.rise ln(1 + 2 redilate / rise) later (0.64 s), and comes
    back with the time constant reflex.redilate (2.4 s: 90 % back in 5.5 s; Pilley & Thompson 1975, 90 % in 5 to 6 s);
    the shape (1 - e^(-t / rise))^2 e^(-t / redilate) starts with no step and no kink.  Overlapping flares add, held
    under reflex.most.
  - arousal: the song's loudness (--audio, RMS read with ffmpeg, 0 at its arousal.low and 1 at its arousal.high
    percentile) followed with arousal.rise on the way up and arousal.fall on the way down, as a share of
    arousal.amplitude about its median (the pupil is the model's own at the song's usual loudness).
  - a dilation at the head of each chorus (--chorus, seconds): the shape of the reflex with chorus.latency, .rise and
    .fall, chorus.amplitude high.
  - the near response: per_dioptre narrower for each dioptre the eyes converge nearer than the free distance (from the
    smoothed vergence).
  - unrest: unrest.waves sines between unrest.low_hz and high_hz with random phases (from --seed), unrest.amplitude
    RMS together.
* r is kept in pupil.range; r > 0 is 瞳大 r / 1.73, r < 0 瞳細 -r / 0.67.

The vergence (keys on 右目 and 左目, after their append from 両目):

* Where the eyes look (fixation_targets): the camera when the gaze (both eyes' mean, in the world) is within
  vergence.camera_deg of it for vergence.camera_frames frames on end; one of her hands (the points vergence.hand_points
  of each side, the nearest to the gaze) when it is within hand_deg of the gaze, between near_m and hand_m away, for
  hand_frames frames on end (the camera wins when it is nearer the gaze for its tolerance); else something free_m away.
* The angle per eye is atan((ipd / 2) / distance) (ipd_mm 61.7, unit_mm 80 to the model unit); it follows its demand
  through a critically damped filter of time constant vergence.time (0.1 s: 10 to 90 % in 0.34 s, no overshoot; the
  coordinator asked for 0.2 to 0.3 s or more), from the frame after the demand changes.  Each eye then turns from the
  gaze onto the point at the smoothed distance along it (right eye -X, left eye +X: inward is +yaw for the right eye
  and -yaw for the left, as the coordinator's vergence probe keys them).

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
BIG, THIN, HIDE = "瞳大", "瞳細", "HL消"
SOFT_FROM = 0.6                 # share of a cap up to which soft_cap passes values unchanged

PARAMS = {
    "light": {
        "gain": None,                        # None: r_c / d_p (pmx_eyes.HUMAN, 0.75) times the model's iris scale
        "cap": 8.0,                          # degrees (a turn of the pupil) the added part keeps under
        "max_step": 1.0,                     # degrees a frame the added part changes at most
        "direction": [-0.5, -1.0, 0.5],      # MMD's light, as its window shows it (where the light goes)
        "fade": [45.0, 55.0],                # degrees between n and the line of sight: HL消 0 .. 1
        "fade_step": 0.06,                   # HL消 a frame at most
    },
    "vergence": {
        "ipd_mm": 61.7,                      # the coordinator's probe (interpupillary distance)
        "unit_mm": 80.0,                     # one model unit
        "free_m": 3.0,                       # what she looks at when not the camera or a hand (estimate)
        "near_m": 0.2,                       # a hand nearer than this is not looked at (estimate)
        "camera_deg": 4.0,                   # tools/eye_gaze.py counts a gaze this near the camera as eye contact
        "camera_frames": 3,
        "hand_deg": 6.0,
        "hand_m": 0.7,
        "hand_frames": 9,
        "hand_points": ["人指３先", "中指３先", "親指２先", "手先"],
        "time": 0.1,                         # seconds: the critically damped filter's time constant
    },
    "pupil": {
        "iris_mm": 11.8,                     # the iris' diameter, to give the pupil in mm
        "reflex": {"amplitude": 0.15, "latency": 0.25, "rise": 0.2, "redilate": 2.4, "most": 0.3},
        "arousal": {"amplitude": 0.06, "rise": 1.0, "fall": 3.0, "low": 10.0, "high": 90.0},
        "chorus": {"amplitude": 0.05, "latency": 0.5, "rise": 0.6, "fall": 3.0},
        "near": {"per_dioptre": 0.03},
        "unrest": {"amplitude": 0.02, "low_hz": 0.05, "high_hz": 0.3, "waves": 6},
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


def _about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def eye_rotation(yaw, pitch):
    """the rotation (as applied, in the head's frame) that turns -Z by yaw toward +X and pitch up (tools/eye_gaze.py)"""
    return fk.multiply(_about((0.0, 1.0, 0.0), -yaw), _about((1.0, 0.0, 0.0), pitch))


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


def damped(values, fps, tau):
    """a critically damped follower (no overshoot) of time constant tau seconds: each frame moves by the exact solution
    toward the demand of the frame before, starting at rest on the first value"""
    if not values:
        return []
    w, dt = 1.0 / tau, 1.0 / fps
    decay = math.exp(-w * dt)
    x, v = float(values[0]), 0.0
    out = [x]
    for u in values[:-1]:
        e = x - u
        b = v + w * e
        x = u + (e + b * dt) * decay
        v = (v - w * b * dt) * decay
        out.append(x)
    return out


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
    """(metres, labels) per frame: what the eyes converge on.  A row is {"camera": (degrees off the gaze, metres),
    "hands": [(degrees off the gaze, metres), ...]}; see the module docstring."""
    p = params
    n = len(rows)
    cam_ok = [r["camera"][0] <= p["camera_deg"] for r in rows]
    hand = []
    for r in rows:
        fit = [h for h in r["hands"] if h[0] <= p["hand_deg"] and p["near_m"] <= h[1] <= p["hand_m"]]
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
    for i in range(n):
        if labels[i] == "camera":
            metres.append(rows[i]["camera"][1])
        elif labels[i] == "hand":
            metres.append(hand[i][1])
        else:
            metres.append(p["free_m"])
    return metres, labels


# ---- the light ------------------------------------------------------------------------------

def toward_light(direction):
    """the unit vector toward MMD's light from the window's direction (where the light goes)"""
    return tuple(-c for c in _unit(direction))


def light_swing(heads, light, gain):
    """per head rotation (as applied, in the world): the turn (yaw toward +X, pitch up; degrees) that moves the light
    as far as the half-way direction between the light and the viewer in front of the face has moved from the head
    at rest, times gain"""
    n0 = _unit(tuple(a + b for a, b in zip(light, FORWARD)))
    out = []
    for q in heads:
        n = _unit(tuple(a + b for a, b in zip(fk.rotate(fk.conjugate(q), light), FORWARD)))
        out.append((math.degrees(gain * (n[0] - n0[0])) + 0.0, math.degrees(gain * (n[1] - n0[1])) + 0.0))
    return out


def _soft(x, cap):
    if x <= SOFT_FROM * cap:
        return x
    span = 1.0 - SOFT_FROM
    return cap * (SOFT_FROM + span * math.tanh((x / cap - SOFT_FROM) / span))


def soft_cap(vec, cap):
    """the vector with its length kept under cap: unchanged up to SOFT_FROM of it, along tanh beyond"""
    n = math.hypot(*vec)
    if n <= SOFT_FROM * cap or n == 0.0:
        return tuple(vec)
    k = _soft(n, cap) / n
    return tuple(c * k for c in vec)


def rate_limited(seq, max_step):
    """the sequence of 2-vectors followed with at most max_step a frame"""
    if not seq:
        return []
    out = [tuple(seq[0])]
    cur = tuple(seq[0])
    for target in seq[1:]:
        d = (target[0] - cur[0], target[1] - cur[1])
        n = math.hypot(*d)
        if n > max_step:
            cur = (cur[0] + d[0] * max_step / n, cur[1] + d[1] * max_step / n)
        else:
            cur = tuple(target)
        out.append(cur)
    return out


def smoothed(seq):
    """a 1 4 6 4 1 window over a sequence of 2-vectors (the ends repeated): a mean of neighbouring values, so no step
    grows"""
    n = len(seq)
    if n == 0:
        return []
    weights = (1.0, 4.0, 6.0, 4.0, 1.0)
    out = []
    for i in range(n):
        acc = [0.0, 0.0]
        for k, w in zip(range(-2, 3), weights):
            v = seq[min(n - 1, max(0, i + k))]
            acc[0] += w * v[0]
            acc[1] += w * v[1]
        out.append((acc[0] / 16.0, acc[1] / 16.0))
    return out


def _smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def fade_track(angles, start, end, step):
    """HL消 per frame: smoothstep from 0 at `start` degrees to 1 at `end`, changed by at most `step` a frame"""
    out = []
    for i, a in enumerate(angles):
        want = _smoothstep((a - start) / (end - start))
        if i:
            want = min(out[-1] + step, max(out[-1] - step, want))
        out.append(want + 0.0)
    return out


# ---- the pupil ------------------------------------------------------------------------------

def reflex_shape(t, rise, fall):
    """(1 - e^(-t / rise))^2 e^(-t / fall) scaled to a peak of 1; 0 at and before t = 0"""
    if t <= 0.0:
        return 0.0
    u = rise / (2.0 * fall + rise)
    peak = (1.0 - u) ** 2 * math.exp(rise * math.log(u) / fall)
    return (1.0 - math.exp(-t / rise)) ** 2 * math.exp(-t / fall) / peak


def _follow(values, rise_frames, fall_frames):
    """a first-order follower with one time constant on the way up and another on the way down"""
    out, x = [], values[0] if values else 0.0
    for v in values:
        k = 1.0 / (rise_frames if v > x else fall_frames)
        x += (v - x) * (1.0 - math.exp(-k))
        out.append(x)
    return out


def _median(values):
    s = sorted(values)
    n = len(s)
    return 0.0 if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def pupil_track(n, flares, arousal, chorus, near, params, seed=0, fps=FPS):
    """the change of the pupil's diameter against the model's own, per frame, with its parts: {"total", "reflex",
    "arousal", "chorus", "near", "unrest"}.  `flares` and `chorus` are frames (floats), `arousal` the loudness per
    frame from 0 to 1 (or None), `near` dioptres nearer than the free distance per frame."""
    p = params
    rx = p["reflex"]
    reflex = [0.0] * n
    for at in flares:
        onset = at + rx["latency"] * fps
        for i in range(max(0, int(math.floor(onset))), n):
            reflex[i] += reflex_shape((i - onset) / fps, rx["rise"], rx["redilate"])
    reflex = [-_soft(rx["amplitude"] * v, rx["most"]) + 0.0 for v in reflex]
    ar = p["arousal"]
    if arousal:
        env = _follow(list(arousal[:n]) + [arousal[-1]] * max(0, n - len(arousal)), ar["rise"] * fps, ar["fall"] * fps)
        mid = _median(env)
        arousal_part = [ar["amplitude"] * (v - mid) for v in env]
    else:
        arousal_part = [0.0] * n
    ch = p["chorus"]
    chorus_part = [0.0] * n
    for at in chorus:
        onset = at + ch["latency"] * fps
        for i in range(max(0, int(math.floor(onset))), n):
            chorus_part[i] += ch["amplitude"] * reflex_shape((i - onset) / fps, ch["rise"], ch["fall"])
    near_part = [-p["near"]["per_dioptre"] * max(0.0, d) for d in near]
    un = p["unrest"]
    rng = random.Random(seed)
    waves = []
    for _ in range(int(un["waves"])):
        waves.append((rng.uniform(un["low_hz"], un["high_hz"]), rng.uniform(0.0, 2.0 * math.pi)))
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


def pupil_scales(doc, big=BIG, thin=THIN, iris_material="瞳"):
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
    for key, name in (("big", big), ("thin", thin)):
        ratios = []
        radii = {}
        for v in morphs[big]:
            p, c = doc.vertices[v].position(), centre[side[v]]
            radii[v] = (p[0] - c[0], p[1] - c[1])
        top = max(math.hypot(*r) for r in radii.values())
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


# ---- measures -------------------------------------------------------------------------------

def _pct(values, q):
    s = sorted(values)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(round(q / 100.0 * (len(s) - 1))))]


def _r(value, places=4):
    return round(float(value), places) + 0.0


def step_stats(values):
    """the change from one frame to the next (the length for vectors): its largest and its 99th percentile"""
    if len(values) < 2:
        return {"max": 0.0, "p99": 0.0}
    if isinstance(values[0], (tuple, list)):
        steps = [math.sqrt(sum((b - a) ** 2 for a, b in zip(u, v))) for u, v in zip(values, values[1:])]
    else:
        steps = [abs(b - a) for a, b in zip(values, values[1:])]
    return {"max": _r(max(steps), 5), "p99": _r(_pct(steps, 99), 5)}


def angle_steps(directions):
    """the angle in degrees between the directions of consecutive frames: its largest and its 99th percentile"""
    if len(directions) < 2:
        return {"max": 0.0, "p99": 0.0}
    steps = [_degrees_between(a, b) for a, b in zip(directions, directions[1:])]
    return {"max": _r(max(steps), 5), "p99": _r(_pct(steps, 99), 5)}


def vmd_name_of(name, motion):
    """the name a motion's keys give the bone `name` (cut to 15 bytes of cp932 as a VMD keeps it)"""
    names = {k.name for k in motion.bones}
    return name if name in names else fk.vmd_name(name)


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


def _catchlights(model, handle, eyes):
    out = []
    for b in model.bones:
        if not (b.name_en or "").startswith(pmx_eyes.EN_PREFIX):
            continue
        if not (b.append and b.append.get("parent") == handle and b.flags.get("append_rotate")):
            raise ValueError("the catchlight bone %s does not turn with %s by append" % (b.name, model.bones[handle].name))
        tag = b.name_en[len(pmx_eyes.EN_PREFIX):].split("_")
        side = tag[1] if len(tag) > 1 else ""
        eye = {v: k for k, v in pmx_eyes.SIDE_EN.items()}.get(side)
        names = {model.bones[e].name: e for e in eyes}
        target = next((n for n in names if eye and n.startswith(eye)), None)
        if target is None:
            raise ValueError("cannot tell which eye the catchlight bone %s (%s) belongs to" % (b.name, b.name_en))
        out.append({"name": b.name, "eye": target, "share": float(b.append["ratio"])})
    if not out:
        raise ValueError("the model has no catchlight bones: make it with tools/pmx_eyes.py first")
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
    head = model.bones[heads.pop()].name
    lights = _catchlights(model, handle, eye_idx)
    scales = pupil_scales(doc)
    names = {b.name for b in model.bones}
    vp = p["vergence"]
    hands = [s + h for s in ("右", "左") for h in vp["hand_points"] if s + h in names]
    motion = merge(dance, gaze)
    if not motion.bones:
        raise ValueError("the dance and the gaze have no bone keys")
    last = max(fk.last_frame(dance), fk.last_frame(gaze))
    frames = list(range(0, last + 1))
    n = len(frames)
    track = fk.world_track(model, motion, [head] + eyes + hands, 0, last)
    cam_keys = fk.camera_keys(camera)
    cam_frames = [k.frame for k in cam_keys]
    unit_m = vp["unit_mm"] / 1000.0
    half = vp["ipd_mm"] / 2.0 / vp["unit_mm"]
    head_rot, gaze_head, rows = [], [], []
    for i in range(n):
        hp, hr = track[head][i]
        inv = fk.conjugate(hr)
        per_eye = [fk.rotate(fk.multiply(inv, track[e][i][1]), FORWARD) for e in eyes]
        g_h = _unit(tuple(a + b for a, b in zip(*per_eye)))
        g_w = fk.rotate(hr, g_h)
        centre = tuple((a + b) / 2.0 for a, b in zip(track[eyes[0]][i][0], track[eyes[1]][i][0]))
        c = fk.camera_position(fk.camera_at(cam_keys, frames[i], cam_frames))
        to_cam = tuple(a - b for a, b in zip(c, centre))
        row = {"camera": (_degrees_between(g_w, to_cam), math.sqrt(_dot(to_cam, to_cam)) * unit_m), "hands": []}
        for h in hands:
            to_hand = tuple(a - b for a, b in zip(track[h][i][0], centre))
            row["hands"].append((_degrees_between(g_w, to_hand), math.sqrt(_dot(to_hand, to_hand)) * unit_m, h))
        rows.append(row)
        head_rot.append(hr)
        gaze_head.append(g_h)
    # vergence
    metres, labels = fixation_targets([{"camera": r["camera"], "hands": [h[:2] for h in r["hands"]]} for r in rows], vp)
    demand = [vergence_degrees(max(m, vp["near_m"]), vp["ipd_mm"]) for m in metres]
    angle = damped(demand, FPS, vp["time"])
    distance = [half / math.tan(math.radians(a)) for a in angle]
    turns = [vergence_turns(g, d, half) for g, d in zip(gaze_head, distance)]
    # the light
    lp = p["light"]
    light = toward_light(lp["direction"])
    iris = pmx_eyes.model_scale(doc)
    gain = lp["gain"] if lp["gain"] is not None else (
        pmx_eyes.HUMAN["cornea_radius"] / pmx_eyes.HUMAN["pupil"] * iris["scale"])
    swing = light_swing(head_rot, light, gain)
    capped = [soft_cap(s, lp["cap"]) for s in swing]
    limited = rate_limited(capped, lp["max_step"])
    added = smoothed(limited)
    added_q = [eye_rotation(y, pt) for y, pt in added]
    side = {e: k for k, e in enumerate(eyes)}
    bone_rot = {}
    for c in lights:
        bone_rot[c["name"]] = [fk.multiply(q, fk.power(t[side[c["eye"]]], c["share"])) for q, t in zip(added_q, turns)]
    # the fade: the half-way direction against each eye's line of sight
    n_dirs = [_unit(tuple(a + b for a, b in zip(fk.rotate(fk.conjugate(q), light), FORWARD))) for q in head_rot]
    off = []
    for i in range(n):
        angles = [_degrees_between(n_dirs[i], fk.rotate(turns[i][k], gaze_head[i])) for k in range(2)]
        off.append(sum(angles) / 2.0)
    hide = fade_track(off, lp["fade"][0], lp["fade"][1], lp["fade_step"])
    # the pupil
    pp = p["pupil"]
    near = [max(0.0, 1.0 / (d * unit_m) - 1.0 / vp["free_m"]) for d in distance]
    flare_frames = [t * FPS - SHOWN for t in flares]
    chorus_frames = [t * FPS - SHOWN for t in chorus]
    pupil = pupil_track(n, flare_frames, arousal, chorus_frames, near, pp, seed)
    big, thin = pupil_weights(pupil["total"], scales["big"], scales["thin"])
    # the motion
    keys = []
    for k, e in enumerate(eyes):
        keys += _bone_keys(e, frames, [t[k] for t in turns])
    for c in lights:
        keys += _bone_keys(c["name"], frames, bone_rot[c["name"]])
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
                          "nearest_m": _r(min(metres[a:b + 1]), 3), "point": best[2],
                          "degrees": _r(max(angle[a:b + 1]), 3)})
    turn_deg = [_angle(t[0]) for t in turns]
    handle_track = fk.tracks_of(motion).get(vmd_name_of(model.bones[handle].name, motion))
    handle_frames = [k.frame for k in handle_track] if handle_track else None
    handle_q = [fk.applied(fk.sample(handle_track, f, handle_frames)[1]) if handle_track else fk.IDENTITY for f in frames]
    first = lights[0]
    bone_dirs = [fk.rotate(fk.multiply(r, fk.power(h, first["share"])), FORWARD)
                 for r, h in zip(bone_rot[first["name"]], handle_q)]
    mm0 = pp["iris_mm"] * scales.get("ratio", 0.25)
    report = {
        "frames": [frames[0], frames[-1]], "seed": seed, "params": p,
        "model": {"head": head, "eyes": eyes, "handle": model.bones[handle].name, "share": lights[0]["share"],
                  "catchlights": lights, "pupil_scales": {k: _r(v, 4) for k, v in scales.items()},
                  "pupil_mm": _r(mm0, 3), "half_ipd_units": _r(half, 5)},
        "vergence": {"labels": counts, "hand_runs": hand_runs, "degrees": summary(angle), "demand": summary(demand),
                     "step": step_stats(angle), "turn_step": step_stats(turn_deg)},
        "light": {"gain": gain, "iris_scale": _r(iris["scale"], 4),
                  "swing": summary([math.hypot(*s) for s in swing]), "added": summary([math.hypot(*a) for a in added]),
                  "at_cap_share": _r(sum(1 for c in capped if math.hypot(*c) >= 0.95 * lp["cap"]) / float(n)),
                  "limited_frames": sum(1 for a, b in zip(capped, limited) if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-9),
                  "added_step": step_stats(added), "bone_step": angle_steps(bone_dirs), "bone": first["name"]},
        "fade": {"angle": summary(off), "frames_on": sum(1 for h in hide if h > 0.0),
                 "frames_half": sum(1 for h in hide if h >= 0.5), "frames_full": sum(1 for h in hide if h >= 0.999),
                 "step": step_stats(hide)},
        "pupil": {"flares_s": list(flares), "chorus_s": list(chorus), "relative": summary(pupil["total"]),
                  "mm": summary([mm0 * (1.0 + r) for r in pupil["total"]]),
                  "parts": {k: {"min": _r(min(v)), "max": _r(max(v))} for k, v in pupil.items() if k != "total"},
                  "steps": {"relative": step_stats(pupil["total"]), BIG: step_stats(big), THIN: step_stats(thin),
                            "mm": step_stats([mm0 * r for r in pupil["total"]])},
                  "weights": {BIG: _r(max(big)), THIN: _r(max(thin))}},
        "keys": {"bones": len(keys), "morphs": len(morphs)},
    }
    return Result(out, report)


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
    half = int(window * rate / 2)
    csum = np.concatenate([[0.0], np.cumsum(x * x)])
    db = np.zeros(n)
    for i in range(n):
        centre = int(round((i + SHOWN) / fps * rate))
        a, b = max(0, centre - half), min(len(x), centre + half)
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
        audio_path=None, chorus=(), params_path=None, report_path=None, seed=0):
    started = time.time()
    check_distinct(model_path, dance_path, gaze_path, camera_path, out_path, face_path, look_path, audio_path, params_path,
                   report_path)
    params = PARAMS
    if params_path:
        with open(params_path, encoding="utf-8") as f:
            params = merge_params(PARAMS, json.load(f))
    else:
        params = merge_params(PARAMS, {})
    all_flares = list(flares)
    if look_path:
        with open(look_path, encoding="utf-8") as f:
            look = json.load(f)
        all_flares = sorted(set(float(t) for t in look.get("flares", [])) | set(float(t) for t in flares))
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
    a = ap.parse_args(argv)
    try:
        report = run(a.model, a.dance, a.gaze, a.camera, a.out, a.face, a.look, a.flares, a.audio, a.chorus, a.params,
                     a.report, a.seed)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    short = {"ok": True, "out": report["out"], "frames": report["frames"], "keys": report["keys"],
             "vergence": {k: report["vergence"][k] for k in ("labels", "degrees", "step")},
             "light": {k: report["light"][k] for k in ("added", "added_step", "bone_step", "at_cap_share")},
             "fade": {k: report["fade"][k] for k in ("frames_on", "frames_full", "step")},
             "pupil": {k: report["pupil"][k] for k in ("relative", "mm", "steps")}, "seconds": report["seconds"]}
    if a.report:
        short["report"] = os.path.abspath(a.report)
    print(json.dumps(short, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
