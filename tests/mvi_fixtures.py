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
    """shared.Measured's face: hb, a05 and fq run on the fake pack; wb, shoes and vertical give what the test set"""

    def __init__(self, version, wb=None, shoes=None, ref_shoes=None, vertical=None):
        self.v = version
        self._wb, self._shoes, self._ref_shoes, self._vertical = wb, shoes, ref_shoes, vertical
        self._c = {}

    def hb(self):
        if "hb" not in self._c:
            self._c["hb"] = HB.measure(*self.v.pack())
        return self._c["hb"]

    def a05(self):
        if "a05" not in self._c:
            names, pos, rot = self.v.pack()
            self._c["a05"] = A05.run(names, pos, rot, rest=rin_rest())
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


def front_camera(path, y=10.0, distance=45.0, fov=30):
    """a still camera in front of the model (looking along +Z at (0, y, 0)), written to path"""
    k = dict(distance=-distance, position=(0.0, y, 0.0), rotation=(0.0, 0.0, 0.0), fov=fov)
    vmd.dump(vmd.Motion.for_camera(cameras=[vmd.CameraKey(frame=0, **k), vmd.CameraKey(frame=100, **k)]), path)
    return path


def ref(mid):
    return base.reference(mid)
