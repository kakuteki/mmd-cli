"""tools/spine_layer.py: the trunk's bend between the pelvis and the chest shared out over the spine bones, the chest's
world pose kept."""
import math
import os
import unittest

import numpy as np

from mmd_cli import fk, mathutil
from mmd_cli.formats import pmx, pmx_edit, vmd
from tests.test_pmx_spine import load_tool, toy

spine_layer = load_tool("spine_layer")
pmx_spine = load_tool("pmx_spine")


def key(name, frame, euler=(0, 0, 0)):
    return vmd.BoneKey(name, frame, (0.0, 0.0, 0.0), fk.stored(mathutil.euler_to_quat(*euler)), vmd.bone_interpolation(vmd.LINEAR_CURVE))


def models():
    old = pmx.loads(toy())
    doc = pmx_edit.loads(toy())
    pmx_spine.build(doc)
    return old, pmx.loads(pmx_edit.dumps(doc))


def dance():
    return vmd.Motion(model_name="toy", bones=[
        key("上半身", 0), key("上半身", 10, (40, 10, 5)), key("上半身", 20, (-10, -30, 20)),
        key("上半身2", 0), key("上半身2", 10, (5, 20, 0)), key("上半身2", 20, (0, 10, -5)),
        key("下半身", 0), key("下半身", 20, (10, 15, 0)), key("腰", 0), key("腰", 20, (0, 40, 0))])


def chest_frame(model, motion, name, F):
    tr = fk.world_track(model, motion, [name, "首"], 0, F - 1)
    return tr["首"]


class LayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.new = models()
        cls.motion = dance()
        cls.out, cls.report = spine_layer.layer(cls.old, cls.new, cls.motion)

    def test_neck_pose_kept(self):
        a = chest_frame(self.old, self.motion, "上半身2", 21)
        b = chest_frame(self.new, self.out, pmx_spine.THORACIC, 21)
        for (pa, qa), (pb, qb) in zip(a, b):
            self.assertLess(np.linalg.norm(np.subtract(pa, pb)), 1e-4)
            self.assertGreater(abs(sum(x * y for x, y in zip(qa, qb))), 1 - 1e-8)

    def test_keys_on_all_four(self):
        names = {k.name for k in self.out.bones}
        for n in ("上半身", pmx_spine.LUMBAR, "上半身2", pmx_spine.THORACIC, "下半身", "腰"):
            self.assertIn(n, names)

    def test_twist_mostly_thoracic_bend_mostly_lumbar(self):
        r = self.report["shares_measured"]
        self.assertGreater(r["rot"][3] + r["rot"][2], r["rot"][0] + r["rot"][1])
        self.assertGreater(r["flex"][0], r["flex"][3])

    def test_smooth(self):
        self.assertLess(self.report["max_step_deg"]["out"], 2.0 * self.report["max_step_deg"]["in"] + 0.5)

    def test_shares_table(self):
        for m in ("flex", "lat", "rot"):
            self.assertAlmostEqual(sum(spine_layer.SHARES[m]), 1.0, 9)


if __name__ == "__main__":
    unittest.main()
