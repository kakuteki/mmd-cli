"""The legs and feet of a PMX model as MMD's IK puts them under a VMD motion, frame by frame (numpy, all frames at once).

    rig = LegRig(model)                       # formats.pmx Model with the usual leg rig (Sour's Rin and most models)
    out = solve(rig, motion, frames)          # out["左"]["ankle"][i] ... for frames[i]

mmd_cli.fk leaves IK out, so the legs it gives follow their own keys only.  This module solves the two IKs of each leg
the way MMD does, after the reverse-engineered solver of saba (benikabocha/saba, MMDIkSolver.cpp, MIT; the stage-3
research kept a copy), which plays MMD motions as MMD shows them:

* the leg IK (足ＩＫ: target 足首, links ひざ then 足, PMX loops and unit angle).  Each loop turns the knee in its
  plane (SolvePlane: about its X axis only, by the angle between the ankle and the goal seen from the knee, the sign
  that brings them closer, in the first loop flipped into the limit when outside, then clamped to the limit; the
  knee's own key is dropped) and then the thigh by the plain CCD step (the turn that points the ankle at the goal,
  at most the unit angle, applied in the thigh's own frame after its key: the thigh's key is where the CCD starts,
  which is how a dance keys the swivel of the knee).  The loop stops at the first loop that does not bring the ankle
  closer, keeping the best one.
* the toe IK (つま先ＩＫ: target つま先, link 足首): the same CCD step on 足首, starting from 足首's key.  It turns the
  toe onto the goal by the smallest turn, so whatever roll the key of 足首 has about the toe's direction survives:
  the roll of the foot comes from 足首's key, its direction from the toe goal (a child of 足ＩＫ, so 足ＩＫ's turn swings
  it round the ankle).
* the bones that follow: 腰キャンセル (腰 x -1) above the thigh, the D bones (足D, ひざD, 足首D: append x 1 of the solved
  bones, the IK turn included, as saba's append does) and 足先EX on 足首D, the toes' bone (the ball of the foot).

Bones and keys are read as mmd_cli.fk reads them (fk.sample: what MMD shows at a frame, the stored quaternion applied as
it is, fk.KEY_ROTATION_SIGNS).  Coordinates are MMD's: X to the model's left, Y up, the model facing -Z.  The order of
the solve is MMD's deform order for this rig: the leg IKs (layer 1), then the toe IKs and the D bones (layer 2, the IK
bones before the D bones by index).  Not handled: other IK chains, physics, external parents, IK switched off by a
show/IK key (LegRig.check_iks tells), keys on the knee (ignored by the plane solve, as saba).
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mmd_cli import fk  # noqa: E402

SIDES = ("左", "右")
EPS_DEG = 1.0e-3                 # saba: a CCD step smaller than this (degrees) is skipped
GAIN = 1.0e-7                   # units: a loop that brings the target closer by less ends the solve.  saba (and MMD)
                                # stop at the first loop that does not bring it closer; MMD's float32 cannot tell a
                                # gain this small at the legs' scale (about 1e-6 of 10 units), float64 here could


# ---- quaternions (x, y, z, w) over the last axis -------------------------------------------------------------------

def qmul(a, b):
    """the Hamilton product a * b (b first, then a)"""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    return np.asarray(q, dtype=np.float64) * np.array([-1.0, -1.0, -1.0, 1.0])


def qrot(q, v):
    """v turned by the unit quaternion q (q v q^-1)"""
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], axis=-1)


def qnormalize(q):
    q = np.asarray(q, dtype=np.float64)
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    return np.where(n > 0.0, q / np.where(n > 0.0, n, 1.0), np.array([0.0, 0.0, 0.0, 1.0]))


def qaxis(axis, angle):
    """the turn by `angle` (radians) about the unit vector `axis`"""
    axis = np.asarray(axis, dtype=np.float64)
    half = 0.5 * np.asarray(angle, dtype=np.float64)
    s = np.sin(half)[..., None]
    return np.concatenate([axis * s, np.cos(half)[..., None]], axis=-1)


def qpow(q, k):
    """q to the power k: the same axis, k times the angle (the short way)"""
    q = np.asarray(q, dtype=np.float64)
    q = np.where(q[..., 3:4] < 0.0, -q, q)
    w = np.clip(q[..., 3], -1.0, 1.0)
    angle = 2.0 * np.arccos(w)
    s = np.sqrt(np.maximum(0.0, 1.0 - w * w))
    axis = np.where(s[..., None] > 1e-12, q[..., :3] / np.where(s > 1e-12, s, 1.0)[..., None], np.array([1.0, 0.0, 0.0]))
    return qaxis(axis, k * angle)


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n > 0.0, n, 1.0)


# ---- the rig ---------------------------------------------------------------------------------------------------------

class Side:
    """the bone indices and the IK settings of one leg"""


class LegRig:
    """the leg rig of `model` (formats.pmx Model): per side the leg IK (足ＩＫ: target 足首, links ひざ, 足), the toe IK
    (つま先ＩＫ: target つま先, link 足首), the D bones and 足先EX when the model has them.  ValueError when the model has
    not this rig (a name or a link is missing or elsewhere)."""

    def __init__(self, model, limits, sides=SIDES):
        """`limits`: IK bone index -> [((lo x, y, z), (hi x, y, z)) in radians, or None, per link] as the PMX file
        holds them (ik_limits of a pmx_edit document; formats.pmx does not keep them).  Use LegRig.load(path) or
        LegRig.loads(data) to read both from a file."""
        self.model = model
        self.limits = limits
        self.bones = model.bones
        self.by_name = {}
        for bone in self.bones:
            self.by_name.setdefault(bone.name, bone.index)
        self.sides = {}
        for s in sides:
            self.sides[s] = self._side(s)
        need = set()
        for side in self.sides.values():
            for index in side.order:
                need.add(index)
        self.order = sorted(need, key=self._depth)

    def _depth(self, index):
        d, seen = 0, set()
        while self.bones[index].parent is not None:
            if index in seen:
                raise ValueError("bone %r is its own ancestor" % self.bones[index].name)
            seen.add(index)
            index = self.bones[index].parent
            d += 1
        return (d, index)

    def _find(self, name):
        if name not in self.by_name:
            raise ValueError("the model has no bone named %r (the leg rig needs it)" % name)
        return self.by_name[name]

    def _ancestors(self, index):
        out = []
        while index is not None:
            out.append(index)
            index = self.bones[index].parent
        return out[::-1]

    def _side(self, s):
        side = Side()
        side.name = s
        side.thigh, side.knee, side.ankle, side.toe = (self._find(s + n) for n in ("足", "ひざ", "足首", "つま先"))
        side.leg_ik, side.toe_ik = self._find(s + "足ＩＫ"), self._find(s + "つま先ＩＫ")
        leg, toe = self.bones[side.leg_ik].ik, self.bones[side.toe_ik].ik
        if not leg or leg["target"] != side.ankle or leg["links"] != [side.knee, side.thigh]:
            raise ValueError("%s足ＩＫ is not the IK of %s足首 on %sひざ and %s足" % (s, s, s, s))
        if not toe or toe["target"] != side.toe or toe["links"] != [side.ankle]:
            raise ValueError("%sつま先ＩＫ is not the IK of %sつま先 on %s足首" % (s, s, s))
        if self.bones[side.knee].parent != side.thigh or self.bones[side.ankle].parent != side.knee:
            raise ValueError("the %s leg is not 足 -> ひざ -> 足首" % s)
        if self.bones[side.toe].parent != side.ankle:
            raise ValueError("%sつま先 is not a child of %s足首" % (s, s))
        side.leg_loops, side.leg_limit = int(leg["loops"]), float(leg["angle"])
        side.toe_loops, side.toe_limit = int(toe["loops"]), float(toe["angle"])
        side.knee_lo, side.knee_hi = self._knee_limits(s, side)
        side.ankle_d = self.by_name.get(s + "足首D")
        side.ex = self.by_name.get(s + "足先EX")
        side.d = [self.by_name.get(s + n) for n in ("足D", "ひざD", "足首D")]
        order = self._ancestors(side.thigh) + [side.knee, side.ankle, side.toe]
        order += [i for i in self._ancestors(side.toe_ik) if i not in order]
        for i in side.d + [side.ex]:
            if i is not None:
                order += [j for j in self._ancestors(i) if j not in order]
        side.order = order
        return side

    def _knee_limits(self, s, side):
        """the knee's X limits (radians) of the PMX link; the thigh must have none.  This module solves a knee limited
        about X alone (MMD's plane solve); anything else is refused rather than solved another way."""
        links = self.limits.get(side.leg_ik)
        if links is None or len(links) != 2:
            raise ValueError("no IK link limits for %s足ＩＫ (read them with ik_limits from the PMX file)" % s)
        knee, thigh = links
        if thigh is not None:
            raise ValueError("%s足 has an IK limit; this module solves a free thigh only" % s)
        if knee is None:
            raise ValueError("%sひざ has no IK limit; this module solves a knee limited about X only" % s)
        lo, hi = knee
        if any(abs(v) > 1e-9 for v in tuple(lo[1:]) + tuple(hi[1:])) or not lo[0] < hi[0]:
            raise ValueError("%sひざ's IK limit is not a turn about X alone: %r..%r" % (s, lo, hi))
        return float(lo[0]), float(hi[0])

    @classmethod
    def loads(cls, data, sides=SIDES):
        from mmd_cli.formats import pmx, pmx_edit
        return cls(pmx.loads(data), ik_limits(pmx_edit.loads(data)), sides)

    @classmethod
    def load(cls, path, sides=SIDES):
        with open(path, "rb") as f:
            return cls.loads(f.read(), sides)

    def check_iks(self, motion):
        """the names of the leg and toe IK bones that a show/IK key of `motion` switches off (they are solved as on)"""
        off = set()
        names = set()
        for side in self.sides.values():
            names.add(self.bones[side.leg_ik].name)
            names.add(self.bones[side.toe_ik].name)
        for k in motion.show_iks:
            for name, enabled in k.iks:
                if name in names and not enabled:
                    off.add(name)
        return sorted(off)


def ik_limits(doc):
    """IK bone index -> [((lo x, y, z), (hi x, y, z)) radians or None, per link] of a pmx_edit Document"""
    import struct
    out = {}
    for i, b in enumerate(doc.bones):
        if b.flags & 0x0020:
            links = []
            for _, raw in b.ik_links:
                links.append(None if raw is None else (struct.unpack("<3f", raw[:12]), struct.unpack("<3f", raw[12:])))
            out[i] = links
    return out


# ---- the keys ------------------------------------------------------------------------------------------------------

def sample(rig, motion, frames):
    """bone index -> (positions [F, 3], rotations [F, 4] as applied) at `frames`, for the bones of the rig and their
    append parents (a bone without keys rests)"""
    tracks = fk.tracks_of(motion)
    frames = list(frames)
    need = set(rig.order)
    for index in list(need):
        a = rig.bones[index].append
        if a is not None and a.get("parent") is not None:
            need.add(a["parent"])
    out = {}
    for index in need:
        name = rig.bones[index].name
        keys = tracks.get(name) or tracks.get(fk.vmd_name(name))
        n = len(frames)
        if not keys:
            out[index] = (np.zeros((n, 3)), np.tile([0.0, 0.0, 0.0, 1.0], (n, 1)))
            continue
        kf = [k.frame for k in keys]
        pos = np.empty((n, 3))
        rot = np.empty((n, 4))
        for i, f in enumerate(frames):
            p, q = fk.sample(keys, f, kf)
            pos[i] = p
            rot[i] = fk.applied(q)
        out[index] = (pos, rot)
    return out


# ---- the solve -----------------------------------------------------------------------------------------------------

class _State:
    """world positions and rotations of the rig's bones, filled in order; locals hold the (IK-solved) local turns"""

    def __init__(self, rig, keys):
        self.rig = rig
        self.keys = keys
        self.local_rot = {}
        self.local_pos = {}
        self.pos = {}
        self.rot = {}

    def local(self, index):
        """(translation, rotation) of the bone's own motion: its key, the IK turn when solved, the append"""
        if index in self.local_rot:
            return self.local_pos[index], self.local_rot[index]
        bone = self.rig.bones[index]
        pos, rot = self.keys[index]
        a = bone.append
        if a is not None and a.get("parent") is not None and (bone.flags.get("append_rotate") or bone.flags.get("append_translate")):
            ppos, prot = self.local(a["parent"])
            ratio = float(a["ratio"])
            if bone.flags.get("append_rotate"):
                rot = qmul(rot, qpow(prot, ratio))
            if bone.flags.get("append_translate"):
                pos = pos + ratio * ppos
        self.local_pos[index], self.local_rot[index] = pos, rot
        return pos, rot

    def world(self, index):
        if index in self.pos:
            return self.pos[index], self.rot[index]
        bone = self.rig.bones[index]
        t, r = self.local(index)
        rest = np.array(bone.position, dtype=np.float64)
        if bone.parent is None:
            self.pos[index], self.rot[index] = rest + t, r
        else:
            ppos, prot = self.world(bone.parent)
            offset = rest - np.array(self.rig.bones[bone.parent].position, dtype=np.float64) + t
            self.pos[index], self.rot[index] = ppos + qrot(prot, offset), qmul(prot, r)
        return self.pos[index], self.rot[index]

    def forget(self, indices):
        for i in indices:
            self.pos.pop(i, None)
            self.rot.pop(i, None)


def _offset(rig, child):
    bone = rig.bones[child]
    return np.array(bone.position, dtype=np.float64) - np.array(rig.bones[bone.parent].position, dtype=np.float64)


def _ccd_step(link_pos, link_rot, local, target_pos, goal, limit, active):
    """saba's plain CCD step for one link, on the frames `active`: the turn in the link's own frame that points the
    target at the goal (at most `limit`), applied after the link's local turn.  Returns the new local turns."""
    inv = qconj(link_rot)
    vik = unit(qrot(inv, goal - link_pos))
    vt = unit(qrot(inv, target_pos - link_pos))
    dot = np.clip(np.sum(vik * vt, axis=-1), -1.0, 1.0)
    angle = np.arccos(dot)
    axis = np.cross(vt, vik)
    norm = np.linalg.norm(axis, axis=-1)
    move = active & (np.degrees(angle) >= EPS_DEG) & (norm > 1e-12)
    angle = np.minimum(angle, limit)
    rot = qaxis(axis / np.where(norm > 1e-12, norm, 1.0)[:, None], np.where(move, angle, 0.0))
    return np.where(move[:, None], qmul(local, rot), local)


def _solve_leg(state, side, F):
    rig = state.rig
    o_knee, o_ankle = _offset(rig, side.knee), _offset(rig, side.ankle)
    hip_pos, _ = state.world(side.thigh)                 # the hip joint does not move in the solve
    parent_rot = state.world(rig.bones[side.thigh].parent)[1]
    goal = state.world(side.leg_ik)[0]
    t_knee, _ = state.local(side.knee)
    t_ankle, _ = state.local(side.ankle)
    _, thigh = state.local(side.thigh)
    _, knee = state.local(side.knee)                     # before the first plane step the knee has its key
    thigh, knee = thigh.copy(), knee.copy()
    plane = np.zeros(F)
    best_thigh, best_knee, best_plane = thigh.copy(), knee.copy(), plane.copy()
    best = np.full(F, np.inf)
    active = np.ones(F, dtype=bool)
    lo, hi = side.knee_lo, side.knee_hi
    for it in range(side.leg_loops):
        idx = np.flatnonzero(active)            # the frames still improving (each is solved on its own)
        if len(idx) == 0:
            break
        n = len(idx)
        xaxis = np.broadcast_to(np.array([1.0, 0.0, 0.0]), (n, 3))
        P, H, G = parent_rot[idx], hip_pos[idx], goal[idx]
        TK, TA = o_knee + t_knee[idx], o_ankle + t_ankle[idx]
        th, kn, pl = thigh[idx], knee[idx], plane[idx]

        def chain(thigh_local, knee_local):
            rt = qmul(P, thigh_local)
            kpos = H + qrot(rt, TK)
            rk = qmul(rt, knee_local)
            return rt, kpos, rk, kpos + qrot(rk, TA)

        # the knee: in its plane (about its own X)
        rt, kpos, rk, apos = chain(th, kn)
        inv = qconj(rk)
        vik = unit(qrot(inv, G - kpos))
        vt = unit(qrot(inv, apos - kpos))
        angle = np.minimum(np.arccos(np.clip(np.sum(vik * vt, axis=-1), -1.0, 1.0)), side.leg_limit)
        d1 = np.sum(qrot(qaxis(xaxis, angle), vt) * vik, axis=-1)
        d2 = np.sum(qrot(qaxis(xaxis, -angle), vt) * vik, axis=-1)
        new = pl + np.where(d1 > d2, angle, -angle)
        if it == 0:
            outside = (new < lo) | (new > hi)
            mirrored_in = outside & (-new > lo) & (-new < hi)
            half = 0.5 * (lo + hi)
            further = outside & ~mirrored_in & (np.abs(half - new) > np.abs(half + new))
            new = np.where(mirrored_in | further, -new, new)
        pl = np.clip(new, lo, hi)
        kn = qaxis(xaxis, pl)
        # the thigh: the plain CCD step
        rt, kpos, rk, apos = chain(th, kn)
        th = _ccd_step(H, rt, th, apos, G, side.leg_limit, np.ones(n, dtype=bool))
        rt, kpos, rk, apos = chain(th, kn)
        dist = np.linalg.norm(apos - G, axis=-1)
        better = dist < best[idx] - GAIN
        bi, wi = idx[better], idx[~better]
        best[bi] = dist[better]
        thigh[bi], knee[bi], plane[bi] = th[better], kn[better], pl[better]
        best_thigh[bi], best_knee[bi], best_plane[bi] = th[better], kn[better], pl[better]
        thigh[wi], knee[wi], plane[wi] = best_thigh[wi], best_knee[wi], best_plane[wi]
        active[wi] = False
    state.local_rot[side.thigh] = thigh
    state.local_rot[side.knee] = knee
    state.forget([side.thigh, side.knee, side.ankle, side.toe])
    return plane, best


def _solve_toe(state, side, F):
    rig = state.rig
    o_toe = _offset(rig, side.toe)
    t_toe, _ = state.local(side.toe)
    apos, _ = state.world(side.ankle)
    parent_rot = state.world(side.knee)[1]
    goal = state.world(side.toe_ik)[0]
    _, foot = state.local(side.ankle)
    best_foot = foot.copy()
    best = np.full(F, np.inf)
    active = np.ones(F, dtype=bool)
    for _ in range(side.toe_loops):
        if not active.any():
            break
        rf = qmul(parent_rot, foot)
        tpos = apos + qrot(rf, o_toe + t_toe)
        foot = _ccd_step(apos, rf, foot, tpos, goal, side.toe_limit, active)
        rf = qmul(parent_rot, foot)
        tpos = apos + qrot(rf, o_toe + t_toe)
        dist = np.linalg.norm(tpos - goal, axis=-1)
        better = active & (dist < best - GAIN)
        worse = active & ~better
        best = np.where(better, dist, best)
        best_foot = np.where(better[:, None], foot, best_foot)
        foot = np.where(worse[:, None], best_foot, foot)
        active &= ~worse
    state.local_rot[side.ankle] = foot
    state.forget([side.ankle, side.toe])
    return best


def solve(rig, motion, frames, keys=None):
    """side -> dict of arrays over `frames` (F of them): world positions hip, knee, ankle, toe (the つま先 bone), ex
    (足先EX, or the ankle when the model has none), goal_ankle (足ＩＫ), goal_toe (つま先ＩＫ); world rotations
    q_thigh, q_shin, q_foot (足首), q_ex (足先EX), q_ik (足ＩＫ); local turns local_thigh, local_knee, local_foot;
    knee_angle (the knee's X turn, radians, negative bends) and reach (the ankle's distance from its goal) and
    toe_reach.  `keys` (bone index -> (positions [F, 3], rotations [F, 4] as applied), as sample() gives them) solves
    those values instead of the motion's (a layer trying keys out without writing a VMD)."""
    frames = list(frames)
    F = len(frames)
    if keys is None:
        keys = sample(rig, motion, frames)
    state = _State(rig, keys)
    for index in rig.order:                 # FK of everything first (IK links with their keys)
        state.world(index)
    out = {}
    knees = {}
    for s, side in rig.sides.items():       # layer 1: the leg IKs
        knees[s] = _solve_leg(state, side, F)
    toes = {}
    for s, side in rig.sides.items():       # layer 2: the toe IKs, then the bones that follow
        for i in (side.ankle, side.toe):
            state.world(i)
        toes[s] = _solve_toe(state, side, F)
    for s, side in rig.sides.items():
        for i in side.d + [side.ex]:
            if i is not None:
                state.local_rot.pop(i, None)            # their appends read the solved turns
                state.local_pos.pop(i, None)
                state.forget([i])
        for i in side.d + [side.ex]:
            if i is not None:
                state.forget([j for j in rig.order if _below(rig, j, i)])
        hip, q_thigh = state.world(side.thigh)
        knee, q_shin = state.world(side.knee)
        ankle, q_foot = state.world(side.ankle)
        toe, _ = state.world(side.toe)
        if side.ex is not None:
            ex, q_ex = state.world(side.ex)
        else:
            ex, q_ex = ankle, q_foot
        goal_ankle, q_ik = state.world(side.leg_ik)
        goal_toe, _ = state.world(side.toe_ik)
        out[s] = {
            "hip": hip, "knee": knee, "ankle": ankle, "toe": toe, "ex": ex, "goal_ankle": goal_ankle,
            "goal_toe": goal_toe, "q_thigh": q_thigh, "q_shin": q_shin, "q_foot": q_foot, "q_ex": q_ex, "q_ik": q_ik,
            "local_thigh": state.local_rot[side.thigh], "local_knee": state.local_rot[side.knee],
            "local_foot": state.local_rot[side.ankle], "knee_angle": knees[s][0],
            "reach": np.linalg.norm(ankle - goal_ankle, axis=-1), "toe_reach": np.linalg.norm(toe - goal_toe, axis=-1),
        }
    return out


def _below(rig, index, ancestor):
    """True when `ancestor` is `index` or one of its ancestors"""
    while index is not None:
        if index == ancestor:
            return True
        index = rig.bones[index].parent
    return False
