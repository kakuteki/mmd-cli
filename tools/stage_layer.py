"""The stage of a model (tools/mv_look.py with the look setting "layer": {"on": 1}): a street, a hall or a room modelled for
MMD (a .pmx) and drawn by MMD, laid behind the dancer in place of the stage tools/mv_world.py draws.

    python tools/stage_layer.py info SET.json OUT.json

A SET is a JSON that says which model, where it stands and what its materials are:
    {"model": ".../stage.pmx",              the model (its file is never changed)
     "root": "全ての親",                     the bone that places it (all its vertices hang from it)
     "offset": [x, y, z],                   where MMD moves that bone at frame 0 (MMD units)
     "emissive": ["看板横", ...],            the materials that give light of their own (signs, lit windows)
     "lamps": [[x, y, z], ...]}             lamps of the model (world points, after the offset)

How a frame of the stage is made: MMD draws the model alone with the camera the dancer is drawn with, and the model's
geometry is drawn here again (rasterize: the nearest face at every pixel, projected as mv_world's View projects, so its
depth, material, normal and point in the world lie under MMD's picture of it).
"""
import json
import math
import os
import struct
import sys
from dataclasses import dataclass
from typing import List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NEAR = 0.1                       # nothing nearer the camera than this is drawn (MMD units; mv_world.NEAR)
BOTH_SIDES = 0x01                # a PMX material's flag: drawn on both sides (MMD culls the back of every other face)
MIN_ALPHA = 0.5                  # faces of a material with less alpha are seen through (MMD does not draw alpha 0)
EDGE = 1e-9                      # a pixel centre this close outside a face's edge still counts as inside


# ---- the model --------------------------------------------------------------------------------

@dataclass
class Material:
    name: str
    flags: int = 0               # the PMX flags (BOTH_SIDES: drawn on both sides)
    power: float = 0.0           # the specular power (AutoLuminous makes a material whose power is 100 or more glow)
    alpha: float = 1.0           # the diffuse alpha


@dataclass
class Mesh:
    positions: np.ndarray        # (vertices, 3) world points
    faces: np.ndarray            # (faces, 3) vertex indices
    face_material: np.ndarray    # (faces,) material indices
    materials: List[Material]

    def material_index(self, name):
        for i, m in enumerate(self.materials):
            if m.name == name:
                return i
        raise ValueError("the model has no material %r (it has: %s)" % (name, ", ".join(m.name for m in self.materials)))


def load_mesh(path):
    """the vertices (at rest: no morph), faces and materials of a .pmx"""
    from mmd_cli.formats import pmx_edit
    try:
        doc = pmx_edit.load(path)
    except OSError as exc:
        raise ValueError("cannot read the stage model %s: %s" % (path, exc))
    g = pmx_edit.geometry(doc)
    positions = np.array([v.position() for v in doc.vertices], dtype=np.float64).reshape(-1, 3)
    faces = np.array(g.faces, dtype=np.int64).reshape(-1, 3)
    owner = np.zeros(len(faces), dtype=np.int64)
    at = 0
    for i, m in enumerate(g.materials):
        owner[at:at + m.faces // 3] = i
        at += m.faces // 3
    materials = [Material(m.name, int(m.flags), float(m.specular_power), float(m.diffuse[3])) for m in g.materials]
    return Mesh(positions, faces, owner, materials)


def placed(mesh, offset):
    """the mesh moved by `offset` (its root bone moved so at frame 0: every vertex hangs from it); the mesh is not changed"""
    return Mesh(mesh.positions + np.asarray(offset, dtype=np.float64)[None, :], mesh.faces, mesh.face_material,
                mesh.materials)


# ---- drawing the geometry ----------------------------------------------------------------------

_NUMBA = []


def has_numba():
    """whether numba can compile the rasterizer here (it is not needed: the plain one draws the same, slower)"""
    if not _NUMBA:
        try:
            import numba  # noqa: F401
            _NUMBA.append(True)
        except ImportError:
            _NUMBA.append(False)
    return _NUMBA[0]


_KERNEL = []


def _kernel():
    """the compiled z-buffer (numba), built once"""
    if not _KERNEL:
        import numba

        @numba.njit(cache=False)
        def zbuffer(u, v, iz, width, height, nearest, index):
            for t in range(u.shape[0]):
                u0, u1, u2 = u[t, 0], u[t, 1], u[t, 2]
                v0, v1, v2 = v[t, 0], v[t, 1], v[t, 2]
                area = (u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)
                if abs(area) < 1e-12:
                    continue
                x0 = max(int(math.ceil(min(u0, u1, u2))), 0)
                x1 = min(int(math.floor(max(u0, u1, u2))), width - 1)
                y0 = max(int(math.ceil(min(v0, v1, v2))), 0)
                y1 = min(int(math.floor(max(v0, v1, v2))), height - 1)
                if x1 < x0 or y1 < y0:
                    continue
                inv = 1.0 / area
                for y in range(y0, y1 + 1):
                    for x in range(x0, x1 + 1):
                        w0 = ((u1 - x) * (v2 - y) - (u2 - x) * (v1 - y)) * inv
                        w1 = ((u2 - x) * (v0 - y) - (u0 - x) * (v2 - y)) * inv
                        w2 = 1.0 - w0 - w1
                        if w0 >= -1e-9 and w1 >= -1e-9 and w2 >= -1e-9:
                            z = w0 * iz[t, 0] + w1 * iz[t, 1] + w2 * iz[t, 2]
                            if z > nearest[y, x]:
                                nearest[y, x] = z
                                index[y, x] = t
        _KERNEL.append(zbuffer)
    return _KERNEL[0]


def _clip_near(tri):
    """a triangle in the camera's space (3 x 3: right, up, depth) cut at the near plane: 0 to 2 triangles"""
    inside = tri[:, 2] > NEAR
    if inside.all():
        return [tri]
    if not inside.any():
        return []
    poly = []
    for i in range(3):
        a, b = tri[i], tri[(i + 1) % 3]
        if a[2] > NEAR:
            poly.append(a)
        if (a[2] > NEAR) != (b[2] > NEAR):
            poly.append(a + (NEAR - a[2]) / (b[2] - a[2]) * (b - a))
    return [np.array([poly[0], poly[j], poly[j + 1]]) for j in range(1, len(poly) - 1)]


def _drawn_faces(view, mesh):
    """the faces MMD draws for this camera: not of a see-through material, and facing the camera unless their material is
    drawn on both sides (a face's front is where (b - a) x (c - a) points: measured against MMD's render of the street)"""
    p = mesh.positions
    a, b, c = p[mesh.faces[:, 0]], p[mesh.faces[:, 1]], p[mesh.faces[:, 2]]
    alpha = np.array([m.alpha for m in mesh.materials], dtype=np.float64)
    both = np.array([bool(m.flags & BOTH_SIDES) for m in mesh.materials])
    facing = np.einsum("ij,ij->i", np.cross(b - a, c - a), view.eye[None, :] - a) > 0
    return (alpha[mesh.face_material] >= MIN_ALPHA) & (facing | both[mesh.face_material])


def rasterize(view, mesh, compiled=None):
    """(depth, face) at every pixel of view.size: the depth along the line of sight of the nearest face MMD draws (inf where
    none) and that face's index (-1 where none).  The faces are projected as mv_world's View projects (pixel i at i),
    cut at the near plane, and drawn with 1 / depth interpolated across them (as the picture's perspective has it).
    `compiled`: with numba (None: when it is there)"""
    w, h = view.size
    keep = np.nonzero(_drawn_faces(view, mesh))[0]
    d = mesh.positions - view.eye
    cam = np.stack([d @ view.right, d @ view.up, d @ view.forward], axis=-1)
    tri = cam[mesh.faces[keep]]                                     # (n, 3, 3)
    z = tri[:, :, 2]
    whole = (z > NEAR).all(axis=1)
    cut = np.nonzero(~whole & (z > NEAR).any(axis=1))[0]
    pieces, owners = [tri[whole]], [keep[whole]]
    for k in cut:
        for t in _clip_near(tri[k]):
            pieces.append(t[None])
            owners.append(np.array([keep[k]]))
    tri = np.concatenate(pieces, axis=0) if pieces else np.zeros((0, 3, 3))
    owner = np.concatenate(owners) if owners else np.zeros(0, dtype=np.int64)
    u = w / 2.0 + view.focal * tri[:, :, 0] / tri[:, :, 2]
    v = h / 2.0 - view.focal * tri[:, :, 1] / tri[:, :, 2]
    iz = 1.0 / tri[:, :, 2]
    # (a face far outside the picture: its corners are kept within reach so the pixel loop stays finite)
    on = (u.max(axis=1) >= 0) & (u.min(axis=1) <= w - 1) & (v.max(axis=1) >= 0) & (v.min(axis=1) <= h - 1)
    u, v, iz, owner = u[on], v[on], iz[on], owner[on]
    nearest = np.zeros((h, w), dtype=np.float64)                     # 1 / depth: 0 is nothing
    index = np.full((h, w), -1, dtype=np.int64)
    if compiled is None:
        compiled = has_numba()
    if compiled:
        _kernel()(np.ascontiguousarray(u), np.ascontiguousarray(v), np.ascontiguousarray(iz), w, h, nearest, index)
    else:
        _zbuffer_plain(u, v, iz, w, h, nearest, index)
    face = np.where(index >= 0, owner[np.maximum(index, 0)], -1) if len(owner) else index
    with np.errstate(divide="ignore"):
        depth = np.where(nearest > 0, 1.0 / np.where(nearest > 0, nearest, 1.0), np.inf)
    return depth, face


def _zbuffer_plain(u, v, iz, width, height, nearest, index, block=16):
    """the z-buffer without numba: the faces whose box is at most `block` pixels a side together (every candidate pixel of
    their boxes at once), the larger ones each over its box"""
    area = (u[:, 1] - u[:, 0]) * (v[:, 2] - v[:, 0]) - (u[:, 2] - u[:, 0]) * (v[:, 1] - v[:, 0])
    ok = np.abs(area) >= 1e-12
    x0 = np.clip(np.ceil(u.min(axis=1)), 0, width - 1).astype(np.int64)
    x1 = np.clip(np.floor(u.max(axis=1)), 0, width - 1).astype(np.int64)
    y0 = np.clip(np.ceil(v.min(axis=1)), 0, height - 1).astype(np.int64)
    y1 = np.clip(np.floor(v.max(axis=1)), 0, height - 1).astype(np.int64)
    ok &= (np.floor(u.max(axis=1)) >= np.ceil(u.min(axis=1))) & (np.floor(v.max(axis=1)) >= np.ceil(v.min(axis=1)))
    small = ok & (x1 - x0 < block) & (y1 - y0 < block)

    def scatter(idx, px, py):
        uu, vv, zz = u[idx][:, :, None], v[idx][:, :, None], iz[idx][:, :, None]
        inv = (1.0 / area[idx])[:, None]
        w0 = ((uu[:, 1] - px) * (vv[:, 2] - py) - (uu[:, 2] - px) * (vv[:, 1] - py)) * inv
        w1 = ((uu[:, 2] - px) * (vv[:, 0] - py) - (uu[:, 0] - px) * (vv[:, 2] - py)) * inv
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -EDGE) & (w1 >= -EDGE) & (w2 >= -EDGE) & (px >= 0) & (px < width) & (py >= 0) & (py < height)
        if not inside.any():
            return
        z = (w0 * zz[:, 0] + w1 * zz[:, 1] + w2 * zz[:, 2])[inside]
        flat = (py.astype(np.int64) * width + px.astype(np.int64))
        flat = np.broadcast_to(flat, inside.shape)[inside]
        tri = np.broadcast_to(idx[:, None], inside.shape)[inside]
        order = np.lexsort((-z, flat))                      # by pixel, the nearest (largest 1 / depth) first
        flat, z, tri = flat[order], z[order], tri[order]
        first = np.ones(len(flat), dtype=bool)
        first[1:] = flat[1:] != flat[:-1]
        flat, z, tri = flat[first], z[first], tri[first]
        near_flat, index_flat = nearest.reshape(-1), index.reshape(-1)
        better = z > near_flat[flat]
        near_flat[flat[better]] = z[better]
        index_flat[flat[better]] = tri[better]

    gx, gy = np.meshgrid(np.arange(block), np.arange(block))
    gx, gy = gx.ravel().astype(np.float64), gy.ravel().astype(np.float64)
    sidx = np.nonzero(small)[0]
    for s in range(0, len(sidx), 2048):
        idx = sidx[s:s + 2048]
        scatter(idx, x0[idx][:, None] + gx[None, :], y0[idx][:, None] + gy[None, :])
    for k in np.nonzero(ok & ~small)[0]:
        xs = np.arange(x0[k], x1[k] + 1, dtype=np.float64)
        for ys in np.array_split(np.arange(y0[k], y1[k] + 1, dtype=np.float64), max(1, (y1[k] - y0[k] + 1) * len(xs) // 200000 + 1)):
            px, py = np.meshgrid(xs, ys)
            scatter(np.array([k]), px.ravel()[None, :], py.ravel()[None, :])


@dataclass
class Surface:
    """what the camera sees of the model at every pixel: its point in the world, the unit normal of its face turned to the
    camera, its material (-1 where nothing is drawn) and where something is (seen)"""
    points: np.ndarray
    normals: np.ndarray
    material: np.ndarray
    seen: np.ndarray
    depth: np.ndarray


def surface(view, depth, face, mesh):
    """the Surface of a rasterized picture (rasterize's depth and face)"""
    seen = face >= 0
    rays = view.rays(1)
    with np.errstate(invalid="ignore"):
        points = view.eye[None, None, :] + rays * np.where(seen, depth / view.focal, 0.0)[..., None]
    p = mesh.positions
    a, b, c = p[mesh.faces[:, 0]], p[mesh.faces[:, 1]], p[mesh.faces[:, 2]]
    n = np.cross(b - a, c - a)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    normals = np.zeros(points.shape)
    normals[seen] = n[face[seen]]
    # (turned to the camera: a face drawn on both sides is seen from its back)
    flip = np.einsum("ij,ij->i", normals[seen], view.eye[None, :] - points[seen]) < 0
    sub = normals[seen]
    sub[flip] *= -1.0
    normals[seen] = sub
    material = np.where(seen, mesh.face_material[np.maximum(face, 0)], -1)
    points[~seen] = np.nan
    return Surface(points, normals, material, seen, depth)


# ---- the set ------------------------------------------------------------------------------------

SET_KEYS = ("model", "root", "offset", "emissive", "lamps", "note")


def load_set(path):
    """the set of a JSON file (the module docstring): its model's path made absolute (a relative one is from the set's
    folder), root "全ての親", offset [0, 0, 0], no emissive material and no lamp unless it says"""
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except OSError as exc:
        raise ValueError("cannot read the set %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise ValueError("the set %s is not JSON: %s" % (path, exc))
    return check_set(spec, os.path.dirname(os.path.abspath(path)))


def check_set(spec, folder="."):
    """a set with its defaults, or ValueError for a name it does not know or a value of the wrong kind"""
    if not isinstance(spec, dict):
        raise ValueError("a set is a JSON object, not %r" % (spec,))
    unknown = sorted(set(spec) - set(SET_KEYS))
    if unknown:
        raise ValueError("the set has no setting %s (it has: %s)" % (", ".join(map(repr, unknown)), ", ".join(SET_KEYS)))
    if not isinstance(spec.get("model"), str) or not spec["model"]:
        raise ValueError("the set needs \"model\": the stage's .pmx")
    out = {"model": spec["model"] if os.path.isabs(spec["model"]) else os.path.join(folder, spec["model"]),
           "root": spec.get("root", "全ての親"), "offset": spec.get("offset", [0.0, 0.0, 0.0]),
           "emissive": spec.get("emissive", []), "lamps": spec.get("lamps", [])}
    if not isinstance(out["root"], str) or not out["root"]:
        raise ValueError("the set's root is the name of the bone that places the model, not %r" % (out["root"],))
    if not (isinstance(out["offset"], list) and len(out["offset"]) == 3 and all(_finite(v) for v in out["offset"])):
        raise ValueError("the set's offset is [x, y, z] in MMD units, not %r" % (out["offset"],))
    if not (isinstance(out["emissive"], list) and all(isinstance(n, str) for n in out["emissive"])):
        raise ValueError("the set's emissive is a list of material names, not %r" % (out["emissive"],))
    if not (isinstance(out["lamps"], list) and all(isinstance(p, list) and len(p) == 3 and all(_finite(v) for v in p)
                                                  for p in out["lamps"])):
        raise ValueError("the set's lamps are [[x, y, z], ...] (world points), not %r" % (out["lamps"],))
    out["offset"] = [float(v) for v in out["offset"]]
    out["lamps"] = [[float(v) for v in p] for p in out["lamps"]]
    return out


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def set_mesh(spec):
    """the set's model, placed (its emissive materials checked against it)"""
    mesh = load_mesh(spec["model"])
    for name in spec["emissive"]:
        mesh.material_index(name)
    return placed(mesh, spec["offset"])


# ---- MMD's pictures of the stage ------------------------------------------------------------------

# MMD's menu ids (mmd_cli `menu set`): 215 the axes and the floor grid, 221 the ground shadow, 282 the background black (which
# gives the picture its alpha: 0 where nothing is drawn), 279 the self shadow (on when a model is loaded)
STAGE_MENU = (("215", "off"), ("221", "off"), ("282", "on"))
SELF_SHADOW = "279"
UNCOMPRESSED = "未圧縮"
PICTURE = "mmd_%05d.png"          # MMD's picture of the stage at a frame of the video, in a folder of them


def batch_lines(spec, camera, size, mmd, avi=None, first=None, last=None, stills=None, folder=None, fps=30):
    """the lines of an `mmd batch` that draws the set's model alone (no dancer, no MME: a plain MMD) with the camera motion:
    an uncompressed AVI with alpha of the frames first .. last at `fps` (avi), or a picture of each of `stills` (frames of
    the song) as folder/PICTURE.  The model is placed by a key of its root bone at frame 0; the axes, the grid, the ground
    shadow and the self shadow are off (the author of the city street: the ground shadow looks better hidden), the
    background black"""
    if (avi is None) == (stills is None):
        raise ValueError("draw the stage as an AVI (avi, first, last) or as stills (stills, folder)")
    lines = [["launch", "--headless", "--exe", mmd], ["new"]] + [["menu", "set", m, v] for m, v in STAGE_MENU]
    lines.append(["model", "load", spec["model"]])
    if any(abs(v) > 0 for v in spec["offset"]):
        lines.append(["bone", "set", spec["root"], "--pos"] + ["%.6f" % v for v in spec["offset"]] + ["--frame", "0"])
    lines += [["menu", "set", SELF_SHADOW, "off"], ["model", "select", "camera"], ["motion", "load", camera, "--frame", "0"]]
    w, h = (str(int(v)) for v in size)
    if avi is not None:
        if first is None or last is None or not 0 <= int(first) <= int(last):
            raise ValueError("an AVI of the stage needs its first and last frame, first <= last")
        lines.append(["render", "avi", avi, "--from", str(int(first)), "--to", str(int(last)), "--fps", str(int(fps)),
                      "--size", w, h, "--codec", UNCOMPRESSED])
    else:
        if not folder:
            raise ValueError("stills of the stage need the folder they go to")
        for frame in stills:
            lines += [["frame", "set", str(int(frame))],
                      ["render", "image", os.path.join(folder, PICTURE % int(frame)).replace("\\", "/"), "--size", w, h]]
    lines.append(["quit"])
    return lines


def write_batch(lines, path):
    """an `mmd batch` file of JSON lines"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# the stage alone (tools/stage_layer.py)\n")
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def unpack_avi(avi, folder, first):
    """MMD's AVI of the stage (frames first, first + 1, ...) as folder/PICTURE, RGBA (its alpha kept); the number written"""
    import subprocess
    os.makedirs(folder, exist_ok=True)
    done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", avi, "-start_number", str(int(first)), "-pix_fmt", "rgba",
                           os.path.join(folder, PICTURE)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise RuntimeError("ffmpeg could not unpack %s: %s" % (avi, done.stderr.strip()[-300:]))
    n = 0
    while os.path.exists(os.path.join(folder, PICTURE % (int(first) + n))):
        n += 1
    return n


def same_view(a, b):
    """whether two cameras draw the same picture (mv_world View: where, which way, how wide)"""
    return (a.size == b.size and np.allclose(a.eye, b.eye, rtol=0, atol=1e-9) and np.allclose(a.forward, b.forward, rtol=0, atol=1e-12)
            and np.allclose(a.up, b.up, rtol=0, atol=1e-12) and abs(a.focal - b.focal) < 1e-9)


def picture_frame(folder, frame, view_of):
    """the frame whose picture of MMD's in `folder` shows the stage at `frame`: its own, or, when there is none, the one of
    the earliest frame before it whose camera is still the same (a camera that stands still needs one picture of the stage:
    the stage itself does not move).  view_of(frame) is the camera at a frame.  ValueError when there is none"""
    want = view_of(frame)
    f = int(frame)
    while f >= 0:
        if os.path.exists(os.path.join(folder, PICTURE % f)):
            return f
        f -= 1
        if f < 0 or not same_view(view_of(f), want):
            break
    raise ValueError("no picture of the stage by MMD in %s for frame %d (nor for an earlier frame with the same camera): draw "
                     "it first (`batch`)" % (folder, int(frame)))


def read_picture(path):
    """MMD's picture (RGBA) as floats: its colour (MMD writes it times the alpha: premultiplied) and its alpha 0 to 1"""
    from PIL import Image
    img = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)
    return img[..., :3], img[..., 3] / 255.0


# ---- her shadow on the stage's surfaces --------------------------------------------------------------

def _contact_at(P, n, a, b, r):
    """mv_world.capsule_contact at points P of surfaces whose normals are n (mv_world's has the floor's, up): the share of
    the light from all round the nearest sphere of the capsule hides, (r / d)^2 x its cosine to the surface's normal,
    faded out to nothing at mv_world.contact_reach(r) from the axis"""
    reach = mv_world().contact_reach(r)
    u = b - a
    uu = float(u @ u)
    w0 = a[None, :] - P
    s = np.clip(-(w0 @ u) / uu, 0.0, 1.0) if uu > 1e-12 else np.zeros(len(P))
    c = w0 + s[:, None] * u[None, :]
    dist = np.sqrt(np.maximum((c * c).sum(axis=1), 1e-18))
    t = np.clip((reach - dist) / (0.4 * reach), 0.0, 1.0)
    fade = t * t * (3.0 - 2.0 * t)
    cosine = np.maximum((c * n).sum(axis=1) / dist, 0.0)
    return np.where(dist <= r, 1.0, np.clip((r / dist) ** 2 * cosine, 0.0, 1.0) * fade)


def shadow_at(points, normals, capsules, groups, light, blur_degrees):
    """(key, contact): the share of the key light and of the light from all round that reach the points (N x 3, on the stage's
    surfaces, with their normals) past her body's capsules, 0 to 1: mv_world.soft_shadow_grid's shadow worked out at the
    points themselves, so that it falls on a floor of any height, its steps and kerbs and what stands on it.  The capsules of
    a part of her (groups) keep off what the one that keeps most off keeps off, the parts multiply (BODY_GROUPS); the light
    from all round multiplies capsule by capsule.  Only the points a capsule's shadow can reach are worked out"""
    world = mv_world()
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    n = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    key, contact = np.ones(len(P)), np.ones(len(P))
    if not capsules or not len(P):
        return key, contact
    if groups is not None and len(groups) != len(capsules):
        raise ValueError("shadow_at: a part for each capsule, not %d for %d" % (len(groups), len(capsules)))
    ell = world.toward_light(light)
    sigma = math.radians(max(float(blur_degrees), 0.0))
    low = float(np.min(P[:, 1]))                        # the lowest surface: the boxes are worked out down to it
    held = {}
    for i, (a, b, r) in enumerate(capsules):
        a, b, r = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64), float(r)
        part = groups[i] if groups is not None else i
        lift = np.array([0.0, low, 0.0])
        x0, x1, z0, z1 = world._key_box(a - lift, b - lift, r, ell, sigma)
        near = (P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
        if near.any():
            got = world.capsule_key(P[near], a, b, r, ell, sigma)
            if part not in held:
                held[part] = np.zeros(len(P))
            np.maximum.at(held[part], np.nonzero(near)[0], got)
        reach = world.contact_reach(r) + 0.5
        lo, hi = np.minimum(a, b) - reach - r, np.maximum(a, b) + reach + r
        near = ((P >= lo[None, :]) & (P <= hi[None, :])).all(axis=1)
        if near.any():
            contact[near] *= 1.0 - _contact_at(P[near], n[near], a, b, r)
    for kept in held.values():
        key *= 1.0 - kept
    return key, contact


LEVEL_LEAST = 64                  # a level floor round her with at least this many pixels takes mv_world's grid


def her_shadow(points, normals, state, stage):
    """(key, contact) of her shadow at the points of the stage round her: on a level floor (faces looking straight up, at a
    height that many pixels share) mv_world's grid of that floor (soft_shadow_grid: the same sums on a grid fixed in the world,
    worked out coarser where the shadow is soft; what mv_world lays on its own floor), on every other surface shadow_at at
    the points themselves"""
    world = mv_world()
    P = np.asarray(points, dtype=np.float64)
    n = np.asarray(normals, dtype=np.float64)
    key, contact = np.ones(len(P)), np.ones(len(P))
    groups = getattr(state, "capsule_groups", None)
    level = n[:, 1] > 0.9999
    y = np.round(P[:, 1], 3)
    done = np.zeros(len(P), bool)
    if level.any():
        values, counts = np.unique(y[level], return_counts=True)
        for value, count in zip(values, counts):
            if count < LEVEL_LEAST:
                continue
            on = level & (y == value)
            grid = world.soft_shadow_grid(state.capsules, stage["shadow_light"], float(stage["shadow_blur"]), float(value),
                                          groups=groups)
            if grid is not None:
                key[on], contact[on] = grid.at(P[on, 0], P[on, 2])
            done |= on
    if (~done).any():
        key[~done], contact[~done] = shadow_at(P[~done], n[~done], state.capsules, groups, stage["shadow_light"],
                                               float(stage["shadow_blur"]))
    return key, contact


def soft_light_at(key, contact, normals, stage):
    """what the stage's surfaces keep of their light where her shadow lets `key` of the key light and `contact` of the light
    from all round through: mv_world.soft_light, the key light's share (stage.shadow_key on the floor) taken in proportion
    to how squarely a surface faces the key light against the floor (a face turned from it has none of it to lose)"""
    world = mv_world()
    ell = world.toward_light(stage["shadow_light"])
    k = float(stage.get("shadow_key", world.KEY_SHARE))
    facing = np.maximum(np.asarray(normals, dtype=np.float64).reshape(-1, 3) @ ell / ell[1], 0.0)
    # the floor's light is A all round and K ell_y from the key light, K ell_y / (A + K ell_y) = k; a face whose cosine to
    # the key light is c has K c / (A + K c) of its light from it
    if k >= 1.0:
        share = (facing > 0).astype(np.float64)
    else:
        ratio = k / (1.0 - k) * facing
        share = ratio / (1.0 + ratio)
    s = float(stage["shadow"])
    m_key = 1.0 - s * (1.0 - key)
    m_all = 1.0 - s * float(stage["shadow_contact"]) * (1.0 - contact)
    return (1.0 - share) * m_all + share * m_key


# ---- the night: how the stage is lit ------------------------------------------------------------------

REFERENCE_HEIGHT = 720.0         # lengths in pixels of the look are pixels of a 720 line picture (mv_look)


def emissive_table(mesh, spec):
    """per material: True for the set's emissive materials"""
    table = np.zeros(len(mesh.materials) + 1, dtype=bool)        # (the last for -1: nothing drawn)
    for name in spec["emissive"]:
        table[mesh.material_index(name)] = True
    return table


def lamp_light(points, normals, lamps, layer, compiled=None):
    """[N, 3]: the light of the set's lamps on the points (0 to 1 of white per unit of layer.lamp): each lamp throws its
    colour (layer.lamp_colour) down, (cos of the angle from straight down)^layer.lamp_spot, falling off as
    1 / (1 + (distance / layer.lamp_reach)^2), times the cosine of the light to the surface's normal.  No lamp casts a
    shadow.  `compiled`: with numba (None: when it is there)"""
    P = np.ascontiguousarray(np.asarray(points, dtype=np.float64).reshape(-1, 3))
    n = np.ascontiguousarray(np.asarray(normals, dtype=np.float64).reshape(-1, 3))
    colour = np.asarray(layer["lamp_colour"], dtype=np.float64) / 255.0
    reach, spot = float(layer["lamp_reach"]), float(layer["lamp_spot"])
    L = np.ascontiguousarray(np.asarray(lamps, dtype=np.float64).reshape(-1, 3))
    if compiled is None:
        compiled = has_numba()
    if compiled and len(L):
        weight = np.zeros(len(P))
        _lamp_kernel()(P, n, L, reach, spot, weight)
        return weight[:, None] * colour[None, :]
    weight = np.zeros(len(P))
    for lamp in L:
        v = lamp[None, :] - P
        d = np.sqrt(np.maximum((v * v).sum(axis=1), 1e-12))
        cosine = np.maximum((n * v).sum(axis=1) / d, 0.0)
        down = np.maximum(v[:, 1] / d, 0.0) ** spot if spot > 0 else 1.0
        weight += cosine * down / (1.0 + (d / reach) ** 2)
    return weight[:, None] * colour[None, :]


_LAMP = []


def _lamp_kernel():
    if not _LAMP:
        import numba

        @numba.njit(cache=False, parallel=True)
        def light(P, n, L, reach, spot, out):
            for i in numba.prange(P.shape[0]):
                total = 0.0
                for j in range(L.shape[0]):
                    vx, vy, vz = L[j, 0] - P[i, 0], L[j, 1] - P[i, 1], L[j, 2] - P[i, 2]
                    d = math.sqrt(max(vx * vx + vy * vy + vz * vz, 1e-12))
                    c = (n[i, 0] * vx + n[i, 1] * vy + n[i, 2] * vz) / d
                    if c <= 0.0:
                        continue
                    down = 1.0
                    if spot > 0:
                        down = max(vy / d, 0.0) ** spot
                    total += c * down / (1.0 + (d / reach) ** 2)
                out[i] = total
        _LAMP.append(light)
    return _LAMP[0]


def sky(view, layer):
    """[rows, columns, 3]: the night sky where nothing is drawn, from layer.sky_horizon at the horizon (and below it) to
    layer.sky_top at 0.5 radians above it"""
    d = view.rays(1)
    el = np.arcsin(np.clip(d[..., 1] / np.linalg.norm(d, axis=-1), -1.0, 1.0))
    k = np.clip(el / 0.5, 0.0, 1.0)[..., None]
    return (np.asarray(layer["sky_horizon"], dtype=np.float64)[None, None, :] * (1.0 - k)
            + np.asarray(layer["sky_top"], dtype=np.float64)[None, None, :] * k)


def floor_levels(surf, least=0.01):
    """the heights of the stage's level floors seen (faces looking straight up), each taking at least `least` of them:
    a street and its raised pavements"""
    up = surf.seen & (surf.normals[..., 1] > 0.9999)
    if not up.any():
        return []
    y = np.round(surf.points[up][:, 1], 3)
    values, counts = np.unique(y, return_counts=True)
    return [float(v) for v, c in zip(values, counts) if c >= least * up.sum()]


MIRROR_LEAST = 24.0              # of 255: the parts of the stage brighter than this are mirrored (at night the rest adds little)


def reflection(view, surf, colour, levels, least=MIRROR_LEAST):
    """[rows, columns, 3] and [rows, columns] bool: what the level floors mirror (the picture `colour` of the stage, a pixel
    as bright as `least` or more), and where something is mirrored.  For each level, the stage's points above it are mirrored
    in its plane and drawn again from the camera (the nearest mirrored point at a pixel wins); a pixel of that floor shows the
    mirrored point when the point lies beyond the floor along its line of sight.  Only what the camera sees can be mirrored
    (a screen-space reflection)"""
    h, w = surf.seen.shape
    out = np.zeros((h, w, 3))
    best = np.full(h * w, np.inf)
    got = np.zeros((h, w), bool)
    bright = surf.seen & (colour.max(axis=-1) >= least)
    floor_y = np.where(surf.seen & (surf.normals[..., 1] > 0.9999), np.round(surf.points[..., 1], 3), np.nan)
    flat_out = out.reshape(-1, 3)
    for level in levels:
        src = bright & (surf.points[..., 1] > level + 1e-6)
        if not src.any():
            continue
        X = surf.points[src].copy()
        X[:, 1] = 2.0 * level - X[:, 1]
        u, v, d = view.project(X)
        col = colour[src]
        px, py = np.round(u).astype(np.int64), np.round(v).astype(np.int64)
        ok = (d > NEAR) & (px >= 0) & (px < w) & (py >= 0) & (py < h)
        px, py, d, col = px[ok], py[ok], d[ok], col[ok]
        on = floor_y[py, px] == round(level, 3)
        on &= d > surf.depth[py, px]
        px, py, d, col = px[on], py[on], d[on], col[on]
        flat = py * w + px
        order = np.lexsort((d, flat))
        flat, d, col = flat[order], d[order], col[order]
        first = np.ones(len(flat), dtype=bool)
        first[1:] = flat[1:] != flat[:-1]
        flat, d, col = flat[first], d[first], col[first]
        nearer = d < best[flat]
        best[flat[nearer]] = d[nearer]
        flat_out[flat[nearer]] = col[nearer]
    got.reshape(-1)[np.isfinite(best)] = True
    return out, got


def _blur(img, sigma):
    """img blurred by a Gaussian of `sigma` pixels (OpenCV in 32-bit floats when it is there, else scipy as mv_world blurs),
    edges repeated"""
    if sigma <= 0:
        return img
    try:
        import cv2
        return cv2.GaussianBlur(np.ascontiguousarray(img, dtype=np.float32), (0, 0), float(sigma),
                                borderType=cv2.BORDER_REPLICATE).astype(np.float64)
    except ImportError:
        return mv_world()._blurred(img, sigma) if img.ndim == 3 else mv_world()._blurred(img[..., None], sigma)[..., 0]


FILL = 1.5                       # pixels: the gaps a mirror's points leave are filled over at least this blur
COVERED = 0.05                   # a neighbourhood where the known pixels' Gaussian weight is under this is faded out


def fill_holes(img, got, sigma):
    """the picture `img` known where `got`, its holes filled and the whole blurred by `sigma` pixels (a normalized blur: the
    known pixels' Gaussian mean): the gaps between mirrored points close, the mirror is as rough as sigma says"""
    s = max(float(sigma), FILL)
    weight = _blur(got.astype(np.float64), s)
    total = _blur(img * got[..., None], s)
    with np.errstate(invalid="ignore", divide="ignore"):
        filled = np.where(weight[..., None] > 1e-6, total / np.maximum(weight, 1e-12)[..., None], 0.0)
    # (beyond the reach of the known pixels the mirror shows nothing: faded out where hardly any of the neighbourhood is
    # known; mirrored points a few pixels apart, as a mirror that magnifies leaves them, keep it whole)
    return filled * np.clip(weight / COVERED, 0.0, 1.0)[..., None]


def defocus(img, sigma):
    """mv_world.defocus (every pixel blurred by its own sigma: levels of blur sqrt 2 apart, each pixel mixed from the two
    round its blur) with OpenCV's Gaussian in 32-bit floats when it is there (several times as fast; the same to within a
    hair: its kernel reaches 4 sigma as scipy's), else mv_world's own"""
    try:
        import cv2
    except ImportError:
        return mv_world().defocus(img, sigma)
    img = np.asarray(img, dtype=np.float32)
    sigma = np.asarray(sigma, dtype=np.float64)
    out = img.copy()
    top = float(sigma.max()) if sigma.size else 0.0
    lower, below = 0.0, img
    level = 0.5
    while lower < top:
        above = cv2.GaussianBlur(img, (0, 0), level, borderType=cv2.BORDER_REPLICATE)
        here = (sigma > lower) & (sigma <= level)
        if here.any():
            w = ((sigma[here] - lower) / (level - lower))[:, None].astype(np.float32)
            out[here] = below[here] * (1.0 - w) + above[here] * w
        lower, below = level, above
        level *= mv_world().DOF_LEVELS
    return out.astype(np.float64)


# ---- a frame of the stage --------------------------------------------------------------------------

@dataclass
class Still:
    """what does not change while the camera stands still: the geometry under MMD's picture, the light of the night on it
    (before her shadow), the sky, the haze, the light round every pixel for her (spill)"""
    view: object
    surf: Surface
    emissive: np.ndarray          # [rows, columns] bool: the emissive materials' pixels
    lit: np.ndarray               # [rows, columns, 3]: the stage lit for the night, before her shadow, the sky and the blur
    alpha: np.ndarray             # MMD's alpha
    reflected: np.ndarray         # what the floor mirrors (already times its share), or None
    sky: np.ndarray
    haze: np.ndarray              # [rows, columns]: the haze's share
    spill: np.ndarray             # [rows / 2, columns / 2, 3] or None


def still(look, spec, mesh, table, view, picture, alpha):
    """the Still of a camera over MMD's picture of the stage (premultiplied colour, alpha)"""
    layer, unit = look["layer"], view.size[1] / REFERENCE_HEIGHT
    depth, face = rasterize(view, mesh)
    surf = surface(view, depth, face, mesh)
    emissive = table[surf.material]
    plain = surf.seen & ~emissive
    gain = float(layer["night"]) * np.asarray(layer["tint"], dtype=np.float64)
    lit = picture * gain[None, None, :]
    if float(layer["lamp"]) > 0 and spec["lamps"]:
        light = np.zeros(picture.shape)
        light[plain] = lamp_light(surf.points[plain], surf.normals[plain], spec["lamps"], layer) * float(layer["lamp"])
        lit = lit + picture * light
    lit[emissive] = picture[emissive] * float(layer["emissive"])
    reflected = None
    if float(layer["reflect"]) > 0:
        levels = floor_levels(surf)
        mirror, got = reflection(view, surf, lit, levels)
        mirror = fill_holes(mirror, got, float(layer["reflect_blur"]) * unit)
        on = surf.seen & (surf.normals[..., 1] > 0.9999) & np.isin(np.round(np.nan_to_num(surf.points[..., 1], nan=-1e9), 3),
                                                                    np.round(levels, 3))
        reflected = mirror * (float(layer["reflect"]) * mv_world().fresnel(view) * on)[..., None]
    haze = np.zeros(surf.seen.shape)
    if float(layer["haze"]) > 0:
        haze = np.where(surf.seen, 1.0 - np.exp(-float(layer["haze"]) * np.where(surf.seen, depth, 0.0)), 0.0)
    spill = None
    if float(layer["spill"]) > 0 or float(layer["spill_wrap"]) > 0:
        source = np.where(emissive[..., None], lit, 0.0)
        h, w = surf.seen.shape
        small = source.reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3)) if h % 2 == 0 and w % 2 == 0 else source[::2, ::2]
        spill = _blur(small, float(layer["spill_radius"]) * unit / 2.0)
    return Still(view, surf, emissive, lit, alpha, reflected, sky(view, layer), haze, spill)


FLICKER_SLOW = (0.25, 0.8)        # Hz: the swell of a sign's flicker, drawn per material from this range ...
FLICKER_FAST = (6.0, 13.0)        # ... and the buzz inside it


def flicker_gains(light, materials, t):
    """[materials]: the gain of each material's own light at `t` seconds (look light.flicker, light3): 1 - share x d^2,
    d the product of a slow swell and a fast buzz (each 0.5 + 0.5 sin), their rates and phases drawn for each material
    from light.flicker_seed and its own index (so a material's flicker does not change with how many a camera sees): a lit
    sign dips now and then and never passes its light"""
    share = float(light.get("flicker", 0.0))
    gains = np.ones(materials)
    if share <= 0:
        return gains
    seed = int(light.get("flicker_seed", 0))
    for m in range(materials):
        rng = np.random.default_rng([seed, m])
        slow, fast = rng.uniform(*FLICKER_SLOW), rng.uniform(*FLICKER_FAST)
        p0, p1 = rng.uniform(0.0, 2.0 * math.pi, size=2)
        d = (0.5 + 0.5 * math.sin(2.0 * math.pi * slow * t + p0)) * (0.5 + 0.5 * math.sin(2.0 * math.pi * fast * t + p1))
        gains[m] = 1.0 - share * d * d
    return gains


def stage_frame(look, s, state=None, t=None):
    """the stage of a frame (an RGB picture as floats) from its Still and her state (mv_world.Figure.state: her capsules
    for her shadow), in this order: the night's light (the Still; its lit signs flickering at `t` seconds of the song by
    look light.flicker), her shadow on the surfaces round her, the floor's mirror, the sky, the haze, the blur by depth
    (stage.dof, focused at the camera's look-at point as mv_world focuses), the glow"""
    stage, layer = look["stage"], look["layer"]
    unit = s.view.size[1] / REFERENCE_HEIGHT
    img = s.lit.copy()
    light = look.get("light", {})
    if t is not None and float(light.get("flicker", 0.0)) > 0 and s.emissive.any():
        gains = flicker_gains(light, int(s.surf.material.max()) + 1, float(t))
        img[s.emissive] *= gains[s.surf.material[s.emissive]][:, None]
    if state is not None and float(stage["shadow"]) > 0 and getattr(state, "capsules", None):
        world = mv_world()
        plain = s.surf.seen & ~s.emissive
        P, n = s.surf.points[plain], s.surf.normals[plain]
        ell = world.toward_light(stage["shadow_light"])
        sigma = math.radians(float(stage["shadow_blur"]))
        low = float(P[:, 1].min()) if len(P) else 0.0
        boxes = []
        for a, b, r in state.capsules:
            a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
            lift = np.array([0.0, low, 0.0])
            boxes.append(world._key_box(a - lift, b - lift, float(r), ell, sigma))
            reach = world.contact_reach(float(r)) + 0.5 + float(r)
            boxes.append((min(a[0], b[0]) - reach, max(a[0], b[0]) + reach, min(a[2], b[2]) - reach, max(a[2], b[2]) + reach))
        x0, x1 = min(bx[0] for bx in boxes), max(bx[1] for bx in boxes)
        z0, z1 = min(bx[2] for bx in boxes), max(bx[3] for bx in boxes)
        near = (P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
        if near.any():
            key, contact = her_shadow(P[near], n[near], state, stage)
            keep = soft_light_at(key, contact, n[near], stage)
            idx = np.nonzero(plain.reshape(-1))[0][near]
            flat = img.reshape(-1, 3)
            flat[idx] *= keep[:, None]
    if s.reflected is not None:
        img = img + s.reflected
    img = img + (1.0 - s.alpha)[..., None] * s.sky
    if s.haze.any():
        img = img * (1.0 - s.haze[..., None]) + np.asarray(layer["haze_colour"], dtype=np.float64)[None, None, :] * s.haze[..., None]
    if float(stage["dof"]) > 0:
        world = mv_world()
        far = float(stage["dof"]) * unit
        focus = float(stage["dof_focus"]) or s.view.distance
        if not focus > 0:
            raise ValueError("stage.dof focuses at the camera's look-at point, and the camera is at or beyond it: give "
                             "stage.dof_focus")
        img = defocus(img, world.blur_of(np.where(s.surf.seen, s.surf.depth, np.inf), focus, far))
    if float(layer["glow"]) > 0:
        bright = np.clip(img - float(layer["glow_threshold"]), 0.0, None)
        img = img + float(layer["glow"]) * _blur(bright, float(layer["glow_radius"]) * unit)
    if float(layer["emissive_glow"]) > 0:
        source = np.where(s.emissive[..., None], img, 0.0)
        img = img + float(layer["emissive_glow"]) * _blur(source, float(layer["emissive_glow_radius"]) * unit)
    return img


def as_picture(img):
    """floats (light may pass 255) as an 8-bit RGB picture"""
    from PIL import Image
    return Image.fromarray(np.clip(np.asarray(img) + 0.5, 0, 255).astype(np.uint8), "RGB")


SONG_FPS = 30                    # MMD's frames of the song (mv_world.SONG_FPS)
SPILL = "spill_%05d.png"         # the light round every pixel for her (half size), next to the stage's frames


def needs_spill(look):
    return float(look["layer"]["spill"]) > 0 or float(look["layer"]["spill_wrap"]) > 0


class Drawer:
    """draws the frames of the stage of a set for mv_look: MMD's pictures of the stage (a folder of PICTURE, by frame of the
    song), the camera motion, the dancer (her shadow) and the shutter of the fold; the Still of a camera is kept while the
    camera stands still"""

    def __init__(self, look, spec, size, fps, track, pictures, figure=None, subframes=1, shutter=1.0):
        self.look, self.spec, self.size, self.fps = look, spec, tuple(size), fps
        self.track, self.pictures, self.figure = track, pictures, figure
        self.subframes, self.shutter = subframes, shutter
        self.mesh = set_mesh(spec)
        self.table = emissive_table(self.mesh, spec)
        self._still = None

    def view_of(self, frame):
        return mv_world().view_at(self.track, frame, self.size)

    def frame(self, index):
        """(stage, spill or None) of video frame `index`: the camera of the frame of the song it shows (the camera must stand
        still while the shutter is open: MMD draws the stage at whole frames of the song), her shadow at the middle of the
        moments the shutter is open (as mv_world's floor)"""
        world = mv_world()
        times = world.moments(index, self.fps, self.subframes, self.shutter)
        song = int(math.floor(index * SONG_FPS / float(self.fps) + 1e-9))
        view = self.view_of(song)
        for t in (times[0], times[-1]):
            if world.floor_moves(view, self.view_of(t), 60.0) >= world.SHARP_ENOUGH:
                raise ValueError("the camera moves while the shutter of video frame %d is open (frame %.3f of the song): MMD "
                                 "draws the stage of a model at whole frames of the song, so it is drawn for cameras that "
                                 "stand still between them (keys a frame apart, or none)" % (index, t))
        if self._still is None or not same_view(self._still.view, view):
            got = picture_frame(self.pictures, song, self.view_of)
            picture, alpha = read_picture(os.path.join(self.pictures, PICTURE % got))
            if picture.shape[:2] != (self.size[1], self.size[0]):
                raise ValueError("MMD's picture of the stage %s is %dx%d, the video %dx%d" % (
                    PICTURE % got, picture.shape[1], picture.shape[0], self.size[0], self.size[1]))
            self._still = still(self.look, self.spec, self.mesh, self.table, view, picture, alpha)
        middle = sum(times) / len(times)
        state = self.figure.state(middle) if self.figure is not None else None
        return stage_frame(self.look, self._still, state, t=middle / SONG_FPS), self._still.spill

    def draw(self, ranges, folder):
        for first, count in ranges:
            for index in range(int(first), int(first) + int(count)):
                img, spill = self.frame(index)
                as_picture(img).save(os.path.join(folder, "stage_%05d.png" % index), compress_level=1)
                if needs_spill(self.look):
                    as_picture(spill).save(os.path.join(folder, SPILL % index), compress_level=1)


def write_stage(look, work, size, fps, world, first, count, spans=None):
    """the stage of video frames first .. first + count - 1 (or of `spans`, (first, count) stretches) as
    WORK/stage/stage_NNNNN.png, and with layer.spill or layer.spill_wrap the light round her as WORK/stage/spill_NNNNN.png
    (half size), as mv_world.write_stage writes the stage in the world: `world` is mv_look's world_inputs (the camera, the
    dancer, the shutter, the jobs, and the layer: the set and the folder of MMD's pictures).  With world["jobs"] above 1
    that many processes of this tool (`draw`) draw a share each.  The answer: {"pattern", "first", "frames", "spans" and
    "spill" (its pattern, or None)}"""
    ranges = mv_world().merge_spans(spans if spans is not None else [(first, count)])
    folder = os.path.join(work, "stage")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if (name.startswith("stage_") or name.startswith("spill_")) and name.endswith(".png"):
            os.remove(os.path.join(folder, name))
    total, jobs = sum(n for _, n in ranges), max(1, int(world.get("jobs", 1)))
    layer = world["layer"]
    if jobs == 1 or total < 2:
        spec = load_set(layer["set"])
        Drawer(look, spec, size, fps, world["track"], layer["pictures"], world.get("figure"), world.get("subframes", 1),
               world.get("shutter", 1.0)).draw(ranges, folder)
    else:
        _draw_in_jobs(look, size, fps, world, ranges, folder, jobs, work)
    pattern = os.path.join(folder, "stage_%05d.png").replace("\\", "/")
    spill = os.path.join(folder, SPILL).replace("\\", "/") if needs_spill(look) else None
    return {"pattern": pattern, "first": ranges[0][0], "frames": total, "spans": ranges, "spill": spill}


def _draw_in_jobs(look, size, fps, world, ranges, folder, jobs, work):
    import subprocess
    shares = mv_world()._shares(ranges, min(jobs, sum(n for _, n in ranges)))
    running = []
    for k, share in enumerate(shares):
        job = {"look": look, "size": [int(size[0]), int(size[1])], "fps": fps, "camera": world["camera"],
               "model": world.get("model"), "motions": list(world.get("motions") or []), "ranges": share,
               "subframes": int(world.get("subframes", 1)), "shutter": float(world.get("shutter", 1.0)),
               "set": world["layer"]["set"], "pictures": world["layer"]["pictures"], "folder": folder}
        path = os.path.join(work, "layer_job_%d.json" % k)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=True)
        log = open(os.path.join(work, "layer_job_%d.log" % k), "wb")
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
        raise RuntimeError("drawing the stage failed in %d of %d jobs: %s" % (len(failed), len(shares), " | ".join(failed)))


def _draw_job(path):
    with open(path, encoding="utf-8") as f:
        job = json.load(f)
    world = mv_world()
    look = job["look"]
    figure = None
    if job.get("model") and float(look["stage"]["shadow"]) > 0:
        figure = world.Figure.from_files(job["model"], job["motions"], body=True)
    Drawer(look, load_set(job["set"]), tuple(job["size"]), job["fps"], world.camera_track(job["camera"]), job["pictures"], figure,
           job["subframes"], job["shutter"]).draw(job["ranges"], job["folder"])
    return {"ok": True, "ranges": job["ranges"]}


_WORLD = []


def mv_world():
    """tools/mv_world.py (the camera, the soft shadow, the blur by depth), loaded once from its file"""
    if not _WORLD:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mv_world", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                              "mv_world.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _WORLD.append(module)
    return _WORLD[0]


# ---- the command ----------------------------------------------------------------------------

# ---- where she stands: the placement over the whole song ---------------------------------------------------

def segment_hits(origins, ends, tri):
    """for each segment origins[i] .. ends[i]: the share t (0 to 1) along it of the nearest face of `tri` (n x 3 x 3) it
    crosses (inf where none) and that face's index (-1): Moller and Trumbore's test, every face against every segment"""
    O = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
    D = np.asarray(ends, dtype=np.float64).reshape(-1, 3) - O
    t_best = np.full(len(O), np.inf)
    i_best = np.full(len(O), -1, dtype=np.int64)
    tri = np.asarray(tri, dtype=np.float64).reshape(-1, 3, 3)
    if not len(tri) or not len(O):
        return t_best, i_best
    a = tri[:, 0]
    e1, e2 = tri[:, 1] - a, tri[:, 2] - a
    for s in range(0, len(tri), 4096):
        A, E1, E2 = a[s:s + 4096], e1[s:s + 4096], e2[s:s + 4096]
        p = np.cross(D[:, None, :], E2[None, :, :])                     # (segments, faces, 3)
        det = (E1[None, :, :] * p).sum(axis=2)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = O[:, None, :] - A[None, :, :]
        u = (tv * p).sum(axis=2) * inv
        q = np.cross(tv, E1[None, :, :])
        v = (D[:, None, :] * q).sum(axis=2) * inv
        t = (E2[None, :, :] * q).sum(axis=2) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= 1)
        t = np.where(hit, t, np.inf)
        j = np.argmin(t, axis=1)
        tj = t[np.arange(len(O)), j]
        better = tj < t_best
        t_best[better] = tj[better]
        i_best[better] = s + j[better]
    return t_best, i_best


def point_triangle_distance(P, tri):
    """[points, faces]: the distance from each point to each face (Ericson's closest point on a triangle)"""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)[:, None, :]
    a, b, c = (np.asarray(tri, dtype=np.float64).reshape(-1, 3, 3)[None, :, k, :] for k in range(3))
    ab, ac, ap = b - a, c - a, P - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = P - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = P - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = va + vb + vc
        v = np.where(np.abs(denom) > 1e-300, vb / denom, 0.0)
        w = np.where(np.abs(denom) > 1e-300, vc / denom, 0.0)
        closest = a + ab * v[..., None] + ac * w[..., None]                                   # inside the face
        t_ab = np.clip(np.where(np.abs(d1 - d3) > 1e-300, d1 / (d1 - d3), 0.0), 0.0, 1.0)
        on_ab = a + ab * t_ab[..., None]
        t_ac = np.clip(np.where(np.abs(d2 - d6) > 1e-300, d2 / (d2 - d6), 0.0), 0.0, 1.0)
        on_ac = a + ac * t_ac[..., None]
        t_bc = np.clip(np.where(np.abs((d4 - d3) + (d5 - d6)) > 1e-300, (d4 - d3) / ((d4 - d3) + (d5 - d6)), 0.0), 0.0, 1.0)
        on_bc = b + (c - b) * t_bc[..., None]
    # the regions of Ericson's test, the last that holds wins (they do not overlap)
    out = closest
    out = np.where(((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0))[..., None], on_bc, out)
    out = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[..., None], on_ac, out)
    out = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[..., None], on_ab, out)
    out = np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, out)
    out = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, out)
    out = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, out)
    return np.linalg.norm(P - out, axis=-1)


CHECK_STEP = 0.25                 # MMD units: a capsule is checked as balls this far apart along its axis
FLOOR_TOLERANCE = 0.06            # MMD units (about 5 mm): a ball of her body this far into a face reaches into it
UNDER = 0.1 / 8.0                 # MMD units (0.1 cm, tools/sink_check.py's UNDER_CM): a shoe lower than the floor by more is in it
FLOOR_LOOK = 3.0                  # the floor under a sole is looked for from this far above it ...
FLOOR_DOWN = 60.0                 # ... down to this far below it (a foot high in a kick still has its floor under it)
SOLE_BAND = 0.4                   # MMD units: a shoe's vertices this near its lowest are its sole (where it stands)
SOLE_POINTS = 24                  # at most this many of them are looked under
VIEW_REACH = 150.0                # a camera's sight is checked this far: the inside of a thing it stands in lies nearer


def check_placement(mesh, figure, frames, cameras, size=(1280, 720), body_margin=4.0, soles=None):
    """the numbers of where the stage puts her, over `frames` of the song: {"feet": the floor under her soles (the top face
    looking up under each point of each sole, FLOOR_LOOK above it to FLOOR_DOWN below: the frames with a shoe lower than
    that floor by more than UNDER, the frames with no floor under a sole point, the heights of the floor under her),
    "body": frames where a ball of her capsules (CHECK_STEP apart) reaches into a face that is not the floor under her
    (and, apart, into the floor), "cameras": per camera {"inside": frames where a ray of its view meets the back of a face
    within VIEW_REACH first (it stands in or behind something), "hidden": frames where a face lies between it and a point
    of her (the stage would be laid behind her there)}}.  `figure`: mv_world.Figure with her body; `cameras`: {name: camera
    track}; `soles`: frame -> [(the sole's points [k, 3], the shoe's lowest height)] per shoe, MMD's skinned shoes
    (shoe_soles); without it the soles are her foot capsules' bottoms (rounder than a shoe: they reach a little lower)"""
    world = mv_world()
    P = mesh.positions
    tri_all = P[mesh.faces]
    normal = np.cross(tri_all[:, 1] - tri_all[:, 0], tri_all[:, 2] - tri_all[:, 0])
    up = normal[:, 1] / np.maximum(np.linalg.norm(normal, axis=1), 1e-300)
    states = [(f, figure.state(f)) for f in frames]
    allpts = np.array([p for _, s in states for a, b, r in s.capsules for p in (a, b)])
    lo, hi = allpts.min(axis=0) - body_margin, allpts.max(axis=0) + body_margin
    tmin, tmax = tri_all.min(axis=1), tri_all.max(axis=1)
    near_her = np.nonzero(((tmax >= lo) & (tmin <= hi)).all(axis=1))[0]
    floor_faces = near_her[up[near_her] > 0.9]
    groups = figure.body.groups if figure.body is not None else []
    feet_idx = [i for i, g in enumerate(groups) if g.endswith("foot")]
    rows = {"sunk": [], "off_floor": [], "floor_heights": [], "lift": [], "body": [], "body_floor": []}
    floor_all = np.nonzero(up > 0.9)[0]
    for f, s in states:
        caps = s.capsules
        if soles is not None:
            shoes = soles(f)
        else:
            shoes = []
            for i in feet_idx:
                a, b, r = caps[i]
                low = min(a[1], b[1]) - r
                shoes.append((np.array([(a[0], low, a[2]), (b[0], low, b[2])]), low))
        points = np.concatenate([pts for pts, _ in shoes])
        lows = np.concatenate([np.full(len(pts), low) for pts, low in shoes])
        top = points + [0.0, FLOOR_LOOK, 0.0]
        t, k = segment_hits(top, points - [0.0, FLOOR_DOWN, 0.0], tri_all[floor_all])
        found = np.isfinite(t)
        heights = top[:, 1] - (FLOOR_LOOK + FLOOR_DOWN) * np.where(found, t, 0.0)
        if not found.all():
            rows["off_floor"].append(f)
        if found.any():
            rows["floor_heights"].append(heights[found])
            rows["lift"].append((lows - heights)[found])
            if (lows[found] < heights[found] - UNDER).any():
                rows["sunk"].append(f)
        # her body against the faces near her: balls along every capsule
        balls, radii, is_foot = [], [], []
        for i, (a, b, r) in enumerate(caps):
            a, b = np.asarray(a), np.asarray(b)
            n = max(1, int(math.ceil(np.linalg.norm(b - a) / CHECK_STEP)))
            for j in range(n + 1):
                balls.append(a + (b - a) * j / n)
                radii.append(r)
                is_foot.append(i in feet_idx)
        balls, radii, is_foot = np.array(balls), np.array(radii), np.array(is_foot)
        blo, bhi = balls.min(axis=0) - radii.max(), balls.max(axis=0) + radii.max()
        cand = near_her[((tmax[near_her] >= blo) & (tmin[near_her] <= bhi)).all(axis=1)]
        if len(cand):
            dist = point_triangle_distance(balls, tri_all[cand])
            into = dist < radii[:, None] - FLOOR_TOLERANCE
            floorish = up[cand] > 0.9
            if (into & ~floorish[None, :]).any():
                rows["body"].append(f)
            if (into[~is_foot] & floorish[None, :]).any():
                rows["body_floor"].append(f)
    heights = np.concatenate(rows["floor_heights"]) if rows["floor_heights"] else np.zeros(0)
    lift = np.concatenate(rows["lift"]) if rows["lift"] else np.zeros(0)
    out = {"frames": len(frames), "feet": {"sunk": _spans(rows["sunk"]), "sunk_frames": len(rows["sunk"]),
                                           "off_floor": _spans(rows["off_floor"]), "off_floor_frames": len(rows["off_floor"]),
                                           "floor_height_min": float(heights.min()) if heights.size else None,
                                           "floor_height_max": float(heights.max()) if heights.size else None,
                                           "lowest_above_floor_p01": float(np.percentile(lift, 1)) if lift.size else None,
                                           "lowest_above_floor_min": float(lift.min()) if lift.size else None,
                                           "soles": "skinned shoes" if soles is not None else "foot capsules"},
           "body": {"into_things": _spans(rows["body"]), "into_things_frames": len(rows["body"]),
                    "body_on_floor": _spans(rows["body_floor"]), "body_on_floor_frames": len(rows["body_floor"]),
                    "faces_near_her": int(len(near_her)), "of_them_floor": int(len(floor_faces))},
           "cameras": {}}
    for name, track in cameras.items():
        inside, hidden = [], []
        for f, s in states:
            v = world.view_at(track, f, size)
            # the centre and the four corners of the picture, VIEW_REACH far
            dirs = []
            for u, w in ((0.5, 0.5), (0.02, 0.02), (0.98, 0.02), (0.02, 0.98), (0.98, 0.98)):
                d = v.forward * v.focal + (u - 0.5) * size[0] * v.right - (w - 0.5) * size[1] * v.up
                dirs.append(d / np.linalg.norm(d))
            ends = v.eye[None, :] + VIEW_REACH * np.array(dirs)
            box_lo = np.minimum(ends.min(axis=0), v.eye) - 1.0
            box_hi = np.maximum(ends.max(axis=0), v.eye) + 1.0
            cand = np.nonzero(((tmax >= box_lo) & (tmin <= box_hi)).all(axis=1))[0]
            t, k = segment_hits(np.repeat(v.eye[None, :], len(ends), axis=0), ends, tri_all[cand])
            hit = np.isfinite(t)
            if hit.any():
                back = (normal[cand[k[hit]]] * (ends[hit] - v.eye)).sum(axis=1) > 0
                if back.any():
                    inside.append(f)
            # points of her: both ends of every capsule
            pts = np.array([p for a, b, r in s.capsules for p in (a, b)])
            box_lo = np.minimum(pts.min(axis=0), v.eye) - 1.0
            box_hi = np.maximum(pts.max(axis=0), v.eye) + 1.0
            cand = np.nonzero(((tmax >= box_lo) & (tmin <= box_hi)).all(axis=1))[0]
            if len(cand):
                t, _ = segment_hits(np.repeat(v.eye[None, :], len(pts), axis=0), pts, tri_all[cand])
                # (a face within her own reach of the point is her floor or what she touches, not in front of her)
                gap = (1.0 - t) * np.linalg.norm(pts - v.eye, axis=1)
                if (np.isfinite(t) & (gap > 2.0)).any():
                    hidden.append(f)
        out["cameras"][name] = {"inside": _spans(inside), "inside_frames": len(inside), "hidden": _spans(hidden),
                                "hidden_frames": len(hidden)}
    return out


def shoe_soles(model_path, motion, frames):
    """frame -> [(sole points [k, 3], lowest height)] for each shoe: the shoes' vertices skinned as MMD poses the legs
    (tools/sink_check.py's shoe_vertices and skin, the legs by tools/leg_ik.py), the sole being those within SOLE_BAND of the
    lowest (at most SOLE_POINTS of them, evenly picked)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sink_check", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                            "sink_check.py"))
    sink = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sink)
    from mmd_cli.formats import pmx_edit
    rig = sink.IK.LegRig.load(model_path)
    doc = pmx_edit.load(model_path)
    shoes = {side: sink.shoe_vertices(rig, doc, side) for side in rig.sides}
    frames = list(frames)
    out = {}
    for a in range(0, len(frames), sink.CHUNK):
        block = frames[a:a + sink.CHUNK]
        sol = sink.IK.solve(rig, motion, block)
        for side, (pts, ws, bones) in shoes.items():
            world = sink.skin(rig, side, sol[side], pts, ws, bones, slice(0, len(block)))
            for i, f in enumerate(block):
                v = world[i]
                low = float(v[:, 1].min())
                sole = v[v[:, 1] <= low + SOLE_BAND]
                if len(sole) > SOLE_POINTS:
                    sole = sole[np.linspace(0, len(sole) - 1, SOLE_POINTS).astype(int)]
                out.setdefault(f, []).append((sole, low))
    return lambda f: out[f]


def _spans(frames):
    """[[first, last], ...] runs of frames, with their seconds"""
    runs = []
    for f in frames:
        if runs and f == runs[-1][1] + 1:
            runs[-1][1] = f
        else:
            runs.append([f, f])
    return [{"frames": [a, b], "seconds": [round(a / float(SONG_FPS), 2), round(b / float(SONG_FPS), 2)]} for a, b in runs]


def _mv_look():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mv_look", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mv_look.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _size(text):
    w, h = (int(v) for v in text.lower().split("x"))
    return w, h


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("info", help="the model of a set: its materials, their faces and flags")
    s.add_argument("set")
    s.add_argument("out")
    s = sub.add_parser("batch", help="write the mmd batch that draws the set's model alone with a camera motion")
    s.add_argument("set")
    s.add_argument("camera", help="the camera motion (.vmd) the dancer is drawn with")
    s.add_argument("out", help="the batch file to write")
    s.add_argument("--mmd", required=True, help="MikuMikuDance.exe (a plain one: no MME)")
    s.add_argument("--size", default="1280x720")
    s.add_argument("--avi", help="draw an uncompressed AVI with alpha of the frames --from .. --to (at 30 fps)")
    s.add_argument("--from", dest="start", type=int)
    s.add_argument("--to", type=int)
    s.add_argument("--stills", type=int, nargs="+", help="draw these frames of the song as pictures, into --folder")
    s.add_argument("--folder")
    s = sub.add_parser("unpack", help="MMD's AVI of the stage as a folder of pictures, by frame of the song")
    s.add_argument("avi")
    s.add_argument("folder")
    s.add_argument("--first", type=int, required=True, help="the frame of the song of the AVI's first picture")
    s = sub.add_parser("frame", help="draw one frame of the stage, to look at")
    s.add_argument("set")
    s.add_argument("look")
    s.add_argument("camera")
    s.add_argument("pictures", help="the folder of MMD's pictures of the stage (unpack or batch --stills)")
    s.add_argument("out")
    s.add_argument("--frame", type=int, required=True, help="the frame of the video (at --fps)")
    s.add_argument("--size", default="1280x720")
    s.add_argument("--fps", type=int, default=30)
    s.add_argument("--subframes", type=int, default=1)
    s.add_argument("--shutter", type=float, default=1.0)
    s.add_argument("--model", help="the dancer's model, for her shadow")
    s.add_argument("--motion", action="append", default=[])
    s = sub.add_parser("draw", help="draw the frames of a job file (write_stage with jobs runs these)")
    s.add_argument("job")
    s = sub.add_parser("check", help="where the set puts her over the song: her feet on its floor, her body against it, the "
                                     "cameras in it or behind something in front of her")
    s.add_argument("set")
    s.add_argument("out", help="the numbers (.json)")
    s.add_argument("--model", required=True, help="the dancer's model")
    s.add_argument("--motion", action="append", default=[], required=True, help="her motions, in the order MMD loads them")
    s.add_argument("--camera", action="append", default=[], metavar="NAME=CAMERA.vmd", help="a camera to check (repeatable)")
    s.add_argument("--from", dest="start", type=int, default=0, help="the first frame of the song (default 0)")
    s.add_argument("--to", type=int, help="the last frame (default: her motion's last)")
    s.add_argument("--size", default="1280x720")
    args = p.parse_args(argv)
    try:
        if args.command == "info":
            spec = load_set(args.set)
            mesh = load_mesh(spec["model"])
            out = {"model": spec["model"], "vertices": int(len(mesh.positions)), "faces": int(len(mesh.faces)),
                   "materials": [{"name": m.name, "faces": int((mesh.face_material == i).sum()), "flags": m.flags,
                                  "power": m.power, "alpha": m.alpha} for i, m in enumerate(mesh.materials)]}
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            result = {"out": os.path.abspath(args.out)}
        elif args.command == "batch":
            spec = load_set(args.set)
            lines = batch_lines(spec, os.path.abspath(args.camera), _size(args.size), args.mmd, avi=args.avi, first=args.start,
                                last=args.to, stills=args.stills, folder=args.folder)
            write_batch(lines, args.out)
            result = {"out": os.path.abspath(args.out), "lines": len(lines)}
        elif args.command == "unpack":
            result = {"folder": os.path.abspath(args.folder), "pictures": unpack_avi(args.avi, args.folder, args.first)}
        elif args.command == "frame":
            look = _mv_look().load_look(args.look)
            spec = load_set(args.set)
            world = mv_world()
            figure = world.Figure.from_files(args.model, args.motion, body=True) if args.model else None
            d = Drawer(look, spec, _size(args.size), args.fps, world.camera_track(args.camera), args.pictures, figure,
                       args.subframes, args.shutter)
            img, spill = d.frame(args.frame)
            as_picture(img).save(args.out)
            result = {"out": os.path.abspath(args.out)}
            if spill is not None:
                as_picture(spill).save(args.out[:-4] + "_spill.png")
                result["spill"] = os.path.abspath(args.out[:-4] + "_spill.png")
        elif args.command == "check":
            world = mv_world()
            spec = load_set(args.set)
            figure = world.Figure.from_files(args.model, args.motion, body=True)
            last = figure.last if args.to is None else min(int(args.to), figure.last)
            frames = list(range(int(args.start), last + 1))
            soles = shoe_soles(args.model, figure.body.motion, frames)
            cameras = {}
            for item in args.camera:
                name, _, path = item.partition("=")
                if not path:
                    raise ValueError("--camera is NAME=CAMERA.vmd, not %r" % item)
                cameras[name] = world.camera_track(path)
            got = check_placement(set_mesh(spec), figure, frames, cameras, _size(args.size), soles=soles)
            got.update({"set": os.path.abspath(args.set), "model": os.path.abspath(args.model),
                        "motions": [os.path.abspath(m) for m in args.motion], "offset": spec["offset"]})
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False, indent=1)
            result = {"out": os.path.abspath(args.out), "frames": got["frames"], "sunk": got["feet"]["sunk_frames"],
                      "off_floor": got["feet"]["off_floor_frames"], "into_things": got["body"]["into_things_frames"],
                      "cameras": {k: [v["inside_frames"], v["hidden_frames"]] for k, v in got["cameras"].items()}}
        else:
            result = _draw_job(args.job)
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 1
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
