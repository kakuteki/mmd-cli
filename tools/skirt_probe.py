"""Measure where a PMX model's skirt goes, from MMD's own pictures: a measuring copy of the model whose only drawn parts
are small markers of flat, unique colours on the skirt's bones (and a few body bones), a still camera to film them, the
markers found again in the rendered AVI, and the tilt of every skirt rigid body worked out from the markers' heights.

    python tools/skirt_probe.py markers MODEL.pmx OUT.pmx --legend LEGEND.json [--size 0.07]
    python tools/skirt_probe.py camera OUT.vmd --look X Y Z [--yaw 90] [--distance 700] [--fov 1] [--size 1920 1080]
                                     [--around MODEL.pmx DANCE.vmd FIRST LAST] [--last-frame 7742]
    python tools/skirt_probe.py track AVI LEGEND.json CAMERA.json OUT.json [--first SONG_FRAME] [--fps 60]
    python tools/skirt_probe.py angles TRACK.json LEGEND.json OUT.json
    python tools/skirt_probe.py solve SIDE_TRACK.json FRONT_TRACK.json LEGEND.json OUT.json [--max-gap 0.1]
    python tools/skirt_probe.py analyze SOLVED.json LEGEND.json OUT.json

Why markers: MMD's physics cannot be read back from MMD, and it differs from render to render (it grows from a ~100
pixel difference in the first picture of two renders of the same span), so everything is measured in one render.  The
markers sit on the bones' rest positions and are weighted to them alone (BDEF1), so they follow the bones as MMD's
physics moves them; every other material of the copy is hidden (alpha 0, no edge, no shadow).  A marker's colour is
its material's ambient colour with a black diffuse, no texture and no toon, so MMD draws it flat; LEVELS spaced 45
apart in each channel tell the markers apart, and only opaque pixels (the edges are blended) are used.

The camera: still (the same key at frame 0 and the song's last frame), horizontal (pitch 0), far (700 units) with a
narrow view (1 degree), so a marker's height in the picture is its height in the world to within ~0.03 unit: the depth
is taken as the camera's distance.  The window's angles: yaw 90 looks from +X towards -X (MMD's camera conventions,
mmd_cli.fk: a positive distance puts the camera in front of the look-at point).

Angles: a skirt bone r and the next bone r + 1 of the same column are the two ends of rigid body r (the joints sit on the
bones), so the body's tilt from hanging straight down is acos(-(y[r+1] - y[r]) / L[r]) with L the rest length: 0
hanging, 90 horizontal, more than 90 pointing up.  The hem's elevation is asin((y[hem] - y[waist]) / sum(L)): -90
hanging straight, 0 level with the waist ring, positive above it.  From heights alone (`angles`, one render) a body near
vertical is poorly measured (a pixel moves acos near 1 by degrees); `solve` takes a side and a front render of the same
span and gives every marker seen in both its three coordinates (the renders differ a little: the heights must agree
within --max-gap), and `analyze` measures in 3D: the tilts, the bend at every joint against its rest angle, the spread of
the waist-to-hem line, the root body's turn on the waist (the frame fitted to the waist ring), and how deep skirt markers
sit in the thigh and arm capsules (the model's own capsule radii, kept in the legend with the skirt joints' limits).

The measuring copy is for this work only and is not to be distributed (Sour's ReadMe allows editing; distribution would
need the ReadMe and an editor's ReadMe).
"""
import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit, vmd  # noqa: E402

SKIRT = re.compile(r"^スカート_(\d+)_(\d+)$")
BODY_BONES = ("上半身", "下半身", "左足D", "右足D", "左ひざD", "右ひざD", "左足首D", "右足首D",
              "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首")
SIZE = 0.07                     # a marker's half width (model units; 0.56 cm)
LEVELS = (30, 75, 120, 165, 210, 255)
MIN_SUM = 150                   # no colour darker than this (sum of the channels)
TOL = 12                        # a pixel's channels within TOL of a level count as that level
CAMERA = {"yaw": 90.0, "pitch": 0.0, "distance": 700.0, "fov": 1.0, "size": [1920, 1080]}
HEIGHT_OVER_HIPS = -1.2         # --around: the camera looks at 下半身 + this (the skirt's middle)


# ---- the measuring copy ---------------------------------------------------------------------------------------------

def palette(n):
    """n flat colours (r, g, b) from LEVELS, none darker than MIN_SUM, ordered so that neighbours differ in hue"""
    colours = [(r, g, b) for r in LEVELS for g in LEVELS for b in LEVELS if r + g + b >= MIN_SUM]
    # interleave: step through the list with a stride prime to its length
    stride = 37
    while math.gcd(stride, len(colours)) != 1:
        stride += 2
    ordered = [colours[(i * stride) % len(colours)] for i in range(len(colours))]
    if n > len(ordered):
        raise ValueError("%d markers need more than the %d colours of the palette" % (n, len(ordered)))
    return ordered[:n]


def skirt_grid(doc):
    """(rows, cols, {(row, col): bone index}) of the bones named スカート_row_col; ValueError unless they fill the grid"""
    grid = {}
    for i, b in enumerate(doc.bones):
        m = SKIRT.match(b.name)
        if m:
            grid[(int(m.group(1)), int(m.group(2)))] = i
    if not grid:
        raise ValueError("the model has no bones named スカート_row_col")
    rows, cols = max(r for r, _ in grid) + 1, max(c for _, c in grid) + 1
    missing = [(r, c) for r in range(rows) for c in range(cols) if (r, c) not in grid]
    if missing:
        raise ValueError("the skirt's bones do not fill %d rows x %d columns: missing %s" % (rows, cols, missing[:5]))
    return rows, cols, grid


def _vertex_head(position, normal, extra_uv):
    return struct.pack("<3f3f2f", *position, *normal, 0.0, 0.0) + b"\x00" * (16 * extra_uv)


_AXES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
_FACES = ((2, 0, 4), (2, 4, 1), (2, 1, 5), (2, 5, 0), (3, 4, 0), (3, 1, 4), (3, 5, 1), (3, 0, 5))   # an octahedron


def build_markers(doc, size=SIZE, body=BODY_BONES):
    """turn `doc` (pmx_edit.Document) into the measuring copy; returns the legend"""
    rows, cols, grid = skirt_grid(doc)
    names = {b.name: i for i, b in enumerate(doc.bones)}
    wanted = [(n, names[n], "body", None, None) for n in body if n in names]
    wanted += [(doc.bones[grid[(r, c)]].name, grid[(r, c)], "skirt", r, c) for r in range(rows) for c in range(cols)]
    colours = palette(len(wanted))
    g = pmx_edit.geometry(doc)
    for m in g.materials:                       # the model's own materials: not drawn
        m.diffuse = tuple(m.diffuse[:3]) + (0.0,)
        m.flags = 0
        m.edge_size = 0.0
        m.edge_color = tuple(m.edge_color[:3]) + (0.0,)
    markers = []
    for (name, bone, kind, row, col), colour in zip(wanted, colours):
        p = doc.bones[bone].position
        first = len(doc.vertices)
        for axis in _AXES:
            at = tuple(p[k] + size * axis[k] for k in range(3))
            doc.vertices.append(pmx_edit.Vertex(_vertex_head(at, axis, doc.extra_uv), "BDEF1", [bone], [], b"",
                                                struct.pack("<f", 0.0)))
        g.faces += [first + i for face in _FACES for i in face]
        g.materials.append(pmx_edit.Material("印_" + name, "marker", (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 1.0,
                                             tuple(v / 255.0 for v in colour), 0x01, (0.0, 0.0, 0.0, 0.0), 0.0,
                                             -1, -1, 0, 0, -1, "", 3 * len(_FACES)))
        markers.append({"index": len(markers), "name": name, "bone_index": bone, "kind": kind, "row": row, "col": col,
                        "colour": list(colour), "rest": [round(v, 6) for v in p]})
    pmx_edit.set_geometry(doc, g)
    lengths = {}
    for c in range(cols):
        pts = [doc.bones[grid[(r, c)]].position for r in range(rows)]
        lengths[str(c)] = [round(math.dist(a, b), 6) for a, b in zip(pts, pts[1:])]
    return {"rows": rows, "cols": cols, "size": size, "markers": markers, "lengths": lengths,
            "missing_body": [n for n in body if n not in names], "capsules": _capsules(doc, names),
            "joints": _skirt_joints(doc)}


def _capsules(doc, names):
    """CAPSULES with the radius of the model's own capsule rigid body on the first bone, where it has one"""
    bodies = [(rb.bone, pmx_edit.rigid_body(rb)) for rb in doc.rigid_bodies]
    out = []
    for side, kind, a, b, radius in CAPSULES:
        for bone, body in bodies:
            if a in names and bone == names[a] and body.shape == 2:
                radius = round(body.size[0], 4)
                break
        out.append([side, kind, a, b, radius])
    return out


def _skirt_joints(doc):
    """per skirt body 'row_col': the joint that hangs it (named like the body): its parent body, the rotation limits per
    axis in degrees and the rotation springs"""
    names = [pmx_edit.rigid_names(doc, rb)[0] for rb in doc.rigid_bodies]
    out = {}
    for j in pmx_edit.joints(doc):
        m = SKIRT.match(j.name)
        if m and 0 <= j.a < len(names):
            out["%s_%s" % (m.group(1), m.group(2))] = {
                "parent": names[j.a],
                **{axis: [round(math.degrees(j.rotate_lower[k]), 3), round(math.degrees(j.rotate_upper[k]), 3)]
                   for k, axis in enumerate("xyz")},
                "spring": [round(v, 4) for v in j.spring_rotate]}
    return out


# ---- the camera -----------------------------------------------------------------------------------------------------

def _frame(cam):
    """eye, forward, right, up of `cam` (look, yaw, pitch in the window's degrees, distance, fov, size)"""
    ax, ay = math.radians(cam["pitch"]), math.radians(cam["yaw"])
    d = cam["distance"]
    lx, ly, lz = cam["look"]
    eye = (lx + d * math.sin(ay) * math.cos(ax), ly + d * math.sin(ax), lz - d * math.cos(ay) * math.cos(ax))
    fwd = (-math.sin(ay) * math.cos(ax), -math.sin(ax), math.cos(ay) * math.cos(ax))
    right = (math.cos(ay), 0.0, math.sin(ay))
    up = (fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2], fwd[0] * right[1] - fwd[1] * right[0])
    return eye, fwd, right, up


def _focal(cam):
    return (cam["size"][1] / 2.0) / math.tan(math.radians(cam["fov"]) / 2.0)


def project(point, cam):
    """(u, v): where MMD draws the world point in the picture of `cam` (continuous pixel coordinates, v down)"""
    eye, fwd, right, up = _frame(cam)
    p = [point[k] - eye[k] for k in range(3)]
    depth = sum(p[k] * fwd[k] for k in range(3))
    f = _focal(cam)
    w, h = cam["size"]
    return (w / 2.0 + f * sum(p[k] * right[k] for k in range(3)) / depth, h / 2.0 - f * sum(p[k] * up[k] for k in range(3)) / depth)


def height(v, cam):
    """the world height of a point drawn at picture row v by the horizontal camera `cam`, its depth taken as the
    camera's distance"""
    if abs(cam["pitch"]) > 1e-9:
        raise ValueError("height() needs a horizontal camera (pitch 0)")
    return cam["look"][1] + (cam["size"][1] / 2.0 - v) * cam["distance"] / _focal(cam)


def write_camera(path, cam, last_frame=7742):
    """a camera motion that holds `cam` still from frame 0 to last_frame"""
    if float(cam["fov"]) != int(round(cam["fov"])):
        raise ValueError("MMD's view angle is a whole number of degrees")
    key = dict(distance=-float(cam["distance"]), position=tuple(float(v) for v in cam["look"]),
               rotation=(-math.radians(cam["pitch"]), math.radians(cam["yaw"]), 0.0), fov=int(round(cam["fov"])))
    keys = [vmd.CameraKey(frame=0, **key)] + ([vmd.CameraKey(frame=last_frame, **key)] if last_frame > 0 else [])
    _write(path, vmd.dumps(vmd.Motion.for_camera(cameras=keys)))


def look_around(model_path, dance_path, first, last):
    """the look-at point for a still camera on frames first..last: the mean of 下半身 there, HEIGHT_OVER_HIPS lower"""
    from mmd_cli import fk
    from mmd_cli.formats import pmx
    track = fk.world_track(pmx.load(model_path), vmd.load(dance_path), ["下半身"], first, last)["下半身"]
    n = len(track)
    return [sum(p[0][k] for p in track) / n + (HEIGHT_OVER_HIPS if k == 1 else 0.0) for k in range(3)]


# ---- the markers in the pictures ------------------------------------------------------------------------------------

def _lut(tol=TOL):
    import numpy as np
    lut = np.full(256, -1, np.int16)
    for i, level in enumerate(LEVELS):
        lo, hi = max(0, level - tol), min(255, level + tol)
        lut[lo:hi + 1] = i
    return lut


def _code(colour):
    return LEVELS.index(colour[0]) * 36 + LEVELS.index(colour[1]) * 6 + LEVELS.index(colour[2])


def find_markers(img, colours, tol=TOL, lut=None):
    """{index into colours: (u, v, pixels)} for the colours drawn in `img` (H x W x 4, BGRA as MMD writes it): the
    centre of the opaque pixels whose every channel lies within tol of the colour's"""
    import numpy as np
    lut = _lut(tol) if lut is None else lut
    opaque = img[..., 3] == 255
    ir, ig, ib = lut[img[..., 2]], lut[img[..., 1]], lut[img[..., 0]]
    ok = opaque & (ir >= 0) & (ig >= 0) & (ib >= 0)
    vs, us = np.nonzero(ok)
    if not len(us):
        return {}
    code = (ir[vs, us].astype(np.int32) * 36 + ig[vs, us] * 6 + ib[vs, us])
    count = np.bincount(code, minlength=216)
    su = np.bincount(code, weights=us + 0.5, minlength=216)
    sv = np.bincount(code, weights=vs + 0.5, minlength=216)
    out = {}
    for i, c in enumerate(colours):
        k = _code(c)
        if count[k]:
            out[i] = (float(su[k] / count[k]), float(sv[k] / count[k]), int(count[k]))
    return out


def avi_frames(path, size):
    """the pictures of an AVI as H x W x 4 BGRA arrays (ffmpeg)"""
    import numpy as np
    w, h = size
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "bgra", "-"], stdout=subprocess.PIPE)
    n = w * h * 4
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, np.uint8).reshape(h, w, 4)
    finally:
        p.stdout.close()
        p.wait()


def track(avi, legend, cam, first=0, fps=60):
    """per picture of the AVI: the song frame and every marker's (u, v, pixels) or None"""
    colours = [tuple(m["colour"]) for m in legend["markers"]]
    lut = _lut()
    rows = []
    for k, img in enumerate(avi_frames(avi, cam["size"])):
        found = find_markers(img, colours, lut=lut)
        rows.append({"picture": k, "song_frame": first + k * 30.0 / fps,
                     "markers": [list(found[i]) if i in found else None for i in range(len(colours))]})
    return {"avi": os.path.abspath(avi), "camera": cam, "first": first, "fps": fps, "pictures": rows}


# ---- angles ---------------------------------------------------------------------------------------------------------

def chain_angles(ys, lengths):
    """(tilt of every body in degrees from hanging straight down, or None; the hem's elevation in degrees, or None)
    from the heights ys of a column's bones (None where not seen) and the rest lengths between them"""
    tilt = []
    for r, length in enumerate(lengths):
        a, b = ys[r], ys[r + 1]
        if a is None or b is None:
            tilt.append(None)
            continue
        c = max(-1.0, min(1.0, -(b - a) / length))
        tilt.append(math.degrees(math.acos(c)))
    hem = None
    if ys[0] is not None and ys[-1] is not None:
        hem = math.degrees(math.asin(max(-1.0, min(1.0, (ys[-1] - ys[0]) / sum(lengths)))))
    return tilt, hem


def occluded(tracked, share=0.4):
    """per marker the pixel count below which it counts as hidden (share of its median count over the pictures)"""
    counts = {}
    for row in tracked["pictures"]:
        for i, m in enumerate(row["markers"]):
            if m is not None:
                counts.setdefault(i, []).append(m[2])
    out = {}
    for i, c in counts.items():
        c = sorted(c)
        out[i] = share * c[len(c) // 2]
    return out


def angles(tracked, legend):
    """per picture and column: the bodies' tilts and the hem's elevation (markers seen only in part are left out)"""
    cam = tracked["camera"]
    rows, cols = legend["rows"], legend["cols"]
    where = {(m["row"], m["col"]): m["index"] for m in legend["markers"] if m["kind"] == "skirt"}
    least = occluded(tracked)
    out = []
    for row in tracked["pictures"]:
        cols_out = []
        for c in range(cols):
            ys = []
            for r in range(rows):
                m = row["markers"][where[(r, c)]]
                ys.append(height(m[1], cam) if m is not None and m[2] >= least.get(where[(r, c)], 0) else None)
            tilt, hem = chain_angles(ys, legend["lengths"][str(c)])
            cols_out.append({"tilt": [None if t is None else round(t, 3) for t in tilt],
                             "hem": None if hem is None else round(hem, 3),
                             "y": [None if y is None else round(y, 4) for y in ys]})
        out.append({"picture": row["picture"], "song_frame": row["song_frame"], "columns": cols_out})
    return {"camera": cam, "rows": rows, "cols": cols, "pictures": out}


# ---- three dimensions from two renders --------------------------------------------------------------------------------
#
# MMD's physics differs from render to render, but little: on the 213.4 s turn the markers' heights in three renders
# differed by 0.005-0.03 unit on average (0.2 at most).  So a side render (yaw +-90) and a front render (yaw 0 / 180) of
# the same span give every marker seen in both its three coordinates; the two heights must agree within max_gap.

MAX_GAP = 0.1
LENGTH_TOL = 0.15               # a body's two ends must lie its rest length apart within this share (the joints do not stretch)
CAPSULES = (("左", "leg", "左足D", "左ひざD", 0.987), ("右", "leg", "右足D", "右ひざD", 0.987),
            ("左", "arm", "左腕", "左ひじ", 0.395), ("右", "arm", "右腕", "右ひじ", 0.395),
            ("左", "arm", "左ひじ", "左手首", 0.296), ("右", "arm", "右ひじ", "右手首", 0.296))
# Sour's Rin's collision capsules: the thigh 右足/左足 (radius 0.987), the upper arm 右腕 (0.395), the forearm 右ひじ (0.296)


def _rows(cam, uv):
    """the two linear equations (n . P = n . eye) a picture point (u, v) gives on the world point P"""
    import numpy as np
    eye, fwd, right, up = (np.array(v) for v in _frame(cam))
    f = _focal(cam)
    w, h = cam["size"]
    ku, kv = (uv[0] - w / 2.0) / f, (h / 2.0 - uv[1]) / f
    nu, nv = right - ku * fwd, up - kv * fwd
    return (nu, float(nu @ eye)), (nv, float(nv @ eye))


def point_from_views(a, b, cam_a, cam_b):
    """(the world point drawn at a = (u, v) by cam_a and at b by cam_b, |its height from a - its height from b|)"""
    import numpy as np
    fa, fb = np.array(_frame(cam_a)[1]), np.array(_frame(cam_b)[1])
    if abs(float(fa @ fb)) > 0.5:
        raise ValueError("the two cameras must look across each other (side and front)")
    (ua, va), (ub, vb) = _rows(cam_a, a), _rows(cam_b, b)
    A = np.array([ua[0], va[0], ub[0], vb[0]])
    y = np.array([ua[1], va[1], ub[1], vb[1]])
    p = np.linalg.lstsq(A, y, rcond=None)[0]
    pa = np.linalg.solve(A[[0, 1, 2]], y[[0, 1, 2]])
    pb = np.linalg.solve(A[[0, 2, 3]], y[[0, 2, 3]])
    return p, float(abs(pa[1] - pb[1]))


def solve(track_a, track_b, legend, max_gap=MAX_GAP):
    """the markers' world positions picture by picture from a side and a front render of the same span"""
    pa, pb = track_a["pictures"], track_b["pictures"]
    if len(pa) != len(pb) or any(abs(x["song_frame"] - y["song_frame"]) > 1e-6 for x, y in zip(pa, pb)):
        raise ValueError("the two renders do not hold the same pictures (%d and %d)" % (len(pa), len(pb)))
    least_a, least_b = occluded(track_a), occluded(track_b)
    out = []
    for x, y in zip(pa, pb):
        points, gaps, rejected = [], [], 0
        for i in range(len(legend["markers"])):
            ma, mb = x["markers"][i], y["markers"][i]
            if ma is None or mb is None or ma[2] < least_a.get(i, 0) or mb[2] < least_b.get(i, 0):
                points.append(None)
                gaps.append(None)
                continue
            p, gap = point_from_views(ma[:2], mb[:2], track_a["camera"], track_b["camera"])
            if gap > max_gap:
                rejected += 1
                points.append(None)
            else:
                points.append([round(float(v), 5) for v in p])
            gaps.append(round(gap, 5))
        out.append({"picture": x["picture"], "song_frame": x["song_frame"], "points": points, "gaps": gaps,
                    "rejected": rejected})
    return {"cameras": [track_a["camera"], track_b["camera"]], "max_gap": max_gap, "pictures": out}


def tilt(p, q):
    """degrees between p -> q and straight down"""
    d = [q[k] - p[k] for k in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    return math.degrees(math.acos(max(-1.0, min(1.0, -d[1] / n))))


def _angle(a, b):
    na, nb = math.sqrt(sum(v * v for v in a)), math.sqrt(sum(v * v for v in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


def bends(now, rest):
    """per inner point of a chain: the angle between the links meeting there, less the same angle at rest (None where a
    point is missing)"""
    out = []
    for k in range(1, len(now) - 1):
        a, b, c = now[k - 1], now[k], now[k + 1]
        if a is None or b is None or c is None:
            out.append(None)
            continue
        d0, d1 = [b[i] - a[i] for i in range(3)], [c[i] - b[i] for i in range(3)]
        r0 = [rest[k][i] - rest[k - 1][i] for i in range(3)]
        r1 = [rest[k + 1][i] - rest[k][i] for i in range(3)]
        out.append(_angle(d0, d1) - _angle(r0, r1))
    return out


def capsule_depth(p, a, b, r):
    """how deep p lies inside the capsule of radius r round the segment a-b (0 outside)"""
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    t = max(0.0, min(1.0, sum(x * y for x, y in zip(ab, ap)) / max(1e-12, sum(x * x for x in ab))))
    d = math.sqrt(sum((ap[i] - t * ab[i]) ** 2 for i in range(3)))
    return max(0.0, r - d)


def rotation_y(angle):
    import numpy as np
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def fit_rigid(src, dst):
    """(R, t) with dst ~ R src + t (least squares, Kabsch)"""
    import numpy as np
    a, b = np.array(src, float), np.array(dst, float)
    ca, cb = a.mean(0), b.mean(0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return rot, cb - rot @ ca


def analyze(solved, legend):
    """per picture: per column the bodies' tilts, the hem's elevation, the spread of the waist-to-hem line, the bends at
    the joints (against rest), the root body's turn on the waist (the ring's fitted frame); how many bodies point above
    horizontal; how deep skirt markers sit in the thigh and arm capsules"""
    import numpy as np
    rows, cols = legend["rows"], legend["cols"]
    skirt = {(m["row"], m["col"]): m for m in legend["markers"] if m["kind"] == "skirt"}
    body = {m["name"]: m["index"] for m in legend["markers"] if m["kind"] == "body"}
    caps = [c for c in legend.get("capsules", CAPSULES) if c[2] in body and c[3] in body]
    out = []
    for pic in solved["pictures"]:
        pts = pic["points"]
        ring = [(skirt[(0, c)]["rest"], pts[skirt[(0, c)]["index"]]) for c in range(cols)]
        ring = [(a, b) for a, b in ring if b is not None]
        rot = fit_rigid([a for a, _ in ring], [b for _, b in ring])[0] if len(ring) >= 3 else None
        columns, up, top, doubtful = [], 0, None, 0
        for c in range(cols):
            chain = [pts[skirt[(r, c)]["index"]] for r in range(rows)]
            rest = [skirt[(r, c)]["rest"] for r in range(rows)]
            # a body whose ends are not its rest length apart was mismeasured (a marker taken for another or half hidden):
            # drop the points every body touching them disowns
            bad = []
            for r, length in enumerate(legend["lengths"][str(c)]):
                a, b = chain[r], chain[r + 1]
                bad.append(a is not None and b is not None and abs(math.dist(a, b) / length - 1.0) > LENGTH_TOL)
            doubtful += sum(bad)
            for r in range(rows):
                touching = [bad[k] for k in (r - 1, r) if 0 <= k < len(bad)]
                if touching and all(touching):
                    chain[r] = None
            tilts = [None if a is None or b is None else round(tilt(a, b), 3) for a, b in zip(chain, chain[1:])]
            length = sum(legend["lengths"][str(c)])
            hem = spread = None
            if chain[0] is not None and chain[-1] is not None:
                hem = round(math.degrees(math.asin(max(-1.0, min(1.0, (chain[-1][1] - chain[0][1]) / length)))), 3)
                spread = round(tilt(chain[0], chain[-1]), 3)
            root = None
            if rot is not None and chain[0] is not None and chain[1] is not None:
                rest_dir = rot @ (np.array(rest[1]) - np.array(rest[0]))
                root = round(_angle(rest_dir, [chain[1][k] - chain[0][k] for k in range(3)]), 3)
            for t in tilts:
                if t is not None:
                    up += t > 90.0
                    top = t if top is None or t > top else top
            columns.append({"tilt": tilts, "hem": hem, "spread": spread, "root_turn": root,
                            "bend": [None if b is None else round(b, 3) for b in bends(chain, rest)]})
        contact = {}
        for kind in ("leg", "arm"):
            deepest, inside = None, 0
            for side, k, a_name, b_name, radius in caps:
                if k != kind:
                    continue
                a, b = pts[body[a_name]], pts[body[b_name]]
                if a is None or b is None:
                    continue
                for (r, c), m in skirt.items():
                    p = pts[m["index"]]
                    if p is None:
                        continue
                    d = capsule_depth(p, a, b, radius)
                    if d > 0:
                        inside += 1
                        if deepest is None or d > deepest["depth"]:
                            deepest = {"depth": round(d, 4), "row": r, "col": c, "side": side, "from": a_name}
            contact[kind] = {"max_depth": deepest["depth"] if deepest else 0.0, "deepest": deepest, "inside": inside}
        out.append({"picture": pic["picture"], "song_frame": pic["song_frame"], "columns": columns, "up": int(up),
                    "max_tilt": top, "doubtful": doubtful, "legs": contact["leg"], "arms": contact["arm"]})
    return {"rows": rows, "cols": cols, "pictures": out}


# ---- the command line -----------------------------------------------------------------------------------------------

def _write(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


def _json(path, value):
    _write(path, (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("markers", help="write the measuring copy of a model and its legend")
    s.add_argument("model")
    s.add_argument("out")
    s.add_argument("--legend", required=True)
    s.add_argument("--size", type=float, default=SIZE)
    s = sub.add_parser("camera", help="write a still, horizontal camera (and its numbers next to it as .json)")
    s.add_argument("out")
    s.add_argument("--look", type=float, nargs=3)
    s.add_argument("--around", nargs=4, metavar=("MODEL", "DANCE", "FIRST", "LAST"),
                   help="look at the mean of 下半身 over these frames of the dance (%g lower)" % -HEIGHT_OVER_HIPS)
    s.add_argument("--yaw", type=float, default=CAMERA["yaw"])
    s.add_argument("--distance", type=float, default=CAMERA["distance"])
    s.add_argument("--fov", type=float, default=CAMERA["fov"])
    s.add_argument("--size", type=int, nargs=2, default=CAMERA["size"])
    s.add_argument("--last-frame", type=int, default=7742)
    s = sub.add_parser("track", help="find the markers in every picture of an AVI")
    s.add_argument("avi")
    s.add_argument("legend")
    s.add_argument("camera", help="the camera's .json written by `camera`")
    s.add_argument("out")
    s.add_argument("--first", type=float, default=0.0, help="the song frame of the AVI's first picture")
    s.add_argument("--fps", type=float, default=60.0)
    s = sub.add_parser("angles", help="the skirt bodies' tilts and the hem's elevation per picture (one side render)")
    s.add_argument("track")
    s.add_argument("legend")
    s.add_argument("out")
    s = sub.add_parser("solve", help="the markers' world positions from a side and a front render of the same span")
    s.add_argument("side", help="the track of the side render (yaw 90 or -90)")
    s.add_argument("front", help="the track of the front render (yaw 0 or 180)")
    s.add_argument("legend")
    s.add_argument("out")
    s.add_argument("--max-gap", type=float, default=MAX_GAP, help="the most the two heights may differ (default %g)" % MAX_GAP)
    s = sub.add_parser("analyze", help="tilts, bends, spread and contact with legs and arms per picture (from solve)")
    s.add_argument("solved")
    s.add_argument("legend")
    s.add_argument("out")
    a = ap.parse_args(argv)
    try:
        if a.command == "markers":
            if _same(a.model, a.out) or _same(a.model, a.legend) or _same(a.out, a.legend):
                raise ValueError("the outputs would overwrite the model or each other")
            doc = pmx_edit.load(a.model)
            legend = build_markers(doc, a.size)
            legend["model"] = os.path.abspath(a.model)
            _write(a.out, pmx_edit.dumps(doc))
            _json(a.legend, legend)
            result = {"out": os.path.abspath(a.out), "markers": len(legend["markers"]), "rows": legend["rows"],
                      "cols": legend["cols"], "missing_body": legend["missing_body"]}
        elif a.command == "camera":
            if (a.look is None) == (a.around is None):
                raise ValueError("give --look or --around")
            look = a.look if a.look is not None else look_around(a.around[0], a.around[1], int(a.around[2]), int(a.around[3]))
            cam = {"look": [round(v, 6) for v in look], "yaw": a.yaw, "pitch": 0.0, "distance": a.distance, "fov": a.fov,
                   "size": list(a.size)}
            write_camera(a.out, cam, a.last_frame)
            _json(os.path.splitext(a.out)[0] + ".json", cam)
            result = {"out": os.path.abspath(a.out), "camera": cam}
        elif a.command == "track":
            with open(a.legend, encoding="utf-8") as f:
                legend = json.load(f)
            with open(a.camera, encoding="utf-8") as f:
                cam = json.load(f)
            tracked = track(a.avi, legend, cam, a.first, a.fps)
            _json(a.out, tracked)
            seen = [sum(1 for m in row["markers"] if m is not None) for row in tracked["pictures"]]
            result = {"out": os.path.abspath(a.out), "pictures": len(seen), "seen_min": min(seen) if seen else 0,
                      "seen_max": max(seen) if seen else 0, "markers": len(legend["markers"])}
        elif a.command == "angles":
            with open(a.track, encoding="utf-8") as f:
                tracked = json.load(f)
            with open(a.legend, encoding="utf-8") as f:
                legend = json.load(f)
            out = angles(tracked, legend)
            _json(a.out, out)
            hems = [c["hem"] for p in out["pictures"] for c in p["columns"] if c["hem"] is not None]
            result = {"out": os.path.abspath(a.out), "pictures": len(out["pictures"]),
                      "hem_max": max(hems) if hems else None}
        elif a.command == "solve":
            loaded = []
            for path in (a.side, a.front, a.legend):
                with open(path, encoding="utf-8") as f:
                    loaded.append(json.load(f))
            out = solve(loaded[0], loaded[1], loaded[2], a.max_gap)
            _json(a.out, out)
            seen = [sum(1 for p in pic["points"] if p is not None) for pic in out["pictures"]]
            result = {"out": os.path.abspath(a.out), "pictures": len(seen), "seen_min": min(seen) if seen else 0,
                      "rejected": sum(pic["rejected"] for pic in out["pictures"])}
        else:
            with open(a.solved, encoding="utf-8") as f:
                solved = json.load(f)
            with open(a.legend, encoding="utf-8") as f:
                legend = json.load(f)
            out = analyze(solved, legend)
            _json(a.out, out)
            tops = [p["max_tilt"] for p in out["pictures"] if p["max_tilt"] is not None]
            result = {"out": os.path.abspath(a.out), "pictures": len(out["pictures"]), "max_tilt": max(tops) if tops else None,
                      "pictures_up": sum(1 for p in out["pictures"] if p["up"])}
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict(ok=True, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
