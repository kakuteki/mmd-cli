"""Give a PMX model catchlight bones: each highlight quad of the eyes moves on a bone of its own that turns with the
gaze by a share of its rotation, as the reflection of a light on the cornea does.

    python tools/pmx_eyes.py MODEL.pmx OUT.pmx [--report r.json] [--share K] [--material HL]
                             [--reveal HL HL２] [--pupil-morph 瞳大] [--clear D] [--margin 0.008] [--rim D]

Why: on Sour's Rin the highlights (material HL) hang on the iris' bone (右目子 / 左目子) and turn with the eye as if
painted on it: turned 15 degrees, the eye carries its light along to the same spot of the iris (stage 4 probe, f45 and
f75).  (右目補助 / 左目補助, between the eye and the iris' bone, take -0.5 of the eye's turn, but about the iris'
centre: they keep the iris' disc from turning fully, they do not hold the light back.)  A real eye's light is a mirror
image in the cornea and moves with the cornea's centre of curvature, K = 4.67 mm behind the entrance pupil
(stage 5 RESEARCH 1.1 to 1.4): when the eye turns by g, the light lags the pupil's centre by 0.79 proj(g) iris radii
(0.79 = K over the iris' radius 5.91 mm; the Hirschberg ratio, measured 12.3 to 12.9 degrees/mm).

The share by default (--share not given) keeps that lag on the model's iris (RESEARCH 5.1, formula A): the model's
pupil lies D_p in front of the eye's bone and its iris is r wide (half), so a turn by theta moves the pupil
D_p sin(theta) and the light should follow D_p sin(theta) - 0.79 r sin(theta): share 1 - 0.79 r / D_p.  Sour's Rin:
r 0.1625 across X, D_p 0.415, 0.69 (its iris crossed 4.5 % of its radius a degree, a human's 3.5 %).  The head-relative
ratios of a human eye (formula B, 0.60 across and 0.48 up and down, Ohlendorf 2022) would leave the light 30 % further
behind on this iris: with 0.55 the upper light left the iris for the eye white at a 15-degree gaze (stage 5 probe).
Up and down formula A gives 0.58 on this iris (its half height 0.222): one append ratio cannot hold both, so the
append takes the share across (the gaze moves mostly sideways, up to 18 degrees against 6 up and 10 down) and
tools/eye_optics.py, which keys every frame from formula A, sets the rest.

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
  light 24 % more than the lower).  tools/eye_optics.py keys these bones every frame so that each light sits where
  formula A puts it (the light source, the camera, the eyes' vergence); the append alone stands in for a gaze that
  tool did not see.
* The quad's vertices move wholly onto its bone (BDEF1); no other weight changes.  The new bones join the display
  frame that holds 両目.
* The bones can also move (translate): tools/eye_optics.py keys each light along the camera's line onto the iris'
  surface where the light has come to, at the height above it the light was drawn at.  Sour's Rin's iris is a shallow
  dish tilted outward (at 0.9 of its radius its nasal side lies 0.1 in front of its temporal side) and each light was
  drawn 0.01 to 0.04 in front of the dish where it lies: a light that slides across the iris without that hides behind
  the dish where it rises (turned 15 degrees, the eye hid a light behind its own rim; seen at a slant the near rim hid
  the deep lights: stage 5 probes).  A lift instead (every light brought out in front of the iris' frontmost point)
  put the temporal lights 0.1 to 0.15 in front of their own part of the dish, in front of the lids too: the lights
  showed on the lash line and on the lower lid's skin (stage 5 ray check of the MV, 2.7 % of the lights in frames).
  So nothing is lifted by default; the closing morphs (まばたき, 笑い, ウィンク, ...) stay as they were and hide the
  lights where they always did.  lift_quads (--clear, --rim) brings the quads out when asked.

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

HUMAN = {                       # mm, a human eye (stage 5 RESEARCH 1.1)
    "pupil_to_centre": 4.67,    # K: the entrance pupil to the cornea's centre of curvature (7.72 - 3.05)
    "iris_radius": 5.91,        # half the visible iris (Aguirre 2019)
    "cornea_radius": 7.72,      # the cornea's front surface (Navarro, via Barsingerhorn 2017)
    "pupil_across": 11.7,       # d_p, the centre of rotation to the entrance pupil, turning sideways (Ohlendorf 2022)
    "pupil_up": 8.9,            # the same turning up and down
}
SHARE = None                    # the share of the eye's turn the light follows; None: formula A on the model (build)
IRIS_MATERIAL = "瞳"
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
SURFACES = ("瞳", "目白")         # the iris and the eye white: a light stays in front of them
CLEAR = None                    # model units a light may slide across them and stay in front (lift_quads; None: no rule)
MARGIN = 0.008                  # model units it stays in front by at least
RIM = None                      # model units a light lies in front of the iris' frontmost point (lift_quads; None: no rule)
TRANSLATE = 0x0004              # the bone moves: tools/eye_optics.py keeps each light on the iris' surface
CLOSING_DROP = 0.08             # a morph that lowers an eye's upper light by this much on average closes its lids


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


def morph_names(doc, morph):
    """(name, English name) of a pmx_edit morph"""
    r = _Reader(morph.head, doc.encoding)
    return r.text(), r.text()


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


def eye_surfaces(doc, eye_idx, materials=SURFACES):
    """{eye index: [(p0, p1, p2)]}: the rest-pose triangles of `materials` (those the model has), by the eye each hangs
    under"""
    out = {e: [] for e in eye_idx}
    for name in materials:
        for t in material_triangles(doc, name) or []:
            out[_eye_of(doc, t[0], eye_idx)].append(tuple(doc.vertices[v].position() for v in t))
    return out


def surface_z(triangles, x, y):
    """the frontmost (smallest) z of the triangles over the point (x, y), seen along Z; None where none lies"""
    best = None
    for a, b, c in triangles:
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-14:
            continue
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
        l3 = 1.0 - l1 - l2
        if min(l1, l2, l3) < -1e-9:
            continue
        z = l1 * a[2] + l2 * b[2] + l3 * c[2]
        if best is None or z < best:
            best = z
    return best


def needed_lift(points, triangles, clear=0.06, margin=MARGIN, rings=3, spokes=16):
    """how far toward -Z the points must come so that each, slid by up to `clear` across X and Y in any direction,
    lies at least `margin` in front of the triangles (0 when they already do)"""
    import math
    slides = [(0.0, 0.0)]
    for r in range(1, rings + 1):
        for s in range(spokes):
            a = 2.0 * math.pi * s / spokes
            slides.append((clear * r / rings * math.cos(a), clear * r / rings * math.sin(a)))
    lift = 0.0
    for p in points:
        for dx, dy in slides:
            z = surface_z(triangles, p[0] + dx, p[1] + dy)
            if z is not None:
                lift = max(lift, p[2] - (z - margin))
    return lift


def _set_position(vertex, position):
    vertex.head = struct.pack("<3f", *position) + vertex.head[12:]


def closing_morphs(doc, quads, reveal, drop=CLOSING_DROP):
    """{morph name: set of eye indices}: the vertex morphs (not the reveal morphs) that lower an eye's upper quad by
    `drop` or more on average, so closing the lids over that eye's lights"""
    out = {}
    for name, offsets in vertex_morphs(doc).items():
        if name in reveal:
            continue
        for q in quads:
            if q.get("rank") != 1:
                continue
            dys = [offsets[v][1] for v in q["vertices"] if v in offsets]
            if len(dys) == len(q["vertices"]) and sum(dys) / len(dys) <= -drop:
                out.setdefault(name, set()).add(q["eye_index"])
    return out


def iris_front(doc, eye_idx, material=IRIS_MATERIAL):
    """{eye index: the frontmost (smallest) z of the eye's vertices of the iris material}, rest pose: on a dish-shaped
    iris its rim"""
    out = {}
    for t in material_triangles(doc, material) or []:
        for v in t:
            z = doc.vertices[v].position()[2]
            e = _eye_of(doc, v, eye_idx)
            if e not in out or z < out[e]:
                out[e] = z
    return out


def lift_quads(doc, quads, reveal, clear=CLEAR, margin=MARGIN, surfaces=SURFACES, rim=RIM, iris_material=IRIS_MATERIAL):
    """bring each quad (revealed) out in front of the eye's iris and white for slides up to `clear` (needed_lift) and,
    unless `rim` is None, `rim` in front of the iris' frontmost point (iris_front), moving its vertices toward -Z (the
    larger of the two lifts).  The morphs that close the lids over an eye (closing_morphs) are left as they were.
    Updates the quads' centroid, depth and pivot; returns ({quad name: lift}, {morph: [eye names]})"""
    morphs = vertex_morphs(doc)
    shown = [morphs[name] for name in reveal if name in morphs]
    eye_idx = sorted({q["eye_index"] for q in quads})
    tris = eye_surfaces(doc, eye_idx, surfaces)
    front = iris_front(doc, eye_idx, iris_material) if rim is not None else {}
    lifts = {}
    for q in quads:
        pts = []
        for v in q["vertices"]:
            p = list(doc.vertices[v].position())
            for offsets in shown:
                o = offsets.get(v)
                if o:
                    p = [a + b for a, b in zip(p, o)]
            pts.append(tuple(p))
        lift = needed_lift(pts + [_centroid(pts)], tris[q["eye_index"]], clear, margin) if clear is not None else 0.0
        if q["eye_index"] in front:
            lift = max(lift, max(p[2] for p in pts) - (front[q["eye_index"]] - rim))
        lifts[q["name"]] = lift
    closing = closing_morphs(doc, quads, reveal)
    for q in quads:
        lift = lifts[q["name"]]
        if lift <= 0.0:
            continue
        for v in q["vertices"]:
            x, y, z = doc.vertices[v].position()
            _set_position(doc.vertices[v], (x, y, z - lift))
        q["centroid"] = (q["centroid"][0], q["centroid"][1], q["centroid"][2] - lift)
        q["pivot"] = (q["pivot"][0], q["pivot"][1], q["pivot"][2] - lift)
        q["depth"] += lift
    return lifts, {name: sorted(doc.bones[e].name for e in eyes) for name, eyes in sorted(closing.items())}


def model_scale(doc, pupil_morph=PUPIL_MORPH, iris_material=IRIS_MATERIAL):
    """the model's eye against HUMAN: {"pupil_depth" (the pupil morph's vertices in front of the eye's bone, both
    eyes' mean), "iris_half_width", "iris_half_height" (half the X and Y extents of iris_material per eye, the mean),
    "share_a" (formula A across and up, see the module docstring), "share_b" (a human eye's head-relative ratios),
    "degree_share" (how much of its iris' half width the pupil crosses a degree, against a human's)}"""
    import math
    eye_idx, _ = find_eyes(doc)
    pupil = vertex_morphs(doc).get(pupil_morph) or {}
    depths, widths, heights = [], [], []
    iris = sorted({v for t in material_triangles(doc, iris_material) or [] for v in t})
    for e in eye_idx:
        mine = [doc.vertices[v].position() for v in pupil if _eye_of(doc, v, eye_idx) == e]
        if mine:
            depths.append(_dot(tuple(a - b for a, b in zip(_centroid(mine), doc.bones[e].position)), FORWARD))
        pts = [doc.vertices[v].position() for v in iris if _eye_of(doc, v, eye_idx) == e]
        if pts:
            widths.append((max(p[0] for p in pts) - min(p[0] for p in pts)) / 2.0)
            heights.append((max(p[1] for p in pts) - min(p[1] for p in pts)) / 2.0)
    if not depths:
        raise ValueError("the model has no vertex morph %r: the pupil's depth is measured on its vertices" % pupil_morph)
    if not widths:
        raise ValueError("the model has no %s material: the iris' size is measured on it" % iris_material)
    depth = sum(depths) / len(depths)
    width, height = sum(widths) / len(widths), sum(heights) / len(heights)
    lag = HUMAN["pupil_to_centre"] / HUMAN["iris_radius"]
    k = HUMAN["pupil_to_centre"]
    per_degree = math.radians(1.0)
    return {"pupil_depth": depth, "iris_half_width": width, "iris_half_height": height,
            "share_a": [1.0 - lag * width / depth, 1.0 - lag * height / depth],
            "share_b": [1.0 - k / HUMAN["pupil_across"], 1.0 - k / HUMAN["pupil_up"]],
            "degree_share": [depth * per_degree / width / (HUMAN["pupil_across"] * per_degree / HUMAN["iris_radius"]),
                             depth * per_degree / height / (HUMAN["pupil_up"] * per_degree / HUMAN["iris_radius"])]}


def default_share(scale):
    """the append ratio when --share is not given: formula A across (model_scale's share_a[0])"""
    return scale["share_a"][0]


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
            q["rank"] = n
            q["pivot"] = tuple(c - depth[e] * f for c, f in zip(q["centroid"], FORWARD))
            ordered.append(q)
    names = [q["name"] for q in ordered]
    if len(set(names)) != len(names):
        raise ValueError("two highlight quads of one eye would get the same bone name: %s" % names)
    for name in names:
        if len(name.encode("cp932", "replace")) > NAME_BYTES:
            raise ValueError("the bone name %r is longer than the %d bytes a VMD keeps" % (name, NAME_BYTES))
    return ordered, {doc.bones[e].name: depth[e] for e in eye_idx}, eye_idx, handle_idx


def build(doc, share=SHARE, material=MATERIAL, reveal=REVEAL, pupil_morph=PUPIL_MORPH, clear=CLEAR, margin=MARGIN,
          rim=RIM):
    """add the catchlight bones to `doc` (formats.pmx_edit.Document), bring the highlights out in front of the iris
    (lift_quads; rim None leaves out the rule of the iris' front) and move them onto the bones; returns a report"""
    scale = model_scale(doc, pupil_morph)
    if share is None:
        share = min(1.0, max(0.0, default_share(scale)))
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
    if (clear is not None and clear < 0.0) or margin < 0.0 or (rim is not None and rim < 0.0):
        raise ValueError("--clear, --margin and --rim are distances in model units, 0 or more")
    front = iris_front(doc, eye_idx)
    lifts, closing = lift_quads(doc, quads, tuple(reveal), clear, margin, rim=rim)
    added = []
    for q in quads:
        eye = doc.bones[q["eye_index"]]
        bone = pmx_edit.new_bone(q["name"], q["name_en"], q["pivot"], parent=eye.parent, layer=eye.layer,
                                 tail_offset=tuple(depth[eye.name] * f for f in FORWARD))
        bone.flags |= APPEND_ROTATE | TRANSLATE
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
    return {"share": float(share), "share_a": scale["share_a"], "share_b": scale["share_b"],
            "degree_share": scale["degree_share"], "iris_half_width": scale["iris_half_width"],
            "iris_half_height": scale["iris_half_height"],
            "follows": doc.bones[handle_idx].name, "material": material, "reveal": list(reveal),
            "pupil_morph": pupil_morph, "pupil_depth": {k: round(v, 6) for k, v in depth.items()},
            "eyes": {doc.bones[e].name: list(doc.bones[e].position) for e in eye_idx},
            "quads": [{"bone": q["name"], "name_en": q["name_en"], "eye": doc.bones[q["eye_index"]].name,
                       "reveal": q["reveal"], "vertices": q["vertices"], "centroid": [round(c, 6) for c in q["centroid"]],
                       "depth": round(q["depth"], 6), "pivot": [round(c, 6) for c in q["pivot"]],
                       "lift": round(lifts[q["name"]], 6)} for q in quads],
            "clear": clear, "margin": margin, "rim": rim,
            "iris_front": {doc.bones[e].name: round(z, 6) for e, z in sorted(front.items())}, "closing": closing,
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
    ap.add_argument("--share", type=float, default=SHARE,
                    help="the share of the eye's turn the light follows (default: the human eye's, scaled by the model's iris)")
    ap.add_argument("--material", default=MATERIAL, help="the highlights' material (default %s)" % MATERIAL)
    ap.add_argument("--reveal", nargs="+", default=list(REVEAL), help="the morphs that pull the highlights out (default HL HL２)")
    ap.add_argument("--pupil-morph", default=PUPIL_MORPH, help="a morph of the pupil's vertices: their depth (default %s)" % PUPIL_MORPH)
    ap.add_argument("--clear", type=float, default=CLEAR,
                    help="model units a light may slide across the iris and stay in front of it (default: no rule)")
    ap.add_argument("--margin", type=float, default=MARGIN, help="how far in front, at least (default %g)" % MARGIN)
    ap.add_argument("--rim", type=float, default=RIM,
                    help="model units every light lies in front of the iris' frontmost point, at least (default: no rule)")
    a = ap.parse_args(argv)
    try:
        if os.path.normcase(os.path.abspath(a.model)) == os.path.normcase(os.path.abspath(a.out)):
            raise ValueError("the output would overwrite the model")
        if a.report and os.path.normcase(os.path.abspath(a.report)) in {os.path.normcase(os.path.abspath(p)) for p in (a.model, a.out)}:
            raise ValueError("the report would overwrite a model")
        doc = pmx_edit.load(a.model)
        report = build(doc, a.share, a.material, a.reveal, a.pupil_morph, a.clear, a.margin, a.rim)
        _write(a.out, pmx_edit.dumps(doc))
        if a.report:
            _write(a.report, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "share": report["share"],
                      "share_a": report["share_a"], "share_b": report["share_b"],
                      "bones": [q["bone"] for q in report["quads"]], "moved_vertices": report["moved_vertices"],
                      "pupil_depth": report["pupil_depth"], "lifts": [q["lift"] for q in report["quads"]],
                      "closing": sorted(report["closing"])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
