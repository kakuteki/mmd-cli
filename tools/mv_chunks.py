"""Render a whole MV in chunks: one chunk per camera shot, each rendered by MMD at a high frame rate with an alpha
channel, folded to 30 fps with motion blur and the look of tools/mv_look.py, checked frame by frame, then joined.

    python tools/mv_chunks.py PLAN.json OUTDIR (--shots CAMERA_REPORT.json | --cuts F [F ...] --last F)
                              [--lead 120] [--fps 240] [--shutter 0.5] [--tag final]

Why chunks: an uncompressed BGRA AVI at 240 fps and 1280x720 takes 29.5 MB per frame of the song (228 GB for a song
of 4 minutes 18 seconds), one shot of it some 17 GB at most.  A seam is hidden by the camera cut, and every chunk starts
--lead frames before its cut so that hair and skirt (physics, which MMD starts from the rest pose at the first rendered
frame) have settled by the cut.  The lead-in is rendered but not kept: mv_look gets --offset (the first rendered
frame), --from (the cut) and --to (the end of the shot), and goes on with the light loop and a running flare.

PLAN.json names the files on the render machine, as absolute paths with forward slashes:
    {"mmd": ".../MikuMikuDance.exe", "model": ".../model.pmx", "motions": [".../dance.vmd", ".../lips.vmd"],
     "camera": ".../camera.vmd", "look": ".../look.json",
     "out": "C:/work/song/out", "scripts": "C:/work/song/mv", "mmd_cli": "C:/work/mmd-cli"}
optional: "accessories" ([]), "cues" (none), "menu" (merged over 215 off, 221 off, 282 on; 282 = background black,
which gives the AVI its alpha and must stay on), "size" ([1280, 720]), "codec" ("未圧縮"), "avi_bytes_per_pixel" (4
for the uncompressed BGRA; another codec needs it, measured on one AVI), "mmd_cli_home", "python" ("python"),
"name" ("mv": the joined video is OUT/<name>_<tag>.mp4).  An entry this tool does not know is refused.

--shots takes the shot list of tools/make_camera.py's report (of the run that wrote the camera, or of one with the same
shots: --handheld does not move them); --cuts gives the first frame of every chunk after the first one, and --last
the last frame of the song.  A chunk has at least 3 frames (shorter ones break the timestamps of the join).

Writes into OUTDIR (copy all of it to "scripts" on the render machine): chunk_<tag>_NN.txt (an `mmd batch` file),
concat_<tag>.txt (the ffmpeg list) and render_<tag>.ps1, the driver for Windows PowerShell 5.1:
    powershell -NoProfile -ExecutionPolicy Bypass -File render_<tag>.ps1 [-Resume]
For each chunk the driver checks that the batch is the one it was written with, removes what an earlier attempt left of
the chunk, checks the free space for the AVI, runs the batch, folds the AVI (keeping mv_look's answer as
<mp4>.look.json), counts the frames of the mp4, notes the recipe of the chunk beside it (<mp4>.recipe) and only then
deletes the AVI.  A failure stops the run (exit 1; 3 for the disk) and keeps the AVI.  The joined video is counted too.
-Resume skips a chunk whose mp4 has its frame count and was made from the same recipe: the same batch, look and fold,
and the same size and time of every file it watches: the motions, camera, look and cues, everything under the folders of
the model and of the accessories (textures, toons, spheres), mmd_cli and tools/ on the render machine, and MMD itself.
It does not see fonts (mv_text finds them on the render machine) or MMD's settings: after changing those, render
without -Resume.  The output and scripts folders may not lie in a watched folder.  Before chunk 0 the driver checks the
look with `mv_look.py layers`, so a wrong look stops the run before MMD has rendered anything.

The summary is one line of JSON; an error is {"ok": false, "error": ...} with exit code 2.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

FPS = 30
MMD_FPS = (30, 60, 120, 240, 480)
MIN_FRAMES = 3
UNCOMPRESSED = "未圧縮"
DEFAULT_MENU = {"215": "off", "221": "off", "282": "on"}          # axes and floor grid, ground shadow, background black
REQUIRED = ("mmd", "model", "motions", "camera", "look", "out", "scripts", "mmd_cli")
OPTIONAL = ("accessories", "cues", "menu", "size", "codec", "avi_bytes_per_pixel", "mmd_cli_home", "python", "name")
PATHS = ("mmd", "model", "camera", "look", "out", "scripts", "mmd_cli")
DISK_MARGIN = 2 * 1024 ** 3
PS_QUOTES = re.compile("['\u2018\u2019\u201a\u201b]")      # Windows PowerShell takes each of these for a single quote
NAME = re.compile(r"[A-Za-z0-9_-]+")
ABSOLUTE = re.compile(r"([A-Za-z]:[\\/]|[\\/]{2}[^\\/])")
MAX_BYTES_PER_PIXEL = 1e6               # no AVI comes near; it keeps the arithmetic finite


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _absolute(value):
    return isinstance(value, str) and ABSOLUTE.match(value) is not None


def _folder_of(path):
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[0]


def watched_folders(plan):
    """the folders -Resume reads through: the model's and the accessories' (what they load: textures, toons, spheres),
    and mmd_cli's code"""
    folders = [_folder_of(plan["model"])] + [_folder_of(a) for a in plan["accessories"]]
    folders += ["%s/%s" % (plan["mmd_cli"].replace("\\", "/").rstrip("/"), name) for name in ("mmd_cli", "tools")]
    unique = []
    for f in folders:
        if f not in unique:
            unique.append(f)
    return unique


def _inside(path, folder):
    a, b = path.replace("\\", "/").rstrip("/").lower(), folder.replace("\\", "/").rstrip("/").lower()
    return a == b or a.startswith(b + "/")


def spans_from_report(report):
    """[(cut, end)] from the shots of a tools/make_camera.py report: they must cover frame 0 to the end once"""
    shots = report.get("shots") if isinstance(report, dict) else None
    if not isinstance(shots, list) or not shots:
        raise ValueError("the camera report has no list of shots (\"shots\": [{\"start\": F, \"end\": F}, ...])")
    for shot in shots:
        for key in ("start", "end"):
            if not isinstance(shot, dict) or not _whole(shot.get(key)):
                raise ValueError("a shot's %s is not a whole frame number: %r" % (key, shot))
    shots = sorted(shots, key=lambda s: s["start"])
    if shots[0]["start"] != 0:
        raise ValueError("the first shot must start at frame 0")
    spans = []
    for shot, after in zip(shots, shots[1:] + [None]):
        if shot["end"] < shot["start"]:
            raise ValueError("a shot ends before it starts: %s" % shot)
        if after is not None and after["start"] != shot["end"] + 1:
            raise ValueError("the shots leave a gap or overlap between frame %d and frame %d" % (shot["end"], after["start"]))
        spans.append((shot["start"], shot["end"]))
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
    chunks = [{"index": i, "first": max(0, cut - lead), "cut": cut, "end": end, "frames": end - cut + 1}
              for i, (cut, end) in enumerate(spans)]
    for c in chunks:
        if c["frames"] < MIN_FRAMES:
            # review 10: joined with -c copy, a chunk of 1 or 2 frames puts the timestamps out of order (a frame read
            # three times, the next one lost, all later ones a frame late) while every count still matches
            raise ValueError("chunk %d (frames %d to %d) has %d frame(s): a chunk needs at least %d"
                             % (c["index"], c["cut"], c["end"], c["frames"], MIN_FRAMES))
    return chunks


def avi_bytes(chunk, fps, size, bytes_per_pixel=4):
    """the AVI of the chunk, lead-in included: every frame at 30 fps is fps/30 frames in the AVI"""
    return int((chunk["end"] - chunk["first"] + 1) * (fps // FPS) * size[0] * size[1] * bytes_per_pixel)


def check_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("the plan is a JSON object of named entries")
    missing = [k for k in REQUIRED if k not in plan]
    if missing:
        raise ValueError("the plan lacks %s" % ", ".join(missing))
    unknown = sorted(k for k in plan if k not in REQUIRED + OPTIONAL)
    if unknown:
        raise ValueError("the plan has entries this tool does not know: %s (it knows %s)"
                         % (", ".join(unknown), ", ".join(REQUIRED + OPTIONAL)))
    full = dict(plan)
    for key in PATHS:
        if not _absolute(full[key]):
            raise ValueError("%s is an absolute path on the render machine (C:/... or //host/...), not %r" % (key, full[key]))
    if not isinstance(full["motions"], list) or not full["motions"] or not all(_absolute(m) for m in full["motions"]):
        raise ValueError("motions is a list of at least one absolute path: the motions for the model")
    full.setdefault("accessories", [])
    if not isinstance(full["accessories"], list) or not all(_absolute(a) for a in full["accessories"]):
        raise ValueError("accessories is a list of absolute paths")
    for key in ("cues", "mmd_cli_home"):
        full.setdefault(key, None)
        if full[key] is not None and not _absolute(full[key]):
            raise ValueError("%s is an absolute path or null, not %r" % (key, full[key]))
    menu = full.get("menu", {})
    if not isinstance(menu, dict):
        raise ValueError("menu is an object of menu ids, each \"on\" or \"off\"")
    merged = dict(DEFAULT_MENU)
    for mid, state in menu.items():
        if not re.fullmatch(r"\d+", str(mid)) or state not in ("on", "off"):
            raise ValueError("a menu entry is a menu id and \"on\" or \"off\", not %r: %r" % (mid, state))
        merged[str(int(mid))] = state                       # "0282" is menu 282 to mmd
    if merged["282"] != "on":
        raise ValueError("menu 282 (background black) must be on: without it the AVI has no alpha for mv_look")
    full["menu"] = merged
    full.setdefault("size", [1280, 720])
    if not isinstance(full["size"], list) or len(full["size"]) != 2 or not all(_whole(v) and v > 0 for v in full["size"]):
        raise ValueError("size is [width, height] in whole pixels, not %r" % (full["size"],))
    full.setdefault("codec", UNCOMPRESSED)
    if not isinstance(full["codec"], str) or not full["codec"]:
        raise ValueError("codec is the name of a codec MMD offers for the AVI")
    if "avi_bytes_per_pixel" not in full:
        if full["codec"] != UNCOMPRESSED:
            raise ValueError("with the codec %r the plan needs avi_bytes_per_pixel (an AVI's bytes / (frames x width x "
                             "height), measured on one): the free space is checked against it" % full["codec"])
        full["avi_bytes_per_pixel"] = 4
    bpp = full["avi_bytes_per_pixel"]
    if isinstance(bpp, bool) or not isinstance(bpp, (int, float)) or not 0 < bpp <= MAX_BYTES_PER_PIXEL:
        raise ValueError("avi_bytes_per_pixel is a number above 0 and up to %g, not %r" % (MAX_BYTES_PER_PIXEL, bpp))
    full.setdefault("python", "python")
    if not isinstance(full["python"], str) or not full["python"]:
        raise ValueError("python is the command or the path of the Python on the render machine")
    full.setdefault("name", "mv")
    if not isinstance(full["name"], str) or not NAME.fullmatch(full["name"]):
        raise ValueError("name goes into a file name: letters, digits, _ and - only")
    for key in ("out", "scripts"):
        for folder in watched_folders(full):
            if _inside(full[key], folder):
                raise ValueError("%s (%s) is inside %s, which -Resume watches: every chunk written there would look like a "
                                 "changed input.  Put it elsewhere" % (key, full[key], folder))
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
    """a PowerShell string literal of s: every character PowerShell takes for a single quote is doubled"""
    return "'" + PS_QUOTES.sub(lambda m: m.group(0) * 2, str(s)) + "'"


def _names(plan, tag, chunk):
    name = "%s_%02d" % (tag, chunk["index"])
    return name, "%s/%s.avi" % (plan["out"], name), "%s/%s.mp4" % (plan["out"], name)


def fold_args(plan, tag, chunk, fps, shutter):
    """what mv_look gets after `render AVI LOOK MP4` for the chunk"""
    fold = ["--cues", plan["cues"]] if plan["cues"] else []
    fold += ["--work", "%s/look_work_%s" % (plan["out"], tag), "--subframes", fps // FPS, "--shutter", shutter,
             "--offset", "%.6f" % (chunk["first"] / float(FPS)), "--from", "%.6f" % (chunk["cut"] / float(FPS)),
             "--to", "%.6f" % ((chunk["end"] + 1) / float(FPS))]
    return [str(a) for a in fold]


def recipe(plan, tag, chunk, fps, shutter):
    """what makes the chunk's mp4 apart from the contents of the input files: its batch, its look and its fold"""
    parts = [batch_text(plan, chunk, fps, _names(plan, tag, chunk)[1]), plan["look"]] + fold_args(plan, tag, chunk, fps, shutter)
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def driver_text(plan, chunks, tag, fps, shutter, batch_hashes):
    sub = fps // FPS
    total = sum(c["frames"] for c in chunks)
    joined = "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)
    concat = "%s/concat_%s.txt" % (plan["scripts"], tag)
    py = "python" if plan["python"] == "python" else _ps(plan["python"])
    inputs = [plan["mmd"], plan["model"]] + plan["motions"] + [plan["camera"]] + plan["accessories"] + [plan["look"]]
    inputs += [plan["cues"]] if plan["cues"] else []
    work = "%s/look_work_%s" % (plan["out"], tag)
    lines = ["# %d chunks at %d fps folded to 30 fps (%d subframes, shutter %s), %d frames, joined to %s."
             % (len(chunks), fps, sub, shutter, total, joined),
             "# Written by tools/mv_chunks.py.  -Resume skips a chunk whose mp4 has its frame count and was made from the",
             "# same recipe (batch, look and fold) and the same watched files (size and time): see <mp4>.recipe beside it.",
             "# It does not see fonts or MMD's settings: after changing those, run without -Resume.",
             "param([switch]$Resume)",
             "$ErrorActionPreference = 'Continue'",
             "Set-Location -LiteralPath %s" % _ps(plan["mmd_cli"])]
    if plan["mmd_cli_home"]:
        lines.append("$env:MMD_CLI_HOME = %s" % _ps(plan["mmd_cli_home"]))
    lines += ["$out = %s" % _ps(plan["out"]),
              "$look = %s" % _ps(plan["look"]),
              "$inputs = @(%s)" % ", ".join(_ps(i) for i in inputs),
              "$folders = @(%s)" % ", ".join(_ps(f) for f in watched_folders(plan)),
              "New-Item -ItemType Directory -Force -Path $out | Out-Null",
              "if (-not (Test-Path -LiteralPath $out -PathType Container)) { 'STOP: could not make the output folder {0}' -f $out; exit 1 }",
              "$sw = [Diagnostics.Stopwatch]::StartNew()",
              "function Invoke-Native {",
              "    # an external command, with the last exit code cleared first: one that is not found leaves it as it was",
              "    $global:LASTEXITCODE = $null",
              "    $exe, $rest = $args",
              "    & $exe @rest",
              "}",
              "if (-not ('MvChunks.Disk' -as [type])) {",
              "    Add-Type -Namespace MvChunks -Name Disk -MemberDefinition '[DllImport(\"kernel32.dll\", CharSet = CharSet.Unicode, "
              "SetLastError = true)] public static extern bool GetDiskFreeSpaceEx(string folder, out ulong available, out ulong total, "
              "out ulong free);'",
              "}",
              "function Get-FreeBytes($folder) {",
              "    # the free space of the volume that holds the folder, for a UNC path or a mounted folder too (PSDrive is not)",
              "    $a = [uint64]0; $t = [uint64]0; $f = [uint64]0",
              "    if ([MvChunks.Disk]::GetDiskFreeSpaceEx($folder, [ref]$a, [ref]$t, [ref]$f)) { return $a }",
              "    return -1",
              "}",
              "$files = @($inputs | ForEach-Object { $i = Get-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue; "
              "if ($i) { '{0}|{1}|{2}' -f $_, $i.Length, $i.LastWriteTimeUtc.Ticks } else { '{0}|missing' -f $_ } })",
              "$files += @($folders | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -File -Force -ErrorAction SilentlyContinue } | "
              "Sort-Object FullName | ForEach-Object { '{0}|{1}|{2}' -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks })",
              "$stamp = $files -join \"`n\"",
              "$check = Invoke-Native %s tools/mv_look.py layers $look %s --size %dx%d --fps 30" % (py, _ps(work), plan["size"][0], plan["size"][1]),
              "if ($LASTEXITCODE -ne 0) { 'STOP: the look does not work: {0} (mv_look layers, exit {1})' -f $look, $LASTEXITCODE; $check; exit 1 }",
              "function Count-Frames($path) {",
              "    if (-not (Test-Path -LiteralPath $path)) { return -1 }",
              "    $n = & ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 $path",
              "    if (\"$n\" -match '^\\s*(\\d+)') { return [int]$Matches[1] }",
              "    return -1",
              "}",
              "function Run-Chunk($name, $batch, $bhash, $recipe, $json, $avi, $mp4, $want, $need, [string[]]$fold) {",
              "    $made = \"$recipe`n$stamp\"",
              "    $kept = ''",
              "    $raw = Get-Content -LiteralPath \"$mp4.recipe\" -Raw -ErrorAction SilentlyContinue",
              "    if ($raw) { $kept = $raw.Trim() }",
              "    if ($Resume -and $kept -eq $made -and (Count-Frames $mp4) -eq $want) {",
              "        Remove-Item -LiteralPath $avi -ErrorAction SilentlyContinue",
              "        '{0} skipped: {1} has its {2} frames and was made from the same recipe and inputs' -f $name, $mp4, $want",
              "        return",
              "    }",
              "    if (-not (Test-Path -LiteralPath $batch) -or (Get-FileHash -Algorithm SHA256 -LiteralPath $batch).Hash -ne $bhash) {",
              "        '{0} STOP: {1} is not the batch this driver was written with (copy all of OUTDIR again)' -f $name, $batch",
              "        exit 1",
              "    }",
              "    $left = @(Get-ChildItem -LiteralPath $out -Filter ($name + '.avi.mmdcli-failed*') | ForEach-Object { $_.FullName })",
              "    foreach ($old in @($avi) + $left) {",
              "        if (Test-Path -LiteralPath $old -PathType Container) { '{0} STOP: {1} is a folder, not an earlier attempt' -f $name, $old; exit 1 }",
              "        if (-not (Test-Path -LiteralPath $old)) { continue }",
              "        try { Remove-Item -LiteralPath $old -Force -ErrorAction Stop }",
              "        catch { '{0} STOP: could not remove {1} of an earlier attempt: {2}' -f $name, $old, $_; exit 1 }",
              "        '{0}: removed {1} (an earlier attempt)' -f $name, $old",
              "    }",
              "    foreach ($old in @($mp4, \"$mp4.recipe\", \"$mp4.look.json\")) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }",
              "    $free = Get-FreeBytes $out",
              "    if ($free -lt 0) { '{0} STOP: could not measure the free space of {1}' -f $name, $out; exit 3 }",
              "    if ($free -lt $need) { '{0} STOP: {1} bytes free, the AVI needs {2} with the margin' -f $name, $free, $need; exit 3 }",
              "    Invoke-Native %s -m mmd_cli --out $json batch $batch | Out-Null" % py,
              "    if ($LASTEXITCODE -ne 0) { '{0} STOP: the MMD batch failed (exit {1}), see {2}' -f $name, $LASTEXITCODE, $json; exit 1 }",
              "    Invoke-Native %s tools/mv_look.py render $avi $look $mp4 @fold | Set-Content -LiteralPath \"$mp4.look.json\" -Encoding UTF8" % py,
              "    if ($LASTEXITCODE -ne 0) {",
              "        '{0} STOP: mv_look failed (exit {1}); the AVI is kept: {2}' -f $name, $LASTEXITCODE, $avi",
              "        Get-Content -LiteralPath \"$mp4.look.json\" -ErrorAction SilentlyContinue",
              "        exit 1",
              "    }",
              "    $n = Count-Frames $mp4",
              "    if ($n -ne $want) { '{0} STOP: {1} frames, want {2}; the AVI is kept: {3}' -f $name, $n, $want, $avi; exit 1 }",
              "    Set-Content -LiteralPath \"$mp4.recipe\" -Value $made -Encoding UTF8",
              "    try { Remove-Item -LiteralPath $avi -ErrorAction Stop } catch { '{0}: could not delete {1}: {2}' -f $name, $avi, $_ }",
              "    '{0} {1} frames (want {2}), {3} s' -f $name, $n, $want, [int]$sw.Elapsed.TotalSeconds",
              "}"]
    for c in chunks:
        name, avi, mp4 = _names(plan, tag, c)
        lines.append("Run-Chunk %s %s %s %s %s %s %s %d %d @(%s)" % (
            _ps(name), _ps("%s/chunk_%s.txt" % (plan["scripts"], name)), _ps(batch_hashes[c["index"]]),
            _ps(recipe(plan, tag, c, fps, shutter)), _ps("%s/%s.json" % (plan["out"], name)), _ps(avi), _ps(mp4),
            c["frames"], avi_bytes(c, fps, plan["size"], plan["avi_bytes_per_pixel"]) + DISK_MARGIN,
            ", ".join(_ps(a) for a in fold_args(plan, tag, c, fps, shutter))))
    lines += ["Remove-Item -LiteralPath %s -ErrorAction SilentlyContinue" % _ps(joined),
              "Invoke-Native ffmpeg -v error -y -f concat -safe 0 -i %s -c copy %s" % (_ps(concat), _ps(joined)),
              "if ($LASTEXITCODE -ne 0) { 'STOP: joining failed (exit {0})' -f $LASTEXITCODE; exit 1 }",
              "$n = Count-Frames %s" % _ps(joined),
              "if ($n -ne %d) { 'STOP: the joined video has {0} frames, want {1}' -f $n, %d; exit 1 }" % (total, total),
              "'joined {0} frames (want {1}), {2} s: {3}' -f $n, %d, [int]$sw.Elapsed.TotalSeconds, %s" % (total, _ps(joined))]
    return "\r\n".join(lines) + "\r\n"


def concat_text(plan, chunks, tag):
    return "".join("file '%s'\n" % _names(plan, tag, c)[2].replace("'", "'\\''") for c in chunks)


def write(plan, chunks, outdir, tag, fps, shutter):
    if fps not in MMD_FPS:
        raise ValueError("--fps is one of %s: the rates MMD renders" % ", ".join(str(f) for f in MMD_FPS))
    sub = fps // FPS
    if not (isinstance(shutter, (int, float)) and 0 < shutter <= 1) or (sub > 1 and int(math.floor(shutter * sub + 0.5)) < 1):
        raise ValueError("--shutter is the share of the frame time the shutter is open, above 0 up to 1; with %d subframes "
                         "at least %.4f, for mv_look averages round(shutter x subframes) of them" % (sub, 0.5 / sub))
    if not NAME.fullmatch(tag):
        raise ValueError("--tag goes into file names: letters, digits, _ and - only")
    os.makedirs(outdir, exist_ok=True)
    batches, hashes = [], {}
    for c in chunks:
        name, avi, _ = _names(plan, tag, c)
        data = batch_text(plan, c, fps, avi).encode("utf-8")
        path = os.path.join(outdir, "chunk_%s.txt" % name)
        with open(path, "wb") as f:
            f.write(data)
        batches.append(path)
        hashes[c["index"]] = hashlib.sha256(data).hexdigest().upper()
    driver = os.path.join(outdir, "render_%s.ps1" % tag)
    with open(driver, "w", encoding="utf-8-sig", newline="") as f:      # PowerShell 5.1 reads a file without a BOM as ANSI
        f.write(driver_text(plan, chunks, tag, fps, shutter, hashes))
    concat = os.path.join(outdir, "concat_%s.txt" % tag)
    with open(concat, "w", encoding="utf-8", newline="\n") as f:
        f.write(concat_text(plan, chunks, tag))
    bpp = plan["avi_bytes_per_pixel"]
    return {"chunks": len(chunks), "frames": sum(c["frames"] for c in chunks), "fps": fps, "subframes": sub,
            "shutter": shutter, "codec": plan["codec"], "avi_bytes_per_pixel": bpp,
            "largest_avi_gb": round(max(avi_bytes(c, fps, plan["size"], bpp) for c in chunks) / 1e9, 1),
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
    p.add_argument("--fps", type=int, default=240, help="the rate MMD renders at: 30, 60, 120, 240 or 480 (default 240)")
    p.add_argument("--shutter", type=float, default=0.5, help="share of each 30 fps frame blurred (default 0.5)")
    p.add_argument("--tag", default="final", help="names the files of this run (default final)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.plan, encoding="utf-8-sig") as f:
            plan = check_plan(json.load(f))
        if args.shots:
            if args.last is not None:
                raise ValueError("--last goes with --cuts: with --shots the report gives the last frame")
            with open(args.shots, encoding="utf-8-sig") as f:
                spans = spans_from_report(json.load(f))
        else:
            if args.last is None:
                raise ValueError("--cuts needs --last (the last frame of the song)")
            spans = spans_from_cuts(args.cuts, args.last)
        result = write(plan, plan_chunks(spans, args.lead), args.outdir, args.tag, args.fps, args.shutter)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
