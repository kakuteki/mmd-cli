"""Measure the rig of a PMX model against the motions it plays: what it receives from them (the bones and morphs it lacks
and how much motion they carry), how its leg IK solves a dance, and how its skin deforms on the hardest frames of the
dance (a twisted blend pinching the limb, triangles squeezed or turned over at the joints, one part pushed into
another), as numbers and pictures.  No MMD: the pose and the skinning are MMD's (tools/rig_skin.py), the legs MMD's IK
(tools/leg_ik.py).

    python tools/rig_check.py receivers MODEL.pmx --vmd TAG=PATH ... --out r.json
    python tools/rig_check.py ik MODEL.pmx DANCE.vmd --out r.json [--alt TAG:loops=N[,angle=RAD][,least_bend=DEG]] ...
    python tools/rig_check.py angles MODEL.pmx DANCE.vmd --out angles.npz
    python tools/rig_check.py skin DANCE.vmd --model TAG=MODEL.pmx ... --out DIR [--angles angles.npz] [--pick N]
                                   [--frames F ...] [--figures N]
    python tools/rig_check.py physics MODEL.pmx --out r.json [--gravity 94 118]
    python tools/rig_check.py diff A.pmx B.pmx --out r.json
    python tools/rig_check.py delta DANCE.vmd --model TAG=A.pmx --model TAG=B.pmx ... --out r.json [--frames F ...]
                                   [--angles angles.npz --pick N]

receivers: per VMD, every bone and morph it keys, with the key count, whether the model has it (a VMD names a bone with
  at most 15 bytes of cp932: a longer model name is matched by its first 15), and how much it moves (the largest turn
  of a key from rest, degrees; the largest slide; a morph's largest weight).  `dropped_motion` / `dropped_morphs` are
  what MMD throws away without a word: names the model lacks whose keys move.  `semi_standard`: which of the usual
  semi-standard bones (準標準ボーン) the model has.
ik: the leg IK over a dance as MMD solves it: per side the frames whose ankle stays off its goal by more than 1 mm,
  4 mm and 1 cm (Sour's Rin: 8 cm a unit), split into goals the IK could reach (within the hip-to-ankle distance of
  the knee at its limit's least bend, max_reach) and beyond; the knee's bend where a reachable goal is missed; the frames
  whose knee sits at its least bend; the knee's jumps (a frame whose knee angle differs from the line through its
  neighbours by more than KNEE_JUMP_DEG) and their events (jump frames at most a frame apart are one event: a one-frame
  pop of 25 degrees counts as three jump frames; per event its peak, the size, the bends around it, the goal's distance
  from the hip over the leg's reach and the goal's height above the ankle's rest height); the toe IK's misses.  --alt runs
  the same with other settings (more loops, another unit angle, a knee that keeps a least bend) to see what a change of
  the model would do.
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
physics: the rigid bodies and joints at rest, by family (the name without its numbers): shape, size, mass, damping
  (and the time a velocity takes to fall to 1/e under it: Bullet scales velocities by (1 - d) a second), what each
  collides with (the groups both masks let through), the pendulum frequency of each dynamic body about the joint that
  hangs it (sqrt(g / L) / 2 pi, L the joint to the body's centre) for each --gravity (MMD's window 9.8 is about 94
  units/s^2 as measured, the real g at Sour's Rin's 8 cm a unit is 122.5), the pairs that collide and already overlap at
  rest (they are pushed apart the moment physics starts), and per dynamic body the nearest body-following body (group 0
  or 1: the trunk, head, shoulders, arms, legs) and the gap to it, with whether the two collide.  A rigid body's
  rotation (x, y, z radians) turns its frame by Ry Rx Rz (yaw, pitch, roll as Direct3D builds it), a capsule lies along
  its own Y (size: radius, height between the end centres), a box has half extents.
diff: two PMX files part by part (pmx_diff): the header; per vertex its place, normal, UVs, edge, SDEF points and its
  weights merged per bone (the vertices whose weights changed listed with their material and both weightings, the sum
  of each bone's weights over all vertices before and after); faces, textures, materials field by field; bones, morphs
  and display frames matched by name (added, removed, each changed field, indices into other parts as the names they
  point to); rigid bodies and joints field by field; the soft bodies' bytes.  A copy made by tools/pmx_rig.py should
  differ only by what its recipe names.
delta: two or more models with the same vertices (the first the reference) posed and skinned on the same frames of a
  dance (skin_delta): per frame the vertices that land elsewhere than on the reference (more than 1e-4 units), the
  most per material (cm), and where they lie along the limbs (t along the limb's rest axis, 0 at its first joint, 1 at
  its second: a wrist band is near 1 of the forearm, the hand past it, the cuff on the forearm before it).
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import struct
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

def _with_settings(rig, loops=None, angle=None, least_bend=None):
    """a copy of the leg rig with other leg IK settings: loops, unit angle (radians), and the knee's least bend
    (degrees: the IK limit's upper end becomes -least_bend; 0 is the model's rest bend)"""
    import copy
    r = copy.copy(rig)
    r.sides = {}
    for s, side in rig.sides.items():
        n = copy.copy(side)
        if loops is not None:
            n.leg_loops = int(loops)
        if angle is not None:
            n.leg_limit = float(angle)
        if least_bend is not None:
            n.knee_hi = -math.radians(float(least_bend))
        r.sides[s] = n
    return r


def max_reach(rig, side):
    """the farthest the leg IK can put the ankle from the hip: the knee turned from rest by its limit's upper end (the
    least bend it allows) about its X axis"""
    sd = rig.sides[side]
    hip = np.array(rig.bones[sd.thigh].position, dtype=float)
    knee = np.array(rig.bones[sd.knee].position, dtype=float)
    ankle = np.array(rig.bones[sd.ankle].position, dtype=float)
    shin = IK.qrot(IK.qaxis(np.array([1.0, 0.0, 0.0]), sd.knee_hi), ankle - knee)
    return float(np.linalg.norm(knee - hip + shin))


def _ik_numbers(rig, sol):
    out = {}
    for s in rig.sides:
        d = sol[s]
        hip, goal = d["hip"], d["goal_ankle"]
        D = np.linalg.norm(goal - hip, axis=1)
        reachable = D <= max_reach(rig, s) - 1e-6
        miss = d["reach"] * UNIT_CM
        bend = np.degrees(-d["knee_angle"])
        at_limit = bend <= math.degrees(-rig.sides[s].knee_hi) + 0.5
        r_miss = reachable & (miss > 0.4)
        jumps = np.zeros(len(bend), dtype=bool)
        off = np.zeros(len(bend))
        if len(bend) >= 3:
            off[1:-1] = np.abs(bend[1:-1] - 0.5 * (bend[:-2] + bend[2:]))
            jumps[1:-1] = off[1:-1] > KNEE_JUMP_DEG
        events = []
        rest_ankle_y = float(rig.bones[rig.sides[s].ankle].position[1])
        for f in np.flatnonzero(jumps):
            if events and f - events[-1]["last"] <= 1:
                events[-1]["last"] = int(f)
                if off[f] > events[-1]["deg"]:
                    events[-1]["deg"], events[-1]["peak"] = float(off[f]), int(f)
            else:
                events.append({"first": int(f), "last": int(f), "peak": int(f), "deg": float(off[f])})
        for e in events:
            p = e["peak"]
            e["deg"] = round(e["deg"], 2)
            e["bends"] = [round(float(bend[p + k]), 2) for k in (-1, 0, 1)]
            e["reach_ratio"] = round(float(D[p] / max_reach(rig, s)), 4)
            e["ankle_up_cm"] = round((float(goal[p, 1]) - rest_ankle_y) * UNIT_CM, 3)
        toe = d["toe_reach"] * UNIT_CM
        out[s] = {"frames": int(len(miss)), "miss_gt_1mm": int((miss > 0.1).sum()), "miss_gt_4mm": int((miss > 0.4).sum()),
                  "miss_gt_1cm": int((miss > 1.0).sum()), "unreachable": int((~reachable).sum()),
                  "reachable_miss_gt_1mm": int((reachable & (miss > 0.1)).sum()), "reachable_miss_gt_4mm": int(r_miss.sum()),
                  "reachable_miss_cm_max": round(float(miss[reachable].max()), 4) if reachable.any() else None,
                  "reachable_miss_cm_p99": round(float(np.percentile(miss[reachable], 99)), 4) if reachable.any() else None,
                  "knee_bend_at_reachable_miss_deg": ([round(float(np.percentile(bend[r_miss], q)), 2) for q in (0, 50, 100)]
                                                      if r_miss.any() else None),
                  "knee_at_least_bend": int(at_limit.sum()),
                  "knee_jumps": int(jumps.sum()), "knee_jump_frames": np.flatnonzero(jumps).tolist()[:50],
                  "knee_jump_event_count": len(events), "knee_jump_events": events,
                  "toe_miss_gt_1mm": int((toe > 0.1).sum()), "toe_miss_cm_max": round(float(toe.max()), 4),
                  "reachable_miss_frames": np.flatnonzero(r_miss).tolist()[:200], "max_reach": round(max_reach(rig, s), 5)}
    return out


def ik_report(rig, motion, frames, alternatives=None):
    """the leg IK's misses over `frames` with the model's settings ("model") and with each alternative ({tag: {"loops":
    N, "angle": rad, "least_bend": deg}})"""
    frames = list(frames)
    keys = IK.sample(rig, motion, frames)
    out = {"settings": {s: {"leg_loops": side.leg_loops, "leg_unit_angle_deg": round(math.degrees(side.leg_limit), 4),
                            "toe_loops": side.toe_loops, "toe_unit_angle_deg": round(math.degrees(side.toe_limit), 4),
                            "knee_deg": [round(math.degrees(side.knee_lo), 3), round(math.degrees(side.knee_hi), 3)]}
                        for s, side in rig.sides.items()}}
    sols = {"model": IK.solve(rig, motion, frames, keys=keys)}
    out["model"] = _ik_numbers(rig, sols["model"])
    for tag, kw in (alternatives or {}).items():
        r = _with_settings(rig, kw.get("loops"), kw.get("angle"), kw.get("least_bend"))
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


# ---- physics at rest ------------------------------------------------------------------------------------------------------

def body_frame(body):
    """(centre [3], rotation [3, 3]) of a pmx_edit RigidBody: R = Ry Rx Rz of its rotation (radians)"""
    x, y, z = body.rotation
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return np.array(body.position, float), Ry @ Rx @ Rz


def _segment(body):
    """(a, b, radius) of a sphere or capsule (a == b for a sphere)"""
    c, R = body_frame(body)
    if body.shape == 0:
        return c, c, float(body.size[0])
    half = 0.5 * float(body.size[1]) * R[:, 1]
    return c - half, c + half, float(body.size[0])


def _seg_seg(p1, q1, p2, q2):
    """the closest distance between segments p1-q1 and p2-q2"""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = float(d1 @ d1), float(d2 @ d2), float(d2 @ r)
    if a <= 1e-12 and e <= 1e-12:
        return float(np.linalg.norm(r))
    if a <= 1e-12:
        s, t = 0.0, min(1.0, max(0.0, f / e))
    else:
        c = float(d1 @ r)
        if e <= 1e-12:
            t, s = 0.0, min(1.0, max(0.0, -c / a))
        else:
            b = float(d1 @ d2)
            den = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t, s = 1.0, min(1.0, max(0.0, (b - c) / a))
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * t)))


def _point_box(p, body):
    c, R = body_frame(body)
    local = R.T @ (np.asarray(p, float) - c)
    h = np.array(body.size, float)
    q = np.clip(local, -h, h)
    out = float(np.linalg.norm(local - q))
    if out > 0.0:
        return out
    return -float(np.min(h - np.abs(local)))           # inside: minus the depth to the nearest face


def gap(a, b, samples=21):
    """the distance between the surfaces of two rigid bodies at rest (negative: they overlap by that much).  Spheres and
    capsules exactly; a box against a sphere or capsule by points along the other's segment; two boxes by their corners."""
    if a.shape == 1 and b.shape == 1:
        c, R = body_frame(a)
        corners = [c + R @ (np.array(sg) * np.array(a.size)) for sg in
                   ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, 1), (-1, 1, -1), (-1, -1, 1), (-1, -1, -1))]
        return min(_point_box(p, b) for p in corners + [c])
    if a.shape == 1 or b.shape == 1:
        box, other = (a, b) if a.shape == 1 else (b, a)
        p, q, r = _segment(other)
        return min(_point_box(p + (q - p) * k / (samples - 1), box) for k in range(samples)) - r
    p1, q1, r1 = _segment(a)
    p2, q2, r2 = _segment(b)
    return _seg_seg(p1, q1, p2, q2) - r1 - r2


def collide(a, b):
    """whether two rigid bodies collide: each one's mask lets the other's group through"""
    return bool((a.mask >> b.group) & 1) and bool((b.mask >> a.group) & 1)


def _family(name):
    import re
    m = re.match(r"^(.*?)[_0-9０-９]+(?:[_0-9０-９]*)$", name)
    return m.group(1) if m and m.group(1) else name


def physics_report(doc, gravities=(94.0, 122.5)):
    """the rigid bodies and joints of `doc` at rest (see the module docstring)"""
    names = [pmx_edit.rigid_names(doc, rb)[0] for rb in doc.rigid_bodies]
    bodies = [pmx_edit.rigid_body(rb) for rb in doc.rigid_bodies]
    joints = pmx_edit.joints(doc)
    hang = {}
    for j in joints:
        if 0 <= j.b < len(bodies) and j.b not in hang and bodies[j.b].mode != 0:
            hang[j.b] = j
    fam = {}
    for i, (n, b) in enumerate(zip(names, bodies)):
        f = fam.setdefault(_family(n), {"bodies": 0, "modes": set(), "shapes": set(), "mass": [], "linear_damping": set(),
                                        "angular_damping": set(), "groups": set(), "collides_with": set(), "pendulum_hz": {}})
        f["bodies"] += 1
        f["modes"].add(pmx_edit.RIGID_MODES[b.mode])
        f["shapes"].add(pmx_edit.RIGID_SHAPES[b.shape])
        f["mass"].append(b.mass)
        f["linear_damping"].add(round(b.linear_damping, 6))
        f["angular_damping"].add(round(b.angular_damping, 6))
        f["groups"].add(b.group)
        f["collides_with"] |= {g for g in range(16) if (b.mask >> g) & 1}
        if i in hang:
            L = float(np.linalg.norm(np.array(b.position) - np.array(hang[i].position)))
            for g in gravities:
                f["pendulum_hz"].setdefault(str(g), []).append(math.sqrt(g / max(L, 1e-6)) / (2.0 * math.pi))
    families = {}
    for k, f in fam.items():
        families[k] = {"bodies": f["bodies"], "modes": sorted(f["modes"]), "shapes": sorted(f["shapes"]),
                       "mass": [round(min(f["mass"]), 4), round(max(f["mass"]), 4)],
                       "linear_damping": sorted(f["linear_damping"]), "angular_damping": sorted(f["angular_damping"]),
                       "decay_s": [round(-1.0 / math.log(max(1e-12, 1.0 - d)), 4) if d < 1.0 else 0.0 for d in sorted(f["linear_damping"])],
                       "groups": sorted(f["groups"]), "collides_with": sorted(f["collides_with"]),
                       "pendulum_hz": {g: [round(min(v), 3), round(max(v), 3)] for g, v in f["pendulum_hz"].items()}}
    overlaps = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[j]
            if a.mode == 0 and b.mode == 0:
                continue                # two bodies that follow their bones never push each other
            if not collide(a, b):
                continue
            g = gap(a, b)
            if g < 0.0:
                overlaps.append({"a": names[i], "b": names[j], "depth": round(-g, 4)})
    overlaps.sort(key=lambda o: -o["depth"])
    body_like = [i for i, b in enumerate(bodies) if b.mode == 0 and b.group in (0, 1)]
    near = {}
    for i, b in enumerate(bodies):
        if b.mode == 0:
            continue
        best = min(((gap(b, bodies[k]), k) for k in body_like), default=(None, None))
        if best[1] is None:
            continue
        near[names[i]] = {"nearest": names[best[1]], "gap": round(best[0], 4), "collides": collide(b, bodies[best[1]])}
    return {"bodies": len(bodies), "joints": len(joints), "gravities": list(gravities), "families": families,
            "overlaps_at_rest": overlaps, "dynamic_nearest_body": near}


# ---- two copies of a model compared ----------------------------------------------------------------------------------------

def _r6(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, (tuple, list)):
        return [_r6(v) for v in x]
    return x


def _keyed(names):
    """(name, how many before it had the name) for each name: a key that stays the same when items are appended"""
    seen, out = {}, []
    for n in names:
        out.append((n, seen.get(n, 0)))
        seen[n] = seen.get(n, 0) + 1
    return out


def _merged(v):
    """a vertex's weights merged per bone, the zero ones left out (BDEF4 pads with its first bone at weight 0)"""
    out = {}
    for b, w in v.pairs():
        if b >= 0 and w > 0.0:
            out[b] = out.get(b, 0.0) + w
    return out


def _bone_fields(doc, b):
    def name(i):
        return doc.bones[i].name if 0 <= i < len(doc.bones) else None
    links = [[name(l), None if raw is None else _r6(list(struct.unpack("<6f", raw)))] for l, raw in b.ik_links]
    out = {"name_en": b.name_en, "position": _r6(list(b.position)), "parent": name(b.parent), "layer": b.layer,
           "flags": "0x%04x" % b.flags}
    if b.flags & 0x0001:
        out["tail_bone"] = name(b.tail_bone)
    else:
        out["tail_offset"] = _r6(list(b.tail_offset))
    if b.flags & 0x0300:
        out["append_parent"], out["append_ratio"] = name(b.append_parent), _r6(b.append_ratio)
    if b.flags & 0x0400:
        out["fixed_axis"] = _r6(list(b.fixed_axis))
    if b.flags & 0x0800:
        out["local_axes"] = _r6(list(b.local_axes))
    if b.flags & 0x2000:
        out["external_key"] = b.external_key
    if b.flags & 0x0020:
        out.update({"ik_target": name(b.ik_target), "ik_loops": b.ik_loops, "ik_angle": _r6(b.ik_angle), "ik_links": links})
    return out


def _morph_fields(doc, m):
    r = pmx_edit._Reader(m.head, doc.encoding)
    name, name_en = r.text(), r.text()
    panel, kind = r.u8(), r.u8()
    out = {"name_en": name_en, "panel": panel, "kind": kind, "count": m.count if kind != 2 else len(m.bone_offsets)}
    if kind == 2:
        out["offsets_md5"] = hashlib.md5(b"".join(doc.bones[b].name.encode("utf-8") + raw for b, raw in m.bone_offsets)).hexdigest()
    else:
        out["offsets_md5"] = hashlib.md5(m.body).hexdigest()
    return name, out


def _largest_offset(doc, m):
    if m.kind != 1:
        return None
    size = doc.sizes["vertex"] + 12
    best = 0.0
    for k in range(m.count):
        d = struct.unpack_from("<3f", m.body, k * size + doc.sizes["vertex"])
        best = max(best, math.sqrt(sum(c * c for c in d)))
    return round(best, 6)


def _frame_items(doc, f):
    out = []
    for k, i in f.items:
        if k:
            out.append(["morph", _morph_fields(doc, doc.morphs[i])[0] if 0 <= i < len(doc.morphs) else None])
        else:
            out.append(["bone", doc.bones[i].name if 0 <= i < len(doc.bones) else None])
    return out


def _fields_changed(a, b):
    return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def _header_fields(doc):
    r = pmx._Reader(doc.header)
    version, extra, sizes = pmx._header(r)
    texts = [r.text() for _ in range(4)]
    return {"version": version, "encoding": doc.encoding, "extra_uv": extra, "sizes": sizes, "name": texts[0],
            "name_en": texts[1], "comment": texts[2], "comment_en": texts[3]}


def pmx_diff(a, b, limit=2000):
    """every part of two PMX documents (formats.pmx_edit) compared: the header; the vertices by index (place, normal,
    UVs, weights merged per bone, SDEF points, edge); faces, textures and materials; bones, morphs, display frames by
    name (the n-th of a name); rigid bodies and joints by index; the soft bodies' bytes.  Indices into other parts are
    compared as the names they point to, so items appended at the end change nothing before them.  Returns the changes
    per part ("same", "changed_sections"); at most `limit` vertices are listed per kind of change."""
    rep = {"counts": {}, "changed_sections": []}
    ga, gb = pmx_edit.geometry(a), pmx_edit.geometry(b)
    for tag, doc, g in (("a", a, ga), ("b", b, gb)):
        rep["counts"][tag] = {"vertices": len(doc.vertices), "faces": len(g.faces) // 3, "textures": len(g.textures),
                              "materials": len(g.materials), "bones": len(doc.bones), "morphs": len(doc.morphs),
                              "display_frames": len(doc.frames), "rigid_bodies": len(doc.rigid_bodies),
                              "joints": len(pmx_edit.joints(doc))}
    ha, hb = _header_fields(a), _header_fields(b)
    rep["header"] = {"same": a.header == b.header, "changed": _fields_changed(ha, hb)}
    # vertices
    mat_of = np.full(len(b.vertices), "(none)", dtype=object)
    start = 0
    for m in gb.materials:
        idx = np.array(gb.faces[start:start + m.faces], dtype=np.int64)
        mat_of[np.unique(idx[idx < len(b.vertices)])] = m.name
        start += m.faces
    v = {"count": [len(a.vertices), len(b.vertices)], "position_changed": 0, "normal_changed": 0, "uv_changed": 0,
         "extra_uv_changed": 0, "edge_changed": 0, "weights_changed": 0, "kind_changed": {}, "sdef_changed": 0,
         "weight_changes": [], "position_changes": []}
    sums = {}
    na, nb = len(a.bones), len(b.bones)
    for i in range(min(len(a.vertices), len(b.vertices))):
        va, vb = a.vertices[i], b.vertices[i]
        if va.head[0:12] != vb.head[0:12]:
            v["position_changed"] += 1
            if len(v["position_changes"]) < limit:
                pa, pb = np.array(va.position()), np.array(vb.position())
                v["position_changes"].append({"vertex": i, "material": mat_of[i], "moved": round(float(np.linalg.norm(pb - pa)), 6)})
        v["normal_changed"] += va.head[12:24] != vb.head[12:24]
        v["uv_changed"] += va.head[24:32] != vb.head[24:32]
        v["extra_uv_changed"] += va.head[32:] != vb.head[32:]
        v["edge_changed"] += va.edge != vb.edge
        v["sdef_changed"] += va.sdef != vb.sdef
        if va.kind != vb.kind:
            key = "%s->%s" % (va.kind, vb.kind)
            v["kind_changed"][key] = v["kind_changed"].get(key, 0) + 1
        wa = {a.bones[k].name if k < na else k: w for k, w in _merged(va).items()}
        wb = {b.bones[k].name if k < nb else k: w for k, w in _merged(vb).items()}
        for n in set(wa) | set(wb):
            s = sums.setdefault(n, [0.0, 0.0])
            s[0] += wa.get(n, 0.0)
            s[1] += wb.get(n, 0.0)
        if set(wa) != set(wb) or any(abs(wa[n] - wb[n]) > 1e-6 for n in wa):
            v["weights_changed"] += 1
            if len(v["weight_changes"]) < limit:
                v["weight_changes"].append({"vertex": i, "material": mat_of[i], "position": _r6(list(vb.position())),
                                            "a": [[n, round(w, 6)] for n, w in sorted(wa.items(), key=lambda x: -x[1])],
                                            "b": [[n, round(w, 6)] for n, w in sorted(wb.items(), key=lambda x: -x[1])]})
    v["bone_weight_sums"] = {str(n): [round(s[0], 6), round(s[1], 6)] for n, s in sums.items() if abs(s[0] - s[1]) > 1e-6}
    rep["vertices"] = v
    # faces, textures, materials
    fa, fb = np.array(ga.faces).reshape(-1, 3), np.array(gb.faces).reshape(-1, 3)
    rep["faces"] = {"same": ga.faces == gb.faces, "count": [len(fa), len(fb)],
                    "triangles_changed": int((fa[:min(len(fa), len(fb))] != fb[:min(len(fa), len(fb))]).any(axis=1).sum())}
    rep["textures"] = {"same": ga.textures == gb.textures, "a": ga.textures if ga.textures != gb.textures else None,
                       "b": gb.textures if ga.textures != gb.textures else None}
    mats = []
    for ma, mb in zip(ga.materials, gb.materials):
        da = {k: _r6(list(x) if isinstance(x, tuple) else x) for k, x in vars(ma).items()}
        db = {k: _r6(list(x) if isinstance(x, tuple) else x) for k, x in vars(mb).items()}
        ch = _fields_changed(da, db)
        if ch:
            mats.append({"material": mb.name, "fields": ch})
    rep["materials"] = {"count": [len(ga.materials), len(gb.materials)], "changed": mats,
                        "added": [m.name for m in gb.materials[len(ga.materials):]],
                        "removed": [m.name for m in ga.materials[len(gb.materials):]]}
    # bones
    ka, kb = _keyed([x.name for x in a.bones]), _keyed([x.name for x in b.bones])
    ia = {k: i for i, k in enumerate(ka)}
    bones = {"count": [na, nb], "added": [], "removed": [], "changed": []}
    for j, k in enumerate(kb):
        fb_ = _bone_fields(b, b.bones[j])
        if k not in ia:
            bones["added"].append(dict({"index": j, "name": k[0]}, **fb_))
            continue
        i = ia[k]
        ch = _fields_changed(_bone_fields(a, a.bones[i]), fb_)
        if i != j:
            ch["index"] = [i, j]
        if ch:
            bones["changed"].append({"index": j, "name": k[0], "fields": ch})
    bones["removed"] = [{"index": ia[k], "name": k[0]} for k in ka if k not in set(kb)]
    rep["bones"] = bones
    # morphs
    ma_ = [_morph_fields(a, m) for m in a.morphs]
    mb_ = [_morph_fields(b, m) for m in b.morphs]
    ka, kb = _keyed([n for n, _ in ma_]), _keyed([n for n, _ in mb_])
    ia = {k: i for i, k in enumerate(ka)}
    morphs = {"count": [len(a.morphs), len(b.morphs)], "added": [], "removed": [], "changed": []}
    for j, k in enumerate(kb):
        if k not in ia:
            morphs["added"].append(dict({"index": j, "name": k[0], "largest_offset": _largest_offset(b, b.morphs[j])}, **mb_[j][1]))
            continue
        ch = _fields_changed(ma_[ia[k]][1], mb_[j][1])
        if ia[k] != j:
            ch["index"] = [ia[k], j]
        if ch:
            morphs["changed"].append({"index": j, "name": k[0], "fields": ch})
    morphs["removed"] = [{"index": ia[k], "name": k[0]} for k in ka if k not in set(kb)]
    rep["morphs"] = morphs
    # display frames
    fa_ = {pmx_edit._Reader(f.names, a.encoding).text(): f for f in a.frames}
    fb_ = {pmx_edit._Reader(f.names, b.encoding).text(): f for f in b.frames}
    frames = {"count": [len(a.frames), len(b.frames)], "changed": [], "added": sorted(set(fb_) - set(fa_)),
              "removed": sorted(set(fa_) - set(fb_))}
    for n in [pmx_edit._Reader(f.names, b.encoding).text() for f in b.frames]:
        if n not in fa_:
            continue
        xa, xb = _frame_items(a, fa_[n]), _frame_items(b, fb_[n])
        added = list(xb)
        removed = []
        for it in xa:
            if it in added:
                added.remove(it)
            else:
                removed.append(it)
        if added or removed or fa_[n].names != fb_[n].names or (not added and not removed and xa != xb):
            frames["changed"].append({"frame": n, "added": added, "removed": removed})
    rep["display_frames"] = frames
    # rigid bodies, joints, soft bodies
    rbs = []
    for i, (ra, rb) in enumerate(zip(a.rigid_bodies, b.rigid_bodies)):
        da = dict({"names": list(pmx_edit.rigid_names(a, ra)), "bone": a.bones[ra.bone].name if 0 <= ra.bone < na else None},
                  **{k: _r6(list(x) if isinstance(x, tuple) else x) for k, x in vars(pmx_edit.rigid_body(ra)).items()})
        db = dict({"names": list(pmx_edit.rigid_names(b, rb)), "bone": b.bones[rb.bone].name if 0 <= rb.bone < nb else None},
                  **{k: _r6(list(x) if isinstance(x, tuple) else x) for k, x in vars(pmx_edit.rigid_body(rb)).items()})
        ch = _fields_changed(da, db)
        if ch:
            rbs.append({"rigid_body": db["names"][0], "fields": ch})
    rep["rigid_bodies"] = {"count": [len(a.rigid_bodies), len(b.rigid_bodies)], "changed": rbs,
                           "added": [pmx_edit.rigid_names(b, x)[0] for x in b.rigid_bodies[len(a.rigid_bodies):]],
                           "removed": [pmx_edit.rigid_names(a, x)[0] for x in a.rigid_bodies[len(b.rigid_bodies):]]}
    jts = []
    ja, jb = pmx_edit.joints(a), pmx_edit.joints(b)
    rname_a = [pmx_edit.rigid_names(a, x)[0] for x in a.rigid_bodies]
    rname_b = [pmx_edit.rigid_names(b, x)[0] for x in b.rigid_bodies]
    for x, y in zip(ja, jb):
        da = {k: _r6(list(val) if isinstance(val, tuple) else val) for k, val in vars(x).items()}
        db = {k: _r6(list(val) if isinstance(val, tuple) else val) for k, val in vars(y).items()}
        da["a"], da["b"] = [rname_a[i] if 0 <= i < len(rname_a) else None for i in (x.a, x.b)]
        db["a"], db["b"] = [rname_b[i] if 0 <= i < len(rname_b) else None for i in (y.a, y.b)]
        ch = _fields_changed(da, db)
        if ch:
            jts.append({"joint": y.name, "fields": ch})
    rep["joints"] = {"count": [len(ja), len(jb)], "changed": jts, "added": [x.name for x in jb[len(ja):]],
                     "removed": [x.name for x in ja[len(jb):]]}
    rep["soft_bodies"] = {"same": pmx_edit._split_tail(a)[1] == pmx_edit._split_tail(b)[1]}
    # which parts differ
    if not rep["header"]["same"]:
        rep["changed_sections"].append("header")
    if v["count"][0] != v["count"][1] or any(v[k] for k in ("position_changed", "normal_changed", "uv_changed", "extra_uv_changed",
                                                              "edge_changed", "weights_changed", "sdef_changed")) or v["kind_changed"]:
        rep["changed_sections"].append("vertices")
    if not rep["faces"]["same"]:
        rep["changed_sections"].append("faces")
    if not rep["textures"]["same"]:
        rep["changed_sections"].append("textures")
    if mats or len(ga.materials) != len(gb.materials):
        rep["changed_sections"].append("materials")
    for part in ("bones", "morphs"):
        if rep[part]["added"] or rep[part]["removed"] or rep[part]["changed"]:
            rep["changed_sections"].append(part)
    if frames["changed"] or frames["added"] or frames["removed"]:
        rep["changed_sections"].append("display_frames")
    if rbs or len(a.rigid_bodies) != len(b.rigid_bodies):
        rep["changed_sections"].append("rigid_bodies")
    if jts or len(ja) != len(jb):
        rep["changed_sections"].append("joints")
    if not rep["soft_bodies"]["same"]:
        rep["changed_sections"].append("soft_bodies")
    rep["same"] = not rep["changed_sections"]
    return rep


def _limb_axes(m):
    """(limb_side, rest a, rest b) of the limbs (LIMBS) the model has"""
    out = []
    for s in SIDES:
        for limb, (a, b, _, _) in LIMBS.items():
            if (s + a) in m.by_name and (s + b) in m.by_name:
                out.append(("%s_%s" % (limb, TAGS[s]), m.rest[m.by_name[s + a]], m.rest[m.by_name[s + b]]))
    return out


def skin_delta(models, motion, frames, tol=1e-4, limit=400):
    """{tag: rig_skin Model} (the first is the reference; all with its vertices) posed and skinned on `frames` of
    `motion`: per other model and frame, the vertices that land more than `tol` units from where the reference puts
    them, the most (cm), per material, and their places along the limbs (LIMBS: t 0 at the limb's first joint, 1 at its
    second, at rest; each vertex to the limb whose axis is nearest, t within -0.25..1.5; "other" when none)"""
    tags = list(models)
    ref = models[tags[0]]
    tracks = fk.tracks_of(motion)
    parts = Parts(ref)
    axes = _limb_axes(ref)
    out = {t: {} for t in tags[1:]}
    for f in frames:
        p0 = SKIN.skin(ref, SKIN.solve(ref, SKIN.keys_at(ref, tracks, f)))
        for t in tags[1:]:
            m = models[t]
            if len(m.points) != len(ref.points):
                raise ValueError("model %s has %d vertices, %s %d" % (t, len(m.points), tags[0], len(ref.points)))
            p = SKIN.skin(m, SKIN.solve(m, SKIN.keys_at(m, tracks, f)))
            d = np.linalg.norm(p - p0, axis=1)
            moved = np.flatnonzero(d > tol)
            mats = {}
            for k in moved:
                name = parts.mat_of_vertex[k] or "(none)"
                e = mats.setdefault(name, {"moved": 0, "max_cm": 0.0})
                e["moved"] += 1
                e["max_cm"] = max(e["max_cm"], round(float(d[k]) * UNIT_CM, 4))
            places = {}
            if len(moved):
                rest = ref.points[moved]
                best_r = np.full(len(moved), np.inf)
                best = np.full(len(moved), -1)
                best_t = np.zeros(len(moved))
                for n, (_, a, b) in enumerate(axes):
                    r, tt = _line_distance(rest, a, b)
                    ok = (tt >= -0.25) & (tt <= 1.5) & (r < best_r)
                    best_r = np.where(ok, r, best_r)
                    best = np.where(ok, n, best)
                    best_t = np.where(ok, tt, best_t)
                for n, (name, _, _) in enumerate(axes):
                    sel = best == n
                    if sel.any():
                        places[name] = {"vertices": int(sel.sum()), "t_min": round(float(best_t[sel].min()), 6),
                                        "t_max": round(float(best_t[sel].max()), 6),
                                        "max_cm": round(float(d[moved][sel].max()) * UNIT_CM, 4)}
                if (best < 0).any():
                    places["other"] = {"vertices": int((best < 0).sum()), "max_cm": round(float(d[moved][best < 0].max()) * UNIT_CM, 4)}
            out[t][str(int(f))] = {"moved": int(len(moved)), "max_cm": round(float(d.max()) * UNIT_CM, 4) if len(d) else 0.0,
                                   "materials": mats, "places": places, "vertices": moved.tolist()[:limit]}
    return out


# ---- the parts of Sour's Rin (and models built like her) -----------------------------------------------------------------

TRUNK = ("上半身", "腰椎上部", "上半身2", "胸椎上部")
LIMBS = {      # name: (from bone, to bone, bones the limb's skin hangs on, t range)
    "upper_arm": ("腕", "ひじ", ("腕W", "腕", "腕補助", "腕捩", "腕捩1", "腕捩2", "腕捩3"), (0.08, 0.92)),
    "forearm": ("ひじ", "手首", ("ひじ", "ひじ補助", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3", "手首", "手首補助"), (0.08, 1.06)),
    "thigh": ("足", "ひざ", ("足D", "足", "足補助"), (0.15, 0.9)),
    "shin": ("ひざ", "足首", ("ひざD", "ひざ"), (0.1, 0.9)),
}
JOINTS = {     # name: (centre bone, radius units, bones on either side)
    "shoulder": ("腕", 0.75, ("肩", "腕W", "腕", "腕補助", "腕捩", "腕捩1", "腕捩2", "腕捩3")),
    "elbow": ("ひじ", 0.6, ("腕捩", "腕捩1", "腕捩2", "腕捩3", "腕W", "ひじ", "ひじ補助", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3")),
    "wrist": ("手首", 0.45, ("手捩", "手捩1", "手捩2", "手捩3", "手首", "手首補助")),
    "hip": ("足", 1.1, ("足D", "足", "足補助")),
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
        fore = parts.vertices(_sided(("ひじ", "ひじ補助+", "手捩", "手捩1", "手捩2", "手捩3", "手首", "手首補助"), s) + [
            s + n for n in ("親指０", "親指１", "親指２", "人指０", "人指１", "人指２", "人指３", "中指０", "中指１", "中指２", "中指３",
                            "薬指０", "薬指１", "薬指２", "薬指３", "小指０", "小指１", "小指２", "小指３")], materials=("skin", "nail", "White"))
        upper = parts.vertices(_sided(("腕W", "腕補助", "腕捩", "腕捩1", "腕捩2", "腕捩3"), s), materials=("skin",))
        if len(trunk_f) and len(fore):
            rec["penetration"]["forearm_hand_in_dress_" + t] = _pen(m, fore, trunk_f, pts, nrm, rest_nrm)
        if len(upper):
            uf = m.faces[parts.faces_of(upper, ("skin",))]
            if len(uf) and len(fore):
                rec["penetration"]["forearm_in_upper_arm_" + t] = _pen(m, parts.vertices(_sided(("手捩", "手捩1", "手捩2", "手捩3"), s), materials=("skin",)), uf, pts, nrm, rest_nrm)
        thigh = parts.vertices(_sided(("足D", "足補助"), s), materials=("skin",))
        other = parts.vertices(_sided(("足D", "足補助"), "左" if s == "右" else "右"), materials=("skin",))
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
    b.add_argument("--alt", action="append", default=[], help="TAG:loops=N[,angle=RAD][,least_bend=DEG]")
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
    e = sub.add_parser("physics")
    e.add_argument("model")
    e.add_argument("--out", required=True)
    e.add_argument("--gravity", type=float, nargs="+", default=[94.0, 122.5])
    g = sub.add_parser("diff")
    g.add_argument("a")
    g.add_argument("b")
    g.add_argument("--out", required=True)
    h = sub.add_parser("delta")
    h.add_argument("dance")
    h.add_argument("--model", action="append", default=[], help="TAG=PATH (the first is the reference)")
    h.add_argument("--out", required=True)
    h.add_argument("--frames", type=int, nargs="*", default=[])
    h.add_argument("--angles")
    h.add_argument("--pick", type=int, default=4)
    args = ap.parse_args(argv)
    if args.cmd == "diff":
        with open(args.a, "rb") as f:
            da = f.read()
        with open(args.b, "rb") as f:
            db = f.read()
        rep = pmx_diff(pmx_edit.loads(da), pmx_edit.loads(db))
        rep["a"], rep["b"] = os.path.abspath(args.a), os.path.abspath(args.b)
        rep["md5"] = {"a": hashlib.md5(da).hexdigest(), "b": hashlib.md5(db).hexdigest()}
        _json(args.out, rep)
        print(json.dumps({"same": rep["same"], "changed_sections": rep["changed_sections"],
                          "bones_added": [x["name"] for x in rep["bones"]["added"]],
                          "bones_changed": [x["name"] for x in rep["bones"]["changed"]],
                          "morphs_added": [x["name"] for x in rep["morphs"]["added"]],
                          "vertices_weights_changed": rep["vertices"]["weights_changed"],
                          "vertices_moved": rep["vertices"]["position_changed"]}, ensure_ascii=True))
        return 0
    if args.cmd == "delta":
        paths = _tagged(args.model, "--model")
        if len(paths) < 2:
            raise SystemExit("give two or more --model TAG=PATH")
        models = {tag: SKIN.Model.load(p) for tag, p in paths.items()}
        frames = set(args.frames)
        picked = {}
        if args.angles:
            ang = dict(np.load(args.angles))
            frames0 = ang.pop("frames")
            picked = {k: [(int(frames0[f]), v) for f, v in got] for k, got in pick_frames(ang, per=args.pick).items()}
            frames |= {f for got in picked.values() for f, _ in got}
        rep = skin_delta(models, vmd.load(args.dance), sorted(frames))
        _json(args.out, {"models": paths, "picked": picked, "frames": sorted(frames), "report": rep})
        print(json.dumps({t: {"frames": len(r), "moved_max": max((x["moved"] for x in r.values()), default=0),
                              "max_cm": max((x["max_cm"] for x in r.values()), default=0.0),
                              "materials": sorted({m for x in r.values() for m in x["materials"]})}
                          for t, r in rep.items()}, ensure_ascii=True))
        return 0
    if args.cmd == "physics":
        rep = physics_report(pmx_edit.load(args.model), tuple(args.gravity))
        rep["model"] = os.path.abspath(args.model)
        _json(args.out, rep)
        print(json.dumps({"bodies": rep["bodies"], "joints": rep["joints"], "overlaps_at_rest": len(rep["overlaps_at_rest"]),
                          "deepest": rep["overlaps_at_rest"][:5]}, ensure_ascii=True))
        return 0
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
        print(json.dumps({t: {s: {k: v[k] for k in ("reachable_miss_gt_4mm", "reachable_miss_cm_max", "unreachable", "knee_jumps",
                                                     "knee_at_least_bend")}
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
