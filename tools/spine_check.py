"""Check tools/pmx_spine.py + tools/spine_layer.py: the poses that must not change, and the trunk's skin.

    python tools/spine_check.py DANCE.vmd MODEL.pmx SPINE_DANCE.vmd SPINE_MODEL.pmx [--report r.json] [--frames N]

1. Pose: the world place (cm) and rotation (degrees) of 首, 頭, both 肩, 手首 and 胸椎上部's frame (the old chest, 上半身2,
   carried to it) under the old pair and under the new pair, every frame; the largest gap.
2. Skin: linear blend skinning (SDEF read as BDEF2, physics left out: skirt bones rest on their parents' keys) of the
   vertices that hang on the trunk, on the N frames with the largest trunk bend of the dance and on four set poses
   (flexion 40, lateral bend 30, axial turn 45 degrees, all three), for the old and the new pair.  Per pose: faces
   turned over (the deformed normal against the rest normal turned by the first corner's heaviest bone), the smallest
   and the 1st percentile of the faces' area ratios, and the volume ratio of the trunk's faces (the signed volume about
   their centroid: the trunk's faces are not a closed surface, so this is a comparison between the two models, not an
   absolute volume).
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mmd_cli import fk, mathutil  # noqa: E402
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402

import importlib.util  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_check_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _tool("anatomy_layer")
L = _tool("spine_layer")
S = _tool("pmx_spine")

WATCH = ["首", "頭", "左肩", "右肩", "左手首", "右手首"]


def pose_error(old_model, old_motion, new_model, new_motion, names, F=None):
    F = F or fk.last_frame(old_motion) + 1
    a = fk.world_track(old_model, old_motion, names, 0, F - 1)
    b = fk.world_track(new_model, new_motion, names, 0, F - 1)
    out = {}
    for n in names:
        pa, qa = np.array([p for p, _ in a[n]]), np.array([q for _, q in a[n]])
        pb, qb = np.array([p for p, _ in b[n]]), np.array([q for _, q in b[n]])
        dpos = np.linalg.norm(pa - pb, axis=1) * A.UNIT_CM
        dang = np.degrees(2.0 * np.arccos(np.clip(np.abs(np.sum(qa * qb, axis=1)), 0.0, 1.0)))
        out[n] = {"pos_cm_max": round(float(dpos.max()), 6), "rot_deg_max": round(float(dang.max()), 6),
                  "worst_frame": int(np.argmax(dpos))}
    return out


def _normals(x, faces):
    return np.cross(x[faces[:, 1]] - x[faces[:, 0]], x[faces[:, 2]] - x[faces[:, 0]])


def skin_metrics(rest, deformed, faces, vertex_rot):
    n0, n1 = _normals(rest, faces), _normals(deformed, faces)
    a0, a1 = np.linalg.norm(n0, axis=1), np.linalg.norm(n1, axis=1)
    ok = a0 > 1e-12
    turned = A.qrot(vertex_rot[faces[:, 0]], n0)
    flipped = int(np.sum((np.sum(turned * n1, axis=1) < 0.0) & ok))
    ratio = a1[ok] / a0[ok]

    def volume(x):
        c = x[np.unique(faces)].mean(axis=0)
        p = x[faces] - c
        return float(np.sum(np.einsum("fi,fi->f", p[:, 0], np.cross(p[:, 1], p[:, 2])))) / 6.0
    v0 = volume(rest)
    return {"flipped": flipped, "area_ratio_min": round(float(ratio.min()), 4),
            "area_ratio_p1": round(float(np.percentile(ratio, 1)), 4),
            "volume_ratio": round(volume(deformed) / v0, 6) if abs(v0) > 1e-12 else None}


def _faces(doc):
    raw = doc.middle
    n = int.from_bytes(raw[:4], "little", signed=True)
    fmt = {1: np.uint8, 2: np.uint16, 4: np.int32}[doc.sizes["vertex"]]
    return np.frombuffer(raw[4:4 + n * doc.sizes["vertex"]], dtype=fmt).astype(np.int64).reshape(-1, 3)


def _skin(doc, model, motion, frame, verts):
    names = [b.name for b in model.bones]
    pose = fk.Pose(model, motion, list(dict.fromkeys(names)))
    world = pose.world(frame)
    rest = np.array([b.position for b in model.bones], float)
    P = np.array([world[i][0] for i in range(len(names))])
    Q = np.array([world[i][1] for i in range(len(names))])
    out = np.zeros((len(verts), 3))
    rot = np.zeros((len(verts), 4))
    for j, vi in enumerate(verts):
        v = doc.vertices[vi]
        x = np.array(v.position())
        best = max(v.pairs(), key=lambda bw: bw[1])[0]
        rot[j] = Q[best]
        for b, w in v.pairs():
            if w > 0.0:
                out[j] += w * (P[b] + A.qrot(Q[b], x - rest[b]))
    return out, rot


def _set_poses():
    def key(name, frame, e):
        return vmd.BoneKey(name, frame, (0.0, 0.0, 0.0), fk.stored(mathutil.euler_to_quat(*e)), vmd.bone_interpolation(vmd.LINEAR_CURVE))
    poses = {"flex40": (40, 0, 0), "lat30": (0, 0, 30), "rot45": (0, 45, 0), "all": (40, 45, 30)}
    return {n: vmd.Motion(model_name="pose", bones=[key("上半身", 0, e)]) for n, e in poses.items()}


def skin_report(old_doc, old_model, new_doc, new_model, cases):
    """cases: {label: (old motion, new motion, frame)}"""
    lo, up = old_doc.bone_index(S.LOWER), old_doc.bone_index(S.UPPER)
    verts = [i for i, v in enumerate(old_doc.vertices) if any(b in (lo, up) and w > 0 for b, w in v.pairs())]
    keep = set(verts)
    faces = _faces(old_doc)
    faces = faces[np.all(np.isin(faces, list(keep)), axis=1)]
    remap = {v: j for j, v in enumerate(verts)}
    faces = np.vectorize(remap.get)(faces)
    rest = np.array([old_doc.vertices[i].position() for i in verts])
    out = {"vertices": len(verts), "faces": int(len(faces)), "poses": {}}
    for label, (m_old, m_new, frame) in cases.items():
        xo, ro = _skin(old_doc, old_model, m_old, frame, verts)
        xn, rn = _skin(new_doc, new_model, m_new, frame, verts)
        moved = np.linalg.norm(xn - xo, axis=1) * A.UNIT_CM
        out["poses"][label] = {"old": skin_metrics(rest, xo, faces, ro), "new": skin_metrics(rest, xn, faces, rn),
                               "skin_moved_cm": {"p50": round(float(np.median(moved)), 3), "max": round(float(moved.max()), 3)}}
    return out


def bend_frames(old_model, motion, n):
    F = fk.last_frame(motion) + 1
    _, rot = L._track(old_model, motion, [L.PELVIS, L.UP], F)
    ang = A.qangle(A.qmul(A.qconj(rot[:, 0]), rot[:, 1]))
    picks = []
    for f in np.argsort(-ang):
        if all(abs(int(f) - p) > 30 for p in picks):
            picks.append(int(f))
        if len(picks) == n:
            break
    return [(p, round(float(np.degrees(ang[p])), 2)) for p in picks]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("spine_dance")
    ap.add_argument("spine_model")
    ap.add_argument("--report")
    ap.add_argument("--frames", type=int, default=4)
    a = ap.parse_args(argv)
    old_doc, new_doc = pmx_edit.load(a.model), pmx_edit.load(a.spine_model)
    old_model, new_model = pmx.load(a.model), pmx.load(a.spine_model)
    dance, spine = vmd.load(a.dance), vmd.load(a.spine_dance)
    report = {"pose": pose_error(old_model, dance, new_model, spine, WATCH)}
    picks = bend_frames(old_model, dance, a.frames)
    report["bend_frames"] = picks
    cases = {"frame %d (%.0f deg)" % (f, g): (dance, spine, f) for f, g in picks}
    for name, m in _set_poses().items():
        cases[name] = (m, L.layer(old_model, new_model, m)[0], 0)
    report["skin"] = skin_report(old_doc, old_model, new_doc, new_model, cases)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
