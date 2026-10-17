"""Share the trunk's bend between the pelvis and the chest out over the spine bones of a model made by tools/pmx_spine.py
(上半身, 腰椎上部, 上半身2, 胸椎上部), by the spine's anatomy, with the chest's world pose kept.

    python tools/spine_layer.py DANCE.vmd MODEL.pmx SPINE_MODEL.pmx OUT.vmd [--report r.json] [--place-cap-cm 3.0]

DANCE.vmd is a dance for the original MODEL (its 上半身 and 上半身2 keys, e.g. after tools/anatomy_layer.py, which split
them 0.25 / 0.3 / 0.4); OUT.vmd is for SPINE_MODEL.  This layer goes last: it replaces anatomy_layer's split of the
trunk (that split only survives through the chest's pose, which is kept) and leaves every other bone's keys alone.

The bend B is the chest's (上半身2 in DANCE) rotation against the pelvis (下半身, 上半身's sibling under 腰).  Each spine
bone k takes the cumulative share c_k of B (upright_part of tools/anatomy_layer.py: the swing of the up axis by its
direction, flexion about X and lateral bend about Z, and the twist about Y), from SHARES.  胸椎上部's world rotation is
the old chest's exactly.  A curved spine ends elsewhere than a straight one with the same end rotation, so the chest
drifts from its old place.  The drift is let be up to --place-cap-cm (PLACE_CAP_CM); beyond, the three lower bones'
rotations are corrected by the smallest turns weighted by the joints' range (correction_weights; Gauss-Newton, the
weighted minimum-norm step, damped).  Not to 0 by default: the old place came from the old two-bone rig, and matched
exactly it pulls the bend back onto 上半身 (88 % of a 40 degree flexion).  Everything above the chest (neck, head, arms,
hands) keeps its world rotation and moves with the chest, by at most the cap.  The correction is kept within each
bone's range (ranges(): the degrees of the joints it stands for, flexion+extension, lateral bend, axial turn): where it
would bend a bone further (the review of 2026-10-13: 上半身2 bent back 21.4 degrees at frame 1268, its range 16), the
correction is walked back toward the anatomical shares and the rest is left as the chest's drift beyond the cap
(chest_drift_left_cm).  Per frame the result is a smooth
function of B, so it is as smooth as the input.

SHARES (one side per joint, degrees; the four bones' joints as in tools/pmx_spine.py):
  regional totals (anatomystandard.com, ROM of the spine, in-vivo healthy young males): lumbar flexion+extension 96,
  lateral bend 30, axial turn 15.3; thoracic 48, 30, 47.
  thoracic upper (T1-T7) : lower (T7-L1) halves: axial 9.5 : 11.9 (Fujimori 2012, CT), lateral 6.9 : 10.9 (Fujimori
  2014, CT); flexion: no split found, spread evenly (an assumption).
  Within a region every joint takes an equal part of its half (an assumption; the lumbar flexion is really biased to
  L4/5 and L5/S1, which would give 上半身 more).
  The ratio of the ranges is used as the ratio in which a dance shares its bend out (an assumption: a range is how far
  a joint can go, not how a dancer uses it).
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
KEEP_TOUCHES = True             # the hands that lie on (or near) a part keep their place on it (tools/touch_layer.keep_layer)

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


def _degrees():
    """per bone of CHAIN: the degrees of its joints, (flexion+extension, lateral bend, axial turn)"""
    out = []
    for b in CHAIN:
        row = []
        for m in range(3):
            per = (LUMBAR_TOTAL[m] / 5.0, THORACIC_TOTAL[m] * (1.0 - THORACIC_UPPER[m]) / 6.0, THORACIC_TOTAL[m] * THORACIC_UPPER[m] / 6.0)
            row.append(sum(n * p for n, p in zip(JOINTS[b], per)))
        out.append(row)
    return out


def correction_weights():
    """the weights of the correction's nine turns (the three lower bones, each about X, Y, Z): the square of the joints'
    range about that axis (X flexion, Y axial turn, Z lateral bend), so that a joint that moves more takes more"""
    w = []
    for flex, lat, rot in _degrees()[:3]:
        w += [flex ** 2, rot ** 2, lat ** 2]
    w = np.array(w)
    return w / w.max()


GN_STEPS = 12
BISECT_STEPS = 20
PLACE_CAP_CM = 3.0              # the full song (v5a): 87 frames bent the other way at 3.0, 584 at 1.5, 1,367 at 0
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


def ranges():
    """per bone of CHAIN: the range its joints allow, degrees (flexion+extension, lateral bend, axial turn; one side)"""
    return [[round(v, 6) for v in row] for row in _degrees()]


def _local_angles(Cs, B):
    """F x 4 x 3: |flexion|, |lateral bend|, |axial turn| (degrees) of each spine bone against the one below (上半身
    against the pelvis), from the cumulative rotations C_0..C_2 and the bend B"""
    rel = [Cs[0]] + [A.qmul(A.qconj(Cs[k - 1]), Cs[k]) for k in (1, 2)] + [A.qmul(A.qconj(Cs[2]), B)]
    return np.stack([np.abs(np.stack(A.upright_angles(q), -1)) for q in rel], axis=1)


def frame_runs(mask, gap=5):
    """[[first, last], ...] of the frames where mask holds, runs with at most `gap` frames between them merged"""
    out = []
    for f in np.flatnonzero(mask):
        f = int(f)
        if out and f - out[-1][1] - 1 <= gap:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


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


def layer(old_model, new_model, motion, place_cap_cm=None, log=None, bodies=None):
    """(the motion for new_model, a report); bodies: (tools/retarget.py's Body of old_model, of new_model), with their
    meshes: the hands near a part of the body keep their place on it (KEEP_TOUCHES; none: as before)"""
    place_cap_cm = PLACE_CAP_CM if place_cap_cm is None else place_cap_cm
    if place_cap_cm < 0:
        place_cap_cm = None                                       # no correction at all
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
    R = [_matrix(c) for c in C]
    drift = t - sum(np.einsum("fij,j->fi", R[k], d[k]) for k in range(3))        # where the anatomical shares miss
    size = np.linalg.norm(drift, axis=1) * A.UNIT_CM
    if place_cap_cm is None:
        kept = drift
    else:
        kept = drift * np.minimum(1.0, float(place_cap_cm) / np.maximum(size, 1e-12))[:, None]
    t = t - kept                      # the chest may stay this far from its old place; the rest is corrected
    total = [np.zeros((F, 3)) for _ in range(3)]
    C_anat = list(C)
    Wc = correction_weights()
    for _ in range(GN_STEPS):
        R = [_matrix(c) for c in C]
        reach = sum(np.einsum("fij,j->fi", R[k], d[k]) for k in range(3))
        r = t - reach
        J = np.concatenate([-R[k] @ _skew(d[k]) for k in range(3)], axis=2)        # F x 3 x 9
        JW = J * Wc                                                     # weighted minimum norm: W J^T (J W J^T)^-1 r
        JJ = JW @ np.swapaxes(J, 1, 2) + DAMP * np.eye(3)    # damped: a straight chain cannot stretch
        step = np.einsum("fji,fj->fi", JW, np.linalg.solve(JJ, r[..., None])[..., 0])
        for k in range(3):
            dk = step[:, 3 * k:3 * k + 3]
            total[k] += dk
            C[k] = A.qnorm(A.qmul(C[k], _rotvec_quat(dk)))
    # the correction is kept within each bone's range: the corrected rotations are walked back toward the anatomical
    # ones (one fraction per frame, by bisection) until no bone bends past its range (or past what the shares alone
    # asked, where they ask more); what is given up stays as the chest's drift
    lim = np.array(ranges())
    anat_ang = _local_angles(C_anat, B)
    allowed = np.maximum(lim[None, :, :], anat_ang)                              # F x 4 x 3

    def beyond(Cs):
        return np.any(_local_angles(Cs, B) > allowed + 1e-6, axis=(1, 2))
    lo_s, hi_s = np.zeros(F), np.ones(F)
    over = beyond(C)
    for _ in range(BISECT_STEPS):
        mid = np.where(over, (lo_s + hi_s) / 2.0, 1.0)
        bad = beyond([A.slerp(ca, cf, mid) for ca, cf in zip(C_anat, C)])
        lo_s = np.where(over & ~bad, mid, lo_s)
        hi_s = np.where(over & bad, mid, hi_s)
    frac = np.where(over, lo_s, 1.0)
    C = [A.slerp(ca, cf, frac) for ca, cf in zip(C_anat, C)]
    still = beyond(C) & over
    R = [_matrix(c) for c in C]
    left = np.linalg.norm(t + kept - sum(np.einsum("fij,j->fi", R[k], d[k]) for k in range(3)), axis=1) * A.UNIT_CM
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
    flex_all = A.upright_angles(B)[0]
    opposite = np.zeros(F, bool)
    for a in ang:
        opposite |= (np.sign(a[0]) != np.sign(flex_all)) & (np.abs(a[0]) > 2.0) & (np.abs(flex_all) > 5.0)
    q_up_in = A.qmul(A.qconj(q_lo_in), q_chest)
    report = {"frames": F, "shares_table": SHARES, "shares_measured": shares,
              "correction_deg": {"p50": round(float(np.degrees(np.median(np.linalg.norm(np.concatenate(total, 1), axis=1)))), 3),
                                 "max": round(float(np.degrees(np.max(np.linalg.norm(np.concatenate(total, 1), axis=1)))), 3)},
              "chest_drift_anatomical_cm": {"p50": round(float(np.median(size)), 3),
                                            "p95": round(float(np.percentile(size, 95)), 3), "max": round(float(size.max()), 3)},
              "place_cap_cm": place_cap_cm,
              "opposite_bend_frames": int(opposite.sum()),
              "opposite_max_deg": round(max([float(np.max(np.where(opposite & (np.sign(a[0]) != np.sign(flex_all)), np.abs(a[0]), 0.0)))
                                             for a in ang] + [0.0]), 3),
              "range_deg": ranges(),
              "range_limited_frames": int(np.sum(frac < 1.0)),
              "range_limited_runs": frame_runs(frac < 1.0),
              "beyond_range_frames": int(still.sum()),
              "local_max_deg": [[round(float(v), 3) for v in row] for row in _local_angles(C, B).max(axis=0)],
              "anatomical_local_max_deg": [[round(float(v), 3) for v in row] for row in anat_ang.max(axis=0)],
              "chest_drift_left_cm": {"p95": round(float(np.percentile(left, 95)), 3), "max": round(float(left.max()), 3)},
              "opposite_runs": frame_runs(opposite),
              "corrected_runs": [] if place_cap_cm is None else frame_runs(size > place_cap_cm),
              "chest_residual_cm_max": round(float(np.max(residual)) * A.UNIT_CM, 5),
              "max_step_deg": {"in": round(max_step([A.qmul(A.qconj(q_pelvis), q_lo_in), q_up_in]), 3),
                               "out": round(max_step([rel[0]] + rel[1:]), 3)}}
    if bodies is not None and KEEP_TOUCHES:
        # the chest's drift carries the arms (they keep their world turns): a hand on the belly, the hips or a thigh
        # would go into it or leave it (the v11 review: the belly 35 -> 54 frames of an arm over 1 cm in)
        out, report["touches"] = _tool("touch_layer").keep_layer(bodies[0], motion, bodies[1], out, log=log)
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
    ap.add_argument("--place-cap-cm", type=float, default=PLACE_CAP_CM,
                    help="how far the chest may move from its old place, cm (0 keeps it; negative: no correction)")
    ap.add_argument("--no-keep-touches", action="store_true",
                    help="let the chest's drift carry a hand that lies on the belly, the hips or a thigh (as before v11)")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out) in (os.path.abspath(a.dance), os.path.abspath(a.model), os.path.abspath(a.spine_model)):
        raise SystemExit("the output would overwrite an input")
    bodies = None
    if not a.no_keep_touches:
        RT = _tool("touch_layer").RT
        bodies = (RT.Body.load(a.model), RT.Body.load(a.spine_model))
    out, report = layer(pmx.load(a.model), pmx.load(a.spine_model), vmd.load(a.dance), place_cap_cm=a.place_cap_cm, log=print,
                        bodies=bodies)
    vmd.dump(out, a.out)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("shares_measured", "correction_deg", "chest_drift_anatomical_cm",
                                                    "chest_residual_cm_max", "opposite_bend_frames", "max_step_deg")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
