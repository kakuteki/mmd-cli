"""Measure what the viewer sees of a dance: the world paths of a few bones (forward kinematics on the model) and how
fast and how jerkily they move, so that two versions of a dance can be compared.

    python tools/motion_fk.py DANCE.vmd MODEL.pmx [--bones 右手首 左手首 頭] [--out paths.json]

tools/motion_jerk.py measures a bone's own turn; a wrist turning smoothly on a shaking arm still shakes on screen.
This tool follows the bones to where the model puts them: mmd_cli.fk gives, frame by frame from 0 to the dance's
last bone key, each bone's world position as MMD shows the keys (parents, rest positions, appends; the rotation
convention of mmd_cli/fk.py).  For each bone:

* speed: |p(f+1) - p(f)|, model units per frame (one unit is roughly 8 cm on a 20-unit model; times 30 per second);
* acceleration: |p(f+1) - 2 p(f) + p(f-1)|, the second difference, model units per frame^2;

each as mean, 99th percentile (nearest rank) and maximum, printed as one ASCII JSON line.  --out also writes the
paths themselves (positions rounded to 1e-4).

IK and physics are ignored.  A bone that an IK moves (an IK link or below one: the legs and the feet of most models)
comes out where its own keys alone put it, not where MMD draws it, and is flagged ik_affected: do not read it.  On
Sour's Rin the chains from 全ての親 to the wrists and to the head hold no IK link.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

DEFAULT_BONES = ("右手首", "左手首", "頭")
UNIT = {"position": "model units", "speed": "model units per frame", "acceleration": "model units per frame^2"}
NOTE = ("IK and physics are ignored: a bone flagged ik_affected (an IK link or below one, such as the legs and feet) "
        "is where its own keys alone put it, not where MMD draws it")


def _norm(v):
    return sum(c * c for c in v) ** 0.5


def speeds(path):
    """|p(f+1) - p(f)| for each step of a path"""
    return [_norm(tuple(b - a for a, b in zip(p, q))) for p, q in zip(path, path[1:])]


def accelerations(path):
    """|p(f+1) - 2 p(f) + p(f-1)| for each inner frame of a path"""
    return [_norm(tuple(a - 2.0 * b + c for a, b, c in zip(p, q, r))) for p, q, r in zip(path, path[1:], path[2:])]


def summary(values):
    """mean, 99th percentile (nearest rank) and maximum; zeros for no values"""
    if not values:
        return {"mean": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {"mean": sum(values) / float(len(values)), "p99": ordered[int(round(0.99 * (len(ordered) - 1)))],
            "max": ordered[-1]}


def ik_affected(model):
    """the indices of the bones an IK moves: every IK link and everything below one"""
    links = {i for bone in model.bones if bone.ik for i in bone.ik["links"] if i is not None}
    out = set()
    for bone in model.bones:
        index, seen = bone.index, set()
        while index is not None and index not in seen:
            if index in links:
                out.add(bone.index)
                break
            seen.add(index)
            index = model.bones[index].parent
    return out


def measure(model, dance, names):
    """{"frames": [0, last], "paths": {name: [position per frame]}, "bones": {name: {speed, acceleration, ik_affected}}}"""
    if not dance.bones:
        raise ValueError("the dance has no bone keys")
    last = fk.last_frame(dance)
    track = fk.world_track(model, dance, names, 0, last)
    moved_by_ik = ik_affected(model)
    index = {}
    for bone in model.bones:
        index.setdefault(bone.name, bone.index)
    paths, bones = {}, {}
    for name in names:
        path = [position for position, _ in track[name]]
        paths[name] = path
        bones[name] = {"speed": summary(speeds(path)), "acceleration": summary(accelerations(path)),
                       "ik_affected": index[name] in moved_by_ik}
    return {"frames": [0, last], "paths": paths, "bones": bones}


def _rounded(bones):
    return {name: {"speed": {k: round(v, 6) + 0.0 for k, v in stats["speed"].items()},
                   "acceleration": {k: round(v, 6) + 0.0 for k, v in stats["acceleration"].items()},
                   "ik_affected": stats["ik_affected"]} for name, stats in bones.items()}


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
    """the inputs and the file written must all differ"""
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, MODEL and --out must all differ" % (seen[key], path))
        seen[key] = path


def run(dance_path, model_path, names=DEFAULT_BONES, out_path=None):
    started = time.time()
    check_distinct(dance_path, model_path, out_path)
    dance_full, model_full = os.path.abspath(dance_path), os.path.abspath(model_path)
    dance = vmd.load(dance_full)
    model = (pmd if model_full.lower().endswith(".pmd") else pmx).load(model_full)
    result = measure(model, dance, list(names))
    bones = _rounded(result["bones"])
    summary_ = {"in": dance_full, "model": model_full, "frames": result["frames"], "unit": UNIT, "bones": bones,
                "note": NOTE}
    if out_path:
        full = os.path.abspath(out_path)
        data = {"in": dance_full, "model": model_full, "frames": result["frames"], "unit": UNIT, "bones": bones,
                "paths": {name: [[round(c, 4) + 0.0 for c in p] for p in path] for name, path in result["paths"].items()}}
        write_bytes(full, (json.dumps(data, ensure_ascii=True) + "\n").encode("ascii"))
        summary_["out"] = full
    summary_["seconds"] = round(time.time() - started, 2)
    return summary_


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("model", help="the model (.pmx or .pmd)")
    p.add_argument("--bones", nargs="+", default=list(DEFAULT_BONES), help="the bones to follow (default: %s)"
                   % " ".join(DEFAULT_BONES))
    p.add_argument("--out", help="also write the world path of each bone to this JSON")
    args = p.parse_args(argv)
    try:
        result = run(args.dance, args.model, args.bones, args.out)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
