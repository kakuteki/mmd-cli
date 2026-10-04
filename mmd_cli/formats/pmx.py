"""Read PMX (Polygon Model eXtended, versions 2.0 and 2.1) model files: the names, the element counts,
the bone table with its flags, append and IK links, the morph list with panels and kinds, and the
display frames.

The geometry (vertices, faces, textures, materials), rigid bodies, joints and soft bodies are walked
over to reach the tables behind them and are only counted.  Values are kept as stored: IK angles are
radians, indices are 0-based positions in the file's own tables, and the "none" index -1 becomes None.
The layout follows PMXEditor's PMX仕様.txt (2.0 and the 2.1 additions: QDEF weights, flip and impulse
morphs, joint kinds, soft bodies).  formats.pmd fills the same Model from PMD files.
"""
import struct
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

MAGIC = b"PMX "
ENCODINGS = {0: "utf-16-le", 1: "utf-8"}
PANELS = {1: "eyebrow", 2: "eye", 3: "mouth", 4: "other"}
MORPH_KINDS = {0: "group", 1: "vertex", 2: "bone", 3: "uv", 4: "uv1", 5: "uv2", 6: "uv3", 7: "uv4", 8: "material",
               9: "flip", 10: "impulse"}
FLAG_BITS = (("rotate", 0x0002), ("translate", 0x0004), ("visible", 0x0008), ("enabled", 0x0010), ("ik", 0x0020),
             ("append_rotate", 0x0100), ("append_translate", 0x0200), ("fixed_axis", 0x0400), ("local_axis", 0x0800),
             ("physics_after", 0x1000), ("external_parent", 0x2000))
_TAIL_IS_BONE = 0x0001
_INDEX = {1: struct.Struct("<b"), 2: struct.Struct("<h"), 4: struct.Struct("<i")}
_I32 = struct.Struct("<i")
_F32 = struct.Struct("<f")
_U16 = struct.Struct("<H")


class PmxFormatError(ValueError):
    pass


def panel_name(number):
    return PANELS.get(number) or ("system" if number == 0 else "unknown %d" % number)


@dataclass
class Bone:
    index: int
    name: str
    name_en: Optional[str]
    parent: Optional[int]
    layer: int
    flags: Dict[str, bool]
    append: Optional[dict] = None       # {"parent": index, "ratio": float}
    ik: Optional[dict] = None           # {"target": index, "loops": int, "angle": float, "links": [index, ...]}


@dataclass
class Morph:
    index: int
    name: str
    name_en: Optional[str]
    panel: str                          # eyebrow / eye / mouth / other (system for the hidden panel 0)
    kind: str                           # one of MORPH_KINDS
    offsets: int                        # how many offsets the morph holds; their contents are not kept


@dataclass
class DisplayFrame:
    name: str
    name_en: Optional[str]
    special: bool
    items: List[dict] = field(default_factory=list)      # [{"kind": "bone" | "morph", "index": n}, ...]


@dataclass
class Model:
    format: str
    version: float
    name: str
    name_en: Optional[str]
    comment: str
    comment_en: Optional[str]
    counts: Dict[str, int]
    bones: List[Bone] = field(default_factory=list)
    morphs: List[Morph] = field(default_factory=list)
    display_frames: List[DisplayFrame] = field(default_factory=list)

    def to_json(self, brief=False):
        """plain dicts and lists; brief leaves out the three tables and keeps the names and counts"""
        d = asdict(self)
        if brief:
            for key in ("bones", "morphs", "display_frames"):
                d.pop(key)
        return d


class _Reader:
    """a cursor over the file with bounds checks that name the offset (formats.pmd derives its own from it)"""
    kind = "PMX"
    error = PmxFormatError

    def __init__(self, data, encoding="utf-16-le"):
        self.data = data
        self.pos = 0
        self.encoding = encoding

    def at_end(self):
        return self.pos >= len(self.data)

    def need(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise self.error("%s ends unexpectedly at offset %d (wanted %d more bytes)" % (self.kind, self.pos, size))

    def take(self, size):
        self.need(size)
        chunk = self.data[self.pos:self.pos + size]
        self.pos += size
        return chunk

    def skip(self, size):
        self.need(size)
        self.pos += size

    def unpack(self, st):
        self.need(st.size)
        values = st.unpack_from(self.data, self.pos)
        self.pos += st.size
        return values

    def u8(self):
        self.need(1)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self):
        return self.unpack(_U16)[0]

    def i32(self):
        return self.unpack(_I32)[0]

    def f32(self):
        return self.unpack(_F32)[0]

    def plausible(self, n, item_size, what, at):
        """an element count read at `at`, refused before anything is read when the elements could not fit"""
        if n < 0 or n * item_size > len(self.data) - self.pos:
            raise self.error("implausible %s count %d at offset %d (%d bytes remain)"
                             % (what, n, at, len(self.data) - self.pos))
        return n

    def count(self, item_size, what):
        at = self.pos
        return self.plausible(self.i32(), item_size, what, at)

    def text(self):
        at = self.pos
        n = self.i32()
        if n < 0 or n > len(self.data) - self.pos:
            raise self.error("implausible text length %d at offset %d" % (n, at))
        return self.take(n).decode(self.encoding, "replace")

    def index(self, size):
        """a signed index of 1, 2 or 4 bytes (vertex indices are never read: they are only skipped)"""
        return self.unpack(_INDEX[size])[0]


def _optional(index):
    return None if index < 0 else index


def _header(r):
    if len(r.data) < len(MAGIC) or r.data[:len(MAGIC)].upper() != MAGIC:
        raise PmxFormatError("not a PMX file (bad magic)")
    r.pos = len(MAGIC)
    version = round(r.f32(), 2)
    if version not in (2.0, 2.1):
        raise PmxFormatError("PMX version %s is not supported (only 2.0 and 2.1)" % version)
    n = r.u8()
    if n < 8:
        raise PmxFormatError("PMX header declares %d globals, 8 are needed" % n)
    g = r.take(n)
    if g[0] not in ENCODINGS:
        raise PmxFormatError("unknown text encoding %d in the PMX header" % g[0])
    r.encoding = ENCODINGS[g[0]]
    if g[1] > 4:
        raise PmxFormatError("PMX header declares %d additional UV sets (at most 4)" % g[1])
    sizes = {}
    for name, value in zip(("vertex", "texture", "material", "bone", "morph", "rigid"), g[2:8]):
        if value not in (1, 2, 4):
            raise PmxFormatError("%s index size %d in the PMX header is not 1, 2 or 4" % (name, value))
        sizes[name] = value
    return version, g[1], sizes


def _skip_vertices(r, extra_uv, bone_size):
    n = r.count(32 + 16 * extra_uv + 1 + bone_size + 4, "vertex")
    weight_sizes = {0: bone_size, 1: 2 * bone_size + 4, 2: 4 * bone_size + 16, 3: 2 * bone_size + 40, 4: 4 * bone_size + 16}
    fixed = 32 + 16 * extra_uv       # position, normal, uv, additional uvs
    for i in range(n):
        r.skip(fixed)
        at = r.pos
        kind = r.u8()
        if kind not in weight_sizes:
            raise PmxFormatError("vertex %d has an unknown weight type %d at offset %d" % (i, kind, at))
        r.skip(weight_sizes[kind] + 4)          # the weights, then the edge scale
    return n


def _skip_faces(r, vertex_size):
    at = r.pos
    n = r.count(vertex_size, "face index")
    if n % 3:
        raise PmxFormatError("face index count %d at offset %d is not a multiple of 3" % (n, at))
    r.skip(n * vertex_size)
    return n // 3


def _skip_materials(r, texture_size):
    n = r.count(2 * 4 + 65 + 2 * texture_size + 2 + 1 + 4 + 4, "material")
    for _ in range(n):
        r.text()
        r.text()
        r.skip(65)                              # diffuse, specular, ambient, drawing flags, edge colour and size
        r.skip(2 * texture_size)                # texture, sphere texture
        r.u8()                                  # sphere mode
        if r.u8():                              # toon: a shared toon number, or a texture index
            r.u8()
        else:
            r.skip(texture_size)
        r.text()                                # memo
        r.i32()                                 # face index count
    return n


def _bone(r, index, size):
    name, name_en = r.text(), r.text()
    r.skip(12)                                  # position
    parent = _optional(r.index(size))
    layer = r.i32()
    bits = r.u16()
    flags = {name: bool(bits & bit) for name, bit in FLAG_BITS}
    if bits & _TAIL_IS_BONE:
        r.skip(size)
    else:
        r.skip(12)
    append = None
    if flags["append_rotate"] or flags["append_translate"]:
        append = {"parent": _optional(r.index(size)), "ratio": r.f32()}
    if flags["fixed_axis"]:
        r.skip(12)
    if flags["local_axis"]:
        r.skip(24)
    if flags["external_parent"]:
        r.i32()
    ik = None
    if flags["ik"]:
        ik = {"target": _optional(r.index(size)), "loops": r.i32(), "angle": r.f32(), "links": []}
        for _ in range(r.count(size + 1, "IK link")):
            ik["links"].append(_optional(r.index(size)))
            if r.u8():
                r.skip(24)                      # angle limits
    return Bone(index, name, name_en, parent, layer, flags, append, ik)


def _morph(r, index, sizes):
    name, name_en = r.text(), r.text()
    panel, kind = r.u8(), r.u8()
    if kind not in MORPH_KINDS:
        raise PmxFormatError("morph %d (%s) has an unknown kind %d at offset %d" % (index, name, kind, r.pos - 1))
    offset_size = {0: sizes["morph"] + 4, 1: sizes["vertex"] + 12, 2: sizes["bone"] + 28, 8: sizes["material"] + 113,
                   9: sizes["morph"] + 4, 10: sizes["rigid"] + 25}.get(kind, sizes["vertex"] + 16)
    n = r.count(offset_size, "morph offset")
    r.skip(n * offset_size)
    return Morph(index, name, name_en, panel_name(panel), MORPH_KINDS[kind], n)


def _frame(r, sizes):
    name, name_en = r.text(), r.text()
    special = r.u8() != 0
    items = []
    for _ in range(r.count(2, "display frame item")):
        if r.u8():
            items.append({"kind": "morph", "index": r.index(sizes["morph"])})
        else:
            items.append({"kind": "bone", "index": r.index(sizes["bone"])})
    return DisplayFrame(name, name_en, special, items)


def _skip_rigid_bodies(r, bone_size):
    n = r.count(8 + bone_size + 61, "rigid body")
    for _ in range(n):
        r.text()
        r.text()
        r.skip(bone_size + 61)
    return n


def _skip_joints(r, rigid_size):
    n = r.count(8 + 1 + 2 * rigid_size + 96, "joint")
    for _ in range(n):
        r.text()
        r.text()
        r.skip(1 + 2 * rigid_size + 96)
    return n


def _skip_soft_bodies(r, sizes):
    n = r.count(8 + 1 + sizes["material"] + 124 + 8, "soft body")
    for _ in range(n):
        r.text()
        r.text()
        r.skip(1 + sizes["material"] + 124)
        anchors = r.count(sizes["rigid"] + sizes["vertex"] + 1, "soft body anchor")
        r.skip(anchors * (sizes["rigid"] + sizes["vertex"] + 1))
        pins = r.count(sizes["vertex"], "soft body pin")
        r.skip(pins * sizes["vertex"])
    return n


def loads(data):
    r = _Reader(data)
    version, extra_uv, sizes = _header(r)
    name, name_en, comment, comment_en = r.text(), r.text(), r.text(), r.text()
    counts = {"vertices": _skip_vertices(r, extra_uv, sizes["bone"]), "faces": _skip_faces(r, sizes["vertex"])}
    counts["textures"] = r.count(4, "texture")
    for _ in range(counts["textures"]):
        r.text()
    counts["materials"] = _skip_materials(r, sizes["texture"])
    # the smallest bone: two empty names, position, parent, layer, flags and a tail given as a bone index
    bones = [_bone(r, i, sizes["bone"]) for i in range(r.count(26 + 2 * sizes["bone"], "bone"))]
    morphs = [_morph(r, i, sizes) for i in range(r.count(8 + 2 + 4, "morph"))]
    frames = [_frame(r, sizes) for _ in range(r.count(8 + 1 + 4, "display frame"))]
    counts.update(bones=len(bones), morphs=len(morphs), display_frames=len(frames))
    counts["rigid_bodies"] = _skip_rigid_bodies(r, sizes["bone"])
    counts["joints"] = _skip_joints(r, sizes["rigid"])
    counts["soft_bodies"] = _skip_soft_bodies(r, sizes) if version >= 2.1 and not r.at_end() else 0
    if not r.at_end():
        raise PmxFormatError("%d bytes are left after the last known field: the layout was misread"
                             % (len(data) - r.pos))
    return Model("pmx", version, name, name_en, comment, comment_en, counts, bones, morphs, frames)


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())
