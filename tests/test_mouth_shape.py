"""tools/mouth_shape.py: how open each mix of mouth morphs looks, from pictures of the face where the teeth and the rest of
the inside of the mouth are drawn in two key colours."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx import NORMAL, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("mouth_shape", os.path.join(ROOT, "tools", "mouth_shape.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mouth_shape = load_tool()
WHITE, PINK = (250, 248, 246), (240, 176, 178)


def vertex(w, position, uv):
    raw = w.vertex("BDEF1", (0,))
    return struct.pack("<3f3f2f", *position, 0.0, 0.0, -1.0, *uv) + raw[32:]


def face_model(folder):
    """a model in `folder` with a texture tex/m.png (the left half white, the right half pink): materials face (one
    triangle), 口 (two triangles: the first on the white half, the second on the pink half, flags 0x04 | 0x08 | 0x10),
    hair (one triangle); morphs あ い (vertex morphs on the mouth's vertices) and 照れ, a material morph on material 2
    (hair); returns the path of the model"""
    from PIL import Image
    os.makedirs(os.path.join(folder, "tex"), exist_ok=True)
    img = np.zeros((8, 8, 3), np.uint8)
    img[:, :4] = WHITE
    img[:, 4:] = PINK
    Image.fromarray(img, "RGB").save(os.path.join(folder, "tex", "m.png"))
    w = Writer(vertex=2, bone=2, morph=2, material=1, texture=1)
    vs = [vertex(w, (0, 17, -1), (0.5, 0.5)), vertex(w, (0.1, 17, -1), (0.5, 0.5)), vertex(w, (0, 17.1, -1), (0.5, 0.5)),
          # the teeth: UV on the white half
          vertex(w, (-0.2, 16.5, -1.1), (0.1, 0.2)), vertex(w, (0.2, 16.5, -1.1), (0.3, 0.2)), vertex(w, (0, 16.6, -1.1), (0.2, 0.4)),
          # the tongue: UV on the pink half
          vertex(w, (-0.2, 16.4, -1.0), (0.6, 0.6)), vertex(w, (0.2, 16.4, -1.0), (0.9, 0.6)), vertex(w, (0, 16.45, -1.0), (0.8, 0.9)),
          vertex(w, (0, 18, 0), (0.5, 0.5)), vertex(w, (0.1, 18, 0), (0.5, 0.5)), vertex(w, (0, 18.1, 0), (0.5, 0.5))]
    faces = [w.index(i, "vertex") for i in range(12)]
    mats = [w.material("face", texture=0, faces=3), w.material("口", texture=0, faces=6), w.material("hair", texture=0, faces=3)]
    vm = lambda name, dy: w.text(name) + w.text("") + bytes([3, 1]) + struct.pack("<i", 2) + b"".join(  # noqa: E731
        w.index(v, "vertex") + struct.pack("<3f", 0.0, dy, 0.0) for v in (3, 4))
    mat_morph = w.text("照れ") + w.text("") + bytes([4, 8]) + struct.pack("<i", 1) + w.index(2, "material") + b"\x00" + b"\x00" * 112
    data = w.build(vertices=vs, faces=faces, textures=[w.text("tex\\m.png")], materials=mats,
                   bones=[w.bone("頭", flags=NORMAL, position=(0, 16.2, 0))], morphs=[vm("あ", -0.05), vm("い", 0.01), mat_morph])
    doc = pmx_edit.loads(data)
    g = pmx_edit.geometry(doc)
    g.materials[1].flags = 0x04 | 0x08 | 0x10
    pmx_edit.set_geometry(doc, g)
    path = os.path.join(folder, "face.pmx")
    pmx_edit.dump(doc, path)
    return path


class ComboTest(unittest.TestCase):
    def test_a_combo_is_a_name_and_morph_weights(self):
        self.assertEqual(mouth_shape.parse_combo("i+a0.3=い:1,あ:0.3"), ("i+a0.3", {"い": 1.0, "あ": 0.3}))
        self.assertEqual(mouth_shape.parse_combo("neutral="), ("neutral", {}))

    def test_bad_combos_are_refused(self):
        for bad in ("noequals", "=い:1", "x=い", "x=い:1.5", "x=い:-0.1", "x=い:a", "x=い:1,い:0.5"):
            with self.assertRaises(ValueError, msg=bad):
                mouth_shape.parse_combo(bad)

    def test_the_default_combos_hold_the_vowels_the_lip_sync_mixes_and_the_candidates(self):
        names = [n for n, _ in mouth_shape.DEFAULT_COMBOS]
        self.assertEqual(len(names), len(set(names)))
        d = dict(mouth_shape.DEFAULT_COMBOS)
        for n, m in (("neutral", {}), ("a", {"あ": 1.0}), ("i", {"い": 1.0}), ("u", {"う": 1.0}), ("e", {"え": 1.0}),
                     ("o", {"お": 1.0}), ("i+a0.3", {"い": 1.0, "あ": 0.3}), ("u+o0.2", {"う": 1.0, "お": 0.2}),
                     ("i2", {"い２": 1.0})):
            self.assertEqual(d[n], m)


class ShapesMotionTest(unittest.TestCase):
    def test_frame_k_holds_combo_k_and_every_used_morph_is_keyed_on_every_frame(self):
        combos = [("neutral", {}), ("a", {"あ": 1.0}), ("i+a0.3", {"い": 1.0, "あ": 0.3})]
        motion = mouth_shape.shapes_motion(combos)
        keys = {(k.name, k.frame): k.weight for k in motion.morphs}
        self.assertEqual(len(keys), 2 * 3)
        for f, (_, mix) in enumerate(combos):
            for name in ("あ", "い"):
                self.assertAlmostEqual(keys[(name, f)], mix.get(name, 0.0), places=6)
        self.assertEqual(motion.bones, [])


class KeyCopyTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.model = face_model(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_teeth_and_the_inside_get_key_colours_and_nothing_else_changes(self):
        doc = pmx_edit.load(self.model)
        before = pmx_edit.geometry(doc)
        rep = mouth_shape.key_copy(doc, os.path.dirname(self.model))
        g = pmx_edit.geometry(doc)
        self.assertEqual([m.name for m in g.materials], ["face", "口", "hair", mouth_shape.TEETH_MATERIAL])
        self.assertEqual(rep, {"material": "口", "teeth_faces": 1, "inside_faces": 1})
        # the teeth's triangle is the white one (vertices 3 4 5), the inside keeps the pink one, drawn last
        self.assertEqual(g.faces[-3:], [3, 4, 5])
        self.assertEqual(g.faces[:3], [0, 1, 2])
        self.assertEqual(g.faces[3:6], [6, 7, 8])
        self.assertEqual(g.faces[6:9], [9, 10, 11])
        self.assertEqual([m.faces for m in g.materials], [3, 3, 3, 3])
        for m, colour in ((g.materials[1], mouth_shape.KEY_INSIDE), (g.materials[3], mouth_shape.KEY_TEETH)):
            self.assertEqual(tuple(m.diffuse), (0.0, 0.0, 0.0, 1.0))
            self.assertEqual(tuple(m.specular), (0.0, 0.0, 0.0))
            self.assertEqual(tuple(round(c * 255) for c in m.ambient), colour)
            self.assertEqual((m.texture, m.sphere, m.sphere_mode, m.shared_toon, m.toon), (-1, -1, 0, 0, -1))
            self.assertEqual(m.flags & (0x04 | 0x08 | 0x10), 0)
            self.assertEqual(m.edge_size, 0.0)
        # the face and the hair are as they were, so is every morph (the material morph still names the hair)
        for k in (0, 2):
            self.assertEqual(g.materials[k], before.materials[k])
        out = pmx_edit.dumps(doc)
        again = pmx_edit.loads(out)
        orig = pmx_edit.load(self.model)
        self.assertEqual([(m.head, m.body) for m in again.morphs], [(m.head, m.body) for m in orig.morphs])
        self.assertEqual([v.head for v in again.vertices], [v.head for v in orig.vertices])
        self.assertEqual(struct.unpack_from("<b", orig.morphs[2].body, 0)[0], 2)

    def test_a_model_without_the_mouth_material_is_refused(self):
        doc = pmx_edit.load(self.model)
        with self.assertRaises(ValueError):
            mouth_shape.key_copy(doc, os.path.dirname(self.model), material="歯")

    def test_the_colour_rule(self):
        self.assertTrue(mouth_shape.is_teeth(WHITE))
        self.assertTrue(mouth_shape.is_teeth((236, 232, 226)))
        self.assertFalse(mouth_shape.is_teeth(PINK))
        self.assertFalse(mouth_shape.is_teeth((252, 205, 208)))      # the light pink at the gums' edge
        self.assertFalse(mouth_shape.is_teeth((120, 120, 120)))      # grey shade, not the teeth's light


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.model = face_model(self.dir)
        self.out = os.path.join(self.dir, "out")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_plan_writes_the_motion_the_key_copy_and_a_batch_for_both_models(self):
        combos = [("neutral", {}), ("a", {"あ": 1.0}), ("i", {"い": 1.0})]
        rep = mouth_shape.plan(self.model, self.out, combos, exe="C:/MMD/MikuMikuDance.exe")
        key = os.path.join(self.dir, "face_mouthkey.pmx")
        self.assertTrue(os.path.isfile(key))
        self.assertEqual(rep["key_model"], key)
        with open(os.path.join(self.out, "combos.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["combos"], [["neutral", {}], ["a", {"あ": 1.0}], ["i", {"い": 1.0}]])
        motion = vmd.load(os.path.join(self.out, "shapes.vmd"))
        self.assertEqual(sorted({k.frame for k in motion.morphs}), [0, 1, 2])
        with open(os.path.join(self.out, "batch.txt"), encoding="utf-8") as f:
            lines = [json.loads(x) for x in f.read().splitlines() if x]
        loads = [l[2] for l in lines if l[:2] == ["model", "load"]]
        self.assertEqual(loads, [key, self.model])
        renders = [l[2] for l in lines if l[:2] == ["render", "image"]]
        self.assertEqual(len(renders), 6)
        self.assertEqual([os.path.basename(r) for r in renders[:3]], ["000_neutral.png", "001_a.png", "002_i.png"])
        self.assertTrue(all(os.path.basename(os.path.dirname(r)) == "key" for r in renders[:3]))
        self.assertTrue(all(os.path.basename(os.path.dirname(r)) == "plain" for r in renders[3:]))
        # the camera is set again after every frame set (MMD forgets an unregistered camera value on a frame change)
        for i, l in enumerate(lines):
            if l[:2] == ["frame", "set"]:
                self.assertEqual(lines[i + 1][:2], ["camera", "set"])
        cam = [l for l in lines if l[:2] == ["camera", "set"]][0]
        pos = [float(v) for v in cam[cam.index("--pos") + 1:cam.index("--pos") + 4]]
        # straight in front of the mouth material's box at rest (x 0, y between 16.4 and 16.6, its front z)
        self.assertAlmostEqual(pos[0], 0.0, places=4)
        self.assertAlmostEqual(pos[1], 16.5, places=4)
        self.assertAlmostEqual(pos[2], -1.1, places=4)
        self.assertEqual(lines[0][:2], ["launch", "--headless"])
        self.assertEqual(lines[-1], ["quit"])

    def test_an_unknown_morph_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            mouth_shape.plan(self.model, self.out, [("x", {"ないモーフ": 1.0})])
        self.assertFalse(os.path.exists(self.out))

    def test_the_key_copy_never_overwrites_the_model(self):
        with self.assertRaises(ValueError):
            mouth_shape.plan(self.model, self.out, [("a", {"あ": 1.0})], key_model=self.model)


def picture(size=(120, 160), teeth=(), inside=()):
    """a skin-coloured picture (rows, columns) with key-coloured boxes (row0, row1, col0, col1), ends excluded"""
    img = np.zeros(size + (3,), np.uint8)
    img[:] = (236, 200, 190)
    for r0, r1, c0, c1 in teeth:
        img[r0:r1, c0:c1] = mouth_shape.KEY_TEETH
    for r0, r1, c0, c1 in inside:
        img[r0:r1, c0:c1] = mouth_shape.KEY_INSIDE
    return img


class MeasureTest(unittest.TestCase):
    def test_areas_heights_width_and_corners_of_one_picture(self):
        # an open mouth: the upper teeth (4 rows) over the inside (20 rows), 41 columns wide, centred on column 80
        img = picture(teeth=[(50, 54, 60, 101)], inside=[(54, 74, 60, 101)])
        m = mouth_shape.measure_picture(img)
        self.assertEqual(m["teeth_px"], 4 * 41)
        self.assertEqual(m["inside_px"], 20 * 41)
        self.assertEqual(m["open_px"], 24 * 41)
        self.assertEqual((m["open_fill_px"], m["inside_fill_px"]), (24 * 41, 20 * 41))
        self.assertEqual(m["height_mid_px"], 24)
        self.assertEqual(m["inside_height_mid_px"], 20)
        self.assertEqual(m["height_max_px"], 24)
        self.assertEqual(m["width_px"], 41)
        self.assertAlmostEqual(m["corner_rise_px"], 0.0)

    def test_the_inside_no_key_covers_between_the_teeth_and_the_tongue_is_filled_in(self):
        # the upper teeth (rows 40-43), the back of the mouth in the face's own colour (44-59), the tongue (60-69)
        img = picture(teeth=[(40, 44, 60, 101)], inside=[(60, 70, 60, 101)])
        m = mouth_shape.measure_picture(img)
        self.assertEqual(m["open_px"], 14 * 41)
        self.assertEqual(m["open_fill_px"], 30 * 41)
        self.assertEqual(m["inside_fill_px"], 26 * 41)
        self.assertEqual(m["height_mid_px"], 30)
        self.assertEqual(m["inside_height_mid_px"], 26)

    def test_the_corners_higher_than_the_middle_rise(self):
        # a smile: the opening's ends (3 columns each side) sit 6 rows higher than its middle
        img = picture(teeth=[(60, 64, 66, 94), (54, 58, 60, 66), (54, 58, 94, 100)])
        m = mouth_shape.measure_picture(img)
        self.assertEqual(m["inside_px"], 0)
        self.assertEqual(m["height_mid_px"], 4)
        self.assertEqual(m["width_px"], 40)
        self.assertAlmostEqual(m["corner_rise_px"], 6.0)

    def test_a_shut_mouth_has_no_opening(self):
        m = mouth_shape.measure_picture(picture())
        self.assertEqual((m["open_px"], m["height_mid_px"], m["width_px"]), (0, 0, 0))
        self.assertIsNone(m["corner_rise_px"])

    def test_the_models_outline_and_iris_colours_are_not_keys(self):
        # Sour's Rin's outlines are purple, her irises light blue and navy: none of them is the teeth or the inside
        img = picture(teeth=[(50, 54, 60, 101)])
        img[70:72, 40:120] = (150, 60, 150)
        img[80:84, 40:120] = (170, 200, 240)
        img[86:88, 40:120] = (20, 30, 90)
        m = mouth_shape.measure_picture(img)
        self.assertEqual((m["inside_px"], m["teeth_px"], m["width_px"]), (0, 4 * 41, 41))

    def test_key_colours_far_from_the_middle_are_not_the_mouth(self):
        # a blue-green thing in a corner of the picture (an eye, hair) is left out
        img = picture(teeth=[(50, 54, 60, 101)], inside=[(0, 6, 0, 10)])
        m = mouth_shape.measure_picture(img)
        self.assertEqual(m["inside_px"], 0)
        self.assertEqual(m["teeth_px"], 4 * 41)

    def test_relative_numbers_are_against_the_reference(self):
        rows = [{"name": "a", "teeth_px": 100, "inside_px": 400, "open_px": 500, "open_fill_px": 600, "inside_fill_px": 500,
                 "height_mid_px": 20, "inside_height_mid_px": 16, "height_max_px": 21, "width_px": 50, "corner_rise_px": 0.0},
                {"name": "i", "teeth_px": 150, "inside_px": 40, "open_px": 190, "open_fill_px": 210, "inside_fill_px": 60,
                 "height_mid_px": 6, "inside_height_mid_px": 2, "height_max_px": 7, "width_px": 60, "corner_rise_px": 1.0}]
        out = mouth_shape.relative(rows, "a")
        self.assertAlmostEqual(out[1]["of_ref"]["open"], 0.38)
        self.assertAlmostEqual(out[1]["of_ref"]["inside"], 0.1)
        self.assertAlmostEqual(out[1]["of_ref"]["open_fill"], 0.35)
        self.assertAlmostEqual(out[1]["of_ref"]["inside_fill"], 0.12)
        self.assertAlmostEqual(out[1]["of_ref"]["height_mid"], 0.3)
        self.assertAlmostEqual(out[1]["of_ref"]["width"], 1.2)
        self.assertAlmostEqual(out[0]["of_ref"]["open"], 1.0)
        with self.assertRaises(ValueError):
            mouth_shape.relative(rows, "missing")


class MeasureFolderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_measure_reads_the_key_pictures_of_the_plan_and_writes_the_report_and_the_sheet(self):
        from PIL import Image
        combos = [["a", {"あ": 1.0}], ["i", {"い": 1.0}]]
        os.makedirs(os.path.join(self.dir, "key"))
        os.makedirs(os.path.join(self.dir, "plain"))
        with open(os.path.join(self.dir, "combos.json"), "w", encoding="utf-8") as f:
            json.dump({"combos": combos, "size": [160, 120]}, f, ensure_ascii=False)
        pics = {"a": picture(teeth=[(50, 54, 60, 101)], inside=[(54, 74, 60, 101)]), "i": picture(teeth=[(55, 61, 56, 105)])}
        for k, (name, _) in enumerate(combos):
            Image.fromarray(pics[name], "RGB").save(os.path.join(self.dir, "key", "%03d_%s.png" % (k, name)))
            Image.fromarray(picture(), "RGB").save(os.path.join(self.dir, "plain", "%03d_%s.png" % (k, name)))
        rep = mouth_shape.measure(self.dir, reference="a", sheet=os.path.join(self.dir, "sheet.jpg"))
        self.assertEqual([r["name"] for r in rep["combos"]], ["a", "i"])
        i = rep["combos"][1]
        self.assertEqual((i["teeth_px"], i["inside_px"], i["height_mid_px"], i["width_px"]), (6 * 49, 0, 6, 49))
        self.assertAlmostEqual(i["of_ref"]["height_mid"], 0.25)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "sheet.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "mouth_shape.json")))

    def test_a_missing_picture_is_an_error(self):
        os.makedirs(os.path.join(self.dir, "key"))
        with open(os.path.join(self.dir, "combos.json"), "w", encoding="utf-8") as f:
            json.dump({"combos": [["a", {"あ": 1.0}]], "size": [160, 120]}, f)
        with self.assertRaises(ValueError):
            mouth_shape.measure(self.dir, reference="a")


class CliTest(unittest.TestCase):
    def test_the_command_line_refuses_a_bad_combo(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(mouth_shape.main(["plan", "m.pmx", "out", "--combo", "x=い:2"]), 2)
        self.assertIn("within 0..1", err.getvalue())


if __name__ == "__main__":
    unittest.main()
