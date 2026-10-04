"""Move the forearm twist of a dance onto the wrist, so that a cuff (or a thin forearm) does not collapse.

    python tools/fix_twist.py DANCE.vmd OUT.vmd [--share 0.5] [--report r.json]

A dance made on another model can turn the hand twist bone (手捩) by half a turn: the distributed motion of
ヒビカセ holds 406 right and 387 left keys beyond 90 degrees, many at exactly 180, and says so itself (fix the
places that break).  A model without graded twist bones blends its forearm between the elbow and that one
bone; at 180 degrees the blend has no width left, and the cuff at the wrist is wrung flat (seen on Sour's
Rin, 2026-10-04: close-ups of frames 5388 and 5181 with and without the change).

What the tool does, per side:

* The hand hangs on twist then wrist: its orientation against the elbow is T * W (Hamilton product, the
  parent first).  Any pair with T' * W' == T * W shows the same hand.  T turns about the forearm only, so
  with T' = T^k (the same axis, k times the angle) the wrist W' = T^(1 - k) * W keeps the product.
* How much the forearm keeps (kept_twist): `--share` of the twist up to a quarter turn, then less again,
  down to nothing at a half turn.  With the default 0.5 the forearm never twists more than 45 degrees.
  The fall back to nothing matters: a twist of 180 degrees is where the two ways round meet (a file holds
  190 degrees as -170), and only a forearm that is at rest there does not jump when the dance passes it.
* Twist and wrist have their keys on different frames, and MMD interpolates each bone on its own, so the
  product can only be kept exactly where both have a key.  The tool therefore writes a key on every frame
  from the first to the last key of the pair, each the rotation MMD showed at that frame (the short way
  between the keys, eased by the later key's curve), with straight interpolation between them.
* Every other bone, the morphs and the rest of the file are left as they were.
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

PAIRS = (("右手捩", "右手首"), ("左手捩", "左手首"))
IDENTITY = (0.0, 0.0, 0.0, 1.0)
QUARTER, HALF = 90.0, 180.0


# ---- what MMD shows at a frame --------------------------------------------------------------

def tracks_of(motion):
    """bone name -> its keys sorted by frame"""
    out = {}
    for key in motion.bones:
        out.setdefault(key.name, []).append(key)
    for keys in out.values():
        keys.sort(key=lambda k: k.frame)
    return out


def _bezier_y(curve, x):
    """y of an MMD curve (x1, y1, x2, y2 in 0..127) at the time x in 0..1"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)
    if (x1, y1, x2, y2) == (y1, x1, y2, x2):                         # on the diagonal: straight
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


# ---- the share of the twist -----------------------------------------------------------------

def twist_degrees(q):
    """the angle of a rotation, 0 to 180 degrees"""
    return math.degrees(2.0 * math.acos(min(1.0, abs(q[3]))))


def kept_twist(degrees, share):
    """how much of a twist of `degrees` (0 to 180) the forearm keeps: `share` of it up to a quarter turn,
    falling back to nothing at a half turn"""
    return share * (degrees if degrees <= QUARTER else HALF - degrees)


def power(q, k):
    """q to the power k: the same axis, k times the angle (counted the short way)"""
    return slerp(IDENTITY, q if q[3] >= 0.0 else tuple(-v for v in q), k)


def split(twist, wrist, share):
    """(twist', wrist') showing the same hand, with the forearm keeping kept_twist of the twist"""
    degrees = twist_degrees(twist)
    if degrees < 1e-6:
        return twist, wrist
    k = kept_twist(degrees, share) / degrees
    return power(twist, k), _normalized(mathutil.quat_multiply(power(twist, 1.0 - k), wrist))


def fix(motion, share=0.5, pairs=PAIRS):
    """(a copy of `motion` with the twist of every pair moved onto its wrist, a report); see the module
    docstring.  ValueError when no twist bone of `pairs` has a key."""
    if not 0.0 <= share <= 1.0:
        raise ValueError("--share is the part of the twist the forearm keeps, 0 to 1, not %r" % (share,))
    tracks = tracks_of(motion)
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    replaced, new_keys, report = set(), [], []
    for twist_name, wrist_name in pairs:
        twist_keys, wrist_keys = tracks.get(twist_name), tracks.get(wrist_name)
        if not twist_keys:
            continue
        both = twist_keys + (wrist_keys or [])
        first, last = min(k.frame for k in both), max(k.frame for k in both)
        twist_frames, wrist_frames = [k.frame for k in twist_keys], [k.frame for k in wrist_keys or []]
        before, after, wrist_after = 0.0, 0.0, 0.0
        over = 0
        for frame in range(first, last + 1):
            twist_pos, twist = sample(twist_keys, frame, twist_frames)
            wrist_pos, wrist = sample(wrist_keys, frame, wrist_frames) if wrist_keys else ((0.0, 0.0, 0.0), IDENTITY)
            degrees = twist_degrees(twist)
            before = max(before, degrees)
            over += 1 if degrees > QUARTER else 0
            twist2, wrist2 = split(twist, wrist, share)
            after = max(after, twist_degrees(twist2))
            wrist_after = max(wrist_after, twist_degrees(wrist2))
            new_keys.append(vmd.BoneKey(twist_name, frame, twist_pos, twist2, straight))
            new_keys.append(vmd.BoneKey(wrist_name, frame, wrist_pos, wrist2, straight))
        replaced.update((twist_name, wrist_name))
        count = last - first + 1
        report.append({"twist": twist_name, "wrist": wrist_name, "frames": [first, last],
                       "keys_before": {"twist": len(twist_keys), "wrist": len(wrist_keys or [])},
                       "keys_after": {"twist": count, "wrist": count},
                       "max_twist_before": round(before, 3), "max_twist_after": round(after, 3),
                       "max_wrist_after": round(wrist_after, 3), "frames_over_a_quarter_turn_before": over})
    if not report:
        raise ValueError("the motion has no key on %s: nothing to fix" % " or ".join(p[0] for p in pairs))
    out = copy.copy(motion)
    out.bones = [k for k in motion.bones if k.name not in replaced] + new_keys
    return out, {"share": share, "pairs": report}


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


def run(dance_path, out_path, share=0.5, report_path=None):
    dance_full, out_full = os.path.abspath(dance_path), os.path.abspath(out_path)
    check_distinct(dance_full, out_full, report_path)
    motion = vmd.load(dance_full)
    fixed, report = fix(motion, share)
    write_bytes(out_full, vmd.dumps(fixed))
    back = vmd.load(out_full)
    result = {"in": dance_full, "out": out_full, "share": share, "bone_keys": len(back.bones), "pairs": report["pairs"]}
    if report_path:
        full = os.path.abspath(report_path)
        write_bytes(full, (json.dumps(dict({"in": dance_full, "out": out_full}, **report), ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        result["report"] = full
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("out", help="the dance to write (.vmd)")
    p.add_argument("--share", type=float, default=0.5, help="the part of the twist the forearm keeps, 0 to 1 (default 0.5)")
    p.add_argument("--report", help="write what was changed to this JSON")
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.out, args.share, args.report)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
