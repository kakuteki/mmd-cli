"""Render a whole MV in chunks: one chunk per camera shot, each rendered by MMD at a high frame rate with an alpha
channel, folded to 30 fps with motion blur and the look of tools/mv_look.py, checked frame by frame, then joined.

    python tools/mv_chunks.py PLAN.json OUTDIR (--shots CAMERA_REPORT.json | --cuts F [F ...] --last F)
                              [--lead 120] [--fps 240] [--shutter 0.5] [--tag final]

Why chunks: an uncompressed BGRA AVI of a whole song at 240 fps is ~250 GB; one shot of it is ~17 GB.  A seam is
hidden by the camera cut, and every chunk starts --lead frames before its cut so that hair and skirt (physics, which
MMD starts from the rest pose at the first rendered frame) have settled by the cut.  The lead-in is rendered but
not kept: mv_look gets --offset (the first rendered frame), --from (the cut) and --to (the end of the shot).

PLAN.json names the files on the render machine (forward slashes):
    {"mmd": ".../MikuMikuDance.exe", "model": ".../model.pmx", "motions": [".../dance.vmd", ".../lips.vmd"],
     "camera": ".../camera.vmd", "accessories": [".../stage_floor.x"],
     "look": ".../look.json", "cues": ".../cues.json",
     "out": "C:/work/song/out", "scripts": "C:/work/song/mv", "mmd_cli": "C:/work/mmd-cli"}
optional: "menu" (merged over 215 off, 221 off, 282 on; 282 = background black, which gives the AVI its alpha and
must stay on), "size" ([1280, 720]), "codec" ("未圧縮"), "mmd_cli_home", "python" ("python"), "name" ("mv": the
joined video is OUT/<name>_<tag>.mp4).

--shots takes the shot list of tools/make_camera.py's report; --cuts gives the first frame of every chunk after
the first one, and --last the last frame of the song.

Writes into OUTDIR (copy them to "scripts" on the render machine): chunk_<tag>_NN.txt (an `mmd batch` file),
concat_<tag>.txt (the ffmpeg list) and render_<tag>.ps1, the driver for Windows PowerShell 5.1:
    powershell -NoProfile -ExecutionPolicy Bypass -File render_<tag>.ps1 [-Resume]
For each chunk it checks the free disk space for the AVI, runs the batch, folds the AVI, counts the frames of the
mp4 and only then deletes the AVI.  A failure stops the run (exit 1; 3 for the disk) and keeps the AVI.  The joined
video is counted too.  -Resume skips a chunk whose mp4 already has its frame count: only rerun with the same inputs.

The summary is one line of JSON; an error is {"ok": false, "error": ...} with exit code 2.
"""
import argparse
import json
import os
import re
import sys

FPS = 30
DEFAULT_MENU = {"215": "off", "221": "off", "282": "on"}          # axes and floor grid, ground shadow, background black
REQUIRED = ("mmd", "model", "motions", "camera", "look", "out", "scripts", "mmd_cli")
DISK_MARGIN = 2 * 1024 ** 3


def spans_from_report(report):
    """[(cut, end)] from the shots of a tools/make_camera.py report: they must cover frame 0 to the end once"""
    shots = sorted(report["shots"], key=lambda s: s["start"])
    if not shots or shots[0]["start"] != 0:
        raise ValueError("the first shot must start at frame 0")
    spans = []
    for shot, after in zip(shots, shots[1:] + [None]):
        if shot["end"] < shot["start"]:
            raise ValueError("a shot ends before it starts: %s" % shot)
        if after is not None and after["start"] != shot["end"] + 1:
            raise ValueError("the shots leave a gap or overlap between frame %d and frame %d" % (shot["end"], after["start"]))
        spans.append((int(shot["start"]), int(shot["end"])))
    return spans


def spans_from_cuts(cuts, last):
    """[(cut, end)] for chunks starting at frame 0 and at every cut"""
    starts = [0] + list(cuts)
    for a, b in zip(starts, starts[1:]):
        if b <= a:
            raise ValueError("the cuts must rise and come after frame 0: %s" % list(cuts))
    if starts[-1] > last:
        raise ValueError("cut %d is after the last frame %d" % (starts[-1], last))
    return [(a, b - 1) for a, b in zip(starts, starts[1:] + [last + 1])]


def plan_chunks(spans, lead):
    if lead < 0:
        raise ValueError("--lead must not be negative")
    return [{"index": i, "first": max(0, cut - lead), "cut": cut, "end": end, "frames": end - cut + 1}
            for i, (cut, end) in enumerate(spans)]


def avi_bytes(chunk, fps, size):
    """an uncompressed BGRA AVI of the chunk, lead-in included: every frame at 30 fps is fps/30 frames in the AVI"""
    return (chunk["end"] - chunk["first"] + 1) * (fps // FPS) * size[0] * size[1] * 4


def check_plan(plan):
    missing = [k for k in REQUIRED if k not in plan]
    if missing:
        raise ValueError("the plan lacks %s" % ", ".join(missing))
    full = dict(plan)
    if not isinstance(full["motions"], list) or not full["motions"]:
        raise ValueError("the plan needs at least one motion for the model (\"motions\": [...])")
    full["menu"] = dict(DEFAULT_MENU, **{str(k): v for k, v in plan.get("menu", {}).items()})
    for mid, state in full["menu"].items():
        if not mid.isdigit() or state not in ("on", "off"):
            raise ValueError("a menu entry is a menu id and \"on\" or \"off\": %s: %s" % (mid, state))
    if full["menu"]["282"] != "on":
        raise ValueError("menu 282 (background black) must be on: without it the AVI has no alpha for mv_look")
    full.setdefault("accessories", [])
    full.setdefault("size", [1280, 720])
    if len(full["size"]) != 2 or min(full["size"]) <= 0:
        raise ValueError("size is [width, height]")
    full.setdefault("codec", "未圧縮")
    full.setdefault("python", "python")
    full.setdefault("name", "mv")
    full.setdefault("cues", None)
    full.setdefault("mmd_cli_home", None)
    return full


def _line(argv):
    return json.dumps([str(a) for a in argv], ensure_ascii=False)


def batch_text(plan, chunk, fps, avi):
    w, h = plan["size"]
    lines = ["# chunk %02d: frames %d..%d at %d fps; the shot starts at %d (frames before it settle the physics)"
             % (chunk["index"], chunk["first"], chunk["end"], fps, chunk["cut"]),
             _line(["launch", "--headless", "--exe", plan["mmd"]]), _line(["new"])]
    lines += [_line(["menu", "set", mid, state]) for mid, state in plan["menu"].items()]
    lines.append(_line(["model", "load", plan["model"]]))
    lines += [_line(["motion", "load", m, "--frame", 0]) for m in plan["motions"]]
    lines += [_line(["model", "select", "camera"]), _line(["motion", "load", plan["camera"], "--frame", 0])]
    lines += [_line(["accessory", "load", a]) for a in plan["accessories"]]
    lines.append(_line(["render", "avi", avi, "--from", chunk["first"], "--to", chunk["end"], "--fps", fps,
                        "--size", w, h, "--codec", plan["codec"]]))
    lines.append(_line(["quit"]))
    return "\n".join(lines) + "\n"


def _ps(s):
    return "'" + str(s).replace("'", "''") + "'"


def _names(plan, tag, chunk):
    name = "%s_%02d" % (tag, chunk["index"])
    return name, "%s/%s.avi" % (plan["out"], name), "%s/%s.mp4" % (plan["out"], name)


def driver_text(plan, chunks, tag, fps, shutter):
    sub = fps // FPS
    total = sum(c["frames"] for c in chunks)
    joined = "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)
    concat = "%s/concat_%s.txt" % (plan["scripts"], tag)
    py = _ps(plan["python"]) if plan["python"] != "python" else "python"
    lines = ["# %d chunks at %d fps folded to 30 fps (%d subframes, shutter %s), %d frames, joined to %s."
             % (len(chunks), fps, sub, shutter, total, joined),
             "# Written by tools/mv_chunks.py.  -Resume skips a chunk whose mp4 has its frame count (same inputs only).",
             "param([switch]$Resume)",
             "$ErrorActionPreference = 'Continue'",
             "Set-Location -LiteralPath %s" % _ps(plan["mmd_cli"])]
    if plan["mmd_cli_home"]:
        lines.append("$env:MMD_CLI_HOME = %s" % _ps(plan["mmd_cli_home"]))
    lines += ["$out = %s" % _ps(plan["out"]),
              "$look = %s" % _ps(plan["look"]),
              "New-Item -ItemType Directory -Force -Path $out | Out-Null",
              "$sw = [Diagnostics.Stopwatch]::StartNew()",
              "function Count-Frames($path) {",
              "    if (-not (Test-Path -LiteralPath $path)) { return -1 }",
              "    $n = & ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 $path",
              "    if (\"$n\" -match '^\\s*(\\d+)') { return [int]$Matches[1] }",
              "    return -1",
              "}",
              "function Run-Chunk($name, $batch, $json, $avi, $mp4, $want, $need, [string[]]$fold) {",
              "    if ($Resume -and (Count-Frames $mp4) -eq $want) { '{0} skipped: {1} has its {2} frames' -f $name, $mp4, $want; return }",
              "    $free = (Get-Item -LiteralPath $out).PSDrive.Free",
              "    if ($free -lt $need) { '{0} STOP: {1} bytes free, the AVI needs {2} with the margin' -f $name, $free, $need; exit 3 }",
              "    & %s -m mmd_cli --out $json batch $batch | Out-Null" % py,
              "    if ($LASTEXITCODE -ne 0) { '{0} STOP: the MMD batch failed (exit {1}), see {2}' -f $name, $LASTEXITCODE, $json; exit 1 }",
              "    & %s tools/mv_look.py render $avi $look $mp4 @fold | Out-Null" % py,
              "    if ($LASTEXITCODE -ne 0) { '{0} STOP: mv_look failed (exit {1}); the AVI is kept: {2}' -f $name, $LASTEXITCODE, $avi; exit 1 }",
              "    $n = Count-Frames $mp4",
              "    if ($n -ne $want) { '{0} STOP: {1} frames, want {2}; the AVI is kept: {3}' -f $name, $n, $want, $avi; exit 1 }",
              "    Remove-Item -LiteralPath $avi",
              "    '{0} {1} frames (want {2}), {3} s' -f $name, $n, $want, [int]$sw.Elapsed.TotalSeconds",
              "}"]
    for c in chunks:
        name, avi, mp4 = _names(plan, tag, c)
        fold = []
        if plan["cues"]:
            fold += ["--cues", plan["cues"]]
        fold += ["--work", "%s/look_work_%s" % (plan["out"], tag), "--subframes", sub, "--shutter", shutter,
                 "--offset", "%.6f" % (c["first"] / float(FPS)), "--from", "%.6f" % (c["cut"] / float(FPS)),
                 "--to", "%.6f" % ((c["end"] + 1) / float(FPS))]
        lines.append("Run-Chunk %s %s %s %s %s %d %d @(%s)" % (
            _ps(name), _ps("%s/chunk_%s.txt" % (plan["scripts"], name)), _ps("%s/%s.json" % (plan["out"], name)),
            _ps(avi), _ps(mp4), c["frames"], avi_bytes(c, fps, plan["size"]) + DISK_MARGIN,
            ", ".join(_ps(a) for a in fold)))
    lines += ["& ffmpeg -v error -y -f concat -safe 0 -i %s -c copy %s" % (_ps(concat), _ps(joined)),
              "if ($LASTEXITCODE -ne 0) { 'STOP: joining failed (exit {0})' -f $LASTEXITCODE; exit 1 }",
              "$n = Count-Frames %s" % _ps(joined),
              "if ($n -ne %d) { 'STOP: the joined video has {0} frames, want {1}' -f $n, %d; exit 1 }" % (total, total),
              "'joined {0} frames (want {1}), {2} s: {3}' -f $n, %d, [int]$sw.Elapsed.TotalSeconds, %s" % (total, _ps(joined))]
    return "\r\n".join(lines) + "\r\n"


def concat_text(plan, chunks, tag):
    return "".join("file '%s'\n" % _names(plan, tag, c)[2].replace("'", "'\\''") for c in chunks)


def write(plan, chunks, outdir, tag, fps, shutter):
    if fps < FPS or fps % FPS:
        raise ValueError("--fps must be a multiple of 30 (MMD renders 30, 60, 120, 240, 480)")
    if not 0 < shutter <= 1:
        raise ValueError("--shutter is the share of the frame time the shutter is open: 0 < shutter <= 1")
    if not re.match(r"^[A-Za-z0-9_-]+$", tag):
        raise ValueError("--tag goes into file names: letters, digits, _ and - only")
    os.makedirs(outdir, exist_ok=True)
    batches = []
    for c in chunks:
        name, avi, _ = _names(plan, tag, c)
        path = os.path.join(outdir, "chunk_%s.txt" % name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(batch_text(plan, c, fps, avi))
        batches.append(path)
    driver = os.path.join(outdir, "render_%s.ps1" % tag)
    with open(driver, "w", encoding="utf-8-sig", newline="") as f:      # PowerShell 5.1 reads a file without a BOM as ANSI
        f.write(driver_text(plan, chunks, tag, fps, shutter))
    concat = os.path.join(outdir, "concat_%s.txt" % tag)
    with open(concat, "w", encoding="utf-8", newline="\n") as f:
        f.write(concat_text(plan, chunks, tag))
    return {"chunks": len(chunks), "frames": sum(c["frames"] for c in chunks), "fps": fps, "subframes": fps // FPS,
            "shutter": shutter, "largest_avi_gb": round(max(avi_bytes(c, fps, plan["size"]) for c in chunks) / 1e9, 1),
            "spans": [[c["cut"], c["end"]] for c in chunks], "driver": driver, "batches": batches, "concat": concat,
            "joined": "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)}


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plan", help="JSON: the files on the render machine")
    p.add_argument("outdir", help="where to write the batches, the ffmpeg list and the driver")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--shots", help="the report of tools/make_camera.py: one chunk per shot")
    g.add_argument("--cuts", type=int, nargs="*", help="the first frame of every chunk after the first")
    p.add_argument("--last", type=int, help="with --cuts: the last frame of the song")
    p.add_argument("--lead", type=int, default=120, help="frames rendered before each cut for the physics (default 120)")
    p.add_argument("--fps", type=int, default=240, help="the frame rate MMD renders at (default 240)")
    p.add_argument("--shutter", type=float, default=0.5, help="share of each 30 fps frame blurred (default 0.5)")
    p.add_argument("--tag", default="final", help="names the files of this run (default final)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.plan, encoding="utf-8-sig") as f:
            plan = check_plan(json.load(f))
        if args.shots:
            with open(args.shots, encoding="utf-8-sig") as f:
                spans = spans_from_report(json.load(f))
        else:
            if args.last is None:
                raise ValueError("--cuts needs --last (the last frame of the song)")
            spans = spans_from_cuts(args.cuts, args.last)
        result = write(plan, plan_chunks(spans, args.lead), args.outdir, args.tag, args.fps, args.shutter)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
