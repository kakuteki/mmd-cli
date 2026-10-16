"""tools/mme_shadow.py: the MME effect of the soft self shadow and the files round it."""
import hashlib
import importlib.util
import math
import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("mme_shadow", os.path.join(ROOT, "tools", "mme_shadow.py"))
mme_shadow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mme_shadow)


def define(text, name):
    m = re.search(r"^#define %s (\S+)$" % name, text, re.M)
    return float(m.group(1)) if m else None


def array(text, name):
    m = re.search(r"static const float3 %s\[(\d+)\] = \{(.*?)\};" % name, text, re.S)
    rows = re.findall(r"float3\(([^)]*)\)", m.group(2))
    return int(m.group(1)), [tuple(float(v) for v in r.split(",")) for r in rows]


class EffectTest(unittest.TestCase):
    def test_it_replaces_only_the_body_with_the_self_shadow(self):
        # MMD draws the passes the effect has no technique for with its own shaders (MME's REFERENCE 1.2): the shadow
        # map (zplot), the outline (edge), the ground shadow and the body without the self shadow stay MMD's
        text = mme_shadow.effect()
        passes = set(re.findall(r'MMDPass = "(\w+)"', text))
        self.assertEqual(passes, {"object_ss"})
        # one technique for every combination of texture, sphere map and toon
        combos = re.findall(r"^SS_TECH\(SS_(\d{3}), (true|false), (true|false), (true|false)\)$", text, re.M)
        self.assertEqual(len(combos), 8)
        self.assertEqual({tuple(v == "true" for v in c[1:]) for c in combos},
                         {(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)})
        self.assertTrue(text.isascii())

    def test_the_gaussian_points_sum_to_one_and_fall_off_with_the_radius(self):
        text = mme_shadow.effect(n_taps=32)
        n, rows = array(text, "KERNEL")
        self.assertEqual(n, 32)
        self.assertAlmostEqual(sum(w for _, _, w in rows), 1.0, places=5)
        radii = [math.hypot(x, y) for x, y, _ in rows]
        self.assertLessEqual(max(radii), mme_shadow.KERNEL_SIGMAS + 1e-6)
        # a point twice as far out (in standard deviations) weighs exp(-1.5 r^2) times as much
        (x0, y0, w0), (x1, y1, w1) = rows[0], rows[-1]
        r0, r1 = math.hypot(x0, y0), math.hypot(x1, y1)
        self.assertAlmostEqual(w1 / w0, math.exp(-0.5 * (r1 * r1 - r0 * r0)), places=4)
        # the points cover the disc evenly: no two of them on the same spot
        self.assertEqual(len({(round(x, 4), round(y, 4)) for x, y, _ in rows}), 32)

    def test_the_settings_reach_the_shader(self):
        text = mme_shadow.effect(blur=5.0, min_blur=0.6, n_taps=24, search_taps=12)
        self.assertAlmostEqual(define(text, "SS_BLUR_RAD"), math.radians(5.0), places=8)
        self.assertAlmostEqual(define(text, "SS_MIN_UV"), 0.6 / mme_shadow.SHADOW_MAP, places=8)
        self.assertEqual(define(text, "SS_TAPS"), 24)
        self.assertEqual(define(text, "SS_SEARCH"), 12)
        self.assertEqual(define(text, "SS_CONTACT"), 1)
        self.assertEqual(define(text, "SS_DEBUG"), 0)
        self.assertEqual(define(mme_shadow.effect(debug=True), "SS_DEBUG"), 1)
        self.assertEqual(define(mme_shadow.effect(contact=False), "SS_CONTACT"), 0)

    def test_sharp_is_mmds_own_test_at_one_point(self):
        text = mme_shadow.effect(sharp=True)
        self.assertEqual(define(text, "SS_TAPS"), 1)
        self.assertEqual(define(text, "SS_CONTACT"), 0)
        self.assertEqual(define(text, "SS_MIN_UV"), 0.0)
        n, rows = array(text, "KERNEL")
        self.assertEqual(rows, [(0.0, 0.0, 1.0)])
        # MMD's test: 1 - saturate(max(z - map, 0) * 1500 - 0.3) in mode 1, the slope 8000 x v in mode 2
        self.assertIn("#define SKII1 1500.0", text)
        self.assertIn("#define SKII2 8000.0", text)
        self.assertIn("slope - 0.3f", text)

    def test_wrong_settings_are_refused(self):
        for bad in ({"blur": -1}, {"blur": 45}, {"min_blur": -0.1}, {"n_taps": 0}, {"n_taps": 65}, {"search_taps": 0}):
            with self.assertRaises(ValueError, msg=bad):
                mme_shadow.effect(**bad)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.models = os.path.join(self.folder, "models", "Rin")
        os.makedirs(os.path.join(self.models, "tex"))
        self.model = os.path.join(self.models, "White.pmx")
        with open(self.model, "wb") as f:
            f.write(b"PMX model bytes")
        with open(os.path.join(self.models, "tex", "skin.png"), "wb") as f:
            f.write(b"texture")

    def test_prepare_copies_the_folder_and_writes_the_effect_beside_the_copy(self):
        out = os.path.join(self.folder, "out")
        got = mme_shadow.prepare(self.model, out)
        self.assertEqual(os.path.normcase(got["model"]), os.path.normcase(os.path.join(out, "Rin", "White.pmx").replace("\\", "/")))
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "tex", "skin.png")))
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "White.fx")))         # MME takes <model name>.fx
        self.assertEqual(sorted(os.listdir(self.models)), ["White.pmx", "tex"])       # the original is not written
        # a variant: <model>[<variant>.fx].pmx beside <variant>.fx
        got = mme_shadow.prepare(self.model, out, variant="debug_soft", debug=True)
        self.assertTrue(got["model"].endswith("Rin/White[debug_soft.fx].pmx"))
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes")
        with open(got["effect"], encoding="ascii") as f:
            self.assertIn("#define SS_DEBUG 1", f.read())
        with self.assertRaises(ValueError):
            mme_shadow.prepare(self.model, out, variant="no spaces")

    def test_prepare_refuses_to_write_into_the_models_own_folder(self):
        with self.assertRaises(ValueError):
            mme_shadow.prepare(self.model, os.path.join(self.folder, "models"))

    def test_check_knows_mme_by_its_files(self):
        mmd = os.path.join(self.folder, "mmd")
        os.makedirs(mmd)
        exe = os.path.join(mmd, "MikuMikuDance.exe")
        open(exe, "wb").close()
        self.assertEqual(mme_shadow.check(exe), {"installed": False, "files": {n: "missing" for n in mme_shadow.MME_FILES}})
        for name in mme_shadow.MME_FILES:
            with open(os.path.join(mmd, name), "wb") as f:
                f.write(b"not the dll")
        self.assertEqual(set(mme_shadow.check(exe)["files"].values()), {"different"})
        # the digest is SHA-256 of the file
        self.assertEqual(mme_shadow.sha256(exe), hashlib.sha256(b"").hexdigest())


if __name__ == "__main__":
    unittest.main()
