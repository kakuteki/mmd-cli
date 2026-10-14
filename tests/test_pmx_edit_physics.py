"""formats.pmx_edit: the rigid bodies' fields, the joints and the faces, textures and materials read and written back
byte for byte, and changes that touch only what they change."""
import math
import os
import struct
import unittest

from mmd_cli.formats import pmx, pmx_edit
from tests.test_pmx import RIN, Writer


def rigid_bytes(w, name, bone, group=3, mask=0xFFF7, shape=1, size=(0.3, 0.4, 0.1), position=(1.0, 12.0, -1.5),
                rotation=(-0.2, 3.0, 0.1), mass=0.07, damping=(0.999, 0.998), restitution=0.0, friction=0.5, mode=1):
    return (w.text(name) + w.text("") + w.index(bone, "bone")
            + struct.pack("<BHB3f3f3f5fB", group, mask, shape, *size, *position, *rotation, mass, damping[0], damping[1],
                          restitution, friction, mode))


def joint_bytes(w, name, a, b, kind=0, position=(0.0, 12.7, -1.6), rotation=(-0.15, 3.14, 0.0), move=((0, 0, 0), (0, 0, 0)),
                rotate=((-0.07, -0.07, -0.07), (0.07, 0.07, 0.07)), spring_move=(80.0, 80.0, 80.0), spring_rotate=(80.0, 80.0, 80.0)):
    return (w.text(name) + w.text("") + bytes([kind]) + w.index(a, "rigid") + w.index(b, "rigid")
            + struct.pack("<24f", *position, *rotation, *move[0], *move[1], *rotate[0], *rotate[1], *spring_move, *spring_rotate))


def material_bytes(w, name, faces, texture=-1, sphere=-1, shared_toon=None, toon=-1, diffuse=(0.8, 0.7, 0.6, 1.0),
                   specular=(0.1, 0.2, 0.3), power=5.0, ambient=(0.4, 0.5, 0.6), flags=0x1F, edge=(0.0, 0.0, 0.0, 1.0, 0.5),
                   sphere_mode=1, memo="memo"):
    out = [w.text(name), w.text(name + "_en"), struct.pack("<4f3ff3f", *diffuse, *specular, power, *ambient), bytes([flags]),
           struct.pack("<4ff", *edge), w.index(texture, "texture"), w.index(sphere, "texture"), bytes([sphere_mode])]
    if shared_toon is None:
        out += [b"\x00", w.index(toon, "texture")]
    else:
        out += [b"\x01", bytes([shared_toon])]
    out += [w.text(memo), struct.pack("<i", faces)]
    return b"".join(out)


def physics_model(w=None, softbodies=None):
    w = w or Writer(bone=2, rigid=2)
    bones = [w.bone("上半身"), w.bone("スカート_0_0", parent=0), w.bone("スカート_1_0", parent=1)]
    rigids = [rigid_bytes(w, "上半身", 0, group=0, mask=0xFFFF, shape=2, mode=0),
              rigid_bytes(w, "スカート_0_0", 1, mass=0.1), rigid_bytes(w, "スカート_1_0", 2, mass=0.085)]
    joints = [joint_bytes(w, "スカート_0_0", 0, 1, rotate=((-0.01745, -0.01745, -0.01745), (0.01745, 0.01745, 0.01745))),
              joint_bytes(w, "スカート_1_0", 1, 2)]
    return w.build(bones=bones, rigids=rigids, joints=joints, softbodies=softbodies)


def geometry_model(w):
    vertices = [w.vertex("BDEF1", (0,)) for _ in range(6)]
    faces = [w.index(i, "vertex") for i in (0, 1, 2, 3, 4, 5)]
    materials = [material_bytes(w, "肌", 3, texture=0, sphere=1, toon=2),
                 material_bytes(w, "スカート", 3, texture=1, shared_toon=3, flags=0x11, memo="")]
    return w.build(vertices=vertices, faces=faces, textures=[w.text("tex\\skin.png"), w.text("spa\\m.png"), w.text("toon\\W.png")],
                   materials=materials, bones=[w.bone("センター")])


class RigidBodyTest(unittest.TestCase):
    def test_fields_are_read(self):
        doc = pmx_edit.loads(physics_model())
        rb = doc.rigid_bodies[2]
        self.assertEqual(pmx_edit.rigid_names(doc, rb), ("スカート_1_0", ""))
        body = pmx_edit.rigid_body(rb)
        self.assertEqual((body.group, body.mask, body.shape, body.mode), (3, 0xFFF7, 1, 1))
        self.assertAlmostEqual(body.mass, 0.085, 6)
        self.assertAlmostEqual(body.linear_damping, 0.999, 6)
        self.assertAlmostEqual(body.angular_damping, 0.998, 6)
        self.assertAlmostEqual(body.friction, 0.5, 6)
        self.assertEqual(len(body.size), 3)
        self.assertAlmostEqual(body.rotation[1], 3.0, 6)

    def test_writing_the_same_fields_back_keeps_the_bytes(self):
        data = physics_model()
        doc = pmx_edit.loads(data)
        for rb in doc.rigid_bodies:
            pmx_edit.set_rigid_body(rb, pmx_edit.rigid_body(rb))
        self.assertEqual(pmx_edit.dumps(doc), data)

    def test_a_change_touches_only_its_own_bytes(self):
        data = physics_model()
        doc = pmx_edit.loads(data)
        rb = doc.rigid_bodies[1]
        body = pmx_edit.rigid_body(rb)
        body.mass, body.angular_damping = 0.25, 0.9
        pmx_edit.set_rigid_body(rb, body)
        out = pmx_edit.dumps(doc)
        self.assertEqual(len(out), len(data))
        changed = [i for i, (a, b) in enumerate(zip(data, out)) if a != b]
        self.assertTrue(changed)
        self.assertLess(max(changed) - min(changed), 12)          # within the mass .. angular damping floats
        again = pmx_edit.rigid_body(pmx_edit.loads(out).rigid_bodies[1])
        self.assertAlmostEqual(again.mass, 0.25, 6)
        self.assertAlmostEqual(again.angular_damping, 0.9, 6)
        self.assertAlmostEqual(again.linear_damping, 0.999, 6)

    def test_bad_values_are_refused(self):
        doc = pmx_edit.loads(physics_model())
        rb = doc.rigid_bodies[1]
        body = pmx_edit.rigid_body(rb)
        body.mode = 3
        with self.assertRaises(ValueError):
            pmx_edit.set_rigid_body(rb, body)
        body = pmx_edit.rigid_body(rb)
        body.size = (1.0, 2.0)
        with self.assertRaises(ValueError):
            pmx_edit.set_rigid_body(rb, body)


class JointTest(unittest.TestCase):
    def test_joints_are_read_with_their_limits_in_radians(self):
        doc = pmx_edit.loads(physics_model())
        js = pmx_edit.joints(doc)
        self.assertEqual([(j.name, j.kind, j.a, j.b) for j in js], [("スカート_0_0", 0, 0, 1), ("スカート_1_0", 0, 1, 2)])
        self.assertAlmostEqual(math.degrees(js[0].rotate_upper[0]), 1.0, 3)
        self.assertAlmostEqual(math.degrees(js[1].rotate_lower[2]), -4.01, 2)
        self.assertEqual(js[1].spring_rotate, (80.0, 80.0, 80.0))

    def test_round_trip_with_and_without_soft_bodies(self):
        for version, softbodies in ((2.0, None), (2.1, "two")):
            w = Writer(version=version, bone=2, rigid=1)
            data = physics_model(w, softbodies=[w.softbody(anchors=2, pins=3), w.softbody()] if softbodies else None)
            doc = pmx_edit.loads(data)
            pmx_edit.set_joints(doc, pmx_edit.joints(doc))
            self.assertEqual(pmx_edit.dumps(doc), data, version)
            if softbodies:
                self.assertEqual(pmx.loads(pmx_edit.dumps(doc)).counts["soft_bodies"], 2)

    def test_a_changed_limit_is_written_and_the_rest_kept(self):
        data = physics_model()
        doc = pmx_edit.loads(data)
        js = pmx_edit.joints(doc)
        js[1].rotate_upper = (0.5, 0.07, 0.07)
        js[1].spring_rotate = (1.0, 2.0, 3.0)
        pmx_edit.set_joints(doc, js)
        out = pmx_edit.dumps(doc)
        self.assertEqual(len(out), len(data))
        back = pmx_edit.joints(pmx_edit.loads(out))
        self.assertAlmostEqual(back[1].rotate_upper[0], 0.5, 6)
        self.assertAlmostEqual(back[1].spring_rotate[2], 3.0, 6)
        self.assertEqual(back[0], js[0])
        self.assertEqual(pmx.loads(out).counts["joints"], 2)

    def test_joints_must_name_rigid_bodies_that_exist(self):
        doc = pmx_edit.loads(physics_model())
        js = pmx_edit.joints(doc)
        js[0].b = 7
        with self.assertRaises(ValueError):
            pmx_edit.set_joints(doc, js)


class GeometryTest(unittest.TestCase):
    def test_faces_textures_and_materials_are_read(self):
        w = Writer(vertex=1, texture=1, material=1)
        g = pmx_edit.geometry(pmx_edit.loads(geometry_model(w)))
        self.assertEqual(g.faces, [0, 1, 2, 3, 4, 5])
        self.assertEqual(g.textures, ["tex\\skin.png", "spa\\m.png", "toon\\W.png"])
        m0, m1 = g.materials
        self.assertEqual((m0.name, m0.name_en, m0.texture, m0.sphere, m0.shared_toon, m0.toon, m0.memo, m0.faces),
                         ("肌", "肌_en", 0, 1, 0, 2, "memo", 3))
        self.assertEqual((m1.name, m1.texture, m1.shared_toon, m1.toon, m1.flags, m1.memo), ("スカート", 1, 1, 3, 0x11, ""))
        self.assertAlmostEqual(m0.diffuse[1], 0.7, 6)
        self.assertAlmostEqual(m0.ambient[2], 0.6, 6)
        self.assertAlmostEqual(m0.edge_size, 0.5, 6)

    def test_round_trip_for_every_index_size(self):
        for size in (1, 2, 4):
            w = Writer(vertex=size, texture=size, material=size)
            data = geometry_model(w)
            doc = pmx_edit.loads(data)
            pmx_edit.set_geometry(doc, pmx_edit.geometry(doc))
            self.assertEqual(pmx_edit.dumps(doc), data, size)

    def test_a_material_and_its_faces_can_be_added(self):
        w = Writer(vertex=2, texture=1, material=1)
        doc = pmx_edit.loads(geometry_model(w))
        g = pmx_edit.geometry(doc)
        g.faces += [5, 4, 3]
        g.materials.append(pmx_edit.Material("印", "mark", (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 0.0, (1.0, 0.0, 0.0), 0x01,
                                             (0.0, 0.0, 0.0, 0.0), 0.0, -1, -1, 0, 0, -1, "", 3))
        pmx_edit.set_geometry(doc, g)
        model = pmx.loads(pmx_edit.dumps(doc))
        self.assertEqual((model.counts["faces"], model.counts["materials"]), (3, 3))
        back = pmx_edit.geometry(pmx_edit.loads(pmx_edit.dumps(doc)))
        self.assertEqual(back.materials[2].name, "印")
        self.assertEqual(back.faces[-3:], [5, 4, 3])

    def test_face_counts_must_match_the_materials(self):
        w = Writer()
        doc = pmx_edit.loads(geometry_model(w))
        g = pmx_edit.geometry(doc)
        g.faces += [0, 1, 2]
        with self.assertRaises(ValueError):
            pmx_edit.set_geometry(doc, g)


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinPhysicsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(RIN, "rb") as f:
            cls.data = f.read()
        cls.doc = pmx_edit.loads(cls.data)

    def test_counts_and_a_skirt_joint(self):
        js = pmx_edit.joints(self.doc)
        self.assertEqual((len(self.doc.rigid_bodies), len(js)), (186, 273))
        j = next(j for j in js if j.name == "スカート_1_0")
        names = [pmx_edit.rigid_names(self.doc, rb)[0] for rb in self.doc.rigid_bodies]
        self.assertEqual((names[j.a], names[j.b]), ("スカート_0_0", "スカート_1_0"))
        self.assertAlmostEqual(math.degrees(j.rotate_upper[0]), 4.2, 1)
        top = next(j for j in js if j.name == "スカート_0_0")
        self.assertEqual(names[top.a], "上半身")

    def test_skirt_bodies(self):
        bodies = {pmx_edit.rigid_names(self.doc, rb)[0]: pmx_edit.rigid_body(rb) for rb in self.doc.rigid_bodies}
        self.assertEqual(sum(1 for n in bodies if n.startswith("スカート_")), 112)
        self.assertAlmostEqual(bodies["スカート_6_8"].mass, 0.01, 6)
        self.assertEqual(bodies["スカート_6_8"].mode, 1)
        self.assertAlmostEqual(bodies["スカート_0_0"].linear_damping, 0.999, 6)

    def test_whole_file_round_trip_through_every_new_reader(self):
        doc = pmx_edit.loads(self.data)
        pmx_edit.set_joints(doc, pmx_edit.joints(doc))
        pmx_edit.set_geometry(doc, pmx_edit.geometry(doc))
        for rb in doc.rigid_bodies:
            pmx_edit.set_rigid_body(rb, pmx_edit.rigid_body(rb))
        self.assertEqual(pmx_edit.dumps(doc), self.data)


if __name__ == "__main__":
    unittest.main()
