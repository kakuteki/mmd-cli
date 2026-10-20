"""Measure the kinetic typography of a video in numbers: where and when its text comes and goes, how it moves, what it
looks like, and how it goes with the voice and the beat.

    python tools/typo_analyze.py detect VIDEO OUT.json [--from S] [--to S] [--rate 2] [--height 540]
                                        [--craft-onnx craft.onnx] [--threads 3]          # the text of sampled frames

Why (2026-10-20, typoref): the request is to take the lighting, the kinetic typography of the lyrics and the motion
graphics of the YouTube channel @PizaCG as the reference for our MV.  tools/look_analyze.py measures the look of a frame;
this tool measures the text.

1. The detector: CRAFT (Baek et al. 2019, the text detector of EasyOCR, craft_mlt_25k) on the CPU, through onnxruntime
   when an ONNX export of it is given (about 20 % faster on hinata) or through torch.  For a frame it gives two maps at
   half the frame's size: the region score (a Gaussian on every character) and the link score (between the characters
   of a word or line).  The boxes are read from them as EasyOCR reads them (text_boxes: the parts above LOW_TEXT or
   LINK_TH whose highest score reaches TEXT_TH, grown a little, in a rotated rectangle; the long side is along the
   text, so a column of Japanese text is a box whose long side stands up), and every character is a peak of the region
   score (char_peaks: its place, and its size from the width of its peak at half its height in its own share of the
   map).
2. detect: frames sampled at `rate` a second from the video (read at `height` lines, the colour as tools/look_analyze.py
   reads it), their boxes and characters, and the picture's black bars.  Places are in px of the frame as read and as
   shares of the picture inside the bars.
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_LAZY = {}


def _tool(name):
    """a sibling tool (tools/ is not a package), loaded once"""
    if name not in _LAZY:
        spec = importlib.util.spec_from_file_location("_typo_" + name, os.path.join(HERE, name + ".py"))
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


# ---- the maps of the detector ------------------------------------------------------------------------------------------

TEXT_TH = 0.7                     # a box's highest region score reaches this (EasyOCR's text_threshold)
LOW_TEXT = 0.4                    # the region score above this is text (EasyOCR's low_text)
LINK_TH = 0.4                     # the link score above this joins characters (EasyOCR's link_threshold)
LEAST_AREA = 10                   # map px: smaller parts are noise (EasyOCR)
VERTICAL = 50.0                   # degrees: a box whose long side stands steeper than this is a column of text
PEAK_LEAST = 0.5                  # a character is a peak of the region score at least this high
PEAK_WINDOW = 3                   # map px: a peak is the highest in this square round it
HALF_MAX_DIAMETER = 0.754         # the width of a character's peak at half its height, as a share of the character's
#                                   size: 2 sqrt(2 ln 2) 0.32 for a Gaussian of sigma 0.32 size (the maps of the tests);
#                                   the size of CRAFT's peaks against the glyphs is measured on drawn text (NOTES)


def _rect_geometry(points):
    """the long side, the short side, the angle of the long side (degrees in (-90, 90]) and the centre of a rotated
    rectangle given by its 4 corners"""
    p = np.asarray(points, np.float64)
    e1, e2 = p[1] - p[0], p[2] - p[1]
    l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
    long_edge = e1 if l1 >= l2 else e2
    angle = math.degrees(math.atan2(long_edge[1], long_edge[0]))
    if angle <= -90.0:
        angle += 180.0
    elif angle > 90.0:
        angle -= 180.0
    c = p.mean(axis=0)
    return max(l1, l2), min(l1, l2), angle, (float(c[0]), float(c[1]))


def text_boxes(score, link, ratio=2.0, text_th=TEXT_TH, link_th=LINK_TH, low=LOW_TEXT):
    """the boxes of the text in a detector's maps (score: the region score, link: the link score, both at map size;
    ratio: frame px per map px), read as EasyOCR's getDetBoxes_core reads them.  Each box: x0 y0 x1 y1 (the upright box
    round it, frame px), cx cy, w (the long side, along the text) and h, angle (of the long side, degrees), vertical
    (a column of text), score (its highest region score), area (frame px^2 of its parts)"""
    cv2 = _cv2()
    score = np.asarray(score, np.float32)
    link = np.asarray(link, np.float32)
    text_on = score > low
    link_on = link > link_th
    comb = (text_on | link_on).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(comb, connectivity=4)
    h_img, w_img = score.shape
    out = []
    for k in range(1, n):
        size = int(stats[k, cv2.CC_STAT_AREA])
        if size < LEAST_AREA:
            continue
        part = labels == k
        top = float(score[part].max())
        if top < text_th:
            continue
        seg = np.zeros(score.shape, np.uint8)
        seg[part] = 255
        seg[link_on & ~text_on] = 0                       # the links alone do not widen the box
        x, y = int(stats[k, cv2.CC_STAT_LEFT]), int(stats[k, cv2.CC_STAT_TOP])
        w, h = int(stats[k, cv2.CC_STAT_WIDTH]), int(stats[k, cv2.CC_STAT_HEIGHT])
        niter = int(math.sqrt(size * min(w, h) / float(w * h)) * 2)
        sx, ex, sy, ey = max(0, x - niter), min(w_img, x + w + niter + 1), max(0, y - niter), min(h_img, y + h + niter + 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1 + niter, 1 + niter))
        seg[sy:ey, sx:ex] = cv2.dilate(seg[sy:ey, sx:ex], kernel)
        ys, xs = np.nonzero(seg)
        if len(xs) < 3:
            continue
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        rect = cv2.minAreaRect(pts)
        corners = cv2.boxPoints(rect)
        long_side, short_side, angle, (cx, cy) = _rect_geometry(corners)
        r = float(ratio)
        out.append({"x0": float(corners[:, 0].min()) * r, "y0": float(corners[:, 1].min()) * r,
                    "x1": float(corners[:, 0].max()) * r, "y1": float(corners[:, 1].max()) * r,
                    "cx": cx * r, "cy": cy * r, "w": long_side * r, "h": short_side * r, "angle": angle,
                    "vertical": bool(abs(angle) > VERTICAL), "score": top, "area": float(part.sum()) * r * r})
    return out


def char_peaks(score, ratio=2.0, least=PEAK_LEAST, window=PEAK_WINDOW):
    """the characters in a region score map: [(x, y, peak, size)] in frame px (ratio: frame px per map px), x y the
    peak's place (to a fraction of a map px: the score-weighted middle of its 3 x 3), size from the width of the peak
    at half its height inside its own share of the map (the pixels nearer to it than to any other peak), as the size of
    a character whose Gaussian it is (HALF_MAX_DIAMETER)"""
    ndi = _ndi()
    s = np.asarray(score, np.float64)
    top = ndi.maximum_filter(s, size=window, mode="constant", cval=0.0)
    ys, xs = np.nonzero((s >= top) & (s >= least))
    if len(xs) == 0:
        return []
    # one peak per plateau: keep the first of equal neighbours
    keep, seen = [], set()
    for y, x in sorted(zip(ys.tolist(), xs.tolist()), key=lambda p: -s[p[0], p[1]]):
        if any(abs(y - y2) <= window // 2 and abs(x - x2) <= window // 2 for y2, x2 in seen):
            continue
        seen.add((y, x))
        keep.append((y, x))
    h, w = s.shape
    pts = np.array([[x, y] for y, x in keep], np.float64)
    # each pixel's nearest peak (its share of the map), over the pixels above the lowest half height
    half = np.array([s[y, x] for y, x in keep]) / 2.0
    lit = s >= half.min()
    yy, xx = np.nonzero(lit)
    d2 = (xx[:, None] - pts[None, :, 0]) ** 2 + (yy[:, None] - pts[None, :, 1]) ** 2
    owner = np.argmin(d2, axis=1)
    out = []
    for i, (y, x) in enumerate(keep):
        y0, y1, x0, x1 = max(0, y - 1), min(h, y + 2), max(0, x - 1), min(w, x + 2)
        wts = s[y0:y1, x0:x1]
        gy, gx = np.mgrid[y0:y1, x0:x1]
        cy = float((wts * gy).sum() / wts.sum())
        cx = float((wts * gx).sum() / wts.sum())
        mine = owner == i
        area = int(np.count_nonzero(s[yy[mine], xx[mine]] >= half[i]))
        diameter = 2.0 * math.sqrt(area / math.pi)
        out.append((cx * ratio, cy * ratio, float(s[y, x]), diameter / HALF_MAX_DIAMETER * ratio))
    return out


# ---- the detector ------------------------------------------------------------------------------------------------------

CRAFT_MEAN = np.array([0.485, 0.456, 0.406], np.float32) * 255.0
CRAFT_STD = np.array([0.229, 0.224, 0.225], np.float32) * 255.0
CRAFT_MODEL = os.path.expanduser(os.path.join("~", ".EasyOCR", "model", "craft_mlt_25k.pth"))


class Craft:
    """CRAFT on the CPU: (score, link, ratio) of an RGB frame (uint8), the maps at half its size (ratio 2).  With onnx,
    an ONNX export of craft_mlt_25k run by onnxruntime; without, EasyOCR's own network through torch.  threads: the
    CPU threads it may use (hinata is shared)."""

    def __init__(self, onnx=None, threads=3, model=CRAFT_MODEL):
        self.onnx = onnx
        if onnx:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = int(threads)
            so.inter_op_num_threads = 1
            self.session = ort.InferenceSession(onnx, so, providers=["CPUExecutionProvider"])
        else:
            import torch
            torch.set_num_threads(int(threads))
            from easyocr.detection import get_detector
            self.net = get_detector(model, device="cpu", quantize=False)

    def __call__(self, rgb):
        a = np.asarray(rgb)
        h, w = a.shape[:2]
        h32, w32 = h + (-h) % 32, w + (-w) % 32
        x = np.zeros((h32, w32, 3), np.float32)
        x[:h, :w] = (a.astype(np.float32) - CRAFT_MEAN) / CRAFT_STD
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        if self.onnx:
            y = self.session.run(None, {self.session.get_inputs()[0].name: x})[0]
        else:
            import torch
            with torch.no_grad():
                y = self.net(torch.from_numpy(x))[0].numpy()
        hm, wm = (h + 1) // 2, (w + 1) // 2
        return y[0, :hm, :wm, 0], y[0, :hm, :wm, 1], 2.0


# ---- sampled frames ----------------------------------------------------------------------------------------------------

def sample_frames(n_frames, fps, rate):
    """the numbers of the frames sampled `rate` times a second (every round(fps / rate)-th, from 0)"""
    step = max(1, int(round(float(fps) / float(rate))))
    return list(range(0, int(n_frames), step))


def detect_samples(frames, detector, fps):
    """the text of every frame of `frames` ({n: RGB uint8}): [{n, t, boxes, chars}] in the order of n, t = n / fps (s
    from the start of the frames)"""
    out = []
    for n in sorted(frames):
        score, link, ratio = detector(frames[n])
        boxes = text_boxes(score, link, ratio)
        chars = char_peaks(score, ratio)
        out.append({"n": int(n), "t": n / float(fps), "boxes": boxes,
                    "chars": [[round(c[0], 2), round(c[1], 2), round(c[2], 3), round(c[3], 2)] for c in chars]})
    return out


def detect_video(path, out, start=None, end=None, rate=2.0, height=540, onnx=None, threads=3, matrix="auto",
                 log=None, detector=None):
    """detect (see the module's docstring): OUT.json with the samples, the bars and the frame's size"""
    LA = _tool("look_analyze")
    info = LA.probe(path)
    mat = LA.matrix_for(info, matrix)
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    duration = max(0.0, end - start)
    fps = info["fps"]
    total = int(math.floor(duration * fps + 1e-6))
    ns = sample_frames(total, fps, rate)
    detector = detector or Craft(onnx=onnx, threads=threads)
    t0 = time.time()
    samples, lumas = [], []
    size = None
    batch = 64
    for i in range(0, len(ns), batch):
        part = ns[i:i + batch]
        got = dict(LA.read_frames(path, info, part, height=height, matrix=mat, start=start, duration=duration,
                                  as_uint8=True))
        for n in part:
            if n not in got:
                continue
            a = got[n]
            size = (a.shape[1], a.shape[0])
            lumas.append(LA.luma(a[::4, ::4].astype(np.float64) / 255.0))
            samples += detect_samples({n: a}, detector, fps)
            samples[-1]["t"] = start + n / float(fps)
        if log:
            log("detect %d / %d frames, %.0f s" % (min(i + batch, len(ns)), len(ns), time.time() - t0))
    if not samples:
        raise ValueError("no frames read from %s" % path)
    stack = np.array(lumas)
    bars = LA.find_bars(stack)
    box = LA.active_box(bars, stack.shape[1:])
    box = [int(v * 4) for v in box]
    box[2], box[3] = min(box[2], size[0]), min(box[3], size[1])
    result = {"label": os.path.splitext(os.path.basename(path))[0], "path": path, "probe": info, "range": [start, end],
              "fps": fps, "rate": rate, "height": int(height), "size": list(size), "matrix": mat,
              "picture": box, "detector": {"onnx": onnx, "threads": threads}, "seconds": round(time.time() - t0, 1),
              "samples": samples}
    result["summary"] = detect_summary(result)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return result


def detect_summary(d):
    """the text of the samples in a few numbers: the share of samples with text, the boxes per sample, where the boxes
    are (thirds of the picture across and down), their height as a share of the picture's, the share of columns"""
    x0, y0, x1, y1 = d["picture"]
    pw, ph = float(x1 - x0), float(y1 - y0)
    samples = d["samples"]
    with_text = [s for s in samples if s["boxes"]]
    boxes = [b for s in samples for b in s["boxes"]]
    out = {"samples": len(samples), "text_share": len(with_text) / float(len(samples)) if samples else float("nan"),
           "boxes_per_sample": len(boxes) / float(len(samples)) if samples else float("nan"),
           "boxes": len(boxes)}
    if boxes:
        cx = np.array([(b["cx"] - x0) / pw for b in boxes])
        cy = np.array([(b["cy"] - y0) / ph for b in boxes])
        hh = np.array([b["h"] / ph for b in boxes])
        out.update({"height_median": float(np.median(hh)), "height_p90": float(np.percentile(hh, 90)),
                    "vertical_share": float(np.mean([b["vertical"] for b in boxes])),
                    "across": [float(np.mean(cx < 1 / 3.0)), float(np.mean((cx >= 1 / 3.0) & (cx < 2 / 3.0))),
                               float(np.mean(cx >= 2 / 3.0))],
                    "down": [float(np.mean(cy < 1 / 3.0)), float(np.mean((cy >= 1 / 3.0) & (cy < 2 / 3.0))),
                             float(np.mean(cy >= 2 / 3.0))],
                    "area_share": float(np.mean([sum(b["w"] * b["h"] for b in s["boxes"]) / (pw * ph)
                                                 for s in samples]))})
    return out


# ---- tracks: the same text from sample to sample ----------------------------------------------------------------------

LINK_OVERLAP = 0.3                # a box continues a track when it covers this share of the smaller of the two,
LINK_HEIGHT = 1.6                 # their heights are within this ratio,
LINK_REACH = 3.0                  # or, not overlapping, its centre is within this many heights of where the track goes
GAP_SAMPLES = 1                   # a track may miss this many samples (a blink, a missed detection)
LINE_SHARE = 0.8                  # two tracks together in this share of the samples of the shorter one,
LINE_GAP = 1.5                    # this many heights apart at most along their line,
LINE_ALIGN = 0.35                 # off their common line by this share of the height at most: one line (CRAFT parts a
#                                   line at its spaces)


def _overlap(a, b):
    """the area two upright boxes share, as a share of the smaller"""
    w = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    h = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a["x1"] - a["x0"]) * (a["y1"] - a["y0"]), (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))
    return w * h / max(small, 1e-9)


def _union(boxes):
    """the upright box round several boxes, with their mean angle and the long and short sides of the whole"""
    x0 = min(b["x0"] for b in boxes)
    y0 = min(b["y0"] for b in boxes)
    x1 = max(b["x1"] for b in boxes)
    y1 = max(b["y1"] for b in boxes)
    vertical = boxes[0]["vertical"]
    if len(boxes) == 1:
        return dict(boxes[0])
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "cx": (x0 + x1) / 2.0, "cy": (y0 + y1) / 2.0,
            "w": (y1 - y0) if vertical else (x1 - x0), "h": float(np.median([b["h"] for b in boxes])),
            "angle": float(np.mean([b["angle"] for b in boxes])), "vertical": vertical,
            "score": max(b["score"] for b in boxes), "area": sum(b["area"] for b in boxes)}


def _median_box(boxes):
    keys = ("x0", "y0", "x1", "y1", "cx", "cy", "w", "h", "angle", "score", "area")
    out = {k: float(np.median([b[k] for b in boxes])) for k in keys}
    out["vertical"] = bool(np.mean([b["vertical"] for b in boxes]) >= 0.5)
    return out


def _same_line(a, b):
    """whether two boxes of one sample are parts of one line (see LINE_GAP, LINE_ALIGN)"""
    if a["vertical"] != b["vertical"]:
        return False
    h = max(a["h"], b["h"])
    if max(a["h"], b["h"]) > 1.3 * min(a["h"], b["h"]):
        return False
    if a["vertical"]:
        off = abs(a["cx"] - b["cx"])
        gap = max(b["y0"] - a["y1"], a["y0"] - b["y1"])
    else:
        off = abs(a["cy"] - b["cy"])
        gap = max(b["x0"] - a["x1"], a["x0"] - b["x1"])
    return off <= LINE_ALIGN * h and -0.2 * h <= gap <= LINE_GAP * h


def link_tracks(samples):
    """the text instances of a run of samples ([{n, t, boxes}]): boxes linked from sample to sample (LINK_*), a track
    missing at most GAP_SAMPLES samples, then the tracks that are parts of one line joined (LINE_*).  Each track:
    samples (the indices of its samples), boxes (its box in each, the parts of a line joined), box (the median of
    them), vertical, first and last (frame numbers of its first and last sample)"""
    tracks = []
    for i, s in enumerate(samples):
        cands = []
        for ti, t in enumerate(tracks):
            if i - t["last_i"] > GAP_SAMPLES + 1:
                continue
            last = t["parts"][-1]
            px, py = last["cx"], last["cy"]
            if len(t["parts"]) >= 2:
                j0, j1 = t["samples"][-2], t["samples"][-1]
                prev = t["parts"][-2]
                px += (last["cx"] - prev["cx"]) / float(j1 - j0) * (i - j1)
                py += (last["cy"] - prev["cy"]) / float(j1 - j0) * (i - j1)
            for bi, b in enumerate(s["boxes"]):
                if b["vertical"] != last["vertical"]:
                    continue
                hr = max(b["h"], last["h"]) / max(1e-9, min(b["h"], last["h"]))
                if hr > LINK_HEIGHT:
                    continue
                ov = _overlap(b, last)
                d = math.hypot(b["cx"] - px, b["cy"] - py) / max(b["h"], last["h"])
                if ov >= LINK_OVERLAP:
                    cost = 1.0 - ov
                elif d <= LINK_REACH:
                    cost = 1.0 + d
                else:
                    continue
                cands.append((cost, ti, bi))
        used_t, used_b = set(), set()
        for cost, ti, bi in sorted(cands):
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            t = tracks[ti]
            t["samples"].append(i)
            t["parts"].append(s["boxes"][bi])
            t["last_i"] = i
        for bi, b in enumerate(s["boxes"]):
            if bi not in used_b:
                tracks.append({"samples": [i], "parts": [b], "last_i": i})
    # the parts of one line
    merged = True
    while merged:
        merged = False
        for a in range(len(tracks)):
            for b in range(a + 1, len(tracks)):
                ta, tb = tracks[a], tracks[b]
                both = sorted(set(ta["samples"]) & set(tb["samples"]))
                if len(both) < LINE_SHARE * min(len(ta["samples"]), len(tb["samples"])) or not both:
                    continue
                pa = dict(zip(ta["samples"], ta["parts"]))
                pb = dict(zip(tb["samples"], tb["parts"]))
                if not all(_same_line(pa[k], pb[k]) for k in both):
                    continue
                keys = sorted(set(pa) | set(pb))
                ta["samples"] = keys
                ta["parts"] = [_union([x for x in (pa.get(k), pb.get(k)) if x is not None]) for k in keys]
                del tracks[b]
                merged = True
                break
            if merged:
                break
    out = []
    for k, t in enumerate(sorted(tracks, key=lambda t: (t["samples"][0], t["parts"][0]["cy"]))):
        out.append({"id": k, "samples": t["samples"], "boxes": t["parts"], "box": _median_box(t["parts"]),
                    "vertical": bool(np.mean([p["vertical"] for p in t["parts"]]) >= 0.5),
                    "first": samples[t["samples"][0]]["n"], "last": samples[t["samples"][-1]]["n"]})
    return out


# ---- one track frame by frame ------------------------------------------------------------------------------------------
#
# The samples say roughly when a text is there.  Its own frames say how it comes and goes: every frame of the windows
# round its first and its last sample (and every MID_EVERY-th frame between them) is read in a band round it, the
# detector finds it there, and its strokes (from its clearest frame, the reference) are followed through the frames:
# where they are (a move, a zoom), how strong they stand out from what is round them (a fade: the strokes' contrast
# against the reference's, per character: one character after another), how sharp their edges are (a blur).

MID_RATE = 10.0                   # frames a second read between the windows (the hold)
BAND = 1.25                       # heights above and below a line (or beside a column) the band reaches
ALPHA_SEEN = 0.15                 # a text is seen when its strokes stand out by this share of the reference's
ALPHA_FULL = 0.85                 # ... and is whole from this share on
STILL = 0.03                      # heights a frame: a text moving less than this is still
STILL_SCALE = 0.006               # and growing or shrinking less than this a frame
MOVE_LEAST = (3.0, 0.15)          # px and heights: a text comes from at least the larger of these away to have moved
SCALE_LEAST = 1.15                # it comes at least this much larger or smaller to have zoomed
ROTATE_LEAST = 6.0                # degrees turned to have rotated
MATCH_REACH = 0.45                # a character found within this share of its size of where it should be is it
STAGGER_LEAST = 2                 # frames between the first and the last character to come one after another,
STAGGER_ORDER = 0.7               # with the order along the line at least this (Spearman)
BLUR_LEAST = 0.6                  # edges this much softer than the reference's while the strokes stand out: a blur
SHARP_FULL = 0.8                  # a text is whole only with its edges at least this sharp against the reference's


def refine_plan(track, samples, n_total, fps):
    """the frames to read for a track: every frame from just after the sample before its first to two samples after
    it and from two samples before its last to just before the sample after it, every MID_EVERY-th between"""
    step = samples[1]["n"] - samples[0]["n"] if len(samples) > 1 else max(1, int(round(fps / 2.0)))
    first, last = track["first"], track["last"]
    want = set(range(max(0, first - step + 1), min(n_total, first + 2 * step + 1)))
    want |= set(range(max(0, last - 2 * step), min(n_total, last + step)))
    every = max(1, int(round(fps / MID_RATE)))
    want |= set(range(first, last + 1, every))
    return sorted(n for n in want if 0 <= n < n_total)


def _luma(rgb):
    a = np.asarray(rgb, np.float64) / 255.0
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def _band(track, shape):
    """(x0, y0, x1, y1) of the band a track is looked for in: the whole width (a column: height) of the frame, BAND
    heights round where its samples saw it"""
    h_img, w_img = shape[:2]
    bx0 = min(b["x0"] for b in track["boxes"])
    by0 = min(b["y0"] for b in track["boxes"])
    bx1 = max(b["x1"] for b in track["boxes"])
    by1 = max(b["y1"] for b in track["boxes"])
    h = track["box"]["h"]
    if track["vertical"]:
        return (max(0, int(bx0 - BAND * h)), 0, min(w_img, int(math.ceil(bx1 + BAND * h))), h_img)
    return (0, max(0, int(by0 - BAND * h)), w_img, min(h_img, int(math.ceil(by1 + BAND * h))))


def _shift(box, dx, dy):
    b = dict(box)
    for k in ("x0", "x1", "cx"):
        b[k] += dx
    for k in ("y0", "y1", "cy"):
        b[k] += dy
    return b


def _find_in_band(boxes, ref, vertical):
    """the box of a band that is the track (ref: its median box): the line through it (the parts of one line joined),
    by overlap, else the nearest on its row (column) of a like height"""
    cands = [b for b in boxes if b["vertical"] == vertical and
             max(b["h"], ref["h"]) / max(1e-9, min(b["h"], ref["h"])) <= LINK_HEIGHT * 1.6]
    if not cands:
        return None
    best = max(cands, key=lambda b: _overlap(b, ref))
    if _overlap(best, ref) < LINK_OVERLAP:
        on_row = [b for b in cands if abs((b["cx"] if vertical else b["cy"]) - (ref["cx"] if vertical else ref["cy"]))
                  <= 0.6 * max(b["h"], ref["h"])]
        if not on_row:
            return None
        best = min(on_row, key=lambda b: abs((b["cy"] if vertical else b["cx"]) - (ref["cy"] if vertical else ref["cx"])))
    line = [best]
    grown = True
    while grown:
        grown = False
        for b in cands:
            if b not in line and any(_same_line(b, x) for x in line):
                line.append(b)
                grown = True
    return _union(line)


def _otsu(values):
    v = np.asarray(values, np.float64)
    if v.size < 2 or v.max() - v.min() < 1e-9:
        return float(v.mean()) if v.size else 0.0
    hist, edges = np.histogram(v, bins=64)
    mids = (edges[:-1] + edges[1:]) / 2.0
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids) / np.maximum(w0, 1)
    m1 = (np.sum(hist * mids) - np.cumsum(hist * mids)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(mids[int(np.argmax(between))])


def _ring(y, box, inner, outer):
    """Y' values in the ring between inner and outer heights round a box (clipped to the picture)"""
    h_img, w_img = y.shape
    h = box["h"]
    x0, y0 = int(max(0, box["x0"] - outer * h)), int(max(0, box["y0"] - outer * h))
    x1, y1 = int(min(w_img, box["x1"] + outer * h)), int(min(h_img, box["y1"] + outer * h))
    sub = y[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    out_in = ((xx < box["x0"] - inner * h) | (xx > box["x1"] + inner * h) |
              (yy < box["y0"] - inner * h) | (yy > box["y1"] + inner * h))
    return sub[out_in]


def stroke_mask(y, box, chars):
    """the strokes of a text in its box (Y' of the frame, 0..1): the pixels that differ from the ground round the box
    (the median of the ring 0.3 to 0.8 heights out) past Otsu's threshold, on the side the characters' middles lie.
    Returns (ys, xs, sign, ground): the strokes' pixels, +1 for text lighter than its ground, the ground's Y'"""
    h_img, w_img = y.shape
    pad = 0.15 * box["h"]
    x0, y0 = int(max(0, box["x0"] - pad)), int(max(0, box["y0"] - pad))
    x1, y1 = int(min(w_img, math.ceil(box["x1"] + pad))), int(min(h_img, math.ceil(box["y1"] + pad)))
    ring = _ring(y, box, 0.3, 0.8)
    ground = float(np.median(ring)) if ring.size else float(np.median(y))
    d = y[y0:y1, x0:x1] - ground
    # the side the text lies on: that of the pixels that differ most from the ground (not that of the characters'
    # middles: a hollow letter's middle is the ground)
    far = np.abs(d) >= np.percentile(np.abs(d), 90)
    sign = 1.0 if np.median(d[far]) >= 0 else -1.0
    d = d * sign
    th = max(_otsu(d.ravel()), 0.04)
    ys, xs = np.nonzero(d > th)
    return ys + y0, xs + x0, sign, ground


def _transform_points(px, py, centre, t, s):
    cx, cy = centre
    return cx + t[0] + s * (px - cx), cy + t[1] + s * (py - cy)


def _match(pred, peaks, reach):
    """one to one, the nearest first: pairs (i of pred, j of peaks) within reach"""
    if not len(pred) or not len(peaks):
        return []
    p = np.asarray(pred, np.float64)
    q = np.asarray([[c[0], c[1]] for c in peaks], np.float64)
    d = np.hypot(p[:, None, 0] - q[None, :, 0], p[:, None, 1] - q[None, :, 1])
    pairs, used_i, used_j = [], set(), set()
    for k in np.argsort(d, axis=None):
        i, j = divmod(int(k), d.shape[1])
        if d[i, j] > reach:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((i, j))
    return pairs


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def measure_track(frames, track, detector, fps, start=0.0, bounds=None):
    """how a track comes, stays and goes (see the section's comment).  frames: {n: RGB uint8} (at least those of
    refine_plan), track: one of link_tracks, detector: (score, link, ratio) of an RGB picture.  Returns a list of the
    lines found in the track's band (usually one: another line taking the place of the first is measured apart, see
    _segments), each with frames (first:
    the first seen, full: the first whole and still, hold_end: the last, last: the last seen), times (s, from `start`),
    enter and exit (frames, s, kinds: cut, fade, move, scale, rotate, stagger, blur; dx dy and from: where it came from;
    scale: its size then against its size at rest; stagger: the characters one after another), ref (the reference's
    box and characters) and series (per frame).  bounds: the first and last frame of the video read (a text still
    whole there has not come or gone: its phase is "none", cut_off); by default those of `frames`"""
    ns = sorted(frames)
    bounds = bounds or (ns[0], ns[-1])
    shape = frames[ns[0]].shape
    bx0, by0, bx1, by1 = _band(track, shape)
    ref_box = track["box"]
    vertical = track["vertical"]
    found = {}
    for n in ns:
        crop = np.ascontiguousarray(frames[n][by0:by1, bx0:bx1])
        score, link, ratio = detector(crop)
        boxes = [_shift(b, bx0, by0) for b in text_boxes(score, link, ratio)]
        peaks = [(c[0] + bx0, c[1] + by0, c[2], c[3]) for c in char_peaks(score, ratio)]
        b = _find_in_band(boxes, ref_box, vertical)
        if b is not None:
            m = 0.3 * b["h"]
            inside = [c for c in peaks if b["x0"] - m <= c[0] <= b["x1"] + m and b["y0"] - m <= c[1] <= b["y1"] + m]
        else:
            inside = []
        found[n] = (b, inside)
    out = []
    for part in _segments(frames, ns, found):
        m = _measure_segment(frames, part, found, track, fps, start, bounds)
        if m is not None:
            out.append(m)
    return out


SWAP_NCC = 0.5                    # a line whose strokes match the frame before less than this (normalised correlation),
SWAP_KEEP = 0.7                   # in this frame and the next, which match each other at least this, is another line


def _ink_region(y, box, pad=0.15):
    """(y0, y1, x0, x1) of a box and pad heights round it, clipped to the picture"""
    h = box["h"]
    return (int(max(0, box["y0"] - pad * h)), int(min(y.shape[0], math.ceil(box["y1"] + pad * h))),
            int(max(0, box["x0"] - pad * h)), int(min(y.shape[1], math.ceil(box["x1"] + pad * h))))


def _ncc_strokes(y_a, box_a, y_b, box_b):
    """how alike two frames' texts are: the normalised correlation of Y' over the strokes of the first (Otsu in its
    box, grown by 2 px) with the second read there, the second moved as best of: not at all, by the boxes' middles,
    by their left (top) ends, by their right (bottom) ends (a line that grows a character at a time keeps one end)"""
    sy, sx, _, _ = stroke_mask(y_a, box_a, [])
    if len(sy) < 8:
        return float("nan")
    on = np.zeros(y_a.shape, bool)
    on[sy, sx] = True
    on = _ndi().binary_dilation(on, iterations=2)
    y0, y1, x0, x1 = _ink_region(y_a, box_a)
    yy, xx = np.nonzero(on[y0:y1, x0:x1])
    yy, xx = yy + y0, xx + x0
    a = y_a[yy, xx]
    a = a - a.mean()
    shifts = {(0.0, 0.0), (box_b["cx"] - box_a["cx"], box_b["cy"] - box_a["cy"]),
              (box_b["x0"] - box_a["x0"], box_b["y0"] - box_a["y0"]), (box_b["x1"] - box_a["x1"], box_b["y1"] - box_a["y1"])}
    best = float("nan")
    for dx, dy in shifts:
        yb = np.clip(np.round(yy + dy).astype(int), 0, y_b.shape[0] - 1)
        xb = np.clip(np.round(xx + dx).astype(int), 0, y_b.shape[1] - 1)
        b = y_b[yb, xb]
        b = b - b.mean()
        den = math.sqrt(float((a * a).sum() * (b * b).sum()))
        r = float((a * b).sum() / den) if den > 1e-12 else float("nan")
        if np.isfinite(r) and not (r <= best):
            best = r
    return best


def _segments(frames, ns, found):
    """the frames of a track parted where another line takes its place (SWAP_*): a list of lists of frame numbers"""
    present = [n for n in ns if found[n][0] is not None]
    if not present:
        return []
    cuts = []
    ys = {}

    def y_of(n):
        if n not in ys:
            ys[n] = _luma(frames[n])
        return ys[n]

    for i in range(1, len(present)):
        a, b = present[i - 1], present[i]
        ba, bb = found[a][0], found[b][0]
        r = _ncc_strokes(y_of(a), ba, y_of(b), bb)
        if not (r < SWAP_NCC):
            continue
        if i + 1 < len(present):
            c = present[i + 1]
            r_ac = _ncc_strokes(y_of(a), ba, y_of(c), found[c][0])
            r_bc = _ncc_strokes(y_of(b), bb, y_of(c), found[c][0])
            if not (r_ac < SWAP_NCC and r_bc >= SWAP_KEEP):
                continue
        cuts.append(b)
    parts, cur = [], []
    edges = set(cuts)
    for n in ns:
        if n in edges and cur:
            parts.append(cur)
            cur = []
        cur.append(n)
    if cur:
        parts.append(cur)
    return [p for p in parts if any(found[n][0] is not None for n in p)]


def _measure_segment(frames, ns, found, track, fps, start, bounds):
    """measure_track for the frames ns of one line (see measure_track)"""
    vertical = track["vertical"]
    present = [n for n in ns if found[n][0] is not None]
    if not present:
        return None
    # the reference: the frame of the middle half of the present ones whose box is most like the median, the
    # strongest of those
    mid = present[len(present) // 4: max(len(present) // 4 + 1, 3 * len(present) // 4)]
    med = _median_box([found[n][0] for n in mid])

    def unlike(b):
        return (abs(b["cx"] - med["cx"]) + abs(b["cy"] - med["cy"])) / med["h"] + abs(b["h"] / med["h"] - 1) * 4 + \
            abs(b["w"] / med["w"] - 1) * 2

    ref_n = min(mid, key=lambda n: (round(unlike(found[n][0]), 2), -found[n][0]["score"]))
    rb, rchars = found[ref_n]
    y_ref = _luma(frames[ref_n])
    sy, sx, sign, ground = stroke_mask(y_ref, rb, rchars)
    # the strokes' inside (all four neighbours strokes too: a little off still reads the stroke) and their edge
    on = np.zeros(y_ref.shape, bool)
    on[sy, sx] = True
    core = on.copy()
    core[1:, :] &= on[:-1, :]
    core[:-1, :] &= on[1:, :]
    core[:, 1:] &= on[:, :-1]
    core[:, :-1] &= on[:, 1:]
    ey, ex = np.nonzero(on & ~core)
    cy_, cx_ = np.nonzero(core)
    if len(cy_) >= 0.2 * len(sy):
        sy, sx = cy_, cx_
    centre = (rb["cx"], rb["cy"])
    char_xy = np.array([[c[0], c[1]] for c in rchars], np.float64) if rchars else np.zeros((0, 2))
    if len(char_xy):
        own = np.argmin((sx[:, None] - char_xy[None, :, 0]) ** 2 + (sy[:, None] - char_xy[None, :, 1]) ** 2, axis=1)
        own_e = np.argmin((ex[:, None] - char_xy[None, :, 0]) ** 2 + (ey[:, None] - char_xy[None, :, 1]) ** 2, axis=1)
    else:
        own = np.zeros(len(sx), int)
        own_e = np.zeros(len(ex), int)
    n_chars = max(1, len(char_xy))
    ref_contrast = np.array([(y_ref[sy[own == k], sx[own == k]] - ground).mean() * sign if np.any(own == k) else np.nan
                             for k in range(n_chars)])
    grad_ref = _edge_sharpness(_grad(y_ref, 1.0), ey, ex)
    # each character's cell: the box and a quarter height round it, every pixel to the nearest character; its ink is
    # how much the cell stands out from the ground (a fade lowers it, a blur only spreads it)
    pad = 0.25 * rb["h"]
    gy_, gx_ = np.mgrid[int(max(0, rb["y0"] - pad)):int(min(y_ref.shape[0], rb["y1"] + pad + 1)),
                        int(max(0, rb["x0"] - pad)):int(min(y_ref.shape[1], rb["x1"] + pad + 1))]
    cy_all, cx_all = gy_.ravel(), gx_.ravel()
    if len(char_xy):
        own_c = np.argmin((cx_all[:, None] - char_xy[None, :, 0]) ** 2 + (cy_all[:, None] - char_xy[None, :, 1]) ** 2, axis=1)
    else:
        own_c = np.zeros(len(cx_all), int)
    ink_ref = np.array([((y_ref[cy_all[own_c == k], cx_all[own_c == k]] - ground) * sign).sum() for k in range(n_chars)])
    series = []
    t_prev, s_prev = (0.0, 0.0), 1.0
    reach = MATCH_REACH * (np.median([c[3] for c in rchars]) if rchars else rb["h"])
    for n in ns:
        b, peaks = found[n]
        hyps = [(t_prev, s_prev)]
        if b is not None:
            s_b = b["h"] / rb["h"]
            hyps.append(((b["cx"] - rb["cx"], b["cy"] - rb["cy"]), s_b))
            if vertical:
                hyps.append(((b["cx"] - rb["cx"], b["y0"] - centre[1] - s_b * (rb["y0"] - centre[1])), s_b))
                hyps.append(((b["cx"] - rb["cx"], b["y1"] - centre[1] - s_b * (rb["y1"] - centre[1])), s_b))
            else:
                hyps.append(((b["x0"] - centre[0] - s_b * (rb["x0"] - centre[0]), b["cy"] - rb["cy"]), s_b))
                hyps.append(((b["x1"] - centre[0] - s_b * (rb["x1"] - centre[0]), b["cy"] - rb["cy"]), s_b))
        best = None
        for t, s in hyps:
            px, py = _transform_points(char_xy[:, 0], char_xy[:, 1], centre, t, s) if len(char_xy) else ([], [])
            pairs = _match(list(zip(px, py)), peaks, reach * s)
            res = float(np.mean([math.hypot(px[i] - peaks[j][0], py[i] - peaks[j][1]) for i, j in pairs])) if pairs else 0.0
            key = (len(pairs), -res)
            if best is None or key > best[0]:
                best = (key, t, s, pairs)
        _, t, s, pairs = best
        if len(pairs) >= 3:
            # the size from how far apart the characters found lie against how far apart they lie at rest
            ia = np.array([i for i, _ in pairs])
            q = np.array([[peaks[j][0], peaks[j][1]] for _, j in pairs], np.float64)
            spread_ref = np.hypot(*(char_xy[ia] - char_xy[ia].mean(axis=0)).T).mean()
            spread_now = np.hypot(*(q - q.mean(axis=0)).T).mean()
            if spread_ref > 0.5 * rb["h"]:
                s = float(spread_now / spread_ref)
        if len(pairs) >= 2:
            px, py = _transform_points(char_xy[:, 0], char_xy[:, 1], centre, t, s)
            dx = float(np.median([peaks[j][0] - px[i] for i, j in pairs]))
            dy = float(np.median([peaks[j][1] - py[i] for i, j in pairs]))
            t = (t[0] + dx, t[1] + dy)
        elif b is None:
            t, s = t_prev, s_prev
        y = _luma(frames[n])
        mx, my = _transform_points(sx.astype(np.float64), sy.astype(np.float64), centre, t, s)
        inside = (mx >= 0) & (mx <= y.shape[1] - 1) & (my >= 0) & (my <= y.shape[0] - 1)
        mxi = np.clip(np.round(mx).astype(int), 0, y.shape[1] - 1)
        myi = np.clip(np.round(my).astype(int), 0, y.shape[0] - 1)
        here = dict(rb)
        here.update({"x0": centre[0] + t[0] + s * (rb["x0"] - centre[0]), "x1": centre[0] + t[0] + s * (rb["x1"] - centre[0]),
                     "y0": centre[1] + t[1] + s * (rb["y0"] - centre[1]), "y1": centre[1] + t[1] + s * (rb["y1"] - centre[1]),
                     "h": rb["h"] * s})
        ring = _ring(y, here, 0.3, 0.8)
        g = float(np.median(ring)) if ring.size else ground
        vals = (y[myi, mxi] - g) * sign
        alpha_k = np.array([vals[(own == k) & inside].mean() / ref_contrast[k]
                            if np.any((own == k) & inside) and ref_contrast[k] > 1e-6 else np.nan
                            for k in range(n_chars)])
        weight = float(np.nansum(np.clip(np.nan_to_num(ref_contrast), 0, None)))
        alpha = float(np.nansum(np.nan_to_num(alpha_k) * np.clip(np.nan_to_num(ref_contrast), 0, None)) / weight)             if weight > 1e-9 else 0.0
        seen = alpha_k[np.isfinite(alpha_k) & (alpha_k > 0.5)]
        alpha_vis = float(np.median(seen)) if seen.size else float(np.nanmax(alpha_k)) if np.isfinite(alpha_k).any() else 0.0
        # the edges of the characters that stand out, read on the gradient's highest within about a pixel of where they
        # should be (a stroke a little off still has its edge there)
        vis_k = np.nonzero(np.isfinite(alpha_k) & (alpha_k > 0.5))[0]
        ex_m, ey_m = _transform_points(ex.astype(np.float64), ey.astype(np.float64), centre, t, s)
        keep = np.isin(own_e, vis_k) & (ex_m >= 0) & (ex_m <= y.shape[1] - 1) & (ey_m >= 0) & (ey_m <= y.shape[0] - 1)
        if keep.any() and alpha_vis > 0:
            sharp = _edge_sharpness(_grad(y, s), np.round(ey_m[keep]).astype(int), np.round(ex_m[keep]).astype(int)) / \
                max(1e-9, grad_ref) / max(alpha_vis, 1e-3)
        else:
            sharp = float("nan")
        cxm, cym = _transform_points(cx_all.astype(np.float64), cy_all.astype(np.float64), centre, t, s)
        cin = (cxm >= 0) & (cxm <= y.shape[1] - 1) & (cym >= 0) & (cym <= y.shape[0] - 1)
        cv = (y[np.clip(np.round(cym).astype(int), 0, y.shape[0] - 1), np.clip(np.round(cxm).astype(int), 0, y.shape[1] - 1)] - g) * sign
        # a cell drawn s times larger holds s^2 times the ink: per pixel of the frame, not of the reference
        ink_k = np.array([cv[(own_c == k) & cin].sum() * s * s / ink_ref[k] if ink_ref[k] > 1e-6 and np.any((own_c == k) & cin)
                          else np.nan for k in range(n_chars)])
        vis_ink = ink_k[np.isfinite(ink_k) & (ink_k > 0.5)]
        ink_vis = float(np.median(vis_ink)) if vis_ink.size else (float(np.nanmax(ink_k)) if np.isfinite(ink_k).any() else 0.0)
        split_px, torn = _glitch(frames[n], y, frames[ref_n], y_ref, rb, t, s)
        series.append({"n": int(n), "present": b is not None, "tx": float(t[0]), "ty": float(t[1]), "s": float(s),
                       "split_px": split_px, "torn": torn,
                       "angle": float(b["angle"]) if b is not None else float("nan"), "alpha": alpha,
                       "alpha_vis": alpha_vis, "alpha_k": [float(a) for a in alpha_k], "matched": len(pairs),
                       "sharp": float(sharp), "ink_vis": ink_vis, "ink_k": [float(a) for a in ink_k]})
        t_prev, s_prev = t, s
    return _track_summary(series, track, rb, rchars, ref_n, fps, start, n_chars, bounds)


def _grad(y, scale=1.0):
    """the gradient's size (Y' a px), each pixel the highest within about a pixel (a scaled pixel) round it"""
    gy, gx = np.gradient(y)
    g = np.hypot(gx, gy)
    size = 3 if scale < 1.5 else 2 * int(round(scale)) + 1
    return _ndi().maximum_filter(g, size=size)


GLITCH_SPLIT = 2.0                # px between red and blue that change within a phase: a colour split
TEAR_SHIFT = 3                    # px: a row of the text moved sideways this much against the reference is torn
TEAR_SHARE = 0.08                 # a frame with this share of the text's rows torn is torn
SPLIT_REACH = 8                   # px searched for the colour split
TEAR_REACH = 12                   # px searched for a torn row


def _best_shift(a, b, reach):
    """the shift k (b[i] best matched by a[i + k]) of two profiles within reach, and its normalised correlation"""
    best = (0, -1.0)
    n = len(a)
    for k in range(-reach, reach + 1):
        if k >= 0:
            x, y = a[k:], b[:n - k]
        else:
            x, y = a[:n + k], b[-k:]
        if len(x) < 4:
            continue
        x = x - x.mean()
        y = y - y.mean()
        den = math.sqrt(float((x * x).sum() * (y * y).sum()))
        r = float((x * y).sum() / den) if den > 1e-12 else -1.0
        if r > best[1]:
            best = (k, r)
    return best


def _glitch(rgb, y, rgb_ref, y_ref, rb, t, s):
    """the colour split (px between the red and the blue edges across the text) and whether the frame is torn (a share
    of the text's rows moved sideways against the reference, read only at the reference's size) of a frame"""
    cx, cy = rb["cx"], rb["cy"]
    box = {"x0": cx + t[0] + s * (rb["x0"] - cx), "x1": cx + t[0] + s * (rb["x1"] - cx),
           "y0": cy + t[1] + s * (rb["y0"] - cy), "y1": cy + t[1] + s * (rb["y1"] - cy), "h": rb["h"] * s}
    y0, y1, x0, x1 = _ink_region(y, box, pad=0.3)
    if y1 - y0 < 4 or x1 - x0 < 2 * SPLIT_REACH + 4:
        return 0.0, 0
    crop = np.asarray(rgb[y0:y1, x0:x1], np.float64)
    gr = np.abs(np.diff(crop[..., 0], axis=1)).sum(axis=0)
    gb = np.abs(np.diff(crop[..., 2], axis=1)).sum(axis=0)
    k, r = _best_shift(gr, gb, SPLIT_REACH)
    split = float(abs(k)) if r > 0.3 else 0.0
    torn = 0
    if abs(s - 1.0) < 0.05:
        dx, dy = int(round(t[0])), int(round(t[1]))
        rows = tears = 0
        for row in range(y0, y1):
            rr = row - dy
            a0, a1 = x0 - dx - TEAR_REACH, x1 - dx + TEAR_REACH
            if not (0 <= rr < y_ref.shape[0]) or a0 < 0 or a1 > y_ref.shape[1]:
                continue
            now = y[row, x0:x1]
            if now.std() < 0.03:
                continue
            ref_row = y_ref[rr, a0:a1]
            best = (0, -2.0)
            for k2 in range(-TEAR_REACH, TEAR_REACH + 1):
                seg = ref_row[TEAR_REACH - k2: TEAR_REACH - k2 + (x1 - x0)]
                if len(seg) != len(now):
                    continue
                u, v = now - now.mean(), seg - seg.mean()
                den = math.sqrt(float((u * u).sum() * (v * v).sum()))
                rk = float((u * v).sum() / den) if den > 1e-12 else -1.0
                if rk > best[1]:
                    best = (k2, rk)
            rows += 1
            if abs(best[0]) >= TEAR_SHIFT and best[1] > 0.5:
                tears += 1
        torn = int(rows > 0 and tears / float(rows) >= TEAR_SHARE)
    return split, torn


def _edge_sharpness(g, ys, xs):
    """the gradient (from _grad) at the strokes' edge pixels: the middle of its highest half"""
    if len(ys) == 0:
        return float("nan")
    return float(np.percentile(g[ys, xs], 75))


def _track_summary(series, track, rb, rchars, ref_n, fps, start, n_chars, bounds):
    h = rb["h"]
    by_n = {r["n"]: r for r in series}
    ns = [r["n"] for r in series]
    k_ref = ns.index(ref_n)
    split_ref = series[k_ref]["split_px"]
    seen = [r["alpha"] > ALPHA_SEEN or r["present"] for r in series]
    still = []
    for i, r in enumerate(series):
        if i == 0:
            j = 1 if len(series) > 1 else 0
        else:
            j = i - 1
        dn = max(1, abs(series[j]["n"] - r["n"]))
        v = math.hypot(r["tx"] - series[j]["tx"], r["ty"] - series[j]["ty"]) / dn / h
        vs = abs(math.log(max(r["s"], 1e-6) / max(series[j]["s"], 1e-6))) / dn
        whole = r["ink_vis"] >= ALPHA_FULL and r["alpha"] >= ALPHA_FULL and             not (np.isfinite(r["sharp"]) and r["sharp"] < SHARP_FULL) and             abs(r["split_px"] - split_ref) < GLITCH_SPLIT and not r["torn"]
        still.append(whole and v < STILL and vs < STILL_SCALE)
    # the run of still frames round the reference, and of seen frames round that
    a = b = k_ref
    while a > 0 and still[a - 1]:
        a -= 1
    while b < len(series) - 1 and still[b + 1]:
        b += 1
    if not still[k_ref]:
        a = b = k_ref
    f0, f1 = a, b
    while f0 > 0 and seen[f0 - 1]:
        f0 -= 1
    while f1 < len(series) - 1 and seen[f1 + 1]:
        f1 += 1
    frames = {"first": ns[f0], "full": ns[a], "hold_end": ns[b], "last": ns[f1], "ref": ref_n}
    enter = _phase(series[f0:a + 1], series[a], h, fps, rchars, track["vertical"], entering=True,
                   cut_off=ns[f0] <= bounds[0] and still[f0])
    leave = _phase(series[b:f1 + 1], series[b], h, fps, rchars, track["vertical"], entering=False,
                   cut_off=ns[f1] >= bounds[1] and still[f1])
    times = {k: start + v / float(fps) for k, v in frames.items()}
    held = series[a:b + 1]
    dur = max(1, held[-1]["n"] - held[0]["n"]) / float(fps)
    hold = {"s": (held[-1]["n"] - held[0]["n"]) / float(fps),
            "split_px": float(np.median([r["split_px"] for r in held])),
            "torn_frames": int(sum(r["torn"] for r in held)),
            "drift_h_per_s": math.hypot(held[-1]["tx"] - held[0]["tx"], held[-1]["ty"] - held[0]["ty"]) / h / dur,
            "scale_change": held[-1]["s"] / max(held[0]["s"], 1e-9)}
    return {"frames": frames, "times": times, "enter": enter, "exit": leave, "hold": hold,
            "ref": {"box": rb, "chars": [list(c) for c in rchars]}, "series": series}


def _phase(part, rest, h, fps, chars, vertical, entering, cut_off=False):
    """how a text comes (entering: part runs from its first seen frame to its first whole still one, rest) or goes
    (part runs from its last still frame, rest, to its last seen).  cut_off: it is whole at the edge of what was read
    (it has not come or gone there)"""
    out = {"frames": max(0, part[-1]["n"] - part[0]["n"]) if part else 0, "cut_off": bool(cut_off)}
    out["s"] = out["frames"] / float(fps)
    if cut_off:
        out.update({"kinds": ["none"], "dx": 0.0, "dy": 0.0, "scale": 1.0, "rotate": 0.0, "from": None, "stagger": None,
                    "fade_s": 0.0, "glitch": {"split_px": 0.0, "split_var": 0.0, "torn_frames": 0, "flicker": 0}})
        return out
    kinds = []
    edge = part[0] if entering else part[-1]
    moving = [r for r in part if r is not rest]
    dx, dy = edge["tx"] - rest["tx"], edge["ty"] - rest["ty"]
    out.update({"dx": dx, "dy": dy, "scale": edge["s"] / max(rest["s"], 1e-9),
                "rotate": (edge["angle"] - rest["angle"]) if np.isfinite(edge["angle"]) and np.isfinite(rest["angle"]) else 0.0})
    if math.hypot(dx, dy) >= max(MOVE_LEAST[0], MOVE_LEAST[1] * h):
        kinds.append("move")
        if abs(dx) >= abs(dy):
            out["from"] = "left" if dx < 0 else "right"
        else:
            out["from"] = "above" if dy < 0 else "below"
    else:
        out["from"] = None
    if abs(math.log(max(out["scale"], 1e-6))) >= math.log(SCALE_LEAST):
        kinds.append("scale")
    if abs(out["rotate"]) >= ROTATE_LEAST:
        kinds.append("rotate")
    fading = [r for r in moving if ALPHA_SEEN < r["ink_vis"] < ALPHA_FULL]
    out["fade_s"] = 0.0
    if len(fading) >= 2:
        kinds.append("fade")
        ramp = [r for r in part if 0.1 < r["ink_vis"] < 0.9]
        if len(ramp) >= 2:
            slope = np.polyfit([r["n"] for r in ramp], [r["ink_vis"] for r in ramp], 1)[0]
            out["fade_s"] = float(1.0 / abs(slope) / fps) if abs(slope) > 1e-6 else float("nan")
    # the characters one after another: when each first stands out by half (entering) or last does (leaving)
    st = None
    if part and len(part[0]["alpha_k"]) >= 3:
        times = []
        for k in range(len(part[0]["alpha_k"])):
            ok = [r["n"] for r in part if np.isfinite(r["alpha_k"][k]) and r["alpha_k"][k] > 0.5]
            times.append((ok[0] if entering else ok[-1]) if ok else np.nan)
        times = np.array(times, np.float64)
        good = np.isfinite(times)
        if good.sum() >= 3:
            pos = np.array([c[1] if vertical else c[0] for c in chars], np.float64)[good] if len(chars) == len(times) \
                else np.arange(len(times), dtype=np.float64)[good]
            order = np.argsort(pos)
            tt = times[good][order]
            idx = np.arange(len(tt), dtype=np.float64)
            spread = float(tt.max() - tt.min())
            slope, icpt = np.polyfit(idx, tt, 1)
            fit = slope * idx + icpt
            ss_res = float(((tt - fit) ** 2).sum())
            ss_tot = float(((tt - tt.mean()) ** 2).sum())
            rho = _spearman(idx, tt)
            st = {"spread_frames": spread, "per_char_s": float(slope) / fps, "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0,
                  "rho": rho, "order": ("top_to_bottom" if slope > 0 else "bottom_to_top") if vertical else
                  ("left_to_right" if slope > 0 else "right_to_left")}
            if spread >= STAGGER_LEAST and abs(rho) >= STAGGER_ORDER:
                kinds.append("stagger")
    out["stagger"] = st
    splits = [r["split_px"] for r in moving]
    seen_now = [r["alpha"] > ALPHA_SEEN or r["present"] for r in part]
    flicker = sum(1 for i in range(1, len(seen_now) - 1) if seen_now[i - 1] and not seen_now[i] and seen_now[i + 1])
    out["glitch"] = {"split_px": float(max(splits)) if splits else 0.0,
                     "split_var": float(max(splits) - min(splits + [rest["split_px"]])) if splits else 0.0,
                     "torn_frames": int(sum(r["torn"] for r in moving)), "flicker": int(flicker)}
    if out["glitch"]["split_var"] >= GLITCH_SPLIT or out["glitch"]["torn_frames"] >= 1 or flicker >= 1:
        kinds.append("glitch")
    sharp = [r["sharp"] for r in moving if np.isfinite(r["sharp"]) and r["ink_vis"] > 0.5]
    if sharp and min(sharp) < BLUR_LEAST:
        kinds.append("blur")
    if not kinds:
        kinds = ["cut"] if out["frames"] <= 1 else ["other"]
    out["kinds"] = kinds
    return out


# ---- the command line --------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("detect", help="the text of sampled frames")
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--from", dest="start", type=float, default=None)
    p.add_argument("--to", dest="end", type=float, default=None)
    p.add_argument("--rate", type=float, default=2.0, help="frames sampled a second")
    p.add_argument("--height", type=int, default=540, help="lines the frames are read at")
    p.add_argument("--craft-onnx", default=None, help="an ONNX export of CRAFT (onnxruntime); without, torch")
    p.add_argument("--threads", type=int, default=3)
    p.add_argument("--matrix", default="auto", choices=("auto", "bt601", "bt709"))
    args = ap.parse_args(argv)
    if args.cmd == "detect":
        def log(text):
            print(text, flush=True)
        r = detect_video(args.video, args.out, start=args.start, end=args.end, rate=args.rate, height=args.height,
                         onnx=args.craft_onnx, threads=args.threads, matrix=args.matrix, log=log)
        print(json.dumps({"ok": True, "out": args.out, "samples": len(r["samples"]), "summary": r["summary"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
