"""Small humanoid PMX models for tests/test_retarget.py and tests/test_retarget_check.py: the bone chain the traced dance
moves (全ての親 .. 頭, the shoulders, arms and fingers, the legs with the leg and toe IK of Sour's Rin), at rest positions
given per body, and blobs of vertices (spheres on a bone) for the body's surfaces.  The right side mirrors the left."""
import math
import struct

from mmd_cli import fk
from mmd_cli.formats import vmd
from tests.test_pmx import APPEND_ROTATE, FIXED_AXIS, IK, NORMAL, TRANSLATE, Writer

KNEE_LIMITS = ((-math.pi, 0.0, 0.0), (0.0, 0.0, 0.0))

# the left side (and the middle) of Sour's Rin (White_spine_v6_eyes.pmx, rounded)
RIN = {
    "全ての親": (0.0, 0.0, 0.0), "センター": (0.0, 7.847, 0.0), "グルーブ": (0.0, 8.047, 0.0), "腰": (0.0, 11.726, 0.255),
    "下半身": (0.0, 12.225, -0.649), "上半身": (0.0, 12.225, -0.649), "上半身2": (0.0, 13.798, -0.678),
    "首": (0.0, 15.646, -0.134), "頭": (0.0, 16.243, 0.0), "頭先": (0.0, 18.766, -0.16),
    "肩": (0.23, 15.393, -0.222), "腕": (0.911, 15.277, -0.248), "ひじ": (2.907, 13.732, -0.27),
    "手首": (4.652, 12.41, -0.237), "中指１": (5.41, 11.935, -0.261), "中指２": (5.64, 11.73, -0.262),
    "中指３": (5.87, 11.538, -0.264),
    "足": (0.9012, 10.6579, 0.0073), "ひざ": (1.0032, 6.2313, -0.0361), "足首": (1.1205, 1.7452, 0.37),
    "つま先": (1.0463, 0.1, -1.15), "足先EX": (1.0794, 0.2877, -0.3235),
}
# a body like 初音ミクVer2.pmd (あにまさ式): the arms rest higher (29.7 degrees below level, Rin 37.7), the forearm bent
# 10 degrees down from the upper arm, longer legs and much longer feet
MIKU = {
    "全ての親": (0.0, 0.0, 0.0), "センター": (0.0, 8.0, 0.0), "グルーブ": (0.0, 8.2, 0.0), "腰": (0.0, 12.6, 0.0),
    "下半身": (0.0, 13.243, -0.255), "上半身": (0.0, 13.301, -0.255), "上半身2": (0.0, 14.55, -0.2),
    "首": (0.0, 16.418, 0.0), "頭": (0.0, 16.799, 0.0), "頭先": (0.0, 19.0, 0.0),
    "肩": (0.136, 16.13, 0.265), "腕": (0.891, 15.689, 0.318), "ひじ": (3.591, 14.148, 0.282),
    "手首": (5.27, 12.725, 0.272), "中指１": (6.147, 11.963, 0.23), "中指２": (6.45, 11.76, 0.226),
    "中指３": (6.736, 11.574, 0.221),
    "足": (0.797, 10.753, -0.073), "ひざ": (0.674, 5.927, -0.053), "足首": (0.875, 1.34, 0.0),
    "つま先": (0.929, 0.0, -2.464), "足先EX": (0.9, 0.3, -1.2),
}
# spheres of vertices for the body's surfaces: (bone, centre offset from the bone's rest, radius, points)
RIN_BLOBS = (("頭", (0.0, 1.43, -0.35), 1.35, 400), ("上半身2", (0.0, 0.6, -0.1), 1.0, 200), ("上半身", (0.0, 0.5, 0.0), 1.0, 200),
             ("下半身", (0.0, -1.2, 0.4), 1.3, 300))
MIKU_BLOBS = (("頭", (0.0, 1.47, 0.23), 1.6, 400), ("上半身2", (0.0, 0.6, 0.0), 1.0, 200), ("上半身", (0.0, 0.5, 0.0), 1.0, 200),
              ("下半身", (0.0, -1.2, 0.2), 1.2, 300))
# Rin's shoe: a box of vertices on 足首 from the heel (0.63 behind the ankle) to the toe tip (1.50 ahead), its sole at 0.111
RIN_SHOE = {"heel_back": 0.63, "toe_ahead": 1.50, "sole": 0.111, "top": 1.0, "half_width": 0.35}


def mid(a, b):
    return tuple(0.5 * (x + y) for x, y in zip(a, b))


def sphere(n):
    """n points spread over the unit sphere (a golden spiral)"""
    out = []
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        a = i * math.pi * (3.0 - math.sqrt(5.0))
        out.append((r * math.cos(a), y, r * math.sin(a)))
    return out


def humanoid_bytes(rest, blobs=(), twist_axis=False, name="humanoid", shoe=None, twists=True, extra=()):
    """a PMX of the humanoid with the rest positions `rest` (the left side; the right mirrors x), vertex `blobs` (each
    vertex's normal points out of its sphere), with `shoe` a box of shoe vertices on each 足首, and `extra` bones after
    the others: (name, parent, rest position, sided) — sided ones on both sides as 左name and 右name (the right mirrored),
    their parent a middle bone or the same side's"""
    w = Writer(bone=2, vertex=2)
    pos = {}
    for n, p in rest.items():
        pos[n] = p
    pos["腕捩"] = mid(rest["腕"], rest["ひじ"])
    pos["手捩"] = mid(rest["ひじ"], rest["手首"])
    pos["足IK親"] = (rest["足首"][0], rest["つま先"][1], rest["足首"][2])
    pos["足ＩＫ"] = rest["足首"]
    pos["つま先ＩＫ"] = rest["つま先"]
    rows = [("全ての親", None, "全ての親", NORMAL | TRANSLATE, {}), ("センター", "全ての親", "センター", NORMAL | TRANSLATE, {}),
            ("グルーブ", "センター", "グルーブ", NORMAL | TRANSLATE, {}), ("腰", "グルーブ", "腰", NORMAL, {}),
            ("上半身", "腰", "上半身", NORMAL, {}), ("上半身2", "上半身", "上半身2", NORMAL, {}),
            ("首", "上半身2", "首", NORMAL, {}), ("頭", "首", "頭", NORMAL, {}), ("頭先", "頭", "頭先", NORMAL, {}),
            ("下半身", "腰", "下半身", NORMAL, {})]
    for s in ("左", "右"):
        twist = NORMAL | (FIXED_AXIS if twist_axis else 0)
        if twists:
            arm = [(s + "腕捩", s + "腕", "腕捩", twist, {"axis": "腕"}), (s + "ひじ", s + "腕捩", "ひじ", NORMAL, {}),
                   (s + "手捩", s + "ひじ", "手捩", twist, {"axis": "ひじ"}), (s + "手首", s + "手捩", "手首", NORMAL, {})]
        else:
            arm = [(s + "ひじ", s + "腕", "ひじ", NORMAL, {}), (s + "手首", s + "ひじ", "手首", NORMAL, {})]
        rows += [(s + "肩", "上半身2", "肩", NORMAL, {}), (s + "腕", s + "肩", "腕", NORMAL, {})] + arm + [
                 (s + "中指１", s + "手首", "中指１", NORMAL, {}), (s + "中指２", s + "中指１", "中指２", NORMAL, {}),
                 (s + "中指３", s + "中指２", "中指３", NORMAL, {})]
        rows += [("腰キャンセル" + s, "下半身", "足", NORMAL | APPEND_ROTATE, {"append": ("腰", -1.0)}),
                 (s + "足", "腰キャンセル" + s, "足", NORMAL, {}), (s + "ひざ", s + "足", "ひざ", NORMAL, {}),
                 (s + "足首", s + "ひざ", "足首", NORMAL, {}), (s + "つま先", s + "足首", "つま先", NORMAL, {}),
                 (s + "足IK親", "全ての親", "足IK親", NORMAL | TRANSLATE, {}),
                 (s + "足ＩＫ", s + "足IK親", "足ＩＫ", NORMAL | TRANSLATE | IK,
                  {"layer": 1, "ik": (s + "足首", 40, 2.0, [(s + "ひざ", KNEE_LIMITS), (s + "足", None)])}),
                 (s + "つま先ＩＫ", s + "足ＩＫ", "つま先ＩＫ", NORMAL | TRANSLATE | IK,
                  {"layer": 2, "ik": (s + "つま先", 3, 4.0, [(s + "足首", None)])}),
                 (s + "足D", "腰キャンセル" + s, "足", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足", 1.0)}),
                 (s + "ひざD", s + "足D", "ひざ", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "ひざ", 1.0)}),
                 (s + "足首D", s + "ひざD", "足首", NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足首", 1.0)}),
                 (s + "足先EX", s + "足首D", "足先EX", NORMAL, {"layer": 2})]
    for key_, parent, p, sided in extra:
        pos[key_] = p
        names = [r[0] for r in rows]
        for side in (("左", "右") if sided else ("",)):
            rows.append((side + key_, parent if parent in names else side + parent, key_, NORMAL, {}))
    index = {r[0]: i for i, r in enumerate(rows)}

    def where(name, key):
        x, y, z = pos[key]
        right = name.startswith("右") or name.endswith("右")
        return (-x if right else x, y, z)
    built = []
    for name, parent, key, flags, kw in rows:
        args = {"parent": -1 if parent is None else index[parent], "position": where(name, key), "flags": flags,
                "layer": kw.get("layer", 0)}
        if "append" in kw:
            args["append"] = (index[kw["append"][0]], kw["append"][1])
        if "ik" in kw:
            target, loops, angle, links = kw["ik"]
            args["ik"] = {"target": index[target], "loops": loops, "angle": angle,
                          "links": [(index[l], lim) for l, lim in links]}
        if flags & FIXED_AXIS:
            a = where(name, kw["axis"])
            b = where(name, {"腕": "ひじ", "ひじ": "手首"}[kw["axis"]])
            d = [q - p for p, q in zip(a, b)]
            n = math.sqrt(sum(v * v for v in d))
            args["axis"] = tuple(v / n for v in d)
        built.append(w.bone(name, **args))
    verts = []
    for bone, offset, radius, n in blobs:
        for s in (("左", "右") if bone[0] in "左右" else ("",)):
            b = bone if not s else s + bone[1:]
            c = where(b, bone if not s else bone[1:])
            for p in sphere(n):
                raw = w.vertex("BDEF1", (index[b],))
                q = (c[0] + offset[0] + radius * p[0], c[1] + offset[1] + radius * p[1], c[2] + offset[2] + radius * p[2])
                verts.append(struct.pack("<3f", *q) + struct.pack("<3f", *p) + raw[24:])
    if shoe:
        for s in ("左", "右"):
            ax, ay, az = where(s + "足首", "足首")
            for i in range(12):
                for j in range(4):
                    for k in range(3):
                        z = az + shoe["heel_back"] - (shoe["heel_back"] + shoe["toe_ahead"]) * i / 11.0
                        y = shoe["sole"] + (shoe["top"] - shoe["sole"]) * j / 3.0
                        x = ax + shoe["half_width"] * (k - 1)
                        raw = w.vertex("BDEF1", (index[s + "足首"],))
                        verts.append(struct.pack("<3f", x, y, z) + struct.pack("<3f", 0.0, -1.0 if j == 0 else 0.0, 0.0) + raw[24:])
    return w.build(name=name, bones=built, vertices=verts)


def blob_centre(rest, blobs, bone):
    """(centre at rest, radius) of the blob on `bone` (a name without the side for the middle bones)"""
    for b, offset, radius, _ in blobs:
        if b == bone:
            base = rest[bone]
            return tuple(base[i] + offset[i] for i in range(3)), radius
    raise KeyError(bone)


def axis_angle(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


def key(name, frame, q=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0), curve=None):
    k = vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(float(v) for v in q)))
    if curve is not None:
        k.interpolation = vmd.bone_interpolation(curve)
    return k


def motion(*keys, morphs=()):
    return vmd.Motion(model_name="trace", bones=list(keys), morphs=list(morphs))
