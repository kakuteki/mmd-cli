"""Put a stage, light and glow around the dancer MMD rendered with an alpha channel: nothing happens in MMD.

    python tools/mv_look.py render DANCER.avi look.json OUT.mp4 [--cues cues.json] [--work DIR]
                                   [--from SECONDS] [--to SECONDS] [--size WxH] [--fps N]
    python tools/mv_look.py layers look.json WORK --size WxH --fps N

MMD writes the picture with an alpha channel when its background is blackened (menu 282, `mmd menu set 282
on`): both the PNG of `render image` and the uncompressed AVI of `render avi --codec 未圧縮` are BGRA with
alpha 0 where nothing was drawn (measured on v9.32, 2026-10-04).  So the dancer can be laid over any stage
afterwards, and light can be put behind her.  This tool makes that picture with Pillow (the layers) and
ffmpeg (the compositing), from back to front:

* the plate: a dark stage, a band of haze at the horizon and a pool of light behind the dancer (`plate`);
* the light: soft beams fanning down from above the frame and a few floating specks, drawn on black and
  screened over the plate.  It is a loop of `beams.loop_seconds` that closes (every motion in it is a
  whole number of sine periods per loop), repeated for the whole song with -stream_loop;
* the text cues of the "back" layer (tools/mv_text.py renders them; a title behind the dancer);
* the dancer, by her alpha;
* her glow: the bright parts of the dancer alone (each channel above `glow.threshold` of 255), blurred by
  `glow.radius` pixels and screened over the picture with `glow.strength`;
* at every time in `flares` (a hook, a chorus) the camera punches in a little and comes back, and red and
  blue part for those frames (`camera`): the stage and the dancer move, the text in front does not;
* the lens: darker corners and a fine grain over all of that (`lens`);
* motion blur (--subframes N --shutter S): MMD renders genuine in-between poses at higher rates (measured: 120 fps
  gives 4 different poses per 30 fps frame), so the dancer can be rendered at N times the output rate and every
  output frame made from the average of the first round(S * N) of its N subframes, like a film camera whose
  shutter is open for S of the frame time (0.5 is the film standard).  The average is taken on premultiplied
  colours, since a transparent pixel of MMD's output has colour 0;
* the text cues of the "front" layer;
* a flare at each of those times: a burst of light and a streak for `flare.frames`.

look.json overrides single values of DEFAULT_LOOK; an unknown name is an error (a misspelt setting would
otherwise silently do nothing).  Lengths are in pixels of a 720 line picture and scale with the height.
The output has no sound: the song is added afterwards (ffmpeg -i OUT.mp4 -i song.wav -c:v copy ...).
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
from PIL import Image, ImageDraw, ImageFilter

DEFAULT_LOOK = {
    # colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom)
    "plate": {"base": [10, 12, 20], "haze": [34, 44, 78], "pool": [70, 86, 140], "horizon": 0.68, "vignette": 0.45},
    # count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm
    "beams": {"count": 6, "spread": 76.0, "sway": 3.0, "opacity": 0.55, "loop_seconds": 12,
              "cool": [90, 110, 190], "warm": [200, 150, 80], "warm_every": 5},
    "bokeh": {"count": 26, "opacity": 0.8, "seed": 7, "warm_share": 0.35},
    # tuned on the first real excerpt (hinata, 2026-10-05): 150 / 16 / 0.6 washed the white dress out and
    # turned the skin pink; this keeps the folds of the dress and still gives her a soft edge
    "glow": {"threshold": 175, "radius": 14, "strength": 0.45},
    "flare": {"frames": 12, "strength": 0.85, "colour": [255, 244, 224]},
    # what the camera does at a flare: it punches in by `punch` of the picture and comes back within
    # `punch_frames`, and red and blue part by `aberration` pixels for as long
    "camera": {"punch": 0.04, "punch_frames": 10, "aberration": 3},
    # the lens: the corners a little darker (vignette, 0 none to 1 strong) and a fine grain that changes with
    # every frame (0 none, up to about 10); both lie under the text in front
    "lens": {"vignette": 0.3, "grain": 3},
    "flares": [],
}
REFERENCE_HEIGHT = 720.0
LIGHT_SCALE = 2                  # the light is drawn at half size: it is all blur


# ---- the look -------------------------------------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(name, value, default):
    if isinstance(default, list):
        if not isinstance(value, list) or not all(_is_number(v) for v in value):
            raise ValueError("%s must be a list of numbers, not %r" % (name, value))
        if default and len(value) != len(default):
            raise ValueError("%s needs %d numbers, not %d" % (name, len(default), len(value)))
    elif not _is_number(value):
        raise ValueError("%s must be a number, not %r" % (name, value))


def merge_look(overrides):
    """DEFAULT_LOOK with the values of `overrides` put over it; unknown names and wrong kinds are errors"""
    look = copy.deepcopy(DEFAULT_LOOK)
    if not isinstance(overrides, dict):
        raise ValueError("a look is a JSON object, not %r" % (overrides,))
    for name, value in overrides.items():
        if name not in look:
            raise ValueError("the look has no setting %r (it has: %s)" % (name, ", ".join(sorted(look))))
        if isinstance(look[name], dict):
            if not isinstance(value, dict):
                raise ValueError("%s must be an object, not %r" % (name, value))
            for key, v in value.items():
                if key not in look[name]:
                    raise ValueError("%s has no setting %r (it has: %s)" % (name, key, ", ".join(sorted(look[name]))))
                _check("%s.%s" % (name, key), v, look[name][key])
                look[name][key] = v
        else:
            _check(name, value, look[name])
            look[name] = value
    return look


# ---- the layers -----------------------------------------------------------------------------

def plate(size, settings):
    """the stage: dark, lighter in a band of haze at the horizon and in a pool behind the dancer, darker
    towards the corners"""
    w, h = size
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    haze = np.exp(-((y - float(settings["horizon"])) / 0.22) ** 2)
    pool = np.exp(-((x / 0.55) ** 2 + ((y - 0.52) / 0.42) ** 2))
    img = (np.array(settings["base"], dtype=np.float32)[None, None, :]
           + haze[:, :, None] * np.array(settings["haze"], dtype=np.float32)[None, None, :] * 0.55
           + pool[:, :, None] * np.array(settings["pool"], dtype=np.float32)[None, None, :] * 0.55)
    dark = 1.0 - float(settings["vignette"]) * np.clip(x ** 2 + (2.0 * y - 1.0) ** 2 * 0.6, 0.0, 1.0)
    return Image.fromarray(np.clip(img * dark[:, :, None], 0, 255).astype(np.uint8), "RGB")


def light_frame_count(look, fps):
    return max(1, int(round(float(look["beams"]["loop_seconds"]) * fps)))


def _unit(i, salt):
    """a fixed number in 0..1 for the i-th thing (no random module: the same on every Python)"""
    return (math.sin(i * 12.9898 + salt * 78.233) * 43758.5453) % 1.0


def _beams(size, settings, phase):
    w, h = size
    layer = Image.new("RGB", size, (0, 0, 0))
    count = int(settings["count"])
    if count <= 0 or settings["opacity"] <= 0:
        return np.zeros((h, w, 3), dtype=np.float32)
    draw = ImageDraw.Draw(layer)
    origin = (w * 0.5, -h * 0.35)
    length = h * 2.4
    warm_every = int(settings["warm_every"])
    for i in range(count):
        centre = -settings["spread"] / 2.0 + settings["spread"] * (i + 0.5) / count
        # each beam sways one or two whole periods per loop, out of step with its neighbours
        sway = settings["sway"] * math.sin((1 + i % 2) * phase + 2.0 * math.pi * _unit(i, 1))
        angle = math.radians(centre + sway)
        half = math.radians(2.0 + 2.5 * _unit(i, 2))
        tone = 0.55 + 0.45 * _unit(i, 3)
        colour = settings["warm"] if warm_every > 0 and i % warm_every == warm_every - 1 else settings["cool"]
        p1 = (origin[0] + length * math.sin(angle - half), origin[1] + length * math.cos(angle - half))
        p2 = (origin[0] + length * math.sin(angle + half), origin[1] + length * math.cos(angle + half))
        draw.polygon([origin, p1, p2], fill=tuple(int(c * tone) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, w * 0.022)))
    fade = np.linspace(1.0, 0.25, h, dtype=np.float32)[:, None, None]          # thinner towards the floor
    return np.asarray(layer, dtype=np.float32) * fade * float(settings["opacity"])


def _bokeh(size, settings, phase):
    w, h = size
    count = int(settings["count"])
    if count <= 0 or settings["opacity"] <= 0:
        return np.zeros((h, w, 3), dtype=np.float32)
    layer = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    seed = float(settings["seed"])
    for i in range(count):
        x = _unit(i, seed + 1) * w + 0.02 * w * math.sin(phase + 2.0 * math.pi * _unit(i, seed + 2))
        y = _unit(i, seed + 3) * h * 0.9 + 0.03 * h * math.sin(phase + 2.0 * math.pi * _unit(i, seed + 4))
        r = (3.0 + 11.0 * _unit(i, seed + 5)) * h / REFERENCE_HEIGHT * LIGHT_SCALE / 2.0 + 1.0
        twinkle = 0.7 + 0.3 * math.sin(2.0 * phase + 2.0 * math.pi * _unit(i, seed + 6))
        tone = (0.25 + 0.55 * _unit(i, seed + 7)) * twinkle
        colour = (255, 214, 150) if _unit(i, seed + 8) < settings["warm_share"] else (150, 180, 255)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(c * tone) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, h * 0.014)))
    return np.asarray(layer, dtype=np.float32) * float(settings["opacity"])


def light_frame(size, look, index, count):
    """frame `index` of the loop of `count` frames: beams and specks on black, to be screened over the plate"""
    phase = 2.0 * math.pi * (index % count) / float(count)
    total = _beams(size, look["beams"], phase) + _bokeh(size, look["bokeh"], phase)
    return Image.fromarray(np.clip(total, 0, 255).astype(np.uint8), "RGB")


FLARE_HEIGHT = 0.42              # of the picture, from the top: about the dancer's chest in a full shot


def flare_frame(size, settings, index):
    """frame `index` of a flare, strongest on the first frame: a burst of light in the middle of the picture,
    a thin streak across it at the same height with a soft halo, and only a faint lift of everything else
    (an even white over the whole picture reads as grey fog, not as light)"""
    w, h = size
    frames = max(1, int(settings["frames"]))
    decay = (1.0 - index / float(frames)) ** 2 if index < frames else 0.0
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    dy = y - FLARE_HEIGHT
    burst = np.exp(-((x / 0.42) ** 2 + (dy / 0.30) ** 2))
    streak = (np.exp(-(dy / 0.012) ** 2) + 0.45 * np.exp(-(dy / 0.07) ** 2)) * (0.55 + 0.45 * np.exp(-(x / 0.8) ** 2))
    alpha = np.clip(float(settings["strength"]) * decay * (0.14 + np.maximum(1.05 * burst, 0.8 * streak)), 0.0, 1.0)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[:, :, :3] = np.array(settings["colour"], dtype=np.uint8)[None, None, :]
    out[:, :, 3] = (alpha * 255.0).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def write_layers(look, work, size, fps):
    """the plate, the light loop (at half size) and the flare frames under `work`; returns where they are"""
    os.makedirs(work, exist_ok=True)
    plate_path = os.path.join(work, "plate.png")
    plate(size, look["plate"]).save(plate_path)
    light_dir = os.path.join(work, "light")
    os.makedirs(light_dir, exist_ok=True)
    small = (max(2, size[0] // LIGHT_SCALE), max(2, size[1] // LIGHT_SCALE))
    count = light_frame_count(look, fps)
    for i in range(count):
        light_frame(small, look, i, count).save(os.path.join(light_dir, "light_%05d.png" % i))
    flare_dir = os.path.join(work, "flare")
    os.makedirs(flare_dir, exist_ok=True)
    flare_frames = max(1, int(look["flare"]["frames"]))
    for i in range(flare_frames):
        flare_frame(small, look["flare"], i).save(os.path.join(flare_dir, "flare_%05d.png" % i))
    return {"plate": plate_path, "light_pattern": _slashes(os.path.join(light_dir, "light_%05d.png")), "light_frames": count,
            "flare_pattern": _slashes(os.path.join(flare_dir, "flare_%05d.png")), "flare_frames": flare_frames}


def _slashes(path):
    return path.replace("\\", "/")


# ---- the compositing ------------------------------------------------------------------------

def _visible(start, frames, fps, clip_start, clip_duration):
    """(seconds into the excerpt, first frame to show) of a sequence that starts at `start` seconds, or None
    when no frame of it falls inside the excerpt"""
    offset = start - clip_start
    skip = 0
    if offset < 0:
        skip = int(round(-offset * fps))
        offset = 0.0
    if skip >= frames or (clip_duration is not None and offset >= clip_duration):
        return None
    return offset, skip


def ffmpeg_command(fg, out, plate_path, light_pattern, look, size, fps, plan=None, flare_pattern=None, flare_frames=0,
                   start=None, duration=None, offset=0.0, subframes=1, shutter=1.0, light_frames=None):
    """the ffmpeg argv that lays plate, light, back text, dancer, glow, front text and flares over each other
    (see the module docstring).  `offset` is the song time at the dancer's first frame (a chunk of the song
    rendered from a later frame); `start` and `duration` cut an excerpt, in seconds of the song.  With
    `light_frames` (the length of the light loop) an excerpt shows the loop where the whole song has it at that time,
    and a flare that began before the excerpt has its punch part spent: the seams of a song rendered in chunks
    (tools/mv_chunks.py) then hide in the cuts (review 10)"""
    w, h = size
    taken = check_shutter(subframes, shutter)
    offset = float(offset or 0.0)
    if start is not None and start < offset - 1e-9:
        raise ValueError("--from %.3f is before the dancer's file, which begins at %.3f s of the song" % (start, offset))
    clip_start = float(start) if start is not None else offset
    argv = ["ffmpeg", "-v", "error", "-y"]
    if start is not None:
        argv += ["-ss", "%.3f" % (clip_start - offset)]
    if duration is not None:
        argv += ["-t", "%.3f" % duration]
    # -r before the dancer: her frames are put on the same clock as the layers.  MMD writes 30 fps as
    # 10000000/333333 (30.00003), so her frames come a hair early; left like that, the last frame of the stage
    # falls after her last frame and is dropped (7742 of 7743 on the whole song)
    argv += ["-r", _number(fps * subframes), "-i", fg, "-loop", "1", "-framerate", str(fps), "-i", plate_path]
    # the light is one loop repeated over the whole song: an excerpt begins at the loop's frame for its song time,
    # plays to the end of the loop and then repeats the loop from its start (two inputs, joined in the graph)
    phase = int(round(clip_start * fps)) % int(light_frames) if light_frames else 0
    if phase:
        argv += ["-framerate", str(fps), "-start_number", str(phase), "-i", light_pattern]
    argv += ["-stream_loop", "-1", "-framerate", str(fps), "-i", light_pattern]
    next_input = 4 if phase else 3
    overlays = {"back": [], "front": [], "flare": []}
    for cue in (plan or {}).get("cues", []):
        seen = _visible(cue["start"], cue["frames"], fps, clip_start, duration)
        if seen is None:
            continue
        offset, skip = seen
        argv += ["-framerate", str(fps), "-start_number", str(skip), "-i", cue["pattern"]]
        layer = "back" if cue.get("layer") == "back" else "front"
        overlays[layer].append((next_input, offset, cue["x"], cue["y"], None))
        next_input += 1
    flare_starts = []                  # seconds from the excerpt's start; below 0 for a flare that began before it
    for at in look["flares"]:
        seen = _visible(float(at), flare_frames, fps, clip_start, duration) if flare_pattern else None
        if seen is None:
            continue
        offset, skip = seen
        argv += ["-framerate", str(fps), "-start_number", str(skip), "-i", flare_pattern]
        overlays["flare"].append((next_input, offset, 0, 0, (w, h)))
        flare_starts.append(float(at) - clip_start)
        next_input += 1

    light_in = "[2:v][3:v]concat=n=2:v=1:a=0," if phase else "[2:v]"
    parts = ["[1:v]scale=%d:%d,format=gbrp[plate]" % (w, h),
             "%sscale=%d:%d:flags=bilinear,format=gbrp[light]" % (light_in, w, h),
             "[plate][light]blend=all_mode=screen[stage]"]
    state = {"label": "stage", "n": 0}

    def lay(items):
        for index, offset, x, y, scale in items:
            state["n"] += 1
            scaled = "scale=%d:%d:flags=bilinear," % scale if scale else ""
            # round: setpts cuts its result down to a whole tick, and 16 / 30 s written in decimals is a hair
            # short of the 16th tick (one cue in three came a frame early)
            parts.append("[%d:v]%sformat=rgba,setpts=PTS-STARTPTS+round(%.6f/TB)[c%d]" % (index, scaled, offset, state["n"]))
            parts.append("[%s][c%d]overlay=x=%d:y=%d:eof_action=pass[v%d]" % (state["label"], state["n"], x, y, state["n"]))
            state["label"] = "v%d" % state["n"]

    lay(overlays["back"])
    glow = look["glow"]
    scale = h / REFERENCE_HEIGHT
    if glow["strength"] > 0 and glow["radius"] > 0:
        t = int(glow["threshold"])
        curve = "clip((val-%d)*255/(255-%d),0,255)" % (t, t)
        parts += ["[0:v]%sformat=rgba,split=2[fg][fgb]" % _fold(subframes, taken, fps),
                  "[%s][fg]overlay=shortest=1:format=auto,format=gbrp[comp]" % state["label"],
                  "color=c=black:s=%dx%d:r=%s[blk]" % (w, h, fps),
                  "[blk][fgb]overlay=shortest=1,format=gbrp[fgk]",
                  "[fgk]lutrgb=r='%s':g='%s':b='%s',gblur=sigma=%s[glow]" % (curve, curve, curve, _number(glow["radius"] * scale)),
                  "[comp][glow]blend=all_mode=screen:all_opacity=%.3f:shortest=1[lit]" % glow["strength"]]
        state["label"] = "lit"
    else:
        parts += ["[0:v]%sformat=rgba[fg]" % _fold(subframes, taken, fps),
                  "[%s][fg]overlay=shortest=1:format=auto[lit]" % state["label"]]
        state["label"] = "lit"
    camera = look["camera"]
    span = camera["punch_frames"] / float(fps)
    hits = flare_starts if span > 0 else []
    if hits and camera["punch"] > 0:
        # 1 + punch * (1 - (t - T) / span)^2 from each flare time T on; the picture is scaled about its centre
        amount = "+".join("%s*pow(max(0,1-(%s)/%.3f),2)*gte(t,%.3f)" % (_number(camera["punch"]), _since(at), span, at)
                          for at in hits)
        parts.append("[%s]scale=w='trunc(%d*(1+%s)/2)*2':h='trunc(%d*(1+%s)/2)*2':eval=frame:flags=bilinear,"
                     "crop=%d:%d:(iw-%d)/2:(ih-%d)/2[punch]" % (state["label"], w, amount, h, amount, w, h, w, h))
        state["label"] = "punch"
    shift = int(round(camera["aberration"] * scale))
    if hits and shift > 0:
        enable = "+".join("between(t,%.3f,%.3f)" % (at, at + span) for at in hits)
        parts.append("[%s]rgbashift=rh=-%d:bh=%d:enable='%s'[parted]" % (state["label"], shift, shift, enable))
        state["label"] = "parted"
    lens = look["lens"]
    finish = []
    if lens["vignette"] > 0:
        # the filter takes the angle of the lens: 0.3 is about PI/6.5, 1 about PI/2.6 (dark far into the picture)
        finish.append("vignette=angle=%s" % _number(0.28 + 0.92 * min(float(lens["vignette"]), 1.0)))
    if lens["grain"] > 0:
        finish.append("noise=alls=%d:allf=t" % int(round(lens["grain"])))
    if finish:
        parts.append("[%s]%s[lens]" % (state["label"], ",".join(finish)))
        state["label"] = "lens"
    lay(overlays["front"])
    lay(overlays["flare"])
    parts.append("[%s]format=yuv420p[out]" % state["label"])
    argv += ["-filter_complex", ";".join(parts), "-map", "[out]", "-an", "-r", str(fps),
             "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    return argv


def _since(at):
    """the seconds since T as an ffmpeg expression: t-1.000, or t+0.100 for a T before the excerpt (T = -0.1)"""
    return "t-%.3f" % at if at >= 0 else "t+%.3f" % -at


def check_shutter(subframes, shutter):
    """how many of every `subframes` dancer frames one output frame averages (the shutter is open for that
    share of the frame time); 1 subframe is no blur"""
    if int(subframes) != subframes or subframes < 1:
        raise ValueError("--subframes is a whole number from 1, not %r" % (subframes,))
    if not 0 < shutter <= 1:
        raise ValueError("--shutter is the share of a frame the shutter is open, above 0 up to 1, not %r" % (shutter,))
    if subframes == 1:
        return 1                                   # no blur: the shutter does not matter
    taken = int(math.floor(shutter * subframes + 0.5))
    if taken < 1:
        raise ValueError("--shutter %r takes no subframe of %d: open it to at least %.3f" % (shutter, subframes, 0.5 / subframes))
    return taken


def _fold(subframes, taken, fps):
    """the filters that fold `subframes` dancer frames into one output frame: the first `taken` of each are
    averaged (motion blur, a shutter open for taken / subframes of the frame time).  The alpha is straight, and a
    transparent pixel has colour 0, so the colours are premultiplied for the average and divided back after."""
    if subframes == 1:
        return ""
    return ("format=rgba,premultiply=inplace=1,tmix=frames=%d,select='eq(mod(n,%d),%d)',setpts=N/(%s*TB),"
            "unpremultiply=inplace=1," % (taken, subframes, taken - 1, _number(fps)))


def _number(value):
    """a short decimal without a trailing zero: 4.0 -> 4, 2.25 -> 2.25"""
    return ("%.3f" % value).rstrip("0").rstrip(".")


# ---- the commands ---------------------------------------------------------------------------

def probe(path):
    """(width, height), fps of the first video stream"""
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height,r_frame_rate", "-of", "json", path],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return (int(stream["width"]), int(stream["height"])), parse_rate(stream["r_frame_rate"])
    except (ValueError, KeyError, IndexError):
        raise ValueError("ffprobe cannot read a video stream from %s: %s" % (path, result.stderr.strip()[-300:]))


def parse_rate(text):
    """frames per second from ffprobe's "num/den"; a rate a hair off a whole number is that number (MMD
    writes 30 fps as 10000000/333333, and layers at 30.00003 would drift against a 30 fps song)"""
    try:
        num, den = text.split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        raise ValueError("not a frame rate: %r" % (text,))
    return int(round(fps)) if abs(fps - round(fps)) < 0.001 else fps


def parse_size(text):
    try:
        w, h = (int(v) for v in text.lower().split("x"))
        if w < 2 or h < 2:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError("a size is WIDTHxHEIGHT, like 1280x720, not %r" % (text,))


def load_look(path):
    try:
        with open(path, encoding="utf-8") as f:
            return merge_look(json.load(f))
    except OSError as exc:
        raise ValueError("cannot read the look %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise ValueError("the look %s is not JSON: %s" % (path, exc))


def text_plan(cues_path, work, size, fps):
    """the text sequences of tools/mv_text.py for this picture (it is loaded from its file: tools/ is no package)"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mv_text.py")
    if not os.path.exists(path):
        raise ValueError("--cues needs tools/mv_text.py next to this tool")
    spec = importlib.util.spec_from_file_location("mv_text", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with open(cues_path, encoding="utf-8") as f:
        doc = json.load(f)
    return module.render_sequences(doc, os.path.join(work, "text"), size=size, fps=fps)


def render(args):
    fg = os.path.abspath(args.dancer)
    if not os.path.isfile(fg):
        raise ValueError("no such file: %s" % fg)
    look = load_look(args.look)
    out = os.path.abspath(args.out)
    if os.path.normcase(out) == os.path.normcase(fg):
        raise ValueError("OUT must not be the dancer's file")
    size, fps = probe(fg) if not (args.size and args.fps) else (None, None)
    size = parse_size(args.size) if args.size else size
    fps = args.fps or fps
    check_shutter(args.subframes, args.shutter)
    if args.subframes > 1:
        # the dancer's file runs at `subframes` times the output rate
        out_fps = fps / float(args.subframes)
        fps = int(round(out_fps)) if abs(out_fps - round(out_fps)) < 1e-3 else out_fps
    work = os.path.abspath(args.work or out + ".work")
    layers = write_layers(look, work, size, fps)
    plan = text_plan(args.cues, work, size, fps) if args.cues else None
    start = args.start
    duration = None if args.to is None else args.to - (start or 0.0)
    if duration is not None and duration <= 0:
        raise ValueError("--to must be after --from")
    folder = os.path.dirname(out)
    if folder:
        os.makedirs(folder, exist_ok=True)
    argv = ffmpeg_command(fg, out, layers["plate"], layers["light_pattern"], look, size, fps, plan=plan,
                          flare_pattern=layers["flare_pattern"], flare_frames=layers["flare_frames"],
                          start=start, duration=duration, offset=args.offset, subframes=args.subframes,
                          shutter=args.shutter, light_frames=layers["light_frames"])
    done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    result = {"out": out, "size": list(size), "fps": fps, "offset": args.offset, "subframes": args.subframes,
              "shutter": args.shutter, "work": work, "light_frames": layers["light_frames"],
              "flares": sum(1 for a in argv if a == layers["flare_pattern"]),
              "cues": len(plan["cues"]) if plan else 0, "warnings": plan["warnings"] if plan else [],
              "ffmpeg": done.returncode}
    if done.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("ffmpeg failed (%d): %s" % (done.returncode, done.stderr.strip()[-600:]))
    return result


def layers_command(args):
    look = load_look(args.look)
    if not args.size or not args.fps:
        raise ValueError("layers needs --size WxH and --fps N")
    return write_layers(look, os.path.abspath(args.work), parse_size(args.size), args.fps)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("render", help="lay the stage, the light, the glow (and the text) around the dancer")
    s.add_argument("dancer", help="the video MMD wrote with an alpha channel")
    s.add_argument("look", help="look.json: the settings that differ from the default")
    s.add_argument("out", help="the video to write (.mp4)")
    s.add_argument("--cues", help="text cues for tools/mv_text.py")
    s.add_argument("--work", help="where the layers go (default: OUT.work)")
    s.add_argument("--offset", type=float, default=0.0,
                   help="the song time at the dancer's first frame, in seconds (a chunk rendered from a later frame)")
    s.add_argument("--subframes", type=int, default=1,
                   help="the dancer was rendered at this many times the output rate: fold them into one frame (motion blur)")
    s.add_argument("--shutter", type=float, default=0.5,
                   help="with --subframes: the share of a frame the shutter is open (default 0.5, the film standard)")
    s.add_argument("--from", dest="start", type=float, help="start of an excerpt, in seconds of the song")
    s.add_argument("--to", type=float, help="end of an excerpt, in seconds of the song")
    s.add_argument("--size", help="WxH, when it is not to be read from the dancer's file")
    s.add_argument("--fps", type=float, help="frames per second, when it is not to be read from the dancer's file")
    s = sub.add_parser("layers", help="only write the plate, the light loop and the flare")
    s.add_argument("look")
    s.add_argument("work")
    s.add_argument("--size")
    s.add_argument("--fps", type=float)
    args = p.parse_args(argv)
    if getattr(args, "fps", None) is not None and args.fps == int(args.fps):
        args.fps = int(args.fps)
    try:
        result = render(args) if args.command == "render" else layers_command(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": {"type": "ValueError", "message": str(exc)}}, ensure_ascii=True))
        return 2
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 1
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
