"""tools/pmx_eyes.py: catchlight bones, one per highlight quad, that turn with the eye by a share of its rotation."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import struct
import tempfile
import unittest

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx import APPEND_ROTATE, NORMAL, RIN, TRANSLATE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pmx_eyes = load_tool("pmx_eyes")

EYE_Z, PUPIL_Z = -0.562, -0.975         # Sour's Rin: the eye bone and the pupil plane
HL2_Z, HL2_PULL = -0.952, -0.124        # the upper quad, pulled forward by the morph HL２
HL_Z, HL_PULL = -0.864, -0.109          # the lower quad, pulled forward by the morph HL


def quad(cx, cy, z, half_x, half_y):
    return [(cx - half_x, cy + half_y, z), (cx + half_x, cy + half_y, z), (cx + half_x, cy - half_y, z),
            (cx - half_x, cy - half_y, z)]


def toy_bytes(material="HL", with_eyes=True, with_handle=True, extra_bones=(), extra_morphs=(), iris_z=None):
    """a head with Sour's Rin's eye bones (両目 the handle, 右目 / 左目 turning with it by append ratio 1, the iris on a
    child bone), per eye a pupil quad and two highlight quads at Rin's depths, the morphs that reveal them, 瞳大 and
    まばたき, and one skin triangle.  `extra_bones` [(name, parent index, position)] come after the eyes' (translatable
    when they have no parent), `extra_morphs` [(name, kind)] are empty morphs of that kind (1 vertex, 8 material).
    `iris_z` adds an iris (a flat quad of the material 瞳, 0.16 by 0.22 about the pupil) at that depth."""
    w = Writer(bone=2, vertex=2, morph=1, material=1)
    bones = [w.bone("頭", position=(0.0, 16.24, 0.0)),                                                     # 0
             w.bone("両目" if with_handle else "目線", parent=0, position=(0.0, 19.37, -0.26))]              # 1
    if with_eyes:
        bones += [w.bone("右目", parent=0, position=(-0.41, 17.214, EYE_Z), flags=NORMAL | APPEND_ROTATE, append=(1, 1.0),
                         layer=1),                                                                          # 2
                  w.bone("左目", parent=0, position=(0.41, 17.214, EYE_Z), flags=NORMAL | APPEND_ROTATE, append=(1, 1.0),
                         layer=1),                                                                          # 3
                  w.bone("右目子", parent=2, position=(-0.507, 17.143, -0.976), layer=2),                     # 4
                  w.bone("左目子", parent=3, position=(0.507, 17.143, -0.976), layer=2)]                      # 5
    for name, parent, position in extra_bones:
        bones.append(w.bone(name, parent=parent, position=position, flags=NORMAL | (TRANSLATE if parent < 0 else 0)))
    positions, weights = [], []
    pupil, hl2, hl, iris = {}, {}, {}, {}
    for side, s, bone in (("右", -1.0, 4), ("左", 1.0, 5)):
        if not with_eyes:
            bone = 0
        parts = [("pupil", quad(s * 0.507, 17.143, PUPIL_Z, 0.041, 0.057)),
                 ("hl2", quad(s * 0.45, 17.24, HL2_Z, 0.055, 0.045)),
                 ("hl", quad(s * 0.62, 17.04, HL_Z, 0.065, 0.03))]
        if iris_z is not None:
            parts.append(("iris", quad(s * 0.507, 17.143, iris_z, 0.16, 0.22)))
        for name, corners in parts:
            first = len(positions)
            positions += corners
            weights += [bone] * 4
            {"pupil": pupil, "hl2": hl2, "hl": hl, "iris": iris}[name][side] = list(range(first, first + 4))
    skin = len(positions)
    positions.append((0.0, 17.0, -1.2))
    weights.append(0)

    def vertex(p, b):
        return struct.pack("<3f", *p) + w.vertex("BDEF1", (b,))[12:]
    vertices = [vertex(p, b) for p, b in zip(positions, weights)]

    def tris(q):
        return [q[0], q[1], q[2], q[0], q[2], q[3]]
    pupil_faces = tris(pupil["右"]) + tris(pupil["左"]) + (tris(iris["右"]) + tris(iris["左"]) if iris else [])
    hl_faces = tris(hl2["右"]) + tris(hl["右"]) + tris(hl2["左"]) + tris(hl["左"])
    face_faces = [skin, skin, skin]
    faces = [w.index(i, "vertex") for i in face_faces + pupil_faces + hl_faces]
    materials = [w.material("face", faces=3), w.material("瞳", faces=len(pupil_faces)),
                 w.material(material, faces=len(hl_faces))]

    def morph(name, offsets, panel=4):
        body = b"".join(w.index(v, "vertex") + struct.pack("<3f", *o) for v, o in offsets)
        return w.text(name) + w.text("") + bytes([panel, 1]) + struct.pack("<i", len(offsets)) + body
    big, thin = [], []
    for side, s in (("右", -1.0), ("左", 1.0)):
        for v in pupil[side]:
            x, y, _ = positions[v]
            big.append((v, (1.73 * (x - s * 0.507), 1.73 * (y - 17.143), -0.01)))
            thin.append((v, (-0.67 * (x - s * 0.507), -0.67 * (y - 17.143), 0.0)))
    morphs = [morph("瞳大", big, panel=2), morph("瞳細", thin, panel=2),
              morph("HL", [(v, (0.0, 0.0, HL_PULL)) for v in hl["右"] + hl["左"]]),
              morph("HL２", [(v, (0.0, 0.0, HL2_PULL)) for v in hl2["右"] + hl2["左"]]),
              morph("まばたき", [(v, (0.0, -0.17, 0.05)) for v in hl2["右"] + hl2["左"]], panel=2)]
    morphs += [w.morph(name, kind=kind) for name, kind in extra_morphs]
    morphs.append(w.morph("HL消", kind=8, offsets=1))
    frames = [w.frame("目", items=[("bone", 1)] + ([("bone", 2), ("bone", 3)] if with_eyes else []))]
    return w.build(vertices=vertices, faces=faces, materials=materials, bones=bones, morphs=morphs, frames=frames), \
        {"pupil": pupil, "hl2": hl2, "hl": hl, "iris": iris, "positions": positions}


def turn(yaw=0.0, pitch=0.0):
    """the 両目 key rotation (as applied) that turns the gaze by yaw toward +X and pitch up: pitch about X first, then
    yaw about Y (the convention of tools/eye_gaze.py)"""
    def about(axis, degrees):
        h = math.radians(degrees) / 2.0
        return (axis[0] * math.sin(h), axis[1] * math.sin(h), axis[2] * math.sin(h), math.cos(h))
    return fk.multiply(about((0.0, 1.0, 0.0), -yaw), about((1.0, 0.0, 0.0), pitch))


def skinned(model, motion, vertex_bone, rest, frame=0):
    """the world position of a vertex hanging wholly on one bone"""
    pose = fk.Pose(model, motion, [model.bones[vertex_bone].name])
    position, rotation = pose.world(frame)[vertex_bone]
    offset = tuple(r - b for r, b in zip(rest, model.bones[vertex_bone].position))
    return tuple(p + o for p, o in zip(position, fk.rotate(rotation, offset)))


def centroid(points):
    return tuple(sum(p[c] for p in points) / len(points) for c in range(3))


class ToyBuildTest(unittest.TestCase):
    def setUp(self):
        data, self.layout = toy_bytes()
        self.before = pmx_edit.loads(data)
        self.doc = pmx_edit.loads(data)
        self.report = pmx_eyes.build(self.doc, share=0.55, clear=0.0)
        self.model = pmx.loads(pmx_edit.dumps(self.doc))
        self.names = [b.name for b in self.model.bones]

    def test_one_bone_per_quad_added_after_every_bone(self):
        self.assertEqual(self.names[:6], [b.name for b in self.before.bones])
        self.assertEqual(self.names[6:], ["右HL２", "右HL", "左HL２", "左HL"])
        for i in range(6, 10):
            b = self.model.bones[i]
            self.assertEqual(b.parent, 0)                                   # 頭, as the eyes
            self.assertEqual(b.append["parent"], 1)                         # 両目
            self.assertAlmostEqual(b.append["ratio"], 0.55, 6)
            self.assertTrue(b.flags["rotate"] and b.flags["enabled"] and b.flags["append_rotate"])
            self.assertFalse(b.flags["translate"] or b.flags["append_translate"] or b.flags["ik"])
            self.assertTrue(b.name_en.isascii() and b.name_en.startswith(pmx_eyes.EN_PREFIX))
            self.assertGreaterEqual(b.layer, 1)                              # deformed after 両目 (layer 0)
        self.assertEqual(len({b.name_en for b in self.model.bones[6:]}), 4)

    def test_only_the_highlight_vertices_change_bones(self):
        moved = set()
        for key, bone in (("hl2", 6), ("hl", 7)):
            for v in self.layout[key]["右"]:
                self.assertEqual(self.doc.vertices[v].pairs(), [(bone, 1.0)])
                moved.add(v)
        for key, bone in (("hl2", 8), ("hl", 9)):
            for v in self.layout[key]["左"]:
                self.assertEqual(self.doc.vertices[v].pairs(), [(bone, 1.0)])
                moved.add(v)
        for i, (a, b) in enumerate(zip(self.before.vertices, self.doc.vertices)):
            self.assertEqual(a.head, b.head)                                 # no vertex moves
            if i not in moved:
                self.assertEqual(a.pairs(), b.pairs())
        self.assertEqual(self.report["moved_vertices"], 16)

    def test_the_rest_of_the_file_is_kept(self):
        self.assertEqual(self.before.middle, self.doc.middle)
        self.assertEqual([m.body for m in self.before.morphs], [m.body for m in self.doc.morphs])
        self.assertEqual(self.before.tail, self.doc.tail)

    def test_pivot_lies_the_pupil_depth_behind_the_revealed_quad(self):
        P = self.layout["positions"]
        self.assertAlmostEqual(self.report["pupil_depth"]["右目"], EYE_Z - PUPIL_Z, 4)
        for key, pull, bone in (("hl2", HL2_PULL, 6), ("hl", HL_PULL, 7)):
            c = centroid([P[v] for v in self.layout[key]["右"]])
            pivot = self.model.bones[bone].position
            self.assertAlmostEqual(pivot[0], c[0], 5)
            self.assertAlmostEqual(pivot[1], c[1], 5)
            self.assertAlmostEqual(pivot[2], c[2] + pull + (EYE_Z - PUPIL_Z), 5)

    def test_each_light_moves_the_share_of_the_pupil_whatever_its_depth(self):
        P = self.layout["positions"]
        for yaw, pitch in ((6.0, 0.0), (-6.0, 0.0), (0.0, 5.0), (0.0, -5.0)):
            q = fk.stored(turn(yaw, pitch))
            moved = vmd.Motion(model_name="t", bones=[vmd.BoneKey("両目", 0, fk.ZERO, q)])
            rest = vmd.Motion(model_name="t", bones=[vmd.BoneKey("両目", 0, fk.ZERO, fk.IDENTITY)])
            axis = 0 if yaw else 1
            for side, eye_child, bones in (("右", 4, (6, 7)), ("左", 5, (8, 9))):
                pupil = [P[v] for v in self.layout["pupil"][side]]
                d_pupil = (centroid([skinned(self.model, moved, eye_child, p) for p in pupil])[axis]
                           - centroid([skinned(self.model, rest, eye_child, p) for p in pupil])[axis])
                for key, pull, bone in (("hl2", HL2_PULL, bones[0]), ("hl", HL_PULL, bones[1])):
                    pts = [(p[0], p[1], p[2] + pull) for p in (P[v] for v in self.layout[key][side])]
                    d_light = (centroid([skinned(self.model, moved, bone, p) for p in pts])[axis]
                               - centroid([skinned(self.model, rest, bone, p) for p in pts])[axis])
                    self.assertAlmostEqual(d_light / d_pupil, 0.55, delta=0.015, msg=(side, key, yaw, pitch))

    def test_new_bones_join_the_eyes_display_frame(self):
        items = [it["index"] for it in self.model.display_frames[0].items if it["kind"] == "bone"]
        self.assertEqual(items, [1, 2, 3, 6, 7, 8, 9])

    def test_report_lists_the_quads(self):
        quads = self.report["quads"]
        self.assertEqual([q["bone"] for q in quads], ["右HL２", "右HL", "左HL２", "左HL"])
        self.assertEqual([q["reveal"] for q in quads], ["HL２", "HL", "HL２", "HL"])
        self.assertEqual([q["eye"] for q in quads], ["右目", "右目", "左目", "左目"])
        self.assertEqual(self.report["share"], 0.55)
        self.assertEqual(self.report["follows"], "両目")
        json.dumps(self.report, ensure_ascii=False)
        self.assertAlmostEqual(quads[0]["depth"], EYE_Z - (HL2_Z + HL2_PULL), 4)
        self.assertAlmostEqual(quads[1]["depth"], EYE_Z - (HL_Z + HL_PULL), 4)


class SurfaceTest(unittest.TestCase):
    SQUARE = [((-1.0, -1.0, -1.0), (1.0, -1.0, -1.0), (1.0, 1.0, -1.0)),
              ((-1.0, -1.0, -1.0), (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0))]

    def test_frontmost_surface_under_a_point(self):
        tilted = [((-1.0, -1.0, -1.2), (1.0, -1.0, -1.2), (0.0, 1.0, -0.8))]
        self.assertAlmostEqual(pmx_eyes.surface_z(self.SQUARE, 0.2, 0.3), -1.0)
        self.assertAlmostEqual(pmx_eyes.surface_z(self.SQUARE + tilted, 0.0, -1.0), -1.2)
        self.assertAlmostEqual(pmx_eyes.surface_z(self.SQUARE + tilted, 0.0, 1.0), -1.0)
        self.assertIsNone(pmx_eyes.surface_z(self.SQUARE, 1.5, 0.0))

    def test_lift_brings_points_out_in_front(self):
        self.assertAlmostEqual(pmx_eyes.needed_lift([(0.0, 0.0, -0.97)], self.SQUARE, clear=0.0, margin=0.01), 0.04)
        self.assertEqual(pmx_eyes.needed_lift([(0.0, 0.0, -1.1)], self.SQUARE, clear=0.5, margin=0.01), 0.0)
        # a point beside the surface still has to clear it when it may slide over it
        self.assertEqual(pmx_eyes.needed_lift([(1.05, 0.0, -0.97)], self.SQUARE, clear=0.0, margin=0.01), 0.0)
        self.assertAlmostEqual(pmx_eyes.needed_lift([(1.05, 0.0, -0.97)], self.SQUARE, clear=0.1, margin=0.01), 0.04)


class LiftTest(unittest.TestCase):
    """an iris at z -0.99: the upper light (revealed at -1.076) lies in front of it, the lower one (-0.973) behind"""
    IRIS_Z = -0.99

    def setUp(self):
        data, self.layout = toy_bytes(iris_z=self.IRIS_Z)
        self.before = pmx_edit.loads(data)
        self.doc = pmx_edit.loads(data)
        self.report = pmx_eyes.build(self.doc, share=0.55, clear=0.0, margin=0.01)
        self.quads = {q["bone"]: q for q in self.report["quads"]}

    def test_only_the_light_behind_the_iris_comes_out(self):
        want = (HL_Z + HL_PULL) - (self.IRIS_Z - 0.01)
        self.assertAlmostEqual(self.quads["右HL"]["lift"], want, 5)
        self.assertAlmostEqual(self.quads["左HL"]["lift"], want, 5)
        self.assertEqual(self.quads["右HL２"]["lift"], 0.0)
        for v in self.layout["hl"]["左"]:
            a, b = self.before.vertices[v].position(), self.doc.vertices[v].position()
            self.assertAlmostEqual(b[2], a[2] - want, 5)
            self.assertEqual(a[:2], b[:2])
        for v in self.layout["hl2"]["左"] + self.layout["pupil"]["左"] + self.layout["iris"]["左"]:
            self.assertEqual(self.before.vertices[v].head, self.doc.vertices[v].head)
        model = pmx.loads(pmx_edit.dumps(self.doc))
        pivot = [b for b in model.bones if b.name == "左HL"][0].position
        self.assertAlmostEqual(pivot[2], self.quads["左HL"]["centroid"][2] + (EYE_Z - PUPIL_Z), 5)
        self.assertAlmostEqual(self.quads["左HL"]["centroid"][2], HL_Z + HL_PULL - want, 5)

    def test_the_closing_morph_takes_the_lift_back(self):
        self.assertEqual(self.report["closing"], {"まばたき": ["右目", "左目"]})
        blink = pmx_eyes.vertex_morphs(self.doc)["まばたき"]
        want = self.quads["左HL"]["lift"]
        for v in self.layout["hl"]["左"] + self.layout["hl"]["右"]:
            self.assertEqual(blink[v][:2], (0.0, 0.0))
            self.assertAlmostEqual(blink[v][2], want, 5)              # a closed lid hides it where it hid before
        for v in self.layout["hl2"]["左"]:
            self.assertAlmostEqual(blink[v][1], -0.17, 5)             # the upper light's own offsets stay
            self.assertAlmostEqual(blink[v][2], 0.05, 5)
        pmx.loads(pmx_edit.dumps(self.doc))                          # still a valid file
        reveal = pmx_eyes.vertex_morphs(self.doc)["HL"]
        self.assertEqual(reveal, pmx_eyes.vertex_morphs(self.before)["HL"])

    def test_sliding_needs_more(self):
        data, _ = toy_bytes(iris_z=self.IRIS_Z)
        doc = pmx_edit.loads(data)
        report = pmx_eyes.build(doc, share=0.55, clear=0.06, margin=0.01)
        lifts = {q["bone"]: q["lift"] for q in report["quads"]}
        self.assertGreaterEqual(lifts["左HL"], self.quads["左HL"]["lift"])
        self.assertEqual(lifts["左HL２"], 0.0)


class IrisScaleTest(unittest.TestCase):
    """the share by default keeps the light's lag behind the pupil, in iris radii, a human eye's (formula A)"""

    def test_default_share_is_formula_a_across(self):
        data, _ = toy_bytes(iris_z=-0.96)
        doc = pmx_edit.loads(data)
        report = pmx_eyes.build(doc)
        h = pmx_eyes.HUMAN
        lag = h["pupil_to_centre"] / h["iris_radius"]                        # 0.79 (RESEARCH 1.4)
        depth = EYE_Z - PUPIL_Z
        self.assertAlmostEqual(report["share"], 1.0 - lag * 0.16 / depth, 4)
        self.assertAlmostEqual(report["share_a"][1], 1.0 - lag * 0.22 / depth, 4)   # up and down: the iris' half height
        self.assertAlmostEqual(report["share_b"][0], 1.0 - 4.67 / 11.7, 6)          # a human's, head-relative
        self.assertAlmostEqual(report["share_b"][1], 1.0 - 4.67 / 8.9, 6)
        model = pmx.loads(pmx_edit.dumps(doc))
        self.assertAlmostEqual(model.bones[-1].append["ratio"], report["share"], 5)

    def test_an_explicit_share_wins(self):
        data, _ = toy_bytes(iris_z=-0.96)
        report = pmx_eyes.build(pmx_edit.loads(data), share=0.55)
        self.assertEqual(report["share"], 0.55)
        self.assertGreater(report["share_a"][0], 0.6)

    def test_model_scale_reads_the_iris_and_the_pupil(self):
        data, _ = toy_bytes(iris_z=-0.96)
        scale = pmx_eyes.model_scale(pmx_edit.loads(data))
        self.assertAlmostEqual(scale["iris_half_width"], 0.16, 5)
        self.assertAlmostEqual(scale["iris_half_height"], 0.22, 5)
        self.assertAlmostEqual(scale["pupil_depth"], EYE_Z - PUPIL_Z, 5)
        # a degree carries this pupil across more of its iris than a human's (0.413 / 0.16 against 11.7 / 5.91)
        self.assertAlmostEqual(scale["degree_share"][0], (0.413 / 0.16) / (11.7 / 5.91), 2)


class RefusalTest(unittest.TestCase):
    def test_no_highlight_material(self):
        data, _ = toy_bytes(material="光")
        with self.assertRaises(ValueError) as ctx:
            pmx_eyes.build(pmx_edit.loads(data))
        self.assertIn("HL", str(ctx.exception))

    def test_no_eye_bones(self):
        data, _ = toy_bytes(with_eyes=False)
        with self.assertRaises(ValueError):
            pmx_eyes.build(pmx_edit.loads(data))

    def test_no_gaze_handle(self):
        data, _ = toy_bytes(with_handle=False)
        with self.assertRaises(ValueError):
            pmx_eyes.build(pmx_edit.loads(data))

    def test_share_out_of_range(self):
        data, _ = toy_bytes()
        for share in (0.0, -0.2, 1.5):
            with self.assertRaises(ValueError):
                pmx_eyes.build(pmx_edit.loads(data), share=share)

    def test_built_twice(self):
        data, _ = toy_bytes()
        doc = pmx_edit.loads(data)
        pmx_eyes.build(doc)
        with self.assertRaises(ValueError) as ctx:
            pmx_eyes.build(pmx_edit.loads(pmx_edit.dumps(doc)))
        self.assertIn("already", str(ctx.exception))


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = os.path.join(self.tmp, "model.pmx")
        with open(self.src, "wb") as f:
            f.write(toy_bytes()[0])

    def test_writes_the_model_and_the_report(self):
        out, rep = os.path.join(self.tmp, "eyes.pmx"), os.path.join(self.tmp, "r.json")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(pmx_eyes.main([self.src, out, "--report", rep, "--share", "0.5"]), 0)
        self.assertTrue(json.loads(printed.getvalue())["ok"])
        model = pmx.load(out)
        self.assertAlmostEqual(model.bones[6].append["ratio"], 0.5, 6)
        with open(rep, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["share"], 0.5)

    def test_refuses_to_write_over_the_model(self):
        with open(self.src, "rb") as f:
            before = f.read()
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(pmx_eyes.main([self.src, self.src]), 2)
        self.assertIn("overwrite", json.loads(printed.getvalue())["error"]["message"])
        with open(self.src, "rb") as f:
            self.assertEqual(f.read(), before)


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinTest(unittest.TestCase):
    def test_rin(self):
        doc = pmx_edit.load(RIN)
        before = len(doc.bones)
        report = pmx_eyes.build(doc)
        model = pmx.loads(pmx_edit.dumps(doc))
        self.assertEqual(len(model.bones), before + 4)
        self.assertEqual(report["moved_vertices"], 16)
        self.assertEqual(sorted(q["reveal"] for q in report["quads"]), ["HL", "HL", "HL２", "HL２"])
        self.assertAlmostEqual(report["pupil_depth"]["右目"], 0.413, delta=0.005)
        self.assertAlmostEqual(report["pupil_depth"]["左目"], 0.413, delta=0.005)
        self.assertAlmostEqual(report["iris_half_width"], 0.1625, delta=0.001)     # the iris 0.325 wide
        self.assertAlmostEqual(report["share"], 0.691, delta=0.002)               # formula A: 1 - 0.79 x 0.1625 / 0.415
        self.assertTrue(all(0.0 < q["lift"] < 0.06 for q in report["quads"]))
        self.assertIn("まばたき", report["closing"])
        self.assertIn("笑い", report["closing"])


if __name__ == "__main__":
    unittest.main()
