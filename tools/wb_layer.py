"""The upper body does not ride the hips' quick moves: the spine bends against the quick part of the pelvis's sideways and
fore-and-aft motion, so the chest and the head stay steadier than the hips, and the head keeps its turn in the world.

    python tools/wb_layer.py DANCE.vmd MODEL.pmx OUT.vmd [--report r.json] [--gain 0.9] [--cutoff 1.5]
                             [--max-bend 10.0]

Why (the whole-body measures of 2026-10-17, tools/wb_dynamics.py, FineDance K-pop / choreography / jazz, 62 sequences,
against the MV): how much a body part follows the pelvis's (下半身's origin's) horizontal motion, per frequency band (the
cross-spectrum over the pelvis's spectrum).  People's head follows the pelvis by 0.89 at 0.5 Hz, 0.47 at 1.5 Hz and only
0.17-0.26 from 2 to 4 Hz (pooled; per sequence the median 0.11-0.24), the chest (the upper trunk) by 0.93, 0.74 and
0.65-0.68, the belly (the middle trunk) by about 1 at every frequency.  The traced dance (v9) carries all of them with
センター: the head 0.79-0.99 and the chest 0.89-0.98 at every frequency.  In one number (the slope of the 6 Hz
accelerations): people's head 0.29 [0.13, 0.42], the MV's 0.89; the chest 0.70 [0.56, 0.80] against 0.93.  The whole
upper body moving with every quick move of the hips is a puppet's (the dancer is moved from outside); a person's hips
move under a steady chest and head (the spine takes up the pelvis's quick moves; the head is the steadiest part of the
body, Pozzo et al. 1990).  It also asks the floor for the COM's acceleration of the whole upper body: the MV's COM
accelerates horizontally 4.95 m/s^2 at its 90th percentile (people 2.15), and its ZMP leaves the base of support far
more often than people's.

How: the pelvis's horizontal path p (下半身's origin, the bone the trunk sits on) and its quick part p - LP(p) (LP:
tools/wb_dynamics.lowpass, a zero-phase 2nd order Butterworth at --cutoff Hz).  The head's pivot (頭's origin) is to move
by -gain (p - LP(p)): the spine joints (腰椎上部, 上半身2 and 胸椎上部 of tools/pmx_spine.py's model; 上半身 and 上半身2
without them) each turn by the same small world tilt about the horizontal axis that moves the head's pivot so (the
levers are the joints' distances under it, summed: a tilt phi moves it by phi x sum (head - joint), whose horizontal part
needs the levers' height alone), and 頭 turns back by the whole bend (its world turn is the dance's).  The chest then
moves by about 0.4 of the head's move (its levers are shorter).  On the song (balance-v3's final feet output; the
measure's segment COMs; people's medians [quartiles] in brackets) the defaults give: the head's slope 0.89 -> 0.31
(0.29 [0.13, 0.42]), its 2-4 Hz response 0.88 -> 0.29 (0.23 [0.06, 0.36]), 1-2 Hz 0.83 -> 0.75 (0.64 [0.52, 0.73]); the
chest's slope 0.93 -> 0.65 (0.70 [0.56, 0.80]); the belly 0.98 -> 0.94 (0.96 [0.86, 1.05]); the bend's median 1.2,
90th percentile 4.6, 99th 9.0 degrees, 43 frames at the bound.  Gain 0.75 with a 6 degree bound (the first try) left
the head at 0.44 (225 frames at the bound); gain 1.0 takes the head to 0.25 and the chest to 0.62 with bigger bends.
The hips themselves move faster than people's (センター's horizontal acceleration at its 90th percentile 5.6 m/s^2,
people's pelvis 3.3), so a head kept as steady as people's needs more bend than theirs: the head's quick move against
the pelvis (over 1.5 Hz, over the trunk's length) at its 90th percentile 2.58 degrees before, 3.08 after, people 1.81
[1.59, 2.07].  The belly, the hips and the legs do not move.
The bend is at most --max-bend degrees in all (MAX_BEND_DEG) and fades out where the trunk lies more than 70 degrees from
upright (the levers' height under 0.3 of their length: no tilt of the spine moves the head sideways there).

Written: the spine joints and 頭, a key on every frame (linear), their positions as the dance had them; every other bone
and key, the morphs and the rest of the file are the dance's own bytes; when nothing is to be done the dance comes back
unchanged.  Report (--report; in short on stdout): the written bones, the parameters, the bend (degrees: quantiles, the
frames at the bound), how the head, the chest, the belly, the arms and the whole COM follow the pelvis (the segments'
COMs as tools/wb_dynamics.py's measure() reads them: per band and as one slope), before and after, and the head's
world turn's largest change (degrees).
"""
import argparse
import importlib.util
import io
import json
import math
import os
import sys
import time
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_wb_layer_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _tool("balance_layer")
D = _tool("wb_dynamics")
KEEP_TOUCHES = True             # the hands that lie on (or near) a part keep their place on it (tools/touch_layer.keep_layer)

FPS = 30.0
GAIN = 0.9                      # the head's pivot moves back by this share of the pelvis's quick part (see the doc)
CUTOFF_HZ = 1.5                 # the pelvis's slower part, which the upper body follows (people: 0.89 at 0.5 Hz, 0.47 at 1.5)
MAX_BEND_DEG = 10.0             # the whole bend of the spine at most (the sum over its joints)
UPRIGHT_SHARE = (0.3, 0.6)      # the levers' height over their length: no tilt under the first, the whole over the second
SPINE = ("腰椎上部", "上半身2", "胸椎上部")
SPINE_PLAIN = ("上半身", "上半身2")
HEAD = "頭"
PELVIS = "下半身"


@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    arrays: dict = None         # per frame: bend_deg [F] (the whole bend), pelvis_quick_cm [F, 2] (x, z), head_target_cm [F, 2]


def qmul(a, b):
    return D.qmul(a, b)


def qconj(q):
    return D.qconj(q)


def qexp(v):
    """unit quaternions [F, 4] of rotation vectors v [F, 3] (radians)"""
    th = np.linalg.norm(v, axis=1)
    k = np.where(th > 1e-12, np.sin(th / 2.0) / np.maximum(th, 1e-300), 0.5)
    return np.concatenate([v * k[:, None], np.cos(th / 2.0)[:, None]], 1)


def bend(body, joints, gain=GAIN, cutoff_hz=CUTOFF_HZ, max_bend_deg=MAX_BEND_DEG):
    """the world tilt (rotation vector, radians, [F, 3], y 0) each spine joint turns by, and a report: the head's pivot
    to move by -gain times the pelvis's quick part on the floor plane"""
    p = body.p(PELVIS)
    hp = p - D.lowpass(p, cutoff_hz)
    want = -gain * hp                                    # the head's pivot's move (units)
    head = body.p(HEAD)
    R = sum(head - body.p(j) for j in joints)            # the levers summed [F, 3]
    ry = R[:, 1]
    up = ry / np.maximum(np.linalg.norm(R, axis=1), 1e-9)
    w = B.smoothstep((up - UPRIGHT_SHARE[0]) / (UPRIGHT_SHARE[1] - UPRIGHT_SHARE[0]))
    ry_safe = np.maximum(ry, 1e-6)
    phi = np.zeros_like(p)
    phi[:, 0] = w * want[:, 2] / ry_safe                 # (phi x R)_z = phi_x R_y
    phi[:, 2] = -w * want[:, 0] / ry_safe                # (phi x R)_x = -phi_z R_y
    total = np.degrees(np.linalg.norm(phi, axis=1)) * len(joints)
    over = total > max_bend_deg
    phi[over] *= (max_bend_deg / total[over])[:, None]
    total = np.degrees(np.linalg.norm(phi, axis=1)) * len(joints)
    rep = {"bend_deg": D._q(total, (0.5, 0.9, 0.99)), "bend_deg_max": round(float(total.max()), 3),
           "bounded_frames": int(over.sum()), "faded_frames": int(np.sum(w < 1.0)),
           "pelvis_quick_cm": D._q(np.linalg.norm(hp[:, [0, 2]], axis=1) * 8.0, (0.5, 0.9, 0.99))}
    rep["_arrays"] = {"bend_deg": total, "pelvis_quick_cm": hp[:, [0, 2]] * 8.0, "head_target_cm": want[:, [0, 2]] * 8.0}
    return phi, rep


def write_bones(motion, body, local):
    """the dance with the bones of `local` (name -> rotations as applied [F, 4]) keyed on every frame (linear), their
    positions as the dance had them; every other key as it was"""
    F = body.F
    tracks = fk.tracks_of(motion)
    linear = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    labels = set()
    new = []
    for name, rot in local.items():
        keys = tracks.get(name) or tracks.get(fk.vmd_name(name)) or []
        frames = [k.frame for k in keys]
        raw = keys[0].raw_name if keys else None
        label = keys[0].name if keys else name
        labels.add(label)
        for f in range(F):
            pos = fk.sample(keys, f, frames)[0] if keys else (0.0, 0.0, 0.0)
            q = fk.stored(tuple(float(v) for v in rot[f]))
            new.append(vmd.BoneKey(label, f, tuple(float(v) for v in pos), q, linear, raw_name=raw))
    kept = [k for k in motion.bones if k.name not in labels]
    return vmd.Motion(model_name=motion.model_name, bones=kept + new, morphs=motion.morphs, cameras=motion.cameras,
                      lights=motion.lights, shadows=motion.shadows, show_iks=motion.show_iks)


def parts(body):
    """the points measured, as tools/wb_dynamics.py's measure() reads them (people and the MV alike): the COMs of the
    head (de Leva's head and neck, vertex to cervicale), of the chest (the upper trunk), of the belly (the middle trunk),
    of the arms and of the whole body"""
    lm, _ = D.landmarks_from_body(body)
    segs = D.segments(lm)
    groups = {"head": ["head"], "chest": ["upper_trunk"], "belly": ["middle_trunk"],
              "arms": [n for n in segs if n.startswith(("upper_arm", "forearm", "hand"))], "com": list(segs)}
    out = {}
    for part, names in groups.items():
        mass = sum(segs[n]["mass"] for n in names)
        out[part] = sum(segs[n]["mass"] * segs[n]["com"] for n in names) / mass
    return out


def response(body, joints=None):
    pel = body.p(PELVIS)
    out = {}
    for name, x in parts(body).items():
        out[name] = dict(D.follow_response(x, pel), slope=round(D.follow_slope(x, pel), 4))
    return out


def layer(model, motion, params=None, log=None, body=None):
    """the dance with the upper body steadier than the hips (Result: motion, report); body: tools/retarget.py's Body of
    the model, with its mesh: the hands near a part of the body keep their place on it (KEEP_TOUCHES; none: as before)"""
    log = log or (lambda *_: None)
    p = {"gain": GAIN, "cutoff_hz": CUTOFF_HZ, "max_bend_deg": MAX_BEND_DEG}
    p.update(params or {})
    t0 = time.time()
    mesh = body
    body = B.Body(model, motion)
    joints = SPINE if all(body.sk.has(n) for n in SPINE) else SPINE_PLAIN
    phi, brep = bend(body, joints, p["gain"], p["cutoff_hz"], p["max_bend_deg"])
    arrays = brep.pop("_arrays")
    report = {"params": p, "frames": body.F, "joints": list(joints), "tilt_deg": brep}
    before = response(body, joints)
    if np.abs(phi).max() < 1e-9:
        report.update({"written": [], "response": {k: {"before": v, "after": v} for k, v in before.items()},
                       "head_turn_change_deg_max": 0.0, "seconds": round(time.time() - t0, 2)})
        return Result(motion, report, arrays)
    delta = qexp(phi)                                    # each joint's world tilt
    local = {}
    n = 0
    for j in list(joints) + [HEAD]:
        parent = body.sk.parent(body.sk.i(j))
        Wp = body.q(body.sk.bones[parent].name) if parent is not None else np.tile([0.0, 0.0, 0.0, 1.0], (body.F, 1))
        Wj = body.q(j)
        Lj = qmul(qconj(Wp), Wj)
        if j == HEAD:
            # the head back by the whole bend under it: its world turn is the dance's
            back = qexp(-phi * n)
            local[j] = qmul(qmul(qmul(qconj(Wp), back), Wp), Lj)
        else:
            local[j] = qmul(qmul(qmul(qconj(Wp), delta), Wp), Lj)
            n += 1
    out = write_bones(motion, body, local)
    if mesh is not None and KEEP_TOUCHES:
        # the bend carries the arms with the chest: a hand on a thigh, the hips or the head would go into it or leave it
        # (the v11 review: the thighs 18 -> 30 frames of an arm over 1 cm in, the wrists 2.0 cm at the median)
        out, report["touches"] = _tool("touch_layer").keep_layer(mesh, motion, mesh, out, log=log)
    after_body = B.Body(model, out)
    after = response(after_body, joints)
    dq = np.abs(np.sum(after_body.q(HEAD) * body.q(HEAD), axis=1))
    report.update({"written": sorted(local), "response": {k: {"before": before[k], "after": after[k]} for k in before},
                   "head_turn_change_deg_max": round(float(np.degrees(2.0 * np.arccos(np.clip(dq, -1.0, 1.0))).max()), 4),
                   "seconds": round(time.time() - t0, 2)})
    log("bend: median %.2f, max %.2f degrees" % (brep["bend_deg"]["p50"], brep["bend_deg_max"]))
    return Result(out, report, arrays)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance", help="the dance (.vmd)")
    ap.add_argument("model", help="the model (.pmx or .pmd) the dance is for")
    ap.add_argument("out", help="the dance with the upper body steadier than the hips (.vmd)")
    ap.add_argument("--report", help="write the full report (JSON)")
    ap.add_argument("--gain", type=float, default=GAIN, help="the head's pivot moves back by this share of the pelvis's quick part")
    ap.add_argument("--cutoff", type=float, default=CUTOFF_HZ, help="Hz: the pelvis's slower part, which the upper body follows")
    ap.add_argument("--max-bend", type=float, default=MAX_BEND_DEG, help="degrees: the whole bend of the spine at most")
    ap.add_argument("--arrays", help="write the per-frame curves (.npz): the bend, the pelvis's quick part, the head's target")
    ap.add_argument("--no-keep-touches", action="store_true",
                    help="let the bend carry a hand that lies on a thigh, the hips or the head (as before v11)")
    args = ap.parse_args(argv)
    try:
        B.check_distinct(args.dance, args.model, args.out, args.report, args.arrays)
        motion = vmd.load(args.dance)
        model = (pmd if args.model.lower().endswith(".pmd") else pmx).load(args.model)
        mesh = None if args.no_keep_touches else _tool("touch_layer").RT.Body.load(args.model)
        result = layer(model, motion, {"gain": args.gain, "cutoff_hz": args.cutoff, "max_bend_deg": args.max_bend}, body=mesh)
        B.write_bytes(os.path.abspath(args.out), vmd.dumps(result.motion))
        report = dict(result.report, dance=os.path.abspath(args.dance), model=os.path.abspath(args.model),
                      out=os.path.abspath(args.out))
        if args.report:
            B.write_bytes(os.path.abspath(args.report), (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        if args.arrays:
            buf = io.BytesIO()
            np.savez_compressed(buf, **result.arrays)
            B.write_bytes(os.path.abspath(args.arrays), buf.getvalue())
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    r = result.report
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "written": len(r["written"]),
                      "bend_deg_max": r["tilt_deg"]["bend_deg_max"],
                      "head_2_4Hz": [r["response"]["head"]["before"].get("2-4Hz"), r["response"]["head"]["after"].get("2-4Hz")],
                      "seconds": r["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
