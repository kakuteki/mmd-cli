"""Put a stage, light and glow around the dancer MMD rendered with an alpha channel: nothing happens in MMD.

    python tools/mv_look.py render DANCER.avi look.json OUT.mp4 [--cues cues.json] [--work DIR | --prepared DIR]
                                   [--from SECONDS] [--to SECONDS] [--size WxH] [--fps N] [--encoder x264|nvenc]
    python tools/mv_look.py layers look.json WORK --size WxH --fps N [--encoder x264|nvenc]
    python tools/mv_look.py prepare look.json WORK --size WxH --fps N [--cues cues.json] [--encoder x264|nvenc]

`prepare` draws the layers and the text once, for many renders (tools/mv_chunks.py --workers folds several chunks at the
same time): it writes them under WORK with prepared.json, the note of what they were made from (the look, the cue file,
the size, the rate and the code of this tool and tools/mv_text.py).  `render --prepared WORK` uses them as they are and
writes nothing there, after checking that note and that every frame is there and none more; its argv is the one
`render --work WORK` builds, so the video is the same byte for byte.  --encoder nvenc encodes with h264_nvenc on an NVIDIA
GPU instead of libx264 crf 16 (the default, and the encoder of the video to publish); with it `layers` and `prepare`
also encode a few frames to see that h264_nvenc works on the machine.

MMD writes the picture with an alpha channel when its background is blackened (menu 282, `mmd menu set 282
on`): both the PNG of `render image` and the uncompressed AVI of `render avi --codec 未圧縮` are BGRA with
alpha 0 where nothing was drawn (measured on v9.32, 2026-10-04).  So the dancer can be laid over any stage
afterwards, and light can be put behind her.  This tool makes that picture with Pillow (the layers) and
ffmpeg (the compositing), from back to front:

* the plate: a dark stage, a band of haze at the horizon and a pool of light behind the dancer (`plate`);
* the light: soft beams fanning down from above the frame and a few floating specks, drawn on black and
  screened over the plate.  It is a loop of `beams.loop_seconds` that closes (every motion in it is a
  whole number of sine periods per loop: `beams.cycles` and `bokeh.cycles`), repeated for the whole song with
  -stream_loop.  The picture repeats exactly once per loop: a loop of a phrase of the song (16 bars) with
  cycles of 2 and 3 sways about as fast as the default 12 s loop (periods of 13.7 and 9.1 s for 12 and 6) and
  repeats every 16 bars only;
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
Frame counts (flare.frames, camera.punch_frames) are frames of the song, as MMD counts them (SONG_FPS, 30 a second), and
the light loop is a whole number of them: a video at 60 fps (tools/mv_chunks.py --out-fps 60) has twice the frames of
each and shows on its frame 2n what one at 30 fps shows on its frame n.
The output has no sound: the song is added afterwards (ffmpeg -i OUT.mp4 -i song.wav -c:v copy ...).
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _sibling(name):
    """a tool next to this one, loaded from its file (tools/ is no package)"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_world = _sibling("mv_world")

DEFAULT_LOOK = {
    # colours are r, g, b of 255; horizon is the height of the haze band (0 top, 1 bottom)
    "plate": {"base": [10, 12, 20], "haze": [34, 44, 78], "pool": [70, 86, 140], "horizon": 0.68, "vignette": 0.45},
    # count beams over `spread` degrees, each swaying `sway` degrees; every `warm_every`-th one is warm.  The light is a
    # loop of `loop_seconds`; the beams sway cycles[0] and cycles[1] whole periods per loop, every other beam
    "beams": {"count": 6, "spread": 76.0, "sway": 3.0, "opacity": 0.55, "loop_seconds": 12, "cycles": [1, 2],
              "cool": [90, 110, 190], "warm": [200, 150, 80], "warm_every": 5},
    # the specks drift round cycles[0] times per loop and twinkle cycles[1] times
    "bokeh": {"count": 26, "opacity": 0.8, "seed": 7, "warm_share": 0.35, "cycles": [1, 2]},
    # tuned on the first real excerpt (hinata, 2026-10-05): 150 / 16 / 0.6 washed the white dress out and
    # turned the skin pink; this keeps the folds of the dress and still gives her a soft edge
    "glow": {"threshold": 175, "radius": 14, "strength": 0.45},
    # the flare lasts `frames` frames of the song (SONG_FPS: 0.4 s, at 30 fps and at 60)
    "flare": {"frames": 12, "strength": 0.85, "colour": [255, 244, 224]},
    # what the camera does at a flare: it punches in by `punch` of the picture and comes back within
    # `punch_frames` frames of the song, and red and blue part by `aberration` pixels for as long
    "camera": {"punch": 0.04, "punch_frames": 10, "aberration": 3},
    # the lens: the corners a little darker (vignette, 0 none to 1 strong) and a fine grain that changes with
    # every frame (0 none, up to about 10); both lie under the text in front
    "lens": {"vignette": 0.3, "grain": 3},
    "flares": [],
    # the plate, the light and a floor placed in the world and drawn from the camera (tools/mv_world.py); world 0 keeps
    # them fixed to the picture, as before
    "stage": copy.deepcopy(mv_world.DEFAULT_STAGE),
}
REFERENCE_HEIGHT = 720.0
LIGHT_SCALE = 2                  # the light is drawn at half size: it is all blur
SONG_FPS = 30                    # the frames the look counts in (flare.frames, camera.punch_frames): MMD's, of the song
# the encoders of --encoder: libx264 (the default, and the one of the video to publish) and h264_nvenc on an NVIDIA GPU
ENCODERS = ("x264", "nvenc")
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]
NVENC = ["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1",
         "-rc-lookahead", "32", "-bf", "3", "-profile:v", "high"]
PREPARED = "prepared.json"       # what `prepare` made its layers and text from (render --prepared checks it)


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
    for name in ("beams", "bokeh"):
        # a motion with a part of a period per loop would jump where the loop starts again
        if not all(int(v) == v and v >= 1 for v in look[name]["cycles"]):
            raise ValueError("%s.cycles are whole periods per loop, from 1: not %r" % (name, look[name]["cycles"]))
    _check_stage(look["stage"])
    return look


def _check_stage(stage):
    """the values of the stage section that tools/mv_world.py can draw (see its docstring)"""
    for key in ("world", "floor"):
        if stage[key] not in (0, 1):
            raise ValueError("stage.%s is 0 or 1, not %r" % (key, stage[key]))
    for key in ("floor_half", "floor_step", "floor_line", "pool_radius"):
        if not stage[key] > 0:
            raise ValueError("stage.%s must be above 0, not %r" % (key, stage[key]))
    if stage["radius"] < 0:
        raise ValueError("stage.radius is the radius of the cyc, or 0 for one infinitely far: not %r" % (stage["radius"],))
    if not 0 < stage["specks"] <= 360:
        raise ValueError("stage.specks is the degrees round the stage the specks lie over, above 0 up to 360: not %r"
                         % (stage["specks"],))
    if int(stage["floor_accent_every"]) != stage["floor_accent_every"] or stage["floor_accent_every"] < 0:
        raise ValueError("stage.floor_accent_every is a whole number, 0 for no accent lines")
    for key in ("pool", "shadow"):
        if not 0 <= stage[key] <= 1:
            raise ValueError("stage.%s is 0 (none) to 1, not %r" % (key, stage[key]))
    if any(c < 0 for c in stage["pool_colour"]):
        raise ValueError("stage.pool_colour is r, g, b from 0")
    if stage["world"] and not stage["floor"] and (stage["pool"] > 0 or stage["shadow"] > 0):
        raise ValueError("stage.pool and stage.shadow light and darken the floor this tool draws: they need stage.floor 1")


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
    """the frames of the light loop: at a rate that is a whole number of times SONG_FPS the loop is a whole number of
    frames of the song (so 60 fps has twice the frames of 30 and the same light at the same time), at any other the
    nearest whole number of its own frames"""
    seconds = float(look["beams"]["loop_seconds"])
    times = fps / float(SONG_FPS)
    if times == int(times) and times >= 1:
        return max(1, int(round(seconds * SONG_FPS))) * int(times)
    return max(1, int(round(seconds * fps)))


def song_frames(frames, fps):
    """a count of frames of the song (the look's) at the rate fps: as many seconds"""
    return max(1, int(round(int(frames) * fps / float(SONG_FPS))))


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
        # each beam sways a whole number of periods per loop (cycles, every other beam), out of step with its neighbours
        sway = settings["sway"] * math.sin(settings["cycles"][i % 2] * phase + 2.0 * math.pi * _unit(i, 1))
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
    drift, flicker = (float(c) for c in settings["cycles"])
    for i in range(count):
        x = _unit(i, seed + 1) * w + 0.02 * w * math.sin(drift * phase + 2.0 * math.pi * _unit(i, seed + 2))
        y = _unit(i, seed + 3) * h * 0.9 + 0.03 * h * math.sin(drift * phase + 2.0 * math.pi * _unit(i, seed + 4))
        r = (3.0 + 11.0 * _unit(i, seed + 5)) * h / REFERENCE_HEIGHT * LIGHT_SCALE / 2.0 + 1.0
        twinkle = 0.7 + 0.3 * math.sin(flicker * phase + 2.0 * math.pi * _unit(i, seed + 6))
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
    """the plate, the light loop (at half size) and the flare frames under `work`; returns where they are.  A note of
    `prepare` in `work` goes first: it vouches for the layers prepare drew, not for these.  A stage in the world (look
    stage.world) has no plate and no loop of light: the frames of the stage (tools/mv_world.py) hold them"""
    os.makedirs(work, exist_ok=True)
    forget_prepared(work)
    small = (max(2, size[0] // LIGHT_SCALE), max(2, size[1] // LIGHT_SCALE))
    count = light_frame_count(look, fps)
    plate_path = light_pattern = None
    if not look["stage"]["world"]:
        plate_path = os.path.join(work, "plate.png")
        plate(size, look["plate"]).save(plate_path)
        light_dir = os.path.join(work, "light")
        os.makedirs(light_dir, exist_ok=True)
        _clear_frames(light_dir, "light_")
        for i in range(count):
            light_frame(small, look, i, count).save(os.path.join(light_dir, "light_%05d.png" % i))
        light_pattern = _slashes(os.path.join(light_dir, "light_%05d.png"))
    flare_dir = os.path.join(work, "flare")
    os.makedirs(flare_dir, exist_ok=True)
    # flare.frames are frames of the song: at 60 fps the flare has twice the frames and fades in steps half as large
    flare_frames = song_frames(look["flare"]["frames"], fps)
    flare = dict(look["flare"], frames=flare_frames)
    _clear_frames(flare_dir, "flare_")
    for i in range(flare_frames):
        flare_frame(small, flare, i).save(os.path.join(flare_dir, "flare_%05d.png" % i))
    return {"plate": plate_path, "light_pattern": light_pattern, "light_frames": count,
            "flare_pattern": _slashes(os.path.join(flare_dir, "flare_%05d.png")), "flare_frames": flare_frames}


def _clear_frames(folder, prefix):
    """the frames an earlier look left in the work folder: ffmpeg reads a numbered sequence until a number is missing, so
    a longer loop or flare of before would come back (review 11; mv_text clears its cue frames the same way)"""
    for name in os.listdir(folder):
        if name.startswith(prefix) and name.endswith(".png"):
            os.remove(os.path.join(folder, name))


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


def encoder_args(encoder):
    """the ffmpeg arguments of an encoder of --encoder, from -c:v on (the pixel format and the file follow them)"""
    if encoder == "x264":
        return list(X264)
    if encoder == "nvenc":
        return ["-c:v", "h264_nvenc"] + NVENC
    raise ValueError("--encoder is x264 (libx264, the default) or nvenc (h264_nvenc on an NVIDIA GPU), not %r" % (encoder,))


def check_encoder(encoder):
    """nvenc: encode a few frames with h264_nvenc (it needs an NVIDIA GPU, its driver and an ffmpeg built with it), so that
    a machine without it is found before anything is rendered.  libx264 is not tried: the default does what it did"""
    args = encoder_args(encoder)
    if encoder == "x264":
        return
    done = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=30", "-frames:v", "3"]
                          + args + ["-pix_fmt", "yuv420p", "-f", "null", "-"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise ValueError("the encoder %s (%s) does not work here: %s" % (encoder, args[1], (done.stderr or "").strip()[-300:]))


def ffmpeg_command(fg, out, plate_path, light_pattern, look, size, fps, plan=None, flare_pattern=None, flare_frames=0,
                   start=None, duration=None, offset=0.0, subframes=1, shutter=1.0, light_frames=None, encoder="x264",
                   stage=None):
    """the ffmpeg argv that lays plate, light, back text, dancer, glow, front text and flares over each other
    (see the module docstring).  `offset` is the song time at the dancer's first frame (a chunk of the song
    rendered from a later frame); `start` and `duration` cut an excerpt, in seconds of the song.  With
    `light_frames` (the length of the light loop) an excerpt shows the loop where the whole song has it at that time,
    and a flare that began before the excerpt has its punch part spent: the seams of a song rendered in chunks
    (tools/mv_chunks.py) then hide in the cuts (review 10).  `encoder` (ENCODERS) changes the arguments from -c:v to the
    pixel format and nothing else.  `stage` ({"pattern", "first"}: the frames of tools/mv_world.py, numbered by the frame
    of the video from the song's start, and the excerpt's first) takes the place of the plate and the light for a look
    whose stage lies in the world"""
    w, h = size
    coding = encoder_args(encoder)
    taken = check_shutter(subframes, shutter)
    if (stage is not None) != bool(look["stage"]["world"]):
        raise ValueError("a stage in the world (look stage.world 1) is drawn from its frames, and only such a stage is")
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
    if stage is not None:
        # every frame of the stage is its own (the camera moves): the excerpt reads them from its first
        argv += ["-r", _number(fps * subframes), "-i", fg, "-framerate", str(fps), "-start_number", str(int(stage["first"])),
                 "-i", stage["pattern"]]
        next_input = 2
        phase = 0
    else:
        argv += ["-r", _number(fps * subframes), "-i", fg, "-loop", "1", "-framerate", str(fps), "-i", plate_path]
        # the light is one loop repeated over the whole song: an excerpt drops the loop's first frames up to its song time
        # (one input, trimmed in the graph; two inputs joined with concat came out a frame off for a first part of 1 or 3)
        phase = int(round(clip_start * fps)) % int(light_frames) if light_frames else 0
        argv += ["-stream_loop", "-1", "-framerate", str(fps), "-i", light_pattern]
        next_input = 3
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
    punch_span = look["camera"]["punch_frames"] / float(SONG_FPS)          # frames of the song, whatever the rate
    for at in look["flares"]:
        if not flare_pattern:
            continue
        # the punch runs for punch_frames whether or not the flare's picture (flare.frames) is still on
        since = float(at) - clip_start
        if since > -punch_span and (duration is None or since < duration):
            flare_starts.append(since)
        seen = _visible(float(at), flare_frames, fps, clip_start, duration)
        if seen is None:
            continue
        offset, skip = seen
        argv += ["-framerate", str(fps), "-start_number", str(skip), "-i", flare_pattern]
        overlays["flare"].append((next_input, offset, 0, 0, (w, h)))
        next_input += 1

    if stage is not None:
        parts = ["[1:v]format=gbrp[stage]"]
    else:
        light_in = "[2:v]trim=start_frame=%d,setpts=PTS-STARTPTS," % phase if phase else "[2:v]"
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
    span = punch_span
    hits = flare_starts if span > 0 else []
    if hits and camera["punch"] > 0:
        # 1 + punch * (1 - (t - T) / span)^2 from each flare time T on; the picture is scaled about its centre
        amount = "+".join("%s*pow(max(0,1-(%s)/%.3f),2)*gte(t,%.3f)" % (_number(camera["punch"]), _since(at), span, at)
                          for at in hits)
        sw, sh = "trunc(%d*(1+%s)/2)*2" % (w, amount), "trunc(%d*(1+%s)/2)*2" % (h, amount)
        # crop keeps iw and ih of the first frame it sees, so its x and y come from the same expression of t as the
        # scale: the picture is cut out of the middle of every scaled frame (review 11: (iw-W)/2 left it at the top left)
        parts.append("[%s]scale=w='%s':h='%s':eval=frame:flags=bilinear,crop=%d:%d:x='(%s-%d)/2':y='(%s-%d)/2'[punch]"
                     % (state["label"], sw, sh, w, h, sw, w, sh, h))
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
    argv += ["-filter_complex", ";".join(parts), "-map", "[out]", "-an", "-r", str(fps)] + coding
    argv += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
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
    forget_prepared(work)
    return module.render_sequences(doc, os.path.join(work, "text"), size=size, fps=fps)


# ---- layers prepared once for many renders ---------------------------------------------------

def forget_prepared(work):
    """take the note of `prepare` out of `work` before anything draws there: `render --work` and `layers` into a prepared
    folder would otherwise leave a note that vouches for layers it did not make (review of fast-render, 2-d)"""
    note_path = os.path.join(os.path.abspath(work), PREPARED)
    if os.path.exists(note_path):
        os.remove(note_path)


def _same_folder(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def prepared_key(look, size, fps, cues_path, world=None):
    """what the layers and the text of `prepare` are made from: the values of the look, the size and the rate of the video,
    the bytes of the cue file, and the code that draws them (this tool, tools/mv_text.py and tools/mv_world.py).  For a
    stage in the world (`world`, see world_inputs) also the bytes of the camera motion and of the dancer's files, the code
    that reads them (mmd_cli/fk.py and the readers of vmd and pmx) and the shutter.  The fonts mv_text finds on the machine
    are not in it (tools/mv_chunks.py -Resume does not see them either)"""
    values = {"look": look, "size": [int(size[0]), int(size[1])], "fps": fps}
    if world is not None:
        values["shutter"] = [int(world["subframes"]), float(world["shutter"])]
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8"))
    here = os.path.dirname(os.path.abspath(__file__))
    files = [("cues", cues_path), ("mv_look", os.path.join(here, "mv_look.py")),
             ("mv_text", os.path.join(here, "mv_text.py")), ("mv_world", os.path.join(here, "mv_world.py"))]
    if world is not None:
        package = os.path.join(os.path.dirname(here), "mmd_cli")
        files += [("camera", world["camera"]), ("model", world["model"])] + [("motion", m) for m in world["motions"]]
        files += [("fk", os.path.join(package, "fk.py")), ("vmd", os.path.join(package, "formats", "vmd.py")),
                  ("pmx", os.path.join(package, "formats", "pmx.py"))]
    for label, path in files:
        digest.update(("\0%s\0" % label).encode("ascii"))
        if path is None:
            digest.update(b"none")
            continue
        try:
            with open(path, "rb") as f:
                digest.update(hashlib.sha256(f.read()).digest())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()


def prepare(look, work, size, fps, cues_path=None, world=None):
    """write the plate, the light loop, the flare and the text sequences under `work` once, and then PREPARED, the note of
    what they were made from.  The old note goes first, so that a prepare that fails half way leaves no note that vouches
    for half written layers.  A stage in the world (`world`, see world_inputs) draws its frames for the whole song (as far
    as the camera motion has keys) in place of the plate and the light loop"""
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    note_path = os.path.join(work, PREPARED)
    forget_prepared(work)
    layers = write_layers(look, work, size, fps)
    plan = text_plan(cues_path, work, size, fps) if cues_path else None
    note = {"key": prepared_key(look, size, fps, cues_path, world), "work": _slashes(work), "layers": layers, "text": plan}
    if world is not None:
        last = world["track"][1][-1]
        frames = int(round((last + 1) * fps / float(SONG_FPS)))
        note["stage"] = mv_world.write_stage(look, work, size, fps, world["track"], 0, frames, layers["light_frames"],
                                             world["subframes"], world["shutter"], world["figure"])
    with open(note_path + ".part", "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=True, indent=1)
    os.replace(note_path + ".part", note_path)
    return note


def _whole_sequence(pattern, frames):
    """frames 0 .. frames - 1 of a printf pattern are there and the next one is not: ffmpeg reads a numbered sequence until a
    number is missing, so a frame more would lengthen the loop, the flare or the cue"""
    return all(os.path.isfile(pattern % i) for i in range(int(frames))) and not os.path.exists(pattern % int(frames))


def load_prepared(work, look, size, fps, cues_path=None, world=None):
    """the layers, the text plan and the stage (None but in the world) `prepare` wrote under `work`, after checking that
    they were made there, from this look, cue file, size and rate (and camera, dancer and shutter), by this code, and that
    every frame of them is there (and none more).  Nothing is written"""
    again = "run `mv_look.py prepare` again"
    note_path = os.path.join(os.path.abspath(work), PREPARED)
    try:
        with open(note_path, encoding="utf-8") as f:
            note = json.load(f)
        layers, plan, stage = note["layers"], note["text"], note.get("stage")
    except OSError:
        raise ValueError("%s holds no prepared layers (no %s): run `mv_look.py prepare` first" % (work, PREPARED))
    except (ValueError, KeyError, TypeError):
        raise ValueError("%s is not a note of `prepare`: %s" % (note_path, again))
    if not isinstance(note.get("work"), str) or not _same_folder(note["work"], work):
        raise ValueError("the layers in %s were prepared in %s, and their paths name that folder: %s" % (work, note.get("work"), again))
    if note.get("key") != prepared_key(look, size, fps, cues_path, world):
        raise ValueError("the layers in %s were prepared from another look, cue file, size or rate (or camera, dancer or "
                         "shutter), or by another version of tools/mv_look.py, mv_text.py or mv_world.py: %s" % (work, again))
    sequences = [(layers["flare_pattern"], layers["flare_frames"])]
    sequences += [(cue["pattern"], cue["frames"]) for cue in (plan or {}).get("cues", [])]
    if world is None:
        sequences.append((layers["light_pattern"], layers["light_frames"]))
        whole = os.path.isfile(layers["plate"])
    else:
        whole = isinstance(stage, dict) and stage.get("first") == 0
        if whole:
            sequences.append((stage["pattern"], stage["frames"]))
    if not whole or not all(_whole_sequence(p, n) for p, n in sequences):
        raise ValueError("the layers in %s are not as `prepare` left them (a frame is missing or one too many): %s" % (work, again))
    return layers, plan, stage


# ---- the stage in the world (tools/mv_world.py) ------------------------------------------------

# the floor accessory of tools/make_stage.py in MMD's picture: its plane at alpha 235, its lines 246 and 251.  A dancer's file
# with more of its first picture than FLOOR_SHARE at these was rendered with the floor (her own pixels are opaque or clear)
FLOOR_ALPHA = (226, 252)
FLOOR_SHARE = 0.05


def world_inputs(look, camera=None, model=None, motions=(), subframes=1, shutter=0.5):
    """what a stage in the world is drawn from (None for a look fixed to the picture, which reads none of it): the camera
    motion MMD renders with and, when the floor takes her pool of light or her shadows, the dancer (model and motions in the
    order MMD loads them), and the shutter of the fold (the floor's motion blur)"""
    stage = look["stage"]
    if not stage["world"]:
        return None
    if not camera:
        raise ValueError("the look places the stage in the world (stage.world 1): give the camera motion MMD renders with, "
                         "--camera CAMERA.vmd (tools/mv_chunks.py gives it with \"world\": true in the plan)")
    check_shutter(subframes, shutter)
    world = {"camera": os.path.abspath(camera), "model": None, "motions": [], "figure": None,
             "subframes": int(subframes), "shutter": float(shutter)}
    world["track"] = mv_world.camera_track(world["camera"])
    if stage["floor"] and (stage["pool"] > 0 or stage["shadow"] > 0):
        if not model or not motions:
            raise ValueError("stage.pool and stage.shadow follow the dancer: give --model MODEL.pmx and her --motion files, "
                             "in the order MMD loads them")
        world["model"], world["motions"] = os.path.abspath(model), [os.path.abspath(m) for m in motions]
        world["figure"] = mv_world.Figure.from_files(world["model"], world["motions"])
    return world


def floor_share(fg):
    """the share of the first picture of the dancer's file at the alpha of the floor accessory (FLOOR_ALPHA)"""
    done = subprocess.run(["ffmpeg", "-v", "error", "-i", fg, "-frames:v", "1", "-vf", "alphaextract", "-f", "rawvideo",
                           "-pix_fmt", "gray", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    data = np.frombuffer(done.stdout or b"", dtype=np.uint8)
    if done.returncode != 0 or data.size == 0:
        raise ValueError("cannot read the first picture of %s: %s"
                         % (fg, (done.stderr or b"").decode("utf-8", "replace").strip()[-300:]))
    return float(((data >= FLOOR_ALPHA[0]) & (data <= FLOOR_ALPHA[1])).mean())


def dancer_frames(fg):
    """the number of frames of the dancer's file (its header)"""
    done = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames", "-of",
                           "csv=p=0", fg], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        return int((done.stdout or "").strip())
    except ValueError:
        raise ValueError("cannot read how many frames %s has: give --to" % fg)


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
    encoder_args(args.encoder)
    world = world_inputs(look, args.camera, args.model, args.motion, args.subframes, args.shutter)
    if world is not None and look["stage"]["floor"]:
        share = floor_share(fg)
        if share > FLOOR_SHARE:
            raise ValueError("%.0f %% of the dancer's first picture has the alpha of MMD's floor accessory (%d to %d): the look "
                             "draws the floor itself (stage.floor 1), so leave the floor accessory out of the MMD render "
                             "(the plan's accessories), or let MMD draw it with stage.floor 0" % ((100 * share,) + FLOOR_ALPHA))
    if args.subframes > 1:
        # the dancer's file runs at `subframes` times the output rate
        out_fps = fps / float(args.subframes)
        fps = int(round(out_fps)) if abs(out_fps - round(out_fps)) < 1e-3 else out_fps
    start = args.start
    duration = None if args.to is None else args.to - (start or 0.0)
    if duration is not None and duration <= 0:
        raise ValueError("--to must be after --from")
    if world is not None:
        # the frames of the video this excerpt shows, numbered from the song's start (the stage's frames are)
        offset = float(args.offset or 0.0)
        clip_start = float(start) if start is not None else offset
        first = int(round(clip_start * fps))
        if duration is not None:
            count = int(round(duration * fps))
        else:
            count = dancer_frames(fg) // int(args.subframes) - int(round((clip_start - offset) * fps))
        if count < 1:
            raise ValueError("the excerpt has no frame of the dancer")
    stage = None
    if args.prepared:
        # the layers and the text `prepare` wrote once for many renders (tools/mv_chunks.py --workers): read, never written
        work = os.path.abspath(args.prepared)
        layers, plan, drawn = load_prepared(work, look, size, fps, args.cues, world)
        if world is not None:
            if first < 0 or first + count > drawn["frames"]:
                raise ValueError("the stage prepared in %s has the frames 0 to %d of the video, and this excerpt needs %d to "
                                 "%d: prepare with the camera of the whole song" % (work, drawn["frames"] - 1, first, first + count - 1))
            stage = {"pattern": drawn["pattern"], "first": first, "frames": count}
    else:
        work = os.path.abspath(args.work or out + ".work")
        layers = write_layers(look, work, size, fps)
        plan = text_plan(args.cues, work, size, fps) if args.cues else None
        if world is not None:
            stage = mv_world.write_stage(look, work, size, fps, world["track"], first, count, layers["light_frames"],
                                         world["subframes"], world["shutter"], world["figure"])
    folder = os.path.dirname(out)
    if folder:
        os.makedirs(folder, exist_ok=True)
    argv = ffmpeg_command(fg, out, layers["plate"], layers["light_pattern"], look, size, fps, plan=plan,
                          flare_pattern=layers["flare_pattern"], flare_frames=layers["flare_frames"],
                          start=start, duration=duration, offset=args.offset, subframes=args.subframes,
                          shutter=args.shutter, light_frames=layers["light_frames"], encoder=args.encoder, stage=stage)
    done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    result = {"out": out, "size": list(size), "fps": fps, "offset": args.offset, "subframes": args.subframes,
              "shutter": args.shutter, "work": work, "light_frames": layers["light_frames"],
              "flares": sum(1 for a in argv if a == layers["flare_pattern"]),
              "cues": len(plan["cues"]) if plan else 0, "warnings": plan["warnings"] if plan else [],
              "ffmpeg": done.returncode}
    if stage is not None:
        result["stage"] = {"first": stage["first"], "frames": stage["frames"]}
    if args.prepared:
        result["prepared"] = True
    if args.encoder != "x264":
        result["encoder"] = args.encoder
    if done.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("ffmpeg failed (%d): %s" % (done.returncode, done.stderr.strip()[-600:]))
    return result


def layers_command(args):
    look = load_look(args.look)
    if not args.size or not args.fps:
        raise ValueError("layers needs --size WxH and --fps N")
    check_encoder(args.encoder)
    # a stage in the world: its camera and dancer are read here, so that a wrong one stops a run before MMD renders
    world_inputs(look, args.camera, args.model, args.motion)
    return write_layers(look, os.path.abspath(args.work), parse_size(args.size), args.fps)


def prepare_command(args):
    look = load_look(args.look)
    if not args.size or not args.fps:
        raise ValueError("prepare needs --size WxH and --fps N")
    check_encoder(args.encoder)
    world = world_inputs(look, args.camera, args.model, args.motion, args.subframes, args.shutter)
    note = prepare(look, args.work, parse_size(args.size), args.fps, args.cues, world)
    plan = note["text"]
    result = dict(note["layers"], work=note["work"], cues=len(plan["cues"]) if plan else 0,
                  warnings=plan["warnings"] if plan else [])
    if "stage" in note:
        result["stage"] = {"first": note["stage"]["first"], "frames": note["stage"]["frames"]}
    return result


def _world_arguments(s):
    """what a look whose stage lies in the world is drawn from (a look fixed to the picture reads none of it)"""
    s.add_argument("--camera", help="a stage in the world: the camera motion (.vmd) MMD renders the dancer with")
    s.add_argument("--model", help="a stage in the world with a pool of light or shadows: the dancer's model (.pmx)")
    s.add_argument("--motion", action="append", default=[],
                   help="... and her motions (.vmd), each with its own --motion, in the order MMD loads them")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("render", help="lay the stage, the light, the glow (and the text) around the dancer")
    s.add_argument("dancer", help="the video MMD wrote with an alpha channel")
    s.add_argument("look", help="look.json: the settings that differ from the default")
    s.add_argument("out", help="the video to write (.mp4)")
    s.add_argument("--cues", help="text cues for tools/mv_text.py")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--work", help="where the layers go (default: OUT.work)")
    g.add_argument("--prepared", help="use the layers and the text `prepare` wrote in this folder, writing nothing there")
    s.add_argument("--encoder", choices=ENCODERS, default="x264",
                   help="x264 (libx264 crf 16, the default) or nvenc (h264_nvenc on an NVIDIA GPU)")
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
    _world_arguments(s)
    s = sub.add_parser("layers", help="only write the plate, the light loop and the flare")
    s.add_argument("look")
    s.add_argument("work")
    s.add_argument("--size")
    s.add_argument("--fps", type=float)
    s.add_argument("--encoder", choices=ENCODERS, default="x264", help="nvenc: also check that h264_nvenc works here")
    _world_arguments(s)
    s = sub.add_parser("prepare", help="write the layers and the text once, for many renders with --prepared")
    s.add_argument("look")
    s.add_argument("work")
    s.add_argument("--size")
    s.add_argument("--fps", type=float)
    s.add_argument("--cues", help="text cues for tools/mv_text.py")
    s.add_argument("--encoder", choices=ENCODERS, default="x264", help="nvenc: also check that h264_nvenc works here")
    _world_arguments(s)
    s.add_argument("--subframes", type=int, default=1,
                   help="a stage in the world: the renders fold this many dancer frames into one (the floor's motion blur)")
    s.add_argument("--shutter", type=float, default=0.5, help="a stage in the world: the renders' --shutter")
    args = p.parse_args(argv)
    if getattr(args, "fps", None) is not None and args.fps == int(args.fps):
        args.fps = int(args.fps)
    commands = {"render": render, "layers": layers_command, "prepare": prepare_command}
    try:
        result = commands[args.command](args)
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
