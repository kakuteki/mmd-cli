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
import io
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


# ---- models --------------------------------------------------------------------------------------------------------------

def _pmd_vertices(data):
    """positions [N, 3] and the bone with the larger weight [N] of a PMD file's vertices"""
    pos = struct.calcsize("<3sf20s256s")
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    raw = np.frombuffer(data, dtype=np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("uv", "<f4", 2), ("b", "<u2", 2),
                                               ("w", "u1"), ("e", "u1")]), count=n, offset=pos)
    main = np.where(raw["w"] >= 50, raw["b"][:, 0], raw["b"][:, 1]).astype(np.int64)
    return raw["p"].astype(np.float64), main


def _pmx_vertices(doc):
    P = np.array([v.position() for v in doc.vertices], dtype=np.float64).reshape(-1, 3)
    main = np.array([max(v.pairs(), key=lambda bw: bw[1])[0] for v in doc.vertices], dtype=np.int64)
    return P, main


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

    def __init__(self, model, limits, vertices=None, main_bone=None, name=None):
        self.model = model
        self.limits = limits
        self.vertices = np.zeros((0, 3)) if vertices is None else np.asarray(vertices, dtype=np.float64)
        self.main_bone = np.zeros(0, dtype=np.int64) if main_bone is None else np.asarray(main_bone, dtype=np.int64)
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
            P, main = _pmd_vertices(data)
            return cls(model, limits, P, main, name)
        model = pmx.loads(data)
        doc = pmx_edit.loads(data)
        P, main = _pmx_vertices(doc)
        return cls(model, LI.ik_limits(doc), P, main, name)

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
        "translate": bool}], "rest": {bone: [x, y, z]}}.  An added bone takes the listed children from their parent; a
        moved bone moves the vertices whose largest weight is on it by as much."""
        path = spec["model"]
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        base = cls.load(path)
        return base.edited(spec.get("add", ()), spec.get("rest", {}), name=spec.get("name"))

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
        for bname, at in (rest or {}).items():
            if bname not in names:
                raise ValueError("no bone %r to move" % bname)
            i = names.index(bname)
            old = np.array(bones[i].position, dtype=np.float64)
            bones[i].position = tuple(float(v) for v in at)
            if len(vertices):
                vertices[self.main_bone == i] += np.array(at, dtype=np.float64) - old
        model = pmx.Model(self.model.format, self.model.version, self.model.name, self.model.name_en, self.model.comment,
                          self.model.comment_en, dict(self.model.counts, bones=len(bones)), bones, self.model.morphs,
                          self.model.display_frames)
        return Body(model, self.limits, vertices, self.main_bone, name or self.name)

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
    out = vmd.Motion(model_name=motion.model_name, bones=keys, morphs=list(motion.morphs), cameras=list(motion.cameras),
                     lights=list(motion.lights), shadows=list(motion.shadows), show_iks=list(motion.show_iks))
    report = {"params": p, "scale": s, "stance_shift": shift, "missing_bones": missing, "added_rest_keys": added,
              "corrections_deg": {n: round(math.degrees(float(qangle(c))), 4) for n, c in sorted(corr.items())},
              "source": src.name, "target": tgt.name, "keys_in": len(motion.bones), "keys_out": len(out.bones),
              "seconds": round(time.time() - t0, 2)}
    return Result(out, report)
