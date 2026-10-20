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


if __name__ == "__main__":
    unittest.main()
