import contextlib
import io
import json
import math
import os
import tempfile
import unittest

from mmd_cli import cli, dialogs

try:
    from mmd_cli import app
except ImportError:          # not on Windows
    app = None

from mmd_cli.formats import vmd
from tests.test_motion_edit import camera_motion, model_motion
from tests.test_pmd import bone as pmd_bone, build as build_pmd, skin as pmd_skin
from tests.test_pmx import Writer as PmxWriter


def parse(argv):
    with contextlib.redirect_stderr(io.StringIO()):   # argparse prints usage on errors
        return cli.build_parser().parse_args(argv)


class ParserTest(unittest.TestCase):
    def test_global_options_come_before_the_command(self):
        a = parse(["--pid", "12", "--out", "x.json", "--timeout", "30", "state"])
        self.assertEqual((a.pid, a.out, a.timeout, a.command), (12, "x.json", 30.0, "state"))
        self.assertIsNone(parse(["state"]).timeout)

    def test_launch_headless_and_window_actions(self):
        self.assertTrue(parse(["launch", "--headless"]).headless)
        self.assertFalse(parse(["launch"]).headless)
        for action in ("status", "show", "hide", "minimize"):
            self.assertEqual(parse(["window", action]).action, action)

    def test_relay_flags_are_global(self):
        self.assertTrue(parse(["--in-user-session", "state"]).in_user_session)
        self.assertTrue(parse(["--no-relay", "state"]).no_relay)

    def test_save_commands(self):
        self.assertEqual(parse(["motion", "save", "a.vmd"]).action, "save")
        self.assertEqual(parse(["pose", "save", "a.vpd", "--model", "1"]).model, "1")
        self.assertEqual(parse(["render", "codecs"]).action, "codecs")

    def test_batch_takes_a_file_or_stdin(self):
        a = parse(["batch", "script.txt"])
        self.assertEqual((a.command, a.file, a.keep_going), ("batch", "script.txt", False))
        self.assertTrue(parse(["batch", "-", "--keep-going"]).keep_going)

    def test_dump_lists_key_frames_only_on_request(self):
        self.assertFalse(parse(["dump"]).keys)
        self.assertTrue(parse(["dump", "--keys"]).keys)

    def test_file_info_takes_brief(self):
        a = parse(["file", "info", "x.pmx", "--brief"])
        self.assertEqual((a.command, a.action, a.file, a.brief), ("file", "info", "x.pmx", True))
        self.assertFalse(parse(["file", "info", "x.vmd"]).brief)

    def test_model_info_target_is_optional(self):
        a = parse(["model", "info"])
        self.assertEqual((a.command, a.action, a.target), ("model", "info", None))
        self.assertEqual(parse(["model", "info", "初音ミク"]).target, "初音ミク")
        self.assertEqual(parse(["model", "info", "C:/models/miku.pmx"]).target, "C:/models/miku.pmx")

    def test_camera_set_accepts_negative_numbers(self):
        a = parse(["camera", "set", "--pos", "1.5", "12", "-3.25", "--rot", "10", "20", "5", "--distance", "30",
                   "--fov", "45", "--register"])
        self.assertEqual((a.command, a.action), ("camera", "set"))
        self.assertEqual(a.pos, [1.5, 12.0, -3.25])
        self.assertEqual(a.rot, [10.0, 20.0, 5.0])
        self.assertEqual((a.distance, a.fov, a.register, a.perspective), (30.0, 45, True, None))

    def test_bone_set(self):
        a = parse(["bone", "set", "センター", "--pos", "0", "5", "0", "--frame", "10"])
        self.assertEqual((a.name, a.pos, a.rot, a.quat, a.frame), ("センター", [0.0, 5.0, 0.0], None, None, 10))

    def test_bone_rot_and_quat_exclude_each_other(self):
        with self.assertRaises(SystemExit):
            parse(["bone", "set", "頭", "--rot", "0", "0", "0", "--quat", "0", "0", "0", "1"])

    def test_morph_set_takes_a_value(self):
        a = parse(["morph", "set", "まばたき", "0.75"])
        self.assertEqual((a.name, a.value), ("まばたき", 0.75))

    def test_render_avi_requires_a_range(self):
        with self.assertRaises(SystemExit):
            parse(["render", "avi", "x.avi"])
        a = parse(["render", "avi", "x.avi", "--from", "0", "--to", "30", "--size", "640", "360"])
        self.assertEqual((a.start, a.end, a.size, a.fps), (0, 30, [640, 360], 30))

    def test_accessory_visibility_flags(self):
        self.assertEqual(parse(["accessory", "set", "negi.x", "--hide"]).visible, False)
        self.assertEqual(parse(["accessory", "set", "negi.x", "--show"]).visible, True)
        self.assertIsNone(parse(["accessory", "set", "negi.x"]).visible)

    def test_unknown_command_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            parse(["fly"])
        self.assertEqual(ctx.exception.code, 2)

    def test_non_finite_numbers_are_usage_errors(self):
        # argparse's float accepts "nan" and "inf"; MMD's boxes and the vmd fields have no use for them
        for argv in (["morph", "set", "あ", "nan"], ["camera", "set", "--pos", "1", "inf", "0"],
                     ["bone", "set", "頭", "--rot", "0", "nan", "0"],
                     ["bone", "set", "頭", "--quat", "0", "0", "0", "-inf"], ["light", "set", "--dir", "nan", "0", "0"],
                     ["accessory", "set", "negi.x", "--pos", "0", "0", "Infinity"]):
            with self.assertRaises(SystemExit) as ctx:
                parse(argv)
            self.assertEqual(ctx.exception.code, 2, argv)
        self.assertEqual(parse(["morph", "set", "あ", "1e-3"]).value, 0.001)
        self.assertEqual(parse(["camera", "set", "--pos", "-1.5", "2", "3"]).pos, [-1.5, 2.0, 3.0])


class TargetTest(unittest.TestCase):
    def test_camera_keyword_digits_and_names(self):
        self.assertIsNone(cli.parse_target("camera"))
        self.assertEqual(cli.parse_target("2"), 2)
        self.assertEqual(cli.parse_target("初音ミク"), "初音ミク")
        self.assertIsNone(cli.parse_target(None))

    def test_fullwidth_digits_are_a_name(self):
        # str.isdigit is true for "１" (and int("１") is 1): a model called "１" must stay a name
        self.assertEqual(cli.parse_target("１"), "１")
        self.assertEqual(cli.parse_target("²"), "²")       # isdigit, but int() rejects it
        self.assertEqual(cli.parse_target("-1"), "-1")
        self.assertEqual(cli.parse_target(""), "")


class OutputTest(unittest.TestCase):
    def test_stdout_is_ascii_json(self):
        stream = io.StringIO()
        cli.emit({"ok": True, "name": "初音ミク"}, None, stream)
        text = stream.getvalue()
        text.encode("ascii")
        self.assertEqual(json.loads(text), {"ok": True, "name": "初音ミク"})
        self.assertTrue(text.endswith("\n"))

    def test_out_file_is_utf8_and_stdout_points_to_it(self):
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "r.json")
        stream = io.StringIO()
        cli.emit({"ok": True, "name": "初音ミク"}, target, stream)
        with open(target, encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("初音ミク", raw)
        self.assertEqual(json.loads(raw)["name"], "初音ミク")
        self.assertEqual(json.loads(stream.getvalue()), {"ok": True, "out": target})


class EmitTest(unittest.TestCase):
    def test_out_directory_is_created(self):
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "deep", "er", "r.json")
        cli.emit({"ok": True}, target, io.StringIO())
        with open(target, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"ok": True})

    def test_no_stdout_is_fine(self):
        # pythonw.exe has no console: sys.stdout is None there
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "r.json")
        cli.emit({"ok": True}, target, None)
        self.assertTrue(os.path.exists(target))


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


class ModelFiles(unittest.TestCase):
    """a folder with a tiny pmx and a tiny pmd"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        w = PmxWriter()
        self.pmx = os.path.join(self.folder, "model.pmx")
        write(self.pmx, w.build(name="pmxモデル", bones=[w.bone("センター"), w.bone("頭", parent=0)],
                                morphs=[w.morph("まばたき", panel=2)], frames=[w.frame("Root", special=True, items=[("bone", 0)])]))
        self.pmd = os.path.join(self.folder, "model.pmd")
        write(self.pmd, build_pmd(name="pmdモデル", bones=[pmd_bone("センター", kind=1)], skins=[pmd_skin("base", 0), pmd_skin("あ", 3)]))


class FileInfoTest(ModelFiles):
    def test_model_files_give_names_counts_and_the_tables(self):
        full = cli._file_info(self.pmx)
        self.assertEqual((full["format"], full["name"], full["counts"]["bones"]), ("pmx", "pmxモデル", 2))
        self.assertEqual([b["name"] for b in full["bones"]], ["センター", "頭"])
        self.assertEqual(full["morphs"][0]["panel"], "eye")
        self.assertEqual(full["display_frames"][0]["items"], [{"kind": "bone", "index": 0}])
        brief = cli._file_info(self.pmd, brief=True)
        self.assertEqual((brief["format"], brief["name"], brief["counts"]["morphs"]), ("pmd", "pmdモデル", 1))
        for key in ("bones", "morphs", "display_frames"):
            self.assertNotIn(key, brief)
        self.assertIn("counts", brief)

    def test_through_the_parser_and_dispatch(self):
        self.assertNotIn("bones", cli.dispatch_any(None, parse(["file", "info", self.pmd, "--brief"])))
        self.assertIn("bones", cli.dispatch_any(None, parse(["file", "info", self.pmx])))
        self.assertEqual(json.loads(json.dumps(cli.dispatch_any(None, parse(["file", "info", self.pmx]))))["name"], "pmxモデル")


class DispatchModelInfoTest(unittest.TestCase):
    def test_model_info_goes_to_the_instance_with_the_parsed_target(self):
        class FakeMmd:
            def model_info(self, target):
                return {"target": target}

        self.assertEqual(cli._dispatch(FakeMmd(), parse(["model", "info", "2"])), {"target": 2})
        self.assertEqual(cli._dispatch(FakeMmd(), parse(["model", "info", "初音ミク"])), {"target": "初音ミク"})
        self.assertEqual(cli._dispatch(FakeMmd(), parse(["model", "info", "C:/m/x.pmx"])), {"target": "C:/m/x.pmx"})
        self.assertEqual(cli._dispatch(FakeMmd(), parse(["model", "info"])), {"target": None})


@unittest.skipUnless(app is not None, "needs Windows")
class ModelInfoTest(ModelFiles):
    def bare(self, dump):
        m = app.Mmd.__new__(app.Mmd)
        m.pid, m.hwnd, m.events, m.in_place, m.timeout, m._controls, m._parking = 4242, 1, [], False, 1.0, None, None
        m.require_ready = lambda allow_playing=False: None
        m.dump = dump
        return m

    def summary(self, selected=1):
        return {"selected_model": selected,
                "models": [{"index": 0, "name": "pmxモデル", "path": self.pmx}, {"index": 1, "name": "初音ミク", "path": self.pmd}]}

    def test_a_file_path_is_read_without_touching_the_project(self):
        m = self.bare(dump=lambda keys=True: self.fail("the project must not be saved for a file"))
        result = m.model_info(self.pmx)
        self.assertEqual((result["path"], result["format"], result["name"]), (os.path.abspath(self.pmx), "pmx", "pmxモデル"))
        self.assertEqual(result["counts"]["bones"], 2)
        self.assertEqual(sorted(k for k in result if k in ("path", "format", "name", "counts", "bones", "morphs", "display_frames")),
                         ["bones", "counts", "display_frames", "format", "morphs", "name", "path"])

    def test_a_loaded_model_is_found_by_selection_index_or_name(self):
        calls = []

        def dump(keys=True):
            calls.append(keys)
            return self.summary()

        m = self.bare(dump)
        self.assertEqual((m.model_info(None)["name"], m.model_info(None)["path"]), ("pmdモデル", self.pmd))
        self.assertEqual(m.model_info(0)["format"], "pmx")
        self.assertEqual(m.model_info("初音ミク")["format"], "pmd")
        self.assertEqual(calls, [False, False, False, False])         # never the key frames

    def test_unknown_models_and_no_selection_are_errors(self):
        m = self.bare(lambda keys=True: self.summary())
        with self.assertRaises(app.MmdError) as ctx:
            m.model_info("nobody")
        self.assertIn("nobody", str(ctx.exception))
        with self.assertRaises(app.MmdError):
            m.model_info(2)
        m = self.bare(lambda keys=True: self.summary(selected=None))
        with self.assertRaises(app.MmdError) as ctx:
            m.model_info(None)
        self.assertIn("select", str(ctx.exception))

    def test_a_hand_opened_project_asks_for_the_file(self):
        def dump(keys=True):
            raise app.MmdError("this project (C:/x.pmm) was not opened through mmd-cli; reading it needs a save")

        with self.assertRaises(app.MmdError) as ctx:
            self.bare(dump).model_info("初音ミク")
        self.assertIn("not opened through mmd-cli", str(ctx.exception))
        self.assertIn("mmd model info FILE", str(ctx.exception))

    def test_a_model_file_that_moved_is_reported_with_its_path(self):
        gone = os.path.join(self.folder, "gone.pmx")
        m = self.bare(lambda keys=True: {"selected_model": 0, "models": [{"index": 0, "name": "x", "path": gone}]})
        with self.assertRaises(app.MmdError) as ctx:
            m.model_info(None)
        self.assertIn(gone, str(ctx.exception))


class MotionKeysEditParserTest(unittest.TestCase):
    def test_motion_keys_takes_one_target_and_a_range(self):
        a = parse(["motion", "keys", "cam.vmd", "--camera", "--from", "0", "--to", "300"])
        self.assertEqual((a.command, a.action, a.file, a.camera, a.start, a.end), ("motion", "keys", "cam.vmd", True, 0, 300))
        a = parse(["motion", "keys", "m.vmd", "--bone", "右腕"])
        self.assertEqual((a.bone, a.camera, a.light, a.morph, a.start, a.end), ("右腕", False, False, None, None, None))
        self.assertEqual(parse(["motion", "keys", "m.vmd", "--morph", "あ"]).morph, "あ")
        self.assertTrue(parse(["motion", "keys", "m.vmd", "--light"]).light)
        with self.assertRaises(SystemExit):
            parse(["motion", "keys", "m.vmd", "--camera", "--bone", "右腕"])

    def test_motion_edit_combines_targets_range_and_operations(self):
        a = parse(["motion", "edit", "in.vmd", "out.vmd", "--camera", "--light", "--bone", "a", "--bone", "b", "--all-bones",
                   "--morph", "x", "--all-morphs", "--from", "10", "--to", "20", "--shift", "-5", "--copy-to", "100", "--replace",
                   "--distance-scale", "0.6", "--distance-add", "-2.5", "--pos-add", "1", "2", "3", "--fov-add", "5",
                   "--fov-set", "30", "--rot-add", "0", "0", "10", "--weight-scale", "0.5", "--weight-set", "1",
                   "--interp", "64", "0", "64", "127"])
        self.assertEqual((a.command, a.action, a.src, a.dst), ("motion", "edit", "in.vmd", "out.vmd"))
        self.assertEqual((a.camera, a.light, a.bone, a.all_bones, a.morph, a.all_morphs), (True, True, ["a", "b"], True, ["x"], True))
        self.assertEqual((a.start, a.end, a.shift, a.copy_to, a.replace, a.delete), (10, 20, -5, 100, True, False))
        self.assertEqual((a.distance_scale, a.distance_add, a.pos_add, a.fov_add, a.fov_set), (0.6, -2.5, [1.0, 2.0, 3.0], 5, 30))
        self.assertEqual((a.rot_add, a.weight_scale, a.weight_set, a.interp), ([0.0, 0.0, 10.0], 0.5, 1.0, [64, 0, 64, 127]))
        self.assertIsNone(a.distance_clamp)
        a = parse(["motion", "edit", "a", "b", "--camera", "--delete"])
        self.assertEqual((a.delete, a.shift, a.bone, a.interp, a.start), (True, None, None, None, None))
        self.assertEqual(parse(["motion", "edit", "a", "b", "--camera", "--distance-clamp", "0", "60"]).distance_clamp, [0.0, 60.0])
        with self.assertRaises(SystemExit):
            parse(["motion", "edit", "a", "b", "--camera", "--distance-clamp", "60"])

    def test_interp_values_outside_0_127_are_usage_errors(self):
        for argv in (["bone", "set", "頭", "--interp", "128", "0", "0", "0"], ["bone", "set", "頭", "--interp", "0", "-1", "0", "0"],
                     ["bone", "set", "頭", "--interp", "0", "0", "0"], ["camera", "set", "--register", "--interp", "1.5", "0", "0", "0"],
                     ["motion", "edit", "a", "b", "--camera", "--interp", "0", "0", "0", "200"]):
            with self.assertRaises(SystemExit) as ctx:
                parse(argv)
            self.assertEqual(ctx.exception.code, 2, argv)
        self.assertEqual(parse(["bone", "set", "頭", "--interp", "0", "127", "20", "107"]).interp, [0, 127, 20, 107])
        self.assertIsNone(parse(["bone", "set", "頭", "--rot", "0", "0", "1"]).interp)
        self.assertEqual(parse(["camera", "set", "--register", "--interp", "64", "0", "64", "127"]).interp, [64, 0, 64, 127])
        self.assertIsNone(parse(["camera", "set", "--distance", "30"]).interp)


class MotionFileCommandsTest(unittest.TestCase):
    """motion keys / motion edit read and write files; they run without MMD, like file info"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cam = os.path.join(self.folder, "cam.vmd")
        self.model = os.path.join(self.folder, "model.vmd")
        self.dst = os.path.join(self.folder, "out.vmd")
        write(self.cam, vmd.dumps(camera_motion()))
        write(self.model, vmd.dumps(model_motion()))

    def test_they_are_standalone(self):
        self.assertTrue(cli.standalone(parse(["motion", "keys", "x.vmd"])))
        self.assertTrue(cli.standalone(parse(["motion", "edit", "x.vmd", "y.vmd", "--camera", "--shift", "1"])))
        self.assertFalse(cli.standalone(parse(["motion", "load", "x.vmd"])))
        self.assertFalse(cli.standalone(parse(["motion", "save", "x.vmd"])))

    def test_from_alone_is_an_error_before_the_file_is_read(self):
        missing = os.path.join(self.folder, "none.vmd")
        with self.assertRaises(ValueError):
            cli.dispatch_any(None, parse(["motion", "keys", missing, "--from", "5"]))
        with self.assertRaises(ValueError):
            cli.dispatch_any(None, parse(["motion", "edit", missing, self.dst, "--camera", "--shift", "1", "--to", "5"]))
        self.assertFalse(os.path.exists(self.dst))

    def test_keys_summary_and_listing(self):
        out = cli.dispatch_any(None, parse(["motion", "keys", self.cam]))
        self.assertEqual((out["kind"], out["counts"]["cameras"], out["ranges"]["cameras"], out["range"]), ("camera", 3, [0, 200], None))
        out = cli.dispatch_any(None, parse(["motion", "keys", self.cam, "--camera", "--from", "0", "--to", "100"]))
        self.assertEqual(([k["frame"] for k in out["keys"]], out["keys"][0]["distance"], out["range"]), ([0, 100], 45.0, [0, 100]))
        out = cli.dispatch_any(None, parse(["motion", "keys", self.model, "--bone", "右腕"]))
        self.assertEqual((out["target"], out["keys"][0]["rot"]), ({"kind": "bone", "name": "右腕"}, [0.0, 0.0, 30.0]))
        self.assertEqual(cli.dispatch_any(None, parse(["motion", "keys", self.model, "--morph", "あ"]))["keys"], [{"frame": 5, "weight": 0.5}])
        self.assertEqual(cli.dispatch_any(None, parse(["motion", "keys", self.cam, "--light"]))["count"], 2)
        json.dumps(out)

    def test_edit_writes_the_output_and_reads_it_back(self):
        out = cli.dispatch_any(None, parse(["motion", "edit", self.cam, self.dst, "--camera", "--from", "0", "--to", "100",
                                            "--distance-scale", "0.6"]))
        self.assertEqual((out["out"], out["targets"][0]["touched"], out["counts"]["cameras"]), (self.dst, 2, 3))
        self.assertEqual([k.distance for k in vmd.load(self.dst).cameras], [-27.0, -36.0, -30.0])
        out = cli.dispatch_any(None, parse(["motion", "edit", self.cam, self.dst, "--camera", "--distance-clamp", "0", "40"]))
        self.assertEqual([k.distance for k in vmd.load(self.dst).cameras], [-40.0, -40.0, -30.0])
        out = cli.dispatch_any(None, parse(["motion", "edit", self.model, self.dst, "--all-bones", "--morph", "あ", "--shift", "100"]))
        self.assertEqual([r.get("name") for r in out["targets"]], ["センター", "右腕", "あ"])
        self.assertEqual(out["counts"], {"bones": 6, "morphs": 3, "cameras": 0, "lights": 0, "shadows": 0, "show_ik": 0})
        out = cli.dispatch_any(None, parse(["motion", "edit", self.model, self.dst, "--bone", "右腕", "--rot-add", "0", "0", "10",
                                            "--pos-add", "1", "0", "0", "--interp", "64", "0", "64", "127"]))
        self.assertEqual(out["targets"][0]["interp"], 2)
        back = [k for k in vmd.load(self.dst).bones if k.name == "右腕"]
        self.assertEqual(back[0].position, (1.0, 0.0, 0.0))
        self.assertEqual(vmd.bone_curves(back[0].interpolation)["x"], (64, 0, 64, 127))

    def test_edit_needs_a_target_and_an_operation_that_fit(self):
        for argv in (["--shift", "1"], ["--camera"], ["--bone", "x", "--distance-scale", "2"], ["--camera", "--delete", "--shift", "1"],
                     ["--camera", "--replace"], ["--light", "--interp", "0", "0", "0", "0"]):
            with self.assertRaises(ValueError, msg=argv):
                cli.dispatch_any(None, parse(["motion", "edit", self.cam, self.dst] + argv))
        self.assertFalse(os.path.exists(self.dst))

    def test_through_main_as_json(self):
        result = os.path.join(self.folder, "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["--no-relay", "--out", result, "motion", "keys", self.cam, "--camera", "--from", "100", "--to", "200"])
        self.assertEqual(code, 0)
        with open(result, encoding="utf-8") as f:
            self.assertEqual([k["frame"] for k in json.load(f)["keys"]], [100, 200])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli.main(["--no-relay", "motion", "edit", self.cam, self.dst, "--camera", "--shift", "-1", "--from", "0", "--to", "0"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stream.getvalue())["error"]["type"], "ValueError")
        self.assertFalse(os.path.exists(self.dst))


class DispatchInterpTest(unittest.TestCase):
    def test_bone_and_camera_set_pass_the_curve(self):
        class FakeMmd:
            def set_bone(self, name, pos=None, rot=None, quat=None, frame=None, model=None, interp=None):
                return {"name": name, "rot": rot, "interp": interp}

            def set_camera(self, pos=None, rot=None, distance=None, fov=None, perspective=None, register=False, interp=None):
                return {"register": register, "interp": interp, "distance": distance}

        self.assertEqual(cli._dispatch(FakeMmd(), parse(["bone", "set", "頭", "--rot", "0", "0", "5", "--interp", "64", "0", "64", "127"])),
                         {"name": "頭", "rot": [0.0, 0.0, 5.0], "interp": [64, 0, 64, 127]})
        self.assertIsNone(cli._dispatch(FakeMmd(), parse(["bone", "set", "頭", "--rot", "0", "0", "5"]))["interp"])
        self.assertEqual(cli._dispatch(FakeMmd(), parse(["camera", "set", "--distance", "30", "--register", "--interp", "64", "0", "64", "127"])),
                         {"register": True, "interp": [64, 0, 64, 127], "distance": 30.0})
        self.assertIsNone(cli._dispatch(FakeMmd(), parse(["camera", "set", "--distance", "30"]))["interp"])


def bare_mmd():
    m = app.Mmd.__new__(app.Mmd)
    m.pid, m.hwnd, m.events, m.in_place, m.timeout, m._controls, m._parking = 4242, 1, [], False, 1.0, None, None
    m.require_ready = lambda allow_playing=False: None
    return m


@unittest.skipUnless(app is not None, "needs Windows")
class SetBoneInterpTest(unittest.TestCase):
    """the vmd that set_bone builds and drops onto MMD"""

    def make(self, dropped):
        raw = {"name": "m", "bones": ["センター"], "bone_current": [{"position": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0, 1.0)}]}
        after = dict(raw, bone_init=[], bone_keys=[{"bone": 0, "frame": 12, "interpolation": list(range(16))}])
        folder = tempfile.mkdtemp()
        m = bare_mmd()
        m._selected_model = lambda model=None: (0, raw)
        m._temp_path = lambda name: os.path.join(folder, name)
        m._drop_motion = lambda path: dropped.append(vmd.load(path))
        m.frame = lambda: 12
        m._project = lambda: {"models": [after]}
        return m

    def test_without_a_curve_the_key_is_linear_as_before(self):
        dropped = []
        result = self.make(dropped).set_bone("センター", rot=(0, 0, 30))
        self.assertEqual(dropped[0].bones[0].interpolation, vmd.DEFAULT_BONE_INTERPOLATION)
        self.assertEqual((dropped[0].model_name, dropped[0].bones[0].name, dropped[0].bones[0].frame), ("m", "センター", 0))
        self.assertNotIn("interp", result)
        self.assertEqual(result["frame"], 12)

    def test_the_curve_goes_into_the_vmd_on_all_four_channels(self):
        dropped = []
        result = self.make(dropped).set_bone("センター", rot=(0, 0, 30), interp=(64, 0, 64, 127))
        key = dropped[0].bones[0]
        self.assertEqual(key.interpolation, vmd.bone_interpolation((64, 0, 64, 127)))
        self.assertEqual(vmd.bone_curves(key.interpolation), {c: (64, 0, 64, 127) for c in vmd.BONE_CHANNELS})
        self.assertEqual(key.interpolation[2:4], b"\x00\x00")
        self.assertEqual((result["interp"], result["interp_in_project"]), ([64, 0, 64, 127], list(range(16))))

    def test_a_bad_curve_is_refused_before_anything_is_dropped(self):
        dropped = []
        with self.assertRaises(ValueError):
            self.make(dropped).set_bone("センター", rot=(0, 0, 30), interp=(200, 0, 0, 0))
        self.assertEqual(dropped, [])


@unittest.skipUnless(app is not None, "needs Windows")
class SetCameraInterpTest(unittest.TestCase):
    """with --interp the key is registered by dropping a one-key camera motion built from the values the
    camera boxes show; without it the register button is pressed as before"""

    SHOWN = {"pos": [1.0, 12.0, -3.25], "rot": [10.0, 20.0, 5.0], "distance": 30.0, "fov": 45, "perspective": True}

    # what the project then holds for the key: 24 interpolation bytes made of the curve (review 4, 3.1)
    def make(self, dropped, clicks, keys=({"frame": 12, "interpolation": [64, 0, 64, 127] * 6, "distance": -30.0},)):
        from mmd_cli.ids import Ctl
        folder = tempfile.mkdtemp()
        m = bare_mmd()
        m._require_register_or_camera_mode = lambda register, what: None
        m._camera_mode = lambda: contextlib.nullcontext()
        m.entered = {}
        m.enter = lambda cid, text: m.entered.__setitem__(cid, text)
        m.set_check = lambda cid, on: None
        m.click = lambda cid: clicks.append(cid)
        m._read_camera = lambda: dict(self.SHOWN)
        m._temp_path = lambda name: os.path.join(folder, name)
        m._drop_motion = lambda path: dropped.append(vmd.load(path))
        m.frame = lambda: 12
        m._project = lambda: {"camera": {"init": {"frame": 0, "interpolation": [20, 20, 107, 107] * 6, "distance": -45.0},
                                         "keys": list(keys)}}
        self.register_id = Ctl.CAMERA_REGISTER
        return m

    def test_without_a_curve_the_register_button_is_used(self):
        dropped, clicks = [], []
        result = self.make(dropped, clicks).set_camera(distance=30, register=True)
        self.assertEqual((clicks, dropped), ([self.register_id], []))
        self.assertNotIn("interp", result)

    def test_with_a_curve_a_one_key_camera_motion_is_dropped(self):
        dropped, clicks = [], []
        m = self.make(dropped, clicks)
        result = m.set_camera(distance=30, register=True, interp=(64, 0, 64, 127))
        self.assertEqual(clicks, [])
        self.assertEqual(len(dropped), 1)
        motion = dropped[0]
        self.assertTrue(motion.is_camera)
        self.assertEqual((len(motion.cameras), len(motion.lights)), (1, 0))
        key = motion.cameras[0]
        self.assertEqual((key.frame, key.distance, key.position, key.fov, key.perspective), (0, -30.0, (1.0, 12.0, -3.25), 45, True))
        for got, want in zip(key.rotation, (-math.radians(10), math.radians(20), math.radians(5))):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(key.interpolation, vmd.camera_interpolation((64, 0, 64, 127)))
        self.assertEqual(result["interp"], [64, 0, 64, 127])
        self.assertEqual(result["distance"], 30.0)

    def test_a_curve_needs_register(self):
        dropped, clicks = [], []
        with self.assertRaises(ValueError):
            self.make(dropped, clicks).set_camera(distance=30, interp=(64, 0, 64, 127))
        self.assertEqual((dropped, clicks), ([], []))

    def test_the_key_must_appear_in_the_project(self):
        dropped, clicks = [], []
        with self.assertRaises(app.MmdError) as ctx:
            self.make(dropped, clicks, keys=()).set_camera(distance=30, register=True, interp=(64, 0, 64, 127))
        self.assertIn("12", str(ctx.exception))


class FailureTest(unittest.TestCase):
    def test_value_errors_become_json_with_exit_code_2(self):
        # a value that cannot be used is a usage error (README: 2), like an argument argparse rejects
        payload, code = cli.failure(ValueError("frame must be 0 or more"))
        self.assertEqual(code, 2)
        self.assertEqual(payload, {"ok": False, "error": {"type": "ValueError",
                                                         "message": "frame must be 0 or more"}})

    def test_missing_files_name_the_path(self):
        payload, code = cli.failure(FileNotFoundError("C:/x/y.pmx"))
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["type"], "FileNotFoundError")
        self.assertIn("y.pmx", payload["error"]["message"])

    def test_a_pending_dialog_is_exit_code_3_and_lists_the_dialog(self):
        from mmd_cli import guard
        about = dialogs.Dialog(hwnd=7, cls="#32770", title="About", controls=[
            {"id": 2, "cls": "Button", "text": "OK", "hwnd": 8, "visible": True},
            {"id": 65535, "cls": "Static", "text": "MikuMikuDance Ver.9.32", "hwnd": 9, "visible": True}])
        payload, code = cli.failure(guard.DialogPending([about]))
        self.assertEqual(code, 3)
        self.assertEqual(payload["error"]["type"], "DialogPending")
        self.assertEqual(payload["error"]["dialogs"],
                         [{"hwnd": 7, "kind": "message", "title": "About",
                           "message": "MikuMikuDance Ver.9.32", "buttons": ["OK"]}])


if __name__ == "__main__":
    unittest.main()
