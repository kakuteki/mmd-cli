"""Make a calm camera motion (.vmd) for a dance motion (.vmd), without MMD.

    python tools/make_camera.py DANCE.vmd OUT_camera.vmd [--analysis a.json] [--report r.json]
                                [--seed N] [--min-shot 180] [--max-shot 480]

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
"""
import argparse
import bisect
import dataclasses
import json
import math
import os
import random
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import motion_edit  # noqa: E402
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


def camera_motion(shots):
    return vmd.Motion.for_camera(cameras=[k for shot in shots for k in camera_keys(shot)])


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


def run(dance_path, out_path, seed=0, min_shot=MIN_SHOT, max_shot=MAX_SHOT, analysis_path=None, report_path=None):
    """read the dance, plan, write the camera, read it back; the summary is what main prints"""
    check_limits(min_shot, max_shot)
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, analysis_path, report_path)
    motion = vmd.load(dance_full)
    analysis = analyze(motion)
    shots = plan_shots(motion, min_shot, max_shot, seed, analysis)
    write_bytes(out_full, vmd.dumps(camera_motion(shots)))
    back = vmd.load(out_full)
    result = {"in": dance_full, "out": out_full, "seed": seed, "min_shot": min_shot, "max_shot": max_shot,
              "frames": [0, analysis.last], "shots": len(shots), "keys": len(back.cameras),
              "key_frames": [back.cameras[0].frame, back.cameras[-1].frame],
              "kinds": _count(s.kind for s in shots), "levels": _count(s.level for s in shots)}
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
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.out, args.seed, args.min_shot, args.max_shot, args.analysis, args.report)
    except (ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": {"type": type(e).__name__, "message": str(e)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
