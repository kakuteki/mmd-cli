"""Pose the whole skeleton of a PMX model as MMD poses it (keys, appends, IK, in MMD's deform order) and skin the model's
vertices (BDEF1, BDEF2, BDEF4, SDEF) as MMD skins them, one frame at a time, without MMD.

    m = Model.load("model.pmx")                       # Model.loads(data, ik_loops={"左足ＩＫ": 400}) tries other settings
    keys = keys_at(m, fk.tracks_of(motion), frame)    # bone index -> (translation, rotation as applied)
    pose = solve(m, keys)                             # pose.pos [B, 3], pose.rot [B, 4] (x, y, z, w) in the world;
                                                      # pose.local_rot [B, 4]; pose.ik {IK bone: reach, loops run}
    points = skin(m, pose)                            # [V, 3]       normals(m, pose) [V, 3]

The pose follows saba (benikabocha/saba, PMXModel::UpdateNodeAnimation and MMDIkSolver, MIT), the MMD player whose IK
tools/leg_ik.py copies and checked on MMD's renders of Sour's Rin:

1. every bone's local transform from its key: T(rest offset + key translation + appended translation)
   R(IK turn * key rotation * appended rotation), the world transform its parent's times it;
2. in the deform order (the PMX layer, then the index), a bone with an append (付与) takes its append parent's rotation
   (that bone's key, with its IK turn when it is an IK link) to the power of the ratio (the same axis, ratio times the
   angle, the short way) and the parent's key translation times the ratio; a bone with an IK solves its chain: CCD over
   the links in the file's order, a link limited to one axis turned in its plane (SolvePlane: by the angle between the
   target and the goal seen from it, the sign that brings them closer, mirrored into the limit in the first loop, then
   clamped; its key is dropped), a free link by the plain step (the turn that points the target at the goal, at most
   the unit angle, after its key), each loop kept only when it brings the target closer (by more than GAIN) and the
   solve stopped at the first that does not.  Each change moves the bone's descendants.

Appends of appends: a bone whose append parent has an append of its own takes that parent's key and appended turn
(mmd_cli.fk's rule; saba takes the parent's appended turn alone).  Of Sour's Rin only 目補助 is such a bone.  A link
limited on more than one axis (Euler limits) is refused: saba's decomposition for it is not checked against MMD and
Sour's Rin has none.

Skinning (MMD's coordinates, the stored key turns applied as plain rotations: mmd_cli.fk's convention; R_k, pos_k,
rest_k the world rotation, world place and rest place of the vertex's k-th bone):
  BDEF1/2/4, QDEF:  p' = sum_k w_k (pos_k + R_k (p - rest_k))
  SDEF:             q = slerp(rot_0, rot_1, w_1) (the short way); r = w_0 R0 + w_1 R1; c_k = (C + (C + R_k - r)) / 2;
                    p' = R(q) (p - C) + w_0 (pos_0 + R_0 (c_0 - rest_0)) + w_1 (pos_1 + R_1 (c_1 - rest_1))
                    (saba's PMXModel: C, R0, R1 the vertex's SDEF points)

Left out: physics (a bone driven by a physics rigid body keeps the pose its parent and its keys give it; Model.physics
names those bones and the bones below them), morphs, external parents, IK switched off by a show/IK key, and the
deform-after-physics pass (bones with that flag are posed in the same pass).
"""
import importlib.util
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx_edit  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_rig_skin_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IK = _tool("leg_ik")
qmul, qconj, qrot, qaxis, qpow, unit = _IK.qmul, _IK.qconj, _IK.qrot, _IK.qaxis, _IK.qpow, _IK.unit

EPS_DEG = _IK.EPS_DEG           # a CCD step smaller than this (degrees) is skipped (saba)
GAIN = _IK.GAIN                 # a loop that brings the target closer by less ends the solve (tools/leg_ik.py)
F_TAIL_BONE, F_IK, F_LOCAL_APPEND = 0x0001, 0x0020, 0x0080
F_APPEND_ROTATE, F_APPEND_TRANSLATE, F_AFTER_PHYSICS = 0x0100, 0x0200, 0x1000
KIND_CODE = {"BDEF1": 0, "BDEF2": 1, "BDEF4": 2, "SDEF": 3, "QDEF": 4}
IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])
XYZ = np.eye(3)


class Bone:
    """one bone: name, parent (-1 none), position, layer, flags, append (parent, ratio) or None, ik or None
    ({"target", "loops", "angle", "links": [(link, lo xyz, hi xyz) with None limits for a free link]})"""

    def __init__(self, rec):
        self.name = rec.name
        self.name_en = rec.name_en
        self.parent = rec.parent
        self.position = tuple(rec.position)
        self.layer = rec.layer
        self.flags = rec.flags
        self.append = (rec.append_parent, rec.append_ratio) if rec.flags & (F_APPEND_ROTATE | F_APPEND_TRANSLATE) and rec.append_parent >= 0 else None
        self.append_rotate = bool(rec.flags & F_APPEND_ROTATE)
        self.append_translate = bool(rec.flags & F_APPEND_TRANSLATE)
        self.local_append = bool(rec.flags & F_LOCAL_APPEND)
        self.ik = None
        if rec.flags & F_IK and rec.ik_target >= 0:
            links = []
            for link, raw in rec.ik_links:
                if raw is None:
                    links.append((link, None, None))
                else:
                    v = struct.unpack("<6f", raw)
                    links.append((link, np.array(v[:3]), np.array(v[3:])))
            self.ik = {"target": rec.ik_target, "loops": rec.ik_loops, "angle": rec.ik_angle, "links": links}


def _plane_axis(lo, hi):
    """saba's choice of the plane solve: the axis (0, 1, 2) a limited link turns about alone, or None"""
    if (lo[0] != 0 or hi[0] != 0) and (lo[1] == 0 or hi[1] == 0) and (lo[2] == 0 or hi[2] == 0):
        return 0
    if (lo[1] != 0 or hi[1] != 0) and (lo[0] == 0 or hi[0] == 0) and (lo[2] == 0 or hi[2] == 0):
        return 1
    if (lo[2] != 0 or hi[2] != 0) and (lo[0] == 0 or hi[0] == 0) and (lo[1] == 0 or hi[1] == 0):
        return 2
    return None


class Model:
    """the bones, IKs and vertices of a PMX (a formats.pmx_edit Document).  ik_loops / ik_angles ({IK bone name: loops
    or unit angle in radians}) replace the file's settings, to try other ones without writing a file."""

    def __init__(self, doc, ik_loops=None, ik_angles=None):
        self.doc = doc
        self.bones = [Bone(b) for b in doc.bones]
        B = len(self.bones)
        self.by_name = {}
        for i, b in enumerate(self.bones):
            self.by_name.setdefault(b.name, i)
        for table in (ik_loops or {}), (ik_angles or {}):
            for name in table:
                if name not in self.by_name or self.bones[self.by_name[name]].ik is None:
                    raise ValueError("%r is not an IK bone of the model" % name)
        for name, loops in (ik_loops or {}).items():
            self.bones[self.by_name[name]].ik["loops"] = int(loops)
        for name, angle in (ik_angles or {}).items():
            self.bones[self.by_name[name]].ik["angle"] = float(angle)
        self.rest = np.array([b.position for b in self.bones], dtype=np.float64).reshape(B, 3)
        self.offset = self.rest.copy()
        self.children = [[] for _ in range(B)]
        for i, b in enumerate(self.bones):
            if b.parent >= 0:
                if not b.parent < B:
                    raise ValueError("bone %r has parent %d, the model has %d bones" % (b.name, b.parent, B))
                self.offset[i] = self.rest[i] - self.rest[b.parent]
                self.children[b.parent].append(i)
        self._check_tree()
        self.order = sorted(range(B), key=lambda i: (bool(self.bones[i].flags & F_AFTER_PHYSICS), self.bones[i].layer, i))
        self.links = set()
        for b in self.bones:
            if b.ik is not None:
                for link, lo, hi in b.ik["links"]:
                    if lo is not None and _plane_axis(lo, hi) is None:
                        raise ValueError("IK %s limits link %r on more than one axis (Euler limits are not handled)"
                                         % (b.name, self.bones[link].name))
                    self.links.add(link)
        driven = {rb.bone for rb in doc.rigid_bodies if rb.bone >= 0 and rb.rest[60] != 0}
        self.physics = set()
        stack = list(driven)
        while stack:
            i = stack.pop()
            if i in self.physics:
                continue
            self.physics.add(i)
            stack.extend(self.children[i])
        self._vertices(doc)

    def _check_tree(self):
        seen_ok = set()
        for i in range(len(self.bones)):
            path, j = set(), i
            while j >= 0 and j not in seen_ok:
                if j in path:
                    raise ValueError("bone %r is its own ancestor" % self.bones[i].name)
                path.add(j)
                j = self.bones[j].parent
            seen_ok |= path

    def _vertices(self, doc):
        V = len(doc.vertices)
        self.points = np.empty((V, 3))
        self.normals = np.empty((V, 3))
        self.kinds = np.empty(V, dtype=np.int8)
        self.idx = np.zeros((V, 4), dtype=np.int64)
        self.w = np.zeros((V, 4))
        self.sdef = np.zeros((V, 3, 3))        # C, R0, R1
        for k, v in enumerate(doc.vertices):
            self.points[k] = struct.unpack_from("<3f", v.head, 0)
            self.normals[k] = struct.unpack_from("<3f", v.head, 12)
            self.kinds[k] = KIND_CODE[v.kind]
            pairs = v.pairs()
            for j, (b, wt) in enumerate(pairs[:4]):
                self.idx[k, j] = max(b, 0)
                self.w[k, j] = wt if b >= 0 else 0.0
            if v.kind == "SDEF":
                c = struct.unpack("<9f", v.sdef)
                self.sdef[k] = np.array(c).reshape(3, 3)
        if V and int(self.idx.max(initial=0)) >= len(self.bones):
            raise ValueError("a vertex names bone %d, the model has %d" % (int(self.idx.max()), len(self.bones)))
        g = pmx_edit.geometry(doc)
        self.faces = np.array(g.faces, dtype=np.int64).reshape(-1, 3)
        self.materials = []
        start = 0
        for m in g.materials:
            self.materials.append((m.name, start // 3, m.faces // 3))
            start += m.faces

    @classmethod
    def loads(cls, data, **kw):
        return cls(pmx_edit.loads(data), **kw)

    @classmethod
    def load(cls, path, **kw):
        with open(path, "rb") as f:
            return cls.loads(f.read(), **kw)

    def index(self, name):
        if name not in self.by_name:
            raise KeyError(name)
        return self.by_name[name]


def keys_at(model, tracks, frame):
    """bone index -> (translation [3], rotation [4] as applied) at `frame` for the bones `tracks` (fk.tracks_of) keys,
    names matched as a VMD names them (mmd_cli.fk.vmd_name)"""
    out = {}
    for i, b in enumerate(model.bones):
        keys = tracks.get(b.name) or tracks.get(fk.vmd_name(b.name))
        if keys:
            p, q = fk.sample(keys, frame)
            out[i] = (np.array(p, dtype=np.float64), np.array(fk.applied(q), dtype=np.float64))
    return out


class Pose:
    def __init__(self, pos, rot, local_rot, ik):
        self.pos = pos
        self.rot = rot
        self.local_rot = local_rot
        self.ik = ik


class _State:
    def __init__(self, m, keys):
        B = len(m.bones)
        self.m = m
        self.anim_t = np.zeros((B, 3))
        self.anim_r = np.tile(IDENTITY, (B, 1))
        for i, (t, r) in keys.items():
            self.anim_t[i] = t
            self.anim_r[i] = r
        self.ik_r = np.tile(IDENTITY, (B, 1))
        self.app_r = np.tile(IDENTITY, (B, 1))
        self.app_t = np.zeros((B, 3))
        self.gpos = np.zeros((B, 3))
        self.grot = np.tile(IDENTITY, (B, 1))

    def local_rot(self, i):
        return qmul(qmul(self.ik_r[i], self.anim_r[i]), self.app_r[i])

    def _one(self, i):
        b = self.m.bones[i]
        t = self.m.offset[i] + self.anim_t[i] + self.app_t[i]
        r = self.local_rot(i)
        if b.parent < 0:
            self.gpos[i], self.grot[i] = t, r
        else:
            p = b.parent
            self.gpos[i] = self.gpos[p] + qrot(self.grot[p], t)
            self.grot[i] = qmul(self.grot[p], r)

    def subtree(self, i):
        stack = [i]
        while stack:
            j = stack.pop()
            self._one(j)
            stack.extend(reversed(self.m.children[j]))

    def all(self):
        for i, b in enumerate(self.m.bones):
            if b.parent < 0:
                self.subtree(i)

    def append(self, i):
        b = self.m.bones[i]
        a, ratio = b.append
        parent = self.m.bones[a]
        if b.append_rotate:
            if b.local_append or parent.append is None or not parent.append_rotate:
                ar = self.anim_r[a]
            else:
                ar = qmul(self.anim_r[a], self.app_r[a])
            if a in self.m.links:
                ar = qmul(self.ik_r[a], ar)
            self.app_r[i] = qpow(ar, ratio)
        if b.append_translate:
            if b.local_append or parent.append is None or not parent.append_translate:
                at = self.anim_t[a]
            else:
                at = self.anim_t[a] + self.app_t[a]
            self.app_t[i] = at * ratio

    def ik(self, i):
        """solve the IK of bone i (saba's MMDIkSolver::Solve); returns (the target's distance from the goal, loops run)"""
        ik = self.m.bones[i].ik
        target, links = ik["target"], ik["links"]
        limit = float(ik["angle"])
        plane = {}
        prev = {}
        for link, lo, hi in links:
            self.ik_r[link] = IDENTITY
            plane[link] = 0.0
            prev[link] = np.zeros(3)
            self.subtree(link)
        best = math.inf
        saved = {link: self.ik_r[link].copy() for link, _, _ in links}
        run = 0
        for it in range(int(ik["loops"])):
            run = it + 1
            for link, lo, hi in links:
                if link == target:
                    continue
                if lo is not None:
                    self._plane(it, i, target, link, lo, hi, _plane_axis(lo, hi), limit, plane)
                else:
                    self._ccd(i, target, link, limit)
            dist = float(np.linalg.norm(self.gpos[target] - self.gpos[i]))
            if dist < best - GAIN:
                best = dist
                saved = {link: self.ik_r[link].copy() for link, _, _ in links}
            else:
                for link, _, _ in links:
                    self.ik_r[link] = saved[link]
                    self.subtree(link)
                break
        return float(np.linalg.norm(self.gpos[target] - self.gpos[i])), run

    def _vectors(self, goal, target, link):
        inv = qconj(self.grot[link])
        vik = qrot(inv, self.gpos[goal] - self.gpos[link])
        vt = qrot(inv, self.gpos[target] - self.gpos[link])
        return unit(vik), unit(vt), np.linalg.norm(vik) > 1e-12 and np.linalg.norm(vt) > 1e-12

    def _ccd(self, goal, target, link, limit):
        vik, vt, ok = self._vectors(goal, target, link)
        if not ok:
            return
        angle = math.acos(max(-1.0, min(1.0, float(np.dot(vt, vik)))))
        if math.degrees(angle) < EPS_DEG:
            return
        axis = np.cross(vt, vik)
        n = float(np.linalg.norm(axis))
        if n <= 1e-12:
            return
        rot = qaxis(axis / n, min(angle, limit))
        chain = qmul(qmul(self.ik_r[link], self.anim_r[link]), rot)
        self.ik_r[link] = qmul(chain, qconj(self.anim_r[link]))
        self.subtree(link)

    def _plane(self, it, goal, target, link, lo, hi, axis, limit, plane):
        vik, vt, ok = self._vectors(goal, target, link)
        angle = math.acos(max(-1.0, min(1.0, float(np.dot(vt, vik))))) if ok else 0.0
        angle = min(angle, limit)
        d1 = float(np.dot(qrot(qaxis(XYZ[axis], angle), vt), vik))
        d2 = float(np.dot(qrot(qaxis(XYZ[axis], -angle), vt), vik))
        new = plane[link] + (angle if d1 > d2 else -angle)
        a_lo, a_hi = float(lo[axis]), float(hi[axis])
        if it == 0 and (new < a_lo or new > a_hi):
            if a_lo < -new < a_hi:
                new = -new
            else:
                half = 0.5 * (a_lo + a_hi)
                if abs(half - new) > abs(half + new):
                    new = -new
        new = min(max(new, a_lo), a_hi)
        plane[link] = new
        self.ik_r[link] = qmul(qaxis(XYZ[axis], new), qconj(self.anim_r[link]))
        self.subtree(link)


def solve(model, keys):
    """the pose of `model` under `keys` (keys_at): world places and rotations of every bone, MMD's order of the work"""
    st = _State(model, keys)
    st.all()
    ik = {}
    for i in model.order:
        b = model.bones[i]
        if b.append is not None and (b.append_rotate or b.append_translate):
            st.append(i)
            st.subtree(i)
        if b.ik is not None:
            reach, loops = st.ik(i)
            st.subtree(i)
            ik[i] = {"reach": reach, "loops": loops}
    st.all()
    for i in ik:
        ik[i]["reach"] = float(np.linalg.norm(st.gpos[model.bones[i].ik["target"]] - st.gpos[i]))
    local = np.array([st.local_rot(i) for i in range(len(model.bones))]).reshape(-1, 4)
    return Pose(st.gpos.copy(), st.grot.copy(), local, ik)


# ---- skinning --------------------------------------------------------------------------------------------------------

def rotation_matrices(q):
    """[..., 3, 3] of unit quaternions q [..., 4] (x, y, z, w)"""
    q = np.asarray(q, dtype=np.float64)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)


def slerp(a, b, t):
    """the short way from unit quaternions a [N, 4] to b [N, 4] by t [N]"""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64).copy()
    t = np.asarray(t, dtype=np.float64)
    dot = np.sum(a * b, axis=-1)
    b[dot < 0] *= -1.0
    dot = np.abs(dot)
    near = dot > 0.9995
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    s = np.where(near, 1.0, np.sin(theta))
    wa = np.where(near, 1.0 - t, np.sin((1.0 - t) * theta) / s)
    wb = np.where(near, t, np.sin(t * theta) / s)
    out = wa[..., None] * a + wb[..., None] * b
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


def skin(model, pose, points=None):
    """the vertices [V, 3] of `model` as MMD skins them on `pose` (points: the rest places, default the model's)"""
    p = model.points if points is None else np.asarray(points, dtype=np.float64)
    R = rotation_matrices(pose.rot)
    idx, w = model.idx, model.w
    rel = p[:, None, :] - model.rest[idx]                              # [V, 4, 3]
    moved = pose.pos[idx] + np.einsum("vkij,vkj->vki", R[idx], rel)    # each bone's carry
    out = np.sum(w[:, :, None] * moved, axis=1)
    s = np.flatnonzero(model.kinds == KIND_CODE["SDEF"])
    if len(s):
        b0, b1 = idx[s, 0], idx[s, 1]
        w0 = w[s, 0]
        w1 = 1.0 - w0
        c, r0, r1 = model.sdef[s, 0], model.sdef[s, 1], model.sdef[s, 2]
        rw = r0 * w0[:, None] + r1 * w1[:, None]
        cr0 = (c + (c + r0 - rw)) * 0.5
        cr1 = (c + (c + r1 - rw)) * 0.5
        q = slerp(pose.rot[b0], pose.rot[b1], w1)
        Rq = rotation_matrices(q)
        m0 = pose.pos[b0] + np.einsum("nij,nj->ni", R[b0], cr0 - model.rest[b0])
        m1 = pose.pos[b1] + np.einsum("nij,nj->ni", R[b1], cr1 - model.rest[b1])
        out[s] = np.einsum("nij,nj->ni", Rq, p[s] - c) + m0 * w0[:, None] + m1 * w1[:, None]
    return out


def normals(model, pose):
    """the vertex normals [V, 3] on `pose` (BDEF: the weighted sum of the bones' rotations; SDEF: the blended turn)"""
    R = rotation_matrices(pose.rot)
    idx, w = model.idx, model.w
    n = np.sum(w[:, :, None] * np.einsum("vkij,vj->vki", R[idx], model.normals), axis=1)
    s = np.flatnonzero(model.kinds == KIND_CODE["SDEF"])
    if len(s):
        q = slerp(pose.rot[idx[s, 0]], pose.rot[idx[s, 1]], 1.0 - w[s, 0])
        n[s] = np.einsum("nij,nj->ni", rotation_matrices(q), model.normals[s])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
