"""tools/lip_check.py: the mouth of a face motion measured against the voice alone (the times come from the voice, not
from an alignment of the lyrics)."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import wave

import numpy as np

from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("lip_check", os.path.join(ROOT, "tools", "lip_check.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lip_check = load_tool()
SR = 16000
FPS = 30.0
VOWEL_MORPHS = ("あ", "い", "う", "え", "お")
# formants (Hz) of a high voice, set so that the two levels of lip_check part the vowels as on the separated voice of
# the MV: the first formant of あ え お above 700 Hz, of い う below it; the second of う above 1500 Hz
FORMANTS = {"a": (1000, 1400, 2900), "i": (300, 2800, 3400), "u": (330, 1700, 2700), "e": (900, 2300, 3100),
            "o": (850, 1100, 2800), "N": (260, 1150, 2650)}
F0 = 290.0
# a synthetic song: (start s, the morae as (consonant, vowel, vowel seconds)); a vowel without a consonant inside a
# line follows the vowel before it without a break (legato: no onset)
LINES = [
    (0.6, [("k", "a", 0.26), ("s", "i", 0.22), ("m", "o", 0.28), ("k", "e", 0.24), ("", "u", 0.30), ("s", "a", 0.22),
           ("k", "i", 0.30)]),
    (3.8, [("", "a", 0.24), ("k", "o", 0.22), ("s", "e", 0.26), ("m", "i", 0.24), ("k", "a", 0.24), ("s", "u", 0.22),
           ("m", "o", 0.30)]),
    (7.0, [("s", "u", 0.22), ("k", "a", 0.24), ("m", "e", 0.26), ("", "o", 0.30), ("k", "i", 0.28), ("s", "a", 0.24),
           ("k", "u", 0.28)]),
    (10.2, [("m", "a", 0.26), ("k", "u", 0.22), ("s", "o", 0.24), ("k", "i", 0.24), ("", "e", 0.40), ("m", "a", 0.24),
            ("s", "i", 0.30)]),
]
PITCH_JUMP = (3, 4)             # this mora's pitch rises by 3 semitones half way (no onset)
LENGTH = 13.4


def _sung(formants, n, f0, rng):
    t = np.arange(n) / SR
    out = np.zeros(n)
    vib = 1.0 + 0.01 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * np.cumsum(f0 * vib) / SR
    for k in range(1, int(7000 / f0)):
        f = k * f0
        amp = sum(w * F * F / np.sqrt((F * F - f * f) ** 2 + (90.0 * f) ** 2) for F, w in zip(formants, (1.0, 0.7, 0.35)))
        out += amp / k * np.sin(k * phase + rng.uniform(0, 2 * np.pi))
    return out / (np.sqrt(np.mean(out ** 2)) + 1e-12)


def _fade(x, ms=12):
    n = min(len(x) // 2, int(SR * ms / 1000))
    if n:
        w = 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)
        x[:n] *= w
        x[-n:] *= w[::-1]
    return x


def synth(seed=0):
    """the voice and the true morae [{line, mora, consonant, vowel, c0, v0, v1, word_start, held, kana}]"""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(LENGTH * SR))
    morae = []
    for li, (start, ms) in enumerate(LINES):
        t = start
        for mi, (c, v, dur) in enumerate(ms):
            c0 = t
            if c == "k":
                t += 0.05
                burst = rng.normal(0, 0.3, int(0.012 * SR))
                x[int(t * SR):int(t * SR) + len(burst)] += _fade(burst, 3)
                t += 0.015
            elif c == "s":
                hiss = np.diff(rng.normal(0, 0.25, int(0.09 * SR) + 1))
                x[int(t * SR):int(t * SR) + len(hiss)] += _fade(hiss, 10) * 0.5
                t += 0.09
            elif c == "m":
                hum = _sung(FORMANTS["N"], int(0.07 * SR), F0, rng) * 0.08
                x[int(t * SR):int(t * SR) + len(hum)] += _fade(hum, 10)
                t += 0.07
            v0 = t
            n = int(dur * SR)
            if (li, mi) == PITCH_JUMP:
                half = n // 2
                seg = np.concatenate([_sung(FORMANTS[v], half, F0, rng), _sung(FORMANTS[v], n - half, F0 * 2 ** 0.25, rng)])
            else:
                seg = _sung(FORMANTS[v], n, F0 + 15 * (mi % 3), rng)
            legato = not c and mi > 0
            x[int(t * SR):int(t * SR) + n] += _fade(seg * 0.3, 4 if legato else 15)
            t += dur
            morae.append({"line": li, "mora": mi, "kana": (c + v), "consonant": c, "vowel": v, "held": False,
                          "word_start": mi == 0, "c0": round(c0, 3), "v0": round(v0, 3), "v1": round(t, 3)})
    x += rng.normal(0, 1e-4, len(x))
    return x.astype(np.float32), morae


def onset_syllables(morae):
    """the true vowel starts that follow a consonant or a rest (where a voice onset is)"""
    return np.array([m["v0"] for m in morae if m["consonant"] or m["mora"] == 0])


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype("<i2").tobytes())


def face_leading(morae, lead):
    """a mouth that opens あ for every mora, half way `lead` s before its vowel starts (a ramp of 2 frames), shut before
    the next; and the time each opening crosses half way"""
    keys, halves = [], []
    starts = []
    for m in morae:
        fa = int(round((m["v0"] - lead) * FPS - lip_check.SHOWN)) - 1
        starts.append(fa)
        halves.append((fa + 1 + lip_check.SHOWN) / FPS)
    for k, (m, fa) in enumerate(zip(morae, starts)):
        same_line = k + 1 < len(morae) and morae[k + 1]["line"] == m["line"]
        fb = starts[k + 1] - 3 if same_line else fa + int(round((m["v1"] - m["v0"]) * FPS))
        keys += [vmd.MorphKey("あ", fa, 0.0), vmd.MorphKey("あ", fa + 2, 1.0), vmd.MorphKey("あ", fb, 1.0),
                 vmd.MorphKey("あ", fb + 2, 0.0)]
    keys += [vmd.MorphKey(n, 0, 0.0) for n in VOWEL_MORPHS[1:]]
    keys.append(vmd.MorphKey("まばたき", int(LENGTH * FPS), 0.0))
    return vmd.Motion(model_name="Rin", morphs=keys), np.array(halves)


class Parts(unittest.TestCase):
    def test_a_rise_is_a_swing_up_of_at_least_move(self):
        # the trough is the last of its lowest frames, the peak the first of its highest; a dip of less than 0.15
        # inside a rise does not end it
        o = np.array([0, 0, 0.5, 1, 1, 0.92, 1, 0.2, 0.25, 0.1, 0.9, 0.9, 0.0])
        self.assertEqual(lip_check.rises(o, 0.15), [(1, 3), (9, 10)])

    def test_a_rise_is_timed_where_it_crosses_half_way(self):
        o = np.array([0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 0.0])
        t = lip_check.rise_times(o, 0.15)
        self.assertAlmostEqual(t[0], (3 + lip_check.SHOWN) / FPS, places=6)

    def test_onsets_and_rises_pair_one_to_one_nearest_first(self):
        pairs = lip_check.pair(np.array([1.0, 1.1, 3.0]), np.array([1.05, 2.0]), match=0.2)
        self.assertEqual(len(pairs), 1)
        self.assertIn(pairs[0], [(0, 0), (1, 0)])

    def test_otsu_parts_two_groups(self):
        t = lip_check.otsu([-20, -19, -18, -17, 5, 6, 8])
        self.assertTrue(-17 < t < 5)


class SyntheticTest(unittest.TestCase):
    """a synthetic song of 4 lines with known times, measured with mouths of known leads"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.x, cls.morae = synth()
        cls.voice_path = os.path.join(cls.folder, "voice.wav")
        write_wav(cls.voice_path, cls.x)
        cls.voice = lip_check.Voice(cls.x)
        cls.onsets = lip_check.voice_onsets(cls.voice)
        cls.truth = onset_syllables(cls.morae)
        cls.faces = {}
        for tag, lead in (("lead40", 0.04), ("late80", -0.08)):
            motion, halves = face_leading(cls.morae, lead)
            path = os.path.join(cls.folder, tag + ".vmd")
            vmd.dump(motion, path)
            cls.faces[tag] = (path, halves)
        still = vmd.Motion(model_name="Rin", morphs=[vmd.MorphKey("あ", 0, 0.5), vmd.MorphKey("あ", 400, 0.5)])
        cls.still = os.path.join(cls.folder, "still.vmd")
        vmd.dump(still, cls.still)
        cls.align = os.path.join(cls.folder, "align.json")
        with open(cls.align, "w", encoding="utf-8") as f:
            json.dump(cls.morae, f)
        cls.report_path = os.path.join(cls.folder, "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_check.main([cls.voice_path, cls.faces["lead40"][0], cls.faces["late80"][0], cls.still,
                                       "--align", cls.align, "--report", cls.report_path])
        with open(cls.report_path, encoding="ascii") as f:
            cls.report = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def check(self, *extra):
        r = os.path.join(self.folder, "r_%d.json" % len(extra))
        with contextlib.redirect_stdout(io.StringIO()):
            code = lip_check.main([self.voice_path, self.faces["lead40"][0], "--report", r] + list(extra))
        self.assertEqual(code, 0)
        with open(r, encoding="ascii") as f:
            return json.load(f)

    def check_faces(self, motion):
        path = os.path.join(self.folder, "extra.vmd")
        vmd.dump(motion, path)
        r = os.path.join(self.folder, "r_extra.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lip_check.main([self.voice_path, path, "--report", r]), 0)
        with open(r, encoding="ascii") as f:
            return json.load(f)["faces"]["extra"]

    def test_it_runs(self):
        self.assertEqual(self.code, 0)
        self.assertEqual(sorted(self.report["faces"]), ["late80", "lead40", "still"])

    def test_an_onset_is_found_where_a_syllable_starts_after_a_consonant_or_a_rest(self):
        err = np.array([self.onsets[np.argmin(np.abs(self.onsets - t))] - t for t in self.truth])
        self.assertGreaterEqual(float(np.mean(np.abs(err) <= 0.03)), 0.9, err)
        self.assertLessEqual(abs(float(np.median(err))), 0.015, err)

    def test_no_onset_inside_a_vowel_or_at_a_legato_syllable(self):
        # every onset is a syllable start: not the pitch jump, not the legato vowels
        near = np.array([np.min(np.abs(self.truth - t)) for t in self.onsets])
        self.assertTrue(np.all(near <= 0.04), (self.onsets, near))
        legato = [m["v0"] for m in self.morae if not m["consonant"] and m["mora"] > 0]
        jump = [m for m in self.morae if (m["line"], m["mora"]) == PITCH_JUMP][0]
        for t in legato + [0.5 * (jump["v0"] + jump["v1"])]:
            self.assertGreater(np.min(np.abs(self.onsets - t)), 0.04, t)

    def test_the_lag_is_the_mouths_lead_where_it_opens(self):
        face = self.report["faces"]["lead40"]
        self.assertGreaterEqual(face["share_onsets_paired"], 0.9)
        _, halves = self.faces["lead40"]
        expected = np.array([t - halves[np.argmin(np.abs(np.array([m["v0"] for m in self.morae]) - t))]
                             for t in self.truth]) * 1000.0
        self.assertLessEqual(abs(face["lag_ms"]["median"] - float(np.median(expected))), 12.0, (face, expected))
        self.assertEqual(face["share_mouth_late_over_45ms"], 0.0)

    def test_a_late_mouth_is_late(self):
        face = self.report["faces"]["late80"]
        self.assertTrue(-95.0 <= face["lag_ms"]["median"] <= -65.0, face)
        self.assertGreaterEqual(face["share_mouth_late_over_45ms"], 0.9)

    def test_the_cross_correlation_and_the_triggered_average_have_the_leads_sign(self):
        lead, late = self.report["faces"]["lead40"], self.report["faces"]["late80"]
        self.assertTrue(10 <= lead["xcorr_speed_flux"]["lag_ms"] <= 90, lead["xcorr_speed_flux"])
        self.assertTrue(-130 <= late["xcorr_speed_flux"]["lag_ms"] <= -30, late["xcorr_speed_flux"])
        self.assertTrue(10.0 <= lead["triggered"]["half_before_onset_ms"] <= 80.0, lead["triggered"])
        self.assertTrue(-130.0 <= late["triggered"]["half_before_onset_ms"] <= -30.0, late["triggered"])

    def test_an_onset_knows_whether_its_vowel_sounds_open(self):
        opens = lip_check.onset_open(self.voice, self.onsets)
        truth = {round(m["v0"], 2): m["vowel"] in "aeo" for m in self.morae if m["consonant"] or m["mora"] == 0}
        hits = []
        for t, v in zip(self.onsets, opens):
            near = min(truth, key=lambda u: abs(u - t))
            if abs(near - t) <= 0.03 and v is not None:
                hits.append(v == truth[near])
        self.assertGreaterEqual(len(hits), 20)
        self.assertGreaterEqual(float(np.mean(hits)), 0.85, hits)

    def test_the_open_vowel_onsets_give_the_same_lead(self):
        face = self.report["faces"]["lead40"]["open_vowel_onsets"]
        self.assertGreaterEqual(face["share_paired"], 0.9)
        self.assertLessEqual(abs(face["lag_ms"]["median"] - self.report["faces"]["lead40"]["lag_ms"]["median"]), 15.0)

    def test_the_states_find_a_mouth_shut_on_the_singing_and_open_in_the_silence(self):
        good = self.report["faces"]["lead40"]["states"]
        self.assertLessEqual(good["shut_while_singing"]["share"], 0.15, good)
        self.assertEqual(good["open_in_silence"]["share"], 0.0, good)
        # the still mouth is half open throughout: open in the silences, never shut
        still = self.report["faces"]["still"]["states"]
        self.assertGreaterEqual(still["open_in_silence"]["share"], 0.95, still)
        self.assertEqual(still["shut_while_singing"]["share"], 0.0, still)
        shut = self.check_faces(vmd.Motion(model_name="Rin", morphs=[vmd.MorphKey("あ", 0, 0.0)]))["states"]
        self.assertGreaterEqual(shut["shut_while_singing"]["share"], 0.95, shut)
        self.assertTrue(shut["shut_while_singing"]["longest_s"])

    def test_a_snap_of_the_mouth_is_a_jump(self):
        o = np.array([0.0, 0.1, 0.2, 0.9, 0.9, 0.5, 0.0])
        j = lip_check.jumps(o, 0.4)
        self.assertEqual(j["frames_over"], 2)
        self.assertEqual(j["top"][0], [3, 0.7])
        # the test mouths open over 2 frames (0.5 a frame): every opening is a snap
        self.assertGreaterEqual(self.report["faces"]["lead40"]["jumps"]["frames_over"], len(self.morae))

    def test_a_mouth_that_never_moves_pairs_nothing(self):
        still = self.report["faces"]["still"]
        self.assertEqual(still["paired"], 0)
        self.assertIsNone(still["lag_ms"])
        self.assertIsNone(still["xcorr_speed_flux"])

    def test_the_mouths_numbers_do_not_read_the_alignment(self):
        wrong = os.path.join(self.folder, "wrong.json")
        with open(wrong, "w", encoding="utf-8") as f:
            json.dump([dict(m, c0=m["c0"] + 0.15, v0=m["v0"] + 0.15, v1=m["v1"] + 0.15) for m in self.morae], f)
        a = self.check("--align", self.align)["faces"]["lead40"]
        b = self.check("--align", wrong)["faces"]["lead40"]
        self.assertEqual(a, b)

    def test_the_alignments_starts_are_checked_against_the_flux(self):
        good = self.report["alignment"]["onsets"]
        self.assertGreaterEqual(good["share_within_30ms"], 0.9)
        self.assertLess(good["chance_within_30ms"], good["share_within_30ms"] - 0.3)
        late = os.path.join(self.folder, "late.json")
        with open(late, "w", encoding="utf-8") as f:
            json.dump([dict(m, v0=m["v0"] + 0.1) for m in self.morae], f)
        bad = self.check("--align", late)["alignment"]["onsets"]
        self.assertLessEqual(bad["share_within_30ms"], 0.5)

    def test_a_vowel_stretched_over_the_next_syllable_has_an_onset_inside(self):
        self.assertEqual(self.report["alignment"]["onsets"]["vowels_with_an_onset_inside"], 0)
        merged = []
        for k, m in enumerate(self.morae):
            m = dict(m)
            if (m["line"], m["mora"]) == (2, 0):           # す takes the span of か after it; か is squeezed to its end
                m["v1"] = self.morae[k + 1]["v1"] - 0.05
            if (m["line"], m["mora"]) == (2, 1):
                m["c0"], m["v0"] = self.morae[k]["v1"] - 0.05, self.morae[k]["v1"] - 0.05
            merged.append(m)
        path = os.path.join(self.folder, "merged.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f)
        got = self.check("--align", path)["alignment"]["onsets"]
        self.assertEqual(got["vowels_with_an_onset_inside"], 1, got["onset_inside"])
        self.assertEqual((got["onset_inside"][0]["line"], got["onset_inside"][0]["mora"]), (2, 0))

    def test_the_vowels_sound_as_labelled(self):
        v = self.report["alignment"]["vowels"]
        self.assertGreaterEqual(v["share_agree_close_open"], 0.85, v)
        self.assertEqual(v["lines_fit_better_shifted"], [])

    def test_a_line_labelled_a_mora_off_fits_better_shifted(self):
        off = []
        for m in self.morae:
            m = dict(m)
            if m["line"] == 1:
                seq = [x for x in self.morae if x["line"] == 1]
                if m["mora"] + 1 < len(seq):
                    m["vowel"] = seq[m["mora"] + 1]["vowel"]
            off.append(m)
        path = os.path.join(self.folder, "off.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(off, f)
        v = self.check("--align", path)["alignment"]["vowels"]
        self.assertIn(1, v["lines_fit_better_shifted"])

    def test_the_lines_and_regions_give_the_lags_inside_them(self):
        lines = os.path.join(self.folder, "lines.tsv")
        with open(lines, "w", encoding="utf-8") as f:
            for li, (start, ms) in enumerate(LINES):
                end = max(m["v1"] for m in self.morae if m["line"] == li)
                f.write("%.2f\t%.2f\tline\n" % (start - 0.2, end + 0.2))
        r = self.check("--lines", lines, "--region", "0", "3.6")
        self.assertEqual(len(r["lines"]), 4)
        self.assertTrue(all(row["lead40"]["paired"] >= 3 for row in r["lines"]), r["lines"])
        self.assertEqual(r["regions"][0]["lead40"]["paired"], r["lines"][0]["lead40"]["paired"])

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "needs Pillow")
    def test_the_sheet_and_a_view_are_drawn(self):
        prefix = os.path.join(self.folder, "sheet")
        view = os.path.join(self.folder, "view.png")
        r = self.check("--align", self.align, "--sheet", prefix, "--sample", "10", "--seed", "3",
                       "--view", "0.4", "3.4", view)
        self.assertEqual(r["sheet"]["tiles"], 10)
        self.assertEqual(len(r["sheet"]["pages"]), 2)
        for path in r["sheet"]["pages"] + [view]:
            self.assertTrue(os.path.isfile(path), path)
        with open(prefix + ".json", encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 10)


class CliTest(unittest.TestCase):
    def test_a_missing_file_is_an_argument_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lip_check.main(["no.wav", "no.vmd"]), 2)

    def test_a_sheet_needs_the_alignment(self):
        folder = tempfile.mkdtemp()
        try:
            voice = os.path.join(folder, "v.wav")
            write_wav(voice, np.zeros(SR, np.float32))
            face = os.path.join(folder, "f.vmd")
            vmd.dump(vmd.Motion(model_name="Rin", morphs=[vmd.MorphKey("あ", 0, 0.0)]), face)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lip_check.main([voice, face, "--sheet", os.path.join(folder, "s")]), 2)
                self.assertEqual(lip_check.main([voice, face, "--view", "1", "0.5", os.path.join(folder, "v.png")]), 2)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
