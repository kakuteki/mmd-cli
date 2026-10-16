"""Measure a self shadow drawn alone: how wide its edges are, how much of the body it covers, and how much it flickers
from frame to frame.

    python tools/shadow_measure.py SHADOW.avi [--box X0,Y0,X1,Y1] [--out OUT.json]

SHADOW.avi is MMD's uncompressed AVI (BGRA) of a model drawn with tools/mme_shadow.py --debug: each body pixel's grey is
the share of the light the self shadow lets through (white lit, black in the shadow, opaque), the rest transparent.
--box keeps the measures to a part of the picture.

* edge width (px): over the body's inner pixels whose shadow is half way (0.4 to 0.6), 1 / the slope of the shadow
  (the 10 % to 90 % width of a blurred edge is 1.02 / its steepest slope for a Gaussian, 0.8 / it for a straight ramp;
  a hard edge of MMD's map is about a pixel);
* cover: the share of the body's inner pixels in full shadow (under 0.05) and half lit (0.05 to 0.95);
* flicker: between frames in a row, over the pixels that are body in both: the mean and the root mean square of the
  shadow's change, and the share of them that jump by more than half.  An edge that moves by the same amount changes the
  mean the same however soft it is (the change spreads over more pixels, each smaller); the root mean square and the
  jumps tell a hard edge stepping over pixels from a soft one sliding.  And the flicker ratio: the summed |second
  difference| over three frames to the summed |first difference|: about 2 for a shadow going one way and back
  (flicker), small for one that glides.  Inner pixels are those whose 8 neighbours are body too (the outline is the
  body's own edge, no shadow).
"""
import argparse
import json
import math
import subprocess
import sys

import numpy as np

HALF = (0.4, 0.6)
FULL = 0.05


def inner(alpha):
    """body pixels whose 8 neighbours are body too"""
    a = alpha > 0
    out = a.copy()
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out[1:-1, 1:-1] &= a[1 + dy:a.shape[0] - 1 + dy, 1 + dx:a.shape[1] - 1 + dx]
    return out


def slope(s):
    """the size of the shadow's slope per pixel (central differences; 0 on the picture's border)"""
    gx = np.zeros(s.shape)
    gy = np.zeros(s.shape)
    gx[:, 1:-1] = 0.5 * (s[:, 2:] - s[:, :-2])
    gy[1:-1, :] = 0.5 * (s[2:, :] - s[:-2, :])
    return np.hypot(gx, gy)


def frame_measures(shadow, alpha):
    """the measures of one frame: shadow and alpha as arrays (shadow 0..1)"""
    body = inner(alpha)
    n = int(body.sum())
    if n == 0:
        return {"body_px": 0}
    g = slope(shadow)
    half = body & (shadow > HALF[0]) & (shadow < HALF[1]) & (g > 1e-6)
    widths = 1.0 / g[half] if half.any() else np.array([])
    return {"body_px": n, "half_px": int(half.sum()),
            "edge_width_px": float(np.median(widths)) if widths.size else None,
            "full_shadow": float((shadow[body] < FULL).mean()),
            "half_lit": float(((shadow[body] >= FULL) & (shadow[body] <= 1 - FULL)).mean()),
            "mean_light": float(shadow[body].mean())}


def flicker(shadows, alphas):
    """the frame to frame measures over a sequence (lists of arrays)"""
    steps, squares, jumps, firsts, seconds = [], [], [], [], []
    for t in range(1, len(shadows)):
        both = inner(alphas[t - 1]) & inner(alphas[t])
        if both.any():
            d = np.abs(shadows[t] - shadows[t - 1])[both]
            steps.append(float(d.mean()))
            squares.append(float((d * d).mean()))
            jumps.append(float((d > 0.5).mean()))
        if t >= 2:
            all3 = both & inner(alphas[t - 2])
            if all3.any():
                firsts.append(float(np.abs(shadows[t] - shadows[t - 1])[all3].mean()))
                seconds.append(float(np.abs(shadows[t] - 2 * shadows[t - 1] + shadows[t - 2])[all3].mean()))
    mean = lambda v: float(np.mean(v)) if v else None
    ratio = (float(np.sum(seconds)) / float(np.sum(firsts))) if firsts and np.sum(firsts) > 0 else (0.0 if firsts else None)
    return {"mean_change": mean(steps), "rms_change": math.sqrt(mean(squares)) if squares else None,
            "jump_share": mean(jumps), "mean_second_difference": mean(seconds), "flicker_ratio": ratio}


def read_avi(path, box=None):
    """(shadows, alphas): the frames of an uncompressed AVI of MMD as arrays (shadow 0..1 from the grey; alpha 0..255)"""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                         capture_output=True, check=True).stdout
    n = len(raw) // (w * h * 4)
    frames = np.frombuffer(raw[:n * w * h * 4], dtype=np.uint8).reshape(n, h, w, 4)
    if box:
        x0, y0, x1, y1 = box
        frames = frames[:, y0:y1, x0:x1]
    alphas = [f[..., 3].astype(np.float64) for f in frames]
    # the AVI's colour is multiplied by its alpha: the body is opaque, so its grey is the shadow
    shadows = [np.where(a > 0, f[..., :3].astype(np.float64).mean(axis=2) / np.maximum(a, 1.0), 1.0)
               for f, a in zip(frames, alphas)]
    return [np.clip(s, 0.0, 1.0) for s in shadows], alphas


def measure(shadows, alphas):
    per = [frame_measures(s, a) for s, a in zip(shadows, alphas)]
    widths = [m["edge_width_px"] for m in per if m.get("edge_width_px") is not None]
    summary = {"frames": len(per),
               "edge_width_px": float(np.median(widths)) if widths else None,
               "full_shadow": float(np.mean([m["full_shadow"] for m in per if "full_shadow" in m])) if per else None,
               "half_lit": float(np.mean([m["half_lit"] for m in per if "half_lit" in m])) if per else None,
               "mean_light": float(np.mean([m["mean_light"] for m in per if "mean_light" in m])) if per else None}
    summary.update(flicker(shadows, alphas))
    return {"summary": summary, "frames": per}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("avi")
    p.add_argument("--box", help="X0,Y0,X1,Y1: measure this part of the picture only")
    p.add_argument("--out", help="write the measures to this JSON file")
    a = p.parse_args(argv)
    try:
        box = tuple(int(v) for v in a.box.split(",")) if a.box else None
        if box is not None and (len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]):
            raise ValueError("--box is X0,Y0,X1,Y1 with X1 > X0 and Y1 > Y0")
        result = measure(*read_avi(a.avi, box))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    print(json.dumps(dict({"ok": True}, **result["summary"]), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
