"""Measure a retargeted dance against the dance it came from, from what the viewer sees: does a hand that touches the
body in the source still touch the same part of the target, does an arm go into the target's body, does a foot that
stands on the floor in the source stand still on the floor in the target, and does a foot on its toe reach the floor.

    python tools/retarget_check.py SOURCE.vmd SOURCE_BODY TARGET.vmd TARGET.pmx --report r.json [--arrays a.npz]
                                   [--last F]

SOURCE_BODY is what tools/retarget.py takes (a model or a .json body); TARGET.vmd is any dance of the target (the
retargeted one, or the source dance itself read on the target, to see what the retarget changed).  The measures are
made apart from tools/retarget.py's own arithmetic (it is used only to read the bodies): the bones by forward kinematics
(tools/motor_layer.py), the legs as MMD's IK puts them (tools/leg_ik.py), the target's shoes as their skinned vertices
(tools/sink_check.py), and the body's parts as the convex polytopes of their vertices along 96 directions (tools/retarget.py
uses 98 others).

* contacts: a hand point (the palm's middle, the middle finger's tip) of the source within TOUCH of a part of its body
  (head with what rides on 頭, chest, belly, hips, each thigh) touches it.  On those frames the target's same point is
  'kept' when its distance to the same part of the target is within KEEP of the source's (the source's own distance,
  not less than 0), 'lost' when it is more than LOST off (or LOST inside).  Per part: the touching frames, the share
  kept, the lost runs.
* arms in the body: the target's arm as capsules on its bones (the upper arm, the forearm, the hand; radii the 60th
  percentile of their vertices' distance from the bone), the deepest its forearm and hand go into a part (head, ribbon,
  chest, belly, hips, thighs; each the convex polytope of its vertices) and the upper arm's half by the elbow into the
  head (the upper arm lies against the trunk at the armpit and along the side); a hand on a part the source's hand
  touches (and its forearm's half by the wrist), the hair and the skirt (soft: the physics or the hull's shape) counted
  apart.  The frames over 0.5
  and 1 cm (also per part), the deepest, the runs.  The same for the source's arm in its own body, with the same rule
  (its hand on a part it touches counted apart).
* plants: a source foot stands where its foot IK goal or toe IK goal (forward kinematics: where the foot is meant to
  be) lies within PLANT_EPS of its rest height and moves less than STILL a frame, for PLANT_MIN frames; on its toe
  when pitched more than 4 degrees.  On those frames the target's shoe: its lowest point's height over the floor (the
  shoes' lowest point at rest) and its slide (sink_check's: the slowest touching vertex's move), per plant the path.
  Over the whole dance, the path the target's shoe slides while it is on the floor (within FLOOR_CM; the slowest touching
  vertex, so a foot turning on its ball, toe or heel does not travel), on the source's plants and elsewhere, a minute:
  a foot the source turns or moves near the floor and the target puts on it slides there.  And the one-frame jumps
  along the floor (pops): the target's shoe under POP_NEAR_CM on both frames moving more than POP_CM to the next, with
  the source's foot's move there (the slowest point of its heel-to-toe line); a jump the source does not make (it moves
  less than POP_SHARE of that) is the target's own (the summary's pops_not_in_source).
* touch runs (in contacts): each run of the source's touch with its frames, the source's distance, the hand point's
  speed in the part's frame (a hand resting on a part moves with it: a run of RESTING_MIN frames and more slower than
  RESTING_SPEED rests; a short or fast one passes by), the distance to the part's nearest vertex on both bodies (the
  convex polytope fills a part's hollows: a hand on the chest under its ribbon lies centimetres inside the polytope and
  on the mesh), and the frames kept.
* choreography (chore): what the retarget must not change, the source on its body against the target on its own, by
  forward kinematics: the timing (per point, the lag of the best correlation of the speeds in LAG_WINDOW windows), the
  hands' directions from the shoulders in the chest's frame (the angle between the source's and the target's), the
  head's and the chest's world turns, the steps between the source's plants (the length's ratio, to read against the
  bodies' legs' ratio, and the direction), and the jumps (both feet's IK goals and toe goals over their rest heights by
  JUMP_CM, the target's by JUMP_CM times the legs' ratio, for JUMP_MIN frames: matched, the peak's frame and height, and
  the target's airborne runs the source does not have).
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
FPS = 30.0
FLOOR_CM = 0.4                  # cm (a05's 4 mm): a shoe whose lowest point is this close to the floor is on it
# a one-frame jump along the floor the source does not make (review_integ 2026-10-17, its scripts/pops.py: the retarget
# gave a turning foot's hold back in one frame, the song's 128.0 s 13.7 cm with the shoe 1 cm up, and the later layers put
# that frame on the floor): the target's shoe lower than POP_NEAR_CM on both frames and its slowest touching vertex moving
# more than POP_CM to the next, while the source's foot (the slowest point of its heel-to-toe line, as source_plants
# reads it) moves less than POP_SHARE of that
POP_NEAR_CM = 2.0
POP_CM = 8.0
POP_SHARE = 0.5
RESTING_MIN = 4                 # frames: a touch this long ...
RESTING_SPEED = 35.0            # cm/s: ... whose hand point moves slower than this in the part's frame (median) rests on it
LAG_WINDOW = 60                 # frames (2 s): the timing's windows, LAG_HOP apart, lags within LAG_MAX
LAG_HOP = 30
LAG_MAX = 5
STEP_MIN_CM = 10.0              # cm: the source's steps between plants this long and longer are compared
JUMP_CM = 2.5                   # cm (mv_inspect's 宙): both feet this high over their rest heights ...
JUMP_MIN = 4                    # frames: ... this long is a jump
CHORE_POINTS = ("センター", "頭", "左手首", "右手首", "左足ＩＫ", "右足ＩＫ")
SKIP_SHOULDER = 0.5
PARTS = {"head": ("頭", ("頭",), False), "hair": ("頭", ("髮親", "髪親"), True), "ribbon": ("頭", ("リボン親",), False),
         "chest": ("上半身2", ("上半身2", "胸椎上部", "胸リボン親"), False), "belly": ("上半身", ("上半身", "腰椎上部"), False),
         "hips": ("下半身", ("下半身", "腰"), False), "thigh_左": ("左足", ("左足", "左足D"), False),
         "thigh_右": ("右足", ("右足", "右足D"), False), "skirt": ("下半身", (), True)}


TREE_PARTS = ("ribbon", "hair")


def under(body, roots):
    """the bones `roots` and every bone under them (by the model's parents)"""
    out = set(roots)
    parents = [b.parent for b in body.model.bones]
    grown = True
    while grown:
        grown = False
        for i, p in enumerate(parents):
            if p in out and i not in out:
                out.add(i)
                grown = True
    return sorted(out)


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


def _cube_directions(n=4):
    """unit vectors through an n x n grid on each face of a cube (6 n^2 of them)"""
    t = (np.arange(n) + 0.5) / n * 2.0 - 1.0
    out = []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            for u in t:
                for v in t:
                    p = np.zeros(3)
                    p[axis] = sign
                    p[(axis + 1) % 3] = u
                    p[(axis + 2) % 3] = v
                    out.append(p / np.linalg.norm(p))
    return np.array(out)


CUBE = _cube_directions()


class Part:
    """a part's vertices in its riding bone's rest frame, as the convex polytope they span along the 96 directions of a
    cube's faces: inside is past no face; the depth inside is the nearest face's distance, outside the farthest face's
    (a lower bound of the distance, exact next to a face).  A soft part (the skirt) is measured apart."""

    def __init__(self, body, part):
        ride, bones, self.soft = PARTS[part]
        if part == "skirt":
            idx = [b.index for b in body.model.bones if "スカート" in b.name or "ｽｶｰﾄ" in b.name]
        else:
            idx = [body.i(n) for n in bones if body.has(n)]
            if part in TREE_PARTS:              # the ribbon's loops and the hair's strands hang on bones under them
                idx = under(body, idx)
        m = np.isin(body.main_bone, idx) if len(body.vertices) else np.zeros(0, bool)
        self.ok = body.has(ride) and m.sum() >= 8
        if not self.ok:
            return
        self.ride = ride
        P = body.vertices[m] - body.rest(ride)
        self.d = np.max(P @ CUBE.T, axis=0)
        self.points = P

    def distance(self, q):
        """signed distances of points q [n, 3] (in the part's frame)"""
        return np.max(np.asarray(q, dtype=np.float64) @ CUBE.T - self.d, axis=-1)

    def mesh_distance(self, q):
        """distances of points q [n, 3] (in the part's frame) to the part's nearest vertex (unsigned)"""
        q = np.asarray(q, dtype=np.float64).reshape(-1, 3)
        out = np.empty(len(q))
        for a in range(0, len(q), 64):
            out[a:a + 64] = np.min(np.linalg.norm(q[a:a + 64, None, :] - self.points[None, :, :], axis=2), axis=1)
        return out


def parts_of(body):
    out = {}
    for part in PARTS:
        p = Part(body, part)
        if p.ok:
            out[part] = p
    return out


def hand_points(pose, side):
    """the palm's middle (half way from the wrist to 中指１) and the middle finger's tip (中指３ past 中指２ by 0.6 of their
    bone) [F, 3]; a body without the middle finger's bones: both at the wrist"""
    if not all(pose.sk.has(side + n) for n in ("中指１", "中指２", "中指３")):
        W = pose.get([side + "手首"])[side + "手首"][0]
        return {"palm": W, "tip": W}
    w = pose.get([side + "手首", side + "中指１", side + "中指２", side + "中指３"])
    palm = 0.5 * (w[side + "手首"][0] + w[side + "中指１"][0])
    tip = w[side + "中指３"][0] + 0.6 * (w[side + "中指３"][0] - w[side + "中指２"][0])
    return {"palm": palm, "tip": tip}


def part_locals(pose, parts, points):
    """part -> point -> the points in the part's frame [F, 3]"""
    rides = pose.get(sorted({p.ride for p in parts.values()}))
    out = {}
    for name, part in parts.items():
        pos, rot = rides[part.ride]
        out[name] = {k: ML.qrot(ML.qconj(rot), P - pos) for k, P in points.items()}
    return out


def part_distances(pose, parts, points):
    """part -> point -> signed distances [F]"""
    return {name: {k: parts[name].distance(q) for k, q in by.items()} for name, by in part_locals(pose, parts, points).items()}


def run_speed(local, a, b):
    """the median speed (cm/s) of a point [F, 3] in a part's frame over the frames a..b (and the step into it)"""
    lo = max(0, a - 1)
    v = np.linalg.norm(np.diff(local[lo:b + 1], axis=0), axis=1) * UNIT_CM * FPS
    return float(np.median(v)) if len(v) else 0.0


def resting(frames, speed):
    """a touch run of `frames` frames whose hand point moves `speed` cm/s in the part's frame rests on the part"""
    return bool(frames >= RESTING_MIN and speed < RESTING_SPEED)


def contacts(src_pose, src_parts, tgt_pose, tgt_parts):
    out = {}
    for side in SIDES:
        if not all(src_pose.sk.has(side + n) for n in ("手首", "中指１", "中指２", "中指３")):
            continue
        ls = part_locals(src_pose, src_parts, hand_points(src_pose, side))
        lt = part_locals(tgt_pose, tgt_parts, hand_points(tgt_pose, side))
        rows = {}
        for part in ls:
            if part not in lt or src_parts[part].soft:
                continue
            ds = {k: src_parts[part].distance(q) for k, q in ls[part].items()}
            dt = {k: tgt_parts[part].distance(q) for k, q in lt[part].items()}
            point = np.where(ds["palm"] <= ds["tip"], "palm", "tip")
            d_s = np.where(point == "palm", ds["palm"], ds["tip"])
            d_t = np.where(point == "palm", dt["palm"], dt["tip"])
            touch = d_s < TOUCH
            want = np.maximum(d_s, 0.0)
            kept = touch & (np.abs(d_t - want) <= KEEP)
            lost = touch & ((d_t - want > LOST) | (d_t < -LOST))
            touch_runs = []
            for a, b in runs(touch):
                main = "palm" if np.sum(point[a:b + 1] == "palm") >= np.sum(point[a:b + 1] == "tip") else "tip"
                speed = run_speed(ls[part][main], a, b)
                touch_runs.append({
                    "first": a, "last": b, "frames": b - a + 1, "point": main,
                    "source_cm": {"min": round(float(d_s[a:b + 1].min()) * UNIT_CM, 2), "p50": round(float(np.median(d_s[a:b + 1])) * UNIT_CM, 2)},
                    "speed_cm_s": round(speed, 1), "resting": resting(b - a + 1, speed),
                    "source_mesh_cm": round(float(np.median(src_parts[part].mesh_distance(ls[part][main][a:b + 1]))) * UNIT_CM, 2),
                    "target_cm": round(float(np.median(d_t[a:b + 1])) * UNIT_CM, 2),
                    "target_mesh_cm": round(float(np.median(tgt_parts[part].mesh_distance(lt[part][main][a:b + 1]))) * UNIT_CM, 2),
                    "kept_frames": int(kept[a:b + 1].sum())})
            rows[part] = {"source_touch_frames": int(touch.sum()), "kept_frames": int(kept.sum()),
                          "kept_share": round(float(kept.sum() / touch.sum()), 4) if touch.any() else None,
                          "lost_runs": [[a, b] for a, b in runs(lost)],
                          "source_cm": quant(d_s[touch] * UNIT_CM, (50,)), "target_cm": quant(d_t[touch] * UNIT_CM, (50, 90)),
                          "runs": touch_runs}
        out[side] = rows
    return out


def arm_radii(body, side):
    def radius(bones, a, b, default):
        idx = [body.i(side + n) for n in bones if body.has(side + n)]
        m = np.isin(body.main_bone, idx) if len(body.vertices) else np.zeros(0, bool)
        if m.sum() < 8 or not (body.has(side + a) and body.has(side + b)):
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
        touch_deep = np.zeros(len(S))
        soft_deep = {}
        part_deep = {}
        dist = part_distances(pose, parts, {i: p for i, p in enumerate(pts)})
        for part, by in dist.items():
            for i, d in by.items():
                if seg[i] == 0 and (part != "head" or share[i] < SKIP_SHOULDER):
                    continue                    # the upper arm: only its half by the elbow, only against the head
                if parts[part].soft:
                    soft_deep[part] = np.maximum(soft_deep.get(part, 0.0), rad[i] - d)
                    continue
                pen = rad[i] - d
                near_hand = seg[i] == 2 or (seg[i] == 1 and share[i] >= 0.5)
                if near_hand and touching is not None and part in touching.get(side, {}):
                    on = touching[side][part]
                    touch_deep = np.maximum(touch_deep, np.where(on, pen, 0.0))
                    pen = np.where(on, 0.0, pen)
                deep = np.maximum(deep, pen)
                part_deep[part] = np.maximum(part_deep.get(part, 0.0), pen)
        deep = np.maximum(deep, 0.0)
        out[side] = {"frames_over_0.5cm": int(np.sum(deep > 0.0625)), "frames_over_1cm": int(np.sum(deep > 0.125)),
                     "part_frames_over_1cm": {p: int(np.sum(v > 0.125)) for p, v in sorted(part_deep.items())},
                     "soft_frames_over_1cm": {p: int(np.sum(v > 0.125)) for p, v in soft_deep.items()},
                     "touched_part_frames_over_1cm": int(np.sum(touch_deep > 0.125)),
                     "touched_part_deepest_cm": round(float(touch_deep.max()) * UNIT_CM, 3) if len(touch_deep) else 0.0,
                     "deepest_cm": round(float(deep.max()) * UNIT_CM, 3) if len(deep) else 0.0,
                     "runs_over_1cm": [[a, b] for a, b in runs(deep > 0.125)], "_deep": deep}
    return out


LINE_TS = np.array([-0.3, 0.0, 1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6, 1.0])


def source_line(pose, body, side):
    """(the points [F, k, 3] along the line from the source's foot IK goal (and 0.3 of the foot behind it, the heel) to its
    toe IK goal, each one's height over the floor [F, k] as the goals are over their rest heights between them, the
    foot IK goal's world turn [F, 4])"""
    w = pose.get([side + "足ＩＫ", side + "つま先ＩＫ"])
    ga, qa = w[side + "足ＩＫ"]
    gt, _ = w[side + "つま先ＩＫ"]
    ha = ga[:, 1] - body.rest(side + "足ＩＫ")[1]
    ht = gt[:, 1] - body.rest(side + "つま先ＩＫ")[1]
    P = ga[:, None, :] + LINE_TS[None, :, None] * (gt - ga)[:, None, :]
    H = ha[:, None] + LINE_TS[None, :] * (ht - ha)[:, None]
    return P, H, qa


def source_steps(pose, body):
    """per side [F]: the source's foot's move to the next frame along the floor (units; the last frame 0): its line's
    (source_line) slowest point's, so that a foot turning on its ball, toe or heel does not travel"""
    out = {}
    for side in SIDES:
        P, _, _ = source_line(pose, body, side)
        v = np.zeros(len(P))
        if len(P) > 1:
            v[:-1] = np.linalg.norm(np.diff(P[:, :, [0, 2]], axis=0), axis=2).min(axis=1)
        out[side] = v
    return out


def source_plants(pose, body):
    """per side: [(first, last, toe)] where the source's foot stands (see the module's doc): points along the line from
    the foot IK goal (and 0.3 of the foot behind it, the heel) to the toe IK goal, each as high over the floor as the
    goals are over their rest heights between them; a frame stands when one of them is on the floor and still (a foot
    turning on its ball stands on the ball)"""
    out = {}
    for side in SIDES:
        P, H, qa = source_line(pose, body, side)
        v = np.zeros(H.shape)
        v[1:] = np.linalg.norm(np.diff(P[:, :, [0, 2]], axis=0), axis=2)
        still = np.minimum(v, np.concatenate([v[1:], v[-1:]], axis=0)) < STILL
        on = np.any((np.abs(H) < PLANT_EPS) & still, axis=1)
        fwd = ML.qrot(qa, np.broadcast_to(np.array([0.0, 0.0, -1.0]), qa[:, :3].shape))
        pitch = np.degrees(np.arcsin(np.clip(-fwd[:, 1], -1, 1)))
        out[side] = [(a, b, bool(np.median(pitch[a:b + 1]) > TOE_PITCH)) for a, b in runs(on, PLANT_MIN)]
    return out


def pops(h, sl, src_step, frames):
    """the one-frame jumps along the floor of one side (see POP_CM): h [F] the target's shoe over the floor (cm), sl [F]
    its slowest touching vertex's move to the next frame (cm), src_step [F] the source's foot's (cm)"""
    near = h < POP_NEAR_CM
    rows = []
    for t in np.flatnonzero(near[:-1] & near[1:] & (sl[:-1] > POP_CM)):
        rows.append({"frame": int(frames[t]), "s": round(float(frames[t]) / FPS, 2), "step_cm": round(float(sl[t]), 2),
                     "low_cm": [round(float(h[t]), 2), round(float(h[t + 1]), 2)],
                     "source_step_cm": round(float(src_step[t]), 2), "own": bool(src_step[t] < POP_SHARE * sl[t])})
    return {"count": len(rows), "own": int(sum(r["own"] for r in rows)), "rows": rows[:100]}


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
    steps = source_steps(src_pose, src_body)
    out = {}
    for side in SIDES:
        f = feet[side]
        h = (f["low"] - floor) * UNIT_CM
        sl = f["slide"] * UNIT_CM
        # the shoe on the floor over two frames, its slowest touching vertex's step, on the source's plants and elsewhere
        on = h < FLOOR_CM
        both = np.zeros(len(h), bool)
        both[:-1] = on[:-1] & on[1:]
        in_plant = np.zeros(len(h), bool)
        for a, b, _ in found[side]:
            in_plant[a:b] = True
        step = np.where(both, sl, 0.0)
        minutes = max(len(h) / FPS / 60.0, 1e-9)
        floor_slide = {"in_source_plants": round(float(step[in_plant].sum()) / minutes, 1),
                       "elsewhere": round(float(step[~in_plant].sum()) / minutes, 1)}
        fl, paths, toe_fl, where = [], [], [], []
        for a, b, toe in found[side]:
            fl.append(h[a:b + 1])
            paths.append(float(sl[a:b].sum()))
            where.append((a, b, toe))
            if toe:
                toe_fl.append(h[a:b + 1])
        fl = np.concatenate(fl) if fl else np.zeros(0)
        tf = np.concatenate(toe_fl) if toe_fl else np.zeros(0)
        out[side] = {"plants": len(found[side]), "frames": int(len(fl)), "float_cm": quant(np.maximum(fl, 0.0)),
                     "float_over_1cm_pct": round(100.0 * float(np.mean(fl > 1.0)), 3) if len(fl) else None,
                     "under_floor_frames": int(np.sum(fl < -0.1)), "under_floor_cm": quant(np.maximum(-fl, 0.0), (50, 90, 99, 100)),
                     "slide_path_cm": quant(paths), "plants_sliding_over_1cm": int(np.sum(np.array(paths) > 1.0)),
                     "toe_plants": int(sum(1 for _, _, t in found[side] if t)), "toe_float_cm": quant(np.maximum(tf, 0.0)),
                     "toe_float_over_1cm_pct": round(100.0 * float(np.mean(tf > 1.0)), 3) if len(tf) else None,
                     "sliding_runs": [[a, b, round(p, 2)] for (a, b, _), p in zip(where, paths) if p > 1.0],
                     "floor_slide_cm_per_min": floor_slide,
                     "pops": pops(h, sl, steps[side] * UNIT_CM, frames)}
    return out


def best_lags(vs, vt):
    """per window of LAG_WINDOW frames (LAG_HOP apart) where the source's speeds vs move, the lag (frames, + the target
    later) within LAG_MAX at which the target's speeds vt correlate best"""
    out = []
    for a in range(LAG_MAX, len(vs) - LAG_WINDOW - LAG_MAX, LAG_HOP):
        x = vs[a:a + LAG_WINDOW]
        if x.std() < 1e-4:
            continue
        best, lag = -2.0, 0
        for L in range(-LAG_MAX, LAG_MAX + 1):
            y = vt[a + L:a + L + LAG_WINDOW]
            if y.std() < 1e-4:
                continue
            c = float(np.corrcoef(x, y)[0, 1])
            if c > best:
                best, lag = c, L
        out.append(lag)
    return np.array(out, dtype=int)


def turn_deg(a, b):
    """the angle (degrees) between world turns a and b [F, 4]"""
    d = np.abs(np.sum(np.asarray(a) * np.asarray(b), axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))


def hip_height(body):
    """the hip joints' height over the ankles at rest (the mean of the sides): the legs' size"""
    return float(np.mean([body.rest(s + "足")[1] - body.rest(s + "足首")[1] for s in SIDES]))


def chore(src_pose, src_body, tgt_pose, tgt_body, found):
    """the choreography the target keeps (see the module's doc); found: the source's plants (source_plants)"""
    out = {}
    names = [n for n in CHORE_POINTS if src_pose.sk.has(n) and tgt_pose.sk.has(n)]
    ws, wt = src_pose.get(names), tgt_pose.get(names)
    timing = {}
    for n in names:
        vs = np.linalg.norm(np.diff(ws[n][0], axis=0), axis=1)
        vt = np.linalg.norm(np.diff(wt[n][0], axis=0), axis=1)
        lags = best_lags(vs, vt)
        timing[n] = {"windows": int(len(lags)), "lag0_share": round(float(np.mean(lags == 0)), 4) if len(lags) else None,
                     "lag_ge2_share": round(float(np.mean(np.abs(lags) >= 2)), 4) if len(lags) else None,
                     "lag_p50": float(np.median(lags)) if len(lags) else None}
    out["timing"] = timing
    hands = {}
    for side in SIDES:
        need = ["上半身2", side + "腕", side + "手首"]
        if not all(src_pose.sk.has(n) and tgt_pose.sk.has(n) for n in need):
            continue
        a_s, a_t = src_pose.get(need), tgt_pose.get(need)
        u = ML.qrot(ML.qconj(a_s["上半身2"][1]), a_s[side + "手首"][0] - a_s[side + "腕"][0])
        v = ML.qrot(ML.qconj(a_t["上半身2"][1]), a_t[side + "手首"][0] - a_t[side + "腕"][0])
        ang = np.degrees(np.arccos(np.clip(np.sum(unit(u) * unit(v), axis=1), -1.0, 1.0)))
        hands[side] = {"deg": quant(ang), "frames_over_10deg": int(np.sum(ang > 10.0)), "frames_over_20deg": int(np.sum(ang > 20.0)),
                       "runs_over_20deg": [[a, b] for a, b in runs(ang > 20.0, 3)][:40]}
    out["hand_directions"] = hands
    for n, key in (("頭", "head_turn_deg"), ("上半身2", "chest_turn_deg")):
        if src_pose.sk.has(n) and tgt_pose.sk.has(n):
            out[key] = quant(turn_deg(src_pose.get([n])[n][1], tgt_pose.get([n])[n][1]))
    scale = hip_height(tgt_body) / hip_height(src_body)
    out["legs_ratio"] = round(scale, 4)
    steps = {}
    for side in SIDES:
        ik = side + "足ＩＫ"
        if ik not in ws or ik not in wt:
            continue
        cs = np.array([ws[ik][0][a:b + 1][:, [0, 2]].mean(axis=0) for a, b, _ in found.get(side, [])]).reshape(-1, 2)
        ct = np.array([wt[ik][0][a:b + 1][:, [0, 2]].mean(axis=0) for a, b, _ in found.get(side, [])]).reshape(-1, 2)
        ds, dt = np.diff(cs, axis=0), np.diff(ct, axis=0)
        ls, lt = np.linalg.norm(ds, axis=1), np.linalg.norm(dt, axis=1)
        big = ls * UNIT_CM >= STEP_MIN_CM
        ang = np.degrees(np.abs(np.arctan2(ds[:, 0] * dt[:, 1] - ds[:, 1] * dt[:, 0], np.sum(ds * dt, axis=1))))
        steps[side] = {"steps": int(big.sum()), "length_ratio": quant(lt[big] / ls[big]) if big.any() else None,
                       "direction_deg": quant(ang[big]) if big.any() else None}
    out["steps"] = steps
    feet = [s + n for s in SIDES for n in ("足ＩＫ", "つま先ＩＫ")]
    if all(src_pose.sk.has(n) and tgt_pose.sk.has(n) for n in feet):
        def low(pose, body):
            w = pose.get(feet)
            return np.min(np.stack([(w[n][0][:, 1] - body.rest(n)[1]) * UNIT_CM for n in feet]), axis=0)
        hs, ht = low(src_pose, src_body), low(tgt_pose, tgt_body)
        js, jt = runs(hs > JUMP_CM, JUMP_MIN), runs(ht > JUMP_CM * scale, JUMP_MIN)
        rows = []
        for a, b in js:
            k = a + int(np.argmax(hs[a:b + 1]))
            row = {"first": a, "last": b, "peak": k, "peak_cm": round(float(hs[k]), 2)}
            match = [(c, d) for c, d in jt if c <= b and d >= a]
            if match:
                c, d = match[0][0], match[-1][1]
                k2 = c + int(np.argmax(ht[c:d + 1]))
                row.update(target=[c, d], target_peak_shift=int(k2 - k), target_peak_cm=round(float(ht[k2]), 2))
            rows.append(row)
        out["jumps"] = {"source": len(js), "matched": int(sum(1 for r in rows if "target" in r)), "rows": rows[:100],
                        "target_only": [[c, d] for c, d in jt if not any(c <= b and d >= a for a, b in js)][:100]}
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
    s_in = arms_in(sp, src_body, spa, touching)                 # the same rule on the source's own body
    arrays = {}
    for tag, d in (("target", t_in), ("source", s_in)):
        for side, row in d.items():
            arrays["arm_in_%s_%s" % (tag, {"左": "left", "右": "right"}[side])] = row.pop("_deep")
    rep["arms_in_body"] = {"target": t_in, "source": s_in}
    rep["plants"] = plants(sp, src_body, tgt_motion, tgt_body, frames)
    rep["chore"] = chore(sp, src_body, tp, tgt_body, source_plants(sp, src_body))
    rep["summary"] = summary(rep)
    rep["_arrays"] = arrays
    return rep


def summary(rep):
    touch = kept = 0
    lost = 0
    n_runs = resting = kept_resting = 0
    for side, parts in rep["contacts"].items():
        for r in parts.values():
            touch += r["source_touch_frames"]
            kept += r["kept_frames"]
            lost += len(r["lost_runs"])
            for run in r.get("runs", ()):
                n_runs += 1
                if run["resting"]:
                    resting += run["frames"]
                    kept_resting += run["kept_frames"]
    out = {"contact_frames": touch, "contacts_kept_share": round(kept / touch, 4) if touch else None, "contacts_lost_runs": lost,
           "contact_runs": n_runs, "contact_frames_resting": resting,
           "contacts_kept_share_resting": round(kept_resting / resting, 4) if resting else None}
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
        out["floor_slide_cm_per_min"] = round(float(sum(sum(r["floor_slide_cm_per_min"].values()) for r in pl.values())), 1)
        out["floor_slide_off_plants_cm_per_min"] = round(float(sum(r["floor_slide_cm_per_min"]["elsewhere"] for r in pl.values())), 1)
        out["pops"] = int(sum(r["pops"]["count"] for r in pl.values()))
        out["pops_not_in_source"] = int(sum(r["pops"]["own"] for r in pl.values()))
    ch = rep.get("chore", {})
    lag0 = [t["lag0_share"] for t in ch.get("timing", {}).values() if t["lag0_share"] is not None]
    out["chore_timing_lag0_share_min"] = round(min(lag0), 4) if lag0 else None
    hd = [h["deg"]["p90"] for h in ch.get("hand_directions", {}).values() if h["deg"]]
    out["chore_hand_direction_p90_deg"] = round(max(hd), 3) if hd else None
    out["chore_hand_direction_over_20deg_frames"] = int(sum(h["frames_over_20deg"] for h in ch.get("hand_directions", {}).values()))
    out["chore_head_turn_p99_deg"] = ch["head_turn_deg"]["p99"] if ch.get("head_turn_deg") else None
    ratios = [s["length_ratio"]["p50"] for s in ch.get("steps", {}).values() if s["length_ratio"]]
    out["chore_step_length_ratio_p50"] = round(float(np.mean(ratios)), 4) if ratios else None
    out["chore_legs_ratio"] = ch.get("legs_ratio")
    if "jumps" in ch:
        out["chore_jumps_source"] = ch["jumps"]["source"]
        out["chore_jumps_matched"] = ch["jumps"]["matched"]
        out["chore_airborne_target_only"] = len(ch["jumps"]["target_only"])
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
