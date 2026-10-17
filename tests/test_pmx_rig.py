"""tools/pmx_rig.py: a copy of a PMX model with its rig changed by a recipe, everything else kept byte for byte."""
import json
import math
import os
import struct
import tempfile
import unittest

import numpy as np

from mmd_cli.formats import pmx, pmx_edit
from tests.test_leg_ik import leg_ik, rin_legs_bytes
from tests.test_pmx_spine import load_tool

pmx_rig = load_tool("pmx_rig")


class IkLoopsTest(unittest.TestCase):
    def test_leg_ik_loops_change_and_nothing_else(self):
        data = rin_legs_bytes()
        doc = pmx_edit.loads(data)
        rep = pmx_rig.apply(doc, {"leg_ik_loops": 400})
        out = pmx_edit.dumps(doc)
        rig = leg_ik.LegRig.loads(out)
        for side in ("左", "右"):
            self.assertEqual(rig.sides[side].leg_loops, 400)
            self.assertEqual(rig.sides[side].toe_loops, 3)
            self.assertAlmostEqual(rig.sides[side].leg_limit, 2.0, 6)
        self.assertEqual(sorted(c["bone"] for c in rep["ik"]), ["右足ＩＫ", "左足ＩＫ"])
        self.assertEqual(rep["ik"][0]["old"]["loops"], 40)
        # every byte but the two loop counts is the same
        diff = [i for i, (a, b) in enumerate(zip(data, out)) if a != b]
        self.assertEqual(len(out), len(data))
        self.assertLessEqual(len(diff), 4)

    def test_empty_recipe_is_byte_for_byte(self):
        data = rin_legs_bytes()
        doc = pmx_edit.loads(data)
        pmx_rig.apply(doc, {})
        self.assertEqual(pmx_edit.dumps(doc), data)

    def test_unknown_recipe_key_is_refused(self):
        doc = pmx_edit.loads(rin_legs_bytes())
        with self.assertRaises(ValueError):
            pmx_rig.apply(doc, {"leg_ik_loop": 400})

    def test_command_line_writes_the_copy_and_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "m.pmx")
            with open(src, "wb") as f:
                f.write(rin_legs_bytes())
            out, rep = os.path.join(d, "o.pmx"), os.path.join(d, "r.json")
            self.assertEqual(pmx_rig.main([src, out, "--report", rep, "--leg-ik-loops", "200"]), 0)
            self.assertEqual(leg_ik.LegRig.load(out).sides["左"].leg_loops, 200)
            with open(rep, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["recipe"], {"leg_ik_loops": 200})
            self.assertEqual(pmx_rig.main([src, src, "--leg-ik-loops", "200"]), 2)      # never over the model


if __name__ == "__main__":
    unittest.main()
