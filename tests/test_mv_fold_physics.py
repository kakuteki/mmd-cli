"""The fold of tools/mv_look.py and MMD's physics, which steps 60 times a second whatever the rate of the AVI.

MMD renders the dancer at 240 or 480 fps: the body is posed anew on every frame, the camera moves on the first frame of every
frame of the song only (30 times a second), and hair, skirt and ribbons (the physics) move on every 4th (240) or 8th (480)
frame.  Which frame that is (the phase) changes from render to render.  The fold averages the first round(shutter x N) of
every N frames; when the step of the physics falls inside that window, the cloth shows twice (review of fast-render, Q4).
`render --physics-align` reads where the physics steps in the dancer's file and moves the window of every output frame
inside one step of the physics; tools/mv_chunks.py --align-physics passes it on to every chunk.

The dancers of these tests are synthetic AVIs like MMD's (BGRA, transparent around): a shaded "body" moving 1 px on every
frame, a white "cloth" moving 3 px on the steps of the physics only, and a "floor" of stripes that moves on the first frame
of every frame of the song only (the camera)."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from tests.test_mv_chunks import (FAKE_MMD, FLAT_LOOK, GOLDEN_30, GOLDEN_60, PARSE_FIRST, PLAN, SPANS, WINDOWS, hashes,
                                  load_tool, run_powershell, sha256_of, value)

try:
    import numpy
    mv_look = load_tool("mv_look")
except ImportError:                         # numpy and Pillow: needed by tools/mv_look.py only
    numpy = mv_look = None
mv_chunks = load_tool("mv_chunks")
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
SIZE = (320, 180)
CLOTH_ROW, BODY_ROW = 110, 50


def cloth_dancer(path, rate, frames, steps, size=SIZE, cloth=True, pan=0, noise=0):
    """the AVI: every frame of the song is rate / 30 frames; the cloth moves 3 px on the frames in `steps` (and jumps back to
    where it started on every 30th step, to stay in the picture).  With `pan` the camera moves everything (cloth and body too)
    `pan` px on the first frame of every frame of the song, back and forth, and the cloth is shaded, so that every pixel of it
    changes when the camera moves (review of the branch: the step next to such a frame had no lone pixel left).  With `noise`
    that many pixels of a strip at the top take a new grey on every frame and keep it: lone changes on every frame, as the
    edges of a body in a real picture give them"""
    w, h = size
    song = rate // 30
    ramp = numpy.linspace(40, 250, 24).astype(numpy.uint8)
    shade = numpy.linspace(60, 250, 40).astype(numpy.uint8) if pan else numpy.full(40, 255, numpy.uint8)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", "%dx%d" % size, "-r", str(rate),
                          "-i", "-", "-c:v", "rawvideo", "-pix_fmt", "bgra", path], stdin=subprocess.PIPE)
    k = 0
    rng = numpy.random.default_rng(7)
    strip = numpy.zeros((16, w, 4), numpy.uint8)
    strip[:, :, 3] = 255
    for t in range(frames):
        if t in steps:
            k += 1
        if noise:
            ys, xs = rng.integers(0, 16, noise), rng.integers(0, w, noise)
            strip[ys, xs, :3] = rng.integers(0, 256, (noise, 1)).astype(numpy.uint8)
        cam = pan * ((t // song) % 2)                                       # where the camera has put everything this song frame
        f = numpy.zeros((h, w, 4), numpy.uint8)
        if noise:
            f[:16] = strip
        stripes = (numpy.arange(w) + 2 * (t // song)) % 16 < 3          # the floor: moved by the camera, once a song frame
        f[150:, stripes, :3] = 128
        f[150:, stripes, 3] = 255
        x = 20 + t + cam                                                    # the body, shaded: every pixel of it changes
        f[20:80, x:x + 24, 0] = ramp
        f[20:80, x:x + 24, 1] = ramp
        f[20:80, x:x + 24, 2] = ramp
        f[20:80, x:x + 24, 3] = 255
        if cloth:
            c = 160 + 3 * (k % 30) - cam                                    # back to the left every 30 steps
            for ch in range(3):
                f[90:130, c:c + 40, ch] = shade
            f[90:130, c:c + 40, 3] = 255
        p.stdin.write(f.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg could not write %s" % path)


def every(period, residue, frames, start=0):
    return set(range(start + (residue - start) % period, frames, period))


def answer(argv):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = mv_look.main(argv)
    text = stream.getvalue()
    text.encode("ascii")
    return code, json.loads(text)


def luma(mp4, size=SIZE):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout
    w, h = size
    return [numpy.frombuffer(raw[i * w * h:(i + 1) * w * h], dtype=numpy.uint8).reshape(h, w) for i in range(len(raw) // (w * h))]


def digests(frames):
    """the frames as SHA-256: unittest's diff of two lists of frame bytes runs for many minutes when they differ (review of
    fold-phase: a broken fold then looked like a hung test)"""
    return [hashlib.sha256(f.tobytes()).hexdigest() for f in frames]


def half_covered(frame, row, a=150, b=None):
    """the pixels of a row that are neither the black stage nor the white cloth: the edges of a copy seen through another"""
    line = frame[row, a:b].astype(int)
    return int(((line > 64) & (line < 192)).sum())


def solid(frame, row=CLOTH_ROW, a=150):
    """the pixels of the cloth's row that are fully white: its 40 px when it shows once"""
    return int((frame[row, a:].astype(int) >= 192).sum())


@unittest.skipUnless(mv_look and FFMPEG, "needs numpy, Pillow, ffmpeg and ffprobe")
class PhysicsAlignRenderTest(unittest.TestCase):
    """the real tools/mv_look.py and ffmpeg on synthetic dancers"""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.look = os.path.join(cls.folder, "look.json")
        with open(cls.look, "w", encoding="utf-8") as f:
            json.dump(FLAT_LOOK, f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def dancer(self, name, rate, frames, steps, **kw):
        path = os.path.join(self.folder, name + ".avi")
        if not os.path.exists(path):
            cloth_dancer(path, rate, frames, steps, **kw)
        return path

    def fold(self, fg, name, subframes, *extra):
        out = os.path.join(self.folder, name + ".mp4")
        code, result = answer(["render", fg, self.look, out, "--work", os.path.join(self.folder, "work_" + name),
                               "--subframes", str(subframes), "--shutter", "0.5"] + list(extra))
        self.assertEqual(code, 0, result)
        return luma(out), result

    def test_the_cloth_shows_twice_in_the_default_fold_and_once_aligned_at_every_phase(self):
        for residue in range(4):
            with self.subTest(residue=residue):
                fg = self.dancer("r%d" % residue, 240, 96, every(4, residue, 96))
                default, plain = self.fold(fg, "r%d_default" % residue, 8)
                aligned, result = self.fold(fg, "r%d_aligned" % residue, 8, "--physics-align")
                self.assertEqual(len(aligned), 12)
                self.assertEqual(len(default), 12)
                self.assertNotIn("physics", plain)
                # the window of 4 of 8 subframes holds one step of the physics: one copy of the cloth, nothing half covered
                self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 12, residue)
                self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])
                if residue:
                    # the default window (subframes 0 to 3) holds the step: the cloth shows at two places 3 px apart, with the
                    # weights 1:3, 2:2 or 3:1, so at least one of its edges is a band of 3 half covered pixels
                    self.assertTrue(all(half_covered(f, CLOTH_ROW) >= 3 for f in default),
                                    [half_covered(f, CLOTH_ROW) for f in default])
                else:
                    self.assertEqual([half_covered(f, CLOTH_ROW) for f in default], [0] * 12)
                    self.assertEqual(digests(aligned), digests(default))
                # the body is still blurred: 4 copies 1 px apart give its bright edge 3 half covered pixels
                self.assertTrue(all(half_covered(f, BODY_ROW, 0, 320) >= 2 for f in aligned))
                physics = result["physics"]
                self.assertEqual((physics["period"], physics["residue"]), (4, residue), physics)
                self.assertEqual(physics["segments"], [[0, residue, residue]])

    def test_the_floor_moved_by_the_camera_once_a_song_frame_is_not_taken_for_the_physics(self):
        # the cloth steps on residue 2; the floor (stripes over the whole width) moves on residue 0 of 8
        fg = self.dancer("r2", 240, 96, every(4, 2, 96))
        code, result = answer(["phase", fg, "--subframes", "8", "--shutter", "0.5"])
        self.assertEqual(code, 0, result)
        self.assertEqual((result["period"], result["residue"], result["segments"]), (4, 2, [[0, 2, 2]]), result)

    def test_a_dancer_whose_physics_does_not_move_keeps_the_window_of_before(self):
        fg = self.dancer("still", 240, 96, set(), cloth=False)
        default, _ = self.fold(fg, "still_default", 8)
        aligned, result = self.fold(fg, "still_aligned", 8, "--physics-align")
        self.assertIsNone(result["physics"]["residue"], result)
        self.assertEqual(result["physics"]["segments"], [[0, None, 0]])
        self.assertEqual(digests(aligned), digests(default))

    def test_480_fps_holds_one_step_in_8_of_16_subframes(self):
        fg = self.dancer("r5_480", 480, 128, every(8, 5, 128))
        default, _ = self.fold(fg, "r5_480_default", 16)
        aligned, result = self.fold(fg, "r5_480_aligned", 16, "--physics-align")
        self.assertEqual(len(aligned), 8)
        self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 8)
        self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])
        # the default window (subframes 0 to 7) holds the step on 5: copies 3 px apart at 5:3
        self.assertTrue(all(half_covered(f, CLOTH_ROW) >= 3 for f in default), [half_covered(f, CLOTH_ROW) for f in default])
        self.assertEqual((result["physics"]["period"], result["physics"]["residue"]), (8, 5))
        # the body is still blurred: 8 copies 1 px apart
        self.assertTrue(all(half_covered(f, BODY_ROW, 0, 320) >= 4 for f in aligned))

    def test_960_fps_holds_one_step_in_16_of_32_subframes(self):
        # the rate of the fast spans (mv_chunks --fast-fps 960): the physics still steps 60 times a second, every 16 frames
        fg = self.dancer("r11_960", 960, 256, every(16, 11, 256))
        default, _ = self.fold(fg, "r11_960_default", 32)
        aligned, result = self.fold(fg, "r11_960_aligned", 32, "--physics-align")
        self.assertEqual(len(aligned), 8)
        self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 8)
        self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])
        self.assertTrue(all(half_covered(f, CLOTH_ROW) >= 3 for f in default), [half_covered(f, CLOTH_ROW) for f in default])
        self.assertEqual((result["physics"]["period"], result["physics"]["residue"]), (16, 11))
        self.assertTrue(all(half_covered(f, BODY_ROW, 0, 320) >= 4 for f in aligned))

    def test_60_fps_takes_2_of_4_subframes_within_one_step(self):
        # the physics steps once in every 4 subframes: only residue 1 puts it inside the default window (subframes 0 and 1)
        for residue, shift in ((1, 1), (2, 0)):
            with self.subTest(residue=residue):
                fg = self.dancer("r%d" % residue, 240, 96, every(4, residue, 96))
                default, _ = self.fold(fg, "r%d_60_default" % residue, 4)
                aligned, result = self.fold(fg, "r%d_60_aligned" % residue, 4, "--physics-align")
                self.assertEqual(len(aligned), 24)
                self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 24)
                self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])
                self.assertEqual(result["physics"]["segments"], [[0, residue, shift]])
                if shift == 0:
                    self.assertEqual(digests(aligned), digests(default))
                else:
                    self.assertTrue(all(half_covered(f, CLOTH_ROW) >= 3 for f in default))

    def test_a_phase_that_changes_inside_the_file_is_followed(self):
        steps = every(4, 1, 128) | every(4, 3, 256, start=128)
        fg = self.dancer("slip", 240, 256, steps)
        aligned, result = self.fold(fg, "slip_aligned", 8, "--physics-align")
        self.assertEqual(result["physics"]["segments"], [[0, 1, 1], [16, 3, 3]], result["physics"])
        self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 32)
        self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])

    def test_a_camera_that_moves_the_cloth_too_does_not_hide_the_step_next_to_it(self):
        # the camera moves everything (the shaded cloth too) on subframe 0 of every frame of the song; the physics steps next
        # to it on 1 (residue 1) or on 7 (residue 3): every pixel of the cloth then changes on two frames in a row, none alone
        for residue in (1, 3):
            with self.subTest(residue=residue):
                fg = self.dancer("pan_r%d" % residue, 240, 128, every(4, residue, 128), pan=4, noise=300)
                code, result = answer(["phase", fg, "--subframes", "8"])
                self.assertEqual(code, 0, result)
                self.assertEqual(result["segments"], [[0, residue, residue]], result)
                self.assertEqual(result["residues"], [residue] * 4, result)

    def test_an_excerpt_is_read_as_the_fold_reads_it(self):
        # the chunk's file starts at 10 s of the song; the excerpt from 10.408333 s starts on its 98th frame, 2 past a step of the
        # physics (every 4th frame from frame 3).  Read from the start of the file, the steps would be on residue 3 of the fold's
        # frames and the window would take them in
        fg = self.dancer("r3_long", 240, 192, every(4, 3, 192))
        code, whole = answer(["phase", fg, "--subframes", "8", "--offset", "10.0"])
        self.assertEqual((code, whole["residue"]), (0, 3), whole)
        aligned, result = self.fold(fg, "r3_excerpt", 8, "--physics-align", "--offset", "10.0", "--from", "10.408333",
                                    "--to", "10.808333")
        self.assertEqual(len(aligned), 12)
        self.assertNotEqual(result["physics"]["residue"], 3, result["physics"])
        self.assertEqual([half_covered(f, CLOTH_ROW) for f in aligned], [0] * 12)
        self.assertTrue(all(abs(solid(f) - 40) <= 1 for f in aligned), [solid(f) for f in aligned])


@unittest.skipUnless(mv_look, "needs numpy and Pillow")
class PhysicsAlignArgvTest(unittest.TestCase):
    """what --physics-align changes in the argv: the frames the fold picks, and nothing else"""

    def argv(self, **kw):
        look = mv_look.merge_look({"flares": [44.467], "beams": {"loop_seconds": 27.428571, "cycles": [2, 3]}})
        return mv_look.ffmpeg_command("C:/out/v.avi", "C:/out/v.mp4", "W/plate.png", "W/light/light_%05d.png", look, (1280, 720), 30,
                                      flare_pattern="W/flare/flare_%05d.png", flare_frames=12, start=1334 / 30.0,
                                      duration=406 / 30.0, offset=1214 / 30.0, subframes=8, shutter=0.5, light_frames=823, **kw)

    def test_no_shift_is_the_argv_of_before(self):
        self.assertEqual(self.argv(shifts=[(0, 0)]), self.argv())
        self.assertEqual(self.argv(shifts=None), self.argv())
        # and that argv picks what main f5991b3 picks: subframe 3 of every 8 (ThirtyArgvTest holds main's whole argv)
        self.assertIn("select='eq(mod(n,8),3)'", self.argv()[self.argv().index("-filter_complex") + 1])

    def test_a_shift_changes_the_picked_frames_only(self):
        before, after = self.argv(), self.argv(shifts=[(0, 2)])
        self.assertEqual(len(before), len(after))
        differ = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(differ), 1)
        self.assertEqual(before[differ[0]].replace("select='eq(mod(n,8),3)'", "select='eq(mod(n,8),5)'"), after[differ[0]])

    def test_the_scan_reads_the_frames_the_fold_reads(self):
        fold = self.argv()
        scan = mv_look.dancer_input("C:/out/v.avi", 30, 8, 1334 / 30.0, 406 / 30.0, 1214 / 30.0)
        at = fold.index("C:/out/v.avi") + 1
        self.assertEqual([a for a in fold[:at] if a != "-y"][-len(scan):], scan)
        self.assertEqual(scan, ["-ss", "4.000", "-t", "13.533", "-r", "240", "-i", "C:/out/v.avi"])


@unittest.skipUnless(mv_look, "needs numpy and Pillow")
class PhysicsShiftTest(unittest.TestCase):
    """the window of every output frame: the first subframe it starts on, for the residue of the steps of the physics"""

    def windows_hold_no_step(self, subframes, taken, period, residue, shift, frames=64):
        steps = every(period, residue, frames * subframes)
        return all(not any(f * subframes + shift + j in steps for j in range(1, taken)) for f in range(frames))

    def test_every_residue_has_a_window_within_one_step_when_the_shutter_is_one_step_long(self):
        for subframes, taken, period in ((8, 4, 4), (16, 8, 8), (4, 2, 4), (4, 2, 2), (8, 4, 8)):
            for residue in range(period):
                shift = mv_look.window_shift(residue, subframes, taken, period)
                self.assertTrue(0 <= shift <= subframes - taken, (subframes, taken, period, residue, shift))
                self.assertTrue(self.windows_hold_no_step(subframes, taken, period, residue, shift),
                                (subframes, taken, period, residue, shift))
                # and none earlier would do: the window moves no further than it must
                self.assertFalse(any(self.windows_hold_no_step(subframes, taken, period, residue, s) for s in range(shift)))

    def test_no_residue_keeps_the_window_of_before(self):
        self.assertEqual(mv_look.window_shift(None, 8, 4, 4), 0)

    def test_a_shutter_longer_than_a_step_takes_the_window_with_the_fewest_steps(self):
        # 8 of 8 subframes at 240 fps: two steps inside whatever the shift (there is only one)
        self.assertEqual(mv_look.window_shift(2, 8, 8, 4), 0)
        # 6 of 8: one step inside at best
        shift = mv_look.window_shift(1, 8, 6, 4)
        steps = every(4, 1, 64)
        self.assertEqual(sum(1 for j in range(1, 6) if shift + j in steps), 1)


@unittest.skipUnless(mv_look, "needs numpy and Pillow")
class PhysicsReadingTest(unittest.TestCase):
    """the reading itself, on counts made by hand: which pixels are lone, which windows cannot tell, and how the windows that
    cannot tell (the cloth at rest) are filled.  Review of fold-phase: none of these rules failed a test when broken"""

    def test_a_pixel_that_moves_on_one_frame_alone_is_lone_and_one_that_moves_on_two_in_a_row_is_not(self):
        a = numpy.zeros((1, 1, 4), numpy.uint8)
        b, c = a.copy(), a.copy()
        b[0, 0, 0], c[0, 0, 0] = 100, 200
        self.assertEqual(mv_look.lone_counts([a, a, b, b, b]), ([0, 0, 1, 0, 0], [0, 0, 1, 0, 0]))
        # moved into frame 1 and into frame 2: lone on neither, half lone (still on one side) on both
        self.assertEqual(mv_look.lone_counts([a, b, c, c, c]), ([0, 0, 0, 0, 0], [0, 1, 1, 0, 0]))

    def test_a_window_whose_two_best_residues_tie_cannot_tell(self):
        # two song frames of 8 subframes (the step every 4th), 4 times: residues 1 and 2 as lone as each other
        self.assertEqual(mv_look.physics_residues([0, 30, 30, 0, 0, 30, 30, 0] * 4, 4, 32), [None])
        self.assertEqual(mv_look.physics_residues([0, 90, 30, 0, 0, 90, 30, 0] * 4, 4, 32), [1])

    def test_a_window_with_hardly_any_lone_pixel_cannot_tell(self):
        self.assertEqual(mv_look.physics_residues([0, 1, 0, 0, 0, 1, 0, 0] * 4, 4, 32), [None])

    def test_windows_before_the_first_one_that_can_tell_take_its_residue(self):
        # as p2_240 of the branch's e2 (window 0 could not tell): left unaligned, its frames would fold the step in
        self.assertEqual(mv_look.physics_segments([None, None, 3, 3], 32, 8), [(0, 3)])

    def test_a_window_that_cannot_tell_takes_the_residue_before_it(self):
        self.assertEqual(mv_look.physics_segments([1, 1, None, 1, None, None, 1], 32, 8), [(0, 1)])

    def test_one_window_between_two_that_agree_takes_theirs(self):
        self.assertEqual(mv_look.physics_segments([2, 2, 0, 2, 2], 32, 8), [(0, 2)])

    def test_a_change_held_for_two_windows_starts_a_segment_at_its_first_window(self):
        self.assertEqual(mv_look.physics_segments([1, 1, 3, 3, 3], 32, 8), [(0, 1), (8, 3)])
        # at 60 fps (4 subframes) a window of 32 frames of the dancer is 8 output frames
        self.assertEqual(mv_look.physics_segments([1, 1, 3, 3, 3], 32, 4), [(0, 1), (16, 3)])


@unittest.skipUnless(mv_look, "needs numpy and Pillow")
class PhysicsAlignCommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.look = os.path.join(self.folder, "look.json")
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump(FLAT_LOOK, f)
        self.fg = os.path.join(self.folder, "fg.avi")
        open(self.fg, "wb").close()

    def test_aligning_needs_subframes(self):
        code, result = answer(["render", self.fg, self.look, os.path.join(self.folder, "o.mp4"), "--size", "320x180", "--fps", "30",
                               "--physics-align"])
        self.assertEqual(code, 2)
        self.assertIn("--physics-align", result["error"]["message"])

    @unittest.skipUnless(FFMPEG, "needs ffmpeg")
    def test_a_dancer_ffmpeg_cannot_read_stops_the_aligned_fold_with_its_message(self):
        with open(self.fg, "wb") as f:
            f.write(b"RIFF\0\0\0\0AVI not really")
        code, result = answer(["render", self.fg, self.look, os.path.join(self.folder, "o.mp4"), "--size", "320x180", "--fps", "240",
                               "--subframes", "8", "--physics-align", "--work", os.path.join(self.folder, "w")])
        self.assertEqual(code, 1, result)
        message = result["error"]["message"]
        self.assertIn("could not read the dancer for its physics", message)
        self.assertGreater(len(message.split("): ", 1)[-1].strip()), 10, message)        # with what ffmpeg said
        self.assertNotIn("4294967", message)                                             # its exit code as Windows gives it
        self.assertFalse(os.path.exists(os.path.join(self.folder, "o.mp4")))

    def test_the_window_needs_whole_steps_of_the_physics_in_every_output_frame(self):
        # 240 fps folded by 5 (48 fps) or 120 fps folded by 3 (40 fps): the step falls on another subframe in every output
        # frame, and no one shift holds it out of all their windows
        for fps, subframes in ((48, 5), (40, 3), (80, 3)):
            code, result = answer(["render", self.fg, self.look, os.path.join(self.folder, "o.mp4"), "--size", "320x180", "--fps",
                                   str(fps * subframes), "--subframes", str(subframes), "--physics-align"])
            self.assertEqual(code, 2, (fps, subframes, result))
            self.assertIn("--physics-align", result["error"]["message"])
        for fps, subframes in ((30, 8), (60, 4), (30, 16), (60, 8), (30, 4), (60, 2)):
            mv_look.check_physics_align(fps, subframes)                                 # these fold whole steps

    def test_an_excerpt_from_before_the_dancer_is_refused_before_it_is_read(self):
        code, result = answer(["phase", self.fg, "--subframes", "8", "--fps", "240", "--size", "320x180", "--offset", "10",
                               "--from", "9.5", "--to", "10.5"])
        self.assertEqual(code, 2, result)
        self.assertIn("before the dancer's file", result["error"]["message"])

    def test_aligning_needs_a_rate_of_whole_steps_of_the_physics(self):
        # 90 fps folded by 3: the physics (60 a second) steps every 1.5 frames, no window can follow it
        code, result = answer(["render", self.fg, self.look, os.path.join(self.folder, "o.mp4"), "--size", "320x180", "--fps", "90",
                               "--subframes", "3", "--physics-align"])
        self.assertEqual(code, 2)
        self.assertIn("60", result["error"]["message"])
        self.assertFalse(os.path.exists(os.path.join(self.folder, "o.mp4")))


@unittest.skipUnless(mv_look, "needs numpy and Pillow")
class AlignPhysicsScriptTest(unittest.TestCase):
    """tools/mv_chunks.py --align-physics: every fold of the driver gets --physics-align; without it the scripts are those of
    before, byte for byte"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def written(self, label, **kw):
        folder = os.path.join(self.tmp, label)
        summary = mv_chunks.write(mv_chunks.check_plan(dict(PLAN)), mv_chunks.plan_chunks(SPANS, 120), folder, "t", 240, 0.5, **kw)
        return summary, hashes(folder)

    def test_without_it_the_scripts_are_those_of_before(self):
        for out_fps, golden in ((30, GOLDEN_30), (60, GOLDEN_60)):
            self.assertEqual(self.written("off%d" % out_fps, out_fps=out_fps, align_physics=False)[1], golden["t"], out_fps)

    def test_every_fold_aligns_and_the_recipe_knows_it(self):
        for workers in (1, 2):
            summary, files = self.written("on%d" % workers, align_physics=True, workers=workers)
            with open(summary["driver"], encoding="utf-8-sig") as f:
                driver = f.read()
            folds = re.findall(r"Run-Chunk .* @\((.*)\)", driver)
            self.assertEqual(len(folds), 3, driver)
            self.assertTrue(all("'--physics-align'" in f for f in folds), folds)
            self.assertTrue(summary["align_physics"])
        plan = mv_chunks.check_plan(dict(PLAN))
        chunk = mv_chunks.plan_chunks(SPANS, lead=120)[1]
        on = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5, align_physics=True)
        off = mv_chunks.fold_args(plan, "t", chunk, 240, 0.5)
        self.assertEqual([a for a in on if a != "--physics-align"], off)
        self.assertNotEqual(mv_chunks.recipe(plan, "t", chunk, 240, 0.5, align_physics=True), mv_chunks.recipe(plan, "t", chunk, 240, 0.5))

    def test_a_rate_whose_physics_cannot_be_aligned_is_refused_before_mmd_renders(self):
        # mv_look refuses to align a dancer at 30 or 60 fps (no whole step of the physics in 2 frames or more); found by the
        # driver only after MMD had rendered chunk 0
        plan = mv_chunks.check_plan(dict(PLAN))
        chunks = mv_chunks.plan_chunks(SPANS, 120)
        for fps, out_fps in ((30, 30), (60, 30), (60, 60)):
            with self.assertRaises(ValueError, msg=(fps, out_fps)) as ctx:
                mv_chunks.write(plan, chunks, os.path.join(self.tmp, "x"), "t", fps, 0.5, out_fps=out_fps, align_physics=True)
            self.assertIn("--align-physics", str(ctx.exception))
        for fps, out_fps in ((120, 30), (240, 30), (480, 30), (120, 60), (240, 60), (480, 60)):
            mv_chunks.write(plan, chunks, os.path.join(self.tmp, "ok%d_%d" % (fps, out_fps)), "t", fps, 0.5, out_fps=out_fps,
                            align_physics=True)

    def test_the_summary_says_so_only_when_asked(self):
        self.assertNotIn("align_physics", self.written("off")[0])
        buf = io.StringIO()
        plan = os.path.join(self.tmp, "plan.json")
        with open(plan, "w", encoding="utf-8") as f:
            json.dump(PLAN, f)
        with contextlib.redirect_stdout(buf):
            code = mv_chunks.main([plan, os.path.join(self.tmp, "cli"), "--cuts", "100", "250", "--last", "299", "--align-physics"])
        result = json.loads(buf.getvalue())
        self.assertEqual((code, result["align_physics"]), (0, True), result)


# a stand-in for MMD whose AVI has a cloth: tests/test_mv_chunks.py's FAKE_MMD, with rows 4 to 14 black but for a white box 20 px
# wide that moves 2 px on every 4th subframe at residue 2 of the AVI (as MMD's physics at 240 fps) and comes back to the left
# every 12 steps, when a motion's path holds "_cloth"
FAKE_CLOTH = FAKE_MMD.replace(
    'if any("_v2" in l[2] for l in lines if l[:2] == ["motion", "load"]):',
    'if any("_cloth" in l[2] for l in lines if l[:2] == ["motion", "load"]):\n'
    '    x = "8+2*mod(floor((N+2)/4),12)"\n'
    '    box = "255*between(X,%s,%s+19)" % (x, x)\n'
    '    r, g, b = ("if(between(Y,4,14),%s,%s)" % (box, e) for e in (r, g, b))\n'
    'if any("_v2" in l[2] for l in lines if l[:2] == ["motion", "load"]):')
assert FAKE_CLOTH != FAKE_MMD


@unittest.skipUnless(WINDOWS and FFMPEG and mv_look, "needs Windows PowerShell, ffmpeg, numpy and Pillow")
class AlignPhysicsEndToEndTest(unittest.TestCase):
    """the driver, python, the real tools/mv_look.py and ffmpeg with MMD replaced by a stand-in whose cloth steps on residue 2:
    with --align-physics every chunk folds subframes 2 to 5 and the cloth shows once"""
    W, H = 64, 36

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp.replace("\\", "/")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(os.path.join(fake, "mmd_cli"))
        os.makedirs(os.path.join(fake, "tools"))
        open(os.path.join(fake, "mmd_cli", "__init__.py"), "w").close()
        with open(os.path.join(fake, "mmd_cli", "__main__.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_CLOTH)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("mv_look.py", "mv_text.py"):
            shutil.copyfile(os.path.join(root, "tools", name), os.path.join(fake, "tools", name))
        self.look = self.base + "/look.json"
        with open(self.look, "w", encoding="utf-8") as f:
            json.dump(FLAT_LOOK, f)

    def render(self, out, **kw):
        plan = mv_chunks.check_plan({"mmd": "C:/MMD/MikuMikuDance.exe", "model": "C:/MMD/model.pmx", "motions": ["C:/work/dance_cloth.vmd"],
                                     "camera": "C:/work/camera.vmd", "look": self.look, "out": self.base + "/" + out,
                                     "scripts": self.base + "/scripts_" + out, "mmd_cli": self.base + "/fake", "size": [self.W, self.H]})
        summary = mv_chunks.write(plan, mv_chunks.plan_chunks(mv_chunks.spans_from_cuts([40, 90], 119), lead=30),
                                  self.base + "/scripts_" + out, "t", 240, 0.5, **kw)
        wrapper = os.path.join(self.tmp, "run_%s.ps1" % out)
        with open(wrapper, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("%s\n& %s\nexit $LASTEXITCODE\n" % (PARSE_FIRST % mv_chunks._ps(summary["driver"]), mv_chunks._ps(summary["driver"])))
        code, text = run_powershell(wrapper, timeout=600)
        self.assertEqual(code, 0, text)
        return summary

    def cloth_rows(self, mp4):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
        n = self.W * self.H
        return [numpy.frombuffer(raw[i * n:(i + 1) * n], dtype=numpy.uint8).reshape(self.H, self.W)[9] for i in range(len(raw) // n)]

    def test_every_chunk_folds_one_step_of_the_cloth(self):
        plain = self.render("plain")
        aligned = self.render("aligned", align_physics=True)
        rows = self.cloth_rows(aligned["joined"])
        self.assertEqual(len(rows), 120)
        half = [int(((r.astype(int) > 64) & (r.astype(int) < 192)).sum()) for r in rows]
        self.assertEqual(half, [0] * 120)
        before = [int(((r.astype(int) > 64) & (r.astype(int) < 192)).sum()) for r in self.cloth_rows(plain["joined"])]
        self.assertTrue(all(h >= 2 for h in before), before)
        for i in range(3):
            with open("%s/aligned/t_%02d.mp4.look.json" % (self.base, i), encoding="utf-8-sig") as f:
                said = json.loads(f.read())
            self.assertEqual(said["physics"]["segments"], [[0, 2, 2]], said)


if __name__ == "__main__":
    unittest.main()
