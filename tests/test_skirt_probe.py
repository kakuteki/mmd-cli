"""tools/skirt_probe.py: a measuring copy of the model whose only drawn parts are small markers of flat, unique colours on
the skirt's bones (and a few body bones), a camera to film them, the markers found again in MMD's pictures, and the
skirt's rigid bodies' tilt worked out from the markers' heights."""
import importlib.util
import json
import math
import os
import shutil
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx import NORMAL, RIN, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_tool("skirt_probe")


def read(path):
    with open(path, "rb") as f:
        return f.read()


def toy_bytes(rows=3, cols=4, extra_uv=0):
    """上半身 and 下半身, a skirt of `rows` x `cols` bones hanging from 上半身 (row r at y 13 - r, column c round the
    waist at radius 1 + 0.3 r), one triangle of the body drawn by one material with a texture"""
    w = Writer(bone=2, vertex=2, extra_uv=extra_uv)
    bones = [w.bone("上半身", position=(0, 12.2, 0)), w.bone("下半身", parent=0, position=(0, 12.2, 0))]
    for r in range(rows):
        for c in range(cols):
            a = 2 * math.pi * c / cols
            radius = 1.0 + 0.3 * r
            parent = 0 if r == 0 else 2 + (r - 1) * cols + c
            bones.append(w.bone("スカート_%d_%d" % (r, c), parent=parent,
                                position=(radius * math.sin(a), 13.0 - r, -radius * math.cos(a))))
    vertices = [w.vertex("BDEF1", (0,)) for _ in range(3)]
    faces = [w.index(i, "vertex") for i in (0, 1, 2)]
    material = (w.text("体") + w.text("body") + struct.pack("<4f3ff3f", 1, 1, 1, 1, 0.5, 0.5, 0.5, 10, 0.6, 0.6, 0.6)
                + bytes([0x1F]) + struct.pack("<4ff", 0, 0, 0, 1, 1.0) + w.index(0, "texture") + w.index(-1, "texture")
                + b"\x00" + b"\x01" + b"\x01" + w.text("") + struct.pack("<i", 3))
    return w.build(vertices=vertices, faces=faces, textures=[w.text("tex\\W.png")], materials=[material], bones=bones)


def toy_doc(**kw):
    return pmx_edit.loads(toy_bytes(**kw))


class PaletteTest(unittest.TestCase):
    def test_colours_are_distinct_far_apart_and_not_dark(self):
        colours = probe.palette(150)
        self.assertEqual(len(set(colours)), 150)
        for c in colours:
            self.assertTrue(all(v in probe.LEVELS for v in c), c)
            self.assertGreaterEqual(sum(c), probe.MIN_SUM)
        d = min(max(abs(a - b) for a, b in zip(p, q)) for i, p in enumerate(colours) for q in colours[i + 1:])
        self.assertGreaterEqual(d, 45)

    def test_too_many_markers_is_an_error(self):
        with self.assertRaises(ValueError):
            probe.palette(10000)


class MarkersTest(unittest.TestCase):
    def test_only_markers_are_drawn_each_on_its_bone(self):
        doc = toy_doc()
        n_vertices = len(doc.vertices)
        legend = probe.build_markers(doc, size=0.05, body=("上半身", "下半身", "左ひざD"))
        g = pmx_edit.geometry(doc)
        markers = legend["markers"]
        self.assertEqual(len(markers), 2 + 12)
        self.assertEqual(legend["missing_body"], ["左ひざD"])
        self.assertEqual(len(doc.vertices), n_vertices + 6 * len(markers))
        self.assertEqual(len(g.materials), 1 + len(markers))
        body = g.materials[0]
        self.assertEqual((body.diffuse[3], body.flags, body.edge_size), (0.0, 0, 0.0))     # the model's own: hidden
        for m, mat in zip(markers, g.materials[1:]):
            self.assertEqual(mat.faces, 24)
            self.assertEqual(mat.diffuse, (0.0, 0.0, 0.0, 1.0))
            self.assertEqual(tuple(round(v * 255) for v in mat.ambient), tuple(m["colour"]))
            self.assertEqual((mat.texture, mat.sphere, mat.shared_toon, mat.toon, mat.flags & 0x1E), (-1, -1, 0, -1, 0))
        start = n_vertices
        for m in markers:
            vs = doc.vertices[start:start + 6]
            start += 6
            self.assertTrue(all(v.kind == "BDEF1" and v.bones == [m["bone_index"]] for v in vs))
            centre = np.mean([v.position() for v in vs], axis=0)
            self.assertTrue(np.allclose(centre, doc.bones[m["bone_index"]].position, atol=1e-5))
            self.assertAlmostEqual(max(abs(a - b) for v in vs for a, b in zip(v.position(), centre)), 0.05, 5)
        skirt = [m for m in markers if m["kind"] == "skirt"]
        self.assertEqual(sorted((m["row"], m["col"]) for m in skirt), [(r, c) for r in range(3) for c in range(4)])
        self.assertEqual(len({tuple(m["colour"]) for m in markers}), len(markers))
        self.assertEqual(legend["rows"], 3)
        self.assertEqual(legend["cols"], 4)
        # the rest lengths of the chains: between bones r and r + 1 of a column
        self.assertAlmostEqual(legend["lengths"]["0"][0], math.hypot(1.0, 0.3), 5)
        self.assertEqual(len(legend["lengths"]["0"]), 2)

    def test_the_copy_is_a_valid_pmx_with_extra_uvs(self):
        doc = toy_doc(extra_uv=2)
        probe.build_markers(doc, size=0.05)
        model = pmx.loads(pmx_edit.dumps(doc))
        self.assertEqual(model.counts["materials"], 1 + 2 + 12)
        self.assertEqual(model.counts["faces"], 1 + 8 * 14)

    def test_a_model_without_a_skirt_is_refused(self):
        w = Writer()
        doc = pmx_edit.loads(w.build(bones=[w.bone("上半身")]))
        with self.assertRaises(ValueError):
            probe.build_markers(doc)

    def test_cli_writes_the_copy_and_legend_and_never_the_model(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "m.pmx")
            with open(src, "wb") as f:
                f.write(toy_bytes())
            before = read(src)
            out, legend = os.path.join(tmp, "m_markers.pmx"), os.path.join(tmp, "legend.json")
            self.assertEqual(probe.main(["markers", src, out, "--legend", legend]), 0)
            self.assertEqual(read(src), before)
            data = json.loads(read(legend).decode("utf-8"))
            self.assertEqual(len(data["markers"]), 14)
            self.assertEqual(pmx.load(out).counts["materials"], 15)
            self.assertEqual(probe.main(["markers", src, src, "--legend", legend]), 2)
            self.assertEqual(read(src), before)
        finally:
            shutil.rmtree(tmp)


class CameraTest(unittest.TestCase):
    CAM = {"look": [1.0, 11.0, -2.0], "yaw": 90.0, "pitch": 0.0, "distance": 700.0, "fov": 1.0, "size": [1920, 1080]}

    def test_the_look_at_point_is_the_picture_centre_and_up_is_up(self):
        u, v = probe.project(self.CAM["look"], self.CAM)
        self.assertAlmostEqual(u, 960.0, 6)
        self.assertAlmostEqual(v, 540.0, 6)
        u2, v2 = probe.project([1.0, 12.0, -2.0], self.CAM)
        self.assertAlmostEqual(u2, 960.0, 6)
        self.assertLess(v2, v)                                          # higher in the world: higher in the picture

    def test_height_back_from_the_picture(self):
        for y in (8.0, 11.0, 14.5):
            for side in (-3.0, 0.0, 3.0):
                u, v = probe.project([1.0 + side, y, -2.0 + side], self.CAM)
                self.assertAlmostEqual(probe.height(v, self.CAM), y, delta=0.03)

    def test_the_camera_file_holds_one_still_camera(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "cam.vmd")
            probe.write_camera(path, self.CAM, last_frame=7742)
            keys = fk.camera_keys(vmd.load(path))
            self.assertEqual([k.frame for k in keys], [0, 7742])
            state = fk.camera_at(keys, 1234)
            self.assertEqual(state.fov, 1.0)
            self.assertAlmostEqual(state.distance, 700.0, 4)
            self.assertAlmostEqual(state.angles[1], 90.0, 4)
            eye = fk.camera_position(state)
            self.assertAlmostEqual(eye[0], 701.0, 3)                   # yaw 90: from the +X side
            self.assertAlmostEqual(eye[1], 11.0, 4)
            u, v = probe.project([1.0, 11.0, 5.0], self.CAM)
            self.assertNotAlmostEqual(u, 960.0, 1)
        finally:
            shutil.rmtree(tmp)


def frame_with(spots, w=64, h=48):
    """a BGRA picture with square spots [(colour, u0, v0, side)], everything else transparent"""
    img = np.zeros((h, w, 4), np.uint8)
    for colour, u0, v0, side in spots:
        r, g, b = colour
        img[v0:v0 + side, u0:u0 + side] = (b, g, r, 255)
    return img


class FindTest(unittest.TestCase):
    def test_centres_of_the_colours_are_found(self):
        colours = probe.palette(3)
        img = frame_with([(colours[0], 10, 5, 4), (colours[2], 40, 30, 6)])
        found = probe.find_markers(img, colours)
        self.assertEqual(sorted(found), [0, 2])
        u, v, n = found[0]                       # the picture's continuous coordinates: pixel i spans i .. i + 1
        self.assertAlmostEqual(u, 12.0)
        self.assertAlmostEqual(v, 7.0)
        self.assertEqual(n, 16)
        self.assertEqual(found[2][2], 36)

    def test_edges_unknown_colours_and_blends_are_left_out(self):
        colours = probe.palette(2)
        img = frame_with([(colours[0], 10, 10, 4), ((1, 2, 3), 30, 30, 4)])
        img[10:14, 14, :] = (colours[0][2], colours[0][1], colours[0][0], 128)      # an anti-aliased edge
        mid = tuple((a + b) // 2 for a, b in zip(colours[0], colours[1]))
        img[0:2, 0:2] = (mid[2], mid[1], mid[0], 255)                                # a blend of two markers
        found = probe.find_markers(img, colours)
        self.assertEqual(sorted(found), [0])
        self.assertEqual(found[0][2], 16)
        self.assertAlmostEqual(found[0][0], 12.0)

    def test_small_shifts_of_the_colour_are_tolerated(self):
        colours = probe.palette(1)
        c = tuple(min(255, v + 5) if v < 255 else v - 5 for v in colours[0])
        found = probe.find_markers(frame_with([(c, 3, 3, 3)]), colours)
        self.assertEqual(found[0][2], 9)


class AnglesTest(unittest.TestCase):
    def test_tilt_of_each_body_from_the_heights(self):
        lengths = [1.0, 1.0, 1.0]
        # hanging straight, horizontal, pointing up at 30 degrees above horizontal
        ys = [10.0, 9.0, 9.0, 9.5]
        tilt, hem = probe.chain_angles(ys, lengths)
        self.assertAlmostEqual(tilt[0], 0.0, 6)
        self.assertAlmostEqual(tilt[1], 90.0, 6)
        self.assertAlmostEqual(tilt[2], 120.0, 6)
        self.assertAlmostEqual(hem, math.degrees(math.asin(-0.5 / 3.0)), 6)

    def test_missing_points_and_noise(self):
        tilt, hem = probe.chain_angles([10.0, None, 8.0, 7.5], [1.0, 1.0, 1.0])
        self.assertIsNone(tilt[0])
        self.assertIsNone(tilt[1])
        self.assertAlmostEqual(tilt[2], 60.0, 6)
        self.assertAlmostEqual(hem, math.degrees(math.asin(-2.5 / 3.0)), 6)
        tilt, _ = probe.chain_angles([10.0, 8.9], [1.0])                 # more drop than the body is long: straight down
        self.assertEqual(tilt[0], 0.0)
        tilt, hem = probe.chain_angles([None, 9.0], [1.0])
        self.assertIsNone(hem)


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinMarkersTest(unittest.TestCase):
    def test_every_skirt_bone_and_the_body_bones_get_a_marker(self):
        doc = pmx_edit.load(RIN)
        legend = probe.build_markers(doc)
        self.assertEqual((legend["rows"], legend["cols"]), (8, 16))
        skirt = [m for m in legend["markers"] if m["kind"] == "skirt"]
        self.assertEqual(len(skirt), 128)
        self.assertEqual(legend["missing_body"], [])
        self.assertEqual(len(legend["lengths"]), 16)
        self.assertTrue(all(len(v) == 7 for v in legend["lengths"].values()))
        g = pmx_edit.geometry(doc)
        self.assertTrue(all(m.diffuse[3] == 0.0 for m in g.materials[:-len(legend["markers"])]))
        pmx.loads(pmx_edit.dumps(doc))


if __name__ == "__main__":
    unittest.main()
