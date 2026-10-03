import json
import os
import tempfile
import unittest

from mmd_cli import relay


class DecisionTest(unittest.TestCase):
    def test_interactive_desktop_runs_locally(self):
        self.assertFalse(relay.should_relay(window_station="WinSta0", session_id=1, argv=["state"]))

    def test_service_window_station_relays(self):
        # what an SSH login, a service or a scheduled task without a desktop sees
        self.assertTrue(relay.should_relay(window_station="Service-0x0-3e7$", session_id=0, argv=["state"]))

    def test_session_zero_relays_even_with_winsta0_name(self):
        self.assertTrue(relay.should_relay(window_station="WinSta0", session_id=0, argv=["state"]))

    def test_explicit_flags_win(self):
        self.assertTrue(relay.should_relay(window_station="WinSta0", session_id=1, argv=["--in-user-session", "state"]))
        self.assertFalse(relay.should_relay(window_station="Service-0x0-3e7$", session_id=0, argv=["--no-relay", "state"]))

    def test_commands_that_need_no_window_run_locally(self):
        self.assertFalse(relay.should_relay(window_station="Service-0x0-3e7$", session_id=0, argv=["file", "info", "a.pmm"]))
        self.assertFalse(relay.should_relay(window_station="Service-0x0-3e7$", session_id=0, argv=["--version"]))


class ArgvTest(unittest.TestCase):
    def test_relay_flags_are_removed_and_out_is_redirected(self):
        argv = relay.child_argv(["--in-user-session", "--pid", "5", "--out", "C:/x/r.json", "model", "load", "a.pmx"],
                                out_path="C:/relay/1.json")
        self.assertEqual(argv, ["--pid", "5", "--out", "C:/relay/1.json", "model", "load", "a.pmx"])

    def test_out_is_added_when_missing(self):
        argv = relay.child_argv(["state"], out_path="C:/relay/1.json")
        self.assertEqual(argv, ["--out", "C:/relay/1.json", "state"])

    def test_no_relay_flag_is_removed_too(self):
        self.assertEqual(relay.child_argv(["--no-relay", "state"], out_path="o.json"), ["--out", "o.json", "state"])


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
    def test_task_command_uses_pythonw_and_the_job_file(self):
        interpreter = relay.windowless_interpreter(r"C:\Py\python.exe")
        self.assertEqual(interpreter, r"C:\Py\pythonw.exe")
        cmd = relay.task_command(interpreter, r"C:\Users\k\AppData\Local\mmd-cli\relay\ab12.json")
        self.assertTrue(cmd.startswith('"C:\\Py\\pythonw.exe" -m mmd_cli --job "'))
        self.assertTrue(cmd.endswith('ab12.json"'))
        self.assertLess(len(cmd), 261)      # the limit of schtasks /TR

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


if __name__ == "__main__":
    unittest.main()
