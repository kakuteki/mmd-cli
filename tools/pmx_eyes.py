"""Give a PMX model catchlight bones: each highlight quad of the eyes moves on a bone of its own that turns with the
gaze by a share of its rotation, as the reflection of a light on the cornea does.

    python tools/pmx_eyes.py MODEL.pmx OUT.pmx [--report r.json] [--share 0.55] [--material HL]
                             [--reveal HL HL２] [--pupil-morph 瞳大]

Why: on Sour's Rin the highlights (material HL) hang on the iris' bone (右目子 / 左目子) and turn with the eye as if
painted on it: turned 15 degrees, the eye carries its light along to the same spot of the iris (stage 4 probe, f45 and
f75).  A real eye's light is a mirror image in the cornea: when the eye turns, the cornea's centre of curvature moves
(it lies between the eye's centre of rotation and the pupil), but the point of the cornea that faces the half-way
direction between the light and the viewer does not turn with the eye.  The light therefore moves by
d / d_p of the pupil's way, d the distance from the centre of rotation to the cornea's centre of curvature and d_p
that to the (entrance) pupil: about 5.7 / 10.4 = 0.55 for a human eye (Gullstrand-Le Grand: the centre of rotation
13.5 mm behind the apex of the cornea, its radius 7.8 mm, the entrance pupil 3.05 mm behind the apex).

What is built (formats.pmx_edit keeps every other byte of the file):

* The eyes are 右目 and 左目, each turning with the gaze handle 両目 by append (ratio 1, as tools/eye_gaze.py
  expects); the highlights are the vertices of the material --material (HL), split into quads (the connected pieces of
  its faces), each quad given to the eye whose bone it hangs under (else the nearest eye).
* Each quad's position is taken with the morphs that pull it out in front of the iris (--reveal, the HL and HL２ that
  tools/face_life.py --hold keeps at 1): on Sour's Rin they hide behind the iris at rest.
* One bone per quad, added after every bone of the file (no index moves): parent the eyes' parent (頭), turning with
  両目 by append with ratio --share, on the eyes' deform layer.  Its pivot lies the pupil's depth behind the revealed
  quad (straight back, +Z), the pupil's depth being that of the --pupil-morph's vertices in front of the eye's bone:
  a turn of the bone then moves the quad sideways as far as the same turn of the eye moves the pupil, so ratio
  --share moves it --share of the pupil's way, whatever the quad's own depth (Sour's Rin's upper quad lies 0.514
  in front of the eye's bone, the lower 0.411, the pupil 0.413: one bone at the eye's centre would move the upper
  light 24 % more than the lower).  tools/eye_optics.py keys these bones with the rest of the light's motion (the
  head's turns against the light, the eyes' vergence) and reads --share back from the append ratio.
* The quad's vertices move wholly onto its bone (BDEF1); no vertex moves, no other weight changes.  The new bones
  join the display frame that holds 両目.

Names: the side's first character and the reveal morph (右HL２, 右HL, 左HL２, 左HL; at most 15 bytes of cp932, the VMD
limit), English names catchlight_<R|L>_<n> (the upper quad first).  A model that already has them is refused.  The
model is changed for this work only and is not to be distributed (Sour's ReadMe allows editing; distribution would
need the ReadMe and an editor's ReadMe).
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit  # noqa: E402
from mmd_cli.formats.pmx import _Reader  # noqa: E402

SHARE = 0.55                    # the share of the eye's turn the light follows: d / d_p (see the docstring)
MATERIAL = "HL"
REVEAL = ("HL", "HL２")
PUPIL_MORPH = "瞳大"
EYES = ("右目", "左目")
HANDLE = "両目"
FORWARD = (0.0, 0.0, -1.0)      # the rest gaze: the model faces -Z
EN_PREFIX = "catchlight"
SIDE_EN = {"右": "R", "左": "L"}
APPEND_ROTATE = 0x0100
NAME_BYTES = 15                 # a VMD names a bone in 15 bytes of cp932


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _centroid(points):
    return tuple(sum(p[c] for p in points) / len(points) for c in range(3))


def middle_tables(doc):
    """(the face index list, [(material name, its index count)]) from the raw middle of a pmx_edit.Document"""
    r = _Reader(doc.middle, doc.encoding)
    size = doc.sizes["vertex"]
    n = r.i32()
    faces = struct.unpack_from("<%d%s" % (n, {1: "B", 2: "H", 4: "i"}[size]), doc.middle, r.pos)
    r.skip(n * size)
    for _ in range(r.i32()):
        r.text()
    materials = []
    texture = doc.sizes["texture"]
    for _ in range(r.i32()):
        name = r.text()
        r.text()
        r.skip(65 + 2 * texture)
        r.u8()                                  # sphere mode
        if r.u8():                              # a shared toon number, or a texture index
            r.u8()
        else:
            r.skip(texture)
        r.text()
        materials.append((name, r.i32()))
    return faces, materials


def material_triangles(doc, name):
    """[(a, b, c)] the faces of the material `name`, or None when the model has no such material"""
    faces, materials = middle_tables(doc)
    start = 0
    for mname, count in materials:
        if mname == name:
            return [tuple(faces[i:i + 3]) for i in range(start, start + count, 3)]
        start += count
    return None


def morph_name(doc, morph):
    return _Reader(morph.head, doc.encoding).text()


def vertex_morphs(doc):
    """{name: {vertex: (dx, dy, dz)}} of the vertex morphs (the first of a name)"""
    size = doc.sizes["vertex"]
    fmt = "<" + {1: "B", 2: "H", 4: "i"}[size]
    out = {}
    for m in doc.morphs:
        if m.kind != 1:
            continue
        name = morph_name(doc, m)
        if name in out:
            continue
        offsets = {}
        for k in range(m.count):
            at = k * (size + 12)
            offsets[struct.unpack_from(fmt, m.body, at)[0]] = struct.unpack_from("<3f", m.body, at + size)
        out[name] = offsets
    return out


def components(triangles):
    """the connected pieces of a set of triangles: [sorted vertex list], in the order of their first triangle"""
    parent = {}

    def find(v):
        while parent.setdefault(v, v) != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for a, b, c in triangles:
        for x, y in ((a, b), (b, c)):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx
    order, groups = [], {}
    for tri in triangles:
        for v in tri:
            root = find(v)
            if root not in groups:
                groups[root] = set()
                order.append(root)
            groups[root].add(v)
    return [sorted(groups[root]) for root in order]


def _eye_of(doc, vertex, eyes):
    """the eye bone (index) a vertex hangs under: up the parent chain of its heaviest bone, else the nearest eye"""
    pairs = sorted(doc.vertices[vertex].pairs(), key=lambda bw: -bw[1])
    bone, seen = pairs[0][0], set()
    while bone >= 0 and bone not in seen:
        if bone in eyes:
            return bone
        seen.add(bone)
        bone = doc.bones[bone].parent
    p = doc.vertices[vertex].position()
    return min(eyes, key=lambda e: sum((a - b) ** 2 for a, b in zip(p, doc.bones[e].position)))


def _side_of(doc, vertices, eyes):
    votes = {}
    for v in vertices:
        e = _eye_of(doc, v, eyes)
        votes[e] = votes.get(e, 0) + 1
    return max(sorted(votes), key=lambda e: votes[e])


def find_eyes(doc, eyes=EYES, handle=HANDLE):
    """(the eye bone indices, the handle's index): each eye turning with the handle by append"""
    names = {b.name: i for i, b in reversed(list(enumerate(doc.bones)))}
    missing = [n for n in eyes if n not in names]
    if missing:
        raise ValueError("the model has no %s bone: there is no eye to put a light on" % "/".join(missing))
    out = [names[n] for n in eyes]
    for i in out:
        b = doc.bones[i]
        if not (b.flags & APPEND_ROTATE and 0 <= b.append_parent < len(doc.bones)
                and doc.bones[b.append_parent].name == handle):
            raise ValueError("%s does not turn with %s by append: the gaze of tools/eye_gaze.py keys %s"
                             % (b.name, handle, handle))
    return out, names[handle]


def plan(doc, material=MATERIAL, reveal=REVEAL, pupil_morph=PUPIL_MORPH, eyes=EYES, handle=HANDLE):
    """the quads and their bones, before anything is changed: (quads, pupil depth by eye name, eye indices, handle)"""
    eye_idx, handle_idx = find_eyes(doc, eyes, handle)
    triangles = material_triangles(doc, material)
    if not triangles:
        raise ValueError("the model has no faces of the material %r: there are no highlights to move" % material)
    morphs = vertex_morphs(doc)
    pupil = morphs.get(pupil_morph)
    if not pupil:
        raise ValueError("the model has no vertex morph %r: the pupil's depth is measured on its vertices" % pupil_morph)
    depth = {}
    for e in eye_idx:
        mine = [v for v in pupil if _eye_of(doc, v, eye_idx) == e]
        if not mine:
            raise ValueError("%s moves no vertex of %s" % (pupil_morph, doc.bones[e].name))
        c = _centroid([doc.vertices[v].position() for v in mine])
        depth[e] = _dot(tuple(a - b for a, b in zip(c, doc.bones[e].position)), FORWARD)
    shown = [(name, morphs[name]) for name in reveal if name in morphs]
    quads = []
    for vertices in components(triangles):
        eye = _side_of(doc, vertices, eye_idx)
        pulled = []
        by = []
        for name, offsets in shown:
            if any(v in offsets for v in vertices):
                by.append(name)
        for v in vertices:
            p = list(doc.vertices[v].position())
            for name, offsets in shown:
                o = offsets.get(v)
                if o:
                    p = [a + b for a, b in zip(p, o)]
            pulled.append(tuple(p))
        c = _centroid(pulled)
        quads.append({"eye_index": eye, "vertices": vertices, "reveal": by[0] if len(by) == 1 else None, "centroid": c,
                      "depth": _dot(tuple(a - b for a, b in zip(c, doc.bones[eye].position)), FORWARD)})
    ordered = []
    for e in eye_idx:
        mine = sorted((q for q in quads if q["eye_index"] == e), key=lambda q: -q["centroid"][1])
        side = doc.bones[e].name[0]
        for n, q in enumerate(mine, 1):
            q["name"] = side + (q["reveal"] if q["reveal"] else material + str(n))
            q["name_en"] = "%s_%s_%d" % (EN_PREFIX, SIDE_EN.get(side, str(eye_idx.index(e))), n)
            q["pivot"] = tuple(c - depth[e] * f for c, f in zip(q["centroid"], FORWARD))
            ordered.append(q)
    names = [q["name"] for q in ordered]
    if len(set(names)) != len(names):
        raise ValueError("two highlight quads of one eye would get the same bone name: %s" % names)
    for name in names:
        if len(name.encode("cp932", "replace")) > NAME_BYTES:
            raise ValueError("the bone name %r is longer than the %d bytes a VMD keeps" % (name, NAME_BYTES))
    return ordered, {doc.bones[e].name: depth[e] for e in eye_idx}, eye_idx, handle_idx


def build(doc, share=SHARE, material=MATERIAL, reveal=REVEAL, pupil_morph=PUPIL_MORPH):
    """add the catchlight bones to `doc` (formats.pmx_edit.Document) and move the highlights onto them; returns a report"""
    if not 0.0 < share <= 1.0:
        raise ValueError("--share is the part of the eye's turn the light follows, above 0 and at most 1, not %r" % share)
    if any(b.name_en.startswith(EN_PREFIX) for b in doc.bones):
        raise ValueError("the model already has catchlight bones (%s...): build it from the model without them"
                         % EN_PREFIX)
    quads, depth, eye_idx, handle_idx = plan(doc, material, tuple(reveal), pupil_morph)
    taken = {b.name for b in doc.bones}
    clash = [q["name"] for q in quads if q["name"] in taken]
    if clash:
        raise ValueError("the model already has bones named %s" % ", ".join(clash))
    added = []
    for q in quads:
        eye = doc.bones[q["eye_index"]]
        bone = pmx_edit.new_bone(q["name"], q["name_en"], q["pivot"], parent=eye.parent, layer=eye.layer,
                                 tail_offset=tuple(depth[eye.name] * f for f in FORWARD))
        bone.flags |= APPEND_ROTATE
        bone.append_parent, bone.append_ratio = handle_idx, float(share)
        index = pmx_edit.insert_bone(doc, len(doc.bones), bone)
        for v in q["vertices"]:
            doc.vertices[v].set_weights([(index, 1.0)])
        added.append(index)
    frame_name = None
    for f in doc.frames:
        if any(k == 0 and i in [handle_idx] + list(eye_idx) for k, i in f.items):
            f.items = f.items + [(0, i) for i in added]
            frame_name = _Reader(f.names, doc.encoding).text()
            break
    return {"share": float(share), "follows": doc.bones[handle_idx].name, "material": material, "reveal": list(reveal),
            "pupil_morph": pupil_morph, "pupil_depth": {k: round(v, 6) for k, v in depth.items()},
            "eyes": {doc.bones[e].name: list(doc.bones[e].position) for e in eye_idx},
            "quads": [{"bone": q["name"], "name_en": q["name_en"], "eye": doc.bones[q["eye_index"]].name,
                       "reveal": q["reveal"], "vertices": q["vertices"], "centroid": [round(c, 6) for c in q["centroid"]],
                       "depth": round(q["depth"], 6), "pivot": [round(c, 6) for c in q["pivot"]]} for q in quads],
            "moved_vertices": sum(len(q["vertices"]) for q in quads), "display_frame": frame_name}


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", help="the model (.pmx) with 右目 and 左目 turning with 両目 and the highlights' material")
    ap.add_argument("out", help="the model to write (.pmx): next to the model, for its textures")
    ap.add_argument("--report", help="write the quads, their bones and pivots to this JSON")
    ap.add_argument("--share", type=float, default=SHARE, help="the share of the eye's turn the light follows (default %g)" % SHARE)
    ap.add_argument("--material", default=MATERIAL, help="the highlights' material (default %s)" % MATERIAL)
    ap.add_argument("--reveal", nargs="+", default=list(REVEAL), help="the morphs that pull the highlights out (default HL HL２)")
    ap.add_argument("--pupil-morph", default=PUPIL_MORPH, help="a morph of the pupil's vertices: their depth (default %s)" % PUPIL_MORPH)
    a = ap.parse_args(argv)
    try:
        if os.path.normcase(os.path.abspath(a.model)) == os.path.normcase(os.path.abspath(a.out)):
            raise ValueError("the output would overwrite the model")
        if a.report and os.path.normcase(os.path.abspath(a.report)) in {os.path.normcase(os.path.abspath(p)) for p in (a.model, a.out)}:
            raise ValueError("the report would overwrite a model")
        doc = pmx_edit.load(a.model)
        report = build(doc, a.share, a.material, a.reveal, a.pupil_morph)
        _write(a.out, pmx_edit.dumps(doc))
        if a.report:
            _write(a.report, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "share": report["share"],
                      "bones": [q["bone"] for q in report["quads"]], "moved_vertices": report["moved_vertices"],
                      "pupil_depth": report["pupil_depth"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
