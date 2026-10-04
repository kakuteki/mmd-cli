import unittest

from mmd_cli import batch, cli


class ParseLinesTest(unittest.TestCase):
    def test_blank_lines_and_comments_are_skipped(self):
        entries = batch.parse_lines("\n# a comment\n   \nframe set 3\n")
        self.assertEqual([(e["line"], e["argv"]) for e in entries], [(4, ["frame", "set", "3"])])

    def test_json_array_and_object_lines(self):
        entries = batch.parse_lines('["bone", "set", "右腕", "--rot", "0", "0", "35"]\n{"id": "wink", "args": ["morph", "set", "ウィンク", "1"]}\n')
        self.assertEqual(entries[0]["argv"], ["bone", "set", "右腕", "--rot", "0", "0", "35"])
        self.assertIsNone(entries[0].get("id"))
        self.assertEqual(entries[1]["argv"], ["morph", "set", "ウィンク", "1"])
        self.assertEqual(entries[1]["id"], "wink")

    def test_plain_lines_keep_quoted_paths_and_backslashes(self):
        entries = batch.parse_lines(r'model load "C:\MMD\UserFile\Model\初音ミク.pmd"' + "\n")
        self.assertEqual(entries[0]["argv"], ["model", "load", r"C:\MMD\UserFile\Model\初音ミク.pmd"])

    def test_a_leading_mmd_word_is_tolerated(self):
        self.assertEqual(batch.parse_lines("mmd frame get\n")[0]["argv"], ["frame", "get"])

    def test_broken_json_line_is_an_error_with_the_line_number(self):
        with self.assertRaises(batch.BatchSyntaxError) as ctx:
            batch.parse_lines('frame get\n["unterminated\n')
        self.assertIn("line 2", str(ctx.exception))

    def test_global_options_are_not_allowed_per_line(self):
        with self.assertRaises(batch.BatchSyntaxError) as ctx:
            batch.parse_lines("--pid 5 state\n")
        self.assertIn("--pid", str(ctx.exception))


class FakeMmd:
    def __init__(self):
        self.pid = 42
        self.events = []
        self.calls = []

    def take_events(self):
        events, self.events = self.events, []
        return events


class RunBatchTest(unittest.TestCase):
    def setUp(self):
        self.mmd = FakeMmd()
        self.parser = cli.build_parser()

    def dispatch(self, mmd, args):
        mmd.calls.append((args.command, getattr(args, "action", None)))
        if args.command == "frame" and args.action == "set" and args.number == 99:
            raise ValueError("no frame 99")
        if args.command == "model" and args.action == "load":
            mmd.events.append({"kind": "model_info", "action": "ok"})
            return {"name": "miku"}
        return {"frame": 1}

    def run_text(self, text, **kw):
        entries = batch.parse_lines(text)
        return batch.run_batch(entries, lambda: self.mmd, self.dispatch, self.parser, **kw)

    def test_results_follow_the_lines_and_carry_dialog_events(self):
        results, code = self.run_text("model load a.pmx\nframe get\n")
        self.assertEqual(code, 0)
        self.assertEqual([r["ok"] for r in results], [True, True])
        self.assertEqual(results[0]["name"], "miku")
        self.assertEqual(results[0]["answered_dialogs"], [{"kind": "model_info", "action": "ok"}])
        self.assertEqual(results[0]["line"], 1)
        self.assertEqual(results[1]["argv"], ["frame", "get"])
        self.assertEqual(self.mmd.calls, [("model", "load"), ("frame", "get")])

    def test_stops_at_the_first_failure_by_default(self):
        results, code = self.run_text("frame get\nframe set 99\nframe get\n")
        self.assertEqual(code, 1)
        self.assertEqual([r["ok"] for r in results], [True, False])
        self.assertEqual(results[1]["error"]["type"], "ValueError")
        self.assertEqual(len(self.mmd.calls), 2)

    def test_keep_going_runs_everything_and_still_reports_failure(self):
        results, code = self.run_text("frame get\nframe set 99\nframe get\n", stop_on_error=False)
        self.assertEqual(code, 1)
        self.assertEqual([r["ok"] for r in results], [True, False, True])

    def test_usage_errors_in_a_line_are_reported_not_raised(self):
        results, code = self.run_text("frame set notanumber\n")
        self.assertEqual(code, 2)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["error"]["type"], "UsageError")

    def test_the_instance_is_only_attached_when_a_line_needs_it(self):
        made = []

        def make():
            made.append(1)
            return self.mmd
        entries = batch.parse_lines("file info x.pmm\n")
        batch.run_batch(entries, make, lambda mmd, args: {"ok": True, "local": mmd is None}, self.parser)
        self.assertEqual(made, [])

    def test_launch_line_provides_the_instance_for_later_lines(self):
        seen = []

        def dispatch(mmd, args):
            seen.append(mmd)
            if args.command == "launch":
                return {"state": "launched", "_instance": self.mmd}
            return {"frame": 0}
        entries = batch.parse_lines("launch --exe x.exe\nframe get\n")
        results, code = batch.run_batch(entries, lambda: None, dispatch, self.parser)
        self.assertEqual(code, 0)
        self.assertIs(seen[1], self.mmd)
        self.assertNotIn("_instance", results[0])

    def test_summary(self):
        results, code = self.run_text("frame get\nframe set 99\n", stop_on_error=False)
        s = batch.summary(results, code)
        self.assertEqual((s["ok"], s["ran"], s["failed"], s["exit_code"]), (False, 2, 1, 1))
        self.assertEqual(s["results"], results)


if __name__ == "__main__":
    unittest.main()
