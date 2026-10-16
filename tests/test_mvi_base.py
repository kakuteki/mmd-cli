"""tools/mvi/base.py and report.py: the judgement against people and the rules (the human baseline's p31 rule), the
comparison of two versions, the places and which of them the timeline lists, the outputs."""
import json
import os
import shutil
import tempfile
import unittest

from tests import mvi_fixtures  # noqa: F401  (puts tools/ on the path)
from mvi import base, report

PEOPLE = {"kind": "people", "q1": 1.0, "q3": 3.0, "median": 2.0, "p10": 0.5, "p90": 4.0}


def text(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


class JudgeTest(unittest.TestCase):
    def test_inside_the_quartiles_is_the_middle(self):
        for v in (1.0, 2.0, 3.0):
            self.assertEqual(base.judge(PEOPLE, v)["side"], 0)
            self.assertEqual(base.judge(PEOPLE, v)["word"], "中")

    def test_outside_counts_the_scales_past_the_quartile(self):
        # scale = max(IQR 2, (p90 - p10) / 2 = 1.75) = 2
        j = base.judge(PEOPLE, 5.0)
        self.assertEqual((j["side"], j["dist"], j["word"]), (1, 1.0, "上へ外"))
        j = base.judge(PEOPLE, 0.0)
        self.assertEqual((j["side"], j["dist"], j["word"]), (-1, 0.5, "下へ外"))

    def test_a_wide_tail_widens_the_scale(self):
        ref = dict(PEOPLE, p10=-5.0, p90=9.0)                   # (p90 - p10) / 2 = 7
        self.assertEqual(base.judge(ref, 10.0)["dist"], 1.0)

    def test_one_frame_or_event_of_the_mv_is_inside_people_who_never_do_it(self):
        ref = {"kind": "people", "q1": 0.0, "q3": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
        res = base.resolution("%")                              # one frame of 246 s, in %
        self.assertEqual(base.judge(ref, 0.9 * res, "%")["side"], 0)
        self.assertEqual(base.judge(ref, 2.0 * res, "%")["side"], 1)
        self.assertEqual(base.judge(ref, 0.5 * base.resolution("/min"), "/min")["side"], 0)

    def test_a_limit_breaks_past_its_bound_in_its_scale(self):
        ref = {"kind": "limit", "max": 0, "scale": 1.0}
        self.assertEqual(base.judge(ref, 0)["side"], 0)
        self.assertEqual(base.judge(ref, 3)["dist"], 3.0)
        low = {"kind": "limit", "min": 10.0, "scale": 5.0}
        self.assertEqual(base.judge(low, 0.0)["side"], -1)
        self.assertEqual(base.judge(low, 0.0)["dist"], 2.0)

    def test_a_window_holds_both_sides(self):
        ref = {"kind": "window", "lo": -45.0, "hi": 125.0, "scale": 50.0}
        self.assertEqual(base.judge(ref, 92.0)["side"], 0)
        self.assertEqual(base.judge(ref, 150.0)["dist"], 0.5)
        self.assertEqual(base.judge(ref, -95.0)["side"], -1)

    def test_nothing_is_judged_without_a_value_or_against_an_info(self):
        self.assertIsNone(base.judge(PEOPLE, None))
        self.assertIsNone(base.judge(PEOPLE, float("nan")))
        self.assertIsNone(base.judge({"kind": "info"}, 3.0))
        self.assertIsNone(base.judge(None, 3.0))


class CompareTest(unittest.TestCase):
    def word(self, a, b, ref=PEOPLE):
        return base.compare(ref, a, b)["word"]

    def test_the_words(self):
        self.assertEqual(self.word(5.0, 2.5), "入った")
        self.assertEqual(self.word(2.0, 2.5), "中のまま")
        self.assertEqual(self.word(7.0, 5.0), "近づいた")
        self.assertEqual(self.word(5.0, 7.0), "遠ざかった")
        self.assertEqual(self.word(2.0, 6.0), "遠ざかった")
        self.assertEqual(self.word(5.0, -1.0), "直しすぎ")
        self.assertEqual(self.word(5.0, 5.05), "変わらず")

    def test_a_rule_compares_the_distance_past_it(self):
        ref = {"kind": "limit", "max": 0, "scale": 1.0}
        self.assertEqual(self.word(9, 0, ref), "入った")
        self.assertEqual(self.word(9, 3, ref), "近づいた")

    def test_no_comparison_without_both_values(self):
        self.assertIsNone(base.compare(PEOPLE, None, 2.0))
        self.assertIsNone(base.compare({"kind": "info"}, 1.0, 2.0))


class EventTest(unittest.TestCase):
    def test_severity_counts_the_scales_past_the_edge(self):
        e = base.event("feet.knee_gain_deg", 30, 36, 50.0, "度", 20.0, 10.0, "x")
        self.assertEqual(e["severity"], 3.0)
        self.assertEqual((e["t0"], e["t1"]), (1.0, 1.23))
        e = base.event("upper.head_stop_ms", 0, 0, 20.0, "ms", 37.0, 17.0, side=-1)
        self.assertEqual(e["severity"], 1.0)
        self.assertEqual(e["side"], -1)

    def test_a_place_on_the_good_side_of_its_edge_has_no_severity(self):
        self.assertEqual(base.event("x.y", 0, 0, 10.0, "", 20.0, 1.0)["severity"], 0.0)

    def test_runs(self):
        self.assertEqual(base.runs([0, 1, 1, 0, 1, 0, 1, 1, 1]), [(1, 2), (4, 4), (6, 8)])
        self.assertEqual(base.runs([0, 1, 1, 0, 1, 1, 1], 3), [(4, 6)])

    def test_the_event_rule_is_people_pooled_places(self):
        edge, scale = base.event_rule("feet.knee_gain_deg", 1.0, 1.0)
        ev = base.reference("feet.knee_gain_deg")["event"]
        self.assertEqual((edge, scale), (ev["edge"], ev["scale"]))
        self.assertGreater(edge, base.reference("feet.knee_gain_deg")["q3"])      # people's places spread wider
        self.assertEqual(base.event_rule("no.such", 2.0, 3.0), (2.0, 3.0))


class HumanJsonTest(unittest.TestCase):
    def test_only_aggregates_and_rules(self):
        h = base.human()
        for mid, ref in h.items():
            if mid.startswith("_"):
                continue
            self.assertIn(ref["kind"], ("people", "limit", "window", "info"), mid)
            self.assertIn("source", ref, mid)
            if ref["kind"] == "people":
                self.assertTrue(ref["p10"] <= ref["q1"] <= ref["median"] <= ref["q3"] <= ref["p90"], mid)
                self.assertGreaterEqual(ref["n"], 5, mid)
                allowed = {"kind", "group", "source", "n", "p10", "q1", "median", "q3", "p90", "event"}
                self.assertFalse(set(ref) - allowed, mid)


def rep(measures, events, label="A"):
    r = {"label": label, "made": "now", "frames": 300, "first": 0, "last": 299, "measures": measures, "events": events,
         "failed": {}, "series": {}}
    return report.mark_listed(r)


def mrow(mid, value, ref):
    return {"id": mid, "concept": mid.split(".")[0], "name": mid, "value": value, "unit": "", "from": "test", "ref": ref,
            "judge": base.judge(ref, value)}


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_which_places_are_listed(self):
        limit = {"kind": "limit", "max": 0, "scale": 1.0}
        window = {"kind": "window", "lo": -45.0, "hi": 125.0, "scale": 50.0}
        r = rep([mrow("gravity.out_up", 5.0, PEOPLE), mrow("gravity.inside", 2.0, PEOPLE), mrow("skirt.rule", 2, limit),
                 mrow("mouth.win", 50.0, window), mrow("mouth.info", 3.0, {"kind": "info"})],
                [base.event("gravity.out_up", 10, 12, 9.0, "", 4.0, 1.0),               # same side as the measure
                 base.event("gravity.out_up", 20, 22, 0.0, "", 1.0, 1.0, side=-1),      # the other side
                 base.event("gravity.inside", 30, 31, 9.0, "", 4.0, 1.0),               # the measure is inside people
                 base.event("skirt.rule", 40, 40, 130.0, "", 122.0, 12.2),
                 base.event("mouth.win", 50, 50, 150.0, "", 125.0, 50.0),               # outside the window itself
                 base.event("mouth.win", 60, 60, 100.0, "", 125.0, 50.0),               # inside the window
                 base.event("mouth.info", 70, 70, 9.0, "", 1.0, 1.0)])
        listed = [(e["id"], e["first"]) for e in report.timeline(r)]
        self.assertEqual(sorted(listed), sorted([("gravity.out_up", 10), ("skirt.rule", 40), ("mouth.win", 50)]))

    def test_the_timeline_is_heaviest_first_then_earliest(self):
        limit = {"kind": "limit", "max": 0, "scale": 1.0}
        r = rep([mrow("skirt.rule", 3, limit)],
                [base.event("skirt.rule", 50, 50, 3.0, "", 0.0, 1.0), base.event("skirt.rule", 10, 10, 1.0, "", 0.0, 1.0),
                 base.event("skirt.rule", 5, 5, 3.0, "", 0.0, 1.0)])
        self.assertEqual([e["first"] for e in report.timeline(r)], [5, 50, 10])

    def test_compare_finds_the_new_and_the_gone_places(self):
        limit = {"kind": "limit", "max": 0, "scale": 1.0}
        a = rep([mrow("skirt.rule", 2, limit)], [base.event("skirt.rule", 10, 12, 1.0, "", 0.0, 1.0),
                                                 base.event("skirt.rule", 100, 101, 1.0, "", 0.0, 1.0)], "A")
        b = rep([mrow("skirt.rule", 2, limit)], [base.event("skirt.rule", 11, 11, 1.0, "", 0.0, 1.0),
                                                 base.event("skirt.rule", 200, 205, 1.0, "", 0.0, 1.0)], "B")
        c = report.compare(a, b)
        self.assertEqual([e["first"] for e in c["new"]], [200])
        self.assertEqual([e["first"] for e in c["gone"]], [100])
        self.assertEqual(c["rows"][0]["word"]["word"], "変わらず")

    def test_the_files(self):
        limit = {"kind": "limit", "max": 0, "scale": 1.0}
        r = rep([mrow("skirt.rule", 1, limit), mrow("gravity.inside", 2.0, PEOPLE)],
                [base.event("skirt.rule", 10, 12, 130.0, "u/s²", 122.0, 12.2, "床で 130")])
        paths = report.write(r, self.folder)
        for name in ("report.json", "report.md", "outliers.md", "outliers.csv", "events.csv"):
            self.assertTrue(os.path.isfile(paths[name]), name)
        md = text(paths["report.md"])
        self.assertIn("スカートの危なさ", md)
        self.assertIn("上へ外", md)
        csv_lines = text(paths["outliers.csv"], "utf-8-sig").strip().splitlines()
        self.assertEqual(len(csv_lines), 2)
        self.assertIn("床で 130", csv_lines[1])
        back = report.load(self.folder)
        self.assertEqual(back["measures"][0]["value"], 1)
        c = report.compare(back, back)
        out = report.write_compare(c, self.folder)
        self.assertIn("中のまま", text(out["compare.md"]))
        self.assertEqual(json.loads(text(out["compare.json"]))["new"], [])


if __name__ == "__main__":
    unittest.main()
