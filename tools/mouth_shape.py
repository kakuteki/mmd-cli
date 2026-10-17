"""Measure the mouth shapes of a model: how open each mix of mouth morphs looks, how much of the teeth and of the rest of
the inside shows, and where the corners of the opening sit, from MMD's own pictures of the face.

    python tools/mouth_shape.py plan MODEL.pmx OUTDIR [--combo NAME=MORPH:W[,MORPH:W ...] ...] [--no-defaults]
                                     [--key-model KEY.pmx] [--size 720] [--distance 3.5] [--fov 20] [--exe MMD.exe]
    python tools/mouth_shape.py measure OUTDIR [--reference a] [--sheet SHEET.jpg]

Why (v11 face review, 2026-10-17): the lip-sync layer (tools/lip_sync.py) shapes い as い + あ 0.3 and う as う + お 0.2.
Its author measured the dark area of the open mouth on a rest-pose picture (い alone 2 % of あ: the teeth close it), the
rigging review measured the whole inside of the mouth material drawn green (い + あ 0.3 is 0.94 of あ: too open for い) and
recommended い２ or い + あ 0.1.  The two measured different things; this tool measures both on the same pictures: the
teeth and the rest of the inside apart, the height of the opening, its width and its corners, for any mix.

plan: writes OUTDIR/shapes.vmd (combo k on frame k: every morph any combo uses keyed on every frame), OUTDIR/combos.json
and OUTDIR/batch.txt for `mmd batch` (JSON lines), and a measuring copy of the model, KEY (default MODEL's name +
_mouthkey.pmx beside it, where its textures are): the mouth material's faces (MATERIAL, Sour's Rin's 口: the teeth, the
gums and the tongue) split by the texture's colour under each face's UV centroid into the teeth (is_teeth: light and
unsaturated) and the rest, each drawn flat in a key colour (KEY_TEETH green, KEY_INSIDE cyan: black diffuse, the key
as ambient, no texture, sphere, toon, edge or self shadow).  The teeth go to a new material appended at the end, so no
material morph's index moves; nothing else changes.  The batch renders every frame from a still camera straight in
front of the mouth (the mouth material's box at rest: its middle across and up, its front), with the key copy (into
OUTDIR/key/) and then with MODEL as it is (OUTDIR/plain/, the pictures to look at).  MMD's axes and ground shadow off.
measure: per combo, the key picture's teeth and inside pixels (WINDOW: within the middle of the picture, where the camera
looks at the mouth), the opening (either), the opening filled down each column (open_fill: the key pixels and what lies
between them, the inside of the mouth no key covers: Sour's Rin's face mesh lines the mouth's back, 22 % of あ's
opening) and that less the teeth (inside_fill: the gap a viewer reads as an open mouth), its height in a MID_BAND-column
band at the opening's middle (and the rows of it that are not teeth), its greatest height, its width, and its corners: the mean row of the
opening in its first and last CORNER_COLUMNS columns, as a rise over the middle of the opening at its middle band (+ the
corners higher, a smile).  of_ref: the same against the reference combo (default a, あ).  OUTDIR/mouth_shape.json, and
--sheet a picture of the plain pictures, cropped about the mouth, with the outlines of the teeth (green) and the inside
(cyan) and the numbers.

The copy is for measuring only; a model's terms may forbid handing it on.
"""
import argparse
import json
import math
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402

MATERIAL = "口"
TEETH_MATERIAL = "口歯"
KEY_TEETH = (0, 255, 0)
KEY_INSIDE = (0, 255, 255)      # cyan: the model's outlines are purple and its irises light blue (a magenta key took the
                                # hair's outline for the inside, 2026-10-17)
TEETH_LIGHT = 200               # the teeth: every channel of the texture this light or more ...
TEETH_GREY = 40                 # ... and the channels this close (the gums and the tongue are pink: 60 or more apart)
KEY_MARGIN = 80                 # a key pixel: its key channels this much above the others
WINDOW = (0.5, 0.7)             # the share of the picture's height and width about its middle where the mouth is
MID_BAND = 5                    # columns at the opening's middle for its height
CORNER_COLUMNS = 3              # columns at each end of the opening for its corners
SIZE = 720
DISTANCE = 3.5
FOV = 20
EXE = "C:/Users/nayta/Desktop/MikuMikuDance_v932x64/MikuMikuDance.exe"
DEFAULT_COMBOS = [
    ("neutral", {}), ("a", {"あ": 1.0}), ("i", {"い": 1.0}), ("u", {"う": 1.0}), ("e", {"え": 1.0}), ("o", {"お": 1.0}),
    ("n", {"ん": 1.0}), ("i2", {"い２": 1.0}), ("u2", {"う２": 1.0}),
    ("i+a0.05", {"い": 1.0, "あ": 0.05}), ("i+a0.1", {"い": 1.0, "あ": 0.1}), ("i+a0.15", {"い": 1.0, "あ": 0.15}),
    ("i+a0.2", {"い": 1.0, "あ": 0.2}), ("i+a0.3", {"い": 1.0, "あ": 0.3}), ("i2+a0.1", {"い２": 1.0, "あ": 0.1}),
    ("i+e0.2", {"い": 1.0, "え": 0.2}), ("i+e0.3", {"い": 1.0, "え": 0.3}),
    ("u+o0.1", {"う": 1.0, "お": 0.1}), ("u+o0.2", {"う": 1.0, "お": 0.2}), ("u+a0.1", {"う": 1.0, "あ": 0.1}),
    ("a0.5", {"あ": 0.5}), ("i0.5+a0.15", {"い": 0.5, "あ": 0.15}), ("i0.5+a0.05", {"い": 0.5, "あ": 0.05}),
    ("i2_0.5", {"い２": 0.5}), ("u0.5+o0.1", {"う": 0.5, "お": 0.1}), ("u0.5", {"う": 0.5}),
]


# ---- the combos ------------------------------------------------------------------------------

def parse_combo(text):
    """'NAME=MORPH:W,MORPH:W' (weights 0..1; 'NAME=' is the rest pose) -> (name, {morph: weight}); ValueError"""
    if "=" not in text:
        raise ValueError("a combo is NAME=MORPH:W,...: %r" % text)
    name, rest = text.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError("a combo needs a name: %r" % text)
    mix = {}
    for part in [p for p in rest.split(",") if p.strip()]:
        if ":" not in part:
            raise ValueError("a morph of a combo is MORPH:W: %r" % part)
        morph, w = part.rsplit(":", 1)
        morph = morph.strip()
        try:
            weight = float(w)
        except ValueError:
            raise ValueError("not a weight: %r" % part)
        if not 0.0 <= weight <= 1.0 or not morph:
            raise ValueError("a weight is within 0..1: %r" % part)
        if morph in mix:
            raise ValueError("%r is given twice in %r" % (morph, text))
        mix[morph] = weight
    return name, mix


def shapes_motion(combos):
    """the VMD with combo k on frame k (every morph any combo uses keyed on every frame, 0 where the combo leaves it)"""
    used = sorted({m for _, mix in combos for m in mix})
    keys = [vmd.MorphKey(name, f, float(mix.get(name, 0.0))) for f, (_, mix) in enumerate(combos) for name in used]
    return vmd.Motion(model_name="mouth_shape", morphs=keys)


# ---- the measuring copy ----------------------------------------------------------------------

def is_teeth(rgb):
    r, g, b = (int(c) for c in rgb[:3])
    return min(r, g, b) >= TEETH_LIGHT and max(r, g, b) - min(r, g, b) <= TEETH_GREY


def _uv(doc, v):
    return struct.unpack_from("<2f", doc.vertices[v].head, 24)


def _flat(m, colour):
    m.diffuse = (0.0, 0.0, 0.0, 1.0)
    m.specular = (0.0, 0.0, 0.0)
    m.ambient = tuple(c / 255.0 for c in colour)
    m.texture, m.sphere, m.sphere_mode, m.shared_toon, m.toon = -1, -1, 0, 0, -1
    m.flags = m.flags & ~(0x04 | 0x08 | 0x10)
    m.edge_size = 0.0


def key_copy(doc, folder, material=MATERIAL):
    """split `material` of `doc` (pmx_edit.Document, its textures under `folder`) into the teeth (a new material at the
    end) and the rest, both flat key colours; returns the counts"""
    from PIL import Image
    g = pmx_edit.geometry(doc)
    found = [k for k, m in enumerate(g.materials) if m.name == material]
    if not found:
        raise ValueError("the model has no material %s" % material)
    k = found[0]
    mat = g.materials[k]
    if mat.texture < 0:
        raise ValueError("the material %s has no texture to tell the teeth by" % material)
    tex = np.asarray(Image.open(os.path.join(folder, g.textures[mat.texture].replace("\\", "/"))).convert("RGB"))
    h, w = tex.shape[:2]
    a = sum(m.faces for m in g.materials[:k])
    teeth, inside = [], []
    for t in range(mat.faces // 3):
        tri = g.faces[a + 3 * t:a + 3 * t + 3]
        uvs = [_uv(doc, v) for v in tri]
        u = (sum(x for x, _ in uvs) / 3.0) % 1.0
        v = (sum(y for _, y in uvs) / 3.0) % 1.0
        (teeth if is_teeth(tex[min(h - 1, int(v * h)), min(w - 1, int(u * w))]) else inside).append(tri)
    import copy
    tm = copy.deepcopy(mat)
    tm.name, tm.name_en = TEETH_MATERIAL, "mouth teeth key"
    _flat(mat, KEY_INSIDE)
    _flat(tm, KEY_TEETH)
    mat.faces = 3 * len(inside)
    tm.faces = 3 * len(teeth)
    g.faces = g.faces[:a] + [i for tri in inside for i in tri] + g.faces[a + 3 * (len(inside) + len(teeth)):] + [
        i for tri in teeth for i in tri]
    g.materials.append(tm)
    pmx_edit.set_geometry(doc, g)
    return {"material": material, "teeth_faces": len(teeth), "inside_faces": len(inside)}


def mouth_box(doc, material=MATERIAL):
    """(x middle, y middle, front z) of the material's vertices at rest"""
    g = pmx_edit.geometry(doc)
    k = [i for i, m in enumerate(g.materials) if m.name == material]
    if not k:
        raise ValueError("the model has no material %s" % material)
    a = sum(m.faces for m in g.materials[:k[0]])
    ps = np.array([doc.vertices[v].position() for v in set(g.faces[a:a + g.materials[k[0]].faces])], float)
    return (float((ps[:, 0].min() + ps[:, 0].max()) / 2.0), float((ps[:, 1].min() + ps[:, 1].max()) / 2.0),
            float(ps[:, 2].min()))


# ---- the plan --------------------------------------------------------------------------------

def plan(model_path, out, combos, key_model=None, size=SIZE, distance=DISTANCE, fov=FOV, exe=EXE, material=MATERIAL):
    """write the motion, the key copy and the batch (see the module docstring); returns a summary"""
    names = {m.name for m in pmx.load(model_path).morphs}
    unknown = sorted({m for _, mix in combos for m in mix} - names)
    if unknown:
        raise ValueError("the model has no morph %s" % ", ".join(unknown))
    if len({n for n, _ in combos}) != len(combos):
        raise ValueError("two combos have one name")
    key_model = key_model or os.path.splitext(model_path)[0] + "_mouthkey.pmx"
    if os.path.abspath(key_model) == os.path.abspath(model_path):
        raise ValueError("the key copy would overwrite the model")
    doc = pmx_edit.load(model_path)
    centre = mouth_box(doc, material)
    split = key_copy(doc, os.path.dirname(os.path.abspath(model_path)), material)
    os.makedirs(os.path.join(out, "key"), exist_ok=True)
    os.makedirs(os.path.join(out, "plain"), exist_ok=True)
    pmx_edit.dump(doc, key_model)
    shapes = os.path.join(out, "shapes.vmd")
    vmd.dump(shapes_motion(combos), shapes)
    out_abs = os.path.abspath(out).replace("\\", "/")
    lines = [["launch", "--headless", "--exe", exe], ["new"], ["menu", "set", "215", "off"], ["menu", "set", "221", "off"]]
    for tag, model in (("key", key_model), ("plain", model_path)):
        if tag == "plain":
            lines.append(["new"])
        lines += [["model", "load", model], ["motion", "load", shapes.replace("\\", "/"), "--frame", "0"], ["model", "select", "camera"]]
        for f, (name, _) in enumerate(combos):
            lines += [["frame", "set", str(f)],
                      ["camera", "set", "--pos", "%.4f" % centre[0], "%.4f" % centre[1], "%.4f" % centre[2], "--rot", "0", "0", "0",
                       "--distance", "%.3f" % distance, "--fov", str(fov)],
                      ["render", "image", "%s/%s/%s" % (out_abs, tag, picture_name(f, name)), "--size", str(size), str(size)]]
    lines.append(["quit"])
    with open(os.path.join(out, "batch.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n")
    info = {"model": model_path, "key_model": key_model, "combos": [[n, m] for n, m in combos], "size": [size, size],
            "camera": {"look": [round(c, 4) for c in centre], "distance": distance, "fov": fov}, "split": split}
    with open(os.path.join(out, "combos.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    return info


def picture_name(frame, name):
    return "%03d_%s.png" % (frame, "".join(c if c.isalnum() or c in "+-._" else "_" for c in name))


# ---- measuring the pictures ------------------------------------------------------------------

def key_masks(img):
    """(teeth, inside) boolean masks of the key colours within WINDOW about the picture's middle"""
    a = np.asarray(img, int)[:, :, :3]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    teeth = (g - np.maximum(r, b)) > KEY_MARGIN
    inside = (np.minimum(g, b) - r) > KEY_MARGIN
    h, w = teeth.shape
    win = np.zeros_like(teeth)
    dh, dw = int(round(h * WINDOW[0] / 2.0)), int(round(w * WINDOW[1] / 2.0))
    win[max(0, h // 2 - dh):h // 2 + dh, max(0, w // 2 - dw):w // 2 + dw] = True
    return teeth & win, inside & win


def _extent(col):
    rows = np.where(col)[0]
    return (int(rows.max() - rows.min() + 1), float((rows.max() + rows.min()) / 2.0)) if len(rows) else (0, None)


def measure_picture(img):
    """the numbers of one key picture (see the module docstring)"""
    teeth, inside = key_masks(img)
    opening = teeth | inside
    out = {"teeth_px": int(teeth.sum()), "inside_px": int(inside.sum()), "open_px": int(opening.sum()),
           "open_fill_px": 0, "inside_fill_px": 0, "height_mid_px": 0, "inside_height_mid_px": 0, "height_max_px": 0,
           "width_px": 0, "corner_rise_px": None}
    cols = np.where(opening.any(axis=0))[0]
    if not len(cols):
        return out
    c0, c1 = int(cols.min()), int(cols.max())
    # the opening filled down each column: the inside of the mouth that is no part of the mouth material (Sour's Rin:
    # the pocket of the face mesh behind the teeth, a fifth of あ's opening) lies between key pixels
    fill = sum(_extent(opening[:, c])[0] for c in range(c0, c1 + 1))
    out["open_fill_px"] = int(fill)
    out["inside_fill_px"] = int(fill - teeth.sum())
    mid = (c0 + c1) / 2.0
    band = slice(int(math.floor(mid - MID_BAND / 2.0 + 0.5)), int(math.floor(mid + MID_BAND / 2.0 + 0.5)))
    h_mid, row_mid = _extent(opening[:, band].any(axis=1))
    out["height_mid_px"] = h_mid
    if h_mid:
        rows = np.where(opening[:, band].any(axis=1))[0]
        span = teeth[rows.min():rows.max() + 1, band]
        out["inside_height_mid_px"] = int(h_mid - (span.mean(axis=1) >= 0.5).sum())   # the rows that are not teeth
    out["height_max_px"] = max(_extent(opening[:, c])[0] for c in range(c0, c1 + 1))
    out["width_px"] = c1 - c0 + 1
    ends = []
    for cs in (range(c0, min(c1, c0 + CORNER_COLUMNS - 1) + 1), range(max(c0, c1 - CORNER_COLUMNS + 1), c1 + 1)):
        rows = np.concatenate([np.where(opening[:, c])[0] for c in cs])
        ends.append(float(rows.mean()))
    if row_mid is not None:
        out["corner_rise_px"] = round(row_mid - float(np.mean(ends)), 2)
    return out


def relative(rows, reference):
    """each row with of_ref: its open, inside and teeth areas, middle height, inside height and width over the
    reference's"""
    ref = [r for r in rows if r["name"] == reference]
    if not ref:
        raise ValueError("no combo %s to compare with" % reference)
    ref = ref[0]

    def ratio(a, b):
        return round(a / float(b), 3) if b else None
    for r in rows:
        r["of_ref"] = {"open": ratio(r["open_px"], ref["open_px"]), "inside": ratio(r["inside_px"], ref["inside_px"]),
                       "open_fill": ratio(r["open_fill_px"], ref["open_fill_px"]),
                       "inside_fill": ratio(r["inside_fill_px"], ref["inside_fill_px"]),
                       "teeth": ratio(r["teeth_px"], ref["teeth_px"]), "height_mid": ratio(r["height_mid_px"], ref["height_mid_px"]),
                       "inside_height_mid": ratio(r["inside_height_mid_px"], ref["inside_height_mid_px"]),
                       "width": ratio(r["width_px"], ref["width_px"])}
    return rows


def _sheet(path, out, combos, rows, size=240):
    from PIL import Image, ImageDraw
    tiles = []
    for f, ((name, _), row) in enumerate(zip(combos, rows)):
        plain_path = os.path.join(out, "plain", picture_name(f, name))
        key = np.asarray(Image.open(os.path.join(out, "key", picture_name(f, name))).convert("RGB"))
        base = Image.open(plain_path).convert("RGB") if os.path.isfile(plain_path) else Image.fromarray(key.astype(np.uint8), "RGB")
        teeth, inside = key_masks(key)
        h, w = teeth.shape
        crop = (int(w * 0.3), int(h * 0.3), int(w * 0.7), int(h * 0.7))
        img = np.asarray(base, np.uint8).copy()
        for mask, colour in ((teeth, KEY_TEETH), (inside, KEY_INSIDE)):
            edge = mask & ~(np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
            img[edge] = colour
        tile = Image.fromarray(img).crop(crop).resize((size, size))
        d = ImageDraw.Draw(tile)
        rel = row.get("of_ref") or {}
        d.text((4, 4), "%s" % name, fill=(255, 0, 0))
        d.text((4, size - 28), "open %s  in %s" % (rel.get("open"), rel.get("inside")), fill=(255, 0, 0))
        d.text((4, size - 14), "h %s  w %s" % (rel.get("height_mid"), rel.get("width")), fill=(255, 0, 0))
        tiles.append(tile)
    cols = 6
    sheet = Image.new("RGB", (size * cols, size * int(math.ceil(len(tiles) / float(cols)))), (30, 30, 30))
    for k, t in enumerate(tiles):
        sheet.paste(t, (size * (k % cols), size * (k // cols)))
    sheet.save(path, quality=92)


def measure(out, reference="a", sheet=None):
    """measure the key pictures of a plan's OUTDIR; writes OUTDIR/mouth_shape.json (and the sheet); returns the report"""
    from PIL import Image
    with open(os.path.join(out, "combos.json"), encoding="utf-8") as f:
        info = json.load(f)
    combos = [(n, m) for n, m in info["combos"]]
    rows = []
    for f, (name, mix) in enumerate(combos):
        path = os.path.join(out, "key", picture_name(f, name))
        if not os.path.isfile(path):
            raise ValueError("no picture %s" % path)
        row = {"name": name, "mix": mix}
        row.update(measure_picture(np.asarray(Image.open(path).convert("RGB"))))
        rows.append(row)
    relative(rows, reference)
    report = {"reference": reference, "combos": rows, "camera": info.get("camera"), "split": info.get("split"),
              "rules": {"teeth_light": TEETH_LIGHT, "teeth_grey": TEETH_GREY, "key_margin": KEY_MARGIN, "window": list(WINDOW),
                        "mid_band": MID_BAND, "corner_columns": CORNER_COLUMNS}}
    with open(os.path.join(out, "mouth_shape.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if sheet:
        _sheet(sheet, out, combos, rows)
    return report


# ---- the tool --------------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("plan", help="write the motion, the key copy and the batch")
    s.add_argument("model")
    s.add_argument("out")
    s.add_argument("--combo", action="append", default=[], help="NAME=MORPH:W,MORPH:W (repeated)")
    s.add_argument("--no-defaults", action="store_true", help="only the --combo ones")
    s.add_argument("--key-model", help="where the key copy goes (default beside MODEL)")
    s.add_argument("--size", type=int, default=SIZE)
    s.add_argument("--distance", type=float, default=DISTANCE)
    s.add_argument("--fov", type=int, default=FOV)
    s.add_argument("--exe", default=EXE)
    s.add_argument("--material", default=MATERIAL)
    s = sub.add_parser("measure", help="measure the key pictures of a plan")
    s.add_argument("out")
    s.add_argument("--reference", default="a")
    s.add_argument("--sheet")
    args = p.parse_args(argv)
    try:
        if args.what == "plan":
            combos = [] if args.no_defaults else list(DEFAULT_COMBOS)
            for text in args.combo:
                combos.append(parse_combo(text))
            if not combos:
                raise ValueError("no combo")
            if not os.path.isfile(args.model):
                print("mouth_shape: no such file: %s" % args.model, file=sys.stderr)
                return 2
            info = plan(args.model, args.out, combos, args.key_model, args.size, args.distance, args.fov, args.exe, args.material)
            print(json.dumps({"combos": len(combos), "key_model": info["key_model"], "split": info["split"],
                              "batch": os.path.join(args.out, "batch.txt")}, ensure_ascii=True))
        else:
            rep = measure(args.out, args.reference, args.sheet)
            print(json.dumps([[r["name"], r["of_ref"]] for r in rep["combos"]], ensure_ascii=True))
    except ValueError as e:
        print("mouth_shape: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
