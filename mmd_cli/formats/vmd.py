"""Read and write VMD (Vocaloid Motion Data) files.

Values are kept exactly as they are stored in the file: bone rotations are quaternions
(x, y, z, w), camera rotations are radians with the X angle negated relative to what the
MMD window shows, and the camera distance is negative.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAGIC = b"Vocaloid Motion Data 0002"
ENCODING = "cp932"
CAMERA_MODEL_NAME = "カメラ・照明"

# the bytes MMD writes for an untouched (linear-looking) interpolation curve
DEFAULT_BONE_INTERPOLATION = bytes(
    [20, 20, 0, 0, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107]
    + [20] * 7 + [107] * 8 + [0]
    + [20] * 6 + [107] * 8 + [0, 0]
    + [20] * 5 + [107] * 8 + [0, 0, 0])
DEFAULT_CAMERA_INTERPOLATION = bytes([20, 107, 20, 107] * 6)

# An interpolation curve is the two control points (x1, y1) (x2, y2) of the bezier the MMD window
# draws, each 0..127; (20, 20) (107, 107) is the curve above.  A bone key has one per channel
# (X, Y, Z, rotation), a camera key one per channel (X, Y, Z, rotation, distance, view angle).
LINEAR_CURVE = (20, 20, 107, 107)
BONE_CHANNELS = ("x", "y", "z", "rotation")
CAMERA_CHANNELS = ("x", "y", "z", "rotation", "distance", "fov")


def check_curve(curve):
    """x1 y1 x2 y2 as a tuple of ints, each 0..127"""
    values = tuple(curve)
    if len(values) != 4:
        raise ValueError("an interpolation curve is 4 numbers: x1 y1 x2 y2")
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 0 <= v <= 127:
            raise ValueError("interpolation values are whole numbers from 0 to 127, not %r" % (v,))
    return tuple(int(v) for v in values)


def bone_interpolation(curve, keep=None):
    """the 64 bytes of a bone key with `curve` on all four channels.

    Layout, measured on files MMD and others wrote (tests/test_vmd.py): the first 16 bytes are x1 of
    the four channels, then y1, x2 and y2 of the four; each later row of 16 is the previous row
    shifted left by one byte and padded with 0.  Bytes 2 and 3 of the first row never hold the curve
    (MMD writes 0 there even for curved keys; they are said to carry the physics on/off flag): a new
    key gets 0 there, `keep` (an existing key's 64 bytes) keeps what that key had."""
    x1, y1, x2, y2 = check_curve(curve)
    row = [x1] * 4 + [y1] * 4 + [x2] * 4 + [y2] * 4
    out = []
    for shift in range(4):
        out += row[shift:] + [0] * shift
    out[2], out[3] = (keep[2], keep[3]) if keep is not None else (0, 0)
    return bytes(out)


def camera_interpolation(curve):
    """the 24 bytes of a camera key with `curve` on all six channels: x1 x2 y1 y2 per channel"""
    x1, y1, x2, y2 = check_curve(curve)
    return bytes([x1, x2, y1, y2] * 6)


def bone_curves(data):
    """channel -> (x1, y1, x2, y2) of a bone key's 64 bytes.  x1 of Z and rotation are taken from the
    second row, where the first row's bytes 2 and 3 are intact."""
    first = list(data[:16])
    first[2], first[3] = data[17], data[18]
    return {name: (first[c], first[c + 4], first[c + 8], first[c + 12]) for c, name in enumerate(BONE_CHANNELS)}


def camera_curves(data):
    """channel -> (x1, y1, x2, y2) of a camera key's 24 bytes"""
    return {name: (data[c * 4], data[c * 4 + 2], data[c * 4 + 1], data[c * 4 + 3])
            for c, name in enumerate(CAMERA_CHANNELS)}

_BONE = struct.Struct("<15sI3f4f64s")
_MORPH = struct.Struct("<15sIf")
_CAMERA = struct.Struct("<If3f3f24sIB")
_LIGHT = struct.Struct("<I3f3f")
_SHADOW = struct.Struct("<IBf")
_COUNT = struct.Struct("<I")


@dataclass
class BoneKey:
    name: str
    frame: int
    position: Tuple[float, float, float]
    rotation: Tuple[float, float, float, float]
    interpolation: bytes = DEFAULT_BONE_INTERPOLATION
    raw_name: Optional[bytes] = None        # the name field as read; MMD cuts names at 15 bytes, even mid-character


@dataclass
class MorphKey:
    name: str
    frame: int
    weight: float
    raw_name: Optional[bytes] = None


@dataclass
class CameraKey:
    frame: int
    distance: float
    position: Tuple[float, float, float]
    rotation: Tuple[float, float, float]
    fov: int = 30
    perspective: bool = True
    interpolation: bytes = DEFAULT_CAMERA_INTERPOLATION


@dataclass
class LightKey:
    frame: int
    rgb: Tuple[float, float, float]
    direction: Tuple[float, float, float]


@dataclass
class ShadowKey:
    frame: int
    mode: int
    distance: float


@dataclass
class ShowIkKey:
    frame: int
    visible: bool
    iks: List[Tuple[str, bool]] = field(default_factory=list)


@dataclass
class Motion:
    model_name: str = ""
    bones: List[BoneKey] = field(default_factory=list)
    morphs: List[MorphKey] = field(default_factory=list)
    cameras: List[CameraKey] = field(default_factory=list)
    lights: List[LightKey] = field(default_factory=list)
    shadows: List[ShadowKey] = field(default_factory=list)
    show_iks: List[ShowIkKey] = field(default_factory=list)

    @classmethod
    def for_camera(cls, cameras=None, lights=None, shadows=None):
        return cls(model_name=CAMERA_MODEL_NAME, cameras=list(cameras or []), lights=list(lights or []),
                   shadows=list(shadows or []))

    @property
    def is_camera(self):
        return self.model_name == CAMERA_MODEL_NAME


def _encode(text, what):
    try:
        return text.encode(ENCODING)
    except UnicodeEncodeError:
        raise ValueError("%s %r has characters outside cp932" % (what, text)) from None


def _fixed(text, size, what):
    raw = _encode(text, what)
    if len(raw) > size:
        raise ValueError("%s %r does not fit in %d bytes (cp932)" % (what, text, size))
    return raw.ljust(size, b"\x00")


def _truncated(text, size):
    """encode (characters outside cp932 become '?'), cutting on a character boundary when the text
    is too long for the field"""
    raw = text.encode(ENCODING, "replace")
    while len(raw) > size:
        text = text[:-1]
        raw = text.encode(ENCODING, "replace")
    return raw.ljust(size, b"\x00")


def _frame(frame, what, name=None):
    """frame numbers are unsigned 32-bit in the file"""
    if not 0 <= frame <= 0xFFFFFFFF:
        where = what if name is None else "%s %r" % (what, name)
        raise ValueError("%s: frame %r is out of range (0 to 4294967295)" % (where, frame))
    return frame


def _text(raw):
    return raw.split(b"\x00", 1)[0].decode(ENCODING, "replace")


def _raw(raw):
    return raw.split(b"\x00", 1)[0]


def _name_field(key, size, what):
    """the name as the file had it when the key came from a file and was not renamed (a name cut inside a
    double-byte character cannot be re-encoded from its text), else the text encoded"""
    raw = key.raw_name
    if raw is not None and _text(raw) == key.name:
        return raw.ljust(size, b"\x00")
    return _fixed(key.name, size, what)


def dumps(motion):
    out = [MAGIC.ljust(30, b"\x00"), _truncated(motion.model_name, 20)]
    out.append(_COUNT.pack(len(motion.bones)))
    for k in motion.bones:
        if len(k.interpolation) != 64:
            raise ValueError("bone interpolation must be 64 bytes")
        out.append(_BONE.pack(_name_field(k, 15, "bone name"), _frame(k.frame, "bone", k.name), *k.position,
                              *k.rotation, k.interpolation))
    out.append(_COUNT.pack(len(motion.morphs)))
    for k in motion.morphs:
        out.append(_MORPH.pack(_name_field(k, 15, "morph name"), _frame(k.frame, "morph", k.name), k.weight))
    out.append(_COUNT.pack(len(motion.cameras)))
    for k in motion.cameras:
        if len(k.interpolation) != 24:
            raise ValueError("camera interpolation must be 24 bytes")
        out.append(_CAMERA.pack(_frame(k.frame, "camera key"), k.distance, *k.position, *k.rotation,
                                k.interpolation, k.fov, 0 if k.perspective else 1))
    out.append(_COUNT.pack(len(motion.lights)))
    for k in motion.lights:
        out.append(_LIGHT.pack(_frame(k.frame, "light key"), *k.rgb, *k.direction))
    out.append(_COUNT.pack(len(motion.shadows)))
    for k in motion.shadows:
        out.append(_SHADOW.pack(_frame(k.frame, "shadow key"), k.mode, k.distance))
    out.append(_COUNT.pack(len(motion.show_iks)))
    for k in motion.show_iks:
        out.append(struct.pack("<IBI", _frame(k.frame, "show/IK key"), 1 if k.visible else 0, len(k.iks)))
        for name, enabled in k.iks:
            out.append(_fixed(name, 20, "IK bone name") + bytes([1 if enabled else 0]))
    return b"".join(out)


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def at_end(self):
        return self.pos >= len(self.data)

    def unpack(self, st):
        if self.pos + st.size > len(self.data):
            raise ValueError("VMD ends in the middle of a record (offset %d)" % self.pos)
        values = st.unpack_from(self.data, self.pos)
        self.pos += st.size
        return values

    def count(self):
        return self.unpack(_COUNT)[0]


def loads(data):
    if data[:len(MAGIC)] != MAGIC:
        raise ValueError("not a VMD file (bad magic)")
    if len(data) < 54:
        raise ValueError("VMD header is truncated")
    motion = Motion(model_name=_text(data[30:50]))
    r = _Reader(data)
    r.pos = 50
    for _ in range(r.count()):
        v = r.unpack(_BONE)
        motion.bones.append(BoneKey(_text(v[0]), v[1], tuple(v[2:5]), tuple(v[5:9]), v[9], raw_name=_raw(v[0])))
    if r.at_end():
        return motion
    for _ in range(r.count()):
        v = r.unpack(_MORPH)
        motion.morphs.append(MorphKey(_text(v[0]), v[1], v[2], raw_name=_raw(v[0])))
    if r.at_end():
        return motion
    for _ in range(r.count()):
        v = r.unpack(_CAMERA)
        motion.cameras.append(CameraKey(v[0], v[1], tuple(v[2:5]), tuple(v[5:8]), v[9], v[10] == 0, v[8]))
    if r.at_end():
        return motion
    for _ in range(r.count()):
        v = r.unpack(_LIGHT)
        motion.lights.append(LightKey(v[0], tuple(v[1:4]), tuple(v[4:7])))
    if r.at_end():
        return motion
    for _ in range(r.count()):
        v = r.unpack(_SHADOW)
        motion.shadows.append(ShadowKey(v[0], v[1], v[2]))
    if r.at_end():
        return motion
    head = struct.Struct("<IBI")
    item = struct.Struct("<20sB")
    for _ in range(r.count()):
        frame, visible, n = r.unpack(head)
        iks = []
        for _ in range(n):
            name, enabled = r.unpack(item)
            iks.append((_text(name), enabled != 0))
        motion.show_iks.append(ShowIkKey(frame, visible != 0, iks))
    return motion


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())


def dump(motion, path):
    with open(path, "wb") as f:
        f.write(dumps(motion))
