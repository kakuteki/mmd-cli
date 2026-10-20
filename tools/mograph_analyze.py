"""Measure the motion graphics of a video in numbers: how its shots change and when against the beat, and the graphic
things on its frames.

    python tools/mograph_analyze.py events VIDEO OUT.json [--from S] [--to S] [--voice VOICE.json] [--size 128x72]
                                           # every frame: cuts, flashes, fades, dissolves, zoom punches, shakes,
                                           # glitch frames, colour flashes, and how many fall on the beat
    python tools/mograph_analyze.py elements VIDEO OUT.json [--from S] [--to S] [--frames 60] [--height 720]
                                           # sampled frames: particles and bokeh, long straight lines
    python tools/mograph_analyze.py compare OUT.md OUT.json --ref A.json ... --ours X.json ...

Why (2026-10-20, typoref): the request is to take the lighting, the kinetic typography of the lyrics and the motion
graphics of the YouTube channel @PizaCG as the reference for our MV.  tools/look_analyze.py measures the look of a frame
and tools/typo_analyze.py the text; this tool measures the rest of what an editor lays on and between the shots.

events: every frame is read small (128 x 72, the colour as tools/look_analyze.py reads it) and kept as a few numbers:
  the cuts and the flashes of tools/look_analyze.py (on the frame made 32 x 18); a fade: the picture going down to black
  (mean Y' under FADE_BLACK) or up to white (over FADE_WHITE) over at least FADE_LEAST frames and staying there; a
  dissolve: a change spread over 3 to 16 frames whose middle frame is the mean of its ends (a camera move is not:
  its middle is the picture moved, not two pictures over each other); the camera's motion from frame to frame (the
  similarity transform fitted to the optical flow: shift, scale, turn): a zoom punch is a scale jump of at least
  PUNCH_LEAST within three frames, PUNCH_OVER times the scale's change round it (a smooth zoom is not), and the shake is
  the rms of the shift less its running mean over SHAKE_WINDOW; a glitch frame: red and blue drawn apart across the
  picture by at least GLITCH_SPLIT (720 line px); a colour flash: the mean chroma rising by COLOUR_RISE over its
  running median for a short time and coming back.  Each kind's events against the beat (from tools/typo_analyze.py's
  voice run): the share within a frame of a beat, and the chance of that.
elements: particles are the small round bright spots (scale-normalised Laplacian of Gaussian, local maxima over
  space and scale, each standing PARTICLE_LEAST above the ground round it); bokeh are those of radius from BOKEH_SIGMA
  up (a defocused light); long straight lines from OpenCV's line segment detector, the two edges of one thick line
  joined, at least LINE_LEAST of the frame's height long.
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_LAZY = {}


def _tool(name):
    if name not in _LAZY:
        spec = importlib.util.spec_from_file_location("_mograph_" + name, os.path.join(HERE, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LAZY[name] = module
    return _LAZY[name]


def _cv2():
    if "cv2" not in _LAZY:
        import cv2
        _LAZY["cv2"] = cv2
    return _LAZY["cv2"]


def _ndi():
    if "ndi" not in _LAZY:
        import scipy.ndimage
        _LAZY["ndi"] = scipy.ndimage
    return _LAZY["ndi"]


REFERENCE_HEIGHT = 720.0
FADE_BLACK = 0.06                 # mean Y' under this: black
FADE_WHITE = 0.90                 # over this: white
FADE_LEAST = 3                    # frames the picture takes going there at least
DISSOLVE_W = (2, 3, 5, 8)         # half widths (frames) tried for a dissolve
DISSOLVE_LEAST = 0.05             # mean |Y' change| between its ends at least this
DISSOLVE_MID = 0.25               # its middle frame within this share of that change of the mean of its ends
PUNCH_LEAST = 0.08                # log scale change within three frames for a zoom punch, and
PUNCH_OVER = 6.0                  # this many times the scale's usual change round it (a second each side)
PUNCH_MERGE = 0.3                 # s: punches closer than this are one
SHAKE_WINDOW = 0.2                # s: the shake is the shift less its running mean over this
GLITCH_SPLIT = 8.0                # 720 line px between red and blue across the picture: a glitch frame
SPLIT_REACH = 6                   # px searched at the read size
COLOUR_RISE = 12.0                # C*ab over the running median: a colour flash
COLOUR_LONGEST = 0.6              # s
BEAT_REACH = 0.01                 # s added to a frame either side: on the beat


def _luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _mean_lab(rgb):
    LA = _tool("look_analyze")
    m = np.asarray(rgb, np.float64).reshape(-1, 3).mean(axis=0)
    return LA.rgb_to_lab(m[None, :])[0]


def _similarity(flow, border=4):
    """the similarity transform (dx, dy, log scale, turn) fitted to an optical flow field (least squares about the
    middle, the border left out)"""
    h, w = flow.shape[:2]
    ys, xs = np.mgrid[border:h - border, border:w - border].astype(np.float64)
    u = flow[border:h - border, border:w - border, 0].ravel()
    v = flow[border:h - border, border:w - border, 1].ravel()
    x = (xs - (w - 1) / 2.0).ravel()
    y = (ys - (h - 1) / 2.0).ravel()
    # u = a x - b y + tx ; v = b x + a y + ty
    A = np.zeros((2 * x.size, 4))
    A[0::2, 0], A[0::2, 1], A[0::2, 2] = x, -y, 1.0
    A[1::2, 0], A[1::2, 1], A[1::2, 3] = y, x, 1.0
    rhs = np.empty(2 * x.size)
    rhs[0::2], rhs[1::2] = u, v
    (a, b, tx, ty), *_ = np.linalg.lstsq(A, rhs, rcond=None)
    return float(tx), float(ty), float(math.log(max(1e-6, math.hypot(1.0 + a, b)))), float(math.degrees(math.atan2(b, 1.0 + a)))


def _split(rgb, reach=SPLIT_REACH):
    """px (at the read size) between the red and the blue edges across the picture: the shift of the column profiles of
    their horizontal gradients that lines them up best (to a fraction of a px)"""
    gr = np.abs(np.diff(rgb[..., 0], axis=1)).sum(axis=0)
    gb = np.abs(np.diff(rgb[..., 2], axis=1)).sum(axis=0)
    n = len(gr)
    best, vals = None, {}
    for k in range(-reach, reach + 1):
        x, y = (gr[k:], gb[:n - k]) if k >= 0 else (gr[:n + k], gb[-k:])
        x = x - x.mean()
        y = y - y.mean()
        den = math.sqrt(float((x * x).sum() * (y * y).sum()))
        vals[k] = float((x * y).sum() / den) if den > 1e-12 else -1.0
        if best is None or vals[k] > vals[best]:
            best = k
    if best is None or vals[best] < 0.3:
        return 0.0
    if -reach < best < reach:
        a, b, c = vals[best - 1], vals[best], vals[best + 1]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        return abs(best + max(-0.5, min(0.5, frac)))
    return float(abs(best))


class EventReader:
    """the per-frame numbers of the events, a frame at a time (frames: RGB 0..1 at the read size)"""

    def __init__(self, fps):
        self.fps = float(fps)
        self.small, self.mean_y, self.chroma, self.motion, self.split = [], [], [], [], []
        self._prev = None
        self._h = None

    def push(self, rgb):
        cv2 = _cv2()
        rgb = np.asarray(rgb, np.float64)
        h, w = rgb.shape[:2]
        self._h = h
        y = _luma(rgb)
        self.small.append(cv2.resize(y.astype(np.float32), (32, 18), interpolation=cv2.INTER_AREA))
        self.mean_y.append(float(y.mean()))
        lab = _mean_lab(rgb)
        self.chroma.append(float(math.hypot(lab[1], lab[2])))
        g = np.clip(y * 255.0, 0, 255).astype(np.uint8)
        if self._prev is None:
            self.motion.append((0.0, 0.0, 0.0, 0.0))
        else:
            flow = cv2.calcOpticalFlowFarneback(self._prev, g, None, 0.5, 3, 9, 3, 5, 1.1, 0)
            self.motion.append(_similarity(flow))
        self._prev = g
        self.split.append(_split(rgb) * REFERENCE_HEIGHT / h)

    def finish(self, beats=None, start=0.0):
        return _events(self, beats, start)


def _runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def _on_beat(times, beats, fps):
    b = np.asarray(beats or [], np.float64)
    if b.size < 2 or not len(times):
        return float("nan"), float("nan")
    reach = 1.0 / fps + BEAT_REACH
    near = [np.min(np.abs(b - t)) <= reach for t in times]
    return float(np.mean(near)), float(min(1.0, 2 * reach / float(np.median(np.diff(b)))))


def _events(r, beats=None, start=0.0):
    LA = _tool("look_analyze")
    fps = r.fps
    n = len(r.mean_y)
    small = np.array(r.small, np.float64)
    series = np.array(r.mean_y)
    chroma = np.array(r.chroma)
    flash_events, flash_sum = LA.flashes(series, fps)
    # colour flashes: the chroma's short rises
    half = max(1, int(round(0.5 * fps)))
    rise = chroma - LA._running_median(chroma, half)
    colour = []
    for a, b in _runs(rise >= COLOUR_RISE):
        before, after = chroma[max(0, a - 8):a], chroma[b:b + 8]
        if b - a <= COLOUR_LONGEST * fps and len(before) and len(after) and \
                abs(after.mean() - before.mean()) < 0.5 * float(rise[a:b].max()):
            colour.append({"frame": int(a), "frames": int(b - a), "rise": float(rise[a:b].max())})
    quiet = list(flash_events) + [{"start": c["frame"], "end": c["frame"] + c["frames"]} for c in colour]
    cut_list, cut_sum = LA.cuts(small, fps, quiet)
    cut_set = set(cut_list)
    # fades to black and to white
    fades = []
    for to, mask in (("black", series < FADE_BLACK), ("white", series > FADE_WHITE)):
        for a, b in _runs(mask):
            if b - a < 2 or a < FADE_LEAST:
                continue
            ramp = series[max(0, a - int(fps)):a]
            if to == "black":
                ok = ramp.size and ramp.max() - series[a] > 0.1 and (series[a - FADE_LEAST:a] > FADE_BLACK).all()
            else:
                ok = ramp.size and series[a] - ramp.min() > 0.1 and (series[a - FADE_LEAST:a] < FADE_WHITE).all()
            if ok and not any(a - 1 <= c <= a + 1 for c in cut_set):
                fades.append({"frame": int(a), "frames": int(b - a), "to": to})
    in_fade = np.zeros(n, bool)
    for f in fades:
        in_fade[max(0, f["frame"] - int(fps)):f["frame"] + f["frames"] + int(fps)] = True
    # dissolves: a change spread over frames whose middle is the mean of its ends
    d = np.zeros(n)
    d[1:] = np.abs(np.diff(small, axis=0)).mean(axis=(1, 2))
    marks = np.zeros(n, bool)
    for w in DISSOLVE_W:
        for k in range(w, n - w):
            if in_fade[k] or any(k - w < c <= k + w for c in cut_set):
                continue
            D = float(np.abs(small[k + w] - small[k - w]).mean())
            if D < DISSOLVE_LEAST:
                continue
            M = float(np.abs(small[k] - 0.5 * (small[k - w] + small[k + w])).mean())
            if M <= DISSOLVE_MID * D and d[k - w + 1:k + w + 1].max() < 0.6 * D:
                marks[k] = True
    dissolves = []
    for a, b in _runs(marks):
        mid = (a + b - 1) // 2
        # its length: the frames round it changing by more than a quarter of the most
        top = d[max(0, a - 10):min(n, b + 10)].max()
        lo, hi = mid, mid
        while lo > 0 and d[lo] > 0.25 * top:
            lo -= 1
        while hi < n - 1 and d[hi + 1] > 0.25 * top:
            hi += 1
        dissolves.append({"frame": int(mid), "frames": int(hi - lo)})
    # the camera: zoom punches and shake (frames at a cut left out)
    mo = np.array(r.motion, np.float64)
    bad = np.zeros(n, bool)
    for c in cut_set:
        bad[max(0, c - 1):c + 2] = True
    for e in flash_events:
        bad[max(0, e["start"] - 1):e["end"] + 1] = True
    z = np.where(bad, 0.0, mo[:, 2])
    s3 = np.convolve(z, np.ones(3), mode="same")
    usual = LA._running_median(np.abs(z), int(round(fps)))
    cand = (np.abs(s3) >= PUNCH_LEAST) & (np.abs(s3) >= PUNCH_OVER * (3 * usual + 1e-3))
    punches = []
    for a, b in _runs(cand):
        k = a + int(np.argmax(np.abs(s3[a:b])))
        if punches and k - punches[-1]["frame"] <= PUNCH_MERGE * fps:
            continue
        punches.append({"frame": int(k), "log_scale": float(s3[k])})
    scale = REFERENCE_HEIGHT / float(r._h or REFERENCE_HEIGHT)
    tx = np.where(bad, np.nan, mo[:, 0])
    ty = np.where(bad, np.nan, mo[:, 1])
    k = max(3, int(round(SHAKE_WINDOW * fps)) | 1)
    good = ~np.isnan(tx)
    hp = []
    if good.sum() > k:
        fx = np.interp(np.arange(n), np.nonzero(good)[0], tx[good])
        fy = np.interp(np.arange(n), np.nonzero(good)[0], ty[good])
        mx = np.convolve(np.pad(fx, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
        my = np.convolve(np.pad(fy, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
        hp = np.hypot(fx - mx, fy - my)[good] * scale
    glitches = [{"frame": int(i), "split_px": float(v)} for i, v in enumerate(r.split) if v >= GLITCH_SPLIT]
    minutes = n / fps / 60.0
    times = {"cuts": [start + c / fps for c in cut_list], "flashes": [start + e["start"] / fps for e in flash_events],
             "punches": [start + p["frame"] / fps for p in punches], "glitches": [start + g["frame"] / fps for g in glitches],
             "colour_flashes": [start + c["frame"] / fps for c in colour]}
    summary = {"cuts.per_min": cut_sum["cuts.per_min"], "shots.median_s": cut_sum["shots.median_s"],
               "flash.per_min": flash_sum["flash.per_min"], "fades.per_min": len(fades) / minutes if minutes else float("nan"),
               "dissolves.per_min": len(dissolves) / minutes if minutes else float("nan"),
               "punches.per_min": len(punches) / minutes if minutes else float("nan"),
               "glitch.per_min": len(glitches) / minutes if minutes else float("nan"),
               "colourflash.per_min": len(colour) / minutes if minutes else float("nan"),
               "shake.rms": float(np.sqrt(np.mean(np.square(hp)))) if len(hp) else float("nan"),
               "camera.zoom_rms": float(np.sqrt(np.mean(np.square(z[~bad])))) if (~bad).any() else float("nan")}
    # the floor of the rates: half the difference between the video's two halves (the same video, read again)
    floor = {}
    half_t = start + n / fps / 2.0
    half_min = minutes / 2.0
    frames_of = {"cuts.per_min": times["cuts"], "flash.per_min": times["flashes"], "punches.per_min": times["punches"],
                 "glitch.per_min": times["glitches"], "colourflash.per_min": times["colour_flashes"],
                 "fades.per_min": [start + f["frame"] / fps for f in fades],
                 "dissolves.per_min": [start + d_["frame"] / fps for d_ in dissolves]}
    for key, ts in frames_of.items():
        if half_min > 0:
            a_ = sum(1 for t in ts if t < half_t) / half_min
            b_ = sum(1 for t in ts if t >= half_t) / half_min
            floor[key] = abs(a_ - b_) / 2.0
    if len(hp):
        h1, h2 = hp[:len(hp) // 2], hp[len(hp) // 2:]
        floor["shake.rms"] = abs(float(np.sqrt(np.mean(np.square(h1)))) - float(np.sqrt(np.mean(np.square(h2))))) / 2.0             if len(h1) and len(h2) else float("nan")
    for kind in ("cuts", "flashes", "punches", "glitches", "colour_flashes"):
        share, chance = _on_beat(times[kind], (beats or {}).get("beats") if isinstance(beats, dict) else beats, fps)
        key = {"flashes": "flash", "glitches": "glitch", "colour_flashes": "colourflash"}.get(kind, kind)
        summary[key + ".on_beat"] = share
        summary[key + ".on_beat_chance"] = chance
    return {"fps": fps, "frames": n, "cuts": [{"frame": int(c)} for c in cut_list], "flashes": flash_events,
            "fades": fades, "dissolves": dissolves, "punches": punches, "glitches": glitches, "colour_flashes": colour,
            "times": times, "summary": summary, "floor": floor}


def events_of(frames, fps, beats=None, start=0.0):
    """the events of a stack of frames (N x h x w x 3, RGB 0..1); beats: a list of times (s) or a voice run's dict"""
    r = EventReader(fps)
    for f in frames:
        r.push(f)
    return r.finish(beats, start)


def events_video(path, out=None, start=None, end=None, size=(128, 72), voice=None, log=None):
    """events of a video read at `size` (see the module's docstring), OUT.json"""
    LA = _tool("look_analyze")
    info = LA.probe(path)
    mat = LA.matrix_for(info)
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    w, h = size
    rng = "pc" if info.get("color_range") in ("pc", "jpeg") else "tv"
    vf = "scale=%d:%d:flags=area:in_color_matrix=%s:in_range=%s:out_range=pc,format=rgb24" % (w, h, mat, rng)
    pre, post = LA._range_args(start, end - start)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", path] + post + \
           ["-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    reader = EventReader(info["fps"])
    for k, a in enumerate(LA._ffmpeg_frames(argv, (w, h))):
        reader.push(a.astype(np.float64) / 255.0)
        if log and k % 1000 == 0:
            log("events %d frames" % k)
    beats = None
    if voice:
        with open(voice, encoding="utf-8") as f:
            v = json.load(f)
        beats = {"beats": v.get("beats", []), "downbeats": v.get("downbeats", [])}
    res = reader.finish(beats, start)
    res.update({"label": os.path.splitext(os.path.basename(path))[0], "path": path, "range": [start, end], "size": [w, h],
                "voice": voice})
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, allow_nan=True)
    return res


# ---- the graphic things on a frame ------------------------------------------------------------------------------------

PARTICLE_SIGMAS = (1.2, 1.8, 2.7, 4.0, 6.0, 9.0, 13.0)    # 720 line px
PARTICLE_LEAST = 0.12             # Y' a particle stands above the ground round it (the ring 2.5 to 4 sigma out)
PARTICLE_LOG = 0.04               # its scale-normalised Laplacian at least this
BOKEH_SIGMA = 4.0                 # 720 line px: a particle this wide or wider is bokeh (a defocused light)
LINE_LEAST = 0.15                 # of the frame's height: a long line
LINE_JOIN = (3.0, 6.0)            # degrees and 720 line px: segments this parallel and near are one line's two edges
AXIS = 3.0                        # degrees from level or upright: on the frame's axes


def particles(rgb, unit=1.0, mask=None):
    """the small round bright spots of a frame (RGB 0..1, unit: its px per 720 line px): particle.count, particle.bokeh
    (the share of them BOKEH_SIGMA wide or wider), particle.size (their median sigma, 720 line px); mask: where not to
    look (text, the person)"""
    ndi = _ndi()
    y = _luma(np.asarray(rgb, np.float64))
    sig = [s * unit for s in PARTICLE_SIGMAS]
    stack = np.array([-(s * s) * ndi.gaussian_laplace(y, s) for s in sig])
    found = []
    for k, s in enumerate(sig):
        lo, hi = max(0, k - 1), min(len(sig), k + 2)
        local = ndi.maximum_filter(stack[lo:hi], size=(hi - lo, int(2 * s) | 1, int(2 * s) | 1))
        peak = (stack[k] >= local[k - lo]) & (stack[k] >= PARTICLE_LOG)
        ys, xs = np.nonzero(peak)
        for yy, xx in zip(ys, xs):
            if mask is not None and mask[yy, xx]:
                continue
            r0, r1 = 2.5 * s, 4.0 * s
            y0, y1 = int(max(0, yy - r1)), int(min(y.shape[0], yy + r1 + 1))
            x0, x1 = int(max(0, xx - r1)), int(min(y.shape[1], xx + r1 + 1))
            gy, gx = np.mgrid[y0:y1, x0:x1]
            rr = np.hypot(gy - yy, gx - xx)
            ring = y[y0:y1, x0:x1][(rr >= r0) & (rr <= r1)]
            if not ring.size:
                continue
            core = y[y0:y1, x0:x1][rr <= max(1.0, 0.5 * s)].mean()
            if core - np.median(ring) >= PARTICLE_LEAST:
                found.append((float(stack[k, yy, xx]), xx, yy, s))
    # one per spot: the strongest response within its own size
    found.sort(reverse=True)
    kept = []
    for v, xx, yy, s in found:
        if any(math.hypot(xx - x2, yy - y2) < 1.5 * max(s, s2) for _, x2, y2, s2 in kept):
            continue
        kept.append((v, xx, yy, s))
    sizes = [s / unit for _, _, _, s in kept]
    n = len(kept)
    return {"particle.count": n, "particle.bokeh": float(np.mean([s >= BOKEH_SIGMA for s in sizes])) if n else 0.0,
            "particle.size": float(np.median(sizes)) if n else float("nan")}


def lines(rgb, unit=1.0):
    """the long straight lines of a frame: lines.count, lines.axis (the share of them level or upright, AXIS),
    lines.length (their total length over the frame's height)"""
    cv2 = _cv2()
    y = np.clip(_luma(np.asarray(rgb, np.float64)) * 255.0, 0, 255).astype(np.uint8)
    lsd = cv2.createLineSegmentDetector()
    segs = lsd.detect(y)[0]
    h = y.shape[0]
    least = LINE_LEAST * h
    items = []
    for s in (segs if segs is not None else []):
        x0, y0, x1, y1 = (float(v) for v in s[0])
        length = math.hypot(x1 - x0, y1 - y0)
        if length < least:
            continue
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
        items.append((length, ang, (x0, y0, x1, y1)))
    items.sort(reverse=True)
    joined = []
    for length, ang, p in items:
        mx, my = (p[0] + p[2]) / 2.0, (p[1] + p[3]) / 2.0
        same = False
        for L2, a2, q in joined:
            da = min(abs(ang - a2), 180.0 - abs(ang - a2))
            if da > LINE_JOIN[0]:
                continue
            # the distance of this one's middle from the other's line
            dx, dy = q[2] - q[0], q[3] - q[1]
            den = math.hypot(dx, dy)
            dist = abs(dx * (q[1] - my) - (q[0] - mx) * dy) / den if den > 0 else 1e9
            if dist <= LINE_JOIN[1] * unit:
                same = True
                break
        if not same:
            joined.append((length, ang, p))
    axis = [min(a % 90.0, 90.0 - a % 90.0) <= AXIS for _, a, _ in joined]
    return {"lines.count": len(joined), "lines.axis": float(np.mean(axis)) if joined else float("nan"),
            "lines.length": float(sum(L for L, _, _ in joined) / h)}


def elements_video(path, out=None, start=None, end=None, frames=60, height=720, log=None):
    """elements of frames spread over a video (see the module's docstring), their medians, OUT.json"""
    LA = _tool("look_analyze")
    info = LA.probe(path)
    mat = LA.matrix_for(info)
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    total = int(math.floor((end - start) * info["fps"] + 1e-6))
    ns = sorted(set(int(round(x)) for x in np.linspace(int(0.5 * info["fps"]), max(1, total - 1 - int(0.5 * info["fps"])),
                                                        frames)))
    got = dict(LA.read_frames(path, info, ns, height=height, matrix=mat, start=start, duration=end - start))
    rows = []
    for n in ns:
        if n not in got:
            continue
        a = got[n]
        unit = a.shape[0] / REFERENCE_HEIGHT
        m = {}
        m.update(particles(a, unit))
        m.update(lines(a, unit))
        rows.append({"n": int(n), "t": start + n / float(info["fps"]), "shot": 0, "m": {k: float(v) for k, v in m.items()}})
        if log:
            log("frame %d particles %d lines %d" % (n, m["particle.count"], m["lines.count"]))
    res = {"label": os.path.splitext(os.path.basename(path))[0], "path": path, "range": [start, end], "height": height,
           "frames": rows, "summary": LA.summarise(rows)}
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, allow_nan=True)
    return res


MOGRAPH_CONCEPTS = ("change", "camera", "things")
MOGRAPH_CONCEPT_LABELS = {"change": "画面の切り替え", "camera": "カメラと画面のゆれ", "things": "画面の飾り"}
MOGRAPH_MEASURES = {
    "cuts.per_min": ("change", "カット（1 分あたり）", "回"),
    "shots.median_s": ("change", "1 カットの長さの中央", "秒"),
    "cuts.on_beat": ("change", "拍の上（1 コマ以内）のカットの割合", ""),
    "cuts.on_beat_chance": ("change", "（その偶然の割合）", ""),
    "flash.per_min": ("change", "白いフラッシュ（1 分あたり）", "回"),
    "flash.on_beat": ("change", "拍の上のフラッシュの割合", ""),
    "colourflash.per_min": ("change", "色のフラッシュ（1 分あたり）", "回"),
    "fades.per_min": ("change", "黒か白へのフェード（1 分あたり）", "回"),
    "dissolves.per_min": ("change", "ディゾルブ（重ねての切り替え、1 分あたり）", "回"),
    "glitch.per_min": ("change", "グリッチのコマ（赤と青のずれ、1 分あたり）", "コマ"),
    "punches.per_min": ("camera", "急な寄り引き（ズームのパンチ、1 分あたり）", "回"),
    "punches.on_beat": ("camera", "拍の上のパンチの割合", ""),
    "shake.rms": ("camera", "画面のゆれ（移動の速い成分の rms、720 行の画素/コマ）", "px"),
    "camera.zoom_rms": ("camera", "寄り引きの速さ（1 コマの拡大率の対数の rms）", ""),
    "particle.count": ("things", "粒（小さい光の点）の数（1 コマ）", "個"),
    "particle.bokeh": ("things", "そのうち玉ボケ（半径の大きい粒）の割合", ""),
    "particle.size": ("things", "粒の大きさ（中央、720 行の画素の sigma）", "px"),
    "lines.count": ("things", "長い直線（絵の高さの 15 % 以上）の数（1 コマ）", "本"),
    "lines.axis": ("things", "そのうち水平か垂直の直線の割合", ""),
}


def summary_of(events, elements, label=None):
    """one summary (look_analyze's form) from an events run and an elements run"""
    s = {}
    fl = (events or {}).get("floor", {})
    for k, v in (events or {}).get("summary", {}).items():
        s[k] = {"median": float(v) if v is not None else float("nan"), "q25": float("nan"), "q75": float("nan"), "n": 1,
                "floor_pair": float(fl.get(k, float("nan"))), "ci": [float("nan"), float("nan")]}
    for k, v in (elements or {}).get("summary", {}).items():
        s[k] = v
    return {"label": label or (events or elements or {}).get("label"), "summary": s}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("events")
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--from", dest="start", type=float, default=None)
    p.add_argument("--to", dest="end", type=float, default=None)
    p.add_argument("--voice", default=None, help="a voice run of tools/typo_analyze.py (its beats)")
    p.add_argument("--size", default="128x72")
    p = sub.add_parser("elements")
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--from", dest="start", type=float, default=None)
    p.add_argument("--to", dest="end", type=float, default=None)
    p.add_argument("--frames", type=int, default=60)
    p.add_argument("--height", type=int, default=720)
    p = sub.add_parser("compare")
    p.add_argument("out_md")
    p.add_argument("out_json")
    p.add_argument("--ref", nargs="+", required=True, help="pairs EVENTS.json,ELEMENTS.json")
    p.add_argument("--ours", nargs="+", required=True, help="pairs EVENTS.json,ELEMENTS.json[,LABEL]")
    args = ap.parse_args(argv)

    def log(text):
        print(text, flush=True)
    if args.cmd == "events":
        w, h = (int(v) for v in args.size.lower().split("x"))
        r = events_video(args.video, args.out, args.start, args.end, (w, h), args.voice, log)
        print(json.dumps({"ok": True, "out": args.out, "frames": r["frames"],
                          "summary": {k: (round(v, 4) if isinstance(v, float) and np.isfinite(v) else None)
                                      for k, v in r["summary"].items()}}))
        return 0
    if args.cmd == "elements":
        r = elements_video(args.video, args.out, args.start, args.end, args.frames, args.height, log)
        print(json.dumps({"ok": True, "out": args.out, "frames": len(r["frames"])}))
        return 0
    if args.cmd == "compare":
        LA = _tool("look_analyze")

        def load(spec):
            parts = spec.split(",")
            ev = json.load(open(parts[0], encoding="utf-8"))
            el = json.load(open(parts[1], encoding="utf-8")) if len(parts) > 1 and parts[1] else None
            return summary_of(ev, el, parts[2] if len(parts) > 2 else None)
        refs = [load(x) for x in args.ref]
        ours = [load(x) for x in args.ours]
        rows = LA.compare(refs, ours, measures=MOGRAPH_MEASURES)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump({"refs": [r["label"] for r in refs], "ours": [o["label"] for o in ours], "rows": rows}, f,
                      ensure_ascii=False, indent=1, allow_nan=True)
        md = LA.table_md(rows, [o["label"] for o in ours], concepts=MOGRAPH_CONCEPTS, concept_labels=MOGRAPH_CONCEPT_LABELS)
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write("# 画面の切り替えと飾り: 参考 %d 本と私たち\n\n参考: %s\n%s" % (len(refs), ", ".join(r["label"] for r in refs), md))
        print(json.dumps({"ok": True, "out": args.out_md, "rows": len(rows)}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
