"""The time figure (図示): the per-frame curves of a report along the song, one row each, with the rule's lines, people's
band where a curve has one, and the listed places of the curve's idea marked above it in red.  Drawn with Pillow (no
plotting library), the min and max of the frames under each pixel column so that a one-frame spike stays visible.
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import base

FONTS = ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")
WIDTH = 1800
ROW = 150
LEFT, RIGHT, TOP = 70, 20, 50
INK = (40, 40, 40)
GRID = (225, 225, 225)
CURVE = (31, 119, 180)
BAND = (210, 235, 210)
LIMIT = (200, 120, 0)
EVENT = (214, 39, 40)
DEFAULT = ("pelvis_down", "centre_ay", "pelvis_acc", "hover", "shoe_left", "shoe_right", "zmp_margin", "com_lateral",
           "eye_edge", "mouth_open")


def font(size):
    for p in FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _envelope(y, x0, x1, cols):
    """per pixel column the (min, max) of the finite values of y[x0:x1] that fall in it"""
    n = x1 - x0
    edges = np.linspace(0, n, cols + 1).astype(int)
    lo = np.full(cols, np.nan)
    hi = np.full(cols, np.nan)
    seg = y[x0:x1]
    for c in range(cols):
        a, b = edges[c], max(edges[c + 1], edges[c] + 1)
        v = seg[a:b]
        v = v[np.isfinite(v)]
        if len(v):
            lo[c], hi[c] = v.min(), v.max()
    return lo, hi


def figure(report, series, path, names=None, t0=None, t1=None, title=None):
    """write the figure; series: name -> array [F] (the report's series.npz), report["series"][name]: its label etc."""
    meta = report.get("series", {})
    names = [n for n in (names or DEFAULT) if n in series and n in meta] if names else [n for n in DEFAULT if n in series and n in meta]
    if not names:
        names = [n for n in meta if n in series]
    F = report["frames"]
    f0 = 0 if t0 is None else max(0, int(round(t0 * base.FPS)))
    f1 = F if t1 is None else min(F, int(round(t1 * base.FPS)) + 1)
    if f1 - f0 < 2:
        raise ValueError("the span of the figure has fewer than 2 frames")
    cols = WIDTH - LEFT - RIGHT
    H = TOP + ROW * len(names) + 40
    img = Image.new("RGB", (WIDTH, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_title, f_lab, f_small = font(22), font(15), font(12)
    d.text((LEFT, 12), title or "%s の物差しの時間の図（%s〜%s 秒）" % (report["label"], base.num(f0 / base.FPS), base.num(f1 / base.FPS)),
           fill=INK, font=f_title)
    xs = lambda f: LEFT + (f - f0) / float(f1 - f0) * cols          # noqa: E731
    evs = [e for e in report["events"] if e.get("listed")]
    for k, name in enumerate(names):
        m = meta[name]
        y = np.asarray(series[name], dtype=np.float64)
        top = TOP + k * ROW
        y0p, y1p = top + 31, top + ROW - 8
        seg = y[f0:f1]
        fin = seg[np.isfinite(seg)]
        lims = [v for v in (m.get("lo"), m.get("hi")) if v is not None]
        if len(fin):
            lo, hi = float(np.percentile(fin, 0.5)), float(np.percentile(fin, 99.5))
            lo, hi = min([lo] + lims), max([hi] + lims)
        else:
            lo, hi = (min(lims), max(lims)) if lims else (0.0, 1.0)
        if hi - lo < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        pad = 0.05 * (hi - lo)
        lo, hi = lo - pad, hi + pad
        ys = lambda v: y1p - (v - lo) / (hi - lo) * (y1p - y0p)      # noqa: E731
        d.rectangle([LEFT, y0p, LEFT + cols, y1p], outline=GRID)
        ref = base.reference(m["ref"]) if m.get("ref") else None
        if ref and ref.get("kind") == "people":
            d.rectangle([LEFT, max(y0p, ys(ref["q3"])), LEFT + cols, min(y1p, ys(ref["q1"]))], fill=BAND)
        for v in lims:
            if lo <= v <= hi:
                yy = ys(v)
                for xx in range(LEFT, LEFT + cols, 12):
                    d.line([xx, yy, xx + 6, yy], fill=LIMIT, width=1)
        if "air" in series and name == "pelvis_down":
            air = np.asarray(series["air"], bool)[f0:f1]
            for a, b in base.runs(air):
                d.rectangle([xs(f0 + a), y0p, xs(f0 + b + 1), y1p], fill=(235, 235, 250))
        lo_c, hi_c = _envelope(y, f0, f1, cols)
        for c in range(cols):
            if np.isfinite(lo_c[c]):
                d.line([LEFT + c, ys(hi_c[c]), LEFT + c, ys(lo_c[c])], fill=CURVE, width=1)
        concept, ids = m.get("concept"), m.get("ids")
        for e in evs:
            if (e["id"] not in ids if ids else e["concept"] != concept) or e["last"] < f0 or e["first"] >= f1:
                continue
            d.rectangle([xs(max(e["first"], f0)), top + 23, max(xs(max(e["first"], f0)) + 2, xs(min(e["last"] + 1, f1))), top + 28],
                        fill=EVENT)
        d.text((LEFT, top + 1), m.get("label", name), fill=INK, font=f_lab)
        for v in (lo + pad, hi - pad):
            d.text((4, ys(v) - 7), base.num(v, 3), fill=INK, font=f_small)
    step = 10 if (f1 - f0) / base.FPS <= 120 else 30
    t = (f0 / base.FPS // step + 1) * step
    while t * base.FPS < f1:
        x = xs(t * base.FPS)
        d.line([x, TOP + 18, x, TOP + ROW * len(names)], fill=GRID)
        d.text((x - 12, H - 32), "%d 秒" % int(round(t)), fill=INK, font=f_small)
        t += step
    d.text((LEFT + cols - 520, H - 18), "緑の帯 = 人の四分位（列ごとの値）、橙の破線 = 決まり、赤 = 外れた所（重い順の時刻表に入るもの）",
           fill=INK, font=f_small)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path)
    return path
