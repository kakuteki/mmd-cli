"""tools/face_life.py: the face motion (expressions, blinks, mouth) rewritten to move more like a person's."""
import contextlib
import importlib.util
import io
import json
import math
import random
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("face_life", os.path.join(ROOT, "tools", "face_life.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


face_life = load_tool()
F = 1800
FPS = 30.0


def key(name, frame, weight):
    return vmd.MorphKey(name, frame, weight)


def blink_keys():
    """the intro closed until 102, then type A blinks (a 0.50 key one frame before the peak, nothing holding the
    base before it: the lid creeps up from 0.26 to 0.50 between blinks), as the KAZUSA motion has them"""
    keys = [key("まばたき", 0, 1.0), key("まばたき", 100, 1.0), key("まばたき", 102, 0.26)]
    for peak in (300, 420, 560, 900, 1150, 1400, 1650):
        keys += [key("まばたき", peak - 1, 0.5), key("まばたき", peak, 1.0), key("まばたき", peak + 1, 1.0),
                 key("まばたき", peak + 3, 0.26)]
    # a long closure as the smile ends (笑い 0.5 -> 0 over 1500-1505): まばたき + 笑い stays at or under 1
    keys += [key("まばたき", 1500, 0.3), key("まばたき", 1506, 1.0), key("まばたき", 1520, 1.0),
             key("まばたき", 1524, 0.26)]
    return keys


def lip_keys():
    """a phrase of vowels from 600: crossfades of two frames and one closure of the lips (m) before お at 627"""
    k = []
    add = lambda n, f, w: k.append(key(n, f, w))  # noqa: E731
    add("あ", 0, 0.0); add("い", 0, 0.0); add("う", 0, 0.0); add("え", 0, 0.0); add("お", 0, 0.0)
    add("あ", 596, 0.0); add("あ", 600, 1.0); add("あ", 605, 1.0); add("あ", 607, 0.0)      # a, then i at 607
    add("い", 605, 0.0); add("い", 607, 1.0); add("い", 612, 1.0); add("い", 614, 0.0)      # i, then a at 614
    add("あ", 612, 0.0); add("あ", 614, 1.0); add("あ", 622, 1.0); add("あ", 623, 0.0)      # a, shut 624-625
    add("お", 625, 0.0); add("お", 627, 1.0); add("お", 634, 1.0); add("お", 636, 0.0)      # o (after m)
    add("え", 634, 0.0); add("え", 636, 1.0); add("え", 650, 1.0); add("え", 656, 0.0)      # e, end of phrase
    add("お", 676, 0.0); add("お", 680, 1.0); add("お", 690, 1.0); add("お", 694, 0.0)      # o after a shut gap
    return k


def face_motion():
    keys = [key("真面目", 0, 0.0), key("真面目", 400, 0.0), key("真面目", 405, 1.0), key("真面目", 1000, 1.0),
            key("真面目", 1005, 0.0), key("下", 0, 0.0), key("下", 400, 0.0), key("下", 405, 0.6), key("下", 1000, 0.6),
            key("下", 1005, 0.0), key("笑い", 0, 0.0), key("笑い", 1100, 0.0), key("笑い", 1105, 0.5),
            key("笑い", 1500, 0.5), key("笑い", 1505, 0.0), key("口角上げ", 0, 0.0), key("口角下げ", 0, 0.0),
            key("ウィンク", 0, 0.0)]
    return vmd.Motion(model_name="face", morphs=keys + blink_keys() + lip_keys())


TURNS = (500, 800, 1200, 1600)          # the head swings by 45 degrees in 6 frames here


def head_track():
    """the head's world rotation per frame (as applied): still, with quick yaw swings at TURNS, back and forth"""
    yaw = np.zeros(F)
    sign = 1.0
    for start in TURNS:
        target = 45.0 if sign > 0 else 0.0
        yaw[start:start + 6] = np.linspace(yaw[start - 1], target, 7)[1:]
        yaw[start + 6:] = target
        sign = -sign
    out = np.zeros((F, 4))
    out[:, 1] = np.sin(np.radians(yaw) / 2)
    out[:, 3] = np.cos(np.radians(yaw) / 2)
    return out


def still_eyes():
    out = np.zeros((F, 4))
    out[:, 3] = 1.0
    return out


def quiet_gap_voice():
    """the centre power every 10 ms: loud, but quiet from frame 650 to 676 (the shut gap before the second phrase)"""
    n = int(F / FPS * 100) + 10
    voice = np.ones(n)
    t = np.arange(n) / 100.0 + face_life.AUDIO_T0
    voice[(t >= (650 + face_life.SHOWN) / FPS) & (t <= (676 + face_life.SHOWN) / FPS)] = 1e-4
    return voice


def inputs(**over):
    values = dict(face=face_motion(), frames=F, head=head_track(), eyes=still_eyes(), body_start=150,
                  voice=quiet_gap_voice(), lines=[(19.9, 23.4)], morphs=None, dance_morph_keys=[])
    values.update(over)
    return face_life.Inputs(**values)


def tracks(motion, frames=F):
    out = {}
    by = {}
    for k in motion.morphs:
        by.setdefault(k.name, {})[k.frame] = k.weight
    for name, d in by.items():
        fr = sorted(d)
        out[name] = np.interp(np.arange(frames), fr, [d[f] for f in fr])
    return out


V7_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "face_life_v7_synthetic.vmd")


class V7StyleTest(unittest.TestCase):
    """--style v7 makes the face of the MV v7 again: the fixture is the output of the tool as it was at main 08894a4
    (the v7 face) for these inputs, seed 0, 瞳1off held at 1 and HL２ at 0.5"""

    def test_the_v7_style_writes_the_v7_face_byte_for_byte(self):
        with open(V7_FIXTURE, "rb") as f:
            v7 = f.read()
        made = vmd.dumps(face_life.plan(inputs(), seed=0, hold={"瞳1off": 1.0, "HL２": 0.5}, style="v7").motion)
        self.assertEqual(made, v7)

    def test_the_human_style_is_the_default_and_differs(self):
        with open(V7_FIXTURE, "rb") as f:
            v7 = f.read()
        default = face_life.plan(inputs(), seed=0, hold={"瞳1off": 1.0, "HL２": 0.5})
        self.assertEqual(default.report["style"], "human")
        self.assertNotEqual(vmd.dumps(default.motion), v7)

    def test_an_unknown_style_is_refused(self):
        with self.assertRaisesRegex(ValueError, "style"):
            face_life.plan(inputs(), seed=0, style="v6")

    def test_the_command_passes_the_style_on(self):
        argv = ["f.vmd", "d.vmd", "g.vmd", "m.pmx", "o.vmd"]
        with mock.patch.object(face_life, "run", return_value={}) as run, mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(face_life.main(argv), 0)
            self.assertEqual(run.call_args.kwargs["style"], "human")
            self.assertEqual(face_life.main(argv + ["--style", "v7"]), 0)
            self.assertEqual(run.call_args.kwargs["style"], "v7")
        with mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            face_life.main(argv + ["--style", "v6"])


def shut_runs(b, s, start=150, longest=face_life.SHORT_CLOSURE):
    """per blink (a10's closures of まばたき + 笑い from `start`, those shut longer than `longest` frames left out): (the
    last frame the lid is at its level before, the first frame of its peak, the last frame of its peak, the first frame
    it is back at its level).  The closing takes p0 - before frames, the opening after - p1, the blink after - before."""
    c = b + s
    out = []
    for e in face_life.episodes(c, start):
        if e["closed"] > longest:
            continue
        around = s[max(0, e["cs"] - 4):min(len(s), e["oe"] + 12)]
        if around.max() - around.min() > 0.02:
            continue                        # the smile moves under it: its rise or fall is no part of the blink
        top = c[e["t0"]:e["t1"] + 1].max()
        peak = [f for f in range(e["t0"], e["t1"] + 1) if c[f] >= top - 1e-6]
        level = c[max(0, e["cs"] - 3):e["cs"] + 1].min()
        f0 = peak[0]
        while f0 > 0 and c[f0 - 1] > level + 0.01:
            f0 -= 1
        level = c[e["oe"]:min(len(c), e["oe"] + 12)].min()
        f1 = peak[-1]
        while f1 + 1 < len(c) and c[f1 + 1] > level + 0.01:
            f1 += 1
        out.append((f0 - 1, peak[0], peak[-1], f1 + 1))
    return out


LONG_LINES = [(8.0, 12.0), (19.9, 23.4), (30.0, 34.0), (40.0, 44.0), (50.0, 55.0)]


def phrased_face():
    """the synthetic face with phrases of vowels (8 frames apart) spread over the song, so that it has phrase ends"""
    face = face_motion()
    extra = []
    for a, z in ((240, 330), (900, 990), (1200, 1290), (1500, 1650)):
        for i, f in enumerate(range(a, z, 8)):
            v = "あいうえお"[i % 5]
            extra += [key(v, f - 2, 0.0), key(v, f, 1.0), key(v, f + 4, 1.0), key(v, f + 6, 0.0)]
    face.morphs = face.morphs + extra
    return face


def choppy_face():
    """the synthetic face with short phrases (3 vowels, 8 frames apart) every 60 frames from 300 to 1700: a phrase end
    every 2 seconds"""
    face = face_motion()
    extra = []
    for a in range(300, 1700, 60):
        for i, f in enumerate(range(a, a + 24, 8)):
            v = "あいうえお"[i % 5]
            extra += [key(v, f - 2, 0.0), key(v, f, 1.0), key(v, f + 4, 1.0), key(v, f + 6, 0.0)]
    face.morphs = face.morphs + extra
    return face


def long_blinks(b, s, start=150):
    """the blinks of the tracks that stay shut (まばたき + 笑い at their peak) 3 frames or more: [(the last frame at the
    level before, the first frame back at the level after)]"""
    return [(a, z) for a, t0, t1, z in shut_runs(b, s, start, longest=8) if t1 - t0 + 1 >= 3]


class LongBlinkTest(unittest.TestCase):
    """(review of face-v2) no study measured singers' blinks.  Long blinks in conversation (Homke et al. 2017, 2018)
    are a listener's, at the end of the speaker's turn: no ground for a singer's.  A character's blink looked most
    natural at 7 to 9 frames and less natural at 11 and 13 (Trutoiu et al. 2011).  So a long blink is kept to 10 to 11
    frames (shut 3 to 4 frames, a normal one 1 to 2) and two are at least LONG_GAP frames apart (in B2 four came within
    10 seconds)"""

    @classmethod
    def setUpClass(cls):
        cls.runs = []
        for seed in range(5):
            t = tracks(face_life.plan(inputs(face=choppy_face(), lines=[(9.0, 58.0)]), seed=seed).motion)
            cls.runs.append(long_blinks(t["まばたき"], t["笑い"]))

    def test_a_long_blink_lasts_10_to_11_frames(self):
        lengths = [z - a for run in self.runs for a, z in run]
        self.assertGreater(len(lengths), 4, lengths)
        self.assertTrue(all(10 <= n <= 11 for n in lengths), lengths)

    def test_long_blinks_are_apart(self):
        for run in self.runs:
            starts = [a for a, _ in run]
            self.assertTrue(all(b - a >= face_life.LONG_GAP for a, b in zip(starts, starts[1:])), starts)


class HumanBlinkTest(unittest.TestCase):
    """a spontaneous blink closes in 2 to 3 frames and opens in 4 to 7, 7 to 12 frames in all as the end of the
    opening is taken (Wu et al. 2014: 7.8 frames from 10 % of the peak speed to 10 %); a character's blink looked most
    natural at 7 to 9 frames, less at 11 and 13 (Trutoiu et al. 2011).  The lid closes 1.4 to 2.6 times as fast as it
    opens; the opening is fast first and slow at its end.  Some blinks after a phrase and where nothing is sung are
    long (10 to 11 frames: LongBlinkTest)"""

    @classmethod
    def setUpClass(cls):
        cls.result = face_life.plan(inputs(face=phrased_face(), lines=LONG_LINES), seed=0)
        cls.t = tracks(cls.result.motion)
        cls.listed = cls.result.report["blink"]["new"]["list"]
        cls.blinks = shut_runs(cls.t["まばたき"], cls.t["笑い"], longest=8)
        cls.pooled = [x for seed in range(5)
                      for x in face_life.plan(inputs(face=phrased_face(), lines=LONG_LINES), seed=seed).report["blink"]["new"]["list"]]

    def test_there_are_blinks_both_short_and_long(self):
        self.assertGreater(len(self.blinks), 8)
        long_ = [x for x in self.pooled if x["hold"] >= 2]
        self.assertGreater(len(long_), 3)
        self.assertLess(len(long_), 0.35 * len(self.pooled))
        self.assertTrue(all(x["cause"] in ("phrase_end", "fill") for x in long_), long_)

    def test_a_short_blink_lasts_7_to_10_frames(self):
        lengths = [z - a for a, _, _, z in self.blinks]
        short = [n for n in lengths if n <= 10]
        self.assertTrue(short and all(7 <= n <= 10 for n in short), lengths)
        self.assertTrue(8 <= float(np.median(short)) <= 9, lengths)

    def test_the_lid_opens_at_least_one_and_a_half_times_as_slowly_as_it_closes(self):
        for a, t0, t1, z in self.blinks:
            self.assertLessEqual(t0 - a, 3)
            self.assertGreaterEqual(z - t1, 1.5 * (t0 - a), (a, t0, t1, z))

    def test_the_opening_is_fast_first_and_slow_at_its_end(self):
        c = self.t["まばたき"] + self.t["笑い"]
        for a, t0, t1, z in self.blinks:
            steps = -np.diff(c[t1:z + 1])
            self.assertTrue(np.all(steps > -1e-9), steps)
            half = len(steps) // 2
            self.assertGreater(steps[:half].sum(), 1.5 * steps[half:].sum(), steps)

    def test_the_report_counts_the_blinks_as_a10_did(self):
        dist = self.result.report["blink"]["new"]["frames_closing_start_to_open"]
        self.assertGreaterEqual(dist["median"], 7)


def between_blinks(b, s, start=150):
    """frames from `start` outside the blinks and the long closures (a10's episodes, closing start to opening end)"""
    mask = np.zeros(len(b), bool)
    mask[start:] = True
    for e in face_life.episodes(b + s, start):
        mask[max(0, e["cs"] - 1):e["oe"] + 2] = False
    return mask


def pitched_eyes(spans):
    """the 両目 rotation per frame: level, but `spans` [(first, last, degrees up)]"""
    eyes = still_eyes()
    for a, z, deg in spans:
        half = np.radians(deg) / 2.0
        eyes[a:z + 1, 0] = np.sin(half)
        eyes[a:z + 1, 3] = np.cos(half)
    return eyes


class HumanLidTest(unittest.TestCase):
    """the lid between the blinks.  The KAZUSA motion holds the upper lid low (まばたき 0.22 to 0.38) through its serious
    face; the synthetic face holds 0.26 from the wake-up on.  The human style shows only part of the author's lowering
    above the neutral lid: little while a phrase is sung, more after it; the lid follows the eyes up and down"""

    @classmethod
    def setUpClass(cls):
        cls.result = face_life.plan(inputs(), seed=0)
        cls.t = tracks(cls.result.motion)
        cls.open = between_blinks(cls.t["まばたき"], cls.t["笑い"])
        cls.v7 = tracks(face_life.plan(inputs(), seed=0, style="v7").motion)

    def test_the_authors_low_lid_shows_only_in_part(self):
        b, s = self.t["まばたき"], self.t["笑い"]
        lid = b[self.open & (s < 0.01)]
        self.assertGreaterEqual(lid.min(), face_life.LID_NEUTRAL - 1e-6)
        self.assertLessEqual(lid.max(), 0.26 + 1e-6)
        self.assertLess(float(np.mean(lid)), 0.10 + 0.6 * (0.26 - 0.10))

    def test_the_eyes_are_more_open_while_a_phrase_is_sung_than_after_it(self):
        b = self.t["まばたき"]
        sung = [f for f in range(604, 634) if self.open[f]]       # the phrase of 600 to 636
        after = [f for f in range(652, 676) if self.open[f]]      # its end and the pause before 680
        self.assertTrue(sung and after)
        self.assertLess(float(np.mean(b[sung])), float(np.mean(b[after])) - 0.04)

    def test_half_closed_eyes_take_much_less_time_than_in_v7(self):
        open7 = between_blinks(self.v7["まばたき"], self.v7["笑い"])
        half7 = float((self.v7["まばたき"][open7] >= 0.2).mean())
        half = float((self.t["まばたき"][self.open] >= 0.2).mean())
        self.assertGreater(half7, 0.9)
        self.assertLess(half, 0.5 * half7)

    def test_the_lid_changes_quickly_and_never_creeps(self):
        b = self.t["まばたき"]
        step = np.diff(b, prepend=b[0])
        creep = (step > 1e-5) & (step <= 0.05)
        creep[:150] = False
        self.assertEqual([r for r in face_life.runs(creep) if r[1] - r[0] + 1 >= 10], [])


class ShownShareTest(unittest.TestCase):
    """the share of the author's lowered lid that shows moves at a phrase's start and after its end, over a few frames,
    or at once while the eye is shut when a blink comes near (a person changes the lid's height with a blink)"""

    PHRASE = [face_life.lip_timing.Phrase(300, 400, "aiu")]

    def test_the_eyes_open_for_the_phrase_and_relax_after_it(self):
        s = face_life.shown_share(self.PHRASE, 1000)
        self.assertAlmostEqual(s[250], face_life.LID_SHOWN[1])
        self.assertAlmostEqual(s[350], face_life.LID_SHOWN[0])
        self.assertAlmostEqual(s[420], face_life.LID_SHOWN[2])
        self.assertAlmostEqual(s[600], face_life.LID_SHOWN[1])
        self.assertGreater(len(set(np.round(s[293:301], 6))), 3)          # a ramp, ending at the first vowel

    def test_a_change_near_a_blink_happens_while_the_eye_is_shut(self):
        s = face_life.shown_share(self.PHRASE, 1000, blinks=[(295, 297, 305)])
        self.assertEqual(len(set(np.round(s[285:310], 6))), 2)
        self.assertAlmostEqual(s[296], face_life.LID_SHOWN[1])
        self.assertAlmostEqual(s[297], face_life.LID_SHOWN[0])

    def test_a_blink_that_ends_just_before_the_change_takes_it(self):
        s = face_life.shown_share(self.PHRASE, 1000, blinks=[(280, 282, 291)])
        self.assertAlmostEqual(s[281], face_life.LID_SHOWN[1])
        self.assertAlmostEqual(s[282], face_life.LID_SHOWN[0])
        self.assertEqual(len(set(np.round(s[270:310], 6))), 2)

    def test_a_blink_far_from_the_change_leaves_the_ramp(self):
        free = face_life.shown_share(self.PHRASE, 1000)
        far = face_life.shown_share(self.PHRASE, 1000, blinks=[(260, 262, 270)])
        np.testing.assert_array_equal(free, far)

    def test_a_quiet_phrase_never_shows_more_than_the_authors_own_lowering(self):
        # the quietest phrase shows LID_QUIET more of the author's lowering than the loudest, but never more than all of it
        phrases = [face_life.lip_timing.Phrase(300, 400, "aiu"), face_life.lip_timing.Phrase(600, 700, "aiu")]
        n = int(1000 / FPS * 100) + 10                                       # the centre power every 10 ms
        voice = np.ones(n)
        t = np.arange(n) / 100.0 + face_life.AUDIO_T0
        voice[(t >= 600 / FPS) & (t <= 701 / FPS)] = 1e-4                  # the second phrase is quiet
        with mock.patch.object(face_life, "LID_SHOWN", (0.85, 0.95, 1.0)):
            s = face_life.shown_share(phrases, 1000, voice)
        self.assertGreater(s[650], s[350])
        self.assertLessEqual(float(s.max()), 1.0 + 1e-9)


class LidFollowsTheEyesTest(unittest.TestCase):
    """the upper lid moves with the eyes (Sour's Rin: まばたき about 0.027 a degree down keeps the lid where it is on the
    iris, 0.021 a degree up; it cannot rise above 0)"""

    @classmethod
    def setUpClass(cls):
        cls.level = tracks(face_life.plan(inputs(), seed=0).motion)["まばたき"]
        cls.down = tracks(face_life.plan(inputs(eyes=pitched_eyes([(700, 790, -8.0)])), seed=0).motion)["まばたき"]
        cls.up = tracks(face_life.plan(inputs(eyes=pitched_eyes([(700, 790, 6.0)])), seed=0).motion)["まばたき"]
        cls.open = between_blinks(cls.level, np.zeros(F)) & between_blinks(cls.down, np.zeros(F)) \
            & between_blinks(cls.up, np.zeros(F))

    def test_looking_down_lowers_the_lid_with_the_eyes(self):
        frames = [f for f in range(706, 788) if self.open[f]]
        self.assertTrue(frames)
        rise = self.down[frames] - self.level[frames]
        np.testing.assert_allclose(rise, 8 * face_life.LID_FOLLOW[0], atol=0.02)

    def test_looking_up_raises_the_lid_down_to_open(self):
        frames = [f for f in range(706, 788) if self.open[f]]
        fall = self.level[frames] - self.up[frames]
        expected = np.minimum(self.level[frames], 6 * face_life.LID_FOLLOW[1])
        np.testing.assert_allclose(fall, expected, atol=0.02)
        self.assertGreaterEqual(self.up.min(), 0.0)

    def test_the_lid_moves_with_the_saccade(self):
        moved = np.abs(self.down - self.level) > 0.05
        first = int(np.argmax(moved[690:])) + 690
        self.assertTrue(700 <= first <= 703, first)


def nodding(a, z, period=13, swing=4.0, look=-4.0, counter=True):
    """(head, eyes, the eyes' pitch in the head): head_track's head nodding over [a, z] by `swing` degrees each way
    every `period` frames, and the eyes `look` degrees down in the head; with `counter` they turn against the nod so
    that the gaze stays still in the world (a dancer's eyes on the beat: they move in the head without a saccade)"""
    head, eyes = head_track(), still_eyes()
    nod = np.zeros(F)
    nod[a:z + 1] = swing * np.sin(2.0 * np.pi * (np.arange(a, z + 1) - a) / period)
    pitch = look - nod if counter else np.full(F, look)
    for f in range(F):
        h = math.radians(nod[f]) / 2.0
        head[f] = fk.multiply(tuple(head[f]), (math.sin(h), 0.0, 0.0, math.cos(h)))
        e = math.radians(pitch[f]) / 2.0
        eyes[f] = (math.sin(e), 0.0, 0.0, math.cos(e))
    return head, eyes, pitch


class LidFollowsMovingEyesTest(unittest.TestCase):
    """human style: the upper lid goes with the eyes on every frame, also when they move in the head without a
    saccade (a person's lid follows the eye's vertical position however the eye moves: Becker and Fuchs 1988).  The
    dance's eyes turn against the head's nod on the beat all the time; a lid set once per fixation (the median of the
    eyes between two saccades) stays where the eyes were on average and leaves them behind"""

    @classmethod
    def setUpClass(cls):
        head, eyes, cls.pitch = nodding(700, 790)
        cls.moving = tracks(face_life.plan(inputs(head=head, eyes=eyes), seed=0).motion)["まばたき"]
        head, eyes, _ = nodding(700, 790, counter=False)
        cls.still = tracks(face_life.plan(inputs(head=head, eyes=eyes), seed=0).motion)["まばたき"]
        cls.open = between_blinks(cls.moving, np.zeros(F)) & between_blinks(cls.still, np.zeros(F))

    def test_no_saccade_is_found_in_the_counter_turn(self):
        head, eyes, _ = nodding(700, 790)
        self.assertEqual([s for s in face_life.saccades(head, eyes) if 690 <= s["start"] <= 800], [])

    def test_the_lid_goes_with_the_eyes_on_every_frame(self):
        frames = [f for f in range(703, 788) if self.open[f]]
        self.assertGreater(len(frames), 40)
        rise = self.moving[frames] - self.still[frames]
        expected = face_life.LID_FOLLOW[0] * (-self.pitch[frames] - 4.0)
        np.testing.assert_allclose(rise, expected, atol=0.02)
        self.assertGreater(float(np.abs(rise).max()), 0.08)


class BakeWithinTest(unittest.TestCase):
    """a lid that follows the eyes bends on almost every frame: baked key for key it fills MMD's registered points
    (20,000 for a model's morph keys with every motion loaded).  bake_within keeps the keys that straight lines need
    to stay within a tolerance of every frame, and never turns a slow rise broken by small dips into a10's creep"""

    def test_the_keys_stay_within_the_tolerance_and_are_fewer(self):
        f = np.arange(600)
        v = 0.2 + 0.1 * np.sin(f / 40.0) + 0.3 * (f >= 300) + 0.004 * np.sin(f / 2.0)
        keys = face_life.bake_within(v, 0.001, 0)
        back = face_life.track(keys, len(v))
        self.assertLessEqual(float(np.abs(back - v).max()), 0.001 + 1e-6)
        self.assertLess(len(keys), 0.8 * len(face_life.bake(v)))
        self.assertEqual((keys[0][0], keys[-1][0]), (0, 599))

    def test_a_slow_rise_broken_by_small_dips_stays_without_creep(self):
        v = np.full(200, 0.1)
        i = np.arange(40)
        v[80:120] = 0.1 + 0.0005 * i + 0.0008 * (i % 2)         # up 0.0013, down 0.0003, up ...: no creep; a line within
                                                                  # 0.001 of it rises 0.0005 a frame for 40 frames: one
        v[120:] = v[119]
        self.assertEqual(face_life.creep_runs(v, 0), [])
        keys = face_life.bake_within(v, 0.001, 0)
        self.assertEqual(face_life.creep_runs(face_life.track(keys, len(v)), 0), [])

    def test_the_human_blink_track_is_baked_within_the_tolerance(self):
        # a slow nod (2 s): the lid follows a gentle curve that bake keys on every frame where it bends (50 keys here)
        head, eyes, _ = nodding(700, 790, period=60, swing=6.0)
        motion = face_life.plan(inputs(head=head, eyes=eyes), seed=0).motion
        frames = sorted(k.frame for k in motion.morphs if k.name == "まばたき")
        inside = [f for f in frames if 702 <= f <= 788]
        self.assertLess(len(inside), 0.5 * 87)


def moving_point(moves, frames=F, rest=(0.0, 10.0, 0.0)):
    """a point's world position per frame: at rest, moved by `moves` [(first, frames, (dx, dy, dz))], each move eased
    in and out (smoothstep) over its frames and held after"""
    p = np.tile(np.array(rest, float), (frames, 1))
    for first, n, d in moves:
        x = np.clip((np.arange(frames) - first) / float(n), 0.0, 1.0)
        p += (x * x * (3.0 - 2.0 * x))[:, None] * np.array(d, float)[None, :]
    return p


class KimeTest(unittest.TestCase):
    """the body's accents ("決め"): a fast move of the head or a hand that stops and holds the pose"""

    def test_a_fast_move_that_stops_and_holds_is_a_kime(self):
        hand = moving_point([(300, 5, (3.0, 0.0, 0.0))])                 # 3 units in 5 frames, then held
        found = face_life.kimes({"右手首": hand}, start=0)
        self.assertEqual(len(found), 1)
        self.assertTrue(304 <= found[0]["frame"] <= 307, found)

    def test_a_stop_that_moves_on_at_once_is_no_kime(self):
        # out and straight back (the return stops and holds: that one is a kime)
        hand = moving_point([(300, 5, (3.0, 0.0, 0.0)), (306, 5, (-3.0, 0.0, 0.0))])
        frames = [k["frame"] for k in face_life.kimes({"右手首": hand}, start=0)]
        self.assertFalse([f for f in frames if f < 310], frames)
        self.assertEqual(len(frames), 1)

    def test_slow_moves_are_no_kime(self):
        hand = moving_point([(300, 60, (3.0, 0.0, 0.0))])
        self.assertEqual(face_life.kimes({"右手首": hand}, start=0), [])

    def test_parts_stopping_together_are_one_kime_and_the_strongest_counts(self):
        a = moving_point([(300, 5, (3.0, 0.0, 0.0))])
        b = moving_point([(301, 4, (0.0, 4.0, 0.0))])
        found = face_life.kimes({"右手首": a, "左手首": b}, start=0)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0]["speed"], 25.0)

    def test_nothing_before_the_body_starts(self):
        hand = moving_point([(100, 5, (3.0, 0.0, 0.0)), (400, 5, (-3.0, 0.0, 0.0))])
        found = face_life.kimes({"右手首": hand}, start=200)
        self.assertEqual(len(found), 1)
        self.assertTrue(404 <= found[0]["frame"] <= 407, found)


class KimeAlignTest(unittest.TestCase):
    """human style: a change of the face that a kime can reach (ALIGN frames) arrives a frame before it, the face
    landing with the pose (a picture up to about 4 frames before the sound goes unnoticed, 1.4 frames after it does
    not: ITU-R BT.1359-1); v7 kept the rule of the head's fastest turn"""

    KEYS = {"真面目": [(0, 0.0), (400, 0.0), (405, 1.0)], "笑い": [(0, 0.0), (403, 0.0), (408, 0.5)]}

    def stretched(self, kimes, style, seed=0):
        out, events, stretched = face_life.rewrite_expressions(
            {n: list(v) for n, v in self.KEYS.items()}, [(0, 0.5), (F - 1, 0.5)], np.zeros(F), F, random.Random(seed),
            lambda n: n not in ("口角上げ", "口角下げ"), kimes=kimes, style=style)
        return {n: (s, e) for n, s, e in stretched}, events

    def test_a_change_within_reach_of_a_kime_arrives_a_frame_before_it(self):
        for seed in range(5):
            spans, events = self.stretched([{"frame": 416, "speed": 30.0, "part": "右手首"}], "human", seed)
            self.assertLessEqual(abs(max(e for _, e in spans.values()) - 415), 1, (seed, spans))
            self.assertEqual(events[0]["kime"], 416)

    def test_human_changes_take_13_frames_or_more(self):
        for seed in range(5):
            spans, _ = self.stretched([], "human", seed)
            self.assertTrue(all(e - s >= 13 for s, e in spans.values()), spans)

    def test_a_kime_out_of_reach_moves_nothing(self):
        alone, _ = self.stretched([], "human")
        far, events = self.stretched([{"frame": 470, "speed": 30.0, "part": "右手首"}], "human")
        self.assertEqual(alone, far)
        self.assertIsNone(events[0]["kime"])

    def test_the_strongest_kime_within_reach_wins(self):
        spans, _ = self.stretched([{"frame": 410, "speed": 12.0, "part": "頭"}, {"frame": 418, "speed": 40.0, "part": "左手首"}],
                                  "human")
        self.assertLessEqual(abs(max(e for _, e in spans.values()) - 417), 1, spans)

    def test_the_v7_style_does_not_look_at_kimes(self):
        plain, _ = self.stretched([], "v7")
        kimed, _ = self.stretched([{"frame": 416, "speed": 30.0, "part": "右手首"}], "v7")
        self.assertEqual(plain, kimed)


class FlashTest(unittest.TestCase):
    """human style: at some of the kimes where she sings, the eyes open for a moment (the lid to the model's open
    eye, at its widest a frame before the kime), a few a minute, never two within FLASH_GAP frames"""

    def plan_with(self, moves, seed=0):
        hand = moving_point(moves)
        return face_life.plan(inputs(parts={"右手首": hand}), seed=seed)

    def test_the_eyes_open_at_a_kime_where_she_sings(self):
        result = self.plan_with([(612, 5, (3.0, 0.0, 0.0))])               # stops about 616, in the phrase 600-636
        flashes = result.report["blink"]["flashes"]
        self.assertEqual(len(flashes), 1)
        k = flashes[0]
        self.assertTrue(615 <= k <= 619, k)
        b = tracks(result.motion)["まばたき"]
        plain = tracks(face_life.plan(inputs(), seed=0).motion)["まばたき"]
        if between_blinks(b, np.zeros(F))[k - 1]:
            self.assertLess(b[k - 1], 0.02)
        self.assertLess(float(b[k - 1]), float(plain[k - 1]) - 0.08)
        np.testing.assert_allclose(b[k + 12:k + 20], plain[k + 12:k + 20], atol=1e-6)

    def test_no_flash_where_she_does_not_sing(self):
        result = self.plan_with([(1200, 5, (3.0, 0.0, 0.0))])
        self.assertEqual(result.report["blink"]["flashes"], [])

    def test_flashes_are_few_and_apart(self):
        moves, sign = [], 1.0
        for f in range(240, 1700, 25):                                       # a kime every 25 frames
            moves.append((f, 5, (3.0 * sign, 0.0, 0.0)))
            sign = -sign
        lines = [(8.0, 57.0)]                                                # she sings all along
        result = face_life.plan(inputs(parts={"右手首": moving_point(moves)}, lines=lines), seed=0)
        flashes = result.report["blink"]["flashes"]
        # the blinks are many here and a flash a blink runs into gives way (FlashClashTest): a few are left
        self.assertGreaterEqual(len(flashes), 2)
        self.assertTrue(all(b - a >= face_life.FLASH_GAP for a, b in zip(flashes, flashes[1:])), flashes)
        window = int(60 * FPS)
        self.assertLessEqual(max(sum(1 for g in flashes if f <= g < f + window) for f in range(0, F, 10)),
                             face_life.FLASH_RATE)

    def test_the_v7_style_has_none(self):
        result = face_life.plan(inputs(parts={"右手首": moving_point([(612, 5, (3.0, 0.0, 0.0))])}), seed=0, style="v7")
        self.assertNotIn("flashes", result.report["blink"])


def smiling_face(weight=0.6, frames=(800, 1300)):
    """the synthetic face with 笑い at `weight` over `frames` and the author's lid at 0 there (as in KAZUSA's smiles),
    0.26 elsewhere after the eyes open at 102, no old blinks"""
    face = face_motion()
    a, z = frames
    lid = [key("まばたき", 0, 1.0), key("まばたき", 100, 1.0), key("まばたき", 102, 0.26), key("まばたき", a - 5, 0.26),
           key("まばたき", a, 0.0), key("まばたき", z + 5, 0.0), key("まばたき", z + 10, 0.26)]
    face.morphs = [k for k in face.morphs if k.name not in ("笑い", "まばたき")] + lid + [
        key("笑い", 0, 0.0), key("笑い", a, 0.0), key("笑い", a + 5, weight), key("笑い", z, weight), key("笑い", z + 5, 0.0)]
    return face


class SmileTest(unittest.TestCase):
    """human style: the lid that follows the eyes down never shuts a smiling eye between the blinks (まばたき + 笑い at
    most CLOSURE_CAP, or the author's); a blink comes about 20 frames before a smile falls (Trutoiu 2014)"""

    def test_looking_down_in_a_broad_smile_leaves_the_eye_open(self):
        result = face_life.plan(inputs(face=smiling_face(), eyes=pitched_eyes([(900, 1100, -10.0)])), seed=0)
        t = tracks(result.motion)
        b, s = t["まばたき"], t["笑い"]
        mask = between_blinks(b, s)
        frames = [f for f in range(905, 1095) if mask[f]]
        self.assertTrue(frames)
        self.assertLessEqual(float((b + s)[frames].max()), face_life.CLOSURE_CAP + 1e-6)
        self.assertGreater(result.report["blink"]["lid"]["frames_capped_for_the_smile"], 0)

    def test_a_blink_comes_about_21_frames_before_the_smile_has_fallen(self):
        # Trutoiu (2014, 5.3): blinks come 21 frames on average before a smile's offset, the last frame the lip corners
        # move (by chance 38); the smile here falls from 1300 on, over the human style's offset of 15 to 20 frames
        hits = 0
        for seed in range(6):
            result = face_life.plan(inputs(face=smiling_face()), seed=seed)
            s = tracks(result.motion)["笑い"]
            end = max(g for g in range(1290, 1400) if s[g - 1] - s[g] > 0.005)
            starts = [x["start"] for x in result.report["blink"]["new"]["list"] if x["cause"] == "smile_end"]
            hits += len(starts)
            for f in starts:
                self.assertTrue(18 <= end - f <= 24, (seed, f, end))
        self.assertGreaterEqual(hits, 2)


class SmileBreathesTest(unittest.TestCase):
    """human style: a held smile eases off and comes back by up to HUMAN_WAVE["eye"] of its weight (within a fifth a
    held face is not taken for a new one; v7 moved it by up to 12 %)"""

    def test_a_long_smile_moves_more_but_never_by_more_than_a_fifth(self):
        def spread(style):
            s = tracks(face_life.plan(inputs(face=smiling_face()), seed=0, style=style).motion)["笑い"][830:1270]
            return s.min(), s.max()
        lo, hi = spread("human")
        lo7, hi7 = spread("v7")
        self.assertGreaterEqual(lo, (1.0 - face_life.HUMAN_WAVE["eye"]) * hi - 1e-6)
        self.assertGreater((hi - lo) / hi, 1.3 * (hi7 - lo7) / hi7)


class FlashQuietTest(unittest.TestCase):
    def test_no_blink_starts_about_a_flash(self):
        moves, sign = [], 1.0
        for f in range(240, 1700, 25):
            moves.append((f, 5, (3.0 * sign, 0.0, 0.0)))
            sign = -sign
        result = face_life.plan(inputs(parts={"右手首": moving_point(moves)}, lines=[(8.0, 57.0)]), seed=0)
        flashes = result.report["blink"]["flashes"]
        starts = [x["start"] for x in result.report["blink"]["new"]["list"]]
        self.assertTrue(flashes and starts)
        for k in flashes:
            near = [f for f in starts if k - face_life.FLASH_QUIET[0] <= f <= k + face_life.FLASH_QUIET[1]]
            self.assertEqual(near, [], (k, near))


class FlashClashTest(unittest.TestCase):
    """(review of face-v2) a blink that started before the quiet window (a long one lasts longer than it) must not run
    into a flash: the eye would open from the blink straight to its widest.  And no minute has more flashes than
    FLASH_RATE, not only the song on average"""

    def test_no_blink_runs_into_a_flash(self):
        clashes = []
        for seed in range(8):
            moves, sign = [], 1.0
            for f in range(240, 1700, 25):
                moves.append((f, 5, (3.0 * sign, 0.0, 0.0)))
                sign = -sign
            result = face_life.plan(inputs(face=phrased_face(), parts={"右手首": moving_point(moves)},
                                           lines=[(8.0, 57.0)]), seed=seed)
            t = tracks(result.motion)
            c = t["まばたき"] + t["笑い"]
            for k in result.report["blink"]["flashes"]:
                if c[k - 6:k + 9].max() >= 0.8:
                    clashes.append((seed, k))
        self.assertEqual(clashes, [])

    def test_no_minute_has_more_flashes_than_the_rate(self):
        accents = [{"frame": f, "speed": 30.0 + (f % 7), "part": "右手首"} for f in range(100, 1800, 70)]
        accents += [{"frame": f, "speed": 40.0, "part": "右手首"} for f in range(1900, 5400, 400)]
        chosen = face_life.choose_flashes(accents, np.ones(5400, bool), 5400, 0)
        self.assertGreater(len(chosen), 8)
        window = int(60 * face_life.FPS)
        most = max(sum(1 for g in chosen if f <= g < f + window) for f in range(0, 5400, 10))
        self.assertLessEqual(most, face_life.FLASH_RATE, chosen)


class HumanReportTest(unittest.TestCase):
    """the report gives the half-closed eye (a10's: まばたき 0.2 or more between the blinks) before and after, and after
    without what the lid follows the eyes by; the kimes and the changes of the face that land on one"""

    @classmethod
    def setUpClass(cls):
        cls.result = face_life.plan(inputs(parts={"右手首": moving_point([(403, 5, (3.0, 0.0, 0.0))])},
                                           eyes=pitched_eyes([(700, 790, -8.0)])), seed=0)
        cls.report = cls.result.report

    def test_half_closed_eyes_before_and_after(self):
        lid = self.report["blink"]["lid"]
        t = tracks(self.result.motion)
        mask = between_blinks(t["まばたき"], t["笑い"], start=self.report["intro"]["eyes_open"] + 30)
        own = float((t["まばたき"][mask] >= 0.2).mean())
        self.assertAlmostEqual(lid["half_eye"]["new"], own, delta=0.03)
        self.assertGreater(lid["half_eye"]["before"], 0.9)
        self.assertLessEqual(lid["half_eye_without_the_gaze"], lid["half_eye"]["new"])

    def test_the_kimes_and_the_changes_on_them(self):
        k = self.report["expression"]["kimes"]
        self.assertEqual(k["found"], 1)
        self.assertEqual(k["changes_on_one"], 1)
        json.dumps(self.report)


class BlinkShapeTest(unittest.TestCase):
    def test_every_v7_shape_is_7_to_10_frames_and_opens_slower_than_it_closes(self):
        seen = set()
        for closing in face_life.CLOSING_FRAMES:
            for hold in face_life.HOLD_FRAMES:
                for opening in face_life.OPENING_FRAMES:
                    profile = face_life.blink_profile(closing, hold, opening)
                    self.assertEqual(len(profile), closing + hold + opening + 1)
                    self.assertEqual((profile[0], profile[-1]), (0.0, 0.0))
                    self.assertEqual(max(profile), 1.0)
                    self.assertTrue(7 <= closing + hold + opening <= 10)
                    self.assertGreater(opening, closing)
                    falling = np.diff(profile[closing + hold:])
                    self.assertTrue(np.all(falling < 0))
                    self.assertTrue(np.all(np.diff(falling) > 0))      # fast first, slow at the end
                    seen.add(closing + hold + opening)
        self.assertGreaterEqual(len(seen), 3)


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = face_life.plan(inputs(), seed=0)
        cls.t = tracks(cls.result.motion)

    def test_no_bone_keys_and_every_input_morph_is_kept(self):
        self.assertEqual(self.result.motion.bones, [])
        self.assertTrue({"ウィンク", "あ", "まばたき", "真面目"} <= set(self.t))

    def test_the_lid_no_longer_creeps_between_blinks(self):
        b = self.t["まばたき"]
        step = np.diff(b, prepend=b[0])
        creep = (step > 1e-5) & (step <= 0.05)
        creep[:150] = False
        runs = face_life.runs(creep)
        self.assertEqual([r for r in runs if r[1] - r[0] + 1 >= 10], [])

    def test_blinks_are_not_one_template_and_last_7_to_11_frames(self):
        blinks = self.result.report["blink"]["new"]["list"]
        self.assertGreater(len(blinks), 8)
        shapes = {(b["closing"], b["hold"], b["opening"]) for b in blinks}
        self.assertGreater(len(shapes), 1)
        t = self.t
        lengths = [z - a for a, _, _, z in shut_runs(t["まばたき"], t["笑い"], longest=8)]
        self.assertTrue(lengths and all(7 <= n <= 11 for n in lengths), lengths)

    def test_a_quick_head_swing_mostly_brings_a_blink(self):
        starts = [b["start"] for b in self.result.report["blink"]["new"]["list"]]
        hit = [any(t - 3 <= s <= t + 9 for s in starts) for t in TURNS]
        self.assertGreaterEqual(sum(hit), 2)

    def test_the_eyes_open_before_the_body_moves(self):
        b = self.t["まばたき"]
        opened = int(np.argmax(b < 0.5))
        self.assertLess(opened, 150)
        self.assertGreater(opened, 60)
        self.assertEqual(self.result.report["intro"]["eyes_open"], opened)
        self.assertEqual(self.result.report["intro"]["body_start"], 150)

    def test_the_peak_of_a_blink_inside_a_smile_is_one_minus_the_smile(self):
        b, s = self.t["まばたき"], self.t["笑い"]
        for bl in self.result.report["blink"]["new"]["list"]:
            f = bl["start"] + bl["closing"]
            if s[f] > 0.1:
                self.assertAlmostEqual(b[f] + s[f], 1.0, places=2)

    def test_expression_changes_take_10_frames_or_more(self):
        keys = sorted((k.frame, k.weight) for k in self.result.motion.morphs if k.name == "真面目")
        ramps = [(f1 - f0) for (f0, w0), (f1, w1) in zip(keys, keys[1:]) if abs(w1 - w0) > 0.3]
        self.assertEqual(len(ramps), 2)
        self.assertTrue(all(r >= 10 for r in ramps), ramps)

    def test_a_long_hold_is_never_flat(self):
        for name in ("真面目", "下", "笑い"):
            keys = sorted((k.frame, k.weight) for k in self.result.motion.morphs if k.name == name)
            for (f0, w0), (f1, w1) in zip(keys, keys[1:]):
                if w0 > 0.05:
                    self.assertNotAlmostEqual(w0, w1, places=6, msg=(name, f0, f1))
                    self.assertLess(f1 - f0, 4 * FPS)
            w = self.t[name]
            self.assertLessEqual(w.max(), 1.0)
            self.assertGreater(w.max(), 0.4)

    def test_brows_lead_and_the_eyes_follow(self):
        def start(name):
            w = self.t[name]
            return int(np.argmax(w > 0.02))
        self.assertLess(start("真面目"), start("口角下げ") + 1)
        smile = self.t["笑い"]
        corners = self.t["口角上げ"]
        self.assertLess(int(np.argmax(corners > 0.02)), int(np.argmax(smile > 0.02)))
        self.assertGreater(corners[1300], 0.2)

    def test_vowel_onsets_keep_their_frames(self):
        lip = face_life.load_lip_timing()
        before = [(o.frame, o.vowel) for o in lip.onsets(face_motion())]
        after = [(o.frame, o.vowel) for o in lip.onsets(self.result.motion)]
        self.assertEqual(before, after)

    def test_the_vowels_never_add_up_to_more_than_one(self):
        s = sum(self.t[v] for v in "あいうえお")
        self.assertLessEqual(s.max(), 1.0 + 1e-6)

    def test_crossfades_and_the_lip_closure_take_two_frames_or_more(self):
        a, o = self.t["あ"], self.t["お"]
        s = sum(self.t[v] for v in "あいうえお")
        shut = [f for f in range(615, 627) if s[f] < 0.05]
        self.assertTrue(shut)                                   # the lips still close for m
        self.assertLessEqual(abs(np.mean(shut) - 624.5), 1.0)   # around the same time
        self.assertGreater(o[626], 0.05)                        # opening: frame 625 or 626 is half way
        self.assertLess(o[626], o[627])
        self.assertTrue(0.05 < a[shut[0] - 1] < a[614])         # closing: not 1 frame from full to shut
        i = self.t["い"]
        self.assertTrue(0.05 < i[605] < i[607] and 0.05 < i[606])

    def test_the_mouth_breathes_where_nothing_is_sung(self):
        a = self.t["あ"]
        quiet = a[1000:1500]
        self.assertGreater(quiet.max(), 0.04)
        self.assertLessEqual(quiet.max(), 0.21)
        still = np.abs(np.diff(quiet)) < 1e-6
        self.assertLess(still.mean(), 0.2)

    def test_the_eyes_never_close_further_than_the_author_closed_them(self):
        before = tracks(face_motion())
        b, s = self.t["まばたき"], self.t["笑い"]
        allowed = np.maximum(1.0, before["まばたき"] + before["笑い"])
        self.assertLessEqual(float((b + s - allowed)[150:].max()), 1e-6)

    def test_a_held_vowel_eases_off(self):
        a = self.t["あ"]
        held = a[614:621]
        self.assertTrue(np.all(np.diff(held) < 0), held)
        self.assertGreater(held[-1], 0.85 * held[0])

    def test_no_onset_is_added(self):
        lip = face_life.load_lip_timing()
        before = {(o.frame, o.vowel) for o in lip.onsets(face_motion())}
        after = {(o.frame, o.vowel) for o in lip.onsets(self.result.motion)}
        self.assertEqual(after - before, set())
        self.assertEqual(self.result.report["mouth"]["new"]["onsets_added"], 0)

    def test_a_breath_between_phrases_does_not_open_shut_lips(self):
        s = sum(self.t[v] for v in "あいうえお")
        self.assertLess(float(s[660:672].min()), 0.05)

    def test_the_report_has_before_and_after(self):
        r = self.result.report
        for part in ("expression", "blink", "mouth"):
            self.assertIn("before", r[part])
            self.assertIn("new", r[part])
        json.dumps(r)


class SeedTest(unittest.TestCase):
    def test_the_same_seed_gives_the_same_file_and_another_seed_another(self):
        a = vmd.dumps(face_life.plan(inputs(), seed=3).motion)
        b = vmd.dumps(face_life.plan(inputs(), seed=3).motion)
        c = vmd.dumps(face_life.plan(inputs(), seed=4).motion)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class WakeUpTest(unittest.TestCase):
    def test_eyes_that_open_after_the_body_starts_open_before_it(self):
        result = face_life.plan(inputs(body_start=60), seed=0)
        b = tracks(result.motion)["まばたき"]
        self.assertLess(int(np.argmax(b < 0.5)), 60)
        self.assertEqual(result.report["intro"]["moved_by"], 60 - face_life.LEAD - 102)


class BlinkRateTest(unittest.TestCase):
    def test_a_restless_gaze_does_not_make_her_blink_too_often(self):
        yaw = np.zeros(F)
        gaps = (37, 71, 52, 89, 44, 63, 58, 76)                          # about 2 s apart (30 a minute), unevenly
        starts = [200]
        while starts[-1] + 100 < F:
            starts.append(starts[-1] + gaps[len(starts) % len(gaps)])
        for i, start in enumerate(starts):
            target = 40.0 if i % 2 == 0 else 0.0
            yaw[start:start + 6] = np.linspace(yaw[start - 1], target, 7)[1:]
            yaw[start + 6:] = target
        head = np.zeros((F, 4))
        head[:, 1], head[:, 3] = np.sin(np.radians(yaw) / 2), np.cos(np.radians(yaw) / 2)
        for style in face_life.STYLES:
            result = face_life.plan(inputs(head=head), seed=0, style=style)
            new = result.report["blink"]["new"]
            minutes = (F - result.report["intro"]["eyes_open"]) / FPS / 60.0
            self.assertLessEqual(new["blinks"] / minutes, face_life.RATE + 0.5, style)      # the author's long closures aside
            self.assertLessEqual(new["most_in_10s"], face_life.WINDOW_MAX, style)
            self.assertGreater(new["gaze_shift_33"]["observed"], new["gaze_shift_33"]["chance_p97.5"], style)


class GroupingTest(unittest.TestCase):
    def test_changes_within_four_frames_are_one_change_of_the_face(self):
        keys = {"真面目": [(0, 0.0), (400, 0.0), (405, 1.0)], "笑い": [(0, 0.0), (403, 0.0), (408, 0.5)],
                "困る": [(0, 0.0), (700, 0.0), (705, 1.0)], "怒り": [(0, 0.0), (710, 0.0), (715, 0.5)]}
        speed = np.zeros(F)
        for seed in range(5):
            out, events, stretched = face_life.rewrite_expressions(keys, [(0, 0.5), (F - 1, 0.5)], speed, F,
                                                                    random.Random(seed),
                                                                    lambda n: n not in ("口角上げ", "口角下げ"))
            members = [sorted(n for n, _ in e["members"]) for e in events]
            self.assertIn(sorted(["真面目", "笑い"]), members)
            self.assertIn(["困る"], members)
            self.assertIn(["怒り"], members)
            length = {n: e - s for n, s, e in stretched}
            self.assertEqual(length["真面目"], length["笑い"])
            start = {n: s for n, s, e in stretched}
            self.assertGreaterEqual(start["笑い"] - start["真面目"], 3 + face_life.DELAY["eye"][0])


class DanceKeysTest(unittest.TestCase):
    def test_the_dances_own_face_keys_are_overridden_on_their_frames(self):
        dance = [("まばたき", 258), ("まばたき", 277), ("まばたき", 1201), ("真面目", 0), ("ﾏﾆｷｭｱ", 0)]
        result = face_life.plan(inputs(dance_morph_keys=dance), seed=0)
        merged = {}
        for name, frame in dance:
            merged.setdefault(name, {})[frame] = 0.777                 # what the dance would put there
        for k in result.motion.morphs:                                  # the face motion is loaded after the dance
            merged.setdefault(k.name, {})[k.frame] = k.weight
        alone = tracks(result.motion)
        for name in ("まばたき", "真面目"):
            d = merged[name]
            fr = sorted(d)
            both = np.interp(np.arange(F), fr, [d[f] for f in fr])
            np.testing.assert_allclose(both, alone[name], atol=1e-6)
        self.assertNotIn("ﾏﾆｷｭｱ", alone)


class HoldTest(unittest.TestCase):
    # --hold NAME=WEIGHT: a morph the face motion does not animate, kept at one weight over the whole song (Sour's
    # Rin: 瞳1off shows the dark pupil, HL２ the catchlight; both are 0 when nothing keys them)

    def test_a_held_morph_stays_at_its_weight_on_every_frame(self):
        result = face_life.plan(inputs(), seed=0, hold={"瞳1off": 1.0, "HL２": 0.5})
        t = tracks(result.motion)
        np.testing.assert_allclose(t["瞳1off"], 1.0)
        np.testing.assert_allclose(t["HL２"], 0.5)
        self.assertEqual(result.report["held"], {"瞳1off": 1.0, "HL２": 0.5})

    def test_holding_changes_nothing_else(self):
        plain = tracks(face_life.plan(inputs(), seed=0).motion)
        held = tracks(face_life.plan(inputs(), seed=0, hold={"瞳1off": 1.0}).motion)
        self.assertEqual(set(held) - set(plain), {"瞳1off"})
        for name, track in plain.items():
            np.testing.assert_array_equal(held[name], track)

    def test_a_held_morph_also_wins_on_the_frames_the_dance_keys_it(self):
        dance = [("瞳1off", 0), ("瞳1off", 400)]
        result = face_life.plan(inputs(dance_morph_keys=dance), seed=0, hold={"瞳1off": 1.0})
        merged = {f: 0.0 for _, f in dance}                             # what the dance puts there
        for k in result.motion.morphs:                                  # the face motion is loaded after the dance
            if k.name == "瞳1off":
                merged[k.frame] = k.weight
        fr = sorted(merged)
        np.testing.assert_allclose(np.interp(np.arange(F), fr, [merged[f] for f in fr]), 1.0)

    def test_a_morph_the_model_lacks_cannot_be_held(self):
        with self.assertRaisesRegex(ValueError, "瞳1off"):
            face_life.plan(inputs(morphs={"まばたき", "あ"}), seed=0, hold={"瞳1off": 1.0})

    def test_a_morph_the_face_motion_animates_cannot_be_held(self):
        with self.assertRaisesRegex(ValueError, "まばたき"):
            face_life.plan(inputs(), seed=0, hold={"まばたき": 0.0})

    def test_a_morph_the_tool_itself_animates_cannot_be_held(self):
        # 口角上げ has only a 0 key in the face motion, but the tool adds it under 笑い (review of 366de78, 1)
        with self.assertRaisesRegex(ValueError, "口角上げ"):
            face_life.plan(inputs(), seed=0, hold={"口角上げ": 0.3})

    def test_blinks_the_tool_makes_from_zero_keys_cannot_be_held(self):
        face = face_motion()
        face.morphs = [vmd.MorphKey(k.name, k.frame, 0.0) if k.name == "まばたき" else k for k in face.morphs]
        with self.assertRaisesRegex(ValueError, "まばたき"):
            face_life.plan(inputs(face=face), seed=0, hold={"まばたき": 0.0})

    def test_a_morph_keyed_only_at_0_is_held_with_exactly_its_two_keys(self):
        result = face_life.plan(inputs(), seed=0, hold={"ウィンク": 0.4})
        keys = sorted((k.frame, k.weight) for k in result.motion.morphs if k.name == "ウィンク")
        self.assertEqual(keys, [(0, 0.4), (F - 1, 0.4)])

    def test_a_half_width_name_points_to_the_full_width_morph(self):
        with self.assertRaisesRegex(ValueError, "HL２"):
            face_life.plan(inputs(morphs={"HL２", "まばたき", "あ"}), seed=0, hold={"HL2": 1.0})

    def test_the_command_passes_the_held_morphs_on_and_refuses_a_bad_one(self):
        argv = ["f.vmd", "d.vmd", "g.vmd", "m.pmx", "o.vmd"]
        with mock.patch.object(face_life, "run", return_value={}) as run, mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(face_life.main(argv + ["--hold", "瞳1off=1", "--hold", "HL２=0.5"]), 0)
            self.assertEqual(run.call_args.args[-1], {"瞳1off": 1.0, "HL２": 0.5})
            self.assertEqual(face_life.main(argv), 0)
            self.assertEqual(run.call_args.args[-1], {})
            run.reset_mock()
            self.assertEqual(face_life.main(argv + ["--hold", "HL２"]), 2)
            run.assert_not_called()

    def test_the_option_is_name_equals_weight_from_0_to_1(self):
        self.assertEqual(face_life.parse_hold(["瞳1off=1", "HL２=0.25"]), {"瞳1off": 1.0, "HL２": 0.25})
        self.assertEqual(face_life.parse_hold(None), {})
        for bad in (["瞳1off"], ["=1"], ["瞳1off=x"], ["瞳1off=1.5"], ["瞳1off=-0.1"], ["瞳1off=1", "瞳1off=0.5"]):
            with self.assertRaises(ValueError, msg=bad):
                face_life.parse_hold(bad)


class SaccadeTest(unittest.TestCase):
    def test_quick_eye_turns_are_found_and_slow_ones_are_not(self):
        eyes = still_eyes()
        yaw = np.zeros(F)
        yaw[300:303] = [8.0, 16.0, 24.0]
        yaw[303:] = 24.0
        yaw[600:700] = np.linspace(24.0, 0.0, 100)       # slow: 0.24 degrees a frame (a counter-rotation)
        yaw[700:] = 0.0
        eyes[:, 1] = np.sin(np.radians(yaw) / 2)
        eyes[:, 3] = np.cos(np.radians(yaw) / 2)
        head = still_eyes()
        found = face_life.saccades(head, eyes)
        self.assertEqual([(s["start"], round(s["amplitude"])) for s in found], [(300, 24)])


def real_file(*parts):
    """a file of the real song under _spike/ of this tree, of a tree up to 3 folders above it (a worktree), or of
    MMD_CLI_DATA (a folder holding _spike/: a copy of the tree kept away from the data, as on the render machine)"""
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


def rin_path():
    """Sour's Rin: MMD_CLI_RIN when set, else the model folder of MMD under the user's Desktop (a fixed path of one
    machine skipped the real tests on another without a word: review gaze-smooth 13)"""
    rel = os.path.join("MikuMikuDance_v932x64", "UserFile", "Model", "Sour式鏡音リンVer.2.01", "White.pmx")
    for path in (os.environ.get("MMD_CLI_RIN"), os.path.join(os.path.expanduser("~"), "Desktop", rel)):
        if path and os.path.isfile(path):
            return path
    return None


SPIKE = ("_spike", "out", "hibikase")
REAL_FACE = real_file(*SPIKE, "kazusa", "ヒビカセ（Choreography by ATY）", "ヒビカセ　Face&Lips 歌ってる方.vmd")
REAL_DANCE = real_file(*SPIKE, "variants", "dance_final_dn6_twist.vmd")
REAL_GAZE = real_file(*SPIKE, "variants", "gaze_final_dn6.vmd")
REAL_CUES = real_file(*SPIKE, "mv", "production", "cues_mv.json")
REAL_AUDIO = real_file(*SPIKE, "audio", "hibikase_yt_TkroHwQYpFE.webm")
RIN = rin_path()
REAL = all((REAL_FACE, REAL_DANCE, REAL_GAZE, REAL_CUES, REAL_AUDIO, RIN))


@unittest.skipUnless(REAL, "the KAZUSA face motion, the dance, the gaze, the cues, the sound or Rin is not here")
class RealSongTest(unittest.TestCase):
    dance, gaze = REAL_DANCE, REAL_GAZE

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.out = os.path.join(cls.folder, "face.vmd")
        cls.report_path = os.path.join(cls.folder, "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = face_life.main([REAL_FACE, cls.dance, cls.gaze, RIN, cls.out, "--audio", REAL_AUDIO,
                                       "--cues", REAL_CUES, "--report", cls.report_path, "--seed", "0"])
        with open(cls.report_path, encoding="ascii") as f:
            cls.report = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, True)

    def test_it_runs_and_writes_a_face_motion_only(self):
        self.assertEqual(self.code, 0)
        back = vmd.load(self.out)
        self.assertEqual(back.bones, [])
        self.assertEqual(back.model_name, vmd.load(REAL_FACE).model_name)

    def test_the_before_numbers_are_the_analysts(self):
        e, b, m = (self.report[p]["before"] for p in ("expression", "blink", "mouth"))
        self.assertEqual(e["ramp_frames"]["median"], 5.0)
        self.assertAlmostEqual(e["per_morph"]["真面目"]["plateau_share_of_active"], 0.84, places=2)
        self.assertEqual(b["blinks"], 102)
        self.assertEqual(b["creep"]["runs"], 58)
        self.assertAlmostEqual(m["onset_weight_eq1"], 0.987, places=3)

    def test_the_targets(self):
        e, b, m = (self.report[p]["new"] for p in ("expression", "blink", "mouth"))
        self.assertGreaterEqual(e["ramp_frames"]["median"], 10)
        self.assertGreaterEqual(e["transition_frames"]["median"], 10)
        for name, row in e["per_morph"].items():
            if row["active_frames"]:
                self.assertLess(row["plateau_share_of_active"], 0.30, name)
                self.assertLess(row["longest_plateau_s"], 4.0, name)
        self.assertEqual(b["creep"]["runs"], 0)
        self.assertGreater(len(b["shapes"]), 1)
        self.assertGreaterEqual(b["gaze_shift_33"]["observed"], 0.5)
        self.assertGreater(b["gaze_shift_33"]["observed"], b["gaze_shift_33"]["chance_p97.5"])
        self.assertGreater(b["ibi"]["skew"], 0.5)
        self.assertTrue(10.0 <= b["rate_per_min"] <= 32.5)
        self.assertLess(m["onset_weight_eq1"], 0.5)
        self.assertLessEqual(m["sum_max"], 1.0 + 1e-6)
        self.assertEqual(m["onsets_moved"], 0)
        self.assertEqual(m["onsets_added"], 0)
        self.assertLessEqual(b["most_in_10s"], face_life.WINDOW_MAX)
        self.assertLessEqual(b["closure_over_the_author"], 1e-6)
        self.assertLess(m["outside_still_share"], 0.53)
        self.assertLess(self.report["intro"]["eyes_open"], self.report["intro"]["body_start"])
        lag = self.report["mouth"]["lag_ms"]
        self.assertEqual(lag["before"], lag["new"])

    def test_the_human_targets(self):
        lid = self.report["blink"]["lid"]
        # a10's count takes the lid that follows the eyes down (the cover kept) for a half-closed eye too
        self.assertLess(lid["half_eye"]["new"], 0.55 * lid["half_eye"]["before"])
        self.assertLess(lid["half_eye_without_the_gaze"], 0.1)
        minutes = (self.report["frames"][1] + 1) / 30.0 / 60.0
        flashes = self.report["blink"]["flashes"]
        self.assertTrue(0 < len(flashes) <= face_life.FLASH_RATE * minutes + 1, flashes)
        self.assertGreater(self.report["blink"]["long_blinks"], 0)
        self.assertGreater(self.report["expression"]["kimes"]["found"], 0)
        self.assertEqual(self.report["style"], "human")


STAGE_DANCE = real_file("_spike", "out", "stage1", "breath", "dance_v3_breath.vmd")
STAGE_GAZE = real_file("_spike", "out", "stage1", "eye", "gaze_v3_on_v2dance.vmd")


@unittest.skipUnless(REAL and STAGE_DANCE and STAGE_GAZE, "the stage-1 dance (breath) or gaze (eye) is not here")
class StageOneInputsTest(RealSongTest):
    """the same checks on the inputs of stage 1: the dance with breathing and the new, more restless gaze"""
    dance, gaze = STAGE_DANCE, STAGE_GAZE

    def test_the_before_numbers_are_the_analysts(self):
        """the analysts measured the MV's inputs, not these"""


if __name__ == "__main__":
    unittest.main()
