"""Share the trunk's bend between the pelvis and the chest out over the spine bones of a model made by tools/pmx_spine.py
(上半身, 腰椎上部, 上半身2, 胸椎上部), by the spine's anatomy, with the chest's world pose kept.

    python tools/spine_layer.py DANCE.vmd MODEL.pmx SPINE_MODEL.pmx OUT.vmd [--report r.json]

DANCE.vmd is a dance for the original MODEL (its 上半身 and 上半身2 keys, e.g. after tools/anatomy_layer.py, which split
them 0.25 / 0.3 / 0.4); OUT.vmd is for SPINE_MODEL.  This layer goes last: it replaces anatomy_layer's split of the
trunk (that split only survives through the chest's pose, which is kept) and leaves every other bone's keys alone.

The bend B is the chest's (上半身2 in DANCE) rotation against the pelvis (下半身, 上半身's sibling under 腰).  Each spine
bone k takes the cumulative share c_k of B (upright_part of tools/anatomy_layer.py: the swing of the up axis by its
direction, flexion about X and lateral bend about Z, and the twist about Y), from SHARES.  Then, so that the chest is
also where it was (a curved spine ends elsewhere than a straight one with the same end rotation), the three lower
bones' rotations are corrected by the smallest turns (Gauss-Newton, the minimum-norm step, damped) that bring 胸椎上部 to the
place of the old chest frame; 胸椎上部's world rotation is the old chest's exactly.  Everything above (neck, head, arms,
hands) then has its old world pose.  Per frame the result is a smooth function of B, so it is as smooth as the input.

SHARES (one side per joint, degrees; the four bones' joints as in tools/pmx_spine.py):
  regional totals (anatomystandard.com, ROM of the spine, in-vivo healthy young males): lumbar flexion+extension 96,
  lateral bend 30, axial turn 15.3; thoracic 48, 30, 47.
  thoracic upper (T1-T7) : lower (T7-L1) halves: axial 9.5 : 11.9 (Fujimori 2012, CT), lateral 6.9 : 10.9 (Fujimori
  2014, CT); flexion: no split found, spread evenly (an assumption).
  Within a region every joint takes an equal part of its half (an assumption).
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_spine_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _tool("anatomy_layer")
S = _tool("pmx_spine")

WAIST, PELVIS, LO, UP = "腰", "下半身", "上半身", "上半身2"
CHAIN = (LO, S.LUMBAR, UP, S.THORACIC)

# degrees per joint, one side: (flexion+extension, lateral bend, axial turn)
LUMBAR_TOTAL = (96.0, 30.0, 15.3)
THORACIC_TOTAL = (48.0, 30.0, 47.0)
THORACIC_UPPER = (0.5, 6.9 / (6.9 + 10.9), 9.5 / (9.5 + 11.9))   # the upper half's part of the thoracic total
# the joints each bone stands for: (lumbar joints, lower thoracic joints, upper thoracic joints) of 5, 6 and 6
JOINTS = {LO: (4, 0, 0), S.LUMBAR: (1, 2, 0), UP: (0, 4, 0), S.THORACIC: (0, 0, 6)}


def _shares():
    out = {}
    for m, key in enumerate(("flex", "lat", "rot")):
        per = (LUMBAR_TOTAL[m] / 5.0, THORACIC_TOTAL[m] * (1.0 - THORACIC_UPPER[m]) / 6.0, THORACIC_TOTAL[m] * THORACIC_UPPER[m] / 6.0)
        deg = [sum(n * p for n, p in zip(JOINTS[b], per)) for b in CHAIN]
        out[key] = [d / sum(deg) for d in deg]
    return out


SHARES = _shares()
GN_STEPS = 12
DAMP = 1e-6


def _matrix(q):
    """rotation matrices [..., 3, 3] of quaternions"""
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
                     np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
                     np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1)], -2)


def _skew(d):
    x, y, z = d
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)


def _rotvec_quat(v):
    ang = np.linalg.norm(v, axis=-1)
    return A.aa(A.unit(np.where(ang[..., None] > 1e-12, v, np.array([1.0, 0.0, 0.0]))), ang)


def _track(model, motion, names, F):
    pose = fk.Pose(model, motion, names)
    pos = np.zeros((F, len(names), 3))
    rot = np.zeros((F, len(names), 4))
    idx = [i for _, i in pose.targets]
    for f in range(F):
        w = pose.world(f)
        for j, i in enumerate(idx):
            pos[f, j], rot[f, j] = w[i]
    return pos, A.continuous(rot)


def _rest(model, name):
    for b in model.bones:
        if b.name == name:
            return np.array(b.position, dtype=float)
    raise ValueError("the model has no bone named %r" % name)


def layer(old_model, new_model, motion, log=None):
    """(the motion for new_model, a report)"""
    F = fk.last_frame(motion) + 1
    pos, rot = _track(old_model, motion, [WAIST, PELVIS, LO, UP], F)
    q_waist, q_pelvis, q_lo_in, q_chest = rot[:, 0], rot[:, 1], rot[:, 2], rot[:, 3]
    p_lo, p_chest = pos[:, 2], pos[:, 3]
    rest = [_rest(new_model, n) for n in CHAIN]
    d = [rest[k + 1] - rest[k] for k in range(3)]
    old_up = _rest(old_model, UP)
    B = A.continuous(A.qnorm(A.qmul(A.qconj(q_pelvis), q_chest)))
    cum = np.cumsum(np.array([SHARES[m] for m in ("flex", "lat", "rot")]), axis=1)
    C = [A.upright_part(B, {"flex": cum[0, k], "lat": cum[1, k], "rot": cum[2, k]}) for k in range(3)]
    # where 胸椎上部 must be: the old chest frame carries its rest point; in the pelvis's frame, from 上半身's joint
    target_world = p_chest + A.qrot(q_chest, rest[3] - old_up)
    t = A.qrot(A.qconj(q_pelvis), target_world - p_lo)
    total = [np.zeros((F, 3)) for _ in range(3)]
    for _ in range(GN_STEPS):
        R = [_matrix(c) for c in C]
        reach = sum(np.einsum("fij,j->fi", R[k], d[k]) for k in range(3))
        r = t - reach
        J = np.concatenate([-R[k] @ _skew(d[k]) for k in range(3)], axis=2)        # F x 3 x 9
        JJ = J @ np.swapaxes(J, 1, 2) + DAMP * np.eye(3)    # damped: a straight chain cannot stretch
        step = np.einsum("fji,fj->fi", J, np.linalg.solve(JJ, r[..., None])[..., 0])
        for k in range(3):
            dk = step[:, 3 * k:3 * k + 3]
            total[k] += dk
            C[k] = A.qnorm(A.qmul(C[k], _rotvec_quat(dk)))
    R = [_matrix(c) for c in C]
    residual = np.linalg.norm(t - sum(np.einsum("fij,j->fi", R[k], d[k]) for k in range(3)), axis=1)
    worlds = [A.qmul(q_pelvis, c) for c in C] + [q_chest]
    local = {LO: A.qmul(A.qconj(q_waist), worlds[0])}
    for k in range(1, 4):
        local[CHAIN[k]] = A.qmul(A.qconj(worlds[k - 1]), worlds[k])
    local = {n: A.continuous(A.qnorm(q)) for n, q in local.items()}
    out = A.build(motion, None, local, {}, F)
    # the measures
    rel = [A.qmul(A.qconj(q_pelvis), worlds[0])] + [local[n] for n in CHAIN[1:]]
    ang = [A.upright_angles(q) for q in rel]
    shares = {}
    for m, key in enumerate(("flex", "lat", "rot")):
        s = [float(np.sum(np.abs(a[m]))) for a in ang]
        shares[key] = [round(x / max(sum(s), 1e-12), 4) for x in s]

    def max_step(qs):
        return max(float(np.degrees(np.max(A.qangle(A.qmul(A.qconj(q[:-1]), q[1:]))))) if len(q) > 1 else 0.0 for q in qs)
    q_up_in = A.qmul(A.qconj(q_lo_in), q_chest)
    report = {"frames": F, "shares_table": SHARES, "shares_measured": shares,
              "correction_deg": {"p50": round(float(np.degrees(np.median(np.linalg.norm(np.concatenate(total, 1), axis=1)))), 3),
                                 "max": round(float(np.degrees(np.max(np.linalg.norm(np.concatenate(total, 1), axis=1)))), 3)},
              "chest_residual_cm_max": round(float(np.max(residual)) * A.UNIT_CM, 5),
              "max_step_deg": {"in": round(max_step([A.qmul(A.qconj(q_pelvis), q_lo_in), q_up_in]), 3),
                               "out": round(max_step([rel[0]] + rel[1:]), 3)}}
    if log:
        log("spine: chest residual %.5f cm, correction p50 %.2f deg" % (report["chest_residual_cm_max"], report["correction_deg"]["p50"]))
    return out, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance")
    ap.add_argument("model")
    ap.add_argument("spine_model")
    ap.add_argument("out")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out) in (os.path.abspath(a.dance), os.path.abspath(a.model), os.path.abspath(a.spine_model)):
        raise SystemExit("the output would overwrite an input")
    out, report = layer(pmx.load(a.model), pmx.load(a.spine_model), vmd.load(a.dance), log=print)
    vmd.dump(out, a.out)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("shares_measured", "correction_deg", "chest_residual_cm_max", "max_step_deg")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
