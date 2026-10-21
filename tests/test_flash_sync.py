"""tools/flash_sync.py: the flashes of a look put on moments of the song a viewer hears (a strong hit of the backing at the
head of a section, at the band's return or where the title word is sung), or dropped; the punches on their frames on the title
words they stood for, as sung (not with the flashes).
Synthetic sounds only (the song itself is measured on hinata, its numbers are in the stage-6 notes)."""
import contextlib
import copy
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
except ImportError:                                   # the tool needs numpy; the rest of the suite does not
    np = None


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FS = load("flash_sync") if np is not None else None
ML = load("mograph_layer") if np is not None else None
FFMPEG = shutil.which("ffmpeg")
SR = 22050
FIRST, PERIOD = 0.01593, 0.4285714


def burst(n, rng, decay=0.02, sr=SR):
    """a drum-like hit: a decaying noise burst of n samples"""
    return rng.standard_normal(n) * np.exp(-np.arange(n) / (decay * sr))


def tone(seconds, f0=220.0, sr=SR, attack=0.004):
    """a sung vowel: a harmonic tone (F0 and 7 harmonics) with a short attack"""
    t = np.arange(int(seconds * sr)) / float(sr)
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8))
    env = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / 0.01)
    return x * env


FORMANTS = {"i": (300.0, 2300.0), "u": (350.0, 1300.0), "e": (500.0, 1900.0), "a": (800.0, 1250.0), "o": (550.0, 900.0)}


def vowel(seconds, kind, f0=200.0, sr=SR, attack=0.0005):
    """a sung vowel of `kind` (i u e a o): a harmonic tone shaped by two formants, with a short attack"""
    f1, f2 = FORMANTS[kind]
    t = np.arange(int(seconds * sr)) / float(sr)
    x = np.zeros_like(t)
    for k in range(1, 20):
        f = f0 * k
        amp = np.exp(-((f - f1) / 150.0) ** 2) + 0.6 * np.exp(-((f - f2) / 250.0) ** 2) + 0.02
        x += amp * np.sin(2 * np.pi * f * t)
    env = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / 0.01)
    return x * env


def put(x, at, piece, sr=SR):
    i = int(round(at * sr))
    x[i:i + len(piece)] += piece[:max(0, len(x) - i)]


def write_wav(path, x, scale, sr=SR):
    """x times scale as 16 bit (one scale for the files of one song: the mix stays the backing plus the voice)"""
    y = np.clip(x * scale, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


# ---- the clock and the hits ---------------------------------------------------------------------------------------

@unittest.skipUnless(FS, "needs numpy")
class HitTest(unittest.TestCase):
    def test_hits_are_found_on_their_onsets_and_ordered_by_their_strength(self):
        rng = np.random.default_rng(11)
        x = 0.0005 * rng.standard_normal(SR * 6)
        onsets = [0.7311, 1.6047, 2.4163, 3.3398, 4.2522, 5.1117]
        hit = burst(int(0.12 * SR), rng)                     # one hit, each time twice as loud
        for k, t0 in enumerate(onsets):
            put(x, t0, 0.02 * 2 ** k * hit)
        times, env = FS.onset_envelope(x)
        hits = FS.hits_of(times, env)
        found = []
        for t0 in onsets:
            near = [h for h in hits if abs(h["t"] - t0) < 0.03]
            self.assertTrue(near, "no hit near %.4f" % t0)
            found.append(max(near, key=lambda h: h["height"]))
        for t0, h in zip(onsets, found):
            self.assertLess(abs(h["t"] - t0), 0.005, "the hit at %.4f is read at %.4f" % (t0, h["t"]))
        heights = [h["height"] for h in found]
        self.assertEqual(heights, sorted(heights))

    def test_the_strongest_hit_near_a_time_and_its_place_among_the_songs_hits(self):
        hits = FS.Hits([{"t": t, "height": h} for t, h in ((1.0, 1.0), (1.1, 5.0), (1.2, 2.0), (1.3, 9.0), (5.0, 3.0))])
        near = hits.strongest(1.12, 2 / 30.0)
        self.assertEqual(near["t"], 1.1)
        self.assertEqual(near["pct"], 60.0)                # 3 of the 5 hits are weaker
        self.assertEqual(hits.strongest(1.3, 0.001)["pct"], 80.0)
        self.assertIsNone(hits.strongest(3.0, 2 / 30.0))
        # the local measure: its height over the median of the hits within LOCAL seconds of it
        self.assertAlmostEqual(hits.strongest(1.3, 0.001)["local"], 9.0 / 3.5)

    def test_the_backing_is_the_mix_less_the_voice_found_at_its_lag(self):
        rng = np.random.default_rng(5)
        voice = rng.standard_normal(SR * 4)
        backing = rng.standard_normal(SR * 4)
        mix = backing + FS.shifted(voice, 41)
        self.assertEqual(FS.align(mix, voice), 41)
        self.assertEqual(FS.align(backing + FS.shifted(voice, -17), voice), -17)
        out = FS.backing_of(mix, voice, 41)
        self.assertLess(float(np.abs(out[100:-100] - backing[100:-100]).max()), 1e-9)


    def test_a_mix_of_another_source_is_found_where_its_backing_lies(self):
        # (another singer's version: the same backing, maybe a lead-in of its own) the lag of the mixes' onsets
        rng = np.random.default_rng(9)
        ref = 0.001 * rng.standard_normal(SR * 12)
        hit = burst(int(0.1 * SR), rng)
        for k in range(40):
            put(ref, 0.5 + 0.27 * k + 0.05 * rng.random(), (0.1 + rng.random()) * hit)
        same = ref + 0.02 * rng.standard_normal(len(ref))               # another voice over the same backing
        lag, r = FS.mix_lag(same, ref)
        self.assertLess(abs(lag), 0.008)                             # (a guard at a frame: a quarter of one)
        self.assertGreater(r, 0.8)
        later = np.concatenate([0.001 * rng.standard_normal(int(0.31 * SR)), ref])[:len(ref)]
        lag, r = FS.mix_lag(later, ref)
        self.assertLess(abs(lag - 0.31), 0.008)


# ---- the voice ----------------------------------------------------------------------------------------------------

@unittest.skipUnless(FS, "needs numpy")
class SyllableTest(unittest.TestCase):
    def voice(self, onset, previous_end=None, hiss=None, seconds=3.0):
        rng = np.random.default_rng(2)
        x = 0.003 * rng.standard_normal(int(seconds * SR))
        if previous_end is not None:
            put(x, previous_end - 0.4, tone(0.4, 247.0))
        if hiss is not None:
            # a breath of h: noise high in the spectrum (three differences of white noise), little of it in the voiced band
            n = int((onset - hiss) * SR)
            put(x, hiss, 0.03 * np.diff(rng.standard_normal(n + 3), 3))
        if onset is not None:
            put(x, onset, tone(0.3, 262.0, attack=0.0005))       # a vowel that comes in at once: its onset is a point
        return x

    def test_the_first_syllable_is_where_its_vowel_comes_in_a_sixteenth_before_the_beat(self):
        beat = 1.5
        x = self.voice(beat - 0.107, previous_end=beat - 0.28)
        t, db = FS.voice_level(x)
        got = FS.first_syllable(t, db, beat)
        self.assertIsNotNone(got)
        # where its power reaches half of the loudest after it: the onset itself for a step (a tenth would read 3 ms early)
        self.assertLess(abs(got["t"] - (beat - 0.107)), 0.0015, got)
        self.assertGreaterEqual(got["rise_db"], FS.SYLLABLE_RISE_DB)

    def test_a_breath_before_the_vowel_is_not_its_onset_and_an_early_one_is_still_found(self):
        beat = 1.5
        x = self.voice(beat - 0.16, previous_end=beat - 0.30, hiss=beat - 0.21)
        t, db = FS.voice_level(x)
        got = FS.first_syllable(t, db, beat)
        self.assertLess(abs(got["t"] - (beat - 0.16)), 0.0015, got)

    def sung(self, beat, word, before="a", lead=0.10, seconds=3.0):
        """a syllable of the word before (its vowel `before`) a sixteenth and a bit before the beat, then the title word's vowels
        one an eighth from the beat's eighth on (as the title words are sung in this song), a short stop before each"""
        rng = np.random.default_rng(4)
        x = 0.003 * rng.standard_normal(int(seconds * SR))
        eighth = PERIOD / 2.0
        put(x, beat - lead, vowel(lead + eighth - 0.04, before))
        for k, v in enumerate(word):
            put(x, beat + (k + 1) * eighth, vowel(eighth - 0.04, v))
        return x

    def test_the_title_word_is_the_run_of_its_vowels_not_the_syllable_before_it(self):
        beat = 1.2
        x = self.sung(beat, "iiae")
        sy = FS.syllables_of(x)
        got = FS.title_start(sy, beat, "iiae")
        self.assertIsNotNone(got)
        self.assertLess(abs(got["t"] - (beat + PERIOD / 2.0)), 0.006, got)          # the first i, an eighth after the beat
        self.assertEqual(len(got["run"]), 4)
        # the syllable before it (an open vowel just before the beat) is a syllable too, but not the word's first
        self.assertTrue(any(abs(t - (beat - 0.10)) < 0.01 for t in [y["t"] for y in sy]))
        # where the voice first comes in near the beat is that syllable: what the beat alone finds
        rise = FS.first_syllable(*FS.voice_level(x), beat)
        self.assertLess(abs(rise["t"] - (beat - 0.10)), 0.006)

    def test_a_word_sung_partly_legato_is_still_its_vowels_in_order(self):
        # (the second singer's title words 1 and 2: two syllables in the middle run on from the one before, no stop, no onset)
        beat = 1.2
        rng = np.random.default_rng(6)
        x = 0.003 * rng.standard_normal(int(3.0 * SR))
        eighth = PERIOD / 2.0
        put(x, beat - 0.10, vowel(0.10 + eighth - 0.04, "a"))
        put(x, beat + eighth, vowel(eighth - 0.04, "i"))
        put(x, beat + 2 * eighth, np.concatenate([vowel(eighth, "i", attack=0.01), vowel(eighth - 0.04, "a", attack=0.01)]))
        put(x, beat + 4 * eighth, vowel(eighth - 0.04, "e"))
        sy = FS.syllables_of(x)
        self.assertLess(len([y for y in sy if beat < y["t"] < beat + 5 * eighth]), 4)          # not every syllable comes in
        got = FS.title_start(sy, beat, "iiae")
        self.assertIsNotNone(got)
        self.assertLess(abs(got["t"] - (beat + eighth)), 0.006, got)
        # and a start one syllable late (the second i) matches fewer of the word's vowels: not taken
        self.assertGreaterEqual(len(got["run"]), 3)

    def test_the_title_word_is_the_one_round_its_beat_not_the_same_word_a_bar_before(self):
        beat = 2.2
        rng = np.random.default_rng(7)
        x = 0.003 * rng.standard_normal(int(4.0 * SR))
        eighth = PERIOD / 2.0
        for k, v in enumerate("iiae"):                                                  # the word sung once more, earlier
            put(x, beat - 1.6 + k * eighth, vowel(eighth - 0.04, v))
        for k, v in enumerate("iiae"):
            put(x, beat + (k + 1) * eighth, vowel(eighth - 0.04, v))
        got = FS.title_start(FS.syllables_of(x), beat, "iiae")
        self.assertLess(abs(got["t"] - (beat + eighth)), 0.006, got)

    def test_one_onset_a_syllable(self):
        # a short voiced blip 40 ms before the vowel (a consonant's voicing, a slur): two rises, one syllable
        rng = np.random.default_rng(8)
        x = 0.003 * rng.standard_normal(int(2.0 * SR))
        put(x, 0.80, vowel(0.015, "a"))
        put(x, 0.84, vowel(0.25, "i"))
        put(x, 1.30, vowel(0.25, "a"))
        sy = FS.syllables_of(x)
        times = [y["t"] for y in sy]
        self.assertTrue(all(b - a >= FS.SYLLABLE_APART for a, b in zip(times, times[1:])), times)
        self.assertEqual(len([t for t in times if 0.75 < t < 0.95]), 1, times)

    def legato(self, beat, parts, after=()):
        """the word before (an open vowel just before the beat), then the title word sung as `parts`: (eighths from the beat,
        vowels sung as one held run without a stop), then `after`: (eighths, vowel) of the next word"""
        rng = np.random.default_rng(10)
        x = 0.003 * rng.standard_normal(int(4.0 * SR))
        eighth = PERIOD / 2.0
        put(x, beat - 0.10, vowel(0.10 + eighth - 0.04, "a"))
        for at, vs in parts:
            put(x, beat + at * eighth, np.concatenate([vowel(eighth - (0.04 if k == len(vs) - 1 else 0.0), v, attack=0.01 if k else 0.0005)
                                                        for k, v in enumerate(vs)]))
        for at, v in after:
            put(x, beat + at * eighth, vowel(eighth - 0.04, v))
        return x

    def test_the_second_syllable_may_be_the_one_missing(self):
        # i i run together (one onset), then a and e: the a is the word's third vowel, not its second
        beat = 1.2
        x = self.legato(beat, [(1, "ii"), (3, "a"), (4, "e")])
        got = FS.title_start(FS.syllables_of(x), beat, "iiae")
        self.assertIsNotNone(got)
        self.assertLess(abs(got["t"] - (beat + PERIOD / 2.0)), 0.006, got)
        self.assertEqual(got["positions"], [0, 2, 3])

    def test_where_the_vowels_cannot_place_a_syllable_its_time_on_the_eighths_does(self):
        # (the second singer's title words 1 and 2) the a sung on from the i before it, or the two middle syllables sung on from
        # the first: the e that comes in is the word's fourth syllable, three eighths after its first - a close i then an open
        # vowel reads the same at the third place and at the fourth
        beat = 1.2
        eighth = PERIOD / 2.0
        got = FS.title_start(FS.syllables_of(self.legato(beat, [(1, "i"), (2, "ia"), (4, "e")])), beat, "iiae", step=eighth)
        self.assertEqual(got["positions"], [0, 1, 3], got)
        got = FS.title_start(FS.syllables_of(self.legato(beat, [(1, "iia"), (4, "e")])), beat, "iiae", step=eighth)
        self.assertEqual(got["positions"], [0, 3], got)
        self.assertLess(abs(got["t"] - (beat + eighth)), 0.006, got)

    def test_the_title_word_is_looked_for_from_its_beat_not_from_where_the_structure_writes_it(self):
        # a voice that sings the word early, from 0.2 s before the beat (another singer may): it is looked for from the beat
        # (TITLE_SEARCH), not from the hook's t, which version 3 of the song structure writes on the first eighth after the beat
        beat = FIRST + 12 * PERIOD
        eighth = PERIOD / 2.0
        sung = [{"t": beat - 0.5, "rise_db": 20.0, "open": 8.0}]
        sung += [{"t": beat - 0.2 + k * eighth, "rise_db": 20.0, "open": o} for k, o in enumerate((-15.0, -14.0, 5.0, 3.0))]
        structure = {"beat": {"first": FIRST, "period": PERIOD, "per_bar": 4}, "hooks": [{"n": 1, "beat": 12, "t": beat + eighth}]}
        got = FS.titles_of(structure, sung, "iiae")[1]
        self.assertAlmostEqual(got["t"], beat - 0.2, places=6)
        self.assertEqual(got["positions"], [0, 1, 2, 3])

    def test_the_next_word_past_the_title_words_length_is_not_its_syllables(self):
        # the title word sung with its middle run together, and the next word's close vowels soon after it
        beat = 1.2
        x = self.legato(beat, [(1, "i"), (2, "ia"), (4, "e")], after=[(6, "i"), (7, "i")])
        got = FS.title_start(FS.syllables_of(x), beat, "iiae")
        self.assertIsNotNone(got)
        self.assertLess(abs(got["t"] - (beat + PERIOD / 2.0)), 0.006, got)
        self.assertLessEqual(max(got["run"]) - got["t"], FS.WORD_SYLLABLE * 3 + 1e-9)

    def test_no_title_word_where_no_run_has_its_vowels_in_order(self):
        beat = 1.2
        x = self.sung(beat, "aaii", before="a")
        self.assertIsNone(FS.title_start(FS.syllables_of(x), beat, "iiae"))
        with self.assertRaises(ValueError):
            FS.title_start(FS.syllables_of(x), beat, "iix")                           # not a vowel

    def test_no_syllable_without_a_rise(self):
        beat = 1.5
        x = self.voice(None)
        put(x, beat - 0.8, tone(1.2, 247.0))                 # a note held through the window: no onset in it
        t, db = FS.voice_level(x)
        self.assertIsNone(FS.first_syllable(t, db, beat))


# ---- frames, heads and the band's return ---------------------------------------------------------------------------

@unittest.skipUnless(FS, "needs numpy")
class MomentTest(unittest.TestCase):
    def test_the_frame_of_a_moment_starts_no_later_than_its_sound(self):
        for t in (86.044, 86.0, 85.99999, 0.0, 241.737, 7.0 / 30.0, 1.0 / 30.0 - 1e-7):
            f = FS.frame_of_moment(t)
            self.assertLessEqual(f / 30.0, t + 1e-6, t)
            self.assertGreater((f + 1) / 30.0, t, t)
        self.assertEqual(FS.frame_of_moment(86.044), 2581)
        self.assertEqual(FS.frame_of_moment(7.0 / 30.0), 7)
        # the time written for it gives that frame back under round and ceil (mograph_layer.frame_time)
        for f in (2581, 2623, 7252):
            t = FS.time_of_frame(f)
            self.assertEqual(int(round(t * 30)), f)
            self.assertEqual(int(math.ceil(t * 30)), f)

    def test_the_band_returns_where_a_strong_hit_ends_a_stop(self):
        # the drums stop under the last title word and come back with a hard hit: the song's hits every eighth (median 50),
        # then 1.5 s of hits under its median, then a hit over its 90th percentile
        hits = [{"t": 1.0 + 0.2143 * k, "height": 45.0 + 10.0 * (k % 3)} for k in range(60)]
        stop_from = hits[-1]["t"]
        hits += [{"t": stop_from + 0.3 * k, "height": 10.0} for k in range(1, 6)]
        back = stop_from + 1.7
        hits += [{"t": back, "height": 200.0}] + [{"t": back + 0.2143 * k, "height": 50.0} for k in range(1, 20)]
        got = FS.band_returns(FS.Hits(hits))
        self.assertEqual([round(r["t"], 3) for r in got], [round(back, 3)])
        self.assertGreaterEqual(got[0]["quiet_s"], FS.STOP_S)
        # a hard hit with the band playing on before it is no return, nor a soft one after the stop
        hits2 = [dict(h) for h in hits if not (stop_from < h["t"] < back)]
        self.assertEqual(FS.band_returns(FS.Hits(hits2 + [{"t": stop_from + 0.85, "height": 65.0}])), [])
        hits3 = [dict(h, height=60.0) if h["t"] == back else h for h in hits]
        self.assertEqual(FS.band_returns(FS.Hits(hits3)), [])


    def test_a_return_on_a_beat_is_the_beat_of_the_grid(self):
        # the grid of the song structure (fitted to the kick's attack over the whole song) is the time of a hit on a beat; one hit
        # read alone comes a few ms after it (here 6 ms: beat 564 at 241.7302 s, frame 7251, read at 241.7362 s, frame 7252)
        structure = {"beat": {"first": FIRST, "period": PERIOD, "per_bar": 4}, "sections": [{"id": "intro", "t": 0.016}],
                     "hooks": []}
        beat = FIRST + 564 * PERIOD
        got = FS.moments_of(structure, {}, [{"t": beat + 0.006, "quiet_s": 1.7, "pct": 98.0}])
        self.assertAlmostEqual(got[0]["t"], beat, places=4)
        self.assertAlmostEqual(got[0]["hit_t"], beat + 0.006, places=4)
        self.assertEqual(FS.frame_of_moment(got[0]["t"]), 7251)
        off = FS.moments_of(structure, {}, [{"t": beat + 0.107, "quiet_s": 1.7, "pct": 98.0}])      # a sixteenth after: off the beat
        self.assertAlmostEqual(off[0]["t"], beat + 0.107, places=4)

    def test_a_title_word_is_told_from_its_beat_on_the_grid(self):
        # version 3 of the song structure writes a title word's t on its first sung eighth, version 2 on the beat before it:
        # the beat is the grid's (the word's "beat"); with no grid or no beat, its t
        grid = {"beat": {"first": FIRST, "period": PERIOD, "per_bar": 4}}
        self.assertAlmostEqual(FS.hook_beat(grid, {"n": 1, "beat": 201, "t": 86.373}), FIRST + 201 * PERIOD, places=9)
        self.assertEqual(FS.hook_beat({}, {"n": 1, "beat": 201, "t": 86.373}), 86.373)
        self.assertEqual(FS.hook_beat(grid, {"n": 1, "t": 86.373}), 86.373)
        structure = dict(grid, sections=[{"id": "intro", "t": 0.016}], hooks=[{"n": 1, "beat": 201, "t": 86.373}])
        got = FS.moments_of(structure, {1: {"t": 86.389, "rise_db": 28.0}}, [])
        self.assertAlmostEqual(got[0]["beat"], FIRST + 201 * PERIOD, places=9)


# ---- the decision -------------------------------------------------------------------------------------------------

def flash(t, **more):
    return dict({"kind": "flash", "t": t, "note": "test", "strength": 0.0, "light": 1.1}, **more)


def punch(t, **more):
    return dict({"kind": "punch", "t": t, "note": "test", "amount": 0.12}, **more)


def song_hits(strong=(), weak=()):
    """the song's hits: 90 ordinary ones spread over it (heights 1.00 to 1.89), and these: weak ones (1.2, about a fifth of
    them weaker) and strong ones (10, over all of them)"""
    out = [{"t": 0.5 + 0.7 * k, "height": 1.0 + 0.01 * k} for k in range(90)]
    out += [{"t": t, "height": 1.2} for t in weak] + [{"t": t, "height": 10.0} for t in strong]
    return FS.Hits(out)


@unittest.skipUnless(FS, "needs numpy")
class DecideTest(unittest.TestCase):
    def hits(self, strong=(), weak=()):
        return song_hits(strong, weak)

    def test_a_flash_moves_to_the_nearest_moment_with_a_strong_hit_on_it_and_its_punch_stays_on_the_title_word(self):
        # (the coordinator, 2026-10-21, after review flashsyncrev: one rule an effect) the punch marks the title word as sung and
        # does not go with its flash: title word 1's flash to the head of inter1, its punch to the word's first syllable
        moments = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29}]
        events = [flash(10.0), punch(10.0), punch(5.0)]
        out = FS.decide(events, moments, self.hits(strong=[11.30]), skirt=[])
        f = [d for d in out if d["kind"] == "flash"][0]
        self.assertEqual(f["action"], "move")
        self.assertEqual(f["frame"], FS.frame_of_moment(11.29))
        self.assertEqual(f["moment"]["kind"], "section")
        p = [d for d in out if d["kind"] == "punch" and d["old_frame"] == 300][0]
        self.assertEqual((p["action"], p["frame"], p["n"]), ("move", FS.frame_of_moment(9.893), 1))
        self.assertNotEqual(p["frame"], f["frame"])
        other = [d for d in out if d["kind"] == "punch" and d["old_frame"] == 150]
        self.assertEqual(other, [])                          # a punch on no flash's frame is not the tool's

    def test_a_punch_goes_to_the_title_word_as_sung_whatever_becomes_of_its_flash(self):
        # its flash moved (title word 1), dropped (2) or kept (3): each punch on its own title word's first syllable as sung
        moments = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29},
                   {"kind": "title", "n": 2, "t": 30.21, "beat": 30.0},
                   {"kind": "title", "n": 3, "t": 50.01, "beat": 50.0}]
        events = [flash(10.0), punch(10.0), flash(30.0), punch(30.0), flash(ML.frame_time(1500)), punch(ML.frame_time(1500))]
        out = FS.decide(events, moments, self.hits(strong=[11.30, 50.01]), skirt=[])
        flashes = {d["old_frame"]: d for d in out if d["kind"] == "flash"}
        self.assertEqual([flashes[k]["action"] for k in (300, 900, 1500)], ["move", "drop", "keep"])
        punches = {d["old_frame"]: d for d in out if d["kind"] == "punch"}
        self.assertEqual([(punches[k]["frame"], punches[k]["n"]) for k in (300, 900, 1500)],
                         [(FS.frame_of_moment(9.893), 1), (FS.frame_of_moment(30.21), 2), (1500, 3)])
        self.assertEqual(punches[1500]["action"], "keep")                  # on its title word already: nothing moves
        self.assertEqual(punches[900]["action"], "move")

    def test_the_title_word_keeps_its_flash_on_the_voice_when_a_strong_hit_is_on_it(self):
        moments = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}]
        out = FS.decide([flash(10.0)], moments, self.hits(strong=[9.90]), skirt=[])
        self.assertEqual(out[0]["frame"], FS.frame_of_moment(9.893))      # the earlier of the voice and the hit
        self.assertEqual(out[0]["action"], "move")

    def test_a_flash_on_no_strong_hit_is_dropped_and_its_punch_goes_to_the_title_word_as_sung(self):
        moments = [{"kind": "title", "n": 2, "t": 19.89, "beat": 20.0}, {"kind": "section", "id": "bridge", "t": 21.3}]
        out = FS.decide([flash(20.0), punch(20.0)], moments, self.hits(weak=[19.9, 20.0, 21.3]), skirt=[])
        f = [d for d in out if d["kind"] == "flash"][0]
        p = [d for d in out if d["kind"] == "punch"][0]
        self.assertEqual(f["action"], "drop")
        self.assertEqual((p["action"], p["frame"]), ("move", FS.frame_of_moment(19.89)))

    def test_the_light_starts_on_the_earlier_of_the_moment_and_its_hit(self):
        # a head written at 11.31 s (frame 339) whose hit is read at 11.29 s (frame 338): the light on 338, not after the sound
        out = FS.decide([flash(10.0)], [{"kind": "section", "id": "inter1", "t": 11.31}], self.hits(strong=[11.29]), skirt=[])
        self.assertEqual(out[0]["frame"], 338)
        out = FS.decide([flash(10.0)], [{"kind": "section", "id": "inter1", "t": 11.29}], self.hits(strong=[11.31]), skirt=[])
        self.assertEqual(out[0]["frame"], 338)

    def test_of_two_moments_with_a_strong_hit_the_nearer_is_taken_though_the_other_is_stronger(self):
        # (the flash keeps as near to where it was put as it can: its phrase)
        moments = [{"kind": "section", "id": "a", "t": 10.6}, {"kind": "return", "t": 9.2, "bar": 3}]
        hits = song_hits(strong=[10.6])
        hits = FS.Hits([{"t": t, "height": h} for t, h in zip(hits.times, hits.heights)] + [{"t": 9.2, "height": 30.0}])
        out = FS.decide([flash(10.0)], moments, hits, skirt=[])
        self.assertEqual(out[0]["moment"]["id"], "a")

    def test_a_strong_hit_alone_means_nothing_and_a_moment_further_than_a_bar_is_not_taken(self):
        moments = [{"kind": "section", "id": "verse2", "t": 32.2}]
        out = FS.decide([flash(30.0)], moments, self.hits(strong=[30.0, 32.2]), skirt=[])
        self.assertEqual(out[0]["action"], "drop")

    def test_a_punch_does_not_go_near_where_the_skirt_flares(self):
        # the band returns 1.3 s after the title word, 0.67 s before the skirt flares (as at 241.7 and 242.4 s of the song):
        # the flash goes there, its punch to the title word as sung (mograph_layer's plan keeps a punch's frames half a second
        # from the skirt's times)
        moments = [{"kind": "title", "n": 4, "t": 39.89, "beat": 40.0}, {"kind": "return", "t": 41.3}]
        out = FS.decide([flash(40.0), punch(40.0)], moments, self.hits(strong=[41.3]), skirt=[41.97])
        f = [d for d in out if d["kind"] == "flash"][0]
        p = [d for d in out if d["kind"] == "punch"][0]
        self.assertEqual((f["action"], f["frame"]), ("move", FS.frame_of_moment(41.3)))
        self.assertEqual((p["action"], p["frame"]), ("move", FS.frame_of_moment(39.89)))
        out = FS.decide([flash(40.0), punch(40.0)], moments, self.hits(strong=[41.3]), skirt=[40.2, 41.97])
        p = [d for d in out if d["kind"] == "punch"][0]
        self.assertEqual(p["action"], "drop")                          # near the skirt at both places

    def test_a_flare_of_the_look_is_judged_alike(self):
        moments = [{"kind": "section", "id": "inter1", "t": 11.29}]
        out = FS.decide([], moments, self.hits(strong=[11.3]), skirt=[], flares=[10.5, 30.0])
        self.assertEqual([(d["kind"], d["action"]) for d in out], [("flare", "move"), ("flare", "drop")])
        self.assertEqual(out[0]["frame"], FS.frame_of_moment(11.29))


# ---- the look ------------------------------------------------------------------------------------------------------

@unittest.skipUnless(FS, "needs numpy")
class PlaceTest(unittest.TestCase):
    LOOK = {"flares": [10.5, 30.0], "mograph": {"on": 1, "events": [
        punch(5.0), flash(10.0), punch(10.0), flash(20.0), punch(20.0), {"kind": "shake", "t": 20.0, "note": "landing"}]}}

    def test_the_look_gets_the_decisions_and_nothing_else_changes(self):
        moments = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29},
                   {"kind": "title", "n": 2, "t": 19.89, "beat": 20.0}]
        hits = song_hits(strong=[11.3])
        look = copy.deepcopy(self.LOOK)
        decisions = FS.decide(look["mograph"]["events"], moments, hits, skirt=[], flares=look["flares"])
        out = FS.place(look, decisions)
        self.assertEqual(look, self.LOOK)                                   # the look given is not touched
        ev = out["mograph"]["events"]
        frames = sorted((e["kind"], ML.frame_of(e["t"], 30)) for e in ev)
        # the flash at 10 s to the head (338), its punch to title word 1 as sung (296), the punch of the dropped flash at 20 s
        # to title word 2 as sung (596)
        self.assertEqual(frames, sorted([("punch", 150), ("flash", 338), ("punch", 296), ("punch", 596), ("shake", 600)]))
        self.assertEqual(out["flares"], [FS.time_of_frame(338)])           # the flare at 10.5 s goes to the same moment
        ML.merge(out["mograph"])                                            # still a section mograph_layer takes
        moved = [e for e in ev if ML.frame_of(e["t"], 30) == 338 and e["kind"] == "flash"][0]
        self.assertIn("flashsync", moved["note"])
        self.assertEqual(moved["light"], 1.1)                               # its own values kept

    def test_measure_reads_two_sounds_and_writes_the_decisions(self):
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(8)
        seconds = 12.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        for b in range(28):
            put(backing, FIRST + b * PERIOD, 0.15 * burst(int(0.1 * SR), rng))
        put(backing, FIRST + 19 * PERIOD, 1.0 * burst(int(0.15 * SR), rng))          # the head of "inter1", hard
        voice = 0.0003 * rng.standard_normal(int(seconds * SR))
        beat = FIRST + 16 * PERIOD                                                     # the title word's beat
        put(voice, beat - 0.5, tone(0.22, 247.0))
        put(voice, beat - 0.107, tone(0.5, 262.0))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "bars": [FIRST + 4 * k * PERIOD for k in range(7)],
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD},
                                  {"id": "inter1", "beat": 19, "t": FIRST + 19 * PERIOD}],
                     "hooks": [{"n": 1, "beat": 16, "t": beat}], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(ML.frame_time(ML.frame_of(beat, 30))),
                                                            punch(ML.frame_time(ML.frame_of(beat, 30)))]}}
        with tempfile.TemporaryDirectory() as d:
            mix_path, voice_path = os.path.join(d, "mix.wav"), os.path.join(d, "voice.wav")
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            write_wav(mix_path, backing + voice, scale)
            write_wav(voice_path, voice, scale)
            paths = {}
            for name, doc in (("structure", structure), ("look", look)):
                paths[name] = os.path.join(d, name + ".json")
                with open(paths[name], "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            out, arrays = os.path.join(d, "measure.json"), os.path.join(d, "arrays.npz")
            with contextlib.redirect_stdout(io.StringIO()):
                code = FS.main(["measure", mix_path, voice_path, paths["structure"], paths["look"], out, "--arrays", arrays])
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as f:
                rep = json.load(f)
            title = [m for m in rep["moments"] if m["kind"] == "title"][0]
            self.assertLess(abs(title["t"] - (beat - 0.107)), 0.008, title)
            f0 = [x for x in rep["decisions"] if x["kind"] == "flash"][0]
            self.assertEqual(f0["action"], "move")
            self.assertEqual(f0["moment"]["kind"], "section")
            self.assertEqual(f0["frame"], FS.frame_of_moment(FIRST + 19 * PERIOD))
            new_look = os.path.join(d, "placed.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["place", paths["look"], out, new_look]), 0)
            with open(new_look, encoding="utf-8") as f:
                placed = json.load(f)
            # the flash on the head, its punch on the title word as sung (not with the flash)
            self.assertEqual(sorted((e["kind"], ML.frame_of(e["t"], 30)) for e in placed["mograph"]["events"]),
                             [("flash", f0["frame"]), ("punch", FS.frame_of_moment(title["t"]))])
            self.assertNotEqual(FS.frame_of_moment(title["t"]), f0["frame"])
            # another source's mix over the same backing is measured against the reference: on it, it goes on; a mix that lies
            # 0.3 s off is refused (the song structure's beats would not be where its hits are)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["measure", mix_path, voice_path, paths["structure"], paths["look"], out,
                                          "--reference", mix_path]), 0)
            with open(out, encoding="utf-8") as f:
                self.assertLess(abs(json.load(f)["reference"]["lag_ms"]), 8.0)
            shifted_path = os.path.join(d, "shifted.wav")
            write_wav(shifted_path, np.concatenate([np.zeros(int(0.3 * SR)), backing + voice]), scale)
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                code = FS.main(["measure", mix_path, voice_path, paths["structure"], paths["look"], os.path.join(d, "no.json"),
                                "--reference", shifted_path])
            self.assertEqual(code, 2)
            self.assertIn("structure", said.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "no.json")))
            table = os.path.join(d, "table.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["table", out, table]), 0)
            with open(table, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("inter1", text)
            self.assertIn("伴奏の強い立ち上がり（全曲の", text)                  # the reason, in Japanese
            self.assertIn("パンチは題名の語 1 の 1 音目を歌うコマへ（光は動かした）", text)
            try:
                import matplotlib  # noqa: F401
            except ImportError:
                return
            for lang in ("en", "ja"):
                png = os.path.join(d, "figure_%s.png" % lang)
                with contextlib.redirect_stdout(io.StringIO()):
                    code = FS.main(["figure", out, arrays, png, "--lang", lang])
                if lang == "ja" and code == 2:
                    continue                                                     # no Japanese font on this machine
                self.assertEqual(code, 0, lang)
                self.assertGreater(os.path.getsize(png), 10000)


@unittest.skipUnless(FS, "needs numpy")
class SourceTest(unittest.TestCase):
    """another source of the song (another singer over the same backing): the hits of the backing from the source the song
    structure was measured on, the title words' first syllables from the new voice, and the two sources side by side"""

    def test_the_backing_comes_from_the_reference_and_the_title_word_from_the_new_voice(self):
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(12)
        seconds = 12.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(28):
            put(backing, FIRST + b * PERIOD, 0.15 * hit)
        head = FIRST + 19 * PERIOD
        hard = backing.copy()
        put(hard, head, 1.0 * burst(int(0.15 * SR), rng))                   # the head of "inter1": hard in the reference
        beat = FIRST + 16 * PERIOD
        voices = {}
        for name, lead in (("ref", 0.107), ("new", 0.150)):                  # the new singer comes in earlier
            v = 0.0003 * rng.standard_normal(int(seconds * SR))
            put(v, beat - 0.5, tone(0.22, 247.0))
            put(v, beat - lead, tone(0.5, 262.0, attack=0.0005))
            voices[name] = v
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}, {"id": "inter1", "beat": 19, "t": head}],
                     "hooks": [{"n": 1, "beat": 16, "t": beat}], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(ML.frame_time(ML.frame_of(beat, 30))),
                                                            punch(ML.frame_time(ML.frame_of(beat, 30)))]}}
        with tempfile.TemporaryDirectory() as d:
            files = {}
            scale = 0.8 / max(np.abs(hard + voices["ref"]).max(), 1e-9)
            # the new source's backing as its own separation gives it: the head's hit softer (no strong hit there)
            for name, x in (("mix0", hard + voices["ref"]), ("voice0", voices["ref"]), ("mix1", backing + voices["new"]),
                            ("voice1", voices["new"])):
                files[name] = os.path.join(d, name + ".wav")
                write_wav(files[name], x, scale)
            for name, doc in (("structure", structure), ("look", look)):
                files[name] = os.path.join(d, name + ".json")
                with open(files[name], "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            outs = {}
            for tag, extra in (("ref", []), ("own", []), ("new", ["--backing-from", files["mix0"], files["voice0"]])):
                mix, voice = (files["mix0"], files["voice0"]) if tag == "ref" else (files["mix1"], files["voice1"])
                outs[tag] = os.path.join(d, "measure_%s.json" % tag)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(FS.main(["measure", mix, voice, files["structure"], files["look"], outs[tag]] + extra), 0, tag)
            reps = {}
            for tag, path in outs.items():
                with open(path, encoding="utf-8") as f:
                    reps[tag] = json.load(f)

            def first(rep, kind):
                return [x for x in rep["decisions"] if x["kind"] == kind][0]

            def title(rep):
                return [m for m in rep["moments"] if m["kind"] == "title"][0]["t"]
            self.assertLess(abs(title(reps["new"]) - (beat - 0.150)), 0.004)            # the new voice's first syllable
            self.assertLess(abs(title(reps["ref"]) - (beat - 0.107)), 0.004)
            # its own backing has no strong hit at the head: the flash is dropped; the reference's backing has: it moves there
            self.assertEqual(first(reps["own"], "flash")["action"], "drop")
            self.assertEqual(first(reps["new"], "flash")["action"], "move")
            self.assertEqual(first(reps["new"], "flash")["frame"], FS.frame_of_moment(head))
            self.assertEqual(reps["new"]["backing_from"]["mix"], os.path.abspath(files["mix0"]))
            # the punch of the dropped flash goes to the new voice's first syllable, and so does the punch of the flash that moves
            # to the head (a punch marks the title word as sung, not its flash)
            self.assertEqual(first(reps["own"], "punch")["frame"], FS.frame_of_moment(beat - 0.150))
            self.assertEqual(first(reps["new"], "punch")["frame"], FS.frame_of_moment(beat - 0.150))
            # the two sources side by side
            table = os.path.join(d, "compare.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["compare", outs["ref"], outs["new"], table, "--labels", "first,second"]), 0)
            with open(table, encoding="utf-8") as f:
                text = f.read()
            for want in ("| | first | second |", "%.3f" % title(reps["ref"]), "%.3f" % title(reps["new"])):
                self.assertIn(want, text)
            self.assertLess(text.index("%.3f" % title(reps["ref"])), text.index("%.3f" % title(reps["new"])))

    def test_a_new_source_measured_without_the_references_backing_is_warned_of(self):
        # (review flashsyncrev) the second singer's pair measured on its own leaves its voice in the backing: the stop under the
        # last title word has hits at the song's median (no band's return is found) and the flash on the return is dropped with
        # nothing said (measured: Rin's pair without --backing-from drops 7213, the official pair's backing moves it to 7251).
        # A new source (--reference another file) measured without --backing-from is warned of; with it, or the reference
        # itself, or no reference, nothing is said
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(31)
        seconds = 8.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        for b in range(16):
            put(backing, FIRST + b * PERIOD, 0.15 * burst(int(0.1 * SR), rng))
        voice = 0.0003 * rng.standard_normal(int(seconds * SR))
        beat = FIRST + 8 * PERIOD
        put(voice, beat - 0.107, tone(0.4, 262.0))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}],
                     "hooks": [{"n": 1, "beat": 8, "t": beat}], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(ML.frame_time(ML.frame_of(beat, 30)))]}}
        with tempfile.TemporaryDirectory() as d:
            files = {}
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            for name, x in (("mix0", backing + voice), ("voice0", voice), ("mix1", backing + voice), ("voice1", voice)):
                files[name] = os.path.join(d, name + ".wav")
                write_wav(files[name], x, scale)
            for name, doc in (("structure", structure), ("look", look)):
                files[name] = os.path.join(d, name + ".json")
                with open(files[name], "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            said = {}
            for tag, mix, voice_path, extra in (
                    ("new_alone", files["mix1"], files["voice1"], ["--reference", files["mix0"]]),
                    ("new_with", files["mix1"], files["voice1"], ["--reference", files["mix0"], "--backing-from", files["mix0"],
                                                                  files["voice0"]]),
                    ("reference_itself", files["mix0"], files["voice0"], ["--reference", files["mix0"]]),
                    ("no_reference", files["mix1"], files["voice1"], [])):
                out = os.path.join(d, "measure_%s.json" % tag)
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    self.assertEqual(FS.main(["measure", mix, voice_path, files["structure"], files["look"], out] + extra), 0, tag)
                with open(out, encoding="utf-8") as f:
                    said[tag] = (json.load(f).get("warnings"), json.loads(printed.getvalue()).get("warnings"))
            report, printed = said["new_alone"]
            self.assertTrue(report and any("--backing-from" in w for w in report), report)
            self.assertEqual(printed, report)                                  # said where it is run, too
            for tag in ("new_with", "reference_itself", "no_reference"):
                self.assertEqual(said[tag], ([], []), tag)
            # and in the table a person reads
            for tag, want in (("new_alone", True), ("new_with", False)):
                table = os.path.join(d, "table_%s.md" % tag)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(FS.main(["table", os.path.join(d, "measure_%s.json" % tag), table]), 0)
                with open(table, encoding="utf-8") as f:
                    text = f.read()
                self.assertEqual("測りの警告" in text and "--backing-from" in text, want, tag)


@unittest.skipUnless(FS, "needs numpy")
class TitleVowelsTest(unittest.TestCase):
    def test_measure_tells_the_title_word_by_its_vowels_and_the_punch_goes_there(self):
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(21)
        seconds = 10.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(22):
            put(backing, FIRST + b * PERIOD, 0.15 * hit)
        beat = FIRST + 12 * PERIOD
        eighth = PERIOD / 2.0
        voice = 0.003 * rng.standard_normal(int(seconds * SR))
        put(voice, beat - 0.10, vowel(0.10 + eighth - 0.04, "a"))                      # the word before: just before the beat
        for k, v in enumerate("iiae"):
            put(voice, beat + (k + 1) * eighth, vowel(eighth - 0.04, v))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}],
                     "hooks": [{"n": 1, "beat": 12, "t": beat}], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(ML.frame_time(ML.frame_of(beat, 30))),
                                                            punch(ML.frame_time(ML.frame_of(beat, 30)))]}}
        with tempfile.TemporaryDirectory() as d:
            files = {}
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            for name, x in (("mix", backing + voice), ("voice", voice)):
                files[name] = os.path.join(d, name + ".wav")
                write_wav(files[name], x, scale)
            for name, doc in (("structure", structure), ("look", look)):
                files[name] = os.path.join(d, name + ".json")
                with open(files[name], "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            reps = {}
            for tag, extra in (("rise", []), ("vowels", ["--title-vowels", "iiae"])):
                out = os.path.join(d, "measure_%s.json" % tag)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(FS.main(["measure", files["mix"], files["voice"], files["structure"], files["look"], out]
                                             + extra), 0, tag)
                with open(out, encoding="utf-8") as f:
                    reps[tag] = json.load(f)
            t = {k: [m for m in r["moments"] if m["kind"] == "title"][0]["t"] for k, r in reps.items()}
            self.assertLess(abs(t["vowels"] - (beat + eighth)), 0.006)                    # the title word's first syllable
            self.assertLess(abs(t["rise"] - (beat - 0.10)), 0.006)                       # the voice's first rise: the word before
            p = [x for x in reps["vowels"]["decisions"] if x["kind"] == "punch"][0]
            self.assertEqual(p["frame"], FS.frame_of_moment(t["vowels"]))
            self.assertIn("iiae", reps["vowels"]["title_how"])

    def test_a_structure_that_writes_the_title_word_on_its_sung_eighth_is_read_from_its_beat(self):
        # (the song structure's version 3: the title word's t on its first sung eighth) the word sung partly legato, the a run on
        # from the i before it: measure tells its places by the eighths of the structure's beat, and looks for its first syllable
        # from the beat - as with version 2, which wrote t on the beat
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(23)
        seconds = 10.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(22):
            put(backing, FIRST + b * PERIOD, 0.15 * hit)
        beat = FIRST + 12 * PERIOD
        eighth = PERIOD / 2.0
        voice = 0.003 * rng.standard_normal(int(seconds * SR))
        put(voice, beat - 0.10, vowel(0.10 + eighth - 0.04, "a"))                      # the word before: just before the beat
        put(voice, beat + eighth, vowel(eighth - 0.04, "i"))
        put(voice, beat + 2 * eighth, np.concatenate([vowel(eighth, "i"), vowel(eighth - 0.04, "a", attack=0.01)]))
        put(voice, beat + 4 * eighth, vowel(eighth - 0.04, "e"))
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(ML.frame_time(ML.frame_of(beat, 30))),
                                                            punch(ML.frame_time(ML.frame_of(beat, 30)))]}}
        with tempfile.TemporaryDirectory() as d:
            files = {}
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            for name, x in (("mix", backing + voice), ("voice", voice)):
                files[name] = os.path.join(d, name + ".wav")
                write_wav(files[name], x, scale)
            files["look"] = os.path.join(d, "look.json")
            with open(files["look"], "w", encoding="utf-8") as f:
                json.dump(look, f)
            for version, t in ((2, beat), (3, beat + eighth)):
                structure = {"version": version, "seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                             "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}],
                             "hooks": [{"n": 1, "beat": 12, "t": t}], "skirt": []}
                files["structure"] = os.path.join(d, "structure.json")
                with open(files["structure"], "w", encoding="utf-8") as f:
                    json.dump(structure, f)
                reps = {}
                for tag, extra in (("rise", []), ("vowels", ["--title-vowels", "iiae"])):
                    out = os.path.join(d, "measure_%s.json" % tag)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(FS.main(["measure", files["mix"], files["voice"], files["structure"], files["look"], out]
                                                 + extra), 0, tag)
                    with open(out, encoding="utf-8") as f:
                        reps[tag] = json.load(f)
                title = {k: [m for m in r["moments"] if m["kind"] == "title"][0] for k, r in reps.items()}
                self.assertLess(abs(title["vowels"]["t"] - (beat + eighth)), 0.006, version)
                self.assertEqual(reps["vowels"]["syllables"]["1"]["positions"], [0, 1, 3], version)
                self.assertLess(abs(title["rise"]["t"] - (beat - 0.10)), 0.006, version)    # from the beat, as before
                self.assertAlmostEqual(title["vowels"]["beat"], beat, places=6)


# ---- review flashsyncrev: what the tests above let through (tools/flash_sync.py broken one place at a time on hinata: 57 ways,
# 36 passed them; these catch 35 of the 36, the last breaks nothing: two flashes on one frame get one decision) ----

@unittest.skipUnless(FS, "needs numpy")
class RuleEdgeTest(unittest.TestCase):
    def test_a_hit_at_the_90th_percentile_is_strong(self):
        # (strong_boundary) "90 % 点以上": 9 of the 10 hits weaker than the moment's -> percentile 90.0, strong
        hits = FS.Hits([{"t": float(k), "height": float(k)} for k in range(1, 10)] + [{"t": 11.30, "height": 10.0}])
        self.assertEqual(hits.strongest(11.30, 0.001)["pct"], 90.0)
        out = FS.decide([flash(10.0)], [{"kind": "section", "id": "inter1", "t": 11.29}], hits, skirt=[])
        self.assertEqual((out[0]["action"], out[0]["frame"]), ("move", FS.frame_of_moment(11.29)))

    def test_a_return_at_the_90th_percentile_is_a_return(self):
        # (returns_strong_boundary) 10 quiet hits, 8 loud ones (percentile 50: loud), a stop of 1.5 s, then a hit at exactly
        # the 90th percentile; one stronger hit long after
        hits = [{"t": 1.0 + 0.3 * k, "height": 5.0} for k in range(8)]
        hits += [{"t": 3.4 + 0.25 * k, "height": 1.0} for k in range(4)] + [{"t": 5.0 + 0.3 * k, "height": 1.0} for k in range(6)]
        hits += [{"t": 4.6, "height": 10.0}, {"t": 9.0, "height": 20.0}]
        h = FS.Hits(hits)
        self.assertEqual(h.percentile(10.0), 90.0)
        self.assertIn(4.6, [r["t"] for r in FS.band_returns(h)])

    def test_a_strong_hit_a_frame_and_a_half_off_the_moment_is_not_on_it(self):
        # (near_frames_two, near_wider_in_place) the rule's +-1 frame: a strong hit 50 ms after the head is not on it
        out = FS.decide([flash(10.0)], [{"kind": "section", "id": "inter1", "t": 11.29}], song_hits(strong=[11.34]), skirt=[])
        self.assertEqual(out[0]["action"], "drop")

    def test_a_return_fifty_ms_off_the_beat_keeps_its_time(self):
        # (grid_two_frames, near_frames_two) only a hit within a frame of a beat is put on the grid
        structure = {"beat": {"first": FIRST, "period": PERIOD, "per_bar": 4}, "sections": [{"id": "intro", "t": 0.016}], "hooks": []}
        beat = FIRST + 564 * PERIOD
        got = FS.moments_of(structure, {}, [{"t": beat + 0.050, "quiet_s": 1.7, "pct": 98.0}])
        self.assertAlmostEqual(got[0]["t"], beat + 0.050, places=4)

    def test_the_skirts_half_second_holds_on_both_sides_of_the_punch(self):
        # (skirt_gap_small) the punch on the title word as sung (39.89 s: frame 1196 from 39.867 s, 12 frames to 40.267 s) is
        # half a second from where the skirt flares: 0.4 s after its end or 0.4 s before its start is near, and the punch is
        # dropped; 0.6 s either side is not
        moments = [{"kind": "title", "n": 4, "t": 39.89, "beat": 40.0}, {"kind": "return", "t": 41.3}]
        start, end = FS.frame_of_moment(39.89) / 30.0, FS.frame_of_moment(39.89) / 30.0 + 12 / 30.0
        for skirt, want in ((end + 0.4, "drop"), (start - 0.4, "drop"), (end + 0.6, "move"), (start - 0.6, "move")):
            out = FS.decide([flash(40.0), punch(40.0)], moments, song_hits(strong=[41.3]), skirt=[skirt])
            p = [d for d in out if d["kind"] == "punch"][0]
            self.assertEqual(p["action"], want, skirt)
            if want == "move":
                self.assertEqual(p["frame"], FS.frame_of_moment(39.89), skirt)

    def test_a_flash_moves_at_most_a_bar_of_the_structures_beat(self):
        # (reach_of_two_bars) measure's reach is a bar of the structure's beat (and a frame): in a song of three beats of 0.5 s
        # to the bar, a head with a strong hit 1.45 s from the flash is reached, one 1.6 s from it is not (two bars would)
        reach = FS.reach_of({"beat": {"per_bar": 3, "period": 0.5}})
        for away, want in ((1.45, "move"), (1.6, "drop")):
            out = FS.decide([flash(10.0)], [{"kind": "section", "id": "a", "t": 10.0 + away}], song_hits(strong=[10.0 + away]),
                            skirt=[], reach=reach)
            self.assertEqual(out[0]["action"], want, away)
        out = FS.decide([flash(10.0)], [{"kind": "section", "id": "a", "t": 11.6}], song_hits(strong=[11.6]), skirt=[],
                        reach=FS.reach_of({"beat": {"per_bar": 4, "period": PERIOD}}))
        self.assertEqual(out[0]["action"], "move")                      # a bar of 140 BPM is 1.71 s


@unittest.skipUnless(FS, "needs numpy")
class HitMoreTest(unittest.TestCase):
    def test_a_sound_that_stops_short_is_no_hit_where_it_stops(self):
        # (flux_both_ways) a hit is a sound coming in, not one going out: a noise faded in over 0.2 s that stops at once at
        # 1.7 s makes no hit there to match the drum hit at 0.5 s
        rng = np.random.default_rng(51)
        x = 0.0005 * rng.standard_normal(SR * 3)
        put(x, 0.5, 0.3 * burst(int(0.12 * SR), rng))
        n = int(0.6 * SR)
        put(x, 1.1, 0.3 * rng.standard_normal(n) * np.minimum(1.0, np.arange(n) / (0.2 * SR)))
        hits = FS.hits_of(*FS.onset_envelope(x))
        drum = max(h["height"] for h in hits if abs(h["t"] - 0.5) < 0.03)
        at_stop = [(round(h["t"], 3), h["height"]) for h in hits if 1.65 < h["t"] < 1.8]       # (a window is 46 ms long)
        self.assertTrue(all(h < 0.3 * drum for _, h in at_stop), (drum, at_stop))

    def test_hits_lie_on_their_onsets_within_two_ms(self):
        # (vertex_sign) the parabola's top puts a hit between the rows of the envelope (rows 5 ms apart)
        rng = np.random.default_rng(52)
        x = 0.0005 * rng.standard_normal(SR * 8)
        hit = burst(int(0.12 * SR), rng)
        onsets = [0.7311 + 0.6173 * k for k in range(11)]
        for t0 in onsets:
            put(x, t0, 0.3 * hit)
        hits = FS.hits_of(*FS.onset_envelope(x))
        errs = [min(abs(h["t"] - t0) for h in hits) for t0 in onsets]
        self.assertLess(max(errs), 0.002, errs)

    def test_two_unrelated_sounds_do_not_correlate(self):
        # (lag_envelopes_not_centred) mix_lag's r is a correlation: two unrelated sounds (a steady noise, a few hits each) give a
        # low one, the same sound a high one
        rng = np.random.default_rng(53)
        sounds = []
        for _ in range(2):
            x = 0.05 * rng.standard_normal(SR * 12)
            hit = burst(int(0.1 * SR), rng)
            for k in range(5):
                put(x, 0.5 + 11.0 * rng.random(), 0.8 * hit)
            sounds.append(x)
        _, r = FS.mix_lag(sounds[0], sounds[1])
        self.assertLess(r, 0.3)
        _, same = FS.mix_lag(sounds[0], sounds[0] + 0.01 * rng.standard_normal(SR * 12))
        self.assertGreater(same, 0.8)


@unittest.skipUnless(FS, "needs numpy")
class PunchAndKeepTest(unittest.TestCase):
    def test_the_punch_of_a_dropped_flash_a_few_ms_off_its_beat_goes_to_the_title_word(self):
        # (title_for_exact_beat) the look writes a flash on its frame's time (86.166 s for the beat at 86.159 s): its title word
        # is still the one whose beat is nearest (here the beat at 19.993 s, the flash on frame 600 written 19.999 s)
        moments = [{"kind": "title", "n": 2, "t": 20.22, "beat": 19.993}]
        t = ML.frame_time(600)
        out = FS.decide([flash(t), punch(t)], moments, song_hits(), skirt=[])
        p = [d for d in out if d["kind"] == "punch"][0]
        self.assertEqual((p["action"], p["frame"]), ("move", FS.frame_of_moment(20.22)))

    def test_the_title_word_of_a_flash_is_told_by_its_beat(self):
        # (title_for_on_t) of two title words in reach, the one whose beat the flash stands on, not the one sung nearest it
        moments = [{"kind": "title", "n": 1, "t": 20.23, "beat": 20.0}, {"kind": "title", "n": 2, "t": 19.85, "beat": 18.8}]
        out = FS.decide([flash(20.0), punch(20.0)], moments, song_hits(), skirt=[])
        p = [d for d in out if d["kind"] == "punch"][0]
        self.assertEqual((p["n"], p["frame"]), (1, FS.frame_of_moment(20.23)))

    def test_a_flash_on_its_moment_is_kept_and_so_is_its_punch(self):
        # (flash_keep_said_move, punch_keep_said_move) a strong hit at the head on the flash's own frame and the title word sung
        # on that frame too: nothing moves and the look is left as it was
        t = ML.frame_time(300)
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(t), punch(t)]}}
        moments = [{"kind": "section", "id": "a", "t": 10.0}, {"kind": "title", "n": 1, "t": 10.01, "beat": 10.0}]
        out = FS.decide(look["mograph"]["events"], moments, song_hits(strong=[10.0]), skirt=[])
        self.assertEqual([(d["kind"], d["action"], d["frame"]) for d in out], [("flash", "keep", 300), ("punch", "keep", 300)])
        placed = FS.place(look, out)
        self.assertEqual(placed["mograph"]["events"], look["mograph"]["events"])


@unittest.skipUnless(FS, "needs numpy")
class PlaceMoreTest(unittest.TestCase):
    def test_flares_all_dropped_leave_none(self):
        # (place_flares_left_when_all_dropped) a look whose flares are all dropped is written with flares [] (left as they were,
        # light3's five flares would come back)
        look = {"flares": [30.0, 44.467], "mograph": {"on": 1, "events": []}}
        out = FS.decide([], [{"kind": "section", "id": "inter1", "t": 11.29}], song_hits(strong=[11.3]), skirt=[],
                        flares=look["flares"])
        self.assertEqual([d["action"] for d in out], ["drop", "drop"])
        self.assertEqual(FS.place(look, out)["flares"], [])

    def test_the_flares_come_out_in_time_order(self):
        # (place_flares_unsorted) flares given out of order are written in time order
        moments = [{"kind": "section", "id": "a", "t": 12.6}, {"kind": "section", "id": "b", "t": 10.0}]
        out = FS.decide([], moments, song_hits(strong=[12.6, 10.0]), skirt=[], flares=[12.5, 10.2])
        placed = FS.place({"flares": [12.5, 10.2]}, out)
        self.assertEqual(placed["flares"], sorted(placed["flares"]))
        self.assertEqual(placed["flares"], [FS.time_of_frame(300), FS.time_of_frame(378)])

    def test_a_moved_event_keeps_its_note_and_is_written_on_its_frames_time(self):
        # (place_note_replaced, place_time_plain) the note of the plan stays in front of flashsync's, and the time is
        # mograph_layer.frame_time of the frame (round and ceil give the frame back)
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(10.0, note="title word 1 (beat 23)")]}}
        out = FS.decide(look["mograph"]["events"], [{"kind": "section", "id": "inter1", "t": 11.29}], song_hits(strong=[11.3]),
                        skirt=[])
        e = FS.place(look, out)["mograph"]["events"][0]
        self.assertTrue(e["note"].startswith("title word 1 (beat 23); flashsync: moved from"), e["note"])
        self.assertEqual(e["t"], ML.frame_time(338))
        self.assertEqual((int(round(e["t"] * 30)), int(math.ceil(e["t"] * 30))), (338, 338))

    def test_a_look_the_motion_graphics_refuse_is_refused(self):
        # (place_no_merge_check) place checks the section it writes: events with mograph.on 0 draw nothing
        look = {"mograph": {"on": 0, "events": [{"kind": "shake", "t": 20.0, "note": "landing"}]}}
        with self.assertRaises(ValueError):
            FS.place(look, [])


@unittest.skipUnless(FS, "needs numpy")
class MomentMoreTest(unittest.TestCase):
    STRUCTURE = {"beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                 "sections": [{"id": "intro", "beat": 0, "t": FIRST}, {"id": "inter1", "beat": 19, "t": FIRST + 19 * PERIOD}],
                 "hooks": []}

    def test_the_first_section_is_no_moment_and_a_return_on_a_head_is_the_head(self):
        # (moments_with_first_section, returns_at_heads_kept) the song's start is no moment; a return read on a section's
        # head is that head, once
        head = FIRST + 19 * PERIOD
        got = FS.moments_of(self.STRUCTURE, {}, [{"t": head + 0.006, "quiet_s": 1.5, "pct": 97.0}])
        self.assertEqual([(m["kind"], m.get("id")) for m in got], [("section", "inter1")])

    def test_a_beat_written_as_true_is_no_beat(self):
        # (hook_beat_bool_taken) JSON true is not beat 1
        self.assertEqual(FS.hook_beat({"beat": {"first": FIRST, "period": PERIOD}}, {"n": 1, "beat": True, "t": 5.0}), 5.0)

    def test_hits_given_out_of_order_are_told_in_time_order(self):
        # (hits_unsorted) band_returns reads the hits in time order whatever order they come in: a loud hit 0.85 s before the
        # hard one leaves no stop, also when the hits come last first
        hits = [{"t": 1.0 + 0.2143 * k, "height": 45.0 + 10.0 * (k % 3)} for k in range(60)]
        stop_from = hits[-1]["t"]
        back = stop_from + 1.7
        hits += [{"t": stop_from + 0.85, "height": 65.0}]
        hits += [{"t": back, "height": 200.0}] + [{"t": back + 0.2143 * k, "height": 50.0} for k in range(1, 20)]
        self.assertEqual(FS.band_returns(FS.Hits(hits)), [])
        self.assertEqual(FS.band_returns(FS.Hits(list(reversed(hits)))), [])


@unittest.skipUnless(FS, "needs numpy")
class TitleMoreTest(unittest.TestCase):
    E = PERIOD / 2.0

    def test_a_syllable_at_its_place_of_two_alike_goes_to_its_own(self):
        # (misfit_signed) the a of the word at its eighth (the second i and the e missing): an open vowel reads the same at
        # the a's place and the e's; its time puts it at the a's
        b = 1.2
        sung = [{"t": b + self.E, "rise_db": 20.0, "open": -15.0}, {"t": b + 3 * self.E, "rise_db": 20.0, "open": 4.0}]
        got = FS.title_start(sung, b, "iiae", step=self.E)
        self.assertEqual(got["positions"], [0, 2])

    def test_the_widest_margin_places_the_syllables(self):
        # (margin_smallest) the second i a little more open than the first (as the second singer's title word 1 reads: -12.5
        # and -14.8): read as the a it would leave a margin of 2.3 dB, as the i one of 14.5: it is the i
        b = 1.2
        sung = [{"t": b + self.E, "rise_db": 20.0, "open": -14.8}, {"t": b + 2 * self.E, "rise_db": 20.0, "open": -12.5},
                {"t": b + 4 * self.E, "rise_db": 20.0, "open": 1.9}]
        got = FS.title_start(sung, b, "iiae", step=self.E)
        self.assertEqual(got["positions"], [0, 1, 3])
        self.assertAlmostEqual(got["margin"], 14.4, places=1)

    def test_the_next_word_four_eighths_on_is_not_the_title_words(self):
        # (title_span_n) the next word's open vowel 0.86 s after the first syllable (past the word's 0.75 s): not in its run
        b = 1.2
        sung = [{"t": b + self.E, "rise_db": 20.0, "open": -15.0}, {"t": b + 4 * self.E, "rise_db": 20.0, "open": 3.0},
                {"t": b + 5 * self.E, "rise_db": 20.0, "open": 5.0}]
        got = FS.title_start(sung, b, "iiae", step=self.E)
        self.assertEqual(got["positions"], [0, 3])
        self.assertEqual(len(got["run"]), 2)

    def test_a_second_onset_in_the_last_syllable_does_not_lose_the_word(self):
        # (title_after_n) four syllables, then a second onset in the last one 77 ms on (a re-attack): the run is the word's four
        b = 1.2
        sung = [{"t": b + k * self.E + self.E, "rise_db": 20.0, "open": o} for k, o in enumerate((-15.0, -14.0, 5.0, 3.0))]
        sung.append({"t": b + 4 * self.E + 0.077, "rise_db": 14.0, "open": 3.0})
        got = FS.title_start(sung, b, "iiae", step=self.E)
        self.assertIsNotNone(got)
        self.assertEqual((got["t"], got["positions"]), (b + self.E, [0, 1, 2, 3]))

    def test_vowels_all_close_or_all_open_cannot_tell_the_word(self):
        # (vowels_all_close_ok)
        for v in ("iiii", "aeo"):
            with self.assertRaises(ValueError):
                FS.title_start([], 1.0, v)


@unittest.skipUnless(FS, "needs numpy")
class VoiceMoreTest(unittest.TestCase):
    def test_the_vowel_is_read_after_its_glide_in(self):
        # (vowel_read_early) a close vowel coming in through 25 ms of an open one (the consonant's glide): read close
        rng = np.random.default_rng(31)
        x = 0.003 * rng.standard_normal(int(1.5 * SR))
        put(x, 0.5, np.concatenate([vowel(0.025, "a"), vowel(0.25, "i", attack=0.002)]))
        sy = [y for y in FS.syllables_of(x) if 0.45 < y["t"] < 0.6]
        self.assertEqual(len(sy), 1, sy)
        self.assertLess(sy[0]["open"], -5.0, sy)

    def test_a_vowel_soon_after_a_loud_note_has_its_own_onset(self):
        # (onset_low_at_window_start) a note that ends 40 ms before the next vowel (a consonant's stop): the vowel's onset is
        # read from the gap, not from the note before
        rng = np.random.default_rng(32)
        x = 0.003 * rng.standard_normal(int(2.0 * SR))
        put(x, 0.6, tone(0.36, 262.0))                       # ends at 0.96 s
        put(x, 1.0, tone(0.3, 294.0, attack=0.0005))
        t, db = FS.voice_level(x)
        got = FS.first_syllable(t, db, 1.05, search=(-0.1, 0.1))
        self.assertIsNotNone(got)
        self.assertLess(abs(got["t"] - 1.0), 0.002, got)

    def test_a_dip_of_eight_db_in_a_held_vowel_is_no_syllable(self):
        # (rise_db_low) a held vowel that dips by 8 dB for 40 ms and comes back: one syllable
        rng = np.random.default_rng(33)
        x = 0.003 * rng.standard_normal(int(2.0 * SR))
        v = vowel(0.8, "a")
        n0, n1 = int(0.35 * SR), int(0.39 * SR)
        v[n0:n1] *= 10 ** (-8.0 / 20.0)
        put(x, 0.5, v)
        sy = [y["t"] for y in FS.syllables_of(x) if 0.4 < y["t"] < 1.4]
        self.assertEqual(len(sy), 1, sy)


@unittest.skipUnless(FS, "needs numpy")
class MeasureMoreTest(unittest.TestCase):
    def files(self, d, sounds, docs, scale):
        out = {}
        for name, x in sounds.items():
            out[name] = os.path.join(d, name + ".wav")
            write_wav(out[name], x, scale)
        for name, doc in docs.items():
            out[name] = os.path.join(d, name + ".json")
            with open(out[name], "w", encoding="utf-8") as f:
                json.dump(doc, f)
        return out

    def run_measure(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = FS.main(["measure"] + args)
        return code, said.getvalue()

    def test_the_band_returns_on_the_backing_while_the_voice_sings_through_the_stop(self):
        # (returns_from_mix) as under the last title word: the drums stop for four beats while the voice sings on, then come
        # back hard; the mix has the voice's onsets in the stop, the backing has none
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(41)
        seconds = 14.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(0, 20):
            put(backing, FIRST + b * PERIOD, 0.2 * hit)
        back = FIRST + 24 * PERIOD
        backing[int((FIRST + 19 * PERIOD + 0.2) * SR):int(back * SR)] = 0.0          # the band stops (after beat 19's hit)
        put(backing, back, 1.0 * burst(int(0.15 * SR), rng))                         # and comes back hard on beat 24
        for b in range(25, 31):
            put(backing, FIRST + b * PERIOD, 0.2 * hit)
        voice = 0.0003 * rng.standard_normal(int(seconds * SR))
        for k in range(8):                                                           # eighths through the stop
            put(voice, FIRST + 20 * PERIOD + k * PERIOD / 2.0, 0.6 * tone(0.17, 262.0 + 20 * k, attack=0.0005))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "intro", "beat": 0, "t": FIRST}, {"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}],
                     "hooks": [], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": []}}
        with tempfile.TemporaryDirectory() as d:
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            f = self.files(d, {"mix": backing + voice, "voice": voice}, {"structure": structure, "look": look}, scale)
            out = os.path.join(d, "m.json")
            self.assertEqual(self.run_measure([f["mix"], f["voice"], f["structure"], f["look"], out])[0], 0)
            with open(out, encoding="utf-8") as fh:
                rep = json.load(fh)
        self.assertTrue(any(abs(r["t"] - back) < 0.01 for r in rep["returns"]), rep["returns"])

    def test_a_voice_file_that_lies_early_is_read_where_it_is_in_the_mix(self):
        # (voice_not_shifted) the separated voice 20 ms ahead of the mix: the title word's first syllable is read in the mix's time
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(42)
        seconds = 10.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(22):
            put(backing, FIRST + b * PERIOD, 0.15 * hit)
        beat = FIRST + 12 * PERIOD
        voice = 0.003 * rng.standard_normal(int(seconds * SR))
        put(voice, beat - 0.10, vowel(0.10 + PERIOD / 2.0 - 0.04, "a"))
        for k, v in enumerate("iiae"):
            put(voice, beat + (k + 1) * PERIOD / 2.0, vowel(PERIOD / 2.0 - 0.04, v))
        early = FS.shifted(voice, -int(0.020 * SR))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}], "hooks": [{"n": 1, "beat": 12, "t": beat}],
                     "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": []}}
        with tempfile.TemporaryDirectory() as d:
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            f = self.files(d, {"mix": backing + voice, "voice": early}, {"structure": structure, "look": look}, scale)
            out = os.path.join(d, "m.json")
            self.assertEqual(self.run_measure([f["mix"], f["voice"], f["structure"], f["look"], out, "--title-vowels", "iiae"])[0], 0)
            with open(out, encoding="utf-8") as fh:
                rep = json.load(fh)
        self.assertEqual(rep["align"]["lag_samples"], int(0.020 * SR))
        title = [m for m in rep["moments"] if m["kind"] == "title"][0]
        self.assertLess(abs(title["t"] - (beat + PERIOD / 2.0)), 0.006, title)

    def test_another_sources_backing_hits_are_those_of_the_reference_measure(self):
        # (backing_from_ref_of_new, span_whole_sound) --backing-from gives the very hits (and percentiles) the measure of that pair
        # gives, whatever the new mix is
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(43)
        seconds = 12.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(28):
            put(backing, FIRST + b * PERIOD, (0.1 + 0.3 * rng.random()) * hit)
        v0 = 0.0003 * rng.standard_normal(int(seconds * SR))
        put(v0, 3.0, tone(0.5, 262.0))
        v1 = 0.0003 * rng.standard_normal(int(seconds * SR))
        put(v1, 3.0, 3.0 * tone(1.5, 330.0))                                          # a louder, longer voice
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}], "hooks": [], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": []}}
        with tempfile.TemporaryDirectory() as d:
            scale = 0.5 / max(np.abs(backing + v1).max(), 1e-9)
            f = self.files(d, {"mix0": backing + v0, "voice0": v0, "mix1": np.concatenate([backing + v1, np.zeros(int(0.7 * SR))]),
                               "voice1": np.concatenate([v1, np.zeros(int(0.7 * SR))])}, {"structure": structure, "look": look}, scale)
            a, b = os.path.join(d, "a.json"), os.path.join(d, "b.json")
            self.assertEqual(self.run_measure([f["mix0"], f["voice0"], f["structure"], f["look"], a])[0], 0)
            self.assertEqual(self.run_measure([f["mix1"], f["voice1"], f["structure"], f["look"], b,
                                               "--backing-from", f["mix0"], f["voice0"]])[0], 0)
            reps = []
            for p in (a, b):
                with open(p, encoding="utf-8") as fh:
                    reps.append(json.load(fh))
        self.assertEqual(reps[1]["hits"]["backing"], reps[0]["hits"]["backing"])
        self.assertNotEqual(reps[1]["hits"]["backing_own"], reps[0]["hits"]["backing"])

    def test_a_reference_a_frame_and_a_half_off_is_refused(self):
        # (reference_guard_two_frames) the guard is a frame: a mix 50 ms off the reference is refused
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(44)
        seconds = 12.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for k in range(40):
            put(backing, 0.5 + 0.27 * k + 0.05 * rng.random(), (0.1 + rng.random()) * hit)
        voice = 0.0003 * rng.standard_normal(int(seconds * SR))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}], "hooks": [], "skirt": []}
        look = {"flares": [], "mograph": {"on": 1, "events": []}}
        with tempfile.TemporaryDirectory() as d:
            scale = 0.8 / max(np.abs(backing).max(), 1e-9)
            f = self.files(d, {"mix": backing + voice, "voice": voice,
                               "ref": np.concatenate([np.zeros(int(0.050 * SR)), backing + voice])[:len(backing)]},
                           {"structure": structure, "look": look}, scale)
            code, said = self.run_measure([f["mix"], f["voice"], f["structure"], f["look"], os.path.join(d, "x.json"),
                                           "--reference", f["ref"]])
        self.assertEqual(code, 2, said)
        self.assertIn("structure", said)


@unittest.skipUnless(FS, "needs numpy")
class ReportTest(unittest.TestCase):
    def report(self):
        moments = [{"kind": "title", "n": 1, "t": 10.23, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29}]
        for m in moments:
            m["near"] = {"backing": {"pct": 91.0}, "mix": {"pct": 92.0}, "voice": None}
        decisions = FS.decide([flash(ML.frame_time(300))], moments, song_hits(strong=[11.3]), skirt=[])
        for d in decisions:
            d["at_old"] = {"backing": {"pct": 58.0}, "mix": {"pct": 51.0}, "voice": None}
            d["old_from_voice_ms"] = round((d["old_frame"] / 30.0 - d["title"]["t"]) * 1000.0, 1)
        return {"settings": {"fps": 30, "strong": 90.0, "near_frames": 1, "reach_frames": 2, "skirt_gap": 0.5},
                "moments": moments, "decisions": decisions}

    def test_the_table_writes_backing_then_mix_then_voice(self):
        # (table_columns_swapped)
        text = FS.table_md(self.report())
        self.assertIn("| 58 / 51 / - |", text)
        self.assertIn("| -230 ms |", text)

    def test_compare_writes_b_less_a_and_the_decisions_in_order(self):
        # (compare_diff_sign, compare_decisions_swapped) B sings 43 ms earlier than A; B drops the flash A moves
        a = self.report()
        b = self.report()
        b["moments"][0] = dict(b["moments"][0], t=10.187)
        b["decisions"][0] = dict(b["decisions"][0], action="drop", frame=None)
        for rep in (a, b):
            rep["inputs"] = {"mix": "mix.wav", "voice": "voice.wav"}
        text = FS.compare_md(a, b, ["A", "B"])
        self.assertIn("| -43 ms |", text)
        self.assertIn("| 動かす → 338 | 削る |", text)


@unittest.skipUnless(FS, "needs numpy")
class PunchRuleTest(unittest.TestCase):
    """the punch rule of 2026-10-21 (each punch on the title word its flash stood for, as sung): what the look's notes and the
    table say of it (punch_flash_action_said_move, fate_dropped_said_stays, fate_moment_left_out) and a punch with no title word
    to go to (punch_no_title_kept)"""
    MOMENTS = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29},
               {"kind": "title", "n": 2, "t": 19.89, "beat": 20.0}]

    def test_a_punch_with_no_title_word_as_sung_is_dropped(self):
        out = FS.decide([flash(10.0), punch(10.0)], [{"kind": "section", "id": "inter1", "t": 11.29}], song_hits(strong=[11.3]),
                        skirt=[])
        f, p = out
        self.assertEqual((f["action"], p["action"], p["frame"], p["why"]), ("move", "drop", None, "no_title"))
        placed = FS.place({"flares": [], "mograph": {"on": 1, "events": [flash(10.0), punch(10.0)]}}, out)
        self.assertEqual([e["kind"] for e in placed["mograph"]["events"]], ["flash"])

    def test_the_punchs_note_says_what_became_of_its_flash(self):
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(10.0), punch(10.0, note="title word 1 (beat 23)"),
                                                            flash(20.0), punch(20.0, note="title word 2 (beat 46)")]}}
        out = FS.decide(look["mograph"]["events"], self.MOMENTS, song_hits(strong=[11.3]), skirt=[])
        notes = {round(e["t"] * 30): e["note"] for e in FS.place(look, out)["mograph"]["events"] if e["kind"] == "punch"}
        self.assertEqual(notes[FS.frame_of_moment(9.893)], "title word 1 (beat 23); flashsync: moved from 10.000 s, "
                                                           "its flash goes to the head of inter1: on title word 1 as sung")
        self.assertEqual(notes[FS.frame_of_moment(19.89)], "title word 2 (beat 46); flashsync: moved from 20.000 s, "
                                                           "its flash is dropped: on title word 2 as sung")

    def test_the_table_says_the_punch_marks_the_title_word_and_what_became_of_its_flash(self):
        out = FS.decide([flash(10.0), punch(10.0), flash(20.0), punch(20.0)], self.MOMENTS, song_hits(strong=[11.3]), skirt=[])
        for d in out:
            d["at_old"] = {"backing": None, "mix": None, "voice": None}
        moments = [dict(m, near={"backing": None, "mix": None, "voice": None}) for m in self.MOMENTS]
        text = FS.table_md({"settings": {"fps": 30, "strong": 90.0, "near_frames": 1, "reach_frames": 2, "skirt_gap": 0.5},
                            "moments": moments, "decisions": out})
        self.assertIn("パンチは題名の語 1 の 1 音目を歌うコマへ（光は動かした）", text)
        self.assertIn("パンチは題名の語 2 の 1 音目を歌うコマへ（光は削った）", text)


@unittest.skipUnless(FS, "needs numpy")
class MeasureReportTest(unittest.TestCase):
    def test_the_old_light_is_said_before_or_after_the_voice(self):
        # (old_from_voice_sign) measure writes how far the old light is from the title word's first syllable: negative = before
        if not FFMPEG:
            self.skipTest("needs ffmpeg")
        rng = np.random.default_rng(45)
        seconds = 10.0
        backing = 0.002 * rng.standard_normal(int(seconds * SR))
        hit = burst(int(0.1 * SR), rng)
        for b in range(22):
            put(backing, FIRST + b * PERIOD, 0.15 * hit)
        beat = FIRST + 12 * PERIOD
        voice = 0.003 * rng.standard_normal(int(seconds * SR))
        for k, v in enumerate("iiae"):
            put(voice, beat + (k + 1) * PERIOD / 2.0, vowel(PERIOD / 2.0 - 0.04, v))
        structure = {"seconds": seconds, "beat": {"first": FIRST, "period": PERIOD, "per_bar": 4},
                     "sections": [{"id": "chorus1", "beat": 4, "t": FIRST + 4 * PERIOD}], "hooks": [{"n": 1, "beat": 12, "t": beat}],
                     "skirt": []}
        t = ML.frame_time(ML.frame_of(beat, 30))
        look = {"flares": [], "mograph": {"on": 1, "events": [flash(t), punch(t)]}}
        with tempfile.TemporaryDirectory() as d:
            paths = {}
            scale = 0.8 / max(np.abs(backing + voice).max(), 1e-9)
            for name, x in (("mix", backing + voice), ("voice", voice)):
                paths[name] = os.path.join(d, name + ".wav")
                write_wav(paths[name], x, scale)
            for name, doc in (("structure", structure), ("look", look)):
                paths[name] = os.path.join(d, name + ".json")
                with open(paths[name], "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
            out = os.path.join(d, "m.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["measure", paths["mix"], paths["voice"], paths["structure"], paths["look"], out,
                                          "--title-vowels", "iiae"]), 0)
            with open(out, encoding="utf-8") as fh:
                rep = json.load(fh)
        f0 = [x for x in rep["decisions"] if x["kind"] == "flash"][0]
        self.assertLess(f0["old_from_voice_ms"], -150.0, f0)


if __name__ == "__main__":
    unittest.main()
