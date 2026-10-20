"""The motion graphics of the MV: the look's "mograph" section (tools/mv_look.py), what an editor lays on the picture and
between the shots, placed on the song's structure.

    python tools/mograph_layer.py plan STRUCTURE.json OUT.json [--look LOOK.json] [--level L]
        the look (LOOK.json's, or one of this section alone) with its "mograph" section placed from the song's structure
        (looks/song_structure.json of the stage-6 work: beats, sections, title words, landings) by the rules of `plan`.  The
        events are a table to edit by hand: add, move or drop one and mv_look draws what the table says
    python tools/mograph_layer.py frame LOOK.json OUT.png --frame N --camera CAMERA.vmd [--size 1280x720]
        the particles of one frame of the song over a grey card (left: behind the dancer, right: in front of her), to look at
    python tools/mograph_layer.py apply VIDEO LOOK.json OUT.mp4 [--from S] [--to S] [--offset S]
        the section's punches, shakes, glitches, dissolves, fades and flashes laid over a finished video (not the particles:
        they go between the stage and the dancer), to measure them with tools/mograph_analyze.py or to look at them
    python tools/mograph_layer.py draw JOB.json         (write_particles with jobs runs these)

Why (2026-10-21, mograph): the motion graphics of the channel @PizaCG, measured by tools/mograph_analyze.py over nine of its
videos (the median [quartiles], as the review typorev corrected them): zoom punches 2.5 [1.7, 5.1] a minute (about 2 by eye,
most of them the MMD camera's own quick zooms), flashes 0.80 [0, 1.69] a minute (stage LEDs and lasers among them: the
editor's white flashes are fewer), a shake of 1.41 [1.26, 1.93] px (the fast motion of a frame, 720 line px), fades 0.76
[0.58, 1.17] and dissolves 0.39 [0, 1.42] a minute, cuts 24.6 a minute that come 0.077 s (2.3 frames) before the beat in five of
the nine.  The counts of glitch frames and of particles are no targets (the measure misses glitches in colourful pictures and
counts the lyrics, windows and signs as particles): glitches few, particles restrained, by eye, never over the dancer.  Our
v11 r2 had none of these.

The section (DEFAULTS: the look's values override them; an unknown name or a value of the wrong kind is an error):
  on          1 draws it.  0 (the default) draws nothing: the look's ffmpeg argv is the one of before, byte for byte
  punch       the picture zooms in by `amount` about `centre` (x, y of the picture, 0..1: the point that stays put)
              within `rise` frames of the song and eases back over `fall`
  shake       the picture jolts by `amount` px (of a 720 line picture) and rings at `hz` for `frames`, dying away; it is
              zoomed in as far as the jolt reaches, so that its edges never show
  flash       the picture lifts towards `colour` by `strength` (0..1 of the way) on its first frame and falls back over
              `frames`
  fade        the picture goes to `colour` over `out` frames, stays `hold` (-1: to the end) and comes back over `back`
  dissolve    the picture of the frame before it stays and fades out over the moving picture over `frames`
  glitch      for `frames` frames red and blue part by twice `split` px and `bands` bands of the picture slide by up to `shift`
  particles   `specks` small specks in the air round the dancer (`box`: x0 y0 z0 x1 y1 z1, MMD units: near the focus, sharp)
              and `lights` soft lights far behind her (`light_box`: blurred into bokeh), drifting by `drift` units a second.  They lie in the world (the camera moves past them as past the stage) and
              blur by their distance from the focus as stage.dof blurs the stage; those nearer the camera than the dancer go in
              front of her, the rest behind (`front` caps the cover of one in front).  `clear` keeps a column of that radius
              round the dancer's place free.  They need stage.world 1
  busy        [[from, to, level], ...]: over those seconds of the song as many particles as `level` times the number (1
              elsewhere; one second to change)
  events      [{"kind": punch|shake|flash|fade|dissolve|glitch, "t": seconds of the song, any value of the kind's section,
              "note": why}, ...]

Frames of the song are MMD's, 30 a second (mv_look's flare.frames): a video at 60 fps has the effects for as many seconds.
An event's frame is round(t x fps) of the video, so a render in chunks draws on every frame what the whole song draws there.

In mv_look's picture: the particles behind the dancer over the stage (before the text behind her), those in front over her
and her glow; the punches, shakes, glitches and dissolves after the camera's punch of a flare and before the lens; the fades
and the flashes after the lens, under the text in front.
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
SONG_FPS = 30                    # the frames the section counts in: MMD's, of the song (mv_look.SONG_FPS)
REFERENCE_HEIGHT = 720.0         # lengths are pixels of a 720 line picture (mv_look)
KINDS = ("punch", "shake", "flash", "fade", "dissolve", "glitch")
DEFAULTS = {
    "on": 0,
    "punch": {"amount": 0.10, "rise": 2, "fall": 10, "centre": [0.5, 0.45]},
    "shake": {"amount": 5.0, "frames": 10, "hz": 9.0},
    # (9 frames: 4 of them over 0.10 of Y' on the city at night, as tools/mograph_analyze.py reads a flash; the references'
    # last 0.119 s, 3.6 frames.  7 gave 2 on window A of the previews)
    "flash": {"strength": 0.27, "frames": 9, "colour": [255, 255, 255]},
    "fade": {"out": 12, "hold": 2, "back": 15, "colour": [0, 0, 0]},
    "dissolve": {"frames": 12},
    # (split 14: red and blue 28 px apart, which tools/mograph_analyze.py reads at its 128 x 72 as the references' glitches;
    # split 6 on v7 read as none, 2026-10-21)
    "glitch": {"frames": 2, "split": 14.0, "bands": 3, "shift": 40.0, "seed": 5},
    # (the specks in the air round her, near the focus, sharp; the lights far behind her, low over the street, blurred into
    # bokeh by stage.dof.  One box for both, 2026-10-21's first try, blurred nearly all of them; a speck box 54 deep put a third
    # of them out of focus, and a light box up to 50 high lay above the frame of the front camera, which looks down on her:
    # 9 of 40 in the picture)
    "particles": {"specks": 0, "lights": 0, "seed": 9, "brightness": 1.0, "size": 1.0, "drift": [0.25, 0.06, 0.0],
                  "box": [-34.0, 0.5, -16.0, 34.0, 30.0, 14.0], "light_box": [-70.0, 0.5, 40.0, 70.0, 22.0, 150.0],
                  "clear": 9.0, "front": 0.35},
    "busy": [],
    "events": [],
}
LIMITS = {"punch.amount": (0.0, 0.5), "shake.amount": (0.0, 40.0), "shake.hz": (0.1, 14.9), "flash.strength": (0.0, 1.0),
          "glitch.split": (0.0, 40.0), "glitch.shift": (0.0, 200.0), "particles.brightness": (0.0, 4.0),
          "particles.size": (0.05, 10.0), "particles.front": (0.0, 1.0), "particles.clear": (0.0, 100.0)}
WHOLE = {"punch.rise": 1, "punch.fall": 1, "shake.frames": 1, "flash.frames": 1, "fade.out": 0, "fade.hold": -1,
         "fade.back": 0, "dissolve.frames": 1, "glitch.frames": 1, "glitch.bands": 0, "glitch.seed": 0,
         "particles.specks": 0, "particles.lights": 0, "particles.seed": 0}
MARGIN = 1.15                    # a shake's zoom covers this many times its reach (bilinear sampling needs a pixel more)
FRONT_GAP = 2.0                  # MMD units: a particle this much nearer the camera than the dancer's place is in front
NEAR_FADE = (3.0, 8.0)           # MMD units from the eye: none nearer than the first, all of it past the second
EDGE_FADE = 3.0                  # MMD units: particles fade within this of the box's faces (they wrap round there)
SPRITE_LEAST = 0.6               # px: the least spread (a standard deviation) of a particle on the picture
BUSY_RAMP = 1.0                  # s: a busy span's level comes and goes over this
DEFAULT_SHAKE_RATIO = (0.6, 1.37)   # the vertical jolt: this share of the horizontal one, ringing this many times as fast
ARGV_MOST = 30000                # characters: a longer ffmpeg command goes past Windows' command line (32767)
CUT_LEAD = 0.077                 # s: a change of picture at a section's start comes this much before its first beat, as the
                                 # references' cuts do (five of nine, [0.034, 0.108]: typorev)
# the plan's particles: restrained, by eye (their count is no target: typorev), and a little busier over the interludes
PLAN_PARTICLES = {"specks": 100, "lights": 24}
PLAN_BUSY = 1.3


# ---- the section ---------------------------------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _value(name, value, default):
    """`value` checked against the kind of `default` (a number, or a list of numbers as long) and its LIMITS and WHOLE"""
    if isinstance(default, list):
        if not isinstance(value, list) or len(value) != len(default) or not all(_is_number(v) for v in value):
            raise ValueError("mograph.%s is a list of %d numbers, not %r" % (name, len(default), value))
    elif not _is_number(value):
        raise ValueError("mograph.%s is a number, not %r" % (name, value))
    if name in LIMITS and not LIMITS[name][0] <= value <= LIMITS[name][1]:
        raise ValueError("mograph.%s is %g to %g, not %r" % (name, LIMITS[name][0], LIMITS[name][1], value))
    if name in WHOLE and (int(value) != value or value < WHOLE[name]):
        raise ValueError("mograph.%s is a whole number from %d, not %r" % (name, WHOLE[name], value))
    if name.endswith("colour") and not all(0 <= c <= 255 for c in value):
        raise ValueError("mograph.%s is r, g, b of 0 to 255, not %r" % (name, value))
    if name == "punch.centre" and not all(0.0 <= c <= 1.0 for c in value):
        raise ValueError("mograph.punch.centre is x, y of the picture, 0 to 1: not %r" % (value,))
    return int(value) if name in WHOLE else value


def _event(e, i):
    if not isinstance(e, dict):
        raise ValueError("mograph.events[%d] is an object {\"kind\", \"t\", ...}, not %r" % (i, e))
    kind = e.get("kind")
    if kind not in KINDS:
        raise ValueError("mograph.events[%d].kind is one of %s, not %r" % (i, ", ".join(KINDS), kind))
    t = e.get("t")
    if not _is_number(t) or t < 0:
        raise ValueError("mograph.events[%d].t is the time in seconds of the song, from 0: not %r" % (i, t))
    out = {"kind": kind, "t": float(t)}
    for key, value in e.items():
        if key in ("kind", "t"):
            continue
        if key == "note":
            if not isinstance(value, str):
                raise ValueError("mograph.events[%d].note is text, not %r" % (i, value))
            out["note"] = value
            continue
        if key not in DEFAULTS[kind]:
            raise ValueError("mograph.events[%d] (%s) has no setting %r (it has: %s)" % (i, kind, key,
                                                                                   ", ".join(sorted(DEFAULTS[kind]))))
        out[key] = _value("%s.%s" % (kind, key), value, DEFAULTS[kind][key])
    return out


def merge(overrides):
    """DEFAULTS with the values of `overrides` (the look's "mograph") put over them; unknown names and values of the wrong
    kind are errors, and so is a value that would draw nothing (anything but the defaults while "on" is 0)"""
    section = copy.deepcopy(DEFAULTS)
    if not isinstance(overrides, dict):
        raise ValueError("mograph is an object, not %r" % (overrides,))
    for name, value in overrides.items():
        if name not in section:
            raise ValueError("mograph has no setting %r (it has: %s)" % (name, ", ".join(sorted(section))))
        if name == "events":
            if not isinstance(value, list):
                raise ValueError("mograph.events is a list of events, not %r" % (value,))
            section["events"] = sorted((_event(e, i) for i, e in enumerate(value)), key=lambda e: (e["t"], KINDS.index(e["kind"])))
        elif name == "busy":
            section["busy"] = _busy(value)
        elif name == "on":
            if value not in (0, 1) or isinstance(value, bool):
                raise ValueError("mograph.on is 0 or 1, not %r" % (value,))
            section["on"] = int(value)
        else:
            if not isinstance(value, dict):
                raise ValueError("mograph.%s is an object, not %r" % (name, value))
            for key, v in value.items():
                if key not in section[name]:
                    raise ValueError("mograph.%s has no setting %r (it has: %s)" % (name, key, ", ".join(sorted(section[name]))))
                section[name][key] = _value("%s.%s" % (name, key), v, DEFAULTS[name][key])
    for name in ("box", "light_box"):
        box = section["particles"][name]
        if not all(box[k + 3] > box[k] for k in range(3)):
            raise ValueError("mograph.particles.%s is x0, y0, z0, x1, y1, z1 with each end past its start, not %r" % (name, box))
    if not section["on"]:
        changed = sorted(k for k in section if k != "on" and section[k] != DEFAULTS[k])
        if changed:
            raise ValueError("mograph.%s draws motion graphics: it needs mograph.on 1" % changed[0])
    return section


def _busy(spans):
    if not isinstance(spans, list):
        raise ValueError("mograph.busy is a list of [from, to, level], not %r" % (spans,))
    out = []
    for i, s in enumerate(spans):
        if not (isinstance(s, list) and len(s) == 3 and all(_is_number(v) for v in s) and s[1] > s[0] >= 0 and s[2] >= 0):
            raise ValueError("mograph.busy[%d] is [from, to, level]: seconds of the song (to after from) and a level from 0, "
                             "not %r" % (i, s))
        out.append([float(v) for v in s])
    return sorted(out)


def events_of(section):
    """the events with every value of their kind (the section's, put over by the event's own)"""
    out = []
    for e in section["events"]:
        full = copy.deepcopy(section[e["kind"]])
        full.update(e)
        out.append(full)
    return out


def needs_particles(section):
    return bool(section["on"]) and (section["particles"]["specks"] + section["particles"]["lights"]) > 0


def check_look(look):
    """what the rest of the look must be for the section: particles lie in the world (they need stage.world 1)"""
    section = look["mograph"]
    if needs_particles(section) and not look["stage"]["world"]:
        raise ValueError("mograph.particles lie in the world, seen by the camera MMD renders with: they need stage.world 1")


# ---- time ----------------------------------------------------------------------------------------------------------

def song_span(frames, fps):
    """frames of the song (30 a second) as frames of a video at `fps` (a float: an envelope is smooth between them)"""
    return float(frames) * fps / float(SONG_FPS)


def frame_of(seconds, fps):
    """the video frame (from the song's start) of a time of the song: the one an event starts on"""
    return int(round(float(seconds) * fps))


def _n(value):
    """a short decimal for an expression: 4.0 -> 4, 0.125 -> 0.125, -0.0 -> 0"""
    text = ("%.6f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# ---- the envelopes (frame units: x = frames since the event's start) -----------------------------------------------
# Each is a Python function and an ffmpeg expression of the same shape: the expression is what the picture shows, the
# function lets the plan and the tests read it.

def punch_value(x, rise, fall):
    """the share of a punch's amount at x frames after its start: up within `rise` frames (eased out: the first frame is
    already most of the way), then back over `fall` (a cosine)"""
    if x < 0 or x >= rise + fall - 1:
        return 0.0
    if x < rise:
        return 1.0 - (1.0 - (x + 1.0) / rise) ** 2
    return 0.5 + 0.5 * math.cos(math.pi * (x - rise + 1.0) / fall)


def _punch_expr(X, amount, rise, fall):
    return ("%s*if(lt(%s,0)+gte(%s,%s),0,if(lt(%s,%s),1-pow(1-(%s+1)/%s,2),0.5+0.5*cos(PI*(%s-%s)/%s)))"
            % (_n(amount), X, X, _n(rise + fall - 1), X, _n(rise), X, _n(rise), X, _n(rise - 1), _n(fall)))


def shake_values(x, amount, frames, hz, fps):
    """(dx, dy, margin): the jolt at x frames after the start of a shake, px, and the share of the picture it reaches"""
    if x < 0 or x >= frames:
        return 0.0, 0.0, 0.0
    w = (1.0 - x / float(frames)) ** 2
    dx = amount * w * math.cos(2.0 * math.pi * hz * x / fps)
    dy = DEFAULT_SHAKE_RATIO[0] * amount * w * math.sin(2.0 * math.pi * hz * DEFAULT_SHAKE_RATIO[1] * x / fps)
    return dx, dy, amount * (1.0 - x / float(frames))


def _shake_exprs(X, amount, frames, hz, fps):
    on = "between(%s,0,%s)" % (X, _n(math.ceil(frames) - 1))
    w = "pow(1-%s/%s,2)" % (X, _n(frames))
    dx = "if(%s,%s*%s*cos(%s*%s),0)" % (on, _n(amount), w, _n(2.0 * math.pi * hz / fps), X)
    dy = "if(%s,%s*%s*sin(%s*%s),0)" % (on, _n(DEFAULT_SHAKE_RATIO[0] * amount), w,
                                         _n(2.0 * math.pi * hz * DEFAULT_SHAKE_RATIO[1] / fps), X)
    reach = "if(%s,%s*(1-%s/%s),0)" % (on, _n(amount), X, _n(frames))
    return dx, dy, reach


def flash_value(x, strength, frames):
    if x < 0 or x >= frames:
        return 0.0
    return strength * (1.0 - x / float(frames)) ** 1.5


def _flash_expr(X, strength, frames):
    return "if(between(%s,0,%s),%s*pow(1-%s/%s,1.5),0)" % (X, _n(math.ceil(frames) - 1), _n(strength), X, _n(frames))


def _smooth(u):
    return u * u * (3.0 - 2.0 * u)


def fade_value(x, out, hold, back):
    """the share of the fade's colour at x frames after its start: up over `out` (the frame out - 1 at 1), `hold` frames at
    1 (-1: for ever), down over `back`"""
    if x < 0:
        return 0.0
    if x < out:
        return _smooth((x + 1.0) / out)
    if hold < 0 or x < out + hold:
        return 1.0
    if x < out + hold + back:
        return 1.0 - _smooth((x - out - hold + 1.0) / (back + 1.0))
    return 0.0


def _fade_expr(X, out, hold, back):
    up = "1" if out <= 0 else "pow((%s+1)/%s,2)*(3-2*(%s+1)/%s)" % (X, _n(out), X, _n(out))
    if hold < 0:
        rest = "1"
    else:
        down = "0" if back <= 0 else ("if(lt(%s,%s),1-pow((%s-%s)/%s,2)*(3-2*(%s-%s)/%s),0)"
                                      % (X, _n(out + hold + back), X, _n(out + hold - 1), _n(back + 1), X,
                                         _n(out + hold - 1), _n(back + 1)))
        rest = "if(lt(%s,%s),1,%s)" % (X, _n(out + hold), down)
    return "if(lt(%s,0),0,if(lt(%s,%s),%s,%s))" % (X, X, _n(out), up, rest)


def event_frames(e, fps):
    """(first, last) video frames an event draws on, from its own frame (frame_of its time); last None: to the end"""
    first = frame_of(e["t"], fps)
    k = e["kind"]
    if k == "punch":
        n = song_span(e["rise"] + e["fall"] - 1, fps)
    elif k == "shake":
        n = song_span(e["frames"], fps)
    elif k == "flash":
        n = song_span(e["frames"], fps)
    elif k == "fade":
        if e["hold"] < 0:
            return first, None
        n = song_span(e["out"] + e["hold"] + e["back"], fps)
    elif k == "dissolve":
        return first - 1, first + int(math.ceil(song_span(e["frames"], fps))) - 1
    else:
        n = song_span(e["frames"], fps)
    return first, first + max(1, int(math.ceil(n))) - 1


def glitch_frames(e, fps, size):
    """[(frame, split px, [(y0, y1, shift px), ...])] of a glitch, its bands placed by its seed and its frame (the same
    bands on the same frame of the song, whatever the excerpt)"""
    w, h = size
    unit = h / REFERENCE_HEIGHT
    first = frame_of(e["t"], fps)
    out = []
    for j in range(max(1, int(round(song_span(e["frames"], fps))))):
        rng = np.random.default_rng([int(e["seed"]), first + j])
        split = float(e["split"]) * unit * (0.75 + 0.5 * rng.random())
        bands = []
        for _ in range(int(e["bands"])):
            height = h * (0.02 + 0.10 * rng.random())
            y0 = rng.random() * (h - height)
            shift = float(e["shift"]) * unit * (0.3 + 0.7 * rng.random()) * (1 if rng.random() < 0.5 else -1)
            bands.append((y0, y0 + height, shift))
        out.append((first + j, split, bands))
    return out


# ---- the filters of a render ---------------------------------------------------------------------------------------

class Graph:
    """the filters of the section for one render: an excerpt of the song from `clip_start` seconds (`duration`: None to the
    end of the dancer's file) at `fps` and `size`.  `particles` ({"back", "front": printf patterns of the frames numbered
    from the song's start, "first": the excerpt's first}) when the section has particles.  mv_look calls inputs() once,
    then back(), front(), camera() and veils() at their places in its graph; each takes the label of the picture so far
    and gives the label after it (the same label when it adds nothing)"""

    def __init__(self, section, size, fps, clip_start, duration=None, particles=None):
        self.section = section
        self.size = (int(size[0]), int(size[1]))
        self.fps = fps
        self.first = frame_of(clip_start, fps)
        self.count = None if duration is None else max(1, int(round(float(duration) * fps)))
        self.particles = particles
        self.events = [e for e in events_of(section) if self._overlaps(e)]
        self.at = {}
        if needs_particles(section) and not particles:
            raise ValueError("mograph.particles: the render needs the frames of the particles (mograph_layer.write_particles)")
        for e in self.events:
            if e["kind"] == "dissolve":
                held = frame_of(e["t"], fps) - 1 - self.first
                if held < 0:
                    raise ValueError("the dissolve at %.3f s holds the picture of the frame before it, which is not in this "
                                     "excerpt (from %.3f s): start the excerpt before it, or move the dissolve"
                                     % (e["t"], clip_start))

    def _overlaps(self, e):
        a, b = event_frames(e, self.fps)
        a -= self.first
        b = None if b is None else b - self.first
        if b is not None and b < 0:
            return False
        return self.count is None or a < self.count

    def _x(self, e, var):
        """the expression of frames since the event's start, in `var` (the filter's frame number from the excerpt's start)"""
        k = frame_of(e["t"], self.fps) - self.first
        return "(%s%s)" % (var, "-%d" % k if k > 0 else "+%d" % -k if k < 0 else "")

    def _span(self, e):
        a, b = event_frames(e, self.fps)
        a -= self.first
        b = 10 ** 9 if b is None else b - self.first
        return max(0, a), b

    def _enable(self, events, var="n"):
        return "+".join("between(%s,%d,%d)" % (var, a, b) for a, b in (self._span(e) for e in events))

    # inputs: the particles' frames, after mv_look's own inputs
    def inputs(self, next_input):
        argv = []
        if self.particles:
            for side in ("back", "front"):
                argv += ["-framerate", str(self.fps), "-start_number", str(int(self.particles["first"])), "-i",
                         self.particles[side]]
                self.at[side] = next_input
                next_input += 1
        return argv

    def back(self, parts, label):
        return self._lay("back", parts, label)

    def front(self, parts, label):
        return self._lay("front", parts, label)

    def _lay(self, side, parts, label):
        if side not in self.at:
            return label
        parts.append("[%d:v]format=rgba[mg_%s]" % (self.at[side], side))
        parts.append("[%s][mg_%s]overlay=eof_action=pass:format=gbrp[mg_%s_on]" % (label, side, side))
        return "mg_%s_on" % side

    def camera(self, parts, label):
        label = self._transform(parts, label)
        label = self._glitch(parts, label)
        return self._dissolve(parts, label)

    def _transform(self, parts, label):
        moves = [e for e in self.events if e["kind"] in ("punch", "shake")]
        if not moves:
            return label
        w, h = self.size
        unit = h / REFERENCE_HEIGHT
        punch_terms, reach_terms, dxs, dys = [], [], [], []
        px, py = None, None
        centres = sorted({tuple(e["centre"]) for e in moves if e["kind"] == "punch"})
        if len(centres) > 1:
            # one transform a frame: the point that stays put is one for the whole excerpt
            raise ValueError("the punches of one render zoom about one centre, not %s: give them the same punch.centre"
                             % ", ".join("%s" % list(c) for c in centres))
        for e in moves:
            X = self._x(e, "(in-1)")
            if e["kind"] == "punch":
                punch_terms.append(_punch_expr(X, e["amount"], song_span(e["rise"], self.fps), song_span(e["fall"], self.fps)))
                if px is None:
                    px, py = e["centre"][0] * w, e["centre"][1] * h
            else:
                dx, dy, reach = _shake_exprs(X, e["amount"] * unit, song_span(e["frames"], self.fps), e["hz"], self.fps)
                dxs.append(dx)
                dys.append(dy)
                reach_terms.append(reach)
        if px is None:
            px, py = self.section["punch"]["centre"][0] * w, self.section["punch"]["centre"][1] * h
        # the shake's zoom: as far in as the jolt reaches past the nearest edge from the point that stays put
        nearest = max(1.0, min(px, w - px, py, h - py))
        s = "(1+%s)" % "+".join(punch_terms) if punch_terms else "1"
        if reach_terms:
            s += "*(1+%s*(%s))" % (_n(MARGIN / nearest), "+".join(reach_terms))
        dx = "+".join(dxs) or "0"
        dy = "+".join(dys) or "0"
        x0 = "%s-(%s+%s)/(%s)" % (_n(px), _n(px), dx, s)
        x1 = "%s+(%s-%s)/(%s)" % (_n(px), _n(w - px), dx, s)
        y0 = "%s-(%s+%s)/(%s)" % (_n(py), _n(py), dy, s)
        y2 = "%s+(%s-%s)/(%s)" % (_n(py), _n(h - py), dy, s)
        parts.append("[%s]perspective=x0='%s':y0='%s':x1='%s':y1='%s':x2='%s':y2='%s':x3='%s':y3='%s':interpolation=linear:"
                     "eval=frame:enable='%s'[mg_cam]" % (label, x0, y0, x1, y0, x0, y2, x1, y2, self._enable(moves)))
        return "mg_cam"

    def _glitch(self, parts, label):
        glitches = [e for e in self.events if e["kind"] == "glitch"]
        if not glitches:
            return label
        terms_r, terms_b, terms_g = [], [], []
        for e in glitches:
            for frame, split, bands in glitch_frames(e, self.fps, self.size):
                n = frame - self.first
                if n < 0 or (self.count is not None and n >= self.count):
                    continue
                band = "+".join("between(Y,%s,%s)*%s" % (_n(a), _n(b), _n(d)) for a, b, d in bands) or "0"
                terms_g.append("eq(N,%d)*(%s)" % (n, band))
                terms_r.append("eq(N,%d)*(%s+%s)" % (n, _n(split), band))
                terms_b.append("eq(N,%d)*(%s-%s)" % (n, band, _n(split)))
        if not terms_g:
            return label
        parts.append("[%s]geq=r='r(X-(%s),Y)':g='g(X-(%s),Y)':b='b(X-(%s),Y)':enable='%s'[mg_glitch]"
                     % (label, "+".join(terms_r), "+".join(terms_g), "+".join(terms_b), self._enable(glitches)))
        return "mg_glitch"

    def _dissolve(self, parts, label):
        for i, e in enumerate(e for e in self.events if e["kind"] == "dissolve"):
            k = frame_of(e["t"], self.fps) - self.first
            frames = max(1, int(round(song_span(e["frames"], self.fps))))
            fps = _n(self.fps)
            parts += ["[%s]split=2[mg_dm%d][mg_dg%d]" % (label, i, i),
                      "[mg_dg%d]trim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS,loop=loop=%d:size=1:start=0,"
                      "setpts=N/(%s*TB)+%s/TB,format=rgba,fade=t=out:st=%s:d=%s:alpha=1[mg_dh%d]"
                      % (i, k - 1, k, frames - 1, fps, _n(k / float(self.fps)), _n((k - 1) / float(self.fps)),
                         _n((frames + 1) / float(self.fps)), i),
                      "[mg_dm%d][mg_dh%d]overlay=eof_action=pass:format=gbrp[mg_d%d]" % (i, i, i)]
            label = "mg_d%d" % i
        return label

    def veils(self, parts, label):
        """the fades, then the flashes: a picture of one colour over the whole frame whose alpha follows the events (drawn
        1 x 1 and scaled up: its alpha is one number a frame.  Drawn 2 x 2, geq of ffmpeg 8.0 on hinata left one of the four
        pixels unlit from the flash's second frame on, inside mv_look's graph: a quarter of the picture did not flash)"""
        w, h = self.size
        groups = []
        for kind in ("fade", "flash"):
            colours = []
            for e in self.events:
                if e["kind"] == kind and list(e["colour"]) not in colours:
                    colours.append(list(e["colour"]))
            groups += [(kind, c) for c in colours]
        for i, (kind, colour) in enumerate(groups):
            mine = [e for e in self.events if e["kind"] == kind and list(e["colour"]) == colour]
            terms = []
            for e in mine:
                X = self._x(e, "N")
                if kind == "fade":
                    terms.append(_fade_expr(X, song_span(e["out"], self.fps), -1 if e["hold"] < 0 else song_span(e["hold"], self.fps),
                                            song_span(e["back"], self.fps)))
                else:
                    terms.append(_flash_expr(X, e["strength"], song_span(e["frames"], self.fps)))
            r, g, b = (int(round(c)) for c in colour)
            parts += ["color=c=0x%02x%02x%02x:s=1x1:r=%s,format=rgba,geq=r=%d:g=%d:b=%d:a='255*min(1,%s)',"
                      "scale=%d:%d:flags=neighbor[mg_v%d]" % (r, g, b, _n(self.fps), r, g, b, "+".join(terms), w, h, i),
                      "[%s][mg_v%d]overlay=format=gbrp:shortest=1:enable='%s'[mg_veiled%d]" % (label, i, self._enable(mine), i)]
            label = "mg_veiled%d" % i
        return label


def long_argv(argv, path):
    """an ffmpeg argv whose filter graph makes it longer than ARGV_MOST characters, with the graph written to `path` and given
    by -/filter_complex (ffmpeg 7 on); a shorter argv as it is"""
    if sum(len(a) + 3 for a in argv) <= ARGV_MOST or "-filter_complex" not in argv:
        return argv
    i = argv.index("-filter_complex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(argv[i + 1])
    return argv[:i] + ["-/filter_complex", path.replace("\\", "/")] + argv[i + 2:]


# ---- the particles -------------------------------------------------------------------------------------------------

_WORLD = []


def world_tool():
    """tools/mv_world.py (the camera, the thin lens's blur), loaded once from its file"""
    if not _WORLD:
        spec = importlib.util.spec_from_file_location("mv_world", os.path.join(HERE, "mv_world.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _WORLD.append(module)
    return _WORLD[0]


SPECK_COLOURS = ((255.0, 240.0, 214.0), (255.0, 255.0, 255.0), (214.0, 228.0, 255.0))
LIGHT_COLOURS = ((255.0, 196.0, 120.0), (255.0, 160.0, 186.0), (150.0, 214.0, 255.0), (255.0, 228.0, 170.0))


class Field:
    """the particles of a section: where each is at a time of the song, how large, how bright and in what colour.  Every
    one is fixed by the seed: a frame shows the same particles whatever the excerpt or the job that draws it"""

    def __init__(self, section):
        p = section["particles"]
        self.p = p
        self.busy = section["busy"]
        top = max([1.0] + [s[2] for s in self.busy])
        self.base = {"speck": int(p["specks"]), "light": int(p["lights"])}
        counts = {k: int(math.ceil(n * top)) for k, n in self.base.items()}
        rng = np.random.default_rng(int(p["seed"]))
        kinds, ranks = [], []
        for kind in ("speck", "light"):
            kinds += [kind] * counts[kind]
            ranks += list(range(counts[kind]))
        n = len(kinds)
        self.kind = np.array(kinds)
        self.rank = np.array(ranks, float)
        # each particle in its kind's box: the specks in "box", the lights in "light_box"
        boxes = {"speck": np.array(p["box"], float), "light": np.array(p["light_box"], float)}
        self.lo = np.array([boxes[k][:3] for k in kinds]).reshape(n, 3)
        self.size = np.array([boxes[k][3:] - boxes[k][:3] for k in kinds]).reshape(n, 3)
        self.start = self.lo + rng.random((n, 3)) * self.size
        self.velocity = np.array(p["drift"], float)[None, :] * (0.6 + 0.8 * rng.random((n, 1))) + rng.normal(0, 0.05, (n, 3))
        self.sway = rng.random((n, 3)) * 0.4
        self.sway_hz = 0.05 + 0.15 * rng.random((n, 3))
        self.phase = rng.random((n, 3)) * 2.0 * math.pi
        speck = self.kind == "speck"
        # (the lights 0.45 to 0.85 bright: their blur spreads them over 4 to 5 px, and at 0.25 to 0.6 the brightest stood
        # 0.2 over the street, too faint to see as lights; 2026-10-21)
        self.radius = np.where(speck, 0.035 + 0.035 * rng.random(n), 0.20 + 0.25 * rng.random(n)) * float(p["size"])
        self.bright = np.where(speck, 0.35 + 0.6 * rng.random(n), 0.45 + 0.40 * rng.random(n)) * float(p["brightness"])
        self.twinkle_hz = 0.15 + 0.45 * rng.random(n)
        self.twinkle_phase = rng.random(n) * 2.0 * math.pi
        pick = rng.random(n)
        self.colour = np.array([SPECK_COLOURS[int(q * len(SPECK_COLOURS)) % len(SPECK_COLOURS)] if s else
                                LIGHT_COLOURS[int(q * len(LIGHT_COLOURS)) % len(LIGHT_COLOURS)] for s, q in zip(speck, pick)])

    def level(self, seconds):
        """the busy level at a time of the song (1 outside the spans; BUSY_RAMP to change)"""
        level = 1.0
        for a, b, v in self.busy:
            if a - BUSY_RAMP < seconds < b + BUSY_RAMP:
                k = min(1.0, (seconds - (a - BUSY_RAMP)) / BUSY_RAMP, ((b + BUSY_RAMP) - seconds) / BUSY_RAMP)
                level = max(level, 1.0 + (v - 1.0) * max(0.0, k)) if v >= 1.0 else min(level, 1.0 + (v - 1.0) * max(0.0, k))
        return level

    def at(self, seconds):
        """(positions [n, 3], weights [n]): where each particle is at a time of the song (drifting, swaying, wrapped round the
        box) and how much of it shows (the busy level, the box's faces, the dancer's column)"""
        t = float(seconds)
        moved = self.start - self.lo + self.velocity * t + self.sway * np.sin(2.0 * math.pi * self.sway_hz * t + self.phase)
        rel = np.mod(moved, self.size)
        pos = self.lo + rel
        edge = np.clip(np.minimum(rel, self.size - rel) / EDGE_FADE, 0.0, 1.0).min(axis=1)
        level = self.level(t)
        visible = np.zeros(len(self.kind))
        for kind, n in self.base.items():
            mine = self.kind == kind
            visible[mine] = np.clip(level * n - self.rank[mine], 0.0, 1.0)
        clear = float(self.p["clear"])
        if clear > 0:
            # the dancer's column: round the stage's centre, up to her height and a little more
            r = np.hypot(pos[:, 0], pos[:, 2] + 5.0)
            visible *= np.clip((r - clear) / 2.0, 0.0, 1.0) + (pos[:, 1] > 24.0)
            visible = np.clip(visible, 0.0, 1.0)
        twinkle = 0.7 + 0.3 * np.sin(2.0 * math.pi * self.twinkle_hz * t + self.twinkle_phase)
        return pos, visible * edge * twinkle

    def draw(self, view, seconds, look, size):
        """(behind, in front): [h, w, 4] float RGBA (straight alpha, colour 0..255) of the particles as `view` sees them at a
        time of the song"""
        w, h = int(size[0]), int(size[1])
        unit = h / REFERENCE_HEIGHT
        stage = look["stage"]
        far = float(stage["dof"]) * unit
        focus = float(stage["dof_focus"]) or float(view.distance)
        pos, weight = self.at(seconds)
        u, v, depth = view.project(pos)
        front_from = float(view.distance) - FRONT_GAP
        layers = {"back": [np.zeros((h, w, 3)), np.zeros((h, w))], "front": [np.zeros((h, w, 3)), np.zeros((h, w))]}
        WT = world_tool()
        near = np.clip((depth - NEAR_FADE[0]) / (NEAR_FADE[1] - NEAR_FADE[0]), 0.0, 1.0)
        blur = WT.blur_of(depth, focus, far) if far > 0 and focus > 0 else np.zeros(len(depth))
        for i in np.nonzero((weight > 0.004) & (depth > NEAR_FADE[0]))[0]:
            r_px = self.radius[i] * view.focal / depth[i]
            b = float(blur[i])
            # (at least SPRITE_LEAST: a narrower spot falls between the pixels and flickers as it drifts)
            sigma = max(SPRITE_LEAST, math.sqrt((0.5 * r_px) ** 2 + b * b))
            disc = b > 1.5 * max(0.6, r_px)
            if disc:
                radius = math.sqrt(r_px ** 2 + (1.4 * b) ** 2)
                reach = int(math.ceil(radius + 2))
                peak = self.bright[i] * max(0.3, min(1.0, 3.0 / radius))
            else:
                radius = sigma
                reach = int(math.ceil(3.5 * sigma + 1))
                peak = self.bright[i] * min(1.0, 1.2 / sigma ** 0.5)
            x, y = float(u[i]), float(v[i])
            if not (-reach <= x < w + reach and -reach <= y < h + reach):
                continue
            c0, c1 = max(0, int(math.floor(x)) - reach), min(w, int(math.ceil(x)) + reach + 1)
            r0, r1 = max(0, int(math.floor(y)) - reach), min(h, int(math.ceil(y)) + reach + 1)
            if c1 <= c0 or r1 <= r0:
                continue
            dx, dy = np.arange(c0, c1) - x, np.arange(r0, r1) - y
            d = np.sqrt(dy[:, None] ** 2 + dx[None, :] ** 2)
            if disc:
                edge = max(1.0, 0.12 * radius)
                shape = np.clip((radius - d) / edge + 0.5, 0.0, 1.0) * (0.85 + 0.15 * np.clip(d / radius, 0.0, 1.0))
            else:
                shape = np.exp(-d * d / (2.0 * sigma * sigma))
            a = shape * peak * weight[i] * near[i]
            side = "front" if depth[i] < front_from else "back"
            if side == "front":
                a = np.minimum(a, float(self.p["front"]))
            colour, alpha = layers[side]
            colour[r0:r1, c0:c1] += a[..., None] * self.colour[i][None, None, :]
            alpha[r0:r1, c0:c1] += a
        out = []
        for side in ("back", "front"):
            colour, alpha = layers[side]
            alpha = np.clip(alpha, 0.0, 1.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                rgb = np.where(alpha[..., None] > 1e-6, colour / np.maximum(alpha, 1e-6)[..., None], 0.0)
            out.append(np.concatenate([np.clip(rgb, 0, 255), alpha[..., None] * 255.0], axis=2))
        return out[0], out[1]


def _as_png(rgba):
    from PIL import Image
    return Image.fromarray(np.clip(rgba + 0.5, 0, 255).astype(np.uint8), "RGBA")


BACK, FRONT = "back_%05d.png", "front_%05d.png"


def particle_frame(field, look, size, fps, track, index, subframes=1, shutter=1.0):
    """the particles of video frame `index` (behind, in front): at the middle of the moments its shutter is open, as the
    stage of tools/mv_world.py is drawn"""
    WT = world_tool()
    times = WT.moments(index, fps, subframes, shutter)
    middle = sum(times) / len(times)
    view = WT.view_at(track, middle, size)
    return field.draw(view, middle / float(SONG_FPS), look, size)


def _draw(look, size, fps, track, ranges, subframes, shutter, folder):
    field = Field(look["mograph"])
    for first, count in ranges:
        for index in range(int(first), int(first) + int(count)):
            back, front = particle_frame(field, look, size, fps, track, index, subframes, shutter)
            _as_png(back).save(os.path.join(folder, BACK % index), compress_level=1)
            _as_png(front).save(os.path.join(folder, FRONT % index), compress_level=1)


def write_particles(look, work, size, fps, world, first, count, spans=None):
    """the particles of video frames first .. first + count - 1 (or of `spans`, (first, count) stretches) as
    WORK/mograph/back_NNNNN.png and front_NNNNN.png (the frames of before go first: ffmpeg reads a numbered sequence until a
    number is missing).  `world` is mv_look's world_inputs (the camera, the shutter and the jobs).  The answer: {"back",
    "front" (patterns), "first", "frames", "spans"}"""
    WT = world_tool()
    ranges = WT.merge_spans(spans if spans is not None else [(first, count)])
    folder = os.path.join(work, "mograph")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if (name.startswith("back_") or name.startswith("front_")) and name.endswith(".png"):
            os.remove(os.path.join(folder, name))
    total, jobs = sum(n for _, n in ranges), max(1, int(world.get("jobs", 1)))
    subframes, shutter = int(world.get("subframes", 1)), float(world.get("shutter", 1.0))
    if jobs == 1 or total < 2:
        _draw(look, size, fps, world["track"], ranges, subframes, shutter, folder)
    else:
        _draw_in_jobs(look, size, fps, world, ranges, subframes, shutter, folder, jobs, work)
    pattern = os.path.join(folder, "%s").replace("\\", "/")
    return {"back": pattern % BACK, "front": pattern % FRONT, "first": ranges[0][0], "frames": total, "spans": ranges}


def _draw_in_jobs(look, size, fps, world, ranges, subframes, shutter, folder, jobs, work):
    shares = world_tool()._shares(ranges, min(jobs, sum(n for _, n in ranges)))
    running = []
    for k, share in enumerate(shares):
        job = {"look": look, "size": [int(size[0]), int(size[1])], "fps": fps, "camera": world["camera"], "ranges": share,
               "subframes": subframes, "shutter": shutter, "folder": folder}
        path = os.path.join(work, "mograph_job_%d.json" % k)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=True)
        log = open(os.path.join(work, "mograph_job_%d.log" % k), "wb")
        running.append((path, log, subprocess.Popen([sys.executable, os.path.abspath(__file__), "draw", path],
                                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)))
    failed = []
    for path, log, process in running:
        process.wait()
        log.close()
        with open(log.name, "rb") as f:
            said = f.read().decode("utf-8", "replace").strip()
        if process.returncode != 0:
            failed.append("%s (exit %d): %s" % (os.path.basename(path), process.returncode, said[-400:]))
        for leftover in (path, log.name):
            try:
                os.remove(leftover)
            except OSError:
                pass
    if failed:
        raise RuntimeError("drawing the particles failed in %d of %d jobs: %s" % (len(failed), len(shares), " | ".join(failed)))


def particles_ready(note, spans):
    """the particles a `prepare` wrote (its note's "mograph") hold every frame of `spans` and no more after each"""
    if not isinstance(note, dict) or not isinstance(note.get("spans"), list):
        return False
    for first, count in spans:
        for pattern in (note["back"], note["front"]):
            if not all(os.path.isfile(pattern % i) for i in range(int(first), int(first) + int(count))):
                return False
    return True


# ---- the plan: the events placed on the song's structure -----------------------------------------------------------

def load_structure(path):
    """the song's structure (looks/song_structure.json of the stage-6 work): checked for what plan reads"""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    for key in ("beat", "sections", "hooks", "interludes", "end", "seconds"):
        if key not in doc:
            raise ValueError("%s has no %r: not a song structure" % (path, key))
    return doc


def frame_time(frame):
    """the time to write for an event that starts on `frame` of the song (30 a second): a third of a millisecond or more under
    the frame's own time, floored to the millisecond, so that round(t x fps) and ceil(t x fps) both give that frame (the
    flares of the look of 2026-10 started their punch a frame after their picture at 44.467 and 225.8 s: lookfrom)"""
    return math.floor((int(frame) / float(SONG_FPS) - 0.0003) * 1000.0) / 1000.0


def plan(structure, level=1.0, particles=None):
    """the "mograph" section placed on the song (see the rules in the code; every event says why in its note):

    * a white flash and a punch on the first beat of each title word (the hook: light and text change there too);
    * a punch on the first beat of each chorus and of each pre-chorus (B): with the title words about 2 a minute, as the
      references' editors punch (typorev: 2.5 [1.7, 5.1] a minute measured, most of them the camera's own zooms);
    * a shake where the dancer comes down from a jump (the landings) and on the strongest accents of the song that the dance
      stops on (a deceleration of 5.5 times the dance's mean or more), one within half a second;
    * a dip to black before the band comes in (the picture back at once) and at the break, and the end fading to black from
      the last bar line on;
    * a dissolve into the second verse and into the bridge (sections that start without a cut of their own);
    * these changes of picture CUT_LEAD before their beat, as the references cut;
    * a glitch of two frames on the last beat before the third chorus and one at the outro;
    * the particles, a little busier (1.3 times) over the interludes.
    Every event starts on the frame of its moment (round(t x 30)) and is written as that frame's frame_time.  No punch or
    shake lands within half a second of where the skirt flares (the underwear checks look there)"""
    beat = structure["beat"]

    def at(b):
        return float(beat["first"]) + b * float(beat["period"])
    sections = {s["id"]: s for s in structure["sections"]}
    skirt = [float(s) for s in structure.get("skirt", [])]
    events = []

    def near_skirt(t, frames):
        end = t + frames / float(SONG_FPS)
        return any(t - 0.5 < s < end + 0.5 for s in skirt)

    def add(kind, t, note, **values):
        e = {"kind": kind, "t": frame_time(frame_of(t, SONG_FPS)), "note": note}
        e.update(values)
        events.append(e)
    punch = DEFAULTS["punch"]
    punch_len = punch["rise"] + punch["fall"]
    for h in structure["hooks"]:
        add("flash", h["t"], "title word %d (beat %d)" % (h["n"], h["beat"]))
        if not near_skirt(h["t"], punch_len):
            add("punch", h["t"], "title word %d (beat %d)" % (h["n"], h["beat"]), amount=0.12)
    for sid in ("chorus1", "chorus2", "chorus3"):
        s = sections.get(sid)
        if s and not near_skirt(s["t"], punch_len):
            add("punch", s["t"], "%s, first beat (beat %d)" % (sid, s["beat"]))
    for sid in ("pre1", "pre2"):
        s = sections.get(sid)
        if s and not near_skirt(s["t"], punch_len):
            # (0.09: tools/mograph_analyze.py counts a punch from a zoom of 0.08 in the log, 8.3 %, within three frames)
            add("punch", s["t"], "%s, first beat (beat %d)" % (sid, s["beat"]), amount=0.09)
    shakes = []
    for land in structure.get("landings", []):
        shakes.append((float(land["t"]), "landing (%d frames in the air)" % land["air_frames"]))
    for acc in structure.get("accents", []):
        if acc["decel"] >= 5.5:
            shakes.append((float(acc["t"]), "accent the dance stops on (deceleration %.1f)" % acc["decel"]))
    last = -10.0
    for t, note in sorted(shakes):
        if t - last < 0.5 or near_skirt(t, DEFAULTS["shake"]["frames"]):
            continue
        add("shake", t, note)
        last = t
    def change(sid):
        """the frame of the change of picture at a section's start: CUT_LEAD before its first beat"""
        return frame_of(sections[sid]["t"] - CUT_LEAD, SONG_FPS)
    if "band" in sections:
        out, hold = 18, 3
        add("fade", (change("band") - out - hold) / float(SONG_FPS),
            "dip before the band comes in (beat %d): back at once, %.3f s before the beat" % (sections["band"]["beat"], CUT_LEAD),
            out=out, hold=hold, back=0)
    if "break" in sections:
        add("fade", (change("break") - 13) / float(SONG_FPS),
            "dip at the break (beat %d), the low end drops: black %.3f s before the beat" % (sections["break"]["beat"], CUT_LEAD),
            out=13, hold=4, back=30)
    if "end" in sections:
        # over a bar (1.7 s): tools/mograph_analyze.py reads a fade to black that falls by 0.1 of Y' within the second before
        # the black, and v7's dark picture faded over two bars fell by 0.03
        add("fade", change("end") / float(SONG_FPS),
            "the end: to black over the last bar line's bar (beat %d) on" % sections["end"]["beat"], out=51, hold=-1, back=0)
    for sid in ("verse2", "bridge"):
        if sid in sections:
            add("dissolve", change(sid) / float(SONG_FPS),
                "into %s (beat %d), %.3f s before the beat" % (sid, sections[sid]["beat"], CUT_LEAD))
    if "chorus3" in sections:
        b = sections["chorus3"]["beat"] - 1
        add("glitch", at(b), "the last beat before chorus3 (beat %d)" % b, frames=2)
    if "outro" in sections:
        add("glitch", sections["outro"]["t"], "outro (beat %d)" % sections["outro"]["beat"], frames=1)
    section = copy.deepcopy(DEFAULTS)
    section["on"] = 1
    section["particles"].update(particles or PLAN_PARTICLES)
    section["busy"] = [[round(i["from"], 3), round(i["to"], 3), PLAN_BUSY] for i in structure["interludes"]]
    if level != 1.0:
        for e in events:
            if e["kind"] in ("punch", "shake", "flash"):
                key = {"punch": "amount", "shake": "amount", "flash": "strength"}[e["kind"]]
                e[key] = round(float(e.get(key, DEFAULTS[e["kind"]][key])) * level, 4)
    section["events"] = sorted(events, key=lambda e: (e["t"], KINDS.index(e["kind"])))
    return merge({k: v for k, v in section.items() if v != DEFAULTS[k] or k == "on"})


def rates(section, seconds):
    """the events of a section a minute, by kind, over a song of `seconds` (glitch: frames a minute, as the reference counts
    them)"""
    minutes = seconds / 60.0
    out = {}
    for kind in KINDS:
        mine = [e for e in events_of(section) if e["kind"] == kind]
        n = sum(int(e["frames"]) for e in mine) if kind == "glitch" else len(mine)
        out[kind] = n / minutes
    return out


# ---- apply: the events over a finished video -----------------------------------------------------------------------

def apply_argv(video, out, section, size, fps, start=None, duration=None, offset=0.0, matrix="bt709", colour_range="tv"):
    """the ffmpeg argv that lays the section's punches, shakes, glitches, dissolves, fades and flashes over a finished video
    (an excerpt from `start` seconds of the song for `duration`; `offset`: the song's time at the video's first frame), read
    by its own YCbCr `matrix` and range and written by BT.709 with its four tags as mv_look writes"""
    offset = float(offset or 0.0)
    clip_start = offset if start is None else float(start)
    no_particles = dict(section, particles=dict(section["particles"], specks=0, lights=0))
    graph = Graph(no_particles, size, fps, clip_start, duration)
    argv = ["ffmpeg", "-v", "error", "-y"]
    first = int(round((clip_start - offset) * fps))          # the excerpt's first frame, of the video
    count = None if duration is None else max(1, int(round(float(duration) * fps)))
    pick, audio = "", "0:a?"
    if start is not None or count is not None:
        # the excerpt's frames picked by their number, round((t + seek) x fps), from a seek a second before: a seek and a -t
        # that end on times read a frame more where the frames lie a hair before their times (v7 from 58 s on lies 5 ticks of
        # 1/15360 s early: its excerpt 40-60 s read 601 frames, and the effects after it came a frame late; 2026-10-21)
        seek = max(0.0, first / float(fps) - 1.0) if start is not None else 0.0
        if seek > 0:
            argv += ["-ss", "%.6f" % seek]
        if count is not None:
            argv += ["-t", "%.6f" % ((first + count + 1) / float(fps) - seek)]
        argv += ["-i", video]
        index = "round((t+%s)*%s)" % (_n(seek), _n(fps))
        within = "gte(%s,%d)" % (index, first) + ("*lte(%s,%d)" % (index, first + count - 1) if count is not None else "")
        pick = "select='%s',setpts=N/(%s*TB)," % (within, _n(fps))
        # and the sound of the very same span, from the same file read again (its own seek, cut to the sample and encoded)
        argv += ["-ss", "%.6f" % (first / float(fps))] + (["-t", "%.6f" % (count / float(fps))] if count is not None else [])
        audio = "1:a?"
    argv += ["-i", video]
    parts = ["[0:v]%sscale=in_color_matrix=%s:in_range=%s,format=gbrp,setpts=PTS-STARTPTS[src]" % (pick, matrix, colour_range)]
    label = graph.camera(parts, "src")
    label = graph.veils(parts, label)
    parts.append("[%s]scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:"
                 "color_trc=bt709:colorspace=bt709:range=tv[out]" % label)
    argv += ["-filter_complex", ";".join(parts), "-map", "[out]", "-map", audio] + \
        (["-c:a", "copy"] if audio == "0:a?" else ["-c:a", "aac", "-b:a", "192k"]) + \
        ["-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    return argv


# ---- the commands --------------------------------------------------------------------------------------------------

def _mv_look():
    spec = importlib.util.spec_from_file_location("mv_look", os.path.join(HERE, "mv_look.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="the section placed on the song's structure, as a look")
    p.add_argument("structure")
    p.add_argument("out")
    p.add_argument("--look", help="a look to put the section into (its other values are kept)")
    p.add_argument("--level", type=float, default=1.0, help="the punches', shakes' and flashes' strength times this")
    p = sub.add_parser("frame", help="the particles of one frame over a grey card")
    p.add_argument("look")
    p.add_argument("out")
    p.add_argument("--frame", type=float, required=True, help="the frame of the song")
    p.add_argument("--camera", required=True)
    p.add_argument("--size", default="1280x720")
    p = sub.add_parser("apply", help="the section's events over a finished video")
    p.add_argument("video")
    p.add_argument("look")
    p.add_argument("out")
    p.add_argument("--from", dest="start", type=float)
    p.add_argument("--to", type=float)
    p.add_argument("--offset", type=float, default=0.0)
    p = sub.add_parser("draw", help="draw the particles of a job file (write_particles with jobs runs these)")
    p.add_argument("job")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "draw":
            with open(args.job, encoding="utf-8") as f:
                job = json.load(f)
            _draw(job["look"], tuple(job["size"]), job["fps"], world_tool().camera_track(job["camera"]), job["ranges"],
                  job["subframes"], job["shutter"], job["folder"])
            print(json.dumps({"ok": True, "ranges": job["ranges"]}))
            return 0
        if args.cmd == "plan":
            structure = load_structure(args.structure)
            section = plan(structure, args.level)
            look = {}
            if args.look:
                with open(args.look, encoding="utf-8") as f:
                    look = json.load(f)
            look["mograph"] = {k: v for k, v in section.items() if v != DEFAULTS[k] or k == "on"}
            ML = _mv_look()
            full = ML.merge_look(look)                       # the whole look must still be one
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(look, f, ensure_ascii=False, indent=1)
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "events": len(section["events"]),
                              "per_min": {k: round(v, 3) for k, v in rates(full["mograph"], float(structure["seconds"])).items()}},
                             ensure_ascii=True))
            return 0
        ML = _mv_look()
        look = ML.load_look(args.look)
        if args.cmd == "frame":
            size = ML.parse_size(args.size)
            track = world_tool().camera_track(args.camera)
            field = Field(look["mograph"])
            back, front = particle_frame(field, look, size, SONG_FPS, track, int(round(args.frame)))
            card = np.full((size[1], size[0], 3), 96.0)
            out = []
            for layer in (back, front):
                a = layer[..., 3:] / 255.0
                out.append(card * (1 - a) + layer[..., :3] * a)
            from PIL import Image
            Image.fromarray(np.clip(np.concatenate(out, axis=1) + 0.5, 0, 255).astype(np.uint8)).save(args.out)
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}))
            return 0
        if args.cmd == "apply":
            if not look["mograph"]["on"]:
                raise ValueError("the look has no motion graphics (mograph.on 0)")
            size, fps = ML.probe(args.video)
            spec = importlib.util.spec_from_file_location("look_analyze", os.path.join(HERE, "look_analyze.py"))
            LA = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(LA)
            info = LA.probe(args.video)
            duration = None if args.to is None else args.to - (args.start if args.start is not None else args.offset)
            argv = apply_argv(args.video, args.out, look["mograph"], size, fps, args.start, duration, args.offset,
                              LA.matrix_for(info), "pc" if info.get("color_range") in ("pc", "jpeg") else "tv")
            argv = long_argv(argv, args.out + ".filter_complex.txt")
            done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if done.returncode != 0:
                raise RuntimeError("ffmpeg failed (%d): %s" % (done.returncode, done.stderr.strip()[-600:]))
            if os.path.exists(args.out + ".filter_complex.txt"):
                os.remove(args.out + ".filter_complex.txt")
            print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "size": list(size), "fps": fps}))
            return 0
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": {"type": "ValueError", "message": str(exc)}}, ensure_ascii=True))
        return 2
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
