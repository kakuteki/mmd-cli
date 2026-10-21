"""tools/camera_rhythm.py: how a camera keeps time with the music (its cuts and its motion against the beats, the strong
onsets and the section heads, in frames) and how much of the song it moves and how; one yardstick for a camera motion
(.vmd) and for a video (the picture's motion: the similarity transform of the background's flow)."""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import tempfile
import unittest
import wave

import numpy as np

from mmd_cli import fk
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cr = load("camera_rhythm")
oc = load("operator_camera")
FPS = 30


def keys_of(frames, cuts=(0,)):
    """camera keys (a key on every frame) from operator_camera CameraFrames"""
    return fk.camera_keys(oc.camera_motion(frames, list(cuts)))


def frame_at(look, yaw, pitch, reach, fov=30):
    return oc.CameraFrame(oc.place_camera(look, yaw, pitch, reach), yaw, pitch, 0.0, fov, reach)


LOOK = (0.0, 13.0, 0.0)


class OnsetTest(unittest.TestCase):
    def test_clicks_in_quiet_noise_are_found_at_their_times(self):
        # a click (a short burst of noise) every 0.5 s from 1.0 s over faint noise: the onsets are those times (the
        # envelope's own delay taken off by the calibration of a04: the kick's attack), strong; nothing else stands out
        sr = 16000
        rng = np.random.default_rng(1)
        x = 0.002 * rng.standard_normal(sr * 6).astype(np.float32)
        times = [1.0 + 0.5 * k for k in range(9)]
        for t in times:
            i = int(t * sr)
            x[i:i + 160] += 0.8 * rng.standard_normal(160).astype(np.float32)
        found = cr.onsets_of(x, sr, min_z=3.0, gap=0.2)
        got = [o["t"] for o in found]
        self.assertEqual(len(got), len(times), got)
        for a, b in zip(got, times):
            self.assertLess(abs(a - b), 0.025, (a, b))
        self.assertTrue(all(o["z"] >= 3.0 for o in found))


class GridTest(unittest.TestCase):
    def test_offsets_to_the_nearest_beat_in_frames(self):
        beats = [0.5 * k for k in range(1, 40)]          # 120 BPM: 15 frames a beat
        events = [b - 2.0 / FPS for b in beats[::3]]     # every third beat, two frames early
        r = cr.on_grid(events, beats, FPS)
        self.assertEqual(r["n"], len(events))
        self.assertAlmostEqual(r["offset_median"], -2.0, places=6)
        self.assertEqual(r["within_lead"], 1.0)          # within [-3, +1] frames of a beat
        self.assertGreater(r["lock_R"], 0.95)
        self.assertLess(r["lock_p"], 0.01)
        # events spread over the beat: no lock
        spread = [b + (k % 7) * 2.1 / FPS for k, b in enumerate(beats)]
        self.assertLess(cr.on_grid(spread, beats, FPS)["lock_R"], 0.5)


class SeriesTest(unittest.TestCase):
    def test_a_pan_between_two_stills_is_one_motion_from_its_start_to_its_stop(self):
        n = 150
        motion = np.zeros((n, 4))
        motion[40:100, 0] = 100.0 / FPS                  # 720-line px a frame: 100 px/s sideways over frames 40-99
        t = cr.picture_track(motion, FPS, cuts=[])
        self.assertEqual(t["moving"][:35].sum(), 0)
        self.assertTrue(t["moving"][45:95].all())
        segs = t["segments"]
        self.assertEqual(len(segs), 1)
        self.assertLessEqual(abs(segs[0]["start"] - 40), 2)
        self.assertLessEqual(abs(segs[0]["stop"] - 100), 2)
        self.assertEqual(segs[0]["kind"], "pan")
        self.assertAlmostEqual(t["moving_share"], 60.0 / n, delta=0.04)

    def test_a_zoom_reads_as_a_zoom_and_a_cut_is_no_motion(self):
        n = 120
        motion = np.zeros((n, 4))
        motion[20:80, 2] = 0.05 / FPS                    # the picture grows 5 % a second
        motion[100, 0] = 300.0                           # a cut: a jump of the whole picture
        t = cr.picture_track(motion, FPS, cuts=[100])
        kinds = [s["kind"] for s in t["segments"]]
        self.assertEqual(kinds, ["zoom"])
        self.assertFalse(t["moving"][98:103].any())


class CameraTest(unittest.TestCase):
    def kinds(self, frames, cuts=(0,)):
        k = cr.camera_kinematics(keys_of(frames, cuts), len(frames) - 1)
        return k, [s["kind"] for s in k["segments"]]

    def test_a_still_camera_does_not_move(self):
        k, kinds = self.kinds([frame_at(LOOK, 0.0, 5.0, 34.0)] * 90)
        self.assertEqual(kinds, [])
        self.assertEqual(k["moving_share"], 0.0)

    def test_the_kinds_of_motion_are_told_apart(self):
        n = 90
        ease = [0.5 - 0.5 * math.cos(math.pi * f / (n - 1)) for f in range(n)]
        dolly = [frame_at(LOOK, 0.0, 5.0, 38.0 - 8.0 * e) for e in ease]
        orbit = [frame_at(LOOK, -20.0 + 40.0 * e, 5.0, 34.0) for e in ease]
        crane = [frame_at(LOOK, 0.0, 5.0 + 15.0 * e, 34.0) for e in ease]
        track = []
        for e in ease:
            look = (LOOK[0] + 8.0 * e, LOOK[1], LOOK[2])
            track.append(frame_at(look, 0.0, 5.0, 34.0))
        for frames, want in ((dolly, "dolly"), (orbit, "orbit"), (crane, "crane"), (track, "track")):
            k, kinds = self.kinds(frames)
            self.assertEqual(kinds, [want], want)
            seg = k["segments"][0]
            self.assertLessEqual(seg["start"], 12, want)
            self.assertGreaterEqual(seg["stop"], n - 12, want)

    def test_a_cut_is_found_and_is_no_motion(self):
        a = [frame_at(LOOK, 0.0, 5.0, 34.0)] * 60
        b = [frame_at(LOOK, 40.0, 10.0, 30.0)] * 60
        k, kinds = self.kinds(a + b, cuts=(0, 60))
        self.assertEqual(k["cuts"], [60])
        self.assertEqual(kinds, [])


class FlowTest(unittest.TestCase):
    """the picture's motion of a camera motion, from the stage's geometry: what the references' camera fit would read"""

    def setUp(self):
        sl = load("stage_layer")
        # a floor and a back wall, both wide
        P = np.array([[-200, 0, -200], [200, 0, -200], [200, 0, 200], [-200, 0, 200],
                      [-200, 0, 60], [200, 0, 60], [200, 80, 60], [-200, 80, 60]], np.float64)
        F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7]], np.int64)
        self.mesh = sl.Mesh(P, F, np.zeros(len(F), np.int64), [sl.Material("m", flags=sl.BOTH_SIDES)])

    def test_a_pan_shifts_the_picture_by_the_focal_length_times_the_turn(self):
        frames = [frame_at(LOOK, 0.1 * f, 5.0, 34.0) for f in range(6)]   # the camera swings round the look-at point
        keys = keys_of(frames)
        m = cr.picture_motion_of_camera(keys, 5, self.mesh, size=(128, 72))
        self.assertEqual(m.shape, (6, 4))
        # a sideways shift every frame, about the same each frame; no zoom to speak of
        self.assertGreater(abs(m[3, 0]), 0.5)
        self.assertLess(abs(m[3, 2]), 0.002)

    def test_a_push_in_grows_the_picture(self):
        frames = [frame_at(LOOK, 0.0, 5.0, 34.0 - 0.5 * f) for f in range(6)]
        m = cr.picture_motion_of_camera(keys_of(frames), 5, self.mesh, size=(128, 72))
        self.assertGreater(m[3, 2], 0.002)


class VideoTest(unittest.TestCase):
    def test_a_moving_texture_reads_as_a_pan(self):
        rng = np.random.default_rng(3)
        base = rng.random((72, 400, 3))
        frames = []
        for f in range(40):
            dx = 0 if f < 10 else min(2 * (f - 10), 60)
            frames.append(base[:, 100 + dx:100 + dx + 128])
        m = cr.motion_of_frames(frames, FPS)
        t = cr.picture_track(m, FPS, cuts=[])
        self.assertEqual(t["moving"][:8].sum(), 0)
        self.assertTrue(t["moving"][14:38].any())


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_vmd_writes_the_cuts_the_motion_and_their_place_against_the_beat(self):
        n = 240
        ease = [0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, (f - 60) / 60.0))) for f in range(n)]
        frames = [frame_at(LOOK, -20.0 + 40.0 * e, 5.0, 34.0) for e in ease[:150]] + \
                 [frame_at(LOOK, 50.0, 10.0, 30.0)] * (n - 150)
        cam = os.path.join(self.folder, "cam.vmd")
        with open(cam, "wb") as f:
            f.write(vmd.dumps(oc.camera_motion(frames, [0, 150])))
        song = os.path.join(self.folder, "song.json")
        with open(song, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "beats": [0.5 * k for k in range(17)],
                       "sections": [{"id": "intro", "t": 0.0, "frame": 0}, {"id": "verse1", "t": 5.0, "frame": 150}]}, f)
        out = os.path.join(self.folder, "r.json")
        self.assertEqual(cr.main(["vmd", cam, out, "--song", song]), 0)
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["cuts"], [150])
        self.assertEqual(r["cuts_on_grid"]["beats"]["n"], 1)
        self.assertEqual(r["cuts_on_grid"]["beats"]["offset_median"], 0.0)
        self.assertEqual(r["cuts_on_grid"]["sections"]["offset_median"], 0.0)
        self.assertIn("orbit", r["kinds_seconds"])
        for key in ("starts", "stops", "peaks"):
            self.assertIn(key, r["events_on_grid"])
        md = os.path.join(self.folder, "c.md")
        self.assertEqual(cr.main(["compare", md, md + ".json", "ours=" + out]), 0)
        with open(md, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ours", text)


# ---- (review camsyncrev 2026-10-21) the cases the tests above let pass: the tools broken one place at a time (139 ways:
# 80 that changed what the tool does were not caught), each case below fails on one of them and passes on the tool as it is

mc = load("make_camera")


def panning(n, frames, px_per_s, axis=0):
    """a picture's motion (N x 4) that shifts px_per_s (720-line px a second) on `frames`, sideways (axis 0) or up (1)"""
    m = np.zeros((n, 4))
    for f in frames:
        m[f, axis] = px_per_s / FPS
    return m


def clicks(times, seconds, amplitude=0.8, noise=0.002, seed=1, burst=None, sr=16000):
    rng = np.random.default_rng(seed)
    x = noise * rng.standard_normal(int(sr * seconds)).astype(np.float32)
    for t in times:
        i = int(t * sr)
        b = amplitude * rng.standard_normal(160).astype(np.float32) if burst is None else burst
        x[i:i + len(b)] += b
    return x


def write_json(folder, name, data):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def quiet(main, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


class OnsetCasesTest(unittest.TestCase):
    def test_a_high_click_is_an_onset_too(self):
        # a hi-hat or a clap: a 10 ms burst of a 3 kHz tone, nothing of it under a kilohertz, every 0.5 s over faint noise;
        # each is found at its time (T1-02: the band cut at 800 Hz loses them)
        sr = 16000
        n = 160
        burst = (0.8 * np.hanning(n) * np.sin(2 * np.pi * 3000.0 * np.arange(n) / sr)).astype(np.float32)
        times = [1.0 + 0.5 * k for k in range(9)]
        got = [o["t"] for o in cr.onsets_of(clicks(times, 6, burst=burst, seed=2), sr, min_z=3.0, gap=0.2)]
        self.assertEqual(len(got), len(times), got)
        for a, b in zip(got, times):
            self.assertLess(abs(a - b), 0.03, (a, b))

    def test_a_loud_steady_noise_between_the_clicks_is_no_onset(self):
        # clicks a little louder than a steady loud noise: the envelope is measured against its own mean over the song
        # (z-scored), so the noise stands at about 0 and only the clicks stand out, even at a low --min-z (T1-03)
        times = [1.0 + 0.5 * k for k in range(9)]
        got = [o["t"] for o in cr.onsets_of(clicks(times, 6, amplitude=0.25, noise=0.05, seed=4), 16000, min_z=1.0,
                                            gap=0.2)]
        self.assertEqual(len(got), len(times), got)

    def test_two_onsets_closer_than_the_gap_are_one(self):
        # a flam (1.0 s and 1.12 s) with --gap 0.3 is one onset, the stronger; a click 1.5 s later is another (T1-05)
        got = [o["t"] for o in cr.onsets_of(clicks([1.0, 2.5], 4, seed=5) + clicks([1.12], 4, amplitude=0.5, noise=0.0,
                                                                                  seed=6), 16000, min_z=3.0, gap=0.3)]
        self.assertEqual(len(got), 2, got)
        self.assertLess(abs(got[0] - 1.0), 0.03, got)


class GridEdgesTest(unittest.TestCase):
    def test_the_lead_window_is_the_one_the_table_names(self):
        # the table calls within_lead "拍の -3〜+1 コマ" and within_1 a frame either way: 3 frames before a beat keeps time,
        # 4 before does not, 1 after does, 2 after does not (T1-08, T1-09)
        beats = [0.5 * k for k in range(1, 40)]
        for off, lead, one in ((-4, 0.0, 0.0), (-3, 1.0, 0.0), (-2, 1.0, 0.0), (-1, 1.0, 1.0), (0, 1.0, 1.0), (1, 1.0, 1.0),
                               (2, 0.0, 0.0)):
            r = cr.on_grid([b + off / 30.0 for b in beats[1:-1:3]], beats, FPS)
            self.assertEqual((r["within_lead"], r["within_1"]), (lead, one), off)

    def test_the_chance_of_the_lead_is_where_events_at_random_land(self):
        rng = np.random.default_rng(6)
        beats = [0.5 * k for k in range(200)]
        r = cr.on_grid(list(rng.uniform(1.0, 98.0, 4000)), beats, FPS)
        self.assertAlmostEqual(r["within_lead"], r["chance_lead"], delta=0.03)          # T1-10
        self.assertLess(r["lock_R"], 0.1)

    def test_the_place_the_events_keep_is_in_frames(self):
        beats = [0.5 * k for k in range(1, 40)]
        r = cr.on_grid([b - 2.0 / 30 for b in beats[::3]], beats, FPS)
        self.assertAlmostEqual(r["lock_offset"], -2.0, delta=0.05)                       # T1-11

    def test_an_event_just_before_the_last_beat_is_measured_to_it(self):
        beats = [0.5 * k for k in range(1, 40)]
        self.assertAlmostEqual(cr.on_grid([beats[-1] - 1.0 / 30], beats, FPS)["offset_median"], -1.0, places=6)  # T1-13


class SeriesEdgesTest(unittest.TestCase):
    def test_a_pause_of_up_to_max_gap_frames_does_not_split_a_move(self):
        for gap, count in ((cr.MAX_GAP, 1), (cr.MAX_GAP + 1, 2)):                         # T1-16
            frames = list(range(40, 70)) + list(range(70 + gap, 110))
            self.assertEqual(len(cr.picture_track(panning(150, frames, 100.0), FPS)["segments"]), count, gap)

    def test_a_move_of_min_run_frames_counts_and_a_shorter_one_does_not(self):
        for frames, count in ((cr.MIN_RUN, 1), (cr.MIN_RUN - 1, 0)):                      # T1-17
            self.assertEqual(len(cr.picture_track(panning(100, range(40, 40 + frames), 100.0), FPS)["segments"]), count)

    def test_a_frame_moves_over_its_threshold_and_not_under_it(self):
        pan = cr.PICTURE_MOVE["pan"]                                                       # T1-18
        self.assertEqual(len(cr.picture_track(panning(120, range(30, 90), 1.5 * pan), FPS)["segments"]), 1)
        self.assertEqual(len(cr.picture_track(panning(120, range(30, 90), 0.5 * pan), FPS)["segments"]), 0)

    def test_the_peak_is_the_frame_the_pace_is_highest(self):
        m = np.zeros((150, 4))
        for f in range(45, 96):
            m[f, 0] = (300.0 - 10.0 * abs(f - 70)) / FPS                                  # up to 300 px/s at frame 70
        segs = cr.picture_track(m, FPS)["segments"]
        self.assertEqual(len(segs), 1)
        self.assertLessEqual(abs(segs[0]["peak"] - 70), 1, segs)                           # T1-20

    def test_a_pan_stops_on_the_first_frame_after_it(self):
        segs = cr.picture_track(panning(150, range(40, 100), 100.0), FPS)["segments"]
        self.assertEqual([(s["start"], s["stop"]) for s in segs], [(40, 100)])             # T1-21

    def test_the_frames_next_to_a_cut_are_no_motion(self):
        t = cr.picture_track(panning(120, range(0, 120), 100.0), FPS, cuts=[60])           # T1-22
        self.assertEqual([bool(t["moving"][f]) for f in (57, 59, 60, 61, 63)], [True, False, False, False, True])

    def test_an_up_and_down_pan_is_a_pan(self):
        segs = cr.picture_track(panning(150, range(40, 100), 100.0, axis=1), FPS)["segments"]
        self.assertEqual([s["kind"] for s in segs], ["pan"])                               # T1-23

    def test_a_zoom_out_is_a_zoom(self):
        m = np.zeros((120, 4))
        m[20:80, 2] = -0.05 / FPS
        self.assertEqual([s["kind"] for s in cr.picture_track(m, FPS)["segments"]], ["zoom"])   # T1-24

    def test_a_flicker_of_the_picture_is_no_move(self):
        # the picture jolts on 2 frames of every 5 (flow noise, a strobe), never on 3 running: no move (T1-15)
        m = np.zeros((150, 4))
        for f in range(20, 130):
            if f % 5 < 2:
                m[f, 0] = 200.0 / FPS
        self.assertEqual(cr.picture_track(m, FPS)["segments"], [])

    def test_a_move_on_to_the_last_frame_moves_there(self):
        # a pan that goes on through the end of the clip, one frame of its flow weak near the end: it still moves on the
        # last frame (T1-14: an edge padded with 0 drops it)
        n = 100
        m = panning(n, range(60, n), 100.0)
        m[n - 3, 0] = 10.0 / FPS
        t = cr.picture_track(m, FPS)
        self.assertTrue(t["moving"][n - 1])
        self.assertEqual(t["segments"][-1]["stop"], n)


class CameraKindsTest(unittest.TestCase):
    def test_a_jump_of_the_eye_without_a_step_key_is_a_cut(self):
        # a camera made elsewhere, no step curve on its cut: the eye jumps 10 units sideways in a frame, the way it looks
        # unchanged (T1-28)
        a = [frame_at(LOOK, 0.0, 5.0, 34.0)] * 60
        b = [frame_at((LOOK[0] + 10.0, LOOK[1], LOOK[2]), 0.0, 5.0, 34.0)] * 60
        k = cr.camera_kinematics(keys_of(a + b), 119)
        self.assertEqual(k["cuts"], [60])

    def test_make_cameras_handheld_sway_reads_as_handheld(self):
        # make_camera --handheld 1 on a camera that stands still: about 0.5 deg/s at most, not a move and not still either
        # (camera_rhythm's docstring) (T1-31)
        shot = mc.MusicShot(0, 0, 299, "break", "break", 4, {"distance": 40.0, "pitch": 6.0, "yaw": 0.0, "track": 0.0}, [],
                            [(0.0, 0.0)] * 300)
        k = cr.camera_kinematics(fk.camera_keys(mc.music_motion([shot], 299, handheld=1.0, seed=0)), 299)
        self.assertEqual(k["segments"], [])
        self.assertGreater(k["kinds_seconds"]["handheld"], 0.8 * 300 / FPS, k["kinds_seconds"])

    def test_the_kinds_share_the_frames_out(self):
        # an orbit of 2 seconds between two holds: every frame is one move, handheld or still, once (T1-32)
        n = 180
        ease = [0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, (f - 60) / 60.0))) for f in range(n)]
        k = cr.camera_kinematics(keys_of([frame_at(LOOK, -20.0 + 40.0 * e, 5.0, 34.0) for e in ease]), n - 1)
        self.assertAlmostEqual(sum(k["kinds_seconds"].values()), n / float(FPS), delta=1.5 / FPS)
        self.assertGreater(k["kinds_seconds"]["orbit"], 1.0)

    def test_a_camera_that_goes_and_comes_back_turns_once(self):
        # tracking 6 units a second to her left for 50 frames and back for 50: one turn, at the way back; a straight track
        # none (T1-33)
        def track(xs):
            return keys_of([frame_at((x, LOOK[1], LOOK[2]), 0.0, 5.0, 34.0) for x in xs])
        there = [0.2 * f for f in range(50)]
        k = cr.camera_kinematics(track(there + [there[-1] - 0.2 * (f + 1) for f in range(50)]), 99)
        self.assertEqual(len(k["turns"]), 1, k["turns"])
        self.assertLessEqual(abs(k["turns"][0] - 50), cr.TURN_SPAN)
        self.assertEqual(cr.camera_kinematics(track([0.2 * f for f in range(100)]), 99)["turns"], [])

    def test_a_crane_up_rises(self):
        n = 90
        ease = [0.5 - 0.5 * math.cos(math.pi * f / (n - 1)) for f in range(n)]
        k = cr.camera_kinematics(keys_of([frame_at(LOOK, 0.0, 5.0 + 15.0 * e, 34.0) for e in ease]), n - 1)
        self.assertGreater(min(k["components"]["crane"][30:60]), 0.0)                     # T1-27

    def test_a_camera_moving_all_through_its_shots_moves_on_every_frame_it_can(self):
        # an orbit at an even pace through a cut every 20 frames: all the frames but those round the cuts (and the first)
        # move, and the share counts the frames it can move on (T1-25)
        n = 200
        cuts = list(range(0, n, 20))
        k = cr.camera_kinematics(keys_of([frame_at(LOOK, 1.0 * f, 5.0, 34.0) for f in range(n)], cuts), n - 1)
        self.assertEqual(k["cuts"], cuts[1:])
        self.assertGreater(k["moving_share"], 0.97)

    def test_a_camera_behind_her_that_jitters_across_the_back_does_not_orbit(self):
        # heading 180 with a hundredth of a degree of jitter from frame to frame across the back: the heading is unwrapped,
        # no spin is read (T1-26: only a jitter across 180 on consecutive frames shows it; one crossing the median removes)
        n = 120
        k = cr.camera_kinematics(keys_of([frame_at(LOOK, 180.0 + (0.01 if f % 2 else -0.01), 5.0, 34.0) for f in range(n)]),
                                 n - 1)
        self.assertEqual(k["segments"], [])


class FlowScaleTest(unittest.TestCase):
    def mesh(self, wall=True):
        sl = load("stage_layer")
        P = [[-2000, 0, -2000], [2000, 0, -2000], [2000, 0, 2000], [-2000, 0, 2000]]
        F = [[0, 2, 1], [0, 3, 2]]
        if wall:
            P += [[-200, 0, 60], [200, 0, 60], [200, 80, 60], [-200, 80, 60]]
            F += [[4, 5, 6], [4, 6, 7]]
        F = np.array(F, np.int64)
        return sl.Mesh(np.array(P, np.float64), F, np.zeros(len(F), np.int64), [sl.Material("m", flags=sl.BOTH_SIDES)])

    def test_a_pan_shifts_the_picture_by_the_focal_length_times_the_turn(self):
        # the camera turns about its own eye 0.1 degree a frame: the picture shifts by f tan(0.1 degree), f = 360 / tan(15
        # degrees) in 720-line px for a field of 30, whatever the read size (T1-35)
        eye = oc.place_camera(LOOK, 0.0, 5.0, 34.0)
        frames = [oc.CameraFrame(eye, 0.1 * f, 5.0, 0.0, 30, 34.0) for f in range(6)]
        m = cr.picture_motion_of_camera(keys_of(frames), 5, self.mesh(), size=(128, 72))
        want = 360.0 / math.tan(math.radians(15.0)) * math.tan(math.radians(0.1))
        self.assertAlmostEqual(abs(m[3, 0]), want, delta=0.1 * want)

    def test_a_track_under_an_open_sky_hardly_moves_the_picture(self):
        # the camera tracks sideways half a unit a frame, looking up over a floor: most of the picture is sky (nothing of
        # the stage behind it: far away, FAR), which a sideways move does not shift (T1-34: the sky left out, the floor's
        # parallax takes the fit)
        frames = [oc.CameraFrame((0.5 * f, 13.0, -40.0), 0.0, -8.0, 0.0, 30, 34.0) for f in range(6)]
        m = cr.picture_motion_of_camera(keys_of(frames), 5, self.mesh(wall=False), size=(128, 72))
        self.assertLess(abs(m[3, 0]), 1.0, m[3])


class CommandOutputTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def camera(self, frames, cuts):
        path = os.path.join(self.folder, "cam%d.vmd" % len(os.listdir(self.folder)))
        with open(path, "wb") as f:
            f.write(vmd.dumps(oc.camera_motion(frames, cuts)))
        return path

    def song(self, sections=None):
        return write_json(self.folder, "song.json", {"fps": 30, "beats": [0.5 * k for k in range(41)],
                                                     "sections": sections or [{"id": "intro", "t": 0.0}, {"id": "verse1", "t": 5.0}]})

    def test_section_heads_given_in_frames_are_read_as_seconds(self):
        path = self.song([{"id": "intro", "frame": 0}, {"id": "verse1", "frame": 150}])
        self.assertEqual(cr.load_song(path)["sections"], [0.0, 5.0])                    # T1-37

    def test_an_onset_of_the_strong_z_itself_is_strong(self):
        path = write_json(self.folder, "on.json", {"onsets": [{"t": 1.0, "z": 4.0}, {"t": 2.0, "z": 3.99}, {"t": 3.0, "z": 6.0}]})
        self.assertEqual(cr.load_onsets(path, 4.0), [1.0, 3.0])                            # T1-38

    def test_the_shots_and_the_cut_rate_of_a_camera(self):
        # shots of 1, 1 and 10 seconds: 2 cuts in 12 s, 10 a minute, the median shot 1 s (T1-39, T1-40)
        frames = [frame_at(LOOK, 0.0, 5.0, 34.0)] * 30 + [frame_at(LOOK, 40.0, 10.0, 30.0)] * 30 + \
                 [frame_at(LOOK, -30.0, 8.0, 36.0)] * 300
        out = os.path.join(self.folder, "r.json")
        code, _ = quiet(cr.main, ["vmd", self.camera(frames, [0, 30, 60]), out, "--song", self.song()])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["cuts"], [30, 60])
        self.assertAlmostEqual(r["cuts_per_min"], 10.0, places=3)
        self.assertAlmostEqual(r["shots_median_s"], 1.0, places=3)

    def orbit_then_cut(self):
        n = 240
        ease = [0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, (f - 60) / 60.0))) for f in range(n)]
        frames = [frame_at(LOOK, -20.0 + 40.0 * e, 5.0, 34.0) for e in ease[:150]] + [frame_at(LOOK, 50.0, 10.0, 30.0)] * 90
        return self.camera(frames, [0, 150])

    def test_the_comparison_carries_the_outputs_own_numbers(self):
        out = os.path.join(self.folder, "r.json")
        self.assertEqual(quiet(cr.main, ["vmd", self.orbit_then_cut(), out, "--song", self.song()])[0], 0)
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
        t = cr.compare(os.path.join(self.folder, "c.md"), os.path.join(self.folder, "c.json"), ["ours=" + out])
        rows = {(row["side"], row["key"]): row["values"][0] for row in t["rows"]}
        self.assertEqual(rows.get(("camera", "cuts.beats.offset_median")), r["cuts_on_grid"]["beats"]["offset_median"])
        self.assertEqual(rows.get(("camera", "starts.beats.within_lead")), r["events_on_grid"]["starts"]["beats"]["within_lead"])
        self.assertEqual(rows.get(("camera", "moving_share")), r["moving_share"])                     # T1-41

    def test_vmd_measures_against_the_strong_onsets_it_is_given(self):
        # a strong onset 2 frames before the cut (5.0 s) and a weak one a frame after it: --strong 4 keeps the strong one
        # only, so the cut is 2 frames after it (T1-42)
        onsets = write_json(self.folder, "on.json", {"onsets": [{"t": 5.0 - 2.0 / 30, "z": 6.0}, {"t": 5.0 + 1.0 / 30, "z": 3.0}]})
        out = os.path.join(self.folder, "r.json")
        self.assertEqual(quiet(cr.main, ["vmd", self.orbit_then_cut(), out, "--song", self.song(), "--onsets", onsets,
                                         "--strong", "4"])[0], 0)
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
        self.assertIn("onsets", r["cuts_on_grid"])
        self.assertEqual(r["cuts_on_grid"]["onsets"]["n"], 1)
        self.assertAlmostEqual(r["cuts_on_grid"]["onsets"]["offset_median"], 2.0, places=3)

    def test_the_onsets_command_reads_an_audio_file(self):
        # (needs ffmpeg, as the command does) clicks every 0.5 s from 1.0 s in a 16-bit WAV (T1-43)
        if shutil.which("ffmpeg") is None:
            self.fail("ffmpeg is not on PATH: the onsets command reads audio with it")
        x = clicks([1.0 + 0.5 * k for k in range(9)], 6)
        wav = os.path.join(self.folder, "c.wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes())
        out = os.path.join(self.folder, "on.json")
        code, result = quiet(cr.main, ["onsets", wav, out, "--min-z", "3", "--gap", "0.2"])
        self.assertEqual(code, 0, result)
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual((r["min_z"], r["gap"]), (3.0, 0.2))
        self.assertEqual(len(r["onsets"]), 9, r["onsets"])
