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


# ---- the command ----------------------------------------------------------------------------

def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("info", help="the model of a set: its materials, their faces and flags")
    s.add_argument("set")
    s.add_argument("out")
    args = p.parse_args(argv)
    try:
        with open(args.set, encoding="utf-8") as f:
            spec = json.load(f)
        mesh = load_mesh(spec["model"])
        out = {"model": spec["model"], "vertices": int(len(mesh.positions)), "faces": int(len(mesh.faces)),
               "materials": [{"name": m.name, "faces": int((mesh.face_material == i).sum()), "flags": m.flags, "power": m.power,
                              "alpha": m.alpha} for i, m in enumerate(mesh.materials)]}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
