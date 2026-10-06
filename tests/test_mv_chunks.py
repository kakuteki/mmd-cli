"""tools/mv_chunks.py: a long render split at the camera cuts, each chunk rendered fast, folded with blur, checked, joined."""
import contextlib
import importlib.util
import io
import json
import os
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

LIPS = "C:/work/song/kazusa/ヒビカセ（Choreography by ATY）/ヒビカセ　Face&Lips 歌ってる方.vmd"
PLAN = {
    "mmd": "C:/MMD/MikuMikuDance.exe",
    "model": "C:/MMD/UserFile/Model/Rin/White.pmx",
    "motions": ["C:/work/song/dance.vmd", LIPS],
    "camera": "C:/work/song/camera.vmd",
    "accessories": ["C:/work/song/stage_floor.x"],
    "look": "C:/work/song/look.json",
    "cues": "C:/work/song/cues.json",
    "out": "C:/work/song/out",
    "scripts": "C:/work/song/mv",
    "mmd_cli": "C:/work/mmd-cli",
}
REPORT = {"shots": [{"start": 0, "end": 99}, {"start": 100, "end": 249}, {"start": 250, "end": 299}]}
SPANS = [(0, 99), (100, 249), (250, 299)]


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

    def test_the_avi_holds_every_subframe_of_the_lead_in_and_the_span(self):
        chunk = {"first": 130, "cut": 250, "end": 299}
        self.assertEqual(mv_chunks.avi_bytes(chunk, fps=240, size=(1280, 720)), 170 * 8 * 1280 * 720 * 4)


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
            ["accessory", "load", "C:/work/song/stage_floor.x"],
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

    def test_missing_plan_entries_are_named(self):
        plan = dict(PLAN)
        del plan["camera"], plan["look"]
        with self.assertRaises(ValueError) as ctx:
            mv_chunks.check_plan(plan)
        self.assertIn("camera", str(ctx.exception))
        self.assertIn("look", str(ctx.exception))

    def test_a_plan_without_a_motion_is_refused(self):
        with self.assertRaises(ValueError):
            mv_chunks.check_plan(dict(PLAN, motions=[]))


STUBS = r"""
$log = $env:STUB_LOG
function python {
    Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ')) -Encoding UTF8
    if ($args[0] -eq '-m') {
        if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) { $global:LASTEXITCODE = 1; return }
        $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
        Set-Content -LiteralPath (($render | ConvertFrom-Json)[2]) -Value 'avi'
        $global:LASTEXITCODE = 0
        return
    }
    $mp4 = $args[4]
    $from = [double]$args[[array]::IndexOf($args, '--from') + 1]
    $to = [double]$args[[array]::IndexOf($args, '--to') + 1]
    $n = [int][math]::Round(($to - $from) * 30)
    if ($env:STUB_SHORT -and ($mp4 -like ('*' + $env:STUB_SHORT + '*'))) { $n = $n - 1 }
    Set-Content -LiteralPath $mp4 -Value $n
    $global:LASTEXITCODE = 0
}
function ffprobe { $p = $args[-1]; if (Test-Path -LiteralPath $p) { Get-Content -LiteralPath $p } }
function ffmpeg {
    Add-Content -LiteralPath $log -Value ('ffmpeg ' + ($args -join ' ')) -Encoding UTF8
    $sum = 0
    foreach ($line in Get-Content -LiteralPath $args[[array]::IndexOf($args, '-i') + 1] -Encoding UTF8) {
        if ($line -match "^file '(.*)'$") { $sum += [int](Get-Content -LiteralPath $Matches[1]) }
    }
    if ($env:STUB_JOIN_SHORT) { $sum = $sum - 1 }
    Set-Content -LiteralPath $args[-1] -Value $sum
    $global:LASTEXITCODE = 0
}
"""


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "the driver is Windows PowerShell on the render machine")
class DriverTest(unittest.TestCase):
    """The written driver run for real, with python / ffprobe / ffmpeg replaced by PowerShell functions that do what they
    would (the batch writes its AVI, the fold writes an mp4 of (to - from) * 30 frames, the join adds them up)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp.replace("\\", "/")
        self.out = self.base + "/out"
        os.makedirs(self.out)
        self.log = os.path.join(self.tmp, "calls.log")

    def write(self, **plan):
        full = mv_chunks.check_plan(dict(PLAN, out=self.out, scripts=self.base, mmd_cli=self.base, **plan))
        return mv_chunks.write(full, mv_chunks.plan_chunks(SPANS, lead=120), self.tmp, tag="t", fps=240, shutter=0.5)

    def run_driver(self, switches="", **env):
        wrapper = os.path.join(self.tmp, "wrapper.ps1")
        with open(wrapper, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(STUBS + "\n& '%s/render_t.ps1' %s\nexit $LASTEXITCODE\n" % (self.base, switches))
        if os.path.exists(self.log):
            os.remove(self.log)
        open(self.log, "w").close()
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", wrapper],
                           capture_output=True, stdin=subprocess.DEVNULL, env=dict(os.environ, STUB_LOG=self.log, **env),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=120)
        with open(self.log, encoding="utf-8-sig") as f:
            calls = [l.strip() for l in f if l.strip()]
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"), calls

    def frames(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8-sig") as f:
            return int(f.read().strip())

    def test_every_chunk_is_rendered_folded_checked_and_joined(self):
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(len([c for c in calls if c.startswith("python -m mmd_cli")]), 3)
        folds = [c for c in calls if "mv_look.py render" in c]
        self.assertEqual(len(folds), 3)
        self.assertIn("--subframes 8 --shutter 0.5 --offset 4.333333 --from 8.333333 --to 10.000000", folds[2])
        self.assertIn("--cues C:/work/song/cues.json", folds[0])
        self.assertEqual([n for n in os.listdir(self.out) if n.endswith(".avi")], [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        self.assertIn("joined 300 frames", text)

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

    def test_resume_skips_only_the_chunks_that_are_already_complete(self):
        self.write()
        self.assertEqual(self.run_driver(STUB_SHORT="t_01")[0], 1)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        batches = [c for c in calls if c.startswith("python -m mmd_cli")]
        self.assertEqual(len(batches), 2, calls)                 # t_00 was complete; t_01 had 149 frames
        self.assertFalse(any("chunk_t_00" in c for c in batches))
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        code, text, calls = self.run_driver()                    # without -Resume every chunk is rendered again
        self.assertEqual(len([c for c in calls if c.startswith("python -m mmd_cli")]), 3)

    def test_a_joined_video_short_of_frames_fails_the_run(self):
        self.write()
        code, text, calls = self.run_driver(STUB_JOIN_SHORT="1")
        self.assertEqual(code, 1, text)
        self.assertIn("the joined video has 299 frames, want 300", text)

    def test_too_little_disk_for_the_avi_stops_before_rendering(self):
        self.write(size=[100000, 100000])
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(calls, [])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plan = os.path.join(self.tmp, "plan.json")
        self.report = os.path.join(self.tmp, "report.json")
        with open(self.plan, "w", encoding="utf-8") as f:
            json.dump(PLAN, f, ensure_ascii=False)
        with open(self.report, "w", encoding="utf-8") as f:
            json.dump(REPORT, f)

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

    def test_cuts_can_stand_in_for_a_camera_report(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--cuts", "100", "250", "--last", "299", "--fps", "60")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["chunks"], res["frames"], res["subframes"]), (3, 300, 2))

    def test_a_frame_rate_that_is_not_a_multiple_of_30_is_refused(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--fps", "100")
        self.assertEqual(code, 2)
        self.assertFalse(res["ok"])

    def test_cuts_need_the_last_frame(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--cuts", "100")
        self.assertEqual(code, 2)
        self.assertIn("--last", res["error"])

    def test_a_shutter_outside_zero_to_one_is_refused(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--shutter", "1.5")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
