"""tools/face_life.py: the face motion (expressions, blinks, mouth) rewritten to move more like a person's."""
import contextlib
import importlib.util
import io
import json
import random
import os
import shutil
import tempfile
import unittest

import numpy as np

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


class BlinkShapeTest(unittest.TestCase):
    def test_every_shape_is_7_to_10_frames_and_opens_slower_than_it_closes(self):
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

    def test_blinks_are_not_one_template_and_last_7_to_10_frames(self):
        blinks = self.result.report["blink"]["new"]["list"]
        self.assertGreater(len(blinks), 8)
        shapes = {(b["closing"], b["hold"], b["opening"]) for b in blinks}
        self.assertGreater(len(shapes), 1)
        for b in blinks:
            self.assertTrue(7 <= b["closing"] + b["hold"] + b["opening"] <= 10)

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
        result = face_life.plan(inputs(head=head), seed=0)
        new = result.report["blink"]["new"]
        self.assertLessEqual(new["rate_per_min"], face_life.RATE + 1.0)
        self.assertLessEqual(new["most_in_10s"], face_life.WINDOW_MAX)
        self.assertGreater(new["gaze_shift_33"]["observed"], new["gaze_shift_33"]["chance_p97.5"])


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
    folder = ROOT
    for _ in range(4):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        folder = os.path.dirname(folder)
    return None


SPIKE = ("_spike", "out", "hibikase")
REAL_FACE = real_file(*SPIKE, "kazusa", "ヒビカセ（Choreography by ATY）", "ヒビカセ　Face&Lips 歌ってる方.vmd")
REAL_DANCE = real_file(*SPIKE, "variants", "dance_final_dn6_twist.vmd")
REAL_GAZE = real_file(*SPIKE, "variants", "gaze_final_dn6.vmd")
REAL_CUES = real_file(*SPIKE, "mv", "production", "cues_mv.json")
REAL_AUDIO = real_file(*SPIKE, "audio", "hibikase_yt_TkroHwQYpFE.webm")
RIN = "C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/Sour式鏡音リンVer.2.01/White.pmx"
REAL = all((REAL_FACE, REAL_DANCE, REAL_GAZE, REAL_CUES, REAL_AUDIO)) and os.path.isfile(RIN)


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
