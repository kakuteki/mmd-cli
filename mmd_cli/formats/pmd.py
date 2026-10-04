"""Read PMD (Polygon Model Data 1.0, the format before PMX) model files into the Model of formats.pmx.

Strings are cp932, cut at the first NUL, bytes that do not decode become U+FFFD.  The geometry is
only counted (counts["textures"] is the number of distinct texture file names the materials use).
Values are kept as stored; in particular the IK angle is the file's value, which PMX stores times 4
as radians (the standard leg IK is 0.5 here and 2.0 in PMX files, the toe IK 1.0 and 4.0).

Bone types (one byte per bone) and the PMX-style flags they become.  Measured on the 13 models
shipped with MMD 9.32: bones of types 0, 1, 2, 4, 5 and 8 are the ones that appear in the bone
display frames, so those are called visible; PMD has no separate "enabled" (操作可) flag and MMD
cannot operate a bone it does not show, so enabled follows visible.  Every bone rotates
(a hidden tip bone still takes motion data).  layer is always 0 and append_translate, local_axis,
physics_after and external_parent are always False: PMD has none of these.

  type  meaning       rotate translate visible enabled ik   append                         fixed_axis
  0     回転          yes    no        yes     yes     no   -                              no
  1     回転と移動    yes    yes       yes     yes     no   -                              no
  2     IK            yes    yes       yes     yes     yes  -                              no
  3     不明          yes    no        no      no      no   -                              no   (never seen; treated as hidden)
  4     IK影響下      yes    no        yes     yes     no   -                              no
  5     回転影響下    yes    no        yes     yes     no   parent = ik_parent, ratio 1.0  no
  6     IK接続先      yes    no        no      no      no   -                              no
  7     非表示        yes    no        no      no      no   -                              no
  8     捻り          yes    no        yes     yes     no   -                              yes  (the axis points at the tail bone)
  9     回転運動      yes    no        no      no      no   parent = tail, ratio = ik_parent / 100  no

For type 9 the tail field is the bone whose rotation is copied and the ik_parent field is the share in
percent (初音ミクVer2.pmd: 左腕捩1/2/3 take 25/50/75 of 左腕捩); for type 5 the ik_parent field is the
source bone (左目 follows 両目).  A bone named in the IK table gets its IK data and flags["ik"] whatever
its type says.

Morph indices are the file's skin numbers.  Skin 0 is the "base" shape: MMD keeps it as morph 0 in
its own lists (a pmm names it) but never shows it, so it is left out of `morphs` and of counts["morphs"]
while the other skins keep their numbers.  The 表情枠 (the skins shown in the morph panel) becomes a
special display frame named 表情 with morph items, placed first; the bone frames follow in file order,
their names without the trailing newline the format stores, each holding the bones assigned to it
(センター belongs to no frame: MMD lists it on its own).

The English block, the toon texture names, the rigid bodies and the joints are trailing sections a
file may stop before (counts are then 0 and English names None); a section that has begun must be
complete.
"""
import struct

from .pmx import FLAG_BITS, Bone, DisplayFrame, Model, Morph, _Reader as _PmxReader, panel_name

MAGIC = b"Pmd"
ENCODING = "cp932"
BONE_TYPES = {0: "rotate", 1: "rotate and translate", 2: "IK", 3: "unknown", 4: "under IK", 5: "under rotation",
              6: "IK target", 7: "hidden", 8: "twist", 9: "rotation motion"}
_SHOWN_TYPES = (0, 1, 2, 4, 5, 8)
_HEADER = struct.Struct("<3sf20s256s")
_BONE = struct.Struct("<20shhBH3f")
_IK = struct.Struct("<HHBHf")
_BONE_DISPLAY = struct.Struct("<HB")
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_VERTEX_SIZE, _MATERIAL_SIZE, _SKIN_VERTEX_SIZE, _RIGID_BODY_SIZE, _JOINT_SIZE = 38, 70, 16, 83, 124
_TOON_BLOCK_SIZE = 10 * 100


class PmdFormatError(ValueError):
    pass


def _text(raw):
    return raw.split(b"\x00", 1)[0].decode(ENCODING, "replace")


def _frame_name(text):
    return text.rstrip("\r\n")


class _Reader(_PmxReader):
    kind = "PMD"
    error = PmdFormatError

    def __init__(self, data):
        _PmxReader.__init__(self, data, ENCODING)

    def u32(self):
        return self.unpack(_U32)[0]

    def count8(self, item_size, what):
        at = self.pos
        return self.plausible(self.u8(), item_size, what, at)

    def count16(self, item_size, what):
        at = self.pos
        return self.plausible(self.unpack(_U16)[0], item_size, what, at)

    def count32(self, item_size, what):
        at = self.pos
        return self.plausible(self.u32(), item_size, what, at)

    def fixed(self, size):
        return _text(self.take(size))


def _bone(index, raw, ik, name_en):
    name, parent, tail, kind, ik_parent = _text(raw[0]), raw[1], raw[2], raw[3], raw[4]
    shown = kind in _SHOWN_TYPES
    flags = {flag: False for flag, _ in FLAG_BITS}
    flags.update(rotate=True, translate=kind in (1, 2), visible=shown, enabled=shown, ik=kind == 2 or ik is not None,
                 append_rotate=kind in (5, 9), fixed_axis=kind == 8)
    append = None
    if kind == 5:
        append = {"parent": ik_parent, "ratio": 1.0}
    elif kind == 9:
        append = {"parent": tail, "ratio": ik_parent / 100.0}
    return Bone(index, name, name_en, None if parent < 0 else parent, 0, flags, append, ik)


def loads(data):
    if data[:len(MAGIC)] != MAGIC:
        raise PmdFormatError("not a PMD file (bad magic)")
    r = _Reader(data)
    _, version, name, comment = r.unpack(_HEADER)
    version = round(version, 2)
    if version != 1.0:
        raise PmdFormatError("PMD version %s is not supported (only 1.0)" % version)
    counts = {"vertices": r.count32(_VERTEX_SIZE, "vertex")}
    r.skip(counts["vertices"] * _VERTEX_SIZE)
    at = r.pos
    n = r.count32(2, "face index")
    if n % 3:
        raise PmdFormatError("face index count %d at offset %d is not a multiple of 3" % (n, at))
    r.skip(n * 2)
    counts["faces"] = n // 3
    materials = r.count32(_MATERIAL_SIZE, "material")
    textures = set()
    for _ in range(materials):
        for part in _text(r.take(_MATERIAL_SIZE)[50:]).split("*"):       # "texture.bmp*sphere.sph"
            if part:
                textures.add(part)
    counts.update(textures=len(textures), materials=materials)

    raw_bones = [r.unpack(_BONE) for _ in range(r.count16(_BONE.size, "bone"))]
    iks = {}
    for _ in range(r.count16(_IK.size, "IK")):
        bone_index, target, chain, loops, angle = r.unpack(_IK)
        links = list(r.unpack(struct.Struct("<%dH" % chain)))
        iks.setdefault(bone_index, {"target": target, "loops": loops, "angle": angle, "links": links})
    skins = []
    for _ in range(r.count16(25, "skin")):
        skin_name = r.fixed(20)
        vertices = r.count32(_SKIN_VERTEX_SIZE, "skin vertex")
        kind = r.u8()
        r.skip(vertices * _SKIN_VERTEX_SIZE)
        skins.append((skin_name, kind, vertices))
    skin_display = [r.unpack(_U16)[0] for _ in range(r.count8(2, "skin display"))]
    frame_names = [r.fixed(50) for _ in range(r.count8(50, "bone frame"))]
    bone_display = [r.unpack(_BONE_DISPLAY) for _ in range(r.count32(_BONE_DISPLAY.size, "bone display"))]

    english = None
    if not r.at_end() and r.u8():
        english = {"name": r.fixed(20), "comment": r.fixed(256), "bones": [r.fixed(20) for _ in raw_bones],
                   "skins": [r.fixed(20) for _ in range(max(len(skins) - 1, 0))],
                   "frames": [r.fixed(50) for _ in frame_names]}
    if not r.at_end():
        r.skip(_TOON_BLOCK_SIZE)
    rigid_bodies = joints = 0
    if not r.at_end():
        rigid_bodies = r.count32(_RIGID_BODY_SIZE, "rigid body")
        r.skip(rigid_bodies * _RIGID_BODY_SIZE)
    if not r.at_end():
        joints = r.count32(_JOINT_SIZE, "joint")
        r.skip(joints * _JOINT_SIZE)
    if not r.at_end():
        raise PmdFormatError("%d bytes are left after the last known field: the layout was misread"
                             % (len(data) - r.pos))

    bones = [_bone(i, raw, iks.get(i), english["bones"][i] if english else None) for i, raw in enumerate(raw_bones)]
    morphs = [Morph(i, skin_name, english["skins"][i - 1] if english and i >= 1 else None, panel_name(kind), "vertex", n)
              for i, (skin_name, kind, n) in enumerate(skins) if kind != 0]
    frames = [DisplayFrame("表情", None, True, [{"kind": "morph", "index": s} for s in skin_display])]
    for i, frame_name in enumerate(frame_names):
        items = [{"kind": "bone", "index": b} for b, f in bone_display if f == i + 1]
        frames.append(DisplayFrame(_frame_name(frame_name), _frame_name(english["frames"][i]) if english else None, False, items))
    counts.update(bones=len(bones), morphs=len(morphs), display_frames=len(frames), rigid_bodies=rigid_bodies, joints=joints,
                  soft_bodies=0)                 # PMD has none; the key keeps the two formats' JSON alike
    return Model("pmd", version, _text(name), english["name"] if english else None, _text(comment),
                 english["comment"] if english else None, counts, bones, morphs, frames)


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())
