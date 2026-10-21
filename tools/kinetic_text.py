"""Kinetic typography for the MV's lyrics, after @PizaCG's videos: the lyrics cut into short pieces at the syllables of
the voice, each piece coming in, moving on and going out in about a second, as subtitles in front of the dancer and as
large words behind her; the title, a tag and the credits.  Nothing happens in MMD.

    python tools/kinetic_text.py words OUT.json --cues CUES.json --lines LINES.tsv --align ALIGN.json
                                      [--structure STRUCTURE.json] [--credits CREDITS.json] [--marks SONG_STRUCTURE.json]
    python tools/kinetic_text.py sheet WORDS.json OUT.json [--look LOOK.json] [--fps N]
    python tools/kinetic_text.py frames WORDS.json WORK [--look LOOK.json] [--size WxH] [--fps N] [--from S] [--to S]
    python tools/kinetic_text.py preview WORDS.json OUT.png --at S [--over PICTURE] [--look LOOK.json] [--size WxH]
    python tools/kinetic_text.py over VIDEO WORDS.json OUT.mp4 [--look LOOK.json] [--from S] [--to S] [--fps N]

Why (kinetic, 2026-10-21): the request is to take the kinetic typography of the YouTube channel @PizaCG as the reference
for the lyrics.  typoref measured nine of its videos with tools/typo_analyze.py (the median over the videos of each
video's median, and its quartiles): a line is a piece of 5 [5, 6] characters, seen 1.07 [1.00, 1.30] s and never standing
still (0.00 [0.00, 0.03] s whole and still), it takes 0.43 s to come (a fade with a move, a zoom, a blur or the
characters one after another) and 0.40 s to go (a move in 6 of 10, a zoom in 2), it starts with the voice and is whole
about 0.5 s after the voice's strong onset; the characters are 4 to 6 % of the picture tall, white (L* 77) with a soft
glow, in the middle; a third of the lines are large (6 % or more) and lie behind the dancer.  Ours (v7) showed a line of
11 characters for 3.2 s, standing still for 2.9 s.

What is done:

1. The words file (`words`; it holds the lyrics, so it stays with the song's files and is not distributed): every line
   of the lyrics with its text, its reading in kana and its syllables (morae) with their times, from the MV's cue file
   (tools/mv_text.py: the text of its lyric cues, in order), the lines' readings (LINES.tsv: start, end, kana) and the
   alignment of tools/lip_sync.py (--align-out: per mora the consonant's start c0, the vowel's start v0 and end v1).
   The structure of the song (sections: verse, chorus, bridge, outro, interlude, intro, end; the title word sung in the
   hooks; the words drawn in an accent colour), the title, the tag and the credit cards come from STRUCTURE.json and
   CREDITS.json; the marks (marks_of) from the MV's shared song structure, which the motion graphics flash and punch on.
   The singer is named in one place, STRUCTURE.json's vocal {latin, name}: the title, the tag and the cards write
   {vocal.latin} and {vocal.name} where it goes (a change of the voice is one change; vocal_warnings says when the two
   forms name two singers).
2. Reading (align_reading, line_chars): each character of a line is matched to its part of the reading: a kana reads as
   the same kana (hiragana and katakana alike), a run of kanji as the kana between the kana round it (one word, never
   cut), a space or a mark as nothing unless the reading has it there; so every character gets the times of its morae.
3. Pieces (cut_line): the line cut into pieces each sung about `sung` s (kinetic2: the references' life; with sung 0, of
   about `chars` characters), between `chars_min` and `chars_max` characters, where a cut costs least: at a space, then
   before a word of kanji or katakana after hiragana; never through a run of kanji or of katakana, and never before a
   small kana, the long mark, a closing mark or ん, nor after an opening one.
4. The plan (plan_words): each piece of a sung line is a subtitle in front of the dancer, coming `lead` s before the
   consonant of its first syllable and on the screen while it is sung and `hang` s after, `life` s at least and at most;
   the pieces of a line take the rows of `sub_rows` in turn (from the first no subtitle is on as the line comes), a share
   of the verses' lines stand in a column at a side.  In
   a chorus, the bridge and the outro `big_per_line` pieces of a line are also large words behind the dancer (tilted,
   in two rows, or hollow with a neon edge).  The title word of the hooks comes one character a syllable, large, behind
   her; the interludes have the title in hollow letters cut by the picture's edge drifting across behind her.  Each
   piece comes and goes in one of the ways of ENTERS and EXITS, as often as the look's mixes say (the references'
   shares), and drifts or grows all the while it is on (`drift`, `push`).  With the words file's marks the pieces come
   and go on the song structure's frames near their times (_on_marks), the title word comes on its frame a character a
   syllable, the interludes' title and the end card on a section's first frame.
5. Drawing (draw_piece): Pillow sets the glyphs (Noto Sans JP, Noto Serif JP, Shippori Mincho: all under the SIL Open
   Font License; a missing Shippori Mincho is replaced by Noto Serif JP and the warnings say so); numpy and OpenCV lay
   them out per frame in premultiplied colour (a move, a zoom and the tilt in one affine warp, then the blur, the glow,
   the outline or the neon edge, the drop shadow, the glitch's parted colours and torn rows).
6. The pictures (render_sequences): two sequences of whole frames, RGBA PNG with straight alpha, numbered from the first
   frame of the span: the "back" layer (the large words, the hooks, the interludes' title, the title unless its layer is
   front) and the "front" one (the subtitles, the tag, the credits).  tools/mv_look.py (look text2.on 1) lays the back layer between the stage
   and the dancer and the front one over all; `over` lays both over a video or a picture (to measure the text with
   tools/typo_analyze.py).

The values are the look's text2 section (tools/mv_look.py DEFAULT_LOOK, --look); fonts are looked for in the folders of
MMD_CLI_FONTS (separated by the path separator), then in Windows' fonts folders.
"""
import argparse
import concurrent.futures
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
_LAZY = {}


def _tool(name):
    """a sibling tool (tools/ is not a package), loaded once"""
    if name not in _LAZY:
        spec = importlib.util.spec_from_file_location("_kinetic_" + name, os.path.join(HERE, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LAZY[name] = module
    return _LAZY[name]


def _cv2():
    if "cv2" not in _LAZY:
        import cv2
        _LAZY["cv2"] = cv2
    return _LAZY["cv2"]


def _ascii(text):
    """for a message: the terminal is cp932, a character outside ASCII is written as its escape"""
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _warn(warnings, text):
    text = _ascii(text)
    if text not in warnings:
        warnings.append(text)


def _unit(*keys):
    """a fixed number in [0, 1) for these keys (the same on every machine and Python)"""
    digest = hashlib.sha256(repr(keys).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64


# ---- the settings (the look's text2 section) ----------------------------------------------------------------------------

def default_settings():
    """the text2 section of tools/mv_look.py's DEFAULT_LOOK (a copy)"""
    return json.loads(json.dumps(_tool("mv_look").DEFAULT_LOOK["text2"]))


def settings_of(look_path=None):
    """the text2 section of a look (tools/mv_look.py merges and checks it), or the default"""
    if not look_path:
        return default_settings()
    return _tool("mv_look").load_look(look_path)["text2"]


ENTERS = ("rise", "slide", "drop", "zoom", "zoomrise", "zoomblur", "blurin", "fadein", "type", "glitch", "cut", "pop")
EXITS = ("lift", "sink", "slideout", "flyout", "zoomout", "shrink", "fadeout", "untype", "glitchout", "cutout", "popout")
# what each way does: where it comes from or goes to (heights of its characters: x right, y down), the size it comes
# from or goes to, the blur (px of a 720 line picture) it comes from or goes to, and whether it fades, its characters
# come one after another, it glitches, it overshoots, or it is there (or gone) at once.  Every piece drifts to the right
# all the while (_drift): a move across goes to the right too and a zoom in grows, so that no move cancels the drift
# and the piece never stands still (tools/typo_analyze.py: less than 0.03 heights and 0.6 % of size a frame)
MOVES = {
    "rise": {"move": (0.0, 1.8), "fade": 1},
    "slide": {"move": (-1.8, 0.0), "blur": 9.0},
    "drop": {"move": (0.0, -1.8), "overshoot": 1},
    "zoom": {"scale": 0.6, "fade": 1},
    "zoomrise": {"scale": 0.7, "move": (0.0, 1.2)},
    "zoomblur": {"scale": 0.75, "blur": 9.0},
    "blurin": {"blur": 10.0, "fade": 1},
    "fadein": {"fade": 1},
    "type": {"move": (0.0, 0.6), "fade": 1, "stagger": 1},
    "glitch": {"move": (-0.35, 0.0), "glitch": 1},
    "cut": {"cut": 1},
    "pop": {"pop": 1},
    "lift": {"move": (0.0, -1.8), "fade": 1},
    "sink": {"move": (0.0, 1.8), "fade": 1},
    "slideout": {"move": (1.8, 0.0), "blur": 9.0},
    "flyout": {"move": (0.0, -2.5)},
    "zoomout": {"scale": 1.35, "fade": 1},
    "shrink": {"scale": 0.7, "blur": 8.0},
    "fadeout": {"fade": 1},
    "untype": {"fade": 1, "stagger": 1},
    "glitchout": {"move": (0.3, 0.0), "glitch": 1},
    "cutout": {"cut": 1},
    "popout": {"pop": 1},
}
POP_S = 0.067                     # s a pop takes (two frames: too short to read as a fade; three were read as one)
STILL_AT_CUT = 0.25               # s a piece stands still after a cut in and before a cut out (a cut is read as one only when
                                  # the text stands still next to it: drifting, the tool reads it as another way)
SONG_FPS = 30                     # the frames of the song a glitch is counted in (glitch_frames)
GLITCH_SPLIT = (6.0, 3.0, 5.0)    # px of a 720 line picture red and blue part on the glitch's frames, in turn
GLITCH_ROWS = 3                   # bands of rows torn sideways on a glitch's frame
GLITCH_TEAR = 12.0                # px of a 720 line picture a torn band moves at most
STAGGER_SPAN = 0.6                # of the way to come: each character's own, when they come one after another
HOOK_COME = 0.25                  # s a character of the title word takes to come (at its syllable)
HOOK_ZOOM = 1.6                   # ... from this size
FADE_TITLE = (0.8, 0.6)           # s the title takes to come and to go
FADE_TAG = 1.0                    # s the tag takes to come and to go
FADE_INTERLUDE = 0.8              # s the interludes' title takes to come and to go


def check_settings(s):
    """the values of the text2 section this tool can draw (tools/mv_look.py has checked their kinds); a wrong one is an
    error naming it"""
    def need(ok, text):
        if not ok:
            raise ValueError("text2." + text)

    def whole(v):
        return float(v) == int(v)
    need(all(whole(s[k]) for k in ("chars", "chars_min", "chars_max")) and 1 <= s["chars_min"] <= s["chars"] <= s["chars_max"],
         "chars_min, chars and chars_max are whole numbers, 1 <= chars_min <= chars <= chars_max: not %r, %r, %r"
         % (s["chars_min"], s["chars"], s["chars_max"]))
    for k in ("sung", "lead", "hang", "drift", "stagger", "push", "outline_px", "glow", "glow_radius", "neon_glow", "shadow",
              "credit_fade"):
        need(math.isfinite(s[k]) and s[k] >= 0, "%s is from 0, not %r" % (k, s[k]))
    for k in ("enter", "exit"):
        need(0 <= s[k] <= 2.0, "%s is 0 to 2 seconds, not %r" % (k, s[k]))
    need(0 < s["life"][0] <= s["life"][1], "life is [shortest, longest] seconds a piece is on, not %r" % (s["life"],))
    for k in ("sub_size", "big_size", "edge_size", "edge_word", "hook_size", "title_size", "tag_size", "credit_size", "role_size"):
        need(0 < s[k] <= 1, "%s is a share of the picture's height, above 0 up to 1: not %r" % (k, s[k]))
    for k in ("column_share", "mincho_share", "bracket_share", "outline_share", "shadow_share", "big_alpha", "edge_alpha",
              "tag_alpha", "sub_x", "column_y", "hook_y"):
        need(0 <= s[k] <= 1, "%s is 0 to 1, not %r" % (k, s[k]))
    for k in ("sub_rows", "column_x", "big_x", "big_y"):
        need(len(s[k]) >= 1 and all(0 <= v <= 1 for v in s[k]), "%s are shares of the picture, 0 to 1: not %r" % (k, s[k]))
    need(-90 <= s["tilt"] <= 90, "tilt is degrees, -90 to 90: not %r" % (s["tilt"],))
    for k in ("weight", "weight_mincho"):
        need(100 <= s[k] <= 900, "%s is a font weight, 100 to 900: not %r" % (k, s[k]))
    need(0 <= s["big_per_line"] <= 4, "big_per_line is 0 to 4 (a fraction: some lines one more), not %r" % (s["big_per_line"],))
    need(whole(s["glitch_frames"]) and 1 <= s["glitch_frames"] <= 15, "glitch_frames is 1 to 15, not %r" % (s["glitch_frames"],))
    need(whole(s["seed"]), "seed is a whole number, not %r" % (s["seed"],))
    need(s["at_vowel"] in (0, 1), "at_vowel is 0 (a piece comes at the consonant) or 1 (at the vowel), not %r" % (s["at_vowel"],))
    for k in ("fill", "blue", "red", "outline", "neon"):
        need(len(s[k]) == 3 and all(0 <= c <= 255 for c in s[k]), "%s is r, g, b of 255, not %r" % (k, s[k]))
    need(len(s["shadow_px"]) == 2, "shadow_px is [right, down], not %r" % (s["shadow_px"],))
    for k, names in (("enter_mix", ENTERS), ("exit_mix", EXITS), ("big_enter_mix", ENTERS), ("big_exit_mix", EXITS)):
        need(len(s[k]) == len(names) and all(v >= 0 for v in s[k]) and sum(s[k]) > 0,
             "%s is %d weights from 0 (%s), not all 0: not %r" % (k, len(names), ", ".join(names), s[k]))


# ---- characters and their reading ---------------------------------------------------------------------------------------

SMALL_KANA = frozenset("\u3041\u3043\u3045\u3047\u3049\u3063\u3083\u3085\u3087\u308e"
                       "\u30a1\u30a3\u30a5\u30a7\u30a9\u30c3\u30e3\u30e5\u30e7\u30ee\u30f5\u30f6")
LONG_MARK = "\u30fc"                                                      # ー
# ん and ン: no Japanese word begins with them, so a piece that did would part a word (kineticrev 2026-10-21: a line of the
# MV was cut before ん); they stay with the kana before them, as the small kana do
NO_START = frozenset("\u3093\u30f3")                                       # ん ン
OPENING = frozenset("\u300c\u300e\uff08\u3008\u300a\u3010\u3014(")         # 「『（〈《【〔(
CLOSING = frozenset("\u300d\u300f\uff09\u3009\u300b\u3011\u3015)\u3001\u3002\uff0c\uff0e\uff01\uff1f!?\u2026\u2025\u30fb")
MARKS = OPENING | CLOSING | frozenset("\u301c\uff5e\"'")


def kind_of(ch):
    """space, mark, hira, kata (the long mark too), kanji or other"""
    if ch.isspace():
        return "space"
    if ch in MARKS:
        return "mark"
    o = ord(ch)
    if 0x3041 <= o <= 0x309F:
        return "hira"
    if 0x30A1 <= o <= 0x30FF:
        return "kata"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF or ch in "\u3005\u3006\u3007":
        return "kanji"
    return "other"


def sound(ch):
    """a kana as hiragana: the katakana and the hiragana of one sound are the same"""
    o = ord(ch)
    return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else ch


def _passable(ch):
    return ch.isspace() or ch in MARKS


def _is_kana(ch):
    return kind_of(ch) in ("hira", "kata")


READ_ACROSS = 10.0                # the cost of a space of the reading inside a run of kanji
READ_SPREAD = 0.1                 # ... of a run's kana a kanji away from 2, squared


@dataclasses.dataclass(frozen=True)
class Ruby:
    start: int                    # the slice of the reading the character is read as
    end: int
    group: int                    # its run of kanji (the run's first character): a word the pieces never cut


def align_reading(text, reading):
    """for every character of `text`, the slice of `reading` it is read as: a kana as the same kana (hiragana and
    katakana alike), a run of kanji (or of other letters) as kana between the kana round it (1 to 4 a character, one
    more for the run), a space or a mark as the same character of the reading or as nothing; spaces and marks of the
    reading that the text lacks are passed over.  ValueError when the text cannot be read so"""
    n, m = len(text), len(reading)
    kinds = [kind_of(c) for c in text]
    runs, i = {}, 0
    while i < n:
        if kinds[i] in ("kanji", "other"):
            e = i
            while e < n and kinds[e] == kinds[i]:
                e += 1
            runs[i] = e
            i = e
        else:
            i += 1
    memo = {}

    def better(a, b):
        return b if a is None or (b is not None and b[0] < a[0]) else a

    def solve(i, j):
        """the least costly reading of text[i:] from reading[j:]: (cost, ((start, end), ...)) or None.  A space of the
        reading inside a run of kanji costs READ_ACROSS (two words written together), a run's kana a kanji away from two
        cost a little (READ_SPREAD)"""
        if (i, j) in memo:
            return memo[(i, j)]
        out = None
        if i == n:
            out = (0.0, ()) if all(_passable(reading[k]) for k in range(j, m)) else None
        elif kinds[i] in ("kanji", "other"):
            e, s = runs[i], j
            while True:
                kana = across = 0
                for length in range(1, m - s + 1):
                    last = reading[s + length - 1]
                    if not _is_kana(last):
                        if _passable(last) and kana:     # a space of the reading inside the run (two words written as one)
                            across += 1
                            continue
                        break
                    kana += 1
                    if kana > 4 * (e - i) + 1:
                        break
                    rest = solve(e, s + length)
                    if rest is not None:
                        cost = rest[0] + READ_ACROSS * across + READ_SPREAD * (kana / float(e - i) - 2.0) ** 2
                        out = better(out, (cost, ((s, s + length),) * (e - i) + rest[1]))
                if s >= m or not _passable(reading[s]):
                    break
                s += 1
        elif kinds[i] in ("space", "mark"):
            s = j
            while s < m:
                if reading[s] == text[i] or (text[i].isspace() and reading[s].isspace()):
                    rest = solve(i + 1, s + 1)
                    if rest is not None:
                        out = better(out, (rest[0], ((s, s + 1),) + rest[1]))
                if not _passable(reading[s]):
                    break
                s += 1
            rest = solve(i + 1, j)
            if rest is not None:
                out = better(out, (rest[0], ((j, j),) + rest[1]))
        else:
            s = j
            while s < m and sound(reading[s]) != sound(text[i]) and _passable(reading[s]):
                s += 1
            if s < m and sound(reading[s]) == sound(text[i]):
                rest = solve(i + 1, s + 1)
                if rest is not None:
                    out = (rest[0], ((s, s + 1),) + rest[1])
        memo[(i, j)] = out
        return out

    best = solve(0, 0)
    if best is None:
        raise ValueError("the line %s cannot be read as %s" % (_ascii(text), _ascii(reading)))
    found = best[1]
    groups, k = [], 0
    while k < n:
        e = runs.get(k, k + 1)
        groups += [k] * (e - k)
        k = e
    return [Ruby(a, b, g) for (a, b), g in zip(found, groups)]


def reading_morae(reading, morae):
    """for every character of the reading, the mora (an index into `morae`, their kana: "\u304d\u3087" is one) it
    belongs to, None for a space or a mark; ValueError when the morae do not spell the reading"""
    out, j = [None] * len(reading), 0
    for k, kana in enumerate(morae):
        for ch in kana:
            while j < len(reading) and _passable(reading[j]) and sound(reading[j]) != sound(ch):
                j += 1
            if j >= len(reading) or sound(reading[j]) != sound(ch):
                raise ValueError("the morae %s do not spell the reading %s (mora %d)" % (_ascii("".join(morae)), _ascii(reading), k))
            out[j] = k
            j += 1
    if not all(_passable(c) for c in reading[j:]):
        raise ValueError("the morae %s spell only a part of the reading %s" % (_ascii("".join(morae)), _ascii(reading)))
    return out


@dataclasses.dataclass
class Char:
    ch: str
    kind: str
    group: int                    # its word (a run of kanji: the run's first character; its own index otherwise)
    t0: float = 0.0               # s: the consonant of its first syllable starts
    t1: float = 0.0               # s: the vowel of its last syllable ends
    first: int = -1               # its first and last mora (-1: read as nothing, a space or a mark)
    last: int = -1
    v0: float = 0.0               # s: the vowel of its first syllable starts (where the voice's onset is strongest)


def _mora(row):
    """a mora of the alignment: a row of tools/lip_sync.py's --align-out ({kana, c0, v0, v1, ...}) or of a words file
    ([kana, c0, v0, v1])"""
    if isinstance(row, dict):
        return {"kana": row["kana"], "c0": float(row["c0"]), "v0": float(row["v0"]), "v1": float(row["v1"])}
    return {"kana": row[0], "c0": float(row[1]), "v0": float(row[2]), "v1": float(row[3])}


def line_chars(text, reading, morae):
    """the characters of a line with the times of their morae (a character read as nothing takes the time of the next
    one that is read, at the end of the line of the one before)"""
    rows = [_mora(m) for m in morae]
    ruby = align_reading(text, reading)
    index = reading_morae(reading, [r["kana"] for r in rows])
    chars = []
    for ch, r in zip(text, ruby):
        c = Char(ch, kind_of(ch), r.group)
        ks = [index[j] for j in range(r.start, r.end) if index[j] is not None]
        if ks:
            c.first, c.last = min(ks), max(ks)
            c.t0, c.t1, c.v0 = rows[c.first]["c0"], rows[c.last]["v1"], rows[c.first]["v0"]
        chars.append(c)
    later = None
    for c in reversed(chars):
        if c.first >= 0:
            later = c
        elif later is not None:
            c.t0 = c.t1 = c.v0 = later.t0
    earlier = None
    for c in chars:
        if c.first >= 0:
            earlier = c
        elif earlier is not None and c.t0 == 0.0 and c.t1 == 0.0:
            c.t0 = c.t1 = c.v0 = earlier.t1
    return chars


# ---- the pieces of a line -----------------------------------------------------------------------------------------------

# what a cut between two words costs, by the kinds of the characters on either side (a cut after a space costs 0): a
# word of kanji or katakana after hiragana starts a phrase; hiragana after a particle may; hiragana after hiragana or
# after kanji is mostly inside a word (書|く, 走っ|ている: the endings of a verb)
CUT_COST = {("hira", "kanji"): 1.0, ("hira", "kata"): 1.0, ("hira", "other"): 1.0, ("kata", "kanji"): 2.0,
            ("kanji", "kata"): 2.0, ("other", "kanji"): 2.0, ("kanji", "other"): 2.0, ("kata", "hira"): 2.5,
            ("hira", "hira"): 6.0, ("kanji", "hira"): 6.0}
CUT_DEFAULT = 3.0
PARTICLES = frozenset("はがをにへとでものや")   # は が を に へ と で も の や
AFTER_PARTICLE = 2.0              # a cut between a particle and hiragana
LENGTH_COST = 0.5                 # a piece's length off chars costs this times its square
SHORT_COST = 50.0                 # a piece shorter than chars_min (when the line is longer)
LONG_COST = 1000.0                # a character over chars_max (only when one word is longer)
TIME_COST = 4.0                   # a piece sung longer than the longest life + TIME_SLACK costs this a second squared
TIME_SLACK = 0.25                 # (a slow line is cut more: each piece comes when it is sung)
# cutting by the time sung (settings["sung"] above 0; kinetic2 2026-10-21): a piece's sung time off `sung` costs LENGTH_COST
# times its square in units of SUNG_UNIT s, a mora of the song (140 bpm, two morae a beat): one unit costs as a character
# did in the cutting by characters
SUNG_UNIT = 0.2
# ... and a cut inside a word (hiragana after hiragana that is no particle, or after kanji: the ending of a verb or an
# adjective) costs INSIDE_WORD_COST, not CUT_COST's 6: a piece sung up to about 2 s keeps its words whole (the time's cost of
# a piece sung 2.0 s is 20).  With 6, words8 of 2026-10-21 had 26 of 137 cuts inside a word, as before a negation
INSIDE_WORD = frozenset({("hira", "hira"), ("kanji", "hira")})
INSIDE_WORD_COST = 30.0
# ... and a piece over a space (where the lyrics part their phrases) holds whole phrases: with the time alone, words8 of
# 2026-10-21 had 7 pieces over a space begun inside a phrase (as the last particle of a sentence put in front of the next
# phrase, which it then reads as) and 6 ended inside one


@dataclasses.dataclass
class _Atom:
    start: int
    end: int
    head: str                     # the kind of its first and last characters that are not marks
    tail: str
    size: int                     # its characters (marks count, spaces do not)
    space_before: bool = False


def _atoms(chars, longest):
    """the line in words a cut never goes through: a run of kanji, a run of katakana (no longer than `longest`), every
    other character alone; a small kana, the long mark and a closing mark join the word before, an opening mark the one
    after; spaces only part them"""
    raw, i, n = [], 0, len(chars)
    while i < n:
        c = chars[i]
        if c.kind == "space":
            raw.append(None)
            i += 1
            continue
        e = i + 1
        if c.kind in ("kanji", "other"):
            while e < n and chars[e].group == c.group:
                e += 1
        elif c.kind == "kata":
            while e < n and chars[e].kind == "kata" and e - i < longest:
                e += 1
        raw.append([i, e])
        i = e
    glued, space = [], False
    for a in raw:
        if a is None:
            space = True
            continue
        first = chars[a[0]].ch
        if glued and not space and (first in SMALL_KANA or first in NO_START or first == LONG_MARK or first in CLOSING):
            glued[-1][1] = a[1]
        else:
            glued.append([a[0], a[1], space])
        space = False
    out, pending = [], None
    for a0, a1, sp in glued:
        if pending is not None:
            a0, sp = pending[0], pending[2]
            pending = None
        if all(chars[k].ch in OPENING for k in range(a0, a1)):
            pending = [a0, a1, sp]
            continue
        body = [chars[k].kind for k in range(a0, a1) if chars[k].kind not in ("mark", "space")] or ["other"]
        out.append(_Atom(a0, a1, body[0], body[-1], sum(1 for k in range(a0, a1) if chars[k].kind != "space"), sp))
    if pending is not None:                       # an opening mark at the end of the line: with the word before
        if out:
            out[-1].end = pending[1]
            out[-1].size += pending[1] - pending[0]
        else:
            out.append(_Atom(pending[0], pending[1], "other", "other", pending[1] - pending[0], pending[2]))
    return out


def cut_line(chars, settings):
    """the pieces of a line: [(first, end)] indices into `chars` (no piece begins or ends with a space), each sung about
    settings["sung"] s (or, with sung 0, of about settings["chars"] characters), where the cuts cost least (CUT_COST; a
    piece's sung time or length off the target costs its square).  Cut by the time, a piece over a space holds whole
    phrases"""
    target, least, most = int(settings["chars"]), int(settings["chars_min"]), int(settings["chars_max"])
    by_time = float(settings.get("sung", 0.0))
    longest = float(settings["life"][1]) + TIME_SLACK
    atoms = _atoms(chars, most)
    if not atoms:
        return []
    total = sum(a.size for a in atoms)
    n = len(atoms)
    timed = [[c for c in chars[x.start:x.end] if c.first >= 0] for x in atoms]
    best, back = [0.0] + [math.inf] * n, [None] * (n + 1)
    for b in range(1, n + 1):
        size = 0
        t0, t1 = math.inf, -math.inf
        spaced = False                                  # the piece atoms[a:b] holds a space
        for a in range(b - 1, -1, -1):
            size += atoms[a].size
            spaced = spaced or (a < b - 1 and atoms[a + 1].space_before)
            if timed[a]:
                t0 = min(t0, min(c.t0 for c in timed[a]))
                t1 = max(t1, max(c.t1 for c in timed[a]))
            sung = t1 - t0 if t1 > t0 else 0.0
            if a == 0 or atoms[a].space_before:
                cut = 0.0
            elif atoms[a - 1].tail == "hira" and atoms[a].head == "hira" and chars[atoms[a - 1].end - 1].ch in PARTICLES:
                cut = AFTER_PARTICLE
            else:
                cut = CUT_COST.get((atoms[a - 1].tail, atoms[a].head), CUT_DEFAULT)
                if by_time > 0 and (atoms[a - 1].tail, atoms[a].head) in INSIDE_WORD:
                    cut = INSIDE_WORD_COST
            if by_time > 0:
                cost = LENGTH_COST * ((sung - by_time) / SUNG_UNIT) ** 2 + cut
            else:
                cost = LENGTH_COST * (size - target) ** 2 + cut + TIME_COST * max(0.0, sung - longest) ** 2
            if size > most:
                cost += LONG_COST * (size - most)
            if size < least and size < total:
                cost += SHORT_COST
            if by_time > 0 and spaced and not ((a == 0 or atoms[a].space_before) and (b == n or atoms[b].space_before)):
                cost = math.inf                         # part of a phrase over a space
            if best[a] + cost < best[b]:
                best[b], back[b] = best[a] + cost, a
            if size > 3 * most:
                break
    cuts, b = [], n
    while b > 0:
        a = back[b]
        cuts.append((atoms[a].start, atoms[b - 1].end))
        b = a
    return list(reversed(cuts))


# ---- the words file -----------------------------------------------------------------------------------------------------

WORDS_KIND = "kinetic_words"
SECTION_KINDS = ("intro", "verse", "chorus", "bridge", "outro", "interlude", "end")
BIG_SECTIONS = ("chorus", "bridge", "outro")      # the sections whose lines also have large words
EDGE_X = (0.03, 0.97)             # where the hollow large words stand: cut by the left or the right edge
BIG_VARIANTS = ("tilt", "hollow", "tilt", "stack")   # the large words in turn: tilted, hollow cut by an edge (upright),
                                  # tilted, two rows of Mincho (each row is read as a line of its own, of a few characters)
BIG_ECHO = 0.15                   # s before its subtitle goes, a large word comes: it echoes the words behind the dancer (made
                                  # when the subtitles went before their words were sung: the echo came while they were
                                  # still sung, and the text was on more of the sung time, the references 0.56.  With the
                                  # subtitles on until sung, kinetic2, it comes after they are sung)
BIG_LONGER = 0.35                 # s a large word stays on longer than the subtitle it echoes
CUE_MEETS = 1.5                   # s: a lyric cue and the line of the alignment it is meet within this
# the marks of the MV's shared song structure (the words file's "marks", from the motion graphics' table: a white flash and
# a punch start on a section's first frame, on a chorus half's and on the title word's; the picture changes on a section's
# cut): the text comes and goes on them when it would come or go near one
MARK_EARLIER = 0.25               # s: a piece comes up to this much sooner, to come on a mark
MARK_LATER = 0.1                  # s: ... or up to this much later
END_SOONER = 0.15                 # s: a piece goes up to this much sooner, to be gone on a mark or a cut
END_LATER = 0.1                   # s: ... or up to this much later
HOOK_GOES = (0.2, 1.3)            # s after the title word's last syllable: on a section's mark in this it starts to go
HOOK_EXIT = 0.3                   # s the title word takes to go (a glitch)
INTERLUDE_COMES = (-0.5, 3.0)     # s about an interlude's start: its title comes on the first section's mark in this
INTERLUDE_GOES = (-1.0, 0.5)      # s about the time its title would be gone: it is gone on a section's mark in this
CARD_MARK = 0.5                   # s: a credit card that would come this near a section's mark comes on it
# the singer, named in one place (kineticrev, 2026-10-21: the title said one singer and the credits another, in three texts
# of two files): the words file's vocal {latin, name}, the singer as the title and the tag write it (Latin letters) and as
# the credits do; their texts write {vocal.latin} and {vocal.name} where it goes
VOCAL_FIELDS = ("latin", "name")
VOCAL_MARK = "{vocal."
# the singers whose two forms are known (a vocal whose latin is one of them and whose name is another is warned of)
SINGERS = {"HATSUNE MIKU": "初音ミク", "KAGAMINE RIN": "鏡音リン",      # 初音ミク 鏡音リン
           "KAGAMINE LEN": "鏡音レン", "MEGURINE LUKA": "巡音ルカ"}     # 鏡音レン 巡音ルカ


def parse_lines(text):
    """the rows of LINES.tsv (start, end and the line in kana, tab-separated; # starts a comment)"""
    rows = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            raise ValueError("a line of LINES.tsv is start, end and the line in kana, tab-separated: %s" % _ascii(raw))
        rows.append((float(parts[0]), float(parts[1]), parts[2].strip()))
    return rows


def marks_of(structure):
    """the marks of the MV's shared song structure (version 2 or later, made by the motion graphics: frames) in seconds:
    sections (their first frames: the white flash and the punch start there), starts (those, the chorus halves' and the
    title words'), cuts (the frames the picture changes on) and hooks (the title word's frame and its syllables on frames)"""
    if not isinstance(structure, dict) or int(structure.get("version", 1)) < 2:
        raise ValueError("the song structure needs version 2 or later (the frames of the sections and the title words)")
    fps = float(structure.get("fps", 30))
    sections = sorted(int(s["frame"]) / fps for s in structure.get("sections", []))
    halves = [int(h["frame"]) / fps for h in structure.get("chorus_halves", [])]
    hooks = []
    for h in structure.get("hooks", []):
        at = int(h["frame"]) / fps
        hooks.append({"at": at, "syllables": [at] + [round(float(t) * fps) / fps for t in h.get("syllables", [])[1:]]})
    cuts = sorted(int(s["change_frame"]) / fps for s in structure.get("sections", []) if "change_frame" in s)
    return {"sections": sections, "starts": sorted(set(sections + halves + [h["at"] for h in hooks])), "cuts": cuts,
            "hooks": hooks}


STRUCTURE_KEYS = ("sections", "hook", "accents", "title", "tag", "interlude", "end", "vocal")


def build_words(cues, lines_text, align, structure=None, credits=None, marks=None):
    """the words file (a dict) from the MV's cue file (its lyric cues give the lines' text, in order of their start),
    LINES.tsv's text (the readings), the alignment (tools/lip_sync.py --align-out: rows with line, kana, c0, v0, v1), the
    structure ({sections, hook, accents, title, tag, interlude, end, vocal}), the credits ({cards}) and the marks
    (marks_of)"""
    readings = parse_lines(lines_text)
    lyric = sorted([c for c in cues.get("cues", []) if isinstance(c, dict) and c.get("style") == "lyric" and "text" in c],
                   key=lambda c: float(c["start"]))
    by_line = {}
    for row in align:
        by_line.setdefault(int(row["line"]), []).append(row)
    lines = []
    for k, (_, _, reading) in enumerate(readings):
        morae = by_line.get(k)
        if not morae:
            raise ValueError("the alignment has no morae for line %d (%s)" % (k, _ascii(reading)))
        text = None
        if k < len(lyric):
            cue = lyric[k]
            if abs(float(cue["start"]) - float(morae[0]["c0"])) > CUE_MEETS:
                raise ValueError("the lyric cue %s (%.2f s) and line %d of the alignment (%.2f s) are more than %.1f s apart: "
                                 "they are not the same line" % (cue.get("id"), float(cue["start"]), k, float(morae[0]["c0"]),
                                                                 CUE_MEETS))
            text = cue["text"]
            line_chars(text, reading, morae)                     # it reads, or this says where it does not
        else:
            reading_morae(reading, [m["kana"] for m in morae])
        lines.append({"text": text, "reading": reading,
                      "morae": [[m["kana"], round(float(m["c0"]), 3), round(float(m["v0"]), 3), round(float(m["v1"]), 3)]
                                for m in morae]})
    words = {"kind": WORDS_KIND, "version": 1, "lines": lines}
    for key, value in (structure or {}).items():
        if key not in STRUCTURE_KEYS:
            raise ValueError("the structure has no setting %r (it has: %s)" % (key, ", ".join(STRUCTURE_KEYS)))
        words[key] = value
    if credits:
        words["credits"] = credits["cards"] if isinstance(credits, dict) else credits
    if marks:
        words["marks"] = marks
    check_words(words)
    return words


def check_words(words):
    if not isinstance(words, dict) or words.get("kind") != WORDS_KIND:
        raise ValueError("not a words file of tools/kinetic_text.py (its kind is %r)" % (words.get("kind") if isinstance(words, dict) else None,))
    for s in words.get("sections", []):
        if s.get("kind") not in SECTION_KINDS or not float(s["end"]) > float(s["start"]):
            raise ValueError("a section is {kind (%s), start, end after start}: not %r" % (", ".join(SECTION_KINDS), s))
    for card in words.get("credits", []):
        if not float(card["end"]) > float(card["start"]) or not card.get("rows"):
            raise ValueError("a credit card is {start, end after start, rows}: not %s" % _ascii(card))
    if words.get("title") and words["title"].get("layer", "back") not in LAYERS:
        raise ValueError("the title's layer is back (behind the dancer, the default) or front, not %r" % (words["title"]["layer"],))
    marks = words.get("marks")
    if marks is not None:
        if not isinstance(marks, dict) or set(marks) - {"sections", "starts", "cuts", "hooks"}:
            raise ValueError("the marks are {sections, starts, cuts, hooks} (marks_of): not %s" % _ascii(marks))
        for key in ("sections", "starts", "cuts"):
            if not all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in marks.get(key, [])):
                raise ValueError("the marks' %s are seconds: not %s" % (key, _ascii(marks.get(key))))
        for h in marks.get("hooks", []):
            if not isinstance(h, dict) or not isinstance(h.get("at"), (int, float)) or not h.get("syllables"):
                raise ValueError("a hook of the marks is {at, syllables}: not %s" % _ascii(h))
    _check_vocal(words)
    return words


def _card_texts(words):
    """every text of the title, the tag and the credit cards (where the singer may be written in)"""
    for r in (words.get("title") or {}).get("rows", []):
        yield r.get("text", "")
    if words.get("tag"):
        yield words["tag"].get("text", "")
    for card in words.get("credits", []):
        for r in card.get("rows", []):
            for key in ("role", "name", "note"):
                if r.get(key):
                    yield r[key]


def _check_vocal(words):
    """the vocal is {latin, name} of words; every {vocal.FIELD} of the cards' texts is one of them and is named"""
    vocal = words.get("vocal")
    if vocal is not None and (not isinstance(vocal, dict) or set(vocal) - set(VOCAL_FIELDS)
                              or not all(isinstance(v, str) and v.strip() for v in vocal.values())):
        raise ValueError("the vocal is {latin, name}: the singer as the title and the tag write it (Latin letters) and as "
                         "the credits do, words: not %s" % _ascii(vocal))
    for text in _card_texts(words):
        k = text.find(VOCAL_MARK)
        while k >= 0:
            e = text.find("}", k)
            field = text[k + len(VOCAL_MARK):e] if e > k else ""
            if field not in VOCAL_FIELDS:
                raise ValueError("%s: the singer is written in as {vocal.latin} or {vocal.name}" % _ascii(text))
            if not vocal or not vocal.get(field):
                raise ValueError("%s writes in the singer: the words file needs vocal.%s (the one place the singer is named)"
                                 % (_ascii(text), field))
            k = text.find(VOCAL_MARK, e)


def _with_vocal(text, words):
    """a text of the cards with the singer written in"""
    vocal = words.get("vocal") or {}
    for field in VOCAL_FIELDS:
        if field in vocal:
            text = text.replace("{vocal.%s}" % field, vocal[field])
    return text


def vocal_warnings(words):
    """a warning when the vocal's two forms name two singers (the title one voice, the credits another)"""
    vocal = words.get("vocal") or {}
    latin, name = str(vocal.get("latin", "")).strip().upper(), str(vocal.get("name", "")).strip()
    if latin in SINGERS and name in SINGERS.values() and SINGERS[latin] != name:
        return [_ascii("the singer is two singers: %s in the title and the tag, %s in the credits (set the words file's "
                       "vocal to the voice of the song)" % (vocal["latin"], vocal["name"]))]
    return []


HOOK_NEAR = 0.6                   # s: the song structure's title word this near the one a line sings is its mark
HOOK_OFF = 0.1                    # s: ... and its syllables further than this from the vowels sung are warned of (kinetic2
                                  # 2026-10-21: version 2 of the table had them an eighth, 0.21 s, early: the characters
                                  # came before the singing, and kinetic and kineticrev had checked them by the table only)


def hook_warnings(words):
    """a warning for each title word of the song structure's marks whose syllables lie more than HOOK_OFF s from the vowels
    its line sings them on (the alignment)"""
    hook = words.get("hook") or {}
    marked = _marks(words)[1]
    out = []
    for line in words.get("lines", []):
        for m0, m1 in _hook_spans(line, hook):
            vowels = [_mora(m)["v0"] for m in line["morae"][m0:m1 + 1]]
            mark = min(marked, key=lambda h: abs(float(h["at"]) - vowels[0]), default=None)
            if mark is None or abs(float(mark["at"]) - vowels[0]) > HOOK_NEAR:
                continue
            off = [float(t) - v for t, v in zip(mark["syllables"], vowels)]
            worst = max(off, key=abs)
            if abs(worst) > HOOK_OFF:
                out.append(_ascii("the title word of the song structure at %.3f s is %.2f s %s its singing (its syllables "
                                  "%s s, the alignment's vowels %s s): its characters come %s the voice"
                                  % (float(mark["at"]), abs(worst), "before" if worst < 0 else "after",
                                     ", ".join("%.3f" % float(t) for t in mark["syllables"]),
                                     ", ".join("%.3f" % v for v in vowels), "before" if worst < 0 else "after")))
    return out


def _marks(words):
    """the words file's marks (none: empty), each list in order"""
    m = words.get("marks") or {}
    return ({key: sorted(float(t) for t in m.get(key, [])) for key in ("sections", "starts", "cuts")},
            sorted(m.get("hooks", []), key=lambda h: float(h["at"])))


def _near(t, marks, sooner, later):
    """the mark nearest t from `sooner` s before it to `later` s after it, or None"""
    best = None
    for m in marks:
        if t - sooner - 1e-9 <= m <= t + later + 1e-9 and (best is None or abs(m - t) < abs(best - t)):
            best = m
    return best


def _on_marks(pieces, marks):
    """the subtitles and the large words come on a mark of the song structure near their start and are gone on a mark or a
    cut near their end (each only if the piece keeps at least 0.3 s)"""
    ends = sorted(set(marks["starts"] + marks["cuts"]))
    for p in pieces:
        start = _near(p.start, marks["starts"], MARK_EARLIER, MARK_LATER)
        if start is not None and p.end - start >= 0.3:
            p.start = start
        # its words sung, it may go on a mark from END_SOONER s before its singing ended (kinetic2: its tail, `hang`, is its
        # way to go; on a section's mark the picture changes or flashes)
        sooner = END_SOONER if p.sung_end is None else max(END_SOONER, p.end - p.sung_end + END_SOONER)
        end = _near(p.end, ends, sooner, END_LATER)
        if end is not None and end - p.start >= 0.3:
            p.end = end


def load_words(path):
    with open(path, encoding="utf-8-sig") as f:
        try:
            return check_words(json.load(f))
        except ValueError as e:
            raise ValueError("%s: %s" % (path, e)) from None


def _words(words):
    if isinstance(words, (str, os.PathLike)):
        return load_words(words)
    return check_words(words)


# ---- the plan -----------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Row:
    text: str
    size: float                   # the characters' height: a share of the picture's height
    face: str = "sans"            # sans (Noto Sans JP), serif (Noto Serif JP) or mincho (Shippori Mincho)
    weight: int = 500
    colours: tuple = ()           # per character: fill, blue, red, neon, role
    tracking: float = 0.0         # em between the characters
    gap: float = 0.3              # em (of its own size) between the row before and this one


@dataclasses.dataclass
class Piece:
    id: str
    role: str                     # sub, column, big, hook, interlude, title, tag, credit
    layer: str                    # front (over the dancer) or back (behind her)
    rows: list
    start: float
    end: float
    x: float                      # shares of the picture: the block's anchor (align says which side of it)
    y: float
    align: str = "center"
    vertical: bool = False
    tilt: float = 0.0             # degrees: below 0 the line rises to the right
    hollow: bool = False
    outline: bool = False
    shadow: bool = False
    glow: float = 0.0
    alpha: float = 1.0
    enter: str = "fadein"
    exit: str = "fadeout"
    enter_s: float = 0.45
    exit_s: float = 0.4
    drift: tuple = (0.0, 0.0)     # heights of its first row's characters a second
    push: float = 0.0             # its size grows by this share a second
    char_times: tuple = ()        # the hooks: when each character of the first row comes
    line: int = -1
    section: str = ""
    sung_end: float = None        # a subtitle: s its last sound ends (it may go on a mark from END_SOONER s before)


def _sections(words):
    return sorted(({"kind": s["kind"], "start": float(s["start"]), "end": float(s["end"])} for s in words.get("sections", [])),
                  key=lambda s: s["start"])


def section_at(sections, t):
    """the kind of the section the time t lies in (the last one that started; verse before the first)"""
    kind = "verse"
    for s in sections:
        if s["start"] <= t < s["end"]:
            kind = s["kind"]
    return kind


def _allocate(count, weights, names, seed, salt):
    """`count` names in the shares of `weights`, as closely as the count allows (largest remainders), in an order fixed by
    the seed"""
    w = np.asarray(weights, np.float64)
    w = w / w.sum()
    exact = w * count
    n = np.floor(exact).astype(int)
    order = sorted(range(len(w)), key=lambda k: (-(exact[k] - n[k]), _unit(seed, salt, "rest", k)))
    for k in order[:count - int(n.sum())]:
        n[k] += 1
    picks = [names[k] for k in range(len(w)) for _ in range(n[k])]
    return [p for _, p in sorted(enumerate(picks), key=lambda e: _unit(seed, salt, "order", e[0]))]


def _chosen(count, share, seed, salt):
    """which of `count` things take a share (round(share * count) of them, fixed by the seed)"""
    take = int(round(share * count))
    ranked = sorted(range(count), key=lambda k: _unit(seed, salt, k))
    return set(ranked[:take])


def _colours(text, accents):
    """a colour per character: the accent of a word of `accents` ({colour: [words]}) where one stands, else the fill"""
    out = ["fill"] * len(text)
    for colour in ("blue", "red"):
        for word in (accents or {}).get(colour, []):
            if not word:
                continue
            k = text.find(word)
            while k >= 0:
                for j in range(k, k + len(word)):
                    out[j] = colour
                k = text.find(word, k + len(word))
    return tuple(out)


def _hook_spans(line, hook):
    """[(first mora, last mora)] where the title word's reading is sung in the line"""
    if not hook or not hook.get("reading"):
        return []
    want = "".join(sound(c) for c in hook["reading"] if not _passable(c))
    kana = ["".join(sound(c) for c in (m["kana"] if isinstance(m, dict) else m[0])) for m in line["morae"]]
    out, k = [], 0
    while k < len(kana):
        joined, e = "", k
        while e < len(kana) and len(joined) < len(want):
            joined += "".join(sound(c) for c in kana[e])
            e += 1
        if joined == want:
            out.append((k, e - 1))
            k = e
        else:
            k += 1
    return out


def _life(start, sung_end, settings):
    shortest, longest = settings["life"]
    return start + min(longest, max(shortest, sung_end - start + settings["hang"]))


def _rows(subs, rows):
    """the subtitles' rows (not the columns'): the pieces of a line take `rows` in turn from the first one no subtitle is
    on as the line comes (on until sung, the last piece of a line is still going when the next line comes: by the piece's
    number alone both took the first row, drawn over each other).  Should a piece's row still be taken as it comes (three
    on at once, sung very fast), the one there goes as it comes"""
    lines = {}
    for p in subs:
        if p.role == "sub":
            lines.setdefault(p.line, []).append(p)
    on = {}                                       # a row's index -> the last subtitle on it
    for k in sorted(lines, key=lambda k: min(p.start for p in lines[k])):
        line = sorted(lines[k], key=lambda p: p.start)
        free = [i for i in range(len(rows)) if i not in on or on[i].end <= line[0].start + 1e-9]
        first = free[0] if free else min(on, key=lambda i: on[i].end)
        for j, p in enumerate(line):
            i = (first + j) % len(rows)
            p.y = rows[i]
            if i in on and on[i].end > p.start:
                on[i].end = p.start
            on[i] = p


def plan_words(words, settings, fps=30.0, aspect=16.0 / 9.0):
    """every piece of text of the words file, in the order they come (see the module docstring); aspect: the picture's
    width over its height (a drift across is shares of the width)"""
    words = _words(words)
    s = settings
    seed = int(s["seed"])
    sections = _sections(words)
    accents = words.get("accents") or {}
    hook = words.get("hook") or {}
    pieces = []
    subs, bigs = [], []
    lines = words.get("lines", [])
    sung = [k for k, ln in enumerate(lines) if ln.get("text")]
    mincho = _chosen(len(sung), s["mincho_share"], seed, "mincho")
    bracket = _chosen(len(sung), s["bracket_share"], seed, "bracket")
    outline = _chosen(len(sung), s["outline_share"], seed, "outline")
    shadow = _chosen(len(sung), s["shadow_share"], seed, "shadow")
    verse_lines = [k for k in sung if section_at(sections, float(lines[k]["morae"][0][1] if not isinstance(lines[k]["morae"][0], dict)
                                                                      else lines[k]["morae"][0]["c0"])) in ("verse",)]
    column = {verse_lines[i] for i in _chosen(len(verse_lines), s["column_share"], seed, "column")}
    side = 0
    big_side = 0
    big_kind = 0
    big_lines = 0
    for order, k in enumerate(sung):
        line = lines[k]
        text = line["text"]
        chars = line_chars(text, line["reading"], line["morae"])
        start_line = min(c.t0 for c in chars if c.first >= 0)
        kind = section_at(sections, start_line)
        cuts = cut_line(chars, s)
        face = "mincho" if order in mincho else "sans"
        weight = int(s["weight_mincho"] if face == "mincho" else s["weight"])
        colours = _colours(text, accents)
        in_column = k in column
        made = []
        for j, (a, b) in enumerate(cuts):
            piece_text = "".join(c.ch for c in chars[a:b])
            piece_colours = colours[a:b]
            if order in bracket:
                if j == 0:
                    piece_text, piece_colours = "\u300c" + piece_text, ("fill",) + piece_colours
                if j == len(cuts) - 1:
                    piece_text, piece_colours = piece_text + "\u300d", piece_colours + ("fill",)
            timed = [c for c in chars[a:b] if c.first >= 0]
            start = min((c.v0 if s["at_vowel"] else c.t0) for c in timed) - s["lead"]
            end = _life(start, max(c.t1 for c in timed), s)
            if in_column:
                x, y = s["column_x"][side % len(s["column_x"])], s["column_y"]
            else:
                x, y = s["sub_x"], s["sub_rows"][j % len(s["sub_rows"])]
            # (no outline round Mincho: at 2 px it is as wide as the thin strokes and buries them in its colour)
            p = Piece("L%02dp%d" % (k, j), "column" if in_column else "sub", "front",
                      [Row(piece_text, s["sub_size"], face, weight, piece_colours, s["tracking"])], start, end, x, y,
                      vertical=in_column, outline=order in outline and face != "mincho", shadow=order in shadow, glow=s["glow"],
                      enter_s=s["enter"], exit_s=s["exit"], line=k, section=kind, sung_end=max(c.t1 for c in timed))
            made.append(p)
            subs.append(p)
        if in_column:
            side += 1
        pieces += made
        # a line that sings the title word has it large already (the hook): no large word of its own
        if kind in BIG_SECTIONS and s["big_per_line"] > 0 and not _hook_spans(line, hook):
            ranked = sorted(range(len(made)), key=lambda j: (-(any(c != "fill" for c in made[j].rows[0].colours)),
                                                             abs(len(made[j].rows[0].text) - 4), -j))
            # (a fraction: the lines take its whole part and one more in turn, as many as the fraction says)
            count = int(math.floor((big_lines + 1) * s["big_per_line"] + 1e-9)) - int(math.floor(big_lines * s["big_per_line"] + 1e-9))
            big_lines += 1
            for j in sorted(ranked[:count]):
                src = made[j]
                body = src.rows[0].text.strip("\u300c\u300d")
                body_colours = tuple(c for c, ch in zip(src.rows[0].colours, src.rows[0].text) if ch not in "\u300c\u300d")
                variant = BIG_VARIANTS[big_kind % len(BIG_VARIANTS)]
                big_kind += 1
                rows = [Row(body.replace(" ", ""), s["big_size"], "sans", 800, tuple(c for c, ch in zip(body_colours, body) if ch != " "))]
                if variant == "stack" and len(rows[0].text) >= 4:
                    half = _split_two(rows[0].text)
                    rows = [Row(rows[0].text[:half], s["big_size"], "mincho", 700, rows[0].colours[:half]),
                            Row(rows[0].text[half:], s["big_size"], "mincho", 700, rows[0].colours[half:])]
                elif variant == "stack":
                    rows = [Row(rows[0].text, s["big_size"], "mincho", 700, rows[0].colours)]
                x = s["big_x"][big_side % len(s["big_x"])]
                if variant == "hollow":
                    # the hollow words are cut by the picture's edge (as the references' are): the side it is on, the edge's size
                    rows = [dataclasses.replace(r, size=s["edge_word"]) for r in rows]
                    x = EDGE_X[0] if x < 0.5 else EDGE_X[1]
                echo = src.end - BIG_ECHO
                p = Piece("L%02db%d" % (k, j), "big", "back", rows, echo, echo + (src.end - src.start) + BIG_LONGER,
                          x, s["big_y"][(big_side // 2) % len(s["big_y"])],
                          tilt=s["tilt"] if variant == "tilt" else 0.0,
                          hollow=variant == "hollow", glow=s["neon_glow"] if variant == "hollow" else s["glow"],
                          alpha=s["big_alpha"], enter_s=s["enter"], exit_s=s["exit"], push=s["push"], line=k, section=kind)
                big_side += 1
                pieces.append(p)
                bigs.append(p)
    # on the marks of the song structure (the white flash and the punch of the motion graphics, the changes of picture)
    _on_marks(subs + bigs, _marks(words)[0])
    _rows(subs, s["sub_rows"])
    # the ways the pieces come and go: in the shares of the mixes, over all the subtitles and over all the large words
    for group, enter_mix, exit_mix, salt in ((subs, s["enter_mix"], s["exit_mix"], "sub"),
                                            (bigs, s["big_enter_mix"], s["big_exit_mix"], "big")):
        enters = _allocate(len(group), enter_mix, ENTERS, seed, salt + "-enter")
        exits = _allocate(len(group), exit_mix, EXITS, seed, salt + "-exit")
        for p, e, x in zip(group, enters, exits):
            p.enter, p.exit = e, x
            if e == "cut":
                p.enter_s = 0.0
            elif e == "pop":
                p.enter_s = POP_S
            if x == "cutout":
                p.exit_s = 0.0
            elif x == "popout":
                p.exit_s = POP_S
            p.drift = _drift(p, s)
            if p.role == "sub" and p.drift[0]:
                # it drifts across all its life: it starts half its way to the left, so that it is in the middle half way
                p.x -= 0.5 * p.drift[0] * (p.end - p.start) * p.rows[0].size / aspect
    pieces += _hooks(words, s, fps)
    _clear_for_hooks(pieces)
    pieces += _interludes(words, s, pieces)
    pieces += _cards(words, s)
    return sorted(pieces, key=lambda p: (p.start, p.id))


def _split_two(text):
    """where a large word is parted into two rows: the cut nearest its middle that does not part a word"""
    best, at = None, max(1, len(text) // 2)
    for k in range(1, len(text)):
        if (text[k] in SMALL_KANA or text[k] in NO_START or text[k] == LONG_MARK or text[k] in CLOSING
                or text[k - 1] in OPENING):
            continue
        if kind_of(text[k - 1]) == kind_of(text[k]) and kind_of(text[k]) in ("kanji", "kata"):
            continue
        cost = abs(k - len(text) / 2.0)
        if best is None or cost < best:
            best, at = cost, k
    return at


def _drift(p, s):
    """the drift of a piece (heights a second): the subtitles and the columns to the right, the large words barely (they
    grow: push)"""
    if p.role in ("sub", "column"):
        return (float(s["drift"]), 0.0)
    return (0.15 * float(s["drift"]), 0.0)


def _hooks(words, s, fps):
    hook = words.get("hook") or {}
    text = hook.get("text", "")
    out = []
    sections = _sections(words)
    marks, marked = _marks(words)
    for k, line in enumerate(words.get("lines", [])):
        for n, (m0, m1) in enumerate(_hook_spans(line, hook)):
            morae = [_mora(m) for m in line["morae"][m0:m1 + 1]]
            chars = list(text) if len(text) == len(morae) else [text]
            at = "v0" if s["at_vowel"] else "c0"
            times = tuple(round(m[at] - s["lead"], 4) for m in morae) if len(chars) == len(morae) else (morae[0][at] - s["lead"],)
            end = morae[-1]["v1"] + 0.6
            # the song structure's title word near it (HOOK_NEAR): it comes on its frame, a character on each of its
            # syllables, and starts to go on the next section's mark (where the motion graphics flash); hook_warnings says
            # when the table's syllables are off the singing
            mark = min(marked, key=lambda h: abs(float(h["at"]) - times[0]), default=None)
            if mark is not None and abs(float(mark["at"]) - times[0]) <= HOOK_NEAR:
                syllables = [float(t) for t in mark["syllables"]]
                times = (float(mark["at"]),) + (tuple(syllables[1:]) if len(syllables) == len(times) else times[1:])
                goes = [m for m in marks["sections"] if times[-1] + HOOK_GOES[0] < m <= times[-1] + HOOK_GOES[1]]
                if goes:
                    end = goes[0] + HOOK_EXIT
            start = times[0]
            out.append(Piece("H%02d_%d" % (k, n), "hook", "back",
                             [Row("".join(chars), s["hook_size"], "sans", 900, ("neon",) * len("".join(chars)), 0.05)],
                             start, end, 0.5, s["hook_y"], hollow=False, glow=s["neon_glow"], alpha=1.0, enter="fadein",
                             exit="glitchout", enter_s=0.0, exit_s=HOOK_EXIT, drift=(0.0, 0.0), push=0.06, char_times=times,
                             line=k, section=section_at(sections, start)))
    return out


def _clear_for_hooks(pieces):
    """the title word is large behind her by itself (a line that sings it has no large word of its own): a large word on
    across its start ends there (not drawn if that leaves it less than 0.3 s), one that would come while it is on is not
    drawn (kinetic2: on until sung, the echo of the line before came after its words, under the title word)"""
    for h in [p for p in pieces if p.role == "hook"]:
        for p in [q for q in pieces if q.role == "big" and q.start < h.end and q.end > h.start]:
            if h.start - p.start >= 0.3:
                p.end = h.start
            else:
                pieces.remove(p)


def _interludes(words, s, pieces):
    title = (words.get("interlude") or {}).get("text") or ""
    if not title:
        return []
    out = []
    marks = _marks(words)[0]["sections"]
    for n, sec in enumerate(sec for sec in _sections(words) if sec["kind"] == "interlude"):
        busy = [p.end for p in pieces if p.layer == "back" and sec["start"] - 2.0 <= p.start < sec["end"] and p.end > sec["start"]]
        start = max([sec["start"]] + busy) + 0.3
        end = sec["end"] - 0.2
        # on the song structure's marks: it comes on the first section's mark about the interlude's start that no subtitle is on
        # (the title word may be going; the large words of the section before go there, below), and is gone on a section's
        # mark near its end
        sung = [p.char_times[-1] if p.char_times else p.start for p in pieces
                if p.role == "hook" and sec["start"] - 2.0 <= p.start < sec["end"]]     # the title word's last syllable
        for m in marks:
            if (sec["start"] + INTERLUDE_COMES[0] <= m <= sec["start"] + INTERLUDE_COMES[1]
                    and not any(p.role in ("sub", "column") and p.start < m < p.end for p in pieces)
                    and all(m >= h + 0.2 for h in sung)):
                start = m
                break
        goes = [m for m in marks if end + INTERLUDE_GOES[0] <= m <= end + INTERLUDE_GOES[1] and m > start]
        if goes:
            end = min(goes, key=lambda m: abs(m - end))
        if end - start < 2 * FADE_INTERLUDE + 0.5:
            continue
        # the large words of the section before (the echo of its last line) go on the interlude's head: one on across it
        # ends there, one that would come on it or after it is not drawn (kinetic2 2026-10-21: the echo of the bridge's last
        # line kept the title off the break's head)
        for p in [q for q in pieces if q.role == "big" and q.end > start + 1e-9 and q.start < end]:
            if start - p.start >= 0.3:
                p.end = start
            else:
                pieces.remove(p)
        across = 0.5 / max(1e-6, s["edge_size"])                 # heights: half the picture's width at 16:9 is 0.89 h
        speed = across * (16.0 / 9.0) / (end - start)
        out.append(Piece("I%d" % n, "interlude", "back", [Row(title, s["edge_size"], "sans", 900, ("neon",) * len(title), 0.08)],
                         start, end, 0.62, 0.5, hollow=True, glow=s["neon_glow"] * 0.6, alpha=s["edge_alpha"],
                         enter="fadein", exit="fadeout", enter_s=FADE_INTERLUDE, exit_s=FADE_INTERLUDE,
                         drift=(-speed, 0.0), section="interlude"))
    return out


ROLE_STYLES = {"title": ("mincho", 800, 1.0, 0.04), "latin": ("sans", 700, 0.3, 0.5), "small": ("sans", 500, 0.17, 0.2)}
CREDIT_ENTRY_GAP = 1.1            # em of a role's row before it: the entries of a card stand apart
CREDIT_NOTE = 0.7                 # a note's size against a name's


def _cards(words, s):
    out = []
    title = words.get("title")
    if title:
        rows = []
        for r in title.get("rows", []):
            face, weight, size, tracking = ROLE_STYLES.get(r.get("style", "small"), ROLE_STYLES["small"])
            text = _with_vocal(r["text"], words)
            rows.append(Row(text, s["title_size"] * size, face, weight, ("fill",) * len(text), tracking))
        # behind the dancer, as the large words are (kineticrev 2026-10-21: in front, the opening title lay over her face for
        # 198 of its 200 frames on the final camera D, its Latin rows across her eyes); "layer": "front" puts it in front
        out.append(Piece("title", "title", title.get("layer", "back"), rows, float(title["start"]), float(title["end"]),
                         float(title.get("x", 0.5)),
                         float(title.get("y", 0.42)), align=title.get("align", "center"), glow=s["glow"], enter="blurin",
                         exit="fadeout", enter_s=FADE_TITLE[0], exit_s=FADE_TITLE[1], drift=(0.0, -0.08), push=0.02))
    tag = words.get("tag")
    if tag:
        text = _with_vocal(tag["text"], words)
        out.append(Piece("tag", "tag", "front", [Row(text, s["tag_size"], "sans", 500, ("fill",) * len(text), 0.25)],
                         float(tag["start"]), float(tag["end"]), float(tag.get("x", 0.97)), float(tag.get("y", 0.06)),
                         align=tag.get("align", "right"), alpha=s["tag_alpha"], enter="fadein", exit="fadeout",
                         enter_s=FADE_TAG, exit_s=FADE_TAG))
    sections = _marks(words)[0]["sections"]
    for n, card in enumerate(words.get("credits", [])):
        # a card that would come near a section's mark of the song structure comes on it (the end's first card)
        mark = _near(float(card["start"]), sections, CARD_MARK, CARD_MARK)
        start = float(card["start"]) if mark is None or mark >= float(card["end"]) - 1.0 else mark
        rows = []
        for r in card["rows"]:
            # an entry: what was done (small, spaced, in the accent), who did it, a note; the entries a line apart
            role, name, note = (_with_vocal(r[k], words) if r.get(k) else "" for k in ("role", "name", "note"))
            if role:
                rows.append(Row(role, s["role_size"], "sans", 700, ("role",) * len(role), 0.3, CREDIT_ENTRY_GAP if rows else 0.0))
            if name:
                rows.append(Row(name, s["credit_size"] * float(r.get("size", 1.0)), r.get("face", "sans"), 600,
                                ("fill",) * len(name), 0.04, 0.15 if rows else 0.0))
            if note:
                rows.append(Row(note, s["credit_size"] * CREDIT_NOTE, "sans", 500, ("fill",) * len(note), 0.04, 0.15))
        out.append(Piece("C%d" % n, "credit", "front", rows, start, float(card["end"]), float(card.get("x", 0.07)),
                         float(card.get("y", 0.5)), align=card.get("align", "left"), glow=s["glow"] * 0.6,
                         enter="rise", exit="fadeout", enter_s=s["credit_fade"], exit_s=s["credit_fade"], drift=(0.0, -0.06)))
    return out


def piece_record(p):
    """a piece as the sheet writes it"""
    d = dataclasses.asdict(p)
    d["rows"] = [dataclasses.asdict(r) for r in p.rows]
    return d


# ---- motion -------------------------------------------------------------------------------------------------------------

def ease_out(p):
    return 1.0 - (1.0 - p) ** 3


def ease_in(p):
    return p ** 3


def _clamp(v):
    return min(1.0, max(0.0, v))


def smooth(p):
    """slow at both ends"""
    p = _clamp(p)
    return p * p * (3.0 - 2.0 * p)


def back_out(p, overshoot=1.4):
    """an ease that goes a little past the end and comes back"""
    p -= 1.0
    return 1.0 + p * p * ((overshoot + 1.0) * p + overshoot)


@dataclasses.dataclass
class State:
    alpha: float = 1.0
    dx: float = 0.0               # heights of the first row's characters: right
    dy: float = 0.0               # ... down
    scale: float = 1.0
    blur: float = 0.0             # px of a 720 line picture
    split: float = 0.0            # px of a 720 line picture red and blue part (a glitch)
    tear: int = 0                 # a glitch's frame: the bands of rows torn are chosen by this number (0: none)
    chars: tuple = ()             # per character of the first row: (alpha, dx, dy, scale); () all alike


def _times(p):
    """the piece's ways to come and go, cut in proportion when it is shorter than both together"""
    life = p.end - p.start
    enter, leave = p.enter_s, p.exit_s
    if enter + leave > life > 0:
        enter, leave = enter * life / (enter + leave), leave * life / (enter + leave)
    return enter, leave


def piece_state(p, t, settings):
    """the State of a piece at the time t (seconds of the song), or None when it is not on"""
    if not p.start <= t < p.end:
        return None
    age = t - p.start
    enter_s, exit_s = _times(p)
    E, X = MOVES[p.enter], MOVES[p.exit]
    u_in = 1.0 if enter_s <= 0 else _clamp(age / enter_s)
    u_out = 0.0 if exit_s <= 0 else _clamp((t - (p.end - exit_s)) / exit_s)
    came, gone = ease_out(u_in), ease_in(u_out)
    st = State()
    # the drift: from a cut in it starts STILL_AT_CUT s later, before a cut out it stops STILL_AT_CUT s earlier
    lo = STILL_AT_CUT if (E.get("cut") or E.get("pop")) else 0.0
    hi = (p.end - p.start) - (STILL_AT_CUT if (X.get("cut") or X.get("pop")) else 0.0)
    drifted = min(max(age, lo), max(lo, hi)) - lo
    st.dx, st.dy = p.drift[0] * drifted, p.drift[1] * drifted
    if not E.get("stagger"):
        mx, my = E.get("move", (0.0, 0.0))
        left = (1.0 - back_out(u_in)) if E.get("overshoot") else (1.0 - came)
        st.dx += mx * left
        st.dy += my * left
    if not X.get("stagger"):
        mx, my = X.get("move", (0.0, 0.0))
        st.dx += mx * gone
        st.dy += my * gone
    st.scale = (1.0 + p.push * age) * (E.get("scale", 1.0) + (1.0 - E.get("scale", 1.0)) * came) \
        * (1.0 + (X.get("scale", 1.0) - 1.0) * gone)
    # the blur clears (and comes) at one speed: it stays soft for more of the way than the move
    st.blur = E.get("blur", 0.0) * (1.0 - u_in) + X.get("blur", 0.0) * u_out
    # a fade in and out of its own (smooth at both ends: it is nothing on its first frame and next to nothing on its last);
    # a pop fades in and out in POP_S
    a_in = smooth(u_in) if (E.get("fade") and not E.get("stagger")) else 1.0
    a_out = (1.0 - smooth(u_out)) if (X.get("fade") and not X.get("stagger")) else 1.0
    if E.get("pop"):
        a_in = smooth(age / POP_S)
    if X.get("pop"):
        a_out = 1.0 - smooth((t - (p.end - POP_S)) / POP_S)
    st.alpha = p.alpha * a_in * a_out
    frames = int(settings["glitch_frames"])
    step = None
    since, until = int(math.floor(age * SONG_FPS + 1e-6)), int(math.floor((p.end - t) * SONG_FPS + 1e-6))
    if E.get("glitch") and since < frames:
        step = since
    elif X.get("glitch") and until < frames:
        step = until
    if step is not None:
        st.split = GLITCH_SPLIT[step % len(GLITCH_SPLIT)]
        st.tear = 1 + int(_unit(p.id, step) * 1e6)
        if step == 1:                                      # one frame off: it flickers
            st.alpha = 0.0
    n = len(p.rows[0].text) if p.rows else 0
    if p.char_times:
        chars = []
        for k in range(n):
            when = p.char_times[min(k, len(p.char_times) - 1)]
            u = _clamp((t - when) / HOOK_COME)
            chars.append((u * u * (3 - 2 * u) if t >= when else 0.0, 0.0, 0.0, HOOK_ZOOM + (1.0 - HOOK_ZOOM) * ease_out(u)))
        st.chars = tuple(chars)
    elif E.get("stagger") or X.get("stagger"):
        chars = []
        delay = float(settings["stagger"])
        for k in range(n):
            a, cdx, cdy = 1.0, 0.0, 0.0
            if E.get("stagger"):
                own = max(1e-6, enter_s * STAGGER_SPAN)
                u = _clamp((age - k * delay) / own)
                c = ease_out(u)
                a *= c
                cdx += E["move"][0] * (1.0 - c)
                cdy += E["move"][1] * (1.0 - c)
            if X.get("stagger"):
                own = max(1e-6, exit_s * STAGGER_SPAN)
                u = _clamp((t - (p.end - exit_s) - k * delay) / own)
                g = ease_in(u)
                a *= 1.0 - g
                mx, my = X.get("move", (0.0, 0.0))
                cdx += mx * g
                cdy += my * g
            chars.append((a, cdx, cdy, 1.0))
        st.chars = tuple(chars)
    return st


# ---- fonts --------------------------------------------------------------------------------------------------------------

FONTS_ENV = "MMD_CLI_FONTS"
FONT_DIRS = ("C:/Windows/Fonts", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"))
# the faces (SIL Open Font License 1.1 all three): the file names looked for, the first found; Shippori Mincho has a file a
# weight (no weight axis): the one nearest the weight asked for is taken
FONT_FILES = {"sans": ("NotoSansJP-VF.ttf",), "serif": ("NotoSerifJP-VF.ttf",)}
MINCHO_FILES = {400: "ShipporiMincho-Regular.ttf", 500: "ShipporiMincho-Medium.ttf", 600: "ShipporiMincho-SemiBold.ttf",
                700: "ShipporiMincho-Bold.ttf", 800: "ShipporiMincho-ExtraBold.ttf"}
REFERENCE_CHAR = "\u56fd"         # 国: the glyph whose ink gives a row of Japanese its top and bottom
VERTICAL_FORMS = {"\u300c": "\ufe41", "\u300d": "\ufe42", "\u300e": "\ufe43", "\u300f": "\ufe44", "\uff08": "\ufe35",
                  "\uff09": "\ufe36", "\u3001": "\ufe11", "\u3002": "\ufe12"}
TURNED = frozenset("\u30fc\u301c\uff5e\u2026\u2025-")     # turned a quarter in a column


def _find_font(names, dirs):
    for folder in dirs:
        if not folder or not os.path.isdir(folder):
            continue
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
        try:
            listing = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            for f in listing:
                if f.lower().endswith(name.lower()):
                    return os.path.join(folder, f)
    return None


def _weight_axes(font, weight):
    values, found = [], False
    for axis in font.get_variation_axes():
        name = axis.get("name", b"")
        name = name.decode("ascii", "replace") if isinstance(name, bytes) else str(name)
        if name.strip().lower() in ("weight", "wght"):
            values.append(min(max(weight, axis["minimum"]), axis["maximum"]))
            found = True
        else:
            values.append(axis["default"])
    return values if found else None


class FontBook:
    """the files of the faces on this machine and the glyphs drawn from them (as masks, cached)"""

    def __init__(self, dirs=None):
        self.warnings = []
        extra = [p for p in os.environ.get(FONTS_ENV, "").split(os.pathsep) if p]
        folders = list(dirs or []) + extra + list(FONT_DIRS)
        self.files = {face: _find_font(names, folders) for face, names in FONT_FILES.items()}
        self.mincho = {w: path for w, path in ((w, _find_font((name,), folders)) for w, name in MINCHO_FILES.items()) if path}
        self.files["mincho"] = self.mincho[min(self.mincho)] if self.mincho else None
        if not self.files["sans"]:
            raise ValueError("Noto Sans JP (NotoSansJP-VF.ttf) is not in %s: install it or name its folder in %s"
                             % (", ".join(_ascii(f) for f in folders), FONTS_ENV))
        if not self.files["serif"]:
            self.files["serif"] = self.files["sans"]
            _warn(self.warnings, "Noto Serif JP is not found: serif text is drawn with %s" % os.path.basename(self.files["sans"]))
        if not self.files["mincho"]:
            self.files["mincho"] = self.files["serif"]
            _warn(self.warnings, "Shippori Mincho is not found (name its folder in %s): Mincho text is drawn with %s"
                  % (FONTS_ENV, os.path.basename(self.files["serif"])))
        self._faces, self._glyphs = {}, {}

    def font(self, face, px, weight):
        """the face at px; the weight moves the weight axis of a variable font (a static face, Shippori Mincho Bold, has its
        own weight: the file of the nearest weight is taken)"""
        path = self.files[face]
        if face == "mincho" and self.mincho:
            path = self.mincho[min(self.mincho, key=lambda w: (abs(w - int(weight)), w))]
        key = (path, int(px), int(weight))
        if key not in self._faces:
            f = ImageFont.truetype(key[0], key[1])
            try:
                axes = _weight_axes(f, key[2])
            except (OSError, NotImplementedError, ValueError):
                axes = None                              # not a variable font
            if axes is not None:
                try:
                    f.set_variation_by_axes(axes)
                except (OSError, NotImplementedError, ValueError):
                    _warn(self.warnings, "%s: the weight %d could not be set" % (os.path.basename(key[0]), key[2]))
            self._faces[key] = f
        return self._faces[key]

    def glyph(self, font, ch, stroke=0):
        """(mask 0..1 float32, left, top) of a character set with its pen at (0, 0) on the baseline, or None (nothing to
        draw); stroke widens it by that many px all round"""
        key = (id(font), ch, int(stroke))
        if key not in self._glyphs:
            box = font.getbbox(ch, anchor="ls", stroke_width=int(stroke))
            if box[2] <= box[0] or box[3] <= box[1] or ch.isspace():
                self._glyphs[key] = None
            else:
                im = Image.new("L", (box[2] - box[0], box[3] - box[1]), 0)
                ImageDraw.Draw(im).text((-box[0], -box[1]), ch, font=font, fill=255, anchor="ls", stroke_width=int(stroke),
                                        stroke_fill=255)
                self._glyphs[key] = (np.asarray(im, np.float32) / 255.0, int(box[0]), int(box[1]))
        return self._glyphs[key]


# ---- the layout of a piece (at rest, px of the frame) -----------------------------------------------------------------

@dataclasses.dataclass
class Placed:
    index: int                    # the character's place in the first row (for its own motion), -1 in the other rows
    fill: object                  # the mask
    ring: object                  # the outline or neon edge (a mask), or None
    x: int                        # the masks' top left, in the block's frame (px)
    y: int
    rx: int                       # the ring's top left
    ry: int
    colour: str


@dataclasses.dataclass
class Layout:
    piece: Piece
    glyphs: list
    box: tuple                    # x0, y0, x1, y1 of all the ink at rest, in the block's frame
    anchor: tuple                 # where the block's (0, 0) lies in the picture (px)
    height: float                 # px of the first row's characters (what dx, dy count in)
    scale: float                  # the picture's height over 720


def _row_metrics(book, row, H):
    px = max(4, int(round(row.size * H)))
    weight = row.weight
    font = book.font(row.face, px, weight)
    _, top, _, bottom = font.getbbox(REFERENCE_CHAR, anchor="ls")
    return font, px, float(top), float(bottom)


def layout_piece(piece, size, book, settings):
    """where every glyph of a piece goes at rest"""
    W, H = size
    scale = H / 720.0
    stroke = 0
    if piece.hollow:
        stroke = max(1, int(round(settings["outline_px"] * scale * 1.5)))
    elif piece.outline:
        stroke = max(1, int(round(settings["outline_px"] * scale)))
    glyphs = []
    first_px = None
    if piece.vertical:
        row = piece.rows[0]
        font, px, top, bottom = _row_metrics(book, row, H)
        first_px = px
        step = px * (1.0 + row.tracking)
        y = 0.0
        for k, ch in enumerate(row.text):
            shown = VERTICAL_FORMS.get(ch, ch)
            g = book.glyph(font, shown)
            if g is not None:
                mask, left, gtop = g
                ring = book.glyph(font, shown, stroke) if stroke else None
                if ch in TURNED:
                    mask = np.rot90(mask, -1).copy()
                    ring = (np.rot90(ring[0], -1).copy(), ring[1], ring[2]) if ring else None
                h_, w_ = mask.shape
                cx, cy = 0.0, y + px / 2.0
                gx, gy = int(round(cx - w_ / 2.0)), int(round(cy - h_ / 2.0))
                if ch in SMALL_KANA:
                    gx, gy = gx + int(round(0.1 * px)), gy - int(round(0.1 * px))
                rx = ry = 0
                if ring:
                    rh, rw = ring[0].shape
                    rx, ry = int(round(cx - rw / 2.0)), int(round(cy - rh / 2.0))
                glyphs.append(Placed(k, mask, ring[0] if ring else None, gx, gy, rx, ry, row.colours[k] if k < len(row.colours) else "fill"))
            y += step
        total = y - step * row.tracking
        for g in glyphs:
            g.y -= int(round(total / 2.0))
            g.ry -= int(round(total / 2.0))
    else:
        metrics = [_row_metrics(book, r, H) for r in piece.rows]
        widths = []
        for r, (font, px, _, _) in zip(piece.rows, metrics):
            w = 0.0
            for ch in r.text:
                w += font.getlength(ch) + r.tracking * px
            widths.append(w - (r.tracking * px if r.text else 0.0))
        heights = [bottom - top for _, _, top, bottom in metrics]
        gaps = [r.gap * m[1] for r, m in zip(piece.rows, metrics)]
        total = sum(heights) + sum(gaps[1:])
        y = -total / 2.0
        block_w = max(widths) if widths else 0.0
        for n, (r, (font, px, top, bottom), w) in enumerate(zip(piece.rows, metrics, widths)):
            if first_px is None:
                first_px = px
            if n:
                y += gaps[n]
            base = y - top
            x = {"center": -w / 2.0, "left": 0.0, "right": -w}[piece.align]
            if piece.align == "center" and len(piece.rows) > 1:
                x = -w / 2.0
            for k, ch in enumerate(r.text):
                g = book.glyph(font, ch)
                if g is not None:
                    mask, left, gtop = g
                    ring = book.glyph(font, ch, stroke) if stroke else None
                    glyphs.append(Placed(k if n == 0 else -1, mask, ring[0] if ring else None,
                                         int(round(x + left)), int(round(base + gtop)),
                                         int(round(x + ring[1])) if ring else 0, int(round(base + ring[2])) if ring else 0,
                                         r.colours[k] if k < len(r.colours) else "fill"))
                x += font.getlength(ch) + r.tracking * px
            y += heights[n]
        del block_w
    if glyphs:
        x0 = min(min(g.x, g.rx if g.ring is not None else g.x) for g in glyphs)
        y0 = min(min(g.y, g.ry if g.ring is not None else g.y) for g in glyphs)
        x1 = max(max(g.x + g.fill.shape[1], (g.rx + g.ring.shape[1]) if g.ring is not None else 0) for g in glyphs)
        y1 = max(max(g.y + g.fill.shape[0], (g.ry + g.ring.shape[0]) if g.ring is not None else 0) for g in glyphs)
    else:
        x0 = y0 = x1 = y1 = 0
    anchor = (piece.x * W, piece.y * H)
    return Layout(piece, glyphs, (x0, y0, x1, y1), anchor, float(first_px or max(4, H * 0.04)), scale)


# ---- drawing ------------------------------------------------------------------------------------------------------------

def _colour(settings, key):
    if key == "role":
        key = "blue"
    if key == "neon":
        return np.asarray(settings["neon"], np.float32) / 255.0
    return np.asarray(settings.get(key, settings["fill"]), np.float32) / 255.0


def _over(dst, src):
    """premultiplied src over dst (both h, w, 4 float32), into dst"""
    dst *= (1.0 - src[..., 3:4])
    dst += src


def _paste(canvas, mask, x, y, colour, alpha):
    """a mask in a colour (premultiplied, times alpha) over the canvas at x, y (cut at its edges)"""
    h, w = mask.shape
    H, W = canvas.shape[:2]
    a0, b0 = max(0, x), max(0, y)
    a1, b1 = min(W, x + w), min(H, y + h)
    if a1 <= a0 or b1 <= b0:
        return
    m = mask[b0 - y:b1 - y, a0 - x:a1 - x] * alpha
    src = np.empty((b1 - b0, a1 - a0, 4), np.float32)
    src[..., 3] = m
    src[..., :3] = m[..., None] * colour[None, None, :]
    _over(canvas[b0:b1, a0:a1], src)


def _scaled(mask, factor):
    if abs(factor - 1.0) < 1e-3:
        return mask
    cv2 = _cv2()
    h, w = mask.shape
    return cv2.resize(mask, (max(1, int(round(w * factor))), max(1, int(round(h * factor)))), interpolation=cv2.INTER_LINEAR)


def _local(layout, state, settings):
    """the piece at rest with every character's own alpha, move and size: (premultiplied h, w, 4 float32, its top left in
    the block's frame)"""
    x0, y0, x1, y1 = layout.box
    pad = int(math.ceil(layout.height * 1.2)) if state.chars else 2
    ox, oy = x0 - pad, y0 - pad
    canvas = np.zeros((y1 - y0 + 2 * pad, x1 - x0 + 2 * pad, 4), np.float32)
    piece = layout.piece
    fill_colour = {}
    ring_colour = _colour(settings, "neon") if piece.hollow else _colour(settings, "outline")
    for g in layout.glyphs:
        a, cdx, cdy, cs = (1.0, 0.0, 0.0, 1.0)
        if state.chars and g.index >= 0 and g.index < len(state.chars):
            a, cdx, cdy, cs = state.chars[g.index]
        if a <= 0.0:
            continue
        shift_x, shift_y = int(round(cdx * layout.height)), int(round(cdy * layout.height))
        if g.ring is not None:
            ring = _scaled(g.ring, cs)
            rx = g.rx + shift_x - ox + (g.ring.shape[1] - ring.shape[1]) // 2
            ry = g.ry + shift_y - oy + (g.ring.shape[0] - ring.shape[0]) // 2
            if piece.hollow:
                fill = _scaled(g.fill, cs)
                fx = g.x + shift_x - ox + (g.fill.shape[1] - fill.shape[1]) // 2
                fy = g.y + shift_y - oy + (g.fill.shape[0] - fill.shape[0]) // 2
                edge = ring.copy()
                fh, fw = fill.shape
                ex, ey = fx - rx, fy - ry
                a0, b0 = max(0, ex), max(0, ey)
                a1, b1 = min(edge.shape[1], ex + fw), min(edge.shape[0], ey + fh)
                if a1 > a0 and b1 > b0:
                    edge[b0:b1, a0:a1] = np.clip(edge[b0:b1, a0:a1] - fill[b0 - ey:b1 - ey, a0 - ex:a1 - ex], 0.0, 1.0)
                _paste(canvas, edge, rx, ry, ring_colour, a)
                continue
            _paste(canvas, ring, rx, ry, ring_colour, a)
        fill = _scaled(g.fill, cs)
        fx = g.x + shift_x - ox + (g.fill.shape[1] - fill.shape[1]) // 2
        fy = g.y + shift_y - oy + (g.fill.shape[0] - fill.shape[0]) // 2
        if g.colour not in fill_colour:
            fill_colour[g.colour] = _colour(settings, g.colour)
        _paste(canvas, fill, fx, fy, fill_colour[g.colour], a)
    return canvas, (ox, oy)


def _glow_colour(layout, settings):
    if layout.piece.hollow:
        return _colour(settings, "neon")
    c = _colour(settings, "fill")
    return 0.5 * c + 0.5


def draw_piece(frame, layout, state, settings):
    """a piece in a State over a frame (premultiplied h, w, 4 float32), in place; returns the box it drew in (x0, y0, x1,
    y1) or None"""
    cv2 = _cv2()
    if state is None or state.alpha <= 0.0 or not layout.glyphs:
        return None
    piece = layout.piece
    H, W = frame.shape[:2]
    local, (ox, oy) = _local(layout, state, settings)
    lh, lw = local.shape[:2]
    # the block's frame -> the picture: scale and tilt about the block's (0, 0), then to the anchor and the move
    a = math.radians(-piece.tilt)
    c, s_ = math.cos(a) * state.scale, math.sin(a) * state.scale
    tx = layout.anchor[0] + state.dx * layout.height
    ty = layout.anchor[1] + state.dy * layout.height
    # local pixel (u, v) is the block's (u + ox, v + oy)
    M = np.array([[c, s_, tx + c * ox + s_ * oy], [-s_, c, ty - s_ * ox + c * oy]], np.float64)
    corners = np.array([[0, 0, 1], [lw, 0, 1], [0, lh, 1], [lw, lh, 1]], np.float64) @ M.T
    blur_px = state.blur * layout.scale
    reach = 3.0 * max(blur_px, settings["glow_radius"] * layout.scale if piece.glow > 0 else 0.0, 2.0 if piece.shadow else 0.0)
    reach += max(abs(v) for v in settings["shadow_px"]) * layout.scale if piece.shadow else 0.0
    reach += (GLITCH_TEAR + max(GLITCH_SPLIT)) * layout.scale if state.split else 0.0
    rx0 = max(0, int(math.floor(corners[:, 0].min() - reach)))
    ry0 = max(0, int(math.floor(corners[:, 1].min() - reach)))
    rx1 = min(W, int(math.ceil(corners[:, 0].max() + reach)))
    ry1 = min(H, int(math.ceil(corners[:, 1].max() + reach)))
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    M[0, 2] -= rx0
    M[1, 2] -= ry0
    roi = cv2.warpAffine(local, M, (rx1 - rx0, ry1 - ry0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if blur_px > 0.3:
        roi = cv2.GaussianBlur(roi, (0, 0), blur_px)
    alpha = roi[..., 3].copy()
    under = np.zeros_like(roi)
    if piece.shadow and settings["shadow"] > 0:
        sx, sy = (v * layout.scale for v in settings["shadow_px"])
        shifted = cv2.warpAffine(alpha, np.array([[1, 0, sx], [0, 1, sy]], np.float32), (alpha.shape[1], alpha.shape[0]))
        sh = cv2.GaussianBlur(shifted, (0, 0), max(0.5, 2.0 * layout.scale)) * float(settings["shadow"])
        under[..., 3] = np.clip(sh, 0.0, 1.0)
    if piece.glow > 0 and settings["glow_radius"] > 0:
        g = np.clip(cv2.GaussianBlur(alpha, (0, 0), settings["glow_radius"] * layout.scale) * piece.glow, 0.0, 1.0)
        glow = np.empty_like(roi)
        glow[..., 3] = g
        glow[..., :3] = g[..., None] * _glow_colour(layout, settings)[None, None, :]
        _over(under, glow)
    _over(under, roi)
    roi = under
    if state.split:
        roi = _glitch(roi, state, layout.scale)
    if state.alpha < 1.0:
        roi *= state.alpha
    _over(frame[ry0:ry1, rx0:rx1], roi)
    return (rx0, ry0, rx1, ry1)


def _glitch(roi, state, scale):
    """red and blue parted sideways, and a few bands of rows torn (premultiplied colours: each channel moves with an alpha
    of its own, the alpha is the most of the three)"""
    k = int(round(state.split * scale))
    out = roi.copy()
    if k:
        red = np.zeros_like(roi[..., 0])
        blue = np.zeros_like(roi[..., 0])
        ra = np.zeros_like(roi[..., 0])
        ba = np.zeros_like(roi[..., 0])
        red[:, :-k] = roi[:, k:, 0]
        ra[:, :-k] = roi[:, k:, 3]
        blue[:, k:] = roi[:, :-k, 2]
        ba[:, k:] = roi[:, :-k, 3]
        out[..., 0] = red
        out[..., 2] = blue
        out[..., 3] = np.maximum(np.maximum(roi[..., 3], ra), ba)
    h = out.shape[0]
    if state.tear and h > 8:
        for n in range(GLITCH_ROWS):
            u = _unit(state.tear, n, "row")
            v = _unit(state.tear, n, "height")
            w = _unit(state.tear, n, "shift")
            band = max(2, int(h * (0.06 + 0.12 * v)))
            top = int((h - band) * u)
            shift = int(round((w * 2.0 - 1.0) * GLITCH_TEAR * scale))
            if shift:
                out[top:top + band] = np.roll(out[top:top + band], shift, axis=1)
    return out


def straight(frame, box=None):
    """premultiplied float RGBA -> straight RGBA uint8; with a box (x0, y0, x1, y1) only that part is read, the rest is
    clear (what was drawn lies in it)"""
    if box is not None:
        out = np.zeros(frame.shape, np.uint8)
        x0, y0, x1, y1 = box
        out[y0:y1, x0:x1] = straight(frame[y0:y1, x0:x1])
        return out
    a = frame[..., 3:4]
    rgb = np.where(a > 1e-6, frame[..., :3] / np.maximum(a, 1e-6), 0.0)
    out = np.empty(frame.shape, np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(a[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


# ---- the pictures -------------------------------------------------------------------------------------------------------

FRAME_NAME = "f%05d.png"
LAYERS = ("back", "front")


def _clear(folder):
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.startswith("f") and (name.endswith(".png") or name.endswith(".png.part")):
            os.remove(os.path.join(folder, name))


def _png(rgba):
    cv2 = _cv2()
    bgra = rgba[..., [2, 1, 0, 3]]
    ok, data = cv2.imencode(".png", bgra, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise OSError("OpenCV could not write a PNG")
    return data.tobytes()


def end_of(words, pieces):
    """the song's end as far as the text goes: the words file's `end`, else the last piece's end"""
    if words.get("end"):
        return float(words["end"])
    return max([p.end for p in pieces] + [0.0])


class Drawer:
    """the frames of a words file: the pieces planned once, laid out once, drawn at any time"""

    def __init__(self, words, size, fps, settings=None, book=None):
        self.words = _words(words)
        self.settings = settings or default_settings()
        check_settings(self.settings)
        self.size = (int(size[0]), int(size[1]))
        self.fps = float(fps)
        self.book = book or FontBook()
        self.pieces = plan_words(self.words, self.settings, self.fps, self.size[0] / float(self.size[1]))
        self.layouts = {p.id: layout_piece(p, self.size, self.book, self.settings) for p in self.pieces}

    @property
    def warnings(self):
        """the fonts' (a face not found), the singer's (vocal_warnings) and the title word's (hook_warnings)"""
        out = list(self.book.warnings)
        for w in vocal_warnings(self.words) + hook_warnings(self.words):
            _warn(out, w)
        return out

    def frame(self, t, layer):
        """the layer at the time t: premultiplied (h, w, 4) float32, and the box anything was drawn in (None: nothing)"""
        W, H = self.size
        img = np.zeros((H, W, 4), np.float32)
        box = None
        for p in self.pieces:
            if p.layer != layer or not p.start <= t < p.end:
                continue
            st = piece_state(p, t, self.settings)
            if st is None or st.alpha <= 0.0:
                continue
            b = draw_piece(img, self.layouts[p.id], st, self.settings)
            if b is not None:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        return img, box


def render_sequences(words, work, size=None, fps=None, settings=None, span=None, book=None, jobs=4):
    """Draw the two layers of a words file under `work` (kinetic_back, kinetic_front: whole frames, RGBA PNG numbered from
    0) and return the plan of tools/mv_text.py's render_sequences: where and when each sequence is laid over the video.
    span (from, to) in seconds draws the frames from round(from * fps) up to round(to * fps); without it, from the
    song's start to the end of the text.  A layer with nothing on it in the span has no sequence"""
    words = _words(words)
    size = tuple(size or words.get("size") or (1280, 720))
    fps = float(fps or words.get("fps") or 30)
    drawer = Drawer(words, size, fps, settings, book)
    if span is None:
        first, last = 0, int(math.ceil(end_of(words, drawer.pieces) * fps))
    else:
        first, last = int(round(float(span[0]) * fps)), int(round(float(span[1]) * fps))
    frames = max(1, last - first)
    work = os.path.abspath(work)
    W, H = drawer.size
    empty = _png(np.zeros((H, W, 4), np.uint8))
    plan = {"fps": int(fps) if fps == int(fps) else fps, "size": [W, H], "cues": [], "warnings": [], "pieces": len(drawer.pieces)}
    for layer in LAYERS:
        if not any(p.layer == layer and p.end > first / fps and p.start < last / fps for p in drawer.pieces):
            continue
        folder = os.path.join(work, "kinetic_" + layer)
        _clear(folder)

        def write(n, picture):
            data = _png(picture) if picture is not None else empty
            with open(os.path.join(folder, FRAME_NAME % n), "wb") as f:
                f.write(data)
        # the PNG encoding (OpenCV lets go of the GIL) runs beside the drawing, at most `jobs` frames at a time
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
            pending = []
            for n in range(frames):
                img, box = drawer.frame((first + n) / fps, layer)
                pending.append(pool.submit(write, n, straight(img, box) if box else None))
                if len(pending) >= 2 * max(1, int(jobs)):
                    pending.pop(0).result()
            for f in pending:
                f.result()
        plan["cues"].append({"id": "kinetic_" + layer, "layer": layer, "x": 0, "y": 0, "canvas": [W, H],
                             "start_frame": first, "start": first / fps, "frames": frames,
                             "pattern": folder.replace("\\", "/").replace("%", "%%") + "/" + FRAME_NAME})
    for w in drawer.warnings:
        _warn(plan["warnings"], w)
    return plan


def preview(words, out, at, over=None, size=None, settings=None):
    """one picture: both layers at `at` seconds over a picture (`over`) or over a dark grey"""
    words = _words(words)
    if over:
        with Image.open(over) as im:
            base = im.convert("RGB")
        if size and base.size != tuple(size):
            base = base.resize(tuple(size), Image.LANCZOS)
    else:
        base = Image.new("RGB", tuple(size or words.get("size") or (1280, 720)), (24, 26, 34))
    drawer = Drawer(words, base.size, words.get("fps") or 30, settings)
    picture = np.asarray(base, np.float32) / 255.0
    shown = []
    for layer in LAYERS:
        img, box = drawer.frame(float(at), layer)
        if box:
            picture = picture * (1.0 - img[..., 3:4]) + img[..., :3]
            shown += [p.id for p in drawer.pieces if p.layer == layer and p.start <= at < p.end]
    Image.fromarray(np.clip(picture * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGB").save(out)
    return {"out": os.path.abspath(out), "at": at, "pieces": shown, "warnings": drawer.warnings}


def _run(argv):
    done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.returncode, done.stderr.decode("utf-8", "replace")


def over_command(video, words, out, start=None, end=None, fps=None, settings=None, work=None):
    """both layers over a video or a still picture (`--to` needed for a picture), encoded as the MV is (libx264 crf 16,
    BT.709 with its four tags); for measuring the text with tools/typo_analyze.py"""
    words = _words(words)
    still = os.path.splitext(video)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp")
    if still:
        with Image.open(video) as im:
            size = im.size
        if end is None:
            raise ValueError("over a picture needs --to")
        fps = float(fps or 30)
    else:
        size, rate = _tool("mv_look").probe(video)
        fps = float(fps or rate)
    a = float(start or 0.0)
    if end is None:
        drawer = Drawer(words, size, fps, settings)
        end = end_of(words, drawer.pieces)
    frames = int(round(float(end) * fps)) - int(round(a * fps))
    if still:
        return _over_still(video, words, out, a, frames, fps, settings, size)
    work = os.path.abspath(work or out + ".work")
    plan = render_sequences(words, work, size, fps, settings, span=(a, float(end)))
    argv = ["ffmpeg", "-v", "error", "-y", "-ss", "%.6f" % a, "-i", video]
    chains, last = ["[0:v]format=gbrp,trim=end_frame=%d,setpts=PTS-STARTPTS[v0]" % frames], "v0"
    for k, cue in enumerate(plan["cues"], 1):
        argv += ["-framerate", "%g" % fps, "-start_number", "0", "-i", cue["pattern"]]
        chains.append("[%d:v]format=rgba,setpts=PTS-STARTPTS[t%d]" % (k, k))
        chains.append("[%s][t%d]overlay=x=0:y=0:eof_action=pass:format=gbrp[v%d]" % (last, k, k))
        last = "v%d" % k
    chains.append("[%s]%s[out]" % (last, _tool("mv_look").COLOUR_OUT))
    argv += ["-filter_complex", ";".join(chains), "-map", "[out]", "-an", "-r", "%g" % fps, "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    code, err = _run(argv)
    if code != 0:
        raise RuntimeError("ffmpeg failed (%d): %s" % (code, err.strip()[-600:]))
    return {"out": os.path.abspath(out), "frames": frames, "fps": fps, "size": list(size), "layers": len(plan["cues"]),
            "pieces": plan["pieces"], "warnings": plan["warnings"]}


def compose(base, drawer, t):
    """the back and then the front layer at the time t over a picture (float RGB 0..1, h, w, 3), or None when neither has
    anything on it"""
    out = None
    for layer in LAYERS:
        img, box = drawer.frame(t, layer)
        if box is None:
            continue
        if out is None:
            out = base.copy()
        x0, y0, x1, y1 = box
        part = img[y0:y1, x0:x1]
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1.0 - part[..., 3:4]) + part[..., :3]
    return out


def _over_still(picture, words, out, start, frames, fps, settings, size):
    """both layers over a still picture, laid in numpy (premultiplied over: the picture times 1 - alpha, plus the layer) and
    handed to ffmpeg as raw frames: no PNG in between (they cost the most of a frame), the same picture up to the
    rounding of the PNGs' 8 bits"""
    with Image.open(picture) as im:
        base = np.asarray(im.convert("RGB"), np.float32) / 255.0
    drawer = Drawer(words, size, fps, settings)
    W, H = drawer.size
    first = int(round(start * fps))
    argv = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-framerate", "%g" % fps,
            "-i", "-", "-vf", "format=gbrp," + _tool("mv_look").COLOUR_OUT, "-an", "-frames:v", str(frames), "-c:v", "libx264",
            "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    with open(os.devnull, "wb") as sink:
        enc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=sink, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        still_bytes = (np.clip(base * 255.0 + 0.5, 0, 255)).astype(np.uint8).tobytes()
        try:
            for n in range(frames):
                picture_now = compose(base, drawer, (first + n) / fps)
                if picture_now is None:
                    enc.stdin.write(still_bytes)
                else:
                    enc.stdin.write(np.clip(picture_now * 255.0 + 0.5, 0, 255).astype(np.uint8).tobytes())
            enc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        err = enc.stderr.read().decode("utf-8", "replace")
        code = enc.wait()
    if code != 0:
        raise RuntimeError("ffmpeg failed (%d): %s" % (code, err.strip()[-600:]))
    return {"out": os.path.abspath(out), "frames": frames, "fps": fps, "size": [W, H], "layers": 2, "pieces": len(drawer.pieces),
            "warnings": drawer.warnings}


# ---- the commands -------------------------------------------------------------------------------------------------------

def _size(text):
    try:
        w, h = (int(v) for v in text.lower().split("x"))
        if w < 2 or h < 2:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError("a size is WIDTHxHEIGHT, like 1280x720, not %r" % (text,))


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("words", help="the words file from the cue file, the readings and the alignment")
    s.add_argument("out")
    s.add_argument("--cues", required=True, help="the MV's cue file (tools/mv_text.py): its lyric cues give the lines' text")
    s.add_argument("--lines", required=True, help="LINES.tsv: start, end and the line in kana")
    s.add_argument("--align", required=True, help="tools/lip_sync.py --align-out: the morae and their times")
    s.add_argument("--structure", help="sections, hook, accents, title, tag, interlude, end")
    s.add_argument("--credits", help="the credit cards")
    s.add_argument("--marks", help="the MV's shared song structure (version 2: the frames the motion graphics flash and "
                                   "punch on): the text comes and goes on them")
    s = sub.add_parser("sheet", help="every piece with its times, place and ways to come and go")
    s.add_argument("words")
    s.add_argument("out")
    s.add_argument("--look")
    s.add_argument("--fps", type=float, default=30.0)
    s = sub.add_parser("frames", help="draw the two layers and print the plan")
    s.add_argument("words")
    s.add_argument("work")
    s.add_argument("--look")
    s.add_argument("--size", default="1280x720")
    s.add_argument("--fps", type=float, default=30.0)
    s.add_argument("--from", dest="start", type=float)
    s.add_argument("--to", type=float)
    s = sub.add_parser("preview", help="one picture of what is on at a time")
    s.add_argument("words")
    s.add_argument("out")
    s.add_argument("--at", type=float, required=True)
    s.add_argument("--over")
    s.add_argument("--look")
    s.add_argument("--size")
    s = sub.add_parser("over", help="both layers over a video or a picture (to measure the text)")
    s.add_argument("video")
    s.add_argument("words")
    s.add_argument("out")
    s.add_argument("--look")
    s.add_argument("--from", dest="start", type=float)
    s.add_argument("--to", type=float)
    s.add_argument("--fps", type=float)
    s.add_argument("--work")
    args = p.parse_args(argv)
    try:
        if args.command == "words":
            with open(args.lines, encoding="utf-8-sig") as f:
                lines_text = f.read()
            words = build_words(_read_json(args.cues), lines_text, _read_json(args.align),
                                _read_json(args.structure) if args.structure else None,
                                _read_json(args.credits) if args.credits else None,
                                marks_of(_read_json(args.marks)) if args.marks else None)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(words, f, ensure_ascii=False, indent=1)
            result = {"out": os.path.abspath(args.out), "lines": len(words["lines"]),
                      "sung": sum(1 for ln in words["lines"] if ln.get("text")),
                      "warnings": vocal_warnings(words) + hook_warnings(words)}
        elif args.command == "sheet":
            settings = settings_of(args.look)
            check_settings(settings)
            pieces = plan_words(load_words(args.words), settings, args.fps)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump({"pieces": [piece_record(x) for x in pieces]}, f, ensure_ascii=False, indent=1)
            roles = {}
            for x in pieces:
                roles[x.role] = roles.get(x.role, 0) + 1
            words = load_words(args.words)
            result = {"out": os.path.abspath(args.out), "pieces": len(pieces), "roles": roles,
                      "warnings": vocal_warnings(words) + hook_warnings(words)}
        elif args.command == "frames":
            span = None
            if args.start is not None or args.to is not None:
                if args.start is None or args.to is None:
                    raise ValueError("--from and --to go together")
                span = (args.start, args.to)
            result = render_sequences(load_words(args.words), args.work, _size(args.size), args.fps, settings_of(args.look), span)
        elif args.command == "preview":
            result = preview(load_words(args.words), args.out, args.at, args.over, _size(args.size) if args.size else None,
                             settings_of(args.look))
        else:
            result = over_command(args.video, load_words(args.words), args.out, args.start, args.to, args.fps,
                                  settings_of(args.look), args.work)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": {"type": "ValueError", "message": _ascii(e)}}, ensure_ascii=True))
        return 2
    except (OSError, RuntimeError) as e:
        print(json.dumps({"ok": False, "error": {"type": type(e).__name__, "message": _ascii(e)}}, ensure_ascii=True))
        return 1
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
