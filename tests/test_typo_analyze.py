"""tools/typo_analyze.py: the kinetic typography of a video (where and when its text comes and goes, how it moves, what it
looks like, and how it goes with the voice and the beat) measured in numbers.

Every measure is tried on text made for it, whose answer is known from how it was made: character maps drawn where the
characters are, lines that slide, grow, fade or come one character after another by known amounts, text drawn with a
known colour, outline, shadow and glow, voices whose phrases start at known times.  The text detector (CRAFT, through
EasyOCR) is heavy, so most tests feed the tool's own steps with maps drawn the way CRAFT draws them (a Gaussian on every
character, a link between neighbours); the detector itself is tried where EasyOCR is installed (hinata).
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


def load_tool(name="typo_analyze"):
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TA = load_tool() if np is not None else None
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
NEEDS = "needs numpy, scipy and OpenCV"


def craft_like(shape, chars, sigma_scale=0.32, link=True):
    """maps drawn the way CRAFT draws them: the region score is a Gaussian on every character (centre cx, cy, size s in
    map px), the link score a Gaussian on the middle between two neighbours of one line.  chars: [(cx, cy, s, line)]"""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    score = np.zeros(shape)
    links = np.zeros(shape)
    for cx, cy, s, _ in chars:
        sig = sigma_scale * s
        score = np.maximum(score, np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sig * sig)))
    if link:
        by_line = {}
        for c in chars:
            by_line.setdefault(c[3], []).append(c)
        for cs in by_line.values():
            cs = sorted(cs, key=lambda c: (c[0], c[1]))
            for a, b in zip(cs, cs[1:]):
                mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
                sig = sigma_scale * (a[2] + b[2]) / 2.0
                links = np.maximum(links, np.exp(-((xx - mx) ** 2 + (yy - my) ** 2) / (2 * sig * sig)))
    return score.astype(np.float32), links.astype(np.float32)


def line_chars(x0, y, n, size, gap=1.0, line=0, vertical=False):
    """n characters of one line from (x0, y), size map px, centres size * gap apart"""
    if vertical:
        return [(x0, y + i * size * gap, size, line) for i in range(n)]
    return [(x0 + i * size * gap, y, size, line) for i in range(n)]


@unittest.skipUnless(TA, NEEDS)
class MapsTest(unittest.TestCase):
    def test_a_line_is_one_box_round_its_characters(self):
        chars = line_chars(40, 50, 6, 12)                      # 6 characters, 12 map px, from x 40 to 100
        score, link = craft_like((120, 200), chars)
        boxes = TA.text_boxes(score, link, ratio=2.0)
        self.assertEqual(len(boxes), 1)
        b = boxes[0]
        # in frame px (ratio 2): the characters span 34..106 map px across and 44..56 down
        self.assertAlmostEqual(b["cx"], 2 * 70, delta=4)
        self.assertAlmostEqual(b["cy"], 2 * 50, delta=3)
        self.assertGreater(b["w"], 2 * 60)
        self.assertLess(b["h"], 2 * 22)
        self.assertLess(abs(b["angle"]), 5)
        self.assertFalse(b["vertical"])

    def test_two_lines_apart_are_two_boxes(self):
        chars = line_chars(30, 30, 5, 10, line=0) + line_chars(30, 90, 4, 10, line=1)
        score, link = craft_like((130, 160), chars)
        boxes = sorted(TA.text_boxes(score, link, ratio=1.0), key=lambda b: b["cy"])
        self.assertEqual(len(boxes), 2)
        self.assertAlmostEqual(boxes[0]["cy"], 30, delta=2)
        self.assertAlmostEqual(boxes[1]["cy"], 90, delta=2)

    def test_a_column_of_characters_is_a_vertical_box(self):
        chars = line_chars(60, 20, 6, 12, vertical=True)
        score, link = craft_like((120, 120), chars)
        boxes = TA.text_boxes(score, link, ratio=1.0)
        self.assertEqual(len(boxes), 1)
        self.assertTrue(boxes[0]["vertical"])
        self.assertGreater(boxes[0]["w"], 60)                 # w is the long side, along the text

    def test_weak_maps_make_no_box(self):
        chars = line_chars(40, 50, 6, 12)
        score, link = craft_like((120, 200), chars)
        self.assertEqual(TA.text_boxes(score * 0.5, link * 0.5, ratio=1.0), [])    # the peaks under the text threshold

    def test_peaks_are_the_characters(self):
        chars = line_chars(30.0, 40.0, 5, 12, gap=1.1) + line_chars(35.5, 90.0, 3, 16, gap=1.1, line=1)
        score, _ = craft_like((130, 120), chars)
        peaks = TA.char_peaks(score, ratio=2.0)
        self.assertEqual(len(peaks), len(chars))
        want = sorted((2 * c[0], 2 * c[1]) for c in chars)
        got = sorted((p[0], p[1]) for p in peaks)
        for (wx, wy), (gx, gy) in zip(want, got):
            self.assertAlmostEqual(gx, wx, delta=1.2)
            self.assertAlmostEqual(gy, wy, delta=1.2)

    def test_a_peak_knows_the_size_of_its_character(self):
        # sizes 10 and 20 map px read in the ratio 1 : 2 (the absolute size is calibrated on CRAFT, see SIZE_PER_BLOB)
        small, _ = craft_like((80, 80), [(40, 40, 10, 0)], link=False)
        big, _ = craft_like((80, 80), [(40, 40, 20, 0)], link=False)
        s1 = TA.char_peaks(small, ratio=1.0)[0][3]
        s2 = TA.char_peaks(big, ratio=1.0)[0][3]
        self.assertAlmostEqual(s2 / s1, 2.0, delta=0.15)


@unittest.skipUnless(TA, NEEDS)
class SampleTest(unittest.TestCase):
    def test_sample_frames_spread_at_the_rate(self):
        ns = TA.sample_frames(n_frames=300, fps=30, rate=2.0)
        self.assertEqual(ns[0], 0)
        self.assertEqual(ns[1] - ns[0], 15)
        self.assertEqual(len(ns), 20)
        ns60 = TA.sample_frames(n_frames=600, fps=60, rate=2.0)
        self.assertEqual(ns60[1] - ns60[0], 30)

    def test_detect_frames_with_a_given_detector(self):
        # a detector that sees one line from frame 10 on: the samples say where and when
        def detector(rgb):
            k = int(rgb[0, 0, 0])                              # the frame number is written in the first pixel
            if k < 10:
                return np.zeros((60, 100), np.float32), np.zeros((60, 100), np.float32), 2.0
            s, l = craft_like((60, 100), line_chars(20, 30, 5, 10))
            return s, l, 2.0
        frames = {}
        for n in range(0, 30, 5):
            a = np.zeros((120, 200, 3), np.uint8)
            a[0, 0, 0] = n
            frames[n] = a
        samples = TA.detect_samples(frames, detector, fps=30.0)
        self.assertEqual([s["n"] for s in samples], [0, 5, 10, 15, 20, 25])
        self.assertEqual([len(s["boxes"]) for s in samples], [0, 0, 1, 1, 1, 1])
        self.assertEqual(len(samples[2]["chars"]), 5)
        self.assertAlmostEqual(samples[2]["t"], 10 / 30.0)


def box(cx, cy, w, h, vertical=False, score=0.9):
    return {"x0": cx - w / 2.0, "y0": cy - h / 2.0, "x1": cx + w / 2.0, "y1": cy + h / 2.0, "cx": cx, "cy": cy,
            "w": w, "h": h, "angle": 90.0 if vertical else 0.0, "vertical": vertical, "score": score, "area": w * h}


def samples_of(boxes_by_sample, step=15, fps=30.0):
    return [{"n": i * step, "t": i * step / fps, "boxes": bs, "chars": []} for i, bs in enumerate(boxes_by_sample)]


@unittest.skipUnless(TA, NEEDS)
class LinkTest(unittest.TestCase):
    def test_a_line_that_stays_is_one_track(self):
        ss = samples_of([[], [], [box(300, 600, 400, 40)], [box(301, 600, 400, 40)], [box(300, 601, 398, 40)], []])
        tracks = TA.link_tracks(ss)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["samples"], [2, 3, 4])

    def test_two_lines_at_once_are_two_tracks(self):
        ss = samples_of([[box(300, 500, 400, 40), box(300, 600, 300, 40)]] * 3)
        tracks = TA.link_tracks(ss)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(sorted(len(t["samples"]) for t in tracks), [3, 3])

    def test_a_line_that_grows_a_character_at_a_time_is_one_track(self):
        ss = samples_of([[box(120 + 20 * k, 400, 40 + 40 * k, 40)] for k in range(6)])
        self.assertEqual(len(TA.link_tracks(ss)), 1)

    def test_a_line_that_slides_is_one_track(self):
        ss = samples_of([[box(200 + 50 * k, 400, 300, 40)] for k in range(5)])        # 50 px a sample, h 40
        tracks = TA.link_tracks(ss)
        self.assertEqual(len(tracks), 1)

    def test_a_line_far_away_of_another_size_is_another_track(self):
        ss = samples_of([[box(300, 600, 400, 40)], [box(900, 150, 200, 90)]])
        self.assertEqual(len(TA.link_tracks(ss)), 2)

    def test_a_gap_of_one_sample_is_bridged_two_are_not(self):
        one = samples_of([[box(300, 600, 400, 40)], [], [box(300, 600, 400, 40)]])
        two = samples_of([[box(300, 600, 400, 40)], [], [], [box(300, 600, 400, 40)]])
        self.assertEqual(len(TA.link_tracks(one)), 1)
        self.assertEqual(len(TA.link_tracks(two)), 2)

    def test_the_words_of_one_line_are_joined(self):
        # CRAFT parts a line at its spaces: two boxes on one baseline, a short gap apart, always together
        ss = samples_of([[box(200, 400, 160, 40), box(400, 400, 200, 40)]] * 4)
        tracks = TA.link_tracks(ss)
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0]["box"]["x0"], 120, delta=1)
        self.assertAlmostEqual(tracks[0]["box"]["x1"], 500, delta=1)


# ---- synthetic animated text and a detector that reads it from the pixels ----------------------------------------------

def pixel_detector(rgb, least=0.5):
    """a stand-in for CRAFT on the synthetic frames: the bright blocks (Y' over `least`) are the characters, each a
    Gaussian of its size in a half size map, neighbours on one row linked"""
    y = rgb.astype(np.float64).mean(axis=2) / 255.0
    lab, n = ndi.label(y > least)
    chars = []
    for k, sl in enumerate(ndi.find_objects(lab)):
        if sl is None:
            continue
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if hh * ww < 4:
            continue
        chars.append([(sl[1].start + sl[1].stop - 1) / 4.0, (sl[0].start + sl[0].stop - 1) / 4.0, max(hh, ww) / 2.0 / 0.75])
    # rows: neighbours within 1.6 sizes across and half a size up or down
    line = list(range(len(chars)))
    def find(i):
        while line[i] != i:
            i = line[i]
        return i
    for i, a in enumerate(chars):
        for j, b in enumerate(chars):
            if i < j and abs(a[1] - b[1]) < 0.5 * a[2] and abs(a[0] - b[0]) < 1.6 * a[2]:
                line[find(i)] = find(j)
    cs = [(c[0], c[1], c[2], find(i)) for i, c in enumerate(chars)]
    h, w = y.shape
    score, link = craft_like(((h + 1) // 2, (w + 1) // 2), cs)
    return score, link, 2.0


def draw_text(h=180, w=320, n_chars=6, size=16, centre=(160.0, 120.0), alpha=1.0, offset=(0.0, 0.0), scale=1.0,
              char_alpha=None, bg=0.15, seed=0, colour=(1.0, 1.0, 1.0), blur=0.0, ring=False, split=0.0, tear=None):
    """a frame (uint8) with a line of n block characters of `size` px centred on `centre`, moved by `offset`, scaled by
    `scale` about its centre, at `alpha` (each character also at char_alpha[k]), on a dark noisy ground.  ring: the
    blocks hollow (another text in the same place); split: red drawn that many px right and blue left of green;
    tear: (row0, row1, px) the rows between moved sideways"""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), bg) + rng.normal(0, 0.01, (h, w, 3))
    yy, xx = np.mgrid[0:h, 0:w]
    gap = 1.25 * size
    cx0 = centre[0] - gap * (n_chars - 1) / 2.0
    for k in range(n_chars):
        a = alpha * (1.0 if char_alpha is None else char_alpha[k])
        if a <= 0:
            continue
        x = centre[0] + scale * (cx0 + k * gap - centre[0]) + offset[0]
        y = centre[1] + offset[1]
        half = 0.4 * size * scale
        for c in range(3):
            xs = xx - (split if c == 0 else -split if c == 2 else 0.0)
            if tear is not None:
                xs = np.where((yy >= tear[0]) & (yy < tear[1]), xs - tear[2], xs)
            inside = (np.abs(xs - x) <= half) & (np.abs(yy - y) <= half)
            if ring:
                inside &= ~((np.abs(xs - x) <= half * 0.5) & (np.abs(yy - y) <= half * 0.5))
            inside = inside.astype(np.float64)
            if blur > 0:
                inside = ndi.gaussian_filter(inside, blur)
            img[..., c] = img[..., c] * (1 - a * inside) + colour[c] * a * inside
    return np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)


def clip_of(alpha_of, n_frames=60, **kw):
    """{n: frame} of a clip whose text at frame n is drawn with the keywords alpha_of(n) returns (merged with kw)"""
    out = {}
    for n in range(n_frames):
        args = dict(kw)
        args.update(alpha_of(n))
        out[n] = draw_text(seed=n, **args)
    return out


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1.0 - (1.0 - t) ** 3


@unittest.skipUnless(TA, NEEDS)
class TrackMeasureTest(unittest.TestCase):
    fps = 30.0

    def measure(self, frames, rate=2.0, texts=1):
        ns = TA.sample_frames(len(frames), self.fps, rate)
        samples = TA.detect_samples({n: frames[n] for n in ns}, pixel_detector, self.fps)
        tracks = TA.link_tracks(samples)
        self.assertEqual(len(tracks), 1, [t["samples"] for t in tracks])
        plan = TA.refine_plan(tracks[0], samples, len(frames), self.fps)
        got = {n: frames[n] for n in plan}
        out = TA.measure_track(got, tracks[0], pixel_detector, self.fps, bounds=(0, len(frames) - 1))
        self.assertEqual(len(out), texts, [m["frames"] for m in out])
        return out[0] if texts == 1 else out

    def test_a_fade_in_and_out(self):
        def look(n):
            if n < 10 or n > 51:
                return {"alpha": 0.0}
            if n <= 20:
                return {"alpha": (n - 10) / 10.0}
            if n <= 45:
                return {"alpha": 1.0}
            return {"alpha": (51 - n) / 6.0}
        m = self.measure(clip_of(look))
        self.assertTrue(10 <= m["frames"]["first"] <= 12, m["frames"])
        self.assertTrue(19 <= m["frames"]["full"] <= 21, m["frames"])
        self.assertTrue(44 <= m["frames"]["hold_end"] <= 46, m["frames"])
        self.assertTrue(49 <= m["frames"]["last"] <= 51, m["frames"])
        self.assertIn("fade", m["enter"]["kinds"])
        self.assertNotIn("move", m["enter"]["kinds"])
        self.assertNotIn("scale", m["enter"]["kinds"])
        self.assertIn("fade", m["exit"]["kinds"])

    def test_a_slide_in_from_the_left(self):
        def look(n):
            if n < 10:
                return {"alpha": 0.0}
            return {"offset": (-150.0 * (1.0 - ease_out((n - 10) / 10.0)), 0.0)}
        m = self.measure(clip_of(look))
        self.assertIn("move", m["enter"]["kinds"])
        self.assertAlmostEqual(m["enter"]["dx"], -150.0 * (1 - ease_out(0.0)), delta=14)
        self.assertLess(abs(m["enter"]["dy"]), 4)
        self.assertEqual(m["enter"]["from"], "left")
        self.assertTrue(9 <= m["enter"]["frames"] <= 12, m["enter"])
        self.assertNotIn("fade", m["enter"]["kinds"])

    def test_characters_one_after_another(self):
        def look(n):
            return {"char_alpha": [1.0 if n >= 10 + 3 * k else 0.0 for k in range(6)]}
        m = self.measure(clip_of(look))
        st = m["enter"]["stagger"]
        self.assertAlmostEqual(st["per_char_s"], 3 / 30.0, delta=0.02)
        self.assertEqual(st["order"], "left_to_right")
        self.assertGreater(st["r2"], 0.9)
        self.assertIn("stagger", m["enter"]["kinds"])
        self.assertTrue(14 <= m["enter"]["frames"] <= 17, m["enter"])

    def test_a_zoom_from_twice_the_size(self):
        def look(n):
            if n < 10:
                return {"alpha": 0.0}
            return {"scale": 2.0 - ease_out((n - 10) / 10.0)}
        m = self.measure(clip_of(look))
        self.assertIn("scale", m["enter"]["kinds"])
        self.assertAlmostEqual(m["enter"]["scale"], 2.0, delta=0.25)

    def test_a_line_that_pops_in(self):
        m = self.measure(clip_of(lambda n: {"alpha": 1.0 if n >= 10 else 0.0}))
        self.assertTrue(9 <= m["frames"]["first"] <= 10, m["frames"])
        self.assertLessEqual(m["enter"]["frames"], 1)
        self.assertEqual(m["enter"]["kinds"], ["cut"])

    def test_a_line_still_there_at_the_end_has_not_gone(self):
        m = self.measure(clip_of(lambda n: {"alpha": 1.0 if n >= 10 else 0.0}))
        self.assertEqual(m["exit"]["kinds"], ["none"])
        self.assertTrue(m["exit"]["cut_off"])

    def test_a_blur_that_clears_is_a_blur_not_a_fade(self):
        def look(n):
            if n < 10:
                return {"alpha": 0.0}
            return {"blur": max(0.0, 4.0 * (1 - (n - 10) / 8.0))}
        m = self.measure(clip_of(look))
        self.assertIn("blur", m["enter"]["kinds"])
        self.assertNotIn("fade", m["enter"]["kinds"])
        self.assertTrue(6 <= m["enter"]["frames"] <= 9, m["enter"])

    def test_a_fade_is_not_a_blur(self):
        m = self.measure(clip_of(lambda n: {"alpha": min(1.0, max(0.0, (n - 10) / 10.0))}))
        self.assertIn("fade", m["enter"]["kinds"])
        self.assertNotIn("blur", m["enter"]["kinds"])
        self.assertAlmostEqual(m["enter"]["fade_s"], 10 / 30.0, delta=0.05)


    def test_another_line_in_the_same_place_is_another_text(self):
        def look(n):
            if n < 10 or n > 55:
                return {"alpha": 0.0}
            if n < 30:
                return {}
            return {"ring": True, "n_chars": 4, "size": 20, "centre": (150.0, 121.0)}    # another line where the first was
        a, b = self.measure(clip_of(look), texts=2)
        self.assertTrue(9 <= a["frames"]["first"] <= 10, a["frames"])
        self.assertTrue(28 <= a["frames"]["last"] <= 29, a["frames"])
        self.assertTrue(30 <= b["frames"]["first"] <= 31, b["frames"])
        self.assertTrue(54 <= b["frames"]["last"] <= 55, b["frames"])

    def test_a_glitch_coming_in(self):
        def look(n):
            if n < 9:
                return {"alpha": 0.0}
            if n < 15:                                       # the sample at 15 sees it whole
                return {"split": 4.0 if n % 2 == 0 else 0.0, "tear": (114, 120, 9.0) if n % 2 else None}
            return {}
        m = self.measure(clip_of(look))
        self.assertIn("glitch", m["enter"]["kinds"])
        self.assertGreater(m["enter"]["glitch"]["split_px"], 2.5)
        self.assertGreater(m["enter"]["glitch"]["torn_frames"], 0)

    def test_a_still_line_has_no_glitch(self):
        m = self.measure(clip_of(lambda n: {"alpha": 1.0 if n >= 10 else 0.0}))
        self.assertLess(m["enter"]["glitch"]["split_px"], 1.0)
        self.assertEqual(m["enter"]["glitch"]["torn_frames"], 0)
        self.assertLess(m["hold"]["split_px"], 1.0)


if __name__ == "__main__":
    unittest.main()
