"""Measure a retargeted dance against the dance it came from, from what the viewer sees: does a hand that touches the
body in the source still touch the same part of the target, does an arm go into the target's body, does a foot that
stands on the floor in the source stand still on the floor in the target, and does a foot on its toe reach the floor.

    python tools/retarget_check.py SOURCE.vmd SOURCE_BODY TARGET.vmd TARGET.pmx --report r.json [--arrays a.npz]
                                   [--last F]

SOURCE_BODY is what tools/retarget.py takes (a model or a .json body); TARGET.vmd is any dance of the target (the
retargeted one, or the source dance itself read on the target, to see what the retarget changed).  The measures are
made apart from tools/retarget.py's own arithmetic (it is used only to read the bodies): the bones by forward kinematics
(tools/motor_layer.py), the legs as MMD's IK puts them (tools/leg_ik.py), the target's shoes as their skinned vertices
(tools/sink_check.py), and the body's surfaces as the nearest of its vertices, signed by that vertex's normal (no grid).

* contacts: a hand point (the palm's middle, the middle finger's tip) of the source within TOUCH of a part of its body
  (head with what rides on 頭, chest, belly, hips, each thigh) touches it.  On those frames the target's same point is
  'kept' when its distance to the same part of the target is within KEEP of the source's (the source's own distance,
  not less than 0), 'lost' when it is more than LOST off (or LOST inside).  Per part: the touching frames, the share
  kept, the lost runs.
* arms in the body: the target's arm as capsules on its bones (the upper arm, the forearm, the hand; radii the 60th
  percentile of their vertices' distance from the bone), the deepest it goes into a part (the upper arm's half by the shoulder
  arm not tested against the trunk, the hand not against a part the source's hand touches then).  The frames over 0.5
  and 1 cm, the deepest, the runs.  The same for the source's arm in its own body.
* plants: a source foot stands where its foot IK goal or toe IK goal (forward kinematics: where the foot is meant to
  be) lies within PLANT_EPS of its rest height and moves less than STILL a frame, for PLANT_MIN frames; on its toe
  when pitched more than 4 degrees.  On those frames the target's shoe: its lowest point's height over the floor (the
  shoes' lowest point at rest) and its slide (sink_check's: the slowest touching vertex's move), per plant the path.
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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mmd_cli.formats import vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_retarget_check_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RT = _tool("retarget")
ML = _tool("motor_layer")
LI = _tool("leg_ik")
SC = _tool("sink_check")

SIDES = ("左", "右")
UNIT_CM = 8.0
TOUCH = 0.15                    # units (1.2 cm): a source hand point this close to a part touches it
KEEP = 0.125                    # units (1 cm): the target's point within this of the source's distance keeps the touch
LOST = 0.25                     # units (2 cm): more than this off (or inside) loses it
PLANT_EPS = 0.05                # units (4 mm, a05's contact): a goal this close to its rest height is on the floor
STILL = 0.025                   # units a frame
PLANT_MIN = 3
TOE_PITCH = 4.0
VOXEL = 0.04
SIDE_PLANE = 0.3                # units: a point this close beside its nearest vertex is measured to that vertex's plane
SKIP_SHOULDER = 0.5
PARTS = {"head": ("頭", ("頭",)), "chest": ("上半身2", ("上半身2", "胸椎上部")), "belly": ("上半身", ("上半身", "腰椎上部")),
         "hips": ("下半身", ("下半身", "腰")), "thigh_左": ("左足", ("左足", "左足D")), "thigh_右": ("右足", ("右足", "右足D"))}


def runs(mask, min_len=1):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]]).astype(np.int8)
    d = np.diff(m)
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1) if b - a + 1 >= min_len]


def quant(x, qs=(50, 90, 99, 100)):
    x = np.asarray(x, dtype=np.float64)
    if not len(x):
        return None
    return {("max" if q == 100 else "p%d" % q): round(float(np.percentile(x, q)), 4) for q in qs}


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)


class Pose:
    """forward kinematics of a body (tools/retarget.Body) under a motion, every frame, with tools/motor_layer.py"""

    def __init__(self, body, motion, frames):
        self.body = body
        self.sk = ML.Skeleton(body.model)
        self.frames = frames
        self.motion = motion
        self._w = {}

    def get(self, names):
        need = [n for n in names if n not in self._w and self.sk.has(n)]
        if need:
            order = self.sk.closure([self.sk.i(n) for n in need])
            keys = ML.sample_keys(self.motion, self.sk, order, len(self.frames))
            wpos, wrot = ML.fk_all(self.sk, keys, order, len(self.frames))
            for k in order:
                self._w[self.sk.bones[k].name] = (wpos[k], wrot[k])
        return {n: self._w[n] for n in names if n in self._w}


class Part:
    """a part's vertices (voxel-thinned) in its riding bone's rest frame with their normals: the nearest vertex's
    distance, signed by its normal"""

    def __init__(self, body, part):
        ride, bones = PARTS[part]
        idx = [body.i(n) for n in bones if body.has(n)]
        if part == "head" and body.has("頭"):
            head = body.i("頭")
            idx += [b.index for b in body.model.bones if b.parent == head]
        m = np.isin(body.main_bone, idx) if len(body.vertices) else np.zeros(0, bool)
        self.ok = body.has(ride) and m.sum() >= 8
        if not self.ok:
            return
        self.ride = ride
        P = body.vertices[m] - body.rest(ride)
        N = unit(body.normals[m])
        cell = np.floor(P / VOXEL).astype(np.int64)
        _, first = np.unique(cell, axis=0, return_index=True)
        self.P, self.N = P[first], N[first]
        self.centre = 0.5 * (self.P.min(axis=0) + self.P.max(axis=0))
        self.radius = float(np.linalg.norm(self.P - self.centre, axis=1).max())

    def distance(self, q, reach=1.5):
        """signed distances of points q [n, 3] (in the part's frame); points farther than `reach` from the part's bounding
        sphere get their distance to the sphere"""
        q = np.asarray(q, dtype=np.float64)
        out = np.linalg.norm(q - self.centre, axis=1) - self.radius
        near = np.flatnonzero(out < reach)
        step = max(16, int(2.0e6 // len(self.P)))
        for a in range(0, len(near), step):
            i = near[a:a + step]
            d2 = np.sum((q[i, None, :] - self.P[None, :, :]) ** 2, axis=-1)
            j = np.argmin(d2, axis=1)
            off = q[i] - self.P[j]
            along = np.sum(off * self.N[j], axis=1)
            euclid = np.sqrt(d2[np.arange(len(i)), j])
            side = np.sqrt(np.maximum(euclid ** 2 - along ** 2, 0.0))
            s = np.sign(along)
            s[s == 0] = 1.0
            # close to the surface, the distance to the nearest vertex's tangent plane (a thin sampling of a smooth
            # surface overstates the plain distance by up to half the spacing)
            out[i] = np.where(side < SIDE_PLANE, along, s * euclid)
        return out


def parts_of(body):
    out = {}
    for part in PARTS:
        p = Part(body, part)
        if p.ok:
            out[part] = p
    return out


def hand_points(pose, side):
    w = pose.get([side + "手首", side + "中指１", side + "中指２", side + "中指３"])
    palm = 0.5 * (w[side + "手首"][0] + w[side + "中指１"][0])
    tip = w[side + "中指３"][0] + 0.6 * (w[side + "中指３"][0] - w[side + "中指２"][0])
    return {"palm": palm, "tip": tip}


def part_distances(pose, parts, points):
    """part -> point -> signed distances [F]"""
    rides = pose.get(sorted({p.ride for p in parts.values()}))
    out = {}
    for name, part in parts.items():
        pos, rot = rides[part.ride]
        out[name] = {k: part.distance(ML.qrot(ML.qconj(rot), P - pos)) for k, P in points.items()}
    return out


def contacts(src_pose, src_parts, tgt_pose, tgt_parts):
    out = {}
    for side in SIDES:
        if not all(src_pose.sk.has(side + n) for n in ("手首", "中指１", "中指２", "中指３")):
            continue
        ds = part_distances(src_pose, src_parts, hand_points(src_pose, side))
        dt = part_distances(tgt_pose, tgt_parts, hand_points(tgt_pose, side))
        rows = {}
        for part in ds:
            if part not in dt:
                continue
            point = np.where(ds[part]["palm"] <= ds[part]["tip"], "palm", "tip")
            d_s = np.where(point == "palm", ds[part]["palm"], ds[part]["tip"])
            d_t = np.where(point == "palm", dt[part]["palm"], dt[part]["tip"])
            touch = d_s < TOUCH
            want = np.maximum(d_s, 0.0)
            kept = touch & (np.abs(d_t - want) <= KEEP)
            lost = touch & ((d_t - want > LOST) | (d_t < -LOST))
            rows[part] = {"source_touch_frames": int(touch.sum()), "kept_frames": int(kept.sum()),
                          "kept_share": round(float(kept.sum() / touch.sum()), 4) if touch.any() else None,
                          "lost_runs": [[a, b] for a, b in runs(lost)],
                          "source_cm": quant(d_s[touch] * UNIT_CM, (50,)), "target_cm": quant(d_t[touch] * UNIT_CM, (50, 90))}
        out[side] = rows
    return out


def arm_radii(body, side):
    def radius(bones, a, b, default):
        idx = [body.i(side + n) for n in bones if body.has(side + n)]
        m = np.isin(body.main_bone, idx) if len(body.vertices) else np.zeros(0, bool)
        if m.sum() < 8:
            return default
        A, B = body.rest(side + a), body.rest(side + b)
        P = body.vertices[m]
        t = np.clip(np.sum((P - A) * (B - A), axis=1) / max(float(np.sum((B - A) ** 2)), 1e-9), 0, 1)
        return float(np.percentile(np.linalg.norm(P - (A + t[:, None] * (B - A)), axis=1), 60))
    return (radius(("腕", "腕捩", "腕捩1", "腕捩2", "腕捩3", "腕W"), "腕", "ひじ", 0.35),
            radius(("ひじ", "手捩", "手捩1", "手捩2", "手捩3"), "ひじ", "手首", 0.3),
            radius(("手首",), "手首", "中指１", 0.25))


def arms_in(pose, body, parts, touching=None):
    """per side: the deepest the arm goes into a part per frame [F] and the summary"""
    out = {}
    for side in SIDES:
        names = [side + n for n in ("腕", "ひじ", "手首")]
        if not all(pose.sk.has(n) for n in names):
            continue
        w = pose.get(names)
        hp = hand_points(pose, side)
        S, E, W = (w[n][0] for n in names)
        r = arm_radii(body, side)
        pts, rad, seg, share = [], [], [], []
        for n, (a, b, rr) in enumerate(((S, E, r[0]), (E, W, r[1]), (W, hp["tip"], r[2]))):
            for t in np.linspace(0.0, 1.0, 9):
                pts.append(a + t * (b - a))
                rad.append(rr)
                seg.append(n)
                share.append(t)
        rad, seg, share = np.array(rad), np.array(seg), np.array(share)
        deep = np.zeros(len(S))
        dist = part_distances(pose, parts, {i: p for i, p in enumerate(pts)})
        for part, by in dist.items():
            for i, d in by.items():
                if part in ("chest", "belly") and seg[i] == 0 and share[i] < SKIP_SHOULDER:
                    continue
                pen = rad[i] - d
                if seg[i] == 2 and touching is not None and part in touching.get(side, {}):
                    pen = np.where(touching[side][part], 0.0, pen)
                deep = np.maximum(deep, pen)
        deep = np.maximum(deep, 0.0)
        out[side] = {"frames_over_0.5cm": int(np.sum(deep > 0.0625)), "frames_over_1cm": int(np.sum(deep > 0.125)),
                     "deepest_cm": round(float(deep.max()) * UNIT_CM, 3) if len(deep) else 0.0,
                     "runs_over_1cm": [[a, b] for a, b in runs(deep > 0.125)], "_deep": deep}
    return out


def source_plants(pose, body):
    """per side: [(first, last, toe)] where the source's foot stands (see the module's doc): points along the line from
    the foot IK goal (and 0.3 of the foot behind it, the heel) to the toe IK goal, each as high over the floor as the
    goals are over their rest heights between them; a frame stands when one of them is on the floor and still (a foot
    turning on its ball stands on the ball)"""
    out = {}
    ts = np.array([-0.3, 0.0, 1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6, 1.0])
    for side in SIDES:
        w = pose.get([side + "足ＩＫ", side + "つま先ＩＫ"])
        ga, qa = w[side + "足ＩＫ"]
        gt, _ = w[side + "つま先ＩＫ"]
        ha = ga[:, 1] - body.rest(side + "足ＩＫ")[1]
        ht = gt[:, 1] - body.rest(side + "つま先ＩＫ")[1]
        P = ga[:, None, :] + ts[None, :, None] * (gt - ga)[:, None, :]
        H = ha[:, None] + ts[None, :] * (ht - ha)[:, None]
        v = np.zeros(H.shape)
        v[1:] = np.linalg.norm(np.diff(P[:, :, [0, 2]], axis=0), axis=2)
        still = np.minimum(v, np.concatenate([v[1:], v[-1:]], axis=0)) < STILL
        on = np.any((np.abs(H) < PLANT_EPS) & still, axis=1)
        fwd = ML.qrot(qa, np.broadcast_to(np.array([0.0, 0.0, -1.0]), qa[:, :3].shape))
        pitch = np.degrees(np.arcsin(np.clip(-fwd[:, 1], -1, 1)))
        out[side] = [(a, b, bool(np.median(pitch[a:b + 1]) > TOE_PITCH)) for a, b in runs(on, PLANT_MIN)]
    return out


def plants(src_pose, src_body, tgt_motion, tgt_body, frames):
    if getattr(tgt_body, "doc", None) is None:
        return {"error": "the target is not a PMX read with its vertices"}
    rig = tgt_body.rig()
    try:
        floor = SC.rest_floor(rig, tgt_body.doc)
    except ValueError as exc:                   # no shoe skinned on the legs
        return {"error": str(exc)}
    feet = SC.shoe_track(rig, tgt_body.doc, tgt_motion, list(frames))
    found = source_plants(src_pose, src_body)
    out = {}
    for side in SIDES:
        f = feet[side]
        h = (f["low"] - floor) * UNIT_CM
        sl = f["slide"] * UNIT_CM
        fl, paths, toe_fl = [], [], []
        for a, b, toe in found[side]:
            fl.append(h[a:b + 1])
            paths.append(float(sl[a:b].sum()))
            if toe:
                toe_fl.append(h[a:b + 1])
        fl = np.concatenate(fl) if fl else np.zeros(0)
        tf = np.concatenate(toe_fl) if toe_fl else np.zeros(0)
        out[side] = {"plants": len(found[side]), "frames": int(len(fl)), "float_cm": quant(np.maximum(fl, 0.0)),
                     "float_over_1cm_pct": round(100.0 * float(np.mean(fl > 1.0)), 3) if len(fl) else None,
                     "under_floor_frames": int(np.sum(fl < -0.1)),
                     "slide_path_cm": quant(paths), "plants_sliding_over_1cm": int(np.sum(np.array(paths) > 1.0)),
                     "toe_plants": int(sum(1 for _, _, t in found[side] if t)), "toe_float_cm": quant(np.maximum(tf, 0.0)),
                     "toe_float_over_1cm_pct": round(100.0 * float(np.mean(tf > 1.0)), 3) if len(tf) else None}
    return out


def measure(src_motion, src_body, tgt_motion, tgt_body, last=None):
    """the report over frames 0..last (see the module's doc); arrays of the per-frame depths under "_arrays\""""
    if last is None:
        last = max(max(k.frame for k in src_motion.bones), max(k.frame for k in tgt_motion.bones))
    first = 0
    frames = np.arange(first, last + 1)
    sp, tp = Pose(src_body, src_motion, frames), Pose(tgt_body, tgt_motion, frames)
    spa, tpa = parts_of(src_body), parts_of(tgt_body)
    rep = {"frames": [int(first), int(last)], "parts_source": sorted(spa), "parts_target": sorted(tpa)}
    rep["contacts"] = contacts(sp, spa, tp, tpa)
    touching = {}
    for side in SIDES:
        if not all(sp.sk.has(side + n) for n in ("手首", "中指１", "中指２", "中指３")):
            continue
        ds = part_distances(sp, spa, hand_points(sp, side))
        touching[side] = {part: np.minimum(v["palm"], v["tip"]) < TOUCH for part, v in ds.items()}
    t_in = arms_in(tp, tgt_body, tpa, touching)
    s_in = arms_in(sp, src_body, spa)
    arrays = {}
    for tag, d in (("target", t_in), ("source", s_in)):
        for side, row in d.items():
            arrays["arm_in_%s_%s" % (tag, {"左": "left", "右": "right"}[side])] = row.pop("_deep")
    rep["arms_in_body"] = {"target": t_in, "source": s_in}
    rep["plants"] = plants(sp, src_body, tgt_motion, tgt_body, frames)
    rep["summary"] = summary(rep)
    rep["_arrays"] = arrays
    return rep


def summary(rep):
    touch = kept = 0
    lost = 0
    for side, parts in rep["contacts"].items():
        for r in parts.values():
            touch += r["source_touch_frames"]
            kept += r["kept_frames"]
            lost += len(r["lost_runs"])
    out = {"contact_frames": touch, "contacts_kept_share": round(kept / touch, 4) if touch else None, "contacts_lost_runs": lost}
    for tag in ("target", "source"):
        rows = rep["arms_in_body"][tag].values()
        out["arms_in_body_%s_frames_over_1cm" % tag] = int(sum(r["frames_over_1cm"] for r in rows))
        out["arms_in_body_%s_deepest_cm" % tag] = max([r["deepest_cm"] for r in rows] or [0.0])
    pl = rep["plants"]
    if "error" not in pl:
        out["plants"] = int(sum(r["plants"] for r in pl.values()))
        out["plants_sliding_over_1cm"] = int(sum(r["plants_sliding_over_1cm"] for r in pl.values()))
        fl = [r["float_over_1cm_pct"] for r in pl.values() if r["float_over_1cm_pct"] is not None]
        out["plant_float_over_1cm_pct"] = round(float(np.mean(fl)), 3) if fl else None
        tf = [r["toe_float_over_1cm_pct"] for r in pl.values() if r["toe_float_over_1cm_pct"] is not None]
        out["toe_float_over_1cm_pct"] = round(float(np.mean(tf)), 3) if tf else None
        out["plant_under_floor_frames"] = int(sum(r["under_floor_frames"] for r in pl.values()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source_dance")
    ap.add_argument("source_body")
    ap.add_argument("target_dance")
    ap.add_argument("target_model")
    ap.add_argument("--report", required=True)
    ap.add_argument("--arrays")
    ap.add_argument("--last", type=int)
    args = ap.parse_args(argv)
    try:
        t0 = time.time()
        rep = measure(vmd.load(args.source_dance), RT.Body.load(args.source_body), vmd.load(args.target_dance),
                      RT.Body.load(args.target_model), args.last)
        arrays = rep.pop("_arrays")
        rep.update(source_dance=os.path.abspath(args.source_dance), source_body=os.path.abspath(args.source_body),
                   target_dance=os.path.abspath(args.target_dance), target_model=os.path.abspath(args.target_model),
                   seconds=round(time.time() - t0, 1))
        RT.write_bytes(os.path.abspath(args.report), (json.dumps(rep, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        if args.arrays:
            import io
            buf = io.BytesIO()
            np.savez_compressed(buf, **arrays)
            RT.write_bytes(os.path.abspath(args.arrays), buf.getvalue())
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "report": os.path.abspath(args.report), "summary": rep["summary"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
