import contextlib
import io
import json
import os
import tempfile
import unittest

from mmd_cli import cli, dialogs

try:
    from mmd_cli import app
except ImportError:          # not on Windows
    app = None

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


class FailureTest(unittest.TestCase):
    def test_value_errors_become_json_with_exit_code_1(self):
        payload, code = cli.failure(ValueError("frame must be 0 or more"))
        self.assertEqual(code, 1)
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
