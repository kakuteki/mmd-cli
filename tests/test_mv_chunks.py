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
import time
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
# The SHA-256 of the scripts the default (30 fps) writes, as the tool wrote them before --out-fps (main 60956b2): the 30 fps
# render of the MV runs from scripts of this tool, so they stay the same byte for byte.  (The plan of that render, written
# again with the tool of 60956b2, gave the 23 files it runs from, byte for byte: _spike/out/stage5/out_fps/golden_30.py.)
GOLDEN_30 = {
    "t": {"chunk_t_00.txt": "0bf0308d6ea9d57f259be7bb76367f404fe9d3f8cc5f6d7ae464c7136b94438f",
          "chunk_t_01.txt": "accc198b507625ad32973d2471daa2ca18c0552e4b6b592960bc04c879a351c5",
          "chunk_t_02.txt": "2bc1d35bd2664a9106dfb2bcefe42068ddb23e8d9b0f2bfac0678120d12db0f3",
          "concat_t.txt": "8c714127c433bd6b1536ed5a0a86deab54d84d0b9a0789a80adeac8d3d110573",
          "render_t.ps1": "f8830f610b7319707d63152d6a6da5379be7d80f96fcb9cf8b29256bc607adb4"},
    "b2": {"chunk_b2_00.txt": "6a0d67867bdea71b3bee1c7f0d686d1495bb0643df039ede1ce020cf511b77e0",
           "chunk_b2_01.txt": "0744a9869afba685f3f48951e1ff9311d44891217e1eea397568c18e7e87668a",
           "chunk_b2_02.txt": "220a6d7f2c408957bd3745af4d3ed8e2230c168fcd5127ffe6fed4eb01b54833",
           "concat_b2.txt": "43935d24226981ac78ce82da256fb8d4302bcf8c71f87791fb42d88cd8b43587",
           "render_b2.ps1": "17ec89ab44a5013a3bb729f77b1b4f90e2c4a352571c0956cbb9e4ff1eecd95f"},
}
PLAN_B2 = dict(PLAN, python="C:/Program Files/Python 3/python.exe", mmd_cli_home="C:/work/home", name="song", size=[640, 360],
               menu={"298": "on"}, cues=None)
# The same at --out-fps 60, written with the tool of main afd25c4, before --workers and --encoder
# (_spike/out/stage5/fast_render/golden_60.py): the version to watch keeps its scripts too
GOLDEN_60 = {
    "t": {"chunk_t_60fps_00.txt": "41511cb5ea6ffb62253fc00e7be3f8f7b18623038c99afbc5275897587dd5472",
          "chunk_t_60fps_01.txt": "5816909f53c59f63b137edfc91ea1898c924aa2d0e93ad6161c067050c7281ee",
          "chunk_t_60fps_02.txt": "3c13392f9a2039c50d87b585234e418ddc8ef6982bdc49f6c2bd2e9def858cc0",
          "concat_t_60fps.txt": "ad86cae087c8f5012190c6cc6d61d030c1b02b5729d7f41a0ad8bc5939de005b",
          "render_t_60fps.ps1": "21309a52b2a6e4503c42c1128f6252b12d490658a8ce0cb8e770e63fa44fa1b5"},
    "b2": {"chunk_b2_60fps_00.txt": "3b20b916c359d8cc6cf4f4ab59186dee1865bd15d39b347127604d28e86ddd42",
           "chunk_b2_60fps_01.txt": "34a3cb0ea79f11a51c65d3ae1b17ed7611bcb2700a0d01a150713b3023e3c52d",
           "chunk_b2_60fps_02.txt": "d2c4c79ae1c75ee5b145969f467fcdfdf99973ed337ed0adf00c4b7ee93c9fcf",
           "concat_b2_60fps.txt": "9ae0c07ef9cc58bd266cd5d24b4b3f419cf4652eb75b3977d0a3df38a56ecf98",
           "render_b2_60fps.ps1": "0500d2b4de8c844118aa9dc4ec91b2514a3336b404125b0c06d08a856cda0eac"},
}


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


def hashes(folder):
    files = {}
    for name in os.listdir(folder):
        with open(os.path.join(folder, name), "rb") as f:
            files[name] = hashlib.sha256(f.read()).hexdigest()
    return files


def value(args, key):
    return args[args.index(key) + 1]


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class OutFpsTest(unittest.TestCase):
    """--out-fps 60 makes a version to watch at home (the one to publish stays at 30 fps, as the motion asks).  MMD renders
    the same AVI and the chunks are the same frames of the song; every frame of the song becomes two frames of the video,
    each folded from half as many subframes"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, label, plan=PLAN, spans=SPANS, lead=120, fps=240, shutter=0.5, tag="t", **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(plan), mv_chunks.plan_chunks(spans, lead), folder, tag, fps, shutter, **kw)
        return summary, hashes(folder)

    def test_the_default_writes_the_scripts_of_before_byte_for_byte(self):
        for label, kw in (("default", {}), ("thirty", {"out_fps": 30})):
            self.assertEqual(self.written(label, **kw)[1], GOLDEN_30["t"], label)
        b2 = self.written("b2", PLAN_B2, mv_chunks.spans_from_cuts([40, 90], 119), 30, 120, 0.75, "b2")[1]
        self.assertEqual(b2, GOLDEN_30["b2"])

    def test_mmd_renders_the_same_avi_at_60(self):
        thirty, sixty = self.written("30")[0], self.written("60", out_fps=60)[0]
        for a, b in zip(thirty["batches"], sixty["batches"]):
            with open(a, encoding="utf-8") as f, open(b, encoding="utf-8") as g:
                self.assertEqual(f.read().replace("/t_", "/t_60fps_"), g.read())       # only the name of the AVI differs
        self.assertEqual(sixty["largest_avi_gb"], thirty["largest_avi_gb"])
        self.assertEqual((sixty["fps"], sixty["spans"]), (240, [[0, 99], [100, 249], [250, 299]]))

    def test_every_frame_of_the_song_is_two_frames_folded_from_half_the_subframes(self):
        plan = mv_chunks.check_plan(dict(PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[2]                           # 130..299, the shot from 250
        thirty = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5)
        sixty = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5, out_fps=60)
        self.assertEqual((value(thirty, "--subframes"), value(sixty, "--subframes")), ("8", "4"))
        for key in ("--cues", "--work", "--shutter", "--offset", "--from", "--to"):    # seconds of the song, as at 30
            self.assertEqual(value(sixty, key), value(thirty, key), key)
        self.assertEqual([value(sixty, k) for k in ("--offset", "--from", "--to")], ["4.333333", "8.333333", "10.000000"])
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 240, 0.5, out_fps=60), mv_chunks.recipe(plan, "t", chunk, 240, 0.5))

    def test_the_driver_wants_twice_the_frames_and_checks_the_look_at_60(self):
        summary = self.written("60", out_fps=60)[0]
        self.assertEqual((summary["out_fps"], summary["fps"], summary["subframes"], summary["frames"]), (60, 240, 4, 600))
        with open(summary["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        self.assertEqual(driver.splitlines()[0], "# 3 chunks at 240 fps folded to 60 fps (4 subframes, shutter 0.5), 600 frames, "
                                                 "joined to C:/work/song/out/mv_t_60fps.mp4.")
        runs = re.findall(r"^Run-Chunk (?:'[^']*' ){7}(\d+) (\d+) @\(", driver, re.M)
        self.assertEqual([int(want) for want, _ in runs], [200, 300, 100])
        # the AVI is the one of 30 fps: the disk must hold as much
        self.assertEqual([int(need) for _, need in runs],
                         [mv_chunks.avi_bytes(c, 240, (1280, 720)) + 2 * GIB for c in mv_chunks.plan_chunks(SPANS, lead=120)])
        self.assertIn("if ($n -ne 600) { 'STOP: the joined video has {0} frames, want {1}' -f $n, 600; exit 1 }", driver)
        check = [l for l in driver.splitlines() if l.startswith("$check = ")]
        self.assertEqual(len(check), 1)
        self.assertTrue(check[0].endswith(" --size 1280x720 --fps 60"), check)          # the layers the fold will use

    def test_the_files_of_60_fps_are_named_apart_from_those_of_30(self):
        # the command of a 30 fps render with --out-fps 60 added: it must not remove that render's chunks, its joined
        # video or its driver
        thirty, files30 = self.written("both")
        sixty, both = self.written("both", out_fps=60)
        self.assertEqual({n: both[n] for n in files30}, GOLDEN_30["t"])                 # the files of 30 fps as they were
        self.assertEqual(sorted(set(both) - set(files30)), ["chunk_t_60fps_00.txt", "chunk_t_60fps_01.txt",
                                                             "chunk_t_60fps_02.txt", "concat_t_60fps.txt", "render_t_60fps.ps1"])
        self.assertEqual(sixty["joined"], "C:/work/song/out/mv_t_60fps.mp4")
        with open(sixty["concat"], encoding="utf-8") as f:
            self.assertEqual([l for l in f.read().splitlines() if l.startswith("file ")],
                             ["file 'C:/work/song/out/t_60fps_%02d.mp4'" % i for i in range(3)])
        with open(sixty["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        self.assertIn("'C:/work/song/out/t_60fps_00.avi'", driver)
        self.assertIn("'C:/work/song/out/look_work_t_60fps'", driver)
        self.assertNotIn("'C:/work/song/out/t_00.mp4'", driver)

    def test_the_join_list_of_60_fps_gives_every_chunk_its_length(self):
        # the edit list of an mp4 is in ms: a 60 fps chunk of 40 frames of the song came out 1333 ms long (20475 of 20480
        # ticks), and concat put every later chunk 5 ticks early.  Given its duration, concat uses that instead
        plan = mv_chunks.check_plan(dict(PLAN))
        chunks = mv_chunks.plan_chunks(SPANS, lead=120)
        self.assertEqual(mv_chunks.concat_text(plan, chunks, "t_60fps", out_fps=60).splitlines(), [
            "file 'C:/work/song/out/t_60fps_00.mp4'", "duration 3.333333",
            "file 'C:/work/song/out/t_60fps_01.mp4'", "duration 5.000000",
            "file 'C:/work/song/out/t_60fps_02.mp4'", "duration 1.666667"])
        self.assertEqual(mv_chunks.concat_text(plan, chunks, "t"), mv_chunks.concat_text(plan, chunks, "t", out_fps=30))
        self.assertNotIn("duration", mv_chunks.concat_text(plan, chunks, "t"))

    def test_the_output_is_30_or_60_fps_and_mmd_renders_at_least_as_fast(self):
        plan = mv_chunks.check_plan(dict(PLAN))
        chunks = mv_chunks.plan_chunks(SPANS, lead=0)
        folder = os.path.join(self.tmp, "s")
        for out_fps in (0, 24, 25, 50, 120, "60", 60.0, True, None):
            with self.assertRaises(ValueError, msg=out_fps) as ctx:
                mv_chunks.write(plan, chunks, folder, "t", 240, 0.5, out_fps=out_fps)
            self.assertIn("--out-fps", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            mv_chunks.write(plan, chunks, folder, "t", 30, 0.5, out_fps=60)
        self.assertIn("--fps", str(ctx.exception))
        summary = mv_chunks.write(plan, chunks, folder, "t", 60, 0.5, out_fps=60)       # 60 to 60: no blur, as 30 to 30
        self.assertEqual((summary["subframes"], summary["frames"]), (1, 600))


class WorldPlanTest(unittest.TestCase):
    """"world": true in the plan (a look whose stage lies in the world, tools/mv_world.py): every fold and the look check
    hand mv_look the camera motion and the dancer it is drawn from; the prepare of --workers also the shutter and the span of
    the chunks.  Without it the scripts are those of before (the golden tests above)"""

    WORLD = dict(PLAN, world=True, accessories=[])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, label, **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(self.WORLD), mv_chunks.plan_chunks(SPANS, 120), folder, "t", 240, 0.5, **kw)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            return f.read()

    def test_world_is_true_or_false(self):
        self.assertIs(mv_chunks.check_plan(dict(PLAN))["world"], False)
        self.assertIs(mv_chunks.check_plan(dict(PLAN, world=True))["world"], True)
        for bad in ("yes", 1, None):
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(PLAN, world=bad))

    def test_every_fold_reads_the_camera_and_the_dancer(self):
        plan = mv_chunks.check_plan(self.WORLD)
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[2]
        fold = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5)
        plain = mv_chunks.fold_args(mv_chunks.check_plan(dict(PLAN, accessories=[])), "t", chunk, 240, 0.5)
        self.assertEqual(fold[:len(plain)], plain)
        self.assertEqual(fold[len(plain):], ["--camera", PLAN["camera"], "--model", PLAN["model"],
                                             "--motion", "C:/work/song/dance.vmd", "--motion", LIPS, "--jobs", "4"])
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 240, 0.5),
                            mv_chunks.recipe(mv_chunks.check_plan(dict(PLAN, accessories=[])), "t", chunk, 240, 0.5))

    def test_the_look_check_reads_them_before_mmd_renders(self):
        driver = self.written("one")
        check = [l for l in driver.splitlines() if l.startswith("$check = ")]
        self.assertEqual(len(check), 1)
        self.assertTrue(check[0].endswith("--size 1280x720 --fps 30 --camera 'C:/work/song/camera.vmd' --model "
                                          "'C:/MMD/UserFile/Model/Rin/White.pmx' --motion 'C:/work/song/dance.vmd' --motion '%s' "
                                          "--jobs 4" % LIPS), check)

    def test_stage_jobs_hand_mv_look_the_processes_that_draw_the_stage(self):
        # 4 by default with "world": true (the review's measure on hinata: 4 cores and under 2 GB, the whole song in 12 to
        # 15 minutes, 3 to 4 times one process); a plan fixed to the picture draws no stage and hands none
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[1]
        self.assertEqual(mv_chunks.check_plan(self.WORLD)["stage_jobs"], 4)
        self.assertEqual(mv_chunks.fold_args(mv_chunks.check_plan(self.WORLD), "t", chunk, 240, 0.5)[-2:], ["--jobs", "4"])
        plan = mv_chunks.check_plan(dict(self.WORLD, stage_jobs=8))
        self.assertEqual(mv_chunks.fold_args(plan, "t", chunk, 240, 0.5)[-2:], ["--jobs", "8"])
        self.assertNotIn("--jobs", mv_chunks.fold_args(mv_chunks.check_plan(dict(self.WORLD, stage_jobs=1)), "t", chunk, 240, 0.5))
        self.assertEqual(mv_chunks.check_plan(dict(PLAN))["stage_jobs"], 1)
        self.assertNotIn("--jobs", mv_chunks.fold_args(mv_chunks.check_plan(dict(PLAN)), "t", chunk, 240, 0.5))
        for bad in ({"stage_jobs": 0}, {"stage_jobs": 2.5}, {"stage_jobs": True}, {"stage_jobs": 2, "world": False}):
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(self.WORLD, **bad))

    def test_a_stage_of_a_model_hands_mv_look_its_set_and_mmds_pictures_of_it(self):
        # "stage_set" and "stage_pictures" (tools/stage_layer.py: a look with layer.on 1): every fold and the look check pass
        # them on after the camera and the dancer; without them the folds are those of before
        city = dict(self.WORLD, stage_set="C:/work/song/stage/city.json", stage_pictures="C:/work/song/stage/pictures")
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[1]
        fold = mv_chunks.fold_args(mv_chunks.check_plan(city), "t", chunk, 240, 0.5)
        world = mv_chunks.fold_args(mv_chunks.check_plan(self.WORLD), "t", chunk, 240, 0.5)
        self.assertEqual(fold, world + ["--stage-set", "C:/work/song/stage/city.json", "--stage-pictures",
                                        "C:/work/song/stage/pictures"])
        folder = os.path.join(self.tmp, "city")
        summary = mv_chunks.write(mv_chunks.check_plan(city), mv_chunks.plan_chunks(SPANS, 120), folder, "t", 240, 0.5)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            check = [l for l in f.read().splitlines() if l.startswith("$check = ")]
        self.assertTrue(check[0].endswith("--stage-set 'C:/work/song/stage/city.json' --stage-pictures "
                                          "'C:/work/song/stage/pictures'"), check)
        for bad in ({"stage_set": "C:/work/song/stage/city.json"},                       # the pictures missing
                    {"stage_pictures": "C:/work/song/stage/pictures"},                   # the set missing
                    {"stage_set": "stage/city.json", "stage_pictures": "C:/work/song/stage/pictures"}):   # not absolute
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(self.WORLD, **bad))
        with self.assertRaises(ValueError):                         # a stage of a model lies in the world
            mv_chunks.check_plan(dict(PLAN, stage_set="C:/work/song/stage/city.json", stage_pictures="C:/work/song/stage/p"))

    def test_the_workers_prepare_the_stage_of_their_chunks_with_their_shutter(self):
        driver = self.written("two", workers=2)
        prepare = [l for l in driver.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertEqual(len(prepare), 1)
        self.assertIn(" --camera 'C:/work/song/camera.vmd' ", prepare[0])
        spans = " --span 0.000000 3.333333 --span 3.333333 8.333333 --span 8.333333 10.000000"
        self.assertTrue(prepare[0].endswith("--jobs 4 --subframes 8 --shutter 0.5" + spans), prepare)
        sixty = self.written("sixty", workers=2, out_fps=60)
        prepare = [l for l in sixty.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertTrue(prepare[0].endswith("--subframes 4 --shutter 0.5" + spans), prepare)

    def test_the_workers_prepare_only_the_stage_of_their_chunks(self):
        # chunks apart in the song (the excerpts of a preview): the stage between them is not drawn.  The review of
        # stage-world drew 3,901 frames for the 242 of two chunks of camera A, 84 % of the run
        folder = os.path.join(self.tmp, "apart")
        summary = mv_chunks.write(mv_chunks.check_plan(self.WORLD), mv_chunks.plan_chunks([(2100, 2220), (5880, 6000)], 120),
                                  folder, "t", 240, 0.5, workers=2)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            prepare = [l for l in f.read().splitlines() if "tools/mv_look.py prepare" in l]
        self.assertTrue(prepare[0].endswith("--span 70.000000 74.033333 --span 196.000000 200.033333"), prepare)
        self.assertNotIn(" --from ", prepare[0])


class SelfShadowPlanTest(unittest.TestCase):
    """"self_shadow" in the plan (tools/mme_shadow.py): before MMD renders, the driver checks that it will draw the model's
    body shadow as the plan says ("soft": through MME with the effect beside the model; "mmd": MMD's own), and with "soft"
    -Resume watches MME's files beside MMD.  Without it the scripts are those of before (the golden tests above)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, plan, label, **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(plan), mv_chunks.plan_chunks(SPANS, 120), folder, "t", 240, 0.5, **kw)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            return f.read()

    def test_self_shadow_is_mmd_or_soft_or_left_out(self):
        self.assertIsNone(mv_chunks.check_plan(dict(PLAN))["self_shadow"])
        for want in ("mmd", "soft"):
            self.assertEqual(mv_chunks.check_plan(dict(PLAN, self_shadow=want))["self_shadow"], want)
        for bad in ("hard", "Soft", 1, True):
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(PLAN, self_shadow=bad))

    def test_the_driver_checks_the_self_shadow_before_anything_renders(self):
        for want in ("mmd", "soft"):
            for workers in (1, 2):
                driver = self.written(dict(PLAN, self_shadow=want), "%s%d" % (want, workers), workers=workers)
                lines = driver.splitlines()
                verify = [i for i, line in enumerate(lines) if "tools/mme_shadow.py verify" in line]
                self.assertEqual(len(verify), 1, (want, workers))
                self.assertTrue(lines[verify[0]].endswith(
                    "verify 'C:/MMD/MikuMikuDance.exe' 'C:/MMD/UserFile/Model/Rin/White.pmx' %s" % want), lines[verify[0]])
                self.assertIn("exit 1", lines[verify[0] + 1])
                self.assertIn("exit 1", lines[verify[0] + 2])
                # in the driver's own part, before the look is checked and before any chunk is rendered (one worker:
                # the calls of Run-Chunk; --workers: the start of the worker processes, which render)
                look = [i for i, line in enumerate(lines) if line.startswith("$check = ")]
                self.assertTrue(look and verify[0] < look[0], (want, workers))
                if workers == 1:
                    calls = [i for i, line in enumerate(lines) if line.startswith("Run-Chunk ")]
                else:
                    calls = [i for i, line in enumerate(lines) if line.startswith("$self = (Get-Process")]
                self.assertTrue(calls and verify[0] < min(calls), (want, workers))
        self.assertNotIn("mme_shadow", self.written(dict(PLAN), "plain"))
        self.assertNotIn("mme_shadow", self.written(dict(PLAN), "plain2", workers=2))

    def test_with_soft_a_failed_batch_stops_the_mmd_it_left_open(self):
        # MME answers a broken effect with a window of its own, and the batch stops at it with MMD open behind it
        # (softshadow-mme NOTES): the soft driver stops that MMD (DriverTest runs it); the others are as before
        for workers in (1, 2):
            lines = self.written(dict(PLAN, self_shadow="soft"), "stop%d" % workers, workers=workers).splitlines()
            defined = [i for i, line in enumerate(lines) if line == "function Stop-Launched($json) {"]
            run = [i for i, line in enumerate(lines) if line.startswith("function Run-Chunk(")]
            self.assertEqual(len(defined), 1, workers)
            self.assertLess(defined[0], run[0])
            batch = [i for i, line in enumerate(lines) if "-m mmd_cli --out $json batch $batch" in line]
            self.assertEqual(lines[batch[0] + 1], "    if ($LASTEXITCODE -ne 0) { Stop-Launched $json }")
            self.assertIn("STOP: the MMD batch failed", lines[batch[0] + 2])
            self.assertIn("-ieq 'C:/MMD/MikuMikuDance.exe'", "\n".join(lines[defined[0]:run[0]]))
            for plan in (dict(PLAN), dict(PLAN, self_shadow="mmd")):
                self.assertNotIn("Stop-Launched", self.written(plan, "plain%d%s" % (workers, plan.get("self_shadow")),
                                                               workers=workers))

    def test_with_the_night_the_check_takes_the_look(self):
        # light3: "night": true (the look's light.person drawn by the effect beside the model) has the check compare the
        # effect with the plan's look; it needs "soft".  Without it the line is the one of before
        self.assertFalse(mv_chunks.check_plan(dict(PLAN, self_shadow="soft"))["night"])
        for bad in ({"night": True}, {"night": True, "self_shadow": "mmd"}, {"night": 1, "self_shadow": "soft"}):
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(PLAN, **bad))
        for workers in (1, 2):
            lines = self.written(dict(PLAN, self_shadow="soft", night=True), "night%d" % workers, workers=workers).splitlines()
            verify = [line for line in lines if "tools/mme_shadow.py verify" in line]
            self.assertEqual(len(verify), 1)
            self.assertTrue(verify[0].endswith("verify 'C:/MMD/MikuMikuDance.exe' 'C:/MMD/UserFile/Model/Rin/White.pmx' soft "
                                               "--look 'C:/work/song/look.json' --camera 'C:/work/song/camera.vmd'"), verify[0])
            plain = [line for line in self.written(dict(PLAN, self_shadow="soft"), "soft%d" % workers,
                                                   workers=workers).splitlines() if "tools/mme_shadow.py verify" in line]
            self.assertTrue(plain[0].endswith("White.pmx' soft"), plain[0])

    def test_with_the_night_the_check_holds_the_cameras_light_too(self):
        # review light3rev: with "night" the driver's check also gives the plan's camera, whose light must be the night's
        # (tools/mme_shadow.py verify --camera: light-vmd writes it); without "night" the line is the one of before
        for workers in (1, 2):
            lines = self.written(dict(PLAN, self_shadow="soft", night=True), "nightcam%d" % workers, workers=workers).splitlines()
            verify = [line for line in lines if "tools/mme_shadow.py verify" in line]
            self.assertEqual(len(verify), 1)
            self.assertTrue(verify[0].endswith("--look 'C:/work/song/look.json' --camera 'C:/work/song/camera.vmd'"), verify[0])

    def test_soft_watches_mmes_files_beside_mmd(self):
        soft = mv_chunks._inputs(mv_chunks.check_plan(dict(PLAN, self_shadow="soft")))
        for name in ("d3d9.dll", "MMHack.dll", "MMEffect.dll"):
            self.assertIn("C:/MMD/" + name, soft)
        plain = mv_chunks._inputs(mv_chunks.check_plan(dict(PLAN)))
        self.assertEqual(mv_chunks._inputs(mv_chunks.check_plan(dict(PLAN, self_shadow="mmd"))), plain)


class WorkersScriptTest(unittest.TestCase):
    """--workers N (N from 2) writes a driver that renders and folds N chunks at the same time.  The batches and the join list
    are those of one worker; the layers and the text are prepared once and every chunk folds with them (--prepared).
    --workers 1, the default, writes the scripts of before, byte for byte"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, label, plan=PLAN, spans=SPANS, lead=120, fps=240, shutter=0.5, tag="t", **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(plan), mv_chunks.plan_chunks(spans, lead), folder, tag, fps, shutter, **kw)
        return summary, hashes(folder)

    def driver(self, summary):
        with open(summary["driver"], encoding="utf-8-sig") as f:
            return f.read()

    def test_one_worker_writes_the_scripts_of_before_byte_for_byte(self):
        for out_fps, golden in ((30, GOLDEN_30), (60, GOLDEN_60)):
            for label, kw in (("default", {}), ("one", {"workers": 1}), ("x264", {"workers": 1, "encoder": "x264"})):
                self.assertEqual(self.written("%s_%d" % (label, out_fps), out_fps=out_fps, **kw)[1], golden["t"], (label, out_fps))
            b2 = self.written("b2_%d" % out_fps, PLAN_B2, mv_chunks.spans_from_cuts([40, 90], 119), 30, 120, 0.75, "b2",
                              out_fps=out_fps, workers=1)[1]
            self.assertEqual(b2, golden["b2"], out_fps)

    def test_workers_render_the_batches_and_join_the_list_of_one_worker(self):
        one, one_files = self.written("one")
        two, two_files = self.written("two", workers=2)
        self.assertEqual(sorted(one_files), sorted(two_files))
        for name in one_files:
            if name != "render_t.ps1":
                self.assertEqual(two_files[name], one_files[name], name)
        self.assertNotEqual(two_files["render_t.ps1"], one_files["render_t.ps1"])
        self.assertEqual(two["workers"], 2)
        self.assertNotIn("workers", one)
        self.assertEqual({k: v for k, v in two.items() if k not in ("workers", "driver", "batches", "concat")},
                         {k: v for k, v in one.items() if k not in ("driver", "batches", "concat")})

    def test_the_driver_of_workers_prepares_once_and_every_chunk_folds_with_the_prepared_layers(self):
        summary = self.written("two", workers=2)[0]
        driver = self.driver(summary)
        self.assertIn("param([switch]$Resume, [int]$Worker = 0)", driver)
        prepare = [l for l in driver.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertEqual(len(prepare), 1, prepare)
        self.assertTrue(prepare[0].endswith("--size 1280x720 --fps 30 --cues 'C:/work/song/cues.json'"), prepare)
        self.assertNotIn("tools/mv_look.py layers", driver)
        takes = re.findall(r"^ +if \(Take '([^']+)'\) \{ Run-Chunk .*\}$", driver, re.M)
        self.assertEqual(takes, ["t_00", "t_01", "t_02"])
        plan = mv_chunks.check_plan(dict(PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[2]
        fold = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5, prepared=True)
        self.assertEqual(value(fold, "--prepared"), "C:/work/song/out/look_work_t")
        self.assertNotIn("--work", fold)
        one = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5)
        self.assertEqual([a for a in fold if a not in ("--prepared",)], [a for a in one if a not in ("--work",)])
        # what -Resume compares: a chunk folded with prepared layers is not taken for one folded with its own (nor back)
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 240, 0.5, prepared=True), mv_chunks.recipe(plan, "t", chunk, 240, 0.5))

    def test_no_more_workers_start_than_there_are_chunks(self):
        driver = self.driver(self.written("many", workers=8)[0])
        self.assertIn("$count = 3", driver)
        driver = self.driver(self.written("two", workers=2)[0])
        self.assertIn("$count = 2", driver)

    def test_the_number_of_workers_is_a_whole_number_from_1_to_8(self):
        plan = mv_chunks.check_plan(dict(PLAN))
        chunks = mv_chunks.plan_chunks(SPANS, lead=0)
        for workers in (0, -1, 9, "2", 2.0, True, None):
            with self.assertRaises(ValueError, msg=workers) as ctx:
                mv_chunks.write(plan, chunks, os.path.join(self.tmp, "w"), "t", 240, 0.5, workers=workers)
            self.assertIn("--workers", str(ctx.exception))


class EncoderScriptTest(unittest.TestCase):
    """--encoder nvenc folds with h264_nvenc.  Its files carry "_nvenc" after the tag (and after _60fps), so that it removes
    nothing of a run with libx264, the default and the encoder of the video to publish; the look check tries h264_nvenc
    before MMD renders"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, folder, **kw):
        return mv_chunks.write(mv_chunks.check_plan(dict(PLAN)), mv_chunks.plan_chunks(SPANS, 120), os.path.join(self.tmp, folder),
                               "t", 240, 0.5, **kw)

    def test_nvenc_names_its_files_apart_and_leaves_those_of_libx264_alone(self):
        self.written("both")
        summary = self.written("both", encoder="nvenc")
        files = hashes(os.path.join(self.tmp, "both"))
        self.assertEqual({n: files[n] for n in GOLDEN_30["t"]}, GOLDEN_30["t"])
        self.assertEqual(sorted(set(files) - set(GOLDEN_30["t"])), ["chunk_t_nvenc_00.txt", "chunk_t_nvenc_01.txt",
                                                                   "chunk_t_nvenc_02.txt", "concat_t_nvenc.txt", "render_t_nvenc.ps1"])
        self.assertEqual((summary["joined"], summary["encoder"]), ("C:/work/song/out/mv_t_nvenc.mp4", "nvenc"))
        sixty = self.written("sixty", encoder="nvenc", out_fps=60, workers=2)
        self.assertEqual(sixty["joined"], "C:/work/song/out/mv_t_60fps_nvenc.mp4")
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "sixty")))[-1], "render_t_60fps_nvenc.ps1")

    def test_every_fold_and_the_look_check_use_nvenc(self):
        for workers, check in ((1, "layers"), (2, "prepare")):
            summary = self.written("w%d" % workers, encoder="nvenc", workers=workers)
            with open(summary["driver"], encoding="utf-8-sig") as f:
                driver = f.read()
            folds = re.findall(r"Run-Chunk .* @\((.*)\)", driver)
            self.assertEqual(len(folds), 3, driver)
            self.assertTrue(all(f.endswith("'--encoder', 'nvenc'") for f in folds), folds)
            checks = [l for l in driver.splitlines() if "tools/mv_look.py %s" % check in l]
            self.assertEqual(len(checks), 1)
            self.assertIn(" --encoder nvenc", checks[0])
        plan = mv_chunks.check_plan(dict(PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[1]
        self.assertNotEqual(mv_chunks.recipe(plan, "t_nvenc", chunk, 240, 0.5, encoder="nvenc"),
                            mv_chunks.recipe(plan, "t_nvenc", chunk, 240, 0.5))

    def test_an_encoder_it_does_not_know_is_refused(self):
        for encoder in ("h264", "NVENC", "", None):
            with self.assertRaises(ValueError, msg=encoder) as ctx:
                self.written("x", encoder=encoder)
            self.assertIn("--encoder", str(ctx.exception))


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


class FastSpansTest(unittest.TestCase):
    """--fast-spans / --fast-fps: the chunks that hold a fast stretch of the song are rendered at a higher rate (960: the
    copies of a fast hand half as far apart as at 480), the others at --fps.  A whole chunk changes its rate, so the rate
    changes only where a chunk ends (a cut of the camera, where every chunk starts its own MMD and its own physics anyway)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, label, fast, fps=480, plan=PLAN, **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(dict(plan)), mv_chunks.plan_chunks(SPANS, 120), folder, "t", fps, 0.5,
                                  fast=fast, **kw)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            return summary, f.read()

    def render_fps(self, summary):
        rates = []
        for path in summary["batches"]:
            with open(path, encoding="utf-8") as f:
                line = [l for l in f if '"render"' in l][0]
            argv = json.loads(line)
            rates.append(int(argv[argv.index("--fps") + 1]))
        return rates

    def test_the_chunk_of_a_fast_span_renders_and_folds_at_the_fast_rate(self):
        # chunk 1 is frames 100-249 (3.33 to 8.33 s)
        summary, driver = self.written("one", {"spans": [(4.0, 5.0)], "fps": 960})
        self.assertEqual(self.render_fps(summary), [480, 960, 480])
        calls = [l for l in driver.splitlines() if l.startswith("Run-Chunk ")]
        self.assertEqual(len(calls), 3)
        self.assertEqual([value(re.findall(r"'([^']*)'", c), "--subframes") for c in calls], ["16", "32", "16"])
        self.assertEqual(summary["fast"], {"fps": 960, "subframes": 32, "spans": [[4.0, 5.0]], "chunks": [1]})
        self.assertEqual(summary["largest_avi_gb"], round(250 * 32 * 1280 * 720 * 4 / 1e9, 1))     # chunk 1 with its lead (frames 0-249)
        self.assertEqual(summary["frames"], 300)

    def test_a_span_across_a_cut_takes_both_chunks_and_several_spans_add_up(self):
        summary, _ = self.written("two", {"spans": [(3.0, 3.5), (9.0, 9.2)], "fps": 960})
        self.assertEqual(self.render_fps(summary), [960, 960, 960])
        summary, _ = self.written("edge", {"spans": [(3.0, 3.3333)], "fps": 960})      # ends before frame 100 begins
        self.assertEqual(self.render_fps(summary), [960, 480, 480])

    def test_without_fast_spans_the_scripts_are_those_of_before(self):
        a, _ = self.written("none", None)
        folder = os.path.join(self.tmp, "plain")
        mv_chunks.write(mv_chunks.check_plan(dict(PLAN)), mv_chunks.plan_chunks(SPANS, 120), folder, "t", 480, 0.5)
        self.assertEqual(hashes(os.path.join(self.tmp, "none")), hashes(folder))
        self.assertNotIn("fast", a)

    def test_the_recipe_of_a_fast_chunk_differs_so_resume_does_not_keep_the_slow_mp4(self):
        plan = mv_chunks.check_plan(dict(PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, 120)[1]
        fast = dict(chunk, fps=960)
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 480, 0.5), mv_chunks.recipe(plan, "t", fast, 480, 0.5))
        self.assertEqual(mv_chunks.recipe(plan, "t", fast, 480, 0.5), mv_chunks.recipe(plan, "t", fast, 960, 0.5))

    def test_bad_fast_spans_are_refused_before_mmd_renders(self):
        for fast in ({"spans": [(4.0, 5.0)], "fps": 720},          # not a rate MMD renders
                     {"spans": [(4.0, 5.0)], "fps": 480},          # not above --fps
                     {"spans": [(4.0, 5.0)], "fps": 240},
                     {"spans": [(5.0, 4.0)], "fps": 960},          # ends before it starts
                     {"spans": [(20.0, 21.0)], "fps": 960},        # in no chunk: it would silently do nothing
                     {"spans": [], "fps": 960}):
            with self.assertRaises(ValueError, msg=fast):
                self.written("bad", fast)

    def test_aligning_the_physics_at_960(self):
        summary, driver = self.written("align", {"spans": [(4.0, 5.0)], "fps": 960}, align_physics=True)
        self.assertEqual(driver.count("'--physics-align'"), 3)

    def test_the_workers_prepare_the_stage_once_per_rate(self):
        # the prepared stage is drawn with the fold's shutter in subframes (mv_look's prepared key holds them): the fast
        # chunks fold with a stage of their own, prepared with 32 subframes, in a folder of its own
        world = dict(PLAN, world=True, accessories=[])
        summary, driver = self.written("workers", {"spans": [(4.0, 5.0)], "fps": 960}, plan=world, workers=2)
        prepare = [l for l in driver.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertEqual(len(prepare), 2)
        self.assertIn("look_work_t' ", prepare[0])
        self.assertTrue(prepare[0].endswith("--subframes 16 --shutter 0.5 --span 0.000000 3.333333 --span 8.333333 10.000000"),
                        prepare[0])
        self.assertIn("look_work_t_960fps' ", prepare[1])
        self.assertTrue(prepare[1].endswith("--subframes 32 --shutter 0.5 --span 3.333333 8.333333"), prepare[1])
        calls = [l for l in driver.splitlines() if "Run-Chunk " in l]
        self.assertIn("'C:/work/song/out/look_work_t_960fps'", calls[1])
        self.assertIn("'C:/work/song/out/look_work_t'", calls[0])

    def test_workers_with_every_chunk_fast_prepare_once(self):
        world = dict(PLAN, world=True, accessories=[])
        summary, driver = self.written("allfast", {"spans": [(0.0, 10.0)], "fps": 960}, plan=world, workers=2)
        prepare = [l for l in driver.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertEqual(len(prepare), 1)
        self.assertIn("--subframes 32", prepare[0])

    def test_parse_fast_spans(self):
        self.assertEqual(mv_chunks.parse_spans("18.3-20.3,60.2-63.3,127.8-131.9,242.0-243.2"),
                         [(18.3, 20.3), (60.2, 63.3), (127.8, 131.9), (242.0, 243.2)])
        for bad in ("", "18.3", "18.3-", "a-b", "20-18", "1-2,,3-4"):
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.parse_spans(bad)


@unittest.skipUnless(mv_look, "needs numpy and Pillow for tools/mv_look.py")
class ShutterTest(unittest.TestCase):
    def test_the_frame_rates_and_shutters_taken_are_the_ones_mmd_and_mv_look_take(self):
        # review 10: fps 60 with shutter 0.2 passed here, and mv_look refused it after MMD had rendered chunk 0
        chunks = mv_chunks.plan_chunks(SPANS, lead=0)
        plan = mv_chunks.check_plan(dict(PLAN))
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        for out_fps in (30, 60):
            for fps in (30, 60, 90, 120, 240, 480, 960):
                for shutter in (0.01, 0.05, 0.07, 0.1, 0.12, 0.13, 0.2, 0.24, 0.25, 0.3, 0.5, 1.0):
                    try:
                        mv_look.check_shutter(fps // out_fps, shutter)
                        looks_ok = fps in (30, 60, 120, 240, 480, 960)
                    except ValueError:
                        looks_ok = False
                    try:
                        mv_chunks.write(plan, chunks, folder, "t", fps, shutter, out_fps=out_fps)
                        ok = True
                    except ValueError:
                        ok = False
                    self.assertEqual(ok, looks_ok, (out_fps, fps, shutter))


# What the stand-ins of python share (render12): the value after a switch, and the first frame of the song from .. to (seconds)
# whose picture of the stage by MMD is missing from a folder (mv_look needs them all)
STUB_HELPERS = r"""
function Arg-After($list, $key) { $i = [array]::IndexOf($list, $key); if ($i -lt 0) { return $null }; return $list[$i + 1] }
function Missing-Picture($folder, $from, $to) {
    for ($f = [int][math]::Round($from * 30); $f -lt [int][math]::Round($to * 30); $f++) {
        if (-not (Test-Path -LiteralPath (Join-Path $folder ('mmd_{0:D5}.png' -f $f)))) { return $f }
    }
    return $null
}
"""
# tools/stage_layer.py batch and unpack as the stand-ins of python do them (render12): the batch draws the frames --from .. --to of
# the stage at 30 fps (its render line, as the real one writes it); unpack writes a picture for every frame the AVI holds (the
# stand-in of MMD writes the rate and the frames of the song into the AVI) and, with STUB_FREE_DROP, takes that many bytes off
# the free space (somebody else writing while the stage was drawn)
STAGE_STUB = r"""
    if ($args[0] -eq 'tools/stage_layer.py' -and $args[1] -eq 'batch') {
        if (-not (Test-Path -LiteralPath $args[2])) { '{"ok": false, "error": "cannot read the set"}'; $global:LASTEXITCODE = 2; return }
        $line = ConvertTo-Json -Compress -InputObject @('render', 'avi', (Arg-After $args '--avi'), '--from', (Arg-After $args '--from'),
                                                       '--to', (Arg-After $args '--to'), '--fps', '30')
        Set-Content -LiteralPath $args[4] -Encoding UTF8 -Value @('# the stage alone (a stand-in)', $line)
        '{"ok": true}'; $global:LASTEXITCODE = 0; return
    }
    if ($args[0] -eq 'tools/stage_layer.py' -and $args[1] -eq 'unpack') {
        $avi = $args[2]; $dir = $args[3]; $first = [int](Arg-After $args '--first')
        if (-not (Test-Path -LiteralPath $avi)) { '{"ok": false, "error": "no AVI"}'; $global:LASTEXITCODE = 1; return }
        $n = [int]@(Get-Content -LiteralPath $avi)[1]
        if ($env:STUB_UNPACK_SHORT -and ($dir -like ('*' + $env:STUB_UNPACK_SHORT))) { $n = $n - 1 }
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        for ($i = 0; $i -lt $n; $i++) { Set-Content -LiteralPath (Join-Path $dir ('mmd_{0:D5}.png' -f ($first + $i))) -Value 'picture' }
        if ($env:STUB_FREE_FILE -and $env:STUB_FREE_DROP) {
            Set-Content -LiteralPath $env:STUB_FREE_FILE -Value ([decimal](Get-Content -LiteralPath $env:STUB_FREE_FILE) - [decimal]$env:STUB_FREE_DROP)
        }
        '{"ok": true, "pictures": ' + $n + '}'; $global:LASTEXITCODE = 0; return
    }
"""
# the AVI holds its rate, as the header of MMD's AVI does, and the frames of the song it covers (for the stand-in of unpack)
STUB_AVI = ("Set-Content -LiteralPath $r[2] -Value @($r[[array]::IndexOf($r, '--fps') + 1], "
            "([int]$r[[array]::IndexOf($r, '--to') + 1] - [int]$r[[array]::IndexOf($r, '--from') + 1] + 1))")
# mv_look render with a stage of a model: every picture of the stage by MMD of the excerpt must be there (the real one stops
# without one); its stage's frames go to the work folder
STUB_RENDER_STAGE = (
    "    elseif ((Arg-After $args '--stage-pictures') -and ($null -ne (Missing-Picture (Arg-After $args '--stage-pictures') $from $to))) {\n"
    "        $why = 'no picture of the stage by MMD for frame ' + (Missing-Picture (Arg-After $args '--stage-pictures') $from $to)\n"
    "    }\n")
STUB_STAGE_FRAMES = (
    "    if ((Arg-After $args '--stage-pictures') -and (Arg-After $args '--work')) {\n"
    "        New-Item -ItemType Directory -Force -Path ((Arg-After $args '--work') + '/stage') | Out-Null\n"
    "        Set-Content -LiteralPath ((Arg-After $args '--work') + '/stage/stage_00000.png') -Value 'a frame of the stage'\n"
    "    }\n")
# mv_look layers with a stage of a model: the folder of MMD's pictures must be there
STUB_LAYERS_STAGE = (
    "        if ((Arg-After $args '--stage-pictures') -and -not (Test-Path -LiteralPath (Arg-After $args '--stage-pictures') -PathType Container)) {\n"
    "            '{\"ok\": false, \"error\": \"no folder of the pictures of the stage\"}'; $global:LASTEXITCODE = 2; return\n"
    "        }\n")


STUBS = STUB_HELPERS + r"""
$log = $env:STUB_LOG
function python {
    Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ') + ' home=' + $env:MMD_CLI_HOME) -Encoding UTF8
    if ($args[0] -eq 'tools/mme_shadow.py') { '{"ok": true}'; $global:LASTEXITCODE = 0; return }
""" + STAGE_STUB + r"""
    if ($args[0] -eq '-m') {
        if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) {
            # the answer of a batch that stopped at a window: its launch with the process id (STUB_BATCH_PID)
            if ($env:STUB_BATCH_PID) {
                Set-Content -LiteralPath $args[3] -Encoding UTF8 -Value ('{"ok": false, "results": [{"argv": ["launch", "--headless"], ' +
                    '"ok": true, "pid": ' + $env:STUB_BATCH_PID + '}, {"argv": ["model", "load"], "ok": false}]}')
            }
            $global:LASTEXITCODE = 1; return
        }
        $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
        $r = $render | ConvertFrom-Json
""" + "        " + STUB_AVI + r"""
        $global:LASTEXITCODE = 0
        return
    }
    if ($args[1] -eq 'layers') {
        # tools/mv_look.py layers LOOK WORK ...: the look must be JSON
        try { $null = Get-Content -LiteralPath $args[2] -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
        catch { '{"ok": false, "error": "the look is not JSON"}'; $global:LASTEXITCODE = 2; return }
""" + STUB_LAYERS_STAGE + r"""        '{"ok": true}'
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
""" + STUB_RENDER_STAGE + r"""    elseif ($env:STUB_LOOK_FAILS -and ($mp4 -like ('*' + $env:STUB_LOOK_FAILS + '*'))) { $why = 'stub failure' }
    if ($why) { '{"ok": false, "error": "' + $why + '"}'; $global:LASTEXITCODE = 2; return }
    $null = Get-Content -LiteralPath $look -Raw | ConvertFrom-Json
    # the output runs at the rate of the AVI over the subframes (mv_look reads the rate from the AVI)
    $rate = [double](Get-Content -LiteralPath $avi -TotalCount 1)
    $sub = [double]$args[[array]::IndexOf($args, '--subframes') + 1]
    $n = [int][math]::Round(($to - $from) * $rate / $sub)
    if ($env:STUB_SHORT -and ($mp4 -like ('*' + $env:STUB_SHORT + '*'))) { $n = $n - 1 }
    Set-Content -LiteralPath $mp4 -Value $n
""" + STUB_STAGE_FRAMES + r"""    '{"ok": true}'
    $global:LASTEXITCODE = 0
}
function ffprobe { $p = $args[-1]; if (Test-Path -LiteralPath $p) { Get-Content -LiteralPath $p } }
if ($env:STUB_NO_DISK) {
    Add-Type -Namespace MvChunks -Name Disk -MemberDefinition 'public static bool GetDiskFreeSpaceEx(string folder, out ulong available, out ulong total, out ulong free) { available = 0; total = 0; free = 0; return false; }'
}
if ($env:STUB_FREE_FILE) {
    # the free space the test sets (render12): the number in the file, read at every call
    Add-Type -Namespace MvChunks -Name Disk -MemberDefinition 'public static bool GetDiskFreeSpaceEx(string folder, out ulong available, out ulong total, out ulong free) { available = ulong.Parse(System.IO.File.ReadAllText(System.Environment.GetEnvironmentVariable("STUB_FREE_FILE")).Trim()); total = available; free = available; return true; }'
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
    would: the batch writes its AVI (which holds its rate), the fold refuses a missing AVI or look and writes an mp4 of
    (to - from) * rate / subframes frames, the join adds the frames of the listed mp4s up"""

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

    def write(self, shutter=0.5, out_fps=30, **plan):
        b = self.base
        full = {"mmd": b + "/MMD/MikuMikuDance.exe", "model": b + "/model/White.pmx", "motions": [b + "/dance.vmd", b + "/lips.vmd"],
                "camera": b + "/camera.vmd", "accessories": [b + "/stage/floor.x", b + "/stage2/prop.x"], "look": self.look, "cues": self.cues,
                "out": self.out, "scripts": self.scripts, "mmd_cli": b}
        full.update(plan)
        self.plan = mv_chunks.check_plan(full)
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240,
                                       shutter=shutter, out_fps=out_fps)
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

    def test_a_fast_chunk_renders_at_its_rate_and_joins_with_the_others(self):
        self.write()
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240,
                                       shutter=0.5, fast={"spans": [(4.0, 5.0)], "fps": 960})
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3)
        folds = [c for c in calls if " render " in c and "mv_look" in c]
        self.assertEqual([("--subframes 32" in c, "--subframes 8" in c) for c in folds], [(False, True), (True, False), (False, True)])
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        self.assertEqual(self.frames("t_01.mp4"), 150)

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

    def test_at_60_fps_every_chunk_and_the_joined_video_have_twice_the_frames(self):
        self.write(out_fps=60)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual([self.frames("t_60fps_%02d.mp4" % i) for i in range(3)], [200, 300, 100])
        self.assertEqual(self.frames("mv_t_60fps.mp4"), 600)
        self.assertIn("joined 600 frames (want 600)", text)
        folds = [c for c in calls if "mv_look.py render" in c]
        self.assertEqual(len(folds), 3)
        self.assertTrue(all(" --subframes 4 --shutter 0.5 " in c for c in folds), folds)
        layers = [c for c in calls if "mv_look.py layers" in c]
        self.assertEqual(len(layers), 1, calls)
        self.assertIn(" --size 1280x720 --fps 60 home=", layers[0])                  # the look checked at the rate it is used

    def test_a_60_fps_run_leaves_the_30_fps_run_of_the_same_tag_alone(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        thirty = {name: self.frames(name) for name in ("t_00.mp4", "t_01.mp4", "t_02.mp4", "mv_t.mp4")}
        self.assertEqual(thirty, {"t_00.mp4": 100, "t_01.mp4": 150, "t_02.mp4": 50, "mv_t.mp4": 300})
        driver = self.summary["driver"]
        self.write(out_fps=60)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual({name: self.frames(name) for name in thirty}, thirty)
        self.assertEqual(self.frames("mv_t_60fps.mp4"), 600)
        self.assertTrue(os.path.exists(driver))

    def test_resume_at_60_fps_skips_only_the_chunks_that_are_already_complete(self):
        self.write(out_fps=60)
        self.assertEqual(self.run_driver(STUB_SHORT="t_60fps_01")[0], 1)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        batches = self.batches(calls)
        self.assertEqual(len(batches), 2, calls)
        self.assertFalse(any("chunk_t_60fps_00" in c for c in batches))
        self.assertEqual(self.frames("mv_t_60fps.mp4"), 600)

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

    def test_with_the_soft_self_shadow_a_failed_batch_stops_the_mmd_it_left_open_and_nothing_else(self):
        # MME answers a broken effect with a window of its own and the batch stops at it, MMD left open behind it
        # (softshadow-mme NOTES): the driver stops that MMD by the process id of the batch's launch, when it is the
        # plan's MMD.  A program that is not stands for MMD here (ping, copied to the plan's MikuMikuDance.exe)
        ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
        if not os.path.isfile(ping):
            self.skipTest("needs PING.EXE")
        exe = os.path.join(self.tmp, "MMD", "MikuMikuDance.exe")
        shutil.copy2(ping, exe)
        for name in ("d3d9.dll", "MMHack.dll", "MMEffect.dll"):
            self.put("MMD/" + name, name)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
        mmd = subprocess.Popen([exe, "-n", "120", "127.0.0.1"], **quiet)
        other = subprocess.Popen([ping, "-n", "120", "127.0.0.1"], **quiet)
        for proc in (mmd, other):
            self.addCleanup(proc.wait, 10)
            self.addCleanup(proc.kill)
        self.write(self_shadow="soft")
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01.json", STUB_BATCH_PID=str(other.pid))
        self.assertEqual(code, 1, text)
        self.assertIsNone(other.poll())                               # not the plan's MMD: left alone
        self.assertNotIn("stopped MMD", text)
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01.json", STUB_BATCH_PID=str(mmd.pid))
        self.assertEqual(code, 1, text)
        self.assertIn("stopped MMD %d" % mmd.pid, text)
        self.assertIn("STOP: the MMD batch failed (exit 1)", text)    # the batch's own code, after the stop
        self.assertIsNotNone(mmd.wait(10))
        self.assertTrue(any("tools/mme_shadow.py verify" in c for c in calls), calls)

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


# The stand-ins of DriverTest as scripts on the PATH, for the drivers of --workers: the workers are processes of their own,
# where the functions of a wrapper do not reach.  Every process logs to a file of its own (STUB_LOG.<pid>).  STUB_SLOW makes a
# batch take 3 seconds, so that a test knows which chunk is still under way when another one fails
PATH_STUBS = {
    "python.ps1": STUB_HELPERS + r"""
$log = $env:STUB_LOG + '.' + $PID
Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ') + ' home=' + $env:MMD_CLI_HOME) -Encoding UTF8
""" + STAGE_STUB + r"""
if ($args[0] -eq '-m') {
    if ($env:STUB_MMD_OVERLAP) {
        # (render12) the MMD batches of the run under way at once: a mark in the folder while this one runs; the marks are
        # counted when it starts and when it ends (two that overlap: one of them starts while the other's mark is there)
        $mark = Join-Path $env:STUB_MMD_OVERLAP ('run_' + $PID)
        Set-Content -LiteralPath $mark -Value 'running'
        Add-Content -LiteralPath (Join-Path $env:STUB_MMD_OVERLAP ('seen_' + $PID)) -Value @(Get-ChildItem -LiteralPath $env:STUB_MMD_OVERLAP -Filter 'run_*').Count
        Start-Sleep -Milliseconds 2000
        Add-Content -LiteralPath (Join-Path $env:STUB_MMD_OVERLAP ('seen_' + $PID)) -Value @(Get-ChildItem -LiteralPath $env:STUB_MMD_OVERLAP -Filter 'run_*').Count
        Remove-Item -LiteralPath $mark
    }
    if ($env:STUB_SLOW -and (($args -join ' ') -like ('*' + $env:STUB_SLOW + '*'))) { Start-Sleep -Seconds 3 }
    if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) { $global:LASTEXITCODE = 1; return }
    $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
    $r = $render | ConvertFrom-Json
""" + STUB_AVI + r"""
    $global:LASTEXITCODE = 0
    return
}
if ($args[1] -eq 'layers' -or $args[1] -eq 'prepare') {
    try { $null = Get-Content -LiteralPath $args[2] -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
    catch { '{"ok": false, "error": "the look is not JSON"}'; $global:LASTEXITCODE = 2; return }
""" + STUB_LAYERS_STAGE + r"""    '{"ok": true}'
    $global:LASTEXITCODE = 0
    return
}
$avi = $args[2]; $look = $args[3]; $mp4 = $args[4]
$from = [double]$args[[array]::IndexOf($args, '--from') + 1]
$to = [double]$args[[array]::IndexOf($args, '--to') + 1]
$offset = [double]$args[[array]::IndexOf($args, '--offset') + 1]
$why = $null
if (-not (Test-Path -LiteralPath $avi)) { $why = 'no such file: ' + $avi }
elseif (-not (Test-Path -LiteralPath $look)) { $why = 'no look: ' + $look }
elseif ($offset -gt $from) { $why = '--from is before the dancer' }
""" + STUB_RENDER_STAGE + r"""elseif ($env:STUB_LOOK_FAILS -and ($mp4 -like ('*' + $env:STUB_LOOK_FAILS + '*'))) { $why = 'stub failure' }
if ($why) { '{"ok": false, "error": "' + $why + '"}'; $global:LASTEXITCODE = 2; return }
$rate = [double](Get-Content -LiteralPath $avi -TotalCount 1)
$sub = [double]$args[[array]::IndexOf($args, '--subframes') + 1]
$n = [int][math]::Round(($to - $from) * $rate / $sub)
if ($env:STUB_SHORT -and ($mp4 -like ('*' + $env:STUB_SHORT + '*'))) { $n = $n - 1 }
Set-Content -LiteralPath $mp4 -Value $n
""" + STUB_STAGE_FRAMES + r"""'{"ok": true}'
$global:LASTEXITCODE = 0
""",
    "ffprobe.ps1": r"""
$p = $args[-1]
if (Test-Path -LiteralPath $p) { Get-Content -LiteralPath $p }
""",
    "ffmpeg.ps1": r"""
Add-Content -LiteralPath ($env:STUB_LOG + '.' + $PID) -Value ('ffmpeg ' + ($args -join ' ')) -Encoding UTF8
if ($env:STUB_JOIN_FAILS) { $global:LASTEXITCODE = 1; return }
$sum = 0
foreach ($line in Get-Content -LiteralPath $args[[array]::IndexOf($args, '-i') + 1] -Encoding UTF8) {
    if ($line -match "^file '(.*)'$") { $sum += [int](Get-Content -LiteralPath $Matches[1]) }
}
Set-Content -LiteralPath $args[-1] -Value $sum
$global:LASTEXITCODE = 0
""",
}


class MmdOverlap(object):
    """what the stand-in batches of STUB_MMD_OVERLAP counted (render12)"""

    @staticmethod
    def seen(folder):
        out = []
        for name in sorted(os.listdir(folder)):
            if name.startswith("seen_"):
                with open(os.path.join(folder, name), encoding="utf-8-sig") as f:
                    out += [int(l) for l in f if l.strip()]
        return out


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class WorkersDriverTest(unittest.TestCase):
    """The driver of --workers run for real, with python / ffprobe / ffmpeg replaced by the scripts of PATH_STUBS: the workers
    are PowerShell processes of their own that take the chunks no one has taken, a failure stops the others from taking more,
    and the driver joins what they made"""

    FILES = DriverTest.FILES
    setUp = DriverTest.setUp
    put = DriverTest.put
    frames = DriverTest.frames
    batches = DriverTest.batches

    def write(self, workers=2, shutter=0.5, out_fps=30, **plan):
        b = self.base
        full = {"mmd": b + "/MMD/MikuMikuDance.exe", "model": b + "/model/White.pmx", "motions": [b + "/dance.vmd", b + "/lips.vmd"],
                "camera": b + "/camera.vmd", "accessories": [b + "/stage/floor.x", b + "/stage2/prop.x"], "look": self.look, "cues": self.cues,
                "out": self.out, "scripts": self.scripts, "mmd_cli": b}
        full.update(plan)
        self.plan = mv_chunks.check_plan(full)
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240,
                                       shutter=shutter, out_fps=out_fps, workers=workers)
        return self.summary

    def run_driver(self, switches="", **env):
        """(exit code, what the driver and its workers printed, {pid: the calls that process made})"""
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs, exist_ok=True)
        for name, text in PATH_STUBS.items():
            with open(os.path.join(stubs, name), "w", encoding="utf-8-sig", newline="\r\n") as f:
                f.write(text)
        for name in os.listdir(self.tmp):
            if name.startswith("calls.log."):
                os.remove(os.path.join(self.tmp, name))
        wrapper = os.path.join(self.tmp, "wrapper.ps1")
        with open(wrapper, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("%s\n& %s %s\nexit $LASTEXITCODE\n" % (PARSE_FIRST % mv_chunks._ps(self.summary["driver"]),
                                                           mv_chunks._ps(self.summary["driver"]), switches))
        env = dict(env, STUB_LOG=os.path.join(self.tmp, "calls.log"), PATH=stubs + os.pathsep + os.environ["PATH"])
        code, text = run_powershell(wrapper, env, timeout=300)
        calls = {}
        for name in os.listdir(self.tmp):
            if name.startswith("calls.log."):
                with open(os.path.join(self.tmp, name), encoding="utf-8-sig") as f:
                    calls[name.split(".")[-1]] = [l.strip() for l in f if l.strip()]
        return code, text, calls

    @staticmethod
    def every(calls):
        return [c for pid in sorted(calls) for c in calls[pid]]

    def rendered(self, calls):
        """the chunks whose batch ran, in no order"""
        return sorted(re.search(r"chunk_(t_\d\d)\.txt", c).group(1) for c in self.batches(self.every(calls)))

    def test_every_chunk_is_rendered_once_by_the_workers_and_joined(self):
        for workers in (2, 3):
            with self.subTest(workers=workers):
                self.write(workers=workers)
                code, text, calls = self.run_driver(STUB_SLOW="chunk_t_00")
                self.assertEqual(code, 0, text)
                self.assertEqual(self.rendered(calls), ["t_00", "t_01", "t_02"])
                self.assertEqual(self.frames("mv_t.mp4"), 300)
                self.assertIn("joined 300 frames (want 300)", text)
                self.assertEqual([n for n in os.listdir(self.out) if n.endswith(".avi")], [])
                # chunk 00 takes 3 s: the others are rendered meanwhile by another process
                busy = [pid for pid, made in calls.items() if self.batches(made)]
                self.assertGreaterEqual(len(busy), 2, calls)

    def test_with_mmd_limit_the_workers_never_run_two_mmd_at_once(self):
        # (mmd_limit, render12) two workers would count the same MikuMikuDance and start two: their batches go one at a time
        self.write(mmd_limit=99)
        marks = os.path.join(self.tmp, "marks")
        os.makedirs(marks)
        code, text, calls = self.run_driver(STUB_MMD_OVERLAP=marks)
        self.assertEqual(code, 0, text)
        seen = MmdOverlap.seen(marks)
        self.assertEqual(len(seen), 3 * 2, seen)                       # 3 chunks, 2 counts each
        self.assertEqual(max(seen), 1, (seen, text))
        self.assertEqual(self.rendered(calls), ["t_00", "t_01", "t_02"])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_the_layers_are_prepared_once_and_every_chunk_folds_with_them(self):
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        every = self.every(calls)
        prepares = [c for c in every if "mv_look.py prepare" in c]
        self.assertEqual(len(prepares), 1, every)
        self.assertIn(" --size 1280x720 --fps 30 --cues %s home=" % self.cues, prepares[0])
        self.assertFalse(any("mv_look.py layers" in c for c in every), every)
        folds = [c for c in every if "mv_look.py render" in c]
        self.assertEqual(len(folds), 3)
        self.assertTrue(all(" --prepared %s/look_work_t " % self.out in c for c in folds), folds)
        self.assertFalse(any(" --work " in c for c in folds), folds)

    def test_a_failed_chunk_stops_the_run_and_no_worker_takes_another_chunk(self):
        # the batch of chunk 00 fails at once while chunk 01 takes 3 s: its worker finishes it and takes no more
        self.write()
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_00.json", STUB_SLOW="chunk_t_01")
        self.assertEqual(code, 1, text)
        self.assertNotIn("t_02", self.rendered(calls))
        self.assertFalse(any(c.startswith("ffmpeg") for c in self.every(calls)), calls)
        self.assertIn("STOP", text)
        self.assertFalse(os.path.exists(os.path.join(self.out, "mv_t.mp4")))

    def test_a_short_chunk_fails_the_run_and_keeps_its_avi(self):
        self.write()
        code, text, calls = self.run_driver(STUB_SHORT="t_01")
        self.assertEqual(code, 1, text)
        self.assertTrue(os.path.exists(os.path.join(self.out, "t_01.avi")))
        self.assertIn("149 frames, want 150", text)
        self.assertFalse(any(c.startswith("ffmpeg") for c in self.every(calls)), calls)

    def test_resume_after_a_failure_renders_only_the_chunks_that_are_not_complete(self):
        self.write()
        self.assertEqual(self.run_driver(STUB_SHORT="t_01")[0], 1)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        rendered = self.rendered(calls)
        self.assertIn("t_01", rendered)
        self.assertNotIn("t_00", rendered)                           # finished before the failure stopped the run
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_resume_reaches_every_worker(self):
        self.write(workers=3)
        self.assertEqual(self.run_driver()[0], 0)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.rendered(calls), [])                   # every worker skipped what was complete
        for name in ("t_00", "t_01", "t_02"):
            self.assertIn("%s skipped: " % name, text)
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_a_look_that_does_not_work_stops_the_run_before_a_worker_starts(self):
        self.put("look.json", "{not json")
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("the look is not JSON", text)
        self.assertEqual(self.rendered(calls), [])
        self.assertEqual(len(calls), 1, calls)                       # the driver alone: no worker was started

    def test_a_second_run_of_the_same_driver_is_refused_while_one_runs(self):
        self.write()
        os.makedirs(os.path.join(self.out, "run_t"), exist_ok=True)
        with open(os.path.join(self.out, "run_t", "lock"), "a"):         # held, as a running driver holds it
            code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("another run", text)
        self.assertEqual(self.rendered(calls), [])
        code, text, calls = self.run_driver()                            # and once it is let go, the run goes
        self.assertEqual(code, 0, text)

    def test_a_worker_started_by_hand_finds_no_run_and_renders_nothing(self):
        self.write()
        os.makedirs(os.path.join(self.out, "run_t"), exist_ok=True)
        code, text, calls = self.run_driver("-Worker 1")
        self.assertEqual(code, 1, text)
        self.assertIn("found no run", text)
        self.assertEqual(self.rendered(calls), [])

    def test_what_an_earlier_run_left_in_its_folder_does_not_stop_this_one(self):
        self.write()
        for name in ("claim_t_00", "done_t_01", "stop", "busy_t_02", "stamp.txt"):
            self.put("out/run_t/" + name, "left by an earlier run")
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.rendered(calls), ["t_00", "t_01", "t_02"])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_paths_with_typographic_quotes_run_with_workers(self):
        self.out = self.base + "/Don’t/out ‘x’"
        self.scripts = self.base + "/Don’t/scripts ‚y‛"
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("mv_t.mp4", self.out), 300)

    def test_too_little_disk_for_an_avi_stops_the_run_before_rendering(self):
        self.write(avi_bytes_per_pixel=1e6)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.rendered(calls), [])
        self.assertIn("bytes free, the AVI needs", text)

    def test_at_60_fps_the_workers_make_twice_the_frames(self):
        self.write(out_fps=60, workers=3)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual([self.frames("t_60fps_%02d.mp4" % i) for i in range(3)], [200, 300, 100])
        self.assertEqual(self.frames("mv_t_60fps.mp4"), 600)
        prepares = [c for c in self.every(calls) if "mv_look.py prepare" in c]
        self.assertIn(" --size 1280x720 --fps 60 --cues ", prepares[0])


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class DiskReserveTest(unittest.TestCase):
    """the free space of the workers: an AVI starts when the disk holds it with its margin after what the AVIs under way still
    have to write; it waits while those would leave too little, and stops the run (exit 3) when even alone it does not fit.
    The function of the driver is run by itself, its measure of the disk given"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        base = self.tmp.replace("\\", "/")
        plan = mv_chunks.check_plan(dict(PLAN, out=base + "/out", scripts=base + "/scripts"))
        summary = mv_chunks.write(plan, mv_chunks.plan_chunks(SPANS, lead=120), self.tmp + "/scripts", "t", 240, 0.5, workers=2)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        self.functions = "\n".join(self.function(driver, name) for name in ("Hold", "Lock-Disk", "Reserve"))
        self.run = base + "/out/run_t"
        os.makedirs(self.run)

    @staticmethod
    def function(driver, name):
        start = re.search(r"^function %s[( ]" % re.escape(name), driver, re.M).start()
        return driver[start:driver.index("\n}\n", start) + 3]

    def reserve(self, free, busy=(), gone_after=None, stop_after=None):
        """Reserve 't_02' for an AVI of 1000 bytes (its need, the margin in) with `free` bytes free and the AVIs under way in
        `busy` [(name, need, written)]; `gone_after`: seconds after which those are done; `stop_after`: after which another
        chunk fails"""
        for name, need, written in busy:
            avi = "%s/%s.avi" % (self.run, name)
            with open(avi, "wb") as f:
                f.write(b"\0" * written)
            with open("%s/busy_%s" % (self.run, name), "w", encoding="utf-8") as f:
                f.write("%s|%d" % (avi, need))
        script = os.path.join(self.tmp, "reserve.ps1")
        with open(script, "w", encoding="utf-8-sig", newline="\r\n") as f:
            # when Reserve came back, in the ticks of .NET (100 ns from the year 1), to set against the time of the change
            f.write("$run = %s\n$out = %s\n$diskWait = 0.2\n$sw = [Diagnostics.Stopwatch]::StartNew()\n"
                    "function Get-FreeBytes($folder) { return %d }\n%s\n"
                    "$went = Reserve 't_02' %s 1000\n'went {0} after {1:N1} s at {2}' -f $went, $sw.Elapsed.TotalSeconds, "
                    "[DateTime]::UtcNow.Ticks\nexit 0\n"
                    % (mv_chunks._ps(self.run), mv_chunks._ps(self.tmp), free, self.functions,
                       mv_chunks._ps(self.run + "/t_02.avi")))
        proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.changed_at = None
        for after, change in ((gone_after, self.done), (stop_after, self.failed)):
            if after is not None:
                time.sleep(after)
                self.changed_at = int(time.time() * 1e7) + 621355968000000000      # .NET ticks of the Unix epoch
                change(busy)
        out = proc.communicate(timeout=120)[0]
        return proc.returncode, out.decode("utf-8", "replace"), os.path.exists(self.run + "/busy_t_02")

    def done(self, busy):
        """the AVIs under way are folded and gone, and so are their notes"""
        for name, _, _ in busy:
            os.remove("%s/busy_%s" % (self.run, name))
            os.remove("%s/%s.avi" % (self.run, name))

    def failed(self, busy):
        with open(self.run + "/stop", "w") as f:
            f.write("a chunk failed")

    def test_an_avi_that_fits_starts_and_is_noted_as_under_way(self):
        code, text, noted = self.reserve(free=1000)
        self.assertEqual(code, 0, text)
        self.assertIn("went True", text)
        self.assertTrue(noted)

    def test_it_waits_while_the_avis_under_way_would_leave_too_little(self):
        # 2400 free, but chunk 00 still has 2000 - 500 to write: 1000 do not fit (900 would be left) until it is done
        code, text, noted = self.reserve(free=2400, busy=[("t_00", 2000, 500)], gone_after=2)
        self.assertEqual(code, 0, text)
        went = int(re.search(r"went True after [\d.]+ s at (\d+)", text).group(1))
        self.assertGreaterEqual(went, self.changed_at, text)                   # not before chunk 00 was done
        self.assertTrue(noted)

    def test_what_an_avi_under_way_has_written_is_already_off_the_free_space(self):
        # 1600 free with 1000 of chunk 00 written: it has 1500 - 1000 = 500 to go, and 1600 - 500 holds 1000
        code, text, noted = self.reserve(free=1600, busy=[("t_00", 1500, 1000)])         # nothing changes: it goes at once
        self.assertEqual(code, 0, text)
        self.assertIn("went True", text)
        self.assertTrue(noted)

    def test_too_little_even_alone_stops_the_run_with_exit_3(self):
        code, text, noted = self.reserve(free=999)
        self.assertEqual(code, 3, text)
        self.assertIn("999 bytes free, the AVI needs 1000", text)
        self.assertFalse(noted)

    def test_a_failure_elsewhere_ends_the_wait_without_rendering(self):
        code, text, noted = self.reserve(free=1500, busy=[("t_00", 2000, 0)], stop_after=1)
        self.assertEqual(code, 0, text)
        self.assertIn("went False", text)
        self.assertFalse(noted)


STAGE_FILES = dict(DriverTest.FILES, **{"MMDplain/MikuMikuDance.exe": "plain mmd", "stagemodel/city.pmx": "city",
                                        "stagemodel/tex/sign.png": "sign"})


def needs_of(driver):
    """the bytes every Run-Chunk of a driver needs (the AVI and its margin; with a free space kept, the chunk's peak)"""
    return [int(n) for n in re.findall(r"Run-Chunk (?:'[^']*' ){7}\d+ (\d+) @\(", driver)]


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class StageDriverTest(unittest.TestCase):
    """The stage of a model drawn chunk by chunk ("stage_mmd" in the plan), the driver run for real with the stand-ins: before a
    chunk the driver has the plain MMD draw the stage over the frames the chunk shows (tools/stage_layer.py batch, the batch,
    unpack into the chunk's folder of pictures), folds the chunk with them in a work folder of its own and removes both once its
    mp4 has passed.  Before every MMD it measures the free space (STUB_FREE_FILE sets it here) and starts nothing that would leave
    less than keep_free_gb"""

    FILES = STAGE_FILES
    put = DriverTest.put
    frames = DriverTest.frames
    batches = DriverTest.batches

    def setUp(self):
        DriverTest.setUp(self)
        self.set = self.base + "/sets/city.json"
        self.put("sets/city.json", json.dumps({"model": self.base + "/stagemodel/city.pmx", "offset": [0, 0.111, 0]}))
        self.pictures = self.base + "/pictures"
        self.free = os.path.join(self.tmp, "free.txt")
        self.set_free(10 ** 15)

    def set_free(self, n):
        with open(self.free, "w", encoding="ascii") as f:
            f.write(str(int(n)))

    def write(self, **plan):
        b = self.base
        full = {"mmd": b + "/MMD/MikuMikuDance.exe", "model": b + "/model/White.pmx", "motions": [b + "/dance.vmd", b + "/lips.vmd"],
                "camera": b + "/camera.vmd", "accessories": [], "look": self.look, "cues": self.cues, "out": self.out,
                "scripts": self.scripts, "mmd_cli": b, "world": True, "stage_set": self.set, "stage_pictures": self.pictures,
                "stage_mmd": b + "/MMDplain/MikuMikuDance.exe"}
        full.update(plan)
        self.plan = mv_chunks.check_plan({k: v for k, v in full.items() if v is not None})     # None: not in the plan
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240, shutter=0.5)
        with open(self.summary["driver"], encoding="utf-8-sig") as f:
            self.driver = f.read()
        return self.summary

    def run_driver(self, switches="", **env):
        env.setdefault("STUB_FREE_FILE", self.free)
        return DriverTest.run_driver(self, switches, **env)

    @staticmethod
    def steps(calls):
        """(what, chunk) of the calls that draw: the stage's batch, MMD for the stage, unpack, MMD for her, the fold"""
        out = []
        for c in calls:
            m = re.search(r"(t_\d\d)", c)
            if "tools/stage_layer.py batch" in c:
                out.append(("stage batch", m.group(1)))
            elif c.startswith("python -m mmd_cli") and "_stage.txt" in c:
                out.append(("stage mmd", m.group(1)))
            elif "tools/stage_layer.py unpack" in c:
                out.append(("unpack", m.group(1)))
            elif c.startswith("python -m mmd_cli"):
                out.append(("mmd", m.group(1)))
            elif "tools/mv_look.py render" in c:
                out.append(("fold", m.group(1)))
        return out

    def left(self):
        """what the stage of the chunks left: the stage's AVIs, the folders of pictures, the work folders of the chunks"""
        got = sorted(n for n in os.listdir(self.out) if n.endswith(".avi") or n.startswith("look_work_t_"))
        if os.path.isdir(self.pictures):
            got += sorted("pictures/" + n for n in os.listdir(self.pictures))
        return got

    def test_every_chunk_has_its_stage_drawn_right_before_it_and_removed_after_it(self):
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.steps(calls), [(s, "t_%02d" % i) for i in range(3)
                                             for s in ("stage batch", "stage mmd", "unpack", "mmd", "fold")])
        # the stage over the frames each chunk shows (from its cut, not its lead-in), with the plain MMD, at the plan's size
        stage = [c for c in calls if "tools/stage_layer.py batch" in c]
        self.assertEqual([re.search(r"--from (\d+) --to (\d+)", c).groups() for c in stage], [("0", "99"), ("100", "249"), ("250", "299")])
        self.assertTrue(all(("--mmd %s/MMDplain/MikuMikuDance.exe --size 1280x720" % self.base) in c for c in stage), stage)
        self.assertTrue(all((" %s %s/camera.vmd " % (self.set, self.base)) in c for c in stage), stage)
        unpacks = [c for c in calls if "tools/stage_layer.py unpack" in c]
        self.assertEqual([re.search(r"--first (\d+)", c).group(1) for c in unpacks], ["0", "100", "250"])
        # every fold read the pictures of its own frames (the stand-in refuses a missing one) and drew in its own work folder
        folds = [c for c in calls if "tools/mv_look.py render" in c]
        for i, c in enumerate(folds):
            self.assertIn(" --stage-pictures %s/t_%02d " % (self.pictures, i), c)
            self.assertIn(" --work %s/look_work_t_%02d " % (self.out, i), c)
        # nothing of the stage is left behind, and the video is whole
        self.assertEqual(self.left(), [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)
        self.assertIn("joined 300 frames", text)

    def test_the_look_is_checked_with_the_folder_of_the_pictures_before_any_mmd(self):
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertIn("tools/mv_look.py layers", calls[0])
        self.assertIn(" --stage-pictures %s " % self.pictures, calls[0] + " ")

    def test_resume_after_a_whole_run_draws_nothing_though_the_pictures_came_and_went(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.steps(calls), [])
        for name in ("t_00", "t_01", "t_02"):
            self.assertIn("%s skipped: " % name, text)

    def test_resume_after_a_failed_fold_goes_on_from_that_chunk(self):
        self.write()
        code, text, calls = self.run_driver(STUB_LOOK_FAILS="t_01")
        self.assertEqual(code, 1, text)
        # a failure keeps what the chunk made, to look at: its AVI and its pictures
        self.assertTrue(os.path.exists(os.path.join(self.out, "t_01.avi")))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "pictures", "t_01")))
        self.assertNotIn(("stage batch", "t_02"), self.steps(calls))
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.steps(calls), [(s, "t_%02d" % i) for i in (1, 2)
                                             for s in ("stage batch", "stage mmd", "unpack", "mmd", "fold")])
        self.assertEqual(self.left(), [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_a_chunk_that_would_leave_less_than_the_free_space_kept_is_not_started(self):
        self.write(keep_free_gb=1)
        needs = needs_of(self.driver)
        self.assertEqual(len(needs), 3)
        self.assertTrue(needs[1] > needs[0], needs)
        # too little for chunk 0: nothing is drawn, not even its stage
        self.set_free(needs[0] + GIB - 1)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.steps(calls), [])
        self.assertIn("t_00 STOP: ", text)
        self.assertIn("-Resume", text)
        # enough for chunk 0 and not for chunk 1 (whose lead-in makes it longer): chunk 0 is made, chunk 1 not started
        self.set_free(needs[0] + GIB)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.steps(calls), [(s, "t_00") for s in ("stage batch", "stage mmd", "unpack", "mmd", "fold")])
        self.assertIn("t_01 STOP: ", text)
        self.assertEqual(self.left(), [])                          # it stopped clean
        # and with room again -Resume goes on from chunk 1
        self.set_free(max(needs) + GIB)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual([c for _, c in self.steps(calls)][::5], ["t_01", "t_02"])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_the_free_space_is_measured_again_before_mmd_draws_her(self):
        # enough when the chunk starts, but somebody else writes while its stage is drawn: her MMD does not start, and the chunk's
        # pictures go (the next try draws them again)
        self.write(keep_free_gb=1)
        needs = needs_of(self.driver)
        self.set_free(needs[0] + GIB)
        code, text, calls = self.run_driver(STUB_FREE_DROP=str(10 ** 6))
        self.assertEqual(code, 3, text)
        self.assertEqual(self.steps(calls), [("stage batch", "t_00"), ("stage mmd", "t_00"), ("unpack", "t_00")])
        self.assertIn("t_00 STOP: ", text)
        self.assertEqual(self.left(), [])

    def test_a_stage_mmd_with_mme_beside_it_stops_the_run_before_anything(self):
        # the stage of a model is MMD's own picture of it (tools/stage_layer.py lays the night on it): MME would draw its effects
        self.put("MMDplain/d3d9.dll", "MME")
        self.write()
        code, text, calls = self.run_driver()
        self.assertEqual(code, 1, text)
        self.assertIn("MME", text)
        self.assertEqual(calls, [])

    def test_resume_sees_the_stage_set_and_the_folder_of_its_model(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)

        def drawn(label):
            code, text, calls = self.run_driver("-Resume")
            self.assertEqual(code, 0, (label, text))
            return len([s for s in self.steps(calls) if s[0] == "stage mmd"])
        self.assertEqual(drawn("nothing changed"), 0)
        self.put("stagemodel/tex/sign.png", "another sign")
        self.assertEqual(drawn("a texture of the stage"), 3)
        self.put("sets/city.json", json.dumps({"model": self.base + "/stagemodel/city.pmx", "offset": [0, 0.2, 0]}))
        self.assertEqual(drawn("the set"), 3)
        self.put("MMDplain/MikuMikuDance.exe", "another plain mmd")
        self.assertEqual(drawn("the stage's MMD"), 3)
        # a model named from the set's folder is found there
        self.put("sets/city.json", json.dumps({"model": "../stagemodel/city.pmx"}))
        self.assertEqual(drawn("the set again"), 3)
        self.put("stagemodel/tex/sign.png", "a third sign")
        self.assertEqual(drawn("a texture of a model named from the set's folder"), 3)
        self.assertEqual(drawn("nothing changed again"), 0)

    def test_an_output_or_pictures_folder_inside_the_stage_models_folder_stops_the_run(self):
        # -Resume watches the folder of the stage's model (only the set names it, read on the render machine), named in the set
        # by its full path or from the set's folder
        for model in (self.base + "/stagemodel/city.pmx", "../stagemodel/city.pmx"):
            self.put("sets/city.json", json.dumps({"model": model}))
            for change in ({"out": self.base + "/stagemodel/out"}, {"stage_pictures": self.base + "/stagemodel/pictures"}):
                with self.subTest(model=model, change=change):
                    if "out" in change:
                        self.out = change["out"]
                    self.write(**change)
                    code, text, calls = self.run_driver()
                    self.assertEqual(code, 1, text)
                    self.assertIn("inside", text)
                    self.assertEqual(calls, [])
                    self.out = self.base + "/out"

    def test_a_failed_stage_stops_the_run_before_mmd_draws_her(self):
        self.write()
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01_stage.json")
        self.assertEqual(code, 1, text)
        self.assertEqual(self.steps(calls)[-1], ("stage mmd", "t_01"))
        self.assertIn("t_01 STOP", text)
        self.write()
        code, text, calls = self.run_driver(STUB_UNPACK_SHORT="t_01")
        self.assertEqual(code, 1, text)
        self.assertEqual(self.steps(calls)[-1], ("unpack", "t_01"))
        self.assertIn("149 pictures", text)

    def test_a_failed_stage_batch_stops_the_stage_mmd_it_left_open_and_nothing_else(self):
        # mmd_cli's batch stops at a failure without its quit, and leaves MMD open (on a shared machine it holds memory and counts
        # among the MMDs others wait for): the driver stops the process of the batch's launch when it is the stage's MMD.  A
        # program that is not MMD stands for it here (ping, copied to the plan's plain MikuMikuDance.exe)
        ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
        if not os.path.isfile(ping):
            self.skipTest("needs PING.EXE")
        exe = os.path.join(self.tmp, "MMDplain", "MikuMikuDance.exe")
        shutil.copy2(ping, exe)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
        mmd = subprocess.Popen([exe, "-n", "120", "127.0.0.1"], **quiet)
        other = subprocess.Popen([ping, "-n", "120", "127.0.0.1"], **quiet)
        for proc in (mmd, other):
            self.addCleanup(proc.wait, 10)
            self.addCleanup(proc.kill)
        self.write()
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01_stage.json", STUB_BATCH_PID=str(other.pid))
        self.assertEqual(code, 1, text)
        self.assertIsNone(other.poll())                               # not the stage's MMD: left alone
        self.assertNotIn("stopped MMD", text)
        code, text, calls = self.run_driver(STUB_BATCH_FAILS="t_01_stage.json", STUB_BATCH_PID=str(mmd.pid))
        self.assertEqual(code, 1, text)
        self.assertIn("stopped MMD %d" % mmd.pid, text)
        self.assertIn("t_01 STOP: MMD could not draw the stage (exit 1)", text)
        self.assertIsNotNone(mmd.wait(10))

    def test_what_a_cut_short_run_left_of_a_chunk_goes_before_the_chunk_or_when_it_is_skipped(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        for rel in ("pictures/t_01/mmd_00100.png", "out/look_work_t_01/stage/stage_00100.png", "out/t_01_stage.avi",
                    "out/t_02_stage.avi.mmdcli-failed", "pictures/t_02/mmd_00250.png"):
            self.put(rel, "left over")
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.steps(calls), [])
        self.assertEqual(self.left(), [])
        self.assertFalse(os.path.exists(os.path.join(self.out, "t_02_stage.avi.mmdcli-failed")))

    def test_pictures_drawn_before_are_read_as_they_are_and_watched(self):
        # without stage_mmd: the folder of the plan holds MMD's pictures of every frame the chunks show, drawn before (as now)
        for f in range(300):
            self.put("pictures/mmd_%05d.png" % f, "picture")
        self.write(stage_mmd=None)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 0, text)
        self.assertEqual([s for s, _ in self.steps(calls)], ["mmd", "fold"] * 3)
        self.assertTrue(all(" --stage-pictures %s " % self.pictures in c for c in calls if "mv_look.py render" in c))
        self.assertEqual(len(os.listdir(self.pictures)), 300)               # left as they were
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual((code, self.steps(calls)), (0, []), text)
        self.put("pictures/mmd_00120.png", "another picture")
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.batches(calls)), 3)

    def test_the_free_space_is_kept_with_pictures_drawn_before_too(self):
        for f in range(300):
            self.put("pictures/mmd_%05d.png" % f, "picture")
        self.write(stage_mmd=None, keep_free_gb=1)
        needs = needs_of(self.driver)
        self.set_free(needs[0] + GIB - 1)
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.batches(calls), [])
        self.set_free(max(needs) + GIB)
        self.assertEqual(self.run_driver()[0], 0)


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class StageWorkersDriverTest(unittest.TestCase):
    """The stage of a model drawn chunk by chunk with --workers: every worker draws the stage of the chunk it takes right before
    it, folds it in the chunk's own work folder and removes both; the look is checked once before the workers start.  The free
    space is the real one here (the workers are processes of their own): the size is small and keep_free_gb 0, or far beyond
    the disk"""

    FILES = STAGE_FILES
    setUp = StageDriverTest.setUp
    set_free = StageDriverTest.set_free
    put = DriverTest.put
    frames = DriverTest.frames
    batches = DriverTest.batches
    steps = staticmethod(StageDriverTest.steps)
    left = StageDriverTest.left
    every = staticmethod(WorkersDriverTest.every)
    run_driver = WorkersDriverTest.run_driver

    def write(self, workers=2, **plan):
        b = self.base
        full = {"mmd": b + "/MMD/MikuMikuDance.exe", "model": b + "/model/White.pmx", "motions": [b + "/dance.vmd", b + "/lips.vmd"],
                "camera": b + "/camera.vmd", "accessories": [], "look": self.look, "cues": self.cues, "out": self.out,
                "scripts": self.scripts, "mmd_cli": b, "world": True, "stage_set": self.set, "stage_pictures": self.pictures,
                "stage_mmd": b + "/MMDplain/MikuMikuDance.exe", "size": [64, 36], "keep_free_gb": 0}
        full.update(plan)
        self.plan = mv_chunks.check_plan({k: v for k, v in full.items() if v is not None})
        self.summary = mv_chunks.write(self.plan, mv_chunks.plan_chunks(SPANS, lead=120), self.scripts, tag="t", fps=240, shutter=0.5,
                                       workers=workers)
        return self.summary

    def test_every_worker_draws_the_stage_of_its_chunk_before_it_and_removes_it_after(self):
        self.write()
        code, text, calls = self.run_driver(STUB_SLOW="chunk_t_00")
        self.assertEqual(code, 0, text)
        every = self.every(calls)
        self.assertFalse(any("mv_look.py prepare" in c for c in every), every)
        self.assertEqual(len([c for c in every if "mv_look.py layers" in c]), 1)
        for pid, made in calls.items():
            # in every worker the stage of a chunk comes right before her, and its fold after them
            steps = self.steps(made)
            for i in range(0, len(steps), 5):
                self.assertEqual([s for s, _ in steps[i:i + 5]], ["stage batch", "stage mmd", "unpack", "mmd", "fold"], steps)
                self.assertEqual(len({c for _, c in steps[i:i + 5]}), 1, steps)
        self.assertEqual(sorted(c for s, c in self.steps(every) if s == "fold"), ["t_00", "t_01", "t_02"])
        self.assertGreaterEqual(len([pid for pid, made in calls.items() if self.batches(made)]), 2)
        folds = [c for c in every if "mv_look.py render" in c]
        self.assertTrue(all(re.search(r" --work \S+/look_work_(t_\d\d) .* --stage-pictures \S+/pictures/\1( |$)", c) for c in folds), folds)
        self.assertEqual(self.left(), [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_resume_after_a_whole_run_draws_nothing(self):
        self.write()
        self.assertEqual(self.run_driver()[0], 0)
        code, text, calls = self.run_driver("-Resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.steps(self.every(calls)), [])

    def test_with_mmd_limit_the_workers_never_run_two_mmd_at_once(self):
        # (mmd_limit) the batches of the stage and of her, in both workers, one at a time: each stand-in batch marks itself
        # for 2 s and counts the marks when it starts and ends (the limit is far above the MikuMikuDance of this machine)
        self.write(mmd_limit=99)
        marks = os.path.join(self.tmp, "marks")
        os.makedirs(marks)
        code, text, calls = self.run_driver(STUB_MMD_OVERLAP=marks)
        self.assertEqual(code, 0, text)
        seen = MmdOverlap.seen(marks)
        self.assertEqual(len(seen), 3 * 2 * 2, seen)                   # 3 chunks, 2 batches each, 2 counts each
        self.assertEqual(max(seen), 1, (seen, text))
        self.assertGreaterEqual(len([pid for pid, made in calls.items() if self.batches(made)]), 2)
        self.assertIn("waiting for the MMD of another worker of this run", text)
        self.assertEqual(self.left(), [])
        self.assertEqual(self.frames("mv_t.mp4"), 300)

    def test_a_free_space_beyond_the_disk_stops_the_run_before_any_mmd(self):
        self.write(keep_free_gb=10 ** 9)                      # an exabyte
        code, text, calls = self.run_driver()
        self.assertEqual(code, 3, text)
        self.assertEqual(self.steps(self.every(calls)), [])
        self.assertIn("STOP", text)


class MmdLimitPlanTest(unittest.TestCase):
    """"mmd_limit" (render12): before every MMD the driver waits while that many MikuMikuDance (anyone's) run on the machine
    (the rule of the shared render machine: 3).  Without it the scripts are those of before"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def driver(self, plan, workers=1):
        summary = mv_chunks.write(mv_chunks.check_plan(dict(plan)), mv_chunks.plan_chunks(SPANS, 120),
                                  os.path.join(self.tmp, "s%d" % len(os.listdir(self.tmp))), "t", 240, 0.5, workers=workers)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            return f.read()

    def test_mmd_limit_is_a_whole_number_from_1_or_left_out(self):
        self.assertIsNone(mv_chunks.check_plan(dict(PLAN))["mmd_limit"])
        self.assertEqual(mv_chunks.check_plan(dict(PLAN, mmd_limit=3))["mmd_limit"], 3)
        for bad in (0, -1, 2.5, "3", True):
            with self.assertRaises(ValueError, msg=bad) as ctx:
                mv_chunks.check_plan(dict(PLAN, mmd_limit=bad))
            self.assertIn("mmd_limit", str(ctx.exception))

    def test_every_mmd_waits_for_its_turn_first(self):
        # in every Run-Chunk, a wait before each MMD batch: her batch, and with stage_mmd the stage's batch too
        for plan, workers, batches in ((dict(PLAN, mmd_limit=3), 1, 1), (dict(PLAN, mmd_limit=3), 2, 1),
                                       (dict(CITY_PLAN, mmd_limit=3), 1, 2), (dict(CITY_PLAN, mmd_limit=3), 2, 2)):
            text = self.driver(plan, workers)
            body = text[text.index("function Run-Chunk("):]
            body = body[:body.index("\n}\n")]
            lines = [l.strip() for l in body.splitlines()]
            runs = [i for i, l in enumerate(lines) if " -m mmd_cli --out " in l]
            self.assertEqual(len(runs), batches, (plan.get("stage_mmd"), workers))
            for i in runs:
                # one worker waits (Wait-Mmd); a worker of --workers takes the run's lock and waits in it (Lock-Mmd)
                waits = [j for j, l in enumerate(lines[:i]) if l.startswith("Wait-Mmd " if workers == 1 else "Lock-Mmd ")]
                self.assertTrue(waits, lines[i])
                # the wait comes after the MMD before it (each MMD waits for its own turn)
                self.assertTrue(all(j > k for k in runs if k < i for j in waits[-1:]), (lines[i], waits, runs))
            self.assertIn("$mmdLimit = 3", text)
        self.assertNotIn("Wait-Mmd", self.driver(dict(PLAN)))

    def test_the_workers_hold_one_lock_from_the_count_until_their_mmd_quits(self):
        # two workers that count the MikuMikuDance at once see the same number and would both start one (render12 saw 2 run,
        # then 4: the two workers of r12g woke from their wait together).  A worker takes the run's lock (mmd.lock) before it
        # counts and keeps it until its MMD has quit; it never waits for the disk while it holds it (Reserve waits for the
        # chunks under way, whose MMD may wait for the lock)
        for plan, batches in ((dict(PLAN, mmd_limit=3), 1), (dict(CITY_PLAN, mmd_limit=3), 2)):
            with self.subTest(stage=bool(plan.get("stage_mmd"))):
                text = self.driver(plan, 2)
                self.assertIn("function Lock-Mmd(", text)
                self.assertIn("function Unlock-Mmd", text)
                self.assertIn("'mmd.lock'", text)
                body = text[text.index("function Run-Chunk("):]
                body = body[:body.index("\n}\n")]
                lines = [l.strip() for l in body.splitlines()]
                runs = [i for i, l in enumerate(lines) if " -m mmd_cli --out " in l]
                self.assertEqual(len(runs), batches)
                for i in runs:
                    j = [n for n, l in enumerate(lines[:i]) if l.startswith("Lock-Mmd ")][-1]
                    held = lines[j:i]
                    self.assertFalse([l for l in held if "Reserve " in l or l.startswith("Unlock-Mmd")], held)
                    after = lines[i + 1:]
                    k = [n for n, l in enumerate(after) if l.startswith("Unlock-Mmd")][0]
                    # the lock goes once the batch is over (a failed batch's MMD stopped first), before the run can stop
                    self.assertFalse([l for l in after[:k] if "STOP" in l or "exit " in l or "Lock-Mmd " in l], after[:k + 1])
        # one worker, or no limit: no lock (the scripts of before)
        for plan, workers in ((dict(PLAN, mmd_limit=3), 1), (dict(CITY_PLAN, mmd_limit=3), 1), (dict(CITY_PLAN), 2), (dict(PLAN), 2)):
            self.assertNotIn("Lock-Mmd", self.driver(plan, workers))


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class WaitMmdTest(unittest.TestCase):
    """Wait-Mmd of the driver run by itself: it returns at once while fewer than the limit run; with as many running it waits,
    goes on once one ends, and after the wait it is given stops the run (exit 3).  Stand-ins of MikuMikuDance: ping copied to
    a MikuMikuDance.exe"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
        if not os.path.isfile(ping):
            self.skipTest("needs PING.EXE")
        self.exe = os.path.join(self.tmp, "MikuMikuDance.exe")
        shutil.copy2(ping, self.exe)
        summary = mv_chunks.write(mv_chunks.check_plan(dict(PLAN, mmd_limit=3)), mv_chunks.plan_chunks(SPANS, 120),
                                  os.path.join(self.tmp, "s"), "t", 240, 0.5)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            self.function = DiskReserveTest.function(f.read(), "Wait-Mmd")

    def running(self):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MikuMikuDance.exe", "/FO", "CSV", "/NH"], capture_output=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.decode("mbcs", "replace")
        return sum(1 for line in out.splitlines() if line.startswith('"MikuMikuDance.exe"'))

    def fake_mmd(self, seconds):
        proc = subprocess.Popen([self.exe, "-n", str(seconds), "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.kill)
        return proc

    def wait(self, limit, minutes, end_after=None, proc=None, clear=None):
        script = os.path.join(self.tmp, "wait.ps1")
        with open(script, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("$mmdLimit = %d\n$mmdWait = %s\n$mmdPoll = 0.2\n%s\n$t = [Diagnostics.Stopwatch]::StartNew()\n"
                    "Wait-Mmd 't_01' @(%s)\n'went after {0:N1} s' -f $t.Elapsed.TotalSeconds\nexit 0\n"
                    % (limit, minutes, self.function, mv_chunks._ps(clear) if clear else ""))
        p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if end_after is not None:
            time.sleep(end_after)
            proc.kill()
        out = p.communicate(timeout=120)[0].decode("utf-8", "replace")
        return p.returncode, out

    def test_it_goes_at_once_under_the_limit(self):
        code, text = self.wait(self.running() + 1, 1)
        self.assertEqual(code, 0, text)
        self.assertIn("went after", text)
        self.assertNotIn("waiting", text)

    def test_it_waits_while_as_many_run_and_goes_on_when_one_ends(self):
        mmd = self.fake_mmd(120)
        code, text = self.wait(self.running(), 1, end_after=2.5, proc=mmd)
        self.assertEqual(code, 0, text)
        self.assertIn("t_01: waiting, ", text)
        went = float(re.search(r"went after ([\d.]+) s", text).group(1))
        self.assertGreaterEqual(went, 2.0, text)

    def test_after_its_wait_it_stops_the_run_with_exit_3_and_clears_what_it_is_given(self):
        self.fake_mmd(120)
        pictures = os.path.join(self.tmp, "pictures", "t_01")
        os.makedirs(pictures)
        with open(os.path.join(pictures, "mmd_00100.png"), "w") as f:
            f.write("picture")
        code, text = self.wait(self.running(), 0.05, clear=pictures)     # 3 seconds
        self.assertEqual(code, 3, text)
        self.assertIn("t_01 STOP: ", text)
        self.assertNotIn("went after", text)
        self.assertFalse(os.path.exists(pictures))


@unittest.skipUnless(WINDOWS, "the driver is Windows PowerShell on the render machine")
class FloorReserveTest(unittest.TestCase):
    """the free space of the workers with a free space kept (keep_free_gb): a chunk starts when the disk holds its peak and the
    space kept after what the chunks under way still have to write (their peak less what their files and folders hold now); it
    waits while those would leave too little and stops the run (exit 3) when even alone it does not fit.  Before MMD draws her,
    the chunk measures again and stops (exit 3) if somebody else took the room meanwhile.  The functions of the driver are run by
    themselves, the free space given"""

    KEEP = 100

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        base = self.tmp.replace("\\", "/")
        plan = mv_chunks.check_plan(dict(CITY_PLAN, out=base + "/out", scripts=base + "/scripts", keep_free_gb=1))
        summary = mv_chunks.write(plan, mv_chunks.plan_chunks(SPANS, lead=120), self.tmp + "/scripts", "t", 240, 0.5, workers=2)
        with open(summary["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        self.functions = "\n".join(DiskReserveTest.function(driver, name)
                                   for name in ("Hold", "Lock-Disk", "Used", "Owed", "Reserve", "Need-Still"))
        self.run = base + "/out/run_t"
        os.makedirs(self.run)

    def busy(self, name, need, files=0, folder=0):
        """a chunk under way that needs `need` bytes at its peak and holds `files` bytes in its AVI and `folder` in a folder of two files"""
        avi, pics = "%s/%s.avi" % (self.run, name), "%s/%s_pictures" % (self.run, name)
        with open(avi, "wb") as f:
            f.write(b"\0" * files)
        os.makedirs(pics)
        for k, n in enumerate((folder // 2, folder - folder // 2)):
            with open("%s/mmd_%05d.png" % (pics, k), "wb") as f:
                f.write(b"\0" * n)
        with open("%s/busy_%s" % (self.run, name), "w", encoding="utf-8") as f:
            f.write("%d|%s|%s" % (need, avi, pics))

    def call(self, line, free, gone_after=None):
        script = os.path.join(self.tmp, "call.ps1")
        with open(script, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("$run = %s\n$out = %s\n$diskWait = 0.2\n$keep = [decimal]%d\n"
                    "function Get-FreeBytes($folder) { return %d }\n%s\n%s\nexit 0\n"
                    % (mv_chunks._ps(self.run), mv_chunks._ps(self.tmp), self.KEEP, free, self.functions, line))
        proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if gone_after is not None:
            time.sleep(gone_after)
            for name in os.listdir(self.run):
                if name.startswith("busy_"):
                    os.remove(os.path.join(self.run, name))
        out = proc.communicate(timeout=120)[0]
        return proc.returncode, out.decode("utf-8", "replace")

    def reserve(self, free, need=1000, gone_after=None):
        code, text = self.call("$went = Reserve 't_02' %d @(%s)\n'went {0}' -f $went" % (need, mv_chunks._ps(self.run + "/t_02.avi")),
                               free, gone_after)
        return code, text, os.path.exists(self.run + "/busy_t_02")

    def test_a_chunk_starts_when_its_peak_leaves_the_space_kept(self):
        code, text, noted = self.reserve(free=1100)
        self.assertEqual(code, 0, text)
        self.assertIn("went True", text)
        self.assertTrue(noted)
        with open(self.run + "/busy_t_02", encoding="utf-8") as f:
            self.assertEqual(f.read().split("|")[0], "1000")

    def test_too_little_even_alone_stops_the_run_with_exit_3(self):
        code, text, noted = self.reserve(free=1099)
        self.assertEqual(code, 3, text)
        self.assertIn("t_02 STOP: ", text)
        self.assertFalse(noted)

    def test_it_waits_while_a_chunk_under_way_would_leave_too_little_and_counts_what_its_folders_hold(self):
        # chunk 00 needs 2000 at its peak and holds 300 in its AVI and 500 in its folder of pictures: 1200 to go.  With 2300 free,
        # 2300 - 1200 - 1000 = 100 = the space kept: it goes at once
        self.busy("t_00", 2000, files=300, folder=500)
        code, text, noted = self.reserve(free=2300)
        self.assertEqual(code, 0, text)
        self.assertIn("went True", text)
        os.remove(self.run + "/busy_t_02")
        # one byte less and it waits until chunk 00 is done
        code, text, noted = self.reserve(free=2299, gone_after=2)
        self.assertEqual(code, 0, text)
        self.assertIn("went True", text)
        self.assertTrue(noted)

    def test_before_mmd_draws_her_the_chunk_stops_if_somebody_took_the_room(self):
        # the chunk under way (this one) needs 2000 and holds 800: 1200 to go, and 1300 are free: 100 kept, it goes on
        self.busy("t_02", 2000, files=0, folder=800)
        code, text = self.call("Need-Still 't_02' @()\n'went on'", free=1300)
        self.assertEqual(code, 0, text)
        self.assertIn("went on", text)
        # one byte less: it stops (exit 3) and clears what it is given (its pictures)
        code, text = self.call("Need-Still 't_02' @(%s)\n'went on'" % mv_chunks._ps(self.run + "/t_02_pictures"), free=1299)
        self.assertEqual(code, 3, text)
        self.assertIn("t_02 STOP: ", text)
        self.assertNotIn("went on", text)
        self.assertFalse(os.path.exists(self.run + "/t_02_pictures"))


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

    def render(self, motions, switches="", out_fps=30, workers=1, out="out"):
        plan = mv_chunks.check_plan({"mmd": "C:/MMD/MikuMikuDance.exe", "model": "C:/MMD/model.pmx", "motions": motions,
                                     "camera": "C:/work/camera.vmd", "look": self.look, "out": self.base + "/" + out,
                                     "scripts": self.base + "/scripts", "mmd_cli": self.fake, "size": [self.W, self.H]})
        spans = mv_chunks.spans_from_cuts([40, 90], 119)
        summary = mv_chunks.write(plan, mv_chunks.plan_chunks(spans, lead=30), self.base + "/scripts", "t", 240, 0.5,
                                  out_fps=out_fps, workers=workers)
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

    def test_workers_make_the_video_of_one_worker_byte_for_byte(self):
        # the real tools/mv_look.py and ffmpeg: chunks folded at the same time with the layers prepared once are the chunks
        # folded one after the other, each with its layers drawn again
        for out_fps, workers in ((30, 2), (60, 3)):
            with self.subTest(out_fps=out_fps, workers=workers):
                one = self.render(["C:/work/dance.vmd"], out_fps=out_fps, out="one%d" % out_fps)[0]
                many, text = self.render(["C:/work/dance.vmd"], out_fps=out_fps, workers=workers, out="many%d" % out_fps)
                tag = "t" if out_fps == 30 else "t_60fps"
                for name in ["mv_%s.mp4" % tag] + ["%s_%02d.mp4" % (tag, i) for i in range(3)]:
                    self.assertEqual(sha256_of("%s/many%d/%s" % (self.base, out_fps, name)),
                                     sha256_of("%s/one%d/%s" % (self.base, out_fps, name)), name)
                frames = [f for f, _, _ in self.read_back(many)]
                self.assertEqual(frames, list(range(120)) if out_fps == 30 else [n for n in range(120) for _ in (0, 1)])

    def test_at_60_fps_every_song_frame_is_two_frames_from_the_two_halves_of_its_subframes(self):
        joined, text = self.render(["C:/work/dance.vmd"], out_fps=60)
        self.assertTrue(joined.endswith("/out/mv_t_60fps.mp4"), joined)
        frames = self.read_back(joined)
        self.assertEqual([f for f, _, _ in frames], [n for n in range(120) for _ in (0, 1)])
        # 240 fps folded to 60 with the shutter open half the frame: frame 2n is the mean of subframes 0 and 1 of song
        # frame n (red 0 and 32), frame 2n + 1 the mean of subframes 4 and 5 (red 128 and 160)
        reds = [red for _, red, _ in frames]
        self.assertTrue(all(abs(red - 16) < 6 for red in reds[0::2]), [round(red) for red in reds[0::2]])
        self.assertTrue(all(abs(red - 144) < 6 for red in reds[1::2]), [round(red) for red in reds[1::2]])
        # across the joins (concat -c copy) the frames follow each other every 1/60 s
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                                "-of", "csv=p=0", joined], capture_output=True, text=True, stdin=subprocess.DEVNULL, check=True)
        times = [float(t.strip().strip(",")) for t in probe.stdout.split() if t.strip().strip(",")]
        self.assertEqual(len(times), 240)
        self.assertEqual({round((b - a) * 60, 3) for a, b in zip(times, times[1:])}, {1.0})


# The SHA-256 of the scripts main 4f034ce's tools/mv_chunks.py wrote for plans without a stage of a model, beyond the default
# plan of GOLDEN_30 and GOLDEN_60: in the world, with workers, fast spans, the physics aligned, the soft self shadow, 60 fps and
# nvenc (render12, _spike/out/stage6/render12/golden_main.py).  The stage of a model drawn chunk by chunk and the free space kept
# on the disk change nothing of them
WORLD_PLAN = dict(PLAN, world=True, accessories=[])
MAIN_VARIANTS = {
    "world": (WORLD_PLAN, dict(tag="w", fps=240, shutter=0.5)),
    "world_workers_fast_align": (WORLD_PLAN, dict(tag="wf", fps=480, shutter=0.5, workers=2, align_physics=True,
                                                  fast={"spans": [(4.0, 5.0)], "fps": 960})),
    "soft_workers_60_nvenc": (dict(PLAN, self_shadow="soft"), dict(tag="s", fps=240, shutter=0.5, workers=3, out_fps=60,
                                                                    encoder="nvenc")),
    "world_jobs8_nocues_workers": (dict(WORLD_PLAN, stage_jobs=8, cues=None), dict(tag="j", fps=240, shutter=0.5, workers=2)),
}
MAIN_4F034CE = {
    "soft_workers_60_nvenc": {
        "chunk_s_60fps_nvenc_00.txt": "f3e88238abd3a0745c2d287d48bedee0171a7447dee801c5f517591a3d3a174f",
        "chunk_s_60fps_nvenc_01.txt": "947485d6278d1db32fb9f789f5e56bb8495f5cce57abbcb9d239550b2f990e48",
        "chunk_s_60fps_nvenc_02.txt": "308497b2535a70b85b1d7bb96339a56a535134d285d12bffa6ea4f443fb24003",
        "concat_s_60fps_nvenc.txt": "a184be7bc0676c5cad602a405a1021f91b2ea5ca6e82e2ecd7be0f9aac2dae40",
        "render_s_60fps_nvenc.ps1": "6a7821319f812951b582e2faf059d1da6e12596e88475716d806f722b4583be1"},
    "world": {
        "chunk_w_00.txt": "95c530f97da710ef5bee416890d5563e07d9a58f029554c09ecc2d64d4ebcd59",
        "chunk_w_01.txt": "76d34f2b3dcf5fb18664ed6b4617d6d968f9ae91769a52815f9aae39c4374394",
        "chunk_w_02.txt": "b9c92ed2eba7b1322228b0041bdbc70ef9eff77dae21a217db3b8178284fa05d",
        "concat_w.txt": "7c25942fc2ce5f11737b513e6d75430b61fa0bc3f06f9e9f8b4c733d8b32916a",
        "render_w.ps1": "f216565dd72e548a003e1646f94f67993b45f5169662d0ec6893da4811f93d2e"},
    "world_jobs8_nocues_workers": {
        "chunk_j_00.txt": "b100978036a68dc8ed7a1b2349a4490f0b62262d9363025117b9c846ce8aa517",
        "chunk_j_01.txt": "1a36ae01064b2c90b43d7e6759fbdc1eda2807399f23437c9b4a29952c77a977",
        "chunk_j_02.txt": "bd8bec000273a30396e2f197c64fd62d066e2efc3c285b9cabc030082fd25af2",
        "concat_j.txt": "f7b3c05be056fa1076fe2bbe885165ae9fde663a65f537cc2926e3889720ed57",
        "render_j.ps1": "79016a30bfe3968b9ea0880784d40052f316071e0d56c47c7d34e33e4257d8c8"},
    "world_workers_fast_align": {
        "chunk_wf_00.txt": "b05c4f941aa36624f890994d059974d96dcefa6613f5d60fe52a78ffef5c9b78",
        "chunk_wf_01.txt": "152b7c3e0ad746769241fe626d500de3023b8e81a8a24d83f737fe14fe608559",
        "chunk_wf_02.txt": "3fb14b199a541d8dd497fdf8a026d53c31f702dda61ac3dc62ab2d840e88ad50",
        "concat_wf.txt": "06a18cb678a3c337c123c8a399425f9bad9e6f9c56eaa9cb0dbfe99286ff710a",
        "render_wf.ps1": "a70c3f2f2d3d4cef905f6ca99eec33370b942eaa4d3e4737aad1b5758f566fea"},
}


class MainBytesTest(unittest.TestCase):
    def test_plans_without_a_stage_of_a_model_get_the_scripts_main_wrote(self):
        for name, (plan, kw) in MAIN_VARIANTS.items():
            with self.subTest(variant=name):
                folder = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, folder, True)
                kw = dict(kw)
                tag, fps, shutter = kw.pop("tag"), kw.pop("fps"), kw.pop("shutter")
                summary = mv_chunks.write(mv_chunks.check_plan(dict(plan)), mv_chunks.plan_chunks(SPANS, 120), folder, tag, fps,
                                          shutter, **kw)
                self.assertEqual(hashes(folder), MAIN_4F034CE[name])
                self.assertNotIn("disk", summary)                  # no free space is kept: the summary of before


CITY_PLAN = dict(PLAN, world=True, accessories=[], stage_set="C:/work/song/stage/city.json",
                 stage_pictures="C:/work/song/stage_pictures", stage_mmd="C:/MMD_plain/MikuMikuDance.exe")


class StagePlanTest(unittest.TestCase):
    """A stage of a model drawn chunk by chunk ("stage_mmd": the plain MMD that draws it before every chunk, into a folder of
    the chunk under "stage_pictures") and the free space the driver keeps on the disk ("keep_free_gb"): what the plan takes,
    what every fold gets and what the summary says of the disk"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, plan, fps=240, workers=1, out_fps=30, spans=SPANS):
        folder = os.path.join(self.tmp, "s%d" % len(os.listdir(self.tmp)))
        return mv_chunks.write(mv_chunks.check_plan(dict(plan)), mv_chunks.plan_chunks(spans, 120), folder, "t", fps, 0.5,
                               out_fps=out_fps, workers=workers)

    def test_stage_mmd_goes_with_a_stage_of_a_model_and_is_an_absolute_path(self):
        self.assertEqual(mv_chunks.check_plan(dict(CITY_PLAN))["stage_mmd"], "C:/MMD_plain/MikuMikuDance.exe")
        self.assertIsNone(mv_chunks.check_plan(dict(CITY_PLAN, stage_mmd=None))["stage_mmd"])      # the pictures drawn before
        self.assertIsNone(mv_chunks.check_plan(dict(PLAN))["stage_mmd"])
        for bad in ({"stage_mmd": "MikuMikuDance.exe"}, {"stage_mmd": 3}, {"stage_mmd": ""},
                    {"stage_set": None, "stage_pictures": None}):                  # no stage of a model to draw
            with self.assertRaises(ValueError, msg=bad):
                mv_chunks.check_plan(dict(CITY_PLAN, **bad))

    def test_30_gb_are_kept_free_with_a_stage_of_a_model_and_nothing_without_unless_the_plan_says(self):
        self.assertEqual(mv_chunks.check_plan(dict(CITY_PLAN))["keep_free_gb"], 30)
        self.assertEqual(mv_chunks.check_plan(dict(CITY_PLAN, stage_mmd=None))["keep_free_gb"], 30)
        self.assertIsNone(mv_chunks.check_plan(dict(PLAN))["keep_free_gb"])                # the plans of before
        self.assertIsNone(mv_chunks.check_plan(dict(WORLD_PLAN))["keep_free_gb"])
        self.assertIsNone(mv_chunks.check_plan(dict(CITY_PLAN, keep_free_gb=None))["keep_free_gb"])
        self.assertEqual(mv_chunks.check_plan(dict(PLAN, keep_free_gb=12.5))["keep_free_gb"], 12.5)   # any plan may ask
        self.assertEqual(mv_chunks.check_plan(dict(CITY_PLAN, keep_free_gb=0))["keep_free_gb"], 0)
        for bad in (-1, "30", True, float("nan"), float("inf"), [30]):
            with self.assertRaises(ValueError, msg=bad) as ctx:
                mv_chunks.check_plan(dict(CITY_PLAN, keep_free_gb=bad))
            self.assertIn("keep_free_gb", str(ctx.exception))

    def test_the_pictures_of_the_chunks_lie_outside_what_resume_watches(self):
        # the driver makes and removes a folder of pictures for every chunk: in a watched folder every chunk would look like a
        # changed input
        for root in ("C:/MMD/UserFile/Model/Rin/pictures", "C:/work/mmd-cli/tools/pictures", "c:\\mmd\\userfile\\model\\rin"):
            with self.assertRaises(ValueError, msg=root) as ctx:
                mv_chunks.check_plan(dict(CITY_PLAN, stage_pictures=root))
            self.assertIn("inside", str(ctx.exception))
        # pictures drawn before are an input (-Resume watches them): the output may not lie among them
        for change in ({"out": "C:/work/song/stage_pictures/out"}, {"scripts": "C:/work/song/stage_pictures/mv"}):
            with self.assertRaises(ValueError, msg=change) as ctx:
                mv_chunks.check_plan(dict(CITY_PLAN, stage_mmd=None, **change))
            self.assertIn("inside", str(ctx.exception))
        mv_chunks.check_plan(dict(CITY_PLAN, out="C:/work/song/stage_pictures/out"))      # chunk by chunk they are no input

    def test_every_fold_reads_the_pictures_of_its_chunk_and_draws_its_stage_in_a_folder_of_its_own(self):
        plan = mv_chunks.check_plan(dict(CITY_PLAN))
        chunks = mv_chunks.plan_chunks(SPANS, 120)
        for c in chunks:
            fold = mv_chunks.fold_args(plan, "t", c, 240, 0.5)
            self.assertEqual(value(fold, "--stage-pictures"), "C:/work/song/stage_pictures/t_%02d" % c["index"])
            self.assertEqual(value(fold, "--work"), "C:/work/song/out/look_work_t_%02d" % c["index"])
            self.assertEqual(value(fold, "--stage-set"), "C:/work/song/stage/city.json")
        # the pictures drawn before: the folder of the plan for every chunk, as before
        before = mv_chunks.check_plan(dict(CITY_PLAN, stage_mmd=None))
        fold = mv_chunks.fold_args(before, "t", chunks[1], 240, 0.5)
        self.assertEqual((value(fold, "--stage-pictures"), value(fold, "--work")),
                         ("C:/work/song/stage_pictures", "C:/work/song/out/look_work_t"))

    def test_the_workers_fold_every_chunk_with_its_own_stage_and_prepare_nothing(self):
        # the stage of a chunk is drawn when the chunk comes (its pictures are not there before): no prepare of the stage of every
        # chunk before the workers start, and every fold draws its layers, its text and its stage in its own folder
        with open(self.written(CITY_PLAN, workers=2)["driver"], encoding="utf-8-sig") as f:
            driver = f.read()
        self.assertNotIn("tools/mv_look.py prepare", driver)
        self.assertEqual(len([l for l in driver.splitlines() if "tools/mv_look.py layers" in l]), 1)
        calls = re.findall(r"if \(Take '(t_\d\d)'\) \{ Run-Chunk (.*)\}$", driver, re.M)
        self.assertEqual([n for n, _ in calls], ["t_00", "t_01", "t_02"])
        for name, call in calls:
            self.assertIn("'--work', 'C:/work/song/out/look_work_%s'" % name, call)
            self.assertIn("'--stage-pictures', 'C:/work/song/stage_pictures/%s'" % name, call)
            self.assertNotIn("'--prepared'", call)

    def test_the_recipe_holds_how_the_stage_of_the_chunk_is_drawn(self):
        # -Resume does not keep an mp4 whose stage was drawn another way
        plan = mv_chunks.check_plan(dict(CITY_PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, 120)[1]
        made = mv_chunks.recipe(plan, "t", chunk, 240, 0.5)
        for change in ({"stage_mmd": None}, {"stage_mmd": "C:/MMD2/MikuMikuDance.exe"}, {"size": [640, 360]}):
            self.assertNotEqual(made, mv_chunks.recipe(mv_chunks.check_plan(dict(CITY_PLAN, **change)), "t", chunk, 240, 0.5), change)
        self.assertEqual(made, mv_chunks.recipe(mv_chunks.check_plan(dict(CITY_PLAN)), "t", chunk, 240, 0.5))

    def test_the_summary_gives_the_peak_of_every_chunk_on_the_disk(self):
        disk = self.written(CITY_PLAN)["disk"]
        self.assertEqual(disk["keep_free_gb"], 30)
        chunks = disk["chunks"]
        self.assertEqual([c["chunk"] for c in chunks], [0, 1, 2])
        for c in chunks:
            # while the chunk folds, the person's AVI, the chunk's pictures, the stage's frames and the mp4 are there at once; the
            # stage's AVI is gone by then (unpacked and deleted before MMD draws her)
            self.assertAlmostEqual(c["peak_gb"], c["avi_gb"] + c["pictures_gb"] + c["stage_gb"] + c["mp4_gb"], delta=0.015)
            self.assertGreater(c["peak_gb"], c["stage_avi_gb"] + c["pictures_gb"])
            self.assertTrue(all(c[k] > 0 for k in ("avi_gb", "stage_avi_gb", "pictures_gb", "stage_gb", "mp4_gb")), c)
        # the person's AVI holds every subframe of the lead-in and the shot (chunk 1: 250 frames of the song at 240 fps); the
        # stage's AVI the 150 frames the chunk shows at 30 fps (both BGRA)
        self.assertAlmostEqual(chunks[1]["avi_gb"], 250 * 8 * 1280 * 720 * 4 / 1024.0 ** 3, delta=0.01)
        self.assertAlmostEqual(chunks[1]["stage_avi_gb"], 150 * 1280 * 720 * 4 / 1024.0 ** 3, delta=0.01)
        self.assertEqual(max(range(3), key=lambda i: chunks[i]["peak_gb"]), disk["largest_chunk"])
        # twice the subframes, twice the person's AVI; the pictures and the stage's frames stay
        for a, b in zip(chunks, self.written(CITY_PLAN, fps=480)["disk"]["chunks"]):
            self.assertAlmostEqual(b["avi_gb"], 2 * a["avi_gb"], delta=0.01)
            self.assertEqual((b["pictures_gb"], b["stage_gb"]), (a["pictures_gb"], a["stage_gb"]))
        # at 60 fps as many pictures (MMD draws the stage at the frames of the song), twice the stage's frames
        for a, b in zip(chunks, self.written(CITY_PLAN, out_fps=60)["disk"]["chunks"]):
            self.assertEqual(b["pictures_gb"], a["pictures_gb"])
            self.assertAlmostEqual(b["stage_gb"], 2 * a["stage_gb"], delta=0.01)
        # pictures drawn before take no room of the chunk; a plan that keeps no free space says nothing of the disk
        before = self.written(dict(CITY_PLAN, stage_mmd=None))["disk"]["chunks"]
        self.assertTrue(all(c["stage_avi_gb"] == 0 and c["pictures_gb"] == 0 for c in before), before)
        self.assertNotIn("disk", self.written(dict(CITY_PLAN, keep_free_gb=None)))
        self.assertIn("disk", self.written(dict(PLAN, keep_free_gb=10)))

    def test_the_free_space_to_start_with_holds_the_floor_and_the_peaks_of_the_chunks_at_once(self):
        one = self.written(CITY_PLAN)["disk"]
        two = self.written(CITY_PLAN, workers=2)["disk"]
        peaks = sorted((c["peak_gb"] for c in one["chunks"]), reverse=True)
        self.assertGreaterEqual(one["start_free_gb"], 30 + peaks[0])
        self.assertLess(one["start_free_gb"], 30 + peaks[0] + peaks[1])
        self.assertGreaterEqual(two["start_free_gb"], 30 + peaks[0] + peaks[1])
        self.assertEqual([c["peak_gb"] for c in two["chunks"]], [c["peak_gb"] for c in one["chunks"]])


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

    def test_fast_spans_on_the_command_line(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "f"), "--shots", self.report, "--tag", "t", "--fps", "480",
                              "--fast-spans", "4.0-5.0", "--fast-fps", "960")
        self.assertEqual(code, 0, res)
        self.assertEqual(res["fast"], {"fps": 960, "subframes": 32, "spans": [[4.0, 5.0]], "chunks": [1]})
        for argv in (("--fast-spans", "4.0-5.0"), ("--fast-fps", "960"), ("--fast-spans", "x", "--fast-fps", "960")):
            code, res = self.main(self.plan, os.path.join(self.tmp, "g"), "--shots", self.report, "--fps", "480", *argv)
            self.assertEqual(code, 2, (argv, res))

    def test_cuts_can_stand_in_for_a_camera_report(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--cuts", "100", "250", "--last", "299", "--fps", "60")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["chunks"], res["frames"], res["subframes"]), (3, 300, 2))

    def test_out_fps_60_writes_a_version_to_watch_with_twice_the_frames(self):
        outdir = os.path.join(self.tmp, "s")
        code, res = self.main(self.plan, outdir, "--shots", self.report, "--tag", "t", "--out-fps", "60")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["out_fps"], res["fps"], res["subframes"], res["frames"]), (60, 240, 4, 600))
        self.assertEqual(res["spans"], [[0, 99], [100, 249], [250, 299]])               # frames of the song, as at 30
        self.assertEqual(res["joined"], "C:/work/song/out/mv_t_60fps.mp4")
        self.assertEqual(sorted(os.listdir(outdir)), ["chunk_t_60fps_00.txt", "chunk_t_60fps_01.txt", "chunk_t_60fps_02.txt",
                                                      "concat_t_60fps.txt", "render_t_60fps.ps1"])
        code, res = self.main(self.plan, os.path.join(self.tmp, "d"), "--shots", self.report, "--tag", "t")
        self.assertEqual((code, "out_fps" in res, res["frames"], res["subframes"]), (0, False, 300, 8))
        self.assertEqual(hashes(os.path.join(self.tmp, "d")), GOLDEN_30["t"])

    def test_the_default_prints_the_summary_of_before(self):
        # the names and their order in the line main 60956b2 printed: --out-fps adds nothing at the default
        code, res = self.main(self.plan, os.path.join(self.tmp, "d"), "--shots", self.report, "--tag", "t")
        self.assertEqual(code, 0, res)
        self.assertEqual(list(res), ["ok", "chunks", "frames", "fps", "subframes", "shutter", "codec", "avi_bytes_per_pixel",
                                     "largest_avi_gb", "spans", "driver", "batches", "concat", "joined"])
        code, res = self.main(self.plan, os.path.join(self.tmp, "e"), "--shots", self.report, "--tag", "t", "--out-fps", "30")
        self.assertNotIn("out_fps", res)

    def test_workers_and_the_encoder_are_in_the_summary_only_when_they_are_not_the_default(self):
        code, res = self.main(self.plan, os.path.join(self.tmp, "w"), "--shots", self.report, "--tag", "t", "--workers", "3")
        self.assertEqual((code, res["workers"], res["joined"]), (0, 3, "C:/work/song/out/mv_t.mp4"))
        self.assertNotIn("encoder", res)
        code, res = self.main(self.plan, os.path.join(self.tmp, "n"), "--shots", self.report, "--tag", "t", "--encoder", "nvenc")
        self.assertEqual((code, res["encoder"], res["joined"]), (0, "nvenc", "C:/work/song/out/mv_t_nvenc.mp4"))
        self.assertNotIn("workers", res)
        code, res = self.main(self.plan, os.path.join(self.tmp, "d"), "--shots", self.report, "--tag", "t", "--workers", "1",
                              "--encoder", "x264")
        self.assertEqual(list(res), ["ok", "chunks", "frames", "fps", "subframes", "shutter", "codec", "avi_bytes_per_pixel",
                                     "largest_avi_gb", "spans", "driver", "batches", "concat", "joined"])
        self.assertEqual(hashes(os.path.join(self.tmp, "d")), GOLDEN_30["t"])

    def test_workers_out_of_range_or_an_unknown_encoder_are_errors_in_json(self):
        for flag, given in (("--workers", "0"), ("--workers", "9"), ("--workers", "-2"), ("--encoder", "h265"), ("--encoder", "")):
            code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, flag, given)
            self.assertEqual(code, 2, (flag, given))
            self.assertIn(flag, res["error"], (flag, given))

    def test_an_output_rate_other_than_30_or_60_is_refused(self):
        for out_fps in ("50", "120", "0"):
            code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--out-fps", out_fps)
            self.assertEqual(code, 2, out_fps)
            self.assertIn("--out-fps", res["error"])
        code, res = self.main(self.plan, os.path.join(self.tmp, "s"), "--shots", self.report, "--fps", "30", "--out-fps", "60")
        self.assertEqual(code, 2)
        self.assertIn("--fps", res["error"])

    def test_a_frame_rate_mmd_does_not_render_is_refused(self):
        for fps in ("100", "90", "720", "1920"):
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
