"""Measure how the mouth of a face motion goes with the singing voice, with times taken from the voice alone.

    python tools/lip_check.py VOCAL FACE.vmd [FACE.vmd ...] [--report r.json] [--lines LINES.tsv] [--region T0 T1]
                              [--align a.json [--sheet PREFIX --sample 40 --seed 1]] [--view T0 T1 PNG]
                              [--area 1,0.02,0.28,0.63,0.68]

Why (stage 6 lipsync review, 2026-10-17): tools/lip_sync.py places the mouth from its own alignment of the lyrics to
the voice, and its numbers measured the mouth against the vowel onsets of that same alignment: the lag it found (the
mouth half open 37 ms before the vowel) is the lead it was built with (50 ms, less the smoothing), and the hand-made
mouth's lead against that alignment (74 ms) is the lag of the guide that pulls the alignment to the hand-made keys
(70 ms).  Neither says whether the syllables are where the voice sings them.  This tool takes the times from the voice
alone; it reads an alignment only to check that alignment (--align).

1. The voice: VOCAL (the separated singing voice, anything ffmpeg reads) at SR, every 10 ms (windows of WIN samples
   centred on the row's time): the power in BAND (300 to 3500 Hz, the voice onsets of HANDOVER 2026-10-06), its level
   (dB re the 99th percentile of the song) and the onset strength, the positive spectral flux of the log power.
   A flux peak is a row whose flux is the largest within PEAK_SPACING on each side and above FLUX_FLOOR times the
   median flux where the voice sounds.  A voice onset is a flux peak where the level rises by RISE_DB or more from the
   quietest of the PRE seconds before to the loudest of the POST seconds after, to above SOUND_DB and to within FULL[1]
   of the loudest of the FULL[0] seconds after (the vowel, not the hum of m or the hiss of s before it): a syllable
   that starts after a consonant or a rest (a legato syllable makes none).  On the synthetic song of the tests the
   onsets fall within 30 ms of the vowel's start (after k at its burst, 15 ms before).
2. The mouth: each FACE's visible opening O(f) = min(1, sum of the vowel morphs' weights times AREA), AREA the open
   area of each shape on the render model with あ = 1 (Sour's Rin, a rest-pose render, stage 6 lipsync: い shows only
   the teeth), linear between keys as MMD; frame f is shown at (f + SHOWN) / FPS s (the MV: 240 fps subframes folded
   at shutter 0.5, tools/mv_look.py).  A rise is a swing of O from a trough to the next peak of at least MOVE (a
   zigzag with that threshold); its time is where O first crosses half way.
3. Per voice onset, the rise of each FACE paired with it (one to one, the nearest first, within MATCH): the lag is the
   onset's time minus the rise's time (positive: the mouth first).  Per FACE: the share of onsets paired, the lags
   (median, p10 to p90), the share of the paired onsets with the mouth later than LATE (45 ms) or earlier than EARLY
   (125 ms) (ITU-R BT.1359-1: from the sound 45 ms before the picture to 125 ms after it goes unnoticed), the share of
   rises with no onset (the mouth opens where no syllable starts after a consonant or a rest; legato syllables make
   no onset, so this is not zero for a good mouth), and the same lags over the onsets every FACE pairs ("common").
   The triggered average: O averaged over all onsets (no pairing), and where it crosses half way from its low before
   the onset to its high after it.  The same over the onsets whose vowel sounds open (OPEN over ONSET_VOWEL after the
   onset, split at Otsu's threshold over all onsets, see --align): い and う open the mouth little (い = い + あ 0.3 is
   0.32 of あ), so after a close vowel the nearest rise is often the next syllable's and the lag reads late; the open
   vowels are where the mouth must open visibly.
4. Over the song: the normalised cross-correlation of each FACE's opening speed (the positive part of dO/dt) with the
   flux, on the rows near the singing: the lag of its peak (positive: the mouth first) and r.
5. The states: the share (and the longest spans) of the time the voice clearly sings (above LOUD_DB) with the mouth
   looking shut (O below SHUT), and of the silences (below QUIET_DB for SILENCE_RUN or longer, less LATE at their start
   and EARLY at their end, where the mouth may still be closing or already opening) with the mouth open (O above
   OPEN); with --lines, also inside and outside the lines.  The jumps: the frames where the opening changes by more
   than 0.4 from the frame before (a snap the eye sees).
--lines (the lyric lines file of lip_sync; only the start and end of each row are read): the lags line by line, to
   find a line whose mouth sits a syllable off.  --region T0 T1 (repeated): the lags inside a span of the song.
--align (lip_sync --align-out): checks of the alignment against the voice.
   * onsets: each aligned vowel start that begins a syllable (after a consonant or at a word's start) against the
     nearest voice onset (positive: the aligned start is later); the same with the starts moved 100 ms both ways is
     what chance gives.  A syllable sung legato (r, w, y, n often) makes no onset, so the share is not 1 for a good
     alignment.  The aligned vowels with a voice onset well inside them (INSIDE): two notes under one syllable, either
     sung so (a vowel carried over two notes) or merged by the alignment (its neighbour squeezed): look at them (--view).
   * vowels: two spectral levels of each aligned vowel over its middle where the voice sounds: OPEN, the level of
     700 to 1500 Hz over 300 to 700 Hz (the first formant: high for あ え お, low for い う), and FRONT, 1800 to 3500 Hz
     over 700 to 1500 Hz (the second formant: high for え, low for あ お).  Each is split in two where the song's vowels
     part best (Otsu's threshold over all of them, the labels unread): a vowel sounds close (い う), open and front
     (え) or open and back (あ お).  The share whose label agrees (close against open, and the three classes), the
     counts per vowel, and per line whether the labels agree better shifted by one mora on close against open (a line
     aligned a syllable off does).  On the separated voice of the MV, close against open agrees for 0.89 of the vowels
     and あ is often heard front: the three classes are a coarse check.
--sheet PREFIX: pages PREFIX_01.png ... of tiles, one per syllable drawn at random (--sample, --seed) from the aligned
   syllables that begin after a consonant or at a word's start: the spectrogram of the voice around it (0 to 5 kHz),
   the alignment's boundaries (c0 blue, v0 green, v1 red; the drawn syllable bold), the voice onsets (orange marks on
   top), the flux peaks (black ticks at the bottom), the level (blue) and each FACE's opening as shown (the first
   grey, the second red).  PREFIX.json lists the tiles, to count the hits by eye.  Needs Pillow.
--view T0 T1 PNG (repeated): one span of the song drawn as the tiles are (500 pixels a second), to look at a place.

The report (--report; in short on stdout) holds all of it.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli.formats import vmd  # noqa: E402

FPS = 30.0
SHOWN = 0.1875                  # frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py)
SR = 16000
HOP = 160                       # 10 ms
STEP = HOP / float(SR)
WIN = 512                       # 32 ms
BAND = (300.0, 3500.0)
SOUND_DB = -30.0                # the voice sounds above this (dB re the 99th percentile)
PEAK_SPACING = 0.05             # s: a flux peak is the largest within this on each side
FLUX_FLOOR = 1.0                # a flux peak is above this times the median flux where the voice sounds
RISE_DB = 6.0
PRE = 0.04                      # s before a flux peak where the level is lowest ...
POST = 0.03                     # s ... and after it where it is highest
FULL = (0.25, 6.0)              # the level after an onset is within 6 dB of the loudest of the 0.25 s after it (not the
                                # hum of m or the hiss of s before the vowel)
VOWELS = ("あ", "い", "う", "え", "お")
AREA = (1.0, 0.02, 0.28, 0.63, 0.68)     # the open area of あ い う え お on Sour's Rin (stage 6 lipsync, shape_area.json)
MOVE = 0.15                     # a rise of the opening is at least this
MATCH = 0.20                    # s: an onset and a rise further apart are not paired
LATE = 0.045                    # s: the mouth this much after the sound is noticed (ITU-R BT.1359-1)
EARLY = 0.125                   # s: the mouth this much before the sound is noticed
TRIGGER = 0.40                  # s each side of the onsets for the triggered average
XCORR_LAG = 0.30                # s
NEAR_SINGING = 0.5              # s: the cross-correlation is taken within this of a row where the voice sounds
CHANCE_SHIFT = 0.10             # s: the aligned starts moved this much both ways give the chance agreement
INSIDE = (0.08, 0.05)           # s: a voice onset this far after an aligned vowel's start and before its end is inside it
ONSET_VOWEL = (0.03, 0.13)      # s after an onset over which its vowel is heard (OPEN, as for the aligned vowels)
LOUD_DB = -20.0                 # the voice clearly sings above this ...
QUIET_DB = -40.0                # ... and is silent below this
SHUT = 0.1                      # the mouth looks shut below this opening ...
OPEN = 0.35                     # ... and open above this
SILENCE_RUN = 0.15              # s: a silence counts from this long
OPEN_BANDS = ((300.0, 700.0), (700.0, 1500.0))      # OPEN = the level of the second over the first
FRONT_BANDS = ((700.0, 1500.0), (1800.0, 3500.0))   # FRONT = the level of the second over the first
CLASS_OF = {"a": "open back", "o": "open back", "e": "open front", "i": "close", "u": "close"}
SHIFT_GAIN = 0.2                # a line fits better shifted by one mora when the share agreeing grows by this
SHIFT_MIN = 6                   # vowels a line needs for the shift test
FONTS = ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


# ---- the voice -------------------------------------------------------------------------------

def read_sound(path):
    """the sound of `path` as mono float32 at SR, read with ffmpeg"""
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def band_power(x, win=WIN, hop=HOP, band=BAND):
    """[rows, bins] power in the band, row k centred on k * hop samples, and the bins' frequencies"""
    x = np.asarray(x, np.float32)
    pad = np.pad(x, (win // 2, win // 2))
    n = max(0, 1 + (len(pad) - win) // hop)
    if n < 10:
        raise ValueError("the voice is too short")
    freqs = np.fft.rfftfreq(win, 1.0 / SR)
    keep = (freqs >= band[0]) & (freqs < band[1])
    w = np.hanning(win).astype(np.float32)
    out = np.zeros((n, int(keep.sum())), np.float32)
    for s0 in range(0, n, 2000):
        s1 = min(n, s0 + 2000)
        idx = (np.arange(s0, s1) * hop)[:, None] + np.arange(win)[None, :]
        spec = np.fft.rfft(pad[idx] * w, axis=1)[:, keep]
        out[s0:s1] = spec.real ** 2 + spec.imag ** 2
    return out, freqs[keep]


class Voice:
    """level (dB re the 99th percentile), flux and the power of the band, every STEP s"""

    def __init__(self, x):
        self.power, self.freqs = band_power(x)
        db = 10.0 * np.log10(self.power.sum(axis=1) + 1e-12)
        self.level = db - float(np.percentile(db, 99))
        sounding = self.level > SOUND_DB
        ref = float(np.median(self.power[sounding])) if sounding.sum() > 10 else float(np.median(self.power))
        lg = np.log1p(self.power / (ref + 1e-20))
        self.flux = np.concatenate([[0.0], np.maximum(np.diff(lg, axis=0), 0.0).sum(axis=1)])
        self.flux_median = float(np.median(self.flux[sounding])) if sounding.sum() > 10 else float(np.median(self.flux))

    @property
    def rows(self):
        return len(self.level)

    def band_level(self, rows, band):
        """dB of the power within band (Hz) on the given rows"""
        keep = (self.freqs >= band[0]) & (self.freqs < band[1])
        return 10.0 * np.log10(self.power[rows][:, keep].sum(axis=1) + 1e-12)


def _window_extreme(values, before, after, fn):
    """fn (np.min or np.max) of values over [k - before, k + after] for every k"""
    padded = np.pad(values, (before, after), mode="edge")
    return fn(np.lib.stride_tricks.sliding_window_view(padded, before + after + 1), axis=1)


def flux_peaks(voice):
    """rows of the flux peaks (see the module docstring)"""
    s = int(round(PEAK_SPACING / STEP))
    top = _window_extreme(voice.flux, s, s, np.max)
    floor = FLUX_FLOOR * voice.flux_median
    return np.where((voice.flux >= top) & (voice.flux > floor) & (voice.flux > 0))[0]


def voice_onsets(voice):
    """the onset times (s) of the syllables that start after a consonant or a rest"""
    peaks = flux_peaks(voice)
    pre = _window_extreme(voice.level, int(round(PRE / STEP)), 0, np.min)
    post = _window_extreme(voice.level, 0, int(round(POST / STEP)), np.max)
    full = _window_extreme(voice.level, 0, int(round(FULL[0] / STEP)), np.max)
    keep = [k for k in peaks if post[k] - pre[k] >= RISE_DB and post[k] > SOUND_DB and post[k] >= full[k] - FULL[1]]
    return np.asarray(keep, float) * STEP


# ---- the mouth -------------------------------------------------------------------------------

def vowel_tracks(motion, frames):
    """[frames, 5] weights of あ い う え お, linear between keys, held before the first and after the last"""
    keys = {}
    for k in motion.morphs:
        if k.name in VOWELS:
            keys.setdefault(k.name, {})[k.frame] = float(k.weight)
    out = np.zeros((frames, 5))
    for j, name in enumerate(VOWELS):
        ks = sorted(keys.get(name, {}).items())
        if ks:
            out[:, j] = np.interp(np.arange(frames), [f for f, _ in ks], [w for _, w in ks])
    return out


def opening(motion, frames, area=AREA):
    return np.minimum(1.0, vowel_tracks(motion, frames) @ np.asarray(area, float))


def rises(o, move=MOVE):
    """[(trough frame, peak frame)] of the swings up of at least `move` (a zigzag with that threshold)"""
    out = []
    lo, hi = 0, None
    for i in range(1, len(o)):
        if hi is None:
            if o[i] <= o[lo]:
                lo = i
            elif o[i] - o[lo] >= move:
                hi = i
        else:
            if o[i] > o[hi]:
                hi = i
            elif o[hi] - o[i] >= move:
                out.append((lo, hi))
                lo, hi = i, None
    if hi is not None:
        out.append((lo, hi))
    return out


def rise_times(o, move=MOVE):
    """the shown time (s) where each rise first crosses half way"""
    out = []
    for lo, hi in rises(o, move):
        half = o[lo] + 0.5 * (o[hi] - o[lo])
        seg = o[lo:hi + 1]
        j = int(np.argmax(seg >= half))
        if j == 0:
            f = float(lo)
        else:
            a, b = seg[j - 1], seg[j]
            f = lo + j - 1 + ((half - a) / (b - a) if b > a else 1.0)
        out.append((f + SHOWN) / FPS)
    return np.asarray(out, float)


def pair(onsets, events, match=MATCH):
    """[(onset index, event index)] one to one, the nearest pairs first, within match"""
    cand = []
    for i, t in enumerate(onsets):
        lo = int(np.searchsorted(events, t - match))
        hi = int(np.searchsorted(events, t + match, side="right"))
        for j in range(lo, hi):
            cand.append((abs(t - events[j]), i, j))
    cand.sort()
    used_i, used_j, out = set(), set(), []
    for _, i, j in cand:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            out.append((i, j))
    return sorted(out)


def _stats(values):
    v = np.asarray(values, float)
    if not len(v):
        return None
    return {"n": int(len(v)), "median": round(float(np.median(v)), 1), "p10": round(float(np.percentile(v, 10)), 1),
            "p25": round(float(np.percentile(v, 25)), 1), "p75": round(float(np.percentile(v, 75)), 1),
            "p90": round(float(np.percentile(v, 90)), 1)}


def lag_summary(lags):
    """the lags (ms, positive: the mouth first) and the shares noticed late or early"""
    lags = np.asarray(lags, float)
    out = {"lag_ms": _stats(lags)}
    if len(lags):
        out["share_mouth_late_over_45ms"] = round(float((lags < -1000.0 * LATE).mean()), 3)
        out["share_mouth_early_over_125ms"] = round(float((lags > 1000.0 * EARLY).mean()), 3)
    return out


def lag_measure(onsets, events, match=MATCH):
    """the pairing of the voice onsets with the mouth's rises: the summary, the pairs and their lags (ms)"""
    pairs = pair(onsets, events, match)
    lags = np.array([1000.0 * (onsets[i] - events[j]) for i, j in pairs])
    out = {"onsets": int(len(onsets)), "rises": int(len(events)), "paired": int(len(pairs)),
           "share_onsets_paired": round(len(pairs) / max(1, len(onsets)), 3),
           "share_rises_without_onset": round(1.0 - len(pairs) / max(1, len(events)), 3)}
    out.update(lag_summary(lags))
    return out, pairs, lags


def triggered(o, onsets):
    """O averaged around the onsets; the ms before the onset where it crosses half way from its low to its high (the
    high within 100 ms before to 300 ms after the onset, the low within 300 ms before the high; positive: the mouth
    first), or None"""
    if not len(onsets):
        return None
    shown = (np.arange(len(o)) + SHOWN) / FPS
    grid = np.arange(-TRIGGER, TRIGGER + STEP / 2, STEP)
    avg = np.mean([np.interp(t + grid, shown, o) for t in onsets], axis=0)
    mid = len(grid) // 2
    a = mid - int(round(0.1 / STEP))
    i1 = a + int(np.argmax(avg[a:mid + int(round(0.3 / STEP)) + 1]))
    b = max(0, i1 - int(round(0.3 / STEP)))
    i0 = b + int(np.argmin(avg[b:i1 + 1]))
    if i1 <= i0 or avg[i1] - avg[i0] < 0.02:
        return {"half_before_onset_ms": None, "low": round(float(avg[i0]), 3), "high": round(float(avg[i1]), 3)}
    half = avg[i0] + 0.5 * (avg[i1] - avg[i0])
    k = i0 + int(np.argmax(avg[i0:i1 + 1] >= half))
    t = grid[k - 1] + (half - avg[k - 1]) / (avg[k] - avg[k - 1]) * STEP if k > i0 and avg[k] > avg[k - 1] else grid[k]
    return {"half_before_onset_ms": round(-1000.0 * float(t), 1), "low": round(float(avg[i0]), 3),
            "high": round(float(avg[i1]), 3)}


def onset_open(voice, onsets):
    """for each onset, whether the vowel after it sounds open (あ え お) rather than close (い う): OPEN over ONSET_VOWEL
    after it, split at Otsu's threshold over all the onsets; None where it cannot be heard"""
    levels = []
    for t in onsets:
        rows = np.arange(int(round((t + ONSET_VOWEL[0]) / STEP)), int(round((t + ONSET_VOWEL[1]) / STEP)))
        rows = rows[(rows >= 0) & (rows < voice.rows)]
        rows = rows[voice.level[rows] > SOUND_DB]
        if len(rows) < 3:
            levels.append(None)
            continue
        levels.append(float(np.mean(voice.band_level(rows, OPEN_BANDS[1]) - voice.band_level(rows, OPEN_BANDS[0]))))
    known = [v for v in levels if v is not None]
    if len(known) < 4:
        return [None] * len(onsets)
    t_open = otsu(known)
    return [None if v is None else v > t_open for v in levels]


def _runs(mask, shortest=1):
    """[(first row, last row + 1)] of the runs of True at least `shortest` rows long"""
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= shortest:
                out.append((start, i))
            start = None
    return out


def states(o, voice, spans=None):
    """the time the mouth looks shut while the voice clearly sings and open in a silence, and the longest such spans;
    with spans (the lyric lines), the same inside them and outside them"""
    m = opening_on_rows(o, voice.rows)
    loud = voice.level > LOUD_DB
    quiet = np.zeros(voice.rows, bool)
    for a, b in _runs(voice.level < QUIET_DB, int(round(SILENCE_RUN / STEP))):
        # the mouth may still close LATE into a silence and open EARLY before its end (the ends are left out)
        quiet[a + int(round(LATE / STEP)):max(a, b - int(round(EARLY / STEP)))] = True
    parts = [("", np.ones(voice.rows, bool))]
    if spans:
        inside = np.zeros(voice.rows, bool)
        for a, b in spans:
            inside[max(0, int(a / STEP)):max(0, int(b / STEP) + 1)] = True
        parts += [("_inside_lines", inside), ("_outside_lines", ~inside)]
    out = {}
    for suffix, part in parts:
        for name, where, bad in (("shut_while_singing", loud, m < SHUT), ("open_in_silence", quiet, m > OPEN)):
            w = where & part
            runs = sorted(_runs(w & bad, 1), key=lambda r: r[0] - r[1])[:10]
            out[name + suffix] = {"share": round(float((w & bad).sum() / max(1, w.sum())), 3),
                                  "seconds": round(float((w & bad).sum() * STEP), 2),
                                  "longest_s": [[round(a * STEP, 2), round(b * STEP, 2)] for a, b in runs]}
    return out


def jumps(o, over=0.4):
    """the frames where the opening changes by more than `over` from the frame before (a snap the eye sees)"""
    d = np.diff(o)
    big = np.where(np.abs(d) > over)[0]
    top = big[np.argsort(-np.abs(d[big]))][:10]
    return {"frames_over": int(len(big)), "over": over, "largest": round(float(np.abs(d).max()), 3) if len(d) else 0.0,
            "top": [[int(f + 1), round(float(d[f]), 3)] for f in top]}


def opening_on_rows(o, rows):
    """the opening at the voice's rows (shown times)"""
    shown = (np.arange(len(o)) + SHOWN) / FPS
    return np.interp(np.arange(rows) * STEP, shown, o)


def xcorr(o, voice):
    """the peak of the normalised cross-correlation of the opening speed with the flux near the singing"""
    m = opening_on_rows(o, voice.rows)
    speed = np.maximum(np.diff(m, prepend=m[0]), 0.0)
    near = _window_extreme((voice.level > SOUND_DB).astype(float), int(NEAR_SINGING / STEP),
                           int(NEAR_SINGING / STEP), np.max) > 0
    idx = np.where(near)[0]
    L = int(round(XCORR_LAG / STEP))
    idx = idx[(idx >= L) & (idx < voice.rows - L)]
    if len(idx) < 50 or speed[idx].std() == 0:
        return None
    a = speed[idx] - speed[idx].mean()
    out = []
    for lag in range(-L, L + 1):
        b = voice.flux[idx + lag]                       # the voice `lag` rows after the mouth
        b = b - b.mean()
        den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
        out.append(float((a * b).sum()) / den if den > 0 else 0.0)
    k = int(np.argmax(out))
    return {"lag_ms": int(round((k - L) * STEP * 1000)), "r": round(out[k], 3), "r_at_0": round(out[L], 3)}


# ---- the lines and the alignment ------------------------------------------------------------

def read_spans(path):
    """[(start s, end s)] of a lyric lines file (start, end and the line, tab-separated; # starts a comment)"""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for n, row in enumerate(f, start=1):
            row = row.rstrip("\r\n")
            if not row.strip() or row.lstrip().startswith("#"):
                continue
            parts = row.split("\t")
            if len(parts) < 2:
                raise ValueError("line %d of %s: want start and end, tab-separated" % (n, path))
            rows.append((float(parts[0]), float(parts[1])))
    return sorted(rows)


def in_spans(spans, onsets, lags_by, pairs_by):
    """per span: each FACE's lags over the onsets inside it"""
    out = []
    for li, (a, b) in enumerate(spans):
        row = {"span": li, "start": a, "end": b, "onsets": int(((onsets >= a) & (onsets <= b)).sum())}
        for tag, pairs in pairs_by.items():
            lags = [lags_by[tag][k] for k, (i, _) in enumerate(pairs) if a <= onsets[i] <= b]
            row[tag] = {"paired": len(lags), "median_ms": round(float(np.median(lags)), 1) if lags else None,
                        "late_over_45ms": int(sum(1 for v in lags if v < -1000.0 * LATE))}
        out.append(row)
    return out


def starts_syllable(m):
    return m["vowel"] in "aiueo" and not m.get("held") and bool(m.get("consonant") or m.get("word_start"))


def _nearest(times, refs):
    """for each time, the signed distance to the nearest of refs (refs sorted)"""
    out = []
    for t in times:
        j = int(np.searchsorted(refs, t))
        near = [refs[k] for k in (j - 1, j) if 0 <= k < len(refs)]
        out.append(t - min(near, key=lambda r: abs(r - t)))
    return np.asarray(out, float)


def onset_check(morae, voice):
    """each aligned vowel start that begins a syllable against the nearest voice onset (ms, positive: aligned later)"""
    onsets = voice_onsets(voice)
    starts = [m for m in morae if starts_syllable(m)]
    if not len(onsets) or not starts:
        return None
    v0 = np.array([m["v0"] for m in starts])
    d = 1000.0 * _nearest(v0, onsets)
    a = np.abs(d)
    chance = [np.abs(1000.0 * _nearest(v0 + s, onsets)) for s in (-CHANCE_SHIFT, CHANCE_SHIFT)]
    by = {}
    for m, x in zip(starts, d):
        by.setdefault(m.get("consonant") or "-", []).append(x)
    inside = []
    for m in morae:
        if m["vowel"] not in "aiueo":
            continue
        got = onsets[(onsets >= m["v0"] + INSIDE[0]) & (onsets <= m["v1"] - INSIDE[1])]
        if len(got):
            inside.append({"line": m["line"], "mora": m["mora"], "kana": m.get("kana"), "v0": m["v0"], "v1": m["v1"],
                           "onsets": [round(float(t), 2) for t in got]})
    return {"syllables": len(d), "offset_ms": _stats(d), "share_within_30ms": round(float((a <= 30).mean()), 3),
            "share_within_50ms": round(float((a <= 50).mean()), 3),
            "chance_within_30ms": round(float(np.mean([(c <= 30).mean() for c in chance])), 3),
            "chance_within_50ms": round(float(np.mean([(c <= 50).mean() for c in chance])), 3),
            "by_consonant": {k: {"n": len(v), "median_abs_ms": round(float(np.median(np.abs(v))), 1),
                                 "within_30ms": round(float(np.mean(np.abs(v) <= 30)), 3)}
                             for k, v in sorted(by.items())},
            "vowels_with_an_onset_inside": len(inside), "vowels": sum(1 for m in morae if m["vowel"] in "aiueo"),
            "onset_inside": inside[:100]}


def otsu(values):
    """the threshold that parts the values into two groups of the least spread within them"""
    v = np.sort(np.asarray(values, float))
    if len(v) < 2:
        return float(v[0]) if len(v) else 0.0
    best, cut = None, 0.5 * (v[0] + v[-1])
    for k in range(1, len(v)):
        a, b = v[:k], v[k:]
        within = a.var() * len(a) + b.var() * len(b)
        if best is None or within < best:
            best, cut = within, 0.5 * (v[k - 1] + v[k])
    return float(cut)


def vowel_levels(voice, m):
    """(OPEN, FRONT) in dB over the middle of an aligned vowel where the voice sounds, or None"""
    a, b = int(round(m["v0"] / STEP)), int(round(m["v1"] / STEP))
    if b - a < 6:
        return None
    cut = int((b - a) * 0.2)
    rows = [r for r in range(a + cut, b - cut) if 0 <= r < voice.rows and voice.level[r] > SOUND_DB]
    if len(rows) < 3:
        return None
    rows = np.asarray(rows)
    op = voice.band_level(rows, OPEN_BANDS[1]) - voice.band_level(rows, OPEN_BANDS[0])
    fr = voice.band_level(rows, FRONT_BANDS[1]) - voice.band_level(rows, FRONT_BANDS[0])
    return float(np.mean(op)), float(np.mean(fr))


def vowel_check(morae, voice):
    """each aligned vowel's sound class against its label (see the module docstring)"""
    rows = []
    for m in morae:
        if m["vowel"] not in "aiueo" or m.get("held"):
            continue
        rows.append((m["line"], m["mora"], m["vowel"], vowel_levels(voice, m)))
    measured = [r for r in rows if r[3] is not None]
    if len(measured) < 4:
        return None
    t_open = otsu([lv[0] for _, _, _, lv in measured])
    opened = [lv for _, _, _, lv in measured if lv[0] > t_open]
    t_front = otsu([lv[1] for lv in opened]) if len(opened) >= 2 else 0.0

    def heard(lv):
        if lv is None:
            return None
        if lv[0] <= t_open:
            return "close"
        return "open front" if lv[1] > t_front else "open back"
    confusion = {}
    for _, _, v, lv in measured:
        c = confusion.setdefault(v, {"n": 0, "close": 0, "open front": 0, "open back": 0})
        c["n"] += 1
        c[heard(lv)] += 1
    lines = {}
    for li, mi, v, lv in rows:
        lines.setdefault(li, []).append((mi, v, heard(lv)))
    per, shifted = [], []
    for li in sorted(lines):
        seq = sorted(lines[li])
        vs = [v for _, v, _ in seq]
        hs = [h for _, _, h in seq]

        def agree(s):
            # close against open, the split the two formant levels tell best
            hits = [(hs[k] == "close") == (CLASS_OF[vs[k + s]] == "close") for k in range(len(seq))
                    if hs[k] is not None and 0 <= k + s < len(seq)]
            return (float(np.mean(hits)), len(hits)) if hits else (None, 0)
        a0, n0 = agree(0)
        am, _ = agree(-1)
        ap, _ = agree(1)
        per.append({"line": li, "n": n0, "agree": None if a0 is None else round(a0, 3),
                    "agree_shift_minus1": None if am is None else round(am, 3),
                    "agree_shift_plus1": None if ap is None else round(ap, 3)})
        if a0 is not None and n0 >= SHIFT_MIN and max(am or 0.0, ap or 0.0) >= a0 + SHIFT_GAIN:
            shifted.append(li)
    three = [heard(lv) == CLASS_OF[v] for _, _, v, lv in measured]
    two = [(heard(lv) == "close") == (CLASS_OF[v] == "close") for _, _, v, lv in measured]
    return {"vowels": len(rows), "measured": len(measured), "open_threshold_db": round(t_open, 2),
            "front_threshold_db": round(t_front, 2), "share_agree_close_open": round(float(np.mean(two)), 3),
            "share_agree_three_classes": round(float(np.mean(three)), 3), "confusion": confusion,
            "lines_fit_better_shifted": shifted, "per_line": per}


# ---- the sheet -------------------------------------------------------------------------------

def sample_syllables(morae, n, seed):
    pool = [i for i, m in enumerate(morae) if starts_syllable(m)]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
    return sorted(pool[k] for k in pick)


def _font(size):
    from PIL import ImageFont
    for path in FONTS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size), True
            except OSError:
                continue
    return ImageFont.load_default(), False


class _Canvas:
    """what the tiles and the views draw from"""

    def __init__(self, x, voice, morae, openings):
        self.x, self.voice, self.morae, self.openings = x, voice, morae or [], openings
        self.onsets = voice_onsets(voice)
        self.peaks = flux_peaks(voice) * STEP
        self.font, self.kana_ok = _font(14)


def _draw_span(img, d, c, ox, oy, tw, t0, t1, title, highlight=None, lab=22, sh=200, mh=90):
    """one span of the song at (ox, oy), tw wide: the spectrogram, the alignment, the onsets, the level and the
    mouths (see the module docstring)"""
    from PIL import Image

    def px(t):
        return ox + int(round((t - t0) / (t1 - t0) * tw))
    s0, s1 = int(round(t0 * SR)), int(round(t1 * SR))
    seg = np.zeros(s1 - s0, np.float32)
    a, b = max(0, s0), min(len(c.x), s1)
    if b > a:
        seg[a - s0:b - s0] = c.x[a:b]
    pw, _ = band_power(seg, WIN, max(16, int(round((t1 - t0) * SR / tw))), (0.0, 5000.0))
    db = 10.0 * np.log10(pw + 1e-12)
    top = float(np.percentile(db, 99.5))
    g = np.clip((db - (top - 50.0)) / 50.0, 0.0, 1.0)
    pic = (255 * (1.0 - g.T[::-1])).astype(np.uint8)
    img.paste(Image.fromarray(pic, "L").resize((tw, sh)).convert("RGB"), (ox, oy + lab))
    for j, mm in enumerate(c.morae):
        if mm["v1"] < t0 or mm["c0"] > t1:
            continue
        w = 3 if j == highlight else 1
        if mm["c0"] < mm["v0"]:
            d.line([(px(mm["c0"]), oy + lab), (px(mm["c0"]), oy + lab + sh)], fill=(40, 90, 255), width=w)
        d.line([(px(mm["v0"]), oy + lab), (px(mm["v0"]), oy + lab + sh)], fill=(0, 170, 0), width=w)
        d.line([(px(mm["v1"]), oy + lab + sh // 2), (px(mm["v1"]), oy + lab + sh)], fill=(220, 0, 0), width=w)
        name = mm.get("kana") if c.kana_ok and mm.get("kana") else (mm.get("consonant") or "") + mm["vowel"]
        d.text((px(mm["v0"]) + 3, oy + lab + 3), name, fill=(230, 100, 0) if j == highlight else (150, 110, 0),
               font=c.font)
    for t in c.onsets:
        if t0 <= t <= t1:
            d.polygon([(px(t) - 5, oy + lab), (px(t) + 5, oy + lab), (px(t), oy + lab + 9)], fill=(255, 130, 0))
    for t in c.peaks:
        if t0 <= t <= t1:
            d.line([(px(t), oy + lab + sh - 10), (px(t), oy + lab + sh)], fill=(0, 0, 0), width=2)
    base = oy + lab + sh + mh - 6
    d.line([(ox, base), (ox + tw, base)], fill=(200, 200, 200))
    rows = np.arange(max(0, int(t0 / STEP)), min(c.voice.rows, int(t1 / STEP) + 1))
    pts = [(px(r * STEP), base - int(round(np.clip((c.voice.level[r] + 40.0) / 40.0, 0, 1) * (mh - 12)))) for r in rows]
    if len(pts) > 1:
        d.line(pts, fill=(120, 170, 255), width=1)
    colours = [(110, 110, 110), (220, 30, 30), (30, 120, 220), (0, 150, 0)]
    for n, (tag, o) in enumerate(c.openings):
        pts = []
        for f in range(max(0, int(t0 * FPS) - 2), min(len(o), int(t1 * FPS) + 2)):
            ts = (f + SHOWN) / FPS
            if t0 <= ts <= t1:
                pts.append((px(ts), base - int(round(o[f] * (mh - 12)))))
        if len(pts) > 1:
            d.line(pts, fill=colours[n % len(colours)], width=2)
    tick = 0.1 if t1 - t0 <= 2.0 else 0.5
    for k in range(int(math.ceil(t0 / tick)), int(math.floor(t1 / tick)) + 1):
        d.line([(px(k * tick), base), (px(k * tick), base + 4)], fill=(0, 0, 0))
    d.rectangle([ox, oy, ox + tw - 1, oy + lab + sh + mh - 1], outline=(0, 0, 0))
    d.text((ox + 4, oy + 2), title, fill=(0, 0, 0), font=c.font)


def draw_sheet(prefix, canvas, picks, span=0.4, cols=2, rows_per_page=4):
    """the pages of tiles of the drawn syllables (see the module docstring); returns the tiles listed and the pages"""
    from PIL import Image, ImageDraw
    tw, th = 640, 22 + 200 + 90
    listed, pages = [], []
    per_page = cols * rows_per_page
    for p0 in range(0, len(picks), per_page):
        chunk = picks[p0:p0 + per_page]
        img = Image.new("RGB", (cols * tw, int(math.ceil(len(chunk) / float(cols))) * th), (255, 255, 255))
        d = ImageDraw.Draw(img)
        for k, idx in enumerate(chunk):
            tile = p0 + k
            m = canvas.morae[idx]
            title = "#%d  %.2f s  line %d  mora %d  %s" % (tile, m["v0"], m["line"], m["mora"],
                                                        (m.get("consonant") or "-") + m["vowel"])
            _draw_span(img, d, canvas, (k % cols) * tw, (k // cols) * th, tw, m["v0"] - span, m["v0"] + span, title,
                       highlight=idx)
            listed.append({"tile": tile, "page": len(pages) + 1, "index": idx, "line": m["line"], "mora": m["mora"],
                           "kana": m.get("kana"), "c0": m["c0"], "v0": m["v0"], "v1": m["v1"]})
        path = "%s_%02d.png" % (prefix, len(pages) + 1)
        img.save(path)
        pages.append(path)
    with open(prefix + ".json", "w", encoding="utf-8") as f:
        json.dump(listed, f, ensure_ascii=False, indent=0)
    return listed, pages


def draw_view(path, canvas, t0, t1, px_per_second=500):
    """one wide span of the song as a picture (the same marks as the sheet's tiles)"""
    from PIL import Image, ImageDraw
    tw = max(200, int(round((t1 - t0) * px_per_second)))
    img = Image.new("RGB", (tw, 22 + 200 + 90), (255, 255, 255))
    _draw_span(img, ImageDraw.Draw(img), canvas, 0, 0, tw, t0, t1, "%.2f - %.2f s" % (t0, t1))
    img.save(path)


# ---- the tool --------------------------------------------------------------------------------

def run(vocal_path, face_paths, lines_path=None, align_path=None, report_path=None, sheet=None, sample=40, seed=1,
        area=AREA, regions=(), views=(), sound=None):
    """the report (and the files asked for); views: [(t0, t1, path)]; sound: the voice as mono float32 at SR (tests)"""
    x = read_sound(vocal_path) if sound is None else np.asarray(sound, np.float32)
    voice = Voice(x)
    onsets = voice_onsets(voice)
    report = {"voice": {"seconds": round(len(x) / float(SR), 2), "onsets": int(len(onsets)),
                        "flux_peaks": int(len(flux_peaks(voice))),
                        "sounding_seconds": round(float((voice.level > SOUND_DB).sum() * STEP), 2)},
              "area": list(area), "faces": {}}
    openings, lags_by, pairs_by = [], {}, {}
    frames = int(math.ceil(len(x) / float(SR) * FPS)) + 1
    opens = onset_open(voice, onsets)
    report["voice"]["onsets_open_vowel"] = int(sum(1 for v in opens if v))
    for path in face_paths:
        tag = os.path.splitext(os.path.basename(path))[0]
        while tag in report["faces"]:
            tag += "_"
        o = opening(vmd.load(path), frames, area)
        res, pairs, lags = lag_measure(onsets, rise_times(o))
        res["open_vowel_onsets"] = dict(
            share_paired=round(sum(1 for i, _ in pairs if opens[i]) / max(1, sum(1 for v in opens if v)), 3),
            **lag_summary([v for (i, _), v in zip(pairs, lags) if opens[i]]))
        res["triggered"] = triggered(o, onsets)
        res["triggered_open_vowel"] = triggered(o, onsets[[bool(v) for v in opens]] if len(onsets) else onsets)
        res["xcorr_speed_flux"] = xcorr(o, voice)
        res["states"] = states(o, voice, read_spans(lines_path) if lines_path else None)
        res["jumps"] = jumps(o)
        res["noticed"] = [{"onset_s": round(float(onsets[i]), 2), "lag_ms": round(float(v), 1)}
                          for (i, _), v in zip(pairs, lags) if v < -1000.0 * LATE or v > 1000.0 * EARLY][:200]
        report["faces"][tag] = res
        openings.append((tag, o))
        lags_by[tag], pairs_by[tag] = lags, pairs
    common = set(range(len(onsets)))
    for pairs in pairs_by.values():
        common &= {i for i, _ in pairs}
    for tag, pairs in pairs_by.items():
        lags = [lags_by[tag][k] for k, (i, _) in enumerate(pairs) if i in common]
        report["faces"][tag]["common"] = dict(onsets=len(common), **lag_summary(lags))
    if lines_path:
        report["lines"] = in_spans(read_spans(lines_path), onsets, lags_by, pairs_by)
    if regions:
        report["regions"] = in_spans([tuple(r) for r in regions], onsets, lags_by, pairs_by)
    morae = None
    if align_path:
        with open(align_path, encoding="utf-8") as f:
            morae = json.load(f)
        report["alignment"] = {"onsets": onset_check(morae, voice), "vowels": vowel_check(morae, voice)}
    if sheet or views:
        canvas = _Canvas(x, voice, morae, openings)
        if sheet and morae:
            listed, pages = draw_sheet(sheet, canvas, sample_syllables(morae, sample, seed))
            report["sheet"] = {"pages": pages, "tiles": len(listed), "seed": seed}
        for t0, t1, path in views:
            draw_view(path, canvas, t0, t1)
        if views:
            report["views"] = [path for _, _, path in views]
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=True, indent=1)
    return report


def _area(text):
    try:
        v = tuple(float(s) for s in text.split(","))
    except ValueError:
        v = ()
    if len(v) != 5 or any(a < 0 for a in v):
        raise argparse.ArgumentTypeError("five areas, of あ い う え お, comma-separated")
    return v


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("vocal", help="the singing voice alone (any file ffmpeg reads)")
    p.add_argument("faces", nargs="+", help="face motions (.vmd) whose mouths to measure")
    p.add_argument("--lines", help="the lyric lines (start, end, ... tab-separated): the lags line by line")
    p.add_argument("--region", nargs=2, type=float, action="append", default=[], metavar=("T0", "T1"),
                   help="the lags inside this span of the song (s; repeated)")
    p.add_argument("--align", help="lip_sync's --align-out: check the alignment against the voice")
    p.add_argument("--sheet", help="PREFIX of the pages of random aligned syllables (needs --align and Pillow)")
    p.add_argument("--sample", type=int, default=40, help="syllables on the sheet (default %(default)s)")
    p.add_argument("--seed", type=int, default=1, help="the draw of the sheet (default %(default)s)")
    p.add_argument("--view", nargs=3, action="append", default=[], metavar=("T0", "T1", "PNG"),
                   help="draw a span of the song as the sheet's tiles do (repeated; needs Pillow)")
    p.add_argument("--area", type=_area, default=AREA, help="the open area of あ,い,う,え,お (default %(default)s)")
    p.add_argument("--report", help="write the report (JSON)")
    args = p.parse_args(argv)
    for path in [args.vocal] + args.faces + [q for q in (args.lines, args.align) if q]:
        if not os.path.isfile(path):
            print("lip_check: no such file: %s" % path, file=sys.stderr)
            return 2
    if args.sheet and not args.align:
        print("lip_check: --sheet needs --align", file=sys.stderr)
        return 2
    try:
        views = [(float(a), float(b), path) for a, b, path in args.view]
    except ValueError:
        print("lip_check: --view wants T0 T1 PNG", file=sys.stderr)
        return 2
    if any(not b > a for a, b, _ in views):
        print("lip_check: --view: T1 must be after T0", file=sys.stderr)
        return 2
    try:
        report = run(args.vocal, args.faces, args.lines, args.align, args.report, args.sheet, args.sample, args.seed,
                     args.area, args.region, views)
    except (ValueError, subprocess.CalledProcessError) as e:
        print("lip_check: %s" % e, file=sys.stderr)
        return 1
    keys = ("share_onsets_paired", "lag_ms", "share_mouth_late_over_45ms", "share_rises_without_onset", "triggered",
            "xcorr_speed_flux")
    short = {"voice": report["voice"],
             "faces": {k: {kk: v[kk] for kk in keys if kk in v} for k, v in report["faces"].items()}}
    if "alignment" in report:
        al = report["alignment"]
        short["alignment"] = {
            "onsets": {k: al["onsets"][k] for k in ("offset_ms", "share_within_30ms", "chance_within_30ms")}
            if al["onsets"] else None,
            "vowels": {k: al["vowels"][k] for k in ("share_agree_close_open", "share_agree_three_classes",
                                                     "lines_fit_better_shifted")} if al["vowels"] else None}
    print(json.dumps(short, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
