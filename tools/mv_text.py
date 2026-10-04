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
RISE = (24.0, -12.0)                         # px: where "rise" starts below its place, where it leaves above it
TRACKING_IN = (0.6, 0.1)                     # em: how far "tracking-in" starts spread, and spreads again leaving
WIPE_EDGE = 24.0                             # px: the soft edge of "wipe"
FLASH = (1.0, 0.0, 1.0, 0.35, 1.0)           # the alpha of the first frames of "flash"; full after them
# "left-third" and "right-third" centre the block on a quarter and on three quarters of the width: beside
# the dancer, who stands in the middle (a lyric in the centre of the lower third lands on the legs)
X_ANCHORS = ("left", "center", "right", "left-third", "right-third")
Y_ANCHORS = ("top", "middle", "lower", "bottom")
# in front of the dancer or behind: this tool lays both over the video in the order of the list; a tool
# that has the dancer as a layer of its own puts the "back" cues under her
LAYERS = ("front", "back")
PALETTES = {
    # white text and an amber accent for a black stage (glow and light effects need the black)
    "dark": {"text": (245, 245, 248), "accent": (240, 160, 48), "secondary": (172, 172, 174), "ink": (22, 22, 30),
             "stage": (0, 0, 0)},
    # ink on the white stage MMD draws by default; white text would vanish there
    "light": {"text": (22, 22, 30), "accent": (240, 160, 48), "secondary": (120, 120, 130), "ink": (22, 22, 30),
              "stage": (255, 255, 255)},
}
DEFAULT_PALETTE = "dark"
DEFAULT_STYLE, DEFAULT_ANIM, DEFAULT_X, DEFAULT_Y, DEFAULT_LAYER = "lyric", "fade", "center", "lower", "front"
# the names of the older tools/overlay_text.py, read in a bare list of cues
OLD_STYLES = {"title": "logo", "lyric": "lyric", "credit": "credit", "caption": "sub"}
OLD_ANIMS = {"fade": "fade", "slide-up": "rise", "slide-left": "rise"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
SHEET_KEYS = ("fps", "size", "palette", "cues", "note")
CUE_KEYS = ("id", "start", "end", "x", "y", "anim", "layer", "text", "style", "size", "lines", "enter", "exit", "note")
LINE_KEYS = ("text", "style", "size")

# ---- the layout -----------------------------------------------------------------------------
# All px below are those of a frame REFERENCE_HEIGHT high and scale with the frame height.
REFERENCE_HEIGHT = 720
MARGIN = (64, 48)                            # px kept free at the left and right, at the top and bottom
LINE_GAP = 0.35                              # em of the larger neighbour, from the bottom of a line to the next top
LOWER = 5.0 / 6.0                            # "lower": the block is centred on the middle of the lower third
X_CENTRES = {"center": 0.5, "left-third": 0.25, "right-third": 0.75}
REFERENCE = {"latin": "H", "jp": "国"}   # the letters whose ink gives a line its top and its bottom
UNDERLINE = {"width": 0.6, "height": 2.0, "gap": 0.2}       # of the text width; px; em under the last line
INK_COPY = 3.0                               # px: how far left of the text its ink copy sits
SHADOW = {"colour": (0, 0, 0), "alpha": 170, "blur": 6.0, "offset": 2.0}     # px: blur radius, how far down
BLUR_REACH = 3.0                             # Pillow's GaussianBlur(r) reaches about 2.6 r past its source (measured)
CANVAS_PAD = 8                               # px (not scaled) around everything a cue draws


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
    shadow: bool = False         # a soft dark copy under the text (SHADOW), for text that lies on the picture


# Sizes are px in a 720 high frame and scale with the frame height.  A style the design gives one script
# only gets the other at the same size and a weight to match (a Japanese title in "logo" is Noto Black);
# "jp" as the Latin role means Noto draws the Latin of that style too.
STYLES = {
    "logo": Style("logo", 150, 150, 900, 0.02, "text"),
    "title_jp": Style("jp", 44, 44, 900, 0.0, "text"),
    "sub": Style("latin", 30, 30, 700, 0.25, "accent", upper=True),
    "credit": Style("latin", 22, 24, 400, 0.12, "secondary"),
    "lyric": Style("jp", 46, 46, 700, 0.0, "text", underline=True, shadow=True),
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
        self._boxes = {}

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

    def reference(self, font, script):
        """(top, bottom) of a line set in this face, relative to its baseline (up is negative), from the ink
        of one letter: a capital for Latin, which stands on the baseline, and the body of a kanji for
        Japanese.  The same for every text, so lines of one style sit alike whatever they say."""
        key = (id(font), script)
        if key not in self._boxes:
            _, top, _, bottom = font.getbbox(REFERENCE[script], anchor="ls")
            self._boxes[key] = (float(top), float(bottom) if script == "jp" else 0.0)
        return self._boxes[key]


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
    layer: str = DEFAULT_LAYER


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
               seconds("enter", ENTER), seconds("exit", EXIT), choice("layer", LAYERS, DEFAULT_LAYER))


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


# ---- motion ---------------------------------------------------------------------------------

@dataclasses.dataclass
class State:
    """how a cue is drawn at one moment"""
    alpha: float = 1.0
    dx: float = 0.0                  # px, to the right
    dy: float = 0.0                  # px, down
    tracking_extra: float = 0.0      # em added after every character
    wipe: float = 1.0                # the share of the block shown, from the left
    underline: float = 1.0           # the share of a lyric's underline drawn


def _progress(elapsed, duration):
    """0 to 1 over `duration` seconds; a duration of 0 is done as soon as it starts"""
    if duration <= 0.0:
        return 1.0 if elapsed >= 0.0 else 0.0
    return min(1.0, max(0.0, elapsed / duration))


def ease_out(p):
    """cubic: fast at first, settling"""
    return 1.0 - (1.0 - p) ** 3


def ease_in(p):
    """cubic: slow at first, leaving fast"""
    return p ** 3


@dataclasses.dataclass
class Motion:
    """the anim of one cue.  `start` and `end` are the times of its first frame and of the frame after its
    last; `scale` is the frame height over 720 (the px of RISE are those of a 720 high frame); `roll` is the
    offset "roll" starts and ends at, which only the layout knows."""
    anim: str
    start: float
    end: float
    enter: float = ENTER
    exit: float = EXIT
    fps: float = float(FPS)
    scale: float = 1.0
    roll: Tuple[float, float] = (0.0, 0.0)

    def at(self, t):
        """the State at the time t (seconds in the video)"""
        came = ease_out(_progress(t - self.start, self.enter))
        gone = ease_in(_progress(t - (self.end - self.exit), self.exit))
        if self.anim == "flash":
            frame = int(round((t - self.start) * self.fps))
            return State(alpha=FLASH[frame] if 0 <= frame < len(FLASH) else 1.0)
        if self.anim == "roll":
            share = _progress(t - self.start, self.end - self.start)
            return State(dy=self.roll[0] + (self.roll[1] - self.roll[0]) * share)
        if self.anim == "wipe":
            return State(alpha=1.0 - gone, wipe=came, underline=came)
        state = State(alpha=min(came, 1.0 - gone), underline=came)
        if self.anim == "rise":
            state.dy = self.scale * (RISE[0] * (1.0 - came) + RISE[1] * gone)
        elif self.anim == "tracking-in":
            state.tracking_extra = TRACKING_IN[0] * (1.0 - came) + TRACKING_IN[1] * gone
        return state

    def extents(self):
        """(least dy, greatest dy, greatest tracking_extra) over the whole cue: what the canvas must hold"""
        if self.anim == "rise":
            return (self.scale * RISE[1], self.scale * RISE[0], 0.0)
        if self.anim == "tracking-in":
            return (0.0, 0.0, max(TRACKING_IN))
        if self.anim == "roll":
            return (float(min(self.roll)), float(max(self.roll)), 0.0)
        return (0.0, 0.0, 0.0)


# ---- layout ---------------------------------------------------------------------------------

@dataclasses.dataclass
class Glyph:
    char: str
    script: str                  # "latin" or "jp": which reference letter gives its line its top and bottom
    font: object                 # the Pillow face that draws it
    size: int                    # px: the em its tracking is counted in
    advance: float               # px to the next character, before tracking
    tracking: float              # em
    ink: Optional[Tuple[int, int, int, int]]     # what it sets, from its origin on the baseline; None: nothing


@dataclasses.dataclass
class Line:
    glyphs: List[Glyph]
    style: Style
    colour: Tuple[int, int, int]
    size: int                    # px: the largest em in the line, which the gaps around it are counted in
    width: float                 # at rest: from the first origin to the end of the last advance
    top: float                   # of its reference box, from the baseline (negative: above it)
    bottom: float
    baseline: float = 0.0        # y in the reference box of the block


def _line_width(line, extra):
    """the width of a line with `extra` em more after every character but the last"""
    return line.width + extra * sum(g.size for g in line.glyphs[:-1])


def _aligned(free, align):
    """where something starts that leaves `free` px of its row: on the side the block is anchored to"""
    return {"left": 0.0, "center": free / 2.0, "right": free}[align]


def _line_x(line, extra, align, width):
    """where a line starts in a reference box `width` wide; spread letters close in towards the anchored side"""
    return _aligned(width - _line_width(line, extra), align)


@dataclasses.dataclass
class Layout:
    """A cue laid out in a frame.  The reference box is its lines at rest: as wide as the widest line, from
    the top of the first line to the bottom of the last (or of the underline).  The block is the reference
    box grown to hold all the ink (a descender, a glitch letter taller than the capitals, the ink copy);
    the anchors place the block.  The canvas is the block through all of its motion, with padding, cut at
    the frame: the picture drawn for every frame of the cue."""
    cue: Cue
    lines: List[Line]
    align: str                   # "left", "center" or "right"
    width: float                 # of the reference box
    origin: Tuple[int, int]      # of the reference box, inside the block
    block: Tuple[int, int]       # width, height
    anchor: Tuple[int, int]      # the top left of the block in the frame
    canvas_origin: Tuple[int, int]               # in the frame: where ffmpeg lays the pictures
    canvas: Tuple[int, int]
    motion: Motion
    start_frame: int
    frames: int
    scale: float                 # the frame height over REFERENCE_HEIGHT
    palette: dict
    underline: Optional[Tuple[float, float, float, int]]     # x, y, width, height in the reference box
    warnings: List[str]

    def line_width(self, line, extra=0.0):
        return _line_width(line, extra)

    def line_x(self, line, extra=0.0):
        return _line_x(line, extra, self.align, self.width)


def frame_of(seconds, fps):
    """the frame a time falls on: the nearest"""
    return int(round(fractions.Fraction(seconds) * fps))


def fps_text(fps):
    """30 or 30000/1001: the rate as ffmpeg takes it"""
    return str(fps.numerator) if fps.denominator == 1 else "%d/%d" % (fps.numerator, fps.denominator)


def _glyphs(text, style, factor, book, warnings, what):
    """the characters of a line with the face that draws each: Japanese from the Japanese font, the rest from
    the Latin face of the style, or from the Japanese font as well where that face lacks the character (the
    Y1 faces have little punctuation; the box a face draws for what it lacks must not reach the video)"""
    latin_px = max(1, int(round(style.latin_size * factor)))
    jp_px = max(1, int(round(style.jp_size * factor)))
    latin, jp = book.font(style.latin, latin_px, style.weight), book.font("jp", jp_px, style.weight)
    out = []
    for script, part in runs(text):
        for ch in part:
            font, px, tracking = (latin, latin_px, style.tracking) if script == "latin" else (jp, jp_px, 0.0)
            if font is not jp and not book.has_glyph(font, ch):
                _warn(warnings, "%s: %s has no glyph for %r (U+%04X), it is drawn with %s"
                      % (what, os.path.basename(font.path), ch, ord(ch), os.path.basename(jp.path)))
                font, px = jp, jp_px
            if not book.has_glyph(font, ch):
                _warn(warnings, "%s: no font here has a glyph for %r (U+%04X), it is drawn as an empty box"
                      % (what, ch, ord(ch)))
            box = font.getbbox(ch, anchor="ls")
            ink = tuple(int(v) for v in box) if box[2] > box[0] and box[3] > box[1] else None
            out.append(Glyph(ch, script, font, px, float(font.getlength(ch)), tracking, ink))
    return out


def _width(glyphs):
    return sum(g.advance + g.tracking * g.size for g in glyphs) - glyphs[-1].tracking * glyphs[-1].size


def _line(spec, index, scale, palette, book, safe, warnings, what):
    """a line of a cue set in its style.  A line wider than the `safe` px between the margins is set smaller
    until it fits (the headline face is wide: eight letters at 150 px are 1228 px in a 1280 px frame)."""
    style = STYLES[spec.style]
    text = spec.text.upper() if style.upper else spec.text
    factor = wanted = scale * (spec.size / style.latin_size if spec.size else 1.0)
    glyphs = _glyphs(text, style, factor, book, warnings, what)
    while _width(glyphs) > safe and max(g.size for g in glyphs) > 1:
        factor *= min(safe / _width(glyphs), 0.99)
        glyphs = _glyphs(text, style, factor, book, warnings, what)
    size = max(g.size for g in glyphs)
    if factor != wanted:
        _warn(warnings, "%s: line %d does not fit the %d px between the margins, it is drawn at %d %% of its size (%d px)"
              % (what, index, safe, int(round(100.0 * factor / wanted)), size))
    boxes = [book.reference(g.font, g.script) for g in glyphs]
    return Line(glyphs, style, palette[style.colour], size, _width(glyphs),
                min(top for top, _ in boxes), max(bottom for _, bottom in boxes))


def _anchor(cue, block, frame, margin, warnings, what):
    """the top left of the block in the frame"""
    (bw, bh), (width, height), (mx, my) = block, frame, margin
    if cue.x == "left":
        x = mx
    elif cue.x == "right":
        x = width - mx - bw
    else:
        x = int(round(width * X_CENTRES[cue.x] - bw / 2.0))
    x = max(mx, min(x, width - mx - bw))                 # a third stops at the margin
    if bw > width - 2 * mx:                              # ink beyond a line that fills the width: shared by both sides
        x = int(round((width - bw) / 2.0))
    y = {"top": my, "bottom": height - my - bh, "middle": int(round((height - bh) / 2.0)),
         "lower": int(round(height * LOWER - bh / 2.0))}[cue.y]
    y = max(my, min(y, height - my - bh))
    if bh > height - 2 * my:
        y = int(round((height - bh) / 2.0))
        if cue.anim != "roll":                           # a roll is as long as it likes: it passes through
            _warn(warnings, "%s: the block is %d px high, more than the %d px between the margins"
                  % (what, bh, height - 2 * my))
    return (x, y)


def layout_cue(cue, sheet, book):
    """lay a cue out in the frame of the sheet (see Layout)"""
    width, height = sheet.size
    scale = height / float(REFERENCE_HEIGHT)
    margin_x, margin_y = (int(round(m * scale)) for m in MARGIN)
    what = "cue %s" % cue.id
    start_frame, end_frame = frame_of(cue.start, sheet.fps), frame_of(cue.end, sheet.fps)
    if end_frame <= start_frame:
        raise ValueError("%s: %g s to %g s is less than one frame at %s fps" % (what, cue.start, cue.end, fps_text(sheet.fps)))
    warnings, palette = [], PALETTES[sheet.palette]
    lines = [_line(spec, i, scale, palette, book, width - 2 * margin_x, warnings, what) for i, spec in enumerate(cue.lines)]

    # the reference box.  Lines sit on whole pixels: text at rest on a fraction of a pixel has blurred stems.
    y = 0.0
    for above, line in zip([None] + lines, lines):
        if above is not None:
            y += round(LINE_GAP * max(above.size, line.size))
        line.baseline = y - line.top
        y = line.baseline + line.bottom
    align = cue.x if cue.x in ("left", "right") else "center"
    ref_width = max(line.width for line in lines)
    underline = None
    if lines[-1].style.underline:
        rule_width = UNDERLINE["width"] * ref_width
        underline = (_aligned(ref_width - rule_width, align), y + round(UNDERLINE["gap"] * lines[-1].size), rule_width,
                     max(1, int(round(UNDERLINE["height"] * scale))))
        y = underline[1] + underline[3]

    # the block: the reference box and all the ink at rest
    copy = max(1, int(round(INK_COPY * scale)))
    x0, y0, x1, y1 = 0.0, 0.0, ref_width, y
    for line in lines:
        x = _line_x(line, 0.0, align, ref_width)
        for g in line.glyphs:
            if g.ink is not None:
                x0 = min(x0, x + g.ink[0] - (copy if line.style.ink_copy else 0))
                y0 = min(y0, line.baseline + g.ink[1])
                x1, y1 = max(x1, x + g.ink[2]), max(y1, line.baseline + g.ink[3])
            x += g.advance + g.tracking * g.size
    origin = (-int(math.floor(x0)), -int(math.floor(y0)))
    block = (int(math.ceil(x1)) + origin[0], int(math.ceil(y1)) + origin[1])
    anchor = _anchor(cue, block, sheet.size, (margin_x, margin_y), warnings, what)

    # the motion runs on the frame grid: its first frame is exactly its start
    motion = Motion(cue.anim, float(start_frame / sheet.fps), float(end_frame / sheet.fps), cue.enter, cue.exit,
                    float(sheet.fps), scale)
    if cue.anim == "roll":                               # from just under the frame to just over it
        motion.roll = (float(height - anchor[1]), -float(anchor[1] + block[1]))

    # the canvas: the block wherever the motion takes it, the letters as far as they spread, the shadow's blur
    dy_min, dy_max, extra = motion.extents()
    grow_left = grow_right = 0.0
    for line in (lines if extra else ()):
        x = _line_x(line, extra, align, ref_width)
        grow_left, grow_right = max(grow_left, -x), max(grow_right, x + _line_width(line, extra) - ref_width)
    pad = CANVAS_PAD
    if any(line.style.shadow for line in lines):
        pad = max(pad, int(math.ceil(BLUR_REACH * SHADOW["blur"] * scale)) + int(math.ceil(SHADOW["offset"] * scale)))
    left = max(0, anchor[0] - int(math.ceil(grow_left)) - pad)
    top = max(0, anchor[1] + int(math.floor(min(0.0, dy_min))) - pad)
    right = min(width, anchor[0] + block[0] + int(math.ceil(grow_right)) + pad)
    bottom = min(height, anchor[1] + block[1] + int(math.ceil(max(0.0, dy_max))) + pad)
    canvas = (max(1, right - left), max(1, bottom - top))
    return Layout(cue, lines, align, ref_width, origin, block, anchor, (left, top), canvas, motion, start_frame,
                  end_frame - start_frame, scale, palette, underline, warnings)
