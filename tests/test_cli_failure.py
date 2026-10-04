"""what a failed command reports, and what a launch reports, without MMD"""
import contextlib
import sys
import types
import unittest
from unittest import mock

from mmd_cli import cli, dialogs
from tests.test_cli import parse

try:
    from mmd_cli import app, guard
except ImportError:          # not on Windows
    app = None


@unittest.skipUnless(app is not None, "needs Windows")
class FailureReportTest(unittest.TestCase):
    def test_dialogs_answered_before_a_failure_are_reported(self):
        exc = app.MmdError("boom")
        exc.answered_dialogs = [{"kind": "message", "action": "ok"}]
        payload, code = cli.failure(exc)
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["answered_dialogs"], [{"kind": "message", "action": "ok"}])

    def test_a_pending_dialog_report_includes_what_was_answered_before_it(self):
        d = dialogs.Dialog(5, "#32770", "何か", [{"id": 1, "cls": "Button", "text": "OK", "hwnd": 51, "visible": True}])
        exc = guard.DialogPending([d], events=[{"kind": "model_info", "action": "ok"},
                                               dict(d.to_json(), action="left open")])
        payload, code = cli.failure(exc)
        self.assertEqual(code, 3)
        self.assertEqual(payload["error"]["answered_dialogs"], [{"kind": "model_info", "action": "ok"}])
        self.assertEqual([x["title"] for x in payload["error"]["dialogs"]], ["何か"])

    def test_a_bad_value_is_a_usage_error(self):
        # review 1 (4.4): README promises exit code 2 for an argument that is wrong; frame set -1 raised ValueError -> 1
        payload, code = cli.failure(ValueError("need 0 <= start <= end"))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["type"], "ValueError")
        payload, code = cli.failure(app.MmdError("select a model first"))
        self.assertEqual(code, 1)

    def test_what_a_failed_operation_wrote_is_pointed_at(self):
        exc = app.MmdError("boom")
        exc.kept_output = "C:/x/clip.avi.mmdcli-failed"
        payload, code = cli.failure(exc)
        self.assertEqual(payload["error"]["kept_output"], "C:/x/clip.avi.mmdcli-failed")

    def test_run_attaches_the_answered_dialogs_to_the_failure(self):
        shield = types.SimpleNamespace(events=[])

        class FakeMmd:
            def shield(self):
                return contextlib.nullcontext(shield)

            def take_events(self):
                return [{"kind": "message", "action": "ok"}]

            def state(self):
                raise app.MmdError("boom")

        with mock.patch.object(cli, "_attach", return_value=FakeMmd()):
            with self.assertRaises(app.MmdError) as ctx:
                cli.run(parse(["state"]))
        self.assertEqual(ctx.exception.answered_dialogs, [{"kind": "message", "action": "ok"}])


@unittest.skipUnless(app is not None, "needs Windows")
class LaunchResultTest(unittest.TestCase):
    def test_foreground_events_are_copied_into_the_result(self):
        shields = []

        class FakeShield:
            def __init__(self, pid=None):
                self.pid = pid
                self.events = [{"foreground_taken_by": "x"}]
                shields.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        fake = types.SimpleNamespace(pid=5, state=lambda: {"pid": 5})
        with mock.patch.object(guard, "FocusShield", FakeShield), mock.patch.object(app, "launch", return_value=fake):
            result = cli.dispatch_any(None, parse(["launch", "--exe", sys.executable]))
        self.assertEqual(result["foreground_restored"], [{"foreground_taken_by": "x"}])
        self.assertIsNot(result["foreground_restored"], shields[0].events)
        self.assertIs(result["_instance"], fake)


if __name__ == "__main__":
    unittest.main()
