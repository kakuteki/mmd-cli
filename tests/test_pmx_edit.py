"""formats.pmx_edit: a PMX read whole and written back byte for byte, and bones inserted with every bone index moved."""
import os
import struct
import unittest

from mmd_cli.formats import pmx, pmx_edit
from tests.test_pmx import IK, NORMAL, RIN, TAIL_IS_BONE, APPEND_ROTATE, Writer


def small(w=None, softbodies=None):
    w = w or Writer(bone=2, vertex=2)
    bones = [w.bone("root", position=(0, 0, 0)),
             w.bone("a", parent=0, position=(0, 1, 0), flags=NORMAL | TAIL_IS_BONE, tail=2),
             w.bone("b", parent=1, position=(0, 2, 0)),
             w.bone("tw", parent=1, position=(0, 1.5, 0), flags=NORMAL | APPEND_ROTATE, append=(2, 0.5)),
             w.bone("ik", parent=0, position=(0, 0, 0), flags=NORMAL | IK,
                    ik={"target": 2, "loops": 3, "angle": 0.5, "links": [(1, ((-1, 0, 0), (0, 0, 0))), (0, None)]})]
    vertices = [w.vertex("BDEF1", (2,)), w.vertex("BDEF2", (1, 2), (0.25,)), w.vertex("BDEF4", (0, 1, 2, 3), (0.1, 0.2, 0.3, 0.4)),
                w.vertex("SDEF", (1, 2), (0.5,))]
    faces = [w.index(0, "vertex"), w.index(1, "vertex"), w.index(2, "vertex")]     # the count is of indices
    bone_morph = (w.text("bm") + w.text("") + bytes([4, 2]) + struct.pack("<i", 1) + w.index(2, "bone")
                  + struct.pack("<7f", 0, 0, 0, 0, 0, 0, 1))
    frames = [w.frame("f", items=[("bone", 0), ("bone", 2), ("morph", 0)])]
    rigids = [w.rigid("r", bone=2)]
    return w.build(vertices=vertices, faces=faces, materials=[w.material(faces=3)], bones=bones,
                   morphs=[bone_morph], frames=frames, rigids=rigids, joints=[w.joint(a=0, b=0)], softbodies=softbodies)


class RoundTripTest(unittest.TestCase):
    def test_small_file_comes_back_byte_for_byte(self):
        data = small()
        self.assertEqual(pmx_edit.dumps(pmx_edit.loads(data)), data)

    def test_soft_bodies_and_one_byte_indices(self):
        w = Writer(version=2.1, bone=1, vertex=1)
        data = small(w, softbodies=[w.softbody()])
        self.assertEqual(pmx_edit.dumps(pmx_edit.loads(data)), data)

    def test_vertices_are_readable(self):
        doc = pmx_edit.loads(small())
        self.assertEqual([v.kind for v in doc.vertices], ["BDEF1", "BDEF2", "BDEF4", "SDEF"])
        self.assertEqual(doc.vertices[1].bones, [1, 2])
        self.assertAlmostEqual(doc.vertices[1].weights[0], 0.25)

    @unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
    def test_sour_rin_round_trip(self):
        with open(RIN, "rb") as f:
            data = f.read()
        self.assertEqual(pmx_edit.dumps(pmx_edit.loads(data)), data)


class InsertTest(unittest.TestCase):
    def setUp(self):
        self.doc = pmx_edit.loads(small())

    def test_insert_moves_every_index(self):
        new = pmx_edit.new_bone("mid", "mid_en", position=(0, 1.5, 0), parent=1)
        index = pmx_edit.insert_bone(self.doc, 2, new)
        self.assertEqual(index, 2)
        model = pmx.loads(pmx_edit.dumps(self.doc))
        names = [b.name for b in model.bones]
        self.assertEqual(names, ["root", "a", "mid", "b", "tw", "ik"])
        b = model.bones[3]
        self.assertEqual(b.parent, 1)                       # old parent kept (re-parenting is a separate step)
        self.assertEqual(model.bones[1].tail, {"bone": 3})
        self.assertEqual(model.bones[4].append["parent"], 3)
        self.assertEqual(model.bones[5].ik["target"], 3)
        self.assertEqual(model.bones[5].ik["links"], [1, 0])
        self.assertEqual(model.display_frames[0].items[1], {"kind": "bone", "index": 3})
        self.assertEqual(self.doc.vertices[0].bones, [3])
        self.assertEqual(self.doc.vertices[2].bones, [0, 1, 3, 4])
        self.assertEqual(self.doc.morph_bone_offsets(0)[0][0], 3)
        self.assertEqual(self.doc.rigid_bodies[0].bone, 3)
        self.assertEqual(model.counts["bones"], 6)

    def test_new_bone_parent_given_in_new_numbering(self):
        new = pmx_edit.new_bone("mid", position=(0, 1.5, 0), parent=1)
        pmx_edit.insert_bone(self.doc, 2, new)
        self.doc.bones[3].parent = 2
        model = pmx.loads(pmx_edit.dumps(self.doc))
        self.assertEqual(model.bones[3].parent, 2)
        self.assertEqual(model.bones[2].flags["rotate"], True)
        self.assertEqual(model.bones[2].flags["translate"], False)

    def test_add_to_frame(self):
        new = pmx_edit.new_bone("mid", position=(0, 1.5, 0), parent=1)
        i = pmx_edit.insert_bone(self.doc, 2, new)
        self.doc.frames[0].items.insert(1, (0, i))
        model = pmx.loads(pmx_edit.dumps(self.doc))
        self.assertEqual([it["index"] for it in model.display_frames[0].items if it["kind"] == "bone"], [0, 2, 3])

    def test_set_weights_changes_kind(self):
        v = self.doc.vertices[0]
        v.set_weights([(1, 0.25), (2, 0.75)])
        self.assertEqual(v.kind, "BDEF2")
        self.assertEqual(v.bones, [2, 1])
        self.assertAlmostEqual(v.weights[0], 0.75)
        v.set_weights([(0, 0.1), (1, 0.2), (2, 0.3), (3, 0.4)])
        self.assertEqual(v.kind, "BDEF4")
        v.set_weights([(3, 1.0)])
        self.assertEqual(v.kind, "BDEF1")
        pmx.loads(pmx_edit.dumps(self.doc))                 # still a valid file


if __name__ == "__main__":
    unittest.main()
