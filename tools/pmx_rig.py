"""Change the rig of a PMX model in a copy: the leg IK's loops, and (as the recipe grows) twist bones with their weights,
morphs and physics.  Everything the recipe does not name is kept byte for byte (formats.pmx_edit).

    python tools/pmx_rig.py MODEL.pmx OUT.pmx [--report r.json] [--leg-ik-loops N]

Recipe:
  --leg-ik-loops N    the loops of the leg IKs (足ＩＫ, both sides).  MMD's leg IK is a CCD that keeps a loop only when it
                      brings the ankle closer and stops at the first that does not; near a straight leg it gains little a
                      loop, so 40 loops (Sour's Rin, most models) leave the ankle short of a goal the leg could reach
                      (v10: 4 mm or more on 228 + 439 frames, up to 1.3 cm, tools/rig_check.py ik).  More loops let it
                      get there; a frame that converges sooner stops sooner, so they cost only where they help.

The copy is for this work only and is not to be distributed (Sour's ReadMe allows editing; distribution would need the
ReadMe and an editor's ReadMe).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit  # noqa: E402

KEYS = ("leg_ik_loops",)
LEG_IKS = ("左足ＩＫ", "右足ＩＫ")


def _check(recipe):
    unknown = set(recipe) - set(KEYS)
    if unknown:
        raise ValueError("unknown recipe keys: %s" % sorted(unknown))
    loops = recipe.get("leg_ik_loops")
    if loops is not None and not (isinstance(loops, int) and 1 <= loops <= 10000):
        raise ValueError("leg_ik_loops must be a whole number from 1 to 10000")


def apply(doc, recipe):
    """change `doc` (formats.pmx_edit Document) by `recipe` (a dict of KEYS); returns the report of every change"""
    _check(recipe)
    report = {"recipe": dict(recipe), "ik": []}
    if recipe.get("leg_ik_loops") is not None:
        for name in LEG_IKS:
            b = doc.bones[doc.bone_index(name)]
            if not b.flags & 0x0020:
                raise ValueError("%s is not an IK bone" % name)
            report["ik"].append({"bone": name, "old": {"loops": b.ik_loops}, "new": {"loops": recipe["leg_ik_loops"]}})
            b.ik_loops = recipe["leg_ik_loops"]
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
