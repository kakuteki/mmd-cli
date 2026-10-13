"""Render a whole MV in chunks: one chunk per camera shot, each rendered by MMD at a high frame rate with an alpha
channel, folded to 30 fps (or 60) with motion blur and the look of tools/mv_look.py, checked frame by frame, then joined.

    python tools/mv_chunks.py PLAN.json OUTDIR (--shots CAMERA_REPORT.json | --cuts F [F ...] --last F)
                              [--lead 120] [--fps 240] [--shutter 0.5] [--out-fps 30] [--tag final]

Why chunks: an uncompressed BGRA AVI at 240 fps and 1280x720 takes 29.5 MB per frame of the song (228 GB for a song
of 4 minutes 18 seconds), one shot of it some 17 GB at most.  A seam is hidden by the camera cut, and every chunk starts
--lead frames before its cut so that hair and skirt (physics, which MMD starts from the rest pose at the first rendered
frame) have settled by the cut.  The lead-in is rendered but not kept: mv_look gets --offset (the first rendered
frame), --from (the cut) and --to (the end of the shot), and goes on with the light loop and a running flare.

The cuts, the lead and the spans are frames of the song (MMD's frames, 30 per second) whatever the output.  --out-fps is
the rate of the joined video: 30 (the default; the rate to publish: the motion asks for 30 fps videos) or 60 (to watch).
At 60 MMD renders the same AVI and every frame of the song becomes two frames of the video, each the average of
round(shutter x fps / 60) of its fps / 60 subframes (4 and 2 at 240 fps); the effects of the look last as many seconds
as at 30 (mv_look counts them in frames of the song).  The files of a run at 60 fps carry "_60fps" after the tag
(render_final_60fps.ps1, final_60fps_00.mp4, <name>_final_60fps.mp4), so that it removes nothing of a run at 30 fps of
the same tag.

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
-Resume skips a chunk whose mp4 has its frame count and was made from the same recipe: the SHA-256 of its batch text,
the look's path and its fold arguments, and the size and time of every file it watches: the motions, camera, look and
cues, everything under the folders of the model and of the accessories (textures, toons, spheres; a __pycache__ folder
is left out, its bytecode is no input), mmd_cli and tools/ on the render machine, and MMD itself.  It does not see
fonts (mv_text finds them on the render machine), MMD's settings, Python and its libraries, ffmpeg, or files outside
those folders (a texture the model reads from elsewhere) or behind a junction inside them: after changing any of those,
render without -Resume.  The output and scripts folders may not lie in a watched folder.  Before chunk 0 the driver
checks the look with `mv_look.py layers`, so a wrong look stops the run before MMD has rendered anything.

The summary is one line of JSON (frames: of the joined video; spans: frames of the song; out_fps only at 60, so that the
default prints what it printed before --out-fps); an error is {"ok": false, "error": ...} with exit code 2.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

FPS = 30                        # the frames of the song (MMD's): the cuts, the lead, the spans and the seconds count in them
OUT_FPS = (30, 60)              # the joined video: 30 to publish (the motion's terms), 60 to watch
MMD_FPS = (30, 60, 120, 240, 480)
MIN_FRAMES = 3
UNCOMPRESSED = "未圧縮"
DEFAULT_MENU = {"215": "off", "221": "off", "282": "on"}          # axes and floor grid, ground shadow, background black
REQUIRED = ("mmd", "model", "motions", "camera", "look", "out", "scripts", "mmd_cli")
OPTIONAL = ("accessories", "cues", "menu", "size", "codec", "avi_bytes_per_pixel", "mmd_cli_home", "python", "name", "world")
PATHS = ("mmd", "model", "camera", "look", "out", "scripts", "mmd_cli")
DISK_MARGIN = 2 * 1024 ** 3
PS_QUOTES = re.compile("['\u2018\u2019\u201a\u201b]")      # Windows PowerShell takes each of these for a single quote
NAME = re.compile(r"[A-Za-z0-9_-]+")
ABSOLUTE = re.compile(r"([A-Za-z]:[\\/]|[\\/]{2}[^\\/])")
MAX_BYTES_PER_PIXEL = 1e6               # no AVI comes near; it keeps the arithmetic finite
MAX_WORKERS = 8                         # each worker runs an MMD and an encoder (GeForce cards take up to 8 NVENC sessions)
ENCODERS = ("x264", "nvenc")            # libx264 (the default, the video to publish) or h264_nvenc


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
    """the AVI of the chunk, lead-in included: every frame of the song is fps/30 frames in the AVI (whatever the output)"""
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
    if any(v % 2 for v in full["size"]):
        raise ValueError("size is even in both ways: the video is yuv420p, which ffmpeg refuses for an odd size "
                         "(found only after MMD has rendered chunk 0), not %r" % (full["size"],))
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
    full.setdefault("world", False)
    if not isinstance(full["world"], bool):
        raise ValueError("world is true (the look's stage lies in the world: mv_look reads the camera and the dancer) or "
                         "false, not %r" % (full["world"],))
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


def fold_args(plan, tag, chunk, fps, shutter, out_fps=FPS, encoder="x264", prepared=False):
    """what mv_look gets after `render AVI LOOK MP4` for the chunk: the subframes make the output rate (mv_look divides
    the rate of the AVI by them), the times are seconds of the song.  `prepared`: the layers and the text the driver of
    --workers prepared once (mv_look reads them and writes nothing there); `encoder` nvenc folds with h264_nvenc"""
    fold = ["--cues", plan["cues"]] if plan["cues"] else []
    fold += ["--prepared" if prepared else "--work", "%s/look_work_%s" % (plan["out"], tag), "--subframes", fps // out_fps,
             "--shutter", shutter, "--offset", "%.6f" % (chunk["first"] / float(FPS)), "--from", "%.6f" % (chunk["cut"] / float(FPS)),
             "--to", "%.6f" % ((chunk["end"] + 1) / float(FPS))]
    if encoder != "x264":
        fold += ["--encoder", encoder]
    return [str(a) for a in fold + _world_args(plan)]


def _world_args(plan):
    """with "world": true, what a stage in the world is drawn from: the camera motion and the dancer (mv_look reads the
    dancer only for a pool of light or shadows)"""
    if not plan["world"]:
        return []
    args = ["--camera", plan["camera"], "--model", plan["model"]]
    for motion in plan["motions"]:
        args += ["--motion", motion]
    return args


def recipe(plan, tag, chunk, fps, shutter, out_fps=FPS, encoder="x264", prepared=False):
    """what makes the chunk's mp4 apart from the contents of the input files: its batch, its look and its fold"""
    parts = [batch_text(plan, chunk, fps, _names(plan, tag, chunk)[1]), plan["look"]] + fold_args(plan, tag, chunk, fps, shutter,
                                                                                                   out_fps, encoder, prepared)
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _inputs(plan):
    inputs = [plan["mmd"], plan["model"]] + plan["motions"] + [plan["camera"]] + plan["accessories"] + [plan["look"]]
    return inputs + ([plan["cues"]] if plan["cues"] else [])


def _python(plan):
    return "python" if plan["python"] == "python" else _ps(plan["python"])


def _look_check(plan, work, out_fps, encoder, prepare=False, chunks=None, subframes=1, shutter=0.5):
    """the line that checks the look before MMD renders: `layers` (the driver of one worker), or `prepare` (the one of
    --workers: the layers and the text, once for every chunk).  With nvenc it also tries h264_nvenc.  With "world": true it
    reads the camera and the dancer too, and `prepare` draws the stage of the chunks' span with the folds' shutter"""
    line = "$check = Invoke-Native %s tools/mv_look.py %s $look %s --size %dx%d --fps %d" % (
        _python(plan), "prepare" if prepare else "layers", _ps(work), plan["size"][0], plan["size"][1], out_fps)
    if prepare and plan["cues"]:
        line += " --cues %s" % _ps(plan["cues"])
    if encoder != "x264":
        line += " --encoder %s" % encoder
    world = _world_args(plan)
    if world:
        line += " " + " ".join(a if a.startswith("--") else _ps(a) for a in world)
        if prepare:
            line += " --subframes %d --shutter %s --from %.6f --to %.6f" % (
                subframes, shutter, chunks[0]["cut"] / float(FPS), (chunks[-1]["end"] + 1) / float(FPS))
    return line


def _stamp_lines():
    """the size and time of every watched file, as -Resume compares them"""
    return ["$files = @($inputs | ForEach-Object { $i = Get-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue; "
            "if ($i) { '{0}|{1}|{2}' -f $_, $i.Length, $i.LastWriteTimeUtc.Ticks } else { '{0}|missing' -f $_ } })",
            "$files += @($folders | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -File -Force -ErrorAction SilentlyContinue } | "
            "Where-Object { $_.FullName -notmatch '[\\\\/]__pycache__[\\\\/]' } | Sort-Object FullName | ForEach-Object { '{0}|{1}|{2}' -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks })",
            "$stamp = $files -join \"`n\""]


def _check_lines(plan, look_check, what):
    return [look_check,
            # review 13: the path goes in through _ps like every other value (all the quotes PowerShell knows doubled)
            "if ($null -eq $LASTEXITCODE) { 'STOP: {0} did not run for the look check (not found?)' -f %s; exit 1 }" % _ps(plan["python"]),
            "if ($LASTEXITCODE -ne 0) { 'STOP: mv_look %s failed on the look {0} ({1}):' -f $look, (Why $LASTEXITCODE); $check; exit 1 }"
            % what]


def _helper_lines():
    """Invoke-Native, Why and Get-FreeBytes: the same in both drivers"""
    return ["function Invoke-Native {",
            "    # an external command, with the last exit code cleared first: one that is not found leaves it as it was.",
            "    # The rest is an array even for one argument (splatting a lone string passes its characters)",
            "    $global:LASTEXITCODE = $null",
            "    $exe = $args[0]",
            "    $rest = @($args | Select-Object -Skip 1)",
            "    & $exe @rest",
            "}",
            "function Why($code) { if ($null -eq $code) { 'did not run' } else { 'exit ' + $code } }",
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
            "}"]


COUNT_FRAMES = ["function Count-Frames($path) {",
                "    if (-not (Test-Path -LiteralPath $path)) { return -1 }",
                "    $n = & ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 $path",
                "    if (\"$n\" -match '^\\s*(\\d+)') { return [int]$Matches[1] }",
                "    return -1",
                "}"]


def _run_chunk_lines(plan, workers):
    """the function that renders, folds and checks one chunk.  For --workers (workers: True) the disk is shared (Reserve
    counts what the AVIs under way still have to write), a chunk that is done says so in the folder of the run, and the
    seconds are those of the run (the workers start after the driver)"""
    py = _python(plan)
    if workers:
        free = ["    if (-not (Reserve $name $avi $need)) { '{0}: not rendered, another chunk failed' -f $name; return }"]
        skipped, finished = ["        Done $name"], ["    Release $name",
                                                     "    '{0} {1} frames (want {2}), {3} s (worker {4})' -f $name, $n, $want, (Seconds), $Worker",
                                                     "    Done $name"]
    else:
        free = ["    $free = Get-FreeBytes $out",
                "    if ($free -lt 0) { '{0} STOP: could not measure the free space of {1}' -f $name, $out; exit 3 }",
                "    if ($free -lt $need) { '{0} STOP: {1} bytes free, the AVI needs {2} with the margin' -f $name, $free, $need; exit 3 }"]
        skipped, finished = [], ["    '{0} {1} frames (want {2}), {3} s' -f $name, $n, $want, [int]$sw.Elapsed.TotalSeconds"]
    return (["function Run-Chunk($name, $batch, $bhash, $recipe, $json, $avi, $mp4, $want, $need, [string[]]$fold) {",
             "    $made = \"$recipe`n$stamp\"",
             "    $kept = ''",
             "    $raw = Get-Content -LiteralPath \"$mp4.recipe\" -Raw -ErrorAction SilentlyContinue",
             "    if ($raw) { $kept = $raw.Trim() }",
             "    if ($Resume -and $kept -eq $made -and (Count-Frames $mp4) -eq $want) {",
             "        Remove-Item -LiteralPath $avi -ErrorAction SilentlyContinue",
             "        '{0} skipped: {1} has its {2} frames and was made from the same recipe and inputs' -f $name, $mp4, $want"]
            + skipped +
            ["        return",
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
             "    foreach ($old in @($mp4, \"$mp4.recipe\", \"$mp4.look.json\")) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }"]
            + free +
            ["    Invoke-Native %s -m mmd_cli --out $json batch $batch | Out-Null" % py,
             "    if ($LASTEXITCODE -ne 0) { '{0} STOP: the MMD batch failed ({1}), see {2}' -f $name, (Why $LASTEXITCODE), $json; exit 1 }",
             "    Invoke-Native %s tools/mv_look.py render $avi $look $mp4 @fold | Set-Content -LiteralPath \"$mp4.look.json\" -Encoding UTF8" % py,
             "    if ($LASTEXITCODE -ne 0) {",
             "        '{0} STOP: mv_look failed ({1}); the AVI is kept: {2}' -f $name, (Why $LASTEXITCODE), $avi",
             "        Get-Content -LiteralPath \"$mp4.look.json\" -ErrorAction SilentlyContinue",
             "        exit 1",
             "    }",
             "    $n = Count-Frames $mp4",
             "    if ($n -ne $want) { '{0} STOP: {1} frames, want {2}; the AVI is kept: {3}' -f $name, $n, $want, $avi; exit 1 }",
             "    Set-Content -LiteralPath \"$mp4.recipe\" -Value $made -Encoding UTF8",
             "    try { Remove-Item -LiteralPath $avi -ErrorAction Stop } catch { '{0}: could not delete {1}: {2}' -f $name, $avi, $_ }"]
            + finished + ["}"])


def _chunk_call(plan, tag, chunk, fps, shutter, batch_hashes, out_fps, encoder, prepared):
    name, avi, mp4 = _names(plan, tag, chunk)
    return "Run-Chunk %s %s %s %s %s %s %s %d %d @(%s)" % (
        _ps(name), _ps("%s/chunk_%s.txt" % (plan["scripts"], name)), _ps(batch_hashes[chunk["index"]]),
        _ps(recipe(plan, tag, chunk, fps, shutter, out_fps, encoder, prepared)), _ps("%s/%s.json" % (plan["out"], name)), _ps(avi),
        _ps(mp4), chunk["frames"] * (out_fps // FPS), avi_bytes(chunk, fps, plan["size"], plan["avi_bytes_per_pixel"]) + DISK_MARGIN,
        ", ".join(_ps(a) for a in fold_args(plan, tag, chunk, fps, shutter, out_fps, encoder, prepared)))


def _join_lines(joined, concat, total):
    return ["Remove-Item -LiteralPath %s -ErrorAction SilentlyContinue" % _ps(joined),
            "Invoke-Native ffmpeg -v error -y -f concat -safe 0 -i %s -c copy %s" % (_ps(concat), _ps(joined)),
            "if ($LASTEXITCODE -ne 0) { 'STOP: joining failed ({0})' -f (Why $LASTEXITCODE); exit 1 }",
            "$n = Count-Frames %s" % _ps(joined),
            "if ($n -ne %d) { 'STOP: the joined video has {0} frames, want {1}' -f $n, %d; exit 1 }" % (total, total)]


def driver_text(plan, chunks, tag, fps, shutter, batch_hashes, out_fps=FPS, encoder="x264"):
    sub = fps // out_fps
    per = out_fps // FPS                                    # frames of the video to a frame of the song
    total = sum(c["frames"] for c in chunks) * per
    joined = "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)
    concat = "%s/concat_%s.txt" % (plan["scripts"], tag)
    work = "%s/look_work_%s" % (plan["out"], tag)
    lines = ["# %d chunks at %d fps folded to %d fps (%d subframes, shutter %s), %d frames, joined to %s."
             % (len(chunks), fps, out_fps, sub, shutter, total, joined),
             "# Written by tools/mv_chunks.py.  -Resume skips a chunk whose mp4 has its frame count and was made from the",
             "# same recipe (batch, look and fold) and the same watched files (size and time): see <mp4>.recipe beside it.",
             "# It does not see fonts, MMD's settings, Python, ffmpeg or files outside the watched folders: after changing",
             "# any of those, run without -Resume.",
             "param([switch]$Resume)",
             "$ErrorActionPreference = 'Continue'",
             "Set-Location -LiteralPath %s" % _ps(plan["mmd_cli"])]
    if plan["mmd_cli_home"]:
        lines.append("$env:MMD_CLI_HOME = %s" % _ps(plan["mmd_cli_home"]))
    lines += ["$out = %s" % _ps(plan["out"]),
              "$look = %s" % _ps(plan["look"]),
              "$inputs = @(%s)" % ", ".join(_ps(i) for i in _inputs(plan)),
              "$folders = @(%s)" % ", ".join(_ps(f) for f in watched_folders(plan)),
              "New-Item -ItemType Directory -Force -Path $out | Out-Null",
              "if (-not (Test-Path -LiteralPath $out -PathType Container)) { 'STOP: could not make the output folder {0}' -f $out; exit 1 }",
              "$sw = [Diagnostics.Stopwatch]::StartNew()"]
    lines += _helper_lines() + _stamp_lines()
    # the look is checked at the rate the fold will draw it at
    lines += _check_lines(plan, _look_check(plan, work, out_fps, encoder), "layers")
    lines += COUNT_FRAMES + _run_chunk_lines(plan, workers=False)
    lines += [_chunk_call(plan, tag, c, fps, shutter, batch_hashes, out_fps, encoder, False) for c in chunks]
    lines += _join_lines(joined, concat, total)
    lines.append("'joined {0} frames (want {1}), {2} s: {3}' -f $n, %d, [int]$sw.Elapsed.TotalSeconds, %s" % (total, _ps(joined)))
    return "\r\n".join(lines) + "\r\n"


def workers_driver_text(plan, chunks, tag, fps, shutter, batch_hashes, out_fps, encoder, workers):
    """the driver of --workers: the same script is the driver (no -Worker) and each of its workers (-Worker k)"""
    sub = fps // out_fps
    total = sum(c["frames"] for c in chunks) * (out_fps // FPS)
    joined = "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)
    concat = "%s/concat_%s.txt" % (plan["scripts"], tag)
    work = "%s/look_work_%s" % (plan["out"], tag)
    run = "%s/run_%s" % (plan["out"], tag)
    count = min(workers, len(chunks))
    names = [_names(plan, tag, c)[0] for c in chunks]
    lines = ["# %d chunks at %d fps folded to %d fps (%d subframes, shutter %s), %d frames, joined to %s."
             % (len(chunks), fps, out_fps, sub, shutter, total, joined),
             "# %d workers at a time.  Every worker is this script again (-Worker k): it takes the next chunk no worker has taken"
             % count,
             "# (a claim in the folder of the run, made with CreateNew), renders, folds and checks it as the driver of one worker",
             "# would, and takes the next.  The layers and the text are prepared once, before the first worker starts, and every",
             "# chunk folds with them (mv_look --prepared).  A failure stops the run: no worker takes another chunk, the chunks under",
             "# way are finished, and the driver exits with the code of the failure (1; 3 for the disk) without joining.",
             "# Written by tools/mv_chunks.py --workers %d.  -Resume skips a chunk whose mp4 has its frame count and was made from" % workers,
             "# the same recipe (batch, look and fold) and the same watched files (size and time): see <mp4>.recipe beside it.",
             "# It does not see fonts, MMD's settings, Python, ffmpeg or files outside the watched folders: after changing",
             "# any of those, run without -Resume.",
             "param([switch]$Resume, [int]$Worker = 0)",
             "$ErrorActionPreference = 'Continue'",
             "Set-Location -LiteralPath %s" % _ps(plan["mmd_cli"])]
    if plan["mmd_cli_home"]:
        lines.append("$env:MMD_CLI_HOME = %s" % _ps(plan["mmd_cli_home"]))
    lines += ["$out = %s" % _ps(plan["out"]),
              "$look = %s" % _ps(plan["look"]),
              "$run = %s" % _ps(run),
              "$inputs = @(%s)" % ", ".join(_ps(i) for i in _inputs(plan)),
              "$folders = @(%s)" % ", ".join(_ps(f) for f in watched_folders(plan)),
              "$diskWait = 5",
              "New-Item -ItemType Directory -Force -Path $out | Out-Null",
              "if (-not (Test-Path -LiteralPath $out -PathType Container)) { 'STOP: could not make the output folder {0}' -f $out; exit 1 }"]
    lines += _helper_lines() + COUNT_FRAMES
    lines += ["function Hold($path) {",
              "    # the file open for this process alone (FileShare None): $null while another process has it open",
              "    try { return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }",
              "    catch { return $null }",
              "}",
              "function Lock-Disk {",
              "    # the notes of the AVIs under way are read and written by one worker at a time (each holds it for milliseconds)",
              "    $lock = $null",
              "    $waited = [Diagnostics.Stopwatch]::StartNew()",
              "    while (-not $lock) {",
              "        $lock = Hold (Join-Path $run 'disk.lock')",
              "        if ($lock) { break }",
              "        if ($waited.Elapsed.TotalSeconds -gt 60) { 'STOP: could not open {0} for a minute' -f (Join-Path $run 'disk.lock'); exit 1 }",
              "        Start-Sleep -Milliseconds 50",
              "    }",
              "    return $lock",
              "}",
              "function Reserve($name, $avi, $need) {",
              "    # the AVI starts when the disk holds it with its margin after what the AVIs under way (busy_<chunk> in the folder",
              "    # of the run: their AVI and need) still have to write.  While those would leave too little it waits; with none",
              "    # under way and still too little it stops the run (exit 3).  $false when another chunk failed meanwhile",
              "    while ($true) {",
              "        if (Test-Path -LiteralPath (Join-Path $run 'stop')) { return $false }",
              "        $lock = Lock-Disk",
              "        try {",
              "            $free = Get-FreeBytes $out",
              "            if ($free -lt 0) { '{0} STOP: could not measure the free space of {1}' -f $name, $out; exit 3 }",
              "            $owed = [decimal]0",
              "            $busy = @(Get-ChildItem -LiteralPath $run -Filter 'busy_*' -File -Force -ErrorAction SilentlyContinue)",
              "            foreach ($b in $busy) {",
              "                $note = ([IO.File]::ReadAllText($b.FullName)).Trim().Split('|')",
              "                $done = 0",
              "                $i = Get-Item -LiteralPath $note[0] -Force -ErrorAction SilentlyContinue",
              "                if ($i) { $done = $i.Length }",
              "                $owed += [math]::Max([decimal]0, [decimal]$note[1] - $done)",
              "            }",
              "            if ([decimal]$free - $owed -ge $need) {",
              "                [IO.File]::WriteAllText((Join-Path $run ('busy_' + $name)), ('{0}|{1}' -f $avi, $need))",
              "                return $true",
              "            }",
              "            if ($busy.Count -eq 0) { '{0} STOP: {1} bytes free, the AVI needs {2} with the margin' -f $name, $free, $need; exit 3 }",
              "        } finally { $lock.Close() }",
              "        Start-Sleep -Milliseconds ([int]($diskWait * 1000))",
              "    }",
              "}",
              "function Release($name) {",
              "    $lock = Lock-Disk",
              "    try { Remove-Item -LiteralPath (Join-Path $run ('busy_' + $name)) -Force -ErrorAction SilentlyContinue } finally { $lock.Close() }",
              "}",
              "function Done($name) { [IO.File]::WriteAllText((Join-Path $run ('done_' + $name)), [string]$Worker) }",
              "function Seconds { [int]([DateTime]::UtcNow - $since).TotalSeconds }"]
    lines += _run_chunk_lines(plan, workers=True)
    lines += ["if ($Worker -gt 0) {",
              "    # a worker: the stamp of the inputs and the start of the run are the driver's",
              "    $mine = Hold (Join-Path $run ('worker_' + $Worker + '.lock'))",
              "    if (-not $mine) { 'STOP: worker {0} could not open its lock in {1}' -f $Worker, $run; exit 1 }",
              "    if (-not (Test-Path -LiteralPath (Join-Path $run 'started.txt'))) {",
              "        'STOP: worker {0} found no run in {1}: the driver starts its workers (run it without -Worker)' -f $Worker, $run",
              "        exit 1",
              "    }",
              "    $stamp = [IO.File]::ReadAllText((Join-Path $run 'stamp.txt'))",
              "    $since = New-Object DateTime -ArgumentList ([int64][IO.File]::ReadAllText((Join-Path $run 'started.txt'))), ([DateTimeKind]::Utc)",
              "    function Take($name) {",
              "        # the chunk for this worker alone: the claim is a file made with CreateNew, which fails for every other worker",
              "        if (Test-Path -LiteralPath (Join-Path $run 'stop')) { return $false }",
              "        try { [IO.File]::Open((Join-Path $run ('claim_' + $name)), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None).Close(); return $true }",
              "        catch { return $false }",
              "    }",
              "    $through = $false",
              "    try {"]
    lines += ["        if (Take %s) { %s }" % (_ps(_names(plan, tag, c)[0]), _chunk_call(plan, tag, c, fps, shutter, batch_hashes, out_fps,
                                                                                        encoder, True)) for c in chunks]
    lines += ["        $through = $true",
              "    } catch {",
              "        # an error the steps do not expect (a .NET call that threw): a failure like the others",
              "        'STOP: worker {0}: {1}' -f $Worker, $_",
              "        exit 1",
              "    } finally {",
              "        # a chunk that failed ended this worker (exit 1, or 3 for the disk): no worker takes another chunk",
              "        if (-not $through) { [IO.File]::WriteAllText((Join-Path $run 'stop'), [string]$Worker) }",
              "    }",
              "    exit 0",
              "}",
              "# the driver: one run at a time; what an earlier run left in the folder of the run goes (a worker of it that is still",
              "# running holds its lock, which cannot be removed: the run stops)",
              "New-Item -ItemType Directory -Force -Path $run | Out-Null",
              "$hold = Hold (Join-Path $run 'lock')",
              "if (-not $hold) { 'STOP: another run of this driver holds {0}' -f (Join-Path $run 'lock'); exit 1 }",
              "foreach ($old in @(Get-ChildItem -LiteralPath $run -File -Force | Where-Object { $_.Name -ne 'lock' })) {",
              "    try { Remove-Item -LiteralPath $old.FullName -Force -ErrorAction Stop }",
              "    catch { 'STOP: could not remove {0} of an earlier run (a worker of it still running?): {1}' -f $old.FullName, $_; exit 1 }",
              "}",
              "$since = [DateTime]::UtcNow",
              "[IO.File]::WriteAllText((Join-Path $run 'started.txt'), [string]$since.Ticks)"]
    lines += _stamp_lines()
    lines += ["[IO.File]::WriteAllText((Join-Path $run 'stamp.txt'), $stamp)"]
    # the layers and the text, prepared at the rate the folds draw them at: a wrong look or cue file stops the run here
    lines += _check_lines(plan, _look_check(plan, work, out_fps, encoder, prepare=True, chunks=chunks, subframes=sub,
                                            shutter=shutter), "prepare")
    lines += ["'prepared the layers and the text in {0}, {1} s' -f %s, (Seconds)" % _ps(work),
              "$self = (Get-Process -Id $PID).Path",
              "$count = %d" % count,
              "$started = @()",
              "for ($k = 1; $k -le $count; $k++) {",
              "    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('\"{0}\"' -f $PSCommandPath), '-Worker', $k)",
              "    if ($Resume) { $a += '-Resume' }",
              "    $p = $null",
              "    try { $p = Start-Process -FilePath $self -ArgumentList $a -NoNewWindow -PassThru -ErrorAction Stop; $null = $p.Handle } catch { }",
              "    if (-not $p) { 'STOP: could not start worker {0}' -f $k; [IO.File]::WriteAllText((Join-Path $run 'stop'), 'driver'); break }",
              "    $started += $p",
              "}",
              "$failed = $null",
              "while ($true) {",
              "    foreach ($p in $started) {",
              "        if (-not $failed -and $p.HasExited -and $p.ExitCode -ne 0) {",
              "            $failed = $p",
              "            [IO.File]::WriteAllText((Join-Path $run 'stop'), 'driver')",
              "        }",
              "    }",
              "    if (@($started | Where-Object { -not $_.HasExited }).Count -eq 0) { break }",
              "    Start-Sleep -Milliseconds 500",
              "}",
              "if ($started.Count -lt $count) { exit 1 }",
              "if ($failed) {",
              "    'STOP: a worker failed (exit {0}); no chunk was taken after it, the joined video is not made' -f $failed.ExitCode",
              "    if ($failed.ExitCode -eq 3) { exit 3 }",
              "    exit 1",
              "}",
              "$missing = @(@(%s) | Where-Object { -not (Test-Path -LiteralPath (Join-Path $run ('done_' + $_))) })"
              % ", ".join(_ps(n) for n in names),
              "if ($missing.Count -gt 0) { 'STOP: no worker finished {0}' -f ($missing -join ', '); exit 1 }"]
    lines += _join_lines(joined, concat, total)
    lines.append("'joined {0} frames (want {1}), {2} s: {3}' -f $n, %d, (Seconds), %s" % (total, _ps(joined)))
    return "\r\n".join(lines) + "\r\n"


def concat_text(plan, chunks, tag, out_fps=FPS):
    """the list ffmpeg joins.  At 60 fps every chunk has its length too: an mp4 keeps it in its edit list in ms, and a chunk
    whose frames of the song leave 1 over 3 can come out 1 ms short, depending on its picture (1333 ms for 40 frames: 20475 of
    20480 ticks), which puts every later chunk 5 ticks early (ffmpeg 8.0 and 8.1, 2026-10-13); concat takes the given length
    instead.  The list of 30 fps stays as it was, so that the video to publish keeps its bytes: a 30 fps chunk can come out
    short as well (chunk 04 of the v7 render: 13533 ms for 406 frames, so the joined video is 5 ticks early from frame 1740 on;
    review of out-fps)"""
    text = ""
    for c in chunks:
        text += "file '%s'\n" % _names(plan, tag, c)[2].replace("'", "'\\''")
        if out_fps != FPS:
            text += "duration %.6f\n" % (c["frames"] / float(FPS))
    return text


def run_tag(tag, out_fps, encoder="x264"):
    """what names the files of a run: the tag, and at 60 fps the tag with "_60fps" (a run at 60 fps with the tag of a run at
    30 fps would otherwise remove its chunks, its joined video and its driver), and with h264_nvenc "_nvenc" after that (the
    files of libx264, the encoder of the video to publish, stay as they are)"""
    tag = tag if out_fps == FPS else "%s_%dfps" % (tag, out_fps)
    return tag if encoder == "x264" else "%s_%s" % (tag, encoder)


def write(plan, chunks, outdir, tag, fps, shutter, out_fps=FPS, workers=1, encoder="x264"):
    if not _whole(workers) or not 1 <= workers <= MAX_WORKERS:
        raise ValueError("--workers is the number of chunks rendered and folded at the same time, 1 to %d, not %r" % (MAX_WORKERS, workers))
    if encoder not in ENCODERS:
        raise ValueError("--encoder is x264 (libx264, the default and the encoder of the video to publish) or nvenc (h264_nvenc "
                         "on an NVIDIA GPU), not %r" % (encoder,))
    if not _whole(out_fps) or out_fps not in OUT_FPS:
        raise ValueError("--out-fps is 30 (the video to publish: the motion asks for 30 fps) or 60 (to watch), not %r" % (out_fps,))
    if fps not in MMD_FPS:
        raise ValueError("--fps is one of %s: the rates MMD renders" % ", ".join(str(f) for f in MMD_FPS))
    if fps < out_fps:
        raise ValueError("--fps %d is below --out-fps %d: MMD renders at least one frame for every frame of the video" % (fps, out_fps))
    sub = fps // out_fps
    if not (isinstance(shutter, (int, float)) and 0 < shutter <= 1) or (sub > 1 and int(math.floor(shutter * sub + 0.5)) < 1):
        raise ValueError("--shutter is the share of the frame time the shutter is open, above 0 up to 1; with %d subframes "
                         "at least %.4f, for mv_look averages round(shutter x subframes) of them" % (sub, 0.5 / sub))
    if not NAME.fullmatch(tag):
        raise ValueError("--tag goes into file names: letters, digits, _ and - only")
    tag = run_tag(tag, out_fps, encoder)
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
        if workers == 1:
            f.write(driver_text(plan, chunks, tag, fps, shutter, hashes, out_fps, encoder))
        else:
            f.write(workers_driver_text(plan, chunks, tag, fps, shutter, hashes, out_fps, encoder, workers))
    concat = os.path.join(outdir, "concat_%s.txt" % tag)
    with open(concat, "w", encoding="utf-8", newline="\n") as f:
        f.write(concat_text(plan, chunks, tag, out_fps))
    bpp = plan["avi_bytes_per_pixel"]
    summary = {"chunks": len(chunks), "frames": sum(c["frames"] for c in chunks) * (out_fps // FPS)}
    if out_fps != FPS:
        summary["out_fps"] = out_fps              # only at 60: the default prints the summary of before, byte for byte
    if workers != 1:
        summary["workers"] = workers              # and these two only when they are asked for
    if encoder != "x264":
        summary["encoder"] = encoder
    summary.update({"fps": fps, "subframes": sub, "shutter": shutter, "codec": plan["codec"], "avi_bytes_per_pixel": bpp,
                    "largest_avi_gb": round(max(avi_bytes(c, fps, plan["size"], bpp) for c in chunks) / 1e9, 1),
                    "spans": [[c["cut"], c["end"]] for c in chunks], "driver": driver, "batches": batches, "concat": concat,
                    "joined": "%s/%s_%s.mp4" % (plan["out"], plan["name"], tag)})
    return summary


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
    p.add_argument("--shutter", type=float, default=0.5, help="share of each frame of the video blurred (default 0.5)")
    p.add_argument("--out-fps", type=int, default=FPS,
                   help="the rate of the joined video: 30 (default; to publish) or 60 (to watch; the files get _60fps)")
    p.add_argument("--tag", default="final", help="names the files of this run (default final)")
    p.add_argument("--workers", type=int, default=1,
                   help="chunks rendered and folded at the same time, 1 to %d (default 1: one after the other)" % MAX_WORKERS)
    p.add_argument("--encoder", default="x264",
                   help="x264 (libx264 crf 16, the default; the video to publish) or nvenc (h264_nvenc; the files get _nvenc)")
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
        result = write(plan, plan_chunks(spans, args.lead), args.outdir, args.tag, args.fps, args.shutter, args.out_fps,
                       args.workers, args.encoder)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
