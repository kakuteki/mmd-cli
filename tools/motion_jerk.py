"""Measure how jerky a dance is: the per-frame acceleration of a few bones, as a number to compare before and after.

    python tools/motion_jerk.py DANCE.vmd [--bones NAME ...]

For every bone asked for (default: センター, 右腕, 左腕, 上半身) the bone's path is reconstructed at every
frame of its track as MMD shows it (tools/smooth_motion.py sample: straight between keys, eased by the
later key's curve), and the acceleration is the second finite difference of that path:

* a translation bone (センター, グルーブ, 全ての親): |p(f+1) - 2 p(f) + p(f-1)| in model units per frame^2;
* any other bone: the change of the per-frame turn, |w(f+1) - w(f)| in degrees per frame^2, where
  w(f) = log(q(f)^-1 q(f+1)) is the rotation vector of the step from frame f to f+1 (its length is the
  angle turned in that frame; both steps are read in the bone's own frame at their start).

The mean, 99th percentile and maximum are printed as one ASCII JSON line.  A bone without keys is
reported as null.
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for folder in (ROOT, HERE):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import smooth_motion  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402

DEFAULT_BONES = ("センター", "右腕", "左腕", "上半身")


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def accelerations(keys, translation):
    """the per-frame acceleration of a track, one value per interior frame"""
    frames = [k.frame for k in keys]
    path = [smooth_motion.sample(keys, f, frames) for f in range(keys[0].frame, keys[-1].frame + 1)]
    if translation:
        pos = [p for p, _ in path]
        return [_norm(tuple(x - 2 * y + z for x, y, z in zip(a, b, c))) for a, b, c in zip(pos, pos[1:], pos[2:])]
    rots = [r for _, r in path]
    steps = [smooth_motion.log_map(smooth_motion.relative(a, b)) for a, b in zip(rots, rots[1:])]
    return [math.degrees(_norm(tuple(x - y for x, y in zip(a, b)))) for a, b in zip(steps, steps[1:])]


def summary(values, unit, frames):
    if not values:
        return {"frames": frames, "unit": unit, "mean": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {"frames": frames, "unit": unit, "mean": sum(values) / len(values),
            "p99": ordered[int(round(0.99 * (len(ordered) - 1)))], "max": ordered[-1]}


def measure(motion, bones=DEFAULT_BONES):
    tracks = smooth_motion.tracks_of(motion)
    out = {}
    for name in bones:
        keys = tracks.get(name)
        if not keys:
            out[name] = None
            continue
        translation = name in smooth_motion.POSITION_BONES
        values = accelerations(keys, translation)
        out[name] = summary(values, "units/frame^2" if translation else "deg/frame^2", keys[-1].frame - keys[0].frame + 1)
    return {"bones": out}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("--bones", nargs="+", default=list(DEFAULT_BONES), help="the bones to measure")
    args = p.parse_args(argv)
    try:
        full = os.path.abspath(args.dance)
        result = measure(vmd.load(full), args.bones)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True, "in": full}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
