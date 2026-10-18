"""Measure the look of a video (or a folder of frames) in numbers: its tone, colour, light, optics, texture and frame.

    python tools/look_analyze.py measure VIDEO|FOLDER OUT.json [--label NAME] [--from S] [--to S] [--pairs N]
                                         [--height 720] [--matrix auto|bt601|bt709] [--jobs N] [--crops DIR]
    python tools/look_analyze.py compare OUT.md OUT.json --ref A.json B.json ... --ours X.json Y.json ...
    python tools/look_analyze.py figure strip TABLE.json OUT.png
    python tools/look_analyze.py figure profiles OUT.png A.json B.json ...
    python tools/look_analyze.py crops VIDEO OUT.png --at S S ... [--box X0,Y0,X1,Y1] [--size 320x180]
    python tools/look_analyze.py annotate VIDEO OUT.png --at S [--what bloom|dof|ca|bars]

`measure` reads the video twice with ffmpeg: once every frame at a tiny size (the cuts between shots, the flashes, the
frames that are shown twice, the darkening of the corners over all the frames), then pairs of frames spread over the
video at the analysis height (720 lines by default, the height of our MV: every length is in pixels of a 720 line
picture).  On each pair it measures, idea by idea (the names of the numbers start with the idea's name):

* tone: where the blacks, the middle and the whites of CIE L* lie, the spread (contrast), the fine contrast, whether the
  picture leans dark or bright, clipped whites and crushed blacks;
* colour: saturation (C*ab), colourfulness (Hasler and Suesstrunk 2003), the cast of the whole picture and the cast of
  the shadows, the middle tones and the highlights apart (split toning; teal and orange), the white balance read from
  the near-white pixels (McCamy's colour temperature);
* light: the glow round the brightest parts (how far it reaches, how strong, its colour against the source's: a red
  halo is halation), streaks of a star filter or an anamorphic flare (the angular harmonics of the light round small
  highlights), the flashes of the whole frame (from every frame), and two rough proxies for the light's colour and side;
* optics: the blur of every edge (the gradient ratio after a known re-blur, Zhuo and Sim 2011): depth of field is the
  spread between the sharpest and the softest edges; motion blur against the optical flow of the pair gives the
  shutter (0.5 is a 180 degree shutter); colour fringes (red and blue against green, shifted and scaled about the
  centre); the darkening of the corners; the bending of straight lines (barrel or pincushion);
* texture: the noise of flat areas, the grain that changes from frame to frame and its size, the halo of sharpening
  at strong edges, diffusion (a soft veil round every edge whose core stays sharp), scanlines and torn rows (glitch);
* frame: letterbox bars and the shape of the picture inside them, the frame rate and the rate at which the picture
  really changes (30 fps shown at 60), the cuts between shots.

The measures of every sampled frame, of every shot and of the whole video go into OUT.json with the noise floor of
each: how much it changes between the two frames of a pair (almost the same picture) and over the frames of the video.
`compare` puts videos side by side (the references' median and quartiles, ours, and how far ours lies outside the
references' quartiles in units of their spread) as a table; `figure`, `crops` and `annotate` draw the figures.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

REFERENCE_HEIGHT = 720.0          # every length is in pixels of a picture this tall (the height of our MV)

_LAZY = {}


def _ndi():
    """scipy.ndimage, imported when first needed (the measures need it, reading a JSON does not)"""
    if "ndi" not in _LAZY:
        import scipy.ndimage
        _LAZY["ndi"] = scipy.ndimage
    return _LAZY["ndi"]


def _cv2():
    if "cv2" not in _LAZY:
        import cv2
        _LAZY["cv2"] = cv2
    return _LAZY["cv2"]


# ---- colour ---------------------------------------------------------------------------------------------------------

# sRGB (D65) to CIE XYZ, and the white of D65
_RGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)
_WHITE = np.array([0.95047, 1.0, 1.08883])
_LUMA = np.array([0.2126, 0.7152, 0.0722])        # BT.709 weights, on the coded (gamma) values: Y'


def srgb_to_linear(v):
    v = np.asarray(v, np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((np.clip(v, 0.0, None) + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v):
    v = np.clip(np.asarray(v, np.float64), 0.0, None)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * v ** (1.0 / 2.4) - 0.055)


def _f(t):
    d = 6.0 / 29.0
    return np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)


def _f_inv(t):
    d = 6.0 / 29.0
    return np.where(t > d, t ** 3, 3 * d * d * (t - 4.0 / 29.0))


def rgb_to_xyz(rgb):
    return srgb_to_linear(rgb) @ _RGB_TO_XYZ.T


def rgb_to_lab(rgb):
    """CIE L*a*b* (D65) of sRGB colours in 0..1 (the last axis is r, g, b)"""
    xyz = rgb_to_xyz(rgb) / _WHITE
    fx, fy, fz = _f(xyz[..., 0]), _f(xyz[..., 1]), _f(xyz[..., 2])
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1)


def lab_to_rgb(lab):
    """sRGB in 0..1 of CIE L*a*b* colours (out of gamut clipped)"""
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16.0) / 116.0
    fx, fz = fy + lab[..., 1] / 500.0, fy - lab[..., 2] / 200.0
    xyz = np.stack([_f_inv(fx), _f_inv(fy), _f_inv(fz)], axis=-1) * _WHITE
    return np.clip(linear_to_srgb(xyz @ _XYZ_TO_RGB.T), 0.0, 1.0)


def luma(rgb):
    """Y' (BT.709 weights on the coded values), what a video's luma plane holds"""
    return np.asarray(rgb, np.float64) @ _LUMA


def _hue(a, b):
    return float(math.degrees(math.atan2(b, a)) % 360.0)


# ---- tone and colour of one frame -------------------------------------------------------------------------------------

CLIP_WHITE = 253.0 / 255.0        # a channel this high is clipped white
CLIP_BLACK = 2.0 / 255.0          # all channels this low are crushed black
LOCAL_SIGMA = 10.0                # the fine contrast: L* against itself blurred by this (720 line pixels)


def tone(rgb, lab, unit=1.0):
    """where the tones of a frame lie (CIE L*, 0..100)

    black / white: the 1 and 99 % points; median; p5 / p95; key: where the median lies between the 5 and 95 % points
    (under 0.5 the picture leans dark, low key; over, bright); contrast: the standard deviation of L*; local: the mean
    distance of L* from itself blurred by LOCAL_SIGMA (fine contrast, clarity); shadows / highlights: the share under
    L* 25 and over 75; clip_white: the share with a channel clipped; clip_black: the share with every channel crushed.
    unit is the frame's pixels per 720 line pixel."""
    L = lab[..., 0]
    flat = L.ravel()
    p1, p5, p50, p95, p99 = np.percentile(flat, [1, 5, 50, 95, 99])
    blurred = _ndi().gaussian_filter(L, LOCAL_SIGMA * unit, mode="nearest")
    return {"tone.black": float(p1), "tone.p5": float(p5), "tone.median": float(p50), "tone.p95": float(p95),
            "tone.white": float(p99),
            "tone.key": float((p50 - p5) / (p95 - p5)) if p95 - p5 > 1e-6 else float("nan"),
            "tone.contrast": float(flat.std()),
            "tone.local": float(np.abs(L - blurred).mean()),
            "tone.shadows": float((flat < 25.0).mean()), "tone.highlights": float((flat > 75.0).mean()),
            "tone.clip_white": float((rgb.max(axis=-1) >= CLIP_WHITE).mean()),
            "tone.clip_black": float((rgb.max(axis=-1) <= CLIP_BLACK).mean())}


# the bands of L* for split toning, and the direction of orange in a*b* (teal is its opposite)
SPLIT_BANDS = {"shadow": (8.0, 35.0), "mid": (35.0, 65.0), "high": (65.0, 95.0)}
ORANGE = (math.cos(math.radians(55.0)), math.sin(math.radians(55.0)))


def colour(rgb, lab):
    """the colour of a frame

    chroma: the mean C*ab; chroma_p90; colourfulness: Hasler and Suesstrunk's M (on 0..255 values); cast: the hue and
    size of the mean a*b* (the whole picture, grey world); split.<band>_hue / _chroma: the same of the shadows (L* 8..35),
    the middle (35..65) and the highlights (65..95) apart; split.teal_orange: how much more orange the highlights are
    than the shadows along the teal - orange line of a*b* (0 for a neutral grade, about +20 for a strong one)."""
    a, b = lab[..., 1].ravel(), lab[..., 2].ravel()
    L = lab[..., 0].ravel()
    chroma = np.hypot(a, b)
    v = np.asarray(rgb, np.float64).reshape(-1, 3) * 255.0
    rg = v[:, 0] - v[:, 1]
    yb = 0.5 * (v[:, 0] + v[:, 1]) - v[:, 2]
    m = math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean())
    out = {"colour.chroma": float(chroma.mean()), "colour.chroma_p90": float(np.percentile(chroma, 90)),
           "colour.colourfulness": float(m), "colour.cast_hue": _hue(a.mean(), b.mean()),
           "colour.cast_chroma": float(math.hypot(a.mean(), b.mean()))}
    casts = {}
    for name, (lo, hi) in SPLIT_BANDS.items():
        sel = (L >= lo) & (L < hi)
        if sel.sum() < 0.005 * L.size:
            out["split.%s_hue" % name] = out["split.%s_chroma" % name] = float("nan")
            casts[name] = None
            continue
        ma, mb = float(a[sel].mean()), float(b[sel].mean())
        casts[name] = (ma, mb)
        out["split.%s_hue" % name] = _hue(ma, mb)
        out["split.%s_chroma" % name] = float(math.hypot(ma, mb))
    if casts["shadow"] and casts["high"]:
        along = [c[0] * ORANGE[0] + c[1] * ORANGE[1] for c in (casts["high"], casts["shadow"])]
        out["split.teal_orange"] = float(along[0] - along[1])
    else:
        out["split.teal_orange"] = float("nan")
    return out


WHITE_L, WHITE_CHROMA = 80.0, 30.0       # a near-white pixel: this bright and at most this coloured, and not clipped


def mccamy_cct(x, y):
    """the correlated colour temperature (K) of chromaticity x, y (McCamy 1992)"""
    n = (x - 0.3320) / (0.1858 - y)
    return 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33


def white_balance(rgb, lab):
    """the white balance read from the near-white pixels (L* over WHITE_L, C*ab under WHITE_CHROMA, no channel clipped)

    wb.cct: McCamy's colour temperature of their mean colour (6500 K neutral; lower is warmer); wb.white_a / white_b:
    their mean a* and b*; wb.share: their share of the frame (the reading is weak when it is small)."""
    flat = np.asarray(rgb, np.float64).reshape(-1, 3)
    L, a, b = (lab[..., i].ravel() for i in range(3))
    sel = (L >= WHITE_L) & (np.hypot(a, b) <= WHITE_CHROMA) & (flat.max(axis=1) < 0.995)
    share = float(sel.mean())
    if sel.sum() < max(20, 0.0005 * sel.size):
        return {"wb.cct": float("nan"), "wb.white_a": float("nan"), "wb.white_b": float("nan"), "wb.share": share}
    xyz = rgb_to_xyz(flat[sel]).mean(axis=0)
    x, y = xyz[0] / xyz.sum(), xyz[1] / xyz.sum()
    return {"wb.cct": float(mccamy_cct(x, y)), "wb.white_a": float(a[sel].mean()), "wb.white_b": float(b[sel].mean()),
            "wb.share": share}


# ---- the frame: bars, corners ---------------------------------------------------------------------------------------

BAR_LEVEL = 0.06                  # a bar's rows (or columns) stay under this Y' (15 of 255) in every frame


def find_bars(frames):
    """letterbox (top, bottom) and pillarbox (left, right) bars of a stack of Y' frames (N x H x W), in pixels: the
    rows or columns from each edge that stay dark (their 99 % point under BAR_LEVEL) in every frame"""
    frames = np.asarray(frames, np.float64)
    rows = np.percentile(frames, 99, axis=2).max(axis=0)       # per row: its bright end, the brightest frame
    cols = np.percentile(frames, 99, axis=1).max(axis=0)

    def run(values):
        n = 0
        while n < len(values) and values[n] < BAR_LEVEL:
            n += 1
        return n if n < len(values) // 2 else 0              # a bar never covers half the picture

    return {"top": run(rows), "bottom": run(rows[::-1]), "left": run(cols), "right": run(cols[::-1])}


def active_box(bars, shape):
    """(x0, y0, x1, y1) of the picture inside the bars of a frame of shape (H, W)"""
    h, w = shape[:2]
    return (bars["left"], bars["top"], w - bars["right"], h - bars["bottom"])


def radius_map(h, w):
    """the distance of every pixel centre from the picture's centre over the half diagonal (0 centre, 1 corners), as
    ffmpeg's vignette filter measures it"""
    y, x = np.mgrid[0:h, 0:w]
    return np.hypot(x + 0.5 - w / 2.0, y + 0.5 - h / 2.0) / math.hypot(w / 2.0, h / 2.0)


def vignette(maps):
    """the darkening of the corners from many frames' Y' maps (N x h x w, small) of the picture inside the bars

    vignette.corner: the mean over frames, in the corners (radius 0.9 to 1) over the middle (to 0.3); content that
    changes from frame to frame averages out, a lens darkening that stays does not (ffmpeg's vignette at angle 0.556,
    mv_look's lens.vignette 0.3, gives about 0.55).  vignette.corner_p10: the same of each place's 10 % point over the
    frames (less swayed by a bright subject that keeps to the middle)."""
    maps = np.asarray(maps, np.float64)
    r = radius_map(*maps.shape[1:])
    corner, middle = r >= 0.9, r <= 0.3
    mean = maps.mean(axis=0)
    p10 = np.percentile(maps, 10, axis=0)
    out = {}
    for name, m in (("vignette.corner", mean), ("vignette.corner_p10", p10)):
        out[name] = float(m[corner].mean() / m[middle].mean()) if m[middle].mean() > 1e-6 else float("nan")
    rings = np.linspace(0.0, 1.0, 11)
    out["profile"] = [float(mean[(r >= lo) & (r < hi)].mean()) if ((r >= lo) & (r < hi)).any() else float("nan")
                      for lo, hi in zip(rings[:-1], rings[1:])]
    return out


# ---- time: flashes, cuts, repeated frames ---------------------------------------------------------------------------

FLASH_RISE = 0.10                 # Y' above the running median (of FLASH_WINDOW s each side) by this much is a flash
FLASH_WINDOW = 0.5
FLASH_LONGEST = 0.6               # s: longer is a change of light, not a flash
FLASH_BACK = 0.5                  # after it the level comes back within this share of its rise (a step does not)


def _running_median(x, half):
    pad = np.pad(x, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1)
    return np.median(view, axis=1)


def flashes(series, fps):
    """the flashes in a per-frame mean Y' series: short (under FLASH_LONGEST s) rises of at least FLASH_RISE over the
    running median that come back down; returns (events, summary) with events {start, end, peak} (frames, end
    excluded) and flash.per_min, flash.peak (the mean rise), flash.len_s (the mean length)"""
    series = np.asarray(series, np.float64)
    half = max(1, int(round(FLASH_WINDOW * fps)))
    rise = series - _running_median(series, half)
    hot = rise >= FLASH_RISE
    events = []
    i, n = 0, len(series)
    around = max(1, int(round(0.25 * fps)))
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        peak = float(rise[i:j].max())
        before = series[max(0, i - around):i]
        after = series[j:j + around]
        back = len(before) and len(after) and abs(after.mean() - before.mean()) < FLASH_BACK * peak
        if j - i <= FLASH_LONGEST * fps and back:
            events.append({"start": int(i), "end": int(j), "peak": peak})
        i = j
    minutes = n / float(fps) / 60.0
    summary = {"flash.per_min": len(events) / minutes if minutes > 0 else float("nan"),
               "flash.peak": float(np.mean([e["peak"] for e in events])) if events else 0.0,
               "flash.len_s": float(np.mean([(e["end"] - e["start"]) / float(fps) for e in events])) if events else 0.0}
    return events, summary


CUT_LEAST = 0.06                  # mean |difference| of the thumbnails (Y') a cut changes at least, and
CUT_OVER = 5.0                    # this many times the frame-to-frame change around it


def _diffs(thumbs):
    thumbs = np.asarray(thumbs, np.float64)
    d = np.zeros(len(thumbs))
    d[1:] = np.abs(np.diff(thumbs, axis=0)).mean(axis=(1, 2))
    return d


def cuts(thumbs, fps, flash_events=()):
    """the cuts between shots in a stack of small Y' thumbnails (N x h x w): a frame that differs from the one before
    by at least CUT_LEAST and CUT_OVER times the change around it, and stays different (a flash comes back; the frames
    of a flash are left out); returns (frame indices, summary) with cuts.per_min and shots.median_s"""
    thumbs = np.asarray(thumbs, np.float64)
    n = len(thumbs)
    d = _diffs(thumbs)
    half = max(2, int(round(0.5 * fps)))
    around = _running_median(d, half)
    in_flash = np.zeros(n, bool)
    for e in flash_events:
        in_flash[max(0, e["start"] - 1):min(n, e["end"] + 2)] = True
    later = max(2, int(round(0.05 * fps)))
    found = []
    for i in range(1, n):
        if in_flash[i] or d[i] < max(CUT_LEAST, CUT_OVER * around[i]):
            continue
        k = min(n - 1, i + later)
        if np.abs(thumbs[k] - thumbs[i - 1]).mean() < 0.5 * d[i]:
            continue                                            # it went back: not a cut
        if found and i - found[-1] < later:
            continue
        found.append(i)
    bounds = [0] + found + [n]
    shots = [(b - a) / float(fps) for a, b in zip(bounds[:-1], bounds[1:])]
    minutes = n / float(fps) / 60.0
    return found, {"cuts.per_min": len(found) / minutes if minutes > 0 else float("nan"),
                   "shots.median_s": float(np.median(shots))}


def effective_fps(thumbs, fps):
    """the rate at which the picture really changes: frames that repeat the one before (their change under 0.15 of the
    change around them, where the picture moves) are left out; 30 fps content shown at 60 gives 30 and step 2 (the
    frames to step for a new picture)"""
    d = _diffs(thumbs)[1:]
    if len(d) < 4:
        return {"frame.fps_effective": float(fps), "step": 1}
    half = max(2, int(round(0.25 * fps)))
    pad = np.pad(d, half, mode="edge")
    upper = np.percentile(np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1), 75, axis=1)
    moving = upper >= 0.004
    if moving.sum() < 8:
        return {"frame.fps_effective": float(fps), "step": 1}
    repeat = d[moving] < np.maximum(0.0015, 0.15 * upper[moving])
    rate = fps * (1.0 - repeat.mean())
    step = max(1, int(round(fps / rate))) if rate > 0 else 1
    if abs(fps / step - rate) < 0.1 * fps / step:
        rate = fps / step
    rate = int(round(rate)) if abs(rate - round(rate)) < 0.01 else float(rate)
    return {"frame.fps_effective": rate, "step": step}
