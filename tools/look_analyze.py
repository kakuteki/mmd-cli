"""Measure the look of a video (or a folder of frames) in numbers: its tone, colour, light, optics, texture and frame.

    python tools/look_analyze.py measure VIDEO|FOLDER OUT.json [--label NAME] [--from S] [--to S] [--pairs N]
                                         [--height 720] [--matrix auto|bt601|bt709] [--jobs N] [--crops DIR]
    python tools/look_analyze.py regions VIDEO OUT.json --model isnetis.onnx [--from S] [--to S] [--frames 48] [--faces CASCADE]
                                         [--matrix auto|bt601|bt709]       # the person and the stage apart
    python tools/look_analyze.py compare OUT.md OUT.json --ref A.json B.json ... --ours X.json Y.json ... [--regions]
    python tools/look_analyze.py figure strip TABLE.json OUT.png
    python tools/look_analyze.py figure profiles OUT.png A.json B.json ...
    python tools/look_analyze.py crops VIDEO OUT.png --at S S ... [--box X0,Y0,X1,Y1] [--size 320x180] [--matrix ...]
    python tools/look_analyze.py annotate VIDEO OUT.png --at S [--what bloom|dof|ca|bars|motion|regions|lighting] [--model ...]
    python tools/look_analyze.py text VIDEO MEASURE.json [--frames 24]      # where the text is (EasyOCR on the CPU)

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

The measures of every sampled frame, of every shot (its medians, for shots with two samples or more) and of the whole
video go into OUT.json with the noise floor of each: how much it changes between the two frames of a pair (almost the same picture) and over the frames of the video.

These read the whole frame, so they read what the frame holds as well as how it was filtered: a small bright person on
a dark stage reads dark, "split toned" (the stage's colour against the person's) and "vignetted" (the dark stage at the
corners) before any filter.  `regions` reads the person and the stage apart (the person's mask from an anime person
model, skytnt/anime-seg's ISNet, on the CPU): each one's tone and colour, the light along the person's outline (a rim
light inside it, the person's glow outside it), the stage's blur against the person's, and the glow of the stage's
lights and of the person's.
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
    mv_look's lens.vignette 0.3, gives about 0.55).  vignette.corner_p10 / corner_p95: the same of each place's 10 and
    95 % points over the frames (the 95 % point is the brightest that passes each place: with a moving camera bright
    things pass the corners too, and the darkening shows on them; a still camera with a bright subject in the middle
    and a dark stage round it reads a strong darkening that is the stage, not the lens)."""
    maps = np.asarray(maps, np.float64)
    r = radius_map(*maps.shape[1:])
    corner, middle = r >= 0.9, r <= 0.3
    mean = maps.mean(axis=0)
    p10, p95 = np.percentile(maps, [10, 95], axis=0)
    out = {}
    for name, m in (("vignette.corner", mean), ("vignette.corner_p10", p10), ("vignette.corner_p95", p95)):
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


# ---- light of one frame -----------------------------------------------------------------------------------------------

BLOOM_SOURCE = 0.9                # Y': the light sources whose glow is read
BLOOM_REACH = 96.0                # 720 line pixels: the glow is read this far out from them, and
BLOOM_BACK = (96.0, 160.0)        # the level it falls to (the background) between these distances
BLOOM_AT = 4.0                    # bloom.strength: the share of the sources' light found this far out (720 px)
BLOOM_NEAR = (2.0, 8.0)           # the glow's colour is read between these distances


def _luminance(lin):
    return lin @ _RGB_TO_XYZ[1]


def _components(mask):
    """labels and sizes of the 8-connected parts of a mask"""
    labels, n = _ndi().label(mask, structure=np.ones((3, 3), bool))
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    return labels, n, sizes


def bloom(rgb, unit=1.0, compact=False, sources=None, rings=None):
    """the glow round the brightest parts of a frame (Y' over BLOOM_SOURCE), read from the mean linear luminance in
    rings at each distance from them, over the level it falls to further out (the background)

    bloom.strength: the rings' light over the background as a share of the sources' light over it, BLOOM_AT 720 line
    pixels from the sources (0 without glow; a glow added at k times the blurred source gives about k times a constant);
    bloom.r50 / r10: the distance (720 line pixels) at which that share falls to a half and a tenth of its value at
    BLOOM_AT (how far the glow reaches; nan without glow); bloom.halo_red / halo_blue: how
    much more of the glow's light than of the source's is red (or blue): a red halo round a white light, as film's
    halation, is positive.  compact: only small sources (under 0.2 % of the frame each: highlights, lamps, sparkles),
    whose rings do not come near a big one.  sources / rings (masks): only the sources where sources is true, read
    only on the pixels where rings is true (the person's glow on the stage, the stage's lights off the person).
    profile: the share at each ring (for the figures)."""
    rgb = np.asarray(rgb, np.float64)
    nan = {"bloom.strength": float("nan"), "bloom.r50": float("nan"), "bloom.r10": float("nan"),
           "bloom.halo_red": float("nan"), "bloom.halo_blue": float("nan"), "bloom.sources": 0.0, "profile": []}
    src = luma(rgb) >= BLOOM_SOURCE
    if sources is not None:
        src &= np.asarray(sources, bool)
    ndi = _ndi()
    far_from_big = None
    if compact:
        labels, n, sizes = _components(src)
        small = (sizes <= max(4, 0.002 * src.size)) & (sizes >= 2)
        small[0] = False
        big = src & ~small[labels]
        src = small[labels]
        if big.any():
            far_from_big = ndi.distance_transform_edt(~big) / unit >= BLOOM_BACK[1]
    if src.sum() < 3:
        return nan
    lin = srgb_to_linear(rgb)
    Y = _luminance(lin)
    dist = ndi.distance_transform_edt(~src)                      # image pixels
    d720 = dist / unit
    use = ~src if far_from_big is None else (~src & far_from_big)
    if rings is not None:
        use &= np.asarray(rings, bool)
    back = use & (d720 >= BLOOM_BACK[0]) & (d720 < BLOOM_BACK[1])
    if back.sum() < 50:
        back = use & (d720 >= BLOOM_REACH / 2)
    if back.sum() < 50:
        return nan
    background = float(np.median(Y[back]))
    bg_rgb = np.median(lin[back], axis=0)
    source = float(Y[src].mean())
    if source - background < 0.05:
        return nan
    ring = np.floor(dist).astype(np.int64)
    sel = use & (d720 < BLOOM_REACH) & (ring >= 1)
    nring = int(math.ceil(BLOOM_REACH * unit)) + 1
    counts = np.bincount(ring[sel], minlength=nring)[:nring]
    sums = np.bincount(ring[sel], weights=Y[sel], minlength=nring)[:nring]
    with np.errstate(invalid="ignore", divide="ignore"):
        share = (sums / counts - background) / (source - background)
    centres = (np.arange(nring) + 0.5) / unit                     # 720 line pixels
    ok = counts >= 8
    xs, ys = centres[ok], share[ok]
    out = dict(nan)
    out["bloom.sources"] = float(src.mean())
    if len(xs) < 2 or xs[0] > BLOOM_AT:
        return out
    ref = float(np.interp(BLOOM_AT, xs, ys))
    out["bloom.strength"] = ref
    if ref >= 0.02:
        after = xs > BLOOM_AT
        px, py = np.r_[BLOOM_AT, xs[after]], np.r_[ref, ys[after]]
        for name, level in (("bloom.r50", 0.5), ("bloom.r10", 0.1)):
            below = np.nonzero(py <= level * ref)[0]
            if len(below):
                k = below[0]
                x0, y0, x1, y1 = px[k - 1], py[k - 1], px[k], py[k]
                out[name] = float(x0 + (level * ref - y0) * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x1)
    halo = sel & (d720 >= BLOOM_NEAR[0]) & (d720 <= BLOOM_NEAR[1])
    if halo.sum() >= 8:
        e = np.clip(lin[halo].mean(axis=0) - bg_rgb, 0.0, None)
        s = np.clip(lin[src].mean(axis=0) - bg_rgb, 1e-9, None)
        if e.sum() > 1e-6:
            out["bloom.halo_red"] = float(e[0] / e.sum() - s[0] / s.sum())
            out["bloom.halo_blue"] = float(e[2] / e.sum() - s[2] / s.sum())
    out["profile"] = [[float(c), float(v)] for c, v, k in zip(centres, share, ok) if k]
    return out


STREAK_RING = (6.0, 40.0)         # 720 line pixels round a small highlight where its rays are read,
STREAK_BACK = (40.0, 60.0)        # against the level of this ring
STREAK_BINS = 36
STREAK_HARMONICS = (2, 4, 6, 8)


def streaks(rgb, unit=1.0):
    """rays from small highlights (a star filter, an anamorphic streak): the light round each highlight between
    STREAK_RING over the level further out, summed over the highlights by angle, and its angular harmonics

    streak.strength: the largest of the harmonics 2, 4, 6, 8 over the mean (0 for a round glow, near 1 for thin rays);
    streak.rays: the fewest rays that give it (the smallest harmonic within 0.85 of the largest; 2 is a streak through
    the light, 4 a cross); streak.angle: the angle of a ray (degrees counterclockwise from the right, modulo 360 / rays);
    streak.sources: how many highlights were read."""
    rgb = np.asarray(rgb, np.float64)
    out = {"streak.strength": float("nan"), "streak.rays": float("nan"), "streak.angle": float("nan"),
           "streak.sources": 0.0}
    src = luma(rgb) >= BLOOM_SOURCE
    labels, n, sizes = _components(src)
    if n == 0:
        return out
    h, w = src.shape
    Y = _luminance(srgb_to_linear(rgb))
    reach = STREAK_BACK[1] * unit
    centres = _ndi().center_of_mass(src, labels, range(1, n + 1))
    profile = np.zeros(STREAK_BINS)
    used = 0
    for k, (cy, cx) in enumerate(centres, start=1):
        if sizes[k] > max(4, 0.002 * src.size) or sizes[k] < 1:
            continue
        if cy - reach < 0 or cx - reach < 0 or cy + reach >= h or cx + reach >= w:
            continue                                            # its rings would leave the frame
        y0, y1, x0, x1 = int(cy - reach), int(cy + reach) + 1, int(cx - reach), int(cx + reach) + 1
        yy, xx = np.mgrid[y0:y1, x0:x1]
        r = np.hypot(yy - cy, xx - cx) / unit
        win = Y[y0:y1, x0:x1]
        backr = (r >= STREAK_BACK[0]) & (r < STREAK_BACK[1])
        ring = (r >= STREAK_RING[0]) & (r < STREAK_RING[1]) & ~src[y0:y1, x0:x1]
        if backr.sum() < 20 or ring.sum() < STREAK_BINS:
            continue
        excess = win[ring] - np.median(win[backr])
        theta = np.arctan2(-(yy[ring] - cy), xx[ring] - cx) % (2 * math.pi)
        b = np.minimum((theta / (2 * math.pi) * STREAK_BINS).astype(int), STREAK_BINS - 1)
        cnt = np.bincount(b, minlength=STREAK_BINS)
        if (cnt == 0).any():
            continue
        mean = np.bincount(b, weights=excess, minlength=STREAK_BINS) / cnt
        if mean.mean() <= 0:
            continue
        profile += np.clip(mean, 0.0, None) / max(mean.max(), 1e-12)
        used += 1
    out["streak.sources"] = float(used)
    if used == 0 or profile.sum() <= 0:
        return out
    angles = (np.arange(STREAK_BINS) + 0.5) * 2 * math.pi / STREAK_BINS
    mags = {}
    for k in STREAK_HARMONICS:
        mags[k] = (profile * np.exp(-1j * k * angles)).sum() / profile.sum()
    best = max(abs(f) for f in mags.values())
    rays = min(k for k in STREAK_HARMONICS if abs(mags[k]) >= 0.85 * best)
    out["streak.strength"] = float(best)
    out["streak.rays"] = float(rays)
    out["streak.angle"] = float((math.degrees(-np.angle(mags[rays])) / rays) % (360.0 / rays))
    return out


def light(rgb, lab):
    """two rough proxies for the light of a frame: light.key_hue / key_chroma, the hue and size of the mean a*b* of its
    brightest 2 % (L*); light.lr / light.tb, how much brighter (Y') the right half is than the left (and the top than
    the bottom), as a share of their sum"""
    L = lab[..., 0]
    top = L >= np.percentile(L, 98)
    a, b = float(lab[..., 1][top].mean()), float(lab[..., 2][top].mean())
    Yp = luma(rgb)
    h, w = Yp.shape
    left, right = Yp[:, :w // 2].mean(), Yp[:, w - w // 2:].mean()
    upper, lower = Yp[:h // 2].mean(), Yp[h - h // 2:].mean()
    return {"light.key_hue": _hue(a, b), "light.key_chroma": float(math.hypot(a, b)),
            "light.lr": float((right - left) / max(right + left, 1e-9)),
            "light.tb": float((upper - lower) / max(upper + lower, 1e-9))}


# ---- the lighting of a frame and of a video (typoref, 2026-10-20) ------------------------------------------------------
#
# The light falling in the scene: shafts of light (beams, the light of a spotlight seen in haze or fog) and pools of
# light (spots), read on the frame made small (BEAM_LINES lines) as what rises above the slowly varying light round it,
# soft inside (SOFT_PLATEAU: not a lit window, a sign or a bar of light);
# how many colours the bright parts of a frame have; over a video, how many colours its key light takes and how often
# it changes them, how much it flickers and strobes, and how fast its brightest part moves.

BEAM_LINES = 180                  # the frame is read this many lines tall (averaging whole pixels)
BEAM_BG = 18.0                    # px at BEAM_LINES: the light round a part is the frame blurred by this
BEAM_LEAST = 0.01                 # linear luminance: a part rises at least this above the light round it,
BEAM_SHARE = 0.2                  # and at least this share of the frame's highest rise (its 99.9th percentile)
BEAM_ELONG = 3.0                  # a beam: this many times longer than wide (second moments),
BEAM_LENGTH = 0.25                # at least this long (share of the frame's height),
BEAM_WIDTH = 0.02                 # and at least this wide at half its rise (a painted line or a bar is thinner)
SPOT_ELONG = 3.0                  # a spot: rounder than this (a pool on the floor seen at a slant is 2 to 3 times wider
#                                   than deep),
SPOT_AREA = 0.003                 # covering at least this share of the frame,
SPOT_WIDTH = 0.04                 # and at least this wide at half its rise
SOFT_PLATEAU = 0.45               # beams and spots are soft: under this share of a part rises to 3/4 of its highest (a
#                                   Gaussian pool 0.18, a Gaussian shaft 0.4; a lit window or a bar of light, flat inside,
#                                   0.7 and more)
COLOUR_BINS = 36                  # hue bins of the bright, coloured pixels (10 degrees)
COLOUR_LEAST = 0.10               # a colour of the light holds at least this share of their chroma
STROBE_GAP = 0.35                 # s between the starts of flashes of one strobe at most, and
STROBE_LEAST = 3                  # this many flashes at least
FLICKER_WINDOW = 0.25             # s: the flicker is the mean Y' less its mean over this
PALETTE_LEAST = 0.05              # a colour of the key light holds at least this share of the coloured frames
CHANGE_HUE = 40.0                 # degrees between shots' key light: a change of colour
KEY_COLOURED = 15.0               # C*: the key light is coloured above this


def beams(rgb, unit=1.0, extras=None):
    """the shafts and pools of light of a frame (rgb 0..1): beam.count, beam.share (of the frame), beam.length (of its
    height), beam.angle (from the vertical, degrees), spot.count, spot.share.  extras (a dict) gets the label map at
    BEAM_LINES and the labels of the beams and of the spots (for annotate)"""
    cv2 = _cv2()
    ndi = _ndi()
    lin = _luminance(srgb_to_linear(np.asarray(rgb, np.float64)))
    h, w = lin.shape
    hs = BEAM_LINES
    ws = max(8, int(round(w * hs / float(h))))
    small = cv2.resize(lin.astype(np.float32), (ws, hs), interpolation=cv2.INTER_AREA).astype(np.float64)
    b = ndi.gaussian_filter(small, 1.0)
    r = b - ndi.gaussian_filter(small, BEAM_BG)
    top = float(np.percentile(r, 99.9))
    th = max(BEAM_LEAST, BEAM_SHARE * top)
    lab, n = ndi.label(r > th, structure=np.ones((3, 3)))
    out = {"beam.count": 0, "beam.share": 0.0, "beam.length": float("nan"), "beam.angle": float("nan"),
           "spot.count": 0, "spot.share": 0.0}
    lengths, angles, beam_area, spot_area = [], [], 0, 0
    for k, sl in enumerate(ndi.find_objects(lab), start=1):
        if sl is None:
            continue
        part = lab[sl] == k
        area = int(part.sum())
        if area < 15:
            continue
        ys, xs = np.nonzero(part)
        cov = np.cov(np.stack([xs, ys]).astype(np.float64))
        vals, vecs = np.linalg.eigh(cov)
        l2, l1 = max(vals[0], 1e-9), max(vals[1], 1e-9)
        elong = math.sqrt(l1 / l2)
        length = 4.0 * math.sqrt(l1) / hs
        rr = r[sl][part]
        vx, vy = vecs[0, 1], vecs[1, 1]
        # its width at half its rise, step by step along it (a beam fades along its length): the pixels of each 1 px
        # slice across it that reach half that slice's highest
        along = np.round((xs - xs.mean()) * vx + (ys - ys.mean()) * vy).astype(int)
        widths = []
        for k2 in np.unique(along):
            sel = along == k2
            if sel.sum() >= 2:
                widths.append(int((rr[sel] >= 0.5 * rr[sel].max()).sum()))
        width = float(np.median(widths)) / hs if widths else 0.0
        angle = abs(math.degrees(math.atan2(vx, vy)))
        angle = 180.0 - angle if angle > 90.0 else angle
        soft = float((rr >= 0.75 * rr.max()).sum()) / area < SOFT_PLATEAU
        if not soft:
            continue
        if elong >= BEAM_ELONG and length >= BEAM_LENGTH and width >= BEAM_WIDTH:
            out["beam.count"] += 1
            beam_area += area
            lengths.append(length)
            angles.append(angle)
            if extras is not None:
                extras.setdefault("beam_labels", []).append(k)
        elif elong < SPOT_ELONG and area >= SPOT_AREA * hs * ws and width >= SPOT_WIDTH:
            out["spot.count"] += 1
            spot_area += area
            if extras is not None:
                extras.setdefault("spot_labels", []).append(k)
    if extras is not None:
        extras["light_map"] = lab
    out["beam.share"] = beam_area / float(hs * ws)
    out["spot.share"] = spot_area / float(hs * ws)
    if lengths:
        out["beam.length"] = float(np.median(lengths))
        out["beam.angle"] = float(np.median(angles))
    return out


def light_colours(rgb, lab):
    """how many colours the bright parts of a frame have: light.colours, the peaks of the hue (chroma-weighted, circular)
    of its coloured bright pixels (L* in its top 5 % and at least 25, C* at least 15) holding COLOUR_LEAST of their
    chroma each; light.spread, the circular spread of their hue (degrees)"""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    bright = (L >= max(25.0, float(np.percentile(L, 95)))) & (C >= 15.0)
    if bright.sum() < 20:
        return {"light.colours": 0, "light.spread": 0.0}
    hue = np.degrees(np.arctan2(b[bright], a[bright])) % 360.0
    wgt = C[bright]
    hist = np.bincount((hue / (360.0 / COLOUR_BINS)).astype(int) % COLOUR_BINS, weights=wgt, minlength=COLOUR_BINS)
    hist = hist / hist.sum()
    sm = np.convolve(np.concatenate([hist[-2:], hist, hist[:2]]), [0.25, 0.5, 1.0, 0.5, 0.25], mode="same")[2:-2] / 2.5
    peaks = 0
    for i in range(COLOUR_BINS):
        if sm[i] >= sm[i - 1] and sm[i] > sm[(i + 1) % COLOUR_BINS]:
            mass = sum(hist[(i + d) % COLOUR_BINS] for d in (-2, -1, 0, 1, 2))
            if mass >= COLOUR_LEAST:
                peaks += 1
    ang = np.radians(hue)
    R = math.hypot(float((wgt * np.cos(ang)).sum() / wgt.sum()), float((wgt * np.sin(ang)).sum() / wgt.sum()))
    spread = math.degrees(math.sqrt(max(0.0, -2.0 * math.log(max(R, 1e-9)))))
    return {"light.colours": int(peaks), "light.spread": float(spread)}


def light_palette(rows, duration):
    """over a video's sampled frames (rows with light.key_hue and light.key_chroma): lightcol.palette, the colours its key
    light takes (30 degree bins holding PALETTE_LEAST of the frames where it is coloured); lightcol.colourful, the share of
    frames whose key light is coloured (C* over 20); lightcol.changes_per_min, the changes of the key light's colour
    (CHANGE_HUE) from shot to shot a minute"""
    hues, chromas, shots = [], [], {}
    for r in rows:
        hdeg, c = r["m"].get("light.key_hue"), r["m"].get("light.key_chroma")
        if hdeg is None or c is None or not (np.isfinite(hdeg) and np.isfinite(c)):
            continue
        chromas.append(c)
        if c >= KEY_COLOURED:
            hues.append(hdeg % 360.0)
            shots.setdefault(r.get("shot", 0), []).append(hdeg % 360.0)
    out = {"lightcol.palette": 0, "lightcol.colourful": float(np.mean(np.array(chromas) > 20.0)) if chromas else float("nan"),
           "lightcol.changes_per_min": 0.0}
    if hues:
        counts = np.bincount((np.array(hues) / 30.0).astype(int) % 12, minlength=12) / float(len(hues))
        out["lightcol.palette"] = int((counts >= PALETTE_LEAST).sum())
    means = []
    for k in sorted(shots):
        a = np.radians(shots[k])
        means.append(math.degrees(math.atan2(np.sin(a).mean(), np.cos(a).mean())) % 360.0)
    changes = sum(1 for x, y in zip(means, means[1:]) if min(abs(x - y), 360.0 - abs(x - y)) > CHANGE_HUE)
    out["lightcol.changes_per_min"] = changes / (duration / 60.0) if duration > 0 else float("nan")
    return out


def flicker(series, fps, flash_events=None, cuts=None):
    """the flicker of a per-frame mean Y' series: flicker.hf, the rms of the series less its running mean over
    FLICKER_WINDOW s, on the frames away from the cuts (frame numbers: a cut is a step of the mean, not a flicker of the
    light; typorev: the references' median 0.016 is 0.0098 with their cuts left out, Cinderella / Miku's 0.012 is 0.0027;
    the flashes stay in: a flash is a flicker of the light); strobe.per_min,
    the runs of at least STROBE_LEAST flashes (see flashes) at most STROBE_GAP s apart"""
    x = np.asarray(series, np.float64)
    k = max(3, int(round(FLICKER_WINDOW * fps)) | 1)
    run = np.convolve(np.pad(x, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
    keep = np.ones(x.size, bool)
    for c in (cuts or ()):
        keep[max(0, int(c) - k // 2 - 1):int(c) + k // 2 + 1] = False
    hf = float(np.sqrt(np.mean((x[keep] - run[keep]) ** 2))) if keep.any() else float("nan")
    events = flash_events if flash_events is not None else flashes(x, fps)[0]
    starts = [e["start"] / float(fps) for e in events]
    strobes, run_len = 0, 1
    for a, b in zip(starts, starts[1:]):
        if b - a <= STROBE_GAP:
            run_len += 1
        else:
            if run_len >= STROBE_LEAST:
                strobes += 1
            run_len = 1
    if run_len >= STROBE_LEAST:
        strobes += 1
    minutes = x.size / float(fps) / 60.0
    return {"flicker.hf": hf, "strobe.per_min": strobes / minutes if minutes > 0 else float("nan")}


def light_motion(thumbs, fps, height_px=None):
    """how fast the brightest part of the picture moves: lightmove.speed, the median speed (720 line px a second) of the
    middle of the brightest pixels (Y' over 0.6 and in the top 1 %) of thumbnails (N x h x w, 0..1) over a fifth of a
    second, leaving out spans with a cut (a frame that changes by more than CUT_LEAST)"""
    t = np.asarray(thumbs, np.float64)
    hpx = float(height_px or t.shape[1])
    cents = []
    for f in t:
        on = f >= max(0.6, float(np.percentile(f, 99)))
        if on.sum() == 0:
            cents.append(None)
            continue
        ys, xs = np.nonzero(on)
        wgt = f[on]
        cents.append(((xs * wgt).sum() / wgt.sum(), (ys * wgt).sum() / wgt.sum()))
    d = _diffs(t)
    # over a fifth of a second (a thumbnail's pixel steps are coarse), with no cut between
    k = max(1, int(round(0.2 * fps)))
    cut_at = np.cumsum(d > CUT_LEAST)
    speeds = []
    for i in range(k, len(cents)):
        if cents[i] is None or cents[i - k] is None or cut_at[i] != cut_at[i - k]:
            continue
        speeds.append(math.hypot(cents[i][0] - cents[i - k][0], cents[i][1] - cents[i - k][1]) / k * REFERENCE_HEIGHT / hpx * fps)
    return {"lightmove.speed": float(np.median(speeds)) if speeds else float("nan")}


# ---- texture of one frame ---------------------------------------------------------------------------------------------

_IMMERKAER = np.array([[1.0, -2.0, 1.0], [-2.0, 4.0, -2.0], [1.0, -2.0, 1.0]])


def flat_mask(gray, sigma=2.0, grow=2):
    """the pixels away from edges: the gradient of the picture smoothed by sigma under 3 times its median, the edges
    grown by grow pixels (smoothing first keeps the choice of pixels from following the noise in them)"""
    ndi = _ndi()
    s = ndi.gaussian_filter(gray, sigma)
    g = np.hypot(ndi.sobel(s, axis=1), ndi.sobel(s, axis=0))
    edge = g > 3.0 * max(float(np.median(g)), 1e-4)
    if grow:
        edge = ndi.binary_dilation(edge, iterations=grow)
    return ~edge


def noise_spatial(gray):
    """the noise of the flat areas of a Y' frame (Immerkaer 1996: a Laplacian-like 3 x 3 filter that cancels plain
    shading), in steps of 255: noise.spatial"""
    gray = np.asarray(gray, np.float64)
    conv = _ndi().convolve(gray, _IMMERKAER, mode="reflect")
    flat = flat_mask(gray)
    flat[:1], flat[-1:], flat[:, :1], flat[:, -1:] = False, False, False, False
    if flat.sum() < 100:
        return {"noise.spatial": float("nan")}
    return {"noise.spatial": float(math.sqrt(math.pi / 2.0) * np.abs(conv[flat]).mean() / 6.0 * 255.0)}


def grain(gray0, gray1, unit=1.0, still=None):
    """the grain that changes from one frame to the next, read from their difference where the picture stands still
    (still: a mask, e.g. from the optical flow; the flat areas of both frames are used in any case)

    grain.temporal: its standard deviation in one frame (the robust spread of the difference over sqrt 2), in steps of
    255; grain.size: the distance (720 line pixels) at which the difference's autocorrelation falls to a half (about 1
    for grain of single pixels, more for coarse grain)."""
    g0, g1 = np.asarray(gray0, np.float64), np.asarray(gray1, np.float64)
    mask = flat_mask(g0) & flat_mask(g1)
    if still is not None:
        mask &= still
    out = {"grain.temporal": float("nan"), "grain.size": float("nan")}
    if mask.sum() < 500:
        return out
    d = g1 - g0
    v = d[mask]
    mad = float(np.median(np.abs(v - np.median(v))))
    out["grain.temporal"] = 1.4826 * mad / math.sqrt(2.0) * 255.0
    if mad <= 0:
        return out
    m = mask.astype(np.float64)
    dm = (d - v.mean()) * m
    fd = np.fft.rfft2(dm)
    fm = np.fft.rfft2(m)
    acf = np.fft.irfft2(fd * np.conj(fd), s=d.shape)
    norm = np.fft.irfft2(fm * np.conj(fm), s=d.shape)
    acf = acf / np.maximum(norm, 1.0)
    lags = min(12, d.shape[0] // 4, d.shape[1] // 4)
    r = np.array([(acf[0, k] + acf[k, 0]) / 2.0 for k in range(lags)])
    r = r / r[0]
    for k in range(1, lags):
        if r[k] <= 0.5:
            out["grain.size"] = float(((k - 1) + (r[k - 1] - 0.5) / (r[k - 1] - r[k])) / unit)
            break
    return out


def scanlines(gray):
    """scanlines: a period of 2 to 10 rows in the rows' mean Y' (the rows less their 9-row running mean): scan.peak, the
    strongest frequency of that band over the band's median (a few for a picture without lines), scan.period (rows)"""
    rows = np.asarray(gray, np.float64).mean(axis=1)
    hp = rows - _ndi().uniform_filter1d(rows, 9, mode="reflect")
    spec = np.abs(np.fft.rfft(hp * np.hanning(len(hp))))
    freq = np.fft.rfftfreq(len(hp))
    band = (freq >= 1.0 / 10.0) & (freq <= 0.5)
    if band.sum() < 4:
        return {"scan.peak": float("nan"), "scan.period": float("nan")}
    s = spec[band]
    i = int(np.argmax(s))
    return {"scan.peak": float(s[i] / max(np.median(s), 1e-12)), "scan.period": float(1.0 / freq[band][i])}


GLITCH_SHIFT = 6                  # pixels: a torn row is moved at least this much against the row above
GLITCH_SEARCH = 32


def glitch(gray):
    """torn rows (a glitch effect): rows whose horizontal detail matches the row above best when moved by
    GLITCH_SHIFT pixels or more (the match strong, and clearly better than unmoved): glitch.tears, how many"""
    g = np.asarray(gray, np.float64)
    gx = np.diff(g, axis=1, prepend=g[:, :1])
    gx -= gx.mean(axis=1, keepdims=True)
    n = gx.shape[1]
    f = np.fft.rfft(gx, n=2 * n, axis=1)
    corr = np.fft.irfft(f[1:] * np.conj(f[:-1]), n=2 * n, axis=1)
    lags = np.r_[np.arange(0, GLITCH_SEARCH + 1), np.arange(-GLITCH_SEARCH, 0)]
    corr = np.concatenate([corr[:, :GLITCH_SEARCH + 1], corr[:, -GLITCH_SEARCH:]], axis=1)
    energy = np.sqrt((gx[1:] ** 2).sum(axis=1) * (gx[:-1] ** 2).sum(axis=1))
    ok = energy > 1e-9
    corr[ok] /= energy[ok, None]
    best = np.argmax(corr, axis=1)
    c_best = corr[np.arange(len(best)), best]
    c_zero = corr[:, 0]
    shift = lags[best]
    torn = ok & (np.abs(shift) >= GLITCH_SHIFT) & (c_best >= 0.5) & (c_zero <= 0.5 * c_best)
    return {"glitch.tears": float(torn.sum())}


# ---- optics of one frame: the blur of edges, depth of field, motion blur, colour fringes, distortion -------------------

EDGE_POINTS = 4000                # edges read per frame at most (a random choice, the same for the same frame)
EDGE_LEAST = 0.03                 # an edge's gradient (Y' per pixel, Sobel) at least this
SOBEL_VAR = 0.5                   # px^2: the Sobel gradient and the pixel grid widen a step by this (measured on
                                  # synthetic steps blurred by 0 to 8 px: est^2 - true^2 = 0.51 to 0.70)
REBLUR = (1.0, 3.0, 8.0)          # px: the re-blurs; an edge is read with the narrowest whose reading stays under
SWITCH = (2.5, 6.0, float("inf"))  # its switch (a narrow re-blur hardly lowers a soft edge's gradient)


def _gradient(gray):
    ndi = _ndi()
    gx, gy = ndi.sobel(gray, axis=1) / 8.0, ndi.sobel(gray, axis=0) / 8.0
    return gx, gy, np.hypot(gx, gy)


def edges(gray, unit=1.0, seed=0, points=EDGE_POINTS, least=EDGE_LEAST, mask=None):
    """the edges of a Y' frame (Canny's thin lines of the strongest gradient) with each one's blur

    The blur is read as Zhuo and Sim (2011) do: blurring the frame again by a known s0 lowers an edge's gradient by
    sqrt(sigma^2 + s0^2) / sigma, so sigma follows from the ratio of the two gradients, whatever the edge's contrast
    (the Sobel gradient's own width taken out); s0 is 1, 3 or 8 px (the narrowest that still reads the edge).
    least: the weakest gradient taken (a motion-blurred edge is weak); mask: only edges where it is true.  Returns
    arrays y, x (pixels), nx, ny (the unit normal, towards the bright side), mag (the gradient), sigma (the blur, as a
    Gaussian's standard deviation, in 720 line pixels) and scale (the re-blur it was read with)."""
    cv2, ndi = _cv2(), _ndi()
    g = np.asarray(gray, np.float64)
    gx, gy, mag = _gradient(g)
    u8 = np.clip(ndi.gaussian_filter(g, 0.7) * 255.0, 0, 255).astype(np.uint8)
    hi = least * 255.0 * 8.0 if least < EDGE_LEAST else max(least * 255.0 * 8.0, float(np.percentile(mag, 90)) * 255.0 * 8.0)
    canny = cv2.Canny(u8, hi / 2.0, hi, L2gradient=True, apertureSize=3) > 0
    canny[:3], canny[-3:], canny[:, :3], canny[:, -3:] = False, False, False, False
    sel = canny & (ndi.maximum_filter(mag, size=3) >= least)
    if mask is not None:
        sel &= mask
    ys, xs = np.nonzero(sel)
    if len(ys) > points:
        pick = np.random.default_rng(seed).choice(len(ys), points, replace=False)
        ys, xs = ys[pick], xs[pick]
    peak = ndi.maximum_filter(mag, size=3)            # Canny's line may lie a pixel off the raw gradient's top
    m0 = peak[ys, xs]
    sigmas = {}
    for s0 in REBLUR:
        m1 = ndi.maximum_filter(_gradient(ndi.gaussian_filter(g, s0))[2], size=3)[ys, xs]
        with np.errstate(invalid="ignore", divide="ignore"):
            r = m0 / m1
            est2 = s0 * s0 / np.maximum(r * r - 1.0, 1e-9)
        sigmas[s0] = np.sqrt(np.clip(est2 - SOBEL_VAR, 0.0, None))
    sigma = sigmas[REBLUR[-1]].copy()
    scale = np.full(len(sigma), REBLUR[-1])
    for s0, top in reversed(list(zip(REBLUR[:-1], SWITCH[:-1]))):
        use = sigmas[s0] <= top
        sigma = np.where(use, sigmas[s0], sigma)
        scale = np.where(use, s0, scale)
    sx, sy, smag = _gradient(ndi.gaussian_filter(g, 1.0))      # the normal from the smoothed frame (steadier)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx, ny = sx[ys, xs] / smag[ys, xs], sy[ys, xs] / smag[ys, xs]
    good = np.isfinite(sigma) & (sigma < 40.0 * unit) & np.isfinite(nx) & np.isfinite(ny)
    return {"y": ys[good], "x": xs[good], "nx": nx[good], "ny": ny[good], "mag": m0[good],
            "sigma": sigma[good] / unit, "scale": scale[good], "shape": g.shape}


SOFT_EDGE = 3.0                   # 720 line pixels: an edge blurred more than this is soft (out of focus)


def depth_of_field(e):
    """depth of field from the blur of a frame's edges (720 line pixels): dof.sharp, dof.median, dof.soft: the 10, 50
    and 90 % points (an MMD frame without depth of field has every edge near its sharpest); dof.soft_share: the share
    of edges softer than SOFT_EDGE; dof.edges: how many were read"""
    s = np.asarray(e["sigma"])
    if len(s) < 30:
        return {"dof.sharp": float("nan"), "dof.median": float("nan"), "dof.soft": float("nan"),
                "dof.soft_share": float("nan"), "dof.edges": float(len(s))}
    p10, p50, p90 = np.percentile(s, [10, 50, 90])
    return {"dof.sharp": float(p10), "dof.median": float(p50), "dof.soft": float(p90),
            "dof.soft_share": float((s > SOFT_EDGE).mean()), "dof.edges": float(len(s))}


DOF_BLOCK = 40.0                  # 720 line pixels: depth of field is read in blocks this wide,
DOF_CONTRAST = 0.10               # those whose Y' spreads at least this (5 to 95 %: they hold detail),
DOF_TOP = 0.02                    # each by the blur of its steepest 2 % of pixels


DOF_PRE = 0.0                     # image px: blur the frame by this first (and take it out after); 0 none
DOF_LINES = 180                   # depth of field is read on the frame made this small (averaging whole pixels): the
                                  # noise and the coding blocks of a compressed video, which read sharp, average out,
                                  # while a background blurred by several pixels stays blurred


def blur_map(gray, pre=DOF_PRE):
    """the blur (image pixels) edges() would read at every pixel of the frame blurred by pre (pre taken out after), and
    the gradient there (its top over 3 x 3)"""
    ndi = _ndi()
    g = np.asarray(gray, np.float64)
    if pre:
        g = ndi.gaussian_filter(g, pre)
    m0 = ndi.maximum_filter(_gradient(g)[2], size=3)
    sigma = None
    for s0, top in reversed(list(zip(REBLUR, SWITCH))):
        m1 = ndi.maximum_filter(_gradient(ndi.gaussian_filter(g, s0))[2], size=3)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = m0 / np.maximum(m1, 1e-12)
            est = np.sqrt(np.clip(s0 * s0 / np.maximum(r * r - 1.0, 1e-9) - SOBEL_VAR, 0.0, None))
        sigma = est if sigma is None else np.where(est <= top, est, sigma)
    if pre:
        sigma = np.sqrt(np.clip(sigma * sigma - pre * pre, 0.0, None))
    return sigma, m0


def _blur_blocks(gray, unit=1.0, cover=None):
    """the blocks of dof_blocks: (the blur of each block in 720 line pixels, nan where it holds no detail; the share of
    each block that cover (a mask the size of the frame) covers, or None; the block's size in the frame's pixels), or
    None when the frame holds fewer than 2 x 2 blocks"""
    g = np.asarray(gray, np.float64)
    f = max(1, int(round(g.shape[0] / float(DOF_LINES))))
    c = None if cover is None else np.asarray(cover, np.float64)
    if f > 1:
        hh, ww = (g.shape[0] // f) * f, (g.shape[1] // f) * f
        g = g[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
        if c is not None:
            c = c[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
        unit = unit / f
    sigma, mag = blur_map(g)
    b = max(6, int(round(DOF_BLOCK * unit)))
    h, w = g.shape
    ny, nx = h // b, w // b
    if ny < 2 or nx < 2:
        return None

    def tiles(a):
        return a[:ny * b, :nx * b].reshape(ny, b, nx, b).transpose(0, 2, 1, 3).reshape(ny, nx, b * b)

    tg, ts, tm = tiles(g), tiles(sigma), tiles(mag)
    lo, hi = np.percentile(tg, [5, 95], axis=2)
    textured = (hi - lo) >= DOF_CONTRAST
    k = max(4, int(round(DOF_TOP * b * b)))
    order = np.argsort(tm, axis=2)[:, :, -k:]
    steep = np.take_along_axis(ts, order, axis=2)
    block = np.median(steep, axis=2) / unit
    block[~textured] = np.nan
    share = tiles(c).mean(axis=2) if c is not None else None
    return block, share, b * f


def dof_blocks(gray, unit=1.0, extras=None):
    """depth of field read in blocks (the edges Canny finds keep to what is in focus; a blurred background has weak
    edges): on the frame made DOF_LINES lines tall, each block of DOF_BLOCK px whose Y' spreads at least DOF_CONTRAST is
    read by the median blur of its steepest DOF_TOP of pixels (720 line pixels; blurs under about 2 px are not told
    apart at this size)

    dof.fg_blur / bg_blur: the 25 and 75 % points over the blocks (the sharp side, what is in focus, and the soft
    side); dof.ratio: (bg + 1) / (fg + 1): about 1 to 1.3 when all is in focus (a sharp step reads 0 to 2 px at this
    size, by where it falls on the pixels), several with a blurred background (soft light, haze or glow behind the
    subject read the same); dof.soft_blocks: the share of blocks softer than SOFT_EDGE; dof.blocks: how many blocks
    hold detail.  extras gets the block map."""
    out = {"dof.fg_blur": float("nan"), "dof.bg_blur": float("nan"), "dof.ratio": float("nan"),
           "dof.soft_blocks": float("nan"), "dof.blocks": 0.0}
    got = _blur_blocks(gray, unit)
    if got is None:
        return out
    block, _, size = got
    vals = np.sort(block[np.isfinite(block)])
    out["dof.blocks"] = float(len(vals))
    if extras is not None:
        extras["dof_map"] = (block, size)
    if len(vals) < 6:
        return out
    fg, bg = (float(v) for v in np.percentile(vals, [25, 75]))
    out.update({"dof.fg_blur": fg, "dof.bg_blur": bg, "dof.ratio": (bg + 1.0) / (fg + 1.0),
                "dof.soft_blocks": float((vals > SOFT_EDGE).mean())})
    return out


SHORT = (8.0, 16.0)               # 720 line pixels: the near sides of an edge (sharpening, width) and
LONG = (28.0, 40.0)               # the far sides (diffusion), where a step's flat sides are read
STEP_LEAST = 0.12                 # Y': a step read for its profile rises at least this,
FLAT_MOST = 0.04                  # and each side's spread stays under this
INNER = 4.0                       # diffusion: the share of the step not reached within this of the edge (720 px)
DIFFUSION_TOP = 0.65              # Y': diffusion is read on steps whose bright side is at most this (a glow of the
BRIGHT_EDGE = 0.85                # bright parts does not reach them); the glow's own skirt on steps from this up
CORE_MOST = 3.0                   # diffusion is read on edges whose core is at most this blurred (720 px)
PROFILE_POINTS = 1500


def _profiles(gray, e, half, unit, idx):
    ndi = _ndi()
    t = np.arange(-half, half + 1.0)                                   # 720 line pixels
    ys = e["y"][idx][:, None] + e["ny"][idx][:, None] * t[None, :] * unit
    xs = e["x"][idx][:, None] + e["nx"][idx][:, None] * t[None, :] * unit
    return t, ndi.map_coordinates(gray, [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(ys.shape)


def _steps(t, p, sides):
    """the profiles that are clean steps between flat sides at |t| in sides: normalised to 0 (dark side) .. 1"""
    far_lo = (t >= -sides[1]) & (t <= -sides[0])
    far_hi = (t >= sides[0]) & (t <= sides[1])
    lo, hi = p[:, far_lo].mean(axis=1), p[:, far_hi].mean(axis=1)
    flat = (p[:, far_lo].std(axis=1) <= FLAT_MOST) & (p[:, far_hi].std(axis=1) <= FLAT_MOST)
    ok = flat & (hi - lo >= STEP_LEAST)
    q = (p[ok] - lo[ok, None]) / (hi - lo)[ok, None]
    _steps.hi = hi[ok]
    return ok, q


def _cross(t, q, level, start, direction):
    """where a profile q (over t) first reaches level going from start in direction (+1 or -1), interpolated"""
    i = int(np.argmin(np.abs(t - start)))
    rng = range(i, len(t) - 1) if direction > 0 else range(i, 0, -1)
    for k in rng:
        k2 = k + direction
        a, b = q[k], q[k2]
        if (a - level) * (b - level) <= 0 and a != b:
            return t[k] + (level - a) * (t[k2] - t[k]) / (b - a)
    return float("nan")


def _middle(t, q):
    """where a step's profile crosses its half nearest the edge found"""
    up, down = _cross(t, q, 0.5, 0.0, +1), _cross(t, q, 0.5, 0.0, -1)
    if np.isfinite(up) and np.isfinite(down):
        return up if abs(up) <= abs(down) else down
    return up if np.isfinite(up) else down


def _width(t, q):
    """the 10 to 90 % rise of a step's profile about its middle"""
    mid = _middle(t, q)
    if not np.isfinite(mid):
        return float("nan")
    return _cross(t, q, 0.9, mid, +1) - _cross(t, q, 0.1, mid, -1)


def edge_profiles(gray, e, unit=1.0, seed=0):
    """what the edges' profiles across them show (sampled along each edge's normal, 720 line pixels)

    sharp.width: the 10 to 90 % rise of clean steps (flat sides 8 to 16 px out); sharp.overshoot: how far the profile
    goes past its flat sides next to the edge (the halo of sharpening, as a share of the step); diffusion.share: on
    steps with flat sides 28 to 40 px out, a sharp core and a bright side at most DIFFUSION_TOP, the share of the step
    not reached within INNER px of the edge, less what the core's own blur leaves there (a veil over the frame: the
    sharp core stays, a wide soft skirt is added); diffusion.radius: how far out that skirt reaches half of the rest;
    glow.edge_share / edge_radius: the same on steps whose bright side is at least BRIGHT_EDGE (the skirt a glow of the
    bright parts adds, which diffusion leaves to these); profile.short / long: how many steps."""
    g = np.asarray(gray, np.float64)
    n = len(e["y"])
    out = {"sharp.width": float("nan"), "sharp.overshoot": float("nan"), "diffusion.share": float("nan"),
           "diffusion.radius": float("nan"), "glow.edge_share": float("nan"), "glow.edge_radius": float("nan"),
           "profile.short": 0.0, "profile.long": 0.0}
    if n == 0:
        return out
    idx = np.arange(n)
    if n > PROFILE_POINTS:
        idx = np.random.default_rng(seed).choice(n, PROFILE_POINTS, replace=False)
    t, p = _profiles(g, e, SHORT[1], unit, idx)
    ok, q = _steps(t, p, SHORT)
    out["profile.short"] = float(ok.sum())
    if ok.sum() >= 10:
        widths, overs = [], []
        near_hi = (t >= SHORT[0]) & (t <= SHORT[1])
        near_lo = (t >= -SHORT[1]) & (t <= -SHORT[0])
        inner_hi = (t >= 0) & (t < SHORT[0])
        inner_lo = (t <= 0) & (t > -SHORT[0])
        for row in q:
            wd = _width(t, row)
            if np.isfinite(wd):
                widths.append(wd)
            o_hi = row[inner_hi].max() - row[near_hi].mean()
            o_lo = row[near_lo].mean() - row[inner_lo].min()
            overs.append(max(0.0, (o_hi + o_lo) / 2.0))
        if widths:
            out["sharp.width"] = float(np.median(widths))
        out["sharp.overshoot"] = float(np.median(overs))
    t, p = _profiles(g, e, LONG[1], unit, idx)
    ok, q = _steps(t, p, LONG)
    hi = _steps.hi
    core = e["sigma"][idx][ok]
    keep = core <= CORE_MOST
    for prefix, group in (("diffusion", keep & (hi <= DIFFUSION_TOP)), ("glow.edge", keep & (hi >= BRIGHT_EDGE))):
        shares, radii = _veil(t, q[group], core[group])
        if prefix == "diffusion":
            out["profile.long"] = float(group.sum())
            if len(shares) >= 10:
                out["diffusion.share"] = float(np.median(shares))
            if radii:
                out["diffusion.radius"] = float(np.median(radii))
        else:
            if len(shares) >= 5:
                out["glow.edge_share"] = float(np.median(shares))
            if radii:
                out["glow.edge_radius"] = float(np.median(radii))
    return out


def _veil(t, q, core):
    """per step (normalised profile q, core blur): the share of the step not reached within INNER of its middle, less
    what the core's own blur leaves there, and how far out the rest reaches its half"""
    shares, radii = [], []
    for row, c in zip(q, core):
        mid = _middle(t, row)
        if not np.isfinite(mid) or abs(mid) > INNER:
            continue                                        # its middle is not near the edge found
        q_hi, q_lo = float(np.interp(mid + INNER, t, row)), float(np.interp(mid - INNER, t, row))
        share = math.erf(INNER / (max(c, 1e-3) * math.sqrt(2.0))) - (q_hi - q_lo)
        shares.append(share)
        if share >= 0.05:
            r_hi = _cross(t, row, q_hi + 0.5 * (1.0 - q_hi), mid + INNER, +1)
            r_lo = _cross(t, row, 0.5 * q_lo, mid - INNER, -1)
            vals = [v for v in (r_hi - mid, mid - r_lo) if np.isfinite(v)]
            if vals:
                radii.append(float(np.mean(vals)))
    return shares, radii


MOVING_LEAST = 3.0                # 720 line pixels a frame: an edge moving across itself at least this is read for
STILL_MOST = 0.5                  # motion blur, against edges moving less than this; a pixel moving at least
MOVING_PIXEL = 1.0                # this counts as moving
MOTION_LEAST = 0.008              # Y' per pixel: the weakest moving edge read for motion blur (a 0.3 step blurred over
                                  # 30 px still shows)


def flow(gray0, gray1):
    """the optical flow from one Y' frame to the next (Farneback), pixels a frame: H x W x 2 (x, y)"""
    cv2 = _cv2()
    a = np.clip(np.asarray(gray0) * 255.0, 0, 255).astype(np.uint8)
    b = np.clip(np.asarray(gray1) * 255.0, 0, 255).astype(np.uint8)
    return cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 5, 21, 4, 7, 1.5, 0)


_BOX = {}


def _sigma_1d(profile, s0):
    """the blur edges() reads with the re-blur s0 on a 1-D step profile (the same steps: the central difference, the
    local top over 3, the re-blur, the Sobel width taken out), at the profile's steepest point"""
    ndi = _ndi()

    def grad(p):
        g = np.zeros_like(p)
        g[1:-1] = np.abs(p[2:] - p[:-2]) / 2.0
        return ndi.maximum_filter1d(g, 3)

    m0 = grad(profile)
    i = int(np.argmax(ndi.gaussian_filter1d(m0, 0.7)))
    m1 = grad(ndi.gaussian_filter1d(profile, s0, mode="nearest"))
    r = m0[i] / max(m1[i], 1e-12)
    return math.sqrt(max(s0 * s0 / max(r * r - 1.0, 1e-9) - SOBEL_VAR, 0.0))


def box_length(sigma, scale):
    """the length (pixels) of the box blur (a shutter open while the edge moves) that edges() reads as the blur sigma
    (pixels) with the re-blur scale: edges() reads a Gaussian's sigma well, but a box of length L as about 1.5 to 2
    times L / sqrt(12); this is the inverse of what each re-blur reads on steps blurred by boxes of 0 to 60 pixels
    (made once, the pixel's own width included)"""
    if "tables" not in _BOX:
        x = np.arange(-160.0, 160.0, 1.0)
        lengths = np.arange(0.0, 60.5, 0.5)
        tables = {}
        for s0 in REBLUR:
            reads = []
            for L in lengths:
                lo = 0.3 - L / 2.0
                # the box-blurred step as the pixels see it (each pixel the mean over its own width)
                prof = (np.clip((x + 0.5 - lo) / max(L, 1e-9), 0.0, 1.0) + np.clip((x - 0.5 - lo) / max(L, 1e-9), 0.0, 1.0)) / 2.0                     if L > 0 else (x >= 0.3).astype(np.float64)
                reads.append(_sigma_1d(prof, s0))
            tables[s0] = (np.maximum.accumulate(np.array(reads)), lengths)
        _BOX["tables"] = tables
    sigma = np.asarray(sigma, np.float64)
    scale = np.broadcast_to(np.asarray(scale, np.float64), sigma.shape)
    out = np.zeros(sigma.shape)
    for s0, (reads, lengths) in _BOX["tables"].items():
        sel = scale == s0
        if np.any(sel):
            out[sel] = np.interp(sigma[sel], reads, lengths)
    return out


def motion(gray0, gray1, e, unit=1.0, f=None, seed=0, detail=None):
    """motion and motion blur between two frames (the second the next different picture)

    motion.speed: the median speed of the moving edges (720 line pixels a frame); motion.moving: the share of pixels
    moving at least MOVING_PIXEL; motion.shutter: how long the shutter was open as a share of the frame time: the
    blur of each edge moving across itself (edges(), turned into the length of a box blur by box_length, less the
    still edges' own) over how far it moved across itself in the frame (0 without motion blur, 0.5 for a 180 degree
    shutter); motion.shutter_p75: its upper quartile; motion.blurred_share: the share of the moving edges blurred over
    at least a quarter of their motion (in an MMD render folded from many subframes with the physics held to one step,
    the hair and the skirt stay sharp while the body blurs: the median reads the sharp ones); motion.edges: how many
    moving edges it is read from.  f: the flow if already made; detail, a dict, gets each moving edge and its reading
    (for annotate)."""
    if f is None:
        f = flow(gray0, gray1)
    speed = np.hypot(f[..., 0], f[..., 1]) / unit
    out = {"motion.speed": float("nan"), "motion.moving": float((speed >= MOVING_PIXEL).mean()),
           "motion.shutter": float("nan"), "motion.shutter_p75": float("nan"), "motion.blurred_share": float("nan"),
           "motion.edges": 0.0}
    n = len(e["y"])
    if n == 0:
        return out
    # the moving edges are read again with a low threshold where the picture moves (a long blur leaves weak edges
    # that the frame's own edges miss), the still ones are the frame's own
    weak = edges(gray0, unit, seed=seed, least=MOTION_LEAST, mask=speed >= MOVING_LEAST)
    still_e = e
    e = weak
    if len(e["y"]) == 0:
        return out
    fx, fy = f[e["y"], e["x"], 0], f[e["y"], e["x"], 1]
    across = np.abs(fx * e["nx"] + fy * e["ny"]) / unit
    sp = np.hypot(fx, fy) / unit
    moving = np.nonzero((across >= MOVING_LEAST) & (np.abs(fx * e["nx"] + fy * e["ny"]) >= 0.7 * np.hypot(fx, fy)))[0]
    sfx, sfy = f[still_e["y"], still_e["x"], 0], f[still_e["y"], still_e["x"], 1]
    still = np.nonzero(np.hypot(sfx, sfy) / unit < STILL_MOST)[0]
    if len(moving):
        out["motion.speed"] = float(np.median(sp[moving]))
    out["motion.edges"] = float(len(moving))
    if len(moving) < 10:
        return out
    sig_img = e["sigma"] * unit
    base = float(np.median(box_length(still_e["sigma"][still] * unit, still_e["scale"][still]))) if len(still) >= 10 else 0.0
    lengths = np.sqrt(np.clip(box_length(sig_img[moving], e["scale"][moving]) ** 2 - base ** 2, 0.0, None))
    ratio = lengths / (across[moving] * unit)
    out["motion.shutter"] = float(np.median(ratio))
    out["motion.shutter_p75"] = float(np.percentile(ratio, 75))
    out["motion.blurred_share"] = float((ratio >= 0.25).mean())
    if detail is not None:
        detail.update({"y": e["y"][moving], "x": e["x"][moving], "ratio": ratio, "across": across[moving]})
    return out


CA_SCALES = np.linspace(-0.012, 0.012, 25)     # the radial scales of red and blue against green searched


def aberration(rgb, unit=1.0):
    """colour fringes: how red and blue lie against green, read from the channels' gradients

    ca.red_x / red_y, ca.blue_x / blue_y: the shift of the whole channel (phase correlation; 720 line pixels, + right
    and + down); ca.red_radial / blue_radial: after that, the channel's scale about the centre as the move it makes at
    the corner of a 720 line picture (720 line pixels; + outward), as a lens's lateral colour does."""
    cv2 = _cv2()
    img = np.asarray(rgb, np.float64)
    h, w = img.shape[:2]
    grads = [np.float32(_gradient(img[..., c])[2]) for c in range(3)]
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    out = {}
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    r = np.hypot((yy - cy) / (h / 2.0), (xx - cx) / (w / 2.0))
    outer = (r >= 0.45) & (r <= 1.2)
    corner = math.hypot(w / 2.0, h / 2.0) / unit
    for name, c in (("red", 0), ("blue", 2)):
        (dx, dy), _ = cv2.phaseCorrelate(grads[1], grads[c], win)
        out["ca.%s_x" % name] = float(dx / unit)
        out["ca.%s_y" % name] = float(dy / unit)
        best = []
        for s in CA_SCALES:
            mx = np.float32(cx + (xx - cx) * (1.0 + s) + dx)
            my = np.float32(cy + (yy - cy) * (1.0 + s) + dy)
            back = cv2.remap(grads[c], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            a, b = grads[1][outer], back[outer]
            a, b = a - a.mean(), b - b.mean()
            best.append(float((a * b).sum() / max(math.sqrt((a * a).sum() * (b * b).sum()), 1e-12)))
        k = int(np.argmax(best))
        s = CA_SCALES[k]
        if 0 < k < len(best) - 1:
            y0, y1, y2 = best[k - 1], best[k], best[k + 1]
            den = y0 - 2 * y1 + y2
            if den < 0:
                s = s + 0.5 * (y0 - y2) / den * (CA_SCALES[1] - CA_SCALES[0])
        out["ca.%s_radial" % name] = float(s * corner)
    return out


LINE_LEAST = 0.2                  # distortion: segments at least this long (of the picture's height), and at least
LINE_OFF_CENTRE = 0.2             # this far from the centre (of the half diagonal), are read for their bend


K1_SEARCH = np.linspace(-0.4, 0.4, 161)


def _undistort(px, py, k1):
    """points seen through r_d = r_u (1 + k1 r_u^2) put back where a straight lens would show them"""
    rd = np.hypot(px, py)
    ru = rd.copy()
    for _ in range(8):
        ru = rd / (1.0 + k1 * ru * ru)
    scale = np.where(rd > 0, ru / np.maximum(rd, 1e-12), 1.0)
    return px * scale, py * scale


def _distort(px, py, k1):
    r2 = px * px + py * py
    return px * (1.0 + k1 * r2), py * (1.0 + k1 * r2)


def _reprojection(px, py, groups, k1):
    """the squared distance (in the frame) of the edge points from straight lines put through them where a lens
    without distortion would have shown them: the lines fitted there, the points' feet on them seen through k1 again"""
    ux, uy = _undistort(px, py, k1)
    total = 0.0
    for idx in groups:
        pts = np.stack([ux[idx], uy[idx]], axis=1)
        c = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
        d = vt[0]
        foot = c + ((pts - c) @ d)[:, None] * d[None, :]
        fx, fy = _distort(foot[:, 0], foot[:, 1], k1)
        total += float(((fx - px[idx]) ** 2 + (fy - py[idx]) ** 2).sum())
    return total


def distortion(gray, unit=1.0):
    """the bend of straight lines (the plumb-line way): long straight segments (Hough) and the edge points along each
    (those whose own normal lies along the segment's, each side of a line apart, placed to a part of a pixel), then
    the k1 of r_d = r_u (1 + k1 r_u^2) (r over the half diagonal) under which straight lines fit them best, the fit
    measured in the frame (where they were seen): distortion.k1 (negative for barrel, the middle of a line bowed
    away from the centre; positive for pincushion), distortion.segments (how many were read)"""
    cv2, ndi = _cv2(), _ndi()
    g = np.asarray(gray, np.float64)
    h, w = g.shape
    u8 = np.clip(ndi.gaussian_filter(g, 0.7) * 255.0, 0, 255).astype(np.uint8)
    canny = cv2.Canny(u8, 40, 100, L2gradient=True)
    segs = cv2.HoughLinesP(canny, 1, math.pi / 720.0, threshold=int(0.15 * h), minLineLength=int(LINE_LEAST * h),
                           maxLineGap=int(0.02 * h) + 2)
    out = {"distortion.k1": float("nan"), "distortion.segments": 0.0}
    if segs is None:
        return out
    ys, xs = np.nonzero(canny)
    sx, sy, smag = _gradient(ndi.gaussian_filter(g, 1.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        gnx, gny = sx[ys, xs] / smag[ys, xs], sy[ys, xs] / smag[ys, xs]
    ok = np.isfinite(gnx) & np.isfinite(gny)
    ys, xs, gnx, gny = ys[ok], xs[ok], gnx[ok], gny[ok]
    # each edge point moved along its normal to the top of a parabola through the gradient there (sub-pixel)
    m = [ndi.map_coordinates(smag, [ys + k * gny, xs + k * gnx], order=1, mode="nearest") for k in (-1.0, 0.0, 1.0)]
    den = m[0] - 2.0 * m[1] + m[2]
    with np.errstate(invalid="ignore", divide="ignore"):
        step = np.where(den < 0, np.clip(0.5 * (m[0] - m[2]) / den, -1.0, 1.0), 0.0)
    fy_, fx_ = ys + step * gny, xs + step * gnx
    half = math.hypot(w / 2.0, h / 2.0)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    py, px = (fy_ - cy) / half, (fx_ - cx) / half
    groups = []
    for x1, y1, x2, y2 in segs[:, 0, :]:
        a = np.array([(x1 - cx) / half, (y1 - cy) / half])
        b = np.array([(x2 - cx) / half, (y2 - cy) / half])
        length = float(np.hypot(*(b - a)))
        if length <= 0:
            continue
        tdir = (b - a) / length
        nrm = np.array([-tdir[1], tdir[0]])
        mid = (a + b) / 2.0
        if abs(float(mid @ nrm)) < LINE_OFF_CENTRE:
            continue                                            # a line through the middle does not bend
        rel = np.stack([px - mid[0], py - mid[1]], axis=1)
        along, across = rel @ tdir, rel @ nrm
        band = (np.abs(along) <= length / 2.0) & (np.abs(across) <= 4.0 / half)
        facing = gnx * nrm[0] + gny * nrm[1]
        for side in (facing >= 0.9, facing <= -0.9):    # each side of a line apart (a line's width is no bend)
            idx = np.nonzero(band & side)[0]
            if len(idx) >= 0.6 * length * half:
                groups.append(idx)
    out["distortion.segments"] = float(len(groups))
    if len(groups) < 3:
        return out
    costs = [_reprojection(px, py, groups, k1) for k1 in K1_SEARCH]
    k = int(np.argmin(costs))
    k1 = float(K1_SEARCH[k])
    if 0 < k < len(costs) - 1:
        y0, y1, y2 = costs[k - 1], costs[k], costs[k + 1]
        den = y0 - 2 * y1 + y2
        if den > 0:
            k1 += 0.5 * (y0 - y2) / den * float(K1_SEARCH[1] - K1_SEARCH[0])
    out["distortion.k1"] = k1
    return out


# ---- the measures: names, ideas, labels -----------------------------------------------------------------------------

CONCEPTS = ("tone", "colour", "light", "optics", "texture", "frame")
CONCEPT_LABELS = {"tone": "色調（明るさ）", "colour": "色調（色）", "light": "光", "optics": "光学", "texture": "質感",
                  "frame": "画面"}
MEASURES = {
    "tone.black": ("tone", "黒の位置（L* の 1 % 点）", "L*"),
    "tone.p5": ("tone", "暗い側（L* の 5 % 点）", "L*"),
    "tone.median": ("tone", "明るさの中央（画面全体の L* の中央値。人物が小さいと舞台の明るさを読む）", "L*"),
    "tone.p95": ("tone", "明るい側（L* の 95 % 点）", "L*"),
    "tone.white": ("tone", "白の位置（L* の 99 % 点）", "L*"),
    "tone.key": ("tone", "明暗の寄り（中央値が 5〜95 % 点のどこか。0.5 が真ん中、小さいほど暗い側）", ""),
    "tone.contrast": ("tone", "コントラスト（L* の標準偏差）", "L*"),
    "tone.local": ("tone", "細かいコントラスト（L* と 10 px ぼかしの差の平均）", "L*"),
    "tone.shadows": ("tone", "暗部の割合（L* 25 未満）", ""),
    "tone.highlights": ("tone", "明部の割合（L* 75 超）", ""),
    "tone.clip_white": ("tone", "白飛び（どれかの色が 253 以上の画素の割合）", ""),
    "tone.clip_black": ("tone", "黒つぶれ（全色 2 以下の画素の割合）", ""),
    "colour.chroma": ("colour", "彩度（C*ab の平均）", "C*"),
    "colour.chroma_p90": ("colour", "彩度の高い側（C*ab の 90 % 点）", "C*"),
    "colour.colourfulness": ("colour", "色の豊かさ（Hasler と Suesstrunk の M）", ""),
    "colour.cast_hue": ("colour", "画面全体の色かぶりの色相（a*b* の平均の角度）", "度"),
    "colour.cast_chroma": ("colour", "画面全体の色かぶりの強さ（a*b* の平均の大きさ）", "C*"),
    "split.shadow_hue": ("colour", "影（L* 8〜35）の色かぶりの色相", "度"),
    "split.shadow_chroma": ("colour", "影の色かぶりの強さ", "C*"),
    "split.mid_hue": ("colour", "中間（L* 35〜65）の色かぶりの色相", "度"),
    "split.mid_chroma": ("colour", "中間の色かぶりの強さ", "C*"),
    "split.high_hue": ("colour", "光（L* 65〜95）の色かぶりの色相", "度"),
    "split.high_chroma": ("colour", "光の色かぶりの強さ", "C*"),
    "split.teal_orange": ("colour", "ティールとオレンジの開き（画面全体の L* 65〜95 が 8〜35 よりオレンジ寄り。暗い舞台と明るい人物では舞台と人物の色の差を読む）", "C*"),
    "wb.cct": ("colour", "白の色温度（白に近い画素の平均、McCamy）", "K"),
    "wb.white_a": ("colour", "白の a*（+ 赤み・- 緑み）", ""),
    "wb.white_b": ("colour", "白の b*（+ 黄み・- 青み）", ""),
    "wb.share": ("colour", "白に近い画素の割合", ""),
    "bloom.strength": ("light", "グローの強さ（明るい所から 4 px 先に残る光の割合。白い服のように広く明るい所ではその服の明るさも読む）", ""),
    "bloom.r50": ("light", "グローの届き（半分に落ちる距離）", "px"),
    "bloom.r10": ("light", "グローの裾（1 割に落ちる距離）", "px"),
    "bloom.halo_red": ("light", "にじみの赤み（光源より赤い割合。フィルムのハレーションで +）", ""),
    "bloom.halo_blue": ("light", "にじみの青み", ""),
    "bloom.sources": ("light", "明るい所（Y' 0.9 以上）の割合", ""),
    "glow_small.strength": ("light", "小さい光（点の光源）のグローの強さ", ""),
    "glow_small.r50": ("light", "小さい光のグローの届き", "px"),
    "glow_small.r10": ("light", "小さい光のグローの裾", "px"),
    "glow_small.halo_red": ("light", "小さい光のにじみの赤み", ""),
    "streak.strength": ("light", "光芒の強さ（小さい光のまわりの光の角度の偏り。丸いグローは 0）", ""),
    "streak.rays": ("light", "光芒の本数（2 は横一文字、4 は十字）", "本"),
    "streak.angle": ("light", "光芒の向き（右から反時計回り）", "度"),
    "light.key_hue": ("light", "いちばん明るい 2 % の色相（光の色の目安）", "度"),
    "light.key_chroma": ("light", "いちばん明るい 2 % の色の強さ", "C*"),
    "light.lr": ("light", "右が左より明るい割合（光の向きの目安）", ""),
    "light.tb": ("light", "上が下より明るい割合", ""),
    "beam.count": ("light", "光の筋（ボリュームライト）の本数（1 コマ）", "本"),
    "beam.share": ("light", "光の筋の面積の割合", ""),
    "beam.length": ("light", "光の筋の長さ（絵の高さの割合）", ""),
    "beam.angle": ("light", "光の筋の向き（縦からの角度）", "度"),
    "spot.count": ("light", "光だまり（スポット）の数（1 コマ）", "個"),
    "spot.share": ("light", "光だまりの面積の割合", ""),
    "light.colours": ("light", "明るい所の色の数（1 コマ、色相の山）", "色"),
    "light.spread": ("light", "明るい所の色相の広がり（円の標準偏差）", "度"),
    "lightcol.palette": ("light", "主光の色の数（動画全体、30 度ごと）", "色"),
    "lightcol.colourful": ("light", "主光に色が付いているコマの割合（C* 20 超）", ""),
    "lightcol.changes_per_min": ("light", "主光の色の変わり（カットごと、1 分あたり）", "回"),
    "flicker.hf": ("light", "明るさのちらつき（0.25 秒の平均からの差の rms）", "Y'"),
    "strobe.per_min": ("light", "ストロボ（0.35 秒以内に 3 回以上のフラッシュ、1 分あたり）", "回"),
    "lightmove.speed": ("light", "いちばん明るい所の動く速さ（カットを除く）", "px/秒"),
    "flash.per_min": ("light", "フラッシュの回数（1 分あたり）", "回"),
    "flash.peak": ("light", "フラッシュの強さ（Y' の上がり）", ""),
    "flash.len_s": ("light", "フラッシュの長さ", "秒"),
    "dof.sharp": ("optics", "いちばん鋭い縁のぼけ（縁のぼけの 10 % 点）", "px"),
    "dof.median": ("optics", "縁のぼけの中央", "px"),
    "dof.soft": ("optics", "柔らかい縁のぼけ（90 % 点。被写界深度の外のぼけ）", "px"),
    "dof.soft_share": ("optics", "ぼけた縁（3 px 超）の割合（被写界深度）", ""),
    "dof.fg_blur": ("optics", "鋭い側の区画のぼけ（区画の 25 % 点。ピントの合った所）", "px"),
    "dof.bg_blur": ("optics", "柔らかい側の区画のぼけ（75 % 点。背景）", "px"),
    "dof.ratio": ("optics", "人物と背景の鮮鋭さの比（(背景 + 1) / (ピント + 1)）", ""),
    "dof.soft_blocks": ("optics", "ぼけた区画（3 px 超）の割合", ""),
    "motion.shutter": ("optics", "シャッター（動く縁の伸びから。0.5 が 180 度）", ""),
    "motion.shutter_p75": ("optics", "シャッターの上側（動く縁の 75 % 点）", ""),
    "motion.blurred_share": ("optics", "動きの 1/4 以上ぼけた動く縁の割合", ""),
    "motion.speed": ("optics", "動く縁の速さ", "px/コマ"),
    "motion.moving": ("optics", "動く画素の割合", ""),
    "ca.red_x": ("optics", "赤のずれ（横、+ 右）", "px"),
    "ca.red_y": ("optics", "赤のずれ（縦、+ 下）", "px"),
    "ca.blue_x": ("optics", "青のずれ（横）", "px"),
    "ca.blue_y": ("optics", "青のずれ（縦）", "px"),
    "ca.red_radial": ("optics", "赤の倍率の色収差（隅での外向きのずれ）", "px"),
    "ca.blue_radial": ("optics", "青の倍率の色収差（隅での外向きのずれ）", "px"),
    "vignette.corner": ("optics", "周辺減光（隅の明るさ / 中央の明るさ、全コマの平均。中央の明るい人物と暗い舞台も読む）", ""),
    "vignette.corner_p10": ("optics", "周辺減光（各所の 10 % 点で）", ""),
    "vignette.corner_p95": ("optics", "周辺減光（各所の 95 % 点で。動くカメラで明るい物が隅を通るとき）", ""),
    "distortion.k1": ("optics", "レンズの歪み k1（- たる型、+ 糸巻き型）", ""),
    "distortion.segments": ("optics", "歪みを読んだ直線の数", "本"),
    "noise.spatial": ("texture", "平らな所のノイズ（Immerkaer）", "/255"),
    "grain.temporal": ("texture", "コマごとに変わる粒（フィルムグレイン）の強さ", "/255"),
    "grain.size": ("texture", "粒の大きさ（自己相関が半分になる距離）", "px"),
    "sharp.width": ("texture", "縁の幅（段の 10〜90 %）", "px"),
    "sharp.overshoot": ("texture", "シャープの縁取り（縁の脇の行き過ぎ、段の割合）", ""),
    "diffusion.share": ("texture", "ディフュージョン（鋭い縁のまわりの柔らかいにじみの割合）", ""),
    "diffusion.radius": ("texture", "ディフュージョンの広がり", "px"),
    "glow.edge_share": ("light", "明るい縁のまわりのにじみの割合（明るい所のグローの裾）", ""),
    "glow.edge_radius": ("light", "明るい縁のにじみの広がり", "px"),
    "scan.peak": ("texture", "スキャンライン（行の周期の強さ。線なしで数）", ""),
    "glitch.tears": ("texture", "行の裂け（グリッチ）の数", "行"),
    "text.frames": ("frame", "文字の入るコマの割合（EasyOCR の文字の検出）", ""),
    "text.area": ("frame", "文字の覆う面積の割合", ""),
    "text.height": ("frame", "文字の高さ（箱の高さの中央）", "px"),
    "text.top": ("frame", "上の 1/3 にある文字の割合", ""),
    "text.bottom": ("frame", "下の 1/3 にある文字の割合", ""),
    "text.corner": ("frame", "隅にある文字の割合（透かし・名のり）", ""),
    "frame.aspect": ("frame", "絵の縦横比（黒帯の内側）", ""),
    "frame.bars_tb": ("frame", "上下の黒帯（合計）", "px"),
    "frame.bars_lr": ("frame", "左右の黒帯（合計）", "px"),
    "frame.fps": ("frame", "fps（入れ物）", ""),
    "frame.fps_effective": ("frame", "実際に絵が変わる fps", ""),
    "cuts.per_min": ("frame", "カット（1 分あたり）", "回"),
    "shots.median_s": ("frame", "1 カットの長さの中央", "秒"),
}
# read once from the whole video, not from each frame
VIDEO_LEVEL = {"lightcol.palette", "lightcol.colourful", "lightcol.changes_per_min", "flicker.hf", "strobe.per_min",
               "lightmove.speed",
               "flash.per_min", "flash.peak", "flash.len_s", "vignette.corner", "vignette.corner_p10",
               "vignette.corner_p95", "text.frames", "text.area", "text.height", "text.top", "text.bottom", "text.corner",
               "frame.aspect",
               "frame.bars_tb", "frame.bars_lr", "frame.fps", "frame.fps_effective", "cuts.per_min", "shots.median_s"}
PAIR_ONLY = ("motion.", "grain.")             # need the next picture
FULL_ONLY = ("ca.", "distortion.")            # read on every full_every-th pair only (slower)


def measure_frame(rgb0, rgb1=None, unit=1.0, full=True, seed=0, extras=None):
    """every measure of one frame (rgb0, 0..1) that one frame can give, and those that need the next different
    picture (rgb1: motion and grain); full: also the slower ones (colour fringes, distortion).  extras, a dict, gets
    the glow's profile and the edges' blur for the figures."""
    rgb0 = np.asarray(rgb0, np.float64)
    lab = rgb_to_lab(rgb0)
    g0 = luma(rgb0)
    m = {}
    m.update(tone(rgb0, lab, unit))
    m.update(colour(rgb0, lab))
    m.update(white_balance(rgb0, lab))
    b = bloom(rgb0, unit)
    m.update({k: v for k, v in b.items() if k != "profile"})
    small = bloom(rgb0, unit, compact=True)
    m.update({k.replace("bloom.", "glow_small."): v for k, v in small.items() if k != "profile"})
    m.update(streaks(rgb0, unit))
    m.update(light(rgb0, lab))
    m.update(beams(rgb0, unit))
    m.update(light_colours(rgb0, lab))
    e = edges(g0, unit, seed=seed)
    m.update(depth_of_field(e))
    m.update(dof_blocks(g0, unit))
    m.update(edge_profiles(g0, e, unit, seed=seed))
    m.update(noise_spatial(g0))
    m.update(scanlines(g0))
    m.update(glitch(g0))
    pair_keys = [k for k in MEASURES if k.startswith(PAIR_ONLY)] + ["motion.edges"]
    if rgb1 is not None:
        g1 = luma(np.asarray(rgb1, np.float64))
        f = flow(g0, g1)
        m.update(motion(g0, g1, e, unit, f=f, seed=seed))
        m.update(grain(g0, g1, unit, still=np.hypot(f[..., 0], f[..., 1]) / unit < 0.3))
    else:
        m.update({k: float("nan") for k in pair_keys})
    full_keys = [k for k in MEASURES if k.startswith(FULL_ONLY)]
    if full:
        m.update(aberration(rgb0, unit))
        m.update(distortion(g0, unit))
    else:
        m.update({k: float("nan") for k in full_keys})
    if extras is not None:
        grid = np.arange(1.0, BLOOM_REACH + 1.0)
        if b["profile"]:
            d, v = np.array(b["profile"]).T
            extras["bloom_profile"] = np.interp(grid, d, v, left=np.nan, right=np.nan).tolist()
        extras["tone_hist"] = np.histogram(lab[..., 0], bins=50, range=(0.0, 100.0))[0].tolist()
        extras["sigma_hist"] = np.histogram(e["sigma"], bins=40, range=(0.0, 20.0))[0].tolist()
    return {k: float(v) for k, v in m.items()}


# ---- the person and the stage apart -----------------------------------------------------------------------------------
#
# The measures above read the whole frame.  A small bright person on a dark stage (our front view: the person is 3 to
# 7 % of the frame) and a close-up in a bright set (the references: often half the frame) differ in what the frame
# holds before any filter: the whole frame's tone is mostly the stage's, its "split toning" is the stage's colour against
# the person's, its "vignette" is where the stage is dark.  These read the person (its mask: an anime person model, or
# a layer) and the stage apart.

PERSON_INNER = 3.0                # 720 line px: the person is read this far inside its outline (the edge mixes with
STAGE_GAP = 12.0                  # the stage), the stage this far outside it (the person's glow, the mask's error)
REGION_LEAST = 0.005              # a region under this share of the frame is not read
RIM_EDGE = (3.0, 6.0)             # 720 line px inside the outline: the edge's light, past an outline of 1 to 2 px,
RIM_CORE = (12.0, 20.0)           # against the light further in along the same normal
HALO_EDGE = (1.0, 4.0)            # 720 line px inside the outline: the person's own light at its edge, the source of
HALO_NEAR = (3.0, 8.0)            # the glow it throws on the stage just outside,
HALO_FAR = (24.0, 40.0)           # against the stage further out
HALO_LEAST = 0.05                 # linear luminance: the edge brighter than the far stage by at least this
OUTLINE_POINTS = 3000             # outline points read per frame at most
EDGE_IN = (3.0, 6.0)              # 720 line px inside the outline: the person's colour at her edge (the rim's band) ...
EDGE_OUT = (12.0, 20.0)           # ... against the stage's just outside it, past her glow and the mask's error
MERGE_DE = 15.0                   # CIE76 dE*ab: an edge whose two sides differ by less does not stand out (stagecity)
SEG_SIZE = 1024                   # the person model's input (square, the frame letterboxed into it)
FACE_CHEEK = ((0.55, 0.85), (0.25, 0.75))   # rows and columns of a face's box read for the light on her skin: the cheeks
#                                   (typorev: the references' person read 44.6 L* against ours 76 for their dark costumes;
#                                   their faces 78 against ours 80)
FACE_LEAST = 20                   # pixels of the cheeks on the person at least, for a face to be read

REGION_CONCEPTS = ("frame", "person", "stage", "edge")
REGION_CONCEPT_LABELS = {"frame": "構図", "person": "人物", "stage": "舞台（人物の外）", "edge": "人物の縁"}
REGION_MEASURES = {
    "frame.person_share": ("frame", "人物の面積の割合（構図）", ""),
    "contrast.person_stage": ("frame", "人物と舞台の明るさの差（L* の中央の差）", "L*"),
    "person.L_p10": ("person", "人物の暗い側（L* の 10 % 点）", "L*"),
    "person.L_p50": ("person", "人物の明るさの中央（L*）", "L*"),
    "person.L_p90": ("person", "人物の明るい側（L* の 90 % 点）", "L*"),
    "person.chroma": ("person", "人物の彩度（C*ab の平均）", "C*"),
    "person.cast_hue": ("person", "人物の色かぶりの色相", "度"),
    "person.cast_chroma": ("person", "人物の色かぶりの強さ", "C*"),
    "person.teal_orange": ("person", "人物の中の影と光の色の開き（人物の明るい 1/4 が暗い 1/4 よりオレンジ寄り）", "C*"),
    "stage.L_p10": ("stage", "舞台の暗い側（L* の 10 % 点）", "L*"),
    "stage.L_p50": ("stage", "舞台の明るさの中央（L*）", "L*"),
    "stage.L_p90": ("stage", "舞台の明るい側（L* の 90 % 点）", "L*"),
    "stage.chroma": ("stage", "舞台の彩度（C*ab の平均）", "C*"),
    "stage.cast_hue": ("stage", "舞台の色かぶりの色相", "度"),
    "stage.cast_chroma": ("stage", "舞台の色かぶりの強さ", "C*"),
    "stage.teal_orange": ("stage", "舞台の中の影と光の色の開き", "C*"),
    "person.key_hue": ("person", "人物に当たる光の色相（人物の明るい 1 割の a*b*）", "度"),
    "person.key_chroma": ("person", "人物に当たる光の色の強さ", "C*"),
    "face.L": ("person", "顔の肌の明るさ（頬の L* の中央。衣装の色に左右されない人物の明るさ、regions --faces で）", "L*"),
    "face.chroma": ("person", "顔の肌の彩度（頬の C*ab）", "C*"),
    "face.hue": ("person", "顔の肌の色相（頬の a*b*）", "度"),
    "stage.key_hue": ("stage", "舞台の光の色相（舞台の明るい 1 割の a*b*）", "度"),
    "stage.key_chroma": ("stage", "舞台の光の色の強さ", "C*"),
    "dof.person_blur": ("stage", "人物の区画のぼけ（中央）", "px"),
    "dof.stage_blur": ("stage", "舞台の区画のぼけ（中央）", "px"),
    "dof.stage_ratio": ("stage", "舞台と人物の鮮鋭さの比（(舞台 + 1) / (人物 + 1)）", ""),
    "stage.lights": ("stage", "舞台の光源の割合（舞台のうち Y' 0.9 以上）", ""),
    "bloom.stage_strength": ("stage", "舞台の光のグローの強さ（人物の外の光源、4 px 先）", ""),
    "bloom.stage_r50": ("stage", "舞台の光のグローの届き", "px"),
    "rim.ratio": ("edge", "縁の明るさ / 内側の明るさ（縁の 3〜6 px と 12〜20 px、中央。リムライトで 1 より大）", ""),
    "rim.p90": ("edge", "縁の明るさ / 内側の明るさの 90 % 点（強い縁の光）", ""),
    "halo.share": ("edge", "人物のまわりのにじみ（外 3〜8 px の光の上がり / 縁の光、中央）", ""),
    "halo.dL": ("edge", "人物のまわりのにじみの見え方（外 3〜8 px と 24〜40 px の L* の差。暗い舞台ほど同じ光で大きい）", "L*"),
    "bloom.person_strength": ("edge", "人物の光源が人物の外に落とすグローの強さ（4 px 先）", ""),
    "bloom.person_r50": ("edge", "人物のグローの届き", "px"),
    "edge.dE": ("edge", "縁の内（3〜6 px）と外（12〜20 px）の色の差 ΔE*ab の中央（小さいほど人物が後ろの舞台に紛れる）", "ΔE"),
    "edge.merge": ("edge", "縁の内と外の色の差が 15 未満の点の割合（人物の縁が後ろの舞台と同じ色で見えにくい所）", ""),
}


def _region_stats(L, a, b, sel, prefix, out):
    """tone and colour of the pixels sel: the 10 / 50 / 90 % points of L*, the mean C*ab, the cast, how much more
    orange its brightest quarter is than its darkest (split toning inside the region), and the colour of its
    brightest tenth (the light on it)"""
    Ls = L[sel]
    p10, p50, p90 = (float(v) for v in np.percentile(Ls, [10, 50, 90]))
    aa, bb = a[sel], b[sel]
    lo, hi = np.percentile(Ls, [25, 75])
    dark, bright = Ls <= lo, Ls >= hi

    def along(s):
        return float(aa[s].mean() * ORANGE[0] + bb[s].mean() * ORANGE[1])

    key = Ls >= np.percentile(Ls, 90)                            # the light on it: its brightest tenth
    out.update({prefix + ".key_hue": _hue(aa[key].mean(), bb[key].mean()),
                prefix + ".key_chroma": float(math.hypot(aa[key].mean(), bb[key].mean()))})
    out.update({prefix + ".L_p10": p10, prefix + ".L_p50": p50, prefix + ".L_p90": p90,
                prefix + ".chroma": float(np.hypot(aa, bb).mean()), prefix + ".cast_hue": _hue(aa.mean(), bb.mean()),
                prefix + ".cast_chroma": float(math.hypot(aa.mean(), bb.mean())),
                prefix + ".teal_orange": along(bright) - along(dark)})


def _outline(person, unit, seed):
    """points on the person's outline (pixels of the person with a 4-neighbour outside) and the unit normal into the
    person there (from the mask smoothed by 2 px)"""
    ndi = _ndi()
    edge = person & ~ndi.binary_erosion(person)
    ys, xs = np.nonzero(edge)
    if len(ys) > OUTLINE_POINTS:
        pick = np.random.default_rng(seed).choice(len(ys), OUTLINE_POINTS, replace=False)
        ys, xs = ys[pick], xs[pick]
    s = ndi.gaussian_filter(person.astype(np.float64), 2.0 * unit)
    gy, gx = np.gradient(s)
    g = np.hypot(gx[ys, xs], gy[ys, xs])
    ok = g > 1e-6
    return ys[ok], xs[ok], gy[ys, xs][ok] / g[ok], gx[ys, xs][ok] / g[ok]


def _along(img, ys, xs, ny, nx, ts, order=1):
    """img sampled at the points moved by each distance in ts along the normals: (points, distances)"""
    py = ys[:, None] + ny[:, None] * ts[None, :]
    px = xs[:, None] + nx[:, None] * ts[None, :]
    return _ndi().map_coordinates(img, [py.ravel(), px.ravel()], order=order, mode="nearest").reshape(py.shape), py, px


def silhouette(Y, person, unit=1.0, seed=0):
    """the light along the person's outline (Y: linear luminance), read on the normals of its outline points

    rim.ratio / rim.p90: the light RIM_EDGE inside the outline over the light RIM_CORE inside, on normals that stay in
    the person that far (thin parts left out): 1 for an evenly lit person, over 1 with a rim light; the median and the
    90 % point over the points.  halo.share: the light HALO_NEAR outside over the stage HALO_FAR outside, as a share of
    the person's edge (HALO_EDGE inside) over that stage, on normals that stay off the person and in the frame and where
    the edge is brighter than the stage: 0 without a glow round the person, the glow's share at a few px with one;
    halo.dL: the same light as the eye sees it, L* near less L* far (the same glow lifts a dark stage by more L*)."""
    out = {"rim.ratio": float("nan"), "rim.p90": float("nan"), "rim.points": 0.0, "halo.share": float("nan"),
           "halo.dL": float("nan"), "halo.points": 0.0}
    if person.sum() < 50 or (~person).sum() < 50:
        return out
    ys, xs, ny, nx = _outline(person, unit, seed)
    if len(ys) < 10:
        return out
    h, w = person.shape
    pf = person.astype(np.float64)

    def span(lo, hi):
        return np.arange(lo, hi + 0.5, 1.0) * unit

    t_in = span(RIM_EDGE[0], RIM_CORE[1])
    inside, _, _ = _along(pf, ys, xs, ny, nx, t_in, order=0)
    y_in, _, _ = _along(Y, ys, xs, ny, nx, t_in)
    keep = inside.min(axis=1) > 0.5
    e_sel = (t_in >= RIM_EDGE[0] * unit) & (t_in <= RIM_EDGE[1] * unit)
    c_sel = (t_in >= RIM_CORE[0] * unit) & (t_in <= RIM_CORE[1] * unit)
    edge, core = y_in[:, e_sel].mean(axis=1), y_in[:, c_sel].mean(axis=1)
    keep &= core > 1e-4
    if keep.sum() >= 10:
        ratio = edge[keep] / core[keep]
        out.update({"rim.ratio": float(np.median(ratio)), "rim.p90": float(np.percentile(ratio, 90)),
                    "rim.points": float(keep.sum())})
    t_out = span(1.0, HALO_FAR[1])
    off, py, px = _along(pf, ys, xs, -ny, -nx, t_out, order=0)
    y_out, _, _ = _along(Y, ys, xs, -ny, -nx, t_out)
    in_frame = (py.min(axis=1) >= 0) & (px.min(axis=1) >= 0) & (py.max(axis=1) <= h - 1) & (px.max(axis=1) <= w - 1)
    y_edge, _, _ = _along(Y, ys, xs, ny, nx, span(*HALO_EDGE))
    n_sel = (t_out >= HALO_NEAR[0] * unit) & (t_out <= HALO_NEAR[1] * unit)
    f_sel = (t_out >= HALO_FAR[0] * unit) & (t_out <= HALO_FAR[1] * unit)
    near, far, src = y_out[:, n_sel].mean(axis=1), y_out[:, f_sel].mean(axis=1), y_edge.mean(axis=1)
    keep = (off.max(axis=1) < 0.5) & in_frame & (src - far >= HALO_LEAST)
    if keep.sum() >= 10:

        def lstar(y):
            return 116.0 * _f(np.clip(y, 0.0, None)) - 16.0

        out.update({"halo.share": float(np.median((near[keep] - far[keep]) / (src[keep] - far[keep]))),
                    "halo.dL": float(np.median(lstar(near[keep]) - lstar(far[keep]))),
                    "halo.points": float(keep.sum())})
    return out


def edge_contrast(lab, person, unit=1.0, seed=0):
    """how far the person's colour at her outline (EDGE_IN inside) lies from the stage's right behind it (EDGE_OUT
    outside), read on the normals of the outline points that stay in the person and off it that far, in the frame: the
    median CIE76 dE*ab (edge.dE) and the share of the points under MERGE_DE (edge.merge: where her edge does not stand out
    from what lies behind it: a white dress against a white sign)"""
    out = {"edge.dE": float("nan"), "edge.merge": float("nan")}
    if person.sum() < 50 or (~person).sum() < 50:
        return out
    ys, xs, ny, nx = _outline(person, unit, seed)
    if len(ys) < 10:
        return out
    h, w = person.shape
    pf = person.astype(np.float64)
    t_in = np.arange(EDGE_IN[0], EDGE_IN[1] + 0.5, 1.0) * unit
    t_out = np.arange(EDGE_OUT[0], EDGE_OUT[1] + 0.5, 1.0) * unit
    inside, _, _ = _along(pf, ys, xs, ny, nx, t_in, order=0)
    off, py, px = _along(pf, ys, xs, -ny, -nx, t_out, order=0)
    keep = (inside.min(axis=1) > 0.5) & (off.max(axis=1) < 0.5)
    keep &= (py.min(axis=1) >= 0) & (px.min(axis=1) >= 0) & (py.max(axis=1) <= h - 1) & (px.max(axis=1) <= w - 1)
    if keep.sum() < 10:
        return out
    near = np.stack([_along(lab[..., k], ys, xs, ny, nx, t_in)[0].mean(axis=1) for k in range(3)], axis=1)
    far = np.stack([_along(lab[..., k], ys, xs, -ny, -nx, t_out)[0].mean(axis=1) for k in range(3)], axis=1)
    de = np.linalg.norm(near - far, axis=1)[keep]
    out.update({"edge.dE": float(np.median(de)), "edge.merge": float((de < MERGE_DE).mean())})
    return out


def region_measures(rgb, mask, unit=1.0, seed=0, faces=None):
    """the measures of the person (mask >= 0.5) and of the stage (the rest, STAGE_GAP outside the person) of one frame
    (REGION_MEASURES): their tone and colour apart, the light along the person's outline (rim and glow), the blur of
    the stage's blocks against the person's (depth of field), the glow of the stage's lights and of the person's; with
    faces (boxes x, y, w, h found on the frame), the light on her skin: the cheeks (FACE_CHEEK) of the faces whose middle
    lies on the person, their L*, C*ab and hue (the median over the faces; face.count of them)"""
    rgb = np.asarray(rgb, np.float64)
    ndi = _ndi()
    person = np.asarray(mask, np.float64) >= 0.5
    out = {k: float("nan") for k in REGION_MEASURES}
    out.update({"rim.points": 0.0, "halo.points": 0.0, "face.count": 0.0})
    out["frame.person_share"] = float(person.mean())
    lab = rgb_to_lab(rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    least = REGION_LEAST * person.size
    if person.any():
        inner = ndi.distance_transform_edt(person) > PERSON_INNER * unit
        stage = ndi.distance_transform_edt(~person) > STAGE_GAP * unit
    else:
        inner, stage = person, np.ones_like(person)
    if inner.sum() >= least:
        _region_stats(L, a, b, inner, "person", out)
    if stage.sum() >= least:
        _region_stats(L, a, b, stage, "stage", out)
    out["contrast.person_stage"] = out["person.L_p50"] - out["stage.L_p50"]
    cheeks = []
    for (fx, fy, fw, fh) in (faces or ()):
        cy, cx = int(fy + fh // 2), int(fx + fw // 2)
        if not (0 <= cy < person.shape[0] and 0 <= cx < person.shape[1]) or not person[cy, cx]:
            continue                                        # not on her (a face on a sign, another dancer's off her mask)
        y0, y1 = int(fy + FACE_CHEEK[0][0] * fh), int(fy + FACE_CHEEK[0][1] * fh)
        x0, x1 = int(fx + FACE_CHEEK[1][0] * fw), int(fx + FACE_CHEEK[1][1] * fw)
        sel = person[y0:y1, x0:x1]
        if sel.sum() < FACE_LEAST:
            continue
        cheeks.append([float(np.median(ch[y0:y1, x0:x1][sel])) for ch in (L, a, b)])
    if cheeks:
        c = np.median(np.array(cheeks), axis=0)
        out.update({"face.L": float(c[0]), "face.chroma": float(math.hypot(c[1], c[2])), "face.hue": _hue(c[1], c[2]),
                    "face.count": float(len(cheeks))})
    Y = _luminance(srgb_to_linear(rgb))
    if person.sum() >= least:
        out.update(silhouette(Y, person, unit, seed))
        out.update(edge_contrast(lab, person, unit, seed))
    got = _blur_blocks(luma(rgb), unit, cover=person)
    if got is not None:
        block, share, _ = got
        on_person = np.isfinite(block) & (share >= 0.8)
        on_stage = np.isfinite(block) & (share <= 0.05)
        if on_person.sum() >= 3 and on_stage.sum() >= 3:
            pb, sb = float(np.median(block[on_person])), float(np.median(block[on_stage]))
            out.update({"dof.person_blur": pb, "dof.stage_blur": sb, "dof.stage_ratio": (sb + 1.0) / (pb + 1.0)})
    if person.any():
        b_p = bloom(rgb, unit, sources=person, rings=~person)
        out["bloom.person_strength"], out["bloom.person_r50"] = b_p["bloom.strength"], b_p["bloom.r50"]
    if stage.sum() >= least:
        out["stage.lights"] = float((luma(rgb)[stage] >= BLOOM_SOURCE).mean())
        b_s = bloom(rgb, unit, sources=stage, rings=stage)
        out["bloom.stage_strength"], out["bloom.stage_r50"] = b_s["bloom.strength"], b_s["bloom.r50"]
    return out


_SESSIONS = {}


def seg_session(model, threads=6):
    """the person model (an ONNX file, e.g. skytnt/anime-seg's isnetis.onnx) on the CPU, loaded once"""
    key = (os.path.abspath(model), threads)
    if key not in _SESSIONS:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        _SESSIONS[key] = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
    return _SESSIONS[key]


def person_mask(rgb_u8, session=None, model=None, size=SEG_SIZE):
    """the person's mask (0..1, the frame's size) from the person model: the frame letterboxed into a size x size
    square (RGB in 0..1, as the model was trained), the answer cut back out and made the frame's size"""
    cv2 = _cv2()
    sess = session or seg_session(model)
    img = np.asarray(rgb_u8, np.float32) / 255.0
    h0, w0 = img.shape[:2]
    h, w = (size, int(round(size * w0 / float(h0)))) if h0 > w0 else (int(round(size * h0 / float(w0))), size)
    ph, pw = size - h, size - w
    inp = np.zeros((size, size, 3), np.float32)
    inp[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w] = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    got = sess.run(None, {sess.get_inputs()[0].name: inp.transpose(2, 0, 1)[None]})[0]
    m = np.asarray(got, np.float32).reshape(size, size)[ph // 2:ph // 2 + h, pw // 2:pw // 2 + w]
    return np.clip(cv2.resize(m, (w0, h0), interpolation=cv2.INTER_LINEAR), 0.0, 1.0)


# ---- summaries over frames, comparisons ---------------------------------------------------------------------------

BOOTSTRAP = 400


def _trimmed_rms(d, keep=0.9):
    d = np.sort(np.abs(np.asarray(d, np.float64)))
    if len(d) == 0:
        return float("nan")
    d = d[:max(1, int(math.ceil(keep * len(d))))]
    return float(math.sqrt((d * d).mean()))


def summarise(rows, seed=0):
    """per measure over the frames of a video: median, q25 / q75, n (frames with a value), valid (their share),
    shots (how many shots they come from), floor_pair (the measure's own noise: the trimmed rms of its difference
    between the two pictures of a pair over sqrt 2, from the rows that have m2) and ci (the 2.5 and 97.5 % points of
    the median over the shots drawn again with replacement, BOOTSTRAP times)"""
    keys = []
    for r in rows:
        for k in r["m"]:
            if k not in keys:
                keys.append(k)
    rng = np.random.default_rng(seed)
    out = {}
    for k in keys:
        vals = np.array([r["m"].get(k, float("nan")) for r in rows], np.float64)
        shots = np.array([r.get("shot", 0) for r in rows])
        good = np.isfinite(vals)
        s = {"n": int(good.sum()), "valid": float(good.mean()) if len(vals) else 0.0}
        if good.sum() == 0:
            s.update({"median": float("nan"), "q25": float("nan"), "q75": float("nan"), "shots": 0,
                      "floor_pair": float("nan"), "ci": [float("nan"), float("nan")]})
            out[k] = s
            continue
        v, sh = vals[good], shots[good]
        s["median"] = float(np.median(v))
        s["q25"], s["q75"] = (float(x) for x in np.percentile(v, [25, 75]))
        groups = [v[sh == u] for u in np.unique(sh)]
        s["shots"] = len(groups)
        diffs = [r["m"][k] - r["m2"][k] for r in rows if "m2" in r and k in r["m2"]
                 and np.isfinite(r["m"].get(k, np.nan)) and np.isfinite(r["m2"][k])]
        s["floor_pair"] = _trimmed_rms(diffs) / math.sqrt(2.0) if diffs else float("nan")
        meds = []
        for _ in range(BOOTSTRAP):
            if len(groups) >= 3:
                pick = rng.integers(0, len(groups), len(groups))
                sample = np.concatenate([groups[i] for i in pick])
            else:
                sample = v[rng.integers(0, len(v), len(v))]
            meds.append(np.median(sample))
        s["ci"] = [float(x) for x in np.percentile(meds, [2.5, 97.5])]
        out[k] = s
    return out


def compare(refs, ours, measures=None):
    """rows of the table: per measure the references' per-video medians (their median, quartiles, least and most) and
    each of ours with how far it lies outside the references' quartiles, in units of their spread (the quartile
    distance, at least twice the references' median floor and 5 % of their median): 0 inside, + above, - below
    given by side.  measures: MEASURES (the default) or REGION_MEASURES"""
    rows = []
    for key, (concept, label, unit) in (measures or MEASURES).items():
        vals = [r["summary"].get(key, {}).get("median", float("nan")) for r in refs]
        floors = [r["summary"].get(key, {}).get("floor_pair", float("nan")) for r in refs]
        good = [v for v in vals if v is not None and np.isfinite(v)]
        row = {"key": key, "concept": concept, "label": label, "unit": unit, "refs": dict(zip([r["label"] for r in refs], vals)),
               "ref_n": len(good), "ours": {}}
        if good:
            q25, med, q75 = (float(x) for x in np.percentile(good, [25, 50, 75]))
            fl = [f for f in floors if f is not None and np.isfinite(f)]
            # the quartile distance; at least twice the references' floor and 5 % of their median (references that
            # all agree leave none: 60 fps everywhere)
            spread = max(q75 - q25, 2.0 * float(np.median(fl)) if fl else 0.0, 0.05 * abs(med), 1e-6)
            row.update({"ref_q25": q25, "ref_median": med, "ref_q75": q75, "ref_min": float(min(good)),
                        "ref_max": float(max(good)), "spread": spread})
        for o in ours:
            v = o["summary"].get(key, {}).get("median", float("nan"))
            entry = {"value": v, "floor": o["summary"].get(key, {}).get("floor_pair", float("nan"))}
            if good and v is not None and np.isfinite(v):
                if v > row["ref_q75"]:
                    entry.update({"distance": (v - row["ref_q75"]) / row["spread"], "side": "above"})
                elif v < row["ref_q25"]:
                    entry.update({"distance": (row["ref_q25"] - v) / row["spread"], "side": "below"})
                else:
                    entry.update({"distance": 0.0, "side": "inside"})
            else:
                entry.update({"distance": float("nan"), "side": "none"})
            row["ours"][o["label"]] = entry
        rows.append(row)
    return rows


def _fmt(v):
    if v is None or not np.isfinite(v):
        return "-"
    a = abs(v)
    if a >= 1000:
        return "%.0f" % v
    if a >= 100:
        return "%.1f" % v
    if a >= 1:
        return "%.2f" % v
    return "%.3f" % v


SIDE_JA = {"above": "上へ", "below": "下へ", "inside": "中", "none": "-"}


def table_md(rows, ours_labels, concepts=None, concept_labels=None):
    """the comparison as a markdown table, idea by idea (the references' median [quartiles], ours, and how far outside
    their quartiles ours lie in units of their spread)"""
    lines = []
    head = "| 物差し | 名 | 参考 中央値 [四分位] | " + " | ".join(ours_labels) + " | 参考の外の距離（" + " → ".join(ours_labels) + "） |"
    sep = "| --- | --- | --- | " + " | ".join("---" for _ in ours_labels) + " | --- |"
    labels = concept_labels or CONCEPT_LABELS
    for concept in (concepts or CONCEPTS):
        part = [r for r in rows if r["concept"] == concept]
        if not part:
            continue
        lines += ["", "### " + labels[concept], "", head, sep]
        for r in part:
            ref = "%s [%s, %s]" % (_fmt(r.get("ref_median")), _fmt(r.get("ref_q25")), _fmt(r.get("ref_q75"))) \
                if r.get("ref_n") else "-"
            vals = [_fmt(r["ours"][o]["value"]) for o in ours_labels]
            dist = " → ".join("%s %s" % (SIDE_JA[r["ours"][o]["side"]], _fmt(r["ours"][o]["distance"]))
                              if r["ours"][o]["side"] not in ("inside", "none") else SIDE_JA[r["ours"][o]["side"]]
                              for o in ours_labels)
            unit = (" (%s)" % r["unit"]) if r["unit"] else ""
            lines.append("| %s%s | %s | %s | %s | %s |" % (r["label"], unit, r["key"], ref, " | ".join(vals), dist))
    return "\n".join(lines) + "\n"


# ---- reading videos -------------------------------------------------------------------------------------------------

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
_SPACES = {"bt709": "bt709", "smpte170m": "bt601", "bt470bg": "bt601", "bt2020nc": "bt2020", "bt2020c": "bt2020"}


def parse_rate(text):
    num, _, den = str(text).partition("/")
    rate = float(num) / float(den or 1)
    if not rate > 0:
        raise ValueError("no frame rate in %r" % (text,))
    return int(round(rate)) if abs(rate - round(rate)) < 0.01 else rate


def probe(path, fps=30):
    """what the analysis needs to know of a video (ffprobe) or of a folder of frames (fps given)"""
    if os.path.isdir(path):
        files = sorted(f for f in os.listdir(path) if f.lower().endswith(IMAGE_EXT))
        if not files:
            raise ValueError("no frames in %s" % path)
        from PIL import Image
        with Image.open(os.path.join(path, files[0])) as im:
            w, h = im.size
        return {"folder": True, "files": files, "width": w, "height": h, "fps": fps, "frames": len(files),
                "duration": len(files) / float(fps), "codec": "images", "color_space": "sRGB"}
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,codec_name,pix_fmt,color_space,"
                          "color_range,color_transfer,color_primaries,bit_rate:format=duration,bit_rate",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    st = d["streams"][0]
    fmt = d.get("format", {})
    rate = st.get("avg_frame_rate")
    try:
        fps_v = parse_rate(rate)
    except (ValueError, ZeroDivisionError):
        fps_v = parse_rate(st.get("r_frame_rate"))
    duration = float(fmt.get("duration") or 0.0)
    return {"folder": False, "width": int(st["width"]), "height": int(st["height"]), "fps": fps_v,
            "frames": int(st["nb_frames"]) if st.get("nb_frames", "N/A") not in ("N/A", None) else int(round(duration * fps_v)),
            "duration": duration, "codec": st.get("codec_name"), "pix_fmt": st.get("pix_fmt"),
            "color_space": st.get("color_space"), "color_range": st.get("color_range"),
            "color_transfer": st.get("color_transfer"), "color_primaries": st.get("color_primaries"),
            "bit_rate": int(st.get("bit_rate") or fmt.get("bit_rate") or 0)}


def matrix_for(info, choice="auto"):
    """the YCbCr matrix to read a video with: the one it is tagged with; untagged, what players assume (BT.709 for 720
    lines and more, BT.601 under)"""
    if choice != "auto":
        return choice
    space = _SPACES.get(info.get("color_space") or "")
    if space:
        return space
    return "bt709" if info.get("height", 0) >= 720 else "bt601"


def _scale(info, height):
    h = int(height)
    w = int(round(info["width"] * h / float(info["height"]) / 2.0)) * 2
    return w, h


def _vf(info, height, matrix, extra=""):
    """the filter that reads a frame as RGB at the analysis height: made smaller by averaging the pixels it covers
    (area; lanczos rings by about 8 % of a step at 1.5 to 1, which reads as sharpening), made bigger bicubic"""
    w, h = _scale(info, height) if height else (info["width"], info["height"])
    rng = "pc" if info.get("color_range") in ("pc", "jpeg") else "tv"
    kind = "area" if h < info["height"] else "bicubic"
    return "%sscale=%d:%d:flags=%s+accurate_rnd+full_chroma_int:in_color_matrix=%s:in_range=%s:out_range=pc," \
           "format=rgb24" % (extra, w, h, kind, matrix, rng), (w, h)


def _ffmpeg_frames(argv, size):
    w, h = size
    n = w * h * 3
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        p.stdout.close()
        p.wait()


def _range_args(start, duration):
    a = []
    if start:
        a += ["-ss", "%.6f" % start]
    return a, (["-t", "%.6f" % duration] if duration else [])


def read_frames(path, info, indices, height=None, matrix=None, start=0.0, duration=None, as_uint8=False):
    """the frames of the given numbers (counted from start) as (n, frame) in order, frame H x W x 3 in 0..1 (or uint8),
    scaled to height lines"""
    want = sorted(set(int(i) for i in indices))
    if info.get("folder"):
        from PIL import Image
        first = int(round((start or 0.0) * info["fps"]))
        for n in want:
            with Image.open(os.path.join(path, info["files"][first + n])) as im:
                im = im.convert("RGB")
                if height and im.size[1] != height:
                    im = im.resize(_scale(info, height), Image.BOX if height < im.size[1] else Image.BICUBIC)
                a = np.asarray(im, np.uint8)
            yield n, (a if as_uint8 else a.astype(np.float64) / 255.0)
        return
    matrix = matrix or matrix_for(info)
    expr = "+".join("eq(n\\,%d)" % i for i in want)
    vf, size = _vf(info, height, matrix, extra="select='%s'," % expr)
    pre, post = _range_args(start, duration)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", path] + post + \
           ["-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    for n, a in zip(want, _ffmpeg_frames(argv, size)):
        yield n, (a.copy() if as_uint8 else a.astype(np.float64) / 255.0)


THUMB = (64, 36)                  # every frame at this size: the cuts, flashes, repeats and the corners' darkening


def read_thumbs(path, info, matrix=None, start=0.0, duration=None):
    """every frame at THUMB size as Y' maps (N x 36 x 64, uint8)"""
    if info.get("folder"):
        from PIL import Image
        first = int(round((start or 0.0) * info["fps"]))
        last = len(info["files"]) if not duration else min(len(info["files"]), first + int(round(duration * info["fps"])))
        maps = []
        for f in info["files"][first:last]:
            with Image.open(os.path.join(path, f)) as im:
                a = np.asarray(im.convert("RGB").resize(THUMB, Image.BOX), np.float64) / 255.0
            maps.append(np.clip(luma(a) * 255.0 + 0.5, 0, 255).astype(np.uint8))
        return np.array(maps)
    matrix = matrix or matrix_for(info)
    rng = "pc" if info.get("color_range") in ("pc", "jpeg") else "tv"
    vf = "scale=%d:%d:flags=area:in_color_matrix=%s:in_range=%s:out_range=pc,format=rgb24" % (THUMB + (matrix, rng))
    pre, post = _range_args(start, duration)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", path] + post + \
           ["-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    maps = [np.clip(luma(a.astype(np.float64) / 255.0) * 255.0 + 0.5, 0, 255).astype(np.uint8)
            for a in _ffmpeg_frames(argv, THUMB)]
    return np.array(maps)


# ---- one video ------------------------------------------------------------------------------------------------------

def plan_pairs(n_frames, fps, cut_list, flash_events, step, count):
    """the first frames of count pairs (n, n + step) spread evenly over the frames, half a second in from the ends,
    none across a cut or touching a flash"""
    bad = np.zeros(n_frames + step + 1, bool)
    for c in cut_list:
        bad[max(0, c - step):c] = True                      # a pair starting here would hold the cut
    for e in flash_events:
        bad[max(0, e["start"] - step):e["end"] + 1] = True
    lo, hi = int(0.5 * fps), n_frames - 1 - step - int(0.5 * fps)
    if hi <= lo:
        lo, hi = 0, max(0, n_frames - 1 - step)
    picks = []
    for x in np.linspace(lo, hi, count):
        n = int(round(x))
        for d in range(0, max(2, int(fps))):
            for cand in (n + d, n - d):
                if lo <= cand <= hi and not bad[cand] and cand not in picks:
                    picks.append(cand)
                    break
            else:
                continue
            break
    return sorted(picks)


def _measure_job(job):
    f0, f1, f2, unit, full, seed = job
    extras = {}
    rows = {"m": measure_frame(f0.astype(np.float64) / 255.0, f1.astype(np.float64) / 255.0, unit=unit, full=full,
                               seed=seed, extras=extras), "extras": extras}
    if f2 is not None:
        rows["m2"] = measure_frame(f2.astype(np.float64) / 255.0, None, unit=unit, full=False, seed=seed + 1)
    return rows


def measure_video(path, out, label=None, start=None, end=None, pairs=120, height=720, matrix="auto", jobs=1,
                  pair_every=4, full_every=4, fps=30, seed=0, log=None):
    """measure a video (or folder of frames) and write OUT.json (see the module's docstring)"""
    info = probe(path, fps=fps)
    mat = matrix_for(info, matrix)
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    duration = max(0.0, end - start)
    rate = info["fps"]

    def say(text):
        if log:
            log(text)

    maps = read_thumbs(path, info, mat, start, duration)
    say("thumbs %d" % len(maps))
    thumbs = maps.reshape(len(maps), THUMB[1] // 2, 2, THUMB[0] // 2, 2).mean(axis=(2, 4)) / 255.0
    series = maps.mean(axis=(1, 2)) / 255.0
    flash_events, flash_sum = flashes(series, rate)
    cut_list, cut_sum = cuts(thumbs, rate, flash_events)
    eff = effective_fps(thumbs, rate)
    step = eff["step"]
    ns = plan_pairs(len(maps), rate, cut_list, flash_events, step, pairs)
    want = set(ns) | set(n + step for n in ns)
    frames = dict(read_frames(path, info, want, height=height, matrix=mat, start=start, duration=duration,
                              as_uint8=True))
    say("frames %d" % len(frames))
    ns = [n for n in ns if n in frames and n + step in frames]
    if not ns:
        raise ValueError("no frames read from %s" % path)
    stack = np.array([luma(frames[n].astype(np.float64) / 255.0) for n in ns])
    bars = find_bars(stack)
    x0, y0, x1, y1 = active_box(bars, stack.shape[1:])
    unit = stack.shape[1] / REFERENCE_HEIGHT
    jobs_list = []
    for i, n in enumerate(ns):
        f0 = frames[n][y0:y1, x0:x1]
        f1 = frames[n + step][y0:y1, x0:x1]
        f2 = f1 if i % pair_every == 0 else None
        jobs_list.append((f0, f1, f2, unit, i % full_every == 0, seed + n))
    if jobs > 1:
        import multiprocessing
        with multiprocessing.get_context("spawn").Pool(jobs) as pool:
            results = pool.map(_measure_job, jobs_list, chunksize=1)
    else:
        results = [_measure_job(j) for j in jobs_list]
    rows = []
    for n, r in zip(ns, results):
        shot = sum(1 for c in cut_list if c <= n)
        row = {"n": int(n), "t": start + n / float(rate), "shot": shot, "m": r["m"]}
        if "m2" in r:
            row["m2"] = r["m2"]
        rows.append(row)
    summary = summarise(rows, seed=seed)
    shots = []
    for k in sorted(set(r["shot"] for r in rows)):
        part = [r for r in rows if r["shot"] == k]
        if len(part) < 2:
            continue
        meds = {}
        for key in part[0]["m"]:
            v = np.array([r["m"].get(key, np.nan) for r in part], np.float64)
            meds[key] = float(np.nanmedian(v)) if np.isfinite(v).any() else float("nan")
        shots.append({"shot": int(k), "n": len(part), "start": float(min(r["t"] for r in part)),
                      "end": float(max(r["t"] for r in part)), "m": meds})
    profiles = {}
    curves = [r["extras"]["bloom_profile"] for r in results if r["extras"].get("bloom_profile")]
    if curves:
        med = np.nanmedian(np.array(curves, np.float64), axis=0)
        profiles["bloom"] = [[float(d), float(v)] for d, v in zip(np.arange(1.0, BLOOM_REACH + 1.0), med)
                             if np.isfinite(v)]
    for name in ("tone_hist", "sigma_hist"):
        hs = [r["extras"][name] for r in results if name in r["extras"]]
        if hs:
            profiles[name] = np.sum(np.array(hs, np.float64), axis=0).tolist()
    # the corners' darkening, from every frame inside the bars
    th = maps.shape[1] / float(stack.shape[1])
    tw = maps.shape[2] / float(stack.shape[2])
    box_t = (int(round(x0 * tw)), int(round(y0 * th)), int(round(x1 * tw)), int(round(y1 * th)))
    inner = maps[:, box_t[1]:box_t[3], box_t[0]:box_t[2]].astype(np.float64) / 255.0
    vig = vignette(inner)
    halves = [vignette(inner[0::2])["vignette.corner"], vignette(inner[1::2])["vignette.corner"]]
    w_act, h_act = x1 - x0, y1 - y0
    video_level = {"vignette.corner": (vig["vignette.corner"], abs(halves[0] - halves[1]) / 2.0),
                   "vignette.corner_p10": (vig["vignette.corner_p10"], float("nan")),
                   "vignette.corner_p95": (vig["vignette.corner_p95"], float("nan")),
                   "flash.per_min": (flash_sum["flash.per_min"], float("nan")),
                   "flash.peak": (flash_sum["flash.peak"], float("nan")),
                   "flash.len_s": (flash_sum["flash.len_s"], float("nan")),
                   "cuts.per_min": (cut_sum["cuts.per_min"], float("nan")),
                   "shots.median_s": (cut_sum["shots.median_s"], float("nan")),
                   "frame.aspect": (w_act / float(h_act), 0.0),
                   "frame.bars_tb": ((bars["top"] + bars["bottom"]) / unit, 0.0),
                   "frame.bars_lr": ((bars["left"] + bars["right"]) / unit, 0.0),
                   "frame.fps": (float(rate), 0.0),
                   "frame.fps_effective": (float(eff["frame.fps_effective"]), 0.0)}
    for k, v in light_palette(rows, duration).items():
        video_level[k] = (v, float("nan"))
    for k, v in flicker(series, rate, flash_events, cuts=cut_list).items():
        video_level[k] = (v, float("nan"))
    for k, v in light_motion(maps.astype(np.float64) / 255.0, rate, height_px=maps.shape[1]).items():
        video_level[k] = (v, float("nan"))
    for k, (v, fl) in video_level.items():
        summary[k] = {"median": float(v), "q25": float(v), "q75": float(v), "n": 1, "valid": 1.0, "shots": 1,
                      "floor_pair": float(fl), "ci": [float(v), float(v)]}
    result = {"label": label or os.path.splitext(os.path.basename(path.rstrip("/\\")))[0], "path": path,
              "probe": info if not info.get("folder") else {k: v for k, v in info.items() if k != "files"},
              "range": [start, end], "analysis_height": int(stack.shape[1]),
              "unit": unit, "matrix": mat,
              "frame": {"bars": bars, "box": [int(x0), int(y0), int(x1), int(y1)], "aspect": w_act / float(h_act),
                        "fps": rate, "fps_effective": eff["frame.fps_effective"], "step": step},
              "time": {"cuts": [int(c) for c in cut_list], "flashes": flash_events, "frames": int(len(maps))},
              "vignette": vig, "frames": rows, "shots": shots, "summary": summary, "profiles": profiles}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, allow_nan=True)
    return result


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def layer_masks(path, indices, size, start=0.0, duration=None):
    """{n: mask (0..1)}: the alpha of the frames of the given numbers of a video drawn with an alpha channel (the person
    drawn alone: the dancer's layer of our own render), made `size` by averaging.  ValueError when it is of another shape
    than the frames it is the mask of, or has not all of the frames"""
    info = probe(path)
    w, h = size
    if abs(info["width"] / float(info["height"]) - w / float(h)) > 0.01:
        raise ValueError("the layer %s is %dx%d, the frames it masks %dx%d" % (path, info["width"], info["height"], w, h))
    want = sorted(set(int(i) for i in indices))
    expr = "+".join("eq(n\\,%d)" % i for i in want)
    pre, post = _range_args(start, duration)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", path] + post + \
           ["-vf", "select='%s',alphaextract,scale=%d:%d:flags=area" % (expr, w, h), "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL).stdout
    got = len(raw) // (w * h)
    if got != len(want):
        raise ValueError("the layer %s has %d of the %d frames to mask (from %d to %d)" % (path, got, len(want), want[0],
                                                                                             want[-1]))
    return {n: np.frombuffer(raw[k * w * h:(k + 1) * w * h], np.uint8).reshape(h, w) / 255.0 for k, n in enumerate(want)}


def face_finder(path):
    """a face finder from an OpenCV cascade file (lbpcascade_animeface.xml, nagadomi, MIT: the faces of anime-like
    characters, MMD's among them): frame (RGB uint8) -> boxes (x, y, w, h).  ValueError when it cannot be loaded"""
    cv2 = _cv2()
    cascade = cv2.CascadeClassifier(path) if path and os.path.exists(path) else None
    if cascade is None or cascade.empty():
        raise ValueError("no face finder in %s" % path)

    def find(rgb_u8):
        gray = cv2.equalizeHist(cv2.cvtColor(np.ascontiguousarray(rgb_u8), cv2.COLOR_RGB2GRAY))
        least = max(16, int(round(24 * gray.shape[0] / REFERENCE_HEIGHT)))
        got = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(least, least))
        return [tuple(int(v) for v in f) for f in (got if len(got) else [])]
    return find


def measure_regions(path, out, label=None, start=None, end=None, frames=48, height=720, matrix="auto", model=None,
                    threads=6, mask_fn=None, fps=30, seed=0, log=None, mask_video=None, faces=None):
    """the person and the stage read apart (REGION_MEASURES) on frames spread evenly over a video (or a folder of
    frames), inside its letterbox bars: the person's mask from the person model (model: its ONNX file), from
    mask_fn(frame uint8) -> mask, or from mask_video, a video of the same frames with the person drawn alone with an alpha
    channel (our own render's dancer layer: the person model took a bright floor line under our dancer for part of her on
    some frames, look2); faces: a face finder's cascade file (face_finder) or a function frame -> boxes, for the light on
    her skin (face.*); OUT.json holds each frame's measures and their summary (as measure's)"""
    if mask_fn is None and not model and not mask_video:
        raise ValueError("regions needs the person model (--model isnetis.onnx), the person's layer (--mask-video) or a "
                         "mask function")
    info = probe(path, fps=fps)
    mat = matrix_for(info, matrix)
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    duration = max(0.0, end - start)
    rate = info["fps"]
    total = int(math.floor(duration * rate + 1e-6))
    lo, hi = int(0.5 * rate), total - 1 - int(0.5 * rate)
    if hi <= lo:
        lo, hi = 0, max(0, total - 1)
    ns = sorted(set(int(round(x)) for x in np.linspace(lo, hi, max(1, int(frames)))))
    got = dict(read_frames(path, info, ns, height=height, matrix=mat, start=start, duration=duration, as_uint8=True))
    ns = [n for n in ns if n in got]
    if not ns:
        raise ValueError("no frames read from %s" % path)
    stack = np.array([luma(got[n].astype(np.float64) / 255.0) for n in ns])
    bars = find_bars(stack)
    x0, y0, x1, y1 = active_box(bars, stack.shape[1:])
    unit = stack.shape[1] / REFERENCE_HEIGHT
    layers = None
    if mask_video:
        frame_h, frame_w = got[ns[0]].shape[:2]
        layers = layer_masks(mask_video, ns, (frame_w, frame_h), start=start, duration=duration)
    elif mask_fn is None:
        session = seg_session(model, threads)

        def mask_fn(a):
            return person_mask(a, session=session)
    find_faces = faces if callable(faces) or faces is None else face_finder(faces)
    rows = []
    for n in ns:
        a = np.ascontiguousarray(got[n][y0:y1, x0:x1])
        m = layers[n][y0:y1, x0:x1] if layers is not None else mask_fn(a)
        boxes = find_faces(a) if find_faces is not None else None
        rows.append({"n": int(n), "t": start + n / float(rate), "shot": 0,
                     "m": {k: float(v) for k, v in region_measures(a.astype(np.float64) / 255.0, m, unit, seed=seed + n,
                                                                   faces=boxes).items()}})
        if log:
            log("frame %d person %.3f" % (n, rows[-1]["m"]["frame.person_share"]))
    summary = summarise(rows, seed=seed)
    with_person = sum(1 for r in rows if np.isfinite(r["m"].get("person.L_p50", float("nan"))))
    result = {"label": label or os.path.splitext(os.path.basename(path.rstrip("/\\")))[0], "path": path,
              "probe": info if not info.get("folder") else {k: v for k, v in info.items() if k != "files"},
              "range": [start, end], "analysis_height": int(stack.shape[1]), "unit": unit, "matrix": mat,
              "box": [int(x0), int(y0), int(x1), int(y1)], "frames_with_person": with_person,
              "model": {"path": model, "sha256": _sha256(model)} if model and not mask_video else None,
              "mask": {"video": mask_video, "sha256": _sha256(mask_video)} if mask_video else None,
              "faces": None if faces is None else ("function" if callable(faces) else {"cascade": faces, "sha256": _sha256(faces)}),
              "frames": rows, "summary": summary}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, allow_nan=True)
    return result


# ---- text on the frame ------------------------------------------------------------------------------------------------

TEXT_LEAST = 8.0                  # 720 line pixels: a box of text at least this tall is counted


def text_reader():
    """EasyOCR's text detector (CRAFT) on the CPU, from the models already in ~/.EasyOCR (nothing is downloaded)"""
    if "ocr" not in _LAZY:
        import easyocr
        _LAZY["ocr"] = easyocr.Reader(["en"], gpu=False, download_enabled=False, verbose=False)
    return _LAZY["ocr"]


def text_boxes(rgb_u8, reader):
    """the boxes (x0, y0, x1, y1, pixels) of the text the detector finds in a frame"""
    horizontal, free = reader.detect(np.asarray(rgb_u8))
    out = []
    for b in (horizontal[0] if horizontal else []):
        x0, x1, y0, y1 = (int(v) for v in b)
        out.append((x0, y0, x1, y1))
    for poly in (free[0] if free else []):
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        out.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
    return out


def text_summary(frames, shape, unit=1.0):
    """where and how big the text of a video is, from the boxes of some of its frames (shape: the frame's H, W)

    text.frames: the share of frames with text (a box at least TEXT_LEAST px tall); text.area: the mean share of a
    frame the boxes cover; text.height: the median height of the boxes (720 line pixels: the size of the letters);
    text.top / middle / bottom: the share of boxes whose middle is in that third of the frame; text.corner: the share in
    a corner (the outer quarter across and fifth up or down: watermarks and credits)"""
    h, w = shape[:2]
    boxes, with_text, areas = [], 0, []
    for fb in frames:
        fb = [b for b in fb if (b[3] - b[1]) / unit >= TEXT_LEAST]
        with_text += 1 if fb else 0
        areas.append(sum((b[2] - b[0]) * (b[3] - b[1]) for b in fb) / float(h * w))
        boxes += fb
    out = {"text.frames": with_text / float(len(frames)) if frames else float("nan"),
           "text.area": float(np.mean(areas)) if areas else float("nan"),
           "text.height": float("nan"), "text.top": float("nan"), "text.middle": float("nan"),
           "text.bottom": float("nan"), "text.corner": float("nan")}
    if boxes:
        cy = np.array([(b[1] + b[3]) / 2.0 for b in boxes]) / h
        cx = np.array([(b[0] + b[2]) / 2.0 for b in boxes]) / w
        out["text.height"] = float(np.median([(b[3] - b[1]) / unit for b in boxes]))
        out["text.top"] = float((cy < 1 / 3.0).mean())
        out["text.middle"] = float(((cy >= 1 / 3.0) & (cy < 2 / 3.0)).mean())
        out["text.bottom"] = float((cy >= 2 / 3.0).mean())
        out["text.corner"] = float((((cx < 0.25) | (cx > 0.75)) & ((cy < 0.2) | (cy > 0.8))).mean())
    return out


def measure_text(path, measure_json, frames=24, matrix="auto"):
    """add the text measures to a measure JSON: frames of its sampled frames, spread evenly, read at its analysis
    height inside its bars; the boxes go into its "text" and the measures into its summary (one value each)"""
    with open(measure_json, encoding="utf-8") as fh:
        d = json.load(fh)
    info = probe(path)
    mat = matrix_for(info, d.get("matrix", matrix))
    rows = d["frames"]
    if not rows:
        return d
    pick = sorted(set(int(round(x)) for x in np.linspace(0, len(rows) - 1, min(frames, len(rows)))))
    ns = [rows[i]["n"] for i in pick]
    x0, y0, x1, y1 = d["frame"]["box"]
    got = dict(read_frames(path, info, ns, height=d["analysis_height"], matrix=mat, start=d["range"][0],
                           duration=d["range"][1] - d["range"][0], as_uint8=True))
    reader = text_reader()
    per = []
    for n in ns:
        if n in got:
            per.append(text_boxes(got[n][y0:y1, x0:x1], reader))
    summary = text_summary(per, (y1 - y0, x1 - x0), unit=d["unit"])
    d["text"] = {"frames": [int(n) for n in ns], "boxes": [[list(b) for b in fb] for fb in per]}
    for k, v in summary.items():
        d["summary"][k] = {"median": float(v), "q25": float(v), "q75": float(v), "n": len(per), "valid": 1.0, "shots": 1,
                           "floor_pair": float("nan"), "ci": [float(v), float(v)]}
    with open(measure_json, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, allow_nan=True)
    return d


# ---- figures ----------------------------------------------------------------------------------------------------------

FONTS = ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
OURS_COLOURS = ("#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e")


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    names = []
    for p in FONTS[:1] + ("C:/Windows/Fonts/msyh.ttc",) + FONTS[1:]:     # Microsoft YaHei for simplified Chinese
        if os.path.isfile(p) and len(names) < 2:
            font_manager.fontManager.addfont(p)
            names.append(font_manager.FontProperties(fname=p).get_name())
    if names:
        plt.rcParams["font.family"] = names
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def figure_strip(table, out, keys=None, title=None):
    """the comparison as a figure: one row per measure, the references' per-video medians (grey dots) and their
    quartiles (a grey band), each of ours (coloured), all on the measure's own scale put as (value - median) / spread"""
    plt = _plt()
    rows = [r for r in table["rows"] if r.get("ref_n") and (keys is None or r["key"] in keys)]
    ours = table["ours"]
    fig_h = 0.32 * len(rows) + 1.2
    fig, ax = plt.subplots(figsize=(11, fig_h))
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        med, spread = r["ref_median"], r["spread"]
        ax.add_patch(plt.Rectangle(((r["ref_q25"] - med) / spread, y - 0.3), (r["ref_q75"] - r["ref_q25"]) / spread, 0.6,
                                   color="#dddddd", zorder=1))
        xs = [(v - med) / spread for v in r["refs"].values() if v is not None and np.isfinite(v)]
        ax.scatter(xs, [y] * len(xs), s=12, color="#777777", zorder=2)
        for j, o in enumerate(ours):
            v = r["ours"][o]["value"]
            if v is not None and np.isfinite(v):
                x = float(np.clip((v - med) / spread, -8, 8))
                ax.scatter([x], [y], s=46, marker="D", color=OURS_COLOURS[j % len(OURS_COLOURS)], zorder=3,
                           label=o if i == 0 else None)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(["%s  %s" % (r["key"], _fmt(r["ref_median"])) for r in reversed(rows)], fontsize=7)
    ax.axvline(0, color="#999999", lw=0.8)
    ax.set_xlim(-8.5, 8.5)
    ax.set_xlabel("（値 - 参考の中央値）/ 参考の四分位の幅（灰の帯が参考の四分位、灰の点が参考の各動画、8 で打ち切り）")
    ax.legend(loc="upper right", fontsize=8)
    if title:
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def figure_profiles(out, results, labels=None):
    """the glow's profile (the share of the sources' light at each distance), the tone histogram (L*) and the
    edges' blur histogram of each video, side by side (the references grey, ours coloured)"""
    plt = _plt()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    labels = labels or {}
    k = 0
    for r in results:
        prof = r.get("profiles", {})
        ours = labels.get(r["label"]) is not None
        colour = OURS_COLOURS[k % len(OURS_COLOURS)] if ours else "#888888"
        k += 1 if ours else 0
        lw = 2.0 if ours else 0.8
        if prof.get("bloom"):
            d, s = zip(*prof["bloom"])
            axes[0].plot(d, s, color=colour, lw=lw, label=r["label"] if ours else None)
        if prof.get("tone_hist"):
            h = np.asarray(prof["tone_hist"], np.float64)
            axes[1].plot(np.arange(len(h)) * 2 + 1, h / max(h.sum(), 1e-12), color=colour, lw=lw)
        if prof.get("sigma_hist"):
            h = np.asarray(prof["sigma_hist"], np.float64)
            axes[2].plot(np.arange(len(h)) * 0.5 + 0.25, h / max(h.sum(), 1e-12), color=colour, lw=lw)
    axes[0].set_xlabel("明るい所からの距離（720 行の px）")
    axes[0].set_ylabel("光源の光の割合（背景を引いて）")
    axes[0].set_xlim(0, 60)
    axes[0].set_title("グローの広がり", fontsize=10)
    axes[1].set_xlabel("L*")
    axes[1].set_title("明るさの分布", fontsize=10)
    axes[2].set_xlabel("縁のぼけ（720 行の px）")
    axes[2].set_xlim(0, 12)
    axes[2].set_title("縁のぼけの分布（右に長いほど被写界深度が浅い）", fontsize=10)
    if axes[0].get_legend_handles_labels()[0]:
        axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def _font(size):
    from PIL import ImageFont
    for p in FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _frame_at(path, info, t, height, matrix):
    n = int(round(t * info["fps"]))
    return next(iter(read_frames(path, info, [n], height=height, matrix=matrix, as_uint8=True)))[1]


def contact_sheet(path, out, times, box=None, size=(320, 180), height=720, matrix="auto", label=None):
    """small crops (box in the 720 line frame, scaled to size) of the frames at the given times, in a row, each with
    its time: for the report a small picture of the reference, not the frame itself"""
    from PIL import Image, ImageDraw
    info = probe(path)
    mat = matrix_for(info, matrix)
    ns = [int(round(t * info["fps"])) for t in times]
    got = dict(read_frames(path, info, ns, height=height, matrix=mat, as_uint8=True))     # one pass over the video
    tiles = []
    for t, n in zip(times, ns):
        if n not in got:
            continue
        im = Image.fromarray(got[n])
        if box:
            im = im.crop(box)
        im = im.resize(size, Image.LANCZOS)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 70, 16], fill=(0, 0, 0))
        d.text((3, 1), "%.1f s" % t, fill=(255, 255, 255), font=_font(12))
        tiles.append(im)
    head = 18 if label else 0
    sheet = Image.new("RGB", (size[0] * len(tiles), size[1] + head), (255, 255, 255))
    if label:
        ImageDraw.Draw(sheet).text((4, 2), label, fill=(0, 0, 0), font=_font(12))
    for i, im in enumerate(tiles):
        sheet.paste(im, (i * size[0], head))
    sheet.save(out)
    return out


def annotate(path, out, t, what="dof", box=None, height=720, matrix="auto", scale=1.0, model=None):
    """a frame (cropped to box, 720 line pixels) with what a measure saw drawn on it: dof, the edges coloured by their
    blur (blue sharp, red soft); bloom, the bright sources outlined and rings 4, 16 and 48 px out; ca, the shift of red
    and blue against green as arrows (drawn 20 times longer); bars, the picture inside the bars; regions (model: the
    person model's ONNX), the person's outline, where the stage is read from, and some of the normals the rim (yellow,
    inside) and the glow round the person (green, outside) are read on; lighting, the beams (yellow) and the spots (cyan)
    the lighting measures found"""
    from PIL import Image, ImageDraw
    info = probe(path)
    mat = matrix_for(info, matrix)
    a = _frame_at(path, info, t, height, mat)
    rgb = a.astype(np.float64) / 255.0
    unit = a.shape[0] / REFERENCE_HEIGHT
    im = Image.fromarray(a)
    d = ImageDraw.Draw(im)
    note = ""
    if what == "dof":
        ex = {}
        blocks_out = dof_blocks(luma(rgb), unit, extras=ex)
        bmap, bsize = ex["dof_map"]
        arr = np.asarray(im).astype(np.float64)
        for by in range(bmap.shape[0]):
            for bx in range(bmap.shape[1]):
                v = bmap[by, bx]
                if not np.isfinite(v):
                    continue
                c = np.array([255.0 * min(v / 8.0, 1.0), 60.0, 255.0 * (1 - min(v / 8.0, 1.0))])
                sl = (slice(by * bsize, (by + 1) * bsize), slice(bx * bsize, (bx + 1) * bsize))
                arr[sl] = arr[sl] * 0.65 + c * 0.35
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im)
        e = edges(luma(rgb), unit)
        s = np.clip(e["sigma"] / 8.0, 0, 1)
        for y, x, v in zip(e["y"], e["x"], s):
            c = (int(255 * v), int(80 * (1 - abs(2 * v - 1))), int(255 * (1 - v)))
            d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=c)
        dof = depth_of_field(e)
        note = "縁と区画のぼけ: 青 0 px → 赤 8 px 以上（縁の 90 %% 点 %.1f、区画: ピント %.1f / 背景 %.1f / 比 %.1f）" % (
            dof["dof.soft"], blocks_out["dof.fg_blur"], blocks_out["dof.bg_blur"], blocks_out["dof.ratio"])
    elif what == "lighting":
        ex = {}
        bm = beams(rgb, unit, extras=ex)
        cols = light_colours(rgb, rgb_to_lab(rgb))
        lab_map = ex["light_map"]
        big = np.array(Image.fromarray(lab_map.astype(np.int32)).resize((a.shape[1], a.shape[0]), Image.NEAREST))
        arr = np.asarray(im).astype(np.float64)
        for k_ in ex.get("beam_labels", []):
            sel = big == k_
            arr[sel] = arr[sel] * 0.45 + np.array([255.0, 230.0, 0.0]) * 0.55
        for k_ in ex.get("spot_labels", []):
            sel = big == k_
            arr[sel] = arr[sel] * 0.45 + np.array([0.0, 230.0, 255.0]) * 0.55
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im)
        note = "光の筋（黄）%d 本・光だまり（水色）%d 個、明るい所の色 %d 色（色相の広がり %.0f 度）" % (
            bm["beam.count"], bm["spot.count"], cols["light.colours"], cols["light.spread"])
    elif what == "bloom":
        ndi = _ndi()
        src = luma(rgb) >= BLOOM_SOURCE
        dist = ndi.distance_transform_edt(~src) / unit
        ring = np.zeros(src.shape, bool)
        for r_ in (4.0, 16.0, 48.0):
            ring |= np.abs(dist - r_) < 0.6
        edge = src & ~ndi.binary_erosion(src)
        arr = np.asarray(im).copy()
        arr[ring] = (arr[ring] * 0.3 + np.array([0, 255, 255]) * 0.7).astype(np.uint8)
        arr[edge] = (255, 0, 255)
        im = Image.fromarray(arr)
        d = ImageDraw.Draw(im)
        b = bloom(rgb, unit)
        note = "明るい所（紫の縁）と 4・16・48 px の輪（水色）。グローの強さ %.3f・届き %.1f px" % (
            b["bloom.strength"], b["bloom.r50"])
    elif what == "ca":
        ca = aberration(rgb, unit)
        h, w = a.shape[:2]
        for name, colour in (("red", (255, 40, 40)), ("blue", (40, 120, 255))):
            for cx, cy in ((0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9), (0.5, 0.5)):
                x0, y0 = cx * w, cy * h
                rx, ry = (x0 - w / 2.0) / (w / 2.0), (y0 - h / 2.0) / (h / 2.0)
                radial = ca["ca.%s_radial" % name] * math.hypot(rx * w / 2.0, ry * h / 2.0) / math.hypot(w / 2.0, h / 2.0)
                ang = math.atan2(y0 - h / 2.0, x0 - w / 2.0)
                dx = (ca["ca.%s_x" % name] + radial * math.cos(ang)) * unit * 20
                dy = (ca["ca.%s_y" % name] + radial * math.sin(ang)) * unit * 20
                d.line([x0, y0, x0 + dx, y0 + dy], fill=colour, width=3)
        note = "赤と青の緑に対するずれ（20 倍に伸ばした矢印）: 赤 (%.2f, %.2f) px 倍率 %.2f px、青 (%.2f, %.2f) px 倍率 %.2f px" % (
            ca["ca.red_x"], ca["ca.red_y"], ca["ca.red_radial"], ca["ca.blue_x"], ca["ca.blue_y"], ca["ca.blue_radial"])
    elif what == "motion":
        n = int(round(t * info["fps"]))
        pair = dict(read_frames(path, info, [n, n + 1], height=height, matrix=mat, as_uint8=True))
        g0 = luma(pair[n].astype(np.float64) / 255.0)
        g1 = luma(pair[n + 1].astype(np.float64) / 255.0)
        e = edges(g0, unit)
        det = {}
        m = motion(g0, g1, e, unit, detail=det)
        for y, x, v in zip(det.get("y", []), det.get("x", []), det.get("ratio", [])):
            v = min(float(v), 1.0)
            c = (int(255 * v), int(80 * (1 - abs(2 * v - 1))), int(255 * (1 - v)))
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=c)
        note = "動く縁のぼけ / 動き: 青 0 → 赤 1 以上（中央 %.2f、75 %% 点 %.2f、1/4 以上ぼけた割合 %.2f、%d 点）" % (
            m["motion.shutter"], m["motion.shutter_p75"], m["motion.blurred_share"], m["motion.edges"])
    elif what == "bars":
        bars = find_bars(np.array([luma(rgb)]))
        x0, y0, x1, y1 = active_box(bars, a.shape)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(0, 255, 0), width=2)
        note = "黒帯の内側（緑）: %d x %d" % (x1 - x0, y1 - y0)
    elif what == "regions":
        if not model:
            raise ValueError("annotate regions needs the person model (--model)")
        ndi = _ndi()
        m = person_mask(a, model=model)
        person = m >= 0.5
        r = region_measures(rgb, m, unit)
        stage = ndi.distance_transform_edt(~person) > STAGE_GAP * unit
        arr = np.asarray(im).copy()
        arr[stage & ~ndi.binary_erosion(stage)] = (0, 255, 255)
        arr[person & ~ndi.binary_erosion(person)] = (255, 0, 255)
        im = Image.fromarray(arr)
        d = ImageDraw.Draw(im)
        if person.any() and (~person).any():
            ys, xs, ny, nx = _outline(person, unit, 0)
            for i in range(0, len(ys), max(1, len(ys) // 40)):
                y, x = ys[i], xs[i]
                d.line([x + nx[i] * RIM_EDGE[0] * unit, y + ny[i] * RIM_EDGE[0] * unit,
                        x + nx[i] * RIM_CORE[1] * unit, y + ny[i] * RIM_CORE[1] * unit], fill=(255, 220, 0), width=1)
                d.line([x - nx[i] * HALO_NEAR[0] * unit, y - ny[i] * HALO_NEAR[0] * unit,
                        x - nx[i] * HALO_FAR[1] * unit, y - ny[i] * HALO_FAR[1] * unit], fill=(0, 220, 0), width=1)
        note = "人物の輪郭（紫）・舞台はこの外（水色）・縁の比を読む線（黄、内）とにじみを読む線（緑、外）。人物 %.3f・" \
               "人物 L* %.1f・舞台 L* %.1f・縁の比 %.2f・にじみ %.3f" % (
                   r["frame.person_share"], r["person.L_p50"], r["stage.L_p50"], r["rim.ratio"], r["halo.share"])
    if box:
        im = im.crop(box)
    if scale != 1.0:
        im = im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.LANCZOS)
    font = _font(12)
    lines, line = [], ""
    probe_draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    for ch in "%.1f s  %s" % (t, note):                  # wrapped to the picture's width (a small crop keeps it all)
        if probe_draw.textlength(line + ch, font=font) > im.size[0] - 8:
            lines.append(line)
            line = ""
        line += ch
    lines.append(line)
    head = 4 + 15 * len(lines)
    canvas = Image.new("RGB", (im.size[0], im.size[1] + head), (255, 255, 255))
    canvas.paste(im, (0, head))
    draw = ImageDraw.Draw(canvas)
    for i, text in enumerate(lines):
        draw.text((4, 2 + 15 * i), text, fill=(0, 0, 0), font=font)
    canvas.save(out)
    return out


# ---- the command line -------------------------------------------------------------------------------------------------

def _box(text):
    if not text:
        return None
    parts = [int(v) for v in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("a box is X0,Y0,X1,Y1")
    return tuple(parts)


def _size(text):
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="measure a video or a folder of frames")
    m.add_argument("input")
    m.add_argument("out")
    m.add_argument("--label")
    m.add_argument("--from", dest="start", type=float, help="seconds: where to start (e.g. after an intro)")
    m.add_argument("--to", dest="end", type=float, help="seconds: where to stop")
    m.add_argument("--pairs", type=int, default=120, help="pairs of frames to measure, spread over the video")
    m.add_argument("--height", type=int, default=720, help="the analysis height (lengths are given at 720 lines)")
    m.add_argument("--matrix", default="auto", choices=("auto", "bt601", "bt709", "bt2020"))
    m.add_argument("--jobs", type=int, default=1)
    m.add_argument("--pair-every", type=int, default=4, help="measure the second picture too every this many pairs "
                   "(the noise floor)")
    m.add_argument("--full-every", type=int, default=4, help="the slower measures (fringes, distortion) every this "
                   "many pairs")
    m.add_argument("--fps", type=int, default=30, help="the rate of a folder of frames")
    g = sub.add_parser("regions", help="the person and the stage read apart (the person model's mask)")
    g.add_argument("input")
    g.add_argument("out")
    g.add_argument("--model", help="the person model's ONNX file (skytnt/anime-seg isnetis.onnx)")
    g.add_argument("--mask-video", help="our own render: the person read from her layer, a video of the same frames with "
                                        "her drawn alone with an alpha channel (in place of --model)")
    g.add_argument("--faces", help="a face finder's cascade file (lbpcascade_animeface.xml): the light on her skin, "
                                   "face.L / face.chroma / face.hue, whatever her costume")
    g.add_argument("--label")
    g.add_argument("--from", dest="start", type=float)
    g.add_argument("--to", dest="end", type=float)
    g.add_argument("--frames", type=int, default=48, help="frames spread evenly over the video")
    g.add_argument("--height", type=int, default=720)
    g.add_argument("--matrix", default="auto", choices=("auto", "bt601", "bt709", "bt2020"))
    g.add_argument("--threads", type=int, default=6, help="CPU threads of the model")
    g.add_argument("--fps", type=int, default=30, help="the rate of a folder of frames")
    c = sub.add_parser("compare", help="the references and ours side by side")
    c.add_argument("md")
    c.add_argument("json")
    c.add_argument("--ref", nargs="+", required=True)
    c.add_argument("--ours", nargs="+", required=True)
    c.add_argument("--regions", action="store_true", help="the measures of regions (the person and the stage apart)")
    f = sub.add_parser("figure", help="figures")
    f.add_argument("kind", choices=("strip", "profiles"))
    f.add_argument("out")
    f.add_argument("inputs", nargs="+", help="strip: the compare JSON; profiles: measure JSONs")
    f.add_argument("--ours", nargs="*", default=[], help="profiles: the labels of ours (coloured)")
    f.add_argument("--keys", nargs="*")
    f.add_argument("--title")
    s = sub.add_parser("crops", help="small crops of frames at given times, in a row")
    s.add_argument("input")
    s.add_argument("out")
    s.add_argument("--at", type=float, nargs="+", required=True)
    s.add_argument("--box", type=_box)
    s.add_argument("--size", type=_size, default=(320, 180))
    s.add_argument("--label")
    s.add_argument("--matrix", default="auto", choices=("auto", "bt601", "bt709", "bt2020"),
                   help="our untagged mp4 are BT.601 (as made): auto reads them as BT.709, as players do")
    x = sub.add_parser("text", help="add where and how big the text is to a measure JSON (EasyOCR, CPU)")
    x.add_argument("input")
    x.add_argument("measure_json")
    x.add_argument("--frames", type=int, default=24)
    a = sub.add_parser("annotate", help="a frame with what a measure saw drawn on it")
    a.add_argument("input")
    a.add_argument("out")
    a.add_argument("--at", type=float, required=True)
    a.add_argument("--what", choices=("dof", "bloom", "ca", "bars", "motion", "regions", "lighting"), default="dof")
    a.add_argument("--box", type=_box)
    a.add_argument("--scale", type=float, default=1.0)
    a.add_argument("--model", help="regions: the person model's ONNX file")
    a.add_argument("--matrix", default="auto", choices=("auto", "bt601", "bt709", "bt2020"))
    args = ap.parse_args(argv)
    if args.cmd == "measure":
        r = measure_video(args.input, args.out, label=args.label, start=args.start, end=args.end, pairs=args.pairs,
                          height=args.height, matrix=args.matrix, jobs=args.jobs, pair_every=args.pair_every,
                          full_every=args.full_every, fps=args.fps, log=lambda t: print(t, flush=True))
        print("measured %s: %d pairs, %d cuts, bars %s, fps %s (moves at %s)" % (
            r["label"], len(r["frames"]), len(r["time"]["cuts"]), r["frame"]["bars"], r["frame"]["fps"],
            r["frame"]["fps_effective"]))
    elif args.cmd == "regions":
        r = measure_regions(args.input, args.out, label=args.label, start=args.start, end=args.end, frames=args.frames,
                            height=args.height, matrix=args.matrix, model=args.model, threads=args.threads, fps=args.fps,
                            mask_video=args.mask_video, faces=args.faces)
        s = r["summary"]
        print("regions of %s: %d frames, %d with the person, person %.3f, person L* %.1f, stage L* %.1f, face L* %.1f" % (
            r["label"], len(r["frames"]), r["frames_with_person"], s["frame.person_share"]["median"],
            s["person.L_p50"]["median"], s["stage.L_p50"]["median"], s["face.L"]["median"]))
    elif args.cmd == "compare":
        refs = [_load(p) for p in args.ref]
        ours = [_load(p) for p in args.ours]
        rows = compare(refs, ours, REGION_MEASURES if args.regions else MEASURES)
        labels = [o["label"] for o in ours]
        with open(args.md, "w", encoding="utf-8") as fh:
            if args.regions:
                fh.write(table_md(rows, labels, REGION_CONCEPTS, REGION_CONCEPT_LABELS))
            else:
                fh.write(table_md(rows, labels))
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"refs": [r["label"] for r in refs], "ours": labels, "rows": rows}, fh, ensure_ascii=False,
                      indent=1, allow_nan=True)
        far = sorted(((max([e["distance"] for e in r["ours"].values() if np.isfinite(e["distance"])] or [0]), r["key"])
                      for r in rows), reverse=True)[:12]
        for dist, key in far:
            print("%-24s %.2f" % (key, dist))
    elif args.cmd == "figure":
        if args.kind == "strip":
            figure_strip(_load(args.inputs[0]), args.out, keys=args.keys, title=args.title)
        else:
            results = [_load(p) for p in args.inputs]
            figure_profiles(args.out, results, labels={o: True for o in args.ours})
    elif args.cmd == "crops":
        contact_sheet(args.input, args.out, args.at, box=args.box, size=args.size, label=args.label, matrix=args.matrix)
    elif args.cmd == "text":
        d = measure_text(args.input, args.measure_json, frames=args.frames)
        print("text of %s: %s" % (d["label"], {k: round(v["median"], 3) for k, v in d["summary"].items()
                                              if k.startswith("text.")}))
    elif args.cmd == "annotate":
        annotate(args.input, args.out, args.at, what=args.what, box=args.box, scale=args.scale, matrix=args.matrix,
                 model=args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
