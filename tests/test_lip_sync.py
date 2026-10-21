"""tools/lip_sync.py: the mouth of a face motion shaped from the singing voice and the lyrics."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("lip_sync", os.path.join(ROOT, "tools", "lip_sync.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lip_sync = load_tool()
SR = 16000
FPS = 30.0
VOWEL_MORPHS = ("あ", "い", "う", "え", "お")
# formants (Hz) of a high voice
FORMANTS = {"a": (850, 1250, 2850), "i": (320, 2750, 3350), "u": (360, 1450, 2650), "e": (540, 2250, 2950),
            "o": (520, 880, 2800), "N": (260, 1150, 2650)}


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


# a synthetic song: (start s, the morae as (consonant, vowel, vowel seconds), level dB), each a line
SONG = [
    (0.8, [("k", "a", 0.24), ("", "i", 0.22), ("s", "a", 0.26), ("m", "a", 0.30), ("", "o", 0.40)], 0.0),
    (3.4, [("m", "e", 0.22), ("k", "u", 0.24), ("s", "a", 0.22), ("k", "i", 0.26), ("", "o", 0.22), ("", "u", 0.34)], 0.0),
    (6.2, [("", "a", 0.26), ("k", "i", 0.22), ("m", "a", 0.24), ("", "e", 0.26), ("s", "o", 0.22), ("k", "o", 0.40)], 0.0),
    (9.0, [("k", "a", 0.24), ("", "i", 0.22), ("s", "a", 0.26), ("m", "a", 0.30), ("", "o", 0.40)], -16.0),
    (11.6, [("m", "e", 0.22), ("k", "u", 0.24), ("s", "a", 0.22), ("k", "i", 0.26), ("", "o", 0.22), ("", "u", 0.34)], 0.0),
    (14.4, [("", "a", 0.26), ("k", "i", 0.22), ("m", "a", 0.24), ("", "e", 0.26), ("s", "o", 0.22), ("k", "o", 0.40)], 0.0),
]
KANA = {("k", "a"): "か", ("", "i"): "い", ("s", "a"): "さ", ("m", "a"): "ま", ("", "o"): "お", ("m", "e"): "め",
        ("k", "u"): "く", ("k", "i"): "き", ("", "u"): "う", ("", "a"): "あ", ("", "e"): "え", ("s", "o"): "そ",
        ("k", "o"): "こ"}
AD_LIB = (17.6, "a", 0.5)       # a vowel sung outside the lines (an ad lib), loud
LENGTH = 19.0


def synth_song(seed=0):
    """the voice, the true times [(line, mora, consonant, vowel, c0, v0, v1)] and the lines file's rows"""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(LENGTH * SR))
    truth, rows = [], []
    for li, (start, morae, db) in enumerate(SONG):
        t = start
        first = None
        for mi, (c, v, dur) in enumerate(morae):
            c0 = t
            if c == "k":
                t += 0.05
                burst = rng.normal(0, 0.3, int(0.012 * SR))
                x[int(t * SR):int(t * SR) + len(burst)] += _fade(burst, 3) * 10 ** (db / 20)
                t += 0.015
            elif c == "s":
                hiss = np.diff(rng.normal(0, 0.25, int(0.09 * SR) + 1))
                x[int(t * SR):int(t * SR) + len(hiss)] += _fade(hiss, 10) * 10 ** ((db - 6) / 20)
                t += 0.09
            elif c == "m":
                hum = _sung(FORMANTS["N"], int(0.07 * SR), 260.0, rng) * 0.08
                x[int(t * SR):int(t * SR) + len(hum)] += _fade(hum, 10) * 10 ** (db / 20)
                t += 0.07
            v0 = t
            seg = _sung(FORMANTS[v], int(dur * SR), 260.0 + 20 * (mi % 3), rng) * 0.3 * 10 ** (db / 20)
            x[int(t * SR):int(t * SR) + len(seg)] += _fade(seg, 15)
            t += dur
            truth.append((li, mi, c, v, c0, v0, t))
            first = c0 if first is None else first
        rows.append((first - 0.25, t + 0.2, "".join(KANA[(c, v)] for c, v, _ in morae)))
    a0, v, dur = AD_LIB
    seg = _sung(FORMANTS[v], int(dur * SR), 280.0, rng) * 0.3
    x[int(a0 * SR):int(a0 * SR) + len(seg)] += _fade(seg, 20)
    x += rng.normal(0, 1e-4, len(x))
    return x.astype(np.float32), truth, rows


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype("<i2").tobytes())


def write_lines(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# start\tend\tline\n")
        for a, b, text in rows:
            f.write("%.3f\t%.3f\t%s\n" % (a, b, text))


def face_motion(frames):
    """a face like KAZUSA's: a blink, a smile and its mouth corner, the vowels open at times of their own (one where the
    voice is silent, one on the ad lib)"""
    m = []
    for f in (20, 200, 400):
        m += [vmd.MorphKey("まばたき", f, 0.0), vmd.MorphKey("まばたき", f + 2, 1.0), vmd.MorphKey("まばたき", f + 5, 0.0)]
    m += [vmd.MorphKey("笑い", 100, 0.0), vmd.MorphKey("笑い", 110, 0.6), vmd.MorphKey("口角上げ", 110, 0.36)]
    m += [vmd.MorphKey("あ", 0, 0.0), vmd.MorphKey("あ", 520, 0.0), vmd.MorphKey("あ", 525, 1.0), vmd.MorphKey("あ", 535, 1.0),
          vmd.MorphKey("あ", 540, 0.0)]                                 # 17.3 to 18.0 s: on the ad lib
    m += [vmd.MorphKey("お", 0, 0.0), vmd.MorphKey("お", 250, 0.0), vmd.MorphKey("お", 253, 1.0), vmd.MorphKey("お", 262, 0.0)]
    m += [vmd.MorphKey("い", 0, 0.0), vmd.MorphKey("う", 0, 0.0), vmd.MorphKey("え", 0, 0.0)]
    m += [vmd.MorphKey("まばたき", frames - 1, 0.0)]
    return vmd.Motion(model_name="Rin", morphs=m)


def tracks(motion, frames):
    keys = {}
    for k in motion.morphs:
        keys.setdefault(k.name, {})[k.frame] = k.weight
    out = {}
    for name, d in keys.items():
        fs = sorted(d)
        out[name] = np.interp(np.arange(frames), fs, [d[f] for f in fs])
    return out


def opening(tr, frames):
    """the visible opening: あ 1, い 0.02, う 0.28, え 0.63, お 0.68 (the measured areas on Sour's Rin)"""
    area = {"あ": 1.0, "い": 0.02, "う": 0.28, "え": 0.63, "お": 0.68}
    return sum(tr.get(n, np.zeros(frames)) * a for n, a in area.items())


def frame_at(t, lead_ms=lip_sync.LEAD_MS):
    """the frame that shows the mouth of voice time t (the frame of time t - lead)"""
    return (t - lead_ms / 1000.0) * FPS - lip_sync.SHOWN


class LyricsTest(unittest.TestCase):
    def parse(self, line):
        return [(m.consonant, m.vowel) for m in lip_sync.parse_line(line)]

    def test_a_kana_is_a_consonant_and_a_vowel(self):
        self.assertEqual(self.parse("かんかく"), [("k", "a"), ("", "N"), ("k", "a"), ("k", "u")])
        self.assertEqual(self.parse("まばたき"), [("m", "a"), ("m", "a"), ("s", "a"), ("k", "i")])

    def test_a_small_kana_changes_the_vowel_before(self):
        self.assertEqual(self.parse("ちゃんと"), [("s", "a"), ("", "N"), ("s", "o")])
        self.assertEqual(self.parse("きょうわ"), [("k", "o"), ("", "u"), ("w", "a")])
        self.assertEqual(self.parse("ヴァーチャル"), [("v", "a"), ("", "a"), ("s", "a"), ("r", "u")])

    def test_small_tsu_and_n_are_their_own_morae(self):
        self.assertEqual(self.parse("いっぱい"), [("", "i"), ("", "Q"), ("m", "a"), ("", "i")])

    def test_a_space_starts_a_word(self):
        morae = lip_sync.parse_line("あい うえ")
        self.assertEqual([m.word_start for m in morae], [True, False, True, False])

    def test_the_prolonged_mark_holds_the_vowel_before(self):
        morae = lip_sync.parse_line("ロー")
        self.assertEqual([(m.vowel, m.held) for m in morae], [("o", False), ("o", True)])

    def test_a_kanji_is_an_error(self):
        with self.assertRaises(ValueError):
            lip_sync.parse_line("真夜中")

    def test_brackets_and_commas_are_word_breaks(self):
        self.assertEqual(self.parse("「いま」、あい"), [("", "i"), ("m", "a"), ("", "a"), ("", "i")])


class SyntheticSongTest(unittest.TestCase):
    """the whole tool on a synthetic song: 6 lines of morae with known times, one sung 16 dB softer, and an ad lib"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.x, cls.truth, rows = synth_song()
        cls.voice = os.path.join(cls.folder, "voice.wav")
        write_wav(cls.voice, cls.x)
        cls.lines = os.path.join(cls.folder, "lines.tsv")
        write_lines(cls.lines, rows)
        cls.frames = int(LENGTH * FPS)
        cls.face = face_motion(cls.frames)
        cls.face_path = os.path.join(cls.folder, "face.vmd")
        vmd.dump(cls.face, cls.face_path)
        cls.out = os.path.join(cls.folder, "out.vmd")
        cls.report_path = os.path.join(cls.folder, "r.json")
        cls.align_path = os.path.join(cls.folder, "a.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_sync.main([cls.face_path, cls.voice, cls.out, "--lines", cls.lines, "--report", cls.report_path,
                                      "--align-out", cls.align_path])
        with open(cls.report_path, encoding="ascii") as f:
            cls.report = json.load(f)
        with open(cls.align_path, encoding="utf-8") as f:
            cls.aligned = json.load(f)
        cls.motion = vmd.load(cls.out)
        cls.tr = tracks(cls.motion, cls.frames)
        cls.open = opening(cls.tr, cls.frames)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_it_runs(self):
        self.assertEqual(self.code, 0)
        self.assertEqual(self.report["lines"], 6)
        self.assertEqual(self.report["morae"], len(self.truth))

    def test_the_vowels_are_found_where_they_are_sung(self):
        found = {(m["line"], m["mora"]): m for m in self.aligned}
        errors = [abs(found[(li, mi)]["v0"] - v0) for li, mi, c, v, c0, v0, v1 in self.truth]
        self.assertLessEqual(np.median(errors), 0.02)
        self.assertGreaterEqual(np.mean(np.array(errors) <= 0.04), 0.9, errors)

    def test_the_vowels_learn_their_sound(self):
        self.assertEqual(self.report["model_classes"], ["a", "e", "i", "o", "u"])

    def test_the_lips_shut_before_m(self):
        for li, mi, c, v, c0, v0, v1 in self.truth:
            if c != "m":
                continue
            a, b = frame_at(c0), frame_at(v0)
            span = self.open[int(np.floor(a)):int(np.ceil(b)) + 1]
            self.assertLessEqual(span.min(), 0.05, (li, mi))

    def test_the_mouth_is_open_on_a_and_leads_the_voice(self):
        lead = []
        for li, mi, c, v, c0, v0, v1 in self.truth:
            if v != "a" or c not in ("m", "k") or SONG[li][2] < 0:
                continue
            top = self.open[int(frame_at(v0)):int(frame_at(v1))].max()
            self.assertGreater(top, 0.85, (li, mi))
            f0, f1 = int(np.floor(frame_at(c0))), int(np.ceil(frame_at(v0)))
            low = f0 + int(np.argmin(self.open[f0:f1 + 1]))           # the consonant: the lips shut or the jaw up
            parts = low + int(np.argmax(self.open[low:] > self.open[low] + 0.1))   # the mouth starts to open
            reach = low + int(np.argmax(self.open[low:] >= 0.5 * top))  # half open
            lead.append(((v0 - (parts + lip_sync.SHOWN) / FPS) * 1000.0, (v0 - (reach + lip_sync.SHOWN) / FPS) * 1000.0))
        self.assertGreaterEqual(len(lead), 4)
        self.assertGreaterEqual(min(p for p, _ in lead), 0.0, lead)         # it starts to open before the voice
        self.assertTrue(all(-40.0 <= h <= 120.0 for _, h in lead), lead)   # and is half open within 40 ms after it

    def test_a_soft_line_opens_less_than_a_loud_one(self):
        def top(li):
            out = []
            for l2, mi, c, v, c0, v0, v1 in self.truth:
                if l2 == li and v == "a":
                    out.append(self.open[int(frame_at(v0)):int(frame_at(v1))].max())
            return np.mean(out)
        self.assertLess(top(3), 0.75 * top(0))

    def test_i_shows_an_open_mouth(self):
        for li, mi, c, v, c0, v0, v1 in self.truth:
            if v == "i" and SONG[li][2] == 0.0:
                mid = int(frame_at((v0 + v1) / 2))
                self.assertGreater(self.tr["い"][mid], 0.6)
                self.assertGreater(self.tr["あ"][mid], 0.1)

    def test_u_is_u_alone(self):
        # う alone shows a gap of 0.49 of あ's height (1.2 to 2.6 pixels on the MV's pictures); with お 0.2 it stood taller
        # than お itself (tools/mouth_shape.py, v11 face review)
        for li, mi, c, v, c0, v0, v1 in self.truth:
            if v == "u" and SONG[li][2] == 0.0:
                mid = int(frame_at((v0 + v1) / 2))
                self.assertGreater(self.tr["う"][mid], 0.6)
                self.assertLess(self.tr["お"][mid], 0.02)

    def test_the_mouth_is_shut_in_the_rests(self):
        sung = [(c0, v1) for li, mi, c, v, c0, v0, v1 in self.truth]
        lines = [(SONG[li][0], max(v1 for l2, _, _, _, _, _, v1 in self.truth if l2 == li)) for li in range(len(SONG))]
        quiet = []
        for f in range(self.frames):
            t = (f + lip_sync.SHOWN) / FPS + lip_sync.LEAD_MS / 1000.0
            near_line = any(a - 0.6 <= t <= b + 0.35 for a, b in lines)
            near_adlib = AD_LIB[0] - 0.35 <= t <= AD_LIB[0] + AD_LIB[2] + 0.35
            if not near_line and not near_adlib:
                quiet.append(f)
        self.assertTrue(quiet)
        self.assertLessEqual(max(self.open[f] for f in quiet), lip_sync.REST_OPEN + 1e-6)
        self.assertFalse(sung is None)

    def test_the_face_opening_on_a_silence_is_taken_down(self):
        # FACE opens お fully around frame 253 (8.4 s), where the voice is silent between lines
        self.assertLessEqual(self.tr["お"][253], lip_sync.REST_OPEN + 1e-6)

    def test_an_ad_lib_outside_the_lines_opens_the_mouth_where_the_face_does(self):
        mid = int(frame_at(AD_LIB[0] + AD_LIB[2] / 2))
        self.assertGreater(self.open[mid], 0.6)

    def test_the_mouth_breathes_in_before_a_phrase_after_a_rest(self):
        start = SONG[2][0]                                      # a vowel-only line: no closure before it
        f0, f1 = int(frame_at(start - 0.40)), int(frame_at(start - 0.12))
        self.assertGreater(self.tr["あ"][f0:f1 + 1].max(), 0.1)
        self.assertLessEqual(self.tr["あ"][f0:f1 + 1].max(), lip_sync.INHALE + 1e-6)

    def test_nothing_but_the_vowels_changes(self):
        def others(m):
            return sorted((k.name, k.frame, k.weight) for k in m.morphs if k.name not in VOWEL_MORPHS)
        face = vmd.load(self.face_path)
        self.assertEqual(others(self.motion), others(face))
        self.assertEqual(self.motion.bones, face.bones)
        self.assertEqual(self.motion.model_name, face.model_name)

    def test_the_vowels_never_jump(self):
        for name in VOWEL_MORPHS:
            self.assertLessEqual(np.abs(np.diff(self.tr[name])).max(), 0.6, name)

    def test_the_same_input_gives_the_same_bytes(self):
        out2 = os.path.join(self.folder, "out2.vmd")
        with contextlib.redirect_stdout(io.StringIO()):
            lip_sync.main([self.face_path, self.voice, out2, "--lines", self.lines])
        with open(self.out, "rb") as a, open(out2, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_max_keys_bounds_the_vowel_keys(self):
        out3 = os.path.join(self.folder, "out3.vmd")
        r3 = os.path.join(self.folder, "r3.json")
        full = self.report["keys"]["after_total"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = lip_sync.main([self.face_path, self.voice, out3, "--lines", self.lines, "--max-keys", str(full // 2),
                                  "--report", r3])
        self.assertEqual(code, 0)
        n = sum(1 for k in vmd.load(out3).morphs if k.name in VOWEL_MORPHS)
        self.assertLessEqual(n, full // 2)

    def test_the_dance_keys_are_shadowed(self):
        dance = vmd.Motion(model_name="Rin", morphs=[vmd.MorphKey("あ", 0, 0.0), vmd.MorphKey("い", 77, 0.5)])
        dpath = os.path.join(self.folder, "dance.vmd")
        vmd.dump(dance, dpath)
        out4 = os.path.join(self.folder, "out4.vmd")
        with contextlib.redirect_stdout(io.StringIO()):
            lip_sync.main([self.face_path, self.voice, out4, "--lines", self.lines, "--dance", dpath])
        frames = {(k.name, k.frame) for k in vmd.load(out4).morphs}
        for name in VOWEL_MORPHS:
            self.assertIn((name, 0), frames)
            self.assertIn((name, 77), frames)

    def test_the_report_gives_the_face_lead(self):
        self.assertIn("face_lead_ms", self.report)
        self.assertEqual(len(self.report["line_fit"]), 6)


class GuideTest(unittest.TestCase):
    """a sung sound just before a line that is no lyric (an ad lib, the echo of the intro): the voice alone may take it
    for the line's first syllable; FACE's own vowels (keyed by hand to the song) tell which is which"""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(3)
        cls.folder = tempfile.mkdtemp()
        x = np.zeros(int(6.0 * SR))
        extra = _sung(FORMANTS["a"], int(0.16 * SR), 300.0, rng) * 0.3 * 10 ** (-10 / 20)
        x[int(1.0 * SR):int(1.0 * SR) + len(extra)] += _fade(extra, 15)
        t = 1.45
        cls.truth = []
        for c, v, dur in [("k", "a", 0.22), ("s", "o", 0.2), ("", "i", 0.22), ("k", "u", 0.24), ("s", "e", 0.3)]:
            c0 = t
            if c == "k":
                t += 0.065
            elif c == "s":
                hiss = np.diff(rng.normal(0, 0.25, int(0.09 * SR) + 1))
                x[int(t * SR):int(t * SR) + len(hiss)] += _fade(hiss, 10) * 0.5
                t += 0.09
            seg = _sung(FORMANTS[v], int(dur * SR), 260.0, rng) * 0.3
            x[int(t * SR):int(t * SR) + len(seg)] += _fade(seg, 15)
            cls.truth.append((c, v, c0, t))
            t += dur
        x += rng.normal(0, 1e-4, len(x))
        cls.voice = os.path.join(cls.folder, "v.wav")
        write_wav(cls.voice, x.astype(np.float32))
        cls.lines = os.path.join(cls.folder, "l.tsv")
        write_lines(cls.lines, [(1.3, 2.9, "かそいくせ")])
        names = {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}
        morphs = [vmd.MorphKey(n, 0, 0.0) for n in VOWEL_MORPHS]
        for c, v, c0, v0 in cls.truth:                      # the hand-keyed mouth: open 2 frames before each vowel
            f = int(round((v0 - 0.07) * FPS))
            morphs += [vmd.MorphKey(names[v], f - 2, 0.0), vmd.MorphKey(names[v], f, 1.0), vmd.MorphKey(names[v], f + 5, 1.0),
                       vmd.MorphKey(names[v], f + 6, 0.0)]
        morphs.append(vmd.MorphKey("まばたき", 179, 0.0))
        cls.face = os.path.join(cls.folder, "f.vmd")
        vmd.dump(vmd.Motion(model_name="Rin", morphs=morphs), cls.face)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def aligned(self, *extra):
        a = os.path.join(self.folder, "a.json")
        r = os.path.join(self.folder, "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            code = lip_sync.main([self.face, self.voice, os.path.join(self.folder, "o.vmd"), "--lines", self.lines,
                                  "--align-out", a, "--report", r] + list(extra))
        self.assertEqual(code, 0)
        with open(r, encoding="ascii") as f:
            report = json.load(f)
        with open(a, encoding="utf-8") as f:
            return json.load(f), report

    def test_the_guide_keeps_every_syllable_on_its_own_sound(self):
        morae, report = self.aligned()
        self.assertTrue(report["guide"])
        for m, (c, v, c0, v0) in zip(morae, self.truth):
            self.assertAlmostEqual(m["v0"], v0, delta=0.04, msg=m["kana"])
            self.assertGreater(m["v1"] - m["v0"], 0.12, m["kana"])

    def test_without_the_guide_the_report_says_so(self):
        morae, report = self.aligned("--no-guide")
        self.assertFalse(report["guide"])
        self.assertEqual(len(morae), 5)


class HiatusTest(unittest.TestCase):
    """a syllable that is a vowel alone after another syllable (と お), sung after a short break that is soft but not
    silent (the voice falls 15 to 20 dB, as at 85.3 s of the MV): before 2026-10-17 the alignment had no unit for that
    break but the next syllable's consonant, squeezed と and お into the first note (50 and 60 ms) and spread the next
    と over two notes (review lipsync 5, 85.2 to 85.9 s)"""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7)
        cls.folder = tempfile.mkdtemp()
        x = np.zeros(int(4.0 * SR))
        t = 1.0
        cls.truth = []

        def vowel(v, dur, db=0.0, f0=260.0):
            seg = _sung(FORMANTS[v], int(dur * SR), f0, rng) * 0.3 * 10 ** (db / 20)
            x[int(t * SR):int(t * SR) + len(seg)] += _fade(seg, 15)

        def closure(dur):
            # the tongue's stop: a near silence, then a short burst
            n = int(0.012 * SR)
            burst = rng.normal(0, 0.3, n)
            x[int((t + dur - 0.015) * SR):int((t + dur - 0.015) * SR) + n] += _fade(burst, 3)
        # き
        c0 = t
        t += 0.065
        vowel("i", 0.24)
        cls.truth.append(("k", "i", c0, t))
        t += 0.24
        # ど: a closure, a short note (the lines here are made up, not the MV's)
        c0 = t
        closure(0.08)
        t += 0.08
        vowel("o", 0.12)
        cls.truth.append(("s", "o", c0, t))
        t += 0.12
        # the break: the voice dies down to about -20 dB (reverb, breath) for 0.2 s, then お starts a new note
        vowel("o", 0.2, db=-19.0, f0=250.0)
        t += 0.2
        vowel("o", 0.13, f0=300.0)
        cls.truth.append(("", "o", t, t))
        t += 0.13
        # ど ど: two more notes after closures
        for dur in (0.14, 0.24):
            c0 = t
            closure(0.11)
            t += 0.11
            vowel("o", dur, f0=280.0)
            cls.truth.append(("s", "o", c0, t))
            t += dur
        end1 = t
        # a second line, か then あ after a silent break (a breath): the mouth closes in the silence
        t += 0.6
        c0 = t
        t += 0.065
        vowel("a", 0.2)
        cls.truth.append(("k", "a", c0, t))
        t += 0.2
        cls.silence = (t, t + 0.25)
        t += 0.25
        vowel("a", 0.3, f0=300.0)
        cls.truth.append(("", "a", t, t))
        t += 0.3
        x += rng.normal(0, 1e-4, len(x))
        cls.voice = os.path.join(cls.folder, "v.wav")
        write_wav(cls.voice, x.astype(np.float32))
        cls.lines = os.path.join(cls.folder, "l.tsv")
        write_lines(cls.lines, [(0.8, end1 + 0.2, "きど おどど"), (end1 + 0.45, t + 0.2, "かあ")])
        morphs = [vmd.MorphKey(n, 0, 0.0) for n in VOWEL_MORPHS] + [vmd.MorphKey("まばたき", 149, 0.0)]
        cls.face = os.path.join(cls.folder, "f.vmd")
        vmd.dump(vmd.Motion(model_name="Rin", morphs=morphs), cls.face)
        cls.align = os.path.join(cls.folder, "a.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_sync.main([cls.face, cls.voice, os.path.join(cls.folder, "o.vmd"), "--lines", cls.lines,
                                      "--align-out", cls.align])
        with open(cls.align, encoding="utf-8") as f:
            cls.morae = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_each_syllable_starts_on_its_own_note(self):
        self.assertEqual(self.code, 0)
        self.assertEqual([m["kana"] for m in self.morae], ["き", "ど", "お", "ど", "ど", "か", "あ"])
        for m, (c, v, c0, v0) in zip(self.morae, self.truth):
            self.assertAlmostEqual(m["v0"], v0, delta=0.04, msg=m["kana"])

    def test_no_vowel_is_squeezed_to_its_shortest(self):
        for m in self.morae:
            self.assertGreater(m["v1"] - m["v0"], 0.08, m["kana"])

    def test_the_break_is_found_and_the_jaw_stays_near_the_vowel_through_it(self):
        o = [m for m in self.morae if m["kana"] == "お"][0]
        self.assertIn("g0", o)
        self.assertAlmostEqual(o["g0"], self.truth[1][3] + 0.12, delta=0.05)       # where the と's note dies down
        tr = tracks(vmd.load(os.path.join(self.folder, "o.vmd")), 150)
        mid = int(round(frame_at(o["v0"] - 0.1)))                                 # 0.1 s into the break's end
        self.assertGreater(tr["お"][mid], 0.2)
        self.assertLess(tr["お"][mid], 0.8)

    def test_the_mouth_closes_in_a_silent_break(self):
        a = [m for m in self.morae if m["kana"] == "あ"][0]
        self.assertIn("g0", a)
        tr = tracks(vmd.load(os.path.join(self.folder, "o.vmd")), 150)
        mid = int(round(frame_at(sum(self.silence) / 2.0)))
        self.assertLess(tr["あ"][mid], lip_sync.REST_OPEN)


class OutsideTheLinesTimingTest(unittest.TestCase):
    """outside the lines the mouth is FACE's own, a hand-made mouth that leads the voice by GUIDE_LAG: the output must
    lead the voice there by --lead-ms as it does in the lines, not by both (review 2026-10-17: the mouth closed 0.12 s
    before the end of a long note outside the lines)"""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(5)
        cls.folder = tempfile.mkdtemp()
        x = np.zeros(int(6.0 * SR))
        t = 1.0
        for c, v, dur in [("k", "a", 0.24), ("s", "a", 0.22), ("m", "a", 0.26), ("", "o", 0.34)]:
            if c == "k":
                t += 0.065
            elif c == "s":
                hiss = np.diff(rng.normal(0, 0.25, int(0.09 * SR) + 1))
                x[int(t * SR):int(t * SR) + len(hiss)] += _fade(hiss, 10) * 0.5
                t += 0.09
            elif c == "m":
                hum = _sung(FORMANTS["N"], int(0.07 * SR), 260.0, rng) * 0.08
                x[int(t * SR):int(t * SR) + len(hum)] += _fade(hum, 10)
                t += 0.07
            seg = _sung(FORMANTS[v], int(dur * SR), 260.0, rng) * 0.3
            x[int(t * SR):int(t * SR) + len(seg)] += _fade(seg, 15)
            t += dur
        cls.on, cls.off = 4.0, 4.9                            # a long ad lib after the line
        seg = _sung(FORMANTS["a"], int((cls.off - cls.on) * SR), 300.0, rng) * 0.3
        x[int(cls.on * SR):int(cls.on * SR) + len(seg)] += _fade(seg, 20)
        x += rng.normal(0, 1e-4, len(x))
        cls.voice = os.path.join(cls.folder, "v.wav")
        write_wav(cls.voice, x.astype(np.float32))
        cls.lines = os.path.join(cls.folder, "l.tsv")
        write_lines(cls.lines, [(0.8, t + 0.2, "かさまお")])
        lag = lip_sync.GUIDE_LAG
        fa = int(round((cls.on - lag) * FPS - lip_sync.SHOWN)) - 1
        fb = int(round((cls.off - lag) * FPS - lip_sync.SHOWN)) - 1
        cls.face_half = ((fa + 1 + lip_sync.SHOWN) / FPS, (fb + 1 + lip_sync.SHOWN) / FPS)
        morphs = [vmd.MorphKey(n, 0, 0.0) for n in VOWEL_MORPHS]
        morphs += [vmd.MorphKey("あ", fa, 0.0), vmd.MorphKey("あ", fa + 2, 1.0), vmd.MorphKey("あ", fb, 1.0),
                   vmd.MorphKey("あ", fb + 2, 0.0), vmd.MorphKey("まばたき", 179, 0.0)]
        cls.face = os.path.join(cls.folder, "f.vmd")
        vmd.dump(vmd.Motion(model_name="Rin", morphs=morphs), cls.face)
        cls.out = os.path.join(cls.folder, "o.vmd")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_sync.main([cls.face, cls.voice, cls.out, "--lines", cls.lines])
        cls.frames = 180
        cls.open = opening(tracks(vmd.load(cls.out), cls.frames), cls.frames)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def crossing(self, t0, t1, rising):
        """the shown time where the opening crosses half its height between t0 and t1"""
        f0, f1 = int(t0 * FPS), int(t1 * FPS)
        o = self.open[f0:f1 + 1]
        half = 0.5 * (o.max() + o.min())
        for k in range(1, len(o)):
            a, b = o[k - 1], o[k]
            if (a < half <= b) if rising else (a > half >= b):
                return (f0 + k - 1 + (half - a) / (b - a) + lip_sync.SHOWN) / FPS
        self.fail("no crossing")

    def test_it_runs(self):
        self.assertEqual(self.code, 0)
        self.assertGreater(self.open[int(4.45 * FPS)], 0.6)

    def test_the_mouth_opens_the_lead_before_the_ad_lib(self):
        lead = self.on - self.crossing(3.6, 4.3, True)
        self.assertAlmostEqual(lead, lip_sync.LEAD_MS / 1000.0, delta=0.025)

    def test_the_mouth_closes_the_lead_before_the_ad_lib_ends(self):
        lead = self.off - self.crossing(4.5, 5.3, False)
        self.assertAlmostEqual(lead, lip_sync.LEAD_MS / 1000.0, delta=0.025)


class HoldOutsideTheLinesTest(unittest.TestCase):
    """outside the lines the mouth is FACE's own: where FACE closes it while the voice sings on (the end of a long note
    after the lines, 233.2 s of the MV: closed 0.3 s before the voice), the last vowel it showed is held until the voice
    stops; a sound FACE never opened the mouth on (an instrument leaking into the separated voice, 247.3 s of the MV, or
    a sound that is no singing) stays closed"""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(11)
        cls.folder = tempfile.mkdtemp()
        x = np.zeros(int(8.0 * SR))
        t = 1.0
        for c, v, dur in [("k", "a", 0.24), ("s", "a", 0.22), ("m", "a", 0.26), ("", "o", 0.34)]:
            if c == "k":
                t += 0.065
            elif c == "s":
                hiss = np.diff(rng.normal(0, 0.25, int(0.09 * SR) + 1))
                x[int(t * SR):int(t * SR) + len(hiss)] += _fade(hiss, 10) * 0.5
                t += 0.09
            elif c == "m":
                hum = _sung(FORMANTS["N"], int(0.07 * SR), 260.0, rng) * 0.08
                x[int(t * SR):int(t * SR) + len(hum)] += _fade(hum, 10)
                t += 0.07
            seg = _sung(FORMANTS[v], int(dur * SR), 260.0, rng) * 0.3
            x[int(t * SR):int(t * SR) + len(seg)] += _fade(seg, 15)
            t += dur
        cls.on, cls.off = 4.0, 4.9                            # a long note after the line
        seg = _sung(FORMANTS["e"], int((cls.off - cls.on) * SR), 300.0, rng) * 0.3
        x[int(cls.on * SR):int(cls.on * SR) + len(seg)] += _fade(seg, 20)
        cls.tone = (6.0, 6.6)                                 # a loud steady tone FACE does not sing (a leak)
        n = int((cls.tone[1] - cls.tone[0]) * SR)
        x[int(cls.tone[0] * SR):int(cls.tone[0] * SR) + n] += _fade(0.2 * np.sin(2 * np.pi * 523.0 * np.arange(n) / SR), 20)
        x += rng.normal(0, 1e-4, len(x))
        cls.voice = os.path.join(cls.folder, "v.wav")
        write_wav(cls.voice, x.astype(np.float32))
        cls.lines = os.path.join(cls.folder, "l.tsv")
        write_lines(cls.lines, [(0.8, t + 0.2, "かさまお")])
        lag = lip_sync.GUIDE_LAG
        fa = int(round((cls.on - lag) * FPS - lip_sync.SHOWN)) - 1
        fb = int(round((cls.off - 0.3 - lag) * FPS - lip_sync.SHOWN)) - 1   # FACE closes 0.3 s before the voice ends
        morphs = [vmd.MorphKey(n_, 0, 0.0) for n_ in VOWEL_MORPHS]
        morphs += [vmd.MorphKey("え", fa, 0.0), vmd.MorphKey("え", fa + 2, 1.0), vmd.MorphKey("え", fb, 1.0),
                   vmd.MorphKey("え", fb + 2, 0.0), vmd.MorphKey("まばたき", 239, 0.0)]
        cls.face = os.path.join(cls.folder, "f.vmd")
        vmd.dump(vmd.Motion(model_name="Rin", morphs=morphs), cls.face)
        cls.out = os.path.join(cls.folder, "o.vmd")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_sync.main([cls.face, cls.voice, cls.out, "--lines", cls.lines])
        cls.frames = 240
        cls.open = opening(tracks(vmd.load(cls.out), cls.frames), cls.frames)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_the_mouth_stays_open_until_the_voice_ends(self):
        self.assertEqual(self.code, 0)
        # 0.15 s before the voice ends (after FACE closed): still open
        self.assertGreater(self.open[int(round(frame_at(self.off - 0.15)))], 0.3)
        # and closed soon after it ends
        self.assertLess(self.open[int(round(frame_at(self.off + 0.15)))], 0.1)

    def test_a_sound_face_never_sang_stays_closed(self):
        a, b = int(round(frame_at(self.tone[0] + 0.1))), int(round(frame_at(self.tone[1] - 0.1)))
        self.assertLessEqual(self.open[a:b + 1].max(), lip_sync.REST_OPEN + 1e-6)


class CliTest(unittest.TestCase):
    def test_a_missing_file_is_an_argument_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lip_sync.main(["no.vmd", "no.wav", "o.vmd", "--lines", "no.tsv"]), 2)

    def test_a_kanji_in_the_lines_fails(self):
        folder = tempfile.mkdtemp()
        try:
            x, truth, rows = synth_song()
            voice = os.path.join(folder, "v.wav")
            write_wav(voice, x[: SR * 3])
            lines = os.path.join(folder, "l.tsv")
            write_lines(lines, [(0.5, 2.0, "真夜中")])
            face = os.path.join(folder, "f.vmd")
            vmd.dump(face_motion(90), face)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = lip_sync.main([face, voice, os.path.join(folder, "o.vmd"), "--lines", lines])
            self.assertEqual(code, 1)
            self.assertIn("kanji", err.getvalue())
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def real_file(*parts):
    """a file of the real song under _spike/ of this tree, of a tree up to 3 folders above it (a worktree), or of
    MMD_CLI_DATA (a folder holding _spike/)"""
    folders, folder = [], ROOT
    for _ in range(4):
        folders.append(folder)
        folder = os.path.dirname(folder)
    if os.environ.get("MMD_CLI_DATA"):
        folders.append(os.environ["MMD_CLI_DATA"])
    for folder in folders:
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
    return None


SPIKE = ("_spike", "out", "hibikase")
REAL_FACE = real_file(*SPIKE, "kazusa", "ヒビカセ（Choreography by ATY）", "ヒビカセ　Face&Lips 歌ってる方.vmd")
REAL_VOCAL = real_file(*SPIKE, "audio", "vocals_htdemucs.flac")
REAL_LINES = real_file(*SPIKE, "mv", "lyrics", "lines_timed.tsv")
REAL = all((REAL_FACE, REAL_VOCAL, REAL_LINES))


def _ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(REAL, "the KAZUSA face motion, the separated voice or the timed lyric lines is not here")
class RealSongTest(unittest.TestCase):
    """the whole song: the separated voice (htdemucs) and the 49 lines; the mouth must follow the voice"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.out = os.path.join(cls.folder, "face.vmd")
        cls.report_path = os.path.join(cls.folder, "r.json")
        cls.align_path = os.path.join(cls.folder, "a.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = lip_sync.main([REAL_FACE, REAL_VOCAL, cls.out, "--lines", REAL_LINES, "--report", cls.report_path,
                                      "--align-out", cls.align_path, "--max-keys", "9000"])
        with open(cls.report_path, encoding="ascii") as f:
            cls.report = json.load(f)
        with open(cls.align_path, encoding="utf-8") as f:
            cls.aligned = json.load(f)
        x = lip_sync.read_sound(REAL_VOCAL)
        cls.voice = lip_sync.features(x)
        cls.frames = lip_sync.frames_of(vmd.load(REAL_FACE))
        cls.new = tracks(vmd.load(cls.out), cls.frames)
        cls.old = tracks(vmd.load(REAL_FACE), cls.frames)
        # the independent measure: times from the voice alone (tools/lip_check.py), not from the alignment the mouth
        # was placed on
        spec = importlib.util.spec_from_file_location("lip_check", os.path.join(ROOT, "tools", "lip_check.py"))
        cls.lip_check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.lip_check)
        cls.check = cls.lip_check.run(REAL_VOCAL, [REAL_FACE, cls.out], lines_path=REAL_LINES, align_path=cls.align_path)
        cls.tag_old, cls.tag_new = list(cls.check["faces"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def loud_at_frames(self):
        t = (np.arange(self.frames) + lip_sync.SHOWN) / FPS + lip_sync.LEAD_MS / 1000.0
        rows = np.arange(self.voice.frames) * lip_sync.STEP
        return np.interp(t, rows, self.voice.level)

    def test_every_line_is_aligned(self):
        self.assertEqual(self.code, 0)
        self.assertEqual(len(self.report["line_fit"]), self.report["lines"])
        self.assertGreaterEqual(self.report["lines"], 48)

    def test_the_aligned_vowels_agree_with_the_hand_made_keys(self):
        # the guide pulls the alignment to the hand-made vowels GUIDE_LAG later, so this checks that the guide holds and
        # the hand-made keys are not far from the voice: no agreement on its own (the lip_check tests below are that)
        lead = self.report["face_lead_ms"]
        self.assertGreaterEqual(lead["n"], 400)
        self.assertTrue(0.0 <= lead["median"] <= 120.0, lead)

    def test_the_mouth_follows_the_loudness_better(self):
        level = self.loud_at_frames()
        sung = level > lip_sync.SIL_DB

        def r(tr):
            o = opening(tr, self.frames)
            return float(np.corrcoef(o[sung | (o > 0.05)], np.clip(level[sung | (o > 0.05)], -40, 0))[0, 1])
        self.assertGreater(r(self.new), r(self.old) + 0.15)

    def test_the_mouth_is_shut_where_the_voice_rests_and_open_where_it_sings(self):
        level = self.loud_at_frames()
        o = opening(self.new, self.frames)
        quiet = level < lip_sync.SIL_DB - 6
        self.assertLess(float((o[quiet] > 0.35).mean()), 0.05)
        loud = level > -12
        self.assertLess(float((o[loud] < 0.1).mean()), 0.08)

    def test_the_keys_fit_mmd(self):
        self.assertLessEqual(self.report["keys"]["after_total"], 9000)

    def test_the_mouth_opens_ahead_of_the_voice_by_a_measure_of_its_own(self):
        """the open vowels after a voice onset (lip_check: the mouth must open visibly there): half open 20 to 90 ms
        before the onset, hardly any noticed late or early (ITU-R BT.1359-1), and more of them answered than by the
        hand-made mouth (2026-10-17 on the MV's face_v9f: 54 ms, 0.8 % late, 1.5 % early, 0.88 paired against 0.61)"""
        new = self.check["faces"][self.tag_new]["open_vowel_onsets"]
        old = self.check["faces"][self.tag_old]["open_vowel_onsets"]
        self.assertTrue(20.0 <= new["lag_ms"]["median"] <= 90.0, new)
        self.assertLessEqual(new["share_mouth_late_over_45ms"], 0.05, new)
        self.assertLessEqual(new["share_mouth_early_over_125ms"], 0.05, new)
        self.assertGreater(new["share_paired"], old["share_paired"] + 0.1, (new, old))

    def test_no_line_sits_a_syllable_off(self):
        """per line, the median lag of the voice onsets inside it stays within what goes unnoticed (a line aligned a
        syllable off would sit some 200 ms off), and no line's vowels sound better shifted by one mora"""
        for row in self.check["lines"]:
            got = row[self.tag_new]
            if got["paired"] >= 3:
                self.assertTrue(-45.0 <= got["median_ms"] <= 125.0, row)
        self.assertEqual(self.check["alignment"]["vowels"]["lines_fit_better_shifted"], [])

    def test_the_aligned_syllables_start_where_the_voice_does(self):
        """the aligned starts of the syllables after a consonant fall on a voice onset far more often than chance, and
        the aligned vowels sound close (い う) or open (あ え お) as labelled (2026-10-17: 0.65 against 0.05, 0.89)"""
        onsets = self.check["alignment"]["onsets"]
        self.assertGreaterEqual(onsets["share_within_30ms"], onsets["chance_within_30ms"] + 0.4, onsets)
        self.assertGreaterEqual(self.check["alignment"]["vowels"]["share_agree_close_open"], 0.8)


if __name__ == "__main__":
    unittest.main()
