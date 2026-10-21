"""tools/flash_sync.py: the flashes of a look put on moments of the song a viewer hears (a strong hit of the backing at the
head of a section, at the band's return or where the title word is sung), or dropped; the punches on their frames with them.
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

    def test_the_band_returns_where_its_low_end_comes_back_after_a_bar_without_it(self):
        rng = np.random.default_rng(4)
        bars = [FIRST + 4 * k * PERIOD for k in range(10)]
        x = 0.001 * rng.standard_normal(int(18.0 * SR))
        n = int(0.12 * SR)
        k = np.arange(n) / float(SR)
        kick = np.sin(2 * np.pi * 60 * k) * np.exp(-k / 0.05)
        for b in range(40):
            if not 20 <= b < 24:                          # bar 5 (beats 20-23) without the kick
                put(x, FIRST + b * PERIOD, kick)
        got = FS.band_returns(x, bars)
        self.assertEqual([round(r["t"], 3) for r in got], [round(bars[6], 3)])
        self.assertGreaterEqual(got[0]["drop_db"], FS.RETURN_DB)
        for b in range(20, 24):                           # a kick a little softer: no return
            put(x, FIRST + b * PERIOD, 0.7 * kick)
        self.assertEqual(FS.band_returns(x, bars), [])


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

    def test_a_flash_moves_to_the_nearest_moment_with_a_strong_hit_on_it_and_its_punch_with_it(self):
        moments = [{"kind": "title", "n": 1, "t": 9.893, "beat": 10.0}, {"kind": "section", "id": "inter1", "t": 11.29}]
        events = [flash(10.0), punch(10.0), punch(5.0)]
        out = FS.decide(events, moments, self.hits(strong=[11.30]), skirt=[])
        f = [d for d in out if d["kind"] == "flash"][0]
        self.assertEqual(f["action"], "move")
        self.assertEqual(f["frame"], FS.frame_of_moment(11.29))
        self.assertEqual(f["moment"]["kind"], "section")
        p = [d for d in out if d["kind"] == "punch" and d["old_frame"] == 300][0]
        self.assertEqual((p["action"], p["frame"]), ("move", f["frame"]))
        other = [d for d in out if d["kind"] == "punch" and d["old_frame"] == 150]
        self.assertEqual(other, [])                          # a punch on no flash's frame is not the tool's

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
        self.assertEqual(frames, sorted([("punch", 150), ("flash", 338), ("punch", 338), ("punch", 596), ("shake", 600)]))
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
            out = os.path.join(d, "measure.json")
            with contextlib.redirect_stdout(io.StringIO()):
                code = FS.main(["measure", mix_path, voice_path, paths["structure"], paths["look"], out])
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
            self.assertEqual(sorted(ML.frame_of(e["t"], 30) for e in placed["mograph"]["events"]),
                             [f0["frame"], f0["frame"]])
            table = os.path.join(d, "table.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FS.main(["table", out, table]), 0)
            with open(table, encoding="utf-8") as f:
                self.assertIn("inter1", f.read())


if __name__ == "__main__":
    unittest.main()
