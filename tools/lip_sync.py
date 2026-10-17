"""Lip-sync the mouth of a face motion to the singing voice: align the lyrics to the voice, then shape the mouth from it.

    python tools/lip_sync.py FACE.vmd VOCAL OUT.vmd --lines LINES.tsv [--report r.json] [--align-out a.json]
                             [--lead-ms 50] [--dance DANCE.vmd] [--max-keys N]

FACE is a face motion (tools/face_life.py's OUT, or the KAZUSA "Face&Lips"), VOCAL the singing voice alone, separated
from the song (any file ffmpeg reads; the MV's is htdemucs's "vocals" stem of the song), LINES the lyric lines, one a row,
tab-separated: where the line is sung roughly (start and end in seconds, within a second or so) and the line in kana
(hiragana or katakana; a space between words; a kanji is an error).  OUT is FACE with new keys for あ い う え お and
nothing else changed (every other key is written back as it was).  --dance: the dance loaded before FACE; where it keys
a vowel morph, OUT keys it too, so that OUT's track wins in MMD (face_life's shadowed).

Why (stage 6 lipsync, 2026-10-17): the mouth of the MV was the KAZUSA lip motion, rewritten by face_life.  Its vowels were
keyed by hand, a vowel a sung syllable, but on Sour's Rin the い shape shows only the line of the teeth (its open area is
2 % of あ's, measured on a rest-pose render), its height did not follow the voice (rank correlation with the loudness of
the separated voice 0.03 to 0.10), the mouth stayed open in 30 % of the rests inside the lines and looked shut in 16 % of
the sung time.  The mouth did not read as singing.

What is done:

1. The voice (features): the VOCAL at SR Hz, every HOP samples (10 ms, windows of WIN samples centred on the hop): the
   level in BAND (dB, relative to the 99th percentile of the song: e), MFCC c1..c12 (N_MELS mel bands) and a voicing
   measure (the highest normalised autocorrelation for a pitch between F0_RANGE).
2. The lyrics (moras): each line is cut into morae (parse_line): a consonant class (CONSONANTS: lips shut for m b p, the
   teeth for s z t d, ...), a vowel (a i u e o), ん (N), っ (Q) or ー (the vowel before, held).
3. Alignment (align): the lines that follow each other with less than BLOCK_GAP seconds between them are aligned to the
   voice together, by Viterbi through a left-to-right chain: silence, then per mora a consonant (if it has one), its
   vowel (at least SHORTEST rows), an optional short pause, and silence after each line (which may also take a sound
   that is no lyric, an ad lib or the echo of the line before, at FILLER a row).  A vowel alone after another syllable
   of the line (と お) has an optional break before it instead of the pause (breaks_before): a dip of the voice or near
   silence, scored as a consonant, so that a vowel sung as a new note after the voice dies down is found there (before
   2026-10-17 the only unit for such a dip was the next syllable's consonant: at 85.3 s of the MV と and お were
   squeezed into one note and the next と spread over two; review lipsync 5).  A line may sit only within LINE_SLACK
   of its given time.  A vowel's emission: loud, voiced and steady (no dip), its spectral model (a Gaussian on the MFCC
   per vowel and for ん, trained on this voice: the first pass has none, each next pass is trained on the previous
   alignment, ITERATIONS passes, weighed by SPECTRAL_WEIGHT), and the guide: FACE's own vowels, GUIDE_LAG later (a lip
   motion keyed by hand to the song knows which syllable is which where the voice alone is ambiguous: GUIDE added where
   its mouth shows that vowel, or another; --no-guide leaves it out).  A consonant is a dip of the level or near silence;
   silence is quiet.  Each mora gets c0 (its consonant starts), v0 (its vowel starts), v1 (its vowel ends), in seconds of
   the voice.
4. The mouth (mouth_track), every 10 ms of the voice: on a vowel the vowel's SHAPE (a mix of the model's morphs) times the
   gain of the voice (GAIN: from GAIN[0] at the soft level to 1 at the loud one, smoothed over GAIN_SMOOTH).  The mixes
   were measured on MMD's pictures of Sour's Rin with tools/mouth_shape.py (v11 face review, 2026-10-17): the opening's
   height is the morphs' weights times あ 1, い 0.217, う 0.487, え 0.565, お 0.609 of あ's (within 0.016 over 23 mixes),
   less a band of teeth of 0.245 x w(い)^2 that い brings into it: い alone shows only its teeth, no gap.  The MV shows
   あ's opening 4.7 to 5.5 pixels tall on the front camera and 6.1 to 8.1 on camera D (10 to 90 %, 1280x720): い with
   あ at 0.3 keeps a gap of 1.1 to 1.8 pixels there at gains 0.5 to 1 (0.1 keeps under 0.5: shut), which is why い
   is い + あ 0.3 although on a close picture it stands 88 % of the way from い to え in height (the rigging review's
   concern: on the MV's pictures い and え differ by 0.2 to 0.4 pixels).  う is う alone: its gap is 1.2 to 2.6 pixels
   there, and う + お 0.2 (before) stood taller than お itself (0.68 against 0.61 of あ's height).  On a consonant
   the shape of its vowel times the consonant's opening (CONSONANTS), only over its last CONSONANT_LONGEST (the rest of a
   long consonant is the closure before it); the lips shut on m b p (and on っ and on ん before them or at a pause);
   ん elsewhere nearly closed; over a break before a vowel alone, BREAK_SHARE of that vowel's shape at the voice's
   gain where the voice sounds, closed where it is quiet; silence closed, with a breath (INHALE) before a phrase that
   follows a rest of at least
   INHALE_REST.  The mixes are smoothed (a Gaussian of COARTICULATION ms: one shape flows into the next, a vowel's
   shape starts during the consonant before it) and then the lip closures are put back on top of the smoothing
   (CLOSURE_MOVE), so m b p still shut.
   Outside the aligned singing (an ad lib, a vocal chop, the title word sung outside the lines): the author's vowels of
   FACE where the voice sings (FACE's shape at the voice's gain), closed (at most REST_OPEN) where it does not; where
   FACE closes while the voice sings on above HOLD_DB, FACE's last vowel is held to the end of that run of the voice (the
   end of the long note at 233.2 s of the MV: FACE closed 0.3 s before the voice), and a sound FACE never opened the
   mouth on stays closed (the separated voice also carries what is no singing: at 189 to 196 s of the MV a quiet sound
   unlike her vowels, at 247.3 s a pure tone of the accompaniment; v11 face review).  FACE is
   read GUIDE_LAG later (its own lead taken out), so that there too the mouth leads the voice by --lead-ms and not by
   both (before 2026-10-17 it closed some 0.1 s before the end of a long note outside the lines).
5. The motion: OUT frame f is the mouth at (f + SHOWN) / FPS + LEAD (the MV shows frame f at f + 0.1875, tools/mv_look.py;
   the mouth leads the voice by --lead-ms: in speech the face moves from 20 ms after to 70 ms before the sound of a
   consonant-vowel syllable, Schwartz & Savariaux 2014, PLoS Comput Biol 10(7) e1003743; animators open the jaw two
   frames before the sound; the KAZUSA keys lead by 40 to 70 ms, analysis a12).  The keys of each vowel are those
   straight lines need to stay within KEY_TOLERANCE of every frame; with --max-keys the tolerance grows until all the
   vowel keys fit (MMD registers at most 20,000 morph points for a model, over every motion loaded).

The report (--report, in short on stdout) gives the alignment (per line: its time, how many morae, the mean emission
score a frame), how the vowel onsets of FACE (tools/lip_timing.py onsets) sit against the aligned vowel onsets of the
voice (FACE's lead: positive when the mouth comes first), and the keys.  --align-out writes every mora's times.
The guide pulls the alignment to FACE's vowels GUIDE_LAG later, so FACE's lead sits near GUIDE_LAG by construction: it
shows the guide holds, not that the alignment agrees with the hand-made mouth on its own.  Nor does a lag measured
against this alignment say whether OUT goes with the voice (OUT is placed from it); tools/lip_check.py measures that
with times taken from the voice alone.
"""
import argparse
import dataclasses
import importlib.util
import json
import math
import os
import subprocess
import sys
import unicodedata
from typing import List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli.formats import vmd  # noqa: E402

FPS = 30.0
SHOWN = 0.1875                  # frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py)
SR = 16000
HOP = 160                       # 10 ms
WIN = 400                       # 25 ms
NFFT = 512
AC_FFT = 1024
N_MELS = 40
MEL_RANGE = (80.0, 7600.0)
N_MFCC = 12
BAND = (250.0, 4000.0)
F0_RANGE = (150.0, 1300.0)
STEP = HOP / float(SR)          # seconds a feature row

VOWELS = ("あ", "い", "う", "え", "お")
SHAPES = {"a": {"あ": 1.0}, "i": {"い": 1.0, "あ": 0.3}, "u": {"う": 1.0}, "e": {"え": 1.0}, "o": {"お": 1.0}}
# consonant class -> (share of its vowel's opening kept, a shape of its own or None).  The shares are chosen, not
# measured: the lips shut for m b p, nearly for v f (the lower lip to the teeth), the jaw rises for the teeth and the
# tongue tip (s z t d n), less for r k g h; y passes through い, w through う.
CONSONANTS = {"m": (0.0, None), "v": (0.12, None), "f": (0.25, "u"), "s": (0.35, None), "n": (0.35, None),
              "r": (0.55, None), "k": (0.5, None), "h": (0.6, None), "y": (0.5, "i"), "w": (0.45, "u")}
N_OPEN = 0.15                   # ん, not before the lips shut: nearly closed
BREAK_SHARE = 0.6               # a break before a vowel alone keeps this share of its opening where the voice sounds
                                # (chosen as for h: the jaw stays, nothing closes it)
CONSONANT_LONGEST = 0.10        # s: a consonant shapes the mouth over this much before its vowel at most
GAIN = (0.5, -24.0, -6.0)       # the gain at the soft level, the soft level and the loud level (dB, e)
GAIN_SMOOTH = 0.05              # s
INHALE = 0.22                   # あ of the breath before a phrase
INHALE_REST = 0.45              # s of silence before a phrase that let her breathe in
INHALE_SPAN = (0.40, 0.12)      # s before the phrase's first sound: the breath starts and is gone
COARTICULATION = 30.0           # ms: the sigma of the Gaussian that smooths the shapes (10 to 90 % in 77 ms)
CLOSURE_MOVE = 0.16             # s: the lips shut over this much centred on a closure's start and open over this much
                                # centred on its end (the sound of the vowel starts as they part); a closure shorter
                                # than this shuts at its middle (a lip stroke takes 3 to 4 frames, analysis a12 from
                                # Huber & Chandrasekaran 2006)
CLOSURE_HOLD = 0.04             # s: the lips stay shut at least this long (a frame of the MV at least)
CLOSURE_RAMP = 0.10             # s: shutting and parting take at least this long each
RELEASE = 0.12                  # s: after the last vowel of a phrase the singing ends here
REST_OPEN = 0.15                # outside the singing, where the voice is silent, the mouth opens at most this
HOLD_DB = -20.0                 # outside the lines, FACE's last vowel is held while the voice stays above this (e: the
                                # voice clearly sings, tools/lip_check.py's LOUD_DB)
LEAD_MS = 50.0
KEY_TOLERANCE = 0.025
SIL_DB = -30.0                  # e below this: quiet
FILLER = -2.5                   # log a row: the silence between lines may hold a sound that is no lyric (an ad lib, a
                                # breath, a vocal chop, the echo of the line before) at this cost; a vowel of the line
                                # that sounds like itself scores better, any other worse
BLOCK_GAP = 2.0                 # s between lines that are aligned apart
LINE_SLACK = (1.0, 1.5)         # s a line may begin before its given start, end after its given end
MARGIN = (1.2, 1.6)             # s of the voice taken before and after a block
ITERATIONS = 6
STAY = {"V": 0.9, "C": 0.6, "G": 0.6, "N": 0.85, "Q": 0.85, "SIL": 0.95, "SP": 0.9}
SP_PENALTY = (4.0, 1.5)         # log: a short pause inside a word, between words
SPECTRAL_WEIGHT = 0.5
GUIDE = (2.0, -1.0)             # log a row added to a vowel where the guide's mouth shows that vowel, another vowel
GUIDE_OPEN = 0.3                # the guide's mouth shows a vowel where its mixes add up to more than this
GUIDE_LAG = 0.07                # s: the guide's mouth leads the voice by this much (KAZUSA's keys, analysis a12)
POSTERIOR_FLOOR = -6.0
CLASSES = ("a", "i", "u", "e", "o", "N")
NEG = -1e9


# ---- the lyrics ------------------------------------------------------------------------------

@dataclasses.dataclass
class Mora:
    kana: str
    consonant: str              # "" or a key of CONSONANTS
    vowel: str                  # a i u e o, N (ん) or Q (っ)
    word_start: bool = False
    held: bool = False          # ー: the vowel before, held


_GLIDE_VOWEL = {"YA": "a", "YU": "u", "YO": "o", "A": "a", "I": "i", "U": "u", "E": "e", "O": "o", "WA": "a"}
_SPECIAL = {"SI": ("s", "i"), "TI": ("s", "i"), "TU": ("s", "u"), "HU": ("f", "u"), "ZI": ("s", "i"), "DI": ("s", "i"),
            "DU": ("s", "u"), "WO": ("w", "o"), "VU": ("v", "u")}
_CLASS = {"K": "k", "G": "k", "S": "s", "Z": "s", "T": "s", "D": "s", "N": "n", "H": "h", "B": "m", "P": "m", "M": "m",
          "Y": "y", "R": "r", "W": "w", "V": "v"}
_BREAKS = set(" 　\t、。,.!?！？「」『』()（）・…")


def parse_line(line):
    """the morae of a line of kana (see Mora); ValueError on a kanji or a letter it cannot read"""
    out: List[Mora] = []
    word_start = True
    for ch in line:
        if ch in _BREAKS:
            word_start = True
            continue
        name = unicodedata.name(ch, "")
        if "PROLONGED SOUND MARK" in name or ch == "～":
            if out and out[-1].vowel in "aiueo":
                out.append(Mora(ch, "", out[-1].vowel, word_start, held=True))
                word_start = False
            continue
        if name.startswith("CJK UNIFIED IDEOGRAPH") or name.startswith("CJK COMPATIBILITY IDEOGRAPH"):
            raise ValueError("cannot read the kanji %s: write the line in kana"
                             % ch.encode("ascii", "backslashreplace").decode("ascii"))
        if "HIRAGANA LETTER " not in name and "KATAKANA LETTER " not in name:
            raise ValueError("cannot read %s in a lyric line" % ch.encode("ascii", "backslashreplace").decode("ascii"))
        syllable = name.split("LETTER ", 1)[1]
        small = syllable.startswith("SMALL ")
        syllable = syllable.replace("SMALL ", "")
        if small and syllable == "TU":
            out.append(Mora(ch, "", "Q", word_start))
        elif syllable == "N":
            out.append(Mora(ch, "", "N", word_start))
        elif small and syllable in _GLIDE_VOWEL and out and out[-1].vowel in "aiueo" and not out[-1].held:
            prev = out[-1]
            prev.kana += ch
            prev.vowel = _GLIDE_VOWEL[syllable]
            if syllable == "WA":
                prev.consonant = prev.consonant or "w"
            continue
        else:
            if syllable in _SPECIAL:
                consonant, vowel = _SPECIAL[syllable]
            else:
                vowel = syllable[-1].lower()
                head = syllable[:-1]
                if vowel not in "aiueo" or (head and head[0] not in _CLASS):
                    raise ValueError("cannot read %s in a lyric line" % ch.encode("ascii", "backslashreplace").decode("ascii"))
                consonant = _CLASS[head[0]] if head else ""
            out.append(Mora(ch, consonant, vowel, word_start))
        word_start = False
    return out


def read_lines(path):
    """[(start s, end s, kana)] of a lines file (start, end and the line, tab-separated; # starts a comment)"""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for n, row in enumerate(f, start=1):
            row = row.rstrip("\r\n")
            if not row.strip() or row.lstrip().startswith("#"):
                continue
            parts = row.split("\t")
            if len(parts) < 3:
                raise ValueError("line %d of %s: want start, end and the line, tab-separated" % (n, path))
            start, end = float(parts[0]), float(parts[1])
            if not end > start:
                raise ValueError("line %d of %s: the end is not after the start" % (n, path))
            rows.append((start, end, parts[2].strip()))
    rows.sort(key=lambda r: r[0])
    return rows


# ---- the voice -------------------------------------------------------------------------------

def read_sound(path):
    """the sound of `path` as mono float32 at SR, read with ffmpeg"""
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def mel_matrix():
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    hz = mel2hz(np.linspace(hz2mel(MEL_RANGE[0]), hz2mel(MEL_RANGE[1]), N_MELS + 2))
    bins = np.fft.rfftfreq(NFFT, 1.0 / SR)
    m = np.zeros((N_MELS, len(bins)))
    for i in range(N_MELS):
        lo, c, hi = hz[i], hz[i + 1], hz[i + 2]
        m[i] = np.clip(np.minimum((bins - lo) / (c - lo), (hi - bins) / (hi - c)), 0.0, None)
    return m


@dataclasses.dataclass
class Voice:
    level: np.ndarray           # dB in BAND, relative to the 99th percentile (e)
    mfcc: np.ndarray            # [T, N_MFCC], standardised over the frames that are not quiet
    voicing: np.ndarray         # 0..1
    dip: np.ndarray             # dB under the loudest of the 170 ms around

    @property
    def frames(self):
        return len(self.level)


def features(x):
    """the Voice of a mono signal at SR; row k is centred on k * STEP seconds"""
    x = np.asarray(x, np.float32)
    pad = np.pad(x, (WIN // 2, WIN // 2))
    n = max(0, 1 + (len(pad) - WIN) // HOP)
    if n < 10:
        raise ValueError("the voice is too short")
    win = np.hanning(WIN).astype(np.float32)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    band = (freqs >= BAND[0]) & (freqs < BAND[1])
    mel = mel_matrix()
    k = np.arange(1, N_MFCC + 1)[:, None]
    dct = np.sqrt(2.0 / N_MELS) * np.cos(np.pi * k * (np.arange(N_MELS)[None, :] + 0.5) / N_MELS)
    wac = np.fft.irfft(np.abs(np.fft.rfft(win, AC_FFT)) ** 2, AC_FFT)
    lags = np.arange(int(SR / F0_RANGE[1]), int(SR / F0_RANGE[0]) + 1)
    power = np.zeros(n)
    mf = np.zeros((n, N_MFCC))
    voicing = np.zeros(n)
    for s0 in range(0, n, 2000):
        s1 = min(n, s0 + 2000)
        idx = (np.arange(s0, s1) * HOP)[:, None] + np.arange(WIN)[None, :]
        seg = pad[idx] * win
        spec = np.fft.rfft(seg, NFFT, axis=1)
        p = spec.real ** 2 + spec.imag ** 2
        power[s0:s1] = p[:, band].sum(axis=1)
        mf[s0:s1] = np.log(p @ mel.T + 1e-10) @ dct.T
        sp = np.fft.rfft(seg, AC_FFT, axis=1)
        ac = np.fft.irfft(sp.real ** 2 + sp.imag ** 2, AC_FFT, axis=1)
        norm = ac[:, lags] / np.maximum(ac[:, :1], 1e-12) / (wac[lags] / wac[0])[None, :]
        voicing[s0:s1] = np.clip(norm.max(axis=1), 0.0, 1.0)
    db = 10.0 * np.log10(power + 1e-12)
    level = db - float(np.percentile(db, 99))
    loud = level > SIL_DB
    ref = mf[loud] if loud.sum() > 10 else mf
    mfcc = (mf - ref.mean(axis=0)) / (ref.std(axis=0) + 1e-6)
    padded = np.pad(level, 8, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 17)
    dip = windows.max(axis=1) - level
    return Voice(level=level, mfcc=mfcc, voicing=voicing, dip=dip)


def _logsig(x):
    return -np.logaddexp(0.0, -x)


# ---- the alignment ---------------------------------------------------------------------------

@dataclasses.dataclass
class Unit:
    kind: str                   # V C N Q SIL SP
    label: str                  # the vowel (V), the class (C), "" otherwise
    line: int                   # the line it belongs to (-1: silence between lines and around the block)
    mora: int                   # its mora in the line (-1 for silences)
    optional: bool
    enter: float                # log, added on entering it
    shortest: int               # frames


SHORTEST = {"V": 5, "C": 2, "G": 2, "N": 4, "Q": 3, "SIL": 1, "SP": 3}


def breaks_before(morae, mi):
    """whether mora mi of a line gets an optional break (G) before its vowel: a vowel alone after another syllable of
    the line (と お: sung legato it needs none, sung as a new note it may start after a dip of the voice)"""
    m = morae[mi]
    return mi > 0 and not m.consonant and m.vowel in "aiueo"


def chain(lines_morae):
    """the units of a block: silence, the morae of each line (consonant or break, vowel, optional pause), silence"""
    units = [Unit("SIL", "", -1, -1, False, 0.0, SHORTEST["SIL"])]
    for li, morae in lines_morae:
        for mi, m in enumerate(morae):
            if m.consonant:
                units.append(Unit("C", m.consonant, li, mi, False, 0.0, SHORTEST["C"]))
            elif breaks_before(morae, mi):
                units.append(Unit("G", "", li, mi, True, 0.0, SHORTEST["G"]))
            kind = "V" if m.vowel in "aiueo" else m.vowel
            units.append(Unit(kind, m.vowel if kind == "V" else "", li, mi, False, 0.0, SHORTEST[kind]))
            last = mi == len(morae) - 1
            if not last and not breaks_before(morae, mi + 1):
                # (before a break the break is the pause: two optional units in a row could not both be skipped)
                nxt = morae[mi + 1]
                units.append(Unit("SP", "", li, mi, True, -(SP_PENALTY[1] if nxt.word_start else SP_PENALTY[0]),
                                  SHORTEST["SP"]))
        units.append(Unit("SIL", "", -1, -1, True, 0.0, SHORTEST["SIL"]))
    units[-1].optional = False
    return units


class Model:
    """the Gaussians (diagonal) of the vowels and ん on the MFCC, trained on an alignment"""

    def __init__(self):
        self.mean = {}
        self.std = {}

    def trained(self):
        return len(self.mean) >= 2

    def posteriors(self, mfcc):
        """[T, len(CLASSES)] log posteriors (flat prior) of the trained classes, POSTERIOR_FLOOR for the others"""
        out = np.full((len(mfcc), len(CLASSES)), 0.0)
        if not self.trained():
            return out
        ll = np.full((len(mfcc), len(CLASSES)), -np.inf)
        for j, c in enumerate(CLASSES):
            if c in self.mean:
                z = (mfcc - self.mean[c]) / self.std[c]
                ll[:, j] = -0.5 * (z ** 2).sum(axis=1) - np.log(self.std[c]).sum()
        top = ll.max(axis=1, keepdims=True)
        lse = top + np.log(np.exp(ll - top).sum(axis=1, keepdims=True))
        out = np.maximum(ll - lse, POSTERIOR_FLOOR)
        return out

    def fit(self, voice, segments):
        """segments: [(class, first row, last row)]: the rows inside each (2 off each end when it is long) that are not
        quiet"""
        rows = {c: [] for c in CLASSES}
        for c, a, b in segments:
            if b - a >= 6:
                a, b = a + 2, b - 2
            for r in range(a, b + 1):
                if voice.level[r] > SIL_DB:
                    rows[c].append(r)
        mean, std = {}, {}
        for c, rs in rows.items():
            if len(rs) >= 12:
                x = voice.mfcc[rs]
                mean[c] = x.mean(axis=0)
                std[c] = np.maximum(x.std(axis=0), 0.15)
        self.mean, self.std = mean, std


def emissions(voice, model, rows, guide=None):
    """{column: [len(rows)] log score} for the unit kinds; columns V:a .. V:o, N, C, Q, SIL.  guide: [T, 5] the mixes of
    あいうえお of a lip motion made for the song, on the rows of the voice (GUIDE_LAG later), or None"""
    e = voice.level[rows]
    loud = _logsig((e - SIL_DB) / 3.0)
    quiet = _logsig((SIL_DB - e) / 3.0)
    voiced = 0.5 * _logsig((voice.voicing[rows] - 0.45) / 0.08)
    post = model.posteriors(voice.mfcc[rows]) * SPECTRAL_WEIGHT
    dip = voice.dip[rows]
    out = {}
    steady = 0.5 * _logsig((4.0 - dip) / 1.5)
    for j, c in enumerate(CLASSES):
        if c == "N":
            out["N"] = loud + voiced + post[:, j] + 0.5 * _logsig((dip - 1.0) / 2.0)
        else:
            out["V:" + c] = loud + voiced + post[:, j] + steady
            if guide is not None:
                g = guide[rows]
                shown = g.sum(axis=1) > GUIDE_OPEN
                dominant = np.argmax(g, axis=1)
                out["V:" + c] = out["V:" + c] + np.where(shown, np.where(dominant == j, GUIDE[0], GUIDE[1]), 0.0)
    out["C"] = np.log(0.5 * np.exp(_logsig((dip - 4.0) / 1.2)) + 0.5 * np.exp(_logsig((SIL_DB + 5.0 - e) / 3.0)) + 1e-4)
    out["G"] = out["C"]                               # a break before a vowel: a dip of the voice or near silence
    out["Q"] = quiet
    out["SIL"] = np.logaddexp(quiet, FILLER)          # between the lines also a sound that is no lyric (an ad lib)
    out["SP"] = quiet
    return out


def _column(u):
    if u.kind == "V":
        return "V:" + u.label
    return u.kind


def viterbi(units, emis, allowed):
    """the unit of every row (an index into units) on the best path from the first unit to the last; allowed: [(first
    row, last row)] per unit"""
    states = []                 # (unit index, is its last state)
    first_state = []
    for ui, u in enumerate(units):
        first_state.append(len(states))
        for k in range(u.shortest):
            states.append((ui, k == u.shortest - 1))
    S = len(states)
    T = len(next(iter(emis.values())))
    unit_of = np.array([s[0] for s in states])
    last = np.array([s[1] for s in states])
    stay = np.where(last, np.log([STAY[units[i].kind] for i in unit_of]), NEG)
    adv = np.zeros(S)
    skip_from = np.full(S, -1)
    skip_lp = np.full(S, NEG)
    for ui, u in enumerate(units):
        s = first_state[ui]
        if ui == 0:
            adv[s] = NEG
            continue
        prev = units[ui - 1]
        adv[s] = math.log(1.0 - STAY[prev.kind]) + u.enter
        if prev.optional and ui >= 2:
            skip_from[s] = first_state[ui - 1] - 1          # the last state of the unit before the optional one
            skip_lp[s] = math.log(1.0 - STAY[units[ui - 2].kind]) + u.enter
    cols = sorted({_column(u) for u in units})
    col_index = {c: i for i, c in enumerate(cols)}
    E = np.stack([emis[c] for c in cols], axis=1)          # [T, columns]
    col_of_state = np.array([col_index[_column(units[i])] for i in unit_of])
    lo = np.array([allowed[i][0] for i in unit_of])
    hi = np.array([allowed[i][1] for i in unit_of])
    back = np.zeros((T, S), np.int8)
    delta = np.full(S, NEG)
    delta[0] = E[0, col_of_state[0]]
    has_skip = skip_from >= 0
    sf = np.where(has_skip, skip_from, 0)
    for t in range(1, T):
        c0 = delta + stay
        c1 = np.concatenate(([NEG], delta[:-1])) + adv
        c2 = np.where(has_skip, delta[sf] + skip_lp, NEG)
        best = np.maximum(np.maximum(c0, c1), c2)
        choice = np.where(best == c0, 0, np.where(best == c1, 1, 2)).astype(np.int8)
        ok = (t >= lo) & (t <= hi)
        delta = best + E[t, col_of_state] + np.where(ok, 0.0, NEG)
        back[t] = choice
    if delta[S - 1] < NEG / 2:
        raise ValueError("the lines do not fit the voice within their times")
    path = np.zeros(T, np.int64)
    s = S - 1
    score = float(delta[S - 1])
    for t in range(T - 1, -1, -1):
        path[t] = unit_of[s]
        c = back[t, s]
        if c == 1:
            s -= 1
        elif c == 2:
            s = skip_from[s]
    return path, score


def blocks(lines):
    """[[line index, ...]] of lines less than BLOCK_GAP apart"""
    out = []
    for i, (start, end, _) in enumerate(lines):
        if out and start - lines[out[-1][-1]][1] < BLOCK_GAP:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _segments(path, units, r0):
    """[(unit index, first row, last row)] of the path (rows offset by r0)"""
    out = []
    start = 0
    for t in range(1, len(path) + 1):
        if t == len(path) or path[t] != path[start]:
            out.append((int(path[start]), r0 + start, r0 + t - 1))
            start = t
    return out


def align(voice, lines, iterations=ITERATIONS, guide=None):
    """every mora's times: [{"line", "mora", "kana", "consonant", "vowel", "c0", "v0", "v1"}] (seconds) and the per line
    fit, after `iterations` passes (the first without spectral models)"""
    parsed = [parse_line(text) for _, _, text in lines]
    for i, morae in enumerate(parsed):
        if not morae:
            raise ValueError("lyric line %d has no mora" % (i + 1))
    model = Model()
    result = None
    for it in range(iterations):
        result = _align_pass(voice, lines, parsed, model, guide)
        segs = []
        for m in result["morae"]:
            if m["vowel"] in CLASSES and m["v1"] > m["v0"]:
                segs.append((m["vowel"], int(round(m["v0"] / STEP)), int(round(m["v1"] / STEP)) - 1))
        model.fit(voice, segs)
    result["model_classes"] = sorted(model.mean)
    return result


def _align_pass(voice, lines, parsed, model, guide=None):
    morae_out, fits = [], []
    for block in blocks(lines):
        t0 = max(0.0, lines[block[0]][0] - MARGIN[0])
        t1 = min(voice.frames * STEP, lines[block[-1]][1] + MARGIN[1])
        r0, r1 = int(t0 / STEP), min(voice.frames - 1, int(t1 / STEP))
        rows = np.arange(r0, r1 + 1)
        units = chain([(i, parsed[i]) for i in block])
        allowed = []
        for u in units:
            if u.line < 0:
                allowed.append((0, len(rows) - 1))
            else:
                s, e, _ = lines[u.line]
                allowed.append((max(0, int((s - LINE_SLACK[0]) / STEP) - r0), int((e + LINE_SLACK[1]) / STEP) - r0))
        emis = emissions(voice, model, rows, guide)
        path, score = viterbi(units, emis, allowed)
        segs = _segments(path, units, r0)
        times = {}
        for ui, a, b in segs:
            u = units[ui]
            if u.line < 0 or u.kind in ("SP",):
                continue
            d = times.setdefault((u.line, u.mora), {})
            if u.kind == "C":
                d["c0"] = a * STEP
            elif u.kind == "G":
                d["g0"] = a * STEP
            else:
                d["v0"] = a * STEP
                d["v1"] = (b + 1) * STEP
        per_line = {}
        for (li, mi), d in sorted(times.items()):
            m = parsed[li][mi]
            v0 = d.get("v0")
            if v0 is None:
                continue
            c0 = d.get("c0", v0)
            row = {"line": li, "mora": mi, "kana": m.kana, "consonant": m.consonant, "vowel": m.vowel,
                   "held": m.held, "word_start": m.word_start, "c0": round(c0, 3), "v0": round(v0, 3),
                   "v1": round(d["v1"], 3)}
            if "g0" in d:
                row["g0"] = round(d["g0"], 3)               # the break before this vowel starts
            morae_out.append(row)
            per_line.setdefault(li, []).append((d.get("g0", c0), d["v1"]))
        col = {c: emis[c] for c in emis}
        own = np.array([col[_column(units[path[t]])][t] for t in range(len(path))])
        for li in block:
            if li in per_line:
                a = min(x for x, _ in per_line[li])
                b = max(y for _, y in per_line[li])
                ra, rb = int(a / STEP) - r0, int(b / STEP) - r0
                fits.append({"line": li, "start": round(a, 3), "end": round(b, 3), "morae": len(parsed[li]),
                             "fit": round(float(own[ra:rb].mean()), 3) if rb > ra else None})
    return {"morae": morae_out, "lines": fits}


# ---- the mouth -------------------------------------------------------------------------------

def shape(vowel):
    v = np.zeros(5)
    for name, w in SHAPES[vowel].items():
        v[VOWELS.index(name)] = w
    return v


def gain_track(voice):
    lo, soft, loud = GAIN
    g = np.clip(lo + (1.0 - lo) * (voice.level - soft) / (loud - soft), lo, 1.0)
    n = max(1, int(round(GAIN_SMOOTH / STEP)))
    return np.convolve(np.pad(g, (n // 2, n - 1 - n // 2), mode="edge"), np.ones(n) / n, mode="valid")


def _raised(x):
    x = np.clip(x, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * x)


def mouth_track(voice, morae, face_rows=None):
    """the mixes of あいうえお every row of the voice ([T, 5]) and the rows of the aligned singing; face_rows: FACE's
    mixes on the same rows (for the singing outside the lines), or None"""
    T = voice.frames
    X = np.zeros((T, 5))
    sung = np.zeros(T, bool)
    closures = []
    g = gain_track(voice)
    loud = voice.level > SIL_DB
    rowsof = lambda s: int(round(s / STEP))  # noqa: E731
    by_line = {}
    for m in morae:
        by_line.setdefault(m["line"], []).append(m)
    phrases = []
    for li in sorted(by_line):
        ms = sorted(by_line[li], key=lambda m: m["mora"])
        for k, m in enumerate(ms):
            nxt = ms[k + 1] if k + 1 < len(ms) else None
            prev = ms[k - 1] if k > 0 else None
            c0, v0, v1 = rowsof(m["c0"]), rowsof(m["v0"]), rowsof(m["v1"])
            c0 = max(c0, v0 - int(round(CONSONANT_LONGEST / STEP)))
            pause_after = nxt is None or rowsof(nxt.get("g0", nxt["c0"])) - v1 >= 15
            if m["vowel"] in "aiueo":
                base = shape(m["vowel"])
                X[v0:v1] = base[None, :] * g[v0:v1, None]
                if "g0" in m:
                    # a break before a vowel alone (the voice dips and starts the vowel again): the jaw stays near the
                    # vowel where the voice still sounds, the mouth closes where it is silent
                    g0 = rowsof(m["g0"])
                    X[g0:v0] = base[None, :] * (BREAK_SHARE * g[g0:v0, None]) * loud[g0:v0, None]
                    c0 = min(c0, g0)
                if m["consonant"]:
                    share, own = CONSONANTS[m["consonant"]]
                    if share == 0.0:
                        # behind shut lips the jaw already takes the vowel (the lips alone close and part)
                        X[c0:v0] = base[None, :] * g[c0:v0, None]
                        closures.append((c0, v0))
                    else:
                        target = shape(own) if own else base
                        X[c0:v0] = target[None, :] * (share * g[c0:v0, None])
            elif m["vowel"] == "N":
                shut = pause_after or (nxt is not None and nxt["consonant"] == "m")
                if shut:
                    closures.append((v0, v1))
                    if not pause_after and nxt["vowel"] in "aiueo":
                        X[v0:v1] = shape(nxt["vowel"])[None, :] * g[v0:v1, None]
                elif prev is not None and prev["vowel"] in "aiueo":
                    X[v0:v1] = shape(prev["vowel"])[None, :] * (N_OPEN * g[v0:v1, None])
            elif m["vowel"] == "Q":
                closures.append((v0, v1))
                if not pause_after and nxt["vowel"] in "aiueo":
                    X[v0:v1] = shape(nxt["vowel"])[None, :] * g[v0:v1, None]
            sung[c0:v1] = True
            if phrases and c0 - phrases[-1][1] < 15:
                phrases[-1][1] = v1
            else:
                phrases.append([c0, v1])
    release = int(round(RELEASE / STEP))
    for a, b in phrases:
        sung[a:min(T, b + release)] = True
    # outside the singing: the author's vowels where the voice sings, closed (at most REST_OPEN) where it does not
    if face_rows is not None:
        outside = ~sung
        voiced = outside & loud
        total = face_rows.sum(axis=1)
        dom = np.argmax(face_rows, axis=1)
        for r in np.where(voiced & (total > 0.3))[0]:
            X[r] = shape("aiueo"[dom[r]]) * g[r]
        # where FACE closes the mouth while the voice sings on (above HOLD_DB without a break), its last vowel is held to
        # the voice's end; a sound FACE never opened the mouth on in that run stays closed (a leak of the accompaniment)
        on = outside & (voice.level > HOLD_DB)
        last = None
        for r in range(T):
            if not on[r]:
                last = None
            elif total[r] > 0.3:
                last = dom[r]
            elif last is not None:
                X[r] = shape("aiueo"[last]) * g[r]
        quiet = outside & ~loud
        X[quiet] = np.minimum(face_rows[quiet], REST_OPEN)
    # the breath before a phrase that follows a rest
    for k, (a, b) in enumerate(phrases):
        rest = a - (phrases[k - 1][1] if k > 0 else -10 ** 6)
        if rest * STEP < INHALE_REST:
            continue
        r0, r1 = a - rowsof(INHALE_SPAN[0]), a - rowsof(INHALE_SPAN[1])
        if r0 < 0 or r1 <= r0:
            continue
        mid = (r0 + r1) / 2.0
        for r in range(r0, r1):
            w = _raised(1.0 - abs(r - mid) / ((r1 - r0) / 2.0))
            X[r, 0] = max(X[r, 0], INHALE * w)
    # coarticulation, then the closures again on top
    sigma = COARTICULATION / 1000.0 / STEP
    if sigma > 0:
        rad = int(math.ceil(4 * sigma))
        ker = np.exp(-0.5 * (np.arange(-rad, rad + 1) / sigma) ** 2)
        ker /= ker.sum()
        X = np.stack([np.convolve(np.pad(X[:, j], rad, mode="edge"), ker, mode="valid") for j in range(5)], axis=1)
    env = np.ones(T)
    half = CLOSURE_MOVE / STEP / 2.0
    hold = CLOSURE_HOLD / STEP / 2.0
    ramp = CLOSURE_RAMP / STEP
    for a, b in closures:
        mid = (a + b) / 2.0
        ca, cb = min(a + half, mid - hold), max(b - half, mid + hold)
        s0, e0 = min(a - half, ca - ramp), max(b + half, cb + ramp)
        da, db = ca - s0, e0 - cb
        r = np.arange(max(0, int(math.floor(s0))), min(T, int(math.ceil(e0)) + 1))
        d = np.where(r < ca, (ca - r) / da, np.where(r > cb, (r - cb) / db, 0.0))
        env[r] = np.minimum(env[r], _raised(d))
    X *= env[:, None]
    return np.clip(X, 0.0, 1.0), sung


def frame_values(X, frames, lead_ms):
    """the mix on every frame: frame f shows the mouth of (f + SHOWN) / FPS + lead"""
    t = (np.arange(frames) + SHOWN) / FPS + lead_ms / 1000.0
    rows = np.arange(len(X)) * STEP
    return np.stack([np.interp(t, rows, X[:, j], left=X[0, j], right=X[-1, j]) for j in range(5)], axis=1)


def face_rows_of(face, voice_frames, lag=0.0):
    """FACE's vowel mixes on the rows of the voice (straight between keys, as MMD; row k at k * STEP s, frame f shown at
    (f + SHOWN) / FPS)"""
    keys = {}
    for k in face.morphs:
        if k.name in VOWELS:
            keys.setdefault(k.name, {})[k.frame] = float(k.weight)
    t = (np.arange(voice_frames) * STEP - lag) * FPS - SHOWN
    out = np.zeros((voice_frames, 5))
    for j, name in enumerate(VOWELS):
        ks = sorted(keys.get(name, {}).items())
        if ks:
            out[:, j] = np.interp(t, [f for f, _ in ks], [w for _, w in ks])
    return out


def bake_within(values, tolerance):
    """[(frame, weight)] of a per-frame curve: the keys straight lines between them need to stay within tolerance"""
    v = np.round(np.asarray(values, float), 6)
    n = len(v)
    if n <= 2:
        return [(i, float(v[i])) for i in range(n)]
    keep = [0]
    i = 0
    while i < n - 1:
        j = i + 1
        while j + 1 < n:
            k = j + 1
            x = np.arange(i, k + 1)
            if np.abs(v[i] + (v[k] - v[i]) * (x - i) / float(k - i) - v[i:k + 1]).max() > tolerance:
                break
            j = k
        keep.append(j)
        i = j
    return [(int(f), float(v[f])) for f in keep]


def keys_of(values, tolerance, extra_frames=()):
    out = {}
    for j, name in enumerate(VOWELS):
        ks = dict(bake_within(values[:, j], tolerance))
        for f in extra_frames:
            if 0 <= f < len(values):
                ks[f] = float(np.round(values[f, j], 6))
        out[name] = sorted(ks.items())
    return out


def frames_of(face, dance=None):
    """how many frames the output covers: the last key of FACE (and the dance) + 1"""
    last = max([k.frame for k in face.morphs] + [k.frame for k in face.bones] + [0])
    if dance is not None:
        last = max([last] + [k.frame for k in dance.bones] + [k.frame for k in dance.morphs])
    return last + 1


# ---- the report ------------------------------------------------------------------------------

def _load_lip_timing():
    spec = importlib.util.spec_from_file_location("lip_timing", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                            "lip_timing.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stats(values):
    if not values:
        return None
    v = np.asarray(values, float)
    return {"n": int(len(v)), "median": round(float(np.median(v)), 1), "p25": round(float(np.percentile(v, 25)), 1),
            "p75": round(float(np.percentile(v, 75)), 1), "p10": round(float(np.percentile(v, 10)), 1),
            "p90": round(float(np.percentile(v, 90)), 1)}


def face_lead(face, morae):
    """ms by which FACE's vowel onsets come before the aligned vowel onsets of the voice of the same vowel (each aligned
    onset that starts a syllable after a consonant or a pause, with FACE's nearest onset of that vowel within 250 ms)"""
    lt = _load_lip_timing()
    try:
        onsets = lt.onsets(face)
    except ValueError:
        return None
    by_vowel = {}
    for o in onsets:
        by_vowel.setdefault(o.vowel, []).append((o.frame + SHOWN) / FPS)
    out = []
    for m in morae:
        if m["vowel"] not in "aiueo" or m["held"] or not (m["consonant"] or m["word_start"]):
            continue
        ts = np.asarray(by_vowel.get(m["vowel"], []))
        if not len(ts):
            continue
        j = int(np.argmin(np.abs(ts - m["v0"])))
        if abs(ts[j] - m["v0"]) <= 0.25:
            out.append(1000.0 * (m["v0"] - ts[j]))
    return _stats(out)


# ---- the tool --------------------------------------------------------------------------------

def run(face_path, vocal_path, lines_path, out_path, lead_ms=LEAD_MS, dance_path=None, max_keys=None,
        report_path=None, align_path=None, sound=None, use_guide=True):
    """write OUT and return the report; sound: the voice as mono float32 at SR (for tests), else read from vocal_path"""
    face = vmd.load(face_path)
    dance = vmd.load(dance_path) if dance_path else None
    lines = read_lines(lines_path)
    if not lines:
        raise ValueError("no lyric line in %s" % lines_path)
    x = read_sound(vocal_path) if sound is None else np.asarray(sound, np.float32)
    voice = features(x)
    # FACE's mouth on the voice's rows with its own lead taken out (it leads the voice by GUIDE_LAG): the guide of the
    # alignment, and the mouth outside the lines, which then leads by lead_ms as the mouth in the lines does
    face_rows = face_rows_of(face, voice.frames, GUIDE_LAG)
    guide = face_rows if use_guide and face_rows.sum() > 0 else None
    result = align(voice, lines, guide=guide)
    X, sung = mouth_track(voice, result["morae"], face_rows)
    frames = frames_of(face, dance)
    values = frame_values(X, frames, lead_ms)
    extra = sorted({k.frame for k in dance.morphs if k.name in VOWELS}) if dance is not None else []
    tolerance = KEY_TOLERANCE
    keys = keys_of(values, tolerance, extra)
    while max_keys is not None and sum(len(v) for v in keys.values()) > max_keys:
        tolerance *= 1.25
        if tolerance > 0.5:
            raise ValueError("the vowel keys do not fit in %d keys" % max_keys)
        keys = keys_of(values, tolerance, extra)
    others = [k for k in face.morphs if k.name not in VOWELS]
    new = [vmd.MorphKey(name, f, w) for name in VOWELS for f, w in keys[name]]
    out = dataclasses.replace(face, morphs=others + new)
    vmd.dump(out, out_path)
    before = {name: sum(1 for k in face.morphs if k.name == name) for name in VOWELS}
    report = {
        "lines": len(lines), "morae": len(result["morae"]), "model_classes": result["model_classes"],
        "lead_ms": lead_ms, "key_tolerance": round(tolerance, 4), "guide": guide is not None,
        "keys": {"before": before, "after": {n: len(keys[n]) for n in VOWELS},
                 "before_total": sum(before.values()), "after_total": sum(len(keys[n]) for n in VOWELS)},
        "face_lead_ms": face_lead(face, result["morae"]),
        "sung_seconds": round(float(sung.sum() * STEP), 2),
        "checks": {"vowels_squeezed": sum(1 for m in result["morae"] if m["vowel"] in "aiueo" and not m["held"]
                                          and m["v1"] - m["v0"] < 0.04),
                   "breaks": sum(1 for m in result["morae"] if "g0" in m),
                   "consonants_over_150ms": sum(1 for m in result["morae"] if m["v0"] - m["c0"] > 0.15)},
        "line_fit": result["lines"],
    }
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=True, indent=1)
    if align_path:
        with open(align_path, "w", encoding="utf-8") as f:
            json.dump(result["morae"], f, ensure_ascii=False, indent=0)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("face", help="the face motion (.vmd)")
    p.add_argument("vocal", help="the singing voice alone (any file ffmpeg reads)")
    p.add_argument("out", help="the face motion to write (.vmd)")
    p.add_argument("--lines", required=True, help="the lyric lines: start, end (s) and kana, tab-separated")
    p.add_argument("--lead-ms", type=float, default=LEAD_MS, help="how far the mouth leads the voice (default %(default)s)")
    p.add_argument("--dance", help="the dance loaded before FACE: OUT keys the vowels wherever it does")
    p.add_argument("--max-keys", type=int, help="at most this many vowel keys (the tolerance grows to fit)")
    p.add_argument("--no-guide", action="store_true", help="align on the voice alone (not helped by FACE's vowels)")
    p.add_argument("--report", help="write the report (JSON)")
    p.add_argument("--align-out", help="write every mora's times (JSON)")
    args = p.parse_args(argv)
    if not 0.0 <= args.lead_ms <= 200.0:
        print("lip_sync: --lead-ms must be within 0..200", file=sys.stderr)
        return 2
    for path in (args.face, args.vocal, args.lines) + ((args.dance,) if args.dance else ()):
        if not os.path.isfile(path):
            print("lip_sync: no such file: %s" % path, file=sys.stderr)
            return 2
    if os.path.abspath(args.out) in {os.path.abspath(args.face), os.path.abspath(args.vocal)}:
        print("lip_sync: OUT must not be an input", file=sys.stderr)
        return 2
    try:
        report = run(args.face, args.vocal, args.lines, args.out, args.lead_ms, args.dance, args.max_keys, args.report,
                     args.align_out, use_guide=not args.no_guide)
    except (ValueError, subprocess.CalledProcessError) as e:
        print("lip_sync: %s" % e, file=sys.stderr)
        return 1
    short = {k: report[k] for k in ("lines", "morae", "lead_ms", "key_tolerance", "face_lead_ms", "sung_seconds", "checks")}
    short["keys"] = {"before_total": report["keys"]["before_total"], "after_total": report["keys"]["after_total"]}
    print(json.dumps(short, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
