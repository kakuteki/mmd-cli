"""Check a change of a dance that moves the whole figure up or down (the hover sink of tools/foot_layer.py, 2026-10-17)
from what the viewer sees, measured apart from the layer's own judges, so that a review does not grade the layer by the
yardstick it was built to meet.

    python tools/sink_check.py BEFORE.vmd AFTER.vmd MODEL.pmx --report r.json [--arrays a.npz] [--floor-y Y]
        [--bound 122] [--first F] [--last F]

Both dances are read on the same model, frame by frame from --first to --last (the later of the two dances' last bone
keys).  The legs are where MMD's IK puts them (tools/leg_ik.py, checked against MMD's renders); the rest is forward
kinematics.  Measured, before and after:

* the pelvis: 下半身's and センター's world heights (both above the legs' IK) and their downward acceleration (30 fps
  second differences, + down).  The frames past --bound (units/s^2: the balance layer's DOWN_ACC_MAX, 122, kept for the
  skirt: a pelvis falling faster than gravity throws the skirt up, HANDOVER 2026-10-16), split into the floor (a shoe
  supports) and the air (neither shoe supports for AIR_MIN frames running: there the dance's own fall is kept); and the
  frames the change takes past the bound (after past it and over before by more than 0.5);
* the change itself: 下半身's height after less before, its stretches (how deep, when) and the speed, acceleration and
  jerk it adds; the pelvis's jerk (third differences) before and after;
* the shoes: every vertex skinned wholly on a leg's bones and at least FOOT_SHARE on the foot (足首, 足首D, 足先EX,
  つま先), skinned linearly on the bones as the IK puts them.  Per shoe and frame its lowest point against the floor
  (--floor-y; the shoes' lowest point at rest when not given): under the floor by more than UNDER_CM, on it (within
  CONTACT_CM), supporting (within SUPPORT_CM, the balance layer's support), and its slide along the floor (the
  horizontal move to the next frame of the slowest of the vertices within TOUCH_CM of the lowest, while the shoe stays on
  the floor in both: a shoe turning on its ball or its toe does not slide, as a05's slowest point of the foot's line);
  a figure held by nothing (neither shoe within NOTHING_CM while the lower is under HOVER_CM: a05's
  'hover support', the yardstick the layer was made against, kept here for the comparison only);
* the knees: the bend (180 - the angle at the knee between the thigh and the shank, degrees), after less before.

The report is ASCII-safe JSON (bone names as they are, ensure_ascii); --arrays writes the per-frame curves (npz).
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_sink_check_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IK = _tool("leg_ik")
qrot = IK.qrot

FPS = 30.0
UNIT_CM = 8.0                   # one unit of Sour's Rin is 8 cm
SIDES = ("左", "右")
BOUND = 122.0                   # units/s^2: the pelvis's downward acceleration where a foot holds the body up (the balance
                                # layer's DOWN_ACC_MAX: the real g at 8 cm a unit, 122.5)
BOUND_TOL = 0.5                 # past the bound by more than this (as the balance layer's report counts)
AIR_MIN = 4                     # frames: neither shoe supporting this long is the air (the balance layer's AIR_MIN)
SUPPORT_CM = 1.6                # a shoe this low supports (the balance layer's SUPPORT_H, a05's FLY)
CONTACT_CM = 0.5                # a shoe this low is on the floor (for the slides)
UNDER_CM = 0.1                  # a shoe lower than the floor by more than this is under it
TOUCH_CM = 0.2                  # the shoe's vertices this close to its lowest are the ones touching
NOTHING_CM = 0.4                # a05 s11: neither shoe within this ...
HOVER_CM = 4.0                  # ... and the lower one under this: nothing holds the body
FOOT_SHARE = 0.5                # a vertex this much on the foot's bones belongs to the shoe
CHUNK = 256                     # frames skinned at a time
LEG_BONES = ("足", "ひざ", "足首", "つま先", "足D", "ひざD", "足首D", "足先EX")
FOOT_BONES = ("足首", "足首D", "足先EX", "つま先")
# the solved bone (leg_ik.solve's keys) that each leg bone moves with: the D bones are their bones' turns appended x 1 on
# the same chain, つま先 (rarely a deforming bone) turns with the foot
FOLLOWS = {"足": ("hip", "q_thigh"), "足D": ("hip", "q_thigh"), "ひざ": ("knee", "q_shin"), "ひざD": ("knee", "q_shin"),
           "足首": ("ankle", "q_foot"), "足首D": ("ankle", "q_foot"), "つま先": ("toe", "q_foot"), "足先EX": ("ex", "q_ex")}
TAGS = {"左": "left", "右": "right"}


def runs(mask):
    """[(a, b)] inclusive runs of True"""
    m = np.asarray(mask, dtype=bool)
    out = []
    i, n = 0, len(m)
    while i < n:
        if m[i]:
            j = i
            while j + 1 < n and m[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def long_runs(mask, n):
    """mask with only its runs of n or more"""
    out = np.zeros(len(mask), dtype=bool)
    for a, b in runs(mask):
        if b - a + 1 >= n:
            out[a:b + 1] = True
    return out


def down_acc(y):
    """the downward acceleration [F] (units/s^2, + down) of heights y [F]: 30 fps second differences, 0 at the ends"""
    y = np.asarray(y, dtype=float)
    a = np.zeros(len(y))
    if len(y) >= 3:
        a[1:-1] = -(y[2:] - 2.0 * y[1:-1] + y[:-2]) * FPS * FPS
    return a


def jerk(y):
    """the jerk [F] (units/s^3) of heights y [F]: 30 fps third differences (placed on the second of the four frames)"""
    y = np.asarray(y, dtype=float)
    j = np.zeros(len(y))
    if len(y) >= 4:
        j[1:-2] = (y[3:] - 3.0 * y[2:-1] + 3.0 * y[1:-2] - y[:-3]) * FPS ** 3
    return j


def shoe_vertices(rig, doc, side):
    """(points [N, 3] at rest, weights [N, B], the bones [B] (names)) of the vertices of `side`'s shoe: skinned wholly on
    that leg's bones (LEG_BONES that the model has) and at least FOOT_SHARE on the foot's (FOOT_BONES)"""
    bones = [n for n in LEG_BONES if (side + n) in rig.by_name]
    index = {rig.by_name[side + n]: k for k, n in enumerate(bones)}
    foot = {index[rig.by_name[side + n]] for n in FOOT_BONES if (side + n) in rig.by_name}
    pts, ws = [], []
    for v in doc.vertices:
        w = np.zeros(len(bones))
        other = 0.0
        for b, x in v.pairs():
            if b in index:
                w[index[b]] += x
            else:
                other += x
        if other > 1e-3 or w.sum() < 0.999 or sum(w[k] for k in foot) < FOOT_SHARE:
            continue
        pts.append(v.position())
        ws.append(w / w.sum())
    if not pts:
        raise ValueError("no vertex of the %s shoe is skinned on its leg's bones and mostly on its foot" % side)
    return np.array(pts, dtype=float), np.array(ws), bones


def rest_floor(rig, doc):
    """the floor at rest: the lowest point of the shoes' vertices (the soles the dance's tracer stood on the floor)"""
    return float(min(shoe_vertices(rig, doc, s)[0][:, 1].min() for s in rig.sides))


def skin(rig, side, sol_side, pts, ws, bones, sl):
    """the shoe's vertices [f, N, 3] at the frames `sl` (a slice of the solve) skinned linearly as MMD does"""
    out = 0.0
    for k, name in enumerate(bones):
        if not np.any(ws[:, k] > 0.0):
            continue
        pkey, qkey = FOLLOWS[name]
        rest = np.array(rig.bones[rig.by_name[side + name]].position, dtype=float)
        p = sol_side[pkey][sl][:, None, :]
        q = sol_side[qkey][sl][:, None, :]
        out = out + ws[None, :, k, None] * (p + qrot(q, (pts - rest)[None]))
    return out


def shoe_track(rig, doc, motion, frames, sol=None):
    """side -> {"low": the shoe's lowest point [F] (world y), "argmin": its vertex [F], "slide": the horizontal move to
    the next frame of the slowest touching vertex [F] (units; the last frame 0), "touching": how many touch [F]}"""
    frames = list(frames)
    F = len(frames)
    if sol is None:
        sol = IK.solve(rig, motion, frames)
    out = {}
    touch = TOUCH_CM / UNIT_CM
    for s in rig.sides:
        pts, ws, bones = shoe_vertices(rig, doc, s)
        low = np.zeros(F)
        arg = np.zeros(F, dtype=int)
        slide = np.zeros(F)
        count = np.zeros(F, dtype=int)
        for a in range(0, F, CHUNK):
            b = min(F, a + CHUNK + 1)               # one frame more: the slide to the next frame
            w = skin(rig, s, sol[s], pts, ws, bones, slice(a, b))
            y = w[:, :, 1]
            n = min(CHUNK, F - a)
            low[a:a + n] = y[:n].min(axis=1)
            arg[a:a + n] = y[:n].argmin(axis=1)
            for i in range(n):
                near = y[i] <= low[a + i] + touch
                count[a + i] = int(near.sum())
                if i + 1 < len(w):
                    d = w[i + 1, near][:, [0, 2]] - w[i, near][:, [0, 2]]
                    slide[a + i] = float(np.hypot(d[:, 0], d[:, 1]).min())
        out[s] = {"low": low, "argmin": arg, "slide": slide, "touching": count}
    return out


def knee_bend(sol_side):
    """the knee's bend [F] (degrees: 180 less the angle at the knee between the thigh and the shank)"""
    u = sol_side["hip"] - sol_side["knee"]
    v = sol_side["ankle"] - sol_side["knee"]
    c = np.sum(u * v, axis=1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
    return 180.0 - np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def measure(rig, doc, motion, frames, floor_y):
    """the per-frame curves of one dance (see the module docstring)"""
    frames = list(frames)
    keys = IK.sample(rig, motion, frames)
    sol = IK.solve(rig, motion, frames, keys)
    state = IK._State(rig, keys)                    # the forward kinematics the solve starts from (above the IK)
    m = {}
    for name in ("下半身", "センター"):
        if name not in rig.by_name:
            raise ValueError("the model has no %s" % name)
        m[name + "_y"] = np.array(state.world(rig.by_name[name])[0][:, 1])
    feet = shoe_track(rig, doc, motion, frames, sol)
    sup = {}
    for s in rig.sides:
        h = (feet[s]["low"] - floor_y) * UNIT_CM
        m["low_" + TAGS[s]] = feet[s]["low"]
        m["slide_" + TAGS[s]] = feet[s]["slide"] * UNIT_CM * FPS                    # cm/s
        m["knee_" + TAGS[s]] = knee_bend(sol[s])
        sup[s] = h < SUPPORT_CM
    m["air"] = long_runs(~sup["左"] & ~sup["右"], AIR_MIN) if len(sup) == 2 else np.zeros(len(frames), bool)
    return m


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def side_report(m, s, floor_y):
    t = TAGS[s]
    h = (m["low_" + t] - floor_y) * UNIT_CM
    on = h < CONTACT_CM
    both = on.copy()
    both[:-1] &= on[1:]
    both[-1] = False
    sl = m["slide_" + t][both]
    under = h < -UNDER_CM
    return {"under_floor": {"frames": int(under.sum()), "deepest_cm": _r(max(0.0, -float(h.min())), 3)},
            "on_floor": {"frames": int(on.sum())},
            "support": {"frames": int((h < SUPPORT_CM).sum())},
            "slide": {"frames": int(both.sum()), "median_cm_s": _r(np.median(sl)) if len(sl) else None,
                      "p95_cm_s": _r(np.percentile(sl, 95)) if len(sl) else None,
                      "max_cm_s": _r(sl.max()) if len(sl) else 0.0,
                      "frames_over_5cm_s": int((sl > 5.0).sum()), "frames_over_10cm_s": int((sl > 10.0).sum())}}


def nothing_report(m, floor_y, F):
    hl = (m["low_left"] - floor_y) * UNIT_CM
    hr = (m["low_right"] - floor_y) * UNIT_CM
    lo = np.minimum(hl, hr)
    mask = (lo > NOTHING_CM) & (lo < HOVER_CM)
    long6 = [(a, b) for a, b in runs(mask) if b - a + 1 >= 6]
    minutes = F / FPS / 60.0
    return {"frames": int(mask.sum()), "pct": _r(100.0 * mask.mean() if F else 0.0, 3),
            "runs_6_or_more": len(long6), "runs_6_or_more_per_min": _r(len(long6) / minutes if minutes else 0.0),
            "_runs6": long6}


def compare(rig, doc, before, after, floor_y=None, bound=BOUND, first=0, last=None):
    """the report (a dict; "_arrays" holds the curves) of BEFORE against AFTER on the model (rig: leg_ik.LegRig, doc:
    pmx_edit Document)"""
    if last is None:
        last = max(fk.last_frame(before), fk.last_frame(after))
    frames = list(range(first, last + 1))
    F = len(frames)
    floor_y = rest_floor(rig, doc) if floor_y is None else float(floor_y)
    mb = measure(rig, doc, before, frames, floor_y)
    ma = measure(rig, doc, after, frames, floor_y)
    rep = {"frames": F, "first": first, "last": last, "floor_y": floor_y, "bound_units_s2": bound,
           "units": {"acc": "units/s^2 (+ down)", "jerk": "units/s^3", "unit_cm": UNIT_CM},
           "pelvis": {}, "feet": {}, "knees": {}}
    for name in ("下半身", "センター"):
        a0, a1 = down_acc(mb[name + "_y"]), down_acc(ma[name + "_y"])
        row = {}
        for tag, a, m in (("before", a0, mb), ("after", a1, ma)):
            air = m["air"]
            past = a > bound + BOUND_TOL
            row[tag] = {"max_floor": _r(a[~air].max() if (~air).any() else 0.0, 1),
                        "max_air": _r(a[air].max(), 1) if air.any() else None,
                        "past_bound_floor": int((past & ~air).sum()), "past_bound_air": int((past & air).sum()),
                        "over_98_pct": _r(100.0 * float(np.mean(a > 98.0)), 3)}
        new = np.flatnonzero((a1 > bound + BOUND_TOL) & (a1 > a0 + BOUND_TOL))
        row["new_past_bound"] = [{"frame": int(frames[i]), "s": _r(frames[i] / FPS), "before": _r(a0[i], 1),
                                  "after": _r(a1[i], 1), "air_after": bool(ma["air"][i]), "air_before": bool(mb["air"][i])}
                                 for i in new[:200]]
        row["new_past_bound_count"] = int(len(new))
        row["new_past_bound_floor"] = int(sum(1 for i in new if not ma["air"][i]))
        row["raised_by_more_than_5"] = int(np.sum(a1 > a0 + 5.0))
        rep["pelvis"][name] = row
    d = ma["下半身_y"] - mb["下半身_y"]
    stretches = []
    for a, b in runs(np.abs(d) > 1e-3):
        k = a + int(np.argmax(np.abs(d[a:b + 1])))
        stretches.append({"first": int(frames[a]), "last": int(frames[b]), "s": [_r(frames[a] / FPS), _r(frames[b] / FPS)],
                          "deepest_cm": _r(abs(d[k]) * UNIT_CM, 3), "down": bool(d[k] < 0.0)})
    vd = np.abs(np.gradient(d)) * FPS * UNIT_CM if F > 1 else np.zeros(F)
    rep["change"] = {"stretches": stretches, "frames_changed": int((np.abs(d) > 1e-3).sum()),
                     "deepest_cm": _r(np.abs(d).max() * UNIT_CM, 3) if F else 0.0,
                     "speed_max_cm_s": _r(vd.max() if F else 0.0),
                     "acc_max_units_s2": _r(np.abs(down_acc(d)).max() if F else 0.0, 1),
                     "jerk_max_units_s3": _r(np.abs(jerk(d)).max() if F else 0.0, 0)}
    jb, ja = np.abs(jerk(mb["下半身_y"])), np.abs(jerk(ma["下半身_y"]))
    near = np.zeros(F, dtype=bool)
    for a, b in runs(np.abs(d) > 1e-3):
        near[max(0, a - 3):min(F, b + 4)] = True
    rep["pelvis_jerk"] = {"p99_before": _r(np.percentile(jb, 99) if F else 0.0, 0),
                          "p99_after": _r(np.percentile(ja, 99) if F else 0.0, 0),
                          "max_before": _r(jb.max() if F else 0.0, 0), "max_after": _r(ja.max() if F else 0.0, 0),
                          "near_change_max_before": _r(jb[near].max(), 0) if near.any() else None,
                          "near_change_max_after": _r(ja[near].max(), 0) if near.any() else None}
    for s in rig.sides:
        rep["feet"][s] = {"before": side_report(mb, s, floor_y), "after": side_report(ma, s, floor_y)}
        db = ma["knee_" + TAGS[s]] - mb["knee_" + TAGS[s]]
        sup = (ma["low_" + TAGS[s]] - floor_y) * UNIT_CM < SUPPORT_CM
        rep["knees"][s] = {"more_bent_max_deg": _r(max(0.0, float(db.max())), 3),
                           "straighter_max_deg": _r(max(0.0, float(-db.min())), 3),
                           "frames_over_5_deg": int((np.abs(db) > 5.0).sum()),
                           "frames_over_10_deg": int((np.abs(db) > 10.0).sum()),
                           "nearly_straight_supporting": [int(((mb["knee_" + TAGS[s]] < 5.0) & sup).sum()),
                                                          int(((ma["knee_" + TAGS[s]] < 5.0) & sup).sum())]}
    nb, na = nothing_report(mb, floor_y, F), nothing_report(ma, floor_y, F)
    rep["held_by_nothing"] = {"before": {k: v for k, v in nb.items() if not k.startswith("_")},
                              "after": {k: v for k, v in na.items() if not k.startswith("_")},
                              "after_runs6_s": [[_r(frames[a] / FPS), _r((frames[b] + 1) / FPS)] for a, b in na["_runs6"]][:100]}
    rep["_arrays"] = {"before": mb, "after": ma, "frames": np.array(frames)}
    return rep


def arrays_of(rep):
    """the curves of a report as flat npz names (ASCII)"""
    names = {"下半身_y": "lower_body_y", "センター_y": "centre_y"}
    out = {"frames": rep["_arrays"]["frames"]}
    for tag in ("before", "after"):
        for k, v in rep["_arrays"][tag].items():
            out["%s_%s" % (tag, names.get(k, k))] = np.asarray(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("model")
    ap.add_argument("--report", required=True)
    ap.add_argument("--arrays")
    ap.add_argument("--floor-y", type=float)
    ap.add_argument("--bound", type=float, default=BOUND)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int)
    args = ap.parse_args(argv)
    t0 = time.time()
    with open(args.model, "rb") as f:
        data = f.read()
    rig = IK.LegRig.loads(data)
    doc = pmx_edit.loads(data)
    rep = compare(rig, doc, vmd.load(args.before), vmd.load(args.after), args.floor_y, args.bound, args.first, args.last)
    if args.arrays:
        np.savez_compressed(args.arrays, **arrays_of(rep))
    rep.pop("_arrays")
    rep["inputs"] = {"before": args.before, "after": args.after, "model": args.model}
    rep["seconds"] = round(time.time() - t0, 1)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=True, indent=1)
    p = rep["pelvis"]["下半身"]
    print(json.dumps({"frames": rep["frames"], "lower_body_new_past_bound": p["new_past_bound_count"],
                      "on_the_floor": p["new_past_bound_floor"], "after_max_floor": p["after"]["max_floor"],
                      "deepest_cm": rep["change"]["deepest_cm"], "seconds": rep["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
