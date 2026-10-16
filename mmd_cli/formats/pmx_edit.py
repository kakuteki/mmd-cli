"""Edit PMX files: read the whole file into a Document that dumps() writes back byte for byte, change the vertices'
weights, insert bones (every bone index in the file is moved: vertex weights, parents, tails, appends, IK targets and
links, bone morphs, display frames, rigid bodies).

formats.pmx reads a PMX for inspection and skips the geometry; this module keeps every byte.  The parts the Document
does not unpack (faces, textures, materials, the other morph kinds, the rigid bodies' fields, joints, soft bodies) stay
raw bytes; rigid_body() / set_rigid_body(), joints() / set_joints() and geometry() / set_geometry() read and write them
on demand (byte for byte when nothing is changed).  Index sizes are kept: an insertion that no longer fits the file's
bone index size is refused.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .pmx import ENCODINGS, PmxFormatError, _Reader, _header

WEIGHT_KINDS = {0: "BDEF1", 1: "BDEF2", 2: "BDEF4", 3: "SDEF", 4: "QDEF"}
_KIND_CODE = {v: k for k, v in WEIGHT_KINDS.items()}
_SIGNED = {1: "<b", 2: "<h", 4: "<i"}
_UNSIGNED = {1: "<B", 2: "<H", 4: "<i"}
_LIMITS = {1: 127, 2: 32767, 4: 2 ** 31 - 1}


@dataclass
class Vertex:
    head: bytes                 # position, normal, uv, additional uvs (raw)
    kind: str
    bones: List[int]
    weights: List[float]        # BDEF2 / SDEF: [w0]; BDEF4 / QDEF: four; BDEF1: []
    sdef: bytes                 # C, R0, R1 for SDEF (raw)
    edge: bytes

    def position(self):
        return struct.unpack_from("<3f", self.head, 0)

    def pairs(self):
        """[(bone, weight)] with the weights as they deform"""
        if self.kind == "BDEF1":
            return [(self.bones[0], 1.0)]
        if self.kind in ("BDEF2", "SDEF"):
            return [(self.bones[0], self.weights[0]), (self.bones[1], 1.0 - self.weights[0])]
        return list(zip(self.bones, self.weights))

    def set_weights(self, pairs):
        """BDEF1 / BDEF2 / BDEF4 from [(bone, weight)]: merged per bone, the four largest, normalized, largest first"""
        merged = {}
        for b, w in pairs:
            if w > 0.0:
                merged[b] = merged.get(b, 0.0) + w
        items = sorted(merged.items(), key=lambda bw: -bw[1])[:4]
        total = sum(w for _, w in items)
        if not items or total <= 0.0:
            raise ValueError("a vertex needs a positive weight")
        items = [(b, w / total) for b, w in items]
        self.sdef = b""
        if len(items) == 1:
            self.kind, self.bones, self.weights = "BDEF1", [items[0][0]], []
        elif len(items) == 2:
            self.kind, self.bones, self.weights = "BDEF2", [items[0][0], items[1][0]], [items[0][1]]
        else:
            while len(items) < 4:
                items.append((items[0][0], 0.0))        # padding: the first bone again with no weight
            self.kind, self.bones, self.weights = "BDEF4", [b for b, _ in items], [w for _, w in items]


@dataclass
class BoneRec:
    name: str
    name_en: str
    position: tuple
    parent: int                 # -1 for none
    layer: int
    flags: int
    tail_bone: int = -1         # when flags & 1
    tail_offset: tuple = (0.0, 0.0, 0.0)
    append_parent: int = -1
    append_ratio: float = 0.0
    fixed_axis: Optional[tuple] = None
    local_axes: Optional[tuple] = None   # six floats
    external_key: int = 0
    ik_target: int = -1
    ik_loops: int = 0
    ik_angle: float = 0.0
    ik_links: list = field(default_factory=list)   # [(bone, limits bytes or None)]


@dataclass
class Morph:
    head: bytes                 # names, panel, kind (raw)
    kind: int
    count: int
    body: bytes                 # the offsets (raw) for every kind but bones
    bone_offsets: list = field(default_factory=list)   # [(bone, 28 bytes)] for kind 2


@dataclass
class Frame:
    names: bytes                # both names and the special byte (raw)
    items: list                 # [(0 bone / 1 morph, index)]


@dataclass
class Rigid:
    names: bytes
    bone: int
    rest: bytes                 # 61 bytes


@dataclass
class Document:
    header: bytes               # magic .. comments (raw)
    encoding: str
    sizes: dict
    extra_uv: int
    vertices: List[Vertex]
    middle: bytes               # faces, textures, materials (raw)
    bones: List[BoneRec]
    morphs: List[Morph]
    frames: List[Frame]
    rigid_bodies: List[Rigid]
    tail: bytes                 # joints and soft bodies (raw)

    def morph_bone_offsets(self, i):
        return self.morphs[i].bone_offsets

    def bone_index(self, name):
        for i, b in enumerate(self.bones):
            if b.name == name:
                return i
        raise KeyError(name)


def _idx(r, size, unsigned=False):
    return r.unpack(struct.Struct((_UNSIGNED if unsigned else _SIGNED)[size]))[0]


def _vertex(r, extra_uv, bsize):
    head = r.take(32 + 16 * extra_uv)
    code = r.u8()
    if code not in WEIGHT_KINDS:
        raise PmxFormatError("unknown weight type %d at offset %d" % (code, r.pos - 1))
    kind = WEIGHT_KINDS[code]
    n = {"BDEF1": 1, "BDEF2": 2, "SDEF": 2}.get(kind, 4)
    bones = [_idx(r, bsize) for _ in range(n)]
    nw = {"BDEF1": 0, "BDEF2": 1, "SDEF": 1}.get(kind, 4)
    weights = [r.f32() for _ in range(nw)]
    sdef = r.take(36) if kind == "SDEF" else b""
    return Vertex(head, kind, bones, weights, sdef, r.take(4))


def _text(r):
    return r.text()


def _bone(r, size):
    name, name_en = r.text(), r.text()
    position = r.vec3()
    parent = _idx(r, size)
    layer = r.i32()
    flags = r.u16()
    b = BoneRec(name, name_en, position, parent, layer, flags)
    if flags & 0x0001:
        b.tail_bone = _idx(r, size)
    else:
        b.tail_offset = r.vec3()
    if flags & 0x0300:
        b.append_parent, b.append_ratio = _idx(r, size), r.f32()
    if flags & 0x0400:
        b.fixed_axis = r.vec3()
    if flags & 0x0800:
        b.local_axes = r.vec3() + r.vec3()
    if flags & 0x2000:
        b.external_key = r.i32()
    if flags & 0x0020:
        b.ik_target, b.ik_loops, b.ik_angle = _idx(r, size), r.i32(), r.f32()
        for _ in range(r.i32()):
            link = _idx(r, size)
            b.ik_links.append((link, r.take(24) if r.u8() else None))
    return b


def loads(data):
    r = _Reader(data)
    version, extra_uv, sizes = _header(r)
    for _ in range(4):
        r.text()
    header = data[:r.pos]
    vertices = [_vertex(r, extra_uv, sizes["bone"]) for _ in range(r.i32())]
    start = r.pos
    from .pmx import _skip_faces, _skip_materials
    _skip_faces(r, sizes["vertex"])
    for _ in range(r.i32()):
        r.text()
    _skip_materials(r, sizes["texture"])
    middle = data[start:r.pos]
    bones = [_bone(r, sizes["bone"]) for _ in range(r.i32())]
    morphs = []
    for _ in range(r.i32()):
        at = r.pos
        r.text()
        r.text()
        r.u8()
        kind = r.u8()
        head = data[at:r.pos]
        n = r.i32()
        if kind == 2:
            offsets = [(_idx(r, sizes["bone"]), r.take(28)) for _ in range(n)]
            morphs.append(Morph(head, kind, n, b"", offsets))
        else:
            size = {0: sizes["morph"] + 4, 1: sizes["vertex"] + 12, 8: sizes["material"] + 113,
                    9: sizes["morph"] + 4, 10: sizes["rigid"] + 25}.get(kind, sizes["vertex"] + 16)
            morphs.append(Morph(head, kind, n, r.take(n * size)))
    frames = []
    for _ in range(r.i32()):
        at = r.pos
        r.text()
        r.text()
        r.u8()
        names = data[at:r.pos]
        items = []
        for _ in range(r.i32()):
            k = r.u8()
            items.append((k, _idx(r, sizes["morph"] if k else sizes["bone"])))
        frames.append(Frame(names, items))
    rigids = []
    for _ in range(r.i32()):
        at = r.pos
        r.text()
        r.text()
        names = data[at:r.pos]
        rigids.append(Rigid(names, _idx(r, sizes["bone"]), r.take(61)))
    tail = data[r.pos:]
    return Document(header, ENCODINGS[data[9]], sizes, extra_uv, vertices, middle, bones, morphs, frames, rigids, tail)


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())


def _pack_idx(value, size):
    if not -1 <= value <= _LIMITS[size]:
        raise PmxFormatError("index %d does not fit %d bytes" % (value, size))
    return struct.pack(_SIGNED[size], value)


def _pack_text(s, encoding):
    raw = s.encode(encoding)
    return struct.pack("<i", len(raw)) + raw


def dumps(doc):
    bs = doc.sizes["bone"]
    out = [doc.header, struct.pack("<i", len(doc.vertices))]
    for v in doc.vertices:
        out += [v.head, bytes([_KIND_CODE[v.kind]])]
        out += [_pack_idx(b, bs) for b in v.bones]
        out += [struct.pack("<f", w) for w in v.weights]
        out += [v.sdef, v.edge]
    out.append(doc.middle)
    out.append(struct.pack("<i", len(doc.bones)))
    for b in doc.bones:
        out += [_pack_text(b.name, doc.encoding), _pack_text(b.name_en, doc.encoding), struct.pack("<3f", *b.position),
                _pack_idx(b.parent, bs), struct.pack("<iH", b.layer, b.flags)]
        out.append(_pack_idx(b.tail_bone, bs) if b.flags & 0x0001 else struct.pack("<3f", *b.tail_offset))
        if b.flags & 0x0300:
            out.append(_pack_idx(b.append_parent, bs) + struct.pack("<f", b.append_ratio))
        if b.flags & 0x0400:
            out.append(struct.pack("<3f", *b.fixed_axis))
        if b.flags & 0x0800:
            out.append(struct.pack("<6f", *b.local_axes))
        if b.flags & 0x2000:
            out.append(struct.pack("<i", b.external_key))
        if b.flags & 0x0020:
            out.append(_pack_idx(b.ik_target, bs) + struct.pack("<ifi", b.ik_loops, b.ik_angle, len(b.ik_links)))
            for link, limits in b.ik_links:
                out.append(_pack_idx(link, bs) + (b"\x01" + limits if limits is not None else b"\x00"))
    out.append(struct.pack("<i", len(doc.morphs)))
    for m in doc.morphs:
        if m.kind == 2:
            out += [m.head, struct.pack("<i", len(m.bone_offsets))]
            out += [_pack_idx(b, bs) + raw for b, raw in m.bone_offsets]
        else:
            out += [m.head, struct.pack("<i", m.count), m.body]
    out.append(struct.pack("<i", len(doc.frames)))
    for f in doc.frames:
        out += [f.names, struct.pack("<i", len(f.items))]
        out += [bytes([k]) + _pack_idx(i, doc.sizes["morph"] if k else bs) for k, i in f.items]
    out.append(struct.pack("<i", len(doc.rigid_bodies)))
    for rb in doc.rigid_bodies:
        out += [rb.names, _pack_idx(rb.bone, bs), rb.rest]
    out.append(doc.tail)
    return b"".join(out)


def dump(doc, path):
    with open(path, "wb") as f:
        f.write(dumps(doc))


# ---- rigid bodies, joints, faces / textures / materials (read and written on demand) ----------------------------------

_RIGID = struct.Struct("<BHB3f3f3f5fB")      # the 61 bytes after a rigid body's names and bone
RIGID_SHAPES = {0: "sphere", 1: "box", 2: "capsule"}
RIGID_MODES = {0: "bone", 1: "physics", 2: "physics_bone"}   # follows its bone / physics / physics, bone's position kept


@dataclass
class RigidBody:
    """a rigid body's fields as PMX stores them: rotations in radians, the size as the shape's half extents (sphere:
    radius; capsule: radius, height), `mask` the 16 groups it collides with (bit set = collides)"""
    group: int
    mask: int
    shape: int
    size: tuple
    position: tuple
    rotation: tuple
    mass: float
    linear_damping: float
    angular_damping: float
    restitution: float
    friction: float
    mode: int


def rigid_body(rb):
    """the fields of `rb` (a Document's Rigid)"""
    v = _RIGID.unpack(rb.rest)
    return RigidBody(v[0], v[1], v[2], v[3:6], v[6:9], v[9:12], v[12], v[13], v[14], v[15], v[16], v[17])


def set_rigid_body(rb, body):
    """write `body` (a RigidBody) into `rb`"""
    if body.shape not in RIGID_SHAPES or body.mode not in RIGID_MODES:
        raise ValueError("unknown rigid body shape %r or mode %r" % (body.shape, body.mode))
    if not 0 <= body.group <= 15 or not 0 <= body.mask <= 0xFFFF:
        raise ValueError("rigid body group %r or mask %r out of range" % (body.group, body.mask))
    for what in ("size", "position", "rotation"):
        if len(getattr(body, what)) != 3:
            raise ValueError("rigid body %s needs three values" % what)
    rb.rest = _RIGID.pack(body.group, body.mask, body.shape, *body.size, *body.position, *body.rotation, body.mass,
                          body.linear_damping, body.angular_damping, body.restitution, body.friction, body.mode)


def new_rigid(doc, name, name_en, bone, body):
    """a Rigid for `doc` named `name` on bone index `bone` (-1: none) with the fields of `body` (a RigidBody); append it
    to doc.rigid_bodies yourself (at the end, so no joint's index moves)"""
    if not -1 <= bone < len(doc.bones):
        raise ValueError("rigid body %s names bone %d, the model has %d" % (name, bone, len(doc.bones)))
    rb = Rigid(_pack_text(name, doc.encoding) + _pack_text(name_en, doc.encoding), bone, b"")
    set_rigid_body(rb, body)
    return rb


def rigid_names(doc, rb):
    """(name, English name) of `rb`"""
    r = _Reader(rb.names, doc.encoding)
    return r.text(), r.text()


@dataclass
class Joint:
    """a joint as PMX stores it (rotations and rotation limits in radians; the limits and springs per axis X, Y, Z of
    the joint's frame).  `a` and `b` are rigid body indices."""
    name: str
    name_en: str
    kind: int
    a: int
    b: int
    position: tuple
    rotation: tuple
    move_lower: tuple
    move_upper: tuple
    rotate_lower: tuple
    rotate_upper: tuple
    spring_move: tuple
    spring_rotate: tuple


def _split_tail(doc):
    """(joints, the bytes after them: soft bodies or nothing)"""
    r = _Reader(doc.tail, doc.encoding)
    out = []
    for _ in range(r.i32()):
        name, name_en = r.text(), r.text()
        kind = r.u8()
        a, b = _idx(r, doc.sizes["rigid"]), _idx(r, doc.sizes["rigid"])
        v = r.unpack(struct.Struct("<24f"))
        out.append(Joint(name, name_en, kind, a, b, v[0:3], v[3:6], v[6:9], v[9:12], v[12:15], v[15:18], v[18:21], v[21:24]))
    return out, doc.tail[r.pos:]


def joints(doc):
    """the joints of `doc` (read from its raw tail)"""
    return _split_tail(doc)[0]


def set_joints(doc, items):
    """write `items` (Joints) as the joints of `doc`; the soft bodies after them are kept"""
    rest = _split_tail(doc)[1]
    n = len(doc.rigid_bodies)
    out = [struct.pack("<i", len(items))]
    for j in items:
        if not (-1 <= j.a < n and -1 <= j.b < n):
            raise ValueError("joint %s joins rigid bodies %d and %d, the model has %d" % (j.name, j.a, j.b, n))
        if not 0 <= j.kind <= 255:
            raise ValueError("joint %s has kind %r" % (j.name, j.kind))
        values = [j.position, j.rotation, j.move_lower, j.move_upper, j.rotate_lower, j.rotate_upper, j.spring_move, j.spring_rotate]
        if any(len(v) != 3 for v in values):
            raise ValueError("joint %s needs three values per vector" % j.name)
        out += [_pack_text(j.name, doc.encoding), _pack_text(j.name_en, doc.encoding), bytes([j.kind]),
                _pack_idx(j.a, doc.sizes["rigid"]), _pack_idx(j.b, doc.sizes["rigid"]),
                struct.pack("<24f", *[x for v in values for x in v])]
    doc.tail = b"".join(out) + rest


@dataclass
class Material:
    """a material as PMX stores it; `flags`: 0x01 both sides, 0x02 ground shadow, 0x04 casts on the self shadow map,
    0x08 receives the self shadow, 0x10 edge; `toon` is a shared toon number (0-9) when shared_toon is 1, else a
    texture index; `faces` the count of face vertex indices it draws"""
    name: str
    name_en: str
    diffuse: tuple
    specular: tuple
    specular_power: float
    ambient: tuple
    flags: int
    edge_color: tuple
    edge_size: float
    texture: int
    sphere: int
    sphere_mode: int
    shared_toon: int
    toon: int
    memo: str
    faces: int


@dataclass
class Geometry:
    faces: List[int]            # vertex indices, three per triangle, in the materials' order
    textures: List[str]
    materials: List[Material]


def geometry(doc):
    """the faces, textures and materials of `doc` (read from its raw middle)"""
    r = _Reader(doc.middle, doc.encoding)
    vs, ts = doc.sizes["vertex"], doc.sizes["texture"]
    vfmt = struct.Struct((_UNSIGNED if vs < 4 else _SIGNED)[vs])
    faces = [r.unpack(vfmt)[0] for _ in range(r.i32())]
    textures = [r.text() for _ in range(r.i32())]
    materials = []
    for _ in range(r.i32()):
        name, name_en = r.text(), r.text()
        v = r.unpack(struct.Struct("<4f3ff3f"))
        flags = r.u8()
        e = r.unpack(struct.Struct("<4ff"))
        texture, sphere = _idx(r, ts), _idx(r, ts)
        sphere_mode, shared = r.u8(), r.u8()
        toon = r.u8() if shared else _idx(r, ts)
        memo = r.text()
        materials.append(Material(name, name_en, v[0:4], v[4:7], v[7], v[8:11], flags, e[0:4], e[4], texture, sphere,
                                  sphere_mode, shared, toon, memo, r.i32()))
    if not r.at_end():
        raise PmxFormatError("%d bytes are left after the materials" % (len(doc.middle) - r.pos))
    return Geometry(faces, textures, materials)


def set_geometry(doc, g):
    """write `g` (Geometry) as the faces, textures and materials of `doc`"""
    if sum(m.faces for m in g.materials) != len(g.faces) or len(g.faces) % 3:
        raise ValueError("the materials draw %d face indices, there are %d" % (sum(m.faces for m in g.materials), len(g.faces)))
    vs, ts = doc.sizes["vertex"], doc.sizes["texture"]
    n = len(doc.vertices)
    if any(not 0 <= i < n for i in g.faces):
        raise ValueError("a face names a vertex outside 0..%d" % (n - 1))
    vfmt = (_UNSIGNED if vs < 4 else _SIGNED)[vs]
    if n - 1 > {1: 255, 2: 65535, 4: 2 ** 31 - 1}[vs]:
        raise PmxFormatError("the vertex index size of the file cannot hold %d vertices" % n)
    out = [struct.pack("<i", len(g.faces)), struct.pack("<%d%s" % (len(g.faces), vfmt[1]), *g.faces),
           struct.pack("<i", len(g.textures))]
    out += [_pack_text(t, doc.encoding) for t in g.textures]
    out.append(struct.pack("<i", len(g.materials)))
    for m in g.materials:
        if len(m.diffuse) != 4 or len(m.specular) != 3 or len(m.ambient) != 3 or len(m.edge_color) != 4:
            raise ValueError("material %s has a colour of the wrong length" % m.name)
        out += [_pack_text(m.name, doc.encoding), _pack_text(m.name_en, doc.encoding),
                struct.pack("<4f3ff3f", *m.diffuse, *m.specular, m.specular_power, *m.ambient), bytes([m.flags]),
                struct.pack("<4ff", *m.edge_color, m.edge_size), _pack_idx(m.texture, ts), _pack_idx(m.sphere, ts),
                bytes([m.sphere_mode, m.shared_toon])]
        out.append(bytes([m.toon]) if m.shared_toon else _pack_idx(m.toon, ts))
        out += [_pack_text(m.memo, doc.encoding), struct.pack("<i", m.faces)]
    doc.middle = b"".join(out)


def new_bone(name, name_en="", position=(0.0, 0.0, 0.0), parent=-1, layer=0, tail_offset=(0.0, 0.0, 0.0)):
    """a visible, enabled, rotatable bone (not translatable)"""
    return BoneRec(name, name_en, tuple(position), parent, layer, 0x0002 | 0x0008 | 0x0010, tail_offset=tuple(tail_offset))


def insert_bone(doc, at, bone):
    """insert `bone` (its own indices given in the numbering after the insertion) at position `at`; every bone index
    already in the file that is >= at moves up by one.  Returns `at`."""
    if len(doc.bones) + 1 > _LIMITS[doc.sizes["bone"]] + 1:
        raise PmxFormatError("the bone index size of the file cannot hold another bone")

    def m(i):
        return i + 1 if i >= at else i
    for v in doc.vertices:
        v.bones = [m(b) if b >= 0 else b for b in v.bones]
    for b in doc.bones:
        b.parent = m(b.parent) if b.parent >= 0 else -1
        if b.flags & 0x0001 and b.tail_bone >= 0:
            b.tail_bone = m(b.tail_bone)
        if b.flags & 0x0300 and b.append_parent >= 0:
            b.append_parent = m(b.append_parent)
        if b.flags & 0x0020:
            b.ik_target = m(b.ik_target) if b.ik_target >= 0 else -1
            b.ik_links = [(m(l) if l >= 0 else l, lim) for l, lim in b.ik_links]
    for mo in doc.morphs:
        mo.bone_offsets = [(m(b) if b >= 0 else b, raw) for b, raw in mo.bone_offsets]
    for f in doc.frames:
        f.items = [(k, i if k or i < 0 else m(i)) for k, i in f.items]
    for rb in doc.rigid_bodies:
        rb.bone = m(rb.bone) if rb.bone >= 0 else -1
    doc.bones.insert(at, bone)
    return at
