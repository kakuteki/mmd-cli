"""Read and write VMD (Vocaloid Motion Data) files.

Values are kept exactly as they are stored in the file: bone rotations are quaternions
(x, y, z, w), camera rotations are radians with the X angle negated relative to what the
MMD window shows, and the camera distance is negative.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Tuple

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


@dataclass
class MorphKey:
    name: str
    frame: int
    weight: float


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


def _fixed(text, size, what):
    raw = text.encode(ENCODING)
    if len(raw) > size:
        raise ValueError("%s %r does not fit in %d bytes (cp932)" % (what, text, size))
    return raw.ljust(size, b"\x00")


def _truncated(text, size):
    """encode, cutting on a character boundary when the text is too long for the field"""
    while len(text.encode(ENCODING)) > size:
        text = text[:-1]
    return text.encode(ENCODING).ljust(size, b"\x00")


def _text(raw):
    return raw.split(b"\x00", 1)[0].decode(ENCODING, "replace")


def dumps(motion):
    out = [MAGIC.ljust(30, b"\x00"), _truncated(motion.model_name, 20)]
    out.append(_COUNT.pack(len(motion.bones)))
    for k in motion.bones:
        if len(k.interpolation) != 64:
            raise ValueError("bone interpolation must be 64 bytes")
        out.append(_BONE.pack(_fixed(k.name, 15, "bone name"), k.frame, *k.position, *k.rotation, k.interpolation))
    out.append(_COUNT.pack(len(motion.morphs)))
    for k in motion.morphs:
        out.append(_MORPH.pack(_fixed(k.name, 15, "morph name"), k.frame, k.weight))
    out.append(_COUNT.pack(len(motion.cameras)))
    for k in motion.cameras:
        if len(k.interpolation) != 24:
            raise ValueError("camera interpolation must be 24 bytes")
        out.append(_CAMERA.pack(k.frame, k.distance, *k.position, *k.rotation, k.interpolation, k.fov,
                                0 if k.perspective else 1))
    out.append(_COUNT.pack(len(motion.lights)))
    for k in motion.lights:
        out.append(_LIGHT.pack(k.frame, *k.rgb, *k.direction))
    out.append(_COUNT.pack(len(motion.shadows)))
    for k in motion.shadows:
        out.append(_SHADOW.pack(k.frame, k.mode, k.distance))
    out.append(_COUNT.pack(len(motion.show_iks)))
    for k in motion.show_iks:
        out.append(struct.pack("<IBI", k.frame, 1 if k.visible else 0, len(k.iks)))
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
        motion.bones.append(BoneKey(_text(v[0]), v[1], tuple(v[2:5]), tuple(v[5:9]), v[9]))
    if r.at_end():
        return motion
    for _ in range(r.count()):
        v = r.unpack(_MORPH)
        motion.morphs.append(MorphKey(_text(v[0]), v[1], v[2]))
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
