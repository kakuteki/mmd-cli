"""Make a calm camera motion (.vmd) for a dance motion (.vmd), without MMD.

    python tools/make_camera.py DANCE.vmd OUT_camera.vmd [--analysis a.json] [--report r.json]
                                [--seed N] [--min-shot 180] [--max-shot 480]
    python tools/make_camera.py DANCE.vmd OUT_camera.vmd --song SONG.json [--onsets ONSETS.json] [--handheld 1]
                                [--report r.json] [--seed N]       # cut and moved on the song (音ハメ)

The distributed camera of a dance is often made for a hall and keeps the dancer small.  This tool
writes a camera that keeps the dancer at a comfortable size and moves slowly once per shot (a push
in, a pull out, an orbit or a view from above), each shot 6 to 16 seconds long.  There is no sound to cut
to, so the cuts follow the dance: how strongly the body moves, frame by frame, is measured from the
bone keys, the strong stretches (a chorus) and the quiet ones are told apart, and the shots change
where the strength changes.  The same input and seed give the same output.

How the strength of the motion is measured (analyze):

* For every bone, consecutive keys (sorted by frame) are compared: the rotation changes by the angle
  between the two quaternions (2 acos |q1 . q2|, in radians) and the position by the distance between
  the two positions (model units; the models are about 20 units tall, one unit is roughly 8 cm).
* Each change is spread evenly over the frames between its two keys (a straight move; the real curve
  of the interpolation is ignored) and weighted by the bone.  The rotation weights (ROTATION_WEIGHTS)
  are roughly the length, in model units, of what the bone swings, so a radian of rotation counts as
  the displacement it causes at the far end: the trunk or a leg (about 8 units) moves most of the
  picture, an upper arm (about 7) moves the forearm and the hand, an elbow (about 4) the forearm, the
  head (about 2) only itself, a finger (about 0.5) hardly changes the picture at all, however many
  keys the fingers have.  A translation counts by its length: the center (and the parents that carry
  the whole body) at weight 1, a foot IK at 0.5 because the feet already follow the center.
* The strength of a frame is the sum of these weighted changes over the WINDOW (30) frames around it
  (the motion of that second; a window cut short at either end is scaled up to a full one), so the
  numbers of a slow dance and of a fast one differ by their speed, not by their key count.
* The strong and the quiet stretches (sections) are found on the trend, a TREND_WINDOW (90) frame
  moving average of that strength, with two thresholds at the 35th and 65th percentiles of the trend:
  the state becomes high when the trend rises to the upper threshold and low again when it falls to
  the lower one (hysteresis, so a beat does not flip it).  Each flip gives a candidate cut, placed
  where the trend crossed the middle of the two thresholds on its way to the flip (where the pace
  changed, not the second or two later when the hysteresis confirmed it); the strength of a cut is
  the jump of the trend across it.

How the shots are cut (cut_shots) and what each one does (plan_shots):

* From the start of the dance, a shot ends at the strongest candidate cut that keeps it between
  --min-shot and --max-shot frames (and leaves at least --min-shot for the rest).  When there is none
  in reach, the stretch up to the next clear cut (one at least as strong as the median of all the
  cuts) is divided evenly into as few shots of at most --max-shot as possible and the first of them
  is taken; the rest is planned again from there, so the cut is met on a shot change.  With no clear
  cut ahead the rest of the dance is divided the same way, so a stretch without a change of pace
  still changes camera now and then.  The last shot ends on the last frame of the dance.  --max-shot
  must be at least twice --min-shot, or such a division is not always possible.
* A shot is a peak when at least 60 % of its frames lie in high sections, a valley when at least 60 %
  lie in low ones, and mid otherwise.
* Each shot is one of four kinds, never the same as the shot before: a push in (distance 38 to 32,
  look-at height 13), a pull out (32 to 42, height 13), an orbit (distance 34, Y angle -15 to +15 or
  back, height 12) or a view from above (height 12, X angle +10 which looks down from about head
  height, distance 38 to 36).  No camera sits below the dancer's hips: the first version had a low
  angle (a camera 4 units above the floor looking up), and it looked up into the skirt whenever a turn
  made the skirt flare.  A peak is shot from 6 further away and its orbit swings 22
  degrees; valleys lean to push ins (weight 3 of 6), peaks to pull outs and orbits.  The choice is
  drawn with the seed, so the same seed repeats it; orbits alternate their direction.  A kind whose
  start would hardly differ from the end of the shot before (less than 8 of distance, 10 degrees and
  3 of height: the end of a push in and the start of a pull out) is not drawn either, since such a
  cut reads as a dropped frame.  The view angle is 30, the values are held inside DISTANCE_RANGE,
  HEIGHT_RANGE, ANGLE_X_RANGE and ANGLE_Y_RANGE (Z stays 0), and every shot keeps the dancer from
  below the knees to above the head at both ends (picture_span; the report lists the span).
* The look-at point (the camera's pos) follows the dancer: the x and z of the center bone (with the
  parents that carry it, 全ての親 and グルーブ) interpolated linearly between its keys and averaged
  over LOOK_AT_WINDOW (90) frames, so a step or a hop does not move the camera, at the shot's height.
  A shot has a key every LOOK_AT_STEP (90) frames at most, each looking at that smoothed center; MMD
  moves the point in straight lines between them.  Distance, angles and fov ease over the whole shot
  on one S curve (S_CURVE), cut into a piece per key; the first key of a shot carries the step curve
  (CUT_CURVE), so a render at 60 fps draws nothing between two shots.
* --handheld S (default 0, off) gives the camera the slow sway of a person holding it: on every frame the
  window angles X and Y drift by up to 0.3 * S degrees, the look-at point by 0.03 * S units and the
  distance by 0.1 * S, each a sum of three slow sines (0.13, 0.31 and 0.57 Hz) with phases from the seed.
  The camera then has a key on every frame (straight lines between them, the step curve on each cut).
"""
import argparse
import bisect
import collections
import dataclasses
import json
import math
import os
import random
import sys
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk, motion_edit  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402

FPS = 30
WINDOW = 30                      # frames: the strength of a frame is the motion of the second around it
TREND_WINDOW = 90                # frames: sections are found on a 3 second moving average of the strength
LOW_PERCENTILE, HIGH_PERCENTILE = 35, 65
MIN_SHOT, MAX_SHOT = 180, 480    # frames: 6 to 16 seconds
LEVEL_SHARE = 0.6                # of a shot's frames in high (low) sections to call it a peak (valley)

TYPES = ("push_in", "pull_out", "orbit", "above")
# distance (start, end), height of the look-at point, X angle, Y angle (start, end): the numbers the MMD
# window shows.  Chosen so that the picture (FOV 30, see picture_span) covers the dancer from below the
# knees (height 5) to above the head (21; Rin's head top is at about 19.5, her ribbon at 20.8) at both
# ends of every shot, peaks included, and so that no camera sits below her hips (height 10).
SHOT_VALUES = {
    "push_in": {"distance": (38.0, 32.0), "height": 13.0, "x": 0.0, "y": (0.0, 0.0)},
    "pull_out": {"distance": (32.0, 42.0), "height": 13.0, "x": 0.0, "y": (0.0, 0.0)},
    "orbit": {"distance": (34.0, 34.0), "height": 12.0, "x": 0.0, "y": (-15.0, 15.0)},
    "above": {"distance": (38.0, 36.0), "height": 12.0, "x": 10.0, "y": (0.0, 0.0)},
}
PEAK_DISTANCE_ADD = 6.0
PEAK_ORBIT_SWING = 22.0
TYPE_WEIGHTS = {
    "valley": {"push_in": 3, "pull_out": 1, "orbit": 1, "above": 1},
    "peak": {"push_in": 1, "pull_out": 2, "orbit": 2, "above": 1},
    "mid": {"push_in": 1, "pull_out": 1, "orbit": 1, "above": 1},
}
# a cut must change the picture clearly, or it reads as a dropped frame: at least one of these between the
# end of a shot and the start of the next
CLEAR_CUT = {"distance": 8.0, "angle": 10.0, "height": 3.0}
DISTANCE_RANGE = (24.0, 48.0)
HEIGHT_RANGE = (7.0, 14.0)
ANGLE_X_RANGE = (-10.0, 10.0)
ANGLE_Y_RANGE = (-25.0, 25.0)
FOV = 30
S_CURVE = (64, 0, 64, 127)       # ease in and out over a whole shot, on distance, angles and fov
CUT_CURVE = (127, 0, 127, 0)     # on the first key of a shot: the step, so nothing is drawn between two shots
LOOK_AT_STEP = 90                # frames: at most this far between two keys of a shot (the look-at point follows)
LOOK_AT_WINDOW = 90              # frames: the look-at point is the center averaged over this window

# --handheld: a person holding the camera sways it a little.  Amplitudes at strength 1 (window units:
# degrees, model units); the sway of each channel is a sum of slow sines, so it drifts and never shakes
HANDHELD = {"angle": 0.3, "look_at": 0.03, "distance": 0.1}
SWAY_HZ = (0.13, 0.31, 0.57)
SWAY_WEIGHTS = (0.5, 0.3, 0.2)
SWAY_MAX_HZ = max(SWAY_HZ)

CENTER_BONES = ("全ての親", "センター", "グルーブ")       # the chain that carries the whole body

# (part of the bone name, weight): the first match wins; see the module docstring for the reasoning
ROTATION_WEIGHTS = (
    ("指", 0.5), ("目", 0.2), ("捩", 1.0), ("ＩＫ", 1.0), ("IK", 1.0), ("足首", 1.0), ("手首", 1.5), ("頭", 2.0),
    ("首", 3.0), ("ひじ", 4.0), ("ひざ", 4.0), ("肩", 7.0), ("腕", 7.0), ("足", 8.0),
    ("上半身", 8.0), ("下半身", 8.0), ("センター", 8.0), ("グルーブ", 8.0), ("全ての親", 8.0),
)
DEFAULT_ROTATION_WEIGHT = 1.0
POSITION_WEIGHTS = (("センター", 1.0), ("グルーブ", 1.0), ("全ての親", 1.0), ("ＩＫ", 0.5), ("IK", 0.5))
DEFAULT_POSITION_WEIGHT = 0.5


# ---- the strength of the motion -------------------------------------------------------------

def weight_of(name, table, default):
    for part, weight in table:
        if part in name:
            return weight
    return default


def quat_angle(a, b):
    """the angle in radians between two (x, y, z, w) rotations; q and -q are the same rotation"""
    na = math.sqrt(sum(c * c for c in a))
    nb = math.sqrt(sum(c * c for c in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    dot = abs(sum(x * y for x, y in zip(a, b))) / (na * nb)
    return 2.0 * math.acos(min(1.0, dot))


def tracks_of(motion):
    """bone name -> its keys sorted by frame"""
    tracks = {}
    for key in motion.bones:
        tracks.setdefault(key.name, []).append(key)
    for keys in tracks.values():
        keys.sort(key=lambda k: k.frame)
    return tracks


def _distance(p, q):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q)))


def raw_motion(tracks, last):
    """per frame, the weighted change of all bones spread over the frames between their keys"""
    delta = [0.0] * (last + 2)
    for name, keys in tracks.items():
        w_rot = weight_of(name, ROTATION_WEIGHTS, DEFAULT_ROTATION_WEIGHT)
        w_pos = weight_of(name, POSITION_WEIGHTS, DEFAULT_POSITION_WEIGHT)
        for a, b in zip(keys, keys[1:]):
            span = b.frame - a.frame
            if span <= 0:
                continue
            amount = w_rot * quat_angle(a.rotation, b.rotation) + w_pos * _distance(a.position, b.position)
            if amount == 0.0:
                continue
            rate = amount / span
            delta[a.frame + 1] += rate               # frames a+1 .. b carry the change
            delta[b.frame + 1] -= rate
    out, running = [], 0.0
    for f in range(last + 1):
        running += delta[f]
        out.append(running if running > 1e-12 else 0.0)
    return out


def _prefix(values):
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


def windowed(values, window, scale_to_full):
    """per frame, the sum of `values` over the window centred on it (window // 2 before, the rest after);
    at the ends the window is cut short and, with scale_to_full, scaled up to a full window"""
    n = len(values)
    prefix = _prefix(values)
    before, after = window // 2, window - window // 2
    out = []
    for f in range(n):
        lo, hi = max(0, f - before), min(n, f + after)
        total = prefix[hi] - prefix[lo]
        if scale_to_full and hi - lo < window:
            total *= float(window) / (hi - lo)
        out.append(total)
    return out


def moving_average(values, window):
    n = len(values)
    prefix = _prefix(values)
    before, after = window // 2, window - window // 2
    out = []
    for f in range(n):
        lo, hi = max(0, f - before), min(n, f + after)
        out.append((prefix[hi] - prefix[lo]) / (hi - lo))
    return out


def percentile(values, p):
    """nearest-rank percentile of a list"""
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * p / 100.0))
    return ordered[index]


@dataclasses.dataclass
class Section:
    start: int
    end: int
    level: str                   # "high" or "low"
    mean: float


@dataclasses.dataclass
class Boundary:
    frame: int                   # the first frame of the section that begins here
    strength: float              # the jump of the trend across it


@dataclasses.dataclass
class Analysis:
    last: int                    # the last frame of the dance (the strength has last + 1 entries)
    intensity: List[float]
    trend: List[float]
    thresholds: Dict[str, float]
    sections: List[Section]
    boundaries: List[Boundary]


def find_sections(trend, low, high):
    """runs of high and low state with hysteresis: up at `high`, down at `low`.  A section begins where the
    trend crossed the middle of the two thresholds on its way to the flip, not where the flip was confirmed
    (that is a second or two later).  One section when the thresholds do not leave room between them (a
    flat trend)."""
    n = len(trend)
    if not high > low:
        return [Section(0, n - 1, "high" if trend[0] > 0 else "low", sum(trend) / n)]
    mid = (low + high) / 2.0
    state = "high" if trend[0] >= mid else "low"
    sections, start = [], 0
    for f in range(1, n):
        if state == "low" and trend[f] >= high:
            flip = "high"
        elif state == "high" and trend[f] <= low:
            flip = "low"
        else:
            continue
        cut = f
        while cut - 1 > start and (trend[cut - 1] >= mid if flip == "high" else trend[cut - 1] <= mid):
            cut -= 1
        sections.append(Section(start, cut - 1, state, sum(trend[start:cut]) / (cut - start)))
        state, start = flip, cut
    sections.append(Section(start, n - 1, state, sum(trend[start:]) / (n - start)))
    return sections


def find_boundaries(trend, sections):
    out = []
    for section in sections[1:]:
        f = section.start
        before = trend[max(0, f - TREND_WINDOW):f]
        after = trend[f:f + TREND_WINDOW]
        strength = abs(sum(after) / len(after) - sum(before) / len(before))
        out.append(Boundary(f, strength))
    return out


def analyze(motion):
    """the strength of the motion per frame and its sections (see the module docstring)"""
    tracks = tracks_of(motion)
    frames = [k.frame for k in motion.bones]
    if not frames:
        raise ValueError("the dance has no bone keys")
    last = max(frames)
    if last < 1:
        raise ValueError("the dance has only frame 0: nothing to follow")
    intensity = windowed(raw_motion(tracks, last), WINDOW, True)
    trend = moving_average(intensity, TREND_WINDOW)
    thresholds = {"low": percentile(trend, LOW_PERCENTILE), "high": percentile(trend, HIGH_PERCENTILE)}
    sections = find_sections(trend, thresholds["low"], thresholds["high"])
    return Analysis(last, intensity, trend, thresholds, sections, find_boundaries(trend, sections))


def _r(value):
    return round(float(value), 4) + 0.0


# ---- the shots ------------------------------------------------------------------------------

@dataclasses.dataclass
class Shot:
    index: int
    start: int
    end: int                     # both frames included; the next shot starts at end + 1
    kind: str
    level: str                   # "peak", "valley" or "mid"
    distance: Tuple[float, float]
    height: float
    rot: Tuple[Tuple[float, float, float], Tuple[float, float, float]]     # window degrees, start and end
    pos: Tuple[Tuple[float, float, float], Tuple[float, float, float]]     # the look-at point, start and end
    intensity: Dict[str, float]  # mean and max of the strength over the shot
    cut: str                     # how the end was chosen: "section", "even" or "end"
    track: List[Tuple[int, Tuple[float, float, float]]] = dataclasses.field(default_factory=list)
    # (frame, look-at point) of every key of the shot: start, one every LOOK_AT_STEP frames at most, end


def check_limits(min_shot, max_shot):
    if min_shot < 2:
        raise ValueError("--min-shot needs at least 2 frames, not %r" % (min_shot,))
    if max_shot < 2 * min_shot:
        raise ValueError("--max-shot (%r) must be at least twice --min-shot (%r), or a stretch between one and two "
                         "shots long could not be divided" % (max_shot, min_shot))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def _first_piece(stretch, max_shot):
    """the length of the first of the fewest equal pieces of at most max_shot that make up `stretch`"""
    pieces = -(-stretch // max_shot)
    return -(-stretch // pieces)


def cut_shots(analysis, min_shot=MIN_SHOT, max_shot=MAX_SHOT):
    """(start, end, how) of every shot; see the module docstring"""
    check_limits(min_shot, max_shot)
    last = analysis.last
    strength = {b.frame: b.strength for b in analysis.boundaries}
    clear = sorted(f for f, s in strength.items() if s >= _median(strength.values())) if strength else []
    shots, start = [], 0
    while start <= last:
        remaining = last - start + 1
        # a cut must leave at least min_shot frames for the rest of the dance
        longest = min(max_shot, remaining - min_shot)
        candidates = [f for f in strength if start + min_shot <= f <= start + longest]
        # a clear cut beyond reach that still leaves min_shot frames after it (then it is more than
        # max_shot away, so the stretch up to it divides into pieces between max_shot / 2 and max_shot)
        ahead = [f for f in clear if f > start + longest and last + 1 - f >= min_shot]
        if candidates:
            # the strongest change; the earliest when equal
            frame = min(candidates, key=lambda f: (-strength[f], f))
            end, how = frame - 1, "section"
        elif remaining <= max_shot and not ahead:
            end, how = last, "end"
        else:
            # divide the stretch up to the next clear cut (or the rest) evenly and take its first piece
            end, how = start + _first_piece((ahead[0] if ahead else last + 1) - start, max_shot) - 1, "even"
        shots.append((start, end, how))
        start = end + 1
    return shots


def level_of(analysis, start, end):
    """peak / valley / mid by the share of the shot's frames in high and low sections"""
    frames = end - start + 1
    high = sum(min(end, s.end) - max(start, s.start) + 1 for s in analysis.sections
               if s.level == "high" and s.start <= end and s.end >= start)
    if high >= LEVEL_SHARE * frames:
        return "peak"
    if frames - high >= LEVEL_SHARE * frames:
        return "valley"
    return "mid"


def pick_kind(rng, candidates, level):
    """a weighted draw among `candidates`, from rng.random() alone (the choice is reproducible from the
    seed, whatever the Python version)"""
    weights = [TYPE_WEIGHTS[level][t] for t in candidates]
    r = rng.random() * sum(weights)
    for kind, weight in zip(candidates, weights):
        r -= weight
        if r < 0:
            return kind
    return candidates[-1]


def _clamp(value, bounds):
    return min(max(float(value), bounds[0]), bounds[1])


def shot_values(kind, level, orbit_sign):
    """distance (start, end), height, rot (start, end) of a shot, held inside the ranges"""
    values = SHOT_VALUES[kind]
    add = PEAK_DISTANCE_ADD if level == "peak" else 0.0
    distance = tuple(_clamp(d + add, DISTANCE_RANGE) for d in values["distance"])
    height = _clamp(values["height"], HEIGHT_RANGE)
    x = _clamp(values["x"], ANGLE_X_RANGE)
    if kind == "orbit":
        swing = PEAK_ORBIT_SWING if level == "peak" else abs(values["y"][1])
        y = (-swing * orbit_sign, swing * orbit_sign)
    else:
        y = values["y"]
    rot = tuple((x, _clamp(v, ANGLE_Y_RANGE), 0.0) for v in y)
    return distance, height, rot


def picture_span(distance, height, x_angle, fov=FOV):
    """(bottom, top): the heights the picture covers at the dancer's plane.  The camera sits `distance` from
    the look-at point (at `height`) along a line tilted by the X angle as the window shows it (negative
    looks up), and the picture is `fov` degrees tall.  Checked against the spike's frame 0 render (look-at
    15, distance 25, angles 0: the hem cut at 8.3, the ribbon touching 21.7)."""
    up = math.radians(-x_angle)
    camera_height = height - distance * math.sin(up)
    forward = distance * math.cos(up)
    half = math.radians(fov / 2.0)
    return camera_height + forward * math.tan(up - half), camera_height + forward * math.tan(up + half)


def changes_clearly(before, after):
    """whether a cut from the end values of one shot to the start values of the next reads as a cut:
    (distance, height, (x, y, z)) on both sides, see CLEAR_CUT"""
    (d0, h0, (x0, y0, _)), (d1, h1, (x1, y1, _)) = before, after
    return (abs(d1 - d0) >= CLEAR_CUT["distance"] or abs(h1 - h0) >= CLEAR_CUT["height"]
            or abs(x1 - x0) >= CLEAR_CUT["angle"] or abs(y1 - y0) >= CLEAR_CUT["angle"])


# ---- following the dancer -------------------------------------------------------------------

def center_track(motion):
    """the keys of the bones that carry the body, each as (frames, positions) sorted by frame"""
    tracks = tracks_of(motion)
    out = []
    for name in CENTER_BONES:
        keys = tracks.get(name)
        if keys:
            out.append(([k.frame for k in keys], [k.position for k in keys]))
    return out


def _position_at(frames, positions, frame):
    """linear between the keys; held at the first (last) key before (after) them"""
    i = bisect.bisect_right(frames, frame)
    if i == 0:
        return positions[0]
    if i == len(frames) or frames[i - 1] == frame:
        return positions[i - 1]
    f0, f1 = frames[i - 1], frames[i]
    t = (frame - f0) / float(f1 - f0)
    return tuple(a + (b - a) * t for a, b in zip(positions[i - 1], positions[i]))


def look_at(track, frame, height):
    """the point the camera looks at: the dancer's x and z, at `height`"""
    x = z = 0.0
    for frames, positions in track:
        px, _, pz = _position_at(frames, positions, frame)
        x += px
        z += pz
    return (x + 0.0, float(height), z + 0.0)


def _centered_average(values, window):
    """the mean of the `window` values around each one; the window narrows towards the ends so that it stays
    centred (a window cut short on one side would lean the mean towards the other side)"""
    n = len(values)
    prefix = _prefix(values)
    out = []
    for f in range(n):
        half = min(window // 2, f, n - 1 - f)
        out.append((prefix[f + half + 1] - prefix[f - half]) / (2 * half + 1))
    return out


def smoothed_center(track, last, window=LOOK_AT_WINDOW):
    """(x, z) of the dancer for every frame 0..last, averaged over the `window` frames around each, so a
    step or a hop does not move the camera; at the ends of the dance the average narrows to the frame itself"""
    xs, zs = [], []
    for frame in range(last + 1):
        x, _, z = look_at(track, frame, 0.0)
        xs.append(x)
        zs.append(z)
    return list(zip(_centered_average(xs, window), _centered_average(zs, window)))


def shot_frames(start, end, step=LOOK_AT_STEP):
    """the key frames of a shot: both ends and as few in between as keep them at most `step` apart"""
    length = end - start
    pieces = max(1, int(math.ceil(length / float(step))))
    return [start + int(round(length * i / float(pieces))) for i in range(pieces + 1)]


def plan_shots(motion, min_shot=MIN_SHOT, max_shot=MAX_SHOT, seed=0, analysis=None):
    """the shots of the camera for `motion`: where they are cut, what each does, where it looks"""
    if analysis is None:
        analysis = analyze(motion)
    center = smoothed_center(center_track(motion), analysis.last)
    rng = random.Random(seed)
    shots, previous, orbit_sign = [], None, 1
    for index, (start, end, how) in enumerate(cut_shots(analysis, min_shot, max_shot)):
        level = level_of(analysis, start, end)
        candidates = [t for t in TYPES if previous is None or t != previous.kind]
        if previous is not None:
            # never the same kind twice, and never a cut that hardly changes the picture
            clear = [t for t in candidates if changes_clearly((previous.distance[1], previous.height, previous.rot[1]),
                                                              _start_values(shot_values(t, level, orbit_sign)))]
            candidates = clear or candidates
        kind = pick_kind(rng, candidates, level)
        distance, height, rot = shot_values(kind, level, orbit_sign)
        if kind == "orbit":
            orbit_sign = -orbit_sign
        values = analysis.intensity[start:end + 1]
        track = [(f, (center[f][0] + 0.0, float(height), center[f][1] + 0.0)) for f in shot_frames(start, end)]
        shot = Shot(index, start, end, kind, level, distance, height, rot, (track[0][1], track[-1][1]),
                    {"mean": sum(values) / len(values), "max": max(values)}, how, track)
        shots.append(shot)
        previous = shot
    return shots


def _start_values(values):
    distance, height, rot = values
    return distance[0], height, rot[0]


def analysis_json(analysis):
    """the analysis as plain data for --analysis (ASCII when dumped with ensure_ascii)"""
    return {
        "frames": [0, analysis.last], "fps": FPS, "window": WINDOW, "trend_window": TREND_WINDOW,
        "percentiles": {"low": LOW_PERCENTILE, "high": HIGH_PERCENTILE},
        "weights": {"rotation": [[part, w] for part, w in ROTATION_WEIGHTS] + [["*", DEFAULT_ROTATION_WEIGHT]],
                    "position": [[part, w] for part, w in POSITION_WEIGHTS] + [["*", DEFAULT_POSITION_WEIGHT]]},
        "thresholds": {k: _r(v) for k, v in analysis.thresholds.items()},
        "sections": [{"start": s.start, "end": s.end, "level": s.level, "mean": _r(s.mean)} for s in analysis.sections],
        "boundaries": [{"frame": b.frame, "strength": _r(b.strength)} for b in analysis.boundaries],
        "intensity": [_r(v) for v in analysis.intensity],
        "trend": [_r(v) for v in analysis.trend],
    }


# ---- the camera motion and the report -------------------------------------------------------

def _bezier(curve, t):
    """(x, y) in 0..1 of an MMD curve (x1, y1, x2, y2 in 0..127) at the parameter t, and its tangent"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)
    u = 1.0 - t
    point = (3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3, 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3)
    tangent = (3 * (u * u * x1 + 2 * u * t * (x2 - x1) + t * t * (1.0 - x2)),
               3 * (u * u * y1 + 2 * u * t * (y2 - y1) + t * t * (1.0 - y2)))
    return point, tangent


def _t_at_x(curve, x):
    """the parameter at which the curve's x (the time) is `x`; x grows with t on an MMD curve"""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _bezier(curve, mid)[0][0] < x:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def sub_curve(curve, a, b):
    """the piece of `curve` between the parameters a < b as an MMD curve of its own (its box scaled back to
    0..127), so that pieces played one after the other follow the whole curve.  The piece of a cubic
    Bezier is a cubic Bezier: its inner control points are the ends moved a third of the way along the
    tangents."""
    (p0, t0), (p3, t3) = _bezier(curve, a), _bezier(curve, b)
    span = (b - a) / 3.0
    p1 = (p0[0] + span * t0[0], p0[1] + span * t0[1])
    p2 = (p3[0] - span * t3[0], p3[1] - span * t3[1])
    size = (p3[0] - p0[0], p3[1] - p0[1])

    def scaled(p):
        return tuple(int(round(127.0 * (p[i] - p0[i]) / size[i])) if size[i] > 1e-12 else 0 for i in (0, 1))
    (x1, y1), (x2, y2) = scaled(p1), scaled(p2)
    return (min(max(x1, 0), 127), min(max(y1, 0), 127), min(max(x2, 0), 127), min(max(y2, 0), 127))


def _interpolation(curves):
    """the 24 bytes of a camera key from a curve per channel (x1 x2 y1 y2 each, as vmd.camera_curves reads)"""
    out = []
    for channel in vmd.CAMERA_CHANNELS:
        x1, y1, x2, y2 = vmd.check_curve(curves[channel])
        out += [x1, x2, y1, y2]
    return bytes(out)


def camera_keys(shot):
    """the keys of a shot, from the window values (negative distance and the sign of the X angle are
    motion_edit's business).  The first key sits on the cut with the step curve, so nothing is drawn
    between two shots.  Distance, angles and fov follow the S curve over the whole shot: each later key
    carries the piece of it that leads to that key, and its value is where the S curve is at that frame.
    The look-at point moves in straight lines from key to key (it follows the dancer)."""
    out, length, previous_t = [], float(shot.end - shot.start), 0.0
    last = len(shot.track) - 1
    for i, (frame, pos) in enumerate(shot.track):
        if i == 0:
            t = 0.0
            curves = {channel: CUT_CURVE for channel in vmd.CAMERA_CHANNELS}
        else:
            t = 1.0 if i == last else _t_at_x(S_CURVE, (frame - shot.start) / length)
            piece = sub_curve(S_CURVE, previous_t, t)
            curves = {"x": vmd.LINEAR_CURVE, "y": vmd.LINEAR_CURVE, "z": vmd.LINEAR_CURVE,
                      "rotation": piece, "distance": piece, "fov": piece}
        at = _bezier(S_CURVE, t)[0][1]
        distance = shot.distance[0] + (shot.distance[1] - shot.distance[0]) * at
        rot = tuple(a + (b - a) * at for a, b in zip(shot.rot[0], shot.rot[1]))
        values = {"distance": distance, "pos": pos, "rot": rot, "fov": FOV, "perspective": True}
        key = motion_edit.camera_key_from_ui(values, frame=frame)
        out.append(dataclasses.replace(key, interpolation=_interpolation(curves)))
        previous_t = t
    return out


def sway(channel, frame, seed=0):
    """the handheld sway of one channel at `frame`, from -1 to 1: slow sines (SWAY_HZ, weighted by
    SWAY_WEIGHTS) with phases drawn from the seed, so the same seed sways the same way.  A sum of slow sines
    has no shake: its change from frame to frame is bounded by its slowest-to-fastest frequencies."""
    rng = random.Random(seed * 1009 + channel * 7 + 1)
    total = 0.0
    for hz, weight in zip(SWAY_HZ, SWAY_WEIGHTS):
        total += weight * math.sin(2.0 * math.pi * hz * frame / FPS + 2.0 * math.pi * rng.random())
    return total


def _shot_values_at(shot, frame):
    """distance, look-at point and window angles of a shot at `frame`, as the plain keys draw them: the S
    curve over the whole shot for distance and angles, straight lines between the track's keys for the
    look-at point"""
    length = float(shot.end - shot.start)
    t = _t_at_x(S_CURVE, (frame - shot.start) / length) if length > 0 else 1.0
    at = _bezier(S_CURVE, t)[0][1]
    distance = shot.distance[0] + (shot.distance[1] - shot.distance[0]) * at
    rot = tuple(a + (b - a) * at for a, b in zip(shot.rot[0], shot.rot[1]))
    pos = shot.track[-1][1]
    for (f0, p0), (f1, p1) in zip(shot.track, shot.track[1:]):
        if f0 <= frame <= f1:
            u = (frame - f0) / float(f1 - f0) if f1 > f0 else 0.0
            pos = tuple(a + (b - a) * u for a, b in zip(p0, p1))
            break
    return distance, pos, rot


def handheld_keys(shot, strength, seed):
    """a key on every frame of a shot: the plain camera's values with the sway added (HANDHELD at strength
    1), the step curve on the cut and straight lines between frames"""
    step = _interpolation({c: CUT_CURVE for c in vmd.CAMERA_CHANNELS})
    linear = _interpolation({c: vmd.LINEAR_CURVE for c in vmd.CAMERA_CHANNELS})
    out = []
    for frame in range(shot.start, shot.end + 1):
        distance, pos, rot = _shot_values_at(shot, frame)
        k = [sway(c, frame, seed) * strength for c in range(5)]
        values = {"distance": distance + HANDHELD["distance"] * k[4],
                  "pos": (pos[0] + HANDHELD["look_at"] * k[2], pos[1] + HANDHELD["look_at"] * k[3], pos[2]),
                  "rot": (rot[0] + HANDHELD["angle"] * k[0], rot[1] + HANDHELD["angle"] * k[1], rot[2]),
                  "fov": FOV, "perspective": True}
        key = motion_edit.camera_key_from_ui(values, frame=frame)
        out.append(dataclasses.replace(key, interpolation=step if frame == shot.start else linear))
    return out


def camera_motion(shots, handheld=0.0, seed=0):
    """the camera motion of the shots; with `handheld` above 0 a key on every frame carries the sway"""
    if handheld < 0:
        raise ValueError("--handheld is a strength from 0 (none) up, not %r" % (handheld,))
    if handheld == 0:
        return vmd.Motion.for_camera(cameras=[k for shot in shots for k in camera_keys(shot)])
    return vmd.Motion.for_camera(cameras=[k for shot in shots for k in handheld_keys(shot, handheld, seed)])


def _count(items):
    out = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def shot_json(shot):
    frames = shot.end - shot.start + 1
    return {"index": shot.index, "start": shot.start, "end": shot.end, "frames": frames,
            "seconds": round(frames / float(FPS), 2), "kind": shot.kind, "level": shot.level, "cut": shot.cut,
            "distance": [_r(d) for d in shot.distance], "height": _r(shot.height),
            "rot": [[_r(v) for v in r] for r in shot.rot], "pos": [[_r(v) for v in p] for p in shot.pos],
            "keys": len(shot.track),
            # the heights the picture covers at the dancer, [bottom, top] at the start and at the end
            "picture": [[_r(v) for v in picture_span(shot.distance[i], shot.height, shot.rot[i][0])] for i in (0, 1)],
            "intensity": {k: _r(v) for k, v in shot.intensity.items()}}


def report_json(analysis, shots, seed, min_shot, max_shot):
    return {"seed": seed, "min_shot": min_shot, "max_shot": max_shot, "fps": FPS, "fov": FOV, "curve": list(S_CURVE),
            "cut_curve": list(CUT_CURVE), "look_at_step": LOOK_AT_STEP, "look_at_window": LOOK_AT_WINDOW,
            "frames": [0, analysis.last], "thresholds": {k: _r(v) for k, v in analysis.thresholds.items()},
            "sections": [{"start": s.start, "end": s.end, "level": s.level} for s in analysis.sections],
            "kinds": _count(s.kind for s in shots), "levels": _count(s.level for s in shots),
            "cuts": _count(s.cut for s in shots), "shots": [shot_json(s) for s in shots]}


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


def write_json(path, data, indent):
    write_bytes(path, (json.dumps(data, ensure_ascii=True, indent=indent) + "\n").encode("ascii"))


def check_distinct(*paths):
    """the dance and the files written must all differ, or a slip of the hand writes over the dance (there
    is no way back: the camera is written in its place) or one output over another"""
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, OUT, --analysis and --report must all differ"
                             % (seen[key], path))
        seen[key] = path


# ---- --song: the camera cut and moved on the song -----------------------------------------------------------------------
#
# (2026-10-21, camsync: the requester asked for the camera's cuts and moves to keep time with the song, 音ハメ, and for
# moving shots.)  The song's structure (the MV's song_structure.json: the beat grid, the bars, the sections, the title
# words, the lead the references cut by) and its strong onsets (camera_rhythm.py onsets) are the input, so a new
# recording of the song is a new run.

MUSIC_SHOT_BARS = {"intro": (4, 4, 2), "band": (2,), "verse": (4,), "pre": (4, 2, 2), "chorus": (2, 2, 1, 1, 2),
                   "inter": (2,), "bridge": (4,), "break": (0,), "outro": (4,), "last": (2,), "end": (0,)}
# bars a shot lasts, by the part of the song, taken in turn over the part's bars (0: the whole part is one shot).  The
# chorus cuts about 22 times a minute at 140 BPM (the references cut 24.6 [16.6, 26.3]: typorev), the verse and the
# bridge 9 times, the quiet parts less
MUSIC_PALETTE = {"intro": ("dolly_in", "crane_down", "orbit"), "band": ("orbit", "crane_up", "track"),
                 "verse": ("dolly_in", "track", "dolly_out", "track"), "pre": ("crane_up", "dolly_in", "orbit"),
                 "chorus": ("orbit", "dolly_in", "crane_up", "orbit", "dolly_out", "crane_down"),
                 "inter": ("crane_up", "orbit", "crane_down", "orbit"), "bridge": ("track", "orbit", "dolly_out", "track"),
                 "break": (), "outro": ("dolly_out", "crane_up", "orbit"), "last": ("dolly_in", "orbit"), "end": ()}
# the moves of each part, drawn in turn (never the same twice in a row): slow dollies and tracks in the verse, orbits and
# pushes in the chorus, cranes in the interlude; the break and the end hold still (the song stops there)
MUSIC_ENERGY = {"intro": 0.6, "band": 0.9, "verse": 0.6, "pre": 0.8, "chorus": 1.0, "inter": 0.9, "bridge": 0.6,
                "break": 0.0, "outro": 0.7, "last": 0.9, "end": 0.0}
MUSIC_MOVES = ("dolly_in", "dolly_out", "orbit", "crane_up", "crane_down", "track")
MUSIC_FULL = {"dolly": 9.0,      # units of distance at full energy
              "orbit": 40.0,     # degrees of heading (the window's Y)
              "crane": 12.0,     # degrees of the window's X (the camera rises or sinks round the look-at point)
              "track": 8.0}      # units sideways (the look-at point and the camera together)
# (the first sizes, 7, 30, 10 and 5, moved the picture 58 % of the song against the references' 81 % [80, 84] on the same
# yardstick, camera_rhythm: a track of 5 units over 8 beats shifts the street behind her by about 30 px a second, the
# threshold)
MUSIC_RANGE = {"distance": (31.0, 52.0), "pitch": (4.0, 22.0), "yaw": (-65.0, 65.0), "track": (-5.0, 5.0)}
MUSIC_HEIGHT = 13.0              # the look-at point's height (the picture covers 5 to 21 at the dancer within the ranges)
MUSIC_DISTANCES = {"close": (33.0, 36.0, 39.0), "wide": (40.0, 44.0, 48.0)}
MUSIC_WIDE = ("intro", "verse", "bridge", "outro", "break", "end")
# the quiet parts are shot from further (from 46 or so her feet are in the picture; the first music camera, from 31 to
# 42, showed them on 1.3 % of the frames against 25 % of the camera D before it)
MUSIC_PITCHES = (6.0, 9.0, 12.0)
MUSIC_YAWS = (0.0, 25.0, -25.0, 40.0, -40.0, 12.0, -12.0)
MUSIC_STILL = ("break", "end")
MOVE_BEATS = 8                   # beats a move lasts (4 in a shot of one bar)
MOVE_LEAST = 0.3                 # of its full size: a move that has less room than this is drawn another way
MOVE_TAIL = 2.0                  # beats: this many or more left after a shot's last whole move take one more move of 4
                                 # beats that the next cut cuts into (the camera still moving at the cut), not a stop (the
                                 # 10th build stood still about 51 frames at the end of 13 shots, after a move started on a
                                 # strong onset: the picture moved 73 % of the song against the references' 81 %)
MOVE_OVERRUN = 3                 # frames a move may run past its shot's end (the cut hides them: a cut moved onto a
                                 # flash shortens its shot by 2, and a shot that starts on frame 0 or ends on a cut
                                 # before the beat is a few frames short of its bars; both still move over all of them)
ONSET_DELAY = 3                  # frames: a strong onset this far into the shot's first bar starts the move instead of the cut
STRONG = 4.0                     # z: a strong onset (a04's)
HOOK_REACH = 15                  # frames: no push in this near a title word (the motion graphics' punch is the zoom there)
                                 # or a punch of --punch
CUT_SNAP = 6                     # frames (under half a beat at 140 BPM): a planned cut this near a frame of --cut-on (the
                                 # MV's light flashes: a cut on the flash is strong) moves onto it; farther, a cut is added
                                 # there
DEFAULT_CUT_LEAD = 0.077         # s before the beat a cut falls (the references: typorev, 2.3 frames)
GUARD_RISE_LEAST = 1.0           # degrees: with --guard-report, no crane down where the guard's tilt rises more than this
                                 # (the guard swings the camera up round the look-at point where she spins: a crane down
                                 # there turned into a rise in the first music camera, 2 of 65 moves), and no crane up
                                 # where it falls more than this from its height (after a window of the guard: a crane up
                                 # of the music camera's 5th build ran down for 42 frames at 212.5 s)
MUSIC_CONTACT_PITCHES = (4.0, 5.0)       # degrees the window looks down in a shot that holds an eye contact (--contacts):
                                         # level with her eyes, and its Y on her face's way (facing_at), so that the camera
                                         # stays within the reach of her eyes (eye_gaze's contact zone: 16 degrees sideways,
                                         # 5.3 up and 8.9 down off her head's way, the eccentric wall 14.5) while she dances
MUSIC_CONTACT_TURNS = (12.0, -12.0)      # degrees off her face's way a contact shot takes when its own way does not cut
                                         # clearly from the shot before
MUSIC_CONTACT_MOVES = ("dolly_in", "dolly_out")  # the moves of such a shot: a dolly does not turn the camera round her
MUSIC_CONTACT_LEAST = 90         # frames a shot lasts at least to hold a contact (eye_gaze: a run of 48 frames within reach
                                 # and none 2 frames before or 6 after a cut); the wanted time goes to the nearest such shot
                                 # (the music camera without contacts held none of the 12 of the camera D before it)
FACING_HOLD = 8.0                # degrees either side of its middle her face's way may wander over the frames a contact
                                 # shot is aimed at (steady_facing): the camera on the middle stays within eye_gaze's reach
                                 # (the eyes inside the eccentric wall 14.5 come within 4 of it), with room for her head's pitch
CONTACT_RUN = 48                 # frames: eye_gaze makes a contact of a run within reach this long (its CONTACT_MIN)
CONTACT_CLEAR = (6, 2)           # frames after a cut and before the next with no contact (eye_gaze's CUT_CLEAR, END_CLEAR)
# (contact shots from the front at Y 0 or 12 held 4 of the 12 contacts: her head was 11 to 16 degrees off the camera at
# the median in 7 of the 11 shots; on her mean way round the wanted time, 6: she turned within the shots)
FACING_BONES = ("全ての親", "センター", "グルーブ", "腰", "上半身", "腰椎上部", "上半身2", "胸椎上部", "首", "頭")
# the chain from the root to the head (MMD's standard bones, and the spine bones of the MV's model White_v11_spine,
# 腰椎上部 under 上半身2 and 胸椎上部 under 首, which its dance keys; a bone the dance has no keys for rests): her face's
# way is -Z turned by their key rotations, composed from the root (rotations alone, mmd_cli/fk.py's convention).  On the
# MV's dance it is the way eye_gaze's forward kinematics with the model gives on every frame (0.0 degrees apart; without
# the two spine bones 5.0 at the median and 14.6 at the 90th percentile)


@dataclasses.dataclass
class Move:
    name: str
    start: int
    frames: int
    shape: str                   # "drive": up to pace over a beat, even, and down over a beat; "glide": eases in and out
                                 # over the whole move; "hit": at full pace from a strong onset, easing out
    amount: float                # its size in its channel's unit (signed)
    ramp: float = 0.0            # "drive": the share of the move each ramp takes (a beat)


@dataclasses.dataclass
class MusicShot:
    index: int
    start: int
    end: int
    section: str
    kind: str
    bars: int
    base: Dict[str, float]       # distance, pitch, yaw, track at the cut
    moves: List[Move]
    centre: List[Tuple[float, float]]    # the dancer's smoothed x, z on every frame of the shot
    contact: Optional[List[int]] = None  # a shot that holds a wanted eye contact: the frames her face holds its way over
                                         # (steady_facing), the camera on it (MUSIC_CONTACT_*)


def section_kind(section_id):
    kind = str(section_id).rstrip("0123456789")
    return kind if kind in MUSIC_SHOT_BARS else "verse"


def song_beat_period(song):
    beats = song.get("beats") or []
    if len(beats) < 2:
        raise ValueError("the song has no beat grid (beats)")
    return _median([b - a for a, b in zip(beats, beats[1:])])


def song_parts(song, last, fps=FPS):
    """[(section id, kind, [bar head times in the part], first frame)] of the song up to frame `last`"""
    sections = song.get("sections") or []
    if not sections:
        raise ValueError("the song has no sections")
    lead = float(song.get("cut_lead", DEFAULT_CUT_LEAD))
    heads = []
    for s in sections:
        t = float(s["t"]) if s.get("t") is not None else float(s["frame"]) / fps
        heads.append((s["id"], t))
    bars = [float(b) for b in (song.get("bars") or [])]
    if not bars:
        period = song_beat_period(song)
        per = int(song.get("beat", {}).get("per_bar", 4)) if isinstance(song.get("beat"), dict) else 4
        bars = [b for b in song["beats"][::per]]
    out = []
    for i, (sid, t0) in enumerate(heads):
        t1 = heads[i + 1][1] if i + 1 < len(heads) else float("inf")
        first = 0 if i == 0 else int(round((t0 - lead) * fps))
        if first > last:
            break
        inside = [b for b in bars if t0 - 0.02 <= b < t1 - 0.02]
        if not inside or abs(inside[0] - t0) > 0.02:
            inside = [t0] + inside
        out.append((sid, section_kind(sid), inside, first))
    return out


def _move_channel(name):
    return {"dolly_in": "dolly", "dolly_out": "dolly", "orbit": "orbit", "crane_up": "crane", "crane_down": "crane",
            "track": "track"}[name]


def _shape(name, t, ramp=0.125):
    """the share of a move done at the share t of its time: "hit" 1 - (1 - t)^3 (its pace highest at the start),
    "glide" the smoothstep, "drive" a cosine ramp up over `ramp`, an even pace, a cosine ramp down over `ramp`"""
    t = min(max(t, 0.0), 1.0)
    if name == "hit":
        return 1.0 - (1.0 - t) ** 3
    if name == "glide":
        return t * t * (3.0 - 2.0 * t)
    r = min(max(ramp, 1e-6), 0.5)
    v = 1.0 / (1.0 - r)

    def up(u):
        return v * (u / 2.0 - r / (2.0 * math.pi) * math.sin(math.pi * u / r))
    if t <= r:
        return up(t)
    if t >= 1.0 - r:
        return 1.0 - up(1.0 - t)
    return v * (r / 2.0 + (t - r))


def _room(name, values, energy, rng_sign):
    """the signed amount a move can take from `values` within MUSIC_RANGE (its full size times the part's energy)"""
    full = MUSIC_FULL[_move_channel(name)] * energy
    if name == "dolly_in":
        return -min(full, values["distance"] - MUSIC_RANGE["distance"][0])
    if name == "dolly_out":
        return min(full, MUSIC_RANGE["distance"][1] - values["distance"])
    if name == "crane_up":
        return min(full, MUSIC_RANGE["pitch"][1] - values["pitch"])
    if name == "crane_down":
        return -min(full, values["pitch"] - MUSIC_RANGE["pitch"][0])
    if name == "orbit":
        lo, hi = MUSIC_RANGE["yaw"]
        room = hi - values["yaw"] if rng_sign > 0 else values["yaw"] - lo
        if room < full * MOVE_LEAST:
            rng_sign = -rng_sign
            room = hi - values["yaw"] if rng_sign > 0 else values["yaw"] - lo
        return rng_sign * min(full, room)
    lo, hi = MUSIC_RANGE["track"]
    room = hi - values["track"] if rng_sign > 0 else values["track"] - lo
    if room < full * MOVE_LEAST:
        rng_sign = -rng_sign
        room = hi - values["track"] if rng_sign > 0 else values["track"] - lo
    return rng_sign * min(full, room)


def _apply(values, move, frame):
    """the values at `frame` after `move` (values: at the move's start)"""
    out = dict(values)
    if frame <= move.start:
        return out
    k = _shape(move.shape, (frame - move.start) / float(move.frames), move.ramp)
    channel = _move_channel(move.name)
    key = {"dolly": "distance", "orbit": "yaw", "crane": "pitch", "track": "track"}[channel]
    out[key] = values[key] + move.amount * k
    return out


def _end_values(values, move):
    return _apply(values, move, move.start + move.frames)


def _near_hook(start, frames, hooks):
    return any(start - HOOK_REACH <= h <= start + frames + HOOK_REACH for h in hooks)


def _against_guard(name, rising, start, frames):
    """whether the guard's tilt of a first pass (degrees per frame) swings against a crane over its frames by more than
    GUARD_RISE_LEAST: up from its lowest so far under a crane down, down from its highest so far under a crane up"""
    if rising is None or name not in ("crane_up", "crane_down"):
        return False
    span = rising[max(0, start):min(len(rising), start + frames + 1)]
    if not span:
        return False
    worst, low, high = 0.0, span[0], span[0]
    for v in span:
        low, high = min(low, v), max(high, v)
        worst = max(worst, v - low if name == "crane_down" else high - v)
    return worst > GUARD_RISE_LEAST


def facing_chain(motion):
    """the keys of FACING_BONES the dance has, root first, each as (keys sorted by frame, their frames)"""
    tracks = fk.tracks_of(motion)
    return [(tracks[n], [k.frame for k in tracks[n]]) for n in FACING_BONES if n in tracks]


def facing_at(chain, frame):
    """her face's way at `frame` as the window's Y of a camera on it (degrees; Y positive swings the camera to +X, her
    left): -Z turned by the chain's key rotations as MMD shows them there (fk.sample), composed from the root"""
    q = fk.IDENTITY
    for keys, frames in chain:
        q = fk.multiply(q, fk.applied(fk.sample(keys, frame, frames)[1]))
    x, _, z = fk.rotate(q, (0.0, 0.0, -1.0))
    return math.degrees(math.atan2(x, -z))


def steady_facing(chain, first, last, wanted, hold=FACING_HOLD, least=CONTACT_RUN):
    """(a, b, way): of the frames from `first` to `last`, the span over which her face's way stays within `hold` degrees
    either side of its middle: of the spans `least` frames long or longer the one nearest a wanted frame (the longest
    of those that hold one), else the longest; and her mean way over it (the window's Y of a camera on it)"""
    if last < first:
        raise ValueError("no frames to aim a contact shot at (%d to %d)" % (first, last))
    ways = []
    for f in range(first, last + 1):
        v = facing_at(chain, f)
        ways.append(v if not ways else ways[-1] + ((v - ways[-1] + 180.0) % 360.0 - 180.0))   # unwrapped
    n = len(ways)
    spans, lo, hi, j = [], collections.deque(), collections.deque(), 0
    for i in range(n):
        if j <= i:
            j = i
            lo.clear()
            hi.clear()
        while j < n:
            low = min(ways[lo[0]], ways[j]) if lo else ways[j]
            high = max(ways[hi[0]], ways[j]) if hi else ways[j]
            if high - low > 2.0 * hold:
                break
            while lo and ways[lo[-1]] >= ways[j]:
                lo.pop()
            lo.append(j)
            while hi and ways[hi[-1]] <= ways[j]:
                hi.pop()
            hi.append(j)
            j += 1
        spans.append((i, j - 1))
        if lo and lo[0] == i:
            lo.popleft()
        if hi and hi[0] == i:
            hi.popleft()

    def gap(span):
        a, b = first + span[0], first + span[1]
        return min((0 if a <= w <= b else min(abs(w - a), abs(w - b))) for w in wanted) if wanted else 0
    long_ = [s for s in spans if s[1] - s[0] + 1 >= least]
    if long_:
        a, b = min(long_, key=lambda s: (gap(s), s[0] - s[1], s[0]))
    else:
        a, b = min(spans, key=lambda s: (s[0] - s[1], s[0]))
    way = sum(ways[a:b + 1]) / float(b - a + 1)
    return first + a, first + b, (way + 180.0) % 360.0 - 180.0


def contact_shots(spans, contacts, fps=FPS):
    """{index: [the wanted frames it holds]} of the shots ((first, last) frames each) that hold the wanted eye contacts
    (seconds): for each, the nearest shot of MUSIC_CONTACT_LEAST frames or more (the one it falls in when that one is
    long enough)"""
    held = {}
    for t in contacts or []:
        c = int(round(float(t) * fps))
        best = None
        for index, (a, b) in enumerate(spans):
            if b - a + 1 < MUSIC_CONTACT_LEAST:
                continue
            gap = 0 if a <= c <= b else min(abs(c - a), abs(c - b))
            if best is None or gap < best[0]:
                best = (gap, index)
        if best is not None:
            held.setdefault(best[1], []).append(c)
    return held


def cuts_on(cuts, frames, last, bar_frames):
    """the cuts ((frame, section id, kind, bars) each) with a cut on each of `frames` (the MV's light flashes): the
    nearest cut within CUT_SNAP moves onto it, else the shot that holds it is split there (each part keeps its part
    of the song and counts its own bars)"""
    cuts = list(cuts)
    for f in sorted({int(v) for v in frames or []}):
        if not 0 < f <= last or not cuts:
            continue
        i = min(range(len(cuts)), key=lambda k: abs(cuts[k][0] - f))
        if abs(cuts[i][0] - f) <= CUT_SNAP and (i == 0 or cuts[i - 1][0] < f) and (i + 1 == len(cuts) or f < cuts[i + 1][0]):
            cuts[i] = (f,) + tuple(cuts[i][1:])
            continue
        j = max(k for k in range(len(cuts)) if cuts[k][0] < f)
        frame, sid, kind, nbars = cuts[j]
        end = cuts[j + 1][0] if j + 1 < len(cuts) else last + 1
        first_bars = max(1, int(round((f - frame) / bar_frames)))
        cuts[j] = (frame, sid, kind, first_bars)
        cuts.insert(j + 1, (f, sid, kind, max(1, int(round((end - f) / bar_frames)))))
    return cuts


def plan_music_shots(motion, song, onsets, seed=0, last=None, strong=STRONG, rising=None, contacts=None, cut_on=None,
                     punches=None):
    """the shots of the camera on the song (see the module's docstring and MUSIC_*): cuts on the bars CUT_LEAD before
    the beat, each shot moving in whole beats from its cut or from a strong onset in its first bars.  `rising`: the
    tilt per frame operator_camera guard gave a first pass (degrees): no crane down where it rises.  `contacts`: the
    times (seconds) an eye contact is wanted: the shot holding each looks at her from the front and level with her eyes,
    and only dollies (MUSIC_CONTACT_*).  `cut_on`: frames a cut falls on (cuts_on); `punches`: frames of the motion
    graphics' punches, no push in near them (HOOK_REACH, as the title words)"""
    fps = float(song.get("fps", FPS))
    if last is None:
        last = max((k.frame for k in motion.bones), default=0)
    lead = float(song.get("cut_lead", DEFAULT_CUT_LEAD))
    period = song_beat_period(song)
    beat_frames = period * fps
    hooks = [int(h["frame"]) if h.get("frame") is not None else int(round(float(h["t"]) * fps)) for h in song.get("hooks") or []]
    hooks += [int(p) for p in punches or []]
    strong_frames = sorted(int(round(float(o["t"]) * fps)) for o in onsets or [] if float(o.get("z", 0.0)) >= strong)
    centre = smoothed_center(center_track(motion), last)
    rng = random.Random(seed)
    parts = song_parts(song, last, fps)
    # the cuts: each part's bars taken in turn by its pattern
    cuts = []                                   # (frame, section id, kind, bars)
    for (sid, kind, bars, first) in parts:
        pattern = MUSIC_SHOT_BARS[kind]
        i, k = 0, 0
        while i < len(bars):
            n = pattern[k % len(pattern)]
            n = len(bars) - i if n == 0 else min(n, len(bars) - i)
            frame = first if i == 0 else int(round((bars[i] - lead) * fps))
            cuts.append((frame, sid, kind, n))
            i += n
            k += 1
    cuts = cuts_on([c for c in cuts if c[0] <= last], cut_on, last, 4.0 * beat_frames)
    spans = [(frame, cuts[index + 1][0] - 1 if index + 1 < len(cuts) else last) for index, (frame, _, _, _) in enumerate(cuts)]
    held = contact_shots(spans, contacts, fps)
    chain = facing_chain(motion) if held else []
    shots, previous_end, palette_at = [], None, {}
    for index, (frame, sid, kind, nbars) in enumerate(cuts):
        end = spans[index][1]
        if end < frame:
            continue
        contact = None
        # the values at the cut: a clear change from the shot before (CLEAR_CUT), drawn with the seed
        own = MUSIC_DISTANCES["wide" if kind in MUSIC_WIDE else "close"]
        if index in held:
            # on her face's way and level with her eyes; failing a clear cut, the other distances, then 12 degrees off
            first, final = frame + CONTACT_CLEAR[0], end - CONTACT_CLEAR[1]
            a, b, way = steady_facing(chain, *((first, final) if final >= first else (frame, end)), held[index])
            contact, way = [a, b], round(_clamp(way, MUSIC_RANGE["yaw"]), 1)
            other = MUSIC_DISTANCES["close" if kind in MUSIC_WIDE else "wide"]
            turned = tuple(round(_clamp(way + t, MUSIC_RANGE["yaw"]), 1) for t in MUSIC_CONTACT_TURNS)
            options = [(own, MUSIC_CONTACT_PITCHES, (way,)), (other, MUSIC_CONTACT_PITCHES, (way,)),
                       (own + other, MUSIC_CONTACT_PITCHES, turned)]
        else:
            way = 0.0
            options = [(own, MUSIC_PITCHES, MUSIC_YAWS)]
        choices = []
        for distances, pitches, yaws in options:
            for d in distances:
                for p in pitches:
                    for y in yaws:
                        base = {"distance": d, "pitch": p, "yaw": y, "track": 0.0}
                        if previous_end is None or changes_clearly(
                                (previous_end["distance"], MUSIC_HEIGHT, (previous_end["pitch"], previous_end["yaw"], 0.0)),
                                (d, MUSIC_HEIGHT, (p, y, 0.0))):
                            choices.append(base)
            if choices:
                break
        fallback = {"distance": 36.0, "pitch": MUSIC_CONTACT_PITCHES[-1] if contact else 6.0, "yaw": way, "track": 0.0}
        base = dict(choices[int(rng.random() * len(choices))] if choices else fallback)
        moves = []
        if kind not in MUSIC_STILL:
            palette = MUSIC_CONTACT_MOVES if contact else MUSIC_PALETTE[kind]
            energy = MUSIC_ENERGY[kind]
            beats = MOVE_BEATS if nbars >= 2 else 4
            frames_of = int(round(beats * beat_frames))
            start = frame
            shape = "hit" if (kind == "chorus" and nbars == 1) else "drive"
            values = dict(base)
            previous_name = None
            while (start + int(round(4 * beat_frames)) <= end + MOVE_OVERRUN if not moves
                   else (end + 1 + MOVE_OVERRUN - start) / beat_frames >= MOVE_TAIL):
                if start + frames_of > end + MOVE_OVERRUN:
                    frames_of = int(round(4 * beat_frames))
                # a strong onset in the first two beats of the slot starts the move ("hit"), when the move still fits
                for f in strong_frames:
                    if not (start + ONSET_DELAY <= f < start + int(round(2 * beat_frames))):
                        continue
                    fitted = [b for b in (frames_of / beat_frames, 4) if f + int(round(b * beat_frames)) <= end + MOVE_OVERRUN]
                    if fitted:
                        start, frames_of, shape = f, int(round(fitted[0] * beat_frames)), "hit"
                    break
                turn = "contact" if contact else kind
                order = palette_at.get(turn, 0)
                chosen = None
                for j in range(len(palette)):
                    name = palette[(order + j) % len(palette)]
                    if name == previous_name:
                        continue
                    if name == "dolly_in" and _near_hook(start, frames_of, hooks):
                        continue
                    if _against_guard(name, rising, start, frames_of):
                        continue
                    amount = _room(name, values, energy, 1 if rng.random() < 0.5 else -1)
                    if abs(amount) >= MUSIC_FULL[_move_channel(name)] * energy * MOVE_LEAST:
                        chosen = (name, amount)
                        palette_at[turn] = order + j + 1
                        break
                if chosen is None:
                    break
                move = Move(chosen[0], start, frames_of, shape, round(chosen[1], 4), round(beat_frames / frames_of, 4))
                moves.append(move)
                values = _end_values(values, move)
                previous_name = chosen[0]
                # the next move from the next bar head after this one ends (on the beat)
                nxt = start + frames_of
                beats_left = (end + 1 + MOVE_OVERRUN - nxt) / beat_frames
                if beats_left < MOVE_TAIL:
                    break
                start, shape = nxt, "drive"
                frames_of = int(round((MOVE_BEATS if beats_left >= MOVE_BEATS else 4) * beat_frames))
        track = [centre[f] for f in range(frame, end + 1)]
        shot = MusicShot(len(shots), frame, end, sid, kind, nbars, base, moves, track, contact)
        shots.append(shot)
        previous_end = music_shot_values(shot)[-1]
    return shots


def music_shot_values(shot):
    """the camera's window values on every frame of a shot: distance, pitch, yaw, track (and pos, rot, offset)"""
    out = []
    for f in range(shot.start, shot.end + 1):
        values = dict(shot.base)
        for m in shot.moves:
            if f <= m.start:
                break
            values = _apply(values, m, min(f, m.start + m.frames))
        yaw = math.radians(values["yaw"])
        ox, oz = values["track"] * math.cos(yaw), values["track"] * math.sin(yaw)
        cx, cz = shot.centre[f - shot.start]
        values = dict(values, pos=(cx + ox, MUSIC_HEIGHT, cz + oz), rot=(values["pitch"], values["yaw"], 0.0),
                      offset=(ox, oz))
        out.append(values)
    return out


def music_values(shots, last):
    out = []
    for s in shots:
        out += music_shot_values(s)
    return out[:last + 1]


def music_keys(shot, strength, seed):
    step = _interpolation({c: CUT_CURVE for c in vmd.CAMERA_CHANNELS})
    linear = _interpolation({c: vmd.LINEAR_CURVE for c in vmd.CAMERA_CHANNELS})
    out = []
    for i, v in enumerate(music_shot_values(shot)):
        frame = shot.start + i
        k = [sway(c, frame, seed) * strength for c in range(5)] if strength > 0 else [0.0] * 5
        values = {"distance": v["distance"] + HANDHELD["distance"] * k[4],
                  "pos": (v["pos"][0] + HANDHELD["look_at"] * k[2], v["pos"][1] + HANDHELD["look_at"] * k[3], v["pos"][2]),
                  "rot": (v["rot"][0] + HANDHELD["angle"] * k[0], v["rot"][1] + HANDHELD["angle"] * k[1], 0.0),
                  "fov": FOV, "perspective": True}
        key = motion_edit.camera_key_from_ui(values, frame=frame)
        out.append(dataclasses.replace(key, interpolation=step if frame == shot.start else linear))
    return out


def music_motion(shots, last, handheld=0.0, seed=0):
    """the camera motion of the music shots: a key on every frame, the step on every cut, the sway with `handheld`"""
    if handheld < 0:
        raise ValueError("--handheld is a strength from 0 (none) up, not %r" % (handheld,))
    keys = [k for s in shots for k in music_keys(s, handheld, seed) if k.frame <= last]
    return vmd.Motion.for_camera(cameras=keys)


def music_shot_json(shot):
    frames = shot.end - shot.start + 1
    values = music_shot_values(shot)
    return {"index": shot.index, "start": shot.start, "end": shot.end, "frames": frames, "seconds": round(frames / float(FPS), 2),
            "section": shot.section, "kind": shot.kind, "bars": shot.bars, "contact": shot.contact,
            "base": {k: _r(v) for k, v in shot.base.items()},
            "moves": [{"name": m.name, "start": m.start, "frames": m.frames, "shape": m.shape, "amount": _r(m.amount),
                       "ramp": m.ramp} for m in shot.moves],
            "picture": [[_r(v) for v in picture_span(values[i]["distance"], MUSIC_HEIGHT, values[i]["pitch"])] for i in (0, -1)]}


def load_contacts(path, fps=FPS):
    """the wanted eye contacts (seconds) from a JSON file: a list of seconds, {"contacts": [seconds]}, or the report of
    eye_gaze (its contacts' first and last frames: the middle of each)"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("contacts")
        if isinstance(data, dict):
            data = data.get("list")
    if not isinstance(data, list):
        raise ValueError("%s: no list of contacts (a list of seconds, {\"contacts\": [...]} or eye_gaze's report)" % path)
    out = []
    for c in data:
        if isinstance(c, dict):
            out.append((float(c["first"]) + float(c["last"])) / 2.0 / fps)
        else:
            out.append(float(c))
    return out


def run_music(dance_path, out_path, song_path, onsets_path=None, seed=0, handheld=0.0, report_path=None, strong=STRONG,
              guard_report=None, contacts_path=None, cut_on=None, punches=None):
    if handheld < 0:
        raise ValueError("--handheld is a strength from 0 (none) up, not %r" % (handheld,))
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, song_path, onsets_path, report_path, guard_report, contacts_path)
    contacts = load_contacts(contacts_path) if contacts_path else None
    motion = vmd.load(dance_full)
    with open(song_path, encoding="utf-8") as f:
        song = json.load(f)
    onsets = []
    if onsets_path:
        with open(onsets_path, encoding="utf-8") as f:
            data = json.load(f)
        onsets = data["onsets"] if isinstance(data, dict) else data
    last = max((k.frame for k in motion.bones), default=0)
    if last < 1:
        raise ValueError("the dance has no bone keys")
    rising = None
    if guard_report:
        with open(guard_report, encoding="utf-8") as f:
            rising = [float(v) for v in json.load(f)["per_frame"]["tilt"]]
    shots = plan_music_shots(motion, song, onsets, seed, last, strong, rising, contacts, cut_on, punches)
    write_bytes(out_full, vmd.dumps(music_motion(shots, last, handheld, seed)))
    back = vmd.load(out_full)
    moves = [m for s in shots for m in s.moves]
    result = {"in": dance_full, "out": out_full, "song": os.path.abspath(song_path), "seed": seed, "frames": [0, last],
              "shots": len(shots), "keys": len(back.cameras), "moves": _count(m.name for m in moves),
              "handheld": handheld, "cuts_per_min": round((len(shots) - 1) / ((last + 1) / float(FPS) / 60.0), 3),
              "contact_shots": sum(1 for s in shots if s.contact)}
    if report_path:
        full = os.path.abspath(report_path)
        write_json(full, {"in": dance_full, "out": out_full, "seed": seed, "fps": FPS, "fov": FOV, "handheld": handheld,
                          "song": {"path": os.path.abspath(song_path), "cut_lead": float(song.get("cut_lead", DEFAULT_CUT_LEAD)),
                                   "beat_period": _r(song_beat_period(song)), "onsets": os.path.abspath(onsets_path) if onsets_path else None,
                                   "strong": strong, "hooks": [h.get("frame") for h in song.get("hooks") or []],
                                   "version": song.get("version")},
                          "cut_on": sorted(int(v) for v in cut_on or []), "cut_snap": CUT_SNAP,
                          "punches": sorted(int(v) for v in punches or []),
                          "shot_bars": {k: list(v) for k, v in MUSIC_SHOT_BARS.items()},
                          "palette": {k: list(v) for k, v in MUSIC_PALETTE.items()}, "energy": MUSIC_ENERGY,
                          "full": MUSIC_FULL, "range": {k: list(v) for k, v in MUSIC_RANGE.items()}, "move_beats": MOVE_BEATS,
                          "distances": {k: list(v) for k, v in MUSIC_DISTANCES.items()}, "wide": list(MUSIC_WIDE),
                          "hook_reach": HOOK_REACH, "moves": _count(m.name for m in moves),
                          "contacts": {"path": os.path.abspath(contacts_path) if contacts_path else None,
                                       "wanted": [_r(t) for t in contacts or []], "least": MUSIC_CONTACT_LEAST,
                                       "pitches": list(MUSIC_CONTACT_PITCHES), "turns": list(MUSIC_CONTACT_TURNS),
                                       "moves": list(MUSIC_CONTACT_MOVES), "hold": FACING_HOLD, "run": CONTACT_RUN, "clear": list(CONTACT_CLEAR),
                                       "facing_bones": list(FACING_BONES), "shots": [s.index for s in shots if s.contact]},
                          "shots": [music_shot_json(s) for s in shots]}, 1)
        result["report"] = full
    return result


def run(dance_path, out_path, seed=0, min_shot=MIN_SHOT, max_shot=MAX_SHOT, analysis_path=None, report_path=None,
        handheld=0.0):
    """read the dance, plan, write the camera, read it back; the summary is what main prints"""
    check_limits(min_shot, max_shot)
    if handheld < 0:
        raise ValueError("--handheld is a strength from 0 (none) up, not %r" % (handheld,))
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, analysis_path, report_path)
    motion = vmd.load(dance_full)
    analysis = analyze(motion)
    shots = plan_shots(motion, min_shot, max_shot, seed, analysis)
    write_bytes(out_full, vmd.dumps(camera_motion(shots, handheld, seed)))
    back = vmd.load(out_full)
    result = {"in": dance_full, "out": out_full, "seed": seed, "min_shot": min_shot, "max_shot": max_shot,
              "frames": [0, analysis.last], "shots": len(shots), "keys": len(back.cameras),
              "key_frames": [back.cameras[0].frame, back.cameras[-1].frame],
              "kinds": _count(s.kind for s in shots), "levels": _count(s.level for s in shots), "handheld": handheld}
    if analysis_path:
        full = os.path.abspath(analysis_path)
        write_json(full, dict({"in": dance_full}, **analysis_json(analysis)), None)
        result["analysis"] = full
    if report_path:
        full = os.path.abspath(report_path)
        write_json(full, dict({"in": dance_full, "out": out_full}, **report_json(analysis, shots, seed, min_shot, max_shot)), 1)
        result["report"] = full
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd with bone keys)")
    p.add_argument("out", help="the camera motion to write (.vmd)")
    p.add_argument("--analysis", help="write the strength per frame, the sections and the thresholds to this JSON")
    p.add_argument("--report", help="write the list of shots to this JSON")
    p.add_argument("--seed", type=int, default=0, help="the draw of the shot kinds (default 0)")
    p.add_argument("--min-shot", type=int, default=MIN_SHOT, help="shortest shot in frames (default %d)" % MIN_SHOT)
    p.add_argument("--max-shot", type=int, default=MAX_SHOT,
                   help="longest shot in frames (default %d; at least twice --min-shot)" % MAX_SHOT)
    p.add_argument("--handheld", type=float, default=0.0,
                   help="a slow handheld sway: 0 none (default), 1 about 0.3 degrees, keys on every frame")
    p.add_argument("--song", help="cut and move on the song: its structure (beats, bars, sections, title words, cut_lead) "
                                  "as the MV's song_structure.json; --min-shot, --max-shot and --analysis are not used")
    p.add_argument("--onsets", help="with --song: the strong onsets (tools/camera_rhythm.py onsets) a move may start on")
    p.add_argument("--strong", type=float, default=STRONG, help="with --song: the least z of a strong onset (default %g)" % STRONG)
    p.add_argument("--guard-report", help="with --song: the report of operator_camera guard on a first pass: no crane down "
                                          "where the guard raises the camera")
    p.add_argument("--cut-on", type=int, nargs="+", default=[], metavar="FRAME",
                   help="with --song: frames a cut falls on (the MV's light flashes): the nearest cut within %d frames moves "
                        "onto each, else a cut is added there" % CUT_SNAP)
    p.add_argument("--punch", type=int, nargs="+", default=[], metavar="FRAME",
                   help="with --song: frames of the motion graphics' punches: no push in within %d frames of them" % HOOK_REACH)
    p.add_argument("--contacts", help="with --song: the eye contacts wanted, a JSON list of seconds or the report of eye_gaze "
                                      "(its contacts): the shot holding each looks at her from the front, level, and only dollies")
    args = p.parse_args(argv)
    try:
        if args.song:
            result = run_music(args.dance, args.out, args.song, args.onsets, args.seed, args.handheld, args.report, args.strong,
                               args.guard_report, args.contacts, args.cut_on, args.punch)
        else:
            result = run(args.dance, args.out, args.seed, args.min_shot, args.max_shot, args.analysis, args.report,
                         args.handheld)
    except (ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": {"type": type(e).__name__, "message": str(e)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
