"""tools/mograph_analyze.py: the motion graphics of a video in numbers: how its shots change (cuts, flashes, fades,
dissolves, zoom punches, shakes, glitch frames, colour flashes) and when against the beat, and the graphic things on
its frames (particles and bokeh, straight lines).

Every measure is tried on frames made for it, whose answer is known from how they were made.
"""
import importlib.util
import math
import os
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
        p = MG.particles(rgb, unit=1.0)
        self.assertAlmostEqual(p["particle.count"], 48, delta=5)
        self.assertAlmostEqual(p["particle.bokeh"], 8 / 48.0, delta=0.08)

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


if __name__ == "__main__":
    unittest.main()
