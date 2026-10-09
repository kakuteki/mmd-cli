"""Run a C1-continuous curve through the keys of a dance, so the bones stop moving in straight lines with a
velocity jump at every key, and bake it to a key on every frame.

    python tools/smooth_motion.py DANCE.vmd OUT.vmd [--report r.json] [--bones NAME ...] [--skip NAME ...]
                                  [--tension 0.5] [--denoise [HZ]] [--denoise-cap DEG UNITS] [--denoise-fingers]
                                  [--straight]

Why: a traced dance holds sparse keys with the linear curve.  The distributed motion of ヒビカセ has 39,451 of
its 39,660 bone keys on the curve (20, 20, 107, 107), a median gap of 3 to 6 frames and 100 to 200 gaps of
10 frames or more per bone (docs/design-20261004-mv-text.md, last section).  MMD moves each bone on a
straight line between such keys and changes its velocity abruptly on the key: the dance looks jerky.

What the tool does, per bone track (keys sorted by frame; of two keys on one frame the last one counts):

* A segment between two keys is "linear" when the later key's curve is straight on all four channels
  (x1 == y1 and x2 == y2, which MMD draws as a straight line; (20, 20, 107, 107) is the usual one).
  Any other segment was shaped by the author and is kept: it is sampled from the original keys and
  curves exactly as MMD shows it (a straight line per position channel and the short way for the
  rotation, each eased by the later key's curve).
* A segment whose two keys hold the same value (position equal, rotation equal up to the stored sign) is
  "flat": a planted foot, a closed hand.  MMD keeps it exactly still, and so does the tool: the two keys
  stay as they are and nothing is baked between them.  A track whose keys are all equal is not touched.
* A linear segment is replaced by a cubic Hermite curve from key to key.  The tangent at an interior key
  is a monotone (Fritsch-Carlson style) rule on the rates of its two adjacent segments, per position
  component: d1 = (P_i - P_{i-1}) / h1 and d2 = (P_{i+1} - P_i) / h2; the tangent is 0 when they differ in
  sign or one of them is 0 (a hold or a reversal), else sign * min(|d1|, |d2|), times 2 * tension.
  |m| <= min(|d1|, |d2|) (tension 0.5) keeps every segment monotone between its keys: the curve never
  passes beyond a key value and a hold is entered and left at rest, with no dip before or after it.  A
  straight run at uniform speed (d1 == d2) stays exactly a straight run.  tension 0 eases every segment
  in and out, 1 doubles the tangents (still within the monotone bound of 3 * min).  The first and last
  key have a zero tangent (the dance eases into and out of the track).
* Rotations get the same rule in the tangent (log) space.  The two adjacent rates are the rotation vectors
  of the two SEGMENT-wise relative turns, each the short way as MMD plays it (never the turn from
  neighbour to neighbour, which goes the other way round once the two segments add up to more than 180
  degrees): r1 = log(q_{i-1}^-1 q_i) / h1, r2 = log(q_i^-1 q_{i+1}) / h2.  r1 is the same vector in the
  frame of q_{i-1} and of q_i (a rotation leaves its own axis alone), so both are read in q_i's frame.
  The tangent is 0 when one is 0 or they point against each other (r1 . r2 <= 0), else the unit vector of
  r1 + r2 times min(|r1|, |r2|) times 2 * tension.  The segment is then drawn in the body frame of its
  first key as q(u) = q_a * exp(r(u)), r a Hermite curve from 0 to log(q_a^-1 q_b) with those end
  tangents (per frame, times the segment length).  Exactly C1 in the log chart; in angular velocity the
  mismatch at a key is of second order in the turn per segment.  A steady turn about one axis stays
  exactly a steady turn, and a segment never turns further than its own key-to-key arc along that axis.
  When the two arcs at a key lie on different axes the tangent points between them and the curve rounds
  the corner off the arcs; the whole tangent is scaled down (one scale, both sides, so C1 holds) until
  neither neighbouring segment bulges more than 3 degrees off its own arc.  What remains of the
  difference to MMD's straight path is timing along the arc: an eased segment lags or leads the linear
  one by at most 4/27 of its arc (one end at rest) or 0.0962 of it (both ends at rest); a 94-degree
  finger close in 5 frames out of a hold therefore differs by up to 9 degrees mid-way.  That is the ease.
* The key values themselves are kept exactly (position and quaternion as stored, raw name, physics bytes
  2 and 3 of the 64; the frames baked after a key carry that key's physics bytes).
* The result is written as a key on every frame of every segment that moves, all with the linear curve,
  so MMD plays the curve as computed (and a 60 fps render goes straight between adjacent frames, which
  is fine).  Running the tool on its own output changes nothing: every moving segment is then one frame
  long, every flat one stays flat, and the output on a key frame is the key.
* Not touched: tracks with one key or with all keys on one frame or all keys equal, bones named in
  `--skip`, every bone not named when `--bones` is given, morphs, camera, lights, shadows, IK, the model
  name.  The input file is never written over.  The report lists every bone with its keys before and
  after and its segments (linear / authored / flat).

--denoise [HZ] (default off; HZ 7.5 when given bare; docs/reviews/2026-10-06-batch-h-denoise.md, review 9).  Passing
exactly through every key keeps the tracer's jitter where the keys are 1 or 2 frames apart.  The keys of the traced
ヒビカセ sit on the grid the tracer edited with: of the body's angles in the MMD angle boxes that are not exactly 0,
78 % are multiples of 6 degrees (89 % with the many zeros; the fingers only 3 %), and 96.5 % of the non-zero positions
are multiples of 0.3 units, so a key misses the pose by up to 3 degrees per angle and the speed of a fast passage jumps
between multiples of 6 degrees per frame.  The denoise takes that frame-scale jitter out of the baked curve and
nothing else:

* A dense key is a key joined to a neighbour by a gap of at most 2 frames (DENSE_GAP).  An error that alternates on
  keys 1 or 2 frames apart is a 15 or 7.5 Hz pattern, above the beat (1 to 4 Hz); 3 frames apart it is 5 Hz and
  cannot be told from the choreography, so longer gaps are left alone.
* The zone: the frames within 2 frames (DENOISE_MARGIN) of a dense key, minus the pinned frames: every frame of a
  hold or of an authored segment, the frame just before and just after a hold and the frame next to the track's
  first and last key (so the step that touches a still stretch is the plain one; the steps 2 to 4 frames from it may
  change within the bounds), every key that is not dense, the first and last key, and, when the track's height
  varies, every key at its lowest height (a foot on the floor stays where it was traced).  The zone frames that lie
  within 3 frames of each other make one part; a part of fewer than 4 frames (MIN_ZONE) is left alone, since with
  its mean and slope at 0 (below) 3 frames can only take a zigzag c (1, -2, 1) (review 9: it turned a smooth
  deceleration of 6.5, 7.4, 6.9 degrees per frame into 11.0, 3.0, 8.4).
* Fingers (a bone whose name holds 指) are smoothed but not denoised unless --denoise-fingers: they are not on the
  grid and gained nothing measurable.
* On a part (with the 3 frames on either side held) the correction d of the baked curve x minimizes
  sum |d|^2 + lam * sum |third difference of (x + d)|^2, a penalized least-squares (Whittaker) smoother of order 3,
  the discrete minimum-jerk path near x.  lam = (2 sin(pi HZ / 30))^-6: on a curve keyed at every frame the response
  is 1 / (1 + lam (2 sin(pi f / 30))^6), a zero-phase low-pass that halves a sine of HZ.  At 7.5 Hz a frame-to-frame
  alternation keeps 1/9, a 7.5 Hz one 1/2, a 4 Hz accent 96 % and a 2 Hz swing 99.9 %.  Every zone frame counts
  with weight 1, keys and the frames between them alike (the plain curve is the data): leaving the frames between keys
  free let the correction spread into slow bumps, measured as removed energy below 6 Hz.
* The correction of a part has zero mean and zero slope (two linear constraints, per channel): a run is never shifted
  or tilted as a whole, only its frame-to-frame irregularity is redistributed.  Exact for positions and for the
  quaternion components; renormalized, a fast turn can leave the rotation vectors slightly off zero on average.
* Bounds on every zone frame: at most 3 degrees from the plain curve (the angle of the turn between them), at most
  0.05 units per position component (DENOISE_CAP, --denoise-cap DEG UNITS), and never below the track's lowest
  original height (the floor of a foot, the deepest crouch of the center, whatever the bone's spelling).  A frame that
  leaves its bounds is held at the bound and the others solved again (ROUNDS).  When that would leave fewer than
  MIN_ZONE frames free, or the rounds run out, the first correction is scaled down as a whole until it fits (one
  factor, so its mean and slope stay 0 and no frame moves alone: review 9 had single frames at 3 degrees with their
  neighbours fixed).  So the bounds always hold, and a corrected frame passes a traced key's value by at most the
  bound (the plain curve never passes one).
* Rotations are smoothed as quaternion components (one sign all along the track) and renormalized, the bound is
  applied along the geodesic, the written quaternion keeps the stored sign of the frame.  Positions per component.
  The system is banded (a key's jerk terms reach 3 frames): an L D L^T of half-bandwidth 3, stdlib only.
* Everything else is the plain output byte for byte: every frame farther than 2 frames from a dense key, every key
  that is not dense, every hold, every authored segment, every part of fewer than 4 frames, the fingers.  The report
  gives per bone the keys and frames moved, the frames at a bound and the largest moves.  On its own output (a key on
  every frame) --denoise would take every key for dense and move keys that were sparse in the tracing: when 90 % or
  more of a track's key gaps are 1 frame the result's "warnings" say so.  Give it the traced keys.

--straight (with --denoise; default off; stage 2, _spike/out/stage2/smooth/NOTES.md).  The curve above stops at every hold
edge and every turn of 90 degrees or more and takes the slower of the two adjacent rates elsewhere, so it slows down at keys
the motion goes on through: on ヒビカセ 59 to 72 % of the arm, elbow, head and upper body keys are passed at less than half
the mean speed around them (analysis a02), and the hands and the head dip below half their speed about once a second in
the middle of a movement, 1.7 to 2.7 times as often as before smoothing.  --straight bakes MMD's own straight path instead (the
linear segments as MMD shows them) and runs the denoise over the whole of every denoised track: every key counts as dense
and every frame that is not pinned may move, within the same caps of what was baked.  The low-pass rounds the velocity
step at each key over a few frames and adds no slowing down of its own.
* A segment that touches a still key (a hold's first or last key, the track's first or last key) is not baked straight:
  the straight path would stop dead at the hold in one frame, as the traced dance did (review smooth, item 1: the head
  and the center came to rest or set off in one frame as often as before smoothing).  It is the Hermite segment of the
  curve with a zero tangent at the still end and the segment's own chord rate (along its arc) at the other: it joins the
  straight path at its speed and comes to rest over its length.  That ease lags or leads the straight path by at most
  4/27 of the segment's arc; every other frame stays within --denoise-cap of MMD's straight path.
* Pinned as for --denoise (holds and the frame on either side, authored segments, the first and last key and the frame
  next to them, every key at the track's lowest height, a lone floor key of a landing too) and also every segment between
  two keys at the lowest height: a foot that is down slides exactly as traced, the frames between its contacts cannot
  wobble.  "At the lowest height" is an exact match of the stored value (a traced floor is one value, 0.0 in ヒビカセ; a
  floor that wavers by a hair is not seen as one).
* --tension does nothing on the denoised tracks (there are no curve tangents to scale; the eased segments always use
  the chord rate); it still shapes the fingers, which keep the curve unless --denoise-fingers.
"""
import argparse
import bisect
import copy
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import mathutil  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402

IDENTITY = (0.0, 0.0, 0.0, 1.0)
POSITION_BONES = ("センター", "グルーブ", "全ての親")  # bones whose motion is a translation


# ---- what MMD shows at a frame (as tools/fix_twist.py) --------------------------------------

def tracks_of(motion):
    """bone name -> its keys sorted by frame (a stable sort: two keys on one frame keep their file order)"""
    out = {}
    for key in motion.bones:
        out.setdefault(key.name, []).append(key)
    for keys in out.values():
        keys.sort(key=lambda k: k.frame)
    return out


def _bezier_y(curve, x):
    """y of an MMD curve (x1, y1, x2, y2 in 0..127) at the time x in 0..1"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)
    if (x1, x2) == (y1, y2):                                        # on the diagonal: straight
        return x
    lo, hi = 0.0, 1.0
    for _ in range(40):
        t = (lo + hi) / 2.0
        u = 1.0 - t
        if 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 < x:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2.0
    u = 1.0 - t
    return 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3


def is_linear(curve):
    """a curve MMD draws as a straight line"""
    return curve[0] == curve[1] and curve[2] == curve[3]


def _normalized(q):
    n = math.sqrt(sum(v * v for v in q))
    return tuple(v / n for v in q) if n > 0.0 else IDENTITY


def slerp(a, b, t):
    """from a to b the short way"""
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b, dot = tuple(-v for v in b), -dot
    if dot > 0.9995:
        return _normalized(tuple(x + (y - x) * t for x, y in zip(a, b)))
    theta = math.acos(min(1.0, dot))
    s = math.sin(theta)
    wa, wb = math.sin((1.0 - t) * theta) / s, math.sin(t * theta) / s
    return _normalized(tuple(wa * x + wb * y for x, y in zip(a, b)))


def sample(keys, frame, frames=None):
    """(position, rotation) of a bone at `frame` as MMD shows it: held before the first and after the last
    key, in between a straight line per position channel and the short way for the rotation, each eased
    by the curve of the later key.  `frames` is the list of the keys' frames, when the caller has it."""
    if frames is None:
        frames = [k.frame for k in keys]
    i = bisect.bisect_right(frames, frame)
    if i == 0:
        return tuple(keys[0].position), _normalized(keys[0].rotation)
    a = keys[i - 1]
    if i == len(keys) or a.frame == frame:
        return tuple(a.position), _normalized(a.rotation)
    b = keys[i]
    x = (frame - a.frame) / float(b.frame - a.frame)
    curves = vmd.bone_curves(b.interpolation)
    position = tuple(pa + (pb - pa) * _bezier_y(curves[c], x) for pa, pb, c in zip(a.position, b.position, ("x", "y", "z")))
    return position, slerp(_normalized(a.rotation), _normalized(b.rotation), _bezier_y(curves["rotation"], x))


# ---- quaternions as rotation vectors ----------------------------------------------------------

def conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def relative(a, b):
    """the turn r with a * r == b (unit quaternions; the short way, so its w is not negative)"""
    r = mathutil.quat_multiply(conjugate(_normalized(a)), _normalized(b))
    return r if r[3] >= 0.0 else tuple(-v for v in r)


def log_map(q):
    """the rotation vector (axis times angle in radians) of a unit quaternion, the short way"""
    x, y, z, w = q
    if w < 0.0:
        x, y, z, w = -x, -y, -z, -w
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-12:
        return (0.0, 0.0, 0.0)
    angle = 2.0 * math.atan2(s, w)
    k = angle / s
    return (x * k, y * k, z * k)


def exp_map(v):
    """the unit quaternion of a rotation vector"""
    angle = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if angle < 1e-12:
        return (0.5 * v[0], 0.5 * v[1], 0.5 * v[2], 1.0) if angle > 0.0 else IDENTITY
    k = math.sin(angle / 2.0) / angle
    return (v[0] * k, v[1] * k, v[2] * k, math.cos(angle / 2.0))


def rotate(q, v):
    """the vector v turned by the unit quaternion q"""
    x, y, z, w = q
    tx, ty, tz = 2.0 * (y * v[2] - z * v[1]), 2.0 * (z * v[0] - x * v[2]), 2.0 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


# ---- the curve ------------------------------------------------------------------------------

def _hermite(u):
    """the four Hermite basis values at u"""
    u2, u3 = u * u, u * u * u
    return 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2


ZERO = (0.0, 0.0, 0.0)
STILL = 1e-9                                            # a rate below this is a hold
BULGE = 4.0 / 27.0                                      # max of the Hermite basis h10 (at u = 1/3)
LATERAL_BOUND = math.radians(3.0)                       # how far off its own arc a rotation segment may bulge


def same_rotation(a, b):
    """the two stored quaternions are one rotation (equal, or equal up to the sign)"""
    return all(x == y for x, y in zip(a, b)) or all(x == -y for x, y in zip(a, b))


def is_flat(a, b):
    """the keys a and b hold the same value: MMD keeps the segment still"""
    return tuple(a.position) == tuple(b.position) and same_rotation(a.rotation, b.rotation)


def _monotone(d1, d2):
    """the monotone tangent of two adjacent rates: 0 on a hold or a reversal, else the smaller one"""
    if d1 * d2 <= 0.0:
        return 0.0
    return math.copysign(min(abs(d1), abs(d2)), d1)


def tangents(keys, tension):
    """per key: (position tangent per component, rotation-vector tangent in the key's own body frame), per
    frame; the monotone rule of the module docstring"""
    out = []
    for i, k in enumerate(keys):
        if i == 0 or i == len(keys) - 1:
            out.append((ZERO, ZERO))
            continue
        before, after = keys[i - 1], keys[i + 1]
        h1, h2 = float(k.frame - before.frame), float(after.frame - k.frame)
        gain = 2.0 * tension
        pos = tuple(gain * _monotone((pk - pb) / h1, (pa - pk) / h2)
                    for pb, pk, pa in zip(before.position, k.position, after.position))
        r1 = tuple(c / h1 for c in log_map(relative(before.rotation, k.rotation)))   # the same vector in both frames
        r2 = tuple(c / h2 for c in log_map(relative(k.rotation, after.rotation)))
        n1, n2 = math.sqrt(sum(c * c for c in r1)), math.sqrt(sum(c * c for c in r2))
        dot = sum(x * y for x, y in zip(r1, r2))
        if n1 < STILL or n2 < STILL or dot <= 0.0:
            rot = ZERO
        else:
            axis = tuple(x + y for x, y in zip(r1, r2))
            n = math.sqrt(sum(c * c for c in axis))
            rot = tuple(gain * min(n1, n2) * c / n for c in axis)
            # the part of the tangent across a segment's arc bulges the curve off that arc by at most
            # BULGE (4/27 of tangent * length, at u = 1/3): scale the whole tangent down so that neither
            # neighbouring segment leaves its arc by more than LATERAL_BOUND; one scale for both sides keeps C1
            scale = 1.0
            for r, h in ((r1, h1), (r2, h2)):
                along = sum(x * y for x, y in zip(rot, r)) / (sum(c * c for c in r))
                off = math.sqrt(sum((x - along * y) ** 2 for x, y in zip(rot, r)))
                if BULGE * h * off > LATERAL_BOUND:
                    scale = min(scale, LATERAL_BOUND / (BULGE * h * off))
            rot = tuple(c * scale for c in rot)
        out.append((pos, rot))
    return out


def smooth_segment(a, b, ma, mb):
    """[(position, rotation)] for the frames strictly between the keys a and b (tangents per frame)"""
    dt = float(b.frame - a.frame)
    qa = _normalized(a.rotation)
    turning = not same_rotation(a.rotation, b.rotation) or ma[1] != ZERO or mb[1] != ZERO
    e = log_map(relative(qa, b.rotation)) if turning else ZERO
    moving = [pa != pb or ta != 0.0 or tb != 0.0 for pa, pb, ta, tb in zip(a.position, b.position, ma[0], mb[0])]
    out = []
    for frame in range(a.frame + 1, b.frame):
        h00, h10, h01, h11 = _hermite((frame - a.frame) / dt)
        pos = tuple(h00 * pa + h10 * dt * ta + h01 * pb + h11 * dt * tb if m else pa
                    for pa, pb, ta, tb, m in zip(a.position, b.position, ma[0], mb[0], moving))
        if turning:
            r = tuple(h10 * dt * ta + h01 * ee + h11 * dt * tb for ee, ta, tb in zip(e, ma[1], mb[1]))
            rot = _normalized(mathutil.quat_multiply(qa, exp_map(r)))
        else:
            rot = qa
        out.append((pos, rot))
    return out


def eased_ends(a, b, rest_a, rest_b):
    """the end tangents of a segment of --straight that touches a still key: 0 at the still end, the segment's own chord
    rate (its straight speed, along its arc) at the other.  The segment then leaves or joins the straight path at its
    speed and comes to rest over its length, never in one frame (review smooth item 1)"""
    h = float(b.frame - a.frame)
    chord = (tuple((pb - pa) / h for pa, pb in zip(a.position, b.position)),
             tuple(c / h for c in log_map(relative(a.rotation, b.rotation))))   # the same vector in a's and b's frames
    rest = (ZERO, ZERO)
    return (rest if rest_a else chord), (rest if rest_b else chord)


def dedupe(keys):
    """the keys of a track (sorted by frame) with one key per frame: of two keys on one frame the last one counts"""
    deduped = []
    for k in keys:
        if deduped and deduped[-1].frame == k.frame:
            deduped[-1] = k
        else:
            deduped.append(k)
    return deduped


def smooth_track(keys, tension, straight=False):
    """(the new keys, {"linear": n, "authored": n, "flat": n}) for a track with keys on 2 or more frames:
    a key per frame where the value moves, the two keys alone where it does not.  straight: the linear segments are
    baked as MMD shows them (the straight path) instead of the curve, for --straight"""
    deduped = dedupe(keys)
    frames = [k.frame for k in deduped]
    slopes = None if straight else tangents(deduped, tension)
    still = {deduped[0].frame, deduped[-1].frame}                           # where the motion starts from or comes to rest
    for a, b in zip(deduped, deduped[1:]):
        if is_flat(a, b):
            still.update((a.frame, b.frame))
    line = vmd.LINEAR_CURVE
    out, counts = [], {"linear": 0, "authored": 0, "flat": 0}
    for i, a in enumerate(deduped):
        out.append(vmd.BoneKey(a.name, a.frame, tuple(a.position), tuple(a.rotation),
                               vmd.bone_interpolation(line, keep=a.interpolation), a.raw_name))
        if i + 1 == len(deduped):
            break
        b = deduped[i + 1]
        if is_flat(a, b):
            counts["flat"] += 1
            continue
        if all(is_linear(c) for c in vmd.bone_curves(b.interpolation).values()):
            counts["linear"] += 1
            if straight and (a.frame in still or b.frame in still):
                between = smooth_segment(a, b, *eased_ends(a, b, a.frame in still, b.frame in still))
            elif straight:
                between = [sample(deduped, f, frames) for f in range(a.frame + 1, b.frame)]
            else:
                between = smooth_segment(a, b, slopes[i], slopes[i + 1])
        else:
            counts["authored"] += 1
            between = [sample(deduped, f, frames) for f in range(a.frame + 1, b.frame)]
        curve = vmd.bone_interpolation(line, keep=a.interpolation)             # the frames after a key carry its flag
        for frame, (pos, rot) in zip(range(a.frame + 1, b.frame), between):
            out.append(vmd.BoneKey(a.name, frame, pos, rot, curve, a.raw_name))
    return out, counts


def is_constant(keys):
    """every key of the track holds the same value"""
    return all(is_flat(keys[0], k) for k in keys[1:])


# ---- the denoise (--denoise) ------------------------------------------------------------------

FPS = 30.0                              # MMD's frame rate
DENOISE_HZ = 7.5                        # the cutoff of --denoise when none is given
DENOISE_CAP = (3.0, 0.05)               # how far the denoise may move a frame: degrees, model units per position component
DENSE_GAP = 2                           # keys at most this many frames apart make a dense run
DENOISE_MARGIN = 2                      # the frames on either side of a dense key the correction may use
MIN_ZONE = 4                            # a zone of fewer frames is left alone: with its mean and slope at 0 the only
                                        # correction of 3 frames is c(1, -2, 1), a zigzag (review 9 M2)
FINGER = "指"                           # a bone whose name holds it is a finger: smoothed, not denoised unless asked
BAKED_SHARE = 0.9                       # a track with this share of its key gaps 1 frame long looks already baked
JERK = (-1.0, 3.0, -3.0, 1.0)           # the third difference: the penalty is on the jerk
ROUNDS = 12                             # rounds of holding the frames that leave their bounds


def smoothing_weight(hz):
    """the weight of the jerk penalty for a cutoff of `hz`: on keys at every frame the smoother halves a sine of hz
    (its response is 1 / (1 + weight * (2 sin(pi f / FPS))^6), a zero-phase low-pass of order 3)"""
    return (2.0 * math.sin(math.pi * hz / FPS)) ** -6


def check_denoise(hz, cap):
    """(hz, (degrees, units)) as floats, or ValueError"""
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or not 0.0 < hz < FPS / 2.0:
        raise ValueError("--denoise is a cutoff in Hz above 0 and below %g (half of %g fps), not %r" % (FPS / 2.0, FPS, hz))
    cap = tuple(cap)
    if len(cap) != 2 or not all(not isinstance(c, bool) and isinstance(c, (int, float)) and math.isfinite(c) and c > 0.0
                                for c in cap):
        raise ValueError("--denoise-cap is two positive numbers, degrees and model units, not %r" % (cap,))
    return float(hz), (float(cap[0]), float(cap[1]))


def dense_plan(keys, every=False):
    """(the frames the denoise may move, the frames of the dense keys, the track's floor) of a deduped track.

    A key is dense when a gap of at most DENSE_GAP frames joins it to a neighbour.  Pinned (never moved) are: every frame
    of a hold or of an authored segment (their keys too), the frame just before and just after a hold and the frame next
    to the track's first and last key (so the motion enters and leaves every still stretch as the plain curve does),
    every key that is not dense, the track's first and last key and, when the track's height varies, every key at its
    lowest height (a foot on the floor stays where it was traced).  The frames that may move are those within
    DENOISE_MARGIN of a dense key that are not pinned.  every (--straight): every key counts as dense whatever its gaps,
    every frame that is not pinned may move, and a segment between two keys at the lowest height is pinned too (a foot
    that is down keeps the traced path between its contacts, so the frames between them cannot wobble into a skate)."""
    n = len(keys)
    ys = [k.position[1] for k in keys]
    floor = min(ys)
    lifts = max(ys) > floor
    pinned = {keys[0].frame + 1, keys[-1].frame - 1}
    for a, b in zip(keys, keys[1:]):
        if is_flat(a, b):
            pinned.update(range(a.frame - 1, b.frame + 2))
        elif not all(is_linear(c) for c in vmd.bone_curves(b.interpolation).values()):
            pinned.update(range(a.frame, b.frame + 1))
        elif every and lifts and a.position[1] == floor == b.position[1]:
            pinned.update(range(a.frame, b.frame + 1))                      # a foot down: it slides as traced, no more
    dense = set()
    for i, k in enumerate(keys):
        if 0 < i < n - 1 and k.frame not in pinned and not (lifts and k.position[1] == floor) and \
                (every or min(k.frame - keys[i - 1].frame, keys[i + 1].frame - k.frame) <= DENSE_GAP):
            dense.add(k.frame)
        else:
            pinned.add(k.frame)
    if every:
        return {f for f in range(keys[0].frame, keys[-1].frame + 1) if f not in pinned}, dense, floor
    zone = set()
    for f in dense:
        for g in range(max(keys[0].frame, f - DENOISE_MARGIN), min(keys[-1].frame, f + DENOISE_MARGIN) + 1):
            if g not in pinned:
                zone.add(g)
    return zone, dense, floor


def _ldl(bands):
    """L D L^T of a symmetric positive definite matrix of half-bandwidth 3, given by rows [A(i,i), A(i,i+1), A(i,i+2),
    A(i,i+3)]; L as rows [L(i,i-1), L(i,i-2), L(i,i-3)]"""
    n = len(bands)
    low, diag = [[0.0, 0.0, 0.0] for _ in range(n)], [0.0] * n
    for i in range(n):
        row = low[i]
        for k in (3, 2, 1):                                                 # L(i, j) for j = i-3, i-2, i-1 in turn
            j = i - k
            if j < 0:
                continue
            s = bands[j][k]
            for kk in range(k + 1, 4):                                      # the columns m = i-kk < j already done
                m = i - kk
                if m < 0:
                    break
                s -= row[kk - 1] * low[j][kk - k - 1] * diag[m]
            row[k - 1] = s / diag[j]
        d = bands[i][0]
        for k in (1, 2, 3):
            if i - k >= 0:
                d -= row[k - 1] * row[k - 1] * diag[i - k]
        diag[i] = d
    return low, diag


def _ldl_solve(low, diag, b):
    n = len(b)
    z = list(b)
    for i in range(n):
        row = low[i]
        for k in (1, 2, 3):
            if i - k >= 0:
                z[i] -= row[k - 1] * z[i - k]
    for i in range(n):
        z[i] /= diag[i]
    for i in range(n - 1, -1, -1):
        for k in (1, 2, 3):
            if i + k < n:
                z[i] -= low[i + k][k - 1] * z[i + k]
    return z


def _solve(columns, active, zone, fixed, lam):
    """the correction of every channel (columns: values per window frame) on the active frames: minimize
    sum(d^2) + lam * |JERK * (x + d)|^2 with d fixed where not active, and the zone's mean and slope of d at 0"""
    n = len(columns[0])
    free = [j for j in range(n) if active[j]]
    out = [list(fx) for fx in fixed]
    if not free:
        return out
    index = {j: a for a, j in enumerate(free)}
    m = len(free)
    bands = [[1.0, 0.0, 0.0, 0.0] for _ in free]
    rhs = [[0.0] * m for _ in columns]
    base = [[x[j] + fx[j] for j in range(n)] for x, fx in zip(columns, fixed)]
    for r in range(n - 3):
        idx = [index.get(r + s) for s in range(4)]
        if idx[0] is None and idx[1] is None and idx[2] is None and idx[3] is None:
            continue
        for c, b in enumerate(base):
            v = JERK[0] * b[r] + JERK[1] * b[r + 1] + JERK[2] * b[r + 2] + JERK[3] * b[r + 3]
            if v:
                for s in range(4):
                    if idx[s] is not None:
                        rhs[c][idx[s]] -= lam * JERK[s] * v
        for s in range(4):
            if idx[s] is not None:
                for t in range(s, 4):
                    if idx[t] is not None:
                        bands[idx[s]][idx[t] - idx[s]] += lam * JERK[s] * JERK[t]
    low, diag = _ldl(bands)
    z = [_ldl_solve(low, diag, b) for b in rhs]
    # the run is not moved as a whole: the zone's mean and slope of d stay 0 (the held frames count with their d)
    if m <= 2:
        z = [[0.0] * m for _ in columns]
    else:
        frames = [j for j in range(n) if zone[j]]
        mid, scale = sum(frames) / float(len(frames)), float(len(frames))
        rows = [[1.0 if zone[j] else 0.0 for j in range(n)], [(j - mid) / scale if zone[j] else 0.0 for j in range(n)]]
        cf = [[row[j] for j in free] for row in rows]
        w = [_ldl_solve(low, diag, c) for c in cf]
        s00 = sum(a * b for a, b in zip(cf[0], w[0]))
        s01 = sum(a * b for a, b in zip(cf[0], w[1]))
        s11 = sum(a * b for a, b in zip(cf[1], w[1]))
        det = s00 * s11 - s01 * s01
        if det <= 1e-12 * s00 * s11:
            z = [[0.0] * m for _ in columns]
        else:
            for c in range(len(columns)):
                held = [-sum(row[j] * fixed[c][j] for j in range(n) if zone[j] and not active[j]) for row in rows]
                r0 = sum(a * b for a, b in zip(cf[0], z[c])) - held[0]
                r1 = sum(a * b for a, b in zip(cf[1], z[c])) - held[1]
                mu0, mu1 = (s11 * r0 - s01 * r1) / det, (s00 * r1 - s01 * r0) / det
                z[c] = [v - w[0][a] * mu0 - w[1][a] * mu1 for a, v in enumerate(z[c])]
    for c in range(len(columns)):
        for a, j in enumerate(free):
            out[c][j] = z[c][a]
    return out


def _shrink(columns, zone, d, project):
    """d times the largest factor in [0, 1] that keeps every zone frame inside its bounds (bisection: the bounds of a
    frame hold on an interval of factors that contains 0, the plain curve).  A common factor keeps the mean and the
    slope of d at 0 and its shape whole."""
    low, high = 0.0, 1.0
    for _ in range(50):
        t = (low + high) / 2.0
        if all(project(j, [x[j] + t * dd[j] for x, dd in zip(columns, d)]) is None for j in range(len(zone)) if zone[j]):
            low = t
        else:
            high = t
    return [[low * v for v in dd] for dd in d]


def _settle(columns, zone, lam, project):
    """the new values of the window's frames: _solve, then hold every zone frame that leaves its bounds at its bound
    (project(j, values) gives the bounded values, or None when inside) and solve again.  When holding would leave fewer
    than MIN_ZONE frames free (then the mean and slope could only be kept by a zigzag, or not at all: a held frame alone,
    review 9 M1), or the rounds run out, the first correction is scaled down as a whole into the bounds instead."""
    n = len(columns[0])
    fixed = [[0.0] * n for _ in columns]
    active = list(zone)
    first = None
    for _ in range(ROUNDS):
        d = _solve(columns, active, zone, fixed, lam)
        if first is None:
            first = d
        held = []
        for j in range(n):
            if active[j]:
                bound = project(j, [x[j] + dd[j] for x, dd in zip(columns, d)])
                if bound is not None:
                    held.append((j, bound))
        if not held:
            break
        if sum(active) - len(held) < MIN_ZONE:
            d = _shrink(columns, zone, first, project)
            break
        for j, bound in held:
            for c, x in enumerate(columns):
                fixed[c][j] = bound[c] - x[j]
            active[j] = False
    else:
        d = _shrink(columns, zone, first, project)
    values = []
    for j in range(n):
        v = [x[j] + dd[j] for x, dd in zip(columns, d)]
        if zone[j]:
            v = project(j, v) or v
        values.append(v)
    return values


def denoise_track(keys, baked, hz, cap=DENOISE_CAP, every=False):
    """(the baked keys with the frame-scale jitter of the dense runs taken out, what was moved): keys is the deduped
    track, baked what smooth_track made of it.  every: all of the track, not only its dense runs (--straight).  See the
    module docstring."""
    stats = {"keys": 0, "frames": 0, "at_cap": 0, "max_deg": 0.0, "max_units": 0.0}
    zone, dense, floor = dense_plan(keys, every)
    if not zone:
        return baked, stats
    cap_deg, cap_units = cap
    cap_rad = math.radians(cap_deg)
    lam = smoothing_weight(hz)
    f0, f1 = keys[0].frame, keys[-1].frame
    at = {k.frame: k for k in baked}
    pos, rot, last = [], [], None
    for f in range(f0, f1 + 1):                                             # the baked path at every frame (a hold keeps its value)
        last = at.get(f, last)
        pos.append(tuple(last.position))
        q = _normalized(last.rotation)
        if rot and sum(a * b for a, b in zip(q, rot[-1])) < 0.0:
            q = tuple(-v for v in q)                                        # one sign all along: the components are smooth
        rot.append(q)
    new_pos, new_rot = list(pos), list(rot)
    frames = sorted(zone)
    groups, start = [], frames[0]
    for prev, f in zip(frames, frames[1:]):
        if f - prev > 3:                                                    # no jerk term reaches across 3 pinned frames
            groups.append((start, prev))
            start = f
    groups.append((start, frames[-1]))
    for a, b in groups:
        lo, hi = max(f0, a - 3), min(f1, b + 3)
        window = range(lo - f0, hi - f0 + 1)
        inside = [lo + j in zone for j in range(len(window))]
        if sum(inside) < MIN_ZONE:
            continue                                                        # too short to shape: left as the plain curve
        x = [[rot[i][c] for i in window] for c in range(4)]
        if any(rot[i] != rot[window[0]] for i in window):
            def bound_rotation(j, v, x=x):
                xq = (x[0][j], x[1][j], x[2][j], x[3][j])
                turn = log_map(relative(xq, v))                             # from the plain frame, the short way
                angle = math.sqrt(sum(c * c for c in turn))
                if angle <= cap_rad:
                    return None
                # back along that arc to the cap, exactly (slerp blends linearly below 3.6 degrees and misses it)
                return list(_normalized(mathutil.quat_multiply(xq, exp_map(tuple(c * cap_rad / angle for c in turn)))))
            values = _settle(x, inside, lam, bound_rotation)
            for j, i in enumerate(window):
                if inside[j]:
                    new_rot[i] = _normalized(values[j])
        for c in range(3):
            xc = [pos[i][c] for i in window]
            if all(v == xc[0] for v in xc):
                continue

            def bound_position(j, v, xc=xc, c=c):
                low, high = xc[j] - cap_units, xc[j] + cap_units
                if c == 1:
                    low = max(low, floor)
                return [low] if v[0] < low else [high] if v[0] > high else None
            values = _settle([xc], inside, lam, bound_position)
            for j, i in enumerate(window):
                if inside[j]:
                    p = list(new_pos[i])
                    p[c] = values[j][0]
                    new_pos[i] = tuple(p)
    out = []
    for k in baked:
        i = k.frame - f0
        if k.frame not in zone or (new_pos[i] == pos[i] and new_rot[i] == rot[i]):
            out.append(k)
            continue
        q = new_rot[i] if new_rot[i] != rot[i] else tuple(k.rotation)
        if sum(a * b for a, b in zip(q, k.rotation)) < 0.0:
            q = tuple(-v for v in q)                                        # the stored sign of the baked frame
        out.append(vmd.BoneKey(k.name, k.frame, new_pos[i], q, k.interpolation, k.raw_name))
        degrees = math.degrees(2.0 * math.acos(min(1.0, abs(sum(a * b for a, b in zip(new_rot[i], rot[i]))))))
        units = max(abs(a - b) for a, b in zip(new_pos[i], pos[i]))
        stats["frames"] += 1
        stats["keys"] += k.frame in dense
        stats["at_cap"] += degrees >= cap_deg - 1e-6 or units >= cap_units - 1e-9
        stats["max_deg"] = max(stats["max_deg"], degrees)
        stats["max_units"] = max(stats["max_units"], units)
    return out, stats


def smooth(motion, tension=0.5, bones=None, skip=(), denoise=None, denoise_cap=None, denoise_fingers=False, straight=False):
    """(a copy of `motion` with every chosen bone track smoothed, a report); see the module docstring.  denoise is the
    cutoff in Hz of the denoise of the dense runs (None: no denoise), denoise_cap its (degrees, units), denoise_fingers
    takes the finger bones in too, straight (--straight) low-passes the straight path at every key of a denoised track
    instead.  report["warnings"] lists what looks wrong with the input (an already baked file)."""
    if not 0.0 <= tension <= 1.0:
        raise ValueError("--tension scales the tangents, 0 to 1, not %r" % (tension,))
    if denoise is None and (denoise_cap is not None or denoise_fingers or straight):
        raise ValueError("--denoise-cap, --denoise-fingers and --straight go with --denoise: give --denoise too")
    if denoise is not None:
        denoise, denoise_cap = check_denoise(denoise, DENOISE_CAP if denoise_cap is None else denoise_cap)
    tracks = tracks_of(motion)
    skip = set(skip)
    chosen = set(tracks) if bones is None else set(bones)
    chosen -= skip
    new_bones, report, denoised, looks_baked = [], [], 0, []
    for name in tracks:                                                      # the file's order of first appearance
        keys = tracks[name]
        entry = {"name": name, "keys_before": len(keys), "keys_after": len(keys),
                 "frames": [keys[0].frame, keys[-1].frame], "segments": {"linear": 0, "authored": 0, "flat": 0},
                 "changed": False}
        if name in chosen and keys[0].frame != keys[-1].frame and not is_constant(keys):
            denoised_here = denoise is not None and (FINGER not in name or denoise_fingers)
            baked, counts = smooth_track(keys, tension, straight and denoised_here)
            if denoise is not None:
                if not denoised_here:
                    entry["denoise"] = {"keys": 0, "frames": 0, "at_cap": 0, "max_deg": 0.0, "max_units": 0.0, "skipped": "finger"}
                else:
                    traced = dedupe(keys)
                    gaps = [b.frame - a.frame for a, b in zip(traced, traced[1:])]
                    if len(gaps) >= 10 and sum(g == 1 for g in gaps) >= BAKED_SHARE * len(gaps):
                        looks_baked.append(name)
                    denoised += 1
                    baked, entry["denoise"] = denoise_track(traced, baked, denoise, denoise_cap, straight)
            keys = baked
            entry.update(keys_after=len(keys), segments=counts, changed=True)
        new_bones += keys
        report.append(entry)
    out = copy.copy(motion)
    for field, value in list(vars(out).items()):                               # own lists: the input stays untouched
        if isinstance(value, list):
            setattr(out, field, list(value))
    out.bones = new_bones
    settings = None if denoise is None else {"hz": denoise, "cap_deg": denoise_cap[0], "cap_units": denoise_cap[1],
                                             "max_gap": DENSE_GAP, "margin": DENOISE_MARGIN, "min_zone": MIN_ZONE,
                                             "fingers": bool(denoise_fingers), "straight": bool(straight)}
    warnings = []
    if looks_baked:
        warnings.append("%d of the %d denoised tracks have a key on 90 %% or more of their frames (%s%s): an already baked "
                        "file?  --denoise takes all their keys for dense and moves keys that were sparse in the tracing; "
                        "give it the traced keys" % (len(looks_baked), denoised, ", ".join(looks_baked[:3]),
                                                     ", ..." if len(looks_baked) > 3 else ""))
    return out, {"tension": tension, "denoise": settings, "warnings": warnings, "skipped": sorted(skip & set(tracks)),
                 "bones_requested_but_absent": sorted(set(bones or ()) - set(tracks)), "bones": report}


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
    """the dance and the files written must all differ: the dance is not to be written over"""
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, OUT and --report must all differ" % (seen[key], path))
        seen[key] = path


def run(dance_path, out_path, tension=0.5, bones=None, skip=(), report_path=None, denoise=None, denoise_cap=None,
        denoise_fingers=False, straight=False):
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, report_path)
    if not 0.0 <= tension <= 1.0:
        raise ValueError("--tension scales the tangents, 0 to 1, not %r" % (tension,))
    if denoise is None and (denoise_cap is not None or denoise_fingers or straight):
        raise ValueError("--denoise-cap, --denoise-fingers and --straight go with --denoise: give --denoise too")
    if denoise is not None:
        check_denoise(denoise, DENOISE_CAP if denoise_cap is None else denoise_cap)
    motion = vmd.load(dance_full)
    smoothed, report = smooth(motion, tension, bones, skip, denoise, denoise_cap, denoise_fingers, straight)
    write_bytes(out_full, vmd.dumps(smoothed))
    back = vmd.load(out_full)
    changed = [b for b in report["bones"] if b["changed"]]
    summary = None
    if report["denoise"] is not None:
        moved = [b["denoise"] for b in changed]
        summary = dict(report["denoise"], **{kind: sum(m[kind] for m in moved) for kind in ("keys", "frames", "at_cap")})
        summary.update({kind: max([m[kind] for m in moved] or [0.0]) for kind in ("max_deg", "max_units")})
    result = {"in": dance_full, "out": out_full, "tension": tension, "denoise": summary, "warnings": report["warnings"],
              "bone_keys_before": len(motion.bones),
              "bone_keys": len(back.bones), "bones_changed": len(changed), "skipped": report["skipped"],
              "segments": {kind: sum(b["segments"][kind] for b in changed) for kind in ("linear", "authored", "flat")},
              "bones": report["bones"]}
    if report_path:
        full = os.path.abspath(report_path)
        write_bytes(full, (json.dumps(dict({"in": dance_full, "out": out_full}, **report), ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        result["report"] = full
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("out", help="the dance to write (.vmd)")
    p.add_argument("--report", help="write what was changed to this JSON")
    p.add_argument("--bones", nargs="+", help="smooth only these bones")
    p.add_argument("--skip", nargs="+", default=[], help="leave these bones as they are")
    p.add_argument("--tension", type=float, default=0.5, help="scale of the tangents, 0 to 1 (default 0.5 = Catmull-Rom)")
    p.add_argument("--denoise", nargs="?", type=float, const=DENOISE_HZ, default=None, metavar="HZ",
                   help="also take the frame-scale jitter out of the runs of keys 1-2 frames apart; HZ is the cutoff "
                        "(default %g)" % DENOISE_HZ)
    p.add_argument("--denoise-cap", nargs=2, type=float, default=None, metavar=("DEG", "UNITS"),
                   help="how far --denoise may move a frame (default %g degrees, %g units)" % DENOISE_CAP)
    p.add_argument("--denoise-fingers", action="store_true",
                   help="let --denoise take the finger bones in too (left out by default)")
    p.add_argument("--straight", action="store_true",
                   help="with --denoise: low-pass MMD's straight path at every key instead of running a curve through "
                        "the keys (no slowing down at a key the motion goes on through; the segments next to a hold ease); "
                        "--tension then only shapes the fingers")
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.out, args.tension, args.bones, args.skip, args.report, args.denoise, args.denoise_cap,
                     args.denoise_fingers, args.straight)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
