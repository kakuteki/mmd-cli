"""tools/pmx_skirt.py: a copy of a PMX model whose skirt physics (the skirt's rigid bodies, the joints that hang them and
the ring joints between neighbours) is changed by a recipe, everything else kept byte for byte."""
import importlib.util
import json
import math
import os
import shutil
import tempfile
import unittest

from mmd_cli.formats import pmx, pmx_edit
from tests.test_pmx import RIN, Writer
from tests.test_pmx_edit_physics import joint_bytes, rigid_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


skirt = load_tool("pmx_skirt")
DR, DY = 0.5, 1.0                     # each bone row 0.5 further out and 1.0 lower: every body tilts atan(0.5) = 26.57 deg
REST = math.degrees(math.atan2(DR, DY))


def rad(d):
    return math.radians(d)


def toy_bytes(rows=3, cols=4, limit=10.0, ring=True):
    """上半身 and 髪 bones and bodies; a skirt of `rows` x `cols` bodies hung by joints (スカート_r_c, X/Y/Z limits
    +-limit*(r+1)) and, with ring, joined to the next column by スカート横_r_c; a hair joint that must not change"""
    w = Writer(bone=2, rigid=2)
    bones = [w.bone("上半身", position=(0, 12.0, 0)), w.bone("髪", parent=0, position=(0, 17.0, 0))]
    index = {}
    for r in range(rows + 1):
        for c in range(cols):
            a = 2 * math.pi * c / cols
            radius = 1.0 + DR * r
            index[(r, c)] = len(bones)
            parent = 0 if r == 0 else index[(r - 1, c)]
            bones.append(w.bone("スカート_%d_%d" % (r, c), parent=parent,
                                position=(radius * math.sin(a), 13.0 - DY * r, -radius * math.cos(a))))
    rigids = [rigid_bytes(w, "上半身", 0, group=0, mask=0xFFFF, shape=2, mode=0),
              rigid_bytes(w, "髪", 1, group=2, mass=0.5, mode=2)]
    body = {}
    for r in range(rows):
        for c in range(cols):
            body[(r, c)] = len(rigids)
            rigids.append(rigid_bytes(w, "スカート_%d_%d" % (r, c), index[(r, c)], mass=0.1 - 0.02 * r,
                                      size=(0.3 + 0.1 * r, 0.4, 0.1)))
    joints = [joint_bytes(w, "髪", 0, 1, rotate=((rad(-30), rad(-30), rad(-30)), (rad(30), rad(30), rad(30))))]
    for r in range(rows):
        for c in range(cols):
            lim = rad(limit * (r + 1))
            joints.append(joint_bytes(w, "スカート_%d_%d" % (r, c), 0 if r == 0 else body[(r - 1, c)], body[(r, c)],
                                      rotate=((-lim, -lim, -lim), (lim, lim, lim)), spring_rotate=(40.0, 40.0, 40.0)))
            if ring:
                joints.append(joint_bytes(w, "スカート横_%d_%d" % (r, c), body[(r, c)], body[(r, (c + 1) % cols)],
                                          move=((-0.2, -0.1, -0.2), (0.2, 0.1, 0.2)),
                                          rotate=((rad(-1), rad(-1), rad(-1)), (rad(1), rad(1), rad(1)))))
    return w.build(bones=bones, rigids=rigids, joints=joints)


def by_name(doc):
    names = [pmx_edit.rigid_names(doc, rb)[0] for rb in doc.rigid_bodies]
    return ({n: pmx_edit.rigid_body(rb) for n, rb in zip(names, doc.rigid_bodies)},
            {j.name: j for j in pmx_edit.joints(doc)})


def read(path):
    with open(path, "rb") as f:
        return f.read()


class FindTest(unittest.TestCase):
    def test_the_skirt_is_found(self):
        s = skirt.find_skirt(pmx_edit.loads(toy_bytes()))
        self.assertEqual((s.rows, s.cols), (3, 4))
        self.assertEqual(len(s.vertical), 12)
        self.assertEqual(len(s.ring), 12)
        for (r, c), t in s.rest_tilt.items():
            self.assertAlmostEqual(t, REST, 4)

    def test_a_model_without_a_skirt_or_with_holes_is_refused(self):
        w = Writer()
        with self.assertRaises(ValueError):
            skirt.find_skirt(pmx_edit.loads(w.build(bones=[w.bone("上半身")])))
        doc = pmx_edit.loads(toy_bytes())
        js = [j for j in pmx_edit.joints(doc) if j.name != "スカート_1_2"]
        pmx_edit.set_joints(doc, js)
        with self.assertRaises(ValueError):
            skirt.find_skirt(doc)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.data = toy_bytes()
        self.doc = pmx_edit.loads(self.data)

    def test_an_empty_recipe_changes_nothing(self):
        report = skirt.apply(self.doc, {})
        self.assertEqual(report["changes"], [])
        self.assertEqual(pmx_edit.dumps(self.doc), self.data)

    def test_limit_and_spring_scales_touch_only_the_hanging_joints(self):
        skirt.apply(self.doc, {"limit_scale": 0.5, "spring_scale": 3.0})
        bodies, joints = by_name(self.doc)
        b0, j0 = by_name(pmx_edit.loads(self.data))
        j = joints["スカート_2_1"]
        self.assertAlmostEqual(math.degrees(j.rotate_upper[0]), 15.0, 4)
        self.assertAlmostEqual(math.degrees(j.rotate_lower[2]), -15.0, 4)
        self.assertAlmostEqual(j.spring_rotate[1], 120.0, 4)
        self.assertEqual(joints["スカート横_2_1"], j0["スカート横_2_1"])
        self.assertEqual(joints["髪"], j0["髪"])
        self.assertEqual(bodies, b0)

    def test_reach_caps_every_column_from_its_rest_tilt(self):
        report = skirt.apply(self.doc, {"reach": REST + 20.0})
        _, joints = by_name(self.doc)
        # limits 10, 20, 30 add up to 10, 30, 60: the lowest body would reach REST + 60; capped to REST + 20 -> x 1/3
        for c in range(4):
            for r, deg in enumerate((10.0, 20.0, 30.0)):
                j = joints["スカート_%d_%d" % (r, c)]
                self.assertAlmostEqual(math.degrees(j.rotate_upper[0]), deg / 3.0, 4)
                self.assertAlmostEqual(math.degrees(j.rotate_lower[0]), -deg / 3.0, 4)
                self.assertAlmostEqual(math.degrees(j.rotate_upper[1]), deg, 4)          # Y and Z kept
            self.assertAlmostEqual(report["reach_before"][str(c)], REST + 60.0, 3)
            self.assertAlmostEqual(report["reach_after"][str(c)], REST + 20.0, 3)

    def test_reach_never_widens(self):
        skirt.apply(self.doc, {"reach": 170.0})
        self.assertEqual(pmx_edit.dumps(self.doc), self.data)

    def test_ring_mass_and_damping(self):
        report = skirt.apply(self.doc, {"ring_rotate": 20.0, "ring_move_scale": 0.5, "mass": [0.2, 0.15, 0.1],
                                        "damping": [0.9, 0.95]})
        bodies, joints = by_name(self.doc)
        ring = joints["スカート横_1_3"]
        self.assertAlmostEqual(math.degrees(ring.rotate_upper[1]), 20.0, 4)
        self.assertAlmostEqual(math.degrees(ring.rotate_lower[0]), -20.0, 4)
        self.assertAlmostEqual(ring.move_upper[0], 0.1, 6)
        self.assertAlmostEqual(ring.move_lower[1], -0.05, 6)
        self.assertAlmostEqual(bodies["スカート_1_2"].mass, 0.15, 6)
        self.assertAlmostEqual(bodies["スカート_2_0"].linear_damping, 0.9, 6)
        self.assertAlmostEqual(bodies["スカート_0_0"].angular_damping, 0.95, 6)
        self.assertAlmostEqual(bodies["髪"].mass, 0.5, 6)
        self.assertEqual(bodies["上半身"].mode, 0)
        kinds = {(c["kind"], c["field"]) for c in report["changes"]}
        self.assertIn(("rigid", "mass"), kinds)
        self.assertIn(("joint", "rotate_upper"), kinds)
        one = next(c for c in report["changes"] if c["name"] == "スカート_1_2" and c["field"] == "mass")
        self.assertAlmostEqual(one["old"], 0.08, 6)
        self.assertAlmostEqual(one["new"], 0.15, 6)

    def test_mass_by_fabric_area(self):
        report = skirt.apply(self.doc, {"mass_area": 0.1})
        bodies, _ = by_name(self.doc)
        for r, expect in enumerate((0.1, 0.1 * 0.4 / 0.3, 0.1 * 0.5 / 0.3)):          # the face 0.3 + 0.1 r wide, 0.4 high
            for c in range(4):
                self.assertAlmostEqual(bodies["スカート_%d_%d" % (r, c)].mass, expect, 6)
        self.assertEqual(sum(1 for c in report["changes"] if c["field"] == "mass"), 12)
        with self.assertRaises(ValueError):
            skirt.apply(pmx_edit.loads(self.data), {"mass_area": 0.1, "mass": [0.1, 0.1, 0.1]})

    def test_ceilings_hold_every_lower_end_below_a_line_from_the_waist(self):
        before = len(pmx_edit.joints(self.doc))
        report = skirt.apply(self.doc, {"ceiling": 80.0})
        js = pmx_edit.joints(self.doc)
        self.assertEqual(len(js), before + 12)
        names = [pmx_edit.rigid_names(self.doc, rb)[0] for rb in self.doc.rigid_bodies]
        bones = {b.name: b.position for b in self.doc.bones}
        new = {j.name: j for j in js[before:]}
        self.assertEqual(len(new), 12)
        step = math.hypot(DR, DY)
        for r in range(3):
            for c in range(4):
                j = new["スカート天井_%d_%d" % (r, c)]
                self.assertEqual((names[j.a], names[j.b]), ("上半身", "スカート_%d_%d" % (r, c)))
                low = bones["スカート_%d_%d" % (r + 1, c)]
                self.assertTrue(all(abs(a - b) < 1e-6 for a, b in zip(j.position, low)))
                self.assertEqual(j.rotation, (0.0, 0.0, 0.0))
                ring_y = bones["スカート_0_%d" % c][1]
                ceiling = ring_y - math.cos(math.radians(80.0)) * step * (r + 1)
                self.assertAlmostEqual(j.move_upper[1], ceiling - low[1], 5)
                self.assertGreater(j.move_upper[1], 0.0)
                self.assertLessEqual(j.move_lower[1], -50.0)
                self.assertTrue(all(lo > hi for lo, hi in zip(j.rotate_lower, j.rotate_upper)))     # turning: free
                self.assertEqual((j.spring_move, j.spring_rotate), ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        self.assertEqual(len(report["added"]), 12)
        model = pmx.loads(pmx_edit.dumps(self.doc))
        self.assertEqual(model.counts["joints"], before + 12)
        again = pmx_edit.loads(pmx_edit.dumps(self.doc))
        with self.assertRaises(ValueError):                    # a second time: the ceilings are there already
            skirt.apply(again, {"ceiling": 80.0})

    def test_bad_recipes_are_refused(self):
        for bad in ({"mass": [0.1, 0.1]}, {"damping": [0.5]}, {"limit_scale": -1.0}, {"reach": 0.0}, {"nonsense": 1},
                    {"ceiling": 95.0}, {"mass_area": 0.0}):
            with self.assertRaises(ValueError, msg=bad):
                skirt.apply(pmx_edit.loads(self.data), bad)
        doc = pmx_edit.loads(toy_bytes(ring=False))
        with self.assertRaises(ValueError):
            skirt.apply(doc, {"ring_rotate": 10.0})

    def test_nothing_outside_the_skirt_changes_in_the_file(self):
        skirt.apply(self.doc, {"limit_scale": 0.5, "ring_rotate": 20.0, "mass": [0.2, 0.15, 0.1], "damping": [0.9, 0.95]})
        out = pmx_edit.loads(pmx_edit.dumps(self.doc))
        before = pmx_edit.loads(self.data)
        self.assertEqual(out.header, before.header)
        self.assertEqual(out.middle, before.middle)
        self.assertEqual([b.name for b in out.bones], [b.name for b in before.bones])
        self.assertEqual(out.rigid_bodies[:2], before.rigid_bodies[:2])
        self.assertEqual(pmx_edit.joints(out)[0], pmx_edit.joints(before)[0])


class CommandLineTest(unittest.TestCase):
    def test_writes_the_copy_and_report_and_never_the_model(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "m.pmx")
            with open(src, "wb") as f:
                f.write(toy_bytes())
            before = read(src)
            out, rep = os.path.join(tmp, "m_skirt.pmx"), os.path.join(tmp, "r.json")
            self.assertEqual(skirt.main([src, out, "--report", rep, "--ring-rotate", "15", "--mass", "0.2", "0.15", "0.1"]), 0)
            self.assertEqual(read(src), before)
            self.assertEqual(pmx.load(out).counts["joints"], 25)
            report = json.loads(read(rep).decode("utf-8"))
            self.assertEqual(report["recipe"]["ring_rotate"], 15.0)
            self.assertTrue(report["changes"])
            self.assertEqual(skirt.main([src, src, "--ring-rotate", "15"]), 2)
            self.assertEqual(read(src), before)
        finally:
            shutil.rmtree(tmp)


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinSkirtTest(unittest.TestCase):
    def test_the_skirt_of_sour_rin(self):
        doc = pmx_edit.load(RIN)
        s = skirt.find_skirt(doc)
        self.assertEqual((s.rows, s.cols, len(s.vertical), len(s.ring)), (7, 16, 112, 112))
        self.assertAlmostEqual(s.rest_tilt[(6, 8)], 25.35, 1)
        report = skirt.apply(doc, {"reach": 80.0})
        self.assertAlmostEqual(report["reach_before"]["4"], 102.88, 1)
        self.assertLessEqual(max(report["reach_after"].values()), 80.0 + 1e-6)
        self.assertAlmostEqual(report["reach_after"]["0"], 80.0, 3)        # the front: 82.9 -> 80
        pmx.loads(pmx_edit.dumps(doc))

    def test_the_recommended_ceiling_on_sour_rin(self):
        with open(RIN, "rb") as f:
            data = f.read()
        doc = pmx_edit.loads(data)
        report = skirt.apply(doc, {"ceiling": 70.0})
        self.assertEqual((len(report["changes"]), len(report["added"])), (0, 112))
        out = pmx_edit.loads(pmx_edit.dumps(doc))
        names = [pmx_edit.rigid_names(out, rb)[0] for rb in out.rigid_bodies]
        js = pmx_edit.joints(out)
        self.assertEqual(len(js), 273 + 112)
        self.assertEqual(js[:273], pmx_edit.joints(pmx_edit.loads(data)))          # the model's own joints untouched
        self.assertEqual(out.rigid_bodies, pmx_edit.loads(data).rigid_bodies)      # and its rigid bodies
        for j in js[273:]:
            self.assertEqual(names[j.a], "上半身")
            self.assertTrue(names[j.b].startswith("スカート_"))
            self.assertGreater(j.move_upper[1], 0.0)
        rise = {a["name"]: a["rise"] for a in report["added"]}
        bones = {b.name: b.position for b in out.bones}
        chain = [bones["スカート_%d_0" % r] for r in range(8)]
        expect = chain[0][1] - math.cos(math.radians(70.0)) * sum(math.dist(a, b) for a, b in zip(chain, chain[1:])) - chain[7][1]
        self.assertAlmostEqual(rise["スカート天井_6_0"], expect, 5)          # the front hem may rise 2.88 units, no more
        self.assertAlmostEqual(expect, 2.877, 2)
        self.assertEqual(pmx.loads(pmx_edit.dumps(doc)).counts["joints"], 385)


if __name__ == "__main__":
    unittest.main()
