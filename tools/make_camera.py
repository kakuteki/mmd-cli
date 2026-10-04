"""Make a calm camera motion (.vmd) for a dance motion (.vmd), without MMD.

    python tools/make_camera.py DANCE.vmd OUT_camera.vmd [--analysis a.json] [--report r.json]
                                [--seed N] [--min-shot 180] [--max-shot 480]

The distributed camera of a dance is often made for a hall and keeps the dancer small.  This tool
writes a camera that keeps the dancer at a comfortable size and moves slowly once per shot (a push
in, a pull out, an orbit or a low angle), each shot 6 to 16 seconds long.  There is no sound to cut
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
  the lower one (hysteresis, so a beat does not flip it).  The frames where the state flips are the
  candidate cuts; the strength of a cut is the jump of the trend across it.
"""
import dataclasses
import math
import os
import sys
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FPS = 30
WINDOW = 30                      # frames: the strength of a frame is the motion of the second around it
TREND_WINDOW = 90                # frames: sections are found on a 3 second moving average of the strength
LOW_PERCENTILE, HIGH_PERCENTILE = 35, 65

# (part of the bone name, weight): the first match wins; see the module docstring for the reasoning
ROTATION_WEIGHTS = (
    ("指", 0.5), ("目", 0.2), ("ＩＫ", 1.0), ("足首", 1.0), ("手首", 1.5), ("頭", 2.0), ("首", 3.0),
    ("ひじ", 4.0), ("ひざ", 4.0), ("肩", 7.0), ("腕", 7.0), ("足", 8.0),
    ("上半身", 8.0), ("下半身", 8.0), ("センター", 8.0), ("グルーブ", 8.0), ("全ての親", 8.0),
)
DEFAULT_ROTATION_WEIGHT = 1.0
POSITION_WEIGHTS = (("センター", 1.0), ("グルーブ", 1.0), ("全ての親", 1.0), ("ＩＫ", 0.5))
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
    """runs of high and low state with hysteresis: up at `high`, down at `low`.  One section when the
    thresholds do not leave room between them (a flat trend)."""
    n = len(trend)
    if not high > low:
        return [Section(0, n - 1, "high" if trend[0] > 0 else "low", sum(trend) / n)]
    state = "high" if trend[0] >= high else "low"
    sections, start = [], 0
    for f in range(1, n):
        if state == "low" and trend[f] >= high:
            flip = "high"
        elif state == "high" and trend[f] <= low:
            flip = "low"
        else:
            continue
        sections.append(Section(start, f - 1, state, sum(trend[start:f]) / (f - start)))
        state, start = flip, f
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
