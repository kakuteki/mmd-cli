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


GLYPH_HOLES = ((-0.45, -0.45), (0.45, -0.45), (-0.45, 0.45), (0.45, 0.45), (0.0, 0.0), (0.0, -0.5), (-0.5, 0.0))


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
            else:
                # every character its own: a small hole somewhere else in each (a line of like blocks would match
                # itself moved by a character)
                hx, hy = GLYPH_HOLES[k % len(GLYPH_HOLES)]
                inside &= ~((np.abs(xs - x - hx * half) <= half * 0.3) & (np.abs(yy - y - hy * half) <= half * 0.3))
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
class EdgeBoxTest(unittest.TestCase):
    """a box beyond the picture: a track followed through a punch (the picture zoomed) carries its box past the edge, and the
    ring round it was cut out with np.mgrid of a negative size (kinetic 2026-10-21: track stopped on the preview v3_P2 with
    ValueError, negative dimensions).  The ring of such a box is empty (its callers then take the ground they had), its
    strokes none; a box across the edge keeps the part of its ring inside the picture"""

    def setUp(self):
        self.y = np.random.default_rng(1).random((90, 160))

    def test_a_box_beyond_the_picture_has_no_ring_and_no_strokes(self):
        for box in ({"x0": 170.0, "x1": 200.0, "y0": 10.0, "y1": 20.0, "h": 10.0},      # right of it
                    {"x0": -60.0, "x1": -30.0, "y0": 10.0, "y1": 20.0, "h": 10.0},      # left
                    {"x0": 10.0, "x1": 40.0, "y0": 120.0, "y1": 130.0, "h": 10.0},      # below
                    {"x0": 10.0, "x1": 40.0, "y0": -50.0, "y1": -30.0, "h": 10.0}):     # above
            self.assertEqual(TA._ring(self.y, box, 0.3, 0.8).size, 0, box)
            ys, xs, sign, ground = TA.stroke_mask(self.y, box, [])
            self.assertEqual((len(ys), len(xs)), (0, 0), box)
            self.assertTrue(np.isfinite(ground), box)

    def test_a_box_across_the_edge_keeps_its_ring_inside_the_picture(self):
        box = {"x0": 150.0, "x1": 175.0, "y0": 40.0, "y1": 50.0, "h": 10.0}
        ring = TA._ring(self.y, box, 0.3, 0.8)
        y = self.y.copy()
        y[32:59, 142:148] = 7.0                                   # the ring's left part (x 142 to 147), inside the picture
        self.assertGreater(ring.size, 0)
        self.assertIn(7.0, set(TA._ring(y, box, 0.3, 0.8).tolist()))


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
        out = TA.measure_track(got, tracks[0], self.fps, bounds=(0, len(frames) - 1))
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

    def series_of(self, before, n_frames=60, at=30):
        """the stored readings of a still line that cuts in at frame `at`: before it, every frame reads `before`
        (ncc, alpha, ink) - the picture where it will stand; from it, the line whole"""
        rows = []
        for n in range(n_frames):
            ncc, alpha, ink = before if n < at else (1.0, 1.0, 1.0)
            rows.append({"n": n, "present": ncc >= TA.PRESENT_NCC, "ncc": ncc, "tx": 0.0, "ty": 0.0, "s": 1.0,
                         "split_px": 0.0, "torn": 0, "angle": float("nan"), "alpha": alpha, "alpha_vis": alpha,
                         "alpha_k": [alpha] * 6, "sharp": 1.0 if n >= at else float("nan"), "ink_vis": ink,
                         "ink_k": [ink] * 6, "bg_dx": float("nan"), "bg_dy": float("nan")})
        return rows

    def phases(self, rows):
        rb = {"x0": 100.0, "x1": 220.0, "y0": 112.0, "y1": 128.0, "cx": 160.0, "cy": 120.0, "h": 16.0, "w": 120.0}
        chars = [(110.0 + 20.0 * k, 120.0, 16.0, 0.9) for k in range(6)]
        return TA._track_summary(rows, {"vertical": False}, rb, chars, 45, self.fps, 0.0, 6, (0, 59))

    def test_the_picture_where_a_line_will_stand_is_not_the_line_coming(self):
        # typorev: RE: 踊 before two lines cut in (their stored readings): the lit street and the legs where one would
        # stand stood out by 0.26 to 0.37 of its strokes' contrast while its template matched there at 0.25 to 0.34; the
        # template of the other (the thin line and the wet street round it) matched the street at 0.5 to 0.6 while the
        # strokes' place stood out by 0.02 to 0.08.  Either alone saw the lines a second early, coming in by a fade
        for before in ((0.28, 0.28, 0.68), (0.55, 0.05, 0.6)):
            m = self.phases(self.series_of(before))
            self.assertEqual(m["frames"]["first"], 30, (before, m["frames"]))
            self.assertEqual(m["enter"]["kinds"], ["cut"], (before, m["enter"]))
            keep = TA._seen
            TA._seen = lambda r: bool(r["alpha"] > 0.15 or r["present"])           # the rule before typorev
            try:
                old = self.phases(self.series_of(before))
            finally:
                TA._seen = keep
            self.assertEqual(old["frames"]["first"], 0, (before, old["frames"]))
        # a line faint but surely there (both) is seen: a fade over a plain ground
        rows = self.series_of((0.9, 0.3, 0.3), at=30)
        for k, r in enumerate(rows[:30]):
            r.update({"alpha": 0.1 + 0.03 * k, "ink_vis": 0.1 + 0.03 * k, "ncc": 0.6 + 0.01 * k})
        self.assertEqual(self.phases(rows)["frames"]["first"], 2)

    def test_a_run_read_again_from_its_frames(self):
        # phases: a run's texts read again from their stored frames by the rules as they are now (the old seen read the
        # lit place of a line as the line from frame 0; read again, it comes at its cut)
        rows = self.series_of((0.28, 0.28, 0.68))
        keep = TA._seen
        TA._seen = lambda r: bool(r["alpha"] > 0.15 or r["present"])
        try:
            old = self.phases(rows)
        finally:
            TA._seen = keep
        self.assertEqual(old["frames"]["first"], 0)
        text = dict(old, series=TA._compact(rows), vertical=False,
                    ref={"box": {"x0": 100.0, "x1": 220.0, "y0": 112.0, "y1": 128.0, "cx": 160.0, "cy": 120.0, "h": 16.0,
                                 "w": 120.0}, "chars": [[110.0 + 20.0 * k, 120.0, 16.0, 0.9] for k in range(6)]})
        run = json.loads(json.dumps({"fps": self.fps, "range": [0.0, 2.0], "texts": [text]}))
        again = TA.rephase_run(run)["texts"][0]
        self.assertEqual(again["frames"]["first"], 30)
        self.assertEqual(again["enter"]["kinds"], ["cut"])
        self.assertAlmostEqual(again["times"]["first"], 1.0)
        self.assertEqual(again["frames"], self.phases(rows)["frames"])

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
        self.assertTrue(m["whole"])

    def test_lines_of_the_picture_moving_behind_a_still_line_do_not_tear_it(self):
        # our v7: the stage's grid lines slide behind the lyrics (they read as torn rows, the lines as glitching in)
        frames = clip_of(lambda n: {"alpha": 0.0} if n < 10 else {"offset": (0.0, 24.0 * (1.0 - ease_out((n - 10) / 8.0))),
                                                                   "alpha": min(1.0, (n - 9) / 8.0)})
        for n, f in frames.items():
            g = f.astype(np.float64)
            for k in range(-4, 6):
                x0 = 40 * k + 3 * n                                   # slanted lines moving right 3 px a frame
                for y in range(f.shape[0]):
                    x = int(x0 + 0.6 * y)
                    if 0 <= x < f.shape[1] - 1:
                        g[y, x:x + 2] = 0.6 * g[y, x:x + 2] + 0.4 * np.array([230.0, 150.0, 60.0])
            frames[n] = np.clip(g, 0, 255).astype(np.uint8)
        m = self.measure(frames)
        self.assertNotIn("glitch", m["enter"]["kinds"], m["enter"])
        self.assertEqual(m["hold"]["torn_frames"], 0)
        self.assertIn("move", m["enter"]["kinds"])

    def test_a_line_rising_as_it_fades_in_is_no_blur(self):
        # our v7 lyrics rise 0.25 s as they fade in: their faint first frames are soft for being faint
        m = self.measure(clip_of(lambda n: {"alpha": 0.0} if n < 10 else
                                 {"offset": (0.0, 20.0 * (1.0 - ease_out((n - 10) / 8.0))),
                                  "alpha": min(1.0, (n - 9) / 8.0)}))
        self.assertIn("move", m["enter"]["kinds"])
        self.assertIn("fade", m["enter"]["kinds"])
        self.assertNotIn("blur", m["enter"]["kinds"])
        self.assertNotIn("glitch", m["enter"]["kinds"])

    def test_the_picture_sliding_in_the_margin_of_the_box_is_no_tear(self):
        # our v7: the box has a few rows above and below the letters; there the stage's grid lines slide sideways under
        # a still line, and those rows read as torn (the letters' own rows match where they are)
        rng = np.random.default_rng(3)
        h, w = 120, 360
        xx = np.arange(w)

        def ground(n):
            stripes = 0.12 + 0.16 * (np.sin(2 * np.pi * (xx - 6 * n) / 23.0) > 0.6)    # lines sliding 6 px a frame
            return np.repeat(stripes[None, :], h, axis=0) + rng.normal(0, 0.003, (h, w))

        letters = np.zeros((h, w))
        for k in range(9):                                       # strokes of letters on rows 50 to 75
            x0 = 40 + 31 * k
            letters[50:75, x0:x0 + 4] = 1.0
            letters[50 + (k * 7) % 20:54 + (k * 7) % 20, x0:x0 + 22] = 1.0
        box = {"x0": 36.0, "x1": 326.0, "y0": 44.0, "y1": 81.0, "cx": 181.0, "cy": 62.5, "w": 290.0, "h": 37.0}

        def frame(n, tear=False):
            lt = letters.copy()
            if tear:
                lt[55:65] = np.roll(lt[55:65], 6, axis=1)
            y = ground(n) * (1 - lt) + 0.95 * lt
            return y, np.repeat(y[..., None] * 255.0, 3, axis=2)
        y_ref, rgb_ref = frame(0)
        for n in (1, 2, 3):
            y, rgb = frame(n)
            self.assertEqual(TA._glitch(rgb, y, rgb_ref, y_ref, box, (0.0, 0.0), 1.0)[1], 0, n)
        y, rgb = frame(2, tear=True)
        self.assertEqual(TA._glitch(rgb, y, rgb_ref, y_ref, box, (0.0, 0.0), 1.0)[1], 1)

    def panned(self, sign, n_frames=150, step=1.3):
        """a picture panning `step` px a frame to the left behind a line of text that stays put (sign False) or is part
        of the picture and pans with it (sign True)"""
        rng = np.random.default_rng(11)
        tex = ndi.gaussian_filter(rng.standard_normal((180, 320 + int(step * n_frames) + 40)), 3.0)
        tex = 0.12 + 0.28 * (tex - tex.min()) / (tex.max() - tex.min())
        out = {}
        for n in range(n_frames):
            x0 = int(round(step * n))
            frac = step * n - x0
            ground = (1 - frac) * tex[:, x0:x0 + 320] + frac * tex[:, x0 + 1:x0 + 321]
            off = (-step * n + 60.0, 0.0) if sign else (0.0, 0.0)
            text = draw_text(bg=0.0, seed=n, offset=off, centre=(160.0 - 60.0 if sign else 160.0, 120.0)).astype(np.float64) / 255.0
            mask = text.mean(axis=2) > 0.5
            f = np.repeat(ground[..., None], 3, axis=2)
            f[mask] = text[mask]
            out[n] = np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return out

    def test_a_sign_moving_with_the_picture_is_in_the_scene(self):
        # a neon sign of the night street (RE: 踊): the camera pans and the sign goes with the street
        m = self.measure(self.panned(sign=True))
        self.assertEqual(m["space"]["kind"], "scene", m["space"])

    def test_a_line_on_the_screen_over_a_panning_picture_stays(self):
        m = self.measure(self.panned(sign=False))
        self.assertEqual(m["space"]["kind"], "screen", m["space"])

    def test_a_line_only_seen_moving_is_not_whole(self):
        # never still: its look is read off a frame of its motion (the look of the lyrics is read on the whole ones)
        m = self.measure(clip_of(lambda n: {"alpha": 0.0} if n < 10 or n > 50 else {"offset": (3.0 * (n - 30), 0.0)}))
        self.assertFalse(m["whole"])


    def test_pieces_of_frames_read_as_the_whole_frames(self):
        frames = clip_of(lambda n: {"alpha": 0.0} if n < 10 else {"offset": (-60.0 * (1.0 - ease_out((n - 10) / 8.0)), 0.0)})
        ns = TA.sample_frames(len(frames), self.fps, 2.0)
        samples = TA.detect_samples({n: frames[n] for n in ns}, pixel_detector, self.fps)
        track = TA.link_tracks(samples)[0]
        plan = TA.refine_plan(track, samples, len(frames), self.fps)
        whole = TA.measure_track({n: frames[n] for n in plan}, track, self.fps, bounds=(0, 59))
        x0, y0, x1, y1 = TA._band(track, frames[0].shape)
        pieces = {n: frames[n][y0 - 5:y1 + 3, :] for n in plan}
        part = TA.measure_track(pieces, track, self.fps, bounds=(0, 59), origin=(0, y0 - 5),
                                frame_shape=frames[0].shape[:2])
        self.assertEqual(whole[0]["frames"], part[0]["frames"])
        self.assertAlmostEqual(whole[0]["ref"]["box"]["cy"], part[0]["ref"]["box"]["cy"], places=6)
        self.assertEqual(whole[0]["enter"]["kinds"], part[0]["enter"]["kinds"])


@unittest.skipUnless(TA, NEEDS)
class VideoTest(unittest.TestCase):
    """detect and track over a folder of frames (what look_analyze reads as a video), with the stand-in detector"""

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        cls.tmp = tempfile.mkdtemp(prefix="typo_video_")
        cls.fps = 30.0

        def look(n):
            if n < 12 or n > 70:
                return {"alpha": 0.0}
            if n <= 20:
                return {"alpha": (n - 12) / 8.0}
            return {}
        for n in range(90):
            args = dict(seed=n)
            args.update(look(n))
            Image.fromarray(draw_text(**args)).save(os.path.join(cls.tmp, "f%04d.png" % n))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detect_then_track(self):
        det = TA.detect_video(self.tmp, None, rate=2.0, height=None, detector=pixel_detector)
        self.assertEqual(det["fps"], 30)
        self.assertEqual(len(det["samples"]), 6)
        out = TA.track_video(self.tmp, det, None, detector=pixel_detector, style=True)
        self.assertEqual(len(out["texts"]), 1)
        t = out["texts"][0]
        self.assertTrue(12 <= t["frames"]["first"] <= 14, t["frames"])
        self.assertTrue(19 <= t["frames"]["full"] <= 21, t["frames"])
        self.assertTrue(69 <= t["frames"]["last"] <= 70, t["frames"])
        self.assertIn("fade", t["enter"]["kinds"])
        self.assertEqual(t["exit"]["kinds"], ["cut"])
        self.assertAlmostEqual(t["place"]["x"], 0.5, delta=0.03)              # the middle of the picture across
        self.assertAlmostEqual(t["place"]["y"], 120 / 180.0, delta=0.03)
        self.assertGreater(t["style"]["fill_L"], 85)

    def test_the_look_read_again_after_the_tracking(self):
        det = TA.detect_video(self.tmp, None, rate=2.0, height=None, detector=pixel_detector)
        out = TA.track_video(self.tmp, det, None, detector=pixel_detector, style=True)
        first = dict(out["texts"][0]["style"])
        for t in out["texts"]:
            t.pop("style", None)
            t.pop("typeface", None)
        again = TA.restyle_video(self.tmp, json.loads(json.dumps(out)))
        self.assertAlmostEqual(again["texts"][0]["style"]["fill_L"], first["fill_L"], places=6)
        self.assertIn("class", again["texts"][0]["typeface"])

    def test_a_look_that_cannot_be_read_does_not_lose_the_run(self):
        # a run of half an hour lost to one text whose fill could not be read (踊 / Odo, Eks4OJ1d56U, 10-21)
        det = TA.detect_video(self.tmp, None, rate=2.0, height=None, detector=pixel_detector)
        real = TA.text_style

        def broken(rgb, box):
            raise ValueError("cannot convert float NaN to integer")
        TA.text_style = broken
        try:
            out = TA.track_video(self.tmp, det, None, detector=pixel_detector, style=True)
        finally:
            TA.text_style = real
        self.assertEqual(len(out["texts"]), 1)
        self.assertIn("error", out["texts"][0]["style"])
        self.assertIn("weight", out["texts"][0]["typeface"])

    def test_the_fill_of_a_text_whose_deep_strokes_are_all_another_colour(self):
        # the deepest strokes of one colour, every other deep pixel far from it: the fill is still read
        a = np.full((120, 300, 3), 20, np.uint8)
        a[44:64, 60:140] = (250, 30, 30)                       # a red block and a blue one as deep: their mean colour
        a[44:64, 160:240] = (30, 30, 250)                      # lies far from both
        box = {"x0": 40.0, "y0": 44.0, "x1": 260.0, "y1": 64.0, "cx": 150.0, "cy": 54.0, "w": 220.0, "h": 20.0,
               "angle": 0.0, "vertical": False, "score": 1.0, "area": 0.0}
        st = TA.text_style(a, box)
        self.assertEqual(len(st["fill_rgb"]), 3)


# ---- the look of the text: drawn with Pillow, its colour, outline, shadow and glow known -----------------------------

WIN_FONTS = "C:/Windows/Fonts"


def font_path(name):
    p = os.path.join(WIN_FONTS, name)
    return p if os.path.exists(p) else None


def render(text="東京の夜空に光る星", font="NotoSansJP-VF.ttf", size=64, weight=None, fill=(255, 255, 255),
           ground=(30, 30, 40), stroke=0, stroke_fill=None, shadow=None, glow=None, hollow=False, pad=40):
    """(RGB uint8, box) of a line drawn with Pillow: shadow (dx, dy, blur, rgb), glow (sigma, strength) of the fill
    colour round the text, hollow: only the outline (stroke) drawn, its inside the ground"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    f = ImageFont.truetype(font_path(font), size)
    if weight is None and font.startswith("Noto"):
        weight = 700                                  # the default instance of the Noto variable fonts is Thin
    if weight is not None:
        try:
            axes = []
            for ax in f.get_variation_axes():
                axes.append(weight if str(ax.get("name", b"")).lower().find("weight") >= 0 or ax.get("name") in (b"Weight",)
                            else ax["default"])
            f.set_variation_by_axes(axes)
        except Exception:
            pass
    x0, y0, x1, y1 = f.getbbox(text, stroke_width=stroke)
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    img = Image.new("RGB", (w, h), ground)
    org = (pad - x0, pad - y0)

    def text_layer(colour, sw=0, sfill=None, inner=None):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(org, text, font=f, fill=inner if inner is not None else colour + (255,),
                                   stroke_width=sw, stroke_fill=(sfill + (255,)) if sfill else None)
        return layer
    if glow:
        g = text_layer(fill).filter(ImageFilter.GaussianBlur(glow[0]))
        a = np.asarray(g, np.float64)
        base = np.asarray(img, np.float64)
        add = a[..., :3] * (a[..., 3:4] / 255.0) * glow[1]
        img = Image.fromarray(np.clip(base + add, 0, 255).astype(np.uint8))
    if shadow:
        dx, dy, blur, rgb = shadow
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((org[0] + dx, org[1] + dy), text, font=f, fill=rgb + (255,))
        if blur:
            sh = sh.filter(ImageFilter.GaussianBlur(blur))
        img.paste(sh, (0, 0), sh)
    if hollow:
        lay = text_layer(fill, sw=stroke, sfill=stroke_fill or fill, inner=(0, 0, 0, 0))
        img.paste(lay, (0, 0), lay)
        # the inside back to the ground: draw the text in the ground colour over the stroke's middle
        inner = text_layer(ground)
        img.paste(inner, (0, 0), inner)
    else:
        lay = text_layer(fill, sw=stroke, sfill=stroke_fill)
        img.paste(lay, (0, 0), lay)
    a = np.asarray(img, np.uint8).copy()
    box = {"x0": float(pad), "y0": float(pad), "x1": float(w - pad), "y1": float(h - pad), "cx": w / 2.0, "cy": h / 2.0,
           "w": float(w - 2 * pad), "h": float(h - 2 * pad), "angle": 0.0, "vertical": False, "score": 1.0, "area": 0.0}
    return a, box


HAS_FONTS = np is not None and font_path("NotoSansJP-VF.ttf") is not None and font_path("yumin.ttf") is not None


@unittest.skipUnless(TA and HAS_FONTS, NEEDS + " and the Windows Japanese fonts")
class StyleTest(unittest.TestCase):
    def style(self, **kw):
        a, box = render(**kw)
        return TA.text_style(a, box)

    def test_plain_white_text(self):
        st = self.style()
        self.assertGreater(st["fill_L"], 90)
        self.assertLess(st["fill_C"], 8)
        self.assertFalse(st["outline"])
        self.assertFalse(st["shadow"])
        self.assertLess(st["glow"], 0.05)
        self.assertFalse(st["hollow"])

    def test_red_text(self):
        st = self.style(fill=(220, 40, 40))
        self.assertGreater(st["fill_C"], 50)
        self.assertTrue(-20 <= st["fill_hue"] <= 50, st["fill_hue"])       # red: a* high, b* a little

    def test_an_outline_is_seen_with_its_colour_and_width(self):
        st = self.style(stroke=4, stroke_fill=(10, 10, 10), ground=(120, 120, 130))
        self.assertTrue(st["outline"], st)
        self.assertLess(st["outline_L"], 25)
        self.assertGreater(st["fill_L"], 90)
        self.assertAlmostEqual(st["outline_px"], 4.0, delta=1.6)

    def test_a_drop_shadow_is_seen_with_its_offset(self):
        st = self.style(shadow=(5, 5, 1, (0, 0, 0)), ground=(120, 120, 130))
        self.assertTrue(st["shadow"], st)
        self.assertAlmostEqual(st["shadow_dx"], 5, delta=1.6)
        self.assertAlmostEqual(st["shadow_dy"], 5, delta=1.6)
        self.assertFalse(st["outline"])

    def test_a_glow_is_seen_and_a_plain_text_has_none(self):
        glowing = self.style(glow=(6, 2.5), ground=(20, 20, 30))
        plain = self.style(ground=(20, 20, 30))
        self.assertGreater(glowing["glow"], 0.12)
        self.assertGreater(glowing["glow"], 4 * max(plain["glow"], 0.01))
        self.assertGreater(glowing["glow_px"], 3)

    def test_hollow_letters(self):
        st = self.style(hollow=True, stroke=3, stroke_fill=(60, 230, 230), ground=(15, 15, 25), size=96)
        self.assertTrue(st["hollow"], st)


@unittest.skipUnless(TA and HAS_FONTS, NEEDS + " and the Windows Japanese fonts")
class TypefaceTest(unittest.TestCase):
    def features(self, font, weight=None, size=72):
        a, box = render(font=font, size=size, weight=weight)
        return TA.typeface(a, box)

    def test_gothic_and_mincho_part(self):
        gothic = [self.features(f) for f in ("NotoSansJP-VF.ttf", "YuGothM.ttc", "meiryo.ttc", "msgothic.ttc")]
        mincho = [self.features(f) for f in ("yumin.ttf", "msmincho.ttc", "NotoSerifJP-VF.ttf")]
        for g in gothic:
            self.assertEqual(g["class"], "gothic", g)
        for m in mincho:
            self.assertEqual(m["class"], "mincho", m)
        self.assertGreater(min(g["hv"] for g in gothic), max(m["hv"] for m in mincho))

    def test_a_heavier_weight_reads_heavier(self):
        light = self.features("NotoSansJP-VF.ttf", weight=300)
        heavy = self.features("NotoSansJP-VF.ttf", weight=900)
        self.assertGreater(heavy["weight"], 1.5 * light["weight"])

    def test_a_glow_round_mincho_does_not_make_it_gothic(self):
        # the references' lyrics glow (glow 0.12 to 0.20): the glow's light round the thin horizontals read as their width
        for font in ("yumin.ttf", "NotoSerifJP-VF.ttf"):
            for glow in ((2, 1.0), (3, 1.5), (5, 2.0)):
                a, box = render(font=font, size=44, weight=500 if font.startswith("Noto") else None, glow=glow,
                                ground=(20, 22, 40))
                tf = TA.typeface(a, box)
                self.assertEqual(tf["class"], "mincho", (font, glow, tf))

    def test_a_figure_behind_and_a_rule_of_the_fill_colour_are_not_letters(self):
        # our v7: the dancer's legs (pale, wide) cross the box behind a white line and its rule is light too: the fill
        # was read off the legs (the deepest pixels) and the rule's long thin horizontal counted as a stroke
        a, box = render(font="NotoSansJP-VF.ttf", size=48, weight=700, ground=(25, 28, 50))
        a = a.copy()
        x = int(box["x0"] + 0.55 * box["w"])
        a[:, x:x + 56] = (225, 160, 168)                       # a leg from the top of the picture to the bottom
        a[int(box["y0"]):int(box["y1"]), :] = np.where(        # the letters stay in front of it
            render(font="NotoSansJP-VF.ttf", size=48, weight=700, ground=(0, 0, 0))[0][int(box["y0"]):int(box["y1"]), :] > 128,
            255, a[int(box["y0"]):int(box["y1"]), :])
        y = int(box["y1"] + 0.08 * box["h"])
        a[y:y + 2, int(box["x0"] + 0.2 * box["w"]):int(box["x0"] + 0.8 * box["w"])] = (250, 245, 235)
        mask, _, (ox, oy), _ = TA._letters_of(a, box)
        ys, xs = np.nonzero(mask)
        self.assertLess(float(((xs + ox >= x) & (xs + ox < x + 56)).mean()), 0.25)      # the letters, not the leg
        tf = TA.typeface(a, box)
        self.assertEqual(tf["class"], "gothic", tf)
        self.assertGreater(tf["hv"], 0.7, tf)
        self.assertLess(tf["stroke_px"], 8.0, tf)                                     # the letters' strokes (about 5 px)

    def test_a_rule_touching_the_letters_is_not_a_stroke(self):
        # our v7: the light rule under a line joins the letters where a figure behind meets them: one piece, no rule
        a, box = render(font="NotoSansJP-VF.ttf", size=48, weight=700, ground=(25, 28, 50))
        a = a.copy()
        y = int(box["y1"] + 0.06 * box["h"])
        x0, x1 = int(box["x0"] + 0.1 * box["w"]), int(box["x0"] + 0.95 * box["w"])
        a[y:y + 2, x0:x1] = (250, 245, 235)
        cols = np.nonzero((a[int(box["y1"]) - 3, x0:x1] > 128).all(axis=1))[0]
        for c in cols[::7]:                                           # bridges from the letters' feet to the rule
            a[int(box["y1"]) - 3:y, x0 + c] = (250, 245, 235)
        mask, _, (ox, oy), _ = TA._letters_of(a, box)
        self.assertLess(float(mask[y - oy:y - oy + 2, x0 - ox:x1 - ox].mean()), 0.3)
        tf = TA.typeface(a, box)
        self.assertEqual(tf["class"], "gothic", tf)
        self.assertGreater(tf["hv"], 0.7, tf)

    def test_a_rule_under_the_line_is_not_a_stroke_of_its_letters(self):
        # our lyric style: a thin accent rule a little under the line, wider than it (its long thin horizontal read
        # the gothic lines of our v7 as mincho)
        a, box = render(font="NotoSansJP-VF.ttf", size=72, weight=700, ground=(40, 40, 60))
        y = int(box["y1"] + 0.22 * box["h"])
        a[y:y + 3, int(box["x0"] - 12):int(box["x1"] + 12)] = (255, 200, 80)
        tf = TA.typeface(a, box)
        self.assertEqual(tf["class"], "gothic", tf)
        self.assertGreater(tf["hv"], 0.7, tf)


# ---- the voice and the beat ----------------------------------------------------------------------------------------------

def sung(phrases, sr=16000, total=6.0, f0=220.0, syllable=0.25, gap=0.06, seed=0):
    """a voice-like sound: harmonic syllables (f0 and its harmonics, a little vibrato) of `syllable` s with consonant
    gaps of `gap` s, inside each phrase (start, end); quiet noise elsewhere"""
    rng = np.random.default_rng(seed)
    t = np.arange(int(total * sr)) / float(sr)
    x = rng.normal(0, 1e-4, t.size)
    for a, b in phrases:
        s0 = a
        while s0 < b - 0.05:
            s1 = min(b, s0 + syllable)
            m = (t >= s0) & (t < s1)
            tt = t[m] - s0
            env = np.minimum(1.0, tt / 0.015) * np.minimum(1.0, (s1 - s0 - tt) / 0.03)
            ph = 2 * np.pi * f0 * tt + 0.3 * np.sin(2 * np.pi * 5.5 * tt)
            x[m] += 0.3 * env * sum(np.sin(k * ph) / k for k in range(1, 8))
            s0 = s1 + gap
    return x.astype(np.float32)


def clicks(bpm=120.0, first=0.5, total=10.0, sr=22050, accent_every=4, accent_at=0):
    """a click on every beat, a low thump on every accent_every-th (from beat accent_at)"""
    t = np.arange(int(total * sr)) / float(sr)
    x = np.zeros(t.size)
    period = 60.0 / bpm
    k = 0
    b = first
    while b < total - 0.1:
        m = (t >= b) & (t < b + 0.08)
        tt = t[m] - b
        x[m] += 0.5 * np.exp(-tt / 0.01) * np.sin(2 * np.pi * 2000 * tt)
        if (k - accent_at) % accent_every == 0:
            x[m] += 0.9 * np.exp(-tt / 0.03) * np.sin(2 * np.pi * 60 * tt)
        k += 1
        b += period
    return x.astype(np.float32), sr


@unittest.skipUnless(TA, NEEDS)
class VoiceTest(unittest.TestCase):
    def test_phrases_start_where_the_singing_starts(self):
        x = sung([(1.0, 2.5), (3.0, 4.2), (4.9, 5.6)])
        v = TA.voice_events(x)
        starts = [p[0] for p in v["phrases"]]
        self.assertEqual(len(starts), 3, v["phrases"])
        for got, want in zip(starts, (1.0, 3.0, 4.9)):
            self.assertAlmostEqual(got, want, delta=0.04)
        ends = [p[1] for p in v["phrases"]]
        for got, want in zip(ends, (2.5, 4.2, 5.6)):
            self.assertAlmostEqual(got, want, delta=0.08)
        self.assertGreater(len(v["onsets"]), 6)

    def test_the_beat_and_the_bar(self):
        try:
            import librosa  # noqa: F401
        except ImportError:
            self.skipTest("needs librosa")
        x, sr = clicks(bpm=120.0, first=0.5, accent_at=2)
        b = TA.beat_events(x, sr)
        self.assertAlmostEqual(b["bpm"], 120.0, delta=3.0)
        want = 0.5 + 0.5 * np.arange(18)
        got = np.array(b["beats"])
        near = [np.min(np.abs(got - w)) for w in want[1:-1]]
        self.assertLess(np.median(near), 0.03)
        down = np.array(b["downbeats"])
        # the accents fall on beats 2, 6, 10, ...: at 1.5, 3.5, 5.5 s
        self.assertLess(np.min(np.abs(down - 3.5)), 0.04)


@unittest.skipUnless(TA, NEEDS)
class SyncTest(unittest.TestCase):
    def text(self, first, full, last, place_y=0.85):
        return {"times": {"first": first, "full": full, "hold_end": last - 0.1, "last": last},
                "place": {"x": 0.5, "y": place_y, "h": 0.04, "w": 0.15 + 0.013 * (int(round(first * 10)) % 8)},
                "enter": {"kinds": ["fade"]}, "exit": {"kinds": ["fade"]}}

    def voice(self, lines, total=12.0, weak_every=0.25):
        """a voice in the form of voice_events: strong onsets where the lines start, weak ones every weak_every s while
        it sings, its level -10 dB while it sings and -60 dB between, its onset strength at the onsets"""
        step = 0.01
        n = int(total / step)
        level = np.full(n, -60.0)
        flux = np.zeros(n)
        onsets, strength = [], []
        for a, b in lines:
            level[int(a / step):int(b / step)] = -10.0
            t = a
            while t < b:
                strong = abs(t - a) < 1e-9
                onsets.append(t)
                strength.append(5.0 if strong else 1.0)
                flux[int(round(t / step))] = 5.0 if strong else 1.0
                t += weak_every
        return {"phrases": [list(l) for l in lines], "onsets": onsets, "strength": strength, "level": list(level),
                "flux": list(flux), "step": step, "offset": 0.0}

    def test_a_text_that_comes_before_the_voice(self):
        lines = ((2.0, 4.0), (5.0, 7.0), (8.0, 9.5))
        voice = self.voice(lines)
        texts = [self.text(p - 0.2, p - 0.05, e + 0.3) for p, e in lines]
        r = TA.sync(texts, voice, beats=None, fps=30.0, duration=10.0)
        self.assertAlmostEqual(r["lead_s"]["median"], 0.2, delta=0.01)
        self.assertAlmostEqual(r["full_lead_s"]["median"], 0.05, delta=0.01)
        self.assertAlmostEqual(r["trig_lead_s"], 0.2, delta=0.011)
        self.assertEqual(r["paired"], 3)
        self.assertEqual([t["kind"] for t in r["texts"]], ["lyric"] * 3)

    def sparse_voice(self, starts, total=90.0, weak_every=1.6):
        """a voice singing all along (-10 dB) whose strong onsets are where the lines start and whose few weak ones (the
        strong ones are the top quarter) fall every weak_every s away from them"""
        step = 0.01
        level = np.full(int(total / step), -10.0)
        onsets = sorted([(s, 5.0) for s in starts] +
                        [(t, 1.0) for t in np.arange(0.3, total - 0.3, weak_every) if min(abs(t - s) for s in starts) > 0.15])
        flux = np.zeros(level.size)
        for t, s in onsets:
            flux[int(round(t / step))] = s
        return {"phrases": [[0.2, total - 0.2]], "onsets": [t for t, _ in onsets], "strength": [s for _, s in onsets],
                "level": list(level), "flux": list(flux), "step": step, "offset": 0.0}

    def test_the_lead_is_read_against_chance(self):
        # typorev: the references' lead was read without its chance.  Lines 0.2 s ahead of the strong onsets lie nearer
        # to them than the same lines moved at random; lines put at random do not.  And full_lead_s is lead_s less the
        # time the line takes to come in, not a second reading of the voice
        rng = np.random.default_rng(4)
        starts = list(np.cumsum(rng.uniform(2.5, 4.5, 20)) + 1.0)
        voice = self.sparse_voice(starts)
        def spread(texts):                    # each in its own place across: not one place come back to (a mark)
            for k, t in enumerate(texts):
                t["place"]["x"] = 0.2 + 0.03 * k
            return texts
        locked = spread([self.text(s - 0.2, s + 0.3, s + 2.0) for s in starts])
        r = TA.sync(locked, voice, beats=None, fps=30.0, duration=90.0)
        self.assertEqual([x["kind"] for x in r["texts"]], ["lyric"] * 20)
        self.assertAlmostEqual(r["near_s"]["median"], 0.2, delta=0.01)
        self.assertLess(r["near_s"]["median"], r["chance"]["near_band"][0])
        self.assertGreater(r["chance"]["near_s"], 0.5)
        for row in r["texts"]:
            self.assertAlmostEqual(row["full_lead_s"], row["lead_s"] - (row["full"] - row["first"]), places=9)
        loose = spread([self.text(a, a + 0.5, a + 2.0) for a in np.sort(rng.uniform(1.0, 85.0, 20))])
        r2 = TA.sync(loose, voice, beats=None, fps=30.0, duration=90.0)
        lo, hi = r2["chance"]["near_band"]
        self.assertTrue(lo <= r2["near_s"]["median"] <= hi, (r2["near_s"], r2["chance"]))
        whole = [dict(t, id=k, n_chars=5, vertical=False, hold={"s": 1.0, "drift_h_per_s": 0.0}, ref={"box": {"h": 20.0}},
                      enter={"kinds": ["fade"], "s": 0.5, "dx": 0.0, "dy": 0.0, "scale": 1.0, "fade_s": 0.5, "stagger": None},
                      exit={"kinds": ["fade"], "s": 0.2}) for k, t in enumerate(locked)]
        s = TA.typo_summary({"label": "x", "fps": 30.0, "range": [0.0, 90.0], "texts": whole}, r, voice=voice)["summary"]
        self.assertAlmostEqual(s["sync.near_s"]["median"], 0.2, delta=0.01)
        self.assertGreater(s["sync.near_chance"]["median"], 0.5)
        self.assertIn("sync.lead_chance", s)

    def test_a_sign_in_the_scene_is_no_lyric(self):
        voice = self.voice(((2.0, 4.0),))
        t = self.text(2.0, 2.1, 3.9)
        t["space"] = {"kind": "scene"}
        r = TA.sync([t], voice, beats=None, fps=30.0, duration=10.0)
        self.assertEqual(r["texts"][0]["kind"], "scene")

    def test_a_text_on_the_beat(self):
        beats = {"beats": list(0.5 + 0.5 * np.arange(40)), "downbeats": list(0.5 + 2.0 * np.arange(10)), "bpm": 120.0}
        on = [self.text(0.5 + 0.5 * k, 0.6 + 0.5 * k, 1.0 + 0.5 * k) for k in range(2, 30, 3)]
        off = [self.text(0.75 + 0.5 * k, 0.8 + 0.5 * k, 1.0 + 0.5 * k) for k in range(2, 30, 3)]
        r_on = TA.sync(on, {"phrases": [], "onsets": []}, beats=beats, fps=30.0, duration=20.0)
        r_off = TA.sync(off, {"phrases": [], "onsets": []}, beats=beats, fps=30.0, duration=20.0)
        self.assertGreater(r_on["on_beat"]["share"], 0.95)
        self.assertLess(r_off["on_beat"]["share"], 0.05)
        self.assertAlmostEqual(r_on["on_beat"]["chance"], 2 * (1 / 30.0 + 0.01) / 0.5, delta=0.02)


    def test_the_summary_of_a_video(self):
        def tx(i, first, last, y, kinds, h=0.05):
            return {"id": i, "times": {"first": first, "full": first + 0.2, "hold_end": last - 0.2, "last": last},
                    "place": {"x": 0.5, "y": y, "h": h, "w": 0.4}, "n_chars": 8, "vertical": False,
                    "enter": {"kinds": kinds, "s": 0.2, "dx": -30.0, "dy": 0.0, "scale": 1.0, "fade_s": 0.25,
                              "stagger": None},
                    "exit": {"kinds": ["fade"], "s": 0.2}, "hold": {"s": last - first - 0.4, "drift_h_per_s": 0.0},
                    "ref": {"box": {"h": 30.0}}, "style": {"fill_L": 95.0, "fill_C": 3.0, "contrast_L": 80.0, "glow": 0.1,
                                                           "outline": i == 0, "outline_px": 2.0, "shadow": False,
                                                           "hollow": False},
                    "typeface": {"weight": 0.1, "class": "gothic"}}
        texts = [tx(0, 1.8, 4.2, 0.85, ["fade"]), tx(1, 4.8, 7.2, 0.85, ["fade"]), tx(2, 7.8, 9.0, 0.5, ["move"]),
                 tx(3, 9.4, 11.0, 0.2, ["cut"])]
        tr = {"label": "x", "fps": 30.0, "range": [0.0, 12.0], "texts": texts}
        voice = self.voice(((2.0, 4.0), (5.0, 7.0), (8.0, 9.0), (9.5, 11.0)))
        sy = TA.sync(texts, voice, beats=None, fps=30.0, duration=12.0)
        r = TA.typo_summary(tr, sy, voice=voice)
        s = r["summary"]
        self.assertEqual(r["lyrics"], 4)
        self.assertAlmostEqual(s["enter.fade"]["median"], 0.5)
        self.assertAlmostEqual(s["enter.move"]["median"], 0.25)
        self.assertAlmostEqual(s["enter.cut"]["median"], 0.25)
        self.assertAlmostEqual(s["typo.lower"]["median"], 0.5)
        self.assertAlmostEqual(s["style.outline"]["median"], 0.25)
        self.assertAlmostEqual(s["sync.lead_s"]["median"], 0.15, delta=0.06)
        self.assertAlmostEqual(s["sync.trig_lead_s"]["median"], 0.2, delta=0.011)
        self.assertAlmostEqual(s["typo.per_min"]["median"], 4 / 9.0 * 60.0, delta=0.5)     # 4 lines over 2 to 11 s
        self.assertGreater(s["typo.on_screen"]["median"], 0.8)
        self.assertEqual(s["typo.concurrent"]["median"], 1.0)
        self.assertAlmostEqual(s["enter.move_h"]["median"], 1.0)                          # 30 px at 30 px tall
        # the core: the lines read surely (a text cut by the frame's edge, a piece of a few frames out)
        texts[2]["times"]["last"] = texts[2]["times"]["first"] + 0.2
        texts[3]["place"]["x"] = 0.98
        c = TA.typo_summary(tr, sy, voice=voice, core=True)
        self.assertEqual(c["lyrics"], 2)
        self.assertAlmostEqual(c["summary"]["enter.fade"]["median"], 1.0)

    def test_a_small_text_that_comes_back_to_one_place_is_a_mark(self):
        voice = self.voice(((0.5, 59.0),), total=60.0)
        texts = []
        for a in (2.0, 15.0, 30.0, 45.0):
            t = self.text(a, a + 0.1, a + 4.0)
            t["place"] = {"x": 0.97, "y": 0.86, "h": 0.033, "w": 0.05}
            texts.append(t)
        lyric = self.text(10.0, 10.2, 12.0)
        lyric["place"] = {"x": 0.5, "y": 0.84, "h": 0.04, "w": 0.2}
        r = TA.sync(texts + [lyric], voice, beats=None, fps=30.0, duration=60.0)
        self.assertEqual([x["kind"] for x in r["texts"]], ["mark"] * 4 + ["lyric"])

    def test_lines_as_wide_as_each_other_are_no_mark_when_they_read_otherwise(self):
        # Japanese is set full width: lines of as many characters are as wide; what they show tells them apart
        voice = self.voice(((0.5, 59.0),), total=60.0)
        rng = np.random.default_rng(3)
        texts = []
        for k, a in enumerate((2.0, 15.0, 30.0, 45.0)):
            t = self.text(a, a + 0.1, a + 4.0)
            t["place"] = {"x": 0.25, "y": 0.83, "h": 0.07, "w": 0.37}
            t["sig"] = TA.signature_of(rng.uniform(0, 1, (16, 84)))
            texts.append(t)
        r = TA.sync(texts, voice, beats=None, fps=30.0, duration=60.0)
        self.assertEqual([x["kind"] for x in r["texts"]], ["lyric"] * 4)
        logo = rng.uniform(0, 1, (16, 84))
        for t in texts:
            t["sig"] = TA.signature_of(logo + rng.normal(0, 0.02, logo.shape))
        r = TA.sync(texts, voice, beats=None, fps=30.0, duration=60.0)
        self.assertEqual([x["kind"] for x in r["texts"]], ["mark"] * 4)

    def test_a_sign_seen_again_at_other_sizes_is_in_the_scene(self):
        # the night street's neon sign (RE: 踊): the camera comes back to it from near and far; it is still in each shot
        voice = self.voice(((0.5, 59.0),), total=60.0)
        rng = np.random.default_rng(5)
        sign = rng.uniform(0, 1, (16, 90))
        texts = []
        for a, (x, y, h) in zip((3.0, 18.0, 33.0, 48.0), ((0.4, 0.2, 0.03), (0.6, 0.3, 0.05), (0.3, 0.15, 0.08), (0.5, 0.25, 0.04))):
            t = self.text(a, a + 0.1, a + 3.0)
            t["place"] = {"x": x, "y": y, "h": h, "w": 0.2}
            t["sig"] = TA.signature_of(sign + rng.normal(0, 0.02, sign.shape))
            texts.append(t)
        # a chorus line sung again, in one size, left and right in turn (our v7): a lyric each time
        line = rng.uniform(0, 1, (16, 84))
        for a, x in zip((6.0, 21.0, 36.0, 51.0), (0.25, 0.75, 0.25, 0.75)):
            t = self.text(a, a + 0.1, a + 3.0)
            t["place"] = {"x": x, "y": 0.83, "h": 0.07, "w": 0.37}
            t["sig"] = TA.signature_of(line + rng.normal(0, 0.02, line.shape))
            texts.append(t)
        r = TA.sync(texts, voice, beats=None, fps=30.0, duration=60.0)
        self.assertEqual([x["kind"] for x in r["texts"]], ["scene"] * 4 + ["lyric"] * 4)

    def test_a_text_that_comes_and_goes_with_the_shot_is_in_the_scene(self):
        voice = self.voice(((0.5, 19.0),), total=20.0)
        sign = self.text(4.0, 4.0, 7.0)
        sign["place"] = {"x": 0.3, "y": 0.2, "h": 0.04, "w": 0.1}
        lyric = self.text(5.0, 5.2, 6.5)
        lyric["place"] = {"x": 0.5, "y": 0.84, "h": 0.04, "w": 0.2}
        r = TA.sync([sign, lyric], voice, beats=None, fps=30.0, duration=20.0, cuts=[4.0, 7.0 + 1 / 30.0, 12.0])
        self.assertEqual([x["kind"] for x in r["texts"]], ["scene", "lyric"])

    def test_a_text_that_stays_all_along_is_a_mark(self):
        voice = {"phrases": [[2.0, 4.0]], "onsets": [2.0]}
        r = TA.sync([self.text(0.0, 0.0, 60.0, place_y=0.05)], voice, beats=None, fps=30.0, duration=60.0)
        self.assertEqual(r["texts"][0]["kind"], "mark")


@unittest.skipUnless(TA, NEEDS)
class FigureTest(unittest.TestCase):
    def test_the_figures_are_drawn(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("needs matplotlib")
        tmp = tempfile.mkdtemp(prefix="typo_fig_")
        try:
            sync_test = SyncTest()
            voice = sync_test.voice(((2.0, 4.0), (5.0, 7.0)))
            voice["beats"] = [0.5 * k for k in range(24)]
            texts = []
            for i, (a, b) in enumerate(((1.8, 4.2), (4.8, 7.2))):
                t = sync_test.text(a, a + 0.2, b)
                t.update({"id": i, "place": {"x": 0.5, "y": 0.85, "h": 0.05, "w": 0.4}, "vertical": False,
                          "enter": {"kinds": ["fade"]}, "exit": {"kinds": ["cut"]}})
                texts.append(t)
            tr = {"label": "x", "range": [0.0, 10.0], "fps": 30.0, "texts": texts}
            sy = TA.sync(texts, voice, beats={"beats": voice["beats"]}, fps=30.0, duration=10.0)
            for kind, path in (("timeline", TA.figure_timeline(os.path.join(tmp, "t.png"), tr, sy, voice)),
                               ("layout", TA.figure_layout(os.path.join(tmp, "l.png"), [("x", tr, sy), ("y", tr, sy)])),
                               ("trigger", TA.figure_trigger(os.path.join(tmp, "g.png"), [("x", sy)]))):
                self.assertTrue(os.path.getsize(path) > 1000, kind)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(TA and HAS_FONTS, NEEDS + " and the Windows Japanese fonts")
class FontMatchTest(unittest.TestCase):
    """which of some fonts a text on a frame is drawn in: each character's strokes against the same character drawn in
    each font (laid where the character is, its size fitted), even with the letters spaced out"""

    def spaced(self, text, font, size=64, tracking=0.3, weight=None):
        """a frame with the text drawn one character at a time, `tracking` em apart, and the characters' middles"""
        from PIL import Image, ImageDraw, ImageFont
        f = ImageFont.truetype(font_path(font), size)
        if weight is not None:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        w = int(size * (len(text) * (1 + tracking) + 2))
        img = Image.new("RGB", (w, size * 3), (25, 25, 35))
        d = ImageDraw.Draw(img)
        x = size
        mids = []
        for ch in text:
            x0, y0, x1, y1 = f.getbbox(ch)
            d.text((x - x0, size - y0 + (size - (y1 - y0)) // 2), ch, font=f, fill=(255, 255, 255))
            mids.append((x + (x1 - x0) / 2.0, size * 1.5))
            x += int(size * (1 + tracking))
        box = {"x0": size * 0.8, "y0": size * 0.8, "x1": x, "y1": size * 2.2, "cx": (size * 0.8 + x) / 2.0, "cy": size * 1.5,
               "w": x - size * 0.8, "h": size * 1.4, "angle": 0.0, "vertical": False, "score": 1.0, "area": 0.0}
        return np.asarray(img), box, mids

    def test_the_font_it_is_drawn_in_comes_first(self):
        text = "東京の夜空に光る星"
        fonts = ["yumin.ttf", "msmincho.ttc", "NotoSerifJP-VF.ttf", "YuGothM.ttc", "msgothic.ttc"]
        for truth in ("yumin.ttf", "YuGothM.ttc"):
            a, box, mids = self.spaced(text, truth)
            r = TA.font_match(a, box, text, [font_path(f) for f in fonts], chars=mids)
            ranked = [os.path.basename(x["font"]) for x in r["ranking"]]
            self.assertEqual(ranked[0], truth, r["ranking"][:3])
            self.assertGreater(r["ranking"][0]["iou"], r["ranking"][1]["iou"])
            self.assertEqual(r["chars"], len(text))

    def test_a_glow_does_not_make_the_face_heavier(self):
        # a glow round the letters (the references') drew the match to the bold faces (Yu Gothic Bold over Medium)
        from PIL import Image, ImageFilter
        text = "東京の夜空に光る星"
        fonts = ["yumin.ttf", "msmincho.ttc", "NotoSerifJP-VF.ttf", "YuGothM.ttc", "msgothic.ttc", "YuGothB.ttc"]
        a, box, mids = self.spaced(text, "YuGothM.ttc", size=44)
        g = np.asarray(Image.fromarray(a).filter(ImageFilter.GaussianBlur(2)), np.float64)
        b = np.clip(a.astype(np.float64) + 1.2 * g, 0, 255).astype(np.uint8)
        r = TA.font_match(b, box, text, [font_path(f) for f in fonts], chars=mids)
        self.assertEqual(os.path.basename(r["ranking"][0]["font"]), "YuGothM.ttc", r["ranking"][:3])

    def test_a_rule_under_the_line_does_not_change_the_font(self):
        text = "東京の夜空に光る星"
        fonts = ["yumin.ttf", "msmincho.ttc", "NotoSerifJP-VF.ttf", "YuGothM.ttc", "msgothic.ttc"]
        a, box, mids = self.spaced(text, "YuGothM.ttc")
        a = a.copy()
        y = int(box["y1"] + 0.12 * box["h"])
        a[y:y + 3, int(box["x0"]):int(box["x1"])] = (255, 200, 80)
        r = TA.font_match(a, box, text, [font_path(f) for f in fonts], chars=mids)
        self.assertEqual(os.path.basename(r["ranking"][0]["font"]), "YuGothM.ttc", r["ranking"][:3])


if __name__ == "__main__":
    unittest.main()
