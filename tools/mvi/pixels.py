"""描いた絵の物差し: what only a rendered picture shows.  The measure never renders: it reads pictures drawn elsewhere.

* pants: the underwear pixels of renders of the green-underwear copy of the model (skirt-physics' method, balance_v3's
  pants_mine.py): a pixel with green 160 or more, red and blue 90 or less, and (when the picture has alpha) alpha 128 or
  more; optionally inside a box (x0 y0 x1 y1).  Per picture the count; the rule is 0.
* shadow: the floor shadow's flicker (tools/shadow_check.py rough, and review_softshadow's pixel_checks.rough that the
  later reviews and v10 used): per frame the ratio of the picture with the shadow over the one without it, read where
  the plain floor is bright enough, over the pixels the shadow reaches (the ratio under 0.95 at some frame); the
  roughness in time (mean |second difference| / mean |first difference|: about 1.73 for white noise, near 0 for a
  smooth motion) of each pixel and of the whole darkening (the sum of 1 - ratio over the picture), the largest change
  of a pixel from one frame to the next and of the whole darkening (% of it).
"""
import glob
import json

import numpy as np
from PIL import Image

from . import base

G_MIN, RB_MAX, A_MIN = 160, 90, 128


def pants_count(img, box=None):
    a = np.asarray(img.convert("RGBA") if img.mode != "RGBA" else img, dtype=np.int32)
    if box is not None:
        x0, y0, x1, y1 = [int(v) for v in box]
        a = a[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
    m = (a[..., 1] >= G_MIN) & (a[..., 0] <= RB_MAX) & (a[..., 2] <= RB_MAX)
    if has_alpha:
        m &= a[..., 3] >= A_MIN
    return int(m.sum())


def expand(patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p))
        out += hits if hits else [p]
    return out


def pants(paths, box=None, first_frame=None):
    """{"rows": [the measure], "events": [pictures with pixels], "counts": [...]}; first_frame: the song frame of the first
    picture (the pictures one frame apart), for the events' times"""
    counts = []
    for p in paths:
        with Image.open(p) as img:
            counts.append(pants_count(img, box))
    n_bad = sum(1 for c in counts if c > 0)
    row = base.row("pixels.pants_frames", "下着の画素が出る絵", n_bad, "frames", "pixels.pants（緑の下着の写しの絵、G 160 以上・R/B 90 以下）",
                   pictures=len(paths), px_max=max(counts or [0]))
    events = []
    if first_frame is not None:
        for i, c in enumerate(counts):
            if c > 0:
                events.append(base.event("pixels.pants_frames", first_frame + i, first_frame + i, c, "画素", 0, 1.0, "%s に %d 画素" % (paths[i], c)))
    return {"rows": [row], "events": events, "counts": [{"picture": p, "pixels": c} for p, c in zip(paths, counts)]}


def shadow(plain_pattern, shaded_pattern, first, last, min_plain=4.0, reach=0.95):
    sc = base.tool("shadow_check")
    frames = list(range(first, last + 1))
    series = [sc.ratio_map(sc._rgb(shaded_pattern % i), sc._rgb(plain_pattern % i), min_plain) for i in frames]
    stack = np.stack(series)
    reached = np.nanmin(np.where(np.isfinite(stack), stack, 1.0), axis=0) < reach
    cols = stack[:, reached]
    steps = np.abs(np.diff(cols, axis=0))
    rough = sc.roughness(cols) if cols.size else None
    total = np.nansum(1.0 - np.where(np.isfinite(stack), stack, 1.0), axis=(1, 2))
    rough_total = sc.roughness(total) if len(total) > 2 else None
    change = np.abs(np.diff(total)) / np.where(total[:-1] > 0, total[:-1], np.nan)
    per = np.nanmax(steps, axis=1) if steps.size else np.zeros(0)
    src = "tools/shadow_check.py の rough（review_softshadow の pixel_checks.rough と同じ: 比が 0.95 を下回る画素）"
    row = base.row("pixels.shadow_rough", "床の影の時間の粗さ 画素ごと（白色雑音 1.73、なめらか 0）", rough, "", src,
                   frames=len(frames), pixels=int(reached.sum()), largest_step=None if not steps.size else float(np.nanmax(steps)),
                   p999_step=None if not steps.size else float(np.nanpercentile(steps, 99.9)))
    row_t = base.row("pixels.shadow_total_rough", "床の影の量（暗くなった分の合計）の時間の粗さ", rough_total, "", src,
                     largest_total_change_pct=None if not np.isfinite(change).any() else float(np.nanmax(change) * 100.0))
    events = []
    if len(per):
        thr = float(np.nanpercentile(per, 99)) if len(per) > 10 else float(np.nanmax(per))
        for k, v in enumerate(per):
            if v >= thr and v > 0.05:
                events.append(base.event("pixels.shadow_rough", frames[k], frames[k + 1], float(v), "比", 0.05, 0.05,
                                         "影の濃さが 1 コマで %.3f 変わる" % v))
    return {"rows": [row, row_t], "events": events, "per_step_max": [None if not np.isfinite(v) else float(v) for v in per]}


def write(res, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base.round_tree(res), f, ensure_ascii=False, indent=1)
