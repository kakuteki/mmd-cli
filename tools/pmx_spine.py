"""Give a PMX model more spine: two bones inserted in the 上半身 - 上半身2 chain, and the trunk's vertex weights spread
over the four bones by height.

    python tools/pmx_spine.py MODEL.pmx OUT.pmx [--report r.json]

The chain becomes (Sour's Rin; the vertebral levels are estimates from the heights, the hip at y 10.6 and C7/T1 at the
neck, y 15.65, with the lumbar spine a third and the thoracic spine a little over a half of that span):

    上半身   (y 12.225, about L3)   the joints L2/3 .. L5/S1
    腰椎上部 (LUMBAR_Y, about T12/L1) T11/12, T12/L1, L1/2     new
    上半身2  (y 13.80, about T8/9)  T7/8 .. T10/11
    胸椎上部 (THORACIC_Y, about T4)  T1/2 .. T6/7            new: the chest; 首, 肩P and every other child of 上半身2
                                                              move onto it
    (the children of 上半身 between 腰椎上部 and 上半身2, the skirt's root ring at y 13.3, move onto 腰椎上部: left on
    上半身 the waistband tore between the skirt's and the trunk's weights, 47 faces turned over at a 40 degree bend)

Weights: on each vertex the part that sat on 上半身 and 上半身2 is shared out again over the four bones by the vertex's
height (smoothstep blends BLEND_HALF either side of each joint); the rest of its weights (下半身, 肩, 首, the skirt, the
legs, ...) stay, except that a vertex left with more than four bones keeps the four heaviest and is normalized again:
on Sour's Rin 300 vertices, the other bones' weights changing by at most 0.0038 (the review of 2026-10-13).  The vertices that also hang on the skirt, a leg or a physics bone are reweighted the same way (left on
the old split they would tear from their neighbours) and counted.  SDEF vertices whose trunk part changes become BDEF (their SDEF centre is for the old pair).  Rigid
bodies are left on their bones.  The model is changed for this work only and is not to be distributed (Sour's ReadMe
allows editing; distribution would need the ReadMe and an editor's ReadMe).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit  # noqa: E402

LOWER, UPPER, NECK = "上半身", "上半身2", "首"
LUMBAR, LUMBAR_EN = "腰椎上部", "spine_upper_lumbar"
THORACIC, THORACIC_EN = "胸椎上部", "spine_upper_thoracic"
LUMBAR_Y = 12.95
THORACIC_Y = 14.85
UPPER_Y = 13.798                # Sour's Rin's 上半身2 (height_shares' default; build reads the model's own)
BLEND_HALF = 0.35               # model units (about 2.8 cm) either side of a joint
SKIP_WORDS = ("スカート", "足")


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def height_shares(y, joints=(LUMBAR_Y, UPPER_Y, THORACIC_Y), half=BLEND_HALF):
    """the shares of 上半身, 腰椎上部, 上半身2, 胸椎上部 at the height y"""
    s = [smoothstep((y - (j - half)) / (2.0 * half)) for j in joints]
    return [1.0 - s[0], s[0] - s[1], s[1] - s[2], s[2]]


def _between(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + (b[0] - a[0]) * t, y, a[2] + (b[2] - a[2]) * t)


def build(doc, lumbar_y=LUMBAR_Y, thoracic_y=THORACIC_Y, half=BLEND_HALF):
    """insert the two bones into `doc` (formats.pmx_edit.Document) and spread the weights; returns a report"""
    lo, up, neck = doc.bone_index(LOWER), doc.bone_index(UPPER), doc.bone_index(NECK)
    B = doc.bones
    if B[up].parent != lo or B[neck].parent != up:
        raise ValueError("the model's chain is not 上半身 -> 上半身2 -> 首")
    p_lo, p_up, p_neck = B[lo].position, B[up].position, B[neck].position
    if not p_lo[1] < lumbar_y < p_up[1] < thoracic_y < p_neck[1]:
        raise ValueError("the joints' heights are not in order along the chain")
    flags = B[up].flags
    # 腰椎上部 just before 上半身2
    sl = pmx_edit.insert_bone(doc, up, pmx_edit.new_bone(LUMBAR, LUMBAR_EN, _between(p_lo, p_up, lumbar_y), parent=lo))
    up += 1
    neck += 1
    doc.bones[up].parent = sl
    # 胸椎上部 just after 上半身2; every child of 上半身2 moves onto it
    su = pmx_edit.insert_bone(doc, up + 1, pmx_edit.new_bone(THORACIC, THORACIC_EN, _between(p_up, p_neck, thoracic_y), parent=up))
    neck += 1
    moved = []
    for i, b in enumerate(doc.bones):
        if b.parent == up and i != su:
            b.parent = su
            moved.append(b.name)
    # the children of 上半身 within 腰椎上部's stretch (the skirt's root ring, y 13.3) follow 腰椎上部
    for i, b in enumerate(doc.bones):
        if b.parent == lo and i not in (sl, up) and lumbar_y <= b.position[1] < doc.bones[up].position[1]:
            b.parent = sl
            moved.append(b.name)
    for i, tail in ((lo, sl), (sl, up), (up, su), (su, neck)):
        b = doc.bones[i]
        b.flags = (b.flags | 0x0001) if i in (lo, up) else (flags | 0x0001)
        b.tail_bone = tail
    for f in doc.frames:
        items = []
        for k, i in f.items:
            items.append((k, i))
            if k == 0 and i == lo and (0, sl) not in f.items:
                items.append((0, sl))
            if k == 0 and i == up and (0, su) not in f.items:
                items.append((0, su))
        f.items = items
    # the weights
    physics = {rb.bone for rb in doc.rigid_bodies if rb.rest[60] != 0 and rb.bone >= 0}
    avoid = {i for i, b in enumerate(doc.bones) if i in physics or any(w in b.name for w in SKIP_WORDS)}
    chain = [lo, sl, up, su]
    joints = (lumbar_y, doc.bones[up].position[1], thoracic_y)
    reweighted = skipped = sdef = 0
    for v in doc.vertices:
        pairs = v.pairs()
        trunk = sum(w for b, w in pairs if b in (lo, up))
        if trunk <= 0.0:
            continue
        if any(b in avoid and w > 0.0 for b, w in pairs):
            skipped += 1                # counted: their skirt / leg part stays as it is
        rest = [(b, w) for b, w in pairs if b not in (lo, up)]
        shares = height_shares(v.position()[1], joints, half)
        new = rest + [(b, trunk * s) for b, s in zip(chain, shares) if s > 1e-6]
        sdef += v.kind == "SDEF"
        v.set_weights(new)
        reweighted += 1
    return {"inserted": {LUMBAR: sl, THORACIC: su}, "positions": {LUMBAR: doc.bones[sl].position,
                                                                   THORACIC: doc.bones[su].position},
            "moved_children": moved, "reweighted": reweighted, "with_skirt_or_leg": skipped, "sdef_to_bdef": sdef,
            "joints_y": joints, "blend_half": half}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    if os.path.abspath(a.model) == os.path.abspath(a.out):
        raise SystemExit("the output would overwrite the model")
    doc = pmx_edit.load(a.model)
    report = build(doc)
    pmx_edit.dump(doc, a.out)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text)
    print("inserted %s and %s; %d vertices reweighted, %d of them also on the skirt or a leg" % (LUMBAR, THORACIC, report["reweighted"], report["with_skirt_or_leg"]))


if __name__ == "__main__":
    main()
