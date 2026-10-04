"""formats.pmd: small PMD files built here byte by byte, and the models shipped with MMD when they are present."""
import os
import struct
import unittest

from mmd_cli.formats import pmd, pmm

MODEL_DIR = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model"
MIKU = os.path.join(MODEL_DIR, "初音ミク.pmd")
MEIKO = os.path.join(MODEL_DIR, "MEIKO.pmd")
KAITO = os.path.join(MODEL_DIR, "カイト.pmd")
DUMMY = os.path.join(MODEL_DIR, "ダミーボーン.pmd")
PMM_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "scene_v932.pmm")


def fixed(text, size):
    return text.encode("cp932").ljust(size, b"\x00")


def bone(name, parent=-1, tail=-1, kind=0, ik_parent=0):
    return struct.pack("<20shhBH3f", fixed(name, 20), parent, tail, kind, ik_parent, 0.0, 1.0, 0.0)


def ik(bone_index, target, loops, weight, links):
    return struct.pack("<HHBHf", bone_index, target, len(links), loops, weight) + struct.pack("<%dH" % len(links), *links)


def skin(name, kind, vertices=0):
    return struct.pack("<20sIB", fixed(name, 20), vertices, kind) + b"\x00" * (16 * vertices)


def material(texture=""):
    return b"\x00" * 50 + fixed(texture, 20)


def build(name="モデル", comment="コメント", vertices=0, faces=0, materials=(), bones=(), iks=(), skins=(), skin_display=(),
          frames=(), bone_display=(), english=None, toons=False, rigid_bodies=0, joints=0, stop_after_core=False):
    """english: None (no block at all), False (flag 0), or (name_en, comment_en, bone_names, skin_names, frame_names)"""
    out = [b"Pmd", struct.pack("<f", 1.0), fixed(name, 20), fixed(comment, 256)]
    out.append(struct.pack("<I", vertices) + b"\x00" * (38 * vertices))
    out.append(struct.pack("<I", faces) + b"\x00" * (2 * faces))
    out.append(struct.pack("<I", len(materials)) + b"".join(materials))
    out.append(struct.pack("<H", len(bones)) + b"".join(bones))
    out.append(struct.pack("<H", len(iks)) + b"".join(iks))
    out.append(struct.pack("<H", len(skins)) + b"".join(skins))
    out.append(bytes([len(skin_display)]) + struct.pack("<%dH" % len(skin_display), *skin_display))
    out.append(bytes([len(frames)]) + b"".join(fixed(f, 50) for f in frames))
    out.append(struct.pack("<I", len(bone_display)) + b"".join(struct.pack("<HB", b, f) for b, f in bone_display))
    if stop_after_core:
        return b"".join(out)
    if english is None:
        return b"".join(out)
    if english is False:
        out.append(b"\x00")
    else:
        name_en, comment_en, bone_names, skin_names, frame_names = english
        out += [b"\x01", fixed(name_en, 20), fixed(comment_en, 256)]
        out += [fixed(n, 20) for n in bone_names]
        out += [fixed(n, 20) for n in skin_names]
        out += [fixed(n, 50) for n in frame_names]
    if not toons:
        return b"".join(out)
    out += [fixed("toon%02d.bmp" % (i + 1), 100) for i in range(10)]
    out.append(struct.pack("<I", rigid_bodies) + b"\x00" * (83 * rigid_bodies))
    out.append(struct.pack("<I", joints) + b"\x00" * (124 * joints))
    return b"".join(out)


def true_flags(b):
    return {k for k, v in b.flags.items() if v}


class HeaderTest(unittest.TestCase):
    def test_names_counts_and_textures(self):
        data = build(name="初音ミク", comment="説明\r\n2行目", vertices=3, faces=6,
                     materials=[material("eye2.bmp"), material("body.bmp*sphere.sph"), material("eye2.bmp"), material()],
                     english=("Miku Hatsune", "about", [], [], []), toons=True, rigid_bodies=2, joints=1)
        m = pmd.loads(data)
        self.assertEqual((m.format, m.version), ("pmd", 1.0))
        self.assertEqual((m.name, m.name_en, m.comment, m.comment_en), ("初音ミク", "Miku Hatsune", "説明\r\n2行目", "about"))
        self.assertEqual(m.counts, {"vertices": 3, "faces": 2, "textures": 3, "materials": 4, "bones": 0, "morphs": 0,
                                    "display_frames": 1, "rigid_bodies": 2, "joints": 1})

    def test_text_is_cut_at_nul_and_bad_bytes_are_replaced(self):
        # 0x81 is a cp932 lead byte with nothing after it (0xFF would not do: Python's cp932 maps it to U+F8F3)
        data = build(name="abc")
        broken = data.replace(fixed("abc", 20), b"ab\x81\x00zz".ljust(20, b"\x00"))
        self.assertEqual(pmd.loads(broken).name, "ab\ufffd")

    def test_version_other_than_1_0_is_refused(self):
        data = build()
        with self.assertRaises(pmd.PmdFormatError) as ctx:
            pmd.loads(data[:3] + struct.pack("<f", 2.0) + data[7:])
        self.assertIn("2.0", str(ctx.exception))


class BoneTest(unittest.TestCase):
    def test_every_bone_type_becomes_flags(self):
        bones = [bone("センター", -1, 10, kind=1), bone("上半身", 0, 2, kind=0), bone("左足ＩＫ", -1, 11, kind=2),
                 bone("謎", 0, 4, kind=3), bone("左ひざ", 1, 5, kind=4, ik_parent=2), bone("左目", 1, 6, kind=5, ik_parent=1),
                 bone("左つま先", 4, 0, kind=6, ik_parent=2), bone("頭先", 1, 0, kind=7), bone("左腕捩", 1, 9, kind=8),
                 bone("左腕捩1", 1, 8, kind=9, ik_parent=25), bone("センター先", 0, 0, kind=7), bone("左足ＩＫ先", 2, 0, kind=7)]
        m = pmd.loads(build(bones=bones, iks=[ik(2, 6, 40, 0.5, [4, 1])]))
        self.assertEqual(m.counts["bones"], 12)
        self.assertEqual([b.index for b in m.bones], list(range(12)))
        self.assertEqual([b.parent for b in m.bones], [None, 0, None, 0, 1, 1, 4, 1, 1, 1, 0, 2])
        self.assertEqual([b.layer for b in m.bones], [0] * 12)
        names = ("rotate", "translate", "visible", "enabled", "ik", "append_rotate", "append_translate", "fixed_axis",
                 "local_axis", "physics_after", "external_parent")
        self.assertEqual(sorted(m.bones[0].flags), sorted(names))
        shown = {"rotate", "visible", "enabled"}
        self.assertEqual(true_flags(m.bones[0]), shown | {"translate"})               # 1 回転移動
        self.assertEqual(true_flags(m.bones[1]), shown)                               # 0 回転
        self.assertEqual(true_flags(m.bones[2]), shown | {"translate", "ik"})         # 2 IK
        self.assertEqual(true_flags(m.bones[3]), {"rotate"})                          # 3 不明: like hidden
        self.assertEqual(true_flags(m.bones[4]), shown)                               # 4 IK影響下
        self.assertEqual(true_flags(m.bones[5]), shown | {"append_rotate"})           # 5 回転影響下
        self.assertEqual(true_flags(m.bones[6]), {"rotate"})                          # 6 IK接続先
        self.assertEqual(true_flags(m.bones[7]), {"rotate"})                          # 7 非表示
        self.assertEqual(true_flags(m.bones[8]), shown | {"fixed_axis"})              # 8 捻り
        self.assertEqual(true_flags(m.bones[9]), {"rotate", "append_rotate"})         # 9 回転運動
        self.assertEqual(m.bones[5].append, {"parent": 1, "ratio": 1.0})
        self.assertEqual(m.bones[9].append, {"parent": 8, "ratio": 0.25})            # source is the tail field, ratio ik_parent / 100
        self.assertEqual([b.append for b in m.bones if b.index not in (5, 9)], [None] * 10)
        self.assertEqual(m.bones[2].ik, {"target": 6, "loops": 40, "angle": 0.5, "links": [4, 1]})
        self.assertEqual([b.ik for b in m.bones if b.index != 2], [None] * 11)
        self.assertIsNone(m.bones[0].name_en)

    def test_an_ik_record_marks_its_bone_even_when_the_type_says_otherwise(self):
        m = pmd.loads(build(bones=[bone("a", kind=0), bone("b", kind=0)], iks=[ik(1, 0, 3, 1.0, [0])]))
        self.assertTrue(m.bones[1].flags["ik"])
        self.assertEqual(m.bones[1].ik["links"], [0])
        self.assertFalse(m.bones[0].flags["ik"])

    def test_english_names_follow_the_bones(self):
        m = pmd.loads(build(bones=[bone("センター", kind=1), bone("頭", 0)], skins=[skin("base", 0), skin("あ", 3)],
                            frames=["体\n"], english=("Miku", "", ["center", "head"], ["a"], ["Body"])))
        self.assertEqual([b.name_en for b in m.bones], ["center", "head"])
        self.assertEqual(m.morphs[0].name_en, "a")
        self.assertEqual(m.display_frames[1].name_en, "Body")


class MorphAndFrameTest(unittest.TestCase):
    def test_panels_and_file_indices_without_the_base(self):
        skins = [skin("base", 0, 10), skin("真面目", 1, 3), skin("まばたき", 2, 7), skin("あ", 3, 2), skin("照れ", 4, 1)]
        m = pmd.loads(build(skins=skins, skin_display=[3, 2, 1, 4]))
        self.assertEqual([(x.index, x.name, x.panel, x.kind, x.offsets) for x in m.morphs],
                         [(1, "真面目", "eyebrow", "vertex", 3), (2, "まばたき", "eye", "vertex", 7), (3, "あ", "mouth", "vertex", 2),
                          (4, "照れ", "other", "vertex", 1)])
        self.assertEqual(m.counts["morphs"], 4)
        self.assertEqual([x.name_en for x in m.morphs], [None] * 4)
        exp = m.display_frames[0]
        self.assertEqual((exp.name, exp.name_en, exp.special), ("表情", None, True))
        self.assertEqual(exp.items, [{"kind": "morph", "index": i} for i in (3, 2, 1, 4)])

    def test_bone_frames_lose_their_trailing_newline_and_hold_their_bones(self):
        bones = [bone("センター", kind=1), bone("上半身", 0), bone("首", 1), bone("左足ＩＫ", kind=2)]
        m = pmd.loads(build(bones=bones, frames=["ＩＫ\n", "体(上)\n", "空"], bone_display=[(1, 2), (3, 1), (2, 2), (0, 9)]))
        self.assertEqual([(f.name, f.special) for f in m.display_frames], [("表情", True), ("ＩＫ", False), ("体(上)", False), ("空", False)])
        self.assertEqual(m.display_frames[1].items, [{"kind": "bone", "index": 3}])
        self.assertEqual(m.display_frames[2].items, [{"kind": "bone", "index": 1}, {"kind": "bone", "index": 2}])
        self.assertEqual(m.display_frames[3].items, [])
        self.assertEqual(m.counts["display_frames"], 4)

    def test_to_json(self):
        m = pmd.loads(build(bones=[bone("a", kind=1)], skins=[skin("base", 0), skin("x", 2)]))
        d = m.to_json()
        self.assertEqual(d["bones"][0]["flags"]["translate"], True)
        self.assertEqual(d["morphs"][0]["panel"], "eye")
        self.assertNotIn("bones", m.to_json(brief=True))


class TrailingSectionsTest(unittest.TestCase):
    def test_a_file_that_stops_after_the_core_tables_is_read(self):
        m = pmd.loads(build(bones=[bone("a", kind=1)], skins=[skin("base", 0), skin("x", 2)], frames=["f"], stop_after_core=True))
        self.assertEqual(m.counts["bones"], 1)
        self.assertEqual((m.name_en, m.comment_en), (None, None))
        self.assertEqual([b.name_en for b in m.bones], [None])
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"]), (0, 0))

    def test_english_flag_zero_means_no_english_names(self):
        m = pmd.loads(build(bones=[bone("a", kind=1)], english=False, toons=True, rigid_bodies=1))
        self.assertEqual((m.name_en, m.bones[0].name_en), (None, None))
        self.assertEqual(m.counts["rigid_bodies"], 1)

    def test_english_block_without_skins_has_no_skin_names(self):
        # with no skins the English block holds max(0, skins - 1) = 0 skin names, not -1
        m = pmd.loads(build(bones=[bone("a", kind=1)], frames=["f"], english=("Dummy", "", ["bone_a"], [], ["frame"]),
                            toons=True, rigid_bodies=3, joints=2))
        self.assertEqual((m.name_en, m.bones[0].name_en), ("Dummy", "bone_a"))
        self.assertEqual(m.display_frames[1].name_en, "frame")
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"]), (3, 2))

    def test_a_file_that_ends_after_the_toon_names_has_no_rigid_bodies(self):
        data = build(bones=[bone("a", kind=1)], english=("E", "", ["a"], [], []), toons=True)
        data = data[:len(data) - 8]            # drop the two zero counts
        m = pmd.loads(data)
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"]), (0, 0))

    def test_a_file_that_ends_after_the_rigid_bodies_has_no_joints(self):
        data = build(bones=[bone("a", kind=1)], english=False, toons=True, rigid_bodies=1)
        m = pmd.loads(data[:-4])
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"]), (1, 0))


class ErrorTest(unittest.TestCase):
    def test_empty_file(self):
        with self.assertRaises(pmd.PmdFormatError):
            pmd.loads(b"")

    def test_wrong_magic(self):
        with self.assertRaises(pmd.PmdFormatError):
            pmd.loads(b"PMX " + b"\x00" * 300)

    def test_truncated_header(self):
        with self.assertRaises(pmd.PmdFormatError) as ctx:
            pmd.loads(b"Pmd" + struct.pack("<f", 1.0) + fixed("x", 20))
        self.assertIn("offset", str(ctx.exception))

    def test_truncated_in_the_middle_of_a_bone(self):
        data = build(bones=[bone("センター", kind=1), bone("上半身", 0)])
        with self.assertRaises(pmd.PmdFormatError) as ctx:
            pmd.loads(data[:283 + 4 + 4 + 4 + 2 + 39 + 20])
        self.assertIn("offset", str(ctx.exception))

    def test_truncated_english_block_is_an_error_not_a_short_read(self):
        data = build(bones=[bone("a", kind=1)], english=("E", "", ["a"], [], []))
        with self.assertRaises(pmd.PmdFormatError):
            pmd.loads(data[:-5])

    def test_huge_counts_stop_at_once_with_the_offset(self):
        data = build()
        at = 283                                   # the vertex count
        for n in (0xFFFFFFFF, 0x10000000):
            with self.assertRaises(pmd.PmdFormatError) as ctx:
                pmd.loads(data[:at] + struct.pack("<I", n) + data[at + 4:])
            self.assertIn("offset %d" % at, str(ctx.exception))
        skins = build(skins=[skin("base", 0)])
        at = 283 + 4 + 4 + 4 + 2 + 2 + 2 + 20       # the vertex count of skin 0
        with self.assertRaises(pmd.PmdFormatError) as ctx:
            pmd.loads(skins[:at] + struct.pack("<I", 0x7FFFFFFF) + skins[at + 4:])
        self.assertIn("offset %d" % at, str(ctx.exception))

    def test_face_index_count_that_is_not_a_multiple_of_three_is_an_error(self):
        with self.assertRaises(pmd.PmdFormatError):
            pmd.loads(build(faces=4))

    def test_trailing_bytes_after_the_joints_mean_the_layout_was_misread(self):
        with self.assertRaises(pmd.PmdFormatError) as ctx:
            pmd.loads(build(english=False, toons=True) + b"\x00")
        self.assertIn("1 bytes are left", str(ctx.exception))


@unittest.skipUnless(os.path.isfile(MIKU), "the Miku model is not here")
class MikuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pmd.load(MIKU)

    def test_names_and_counts(self):
        m = self.model
        self.assertEqual((m.name, m.name_en), ("初音ミク", "Miku Hatsune"))
        self.assertTrue(m.comment.startswith("PolyMo用モデルデータ：初音ミク"))
        self.assertEqual(m.counts["bones"], len(m.bones))
        self.assertEqual(m.counts["morphs"], len(m.morphs))
        self.assertEqual(m.counts["display_frames"], len(m.display_frames))
        # 122 bones, 7 IK, 16 skins of which one is the base, 7 bone frames + the expression frame, 45 rigid bodies, 27 joints
        self.assertEqual(m.counts, {"vertices": 9036, "faces": 14997, "textures": 1, "materials": 17, "bones": 122, "morphs": 15,
                                    "display_frames": 8, "rigid_bodies": 45, "joints": 27})

    def test_center_bone_has_no_parent(self):
        bones = {b.name: b for b in self.model.bones}
        self.assertEqual(bones["センター"].index, 0)
        self.assertIsNone(bones["センター"].parent)
        self.assertEqual(true_flags(bones["センター"]), {"rotate", "translate", "visible", "enabled"})
        self.assertEqual(bones["上半身"].parent, 0)

    def test_bone_types_as_mmd_shows_them(self):
        bones = {b.name: b for b in self.model.bones}
        self.assertEqual(true_flags(bones["左ひざ"]), {"rotate", "visible", "enabled"})                 # 4 IK影響下
        self.assertEqual(true_flags(bones["左目"]), {"rotate", "visible", "enabled", "append_rotate"})   # 5 回転影響下
        self.assertEqual(bones["左目"].append, {"parent": bones["両目"].index, "ratio": 1.0})
        self.assertEqual(true_flags(bones["左つま先"]), {"rotate"})                                      # 6 IK接続先
        self.assertEqual(true_flags(bones["頭先"]), {"rotate"})                                          # 7 非表示
        ik = bones["左足ＩＫ"].ik
        self.assertEqual((ik["loops"], ik["angle"]), (40, 0.5))
        self.assertEqual([self.model.bones[i].name for i in ik["links"]], ["左ひざ", "左足"])
        self.assertEqual(self.model.bones[ik["target"]].name, "左足首")
        self.assertEqual(sum(1 for b in self.model.bones if b.ik is not None), 7)
        framed = {item["index"] for f in self.model.display_frames for item in f.items if item["kind"] == "bone"}
        # every bone in a display frame is one we call visible; the ones outside are センター (MMD lists it on its own) and the hidden ones
        self.assertTrue(framed <= {b.index for b in self.model.bones if b.flags["visible"]})
        self.assertEqual({b.name for b in self.model.bones if b.flags["visible"]} - {self.model.bones[i].name for i in framed},
                         {"センター"})

    def test_blink_is_an_eye_morph_numbered_as_mmd_numbers_it(self):
        morphs = {x.name: x for x in self.model.morphs}
        self.assertEqual((morphs["まばたき"].panel, morphs["まばたき"].index, morphs["まばたき"].name_en), ("eye", 5, "blink"))
        self.assertEqual((morphs["あ"].panel, morphs["あ"].index), ("mouth", 9))
        self.assertEqual(morphs["真面目"].panel, "eyebrow")
        self.assertNotIn("base", morphs)
        exp = self.model.display_frames[0]
        self.assertEqual((exp.name, exp.special, len(exp.items)), ("表情", True, 15))
        self.assertEqual([f.name for f in self.model.display_frames[1:]], ["ＩＫ", "体(上)", "髪", "腕", "指", "体(下)", "足"])
        self.assertEqual([f.name_en for f in self.model.display_frames[1:]], ["IK", "Body[u]", "Hair", "Arms", "Fingers", "Body[l]", "Legs"])

    @unittest.skipUnless(os.path.isfile(PMM_FIXTURE), "no pmm fixture")
    def test_mmd_numbers_bones_and_morphs_the_same_way(self):
        # the pmm fixture was saved by MMD with this very model loaded
        project = pmm.load(PMM_FIXTURE)
        model = project["models"][0]
        self.assertEqual(model["bones"], [b.name for b in self.model.bones])
        self.assertEqual(model["morphs"][0], "base")
        self.assertEqual(model["morphs"][1:], [x.name for x in self.model.morphs])
        self.assertEqual([x.index for x in self.model.morphs], list(range(1, 16)))

    def test_the_whole_file_is_read(self):
        with open(MIKU, "rb") as f:
            data = f.read()
        with self.assertRaises(pmd.PmdFormatError):
            pmd.loads(data + b"\x00")


@unittest.skipUnless(os.path.isfile(MEIKO), "the MEIKO model is not here")
class MeikoTest(unittest.TestCase):
    def test_counts(self):
        m = pmd.load(MEIKO)
        self.assertEqual((m.name, m.name_en), ("MEIKO", "aniMEIKO"))
        self.assertEqual((m.counts["bones"], m.counts["morphs"], m.counts["display_frames"]), (99, 42, 8))
        self.assertEqual(m.counts["bones"], len(m.bones))
        self.assertIsNone({b.name: b for b in m.bones}["センター"].parent)
        self.assertEqual({x.name: x.panel for x in m.morphs}["まばたき"], "eye")


@unittest.skipUnless(os.path.isfile(KAITO) and os.path.isfile(DUMMY), "the Kaito / dummy bone models are not here")
class ShortFilesTest(unittest.TestCase):
    def test_kaito_ends_after_the_toon_names(self):
        m = pmd.load(KAITO)
        self.assertEqual((m.counts["bones"], m.counts["morphs"]), (106, 24))
        self.assertEqual((m.counts["rigid_bodies"], m.counts["joints"]), (0, 0))
        self.assertIsNotNone(m.name_en)

    def test_dummy_bones_have_no_morphs_but_english_names(self):
        m = pmd.load(DUMMY)
        self.assertEqual((m.name, m.name_en), ("ダミーボーン", "Dummy Bone"))
        self.assertEqual((m.counts["bones"], m.counts["morphs"], m.counts["vertices"]), (30, 0, 0))
        self.assertEqual(m.bones[0].name_en, "bone01")
        self.assertEqual(m.display_frames[0].items, [])
        self.assertEqual(m.display_frames[1].name, "ﾎﾞｰﾝ02～")


if __name__ == "__main__":
    unittest.main()
