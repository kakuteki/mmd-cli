"""Move the traced dance from the body it was traced on (the source) onto another body (the target, Sour's Rin), keeping
what the source body did: the arms point the same way although the two bodies rest them at other angles, the centre and
the feet move by the legs' ratio and the legs keep their spread, a foot on the floor stays put and on the floor, a hand
that touches the head, the trunk, the hips or the other hand still touches it, and the arms stay out of the body.

    python tools/retarget.py run DANCE.vmd SOURCE TARGET.pmx OUT.vmd [--report r.json] [--arrays a.npz]
                                 [--no-feet] [--no-hands] [--no-clear] [--stance legs|offsets]
    python tools/retarget.py fit DANCE.vmd --candidates A.pmx B.pmd ... --out fit.json [--target T.pmx]

SOURCE is a model (.pmx / .pmd) or a body (.json: {"model": path, "add": [bones to add], "rest": {bone: [x, y, z]},
"foot": {...}}; see Body.from_spec).  The dance is a VMD made for the source; the output is the same bones' keys for the
target, on the same frames (keys are added only where a correction needs them), the morphs and the rest of the file as
they were.  Bones the target lacks are passed through unchanged and listed in the report.

The mapping (both bodies stand in MMD's rest pose: every bone's frame lines up with the world; X to the model's left, Y
up, the model faces -Z; a key turns its bone in its parent's frame, mmd_cli/fk.py):

* rotations: a bone b whose rest direction (CORRECTED: the upper arm, its twist, the forearm, the hand's twist, the hand)
  differs between the bodies gets the turn C_b that takes the target's rest direction onto the source's; its key becomes
  L_T = C_p^-1 L_S C_b (p: the nearest corrected ancestor).  Then W_T(b) = W_S(b) C_b on every frame: the bone points
  where the source's points, a twist turns about the target's own arm (it is the source's twist conjugated), and the
  bones under it (the fingers) keep the source's world turn.  Every other bone keeps its key (the trunk, the head, the
  shoulders, the legs, the fingers: both bodies stand upright facing -Z at rest, and their bone directions there are a
  modeller's choice, not a pose).  Turning by a constant on each side keeps MMD's interpolation of the keys (slerp is
  kept by q -> A q B).
* translations: every key's translation is scaled by s = the target's hip height over its ankle over the source's
  (both at rest, the mean of the two sides).  The foot IK is moved once more sideways by k = s (ankle_S - hip_S)_x -
  (ankle_T - hip_T)_x (per side, --stance legs, the default): a leg at rest offsets leans out from its hip as the
  source's does (the stance width keeps its ratio to the legs); --stance offsets leaves the target's own rest stance.
"""
import argparse
import importlib.util
import json
import math
import os
import struct
import sys
import time
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, pmx_edit, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_retarget_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LI = _tool("leg_ik")

SIDES = ("左", "右")
FPS = 30.0
UNIT_CM = 8.0                   # one unit of Sour's Rin is 8 cm (the analysis pack)
# the bones whose rest direction is mapped (side prefix added): bone -> (from, to) of the direction
CORRECTED = {"腕": ("腕", "ひじ"), "腕捩": ("腕", "ひじ"), "ひじ": ("ひじ", "手首"), "手捩": ("ひじ", "手首"),
             "手首": ("手首", "中指１")}
IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


# ---- quaternions (x, y, z, w) over the last axis ----------------------------------------------------------------------

def qmul(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    out = np.array(q, dtype=np.float64, copy=True)
    out[..., :3] *= -1.0
    return out


def qrot(q, v):
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], axis=-1)


def qnorm(q):
    q = np.asarray(q, dtype=np.float64)
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-300)


def qaxis(axis, angle):
    """the turn by `angle` (radians) about the unit vector `axis`"""
    axis = np.asarray(axis, dtype=np.float64)
    half = 0.5 * np.asarray(angle, dtype=np.float64)
    return np.concatenate([axis * np.sin(half)[..., None], np.cos(half)[..., None]], axis=-1)


def qbetween(a, b):
    """the smallest turn that takes the direction a onto b (unit vectors, [..., 3])"""
    a = unit(a)
    b = unit(b)
    c = np.cross(a, b)
    d = np.sum(a * b, axis=-1)
    q = np.concatenate([c, (1.0 + d)[..., None]], axis=-1)
    # opposite directions: any axis at right angles to a
    flat = (1.0 + d) < 1e-12
    if np.any(flat):
        other = np.where(np.abs(a[..., 0:1]) < 0.9, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))
        ax = unit(np.cross(a, other))
        q = np.where(flat[..., None], np.concatenate([ax, np.zeros(ax.shape[:-1] + (1,))], axis=-1), q)
    return qnorm(q)


def qangle(q):
    """the angle (radians) of the turn q"""
    q = np.asarray(q, dtype=np.float64)
    return 2.0 * np.arctan2(np.linalg.norm(q[..., :3], axis=-1), np.abs(q[..., 3]))


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)


# ---- one bone's keys -----------------------------------------------------------------------------------------------------

CHANNELS = ("x", "y", "z", "rotation")


def _linear(c):
    return c[0] == c[1] and c[2] == c[3]


def bezier_points(curves, t):
    """(x, y) of MMD curves [n, 4] (x1, y1, x2, y2 in 0..127) at Bezier parameters t [n]"""
    c = np.asarray(curves, dtype=np.float64) / 127.0
    u = 1.0 - t
    x = 3 * u * u * t * c[:, 0] + 3 * u * t * t * c[:, 2] + t ** 3
    y = 3 * u * u * t * c[:, 1] + 3 * u * t * t * c[:, 3] + t ** 3
    return x, y


def bezier_t(curves, x):
    """the Bezier parameter where the curves [n, 4] reach the times x [n] (bisection, as mmd_cli.fk.bezier_y)"""
    lo = np.zeros(len(x))
    hi = np.ones(len(x))
    c = np.asarray(curves, dtype=np.float64) / 127.0
    for _ in range(40):
        t = 0.5 * (lo + hi)
        u = 1.0 - t
        below = 3 * u * u * t * c[:, 0] + 3 * u * t * t * c[:, 2] + t ** 3 < x
        lo = np.where(below, t, lo)
        hi = np.where(below, hi, t)
    return 0.5 * (lo + hi)


def bezier_y(curves, x):
    """y of the curves [n, 4] at the times x [n] in 0..1 (straight curves give x itself)"""
    curves = np.asarray(curves, dtype=np.int64).reshape(-1, 4)
    x = np.asarray(x, dtype=np.float64)
    out = x.copy()
    bent = ~((curves[:, 0] == curves[:, 1]) & (curves[:, 2] == curves[:, 3]))
    if np.any(bent):
        t = bezier_t(curves[bent], x[bent])
        out[bent] = bezier_points(curves[bent], t)[1]
    return out


def slerp_n(a, b, t):
    """slerp of quaternion rows a, b [n, 4] at t [n], the short way (mmd_cli.fk.slerp)"""
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
    return qnorm(wa[:, None] * a + wb[:, None] * b)


def curves_bytes(curves, keep):
    """the 64 bytes of a bone key with one curve per channel (channel -> (x1, y1, x2, y2)), bytes 2 and 3 of the first
    row as in `keep` (formats.vmd.bone_interpolation's layout)"""
    row = []
    for part in range(4):
        row += [int(curves[c][part]) for c in CHANNELS]
    out = []
    for shift in range(4):
        out += row[shift:] + [0] * shift
    out[2], out[3] = keep[2], keep[3]
    return bytes(out)


def _cut(cv, u):
    """the two curves a curve (x1, y1, x2, y2) becomes when its segment is cut at the time u (0..1), each rounded to
    MMD's 1/127 steps; straight curves stay straight"""
    if _linear(cv):
        return vmd.LINEAR_CURVE, vmd.LINEAR_CURVE
    t = float(bezier_t(np.array([cv]), np.array([u]))[0])
    p = [np.array(v, dtype=np.float64) for v in ((0.0, 0.0), (cv[0] / 127.0, cv[1] / 127.0), (cv[2] / 127.0, cv[3] / 127.0),
                                                  (1.0, 1.0))]
    p01, p12, p23 = p[0] + t * (p[1] - p[0]), p[1] + t * (p[2] - p[1]), p[2] + t * (p[3] - p[2])
    q0, q1 = p01 + t * (p12 - p01), p12 + t * (p23 - p12)
    m = q0 + t * (q1 - q0)

    def boxed(pts, lo, hi):
        span = hi - lo
        if span[0] < 1e-9 or span[1] < 1e-9:
            return vmd.LINEAR_CURVE
        out = []
        for pt in pts:
            out += [int(round(min(1.0, max(0.0, (pt[0] - lo[0]) / span[0])) * 127)),
                    int(round(min(1.0, max(0.0, (pt[1] - lo[1]) / span[1])) * 127))]
        return tuple(out)
    return boxed((p01, q0), p[0], m), boxed((q1, p23), m, p[3])


class Track:
    """one bone's keys, sorted by frame (of two keys on one frame the last counts), as arrays: frames [K], positions
    [K, 3], rotations as applied [K, 4], each key's curves (channel -> [K, 4]) and its 64 bytes; sample() gives what MMD
    shows on any frame (mmd_cli.fk.sample), split() adds a key without changing the motion, fit() sets and adds keys
    until the motion meets wanted values"""

    def __init__(self, keys):
        keys = sorted(keys, key=lambda k: k.frame)
        last = {}
        for k in keys:
            last[k.frame] = k
        keys = [last[f] for f in sorted(last)]
        if not keys:
            raise ValueError("a track needs keys")
        self.name = keys[0].name
        self.raw_name = keys[0].raw_name
        self.frames = np.array([k.frame for k in keys], dtype=np.int64)
        self.pos = np.array([k.position for k in keys], dtype=np.float64).reshape(-1, 3)
        self.rot = qnorm(np.array([fk.applied(k.rotation) for k in keys], dtype=np.float64).reshape(-1, 4))
        self.raw = [bytes(k.interpolation) for k in keys]
        self.curves = {c: np.array([vmd.bone_curves(r)[c] for r in self.raw], dtype=np.int64).reshape(-1, 4) for c in CHANNELS}

    def __len__(self):
        return len(self.frames)

    def sample(self, frames):
        frames = np.asarray(frames, dtype=np.float64)
        K = len(self.frames)
        i = np.searchsorted(self.frames, frames, side="right")
        a = np.clip(i - 1, 0, K - 1)
        b = np.clip(i, 0, K - 1)
        between = (i > 0) & (i < K) & (self.frames[a] != frames)
        x = np.where(between, (frames - self.frames[a]) / np.maximum(self.frames[b] - self.frames[a], 1), 0.0)
        pos = self.pos[a].copy()
        rot = self.rot[a].copy()
        if np.any(between):
            idx = np.flatnonzero(between)
            for ch, c in enumerate(CHANNELS[:3]):
                y = bezier_y(self.curves[c][b[idx]], x[idx])
                pos[idx, ch] = self.pos[a[idx], ch] + (self.pos[b[idx], ch] - self.pos[a[idx], ch]) * y
            y = bezier_y(self.curves["rotation"][b[idx]], x[idx])
            rot[idx] = slerp_n(self.rot[a[idx]], self.rot[b[idx]], y)
        return pos, rot

    def index_of(self, frame):
        j = int(np.searchsorted(self.frames, frame))
        return j if j < len(self.frames) and self.frames[j] == frame else None

    def split(self, frame):
        """add a key on `frame` holding what MMD shows there and return its index; the segment's curves are cut in two
        (a key before the first or after the last holds that key's value)"""
        frame = int(frame)
        j = self.index_of(frame)
        if j is not None:
            return j
        pos, rot = self.sample(np.array([frame]))
        i = int(np.searchsorted(self.frames, frame))
        K = len(self.frames)
        if i == 0 or i == K:
            self._insert(i, frame, pos[0], rot[0], vmd.bone_interpolation(vmd.LINEAR_CURVE))
            return i
        u = (frame - self.frames[i - 1]) / float(self.frames[i] - self.frames[i - 1])
        left, right = {}, {}
        for c in CHANNELS:
            left[c], right[c] = _cut(tuple(int(v) for v in self.curves[c][i]), u)
        keep = self.raw[i]
        self.raw[i] = curves_bytes(right, keep)
        for c in CHANNELS:
            self.curves[c][i] = right[c]
        self._insert(i, frame, pos[0], rot[0], curves_bytes(left, keep))
        return i

    def _insert(self, i, frame, pos, rot, raw):
        self.frames = np.insert(self.frames, i, frame)
        self.pos = np.insert(self.pos, i, pos, axis=0)
        self.rot = np.insert(self.rot, i, rot, axis=0)
        self.raw.insert(i, raw)
        cv = vmd.bone_curves(raw)
        for c in CHANNELS:
            self.curves[c] = np.insert(self.curves[c], i, np.array(cv[c], dtype=np.int64), axis=0)

    def keys(self):
        out = []
        for f, p, q, raw in zip(self.frames, self.pos, self.rot, self.raw):
            out.append(vmd.BoneKey(self.name, int(f), tuple(float(v) for v in p), fk.stored(tuple(float(v) for v in q)), raw,
                                   raw_name=self.raw_name))
        return out

    def _set(self, j, n, want_rot, want_pos):
        if want_rot is not None:
            q = want_rot[n]
            self.rot[j] = q if float(np.dot(q, self.rot[j])) >= 0.0 else -q
        if want_pos is not None:
            self.pos[j] = want_pos[n]

    def fit(self, frames, want_rot=None, want_pos=None, tol_deg=0.5, tol_pos=0.01, limit=None):
        """set the keys on `frames` to the wanted values (rotations as applied [n, 4], positions [n, 3]) and add keys,
        splitting segments, where what MMD shows between keys misses them by more than the tolerances; returns how many
        keys were added"""
        frames = np.asarray(frames, dtype=np.int64)
        where = {int(f): n for n, f in enumerate(frames)}
        for j, f in enumerate(self.frames):
            n = where.get(int(f))
            if n is not None:
                self._set(j, n, want_rot, want_pos)
        added = 0
        limit = len(frames) if limit is None else limit
        while added < limit:
            pos, rot = self.sample(frames)
            err = np.zeros(len(frames))
            if want_rot is not None:
                err = np.maximum(err, np.degrees(qangle(qmul(qconj(want_rot), rot))) / tol_deg)
            if want_pos is not None:
                err = np.maximum(err, np.linalg.norm(want_pos - pos, axis=1) / tol_pos)
            for f in self.frames:                  # a key already holds its wanted value
                n = where.get(int(f))
                if n is not None:
                    err[n] = 0.0
            n = int(np.argmax(err))
            if err[n] <= 1.0:
                break
            j = self.split(int(frames[n]))
            self._set(j, n, want_rot, want_pos)
            added += 1
        return added

    def fit_rotations(self, frames, want, tol_deg=0.5, limit=None):
        return self.fit(frames, want_rot=np.asarray(want, dtype=np.float64), tol_deg=tol_deg, limit=limit)

    def fit_positions(self, frames, want, tol=0.01, limit=None):
        return self.fit(frames, want_pos=np.asarray(want, dtype=np.float64), tol_pos=tol, limit=limit)


# ---- models --------------------------------------------------------------------------------------------------------------

def _pmd_vertices(data):
    """positions [N, 3], normals [N, 3] and the bone with the larger weight [N] of a PMD file's vertices"""
    pos = struct.calcsize("<3sf20s256s")
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    raw = np.frombuffer(data, dtype=np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("uv", "<f4", 2), ("b", "<u2", 2),
                                               ("w", "u1"), ("e", "u1")]), count=n, offset=pos)
    main = np.where(raw["w"] >= 50, raw["b"][:, 0], raw["b"][:, 1]).astype(np.int64)
    return raw["p"].astype(np.float64), raw["n"].astype(np.float64), main


def _pmx_vertices(doc):
    P = np.array([v.position() for v in doc.vertices], dtype=np.float64).reshape(-1, 3)
    N = np.array([struct.unpack_from("<3f", v.head, 12) for v in doc.vertices], dtype=np.float64).reshape(-1, 3)
    main = np.array([max(v.pairs(), key=lambda bw: bw[1])[0] for v in doc.vertices], dtype=np.int64)
    return P, N, main


def _pmd_limits(model):
    """the leg IKs' link limits of a PMD model as MMD (and saba) use them: a knee (a link named ひざ) turns about X only,
    -180..-0.5 degrees; other links are free.  PMD stores the IK's unit angle as a quarter of PMX's radians."""
    out = {}
    for b in model.bones:
        if b.ik:
            out[b.index] = [((-math.pi, 0.0, 0.0), (math.radians(-0.5), 0.0, 0.0)) if "ひざ" in model.bones[i].name else None
                            for i in b.ik["links"]]
            b.ik = dict(b.ik, angle=float(b.ik["angle"]) * 4.0)
    return out


class Body:
    """a model's skeleton at rest (formats.pmx Model), its leg IK limits (for tools/leg_ik.py) and its vertices (positions
    [N, 3] and the bone with the largest weight [N]) for the body's surfaces"""

    def __init__(self, model, limits, vertices=None, main_bone=None, name=None, normals=None, foot_from_mesh=True):
        self.model = model
        self.limits = limits
        self.vertices = np.zeros((0, 3)) if vertices is None else np.asarray(vertices, dtype=np.float64)
        self.main_bone = np.zeros(0, dtype=np.int64) if main_bone is None else np.asarray(main_bone, dtype=np.int64)
        self.normals = np.zeros_like(self.vertices) if normals is None else np.asarray(normals, dtype=np.float64)
        self.foot_from_mesh = foot_from_mesh
        self._surfaces = None
        self.name = name or model.name
        self.index = {}
        for b in model.bones:
            if b.position is None:
                raise ValueError("bone %r has no rest position" % b.name)
            self.index.setdefault(b.name, b.index)
        self.rest_all = np.array([b.position for b in model.bones], dtype=np.float64).reshape(-1, 3)
        self._rig = None

    # -- reading -----------------------------------------------------------------------------------------------------
    @classmethod
    def loads(cls, data, name=None):
        if data[:3] == b"Pmd":
            model = pmd.loads(data)
            limits = _pmd_limits(model)
            P, N, main = _pmd_vertices(data)
            return cls(model, limits, P, main, name, N)
        model = pmx.loads(data)
        doc = pmx_edit.loads(data)
        P, N, main = _pmx_vertices(doc)
        return cls(model, LI.ik_limits(doc), P, main, name, N)

    @classmethod
    def load(cls, path):
        if path.lower().endswith(".json"):
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
            return cls.from_spec(spec, os.path.dirname(os.path.abspath(path)))
        with open(path, "rb") as f:
            return cls.loads(f.read(), name=os.path.basename(path))

    @classmethod
    def from_spec(cls, spec, base_dir="."):
        """a body from a model and edits: {"model": path, "add": [{"name", "parent", "at": [x, y, z], "children": [...],
        "translate": bool, "vertices_above": [bone, y]}], "rest": {bone: [x, y, z]}, "foot": "mesh" | "bones"}.  An added
        bone takes the listed children from their parent and the vertices of `bone` above the height y; a moved bone
        moves the vertices whose largest weight is on it by as much; "foot": "bones" takes the sole from the bones (the
        toe bone and the ankle) instead of the shoe's vertices."""
        path = spec["model"]
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        base = cls.load(path)
        out = base.edited(spec.get("add", ()), spec.get("rest", {}), name=spec.get("name"))
        out.foot_from_mesh = spec.get("foot", "mesh") != "bones"
        out.spec = spec
        return out

    def edited(self, add=(), rest=None, name=None):
        """a copy with bones added (see from_spec) and rest positions moved"""
        import copy
        bones = [copy.deepcopy(b) for b in self.model.bones]
        names = [b.name for b in bones]
        for item in add:
            if item["name"] in names:
                raise ValueError("the model already has a bone named %r" % item["name"])
            parent = item.get("parent")
            if parent is not None and parent not in names:
                raise ValueError("no bone %r to add %r under" % (parent, item["name"]))
            new = pmx.Bone(len(bones), item["name"], None, None if parent is None else names.index(parent), 0,
                           {f: False for f, _ in pmx.FLAG_BITS}, None, None, tuple(float(v) for v in item["at"]),
                           {"offset": (0.0, 0.0, 0.0)})
            new.flags.update(rotate=True, visible=True, enabled=True, translate=bool(item.get("translate", False)))
            bones.append(new)
            names.append(new.name)
            for child in item.get("children", ()):
                if child not in names:
                    raise ValueError("no bone %r to put under %r" % (child, item["name"]))
                bones[names.index(child)].parent = new.index
        # parents before children: the order the formats keep is the file's; the FK here sorts by depth itself
        vertices = self.vertices.copy()
        main_bone = self.main_bone.copy()
        for item in add:
            above = item.get("vertices_above")
            if above and len(vertices):
                src = names.index(above[0])
                main_bone[(self.main_bone == src) & (vertices[:, 1] > float(above[1]))] = names.index(item["name"])
        for bname, at in (rest or {}).items():
            if bname not in names:
                raise ValueError("no bone %r to move" % bname)
            i = names.index(bname)
            old = np.array(bones[i].position, dtype=np.float64)
            bones[i].position = tuple(float(v) for v in at)
            if len(vertices):
                vertices[main_bone == i] += np.array(at, dtype=np.float64) - old
        model = pmx.Model(self.model.format, self.model.version, self.model.name, self.model.name_en, self.model.comment,
                          self.model.comment_en, dict(self.model.counts, bones=len(bones)), bones, self.model.morphs,
                          self.model.display_frames)
        return Body(model, self.limits, vertices, main_bone, name or self.name, self.normals, self.foot_from_mesh)

    # -- the skeleton --------------------------------------------------------------------------------------------------
    def has(self, name):
        return name in self.index

    def i(self, name):
        return self.index[name]

    def rest(self, name):
        return self.rest_all[self.index[name]].copy()

    def parent(self, k):
        return self.model.bones[k].parent

    def rig(self):
        """tools/leg_ik.LegRig of the body (ValueError without the usual leg rig)"""
        if self._rig is None:
            self._rig = LI.LegRig(self.model, self.limits)
        return self._rig

    def hip_height(self, side):
        """the hip joint's height over the ankle at rest (units)"""
        return float(self.rest(side + "足")[1] - self.rest(side + "足首")[1])

    def direction(self, a, b):
        return unit(self.rest(b) - self.rest(a))


# ---- poses: the bones' world positions and rotations over frames ---------------------------------------------------------

def tracks_of(keys):
    """bone name -> Track of a list of BoneKeys"""
    by = {}
    for k in keys:
        by.setdefault(k.name, []).append(k)
    return {n: Track(ks) for n, ks in by.items()}


def closure(body, ks):
    """the bones ks with their ancestors and append parents, each after its parent and its append parent"""
    need, stack = set(), list(ks)
    while stack:
        k = stack.pop()
        if k in need:
            continue
        need.add(k)
        if body.parent(k) is not None:
            stack.append(body.parent(k))
        a = append_of(body, k)
        if a is not None:
            stack.append(a[0])
    order, placed = [], set()

    def place(k, depth=0):
        if k in placed:
            return
        if depth > len(body.model.bones):
            raise ValueError("the bones of %r go round in a loop" % body.model.bones[k].name)
        if body.parent(k) is not None:
            place(body.parent(k), depth + 1)
        a = append_of(body, k)
        if a is not None:
            place(a[0], depth + 1)
        placed.add(k)
        order.append(k)
    for k in sorted(need):
        place(k)
    return order


def append_of(body, k):
    """(parent, ratio, rotates, translates) of the bone's append, or None (mmd_cli.fk.Pose._appends)"""
    b = body.model.bones[k]
    a = b.append
    if a is None or a.get("parent") is None:
        return None
    rot, tr = bool(b.flags.get("append_rotate")), bool(b.flags.get("append_translate"))
    if not (rot or tr):
        return None
    return a["parent"], float(a["ratio"]), rot, tr


def key_values(body, trk, frames, ks, overrides=None):
    """bone index -> (key positions [F, 3], rotations as applied [F, 4]) of the bones ks: an override, else the track of
    the bone's name (or its 15-byte VMD name), else rest"""
    F = len(frames)
    out = {}
    for k in ks:
        if overrides and k in overrides:
            out[k] = overrides[k]
            continue
        name = body.model.bones[k].name
        tr = trk.get(name) or trk.get(fk.vmd_name(name))
        if tr is None:
            out[k] = (np.zeros((F, 3)), np.tile(IDENTITY, (F, 1)))
        else:
            out[k] = tr.sample(frames)
    return out


def world_pose(body, trk, frames, names, overrides=None):
    """name -> (world positions [F, 3], world rotations [F, 4]) of the bones `names` (no IK: the rule of mmd_cli.fk)"""
    frames = np.asarray(frames)
    ks = closure(body, [body.i(n) for n in names])
    keys = key_values(body, trk, frames, ks, overrides)
    local = {}

    def loc(k):
        if k in local:
            return local[k]
        P, R = keys[k]
        a = append_of(body, k)
        if a is not None:
            pp, pr = loc(a[0])
            if a[2]:
                R = qmul(R, LI.qpow(pr, a[1]))
            if a[3]:
                P = P + a[1] * pp
        local[k] = (P, R)
        return local[k]
    wpos, wrot = {}, {}
    for k in ks:
        P, R = loc(k)
        par = body.parent(k)
        if par is None:
            wpos[k] = body.rest_all[k] + P
            wrot[k] = R
        else:
            wpos[k] = wpos[par] + qrot(wrot[par], body.rest_all[k] - body.rest_all[par] + P)
            wrot[k] = qmul(wrot[par], R)
    return {n: (wpos[body.i(n)], wrot[body.i(n)]) for n in names}


def leg_pose(body, trk, frames):
    """tools/leg_ik.solve of the body's legs under the tracks (MMD's IK)"""
    rig = body.rig()
    need = set(rig.order)
    for k in list(need):
        a = rig.bones[k].append
        if a is not None and a.get("parent") is not None:
            need.add(a["parent"])
    keys = key_values(body, trk, np.asarray(frames), sorted(need))
    return LI.solve(rig, None, list(frames), keys=keys)


# ---- the body's surfaces: signed distances from the mesh, per part, in the part's bone frame -----------------------------

# part -> (the bone it rides on, the bones whose vertices make it); the head takes its bone's direct children too (hair,
# ribbon, glasses on Rin; the front hair and tails' roots on あにまさ式)
PARTS = {"head": ("頭", ("頭",)), "chest": ("上半身2", ("上半身2", "胸椎上部")), "belly": ("上半身", ("上半身", "腰椎上部")),
         "hips": ("下半身", ("下半身", "腰")), "thigh_左": ("左足", ("左足", "左足D")), "thigh_右": ("右足", ("右足", "右足D"))}
HEAD_CHILDREN = True
GRID = 0.1                      # units: the signed distance grid's spacing
MARGIN = 1.0                    # units the grid reaches past the part's vertices
VOXEL = 0.08                    # units: vertices closer than this are merged before the grid is filled


class Surface:
    """a signed distance to a part's mesh (its vertices with their normals, in the riding bone's frame relative to its rest
    position): on a grid, the distance to the nearest vertex signed by that vertex's normal; trilinear between nodes,
    past the grid the distance to its box added"""

    def __init__(self, points, normals, spacing=GRID, margin=MARGIN):
        points = np.asarray(points, dtype=np.float64)
        normals = unit(np.asarray(normals, dtype=np.float64))
        cell = np.floor(points / VOXEL).astype(np.int64)
        _, inv = np.unique(cell, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        n = inv.max() + 1
        P = np.zeros((n, 3))
        N = np.zeros((n, 3))
        c = np.bincount(inv, minlength=n).astype(np.float64)
        for d in range(3):
            P[:, d] = np.bincount(inv, weights=points[:, d], minlength=n) / c
            N[:, d] = np.bincount(inv, weights=normals[:, d], minlength=n)
        self.points = P
        self.normals = unit(N)
        self.lo = P.min(axis=0) - margin
        self.hi = P.max(axis=0) + margin
        self.box_center = 0.5 * (P.min(axis=0) + P.max(axis=0))
        self.box_half = np.maximum(0.5 * (P.max(axis=0) - P.min(axis=0)), 1e-3)
        self.h = spacing
        self.shape = tuple(int(v) for v in np.ceil((self.hi - self.lo) / spacing).astype(int) + 1)
        gx, gy, gz = (self.lo[d] + spacing * np.arange(self.shape[d]) for d in range(3))
        nodes = np.stack(np.meshgrid(gx, gy, gz, indexing="ij"), axis=-1).reshape(-1, 3)
        dist = np.empty(len(nodes))
        step = max(64, int(2.0e6 // max(len(P), 1)))
        for a in range(0, len(nodes), step):
            q = nodes[a:a + step]
            d2 = np.sum((q[:, None, :] - P[None, :, :]) ** 2, axis=-1)
            j = np.argmin(d2, axis=1)
            sign = np.sign(np.sum((q - P[j]) * self.normals[j], axis=1))
            sign[sign == 0] = 1.0
            dist[a:a + step] = sign * np.sqrt(d2[np.arange(len(q)), j])
        self.grid = dist.reshape(self.shape)

    def sdf(self, q):
        q = np.asarray(q, dtype=np.float64)
        flat = q.reshape(-1, 3)
        inside = np.clip(flat, self.lo, self.hi)
        outside = np.linalg.norm(flat - inside, axis=1)
        g = (inside - self.lo) / self.h
        i0 = np.clip(np.floor(g).astype(np.int64), 0, np.array(self.shape) - 2)
        t = np.clip(g - i0, 0.0, 1.0)
        out = np.zeros(len(flat))
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    w = ((t[:, 0] if dx else 1 - t[:, 0]) * (t[:, 1] if dy else 1 - t[:, 1]) * (t[:, 2] if dz else 1 - t[:, 2]))
                    out += w * self.grid[i0[:, 0] + dx, i0[:, 1] + dy, i0[:, 2] + dz]
        return (out + outside).reshape(q.shape[:-1])

    def grad(self, q):
        q = np.asarray(q, dtype=np.float64)
        e = 0.5 * self.h
        g = np.stack([(self.sdf(q + e * ax) - self.sdf(q - e * ax)) / (2 * e) for ax in np.eye(3)], axis=-1)
        return unit(g)

    def closest(self, q):
        """the point of the surface nearest q (one step along the gradient)"""
        return q - self.sdf(q)[..., None] * self.grad(q)


def part_vertices(body, part):
    """(points rel. the riding bone's rest position, normals) of a part, or None"""
    ride, bones = PARTS[part]
    if not body.has(ride) or not len(body.vertices):
        return None
    idx = [body.i(n) for n in bones if body.has(n)]
    if part == "head" and HEAD_CHILDREN:
        head = body.i("頭")
        idx += [b.index for b in body.model.bones if b.parent == head and not b.name.endswith(("目", "目光"))]
    m = np.isin(body.main_bone, idx)
    if m.sum() < 8:
        return None
    return body.vertices[m] - body.rest(ride), body.normals[m]


def surfaces(body):
    """part -> Surface of the body (parts without vertices are left out); kept on the body"""
    if getattr(body, "_surfaces", None) is None:
        out = {}
        for part in PARTS:
            pv = part_vertices(body, part)
            if pv is not None:
                out[part] = Surface(*pv)
        body._surfaces = out
    return body._surfaces


def arm_radii(body, side):
    """(upper arm, forearm, hand) radii: the 60th percentile of the distance of the vertices on those bones from the
    bone's segment (a body without such vertices gets 0.35, 0.3, 0.25)"""
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


def hand_offsets(body, side):
    """the hand's points relative to the wrist at rest: the palm's middle and the middle finger's tip"""
    w = body.rest(side + "手首")
    m1 = body.rest(side + "中指１") if body.has(side + "中指１") else w
    if body.has(side + "中指先"):
        tip = body.rest(side + "中指先")
    elif body.has(side + "中指３") and body.has(side + "中指２"):
        tip = body.rest(side + "中指３") + 0.6 * (body.rest(side + "中指３") - body.rest(side + "中指２"))
    else:
        tip = m1 + 0.8 * (m1 - w)
    return {"palm": 0.5 * (m1 - w), "tip": tip - w}


# ---- the feet: a foot that stands on the floor in the source stands still on the floor in the target ----------------------

FLOOR_EPS = 0.06                # units (5 mm): a sole point this close to the floor touches it
STILL = 0.025                   # units a frame (6 cm/s): a touching point slower than this stands
PLANT_MIN = 3                   # frames: standing this long is a plant
PITCH_FLAT_DEG = 4.0            # a foot pitched less than this stands flat; toe down more: on the toe; toe up more: on the heel
MAX_PITCH_DEG = 75.0            # the foot's pitch from flat at most (toe down)
EASE = 3                        # frames a correction takes to come in and to go out
HEEL_BACK = 0.3                 # without a shoe mesh, the heel lies this share of the ankle-to-toe line behind the ankle
SHOE = ("足首", "足首D", "足先EX", "つま先")


def sole_points(body, side):
    """the foot's sole points at rest relative to the ankle (heel, ball, toe) and the floor height: from the shoe's
    vertices (the lowest band's back and front ends) when the body has them, else from the bones"""
    ankle = body.rest(side + "足首")
    toe = body.rest(side + "つま先")
    idx = [body.i(side + n) for n in SHOE if body.has(side + n)]
    m = np.isin(body.main_bone, idx) if (len(body.vertices) and getattr(body, "foot_from_mesh", True)) else np.zeros(0, bool)
    if m.sum() >= 20:
        P = body.vertices[m]
        floor = float(P[:, 1].min())
        low = P[P[:, 1] < floor + 0.25]
        front = low[np.argmin(low[:, 2])]
        back = low[np.argmax(low[:, 2])]
        heel = np.array([ankle[0], floor, back[2]])
        tip = np.array([front[0], floor, front[2]])
    else:
        floor = float(toe[1])
        tip = np.array([toe[0], floor, toe[2]])
        heel = np.array([ankle[0], floor, ankle[2] + HEEL_BACK * (ankle[2] - toe[2])])
    if body.has(side + "足先EX"):
        ex = body.rest(side + "足先EX")
        ball = np.array([ex[0], floor, ex[2]])
    else:
        ball = heel + 0.7 * (tip - heel)
    return {"heel": heel - ankle, "ball": ball - ankle, "toe": tip - ankle}, floor


def foot_pitch(q_foot):
    """degrees the foot's front (-Z turned by the foot) points below level (+ toe down)"""
    fwd = qrot(q_foot, np.array([0.0, 0.0, -1.0]))
    return np.degrees(np.arcsin(np.clip(-fwd[..., 1], -1.0, 1.0)))


def runs(mask, min_len=1):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]]).astype(np.int8)
    d = np.diff(m)
    st = np.flatnonzero(d == 1)
    en = np.flatnonzero(d == -1) - 1
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a + 1 >= min_len]


def plants(body, legs, side):
    """the source's plants of one foot: [(first, last, kind)] with kind flat / toe / heel, and the per-frame arrays.  A
    frame stands when one of the sole points (heel, ball, toe) touches the floor and moves slower than STILL (a flat
    foot turning on its ball stands on the ball)."""
    pts, floor = sole_points(body, side)
    leg = legs[side]
    A, Q = leg["ankle"], leg["q_foot"]
    names = ("heel", "ball", "toe")
    W = np.stack([A + qrot(Q, pts[k]) for k in names], axis=1)                 # [F, 3, 3]
    H = W[:, :, 1] - floor
    v = np.zeros(H.shape)
    v[1:] = np.linalg.norm(np.diff(W[:, :, [0, 2]], axis=0), axis=2)
    v_next = np.concatenate([v[1:], v[-1:]], axis=0) if len(v) else v
    still = np.minimum(v, v_next) < STILL
    stand = np.any((H < FLOOR_EPS) & still, axis=1)
    pitch = foot_pitch(Q)
    out = []
    for a, b in runs(stand, PLANT_MIN):
        p = float(np.median(pitch[a:b + 1]))
        kind = "toe" if p > PITCH_FLAT_DEG else ("heel" if p < -PITCH_FLAT_DEG else "flat")
        out.append((a, b, kind))
    return out, {"height": H.min(axis=1), "pitch": pitch, "stand": stand}


def ease_weights(F, spans, ease=EASE):
    """per frame, the index of the span it belongs to (-1: none) and its weight (1 inside, a smoothstep over `ease` frames
    on each side)"""
    which = np.full(F, -1)
    weight = np.zeros(F)
    for n, (a, b) in enumerate(spans):
        for f in range(max(0, a - ease), min(F, b + ease + 1)):
            if f < a:
                w = (f - (a - ease - 1)) / float(ease + 1)
            elif f > b:
                w = ((b + ease + 1) - f) / float(ease + 1)
            else:
                w = 1.0
            w = w * w * (3 - 2 * w)
            if w > weight[f]:
                which[f], weight[f] = n, w
    return which, weight


def pitch_turn(q_foot, degrees):
    """the world turn that pitches the foot by `degrees` (toe down) about its own side axis"""
    axis = unit(qrot(q_foot, np.array([1.0, 0.0, 0.0])))
    return qaxis(axis, -np.radians(degrees))


def solve_pitch(A, Q, offset, floor, lo, hi, step=0.5):
    """per frame the pitch change (degrees, in lo..hi) nearest 0 that puts the point `offset` (rel. the ankle A, turned by
    the foot Q) on the floor; where no pitch in the range reaches it, the one that brings it nearest.  Returns (change,
    the point's height above the floor left over)."""
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    n = len(A)
    if not n:
        return np.zeros(0), np.zeros(0)

    def height(d):
        return A[:, 1] + qrot(qmul(pitch_turn(Q, d), Q), offset)[:, 1] - floor
    steps = int(np.ceil(np.max(hi - lo) / step)) + 1
    grid = lo[:, None] + (hi - lo)[:, None] * np.linspace(0.0, 1.0, steps)[None, :]
    H = np.stack([height(grid[:, j]) for j in range(steps)], axis=1)
    best = np.full(n, np.nan)
    a_br = np.zeros(n)
    b_br = np.zeros(n)
    for j in range(steps - 1):              # the crossing nearest no change
        cross = (np.sign(H[:, j]) != np.sign(H[:, j + 1])) | (H[:, j] == 0.0)
        mid = 0.5 * (grid[:, j] + grid[:, j + 1])
        take = cross & (np.isnan(best) | (np.abs(mid) < np.abs(best)))
        best = np.where(take, mid, best)
        a_br = np.where(take, grid[:, j], a_br)
        b_br = np.where(take, grid[:, j + 1], b_br)
    found = ~np.isnan(best)
    a, b = a_br.copy(), b_br.copy()
    ha = height(a)
    for _ in range(30):
        m = 0.5 * (a + b)
        hm = height(m)
        same = np.sign(hm) == np.sign(ha)
        a = np.where(same, m, a)
        ha = np.where(same, hm, ha)
        b = np.where(same, b, m)
    nearest = grid[np.arange(n), np.argmin(np.abs(H), axis=1)]
    d = np.where(found, 0.5 * (a + b), nearest)
    return d, height(d)


FLAT_LIFT_MAX = 0.15            # units (1.2 cm): a flat foot's ankle moves up or down at most this to put its sole on the floor
FEET_ROUNDS = 2


def fix_feet(src, tgt, src_legs, tgt_trk, frames, params, log):
    """the target's foot IK keys for the source's plants: the touching sole point held still on the floor; a foot on its
    toe or heel pitched about its own side axis (the ankle where the mapping put it) until that point reaches the floor;
    a flat foot's ankle moved up or down (at most FLAT_LIFT_MAX) until its sole does.  The hips are never lowered.
    Returns the report."""
    F = len(frames)
    rep = {}
    found = {side: plants(src, src_legs, side) for side in SIDES}
    for rnd in range(FEET_ROUNDS):
        tgt_legs = leg_pose(tgt, tgt_trk, frames)
        for side in SIDES:
            spans, _ = found[side]
            pts_t, floor_t = sole_points(tgt, side)
            leg = tgt_legs[side]
            A, Q = leg["ankle"], leg["q_foot"]
            which, weight = ease_weights(F, [(a, b) for a, b, _ in spans])
            d_pitch = np.zeros(F)
            shift = np.zeros((F, 3))
            left_over = np.full(F, np.nan)
            kinds = {"flat": 0, "toe": 0, "heel": 0}
            for n, (a, b, kind) in enumerate(spans):
                kinds[kind] += 1
                idx = np.flatnonzero(which == n)
                if not len(idx):
                    continue
                point = pts_t["toe" if kind == "toe" else ("heel" if kind == "heel" else "ball")]
                p0 = foot_pitch(Q[idx])
                if kind == "flat":
                    d = np.zeros(len(idx))
                    low = np.min(np.stack([A[idx, 1] + qrot(Q[idx], v)[:, 1] for v in pts_t.values()], axis=1), axis=1) - floor_t
                    lift = np.clip(-low, -FLAT_LIFT_MAX, FLAT_LIFT_MAX)
                    left_over[idx] = low + lift
                else:
                    if kind == "toe":
                        lo, hi = -np.maximum(p0, 0.0), MAX_PITCH_DEG - p0
                    else:
                        lo, hi = -MAX_PITCH_DEG - p0, -np.minimum(p0, 0.0)
                    d, rest_h = solve_pitch(A[idx], Q[idx], point, floor_t, lo, hi)
                    lift = np.zeros(len(idx))
                    left_over[idx] = rest_h
                Qn = qmul(pitch_turn(Q[idx], d), Q[idx])
                C = A[idx] + qrot(Qn, point)
                inside = (idx >= a) & (idx <= b)
                lock = np.mean(C[inside][:, [0, 2]], axis=0) if np.any(inside) else np.mean(C[:, [0, 2]], axis=0)
                sh = np.zeros((len(idx), 3))
                sh[:, 0] = lock[0] - C[:, 0]
                sh[:, 2] = lock[1] - C[:, 2]
                sh[:, 1] = lift
                w = weight[idx]
                d_pitch[idx] = w * d
                shift[idx] = w[:, None] * sh
            ik = side + "足ＩＫ"
            tr = tgt_trk.get(ik)
            if tr is None:
                tgt_trk[ik] = tr = Track([vmd.BoneKey(ik, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))])
            par = tgt.model.bones[tgt.i(ik)].parent
            pname = tgt.model.bones[par].name if par is not None else None
            Wp = world_pose(tgt, tgt_trk, frames, [pname])[pname][1] if pname else np.tile(IDENTITY, (F, 1))
            pos, rot = tr.sample(frames)
            new_rot = qmul(qconj(Wp), qmul(pitch_turn(Q, d_pitch), qmul(Wp, rot)))
            new_pos = pos + qrot(qconj(Wp), shift)
            moved = np.flatnonzero(weight > 0)
            added = tr.fit(frames[moved], want_rot=new_rot[moved], want_pos=new_pos[moved], tol_deg=0.25, tol_pos=0.005) if len(moved) else 0
            r = rep.setdefault(side, {"plants": len(spans), "kinds": kinds, "plant_frames": int(sum(b - a + 1 for a, b, _ in spans)),
                                      "keys_added": 0})
            r["keys_added"] += added
            if rnd == 0:
                r["pitch_change_deg"] = _quant(np.abs(d_pitch[weight >= 1.0]))
                r["shift_cm"] = _quant(np.linalg.norm(shift[weight >= 1.0], axis=1) * UNIT_CM)
            inside_toe = np.isin(which, [n for n, s in enumerate(spans) if s[2] != "flat"]) & (weight >= 1.0)
            r["toe_left_over_cm"] = _quant(np.abs(left_over[inside_toe & ~np.isnan(left_over)]) * UNIT_CM)
            r["toe_unreached_frames"] = int(np.sum(inside_toe & (np.abs(np.nan_to_num(left_over)) > 0.0125)))
            log("feet %s round %d: %d plants (%s), %d keys added" % (side, rnd, len(spans), kinds, added))
    return rep


def _quant(x, qs=(50, 90, 99, 100)):
    x = np.asarray(x, dtype=np.float64)
    if not len(x):
        return None
    return {("max" if q == 100 else "p%d" % q): round(float(np.percentile(x, q)), 4) for q in qs}


# ---- the hands: a hand near the body in the source is as near the same place of the target's body --------------------

TOUCH = 0.12                    # units (1 cm): a hand point this close to a part touches it
NEAR = 0.8                      # units (6.4 cm): the hand's place on a part is kept within this, fading out towards it
HAND_THICK = 0.15               # units: half a hand's thickness (the two palms' points touch at twice this)
CLEAR_ROUNDS = 3
CLEAR_MARGIN = 0.02             # units: the arm is pushed this much past the surface
SHOULDER_SKIP = 0.35            # the upper arm's first share lies in the trunk at rest: not tested against it
TOL_DEG = 0.3                   # the keys meet the wanted turns this closely


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def part_frames(body, trk, frames):
    """part -> (world position [F, 3] of the riding bone, its world turn [F, 4]) for the body's surfaces"""
    surf = surfaces(body)
    names = sorted({PARTS[p][0] for p in surf})
    wp = world_pose(body, trk, frames, names) if names else {}
    return {p: wp[PARTS[p][0]] for p in surf}


def arm_names(side):
    return [side + n for n in ("腕", "腕捩", "ひじ", "手捩", "手首")]


def arm_pose(body, trk, frames, side):
    names = arm_names(side)
    have = [n for n in names if body.has(n)]
    return world_pose(body, trk, frames, have)


def frame_turn(d0, n0, d1, n1):
    """the turn taking the frame (d0, n0) onto (d1, n1) (unit, at right angles), rows of frames"""
    def mat(d, n):
        return np.stack([d, n, np.cross(d, n)], axis=-1)
    M = mat(d1, n1) @ np.swapaxes(mat(d0, n0), -1, -2)
    return mat_quat(M)


def mat_quat(M):
    """unit quaternions of rotation matrices [..., 3, 3]"""
    M = np.asarray(M, dtype=np.float64)
    tr = M[..., 0, 0] + M[..., 1, 1] + M[..., 2, 2]
    q = np.empty(M.shape[:-2] + (4,))
    w = np.sqrt(np.maximum(0.0, 1.0 + tr)) / 2.0
    x = np.sqrt(np.maximum(0.0, 1.0 + M[..., 0, 0] - M[..., 1, 1] - M[..., 2, 2])) / 2.0
    y = np.sqrt(np.maximum(0.0, 1.0 - M[..., 0, 0] + M[..., 1, 1] - M[..., 2, 2])) / 2.0
    z = np.sqrt(np.maximum(0.0, 1.0 - M[..., 0, 0] - M[..., 1, 1] + M[..., 2, 2])) / 2.0
    q[..., 0] = np.copysign(x, M[..., 2, 1] - M[..., 1, 2])
    q[..., 1] = np.copysign(y, M[..., 0, 2] - M[..., 2, 0])
    q[..., 2] = np.copysign(z, M[..., 1, 0] - M[..., 0, 1])
    q[..., 3] = w
    return qnorm(q)


def arm_ik(S, E, W, Wt, pole=None):
    """the elbow E* and the wrist reached W* for wanted wrists Wt (shoulders S, elbows E, wrists W [F, 3]): the arm keeps
    its lengths; the elbow keeps the side of the shoulder-wrist line it was on (or goes towards `pole`)"""
    a = np.linalg.norm(E - S, axis=1)
    b = np.linalg.norm(W - E, axis=1)
    d = np.linalg.norm(Wt - S, axis=1)
    dd = np.clip(d, np.abs(a - b) + 1e-4, a + b - 1e-4)
    u = unit(Wt - S)
    P = (E if pole is None else pole) - S
    v = P - np.sum(P * u, axis=1)[:, None] * u
    bad = np.linalg.norm(v, axis=1) < 1e-6
    if np.any(bad):
        alt = np.cross(u, np.array([0.0, 0.0, 1.0]))
        v = np.where(bad[:, None], alt, v)
    v = unit(v)
    cos_a = np.clip((a * a + dd * dd - b * b) / (2 * a * dd), -1.0, 1.0)
    Es = S + a[:, None] * (cos_a[:, None] * u + np.sqrt(1 - cos_a ** 2)[:, None] * v)
    return Es, S + dd[:, None] * u


def arm_locals(body, trk, frames, side, Es, Ws, hand_turn):
    """the local turns (as applied) of 腕, ひじ and 手首 that put the elbow at Es and the wrist at Ws, keeping the arm's
    plane turned with it (the elbow a hinge) and the hand's world turn `hand_turn`"""
    names = arm_names(side)
    up, tw, el, htw, hd = names
    par = body.model.bones[body.i(up)].parent
    wp = world_pose(body, trk, frames, [body.model.bones[par].name] + names)
    Wpar = wp[body.model.bones[par].name][1]
    S, Rup = wp[up]
    E, Rel = wp[el]
    W = wp[hd][0]
    keys = key_values(body, trk, frames, [body.i(n) for n in names])
    L = {n: keys[body.i(n)][1] for n in names}
    d0, d1 = unit(E - S), unit(Es - S)
    f0, f1 = W - E, Ws - Es
    n0, n1 = np.cross(d0, f0), np.cross(d1, f1)
    straight = (np.linalg.norm(n0, axis=1) < 1e-4 * np.linalg.norm(f0, axis=1)) | (np.linalg.norm(n1, axis=1) < 1e-4 * np.linalg.norm(f1, axis=1))
    n0 = unit(n0 - np.sum(n0 * d0, axis=1)[:, None] * d0)
    n1 = unit(n1 - np.sum(n1 * d1, axis=1)[:, None] * d1)
    turn_up = frame_turn(d0, n0, d1, n1)
    turn_up = np.where(straight[:, None], qbetween(d0, d1), turn_up)
    Rup2 = qmul(turn_up, Rup)
    Rtw2 = qmul(Rup2, L[tw])
    f0b = qrot(turn_up, f0)
    turn_fo = qbetween(f0b, f1)
    Rel2 = qmul(turn_fo, qmul(turn_up, Rel))
    Rhtw2 = qmul(Rel2, L[htw])
    return {up: qnorm(qmul(qconj(Wpar), Rup2)), el: qnorm(qmul(qconj(Rtw2), Rel2)), hd: qnorm(qmul(qconj(Rhtw2), hand_turn))}


def hand_world(body, trk, frames, side):
    """(wrist position, hand turn, {point: world position}) of a hand"""
    wp = world_pose(body, trk, frames, [side + "手首"])
    W, R = wp[side + "手首"]
    off = hand_offsets(body, side)
    return W, R, {k: W + qrot(R, v) for k, v in off.items()}


def contacts(src, src_trk, frames, side, src_parts, src_hand):
    """per part: the source's nearest distance of the hand (palm or tip) to it [F], which point, the nearest surface point
    (in the part's frame) and the weight of the relation [F]"""
    surf = surfaces(src)
    out = {}
    for part, (pos, rot) in src_parts.items():
        s = surf[part]
        best = None
        for point, P in src_hand[2].items():
            local = qrot(qconj(rot), P - pos)
            d = s.sdf(local)
            if best is None:
                best = (d, np.full(len(d), point, dtype=object), local)
            else:
                closer = d < best[0]
                best = (np.where(closer, d, best[0]), np.where(closer, point, best[1]), np.where(closer[:, None], local, best[2]))
        d, which, local = best
        out[part] = {"d": d, "point": which, "near": s.closest(local), "w": smoothstep((NEAR - d) / (NEAR - TOUCH))}
    return out


def mapped_contact(src, tgt, part, near_src, d_src):
    """the target's point (in its part's frame) answering the source's nearest surface point and distance"""
    ss, st = surfaces(src)[part], surfaces(tgt)[part]
    u = (near_src - ss.box_center) / ss.box_half
    p0 = st.box_center + u * st.box_half
    c = st.closest(st.closest(p0))
    n = st.grad(c)
    k = float(np.mean(st.box_half / ss.box_half))
    return c + n * (np.maximum(d_src, 0.0) * k)[:, None]


def fix_hands(src, tgt, src_trk, tgt_trk, frames, params, log):
    """the target's arm keys (腕, ひじ, 手首): the hand kept where the source's is relative to a part it is near (and to
    the other hand), then the arm pushed out of the target's head, trunk, hips and thighs; returns the report"""
    F = len(frames)
    rep = {}
    have_src = set(surfaces(src)) & set(surfaces(tgt))
    src_parts = {p: v for p, v in part_frames(src, src_trk, frames).items() if p in have_src}
    tgt_parts = {p: v for p, v in part_frames(tgt, tgt_trk, frames).items() if p in have_src}
    want = {}
    weights = {}
    hands_src = {side: hand_world(src, src_trk, frames, side) for side in SIDES}
    hands_tgt = {side: hand_world(tgt, tgt_trk, frames, side) for side in SIDES}
    for side in SIDES:
        if not all(tgt.has(n) and src.has(n) for n in arm_names(side)):
            continue
        Wt, Rt, pts_t = hands_tgt[side]
        target = Wt.copy()
        total = np.zeros(F)
        acc = np.zeros((F, 3))
        top = np.zeros(F)
        rel = contacts(src, src_trk, frames, side, src_parts, hands_src[side]) if params.get("hands", True) else {}
        off_t = hand_offsets(tgt, side)
        used = {}
        for part, c in rel.items():
            w = c["w"]
            on = w > 0
            used[part] = int(np.sum(w >= 1.0))
            if not np.any(on):
                continue
            pos, rot = tgt_parts[part]
            Q = mapped_contact(src, tgt, part, c["near"][on], c["d"][on])
            Qw = pos[on] + qrot(rot[on], Q)
            offs = np.stack([off_t[p] for p in c["point"][on]])
            want_w = Qw - qrot(Rt[on], offs)
            acc[on] += w[on, None] * want_w
            total[on] += w[on]
            top[on] = np.maximum(top[on], w[on])
        has = total > 0
        target[has] = Wt[has] + top[has, None] * (acc[has] / total[has, None] - Wt[has])
        want[side] = target
        weights[side] = {part: c["w"] for part, c in rel.items()}
        rep[side] = {"touch_frames": used}
    # the two hands: their palms as far apart (and the same way) as the source's, scaled by the shoulders' ratio
    if params.get("hands", True) and all(s in want for s in SIDES):
        ps = hands_src["左"][2]["palm"] - hands_src["右"][2]["palm"]
        pt = hands_tgt["左"][2]["palm"] - hands_tgt["右"][2]["palm"]
        dist = np.linalg.norm(ps, axis=1) - 2 * HAND_THICK
        w = smoothstep((NEAR - dist) / (NEAR - TOUCH))
        k = np.linalg.norm(tgt.rest("左腕") - tgt.rest("右腕")) / max(np.linalg.norm(src.rest("左腕") - src.rest("右腕")), 1e-6)
        need = (ps * k - pt) * w[:, None]
        want["左"] = want["左"] + 0.5 * need
        want["右"] = want["右"] - 0.5 * need
        rep["hands_together_frames"] = int(np.sum(w >= 1.0))
    for side in list(want):
        Wt, Rt, _ = hands_tgt[side]
        moved = np.linalg.norm(want[side] - Wt, axis=1) > 1e-6
        ap = arm_pose(tgt, tgt_trk, frames, side)
        S, E, W = ap[side + "腕"][0], ap[side + "ひじ"][0], ap[side + "手首"][0]
        Es, Ws = arm_ik(S, E, W, want[side])
        Es = np.where(moved[:, None], Es, E)
        Ws = np.where(moved[:, None], Ws, W)
        loc = arm_locals(tgt, tgt_trk, frames, side, Es, Ws, Rt)
        for name, q in loc.items():
            _fit_turns(tgt_trk, name, frames, q, moved)
        rep[side]["moved_frames"] = int(moved.sum())
        rep[side]["moved_cm"] = _quant(np.linalg.norm(want[side] - Wt, axis=1)[moved] * UNIT_CM)
    if params.get("clear", True):
        clr = clear_arms(tgt, tgt_trk, frames, weights, tgt_parts, log)
        for side in SIDES:
            rep.setdefault(side, {})["clear"] = clr.get(side)
    return rep


def _fit_turns(trk, name, frames, q, frames_mask):
    tr = trk.get(name)
    if tr is None:
        trk[name] = tr = Track([vmd.BoneKey(name, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))])
    idx = np.flatnonzero(frames_mask)
    if not len(idx):
        return 0
    # the frames around the moved ones are held to their present values so a new key does not bend them
    lo, hi = max(0, idx[0] - 1), min(len(frames) - 1, idx[-1] + 1)
    span = np.arange(lo, hi + 1)
    _, now = tr.sample(frames[span])
    want = now.copy()
    sel = frames_mask[span]
    want[sel] = q[span][sel]
    return tr.fit(frames[span], want_rot=want, tol_deg=TOL_DEG)


def arm_points(body, side, ap, radii, hand):
    """the arm's test points [F, n, 3], their radii [n], the share along their segment [n] and the segment [n] (0 upper
    arm, 1 forearm, 2 hand)"""
    S, E, W = ap[side + "腕"][0], ap[side + "ひじ"][0], ap[side + "手首"][0]
    tip = hand[2]["tip"]
    pts, rad, share, seg = [], [], [], []
    for n, (a, b, r) in enumerate(((S, E, radii[0]), (E, W, radii[1]), (W, tip, radii[2]))):
        for t in np.linspace(0.0, 1.0, 7):
            pts.append(a + t * (b - a))
            rad.append(r)
            share.append(t)
            seg.append(n)
    return np.stack(pts, axis=1), np.array(rad), np.array(share), np.array(seg)


def penetration(tgt, side, ap, hand, parts, contact_w):
    """per frame the deepest the arm goes into a part (units, >= 0) and the pushes that take the wrist and the elbow out
    (world [F, 3]: the deepest point's push, by its share of the lever)"""
    surf = surfaces(tgt)
    radii = arm_radii(tgt, side)
    P, rad, share, seg = arm_points(tgt, side, ap, radii, hand)
    F = P.shape[0]
    deepest = np.zeros(F)
    best_w = np.zeros(F)
    best_e = np.zeros(F)
    push_w = np.zeros((F, 3))
    push_e = np.zeros((F, 3))
    lever_w = np.where(seg == 0, 0.0, np.where(seg == 1, share, 1.0))
    lever_e = np.where(seg == 0, share, np.where(seg == 1, 1.0 - share, 0.0))
    for part, (pos, rot) in parts.items():
        s = surf[part]
        local = qrot(qconj(rot)[:, None, :], P - pos[:, None, :])
        pen = rad[None, :] - s.sdf(local)
        if part in ("chest", "belly"):
            pen[:, (seg == 0) & (share < SHOULDER_SKIP)] = 0.0
        if part in contact_w:
            pen[:, seg == 2] *= (contact_w[part] < 0.3)[:, None]
        pen = np.maximum(pen, 0.0)
        if not np.any(pen > 0):
            continue
        deepest = np.maximum(deepest, pen.max(axis=1))
        g = qrot(rot[:, None, :], s.grad(local))
        vec = (pen + CLEAR_MARGIN * (pen > 0))[:, :, None] * g
        for lever, best, push in ((lever_w, best_w, push_w), (lever_e, best_e, push_e)):
            score = pen * lever[None, :]
            j = np.argmax(score, axis=1)
            sc = score[np.arange(F), j]
            take = sc > best
            push[take] = vec[np.arange(F), j][take] * lever[j][take][:, None]
            best[take] = sc[take]
    return deepest, push_w, push_e


def clear_arms(tgt, trk, frames, contact_weights, parts, log):
    """push the target's arms out of its head, trunk, hips and thighs (arm IK on the frames that go in; the change eases
    in and out over EASE frames); returns the report per side"""
    F = len(frames)
    rep = {}
    for side in SIDES:
        if not all(tgt.has(n) for n in arm_names(side)):
            continue
        cw = {}
        before = None
        moved_any = np.zeros(F, bool)
        for rnd in range(CLEAR_ROUNDS):
            ap = arm_pose(tgt, trk, frames, side)
            hand = hand_world(tgt, trk, frames, side)
            if not cw:
                cw = contact_weights.get(side, {})
            deep, pw, pe = penetration(tgt, side, ap, hand, parts, cw)
            if before is None:
                before = deep.copy()
            bad = deep > 0.005
            if not np.any(bad):
                break
            # ease the pushes in and out
            which, weight = ease_weights(F, runs(bad))
            pw2 = np.zeros_like(pw)
            pe2 = np.zeros_like(pe)
            for n, (a, b) in enumerate(runs(bad)):
                m = which == n
                peak_w = pw[a:b + 1][np.argmax(np.linalg.norm(pw[a:b + 1], axis=1))]
                peak_e = pe[a:b + 1][np.argmax(np.linalg.norm(pe[a:b + 1], axis=1))]
                inside = np.zeros(F, bool)
                inside[a:b + 1] = True
                pw2[m & inside] = pw[m & inside]
                pe2[m & inside] = pe[m & inside]
                pw2[m & ~inside] = weight[m & ~inside, None] * peak_w
                pe2[m & ~inside] = weight[m & ~inside, None] * peak_e
            moved = weight > 0
            moved_any |= moved
            S, E, W = ap[side + "腕"][0], ap[side + "ひじ"][0], ap[side + "手首"][0]
            Es, Ws = arm_ik(S, E, W, W + pw2, pole=E + pe2)
            Es = np.where(moved[:, None], Es, E)
            Ws = np.where(moved[:, None], Ws, W)
            loc = arm_locals(tgt, trk, frames, side, Es, Ws, hand[1])
            for name, q in loc.items():
                _fit_turns(trk, name, frames, q, moved)
        ap = arm_pose(tgt, trk, frames, side)
        hand = hand_world(tgt, trk, frames, side)
        after, _, _ = penetration(tgt, side, ap, hand, parts, cw)
        rep[side] = {"in_before_frames": int(np.sum(before > 0.005)) if before is not None else 0,
                     "in_after_frames": int(np.sum(after > 0.005)), "deepest_before_cm": round(float(before.max()) * UNIT_CM, 3) if before is not None else 0.0,
                     "deepest_after_cm": round(float(after.max()) * UNIT_CM, 3), "moved_frames": int(moved_any.sum())}
        log("clear %s: frames in %d -> %d, deepest %.2f -> %.2f cm" % (side, rep[side]["in_before_frames"], rep[side]["in_after_frames"],
                                                                    rep[side]["deepest_before_cm"], rep[side]["deepest_after_cm"]))
    return rep


# ---- the mapping ---------------------------------------------------------------------------------------------------------

def scale_of(src, tgt):
    """s: the target's hip height over its ankles over the source's (rest, the mean of the sides)"""
    return float(np.mean([tgt.hip_height(s) for s in SIDES]) / np.mean([src.hip_height(s) for s in SIDES]))


def stance_shift(src, tgt, s):
    """side -> the foot IK's sideways shift (units, x) that keeps the source's leg spread at rest offsets"""
    out = {}
    for side in SIDES:
        a_s = src.rest(side + "足首")[0] - src.rest(side + "足")[0]
        a_t = tgt.rest(side + "足首")[0] - tgt.rest(side + "足")[0]
        out[side] = float(s * a_s - a_t)
    return out


def corrections(src, tgt):
    """target bone name -> C (the turn taking the target's rest direction onto the source's) for CORRECTED bones both
    bodies have"""
    out = {}
    for side in SIDES:
        for bone, (a, b) in CORRECTED.items():
            name = side + bone
            ends = [side + a, side + b]
            if not (tgt.has(name) and all(src.has(e) and tgt.has(e) for e in ends)):
                continue
            out[name] = qbetween(tgt.direction(*ends), src.direction(*ends))
    return out


def effective_corrections(tgt, corr):
    """target bone index -> its C: its own (CORRECTED), else its parent's (a finger turns with its hand, a twist helper with
    its arm), else identity"""
    out = {}

    def of(k, depth=0):
        if k in out:
            return out[k]
        if depth > len(tgt.model.bones):
            raise ValueError("the bones of %r go round in a loop" % tgt.model.bones[k].name)
        name = tgt.model.bones[k].name
        if name in corr:
            out[k] = corr[name]
        else:
            p = tgt.parent(k)
            out[k] = IDENTITY if p is None else of(p, depth + 1)
        return out[k]
    for b in tgt.model.bones:
        of(b.index)
    return out


def map_rotation(q_applied, cp, cb):
    """L_T = C_p^-1 L_S C_b (as applied)"""
    return qnorm(qmul(qmul(qconj(cp), np.asarray(q_applied, dtype=np.float64)), cb))


@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    arrays: dict = field(default_factory=dict)


def params_default():
    return {"feet": True, "hands": True, "clear": True, "stance": "legs"}


def pure_keys(motion, src, tgt, s, shift, corr):
    """the motion's bone keys mapped (see the module's doc): a list of new BoneKeys and the names the target lacks.  A
    corrected bone without keys gets one on frame 0 (its rest turned by C_p^-1 C_b) when that is not the identity."""
    missing = set()
    out = []
    ceff = effective_corrections(tgt, corr)

    def turns(name):
        k = tgt.i(name)
        p = tgt.parent(k)
        return (IDENTITY if p is None else ceff[p]), ceff[k]
    for k in motion.bones:
        name = k.name
        if not tgt.has(name):
            missing.add(name)
            out.append(vmd.BoneKey(k.name, k.frame, tuple(k.position), tuple(k.rotation), k.interpolation, raw_name=k.raw_name))
            continue
        cp, cb = turns(name)
        rot = tuple(k.rotation)
        if not (np.allclose(cp, IDENTITY) and np.allclose(cb, IDENTITY)):
            src_q = fk.applied(fk.normalized(k.rotation))
            q = map_rotation(src_q, cp, cb)
            if float(np.dot(q, src_q)) < 0.0:
                q = -q
            rot = fk.stored(tuple(float(v) for v in q))
        pos = tuple(float(v) * s for v in k.position)
        if name.endswith("足ＩＫ") and name[0] in shift:
            pos = (pos[0] + shift[name[0]], pos[1], pos[2])
        out.append(vmd.BoneKey(k.name, k.frame, pos, rot, k.interpolation, raw_name=k.raw_name))
    keyed = {k.name for k in motion.bones}
    added = []
    for name in sorted(corr):
        if name in keyed:
            continue
        cp, cb = turns(name)
        q = map_rotation(IDENTITY, cp, cb)
        if qangle(q) > 1e-9:
            out.append(vmd.BoneKey(name, 0, (0.0, 0.0, 0.0), fk.stored(tuple(float(v) for v in q))))
            added.append(name)
    return out, sorted(missing), added


def layer(motion, src, tgt, params=None, log=None):
    """the dance moved onto the target body (Result: motion, report)"""
    log = log or (lambda *_: None)
    p = params_default()
    p.update(params or {})
    t0 = time.time()
    s = scale_of(src, tgt)
    shift = stance_shift(src, tgt, s) if p["stance"] == "legs" else {side: 0.0 for side in SIDES}
    corr = corrections(src, tgt)
    keys, missing, added = pure_keys(motion, src, tgt, s, shift, corr)
    named = {k.name for k in keys}
    for side in SIDES:                          # a foot IK without keys still takes its stance shift
        name = side + "足ＩＫ"
        if shift[side] != 0.0 and name not in named and tgt.has(name):
            keys.append(vmd.BoneKey(name, 0, (shift[side], 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
            added.append(name)
    report = {"params": p, "scale": s, "stance_shift": shift, "missing_bones": missing, "added_rest_keys": added,
              "corrections_deg": {n: round(math.degrees(float(qangle(c))), 4) for n, c in sorted(corr.items())},
              "source": src.name, "target": tgt.name, "keys_in": len(motion.bones)}
    if (p["feet"] or p["hands"] or p["clear"]) and motion.bones:
        lost = set(missing)
        passing = [k for k in keys if k.name in lost]
        trk_t = tracks_of([k for k in keys if k.name not in lost])
        trk_s = tracks_of(motion.bones)
        frames = np.arange(0, max(k.frame for k in motion.bones) + 1)
        report["duplicate_keys_dropped"] = int(len(keys) - len(passing) - sum(len(t) for t in trk_t.values()))
        if p["feet"]:
            report["feet"] = fix_feet(src, tgt, leg_pose(src, trk_s, frames), trk_t, frames, p, log)
        if p["hands"] or p["clear"]:
            report["hands"] = fix_hands(src, tgt, trk_s, trk_t, frames, p, log)
        keys = [k for t in trk_t.values() for k in t.keys()] + passing
    out = vmd.Motion(model_name=motion.model_name, bones=keys, morphs=list(motion.morphs), cameras=list(motion.cameras),
                     lights=list(motion.lights), shadows=list(motion.shadows), show_iks=list(motion.show_iks))
    report["keys_out"] = len(out.bones)
    report["seconds"] = round(time.time() - t0, 2)
    return Result(out, report)
