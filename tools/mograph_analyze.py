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

events: every frame is read small (72 lines, as wide as its own shape makes it: 128 for 16:9; the colour as
  tools/look_analyze.py reads it) and kept as a few numbers: the cuts and the flashes of tools/look_analyze.py (on the
  frame made 32 x 18; a cut that only darkens or lightens the same picture is a fade's step, and a flash is a light on
  one shot or a white wash, not a short bright shot between two cuts); a fade: the picture going down to black
  (mean Y' under FADE_BLACK) or up to white (over FADE_WHITE) over at least FADE_LEAST frames and staying there; a
  dissolve: a change spread over 3 to 16 frames whose middle frame is the mean of its ends (a camera move is not:
  its middle is the picture moved, not two pictures over each other); the camera's motion from frame to frame (the
  similarity transform fitted to the optical flow robustly: what moves on its own, a dancer or a growing line of text,
  is left out): a zoom punch is a scale jump of at least
  PUNCH_LEAST within three frames, PUNCH_OVER times the scale's change round it (a smooth zoom is not), and the shake is
  the rms of the shift less its running mean over SHAKE_WINDOW; a glitch frame: red and blue drawn apart across the
  picture by at least GLITCH_SPLIT (720 line px); a colour flash: the mean chroma rising by COLOUR_RISE over its
  running median for a short time and coming back.  Each kind's events against the beat (from tools/typo_analyze.py's
  voice run): the share within a frame of a beat, and the chance of that; and how they keep one place in the beat
  (Rayleigh's R and p, and where: s from the beat), which also finds events kept a few frames off the beat.
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
DISSOLVE_MID = 0.25               # its middle frame within this share of that change of the mean of its ends,
DISSOLVE_ENDS = 0.6               # and its ends two pictures (correlation under this; a picture dimmed, or a line of
#                                   text come on, correlates with itself)
PUNCH_LEAST = 0.08                # log scale change within three frames for a zoom punch, and
PUNCH_OVER = 6.0                  # this many times the scale's usual change round it (a second each side)
PUNCH_MERGE = 0.3                 # s: punches closer than this are one
SHAKE_WINDOW = 0.2                # s: the shake is the shift less its running mean over this
GLITCH_SPLIT = 8.0                # 720 line px between red and blue across the picture: a glitch frame
SPLIT_REACH = 6                   # px searched at the read size
COLOUR_RISE = 12.0                # C*ab over the running median: a colour flash
COLOUR_LONGEST = 0.6              # s
BEAT_REACH = 0.01                 # s added to a frame either side: on the beat
CAMERA_ROBUST = 4.685             # the camera's motion is fitted to the flow robustly (Tukey's biweight, 3 rounds): flow
#                                   further than this many robust sigmas from the fit gets no weight (a dancer, a sign
#                                   or a line of text that moves or grows on its own is not the camera; typorev: a dancer
#                                   on a still picture read as a shake of 0.4 to 1.0 px in our still front camera)
CAMERA_NOISE = 0.05               # px at the read size: the least robust sigma (the flow's own noise)
CUT_SAME = 0.95                   # a change whose thumbnail correlates with the one before it at least this is the same
#                                   picture made darker or lighter (a fade, a light coming up), not a cut (typorev: a fade
#                                   to black of a bright picture over 10 frames read as 4 cuts, and the cut next to it
#                                   threw the fade out)
FLASH_SAME = 0.6                  # a flash is a light on one shot (the thumbnails before and after it correlate at least
FLASH_WASH = 0.7                  # this) or a white wash (its brightest thumbnail's contrast under this share of the
#                                   contrast before and after it; a white flash over a cut is one); a short bright shot
#                                   between two cuts, neither, is two cuts (typorev: RE:odo 1187, 2282, a close-up of blond
#                                   hair for a few frames, were read as flashes and their cuts lost)


def _ncc(a, b):
    a = np.asarray(a, np.float64).ravel()
    b = np.asarray(b, np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-12 else 1.0


def _luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _mean_lab(rgb):
    LA = _tool("look_analyze")
    m = np.asarray(rgb, np.float64).reshape(-1, 3).mean(axis=0)
    return LA.rgb_to_lab(m[None, :])[0]


def _similarity(flow, border=4, weight=None):
    """the similarity transform (dx, dy, log scale, turn) fitted to an optical flow field about the middle (the border
    left out): least squares (weighted by `weight`, all alike by default), then reweighted three times by Tukey's
    biweight of the flow's distance from the fit (CAMERA_ROBUST), so that what moves on its own (a dancer, a growing
    line of text) does not move the camera.  (Weighting by the picture's edges was tried and left out: in dark stages
    the flat background then lost its say and the dancer took the camera, GETCHA 2.57 -> 3.78)"""
    h, w = flow.shape[:2]
    ys, xs = np.mgrid[border:h - border, border:w - border].astype(np.float64)
    u = flow[border:h - border, border:w - border, 0].ravel().astype(np.float64)
    v = flow[border:h - border, border:w - border, 1].ravel().astype(np.float64)
    x = (xs - (w - 1) / 2.0).ravel()
    y = (ys - (h - 1) / 2.0).ravel()
    # u = a x - b y + tx ; v = b x + a y + ty
    A = np.zeros((2 * x.size, 4))
    A[0::2, 0], A[0::2, 1], A[0::2, 2] = x, -y, 1.0
    A[1::2, 0], A[1::2, 1], A[1::2, 3] = y, x, 1.0
    rhs = np.empty(2 * x.size)
    rhs[0::2], rhs[1::2] = u, v
    w0 = np.ones(x.size) if weight is None else np.asarray(weight, np.float64)[border:h - border, border:w - border].ravel()
    if not (w0 > 1e-6).any():
        w0 = np.ones(x.size)
    wt = w0.copy()
    sol = np.zeros(4)
    for it in range(4):
        sw = np.sqrt(np.repeat(wt, 2))
        sol, *_ = np.linalg.lstsq(A * sw[:, None], rhs * sw, rcond=None)
        if it == 3:
            break
        pred = A @ sol
        res = np.hypot(u - pred[0::2], v - pred[1::2])
        sigma = max(CAMERA_NOISE, 1.4826 * float(np.median(res[w0 > 1e-6])))
        c = CAMERA_ROBUST * sigma
        k = np.clip(res / c, 0.0, 1.0)
        wt = w0 * (1.0 - k * k) ** 2
        if not (wt > 1e-6).any():
            break
    a, b, tx, ty = sol
    return float(tx), float(ty), float(math.log(max(1e-6, math.hypot(1.0 + a, b)))), float(math.degrees(math.atan2(b, 1.0 + a)))


def read_size(info, size=(128, 72)):
    """the size events are read at: size's height, the width the video's own shape gives (a 640 x 720 picture read
    128 x 72 would be stretched twice across, its sideways shake and colour split read twice as large)"""
    w, h = size
    if info.get("width") and info.get("height"):
        w = max(16, int(round(h * float(info["width"]) / float(info["height"]) / 2.0)) * 2)
    return int(w), int(h)


def _split(rgb, reach=SPLIT_REACH):
    """px (at the read size) between the red and the blue edges across the picture, the same in its left and its right
    half (red next to blue in the picture parts them in one place only): the smaller of the two halves' splits when
    they agree in direction, else 0"""
    w = rgb.shape[1]
    a = _split_one(rgb[:, :w // 2], reach)
    b = _split_one(rgb[:, w // 2:], reach)
    if a * b <= 0:
        return 0.0
    return float(min(abs(a), abs(b)))


def _split_one(rgb, reach=SPLIT_REACH):
    """the signed shift (px) of the column profiles of the horizontal gradients of red against blue that lines them
    up best (to a fraction of a px); 0 when they line up poorly"""
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
    if best is None or vals[best] < 0.5 or vals[best] - vals.get(0, -1.0) < 0.05:
        return 0.0
    if -reach < best < reach:
        a, b, c = vals[best - 1], vals[best], vals[best + 1]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        return float(best + max(-0.5, min(0.5, frac)))
    return float(best)


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
    """the share of the events within a frame (and BEAT_REACH) of a beat, the chance of that, and how they keep one
    place in the beat (the phase from one beat to the next): (R, p, offset) of Rayleigh's test, R from 0 (anywhere in
    the beat) to 1 (one place), p its chance, offset the place (s from the nearest beat, - before it).  The share alone
    misses events kept 2 or 3 frames before the beat (typorev: the references' cuts, R 0.25 to 0.37, p 0.003 to 0.00003,
    while their share within a frame was at chance)"""
    b = np.asarray(beats or [], np.float64)
    nan3 = (float("nan"), float("nan"), float("nan"))
    if b.size < 2 or not len(times):
        return float("nan"), float("nan"), nan3
    reach = 1.0 / fps + BEAT_REACH
    near = [np.min(np.abs(b - t)) <= reach for t in times]
    period = float(np.median(np.diff(b)))
    ph = []
    for t in times:
        k = int(np.searchsorted(b, t))
        if 0 < k < len(b):
            ph.append((t - b[k - 1]) / (b[k] - b[k - 1]))
    lock = nan3
    if ph:
        ang = 2.0 * math.pi * np.asarray(ph)
        C, S = float(np.cos(ang).mean()), float(np.sin(ang).mean())
        R = math.hypot(C, S)
        n = len(ph)
        z = n * R * R
        p = math.exp(-z) * (1 + (2 * z - z * z) / (4 * n) - (24 * z - 132 * z ** 2 + 76 * z ** 3 - 9 * z ** 4) / (288 * n * n))
        phase = math.atan2(S, C) / (2.0 * math.pi)                 # -0.5 .. 0.5 of a beat from the beat
        lock = (float(R), float(max(0.0, min(1.0, p))), float(phase * period))
    return float(np.mean(near)), float(min(1.0, 2 * reach / period)), lock


def _events(r, beats=None, start=0.0):
    LA = _tool("look_analyze")
    fps = r.fps
    n = len(r.mean_y)
    small = np.array(r.small, np.float64)
    series = np.array(r.mean_y)
    chroma = np.array(r.chroma)
    flash_events, _ = LA.flashes(series, fps)
    # a flash is a light on one shot or a white wash (FLASH_SAME, FLASH_WASH): a short bright shot between two cuts is
    # two cuts
    kept = []
    for e in flash_events:
        a, b = int(e["start"]), int(e["end"])
        if a < 1 or b >= n or b <= a:
            kept.append(e)
            continue
        before, after = small[a - 1], small[b]
        top = small[a + int(np.argmax(series[a:b]))]
        if _ncc(before, after) >= FLASH_SAME or top.std() < FLASH_WASH * min(before.std(), after.std()):
            kept.append(e)
    flash_events = kept
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
    # the same picture darker or lighter (CUT_SAME) is no cut: a fade (neither picture flat; from a flat black frame to
    # a picture it is one)
    cut_list = [c for c in cut_list if not (small[c - 1].std() >= 0.002 and small[c].std() >= 0.002 and
                                            _ncc(small[c - 1], small[c]) >= CUT_SAME)]
    bounds = [0] + cut_list + [n]
    cut_sum = {"cuts.per_min": len(cut_list) / (n / fps / 60.0) if n else float("nan"),
               "shots.median_s": float(np.median([(b - a) / fps for a, b in zip(bounds[:-1], bounds[1:])]))}
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
            if M <= DISSOLVE_MID * D and d[k - w + 1:k + w + 1].max() < 0.6 * D and                     _ncc(small[k - w], small[k + w]) < DISSOLVE_ENDS:
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
               "flash.per_min": len(flash_events) / minutes if minutes else float("nan"),
               "fades.per_min": len(fades) / minutes if minutes else float("nan"),
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
        share, chance, lock = _on_beat(times[kind], (beats or {}).get("beats") if isinstance(beats, dict) else beats, fps)
        key = {"flashes": "flash", "glitches": "glitch", "colour_flashes": "colourflash"}.get(kind, kind)
        summary[key + ".on_beat"] = share
        summary[key + ".on_beat_chance"] = chance
        summary[key + ".beat_lock"], summary[key + ".beat_lock_p"], summary[key + ".beat_offset_s"] = lock
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
    w, h = read_size(info, size)
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
PARTICLE_ROUND = 3.0              # the larger of a particle's two curvatures at most this many times the smaller
LINE_LEAST = 0.15                 # of the frame's height: a long line
LINE_JOIN = (3.0, 6.0)            # degrees and 720 line px: segments this parallel and near are one line's two edges
AXIS = 3.0                        # degrees from level or upright: on the frame's axes


def particles(rgb, unit=1.0, mask=None, points=False):
    """the small round bright spots of a frame (RGB 0..1, unit: its px per 720 line px): particle.count, particle.bokeh
    (the share of them BOKEH_SIGMA wide or wider), particle.size (their median sigma, 720 line px); mask: where not to
    look (text, the person); points: also where they are (x, y, sigma in the frame's px), to draw them"""
    ndi = _ndi()
    y = _luma(np.asarray(rgb, np.float64))
    sig = [s * unit for s in PARTICLE_SIGMAS]
    stack = np.array([-(s * s) * ndi.gaussian_laplace(y, s) for s in sig])
    hess = [(ndi.gaussian_filter(y, s, order=(0, 2)), ndi.gaussian_filter(y, s, order=(2, 0)),
             ndi.gaussian_filter(y, s, order=(1, 1))) for s in sig]
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
            # round: curved as much across as along (the Hessian's two eigenvalues within PARTICLE_ROUND of each other);
            # a thin line is curved across only (a floor of grid lines read as rows of spots, our stage)
            a_, b_, c_ = hess[k][0][yy, xx], hess[k][1][yy, xx], hess[k][2][yy, xx]
            det = a_ * b_ - c_ * c_
            if det <= 0 or (a_ + b_) ** 2 / det >= (PARTICLE_ROUND + 1.0) ** 2 / PARTICLE_ROUND:
                continue
            # and above its ring all round (its 80 % point): where two lines cross, their four arms light the ring
            if core - np.percentile(ring, 80) >= PARTICLE_LEAST:
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
    out = {"particle.count": n, "particle.bokeh": float(np.mean([s >= BOKEH_SIGMA for s in sizes])) if n else 0.0,
           "particle.size": float(np.median(sizes)) if n else float("nan")}
    if points:
        out["points"] = [(int(xx), int(yy), float(s)) for _, xx, yy, s in kept]
    return out


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


# ---- the flashes that may harm (Rec. ITU-R BT.1702-3, 2023) -------------------------------------------------------------
# Guideline 1: "A potentially harmful flash occurs when there is a pair of opposing changes in luminance ... When screen
# luminance of the darker image is below 160 cd/m2, a potentially harmful sequence of flashes occurs where there is a difference
# of 20 cd/m2 or more between the screen luminance of the darker and the brighter images"; "Isolated single, double, or triple
# flashes are acceptable, but a sequence of flashes is not permitted when both the following occur: the combined area of
# flashes occurring concurrently occupies more than 25% of the displayed screen area; and there are more than three flashes
# (i.e. six changes in luminance as described above) within any one-second period"; "Irrespective of luminance, a transition
# to or from a saturated red is also potentially harmful".  NOTE 3: SDR pictures shown with peak white at 200 cd/m2; Table 1:
# the screen luminance of a signal level V (black 0, white 1) is that of Rec. ITU-R BT.1886, 200 x V^2.4.  (The 1/17
# Michelson contrast for a darker image from 160 cd/m2 is for HDR programmes only.)  A saturated red, which the recommendation
# does not define, is WCAG 2.2's: R / (R + G + B) of 0.8 or more, its change (R - G - B) x 320 past 20 (linear values).

FLASH_CD = 20.0                   # cd/m2 between the darker and the brighter image
DARK_BELOW = 160.0                # cd/m2: the darker image below this
WHITE_CD = 200.0                  # cd/m2 of peak white (SDR)
QUARTER = 0.25                    # of the screen
MOST_CHANGES = 6                  # in a second: more is more than three flashes
RED_SHARE = 0.8
RED_SCALE = 320.0
RED_CHANGE = 20.0
SAFETY_GRID = (64, 36)            # cells over the picture: what flashes is told by area


def screen_luminance(v):
    """cd/m2 of a signal level v (0..1) on the SDR display of BT.1702 (BT.1886, white 200)"""
    return WHITE_CD * np.clip(np.asarray(v, np.float64), 0.0, 1.0) ** 2.4


def _cells(values, grid):
    """values [h, w] averaged over the cells of `grid` (columns, rows): the area each cell covers alike"""
    cols, rows = grid
    h, w = values.shape
    ys = (np.arange(rows + 1) * h) // rows
    xs = (np.arange(cols + 1) * w) // cols
    sums = np.add.reduceat(np.add.reduceat(values, ys[:-1], axis=0), xs[:-1], axis=1)
    counts = np.outer(np.diff(ys), np.diff(xs))
    return sums / counts


class _Swings:
    """per cell, the changes of a value with a hysteresis: a change is told on the frame the value has gone `least` from the last
    extreme the other way, and counts when `counts(low, high)` says so (the darker image below DARK_BELOW).  Rising, the high
    follows the value up; falling, the low follows it down; before the first change both do"""

    def __init__(self, first, least, counts):
        self.least, self.counts = least, counts
        self.lo = np.array(first, np.float64)
        self.hi = np.array(first, np.float64)
        self.dir = np.zeros(self.lo.shape, np.int8)    # 0 not yet, +1 rising, -1 falling

    def push(self, v):
        """(up, down): the cells with a change told on this frame"""
        d = self.dir
        self.hi = np.where(d >= 0, np.maximum(self.hi, v), self.hi)
        self.lo = np.where(d <= 0, np.minimum(self.lo, v), self.lo)
        rise = (d <= 0) & (v - self.lo >= self.least)              # up from the low
        fall = (d >= 0) & (self.hi - v >= self.least) & ~rise      # down from the high
        up = rise & self.counts(self.lo, v)
        down = fall & self.counts(v, self.hi)
        self.dir = np.where(rise, 1, np.where(fall, -1, d)).astype(np.int8)
        self.hi = np.where(rise, v, self.hi)
        self.lo = np.where(fall, v, self.lo)
        return up, down


def _swing_states(series, least, counts):
    """[(up, down)] a frame, the cells' changes (the series: [frames, rows, cols])"""
    sw = _Swings(series[0], least, counts)
    out = [(np.zeros(series[0].shape, bool), np.zeros(series[0].shape, bool))]
    for v in series[1:]:
        out.append(sw.push(v))
    return out


def _flash_report(changes, fps):
    """the counts of BT.1702's Guideline 1 from the changes of every cell: the most changes in a second that more than a quarter
    of the screen goes through (most_flashes_a_second: half of it), the same for any one cell, whether a sequence is not
    permitted (harmful), and the changes and flashes over more than a quarter of the screen at once (their leading edges)"""
    n = len(changes)
    ups = np.array([u for u, _ in changes], np.float64)
    downs = np.array([d for _, d in changes], np.float64)
    both = ups + downs
    window = max(1, int(round(fps)))
    csum = np.concatenate([np.zeros((1,) + both.shape[1:]), np.cumsum(both, axis=0)])
    most_quarter, most_anywhere, harmful_at = 0, 0, []
    for end in range(n):
        start = max(0, end - window + 1)
        count = csum[end + 1] - csum[start]                    # the cells' changes in the second ending on this frame
        k_any = int(count.max())
        most_anywhere = max(most_anywhere, k_any)
        flat = np.sort(count.ravel())[::-1]
        need = int(math.floor(QUARTER * flat.size)) + 1        # more than a quarter
        k_quarter = int(flat[need - 1]) if need <= flat.size else 0
        most_quarter = max(most_quarter, k_quarter)
        if k_quarter > MOST_CHANGES:
            harmful_at.append(end)
    # the changes over more than a quarter of the screen at once (the cells' changes within a frame either side), one a run, on
    # its frame of the most
    area_up, area_down = ups.mean(axis=(1, 2)), downs.mean(axis=(1, 2))
    big = []
    for d, area in ((1, area_up), (-1, area_down)):
        near = np.convolve(area, np.ones(3), mode="same")
        for a, b in _runs(near > QUARTER):
            i = a + int(np.argmax(area[a:b]))
            big.append((i, d, float(near[a:b].max())))
    big.sort()
    flashes, i = [], 0
    while i + 1 < len(big):
        if big[i][1] != big[i + 1][1]:
            flashes.append({"frame": big[i][0], "area": min(big[i][2], big[i + 1][2]), "second": big[i + 1][0]})
            i += 2
        else:
            i += 1
    edges = [f["frame"] for f in flashes]
    gaps = [(b - a) / float(fps) for a, b in zip(edges, edges[1:])]
    return {"most_flashes_a_second": most_quarter // 2, "most_changes_a_second": most_quarter,
            "most_flashes_a_second_anywhere": most_anywhere // 2, "harmful": bool(harmful_at),
            "harmful_frames": harmful_at[:50], "changes": len(big), "flashes": flashes,
            "least_gap_s": min(gaps) if gaps else None}


def safety_of(frames, fps, grid=SAFETY_GRID):
    """BT.1702-3's flashes in frames (RGB 0..1, the signal levels: a video read to the full range): the screen luminance of
    every pixel (BT.1886 on 200 cd/m2 white) averaged over the cells of `grid`, and per cell its changes of FLASH_CD or more
    whose darker side is below DARK_BELOW; and the saturated red's changes (WCAG 2.2's measure).  See _flash_report"""
    lum, red = [], []
    for f in frames:
        f = np.asarray(f, np.float64)
        g = (min(grid[0], f.shape[1]), min(grid[1], f.shape[0]))
        y = f[..., 0] * 0.2126 + f[..., 1] * 0.7152 + f[..., 2] * 0.0722
        lum.append(_cells(screen_luminance(y), g))
        lin = np.clip(f, 0.0, 1.0) ** 2.4
        total = lin.sum(axis=2)
        with np.errstate(divide="ignore", invalid="ignore"):
            share = np.where(total > 0, lin[..., 0] / total, 0.0)
        r = np.maximum(0.0, lin[..., 0] - lin[..., 1] - lin[..., 2]) * RED_SCALE * (share >= RED_SHARE)
        red.append(_cells(r, g))
    lum, red = np.array(lum), np.array(red)
    general_changes = _swing_states(lum, FLASH_CD, lambda lo, hi: lo < DARK_BELOW)
    general = _flash_report(general_changes, fps)
    reds = _flash_report(_swing_states(red, RED_CHANGE, lambda lo, hi: np.ones(lo.shape, bool)), fps)
    for f in general["flashes"]:
        # the change at its leading edge: over the three frames round it, the median of the cells that changed there
        a = f["frame"]
        lo, hi = max(0, a - 2), min(len(lum) - 1, a + 1)
        changed = np.zeros(lum[0].shape, bool)
        for k in range(max(0, a - 1), min(len(lum), a + 2)):
            changed |= general_changes[k][0] | general_changes[k][1]
        f["cd"] = float(np.median(np.abs(lum[hi] - lum[lo])[changed])) if changed.any() else 0.0
    return {"fps": fps, "frames": len(lum), "grid": list(lum.shape[1:][::-1]), "general": general, "red": reds,
            "settings": {"flash_cd": FLASH_CD, "dark_below": DARK_BELOW, "white_cd": WHITE_CD, "quarter": QUARTER,
                         "most_changes": MOST_CHANGES, "source": "Rec. ITU-R BT.1702-3 (11/2023) Guideline 1, NOTE 3, Table 1"}}


def safety_video(path, out=None, start=None, end=None, size=(256, 144), log=None):
    """safety_of over a video read at `size` (its own matrix and range, to the full range) into cells, OUT.json"""
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
    frames = [a.astype(np.float64) / 255.0 for a in LA._ffmpeg_frames(argv, (w, h))]
    res = safety_of(frames, info["fps"])
    for part in ("general", "red"):
        for f in res[part]["flashes"]:
            f["t"] = start + f["frame"] / float(info["fps"])
    res.update({"label": os.path.splitext(os.path.basename(path))[0], "path": path, "range": [start, end], "size": [w, h]})
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


MOGRAPH_CONCEPTS = ("change", "camera", "things")
MOGRAPH_CONCEPT_LABELS = {"change": "画面の切り替え", "camera": "カメラと画面のゆれ", "things": "画面の飾り"}
MOGRAPH_MEASURES = {
    "cuts.per_min": ("change", "カット（1 分あたり）", "回"),
    "shots.median_s": ("change", "1 カットの長さの中央", "秒"),
    "cuts.on_beat": ("change", "拍の上（1 コマ以内）のカットの割合", ""),
    "cuts.on_beat_chance": ("change", "（その偶然の割合）", ""),
    "cuts.beat_lock": ("change", "カットの拍への揃い（拍の中の位相の集まり R: 0 ばらばら〜1 揃う。1 コマ以内かは問わない）", ""),
    "cuts.beat_lock_p": ("change", "（その揃いが偶然で出る確からしさ、Rayleigh の検定）", ""),
    "cuts.beat_offset_s": ("change", "カットが揃う所（拍からの秒、- は拍の前）", "秒"),
    "flash.per_min": ("change", "明るさの短い山（白いフラッシュのほか、舞台の光や LED の点滅も入る。1 分あたり）", "回"),
    "flash.on_beat": ("change", "拍の上のフラッシュの割合", ""),
    "colourflash.per_min": ("change", "色のフラッシュ（1 分あたり）", "回"),
    "fades.per_min": ("change", "黒か白へのフェード（1 分あたり）", "回"),
    "dissolves.per_min": ("change", "ディゾルブ（重ねての切り替え、1 分あたり）", "回"),
    "glitch.per_min": ("change", "画面全体で赤と青がずれたコマ（1 分あたり。部分の四角・横の筋・文字だけのグリッチは数えない）", "コマ"),
    "punches.per_min": ("camera", "急な寄り引き（ズームのパンチとカメラの速い寄り引き、1 分あたり）", "回"),
    "punches.beat_lock": ("camera", "パンチの拍への揃い（R）", ""),
    "punches.on_beat": ("camera", "拍の上のパンチの割合", ""),
    "shake.rms": ("camera", "画面のゆれ（移動の速い成分の rms、720 行の画素/コマ）", "px"),
    "camera.zoom_rms": ("camera", "寄り引きの速さ（1 コマの拡大率の対数の rms）", ""),
    "particle.count": ("things", "小さい明るい点の数（1 コマ。窓・看板・文字の画・髪の照りも数える。飾りの粒だけではない）", "個"),
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
    p = sub.add_parser("safety", help="the flashes that may harm (Rec. ITU-R BT.1702-3 Guideline 1)")
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--from", dest="start", type=float, default=None)
    p.add_argument("--to", dest="end", type=float, default=None)
    p.add_argument("--size", default="256x144", help="the size the video is read at, then put into %dx%d cells" % SAFETY_GRID)
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
    if args.cmd == "safety":
        w, h = (int(v) for v in args.size.lower().split("x"))
        r = safety_video(args.video, args.out, args.start, args.end, (w, h), log)
        g, red = r["general"], r["red"]
        print(json.dumps({"ok": True, "out": args.out, "frames": r["frames"], "harmful": g["harmful"] or red["harmful"],
                          "most_flashes_a_second": g["most_flashes_a_second"], "flashes": len(g["flashes"]),
                          "red_most_flashes_a_second": red["most_flashes_a_second"], "least_gap_s": g["least_gap_s"]}))
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
