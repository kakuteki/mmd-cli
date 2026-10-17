"""tools/mvi/retarget.py (体の触れ): a version whose arm goes into its hips is judged outside the rule and lists the place;
the retargeted version is not; with the source given, the kept touches and the plants are measured too."""
import json
import os
import tempfile
import unittest

from tests import mvi_fixtures as MF  # puts tools/ on the path for mvi

assert MF.TOOLS
from tests import test_retarget as T
from tests.retarget_fixtures import MIKU, RIN, key, motion
from mvi import body, report, retarget as part, shared


def arm_in_hips_dance():
    """the source's arm close to its hips (clear on the source), held over frames 0..4"""
    for a in range(-60, -24, 2):
        for b in (-20, -10, 0, 10, 20):
            m = motion(*T.arm_pose_keys(a, b, 0))
            src = T.arm_penetration(T.MIKU_DATA, MIKU, T.MIKU_BLOBS, m, [0])
            pure = T.retarget.layer(m, T.body(T.MIKU_DATA), T.body(T.RIN_DATA), T.PURE)
            tgt = T.arm_penetration(T.RIN_DATA, RIN, T.RIN_BLOBS, pure.motion, [0])
            if src < -0.05 and 0.15 < tgt < 0.4:
                keys = T.arm_pose_keys(a, b, 0)
                return motion(*keys, *[key(k.name, 4, k.rotation) for k in keys])
    raise AssertionError("no pose found")


class RetargetPartTest(unittest.TestCase):
    def run_part(self, d, dance, source=None):
        paths = {}
        for name, data in (("miku.pmx", T.MIKU_DATA), ("rin.pmx", T.RIN_SHOE_DATA)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as f:
                f.write(data)
        dp = os.path.join(d, "dance_%d.vmd" % len(os.listdir(d)))
        T.vmd.dump(dance, dp)
        spec = {"label": "t", "model": paths["rin.pmx"], "motions": [dp]}
        if source is not None:
            sp = os.path.join(d, "source.vmd")
            T.vmd.dump(source, sp)
            spec["source"] = {"dance": sp, "body": paths["miku.pmx"]}
        m = shared.Measured(body.Version(spec, cache=None))
        return part.measure(m)

    def test_an_arm_in_the_hips_is_outside_the_rule_and_listed(self):
        src = arm_in_hips_dance()
        pure = T.retarget.layer(src, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), T.PURE).motion
        out = T.retarget.layer(src, T.body(T.MIKU_DATA), T.body(T.RIN_SHOE_DATA), {"feet": False, "hands": False}).motion
        with tempfile.TemporaryDirectory() as d:
            a = self.run_part(d, pure)
            b = self.run_part(d, out, source=src)
        ra = {r["id"]: r for r in a["rows"]}
        rb = {r["id"]: r for r in b["rows"]}
        self.assertEqual(ra["retarget.arms_in_body_frames"]["value"], 5)
        self.assertEqual(ra["retarget.arms_in_body_frames"]["judge"]["word"], "上へ外")
        rep = report.mark_listed({"measures": a["rows"], "events": a["events"]})
        listed = [e for e in rep["events"] if e["listed"] and e["id"] == "retarget.arms_in_body_frames"]
        self.assertEqual([(e["first"], e["last"]) for e in listed], [(0, 4)])
        self.assertEqual(rb["retarget.arms_in_body_frames"]["value"], 0)
        self.assertEqual(rb["retarget.arms_in_body_frames"]["judge"]["word"], "中")
        self.assertIn("retarget.contacts_kept_share", rb)          # measured with the source given
        self.assertNotIn("retarget.contacts_kept_share", ra)

    def test_the_ids_have_their_rules(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "mvi", "human.json"),
                  encoding="utf-8") as f:
            human = json.load(f)
        for mid in ("retarget.arms_in_body_frames", "retarget.contacts_kept_share", "retarget.contacts_lost_runs",
                    "retarget.plants_sliding", "retarget.plant_float_pct", "retarget.toe_float_pct"):
            self.assertEqual(human[mid]["kind"], "limit", mid)


if __name__ == "__main__":
    unittest.main()
