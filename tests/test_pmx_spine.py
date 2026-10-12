"""tools/pmx_spine.py: spine bones inserted into the 上半身 - 上半身2 chain and the trunk's weights spread by height."""
import importlib.util
import os
import struct
import unittest

from mmd_cli.formats import pmx, pmx_edit
from tests.test_pmx import NORMAL, RIN, TAIL_IS_BONE, Writer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pmx_spine = load_tool("pmx_spine")


def vertex_at(w, y, kind, bones, weights=()):
    raw = w.vertex(kind, bones, weights)
    return struct.pack("<3f", 0.0, y, 0.0) + raw[12:]


def toy():
    w = Writer(bone=2, vertex=2)
    T = NORMAL | TAIL_IS_BONE
    bones = [w.bone("腰", position=(0, 11.7, 0), flags=T, tail=1),               # 0
             w.bone("上半身", parent=0, position=(0, 12.225, 0), flags=T, tail=2),  # 1
             w.bone("上半身2", parent=1, position=(0, 13.8, 0), flags=T, tail=3),  # 2
             w.bone("首", parent=2, position=(0, 15.65, 0)),                       # 3
             w.bone("左肩P", parent=2, position=(0.2, 15.4, 0)),                   # 4
             w.bone("下半身", parent=0, position=(0, 12.225, 0)),                   # 5
             w.bone("スカート_0_0", parent=1, position=(0, 13.3, 0))]               # 6
    vs = [vertex_at(w, 12.0, "BDEF2", (1, 5), (0.5,)),          # 0 waist: half 上半身, half 下半身
          vertex_at(w, 12.9, "BDEF1", (1,)),                    # 1
          vertex_at(w, 13.8, "BDEF2", (1, 2), (0.5,)),          # 2
          vertex_at(w, 14.8, "BDEF1", (2,)),                    # 3
          vertex_at(w, 15.5, "BDEF2", (2, 4), (0.6,)),          # 4 shoulder root
          vertex_at(w, 13.3, "BDEF2", (2, 6), (0.3,)),          # 5 skirt: untouched
          vertex_at(w, 16.5, "BDEF1", (3,))]                    # 6 neck: untouched
    frames = [w.frame("体幹", items=[("bone", 1), ("bone", 2), ("bone", 3)])]
    return w.build(vertices=vs, bones=bones, frames=frames)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.doc = pmx_edit.loads(toy())
        self.report = pmx_spine.build(self.doc)
        self.model = pmx.loads(pmx_edit.dumps(self.doc))
        self.names = [b.name for b in self.model.bones]

    def idx(self, n):
        return self.names.index(n)

    def test_chain(self):
        lo, sl, up, su = (self.idx(n) for n in ("上半身", pmx_spine.LUMBAR, "上半身2", pmx_spine.THORACIC))
        B = self.model.bones
        self.assertEqual(B[sl].parent, lo)
        self.assertEqual(B[up].parent, sl)
        self.assertEqual(B[su].parent, up)
        self.assertEqual(B[self.idx("首")].parent, su)
        self.assertEqual(B[self.idx("左肩P")].parent, su)
        self.assertEqual(B[self.idx("スカート_0_0")].parent, sl)      # the skirt's root (y 13.3) follows 腰椎上部
        self.assertTrue(lo < sl < up < su < self.idx("首"))           # parents before children
        self.assertEqual(B[lo].tail, {"bone": sl})
        self.assertEqual(B[up].tail, {"bone": su})
        self.assertEqual(B[su].tail, {"bone": self.idx("首")})
        self.assertAlmostEqual(B[sl].position[1], pmx_spine.LUMBAR_Y, 4)
        self.assertAlmostEqual(B[su].position[1], pmx_spine.THORACIC_Y, 4)
        self.assertTrue(B[su].name_en.isascii() and B[sl].name_en.isascii())
        frame = [it["index"] for it in self.model.display_frames[0].items]
        self.assertEqual(frame, [lo, sl, up, su, self.idx("首")])

    def test_weights(self):
        V = self.doc.vertices
        trunk = {self.idx(n) for n in ("上半身", pmx_spine.LUMBAR, "上半身2", pmx_spine.THORACIC)}

        def part(v):
            return sum(w for b, w in v.pairs() if b in trunk)
        self.assertAlmostEqual(part(V[0]), 0.5, 5)                    # the trunk's part is kept
        self.assertEqual(dict(V[0].pairs())[self.idx("下半身")], 0.5)
        self.assertAlmostEqual(dict(V[0].pairs()).get(self.idx("上半身")), 0.5, 5)   # below the first joint
        self.assertAlmostEqual(dict(V[3].pairs()).get(self.idx("上半身2"), 0.0) + dict(V[3].pairs()).get(self.idx(pmx_spine.THORACIC), 0.0), 1.0, 5)
        self.assertAlmostEqual(part(V[4]), 0.6, 5)
        self.assertGreater(dict(V[4].pairs()).get(self.idx(pmx_spine.THORACIC), 0.0), 0.55)   # shoulder root goes up
        p = dict(V[5].pairs())                  # the skirt vertex: its skirt part stays, its trunk part follows height
        self.assertAlmostEqual(p[self.idx("スカート_0_0")], 0.7, 5)
        self.assertAlmostEqual(part(V[5]), 0.3, 5)
        self.assertGreater(p.get(self.idx(pmx_spine.LUMBAR), 0.0), 0.25)
        self.assertEqual(self.report["with_skirt_or_leg"], 1)
        self.assertEqual(V[6].pairs(), [(self.idx("首"), 1.0)])

    def test_heights_share_smoothly(self):
        ys = [12.0 + 0.05 * i for i in range(80)]
        prev = None
        for y in ys:
            s = pmx_spine.height_shares(y)
            self.assertAlmostEqual(sum(s), 1.0, 9)
            if prev is not None:
                self.assertLess(max(abs(a - b) for a, b in zip(s, prev)), 0.2)
            prev = s


@unittest.skipUnless(os.path.isfile(RIN), "the Sour Rin model is not here")
class SourRinBuildTest(unittest.TestCase):
    def test_rin(self):
        doc = pmx_edit.load(RIN)
        before = len(doc.bones)
        report = pmx_spine.build(doc)
        model = pmx.loads(pmx_edit.dumps(doc))
        self.assertEqual(len(model.bones), before + 2)
        names = [b.name for b in model.bones]
        self.assertEqual(model.bones[names.index("首")].parent, names.index(pmx_spine.THORACIC))
        self.assertGreater(report["reweighted"], 3000)


if __name__ == "__main__":
    unittest.main()
