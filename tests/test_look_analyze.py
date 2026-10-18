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
    import cv2  # noqa: F401
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
            got = LA.vignette(maps)["vignette.corner"]
            want = mask[r >= 0.9].mean() / mask[r <= 0.3].mean()
            self.assertAlmostEqual(got, want, delta=0.02)
        flat = np.array([np.random.default_rng(i).uniform(0.2, 0.8, (h, w)) for i in range(400)])
        self.assertAlmostEqual(LA.vignette(flat)["vignette.corner"], 1.0, delta=0.02)


@unittest.skipUnless(LA, NEEDS)
class TimeTest(unittest.TestCase):
    def test_flashes_are_short_bright_jumps(self):
        fps = 60
        rng = np.random.default_rng(8)
        series = 0.3 + 0.004 * rng.standard_normal(fps * 40)
        for start in (300, 900, 1500):
            series[start:start + 5] += 0.3           # three white flashes of 5 frames
        series[1800:] += 0.2                          # and a lasting change of light, which is no flash
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
class TextureTest(unittest.TestCase):
    unit = 0.5

    def test_the_noise_of_flat_areas(self):
        rng = np.random.default_rng(11)
        clean = blocks(360, 640, seed=2)
        for sigma in (2.0, 4.0, 8.0):
            noisy = clean + rng.normal(0, sigma / 255.0, clean.shape)
            got = LA.noise_spatial(noisy)["noise.spatial"]
            self.assertAlmostEqual(got, sigma, delta=0.2 * sigma + 0.3)
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


if __name__ == "__main__":
    unittest.main()
