"""tools/mv_inspect.py: the command end to end on a synthetic body (tests.mvi_fixtures.full_body_bytes: Sour's Rin's
rest skeleton with the leg rig and shoes) -- measure, outliers, compare, timeline, mark -- and on the MV itself: v9's
numbers against the numbers the earlier work reported for v9 (the human baseline's v9 table, balance-v3, floaty,
wbbalance, review_wbbalance, the fingers, the gaze report, the lipsync review).  The MV's inputs come from BALANCE_SONG
(tests/test_balance_layer.py: its "dance" is v9's spine_h.vmd in C:/work/hibikase/v9/build; v9's render inputs are
read beside it) and the song's voice and lines from MMD_CLI_DATA; without them those tests skip, with the reason."""
import contextlib
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from tests import mvi_fixtures as MF

import mv_inspect  # noqa: E402  (tools/ is on the path: tests.mvi_fixtures)

from mmd_cli.formats import vmd  # noqa: E402

F = 240


def text(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


def run(*argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mv_inspect.main([str(a) for a in argv])
    lines = out.getvalue().strip().splitlines()
    return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{") else out.getvalue())


def drop(t):
    """センター dropping 6 cm with 240 units/s^2 over 4 frames from frame 120 (the feet on the floor)"""
    k = min(max(t - 120, 0), 4)
    return (0.0, -0.5 * 240.0 * (k / 30.0) ** 2 if k < 4 else -0.5 * 240.0 * (4 / 30.0) ** 2, 0.0)


class SyntheticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.model = os.path.join(cls.folder, "rin-body.pmx")
        with open(cls.model, "wb") as f:
            f.write(MF.full_body_bytes())
        cls.smooth = os.path.join(cls.folder, "smooth.vmd")
        cls.dropping = os.path.join(cls.folder, "drop.vmd")
        vmd.dump(MF.dance(F), cls.smooth)
        vmd.dump(MF.dance(F, centre=drop), cls.dropping)
        cls.camera = MF.front_camera(os.path.join(cls.folder, "cam.vmd"), y=10.0, distance=45.0)
        cls.out_a = os.path.join(cls.folder, "A")
        cls.out_b = os.path.join(cls.folder, "B")
        cls.code_a, cls.res_a = run("measure", "--model", cls.model, "--motions", cls.dropping, "--label", "drop",
                                    "--camera", cls.camera, "--out", cls.out_a)
        cls.code_b, cls.res_b = run("measure", "--model", cls.model, "--motions", cls.smooth, "--label", "smooth",
                                    "--out", cls.out_b, "--no-figure")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def report(self, out):
        with open(os.path.join(out, "report.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_every_part_measures_and_the_files_are_written(self):
        self.assertEqual(self.code_a, 0, self.res_a)
        self.assertEqual(self.res_a["failed"], [])
        rep = self.report(self.out_a)
        for c, _ in MF.base.CONCEPTS[:-1]:
            self.assertTrue(any(r["concept"] == c for r in rep["measures"]), c)
        for name in ("report.json", "report.md", "outliers.md", "outliers.csv", "events.csv", "series.npz", "marks.npz",
                     "timeline.png"):
            self.assertTrue(os.path.isfile(os.path.join(self.out_a, name)), name)
        self.assertFalse(os.path.isfile(os.path.join(self.out_b, "timeline.png")))
        self.assertTrue(os.path.isdir(os.path.join(self.out_a, "cache")))

    def test_the_drop_on_the_floor_is_a_skirt_place_and_the_smooth_dance_has_none(self):
        a = {r["id"]: r for r in self.report(self.out_a)["measures"]}
        b = {r["id"]: r for r in self.report(self.out_b)["measures"]}
        self.assertGreater(a["skirt.floor_over122_frames"]["value"], 0)
        self.assertEqual(a["skirt.floor_over122_frames"]["judge"]["word"], "上へ外")
        self.assertEqual(b["skirt.floor_over122_frames"]["value"], 0)
        places = [e for e in self.report(self.out_a)["events"] if e["listed"] and e["id"] == "skirt.floor_over122_frames"]
        self.assertTrue(places and all(118 <= e["first"] <= 126 for e in places))

    def test_the_cache_gives_the_same_report(self):
        code, res = run("measure", "--model", self.model, "--motions", self.dropping, "--label", "drop", "--out",
                        os.path.join(self.folder, "A2"), "--cache", os.path.join(self.out_a, "cache"), "--no-figure",
                        "--parts", "skirt,spikes")
        self.assertEqual(code, 0)
        a = {r["id"]: r["value"] for r in self.report(self.out_a)["measures"] if r["concept"] in ("skirt", "spikes")}
        a2 = {r["id"]: r["value"] for r in self.report(os.path.join(self.folder, "A2"))["measures"]}
        self.assertEqual(a, a2)

    def test_compare_lists_the_place_gone_in_the_smooth_dance(self):
        out = os.path.join(self.folder, "cmp")
        code, res = run("compare", self.out_a, self.out_b, "--out", out)
        self.assertEqual(code, 0)
        c = json.loads(text(os.path.join(out, "compare.json")))
        row = [r for r in c["rows"] if r["id"] == "skirt.floor_over122_frames"][0]
        self.assertEqual(row["word"]["word"], "入った")
        self.assertTrue(any(e["id"] == "skirt.floor_over122_frames" for e in c["gone"]))
        self.assertIn("入った", text(os.path.join(out, "compare.md")))

    def test_outliers_and_timeline(self):
        code, listing = run("outliers", self.out_a, "--concept", "skirt")
        self.assertEqual(code, 0)
        self.assertIn("外れた所（重い順", listing)
        path = os.path.join(self.folder, "tl.png")
        code, res = run("timeline", self.out_a, "--out", path, "--from", "2", "--to", "6", "--series", "pelvis_down")
        self.assertEqual(code, 0)
        self.assertEqual(Image.open(path).size[0], 1800)

    def test_mark_on_a_picture(self):
        pic = os.path.join(self.folder, "pic.png")
        Image.new("RGB", (1280, 720), (80, 80, 80)).save(pic)
        out = os.path.join(self.folder, "marked")
        code, res = run("mark", self.out_a, "--camera", self.camera, "--out", out, "--picture", "121=" + pic)
        self.assertEqual(code, 0, res)
        info = json.loads(text(os.path.join(out, "marks.json")))[0]
        self.assertIn("skirt.floor_over122_frames", info["events"])
        self.assertTrue(0 < info["com_px"][0] < 1280 and 0 < info["com_px"][1] < 720)

    def test_wrong_input_is_reported(self):
        code, res = run("measure", "--model", self.model, "--motions", os.path.join(self.folder, "nothing.vmd"), "--out",
                        os.path.join(self.folder, "x"))
        self.assertEqual(code, 2)
        self.assertFalse(res["ok"])
        code, res = run("measure", "--model", self.model, "--motions", self.smooth, "--out", os.path.join(self.folder, "y"),
                        "--parts", "gravity,nonsense")
        self.assertEqual(code, 2)

    def test_the_size_aligned_values_are_added_to_the_length_measures(self):
        rep = self.report(self.out_a)
        from tests.test_leg_ik import REST as LEG_REST
        rest = {s + n: np.array([sx * LEG_REST[n][0], LEG_REST[n][1], LEG_REST[n][2]])
                for s, sx in (("左", 1.0), ("右", -1.0)) for n in ("足", "ひざ", "足首")}
        size = rep["size"]
        self.assertEqual(size["by"], "legs")
        self.assertAlmostEqual(size["leg_cm"], MF.base.leg_cm(rest), places=2)
        self.assertAlmostEqual(size["scale"], MF.base.people_leg_cm() / size["leg_cm"], places=3)
        aligned = 0
        for r in rep["measures"]:
            if r["id"] in MF.base.SIZE_ALIGNED and r["value"] is not None:
                self.assertIn("size", r, r["id"])
                self.assertEqual(r["size"]["judge"] is None, r["judge"] is None, r["id"])
                aligned += 1
            else:
                self.assertNotIn("size", r, r["id"])
        self.assertGreater(aligned, 10)
        md = text(os.path.join(self.out_a, "report.md"))
        self.assertIn("脚でそろえた", md)
        self.assertIn("%.3f" % size["scale"], md)

    def test_size_none_leaves_the_report_as_before(self):
        out = os.path.join(self.folder, "nosize")
        code, res = run("measure", "--model", self.model, "--motions", self.dropping, "--label", "drop", "--out", out,
                        "--no-figure", "--parts", "feet,balance", "--size", "none")
        self.assertEqual(code, 0, res)
        rep = self.report(out)
        self.assertNotIn("size", rep)
        self.assertFalse(any("size" in r for r in rep["measures"]))
        self.assertNotIn("脚でそろえた", text(os.path.join(out, "report.md")))
        a = {r["id"]: (r["value"], r["judge"]) for r in self.report(self.out_a)["measures"] if r["concept"] in ("feet", "balance")}
        self.assertEqual({r["id"]: (r["value"], r["judge"]) for r in rep["measures"]}, a)

    def test_compare_judges_the_size_aligned_values_too(self):
        out = os.path.join(self.folder, "cmp_size")
        code, res = run("compare", self.out_a, self.out_b, "--out", out)
        self.assertEqual(code, 0)
        c = json.loads(text(os.path.join(out, "compare.json")))
        rows = {r["id"]: r for r in c["rows"]}
        for mid in MF.base.SIZE_ALIGNED:
            r = rows.get(mid)
            if r and r["a"] is not None and r["b"] is not None and r.get("ref", {}).get("kind", "people") == "people":
                self.assertIn("word_size", r, mid)


# ---- the MV itself ----------------------------------------------------------------------------------------------------

def song_spec():
    """v9 as the human baseline's v9 table measured it (the MV render inputs, camera D's gaze), from BALANCE_SONG"""
    song = os.environ.get("BALANCE_SONG")
    if not song:
        raise unittest.SkipTest("BALANCE_SONG is not set: it names the MV's inputs (tests/test_balance_layer.py); on hinata "
                                "see C:/work/hibikase/stage6/main_suite/run_suite_td.py")
    with open(song, encoding="utf-8") as f:
        paths = json.load(f)
    v9 = os.path.dirname(os.path.dirname(paths["dance"]))
    ri = os.path.join(v9, "render_in", "mv")
    motions = [os.path.join(ri, n) for n in ("hands_v9.vmd", "face_v9d.vmd", "gaze_v9d.vmd", "eye_optics_v9d.vmd")]
    if os.path.basename(paths["dance"]) != "spine_h.vmd" or not all(os.path.isfile(p) for p in motions):
        raise unittest.SkipTest("BALANCE_SONG's dance is not v9's spine_h.vmd beside v9's render_in/mv: %s" % paths["dance"])
    spec = {"label": "v9", "model": paths["model"], "motions": motions, "reference": paths["dance"]}
    data = os.environ.get("MMD_CLI_DATA")
    if data:
        for key, rel in (("vocal", ("audio", "vocals_htdemucs.flac")), ("lines", ("mv", "lyrics", "lines_timed.tsv"))):
            p = os.path.join(data, "_spike", "out", "hibikase", *rel)
            if os.path.isfile(p):
                spec[key] = p
    return spec


class SongTest(unittest.TestCase):
    """v9's numbers as the earlier work reported them (their own JSON, the precision of their tables)"""

    @classmethod
    def setUpClass(cls):
        spec = song_spec()
        cls.folder = tempfile.mkdtemp()
        sp = os.path.join(cls.folder, "v9.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        cls.has_voice = "vocal" in spec
        cls.code, cls.res = run("measure", sp, "--out", os.path.join(cls.folder, "v9"), "--no-figure")
        with open(os.path.join(cls.folder, "v9", "report.json"), encoding="utf-8") as f:
            cls.rep = json.load(f)
        cls.v = {r["id"]: r["value"] for r in cls.rep["measures"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def near(self, mid, value, tol):
        self.assertIsNotNone(self.v.get(mid), mid)
        self.assertLessEqual(abs(self.v[mid] - value), tol, "%s: %s against the reported %s" % (mid, self.v[mid], value))

    def test_nothing_failed(self):
        self.assertEqual(self.code, 0, self.res)

    def test_the_human_baselines_v9_table(self):
        # C:/work/hibikase/v9/hb/out/table_v8_v9.md (the v9 integration, 2026-10-16)
        for mid, value, tol in (("gravity.centre_down_max", -122.0, 0.5), ("gravity.centre_down_gt98_pct", 3.28, 0.01),
                                ("gravity.landing_sink_cm", -1.39, 0.005), ("feet.knee_gain_deg", 6.99, 0.005),
                                ("feet.slide3_per_min", 51.6, 0.05), ("balance.com_lateral_cm", 9.08, 0.005),
                                ("balance.touchdown_xcom_cm", 11.4, 0.05), ("balance.com_outside_2cm_pct", 80.1, 0.05),
                                ("balance.held_outside_per_min", 6.51, 0.005), ("upper.head_stop_ms", 48.7, 0.05),
                                ("upper.head_sudden_stops_per_min", 3.66, 0.005), ("upper.upper_sudden_stops_per_min", 2.93, 0.005),
                                ("upper.head_acc_p99", 193.0, 0.5), ("arms.a09_shoulder_elbow_L", 0.246, 0.0005),
                                ("arms.a09_shoulder_elbow_R", -0.001, 0.0005), ("arms.a09_elbow_wrist_L", -0.12, 0.0005),
                                ("arms.a09_elbow_wrist_R", 0.007, 0.0005), ("arms.a09_wrist_finger_L", 0.209, 0.0005),
                                ("arms.a09_wrist_finger_R", -0.118, 0.0005), ("arms.wrist_3_6hz_pct", 14.2, 0.05),
                                ("arms.wrist_8hz_pct", 0.615, 0.0005), ("spikes.centre_per_min", 11.2, 0.05),
                                ("spikes.wrist_R_per_min", 20.2, 0.05), ("spikes.wrist_L_per_min", 16.1, 0.05),
                                ("spikes.head_per_min", 24.4, 0.05)):
            self.near(mid, value, tol)

    def test_balance_v3_and_floaty(self):
        # balance_v3/NOTES.md's final table (v9 column) and floaty/out/table_floaty_fin2.md (v9 column)
        for mid, value, tol in (("balance.moving_com_lateral_cm", 9.72, 0.005), ("balance.moving_mos_ml_cm", -5.73, 0.005),
                                ("feet.knee_straight_pct", 3.26, 0.005), ("gravity.jump_apex_lowered", 9, 0),
                                ("gravity.beat_dips_weak", 18, 0), ("gravity.hover_pct", 8.07, 0.005),
                                ("gravity.hover_runs6_per_min", 9.3, 0.05), ("gravity.air_per_min", 5.61, 0.005),
                                ("gravity.air_slow_share", 0.348, 0.0005), ("gravity.air_acc_median", -89.4, 0.05),
                                ("gravity.desc_ratio_median", 2.38, 0.005), ("gravity.desc_peak_down_median", -122.0, 0.5),
                                ("gravity.desc_brake_median", 131.0, 0.5), ("gravity.apex_dwell_ms", 133.0, 0.5),
                                ("gravity.beat_range_cm", 4.43, 0.005), ("gravity.vy_p95", 71.7, 0.05),
                                ("gravity.vy_above_3hz_pct", 7.22, 0.005)):
            self.near(mid, value, tol)

    def test_wbbalance_and_its_review(self):
        # wbbalance/out/table_s16.md (v9) and review_wbbalance/out/ub_table.md (v9)
        for mid, value, tol in (("balance.zmp_inside_pct", 17.4, 0.05), ("balance.single_share_pct", 58.5, 0.05),
                                ("balance.zmp_tilt_deg_per_min", 2997.0, 1.0), ("upper.head_follow", 0.89, 0.005),
                                ("upper.chest_follow", 0.93, 0.005), ("upper.arms_follow", 0.90, 0.005),
                                ("upper.head_pelvis_xcorr_peak", 0.623, 0.0005), ("upper.head_stops_per_min", 60.5, 0.05)):
            self.near(mid, value, tol)

    def test_the_fingers_and_the_eyes(self):
        # fingers_v3/NOTES.md (v9: 23.3 / 29.3 deg/s, 0.307 / 0.358) and v9/build/mv/gaze_v9d_report.json's measures
        for mid, value, tol in (("arms.finger_speed_L", 23.3, 0.05), ("arms.finger_speed_R", 29.3, 0.05),
                                ("arms.finger_wrist_ratio_L", 0.307, 0.0005), ("arms.finger_wrist_ratio_R", 0.358, 0.0005),
                                ("eyes.edge_pct", 0.63, 0.005), ("eyes.edge_longest_s", 0.2, 0.0005),
                                ("eyes.eccentric15_pct", 4.07, 0.005)):
            self.near(mid, value, tol)

    def test_the_mouth(self):
        if not self.has_voice:
            self.skipTest("MMD_CLI_DATA has not the song's separated voice")
        # review_lipsync/NOTES.md 4 (the front set's face before lip_sync: every onset +92 ms, 25 % late; the open
        # vowels +107 ms; shut while singing inside the lines 15.6 %)
        for mid, value, tol in (("mouth.lag_median_ms", 92.0, 1.0), ("mouth.late_pct", 25.0, 1.0),
                                ("mouth.lag_open_ms", 107.0, 1.0), ("mouth.shut_singing_pct", 15.6, 0.1)):
            self.near(mid, value, tol)

    def test_the_skirt_rule_holds_on_v9(self):
        self.assertEqual(self.v["skirt.floor_over122_frames"], 0)


if __name__ == "__main__":
    unittest.main()
