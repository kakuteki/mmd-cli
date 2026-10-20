"""Measure the kinetic typography of a video in numbers: where and when its text comes and goes, how it moves, what it
looks like, and how it goes with the voice and the beat.

    python tools/typo_analyze.py detect VIDEO OUT.json [--from S] [--to S] [--rate 2] [--height 540]
                                        [--craft-onnx craft.onnx] [--threads 3]          # the text of sampled frames
    python tools/typo_analyze.py track VIDEO DETECT.json OUT.json [--craft-onnx ...] [--threads 3] [--no-style]
                                        # every text frame by frame: when and how it comes, stays and goes, its look
    python tools/typo_analyze.py voice VOCALS OUT.json [--accompaniment NO_VOCALS] [--offset S]
                                        # the voice's syllable onsets and phrases, the beat and the bar
    python tools/typo_analyze.py sync TRACK.json VOICE.json OUT.json      # the texts against the voice and the beat
    python tools/typo_analyze.py summary TRACK.json SYNC.json OUT.json [--voice VOICE.json] [--label NAME]
    python tools/typo_analyze.py compare OUT.md OUT.json --ref A.json ... --ours X.json ...   # TYPO_MEASURES side by side

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
    probe_out = info if not info.get("folder") else {k: v for k, v in info.items() if k != "files"}
    result = {"label": os.path.splitext(os.path.basename(path.rstrip("/").rstrip(os.sep)))[0], "path": path,
              "probe": probe_out, "range": [start, end], "fps": fps, "rate": rate, "height": int(size[1]),
              "size": list(size), "matrix": mat,
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
        chars = []
        for i, b in zip(t["samples"], t["parts"]):
            m = 0.3 * b["h"]
            chars.append([list(c) for c in samples[i].get("chars", [])
                          if b["x0"] - m <= c[0] <= b["x1"] + m and b["y0"] - m <= c[1] <= b["y1"] + m])
        out.append({"id": k, "samples": t["samples"], "ns": [samples[i]["n"] for i in t["samples"]], "boxes": t["parts"],
                    "chars": chars, "box": _median_box(t["parts"]),
                    "vertical": bool(np.mean([p["vertical"] for p in t["parts"]]) >= 0.5),
                    "first": samples[t["samples"][0]]["n"], "last": samples[t["samples"][-1]]["n"]})
    return out


# ---- one track frame by frame ------------------------------------------------------------------------------------------
#
# The samples say roughly when a text is there.  Its own frames say how it comes and goes: every frame of the windows
# round its first and its last sample (and some frames between them) is read in a band round it.  The text of its
# clearest sample (the reference: its box and characters from the detector) is followed through the frames by matching
# its picture (normalised correlation, at several sizes: a template; the detector is not run again, it costs about
# 0.2 s a frame on hinata's CPU against a few ms): where it is (a move, a zoom), how strongly its strokes stand out from
# what is round them (a fade: the strokes' contrast against the reference's, per character: one character after
# another), how sharp their edges are (a blur), and whether it moves with the picture behind it (text in the scene: a
# sign on a building) or stays put on the screen while that moves (text laid over the picture: lyrics).
# Turning (rotation) is not followed.

MID_RATE = 10.0                   # frames a second read between the windows (the hold)
BAND = 1.25                       # heights above and below a line (or beside a column) the band reaches
ALPHA_SEEN = 0.15                 # a text is seen when its strokes stand out by this share of the reference's
ALPHA_FULL = 0.85                 # ... and is whole from this share on
STILL = 0.03                      # heights a frame: a text moving less than this is still
STILL_SCALE = 0.006               # and growing or shrinking less than this a frame
MOVE_LEAST = (3.0, 0.15)          # px and heights: a text comes from at least the larger of these away to have moved
SCALE_LEAST = 1.15                # it comes at least this much larger or smaller to have zoomed
ROTATE_LEAST = 6.0                # degrees turned to have rotated
STAGGER_LEAST = 2                 # frames between the first and the last character to come one after another,
STAGGER_ORDER = 0.7               # with the order along the line at least this (Spearman)
BLUR_LEAST = 0.6                  # edges this much softer than the reference's while the strokes stand out: a blur
SHARP_FULL = 0.8                  # a text is whole only with its edges at least this sharp against the reference's


LONG_S = 20.0                     # s: a track longer than this (a watermark, a logo) is read once a second between
#                                   its windows


def refine_plan(track, samples, n_total, fps):
    """the frames to read for a track: every frame within two samples of its first and of its last sample, every
    round(fps / MID_RATE)-th between (once a second for a track longer than LONG_S)"""
    step = samples[1]["n"] - samples[0]["n"] if len(samples) > 1 else max(1, int(round(fps / 2.0)))
    first, last = track["first"], track["last"]
    # from two samples before the first (a faint text the detector missed at the sample before) to two after it, the
    # same round the last
    want = set(range(max(0, first - 2 * step + 1), min(n_total, first + 2 * step + 1)))
    want |= set(range(max(0, last - 2 * step), min(n_total, last + 2 * step)))
    every = max(1, int(round(fps / MID_RATE)))
    if last - first > LONG_S * fps:
        every = max(1, int(round(fps)))
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


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


TEMPLATE_PAD = 0.15               # heights round the reference's box in its template
PRESENT_NCC = 0.5                 # the template matches a frame at least this (normalised correlation): the text is there
LOCAL_SCALES = (0.94, 1.0, 1.06)  # sizes tried round the last frame's
GLOBAL_SCALES = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.12, 1.25, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0)
SWAP_NCC = 0.5                    # two samples of a track whose texts match less than this are two lines
BG_LEAST = 1.0                    # px a frame: the picture behind a text moves at least this to tell scene from screen
WORLD_SHARE = 0.6                 # a text that moves with the picture behind it in this share of those frames is in the
#                                   scene; one that stays put while it moves, laid over it (on the screen)


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
    k = box_b["h"] / max(1e-9, box_a["h"])                 # a text grown or shrunk between them
    ca = (box_a["cx"], box_a["cy"])
    ways = {(0.0, 0.0, 1.0), (box_b["cx"] - box_a["cx"], box_b["cy"] - box_a["cy"], 1.0),
            (box_b["x0"] - box_a["x0"], box_b["y0"] - box_a["y0"], 1.0), (box_b["x1"] - box_a["x1"], box_b["y1"] - box_a["y1"], 1.0),
            (box_b["cx"] - box_a["cx"], box_b["cy"] - box_a["cy"], k)}
    best = float("nan")
    for dx, dy, sc in ways:
        yb = np.clip(np.round(ca[1] + dy + sc * (yy - ca[1])).astype(int), 0, y_b.shape[0] - 1)
        xb = np.clip(np.round(ca[0] + dx + sc * (xx - ca[0])).astype(int), 0, y_b.shape[1] - 1)
        b = y_b[yb, xb]
        b = b - b.mean()
        den = math.sqrt(float((a * a).sum() * (b * b).sum()))
        r = float((a * b).sum() / den) if den > 1e-12 else float("nan")
        if np.isfinite(r) and not (r <= best):
            best = r
    return best


class _Template:
    """the picture of a text round its box on the reference frame, matched against other frames at a size s and an
    offset t of its middle: the box's middle lies at c + t on a frame where the text is s times as large"""

    def __init__(self, y_ref, box):
        y0, y1, x0, x1 = _ink_region(y_ref, box, TEMPLATE_PAD)
        self.img = np.ascontiguousarray(y_ref[y0:y1, x0:x1], np.float32)
        self.c = (box["cx"], box["cy"])
        self.off = (box["cx"] - x0, box["cy"] - y0)          # the box's middle inside the template
        self.h = box["h"]
        self._sized = {}

    def sized(self, s):
        key = round(s, 3)
        if key not in self._sized:
            cv2 = _cv2()
            th, tw = self.img.shape
            w, h = max(4, int(round(tw * s))), max(4, int(round(th * s)))
            self._sized[key] = cv2.resize(self.img, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        return self._sized[key]

    def match(self, y, s, around=None, reach=None):
        """(ncc, t) of the best place at size s: anywhere, or with the middle within reach px of `around`"""
        cv2 = _cv2()
        tm = self.sized(s)
        th, tw = tm.shape
        oy, ox = self.off[1] * s, self.off[0] * s
        if around is None:
            y0, x0, y1, x1 = 0, 0, y.shape[0], y.shape[1]
        else:
            cx, cy = around
            y0 = int(max(0, math.floor(cy - oy - reach)))
            x0 = int(max(0, math.floor(cx - ox - reach)))
            y1 = int(min(y.shape[0], math.ceil(cy - oy + th + reach)))
            x1 = int(min(y.shape[1], math.ceil(cx - ox + tw + reach)))
        sub = y[y0:y1, x0:x1]
        # a text partly out of the band (coming in from the side) matches with its outside part on the band's mean:
        # the band is padded by half the template where the search reaches its edge
        top = th // 2 if y0 == 0 else 0
        bottom = th // 2 if y1 == y.shape[0] else 0
        left = tw // 2 if x0 == 0 else 0
        right = tw // 2 if x1 == y.shape[1] else 0
        py, px = top, left
        if top or bottom or left or right:
            sub = cv2.copyMakeBorder(np.ascontiguousarray(sub, np.float32), top, bottom, left, right, cv2.BORDER_CONSTANT,
                                     value=float(sub.mean()))
        if sub.shape[0] < th or sub.shape[1] < tw:
            return -1.0, None
        r = cv2.matchTemplate(np.ascontiguousarray(sub, np.float32), tm, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(r)
        if not np.isfinite(val):
            return -1.0, None
        mx, my = x0 + loc[0] - px + ox, y0 + loc[1] - py + oy
        return float(val), (mx - self.c[0], my - self.c[1])

    def follow(self, y, t_prev, s_prev, speed, last_ncc=1.0):
        """(ncc, t, s) on a frame: near where the text was (sizes LOCAL_SCALES round its last), and anywhere in the band
        (GLOBAL_SCALES) when that matches under PRESENT_NCC or well under the last frame's match"""
        around = (self.c[0] + t_prev[0], self.c[1] + t_prev[1])
        reach = max(4.0, 0.8 * self.h * s_prev) + 2.0 * speed
        best = (-1.0, t_prev, s_prev)
        for k in LOCAL_SCALES:
            v, t = self.match(y, s_prev * k, around, reach)
            if t is not None and v > best[0]:
                best = (v, t, s_prev * k)
        if best[0] < max(PRESENT_NCC, 0.85 * last_ncc):
            for sc in GLOBAL_SCALES:
                v, t = self.match(y, sc)
                if t is not None and v > best[0]:
                    best = (v, t, sc)
        return best


def _sample_parts(ys, track):
    """the samples of a track parted where its text changes (another line in the same place): lists of the indices of
    its samples (SWAP_NCC between neighbours)"""
    parts = [[0]]
    for i in range(1, len(track["ns"])):
        a, b = track["ns"][i - 1], track["ns"][i]
        r = _ncc_strokes(ys[a], track["boxes"][i - 1], ys[b], track["boxes"][i]) if a in ys and b in ys else float("nan")
        if r < SWAP_NCC:
            parts.append([i])
        else:
            parts[-1].append(i)
    return parts


def _clarity(y, box):
    """how clearly a text stands on a frame: its strokes' contrast with the ground times the sharpness of their edges"""
    sy, sx, sign, ground = stroke_mask(y, box, [])
    if len(sy) < 8:
        return 0.0
    contrast = float(((y[sy, sx] - ground) * sign).mean())
    on = np.zeros(y.shape, bool)
    on[sy, sx] = True
    edge = on & ~_ndi().binary_erosion(on)
    ey, ex = np.nonzero(edge)
    g = _edge_sharpness(_grad(y, 1.0), ey, ex) if len(ey) else 0.0
    return max(0.0, contrast) * max(0.0, g)


def _ref_sample(track, idx, ys):
    """of the samples idx of a track, the reference: of the middle half of them (of all for three or fewer), those with
    nearly the most characters (a whole line, not one still coming a character at a time) and a box where most of the
    samples' boxes are (at rest, not still sliding in), the clearest (_clarity)"""
    pool = idx if len(idx) <= 3 else idx[len(idx) // 4: max(len(idx) // 4 + 1, 3 * len(idx) // 4)]
    most = max(len(track["chars"][i]) for i in pool)
    pool = [i for i in pool if len(track["chars"][i]) >= 0.8 * most]      # the whole line, not one still coming
    # at rest: its box where most of the samples' boxes are (not one still sliding in)
    med = _median_box([track["boxes"][i] for i in idx])

    def unlike(b):
        return (abs(b["cx"] - med["cx"]) + abs(b["cy"] - med["cy"])) / med["h"] + abs(b["h"] / med["h"] - 1) * 4
    least = min(unlike(track["boxes"][i]) for i in pool)
    pool = [i for i in pool if unlike(track["boxes"][i]) <= least + 0.3]
    clear = {i: _clarity(ys[track["ns"][i]], track["boxes"][i]) if track["ns"][i] in ys else 0.0 for i in pool}
    return max(pool, key=lambda i: clear[i])


def _follow_all(tmpl, ys, ns, ref_n):
    """{n: (ncc, t, s)} of a template followed from the reference frame forward and back through the frames ns (a frame
    where it is not found keeps the last place, with its low ncc)"""
    out = {ref_n: (1.0, (0.0, 0.0), 1.0)}
    for order in ([n for n in ns if n > ref_n], [n for n in reversed(ns) if n < ref_n]):
        t_prev, s_prev, speed, n_prev, last = (0.0, 0.0), 1.0, 0.0, ref_n, 1.0
        for n in order:
            v, t, sc = tmpl.follow(ys[n], t_prev, s_prev, speed, last)
            if v >= PRESENT_NCC:
                speed = math.hypot(t[0] - t_prev[0], t[1] - t_prev[1]) / max(1, abs(n - n_prev))
                t_prev, s_prev, n_prev, last = t, sc, n, v
                out[n] = (v, t, sc)
            else:
                out[n] = (v, t_prev, s_prev)
    return out


def measure_track(frames, track, fps, start=0.0, bounds=None, origin=(0, 0), frame_shape=None):
    """how a track comes, stays and goes (see the section's comment).  frames: {n: RGB uint8} (at least those of
    refine_plan), whole frames or pieces of them whose top left corner is at `origin` of a frame `frame_shape` (H, W)
    big (they must hold the track's band, see _band); track: one of link_tracks.  Returns a list of the lines found in
    the track (usually one: another line taking the place of the first is measured apart), each with frames (first: the
    first seen, full: the first whole and still, hold_end: the last, last: the last seen), times (s, from `start`), enter
    and exit (frames, s, kinds: cut, fade, move, scale, stagger, blur, glitch; dx dy and from: where it came from;
    scale: its size then against its size at rest; stagger: the characters one after another; glitch), hold, space
    (whether it moves with the picture behind it), ref (the reference's box and characters, in the frame's px) and
    series (per frame).  bounds: the first and last frame of the video read (a text still whole there has not come or
    gone: its phase is "none", cut_off); by default those of `frames`"""
    ns = sorted(frames)
    bounds = bounds or (ns[0], ns[-1])
    shape = frame_shape or frames[ns[0]].shape[:2]
    bx0, by0, bx1, by1 = _band(track, shape)
    ox, oy = origin
    band = {n: np.ascontiguousarray(frames[n][by0 - oy:by1 - oy, bx0 - ox:bx1 - ox]) for n in ns}
    ys = {n: _luma(band[n]) for n in ns}
    tb = dict(track)
    tb["boxes"] = [_shift(b, -bx0, -by0) for b in track["boxes"]]
    tb["box"] = _shift(track["box"], -bx0, -by0)
    tb["chars"] = [[[c[0] - bx0, c[1] - by0] + list(c[2:]) for c in cs] for cs in track.get("chars", [[] for _ in track["boxes"]])]
    tb["ns"] = track.get("ns") or [track["first"]]
    have = [i for i, n in enumerate(tb["ns"]) if n in ys]
    if not have:
        return []
    parts = [[i for i in p if i in have] for p in _sample_parts(ys, {"ns": tb["ns"], "boxes": tb["boxes"]})]
    parts = [p for p in parts if p]
    refs = [_ref_sample(tb, p, ys) for p in parts]
    tmpls = [_Template(ys[tb["ns"][r]], tb["boxes"][r]) for r in refs]
    # the frames of each part: up to where the next part's text matches better than this part's
    edges = []
    for k in range(len(parts) - 1):
        a, b = tb["ns"][parts[k][-1]], tb["ns"][parts[k + 1][0]]
        between = [n for n in ns if a < n < b]
        cut = b
        if between:
            fa = _follow_all(tmpls[k], ys, between, a)
            fb = _follow_all(tmpls[k + 1], ys, between, b)
            for n in between:
                if fb[n][0] > fa[n][0]:
                    cut = n
                    break
        edges.append(cut)
    out = []
    for k, p in enumerate(parts):
        lo = edges[k - 1] if k > 0 else ns[0]
        hi = edges[k] - 1 if k < len(edges) else ns[-1]
        part_ns = [n for n in ns if lo <= n <= hi]
        ref_i = refs[k]
        m = _measure_segment(band, ys, part_ns, tb, ref_i, tmpls[k], fps, start, bounds)
        if m is not None:
            m["ref"]["box"] = _shift(m["ref"]["box"], bx0, by0)
            m["ref"]["chars"] = [[c[0] + bx0, c[1] + by0] + list(c[2:]) for c in m["ref"]["chars"]]
            m["band"] = [int(bx0), int(by0), int(bx1), int(by1)]
            m["track"] = track.get("id")
            out.append(m)
    return out


def _background_shift(y_a, y_b, box):
    """how the picture behind a text moves from one frame to the next (px, and the phase correlation's response): the
    frames' band with the text's box (grown by half its height) filled with the band's mean"""
    cv2 = _cv2()
    a = np.array(y_a, np.float32)
    b = np.array(y_b, np.float32)
    h = box["h"]
    y0, y1 = int(max(0, box["y0"] - 0.5 * h)), int(min(a.shape[0], box["y1"] + 0.5 * h))
    x0, x1 = int(max(0, box["x0"] - 0.5 * h)), int(min(a.shape[1], box["x1"] + 0.5 * h))
    a[y0:y1, x0:x1] = a.mean()
    b[y0:y1, x0:x1] = b.mean()
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    return float(dx), float(dy), float(resp)


def _measure_segment(frames, ys, ns, track, ref_i, tmpl, fps, start, bounds):
    """measure_track for the frames ns of one line, its reference the sample ref_i of the track"""
    if not ns:
        return None
    ref_n = track["ns"][ref_i]
    if ref_n not in ns:
        return None
    rb = track["boxes"][ref_i]
    rchars = [tuple(c) for c in track["chars"][ref_i]]
    y_ref = ys[ref_n]
    sy, sx, sign, ground = stroke_mask(y_ref, rb, rchars)
    if len(sy) < 4:
        return None
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
    followed = _follow_all(tmpl, ys, ns, ref_n)
    series = []
    prev = None
    for n in ns:
        ncc, t, s = followed[n]
        y = ys[n]
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
        alpha = float(np.nansum(np.nan_to_num(alpha_k) * np.clip(np.nan_to_num(ref_contrast), 0, None)) / weight) \
            if weight > 1e-9 else 0.0
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
        row = {"n": int(n), "present": bool(ncc >= PRESENT_NCC), "ncc": float(ncc), "tx": float(t[0]), "ty": float(t[1]),
               "s": float(s), "split_px": split_px, "torn": torn, "angle": float("nan"), "alpha": alpha,
               "alpha_vis": alpha_vis, "alpha_k": [float(a) for a in alpha_k], "sharp": float(sharp),
               "ink_vis": ink_vis, "ink_k": [float(a) for a in ink_k], "bg_dx": float("nan"), "bg_dy": float("nan")}
        if prev is not None and n - prev == 1:
            bdx, bdy, resp = _background_shift(ys[prev], y, here)
            row.update({"bg_dx": bdx, "bg_dy": bdy, "bg_resp": resp})
        series.append(row)
        prev = n
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
    # scene or screen: in the frames where the picture behind it moves, does the text move with it or stay put
    follows = stays = moving = 0
    for i in range(1, len(series)):
        r, q = series[i], series[i - 1]
        if r["n"] - q["n"] != 1 or not (r["present"] and q["present"]) or not np.isfinite(r["bg_dx"]):
            continue
        bg = math.hypot(r["bg_dx"], r["bg_dy"])
        if bg < BG_LEAST:
            continue
        moving += 1
        tdx, tdy = r["tx"] - q["tx"], r["ty"] - q["ty"]
        tol = max(0.75, 0.35 * bg)
        if math.hypot(tdx - r["bg_dx"], tdy - r["bg_dy"]) <= tol:
            follows += 1
        elif math.hypot(tdx, tdy) <= tol:
            stays += 1
    space = {"frames": moving, "follows": follows / float(moving) if moving else float("nan"),
             "stays": stays / float(moving) if moving else float("nan")}
    space["kind"] = ("scene" if moving and space["follows"] >= WORLD_SHARE else
                     "screen" if moving and space["stays"] >= WORLD_SHARE else "unknown")
    hold = {"s": (held[-1]["n"] - held[0]["n"]) / float(fps),
            "split_px": float(np.median([r["split_px"] for r in held])),
            "torn_frames": int(sum(r["torn"] for r in held)),
            "drift_h_per_s": math.hypot(held[-1]["tx"] - held[0]["tx"], held[-1]["ty"] - held[0]["ty"]) / h / dur,
            "scale_change": held[-1]["s"] / max(held[0]["s"], 1e-9)}
    return {"frames": frames, "times": times, "enter": enter, "exit": leave, "hold": hold, "space": space,
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


# ---- the look of a text: its colour, outline, shadow, glow, plate; its typeface --------------------------------------
#
# Read on one frame at the video's own size (thin outlines are 1 to 3 px there), in a text's box: the ground is the
# colour round the box (the ring 0.6 to 1.2 heights out); the strokes are the pixels whose colour (CIELAB) lies far from
# the ground (past Otsu's threshold); inside the strokes, the deep pixels (3 px or more from the ground) are the fill
# and the band at their edge (1 to 2 px) tells an outline (another colour all round) from a drop shadow (another
# colour on one side: the edge pixels of that colour all face one way); outside them, the light that falls off with the
# distance from the strokes is a glow; strokes round holes of the ground larger than themselves are hollow letters.

STYLE_GROUND = (0.6, 1.2)         # heights out from the box: the ring whose colour is the ground
STYLE_PAD = 0.3                   # heights round the box where the strokes are looked for
DEEP = 3.0                        # px into the strokes: the fill
EDGE_BAND = (1.0, 2.5)            # px into the strokes: the edge band (an outline, a shadow's side)
OUTLINE_DE = 15.0                 # CIEDE76 between the edge band and the fill for another colour at the edge
SHADOW_ONE_WAY = 0.35             # the edge pixels of that colour face one way at least this much (mean resultant
#                                   length of their directions): a shadow, under it an outline all round
GLOW_AT = (2.0, 5.0)              # px out from the strokes where the glow is read, against the fill's rise
HOLLOW = 0.8                      # holes of the ground inside the strokes this many times the strokes' area: hollow


def _lab(rgb):
    return _tool("look_analyze").rgb_to_lab(np.asarray(rgb, np.float64) / 255.0)


def _hue(a, b):
    return float(math.degrees(math.atan2(b, a)))


def _off_segment(lab, p, q):
    """CIELAB distance of every pixel from the segment between the colours p and q (the mixes of a text's fill and its
    ground at an anti-aliased edge or in its glow lie on it; an outline's or a shadow's colour does not)"""
    d = q - p
    t = np.clip(((lab - p) * d).sum(axis=-1) / max(float((d * d).sum()), 1e-9), 0.0, 1.0)
    return np.sqrt(((lab - (p + t[..., None] * d)) ** 2).sum(axis=-1))


def text_style(rgb, box):
    """the look of a text on one frame (RGB uint8 at the video's size, box in its px): fill_L fill_C fill_hue fill_rgb
    (the fill's CIELAB lightness, chroma and hue angle, and its colour), contrast_L (fill against ground), outline (and
    outline_L outline_C outline_hue outline_px), shadow (and shadow_dx shadow_dy shadow_strength), glow (the light 2 to 5
    px out from the strokes as a share of the fill's rise over the ground) and glow_px (where it falls to half), hollow,
    ground_L ground_rgb"""
    ndi = _ndi()
    a = np.asarray(rgb, np.uint8)
    h_img, w_img = a.shape[:2]
    hb = max(2.0, box["h"])
    x0 = int(max(0, box["x0"] - STYLE_GROUND[1] * hb))
    y0 = int(max(0, box["y0"] - STYLE_GROUND[1] * hb))
    x1 = int(min(w_img, math.ceil(box["x1"] + STYLE_GROUND[1] * hb)))
    y1 = int(min(h_img, math.ceil(box["y1"] + STYLE_GROUND[1] * hb)))
    sub = a[y0:y1, x0:x1]
    lab = _lab(sub)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    ring_in = ((xx < box["x0"] - STYLE_GROUND[0] * hb) | (xx > box["x1"] + STYLE_GROUND[0] * hb) |
               (yy < box["y0"] - STYLE_GROUND[0] * hb) | (yy > box["y1"] + STYLE_GROUND[0] * hb))
    near = ((xx >= box["x0"] - STYLE_PAD * hb) & (xx <= box["x1"] + STYLE_PAD * hb) &
            (yy >= box["y0"] - STYLE_PAD * hb) & (yy <= box["y1"] + STYLE_PAD * hb))
    ground = np.median(lab[ring_in], axis=0) if ring_in.any() else np.median(lab.reshape(-1, 3), axis=0)
    de = np.sqrt(((lab - ground) ** 2).sum(axis=2))
    th = max(_otsu(de[near]), 8.0)
    strokes = near & (de > th)
    # strokes cut off from the rest by a little (a shadow's own blobs) stay: the look is read on all of them
    out = {"ground_L": float(ground[0]), "ground_rgb": [int(v) for v in np.median(sub[ring_in], axis=0)] if ring_in.any()
           else [0, 0, 0]}
    if strokes.sum() < 20:
        out.update({"fill_L": float("nan"), "fill_C": float("nan"), "fill_hue": float("nan"), "outline": False,
                    "shadow": False, "glow": float("nan"), "glow_px": float("nan"), "hollow": False})
        return out
    # the depth into the strokes: across the 1 px seams where an outline's colour meets the fill's (their mix can be
    # the ground's colour) too
    depth = ndi.distance_transform_edt(ndi.binary_closing(strokes, iterations=1) | strokes)
    deep = strokes & (depth >= DEEP)
    if deep.sum() < 10:
        deep = strokes & (depth >= max(1.0, float(np.percentile(depth[strokes], 75))))
    # the fill: the colour of the deepest strokes (an outline lies at their edge, a drop shadow under them)
    deepest = strokes & (depth >= max(1.0, float(np.percentile(depth[strokes], 80))))
    fill = np.median(lab[deepest], axis=0)
    deep = deep & (np.sqrt(((lab - fill) ** 2).sum(axis=2)) < 2 * OUTLINE_DE)
    band = strokes & (depth >= EDGE_BAND[0]) & (depth <= EDGE_BAND[1])
    holes = ndi.binary_fill_holes(strokes) & ~strokes
    hollow = bool(holes.sum() >= HOLLOW * strokes.sum() and np.median(de[holes]) < OUTLINE_DE) if holes.any() else False
    if hollow:
        fill = np.median(lab[strokes & (depth >= 1.0)], axis=0)
    out.update({"fill_L": float(fill[0]), "fill_C": float(math.hypot(fill[1], fill[2])), "fill_hue": _hue(fill[1], fill[2]),
                "fill_rgb": [int(v) for v in np.median(sub[deep if not hollow else strokes], axis=0)],
                "contrast_L": float(fill[0] - ground[0]), "hollow": hollow})
    # the edge band: pixels of another colour than the fill, and which way they face
    other = band & (_off_segment(lab, ground, fill) > OUTLINE_DE)
    out.update({"outline": False, "shadow": False, "outline_px": 0.0, "shadow_dx": 0.0, "shadow_dy": 0.0,
                "shadow_strength": 0.0})
    if not hollow and other.sum() >= 0.25 * band.sum() and band.sum() > 20:
        oc = np.median(lab[other], axis=0)
        # the side each such pixel lies on: from the nearest fill pixel (deep) to it
        _, (iy, ix) = ndi.distance_transform_edt(~deep, return_indices=True)
        oy, ox = np.nonzero(other)
        vy = oy - iy[oy, ox]
        vx = ox - ix[oy, ox]
        norm = np.hypot(vx, vy)
        ok = norm > 0
        r = float(np.hypot((vx[ok] / norm[ok]).mean(), (vy[ok] / norm[ok]).mean())) if ok.any() else 0.0
        if r >= SHADOW_ONE_WAY:
            # the shadow: the offset that best lays the fill on the pixels of the shadow's colour
            # the shadow is the fill moved: the offset whose moved fill lands on shadow or fill (never on the ground)
            # and covers the most of the shadow's colour
            dark = (np.sqrt(((lab - oc) ** 2).sum(axis=2)) < OUTLINE_DE * 1.5) & near
            filled = (np.sqrt(((lab - fill) ** 2).sum(axis=2)) < OUTLINE_DE * 1.5) & near
            core = strokes & (np.sqrt(((lab - fill) ** 2).sum(axis=2)) < OUTLINE_DE * 1.5)
            ys_, xs_ = np.nonzero(core)
            best = (0, 0, -1.0)
            n_dark = max(1, int(dark.sum()))
            for dy in range(-10, 11):
                for dx in range(-10, 11):
                    if dx == 0 and dy == 0:
                        continue
                    ty, tx = ys_ + dy, xs_ + dx
                    ok = (ty >= 0) & (ty < dark.shape[0]) & (tx >= 0) & (tx < dark.shape[1])
                    if not ok.any():
                        continue
                    land = (dark[ty[ok], tx[ok]] | filled[ty[ok], tx[ok]]).mean()
                    cover = dark[ty[ok], tx[ok]].sum() / float(n_dark)
                    v = float(land * cover)
                    if v > best[2]:
                        best = (dx, dy, v)
            out.update({"shadow": True, "shadow_dx": float(best[0]), "shadow_dy": float(best[1]),
                        "shadow_strength": float(best[2]), "shadow_L": float(oc[0])})
        else:
            # the outline's width: how deep into the strokes its colour reaches (the depth whose pixels lie nearer the
            # outline's colour than the fill's)
            width = 0.0
            near_o = np.sqrt(((lab - oc) ** 2).sum(axis=2)) < np.sqrt(((lab - fill) ** 2).sum(axis=2))
            for d in np.arange(0.5, 12.0, 1.0):
                ring_d = strokes & (depth >= d) & (depth < d + 1.0)
                if ring_d.sum() < 5:
                    break
                share = float(near_o[ring_d].mean())
                width += share
                if share < 0.2:
                    break
            out.update({"outline": True, "outline_L": float(oc[0]), "outline_C": float(math.hypot(oc[1], oc[2])),
                        "outline_hue": _hue(oc[1], oc[2]), "outline_px": float(width)})
    # the glow: how much lighter (on the fill's side) the ground is near the strokes than far from them
    outside = ndi.distance_transform_edt(~strokes)
    yl = lab[..., 0]
    rise = fill[0] - ground[0]
    prof = []
    for d in np.arange(1.0, 25.0, 1.0):
        ringd = (outside >= d) & (outside < d + 1.0) & ~ring_in
        prof.append(float(np.median(yl[ringd]) - ground[0]) if ringd.sum() >= 10 else float("nan"))
    prof = np.array(prof)
    sgn = 1.0 if rise >= 0 else -1.0
    at = (np.arange(1.0, 25.0, 1.0) >= GLOW_AT[0]) & (np.arange(1.0, 25.0, 1.0) <= GLOW_AT[1])
    glow = float(np.nanmean(prof[at]) * sgn / abs(rise)) if abs(rise) > 1e-6 and np.isfinite(prof[at]).any() else 0.0
    out["glow"] = max(0.0, glow)
    half = None
    if np.isfinite(prof[1]) and prof[1] * sgn > 0:
        for i, v in enumerate(prof[1:], start=1):
            if np.isfinite(v) and v * sgn <= 0.5 * prof[1] * sgn:
                half = i + 1.0
                break
    out["glow_px"] = float(half) if half is not None else float("nan")
    return out


TYPE_HV = 0.62                    # horizontal strokes thinner than this share of the vertical ones: mincho.  Measured
#                                   on drawn text (48 to 120 px): gothic 0.72 to 0.97 (Noto Sans JP, Yu Gothic, Meiryo,
#                                   MS Gothic, BIZ UDGothic, HG Gothic M, HG Soei Kaku Pop, UD Digi Kyokasho), mincho 0.24 to
#                                   0.55 (Yu Mincho, MS Mincho, Noto Serif JP, HG Mincho B); BIZ UDMincho (0.77), the textbook
#                                   and brush faces (HG Kyokasho 0.77, HG Gyosho 0.81 to 0.86, HG Seikaisho 0.58 to 0.76) read
#                                   as gothic: the width of the strokes alone does not tell them


def typeface(rgb, box):
    """the typeface of a text on one frame from its strokes (as text_style finds them): weight (the median stroke
    width, measured across each stroke to a fraction of a pixel, over the text's height), hv (the horizontal strokes'
    width over the vertical ones': mincho draws its horizontals thin), uneven (how the width varies along the strokes
    and between them), class: gothic or mincho (TYPE_HV)"""
    ndi = _ndi()
    from skimage.morphology import skeletonize
    a = np.asarray(rgb, np.uint8)
    h_img, w_img = a.shape[:2]
    hb = max(2.0, box["h"])
    x0 = int(max(0, box["x0"] - STYLE_GROUND[1] * hb))
    y0 = int(max(0, box["y0"] - STYLE_GROUND[1] * hb))
    x1 = int(min(w_img, math.ceil(box["x1"] + STYLE_GROUND[1] * hb)))
    y1 = int(min(h_img, math.ceil(box["y1"] + STYLE_GROUND[1] * hb)))
    lab = _lab(a[y0:y1, x0:x1])
    yy, xx = np.mgrid[y0:y1, x0:x1]
    ring_in = ((xx < box["x0"] - STYLE_GROUND[0] * hb) | (xx > box["x1"] + STYLE_GROUND[0] * hb) |
               (yy < box["y0"] - STYLE_GROUND[0] * hb) | (yy > box["y1"] + STYLE_GROUND[0] * hb))
    near = ((xx >= box["x0"] - STYLE_PAD * hb) & (xx <= box["x1"] + STYLE_PAD * hb) &
            (yy >= box["y0"] - STYLE_PAD * hb) & (yy <= box["y1"] + STYLE_PAD * hb))
    ground = np.median(lab[ring_in], axis=0) if ring_in.any() else np.median(lab.reshape(-1, 3), axis=0)
    de = np.sqrt(((lab - ground) ** 2).sum(axis=2))
    strokes = near & (de > max(_otsu(de[near]), 8.0))
    out = {"weight": float("nan"), "hv": float("nan"), "uneven": float("nan"), "class": None}
    if strokes.sum() < 50:
        return out
    full = float(np.percentile(de[strokes], 90))
    soft = np.clip(de / max(full, 1e-6), 0.0, 1.0) * near          # each pixel's share covered by the strokes
    rows = np.nonzero(strokes.any(axis=1))[0] if not box.get("vertical") else np.nonzero(strokes.any(axis=0))[0]
    tall = float(np.percentile(rows, 98) - np.percentile(rows, 2) + 1) if len(rows) else hb
    depth = ndi.distance_transform_edt(strokes)
    skel = skeletonize(strokes)
    nb = ndi.convolve(skel.astype(np.int32), np.ones((3, 3), np.int32), mode="constant") - skel
    plain = skel & (nb == 2)                              # on a stroke: away from its ends and joints
    widths = 2.0 * depth[plain] - 1.0
    if widths.size < 20:
        return out
    # the stroke's direction from the structure tensor of the strokes (smoothed over about a stroke's width)
    f = strokes.astype(np.float64)
    gy, gx = np.gradient(ndi.gaussian_filter(f, 1.0))
    sig = max(1.5, float(np.median(widths)))
    jxx = ndi.gaussian_filter(gx * gx, sig)
    jyy = ndi.gaussian_filter(gy * gy, sig)
    jxy = ndi.gaussian_filter(gx * gy, sig)
    across = 0.5 * np.degrees(np.arctan2(2 * jxy, jxx - jyy))          # the direction across the stroke
    ang = np.abs(across[plain])                                       # 0: across is horizontal (a vertical stroke)
    # each width again, to a fraction of a pixel: the covered shares summed along the line across the stroke through
    # the skeleton pixel, as far as the stroke goes on each side
    py, px = np.nonzero(plain)
    th = np.radians(across[plain])
    reach = max(4.0, 2.0 * float(np.median(widths)) + 2.0)
    ts = np.arange(-reach, reach + 0.25, 0.5)
    sy = py[:, None] + np.sin(th)[:, None] * ts[None, :]
    sx = px[:, None] + np.cos(th)[:, None] * ts[None, :]
    vals = ndi.map_coordinates(soft, [sy.ravel(), sx.ravel()], order=1, mode="constant").reshape(sy.shape)
    mid = len(ts) // 2
    keep = np.ones_like(vals, bool)
    for side in (range(mid + 1, len(ts)), range(mid - 1, -1, -1)):
        gone = np.zeros(len(py), bool)
        for j in side:
            gone |= vals[:, j] < 0.1
            keep[:, j] &= ~gone
    widths = (vals * keep).sum(axis=1) * 0.5
    vert = widths[ang < 20.0]
    horiz = widths[ang > 70.0]
    weight = float(np.median(widths)) / tall
    hv = float(np.median(horiz) / np.median(vert)) if horiz.size >= 10 and vert.size >= 10 else float("nan")
    # unevenness along the strokes: the spread of the width against its local mean along the skeleton
    wmap = np.zeros(strokes.shape)
    wmap[plain] = widths
    cnt = ndi.uniform_filter(plain.astype(np.float64), 7)
    loc = ndi.uniform_filter(wmap, 7) / np.maximum(cnt, 1e-9)
    dev = (wmap[plain] - loc[plain]) / np.maximum(loc[plain], 1e-9)
    uneven = float(np.std(dev) + np.std(widths) / max(np.mean(widths), 1e-9))
    cls = "mincho" if np.isfinite(hv) and hv < TYPE_HV else "gothic"
    out.update({"weight": weight, "hv": hv, "uneven": uneven, "class": cls, "height_px": tall,
                "stroke_px": float(np.median(widths))})
    return out


# ---- a whole video: every track of a detect run, read frame by frame --------------------------------------------------

def iter_frames(path, info, height, matrix, start=0.0, duration=None):
    """(n, RGB uint8) of every frame of a video (or a folder of frames) from `start`, read at `height` lines (None: its
    own size) as tools/look_analyze.py reads them"""
    LA = _tool("look_analyze")
    if info.get("folder"):
        from PIL import Image
        first = int(round((start or 0.0) * info["fps"]))
        last = len(info["files"]) if not duration else min(len(info["files"]), first + int(round(duration * info["fps"])))
        for k, f in enumerate(info["files"][first:last]):
            with Image.open(os.path.join(path, f)) as im:
                im = im.convert("RGB")
                if height and im.size[1] != height:
                    im = im.resize(LA._scale(info, height), Image.BOX if height < im.size[1] else Image.BICUBIC)
                yield k, np.asarray(im, np.uint8)
        return
    vf, size = LA._vf(info, height, matrix)
    pre, post = LA._range_args(start, duration)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", path] + post + \
           ["-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    for k, a in enumerate(LA._ffmpeg_frames(argv, size)):
        yield k, a


def _place(box, picture):
    """where a box lies in the picture inside the bars, and how big it is: x, y (its middle as shares of the picture's
    width and height), h (its short side, the size of its characters, as a share of the picture's height), w (its long
    side as a share of the picture's width, or of its height for a column)"""
    x0, y0, x1, y1 = picture
    pw, ph = float(x1 - x0), float(y1 - y0)
    return {"x": (box["cx"] - x0) / pw, "y": (box["cy"] - y0) / ph, "h": box["h"] / ph,
            "w": box["w"] / (ph if box.get("vertical") else pw)}


def _compact(series):
    out = []
    for r in series:
        c = {}
        for k, v in r.items():
            if isinstance(v, float):
                c[k] = round(v, 4) if np.isfinite(v) else None
            elif isinstance(v, list):
                c[k] = [round(x, 3) if isinstance(x, float) and np.isfinite(x) else (None if isinstance(x, float) else x)
                        for x in v]
            else:
                c[k] = v
        out.append(c)
    return out


def track_video(path, det, out=None, detector=None, onnx=None, threads=3, style=True, log=None):
    """every text of a video measured (see measure_track) from a detect run (det: its JSON as a dict), then the look of
    each (text_style, typeface) on its reference frame read at the video's own size.  OUT.json: the texts in the order
    they come, each with its place in the picture (_place), the times, the phases and the look"""
    LA = _tool("look_analyze")
    fps = det["fps"]
    info = LA.probe(path, fps=fps)
    start, end = det["range"]
    duration = end - start
    height = det["height"]
    read_height = None if height == info["height"] else height
    samples = det["samples"]
    tracks = link_tracks(samples)
    if info.get("folder"):
        total = len(info["files"]) - int(round(start * fps))
    else:
        total = int(math.floor(duration * fps + 1e-6))
    shape = (det["size"][1], det["size"][0])
    by_id = {t["id"]: t for t in tracks}
    plans = {t["id"]: refine_plan(t, samples, total, fps) for t in tracks}
    bands = {t["id"]: _band(t, shape) for t in tracks}
    need = {}
    for tid, plan in plans.items():
        for n in plan:
            need.setdefault(n, []).append(tid)
    last_n = {tid: (max(plan) if plan else -1) for tid, plan in plans.items()}
    buf = {tid: {} for tid in plans}
    texts = []
    t0 = time.time()

    def finish(tid):
        frames = buf.pop(tid)
        if not frames:
            return
        x0, y0 = bands[tid][:2]
        ms = measure_track(frames, by_id[tid], fps, start=start, bounds=(0, total - 1), origin=(x0, y0),
                           frame_shape=shape)
        texts.extend(ms)
        if log:
            log("track %d: %d frames, %d text(s), %.0f s" % (tid, len(frames), len(ms), time.time() - t0))

    for n, frame in iter_frames(path, info, read_height, det["matrix"], start, None if info.get("folder") else duration):
        for tid in need.get(n, ()):
            x0, y0, x1, y1 = bands[tid]
            buf[tid][n] = frame[y0:y1, x0:x1].copy()
        for tid in [t for t in list(buf) if last_n[t] <= n]:
            finish(tid)
    for tid in list(buf):
        finish(tid)
    texts.sort(key=lambda m: (m["frames"]["first"], m["ref"]["box"]["cy"]))
    for k, m in enumerate(texts):
        m["id"] = k
        m["place"] = _place(m["ref"]["box"], det["picture"])
        m["vertical"] = bool(m["ref"]["box"].get("vertical"))
        m["n_chars"] = len(m["ref"]["chars"])
        m["series"] = _compact(m["series"])
    if style and texts:
        refs = sorted(set(m["frames"]["ref"] for m in texts))
        scale = info["height"] / float(height)
        native = dict(LA.read_frames(path, info, refs, height=None, matrix=det["matrix"], start=start,
                                     duration=None if info.get("folder") else duration, as_uint8=True))
        for m in texts:
            a = native.get(m["frames"]["ref"])
            if a is None:
                continue
            b = dict(m["ref"]["box"])
            for k in ("x0", "y0", "x1", "y1", "cx", "cy", "w", "h"):
                b[k] = b[k] * scale
            m["style"] = text_style(a, b)
            m["typeface"] = typeface(a, b)
    result = {"label": det.get("label"), "path": path, "fps": fps, "range": [start, end], "height": height,
              "size": det["size"], "picture": det["picture"], "native": [info["width"], info["height"]],
              "tracks": len(tracks), "seconds": round(time.time() - t0, 1), "texts": texts}
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return result


# ---- the voice and the beat ------------------------------------------------------------------------------------------
#
# The voice: the separated singing (demucs htdemucs), read as tools/lip_check.py reads it (16 kHz, the power of 300 to
# 3500 Hz every 10 ms, its level against the song's 99th percentile, the syllable onsets).  A phrase is a run of the
# voice sounding (above PHRASE_DB) whose quiet gaps are shorter than PHRASE_GAP; it starts at its first onset when one
# lies just round the run's start.  The beat: librosa's beat tracker on the accompaniment (the song without the voice);
# the bar from the beat whose phase of four holds the most low (under 150 Hz) onset strength (the kick on one).

PHRASE_DB = -35.0                 # dB re the voice's 99th percentile: the voice sounds above this
PHRASE_GAP = 0.30                 # s: a quieter gap shorter than this stays inside the phrase
PHRASE_LEAST = 0.20               # s: a shorter run is no phrase
PHRASE_ONSET = (0.05, 0.15)       # s before and after a run's start where its first onset is taken as its start


def voice_events(x, sr=16000):
    """the onsets (s) of the syllables and the phrases ([start, end] s) of a separated voice (mono, at sr)"""
    LC = _tool("lip_check")
    x = np.asarray(x, np.float32)
    if sr != LC.SR:
        from scipy.signal import resample_poly
        g = math.gcd(int(sr), int(LC.SR))
        x = resample_poly(x, LC.SR // g, int(sr) // g).astype(np.float32)
    v = LC.Voice(x)
    onsets = LC.voice_onsets(v)
    on = v.level > PHRASE_DB
    step = LC.STEP
    runs = []
    k = 0
    n = len(on)
    while k < n:
        if not on[k]:
            k += 1
            continue
        j = k
        while j < n and on[j]:
            j += 1
        runs.append([k, j])
        k = j
    merged = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * step < PHRASE_GAP:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    phrases = []
    for a, b in merged:
        if (b - a) * step < PHRASE_LEAST:
            continue
        t0, t1 = a * step, b * step
        near = [o for o in onsets if t0 - PHRASE_ONSET[0] <= o <= t0 + PHRASE_ONSET[1]]
        phrases.append([float(near[0]) if near else float(t0), float(t1)])
    return {"onsets": [float(o) for o in onsets], "phrases": phrases, "step": step}


def beat_events(x, sr):
    """the tempo (bpm), the beats and the bar lines (downbeats, s) of an accompaniment (mono, at sr)"""
    import librosa
    y = np.asarray(x, np.float32)
    env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, units="frames", trim=False)
    beats = librosa.frames_to_time(frames, sr=sr)
    low = librosa.onset.onset_strength(y=y, sr=sr, fmax=150.0, n_mels=8)
    best, phase = -1.0, 0
    for k in range(4):
        idx = frames[k::4]
        idx = idx[idx < len(low)]
        v = float(low[idx].mean()) if len(idx) else 0.0
        if v > best:
            best, phase = v, k
    bpm = float(np.atleast_1d(tempo)[0])
    return {"bpm": bpm, "beats": [float(b) for b in beats], "downbeats": [float(b) for b in beats[phase::4]],
            "phase": phase}


def read_sound(path, sr=16000):
    """mono float32 of a sound file at sr (ffmpeg)"""
    import subprocess
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(int(sr)), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def voice_file(vocals, out=None, accompaniment=None, offset=0.0):
    """voice: the voice's onsets and phrases (and with the accompaniment, the beat) as OUT.json; offset (s) is added to
    every time (the sound and the video's frames on one clock)"""
    v = voice_events(read_sound(vocals, 16000), 16000)
    res = {"vocals": vocals, "onsets": [o + offset for o in v["onsets"]], "phrases": [[a + offset, b + offset] for a, b in v["phrases"]]}
    if accompaniment:
        b = beat_events(read_sound(accompaniment, 22050), 22050)
        res.update({"bpm": b["bpm"], "beats": [t + offset for t in b["beats"]], "downbeats": [t + offset for t in b["downbeats"]],
                    "accompaniment": accompaniment})
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


# ---- the text against the voice and the beat ---------------------------------------------------------------------------

PAIR_REACH = 1.5                  # s: a text and a phrase start further apart than this are not paired
MARK_SHARE = 0.4                  # a text on the screen this share of the video or more is a mark (a logo, a watermark)
LYRIC_OVERLAP = 0.3               # a text that holds the voice this share of its time (or is paired) is a lyric
BEAT_REACH = 0.01                 # s added to a frame either side: an event this near a beat is on it


def _stats(values):
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], np.float64)
    if not v.size:
        return {"n": 0, "median": float("nan"), "q25": float("nan"), "q75": float("nan")}
    return {"n": int(v.size), "median": float(np.median(v)), "q25": float(np.percentile(v, 25)),
            "q75": float(np.percentile(v, 75)), "mean": float(v.mean())}


def _on_beat(times, beats, fps):
    """the share of the times within a frame (and BEAT_REACH) of a beat, the chance of that for times spread evenly,
    and the phases (0..1 of the beat) of the times"""
    b = np.asarray(beats, np.float64)
    if b.size < 2 or not len(times):
        return {"share": float("nan"), "chance": float("nan"), "n": len(times), "phases": []}
    reach = 1.0 / fps + BEAT_REACH
    near, phases = [], []
    for t in times:
        k = int(np.searchsorted(b, t))
        d = min(abs(t - b[max(0, k - 1)]), abs(t - b[min(len(b) - 1, k)]))
        near.append(d <= reach)
        if 0 < k < len(b):
            phases.append(float((t - b[k - 1]) / (b[k] - b[k - 1])))
    period = float(np.median(np.diff(b)))
    return {"share": float(np.mean(near)), "chance": float(min(1.0, 2 * reach / period)), "n": len(times),
            "phases": phases}


def sync(texts, voice, beats=None, fps=30.0, duration=None):
    """each text against the voice and the beat: its kind (mark: on the screen MARK_SHARE of the video or more; lyric:
    paired with a phrase start within PAIR_REACH or holding the voice LYRIC_OVERLAP of its time; other), and for the
    lyrics: lead_s (the phrase's start less the text's first frame: + the text comes first), full_lead_s (the same from
    the frame it is whole), out_lag_s (its last frame less the phrase's end: + it stays after the voice); on_beat: the
    share of the lyrics' first frames on a beat against chance"""
    phrases = voice.get("phrases") or []
    starts = np.array([p[0] for p in phrases], np.float64)
    if duration is None:
        duration = max([t["times"]["last"] for t in texts] + [1.0])
    rows = []
    for t in texts:
        a, full, z = t["times"]["first"], t["times"]["full"], t["times"]["last"]
        row = {"first": a, "full": full, "last": z, "kind": "other", "phrase": None}
        if z - a >= MARK_SHARE * duration:
            row["kind"] = "mark"
            rows.append(row)
            continue
        held = sum(max(0.0, min(z, p[1]) - max(a, p[0])) for p in phrases)
        if starts.size:
            k = int(np.argmin(np.abs(starts - a)))
            if abs(starts[k] - a) <= PAIR_REACH:
                row["phrase"] = k
                row["lead_s"] = float(starts[k] - a)
                row["full_lead_s"] = float(starts[k] - full)
                row["out_lag_s"] = float(z - phrases[k][1])
        if row["phrase"] is not None or (z > a and held / (z - a) >= LYRIC_OVERLAP):
            row["kind"] = "lyric"
        rows.append(row)
    lyr = [r for r in rows if r["kind"] == "lyric"]
    paired = [r for r in lyr if r["phrase"] is not None]
    out = {"texts": rows, "paired": len(paired),
           "lead_s": _stats([r["lead_s"] for r in paired]), "full_lead_s": _stats([r["full_lead_s"] for r in paired]),
           "out_lag_s": _stats([r["out_lag_s"] for r in paired]),
           "lyric_share_paired": len(paired) / float(len(lyr)) if lyr else float("nan")}
    events = [r["first"] for r in (lyr if lyr else rows if not phrases else [])]
    out["on_beat"] = _on_beat(events, beats["beats"], fps) if beats and beats.get("beats") else \
        {"share": float("nan"), "chance": float("nan"), "n": 0, "phases": []}
    out["on_bar"] = _on_beat(events, beats["downbeats"], fps) if beats and beats.get("downbeats") else \
        {"share": float("nan"), "chance": float("nan"), "n": 0, "phases": []}
    return out


# ---- a video in a few numbers, and videos side by side -----------------------------------------------------------------

TYPO_CONCEPTS = ("amount", "place", "time", "enter", "exit", "look", "sync")
TYPO_CONCEPT_LABELS = {"amount": "量", "place": "置き場と大きさ", "time": "出ている時間", "enter": "入り", "exit": "出",
                       "look": "見た目と書体", "sync": "声と拍"}
KINDS = ("cut", "fade", "move", "scale", "rotate", "stagger", "blur", "glitch")
KIND_JA = {"cut": "切り替え（1 コマで出る）", "fade": "フェード", "move": "移動", "scale": "拡大縮小", "rotate": "回転",
           "stagger": "1 文字ずつ", "blur": "ぼかし", "glitch": "グリッチ"}
TYPO_MEASURES = {
    "typo.per_min": ("amount", "歌詞の行の数（歌っている間の 1 分あたり）", "行"),
    "typo.on_screen": ("amount", "歌っている間に歌詞が出ている時間の割合", ""),
    "typo.concurrent": ("amount", "同時に出ている歌詞の行の数（出ている間の時間で重みを付けた中央）", "行"),
    "typo.chars": ("amount", "1 行の文字の数", "字"),
    "typo.size": ("place", "文字の大きさ（字の高さ / 絵の高さ）", ""),
    "typo.x": ("place", "横の置き場（行の中心、左 0〜右 1）", ""),
    "typo.y": ("place", "縦の置き場（行の中心、上 0〜下 1）", ""),
    "typo.lower": ("place", "下 1/3 にある行の割合", ""),
    "typo.upper": ("place", "上 1/3 にある行の割合", ""),
    "typo.centred": ("place", "横の真ん中（0.4〜0.6）にある行の割合", ""),
    "typo.vertical": ("place", "縦書きの行の割合", ""),
    "typo.show_s": ("time", "1 行が見えている時間（出始めから消えるまで）", "秒"),
    "typo.hold_s": ("time", "1 行が止まって全部見えている時間", "秒"),
    "enter.s": ("enter", "入りの長さ（出始めから止まって全部見えるまで）", "秒"),
    "enter.fade_s": ("enter", "フェードの長さ（0 から 1 に換算、フェードの行だけ）", "秒"),
    "enter.move_h": ("enter", "移動の距離（字の高さの何倍、移動の行だけ）", ""),
    "enter.scale": ("enter", "出始めの大きさ / 止まった大きさ（拡大縮小の行だけ）", ""),
    "enter.stagger_s": ("enter", "1 文字ずつの遅れ（1 字あたり、1 文字ずつの行だけ）", "秒"),
    "exit.s": ("exit", "出の長さ（止まって全部見える最後から消えるまで）", "秒"),
    "hold.drift": ("time", "止まっている間のゆっくりした動き（字の高さ / 秒）", ""),
    "style.fill_L": ("look", "文字の塗りの明るさ（L*）", "L*"),
    "style.fill_C": ("look", "文字の塗りの彩度（C*ab）", "C*"),
    "style.contrast_L": ("look", "文字と下地の明るさの差（L*）", "L*"),
    "style.outline": ("look", "縁取りのある行の割合", ""),
    "style.outline_px": ("look", "縁取りの太さ（動画の大きさの画素、縁取りの行だけ）", "px"),
    "style.shadow": ("look", "落ち影のある行の割合", ""),
    "style.glow": ("look", "文字のまわりのグロー（2〜5 px 外の明るさ / 文字の明るさの上がり）", ""),
    "style.hollow": ("look", "中抜き（縁の線だけ）の行の割合", ""),
    "type.mincho": ("look", "明朝の行の割合（横画が縦画の 0.62 倍より細い）", ""),
    "type.weight": ("look", "書体の太さ（画の太さ / 字の高さ）", ""),
    "sync.lead_s": ("sync", "文字が出始める時刻の、歌い出しより前の時間（+ 先）", "秒"),
    "sync.full_lead_s": ("sync", "文字が全部見える時刻の、歌い出しより前の時間", "秒"),
    "sync.out_lag_s": ("sync", "文字が消える時刻の、歌い終わりより後の時間", "秒"),
    "sync.paired": ("sync", "歌い出しと組めた行の割合", ""),
    "sync.on_beat": ("sync", "出始めが拍の上（1 コマ以内）にある行の割合", ""),
    "sync.on_beat_chance": ("sync", "（拍の上に来る偶然の割合）", ""),
}
for _k in KINDS:
    TYPO_MEASURES["enter." + _k] = ("enter", "入りが%sの行の割合" % KIND_JA[_k], "")
    TYPO_MEASURES["exit." + _k] = ("exit", "出が%sの行の割合" % KIND_JA[_k], "")


def _share_stats(flags, seed=0):
    """a share as a summary entry: its mean, and the 2.5 and 97.5 % points of the mean over the texts drawn again"""
    v = np.asarray([1.0 if f else 0.0 for f in flags if f is not None], np.float64)
    if not v.size:
        return {"median": float("nan"), "q25": float("nan"), "q75": float("nan"), "n": 0, "valid": 0.0, "shots": 0,
                "floor_pair": float("nan"), "ci": [float("nan"), float("nan")]}
    rng = np.random.default_rng(seed)
    means = [v[rng.integers(0, v.size, v.size)].mean() for _ in range(400)]
    m = float(v.mean())
    return {"median": m, "q25": m, "q75": m, "n": int(v.size), "valid": 1.0, "shots": int(v.size),
            "floor_pair": float("nan"), "ci": [float(x) for x in np.percentile(means, [2.5, 97.5])]}


def _one(value, n=1):
    return {"median": float(value), "q25": float(value), "q75": float(value), "n": n, "valid": 1.0, "shots": 1,
            "floor_pair": float("nan"), "ci": [float(value), float(value)]}


def typo_summary(tr, sy, voice=None, seed=0):
    """the summary (TYPO_MEASURES, in look_analyze's form: median, quartiles, n, floor_pair, ci) of a video's lyrics
    from its track run (tr) and its sync run (sy, whose texts are in the order of tr's); the times are read to a frame
    (floor_pair 1 / fps)"""
    LA = _tool("look_analyze")
    fps = float(tr["fps"])
    kinds = [r["kind"] for r in sy["texts"]]
    lyr = [(t, r) for t, r in zip(tr["texts"], sy["texts"]) if r["kind"] == "lyric"]
    rows = []
    for t, r in lyr:
        m = {"typo.size": t["place"]["h"], "typo.x": t["place"]["x"], "typo.y": t["place"]["y"],
             "typo.chars": float(t.get("n_chars", 0)), "typo.show_s": t["times"]["last"] - t["times"]["first"],
             "typo.hold_s": t["hold"]["s"], "enter.s": t["enter"]["s"], "exit.s": t["exit"]["s"],
             "hold.drift": t["hold"]["drift_h_per_s"]}
        e = t["enter"]
        if "fade" in e["kinds"]:
            m["enter.fade_s"] = e.get("fade_s", float("nan"))
        if "move" in e["kinds"]:
            m["enter.move_h"] = math.hypot(e["dx"], e["dy"]) / max(1e-9, t["ref"]["box"]["h"])
        if "scale" in e["kinds"]:
            m["enter.scale"] = e["scale"]
        if "stagger" in e["kinds"] and e.get("stagger"):
            m["enter.stagger_s"] = abs(e["stagger"]["per_char_s"])
        st = t.get("style") or {}
        for k in ("fill_L", "fill_C", "contrast_L", "glow"):
            if st.get(k) is not None:
                m["style." + k] = st[k]
        if st.get("outline"):
            m["style.outline_px"] = st.get("outline_px", float("nan"))
        ty = t.get("typeface") or {}
        if ty.get("weight") is not None:
            m["type.weight"] = ty["weight"]
        for k in ("lead_s", "full_lead_s", "out_lag_s"):
            if k in r:
                m["sync." + k] = r[k]
        rows.append({"m": {k: (float(v) if v is not None else float("nan")) for k, v in m.items()}, "shot": t["id"]})
    summary = LA.summarise(rows, seed=seed) if rows else {}
    for k in ("typo.show_s", "typo.hold_s", "enter.s", "exit.s", "enter.fade_s", "enter.stagger_s", "sync.lead_s",
              "sync.full_lead_s", "sync.out_lag_s"):
        if k in summary:
            summary[k]["floor_pair"] = 1.0 / fps
    texts = [t for t, _ in lyr]
    for k in KINDS:
        summary["enter." + k] = _share_stats([k in t["enter"]["kinds"] for t in texts if t["enter"]["kinds"] != ["none"]], seed)
        summary["exit." + k] = _share_stats([k in t["exit"]["kinds"] for t in texts if t["exit"]["kinds"] != ["none"]], seed)
    summary["typo.lower"] = _share_stats([t["place"]["y"] > 2 / 3.0 for t in texts], seed)
    summary["typo.upper"] = _share_stats([t["place"]["y"] < 1 / 3.0 for t in texts], seed)
    summary["typo.centred"] = _share_stats([0.4 <= t["place"]["x"] <= 0.6 for t in texts], seed)
    summary["typo.vertical"] = _share_stats([t.get("vertical", False) for t in texts], seed)
    summary["style.outline"] = _share_stats([(t.get("style") or {}).get("outline") for t in texts], seed)
    summary["style.shadow"] = _share_stats([(t.get("style") or {}).get("shadow") for t in texts], seed)
    summary["style.hollow"] = _share_stats([(t.get("style") or {}).get("hollow") for t in texts], seed)
    summary["type.mincho"] = _share_stats([((t.get("typeface") or {}).get("class") == "mincho")
                                           if (t.get("typeface") or {}).get("class") else None for t in texts], seed)
    # the amount, over the time the voice sings (from the first phrase's start to the last's end)
    phrases = (voice or {}).get("phrases") or []
    if phrases:
        a, z = phrases[0][0], phrases[-1][1]
    else:
        a, z = tr["range"]
    span = max(1e-6, z - a)
    summary["typo.per_min"] = _one(sum(1 for t in texts if t["times"]["last"] >= a and t["times"]["first"] <= z) / span * 60.0,
                                   len(texts))
    grid = np.arange(a, z, 1.0 / fps)
    count = np.zeros(grid.size, int)
    for t in texts:
        count += (grid >= t["times"]["first"]) & (grid <= t["times"]["last"])
    summary["typo.on_screen"] = _one(float((count > 0).mean()) if grid.size else float("nan"), grid.size)
    summary["typo.concurrent"] = _one(float(np.median(count[count > 0])) if (count > 0).any() else 0.0, grid.size)
    summary["sync.paired"] = _one(sy.get("lyric_share_paired", float("nan")), len(texts))
    summary["sync.on_beat"] = _one(sy["on_beat"]["share"], sy["on_beat"].get("n", 0))
    summary["sync.on_beat_chance"] = _one(sy["on_beat"]["chance"], sy["on_beat"].get("n", 0))
    return {"label": tr.get("label"), "fps": fps, "lyrics": len(texts), "texts": len(kinds),
            "kinds": {k: kinds.count(k) for k in sorted(set(kinds))}, "summary": summary}


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
    p = sub.add_parser("track", help="every text of a detect run measured frame by frame, and its look")
    p.add_argument("video")
    p.add_argument("detect", help="the JSON of a detect run of the same video")
    p.add_argument("out")
    p.add_argument("--craft-onnx", default=None)
    p.add_argument("--threads", type=int, default=3)
    p.add_argument("--no-style", action="store_true", help="not the look (colour, outline, typeface)")
    p = sub.add_parser("voice", help="the onsets and phrases of a separated voice, and the beat of the accompaniment")
    p.add_argument("vocals")
    p.add_argument("out")
    p.add_argument("--accompaniment", default=None, help="the song without the voice (for the beat)")
    p.add_argument("--offset", type=float, default=0.0, help="s added to every time")
    p = sub.add_parser("sync", help="the texts of a track run against the voice and the beat")
    p.add_argument("texts", help="the JSON of a track run")
    p.add_argument("voice", help="the JSON of a voice run")
    p.add_argument("out")
    p = sub.add_parser("summary", help="a video's lyrics in a few numbers (TYPO_MEASURES)")
    p.add_argument("texts", help="the JSON of a track run")
    p.add_argument("sync", help="the JSON of a sync run of it")
    p.add_argument("out")
    p.add_argument("--voice", default=None, help="the JSON of the voice run (the singing's span)")
    p.add_argument("--label", default=None)
    p = sub.add_parser("compare", help="summaries side by side: the references' quartiles and ours")
    p.add_argument("out_md")
    p.add_argument("out_json")
    p.add_argument("--ref", nargs="+", required=True)
    p.add_argument("--ours", nargs="+", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "summary":
        with open(args.texts, encoding="utf-8") as f:
            tr = json.load(f)
        with open(args.sync, encoding="utf-8") as f:
            sy = json.load(f)
        vo = None
        if args.voice:
            with open(args.voice, encoding="utf-8") as f:
                vo = json.load(f)
        r = typo_summary(tr, sy, voice=vo)
        if args.label:
            r["label"] = args.label
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1, allow_nan=True)
        print(json.dumps({"ok": True, "out": args.out, "lyrics": r["lyrics"], "kinds": r["kinds"]}))
        return 0
    if args.cmd == "compare":
        LA = _tool("look_analyze")
        refs = [json.load(open(x, encoding="utf-8")) for x in args.ref]
        ours = [json.load(open(x, encoding="utf-8")) for x in args.ours]
        rows = LA.compare(refs, ours, measures=TYPO_MEASURES)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump({"refs": [r["label"] for r in refs], "ours": [o["label"] for o in ours], "rows": rows}, f,
                      ensure_ascii=False, indent=1, allow_nan=True)
        md = LA.table_md(rows, [o["label"] for o in ours], concepts=TYPO_CONCEPTS, concept_labels=TYPO_CONCEPT_LABELS)
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write("# 歌詞の文字: 参考 %d 本と私たち\n\n参考: %s\n%s" % (len(refs), ", ".join(r["label"] for r in refs), md))
        print(json.dumps({"ok": True, "out": args.out_md, "rows": len(rows)}))
        return 0
    if args.cmd == "voice":
        r = voice_file(args.vocals, args.out, accompaniment=args.accompaniment, offset=args.offset)
        print(json.dumps({"ok": True, "out": args.out, "phrases": len(r["phrases"]), "onsets": len(r["onsets"]),
                          "bpm": r.get("bpm")}))
        return 0
    if args.cmd == "sync":
        with open(args.texts, encoding="utf-8") as f:
            tr = json.load(f)
        with open(args.voice, encoding="utf-8") as f:
            vo = json.load(f)
        beats = {"beats": vo["beats"], "downbeats": vo.get("downbeats", [])} if vo.get("beats") else None
        r = sync(tr["texts"], vo, beats=beats, fps=tr["fps"], duration=tr["range"][1] - tr["range"][0])
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(json.dumps({"ok": True, "out": args.out, "paired": r["paired"], "lead_median": r["lead_s"]["median"]}))
        return 0
    if args.cmd == "track":
        with open(args.detect, encoding="utf-8") as f:
            det = json.load(f)

        def log(text):
            print(text, flush=True)
        r = track_video(args.video, det, args.out, onnx=args.craft_onnx, threads=args.threads, style=not args.no_style,
                        log=log)
        print(json.dumps({"ok": True, "out": args.out, "tracks": r["tracks"], "texts": len(r["texts"]),
                          "seconds": r["seconds"]}))
        return 0
    if args.cmd == "detect":
        def log(text):
            print(text, flush=True)
        r = detect_video(args.video, args.out, start=args.start, end=args.end, rate=args.rate, height=args.height,
                         onnx=args.craft_onnx, threads=args.threads, matrix=args.matrix, log=log)
        print(json.dumps({"ok": True, "out": args.out, "samples": len(r["samples"]), "summary": r["summary"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
