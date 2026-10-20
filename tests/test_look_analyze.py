"""tools/look_analyze.py: the look of a video (its tone, colour, light, optics, texture and frame) measured in numbers.

Every measure is tried on a picture made for it, whose answer is known from how it was made (a step blurred by a known
amount, a highlight with a known glow, a frame shifted by a known number of pixels), and on the same picture without the
effect, which must read as none.
"""
import importlib.util
import json
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
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("look_analyze", os.path.join(ROOT, "tools", "look_analyze.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LA = load_tool() if np is not None else None
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
NEEDS = "needs numpy, scipy and OpenCV"


def blocks(h, w, n=60, seed=1, low=0.15, high=0.85):
    """a grey picture of n overlapping rectangles of random levels on a mid grey: steps in every direction"""
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 0.5, np.float64)
    for _ in range(n):
        y0, x0 = rng.integers(0, h - 8), rng.integers(0, w - 8)
        y1, x1 = y0 + rng.integers(8, max(9, h // 3)), x0 + rng.integers(8, max(9, w // 3))
        img[y0:y1, x0:x1] = rng.uniform(low, high)
    return img


def rgb(grey):
    return np.repeat(grey[..., None], 3, axis=2)


@unittest.skipUnless(LA, NEEDS)
class ColourTest(unittest.TestCase):
    def test_lab_of_known_colours(self):
        # CIE L*a*b* (D65) of sRGB white, mid grey and pure red: the textbook values
        lab = LA.rgb_to_lab(np.array([[1.0, 1.0, 1.0], [0.5, 0.5, 0.5], [1.0, 0.0, 0.0]]))
        np.testing.assert_allclose(lab[0], [100.0, 0.0, 0.0], atol=0.05)
        np.testing.assert_allclose(lab[1], [53.39, 0.0, 0.0], atol=0.05)
        np.testing.assert_allclose(lab[2], [53.24, 80.09, 67.20], atol=0.1)

    def test_lab_goes_back_to_the_same_colour(self):
        rng = np.random.default_rng(3)
        colours = rng.uniform(0.02, 0.98, (500, 3))
        np.testing.assert_allclose(LA.lab_to_rgb(LA.rgb_to_lab(colours)), colours, atol=1e-6)

    def test_tone_reads_where_the_blacks_the_middle_and_the_whites_lie(self):
        # half the picture at L* 20 and half at L* 80: the middle between them, the spread 30, half of it in shadow
        lab = np.zeros((90, 160, 3))
        lab[:, :80, 0], lab[:, 80:, 0] = 20.0, 80.0
        picture = LA.lab_to_rgb(lab)
        tone = LA.tone(picture, LA.rgb_to_lab(picture), unit=160 / 1280.0)
        self.assertAlmostEqual(tone["tone.contrast"], 30.0, delta=0.2)
        self.assertAlmostEqual(tone["tone.black"], 20.0, delta=0.2)
        self.assertAlmostEqual(tone["tone.white"], 80.0, delta=0.2)
        self.assertAlmostEqual(tone["tone.shadows"], 0.5, delta=0.01)       # under L* 25
        self.assertAlmostEqual(tone["tone.highlights"], 0.5, delta=0.01)    # over L* 75
        self.assertEqual(tone["tone.clip_white"], 0.0)

    def test_a_dark_picture_is_low_key_and_a_bright_one_high_key(self):
        rng = np.random.default_rng(5)
        dark = rng.beta(2, 6, (90, 160))           # most values low, a few high
        bright = 1.0 - dark
        key_dark = LA.tone(rgb(dark), LA.rgb_to_lab(rgb(dark)), unit=0.125)["tone.key"]
        key_bright = LA.tone(rgb(bright), LA.rgb_to_lab(rgb(bright)), unit=0.125)["tone.key"]
        self.assertLess(key_dark, 0.45)
        self.assertGreater(key_bright, 0.55)

    def test_clipped_whites_and_crushed_blacks_are_counted(self):
        picture = np.full((100, 100, 3), 0.5)
        picture[:10] = 1.0                          # 10 % white
        picture[-5:] = 0.0                          # 5 % black
        tone = LA.tone(picture, LA.rgb_to_lab(picture), unit=100 / 720.0)
        self.assertAlmostEqual(tone["tone.clip_white"], 0.10, delta=0.001)
        self.assertAlmostEqual(tone["tone.clip_black"], 0.05, delta=0.001)

    def test_local_contrast_is_the_fine_detail_not_the_spread(self):
        # a smooth ramp and the same range in fine bars: the same spread of L*, much more local contrast in the bars
        h, w = 180, 320
        ramp = np.tile(np.linspace(0.2, 0.8, w), (h, 1))
        bars = np.where((np.arange(w) // 3) % 2 == 0, 0.2, 0.8)[None, :].repeat(h, axis=0)
        t_ramp = LA.tone(rgb(ramp), LA.rgb_to_lab(rgb(ramp)), unit=0.25)
        t_bars = LA.tone(rgb(bars), LA.rgb_to_lab(rgb(bars)), unit=0.25)
        self.assertGreater(t_bars["tone.local"], 4 * t_ramp["tone.local"])

    def test_split_toning_teal_shadows_and_orange_highlights(self):
        # a grey ramp whose shadows lean to teal and highlights to orange (a*b* given), and the same ramp neutral
        h, w = 60, 400
        lab = np.zeros((h, w, 3))
        lab[..., 0] = np.linspace(8, 95, w)[None, :]
        neutral = LA.lab_to_rgb(lab)
        tinted = lab.copy()
        shadow = lab[..., 0] < 35
        high = lab[..., 0] >= 65
        tinted[shadow, 1], tinted[shadow, 2] = -8.0, -8.0          # hue 225: teal
        tinted[high, 1], tinted[high, 2] = 8.0, 12.0               # hue 56: orange
        tinted = LA.lab_to_rgb(tinted)
        c_neutral = LA.colour(neutral, LA.rgb_to_lab(neutral))
        c_tinted = LA.colour(tinted, LA.rgb_to_lab(tinted))
        self.assertLess(abs(c_neutral["split.teal_orange"]), 0.5)
        self.assertGreater(c_tinted["split.teal_orange"], 15.0)
        self.assertAlmostEqual(c_tinted["split.shadow_hue"], 225.0, delta=5.0)
        self.assertAlmostEqual(c_tinted["split.high_hue"], 56.3, delta=5.0)
        self.assertAlmostEqual(c_tinted["split.shadow_chroma"], math.hypot(8, 8), delta=1.0)
        self.assertLess(c_neutral["colour.chroma"], 0.5)

    def test_colourfulness_grows_with_saturation(self):
        rng = np.random.default_rng(2)
        vivid = rng.uniform(0, 1, (90, 160, 3))
        dull = 0.5 + 0.3 * (vivid - 0.5)
        grey = np.repeat(vivid.mean(axis=2, keepdims=True), 3, axis=2)
        m = [LA.colour(p, LA.rgb_to_lab(p))["colour.colourfulness"] for p in (grey, dull, vivid)]
        self.assertLess(m[0], 1.0)
        self.assertLess(m[0], m[1])
        self.assertLess(m[1], m[2])

    def test_white_balance_of_a_neutral_and_a_warm_white(self):
        # the white of D65 is about 6500 K; a white with less blue reads warmer (lower)
        neutral = np.full((50, 50, 3), 0.9)
        warm = np.empty((50, 50, 3))
        warm[...] = (0.95, 0.88, 0.72)
        wb_n = LA.white_balance(neutral, LA.rgb_to_lab(neutral))
        wb_w = LA.white_balance(warm, LA.rgb_to_lab(warm))
        self.assertAlmostEqual(wb_n["wb.cct"], 6504, delta=60)
        self.assertLess(wb_w["wb.cct"], 5000)
        self.assertGreater(wb_w["wb.white_b"], 5.0)
        self.assertAlmostEqual(wb_n["wb.share"], 1.0)
        dark = np.full((50, 50, 3), 0.2)                         # no white to read it from
        self.assertTrue(math.isnan(LA.white_balance(dark, LA.rgb_to_lab(dark))["wb.cct"]))
        # a bright yellow (blonde hair, a lamp) beside the white is no white: the white's own colour is read
        mixed = np.full((60, 60, 3), 0.92)
        mixed[:, 30:] = (0.97, 0.88, 0.25)                        # L* 89, C* 76
        wb_m = LA.white_balance(mixed, LA.rgb_to_lab(mixed))
        self.assertAlmostEqual(wb_m["wb.cct"], 6504, delta=60)
        self.assertAlmostEqual(wb_m["wb.share"], 0.5, delta=0.01)


@unittest.skipUnless(LA, NEEDS)
class FrameTest(unittest.TestCase):
    def test_letterbox_bars_are_found_on_every_side(self):
        rng = np.random.default_rng(4)
        frames = []
        for _ in range(6):
            f = rng.uniform(0.1, 0.9, (180, 320))
            f[:22], f[-22:] = 0.0, 0.0          # bars top and bottom
            f[:, :10] = 0.01                     # a thin pillar on the left
            frames.append(f)
        bars = LA.find_bars(np.array(frames))
        self.assertEqual((bars["top"], bars["bottom"], bars["left"], bars["right"]), (22, 22, 10, 0))
        box = LA.active_box(bars, (180, 320))
        self.assertEqual(box, (10, 22, 320, 158))

    def test_a_dark_scene_is_not_a_letterbox(self):
        # a dark night picture: dark rows that change from frame to frame are picture, not bars
        rng = np.random.default_rng(6)
        frames = [np.clip(rng.normal(0.03, 0.03, (90, 160)), 0, 1) for _ in range(6)]
        for f in frames:
            f[40:50, 60:100] = 0.8
        bars = LA.find_bars(np.array(frames))
        self.assertEqual(bars["top"] + bars["bottom"], 0)

    def test_vignette_is_read_from_many_frames_of_changing_content(self):
        # the same lens darkening (ffmpeg's cos^4 vignette) over frames of random content: content averages out
        h, w = 36, 64
        r = LA.radius_map(h, w)
        for angle in (0.3, 0.6):
            mask = np.cos(angle * r) ** 4
            rng = np.random.default_rng(7)
            maps = np.array([rng.uniform(0.2, 0.8, (h, w)) * mask for _ in range(400)])
            got = LA.vignette(maps)
            want = mask[r >= 0.9].mean() / mask[r <= 0.3].mean()
            self.assertAlmostEqual(got["vignette.corner"], want, delta=0.02)
            self.assertAlmostEqual(got["vignette.corner_p95"], want, delta=0.02)
        flat = np.array([np.random.default_rng(i).uniform(0.2, 0.8, (h, w)) for i in range(400)])
        self.assertAlmostEqual(LA.vignette(flat)["vignette.corner"], 1.0, delta=0.02)
        self.assertAlmostEqual(LA.vignette(flat)["vignette.corner_p95"], 1.0, delta=0.02)


@unittest.skipUnless(LA, NEEDS)
class TimeTest(unittest.TestCase):
    def test_flashes_are_short_bright_jumps(self):
        fps = 60
        rng = np.random.default_rng(8)
        series = 0.3 + 0.004 * rng.standard_normal(fps * 40)
        for start in (300, 900, 1500):
            series[start:start + 5] += 0.3           # three white flashes of 5 frames
        series[1800:] += 0.2                          # and a lasting change of light, which is no flash
        series[2100:2105] += 0.45                     # nor is a light switched on with a flicker: it does not come back
        series[2105:] += 0.25
        events, summary = LA.flashes(series, fps)
        self.assertEqual([e["start"] for e in events], [300, 900, 1500])
        self.assertAlmostEqual(summary["flash.per_min"], 4.5, delta=0.01)
        self.assertAlmostEqual(summary["flash.peak"], 0.3, delta=0.03)

    def thumbs(self, fps=60, seconds=12, cuts=(240, 500), flash=(400, 3), dup=False):
        """grey thumbnails of a moving picture with hard cuts and a flash; dup: every frame twice (30 in 60)"""
        rng = np.random.default_rng(9)
        # smooth scenes: moving one by a pixel changes it a little, a cut to another changes it a lot
        scenes = []
        for _ in range(len(cuts) + 1):
            field = ndi.gaussian_filter(rng.standard_normal((18, 32)), 3.0, mode="wrap")
            scenes.append(0.5 + 0.3 * field / np.abs(field).max())
        out = []
        n = fps * seconds
        for i in range(n):
            k = sum(i >= c for c in cuts)
            t = (i // 2) * 2 if dup else i
            frame = np.roll(scenes[k], t, axis=1)
            if flash[0] <= i < flash[0] + flash[1]:
                frame = np.clip(frame + 0.5, 0, 1)
            out.append(frame)
        return np.array(out)

    def test_cuts_are_found_and_a_flash_is_not_a_cut(self):
        fps = 60
        thumbs = self.thumbs()
        events, _ = LA.flashes(thumbs.mean(axis=(1, 2)), fps)
        cuts, summary = LA.cuts(thumbs, fps, events)
        self.assertEqual(cuts, [240, 500])
        self.assertAlmostEqual(summary["cuts.per_min"], 10.0, delta=0.01)
        self.assertAlmostEqual(summary["shots.median_s"], (500 - 240) / 60.0, delta=0.5)

    def test_a_video_of_doubled_frames_moves_at_half_its_rate(self):
        fps = 60
        dup = LA.effective_fps(self.thumbs(dup=True, cuts=(), flash=(0, 0)), fps)
        own = LA.effective_fps(self.thumbs(dup=False, cuts=(), flash=(0, 0)), fps)
        self.assertEqual((dup["frame.fps_effective"], dup["step"]), (30, 2))
        self.assertEqual((own["frame.fps_effective"], own["step"]), (60, 1))



def highlights(h, w, points, radius, level=1.0, base=0.05):
    """a dark picture (Y' base) with small round highlights of Y' level at the given (y, x)"""
    img = np.full((h, w), base)
    yy, xx = np.mgrid[0:h, 0:w]
    for y, x in points:
        img[(yy - y) ** 2 + (xx - x) ** 2 <= radius * radius] = level
    return rgb(img)


def add_glow(picture, sigma, strength, channels=(1.0, 1.0, 1.0), threshold=0.9):
    """a glow made the usual way: the bright parts (Y' over threshold) blurred and added in linear light"""
    lin = LA.srgb_to_linear(picture)
    bright = lin * (LA.luma(picture) >= threshold)[..., None]
    glow = np.stack([ndi.gaussian_filter(bright[..., c], sigma) for c in range(3)], axis=-1)
    return np.clip(LA.linear_to_srgb(lin + strength * glow * np.array(channels)), 0.0, 1.0)


POINTS = [(60, 80), (60, 240), (60, 400), (60, 560), (200, 80), (200, 320), (200, 560), (300, 200), (300, 440)]


@unittest.skipUnless(LA, NEEDS)
class LightTest(unittest.TestCase):
    unit = 0.5                                   # the pictures are 360 lines: half a 720 line pixel each

    def test_no_glow_reads_as_none(self):
        bloom = LA.bloom(highlights(360, 640, POINTS, 4), unit=self.unit)
        self.assertLess(bloom["bloom.strength"], 0.01)
        self.assertTrue(math.isnan(bloom["bloom.r50"]))

    def test_a_wider_glow_reaches_further_and_a_stronger_one_is_stronger(self):
        base = highlights(360, 640, POINTS, 4)
        r50 = [LA.bloom(add_glow(base, s, 1.0), unit=self.unit)["bloom.r50"] for s in (2.0, 4.0, 8.0)]
        self.assertLess(r50[0], r50[1])
        self.assertLess(r50[1], r50[2])
        self.assertAlmostEqual(r50[2] / r50[1], 2.0, delta=0.5)       # twice the blur, about twice the reach
        strength = [LA.bloom(add_glow(base, 4.0, k), unit=self.unit)["bloom.strength"] for k in (0.25, 0.5)]
        self.assertGreater(strength[0], 0.02)
        self.assertAlmostEqual(strength[1] / strength[0], 2.0, delta=0.4)

    def test_lengths_are_in_pixels_of_a_720_line_picture(self):
        # the same glow drawn at 720 lines (twice as big) reads the same reach and strength
        small = add_glow(highlights(360, 640, POINTS, 4), 4.0, 1.0)
        big = add_glow(highlights(720, 1280, [(2 * p[0], 2 * p[1]) for p in POINTS], 8), 8.0, 1.0)
        b_small, b_big = LA.bloom(small, unit=0.5), LA.bloom(big, unit=1.0)
        self.assertAlmostEqual(b_small["bloom.r50"] / b_big["bloom.r50"], 1.0, delta=0.15)
        self.assertAlmostEqual(b_small["bloom.strength"] / b_big["bloom.strength"], 1.0, delta=0.15)

    def test_a_red_halo_round_a_white_light_is_halation(self):
        base = highlights(360, 640, POINTS, 4)
        red = LA.bloom(add_glow(base, 4.0, 0.6, channels=(1.0, 0.15, 0.05)), unit=self.unit)
        white = LA.bloom(add_glow(base, 4.0, 0.6), unit=self.unit)
        self.assertGreater(red["bloom.halo_red"], 0.3)
        self.assertLess(abs(white["bloom.halo_red"]), 0.05)

    def rays(self, picture, angles, length=30.0, level=0.6):
        """thin rays from each highlight at the given angles (degrees, counterclockwise from the right, y up)"""
        lin = LA.srgb_to_linear(picture)
        h, w = picture.shape[:2]
        add = np.zeros((h, w))
        for y0, x0 in POINTS:
            for a in angles:
                for t in np.linspace(4, length, 200):
                    y = int(round(y0 - t * math.sin(math.radians(a))))
                    x = int(round(x0 + t * math.cos(math.radians(a))))
                    if 0 <= y < h and 0 <= x < w:
                        add[y, x] = max(add[y, x], level * (1.0 - t / length))
        add = ndi.gaussian_filter(add, 0.7)
        return np.clip(LA.linear_to_srgb(lin + add[..., None]), 0.0, 1.0)

    def test_star_filter_rays_are_counted_and_their_angle_read(self):
        base = highlights(360, 640, POINTS, 2)
        star = LA.streaks(self.rays(base, [15 + 60 * k for k in range(6)]), unit=self.unit)
        self.assertEqual(star["streak.rays"], 6)
        self.assertGreater(star["streak.strength"], 0.3)
        self.assertAlmostEqual(star["streak.angle"], 15.0, delta=5.0)
        flare = LA.streaks(self.rays(base, [0, 180], length=40.0), unit=self.unit)
        self.assertEqual(flare["streak.rays"], 2)
        self.assertAlmostEqual(min(flare["streak.angle"], 180 - flare["streak.angle"]), 0.0, delta=5.0)
        round_glow = LA.streaks(add_glow(base, 4.0, 1.0), unit=self.unit)
        self.assertLess(round_glow["streak.strength"], 0.1)

    def test_the_lights_colour_and_side(self):
        # brighter on the right, and the brightest parts blue
        h, w = 180, 320
        grey = np.tile(np.linspace(0.2, 0.7, w), (h, 1))
        picture = rgb(grey)
        picture[:, -20:] = (0.7, 0.85, 1.0)
        light = LA.light(picture, LA.rgb_to_lab(picture))
        self.assertGreater(light["light.lr"], 0.1)
        self.assertAlmostEqual(light["light.tb"], 0.0, delta=0.02)
        self.assertGreater(light["light.key_hue"], 250.0)
        self.assertLess(light["light.key_hue"], 300.0)


@unittest.skipUnless(LA, NEEDS)
class LightingTest(unittest.TestCase):
    """the lighting of a frame (beams, pools of light, how many colours its lights have) and of a video (its palette of
    light colours, how often they change, flicker and strobes, how the light moves): typoref, 2026-10-20"""

    def dark(self, h=360, w=640, level=0.04, seed=3):
        rng = np.random.default_rng(seed)
        return np.full((h, w, 3), level) + rng.normal(0, 0.004, (h, w, 3))

    def beam(self, img, x0, y0, angle_deg, length, width, amount=0.35, colour=(1.0, 1.0, 1.0)):
        """a soft shaft of light from (x0, y0) going down at angle_deg from the vertical, Gaussian across"""
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        a = math.radians(angle_deg)
        ux, uy = math.sin(a), math.cos(a)
        along = (xx - x0) * ux + (yy - y0) * uy
        across = -(xx - x0) * uy + (yy - y0) * ux
        on = (along >= 0) & (along <= length)
        fall = np.exp(-across ** 2 / (2 * (width / 2.0) ** 2)) * on * np.clip(1.0 - along / (1.3 * length), 0, 1)
        for c in range(3):
            img[..., c] += amount * colour[c] * fall
        return img

    def test_a_shaft_of_light_is_a_beam(self):
        img = self.beam(self.dark(), 320, 0, 20.0, 300, 26)
        b = LA.beams(np.clip(img, 0, 1), unit=0.5)
        self.assertEqual(b["beam.count"], 1)
        self.assertAlmostEqual(b["beam.angle"], 20.0, delta=6.0)
        self.assertGreater(b["beam.length"], 0.6)                   # of the picture's height
        self.assertEqual(b["spot.count"], 0)

    def test_the_beams_parts_are_handed_out_for_the_figure(self):
        img = self.beam(self.dark(), 320, 0, 20.0, 300, 26)
        ex = {}
        b = LA.beams(np.clip(img, 0, 1), unit=0.5, extras=ex)
        self.assertEqual(len(ex["beam_labels"]), b["beam.count"])
        part = ex["light_map"] == ex["beam_labels"][0]
        self.assertGreater(part.sum(), 100)

    def test_a_thin_hard_line_is_no_beam(self):
        img = self.dark()
        img[100:103, 50:600] = 0.9                                  # a painted line on a road, a bar of light
        b = LA.beams(np.clip(img, 0, 1), unit=0.5)
        self.assertEqual(b["beam.count"], 0)

    def test_hard_bright_things_are_no_beams_nor_spots(self):
        # a lit window and an LED bar: bright, flat inside, hard edged (not light in the air or a pool on the floor)
        img = self.dark()
        img[150:200, 300:360] = 0.85                                 # a window
        img[40:60, 100:560] = 0.9                                    # a wide bar of light
        b = LA.beams(np.clip(img, 0, 1), unit=0.5)
        self.assertEqual((b["beam.count"], b["spot.count"]), (0, 0))

    def test_a_round_pool_of_light_is_a_spot(self):
        img = self.dark()
        yy, xx = np.mgrid[0:360, 0:640]
        img += 0.3 * np.exp(-((xx - 300) ** 2 / (2 * 50.0 ** 2) + (yy - 280) ** 2 / (2 * 22.0 ** 2)))[..., None]
        b = LA.beams(np.clip(img, 0, 1), unit=0.5)
        self.assertEqual(b["spot.count"], 1)
        self.assertEqual(b["beam.count"], 0)

    def test_nothing_is_nothing(self):
        b = LA.beams(np.clip(self.dark(), 0, 1), unit=0.5)
        self.assertEqual((b["beam.count"], b["spot.count"]), (0, 0))

    def test_the_colours_of_the_lights(self):
        img = self.dark()
        for x0, col in ((100, (1.0, 0.1, 0.6)), (320, (0.1, 0.9, 1.0)), (540, (1.0, 0.6, 0.1))):
            img = self.beam(img, x0, 0, 0.0, 300, 30, amount=0.5, colour=col)
        three = LA.light_colours(np.clip(img, 0, 1), LA.rgb_to_lab(np.clip(img, 0, 1)))
        one = self.beam(self.dark(), 320, 0, 0.0, 300, 30, amount=0.5, colour=(0.1, 0.9, 1.0))
        single = LA.light_colours(np.clip(one, 0, 1), LA.rgb_to_lab(np.clip(one, 0, 1)))
        self.assertEqual(three["light.colours"], 3)
        self.assertEqual(single["light.colours"], 1)
        self.assertGreater(three["light.spread"], 3 * max(single["light.spread"], 5.0))

    def test_palette_and_changes_of_the_light_colour(self):
        rows = []
        hues = [330.0] * 20 + [200.0] * 20 + [40.0] * 20 + [330.0] * 20
        for i, hdeg in enumerate(hues):
            rows.append({"t": i * 1.5, "shot": i // 20, "m": {"light.key_hue": hdeg - 360.0 if hdeg > 180 else hdeg,
                                                              "light.key_chroma": 30.0}})
        v = LA.light_palette(rows, duration=120.0)
        self.assertEqual(v["lightcol.palette"], 3)
        self.assertAlmostEqual(v["lightcol.colourful"], 1.0)
        self.assertAlmostEqual(v["lightcol.changes_per_min"], 1.5, delta=0.01)       # 3 changes in 2 minutes

    def test_flicker_and_strobe(self):
        fps = 30
        rng = np.random.default_rng(5)
        calm = 0.3 + 0.003 * rng.standard_normal(fps * 20)
        strobe = calm.copy()
        for k in range(8):                                          # 8 flashes 0.2 s apart: a strobe
            strobe[300 + 6 * k:300 + 6 * k + 2] += 0.35
        f_calm = LA.flicker(calm, fps)
        f_strobe = LA.flicker(strobe, fps)
        self.assertEqual(f_calm["strobe.per_min"], 0.0)
        self.assertAlmostEqual(f_strobe["strobe.per_min"], 3.0, delta=0.01)          # one strobe in 20 s
        self.assertGreater(f_strobe["flicker.hf"], 5 * max(f_calm["flicker.hf"], 1e-3))

    def test_cuts_are_no_flicker(self):
        # typorev: a cut is a step of the picture's mean light; the references' 24 cuts a minute read as a flicker of
        # 0.016 where the light itself flickered 0.0045 (RE: 踊, the frames next to a cut left out)
        fps = 30
        rng = np.random.default_rng(6)
        calm = 0.3 + 0.003 * rng.standard_normal(fps * 20)
        cuts = list(range(40, fps * 20, 75))                        # a cut every 2.5 s
        shots = calm.copy()
        for k, c in enumerate(cuts):
            shots[c:] += 0.12 if k % 2 == 0 else -0.09                  # each shot lit another way
        read_over = LA.flicker(shots, fps)["flicker.hf"]
        read_apart = LA.flicker(shots, fps, cuts=cuts)["flicker.hf"]
        steady = LA.flicker(calm, fps)["flicker.hf"]
        self.assertGreater(read_over, 3 * steady)                       # read over the cuts, the steps are flicker
        self.assertLess(read_apart, 1.5 * steady)
        # a strobe inside a shot is still flicker
        strobe = shots.copy()
        for k in range(8):
            strobe[300 + 6 * k:300 + 6 * k + 2] += 0.35
        self.assertGreater(LA.flicker(strobe, fps, cuts=cuts)["flicker.hf"], 5 * steady)

    def test_the_light_moves(self):
        fps = 30
        thumbs = []
        for i in range(90):
            t = np.full((36, 64), 0.05)
            x = 5 + int(i * 0.5)                                    # a light sweeping across, half a thumbnail px a frame
            t[10:14, x:x + 4] = 0.95
            thumbs.append(t)
        still = [np.full((36, 64), 0.05) for _ in range(90)]
        for t in still:
            t[10:14, 20:24] = 0.95
        moving = LA.light_motion(np.array(thumbs), fps, height_px=36)
        resting = LA.light_motion(np.array(still), fps, height_px=36)
        # 0.5 thumbnail px a frame at 30 fps, a thumbnail 36 rows for 720 lines: 0.5 * 30 * 20 = 300 px/s
        self.assertAlmostEqual(moving["lightmove.speed"], 300.0, delta=40.0)
        self.assertLess(resting["lightmove.speed"], 5.0)


@unittest.skipUnless(LA, NEEDS)
class TextureTest(unittest.TestCase):
    unit = 0.5

    def test_the_noise_of_flat_areas(self):
        rng = np.random.default_rng(11)
        clean = blocks(360, 640, seed=2)
        for sigma in (2.0, 4.0, 8.0):
            noisy = clean + rng.normal(0, sigma / 255.0, clean.shape)
            got = LA.noise_spatial(noisy)["noise.spatial"]
            # within 5 % (it reads 0.994 to 1.005 of sigma; without Immerkaer's sqrt(pi / 2) it would read 0.80)
            self.assertAlmostEqual(got, sigma, delta=0.05 * sigma + 0.1)
        self.assertLess(LA.noise_spatial(clean)["noise.spatial"], 0.5)

    def test_grain_that_changes_every_frame_and_its_size(self):
        rng = np.random.default_rng(12)
        clean = blocks(360, 640, seed=3)
        a = clean + rng.normal(0, 4 / 255.0, clean.shape)
        b = clean + rng.normal(0, 4 / 255.0, clean.shape)
        fine = LA.grain(a, b, unit=self.unit)
        self.assertAlmostEqual(fine["grain.temporal"], 4.0, delta=0.6)
        self.assertLess(fine["grain.size"], 1.2)
        # coarse grain: the same noise blurred by 1.5 pixels (3 of a 720 line picture) and brought back to 4 of 255
        n1 = ndi.gaussian_filter(rng.standard_normal(clean.shape), 1.5)
        n2 = ndi.gaussian_filter(rng.standard_normal(clean.shape), 1.5)
        n1, n2 = n1 / n1.std() * 4 / 255.0, n2 / n2.std() * 4 / 255.0
        coarse = LA.grain(clean + n1, clean + n2, unit=self.unit)
        self.assertAlmostEqual(coarse["grain.temporal"], 4.0, delta=0.8)
        self.assertGreater(coarse["grain.size"], 3 * fine["grain.size"])
        self.assertAlmostEqual(coarse["grain.size"], 2 * 1.5 * math.sqrt(math.log(2)) / self.unit, delta=1.5)
        still = LA.grain(clean, clean.copy(), unit=self.unit)
        self.assertLess(still["grain.temporal"], 0.3)

    def test_scanlines_are_a_period_in_the_rows(self):
        clean = blocks(360, 640, seed=4)
        lined = clean.copy()
        lined[::3] -= 0.05
        s_lined = LA.scanlines(lined)
        s_clean = LA.scanlines(clean)
        self.assertAlmostEqual(s_lined["scan.period"], 3.0, delta=0.2)
        self.assertGreater(s_lined["scan.peak"], 3 * s_clean["scan.peak"])

    def test_a_torn_band_of_rows_is_a_glitch(self):
        clean = blocks(360, 640, seed=5, n=120)
        torn = clean.copy()
        torn[100:130] = np.roll(clean[100:130], 20, axis=1)
        self.assertGreaterEqual(LA.glitch(torn)["glitch.tears"], 2)
        self.assertEqual(LA.glitch(clean)["glitch.tears"], 0)


def steps_picture(h=360, w=640, seed=21, levels=(0.15, 0.8), bright=0):
    """big flat rectangles (steps with wide flat sides), well apart: clean edges to read blur from; bright: so many
    more, of Y' 0.97 (light sources)"""
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 0.45)
    for _ in range(14):
        y0, x0 = rng.integers(0, h - 90), rng.integers(0, w - 120)
        img[y0:y0 + rng.integers(60, 90), x0:x0 + rng.integers(80, 120)] = rng.choice(list(levels))
    for _ in range(bright):
        y0, x0 = rng.integers(0, h - 70), rng.integers(0, w - 90)
        img[y0:y0 + 50, x0:x0 + 70] = 0.97
    return img


def moving_frames(shutter, speed=12.0, h=360, w=640):
    """two frames of a bright bar moving right by speed pixels a frame over a still background with still blocks
    above it, each frame the mean of the bar's positions while a shutter open for that share of the frame is open"""
    still = np.full((h, w), 0.3)
    still[20:120, 60:200], still[40:140, 300:420], still[30:110, 480:600] = 0.7, 0.12, 0.85
    frames = []
    for f in range(2):
        acc = np.zeros((h, w))
        subs = 32
        for k in range(subs):
            x = 180.0 + speed * (f + shutter * k / subs)
            img = still.copy()
            xs = np.arange(w)
            cover = np.clip(np.minimum(xs + 1 - x, x + 140 - xs), 0, 1)        # a bar 140 wide, its edges antialiased
            img[200:320] = img[200:320] * (1 - cover) + 0.9 * cover
            acc += img
        frames.append(acc / subs)
    return frames


def barrel(gray, k1):
    """gray seen through a lens with radial distortion r_d = r_u (1 + k1 r_u^2) (r over the half diagonal; k1 < 0 is
    barrel, the middle of a straight line bowed away from the centre)"""
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cy, cx, half = (h - 1) / 2.0, (w - 1) / 2.0, math.hypot(w / 2.0, h / 2.0)
    dy, dx = (yy - cy) / half, (xx - cx) / half
    rd = np.hypot(dx, dy)
    ru = rd.copy()
    for _ in range(20):                                   # solve rd = ru (1 + k1 ru^2) for ru
        ru = rd / (1.0 + k1 * ru * ru)
    scale = np.where(rd > 0, ru / np.maximum(rd, 1e-12), 1.0)
    # what falls outside the picture is left blank (stretching its border would draw straight streaks)
    return ndi.map_coordinates(gray, [cy + dy * scale * half, cx + dx * scale * half], order=1, mode="constant",
                               cval=float(np.median(gray)))


def grid(h=360, w=640, step=40):
    img = np.full((h, w), 0.85)
    for y in range(step // 2, h, step):
        img[y - 1:y + 1] = 0.15
    for x in range(step // 2, w, step):
        img[:, x - 1:x + 1] = 0.15
    return ndi.gaussian_filter(img, 0.6)


@unittest.skipUnless(LA, NEEDS)
class OpticsTest(unittest.TestCase):
    unit = 0.5

    def test_edge_blur_reads_the_blur_of_a_step(self):
        sharp = steps_picture()
        got = []
        for sigma in (1.0, 2.0, 4.0):
            e = LA.edges(ndi.gaussian_filter(sharp, sigma), unit=self.unit)
            got.append(float(np.median(e["sigma"])))
            self.assertAlmostEqual(got[-1], sigma / self.unit, delta=0.25 * sigma / self.unit)
        self.assertLess(got[0], got[1])
        self.assertLess(got[1], got[2])

    def test_depth_of_field_is_sharp_edges_and_soft_edges_in_one_frame(self):
        # the left half in focus, the right half blurred by 4 pixels (8 of a 720 line picture)
        sharp = steps_picture()
        soft = ndi.gaussian_filter(sharp, 4.0)
        both = sharp.copy()
        both[:, 320:] = soft[:, 320:]
        dof = LA.depth_of_field(LA.edges(both, unit=self.unit))
        flat = LA.depth_of_field(LA.edges(ndi.gaussian_filter(sharp, 0.7), unit=self.unit))
        self.assertLess(dof["dof.sharp"], 2.5)
        self.assertAlmostEqual(dof["dof.soft"], 8.0, delta=2.5)
        self.assertGreater(dof["dof.soft_share"], 0.25)
        self.assertLess(flat["dof.soft_share"], 0.05)
        self.assertLess(flat["dof.soft"] - flat["dof.sharp"], 1.5)

    def test_background_blur_is_read_from_blocks_of_detail(self):
        # the edges Canny finds keep to what is in focus: a blurred background has weak edges and is read in blocks,
        # each by the blur of its own steepest places (here a sharp half and the same picture blurred by 4 px)
        tex = ndi.gaussian_filter(blocks(360, 640, seed=13, n=400, low=0.1, high=0.9), 0.5)
        both = tex.copy()
        both[:, 320:] = ndi.gaussian_filter(tex, 4.0)[:, 320:]
        d = LA.dof_blocks(both, unit=self.unit)
        self.assertLess(d["dof.fg_blur"], 2.5)
        self.assertAlmostEqual(d["dof.bg_blur"], 8.0, delta=3.0)
        self.assertGreater(d["dof.ratio"], 3.0)
        sharp = LA.dof_blocks(tex, unit=self.unit)
        self.assertLess(sharp["dof.ratio"], 1.6)
        flat = LA.dof_blocks(np.full((360, 640), 0.5) + 0.01 * np.linspace(0, 1, 640)[None, :], unit=self.unit)
        self.assertTrue(math.isnan(flat["dof.ratio"]))              # no detail to read

    def test_a_blurred_background_under_coding_noise_still_reads_blurred(self):
        # the blocks and the noise of a compressed video are sharp: read at full size they make a background blurred by
        # 8 px read about 1 to 2 px (the first reading of r01's blurred background); read on the frame made 180 lines
        # tall they average out
        tex = ndi.gaussian_filter(blocks(720, 1280, seed=13, n=1600, low=0.1, high=0.9), 1.0)
        both = tex.copy()
        both[:, 640:] = ndi.gaussian_filter(tex, 8.0)[:, 640:]
        noisy = both + np.random.default_rng(3).normal(0, 1.5 / 255.0, both.shape)
        ok, buf = cv2.imencode(".jpg", np.clip(noisy * 255.0 + 0.5, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 40])
        coded = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE).astype(np.float64) / 255.0
        d = LA.dof_blocks(coded, unit=1.0)
        self.assertAlmostEqual(d["dof.bg_blur"], 8.0, delta=2.5)
        self.assertGreater(d["dof.ratio"], 2.5)

    def test_sharpening_leaves_a_halo_on_both_sides_of_an_edge(self):
        picture = ndi.gaussian_filter(steps_picture(), 1.0)
        unsharp = picture + 0.8 * (picture - ndi.gaussian_filter(picture, 2.0))
        plain = LA.edge_profiles(picture, LA.edges(picture, unit=self.unit), unit=self.unit)
        sharpened = LA.edge_profiles(unsharp, LA.edges(unsharp, unit=self.unit), unit=self.unit)
        self.assertLess(plain["sharp.overshoot"], 0.02)
        self.assertGreater(sharpened["sharp.overshoot"], 0.08)
        self.assertAlmostEqual(plain["sharp.width"], 2.563 * 1.0 / self.unit, delta=1.0)   # 10-90 % of a 1 px blur

    def test_diffusion_is_a_veil_round_a_sharp_edge(self):
        picture = ndi.gaussian_filter(steps_picture(), 0.7)
        for alpha in (0.15, 0.3):
            veiled = (1 - alpha) * picture + alpha * ndi.gaussian_filter(picture, 10.0)
            d = LA.edge_profiles(veiled, LA.edges(veiled, unit=self.unit), unit=self.unit)
            # the share of the step that lies beyond 4 pixels (720 line) of the edge: alpha less the little of the
            # wide blur that falls within those 4 pixels (2 here); the steps' far sides are 14 to 20 pixels out, where
            # the veil has not quite come to its end, so a little less is read
            want = alpha * (1 - math.erf(2.0 / (10.0 * math.sqrt(2))))
            self.assertAlmostEqual(d["diffusion.share"], want, delta=0.06)
            self.assertGreater(d["diffusion.radius"], 6.0)
        clean = LA.edge_profiles(picture, LA.edges(picture, unit=self.unit), unit=self.unit)
        self.assertLess(clean["diffusion.share"], 0.04)

    def test_a_glow_of_the_bright_parts_is_not_diffusion(self):
        # a glow made from the brightest parts widens the edges of those parts; diffusion veils every edge.  With many
        # bright parts (12: about half the clean steps are theirs) the bright steps must still be left out of diffusion
        for bright in (4, 12):
            picture = steps_picture(levels=(0.15, 0.3), bright=bright)
            glowing = LA.luma(add_glow(rgb(picture), 8.0, 0.8))
            d = LA.edge_profiles(glowing, LA.edges(glowing, unit=self.unit), unit=self.unit)
            self.assertLess(d["diffusion.share"], 0.04, bright)
            self.assertGreater(d["glow.edge_share"], 0.08, bright)
            plain = LA.edge_profiles(picture, LA.edges(picture, unit=self.unit), unit=self.unit)
            self.assertLess(plain["glow.edge_share"], 0.04, bright)

    def test_motion_blur_gives_the_shutter(self):
        for shutter in (0.0, 0.5, 1.0):
            a, b = moving_frames(shutter)
            m = LA.motion(a, b, LA.edges(a, unit=self.unit), unit=self.unit)
            self.assertAlmostEqual(m["motion.speed"], 24.0, delta=3.0)        # 12 pixels a frame at 360 lines
            self.assertAlmostEqual(m["motion.shutter"], shutter, delta=0.15, msg=shutter)
            self.assertAlmostEqual(m["motion.blurred_share"], 0.0 if shutter == 0 else 1.0, delta=0.15, msg=shutter)
            self.assertGreaterEqual(m["motion.shutter_p75"], m["motion.shutter"])

    def test_colour_fringes_shifted_and_scaled(self):
        grey = ndi.gaussian_filter(blocks(360, 640, seed=7, n=150), 0.8)
        shifted = rgb(grey)
        shifted[..., 0] = ndi.shift(grey, (0, 2.0), order=1, mode="nearest")      # red 2 px right
        shifted[..., 2] = ndi.shift(grey, (0, -2.0), order=1, mode="nearest")     # blue 2 px left
        ca = LA.aberration(shifted, unit=self.unit)
        self.assertAlmostEqual(ca["ca.red_x"], 4.0, delta=0.5)       # 720 line pixels
        self.assertAlmostEqual(ca["ca.blue_x"], -4.0, delta=0.5)
        self.assertAlmostEqual(ca["ca.red_y"], 0.0, delta=0.5)
        h, w = grey.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        scaled = rgb(grey)
        s = 1.004
        scaled[..., 0] = ndi.map_coordinates(grey, [cy + (yy - cy) / s, cx + (xx - cx) / s], order=1, mode="nearest")
        ca = LA.aberration(scaled, unit=self.unit)
        self.assertAlmostEqual(ca["ca.red_radial"], 0.004 * math.hypot(640, 360), delta=0.6)
        self.assertAlmostEqual(ca["ca.blue_radial"], 0.0, delta=0.4)
        clean = LA.aberration(rgb(grey), unit=self.unit)
        for key in ("ca.red_x", "ca.red_y", "ca.blue_x", "ca.red_radial"):
            self.assertAlmostEqual(clean[key], 0.0, delta=0.2, msg=key)

    def test_straight_lines_bend_by_the_lens_distortion(self):
        # k1 of r_d = r_u (1 + k1 r_u^2): negative for barrel (lines bow away from the centre), positive for pincushion
        g = grid()
        none = LA.distortion(g, unit=self.unit)
        self.assertGreater(none["distortion.segments"], 6)
        self.assertAlmostEqual(none["distortion.k1"], 0.0, delta=0.01)
        for k1, tol in ((-0.05, 0.02), (-0.15, 0.04), (0.1, 0.03)):
            got = LA.distortion(barrel(g, k1), unit=self.unit)
            self.assertAlmostEqual(got["distortion.k1"], k1, delta=tol, msg=k1)


def synthetic_video(path, size=(320, 180), fps=30, seconds=6, cuts=(60, 120), bars=20, flash=150, tag=True):
    """a small video of three shots of moving blocks with letterbox bars and a white flash, encoded as YouTube's are
    (H.264, 4:2:0, BT.709 and tagged so) or untagged with ffmpeg's own conversion (BT.601)"""
    w, h = size
    rng = np.random.default_rng(31)
    scenes = [ndi.gaussian_filter(blocks(h, w, seed=s, n=40), 1.0) for s in range(len(cuts) + 1)]
    frames = []
    for i in range(fps * seconds):
        k = sum(i >= c for c in cuts)
        g = np.roll(scenes[k], 2 * i, axis=1)
        img = np.stack([g * 0.9, g, np.clip(g * 1.1, 0, 1)], axis=-1)
        if flash <= i < flash + 3:
            img = np.clip(img + 0.5, 0, 1)
        img[:bars], img[h - bars:] = 0.0, 0.0
        frames.append(np.clip(img * 255.0 + rng.normal(0, 0.5, img.shape), 0, 255).astype(np.uint8))
    argv = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r", str(fps),
            "-i", "-"]
    if tag:
        argv += ["-vf", "scale=out_color_matrix=bt709:out_range=tv", "-colorspace", "bt709", "-color_primaries", "bt709",
                 "-color_trc", "bt709", "-color_range", "tv"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", path]
    subprocess.run(argv, input=b"".join(f.tobytes() for f in frames), check=True)
    return frames


@unittest.skipUnless(LA, NEEDS)
class SummaryTest(unittest.TestCase):
    def test_a_measure_over_frames_has_its_median_spread_and_floor(self):
        # 40 frames in 4 shots; each frame's second picture reads 0.1 more or less: the floor is about 0.1 / sqrt 2
        rng = np.random.default_rng(41)
        rows = []
        for i in range(40):
            v = 5.0 + (i // 10) + 0.05 * rng.standard_normal()
            rows.append({"shot": i // 10, "m": {"tone.median": v}, "m2": {"tone.median": v + (0.1 if i % 2 else -0.1)}})
        s = LA.summarise(rows)["tone.median"]
        self.assertAlmostEqual(s["median"], 6.5, delta=0.5)
        self.assertLess(s["q25"], s["median"])
        self.assertGreater(s["q75"], s["median"])
        self.assertEqual(s["n"], 40)
        self.assertEqual(s["shots"], 4)
        self.assertAlmostEqual(s["floor_pair"], 0.1 / math.sqrt(2), delta=0.02)
        self.assertLess(s["ci"][0], s["median"])
        self.assertGreater(s["ci"][1], s["median"])

    def test_nan_frames_are_left_out_and_counted(self):
        rows = [{"shot": 0, "m": {"bloom.r50": float("nan") if i % 3 else 10.0 + i}} for i in range(30)]
        s = LA.summarise(rows)["bloom.r50"]
        self.assertEqual(s["n"], 10)
        self.assertAlmostEqual(s["valid"], 10 / 30.0)

    def test_compare_reads_how_far_ours_lie_outside_the_references(self):
        refs = [{"label": "r%d" % i, "summary": {"tone.median": {"median": v, "floor_pair": 0.1}}}
                for i, v in enumerate([40.0, 42.0, 44.0, 46.0, 48.0])]
        ours = [{"label": "inside", "summary": {"tone.median": {"median": 45.0, "floor_pair": 0.1}}},
                {"label": "above", "summary": {"tone.median": {"median": 52.0, "floor_pair": 0.1}}}]
        rows = LA.compare(refs, ours)
        row = [r for r in rows if r["key"] == "tone.median"][0]
        self.assertEqual((row["ref_q25"], row["ref_median"], row["ref_q75"]), (42.0, 44.0, 46.0))
        self.assertEqual(row["ours"]["inside"]["distance"], 0.0)
        self.assertAlmostEqual(row["ours"]["above"]["distance"], (52.0 - 46.0) / 4.0)
        self.assertEqual(row["ours"]["above"]["side"], "above")
        # references that all agree (every one at 60 fps) leave no spread: 5 % of their value stands in for it
        same = [{"label": "r%d" % i, "summary": {"frame.fps": {"median": 60.0, "floor_pair": 0.0}}} for i in range(4)]
        ours30 = [{"label": "v", "summary": {"frame.fps": {"median": 30.0, "floor_pair": 0.0}}}]
        fps = [r for r in LA.compare(same, ours30) if r["key"] == "frame.fps"][0]
        self.assertAlmostEqual(fps["ours"]["v"]["distance"], 30.0 / 3.0)
        table = LA.table_md(rows, [o["label"] for o in ours])
        self.assertIn("tone.median", table)
        self.assertIn("1.5", table)

    def test_every_measure_has_a_label(self):
        for key, (concept, label, unit) in LA.MEASURES.items():
            self.assertIn(concept, LA.CONCEPTS, key)
            self.assertTrue(label, key)

    def test_the_colour_matrix_follows_the_tag_and_else_the_players_custom(self):
        self.assertEqual(LA.matrix_for({"color_space": "bt709", "height": 480}, "auto"), "bt709")
        self.assertEqual(LA.matrix_for({"color_space": "smpte170m", "height": 1080}, "auto"), "bt601")
        self.assertEqual(LA.matrix_for({"color_space": None, "height": 720}, "auto"), "bt709")
        self.assertEqual(LA.matrix_for({"color_space": "unknown", "height": 480}, "auto"), "bt601")
        self.assertEqual(LA.matrix_for({"color_space": "bt709", "height": 720}, "bt601"), "bt601")


@unittest.skipUnless(LA, NEEDS)
class FrameMeasureTest(unittest.TestCase):
    def test_one_pair_of_frames_gives_every_frame_measure(self):
        g = ndi.gaussian_filter(blocks(180, 320, seed=9, n=80), 0.8)
        a = rgb(g)
        b = rgb(np.roll(g, 2, axis=1))
        m = LA.measure_frame(a, b, unit=0.25, full=True)
        for key in LA.MEASURES:
            if key in LA.VIDEO_LEVEL:
                continue                                        # read from the whole video, not a frame
            self.assertIn(key, m, key)
            self.assertIsInstance(m[key], float, key)


@unittest.skipUnless(LA and FFMPEG, NEEDS + ", ffmpeg and ffprobe")
class VideoTest(unittest.TestCase):
    def test_a_video_is_read_through_its_shots_bars_and_flash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            synthetic_video(path)
            out = os.path.join(tmp, "v.json")
            LA.measure_video(path, out, label="synthetic", pairs=8, height=180, jobs=1, pair_every=2)
            with open(out, encoding="utf-8") as f:
                d = json.load(f)
        self.assertEqual(d["label"], "synthetic")
        self.assertEqual(d["frame"]["bars"]["top"], 20)
        self.assertEqual(d["frame"]["bars"]["bottom"], 20)
        self.assertAlmostEqual(d["frame"]["aspect"], 320 / 140.0, delta=0.02)
        self.assertEqual(d["time"]["cuts"], [60, 120])
        self.assertEqual([e["start"] for e in d["time"]["flashes"]], [150])
        self.assertEqual(d["frame"]["fps"], 30)
        self.assertEqual(d["frame"]["fps_effective"], 30)
        self.assertEqual(len(d["frames"]), 8)
        for f in d["frames"]:                              # no pair straddles a cut
            self.assertFalse(any(f["n"] < c <= f["n"] + 1 for c in (60, 120)), f["n"])
        s = d["summary"]
        self.assertIn("tone.median", s)
        self.assertIn("floor_pair", s["tone.median"])
        self.assertAlmostEqual(s["cuts.per_min"]["median"], 20.0, delta=0.01)
        self.assertEqual(d["matrix"], "bt709")
        self.assertEqual(len(d["profiles"]["tone_hist"]), 50)
        # each shot with two samples or more has its own medians, its frames and times
        counts = {}
        for f in d["frames"]:
            counts[f["shot"]] = counts.get(f["shot"], 0) + 1
        self.assertEqual([sh["shot"] for sh in d["shots"]], sorted(k for k, c in counts.items() if c >= 2))
        self.assertEqual(len(d["shots"]), 3)
        for sh in d["shots"]:
            self.assertGreaterEqual(sh["n"], 2)
            self.assertLessEqual(sh["start"], sh["end"])
            self.assertIn("tone.median", sh["m"])
        self.assertEqual(sum(d["profiles"]["sigma_hist"]) > 0, True)

    def test_the_figures_and_small_crops_are_drawn(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            synthetic_video(path)
            sheet = LA.contact_sheet(path, os.path.join(tmp, "sheet.png"), [1.0, 3.0], size=(160, 90), height=180,
                                     label="test")
            with Image.open(sheet) as im:
                self.assertEqual(im.size, (320, 108))
            for what in ("dof", "bloom", "ca", "bars", "motion"):
                out = LA.annotate(path, os.path.join(tmp, what + ".png"), 1.0, what=what, height=180)
                self.assertTrue(os.path.getsize(out) > 0, what)
            m = os.path.join(tmp, "v.json")
            self.assertEqual(LA.main(["measure", path, m, "--pairs", "4", "--height", "180"]), 0)
            md, js = os.path.join(tmp, "t.md"), os.path.join(tmp, "t.json")
            self.assertEqual(LA.main(["compare", md, js, "--ref", m, m, "--ours", m]), 0)
            strip = os.path.join(tmp, "strip.png")
            self.assertEqual(LA.main(["figure", "strip", strip, js]), 0)
            prof = os.path.join(tmp, "prof.png")
            self.assertEqual(LA.main(["figure", "profiles", prof, m, "--ours", "v"]), 0)
            self.assertTrue(os.path.getsize(strip) > 0 and os.path.getsize(prof) > 0)

    def test_a_video_made_smaller_for_the_analysis_does_not_ring(self):
        # read at half its height, a hard edge must not overshoot (lanczos rings by a few %, which reads as sharpening)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "edge.mp4")
            img = np.full((540, 960, 3), 51, np.uint8)            # 1080 to 720 is 1.5 to 1: so is 540 to 360
            img[:, 481:] = 204
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "960x540", "-r", "30",
                            "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-colorspace", "bt709",
                            "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", path], input=img.tobytes() * 3, check=True)
            info = LA.probe(path)
            got = next(iter(LA.read_frames(path, info, [1], height=360)))[1]
        row = got[180, :, 1]
        self.assertLess(row.max(), 204 / 255.0 + 0.01)
        self.assertGreater(row.min(), 51 / 255.0 - 0.01)

    def test_the_person_and_the_stage_of_a_video(self):
        def middle_third(a):                                   # a stand-in for the person model
            m = np.zeros(a.shape[:2])
            m[:, a.shape[1] // 3:2 * a.shape[1] // 3] = 1.0
            return m

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            synthetic_video(path, cuts=(), flash=10 ** 6)
            out = os.path.join(tmp, "r.json")
            with self.assertRaises(ValueError):
                LA.measure_regions(path, out)                  # neither the model nor a mask
            LA.measure_regions(path, out, label="syn", frames=6, height=180, mask_fn=middle_third)
            with open(out, encoding="utf-8") as f:
                d = json.load(f)
        self.assertEqual(d["box"], [0, 20, 320, 160])          # read inside the letterbox bars
        self.assertEqual(len(d["frames"]), 6)
        self.assertEqual(d["frames_with_person"], 6)
        s = d["summary"]
        self.assertAlmostEqual(s["frame.person_share"]["median"], 1 / 3.0, delta=0.01)
        for key in LA.REGION_MEASURES:
            self.assertIn(key, s, key)
        rows = LA.compare([d, d], [d], LA.REGION_MEASURES)
        self.assertEqual([r["key"] for r in rows], list(LA.REGION_MEASURES))
        table = LA.table_md(rows, ["syn"], LA.REGION_CONCEPTS, LA.REGION_CONCEPT_LABELS)
        self.assertIn("### 人物", table)
        self.assertIn("person.L_p50", table)

    def test_the_faces_of_a_video_are_read_when_asked(self):
        def middle_third(a):
            m = np.zeros(a.shape[:2])
            m[:, a.shape[1] // 3:2 * a.shape[1] // 3] = 1.0
            return m

        def one_face(a):                                       # a stand-in for the face finder: a box on the person
            h, w = a.shape[:2]
            return [(w // 2 - 12, h // 2 - 12, 24, 24)]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            synthetic_video(path, cuts=(), flash=10 ** 6)
            out = os.path.join(tmp, "r.json")
            d = LA.measure_regions(path, out, frames=4, height=180, mask_fn=middle_third, faces=one_face)
            self.assertTrue(math.isfinite(d["summary"]["face.L"]["median"]))
            self.assertEqual(d["summary"]["face.count"]["median"], 1.0)
            plain = LA.measure_regions(path, out, frames=4, height=180, mask_fn=middle_third)
            self.assertTrue(math.isnan(plain["summary"]["face.L"]["median"]))
            with self.assertRaises(ValueError):                # a face finder that cannot be loaded is no silent nothing
                LA.measure_regions(path, out, frames=4, height=180, mask_fn=middle_third,
                                   faces=os.path.join(tmp, "no_such_cascade.xml"))

    def test_the_person_of_our_own_render_is_read_from_her_layer(self):
        # look2 (2026-10-18): the person model took the bright floor line under v11's dancer for part of her on some frames,
        # and whether it did changed with the stage's blur (the halo read 0.7 and 1.8 for the same dancer and glow).  Our
        # own render has the dancer drawn alone with her alpha: --mask-video reads the person from it, frame by frame.  A
        # bright box (her) with a bright line running down from it to the bottom of the picture (the floor line): read
        # from her layer, the person is the box alone, and no model is needed
        w, h, n = 160, 180, 20
        with tempfile.TemporaryDirectory() as tmp:
            comp = np.full((h, w, 3), 40, np.uint8)                     # (a stage darker than 15 would read as letterbox bars)
            comp[40:110, 60:100] = 230                                  # her
            comp[110:, 78:82] = (200, 130, 40)                           # the amber line under her
            layer = np.zeros((h, w, 4), np.uint8)
            layer[40:110, 60:100] = (230, 230, 230, 255)
            path, mask = os.path.join(tmp, "c.mp4"), os.path.join(tmp, "layer.mov")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r",
                            "30", "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-colorspace", "bt709",
                            "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", path],
                           input=comp.tobytes() * n, check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (w, h), "-r",
                            "30", "-i", "-", "-c:v", "png", "-pix_fmt", "rgba", mask], input=layer.tobytes() * n, check=True)
            out = os.path.join(tmp, "r.json")
            self.assertEqual(LA.main(["regions", path, out, "--mask-video", mask, "--frames", "4", "--height", "180"]), 0)
            with open(out, encoding="utf-8") as f:
                d = json.load(f)
            self.assertAlmostEqual(d["summary"]["frame.person_share"]["median"], 70 * 40 / float(w * h), delta=0.002)
            self.assertEqual(d["mask"]["video"], mask)
            self.assertIsNone(d["model"])
            # a layer of another shape (another picture), or one shorter than the frames read, is refused
            small = os.path.join(tmp, "small.mov")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "160x160", "-r", "30",
                            "-i", "-", "-c:v", "png", "-pix_fmt", "rgba", small], input=layer[:160].tobytes() * n, check=True)
            short = os.path.join(tmp, "short.mov")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (w, h), "-r",
                            "30", "-i", "-", "-c:v", "png", "-pix_fmt", "rgba", short], input=layer.tobytes() * 5, check=True)
            for bad in (small, short):
                with self.assertRaises(ValueError, msg=bad):
                    LA.measure_regions(path, out, frames=4, height=180, mask_video=bad)

    def test_her_layer_is_read_on_the_frame_it_masks(self):
        # look2rev 2026-10-19: the layer and the frames are one picture each; a mask a frame early or late takes her outline
        # of another frame (the light just outside it is then read on her).  The test above has her still, which a mask a
        # frame early passed.  Here she grows by 4 rows a frame, in the frames and in her layer: on every frame read, the
        # person is that frame's box
        w, h, n = 160, 180, 20
        with tempfile.TemporaryDirectory() as tmp:
            comps, layers = [], []
            for k in range(n):
                comp = np.full((h, w, 3), 40, np.uint8)
                comp[40:64 + 4 * k, 60:100] = 230
                layer = np.zeros((h, w, 4), np.uint8)
                layer[40:64 + 4 * k, 60:100] = (230, 230, 230, 255)
                comps.append(comp.tobytes())
                layers.append(layer.tobytes())
            path, mask = os.path.join(tmp, "c.mp4"), os.path.join(tmp, "layer.mov")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r",
                            "30", "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-colorspace", "bt709",
                            "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", path], input=b"".join(comps), check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (w, h), "-r",
                            "30", "-i", "-", "-c:v", "png", "-pix_fmt", "rgba", mask], input=b"".join(layers), check=True)
            out = os.path.join(tmp, "r.json")
            d = LA.measure_regions(path, out, frames=6, height=180, mask_video=mask)
            self.assertGreaterEqual(len(d["frames"]), 5)
            for row in d["frames"]:
                want = (24 + 4 * row["n"]) * 40 / float(w * h)
                self.assertAlmostEqual(row["m"]["frame.person_share"], want, delta=0.001, msg=row["n"])

    def test_colours_come_back_as_they_went_in(self):
        # tagged BT.709 read as BT.709: the grey blocks come back within a few steps of 255
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            frames = synthetic_video(path, cuts=(), flash=10 ** 6, bars=0, seconds=1)
            info = LA.probe(path)
            got = next(iter(LA.read_frames(path, info, [10], height=180)))[1]
        want = frames[10].astype(np.float64) / 255.0
        self.assertLess(float(np.abs(ndi.uniform_filter(got - want, (9, 9, 1))).mean()), 2.0 / 255)


def scene(h=720, w=1280, person_lab=(70.0, 10.0, 20.0), stage_lab=(20.0, 5.0, -25.0), radius=200.0, centre=None):
    """a stage of one colour and a round person of another (CIE L*a*b*): the picture, the person's mask and each
    pixel's distance from the person's centre"""
    lab = np.zeros((h, w, 3))
    lab[...] = stage_lab
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = centre or (h / 2.0, w / 2.0)
    d = np.hypot(yy - cy, xx - cx)
    m = d <= radius
    lab[m] = person_lab
    return LA.lab_to_rgb(lab), m.astype(np.float64), d


@unittest.skipUnless(LA, NEEDS)
class RegionTest(unittest.TestCase):
    """the person and the stage read apart (the person's mask given): a dark stage round a bright person must not read
    as the grade of the whole picture"""

    def test_the_person_and_the_stage_are_read_apart(self):
        picture, mask, _ = scene()
        r = LA.region_measures(picture, mask)
        self.assertAlmostEqual(r["person.L_p50"], 70.0, delta=1.0)
        self.assertAlmostEqual(r["stage.L_p50"], 20.0, delta=1.0)
        self.assertAlmostEqual(r["frame.person_share"], mask.mean(), delta=0.005)
        self.assertAlmostEqual(r["contrast.person_stage"], 50.0, delta=1.5)
        # a warm person on a blue stage: the whole frame's split toning reads the two colours as its shadows and its
        # highlights; inside the person and inside the stage there is none
        whole = LA.colour(picture, LA.rgb_to_lab(picture))["split.teal_orange"]
        self.assertGreater(whole, 15.0)
        self.assertLess(abs(r["person.teal_orange"]), 1.0)
        self.assertLess(abs(r["stage.teal_orange"]), 1.0)

    def test_the_light_on_the_face_is_read_apart_from_the_costume(self):
        # typorev: the references' person read 44.6 L* against ours 76, their faces 78 against ours 80: the references'
        # dark costumes, not their light.  The cheeks of a face found on the person (its box's rows 0.55 to 0.85,
        # columns 0.25 to 0.75) read the light on her whatever she wears
        for costume in (15.0, 85.0):
            picture, mask, _ = scene(person_lab=(costume, 0.0, 0.0), stage_lab=(20.0, 0.0, 0.0))
            lab = LA.rgb_to_lab(picture)
            lab[300:380, 600:680] = (78.0, 14.0, 10.0)                  # a face of skin lit to 78
            r = LA.region_measures(LA.lab_to_rgb(lab), mask, faces=[(600, 300, 80, 80), (790, 300, 100, 100)])
            self.assertAlmostEqual(r["face.L"], 78.0, delta=1.0)
            self.assertAlmostEqual(r["face.chroma"], math.hypot(14.0, 10.0), delta=1.0)
            self.assertAlmostEqual(r["face.hue"], math.degrees(math.atan2(10.0, 14.0)), delta=3.0)
            # a box whose middle is off her, though its cheeks touch her edge (another dancer beside her): not hers
            self.assertEqual(r["face.count"], 1)
            self.assertAlmostEqual(r["person.L_p50"], costume, delta=2.0)
        self.assertTrue(math.isnan(LA.region_measures(picture, mask)["face.L"]))        # no faces given: none read

    def test_the_colour_of_the_light_on_the_person_and_on_the_stage(self):
        # the person's brightest tenth lit red, the stage's lit blue (the rest grey): each region's key light
        picture, mask, _ = scene()
        lab = LA.rgb_to_lab(picture)
        inside = mask > 0.5
        out = ~inside
        lab[..., 1:] = 0.0
        rng = np.random.default_rng(2)
        lab[..., 0] = np.where(inside, 50.0, 20.0) + rng.uniform(-3, 3, lab.shape[:2])
        lit_p = inside & (rng.uniform(size=inside.shape) < 0.08)
        lit_s = out & (rng.uniform(size=inside.shape) < 0.08)
        lab[lit_p, 0], lab[lit_p, 1], lab[lit_p, 2] = 75.0, 45.0, 25.0          # red light: hue about 29 degrees
        lab[lit_s, 0], lab[lit_s, 1], lab[lit_s, 2] = 45.0, 10.0, -45.0         # blue light: hue about 283 degrees
        r = LA.region_measures(LA.lab_to_rgb(lab), mask)
        self.assertAlmostEqual(r["person.key_hue"] % 360.0, 29.0, delta=8.0)
        self.assertAlmostEqual(r["stage.key_hue"] % 360.0, 283.0, delta=8.0)            # -77 degrees
        self.assertGreater(r["person.key_chroma"], 25.0)
        self.assertGreater(r["stage.key_chroma"], 25.0)

    def test_split_toning_inside_the_person(self):
        picture, mask, _ = scene()
        lab = LA.rgb_to_lab(picture)
        inside = mask > 0.5
        x = np.arange(lab.shape[1], dtype=np.float64)
        ramp = (40.0 + 52.0 * np.clip((x - 440.0) / 400.0, 0.0, 1.0))[None, :].repeat(lab.shape[0], axis=0)
        lab[inside, 0] = ramp[inside]
        lab[inside, 1:] = 0.0
        lo, hi = np.percentile(ramp[inside], [25, 75])
        dark, bright = inside & (ramp <= lo), inside & (ramp >= hi)  # the person's darkest and brightest quarters
        lab[dark, 1], lab[dark, 2] = -8.0, -8.0                   # teal shadows
        lab[bright, 1], lab[bright, 2] = 8.0, 12.0                # orange lights
        r = LA.region_measures(LA.lab_to_rgb(lab), mask)
        self.assertGreater(r["person.teal_orange"], 12.0)
        self.assertLess(abs(r["stage.teal_orange"]), 1.0)
        self.assertGreater(r["person.L_p90"] - r["person.L_p10"], 30.0)

    def test_a_rim_light_brightens_the_inside_of_the_outline(self):
        picture, mask, d = scene(person_lab=(50.0, 0.0, 0.0), stage_lab=(15.0, 0.0, 0.0))
        lab = LA.rgb_to_lab(picture)
        rim = (d <= 200.0) & (d > 194.0)                          # 0 to 6 px inside the outline
        lab[rim, 0] = 80.0
        lit = LA.region_measures(LA.lab_to_rgb(lab), mask)
        plain = LA.region_measures(picture, mask)
        self.assertGreater(lit["rim.ratio"], 1.5)
        self.assertAlmostEqual(plain["rim.ratio"], 1.0, delta=0.05)
        # an outline (a dark line 1.5 px wide on the edge, as MMD draws) is no rim and no shadow of the edge
        outlined = LA.rgb_to_lab(picture)
        outlined[(d <= 200.0) & (d > 198.5), 0] = 5.0
        self.assertAlmostEqual(LA.region_measures(LA.lab_to_rgb(outlined), mask)["rim.ratio"], 1.0, delta=0.05)

    def test_a_glow_round_the_person_is_read_outside_the_outline(self):
        picture, mask, _ = scene(person_lab=(95.0, 0.0, 0.0), stage_lab=(10.0, 0.0, 0.0))
        lin = LA.srgb_to_linear(picture)
        halos = []
        for k in (0.0, 0.3, 0.6):
            glow = k * ndi.gaussian_filter(mask, 14.0)            # a glow of the person, added in linear light
            glowing = np.clip(LA.linear_to_srgb(lin + glow[..., None]), 0.0, 1.0)
            halos.append(LA.region_measures(glowing, mask)["halo.share"])
        self.assertLess(abs(halos[0]), 0.01)
        self.assertGreater(halos[1], 0.05)
        self.assertAlmostEqual(halos[2] / halos[1], 2.0, delta=0.5)
        # a light of the stage far from the person is not the person's glow
        far = lin.copy()
        far[40:80, 40:80] = 1.0
        far = far + 0.6 * ndi.gaussian_filter(far * (far >= 0.99), (14.0, 14.0, 0.0))
        far = np.clip(LA.linear_to_srgb(far), 0.0, 1.0)
        self.assertLess(abs(LA.region_measures(far, mask)["halo.share"]), 0.01)

    def test_the_same_glow_shows_more_on_a_dark_stage(self):
        # the same light added round the person (a share of its edge's light) lifts a dark stage by more L* than a
        # bright one: halo.share reads the light, halo.dL what the eye sees of it
        reads = {}
        for stage_l in (8.0, 60.0):
            picture, mask, _ = scene(person_lab=(90.0, 0.0, 0.0), stage_lab=(stage_l, 0.0, 0.0))
            lin = LA.srgb_to_linear(picture)
            glowing = np.clip(LA.linear_to_srgb(lin + 0.3 * ndi.gaussian_filter(mask, 14.0)[..., None]), 0.0, 1.0)
            reads[stage_l] = LA.region_measures(glowing, mask)
            self.assertLess(abs(LA.region_measures(picture, mask)["halo.dL"]), 0.5)
        self.assertGreater(reads[8.0]["halo.dL"], 2.0 * reads[60.0]["halo.dL"])
        self.assertGreater(reads[8.0]["halo.dL"], 10.0)

    def test_background_blur_is_read_on_the_stage_only(self):
        tex = ndi.gaussian_filter(blocks(720, 1280, seed=13, n=1600, low=0.1, high=0.9), 1.0)
        person = ndi.gaussian_filter(blocks(720, 1280, seed=14, n=1600, low=0.1, high=0.9), 1.0)
        mask = np.zeros((720, 1280))
        mask[160:560, 440:840] = 1.0
        sharp = np.where(mask > 0.5, person, tex)
        soft = np.where(mask > 0.5, person, ndi.gaussian_filter(tex, 8.0))
        r_soft = LA.region_measures(rgb(soft), mask)
        r_sharp = LA.region_measures(rgb(sharp), mask)
        self.assertLess(r_soft["dof.person_blur"], 2.5)
        self.assertAlmostEqual(r_soft["dof.stage_blur"], 8.0, delta=3.0)
        self.assertGreater(r_soft["dof.stage_ratio"], 2.5)
        self.assertLess(r_sharp["dof.stage_ratio"], 1.6)

    def test_the_glow_of_the_stage_lights_and_of_the_person_apart(self):
        # small lights on the stage with a glow, and a bright person without one
        base = highlights(720, 1280, [(2 * y, 2 * x) for y, x in POINTS if x > 300], 8)
        lights = add_glow(base, 8.0, 1.0)
        mask = np.zeros((720, 1280))
        mask[200:600, 60:400] = 1.0
        lights[200:600, 60:400] = 0.95
        r = LA.region_measures(lights, mask)
        self.assertGreater(r["bloom.stage_strength"], 0.05)
        self.assertLess(r["bloom.person_strength"], 0.01)
        self.assertGreater(r["stage.lights"], 0.0)                  # the stage holds lights (Y' 0.9 and up)
        picture, m2, _ = scene()
        self.assertEqual(LA.region_measures(picture, m2)["stage.lights"], 0.0)

    def test_the_glows_are_read_off_the_other_region(self):
        # a person with a bright middle in a mid-grey band, no glow: the person's glow is read only off the person (the
        # band next to its bright middle is the person, not its glow)
        h, w = 720, 1280
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.hypot(yy - 360.0, xx - 640.0)
        grey = np.where(d <= 150.0, 0.95, np.where(d <= 200.0, 0.7, 0.05))
        mask = (d <= 200.0).astype(np.float64)
        r = LA.region_measures(rgb(grey), mask)
        # (no glow off the person: none read, or nan when the bright middle lies too far inside to read one)
        self.assertFalse(r["bloom.person_strength"] > 0.02, r["bloom.person_strength"])
        # a light of the stage seen through a gap in a bright person (between the arms) reads as the same light alone:
        # its rings and the level it falls to are read on the stage, not on the person round the gap
        lone = add_glow(highlights(720, 1280, [(360, 900)], 8), 8.0, 1.0)
        m_gap = np.ones((h, w))
        m_gap[:, 870:930] = 0.0                                       # the stage only in a gap 60 px wide
        through = np.where(m_gap[..., None] > 0.5, 0.95, lone)
        r_alone = LA.region_measures(lone, np.zeros((h, w)))
        r_gap = LA.region_measures(through, m_gap)
        self.assertAlmostEqual(r_gap["bloom.stage_strength"] / r_alone["bloom.stage_strength"], 1.0, delta=0.2)

    def test_a_person_that_matches_what_lies_behind_her_edge_merges_with_it(self):
        # a white person on a white sign: her outline does not show (the colours inside and outside it alike); on a dark
        # stage it does; half of her outline over the sign: half of it merges
        apart = LA.region_measures(*scene(person_lab=(92.0, 0.0, 2.0), stage_lab=(15.0, 5.0, -20.0))[:2])
        same = LA.region_measures(*scene(person_lab=(92.0, 0.0, 2.0), stage_lab=(90.0, 1.0, 4.0))[:2])
        self.assertGreater(apart["edge.dE"], 60.0)
        self.assertLess(apart["edge.merge"], 0.01)
        self.assertLess(same["edge.dE"], 5.0)
        self.assertGreater(same["edge.merge"], 0.99)
        picture, mask, d = scene(person_lab=(92.0, 0.0, 2.0), stage_lab=(15.0, 5.0, -20.0))
        lab = LA.rgb_to_lab(picture)
        right = (~(mask > 0.5)) & (np.arange(picture.shape[1])[None, :] >= picture.shape[1] / 2.0)
        lab[right] = (90.0, 1.0, 4.0)                              # a white sign behind her right half
        half = LA.region_measures(LA.lab_to_rgb(lab), mask)
        self.assertAlmostEqual(half["edge.merge"], 0.5, delta=0.08)

    def test_the_stage_is_read_clear_of_the_person_s_edge(self):
        # the model's outline a few px inside the person's: the person's bright edge must not be read as the stage's
        picture, _, d = scene(person_lab=(97.0, 0.0, 0.0), stage_lab=(10.0, 0.0, 0.0), radius=200.0)
        small = (d <= 194.0).astype(np.float64)
        r = LA.region_measures(picture, small)
        self.assertEqual(r["stage.lights"], 0.0)
        self.assertLess(r["stage.L_p90"], 11.0)

    def test_no_person_leaves_the_person_measures_empty(self):
        picture, _, _ = scene()
        r = LA.region_measures(picture, np.zeros(picture.shape[:2]))
        self.assertEqual(r["frame.person_share"], 0.0)
        self.assertTrue(math.isnan(r["person.L_p50"]))
        self.assertTrue(math.isnan(r["rim.ratio"]))
        self.assertTrue(np.isfinite(r["stage.L_p50"]))
        for key in LA.REGION_MEASURES:
            self.assertIn(key, r, key)

    def test_the_model_sees_the_frame_letterboxed_and_its_mask_comes_back_in_place(self):
        # a stand-in for the model that answers its own input's red: the mask must come back where the red was
        class Echo:
            def get_inputs(self):
                return [type("I", (), {"name": "img", "shape": [1, 3, 1024, 1024]})()]

            def run(self, outputs, feed):
                x = feed["img"]
                self.seen = x.shape
                return [x[:, :1]]

        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[100:300, 900:1100, 0] = 255
        echo = Echo()
        m = LA.person_mask(frame, session=echo)
        self.assertEqual(echo.seen, (1, 3, 1024, 1024))
        self.assertEqual(m.shape, (720, 1280))
        self.assertGreater(m[110:290, 910:1090].min(), 0.9)
        self.assertLess(m[:90].max(), 0.1)
        self.assertLess(m[:, :880].max(), 0.1)


def _ocr_ready():
    try:
        import importlib.util as u
        return bool(u.find_spec("easyocr")) and os.path.isfile(os.path.join(os.path.expanduser("~"), ".EasyOCR", "model",
                                                                            "craft_mlt_25k.pth"))
    except Exception:
        return False


@unittest.skipUnless(LA, NEEDS)
class TextTest(unittest.TestCase):
    def test_where_and_how_big_the_text_is(self):
        # four frames of a 720 line picture: a lyric line at the bottom in two, a watermark in a corner in all
        shape = (720, 1280)
        mark = (40, 30, 200, 60)                       # x0, y0, x1, y1: top left corner, 30 px tall
        lyric = (340, 620, 940, 670)                   # bottom middle, 50 px tall
        frames = [[mark, lyric], [mark], [mark, lyric], [mark]]
        t = LA.text_summary(frames, shape, unit=1.0)
        self.assertEqual(t["text.frames"], 1.0)
        self.assertEqual(t["text.height"], 30.0)                     # the median of the boxes' heights
        self.assertAlmostEqual(t["text.bottom"], 2 / 6.0, delta=1e-9)
        self.assertAlmostEqual(t["text.top"], 4 / 6.0, delta=1e-9)
        self.assertAlmostEqual(t["text.corner"], 4 / 6.0, delta=1e-9)
        area = (160 * 30 + 0.5 * 600 * 50) / float(720 * 1280)
        self.assertAlmostEqual(t["text.area"], area, delta=1e-6)
        none = LA.text_summary([[], []], shape, unit=1.0)
        self.assertEqual(none["text.frames"], 0.0)
        self.assertTrue(math.isnan(none["text.height"]))

    @unittest.skipUnless(LA and _ocr_ready(), "needs EasyOCR and its CRAFT model in ~/.EasyOCR (hinata has them)")
    def test_text_drawn_on_a_frame_is_found(self):
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGB", (1280, 720), (30, 40, 60))
        font = None
        for p in ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/arial.ttf"):
            if os.path.isfile(p):
                font = ImageFont.truetype(p, 40)
                break
        ImageDraw.Draw(im).text((100, 600), "Model: someone  Motion: mover", fill=(255, 255, 255), font=font)
        boxes = LA.text_boxes(np.asarray(im), LA.text_reader())
        self.assertTrue(any(b[1] < 660 and b[3] > 600 and b[0] < 400 for b in boxes), boxes)
        empty = LA.text_boxes(np.full((720, 1280, 3), 90, np.uint8), LA.text_reader())
        self.assertEqual(empty, [])

if __name__ == "__main__":
    unittest.main()
