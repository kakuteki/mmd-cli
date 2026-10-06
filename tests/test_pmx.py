"""formats.pmx: small PMX files built here byte by byte, and the models shipped with MMD when they are present."""
import os
import struct
import unittest

from mmd_cli.formats import pmx

MODEL_DIR = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model"
RIN = os.path.join(MODEL_DIR, "Sour式鏡音リンVer.2.01", "White.pmx")
TETO = os.path.join(MODEL_DIR, "Tda式重音テトAP", "Tda式重音テトAP.pmx")

ROTATE, TRANSLATE, VISIBLE, ENABLED, IK = 0x0002, 0x0004, 0x0008, 0x0010, 0x0020
APPEND_ROTATE, APPEND_TRANSLATE, FIXED_AXIS, LOCAL_AXIS, PHYSICS_AFTER, EXTERNAL = 0x0100, 0x0200, 0x0400, 0x0800, 0x1000, 0x2000
TAIL_IS_BONE = 0x0001
NORMAL = ROTATE | VISIBLE | ENABLED


class Writer:
    """builds PMX 2.0 / 2.1 files from a few parameters; what is not given is zero"""

    def __init__(self, version=2.0, encoding=0, extra_uv=0, vertex=1, texture=1, material=1, bone=1, morph=1, rigid=1):
        self.version, self.encoding, self.extra_uv = version, encoding, extra_uv
        self.sizes = {"vertex": vertex, "texture": texture, "material": material, "bone": bone, "morph": morph, "rigid": rigid}
        self.codec = "utf-16-le" if encoding == 0 else "utf-8"

    def text(self, s):
        raw = s.encode(self.codec)
        return struct.pack("<i", len(raw)) + raw

    def index(self, value, kind):
        size = self.sizes[kind]
        if kind == "vertex":
            fmt = {1: "<B", 2: "<H", 4: "<i"}[size]
        else:
            fmt = {1: "<b", 2: "<h", 4: "<i"}[size]
        return struct.pack(fmt, value)

    def vertex(self, kind="BDEF1", bones=(0,), weights=()):
        out = [struct.pack("<8f", 0, 0, 0, 0, 1, 0, 0, 0)] + [struct.pack("<4f", 0, 0, 0, 0)] * self.extra_uv
        out.append(bytes([{"BDEF1": 0, "BDEF2": 1, "BDEF4": 2, "SDEF": 3, "QDEF": 4}[kind]]))
        out += [self.index(b, "bone") for b in bones]
        out += [struct.pack("<f", w) for w in weights]
        if kind == "SDEF":
            out.append(struct.pack("<9f", *([0.0] * 9)))
        out.append(struct.pack("<f", 1.0))          # edge scale
        return b"".join(out)

    def material(self, name="mat", name_en="", texture=-1, sphere=-1, shared_toon=None, toon=-1, memo="", faces=3):
        out = [self.text(name), self.text(name_en), struct.pack("<4f3ff3f", *([0.5] * 11)), b"\x00",
               struct.pack("<4ff", 0, 0, 0, 1, 1), self.index(texture, "texture"), self.index(sphere, "texture"), b"\x00"]
        if shared_toon is None:
            out += [b"\x00", self.index(toon, "texture")]
        else:
            out += [b"\x01", bytes([shared_toon])]
        out += [self.text(memo), struct.pack("<i", faces)]
        return b"".join(out)

    def bone(self, name, name_en="", parent=-1, layer=0, flags=NORMAL, tail=(0.0, 1.0, 0.0), append=(0, 1.0),
             axis=(0.0, 1.0, 0.0), local_axes=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), external_key=0, ik=None,
             position=(0.0, 0.0, 0.0)):
        out = [self.text(name), self.text(name_en), struct.pack("<3f", *position), self.index(parent, "bone"),
               struct.pack("<iH", layer, flags)]
        out.append(self.index(tail, "bone") if flags & TAIL_IS_BONE else struct.pack("<3f", *tail))
        if flags & (APPEND_ROTATE | APPEND_TRANSLATE):
            out.append(self.index(append[0], "bone") + struct.pack("<f", append[1]))
        if flags & FIXED_AXIS:
            out.append(struct.pack("<3f", *axis))
        if flags & LOCAL_AXIS:
            out.append(struct.pack("<6f", *(tuple(local_axes[0]) + tuple(local_axes[1]))))
        if flags & EXTERNAL:
            out.append(struct.pack("<i", external_key))
        if flags & IK:
            ik = ik or {"target": 0, "loops": 1, "angle": 1.0, "links": []}
            out.append(self.index(ik["target"], "bone") + struct.pack("<ifi", ik["loops"], ik["angle"], len(ik["links"])))
            for link, limits in ik["links"]:
                out.append(self.index(link, "bone"))
                if limits is None:
                    out.append(b"\x00")
                else:
                    out.append(b"\x01" + struct.pack("<6f", *(tuple(limits[0]) + tuple(limits[1]))))
        return b"".join(out)

    def morph(self, name, name_en="", panel=4, kind=1, offsets=0):
        size = {0: self.sizes["morph"] + 4, 1: self.sizes["vertex"] + 12, 2: self.sizes["bone"] + 28,
                3: self.sizes["vertex"] + 16, 4: self.sizes["vertex"] + 16, 5: self.sizes["vertex"] + 16,
                6: self.sizes["vertex"] + 16, 7: self.sizes["vertex"] + 16, 8: self.sizes["material"] + 113,
                9: self.sizes["morph"] + 4, 10: self.sizes["rigid"] + 25}[kind]
        return self.text(name) + self.text(name_en) + bytes([panel, kind]) + struct.pack("<i", offsets) + b"\x00" * (size * offsets)

    def frame(self, name, name_en="", special=False, items=()):
        out = [self.text(name), self.text(name_en), bytes([1 if special else 0]), struct.pack("<i", len(items))]
        for kind, index in items:
            out.append(b"\x01" + self.index(index, "morph") if kind == "morph" else b"\x00" + self.index(index, "bone"))
        return b"".join(out)

    def rigid(self, name="rb", name_en="", bone=-1):
        return self.text(name) + self.text(name_en) + self.index(bone, "bone") + b"\x00" * 61

    def joint(self, name="j", name_en="", a=-1, b=-1, kind=0):
        return self.text(name) + self.text(name_en) + bytes([kind]) + self.index(a, "rigid") + self.index(b, "rigid") + b"\x00" * 96

    def softbody(self, name="sb", name_en="", material=-1, anchors=1, pins=2):
        out = [self.text(name), self.text(name_en), b"\x00", self.index(material, "material"), b"\x00" * 124,
               struct.pack("<i", anchors)]
        out += [self.index(-1, "rigid") + self.index(0, "vertex") + b"\x00"] * anchors
        out.append(struct.pack("<i", pins))
        out += [self.index(0, "vertex")] * pins
        return b"".join(out)

    def build(self, name="モデル", name_en="Model", comment="コメント", comment_en="comment", vertices=(), faces=(), textures=(),
              materials=(), bones=(), morphs=(), frames=(), rigids=(), joints=(), softbodies=None):
        s = self.sizes
        out = [b"PMX ", struct.pack("<f", self.version), bytes([8, self.encoding, self.extra_uv, s["vertex"], s["texture"],
                                                                 s["material"], s["bone"], s["morph"], s["rigid"]]),
               self.text(name), self.text(name_en), self.text(comment), self.text(comment_en)]
        for items in (vertices, faces, textures, materials, bones, morphs, frames, rigids, joints):
            out.append(struct.pack("<i", len(items)))
            out.extend(items)
        if softbodies is not None:
            out.append(struct.pack("<i", len(softbodies)))
            out.extend(softbodies)
        return b"".join(out)


def minimal(w=None, **kw):
    w = w or Writer()
    return w.build(**kw)


class HeaderTest(unittest.TestCase):
    def test_names_and_comments_in_utf16(self):
        m = pmx.loads(minimal(name="初音ミク", name_en="Miku", comment="説明\r\n2行目", comment_en="en"))
        self.assertEqual((m.format, m.version), ("pmx", 2.0))
        self.assertEqual((m.name, m.name_en, m.comment, m.comment_en), ("初音ミク", "Miku", "説明\r\n2行目", "en"))

    def test_names_in_utf8(self):
        w = Writer(encoding=1)
        m = pmx.loads(w.build(name="鏡音リン", name_en="Rin", bones=[w.bone("センター", "center")]))
        self.assertEqual((m.name, m.name_en), ("鏡音リン", "Rin"))
        self.assertEqual((m.bones[0].name, m.bones[0].name_en), ("センター", "center"))

    def test_counts_of_an_empty_model_are_zero(self):
        m = pmx.loads(minimal())
        self.assertEqual(m.counts, {"vertices": 0, "faces": 0, "textures": 0, "materials": 0, "bones": 0, "morphs": 0,
                                    "display_frames": 0, "rigid_bodies": 0, "joints": 0, "soft_bodies": 0})
        self.assertEqual((m.bones, m.morphs, m.display_frames), ([], [], []))

    def test_version_2_1_with_soft_bodies_is_read_to_the_end(self):
        w = Writer(version=2.1)
        m = pmx.loads(w.build(softbodies=[w.softbody(anchors=2, pins=3), w.softbody()], bones=[w.bone("a")]))
        self.assertEqual(m.version, 2.1)
        self.assertEqual(m.counts["bones"], 1)
        self.assertEqual(m.counts["soft_bodies"], 2)             # review 3 (1.3): walked and counted

    def test_version_2_1_without_the_soft_body_section_is_accepted(self):
        m = pmx.loads(Writer(version=2.1).build())
        self.assertEqual(m.version, 2.1)

    def test_bad_bytes_in_a_name_are_replaced_not_fatal(self):
        w = Writer(encoding=1)
        data = w.build(name="abc")
        broken = data.replace(struct.pack("<i", 3) + b"abc", struct.pack("<i", 3) + b"a\xffc")
        self.assertEqual(pmx.loads(broken).name, "a\ufffdc")


class GeometryTest(unittest.TestCase):
    def test_every_weight_type_is_skipped_so_the_bones_are_found(self):
        for extra_uv in (0, 1, 4):
            for bone_size in (1, 2, 4):
                w = Writer(version=2.1, extra_uv=extra_uv, bone=bone_size)
                vertices = [w.vertex("BDEF1", (0,)), w.vertex("BDEF2", (0, 1), (0.5,)), w.vertex("BDEF4", (0, 1, 2, 3), (0.25,) * 4),
                            w.vertex("SDEF", (0, 1), (0.5,)), w.vertex("QDEF", (0, 1, 2, 3), (0.25,) * 4)]
                m = pmx.loads(w.build(vertices=vertices, faces=[w.index(i, "vertex") for i in (0, 1, 2, 2, 1, 0)],
                                      bones=[w.bone("センター"), w.bone("上半身", parent=0)]))
                self.assertEqual(m.counts["vertices"], 5, (extra_uv, bone_size))
                self.assertEqual(m.counts["faces"], 2)
                self.assertEqual([b.name for b in m.bones], ["センター", "上半身"])
                self.assertEqual([b.parent for b in m.bones], [None, 0])

    def test_vertex_indices_of_size_1_and_2_are_unsigned(self):
        # a face index of 200 (size 1) or 40000 (size 2) must not upset the walk to the bones
        for size, big in ((1, 200), (2, 40000)):
            w = Writer(vertex=size)
            m = pmx.loads(w.build(vertices=[w.vertex()] * 3, faces=[w.index(big, "vertex")] * 3, bones=[w.bone("a")]))
            self.assertEqual((m.counts["faces"], m.counts["bones"]), (1, 1))

    def test_unknown_weight_type_is_an_error_with_the_offset(self):
        w = Writer()
        data = w.build(vertices=[w.vertex()])
        at = len(w.build()) - 9 * 4 + 4 + 32         # the weight type byte of vertex 0: after the count and 8 floats
        self.assertEqual(data[at], 0)
        broken = data[:at] + b"\x07" + data[at + 1:]
        with self.assertRaises(pmx.PmxFormatError) as ctx:
            pmx.loads(broken)
        self.assertIn("weight type 7", str(ctx.exception))
        self.assertIn("offset %d" % at, str(ctx.exception))

    def test_materials_with_every_toon_and_texture_layout_are_skipped(self):
        for sizes in ((1, 1, 1), (2, 2, 2), (4, 4, 4)):
            w = Writer(texture=sizes[0], material=sizes[1], rigid=sizes[2])
            materials = [w.material("a", texture=0, sphere=1, toon=0, memo="メモ"), w.material("b", shared_toon=3),
                         w.material("c", texture=-1, sphere=-1, toon=-1)]
            m = pmx.loads(w.build(textures=[w.text("body.png"), w.text("face.png")], materials=materials, bones=[w.bone("x")],
                                  rigids=[w.rigid(bone=0)], joints=[w.joint(a=0, b=0)]))
            self.assertEqual((m.counts["textures"], m.counts["materials"], m.counts["rigid_bodies"], m.counts["joints"]),
                             (2, 3, 1, 1), sizes)
            self.assertEqual(m.bones[0].name, "x")

    def test_face_index_count_that_is_not_a_multiple_of_three_is_an_error(self):
        w = Writer()
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(w.build(vertices=[w.vertex()], faces=[w.index(0, "vertex")] * 4))


class BoneTest(unittest.TestCase):
    def test_flags_are_named(self):
        w = Writer()
        bones = [w.bone("全ての親", flags=ROTATE | TRANSLATE | VISIBLE | ENABLED),
                 w.bone("先", flags=TAIL_IS_BONE | ROTATE, tail=0),
                 w.bone("物理", flags=ROTATE | PHYSICS_AFTER | LOCAL_AXIS),
                 w.bone("外", flags=ROTATE | EXTERNAL, external_key=3)]
        m = pmx.loads(w.build(bones=bones))
        names = ("rotate", "translate", "visible", "enabled", "ik", "append_rotate", "append_translate", "fixed_axis",
                 "local_axis", "physics_after", "external_parent")
        self.assertEqual(sorted(m.bones[0].flags), sorted(names))
        self.assertEqual({k for k, v in m.bones[0].flags.items() if v}, {"rotate", "translate", "visible", "enabled"})
        self.assertEqual({k for k, v in m.bones[1].flags.items() if v}, {"rotate"})
        self.assertEqual({k for k, v in m.bones[2].flags.items() if v}, {"rotate", "physics_after", "local_axis"})
        self.assertEqual({k for k, v in m.bones[3].flags.items() if v}, {"rotate", "external_parent"})
        self.assertEqual([b.index for b in m.bones], [0, 1, 2, 3])
        self.assertEqual([b.layer for b in m.bones], [0, 0, 0, 0])

    def test_parent_layer_append_and_ik(self):
        for bone_size in (1, 2, 4):
            w = Writer(bone=bone_size)
            ik = {"target": 2, "loops": 40, "angle": 2.0, "links": [(1, None), (0, ((-3.14, 0, 0), (0, 0, 0)))]}
            bones = [w.bone("足", parent=-1), w.bone("ひざ", parent=0), w.bone("足首", parent=1),
                     w.bone("足ＩＫ", flags=NORMAL | TRANSLATE | IK, layer=1, ik=ik),
                     w.bone("目", flags=NORMAL | APPEND_ROTATE, layer=2, append=(0, 0.5)),
                     w.bone("移", flags=NORMAL | APPEND_TRANSLATE, append=(3, -1.0)),
                     w.bone("捩", flags=NORMAL | FIXED_AXIS, axis=(1, 0, 0))]
            m = pmx.loads(w.build(bones=bones))
            self.assertEqual([b.parent for b in m.bones], [None, 0, 1, None, None, None, None])
            self.assertEqual([b.layer for b in m.bones], [0, 0, 0, 1, 2, 0, 0])
            leg_ik = m.bones[3]
            self.assertTrue(leg_ik.flags["ik"])
            self.assertEqual(leg_ik.ik, {"target": 2, "loops": 40, "angle": 2.0, "links": [1, 0]})
            self.assertIsNone(leg_ik.append)
            self.assertEqual(m.bones[4].append, {"parent": 0, "ratio": 0.5})
            self.assertTrue(m.bones[4].flags["append_rotate"])
            self.assertFalse(m.bones[4].flags["append_translate"])
            self.assertEqual(m.bones[5].append, {"parent": 3, "ratio": -1.0})
            self.assertTrue(m.bones[5].flags["append_translate"])
            self.assertIsNone(m.bones[0].ik)
            self.assertTrue(m.bones[6].flags["fixed_axis"])
            self.assertEqual(m.counts["bones"], 7)

    def test_a_missing_append_parent_and_ik_target_become_none(self):
        # review 3 (1.2): -1 means "none" for these links too, as the module docstring promises
        w = Writer(bone=2)
        ik = {"target": -1, "loops": 1, "angle": 1.0, "links": [(-1, None), (0, None)]}
        m = pmx.loads(w.build(bones=[w.bone("付与", flags=NORMAL | APPEND_ROTATE, append=(-1, 0.5)),
                                     w.bone("ＩＫ", flags=NORMAL | IK, ik=ik)]))
        self.assertEqual(m.bones[0].append, {"parent": None, "ratio": 0.5})
        self.assertEqual(m.bones[1].ik, {"target": None, "loops": 1, "angle": 1.0, "links": [None, 0]})

    def test_bones_whose_tail_is_a_bone_index_pass_the_count_check(self):
        # review 3 (1.1): the smallest bone is 26 + 2 x index size bytes (tail as an index, nothing optional)
        w = Writer(bone=1)
        bones = [w.bone("", flags=NORMAL | TAIL_IS_BONE, tail=0) for _ in range(12)]
        m = pmx.loads(w.build(bones=bones))
        self.assertEqual(m.counts["bones"], 12)

    def test_a_bone_with_every_optional_block_is_followed_correctly(self):
        w = Writer(bone=2)
        everything = TAIL_IS_BONE | NORMAL | TRANSLATE | IK | APPEND_ROTATE | FIXED_AXIS | LOCAL_AXIS | PHYSICS_AFTER | EXTERNAL
        ik = {"target": 1, "loops": 3, "angle": 0.5, "links": [(1, ((0, 0, 0), (1, 1, 1)))]}
        m = pmx.loads(w.build(bones=[w.bone("全部", flags=everything, tail=1, append=(1, 0.25), external_key=7, ik=ik),
                                     w.bone("次", parent=0)]))
        self.assertEqual([b.name for b in m.bones], ["全部", "次"])
        self.assertEqual(m.bones[0].ik["links"], [1])
        self.assertEqual(m.bones[0].append, {"parent": 1, "ratio": 0.25})
        self.assertEqual(m.bones[1].parent, 0)

    def test_rest_position_tail_fixed_axis_and_local_axes_are_kept(self):
        # the values are exact in float32, so they come back as written
        for bone_size in (1, 2, 4):
            w = Writer(bone=bone_size)
            everything = TAIL_IS_BONE | NORMAL | TRANSLATE | IK | APPEND_ROTATE | FIXED_AXIS | LOCAL_AXIS | EXTERNAL
            ik = {"target": 1, "loops": 3, "angle": 0.5, "links": [(1, ((0, 0, 0), (1, 1, 1)))]}
            bones = [w.bone("頭", position=(0.5, 15.25, -0.75), tail=(0.0, 1.5, -0.25)),
                     w.bone("両目", parent=0, position=(0.0, 16.5, -1.0), flags=NORMAL | TAIL_IS_BONE, tail=2),
                     w.bone("両目先", parent=1, position=(0.0, 16.5, -2.0), flags=NORMAL | TAIL_IS_BONE, tail=-1),
                     w.bone("捩", flags=NORMAL | FIXED_AXIS, axis=(0.75, -0.5, 0.25), position=(-4.0, 12.0, 0.0)),
                     w.bone("軸", flags=NORMAL | LOCAL_AXIS, local_axes=((0.0, 1.0, 0.0), (0.0, 0.0, -1.0))),
                     w.bone("全部", flags=everything, tail=0, axis=(1.0, 0.0, 0.0), position=(1.0, 2.0, 3.0),
                            local_axes=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), append=(0, 0.5), ik=ik),
                     w.bone("次", parent=5, position=(-1.0, -2.0, -3.0))]
            m = pmx.loads(w.build(bones=bones))
            self.assertEqual([b.position for b in m.bones],
                             [(0.5, 15.25, -0.75), (0.0, 16.5, -1.0), (0.0, 16.5, -2.0), (-4.0, 12.0, 0.0), (0.0, 0.0, 0.0),
                              (1.0, 2.0, 3.0), (-1.0, -2.0, -3.0)], bone_size)
            self.assertEqual(m.bones[0].tail, {"offset": (0.0, 1.5, -0.25)})
            self.assertEqual(m.bones[1].tail, {"bone": 2})
            self.assertEqual(m.bones[2].tail, {"bone": None})                       # -1: a tail that points nowhere
            self.assertEqual(m.bones[3].tail, {"offset": (0.0, 1.0, 0.0)})          # the writer's default tail
            self.assertEqual(m.bones[3].fixed_axis, (0.75, -0.5, 0.25))
            self.assertEqual(m.bones[4].local_axes, {"x": (0.0, 1.0, 0.0), "z": (0.0, 0.0, -1.0)})
            self.assertEqual((m.bones[5].tail, m.bones[5].fixed_axis), ({"bone": 0}, (1.0, 0.0, 0.0)))
            self.assertEqual(m.bones[5].local_axes, {"x": (1.0, 0.0, 0.0), "z": (0.0, 0.0, 1.0)})
            self.assertEqual(m.bones[5].append, {"parent": 0, "ratio": 0.5})
            self.assertEqual(m.bones[5].ik["links"], [1])
            self.assertEqual(m.bones[6].parent, 5)                                  # everything after was read in place
            for b in (m.bones[0], m.bones[1], m.bones[2], m.bones[4], m.bones[6]):
                self.assertIsNone(b.fixed_axis, b.name)
            for b in (m.bones[0], m.bones[1], m.bones[2], m.bones[3], m.bones[6]):
                self.assertIsNone(b.local_axes, b.name)

    def test_the_new_fields_are_plain_json(self):
        import json
        w = Writer()
        m = pmx.loads(w.build(bones=[w.bone("a", position=(1.0, 2.0, 3.0), flags=NORMAL | FIXED_AXIS | LOCAL_AXIS),
                                     w.bone("b", flags=NORMAL | TAIL_IS_BONE, tail=0)]))
        bones = json.loads(json.dumps(m.to_json()))["bones"]
        self.assertEqual(bones[0]["position"], [1.0, 2.0, 3.0])
        self.assertEqual(bones[0]["tail"], {"offset": [0.0, 1.0, 0.0]})
        self.assertEqual(bones[0]["fixed_axis"], [0.0, 1.0, 0.0])
        self.assertEqual(bones[0]["local_axes"], {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]})
        self.assertEqual(bones[1]["tail"], {"bone": 0})
        self.assertEqual((bones[1]["fixed_axis"], bones[1]["local_axes"]), (None, None))
        # the flags keep their names: fixed_axis there is still the bit
        self.assertIs(bones[0]["flags"]["fixed_axis"], True)


class MorphAndFrameTest(unittest.TestCase):
    def test_panels_and_kinds(self):
        for sizes in ((1, 1, 1, 1, 1), (2, 2, 2, 2, 2), (4, 4, 4, 4, 4)):
            w = Writer(version=2.1, vertex=sizes[0], material=sizes[1], bone=sizes[2], morph=sizes[3], rigid=sizes[4])
            morphs = [w.morph("まばたき", "blink", panel=2, kind=1, offsets=5), w.morph("真面目", panel=1, kind=2, offsets=2),
                      w.morph("あ", panel=3, kind=0, offsets=3), w.morph("照れ", panel=4, kind=8, offsets=1),
                      w.morph("uv", panel=4, kind=3, offsets=4), w.morph("uv1", panel=4, kind=4, offsets=1),
                      w.morph("uv4", panel=4, kind=7, offsets=1), w.morph("flip", panel=4, kind=9, offsets=2),
                      w.morph("impulse", panel=4, kind=10, offsets=2), w.morph("内部", panel=0, kind=1, offsets=0)]
            m = pmx.loads(w.build(morphs=morphs, frames=[w.frame("表情", "Exp", special=True, items=[("morph", 0)])]))
            self.assertEqual([x.panel for x in m.morphs],
                             ["eye", "eyebrow", "mouth", "other", "other", "other", "other", "other", "other", "system"])
            self.assertEqual([x.kind for x in m.morphs],
                             ["vertex", "bone", "group", "material", "uv", "uv1", "uv4", "flip", "impulse", "vertex"])
            self.assertEqual([x.offsets for x in m.morphs], [5, 2, 3, 1, 4, 1, 1, 2, 2, 0])
            self.assertEqual([x.index for x in m.morphs], list(range(10)))
            self.assertEqual((m.morphs[0].name, m.morphs[0].name_en), ("まばたき", "blink"))
            self.assertEqual(m.counts["morphs"], 10)

    def test_unknown_morph_kind_is_an_error(self):
        w = Writer()
        data = w.build(morphs=[w.morph("x", kind=1, offsets=0)])
        broken = data.replace(bytes([4, 1]) + struct.pack("<i", 0), bytes([4, 11]) + struct.pack("<i", 0))
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(broken)

    def test_display_frames_hold_bones_and_morphs(self):
        for bone_size, morph_size in ((1, 1), (2, 1), (1, 2), (4, 4)):
            w = Writer(bone=bone_size, morph=morph_size)
            frames = [w.frame("Root", "Root", special=True, items=[("bone", 0)]),
                      w.frame("表情", "Exp", special=True, items=[("morph", 1), ("morph", 0)]),
                      w.frame("体", items=[("bone", 1), ("bone", 2)]), w.frame("空")]
            m = pmx.loads(w.build(bones=[w.bone(n) for n in "abc"], morphs=[w.morph("x"), w.morph("y")], frames=frames))
            self.assertEqual([(f.name, f.name_en, f.special) for f in m.display_frames],
                             [("Root", "Root", True), ("表情", "Exp", True), ("体", "", False), ("空", "", False)])
            self.assertEqual(m.display_frames[1].items, [{"kind": "morph", "index": 1}, {"kind": "morph", "index": 0}])
            self.assertEqual(m.display_frames[2].items, [{"kind": "bone", "index": 1}, {"kind": "bone", "index": 2}])
            self.assertEqual(m.display_frames[3].items, [])
            self.assertEqual(m.counts["display_frames"], 4)

    def test_to_json_is_plain_data_and_brief_drops_the_lists(self):
        w = Writer()
        m = pmx.loads(w.build(bones=[w.bone("a")], morphs=[w.morph("x")], frames=[w.frame("f")]))
        full = m.to_json()
        self.assertEqual(full["bones"][0]["name"], "a")
        self.assertEqual(full["morphs"][0]["kind"], "vertex")
        self.assertEqual(full["display_frames"][0]["name"], "f")
        brief = m.to_json(brief=True)
        self.assertNotIn("bones", brief)
        self.assertNotIn("morphs", brief)
        self.assertNotIn("display_frames", brief)
        self.assertEqual(brief["counts"]["bones"], 1)
        import json
        json.dumps(full)


class ErrorTest(unittest.TestCase):
    def test_empty_file(self):
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(b"")

    def test_wrong_magic(self):
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(b"Pmd" + b"\x00" * 300)

    def test_unsupported_version(self):
        data = minimal()
        with self.assertRaises(pmx.PmxFormatError) as ctx:
            pmx.loads(data[:4] + struct.pack("<f", 3.0) + data[8:])
        self.assertIn("3.0", str(ctx.exception))

    def test_truncated_in_the_middle_of_a_bone_names_the_offset(self):
        w = Writer()
        data = w.build(bones=[w.bone("センター"), w.bone("上半身", parent=0)])
        cut = len(data) - 10
        with self.assertRaises(pmx.PmxFormatError) as ctx:
            pmx.loads(data[:cut])
        self.assertIn("offset", str(ctx.exception))

    def test_truncated_header(self):
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(b"PMX " + struct.pack("<f", 2.0) + bytes([8, 0, 0, 1]))

    def test_huge_count_stops_at_once_with_the_offset(self):
        w = Writer()
        data = w.build(bones=[w.bone("a")])
        at = len(w.build()) - 9 * 4                  # the vertex count: an empty build ends with nine zero counts
        self.assertEqual(struct.unpack_from("<i", data, at)[0], 0)
        for n in (0x7FFFFFFF, -1):
            broken = data[:at] + struct.pack("<i", n) + data[at + 4:]
            with self.assertRaises(pmx.PmxFormatError) as ctx:
                pmx.loads(broken)
            self.assertIn("offset %d" % at, str(ctx.exception))
        # the same for a text length (the English comment "comment" is 14 bytes of UTF-16 right before the counts)
        broken = data[:at - 18] + struct.pack("<i", 0x7FFFFFF0) + data[at - 14:]
        with self.assertRaises(pmx.PmxFormatError) as ctx:
            pmx.loads(broken)
        self.assertIn("offset %d" % (at - 18), str(ctx.exception))

    def test_trailing_bytes_mean_the_layout_was_misread(self):
        with self.assertRaises(pmx.PmxFormatError) as ctx:
            pmx.loads(minimal() + b"\x00\x00\x00\x00")
        self.assertIn("4 bytes are left", str(ctx.exception))

    def test_bad_global_values_are_rejected(self):
        data = minimal()
        for at, value in ((9, 2), (10, 5), (11, 3)):      # encoding, extra uv count, vertex index size
            with self.assertRaises(pmx.PmxFormatError):
                pmx.loads(data[:at] + bytes([value]) + data[at + 1:])


def root_of(bones, index):
    seen = set()
    while bones[index].parent is not None and index not in seen:
        seen.add(index)
        index = bones[index].parent
    return index


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pmx.load(RIN)

    def test_names_and_counts(self):
        m = self.model
        self.assertEqual(m.name, "Sour_Rin_White")
        self.assertEqual(m.format, "pmx")
        self.assertEqual(m.version, 2.0)
        self.assertEqual(m.counts["bones"], len(m.bones))
        self.assertEqual(m.counts["morphs"], len(m.morphs))
        self.assertEqual(m.counts["display_frames"], len(m.display_frames))
        # 373 bones: 287 of them sit in display frames (all the visible ones), 86 are helper bones
        # (tips, 補助, the innermost skirt row) that are hidden; 133 morphs; 14 frames
        self.assertEqual((m.counts["bones"], m.counts["morphs"], m.counts["display_frames"]), (373, 133, 14))
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"], m.counts["materials"]), (186, 273, 26))
        framed = {item["index"] for f in m.display_frames for item in f.items if item["kind"] == "bone"}
        self.assertEqual(len(framed), 287)
        self.assertEqual({b.index for b in m.bones if b.flags["visible"]}, framed)

    def test_center_bone_and_its_root(self):
        bones = {b.name: b for b in self.model.bones}
        self.assertIn("センター", bones)
        # in this model センター hangs under 全ての親, which is the root
        self.assertEqual(bones["センター"].parent, bones["全ての親"].index)
        self.assertIsNone(self.model.bones[root_of(self.model.bones, bones["センター"].index)].parent)
        self.assertEqual(self.model.bones[root_of(self.model.bones, bones["センター"].index)].name, "全ての親")

    def test_blink_is_an_eye_morph_and_leg_ik_is_read(self):
        morphs = {x.name: x for x in self.model.morphs}
        self.assertEqual(morphs["まばたき"].panel, "eye")
        self.assertEqual(morphs["まばたき"].kind, "vertex")
        self.assertEqual(morphs["真面目"].panel, "eyebrow")
        self.assertEqual(morphs["あ"].panel, "mouth")
        self.assertEqual(morphs["あ"].kind, "group")
        bones = {b.name: b for b in self.model.bones}
        ik = bones["左足ＩＫ"].ik
        self.assertEqual(ik["loops"], 40)
        self.assertAlmostEqual(ik["angle"], 2.0, places=5)          # radians; the same bone holds 0.5 in the PMD models
        self.assertEqual([self.model.bones[i].name for i in ik["links"]], ["左ひざ", "左足"])
        self.assertEqual(self.model.bones[ik["target"]].name, "左足首")
        self.assertEqual(bones["左目"].append, {"parent": bones["両目"].index, "ratio": 1.0})

    def test_rest_positions_of_the_head_and_the_eyes(self):
        bones = {b.name: b for b in self.model.bones}

        def at(name):
            return tuple(round(v, 4) for v in bones[name].position)
        self.assertEqual(at("頭"), (0.0, 16.2431, 0.0))
        # 両目 is a handle above the head (its top, 頭先, is at 18.77); the eyes themselves sit lower, the left
        # one on +X: the model's left is +X, as in every MMD model
        self.assertEqual(at("両目"), (0.0, 19.3736, -0.2599))
        self.assertEqual(at("左目"), (0.4101, 17.2143, -0.562))
        self.assertEqual(at("右目"), (-0.4101, 17.2143, -0.562))
        self.assertEqual(bones["両目"].tail, {"bone": bones["両目先"].index})
        self.assertEqual(at("両目先"), (0.0, 19.3736, -0.8273))             # straight ahead of 両目: -Z
        self.assertAlmostEqual(bones["頭"].tail["offset"][1], 1.96, places=5)
        self.assertIsNone(bones["頭"].fixed_axis)

    def test_the_whole_file_is_read(self):
        with open(RIN, "rb") as f:
            data = f.read()
        with self.assertRaises(pmx.PmxFormatError):
            pmx.loads(data + b"\x00")


@unittest.skipUnless(os.path.isfile(TETO), "the Tda Teto model is not here")
class TdaTetoTest(unittest.TestCase):
    def test_counts_and_center(self):
        m = pmx.load(TETO)
        self.assertEqual(m.name, "Tda式重音テトAP")
        self.assertEqual((m.counts["bones"], m.counts["morphs"], m.counts["display_frames"]), (150, 56, 11))
        self.assertEqual(m.counts["bones"], len(m.bones))
        bones = {b.name: b for b in m.bones}
        self.assertEqual(m.bones[root_of(m.bones, bones["センター"].index)].name, "全ての親")
        self.assertEqual({x.name: x.panel for x in m.morphs}["まばたき"], "eye")
        self.assertEqual(m.counts["faces"] * 3, 150192)


if __name__ == "__main__":
    unittest.main()
