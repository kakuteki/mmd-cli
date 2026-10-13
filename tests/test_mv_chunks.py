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
                                             "--motion", "C:/work/song/dance.vmd", "--motion", LIPS])
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 240, 0.5),
                            mv_chunks.recipe(mv_chunks.check_plan(dict(PLAN, accessories=[])), "t", chunk, 240, 0.5))

    def test_the_look_check_reads_them_before_mmd_renders(self):
        driver = self.written("one")
        check = [l for l in driver.splitlines() if l.startswith("$check = ")]
        self.assertEqual(len(check), 1)
        self.assertTrue(check[0].endswith("--size 1280x720 --fps 30 --camera 'C:/work/song/camera.vmd' --model "
                                          "'C:/MMD/UserFile/Model/Rin/White.pmx' --motion 'C:/work/song/dance.vmd' --motion '%s'"
                                          % LIPS), check)

    def test_the_workers_prepare_the_stage_of_their_chunks_with_their_shutter(self):
        driver = self.written("two", workers=2)
        prepare = [l for l in driver.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertEqual(len(prepare), 1)
        self.assertIn(" --camera 'C:/work/song/camera.vmd' ", prepare[0])
        self.assertTrue(prepare[0].endswith("--subframes 8 --shutter 0.5 --from 0.000000 --to 10.000000"), prepare)
        sixty = self.written("sixty", workers=2, out_fps=60)
        prepare = [l for l in sixty.splitlines() if "tools/mv_look.py prepare" in l]
        self.assertTrue(prepare[0].endswith("--subframes 4 --shutter 0.5 --from 0.000000 --to 10.000000"), prepare)


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
                        looks_ok = fps in (30, 60, 120, 240, 480)
                    except ValueError:
                        looks_ok = False
                    try:
                        mv_chunks.write(plan, chunks, folder, "t", fps, shutter, out_fps=out_fps)
                        ok = True
                    except ValueError:
                        ok = False
                    self.assertEqual(ok, looks_ok, (out_fps, fps, shutter))


STUBS = r"""
$log = $env:STUB_LOG
function python {
    Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ') + ' home=' + $env:MMD_CLI_HOME) -Encoding UTF8
    if ($args[0] -eq '-m') {
        if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) { $global:LASTEXITCODE = 1; return }
        $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
        $r = $render | ConvertFrom-Json
        # the AVI holds its rate, as the header of MMD's AVI does
        Set-Content -LiteralPath $r[2] -Value $r[[array]::IndexOf($r, '--fps') + 1]
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
    # the output runs at the rate of the AVI over the subframes (mv_look reads the rate from the AVI)
    $rate = [double](Get-Content -LiteralPath $avi -TotalCount 1)
    $sub = [double]$args[[array]::IndexOf($args, '--subframes') + 1]
    $n = [int][math]::Round(($to - $from) * $rate / $sub)
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
    "python.ps1": r"""
$log = $env:STUB_LOG + '.' + $PID
Add-Content -LiteralPath $log -Value ('python ' + ($args -join ' ') + ' home=' + $env:MMD_CLI_HOME) -Encoding UTF8
if ($args[0] -eq '-m') {
    if ($env:STUB_SLOW -and (($args -join ' ') -like ('*' + $env:STUB_SLOW + '*'))) { Start-Sleep -Seconds 3 }
    if ($env:STUB_BATCH_FAILS -and (($args -join ' ') -like ('*' + $env:STUB_BATCH_FAILS + '*'))) { $global:LASTEXITCODE = 1; return }
    $render = Get-Content -LiteralPath $args[-1] -Encoding UTF8 | Where-Object { $_ -like '*"render"*' }
    $r = $render | ConvertFrom-Json
    Set-Content -LiteralPath $r[2] -Value $r[[array]::IndexOf($r, '--fps') + 1]
    $global:LASTEXITCODE = 0
    return
}
if ($args[1] -eq 'layers' -or $args[1] -eq 'prepare') {
    try { $null = Get-Content -LiteralPath $args[2] -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
    catch { '{"ok": false, "error": "the look is not JSON"}'; $global:LASTEXITCODE = 2; return }
    '{"ok": true}'
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
elseif ($env:STUB_LOOK_FAILS -and ($mp4 -like ('*' + $env:STUB_LOOK_FAILS + '*'))) { $why = 'stub failure' }
if ($why) { '{"ok": false, "error": "' + $why + '"}'; $global:LASTEXITCODE = 2; return }
$rate = [double](Get-Content -LiteralPath $avi -TotalCount 1)
$sub = [double]$args[[array]::IndexOf($args, '--subframes') + 1]
$n = [int][math]::Round(($to - $from) * $rate / $sub)
if ($env:STUB_SHORT -and ($mp4 -like ('*' + $env:STUB_SHORT + '*'))) { $n = $n - 1 }
Set-Content -LiteralPath $mp4 -Value $n
'{"ok": true}'
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
