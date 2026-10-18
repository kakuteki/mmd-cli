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


def bloom(rgb, unit=1.0, compact=False):
    """the glow round the brightest parts of a frame (Y' over BLOOM_SOURCE), read from the mean linear luminance in
    rings at each distance from them, over the level it falls to further out (the background)

    bloom.strength: the rings' light over the background as a share of the sources' light over it, BLOOM_AT 720 line
    pixels from the sources (0 without glow; a glow added at k times the blurred source gives about k times a constant);
    bloom.r50 / r10: the distance (720 line pixels) at which that share falls to a half and a tenth of its value at
    BLOOM_AT (how far the glow reaches; nan without glow); bloom.halo_red / halo_blue: how
    much more of the glow's light than of the source's is red (or blue): a red halo round a white light, as film's
    halation, is positive.  compact: only small sources (under 0.2 % of the frame each: highlights, lamps, sparkles),
    whose rings do not come near a big one.  profile: the share at each ring (for the figures)."""
    rgb = np.asarray(rgb, np.float64)
    nan = {"bloom.strength": float("nan"), "bloom.r50": float("nan"), "bloom.r10": float("nan"),
           "bloom.halo_red": float("nan"), "bloom.halo_blue": float("nan"), "bloom.sources": 0.0, "profile": []}
    src = luma(rgb) >= BLOOM_SOURCE
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
REBLUR = (1.0, 3.0)               # px: the two re-blurs; the wider is used for edges softer than SOFT_SWITCH
SOFT_SWITCH = 2.5


def _gradient(gray):
    ndi = _ndi()
    gx, gy = ndi.sobel(gray, axis=1) / 8.0, ndi.sobel(gray, axis=0) / 8.0
    return gx, gy, np.hypot(gx, gy)


def edges(gray, unit=1.0, seed=0, points=EDGE_POINTS):
    """the edges of a Y' frame (Canny's thin lines of the strongest gradient) with each one's blur

    The blur is read as Zhuo and Sim (2011) do: blurring the frame again by a known s0 lowers an edge's gradient by
    sqrt(sigma^2 + s0^2) / sigma, so sigma follows from the ratio of the two gradients, whatever the edge's contrast
    (the Sobel gradient's own width taken out).  Returns arrays y, x (pixels), nx, ny (the unit normal, towards the
    bright side), mag (the gradient) and sigma (the blur, as a Gaussian's standard deviation, in 720 line pixels)."""
    cv2, ndi = _cv2(), _ndi()
    g = np.asarray(gray, np.float64)
    gx, gy, mag = _gradient(g)
    u8 = np.clip(ndi.gaussian_filter(g, 0.7) * 255.0, 0, 255).astype(np.uint8)
    hi = max(EDGE_LEAST * 255.0 * 8.0, float(np.percentile(mag, 90)) * 255.0 * 8.0)
    canny = cv2.Canny(u8, hi / 2.0, hi, L2gradient=True, apertureSize=3) > 0
    canny[:3], canny[-3:], canny[:, :3], canny[:, -3:] = False, False, False, False
    sel = canny & (mag >= EDGE_LEAST)
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
    sigma = np.where(sigmas[REBLUR[0]] <= SOFT_SWITCH, sigmas[REBLUR[0]], sigmas[REBLUR[1]])
    sx, sy, smag = _gradient(ndi.gaussian_filter(g, 1.0))      # the normal from the smoothed frame (steadier)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx, ny = sx[ys, xs] / smag[ys, xs], sy[ys, xs] / smag[ys, xs]
    good = np.isfinite(sigma) & (sigma < 40.0 * unit) & np.isfinite(nx) & np.isfinite(ny)
    return {"y": ys[good], "x": xs[good], "nx": nx[good], "ny": ny[good], "mag": m0[good],
            "sigma": sigma[good] / unit, "shape": g.shape}


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


SHORT = (8.0, 16.0)               # 720 line pixels: the near sides of an edge (sharpening, width) and
LONG = (28.0, 40.0)               # the far sides (diffusion), where a step's flat sides are read
STEP_LEAST = 0.12                 # Y': a step read for its profile rises at least this,
FLAT_MOST = 0.04                  # and each side's spread stays under this
INNER = 4.0                       # diffusion: the share of the step not reached within this of the edge (720 px)
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
    steps with flat sides 28 to 40 px out and a sharp core, the share of the step not reached within INNER px of the
    edge, less what the core's own blur leaves there (a veil over the frame: the sharp core stays, a wide soft skirt is
    added); diffusion.radius: how far out that skirt reaches half of the rest; profile.short / long: how many steps."""
    g = np.asarray(gray, np.float64)
    n = len(e["y"])
    out = {"sharp.width": float("nan"), "sharp.overshoot": float("nan"), "diffusion.share": float("nan"),
           "diffusion.radius": float("nan"), "profile.short": 0.0, "profile.long": 0.0}
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
    core = e["sigma"][idx][ok]
    keep = core <= CORE_MOST
    out["profile.long"] = float(keep.sum())
    if keep.sum() >= 10:
        q, core = q[keep], core[keep]
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
        if len(shares) >= 10:
            out["diffusion.share"] = float(np.median(shares))
        if radii:
            out["diffusion.radius"] = float(np.median(radii))
    return out


MOVING_LEAST = 3.0                # 720 line pixels a frame: an edge moving across itself at least this is read for
STILL_MOST = 0.5                  # motion blur, against edges moving less than this; a pixel moving at least
MOVING_PIXEL = 1.0                # this counts as moving


def flow(gray0, gray1):
    """the optical flow from one Y' frame to the next (Farneback), pixels a frame: H x W x 2 (x, y)"""
    cv2 = _cv2()
    a = np.clip(np.asarray(gray0) * 255.0, 0, 255).astype(np.uint8)
    b = np.clip(np.asarray(gray1) * 255.0, 0, 255).astype(np.uint8)
    return cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 5, 21, 4, 7, 1.5, 0)


def motion(gray0, gray1, e, unit=1.0, f=None, seed=0):
    """motion and motion blur between two frames (the second the next different picture)

    motion.speed: the median speed of the moving edges (720 line pixels a frame); motion.moving: the share of pixels
    moving at least MOVING_PIXEL; motion.shutter: how long the shutter was open as a share of the frame time, from the
    10 to 90 % width of edges moving across themselves against the width of still ones: a box blur of length L widens
    a step by 0.8 L, so shutter = sqrt(w_moving^2 - w_still^2) / (0.8 x the edge's motion across itself) (0 without
    motion blur, 0.5 for a 180 degree shutter).  f: the flow if already made."""
    g0 = np.asarray(gray0, np.float64)
    if f is None:
        f = flow(gray0, gray1)
    speed = np.hypot(f[..., 0], f[..., 1]) / unit
    out = {"motion.speed": float("nan"), "motion.moving": float((speed >= MOVING_PIXEL).mean()),
           "motion.shutter": float("nan"), "motion.edges": 0.0}
    n = len(e["y"])
    if n == 0:
        return out
    fx, fy = f[e["y"], e["x"], 0], f[e["y"], e["x"], 1]
    across = np.abs(fx * e["nx"] + fy * e["ny"]) / unit
    sp = np.hypot(fx, fy) / unit
    moving = np.nonzero((across >= MOVING_LEAST) & (np.abs(fx * e["nx"] + fy * e["ny"]) >= 0.7 * np.hypot(fx, fy)))[0]
    still = np.nonzero(sp < STILL_MOST)[0]
    if len(moving):
        out["motion.speed"] = float(np.median(sp[moving]))
    if len(moving) < 10 or len(still) < 10:
        return out
    rng = np.random.default_rng(seed)
    if len(moving) > PROFILE_POINTS:
        moving = rng.choice(moving, PROFILE_POINTS, replace=False)
    if len(still) > PROFILE_POINTS:
        still = rng.choice(still, PROFILE_POINTS, replace=False)

    def widths(idx, half):
        t, p = _profiles(g0, e, half, unit, idx)
        sides = (half * 0.6, half)
        ok, q = _steps(t, p, sides)
        return ok, np.array([_width(t, row) for row in q])

    ok_s, w_s = widths(still, SHORT[1])
    w_still = np.nanmedian(w_s) if np.isfinite(w_s).sum() >= 5 else float("nan")
    half = float(min(80.0, max(SHORT[1], 1.5 * np.percentile(across[moving], 90))))
    ok_m, w_m = widths(moving, half)
    u = across[moving][ok_m]
    good = np.isfinite(w_m)
    out["motion.edges"] = float(good.sum())
    if good.sum() < 5 or not np.isfinite(w_still):
        return out
    s = np.sqrt(np.clip(w_m[good] ** 2 - w_still ** 2, 0.0, None)) / (0.8 * u[good])
    out["motion.shutter"] = float(np.median(s))
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
