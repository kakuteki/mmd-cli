"""Change the physics of a PMX model's skirt in a copy of the model: the skirt's rigid bodies (masses, damping), the joints
that hang them (rotation limits, rotation springs) and the ring joints between neighbours (rotation and translation
limits).  Everything else is kept byte for byte (formats.pmx_edit).

    python tools/pmx_skirt.py MODEL.pmx OUT.pmx [--report r.json] [--limit-scale S] [--reach DEG] [--spring-scale K]
                              [--ring-rotate DEG] [--ring-move-scale S] [--mass M0 .. Mn | --mass-area M]
                              [--damping LINEAR ANGULAR] [--ceiling DEG [--ceiling-anchor]]

The skirt (Sour's Rin: 7 rows x 16 columns): rigid bodies named スカート_row_col, each hung from the body above it (row
0: from the trunk) by the joint of the same name, and joined to the next column by スカート横_row_col.  Bones named
スカート_row_col sit on the joints (one more row of bones than bodies: the hem's tips).

Recipe (each optional):
  --limit-scale S     every hanging joint's rotation limits (all three axes, both sides) times S
  --reach DEG         per column, the hanging joints' X limits (the axis that turns a body in or out) times one factor
                      so that no body could tilt more than DEG from straight down with every joint above it at its X
                      limit: rest tilt (from the bones) + the X limits added up from the waist.  Never widens.
  --spring-scale K    the hanging joints' rotation springs times K
  --ring-rotate DEG   the ring joints' rotation limits set to -DEG .. +DEG on all three axes
  --ring-move-scale S the ring joints' translation limits times S
  --mass M0 .. Mn     the skirt bodies' masses by row
  --mass-area M       every skirt body's mass in proportion to the area of its box's broad face (the fabric it stands
                      for), M for the mean face of the top row
  --damping LIN ANG   the skirt bodies' linear and angular damping
  --ceiling DEG       a joint per skirt body from the trunk (the body the column's top joint hangs from) on the body's
                      lower end, free but for a ceiling in the trunk's frame: the column's waist point less cos(DEG) times
                      the chain's rest length down to that point (a straight column could tilt to DEG and no further)

The copy is for this work only and is not to be distributed (Sour's ReadMe allows editing; distribution would need the
ReadMe and an editor's ReadMe).
"""
import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli.formats import pmx_edit  # noqa: E402

NAME = re.compile(r"^スカート_(\d+)_(\d+)$")
RING = re.compile(r"^スカート横_(\d+)_(\d+)$")
CEILING = "スカート天井_%d_%d"
KEYS = ("limit_scale", "reach", "spring_scale", "ring_rotate", "ring_move_scale", "mass", "mass_area", "damping", "ceiling",
        "ceiling_anchor")
ANCHOR = "スカート天井台"
FREE = 100.0                    # a translation range never reached (model units)


@dataclass
class Skirt:
    rows: int                                   # rows of rigid bodies
    cols: int
    bodies: dict = field(default_factory=dict)      # (row, col) -> rigid body index
    vertical: dict = field(default_factory=dict)    # (row, col) -> index of the joint that hangs the body
    ring: dict = field(default_factory=dict)        # (row, col) -> index of the joint to the next column
    rest_tilt: dict = field(default_factory=dict)   # (row, col) -> degrees from straight down, from the bones


def _grid(names, pattern):
    out = {}
    for i, n in enumerate(names):
        m = pattern.match(n)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = i
    return out


def _full(grid, what):
    if not grid:
        raise ValueError("the model has no %s" % what)
    rows, cols = max(r for r, _ in grid) + 1, max(c for _, c in grid) + 1
    missing = [(r, c) for r in range(rows) for c in range(cols) if (r, c) not in grid]
    if missing:
        raise ValueError("the %s do not fill %d rows x %d columns: missing %s" % (what, rows, cols, missing[:5]))
    return rows, cols


def find_skirt(doc):
    """the skirt's bodies, hanging joints, ring joints and rest tilts; ValueError unless they form a full grid"""
    bodies = _grid([pmx_edit.rigid_names(doc, rb)[0] for rb in doc.rigid_bodies], NAME)
    rows, cols = _full(bodies, "rigid bodies named スカート_row_col")
    js = pmx_edit.joints(doc)
    vertical = {k: v for k, v in _grid([j.name for j in js], NAME).items() if k in bodies}
    if len(vertical) != len(bodies):
        missing = sorted(set(bodies) - set(vertical))
        raise ValueError("skirt bodies without a hanging joint of the same name: %s" % missing[:5])
    for (r, c), j in vertical.items():
        if js[j].b != bodies[(r, c)]:
            raise ValueError("joint %s does not hang the body of its name" % js[j].name)
    ring = _grid([j.name for j in js], RING)
    if ring:
        _full(ring, "ring joints named スカート横_row_col")
    bones = _grid([b.name for b in doc.bones], NAME)
    tilt = {}
    for (r, c) in bodies:
        if (r, c) not in bones or (r + 1, c) not in bones:
            raise ValueError("skirt body %d_%d has no bones at both ends" % (r, c))
        a, b = doc.bones[bones[(r, c)]].position, doc.bones[bones[(r + 1, c)]].position
        d = [b[k] - a[k] for k in range(3)]
        n = math.sqrt(sum(v * v for v in d))
        tilt[(r, c)] = math.degrees(math.acos(max(-1.0, min(1.0, -d[1] / n))))
    return Skirt(rows, cols, bodies, vertical, ring, tilt)


def reach(skirt, js, col):
    """the most a body of the column could tilt from straight down: its rest tilt + the X limits from the waist down"""
    best, total = 0.0, 0.0
    for r in range(skirt.rows):
        total += math.degrees(js[skirt.vertical[(r, col)]].rotate_upper[0])
        best = max(best, skirt.rest_tilt[(r, col)] + total)
    return best


def _check(recipe, skirt):
    unknown = set(recipe) - set(KEYS)
    if unknown:
        raise ValueError("unknown recipe keys: %s" % sorted(unknown))
    for key in ("limit_scale", "spring_scale", "ring_move_scale"):
        if recipe.get(key) is not None and not recipe[key] >= 0.0:
            raise ValueError("%s must be 0 or more" % key)
    if recipe.get("reach") is not None and not 0.0 < recipe["reach"] < 180.0:
        raise ValueError("reach must lie between 0 and 180 degrees")
    if recipe.get("ring_rotate") is not None and not 0.0 <= recipe["ring_rotate"] <= 180.0:
        raise ValueError("ring_rotate must lie between 0 and 180 degrees")
    if recipe.get("mass") is not None and (len(recipe["mass"]) != skirt.rows or min(recipe["mass"]) <= 0.0):
        raise ValueError("mass needs %d positive values, one per row" % skirt.rows)
    if recipe.get("mass_area") is not None:
        if not recipe["mass_area"] > 0.0:
            raise ValueError("mass_area must be positive")
        if recipe.get("mass") is not None:
            raise ValueError("give mass or mass_area, not both")
    if recipe.get("ceiling") is not None and not 0.0 < recipe["ceiling"] < 90.0:
        raise ValueError("ceiling must lie between 0 and 90 degrees")
    if recipe.get("ceiling_anchor") and recipe.get("ceiling") is None:
        raise ValueError("ceiling_anchor needs a ceiling")
    if recipe.get("damping") is not None and (len(recipe["damping"]) != 2 or not all(0.0 <= d <= 1.0 for d in recipe["damping"])):
        raise ValueError("damping needs two values (linear, angular) between 0 and 1")
    if (recipe.get("ring_rotate") is not None or recipe.get("ring_move_scale") is not None) and not skirt.ring:
        raise ValueError("the model's skirt has no ring joints")


def _r(v):
    if isinstance(v, (tuple, list)):
        return [round(float(x), 6) for x in v]
    return round(float(v), 6)


def apply(doc, recipe):
    """change `doc`'s skirt by `recipe` (a dict of KEYS); returns the report: every changed field old -> new, and every
    column's reach before and after"""
    s = find_skirt(doc)
    _check(recipe, s)
    js = pmx_edit.joints(doc)
    changes = []
    before = {str(c): round(reach(s, js, c), 4) for c in range(s.cols)}

    def joint(j, name, value):
        old = getattr(j, name)
        if tuple(old) != tuple(value):
            changes.append({"kind": "joint", "name": j.name, "field": name, "old": _r(old), "new": _r(value)})
            setattr(j, name, tuple(value))

    for (r, c), i in sorted(s.vertical.items()):
        j = js[i]
        if recipe.get("limit_scale") is not None:
            k = recipe["limit_scale"]
            joint(j, "rotate_lower", [v * k for v in j.rotate_lower])
            joint(j, "rotate_upper", [v * k for v in j.rotate_upper])
        if recipe.get("spring_scale") is not None:
            joint(j, "spring_rotate", [v * recipe["spring_scale"] for v in j.spring_rotate])
    if recipe.get("reach") is not None:
        for c in range(s.cols):
            factor, total = 1.0, 0.0
            for r in range(s.rows):
                total += math.degrees(js[s.vertical[(r, c)]].rotate_upper[0])
                if total > 0.0:
                    factor = min(factor, max(0.0, (recipe["reach"] - s.rest_tilt[(r, c)]) / total))
            if factor < 1.0:
                for r in range(s.rows):
                    j = js[s.vertical[(r, c)]]
                    joint(j, "rotate_lower", [j.rotate_lower[0] * factor, j.rotate_lower[1], j.rotate_lower[2]])
                    joint(j, "rotate_upper", [j.rotate_upper[0] * factor, j.rotate_upper[1], j.rotate_upper[2]])
    for (r, c), i in sorted(s.ring.items()):
        j = js[i]
        if recipe.get("ring_rotate") is not None:
            a = math.radians(recipe["ring_rotate"])
            joint(j, "rotate_lower", [-a, -a, -a])
            joint(j, "rotate_upper", [a, a, a])
        if recipe.get("ring_move_scale") is not None:
            k = recipe["ring_move_scale"]
            joint(j, "move_lower", [v * k for v in j.move_lower])
            joint(j, "move_upper", [v * k for v in j.move_upper])
    added = []
    if recipe.get("ceiling") is not None:
        added = _ceilings(doc, s, js, recipe["ceiling"], bool(recipe.get("ceiling_anchor")))
    if changes or added:
        pmx_edit.set_joints(doc, js)
    areas = {}
    if recipe.get("mass_area") is not None:
        for k, i in s.bodies.items():
            half = sorted(pmx_edit.rigid_body(doc.rigid_bodies[i]).size)[-2:]
            areas[k] = 4.0 * half[0] * half[1]
        top = sum(areas[(0, c)] for c in range(s.cols)) / s.cols
    for (r, c), i in sorted(s.bodies.items()):
        rb = doc.rigid_bodies[i]
        body = pmx_edit.rigid_body(rb)
        name = pmx_edit.rigid_names(doc, rb)[0]
        new = {}
        if recipe.get("mass") is not None:
            new["mass"] = recipe["mass"][r]
        if areas:
            new["mass"] = recipe["mass_area"] * areas[(r, c)] / top
        if recipe.get("damping") is not None:
            new["linear_damping"], new["angular_damping"] = recipe["damping"]
        changed = False
        for key, value in new.items():
            if getattr(body, key) != value:
                changes.append({"kind": "rigid", "name": name, "field": key, "old": _r(getattr(body, key)), "new": _r(value)})
                setattr(body, key, value)
                changed = True
        if changed:
            pmx_edit.set_rigid_body(rb, body)
    after = {str(c): round(reach(s, pmx_edit.joints(doc), c), 4) for c in range(s.cols)}
    return {"rows": s.rows, "cols": s.cols, "recipe": dict(recipe), "changes": changes, "added": added,
            "reach_before": before, "reach_after": after,
            "rest_tilt": {"%d_%d" % k: round(v, 3) for k, v in sorted(s.rest_tilt.items())}}


def _anchor(doc, trunks):
    """append the rigid body the ceilings hang from: on the trunk body's bone, where the trunk body is, following the bone
    (mode 0), in group 15 colliding with no group; returns its index"""
    if len(trunks) != 1:
        raise ValueError("the skirt's columns hang from %d trunk bodies, the anchor needs one" % len(trunks))
    t = doc.rigid_bodies[trunks.pop()]
    if any(pmx_edit.rigid_names(doc, rb)[0] == ANCHOR for rb in doc.rigid_bodies):
        raise ValueError("the model has a %s already" % ANCHOR)
    tb = pmx_edit.rigid_body(t)
    body = pmx_edit.RigidBody(15, 0x0000, 0, (0.05, 0.0, 0.0), tb.position, tb.rotation, tb.mass, tb.linear_damping,
                              tb.angular_damping, 0.0, 0.0, 0)
    doc.rigid_bodies.append(pmx_edit.new_rigid(doc, ANCHOR, "skirt_ceiling_anchor", t.bone, body))
    return len(doc.rigid_bodies) - 1


def _ceilings(doc, s, js, degrees, anchor=False):
    """append to js, per skirt body, a joint from the trunk body (the one the column's top joint hangs from) to the body,
    on the body's lower end, that lets that point move freely except upwards past a ceiling in the trunk's frame: the
    column's waist point (bone 0) less cos(degrees) times the rest length of the chain down to the point, so a straight
    column could tilt up to `degrees` from straight down and no further.  Turning is free (lower > upper)."""
    if any(j.name.startswith("スカート天井_") for j in js):
        raise ValueError("the model has skirt ceiling joints already")
    bones = {}
    for b in doc.bones:
        m = NAME.match(b.name)
        if m:
            bones[(int(m.group(1)), int(m.group(2)))] = b.position
    k = math.cos(math.radians(degrees))
    added = []
    base = _anchor(doc, {js[s.vertical[(0, c)]].a for c in range(s.cols)}) if anchor else None
    for c in range(s.cols):
        trunk = js[s.vertical[(0, c)]].a if base is None else base
        ring_y = bones[(0, c)][1]
        chain = 0.0
        for r in range(s.rows):
            a, p = bones[(r, c)], bones[(r + 1, c)]
            chain += math.dist(a, p)
            offset = ring_y - k * chain - p[1]
            if offset <= 0.0:
                raise ValueError("the lower end of skirt body %d_%d rests above its ceiling" % (r, c))
            name = CEILING % (r, c)
            js.append(pmx_edit.Joint(name, "skirt_ceiling_%d_%d" % (r, c), 0, trunk, s.bodies[(r, c)], tuple(p), (0.0, 0.0, 0.0),
                                     (-FREE, -FREE, -FREE), (FREE, offset, FREE), (1.0, 1.0, 1.0), (-1.0, -1.0, -1.0),
                                     (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            added.append({"name": name, "trunk": trunk, "body": s.bodies[(r, c)], "point": _r(p), "rise": round(offset, 6)})
    return added


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
    ap.add_argument("--report", help="write every change and the columns' reach to this JSON")
    ap.add_argument("--limit-scale", type=float)
    ap.add_argument("--reach", type=float)
    ap.add_argument("--spring-scale", type=float)
    ap.add_argument("--ring-rotate", type=float)
    ap.add_argument("--ring-move-scale", type=float)
    ap.add_argument("--mass", type=float, nargs="+")
    ap.add_argument("--mass-area", type=float)
    ap.add_argument("--damping", type=float, nargs=2)
    ap.add_argument("--ceiling", type=float)
    ap.add_argument("--ceiling-anchor", action="store_true")
    a = ap.parse_args(argv)
    recipe = {k: getattr(a, k) for k in KEYS if getattr(a, k) not in (None, False)}
    try:
        if _same(a.model, a.out) or (a.report and (_same(a.report, a.model) or _same(a.report, a.out))):
            raise ValueError("the outputs would overwrite the model or each other")
        doc = pmx_edit.load(a.model)
        report = apply(doc, recipe)
        report["model"] = os.path.abspath(a.model)
        _write(a.out, pmx_edit.dumps(doc))
        if a.report:
            _write(a.report, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "recipe": recipe, "changes": len(report["changes"]),
                      "reach_after_max": max(report["reach_after"].values())}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
