"""Put MV-style text (a title lockup, credits, lyrics, hook cards) on a video MMD rendered, without MMD.

    python tools/mv_text.py render IN.avi cues.json OUT.mp4 [--work DIR] [--size WxH] [--fps N]
    python tools/mv_text.py preview cues.json OUT.png --at SECONDS [--over FRAME.png] [--size WxH]
    python tools/mv_text.py frames cues.json WORK [--size WxH] [--fps N]

The text is drawn with Pillow, one RGBA PNG sequence per cue, and ffmpeg lays the sequences over the video
(`overlay`).  ffmpeg's own drawtext cannot space letters, wipe or offset a copy, which is what makes a title
look designed; drawing the frames here can.  A sequence is only as large as the cue's box, not the frame.
"""
import dataclasses
import fractions
import json
import math
import os
import re
from typing import List, Optional, Tuple

from PIL import ImageFont

# ---- the fonts ------------------------------------------------------------------------------
# The per-user fonts folder holds the Y1 faces by YUTAONE.  They have Latin letters and digits only (no
# kana, no kanji, little punctuation), so Japanese goes to Noto Sans JP, a variable font whose one axis is
# the weight.
USER_FONTS = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")
LATIN_FILES = {
    "logo": "Y1RevForge.otf",                # the headline: a heavy, wide geometric sans
    "latin": "Y1Vectura.otf",                # sub-heads and credits: the same family of shapes, lighter
    "accent": "Y1Cybanin3000-Glitch.otf",    # flash cards only: a broken face, tiring when used all over
}
# the Japanese font and what stands in for it: the first that exists.  Only the first has a weight axis.
JP_FONTS = ("C:/Windows/Fonts/NotoSansJP-VF.ttf", "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc")
CJK_START = 0x2E80                           # from here up (CJK, kana, fullwidth forms) a code point is Japanese
MISSING = "\U0010ffff"                       # no font has it: it is drawn as the face's "missing" box

# ---- the cue file ---------------------------------------------------------------------------
FPS = 30
SIZE = (1280, 720)
ENTER, EXIT = 0.6, 0.4                       # seconds a cue takes to come and to go, unless it says otherwise
ANIMS = ("fade", "rise", "tracking-in", "wipe", "flash", "roll")
X_ANCHORS = ("left", "center", "right")
Y_ANCHORS = ("top", "middle", "lower", "bottom")
PALETTES = {
    # white text and an amber accent for a black stage (glow and light effects need the black)
    "dark": {"text": (245, 245, 248), "accent": (240, 160, 48), "secondary": (172, 172, 174), "ink": (22, 22, 30),
             "stage": (0, 0, 0)},
    # ink on the white stage MMD draws by default; white text would vanish there
    "light": {"text": (22, 22, 30), "accent": (240, 160, 48), "secondary": (120, 120, 130), "ink": (22, 22, 30),
              "stage": (255, 255, 255)},
}
DEFAULT_PALETTE = "dark"
DEFAULT_STYLE, DEFAULT_ANIM, DEFAULT_X, DEFAULT_Y = "lyric", "fade", "center", "lower"
# the names of the older tools/overlay_text.py, read in a bare list of cues
OLD_STYLES = {"title": "logo", "lyric": "lyric", "credit": "credit", "caption": "sub"}
OLD_ANIMS = {"fade": "fade", "slide-up": "rise", "slide-left": "rise"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
SHEET_KEYS = ("fps", "size", "palette", "cues", "note")
CUE_KEYS = ("id", "start", "end", "x", "y", "anim", "text", "style", "size", "lines", "enter", "exit", "note")
LINE_KEYS = ("text", "style", "size")


@dataclasses.dataclass
class Style:
    latin: str                   # the role of the font for Latin: "logo", "latin", "accent" or "jp"
    latin_size: float            # px in a 720 high frame
    jp_size: float               # px, of the Japanese font in the same line
    weight: int                  # of the Japanese font: 900, 700 or 400
    tracking: float              # em added after every Latin character
    colour: str                  # the palette's "text", "accent" or "secondary"
    upper: bool = False
    underline: bool = False      # an accent rule under the block, drawn as the cue comes in
    ink_copy: bool = False       # a copy in the palette's ink, a little to the left, behind the text


# Sizes are px in a 720 high frame and scale with the frame height.  A style the design gives one script
# only gets the other at the same size and a weight to match (a Japanese title in "logo" is Noto Black);
# "jp" as the Latin role means Noto draws the Latin of that style too.
STYLES = {
    "logo": Style("logo", 150, 150, 900, 0.02, "text"),
    "title_jp": Style("jp", 44, 44, 900, 0.0, "text"),
    "sub": Style("latin", 30, 30, 700, 0.25, "accent", upper=True),
    "credit": Style("latin", 22, 24, 400, 0.12, "secondary"),
    "lyric": Style("jp", 46, 46, 700, 0.0, "text", underline=True),
    "hook": Style("accent", 180, 180, 900, 0.0, "accent", ink_copy=True),
    "caption": Style("jp", 28, 28, 400, 0.0, "text"),
}


def _ascii(text):
    """for a warning: the terminal is cp932, a path or a character outside ASCII is written as its escape"""
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _warn(warnings, text):
    """say it once"""
    text = _ascii(text)
    if warnings is not None and text not in warnings:
        warnings.append(text)


# ---- fonts ----------------------------------------------------------------------------------

def runs(text):
    """a line as (script, text) pieces, cut where the script changes: "jp" for code points from CJK_START up,
    "latin" for the rest (spaces and punctuation included)"""
    out = []
    for ch in text:
        script = "jp" if ord(ch) >= CJK_START else "latin"
        if out and out[-1][0] == script:
            out[-1] = (script, out[-1][1] + ch)
        else:
            out.append((script, ch))
    return out


def _weight_axes(font, weight):
    """the value of every axis of a variable font with the weight axis at `weight` (inside its range)"""
    values, found = [], False
    for axis in font.get_variation_axes():
        name = axis.get("name", b"")
        name = name.decode("ascii", "replace") if isinstance(name, bytes) else str(name)
        if name.strip().lower() in ("weight", "wght"):
            values.append(min(max(weight, axis["minimum"]), axis["maximum"]))
            found = True
        else:
            values.append(axis["default"])
    if not found:
        raise ValueError("no weight axis")
    return values


def load_font(path, size, weight=None, warnings=None):
    """the face of a file at `size` px.  `weight` (100 to 900) moves the weight axis of a variable font; when
    the file has no such axis or the call fails, the face stays the file's default instance and a warning
    says so (the default instance of Noto Sans JP is Thin: that must not pass unnoticed)."""
    font = ImageFont.truetype(path, size)
    if weight is None:
        return font
    try:
        font.set_variation_by_axes(_weight_axes(font, weight))
    except (OSError, NotImplementedError, ValueError) as e:
        _warn(warnings, "%s: weight %d could not be set (%s), its default instance is used"
              % (os.path.basename(path), weight, e))
    return font


class FontBook:
    """which file serves each role on this machine, and the faces loaded from them.  A Y1 face that is not
    installed is replaced by the Japanese font, the Japanese font by the first of its candidates that
    exists; `warnings` (ASCII) says which."""

    def __init__(self, user_dir=USER_FONTS, jp_candidates=JP_FONTS):
        self.warnings = []
        jp = next((path for path in jp_candidates if os.path.exists(path)), None)
        if jp is None:
            raise ValueError("no Japanese font on this machine, looked for: %s" % ", ".join(jp_candidates))
        if jp != jp_candidates[0]:
            _warn(self.warnings, "%s not found: Japanese is drawn with %s" % (jp_candidates[0], jp))
        self.files = {"jp": jp}
        for role, name in LATIN_FILES.items():
            path = os.path.join(user_dir, name)
            if os.path.exists(path):
                self.files[role] = path
            else:
                self.files[role] = jp
                _warn(self.warnings, "%s not found in %s: the %s font is %s" % (name, user_dir, role, os.path.basename(jp)))
        self._faces = {}
        self._glyphs = {}

    def font(self, role, size, weight):
        """the face of a role at `size` px.  The weight reaches the Japanese file only: the Y1 faces have one."""
        path = self.files[role]
        key = (path, size, weight if path == self.files["jp"] else None)
        if key not in self._faces:
            self._faces[key] = load_font(path, size, key[2], self.warnings)
        return self._faces[key]

    def has_glyph(self, font, ch):
        """whether the face draws `ch` itself.  A code point it lacks comes out as its "missing" box, which is
        what MISSING comes out as too; white space draws nothing in any face and is taken as present."""
        if ch.isspace():
            return True
        key = (id(font), ch)
        if key not in self._glyphs:
            mask, missing = font.getmask(ch), font.getmask(MISSING)
            self._glyphs[key] = not (mask.size == missing.size and bytes(mask) == bytes(missing))
        return self._glyphs[key]


# ---- the cue file ---------------------------------------------------------------------------

@dataclasses.dataclass
class LineSpec:
    text: str
    style: str
    size: Optional[float] = None     # px in a 720 high frame for the Latin of the line, instead of the style's


@dataclasses.dataclass
class Cue:
    id: str
    start: float                     # seconds in the video
    end: float
    x: str
    y: str
    anim: str
    lines: List[LineSpec]
    enter: float = ENTER
    exit: float = EXIT


@dataclasses.dataclass
class Sheet:
    fps: fractions.Fraction
    size: Tuple[int, int]
    palette: str
    cues: List[Cue]


def parse_fps(value):
    """frames per second as a fraction: 30, 29.97 or "30000/1001" (what ffprobe prints)"""
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError
        fps = fractions.Fraction(str(value) if isinstance(value, float) else value)
    except (ValueError, ZeroDivisionError):
        raise ValueError("fps must be a number or a fraction like 30000/1001, not %r" % (value,)) from None
    if fps <= 0:
        raise ValueError("fps must be above 0, not %r" % (value,))
    return fps


def _frame_size(value):
    ok = (isinstance(value, (list, tuple)) and len(value) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in value))
    if not ok:
        raise ValueError("size must be [width, height] in pixels, not %r" % (value,))
    return (value[0], value[1])


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _only(raw, allowed, what):
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ValueError("%s: unknown key %s (known: %s)" % (what, ", ".join(unknown), ", ".join(allowed)))


def _parse_cue(raw, index, old):
    cue_id = "c%02d" % index                 # what a cue without an id is called; the old format has none
    if not isinstance(raw, dict):
        raise ValueError("cue %s is not an object: %r" % (cue_id, raw))
    if "id" in raw:
        if not isinstance(raw["id"], str) or not ID_PATTERN.match(raw["id"]):
            raise ValueError("cue %s: the id %r must be letters, digits, _ or - (it names a folder)" % (cue_id, raw["id"]))
        cue_id = raw["id"]
    what = "cue %s" % cue_id
    _only(raw, CUE_KEYS + (("fontsize",) if old else ()), what)

    def choice(key, allowed, default, renamed=None):
        value = raw.get(key, default)
        if renamed and isinstance(value, str):
            value = renamed.get(value, value)
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("%s: unknown %s %r (known: %s)" % (what, key, raw.get(key), ", ".join(allowed)))
        return value

    def seconds(key, default=None, least=0.0):
        value = raw.get(key, default)
        if not _number(value) or value < least:
            raise ValueError("%s: %s must be a number of seconds, %g or more, not %r" % (what, key, least, value))
        return float(value)

    def line(spec, style_default, size_default, where):
        if not isinstance(spec, dict):
            raise ValueError("%s: %s is not an object: %r" % (what, where, spec))
        _only(spec, LINE_KEYS, "%s %s" % (what, where))
        style = spec.get("style", style_default)
        if old and isinstance(style, str):
            style = OLD_STYLES.get(style, style)
        if not isinstance(style, str) or style not in STYLES:
            raise ValueError("%s: unknown style %r (known: %s)" % (what, spec.get("style", style_default), ", ".join(STYLES)))
        size = spec.get("size", size_default)
        if size is not None and (not _number(size) or size <= 0):
            raise ValueError("%s: size must be a number of pixels above 0, not %r" % (what, size))
        text = spec.get("text")
        if not isinstance(text, str):
            raise ValueError("%s: %s has no text" % (what, where))
        return [LineSpec(part, style, size) for part in text.split("\n") if part.strip()]

    start, end = seconds("start"), seconds("end")
    if not end > start:
        raise ValueError("%s: end (%g) must be after start (%g)" % (what, end, start))
    if "lines" in raw:
        if "text" in raw or "style" in raw or "size" in raw:
            raise ValueError('%s: has "lines", so text, style and size belong to each line' % what)
        if not isinstance(raw["lines"], list):
            raise ValueError("%s: lines must be a list" % what)
        lines = [piece for i, spec in enumerate(raw["lines"]) for piece in line(spec, DEFAULT_STYLE, None, "line %d" % i)]
    else:
        spec = {key: raw[key] for key in ("text", "style") if key in raw}
        lines = line(spec, DEFAULT_STYLE, raw.get("size", raw.get("fontsize") if old else None), "the cue")
    if not lines:
        raise ValueError("%s: no text to draw" % what)
    return Cue(cue_id, start, end, choice("x", X_ANCHORS, DEFAULT_X), choice("y", Y_ANCHORS, DEFAULT_Y),
               choice("anim", ANIMS, DEFAULT_ANIM, OLD_ANIMS if old else None), lines,
               seconds("enter", ENTER), seconds("exit", EXIT))


def parse_cues(data):
    """the cue file as a Sheet.  An object is the format of the module docstring; a bare list is the format of
    the older tools/overlay_text.py, whose style and anim names are mapped (OLD_STYLES, OLD_ANIMS)."""
    old = isinstance(data, list)
    if old:
        data = {"cues": data}
    if not isinstance(data, dict) or not isinstance(data.get("cues"), list):
        raise ValueError('a cue file is {"cues": [...]} or a bare list of cues')
    _only(data, SHEET_KEYS, "the cue file")
    palette = data.get("palette", DEFAULT_PALETTE)
    if not isinstance(palette, str) or palette not in PALETTES:
        raise ValueError("unknown palette %r (known: %s)" % (palette, ", ".join(PALETTES)))
    sheet = Sheet(parse_fps(data.get("fps", FPS)), _frame_size(data.get("size", list(SIZE))), palette, [])
    for index, raw in enumerate(data["cues"]):
        cue = _parse_cue(raw, index, old)
        if any(cue.id == other.id for other in sheet.cues):
            raise ValueError("cue %s: the id is used twice (it names the cue's folder)" % cue.id)
        sheet.cues.append(cue)
    return sheet


def load_cues(path):
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError("%s is not JSON: %s" % (path, e)) from None
    return parse_cues(data)
