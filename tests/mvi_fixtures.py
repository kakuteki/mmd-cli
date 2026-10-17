"""Synthetic inputs for the tests of tools/mv_inspect.py and its parts (tools/mvi/): a pack (the 26 bones of the analysis
pack) of a body at Sour's Rin's rest swaying its upper body, with the moves a test asks for; a stand-in of a measured
version (shared.Measured) whose engines give what a test sets; a still front camera VMD."""
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from mvi import a05 as A05, base, body, fq as FQ, hb as HB  # noqa: E402

from mmd_cli.formats import vmd  # noqa: E402

# Sour's Rin at rest (model units; tests/test_balance_layer.py's rin-like model, a05's REST)
REST = {"全ての親": (0.0, 0.1, 0.0), "センター": (0.0, 7.8468, 0.0), "グルーブ": (0.0, 8.0468, 0.0), "腰": (0.0, 11.7255, 0.2554),
        "下半身": (0.0, 12.2248, -0.6493), "上半身": (0.0, 12.2248, -0.6493), "上半身2": (0.0, 13.7985, -0.6784),
        "首": (0.0, 15.6456, -0.1343), "頭": (0.0, 16.2431, 0.0), "両目": (0.0, 17.2143, -0.562),
        "左目": (0.4101, 17.2143, -0.562), "右目": (-0.4101, 17.2143, -0.562)}
for _s, _x in (("左", 1.0), ("右", -1.0)):
    REST.update({_s + "肩": (_x * 0.2296, 15.3934, -0.222), _s + "腕": (_x * 0.9114, 15.2768, -0.2484),
                 _s + "ひじ": (_x * 2.9071, 13.7325, -0.27), _s + "手首": (_x * 4.6524, 12.4104, -0.2368),
                 _s + "中指３": (_x * 5.8701, 11.5382, -0.2637), _s + "足ＩＫ": (_x * 1.120466947555542, 1.7452340126037598, 0.3699590861797333),
                 _s + "つま先ＩＫ": (_x * 1.0462599992752075, 0.10000000149011612, -1.1500359773635864)})
UPPER = ("上半身", "上半身2", "首", "頭", "両目", "左目", "右目", "左肩", "右肩", "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首",
         "左中指３", "右中指３")
NAMES = body.PACK_BONES


def pack(F, move=None, sway=0.25, hz=1.0):
    """(names, pos [F, 26, 3], rot [F, 26, 4]) float32: every bone at rest, the upper body swaying sideways by `sway`
    units at `hz` (so that the dance range covers the frames), and move(name, t, p) -> the bone's place at frame t (p: its
    place so far) for what a test changes"""
    pos = np.zeros((F, len(NAMES), 3))
    rot = np.zeros((F, len(NAMES), 4))
    rot[..., 3] = 1.0
    t = np.arange(F)
    for i, n in enumerate(NAMES):
        pos[:, i] = REST[n]
        if n in UPPER:
            pos[:, i, 0] += sway * np.sin(2.0 * math.pi * hz * t / 30.0)
    if move is not None:
        for i, n in enumerate(NAMES):
            for f in range(F):
                p = move(n, f, pos[f, i].copy())
                if p is not None:
                    pos[f, i] = p
    return list(NAMES), pos.astype(np.float32), rot.astype(np.float32)


def rin_rest():
    rest = {k: np.array(v, dtype=np.float64) for k, v in A05.RIN_REST.items()}
    return rest, A05.RIN_REST["左足首"][1], A05.RIN_REST["左つま先"][1]


class FakeVersion:
    def __init__(self, names, pos, rot, spec=None, extra=None, merged=None):
        self._pack = (names, pos, rot)
        self._extra = extra or {}
        self.spec = dict(spec or {})
        self.label = self.spec.get("label", "fake")
        self.frames = len(pos)
        self.first, self.last = 0, len(pos) - 1
        self.merged = merged
        self.reference = None

    def pack(self):
        return self._pack

    def bone(self, name):
        names, pos, rot = self._pack
        if name in names:
            i = names.index(name)
            return pos[:, i], rot[:, i]
        if name in self._extra:
            return self._extra[name]
        raise ValueError(name)


class FakeMeasured:
    """shared.Measured's face: hb, a05 and fq run on the fake pack (a05 with the rest given, Rin's by default); wb, shoes
    and vertical give what the test set; scaled(s) is shared.Scaled on it"""

    def __init__(self, version, wb=None, shoes=None, ref_shoes=None, vertical=None, rest=None):
        self.v = version
        self._wb, self._shoes, self._ref_shoes, self._vertical = wb, shoes, ref_shoes, vertical
        self._rest = rest
        self._c = {}

    def rest(self):
        return self._rest if self._rest is not None else rin_rest()

    def scaled(self, s):
        from mvi import shared
        return shared.Scaled(self, s)

    def hb(self):
        if "hb" not in self._c:
            self._c["hb"] = HB.measure(*self.v.pack())
        return self._c["hb"]

    def a05(self):
        if "a05" not in self._c:
            names, pos, rot = self.v.pack()
            self._c["a05"] = A05.run(names, pos, rot, rest=self.rest())
        return self._c["a05"]

    def fq(self):
        if "fq" not in self._c:
            _, pos, _ = self.v.pack()
            p64 = pos.astype(np.float64)
            rng = FQ.dance_range_fq(p64)
            r = FQ.measure(p64, *rng, events=True)
            r["range"] = list(rng)
            self._c["fq"] = r
        return self._c["fq"]

    def wb(self):
        return self._wb

    def shoes(self, which="dance"):
        return self._shoes if which == "dance" else self._ref_shoes

    def vertical(self):
        return self._vertical


def full_body_bytes():
    """a model with Sour's Rin's rest skeleton for every part: the body chain and the upper body with the eyes, the arms
    with their twist bones and the middle finger, and the leg rig of tests.test_leg_ik (the leg IK, the toe IK, the D
    bones, 足先EX) with a shoe (the sole, the upper and the toe cap of tests.test_foot_layer) on each foot"""
    import struct
    from tests.test_foot_layer import CAP, SOLE, UPPER as SHOE_UPPER
    from tests.test_leg_ik import KNEE_LIMITS, REST as LEG_REST
    from tests.test_pmx import IK, NORMAL, TRANSLATE, APPEND_ROTATE, Writer
    w = Writer(bone=2, vertex=2)
    up = {"上半身": (0.0, 12.2248, -0.6493), "上半身2": (0.0, 13.7985, -0.6784), "首": (0.0, 15.6456, -0.1343),
          "頭": (0.0, 16.2431, 0.0), "頭先": (0.0, 18.7663, -0.1601), "両目": (0.0, 17.2143, -0.562),
          "左目": (0.4101, 17.2143, -0.562), "右目": (-0.4101, 17.2143, -0.562)}
    rows = [("全ての親", None, LEG_REST["全ての親"], NORMAL | TRANSLATE, {}), ("センター", "全ての親", LEG_REST["センター"], NORMAL | TRANSLATE, {}),
            ("グルーブ", "センター", LEG_REST["グルーブ"], NORMAL | TRANSLATE, {}), ("腰", "グルーブ", LEG_REST["腰"], NORMAL, {}),
            ("下半身", "腰", LEG_REST["下半身"], NORMAL, {}), ("上半身", "腰", up["上半身"], NORMAL, {}),
            ("上半身2", "上半身", up["上半身2"], NORMAL, {}), ("首", "上半身2", up["首"], NORMAL, {}), ("頭", "首", up["頭"], NORMAL, {}),
            ("頭先", "頭", up["頭先"], NORMAL, {}), ("両目", "頭", up["両目"], NORMAL, {}), ("左目", "頭", up["左目"], NORMAL, {}),
            ("右目", "頭", up["右目"], NORMAL, {})]
    for s, sx in (("左", 1.0), ("右", -1.0)):
        sh, arm, el, wr, mid = (REST[s + n] for n in ("肩", "腕", "ひじ", "手首", "中指３"))
        tw1 = tuple(0.5 * (a + b) for a, b in zip(arm, el))
        tw2 = tuple(0.5 * (a + b) for a, b in zip(el, wr))
        rows += [(s + "肩", "上半身2", sh, NORMAL, {}), (s + "腕", s + "肩", arm, NORMAL, {}), (s + "腕捩", s + "腕", tw1, NORMAL, {}),
                 (s + "ひじ", s + "腕捩", el, NORMAL, {}), (s + "手捩", s + "ひじ", tw2, NORMAL, {}), (s + "手首", s + "手捩", wr, NORMAL, {}),
                 (s + "中指３", s + "手首", mid, NORMAL, {})]
        leg = lambda n: (sx * LEG_REST[n][0], LEG_REST[n][1], LEG_REST[n][2])      # noqa: E731
        rows += [("腰キャンセル" + s, "下半身", leg("腰キャンセル"), NORMAL | APPEND_ROTATE, {"append": ("腰", -1.0)}),
                 (s + "足", "腰キャンセル" + s, leg("足"), NORMAL, {}), (s + "ひざ", s + "足", leg("ひざ"), NORMAL, {}),
                 (s + "足首", s + "ひざ", leg("足首"), NORMAL, {}), (s + "つま先", s + "足首", leg("つま先"), NORMAL, {}),
                 (s + "足IK親", "全ての親", leg("足IK親"), NORMAL | TRANSLATE, {}),
                 (s + "足ＩＫ", s + "足IK親", leg("足ＩＫ"), NORMAL | TRANSLATE | IK,
                  {"layer": 1, "ik": (s + "足首", 40, 2.0, [(s + "ひざ", KNEE_LIMITS), (s + "足", None)])}),
                 (s + "つま先ＩＫ", s + "足ＩＫ", leg("つま先ＩＫ"), NORMAL | TRANSLATE | IK,
                  {"layer": 2, "ik": (s + "つま先", 3, 4.0, [(s + "足首", None)])}),
                 (s + "足D", "腰キャンセル" + s, leg("足"), NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足", 1.0)}),
                 (s + "ひざD", s + "足D", leg("ひざ"), NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "ひざ", 1.0)}),
                 (s + "足首D", s + "ひざD", leg("足首"), NORMAL | APPEND_ROTATE, {"layer": 2, "append": (s + "足首", 1.0)}),
                 (s + "足先EX", s + "足首D", leg("足先EX"), NORMAL, {"layer": 2})]
    index = {r[0]: i for i, r in enumerate(rows)}
    built = []
    for name, parent, pos, flags, kw in rows:
        args = {"parent": -1 if parent is None else index[parent], "position": pos, "flags": flags, "layer": kw.get("layer", 0)}
        if "append" in kw:
            args["append"] = (index[kw["append"][0]], kw["append"][1])
        if "ik" in kw:
            target, loops, angle, links = kw["ik"]
            args["ik"] = {"target": index[target], "loops": loops, "angle": angle, "links": [(index[l], lim) for l, lim in links]}
        built.append(w.bone(name, **args))
    verts = []
    for side, sx in (("左", 1.0), ("右", -1.0)):
        ankle_d, ex = index[side + "足首D"], index[side + "足先EX"]
        for x, y, z, wex in SOLE + SHOE_UPPER + [CAP]:
            raw = w.vertex("BDEF2", (ex, ankle_d), (wex,)) if wex > 0 else w.vertex("BDEF1", (ankle_d,))
            verts.append(struct.pack("<3f", sx * x, y, z) + raw[12:])
    return w.build(name="rin-body", bones=built, vertices=verts)


def key(name, frame, position=(0.0, 0.0, 0.0), q=(0.0, 0.0, 0.0, 1.0)):
    from mmd_cli import fk
    return vmd.BoneKey(name, frame, tuple(float(v) for v in position), fk.stored(tuple(q)), vmd.bone_interpolation(vmd.LINEAR_CURVE))


def axis_angle(axis, degrees):
    n = math.sqrt(sum(a * a for a in axis))
    h = math.radians(degrees) / 2.0
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


BENT = -1.2                     # センター this far down: the knees bent, every foot goal within reach


def dance(F, centre=lambda t: (0.0, 0.0, 0.0), feet=None, sway=6.0, extra=()):
    """a dance of F frames: センター at BENT + centre(t), the upper body turning sideways by `sway` degrees at 1 Hz (the
    dance range), the arms swinging, the foot IKs at feet(side, t) (on the floor when not given), more keys after"""
    keys = []
    for t in range(F):
        c = centre(t)
        keys.append(key("センター", t, position=(c[0], BENT + c[1], c[2])))
        a = sway * math.sin(2.0 * math.pi * t / 30.0)
        keys.append(key("上半身", t, q=axis_angle((0.0, 0.0, 1.0), a)))
        for s, sx in (("左", 1.0), ("右", -1.0)):
            keys.append(key(s + "腕", t, q=axis_angle((0.0, 0.0, 1.0), sx * (20.0 * math.sin(2.0 * math.pi * t / 45.0)))))
            if feet is not None:
                keys.append(key(s + "足ＩＫ", t, position=feet(s, t)))
    return vmd.Motion(model_name="rin-body", bones=keys + list(extra))


def front_camera(path, y=10.0, distance=45.0, fov=30):
    """a still camera in front of the model (looking along +Z at (0, y, 0)), written to path"""
    k = dict(distance=-distance, position=(0.0, y, 0.0), rotation=(0.0, 0.0, 0.0), fov=fov)
    vmd.dump(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **k), vmd.CameraKey(frame=100, **k)]), path)
    return path


def ref(mid):
    return base.reference(mid)
