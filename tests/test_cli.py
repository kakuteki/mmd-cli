import contextlib
import io
import json
import os
import tempfile
import unittest

from mmd_cli import cli, dialogs


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
