"""Write a stage floor for MMD as a DirectX .x accessory (text): a dark plane and a grid of glowing lines.

    python tools/make_stage.py OUT.x [--half 60] [--step 5] [--line 0.06] [--accent-every 4]

MMD's own floor is the grid that comes with the coordinate axes (menu 215): the grid cannot be kept without
the red, green and blue axis lines.  This accessory is a floor of its own, loaded with `mmd accessory load
OUT.x` after `mmd menu set 215 off` (and `221 off`: the ground shadow is a light grey blot on a dark stage):

* a plane from -half to +half in x and z, a hair below the floor (y -0.02) so the lines do not flicker
  against it, nearly black and slightly transparent;
* a line every `step` units in both directions, a thin quad 2 * `line` wide at y 0; every
  `accent-every`-th one (counted from the centre) is twice as wide and amber, the others cool white.
  The colour of a material is in its emissive part alone and its diffuse part is black, so the floor
  looks the same whatever the light of the scene: MMD adds the lit diffuse to the emissive and clamps,
  which turned an amber in both parts into yellow (measured: 1.0, 0.63, 0.19 came out about 1.0, 1.0, 0.3).

Numbers are MMD units (a model is about 20 tall).  MMD shows an accessory at 10 times the numbers in its
file, so the file holds a tenth of them: measured on v9.32 (2026-10-04) by rendering this floor and MMD's
own 5 unit grid under the same camera, the lines fall on each other.  The half side of 60 leaves an edge
in sight under a wide shot, which reads as the edge of a stage.
"""
import argparse
import dataclasses
import json
import os
import sys
from typing import List, Tuple

FILE_UNITS_PER_MMD_UNIT = 0.1
PLANE_DEPTH = -0.02
# diffuse r g b a, power, specular r g b, emissive r g b
MATERIALS = (
    ((0.0, 0.0, 0.0, 0.92), 5.0, (0.0, 0.0, 0.0), (0.03, 0.045, 0.09)),         # 0 the plane: blue-black
    ((0.0, 0.0, 0.0, 0.55), 5.0, (0.0, 0.0, 0.0), (0.70, 0.82, 1.00)),          # 1 a line: cool white
    ((0.0, 0.0, 0.0, 0.80), 5.0, (0.0, 0.0, 0.0), (1.00, 0.63, 0.19)),          # 2 an accent line: amber
)


@dataclasses.dataclass
class Stage:
    vertices: List[Tuple[float, float, float]]
    faces: List[Tuple[int, int, int]]
    face_materials: List[int]


def _quad(stage, corners, material):
    base = len(stage.vertices)
    stage.vertices.extend(corners)
    stage.faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    stage.face_materials += [material, material]


def floor(half=60.0, step=5.0, line=0.06, accent_every=4):
    """the plane and the grid, in MMD units (see the module docstring)"""
    if not half > 0 or not step > 0 or not line > 0:
        raise ValueError("--half, --step and --line must be greater than 0")
    if step > half:
        raise ValueError("--step (%g) is larger than --half (%g): there would be one line" % (step, half))
    if accent_every < 0 or int(accent_every) != accent_every:
        raise ValueError("--accent-every is a whole number, 0 for no accent lines")
    stage = Stage([], [], [])
    _quad(stage, [(-half, PLANE_DEPTH, -half), (-half, PLANE_DEPTH, half), (half, PLANE_DEPTH, half), (half, PLANE_DEPTH, -half)], 0)
    n = int(half // step)
    for i in range(-n, n + 1):
        c = i * step
        accent = accent_every > 0 and i % int(accent_every) == 0
        w = line * (2.0 if accent else 1.0)
        material = 2 if accent else 1
        lo, hi = max(c - w, -half), min(c + w, half)                # the lines at the edge end with the plane
        _quad(stage, [(lo, 0.0, -half), (lo, 0.0, half), (hi, 0.0, half), (hi, 0.0, -half)], material)
        _quad(stage, [(-half, 0.0, lo), (-half, 0.0, hi), (half, 0.0, hi), (half, 0.0, lo)], material)
    return stage


def x_text(stage, name="stage_floor"):
    """the DirectX text of the mesh (ASCII, CRLF), with every normal pointing up"""
    k = FILE_UNITS_PER_MMD_UNIT
    out = ["xof 0303txt 0032", "", "Mesh %s {" % name, " %d;" % len(stage.vertices)]
    out.append(",\r\n".join(" %.4f;%.4f;%.4f;" % (x * k + 0.0, y * k + 0.0, z * k + 0.0) for x, y, z in stage.vertices) + ";")
    out.append(" %d;" % len(stage.faces))
    out.append(",\r\n".join(" 3;%d,%d,%d;" % f for f in stage.faces) + ";")
    out += ["", " MeshMaterialList {", "  %d;" % len(MATERIALS), "  %d;" % len(stage.face_materials)]
    out.append(",\r\n".join("  %d" % m for m in stage.face_materials) + ";")
    for (r, g, b, a), power, specular, emissive in MATERIALS:
        out += ["  Material {", "   %.4f;%.4f;%.4f;%.4f;;" % (r, g, b, a), "   %.4f;" % power,
                "   %.4f;%.4f;%.4f;;" % specular, "   %.4f;%.4f;%.4f;;" % emissive, "  }"]
    out += [" }", " MeshNormals {", "  1;", "  0.0000;1.0000;0.0000;;", "  %d;" % len(stage.faces)]
    out.append(",\r\n".join("  3;0,0,0;" for _ in stage.faces) + ";")
    out += [" }", "}", ""]
    return "\r\n".join(out)


def write_bytes(path, data):
    """write next to the target and move over it, so a failure leaves the old file as it was"""
    if os.path.isdir(path):
        raise ValueError("%s is a folder" % path)
    folder = os.path.dirname(path)
    if folder:
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
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("out", help="the accessory to write (.x)")
    p.add_argument("--half", type=float, default=60.0, help="half the side of the floor, in MMD units (default 60)")
    p.add_argument("--step", type=float, default=5.0, help="between two lines (default 5, MMD's own grid)")
    p.add_argument("--line", type=float, default=0.06, help="half the width of a line (default 0.06)")
    p.add_argument("--accent-every", type=int, default=4, help="every N-th line is amber and wider; 0 for none (default 4)")
    args = p.parse_args(argv)
    try:
        stage = floor(args.half, args.step, args.line, args.accent_every)
        out = os.path.abspath(args.out)
        write_bytes(out, x_text(stage).encode("ascii"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": True, "out": out, "vertices": len(stage.vertices), "faces": len(stage.faces),
                      "half": args.half, "step": args.step, "line": args.line, "accent_every": args.accent_every},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
