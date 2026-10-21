"""Flashes that mean something: the light of a look (the motion graphics' flashes, tools/mograph_layer.py events of kind
"flash", and the look's flares) put on moments of the song a viewer hears, or dropped; the punch on a flash's frame with it.

    python tools/flash_sync.py measure MIX VOICE STRUCTURE.json LOOK.json OUT.json [--arrays OUT.npz] [--reference MIX0]
        the moments of the song: the title words' first syllable as sung (read from VOICE, the separated singing voice), the
        heads of the sections of STRUCTURE (looks/song_structure.json of the stage-6 work) and the band's returns after a
        stop (read from the backing: MIX less VOICE); the hits (onsets) of the backing, of the mix and of the
        voice and how strong each is among the song's own; and the decision for every flash and flare of LOOK and for the
        punch on a flash's frame.  --reference: the mix STRUCTURE was measured on (for a new source: its mix must lie on the
        reference's hits within a frame, mix_lag, or the measure stops).  --backing-from MIX0 VOICE0: the backing's hits from
        that pair (another singer over the same backing: the hits stay those of the source the structure was measured on, the
        title words' first syllables are the new voice's)
    python tools/flash_sync.py place LOOK.json MEASURE.json OUT.json
        LOOK with the decisions of MEASURE: those flashes, flares and punches moved or dropped, nothing else changed
    python tools/flash_sync.py table MEASURE.json OUT.md
        the decisions and the numbers behind them as a table
    python tools/flash_sync.py compare MEASURE_A.json MEASURE_B.json OUT.md [--labels A,B]
        two sources of the song side by side: the title words' first syllables, the hits on them and the decisions
    python tools/flash_sync.py figure MEASURE.json ARRAYS.npz OUT.png [--lang en|ja]
        the whole song and each flash against the voice, the hits and the heads (needs matplotlib)

Why (2026-10-21, flashsync): the request is that a flash in the MV mean something, or go.  The four flashes of the motion
graphics (look_city_mograph_rv.json) stood on the title words' beats, where the first syllable has already been sung for 100 to
160 ms (it comes in a sixteenth before the beat) and the backing has no hit of its own: a light three or more frames after the
voice it should go with (a sound more than 45 ms before its picture is noticed, ITU-R BT.1359-1) and on nothing a viewer hears.

The rule (decide): a flash stands on a moment that means something in the song - a title word where its first syllable is
sung, the head of a section, the band coming back after a stop - and only where the backing has a strong
hit on it: one of the song's hits at STRONG (the 90th percentile of their strengths) or over, within NEAR_FRAMES frame of the
moment.  The backing, not the mix: it is what a flash of the editor hits on, and it stays when another singer's voice comes in
(the hits of the mix and of the voice are measured and written beside it).  A flash moves to the nearest such moment within a
bar of its place (it keeps to its phrase); none there, it is dropped.  It starts on the frame on which the moment's sound
starts (the earlier of the moment and its hit, floored to a frame: the light comes no later than the sound, as a viewer takes
a light up to some tens of ms early for the same time).  A punch on a flash's frame goes with the flash; where a punch may not
be (half a second from where the skirt flares, mograph_layer's plan) or when the flash is dropped, it goes to the first
syllable of the title word the flash stood for, as sung (a punch marks the title word on the voice), or, not allowed there
either, it is dropped.

How the sound is read: both files at SR through ffmpeg, the voice found in the mix at its lag (the cross-correlation over the
middle of the song) and taken off it (the separated stems add up to the mix: the gain is 1).  The hits: peaks, HIT_SPACING
apart, of the spectral flux of the log magnitude (ONSET_BAND, windows of ONSET_WIN every ONSET_HOP samples) over its median,
their times put back by the lead the same code reads on drum-like bursts (the flux of a window rises before its centre reaches
the onset).  A hit's strength among the song's: the share of its hits that are weaker (percentile), and its height over the
median of the hits within LOCAL seconds (local).  The first syllable of a title word: in SYLLABLE_SEARCH of its beat, the
steepest rise of the voice's level in the voiced band (VOICED) that comes up by SYLLABLE_RISE_DB or more from the quietest of
the SYLLABLE_BEFORE before it to the loudest of the SYLLABLE_AFTER after it (a breath of h before the vowel has little in that
band), at the time its power first reaches half of that loudest (a Hann window centred on a step reads half of it there).
The band's return: a strong hit of the backing after a stop, STOP_S or more in which none of its hits reaches the QUIET_PCT
percentile (the drums stop under the last title word and come back hard on the next bar; the bass plays on through it, so
the low end alone does not show the stop).
"""
import argparse
import copy
import importlib.util
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 22050
FPS = 30                          # frames of the song, MMD's (mograph_layer.SONG_FPS)
ONSET_WIN, ONSET_HOP = 1024, 110  # samples: 46 ms windows every 5 ms
ONSET_BAND = (30.0, 8000.0)       # Hz: the whole band of a drum kit and the band (a04_beat's full band)
HIT_SPACING = 0.05                # s: a hit is the largest flux within this on each side
VOICE_WIN, VOICE_HOP = 512, 55    # samples: 23 ms windows every 2.5 ms
VOICED = (150.0, 1500.0)          # Hz: the voice's fundamental and first formant (review mographrev's hook_timing)
SYLLABLE_SEARCH = (-0.25, 0.15)   # s from the title word's beat: its first syllable comes in 100-160 ms before it
SYLLABLE_RISE_DB = 12.0
SYLLABLE_BEFORE, SYLLABLE_AFTER = 0.075, 0.05
SYLLABLE_SMOOTH = 5               # rows the level is smoothed over for its slope
STOP_S = 1.0                      # s without a hit at the song's median or over (more than two beats at 140 BPM): a stop
QUIET_PCT = 50.0
STRONG = 90.0                     # percentile of the song's hits: a strong hit (the request: "the top 10 % or so")
NEAR_FRAMES = 1                   # a strong hit within this of a moment is on it
REACH_FRAMES = 2                  # the strongest hit within this of a flash is written (the request: +-2 frames)
LOCAL = 2.0                       # s each side: the hits a hit is told against for its local strength
SKIRT_GAP = 0.5                   # s: no punch's frames within this of where the skirt flares (mograph_layer.plan)
ALIGN_MOST = 0.05                 # s: the voice is looked for this far either way in the mix
REFERENCE_MOST = 2.0              # s: a mix of another source is looked for this far either way in the reference mix
_LAZY = {}


def mograph_tool():
    """tools/mograph_layer.py, loaded from its file once: its frame_of, frame_time, merge and DEFAULTS"""
    if "mograph" not in _LAZY:
        spec = importlib.util.spec_from_file_location("mograph_layer", os.path.join(HERE, "mograph_layer.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LAZY["mograph"] = module
    return _LAZY["mograph"]


# ---- the sound -----------------------------------------------------------------------------------------------------

def read_sound(path, sr=SR):
    """the sound of `path` as mono float64 at `sr`, read with ffmpeg"""
    args = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0                        # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def shifted(x, lag):
    """x delayed by `lag` samples (ahead for a negative lag), as long as x, zero where it has nothing"""
    x = np.asarray(x, np.float64)
    out = np.zeros_like(x)
    if lag >= 0:
        out[lag:] = x[:len(x) - lag]
    else:
        out[:lag] = x[-lag:]
    return out


def align(mix, voice, sr=SR, most=ALIGN_MOST):
    """the lag (samples) at which the voice lies in the mix: the largest cross-correlation over the middle of the song
    (a minute at most), within `most` seconds either way"""
    n = min(len(mix), len(voice))
    half = min(n // 4, int(30 * sr))
    a, b = n // 2 - half, n // 2 + half
    reach = max(1, min(int(round(most * sr)), half // 2))
    seg = np.asarray(mix[a:b], np.float64)
    ext = np.zeros(len(seg) + 2 * reach)
    lo, hi = a - reach, b + reach
    src_lo, src_hi = max(0, lo), min(n, hi)
    ext[src_lo - lo:src_hi - lo] = voice[src_lo:src_hi]
    size = 1 << int(math.ceil(math.log2(len(ext) + len(seg))))
    corr = np.fft.irfft(np.fft.rfft(ext, size) * np.conj(np.fft.rfft(seg, size)), size)[:2 * reach + 1]
    # corr[m] = sum_u seg[u] ext[u + m] = the correlation at lag reach - m
    return int(reach - int(np.argmax(corr)))


def backing_of(mix, voice, lag):
    """the mix less the voice at its lag (the separated stems add up to the mix: no gain)"""
    n = min(len(mix), len(voice))
    return np.asarray(mix[:n], np.float64) - shifted(np.asarray(voice[:n], np.float64), lag)


def spectra(x, sr, win, hop, band):
    """(times, magnitudes [rows, bins]): row k is the Hann window centred on sample k x hop (the sound padded by half a window)"""
    x = np.asarray(x, np.float64)
    pad = np.pad(x, (win // 2, win // 2))
    n = max(0, 1 + (len(pad) - win) // hop)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    keep = (freqs >= band[0]) & (freqs < band[1])
    w = np.hanning(win)
    out = np.zeros((n, int(keep.sum())), np.float32)
    for s0 in range(0, n, 4000):
        s1 = min(n, s0 + 4000)
        idx = (np.arange(s0, s1) * hop)[:, None] + np.arange(win)[None, :]
        out[s0:s1] = np.abs(np.fft.rfft(pad[idx] * w, axis=1)[:, keep])
    return np.arange(n) * hop / float(sr), out


def flux(mags, ref):
    """the positive spectral flux of log(1 + magnitude / ref), summed over the bins, one value a row (the first 0)"""
    lg = np.log1p(np.asarray(mags, np.float64) / ref)
    return np.concatenate([[0.0], np.maximum(np.diff(lg, axis=0), 0.0).sum(axis=1)]) if len(lg) else np.zeros(0)


def _peak_rows(env, spacing_rows):
    """rows of env that are its largest within spacing_rows on each side, above its median and 0"""
    if len(env) == 0:
        return np.zeros(0, int)
    s = max(1, int(spacing_rows))
    top = np.max(np.lib.stride_tricks.sliding_window_view(np.pad(env, (s, s), mode="edge"), 2 * s + 1), axis=1)
    return np.nonzero((env >= top) & (env > np.median(env)) & (env > 0))[0]


def _vertex(env, k):
    """the offset (rows, -0.5..0.5) of the parabola's top through rows k - 1, k, k + 1"""
    if k <= 0 or k >= len(env) - 1:
        return 0.0
    y0, y1, y2 = env[k - 1], env[k], env[k + 1]
    den = y0 - 2.0 * y1 + y2
    return float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) if abs(den) > 1e-12 else 0.0


def _clock_lead(sr, win, hop, band):
    """how much earlier than the onset of a drum-like burst (a decaying noise) the flux of this code peaks: seconds, read on
    sixteen bursts in a quiet noise, the median"""
    key = (sr, win, hop, band)
    if key not in _LAZY:
        rng = np.random.default_rng(3)
        x = 0.001 * rng.standard_normal(int(sr * 10))
        true = np.arange(1.0, 9.0, 0.5) + rng.uniform(0.0, 0.01, 16)
        n = int(0.1 * sr)
        for t0 in true:
            i = int(round(t0 * sr))
            x[i:i + n] += 0.5 * rng.standard_normal(n) * np.exp(-np.arange(n) / (0.02 * sr))
        times, mags = spectra(x, sr, win, hop, band)
        env = flux(mags, float(np.median(mags)) + 1e-12)
        rows = _peak_rows(env, round(HIT_SPACING * sr / hop))
        rows = rows[env[rows] > 0.2 * env.max()]
        found = times[rows] + np.array([_vertex(env, k) for k in rows]) * hop / float(sr)
        _LAZY[key] = float(np.median([found[np.argmin(np.abs(found - t0))] - t0 for t0 in true]))
    return _LAZY[key]


def onset_envelope(x, sr=SR, ref=None, win=ONSET_WIN, hop=ONSET_HOP, band=ONSET_BAND):
    """(times, flux): the flux of `x` (see flux; ref: the magnitude it is told against, its own median by default), each row's
    time put back by the clock's lead so that a hit's peak lies on its onset"""
    times, mags = spectra(x, sr, win, hop, band)
    if ref is None:
        ref = float(np.median(mags)) + 1e-12
    return times - _clock_lead(sr, win, hop, band), flux(mags, ref)


def hits_of(times, env, spacing=HIT_SPACING, span=None):
    """[{"t", "height"}]: the peaks of an onset envelope (see _peak_rows), each at its parabola's top, within `span` (s)"""
    times = np.asarray(times, np.float64)
    env = np.asarray(env, np.float64)
    if len(times) < 3:
        return []
    step = float(times[1] - times[0])
    out = []
    for k in _peak_rows(env, round(spacing / step)):
        t = float(times[k] + _vertex(env, k) * step)
        if span is None or span[0] <= t <= span[1]:
            out.append({"t": t, "height": float(env[k])})
    return out


def mix_lag(x, ref, sr=SR, most=REFERENCE_MOST):
    """(lag in seconds, r): where the onsets of `ref` lie in those of `x` (positive: x later), the largest normalised
    cross-correlation of the two onset envelopes within `most` seconds either way (a parabola through its top).  Two mixes over
    one backing have its hits in common whatever voice sings over them"""
    t1, e1 = onset_envelope(x, sr)
    t2, e2 = onset_envelope(ref, sr)
    n = min(len(e1), len(e2))
    a, b = e1[:n] - e1[:n].mean(), e2[:n] - e2[:n].mean()
    step = float(t1[1] - t1[0])
    reach = min(int(round(most / step)), n // 2)
    size = 1 << int(math.ceil(math.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    lags = np.concatenate([corr[:reach + 1], corr[-reach:]]) if reach else corr[:1]
    order = np.concatenate([np.arange(0, reach + 1), np.arange(-reach, 0)]) if reach else np.zeros(1, int)
    k = int(np.argmax(lags))
    i = int(order[k])
    # the parabola's top through the three around it (on the circular correlation)
    y0, y1, y2 = corr[(i - 1) % size], corr[i % size], corr[(i + 1) % size]
    den = y0 - 2.0 * y1 + y2
    frac = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) if abs(den) > 1e-12 else 0.0
    r = float(y1 / math.sqrt(float((a * a).sum() * (b * b).sum()) + 1e-30))
    return (i + frac) * step, r


class Hits:
    """the hits of one sound over the song: how strong one is among them"""

    def __init__(self, hits):
        hits = sorted(hits, key=lambda h: h["t"])
        self.times = np.array([h["t"] for h in hits], np.float64)
        self.heights = np.array([h["height"] for h in hits], np.float64)

    def __len__(self):
        return len(self.times)

    def percentile(self, height):
        """the share of the song's hits weaker than `height`, x 100"""
        return float(100.0 * np.mean(self.heights < height)) if len(self.heights) else float("nan")

    def strongest(self, t, reach):
        """the strongest hit within `reach` seconds of `t` ({"t", "height", "pct", "local"}), or None"""
        if not len(self.times):
            return None
        near = np.nonzero(np.abs(self.times - t) <= reach + 1e-9)[0]
        if not len(near):
            return None
        i = int(near[np.argmax(self.heights[near])])
        h = float(self.heights[i])
        around = self.heights[np.abs(self.times - self.times[i]) <= LOCAL]
        return {"t": round(float(self.times[i]), 4), "height": round(h, 3), "pct": round(self.percentile(h), 1),
                "local": h / float(np.median(around))}

    def summary(self):
        if not len(self.heights):
            return {"count": 0}
        q = np.percentile(self.heights, [50, 90, 95, 99])
        return {"count": len(self.heights), "p50": round(float(q[0]), 3), "p90": round(float(q[1]), 3),
                "p95": round(float(q[2]), 3), "p99": round(float(q[3]), 3)}


# ---- the voice -----------------------------------------------------------------------------------------------------

def voice_level(voice, sr=SR):
    """(times, dB): the voice's power in VOICED every VOICE_HOP samples"""
    times, mags = spectra(voice, sr, VOICE_WIN, VOICE_HOP, VOICED)
    power = (np.asarray(mags, np.float64) ** 2).sum(axis=1)
    return times, 10.0 * np.log10(power + 1e-20)


def first_syllable(times, db, beat, search=SYLLABLE_SEARCH, rise_db=SYLLABLE_RISE_DB, before=SYLLABLE_BEFORE,
                   after=SYLLABLE_AFTER):
    """the onset of the first syllable of a word sung on `beat` (see the module's docstring): {"t", "rise_db", "slope_db_s",
    "low_t", "peak_db"}, or None when the voice has no such rise in the search"""
    times = np.asarray(times, np.float64)
    db = np.asarray(db, np.float64)
    step = float(times[1] - times[0])
    rows = np.nonzero((times >= beat + search[0]) & (times <= beat + search[1]))[0]
    if not len(rows):
        return None
    k = np.ones(SYLLABLE_SMOOTH) / SYLLABLE_SMOOTH
    slope = np.gradient(np.convolve(db, k, mode="same")) / step
    nb, na = int(round(before / step)), int(round(after / step))
    for j in rows[np.argsort(slope[rows])[::-1]]:
        if slope[j] <= 0:
            break
        lo_from = max(0, j - nb)
        low = lo_from + int(np.argmin(db[lo_from:j + 1]))
        peak = float(db[j:j + na + 1].max())
        rise = peak - float(db[low])
        if rise < rise_db:
            continue
        # the onset: where the power first reaches half of the loudest after it (linear between the rows)
        power = 10.0 ** (db / 10.0)
        half = 0.5 * 10.0 ** (peak / 10.0)
        r = low
        while r < j + na and power[r] < half:
            r += 1
        if r > low and power[r] > power[r - 1]:
            t = times[r - 1] + (half - power[r - 1]) / (power[r] - power[r - 1]) * step
        else:
            t = times[r]
        return {"t": round(float(t), 4), "rise_db": round(rise, 1), "slope_db_s": round(float(slope[j]), 1),
                "low_t": round(float(times[low]), 4), "peak_db": round(peak, 1)}
    return None


# ---- moments -------------------------------------------------------------------------------------------------------

def frame_of_moment(t, fps=FPS):
    """the frame on which a sound at `t` seconds happens: its frame starts no later than the sound"""
    return int(math.floor(float(t) * fps + 1e-6))


def time_of_frame(frame):
    """the time to write in a look for an event that starts on `frame` (mograph_layer.frame_time: round and ceil give it)"""
    return mograph_tool().frame_time(frame)


def band_returns(hits, stop=STOP_S, quiet=QUIET_PCT, strong=STRONG):
    """[{"t", "quiet_s", "pct"}]: the strong hits of the backing (`hits`, at the `strong` percentile or over) that end a stop:
    none of its hits in the `stop` seconds before reaches the `quiet` percentile (quiet_s: how long since the last that did)"""
    out = []
    loud = [i for i in range(len(hits)) if hits.percentile(hits.heights[i]) >= quiet]
    for i in range(len(hits)):
        pct = hits.percentile(hits.heights[i])
        if pct < strong:
            continue
        before = [j for j in loud if hits.times[j] < hits.times[i] - 1e-9]
        if not before:
            continue
        quiet_s = float(hits.times[i] - hits.times[before[-1]])
        if quiet_s >= stop:
            out.append({"t": round(float(hits.times[i]), 4), "quiet_s": round(quiet_s, 3), "pct": round(pct, 1)})
    return out


def on_the_grid(t, structure, fps=FPS):
    """the time of the beat of the structure's grid within NEAR_FRAMES frame of `t`, or t itself (the grid is fitted to the
    kick's attack over the whole song; a hit read alone lies a few ms after it)"""
    beat = structure.get("beat", {})
    if "first" not in beat or "period" not in beat:
        return t
    first, period = float(beat["first"]), float(beat["period"])
    b = first + round((t - first) / period) * period
    return b if abs(b - t) <= NEAR_FRAMES / float(fps) else t


def moments_of(structure, syllables, returns):
    """the moments a flash may mean: the title words' first syllables as sung (syllables: {hook n: first_syllable or None}),
    the heads of the sections after the first (at their beats), the band's returns that are no section's head (at the beat of
    the grid when the hit is on one: hit_t keeps where it was read)"""
    out = []
    for h in structure.get("hooks", []):
        s = syllables.get(h["n"])
        if s is not None:
            out.append({"kind": "title", "n": h["n"], "t": s["t"], "beat": h["t"], "rise_db": s["rise_db"]})
    heads = []
    for s in structure.get("sections", [])[1:]:
        heads.append(float(s["t"]))
        out.append({"kind": "section", "id": s["id"], "t": float(s["t"]), "beat": s.get("beat")})
    for r in returns:
        if all(abs(r["t"] - h) > 0.05 for h in heads):
            out.append({"kind": "return", "t": round(on_the_grid(r["t"], structure), 4), "hit_t": r["t"], "quiet_s": r["quiet_s"],
                        "pct": r["pct"]})
    return sorted(out, key=lambda m: m["t"])


def reach_of(structure, fps=FPS):
    """s: a flash moves at most a bar (and a frame) from its place"""
    beat = structure.get("beat", {})
    return float(beat.get("per_bar", 4)) * float(beat.get("period", 60.0 / 140.0)) + 1.0 / fps


# ---- the decisions -------------------------------------------------------------------------------------------------

def _punch_span(e):
    d = mograph_tool().DEFAULTS["punch"]
    return int(e.get("rise", d["rise"])) + int(e.get("fall", d["fall"]))


def near_skirt(t, frames, skirt, fps=FPS):
    """mograph_layer.plan's guard: an effect of `frames` frames from `t` comes within SKIRT_GAP of where the skirt flares"""
    end = t + frames / float(fps)
    return any(t - SKIRT_GAP < float(s) < end + SKIRT_GAP for s in skirt)


def _place_flash(t, moments, hits, reach, fps):
    """(moment, hit, frame) for a flash at `t`: the nearest qualified moment within reach (see the rule), or None"""
    best = None
    for m in moments:
        if abs(m["t"] - t) > reach:
            continue
        hit = hits.strongest(m["t"], NEAR_FRAMES / float(fps))
        if hit is None or hit["pct"] < STRONG:
            continue
        key = (abs(m["t"] - t), -hit["height"])
        if best is None or key < best[0]:
            best = (key, m, hit)
    if best is None:
        return None
    _, m, hit = best
    return m, hit, frame_of_moment(min(m["t"], hit["t"]), fps)


def decide(events, moments, hits, skirt=(), flares=(), reach=None, fps=FPS):
    """the decisions for the flashes among `events` (a look's mograph events, as written), the punches on their frames, and
    the look's `flares` (times): [{"kind", "index", "t", "old_frame", "action" keep|move|drop, "frame", "moment", "hit",
    "reason", ...}] in the order of the events, then the flares"""
    ML = mograph_tool()
    reach = reach if reach is not None else 4 * 60.0 / 140.0 + 1.0 / fps
    out = []
    titles = [m for m in moments if m["kind"] == "title"]

    def title_for(t):
        near = [m for m in titles if abs(m["beat"] - t) <= reach]
        return min(near, key=lambda m: abs(m["beat"] - t)) if near else None

    def judge(kind, index, t):
        old = ML.frame_of(t, fps)
        placed = _place_flash(t, moments, hits, reach, fps)
        d = {"kind": kind, "index": index, "t": t, "old_frame": old, "title": title_for(t)}
        if placed is None:
            d.update(action="drop", frame=None, moment=None, hit=None, why="no_strong_hit",
                     reason="no strong hit of the backing (>= p%g within %d frame) on a moment within a bar" % (STRONG, NEAR_FRAMES))
        else:
            m, hit, frame = placed
            d.update(action="keep" if frame == old else "move", frame=frame, moment=m, hit=hit, why="strong_hit",
                     reason="%s with a strong hit of the backing (p%.1f)" % (_moment_name(m), hit["pct"]))
        return d
    flashes = {}
    for i, e in enumerate(events):
        if e.get("kind") == "flash":
            d = judge("flash", i, float(e["t"]))
            out.append(d)
            flashes.setdefault(d["old_frame"], d)
    for i, e in enumerate(events):
        if e.get("kind") != "punch":
            continue
        frame = ML.frame_of(float(e["t"]), fps)
        f = flashes.get(frame)
        if f is None:
            continue
        span = _punch_span(e)
        d = {"kind": "punch", "index": i, "t": float(e["t"]), "old_frame": frame, "flash": f["index"]}
        if f["action"] != "drop" and not near_skirt(f["frame"] / float(fps), span, skirt, fps):
            d.update(action="keep" if f["frame"] == frame else "move", frame=f["frame"], why="with_flash", reason="with its flash")
        else:
            why = "its flash is dropped" if f["action"] == "drop" else "the skirt flares near its flash's frame"
            code = "flash_dropped" if f["action"] == "drop" else "skirt"
            title = f["title"]
            if title is not None and not near_skirt(frame_of_moment(title["t"], fps) / float(fps), span, skirt, fps):
                nf = frame_of_moment(title["t"], fps)
                d.update(action="keep" if nf == frame else "move", frame=nf, why=code + "_title", n=title["n"],
                         reason="%s: on title word %d as sung" % (why, title["n"]))
            else:
                d.update(action="drop", frame=None, why=code + "_none", reason="%s, and no title word as sung to go to" % why)
        out.append(d)
    for i, t in enumerate(flares):
        out.append(judge("flare", i, float(t)))
    return out


def _moment_name(m):
    if m["kind"] == "title":
        return "title word %d as sung" % m["n"]
    if m["kind"] == "section":
        return "the head of %s" % m["id"]
    return "the band's return%s" % ("" if m.get("bar") is None else " (bar %d)" % m["bar"])


def place(look, decisions):
    """a copy of `look` with the decisions made: the flashes, punches and flares moved to their frames' times or dropped"""
    new = copy.deepcopy(look)
    events = new.get("mograph", {}).get("events", [])
    gone = set()
    for d in decisions:
        if d["kind"] not in ("flash", "punch"):
            continue
        e = events[d["index"]]
        if d["action"] == "drop":
            gone.add(d["index"])
        elif d["action"] == "move":
            e["t"] = time_of_frame(d["frame"])
            e["note"] = ("%s; " % e["note"] if e.get("note") else "") + "flashsync: moved from %.3f s, %s" % (d["t"], d["reason"])
    if events:
        new["mograph"]["events"] = [e for i, e in enumerate(events) if i not in gone]
    flares = [d for d in decisions if d["kind"] == "flare"]
    if flares:
        new["flares"] = sorted(time_of_frame(d["frame"]) for d in flares if d["action"] != "drop")
    if "mograph" in new:
        mograph_tool().merge(new["mograph"])                    # still a section the motion graphics take
    return new


# ---- measure -------------------------------------------------------------------------------------------------------

def _strengths(t, sets, reach):
    return {name: h.strongest(t, reach) for name, h in sets.items()}


def measure(mix_path, voice_path, structure, look, arrays=None, sr=SR, reference=None, backing_from=None):
    """the report (see the module's docstring), and with `arrays` the envelopes and the voice's level as .npz.  `reference`:
    the mix the song structure was measured on; a mix of another source (another singer over the same backing) must lie on it
    within a frame, or the structure's beats are not where its hits are (ValueError).  `backing_from` (MIX0, VOICE0): the hits
    of the backing are those of that pair (the source the structure was measured on: the same backing, as its separation gave
    it), the voice's first syllables are VOICE's; the new pair's own backing is measured beside it (backing_own)"""
    mix, voice = read_sound(mix_path, sr), read_sound(voice_path, sr)
    checked = None
    if reference:
        lag_s, r = mix_lag(mix, read_sound(reference, sr), sr)
        checked = {"path": os.path.abspath(reference), "lag_ms": round(lag_s * 1000.0, 1), "r": round(r, 3)}
        if abs(lag_s) > 1.0 / FPS:
            raise ValueError("the mix lies %.0f ms off the reference mix %s (r %.2f): the song structure's beats are not where "
                             "its hits are; measure the structure again before placing the flashes" % (lag_s * 1000.0, reference, r))
    n = min(len(mix), len(voice))
    mix, voice = mix[:n], voice[:n]
    lag = align(mix, voice, sr)
    voice_at = shifted(voice, lag)
    backing = mix - voice_at
    gain = float(np.dot(mix, voice_at) / max(1e-20, float(np.dot(voice_at, voice_at))))
    _, mags = spectra(mix, sr, ONSET_WIN, ONSET_HOP, ONSET_BAND)
    ref = float(np.median(mags)) + 1e-12                         # one reference for the three
    del mags
    span = (0.5, n / float(sr) - 0.5)
    env, sets = {}, {}
    sources = [("backing", backing, ref, span), ("mix", mix, ref, span), ("voice", voice_at, ref, span)]
    took = None
    if backing_from:
        mix0, voice0 = read_sound(backing_from[0], sr), read_sound(backing_from[1], sr)
        n0 = min(len(mix0), len(voice0))
        mix0, voice0 = mix0[:n0], voice0[:n0]
        lag0 = align(mix0, voice0, sr)
        _, mags0 = spectra(mix0, sr, ONSET_WIN, ONSET_HOP, ONSET_BAND)
        ref0 = float(np.median(mags0)) + 1e-12                   # as the measure of that pair takes it: the same hits
        del mags0
        sources = [("backing", backing_of(mix0, voice0, lag0), ref0, (0.5, n0 / float(sr) - 0.5)),
                   ("backing_own", backing, ref, span)] + sources[1:]
        took = {"mix": os.path.abspath(backing_from[0]), "voice": os.path.abspath(backing_from[1]), "lag_samples": lag0}
    for name, x, r, within in sources:
        t, e = onset_envelope(x, sr, r)
        env[name] = (t, e)
        sets[name] = Hits(hits_of(t, e, span=within))
    vt, vdb = voice_level(voice_at, sr)
    syllables = {h["n"]: first_syllable(vt, vdb, float(h["t"])) for h in structure.get("hooks", [])}
    returns = band_returns(sets["backing"])
    moments = moments_of(structure, syllables, returns)
    near, reach = NEAR_FRAMES / float(FPS), REACH_FRAMES / float(FPS)
    for m in moments:
        m["near"] = _strengths(m["t"], sets, near)
        m["reach"] = _strengths(m["t"], sets, reach)
    events = look.get("mograph", {}).get("events", []) if isinstance(look.get("mograph"), dict) else []
    decisions = decide(events, moments, sets["backing"], structure.get("skirt", []), look.get("flares", []),
                       reach_of(structure), FPS)
    for d in decisions:
        d["at_old"] = _strengths(d["old_frame"] / float(FPS), sets, reach)
        if d.get("frame") is not None:
            d["at_new"] = _strengths(d["frame"] / float(FPS), sets, reach)
        title = d.get("title")
        if title is not None:
            d["old_from_voice_ms"] = round((d["old_frame"] / float(FPS) - title["t"]) * 1000.0, 1)
            if d.get("frame") is not None:
                d["new_from_voice_ms"] = round((d["frame"] / float(FPS) - title["t"]) * 1000.0, 1)
    if arrays:
        np.savez_compressed(arrays, **{"%s_t" % k: v[0].astype(np.float32) for k, v in env.items()},
                            **{"%s_e" % k: v[1].astype(np.float32) for k, v in env.items()},
                            voice_db_t=vt.astype(np.float32), voice_db=vdb.astype(np.float32))
    beat = structure.get("beat", {})
    return {"what": "flash_sync measure: the moments of the song, the hits and the decisions for the look's flashes",
            "inputs": {"mix": os.path.abspath(mix_path), "voice": os.path.abspath(voice_path)},
            "settings": {"sr": sr, "fps": FPS, "onset": [ONSET_WIN, ONSET_HOP, list(ONSET_BAND)], "hit_spacing": HIT_SPACING,
                         "voice": [VOICE_WIN, VOICE_HOP, list(VOICED)], "syllable_search": list(SYLLABLE_SEARCH),
                         "syllable_rise_db": SYLLABLE_RISE_DB, "stop_s": STOP_S, "quiet_pct": QUIET_PCT,
                         "strong": STRONG, "near_frames": NEAR_FRAMES, "reach_frames": REACH_FRAMES, "local": LOCAL,
                         "skirt_gap": SKIRT_GAP, "move_reach_s": round(reach_of(structure), 4),
                         "clock_lead_s": round(_clock_lead(sr, ONSET_WIN, ONSET_HOP, ONSET_BAND), 4),
                         "beat_first": beat.get("first"), "beat_period": beat.get("period")},
            "align": {"lag_samples": lag, "lag_ms": round(lag * 1000.0 / sr, 2), "gain_least_squares": round(gain, 3),
                      "gain_used": 1.0},
            "reference": checked,
            "backing_from": took,
            "hits": {k: v.summary() for k, v in sets.items()},
            "syllables": {str(k): v for k, v in syllables.items()}, "returns": returns,
            "moments": moments, "decisions": decisions}


# ---- the table and the figure --------------------------------------------------------------------------------------

KIND_JA = {"flash": "光のフラッシュ（飾り）", "flare": "フレア（look の flares）", "punch": "パンチ"}
ACTION_JA = {"keep": "そのまま", "move": "動かす", "drop": "削る"}


def _pct(s):
    return "-" if s is None else "%.0f" % s["pct"]


def _moment_ja(m):
    if m is None:
        return "-"
    if m["kind"] == "title":
        return "題名の語 %d の 1 音目（声）" % m["n"]
    if m["kind"] == "section":
        return "節の頭 %s" % m["id"]
    return "伴奏が戻る小節の頭%s" % ("" if m.get("bar") is None else "（小節 %d）" % m["bar"])


def _why_ja(d, st):
    """the reason of a decision, in Japanese"""
    why = d.get("why")
    if why == "strong_hit":
        return "%sに伴奏の強い立ち上がり（全曲の %.0f %% 点）がある" % (_moment_ja(d["moment"]), d["hit"]["pct"])
    if why == "no_strong_hit":
        return "1 小節の中の意味のある瞬間（題名の語の 1 音目・節の頭・伴奏が戻る所）の ±%d コマに、伴奏の %g %% 点以上の立ち上がりが無い" % (
            st["near_frames"], st["strong"])
    if why == "with_flash":
        return "光と同じコマから"
    if why == "flash_dropped_title":
        return "光を削ったので、題名の語 %d の 1 音目を歌うコマへ" % d["n"]
    if why == "skirt_title":
        return "光の所はスカートが広がる所の %g 秒にかかるので、題名の語 %d の 1 音目を歌うコマへ" % (st["skirt_gap"], d["n"])
    if why in ("flash_dropped_none", "skirt_none"):
        return "行き先が無いので削る"
    return d.get("reason", "-")


def table_md(report):
    """the decisions as a Markdown table (Japanese)"""
    fps = report["settings"]["fps"]
    lines = ["# 閃光の決め（tools/flash_sync.py）", "",
             "強い音: 伴奏（全体から声を引いた音）の立ち上がりのうち全曲の %g %% 点以上が、意味のある瞬間の ±%d コマにあること。"
             % (report["settings"]["strong"], report["settings"]["near_frames"]),
             "%% 点の列は、元のコマの ±%d コマの中で最も強い立ち上がりの、全曲の立ち上がりの中の %% 点（伴奏 / 全体 / 声）。"
             % report["settings"]["reach_frames"], ""]
    lines.append("| 種類 | 元の時刻（コマ） | 題名の語の 1 音目からの差 | 元の所の強さ（伴奏 / 全体 / 声） | 決め | 新しい時刻（コマ） | 意味の瞬間 | "
                 "新しい所の伴奏の強さ | 理由 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in report["decisions"]:
        a = d["at_old"]
        new = "-" if d.get("frame") is None else "%.3f 秒（%d）" % (d["frame"] / float(fps), d["frame"])
        hit = d.get("hit")
        new_pct = "-" if d["kind"] == "punch" else ("-" if hit is None else "%.0f（%+.0f ms、局所 %.1f 倍）"
                                                      % (hit["pct"], (hit["t"] - d["frame"] / float(fps)) * 1000, hit["local"]))
        lines.append("| %s | %.3f 秒（%d） | %s | %s / %s / %s | %s | %s | %s | %s | %s |" % (
            KIND_JA.get(d["kind"], d["kind"]), d["t"], d["old_frame"],
            "-" if d.get("old_from_voice_ms") is None else "%+.0f ms" % d["old_from_voice_ms"],
            _pct(a.get("backing")), _pct(a.get("mix")), _pct(a.get("voice")), ACTION_JA[d["action"]], new,
            _moment_ja(d.get("moment")), new_pct, _why_ja(d, report["settings"])))
    lines += ["", "## 意味のある瞬間（±%d コマの中で最も強い立ち上がりの %% 点: 伴奏 / 全体 / 声）" % report["settings"]["near_frames"], "",
              "| 瞬間 | 時刻 | 伴奏 | 全体 | 声 |", "| --- | --- | --- | --- | --- |"]
    for m in report["moments"]:
        s = m["near"]
        lines.append("| %s | %.3f 秒 | %s | %s | %s |" % (_moment_ja(m), m["t"], _pct(s["backing"]), _pct(s["mix"]), _pct(s["voice"])))
    return "\n".join(lines) + "\n"


LABELS = {
    "en": {"voice": "voice level (150-1500 Hz)", "hits": "backing hits", "strong": "strong backing hit (>= p%g)",
           "old": "light before", "new": "light after", "punch_old": "punch before", "punch_new": "punch after",
           "title": "title word %d sung", "return": "the band returns",
           "x": "seconds of the song (grey: beats, darker: bars; a moment's backing hit within a frame in brackets, percentile)",
           "overview": "the whole song: strong backing hits (red), section heads (black), title words sung (purple), "
                       "the light before (grey) and after (green)",
           "row": "%s at %.3f s (frame %d): %s"},
    "ja": {"voice": "声の強さ（150〜1500 Hz）", "hits": "伴奏の立ち上がり", "strong": "伴奏の強い立ち上がり（%g %% 点以上）",
           "old": "前の光", "new": "直した光", "punch_old": "前のパンチ", "punch_new": "直したパンチ",
           "title": "題名の語 %d の 1 音目", "return": "伴奏が戻る",
           "x": "曲の秒（灰の線: 拍、濃い線: 小節の頭。瞬間の名の後の括弧: その ±1 コマの伴奏の立ち上がりの % 点）",
           "overview": "全曲: 伴奏の強い立ち上がり（赤）、節の頭（黒）、題名の語の 1 音目（紫）、前の光（灰）と直した光（緑）",
           "row": "%s %.3f 秒（%d コマ）: %s"},
}
ACTION_LABEL = {"en": {"keep": "kept", "move": "moved to frame %d", "drop": "dropped"},
                "ja": {"keep": "そのまま", "move": "%d コマへ動かす", "drop": "削る"}}
KIND_LABEL = {"en": {"flash": "flash", "flare": "flare"}, "ja": {"flash": "光のフラッシュ", "flare": "フレア"}}
JA_FONTS = ("Meiryo", "Yu Gothic", "MS Gothic", "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic")


def compare_md(a, b, labels):
    """two sources of the song side by side (Japanese): the title words' first syllables as sung, the hits on them, and the
    decisions for the same look"""
    la, lb = labels
    fps = a["settings"]["fps"]

    def lag(rep):
        r = rep.get("reference")
        return "-" if not r else "%+.1f ms（r %.2f）" % (r["lag_ms"], r["r"])

    def backing(rep):
        took = rep.get("backing_from")
        return "自分の全体 − 自分の歌声" if not took else "参照の組（%s − %s）" % (os.path.basename(took["mix"]), os.path.basename(took["voice"]))
    lines = ["# 閃光の決め: %s と %s（tools/flash_sync.py compare）" % (la, lb), "",
             "| | %s | %s |" % (la, lb), "| --- | --- | --- |",
             "| 全体 | %s | %s |" % (os.path.basename(a["inputs"]["mix"]), os.path.basename(b["inputs"]["mix"])),
             "| 歌声 | %s | %s |" % (os.path.basename(a["inputs"]["voice"]), os.path.basename(b["inputs"]["voice"])),
             "| 構成の表の全体からのずれ | %s | %s |" % (lag(a), lag(b)),
             "| 伴奏の立ち上がり | %s | %s |" % (backing(a), backing(b)), "",
             "## 題名の語の 1 音目（声の帯の強さが立ち上がりの後の最大の半分になる時刻）", "",
             "| 題名の語 | 拍 | %s | %s | %s − %s | 1 音目の所の伴奏の %% 点（%s / %s） | 全体の %% 点（%s / %s） |"
             % (la, lb, lb, la, la, lb, la, lb),
             "| --- | --- | --- | --- | --- | --- | --- |"]
    ta = {m["n"]: m for m in a["moments"] if m["kind"] == "title"}
    tb = {m["n"]: m for m in b["moments"] if m["kind"] == "title"}
    for n in sorted(set(ta) | set(tb)):
        ma, mb = ta.get(n), tb.get(n)
        beat = (ma or mb)["beat"]

        def at(m):
            if m is None:
                return "-"
            return "%.3f 秒（拍の %+.0f ms、コマ %d）" % (m["t"], (m["t"] - beat) * 1000, frame_of_moment(m["t"], fps))
        diff = "-" if not (ma and mb) else "%+.0f ms" % ((mb["t"] - ma["t"]) * 1000)
        lines.append("| %d | %.3f 秒 | %s | %s | %s | %s / %s | %s / %s |" % (
            n, beat, at(ma), at(mb), diff, _pct(ma and ma["near"]["backing"]), _pct(mb and mb["near"]["backing"]),
            _pct(ma and ma["near"]["mix"]), _pct(mb and mb["near"]["mix"])))
    lines += ["", "## 決め（同じ look の閃光とパンチ）", "", "| 種類 | 元のコマ | %s | %s |" % (la, lb), "| --- | --- | --- | --- |"]

    def said(d):
        return ACTION_JA[d["action"]] + ("" if d.get("frame") is None or d["action"] == "keep" else " → %d" % d["frame"])
    for da, db in zip(a["decisions"], b["decisions"]):
        lines.append("| %s | %d | %s | %s |" % (KIND_JA.get(da["kind"], da["kind"]), da["old_frame"], said(da), said(db)))
    return "\n".join(lines) + "\n"


def figure(report, arrays, out, lang="en"):
    """the whole song in one row (the strong hits of the backing, the heads, the title words, the light before and after), then
    one row a flash or flare: the voice's level, the backing's hits (strong ones red, with their percentile), the beats, the
    moments, the old frame and the new, and the punches that go with it.  lang "ja" writes the labels in Japanese (needs a
    Japanese font)"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    L, A, K = LABELS[lang], ACTION_LABEL[lang], KIND_LABEL[lang]
    if lang == "ja":
        names = {f.name for f in font_manager.fontManager.ttflist}
        found = [n for n in JA_FONTS if n in names]
        if not found:
            raise ValueError("no Japanese font for the figure (looked for %s)" % ", ".join(JA_FONTS))
        matplotlib.rcParams["font.family"] = found[0]
    a = np.load(arrays)
    st = report["settings"]
    fps, strong = st["fps"], st["strong"]
    first, period = st["beat_first"], st["beat_period"]
    bt, be = a["backing_t"].astype(np.float64), a["backing_e"].astype(np.float64)
    hits = Hits(hits_of(bt, be, span=(0.5, float(bt[-1]) - 0.5)))
    pct = np.array([hits.percentile(h) for h in hits.heights])
    top = float(np.percentile(hits.heights, 99.5)) or 1.0
    rows = [d for d in report["decisions"] if d["kind"] in ("flash", "flare")]
    if not rows:
        raise ValueError("the report has no flash or flare")
    punches = [d for d in report["decisions"] if d["kind"] == "punch"]
    fig, axes = plt.subplots(len(rows) + 1, 1, figsize=(13, 1.6 + 2.7 * len(rows)), squeeze=False,
                             gridspec_kw={"height_ratios": [0.6] + [1.0] * len(rows)})
    ax = axes[0, 0]
    s = pct >= strong
    ax.vlines(hits.times[s], 0, 1, color="#e31a1c", lw=0.7)
    for m in report["moments"]:
        colour = {"section": "#000000", "title": "#6a3d9a", "return": "#e31a1c"}[m["kind"]]
        ax.vlines([m["t"]], 1.05, 1.6, color=colour, lw=1.4)
    for d in rows:
        ax.plot([d["old_frame"] / float(fps)], [-0.3], "v", color="#777777", ms=7)
        if d.get("frame") is not None:
            ax.plot([d["frame"] / float(fps)], [-0.6], "^", color="#33a02c", ms=8)
    ax.set_xlim(0, float(bt[-1]))
    ax.set_ylim(-1.0, 1.8)
    ax.set_yticks([])
    ax.set_title(L["overview"], fontsize=9)
    for ax, d in zip(axes[1:, 0], rows):
        times = [d["old_frame"] / float(fps)] + ([d["frame"] / float(fps)] if d.get("frame") is not None else [])
        title = d.get("title")
        if title:
            times.append(title["t"])
        # and the moments it could have gone to (a bar of its place): what the decision looked at
        reach = float(st.get("move_reach_s", 1.75))
        times += [m["t"] for m in report["moments"] if abs(m["t"] - d["old_frame"] / float(fps)) <= reach]
        lo, hi = min(times) - 0.45, max(times) + 0.6
        vt, vdb = a["voice_db_t"].astype(np.float64), a["voice_db"].astype(np.float64)
        m = (vt >= lo) & (vt <= hi)
        ref = float(np.percentile(vdb, 99))
        ax.plot(vt[m], 0.62 + 0.55 * np.clip((vdb[m] - ref + 50.0) / 50.0, 0, 1), color="#6a3d9a", lw=1.1, label=L["voice"])
        w = (hits.times >= lo) & (hits.times <= hi)
        weak = w & ~(pct >= strong)
        hard = w & (pct >= strong)
        ax.vlines(hits.times[weak], 0, np.clip(hits.heights[weak] / top, 0, 1) * 0.55, color="#1f78b4", lw=1.2, label=L["hits"])
        ax.vlines(hits.times[hard], 0, np.clip(hits.heights[hard] / top, 0, 1) * 0.55, color="#e31a1c", lw=2.0,
                  label=L["strong"] % strong)
        for i in np.nonzero(hard)[0]:
            ax.text(hits.times[i], np.clip(hits.heights[i] / top, 0, 1) * 0.55 + 0.02, "%.0f" % pct[i], fontsize=7,
                    color="#e31a1c", ha="center")
        if first is not None:
            k0 = int(math.ceil((lo - first) / period))
            for k in range(k0, int((hi - first) / period) + 1):
                ax.axvline(first + k * period, color="#999999" if k % 4 == 0 else "#dddddd", lw=0.8, zorder=0)
        for mo in report["moments"]:
            if lo <= mo["t"] <= hi:
                text = (L["title"] % mo["n"]) if mo["kind"] == "title" else (mo["id"] if mo["kind"] == "section" else L["return"])
                near = mo["near"]["backing"]
                text += " (%s)" % ("-" if near is None else "%.0f" % near["pct"])
                colour = {"section": "#000000", "title": "#6a3d9a", "return": "#e31a1c"}[mo["kind"]]
                ax.axvline(mo["t"], color=colour, lw=1.0, ls=":")
                ax.text(mo["t"], 1.22, text, fontsize=8, ha="center", color=colour)
        ax.axvspan(d["old_frame"] / float(fps), (d["old_frame"] + 1) / float(fps), color="#777777", alpha=0.45, label=L["old"])
        if d.get("frame") is not None:
            ax.axvspan(d["frame"] / float(fps), (d["frame"] + 1) / float(fps), color="#33a02c", alpha=0.6, label=L["new"])
        for p in punches:
            if p.get("flash") == d.get("index") and d["kind"] == "flash":
                ax.plot([p["old_frame"] / float(fps)], [-0.12], "v", color="#777777", ms=8, label=L["punch_old"])
                if p.get("frame") is not None:
                    ax.plot([p["frame"] / float(fps)], [-0.12], "v", color="#00a6c8", ms=8, label=L["punch_new"])
        ax.set_xlim(lo, hi)
        ax.set_ylim(-0.25, 1.35)
        ax.set_yticks([])
        what = A[d["action"]] % d["frame"] if d["action"] == "move" else A[d["action"]]
        ax.set_title(L["row"] % (K[d["kind"]], d["t"], d["old_frame"], what), fontsize=9)
    seen = {}
    for ax in axes[1:, 0]:
        for h, lab in zip(*ax.get_legend_handles_labels()):
            seen.setdefault(lab, h)
    fig.legend(list(seen.values()), list(seen.keys()), loc="lower center", fontsize=8, ncol=5, framealpha=0.9)
    axes[-1, 0].set_xlabel(L["x"])
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(out, dpi=110)
    plt.close(fig)


# ---- the commands --------------------------------------------------------------------------------------------------

def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("measure")
    p.add_argument("mix")
    p.add_argument("voice")
    p.add_argument("structure")
    p.add_argument("look")
    p.add_argument("out")
    p.add_argument("--arrays")
    p.add_argument("--reference", help="the mix the song structure was measured on: another source's mix must lie on it")
    p.add_argument("--backing-from", nargs=2, metavar=("MIX0", "VOICE0"),
                   help="the hits of the backing from this pair (the source the structure was measured on)")
    p = sub.add_parser("place")
    p.add_argument("look")
    p.add_argument("measure")
    p.add_argument("out")
    p = sub.add_parser("table")
    p.add_argument("measure")
    p.add_argument("out")
    p = sub.add_parser("compare")
    p.add_argument("measure_a")
    p.add_argument("measure_b")
    p.add_argument("out")
    p.add_argument("--labels", default="A,B", help="the names of the two sources, A,B")
    p = sub.add_parser("figure")
    p.add_argument("measure")
    p.add_argument("arrays")
    p.add_argument("out")
    p.add_argument("--lang", choices=sorted(LABELS), default="en")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "measure":
            rep = measure(args.mix, args.voice, _load(args.structure), _load(args.look), args.arrays, reference=args.reference,
                          backing_from=args.backing_from)
            rep["inputs"].update(structure=os.path.abspath(args.structure), look=os.path.abspath(args.look))
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "lag_ms": rep["align"]["lag_ms"],
                              "decisions": [[d["kind"], d["old_frame"], d["action"], d.get("frame")] for d in rep["decisions"]]}))
            return 0
        if args.cmd == "place":
            look = _load(args.look)
            rep = _load(args.measure)
            new = place(look, rep["decisions"])
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(new, f, ensure_ascii=False, indent=1)
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}))
            return 0
        if args.cmd == "table":
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(table_md(_load(args.measure)))
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}))
            return 0
        if args.cmd == "compare":
            labels = args.labels.split(",")
            if len(labels) != 2:
                raise ValueError("--labels is two names, A,B: not %r" % args.labels)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(compare_md(_load(args.measure_a), _load(args.measure_b), labels))
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}))
            return 0
        if args.cmd == "figure":
            figure(_load(args.measure), args.arrays, args.out, args.lang)
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}))
            return 0
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": {"type": "ValueError", "message": str(exc)}}, ensure_ascii=True))
        return 2
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
