"""Keep the source's hand touches on Rin's body after the later layers: where the dance's source (the trace on the body
it was made on) holds a hand on its head, chest, belly, hips or a thigh, Rin's hand is put back at the same place of
the same part of her body, and her arms come out of her hard parts -- tools/retarget.py's hands (fix_hands: the hand's
relation to the part, the two hands' gap, then clear_arms) once more, on the dance the later layers made, with the
parts read as MMD poses them (the thighs where the leg IK puts them).

    python tools/touch_layer.py DANCE.vmd SOURCE.vmd SOURCE_BODY MODEL.pmx OUT.vmd [--report r.json]
                                [--no-hands] [--no-clear] [--fk-thighs]

DANCE.vmd is Rin's dance after the layers (tools/hand_layer.py's output; before the gaze, which looks at the hands
where they end up); SOURCE.vmd the trace tools/retarget.py started from, on SOURCE_BODY (what retarget takes: a model or
a .json body); MODEL.pmx Rin.  The layer goes last of the layers that move the arms.

Why (the v11 review, _spike/out/stage6/v11arms/NOTES.md): retarget, first in the chain, keeps 88 % of the frames where
the source's hand touches its body (the hand point within 1 cm of the source's distance on the same part) and leaves 5
frames of an arm more than 1 cm into Rin's hard parts; the layers after it move the arms without the body (the anatomy
layer's elbow swivel into the belly, the motor layer's tracking off the head's side and top, the spine layer's chest
drift and wb's spine tilt carrying a hand that rests on a thigh or the hips into it, the hand layer's fingers into the
head), down to 60 % and 208 frames (tools/retarget_check.py, the merged tree's build I7).  Done once more on the finished
dance, retarget's own correction puts back what every layer before took (the review's estimate: 211 -> 31 frames, 61 ->
86.5 %).

The thighs: tools/retarget.py and tools/retarget_check.py read the parts by forward kinematics, the thigh by 足's own
keys; MMD's leg IK sets 足's turn (the dance keys 足 too: the trace 1,010 / 1,135 keys, the layers' output every frame),
and on Hibikase the two differ by 21 - 22 degrees at the median, 39 - 42 at the 90th percentile (so a hand 3 cm off the
thigh by one reading is 1 - 7 cm off by the other).  Here both bodies' thighs are read as tools/leg_ik.py solves them
(--fk-thighs reads them by their keys, as retarget does).

What it writes: the arm bones 腕, ひじ and 手首 of each side, on the frames fix_hands moves (it keys every frame it moves
and holds the frames around them; their twist bones keep their keys and ride along); every other key, those arm keys
it leaves, the morphs and the rest of the file are the dance's own bytes.  Where nothing is to be done the dance comes
back byte for byte.

The report (--report; in short on stdout): per side the source's touching frames per part, the frames the hands moved
and how far (cm), the clearance's frames in before and after and the deepest, and the wrists' moves (cm).
"""
import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402


def _tool(name):
    spec = importlib.util.spec_from_file_location("_touch_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RT = _tool("retarget")

SIDES = RT.SIDES
UNIT_CM = RT.UNIT_CM
ARM = tuple(s + n for s in SIDES for n in ("腕", "ひじ", "手首"))
THIGHS = {"thigh_左": "左", "thigh_右": "右"}


def default_params():
    return {"hands": True, "clear": True, "ik_thighs": True}


@dataclass
class Result:
    motion: vmd.Motion
    report: dict


def part_frames(body, trk, frames, ik_thighs=True):
    """part -> (world position [F, 3] of the bone it rides, its world turn [F, 4]) of the body's surfaces under the
    tracks: tools/retarget.part_frames, with the thighs where MMD's leg IK puts them (tools/leg_ik.py)"""
    out = dict(RT.part_frames(body, trk, frames))
    if ik_thighs and any(p in out for p in THIGHS):
        legs = RT.leg_pose(body, trk, frames)
        for part, side in THIGHS.items():
            if part in out and side in legs:
                out[part] = (legs[side]["hip"], legs[side]["q_thigh"])
    return out


def keep(src, tgt, src_trk, tgt_trk, frames, params=None, log=None):
    """the target's arm keys (腕, ひじ, 手首 in tgt_trk, changed in place): the hand near a part of the source's body put
    where the source's is relative to that part of the target's, the two hands as far apart as the source's (by the
    shoulders' ratio), then the arms pushed out of the target's head, ribbon, trunk, hips and thighs.  tools/retarget.py's
    fix_hands step by step, with the parts read by part_frames (the thighs by the leg IK); returns the report"""
    p = default_params()
    p.update(params or {})
    log = log or (lambda *_: None)
    F = len(frames)
    rep = {}
    have = {q for q in set(RT.surfaces(src)) & set(RT.surfaces(tgt)) if not RT.soft(q)}
    src_parts = {q: v for q, v in part_frames(src, src_trk, frames, p["ik_thighs"]).items() if q in have}
    tgt_all = part_frames(tgt, tgt_trk, frames, p["ik_thighs"])
    tgt_parts = {q: v for q, v in tgt_all.items() if q in have}
    want, weights = {}, {}
    hands_src = {side: RT.hand_world(src, src_trk, frames, side) for side in SIDES}
    hands_tgt = {side: RT.hand_world(tgt, tgt_trk, frames, side) for side in SIDES}
    for side in SIDES:
        if not all(tgt.has(n) and src.has(n) for n in RT.arm_names(side)):
            continue
        Wt, Rt, pts_t = hands_tgt[side]
        target = Wt.copy()
        total = np.zeros(F)
        acc = np.zeros((F, 3))
        top = np.zeros(F)
        rel = RT.contacts(src, src_trk, frames, side, src_parts, hands_src[side]) if p["hands"] else {}
        loc_t = {k: RT.qrot(RT.qconj(Rt), P - Wt) for k, P in pts_t.items()}
        used = {}
        for part, c in rel.items():
            w = c["w"]
            on = w > 0
            used[part] = int(np.sum(w >= 1.0))
            if not np.any(on):
                continue
            pos, rot = tgt_parts[part]
            Q = RT.mapped_contact(src, tgt, part, c["near"][on], c["d"][on])
            Qw = pos[on] + RT.qrot(rot[on], Q)
            offs = np.stack([loc_t[k][f] for k, f in zip(c["point"][on], np.flatnonzero(on))])
            acc[on] += w[on, None] * (Qw - RT.qrot(Rt[on], offs))
            total[on] += w[on]
            top[on] = np.maximum(top[on], w[on])
        has = total > 0
        target[has] = Wt[has] + top[has, None] * (acc[has] / total[has, None] - Wt[has])
        want[side] = target
        weights[side] = {part: {"w": c["w"], "d": c["d"], "want": np.maximum(c["d"], 0.0) * RT.part_scale(src, tgt, part)}
                         for part, c in rel.items()}
        rep[side] = {"touch_frames": used}
    if p["hands"] and all(s in want for s in SIDES):
        ps = hands_src["左"][2]["palm"] - hands_src["右"][2]["palm"]
        pt = hands_tgt["左"][2]["palm"] - hands_tgt["右"][2]["palm"]
        dist = np.linalg.norm(ps, axis=1) - 2 * RT.HAND_THICK
        w = RT.smoothstep((RT.NEAR - dist) / (RT.NEAR - RT.TOUCH))
        k = np.linalg.norm(tgt.rest("左腕") - tgt.rest("右腕")) / max(np.linalg.norm(src.rest("左腕") - src.rest("右腕")), 1e-6)
        need = (ps * k - pt) * w[:, None]
        want["左"] = want["左"] + 0.5 * need
        want["右"] = want["右"] - 0.5 * need
        rep["hands_together_frames"] = int(np.sum(w >= 1.0))
    for side in list(want):
        Wt, Rt, _ = hands_tgt[side]
        moved = np.linalg.norm(want[side] - Wt, axis=1) > 1e-6
        ap = RT.arm_pose(tgt, tgt_trk, frames, side)
        S, E, Wr = ap[side + "腕"][0], ap[side + "ひじ"][0], ap[side + "手首"][0]
        Es, Ws = RT.arm_ik(S, E, Wr, want[side])
        Es = np.where(moved[:, None], Es, E)
        Ws = np.where(moved[:, None], Ws, Wr)
        loc = RT.arm_locals(tgt, tgt_trk, frames, side, Es, Ws, Rt)
        for name, q in loc.items():
            RT._fit_turns(tgt_trk, name, frames, q, moved)
        rep[side]["moved_frames"] = int(moved.sum())
        rep[side]["moved_cm"] = RT._quant(np.linalg.norm(want[side] - Wt, axis=1)[moved] * UNIT_CM)
    if p["clear"]:
        clr = RT.clear_arms(tgt, tgt_trk, frames, weights, tgt_all, log)
        for side in SIDES:
            rep.setdefault(side, {})["clear"] = clr.get(side)
    return rep


def merged(dance, tracks, names):
    """the dance's keys in their order, those of the bones `names` taken from `tracks` where they changed (a key whose
    turn, place and curve are the dance's own stays the dance's bytes), the keys the tracks added after them"""
    at, made = {}, {}
    for n in names:
        if n in tracks:
            at[n] = {int(f): j for j, f in enumerate(tracks[n].frames)}
            made[n] = tracks[n].keys()
    out, used = [], set()
    for k in dance.bones:
        if k.name not in at:
            out.append(k)
            continue
        if (k.name, k.frame) in used:
            continue                          # a second key on one frame: the track kept the last one
        j = at[k.name].get(k.frame)
        if j is None:
            out.append(k)
            continue
        used.add((k.name, k.frame))
        tr = tracks[k.name]
        q0 = RT.qnorm(np.asarray(fk.applied(k.rotation), dtype=np.float64))
        same_turn = abs(float(np.dot(q0, tr.rot[j]))) > 1.0 - 1e-12
        same_place = np.allclose(np.asarray(k.position, dtype=np.float64), tr.pos[j], atol=1e-9)
        out.append(k if same_turn and same_place and bytes(k.interpolation) == tr.raw[j] else made[k.name][j])
    for n, frames in at.items():
        for f, j in frames.items():
            if (n, f) not in used:
                out.append(made[n][j])
    return out


def layer(dance, source, src_body, tgt_body, params=None, log=None):
    """the dance with the source's touches kept on the target body (Result: motion, report)"""
    log = log or (lambda *_: None)
    p = default_params()
    p.update(params or {})
    t0 = time.time()
    if not dance.bones or not source.bones:
        raise ValueError("the dance and its source need bone keys")
    last = max(max(k.frame for k in dance.bones), max(k.frame for k in source.bones))
    frames = np.arange(0, last + 1)
    trk_s = RT.tracks_of(source.bones)
    trk_t = RT.tracks_of(dance.bones)
    before = {s: RT.world_pose(tgt_body, trk_t, frames, [s + "手首"])[s + "手首"][0] for s in SIDES if tgt_body.has(s + "手首")}
    report = {"params": p, "frames": int(len(frames))}
    report.update(keep(src_body, tgt_body, trk_s, trk_t, frames, p, log))
    after = {s: RT.world_pose(tgt_body, trk_t, frames, [s + "手首"])[s + "手首"][0] for s in before}
    for s in before:
        d = np.linalg.norm(after[s] - before[s], axis=1) * UNIT_CM
        report.setdefault(s, {})["wrist_moved"] = {"frames_over_0.5cm": int(np.sum(d > 0.5)),
                                                   "frames_over_2cm": int(np.sum(d > 2.0)), "cm": RT._quant(d[d > 0.05])}
    keys = merged(dance, trk_t, ARM)
    out = vmd.Motion(model_name=dance.model_name, bones=keys, morphs=list(dance.morphs), cameras=list(dance.cameras),
                     lights=list(dance.lights), shadows=list(dance.shadows), show_iks=list(dance.show_iks))
    report["seconds"] = round(time.time() - t0, 2)
    return Result(out, report)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dance", help="Rin's dance after the layers (.vmd)")
    ap.add_argument("source", help="the trace tools/retarget.py started from (.vmd)")
    ap.add_argument("source_body", help="the body the trace was made on (a model, or retarget's .json body)")
    ap.add_argument("model", help="Rin (.pmx)")
    ap.add_argument("out", help="the dance with the touches kept (.vmd)")
    ap.add_argument("--report", help="write the full report (JSON)")
    ap.add_argument("--no-hands", action="store_true", help="leave the hands' places; only push the arms out of the body")
    ap.add_argument("--no-clear", action="store_true", help="only put the hands back; leave the arms in the body")
    ap.add_argument("--fk-thighs", action="store_true", help="read the thighs by their keys, as tools/retarget.py does")
    args = ap.parse_args(argv)
    try:
        RT.check_distinct(args.dance, args.source, args.source_body, args.model, args.out, args.report)
        params = {"hands": not args.no_hands, "clear": not args.no_clear, "ik_thighs": not args.fk_thighs}
        res = layer(vmd.load(args.dance), vmd.load(args.source), RT.Body.load(args.source_body), RT.Body.load(args.model), params)
        RT.write_bytes(os.path.abspath(args.out), vmd.dumps(res.motion))
        rep = dict(res.report, dance=os.path.abspath(args.dance), source=os.path.abspath(args.source),
                   source_body=os.path.abspath(args.source_body), model=os.path.abspath(args.model), out=os.path.abspath(args.out))
        if args.report:
            RT.write_bytes(os.path.abspath(args.report), (json.dumps(rep, ensure_ascii=False, indent=1, default=float) + "\n").encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    short = {s: {"moved_frames": res.report.get(s, {}).get("moved_frames"),
                 "in_after_over_1cm": (res.report.get(s, {}).get("clear") or {}).get("in_after_over_1cm")} for s in SIDES}
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out), "sides": short, "seconds": res.report["seconds"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
