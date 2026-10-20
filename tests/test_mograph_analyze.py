"""tools/mograph_analyze.py: the motion graphics of a video in numbers: how its shots change (cuts, flashes, fades,
dissolves, zoom punches, shakes, glitch frames, colour flashes) and when against the beat, and the graphic things on
its frames (particles and bokeh, straight lines).

Every measure is tried on frames made for it, whose answer is known from how they were made.
"""
import importlib.util
import math
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
    import scipy.ndimage as ndi
    import cv2
except ImportError:                       # the tool needs numpy, scipy and OpenCV; the rest of the suite does not
    np = None


def load_tool():
    spec = importlib.util.spec_from_file_location("mograph_analyze", os.path.join(ROOT, "tools", "mograph_analyze.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MG = load_tool() if np is not None else None
NEEDS = "needs numpy, scipy and OpenCV"
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def scene(seed, h=72, w=128):
    """a smooth coloured picture (RGB 0..1) with detail at several sizes: one picture in all three colours (as a
    picture's edges are), each tinted a little differently"""
    rng = np.random.default_rng(seed)
    f = ndi.gaussian_filter(rng.standard_normal((h, w)), 4.0, mode="wrap") + \
        0.5 * ndi.gaussian_filter(rng.standard_normal((h, w)), 1.2, mode="wrap")
    f = f / np.abs(f).max()
    out = np.zeros((h, w, 3))
    for c in range(3):
        tint = ndi.gaussian_filter(rng.standard_normal((h, w)), 6.0, mode="wrap")
        out[..., c] = 0.5 + 0.3 * f + 0.08 * tint / np.abs(tint).max()
    return np.clip(out, 0, 1)


def zoomed(img, s, dx=0.0, dy=0.0):
    """img scaled by s about its middle and moved by dx dy px (edges replicated)"""
    h, w = img.shape[:2]
    m = np.float32([[s, 0, (1 - s) * w / 2.0 + dx], [0, s, (1 - s) * h / 2.0 + dy]])
    return cv2.warpAffine(img.astype(np.float32), m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT).astype(np.float64)


def dancer(img, cx, cy, s=1.0, seed=3):
    """a textured upright ellipse (a dancer, about an eighth of a 128 x 72 frame) drawn over img at (cx, cy), s times
    as large: what moves on its own in front of the picture"""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    inside = ((xx - cx) / (15.0 * s)) ** 2 + ((yy - cy) / (24.0 * s)) ** 2 <= 1.0
    tex = ndi.gaussian_filter(rng.standard_normal((h, w)), 1.0)
    tex = 0.6 + 0.35 * tex / np.abs(tex).max()
    # the texture rides with the dancer: read it about her middle
    sy = np.clip(np.round((yy - cy) / s + 36).astype(int), 0, h - 1)
    sx = np.clip(np.round((xx - cx) / s + 64).astype(int), 0, w - 1)
    out = img.copy()
    for c, k in enumerate((1.0, 0.85, 0.75)):
        out[..., c] = np.where(inside, tex[sy, sx] * k, img[..., c])
    return out


@unittest.skipUnless(MG, NEEDS)
class EventsTest(unittest.TestCase):
    fps = 30

    def run_frames(self, frames, beats=None):
        return MG.events_of(np.array(frames), self.fps, beats=beats)

    def test_a_cut_is_a_cut_and_no_dissolve(self):
        a, b = scene(1), scene(2)
        frames = [zoomed(a, 1.0, dx=0.2 * i) for i in range(45)] + [zoomed(b, 1.0, dx=0.2 * i) for i in range(45)]
        ev = self.run_frames(frames)
        self.assertEqual([e["frame"] for e in ev["cuts"]], [45])
        self.assertEqual(ev["dissolves"], [])

    def test_a_dissolve_is_a_dissolve_and_no_cut(self):
        a, b = scene(3), scene(4)
        frames = []
        for i in range(90):
            k = min(1.0, max(0.0, (i - 40) / 10.0))                 # 10 frames from a to b
            frames.append((1 - k) * a + k * b)
        ev = self.run_frames(frames)
        self.assertEqual(ev["cuts"], [])
        self.assertEqual(len(ev["dissolves"]), 1)
        self.assertAlmostEqual(ev["dissolves"][0]["frame"], 45, delta=3)
        self.assertAlmostEqual(ev["dissolves"][0]["frames"], 10, delta=4)

    def test_light_dimming_or_a_line_of_text_fading_in_is_no_dissolve(self):
        a = scene(12)
        dim = [a * (1.0 - 0.35 * min(1.0, max(0.0, (i - 40) / 10.0))) for i in range(90)]
        text = []
        for i in range(90):
            f = a.copy()
            k = min(1.0, max(0.0, (i - 40) / 8.0))
            f[56:64, 30:98] = f[56:64, 30:98] * (1 - k) + k                 # a white line of text fading in, low in the frame
            text.append(f)
        self.assertEqual(self.run_frames(dim)["dissolves"], [])
        self.assertEqual(self.run_frames(text)["dissolves"], [])

    def test_a_colourful_picture_is_no_glitch(self):
        a = scene(13)
        frames = []
        for i in range(60):
            f = zoomed(a, 1.1, dx=0.3 * i)
            f[10:40, 20:50] = [0.95, 0.1, 0.1]                              # a red thing next to a blue one
            f[10:40, 50:80] = [0.1, 0.2, 0.95]
            frames.append(f)
        self.assertEqual(self.run_frames(frames)["glitches"], [])

    def test_a_fade_to_black_and_back(self):
        a = scene(5)
        frames = []
        for i in range(90):
            k = 1.0
            if 30 <= i < 38:
                k = 1.0 - (i - 30) / 8.0
            elif 38 <= i < 44:
                k = 0.0
            elif 44 <= i < 52:
                k = (i - 44) / 8.0
            frames.append(a * k)
        ev = self.run_frames(frames)
        self.assertEqual(len(ev["fades"]), 1)
        self.assertEqual(ev["fades"][0]["to"], "black")

    def test_a_quick_fade_of_a_bright_picture_is_a_fade_and_no_cut(self):
        # typorev: each frame of a 10-frame fade of a bright picture changes as much as a cut (more than CUT_LEAST): read
        # as 4 cuts, and the cut next to the fade threw the fade out
        a = np.clip(scene(22) * 0.6 + 0.4, 0, 1)
        frames = []
        for i in range(90):
            k = 1.0
            if 30 <= i < 40:
                k = 1.0 - (i - 29) / 10.0
            elif 40 <= i < 48:
                k = 0.0
            elif 48 <= i < 58:
                k = (i - 47) / 10.0
            frames.append(a * k)
        ev = self.run_frames(frames)
        self.assertEqual(ev["cuts"], [])
        self.assertEqual([f["to"] for f in ev["fades"]], ["black"])
        # out of a black frame into a picture is a cut
        frames = [a * 0.0] * 30 + [a] * 60
        self.assertEqual([e["frame"] for e in self.run_frames(frames)["cuts"]], [30])

    def test_a_zoom_punch_and_a_smooth_zoom(self):
        a = scene(6)
        punch = []
        for i in range(90):
            s = 1.0
            if 40 <= i < 42:
                s = 1.0 + 0.09 * (i - 39)                            # 1.09, 1.18 in two frames
            elif 42 <= i < 48:
                s = 1.18 - 0.03 * (i - 41)                           # back over six
            punch.append(zoomed(a, s))
        smooth = [zoomed(a, 1.0 + 0.18 * i / 89.0) for i in range(90)]
        self.assertEqual(len(self.run_frames(punch)["punches"]), 1)
        self.assertEqual(self.run_frames(smooth)["punches"], [])

    def test_a_shake(self):
        a = scene(7)
        rng = np.random.default_rng(1)
        shaky = [zoomed(a, 1.1, dx=rng.normal(0, 1.5), dy=rng.normal(0, 1.5)) for _ in range(90)]
        steady = [zoomed(a, 1.1, dx=0.1 * i) for i in range(90)]
        r_shaky = self.run_frames(shaky)["summary"]["shake.rms"]
        r_steady = self.run_frames(steady)["summary"]["shake.rms"]
        self.assertGreater(r_shaky, 5 * max(r_steady, 0.5))
        # 1.5 px a frame of 72 lines in each of x and y: about 1.5 * sqrt(2) * 10 = 21 px of 720 at a frame
        self.assertGreater(r_shaky, 8.0)

    def test_a_dancer_on_a_still_picture_is_no_shake(self):
        # typorev: our still front camera read a shake of 0.4 to 1.0 px from the dancer alone; the shake is the camera's
        a = scene(14)
        rng = np.random.default_rng(2)
        x, y = 64.0, 40.0
        frames = []
        for _ in range(90):
            x = float(np.clip(x + rng.normal(0, 3.0), 30, 98))
            y = float(np.clip(y + rng.normal(0, 1.5), 28, 46))
            frames.append(dancer(a, x, y))
        r = self.run_frames(frames)
        self.assertLess(r["summary"]["shake.rms"], 1.0)
        self.assertEqual(r["punches"], [])

    def test_the_camera_shake_under_a_dancer(self):
        a = scene(15)
        rng = np.random.default_rng(3)
        jit = [(rng.normal(0, 1.0), rng.normal(0, 1.0)) for _ in range(90)]
        x, frames, alone = 64.0, [], []
        for i in range(90):
            x = float(np.clip(x + rng.normal(0, 3.0), 30, 98))
            f = zoomed(a, 1.1, dx=jit[i][0], dy=jit[i][1])
            alone.append(f)
            frames.append(dancer(f, x + jit[i][0], 40.0 + jit[i][1]))
        with_dancer = self.run_frames(frames)["summary"]["shake.rms"]
        without = self.run_frames(alone)["summary"]["shake.rms"]
        self.assertGreater(without, 8.0)
        self.assertAlmostEqual(with_dancer / without, 1.0, delta=0.2)

    def test_a_dancer_coming_near_is_no_punch(self):
        a = scene(16)
        frames = []
        for i in range(90):
            s = 1.0
            if 40 <= i < 44:
                s = 1.0 + 0.5 * (i - 39) / 4.0                       # 1.5 times as large in four frames
            elif 44 <= i < 60:
                s = 1.5
            frames.append(dancer(a, 64.0, 40.0, s=s))
        self.assertEqual(self.run_frames(frames)["punches"], [])

    def test_a_short_bright_shot_between_two_cuts_is_two_cuts_not_a_flash(self):
        # typorev: RE:odo 1187 and 2282, a close-up of blond hair for a few frames between two darker shots, were read
        # as flashes and their cuts lost (the frames of a flash are left out of the cuts)
        a, b, c = scene(17) * 0.5, np.clip(scene(18) * 0.6 + 0.4, 0, 1), scene(19) * 0.5
        frames = [a] * 40 + [b] * 6 + [c] * 44
        ev = self.run_frames(frames)
        self.assertEqual(ev["flashes"], [])
        self.assertEqual([e["frame"] for e in ev["cuts"]], [40, 46])
        # a white flash on one picture stays a flash, and no cut
        d = scene(20) * 0.5
        frames = [d] * 40 + [np.clip(d + 0.5, 0, 1)] * 3 + [d] * 47
        ev = self.run_frames(frames)
        self.assertEqual(len(ev["flashes"]), 1)
        self.assertEqual(ev["cuts"], [])
        # and a white flash over a cut (the picture washed out towards white) stays a flash
        e = scene(23) * 0.5
        frames = [d] * 40 + [d + 0.8 * (1 - d)] * 2 + [e + 0.8 * (1 - e)] * 2 + [e] * 46
        self.assertEqual(len(self.run_frames(frames)["flashes"]), 1)

    def test_cuts_kept_before_the_beat_are_locked_to_it(self):
        # typorev: the references' cuts keep 2 to 3 frames before the beat; within a frame of it they were at chance
        fps = 30.0
        beats = [k * 0.5 for k in range(1, 120)]                     # 120 bpm
        early = [b - 2.0 / fps for b in beats[::4]]                  # every fourth beat, 2 frames early
        share, chance, (R, p, off) = MG._on_beat(early, beats, fps)
        self.assertEqual(share, 0.0)
        self.assertGreater(R, 0.95)
        self.assertLess(p, 1e-6)
        self.assertAlmostEqual(off, -2.0 / fps, delta=0.005)
        rng = np.random.default_rng(4)
        loose = sorted(rng.uniform(1.0, 58.0, 30).tolist())
        _, _, (R2, p2, _) = MG._on_beat(loose, beats, fps)
        self.assertLess(R2, 0.4)
        self.assertGreater(p2, 0.01)

    def test_glitch_frames(self):
        a = scene(8)
        frames = []
        for i in range(90):
            f = a.copy()
            if i in (20, 21, 50):
                f[..., 0] = np.roll(a[..., 0], 3, axis=1)            # red 3 px right, blue 3 px left
                f[..., 2] = np.roll(a[..., 2], -3, axis=1)
            frames.append(f)
        ev = self.run_frames(frames)
        self.assertEqual(sorted(e["frame"] for e in ev["glitches"]), [20, 21, 50])

    def test_a_colour_flash(self):
        a = scene(9) * 0.6 + 0.2
        frames = []
        for i in range(90):
            f = a.copy()
            if 30 <= i < 33:
                f = 0.5 * f + 0.5 * np.array([1.0, 0.1, 0.7])         # a magenta wash for three frames
            frames.append(f)
        ev = self.run_frames(frames)
        self.assertEqual(len(ev["colour_flashes"]), 1)
        self.assertEqual(ev["cuts"], [])

    def test_events_on_the_beat(self):
        a, b = scene(10), scene(11)
        frames = []
        for i in range(300):
            frames.append(zoomed(a if (i // 30) % 2 == 0 else b, 1.0, dx=0.05 * (i % 30)))
        beats = [k / 2.0 for k in range(21)]                         # 120 bpm: a beat every 15 frames
        ev = self.run_frames(frames, beats=beats)
        self.assertEqual(len(ev["cuts"]), 9)                         # every 30 frames
        self.assertAlmostEqual(ev["summary"]["cuts.on_beat"], 1.0)
        self.assertLess(ev["summary"]["cuts.on_beat_chance"], 0.3)
        # the floor of the rate of cuts: 4 in the first half, 5 in the second (of 10 s), half the difference a minute
        self.assertAlmostEqual(ev["floor"]["cuts.per_min"], abs(4 / (5 / 60.0) - 5 / (5 / 60.0)) / 2.0, delta=0.01)


@unittest.skipUnless(MG and FFMPEG, NEEDS + ", ffmpeg and ffprobe")
class EventsVideoTest(unittest.TestCase):
    def write(self, path, frames, fps=30):
        h, w = frames[0].shape[:2]
        argv = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r", str(fps),
                "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-colorspace", "bt709", "-color_primaries",
                "bt709", "-color_trc", "bt709", "-color_range", "tv", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                "-pix_fmt", "yuv420p", path]
        subprocess.run(argv, input=b"".join((np.clip(f, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes() for f in frames),
                       check=True)

    def test_a_narrow_video_reads_its_shake_in_the_same_px(self):
        # typorev: a 640 x 720 picture (our front camera) was read 128 x 72, stretched twice across: its sideways shake
        # read twice as large as the same shake of a 1280 x 720 picture
        rng = np.random.default_rng(5)
        big = ndi.zoom(scene(21, h=90, w=150), (10, 10, 1), order=1)[:900, :1500]
        big = np.clip(big + 0.15 * ndi.gaussian_filter(rng.standard_normal(big.shape[:2]), 3.0)[..., None], 0, 1)
        xs = [rng.normal(0, 6.0) for _ in range(60)]                    # px of 720 lines, across only
        wide = [big[90:810, int(110 + x):int(110 + x) + 1280] for x in xs]
        narrow = [f[:, 320:960] for f in wide]
        with tempfile.TemporaryDirectory() as tmp:
            pw, pn = os.path.join(tmp, "wide.mp4"), os.path.join(tmp, "narrow.mp4")
            self.write(pw, wide)
            self.write(pn, narrow)
            sw = MG.events_video(pw)["summary"]["shake.rms"]
            sn = MG.events_video(pn)["summary"]["shake.rms"]
        self.assertGreater(sw, 4.0)
        self.assertAlmostEqual(sn / sw, 1.0, delta=0.25)


@unittest.skipUnless(MG, NEEDS)
class ElementsTest(unittest.TestCase):
    def test_particles_and_bokeh(self):
        rng = np.random.default_rng(4)
        h, w = 720, 1280
        img = np.full((h, w), 0.08)
        yy, xx = np.mgrid[0:h, 0:w]
        dots = [(rng.uniform(40, w - 40), rng.uniform(40, h - 40)) for _ in range(40)]
        for x, y in dots:
            img += 0.7 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
        discs = [(rng.uniform(60, w - 60), rng.uniform(60, h - 60)) for _ in range(8)]
        for x, y in discs:
            r = np.hypot(xx - x, yy - y)
            img += 0.35 * np.clip((14.0 - r) / 2.0, 0, 1)
        rgb = np.repeat(np.clip(img, 0, 1)[..., None], 3, axis=2)
        p = MG.particles(rgb, unit=1.0, points=True)
        self.assertAlmostEqual(p["particle.count"], 48, delta=5)
        self.assertEqual(len(p["points"]), p["particle.count"])
        # each found spot lies on a drawn one
        for x, y, s in p["points"]:
            self.assertLess(min(math.hypot(x - a, y - b) for a, b in dots + discs), 4.0)
        self.assertAlmostEqual(p["particle.bokeh"], 8 / 48.0, delta=0.08)

    def test_thin_lines_are_no_particles(self):
        # our stage: a floor of thin light grid lines on a dark ground (each line read as a row of small spots)
        img = np.full((720, 1280, 3), 0.05)
        for x in range(0, 1280, 64):
            img[:, x:x + 2] = 0.45
        for k in range(12):
            cv2.line(img, (0, 400 + 25 * k), (1279, 380 + 27 * k), (0.4, 0.45, 0.5), 1)
        rng = np.random.default_rng(6)
        yy, xx = np.mgrid[0:720, 0:1280]
        for _ in range(10):                                         # and ten real spots away from the lines
            x, y = rng.uniform(20, 1260), rng.uniform(20, 380)
            x = 32 + 64 * int(x // 64)                              # between two upright lines
            img += 0.7 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))[..., None]
        p = MG.particles(np.clip(img, 0, 1), unit=1.0)
        self.assertAlmostEqual(p["particle.count"], 10, delta=2)

    def test_a_plain_picture_has_no_particles(self):
        rng = np.random.default_rng(5)
        img = np.full((720, 1280, 3), 0.3) + rng.normal(0, 0.005, (720, 1280, 3))
        self.assertEqual(MG.particles(np.clip(img, 0, 1), unit=1.0)["particle.count"], 0)

    def test_long_straight_lines(self):
        img = np.full((720, 1280, 3), 0.1)
        img[200:203, 100:1100] = 0.9                                # level
        img[100:650, 640:643] = 0.9                                 # upright
        cv2.line(img, (100, 650), (900, 300), (0.9, 0.9, 0.9), 3)   # slanted
        ln = MG.lines(img, unit=1.0)
        self.assertEqual(ln["lines.count"], 3)
        self.assertAlmostEqual(ln["lines.axis"], 2 / 3.0, delta=0.01)          # level or upright


def level(v, h=36, w=64):
    """a grey picture of signal level v (0..1, BT.1886: 200 x v^2.4 cd/m2 on the SDR display of BT.1702)"""
    return np.full((h, w, 3), float(v))


@unittest.skipUnless(MG, NEEDS)
class SafetyTest(unittest.TestCase):
    """the flashes of Rec. ITU-R BT.1702-3 (2023), Guideline 1: a flash is a pair of opposing changes of 20 cd/m2 or more
    where the darker image is below 160 cd/m2 (an SDR picture on a display of 200 cd/m2 white, BT.1886); a sequence of flashes
    is not permitted when the flashes at the same time cover more than 25 % of the screen and there are more than three (six
    changes) in any one second"""
    fps = 30

    def test_the_luminance_of_a_signal_level_is_that_of_the_recommendations_table(self):
        # Table 1 of BT.1702-3: 10-bit code values 400 (V 0.384) 20.06, 500 (0.498) 37.48, 860 (0.909) 158.93 cd/m2
        for code, cd in ((400, 20.06), (500, 37.48), (860, 158.93), (940, 200.0)):
            self.assertAlmostEqual(MG.screen_luminance((code - 64) / 876.0), cd, delta=0.05)

    def test_one_white_flash_over_the_whole_picture_is_one_flash_and_allowed(self):
        frames = [level(0.3)] * 20 + [level(0.8)] * 3 + [level(0.3)] * 20
        s = MG.safety_of(frames, self.fps)
        self.assertEqual(s["general"]["most_flashes_a_second"], 1)
        self.assertEqual(len(s["general"]["flashes"]), 1)
        self.assertAlmostEqual(s["general"]["flashes"][0]["area"], 1.0, delta=0.01)
        self.assertEqual(s["general"]["flashes"][0]["frame"], 20)                 # its leading edge
        self.assertAlmostEqual(s["general"]["flashes"][0]["cd"], 200 * (0.8 ** 2.4 - 0.3 ** 2.4), delta=0.5)
        self.assertFalse(s["general"]["harmful"])

    def test_a_strobe_over_the_whole_picture_is_harmful(self):
        frames = [level(0.2 if (i // 2) % 2 == 0 else 0.7) for i in range(60)]        # 7.5 flashes a second
        s = MG.safety_of(frames, self.fps)
        self.assertGreater(s["general"]["most_flashes_a_second"], 3)
        self.assertTrue(s["general"]["harmful"])

    def test_a_strobe_over_a_small_part_is_not(self):
        frames = []
        for i in range(60):
            img = level(0.2)
            if (i // 2) % 2:
                img[:10, :20] = 0.7                                 # 8.7 % of the picture
            frames.append(img)
        s = MG.safety_of(frames, self.fps)
        self.assertFalse(s["general"]["harmful"])
        self.assertLessEqual(s["general"]["most_flashes_a_second"], 0)            # never a quarter of the picture at once
        self.assertGreater(s["general"]["most_flashes_a_second_anywhere"], 3)

    def test_a_change_under_20_cd_is_no_flash(self):
        frames = [level(0.10 if (i // 2) % 2 == 0 else 0.30) for i in range(60)]    # 0.8 to 11.1 cd/m2
        s = MG.safety_of(frames, self.fps)
        self.assertEqual(s["general"]["flashes"], [])
        self.assertEqual(s["general"]["most_flashes_a_second_anywhere"], 0)

    def test_20_cd_is_the_edge(self):
        def strobe(a, b):
            return MG.safety_of([level(a if (i // 2) % 2 == 0 else b) for i in range(60)], self.fps)["general"]["harmful"]
        self.assertTrue(strobe(0.30, 0.49))                     # 11.0 to 36.1 cd/m2: 25
        self.assertFalse(strobe(0.30, 0.45))                    # 11.0 to 29.3 cd/m2: 18

    def test_a_darker_image_from_160_cd_is_left_to_the_hdr_rule(self):
        # 0.92 is 163 cd/m2 and 1.0 is 200: 37 apart, but the 20 cd/m2 rule is for a darker image below 160 (the 1/17 Michelson
        # contrast above it is for HDR programmes only)
        frames = [level(0.92 if (i // 2) % 2 == 0 else 1.0) for i in range(60)]
        self.assertFalse(MG.safety_of(frames, self.fps)["general"]["harmful"])
        frames = [level(0.88 if (i // 2) % 2 == 0 else 1.0) for i in range(60)]        # 147 cd/m2: below 160
        self.assertTrue(MG.safety_of(frames, self.fps)["general"]["harmful"])

    def test_a_fade_to_black_is_one_change_not_a_flash(self):
        frames = [level(0.8 * (1 - min(1.0, i / 30.0))) for i in range(60)]
        s = MG.safety_of(frames, self.fps)
        self.assertEqual(s["general"]["flashes"], [])
        self.assertEqual(s["general"]["changes"], 1)

    def test_flashes_whose_leading_edges_lie_a_third_of_a_second_apart_are_counted_apart(self):
        frames = []
        for i in range(90):
            frames.append(level(0.8 if i % 12 in (0, 1) else 0.3))   # a flash every 0.4 s: 2.5 a second
        s = MG.safety_of(frames, self.fps)
        self.assertEqual(s["general"]["most_flashes_a_second"], 3)
        self.assertFalse(s["general"]["harmful"])
        self.assertAlmostEqual(s["general"]["least_gap_s"], 0.4, delta=0.001)

    def test_a_saturated_red_flicker_is_found(self):
        frames = []
        for i in range(60):
            img = level(0.1)
            if (i // 3) % 2:
                img[...] = (0.9, 0.05, 0.05)
            frames.append(img)
        s = MG.safety_of(frames, self.fps)
        self.assertGreater(s["red"]["most_flashes_a_second"], 3)
        self.assertTrue(s["red"]["harmful"])
        calm = MG.safety_of([level(0.1)] * 60, self.fps)
        self.assertEqual(calm["red"]["most_flashes_a_second"], 0)

    def strobe(self, low, high, h=36, w=64, where=None):
        """two seconds of a picture going between two pictures every two frames (7.5 flashes a second)"""
        frames = []
        for i in range(60):
            img = level(0.0, h, w)
            img[...] = low
            if (i // 2) % 2:
                if where is None:
                    img[...] = high
                else:
                    img[where] = high
            frames.append(img)
        return MG.safety_of(frames, self.fps)

    def test_a_coloured_flash_is_judged_by_the_luminance_of_its_three_channels(self):
        # (the screen's luminance is that of its three primaries, each through BT.1886: full red and blue over black is
        # 200 x (0.2126 + 0.0722) = 57 cd/m2.  The luma of the signal put through the curve made it 9.8, under the 20 of a flash,
        # and a strobe of it passed; review mographrev 2026-10-21)
        s = self.strobe((0.0, 0.0, 0.0), (1.0, 0.0, 1.0))
        self.assertTrue(s["general"]["harmful"])
        self.assertAlmostEqual(s["general"]["flashes"][0]["cd"], 200 * (0.2126 + 0.0722), delta=1.0)
        self.assertEqual(s["red"]["most_flashes_a_second"], 0)                    # half red: no saturated red
        # a grey is as before
        self.assertAlmostEqual(self.strobe(0.3, 0.8)["general"]["flashes"][0]["cd"], 200 * (0.8 ** 2.4 - 0.3 ** 2.4), delta=0.5)

    def test_a_quarter_of_the_screen_is_allowed_and_more_is_not(self):
        # ("the combined area of flashes occurring concurrently occupies more than 25% of the displayed screen area")
        self.assertFalse(self.strobe(0.2, 0.7, where=(slice(None), slice(0, 16)))["general"]["harmful"])    # 16 of 64 columns
        self.assertTrue(self.strobe(0.2, 0.7, where=(slice(None), slice(0, 17)))["general"]["harmful"])

    def test_a_fine_pattern_flashes_over_the_area_it_covers(self):
        # every other column of a 256 x 144 picture: half of every cell of the grid (4 x 4 px) goes from 4.2 to 117 cd/m2, the
        # cells' mean by 56: a flash over the whole screen, not over none of it
        s = self.strobe(0.2, 0.8, h=144, w=256, where=(slice(None), slice(1, None, 2)))
        self.assertTrue(s["general"]["harmful"])

    def test_only_a_saturated_red_makes_a_red_flash(self):
        # WCAG 2.2's saturated red: R / (R + G + B) of 0.8 or more, linear.  An orange of full red and 0.7 green is 0.70
        self.assertEqual(self.strobe((0.0, 0.0, 0.0), (1.0, 0.7, 0.0))["red"]["most_flashes_a_second"], 0)

    def test_a_bright_red_flicker_is_a_red_flash_whatever_its_luminance(self):
        # ("irrespective of luminance": full red and 0.8 red are (R - G - B) x 320 of 320 and 187, 133 apart)
        s = self.strobe((0.8, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertGreater(s["red"]["most_flashes_a_second"], 3)
        self.assertTrue(s["red"]["harmful"])


if __name__ == "__main__":
    unittest.main()
