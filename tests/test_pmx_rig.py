"""tools/pmx_rig.py: a copy of a PMX model with its rig changed by a recipe, everything else kept byte for byte."""
import json
import math
import os
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli.formats import pmx, pmx_edit
from tests.test_leg_ik import leg_ik, rin_legs_bytes
from tests.test_pmx import NORMAL, TAIL_IS_BONE, TRANSLATE, Writer
from tests.test_pmx_spine import load_tool
from tests.test_rig_skin import vertex_rec

pmx_rig = load_tool("pmx_rig")


class IkLoopsTest(unittest.TestCase):
    def test_leg_ik_loops_change_and_nothing_else(self):
        data = rin_legs_bytes()
        doc = pmx_edit.loads(data)
        rep = pmx_rig.apply(doc, {"leg_ik_loops": 400})
        out = pmx_edit.dumps(doc)
        rig = leg_ik.LegRig.loads(out)
        for side in ("左", "右"):
            self.assertEqual(rig.sides[side].leg_loops, 400)
            self.assertEqual(rig.sides[side].toe_loops, 3)
            self.assertAlmostEqual(rig.sides[side].leg_limit, 2.0, 6)
        self.assertEqual(sorted(c["bone"] for c in rep["ik"]), ["右足ＩＫ", "左足ＩＫ"])
        self.assertEqual(rep["ik"][0]["old"]["loops"], 40)
        # every byte but the two loop counts is the same
        diff = [i for i, (a, b) in enumerate(zip(data, out)) if a != b]
        self.assertEqual(len(out), len(data))
        self.assertLessEqual(len(diff), 4)

    def test_empty_recipe_is_byte_for_byte(self):
        data = rin_legs_bytes()
        doc = pmx_edit.loads(data)
        pmx_rig.apply(doc, {})
        self.assertEqual(pmx_edit.dumps(doc), data)

    def test_unknown_recipe_key_is_refused(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        with self.assertRaises(ValueError):
            pmx_rig.apply(doc, {"leg_ik_loop": 400})

    def test_command_line_writes_the_copy_and_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "m.pmx")
            with open(src, "wb") as f:
                f.write(rin_legs_bytes())
            out, rep = os.path.join(d, "o.pmx"), os.path.join(d, "r.json")
            self.assertEqual(pmx_rig.main([src, out, "--report", rep, "--leg-ik-loops", "200"]), 0)
            self.assertEqual(leg_ik.LegRig.load(out).sides["左"].leg_loops, 200)
            with open(rep, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["recipe"], {"leg_ik_loops": 200})
            self.assertEqual(pmx_rig.main([src, src, "--leg-ik-loops", "200"]), 2)      # never over the model


class KneeTest(unittest.TestCase):
    def test_least_bend_sets_the_knee_limit(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        rep = pmx_rig.apply(doc, {"knee_least_bend": 4.0})
        rig = leg_ik.LegRig.loads(pmx_edit.dumps(doc))
        for side in ("左", "右"):
            self.assertAlmostEqual(math.degrees(rig.sides[side].knee_hi), -4.0, places=5)
            self.assertAlmostEqual(math.degrees(rig.sides[side].knee_lo), -180.0, places=4)
        self.assertEqual(len(rep["ik"]), 2)
        self.assertAlmostEqual(rep["ik"][0]["new"]["knee_deg"][1], -4.0, places=4)

    def test_least_bend_out_of_range_is_refused(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        for bad in (-1.0, 30.0):
            with self.assertRaises(ValueError):
                pmx_rig.apply(doc, {"knee_least_bend": bad})


def brow_model():
    """a face with two brows (bones 右眉1..4 / 左眉1..4 from the inner end out, x 0.3 to 0.85) of 4 vertices each, a
    vertex on 頭, the display frame 表情 with one morph, and that morph (a vertex morph on vertex 0)"""
    w = Writer(bone=2, vertex=2, morph=1)
    T = NORMAL | TRANSLATE
    bones = [w.bone("頭", position=(0, 16.2, 0))]
    for side, sx in (("右", -1.0), ("左", 1.0)):
        base = len(bones)
        for k, x in enumerate((0.32, 0.45, 0.65, 0.85)):
            bones.append(w.bone(side + "眉%d" % (k + 1), parent=0 if k == 0 else base + k - 1, position=(sx * x, 17.67, -1.28), flags=T))
    vs = [vertex_rec(w, (0.0, 16.0, -1.0), "BDEF1", (0,))]
    for side, sx, base in (("右", -1.0, 1), ("左", 1.0, 5)):
        for k, x in enumerate((0.32, 0.45, 0.65, 0.85)):
            vs.append(vertex_rec(w, (sx * x, 17.7, -1.28), "BDEF1", (base + min(k, 2),)))
    morph = w.text("既存") + w.text("") + bytes([4, 1]) + struct.pack("<i", 1) + w.index(0, "vertex") + struct.pack("<3f", 0, 0.1, 0)
    frames = [w.frame("Root", "Root", special=True, items=[("bone", 0)]), w.frame("表情", "Exp", special=True, items=[("morph", 0)])]
    return w.build(bones=bones, vertices=vs, morphs=[morph], frames=frames)


class BrowTest(unittest.TestCase):
    def test_inner_brow_morphs(self):
        data = brow_model()
        doc = pmx_edit.loads(data)
        rep = pmx_rig.apply(doc, {"inner_brow": 0.1})
        out = pmx_edit.dumps(doc)
        model = pmx.loads(out)
        names = [m.name for m in model.morphs]
        self.assertEqual(names, ["既存", "眉頭右", "眉頭左"])
        self.assertEqual([(m.panel, m.kind) for m in model.morphs[1:]], [("eyebrow", "vertex")] * 2)
        exp = [f for f in model.display_frames if f.name == "表情"][0]
        self.assertEqual([it["index"] for it in exp.items], [0, 1, 2])
        offs = {name: pmx_rig.vertex_morph_offsets(doc, i) for i, name in ((1, "眉頭右"), (2, "眉頭左"))}
        # the right brow's vertices (1..4) only, the most at the inner end, nothing at the outer end
        self.assertEqual(sorted(offs["眉頭右"]), [1, 2, 3])
        self.assertGreater(offs["眉頭右"][1][1], offs["眉頭右"][2][1])
        self.assertGreater(offs["眉頭右"][2][1], offs["眉頭右"][3][1])
        self.assertAlmostEqual(math.hypot(*offs["眉頭右"][1]), 0.1 * (1 - (0.32 - 0.32) / (0.85 - 0.32)), places=4)
        self.assertEqual(sorted(offs["眉頭左"]), [5, 6, 7])
        for v in (1, 2, 3):
            a, b = offs["眉頭右"][v], offs["眉頭左"][v + 4]
            self.assertAlmostEqual(a[0], -b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)
        self.assertEqual([m["name"] for m in rep["morphs"]], ["眉頭右", "眉頭左"])
        # the old morph and the vertices are as they were (a morph moves vertices only while it is keyed)
        before = pmx_edit.loads(data)
        after = pmx_edit.loads(out)
        self.assertEqual([v.head for v in after.vertices], [v.head for v in before.vertices])
        self.assertEqual((after.morphs[0].head, after.morphs[0].body), (before.morphs[0].head, before.morphs[0].body))
        self.assertEqual([b.name for b in after.bones], [b.name for b in before.bones])

    def test_a_model_with_the_morph_already_is_refused(self):
        doc = pmx_edit.loads(brow_model())
        pmx_rig.apply(doc, {"inner_brow": 0.1})
        with self.assertRaises(ValueError):
            pmx_rig.apply(doc, {"inner_brow": 0.1})


def wrist_model():
    """an arm along +x: 右ひじ (x 0) -> 右手捩 (x 1, the forearm's twist) -> 右手首 (x 2) -> 右中指０ (x 2.3); rings at the wrist
    of 12 vertices: one half and half on 右手捩 / 右手首, one 0.75 / 0.25, one 0.2 on 右ひじ, 0.6 右手捩 and 0.2 右手首; a
    vertex on 右中指０ alone"""
    from tests.test_rig_skin import ring
    w = Writer(bone=2, vertex=2)
    bones = [w.bone("右ひじ", position=(0, 0, 0)), w.bone("右手捩", parent=0, position=(1, 0, 0)),
             w.bone("右手首", parent=1, position=(2, 0, 0)), w.bone("右中指０", parent=2, position=(2.3, 0, 0)),
             w.bone("左ひじ", position=(0, 0, 0)), w.bone("左手捩", parent=4, position=(-1, 0, 0)),
             w.bone("左手首", parent=5, position=(-2, 0, 0))]
    vs = (ring(w, 2.0, 0.3, (1, 2), (0.5,), "BDEF2") + ring(w, 1.9, 0.3, (1, 2), (0.75,), "BDEF2")
          + ring(w, 1.8, 0.3, (0, 1, 2, 2), (0.2, 0.6, 0.2, 0.0), "BDEF4") + [vertex_rec(w, (2.4, 0.1, 0.0), "BDEF1", (3,))])
    return w.build(bones=bones, vertices=vs, frames=[w.frame("Root", "Root", special=True, items=[("bone", 0)])])


class JointHelperTest(unittest.TestCase):
    def setUp(self):
        from tests.test_pmx_spine import load_tool
        self.rig_skin = load_tool("rig_skin")
        self.data = wrist_model()
        self.doc = pmx_edit.loads(self.data)
        self.rep = pmx_rig.apply(self.doc, {"joint_helpers": ["wrist"]})
        self.out = pmx_edit.dumps(self.doc)

    def test_helper_bone(self):
        model = pmx.loads(self.out)
        names = [b.name for b in model.bones]
        self.assertEqual(names[:7], ["右ひじ", "右手捩", "右手首", "右中指０", "左ひじ", "左手捩", "左手首"])   # no index moved
        h = model.bones[names.index("右手首補助")]
        self.assertEqual(model.bones[h.parent].name, "右手捩")
        self.assertEqual(h.position, model.bones[2].position)
        self.assertEqual(h.append["parent"], 2)
        self.assertAlmostEqual(h.append["ratio"], 0.5)
        self.assertTrue(h.flags["append_rotate"])
        self.assertFalse(h.flags["visible"])

    def test_weights_keep_the_mean_turn_and_the_count(self):
        h = [b.name for b in self.doc.bones].index("右手首補助")

        class V:            # a vertex's weights merged per bone (BDEF4 pads with its first bone at weight 0)
            def __init__(self, vertex):
                self.vertex = vertex

            def pairs(self):
                out = {}
                for b, w in self.vertex.pairs():
                    out[b] = out.get(b, 0.0) + w
                return {b: w for b, w in out.items() if w > 0.0}.items()
        v = [V(x) for x in self.doc.vertices]
        half = dict(v[0].pairs())
        self.assertAlmostEqual(half.get(h, 0.0), 1.0, places=6)                      # 0.5 / 0.5: all on the helper
        three = dict(v[12].pairs())                                                  # 0.75 手捩 / 0.25 手首
        self.assertAlmostEqual(three.get(1, 0.0), 0.5, places=6)
        self.assertAlmostEqual(three.get(h, 0.0), 0.5, places=6)
        self.assertAlmostEqual(three.get(2, 0.0), 0.0, places=6)
        four = dict(v[24].pairs())                                                   # 0.2 ひじ, 0.6 手捩, 0.2 手首
        self.assertAlmostEqual(four.get(2, 0.0), 0.0, places=6)
        self.assertAlmostEqual(four.get(h, 0.0), 0.4, places=6)
        self.assertAlmostEqual(four.get(0, 0.0) + four.get(1, 0.0), 0.6, places=6)
        self.assertAlmostEqual(four.get(0, 0.0) / four.get(1, 1.0), 0.2 / 0.6, places=5)  # the forearm side shared as it was
        self.assertEqual(dict(v[36].pairs()), {3: 1.0})                              # off the joint: untouched
        self.assertEqual(self.rep["helpers"][0]["vertices"], 36)

    def test_a_twisted_wrist_keeps_its_girth(self):
        RS = self.rig_skin
        from tests.test_leg_ik import axis_angle, key, motion
        from mmd_cli import fk
        for data, want in ((self.data, 0.3 * math.cos(math.radians(85))), (self.out, 0.3)):
            m = RS.Model.loads(data)
            pose = RS.solve(m, RS.keys_at(m, fk.tracks_of(motion(key("右手首", 0, axis_angle((1, 0, 0), 170.0)))), 0))
            p = RS.skin(m, pose)
            r = np.linalg.norm(p[:12, 1:], axis=1)
            self.assertTrue(np.allclose(r, want, atol=1e-5), (r[:3], want))

    def test_sdef_vertices_are_left_alone(self):
        # an SDEF vertex half on 右手捩 and half on 右手首 keeps its kind, bones, weight and SDEF points; the report counts it
        from tests.test_rig_skin import vertex_rec
        w = Writer(bone=2, vertex=2)
        bones = [w.bone("右ひじ", position=(0, 0, 0)), w.bone("右手捩", parent=0, position=(1, 0, 0)),
                 w.bone("右手首", parent=1, position=(2, 0, 0)), w.bone("左ひじ", position=(0, 0, 0)),
                 w.bone("左手捩", parent=3, position=(-1, 0, 0)), w.bone("左手首", parent=4, position=(-2, 0, 0))]
        vs = [vertex_rec(w, (2.0, 0.3, 0.0), "SDEF", (1, 2), (0.5,), sdef=((2.0, 0, 0), (2.0, 0, 0), (2.0, 0, 0))),
              vertex_rec(w, (2.0, -0.3, 0.0), "BDEF2", (1, 2), (0.5,))]
        doc = pmx_edit.loads(w.build(bones=bones, vertices=vs))
        before = [(v.kind, list(v.bones), list(v.weights), v.sdef) for v in doc.vertices]
        rep = pmx_rig.apply(doc, {"joint_helpers": ["wrist"]})
        self.assertEqual((doc.vertices[0].kind, list(doc.vertices[0].bones), list(doc.vertices[0].weights), doc.vertices[0].sdef), before[0])
        self.assertNotEqual((doc.vertices[1].kind, list(doc.vertices[1].bones)), before[1][:2])      # the BDEF2 one is shared out
        self.assertEqual((rep["helpers"][0]["sdef_left"], rep["helpers"][0]["vertices"]), (1, 1))

    def test_unknown_joint_is_refused(self):
        with self.assertRaises(ValueError):
            pmx_rig.apply(pmx_edit.loads(self.data), {"joint_helpers": ["ankle"]})


if __name__ == "__main__":
    unittest.main()
