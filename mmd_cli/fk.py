"""Forward kinematics without MMD: where the bones of a PMX model are, frame by frame, under a VMD motion, and
where the camera of a camera VMD is.

Bones (Pose, world_track).  Each bone's key value at a frame is what MMD shows there: held before the first and
after the last key, in between a straight line per position channel and the short way for the rotation, each
eased by the curve of the later key (sample, the same rule as tools/fix_twist.py; a bone without keys rests).  A
VMD names a bone with at most 15 bytes of cp932, so a longer model name is matched by its first 15 bytes
(vmd_name).  Then, from the root down (a parent before its children):

    world(bone) = world(parent) * T(rest - parent_rest + key position + appended translation)
                                * R(key rotation * appended rotation)

T is a translation and R a rotation, products apply right to left; a root has world(parent) = identity and
parent_rest = 0.  The rest positions are the PMX bone positions (formats.pmx keeps them).  A bone with an append
(付与) bit takes its append parent's local rotation (that bone's key rotation with its own appended part) scaled by
the ratio (q^ratio: the same axis, ratio times the angle; a negative ratio turns the other way) and applies it
before its own key rotation; likewise it adds its append parent's local translation (key and appended part)
times the ratio.

Left out: IK (the bones an IK moves, legs and feet, come out as their own keys alone say, which is wrong as soon as
an IK bone moves), physics (hair, skirt), external parents, the "local append" bit (0x0080) and the deform order
(layers).  None of them touches Sour's Rin from 全ての親 to the head and the eyes or down the arms to the wrists: no
bone of those chains is an IK link.  Fixed and local axes do not matter here: a key rotation is stored in the
parent's frame whatever axes the window turns it about.

The convention (KEY_ROTATION_SIGNS, the ONE place to flip): MMD's coordinates have X to the model's left, Y up,
and the model faces -Z (the camera at window angles 0 looks along +Z at her face; review 5, measured on renders).
A stored key quaternion (x, y, z, w) is taken to turn these coordinates as the plain Hamilton rotation of its
numbers, v' = q v q^-1 (applied(q) = q).  The evidence: Sour's Rin limits her knees (the links of the leg IK) to
an X turn between -180 and 0 degrees, and in this reading a negative X turn swings the shin back to +Z, which is
how a knee bends; Direct3D, which MMD is built on, makes the same rotation of a quaternion.  It is NOT checked on a
render: the --probe of tools/eye_gaze.py is that check.  If the probe's eyes turn the other way on both axes, MMD
applies the inverse: (-1, -1, -1).  The signs multiply x, y and z of every stored rotation, and stored() is the
same map (it is its own inverse), so FK and every rotation written from it change together.

Camera (camera_keys, camera_at, camera_position).  A camera key holds the look-at point (its position), the
distance (negative in the file), the rotation (radians, X negated against the window) and the view angle.  Each
channel follows the curve of the later key on its own value: x, y and z of the look-at point, the rotation curve on
all three angles, the distance, the view angle (a working assumption carried over from the bones' rule, not measured
on a render).  With the window's angles X and Y (degrees) and the window's distance d, the camera sits at

    look_at + d * (sin Y cos X, sin X, -cos Y cos X)

(X positive lifts the camera so that it looks down, Y positive swings it to the +X side: measured on renders with
vanishing points, review 5, 1.1 and 1.2).  X is applied before Y; the roll Z is taken to turn about the line of
sight without moving the camera (tools/make_camera.py keeps Z at 0, so this is not exercised).
"""
import bisect
import math
from dataclasses import dataclass
from typing import Tuple

from .formats import vmd

KEY_ROTATION_SIGNS = (1.0, 1.0, 1.0)       # THE convention: see the module docstring before changing it

IDENTITY = (0.0, 0.0, 0.0, 1.0)
ZERO = (0.0, 0.0, 0.0)


def applied(q):
    """the rotation MMD applies for the stored key quaternion q (the convention of the module docstring)"""
    sx, sy, sz = KEY_ROTATION_SIGNS
    return (sx * q[0], sy * q[1], sz * q[2], q[3])


def stored(q):
    """the quaternion to store for a rotation that is to be applied (the same map as applied: its own inverse)"""
    return applied(q)


# ---- quaternions (x, y, z, w) ---------------------------------------------------------------

def multiply(a, b):
    """the Hamilton product a * b: rotating by it is rotating by b first, then by a"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def conjugate(q):
    """the inverse of a unit quaternion"""
    return (-q[0], -q[1], -q[2], q[3])


def rotate(q, v):
    """the vector v turned by the unit quaternion q (q v q^-1)"""
    x, y, z, w = q
    vx, vy, vz = v
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return (vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx)


def normalized(q):
    n = math.sqrt(sum(v * v for v in q))
    return tuple(v / n for v in q) if n > 0.0 else IDENTITY


def slerp(a, b, t):
    """from a to b the short way (t outside 0..1 goes on along the same arc)"""
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b, dot = tuple(-v for v in b), -dot
    if dot > 0.9995:
        return normalized(tuple(x + (y - x) * t for x, y in zip(a, b)))
    theta = math.acos(min(1.0, dot))
    s = math.sin(theta)
    wa, wb = math.sin((1.0 - t) * theta) / s, math.sin(t * theta) / s
    return normalized(tuple(wa * x + wb * y for x, y in zip(a, b)))


def power(q, k):
    """q to the power k: the same axis, k times the angle (counted the short way)"""
    return slerp(IDENTITY, q if q[3] >= 0.0 else tuple(-v for v in q), k)


# ---- what MMD shows at a frame (as tools/fix_twist.py) --------------------------------------

def tracks_of(motion):
    """bone name -> its keys sorted by frame (a stable sort: two keys on one frame keep their file order)"""
    out = {}
    for key in motion.bones:
        out.setdefault(key.name, []).append(key)
    for keys in out.values():
        keys.sort(key=lambda k: k.frame)
    return out


def bezier_y(curve, x):
    """y of an MMD curve (x1, y1, x2, y2 in 0..127) at the time x in 0..1"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)
    if (x1, y1, x2, y2) == (y1, x1, y2, x2):                         # on the diagonal: straight
        return x
    lo, hi = 0.0, 1.0
    for _ in range(40):
        t = (lo + hi) / 2.0
        u = 1.0 - t
        if 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 < x:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2.0
    u = 1.0 - t
    return 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3


def sample(keys, frame, frames=None):
    """(position, rotation) of a bone at `frame` as MMD shows it, as stored (see the module docstring).  `frames`
    is the list of the keys' frames, when the caller has it."""
    if frames is None:
        frames = [k.frame for k in keys]
    i = bisect.bisect_right(frames, frame)
    if i == 0:
        return tuple(keys[0].position), normalized(keys[0].rotation)
    a = keys[i - 1]
    if i == len(keys) or a.frame == frame:
        return tuple(a.position), normalized(a.rotation)
    b = keys[i]
    x = (frame - a.frame) / float(b.frame - a.frame)
    curves = vmd.bone_curves(b.interpolation)
    position = tuple(pa + (pb - pa) * bezier_y(curves[c], x) for pa, pb, c in zip(a.position, b.position, ("x", "y", "z")))
    return position, slerp(normalized(a.rotation), normalized(b.rotation), bezier_y(curves["rotation"], x))


def vmd_name(name):
    """the name a VMD gives a bone: at most 15 bytes of cp932 (cut even inside a character), read back the way
    formats.vmd reads names"""
    raw = name.encode(vmd.ENCODING, "replace")[:15]
    return raw.split(b"\x00", 1)[0].decode(vmd.ENCODING, "replace")


# ---- the bones ------------------------------------------------------------------------------

class Pose:
    """forward kinematics of the bones `names` of `model` (formats.pmx / formats.pmd) under `motion`: at(frame)
    gives each one's world position and world rotation (the rotation as applied, see the module docstring)"""

    def __init__(self, model, motion, names):
        self.bones = model.bones
        by_name = {}
        for bone in self.bones:
            by_name.setdefault(bone.name, bone.index)
        self.targets = []
        for name in names:
            if name not in by_name:
                raise ValueError("the model has no bone named %r" % name)
            self.targets.append((name, by_name[name]))
        self.order = self._order([index for _, index in self.targets])
        for index in self.order:
            if self.bones[index].position is None:
                raise ValueError("bone %r has no rest position (the model reader did not keep it)" % self.bones[index].name)
        tracks = tracks_of(motion)
        self.tracks = {}
        for index in self._sampled():
            name = self.bones[index].name
            keys = tracks.get(name) or tracks.get(vmd_name(name))
            if keys:
                self.tracks[index] = (keys, [k.frame for k in keys])

    def _check(self, index, what):
        if not 0 <= index < len(self.bones):
            raise ValueError("%s %d is not a bone of the model (it has %d)" % (what, index, len(self.bones)))
        return index

    def _order(self, targets):
        """the targets and all their ancestors, each after its parent"""
        order, placed = [], set()
        for target in targets:
            chain, index = [], target
            while index is not None and index not in placed:
                if index in chain:
                    raise ValueError("bone %r is its own ancestor" % self.bones[index].name)
                chain.append(index)
                parent = self.bones[index].parent
                index = None if parent is None else self._check(parent, "the parent")
            for index in reversed(chain):
                placed.add(index)
                order.append(index)
        return order

    def _appends(self, bone):
        """(parent index, ratio, rotate, translate) of the bone's append, or None"""
        a = bone.append
        if a is None or a.get("parent") is None:
            return None
        rotate_, translate = bool(bone.flags.get("append_rotate")), bool(bone.flags.get("append_translate"))
        if not (rotate_ or translate):
            return None
        return self._check(a["parent"], "the append parent"), float(a["ratio"]), rotate_, translate

    def _sampled(self):
        """the bones whose keys are needed: the order and, through the appends, their append parents"""
        need, stack = set(self.order), list(self.order)
        while stack:
            append = self._appends(self.bones[stack.pop()])
            if append is not None and append[0] not in need:
                need.add(append[0])
                stack.append(append[0])
        return need

    def _local(self, index, frame, keys, local, depth=0):
        """(translation, rotation) of the bone's own motion: its key and its appended part"""
        if index in local:
            return local[index]
        if depth > len(self.bones):
            raise ValueError("the appends of bone %r go round in a loop" % self.bones[index].name)
        if index not in keys:
            track = self.tracks.get(index)
            if track is None:
                keys[index] = (ZERO, IDENTITY)
            else:
                position, rotation = sample(track[0], frame, track[1])
                keys[index] = (position, applied(rotation))
        translation, rotation = keys[index]
        append = self._appends(self.bones[index])
        if append is not None:
            parent, ratio, turns, moves = append
            by_translation, by_rotation = self._local(parent, frame, keys, local, depth + 1)
            if turns:
                rotation = multiply(rotation, power(by_rotation, ratio))
            if moves:
                translation = tuple(t + ratio * p for t, p in zip(translation, by_translation))
        local[index] = (translation, rotation)
        return local[index]

    def world(self, frame):
        """bone index -> (world position, world rotation) of every bone of the order at `frame`"""
        keys, local, world = {}, {}, {}
        for index in self.order:
            bone = self.bones[index]
            translation, rotation = self._local(index, frame, keys, local)
            if bone.parent is None:
                world[index] = (tuple(r + t for r, t in zip(bone.position, translation)), rotation)
                continue
            parent_position, parent_rotation = world[bone.parent]
            rest = self.bones[bone.parent].position
            offset = rotate(parent_rotation, tuple(b - r + t for b, r, t in zip(bone.position, rest, translation)))
            world[index] = (tuple(p + o for p, o in zip(parent_position, offset)), multiply(parent_rotation, rotation))
        return world

    def at(self, frame):
        """name -> (world position, world rotation) of the requested bones at `frame`"""
        world = self.world(frame)
        return {name: world[index] for name, index in self.targets}


def last_frame(motion):
    """the last frame of the motion's bone keys (0 without any)"""
    return max((k.frame for k in motion.bones), default=0)


def world_track(model, motion, names, first=0, last=None):
    """name -> [(world position, world rotation) at every frame from `first` to `last`] (last: the motion's last bone
    key)"""
    pose = Pose(model, motion, names)
    if last is None:
        last = last_frame(motion)
    out = {name: [] for name, _ in pose.targets}
    for frame in range(first, last + 1):
        world = pose.world(frame)
        for name, index in pose.targets:
            out[name].append(world[index])
    return out


# ---- the camera -----------------------------------------------------------------------------

@dataclass
class CameraState:
    frame: int
    look_at: Tuple[float, float, float]
    distance: float                         # as the window shows it: positive with the camera in front
    angles: Tuple[float, float, float]      # the window's degrees
    fov: float


def camera_keys(motion):
    """the camera keys sorted by frame; ValueError when there are none"""
    keys = sorted(motion.cameras, key=lambda k: k.frame)
    if not keys:
        raise ValueError("the camera motion has no camera keys")
    return keys


def _state(frame, position, distance, rotation, fov):
    x, y, z = rotation
    return CameraState(frame, tuple(float(v) for v in position), -float(distance),
                       (-math.degrees(x) + 0.0, math.degrees(y) + 0.0, math.degrees(z) + 0.0), float(fov))


def camera_at(keys, frame, frames=None):
    """the camera at `frame` as the window would show it (see the module docstring for the interpolation)"""
    if frames is None:
        frames = [k.frame for k in keys]
    i = bisect.bisect_right(frames, frame)
    if i == 0:
        a = keys[0]
        return _state(frame, a.position, a.distance, a.rotation, a.fov)
    a = keys[i - 1]
    if i == len(keys) or a.frame == frame:
        return _state(frame, a.position, a.distance, a.rotation, a.fov)
    b = keys[i]
    x = (frame - a.frame) / float(b.frame - a.frame)
    curves = vmd.camera_curves(b.interpolation)

    def between(va, vb, channel):
        return va + (vb - va) * bezier_y(curves[channel], x)
    position = tuple(between(pa, pb, c) for pa, pb, c in zip(a.position, b.position, ("x", "y", "z")))
    rotation = tuple(between(ra, rb, "rotation") for ra, rb in zip(a.rotation, b.rotation))
    return _state(frame, position, between(a.distance, b.distance, "distance"), rotation,
                  between(float(a.fov), float(b.fov), "fov"))


def camera_position(state):
    """where the camera of `state` is in the world (see the module docstring)"""
    ax, ay = math.radians(state.angles[0]), math.radians(state.angles[1])
    d = state.distance
    lx, ly, lz = state.look_at
    return (lx + d * math.sin(ay) * math.cos(ax), ly + d * math.sin(ax), lz - d * math.cos(ay) * math.cos(ax))


def camera_direction(state):
    """the unit vector the camera looks along, from its angles alone, so that it is defined at distance 0 too (a
    camera turning on the spot): from the camera to the look-at point for a positive distance.  For a negative
    distance (the camera beyond the look-at point) it is taken to be the same (not measured)."""
    ax, ay = math.radians(state.angles[0]), math.radians(state.angles[1])
    return (-math.sin(ay) * math.cos(ax), -math.sin(ax), math.cos(ay) * math.cos(ax))
