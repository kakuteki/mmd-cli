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


class KeepTouchesTest(unittest.TestCase):
    """the chest's drift carries the arms: a hand that lies on the hips would go into them or leave them; given the two
    models' bodies, the layer keeps it where the input has it on the hips (tools/touch_layer.keep_layer)"""

    def test_a_hand_on_the_hips_stays_on_them_while_the_trunk_bends(self):
        from tests import test_touch_layer as T
        old_data = T.RIN_DATA
        doc = pmx_edit.loads(old_data)
        pmx_spine.build(doc)
        new_data = pmx_edit.dumps(doc)
        old, new = pmx.loads(old_data), pmx.loads(new_data)
        best = None
        bend = [key("上半身", 0), key("上半身", 10, (40, 0, 0)), key("上半身", 20, (40, 0, 0)), key("上半身2", 0)]
        for a in range(-78, -41, 3):                    # the trunk bent 40 degrees forward, the palm on the hips
            for b in (-50, -40, -30, -20, -10, 0, 10):
                for g in (30, 50, 70, 90):
                    m = vmd.Motion(model_name="toy", bones=bend + T.arm_pose_keys(a, b, g))
                    d = T.sphere_distance(old_data, T.RIN, T.RIN_LEGS, "下半身", m, T.palm(old_data, m, "左", [20]), [20])[0]
                    if 0.025 <= d <= 0.1 and (best is None or abs(d - 0.05) < abs(best[0] - 0.05)):
                        best = (d, (a, b, g), m)
        self.assertIsNotNone(best)
        d, _, m = best
        plain, _ = spine_layer.layer(old, new, m)
        dp = T.sphere_distance(new_data, T.RIN, T.RIN_LEGS, "下半身", plain, T.palm(new_data, plain, "左", [20]), [20])[0]
        self.assertGreater(abs(dp - d), 0.1)                    # (the drift alone takes the palm 8 mm and more off its place)
        RT = T.touch_layer.RT
        kept, report = spine_layer.layer(old, new, m, bodies=(RT.Body.loads(old_data), RT.Body.loads(new_data)))
        dk = T.sphere_distance(new_data, T.RIN, T.RIN_LEGS, "下半身", kept, T.palm(new_data, kept, "左", [20]), [20])[0]
        self.assertLess(abs(dk - d), 0.06)
        self.assertIn("touches", report)


class LayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.new = models()
        cls.motion = dance()
        cls.out, cls.report = spine_layer.layer(cls.old, cls.new, cls.motion)

    def test_neck_pose_kept_with_cap_zero(self):
        out, _ = spine_layer.layer(self.old, self.new, self.motion, place_cap_cm=0.0)
        a = chest_frame(self.old, self.motion, "上半身2", 21)
        b = chest_frame(self.new, out, pmx_spine.THORACIC, 21)
        for (pa, qa), (pb, qb) in zip(a, b):
            self.assertLess(np.linalg.norm(np.subtract(pa, pb)), 1e-4)
            self.assertGreater(abs(sum(x * y for x, y in zip(qa, qb))), 1 - 1e-8)

    def test_neck_rotation_kept_place_within_cap(self):
        a = chest_frame(self.old, self.motion, "上半身2", 21)
        b = chest_frame(self.new, self.out, pmx_spine.THORACIC, 21)
        drift = []
        for (pa, qa), (pb, qb) in zip(a, b):
            drift.append(np.linalg.norm(np.subtract(pa, pb)) * 8.0)
            self.assertGreater(abs(sum(x * y for x, y in zip(qa, qb))), 1 - 1e-8)
        self.assertLess(max(drift), spine_layer.PLACE_CAP_CM + 1e-3)
        self.assertGreater(max(drift), 0.5)                    # the anatomical curve is let move the chest
        self.assertIn("chest_drift_anatomical_cm", self.report)

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

    def test_correction_weighted_by_range(self):
        w = spine_layer.correction_weights()
        self.assertEqual(w.shape, (9,))
        self.assertGreater(w[0], w[6])          # flexion: 上半身 (lumbar) moves more easily than 上半身2
        self.assertIn("opposite_bend_frames", self.report)

    def test_runs_listed(self):
        self.assertEqual(spine_layer.frame_runs(np.array([0, 1, 1, 0, 0, 1, 0, 1], bool), gap=1),
                         [[1, 2], [5, 7]])
        self.assertIn("corrected_runs", self.report)
        self.assertIn("opposite_runs", self.report)

    def test_correction_kept_within_range(self):
        bent = vmd.Motion(model_name="toy", bones=[key("上半身", 0), key("上半身", 10, (70, 0, 0)), key("上半身", 20, (-40, 30, 0))])
        _, rep = spine_layer.layer(self.old, self.new, bent, place_cap_cm=0.0)
        self.assertEqual(rep["beyond_range_frames"], 0)
        self.assertLessEqual(rep["opposite_max_deg"], max(r[0] for r in spine_layer.ranges()) + 1e-6)
        self.assertIn("range_limited_frames", rep)
        self.assertIn("chest_drift_left_cm", rep)
        for k, (flex, lat, rot) in enumerate(rep["local_max_deg"]):     # within range, or no more than the shares asked
            lim = spine_layer.ranges()[k]
            anat = rep["anatomical_local_max_deg"][k]
            self.assertLessEqual(flex, max(lim[0], anat[0]) + 1e-3)
            self.assertLessEqual(lat, max(lim[1], anat[1]) + 1e-3)

    def test_shares_table(self):
        for m in ("flex", "lat", "rot"):
            self.assertAlmostEqual(sum(spine_layer.SHARES[m]), 1.0, 9)


if __name__ == "__main__":
    unittest.main()
