"""One version of the MV and the arrays every part reads, computed once and kept in a cache folder.

A version (a spec, JSON or the command's flags):

    {"label": "v9", "model": "White_spine_v6_eyes.pmx", "motions": [dance.vmd, face.vmd, gaze.vmd, eye_optics.vmd],
     "dance": dance.vmd, "reference": spine_h.vmd, "camera": cam_front.vmd, "vocal": vocals.flac, "lines": lines.tsv,
     "first": 0, "last": 7742}

* motions: the render inputs in their loading order.  They are merged as MMD merges motions loaded one after another
  onto one model: a later file's key replaces an earlier file's key of the same bone (or morph) on the same frame; keys
  on other frames stay (the analysis pack's builder, stage6/human_baseline/scripts/packbuild/pack_build_vN.py).
* dance: the body's motion (default: the first of motions), for what reads the legs as MMD's IK puts them
  (tools/leg_ik.py, tools/sink_check.py) and the balance layer's body (tools/balance_layer.Body).
* reference: the dance before the body's layers (for the measures that keep the dance's own jumps and accents).
* camera, vocal, lines: for the marks on pictures and the mouth.

pack(): the 26 bones of the uncanny analysis pack (PACK_BONES), pos [F, 26, 3] and rot [F, 26, 4] as float32, by
mmd_cli.fk (no IK, no physics: the legs' FK bones mean nothing, the IK targets are the feet) on the merged motion,
frames first..last; extra(): the same for the twist bones (腕捩, 手捩), the spine's added bones and the eyes' tips.
Both exactly as pack_build_vN.py writes bones_final.npz (float32), so that the analysts' measures read the same numbers.
"""
import json
import os
import time

import numpy as np

from . import base

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, vmd  # noqa: E402

PACK_BONES = ["全ての親", "センター", "グルーブ", "腰", "下半身", "上半身", "上半身2", "首", "頭", "両目", "左目", "右目", "左肩",
              "右肩", "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首", "左中指３", "右中指３", "左足ＩＫ", "右足ＩＫ",
              "左つま先ＩＫ", "右つま先ＩＫ"]
EXTRA_BONES = ["左腕捩", "右腕捩", "左手捩", "右手捩", "左肩", "右肩", "腰椎上部", "胸椎上部", "頭先", "両目先"]
CACHE_VERSION = 1
# the code the cached arrays come from: a change of any of these makes new keys (a cache folder kept across a change of
# the FK or of the legs' IK must not give the old arrays)
CACHE_CODE = (os.path.join("mmd_cli", "fk.py"), os.path.join("mmd_cli", "formats", "vmd.py"),
              os.path.join("mmd_cli", "formats", "pmx.py"), os.path.join("mmd_cli", "formats", "pmx_edit.py"),
              os.path.join("tools", "sink_check.py"), os.path.join("tools", "leg_ik.py"), os.path.join("tools", "mvi", "body.py"))
_CODE_MD5 = []


def code_md5():
    """one md5 over the files of CACHE_CODE (computed once)"""
    if not _CODE_MD5:
        h = base.hashlib.md5()
        for rel in CACHE_CODE:
            with open(os.path.join(base.ROOT, rel), "rb") as f:
                h.update(f.read())
        _CODE_MD5.append(h.hexdigest())
    return _CODE_MD5[0]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def merged_bone_keys(motions):
    """bone name -> keys, after loading `motions` in order (pack_build_vN.merged_bone_keys, verbatim)"""
    by = {}
    for m in motions:
        mine = {}
        for k in m.bones:
            mine.setdefault(k.name, []).append(k)
        for name, keys in mine.items():
            frames = {k.frame for k in keys}
            by[name] = [k for k in by.get(name, []) if k.frame not in frames] + keys
    return by


def merged_morph_keys(motions):
    """morph name -> [(frame, weight)] sorted, the same rule (pack_build_vN.merged_morph_keys, verbatim)"""
    by, order = {}, []
    for m in motions:
        mine = {}
        for k in m.morphs:
            mine.setdefault(k.name, {})[k.frame] = k.weight
        for name, keys in mine.items():
            if name not in by:
                order.append(name)
            old = by.get(name, {})
            old.update(keys)
            by[name] = old
    return {n: sorted(v.items()) for n, v in by.items()}, order


def merged_motion(motions):
    """one vmd.Motion holding the merged bone and morph keys"""
    keys = merged_bone_keys(motions)
    morphs, _ = merged_morph_keys(motions)
    return vmd.Motion(model_name=motions[0].model_name, bones=[k for ks in keys.values() for k in ks],
                      morphs=[vmd.MorphKey(n, f, w) for n, ks in morphs.items() for f, w in ks])


def load_spec(path_or_dict):
    spec = dict(path_or_dict) if isinstance(path_or_dict, dict) else json.load(open(path_or_dict, encoding="utf-8"))
    if "motions" not in spec or not spec["motions"]:
        raise ValueError("a version needs its motions (the render inputs in their loading order)")
    if "model" not in spec:
        raise ValueError("a version needs its model (.pmx)")
    spec.setdefault("label", os.path.splitext(os.path.basename(spec["motions"][0]))[0])
    spec.setdefault("dance", spec["motions"][0])
    missing = [(k, p) for k in ("model", "dance", "reference", "camera", "vocal", "lines")
               for p in [spec.get(k)] if p and not os.path.isfile(p)]
    missing += [("motions", p) for p in spec["motions"] if not os.path.isfile(p)]
    if missing:
        raise ValueError("files of the version that are not there: %s" % "; ".join("%s %s" % kp for kp in missing))
    return spec


class Version:
    """the arrays of one version, computed on demand and kept in `cache` (a folder; None: kept in memory only)"""

    def __init__(self, spec, cache=None):
        self.spec = load_spec(spec)
        self.label = self.spec["label"]
        self.cache = cache
        self._mem = {}
        self._md5 = {}

    # -- inputs ------------------------------------------------------------------------------------------------------
    def md5(self, key):
        p = self.spec.get(key)
        if not p:
            return None
        if p not in self._md5:
            self._md5[p] = base.md5(p)
        return self._md5[p]

    def inputs(self):
        out = {"model": [self.spec["model"], self.md5("model")],
               "motions": [[p, base.md5(p)] for p in self.spec["motions"]]}
        for k in ("dance", "reference", "camera", "vocal", "lines"):
            if self.spec.get(k):
                out[k] = [self.spec[k], self.md5(k)]
        return out

    def _key(self, what, *parts):
        h = base.hashlib.md5(("%s|%d|%s|" % (what, CACHE_VERSION, code_md5())).encode())
        for p in parts:
            h.update(str(p).encode("utf-8"))
            h.update(b"|")
        return what + "_" + h.hexdigest()[:16]

    def _cached(self, key, build):
        if key in self._mem:
            return self._mem[key]
        path = os.path.join(self.cache, key + ".npz") if self.cache else None
        if path and os.path.isfile(path):
            z = np.load(path, allow_pickle=False)
            val = {k: z[k] for k in z.files}
        else:
            val = build()
            if path:
                os.makedirs(self.cache, exist_ok=True)
                tmp = path + ".part.npz"
                np.savez_compressed(tmp, **val)
                os.replace(tmp, path)
        self._mem[key] = val
        return val

    @property
    def model(self):
        if "model" not in self._mem:
            self._mem["model"] = pmx.load(self.spec["model"])
        return self._mem["model"]

    @property
    def motions(self):
        if "motions" not in self._mem:
            self._mem["motions"] = [vmd.load(p) for p in self.spec["motions"]]
        return self._mem["motions"]

    @property
    def merged(self):
        if "merged" not in self._mem:
            self._mem["merged"] = merged_motion(self.motions)
        return self._mem["merged"]

    @property
    def dance(self):
        if "dance" not in self._mem:
            if os.path.normcase(os.path.abspath(self.spec["dance"])) == os.path.normcase(os.path.abspath(self.spec["motions"][0])):
                self._mem["dance"] = self.motions[0]
            else:
                self._mem["dance"] = vmd.load(self.spec["dance"])
        return self._mem["dance"]

    @property
    def reference(self):
        if not self.spec.get("reference"):
            return None
        if "reference" not in self._mem:
            self._mem["reference"] = vmd.load(self.spec["reference"])
        return self._mem["reference"]

    @property
    def first(self):
        return int(self.spec.get("first", 0))

    @property
    def last(self):
        if "last" in self.spec:
            return int(self.spec["last"])
        if "_last" not in self._mem:
            self._mem["_last"] = max(fk.last_frame(m) for m in self.motions)
        return self._mem["_last"]

    @property
    def frames(self):
        return self.last - self.first + 1

    # -- the arrays --------------------------------------------------------------------------------------------------
    def _fk(self):
        names = PACK_BONES + [n for n in EXTRA_BONES if n not in PACK_BONES]
        have = {b.name for b in self.model.bones}
        names = [n for n in names if n in have]
        t = time.time()
        track = fk.world_track(self.model, self.merged, names, self.first, self.last)
        log("fk", self.label, len(names), "bones", self.frames, "frames %.0f s" % (time.time() - t))
        F = self.frames
        out = {}
        for group, lst in (("", PACK_BONES), ("extra_", [n for n in names if n not in PACK_BONES or n in EXTRA_BONES])):
            lst = [n for n in lst if n in track]
            out[group + "pos"] = np.array([[track[b][f][0] for b in lst] for f in range(F)], dtype=np.float32).reshape(F, len(lst), 3)
            out[group + "rot"] = np.array([[track[b][f][1] for b in lst] for f in range(F)], dtype=np.float32).reshape(F, len(lst), 4)
            out[group + "names"] = np.array(lst)
        return out

    def _fk_arrays(self):
        key = self._key("fk", self.md5("model"), *[base.md5(p) for p in self.spec["motions"]], self.first, self.last)
        return self._cached(key, self._fk)

    def pack(self):
        """(names, pos [F, 26, 3] float32, rot [F, 26, 4] float32): the analysis pack's bones_final"""
        a = self._fk_arrays()
        names = [str(n) for n in a["names"]]
        if names != PACK_BONES:
            missing = [n for n in PACK_BONES if n not in names]
            raise ValueError("the model lacks bones of the analysis pack: %s" % ", ".join(missing))
        return names, a["pos"], a["rot"]

    def extra(self):
        """(names, pos, rot) of the twist, spine and tip bones the model has"""
        a = self._fk_arrays()
        return [str(n) for n in a["extra_names"]], a["extra_pos"], a["extra_rot"]

    def bone(self, name):
        """(pos [F, 3], rot [F, 4]) float32 of a bone of pack() or extra()"""
        names, pos, rot = self.pack()
        if name in names:
            i = names.index(name)
            return pos[:, i], rot[:, i]
        en, ep, er = self.extra()
        i = en.index(name)
        return ep[:, i], er[:, i]

    def morph_weights(self, names):
        """morph name -> weights [F] straight between the merged keys (MMD's morph interpolation), 0 without keys"""
        keys, _ = merged_morph_keys(self.motions)
        frames = np.arange(self.first, self.last + 1)
        out = {}
        for n in names:
            ks = keys.get(n)
            out[n] = np.interp(frames, [f for f, _ in ks], [w for _, w in ks]) if ks else np.zeros(len(frames))
        return out

    # -- the legs as MMD's IK puts them -------------------------------------------------------------------------------
    def rig(self):
        if "rig" not in self._mem:
            self._mem["rig"] = base.tool("leg_ik").LegRig.load(self.spec["model"])
        return self._mem["rig"]

    def doc(self):
        if "doc" not in self._mem:
            from mmd_cli.formats import pmx_edit
            self._mem["doc"] = pmx_edit.load(self.spec["model"])
        return self._mem["doc"]

    def shoes(self, which="dance"):
        """tools/sink_check.measure of the dance (or the reference): the pelvis's heights above the legs, the shoes' lowest
        points and slides, the knees, the air (arrays [F]); and the IK's reach per side"""
        motion = self.dance if which == "dance" else self.reference
        src = self.spec["dance"] if which == "dance" else self.spec["reference"]
        key = self._key("shoes", self.md5("model"), base.md5(src), self.first, self.last)

        def build():
            sc = base.tool("sink_check")
            frames = list(range(self.first, self.last + 1))
            t = time.time()
            floor_y = sc.rest_floor(self.rig(), self.doc())
            m = sc.measure(self.rig(), self.doc(), motion, frames, floor_y)
            sol = base.tool("leg_ik").solve(self.rig(), motion, frames)
            log("shoes", self.label, which, "%.0f s" % (time.time() - t))
            out = {"floor_y": np.array(floor_y)}
            for k, v in m.items():
                out[{"下半身_y": "lower_body_y", "センター_y": "centre_y"}.get(k, k)] = np.asarray(v)
            for s, tag in (("左", "left"), ("右", "right")):
                out["reach_" + tag] = np.asarray(sol[s]["reach"], dtype=np.float64)
                out["toe_reach_" + tag] = np.asarray(sol[s]["toe_reach"], dtype=np.float64)
            return out
        return self._cached(key, build)

    def balance_body(self, which="dance"):
        """tools/balance_layer.Body of the dance (or the reference) on the model"""
        k = "body_" + which
        if k not in self._mem:
            motion = self.dance if which == "dance" else self.reference
            self._mem[k] = base.tool("balance_layer").Body(self.model, motion)
        return self._mem[k]
