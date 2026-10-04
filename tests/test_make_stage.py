"""tools/make_stage.py: a stage floor (a dark plane and a grid of glowing lines) as a .x accessory for MMD."""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("make_stage", os.path.join(ROOT, "tools", "make_stage.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_stage = load_tool()


def parse_x(text):
    """the vertices, faces and per-face materials of the one Mesh in a .x text, and its material count"""
    numbers = r"-?\d+\.\d+"
    body = text[text.index("Mesh "):]
    count = int(re.search(r"\{\s*(\d+);", body).group(1))
    vertices = [tuple(float(v) for v in m) for m in re.findall(r"(%s);(%s);(%s);[,;]" % (numbers, numbers, numbers), body)][:count]
    faces = [tuple(int(v) for v in m) for m in re.findall(r"3;(\d+),(\d+),(\d+);[,;]", body.split("MeshMaterialList")[0])]
    materials_part = body.split("MeshMaterialList")[1].split("MeshNormals")[0]
    head = re.search(r"\{\s*(\d+);\s*(\d+);", materials_part)
    n_materials, n_faces = int(head.group(1)), int(head.group(2))
    listed = [int(v) for v in re.findall(r"^\s*(\d+)[,;]\s*$", materials_part.split("Material {")[0], re.M)][2:]
    return {"vertices": vertices, "faces": faces, "face_materials": listed, "materials": n_materials,
            "declared_faces": n_faces, "blocks": materials_part.count("Material {")}


class FloorTest(unittest.TestCase):
    def test_a_plane_and_a_line_every_step_in_both_directions(self):
        stage = make_stage.floor(half=60.0, step=5.0, line=0.06, accent_every=4)
        # 25 positions (-60 .. 60 by 5) in x and in z, each one quad, plus the plane
        self.assertEqual(len(stage.faces), 2 * (1 + 2 * 25))
        self.assertEqual(len(stage.vertices), 4 * (1 + 2 * 25))
        self.assertEqual(len(stage.face_materials), len(stage.faces))
        for face in stage.faces:
            self.assertTrue(all(0 <= i < len(stage.vertices) for i in face), face)
        self.assertEqual(set(stage.face_materials), {0, 1, 2})

    def test_the_lines_lie_on_the_floor_and_the_plane_just_below(self):
        stage = make_stage.floor(half=20.0, step=5.0, line=0.05, accent_every=4)
        plane = [stage.vertices[i] for f, m in zip(stage.faces, stage.face_materials) if m == 0 for i in f]
        lines = [stage.vertices[i] for f, m in zip(stage.faces, stage.face_materials) if m != 0 for i in f]
        self.assertTrue(all(-0.1 < y < 0.0 for _, y, _ in plane), plane[:2])
        self.assertTrue(all(y == 0.0 for _, y, _ in lines))
        self.assertEqual({abs(x) for x, _, _ in plane}, {20.0})
        # a line is 2 * 0.05 wide (an accent line twice that) and centred on a multiple of the step; the two
        # at the edge are cut off there, so nothing hangs out over the plane
        xs = sorted({round(x, 4) for x, _, z in lines if abs(z) == 20.0})
        pairs = list(zip(xs[::2], xs[1::2]))
        self.assertEqual([round((a + b) / 2.0, 4) for a, b in pairs[1:-1]], [-15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0])
        self.assertEqual({round(b - a, 4) for a, b in pairs[1:-1]}, {0.1, 0.2})
        self.assertEqual((pairs[0], pairs[-1]), ((-20.0, -19.9), (19.9, 20.0)))
        self.assertEqual(max(abs(v) for x, _, z in lines for v in (x, z)), 20.0)

    def test_every_fourth_line_is_an_accent_and_zero_means_none(self):
        stage = make_stage.floor(half=20.0, step=5.0, line=0.05, accent_every=4)
        accents = [f for f, m in zip(stage.faces, stage.face_materials) if m == 2]
        self.assertEqual(len(accents), 2 * 2 * 3)                      # at -20, 0, 20 in both directions, 2 faces each
        plain = make_stage.floor(half=20.0, step=5.0, line=0.05, accent_every=0)
        self.assertEqual(set(plain.face_materials), {0, 1})

    def test_bad_measures_are_errors(self):
        for kw in ({"half": 0.0}, {"step": 0.0}, {"step": -5.0}, {"line": 0.0}, {"half": 3.0, "step": 5.0},
                   {"accent_every": -1}):
            args = dict({"half": 60.0, "step": 5.0, "line": 0.06, "accent_every": 4}, **kw)
            with self.assertRaises(ValueError, msg=kw):
                make_stage.floor(**args)


class XTextTest(unittest.TestCase):
    def test_the_text_is_a_directx_mesh_mmd_reads(self):
        stage = make_stage.floor(half=60.0, step=5.0, line=0.06, accent_every=4)
        text = make_stage.x_text(stage)
        text.encode("ascii")
        self.assertTrue(text.startswith("xof 0303txt 0032\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))                 # CRLF throughout
        parsed = parse_x(text)
        self.assertEqual(len(parsed["vertices"]), len(stage.vertices))
        self.assertEqual(parsed["faces"], [tuple(f) for f in stage.faces])
        self.assertEqual(parsed["face_materials"], list(stage.face_materials))
        self.assertEqual((parsed["materials"], parsed["blocks"], parsed["declared_faces"]), (3, 3, len(stage.faces)))
        self.assertIn("MeshNormals", text)

    def test_the_colours_are_emissive_only(self):
        # MMD adds the lit diffuse to the emissive and clamps: with the amber in both, the lines came out
        # yellow (1.0, 1.0, 0.3) under the default light.  The colour lives in the emissive, the diffuse is black
        text = make_stage.x_text(make_stage.floor(20.0, 5.0, 0.05, 4))
        blocks = re.findall(r"Material \{\s*([^}]*)\}", text)
        self.assertEqual(len(blocks), 3)
        emissives = []
        for block in blocks:
            rows = [r.strip() for r in block.strip().splitlines()]
            diffuse = [float(v) for v in rows[0].rstrip(";").split(";")]
            emissive = [float(v) for v in rows[3].rstrip(";").split(";")]
            self.assertEqual(diffuse[:3], [0.0, 0.0, 0.0], block)
            self.assertTrue(0.0 < diffuse[3] <= 1.0, block)
            self.assertGreater(sum(emissive), 0.0, block)
            emissives.append(emissive)
        amber = emissives[2]
        self.assertGreater(amber[0], amber[1] + 0.25)                    # red well above green: amber, not yellow
        self.assertGreater(amber[1], amber[2] + 0.25)

    def test_the_file_holds_a_tenth_of_the_mmd_units(self):
        # MMD shows an accessory at 10 times its numbers (measured: the lines of this floor fall on MMD's own
        # 5 unit grid), so 60 MMD units are 6.0 in the file
        stage = make_stage.floor(half=60.0, step=5.0, line=0.06, accent_every=4)
        parsed = parse_x(make_stage.x_text(stage))
        self.assertEqual(max(abs(x) for x, _, _ in parsed["vertices"]), 6.0)
        self.assertEqual(max(abs(z) for _, _, z in parsed["vertices"]), 6.0)

    def test_the_same_measures_give_the_same_text(self):
        a = make_stage.x_text(make_stage.floor(60.0, 5.0, 0.06, 4))
        b = make_stage.x_text(make_stage.floor(60.0, 5.0, 0.06, 4))
        self.assertEqual(a, b)


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = make_stage.main(argv)
    text = out.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_writes_the_accessory_and_says_what_it_holds(self):
        out = os.path.join(self.folder, "sub", "floor.x")
        code, result = run([out, "--half", "40", "--step", "5"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["out"], os.path.abspath(out))
        with open(out, "rb") as f:
            data = f.read()
        parsed = parse_x(data.decode("ascii"))
        self.assertEqual((result["vertices"], result["faces"]), (len(parsed["vertices"]), len(parsed["faces"])))
        self.assertEqual((result["half"], result["step"]), (40.0, 5.0))
        self.assertEqual(os.listdir(os.path.dirname(out)), ["floor.x"])   # no .part left behind

    def test_bad_measures_exit_2_and_write_nothing(self):
        out = os.path.join(self.folder, "floor.x")
        code, result = run([out, "--step", "0"])
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertIn("message", result["error"])
        self.assertFalse(os.path.exists(out))
        os.makedirs(out)
        code, result = run([out])
        self.assertEqual(code, 2)                                         # a folder is in the way


if __name__ == "__main__":
    unittest.main()
