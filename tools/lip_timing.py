"""When is the song sung?  Read it from the vowels of a lip motion (.vmd), without the sound.

    python tools/lip_timing.py LIPS.vmd [--out timing.json] [--gap 24] [--find LINE ... | --lines FILE]
                                        [--search LINE ...] [--errors N]

A lip motion opens the mouth with the morphs あ い う え お, keyed to the song.  Where such a morph reaches a
peak a vowel is sung, so the motion holds the rhythm of the lyrics: when the singing starts, where the lines
break, and - because a line of lyrics has its own run of vowels - where a given line is sung.  That is
enough to put lyrics on a video in time when the sound itself is not at hand (a dance and a lip motion made
for the same recording both start at frame 0 of it).

* An onset (onsets) is a key of a vowel morph of at least MIN_WEIGHT whose weight is above the key before
  it and not below the key after it: the first frame at which the mouth is fully open.
* A phrase (phrases) is a run of onsets with less than --gap frames (0.8 s) between neighbours.
* --find LINE (repeated, or --lines FILE with one line per row) places the lyrics of the song: all the lines at
  once, in their order, each onset going to one line at most (align).  A line is written in kana or in Latin
  letters (vowels_of: か is a, きょ is o, っ and ん sound no vowel, ー repeats the vowel before it; a kanji cannot
  be read and is an error).  The vowels of all the lines are aligned to the onsets in one pass (an edit
  distance, dynamic programming): a vowel without an onset, an onset of another vowel and an extra onset inside
  a line cost 1 each; an onset between two lines (an ad lib, a breath, the intro) costs 0.05; a line that runs
  on over a pause of PAUSE frames (1.5 s) costs 3 more.  Each line gets the frames of its onsets and its
  errors (the edits inside it).  Lines looked up one by one take each other's vowels where a line begins as
  the one before ends: one pass cannot.
* --search LINE looks one line up everywhere it is sung (find), say a word sung in every chorus.  With --errors N
  a place still counts when N of its vowels are missing, extra or different, since a mouth does not shape
  every syllable.  A place may not be longer than a second per vowel; places do not overlap.

The summary is one line of JSON; --out writes every onset and phrase (frames, and seconds at 30 fps).
"""
import argparse
import dataclasses
import json
import os
import sys
import unicodedata
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli.formats import vmd  # noqa: E402

FPS = 30.0
VOWEL_MORPHS = {"あ": "a", "い": "i", "う": "u", "え": "e", "お": "o"}
MIN_WEIGHT = 0.3
GAP = 24
SPAN_PER_VOWEL = 30              # frames: a match is at most this long per vowel of its line
EDIT = 1.0                       # align: a vowel without an onset, an onset of another vowel, an extra onset in a line
BETWEEN = 0.05                   # align: an onset between two lines (an ad lib, a breath, the intro)
PAUSE = 45                       # align: frames between two onsets that make a pause (1.5 s) ...
PAUSE_COST = 3.0                 # ... which a line costs this much more to run on over
_GLIDES = ("YA", "YU", "YO", "A", "I", "U", "E", "O", "WA")       # small kana that change the vowel before them


@dataclasses.dataclass
class Onset:
    frame: int
    vowel: str
    weight: float


@dataclasses.dataclass
class Phrase:
    start: int
    end: int
    vowels: str


def onsets(motion):
    """every sung vowel of a lip motion, in time order (see the module docstring)"""
    out = []
    seen = False
    for name, vowel in VOWEL_MORPHS.items():
        keys = sorted((k for k in motion.morphs if k.name == name), key=lambda k: k.frame)
        seen = seen or bool(keys)
        for i, key in enumerate(keys):
            before = keys[i - 1].weight if i > 0 else 0.0
            after = keys[i + 1].weight if i + 1 < len(keys) else 0.0
            if key.weight >= MIN_WEIGHT and key.weight > before and key.weight >= after:
                out.append(Onset(key.frame, vowel, round(float(key.weight), 3)))
    if not seen:
        raise ValueError("the motion has no key of a vowel morph (%s): it is not a lip motion" % " ".join(VOWEL_MORPHS))
    return sorted(out, key=lambda o: (o.frame, o.vowel))


def phrases(points, gap=GAP):
    """runs of onsets with less than `gap` frames between neighbours"""
    if gap < 1:
        raise ValueError("--gap is a number of frames, at least 1")
    out: List[Phrase] = []
    for point in points:
        if out and point.frame - out[-1].end < gap:
            out[-1].end = point.frame
            out[-1].vowels += point.vowel
        else:
            out.append(Phrase(point.frame, point.frame, point.vowel))
    return out


def vowels_of(line):
    """the vowels of a line written in kana or Latin letters, as a string of a i u e o"""
    out = []
    for ch in line:
        name = unicodedata.name(ch, "")
        if "HIRAGANA LETTER " in name or "KATAKANA LETTER " in name:
            syllable = name.split("LETTER ", 1)[1]
            small = syllable.startswith("SMALL ")
            syllable = syllable.replace("SMALL ", "")
            if syllable == "N" or (small and syllable == "TU"):
                continue
            vowel = syllable[-1].lower()
            if vowel not in "aiueo":
                continue
            if small and syllable in _GLIDES and out:
                out[-1] = vowel                              # きょ: the small kana takes the place of the vowel
            else:
                out.append(vowel)
        elif "PROLONGED SOUND MARK" in name:
            if out:
                out.append(out[-1])
        elif name.startswith("CJK UNIFIED IDEOGRAPH") or name.startswith("CJK COMPATIBILITY IDEOGRAPH"):
            raise ValueError("cannot read the kanji %s: write the line in kana (or in Latin letters)"
                             % ch.encode("ascii", "backslashreplace").decode("ascii"))
        elif ch.lower() in "aiueo" and ch.isascii():
            out.append(ch.lower())
    return "".join(out)


def _distance(a, b):
    """how many vowels are missing, extra or different between two runs (Levenshtein)"""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, start=1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def find(points, line, errors=0, span=None):
    """where the vowels `line` are sung: [{"frames": the frames of the onsets, "errors": n}], in time order,
    not overlapping, the better match first where two overlap"""
    if not line:
        raise ValueError("the line has no vowel to look for")
    sung = "".join(p.vowel for p in points)
    limit = span if span is not None else SPAN_PER_VOWEL * len(line)
    candidates = []
    for start in range(len(points)):
        for length in range(max(1, len(line) - errors), len(line) + errors + 1):
            end = start + length
            if end > len(points) or points[end - 1].frame - points[start].frame > limit:
                continue
            d = _distance(line, sung[start:end])
            if d <= errors:
                candidates.append((d, abs(length - len(line)), start, end))
    taken, out = [], []
    for d, _, start, end in sorted(candidates):
        if all(end <= s or start >= e for s, e in taken):
            taken.append((start, end))
            out.append((start, {"frames": [p.frame for p in points[start:end]], "errors": d}))
    return [match for _, match in sorted(out, key=lambda item: item[0])]


def align(points, lines, pause=PAUSE):
    """where each of `lines` (runs of vowels, in the order they are sung) is sung, all placed at once:
    [{"frames": the frames of the line's onsets, "errors": n}] for every line, in order.  The onsets taken by the
    lines are in time order and none is in two lines; a line left without an onset has no frames.  The costs are
    in the module docstring; on a tie a match goes before a missing vowel, and that before an extra onset."""
    seq, line_of, first_of = [], [], []
    for k, line in enumerate(lines):
        if not line:
            raise ValueError("line %d has no vowel to place" % (k + 1))
        for p, vowel in enumerate(line):
            seq.append(vowel)
            line_of.append(k)
            first_of.append(p == 0)
    n, m = len(seq), len(points)
    sung = [p.vowel for p in points]
    # paused[j]: onset j comes a pause after onset j - 1
    paused = [False] + [points[j].frame - points[j - 1].frame >= pause for j in range(1, m)]
    # inside[i]: after i vowels the alignment is inside a line (between two of its vowels)
    inside = [0 < i < n and line_of[i - 1] == line_of[i] for i in range(n + 1)]
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    move = [bytearray(m + 1) for _ in range(n + 1)]         # 1 match, 2 vowel without onset, 3 onset without vowel
    cost[0][0] = 0.0
    for i in range(n + 1):
        row, here = cost[i], move[i]
        above = cost[i - 1] if i else None
        extra = EDIT if inside[i] else BETWEEN
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, how = inf, 0
            if i and j:
                c = above[j - 1] + (0.0 if seq[i - 1] == sung[j - 1] else EDIT)
                if paused[j - 1] and not first_of[i - 1]:
                    c += PAUSE_COST
                if c < best:
                    best, how = c, 1
            if i:
                c = above[j] + EDIT
                if c < best:
                    best, how = c, 2
            if j:
                c = row[j - 1] + extra + (PAUSE_COST if inside[i] and paused[j - 1] else 0.0)
                if c < best:
                    best, how = c, 3
            row[j], here[j] = best, how
    out = [{"frames": [], "errors": 0} for _ in lines]
    i, j = n, m
    while i or j:
        how = move[i][j]
        if how == 1:
            line = out[line_of[i - 1]]
            line["frames"].append(points[j - 1].frame)
            line["errors"] += seq[i - 1] != sung[j - 1]
            i, j = i - 1, j - 1
        elif how == 2:
            out[line_of[i - 1]]["errors"] += 1
            i -= 1
        else:
            if inside[i]:
                out[line_of[i]]["errors"] += 1
            j -= 1
    for line in out:
        line["frames"].reverse()
    return out


def _seconds(first, last):
    return [round(first / FPS, 3), round(last / FPS, 3)]


def write_bytes(path, data):
    """write next to the target and move over it, so a failure leaves the old file as it was"""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


def read_lines(path):
    """the lines of lyrics in a UTF-8 text file, one per row; blank rows are no lines"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return [row.strip() for row in f if row.strip()]
    except OSError as exc:
        raise ValueError("cannot read the lines %s: %s" % (path, exc))


def run(lips_path, out_path=None, gap=GAP, lines=(), errors=0, search=()):
    full = os.path.abspath(lips_path)
    points = onsets(vmd.load(full))
    runs = phrases(points, gap)
    found = []
    if lines:
        vowels = [vowels_of(line) for line in lines]
        for index, (line, placed) in enumerate(zip(vowels, align(points, vowels))):
            frames = placed["frames"]
            found.append({"index": index, "line": line, "frames": frames,
                          "seconds": _seconds(frames[0], frames[-1]) if frames else None, "errors": placed["errors"]})
    searched = []
    for line in search:
        vowels = vowels_of(line)
        for match in find(points, vowels, errors):
            searched.append({"line": vowels, "frames": match["frames"], "seconds": _seconds(match["frames"][0], match["frames"][-1]),
                             "errors": match["errors"]})
    result = {"in": full, "onsets": len(points), "phrases": len(runs),
              "first": points[0].frame if points else None, "last": points[-1].frame if points else None, "found": found}
    if search:
        result["searched"] = searched
    if out_path:
        out_full = os.path.abspath(out_path)
        if os.path.normcase(out_full) == os.path.normcase(full):
            raise ValueError("--out must not be the lip motion itself")
        data = {"in": full, "fps": FPS, "gap": gap, "min_weight": MIN_WEIGHT,
                "onsets": [[p.frame, p.vowel, p.weight] for p in points],
                "phrases": [{"start": r.start, "end": r.end, "seconds": _seconds(r.start, r.end), "vowels": r.vowels} for r in runs],
                "found": found}
        if search:
            data["searched"] = searched
        write_bytes(out_full, (json.dumps(data, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        result["out"] = out_full
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("lips", help="the lip motion (.vmd with the morphs あ い う え お)")
    p.add_argument("--out", help="write every onset and phrase to this JSON")
    p.add_argument("--gap", type=int, default=GAP, help="frames of silence that end a phrase (default %d)" % GAP)
    p.add_argument("--find", action="append", default=[], metavar="LINE",
                   help="a line of lyrics in kana or Latin letters; repeat it for every line of the song, in order: "
                        "the lines are placed together")
    p.add_argument("--lines", metavar="FILE", help="the lines of lyrics, one per row of a UTF-8 text file (instead of --find)")
    p.add_argument("--search", action="append", default=[], metavar="LINE",
                   help="a line to look up everywhere it is sung (say a word of every chorus); may repeat")
    p.add_argument("--errors", type=int, default=0,
                   help="with --search: vowels of a line that may be missing, extra or different (default 0)")
    args = p.parse_args(argv)
    try:
        if args.errors < 0:
            raise ValueError("--errors cannot be negative")
        if args.find and args.lines:
            raise ValueError("give the lines with --find or with --lines, not both")
        lines = read_lines(args.lines) if args.lines else args.find
        result = run(args.lips, args.out, args.gap, lines, args.errors, args.search)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
