"""tools/mv_chunks.py: a long render split at the camera cuts, each chunk rendered fast, folded with blur, checked, joined."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from mmd_cli import batch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool(name):
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mv_chunks = load_tool("mv_chunks")
try:
    mv_look = load_tool("mv_look")
except ImportError:                       # numpy and Pillow are only needed for the agreement on the shutter
    mv_look = None

WINDOWS = os.name == "nt" and shutil.which("powershell")
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
LIPS = "C:/work/song/kazusa/ヒビカセ（Choreography by ATY）/ヒビカセ　Face&Lips 歌ってる方.vmd"
PLAN = {
    "mmd": "C:/MMD/MikuMikuDance.exe",
    "model": "C:/MMD/UserFile/Model/Rin/White.pmx",
    "motions": ["C:/work/song/dance.vmd", LIPS],
    "camera": "C:/work/song/camera.vmd",
    "accessories": ["C:/work/song/stage/stage_floor.x"],
    "look": "C:/work/song/look.json",
    "cues": "C:/work/song/cues.json",
    "out": "C:/work/song/out",
    "scripts": "C:/work/song/mv",
    "mmd_cli": "C:/work/mmd-cli",
}
REPORT = {"shots": [{"start": 0, "end": 99}, {"start": 100, "end": 249}, {"start": 250, "end": 299}]}
SPANS = [(0, 99), (100, 249), (250, 299)]
GIB = 1024 ** 3


class SpansTest(unittest.TestCase):
    def test_each_shot_of_the_camera_report_is_a_span(self):
        self.assertEqual(mv_chunks.spans_from_report(REPORT), SPANS)

    def test_the_shots_are_taken_in_frame_order(self):
        shuffled = {"shots": [REPORT["shots"][2], REPORT["shots"][0], REPORT["shots"][1]]}
        self.assertEqual(mv_chunks.spans_from_report(shuffled), SPANS)

    def test_a_gap_or_an_overlap_between_shots_is_refused(self):
        for shots in ([{"start": 0, "end": 99}, {"start": 101, "end": 200}],
                      [{"start": 0, "end": 99}, {"start": 99, "end": 200}]):
            with self.assertRaises(ValueError):
                mv_chunks.spans_from_report({"shots": shots})

    def test_the_first_shot_must_start_at_frame_zero(self):
        with self.assertRaises(ValueError):
            mv_chunks.spans_from_report({"shots": [{"start": 5, "end": 99}]})

    def test_a_report_of_the_wrong_shape_is_refused_by_name(self):
        for report, word in (([1, 2], "shots"), ({}, "shots"), ({"shots": []}, "shots"),
                             ({"shots": [{"start": "0", "end": 99}]}, "start"),
                             ({"shots": [{"start": 0, "end": True}]}, "end")):
            with self.assertRaises(ValueError) as ctx:
                mv_chunks.spans_from_report(report)
            self.assertIn(word, str(ctx.exception), report)

    def test_cuts_split_frame_zero_to_the_last_frame(self):
        self.assertEqual(mv_chunks.spans_from_cuts([2577, 5064], 7742), [(0, 2576), (2577, 5063), (5064, 7742)])
        self.assertEqual(mv_chunks.spans_from_cuts([], 99), [(0, 99)])

    def test_cuts_out_of_order_or_outside_the_song_are_refused(self):
        for cuts in ([5064, 2577], [0, 100], [100, 100], [7743]):
            with self.assertRaises(ValueError):
                mv_chunks.spans_from_cuts(cuts, 7742)


class ChunkTest(unittest.TestCase):
    def test_the_lead_in_starts_before_the_cut_but_not_before_frame_zero(self):
        chunks = mv_chunks.plan_chunks(SPANS, lead=120)
        self.assertEqual([(c["first"], c["cut"], c["end"], c["frames"]) for c in chunks],
                         [(0, 0, 99, 100), (0, 100, 249, 150), (130, 250, 299, 50)])

    def test_a_negative_lead_is_refused(self):
        with self.assertRaises(ValueError):
            mv_chunks.plan_chunks(SPANS, lead=-1)

    def test_a_chunk_of_fewer_than_three_frames_is_refused(self):
        # review 10: a chunk of 1 or 2 frames joined with -c copy puts the timestamps out of order (301 frames out)
        for spans in ([(0, 99), (100, 100), (101, 299)], [(0, 99), (100, 101), (102, 299)]):
            with self.assertRaises(ValueError):
                mv_chunks.plan_chunks(spans, lead=120)
        self.assertEqual(len(mv_chunks.plan_chunks([(0, 99), (100, 102), (103, 299)], lead=120)), 3)

    def test_the_avi_holds_every_subframe_of_the_lead_in_and_the_span(self):
        chunk = {"first": 130, "cut": 250, "end": 299}
        self.assertEqual(mv_chunks.avi_bytes(chunk, fps=240, size=(1280, 720)), 170 * 8 * 1280 * 720 * 4)
        self.assertEqual(mv_chunks.avi_bytes(chunk, fps=240, size=(1280, 720), bytes_per_pixel=1.5),
                         int(170 * 8 * 1280 * 720 * 1.5))


class PlanTest(unittest.TestCase):
    def refused(self, **change):
        plan = dict(PLAN, **change)
        with self.assertRaises(ValueError) as ctx:
            mv_chunks.check_plan(plan)
        return str(ctx.exception)

    def test_missing_plan_entries_are_named(self):
        plan = dict(PLAN)
        del plan["camera"], plan["look"]
        with self.assertRaises(ValueError) as ctx:
            mv_chunks.check_plan(plan)
        self.assertIn("camera", str(ctx.exception))
        self.assertIn("look", str(ctx.exception))

    def test_an_unknown_entry_is_refused(self):
        self.assertIn("accesories", self.refused(accesories=[]))

    def test_paths_are_absolute_strings(self):
        for change in ({"look": ""}, {"look": "look.json"}, {"out": "out"}, {"camera": 3}, {"cues": ""},
                       {"mmd_cli_home": "home"}, {"motions": [None]}, {"motions": "C:/work/dance.vmd"},
                       {"motions": []}, {"accessories": "C:/work/floor.x"}, {"accessories": [""]}):
            self.refused(**change)
        plan = mv_chunks.check_plan(dict(PLAN, out="//hinata/work/out", cues=None))
        self.assertEqual((plan["out"], plan["cues"]), ("//hinata/work/out", None))

    def test_the_size_is_two_whole_numbers(self):
        for size in ("12", [1280, "720"], [1280.5, 720], [True, 720], [1280], [0, 720]):
            self.refused(size=size)

    def test_the_size_is_even_for_the_video(self):
        # review 12: yuv420p takes even sizes only; an odd one failed in ffmpeg after MMD had rendered chunk 0
        for size in ([1281, 720], [1280, 721]):
            self.assertIn("even", self.refused(size=size))

    def test_the_name_goes_into_a_file_name(self):
        self.refused(name="my mv")
        self.refused(name="")

    def test_menu_ids_are_numbers_so_0282_is_282(self):
        # review 10: "0282" passed the check of "282" and mmd reads it as 282: the AVI lost its alpha
        self.assertIn("282", self.refused(menu={"0282": "off"}))
        for menu in ([["282", "on"]], None, {"x": "on"}, {"215": "yes"}):
            self.refused(menu=menu)
        plan = mv_chunks.check_plan(dict(PLAN, menu={215: "on", "0298": "off"}))
        self.assertEqual(plan["menu"], {"215": "on", "221": "off", "282": "on", "298": "off"})

    def test_the_output_may_not_sit_in_a_folder_that_resume_watches(self):
        # review 11: -Resume watches the folders of the model and the accessories; its own output inside one of them
        # would change the stamp with every chunk
        for change in ({"out": "C:/MMD/UserFile/Model/Rin/out"}, {"scripts": "C:/work/song/stage/mv"},
                       {"out": r"c:\work\song\stage\out"}):
            self.assertIn("inside", self.refused(**change), change)
        mv_chunks.check_plan(dict(PLAN, out="C:/MMD/UserFile/Model/Rin2/out"))   # a neighbour of the folder is fine

    def test_a_compressed_codec_needs_its_bytes_per_pixel(self):
        self.assertIn("avi_bytes_per_pixel", self.refused(codec="UT Video"))
        plan = mv_chunks.check_plan(dict(PLAN, codec="UT Video", avi_bytes_per_pixel=1.2))
        self.assertEqual(plan["avi_bytes_per_pixel"], 1.2)
        self.assertEqual(mv_chunks.check_plan(dict(PLAN))["avi_bytes_per_pixel"], 4)
        for bpp in (0, -1, "4", True):
            self.refused(avi_bytes_per_pixel=bpp)


class BatchTest(unittest.TestCase):
    CHUNK = {"index": 1, "first": 0, "cut": 100, "end": 249, "frames": 150}
    AVI = "C:/work/song/out/t_01.avi"

    def lines(self, plan, fps=240):
        return [e["argv"] for e in batch.parse_lines(mv_chunks.batch_text(mv_chunks.check_plan(plan), self.CHUNK, fps, self.AVI))]

    def test_the_scene_is_built_and_the_lead_in_and_span_are_rendered(self):
        lines = self.lines(dict(PLAN))
        self.assertEqual(lines, [
            ["launch", "--headless", "--exe", PLAN["mmd"]],
            ["new"],
            ["menu", "set", "215", "off"], ["menu", "set", "221", "off"], ["menu", "set", "282", "on"],
            ["model", "load", PLAN["model"]],
            ["motion", "load", "C:/work/song/dance.vmd", "--frame", "0"],
            ["motion", "load", LIPS, "--frame", "0"],
            ["model", "select", "camera"],
            ["motion", "load", PLAN["camera"], "--frame", "0"],
            ["accessory", "load", "C:/work/song/stage/stage_floor.x"],
            ["render", "avi", self.AVI, "--from", "0", "--to", "249", "--fps", "240", "--size", "1280", "720", "--codec", "未圧縮"],
            ["quit"]])

    def test_menu_entries_are_merged_over_the_defaults(self):
        lines = self.lines(dict(PLAN, menu={"215": "on", "298": "off"}))
        menus = [l[2:] for l in lines if l[:2] == ["menu", "set"]]
        self.assertEqual(menus, [["215", "on"], ["221", "off"], ["282", "on"], ["298", "off"]])

    def test_without_the_black_background_there_is_no_alpha_so_the_plan_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            mv_chunks.check_plan(dict(PLAN, menu={"282": "off"}))
        self.assertIn("282", str(ctx.exception))


class QuoteTest(unittest.TestCase):
    def test_an_apostrophe_in_the_join_list_is_escaped_as_ffmpeg_reads_it(self):
        plan = mv_chunks.check_plan(dict(PLAN, out="C:/it's/out"))
        text = mv_chunks.concat_text(plan, mv_chunks.plan_chunks(SPANS, lead=0), "t")
        self.assertEqual(text.splitlines()[0], "file 'C:/it'\\''s/out/t_00.mp4'")

    def test_every_character_powershell_takes_for_a_single_quote_is_doubled(self):
        # review 10: PowerShell 5.1 ends a '...' string at U+2018, U+2019, U+201A and U+201B too (cp932 has two of them)
        for q in "'\u2018\u2019\u201a\u201b":
            self.assertEqual(mv_chunks._ps("Don%st" % q), "'Don%s%st'" % (q, q))
        self.assertEqual(mv_chunks._ps("C:/a\uff07b"), "'C:/a\uff07b'")          # the full-width apostrophe is not one


@unittest.skipUnless(mv_look, "needs numpy and Pillow for tools/mv_look.py")
class ShutterTest(unittest.TestCase):
    def test_the_frame_rates_and_shutters_taken_are_the_ones_mmd_and_mv_look_take(self):
        # review 10: fps 60 with shutter 0.2 passed here, and mv_look refused it after MMD had rendered chunk 0
        chunks = mv_chunks.plan_chunks(SPANS, lead=0)
        plan = mv_chunks.check_plan(dict(PLAN))
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        for fps in (30, 60, 90, 120, 240, 480, 960):
            for shutter in (0.01, 0.05, 0.07, 0.1, 0.2, 0.24, 0.25, 0.3, 0.5, 1.0):
                try:
                    mv_look.check_shutter(fps // 30, shutter)
                    looks_ok = fps in (30, 60, 120, 240, 480)
                except ValueError:
                    looks_ok = False
                try:
                    mv_chunks.write(plan, chunks, folder, "t", fps, shutter)
                    ok = True
                except ValueError:
                    ok = False
                self.assertEqual(ok, looks_ok, (fps, shutter))


STUBS = r"""
$log = $env:STUB_LOG
function python {
    Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ') + ' home=' + $env:MMD_CLI_HOME) -Encoding UTF8
    if ($args[0] -eq '-m') {
        if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) { $global:LASTEXITCODE = 1; return }
        $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
        Set-Content -LiteralPath (($render | ConvertFrom-Json)[2]) -Value 'avi'
        $global:LASTEXITCODE = 0
        return
    }
    if ($args[1] -eq 'layers') {
        # tools/mv_look.py layers LOOK WORK ...: the look must be JSON
        try { $null = Get-Content -LiteralPath $args[2] -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
        catch { '{"ok": false, "error": "the look is not JSON"}'; $global:LASTEXITCODE = 2; return }
        '{"ok": true}'
        $global:LASTEXITCODE = 0
        return
    }
    # tools/mv_look.py render AVI LOOK MP4 ...: refuse what the real one refuses, then write the frames it would
    $avi = $args[2]; $look = $args[3]; $mp4 = $args[4]
    $from = [double]$args[[array]::IndexOf($args, '--from') + 1]
    $to = [double]$args[[array]::IndexOf($args, '--to') + 1]
    $offset = [double]$args[[array]::IndexOf($args, '--offset') + 1]
    $why = $null
    if (-not (Test-Path -LiteralPath $avi)) { $why = 'no such file: ' + $avi }
    elseif (-not (Test-Path -LiteralPath $look)) { $why = 'no look: ' + $look }
    elseif ($offset -gt $from) { $why = '--from is before the dancer' }
    elseif ($env:STUB_LOOK_FAILS -and ($mp4 -like ('*' + $env:STUB_LOOK_FAILS + '*'))) { $why = 'stub failure' }
    if ($why) { '{"ok": false, "error": "' + $why + '"}'; $global:LASTEXITCODE = 2; return }
    $null = Get-Content -LiteralPath $look -Raw | ConvertFrom-Json
    $n = [int][math]::Round(($to - $from) * 30)
    if ($env:STUB_SHORT -and ($mp4 -like ('*' + $env:STUB_SHORT + '*'))) { $n = $n - 1 }
    Set-Content -LiteralPath $mp4 -Value $n
    '{"ok": true}'
    $global:LASTEXITCODE = 0
}
function ffprobe { $p = $args[-1]; if (Test-Path -LiteralPath $p) { Get-Content -LiteralPath $p } }
if ($env:STUB_NO_DISK) {
    Add-Type -Namespace MvChunks -Name Disk -MemberDefinition 'public static bool GetDiskFreeSpaceEx(string folder, out ulong available, out ulong total, out ulong free) { available = 0; total = 0; free = 0; return false; }'
}
if (-not $env:STUB_NO_FFMPEG) { function ffmpeg {
    Add-Content -LiteralPath $log -Value ('ffmpeg ' + ($args -join ' ')) -Encoding UTF8
    if ($env:STUB_JOIN_FAILS) { $global:LASTEXITCODE = 1; return }
    $sum = 0
    foreach ($line in Get-Content -LiteralPath $args[[array]::IndexOf($args, '-i') + 1] -Encoding UTF8) {
        if ($line -match "^file '(.*)'$") { $sum += [int](Get-Content -LiteralPath $Matches[1]) }
    }
    if ($env:STUB_JOIN_SHORT) { $sum = $sum - 1 }
    Set-Content -LiteralPath $args[-1] -Value $sum
    $global:LASTEXITCODE = 0
} }
"""


PARSE_FIRST = ("$parseErrors = $null; [void][System.Management.Automation.Language.Parser]::ParseFile(%s, [ref]$null, [ref]$parseErrors)\n"
               "if ($parseErrors) { 'WRAPPER: the driver does not parse: ' + (($parseErrors | ForEach-Object { $_.Message }) -join '; '); exit 98 }")


def run_powershell(script, env=None, timeout=300):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script],
                       capture_output=True, stdin=subprocess.DEVNULL, env=dict(os.environ, **(env or {})),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace") + (r.stdout + r.stderr).decode("cp932", "replace")


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class DriverTest(unittest.TestCase):
    """The written driver run for real, with python / ffprobe / ffmpeg replaced by PowerShell functions that do what they
    would: the batch writes its AVI, the fold refuses a missing AVI or look and writes an mp4 of (to - from) * 30
    frames, the join adds the frames of the listed mp4s up"""

    FILES = {"MMD/MikuMikuDance.exe": "mmd", "model/White.pmx": "pmx", "model/tex/skin.png": "skin",
             "dance.vmd": "dance", "lips.vmd": "lips", "camera.vmd": "camera", "stage/floor.x": "floor",
             "stage/floor_tex.png": "floor texture", "stage2/prop.x": "prop", "stage2/prop_tex.png": "prop texture",
             "cues.json": "{}", "look.json": '{"glow": {"strength": 0}}',
             "mmd_cli/__init__.py": "", "mmd_cli/app.py": "app", "tools/mv_look.py": "look", "tools/mv_text.py": "text"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp.replace("\\", "/")
        self.out = self.base + "/out"
        self.scripts = self.base + "/scripts"
        os.makedirs(self.out)
        for rel, text in self.FILES.items():           # the inputs exist, so that the stamp of -Resume can see them change
            self.put(rel, text)
        self.look = self.base + "/look.json"
        self.cues = self.base + "/cues.json"
        self.log = os.path.join(self.tmp, "calls.log")

    def put(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def write(self, shutter=0.5, **plan):
        b = self.base
        full = {"mmd": b + "/MMD/MikuMikuDance.exe", "model": b + "/model/White.pmx", "motions": [b + "/dance.vmd", b + "/lips.vmd"],
                "camera": b + "/camera.vmd", "accessories": [b + "/stage/floor.x", b + "/stage2/prop.x"], "look": self.look, "cues": self.cues,
                "out": self.out, "scripts": self.scripts, "mmd_cli": b}
        full.update(plan)
        self.plan = mv_chunks.check_plan(full)
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240,
                                       shutter=shutter)
        return self.summary

    def run_driver(self, switches="", before="", **env):
        wrapper = os.path.join(self.tmp, "wrapper.ps1")
        with open(wrapper, "w", encoding="utf-8-sig", newline="\r\n") as f:
            # review 13: a driver that does not parse leaves $LASTEXITCODE as it was, so the wrapper parses it first (exit 98).
            # Not try/catch around the call: that would also stop at a command that is not found, which -File does not
            f.write(STUBS + "\n%s\n%s\n& %s %s\nexit $LASTEXITCODE\n"
                    % (before, PARSE_FIRST % mv_chunks._ps(self.summary["driver"]), mv_chunks._ps(self.summary["driver"]), switches))
        open(self.log, "w").close()
        code, text = run_powershell(wrapper, dict(env, STUB_LOG=self.log))
        with open(self.log, encoding="utf-8-sig") as f:
            calls = [l.strip() for l in f if l.strip()]
        return code, text, calls

    def frames(self, name, folder=None):
        with open(os.path.join(folder or self.out, name), encoding="utf-8-sig") as f:
            return int(f.read().strip())

    def batches(self, calls):
        return [c for c in calls if c.startswith("python -m mmd_cli")]

    def test_every_chunk_is_rendered_folded_checked_and_joined(self):
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3)
        self.assertEqual([n for n in os.listdir(self.out) if n.endswith(".avi")], [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        self.assertIn("joined 300 frames", text)

    def test_every_chunk_folds_its_own_window_with_the_cues(self):
        # review 10: the cues on chunk 0 alone (the words gone from every later chunk) passed the tests
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        folds = [c[c.index("--cues"):c.index(" home=")] for c in calls if "mv_look.py render" in c]
        work, cues = self.out + "/look_work_t", self.cues
        self.assertEqual(folds, [
            "--cues %s --work %s --subframes 8 --shutter 0.5 --offset 0.000000 --from 0.000000 --to 3.333333" % (cues, work),
            "--cues %s --work %s --subframes 8 --shutter 0.5 --offset 0.000000 --from 3.333333 --to 8.333333" % (cues, work),
            "--cues %s --work %s --subframes 8 --shutter 0.5 --offset 4.333333 --from 8.333333 --to 10.000000" % (cues, work)])
        for i, c in enumerate(c for c in calls if "mv_look.py render" in c):
            self.assertIn("render %s/t_%02d.avi %s %s/t_%02d.mp4" % (self.out, i, self.look, self.out, i), c)

    def test_a_new_output_folder_is_made_before_the_disk_is_measured(self):
        self.out = self.base + "/fresh/out"
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_a_short_chunk_stops_the_run_and_keeps_its_avi(self):
        self.write()
        code, text, calls = self.run_driver(STUB_SHORT="t_01")
        self.assertEqual(code, 1, text)
        self.assertTrue(os.path.exists(os.path.join(self.out, "t_01.avi")))
        self.assertFalse(any("chunk_t_02" in c for c in calls), calls)
        self.assertFalse(any(c.startswith("ffmpeg") for c in calls), calls)
        self.assertIn("149 frames, want 150", text)

    def test_a_failed_batch_stops_the_run_before_folding(self):
        self.write()
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01.json")
        self.assertEqual(code, 1, text)
        self.assertFalse(any("t_01.avi" in c for c in calls if "mv_look.py" in c), calls)
        self.assertFalse(any(c.startswith("ffmpeg") for c in calls), calls)

    def test_a_failed_fold_stops_the_run_and_says_why_even_beside_an_old_mp4_of_the_right_length(self):
        # review 10: with the exit code of mv_look unread, an old mp4 of the same name filled the failed chunk
        self.write()
        with open(os.path.join(self.out, "t_01.mp4"), "w") as f:
            f.write("150")
        code, text, calls = self.run_driver(STUB_LOOK_FAILS="t_01")
        self.assertEqual(code, 1, text)
        self.assertIn("stub failure", text)                          # the reason mv_look gave
        self.assertTrue(os.path.exists(os.path.join(self.out, "t_01.avi")))
        self.assertFalse(any(c.startswith("ffmpeg") for c in calls), calls)

    def test_a_failed_join_stops_the_run_even_beside_an_old_joined_video(self):
        self.write()
        with open(os.path.join(self.out, "mv_t.mp4"), "w") as f:
            f.write("300")
        code, text, calls = self.run_driver(STUB_JOIN_FAILS="1")
        self.assertEqual(code, 1, text)
        self.assertIn("joining failed", text)
        self.assertNotIn("joined 300 frames", text)

    def test_a_joined_video_short_of_frames_fails_the_run(self):
        self.write()
        code, text, calls = self.run_driver(STUB_JOIN_SHORT="1")
        self.assertEqual(code, 1, text)
        self.assertIn("the joined video has 299 frames, want 300", text)

    def test_resume_skips_only_the_chunks_that_are_already_complete(self):
        self.write()
        self.assertEqual(self.run_driver(STUB_SHORT="t_01")[0], 1)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        batches = self.batches(calls)
        self.assertEqual(len(batches), 2, calls)                     # t_00 was complete; t_01 had 149 frames
        self.assertFalse(any("chunk_t_00" in c for c in batches))
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        code, text, calls = self.run_driver()                        # without -Resume every chunk is rendered again
        self.assertEqual(len(self.batches(calls)), 3)

    def test_resume_renders_again_after_the_inputs_change(self):
        # review 10: -Resume took the mp4s of the old motion because their frame counts were right
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        self.write(motions=["C:/work/song/dance_v2.vmd", LIPS])
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3, calls)
        code, text, calls = self.run_driver("-Resume")              # nothing changed since: nothing to render
        self.assertEqual(code, 0, text)
        self.assertEqual(self.batches(calls), [])

    def test_resume_renders_again_after_a_change_that_only_the_batch_shows(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        self.write(menu={"215": "on"})                               # the same files, another scene
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3, calls)

    def test_resume_renders_again_when_an_input_file_is_rewritten_in_place(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump({"glow": {"strength": 0.3}, "lens": {"grain": 0}}, f)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3, calls)

    def test_resume_renders_again_a_chunk_with_more_frames_than_its_span(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        with open(os.path.join(self.out, "t_00.mp4"), "w") as f:
            f.write("101")
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual([("chunk_t_00" in c) for c in self.batches(calls)], [True])

    def test_resume_is_decided_before_the_disk_is_measured(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        self.write(avi_bytes_per_pixel=1e6)                          # the same chunks, but no disk is ever enough
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.batches(calls), [])
        self.assertEqual(self.run_driver()[0], 3)
        self.write(avi_bytes_per_pixel=1e6, menu={"215": "on"})     # with -Resume, a chunk to render still needs the disk
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 3, text)
        self.assertEqual(self.batches(calls), [])

    def test_too_little_disk_for_the_avi_stops_before_rendering(self):
        self.write(avi_bytes_per_pixel=1e6)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.batches(calls), [])                      # only the look was checked: nothing was rendered
        self.assertFalse(any("mv_look.py render" in c for c in calls), calls)

    def test_the_disk_must_hold_the_avi_and_two_gibibytes_more(self):
        self.write()
        with open(self.summary["driver"], encoding="utf-8-sig") as f:
            needs = [int(m) for m in re.findall(r"^Run-Chunk .* (\d+) @\(", f.read(), re.M)]
        chunks = mv_chunks.plan_chunks(SPANS, lead=120)
        self.assertEqual(needs, [mv_chunks.avi_bytes(c, 240, (1280, 720)) + 2 * GIB for c in chunks])

    def test_paths_with_typographic_quotes_run(self):
        # review 10: PowerShell 5.1 takes U+2018 and U+2019 (in cp932) for a single quote: the driver did not parse
        self.out = self.base + "/Don\u2019t/out \u2018x\u2019"
        self.scripts = self.base + "/Don\u2019t/scripts"
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("mv_t.mp4", self.out), 300)

    def test_an_unc_output_folder_has_its_free_space_measured(self):
        # review 10: PSDrive is null for a UNC path, so the old driver always stopped for the disk
        unc = "//localhost/C$" + self.base[2:] + "/unc_out"
        if not self.base[1:2] == ":" or not os.path.isdir("//localhost/C$" + self.base[2:]):
            self.skipTest("no administrative share to reach this folder by UNC")
        self.out = unc
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("mv_t.mp4", self.base + "/unc_out"), 300)

    def test_leftovers_of_an_earlier_attempt_are_removed_before_the_chunk_is_rendered(self):
        self.write()
        for name in ("t_00.avi", "t_00.avi.mmdcli-failed", "t_00.avi.mmdcli-failed.1", "t_00.avi.mmdcli-old",
                     "t_000.avi.mmdcli-failed"):
            with open(os.path.join(self.out, name), "w") as f:
                f.write("old")
        os.chmod(os.path.join(self.out, "t_00.avi.mmdcli-failed.1"), 0o444)             # read-only goes too
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        left = sorted(n for n in os.listdir(self.out) if "mmdcli" in n)
        self.assertEqual(left, ["t_00.avi.mmdcli-old", "t_000.avi.mmdcli-failed"])      # somebody's original; not this chunk

    def test_a_leftover_held_open_by_another_program_stops_the_run_and_says_so(self):
        # review 11: a leftover that could not be removed was reported as removed
        self.write()
        held = open(self.put("out/t_00.avi.mmdcli-failed", "held"), "a")
        try:
            code, text, calls = self.run_driver()
        finally:
            held.close()
        self.assertEqual(code, 1, text)
        self.assertIn("could not remove", text)
        self.assertNotIn("t_00: removed", text)
        self.assertEqual(self.batches(calls), [])

    def test_a_folder_where_the_avi_goes_stops_the_run(self):
        self.write()
        self.put("out/t_00.avi/inside.txt", "a folder where the AVI goes")
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("is a folder", text)
        self.assertTrue(os.path.exists(os.path.join(self.out, "t_00.avi", "inside.txt")))
        self.assertEqual(self.batches(calls), [])

    def test_an_output_folder_that_cannot_be_made_stops_the_run_before_anything_else(self):
        free = [d for d in "QRSTUVWXYZ" if not os.path.exists(d + ":/")]
        if not free:
            self.skipTest("no unused drive letter")
        self.out = free[0] + ":/no/such/out"
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("could not make the output folder", text)
        self.assertEqual(calls, [])

    def test_the_avi_of_a_skipped_chunk_is_removed(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        self.put("out/t_01.avi", "left by hand")
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.batches(calls), [])
        self.assertFalse(os.path.exists(os.path.join(self.out, "t_01.avi")))

    def test_an_empty_recipe_means_render_again_without_an_error(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        self.put("out/t_00.mp4.recipe", "")
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual([("chunk_t_00" in c) for c in self.batches(calls)], [True])
        self.assertNotIn("null", text.lower())

    def test_a_look_that_does_not_work_stops_the_run_before_mmd_renders(self):
        # review 11: a wrong look was found by mv_look only after MMD had rendered chunk 0 (some minutes at 240 fps)
        self.put("look.json", "{not json")
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("the look is not JSON", text)
        self.assertEqual(self.batches(calls), [])

    def test_a_command_that_is_not_found_stops_the_run_even_after_an_exit_code_of_0(self):
        # review 10 and 11: a command that is not found leaves $LASTEXITCODE as it was; the driver clears it first
        self.write(python="C:/no/such/folder/python.exe")
        code, text, calls = self.run_driver(before="cmd /c exit 0")
        self.assertEqual(code, 1, text)
        self.assertIn("did not run", text)                         # review 12: not "the look does not work"
        self.assertNotIn("the look does not work", text)

    def test_a_python_path_with_a_typographic_quote_still_parses(self):
        # review 13: the "did not run" line doubled the ASCII quote only, so a ' in the path broke the whole driver
        self.write(python="C:/no/Don\u2019t/python.exe")
        code, text, calls = self.run_driver(before="cmd /c exit 0")
        self.assertEqual(code, 1, text)
        self.assertIn("did not run", text)
        self.assertNotIn("WRAPPER", text)

    def test_a_join_command_that_is_not_found_stops_the_run(self):
        # review 12: the join called without Invoke-Native kept the exit code 0 of the fold before it
        self.write()
        path = os.pathsep.join(os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), p)
                               for p in ("System32", "System32\\WindowsPowerShell\\v1.0", ""))
        code, text, calls = self.run_driver(STUB_NO_FFMPEG="1", PATH=path)
        self.assertEqual(code, 1, text)
        self.assertIn("joining failed", text)
        self.assertIn("did not run", text)

    def test_a_disk_whose_free_space_cannot_be_measured_is_named_as_such(self):
        # review 12: a stand-in for the kernel call that always fails
        self.write()
        code, text, calls = self.run_driver(STUB_NO_DISK="1")
        self.assertEqual(code, 3, text)
        self.assertIn("could not measure the free space", text)
        self.assertEqual(self.batches(calls), [])

    def test_one_argument_reaches_the_command_whole(self):
        # review 12: `$exe, $rest = $args` and `@rest` split a single argument into its characters
        self.write()
        with open(self.summary["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        start = driver.index("function Invoke-Native {")
        helper = driver[start:driver.index("\n}\n", start) + 3]           # read as text: the CRLF are LF here
        probe = os.path.join(self.tmp, "probe.ps1")
        with open(probe, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(helper + "\nfunction probe { 'count ' + $args.Count; foreach ($a in $args) { 'arg [' + $a + ']' } }\n"
                    "Invoke-Native probe 'one argument'\nInvoke-Native probe\nInvoke-Native probe a 'b c'\n")
        code, text = run_powershell(probe)
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith(("count", "arg"))]
        self.assertEqual(lines[:6], ["count 1", "arg [one argument]", "count 0", "count 2", "arg [a]", "arg [b c]"], text)

    def test_resume_renders_again_after_any_input_it_watches_changes(self):
        # review 11: the stamp watched the eight named files only; a texture, mmd_cli or MMD itself went unseen
        self.write()
        self.assertEqual(self.run_driver()[0], 0)

        def renders(label):
            code, text, calls = self.run_driver("-Resume")
            self.assertEqual(code, 0, (label, text))
            return len(self.batches(calls))
        self.assertEqual(renders("nothing changed"), 0)
        for rel in ("model/tex/skin.png", "stage/floor_tex.png", "mmd_cli/app.py", "tools/mv_text.py", "tools/mv_look.py",
                    "MMD/MikuMikuDance.exe", "cues.json"):
            with self.subTest(changed=rel):
                self.put(rel, self.FILES[rel] + " changed")
                self.assertEqual(renders(rel), 3)
        with self.subTest(changed="a motion of the same size"):                  # smooth_motion keeps the number of keys
            path = os.path.join(self.tmp, "dance.vmd")
            old = os.stat(path)
            self.put("dance.vmd", "DANCE")
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 10 ** 9))
            self.assertEqual(renders("motion"), 3)
        with self.subTest(changed="a size, at the old time"):
            path = os.path.join(self.tmp, "camera.vmd")
            old = os.stat(path)
            self.put("camera.vmd", "camera, longer")
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
            self.assertEqual(renders("camera"), 3)
        with self.subTest(changed="nothing but the bytecode python writes"):          # review 12
            self.put("tools/__pycache__/mv_text.cpython-312.pyc", "bytecode")
            self.put("mmd_cli/__pycache__/app.cpython-312.pyc", "bytecode")
            self.assertEqual(renders("pycache"), 0)
        with self.subTest(changed="a texture whose name holds __pycache__"):          # review 13: only the folder is bytecode
            self.put("model/tex/skin__pycache__.png", "a texture all the same")
            self.assertEqual(renders("texture named like the cache"), 3)
        with self.subTest(changed="the second motion"):
            self.put("lips.vmd", "lips changed")
            self.assertEqual(renders("second motion"), 3)
        with self.subTest(changed="a texture of the second accessory"):
            self.put("stage2/prop_tex.png", "prop texture changed")
            self.assertEqual(renders("second accessory"), 3)
        with self.subTest(changed="a texture of the same size, later"):
            path = os.path.join(self.tmp, "model", "tex", "skin.png")
            text = open(path, encoding="utf-8").read()
            old = os.stat(path)
            self.put("model/tex/skin.png", text.upper())
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 10 ** 9))
            self.assertEqual(renders("texture time"), 3)
        with self.subTest(changed="a hidden texture"):
            path = os.path.join(self.tmp, "model", "tex", "skin.png")
            hide = lambda flag: subprocess.run(["attrib", flag, path], check=True, capture_output=True,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            hide("+h")
            self.assertEqual(renders("texture hidden"), 0)
            hide("-h")
            self.put("model/tex/skin.png", "skin, hidden and changed")
            hide("+h")
            self.assertEqual(renders("hidden texture changed"), 3)
            hide("-h")
        with self.subTest(changed="the size of a texture, at the old time"):
            path = os.path.join(self.tmp, "model", "tex", "skin.png")
            old = os.stat(path)
            self.put("model/tex/skin.png", "a much longer skin texture")
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
            self.assertEqual(renders("texture size"), 3)
        with self.subTest(changed="a hidden look"):
            path = os.path.join(self.tmp, "look.json")
            subprocess.run(["attrib", "+h", path], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(renders("hidden"), 0)                               # seen as it was (it read as missing before)
            subprocess.run(["attrib", "-h", path], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.put("look.json", '{"glow": {"strength": 0.2}}')
            subprocess.run(["attrib", "+h", path], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(renders("hidden, changed"), 3)
        with self.subTest(changed="the shutter alone"):
            self.write(shutter=0.75)
            self.assertEqual(renders("shutter"), 3)

    def test_a_batch_that_is_not_the_one_the_driver_was_written_with_stops_the_run(self):
        self.write()
        with open(os.path.join(self.scripts, "chunk_t_01.txt"), "a", encoding="utf-8") as f:
            f.write('["menu", "set", "282", "off"]\n')
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("chunk_t_01.txt", text)
        self.assertFalse(any("chunk_t_01" in c for c in self.batches(calls)), calls)

    def test_the_home_of_mmd_cli_reaches_the_batch(self):
        self.write(mmd_cli_home=self.base + "/home")
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertTrue(all(c.endswith("home=" + self.base + "/home") for c in self.batches(calls)), calls)

    def test_a_python_given_by_path_is_quoted(self):
        self.write(python="C:/Program Files/Python 3/python.exe")
        with open(self.summary["driver"], encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("Invoke-Native 'C:/Program Files/Python 3/python.exe' -m mmd_cli", text)
        self.assertIn("Invoke-Native 'C:/Program Files/Python 3/python.exe' tools/mv_look.py render", text)


FAKE_MMD = r'''"""tests/test_mv_chunks.py: `python -m mmd_cli --out JSON batch FILE` without MMD (after review 10).  It reads the
batch as mmd_cli does and writes the AVI MMD would: BGRA, (to - from + 1) * fps / 30 frames, each frame telling its song
frame (G = 16 * (frame mod 16), B = 16 * (frame // 16 mod 16)) and its subframe (R = 256 / sub * subframe).  A motion
whose path holds "_v2" leaves the top half empty, so that a video of the old motion can be told from the new."""
import json
import os
import subprocess
import sys

argv = sys.argv[1:]
out_json, batch_file = argv[1], argv[3]
with open(batch_file, encoding="utf-8-sig") as f:
    lines = [json.loads(l) for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#")]
render = [l for l in lines if l[:2] == ["render", "avi"]][0]
avi = render[2]
start, end = int(render[render.index("--from") + 1]), int(render[render.index("--to") + 1])
fps = int(render[render.index("--fps") + 1])
w, h = int(render[render.index("--size") + 1]), int(render[render.index("--size") + 2])
sub = fps // 30
s0 = start * sub
k = "floor((N+%d)/%d)" % (s0, sub)
r = "%d*mod(N+%d,%d)" % (256 // sub if sub > 1 else 0, s0, sub)
g = "16*mod(%s,16)" % k
b = "16*mod(floor(%s/16),16)" % k
a = "255"
if any("_v2" in l[2] for l in lines if l[:2] == ["motion", "load"]):
    r, g, b = ("if(lt(Y,H/2),0,%s)" % e for e in (r, g, b))
    a = "if(lt(Y,H/2),0,255)"
done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "nullsrc=s=%dx%d:r=%d" % (w, h, fps),
                       "-frames:v", str((end - start + 1) * sub), "-vf",
                       "format=rgba,geq=r='%s':g='%s':b='%s':a='%s'" % (r, g, b, a),
                       "-c:v", "rawvideo", "-pix_fmt", "bgra", "-f", "avi", avi],
                      capture_output=True, text=True, stdin=subprocess.DEVNULL)
with open(out_json, "w", encoding="utf-8") as f:
    json.dump({"ok": done.returncode == 0, "stderr": done.stderr[-300:]}, f)
sys.exit(done.returncode)
'''
FLAT_LOOK = {"plate": {"base": [0, 0, 0], "haze": [0, 0, 0], "pool": [0, 0, 0], "vignette": 0},
             "beams": {"count": 0, "opacity": 0}, "bokeh": {"count": 0, "opacity": 0}, "glow": {"strength": 0},
             "lens": {"vignette": 0, "grain": 0}, "camera": {"punch": 0, "aberration": 0}}


@unittest.skipUnless(WINDOWS and FFMPEG and mv_look, "needs Windows PowerShell, ffmpeg, numpy and Pillow")
class EndToEndTest(unittest.TestCase):
    """review 10: the driver, python, the real tools/mv_look.py, ffmpeg and ffprobe, with only MMD replaced by a stand-in
    whose frames tell their song frame and subframe in their colour; the joined video is read back frame by frame"""
    W, H = 64, 36

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp.replace("\\", "/")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(os.path.join(fake, "mmd_cli"))
        os.makedirs(os.path.join(fake, "tools"))
        open(os.path.join(fake, "mmd_cli", "__init__.py"), "w").close()
        with open(os.path.join(fake, "mmd_cli", "__main__.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_MMD)
        for name in ("mv_look.py", "mv_text.py"):
            shutil.copyfile(os.path.join(ROOT, "tools", name), os.path.join(fake, "tools", name))
        self.look = self.base + "/look.json"
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump(FLAT_LOOK, f)
        self.fake = self.base + "/fake"

    def render(self, motions, switches=""):
        plan = mv_chunks.check_plan({"mmd": "C:/MMD/MikuMikuDance.exe", "model": "C:/MMD/model.pmx", "motions": motions,
                                     "camera": "C:/work/camera.vmd", "look": self.look, "out": self.base + "/out",
                                     "scripts": self.base + "/scripts", "mmd_cli": self.fake, "size": [self.W, self.H]})
        spans = mv_chunks.spans_from_cuts([40, 90], 119)
        summary = mv_chunks.write(plan, mv_chunks.plan_chunks(spans, lead=30), self.base + "/scripts", "t", 240, 0.5)
        wrapper = os.path.join(self.tmp, "run.ps1")
        with open(wrapper, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("%s\n& %s %s\nexit $LASTEXITCODE\n"
                    % (PARSE_FIRST % mv_chunks._ps(summary["driver"]), mv_chunks._ps(summary["driver"]), switches))
        code, text = run_powershell(wrapper, timeout=600)
        self.assertEqual(code, 0, text)
        return summary["joined"], text

    def read_back(self, mp4):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
        n = self.W * self.H * 3
        frames = []
        for i in range(len(raw) // n):
            px = raw[i * n:(i + 1) * n]
            def mean(rows, channel):
                vals = [px[(y * self.W + x) * 3 + channel] for y in rows for x in range(4, self.W - 4)]
                return sum(vals) / float(len(vals))
            bottom, top = range(self.H // 2 + 2, self.H - 2), range(2, self.H // 2 - 2)
            frame = int(round(mean(bottom, 1) / 16.0)) % 16 + 16 * (int(round(mean(bottom, 2) / 16.0)) % 16)
            frames.append((frame, mean(bottom, 0), sum(mean(top, c) for c in range(3)) / 3.0))
        return frames

    def test_the_joined_video_shows_every_song_frame_once_folded_from_its_first_subframes(self):
        joined, text = self.render(["C:/work/dance.vmd"])
        frames = self.read_back(joined)
        self.assertEqual([f for f, _, _ in frames], list(range(120)))
        # 240 fps folded with shutter 0.5: the mean of subframes 0..3, whose red is 0, 32, 64 and 96
        self.assertTrue(all(abs(red - 48) < 6 for _, red, _ in frames), [round(red) for _, red, _ in frames])
        self.assertTrue(all(top > 10 for _, _, top in frames))

    def test_resume_after_the_motion_changed_shows_the_new_motion(self):
        self.render(["C:/work/dance.vmd"])
        joined, text = self.render(["C:/work/dance_v2.vmd"], "-Resume")
        frames = self.read_back(joined)
        self.assertEqual([f for f, _, _ in frames], list(range(120)))
        self.assertTrue(all(top < 4 for _, _, top in frames), [round(top) for _, _, top in frames])   # all of it is new


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plan = os.path.join(self.tmp, "plan.json")
        self.report = os.path.join(self.tmp, "report.json")
        self.save(PLAN)
        with open(self.report, "w", encoding="utf-8") as f:
            json.dump(REPORT, f)

    def save(self, plan):
        with open(self.plan, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)

    def main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mv_chunks.main(list(argv))
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_the_scripts_are_written_and_the_totals_reported(self):
        outdir = os.path.join(self.tmp, "scripts")
        code, res = self.main(self.plan, outdir, "--shots", self.report, "--tag", "t")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["chunks"], res["frames"], res["subframes"]), (3, 300, 8))
        self.assertEqual(res["largest_avi_gb"], round(250 * 8 * 1280 * 720 * 4 / 1e9, 1))
        names = sorted(os.listdir(outdir))
        self.assertEqual(names, ["chunk_t_00.txt", "chunk_t_01.txt", "chunk_t_02.txt", "concat_t.txt", "render_t.ps1"])
        with open(os.path.join(outdir, "render_t.ps1"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 reads a script without a BOM as ANSI")
        self.assertIn(b"\r\n", raw)
        with open(os.path.join(outdir, "concat_t.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["file 'C:/work/song/out/t_%02d.mp4'" % i for i in range(3)])
        with open(os.path.join(outdir, "chunk_t_01.txt"), "rb") as f:
            self.assertIn(hashlib.sha256(f.read()).hexdigest().upper().encode(), raw)   # the driver knows its batches

    def test_cuts_can_stand_in_for_a_camera_report(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--cuts", "100", "250", "--last", "299", "--fps", "60")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["chunks"], res["frames"], res["subframes"]), (3, 300, 2))

    def test_a_frame_rate_mmd_does_not_render_is_refused(self):
        for fps in ("100", "90", "960"):
            code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--fps", fps)
            self.assertEqual(code, 2, fps)
            self.assertFalse(res["ok"])

    def test_cuts_need_the_last_frame_and_shots_do_not_take_one(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--cuts", "100")
        self.assertEqual(code, 2)
        self.assertIn("--last", res["error"])
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--last", "50")
        self.assertEqual(code, 2)
        self.assertIn("--last", res["error"])

    def test_a_shutter_outside_zero_to_one_or_too_short_for_a_subframe_is_refused(self):
        for fps, shutter in (("240", "1.5"), ("240", "0.05"), ("60", "0.2")):
            code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--fps", fps,
                                  "--shutter", shutter)
            self.assertEqual(code, 2, (fps, shutter))

    def test_a_tag_with_a_newline_is_refused(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--tag", "final\n")
        self.assertEqual(code, 2)
        self.assertIn("--tag", res["error"])

    def test_a_plan_of_the_wrong_type_is_an_error_in_json(self):
        for plan in (dict(PLAN, size="12"), dict(PLAN, menu=[1]), [PLAN]):
            self.save(plan)
            code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report)
            self.assertEqual(code, 2, plan)
            self.assertFalse(res["ok"])

    def test_an_absurd_number_of_bytes_per_pixel_is_an_error_in_json(self):
        self.save(dict(PLAN, avi_bytes_per_pixel=1e300))
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report)
        self.assertEqual(code, 2)
        self.assertIn("avi_bytes_per_pixel", res["error"])

    def test_a_report_of_the_wrong_type_is_an_error_in_json(self):
        with open(self.report, "w", encoding="utf-8") as f:
            json.dump([1, 2], f)
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report)
        self.assertEqual(code, 2)
        self.assertIn("shots", res["error"])


if __name__ == "__main__":
    unittest.main()
