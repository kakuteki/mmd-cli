"""Change the rig of a PMX model in a copy: the leg IK's loops, and (as the recipe grows) twist bones with their weights,
morphs and physics.  Everything the recipe does not name is kept byte for byte (formats.pmx_edit).

    python tools/pmx_rig.py MODEL.pmx OUT.pmx [--report r.json] [--leg-ik-loops N] [--knee-least-bend DEG]
                            [--inner-brow UNITS] [--joint-helpers wrist,shoulder,hip]

Recipe:
  --leg-ik-loops N    the loops of the leg IKs (足ＩＫ, both sides).  MMD's leg IK is a CCD that keeps a loop only when it
                      brings the ankle closer and stops at the first that does not; near a straight leg it gains little a
                      loop, so 40 loops (Sour's Rin, most models) leave the ankle short of a goal the leg could reach
                      (v10: 4 mm or more on 228 + 439 frames, up to 1.3 cm, tools/rig_check.py ik).  More loops let it
                      get there; a frame that converges sooner stops sooner, so they cost only where they help.
  --knee-least-bend D the knee's IK limit (ひざ, the leg IK's first link, a turn about X) ends D degrees short of the
                      model's rest bend instead of at it: where the dance asks for the whole leg's length the knee keeps
                      D degrees more than at rest (Sour's Rin rests at 5.7 degrees) instead of locking there.  It costs a
                      goal at the very end of the reach at most the difference of the two reaches (Rin, 5 degrees: 2.2 mm).
  --inner-brow UNITS  morphs 眉頭右 / 眉頭左 (KAZUSA's singing face keys 眉頭右, Sour's Rin has no such morph: its keys were
                      dropped): the brow's inner end raised by UNITS, falling linearly to nothing at its outer end (the
                      brow's vertices: those hanging most on 眉1..眉3 of the side; inner and outer ends the x of 眉1 and
                      眉4), along the model's own brow-raise direction (Sour's Rin's bone morph 上 moves 眉1 by
                      (0, 0.1992, -0.0419)).  Panel 眉, added to the display frame 表情.
  --joint-helpers J,..  a helper bone at each named joint of both sides that turns half way with the joint (an append of
                      the lower bone's turn x 0.5, like the model's own ひじ補助 x 0.6), and the joint's linear blend
                      shared out over it: a vertex with weight u on the upper side and l on the lower gives m = min(u, l)
                      from each (each bone of a side in proportion) to the helper (2 m).  The weighted mean of its turns is
                      kept (a 0.75 / 0.25 vertex becomes 0.5 upper / 0.5 helper: a quarter of the joint's turn either
                      way), but no two of its bones are more than half the joint's turn apart: linear blending of two
                      turns theta apart pulls the skin in to cos(theta / 2) of its girth (half and half), so a wrist
                      twisted 170 degrees keeps 0.09 of its girth at the band's middle and keeps all of it on the helper.
                      SDEF vertices are left alone (they blend on their own; their kind would change).  Joints:
                        wrist     右手首補助: on 右手捩, at 右手首, x 0.5 of 右手首; upper 右手捩 (and 右ひじ), lower 右手首
                                  (tools/fix_twist.py puts the forearm's twist past 45 degrees on 右手首: v10 up to 175)
                        shoulder  右腕補助: on 右肩, at 右腕, x 0.5 of 右腕W (the arm's swing without its twist, by its IK;
                                  右腕 for a model without 腕W); upper 右肩 and the trunk, lower 右腕W
                        hip       右足補助: on 腰キャンセル右 (足D's parent), at 右足D, x 0.5 of 右足D; upper 下半身, lower 右足D

The copy is for this work only and is not to be distributed (Sour's ReadMe allows editing; distribution would need the
ReadMe and an editor's ReadMe).
"""
import argparse
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit  # noqa: E402

KEYS = ("leg_ik_loops", "knee_least_bend", "inner_brow", "joint_helpers")
TRUNK = ("上半身", "腰椎上部", "上半身2", "胸椎上部", "首")
HELPERS = {     # joint: (helper, parent, at, append parent(s) tried in order, upper side, lower side, layer)
    "wrist": ("{s}手首補助", "{s}手捩", "{s}手首", ("{s}手首",), ("{s}手捩", "{s}ひじ"), ("{s}手首",), 0),
    "shoulder": ("{s}腕補助", "{s}肩", "{s}腕", ("{s}腕W", "{s}腕"), ("{s}肩",) + TRUNK, ("{s}腕W", "{s}腕"), 2),
    "hip": ("{s}足補助", "腰キャンセル{s}", "{s}足D", ("{s}足D",), ("下半身", "腰キャンセル{s}"), ("{s}足D",), 2),
}
HELPER_FLAGS = 0x0002 | 0x0100          # rotatable, an append of the turn; hidden and not to be keyed (like ひじ補助)
LEG_IKS = ("左足ＩＫ", "右足ＩＫ")
BROW_UP = (0.0, 0.1992, -0.0419)            # Sour's Rin's 上: the brow's raise, in the face's slope
PANEL_BROW = 1


def _check(recipe):
    unknown = set(recipe) - set(KEYS)
    if unknown:
        raise ValueError("unknown recipe keys: %s" % sorted(unknown))
    loops = recipe.get("leg_ik_loops")
    if loops is not None and not (isinstance(loops, int) and 1 <= loops <= 10000):
        raise ValueError("leg_ik_loops must be a whole number from 1 to 10000")
    bend = recipe.get("knee_least_bend")
    if bend is not None and not 0.0 <= bend <= 20.0:
        raise ValueError("knee_least_bend must lie between 0 and 20 degrees")
    brow = recipe.get("inner_brow")
    if brow is not None and not 0.0 < brow <= 0.5:
        raise ValueError("inner_brow must lie between 0 and 0.5 units")
    joints = recipe.get("joint_helpers")
    if joints is not None:
        unknown = [j for j in joints if j not in HELPERS]
        if unknown or len(set(joints)) != len(joints):
            raise ValueError("joint_helpers takes each of %s once, not %s" % (sorted(HELPERS), joints))


def _helpers(doc, joints):
    """the joint helper bones and the weights shared out over them (see the module docstring); returns their report"""
    names = {b.name: i for i, b in enumerate(doc.bones)}
    out = []
    for joint in joints:
        helper, parent, at, appends, upper, lower, layer = HELPERS[joint]
        for side, en in (("右", "R"), ("左", "L")):
            def n(t):
                return t.format(s=side)
            if n(helper) in names:
                raise ValueError("the model has a bone %s already" % n(helper))
            for need in (parent, at):
                if n(need) not in names:
                    raise ValueError("the model has no bone %s (the %s helper needs it)" % (n(need), joint))
            source = next((n(a) for a in appends if n(a) in names), None)
            if source is None:
                raise ValueError("the model has no bone to append the %s helper from: %s" % (joint, [n(a) for a in appends]))
            up = {names[n(b)] for b in upper if n(b) in names}
            lo = {names[n(b)] for b in lower if n(b) in names}
            rec = pmx_edit.BoneRec(n(helper), "%s_helper_%s" % (joint, en), tuple(doc.bones[names[n(at)]].position),
                                   names[n(parent)], layer, HELPER_FLAGS, append_parent=names[source], append_ratio=0.5)
            doc.bones.append(rec)
            hi = len(doc.bones) - 1
            names[n(helper)] = hi
            changed = skipped_sdef = 0
            moved = 0.0
            dropped = 0.0
            for v in doc.vertices:
                pairs = {}
                for b, w in v.pairs():
                    if w > 0.0:
                        pairs[b] = pairs.get(b, 0.0) + w
                u = sum(w for b, w in pairs.items() if b in up)
                l = sum(w for b, w in pairs.items() if b in lo)
                if u <= 1e-9 or l <= 1e-9:
                    continue
                if v.kind == "SDEF":
                    skipped_sdef += 1
                    continue
                m = min(u, l)
                new = {}
                for b, w in pairs.items():
                    if b in up:
                        w *= (u - m) / u
                    elif b in lo:
                        w *= (l - m) / l
                    if w > 1e-9:
                        new[b] = w
                new[hi] = new.get(hi, 0.0) + 2.0 * m
                items = sorted(new.items(), key=lambda bw: -bw[1])
                dropped = max(dropped, sum(w for _, w in items[4:]))
                v.set_weights(items)
                changed += 1
                moved += 2.0 * m
            out.append({"joint": joint, "bone": n(helper), "index": hi, "parent": n(parent), "append": source, "ratio": 0.5,
                        "layer": layer, "vertices": changed, "weight_moved": round(moved, 4), "sdef_left": skipped_sdef,
                        "largest_dropped": round(dropped, 6)})
    return out


def _morph_name(doc, m):
    r = pmx_edit._Reader(m.head, doc.encoding)
    return r.text()


def vertex_morph_offsets(doc, index):
    """{vertex: (dx, dy, dz)} of the vertex morph `index` of `doc`"""
    m = doc.morphs[index]
    if m.kind != 1:
        raise ValueError("morph %d is not a vertex morph" % index)
    size = doc.sizes["vertex"]
    fmt = "<" + {1: "B", 2: "H", 4: "i"}[size]
    out = {}
    for k in range(m.count):
        at = k * (size + 12)
        out[struct.unpack_from(fmt, m.body, at)[0]] = struct.unpack_from("<3f", m.body, at + size)
    return out


def _new_vertex_morph(doc, name, name_en, panel, offsets):
    size = doc.sizes["vertex"]
    fmt = "<" + {1: "B", 2: "H", 4: "i"}[size]
    head = pmx_edit._pack_text(name, doc.encoding) + pmx_edit._pack_text(name_en, doc.encoding) + bytes([panel, 1])
    body = b"".join(struct.pack(fmt, v) + struct.pack("<3f", *d) for v, d in sorted(offsets.items()))
    return pmx_edit.Morph(head, 1, len(offsets), body)


def _inner_brow(doc, units):
    """the morphs 眉頭右 / 眉頭左 (see the module docstring); returns their report"""
    names = [_morph_name(doc, m) for m in doc.morphs]
    for n in ("眉頭右", "眉頭左"):
        if n in names:
            raise ValueError("the model has a morph %s already" % n)
    up = BROW_UP
    norm = math.sqrt(sum(v * v for v in up))
    up = tuple(v / norm for v in up)
    out = []
    for side, en in (("右", "R"), ("左", "L")):
        try:
            bones = [doc.bone_index(side + "眉%d" % k) for k in (1, 2, 3)]
            inner = doc.bones[doc.bone_index(side + "眉1")].position[0]
            outer = doc.bones[doc.bone_index(side + "眉4")].position[0]
        except KeyError as exc:
            raise ValueError("the model has no brow bone %s" % exc) from None
        offsets = {}
        for vi, v in enumerate(doc.vertices):
            pairs = sorted(v.pairs(), key=lambda bw: -bw[1])
            if pairs[0][0] not in bones:
                continue
            x = struct.unpack_from("<f", v.head, 0)[0]
            s = (x - inner) / (outer - inner)
            f = 1.0 - min(1.0, max(0.0, s))
            if f > 1e-6:
                offsets[vi] = tuple(units * f * c for c in up)
        if not offsets:
            raise ValueError("no vertex hangs on the %s brow's bones" % side)
        doc.morphs.append(_new_vertex_morph(doc, "眉頭" + side, "inner_brow_up_" + en, PANEL_BROW, offsets))
        out.append({"name": "眉頭" + side, "index": len(doc.morphs) - 1, "vertices": len(offsets),
                    "largest": round(max(math.sqrt(sum(c * c for c in d)) for d in offsets.values()), 6)})
    frame = [f for f in doc.frames if pmx_edit._Reader(f.names, doc.encoding).text() == "表情"]
    if frame:
        for m in out:
            frame[0].items.append((1, m["index"]))
    return out


def apply(doc, recipe):
    """change `doc` (formats.pmx_edit Document) by `recipe` (a dict of KEYS); returns the report of every change"""
    _check(recipe)
    report = {"recipe": dict(recipe), "ik": [], "morphs": [], "helpers": []}
    if recipe.get("leg_ik_loops") is not None or recipe.get("knee_least_bend") is not None:
        for name in LEG_IKS:
            b = doc.bones[doc.bone_index(name)]
            if not b.flags & 0x0020 or not b.ik_links:
                raise ValueError("%s is not an IK bone with links" % name)
            old, new = {"loops": b.ik_loops}, {}
            if recipe.get("leg_ik_loops") is not None:
                b.ik_loops = recipe["leg_ik_loops"]
                new["loops"] = b.ik_loops
            if recipe.get("knee_least_bend") is not None:
                link, raw = b.ik_links[0]
                if raw is None:
                    raise ValueError("%s's first link has no limit" % name)
                lo, hi = list(struct.unpack("<3f", raw[:12])), list(struct.unpack("<3f", raw[12:]))
                if any(abs(v) > 1e-9 for v in lo[1:] + hi[1:]) or not lo[0] < hi[0]:
                    raise ValueError("%s's first link is not limited to a turn about X" % name)
                old["knee_deg"] = [round(math.degrees(lo[0]), 4), round(math.degrees(hi[0]), 4)]
                hi[0] = -math.radians(recipe["knee_least_bend"])
                if not lo[0] < hi[0]:
                    raise ValueError("the knee's limit would be empty")
                b.ik_links[0] = (link, struct.pack("<3f", *lo) + struct.pack("<3f", *hi))
                new["knee_deg"] = [round(math.degrees(lo[0]), 4), round(math.degrees(hi[0]), 4)]
            report["ik"].append({"bone": name, "old": old, "new": new})
    if recipe.get("inner_brow") is not None:
        report["morphs"] += _inner_brow(doc, recipe["inner_brow"])
    if recipe.get("joint_helpers"):
        report["helpers"] += _helpers(doc, recipe["joint_helpers"])
    return report


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


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", help="the model (.pmx), read only")
    ap.add_argument("out", help="the copy to write (.pmx): in a folder with the model's textures")
    ap.add_argument("--report", help="write every change to this JSON")
    ap.add_argument("--leg-ik-loops", type=int)
    ap.add_argument("--knee-least-bend", type=float)
    ap.add_argument("--inner-brow", type=float)
    ap.add_argument("--joint-helpers", type=lambda t: [x for x in t.split(",") if x])
    a = ap.parse_args(argv)
    recipe = {k: getattr(a, k) for k in KEYS if getattr(a, k) is not None}
    try:
        if _same(a.model, a.out) or (a.report and (_same(a.report, a.model) or _same(a.report, a.out))):
            raise ValueError("the outputs would overwrite the model or each other")
        doc = pmx_edit.load(a.model)
        report = apply(doc, recipe)
        report["model"] = os.path.abspath(a.model)
        _write(a.out, pmx_edit.dumps(doc))
        if a.report:
            _write(a.report, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "recipe": recipe}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
