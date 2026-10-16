"""selfshadow_check: measures of the soft self shadow of tools/mme_shadow.py (through MME) that do not go through its sums.

    python tools/selfshadow_check.py probe OUTDIR [--height 10] [--size 1920x1080]
    python tools/selfshadow_check.py contact PROBE.json RAMP.png [--blur 5] [--min-blur 0.05]
    python tools/selfshadow_check.py fan PROBE.json FAN.png
    python tools/selfshadow_check.py acne SHARP.avi SOFT.avi [--far 60] [--box X0,Y0,X1,Y1]
    python tools/selfshadow_check.py seen SHADED.avi LIT.avi [--sub 16] [--shutter 0.5] [--box X0,Y0,X1,Y1]

* probe: two models of plain geometry (PMX 2.0, written here) under MMD's default light (-0.5, -1, 0.5), each with a
  camera (VMD) that sees it, and PROBE.json with what the measures need.  The ramp: a floor and a thin wall standing on
  it across the light, its top edge rising from the floor at one end to --height at the other, so that its shadow on the
  floor starts where it touches the floor and its edge is cast from ever further up.  The fan: square plates in a row,
  each turned from facing the light by 0 to 75 degrees, with nothing between them and the light.
* contact: on a picture of the ramp drawn with an effect of tools/mme_shadow.py --debug (the shadow alone, grey), along
  the wall: the spread of the edge of its shadow on the floor (the standard deviation of a Gaussian edge fitted across it,
  floor units) set against the spread a light --blur degrees wide gives at the distance from the top edge along the
  light (as tools/mv_world.py's floor takes it: the spread on the plane across the light is the blur in radians times the
  distance, and the floor stretches it by 1 / |n.m|, n the floor's normal to the edge, m the normal to the plane of the
  edge and the light), and the lit gap between the wall's foot and where its shadow is half dark.
* fan: on a picture of the fan drawn with --debug: for each plate, the share darker than 0.95 and than 0.5 and the mean.
  No other thing shadows a plate, so what is dark is the plate shadowing itself (shadow acne).
* acne: on the dancer, two AVIs of the same frames drawn with --debug --sharp (MMD's own test at one point) and --debug:
  where MMD's test lets all the light through and none of its shadow is within --far px (a square), how much of the
  light the soft one takes away (the body shadowing itself where MMD does not).
* seen: what the viewer sees of the shade: the luma (BT.709) of the body as drawn over that of the body lit everywhere
  (--debug lit), per pixel where both are opaque and the lit body is bright enough, folded to the video's rate as
  tools/mv_look.py folds (the first round(--shutter x --sub) of every --sub frames averaged, premultiplied): its change
  from one video frame to the next (rms), how rough that is in time (mean |second difference| / mean |first difference|:
  about 1.7 for noise, near 0 for a change that glides), and how deep the shade is (percentiles of the ratio).

Each command prints one JSON object (probe also writes PROBE.json).
"""
import argparse
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LIGHT = (-0.5, -1.0, 0.5)              # MMD's default light: where it shines to
LUMA = np.array([0.2126, 0.7152, 0.0722])
FAN_ANGLES = (0.0, 20.0, 40.0, 50.0, 60.0, 65.0, 70.0, 75.0)
PLATE_HALF = 1.4
PLATE_STEP = 3.5
PLATE_HEIGHT = 3.0
RAMP_FROM, RAMP_TO = -8.0, 6.0          # the wall's foot along the row (u), from where it touches the floor to its top
FLOOR_U, FLOOR_W = (-12.0, 10.0), (-3.0, 12.0)


def _mv_world():
    spec = importlib.util.spec_from_file_location("mv_world", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                           "mv_world.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def frame_axes(light=LIGHT):
    """(L, t, l): the light's direction, the floor's direction across it (u) and the floor's direction along it (w)"""
    L = unit(light)
    l = unit((L[0], 0.0, L[2]))
    t = np.array([l[2], 0.0, -l[0]])
    return L, t, l


def world(u, y, w, light=LIGHT):
    _, t, l = frame_axes(light)
    return u * t + np.array([0.0, y, 0.0]) + w * l


# ---- PMX 2.0 ----------------------------------------------------------------------------------

def _text(s):
    b = s.encode("utf-16-le")
    return struct.pack("<i", len(b)) + b


def pmx_bytes(name, vertices, triangles):
    """a PMX 2.0 model of one material (both sides drawn, casting and taking the self shadow and the ground shadow) and
    one bone: vertices [(position, normal)], triangles [(i, j, k)]"""
    out = [b"PMX ", struct.pack("<f", 2.0), struct.pack("<B", 8),
           bytes([0, 0, 4, 1, 1, 1, 1, 1]),                     # UTF-16, no extra UV, index sizes
           _text(name), _text(name), _text("selfshadow_check probe"), _text("selfshadow_check probe"),
           struct.pack("<i", len(vertices))]
    for (p, n) in vertices:
        out.append(struct.pack("<3f3f2f", *p, *n, 0.0, 0.0) + struct.pack("<Bb", 0, 0) + struct.pack("<f", 1.0))
    out.append(struct.pack("<i", 3 * len(triangles)))
    for tri in triangles:
        out.append(struct.pack("<3i", *tri))
    out.append(struct.pack("<i", 0))                             # textures
    out.append(struct.pack("<i", 1))                             # materials
    out.append(_text("probe") + _text("probe") + struct.pack("<4f", 0.8, 0.8, 0.8, 1.0) + struct.pack("<3f", 0.0, 0.0, 0.0)
               + struct.pack("<f", 1.0) + struct.pack("<3f", 0.4, 0.4, 0.4) + struct.pack("<B", 0x0F)
               + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0) + struct.pack("<f", 1.0) + struct.pack("<bbBBB", -1, -1, 0, 1, 0)
               + _text("") + struct.pack("<i", 3 * len(triangles)))
    out.append(struct.pack("<i", 1))                             # bones
    out.append(_text("センター") + _text("center") + struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack("<b", -1)
               + struct.pack("<i", 0) + struct.pack("<H", 0x001E) + struct.pack("<3f", 0.0, 1.0, 0.0))
    out.append(struct.pack("<i", 0))                             # morphs
    out.append(struct.pack("<i", 2))                             # display frames
    out.append(_text("Root") + _text("Root") + struct.pack("<B", 1) + struct.pack("<i", 1) + struct.pack("<Bb", 0, 0))
    out.append(_text("表情") + _text("Exp") + struct.pack("<B", 1) + struct.pack("<i", 0))
    out.append(struct.pack("<i", 0) + struct.pack("<i", 0))      # rigid bodies, joints
    return b"".join(out)


def _quad(vertices, triangles, corners, normal):
    k = len(vertices)
    vertices.extend((tuple(map(float, c)), tuple(map(float, normal))) for c in corners)
    triangles.extend([(k, k + 1, k + 2), (k, k + 2, k + 3)])


def plate_normal(alpha, light=LIGHT):
    """the normal of a plate turned from facing the light by alpha degrees, up past the zenith"""
    L, _, l = frame_axes(light)
    e = math.atan2(-L[1], math.hypot(L[0], L[2])) + math.radians(alpha)
    return math.cos(e) * (-l) + math.sin(e) * np.array([0.0, 1.0, 0.0])


def plate_corners(index, alpha, light=LIGHT, half=PLATE_HALF):
    _, t, _ = frame_axes(light)
    n = plate_normal(alpha, light)
    a2 = unit(np.cross(n, t))
    centre = world((index - (len(FAN_ANGLES) - 1) / 2.0) * PLATE_STEP, PLATE_HEIGHT, 0.0, light)
    return centre, [centre - half * t - half * a2, centre + half * t - half * a2, centre + half * t + half * a2,
                    centre - half * t + half * a2], n


def ramp_model(height):
    L, t, l = frame_axes()
    vertices, triangles = [], []
    _quad(vertices, triangles, [world(FLOOR_U[0], 0, FLOOR_W[0]), world(FLOOR_U[1], 0, FLOOR_W[0]),
                                world(FLOOR_U[1], 0, FLOOR_W[1]), world(FLOOR_U[0], 0, FLOOR_W[1])], (0.0, 1.0, 0.0))
    k = len(vertices)
    vertices.extend((tuple(map(float, p)), tuple(map(float, -l)))
                    for p in (world(RAMP_FROM, 0, 0), world(RAMP_TO, 0, 0), world(RAMP_TO, height, 0)))
    triangles.append((k, k + 1, k + 2))
    return vertices, triangles


def fan_model():
    vertices, triangles = [], []
    for i, a in enumerate(FAN_ANGLES):
        _, corners, n = plate_corners(i, a)
        _quad(vertices, triangles, corners, n)
    return vertices, triangles


def _camera_for(points, look_at, size, fov=30.0, down=50.0, yaw=-135.0):
    """the distance at which a camera looking at look_at (window angles down, yaw) sees all the points with a margin"""
    from mmd_cli import fk
    mv_world = _mv_world()
    for distance in np.arange(10.0, 400.0, 0.5):
        view = mv_world.View(fk.CameraState(0, tuple(float(v) for v in look_at), float(distance), (down, yaw, 0.0), fov),
                             size)
        u, v, depth = view.project(points)
        if (depth > 1.0).all() and (u > 0.04 * size[0]).all() and (u < 0.96 * size[0]).all() \
                and (v > 0.04 * size[1]).all() and (v < 0.96 * size[1]).all():
            return {"look_at": [float(x) for x in look_at], "distance": float(distance), "angles": [down, yaw, 0.0],
                    "fov": fov}
    raise ValueError("no distance sees the probe")


def _write_camera(path, cam):
    from mmd_cli.formats import vmd
    key = vmd.CameraKey(frame=0, distance=-cam["distance"], position=tuple(cam["look_at"]),
                        rotation=(-math.radians(cam["angles"][0]), math.radians(cam["angles"][1]), 0.0),
                        fov=int(round(cam["fov"])))
    vmd.dump(vmd.Motion.for_camera(cameras=[key, vmd.CameraKey(frame=1000, distance=key.distance, position=key.position,
                                                               rotation=key.rotation, fov=key.fov)]), path)


def probe(outdir, height=10.0, size=(1920, 1080)):
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    doc = {"light": list(LIGHT), "size": list(size), "frame": 0}
    v, tr = ramp_model(height)
    with open(os.path.join(outdir, "ramp.pmx"), "wb") as f:
        f.write(pmx_bytes("probe ramp", v, tr))
    pts = [p for p, _ in v]
    cam = _camera_for(pts, world(-1.0, 0.0, 3.5), size)
    _write_camera(os.path.join(outdir, "ramp_cam.vmd"), cam)
    doc["ramp"] = {"model": "ramp.pmx", "camera": "ramp_cam.vmd", "camera_state": cam, "height": height,
                   "from": RAMP_FROM, "to": RAMP_TO, "floor_u": list(FLOOR_U), "floor_w": list(FLOOR_W)}
    v, tr = fan_model()
    with open(os.path.join(outdir, "fan.pmx"), "wb") as f:
        f.write(pmx_bytes("probe fan", v, tr))
    cam = _camera_for([p for p, _ in v], world(0.0, PLATE_HEIGHT, 0.0), size)
    _write_camera(os.path.join(outdir, "fan_cam.vmd"), cam)
    doc["fan"] = {"model": "fan.pmx", "camera": "fan_cam.vmd", "camera_state": cam, "angles": list(FAN_ANGLES),
                  "half": PLATE_HALF}
    with open(os.path.join(outdir, "probe.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return doc


# ---- pictures ---------------------------------------------------------------------------------

def read_png(path):
    from PIL import Image
    img = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)
    return img[..., :3].mean(axis=2) / 255.0, img[..., 3]


def _view(doc, part, size=None):
    from mmd_cli import fk
    cam = doc[part]["camera_state"]
    return _mv_world().View(fk.CameraState(0, tuple(cam["look_at"]), cam["distance"], tuple(cam["angles"]), cam["fov"]),
                            tuple(size or doc["size"]))


def sample(img, u, v):
    """bilinear samples of img at pixel coordinates (pixel i at i); NaN outside"""
    h, w = img.shape[:2]
    u, v = np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)
    ok = (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
    uc, vc = np.clip(u, 0, w - 1.000001), np.clip(v, 0, h - 1.000001)
    j, i = np.floor(uc).astype(int), np.floor(vc).astype(int)
    fu, fv = uc - j, vc - i
    out = (img[i, j] * (1 - fu) * (1 - fv) + img[i, j + 1] * fu * (1 - fv) + img[i + 1, j] * (1 - fu) * fv
           + img[i + 1, j + 1] * fu * fv)
    return np.where(ok, out, np.nan)


_PHI_X = np.linspace(-9.0, 9.0, 7201)
_PHI_Y = np.array([0.5 * (1.0 + math.erf(x / math.sqrt(2.0))) for x in _PHI_X])


def _phi(x):
    """the standard normal distribution function (a fine table, to 1e-6)"""
    return np.interp(x, _PHI_X, _PHI_Y)


def fit_edge(tau, values):
    """(centre, sigma, rms) of the Gaussian edge 0 -> 1 rising along tau fitted to values by least squares"""
    tau, values = np.asarray(tau, dtype=np.float64), np.asarray(values, dtype=np.float64)
    ok = np.isfinite(values)
    tau, values = tau[ok], values[ok]
    if tau.size < 8:
        raise ValueError("an edge needs 8 samples or more, not %d" % tau.size)
    span = float(tau.max() - tau.min())
    centres = np.linspace(tau.min(), tau.max(), 241)
    best = None
    for s in np.geomspace(span / 4000.0, span, 160):
        r = ((_phi((tau[None, :] - centres[:, None]) / s) - values[None, :]) ** 2).mean(axis=1)
        k = int(np.argmin(r))
        if best is None or r[k] < best[2]:
            best = (float(centres[k]), float(s), float(r[k]))
    c, s, _ = best
    step_c, step_s = span / 240.0, s * 0.05
    for _ in range(60):                                          # a finer search round the best
        for dc in (-step_c, 0.0, step_c):
            for ds in (-step_s, 0.0, step_s):
                cc, ss = c + dc, max(s + ds, span / 8000.0)
                r = float(((_phi((tau - cc) / ss) - values) ** 2).mean())
                if r < best[2]:
                    best = (cc, ss, r)
        c, s = best[0], best[1]
        step_c, step_s = step_c * 0.7, step_s * 0.7
    return best[0], best[1], math.sqrt(best[2])


def contact(doc, img_path, blur=5.0, min_blur=0.05, step=0.5):
    shadow, alpha = read_png(img_path)
    view = _view(doc, "ramp", shadow.shape[::-1])
    ramp = doc["ramp"]
    L, t, l = frame_axes(doc["light"])
    H, u0, u1 = ramp["height"], ramp["from"], ramp["to"]
    k = math.hypot(L[0], L[2]) / -L[1] * H / (u1 - u0)          # the edge on the floor: w = k (u - u0)
    n2 = np.array([-k, 1.0]) / math.hypot(1.0, k)                # its normal on the floor (u, w), out of the shadow
    n_world = n2[0] * t + n2[1] * l
    edge = unit(t + np.array([0.0, H / (u1 - u0), 0.0]))
    m = unit(np.cross(L, edge))
    stretch = 1.0 / abs(float(n_world @ m))
    theta = math.radians(blur)
    # the floor is where it should be on the picture: opaque just inside its corners, clear just outside
    inside = [world(a, 0, b) for a, b in ((ramp["floor_u"][0] + 0.5, ramp["floor_w"][0] + 0.5),
                                         (ramp["floor_u"][1] - 0.5, ramp["floor_w"][0] + 0.5),
                                         (ramp["floor_u"][1] - 0.5, ramp["floor_w"][1] - 0.5),
                                         (ramp["floor_u"][0] + 0.5, ramp["floor_w"][1] - 0.5))]
    outside = [world(a, 0, b) for a, b in ((ramp["floor_u"][0] - 0.5, ramp["floor_w"][1] - 3.0),
                                          (ramp["floor_u"][1] + 0.5, ramp["floor_w"][1] - 3.0),
                                          (0.0, ramp["floor_w"][1] + 0.5))]
    ui, vi, _ = view.project(inside)
    uo, vo, _ = view.project(outside)
    placed = bool((sample(alpha, ui, vi) > 250).all() and (np.nan_to_num(sample(alpha, uo, vo), nan=0.0) < 5).all())
    rows = []
    across = math.hypot(1.0, k)          # a profile along w at one u crosses the edge this many times slower than along n
    for u in np.arange(u0 + 0.5, u1, step):
        h = (u - u0) * H / (u1 - u0)
        d = h / -L[1]                                            # from the top edge down the light to the floor
        sigma_phys = theta * d * stretch
        sigma_floor = min_blur * stretch
        spread = max(sigma_phys, sigma_floor)
        if u > u1 - 3.0 * spread * across - 0.3:
            continue                                             # the shadow of the wall's end reaches here
        wb = k * (u - u0)
        reach = max(0.4, 4.0 * spread) * across
        lo = -min(reach, wb - 0.3)                               # clear of the wall's foot (its lit gap)
        if lo > -2.0 * spread * across:
            continue                                             # the shadow is narrower than its own edge here
        tau = np.linspace(lo, reach, 161)
        pts = [world(u, 0, wb + x, doc["light"]) for x in tau]
        px, py, _ = view.project(pts)
        vals = sample(shadow, px, py)
        c, s, rms = fit_edge(tau, vals)
        s /= across                                              # across the edge (along n)
        row = {"u": round(float(u), 3), "height": round(h, 3), "distance": round(d, 3), "sigma": round(s, 4),
               "sigma_light": round(sigma_phys, 4), "sigma_least": round(sigma_floor, 4),
               "ratio": round(s / sigma_phys, 3) if sigma_phys > 0 else None, "centre": round(c, 4), "fit_rms": round(rms, 4)}
        if wb > 1.0:                                             # the lit gap at the wall's foot
            ws = np.arange(0.01, 0.8, 0.005)
            gu, gv, _ = view.project([world(u, 0, w, doc["light"]) for w in ws])
            g = sample(shadow, gu, gv)
            dark = np.nonzero(g < 0.5)[0]
            row["lit_gap"] = round(float(ws[dark[0]]), 3) if dark.size else None
            row["at_foot"] = round(float(g[np.nanargmin(np.abs(ws - 0.03))]), 3)
        rows.append(row)
    far = [r for r in rows if r["distance"] >= 2.0]
    near = [r for r in rows if r["distance"] < 1.0]
    gaps = [r["lit_gap"] for r in rows if r.get("lit_gap") is not None]
    fit = np.polyfit([r["distance"] for r in far], [r["sigma"] for r in far], 1) if len(far) >= 3 else None
    return {"placed": placed, "stretch": round(stretch, 4), "rows": rows,
            "ratio_median_far": round(float(np.median([r["ratio"] for r in far])), 3) if far else None,
            "sigma_per_distance": round(float(fit[0]), 5) if fit is not None else None,
            "sigma_at_contact": round(float(fit[1]), 4) if fit is not None else None,
            "light_per_distance": round(theta * stretch, 5),
            "sigma_near_median": round(float(np.median([r["sigma"] for r in near])), 4) if near else None,
            "lit_gap_median": round(float(np.median(gaps)), 3) if gaps else None}


def _inside_polygon(px, py, poly):
    """points inside a convex polygon (pixels, its corners in order either way round)"""
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]))
    sign = 1.0 if area > 0 else -1.0
    inside = np.ones(px.shape, dtype=bool)
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        inside &= sign * ((x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)) > 0
    return inside


def fan(doc, img_path, margin=0.25):
    shadow, alpha = read_png(img_path)
    view = _view(doc, "fan", shadow.shape[::-1])
    out = []
    placed = True
    for i, a in enumerate(doc["fan"]["angles"]):
        centre, corners, n = plate_corners(i, a, doc["light"], doc["fan"]["half"] - margin)
        u, v, _ = view.project(corners)
        poly = list(zip(u, v))
        x0, x1 = int(max(0, math.floor(u.min()))), int(min(shadow.shape[1] - 1, math.ceil(u.max())))
        y0, y1 = int(max(0, math.floor(v.min()))), int(min(shadow.shape[0] - 1, math.ceil(v.max())))
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        inside = _inside_polygon(xx.astype(np.float64), yy.astype(np.float64), poly)
        vals = shadow[y0:y1 + 1, x0:x1 + 1][inside]
        opaque = alpha[y0:y1 + 1, x0:x1 + 1][inside]
        placed &= bool(vals.size > 50 and (opaque > 250).mean() > 0.99)
        out.append({"angle": a, "n_dot_light": round(float(n @ -unit(doc["light"])), 4), "px": int(vals.size),
                    "mean": round(float(vals.mean()), 4) if vals.size else None,
                    "darker_095": round(float((vals < 0.95).mean()), 4) if vals.size else None,
                    "darker_05": round(float((vals < 0.5).mean()), 4) if vals.size else None,
                    "p01": round(float(np.percentile(vals, 1)), 4) if vals.size else None})
    return {"placed": placed, "plates": out}


# ---- AVIs -------------------------------------------------------------------------------------

def _size(path):
    probe_ = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.strip().split(",")
    return int(probe_[0]), int(probe_[1])


def frames(path, box=None):
    """the frames of an AVI, one at a time: (rgb straight 0..255, alpha 0..255), as float arrays (MMD's AVI: premultiplied
    colour, divided back)"""
    w, h = _size(path)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    try:
        while True:
            raw = proc.stdout.read(w * h * 4)
            if len(raw) < w * h * 4:
                break
            f = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
            if box:
                f = f[box[1]:box[3], box[0]:box[2]]
            a = f[..., 3].astype(np.float64)
            yield f[..., :3].astype(np.float64) / np.maximum(a, 1.0)[..., None] * 255.0, a
    finally:
        proc.stdout.close()
        proc.wait()


def inner(alpha):
    a = alpha > 250
    out = a.copy()
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out[1:-1, 1:-1] &= a[1 + dy:a.shape[0] - 1 + dy, 1 + dx:a.shape[1] - 1 + dx]
    return out


def near(mask, r):
    """pixels within r (a square) of a pixel of mask: by summed areas"""
    m = mask.astype(np.int64)
    c = np.zeros((m.shape[0] + 1, m.shape[1] + 1), dtype=np.int64)
    c[1:, 1:] = m.cumsum(axis=0).cumsum(axis=1)
    h, w = m.shape
    y0 = np.clip(np.arange(h) - r, 0, h)
    y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w)
    x1 = np.clip(np.arange(w) + r + 1, 0, w)
    total = c[y1][:, x1] - c[y0][:, x1] - c[y1][:, x0] + c[y0][:, x0]
    return total > 0


def acne_frame(sharp, soft, a_sharp, a_soft, far):
    body = inner(a_sharp) & inner(a_soft)
    shadowed = body & (sharp < 0.95)
    lit = body & ~near(shadowed, far) & (sharp > 0.999)
    v = soft[lit]
    return {"far_lit_px": int(v.size), "taken": float((1.0 - v).sum()) if v.size else 0.0,
            "darker_095": int((v < 0.95).sum()), "darker_08": int((v < 0.8).sum())}


def acne(sharp_path, soft_path, far=60, box=None):
    return acne_of(zip(frames(sharp_path, box), frames(soft_path, box)), far)


def acne_of(pairs, far=60):
    """the measures of `acne` over ((sharp rgb, alpha), (soft rgb, alpha)) frames, fed one at a time"""
    tot = {"frames": 0, "far_lit_px": 0, "taken": 0.0, "darker_095": 0, "darker_08": 0}
    worst = 0.0
    for (rs, as_), (rf, af) in pairs:
        m = acne_frame(rs.mean(axis=2) / 255.0, rf.mean(axis=2) / 255.0, as_, af, far)
        tot["frames"] += 1
        for key in ("far_lit_px", "taken", "darker_095", "darker_08"):
            tot[key] += m[key]
        if m["far_lit_px"]:
            worst = max(worst, m["darker_095"] / float(m["far_lit_px"]))
    n = max(tot["far_lit_px"], 1)
    return {"frames": tot["frames"], "far_lit_px": tot["far_lit_px"], "mean_taken": round(tot["taken"] / n, 5),
            "darker_095": round(tot["darker_095"] / float(n), 5), "darker_08": round(tot["darker_08"] / float(n), 5),
            "worst_frame_darker_095": round(worst, 5), "far_px": far}


class Folder:
    """folds subframes into video frames as tools/mv_look.py does: of every `sub` the first round(shutter x sub) are
    averaged with the colour premultiplied by the alpha (only the running sums are held)"""

    def __init__(self, sub, shutter):
        self.sub, self.taken = int(sub), max(1, int(math.floor(shutter * sub + 0.5)))
        self.i, self.pre, self.alpha = 0, None, None

    def add(self, rgb, a):
        """the folded frame (rgb straight, alpha) when this subframe ends one, else None"""
        k = self.i % self.sub
        self.i += 1
        if k == 0:
            self.pre, self.alpha = np.zeros(rgb.shape), np.zeros(a.shape)
        if k < self.taken:
            self.pre += rgb * a[..., None]
            self.alpha += a
        if k == self.sub - 1:
            return self.pre / np.maximum(self.alpha, 1e-6)[..., None], self.alpha / self.taken
        return None


def fold(seq, sub, shutter):
    """the video frames of a run of subframes (rgb, alpha) as tools/mv_look.py folds them"""
    f = Folder(sub, shutter)
    for rgb, a in seq:
        out = f.add(rgb, a)
        if out is not None:
            yield out


def shade_ratio(shaded, lit, min_lit=20.0):
    (rs, as_), (rl, al) = shaded, lit
    ll = rl @ LUMA
    ok = (as_ > 250) & (al > 250) & (ll > min_lit)
    return np.where(ok, (rs @ LUMA) / np.maximum(ll, 1e-6), np.nan)


class TimeMeasures:
    """over a series of ratio maps fed one at a time (NaN where not read): the rms change from one to the next, and the
    roughness (mean |second difference| / mean |first difference| over the pixels read in three in a row)"""

    def __init__(self):
        self.prev = self.prev2 = None
        self.sq, self.n, self.d1, self.d2, self.count = 0.0, 0, 0.0, 0.0, 0

    def add(self, r):
        r = np.asarray(r, dtype=np.float64)
        self.count += 1
        if self.prev is not None:
            d = r - self.prev
            ok = np.isfinite(d)
            self.sq += float((d[ok] ** 2).sum())
            self.n += int(ok.sum())
            if self.prev2 is not None:
                dd = r - 2.0 * self.prev + self.prev2
                ok3 = np.isfinite(dd)
                self.d1 += float(np.abs(d[ok3]).sum())
                self.d2 += float(np.abs(dd[ok3]).sum())
        self.prev2, self.prev = self.prev, r

    def result(self):
        return {"maps": self.count, "rms_change": round(math.sqrt(self.sq / self.n), 5) if self.n else None,
                "roughness": round(self.d2 / self.d1, 4) if self.d1 > 0 else None}


def time_measures(ratios):
    t = TimeMeasures()
    for r in ratios:
        t.add(r)
    return t.result()


def _percentile(hist, edges, q):
    c = np.cumsum(hist)
    if c[-1] == 0:
        return None
    k = int(np.searchsorted(c, q / 100.0 * c[-1]))
    return float(edges[min(k + 1, len(edges) - 1)])


def seen_of(pairs, sub=16, shutter=0.5):
    """the measures of `seen` over ((shaded rgb, alpha), (lit rgb, alpha)) subframes, fed one at a time"""
    at_sub, at_video = TimeMeasures(), TimeMeasures()
    fold_shaded, fold_lit = Folder(sub, shutter), Folder(sub, shutter)
    edges = np.linspace(0.0, 1.5, 1501)
    hist = np.zeros(len(edges) - 1)
    shaded_px = read_px = 0
    for s, l in pairs:
        at_sub.add(shade_ratio(s, l))
        fs, fl = fold_shaded.add(*s), fold_lit.add(*l)
        if fs is None:
            continue
        r = shade_ratio(fs, fl)
        at_video.add(r)
        v = r[np.isfinite(r)]
        read_px += v.size
        shaded_px += int((v < 0.95).sum())
        hist += np.histogram(v[v < 0.95], bins=edges)[0]
    return {"sub": sub, "shutter": shutter, "at_subframes": at_sub.result(), "at_video": at_video.result(),
            "shaded_share": round(shaded_px / float(max(read_px, 1)), 4),
            "shade_p10": _percentile(hist, edges, 10), "shade_median": _percentile(hist, edges, 50)}


def seen(shaded_path, lit_path, sub=16, shutter=0.5, box=None):
    """see the module docstring; the AVIs are read one frame at a time"""
    return seen_of(zip(frames(shaded_path, box), frames(lit_path, box)), sub, shutter)


def _box(text):
    if not text:
        return None
    box = tuple(int(v) for v in text.split(","))
    if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("--box is X0,Y0,X1,Y1 with X1 > X0 and Y1 > Y0")
    return box


def _size_arg(text):
    w, h = (int(v) for v in text.lower().split("x"))
    return w, h


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("probe")
    s.add_argument("outdir")
    s.add_argument("--height", type=float, default=10.0)
    s.add_argument("--size", default="1920x1080")
    s = sub.add_parser("contact")
    s.add_argument("probe")
    s.add_argument("picture")
    s.add_argument("--blur", type=float, default=5.0)
    s.add_argument("--min-blur", type=float, default=0.05)
    s = sub.add_parser("fan")
    s.add_argument("probe")
    s.add_argument("picture")
    s = sub.add_parser("acne")
    s.add_argument("sharp")
    s.add_argument("soft")
    s.add_argument("--far", type=int, default=60)
    s.add_argument("--box")
    s = sub.add_parser("seen")
    s.add_argument("shaded")
    s.add_argument("lit")
    s.add_argument("--sub", type=int, default=16)
    s.add_argument("--shutter", type=float, default=0.5)
    s.add_argument("--box")
    a = p.parse_args(argv)
    try:
        if a.command == "probe":
            out = probe(a.outdir, a.height, _size_arg(a.size))
        elif a.command in ("contact", "fan"):
            with open(a.probe, encoding="utf-8") as f:
                doc = json.load(f)
            out = contact(doc, a.picture, a.blur, a.min_blur) if a.command == "contact" else fan(doc, a.picture)
        elif a.command == "acne":
            out = acne(a.sharp, a.soft, a.far, _box(a.box))
        else:
            out = seen(a.shaded, a.lit, a.sub, a.shutter, _box(a.box))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **out), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
