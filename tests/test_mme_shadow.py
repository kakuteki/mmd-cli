"""tools/mme_shadow.py: the MME effect of the soft self shadow and the files round it."""
import contextlib
import hashlib
import importlib.util
import io
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
        text = mme_shadow.effect(blur=5.0, min_blur=0.07, n_taps=24, search_taps=12)
        self.assertAlmostEqual(define(text, "SS_BLUR_RAD"), math.radians(5.0), places=8)
        self.assertAlmostEqual(define(text, "SS_MIN_WORLD"), 0.07, places=6)
        self.assertAlmostEqual(define(text, "SS_SEARCH_WORLD"), mme_shadow.SEARCH, places=6)
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
        self.assertEqual(define(text, "SS_MIN_WORLD"), 0.0)
        n, rows = array(text, "KERNEL")
        self.assertEqual(rows, [(0.0, 0.0, 1.0)])
        # MMD's test: 1 - saturate(max(z - map, 0) * 1500 - 0.3) in mode 1, the slope 8000 x v in mode 2
        self.assertIn("#define SKII1 1500.0", text)
        self.assertIn("#define SKII2 8000.0", text)
        self.assertIn("slope - 0.3f", text)

    def test_the_shade_keeps_what_the_floor_keeps_in_a_shadow(self):
        # by default the shade keeps 1 - key_share of the light, the key light's share of tools/mv_world.py's floor
        text = mme_shadow.effect()
        self.assertEqual(define(text, "SS_ALIGN"), 1)
        self.assertAlmostEqual(define(text, "SS_KEEP"), 1.0 - mme_shadow.DEFAULTS["key_share"], places=6)
        self.assertAlmostEqual(define(mme_shadow.effect(key_share=0.3), "SS_KEEP"), 0.7, places=6)
        self.assertIn('"key_share": 0.6', text.splitlines()[2])
        # the toon's hue kept, its luma set (BT.709, as tools/shadow_check.py reads the floor); a white toon left white
        self.assertIn("float3(0.2126f, 0.7152f, 0.0722f)", text)
        self.assertIn("if (luma < 0.999f)", text)
        # MMD's toon colours as they are: with key_share None, and always in sharp (the check that the shading is MMD's)
        for toon in (mme_shadow.effect(key_share=None), mme_shadow.effect(sharp=True)):
            self.assertEqual(define(toon, "SS_ALIGN"), 0)
            self.assertIn('"key_share": null', toon.splitlines()[2])
        try:
            spec = importlib.util.spec_from_file_location("mv_world", os.path.join(ROOT, "tools", "mv_world.py"))
            mv_world = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mv_world)
        except ImportError:                    # mv_world needs numpy and Pillow
            return
        self.assertEqual(mme_shadow.DEFAULTS["key_share"], mv_world.KEY_SHARE)

    def test_debug_draws_the_shadow_alone_or_the_body_lit(self):
        self.assertEqual(define(mme_shadow.effect(debug="shadow"), "SS_DEBUG"), 1)
        lit = mme_shadow.effect(debug="lit")
        self.assertEqual(define(lit, "SS_DEBUG"), 2)
        self.assertIn('"debug": "lit"', lit.splitlines()[2])
        self.assertIn("#if SS_DEBUG == 2", lit)
        self.assertEqual(define(mme_shadow.effect(), "SS_DEBUG"), 0)

    def test_wrong_settings_are_refused(self):
        for bad in ({"blur": -1}, {"blur": 45}, {"min_blur": -0.1}, {"min_blur": 3}, {"n_taps": 0}, {"n_taps": 65},
                    {"search_taps": 0}, {"key_share": 1.0}, {"key_share": -0.1}, {"key_share": True},
                    {"debug": "dark"}):
            with self.assertRaises(ValueError, msg=bad):
                mme_shadow.effect(**bad)

    def test_the_command_line_takes_the_shade(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        for args, keep, align in (([], 0.4, 1), (["--key-share", "0.5"], 0.5, 1), (["--toon"], 1.0, 0),
                                  (["--debug", "lit"], 0.4, 1), (["--debug"], 0.4, 1)):
            path = os.path.join(out, "e.fx")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mme_shadow.main(["write", path] + args), 0, args)
            with open(path, encoding="ascii") as f:
                text = f.read()
            self.assertAlmostEqual(define(text, "SS_KEEP"), keep, places=6)
            self.assertEqual(define(text, "SS_ALIGN"), align)
        with open(path, encoding="ascii") as f:
            self.assertEqual(define(f.read(), "SS_DEBUG"), 1)                 # --debug alone: the shadow


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

    def test_prepare_takes_the_model_and_its_textures_again_when_they_changed(self):
        # review of softshadow-mme: the copy was made once and kept, so a model rebuilt since (a new rig, a new skirt)
        # would have been drawn as it was
        out = os.path.join(self.folder, "out")
        mme_shadow.prepare(self.model, out)
        with open(self.model, "wb") as f:
            f.write(b"PMX model bytes, rebuilt")
        with open(os.path.join(self.models, "tex", "skin.png"), "wb") as f:
            f.write(b"texture, painted again")
        got = mme_shadow.prepare(self.model, out)
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes, rebuilt")
        with open(os.path.join(out, "Rin", "tex", "skin.png"), "rb") as f:
            self.assertEqual(f.read(), b"texture, painted again")
        got = mme_shadow.prepare(self.model, out, variant="soft2")
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes, rebuilt")
        # what the tool wrote beside the copy stays (the effects), and a copy that did not change is not written again
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "White.fx")))
        copied = []
        real = mme_shadow.shutil.copy2
        self.addCleanup(setattr, mme_shadow.shutil, "copy2", real)
        mme_shadow.shutil.copy2 = lambda a, b, **kw: copied.append(os.path.normcase(os.path.abspath(a))) or real(a, b, **kw)
        mme_shadow.prepare(self.model, out)
        self.assertNotIn(os.path.normcase(os.path.join(self.models, "tex", "skin.png")), copied)
        self.assertNotIn(os.path.normcase(self.model), copied)

    def test_prepare_refuses_to_write_into_the_models_own_folder(self):
        with self.assertRaises(ValueError):
            mme_shadow.prepare(self.model, os.path.join(self.folder, "models"))
        with self.assertRaises(ValueError):                                # nor into a folder inside it
            mme_shadow.prepare(self.model, self.models)
        self.assertEqual(sorted(os.listdir(self.models)), ["White.pmx", "tex"])

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


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.mmd = os.path.join(self.folder, "mmd")
        os.makedirs(self.mmd)
        self.exe = os.path.join(self.mmd, "MikuMikuDance.exe")
        open(self.exe, "wb").close()
        self.models = os.path.join(self.folder, "models")
        os.makedirs(self.models)
        self.model = os.path.join(self.models, "White.pmx")
        open(self.model, "wb").close()

    def install(self):
        # MME's files as check knows them: their digests made to match
        for name in mme_shadow.MME_FILES:
            with open(os.path.join(self.mmd, name), "wb") as f:
                f.write(name.encode())
        self.addCleanup(setattr, mme_shadow, "MME_FILES", dict(mme_shadow.MME_FILES))
        mme_shadow.MME_FILES = {n: hashlib.sha256(n.encode()).hexdigest() for n in mme_shadow.MME_FILES}

    def test_the_effect_mme_applies_is_the_one_in_brackets_or_the_one_of_the_same_name(self):
        self.assertIsNone(mme_shadow.effect_of(self.model))
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        self.assertTrue(mme_shadow.effect_of(self.model).endswith("White.fx"))
        named = os.path.join(self.models, "White[soft.fx].pmx")
        open(named, "wb").close()
        self.assertIsNone(mme_shadow.effect_of(named))                   # soft.fx is not there yet
        mme_shadow.write(os.path.join(self.models, "soft.fx"))
        self.assertTrue(mme_shadow.effect_of(named).endswith("soft.fx"))

    def test_soft_needs_mme_and_an_effect_of_this_tool(self):
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # no MME
        self.install()
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # no effect
        with open(os.path.join(self.models, "White.fx"), "w") as f:
            f.write("// someone else's effect\n")
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # not ours
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        got = mme_shadow.verify(self.exe, self.model, "soft")
        self.assertEqual(got["self_shadow"], "soft")
        self.assertIn('"blur": 5.0', got["settings"])
        mme_shadow.write(os.path.join(self.models, "White.fx"), key_share=None)          # --toon: a soft shadow too
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "soft")["self_shadow"], "soft")

    def test_soft_refuses_the_effects_for_measuring(self):
        # review of softshadow-mme: --debug draws the shadow alone (black and white) or the body lit, --sharp MMD's own
        # test; a plan that says soft must not render either
        self.install()
        for settings in ({"debug": "shadow"}, {"debug": "lit"}, {"sharp": True}):
            mme_shadow.write(os.path.join(self.models, "White.fx"), **settings)
            with self.assertRaises(ValueError, msg=settings):
                mme_shadow.verify(self.exe, self.model, "soft")

    def test_mmd_refuses_a_model_mme_would_draw_with_an_effect(self):
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")      # no MME at all
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")      # MME is not there
        self.install()
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "mmd")
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "hard")

    def test_mmd_refuses_a_model_another_build_of_mme_would_draw_with_an_effect(self):
        # review of softshadow-mme: MME of another build (not the digests this tool knows) applies the effect all the same
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        with open(os.path.join(self.mmd, "MMEffect.dll"), "wb") as f:
            f.write(b"another build of MME")
        self.assertFalse(mme_shadow.check(self.exe)["installed"])
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "mmd")
        os.remove(os.path.join(self.models, "White.fx"))
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")   # no effect on the model


if __name__ == "__main__":
    unittest.main()
