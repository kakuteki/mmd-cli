"""The stage in the world (tools/mv_look.py with the look setting "stage": {"world": 1}): the backdrop, the beams, the specks
and the floor drawn frame by frame from the camera of the camera motion (.vmd) MMD renders the dancer with, so that they
move as a stage does when the camera turns, rises or comes closer.

    python tools/mv_world.py frame CAMERA.vmd look.json OUT.png --frame N [--size 1280x720] [--model M.pmx --motion D.vmd ...]

Before this, mv_look laid a plate and a loop of light fixed to the picture behind the dancer: when the camera swung 44
degrees round her, the backdrop moved 0 px where a far one moves some 1,300 (the analysis of 2026-10-07, a16), and the
floor MMD drew was black with nothing under her feet.  Here the same pieces lie in the world:

* the cyc: the plate on a vertical cylinder of `radius` round the stage centre (0 makes it infinitely far: only the turn of
  the camera moves it).  Its haze band and its pool of light are where the camera the look was made for (REFERENCE: 38 in
  front of the stage centre, 13 up, level, a view angle of 30) saw them on the plate, so that camera sees the plate of
  before; any other camera sees the cyc from where it is.  The plate's darker sides (plate.vignette) are paint of the cyc
  too: fixed to the picture they would follow the camera and hold the backdrop back (the lens darkens the picture's corners);
* the beams: the fan of `beams` hangs from a truss `truss` behind the stage centre, at the height where the reference camera
  saw the fan's origin (35 % of the picture's height above it), each beam a cone from the truss to the floor, fading
  downwards as it did on the picture;
* the specks: on the cyc (a little in front of it, each at its own depth) over `specks` degrees round the stage centre, as
  many per degree as the plate had per picture, drifting and twinkling as before;
* the floor (`floor` 1): the floor of tools/make_stage.py (a line every `floor_step`, amber every `floor_accent_every`-th,
  `floor_half` to each side, at the height `floor_y`: its --height; 0.111 is where the model's soles stand) in the colours v7
  showed it, so MMD renders the dancer without the floor accessory.  It can take a
  pool of light round the dancer (`pool`) and the shadows of her feet and body (`shadow`), both from her motion (Figure):
  the ankles and toes (the IK bones), the pelvis and the centre, by forward kinematics (mmd_cli/fk.py).

A frame of the stage is drawn at the moment of its video frame; with motion blur (the dancer rendered at `subframes` times the
rate and `shutter` of each frame averaged: mv_look --subframes 8 --shutter 0.5 averages subframes 0..3) the camera is the one
MMD draws those subframes with (view_at: between keys one frame apart MMD keeps the earlier one, so a camera with a key on every
frame, as all the MV's are, stands still for the 8 subframes and only the dancer moves).  Where the camera does move while the
shutter is open (keys further apart) the floor is the average of those moments, and the rest is drawn at their mean.  The
camera follows the module docstring of mmd_cli/fk.py; the projection was checked against MMD's own render of the floor (to
0.15 px at two frames of the MV's camera, tests/test_mv_world.py).  A camera that turns about its line of sight (window Z) is
refused: which way MMD turns the picture has not been measured.
"""
import argparse
import bisect
import copy
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, vmd  # noqa: E402

SONG_FPS = 30                    # MMD's frames of the song (mv_look's SONG_FPS)
LIGHT_SCALE = 2                  # the backdrop and the light are drawn at half size: they are all blur (mv_look's LIGHT_SCALE)
REFERENCE_HEIGHT = 720.0         # lengths of the look are pixels of a 720 line picture (mv_look)
# the camera the picture-fixed look was made for: 38 in front of the stage centre, 13 up, level (make_camera's shots)
REFERENCE = {"look_at": (0.0, 13.0, 0.0), "distance": 38.0, "fov": 30.0}
# where the old fan of beams had its origin: above the middle of the picture by 35 % of its height (mv_look._beams)
BEAM_ORIGIN = (0.5, -0.35)
# (the settings of the stage, look["stage"], and their defaults are mv_look's DEFAULT_LOOK["stage"])
# the floor of tools/make_stage.py as v7 showed it.  Its materials are emissive only (the plane 0.03, 0.045, 0.09 at alpha
# 0.92; a line 0.70, 0.82, 1.00 at 0.55 over it; an accent 1.00, 0.63, 0.19 at 0.80), MMD writes the colour multiplied by
# the alpha, the 240 fps fold multiplies it again and the overlay a third time (it takes the colour as straight): the plane
# 0.92^3 x (7.65, 11.5, 23).  Measured on v7 at 3445 between the lines (6, 9, 18 under the 8 % of the stage that shows
# through, the grain and the vignette)
FLOOR_COLOURS = {"plane": (6.0, 9.0, 17.9), "line": (93.9, 110.9, 138.3), "accent": (198.9, 126.5, 41.6)}
FLOOR_SEE_THROUGH = 0.08         # the old floor let 8 % of the stage behind it through (its alpha 0.92): kept
NEAR = 0.1                       # nothing nearer the camera than this is drawn (MMD units)


# ---- the camera -----------------------------------------------------------------------------

class View:
    """the camera of a camera state (fk.CameraState: the window's look-at point, distance, angles and view angle) on a
    picture of `size`: where it is, which way it looks, and how a world point lands on the picture.  Pixel coordinates are
    those of the picture's pixels (pixel i is at i; MMD's picture is centred on (w / 2, h / 2): measured on its render)"""

    def __init__(self, state, size):
        if abs(state.angles[2]) > 1e-6:
            raise ValueError("the camera turns about its line of sight (window Z %.3f degrees at frame %s): the stage in the "
                             "world does not know which way MMD turns the picture then" % (state.angles[2], state.frame))
        if abs(state.angles[0]) >= 90.0:
            raise ValueError("the camera looks over the top (window X %.3f degrees at frame %s)" % (state.angles[0], state.frame))
        self.size = (int(size[0]), int(size[1]))
        self.eye = np.array(fk.camera_position(state), dtype=np.float64)
        self.forward = np.array(fk.camera_direction(state), dtype=np.float64)
        ax, ay = math.radians(state.angles[0]), math.radians(state.angles[1])
        # MMD turns the camera by X, then Y: the picture's right and up are the window's Y and X turns of +X and +Y
        self.right = np.array([math.cos(ay), 0.0, math.sin(ay)])
        self.up = np.array([-math.sin(ax) * math.sin(ay), math.cos(ax), math.sin(ax) * math.cos(ay)])
        self.focal = (self.size[1] / 2.0) / math.tan(math.radians(state.fov) / 2.0)

    def project(self, points):
        """(u, v, depth) of world points: pixels of the picture and the distance along the line of sight"""
        d = np.asarray(points, dtype=np.float64).reshape(-1, 3) - self.eye
        depth = d @ self.forward
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.size[0] / 2.0 + self.focal * (d @ self.right) / depth
            v = self.size[1] / 2.0 - self.focal * (d @ self.up) / depth
        return u, v, depth

    def rays(self, scale=1):
        """[rows, columns, 3] directions (not of unit length) through the pixels of a picture `scale` times smaller: its
        pixel j covers the pixels j * scale .. (j + 1) * scale - 1 of the full one"""
        w, h = self.size[0] // scale, self.size[1] // scale
        us = (np.arange(w) + 0.5) * scale - 0.5 - self.size[0] / 2.0
        vs = (np.arange(h) + 0.5) * scale - 0.5 - self.size[1] / 2.0
        return (self.forward * self.focal)[None, None, :] + us[None, :, None] * self.right - vs[:, None, None] * self.up


def reference_view(size):
    """the camera the picture-fixed look was made for (REFERENCE)"""
    return View(fk.CameraState(0, REFERENCE["look_at"], REFERENCE["distance"], (0.0, 0.0, 0.0), REFERENCE["fov"]), size)


def camera_track(path):
    """(keys, frames) of a camera motion: what view_at reads.  Every key is looked at here, so that a camera the stage cannot
    be drawn for stops a render or a prepare before its first frame (View refuses the same while drawing): one that turns
    about its line of sight (window Z: which way MMD turns the picture has not been measured), one that looks over the top
    (window X of 90 degrees or more) and an orthographic one (perspective off: the stage is drawn in perspective)"""
    try:
        keys = fk.camera_keys(vmd.load(path))
    except OSError as exc:
        raise ValueError("cannot read the camera motion %s: %s" % (path, exc))
    for k in keys:
        roll, tilt = math.degrees(k.rotation[2]), -math.degrees(k.rotation[0])
        if abs(roll) > 1e-6:
            raise ValueError("the camera turns about its line of sight (window Z %.3f degrees) at frame %d of %s: the stage in "
                             "the world does not know which way MMD turns the picture then" % (roll, k.frame, path))
        if abs(tilt) >= 90.0:
            raise ValueError("the camera looks over the top (window X %.3f degrees) at frame %d of %s" % (tilt, k.frame, path))
        if not k.perspective:
            raise ValueError("the camera is orthographic (perspective off) at frame %d of %s: the stage in the world is drawn "
                             "in perspective" % (k.frame, path))
    return keys, [k.frame for k in keys]


def view_at(track, frame, size):
    """the camera at `frame` of the song as MMD draws it at a higher rate: between two keys one frame apart it keeps the
    earlier key (the camera of a cut, or of a motion with a key on every frame, moves at whole frames only), between keys
    further apart it follows their curve (fk.camera_at).  Measured on 240 fps renders of the cameras D, A and B and of a
    camera with keys 2 and 1 frames apart (review of stage-world, R1 and R1b)"""
    keys, frames = track
    i = bisect.bisect_right(frames, frame)
    if 0 < i < len(frames) and frames[i] - frames[i - 1] == 1:
        frame = frames[i - 1]
    return View(fk.camera_at(keys, frame, frames), size)


# ---- the cyc --------------------------------------------------------------------------------

def _reference_focal(size):
    return (size[1] / 2.0) / math.tan(math.radians(REFERENCE["fov"]) / 2.0)


def _cyc_place(view, scale, radius):
    """(theta, psi) of the cyc where the rays of the pixels meet it: theta the angle round the stage centre from the front
    (+Z, the back of the stage seen from the front) towards +X, psi the height as the angle the reference camera would see
    it at from the back (infinitely far: the ray's own direction).  A ray that does not meet the cyc (straight up, or a
    camera outside it looking away) takes its direction"""
    d = view.rays(scale)
    horizontal = np.hypot(d[..., 0], d[..., 2])
    theta = np.arctan2(d[..., 0], d[..., 2])
    psi = np.arctan2(d[..., 1], horizontal)
    if radius <= 0:
        return theta, psi
    e = view.eye
    a = horizontal ** 2
    b = 2.0 * (e[0] * d[..., 0] + e[2] * d[..., 2])
    c = e[0] ** 2 + e[2] ** 2 - radius ** 2
    disc = b * b - 4.0 * a * c
    ok = (a > 1e-12) & (disc >= 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (-b + np.sqrt(np.where(ok, disc, 0.0))) / (2.0 * np.where(ok, a, 1.0))
    ok &= t > 0
    t = np.where(ok, t, 0.0)
    x, y, z = e[0] + t * d[..., 0], e[1] + t * d[..., 1], e[2] + t * d[..., 2]
    theta = np.where(ok, np.arctan2(x, z), theta)
    psi = np.where(ok, np.arctan2(y - REFERENCE["look_at"][1], radius + REFERENCE["distance"]), psi)
    return theta, psi


def _seen_from_the_front(theta, radius):
    """the angle off the line of sight at which the reference camera sees the cyc at `theta`"""
    if radius <= 0:
        return theta
    return np.arctan2(radius * np.sin(theta), radius * np.cos(theta) + REFERENCE["distance"])


def backdrop(view, look, scale=LIGHT_SCALE):
    """[rows, columns, 3] floats: the cyc as `view` sees it, on a picture `scale` times smaller.  The plate of the look
    (mv_look.plate), its darker sides included, is painted on it as the reference camera saw it"""
    settings = look["plate"]
    radius = float(look["stage"]["radius"])
    theta, psi = _cyc_place(view, scale, radius)
    size = view.size
    focal = _reference_focal(size)
    ys = 0.5 - np.tan(np.clip(psi, -1.5, 1.5)) * focal / size[1]                 # the plate's height, 0 top to 1 bottom
    alpha = _seen_from_the_front(theta, radius)
    front = np.abs(alpha) < math.radians(89.0)
    xs = np.where(front, np.tan(np.where(front, alpha, 0.0)) * focal / (size[0] / 2.0), 1e3)       # -1 left to 1 right
    haze = np.exp(-((ys - float(settings["horizon"])) / 0.22) ** 2)
    pool = np.exp(-((xs / 0.55) ** 2 + ((ys - 0.52) / 0.42) ** 2))
    img = (np.array(settings["base"], dtype=np.float64)[None, None, :]
           + haze[..., None] * np.array(settings["haze"], dtype=np.float64)[None, None, :] * 0.55
           + pool[..., None] * np.array(settings["pool"], dtype=np.float64)[None, None, :] * 0.55)
    # the plate's darker sides, top and bottom are paint of the cyc too (where the reference camera saw them): a darkening
    # fixed to the picture would follow the camera and hold the backdrop back (the lens's vignette darkens the picture)
    dark = 1.0 - float(settings["vignette"]) * np.clip(xs ** 2 + (2.0 * ys - 1.0) ** 2 * 0.6, 0.0, 1.0)
    return img * dark[..., None]


# ---- the light ------------------------------------------------------------------------------

def _unit(i, salt):
    """a fixed number in 0..1 for the i-th thing (mv_look._unit: the same beams and specks as the picture-fixed light)"""
    return (math.sin(i * 12.9898 + salt * 78.233) * 43758.5453) % 1.0


def _origin_elevation(size):
    return math.atan((0.5 - BEAM_ORIGIN[1]) * size[1] / _reference_focal(size))


def truss_point(look, size=(1280, 720)):
    """where the beams start: `truss` behind the stage centre, as high as the reference camera saw the fan's origin"""
    z = float(look["stage"]["truss"])
    height = REFERENCE["look_at"][1] + math.tan(_origin_elevation(size)) * (z + REFERENCE["distance"])
    return (0.0, height, z)


def _polygon_on(view, scale, corners):
    """the corners on the picture at `scale`, or None when one lies behind the camera"""
    u, v, depth = view.project(corners)
    if (depth <= NEAR).any():
        return None
    limit = 20.0 * max(view.size)
    return [(float(np.clip(a, -limit, limit)) / scale, float(np.clip(b, -limit, limit)) / scale) for a, b in zip(u, v)]


def beams(view, look, phase, scale=LIGHT_SCALE):
    """[rows, columns, 3] floats on black: the fan of beams from the truss to the floor, as `view` sees it.  Each beam
    is a cone, drawn in pieces whose shade fades from 1 at the top of the reference picture to 0.25 at its bottom along the
    beam (the picture-fixed beams faded so down the picture)"""
    settings = look["beams"]
    w, h = view.size[0] // scale, view.size[1] // scale
    count = int(settings["count"])
    if count <= 0 or settings["opacity"] <= 0:
        return np.zeros((h, w, 3), dtype=np.float64)
    layer = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    source = np.array(truss_point(look, view.size))
    reference = reference_view(view.size)
    warm_every = int(settings["warm_every"])
    pieces = 12
    for i in range(count):
        centre = -settings["spread"] / 2.0 + settings["spread"] * (i + 0.5) / count
        sway = settings["sway"] * math.sin(settings["cycles"][i % 2] * phase + 2.0 * math.pi * _unit(i, 1))
        angle = math.radians(centre + sway)
        half = math.radians(2.0 + 2.5 * _unit(i, 2))
        tone = 0.55 + 0.45 * _unit(i, 3)
        colour = settings["warm"] if warm_every > 0 and i % warm_every == warm_every - 1 else settings["cool"]
        if math.cos(angle) <= 1e-3:
            continue
        direction = np.array([math.sin(angle), -math.cos(angle), 0.0])       # down the fan's plane, z = truss
        length = source[1] / math.cos(angle)                                  # to the floor
        towards = view.eye - source
        side = np.cross(direction, towards)
        norm = np.linalg.norm(side)
        side = side / norm if norm > 1e-9 else np.array([math.cos(angle), math.sin(angle), 0.0])
        for k in range(pieces):
            t0, t1 = length * k / pieces, length * (k + 1) / pieces
            corners = [source + direction * t0 + side * t0 * math.tan(half), source + direction * t1 + side * t1 * math.tan(half),
                       source + direction * t1 - side * t1 * math.tan(half), source + direction * t0 - side * t0 * math.tan(half)]
            polygon = _polygon_on(view, scale, corners)
            if polygon is None:
                continue
            middle = source + direction * (t0 + t1) / 2.0
            seen = float(reference.project([middle])[1][0]) / view.size[1]
            fade = min(1.0, max(0.25, 1.0 - 0.75 * seen))
            draw.polygon(polygon, fill=tuple(int(c * tone * fade) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, w * 0.022)))
    return np.asarray(layer, dtype=np.float64) * float(settings["opacity"])


def _cyc_span(look, size):
    """the degrees round the stage centre the reference picture shows of the cyc (infinitely far: its width)"""
    radius = float(look["stage"]["radius"])
    edge = math.atan((size[0] / 2.0) / _reference_focal(size))
    if radius <= 0:
        return 2.0 * math.degrees(edge)
    d = REFERENCE["distance"]
    lo, hi = 0.0, math.pi
    for _ in range(60):                                   # theta whose cyc point the reference camera sees at the edge
        mid = (lo + hi) / 2.0
        if math.atan2(radius * math.sin(mid), radius * math.cos(mid) + d) < edge:
            lo = mid
        else:
            hi = mid
    return 2.0 * math.degrees(lo)


def specks(view, look, phase, scale=LIGHT_SCALE):
    """[rows, columns, 3] floats on black: the specks on the cyc as `view` sees them.  The plate had bokeh.count of them on
    the reference picture; the cyc has as many per degree over `specks` degrees, each a little in front of it (up to 15 % of
    the radius) and as high as the reference camera saw it, drifting and twinkling as before"""
    settings = look["bokeh"]
    w, h = view.size[0] // scale, view.size[1] // scale
    if int(settings["count"]) <= 0 or settings["opacity"] <= 0:
        return np.zeros((h, w, 3), dtype=np.float64)
    radius = float(look["stage"]["radius"])
    spread = float(look["stage"]["specks"])
    span = _cyc_span(look, view.size)
    count = max(1, int(round(int(settings["count"]) * spread / span)))
    layer = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    seed = float(settings["seed"])
    drift, flicker = (float(c) for c in settings["cycles"])
    focal = _reference_focal(view.size)
    tall = view.size[1] / focal                           # the tangent of the angle the reference picture's height spans
    for i in range(count):
        theta = math.radians(-spread / 2.0 + spread * _unit(i, seed + 1)
                             + 0.02 * span * math.sin(drift * phase + 2.0 * math.pi * _unit(i, seed + 2)))
        ys = _unit(i, seed + 3) * 0.9 + 0.03 * math.sin(drift * phase + 2.0 * math.pi * _unit(i, seed + 4))
        rise = (0.5 - ys) * tall
        if radius > 0:
            r = radius * (0.85 + 0.15 * _unit(i, seed + 9))
            y = REFERENCE["look_at"][1] + rise * (radius + REFERENCE["distance"])
            point = (r * math.sin(theta), y, r * math.cos(theta))
        else:
            far = 1e6
            point = tuple(view.eye + far * np.array([math.sin(theta), rise, math.cos(theta)]))
        u, v, depth = view.project([point])
        if depth[0] <= NEAR:
            continue
        x, y2 = float(u[0]) / scale, float(v[0]) / scale
        size = (3.0 + 11.0 * _unit(i, seed + 5)) * h / REFERENCE_HEIGHT * LIGHT_SCALE / 2.0 + 1.0
        if not (-3 * size < x < w + 3 * size and -3 * size < y2 < h + 3 * size):
            continue
        twinkle = 0.7 + 0.3 * math.sin(flicker * phase + 2.0 * math.pi * _unit(i, seed + 6))
        tone = (0.25 + 0.55 * _unit(i, seed + 7)) * twinkle
        colour = (255, 214, 150) if _unit(i, seed + 8) < settings["warm_share"] else (150, 180, 255)
        draw.ellipse([x - size, y2 - size, x + size, y2 + size], fill=tuple(int(c * tone) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, h * 0.014)))
    return np.asarray(layer, dtype=np.float64) * float(settings["opacity"])


# ---- the floor ------------------------------------------------------------------------------

def _overlap(dist, width, half):
    """the share of a pixel's footprint `width` wide, `dist` from a line's middle, that the line `half` to each side covers"""
    lo, hi = dist - width / 2.0, dist + width / 2.0
    return np.clip(np.minimum(hi, half) - np.maximum(lo, -half), 0.0, None) / width


def _edge_cover(view, d, axis, at, inside_below):
    """the share of each pixel on the floor's side of its edge `axis` = `at` (0 x, 2 z): the line's distance on the picture,
    in pixels, from where the floor plane meets it.  `inside_below` says the floor is where the coordinate is below `at`"""
    e = view.eye
    g = (e[axis] - at) * d[..., 1] - e[1] * d[..., axis]
    gu = (e[axis] - at) * view.right[1] - e[1] * view.right[axis]
    gv = -((e[axis] - at) * view.up[1] - e[1] * view.up[axis])
    norm = math.hypot(gu, gv)
    if norm < 1e-12:
        return np.ones(g.shape)
    # for a ray down to the floor (d_y < 0) the point is below `at` where g > 0
    signed = (g if inside_below else -g) / norm
    return np.clip(0.5 + signed, 0.0, 1.0)


def _seg_distance(px, pz, a, b):
    vx, vz = b[0] - a[0], b[1] - a[1]
    length = vx * vx + vz * vz
    t = np.clip(((px - a[0]) * vx + (pz - a[1]) * vz) / max(length, 1e-12), 0.0, 1.0)
    return np.hypot(px - (a[0] + t * vx), pz - (a[1] + t * vz))


def _shade(X, Z, figure, strength):
    """how much of the light the dancer keeps off the floor at (X, Z), 0 to 1: each foot's sole (from just behind the ankle
    to the toe) darkens the floor under it, less and more softly the higher it is; her body keeps some light off round
    where she stands"""
    keep = np.ones(X.shape)
    ankle_rest, toe_rest = figure.rest
    for ankle, toe in figure.feet:
        heel = (ankle[0] + 0.15 * (ankle[0] - toe[0]), ankle[2] + 0.15 * (ankle[2] - toe[2]))
        height = max(0.0, 0.5 * ((ankle[1] - ankle_rest) + (toe[1] - toe_rest)))
        amount = strength * 0.85 * math.exp(-height / 1.0)
        spread = 0.35 + 0.5 * height
        dist = _seg_distance(X, Z, heel, (toe[0], toe[2]))
        keep *= 1.0 - amount * np.exp(-dist ** 2 / (2.0 * spread ** 2))
    px, _, pz = figure.pelvis
    keep *= 1.0 - strength * 0.35 * np.exp(-((X - px) ** 2 + (Z - pz) ** 2) / (2.0 * 3.2 ** 2))
    return 1.0 - keep


# ---- the soft shadow of her body (stage.shadow_soft 1) ------------------------------------------

# where MMD's light shines to at its default (`light get` on a new project, 2026-10-17): the light MMD shades her with
MMD_LIGHT = (-0.5, -1.0, 0.5)
KEY_SHARE = 0.6          # of the light on the floor's plane and lines, the share of the key light (the rest is all round)
SHADOW_CELL = 0.08       # MMD units: the soft shadow is worked out on a grid of the floor this fine, fixed in the world
SHADOW_GRID_MAX = 1200   # cells to a side at most (a grid that would be larger is coarser)
CUTOFF = 8.0             # standard deviations of the light's spread past which a capsule keeps none of it off
COARSE_STEPS = 6         # a capsule's shade is worked out on a grid at least this many cells to the distance it changes
COARSE_LEVELS = 4        # over (its least blur on the floor; for the light from all round its axis's height), up to 2^4
                         # times SHADOW_CELL coarser


def _erf(x):
    """the error function (Abramowitz and Stegun 7.1.26, within 1.5e-7)"""
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-a * a)
    return np.sign(x) * y


def _normal_cdf(x):
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def toward_light(light):
    """the unit vector from the floor to the light, from where the light shines to (MMD's light direction)"""
    v = -np.asarray(light, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if not n > 0 or v[1] <= 0:
        raise ValueError("stage.shadow_light is where the light shines to and must point down (y below 0): not %r"
                         % (list(light),))
    return v / n


def capsule_shade(P, a, b, r, ell, sigma):
    """(key, contact): how much of the key light one capsule (the segment a-b, radius r; heights above the floor) keeps
    off the floor points P (N x 3, y 0), and how much of the light from all round it keeps off them, each 0 to 1
    (capsule_key and capsule_contact)"""
    return capsule_key(P, a, b, r, ell, sigma), capsule_contact(P, a, b, r)


def capsule_key(P, a, b, r, ell, sigma):
    """how much of the key light the capsule keeps off the floor points P, 0 to 1.

    The key light comes from `ell` (unit, toward the light) and has the brightness of a normal (Gaussian) spread of
    `sigma` radians round it, so the edge of a shadow is the integral of a Gaussian whose width grows with the distance
    from the floor to what casts it: a sole on the floor casts a sharp shadow, the head one blurred over many times its
    width (contact hardening).  Seen from P the capsule is a band of half-width beta (its angular radius) round the
    point of its axis nearest the light's ray: a band keeps off the share of a Gaussian between its two edges (exact for a
    long one); past an end of the capsule the share of a disc (the same area as a square) is blended in."""
    P = np.asarray(P, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    u = b - a
    uu = float(u @ u)
    w0 = a[None, :] - P
    e = w0 @ ell
    if uu > 1e-12:
        d = w0 @ u
        ub = float(u @ ell)
        denom = uu - ub * ub
        free = (ub * e - d) / denom if denom > 1e-9 * uu else np.full(e.shape, 0.5)
        s = np.clip(free, 0.0, 1.0)
    else:
        free = s = np.zeros(e.shape)
    v = w0 + s[:, None] * u[None, :]
    t = v @ ell
    length = np.sqrt(np.maximum((v * v).sum(axis=1), 1e-18))
    across = np.sqrt(np.maximum(length * length - t * t, 0.0))
    gamma = np.arctan2(across, t)
    inside = length <= r
    beta = np.arcsin(np.clip(r / np.maximum(length, r), 0.0, 1.0))
    sig = max(float(sigma), 1e-6)
    if uu > 1e-12:
        # past an end (or near it) the capsule is its end's disc: the signed overhang, as an angle seen from P
        over = np.where(free > 0.5, free - 1.0, -free) * math.sqrt(uu) / length
        k = np.clip(0.5 + over / (beta + 2.0 * sig), 0.0, 1.0)
    else:
        k = np.ones(e.shape)
    # the band where k < 1 and the disc where k > 0, each only where the Gaussian reaches it (beyond 8 sigma its share is
    # under 1e-15)
    key = np.zeros(e.shape)
    near = (k < 1.0) & (gamma - beta < CUTOFF * sig)
    if near.any():
        g, bt = gamma[near], beta[near]
        key[near] += (1.0 - k[near]) * (_normal_cdf((g + bt) / sig) - _normal_cdf((g - bt) / sig))
    half = beta * math.sqrt(math.pi) / 2.0
    near = (k > 0.0) & (gamma - half < CUTOFF * sig)
    if near.any():
        g, hf = gamma[near], half[near]
        key[near] += k[near] * ((_normal_cdf((g + hf) / sig) - _normal_cdf((g - hf) / sig))
                                * (2.0 * _normal_cdf(hf / sig) - 1.0))
    return np.clip(np.where(inside, 1.0, key), 0.0, 1.0)


def capsule_contact(P, a, b, r):
    """how much of the light from all round the capsule keeps off the floor points P, 0 to 1: the share of the sky the
    nearest sphere of the capsule hides, (r / d)^2 x its cosine (ambient occlusion of a sphere over a plane), faded out to
    nothing at contact_reach(r) from the axis (a capsule higher above the floor than that darkens nothing)"""
    P = np.asarray(P, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    reach = contact_reach(r)
    if min(float(a[1]), float(b[1])) - r >= reach:
        return np.zeros(len(P))
    u = b - a
    uu = float(u @ u)
    w0 = a[None, :] - P
    s2 = np.clip(-(w0 @ u) / uu, 0.0, 1.0) if uu > 1e-12 else np.zeros(len(P))
    c = w0 + s2[:, None] * u[None, :]
    dist = np.sqrt(np.maximum((c * c).sum(axis=1), 1e-18))
    t = np.clip((reach - dist) / (0.4 * reach), 0.0, 1.0)
    fade = t * t * (3.0 - 2.0 * t)
    return np.where(dist <= r, 1.0, np.clip((r / dist) ** 2 * np.maximum(c[:, 1] / dist, 0.0), 0.0, 1.0) * fade)


def contact_reach(r):
    """how far from its axis a capsule of radius r darkens the floor with the light from all round: the sphere's share,
    1/25 of its cosine at 5 r, is faded out smoothly over the last 40 % of this, so the grid needs no hard border"""
    return 5.0 * r + 0.5


def _low(a, b, r):
    """how far the capsule's lowest point is above the floor"""
    return max(min(float(a[1]), float(b[1])) - r, 0.0)


def _key_box(a, b, r, ell, sigma):
    """the floor's x and z ranges the capsule's shadow along the light can reach: where its ends' shadows fall, with the
    Gaussian's tail (4 sigma) at each end's distance, stretched on the floor by 1 / sin(elevation)"""
    xs, zs = [], []
    reach = 0.0
    for p in (np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)):
        run = max(float(p[1]), 0.0) / ell[1]            # how far the point is along the ray to the light
        q = p - run * ell
        xs += [p[0], q[0]]
        zs += [p[2], q[2]]
        reach = max(reach, 4.0 * float(sigma) * run / ell[1])
    margin = reach + r + 0.5
    return min(xs) - margin, max(xs) + margin, min(zs) - margin, max(zs) + margin


def _contact_box(a, b, r):
    """the floor's x and z ranges the capsule darkens with the light from all round (None: it is too high to)"""
    reach = contact_reach(r)
    if _low(a, b, r) >= reach:
        return None
    margin = reach + 0.5
    return (min(a[0], b[0]) - margin, max(a[0], b[0]) + margin, min(a[2], b[2]) - margin, max(a[2], b[2]) + margin)


def _level(scale, cell):
    """how many times coarser (a power of 2, up to 2^COARSE_LEVELS) than `cell` a grid may be for a shade that changes
    over `scale` (COARSE_STEPS cells to it at least)"""
    level = 0
    while level < COARSE_LEVELS and cell * 2 ** (level + 1) * COARSE_STEPS <= scale:
        level += 1
    return level


@dataclass
class ShadowGrid:
    """the soft shadow on a grid of the floor: key[i, j] and contact[i, j] at x = x0 + j cell, z = z0 + i cell (the
    shares of the key light and of the light from all round that reach the floor there, 0 to 1)"""
    x0: float
    z0: float
    cell: float
    key: np.ndarray
    contact: np.ndarray

    def at(self, X, Z):
        """(key, contact) at the floor points (X, Z), bilinearly; 1 (all the light) off the grid"""
        fx = (np.asarray(X, dtype=np.float64) - self.x0) / self.cell
        fz = (np.asarray(Z, dtype=np.float64) - self.z0) / self.cell
        h, w = self.key.shape
        on = (fx >= 0) & (fz >= 0) & (fx <= w - 1) & (fz <= h - 1)
        j = np.clip(np.floor(fx).astype(np.int64), 0, max(w - 2, 0))
        i = np.clip(np.floor(fz).astype(np.int64), 0, max(h - 2, 0))
        tx = np.clip(fx - j, 0.0, 1.0)
        tz = np.clip(fz - i, 0.0, 1.0)
        out = []
        for g in (self.key, self.contact):
            if w < 2 or h < 2:
                out.append(np.ones(fx.shape))
                continue
            v = (g[i, j] * (1 - tx) * (1 - tz) + g[i, j + 1] * tx * (1 - tz) + g[i + 1, j] * (1 - tx) * tz
                 + g[i + 1, j + 1] * tx * tz)
            out.append(np.where(on, v, 1.0))
        return out[0], out[1]


def soft_shadow_grid(capsules, light, blur_degrees, floor_y=0.0, cell=SHADOW_CELL):
    """the ShadowGrid of `capsules` ((a, b, r) world positions and radius) on the floor at y = floor_y, lit from
    `light` (where it shines to) with a Gaussian spread of `blur_degrees`; None without capsules.  The grid is fixed in
    the world (its points at whole multiples of `cell`), so it does not crawl as the camera moves"""
    if not capsules:
        return None
    ell = toward_light(light)
    sigma = math.radians(max(float(blur_degrees), 0.0))
    lifted = [(np.asarray(a, dtype=np.float64) - [0.0, floor_y, 0.0], np.asarray(b, dtype=np.float64) - [0.0, floor_y, 0.0],
               float(r)) for a, b, r in capsules]
    cell = float(cell)
    jobs = []
    for a, b, r in lifted:
        low = _low(a, b, r)
        # the shadow along the light changes over its least blur (at the lowest point's distance), the light from all
        # round over the distance to the capsule's axis
        jobs.append((a, b, r, "key", _key_box(a, b, r, ell, sigma), _level(sigma * low / ell[1], cell)))
        box = _contact_box(a, b, r)
        if box is not None:
            jobs.append((a, b, r, "contact", box, _level(low + r, cell)))
    lo_x, hi_x = min(j[4][0] for j in jobs), max(j[4][1] for j in jobs)
    lo_z, hi_z = min(j[4][2] for j in jobs), max(j[4][3] for j in jobs)
    while max(hi_x - lo_x, hi_z - lo_z) / cell > SHADOW_GRID_MAX:
        cell *= 2.0
    x0, z0 = math.floor(lo_x / cell) * cell, math.floor(lo_z / cell) * cell
    w = int(math.ceil((hi_x - x0) / cell)) + 1
    h = int(math.ceil((hi_z - z0) / cell)) + 1
    grids = {"key": np.ones((h, w)), "contact": np.ones((h, w))}
    for a, b, r, which, (bx0, bx1, bz0, bz1), level in jobs:
        j0, j1 = max(0, int(math.floor((bx0 - x0) / cell))), min(w, int(math.ceil((bx1 - x0) / cell)) + 1)
        i0, i1 = max(0, int(math.floor((bz0 - z0) / cell))), min(h, int(math.ceil((bz1 - z0) / cell)) + 1)
        if j1 <= j0 or i1 <= i0:
            continue
        xs, zs = x0 + cell * np.arange(j0, j1), z0 + cell * np.arange(i0, i1)
        coarse = cell * 2 ** level
        if coarse > cell:
            # far from the floor the shade changes slowly: worked out on a coarser grid (also fixed in the world) and
            # laid onto this one bilinearly
            cxs = math.floor(xs[0] / coarse) * coarse + coarse * np.arange(int(math.ceil((xs[-1] - xs[0]) / coarse)) + 2)
            czs = math.floor(zs[0] / coarse) * coarse + coarse * np.arange(int(math.ceil((zs[-1] - zs[0]) / coarse)) + 2)
            got = _resample(_shade_on(cxs, czs, a, b, r, ell, sigma, which), cxs, czs, xs, zs)
        else:
            got = _shade_on(xs, zs, a, b, r, ell, sigma, which)
        grids[which][i0:i1, j0:j1] *= 1.0 - got
    return ShadowGrid(x0, z0, cell, grids["key"], grids["contact"])


def _shade_on(xs, zs, a, b, r, ell, sigma, which):
    """capsule_key ("key") or capsule_contact ("contact") on the grid of the floor points xs x zs (zs x xs)"""
    gx, gz = np.meshgrid(xs, zs)
    P = np.stack([gx.ravel(), np.zeros(gx.size), gz.ravel()], axis=1)
    got = capsule_key(P, a, b, r, ell, sigma) if which == "key" else capsule_contact(P, a, b, r)
    return got.reshape(gx.shape)


def _resample(g, gxs, gzs, xs, zs):
    """the grid g (on gxs x gzs, evenly spaced) at xs x zs, bilinearly"""
    fx = np.clip((xs - gxs[0]) / (gxs[1] - gxs[0]), 0.0, len(gxs) - 1.000001)
    fz = np.clip((zs - gzs[0]) / (gzs[1] - gzs[0]), 0.0, len(gzs) - 1.000001)
    j, i = np.floor(fx).astype(np.int64), np.floor(fz).astype(np.int64)
    tx, tz = (fx - j)[None, :], (fz - i)[:, None]
    return (g[i][:, j] * (1 - tx) * (1 - tz) + g[i][:, j + 1] * tx * (1 - tz) + g[i + 1][:, j] * (1 - tx) * tz
            + g[i + 1][:, j + 1] * tx * tz)


def needs_body(look):
    """True when the look's floor takes the soft shadow of her body (Figure.from_files(..., body=True))"""
    stage = look["stage"]
    return bool(stage["floor"]) and stage["shadow"] > 0 and bool(int(stage["shadow_soft"]))


def soft_light(key, contact, stage):
    """(plane, pool): what the floor's plane and lines, and the pool of light, keep of their light where the soft shadow
    lets `key` of the key light and `contact` of the light from all round through.  stage.shadow scales the shadow,
    stage.shadow_contact the darkening from all round; the pool is the key light's alone, the plane and the lines take
    KEY_SHARE of theirs from it"""
    s = float(stage["shadow"])
    m_key = 1.0 - s * (1.0 - key)
    m_all = 1.0 - s * float(stage["shadow_contact"]) * (1.0 - contact)
    return ((1.0 - KEY_SHARE) + KEY_SHARE * m_key) * m_all, m_key * m_all


def _inside(view, d, half):
    """the share of each pixel (rays d) the floor square takes"""
    inside = (d[..., 1] < 0).astype(np.float64)
    for axis in (0, 2):
        inside *= _edge_cover(view, d, axis, half, True) * _edge_cover(view, d, axis, -half, False)
    return inside


def _floor_top(view, half, step=8):
    """the first row of the picture the floor can take (looked for every `step` rows: the floor is one piece)"""
    rows = np.arange(0, view.size[1], step)
    d = _rays_rows(view, rows)
    hit = np.nonzero(_inside(view, d, half).max(axis=1) > 0)[0]
    return None if hit.size == 0 else max(0, int(rows[hit[0]]) - step)


def _rays_rows(view, rows):
    """the rays of the full picture's pixels on the given rows"""
    us = np.arange(view.size[0]) - view.size[0] / 2.0
    vs = np.asarray(rows, dtype=np.float64) - view.size[1] / 2.0
    return (view.forward * view.focal)[None, None, :] + us[None, :, None] * view.right - vs[:, None, None] * view.up


def _floor_once(view, stage, figure):
    """(rgb, cover) of the floor for one camera: cover is the share of each pixel the floor takes.  Only the rows the floor
    reaches and the pixels it covers are worked out (elsewhere a ray meets the plane far off, or never)"""
    w, h = view.size
    cover = np.zeros((h, w))
    rgb = np.zeros((h, w, 3))
    e = view.eye
    half = float(stage["floor_half"])
    top = _floor_top(view, half) if e[1] > 0 else None
    if top is None:
        return rgb, cover
    d = _rays_rows(view, np.arange(top, h))
    inside = _inside(view, d, half)
    cover[top:] = inside
    on = np.zeros((h, w), dtype=bool)
    on[top:] = inside > 0
    if not on.any():
        return rgb, cover
    ray = d[inside > 0]
    dy = ray[:, 1]
    t = -e[1] / dy
    X, Z = e[0] + t * ray[:, 0], e[2] + t * ray[:, 2]
    # how far a pixel's footprint reaches along x and along z (d t = e_y d(d_y) / d_y^2; the rays step by right and -up)
    tu, tv = e[1] * view.right[1] / dy ** 2, -e[1] * view.up[1] / dy ** 2
    fx = np.abs(tu * ray[:, 0] + t * view.right[0]) + np.abs(tv * ray[:, 0] - t * view.up[0]) + 1e-9
    fz = np.abs(tu * ray[:, 2] + t * view.right[2]) + np.abs(tv * ray[:, 2] - t * view.up[2]) + 1e-9
    step, line = float(stage["floor_step"]), float(stage["floor_line"])
    every = int(stage["floor_accent_every"])
    plain = np.zeros(X.shape)
    accent = np.zeros(X.shape)
    for coord, foot in ((X, fx), (Z, fz)):
        k = np.round(coord / step)
        dist = np.abs(coord - k * step)
        is_accent = (np.mod(np.abs(k), every) == 0) if every > 0 else np.zeros(k.shape, dtype=bool)
        plain = np.maximum(plain, np.where(is_accent, 0.0, _overlap(dist, foot, line)))
        accent = np.maximum(accent, np.where(is_accent, _overlap(dist, foot, 2.0 * line), 0.0))
    base = np.tile(np.array(FLOOR_COLOURS["plane"], dtype=np.float64), (X.size, 1))
    pool = None
    if figure is not None and stage["pool"] > 0:
        r2 = (X - figure.centre[0]) ** 2 + (Z - figure.centre[1]) ** 2
        glow = float(stage["pool"]) * np.exp(-r2 / (2.0 * float(stage["pool_radius"]) ** 2))
        pool = glow[:, None] * np.array(stage["pool_colour"], dtype=np.float64)[None, :]
    soft = figure is not None and stage["shadow"] > 0 and int(stage["shadow_soft"])
    if soft and getattr(figure, "capsules", None) is None:
        raise ValueError("stage.shadow_soft 1 casts the shadow of her body: read the dancer with her body "
                         "(Figure.from_files(..., body=True)), or set stage.shadow_soft 0")
    if soft:
        # the soft shadow of her body (soft_shadow_grid): the plane, the lines and the pool each keep their share of light
        grid = soft_shadow_grid(figure.capsules, stage["shadow_light"], float(stage["shadow_blur"]), float(stage["floor_y"]))
        through = grid.at(X, Z) if grid is not None else (np.ones(X.shape), np.ones(X.shape))
        lit, pooled = soft_light(*through, stage)
        base = base * lit[:, None]
        if pool is not None:
            base += pool * pooled[:, None]
        mixed = base * (1.0 - plain[:, None]) + np.array(FLOOR_COLOURS["line"])[None, :] * (lit * plain)[:, None]
        rgb[on] = mixed * (1.0 - accent[:, None]) + np.array(FLOOR_COLOURS["accent"])[None, :] * (lit * accent)[:, None]
        return rgb, cover
    if pool is not None:
        base += pool
    if figure is not None and stage["shadow"] > 0:
        # the shadows reach a few units round her: worked out there only
        px, _, pz = figure.pelvis
        reach = [abs(c - p) for foot in figure.feet for point in foot for c, p in ((point[0], px), (point[2], pz))]
        near = (np.abs(X - px) < 12.0 + max(reach)) & (np.abs(Z - pz) < 12.0 + max(reach))
        if near.any():
            base[near] *= 1.0 - _shade(X[near], Z[near], figure, float(stage["shadow"]))[:, None]
    mixed = base * (1.0 - plain[:, None]) + np.array(FLOOR_COLOURS["line"])[None, :] * plain[:, None]
    rgb[on] = mixed * (1.0 - accent[:, None]) + np.array(FLOOR_COLOURS["accent"])[None, :] * accent[:, None]
    return rgb, cover


def _over_the_floor(view, height):
    """`view` with the world lowered by `height`: a floor at y = height is then the plane y = 0 the floor is worked out on
    (its lines, edges, pool and shadows lie at x and z, which the lowering keeps)"""
    if not height:
        return view
    lowered = copy.copy(view)
    lowered.eye = view.eye - np.array([0.0, float(height), 0.0])
    return lowered


def floor(views, look, size, figures=None):
    """(rgb, cover) of the floor seen by the cameras `views` (the moments a shutter is open), averaged: cover is the share
    of each pixel the floor takes, rgb its colour there.  `figures`: the dancer at each of those moments (Figure.state), for
    the pool of light and the shadows.  The floor lies at y = stage.floor_y (make_stage --height)"""
    stage = look["stage"]
    w, h = size
    total = np.zeros((h, w, 3))
    covered = np.zeros((h, w))
    for i, view in enumerate(views):
        rgb, cover = _floor_once(_over_the_floor(view, stage["floor_y"]), stage, figures[i] if figures else None)
        total += rgb * cover[..., None]
        covered += cover
    cover = covered / float(len(views))
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(covered[..., None] > 1e-12, total / np.maximum(covered, 1e-12)[..., None], 0.0)
    return rgb, cover


# ---- the dancer -----------------------------------------------------------------------------

@dataclass
class FigureState:
    feet: List[Tuple[tuple, tuple]]   # (ankle, toe) of the left and the right foot, world positions
    pelvis: tuple
    centre: Tuple[float, float]       # x and z of the centre, averaged over FIGURE_WINDOW frames (where the pool stands)
    rest: Tuple[float, float]         # the height of an ankle and of a toe on the floor (FIGURE_REST_PERCENTILE of the song)
    capsules: list = None             # her body as capsules (a, b, radius), world positions, for the soft shadow (Body)


FIGURE_WINDOW = 90                   # frames: the pool follows the centre averaged like make_camera's look-at point
FIGURE_REST_PERCENTILE = 2.0
FIGURE_BONES = {"ankles": (("左足ＩＫ", "左足IK"), ("右足ＩＫ", "右足IK")),
                "toes": (("左つま先ＩＫ", "左つま先IK"), ("右つま先ＩＫ", "右つま先IK")),
                "pelvis": ("下半身",), "centre": ("センター",)}


def merge_motions(motions):
    """the bone keys of motions loaded one after another, as MMD reads them: a later motion's keys replace the earlier
    ones of the same bone on the same frame (tools/eye_optics.merge)"""
    by = {}
    for motion in motions:
        mine = {}
        for key in motion.bones:
            mine.setdefault(key.name, []).append(key)
        for name, keys in mine.items():
            frames = {k.frame for k in keys}
            by[name] = [k for k in by.get(name, []) if k.frame not in frames] + keys
    return vmd.Motion(model_name=motions[0].model_name, bones=[k for keys in by.values() for k in keys])


REFERENCE_HEAD = 16.24313735961914   # the rest height of 頭 on Sour's Rin, whose mesh BODY_PARTS were measured on
# her body as capsules for the soft shadow: (bone, offset, bone, offset, radius), each end at the bone's rest position plus
# the offset (model units, the model's rest frame, turned with the bone).  Measured on Sour's Rin (White.pmx) at rest
# (softshadow NOTES, measure_body.py / measure_head.py): a radius is the 90th percentile of the distance of the vertices whose
# largest weight is on the bone from its segment; the head with its hair spans y 15.5-19.0, x +-1.55, z -1.6..1.4; the
# ribbon y 19.0-20.6, x +-1.8, z -0.8..-0.2; the hips (下半身's vertices) y 10.2-12.2, x +-1.56, z -1.35..0.91; the skirt
# flares from 1.2 at the waist (y 13) to 3.8 at the hem (y 9.5).  The skirt moves by physics, which is not followed: it is
# two balls on 下半身.  A part whose bones the model lacks is left out; other models are scaled by the height of 頭.
BODY_PARTS = (
    ("上半身", (0.0, 0.0, 0.0), "上半身2", (0.0, 0.0, 0.0), 1.0),
    ("上半身2", (0.0, 0.0, 0.0), "首", (0.0, 0.0, 0.0), 1.05),
    ("首", (0.0, 0.0, 0.0), "頭", (0.0, 0.0, 0.0), 0.36),
    ("頭", (0.0, 0.66, -0.1), "頭", (0.0, 1.46, -0.1), 1.55),            # the head and the hair
    ("頭", (-1.3, 3.66, -0.5), "頭", (1.3, 3.66, -0.5), 0.6),           # the ribbon
    ("左腕", (0.0, 0.0, 0.0), "左ひじ", (0.0, 0.0, 0.0), 0.38),
    ("左ひじ", (0.0, 0.0, 0.0), "左手首", (0.0, 0.0, 0.0), 0.33),
    ("左手首", (0.0, 0.0, 0.0), "左中指３", (0.0, 0.0, 0.0), 0.42),
    ("右腕", (0.0, 0.0, 0.0), "右ひじ", (0.0, 0.0, 0.0), 0.38),
    ("右ひじ", (0.0, 0.0, 0.0), "右手首", (0.0, 0.0, 0.0), 0.33),
    ("右手首", (0.0, 0.0, 0.0), "右中指３", (0.0, 0.0, 0.0), 0.42),
    ("下半身", (-0.75, -1.22, 0.45), "下半身", (0.75, -1.22, 0.45), 1.2),  # the hips
    ("下半身", (0.0, -1.0, 0.6), "下半身", (0.0, -1.0, 0.6), 2.0),       # the skirt: its upper part
    ("下半身", (0.0, -2.5, 0.6), "下半身", (0.0, -2.5, 0.6), 2.9),       # and its hem
)
# the legs, as MMD's IK puts them (tools/leg_ik.py): (from, to, radius) of the solved points; then the foot, turned with
# 足首: the instep from the ankle to above the ball of the foot (足先EX) and the sole from under the heel to the tip of the
# toe, each with its lowest point at the toe's rest height (the sole of the shoe)
LEG_PARTS = (("hip", "knee", 0.78), ("knee", "ankle", 0.68))
INSTEP = 0.5
SOLE = 0.42
LEG_BLOCK = 256                       # frames the legs are solved for at a time (leg_ik is vectorised over frames)


_LEG_IK = []


def _leg_ik():
    """tools/leg_ik.py, loaded once"""
    if not _LEG_IK:
        import importlib.util
        spec = importlib.util.spec_from_file_location("leg_ik", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                             "leg_ik.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEG_IK.append(module)
    return _LEG_IK[0]


class Body:
    """her body as capsules at any frame of the song, for the soft shadow: the legs as MMD's IK puts them (tools/leg_ik.py,
    within 0.06 cm of MMD's render), the rest by forward kinematics (mmd_cli/fk.py), with the radii of BODY_PARTS.
    Between whole frames the capsules move in a straight line.  ValueError when the model has not the leg rig."""

    def __init__(self, model, rig, motion):
        self.leg_ik = _leg_ik()
        bones = {bone.name: bone for bone in model.bones}
        head = bones.get("頭")
        self.scale = (head.position[1] / REFERENCE_HEAD) if head is not None and head.position and head.position[1] > 0 else 1.0
        self.parts = [p for p in BODY_PARTS if p[0] in bones and p[2] in bones]
        names = sorted({p[0] for p in self.parts} | {p[2] for p in self.parts})
        self.pose = fk.Pose(model, motion, names) if names else None
        self.rig = rig
        self.motion = motion
        self.last = fk.last_frame(motion)
        r, ri = SOLE * self.scale, INSTEP * self.scale
        self.foot = {}
        for s, sd in rig.sides.items():
            a = np.asarray(rig.bones[sd.ankle].position, dtype=np.float64)
            t = np.asarray(rig.bones[sd.toe].position, dtype=np.float64)
            ex = np.asarray(rig.bones[sd.ex].position, dtype=np.float64) if sd.ex is not None else 0.5 * (a + t)
            heel = np.array([a[0], t[1] + r, a[2] + 0.1 * self.scale])
            tip = np.array([t[0], t[1] + r, t[2] + r])
            ball = np.array([ex[0], max(ex[1], t[1] + ri), ex[2]])
            self.foot[s] = ((np.zeros(3), ball - a, ri), (heel - a, tip - a, r))
        self._legs = {}
        self._frames = {}

    @classmethod
    def from_file(cls, model_path, model, motion):
        return cls(model, _leg_ik().LegRig.load(model_path), motion)

    def _legs_at(self, frame):
        block = frame // LEG_BLOCK
        if block not in self._legs:
            frames = list(range(block * LEG_BLOCK, min((block + 1) * LEG_BLOCK, self.last + 1)))
            self._legs = {block: (frames[0], self.leg_ik.solve(self.rig, self.motion, frames))}
        first, out = self._legs[block]
        return {s: {k: v[frame - first] for k, v in legs.items()} for s, legs in out.items()}

    def _at_frame(self, frame):
        """the capsules at a whole frame (cached for the last few)"""
        if frame in self._frames:
            return self._frames[frame]
        out = []
        if self.pose is not None:
            world = self.pose.at(frame)
            for b0, o0, b1, o1, r in self.parts:
                ends = []
                for bone, offset in ((b0, o0), (b1, o1)):
                    p, q = world[bone]
                    ends.append(np.asarray(p, dtype=np.float64)
                                + np.asarray(fk.rotate(q, tuple(self.scale * v for v in offset)), dtype=np.float64))
                out.append((ends[0], ends[1], r * self.scale))
        legs = self._legs_at(frame)
        for s, leg in legs.items():
            for a, b, r in LEG_PARTS:
                out.append((np.asarray(leg[a], dtype=np.float64), np.asarray(leg[b], dtype=np.float64), r * self.scale))
            q = leg["q_foot"]
            for p0, p1, r in self.foot[s]:
                out.append((leg["ankle"] + self.leg_ik.qrot(q, p0), leg["ankle"] + self.leg_ik.qrot(q, p1), r))
        if len(self._frames) > 8:
            self._frames.clear()
        self._frames[frame] = out
        return out

    def capsules(self, frame):
        """[(a, b, radius)] at `frame` (a fraction of a frame: the capsules of the whole frames round it, mixed)"""
        f = min(max(float(frame), 0.0), float(self.last))
        i = int(math.floor(f))
        k = f - i
        a = self._at_frame(i)
        if k <= 1e-9 or i >= self.last:
            return a
        b = self._at_frame(i + 1)
        return [(p0 * (1 - k) + p1 * k, q0 * (1 - k) + q1 * k, r0) for (p0, q0, r0), (p1, q1, _) in zip(a, b)]


class Figure:
    """where her feet, pelvis and centre are at any frame of the song: forward kinematics of the model under her motions.
    The feet are the IK bones (where MMD puts the ankles and the toes when the legs reach them).  With a Body, her body as
    capsules too (the soft shadow)"""

    def __init__(self, model, motion, body=None):
        self.body = body
        names = {bone.name for bone in model.bones}

        def pick(options):
            for name in options:
                if name in names:
                    return name
            raise ValueError("the model has none of the bones %s" % ", ".join(options))
        self.ankles = [pick(o) for o in FIGURE_BONES["ankles"]]
        self.toes = [pick(o) for o in FIGURE_BONES["toes"]]
        self.pelvis_name, self.centre_name = pick(FIGURE_BONES["pelvis"]), pick(FIGURE_BONES["centre"])
        self.pose = fk.Pose(model, motion, self.ankles + self.toes + [self.pelvis_name, self.centre_name])
        last = fk.last_frame(motion)
        xs, zs, ankle_y, toe_y = [], [], [], []
        for frame in range(last + 1):
            at = self.pose.at(frame)
            x, _, z = at[self.centre_name][0]
            xs.append(x)
            zs.append(z)
            ankle_y += [at[n][0][1] for n in self.ankles]
            toe_y += [at[n][0][1] for n in self.toes]
        self.last = last
        self.centre_x = _centred_mean(xs, FIGURE_WINDOW)
        self.centre_z = _centred_mean(zs, FIGURE_WINDOW)
        self.rest = (float(np.percentile(ankle_y, FIGURE_REST_PERCENTILE)), float(np.percentile(toe_y, FIGURE_REST_PERCENTILE)))

    @classmethod
    def from_files(cls, model_path, motion_paths, body=False):
        """the dancer of a model file and her motions (in the order MMD loads them); `body` also reads her body as
        capsules (the soft shadow: needs the leg rig of tools/leg_ik.py)"""
        try:
            model = pmx.load(model_path)
            motions = [vmd.load(p) for p in motion_paths]
        except OSError as exc:
            raise ValueError("cannot read the dancer: %s" % exc)
        if not motions:
            raise ValueError("the dancer needs at least one motion")
        motion = merge_motions(motions)
        return cls(model, motion, Body.from_file(model_path, model, motion) if body else None)

    def state(self, frame):
        at = self.pose.at(frame)
        feet = [(tuple(at[a][0]), tuple(at[t][0])) for a, t in zip(self.ankles, self.toes)]
        f = min(max(float(frame), 0.0), float(self.last))
        i = int(math.floor(f))
        j = min(i + 1, self.last)
        k = f - i
        centre = (self.centre_x[i] * (1 - k) + self.centre_x[j] * k, self.centre_z[i] * (1 - k) + self.centre_z[j] * k)
        capsules = self.body.capsules(frame) if self.body is not None else None
        return FigureState(feet, tuple(at[self.pelvis_name][0]), centre, self.rest, capsules)


def _centred_mean(values, window):
    """the mean of the `window` values round each, narrowing at the ends to stay centred (make_camera._centred_average)"""
    n = len(values)
    prefix = np.concatenate([[0.0], np.cumsum(values)])
    out = []
    for f in range(n):
        half = min(window // 2, f, n - 1 - f)
        out.append((prefix[f + half + 1] - prefix[f - half]) / (2 * half + 1))
    return out


# ---- a frame of the stage -------------------------------------------------------------------

def _screen(a, b):
    return 255.0 - (255.0 - a) * (255.0 - b) / 255.0


def moments(index, fps, subframes=1, shutter=1.0):
    """the frames of the song (fractions of MMD's frames) a video frame `index` at `fps` shows: the subframes its shutter
    keeps (mv_look averages the first round(shutter x subframes) of every `subframes`)"""
    taken = 1 if subframes <= 1 else max(1, int(math.floor(shutter * subframes + 0.5)))
    start = index * SONG_FPS / float(fps)
    return [start + SONG_FPS * k / float(fps * max(1, subframes)) for k in range(taken)]


SHARP_ENOUGH = 1.0               # px: a floor that moves less while the shutter is open is drawn once, at its middle


def floor_moves(a, b, half, height=0.0):
    """the farthest a point of the floor square (a grid of them, at y = height) moves on the picture from camera a to b"""
    g = np.linspace(-half, half, 9)
    points = np.array([(x, height, z) for x in g for z in g])
    ua, va, da = a.project(points)
    ub, vb, db = b.project(points)
    w, h = a.size
    seen = (da > NEAR) & (db > NEAR) & (((ua > 0) & (ua < w) & (va > 0) & (va < h)) | ((ub > 0) & (ub < w) & (vb > 0) & (vb < h)))
    return float(np.hypot(ub - ua, vb - va)[seen].max()) if seen.any() else 0.0


def floor_moments(track, times, size, half, height=0.0):
    """the moments the floor is drawn at for a frame whose shutter is open at `times`: all of them when the floor moves
    SHARP_ENOUGH or more in that time (their average is its motion blur), else only their middle (it is sharp then).  A
    camera with a key on every frame does not move while the shutter is open (view_at): its floor is drawn once"""
    middle = sum(times) / len(times)
    if len(times) > 1 and floor_moves(view_at(track, times[0], size), view_at(track, times[-1], size), half,
                                      height) >= SHARP_ENOUGH:
        return list(times)
    return [middle]


def stage_image(look, size, track, fps, index, light_frames, subframes=1, shutter=1.0, figure=None):
    """the stage of video frame `index` (an RGB picture of `size`): the cyc, the beams and the specks at the middle of the
    moments the shutter is open, the floor at the moments of floor_moments (averaged), at the phase of the light loop of
    `light_frames` frames"""
    times = moments(index, fps, subframes, shutter)
    middle = view_at(track, sum(times) / len(times), size)
    phase = 2.0 * math.pi * (index % int(light_frames)) / float(light_frames)
    back = backdrop(middle, look)
    light = beams(middle, look, phase) + specks(middle, look, phase)
    back = _screen(np.clip(back, 0, 255), np.clip(light, 0, 255))
    small = Image.fromarray(np.clip(back + 0.5, 0, 255).astype(np.uint8), "RGB")
    back = np.asarray(small.resize(tuple(size), Image.BILINEAR), dtype=np.float64)
    if int(look["stage"]["floor"]):
        drawn = floor_moments(track, times, size, float(look["stage"]["floor_half"]), float(look["stage"]["floor_y"]))
        views = [view_at(track, t, size) for t in drawn]
        figures = [figure.state(t) for t in drawn] if figure is not None else None
        rgb, cover = floor(views, look, size, figures)
        back = back * (1.0 - cover[..., None]) + cover[..., None] * (rgb + FLOOR_SEE_THROUGH * back)
    return Image.fromarray(np.clip(back + 0.5, 0, 255).astype(np.uint8), "RGB")


def _slashes(path):
    return path.replace("\\", "/")


def _draw(look, size, track, fps, ranges, light_frames, subframes, shutter, figure, pattern):
    for first, count in ranges:
        for index in range(int(first), int(first) + int(count)):
            stage_image(look, size, track, fps, index, light_frames, subframes, shutter, figure).save(pattern % index,
                                                                                                      compress_level=1)


def merge_spans(spans):
    """(first, count) stretches of video frames, sorted, with the ones that overlap or touch made one"""
    merged = []
    for first, count in sorted((int(f), int(n)) for f, n in spans):
        if count < 1 or first < 0:
            raise ValueError("a span of the stage is a first frame from 0 and a count from 1, not %r" % ([first, count],))
        if merged and first <= merged[-1][0] + merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], first + count - merged[-1][0])
        else:
            merged.append([first, count])
    if not merged:
        raise ValueError("no span of the stage to draw")
    return merged


def write_stage(look, work, size, fps, track, first, count, light_frames, subframes=1, shutter=1.0, figure=None, jobs=1,
                sources=None, spans=None):
    """the stage of video frames first .. first + count - 1 as WORK/stage/stage_NNNNN.png (the frames of before go first:
    ffmpeg reads a numbered sequence until a number is missing).  `spans` ((first, count) stretches, in place of first and
    count) draws those frames only: the chunks of a preview lie apart in the song, and the frames between them are not
    drawn.  With `jobs` above 1 that many processes of this tool (`draw`) draw a share of the frames each, reading the
    camera motion and the dancer themselves from `sources` ({"camera", "model", "motions"}, the files `track` and `figure`
    were read from).  Every frame is drawn on its own, so the pictures are the same whatever the jobs.  The answer:
    {"pattern", "spans" (merged), "first" (the first frame drawn), "frames" (how many)}"""
    ranges = merge_spans(spans if spans is not None else [(first, count)])
    folder = os.path.join(work, "stage")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.startswith("stage_") and name.endswith(".png"):
            os.remove(os.path.join(folder, name))
    pattern = os.path.join(folder, "stage_%05d.png")
    total, jobs = sum(n for _, n in ranges), max(1, int(jobs))
    if jobs == 1 or total < 2:
        _draw(look, size, track, fps, ranges, light_frames, subframes, shutter, figure, pattern)
    else:
        if not sources or not sources.get("camera") or (figure is not None and not sources.get("model")):
            raise ValueError("drawing the stage with jobs needs the files it is drawn from: the camera motion and the dancer")
        _draw_in_jobs(look, size, fps, sources, ranges, light_frames, subframes, shutter, figure is not None, pattern,
                      jobs, work)
    return {"pattern": _slashes(pattern), "first": ranges[0][0], "frames": total, "spans": ranges}


def _shares(ranges, parts):
    """the frames of `ranges` cut into `parts` shares of (nearly) the same number of frames, each a list of ranges"""
    frames = [i for first, count in ranges for i in range(first, first + count)]
    edges = [len(frames) * k // parts for k in range(parts + 1)]
    shares = []
    for k in range(parts):
        mine = frames[edges[k]:edges[k + 1]]
        share = []
        for i in mine:
            if share and i == share[-1][0] + share[-1][1]:
                share[-1][1] += 1
            else:
                share.append([i, 1])
        shares.append(share)
    return shares


def _draw_in_jobs(look, size, fps, sources, ranges, light_frames, subframes, shutter, dancer, pattern, jobs, work):
    """`draw` in `jobs` processes, a share of the frames each (their job files and logs lie in WORK and go afterwards)"""
    parts = min(jobs, sum(n for _, n in ranges))
    running = []
    for k, share in enumerate(_shares(ranges, parts)):
        job = {"look": look, "size": [int(size[0]), int(size[1])], "fps": fps, "camera": sources["camera"],
               "model": sources.get("model") if dancer else None, "motions": list(sources.get("motions") or []) if dancer else [],
               "ranges": share, "light_frames": int(light_frames),
               "subframes": int(subframes), "shutter": float(shutter), "pattern": pattern}
        path = os.path.join(work, "stage_job_%d.json" % k)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=True)
        log = open(os.path.join(work, "stage_job_%d.log" % k), "wb")
        running.append((path, log, subprocess.Popen([sys.executable, os.path.abspath(__file__), "draw", path],
                                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)))
    failed = []
    for path, log, process in running:
        process.wait()
        log.close()
        with open(log.name, "rb") as f:
            said = f.read().decode("utf-8", "replace").strip()
        if process.returncode != 0:
            failed.append("%s (exit %d): %s" % (os.path.basename(path), process.returncode, said[-400:]))
        for leftover in (path, log.name):
            try:
                os.remove(leftover)
            except OSError:
                pass
    if failed:
        raise RuntimeError("drawing the stage failed in %d of %d jobs: %s" % (len(failed), parts, " | ".join(failed)))


# ---- the command ----------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("frame", help="draw one frame of the stage in the world, to look at")
    s.add_argument("camera", help="the camera motion (.vmd)")
    s.add_argument("look", help="the look (the stage section is used; world need not be set)")
    s.add_argument("out", help="the picture to write (.png)")
    s.add_argument("--frame", type=float, required=True, help="the frame of the song")
    s.add_argument("--size", default="1280x720")
    s.add_argument("--model", help="the dancer's model, for the pool and the shadows")
    s.add_argument("--motion", action="append", default=[], help="the dancer's motions, in the order MMD loads them")
    s = sub.add_parser("draw", help="draw the frames of a job file (write_stage with jobs runs these)")
    s.add_argument("job")
    args = p.parse_args(argv)
    if args.command == "draw":
        with open(args.job, encoding="utf-8") as f:
            job = json.load(f)
        figure = Figure.from_files(job["model"], job["motions"], body=needs_body(job["look"])) if job["model"] else None
        _draw(job["look"], tuple(job["size"]), camera_track(job["camera"]), job["fps"], job["ranges"],
              job["light_frames"], job["subframes"], job["shutter"], figure, job["pattern"])
        print(json.dumps({"ok": True, "ranges": job["ranges"]}))
        return 0
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location("mv_look", os.path.join(here, "mv_look.py"))
        mv_look = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mv_look)
        look = mv_look.load_look(args.look)
        size = mv_look.parse_size(args.size)
        figure = Figure.from_files(args.model, args.motion, body=needs_body(look)) if args.model else None
        track = camera_track(args.camera)
        light_frames = mv_look.light_frame_count(look, SONG_FPS)
        index = int(round(args.frame))
        stage_image(look, size, track, SONG_FPS, index, light_frames, figure=figure).save(args.out)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": {"type": "ValueError", "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "frame": index}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
