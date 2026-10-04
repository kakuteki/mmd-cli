import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from mmd_cli import cli, relay

try:
    from mmd_cli import win32
except ImportError:          # not on Windows
    win32 = None


SERVICE = dict(window_station="Service-0x0-3e7$", session_id=0)     # an SSH login, a service, a task without a desktop


class DecisionTest(unittest.TestCase):
    def test_interactive_desktop_runs_locally(self):
        self.assertFalse(relay.should_relay(window_station="WinSta0", session_id=1, argv=["state"], command="state"))

    def test_service_window_station_relays(self):
        self.assertTrue(relay.should_relay(argv=["state"], command="state", **SERVICE))

    def test_session_zero_relays_even_with_winsta0_name(self):
        self.assertTrue(relay.should_relay(window_station="WinSta0", session_id=0, argv=["state"], command="state"))

    def test_explicit_flags_win(self):
        self.assertTrue(relay.should_relay(window_station="WinSta0", session_id=1, argv=["--in-user-session", "state"],
                                           command="state"))
        self.assertFalse(relay.should_relay(argv=["--no-relay", "state"], command="state", **SERVICE))

    def test_commands_that_need_no_window_run_locally(self):
        self.assertFalse(relay.should_relay(argv=["file", "info", "a.pmm"], command="file", **SERVICE))
        self.assertFalse(relay.should_relay(argv=["--version"], command=None, **SERVICE))

    def test_should_relay_ignores_option_values_before_the_command(self):
        # the decision is made with the parsed command: "r.json" and "9" are option values, not the command
        for argv in (["--out", "r.json", "file", "info", "x.pmm"], ["--timeout", "9", "file", "info", "x.pmm"]):
            self.assertFalse(relay.should_relay(argv=argv, command="file", **SERVICE), argv)
        self.assertTrue(relay.should_relay(argv=["--out", "r.json", "state"], command="state", **SERVICE))


class MainDecisionTest(unittest.TestCase):
    """cli.main hands the parsed command to should_relay (the three argv shapes measured in review 1, 1.6)"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        mock.patch.object(relay, "window_station_name", return_value=SERVICE["window_station"]).start()
        mock.patch.object(relay, "current_session_id", return_value=0).start()
        self.handed = mock.patch.object(relay, "run_in_user_session",
                                        return_value=({"ok": True, "relayed": True}, 0)).start()
        self.addCleanup(mock.patch.stopall)

    def main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = cli.main(argv)
        return code, json.loads(stdout.getvalue())

    def test_file_info_runs_locally_whatever_options_come_first(self):
        pmm = os.path.join(os.path.dirname(__file__), "fixtures", "scene_v932.pmm")
        out = os.path.join(self.folder, "r.json")
        for argv in (["--out", out, "file", "info", pmm], ["--timeout", "9", "file", "info", pmm], ["file", "info", pmm]):
            code, payload = self.main(argv)
            self.assertEqual((code, payload["ok"]), (0, True), argv)
        self.assertFalse(self.handed.called)

    def test_a_command_that_needs_the_window_is_handed_over_as_is(self):
        code, payload = self.main(["--timeout", "9", "state"])
        self.assertEqual((code, payload["relayed"]), (0, True))
        self.assertEqual(self.handed.call_args, mock.call(["--timeout", "9", "state"]))     # no timeout of its own


class ParkedStdinTest(unittest.TestCase):
    """batch - parks stdin in a file for the child; the parent removes it afterwards, success or not"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.parked = os.path.join(self.folder, "relay", "stdin-%d.txt" % os.getpid())
        mock.patch.dict(os.environ, {"MMD_CLI_HOME": self.folder}).start()
        mock.patch.object(relay, "window_station_name", return_value=SERVICE["window_station"]).start()
        mock.patch.object(relay, "current_session_id", return_value=0).start()
        mock.patch.object(cli.sys, "stdin", io.StringIO("state\nframe get\n")).start()
        self.handed = mock.patch.object(relay, "run_in_user_session").start()
        self.addCleanup(mock.patch.stopall)

    def main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = cli.main(argv)
        return code, json.loads(stdout.getvalue())

    def test_the_child_gets_the_parked_file_and_the_parent_removes_it(self):
        seen = {}

        def handed(argv):
            seen["argv"] = argv
            with open(self.parked, encoding="utf-8") as f:
                seen["text"] = f.read()
            return {"ok": True, "relayed": True}, 0

        self.handed.side_effect = handed
        code, payload = self.main(["batch", "-", "--keep-going"])
        self.assertEqual((code, payload["ok"]), (0, True))
        self.assertEqual(seen["argv"], ["batch", self.parked, "--keep-going"])
        self.assertEqual(seen["text"], "state\nframe get\n")
        self.assertFalse(os.path.exists(self.parked))

    def test_the_parked_file_is_removed_when_the_relay_fails(self):
        self.handed.side_effect = relay.RelayError("nobody is logged on")
        code, payload = self.main(["batch", "-"])
        self.assertEqual((code, payload["error"]["type"]), (1, "RelayError"))
        self.assertFalse(os.path.exists(self.parked))


class ArgvTest(unittest.TestCase):
    def test_relay_flags_are_removed_and_out_is_redirected(self):
        argv = relay.child_argv(["--in-user-session", "--pid", "5", "--out", "C:/x/r.json", "model", "load", "a.pmx"],
                                out_path="C:/relay/1.json")
        self.assertEqual(argv, ["--no-relay", "--pid", "5", "--out", "C:/relay/1.json", "model", "load", "a.pmx"])

    def test_out_is_added_when_missing(self):
        argv = relay.child_argv(["state"], out_path="C:/relay/1.json")
        self.assertEqual(argv, ["--no-relay", "--out", "C:/relay/1.json", "state"])

    def test_child_argv_adds_no_relay(self):
        # the child must never hand the command on again, whatever window station it lands in
        for argv in (["state"], ["--no-relay", "state"], ["--in-user-session", "state"]):
            child = relay.child_argv(argv, out_path="o.json")
            self.assertEqual(child.count("--no-relay"), 1, argv)
            self.assertNotIn("--in-user-session", child)
            self.assertFalse(relay.should_relay(argv=child, command="state", **SERVICE))

    def test_child_argv_with_out_equals(self):
        self.assertEqual(relay.child_argv(["--out=C:/x/r.json", "state"], out_path="C:/relay/1.json"),
                         ["--no-relay", "--out=C:/relay/1.json", "state"])


class JobFileTest(unittest.TestCase):
    def test_roundtrip_keeps_non_ascii(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "job.json")
        job = relay.Job(argv=["bone", "set", "右腕", "--rot", "0", "0", "35"], out_path=os.path.join(folder, "r.json"),
                        cwd=folder, env={"MMD_CLI_HOME": "C:/h"})
        relay.write_job(job, path)
        back = relay.read_job(path)
        self.assertEqual(back.argv, job.argv)
        self.assertEqual(back.out_path, job.out_path)
        self.assertEqual(back.env, {"MMD_CLI_HOME": "C:/h"})
        with open(path, encoding="utf-8") as f:
            self.assertIn("右腕", f.read())


class TaskCommandTest(unittest.TestCase):
    def test_task_arguments_use_pythonw_and_the_job_file(self):
        interpreter = relay.windowless_interpreter(r"C:\Py\python.exe")
        self.assertEqual(interpreter, r"C:\Py\pythonw.exe")
        self.assertEqual(relay.task_arguments(r"C:\Users\k\AppData\Local\mmd-cli\relay\ab12.json"),
                         '-m mmd_cli --job "C:\\Users\\k\\AppData\\Local\\mmd-cli\\relay\\ab12.json"')

    def test_task_definition_runs_on_battery_in_the_interactive_session(self):
        # schtasks /Create alone makes a task that waits for AC power: unplugged, the notebook queued every
        # relay forever (2026-10-04).  The definition is written out in full instead
        xml = relay.task_xml(r"C:\Py\pythonw.exe", '-m mmd_cli --job "C:\\x\\a b.json" <&>')
        for piece in ("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
                      "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
                      "<LogonType>InteractiveToken</LogonType>",
                      "<RunLevel>LeastPrivilege</RunLevel>",
                      "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
                      "<Command>C:\\Py\\pythonw.exe</Command>",
                      '<Arguments>-m mmd_cli --job "C:\\x\\a b.json" &lt;&amp;&gt;</Arguments>'):
            self.assertIn(piece, xml)
        # the principal is the current user's SID: a DOMAIN\\name could not be mapped on hinata (2026-10-04)
        self.assertRegex(xml, r"<UserId>S-1-5-21-[0-9-]+</UserId>")
        self.assertNotIn("<Triggers>", xml)      # on demand only

    def test_create_task_registers_from_a_utf16_file_that_does_not_stay_behind(self):
        folder = tempfile.mkdtemp()
        seen = {}

        def scheduler(*args, timeout=60):
            seen["args"] = args
            with open(args[args.index("/XML") + 1], "rb") as f:
                seen["bytes"] = f.read()
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with mock.patch.dict(os.environ, {"MMD_CLI_HOME": folder}), mock.patch.object(relay, "_schtasks", scheduler):
            result = relay.create_task("mmd-cli\\relay-abc", r"C:\Py\pythonw.exe", "-m mmd_cli")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(seen["args"][:4], ("/Create", "/TN", "mmd-cli\\relay-abc", "/XML"))
        self.assertEqual(seen["args"][5], "/F")
        self.assertTrue(seen["bytes"].startswith(b"\xff\xfe"))                   # UTF-16 with a byte order mark
        self.assertIn("<Command>C:\\Py\\pythonw.exe</Command>", seen["bytes"].decode("utf-16"))
        self.assertEqual(os.listdir(os.path.join(folder, "relay")), [])        # the definition file is gone

    def test_task_name_is_unique_and_namespaced(self):
        a, b = relay.task_name(), relay.task_name()
        self.assertTrue(a.startswith("mmd-cli\\relay-"))
        self.assertNotEqual(a, b)


class ResultTest(unittest.TestCase):
    def test_result_of_a_finished_job(self):
        folder = tempfile.mkdtemp()
        out = os.path.join(folder, "r.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "frame": 3}, f)
        with open(out + ".exit", "w") as f:
            f.write("0")
        payload, code = relay.collect(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "frame": 3, "relayed": True})

    def test_missing_result_is_an_error(self):
        folder = tempfile.mkdtemp()
        payload, code = relay.collect(os.path.join(folder, "none.json"))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_collect_waits_for_a_complete_exit_file(self):
        # an .exit that exists but is still empty must never read as exit code 0
        folder = tempfile.mkdtemp()
        out = os.path.join(folder, "r.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"ok": False}, f)
        with open(out + ".exit", "w"):
            pass
        payload, code = relay.collect(out)
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])

    def test_collect_reads_again_when_the_exit_file_fills_up_late(self):
        folder = tempfile.mkdtemp()
        out = os.path.join(folder, "r.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"ok": False}, f)
        with open(out + ".exit", "w"):
            pass

        def fill():
            with open(out + ".exit", "w") as f:
                f.write("3")

        threading.Timer(0.15, fill).start()
        payload, code = relay.collect(out)
        self.assertEqual(code, 3)
        self.assertEqual(payload, {"ok": False, "relayed": True})


class RunJobTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.out = os.path.join(self.folder, "r.out.json")
        self.job_path = os.path.join(self.folder, "j.json")
        relay.write_job(relay.Job(argv=["--out", self.out, "state"], out_path=self.out), self.job_path)

    def main_writing(self, code):
        def main(argv):
            with open(self.out, "w", encoding="utf-8") as f:
                json.dump({"ok": code == 0}, f)
            return code
        return main

    def test_run_job_writes_exit_atomically(self):
        # the parent reads .exit as soon as it exists: it must appear complete (written to .part, then moved)
        with mock.patch.object(relay.os, "replace", wraps=os.replace) as replace:
            code = relay.run_job(self.job_path, self.main_writing(3))
        self.assertEqual(code, 3)
        with open(self.out + ".exit") as f:
            self.assertEqual(f.read(), "3")
        self.assertIn((self.out + ".exit.part", self.out + ".exit"), [c.args for c in replace.call_args_list])
        self.assertFalse(os.path.exists(self.out + ".exit.part"))

    def test_run_job_leaves_nothing_when_the_parent_gave_up(self):
        # the parent takes the job file away when it stops waiting: a result written after that is litter
        def main(argv):
            os.remove(self.job_path)
            with open(self.out, "w", encoding="utf-8") as f:
                json.dump({"ok": True}, f)
            return 0

        self.assertEqual(relay.run_job(self.job_path, main), 0)
        self.assertFalse(os.path.exists(self.out + ".exit"))
        self.assertFalse(os.path.exists(self.out))

    def test_run_job_writes_no_error_file_either_when_the_parent_gave_up(self):
        def main(argv):
            os.remove(self.job_path)
            raise RuntimeError("late")

        self.assertEqual(relay.run_job(self.job_path, main), 1)
        self.assertFalse(os.path.exists(self.out + ".exit"))
        self.assertFalse(os.path.exists(self.out))

    def test_run_job_writes_the_started_marker_atomically_with_its_pid(self):
        # the parent reads the pid out of .started as soon as it exists
        with mock.patch.object(relay.os, "replace", wraps=os.replace) as replace:
            relay.run_job(self.job_path, self.main_writing(0))
        with open(self.out + ".started") as f:
            self.assertEqual(f.read(), str(os.getpid()))
        self.assertIn((self.out + ".started.part", self.out + ".started"), [c.args for c in replace.call_args_list])


class FakeScheduler:
    """stands in for schtasks: records every call and plays the child when the task is run"""

    def __init__(self, child=None):
        self.calls = []
        self.child = child
        self.job_path = None

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        if args[0] == "/Create":
            from xml.etree import ElementTree
            with open(args[args.index("/XML") + 1], "rb") as f:
                root = ElementTree.fromstring(f.read())
            arguments = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Arguments").text
            self.job_path = arguments.split('"')[1]
        if args[0] == "/Run" and self.child is not None:
            self.child(relay.read_job(self.job_path))
        return subprocess.CompletedProcess(["schtasks.exe"] + list(args), 0, b"", b"")

    def verbs(self):
        return [c[0] for c in self.calls]


class FakeClock:
    """replaces relay.time: sleep advances a virtual clock and runs what was scheduled on it"""

    def __init__(self):
        self.now = 0.0
        self.due = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        for when, callback in list(self.due):
            if when <= self.now:
                self.due.remove((when, callback))
                callback()

    def at(self, when, callback):
        self.due.append((when, callback))


def finish(job, code=0):
    with open(job.out_path, "w", encoding="utf-8") as f:
        json.dump({"ok": code == 0}, f)
    relay._write_whole(job.out_path + ".exit", str(code))


def start(job, pid=4242):
    relay._write_whole(job.out_path + ".started", str(pid))


@unittest.skipUnless(win32 is not None, "needs Windows")
class ParentWaitTest(unittest.TestCase):
    """run_in_user_session without a scheduler, a child process or real time"""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.clock = FakeClock()
        mock.patch.dict(os.environ, {"MMD_CLI_HOME": self.folder}).start()
        mock.patch.object(relay, "time", self.clock).start()
        self.addCleanup(mock.patch.stopall)

    def run_with(self, scheduler, alive, **kwargs):
        with mock.patch.object(relay, "_schtasks", scheduler), \
                mock.patch.object(win32, "process_alive", side_effect=alive):
            return relay.run_in_user_session(["state"], **kwargs)

    def leftovers(self):
        return sorted(os.listdir(os.path.join(self.folder, "relay")))

    def test_parent_waits_as_long_as_the_child_lives(self):
        # an AVI of 300 frames keeps the child busy for minutes; the parent has no clock of its own
        def child(job):
            start(job)
            self.clock.at(400.0, lambda: finish(job))

        scheduler = FakeScheduler(child)
        payload, code = self.run_with(scheduler, alive=lambda pid: True)
        self.assertEqual((payload, code), ({"ok": True, "relayed": True}, 0))
        self.assertGreaterEqual(self.clock.now, 400.0)
        self.assertNotIn("/End", scheduler.verbs())
        self.assertEqual(scheduler.verbs()[-1], "/Delete")
        self.assertEqual(self.leftovers(), [])

    def test_parent_gives_up_when_the_child_died_without_a_result(self):
        scheduler = FakeScheduler(start)
        seen = []
        with self.assertRaises(relay.RelayError) as ctx:
            self.run_with(scheduler, alive=lambda pid: seen.append(pid) or False)
        self.assertIn("4242", str(ctx.exception))
        self.assertEqual(seen[0], 4242)
        self.assertGreaterEqual(self.clock.now, 2.0)        # the grace for a late .exit
        self.assertLess(self.clock.now, 10.0)
        self.assertEqual(scheduler.verbs()[-2:], ["/End", "/Delete"])
        self.assertEqual(self.leftovers(), [])

    def test_a_keyboard_interrupt_leaves_the_child_to_finish_on_its_own(self):
        # review 2 (7.1): /End killed the child in the middle of writing a file or holding a dialog open.
        # Interrupted, the parent walks away; the child finishes and, finding no job file, leaves nothing behind
        scheduler = FakeScheduler(start)

        def alive(pid):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.run_with(scheduler, alive=alive)
        self.assertNotIn("/End", scheduler.verbs())
        self.assertEqual(scheduler.verbs()[-1], "/Delete")
        self.assertEqual(self.leftovers(), [])

    def test_parent_reports_no_logon_when_the_child_never_starts(self):
        scheduler = FakeScheduler()
        with self.assertRaises(relay.RelayError) as ctx:
            self.run_with(scheduler, alive=lambda pid: self.fail("nothing to ask about"))
        self.assertIn("logged on", str(ctx.exception))
        self.assertGreaterEqual(self.clock.now, 15.0)
        self.assertEqual(scheduler.verbs()[-2:], ["/End", "/Delete"])
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
