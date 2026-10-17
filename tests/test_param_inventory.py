"""tools/param_inventory.py: the tuned values taken from the code (constants, options' defaults, functions' number
defaults) with their comments, units and what they depend on; the notes from the records joined to them; the table in
the order of the rebuild; and every tool placed in that order."""
import json
import os
import tempfile
import unittest

from tests import mvi_fixtures  # noqa: F401  (puts tools/ on the path)

import param_inventory as PI  # noqa: E402

SOURCE = '''"""a layer"""
import argparse

FPS = 30.0
DOWN_ACC_MAX = 122.0            # units/s^2: the pelvis's downward acceleration at
                                # most this: the real g at 8 cm a unit (122.5)
# a block above the next two
HOLD_RELAX, HOLD_TAU = 0.08, 12.0       # a held vowel eases off by this much, frames
NAMES = ("頭", "首")
SPEED_MAX_DEG_S = 640.0         # the finger's speed at most (Sour's Rin's White.pmx bones)
GATE = 213.4                    # s: the song's turn at 213.4 s throws the skirt up
LOOK = {
    # the glow, tuned on the first excerpt
    "glow": {"threshold": 175, "radius": 14},
    "stage": {"world": 0,       # 1: the stage in the world
                                # (needs --camera)
              "floor_y": 0.0},
    "name": "plain",
}
mode = 3


def dance_range(parts, thr_mm_s=50.0, trim=15, name="a", flag=True, unit=None):
    return parts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dance")
    ap.add_argument("--down-acc-max", type=float, default=DOWN_ACC_MAX, help="units/s^2: the bound")
    ap.add_argument("--lead", type=float, default=0.25, help="s: the pull starts this long before")
    ap.add_argument("--preset", choices=("default", "human"), default="default")
    ap.add_argument("--report")
    ap.add_argument("--no-dip", action="store_true")
    return ap.parse_args(argv)
'''


def entries(source=SOURCE, name="layer_x.py"):
    return {e["name"]: e for e in PI.scan_source(source, name)}


class ScanTest(unittest.TestCase):
    def test_a_constant_with_its_comment_and_its_continuation(self):
        e = entries()["DOWN_ACC_MAX"]
        self.assertEqual(e["kind"], "const")
        self.assertEqual(e["value"], "122.0")
        self.assertEqual(e["line"], 5)
        self.assertIn("the pelvis's downward acceleration", e["comment"])
        self.assertIn("the real g at 8 cm a unit", e["comment"])
        self.assertEqual(e["unit"], "units/s^2")

    def test_a_tuple_target_gives_one_entry_each(self):
        es = entries()
        self.assertEqual(es["HOLD_RELAX"]["value"], "0.08")
        self.assertEqual(es["HOLD_TAU"]["value"], "12.0")
        self.assertIn("eases off", es["HOLD_TAU"]["comment"])
        self.assertIn("a block above", es["HOLD_RELAX"]["above"])

    def test_names_without_numbers_and_lowercase_names_are_left_out(self):
        es = entries()
        self.assertNotIn("NAMES", es)
        self.assertNotIn("mode", es)
        self.assertNotIn("LOOK.name", es)

    def test_a_dict_of_numbers_gives_its_keys_with_their_comments(self):
        es = entries()
        self.assertEqual(es["LOOK.glow.threshold"]["value"], "175")
        self.assertIn("tuned on the first excerpt", es["LOOK.glow.threshold"]["above"])
        self.assertEqual(es["LOOK.stage.world"]["value"], "0")
        self.assertIn("the stage in the world", es["LOOK.stage.world"]["comment"])
        self.assertIn("needs --camera", es["LOOK.stage.world"]["comment"])
        self.assertEqual(es["LOOK.stage.floor_y"]["line"], 17)

    def test_a_functions_number_defaults(self):
        es = entries()
        e = es["dance_range(thr_mm_s)"]
        self.assertEqual(e["kind"], "default")
        self.assertEqual(e["value"], "50.0")
        self.assertEqual(e["unit"], "mm/s")
        self.assertEqual(es["dance_range(trim)"]["value"], "15")
        self.assertNotIn("dance_range(name)", es)
        self.assertNotIn("dance_range(flag)", es)
        self.assertNotIn("dance_range(unit)", es)

    def test_options_with_defaults_and_the_constants_they_name(self):
        es = entries()
        e = es["--down-acc-max"]
        self.assertEqual(e["kind"], "option")
        self.assertEqual(e["constant"], "DOWN_ACC_MAX")
        self.assertEqual(e["value"], "122.0")
        self.assertEqual(es["--lead"]["value"], "0.25")
        self.assertEqual(es["--lead"]["unit"], "s")
        self.assertEqual(es["--preset"]["value"], '"default"')
        self.assertNotIn("--report", es)
        self.assertNotIn("--no-dip", es)
        self.assertNotIn("dance", es)
        # the constant knows its option
        self.assertEqual(es["DOWN_ACC_MAX"]["option"], "--down-acc-max")


class DependsTest(unittest.TestCase):
    def test_lengths_and_accelerations_hang_on_the_body_and_the_dance_on_the_song(self):
        es = entries()
        self.assertTrue(es["DOWN_ACC_MAX"]["depends"]["body"])
        self.assertTrue(es["DOWN_ACC_MAX"]["depends"]["gravity"])
        self.assertIn("retarget", es["DOWN_ACC_MAX"]["review"])
        self.assertFalse(es["HOLD_TAU"]["depends"]["body"])
        self.assertTrue(es["GATE"]["depends"]["dance"])
        self.assertTrue(es["SPEED_MAX_DEG_S"]["depends"]["model"])
        self.assertIn("rig", es["SPEED_MAX_DEG_S"]["review"])
        self.assertFalse(es["FPS"]["depends"]["body"])
        self.assertEqual(es["FPS"]["review"], "")

    def test_a_colour_is_not_gravity(self):
        e = PI.scan_source('PLATE = [10, 12, 20]   # colours are r, g, b of 255\n', "look_x.py")[0]
        self.assertFalse(e["depends"]["gravity"])
        self.assertEqual(e["review"], "")

    def test_gravity_by_its_value_or_its_name(self):
        # balance_layer's and a05's G = 9.81 had no comment and no unit, and went unmarked (review_adapt)
        es = {e["name"]: e for e in PI.scan_source("G = 9.81\nG_CM = 980.0\nHALF = 61.25\nSHARE = 0.6\nGAP = 4\n"
                                                   "G_MIN = 160                     # the green channel at least\n"
                                                   'STEPS = [(18, "物理の重力"), (19, "カメラ")]\n', "x.py")}
        for n in ("G", "G_CM", "HALF"):
            self.assertTrue(es[n]["depends"]["gravity"], n)
            self.assertIn("retarget", es[n]["review"], n)
        for n in ("SHARE", "GAP", "G_MIN", "STEPS"):
            self.assertFalse(es[n]["depends"]["gravity"], n)
            self.assertEqual(es[n]["review"], "", n)

    def test_an_options_unit_from_its_name(self):
        # an option spells the unit with hyphens (foot_layer's --toe-reach-cm went without a unit and unmarked)
        self.assertEqual(PI.unit_of("--toe-reach-cm", ""), "cm")
        self.assertEqual(PI.unit_of("--hover-glide-cm-s", ""), "cm/s")
        self.assertEqual(PI.unit_of("--down-acc-max", ""), "")
        self.assertEqual(PI.unit_of("--taps", ""), "")
        src = 'def main(ap):\n    ap.add_argument("--toe-reach-cm", type=float, default=0.0, help="a pointed foot reaches")\n'
        e = PI.scan_source(src, "feet_x.py")[0]
        self.assertEqual(e["unit"], "cm")
        self.assertIn("retarget", e["review"])

    def test_units_from_the_name_and_the_comment(self):
        self.assertEqual(PI.unit_of("REACH_TOL_CM", ""), "cm")
        self.assertEqual(PI.unit_of("X", "cm: the band"), "cm")
        self.assertEqual(PI.unit_of("X", "units (4 mm): a contact"), "units")
        self.assertEqual(PI.unit_of("LEAD_S", ""), "s")
        self.assertEqual(PI.unit_of("CUTOFF_HZ", ""), "Hz")
        self.assertEqual(PI.unit_of("X", "degrees: the knee's bend"), "deg")
        self.assertEqual(PI.unit_of("X", "frames each part starts after"), "frames")
        self.assertEqual(PI.unit_of("X", "the share of it"), "")


class NotesTest(unittest.TestCase):
    def test_notes_join_and_stale_notes_are_found(self):
        es = PI.scan_source(SOURCE, "layer_x.py")
        notes = {"layer_x.py:DOWN_ACC_MAX": {"from": "HANDOVER 2026-10-16 balance-v2"},
                 "layer_x.py:GONE": {"from": "nothing"}}
        joined, stale = PI.join_notes(es, notes)
        e = [x for x in joined if x["name"] == "DOWN_ACC_MAX"][0]
        self.assertEqual(e["from"], "HANDOVER 2026-10-16 balance-v2")
        self.assertEqual(stale, ["layer_x.py:GONE"])


class RealCodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = PI.inventory()

    def test_the_balance_layers_bound_and_its_option(self):
        es = {(e["tool"], e["name"]): e for e in self.inv["entries"]}
        e = es[("balance_layer.py", "DOWN_ACC_MAX")]
        self.assertEqual(float(e["value"]), 122.0)
        self.assertEqual(e["unit"], "units/s^2")
        self.assertEqual(e["option"], "--down-acc-max")
        self.assertIn(("balance_layer.py", "--down-acc-max"), es)

    def test_every_tool_has_its_place_in_the_order(self):
        here = os.path.dirname(os.path.abspath(PI.__file__))
        files = sorted(f for f in os.listdir(here) if f.endswith(".py")) + \
            sorted("mvi/" + f for f in os.listdir(os.path.join(here, "mvi")) if f.endswith(".py") and f != "__init__.py")
        placed = PI.placed_tools()
        self.assertEqual([f for f in files if f not in placed], [])
        # a placed tool is here, or one a sibling branch brings (retarget, rig, contact)
        self.assertEqual([f for f in placed if f not in files and f not in PI.EXPECTED], [])

    def test_the_notes_name_values_that_exist(self):
        self.assertEqual(self.inv["stale_notes"], [])

    def test_the_steps_that_read_a_later_steps_files_say_so(self):
        # eye_gaze and eye_optics read the camera (step 19) and eye_optics the look's flares (step 18): the order cannot
        # be from upstream there, so those steps name the redo (review_adapt)
        camera = [s for s in self.inv["order"] if "make_camera.py" in s["tools"]][0]
        render = [s for s in self.inv["order"] if "mv_look.py" in s["tools"]][0]
        gaze = [s for s in self.inv["order"] if "eye_gaze.py" in s["tools"]][0]
        optics = [s for s in self.inv["order"] if "eye_optics.py" in s["tools"]][0]
        for later in (camera, render):
            self.assertGreater(later["step"], gaze["step"])
        self.assertIn("eye_gaze", camera["what"])
        self.assertIn("eye_optics", camera["what"])
        self.assertIn("eye_optics", render["what"])
        self.assertIn(str(optics["step"]), camera["what"])

    def test_the_review_order_runs_from_upstream(self):
        steps = [s["step"] for s in self.inv["order"]]
        self.assertEqual(steps, sorted(steps))
        tools = [t for s in self.inv["order"] for t in s["tools"]]
        self.assertLess(tools.index("balance_layer.py"), tools.index("hand_layer.py"))
        self.assertLess(tools.index("hand_layer.py"), tools.index("eye_gaze.py"))
        self.assertLess(tools.index("face_life.py"), tools.index("lip_sync.py"))
        for s in self.inv["order"]:
            for mid in s.get("measures", []):
                self.assertIn(mid, PI.mvi_measure_ids(), (s["step"], mid))

    def test_the_files_are_written_and_the_check_passes_on_them(self):
        d = tempfile.mkdtemp()
        js, md = os.path.join(d, "params.json"), os.path.join(d, "params.md")
        PI.write(self.inv, js, md)
        with open(js, encoding="utf-8") as f:
            back = json.load(f)
        self.assertEqual(len(back["entries"]), len(self.inv["entries"]))
        with open(md, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("DOWN_ACC_MAX", text)
        self.assertIn("見直す順番", text)
        self.assertEqual(PI.check(self.inv, js, md), [])
        with open(md, "a", encoding="utf-8") as f:
            f.write("x")
        self.assertNotEqual(PI.check(self.inv, js, md), [])


if __name__ == "__main__":
    unittest.main()
