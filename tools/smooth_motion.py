"""Run a C1-continuous curve through the keys of a dance, so the bones stop moving in straight lines with a
velocity jump at every key, and bake it to a key on every frame.

    python tools/smooth_motion.py DANCE.vmd OUT.vmd [--report r.json] [--bones NAME ...] [--skip NAME ...]
                                  [--tension 0.5]

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


def smooth_track(keys, tension):
    """(the new keys, {"linear": n, "authored": n, "flat": n}) for a track with keys on 2 or more frames:
    a key per frame where the value moves, the two keys alone where it does not"""
    deduped = []
    for k in keys:
        if deduped and deduped[-1].frame == k.frame:
            deduped[-1] = k
        else:
            deduped.append(k)
    frames = [k.frame for k in deduped]
    slopes = tangents(deduped, tension)
    straight = vmd.LINEAR_CURVE
    out, counts = [], {"linear": 0, "authored": 0, "flat": 0}
    for i, a in enumerate(deduped):
        out.append(vmd.BoneKey(a.name, a.frame, tuple(a.position), tuple(a.rotation),
                               vmd.bone_interpolation(straight, keep=a.interpolation), a.raw_name))
        if i + 1 == len(deduped):
            break
        b = deduped[i + 1]
        if is_flat(a, b):
            counts["flat"] += 1
            continue
        if all(is_linear(c) for c in vmd.bone_curves(b.interpolation).values()):
            counts["linear"] += 1
            between = smooth_segment(a, b, slopes[i], slopes[i + 1])
        else:
            counts["authored"] += 1
            between = [sample(deduped, f, frames) for f in range(a.frame + 1, b.frame)]
        curve = vmd.bone_interpolation(straight, keep=a.interpolation)         # the frames after a key carry its flag
        for frame, (pos, rot) in zip(range(a.frame + 1, b.frame), between):
            out.append(vmd.BoneKey(a.name, frame, pos, rot, curve, a.raw_name))
    return out, counts


def is_constant(keys):
    """every key of the track holds the same value"""
    return all(is_flat(keys[0], k) for k in keys[1:])


def smooth(motion, tension=0.5, bones=None, skip=()):
    """(a copy of `motion` with every chosen bone track smoothed, a report); see the module docstring"""
    if not 0.0 <= tension <= 1.0:
        raise ValueError("--tension scales the tangents, 0 to 1, not %r" % (tension,))
    tracks = tracks_of(motion)
    skip = set(skip)
    chosen = set(tracks) if bones is None else set(bones)
    chosen -= skip
    new_bones, report = [], []
    for name in tracks:                                                      # the file's order of first appearance
        keys = tracks[name]
        entry = {"name": name, "keys_before": len(keys), "keys_after": len(keys),
                 "frames": [keys[0].frame, keys[-1].frame], "segments": {"linear": 0, "authored": 0, "flat": 0},
                 "changed": False}
        if name in chosen and keys[0].frame != keys[-1].frame and not is_constant(keys):
            keys, counts = smooth_track(keys, tension)
            entry.update(keys_after=len(keys), segments=counts, changed=True)
        new_bones += keys
        report.append(entry)
    out = copy.copy(motion)
    for field, value in list(vars(out).items()):                               # own lists: the input stays untouched
        if isinstance(value, list):
            setattr(out, field, list(value))
    out.bones = new_bones
    return out, {"tension": tension, "skipped": sorted(skip & set(tracks)),
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


def run(dance_path, out_path, tension=0.5, bones=None, skip=(), report_path=None):
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, report_path)
    if not 0.0 <= tension <= 1.0:
        raise ValueError("--tension scales the tangents, 0 to 1, not %r" % (tension,))
    motion = vmd.load(dance_full)
    smoothed, report = smooth(motion, tension, bones, skip)
    write_bytes(out_full, vmd.dumps(smoothed))
    back = vmd.load(out_full)
    changed = [b for b in report["bones"] if b["changed"]]
    result = {"in": dance_full, "out": out_full, "tension": tension, "bone_keys_before": len(motion.bones),
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
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.out, args.tension, args.bones, args.skip, args.report)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
