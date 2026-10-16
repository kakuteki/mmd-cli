"""Check how a dance's feet meet the floor as MMD shows it, measured apart from the contact layer's own judges
(tools/contact_layer.py, 2026-10-17), so that a review does not grade the layer by the yardstick it was built to meet.

    python tools/contact_check.py DANCE.vmd MODEL.pmx --report r.json [--before BEFORE.vmd] [--arrays a.npz]
        [--floor-y Y] [--first F] [--last F]

The legs are where MMD's IK puts them (tools/leg_ik.py, checked against MMD's renders), the shoes are every vertex skinned
on a leg's bones and mostly on its foot, skinned as tools/sink_check.py does (not the contact layer's lower shell), the
centre of mass is tools/wb_dynamics.py's (de Leva's 16 segments on the body's landmarks; the hips' middle when the
model has no body).  Measured on a dance (and on BEFORE the same way, with the changes between them):

* support: per frame how many shoes are on the floor, at CONTACT_CM (a05's 4 mm) and at SUPPORT_CM (1.2 cm: the human
  baseline's tolerance for people's planted feet and tools/wb_dynamics.py's): the shares of two, one and none;
* hover: neither shoe within CONTACT_CM while the lower is under HOVER_CM (a05 s11's 'hover support': nothing holds the
  body), its share, its runs of 6 frames or more a minute and where;
* held: a shoe held still (its lowest point moving under HELD_STEP_CM a frame) HELD_LOW_CM to HOVER_CM over the floor for
  HELD_MIN frames or more (a05 s11 (1)), the share of the feet's frames, the runs a minute, and for each run whether the
  other foot stands and how far the centre of mass's floor point lies outside that foot's sole;
* slides: each contact (a shoe within CONTACT_CM for 2 frames or more), the path of its slowest touching vertex (within
  TOUCH_CM of the lowest; a foot turning on its ball, its toe or its heel does not travel), the contacts sliding over
  3 cm and 10 cm a minute; the standing foot's speed in single support (its 50 and 90 % points, the share over 30 cm/s);
* air: runs with no shoe within SUPPORT_CM, a minute by length (1-3, 4-6, 7-12, 13+ frames) and for those of AIR_MIN
  frames and more the parabola (a frame each side) of the pelvis's height (下半身) and of the centre of mass's: their
  accelerations, the share falling slower than half of gravity;
* the pelvis on the floor: 下半身's and センター's downward acceleration on the frames a shoe is within SUPPORT_FALL_CM
  (the balance layer's support, 1.6 cm): its largest and the frames past BOUND (+ BOUND_TOL);
* with BEFORE: where each of BEFORE's contacts (CONTACT_CM, 3 frames and more) touched down and where that touching vertex
  is on that frame now (its shift along the floor), the contacts whose start or end moved by more than a frame, the
  knees' change of bend and the pelvis's change of height.

The report is ASCII-safe JSON; --arrays writes the per-frame curves.
"""
import argparse
import importlib.util
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_contact_check_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SC = _tool("sink_check")
IK = SC.IK

FPS = 30.0
UNIT_CM = 8.0
G = 122.5                       # units/s^2 at 8 cm a unit
SIDES = ("左", "右")
TAGS = {"左": "left", "右": "right"}
CONTACT_CM = 0.4                # a05's contact (4 mm)
SUPPORT_CM = 1.2                # the human baseline's planted foot and tools/wb_dynamics.py's contact
SUPPORT_FALL_CM = 1.6           # the balance layer's support (the frames whose pelvis is bound)
HOVER_CM = 4.0                  # a05 s11's band
HELD_LOW_CM = 0.4
HELD_STEP_CM = 0.05             # a05 s11 (1): still
HELD_MIN = 9                    # frames (0.3 s)
TOUCH_CM = 0.2                  # the shoe's vertices this near its lowest touch (sink_check's)
AIR_MIN = 4
BOUND = 122.0
BOUND_TOL = 0.5
FAST_STAND = 30.0               # cm/s


def runs(mask, n=1):
    return [(a, b) for a, b in SC.runs(mask) if b - a + 1 >= n]


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def _q(x, qs=(50, 90)):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return {("p%d" % q): _r(np.percentile(x, q), 2) for q in qs} if len(x) else None


def parab(y, a, b):
    i0, i1 = max(a - 1, 0), min(b + 1, len(y) - 1)
    if i1 - i0 < 2:
        return None
    t = np.arange(i0, i1 + 1) / FPS
    return float(2.0 * np.polyfit(t, y[i0:i1 + 1], 2)[0])


def hull(pts):
    pts = np.unique(np.round(np.asarray(pts, dtype=float), 9), axis=0)
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in pts[::-1]:
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])


def outside(p, poly):
    """how far the point p [2] lies outside the convex polygon poly [k, 2] (0 inside; units)"""
    poly = np.asarray(poly, dtype=float)
    if len(poly) == 0:
        return float("inf")

    def seg(a, b):
        ab = b - a
        t = np.clip(np.dot(p - a, ab) / max(float(np.dot(ab, ab)), 1e-18), 0.0, 1.0)
        return float(np.linalg.norm(p - (a + t * ab)))
    if len(poly) == 1:
        return float(np.linalg.norm(p - poly[0]))
    if len(poly) == 2:
        return seg(poly[0], poly[1])
    k = len(poly)
    cr = [(poly[(i + 1) % k][0] - poly[i][0]) * (p[1] - poly[i][1]) - (poly[(i + 1) % k][1] - poly[i][1]) * (p[0] - poly[i][0])
          for i in range(k)]
    if all(c >= 0 for c in cr) or all(c <= 0 for c in cr):
        return 0.0
    return min(seg(poly[i], poly[(i + 1) % k]) for i in range(k))


def centre_of_mass(model, motion, F, sol):
    """the centre of mass [F, 3] by tools/wb_dynamics.py (None-safe: the hips' middle when the model has not the body)"""
    if model is not None:
        try:
            wb = _tool("wb_dynamics")
            bl = _tool("balance_layer")
            lm, _ = wb.landmarks_from_body(bl.Body(model, motion, F))
            return wb.com(wb.segments(lm)), "wb_dynamics (de Leva's 16 segments)"
        except ValueError:
            pass
    return 0.5 * (sol["左"]["hip"] + sol["右"]["hip"]), "the hips' middle"


def measure(rig, doc, model, motion, frames, floor_y):
    """the per-frame curves of one dance"""
    frames = list(frames)
    F = len(frames)
    keys = IK.sample(rig, motion, frames)
    sol = IK.solve(rig, motion, frames, keys)
    state = IK._State(rig, keys)
    m = {"frames": np.array(frames)}
    for name, tag in (("下半身", "lower"), ("センター", "centre")):
        m[tag + "_y"] = np.array(state.world(rig.by_name[name])[0][:, 1])
    tr = SC.shoe_track(rig, doc, motion, frames, sol)
    pts = {}
    for s in SIDES:
        pv, ws, bones = SC.shoe_vertices(rig, doc, s)
        pts[s] = (pv, ws, bones)
        m["low_" + TAGS[s]] = (tr[s]["low"] - floor_y) * UNIT_CM
        m["slide_" + TAGS[s]] = tr[s]["slide"] * UNIT_CM * FPS
        m["knee_" + TAGS[s]] = SC.knee_bend(sol[s])
    com, how = centre_of_mass(model, motion, F, sol)
    m["com"] = com
    m["_how_com"] = how
    m["_sol"] = sol
    m["_pts"] = pts
    return m


def shoe_at(rig, m, s, t, pts):
    """a shoe's vertices [N, 3] at frame index t"""
    pv, ws, bones = pts[s]
    return SC.skin(rig, s, m["_sol"][s], pv, ws, bones, slice(t, t + 1))[0]


def sole_at(rig, doc, m, s, t, pts, floor_y):
    pv, ws, bones = pts[s]
    w = SC.skin(rig, s, m["_sol"][s], pv, ws, bones, slice(t, t + 1))[0]
    near = w[:, 1] <= max(floor_y, float(w[:, 1].min())) + SUPPORT_CM / UNIT_CM
    return hull(w[near][:, [0, 2]])


def report_one(rig, doc, m, floor_y):
    F = len(m["frames"])
    minutes = F / FPS / 60.0
    out = {"frames": F, "centre_of_mass": m["_how_com"]}
    lo = {s: m["low_" + TAGS[s]] for s in SIDES}
    for name, cm in (("contact_4mm", CONTACT_CM), ("support_1.2cm", SUPPORT_CM)):
        n = sum((lo[s] < cm).astype(int) for s in SIDES)
        out[name] = {"two_pct": _r(100.0 * np.mean(n == 2), 2), "one_pct": _r(100.0 * np.mean(n == 1), 2),
                     "none_pct": _r(100.0 * np.mean(n == 0), 2)}
    low = np.minimum(lo["左"], lo["右"])
    hov = (low >= CONTACT_CM) & (low < HOVER_CM)
    r6 = runs(hov, 6)
    out["hover"] = {"pct": _r(100.0 * hov.mean(), 3), "runs6_per_min": _r(len(r6) / minutes, 2),
                    "runs6_s": [[_r(m["frames"][a] / FPS, 2), _r((m["frames"][b] + 1) / FPS, 2)] for a, b in r6][:200]}
    held_frames, held_rows = 0, []
    for s, o in (("左", "右"), ("右", "左")):
        h = lo[s]
        still = np.zeros(F, dtype=bool)
        still[1:] = np.abs(np.diff(h)) < HELD_STEP_CM
        for a, b in runs((h >= HELD_LOW_CM) & (h < HOVER_CM) & still, HELD_MIN):
            held_frames += b - a + 1
            k = (a + b) // 2
            other_on = float(np.mean(lo[o][a:b + 1] < SUPPORT_CM))
            dist = None
            if other_on > 0.5:
                dist = outside(m["com"][k, [0, 2]], sole_at(rig, doc, m, o, k, m["_pts"], floor_y)) * UNIT_CM
            held_rows.append({"foot": TAGS[s], "s": [_r(m["frames"][a] / FPS, 2), _r((m["frames"][b] + 1) / FPS, 2)],
                              "height_cm": _r(np.median(h[a:b + 1]), 2), "other_on": _r(other_on, 2),
                              "com_outside_other_cm": _r(dist, 1) if dist is not None else None})
    out["held"] = {"pct": _r(100.0 * held_frames / (2.0 * F), 3), "runs_per_min": _r(len(held_rows) / minutes, 2),
                   "runs": held_rows[:300]}
    slides, stand = [], []
    for s, o in (("左", "右"), ("右", "左")):
        on = lo[s] < CONTACT_CM
        sl = m["slide_" + TAGS[s]]
        for a, b in runs(on, 2):
            path = float(np.sum(sl[a:b]) / FPS)
            slides.append(path)
        single = on & (lo[o] >= SUPPORT_CM)
        both = single.copy()
        both[:-1] &= on[1:]
        both[-1] = False
        stand += sl[both].tolist()
    slides = np.array(slides)
    stand = np.array(stand)
    out["slides"] = {"contacts": int(len(slides)), "over_3cm_per_min": _r(np.sum(slides > 3.0) / minutes, 2),
                     "over_10cm_per_min": _r(np.sum(slides > 10.0) / minutes, 2),
                     "path_cm_per_min": _r(float(slides.sum()) / minutes, 1),
                     "single_stand_speed_cm_s": _q(stand), "single_stand_over_30_pct":
                         _r(100.0 * np.mean(stand > FAST_STAND), 2) if len(stand) else None}
    none = (lo["左"] >= SUPPORT_CM) & (lo["右"] >= SUPPORT_CM)
    rr = runs(none)
    lens = np.array([b - a + 1 for a, b in rr]) if rr else np.zeros(0, int)
    out["air"] = {"runs_per_min": {k: _r(np.sum((lens >= lo_) & (lens <= hi_)) / minutes, 2)
                                   for k, (lo_, hi_) in {"1-3": (1, 3), "4-6": (4, 6), "7-12": (7, 12), "13+": (13, 10 ** 9)}.items()}}
    pel, com = [], []
    rows = []
    for a, b in rr:
        if b - a + 1 < AIR_MIN:
            continue
        p_ = parab(m["lower_y"], a, b)
        c_ = parab(m["com"][:, 1], a, b)
        pel.append(p_)
        com.append(c_)
        rows.append({"s": [_r(m["frames"][a] / FPS, 2), _r((m["frames"][b] + 1) / FPS, 2)], "frames": b - a + 1,
                     "pelvis_acc": _r(p_, 1), "com_acc": _r(c_, 1)})
    pel, com = np.array(pel, dtype=float), np.array(com, dtype=float)
    out["air"].update({"runs4": len(rows), "pelvis_acc": _q(pel, (10, 50, 90)), "com_acc": _q(com, (10, 50, 90)),
                       "pelvis_slower_than_half_g": _r(np.mean(pel > -G / 2.0), 3) if len(pel) else None,
                       "com_slower_than_half_g": _r(np.mean(com > -G / 2.0), 3) if len(com) else None,
                       "list": rows[:200]})
    floor = (lo["左"] < SUPPORT_FALL_CM) | (lo["右"] < SUPPORT_FALL_CM)
    fa = np.max([SC.down_acc(m["lower_y"]), SC.down_acc(m["centre_y"])], axis=0)
    past = floor & (fa > BOUND + BOUND_TOL)
    out["pelvis_floor"] = {"max": _r(fa[floor].max() if floor.any() else 0.0, 1), "past_bound": int(np.sum(past)),
                           "past_bound_s": [[_r(m["frames"][t] / FPS, 2), _r(fa[t], 1)] for t in np.flatnonzero(past)[:200]]}
    return out


def compare(rig, doc, mb, ma, floor_y):
    """the changes from BEFORE (mb) to AFTER (ma)"""
    F = len(mb["frames"])
    out = {"placements": {}, "timing": {}, "knees": {}, "pelvis": {}}
    shifts = []
    moved_start, moved_end, total = 0, 0, 0
    for s in SIDES:
        t = TAGS[s]
        on_b = mb["low_" + t] < CONTACT_CM
        on_a = ma["low_" + t] < CONTACT_CM
        rb, ra = runs(on_b, 3), runs(on_a, 3)
        for a, b in rb:
            wb, wa = shoe_at(rig, mb, s, a, mb["_pts"]), shoe_at(rig, ma, s, a, ma["_pts"])
            k = int(np.argmin(wb[:, 1]))                # the vertex that touched down, where it is now
            shifts.append(float(np.linalg.norm((wa[k] - wb[k])[[0, 2]])) * UNIT_CM)
            over = [(c, d) for c, d in ra if d >= a and c <= b]
            total += 1
            if not over:
                moved_start += 1
                moved_end += 1
                continue
            c = min(x[0] for x in over)
            d = max(x[1] for x in over)
            moved_start += int(abs(c - a) > 1)
            moved_end += int(abs(d - b) > 1)
        db = ma["knee_" + t] - mb["knee_" + t]
        out["knees"][t] = {"more_bent_max_deg": _r(max(0.0, float(db.max())), 2),
                           "straighter_max_deg": _r(max(0.0, float(-db.min())), 2),
                           "frames_over_10_deg": int(np.sum(np.abs(db) > 10.0))}
    shifts = np.array(shifts)
    out["placements"] = {"contacts": int(len(shifts)), "shift_cm": _q(shifts, (50, 95)),
                         "max_cm": _r(shifts.max(), 2) if len(shifts) else None,
                         "over_2cm": int(np.sum(shifts > 2.0))}
    out["timing"] = {"contacts": total, "start_moved": moved_start, "end_moved": moved_end}
    d = ma["lower_y"] - mb["lower_y"]
    out["pelvis"] = {"max_up_cm": _r(float(d.max()) * UNIT_CM, 2), "max_down_cm": _r(float(-d.min()) * UNIT_CM, 2),
                     "frames_changed": int(np.sum(np.abs(d) > 1e-4))}
    return out


def check(rig, doc, model, motion, before=None, floor_y=None, first=0, last=None):
    """the report (with "_arrays") of a dance, and of its change from `before` when given"""
    if last is None:
        last = fk.last_frame(motion) if before is None else max(fk.last_frame(motion), fk.last_frame(before))
    frames = list(range(first, last + 1))
    floor_y = SC.rest_floor(rig, doc) if floor_y is None else float(floor_y)
    ma = measure(rig, doc, model, motion, frames, floor_y)
    rep = {"floor_y": floor_y, "first": first, "last": last, "after": report_one(rig, doc, ma, floor_y)}
    arrays = {"frames": ma["frames"]}
    for k, v in ma.items():
        if not k.startswith("_") and k != "frames":
            arrays["after_" + k] = np.asarray(v)
    if before is not None:
        mb = measure(rig, doc, model, before, frames, floor_y)
        rep["before"] = report_one(rig, doc, mb, floor_y)
        rep["change"] = compare(rig, doc, mb, ma, floor_y)
        for k, v in mb.items():
            if not k.startswith("_") and k != "frames":
                arrays["before_" + k] = np.asarray(v)
    rep["_arrays"] = arrays
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("--report", required=True)
    ap.add_argument("--before")
    ap.add_argument("--arrays")
    ap.add_argument("--floor-y", type=float)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int)
    args = ap.parse_args(argv)
    t0 = time.time()
    with open(args.model, "rb") as f:
        data = f.read()
    rig = IK.LegRig.loads(data)
    doc = pmx_edit.loads(data)
    model = pmx.loads(data)
    rep = check(rig, doc, model, vmd.load(args.dance), vmd.load(args.before) if args.before else None, args.floor_y,
                args.first, args.last)
    arrays = rep.pop("_arrays")
    if args.arrays:
        np.savez_compressed(args.arrays, **arrays)
    rep["inputs"] = {"dance": args.dance, "before": args.before, "model": args.model}
    rep["seconds"] = round(time.time() - t0, 1)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=True, indent=1)
    a = rep["after"]
    print(json.dumps({"hover_pct": a["hover"]["pct"], "held_pct": a["held"]["pct"],
                      "slides10_per_min": a["slides"]["over_10cm_per_min"], "one_pct": a["support_1.2cm"]["one_pct"],
                      "pelvis_floor_past_bound": a["pelvis_floor"]["past_bound"], "seconds": rep["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
