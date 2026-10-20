"""tools/mme_shadow.py: the MME effect of the soft self shadow and the files round it."""
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("mme_shadow", os.path.join(ROOT, "tools", "mme_shadow.py"))
mme_shadow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mme_shadow)


def define(text, name):
    m = re.search(r"^#define %s (\S+)$" % name, text, re.M)
    return float(m.group(1)) if m else None


def array(text, name):
    m = re.search(r"static const float3 %s\[(\d+)\] = \{(.*?)\};" % name, text, re.S)
    rows = re.findall(r"float3\(([^)]*)\)", m.group(2))
    return int(m.group(1)), [tuple(float(v) for v in r.split(",")) for r in rows]


class EffectTest(unittest.TestCase):
    def test_it_replaces_only_the_body_with_the_self_shadow(self):
        # MMD draws the passes the effect has no technique for with its own shaders (MME's REFERENCE 1.2): the shadow
        # map (zplot), the outline (edge), the ground shadow and the body without the self shadow stay MMD's
        text = mme_shadow.effect()
        passes = set(re.findall(r'MMDPass = "(\w+)"', text))
        self.assertEqual(passes, {"object_ss"})
        # one technique for every combination of texture, sphere map and toon
        combos = re.findall(r"^SS_TECH\(SS_(\d{3}), (true|false), (true|false), (true|false)\)$", text, re.M)
        self.assertEqual(len(combos), 8)
        self.assertEqual({tuple(v == "true" for v in c[1:]) for c in combos},
                         {(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)})
        self.assertTrue(text.isascii())

    def test_the_gaussian_points_weigh_the_same_and_lie_as_the_gaussian_does(self):
        # n points of weight 1 / n whose radii are the quantiles of the Gaussian's radius (truncated at KERNEL_SIGMAS):
        # an edge passing across them steps by 1 / n.  With even radii and Gaussian weights (before softshadow-mme2) the
        # inner points weighed 3 to 5 times the mean, and a wide shadow showed its copies (the review's ramp)
        text = mme_shadow.effect(n_taps=32)
        n, rows = array(text, "KERNEL")
        self.assertEqual(n, 32)
        for _, _, w in rows:
            self.assertAlmostEqual(w, 1.0 / 32, places=6)
        radii = sorted(math.hypot(x, y) for x, y, _ in rows)
        # the Gaussian cut at KERNEL_SIGMAS, then widened so that it has a standard deviation of 1 (cut, it had 0.925:
        # an edge came out 0.75 of the light's on the review's ramp, softshadow-mme2)
        k = mme_shadow.CUT_STD
        self.assertAlmostEqual(k, 0.9254, places=4)
        self.assertLessEqual(max(radii), mme_shadow.KERNEL_SIGMAS / k + 1e-6)
        top = 1.0 - math.exp(-0.5 * mme_shadow.KERNEL_SIGMAS ** 2)
        for i, r in enumerate(radii):
            self.assertAlmostEqual(1.0 - math.exp(-0.5 * (r * k) ** 2), (i + 0.5) / 32 * top, places=5)
        for n in (32, 64):
            pts = mme_shadow.taps(n)
            for axis in (0, 1):
                self.assertAlmostEqual(math.sqrt(sum(p[axis] ** 2 for p in pts) / n), 1.0, delta=0.03)
        # the points cover the disc evenly round it: no two of them on the same spot
        self.assertEqual(len({(round(x, 4), round(y, 4)) for x, y, _ in rows}), 32)
        # a straight edge across the points: the share on its lit side follows the Gaussian's integral within 1 / 32 + a
        # little (the points are not a Gaussian, they stand for one)
        pts = [(x * mme_shadow.CUT_STD, y * mme_shadow.CUT_STD, w) for x, y, w in mme_shadow.taps(32)]
        for k in range(16):
            a = k * math.pi / 16.0
            for x0 in (-1.5, -0.75, 0.0, 0.5, 1.2):
                lit = sum(w for x, y, w in pts if x * math.cos(a) + y * math.sin(a) < x0)
                want = 0.5 * (1.0 + math.erf(x0 / math.sqrt(2.0)))
                self.assertLess(abs(lit - want), 0.09, (a, x0))

    def test_the_settings_reach_the_shader(self):
        text = mme_shadow.effect(blur=5.0, min_blur=0.07, n_taps=24, search_taps=12)
        self.assertAlmostEqual(define(text, "SS_BLUR_RAD"), math.radians(5.0), places=8)
        self.assertAlmostEqual(define(text, "SS_MIN_WORLD"), 0.07, places=6)
        self.assertAlmostEqual(define(text, "SS_SEARCH_WORLD"), mme_shadow.SEARCH, places=6)
        self.assertEqual(define(text, "SS_TAPS"), 24)
        self.assertEqual(define(text, "SS_SEARCH"), 12)
        self.assertEqual(define(text, "SS_CONTACT"), 1)
        self.assertEqual(define(text, "SS_DEBUG"), 0)
        self.assertEqual(define(mme_shadow.effect(debug=True), "SS_DEBUG"), 1)
        self.assertEqual(define(mme_shadow.effect(contact=False), "SS_CONTACT"), 0)

    def test_sharp_is_mmds_own_test_at_one_point(self):
        text = mme_shadow.effect(sharp=True)
        self.assertEqual(define(text, "SS_TAPS"), 1)
        self.assertEqual(define(text, "SS_CONTACT"), 0)
        self.assertEqual(define(text, "SS_MIN_WORLD"), 0.0)
        n, rows = array(text, "KERNEL")
        self.assertEqual(rows, [(0.0, 0.0, 1.0)])
        # MMD's test: 1 - saturate(max(z - map, 0) * 1500 - 0.3) in mode 1, the slope 8000 x v in mode 2
        self.assertIn("#define SKII1 1500.0", text)
        self.assertIn("#define SKII2 8000.0", text)
        self.assertIn("slope - 0.3f", text)

    def test_the_shade_keeps_option_d_by_default_and_the_floor_its_own(self):
        # the shade keeps 1 - key_share of the light.  By default option D (Kaga-san's choice of 2026-10-17 among A: the
        # shade 0.40, B: MMD's toon, C and D: the shade 0.65, the floor 0.65 in C and 0.40 in D): the shade keeps 0.65
        # (key_share 0.35) while the floor's shadow keeps 0.40 (tools/mv_world.py KEY_SHARE 0.6, stage.shadow_key)
        text = mme_shadow.effect()
        self.assertEqual(define(text, "SS_ALIGN"), 1)
        self.assertAlmostEqual(mme_shadow.DEFAULTS["key_share"], 0.35, places=9)
        self.assertAlmostEqual(define(text, "SS_KEEP"), 0.65, places=6)
        self.assertAlmostEqual(define(mme_shadow.effect(key_share=0.3), "SS_KEEP"), 0.7, places=6)
        self.assertAlmostEqual(define(mme_shadow.effect(key_share=0.6), "SS_KEEP"), 0.4, places=6)     # option A
        self.assertIn('"key_share": 0.35', text.splitlines()[2])
        # the toon's hue kept, its luma set (BT.709, as tools/shadow_check.py reads the floor); a white toon left white
        self.assertIn("float3(0.2126f, 0.7152f, 0.0722f)", text)
        self.assertIn("if (luma < 0.999f)", text)
        # MMD's toon colours as they are: with key_share None, and always in sharp (the check that the shading is MMD's)
        for toon in (mme_shadow.effect(key_share=None), mme_shadow.effect(sharp=True)):
            self.assertEqual(define(toon, "SS_ALIGN"), 0)
            self.assertIn('"key_share": null', toon.splitlines()[2])
        try:
            spec = importlib.util.spec_from_file_location("mv_world", os.path.join(ROOT, "tools", "mv_world.py"))
            mv_world = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mv_world)
        except ImportError:                    # mv_world needs numpy and Pillow
            return
        self.assertAlmostEqual(1.0 - mv_world.KEY_SHARE, 0.40, places=9)      # the floor's shadow stays 0.40 (option D)

    def test_debug_draws_the_shadow_alone_or_the_body_lit(self):
        self.assertEqual(define(mme_shadow.effect(debug="shadow"), "SS_DEBUG"), 1)
        lit = mme_shadow.effect(debug="lit")
        self.assertEqual(define(lit, "SS_DEBUG"), 2)
        self.assertIn('"debug": "lit"', lit.splitlines()[2])
        self.assertIn("#if SS_DEBUG == 2", lit)
        self.assertEqual(define(mme_shadow.effect(), "SS_DEBUG"), 0)
        # --debug toon (review of softshadow-mme2): the toon's share of the light where a shade shows, 0 where none can
        # (no toon or a white one), for tools/selfshadow_check.py against --toon
        toon = mme_shadow.effect(debug="toon")
        self.assertEqual(define(toon, "SS_DEBUG"), 3)
        self.assertIn('"debug": "toon"', toon.splitlines()[2])
        body = toon[toon.index("#if SS_DEBUG == 3"):]
        body = body[:body.index("#endif")]
        self.assertIn("saturate(dot(IN.Normal, -LightDirection) * TOON_SLOPE)", body)
        self.assertIn("MaterialToon", body)
        self.assertIn("useToon", body)

    def test_wrong_settings_are_refused(self):
        for bad in ({"blur": -1}, {"blur": 45}, {"min_blur": -0.1}, {"min_blur": 3}, {"n_taps": 0}, {"n_taps": 65},
                    {"search_taps": 0}, {"key_share": 1.0}, {"key_share": -0.1}, {"key_share": True},
                    {"debug": "dark"}):
            with self.assertRaises(ValueError, msg=bad):
                mme_shadow.effect(**bad)

    def test_the_command_line_takes_the_shade(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        for args, keep, align in (([], 0.65, 1), (["--key-share", "0.5"], 0.5, 1), (["--toon"], 1.0, 0),
                                  (["--key-share", "0.6"], 0.4, 1), (["--debug", "lit"], 0.65, 1), (["--debug"], 0.65, 1)):
            path = os.path.join(out, "e.fx")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mme_shadow.main(["write", path] + args), 0, args)
            with open(path, encoding="ascii") as f:
                text = f.read()
            self.assertAlmostEqual(define(text, "SS_KEEP"), keep, places=6)
            self.assertEqual(define(text, "SS_ALIGN"), align)
        with open(path, encoding="ascii") as f:
            self.assertEqual(define(f.read(), "SS_DEBUG"), 1)                 # --debug alone: the shadow


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def oblique_light(light=(-0.5, -1.0, 0.5), scale=0.0225, slant=53.0, rate=1.17 * 0.0016875, offset=(0.11, -0.23, 0.31)):
    """a light's matrix (D3D rows: a point P goes to (P, 1) M) as MMD's measured in the review of softshadow-mme: x and y
    of the map across the light (a point keeps its place on the map along the light), the depth rising `rate` per unit
    along the light and its gradient turned `slant` degrees from the light"""
    L = _unit(light)
    a = _unit(_cross(L, (0.0, 1.0, 0.0)))
    b = _cross(L, a)
    t = _unit(tuple(x + 0.5 * y for x, y in zip(a, b)))
    k = math.tan(math.radians(slant))
    depth = tuple(rate * (l + k * u) for l, u in zip(L, t))
    rows = [[scale * a[i], scale * b[i], depth[i], 0.0] for i in range(3)]
    return rows + [[offset[0], offset[1], offset[2], 1.0]]


def to_map(M, P):
    """(u, v, z): where the point lands on the map (MME: uv = ((1 + x / w) / 2, (1 - y / w) / 2)) and its depth z / w"""
    x, y, z, w = (sum(P[i] * M[i][j] for i in range(3)) + M[3][j] for j in range(4))
    return (1.0 + x / w) / 2.0, (1.0 - y / w) / 2.0, z / w


def warped_light(light=(-0.5, -1.0, 0.5), warp=0.006, **kw):
    """the oblique light with a w that changes across the light (MMD's light matrix: its fourth column is not 0, the
    picture of the map is warped across the light, along the light w stays: softshadow-mme2)"""
    M = oblique_light(light, **kw)
    L = _unit(light)
    a = _unit(_cross(L, (0.0, 1.0, 0.0)))
    b = _cross(L, a)
    c3 = tuple(warp * (u + 0.7 * v) for u, v in zip(a, b))           # across the light only
    for i in range(3):
        M[i][3] = c3[i]
    M[3][3] = 1.3
    return M


class PlaneTest(unittest.TestCase):
    """the depth of the receiver's own plane round a pixel (review of softshadow-mme: MMD's light depth runs some 53 degrees
    off the light, so a point of the map beside the pixel, on the pixel's own plane, has another depth; the search for
    what casts the shadow took the receiver itself, and the points of the Gaussian shadowed it: acne)"""

    LIGHT = (-0.5, -1.0, 0.5)

    def test_the_plane_slope_gives_the_depth_of_the_receivers_plane_round_the_pixel(self):
        M = oblique_light()
        P = (0.7, 9.2, -0.4)
        toward = tuple(-x for x in _unit(self.LIGHT))
        for n in [toward, _unit((0.0, 1.0, 0.0)), _unit((0.3, 0.2, -0.9)), _unit((-0.3, 0.9, 0.2)), _unit((0.5, 0.1, -0.6))]:
            self.assertGreater(_dot(n, toward), mme_shadow.FACING_MIN, n)
            su, sv = mme_shadow.plane_slope(M, n, self.LIGHT)
            t1 = _unit(_cross(n, (0.37, 0.61, 0.7)))
            t2 = _cross(n, t1)
            u0, v0, z0 = to_map(M, P)
            for alpha, beta in ((0.4, 0.0), (0.0, -0.7), (1.3, 0.9), (-2.0, 0.5)):
                Q = tuple(p + alpha * x + beta * y for p, x, y in zip(P, t1, t2))
                u, v, z = to_map(M, Q)
                self.assertAlmostEqual(z - z0, su * (u - u0) + sv * (v - v0), places=12, msg=(n, alpha, beta))

    def test_a_receiver_facing_the_light_has_the_slope_of_the_depths_slant_alone(self):
        toward = tuple(-x for x in _unit(self.LIGHT))
        su, sv = mme_shadow.plane_slope(oblique_light(slant=0.0), toward, self.LIGHT)
        self.assertAlmostEqual(su, 0.0, places=12)          # a depth along the light: the plane facing it keeps one depth
        self.assertAlmostEqual(sv, 0.0, places=12)
        su, sv = mme_shadow.plane_slope(oblique_light(), toward, self.LIGHT)
        # MMD's: 0.0026 of depth per unit across the light (the review), some 0.12 per unit of the map (0.0225 / 2 a unit)
        self.assertGreater(math.hypot(su, sv), 0.1)

    def test_an_edge_on_receiver_is_held_at_the_least_facing(self):
        M = oblique_light()
        L = _unit(self.LIGHT)
        toward = tuple(-x for x in L)
        side = _unit(_cross(L, (0.0, 1.0, 0.0)))                # a plane along the light: no depth of its own
        f = mme_shadow.FACING_MIN
        held = tuple(x * math.sqrt(1.0 - f * f) + y * f for x, y in zip(side, toward))
        got = mme_shadow.plane_slope(M, side, self.LIGHT)
        want = mme_shadow.plane_slope(M, held, self.LIGHT)
        self.assertTrue(all(math.isfinite(x) for x in got))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=12)
        # a face turned from the light is held the same way (its own shade covers it)
        back = tuple(-x for x in toward)
        self.assertTrue(all(math.isfinite(x) for x in mme_shadow.plane_slope(M, back, self.LIGHT)))

    def test_with_the_lights_perspective_the_slope_is_the_planes_round_the_pixel(self):
        # MMD's light matrix divides by w (its fourth column 0.005 a unit across the light, softshadow-mme2): the plane's
        # depth round the pixel follows the columns less the perspective's share there (to first order)
        M = warped_light()
        P = (0.7, 9.2, -0.4)
        toward = tuple(-x for x in _unit(self.LIGHT))
        for n in [toward, _unit((0.0, 1.0, 0.0)), _unit((0.3, 0.2, -0.9)), _unit((-0.3, 0.9, 0.2))]:
            su, sv = mme_shadow.plane_slope(M, n, self.LIGHT, point=P)
            flat_u, flat_v = mme_shadow.plane_slope(M, n, self.LIGHT)       # without the point: the columns as they are
            t1 = _unit(_cross(n, (0.37, 0.61, 0.7)))
            t2 = _cross(n, t1)
            u0, v0, z0 = to_map(M, P)
            for alpha, beta in ((1e-4, 0.0), (0.0, -1e-4), (7e-5, 5e-5)):
                Q = tuple(p + alpha * x + beta * y for p, x, y in zip(P, t1, t2))
                u, v, z = to_map(M, Q)
                got = su * (u - u0) + sv * (v - v0)
                self.assertAlmostEqual(z - z0, got, delta=2e-3 * abs(z - z0) + 1e-14, msg=(n, alpha, beta))
            self.assertGreater(abs(su - flat_u) + abs(sv - flat_v), 0.01)    # the perspective matters

    def test_the_gap_is_a_distance_along_the_light(self):
        M = oblique_light()
        L = _unit(self.LIGHT)
        P = (0.2, 3.0, -1.0)
        for d in (0.5, 2.6, 9.6):
            B = tuple(p - d * l for p, l in zip(P, L))          # what casts the shadow, d up the light from the receiver
            gap = to_map(M, P)[2] - to_map(M, B)[2]
            self.assertAlmostEqual(mme_shadow.along_light(M, self.LIGHT, gap), d, places=9)
        # with the light's perspective (w the same all along the light) the gap is over the rate at the receiver's w
        M = warped_light()
        for d in (0.5, 2.6, 9.6):
            B = tuple(p - d * l for p, l in zip(P, L))
            gap = to_map(M, P)[2] - to_map(M, B)[2]
            self.assertAlmostEqual(mme_shadow.along_light(M, self.LIGHT, gap, point=P), d, places=9)

    def test_the_search_counts_only_what_lies_in_the_lights_cone(self):
        # a thing above the receiver's plane casts a shadow on the pixel only within the light's spread from it: across
        # the light at most SS_CONE standard deviations of the light times its distance along the light (and the least
        # blur).  Beside the pixel and not above it (the next plate of the fan, review of softshadow-mme) it is not a caster
        text = mme_shadow.effect()
        self.assertAlmostEqual(define(text, "SS_CONE"), mme_shadow.KERNEL_SIGMAS, places=6)
        self.assertIn("if (length(off) / perUnit <= SS_CONE * SS_BLUR_RAD * along + SS_MIN_WORLD) {", text)
        self.assertTrue(mme_shadow.in_cone(0.0, 0.2, 5.0, 0.05))
        self.assertTrue(mme_shadow.in_cone(0.9, 4.0, 5.0, 0.05))            # 2.5 x 5 degrees at 4: 0.87 + 0.05
        self.assertFalse(mme_shadow.in_cone(0.95, 4.0, 5.0, 0.05))
        self.assertFalse(mme_shadow.in_cone(1.5, 2.0, 5.0, 0.05))           # the next plate, 1.5 beside and 2 above

    def test_the_search_looks_at_every_scale_round_the_pixel(self):
        # a caster at the distance D along the light counts within 2.5 x the light's spread x D: near the pixel the cone
        # is small (0.38 units at 1.5 for 5 degrees), so the search's points lie from SEARCH_INNER of its radius out to
        # all of it, evenly on a logarithm of the radius, round the golden angle (the even spiral had one point within
        # 0.38 of 1.8 and fell back to MMD's hard test: review of softshadow-mme2)
        pts = mme_shadow.search_points(16)
        radii = sorted(math.hypot(x, y) for x, y, _ in pts)
        self.assertAlmostEqual(radii[0], mme_shadow.SEARCH_INNER, places=6)
        self.assertAlmostEqual(radii[-1], 1.0, places=6)
        steps = [b / a for a, b in zip(radii, radii[1:])]
        self.assertLess(max(steps) - min(steps), 1e-6)                  # the same ratio from each to the next
        cone = (mme_shadow.KERNEL_SIGMAS * math.radians(5.0) * 1.5 + 0.05) / mme_shadow.SEARCH
        self.assertGreaterEqual(sum(1 for r in radii if r <= cone), 6)
        n, rows = array(mme_shadow.effect(), "SEARCH")
        self.assertEqual(n, mme_shadow.DEFAULTS["search_taps"])
        for (x, y, _), (a, b, _) in zip(rows, mme_shadow.search_points(n)):
            self.assertAlmostEqual(x, a, places=6)
            self.assertAlmostEqual(y, b, places=6)

    def test_the_casters_gaps_are_averaged_plainly_over_64_points_by_default(self):
        # review of softshadow-mme2, against the reference of a 5 degree light (MMD's own hard shadow under 64 directions
        # of the light, averaged: tools/selfshadow_check.py against) at 4 frames of the dancer: with the harmonic mean
        # of the gaps (the nearest caster rules) one search point that found a near thing (a fold of the dress) shrank
        # the blur of its pixel alone, and the penumbra came out speckled and lined (8.4 % of its pixels brighter or
        # darker than both neighbours across it, MMD's own 2.1 %) with its outer edge cut (4.5 % of its tail all lit).
        # The plain mean over 64 search points and 64 Gaussian points: 2.4 % and 0.4 %, the mean error the same
        text = mme_shadow.effect()
        self.assertEqual(define(text, "SS_HARMONIC"), 0)
        self.assertLess(text.index("#define SS_HARMONIC 0"), text.index("#ifndef SS_HARMONIC"))   # the body takes it
        self.assertEqual(define(text, "SS_SEARCH"), 64)
        self.assertEqual(define(text, "SS_TAPS"), 64)
        self.assertEqual(array(text, "SEARCH")[0], 64)
        self.assertEqual(array(text, "KERNEL")[0], 64)
        # the points of 64 still lie as the Gaussian lies (a standard deviation of 1 on each axis) and the search from
        # SEARCH_INNER of its radius out to all of it
        pts = mme_shadow.taps(64)
        for axis in (0, 1):
            self.assertAlmostEqual(math.sqrt(sum(p[axis] ** 2 for p in pts) / 64.0), 1.0, delta=0.03)
        radii = sorted(math.hypot(x, y) for x, y, _ in mme_shadow.search_points(64))
        self.assertAlmostEqual(radii[0], mme_shadow.SEARCH_INNER, places=6)
        self.assertAlmostEqual(radii[-1], 1.0, places=6)

    def test_with_no_caster_found_the_least_blur_is_kept(self):
        # no caster in the cone is not a reason for MMD's hard test: the Gaussian at the least blur, as everywhere
        text = mme_shadow.effect()
        self.assertNotIn("return ShadowTest(zc.z, uv, slope);", text)
        self.assertIn("if (found > 0.5f) {", text)

    def test_the_effect_compares_the_map_with_the_receivers_plane(self):
        text = mme_shadow.effect()
        # every point of the map round the pixel, in the search and in the Gaussian, against the receiver's plane there
        self.assertIn("float2 PlaneSlope(float3 n, float3 ndc)", text)
        self.assertIn("LightWorldViewProjMatrix._14", text)             # the perspective's column
        self.assertRegex(text, r"float zr = zc\.z \+ dot\(plane, off\);")
        self.assertRegex(text, r"ShadowTest\(zc\.z \+ dot\(plane, off\), uv \+ off, slope\)")
        # the gap turned into a distance along the light with the light's own matrix (MMD's depth is not along the light:
        # _33 of the projection is not the rate)
        self.assertNotIn("LightProjMatrix._33", text)
        self.assertIn("LightWorldViewProjMatrix._13", text)
        self.assertAlmostEqual(define(text, "SS_FACING_MIN"), mme_shadow.FACING_MIN, places=6)


def array4(text, name):
    m = re.search(r"static const float4 %s\[(\d+)\] = \{(.*?)\};" % name, text, re.S)
    rows = re.findall(r"float4\(([^)]*)\)", m.group(2))
    return int(m.group(1)), [tuple(float(v) for v in r.split(",")) for r in rows]


def _pass_body(text, name):
    """the text of the function `name` of the effect (from its head to the first line that is a lone brace)"""
    start = text.index(name)
    end = text.index("\n}\n", start)
    return text[start:end]


class NightTest(unittest.TestCase):
    """the night's light on her (light3, 2026-10-21; look light.person, @PizaCG's lighting): the effect draws her lit by a
    key light where MMD's light reaches (the soft shadow and the toon's ramp), a fill in the shade, the face between them,
    and a rim light by Fresnel, in colours that change by sections of the song (MME's TIME)"""

    NIGHT = {"on": 1, "key": [0.9, 0.8, 0.7], "fill": [0.15, 0.17, 0.3], "face": 0.7, "rim": [0.5, 0.7, 1.0],
             "rim_power": 2.5, "rim_from": [-0.6, -0.8], "rim_sided": 1.0, "rim_albedo": 0.3, "sections": [], "fade": 0.5}
    # the default effect's text before light3 (0e00708: the soft shadow of v11 r2, the file hinata's model_soft holds)
    BEFORE = "9b06ebd688c245ef9ba3e676b27207ffd90e41ca648cc7a1fe91ebe38088bfdd"

    def test_without_the_night_the_effect_is_byte_for_byte_the_one_of_before(self):
        before = mme_shadow.effect()
        self.assertEqual(hashlib.sha256(before.encode("ascii")).hexdigest(), self.BEFORE)
        self.assertEqual(mme_shadow.effect(light=None), before)
        self.assertEqual(mme_shadow.effect(light={"on": 0}), before)
        self.assertEqual(mme_shadow.effect(light=dict(self.NIGHT, on=0)), before)
        self.assertNotIn("NL_", before)

    def test_the_night_settings_reach_the_shader(self):
        text = mme_shadow.effect(light=self.NIGHT)
        self.assertTrue(text.isascii())
        self.assertEqual(define(text, "SS_NIGHT"), 1)
        self.assertAlmostEqual(define(text, "NL_FACE"), 0.7, places=6)
        self.assertAlmostEqual(define(text, "NL_RIM_POWER"), 2.5, places=6)
        self.assertAlmostEqual(define(text, "NL_RIM_SIDED"), 1.0, places=6)
        self.assertAlmostEqual(define(text, "NL_RIM_ALBEDO"), 0.3, places=6)
        self.assertAlmostEqual(define(text, "NL_FADE"), 0.5, places=6)
        # MMD's light colour scales the key: its default (154; MME gives the panel's colour over 256) is 1
        self.assertAlmostEqual(define(text, "NL_LIGHT_DEFAULT"), 154.0 / 256.0, places=6)
        self.assertIn("LightAmbient / NL_LIGHT_DEFAULT", text)
        n, keys = array4(text, "NL_KEY")
        self.assertEqual(n, 1)
        self.assertEqual(keys, [(0.0, 0.9, 0.8, 0.7)])
        self.assertEqual(array(text, "NL_FILL")[1], [(0.15, 0.17, 0.3)])
        self.assertEqual(array(text, "NL_RIM")[1], [(0.5, 0.7, 1.0)])
        # rim_from is the picture's (x right, y down, as look.rim.from); the shader's view space has y up
        m = re.search(r"^#define NL_RIM_FROM float2\(([^,]+), ([^)]+)\)$", text, re.M)
        self.assertAlmostEqual(float(m.group(1)), -0.6, places=5)
        self.assertAlmostEqual(float(m.group(2)), 0.8, places=5)
        settings = json.loads(text.splitlines()[2].split("Settings:")[1])
        self.assertEqual(settings["light"]["key"], [0.9, 0.8, 0.7])
        # the body's pass only, now drawn by the night's pixel shader; the soft shadow's own techniques are not there
        self.assertEqual(set(re.findall(r'MMDPass = "(\w+)"', text)), {"object_ss"})
        combos = re.findall(r"^NL_TECH\(NL_(\d{3}), (true|false), (true|false), (true|false)\)$", text, re.M)
        self.assertEqual(len(combos), 8)
        self.assertNotIn("\nSS_TECH(SS_", text)

    def test_the_night_draws_key_fill_face_and_rim(self):
        body = _pass_body(mme_shadow.effect(light=self.NIGHT), "float4 NL_PS(")
        # where MMD's light reaches (the soft shadow and the toon's ramp) her colour times the key, in the shade times the
        # fill in the toon's hue (its luma 1)
        self.assertIn("SoftShadow(zc, uv, plane, IN.ZCalcTex.w)", body)
        self.assertIn("saturate(dot(nrm, -LightDirection) * TOON_SLOPE)", body)
        self.assertIn("lerp(fill * hue, key, comp)", body)
        # the materials MMD shades not (no toon, or a white one: the face, the eyes) between the fill and the key
        self.assertIn("lerp(fill, key, NL_FACE)", body)
        self.assertIn("tluma < 0.999f", body)
        # the rim: Fresnel, on the side it comes from
        self.assertIn("pow(1.0f - saturate(dot(nrm, v)), NL_RIM_POWER)", body)
        self.assertIn("NL_RIM_FROM", body)
        # her colour under a white light: MMD's lit colour of the material (ambient + emissive, at most 1), the texture and
        # the sphere map read through MMD's own samplers as the soft shadow reads them
        self.assertIn("saturate(MaterialAmbient + MaterialEmissive)", body)
        self.assertIn("tex2D(MMDSampler1, IN.Tex)", body)
        self.assertIn("tex2D(MMDSampler2, IN.SpTex)", body)

    def test_the_outline_takes_the_nights_light_when_asked(self):
        # MMD draws the outline in the material's edge colour, unlit: on her lit by the night it stood out (the hair's pink).
        # edge below 1: the outline pass too, its colour times edge and the light between the fill and the key
        plain = mme_shadow.effect(light=self.NIGHT)
        self.assertNotIn('MMDPass = "edge"', plain)                       # by default MMD's own outline
        text = mme_shadow.effect(light=dict(self.NIGHT, edge=0.45))
        self.assertAlmostEqual(define(text, "NL_EDGE"), 0.45, places=6)
        self.assertEqual(set(re.findall(r'MMDPass = "(\w+)"', text)), {"object_ss", "edge"})
        body = _pass_body(text, "float4 NL_EdgePS(")
        self.assertIn("EdgeColor.rgb * NL_EDGE", body)
        self.assertIn("lerp(fill, key, 0.5f)", body)
        with self.assertRaises(ValueError):
            mme_shadow.effect(light=dict(self.NIGHT, edge=1.5))

    def test_sections_give_their_colours_from_their_time_faded_in(self):
        a = [0.0, 1.0, 0.55, 0.3, 0.1, 0.12, 0.3, 0.3, 0.5, 1.0]
        b = [44.467, 0.55, 0.5, 1.0, 0.25, 0.12, 0.1, 1.0, 0.6, 0.3]
        night = dict(self.NIGHT, sections=[a, b], fade=0.4)
        text = mme_shadow.effect(light=night)
        n, keys = array4(text, "NL_KEY")
        self.assertEqual(n, 2)
        self.assertEqual(keys[1], tuple(b[:4]))
        self.assertEqual(array(text, "NL_FILL")[1][1], tuple(b[4:7]))
        self.assertEqual(array(text, "NL_RIM")[1][1], tuple(b[7:10]))
        self.assertIn("float NL_Time : TIME < bool SyncInEditMode = true; >;", text)
        self.assertIn("saturate((NL_Time - NL_KEY[i].x) / NL_FADE + 0.5f)", text)
        s = mme_shadow.night(night)
        for t, want in ((10.0, a), (44.467 - 0.2, a), (44.467 + 0.2, b), (200.0, b)):
            key, fill, rim = mme_shadow.section_colours(s, t)
            for got, w in ((key, want[1:4]), (fill, want[4:7]), (rim, want[7:10])):
                for g, x in zip(got, w):
                    self.assertAlmostEqual(g, x, places=9, msg=t)
        key, _, _ = mme_shadow.section_colours(s, 44.467)
        for g, x, y in zip(key, a[1:4], b[1:4]):
            self.assertAlmostEqual(g, 0.5 * (x + y), places=9)
        # without sections the night is one section of its own colours from 0 s
        s = mme_shadow.night(self.NIGHT)
        self.assertEqual(mme_shadow.section_colours(s, 123.0), ([0.9, 0.8, 0.7], [0.15, 0.17, 0.3], [0.5, 0.7, 1.0]))

    def test_wrong_night_settings_are_refused(self):
        for bad in ({"on": 2}, {"key": [1, 1]}, {"key": [1, -0.1, 1]}, {"fill": [0, 0, 9]}, {"face": 1.5},
                    {"rim_power": 0}, {"rim_from": [0, 0]}, {"rim_sided": -0.1}, {"rim_albedo": 2},
                    {"sections": [[0, 1, 1, 1, 0, 0, 0, 0, 0]]}, {"sections": [[5, 1, 1, 1, 0, 0, 0, 0, 0, 0],
                                                                                [3, 1, 1, 1, 0, 0, 0, 0, 0, 0]]},
                    {"sections": [[-1, 1, 1, 1, 0, 0, 0, 0, 0, 0]]}, {"fade": 0}, {"colour": [1, 1, 1]},
                    {"direction": [0, 1, 0]}, {"direction": [0, -1]}):
            with self.assertRaises(ValueError, msg=bad):
                mme_shadow.effect(light=dict(self.NIGHT, **bad))
        # the night is drawn with the soft shadow: not with the effects for measuring
        for other in ({"debug": "shadow"}, {"sharp": True}):
            with self.assertRaises(ValueError, msg=other):
                mme_shadow.effect(light=self.NIGHT, **other)

    def test_prepare_and_write_take_the_look(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        models = os.path.join(folder, "Rin")
        os.makedirs(models)
        model = os.path.join(models, "White.pmx")
        with open(model, "wb") as f:
            f.write(b"PMX")
        look = os.path.join(folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"glow": {"radius": 6}, "light": {"person": self.NIGHT}}, f)
        got = mme_shadow.prepare(model, os.path.join(folder, "out"), variant="night", look=look)
        with open(got["effect"], encoding="ascii") as f:
            text = f.read()
        self.assertEqual(define(text, "SS_NIGHT"), 1)
        self.assertEqual(json.loads(text.splitlines()[2].split("Settings:")[1])["light"]["fill"], [0.15, 0.17, 0.3])
        # a look without the night's light on her writes the soft shadow of before
        plain = os.path.join(folder, "plain.json")
        with open(plain, "w", encoding="utf-8") as f:
            json.dump({"glow": {"radius": 6}}, f)
        got = mme_shadow.prepare(model, os.path.join(folder, "out"), variant="plain", look=plain)
        with open(got["effect"], encoding="ascii", newline="") as f:
            self.assertEqual(f.read().replace("\r\n", "\n"), mme_shadow.effect())
        out = os.path.join(folder, "w.fx")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mme_shadow.main(["write", out, "--look", look]), 0)
        with open(out, encoding="ascii") as f:
            self.assertEqual(define(f.read(), "SS_NIGHT"), 1)


class LightVmdTest(unittest.TestCase):
    def test_the_camera_motion_gets_the_nights_light_and_keeps_its_camera(self):
        sys.path.insert(0, ROOT)
        from mmd_cli.formats import vmd
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cam = os.path.join(folder, "cam.vmd")
        keys = [vmd.CameraKey(frame=f, distance=-45.0, position=(0.0, 10.0, float(f)), rotation=(0.1, 0.0, 0.0))
                for f in (0, 30, 7742)]
        vmd.dump(vmd.Motion.for_camera(cameras=keys, lights=[vmd.LightKey(90, (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))]), cam)
        out = os.path.join(folder, "cam_light.vmd")
        got = mme_shadow.light_vmd(cam, {"on": 1, "direction": [-0.75, -0.55, 0.35]}, out)
        self.assertEqual(got["direction"], [-0.75, -0.55, 0.35])
        m = vmd.load(out)
        self.assertEqual([(k.frame, k.position) for k in m.cameras], [(k.frame, k.position) for k in keys])
        self.assertEqual(len(m.lights), 1)                                   # the light keys it had are left out
        self.assertEqual(m.lights[0].frame, 0)
        for a, b in zip(m.lights[0].rgb, (154.0 / 256.0,) * 3):
            self.assertAlmostEqual(a, b, places=6)                            # MMD's default colour: the key's scale 1
        for a, b in zip(m.lights[0].direction, (-0.75, -0.55, 0.35)):
            self.assertAlmostEqual(a, b, places=6)
        with self.assertRaises(ValueError):
            mme_shadow.light_vmd(cam, None, out)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.models = os.path.join(self.folder, "models", "Rin")
        os.makedirs(os.path.join(self.models, "tex"))
        self.model = os.path.join(self.models, "White.pmx")
        with open(self.model, "wb") as f:
            f.write(b"PMX model bytes")
        with open(os.path.join(self.models, "tex", "skin.png"), "wb") as f:
            f.write(b"texture")

    def test_prepare_copies_the_folder_and_writes_the_effect_beside_the_copy(self):
        out = os.path.join(self.folder, "out")
        got = mme_shadow.prepare(self.model, out)
        self.assertEqual(os.path.normcase(got["model"]), os.path.normcase(os.path.join(out, "Rin", "White.pmx").replace("\\", "/")))
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "tex", "skin.png")))
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "White.fx")))         # MME takes <model name>.fx
        self.assertEqual(sorted(os.listdir(self.models)), ["White.pmx", "tex"])       # the original is not written
        # a variant: <model>[<variant>.fx].pmx beside <variant>.fx
        got = mme_shadow.prepare(self.model, out, variant="debug_soft", debug=True)
        self.assertTrue(got["model"].endswith("Rin/White[debug_soft.fx].pmx"))
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes")
        with open(got["effect"], encoding="ascii") as f:
            self.assertIn("#define SS_DEBUG 1", f.read())
        with self.assertRaises(ValueError):
            mme_shadow.prepare(self.model, out, variant="no spaces")

    def test_prepare_takes_the_model_and_its_textures_again_when_they_changed(self):
        # review of softshadow-mme: the copy was made once and kept, so a model rebuilt since (a new rig, a new skirt)
        # would have been drawn as it was
        out = os.path.join(self.folder, "out")
        mme_shadow.prepare(self.model, out)
        with open(self.model, "wb") as f:
            f.write(b"PMX model bytes, rebuilt")
        with open(os.path.join(self.models, "tex", "skin.png"), "wb") as f:
            f.write(b"texture, painted again")
        got = mme_shadow.prepare(self.model, out)
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes, rebuilt")
        with open(os.path.join(out, "Rin", "tex", "skin.png"), "rb") as f:
            self.assertEqual(f.read(), b"texture, painted again")
        got = mme_shadow.prepare(self.model, out, variant="soft2")
        with open(got["model"], "rb") as f:
            self.assertEqual(f.read(), b"PMX model bytes, rebuilt")
        # what the tool wrote beside the copy stays (the effects), and a copy that did not change is not written again
        self.assertTrue(os.path.isfile(os.path.join(out, "Rin", "White.fx")))
        copied = []
        real = mme_shadow.shutil.copy2
        self.addCleanup(setattr, mme_shadow.shutil, "copy2", real)
        mme_shadow.shutil.copy2 = lambda a, b, **kw: copied.append(os.path.normcase(os.path.abspath(a))) or real(a, b, **kw)
        mme_shadow.prepare(self.model, out)
        self.assertNotIn(os.path.normcase(os.path.join(self.models, "tex", "skin.png")), copied)
        self.assertNotIn(os.path.normcase(self.model), copied)

    def test_prepare_refuses_to_write_into_the_models_own_folder(self):
        with self.assertRaises(ValueError):
            mme_shadow.prepare(self.model, os.path.join(self.folder, "models"))
        with self.assertRaises(ValueError):                                # nor into a folder inside it
            mme_shadow.prepare(self.model, self.models)
        self.assertEqual(sorted(os.listdir(self.models)), ["White.pmx", "tex"])

    def test_check_knows_mme_by_its_files(self):
        mmd = os.path.join(self.folder, "mmd")
        os.makedirs(mmd)
        exe = os.path.join(mmd, "MikuMikuDance.exe")
        open(exe, "wb").close()
        self.assertEqual(mme_shadow.check(exe), {"installed": False, "files": {n: "missing" for n in mme_shadow.MME_FILES}})
        for name in mme_shadow.MME_FILES:
            with open(os.path.join(mmd, name), "wb") as f:
                f.write(b"not the dll")
        self.assertEqual(set(mme_shadow.check(exe)["files"].values()), {"different"})
        # the digest is SHA-256 of the file
        self.assertEqual(mme_shadow.sha256(exe), hashlib.sha256(b"").hexdigest())


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.mmd = os.path.join(self.folder, "mmd")
        os.makedirs(self.mmd)
        self.exe = os.path.join(self.mmd, "MikuMikuDance.exe")
        open(self.exe, "wb").close()
        self.models = os.path.join(self.folder, "models")
        os.makedirs(self.models)
        self.model = os.path.join(self.models, "White.pmx")
        open(self.model, "wb").close()

    def install(self):
        # MME's files as check knows them: their digests made to match
        for name in mme_shadow.MME_FILES:
            with open(os.path.join(self.mmd, name), "wb") as f:
                f.write(name.encode())
        self.addCleanup(setattr, mme_shadow, "MME_FILES", dict(mme_shadow.MME_FILES))
        mme_shadow.MME_FILES = {n: hashlib.sha256(n.encode()).hexdigest() for n in mme_shadow.MME_FILES}

    def test_the_effect_mme_applies_is_the_one_in_brackets_or_the_one_of_the_same_name(self):
        self.assertIsNone(mme_shadow.effect_of(self.model))
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        self.assertTrue(mme_shadow.effect_of(self.model).endswith("White.fx"))
        named = os.path.join(self.models, "White[soft.fx].pmx")
        open(named, "wb").close()
        self.assertIsNone(mme_shadow.effect_of(named))                   # soft.fx is not there yet
        mme_shadow.write(os.path.join(self.models, "soft.fx"))
        self.assertTrue(mme_shadow.effect_of(named).endswith("soft.fx"))

    def test_soft_needs_mme_and_an_effect_of_this_tool(self):
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # no MME
        self.install()
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # no effect
        with open(os.path.join(self.models, "White.fx"), "w") as f:
            f.write("// someone else's effect\n")
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft")             # not ours
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        got = mme_shadow.verify(self.exe, self.model, "soft")
        self.assertEqual(got["self_shadow"], "soft")
        self.assertIn('"blur": 5.0', got["settings"])
        mme_shadow.write(os.path.join(self.models, "White.fx"), key_share=None)          # --toon: a soft shadow too
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "soft")["self_shadow"], "soft")

    def test_soft_takes_the_nights_effect(self):
        # light3: the night's light on her is the soft shadow's body pass drawn in the night's colours: a plan that says soft
        # renders it (its settings say so)
        self.install()
        mme_shadow.write(os.path.join(self.models, "White.fx"), light={"on": 1, "fill": [0.2, 0.2, 0.3]})
        got = mme_shadow.verify(self.exe, self.model, "soft")
        self.assertEqual(got["self_shadow"], "soft")
        self.assertIn('"light":', got["settings"])

    def test_soft_with_a_look_needs_the_looks_night(self):
        # light3: with the look the render uses (mv_chunks' plan "night"), the effect beside the model must draw that look's
        # light.person (or none when the look has none): an effect written for another look is refused before MMD renders
        self.install()
        night = {"on": 1, "fill": [0.2, 0.2, 0.3], "sections": [[0, 1, 0.9, 0.8, 0.2, 0.2, 0.3, 0.4, 0.6, 1.0]]}
        look = os.path.join(self.folder, "look.json")
        with open(look, "w", encoding="utf-8") as f:
            json.dump({"light": {"person": night}}, f)
        fx = os.path.join(self.models, "White.fx")
        mme_shadow.write(fx, light=night)
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "soft", look=look)["self_shadow"], "soft")
        mme_shadow.write(fx, light=dict(night, fill=[0.3, 0.3, 0.3]))                 # another night
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft", look=look)
        mme_shadow.write(fx)                                                          # the soft shadow alone
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft", look=look)
        plain = os.path.join(self.folder, "plain.json")
        with open(plain, "w", encoding="utf-8") as f:
            json.dump({"glow": {"radius": 6}}, f)
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "soft", look=plain)["self_shadow"], "soft")
        mme_shadow.write(fx, light=night)                                             # a night the look does not have
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "soft", look=plain)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mme_shadow.main(["verify", self.exe, self.model, "soft", "--look", look]), 0)
            self.assertEqual(mme_shadow.main(["verify", self.exe, self.model, "soft", "--look", plain]), 2)

    def test_soft_refuses_the_effects_for_measuring(self):
        # review of softshadow-mme: --debug draws the shadow alone (black and white) or the body lit, --sharp MMD's own
        # test; a plan that says soft must not render either
        self.install()
        for settings in ({"debug": "shadow"}, {"debug": "lit"}, {"debug": "toon"}, {"sharp": True}):
            mme_shadow.write(os.path.join(self.models, "White.fx"), **settings)
            with self.assertRaises(ValueError, msg=settings):
                mme_shadow.verify(self.exe, self.model, "soft")

    def test_mmd_refuses_a_model_mme_would_draw_with_an_effect(self):
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")      # no MME at all
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")      # MME is not there
        self.install()
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "mmd")
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "hard")

    def test_mmd_refuses_a_model_another_build_of_mme_would_draw_with_an_effect(self):
        # review of softshadow-mme: MME of another build (not the digests this tool knows) applies the effect all the same
        mme_shadow.write(os.path.join(self.models, "White.fx"))
        with open(os.path.join(self.mmd, "MMEffect.dll"), "wb") as f:
            f.write(b"another build of MME")
        self.assertFalse(mme_shadow.check(self.exe)["installed"])
        with self.assertRaises(ValueError):
            mme_shadow.verify(self.exe, self.model, "mmd")
        os.remove(os.path.join(self.models, "White.fx"))
        self.assertEqual(mme_shadow.verify(self.exe, self.model, "mmd")["self_shadow"], "mmd")   # no effect on the model


if __name__ == "__main__":
    unittest.main()
