"""Measure a version of the MV with every idea it took in, against people, in one place (stage 6, 2026-10-17: "build tools
and debug with them instead of looking each time").  Nothing here starts MMD.

    python tools/mv_inspect.py measure SPEC.json --out DIR [--cache DIR] [--parts gravity,feet,...] [--no-figure]
                                       [--size hip|legs|none]
    python tools/mv_inspect.py measure --model M.pmx --motions DANCE.vmd FACE.vmd GAZE.vmd EYE.vmd [--dance D.vmd]
                                       [--reference SPINE.vmd] [--camera CAM.vmd] [--vocal V.flac] [--lines L.tsv]
                                       [--label v9] --out DIR
    python tools/mv_inspect.py outliers DIR [--top 40] [--concept gravity]
    python tools/mv_inspect.py compare DIR_A DIR_B --out DIR
    python tools/mv_inspect.py timeline DIR --out fig.png [--from SECONDS] [--to SECONDS] [--series a,b]
    python tools/mv_inspect.py mark DIR --camera CAM.vmd --out DIR (--picture FRAME=PNG ... | --video V --start S --at T ...)
    python tools/mv_inspect.py pixels pants PICTURE ... --out OUT.json [--box X0 Y0 X1 Y1] [--first-frame F]
    python tools/mv_inspect.py pixels shadow PLAIN_%05d.png SHADED_%05d.png --first A --last B --out OUT.json [--reach 0.95]

measure: a version (its render inputs in their loading order and the model; see tools/mvi/body.py for the spec) is
measured by every part (tools/mvi/: gravity 重力感, feet 足, balance 重心とバランス, upper 上体, arms 腕と指, eyes 目,
mouth 口, skirt スカートの危なさ, spikes 突起, retarget 体の触れ), each measure against people's values (tools/mvi/human.json: FineDance
K-pop, choreography and jazz, 62 sequences, the median and quartiles, from the earlier work's outputs) or a rule of the
project, judged 中 / 上へ外 / 下へ外 (the human baseline's p31_table rule).  DIR gets report.json (everything),
report.md (the table), outliers.md and outliers.csv (the places outside, the heaviest first, with times, and the
heaviest of each idea; which places are listed: tools/mvi/report.py),
events.csv (every place, listed or not), series.npz (the per-frame curves), marks.npz (the COM, the ZMP and the base of
support per frame, for `mark`) and timeline.png (the curves along the song).  The heavy arrays (the forward kinematics,
MMD's IK, the shoes) are kept in --cache (default DIR/cache) by the inputs' md5 and the md5 of the code they come from
(tools/mvi/body.py CACHE_CODE).

size: people's values were measured on one body (FineDance's: SMPL-X's neutral body, its hip joints 83.98 cm over the
ball of the foot, legs 78.3 cm, the two sides' mean); Sour's Rin's hips stand about as high over her soles (84.1 cm) on
shorter legs (71.2 cm).  The measures of lengths (tools/mvi/base.SIZE_ALIGNED: the hover, the slides, the COM over the
standing foot, the pelvis's sink and bob) are measured again with her body made as large as people's (tools/mvi/
shared.Scaled, the timing kept) and judged too: each such row gets "size" {value, judge} beside its own value and
judgement, which stay what they were; report.json's "size" says by what and by how much.  --size hip (the default:
gait's usual normalisation, the hip's height over the floor; the coordinator's choice of 2026-10-17) makes her hips as
high over her floor (her soles at rest) as people's over theirs (the ball of the foot), --size legs makes her legs
(hip to knee to ankle) people's, --size none measures nothing again.  The places, the timeline and the judgement that
lists them stay the raw ones.

compare: two measured versions in one table, judged 入った / 中のまま / 近づいた / 遠ざかった / 直しすぎ / 変わらず with
the distances outside people (A -> B), and the places outside that are new in B and gone from A (a place B still has,
unlisted because B's measure went inside people, is counted apart, not as gone).

mark: the measured version's marks (the COM and its floor point, the base of support, the ZMP, the listed places of the
frame) drawn on pictures rendered through the camera of the VMD given (the projection was checked on the still front
camera's renders by wbbalance and on a moving close-up camera's by the review of 10-17; a camera with a roll is
refused).

pixels: measures of rendered pictures only (the underwear pixels of the green copy, the floor shadow's flicker).
Exit status: 0, 1 when a part failed (the others are written), 2 for wrong input.
"""
import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from mvi import base, body, marks as MK, pixels as PX, plot as PL, report as RP, shared  # noqa: E402
from mvi import arms, balance, eyes, feet, gravity, mouth, retarget, skirt, spikes, upper  # noqa: E402

PARTS = [("gravity", gravity), ("feet", feet), ("balance", balance), ("upper", upper), ("arms", arms), ("eyes", eyes),
         ("mouth", mouth), ("skirt", skirt), ("spikes", spikes), ("retarget", retarget)]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def spec_of(args):
    if args.spec:
        spec = json.load(open(args.spec, encoding="utf-8"))
    else:
        if not args.model or not args.motions:
            raise ValueError("measure needs a SPEC.json, or --model and --motions")
        spec = {"model": args.model, "motions": args.motions}
    for k in ("dance", "reference", "camera", "vocal", "lines", "label"):
        v = getattr(args, k, None)
        if v:
            spec[k] = v
    return spec


SIZE_PARTS = ("gravity", "feet", "balance")       # the parts with measures in base.SIZE_ALIGNED
SIZES = ("hip", "legs", "none")                    # --size: by the hip's height over the floor (default), by the legs, not


def _size_by(m, rest, by):
    """(rep["size"] without "what", the scale) for `by`; ValueError with the reason when it cannot be had"""
    if by == "hip":
        try:
            floor = m.floor()
        except Exception as e:                              # a model without the leg rig or the shoes sink_check reads
            raise ValueError("the floor her soles stand on at rest could not be read (%s)" % e)
        hip, s = base.hip_cm(rest, floor), base.hip_scale(rest, floor)
        if s is None:
            raise ValueError("the model's hips (足) are missing or not over the floor (%s)" % floor)
        return {"by": "hip", "hip_cm": round(hip, 3), "people_hip_cm": round(base.people_hip_cm(), 3),
                "floor_y": round(float(floor), 5), "scale": round(s, 5)}, s
    leg, s = base.leg_cm(rest), base.size_scale(rest)
    if s is None:
        raise ValueError("the model's legs (足・ひざ・足首) are missing")
    return {"by": "legs", "leg_cm": round(leg, 3), "people_leg_cm": round(base.people_leg_cm(), 3), "scale": round(s, 5)}, s


def size_aligned(m, rep, parts=None, by="hip"):
    """the size-aligned values (the module's doc): rep's rows of base.SIZE_ALIGNED get "size" {value, judge} from the
    parts measured again on m.scaled(scale), the scale by the hip's height over the floor (by "hip": base.hip_scale) or by
    the legs (by "legs": base.size_scale); rep["size"] says by what and by how much, or why not"""
    try:
        rest = m.rest()[0]
    except Exception as e:                                   # a model without the legs a05 reads
        rep["size"] = {"by": None, "why": str(e)}
        return rep
    try:
        info, s = _size_by(m, rest, by)
    except ValueError as e:
        rep["size"] = {"by": None, "why": str(e)}
        return rep
    todo = [(name, part) for name, part in PARTS
            if name in SIZE_PARTS and not (parts and name not in parts) and name not in rep["failed"]]
    if not todo:                                             # (--parts skirt: nothing to measure again, say nothing)
        rep["size"] = {"by": None, "why": "no part with measures of lengths (%s) was measured" % ", ".join(SIZE_PARTS)}
        return rep
    ms = m.scaled(s)
    rows = {r["id"]: r for r in rep["measures"]}
    for name, part in todo:
        t = time.time()
        try:
            res = part.measure(ms)
        except Exception:
            rep["failed"]["size " + name] = traceback.format_exc()
            log("size", name, "FAILED")
            log(rep["failed"]["size " + name])
            continue
        n = 0
        for r2 in res["rows"]:
            r = rows.get(r2["id"])
            if r is not None and r2["id"] in base.SIZE_ALIGNED and r.get("value") is not None:
                r["size"] = {"value": r2["value"], "judge": r2["judge"]}
                n += 1
        log("size", name, "%.1f s" % (time.time() - t), n, "measures")
    if info["by"] == "hip":
        what = ("her body made %.4f times as large (people's hips %.2f cm over the ball of the foot / hers %.2f cm over her "
                "soles at rest, y %.4f), the timing kept: the measures of lengths (base.SIZE_ALIGNED) measured again"
                % (s, info["people_hip_cm"], info["hip_cm"], info["floor_y"]))
    else:
        what = ("her body made %.4f times as large (people's legs %.2f cm / hers %.2f cm), the timing kept: "
                "the measures of lengths (base.SIZE_ALIGNED) measured again" % (s, info["people_leg_cm"], info["leg_cm"]))
    rep["size"] = dict(info, what=what)
    return rep


def measure(spec, out_dir, cache=None, parts=None, figure=True, size="hip"):
    """measure one version; returns (report, failed)"""
    ver = body.Version(spec, cache=cache or os.path.join(out_dir, "cache"))
    m = shared.Measured(ver)
    rep = {"tool": "mv_inspect", "format": RP.FORMAT, "label": ver.label, "made": RP.made(), "inputs": ver.inputs(),
           "spec": ver.spec, "first": ver.first, "last": ver.last, "frames": ver.frames, "measures": [], "events": [],
           "series": {}, "failed": {}}
    arrays = {}
    for name, part in PARTS:
        if parts and name not in parts:
            continue
        t = time.time()
        try:
            res = part.measure(m)
        except Exception:                                    # one part's failure leaves the others' measures
            rep["failed"][name] = traceback.format_exc()
            log("part", name, "FAILED")
            log(rep["failed"][name])
            continue
        rep["measures"] += res["rows"]
        rep["events"] += res["events"]
        for key, s in res["series"].items():
            meta = {k: v for k, v in s.items() if k not in ("y", "air")}
            meta["concept"] = part.CONCEPT
            rep["series"][key] = meta
            arrays[key] = np.asarray(s["y"], dtype=np.float32)
            if "air" in s:
                arrays["air"] = np.asarray(s["air"], dtype=bool)
        log("part", name, "%.1f s" % (time.time() - t), len(res["rows"]), "measures", len(res["events"]), "places")
    if size not in SIZES:
        raise ValueError("--size is one of %s, not %r" % ("|".join(SIZES), size))
    if size != "none":
        size_aligned(m, rep, parts, by=size)
    RP.mark_listed(rep)
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "series.npz"), **arrays)
    if "balance" in (parts or [p for p, _ in PARTS]) and "balance" not in rep["failed"]:
        MK.save_points(os.path.join(out_dir, "marks.npz"), m.wb()[1])
    paths = RP.write(rep, out_dir)
    if figure and arrays:
        try:
            PL.figure(rep, arrays, os.path.join(out_dir, "timeline.png"))
        except Exception:
            rep["failed"]["figure"] = traceback.format_exc()
            log("figure FAILED", rep["failed"]["figure"])
            paths = RP.write(rep, out_dir)
    return rep, paths


def _report_dir(path):
    return path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))


def cmd_measure(args):
    spec = spec_of(args)
    parts = [p.strip() for p in args.parts.split(",")] if args.parts else None
    unknown = [p for p in (parts or []) if p not in dict(PARTS)]
    if unknown:
        raise ValueError("unknown parts: %s (the parts: %s)" % (", ".join(unknown), ", ".join(p for p, _ in PARTS)))
    rep, paths = measure(spec, args.out, args.cache, parts, figure=not args.no_figure, size=args.size)
    listed = sum(1 for e in rep["events"] if e.get("listed"))
    outside = sum(1 for r in rep["measures"] if r.get("judge") and r["judge"]["side"] != 0)
    print(json.dumps({"ok": not rep["failed"], "label": rep["label"], "measures": len(rep["measures"]), "outside": outside,
                      "places_listed": listed, "failed": sorted(rep["failed"]), "out": os.path.abspath(args.out)}, ensure_ascii=True))
    return 1 if rep["failed"] else 0


def cmd_outliers(args):
    rep = RP.load(args.report)
    if args.concept:
        rep = dict(rep, events=[e for e in rep["events"] if e["concept"] == args.concept])
    text = RP.timeline_md(rep, args.top)
    tty = getattr(sys.stdout, "isatty", lambda: False)()
    if hasattr(sys.stdout, "buffer") and not tty:          # a file or a pipe: UTF-8 like the files (u/s² is not in cp932)
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.flush()
    else:                                                   # a console (Windows writes it as Unicode) or a test's buffer
        sys.stdout.write(text)
    return 0


def cmd_compare(args):
    a, b = RP.load(args.a), RP.load(args.b)
    c = RP.compare(a, b)
    paths = RP.write_compare(c, args.out)
    words = {}
    for r in c["rows"]:
        w = (r.get("word") or {}).get("word")
        if w:
            words[w] = words.get(w, 0) + 1
    print(json.dumps({"ok": True, "a": c["a"], "b": c["b"], "words": words, "new": len(c["new"]), "gone": len(c["gone"]),
                      "unlisted_now": len(c["unlisted_now"]), "listed_now": len(c["listed_now"]),
                      "out": {k: os.path.abspath(v) for k, v in paths.items()}}, ensure_ascii=True))
    return 0


def cmd_timeline(args):
    d = _report_dir(args.report)
    rep = RP.load(args.report)
    z = np.load(os.path.join(d, "series.npz"))
    series = {k: z[k] for k in z.files}
    names = [s.strip() for s in args.series.split(",")] if args.series else None
    PL.figure(rep, series, args.out, names, getattr(args, "from"), args.to)
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out)}, ensure_ascii=True))
    return 0


def cmd_mark(args):
    d = _report_dir(args.report)
    rep = RP.load(args.report)
    pts = os.path.join(d, "marks.npz")
    if not os.path.isfile(pts):
        raise ValueError("no marks.npz beside the report (measure with the balance part)")
    pictures = []
    for item in args.picture or []:
        f, p = item.split("=", 1)
        pictures.append((int(f), p))
    if args.video:
        if args.start is None or not args.at:
            raise ValueError("--video needs --start (the song's seconds at the video's first frame) and --at")
        os.makedirs(args.out, exist_ok=True)
        for t in args.at:
            frame = int(round(t * base.FPS))
            path = os.path.join(args.out, "frame_%05d.png" % frame)
            MK.frame_of_video(args.video, t - args.start, path)
            pictures.append((frame, path))
    if not pictures:
        raise ValueError("mark needs --picture FRAME=PNG or --video with --start and --at")
    res = MK.mark(rep, pts, args.camera, pictures, args.out)
    print(json.dumps({"ok": True, "marked": [r["out"] for r in res]}, ensure_ascii=True))
    return 0


def cmd_pixels(args):
    if args.what == "pants":
        paths = PX.expand(args.inputs)
        res = PX.pants(paths, args.box, args.first_frame)
    else:
        if len(args.inputs) != 2 or args.first is None or args.last is None:
            raise ValueError("pixels shadow needs PLAIN_PATTERN SHADED_PATTERN --first A --last B")
        res = PX.shadow(args.inputs[0], args.inputs[1], args.first, args.last, reach=args.reach)
    PX.write(res, args.out)
    print(json.dumps({"ok": True, "values": {r["id"]: r["value"] for r in res["rows"]}, "judge": res["rows"][0]["judge"],
                      "places": len(res["events"]), "out": os.path.abspath(args.out)}, ensure_ascii=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("measure", help="measure one version")
    p.add_argument("spec", nargs="?", help="the version (JSON, see tools/mvi/body.py)")
    p.add_argument("--model")
    p.add_argument("--motions", nargs="+")
    p.add_argument("--dance")
    p.add_argument("--reference")
    p.add_argument("--camera")
    p.add_argument("--vocal")
    p.add_argument("--lines")
    p.add_argument("--label")
    p.add_argument("--out", required=True)
    p.add_argument("--cache")
    p.add_argument("--parts", help="comma-separated parts (default: all)")
    p.add_argument("--no-figure", action="store_true")
    p.add_argument("--size", choices=SIZES, default="hip",
                   help="the measures of lengths also measured with her body as large as people's: by the hip's height over "
                        "the floor (hip, the default) or by the legs (legs); none: not (the module's doc)")
    p = sub.add_parser("outliers", help="the places outside of a measured version")
    p.add_argument("report")
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--concept")
    p = sub.add_parser("compare", help="two measured versions")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--out", required=True)
    p = sub.add_parser("timeline", help="the time figure of a measured version")
    p.add_argument("report")
    p.add_argument("--out", required=True)
    p.add_argument("--from", type=float)
    p.add_argument("--to", type=float)
    p.add_argument("--series")
    p = sub.add_parser("mark", help="the marks on rendered pictures")
    p.add_argument("report")
    p.add_argument("--camera", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--picture", action="append", help="FRAME=PNG (repeat)")
    p.add_argument("--video")
    p.add_argument("--start", type=float, help="the song's seconds at the video's first frame")
    p.add_argument("--at", type=float, nargs="+", help="song seconds to mark")
    p = sub.add_parser("pixels", help="measures of rendered pictures")
    p.add_argument("what", choices=("pants", "shadow"))
    p.add_argument("inputs", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--box", type=float, nargs=4)
    p.add_argument("--first-frame", type=int)
    p.add_argument("--first", type=int)
    p.add_argument("--last", type=int)
    p.add_argument("--reach", type=float, default=0.95, help="shadow: the pixels whose ratio falls under this at some frame")
    args = ap.parse_args(argv)
    try:
        return {"measure": cmd_measure, "outliers": cmd_outliers, "compare": cmd_compare, "timeline": cmd_timeline,
                "mark": cmd_mark, "pixels": cmd_pixels}[args.cmd](args)
    except (ValueError, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
