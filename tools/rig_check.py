"""Measure the rig of a PMX model against the motions it plays: what it receives from them (the bones and morphs it lacks
and how much motion they carry), how its leg IK solves a dance, and how its skin deforms on the hardest frames of the
dance (a twisted blend pinching the limb, triangles squeezed or turned over at the joints, one part pushed into
another), as numbers and pictures.  No MMD: the pose and the skinning are MMD's (tools/rig_skin.py), the legs MMD's IK
(tools/leg_ik.py).

    python tools/rig_check.py receivers MODEL.pmx --vmd TAG=PATH ... --out r.json
    python tools/rig_check.py ik MODEL.pmx DANCE.vmd --out r.json [--alt TAG:loops=N[,angle=RAD]] ...
    python tools/rig_check.py angles MODEL.pmx DANCE.vmd --out angles.npz
    python tools/rig_check.py skin DANCE.vmd --model TAG=MODEL.pmx ... --out DIR [--angles angles.npz] [--pick N]
                                   [--frames F ...] [--figures N]

receivers: per VMD, every bone and morph it keys, with the key count, whether the model has it (a VMD names a bone with
  at most 15 bytes of cp932: a longer model name is matched by its first 15), and how much it moves (the largest turn
  of a key from rest, degrees; the largest slide; a morph's largest weight).  `dropped_motion` / `dropped_morphs` are
  what MMD throws away without a word: names the model lacks whose keys move.  `semi_standard`: which of the usual
  semi-standard bones (準標準ボーン) the model has.
ik: the leg IK over a dance as MMD solves it: per side the frames whose ankle stays off its goal by more than 1 mm,
  4 mm and 1 cm (Sour's Rin: 8 cm a unit), split into goals within the leg's length (the IK could reach them) and
  beyond it; the knee's bend where a reachable goal is missed; the knee's jumps (a frame whose knee angle differs from
  the line through its neighbours by more than KNEE_JUMP_DEG); the toe IK's misses.  --alt runs the same with other
  settings (more loops, another unit angle) to see what a change of the model would do.
angles: the yardsticks of the hard frames over the whole dance (forward kinematics, the legs by MMD's IK): per side the
  upper arm's twist (腕捩 against 腕W, or 腕 when there is no 腕W), the hand's twist against the elbow, the wrist's
  against 手捩, the elbow's bend, the arm's lift (the angle between the upper arm and the chest's down), the wrist's
  bend, the knee's bend, the hip's bend (the thigh against the pelvis's down) and spread.
skin: on frames picked from the angles (the --pick highest of each yardstick, GAP frames apart) or given, for each
  model: (1) limb sections: the limb's vertices binned along it at rest, each one's distance from the line through the
  joints at either end against its rest distance: the lowest bin median is the pinch of the limb (a linear blend between
  two bones twisted by theta keeps cos(theta / 2) of the radius where it is half and half); (2) joints: the triangles
  around each joint, their area against rest (the lowest, the 1st percentile, how many under half and under a quarter)
  and how many turned over (the face faces away from its vertices' normals that faced along it at rest); (3)
  penetration: vertices of one part that lie inside another part's surface by more than DEPTH and did not at rest (the
  arm in the dress of the trunk, one thigh in the other, the forearm in the upper arm, the calf in the thigh), with the
  deepest.  Parts that physics moves (Model.physics) are not measured: here they would hang as at rest.
  Pictures (--figures N): the N worst frames of each yardstick, each model's skin from the front (or the side) with the
  triangles coloured by their area against rest and the vertices pushed in marked.
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_rig_check_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SKIN = _tool("rig_skin")
IK = _tool("leg_ik")

UNIT_CM = 8.0                   # Sour's Rin: one unit is 8 cm
SIDES = ("右", "左")
TAGS = {"右": "R", "左": "L"}
MOVE_DEG = 0.01                 # a key turned less than this from rest does not move
MOVE_UNITS = 1e-4               # nor one slid less than this
MORPH_W = 1e-4                  # a morph key below this weight does nothing
KNEE_JUMP_DEG = 10.0
DEPTH = 0.02                    # units (1.6 mm): a vertex this far inside another part is pushed into it
GAP = 15                        # frames between two picked frames of one yardstick
SEMI_STANDARD = ["全ての親", "操作中心", "センター", "グルーブ", "腰", "上半身", "上半身2", "首", "頭", "両目", "下半身"] + [
    s + n for s in ("左", "右") for n in ("肩P", "肩", "肩C", "腕", "腕捩", "腕捩1", "腕捩2", "腕捩3", "ひじ", "手捩", "手捩1", "手捩2",
                                        "手捩3", "手首", "ダミー", "親指０", "足", "ひざ", "足首", "足D", "ひざD", "足首D", "足先EX",
                                        "足IK親", "足ＩＫ", "つま先ＩＫ")] + ["腰キャンセル左", "腰キャンセル右"]


# ---- generic measures --------------------------------------------------------------------------------------------------

def _line_distance(p, a, b):
    """distance of points p [N, 3] from the line through a and b, and their place t along it (a 0, b 1)"""
    d = b - a
    L2 = float(np.dot(d, d))
    t = (p - a) @ d / L2
    foot = a + t[:, None] * d
    return np.linalg.norm(p - foot, axis=1), t


def section_profile(rest, now, a0, b0, a1, b1, bins=20, lo=0.0, hi=1.0, min_radius=0.02):
    """the pinch of a limb: the vertices (rest [N, 3], now [N, 3]) binned by their place along the rest axis a0 -> b0
    (bins over lo..hi), each one's distance from the axis now (a1 -> b1) against its rest distance.  Returns the bins'
    centres, medians (None for an empty bin) and counts, the lowest median and its place t_at_min, and the 5th
    percentile of all the vertices' ratios.  Vertices closer to the rest axis than min_radius are left out (their ratio
    says nothing)."""
    r0, t = _line_distance(np.asarray(rest, float), np.asarray(a0, float), np.asarray(b0, float))
    r1, _ = _line_distance(np.asarray(now, float), np.asarray(a1, float), np.asarray(b1, float))
    keep = (r0 > min_radius) & (t >= lo) & (t <= hi)
    ratio = np.where(keep, r1 / np.maximum(r0, 1e-12), np.nan)
    edges = np.linspace(lo, hi, bins + 1)
    which = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, bins - 1)
    centres, medians, counts = [], [], []
    for k in range(bins):
        sel = keep & (which == k)
        centres.append(round(float(0.5 * (edges[k] + edges[k + 1])), 6))
        counts.append(int(sel.sum()))
        medians.append(float(np.median(ratio[sel])) if sel.any() else None)
    vals = [(m, c) for m, c in zip(medians, centres) if m is not None]
    low = min(vals) if vals else (None, None)
    return {"t": centres, "median": medians, "count": counts, "min": low[0], "t_at_min": low[1],
            "p5": float(np.nanpercentile(ratio, 5)) if keep.any() else None, "vertices": int(keep.sum())}


def _tri_normals(p, faces):
    a, b, c = p[faces[:, 0]], p[faces[:, 1]], p[faces[:, 2]]
    return np.cross(b - a, c - a)


def area_ratios(rest, now, faces):
    """each triangle's area now against at rest (nan for a triangle of no area at rest)"""
    r = np.linalg.norm(_tri_normals(np.asarray(rest, float), faces), axis=1)
    n = np.linalg.norm(_tri_normals(np.asarray(now, float), faces), axis=1)
    return np.where(r > 1e-12, n / np.where(r > 1e-12, r, 1.0), np.nan)


def flipped(rest, now, faces, rest_normals, now_normals):
    """triangles whose face faced along its vertices' normals at rest and faces away from them now"""
    fr = _tri_normals(np.asarray(rest, float), faces)
    fn = _tri_normals(np.asarray(now, float), faces)
    vr = rest_normals[faces].sum(axis=1)
    vn = now_normals[faces].sum(axis=1)
    return (np.sum(fr * vr, axis=1) > 0) & (np.sum(fn * vn, axis=1) < 0)


def _closest_on_triangles(p, a, b, c):
    """the closest points on triangles (a, b, c) [N, 3] to p [N, 3] and their barycentric weights [N, 3]"""
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    nn = np.sum(n * n, axis=1)
    ok = nn > 1e-18
    ap = p - a
    d = np.where(ok, np.sum(ap * n, axis=1) / np.where(ok, nn, 1.0), 0.0)
    proj = p - d[:, None] * n
    # barycentric of the projection
    v0, v1, v2 = ab, ac, proj - a
    d00, d01, d11 = np.sum(v0 * v0, 1), np.sum(v0 * v1, 1), np.sum(v1 * v1, 1)
    d20, d21 = np.sum(v2 * v0, 1), np.sum(v2 * v1, 1)
    den = d00 * d11 - d01 * d01
    good = ok & (np.abs(den) > 1e-18)
    den = np.where(good, den, 1.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    inside = good & (u >= 0) & (v >= 0) & (w >= 0)
    best = np.where(inside[:, None], proj, np.nan)
    bary = np.where(inside[:, None], np.stack([u, v, w], 1), np.nan)
    bestd = np.where(inside, np.linalg.norm(p - proj, axis=1), np.inf)
    for x, y, ix, iy in ((a, b, 0, 1), (b, c, 1, 2), (c, a, 2, 0)):
        e = y - x
        ee = np.sum(e * e, axis=1)
        t = np.clip(np.sum((p - x) * e, axis=1) / np.where(ee > 0, ee, 1.0), 0.0, 1.0)
        q = x + t[:, None] * e
        dq = np.linalg.norm(p - q, axis=1)
        better = dq < bestd
        bestd = np.where(better, dq, bestd)
        best = np.where(better[:, None], q, best)
        wts = np.zeros((len(p), 3))
        wts[:, ix] = 1.0 - t
        wts[:, iy] = t
        bary = np.where(better[:, None], wts, bary)
    return best, bary


def signed_distance(q, surf, normals, faces, k=8, chunk=2048):
    """the distance of points q [Q, 3] from a surface (vertices surf [S, 3] with normals [S, 3], triangles faces [T, 3]),
    negative inside (the side the normals point away from: the normal at the closest point is the triangle's vertex
    normals blended by the closest point's barycentric weights).  The closest triangle is looked for among the
    triangles around the k surface vertices nearest each point."""
    q = np.asarray(q, float)
    surf = np.asarray(surf, float)
    faces = np.asarray(faces)
    if len(q) == 0 or len(faces) == 0:
        return np.full(len(q), np.inf)
    around = [[] for _ in range(len(surf))]
    for t, f in enumerate(faces):
        for v in f:
            around[v].append(t)
    width = max(len(x) for x in around)
    adj = np.full((len(surf), width), -1, dtype=np.int64)
    for v, ts in enumerate(around):
        adj[v, :len(ts)] = ts
    used = np.unique(faces)
    out = np.empty(len(q))
    k = min(k, len(used))
    for s in range(0, len(q), chunk):
        qq = q[s:s + chunk]
        d2 = np.sum((qq[:, None, :] - surf[None, used, :]) ** 2, axis=2)
        near = used[np.argpartition(d2, k - 1, axis=1)[:, :k]]                    # [n, k] surface vertices
        cand = adj[near].reshape(len(qq), -1)                                      # [n, k * width] triangles
        n, m = cand.shape
        valid = cand >= 0
        tri = faces[np.where(valid, cand, 0)]                                      # [n, m, 3]
        P = np.repeat(qq, m, axis=0)
        A, B, C = surf[tri[..., 0]].reshape(-1, 3), surf[tri[..., 1]].reshape(-1, 3), surf[tri[..., 2]].reshape(-1, 3)
        pt, bary = _closest_on_triangles(P, A, B, C)
        dist = np.linalg.norm(P - pt, axis=1).reshape(n, m)
        dist = np.where(valid, dist, np.inf)
        j = np.argmin(dist, axis=1)
        rows = np.arange(n)
        sel = rows * m + j
        nrm = (bary[sel, 0:1] * normals[tri[rows, j, 0]] + bary[sel, 1:2] * normals[tri[rows, j, 1]]
               + bary[sel, 2:3] * normals[tri[rows, j, 2]])
        side = np.sum((qq - pt[sel]) * nrm, axis=1)
        out[s:s + chunk] = np.where(side < 0, -dist[rows, j], dist[rows, j])
    return out


def penetration(rest_pts, now_pts, surf_rest, norm_rest, faces, surf_now, norm_now, depth=DEPTH):
    """vertices (rest_pts, now_pts) that lie inside a surface by more than `depth` now and outside it at rest: their
    count, the deepest, and their indices"""
    d0 = signed_distance(rest_pts, surf_rest, norm_rest, faces)
    d1 = signed_distance(now_pts, surf_now, norm_now, faces)
    hit = (d1 < -depth) & (d0 >= 0.0)
    return {"inside": int(hit.sum()), "max_depth": float(-d1[hit].min()) if hit.any() else 0.0,
            "indices": np.flatnonzero(hit).tolist(), "inside_at_rest": int((d0 < 0).sum())}


def pick_frames(series, per=5, gap=GAP):
    """name -> [(frame, value)]: the `per` highest frames of each series, at least `gap` frames apart"""
    out = {}
    for name, x in series.items():
        x = np.asarray(x, float)
        order = np.argsort(-np.where(np.isfinite(x), x, -np.inf), kind="stable")
        got = []
        for f in order:
            if not np.isfinite(x[f]):
                break
            if all(abs(int(f) - g) >= gap for g, _ in got):
                got.append((int(f), float(x[f])))
                if len(got) == per:
                    break
        out[name] = got
    return out


# ---- receivers -----------------------------------------------------------------------------------------------------------

def _turn_deg(q):
    n = math.sqrt(sum(v * v for v in q))
    if n <= 0:
        return 0.0
    return math.degrees(2.0 * math.acos(min(1.0, abs(q[3]) / n)))


def _morph_names(doc):
    names = []
    for m in doc.morphs:
        r = pmx_edit._Reader(m.head, doc.encoding)
        names.append(r.text())
    return names


def receivers(doc, motions):
    """what the model (a pmx_edit Document) receives from `motions` ({tag: vmd.Motion}): see the module docstring"""
    bone_names = [b.name for b in doc.bones]
    bones_vmd = {fk.vmd_name(n) for n in bone_names} | set(bone_names)
    morphs = _morph_names(doc)
    morphs_vmd = {fk.vmd_name(n) for n in morphs} | set(morphs)
    ik_bones = [b.name for b in doc.bones if b.flags & 0x0020]
    out = {"model_bones": len(bone_names), "model_morphs": len(morphs), "vmds": {},
           "semi_standard": {n: n in bone_names for n in SEMI_STANDARD}}
    for tag, mo in motions.items():
        bones = {}
        for k in mo.bones:
            e = bones.setdefault(k.name, {"keys": 0, "max_turn_deg": 0.0, "max_slide": 0.0, "frames": [k.frame, k.frame]})
            e["keys"] += 1
            e["max_turn_deg"] = max(e["max_turn_deg"], _turn_deg(k.rotation))
            e["max_slide"] = max(e["max_slide"], math.sqrt(sum(v * v for v in k.position)))
            e["frames"] = [min(e["frames"][0], k.frame), max(e["frames"][1], k.frame)]
        for name, e in bones.items():
            e["in_model"] = name in bones_vmd
            e["moves"] = e["max_turn_deg"] > MOVE_DEG or e["max_slide"] > MOVE_UNITS
            e["max_turn_deg"] = round(e["max_turn_deg"], 4)
            e["max_slide"] = round(e["max_slide"], 6)
        mors = {}
        for k in mo.morphs:
            e = mors.setdefault(k.name, {"keys": 0, "max_weight": 0.0, "min_weight": 0.0, "frames": [k.frame, k.frame]})
            e["keys"] += 1
            e["max_weight"] = max(e["max_weight"], k.weight)
            e["min_weight"] = min(e["min_weight"], k.weight)
            e["frames"] = [min(e["frames"][0], k.frame), max(e["frames"][1], k.frame)]
        for name, e in mors.items():
            e["in_model"] = name in morphs_vmd
            e["max_weight"] = round(e["max_weight"], 6)
            e["min_weight"] = round(e["min_weight"], 6)
        off = {}
        for s in mo.show_iks:
            for name, enabled in s.iks:
                if name in ik_bones and not enabled:
                    off.setdefault(name, []).append(s.frame)
        out["vmds"][tag] = {
            "bone_keys": len(mo.bones), "morph_keys": len(mo.morphs), "camera_keys": len(mo.cameras),
            "bones": bones, "morphs": mors,
            "missing_bones": sorted(n for n, e in bones.items() if not e["in_model"]),
            "dropped_motion": {n: {"keys": e["keys"], "max_turn_deg": e["max_turn_deg"], "max_slide": e["max_slide"],
                                   "frames": e["frames"]}
                               for n, e in bones.items() if not e["in_model"] and e["moves"]},
            "missing_morphs": sorted(n for n, e in mors.items() if not e["in_model"]),
            "dropped_morphs": {n: {"keys": e["keys"], "max_weight": e["max_weight"], "frames": e["frames"]}
                               for n, e in mors.items()
                               if not e["in_model"] and max(abs(e["max_weight"]), abs(e["min_weight"])) > MORPH_W},
            "ik_switched_off": off}
    return out


# ---- the leg IK ---------------------------------------------------------------------------------------------------------

def _with_settings(rig, loops=None, angle=None):
    import copy
    r = copy.copy(rig)
    r.sides = {}
    for s, side in rig.sides.items():
        n = copy.copy(side)
        if loops is not None:
            n.leg_loops = int(loops)
        if angle is not None:
            n.leg_limit = float(angle)
        r.sides[s] = n
    return r


def _ik_numbers(rig, sol):
    out = {}
    for s in rig.sides:
        d = sol[s]
        hip, knee, ankle, goal = d["hip"], d["knee"], d["ankle"], d["goal_ankle"]
        L = np.linalg.norm(knee - hip, axis=1) + np.linalg.norm(ankle - knee, axis=1)
        D = np.linalg.norm(goal - hip, axis=1)
        reachable = D <= L * (1.0 - 1e-6)
        miss = d["reach"] * UNIT_CM
        bend = np.degrees(-d["knee_angle"])
        r_miss = reachable & (miss > 0.4)
        jumps = np.zeros(len(bend), dtype=bool)
        if len(bend) >= 3:
            jumps[1:-1] = np.abs(bend[1:-1] - 0.5 * (bend[:-2] + bend[2:])) > KNEE_JUMP_DEG
        toe = d["toe_reach"] * UNIT_CM
        out[s] = {"frames": int(len(miss)), "miss_gt_1mm": int((miss > 0.1).sum()), "miss_gt_4mm": int((miss > 0.4).sum()),
                  "miss_gt_1cm": int((miss > 1.0).sum()), "unreachable": int((~reachable).sum()),
                  "reachable_miss_gt_1mm": int((reachable & (miss > 0.1)).sum()), "reachable_miss_gt_4mm": int(r_miss.sum()),
                  "reachable_miss_cm_max": round(float(miss[reachable].max()), 4) if reachable.any() else None,
                  "reachable_miss_cm_p99": round(float(np.percentile(miss[reachable], 99)), 4) if reachable.any() else None,
                  "knee_bend_at_reachable_miss_deg": ([round(float(np.percentile(bend[r_miss], q)), 2) for q in (0, 50, 100)]
                                                      if r_miss.any() else None),
                  "knee_jumps": int(jumps.sum()), "knee_jump_frames": np.flatnonzero(jumps).tolist()[:50],
                  "toe_miss_gt_1mm": int((toe > 0.1).sum()), "toe_miss_cm_max": round(float(toe.max()), 4),
                  "reachable_miss_frames": np.flatnonzero(r_miss).tolist()[:200]}
    return out


def ik_report(rig, motion, frames, alternatives=None):
    """the leg IK's misses over `frames` with the model's settings ("model") and with each alternative ({tag: {"loops":
    N, "angle": rad}})"""
    frames = list(frames)
    keys = IK.sample(rig, motion, frames)
    out = {"settings": {s: {"leg_loops": side.leg_loops, "leg_unit_angle_deg": round(math.degrees(side.leg_limit), 4),
                            "toe_loops": side.toe_loops, "toe_unit_angle_deg": round(math.degrees(side.toe_limit), 4),
                            "knee_deg": [round(math.degrees(side.knee_lo), 3), round(math.degrees(side.knee_hi), 3)]}
                        for s, side in rig.sides.items()}}
    sols = {"model": IK.solve(rig, motion, frames, keys=keys)}
    out["model"] = _ik_numbers(rig, sols["model"])
    for tag, kw in (alternatives or {}).items():
        r = _with_settings(rig, kw.get("loops"), kw.get("angle"))
        sols[tag] = IK.solve(r, motion, frames, keys=keys)
        out[tag] = _ik_numbers(r, sols[tag])
        for s in rig.sides:
            a, b = sols["model"][s], sols[tag][s]
            dk = np.degrees(np.abs(a["knee_angle"] - b["knee_angle"]))
            da = np.linalg.norm(a["ankle"] - b["ankle"], axis=1) * UNIT_CM
            out[tag][s]["vs_model"] = {"knee_changed_gt_1deg": int((dk > 1.0).sum()), "knee_change_deg_max": round(float(dk.max()), 3),
                                       "ankle_moved_gt_1mm": int((da > 0.1).sum()), "ankle_moved_cm_max": round(float(da.max()), 4)}
    return out


# ---- the angles of a dance ------------------------------------------------------------------------------------------------

def _q(a):
    return np.asarray(a, dtype=np.float64)


def twist_deg(q, axis):
    """the signed twist (degrees) of rotations q [N, 4] about unit axes [N, 3] (swing-twist)"""
    axis = axis / np.linalg.norm(axis, axis=-1, keepdims=True)
    p = np.sum(q[..., :3] * axis, axis=-1)
    ang = 2.0 * np.degrees(np.arctan2(p, q[..., 3]))
    return (ang + 180.0) % 360.0 - 180.0


def _angle(u, v):
    c = np.sum(u * v, -1) / np.maximum(np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1), 1e-12)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def _minrot(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    q = np.concatenate([np.cross(a, b), (1.0 + np.sum(a * b, -1))[..., None]], -1)
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def dance_angles(model_path, motion, first=0, last=None):
    """name -> per-frame array over first..last (degrees): see the module docstring ("angles")"""
    model = pmx.load(model_path)
    names_of = {b.name for b in model.bones}
    B = {b.name: b for b in model.bones}
    if last is None:
        last = fk.last_frame(motion)
    want = ["上半身", "下半身"] + (["胸椎上部"] if "胸椎上部" in names_of else ["上半身2"])
    for s in SIDES:
        want += [s + n for n in ("肩", "腕", "腕捩", "ひじ", "手捩", "手首", "中指１")]
    want = [n for n in want if n in names_of]
    tr = fk.world_track(model, motion, want, first, last)

    def P(n):
        return np.array([x[0] for x in tr[n]])

    def R(n):
        return np.array([x[1] for x in tr[n]])
    F = last - first + 1
    out = {}
    chest = "胸椎上部" if "胸椎上部" in names_of else "上半身2"
    down_chest = IK.qrot(R(chest), np.tile([0.0, -1.0, 0.0], (F, 1)))
    for s in SIDES:
        t = TAGS[s]
        arm, el, wr = P(s + "腕"), P(s + "ひじ"), P(s + "手首")
        ua, fa = el - arm, wr - el
        rest_ua = np.array(B[s + "ひじ"].position) - np.array(B[s + "腕"].position)
        rest_fa = np.array(B[s + "手首"].position) - np.array(B[s + "ひじ"].position)
        sh = R(s + "肩")
        cur = IK.qrot(IK.qconj(sh), ua)
        arm_w = IK.qmul(sh, _minrot(np.tile(rest_ua, (F, 1)), cur))           # 腕W as its IK makes it
        ref = arm_w
        tw = R(s + "腕捩") if (s + "腕捩") in names_of else R(s + "腕")
        out["upper_arm_twist_" + t] = np.abs(twist_deg(IK.qmul(IK.qconj(ref), tw), np.tile(rest_ua, (F, 1))))
        fu = np.tile(rest_fa, (F, 1))
        out["hand_twist_" + t] = np.abs(twist_deg(IK.qmul(IK.qconj(R(s + "ひじ")), R(s + "手首")), fu))
        if (s + "手捩") in names_of:
            out["wrist_twist_" + t] = np.abs(twist_deg(IK.qmul(IK.qconj(R(s + "手捩")), R(s + "手首")), fu))
        out["elbow_bend_" + t] = _angle(ua, fa)
        out["arm_lift_" + t] = _angle(ua, down_chest)
        if (s + "中指１") in names_of:
            out["wrist_bend_" + t] = _angle(fa, P(s + "中指１") - wr)
    rig = IK.LegRig.load(model_path)
    frames = list(range(first, last + 1))
    sol = IK.solve(rig, motion, frames)
    down_pelvis = IK.qrot(R("下半身"), np.tile([0.0, -1.0, 0.0], (F, 1)))
    side_pelvis = IK.qrot(R("下半身"), np.tile([1.0, 0.0, 0.0], (F, 1)))
    for s in SIDES:
        t = TAGS[s]
        d = sol[s]
        th = d["knee"] - d["hip"]
        out["knee_bend_" + t] = _angle(th, d["ankle"] - d["knee"])
        out["hip_bend_" + t] = _angle(th, down_pelvis)
        sign = 1.0 if s == "左" else -1.0
        lateral = np.sum(th * side_pelvis, -1) * sign
        out["hip_spread_" + t] = np.degrees(np.arcsin(np.clip(lateral / np.linalg.norm(th, axis=-1), -1.0, 1.0)))
    out["frames"] = np.array(frames)
    return out


# ---- the parts of Sour's Rin (and models built like her) -----------------------------------------------------------------

TRUNK = ("上半身", "腰椎上部", "上半身2", "胸椎上部")
LIMBS = {      # name: (from bone, to bone, bones the limb's skin hangs on, t range)
    "upper_arm": ("腕", "ひじ", ("腕W", "腕", "腕捩", "腕捩1", "腕捩2", "腕捩3"), (0.08, 0.92)),
    "forearm": ("ひじ", "手首", ("ひじ", "ひじ補助", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3", "手首"), (0.08, 1.06)),
    "thigh": ("足", "ひざ", ("足D", "足"), (0.15, 0.9)),
    "shin": ("ひざ", "足首", ("ひざD", "ひざ"), (0.1, 0.9)),
}
JOINTS = {     # name: (centre bone, radius units, bones on either side)
    "shoulder": ("腕", 0.75, ("肩", "腕W", "腕", "腕捩", "腕捩1", "腕捩2", "腕捩3")),
    "elbow": ("ひじ", 0.6, ("腕捩", "腕捩1", "腕捩2", "腕捩3", "腕W", "ひじ", "ひじ補助", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3")),
    "wrist": ("手首", 0.45, ("手捩", "手捩1", "手捩2", "手捩3", "手首")),
    "hip": ("足", 1.1, ("足D", "足")),
    "knee": ("ひざ", 0.8, ("足D", "ひざD", "足", "ひざ")),
    "ankle": ("足首", 0.6, ("ひざD", "足首D", "足先EX", "ひざ", "足首")),
}
LIMB_MATERIALS = ("skin",)
JOINT_MATERIALS = ("skin", "White", "Yellow", "Yellow3", "Blue")
DRESS = ("White", "White2", "Yellow")


class Parts:
    """vertex and triangle sets of a model's parts by the bones they hang on (names missing from the model are skipped)"""

    def __init__(self, m):
        self.m = m
        V = len(m.points)
        self.mat_of_vertex = np.full(V, "", dtype=object)
        self.mat_of_face = np.empty(len(m.faces), dtype=object)
        for name, f0, nf in m.materials:
            self.mat_of_face[f0:f0 + nf] = name
            self.mat_of_vertex[np.unique(m.faces[f0:f0 + nf])] = name
        self.phys_share = self.share([i for i in m.physics])

    def ids(self, names):
        return [self.m.by_name[n] for n in names if n in self.m.by_name]

    def share(self, bone_ids):
        """each vertex's weight on the bones bone_ids"""
        if not bone_ids:
            return np.zeros(len(self.m.points))
        mask = np.isin(self.m.idx, np.array(sorted(set(bone_ids))))
        return np.sum(np.where(mask, self.m.w, 0.0), axis=1)

    def vertices(self, side_bones, at_least=0.9, materials=None, physics_max=0.05):
        s = self.share(self.ids(side_bones))
        sel = (s >= at_least) & (self.phys_share <= physics_max)
        if materials is not None:
            sel &= np.isin(self.mat_of_vertex, list(materials))
        return np.flatnonzero(sel)

    def faces_of(self, vertex_ids, materials=None):
        inside = np.zeros(len(self.m.points), dtype=bool)
        inside[vertex_ids] = True
        sel = inside[self.m.faces].all(axis=1)
        if materials is not None:
            sel &= np.isin(self.mat_of_face, list(materials))
        return np.flatnonzero(sel)


def _sided(names, s):
    return [s + n for n in names]


def measure_frame(m, parts, pose, pts, nrm, rest_nrm):
    """the limb sections, joints and penetrations of one posed and skinned model (see the module docstring)"""
    rec = {"sections": {}, "joints": {}, "penetration": {}}
    P0 = m.points
    for s in SIDES:
        t = TAGS[s]
        for limb, (a, b, bones, (lo, hi)) in LIMBS.items():
            if (s + a) not in m.by_name or (s + b) not in m.by_name:
                continue
            vs = parts.vertices(_sided(bones, s), materials=LIMB_MATERIALS)
            ia, ib = m.by_name[s + a], m.by_name[s + b]
            prof = section_profile(P0[vs], pts[vs], m.rest[ia], m.rest[ib], pose.pos[ia], pose.pos[ib], bins=16, lo=lo, hi=hi)
            rec["sections"][limb + "_" + t] = {k: prof[k] for k in ("min", "t_at_min", "p5", "vertices")}
            rec["sections"][limb + "_" + t]["median"] = [None if x is None else round(x, 4) for x in prof["median"]]
        for joint, (centre, radius, bones) in JOINTS.items():
            if (s + centre) not in m.by_name:
                continue
            c = m.rest[m.by_name[s + centre]]
            near = np.flatnonzero(np.linalg.norm(P0 - c, axis=1) <= radius)
            on = parts.vertices(_sided(bones, s), at_least=0.5, materials=JOINT_MATERIALS)
            vs = np.intersect1d(near, on)
            fs = parts.faces_of(vs, JOINT_MATERIALS)
            if len(fs) == 0:
                continue
            f = m.faces[fs]
            ar = area_ratios(P0, pts, f)
            fl = flipped(P0, pts, f, rest_nrm, nrm)
            ok = np.isfinite(ar)
            rec["joints"][joint + "_" + t] = {"triangles": int(len(fs)), "area_min": round(float(np.nanmin(ar)), 4),
                                              "area_p1": round(float(np.nanpercentile(ar[ok], 1)), 4),
                                              "under_half": int((ar[ok] < 0.5).sum()), "under_quarter": int((ar[ok] < 0.25).sum()),
                                              "flipped": int(fl.sum())}
    # penetrations
    trunk_v = parts.vertices(TRUNK, materials=DRESS)
    trunk_f = m.faces[parts.faces_of(trunk_v, DRESS)]
    for s in SIDES:
        t = TAGS[s]
        fore = parts.vertices(_sided(("ひじ", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3", "手首"), s) + [
            s + n for n in ("親指０", "親指１", "親指２", "人指０", "人指１", "人指２", "人指３", "中指０", "中指１", "中指２", "中指３",
                            "薬指０", "薬指１", "薬指２", "薬指３", "小指０", "小指１", "小指２", "小指３")], materials=("skin", "nail", "White"))
        upper = parts.vertices(_sided(("腕W", "腕捩", "腕捩1", "腕捩2", "腕捩3"), s), materials=("skin",))
        if len(trunk_f) and len(fore):
            rec["penetration"]["forearm_hand_in_dress_" + t] = _pen(m, fore, trunk_f, pts, nrm, rest_nrm)
        if len(upper):
            uf = m.faces[parts.faces_of(upper, ("skin",))]
            if len(uf) and len(fore):
                rec["penetration"]["forearm_in_upper_arm_" + t] = _pen(m, parts.vertices(_sided(("手捩", "手捩1", "手捩2", "手捩3"), s), materials=("skin",)), uf, pts, nrm, rest_nrm)
        thigh = parts.vertices(_sided(("足D",), s), materials=("skin",))
        other = parts.vertices(_sided(("足D",), "左" if s == "右" else "右"), materials=("skin",))
        of = m.faces[parts.faces_of(other, ("skin",))]
        if len(thigh) and len(of):
            rec["penetration"]["thigh_in_other_thigh_" + t] = _pen(m, thigh, of, pts, nrm, rest_nrm)
        shin = parts.vertices(_sided(("ひざD",), s), materials=("skin", "White"))
        tf = m.faces[parts.faces_of(thigh, ("skin",))]
        if len(shin) and len(tf):
            rec["penetration"]["calf_in_thigh_" + t] = _pen(m, shin, tf, pts, nrm, rest_nrm)
    return rec


def _pen(m, vs, faces, pts, nrm, rest_nrm):
    rep = penetration(m.points[vs], pts[vs], m.points, rest_nrm, faces, pts, nrm)
    rep["indices"] = [int(vs[i]) for i in rep["indices"]][:400]
    rep["max_depth_cm"] = round(rep["max_depth"] * UNIT_CM, 3)
    return rep


# ---- the skin report ---------------------------------------------------------------------------------------------------

YARDSTICKS = {      # angle name -> the measures it is picked for
    "upper_arm_twist": ("sections", "upper_arm"), "hand_twist": ("sections", "forearm"), "wrist_twist": ("sections", "forearm"),
    "elbow_bend": ("joints", "elbow"), "arm_lift": ("joints", "shoulder"), "wrist_bend": ("joints", "wrist"),
    "knee_bend": ("joints", "knee"), "hip_bend": ("joints", "hip"), "hip_spread": ("joints", "hip"),
}


def skin_report(models, motion, frames):
    """{tag: Model}, a vmd.Motion and frames -> {tag: {frame: measure_frame(...)}}"""
    tracks = fk.tracks_of(motion)
    out = {}
    for tag, m in models.items():
        parts = Parts(m)
        rest_nrm = m.normals / np.maximum(np.linalg.norm(m.normals, axis=1, keepdims=True), 1e-12)
        per = {}
        for f in frames:
            pose = SKIN.solve(m, SKIN.keys_at(m, tracks, f))
            pts = SKIN.skin(m, pose)
            nrm = SKIN.normals(m, pose)
            per[int(f)] = measure_frame(m, parts, pose, pts, nrm, rest_nrm)
            per[int(f)]["ik"] = {m.bones[i].name: round(v["reach"], 6) for i, v in pose.ik.items()}
        out[tag] = per
    return out


def summary(report, picked):
    """per yardstick, side and model: the worst of the picked frames (lowest section / area, most flipped, deepest)"""
    rows = []
    for name, got in picked.items():
        base, t = name.rsplit("_", 1)
        kind, part = YARDSTICKS.get(base, (None, None))
        if kind is None:
            continue
        key = part + "_" + t
        for tag, per in report.items():
            vals = [per[f][kind].get(key) for f, _ in got if f in per and per[f][kind].get(key)]
            if not vals:
                continue
            if kind == "sections":
                worst = min(vals, key=lambda v: v["min"] if v["min"] is not None else 9)
                rows.append({"yardstick": name, "model": tag, "measure": "section_min", "value": worst["min"]})
            else:
                rows.append({"yardstick": name, "model": tag, "measure": "area_min", "value": min(v["area_min"] for v in vals)})
                rows.append({"yardstick": name, "model": tag, "measure": "under_half", "value": max(v["under_half"] for v in vals)})
                rows.append({"yardstick": name, "model": tag, "measure": "flipped", "value": max(v["flipped"] for v in vals)})
    return rows


# ---- pictures ------------------------------------------------------------------------------------------------------------

def draw(models, motion, frame, out_path, view="front", focus=None, title=""):
    """each model's skin at `frame` side by side, triangles coloured by their area against rest (blue squeezed, white
    kept, red stretched), the penetrating vertices of measure_frame as black dots; focus: a bone name to frame"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    tracks = fk.tracks_of(motion)
    n = len(models)
    fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 6.4))
    axes = np.atleast_1d(axes)
    for ax, (tag, m) in zip(axes, models.items()):
        parts = Parts(m)
        pose = SKIN.solve(m, SKIN.keys_at(m, tracks, frame))
        pts = SKIN.skin(m, pose)
        nrm = SKIN.normals(m, pose)
        rest_nrm = m.normals / np.maximum(np.linalg.norm(m.normals, axis=1, keepdims=True), 1e-12)
        rec = measure_frame(m, parts, pose, pts, nrm, rest_nrm)
        keep = parts.phys_share[m.faces].max(axis=1) <= 0.05
        mats = np.isin(parts.mat_of_face, ["skin", "White", "White2", "Yellow", "Yellow3", "Blue", "nail", "pants"])
        f = m.faces[keep & mats]
        ar = area_ratios(m.points, pts, f)
        ax_h, depth_axis = (0, 2) if view == "front" else (2, 0)
        proj = pts[:, [ax_h, 1]].copy()
        if view == "front":
            proj[:, 0] *= -1.0                 # the viewer faces the model: her left (+x) on the right
        zc = pts[f].mean(axis=1)[:, depth_axis]
        order = np.argsort(-zc if view == "front" else zc)   # far first
        cmap = plt.get_cmap("coolwarm")
        col = cmap(np.clip((np.log2(np.where(np.isfinite(ar), ar, 1.0)) + 1.0) / 2.0, 0.0, 1.0))
        ax.add_collection(PolyCollection(proj[f[order]], facecolors=col[order], edgecolors=(0, 0, 0, 0.08), linewidths=0.2))
        hits = sorted({i for r in rec["penetration"].values() for i in r["indices"]})
        if hits:
            ax.scatter(proj[hits, 0], proj[hits, 1], s=3, c="k")
        if focus and focus in m.by_name:
            c = pose.pos[m.by_name[focus]]
            cx = -c[0] if view == "front" else c[ax_h]
            ax.set_xlim(cx - 2.5, cx + 2.5)
            ax.set_ylim(c[1] - 2.5, c[1] + 2.5)
        else:
            ax.set_xlim(proj[:, 0].min() - 0.5, proj[:, 0].max() + 0.5)
            ax.set_ylim(proj[:, 1].min() - 0.5, proj[:, 1].max() + 0.5)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        worst = sorted(((v["min"], k) for k, v in rec["sections"].items() if v["min"] is not None))[:2]
        txt = " ".join("%s %.2f" % (k, v) for v, k in worst)
        ax.set_title("%s  frame %d (%.2f s)\n%s" % (tag, frame, frame / 30.0, txt), fontsize=8)
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


# ---- command line --------------------------------------------------------------------------------------------------------

def _json(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _tagged(items, what):
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit("%s must be TAG=PATH, not %r" % (what, item))
        tag, path = item.split("=", 1)
        out[tag] = path
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("receivers")
    a.add_argument("model")
    a.add_argument("--vmd", action="append", default=[], help="TAG=PATH")
    a.add_argument("--out", required=True)
    b = sub.add_parser("ik")
    b.add_argument("model")
    b.add_argument("dance")
    b.add_argument("--out", required=True)
    b.add_argument("--alt", action="append", default=[], help="TAG:loops=N[,angle=RAD]")
    c = sub.add_parser("angles")
    c.add_argument("model")
    c.add_argument("dance")
    c.add_argument("--out", required=True)
    d = sub.add_parser("skin")
    d.add_argument("dance")
    d.add_argument("--model", action="append", default=[], help="TAG=PATH (the first is the reference)")
    d.add_argument("--out", required=True)
    d.add_argument("--angles")
    d.add_argument("--pick", type=int, default=4)
    d.add_argument("--frames", type=int, nargs="*", default=[])
    d.add_argument("--figures", type=int, default=0)
    args = ap.parse_args(argv)
    if args.cmd == "receivers":
        motions = {tag: vmd.load(p) for tag, p in _tagged(args.vmd, "--vmd").items()}
        rep = receivers(pmx_edit.load(args.model), motions)
        rep["model"] = os.path.abspath(args.model)
        _json(args.out, rep)
        print(json.dumps({t: {"missing_bones": len(v["missing_bones"]), "dropped_motion": v["dropped_motion"],
                              "dropped_morphs": v["dropped_morphs"]} for t, v in rep["vmds"].items()}, ensure_ascii=True))
        return 0
    if args.cmd == "ik":
        alts = {}
        for item in args.alt:
            tag, spec = item.split(":", 1)
            kw = {}
            for part in spec.split(","):
                k, v = part.split("=")
                kw[k] = float(v)
            alts[tag] = kw
        rig = IK.LegRig.load(args.model)
        mo = vmd.load(args.dance)
        rep = ik_report(rig, mo, range(fk.last_frame(mo) + 1), alts)
        rep["model_path"] = os.path.abspath(args.model)
        _json(args.out, rep)
        print(json.dumps({t: {s: {k: v[k] for k in ("reachable_miss_gt_4mm", "reachable_miss_cm_max", "unreachable", "knee_jumps")}
                              for s, v in rep[t].items()} for t in ["model"] + list(alts)}, ensure_ascii=True))
        return 0
    if args.cmd == "angles":
        ang = dance_angles(args.model, vmd.load(args.dance))
        np.savez_compressed(args.out, **ang)
        print(json.dumps({k: [round(float(np.percentile(v, q)), 1) for q in (50, 90, 99, 100)] for k, v in ang.items() if k != "frames"}))
        return 0
    if args.cmd == "skin":
        paths = _tagged(args.model, "--model")
        if not paths:
            raise SystemExit("give at least one --model TAG=PATH")
        models = {tag: SKIN.Model.load(p) for tag, p in paths.items()}
        mo = vmd.load(args.dance)
        picked = {}
        if args.angles:
            ang = dict(np.load(args.angles))
            frames0 = ang.pop("frames")
            picked = {k: [(int(frames0[f]), v) for f, v in got] for k, got in pick_frames(ang, per=args.pick).items()}
        frames = sorted({f for got in picked.values() for f, _ in got} | set(args.frames))
        rep = skin_report(models, mo, frames)
        os.makedirs(args.out, exist_ok=True)
        _json(os.path.join(args.out, "skin.json"), {"models": paths, "picked": picked, "frames": frames, "report": rep,
                                                     "summary": summary(rep, picked)})
        if args.figures:
            figdir = os.path.join(args.out, "fig")
            os.makedirs(figdir, exist_ok=True)
            focus = {"upper_arm_twist": "腕捩", "hand_twist": "手首", "wrist_twist": "手首", "elbow_bend": "ひじ", "arm_lift": "腕",
                     "wrist_bend": "手首", "knee_bend": "ひざ", "hip_bend": "足", "hip_spread": "足"}
            for name, got in picked.items():
                base, t = name.rsplit("_", 1)
                side = "右" if t == "R" else "左"
                for f, v in got[:args.figures]:
                    draw(models, mo, f, os.path.join(figdir, "%s_%05d.png" % (name, f)),
                         view="side" if base in ("hip_bend", "knee_bend", "elbow_bend") else "front",
                         focus=side + focus.get(base, "腕"), title="%s %.1f deg" % (name, v))
        print(json.dumps(summary(rep, picked), ensure_ascii=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
