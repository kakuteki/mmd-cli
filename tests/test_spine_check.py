"""tools/spine_check.py: the pose kept above the chest, and the skin of the trunk measured (flipped faces, area, volume)."""
import unittest

import numpy as np

from mmd_cli.formats import pmx, pmx_edit
from tests.test_pmx_spine import load_tool, toy
from tests.test_spine_layer import dance

spine_check = load_tool("spine_check")
pmx_spine = load_tool("pmx_spine")
spine_layer = load_tool("spine_layer")


class CheckTest(unittest.TestCase):
    def test_pose_error_small(self):
        old = pmx.loads(toy())
        doc = pmx_edit.loads(toy())
        pmx_spine.build(doc)
        new = pmx.loads(pmx_edit.dumps(doc))
        out, _ = spine_layer.layer(old, new, dance())
        err = spine_check.pose_error(old, dance(), new, out, ["首", "左肩P"])
        self.assertLess(err["首"]["pos_cm_max"], 1e-3)
        self.assertLess(err["左肩P"]["rot_deg_max"], 1e-3)

    def test_skin_of_a_tetrahedron(self):
        rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        m = spine_check.skin_metrics(rest, rest * 2.0, faces, np.zeros((4, 4)) + [0, 0, 0, 1])
        self.assertAlmostEqual(m["volume_ratio"], 8.0, 6)
        self.assertEqual(m["flipped"], 0)
        flat = rest.copy()
        flat[3] = [0, 0, -1]                                       # one corner pushed through: three faces turn over
        m = spine_check.skin_metrics(rest, flat, faces, np.zeros((4, 4)) + [0, 0, 0, 1])
        self.assertEqual(m["flipped"], 3)


if __name__ == "__main__":
    unittest.main()
