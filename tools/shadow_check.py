"""shadow_check: measures of the floor shadow of tools/mv_world.py (stage.shadow_soft) that do not go through its own sums.

    python tools/shadow_check.py light --model M.pmx --motion D.vmd [--motion ...] --frame F [--blur 5] [--floor-y 0.111]
    python tools/shadow_check.py pixels PLAIN.png SHADED.png --camera C.vmd --frame F [--floor-y 0.111]
    python tools/shadow_check.py ground ON.png OFF.png PLAIN.png SHADED.png [--grow 2] [--level 0.5] [--overlay OUT.png]
    python tools/shadow_check.py rough PLAIN_%05d.png SHADED_%05d.png --first A --last B

* light: the share of the key light that reaches the floor round her at a frame, by rays: a quadrature of the Gaussian
  light (side x side directions) and, for every floor point and direction, an exact test of the ray against every capsule
  of her body (mv_world.Body); a direction is blocked when any capsule blocks it.  Set against mv_world.soft_shadow_grid's
  key at the same points, and against the product of each capsule's own share (what taking the capsules one by one, as
  the soft shadow does, gives with exact capsules): the error of the capsule sums and the error of the product are told
  apart.  The capsules are the soft shadow's own (the body is the soft shadow's model; how far it is from her mesh is
  what `ground` measures).
* pixels: the floor shadow as the viewer sees it, from two pictures of the stage drawn with and without it
  (mv_world.py frame): the ratio of their luma per pixel, read where the plain floor is bright enough, the floor point of
  each pixel (the camera of the frame), the darkest ratio, the area darker than half, the darkening's centre on the floor.
* ground: MMD's own ground shadow of her mesh (renders with menu 221 on and off, RGBA from MMD's AVI) against the floor
  shadow drawn with the same light (pictures of the stage with and without it, best with stage.shadow_blur 0 and
  stage.shadow_contact 0 and the floor at MMD's ground, floor_y 0): how far the two agree outside her.
* rough: the roughness in time (mean |second difference| / mean |first difference|: about 1.73 for white noise, near 0
  for a smooth motion) of the ratio of a series of picture pairs from a camera that stands still, over the pixels the
  shadow reaches, and the largest change of the ratio from one frame to the next.

Each prints one JSON object.
"""
import argparse
import importlib.util
import json
import math
import os
import statistics
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LUMA = np.array([0.2126, 0.7152, 0.0722])        # BT.709, on the 8-bit values as they are
RAY_LENGTH = 1.0e4                                # MMD units: a ray is a segment this long (the stage is some 100 across)
CHUNK = 1 << 18                                   # rays tested at a time


def _mv_world():
    spec = importlib.util.spec_from_file_location("mv_world", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                           "mv_world.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- rays past capsules ---------------------------------------------------------------------

def ray_capsule_hits(origins, dirs, a, b, r):
    """True where the ray from each origin along its unit direction (forward only) passes within r of the segment a-b:
    the closest points of two segments (the ray taken RAY_LENGTH long), clamped to both (Ericson, Real-Time Collision
    Detection 5.1.9)"""
    O = np.asarray(origins, dtype=np.float64)
    d1 = np.asarray(dirs, dtype=np.float64) * RAY_LENGTH
    p2 = np.asarray(a, dtype=np.float64)
    d2 = np.asarray(b, dtype=np.float64) - p2
    rr = O - p2[None, :]
    aa = (d1 * d1).sum(axis=1)
    e = float(d2 @ d2)
    f = rr @ d2
    c = (d1 * rr).sum(axis=1)
    if e <= 1e-12:
        s = np.clip(-c / aa, 0.0, 1.0)
        t = np.zeros(len(O))
    else:
        bb = d1 @ d2
        denom = aa * e - bb * bb
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(denom > 1e-12 * aa * e, np.clip((bb * f - c * e) / denom, 0.0, 1.0), 0.0)
        t = (bb * s + f) / e
        low, high = t < 0.0, t > 1.0
        s = np.where(low, np.clip(-c / aa, 0.0, 1.0), np.where(high, np.clip((bb - c) / aa, 0.0, 1.0), s))
        t = np.clip(t, 0.0, 1.0)
    gap = rr + d1 * s[:, None] - d2[None, :] * t[:, None]
    return (gap * gap).sum(axis=1) <= float(r) * float(r)


def toward(light):
    """the unit vector toward the light from where it shines to"""
    v = -np.asarray(light, dtype=np.float64)
    return v / np.linalg.norm(v)


def gaussian_directions(light, blur_degrees, side=64):
    """(directions, weights): side x side unit vectors toward a light whose brightness spreads round its direction as an
    isotropic Gaussian of `blur_degrees` (a standard deviation), with equal weights: in each of two axes across the light
    the middles of `side` stretches of equal probability, the tangent vector they make laid on the sphere (the exponential
    map: its length is the angle from the light)"""
    ell = toward(light)
    helper = np.array([1.0, 0.0, 0.0]) if abs(ell[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    e1 = np.cross(ell, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ell, e1)
    z = np.array([statistics.NormalDist().inv_cdf((i + 0.5) / side) for i in range(side)])
    sigma = math.radians(max(float(blur_degrees), 0.0))
    g1, g2 = np.meshgrid(z * sigma, z * sigma)
    tangent = g1.reshape(-1, 1) * e1[None, :] + g2.reshape(-1, 1) * e2[None, :]
    angle = np.linalg.norm(tangent, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        across = np.where(angle[:, None] > 0, tangent / angle[:, None], 0.0)
    dirs = np.cos(angle)[:, None] * ell[None, :] + np.sin(angle)[:, None] * across
    return dirs, np.full(len(dirs), 1.0 / len(dirs))


def light_through(points, capsules, light, blur_degrees, side=64, union=True):
    """the share of the light (gaussian_directions) that reaches each point (N x 3) past the capsules ((a, b, radius)):
    union, a direction is blocked when any capsule blocks it; union False, the product of each capsule's own share"""
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    dirs, weights = gaussian_directions(light, blur_degrees, side)
    m = len(dirs)
    per = max(1, CHUNK // m)
    out = np.ones(len(P))
    for k in range(0, len(P), per):
        chunk = P[k:k + per]
        origins = np.repeat(chunk, m, axis=0)
        ways = np.tile(dirs, (len(chunk), 1))
        if union:
            blocked = np.zeros(len(origins), dtype=bool)
            for a, b, r in capsules:
                blocked |= ray_capsule_hits(origins, ways, a, b, r)
            out[k:k + per] = 1.0 - (blocked.reshape(len(chunk), m) * weights[None, :]).sum(axis=1)
        else:
            share = np.ones(len(chunk))
            for a, b, r in capsules:
                hit = ray_capsule_hits(origins, ways, a, b, r).reshape(len(chunk), m)
                share *= 1.0 - (hit * weights[None, :]).sum(axis=1)
            out[k:k + per] = share
    return out


# ---- the shadow read back from pictures -----------------------------------------------------

def floor_points(view, floor_y=0.0):
    """(X, Z, hit): where the ray through the middle of each pixel (mv_world.View: pixel i at i) meets the plane
    y = floor_y, and whether it does (it goes down to it)"""
    w, h = view.size
    us = np.arange(w) - w / 2.0
    vs = np.arange(h) - h / 2.0
    d = (view.forward * view.focal)[None, None, :] + us[None, :, None] * view.right - vs[:, None, None] * view.up
    dy = d[..., 1]
    drop = float(floor_y) - float(view.eye[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dy < 0, drop / dy, np.nan)
    hit = (dy < 0) & (drop < 0) & np.isfinite(t)
    X = np.where(hit, view.eye[0] + t * d[..., 0], np.nan)
    Z = np.where(hit, view.eye[2] + t * d[..., 2], np.nan)
    return X, Z, hit


def luma(rgb):
    return np.asarray(rgb, dtype=np.float64)[..., :3] @ LUMA


def ratio_map(shaded, plain, min_plain=4.0):
    """luma(shaded) / luma(plain) per pixel; NaN where the plain picture is darker than min_plain (too dark to read)"""
    lp, ls = luma(plain), luma(shaded)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(lp >= float(min_plain), ls / lp, np.nan)


def edge_width(distance, values, lo=0.1, hi=0.9):
    """how far a profile rising from shadow to light goes from `lo` to `hi` of the way between its least and its most:
    taken up to its first rise (its running maximum), each crossing between two samples by a straight line"""
    s = np.asarray(distance, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    span = float(v.max() - v.min())
    if not span > 0:
        return float("nan")
    env = np.maximum.accumulate((v - v.min()) / span)

    def crossing(level):
        k = int(np.argmax(env >= level))
        if k == 0:
            return float(s[0])
        step = env[k] - env[k - 1]
        f = (level - env[k - 1]) / step if step > 0 else 0.0
        return float(s[k - 1] + f * (s[k] - s[k - 1]))
    return crossing(hi) - crossing(lo)


def _grow(mask, n):
    """the mask grown by n pixels (a square of 2n + 1)"""
    out = np.asarray(mask, dtype=bool).copy()
    if n <= 0:
        return out
    padded = np.pad(out, n)
    h, w = out.shape
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            out |= padded[n + dy:n + dy + h, n + dx:n + dx + w]
    return out


def ground_shadow(rgba_on, rgba_off, alpha_min=0.04, her_alpha=0.02, grow=0):
    """(shadow, her): MMD's ground shadow in a render with menu 221 on, by alpha: where `rgba_on` has alpha above
    alpha_min and the render with it off (`rgba_off`) is not her (alpha above her_alpha, grown by `grow` pixels: her
    physics differs a little from render to render)"""
    on = np.asarray(rgba_on, dtype=np.float64)
    off = np.asarray(rgba_off, dtype=np.float64)
    her = _grow(off[..., 3] / 255.0 > her_alpha, int(grow))
    return (on[..., 3] / 255.0 > alpha_min) & ~her, her


def agreement(a, b, valid=None):
    """how two masks agree where `valid`: {"iou", "a_in_b" (the share of a that b covers), "b_in_a", "a", "b"}"""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    if valid is not None:
        a, b = a & valid, b & valid
    inter, union, na, nb = int((a & b).sum()), int((a | b).sum()), int(a.sum()), int(b.sum())
    nan = float("nan")
    return {"iou": inter / union if union else nan, "a_in_b": inter / na if na else nan,
            "b_in_a": inter / nb if nb else nan, "a": na, "b": nb}


def roughness(series, axis=0):
    """mean |second difference| / mean |first difference| along `axis`: about sqrt(3) for white noise, near 0 for a smooth
    motion; NaN when nothing changes"""
    x = np.asarray(series, dtype=np.float64)
    d1 = float(np.nanmean(np.abs(np.diff(x, axis=axis))))
    d2 = float(np.nanmean(np.abs(np.diff(x, n=2, axis=axis))))
    return d2 / d1 if d1 > 0 else float("nan")


# ---- the commands ---------------------------------------------------------------------------

def _rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def _rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)


def _r(x, n=4):
    return None if x is None or not math.isfinite(float(x)) else round(float(x), n)


def cmd_light(args):
    world = _mv_world()
    figure = world.Figure.from_files(args.model, args.motion, body=True)
    capsules = figure.state(args.frame).capsules
    grid = world.soft_shadow_grid(capsules, args.light, args.blur, args.floor_y)
    shaded = grid.key < 0.999
    rows, cols = np.nonzero(shaded)
    if not len(rows):
        print(json.dumps({"ok": True, "frame": args.frame, "points": 0}))
        return 0
    xs = grid.x0 + grid.cell * cols
    zs = grid.z0 + grid.cell * rows
    step = max(args.step, grid.cell)
    while True:
        gx = np.arange(math.floor(xs.min() / step) * step, xs.max() + step, step)
        gz = np.arange(math.floor(zs.min() / step) * step, zs.max() + step, step)
        X, Z = np.meshgrid(gx, gz)
        key, _ = grid.at(X.ravel(), Z.ravel())
        keep = key < 0.999
        if keep.sum() <= args.max_points:
            break
        step *= 1.25
    X, Z, key = X.ravel()[keep], Z.ravel()[keep], key[keep]
    P = np.stack([X, np.full(X.shape, args.floor_y), Z], axis=1)
    union = light_through(P, capsules, args.light, args.blur, args.side)
    product = light_through(P, capsules, args.light, args.blur, args.side, union=False)

    def errors(a, b):
        d = a - b
        return {"max_abs": _r(np.abs(d).max()), "mean_abs": _r(np.abs(d).mean()), "p99_abs": _r(np.percentile(np.abs(d), 99)),
                "darker_by_0.05": int((d < -0.05).sum()), "lighter_by_0.05": int((d > 0.05).sum())}
    out = {"ok": True, "frame": args.frame, "blur": args.blur, "light": list(args.light), "points": int(len(P)),
           "step": _r(step, 3), "side": args.side, "capsules": len(capsules),
           "soft_vs_rays": errors(key, union), "soft_vs_rays_one_by_one": errors(key, product),
           "one_by_one_vs_rays": errors(product, union),
           "darkest": {"soft": _r(key.min()), "rays": _r(union.min())},
           "area_under_half": {"soft": _r((key < 0.5).sum() * step * step, 2), "rays": _r((union < 0.5).sum() * step * step, 2)}}
    if args.out:
        np.savez_compressed(args.out, X=X, Z=Z, soft=key, rays=union, one_by_one=product)
    print(json.dumps(out))
    return 0


def _view(world, camera, frame, size):
    return world.view_at(world.camera_track(camera), frame, size)


def cmd_pixels(args):
    world = _mv_world()
    plain, shaded = _rgb(args.plain), _rgb(args.shaded)
    h, w = plain.shape[:2]
    view = _view(world, args.camera, args.frame, (w, h))
    X, Z, hit = floor_points(view, args.floor_y)
    ratio = ratio_map(shaded, plain, args.min_plain)
    seen = hit & np.isfinite(ratio)
    # the floor area of each pixel: the cross product of its steps to the next pixel along the row and the column
    dXj, dZj = np.gradient(X, axis=1), np.gradient(Z, axis=1)
    dXi, dZi = np.gradient(X, axis=0), np.gradient(Z, axis=0)
    area = np.abs(dXj * dZi - dZj * dXi)
    dark = np.where(seen, np.clip(1.0 - ratio, 0.0, 1.0), 0.0)
    total = float(dark.sum())
    lit = luma(plain)
    out = {"ok": True, "frame": args.frame, "pixels_read": int(seen.sum())}
    if total > 0:
        out.update({"darkest": _r(np.nanmin(np.where(seen, ratio, np.nan))),
                    "p1": _r(np.nanpercentile(np.where(seen, ratio, np.nan), 1)),
                    "area_under_half": _r(np.nansum(np.where(seen & (ratio < 0.5), area, 0.0)), 2),
                    "centre": [_r(np.nansum(dark * np.nan_to_num(X)) / total, 3), _r(np.nansum(dark * np.nan_to_num(Z)) / total, 3)],
                    "luma_core": _r(np.nanmedian(np.where(seen & (ratio < 0.2), luma(shaded), np.nan)), 2)
                    if (seen & (ratio < 0.2)).any() else None,
                    "luma_lit_round": _r(np.nanmedian(np.where(seen & (ratio > 0.98) & (dark == 0) & (lit > 0), lit, np.nan)), 2)})
    print(json.dumps(out))
    return 0


def cmd_ground(args):
    on, off = _rgba(args.on), _rgba(args.off)
    mmd, her = ground_shadow(on, off, args.alpha_min, args.her_alpha, args.grow)
    ratio = ratio_map(_rgb(args.shaded), _rgb(args.plain), args.min_plain)
    mine = np.isfinite(ratio) & (ratio < args.level) & ~her
    valid = ~her & np.isfinite(ratio)
    got = agreement(mmd, mine, valid)
    out = {"ok": True, "mmd_pixels": got["a"], "soft_pixels": got["b"], "iou": _r(got["iou"]),
           "mmd_in_soft": _r(got["a_in_b"]), "soft_in_mmd": _r(got["b_in_a"])}
    for name, m in (("mmd_centre", mmd & valid), ("soft_centre", mine & valid)):
        ys, xs = np.nonzero(m)
        out[name] = [_r(xs.mean(), 1), _r(ys.mean(), 1)] if len(xs) else None
    if args.overlay:
        picture = Image.alpha_composite(Image.new("RGBA", (on.shape[1], on.shape[0]), (40, 40, 48, 255)),
                                        Image.open(args.on).convert("RGBA"))
        draw = np.asarray(picture.convert("RGB"), dtype=np.float64).copy()
        for m, colour in ((mmd & valid, (255, 60, 60)), (mine & valid, (60, 220, 255))):
            draw[m & _grow(~m, 1)] = colour              # the outline: the pixels of the mask next to one outside it
        Image.fromarray(np.clip(draw + 0.5, 0, 255).astype(np.uint8)).save(args.overlay)
        out["overlay"] = os.path.abspath(args.overlay)
    print(json.dumps(out))
    return 0


def cmd_rough(args):
    frames = range(args.first, args.last + 1)
    series = [ratio_map(_rgb(args.shaded % i), _rgb(args.plain % i), args.min_plain) for i in frames]
    stack = np.stack(series)
    reached = np.nanmin(np.where(np.isfinite(stack), stack, 1.0), axis=0) < args.reach
    cols = stack[:, reached]
    steps = np.abs(np.diff(cols, axis=0))
    out = {"ok": True, "frames": len(series), "pixels": int(reached.sum()),
           "roughness": _r(roughness(cols)) if cols.size else None,
           "largest_step": _r(np.nanmax(steps)) if steps.size else None,
           "p999_step": _r(np.nanpercentile(steps, 99.9)) if steps.size else None}
    print(json.dumps(out))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("light", help="the soft shadow's key light against rays past her capsules")
    s.add_argument("--model", required=True)
    s.add_argument("--motion", action="append", required=True)
    s.add_argument("--frame", type=float, required=True)
    s.add_argument("--blur", type=float, default=5.0)
    s.add_argument("--light", type=float, nargs=3, default=[-0.5, -1.0, 0.5])
    s.add_argument("--floor-y", type=float, default=0.0)
    s.add_argument("--side", type=int, default=48, help="directions: side x side")
    s.add_argument("--step", type=float, default=0.16, help="floor points this far apart at least (MMD units)")
    s.add_argument("--max-points", type=int, default=6000)
    s.add_argument("--out", help="the points and the three shares (.npz)")
    s = sub.add_parser("pixels", help="the floor shadow read from two pictures of the stage")
    s.add_argument("plain")
    s.add_argument("shaded")
    s.add_argument("--camera", required=True)
    s.add_argument("--frame", type=float, required=True)
    s.add_argument("--floor-y", type=float, default=0.0)
    s.add_argument("--min-plain", type=float, default=4.0)
    s = sub.add_parser("ground", help="MMD's ground shadow against the floor shadow")
    for name in ("on", "off", "plain", "shaded"):
        s.add_argument(name)
    s.add_argument("--alpha-min", type=float, default=0.04)
    s.add_argument("--her-alpha", type=float, default=0.02)
    s.add_argument("--grow", type=int, default=2)
    s.add_argument("--level", type=float, default=0.5)
    s.add_argument("--min-plain", type=float, default=4.0)
    s.add_argument("--overlay")
    s = sub.add_parser("rough", help="the roughness in time of the shadow of a camera that stands still")
    s.add_argument("plain", help="a pattern, %%05d for the frame")
    s.add_argument("shaded")
    s.add_argument("--first", type=int, required=True)
    s.add_argument("--last", type=int, required=True)
    s.add_argument("--reach", type=float, default=0.95, help="pixels whose ratio falls below this at some frame")
    s.add_argument("--min-plain", type=float, default=4.0)
    args = p.parse_args(argv)
    return {"light": cmd_light, "pixels": cmd_pixels, "ground": cmd_ground, "rough": cmd_rough}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
