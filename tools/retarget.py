"""Move the traced dance from the body it was traced on (the source) onto another body (the target, Sour's Rin), keeping
what the source body did: the arms point the same way although the two bodies rest them at other angles, the centre and
the feet move by the legs' ratio and the legs keep their spread, a foot on the floor stays put and on the floor, a hand
that touches the head, the trunk, the hips or the other hand still touches it, and the arms stay out of the body.

    python tools/retarget.py run DANCE.vmd SOURCE TARGET.pmx OUT.vmd [--report r.json]
                                 [--no-feet] [--no-hands] [--no-clear] [--stance legs|offsets]
    python tools/retarget.py fit DANCE.vmd --candidates A.pmx B.pmd ... --out fit.json

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

Then the corrections, measured on both bodies frame by frame (fix_feet, fix_hands, clear_arms; the hips are never moved):

* feet: where the source's foot stands still on the floor (a plant) the target's takes the source's foot's world turn
  (a flat foot level across), its toe or heel pitched (a flat foot's ankle up or down) until the shoe's lowest vertex
  is on the floor and its touching point held; where the source's foot turns on the floor (its slowest sole point slow)
  and the other foot does not stand, the target's shoe is put on the floor the same way and turns in place on that
  point (a foot carried low and fast is a step, left as mapped, its shoe as high over the floor as the source's); the
  hold along the floor changes only while the foot is off the floor.
* hands: a hand near a part of the source's body (head, chest, belly, hips, thighs, within NEAR) is put at the same
  place of the target's part (scaled by the parts' sizes), and the two hands as far apart as the shoulders' ratio says;
  the hand's points are the palm and the middle finger's tip as the dance's finger keys bend them.
* the arms are pushed out of the target's head, ribbon, trunk, hips and thighs (the upper arm only out of the head):
  what the upper arm goes into by turning the arm at the shoulder, the forearm and the hand by moving the wrist; a
  hand touching a part in the source is not pushed off it, one only near it comes no closer than the source's hand
  does (scaled); a touching hand stays where it is when turning the elbow round the shoulder-wrist line clears the
  upper arm.  The hair and the skirt are measured, not pushed (the physics; a bob's hull reaches the cheeks).
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
        out = cls(model, LI.ik_limits(doc), P, main, name, N)
        out.doc = doc
        return out

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

# part -> (the bone it rides on, the bones whose vertices make it, whether it is soft).  A soft part is measured but the
# arms are not pushed out of it: the skirt (MMD's physics moves it) and the hair (Rin's 髮親: the hull of a bob reaches
# down beside the cheeks and the neck, where a hand on the face belongs).  The head is the face and skull (頭's own
# vertices); the ribbon on top of Rin's head is its own part (its hull with the head's would fill the space between them).
PARTS = {"head": ("頭", ("頭",), False), "hair": ("頭", ("髮親", "髪親"), True), "ribbon": ("頭", ("リボン親",), False),
         "chest": ("上半身2", ("上半身2", "胸椎上部", "胸リボン親"), False), "belly": ("上半身", ("上半身", "腰椎上部"), False),
         "hips": ("下半身", ("下半身", "腰"), False), "thigh_左": ("左足", ("左足", "左足D"), False),
         "thigh_右": ("右足", ("右足", "右足D"), False), "skirt": ("下半身", (), True)}
SKIRT_WORDS = ("スカート", "ｽｶｰﾄ")
# parts that take the vertices of the bones under their bones too: the ribbon's loops and tails hang on 左リボン1..3 and
# 右リボン1..3 under リボン親 (Sour's Rin: 299 of its 422 vertices; with リボン親's own 123 alone the part was its knot and
# a finger in a loop went unseen), the hair's strands on the 前髮・後髮 chains under 髮親
TREE_PARTS = ("ribbon", "hair")


def bone_tree(body, roots):
    """the indices of the bones `roots` and every bone under them"""
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


def _directions(n=98):
    """n unit vectors spread over the sphere (a golden spiral)"""
    i = np.arange(n) + 0.5
    y = 1.0 - 2.0 * i / n
    r = np.sqrt(1.0 - y * y)
    a = np.pi * (3.0 - np.sqrt(5.0)) * i
    return np.stack([r * np.cos(a), y, r * np.sin(a)], axis=1)


DIRECTIONS = _directions()


class Surface:
    """a part as the convex polytope its vertices span along DIRECTIONS (a k-DOP: the intersection of the half-spaces
    u . x <= max over the vertices of u . v), in the riding bone's frame relative to its rest position.  The signed
    distance is the largest of u . x - d_u: exact inside (negative: how deep), a lower bound outside (exact next to a
    face).  Thin or double-sided meshes (hair, ribbons, clothes) do not change which side of a part a point is on."""

    def __init__(self, points, normals=None):
        P = np.asarray(points, dtype=np.float64)
        self.dirs = DIRECTIONS
        self.d = np.max(P @ self.dirs.T, axis=0)
        self.box_center = 0.5 * (P.min(axis=0) + P.max(axis=0))
        self.box_half = np.maximum(0.5 * (P.max(axis=0) - P.min(axis=0)), 1e-3)
        self.count = len(P)

    def _planes(self, q):
        return np.asarray(q, dtype=np.float64) @ self.dirs.T - self.d

    def sdf(self, q):
        return self._planes(q).max(axis=-1)

    def grad(self, q):
        return self.dirs[np.argmax(self._planes(q), axis=-1)]

    def closest(self, q):
        """the point of the surface nearest q (along the face q is past or nearest inside)"""
        q = np.asarray(q, dtype=np.float64)
        return q - self.sdf(q)[..., None] * self.grad(q)


def part_vertices(body, part):
    """(points rel. the riding bone's rest position, normals) of a part, or None"""
    ride, bones, _ = PARTS[part]
    if not body.has(ride) or not len(body.vertices):
        return None
    if part == "skirt":
        idx = [b.index for b in body.model.bones if any(w in b.name for w in SKIRT_WORDS)]
    else:
        idx = [body.i(n) for n in bones if body.has(n)]
        if part in TREE_PARTS:
            idx = bone_tree(body, idx)
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


def soft(part):
    return PARTS[part][2]


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
# a foot on the floor that does not stand still but turns on it (on its ball or toe: the rest of the foot sweeps round
# faster than STILL; the trace leaves such a foot up to 1.7 cm over the floor, the song's 59.2 s, and lets it skid: its
# slowest sole point 15-60 cm/s while it turns 260-1000 degrees a second about a point 3-6 cm off it): its lowest sole
# point this close to the floor, rising or falling slower than TOUCH_RISE, and nearly still (the sole's slowest point
# slower than TOUCH_SPEED) or turning about a point near it (TURN_MIN, TURN_NEAR), for TOUCH_MIN frames, while the other
# foot does not stand.  The target's foot is put on the floor (the foot's pitch, the ankle) and turns in place: the
# point of the sole's line the source's foot turns on (the slowest over the run) is held where it is.  (A foot carried
# low and fast is a step, not on the floor: pressed onto it, the song's 198.9-199.3 s dragged the right shoe 65 cm along
# the floor; beside a standing foot a low moving foot is a small step or a drag.)
TOUCH_FLOOR = 0.25              # units (2 cm)
TOUCH_RISE = 0.03               # units a frame (7 cm/s)
TOUCH_SPEED = 20.0 / UNIT_CM / FPS     # units a frame (20 cm/s)
TURN_MIN = math.radians(60.0) / FPS    # radians a frame (60 degrees a second)
TURN_NEAR = 18.0 / UNIT_CM             # units (18 cm): how far the turn's centre may lie from the sole's slowest point
                                       # (the song's 127.9 s right foot turns 320-460 degrees a second about a point 15-17 cm
                                       # off its sole's slowest one; the step carried at 199 s turns about one 30 cm off)
LINE_T = np.linspace(-0.3, 1.0, 27)    # the sole's line: shares of the way from the heel point to the toe point
TOUCH_MIN = 3
# the hold along the floor (a standing or turning foot's point kept where it is) changes only while the target's shoe
# is off the floor (its lowest vertex over AIR_H, the floor of main's contact_check, with the turn and the lift as they
# ease): taken in the air before a span, given back in the air after it (over HOLD_AIR such frames when the gap is long);
# eased along the floor the song's feet slid 1.5 m in the 3 frames each side, and read off the source's foot the shoe
# was still on the floor while the source's lifted (the pitch and the lift easing out) and slid there
AIR_H = 0.05                    # units (4 mm)
HOLD_AIR = 6                    # frames
CLEAR_TO = 0.075                # units (6 mm): a carried shoe is kept as high over the floor as the source's, up to this
                                # (off the floor of main's contact_check, 4 mm; not higher: the turns' feet stay low)
TOUCH_PITCH_MAX = 20.0          # degrees: the most a foot's pitch is changed from the source's to reach the floor, on the
                                # floor moving (the ankle comes down the rest, within FLAT_LIFT_MAX) or standing on its toe
                                # or heel: a foot is not flicked (the song's 86.07 s pitched 50 degrees for one frame without
                                # it; a toe stand at 137.77 s 51 degrees, its toe on the floor again pitched near vertical)
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
        zf = float(low[:, 2].min())
        front_x = float(np.mean(low[low[:, 2] < zf + 0.0125][:, 0]))      # the front end's middle (a square toe: not a corner)
        back = low[np.argmax(low[:, 2])]
        heel = np.array([ankle[0], floor, back[2]])
        tip = np.array([front_x, floor, zf])
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


def sole_shell(body, side, cap=256, mesh=False):
    """the shoe's vertices within 2 cm of its lowest point (the sole as it is, a raised toe and heel included), relative
    to the ankle at rest, at most `cap` of them spread along the foot; a body without a shoe mesh (or one whose feet are
    read from the bones, unless `mesh`): its sole points"""
    ankle = body.rest(side + "足首")
    idx = [body.i(side + n) for n in SHOE if body.has(side + n)]
    use = len(body.vertices) and (mesh or getattr(body, "foot_from_mesh", True))
    m = np.isin(body.main_bone, idx) if use else np.zeros(0, bool)
    if m.sum() >= 20:
        P = body.vertices[m]
        low = P[P[:, 1] < float(P[:, 1].min()) + 0.25]
        low = low[np.argsort(low[:, 2], kind="stable")]
        if len(low) > cap:
            low = low[np.unique(np.linspace(0, len(low) - 1, cap).round().astype(int))]
        return low - ankle
    pts, _ = sole_points(body, side)
    return np.stack([pts[k] for k in ("heel", "ball", "toe")])


def foot_pitch(q_foot):
    """degrees the foot's front (-Z turned by the foot) points below level (+ toe down)"""
    fwd = qrot(q_foot, np.array([0.0, 0.0, -1.0]))
    return np.degrees(np.arcsin(np.clip(-fwd[..., 1], -1.0, 1.0)))


def unroll(q_foot):
    """(the foot's world turn turned about its own front until its side axis is level, the roll taken out in degrees):
    its heading and pitch kept, the sole level across"""
    fwd = unit(qrot(q_foot, np.array([0.0, 0.0, -1.0])))
    side = qrot(q_foot, np.array([1.0, 0.0, 0.0]))
    up = qrot(q_foot, np.array([0.0, 1.0, 0.0]))
    phi = np.arctan2(side[..., 1], up[..., 1])
    return qnorm(qmul(qaxis(fwd, phi), q_foot)), np.degrees(phi)


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
    low = H.min(axis=1)
    rise = np.zeros(len(low))
    if len(low) > 2:
        rise[1:-1] = 0.5 * np.abs(low[2:] - low[:-2])
        rise[0], rise[-1] = abs(low[1] - low[0]), abs(low[-1] - low[-2])
    # turning on the floor or nearly still (not carried along it): the slowest point of the sole's line (LINE_T, from
    # behind the heel point to the toe point) slower than TOUCH_SPEED, or the foot turning faster than TURN_MIN about a
    # point within TURN_NEAR of that slowest point (its speed over the turn rate)
    line = np.stack([pts["heel"] + t * (pts["toe"] - pts["heel"]) for t in LINE_T])
    Wl = A[:, None, :] + qrot(Q[:, None, :], line[None, :, :])
    vl = np.zeros(Wl.shape[:2])
    vl[1:] = np.linalg.norm(np.diff(Wl[:, :, [0, 2]], axis=0), axis=2)
    vl = 0.5 * (vl + np.concatenate([vl[1:], vl[-1:]], axis=0)) if len(vl) else vl
    fwd = qrot(Q, np.array([0.0, 0.0, -1.0]))
    yaw = np.unwrap(np.arctan2(fwd[:, 0], -fwd[:, 2]))
    turn = np.zeros(len(yaw))
    if len(yaw) > 2:
        turn[1:-1] = 0.5 * np.abs(yaw[2:] - yaw[:-2])
        turn[0], turn[-1] = abs(yaw[1] - yaw[0]), abs(yaw[-1] - yaw[-2])
    slowest = vl.min(axis=1) if len(vl) else np.zeros(0)
    turning = (turn > TURN_MIN) & (slowest < TURN_NEAR * turn)
    touch = (low < TOUCH_FLOOR) & (rise < TOUCH_RISE) & ((slowest < TOUCH_SPEED) | turning)
    return out, {"height": low, "pitch": pitch, "stand": stand, "touch": touch, "line_speed": vl}


def touches(F, spans, arrays, other_spans=()):
    """the runs of frames (TOUCH_MIN and longer) a source foot is on the floor without standing still, outside its
    plants and while the other foot does not stand (then this foot carries the body: turning on it; beside a standing foot
    a low moving foot is a small step or a drag, left as the mapping puts it): [(first, last)]"""
    planted = np.zeros(F, bool)
    for a, b, _ in spans:
        planted[a:b + 1] = True
    other = np.zeros(F, bool)
    for a, b, _ in other_spans:
        other[a:b + 1] = True
    return runs(arrays["touch"] & ~planted & ~other, TOUCH_MIN)


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


PITCH_ON_FLOOR = 0.0125         # units (1 mm): a point this close to the floor is on it (solve_pitch takes it as found)


def solve_pitch(A, Q, offset, floor, lo, hi, step=0.5):
    """per frame the pitch change (degrees, in lo..hi) nearest 0 that puts the point `offset` (rel. the ankle A, turned by
    the foot Q; or the lowest of the points `offset` [k, 3]) on the floor; where no pitch in the range reaches it, the one
    that brings it nearest.  Returns (change, the point's height above the floor left over)."""
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    off = np.asarray(offset, dtype=np.float64)
    n = len(A)
    if not n:
        return np.zeros(0), np.zeros(0)

    def height(d):
        R = qmul(pitch_turn(Q, d), Q)
        if off.ndim == 1:
            return A[:, 1] + qrot(R, off)[:, 1] - floor
        return A[:, 1] + np.min(qrot(R[:, None, :], off[None, :, :])[:, :, 1], axis=1) - floor
    steps = int(np.ceil(np.max(hi - lo) / step)) + 1
    grid = lo[:, None] + (hi - lo)[:, None] * np.linspace(0.0, 1.0, steps)[None, :]
    H = np.stack([height(grid[:, j]) for j in range(steps)], axis=1)
    best = np.full(n, np.nan)
    a_br = np.zeros(n)
    b_br = np.zeros(n)
    for j in range(steps - 1):              # the crossing nearest no change
        cross = (np.sign(H[:, j]) != np.sign(H[:, j + 1])) | (np.abs(H[:, j]) <= PITCH_ON_FLOOR)
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


def hold_offsets(F, spans, hold, edges, mapped, on_floor, src_on_floor, ease_air=HOLD_AIR):
    """the foot IK's offset along the floor [F, 2] (x, z): on a span's frames its hold (`hold`); between spans an offset
    that changes only on the frames the target's shoe is off the floor.  `edges`: per span, the hold against the mapped
    foot at its first and at its last frame; `mapped(n, f)`: where the mapping puts span n's point at frames f [k, 2].
    Out of a span and into the next, while the shoe is on the floor (`on_floor`): the foot moves as the mapping moves it
    (the offset kept) where the source's foot is on the floor too (`src_on_floor`), and stays where it is where the
    source's foot is already off it or not yet on it (the turn and the lift, easing, keep the shoe down a few frames
    longer); over the gap's frames off the floor the offset goes from what the last span left to what the next takes
    (over a long gap back to nothing in its first `ease_air` such frames and in again over its last ones).  Where a gap
    has no frame off the floor, the change is spread over the gap (it slides: listed).  Returns (offsets, the changes
    made along the floor [cm])"""
    H = np.zeros((F, 2))
    floor_moves = []
    order = sorted(range(len(spans)), key=lambda n: spans[n][0])
    bounds = [(n, spans[n][0], spans[n][1], edges[n][0], edges[n][1]) for n in order] + [(None, F, F - 1, np.zeros(2), np.zeros(2))]
    prev, prev_end, prev_off = None, -1, np.zeros(2)
    for n, a, b, o_in, o_out in bounds:
        g0, g1 = prev_end + 1, a - 1
        if g1 >= g0:
            k = np.arange(g0, g1 + 1)
            air = ~on_floor[k]
            if not air.any():
                t = (np.arange(len(k)) + 1.0) / (len(k) + 1.0)
                H[k] = prev_off + (o_in - prev_off) * smoothstep(t)[:, None]
                if prev is not None and n is not None and np.linalg.norm(o_in - prev_off) > 1e-6:
                    floor_moves.append(float(np.linalg.norm(o_in - prev_off)) * UNIT_CM)
            else:
                first, last = int(np.argmax(air)), len(k) - 1 - int(np.argmax(air[::-1]))
                o = prev_off.copy()                       # out of the last span, the shoe still down
                if prev is not None and first > 0:
                    p = mapped(prev, np.arange(g0 - 1, g0 + first))
                    for i in range(first):
                        if not src_on_floor[k[i]]:
                            o = o - (p[i + 1] - p[i])
                        H[k[i]] = o
                out_off = o
                o = o_in.copy()                           # into the next span, the shoe already down
                if n is not None and last < len(k) - 1:
                    q = mapped(n, np.arange(g0 + last + 1, g1 + 2))
                    for j in range(len(k) - 1, last, -1):
                        jj = j - (last + 1)
                        if not src_on_floor[k[j]]:
                            o = o + (q[jj + 1] - q[jj])
                        H[k[j]] = o
                in_off = o
                mid = np.arange(first, last + 1)
                off = air[mid]
                n_air = int(off.sum())
                c = np.cumsum(off).astype(np.float64)
                if n_air < 2 * ease_air:
                    H[k[mid]] = out_off + (in_off - out_off) * smoothstep(c / n_air)[:, None]
                else:
                    go = smoothstep(np.clip(c / ease_air, 0.0, 1.0))
                    come = smoothstep(np.clip((c - (n_air - ease_air)) / ease_air, 0.0, 1.0))
                    H[k[mid]] = out_off * (1.0 - go)[:, None] + in_off * come[:, None]
        if n is not None:
            H[a:b + 1] = hold[a:b + 1]
        prev, prev_end, prev_off = n, b, o_out
    return H, floor_moves


def fix_feet(src, tgt, src_legs, tgt_trk, frames, params, log):
    """the target's foot keys for the source's plants (the foot IK's goal and turn, the ankle's key): the foot takes the
    source's foot's world turn (a foot flat on the floor stays flat, whatever MMD's toe IK would turn the target's foot
    by); a foot on its toe or heel is pitched further about its own side axis (the ankle where the mapping put it, by at
    most TOUCH_PITCH_MAX) until the shoe's lowest vertex (sole_shell) reaches the floor; a flat foot stands level across
    (the source's roll taken out: Hibikase's flat feet roll 7 degrees in the median, and with the sole's middle on the
    floor the edge was 3 mm under it in the median, 1.4 cm at most) and its ankle moves up or down (at most FLAT_LIFT_MAX)
    until the shoe is on the floor; the touching point is held still.  A foot that turns on the floor (touches) is put on
    the floor the same way and turns in place: the sole point it turns on is held.  The turn and the lift ease in and out
    over EASE frames; the hold along the floor changes only while the target's shoe is off the floor (hold_offsets), and
    while the turn eases the point held next is kept where the mapping puts it.  Off the spans a shoe the source carries
    over the floor (faster than TOUCH_SPEED) is carried at least as high (up to CLEAR_TO).  The hips are never lowered.
    Returns the report."""
    F = len(frames)
    rep = {}
    found = {side: plants(src, src_legs, side) for side in SIDES}
    on_floor = {side: touches(F, *found[side], found[[s for s in SIDES if s != side][0]][0]) for side in SIDES}
    names = ("heel", "ball", "toe")
    for rnd in range(FEET_ROUNDS):
        tgt_legs = leg_pose(tgt, tgt_trk, frames)
        for side in SIDES:
            spans, arrays = found[side]
            moving = on_floor[side]
            pts_t, floor_t = sole_points(tgt, side)
            shell_t = sole_shell(tgt, side)
            leg = tgt_legs[side]
            A, Q = leg["ankle"], leg["q_foot"]
            Qs = src_legs[side]["q_foot"]
            all_spans = [(a, b) for a, b, _ in spans] + list(moving)
            which, weight = ease_weights(F, all_spans)
            want_turn = Q.copy()
            lift = np.zeros(F)
            hold = np.zeros((F, 2))
            d_all = np.zeros(F)
            left_over = np.full(F, np.nan)
            kinds = {"flat": 0, "toe": 0, "heel": 0}
            turned_on = {k: 0 for k in names}
            roll_out = []
            points, edges = [], []

            def held_at(n, idx, Qn, point, a, b):
                # the point kept where it is over the span (the mean of where it would be), against the mapped foot at
                # the span's ends (the offset the hold along the floor takes in the air)
                C = A[idx] + qrot(Qn, point)
                inside = (idx >= a) & (idx <= b)
                lock = np.mean(C[inside][:, [0, 2]], axis=0) if np.any(inside) else np.mean(C[:, [0, 2]], axis=0)
                hold[idx[inside]] = lock - C[inside][:, [0, 2]]
                C0a, C0b = (A[f] + qrot(Q[f], point) for f in (a, b))
                points.append(point)
                edges.append((lock - C0a[[0, 2]], lock - C0b[[0, 2]]))

            for n, (a, b, kind) in enumerate(spans):
                kinds[kind] += 1
                idx = np.flatnonzero(which == n)
                point = pts_t["toe" if kind == "toe" else ("heel" if kind == "heel" else "ball")]
                if not len(idx):
                    points.append(point)
                    edges.append((np.zeros(2), np.zeros(2)))
                    continue
                base = Qs[idx]
                p0 = foot_pitch(base)
                if kind == "flat":
                    # a flat foot stands level across (the trace's flat feet roll 7 degrees in the median, 21 at the 90 %
                    # point: on its edge the shoe stood 3 mm under the floor, lifted onto it the ankle stood over its
                    # rest height, which the analysis pack's a05 reads as a hovering foot)
                    base, rolled = unroll(base)
                    roll_out.append(np.abs(rolled[(idx >= a) & (idx <= b)]))
                    d = np.zeros(len(idx))
                    low = A[idx, 1] + np.min(qrot(base[:, None, :], shell_t[None, :, :])[:, :, 1], axis=1) - floor_t
                    up = np.clip(-low, -FLAT_LIFT_MAX, FLAT_LIFT_MAX)
                    left_over[idx] = low + up
                else:
                    if kind == "toe":
                        lo, hi = -np.maximum(p0, 0.0), MAX_PITCH_DEG - p0
                    else:
                        lo, hi = -MAX_PITCH_DEG - p0, -np.minimum(p0, 0.0)
                    lo, hi = np.maximum(lo, -TOUCH_PITCH_MAX), np.minimum(hi, TOUCH_PITCH_MAX)
                    d, rest_h = solve_pitch(A[idx], base, shell_t, floor_t, lo, hi)
                    up = np.zeros(len(idx))
                    left_over[idx] = rest_h
                Qn = qmul(pitch_turn(base, d), base)
                want_turn[idx] = Qn
                lift[idx] = up
                d_all[idx] = d
                held_at(n, idx, Qn, point, a, b)
            for n, (a, b) in enumerate(moving, start=len(spans)):
                # turning on the floor: the shoe's lowest point onto the floor by the foot's pitch (toe down or heel down
                # as the source's foot is, frame by frame; a flat foot level across), what the pitch leaves by the ankle
                # up or down (at most FLAT_LIFT_MAX); the sole point the source's foot turns on held where it is
                idx = np.flatnonzero(which == n)
                t_on = float(LINE_T[int(np.argmin(np.median(arrays["line_speed"][a:b + 1], axis=0)))])
                turned_on["heel" if t_on < 1 / 3 else ("toe" if t_on > 2 / 3 else "ball")] += 1
                point = pts_t["heel"] + t_on * (pts_t["toe"] - pts_t["heel"])
                if not len(idx):
                    points.append(point)
                    edges.append((np.zeros(2), np.zeros(2)))
                    continue
                base = Qs[idx].copy()
                p0 = foot_pitch(base)
                flat = np.abs(p0) <= PITCH_FLAT_DEG
                if np.any(flat):
                    base[flat] = unroll(base[flat])[0]
                d = np.zeros(len(idx))
                low = np.zeros(len(idx))
                for kind, sel in (("toe", p0 > PITCH_FLAT_DEG), ("heel", p0 < -PITCH_FLAT_DEG)):
                    if not np.any(sel):
                        continue
                    if kind == "toe":
                        lo, hi = -np.maximum(p0[sel], 0.0), MAX_PITCH_DEG - p0[sel]
                    else:
                        lo, hi = -MAX_PITCH_DEG - p0[sel], -np.minimum(p0[sel], 0.0)
                    lo, hi = np.maximum(lo, -TOUCH_PITCH_MAX), np.minimum(hi, TOUCH_PITCH_MAX)
                    d[sel], low[sel] = solve_pitch(A[idx[sel]], base[sel], shell_t, floor_t, lo, hi)
                if np.any(flat):
                    low[flat] = A[idx[flat], 1] + np.min(qrot(base[flat][:, None, :], shell_t[None, :, :])[:, :, 1], axis=1) - floor_t
                up = np.clip(-low, -FLAT_LIFT_MAX, FLAT_LIFT_MAX)
                left_over[idx] = low + up
                Qn = qmul(pitch_turn(base, d), base)
                want_turn[idx] = Qn
                lift[idx] = up
                d_all[idx] = d
                inside = (idx >= a) & (idx <= b)
                if np.median(np.abs(p0[inside])) > PITCH_FLAT_DEG:
                    # on its toe or heel the shoe touches the floor there, wherever the source's foot turned: the middle
                    # of the shoe's vertices within 1 mm of its lowest, over the run (else that part sweeps round)
                    y = qrot(Qn[inside][:, None, :], shell_t[None, :, :])[:, :, 1]
                    touching = y <= y.min(axis=1, keepdims=True) + PITCH_ON_FLOOR
                    centres = (touching[:, :, None] * shell_t[None, :, :]).sum(axis=1) / touching.sum(axis=1)[:, None]
                    point = np.median(centres, axis=0)
                held_at(n, idx, Qn, point, a, b)
            in_span = np.zeros(F, bool)
            for a, b in all_spans:
                in_span[a:b + 1] = True
            # off the spans a shoe the source carries over the floor (its sole's slowest point faster than TOUCH_SPEED)
            # is carried at least as high, up to CLEAR_TO (its shoe, from its mesh: the mapping scales the heights by the
            # legs' ratio and the shoes differ, and the song's carried feet came down onto the floor and slid along it
            # while the source's shoe stayed over it; a slower foot, standing or turning, is left to the spans)
            Qw = slerp_n(Q, want_turn, weight)
            low_now = A[:, 1] + weight * lift + np.min(qrot(Qw[:, None, :], shell_t[None, :, :])[:, :, 1], axis=1) - floor_t
            shell_s = sole_shell(src, side, mesh=True)
            src_low = (src_legs[side]["ankle"][:, 1] + np.min(qrot(Qs[:, None, :], shell_s[None, :, :])[:, :, 1], axis=1)
                       - float(src.rest(side + "足首")[1] + shell_s[:, 1].min()))
            clear = np.clip(np.minimum(src_low, CLEAR_TO) - low_now, 0.0, CLEAR_TO) * (1.0 - weight)
            clear[arrays["line_speed"].min(axis=1) < TOUCH_SPEED] = 0.0
            shoe_low = low_now + clear
            # along the floor: the holds, and between them an offset that changes only while the shoe is off the floor
            # (as the turn and the lift leave it, easing)
            H, floor_moves = hold_offsets(F, all_spans, hold, edges, lambda n, f: (A[f] + qrot(Q[f], points[n]))[:, [0, 2]],
                                          shoe_low <= AIR_H, arrays["height"] <= AIR_H)
            # while the turn eases in or out (off a span's frames) the point the foot stands on next or stood on last
            # stays where the mapping puts it plus the offset: the turn is taken about that point, not about the ankle
            easing = np.flatnonzero((weight > 0) & ~in_span)
            if len(easing):
                pk = np.stack([points[k] for k in which[easing]])
                Qw = slerp_n(Q[easing], want_turn[easing], weight[easing])
                H[easing] += (qrot(Q[easing], pk) - qrot(Qw, pk))[:, [0, 2]]
            shift = np.zeros((F, 3))
            shift[:, 0], shift[:, 2] = H[:, 0], H[:, 1]
            shift[:, 1] = weight * lift + clear
            moved = np.flatnonzero((weight > 0) | (np.abs(H).max(axis=1) > 1e-7) | (clear > 1e-7))
            r = rep.setdefault(side, {"plants": len(spans), "kinds": kinds, "plant_frames": int(sum(b - a + 1 for a, b, _ in spans)),
                                      "on_floor_moving": len(moving), "on_floor_moving_frames": int(sum(b - a + 1 for a, b in moving)),
                                      "turned_on": turned_on, "keys_added": 0})
            if len(moved):
                w = weight[moved]
                # the foot IK: its world turn towards the wanted foot turn, its goal shifted (both in its parent's frame)
                ik = side + "足ＩＫ"
                tr = tgt_trk.get(ik)
                if tr is None:
                    tgt_trk[ik] = tr = Track([vmd.BoneKey(ik, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))])
                par = tgt.model.bones[tgt.i(ik)].parent
                pname = tgt.model.bones[par].name if par is not None else None
                Wp = world_pose(tgt, tgt_trk, frames, [pname])[pname][1] if pname else np.tile(IDENTITY, (F, 1))
                pos, rot = tr.sample(frames)
                Wik = qmul(Wp, rot)
                new_ik = qmul(qconj(Wp[moved]), slerp_n(Wik[moved], want_turn[moved], w))
                new_pos = pos[moved] + qrot(qconj(Wp[moved]), shift[moved])
                added = tr.fit(frames[moved], want_rot=new_ik, want_pos=new_pos, tol_deg=0.25, tol_pos=0.005)
                # the ankle's key: the foot's world turn through the solved shin (the toe IK then has nothing to turn)
                ank = side + "足首"
                tr2 = tgt_trk.get(ank)
                if tr2 is None:
                    tgt_trk[ank] = tr2 = Track([vmd.BoneKey(ank, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))])
                _, krot = tr2.sample(frames)
                want_key = qmul(qconj(leg["q_shin"][moved]), want_turn[moved])
                new_key = slerp_n(krot[moved], want_key, w)
                added += tr2.fit(frames[moved], want_rot=new_key, tol_deg=0.25)
                r["keys_added"] += added
            if rnd == 0:
                full = weight >= 1.0
                r["pitch_change_deg"] = _quant(np.abs(d_all[full]))
                r["shift_cm"] = _quant(np.linalg.norm(shift[full], axis=1) * UNIT_CM)
                r["turn_change_deg"] = _quant(np.degrees(qangle(qmul(qconj(Q[full]), want_turn[full]))))
                r["flat_roll_removed_deg"] = _quant(np.concatenate(roll_out)) if roll_out else None
                r["hold_cm"] = _quant(np.linalg.norm(hold[in_span], axis=1) * UNIT_CM)
                r["off_span_offset_cm"] = _quant(np.linalg.norm(H[~in_span], axis=1) * UNIT_CM)
                r["gaps_moved_on_the_floor"] = len(floor_moves)
                r["gaps_moved_on_the_floor_cm"] = _quant(floor_moves)
                r["clearance_frames"] = int(np.sum(clear > 1e-4))
                r["clearance_cm"] = _quant(clear[clear > 1e-4] * UNIT_CM)
            inside_toe = np.isin(which, [n for n, s in enumerate(spans) if s[2] != "flat"]) & (weight >= 1.0)
            r["toe_left_over_cm"] = _quant(np.abs(left_over[inside_toe & ~np.isnan(left_over)]) * UNIT_CM)
            r["toe_unreached_frames"] = int(np.sum(inside_toe & (np.abs(np.nan_to_num(left_over)) > 0.0125)))
            inside_moving = (which >= len(spans)) & (weight >= 1.0)
            r["on_floor_moving_left_over_cm"] = _quant(np.abs(left_over[inside_moving & ~np.isnan(left_over)]) * UNIT_CM)
            log("feet %s round %d: %d plants (%s), %d turning on the floor (on %s), %d keys added" % (
                side, rnd, len(spans), kinds, len(moving), turned_on, r["keys_added"]))
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
TOUCH_BAND = 0.08               # units (6 mm): past TOUCH, a hand on a part is tested against it by this much more
CLEAR_ROUNDS = 4
CLEAR_MARGIN = 0.02             # units: the arm is pushed this much past the surface
CLEAR_TOL = 0.005               # units: an arm this little into a part is left as it is
ELBOW_SHARE = 0.25              # the forearm's first share counts with the upper arm (cleared by turning the arm at the shoulder)
HOLD_FROM = 0.6                 # the relation's weight from which the clearance keeps the hand where it is (1 at a touch)
SHOULDER_SKIP = 0.5             # the upper arm's half by the shoulder is not tested against the head (the shoulder is under it)
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
    """the arm's joints the IK sets (the twist bones between them, when a body has them, ride along)"""
    return [side + n for n in ("腕", "ひじ", "手首")]


def arm_pose(body, trk, frames, side):
    return world_pose(body, trk, frames, arm_names(side))


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
    plane turned with it (the elbow a hinge) and the hand's world turn `hand_turn`.  The bones between them (腕捩, 手捩
    when the body has them) keep their keys and ride along."""
    up, el, hd = arm_names(side)
    pname = {n: body.model.bones[body.model.bones[body.i(n)].parent].name for n in (up, el, hd)}
    wp = world_pose(body, trk, frames, sorted({up, el, hd} | set(pname.values())))
    S, Rup = wp[up]
    E, Rel = wp[el]
    W = wp[hd][0]
    d0, d1 = unit(E - S), unit(Es - S)
    f0, f1 = W - E, Ws - Es
    n0, n1 = np.cross(d0, f0), np.cross(d1, f1)
    straight = (np.linalg.norm(n0, axis=1) < 1e-4 * np.linalg.norm(f0, axis=1)) | (np.linalg.norm(n1, axis=1) < 1e-4 * np.linalg.norm(f1, axis=1))
    n0 = unit(n0 - np.sum(n0 * d0, axis=1)[:, None] * d0)
    n1 = unit(n1 - np.sum(n1 * d1, axis=1)[:, None] * d1)
    turn_up = frame_turn(d0, n0, d1, n1)
    turn_up = np.where(straight[:, None], qbetween(d0, d1), turn_up)
    turn_fo = qbetween(qrot(turn_up, f0), f1)
    turn_el = qmul(turn_fo, turn_up)
    Rup2 = qmul(turn_up, Rup)
    Rel2 = qmul(turn_el, Rel)
    par_el = qmul(turn_up, wp[pname[el]][1])          # what lies between the upper arm and the elbow turns with the arm
    par_hd = qmul(turn_el, wp[pname[hd]][1])          # and what lies between the elbow and the hand with the forearm
    return {up: qnorm(qmul(qconj(wp[pname[up]][1]), Rup2)), el: qnorm(qmul(qconj(par_el), Rel2)),
            hd: qnorm(qmul(qconj(par_hd), hand_turn))}


def hand_world(body, trk, frames, side):
    """(wrist position, hand turn, {point: world position}) of a hand: the palm's middle (half way to 中指１) and the
    middle finger's tip (中指先, or 中指３ past 中指２ by 0.6 of their bone) where the dance's finger keys put them (a
    finger bent at its knuckle is tested where it is); a body without the finger bones: hand_offsets turned with the hand"""
    names = [side + "手首"] + [side + n for n in ("中指１", "中指２", "中指３", "中指先") if body.has(side + n)]
    wp = world_pose(body, trk, frames, names)
    W, R = wp[side + "手首"]
    pts = {k: W + qrot(R, v) for k, v in hand_offsets(body, side).items()}
    if body.has(side + "中指１"):
        pts["palm"] = W + 0.5 * (wp[side + "中指１"][0] - W)
    if body.has(side + "中指先"):
        pts["tip"] = wp[side + "中指先"][0]
    elif body.has(side + "中指３") and body.has(side + "中指２"):
        m3, m2 = wp[side + "中指３"][0], wp[side + "中指２"][0]
        pts["tip"] = m3 + 0.6 * (m3 - m2)
    return W, R, pts


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


def part_scale(src, tgt, part):
    """how much bigger the target's part is than the source's (the mean of their boxes' half sizes' ratios)"""
    ss, st = surfaces(src)[part], surfaces(tgt)[part]
    return float(np.mean(st.box_half / ss.box_half))


def mapped_contact(src, tgt, part, near_src, d_src):
    """the target's point (in its part's frame) answering the source's nearest surface point and distance"""
    ss, st = surfaces(src)[part], surfaces(tgt)[part]
    u = (near_src - ss.box_center) / ss.box_half
    p0 = st.box_center + u * st.box_half
    c = st.closest(st.closest(p0))
    n = st.grad(c)
    return c + n * (np.maximum(d_src, 0.0) * part_scale(src, tgt, part))[:, None]


def fix_hands(src, tgt, src_trk, tgt_trk, frames, params, log):
    """the target's arm keys (腕, ひじ, 手首): the hand kept where the source's is relative to a part it is near (and to
    the other hand), then the arm pushed out of the target's head, trunk, hips and thighs; returns the report"""
    F = len(frames)
    rep = {}
    have_src = {p for p in set(surfaces(src)) & set(surfaces(tgt)) if not soft(p)}
    src_parts = {p: v for p, v in part_frames(src, src_trk, frames).items() if p in have_src}
    tgt_all = part_frames(tgt, tgt_trk, frames)
    tgt_parts = {p: v for p, v in tgt_all.items() if p in have_src}
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
        # the hand's points in the hand's frame, frame by frame (the fingers as the dance bends them; the arm's IK keeps
        # the hand's turn, so they move with the wrist)
        loc_t = {p: qrot(qconj(Rt), P - Wt) for p, P in pts_t.items()}
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
            offs = np.stack([loc_t[p][f] for p, f in zip(c["point"][on], np.flatnonzero(on))])
            want_w = Qw - qrot(Rt[on], offs)
            acc[on] += w[on, None] * want_w
            total[on] += w[on]
            top[on] = np.maximum(top[on], w[on])
        has = total > 0
        target[has] = Wt[has] + top[has, None] * (acc[has] / total[has, None] - Wt[has])
        want[side] = target
        weights[side] = {part: {"w": c["w"], "d": c["d"], "want": np.maximum(c["d"], 0.0) * part_scale(src, tgt, part)}
                         for part, c in rel.items()}
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
        clr = clear_arms(tgt, tgt_trk, frames, weights, tgt_all, log)
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


def penetration(tgt, side, ap, hand, parts, relations):
    """per frame the deepest the arm goes into a part (units, >= 0); the turn about the shoulder that takes the deepest
    point of the upper arm or the elbow out (the whole arm turned with it) [F, 4]; the push that takes the wrist out of
    what the forearm and the hand go into [F, 3], and the same from the hand and the forearm's half by it alone [F, 3]
    (a held hand moves by that only).  The hand and the forearm's half by it are not tested against a part
    the source's hand touches then (relations[part]["d"] within TOUCH: the contact sets them there); near one they come
    as close to it as the source's hand is to its own (relations[part]["want"], the distance the hand's relation wants,
    scaled), as far as their thickness: a hand 2 cm off the source's hips stays 2 cm off the target's."""
    surf = surfaces(tgt)
    radii = arm_radii(tgt, side)
    P, rad, share, seg = arm_points(tgt, side, ap, radii, hand)
    S = ap[side + "腕"][0]
    F = P.shape[0]
    deepest = np.zeros(F)
    best_s = np.zeros(F)
    best_w = np.zeros(F)
    push_s = np.zeros((F, 3))
    at_s = np.zeros((F, 3))
    push_w = np.zeros((F, 3))
    best_h = np.zeros(F)
    push_h = np.zeros((F, 3))
    near_shoulder = (seg == 0) | ((seg == 1) & (share < ELBOW_SHARE))
    lever_w = np.where(seg == 1, share, np.where(seg == 2, 1.0, 0.0)) * ~near_shoulder
    lever_h = lever_w * ((seg == 2) | ((seg == 1) & (share >= 0.5)))
    for part, (pos, rot) in parts.items():
        if soft(part):
            continue
        s = surf[part]
        local = qrot(qconj(rot)[:, None, :], P - pos[:, None, :])
        pen = rad[None, :] - s.sdf(local)
        # the upper arm lies against the trunk, the hips and the thighs in many a pose (its skin and the trunk's meet at
        # the armpit and along the side): only the forearm and the hand are kept out of them; the upper arm, its half
        # by the elbow, out of the head
        if part == "head":
            pen[:, (seg == 0) & (share < SHOULDER_SKIP)] = 0.0
        else:
            pen[:, seg == 0] = 0.0
        if part in relations:
            # the hand and the forearm by it as close to the part as the source's hand is to its own: their middle line
            # no closer than that distance (their thickness where it is further than that); on a part the source's hand
            # touches, where they lie is the contact's (the hand set where the source's is, its turn the source's)
            near_hand = (seg == 2) | ((seg == 1) & (share >= 0.5))
            r_eff = np.minimum(rad[None, :], relations[part]["want"][:, None])
            pen = np.where(near_hand[None, :], pen - rad[None, :] + r_eff, pen)
            # (the excuse fades out over TOUCH_BAND past the touch: the hand does not jump as the source's comes on)
            excuse = smoothstep((TOUCH + TOUCH_BAND - relations[part]["d"]) / TOUCH_BAND)
            pen = np.where(near_hand[None, :], pen * (1.0 - excuse)[:, None], pen)
        pen = np.maximum(pen, 0.0)
        if not np.any(pen > 0):
            continue
        deepest = np.maximum(deepest, pen.max(axis=1))
        g = qrot(rot[:, None, :], s.grad(local))
        vec = (pen + CLEAR_MARGIN * (pen > 0))[:, :, None] * g
        sc = np.where(near_shoulder[None, :], pen, 0.0)
        j = np.argmax(sc, axis=1)
        v = sc[np.arange(F), j]
        take = v > best_s
        push_s[take] = vec[np.arange(F), j][take]
        at_s[take] = P[np.arange(F), j][take]
        best_s[take] = v[take]
        sc = pen * lever_w[None, :]
        j = np.argmax(sc, axis=1)
        v = sc[np.arange(F), j]
        take = v > best_w
        push_w[take] = vec[np.arange(F), j][take] * lever_w[j][take][:, None]
        best_w[take] = v[take]
        sc = pen * lever_h[None, :]
        j = np.argmax(sc, axis=1)
        v = sc[np.arange(F), j]
        take = v > best_h
        push_h[take] = vec[np.arange(F), j][take] * lever_h[j][take][:, None]
        best_h[take] = v[take]
    turn_s = np.tile(IDENTITY, (F, 1))
    has = best_s > 0
    if np.any(has):
        turn_s[has] = qbetween(at_s[has] - S[has], at_s[has] + push_s[has] - S[has])
    return deepest, turn_s, push_w, push_h


SWIVELS = 24                    # elbow positions tried round the shoulder-wrist line when a held hand's arm goes in
SWIVEL_COST = 0.02              # units of depth one radian of swivel away from the dance's elbow is worth
SWIVEL_CLEARS = 0.03            # units: a held hand's elbow position that leaves at most this keeps the hand where it is


def upper_depth(tgt, side, S, E, W, parts, touched=None):
    """per frame the deepest the upper arm's half by the elbow and the forearm's half by the elbow go into a part (the
    head for the upper arm; any hard part for the forearm, but the part the hand touches: a forearm lies on the head
    its hand is on), for elbows E [F, 3] (the shoulder S and the wrist W fixed)"""
    surf = surfaces(tgt)
    radii = arm_radii(tgt, side)
    out = np.zeros(len(S))
    pts = [(S + t * (E - S), radii[0], "upper") for t in np.linspace(SHOULDER_SKIP, 1.0, 4)]
    pts += [(E + t * (W - E), radii[1], "fore") for t in np.linspace(0.0, 0.5, 3)]
    for part, (pos, rot) in parts.items():
        if soft(part):
            continue
        s = surf[part]
        skip = np.zeros(len(S), bool) if touched is None else (touched == part)
        for P, r, kind in pts:
            if kind == "upper" and part != "head":
                continue
            d = r - s.sdf(qrot(qconj(rot), P - pos))
            if kind == "fore":
                d = np.where(skip, 0.0, d)
            out = np.maximum(out, d)
    return np.maximum(out, 0.0)


def best_swivel(tgt, side, S, E, W, parts, touched=None):
    """elbows [F, 3] on the circle the arm allows round the line from the shoulder S to the wrist W (lengths kept), the
    one that goes least into the body, the dance's own swivel preferred (SWIVEL_COST a radian)"""
    u = unit(W - S)
    off = E - S
    centre_len = np.sum(off * u, axis=1)
    radial = off - centre_len[:, None] * u
    rad_len = np.linalg.norm(radial, axis=1)
    v1 = unit(np.where(rad_len[:, None] > 1e-6, radial, np.cross(u, np.array([0.0, 0.0, 1.0]))))
    v2 = np.cross(u, v1)
    best_cost = np.full(len(S), np.inf)
    best = E.copy()
    for k in range(SWIVELS):
        phi = 2 * np.pi * k / SWIVELS
        phi = phi if phi <= np.pi else phi - 2 * np.pi
        Ek = S + centre_len[:, None] * u + rad_len[:, None] * (np.cos(phi) * v1 + np.sin(phi) * v2)
        cost = upper_depth(tgt, side, S, Ek, W, parts, touched) + SWIVEL_COST * abs(phi)
        take = cost < best_cost
        best[take] = Ek[take]
        best_cost[take] = cost[take]
    return best


def clear_arms(tgt, trk, frames, hand_relations, parts, log):
    """push the target's arms out of its head, ribbon, trunk, hips and thighs: what the upper arm or the elbow goes into
    is cleared by turning the whole arm about the shoulder, what the forearm or the hand goes into by moving the wrist
    (arm IK, the elbow kept on its side); each change eases in and out over EASE frames around the frames that go in.
    hand_relations: side -> part -> {"w": the hand's relation's weight [F], "d": the source's hand's distance [F],
    "want": the distance the relation wants [F]} (fix_hands).
    Returns the report per side."""
    F = len(frames)
    rep = {}
    for side in SIDES:
        if not all(tgt.has(n) for n in arm_names(side)):
            continue
        relations = hand_relations.get(side, {})
        cw = {part: r["w"] for part, r in relations.items()}
        # the hand is held where the source's hand touches a part (its relation's weight near 1), not where it is only
        # near one: an arm clears the body by moving its hand when the hand was merely close
        hold = smoothstep((np.max(np.stack(list(cw.values())), axis=0) - HOLD_FROM) / (1.0 - HOLD_FROM)) if cw else None
        before = None
        moved_any = np.zeros(F, bool)
        for rnd in range(CLEAR_ROUNDS):
            ap = arm_pose(tgt, trk, frames, side)
            hand = hand_world(tgt, trk, frames, side)
            deep, ts, pw, ph = penetration(tgt, side, ap, hand, parts, relations)
            if before is None:
                before = deep.copy()
            bad = deep > CLEAR_TOL
            if not np.any(bad):
                break
            spans = runs(bad)
            which, weight = ease_weights(F, spans)
            ts2 = np.tile(IDENTITY, (F, 1))
            pw2 = np.zeros_like(pw)
            ph2 = np.zeros_like(ph)
            for n, (a, b) in enumerate(spans):
                m = which == n
                inside = np.zeros(F, bool)
                inside[a:b + 1] = True
                k = a + int(np.argmax(qangle(ts[a:b + 1])))
                kw = a + int(np.argmax(np.linalg.norm(pw[a:b + 1], axis=1)))
                kh = a + int(np.argmax(np.linalg.norm(ph[a:b + 1], axis=1)))
                ts2[m & inside] = ts[m & inside]
                pw2[m & inside] = pw[m & inside]
                ph2[m & inside] = ph[m & inside]
                ramp = m & ~inside
                ts2[ramp] = slerp_n(np.tile(IDENTITY, (int(ramp.sum()), 1)), np.tile(ts[k], (int(ramp.sum()), 1)), weight[ramp])
                pw2[ramp] = weight[ramp, None] * pw[kw]
                ph2[ramp] = weight[ramp, None] * ph[kh]
            moved = weight > 0
            moved_any |= moved
            S, E, W = ap[side + "腕"][0], ap[side + "ひじ"][0], ap[side + "手首"][0]
            E1 = S + qrot(ts2, E - S)
            W1 = S + qrot(ts2, W - S)
            # a hand on a part the source's hand touches stays where the contact put it: the arm clears the body by its
            # elbow (the IK turns the elbow towards where the turned arm would have it) and the wrist does not follow
            # the turn
            Wt = W1 + pw2
            pole = E1.copy()
            if hold is not None:
                # a held hand: first the elbow round the arm's circle where it goes in least, the hand where it is; only
                # where no elbow position clears the upper arm does the arm turn at the shoulder and the hand leave the
                # contact
                idx = np.flatnonzero((hold >= 0.5) & moved)
                if len(idx):
                    sub = {p: (pos[idx], rot[idx]) for p, (pos, rot) in parts.items()}
                    names = sorted(cw)
                    touched = np.array(names, dtype=object)[np.argmax(np.stack([cw[n][idx] for n in names]), axis=0)]
                    Esw = best_swivel(tgt, side, S[idx], E[idx], W[idx], sub, touched)
                    clears = upper_depth(tgt, side, S[idx], Esw, W[idx], sub, touched) <= SWIVEL_CLEARS
                    k = idx[clears]
                    h = hold[k][:, None]
                    Wt[k] = (1 - h) * (W1[k] + pw2[k]) + h * (W[k] + ph2[k])      # held: out of what the hand goes into
                    pole[k] = (1 - h) * E1[k] + h * Esw[clears]
            Es, Ws = arm_ik(S, E1, W1, Wt, pole=pole)
            Es = np.where(moved[:, None], Es, E)
            Ws = np.where(moved[:, None], Ws, W)
            loc = arm_locals(tgt, trk, frames, side, Es, Ws, hand[1])
            for name, q in loc.items():
                _fit_turns(trk, name, frames, q, moved)
        ap = arm_pose(tgt, trk, frames, side)
        hand = hand_world(tgt, trk, frames, side)
        after = penetration(tgt, side, ap, hand, parts, relations)[0]
        rep[side] = {"in_before_frames": int(np.sum(before > CLEAR_TOL)) if before is not None else 0,
                     "in_after_frames": int(np.sum(after > CLEAR_TOL)), "in_after_over_1cm": int(np.sum(after > 0.125)),
                     "deepest_before_cm": round(float(before.max()) * UNIT_CM, 3) if before is not None else 0.0,
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


# ---- the source body: how well a candidate fits the dance -----------------------------------------------------------------

STANCE_LOW = 0.1                # units: a foot IK goal this close to its rest height (and slow) stands (the stance's reach)
STANCE_SLOW = 0.05              # units a frame
TOE_STILL = 0.03                # units a frame: the toe goal this slow (and pitched) stands on the toe
TOE_PITCH = (6.0, 45.0)         # degrees: the pitches the toe's floor relation is read over (above, the foot is on its ball)
SEMI_STANDARD = ("全ての親", "グルーブ", "上半身2")


def foot_goals(body, trk, frames, side):
    """(the foot IK's goal [F, 3], its world turn [F, 4], the toe IK's goal [F, 3]) by forward kinematics (no IK)"""
    wp = world_pose(body, trk, frames, [side + "足ＩＫ", side + "つま先ＩＫ"])
    return wp[side + "足ＩＫ"][0], wp[side + "足ＩＫ"][1], wp[side + "つま先ＩＫ"][0]


def toe_relation(body, trk, frames):
    """per side: the frames where the toe goal stands still pitched 6..45 degrees (the toe on the floor), the pitch, the
    foot IK's rise over its rest and the toe goal's height over the body's floor"""
    out = {}
    for side in SIDES:
        goal, turn, toe = foot_goals(body, trk, frames, side)
        pitch = foot_pitch(turn)
        v = np.zeros(len(frames))
        v[1:] = np.linalg.norm(np.diff(toe[:, [0, 2]], axis=0), axis=1)
        still = (np.minimum(v, np.concatenate([v[1:], v[-1:]])) < TOE_STILL) & (pitch > TOE_PITCH[0]) & (pitch < TOE_PITCH[1])
        rise = goal[:, 1] - body.rest(side + "足ＩＫ")[1]
        out[side] = {"still": still, "pitch": pitch, "rise": rise, "toe_height": toe[:, 1] - body.rest(side + "つま先ＩＫ")[1]}
    return out


def lower_envelope(pitch, rise, width=6.0, q=10.0):
    """(pitch, rise) of the lower envelope: per bin of `width` degrees the q-th percentile of the rise (a toe on the floor
    lies on it; a foot held in the air lies above)"""
    out = []
    for a in np.arange(TOE_PITCH[0], TOE_PITCH[1], width):
        m = (pitch >= a) & (pitch < a + width)
        if m.sum() >= 3:
            out.append((float(np.median(pitch[m])), float(np.percentile(rise[m], q)), int(m.sum())))
    return out


def fit_toe(points):
    """least squares of rise = l sin(p) - h (1 - cos(p)) over (pitch, rise, n) points (weighted by sqrt n): (l, h)"""
    if len(points) < 2:
        return None
    p = np.radians([x[0] for x in points])
    r = np.array([x[1] for x in points])
    w = np.sqrt([x[2] for x in points])
    A = np.stack([np.sin(p), -(1 - np.cos(p))], axis=1) * w[:, None]
    sol, *_ = np.linalg.lstsq(A, r * w, rcond=None)
    resid = r - np.stack([np.sin(p), -(1 - np.cos(p))], axis=1) @ sol
    return {"l": float(sol[0]), "h": float(sol[1]), "rms": float(np.sqrt(np.mean(resid ** 2)))}


def stance_reach(body, trk, frames):
    """per side: the share of the standing frames (foot IK goal low and slow) whose goal lies more than 5 mm past the
    leg's length from the hip (the two-bone leg), and the 99th percentile of goal distance / leg length"""
    out = {}
    for side in SIDES:
        wp = world_pose(body, trk, frames, [side + "足", side + "足ＩＫ"])
        hip, goal = wp[side + "足"][0], wp[side + "足ＩＫ"][0]
        L = float(np.linalg.norm(body.rest(side + "ひざ") - body.rest(side + "足")) + np.linalg.norm(body.rest(side + "足首") - body.rest(side + "ひざ")))
        d = np.linalg.norm(goal - hip, axis=1)
        v = np.zeros(len(frames))
        v[1:] = np.linalg.norm(np.diff(goal, axis=0), axis=1)
        st = (goal[:, 1] - body.rest(side + "足ＩＫ")[1] < STANCE_LOW) & (np.maximum(v, np.concatenate([v[1:], v[-1:]])) < STANCE_SLOW)
        out[side] = {"stance_frames": int(st.sum()), "over_5mm_pct": round(100.0 * float(np.mean(d[st] - L > 0.0625)), 3) if st.any() else None,
                     "d_over_L_p99": round(float(np.percentile(d[st] / L, 99)), 4) if st.any() else None, "leg": round(L, 4)}
    return out


def own_arms(body, trk, frames):
    """per side: how the dance's arms sit in the candidate's own body (no mapping): the frames the arm goes more than
    1 cm into its head, trunk, hips or thighs, the deepest (cm), and the two palms' least distance (cm, less the hands'
    thickness)"""
    parts = part_frames(body, trk, frames)
    out = {}
    hands = {}
    for side in SIDES:
        if not all(body.has(n) for n in arm_names(side)):
            continue
        ap = arm_pose(body, trk, frames, side)
        hands[side] = hand_world(body, trk, frames, side)
        deep = penetration(body, side, ap, hands[side], parts, {})[0]
        out[side] = {"in_1cm_frames": int(np.sum(deep > 0.125)), "deepest_cm": round(float(deep.max()) * UNIT_CM, 3),
                     "in_1cm_runs": len(runs(deep > 0.125))}
    if len(hands) == 2:
        gap = np.linalg.norm(hands["左"][2]["palm"] - hands["右"][2]["palm"], axis=1) - 2 * HAND_THICK
        out["palms_gap_min_cm"] = round(float(gap.min()) * UNIT_CM, 3)
        out["palms_gap_min_frame"] = int(np.argmin(gap))
    return out


def with_semi_standard(body):
    """the body with 全ての親, グルーブ and 上半身2 added when it lacks them (as PMXEditor's semi-standard bones: 全ての親 at
    the origin over everything, グルーブ 0.2 above センター, 上半身2 at 40 % from 上半身 to 首 with the trunk's upper
    vertices), so that a dance keyed on them moves it; the spec of what was added"""
    add = []
    names = {b.name for b in body.model.bones}
    if "全ての親" not in names:
        roots = [b.name for b in body.model.bones if b.parent is None]
        add.append({"name": "全ての親", "parent": None, "at": [0.0, 0.0, 0.0], "children": roots, "translate": True})
    if "グルーブ" not in names and body.has("センター"):
        c = body.rest("センター")
        kids = [b.name for b in body.model.bones if b.parent == body.i("センター")]
        add.append({"name": "グルーブ", "parent": "センター", "at": [float(c[0]), float(c[1]) + 0.2, float(c[2])], "children": kids,
                    "translate": True})
    if "上半身2" not in names and body.has("上半身") and body.has("首"):
        a, b = body.rest("上半身"), body.rest("首")
        at = a + 0.4 * (b - a)
        kids = [x.name for x in body.model.bones if x.parent == body.i("上半身")]
        add.append({"name": "上半身2", "parent": "上半身", "at": [float(v) for v in at], "children": kids,
                    "vertices_above": ["上半身", float(at[1])]})
    return add


def fit(dance, candidates, log=None):
    """the candidates' fit to the dance (see the module's doc): per candidate the toe's floor relation (the height left
    over where the dance stands on its toes, and the foot (l, h) the dance's own envelope asks for), the standing legs'
    reach, the arms in the candidate's own body and the palms' gap"""
    log = log or (lambda *_: None)
    out = {}
    for path, body in candidates:
        t0 = time.time()
        add = with_semi_standard(body)
        b = body.edited(add) if add else body
        trk = tracks_of(dance.bones)
        frames = np.arange(0, max(k.frame for k in dance.bones) + 1)
        row = {"name": body.name, "added": [a["name"] for a in add]}
        rel = toe_relation(b, trk, frames)
        toe = {}
        for side, r in rel.items():
            m = r["still"]
            env = lower_envelope(r["pitch"][m], r["rise"][m])
            toe[side] = {"frames": int(m.sum()), "height_left_cm": _quant(np.abs(r["toe_height"][m]) * UNIT_CM, (25, 50, 75)),
                         "height_signed_median_cm": round(float(np.median(r["toe_height"][m])) * UNIT_CM, 3) if m.any() else None,
                         "envelope": [[round(p, 2), round(v, 4), n] for p, v, n in env], "fit": fit_toe(env)}
            ank, toe_r = b.rest(side + "足首"), b.rest(side + "つま先")
            l_own, h_own = float(ank[2] - toe_r[2]), float(ank[1] - toe_r[1])
            toe[side]["own"] = {"l": round(l_own, 4), "h": round(h_own, 4)}
            # with the candidate's own ankle height: the toe length each pitch's envelope asks for, and their median
            # (the two-number fit is ill-posed over 6..45 degrees: sin and 1 - cos rise together)
            ask = [(p, (v + h_own * (1 - np.cos(np.radians(p)))) / np.sin(np.radians(p)), n) for p, v, n in env]
            toe[side]["l_asked"] = [[round(p, 2), round(x, 4), n] for p, x, n in ask]
            toe[side]["l_asked_median"] = round(float(np.median([x for _, x, _ in ask])), 4) if ask else None
        row["toe"] = toe
        row["stance"] = stance_reach(b, trk, frames)
        row["arms"] = own_arms(b, trk, frames)
        row["seconds"] = round(time.time() - t0, 1)
        log("fit", body.name, json.dumps({k: row[k] for k in ("stance", "arms")}, ensure_ascii=True))
        out[path] = row
    return out


# ---- the command ------------------------------------------------------------------------------------------------------------

def write_bytes(path, data):
    """write through a temporary name, then replace (a reader never sees half a file)"""
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def check_distinct(*paths):
    seen = {}
    for p in paths:
        if not p:
            continue
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
            raise ValueError("%s is given twice (%s)" % (p, seen[key]))
        seen[key] = p


def _log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def cmd_run(args):
    check_distinct(args.dance, args.out, args.report)
    for p in (args.dance, args.source, args.target):
        if not os.path.isfile(p):
            raise ValueError("no file %s" % p)
    motion = vmd.load(args.dance)
    src = Body.load(args.source)
    tgt = Body.load(args.target)
    params = {"feet": not args.no_feet, "hands": not args.no_hands, "clear": not args.no_clear, "stance": args.stance}
    res = layer(motion, src, tgt, params, log=_log)
    write_bytes(os.path.abspath(args.out), vmd.dumps(res.motion))
    report = dict(res.report, dance=os.path.abspath(args.dance), source_path=os.path.abspath(args.source),
                  target_path=os.path.abspath(args.target), out=os.path.abspath(args.out))
    if args.report:
        write_bytes(os.path.abspath(args.report), (json.dumps(report, ensure_ascii=False, indent=1, default=float) + "\n").encode("utf-8"))
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "scale": round(res.report["scale"], 5),
                      "keys_in": res.report["keys_in"], "keys_out": res.report["keys_out"],
                      "missing_bones": len(res.report["missing_bones"]), "seconds": res.report["seconds"]}, ensure_ascii=True))
    return 0


def cmd_fit(args):
    dance = vmd.load(args.dance)
    cands = [(p, Body.load(p)) for p in args.candidates]
    res = fit(dance, cands, log=_log)
    write_bytes(os.path.abspath(args.out), (json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n").encode("utf-8"))
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "candidates": len(res)}, ensure_ascii=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="move the dance onto the target body")
    p.add_argument("dance")
    p.add_argument("source", help="the body the dance was made for (.pmx / .pmd / .json body)")
    p.add_argument("target", help="the body to move it onto (.pmx)")
    p.add_argument("out")
    p.add_argument("--report")
    p.add_argument("--no-feet", action="store_true")
    p.add_argument("--no-hands", action="store_true")
    p.add_argument("--no-clear", action="store_true")
    p.add_argument("--stance", choices=("legs", "offsets"), default="legs")
    p = sub.add_parser("fit", help="how candidate bodies fit the dance")
    p.add_argument("dance")
    p.add_argument("--candidates", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "fit": cmd_fit}[args.cmd](args)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
