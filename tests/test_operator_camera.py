"""tools/operator_camera.py: a camera a person could have run (cuts on the music, shots that change clearly, a camera
that holds, moves at an even pace and follows the dancer a little late), and a traced live camera framed again for
this scene."""
import importlib.util
import math
import os
import random
import unittest

from mmd_cli import fk
from mmd_cli.formats import vmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    """tools/ is not a package: the module is loaded from its file"""
    spec = importlib.util.spec_from_file_location("operator_camera", os.path.join(ROOT, "tools", "operator_camera.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oc = load_tool()
FPS = 30

# Rin's rest heights (Sour's White.pmx): head top 19.5, eyes 17.2, chin (頭) 16.24, chest (上半身2) 13.8, waist 12.23,
# hip joints 10.66, ankles 1.75, toes 0.1
REST = {"headtop": 19.5, "eyes": 17.21, "chin": 16.24, "chest": 13.8, "waist": 12.23, "hips": 10.66, "toes": 0.1,
        "center": 7.85, "lshoulder": 15.28, "rshoulder": 15.28, "lhip": 10.66, "rhip": 10.66, "ltoe": 0.1, "rtoe": 0.1}
SIDE = {"lshoulder": 0.91, "rshoulder": -0.91, "lhip": 0.90, "rhip": -0.90, "ltoe": 0.90, "rtoe": -0.90}


HEAD = ("headtop", "eyes", "chin")


def standing(frames=300, x=0.0, z=0.0, sway=None, jump=None, turn=None, lean=None, pelvis=None):
    """a dancer standing at (x, z) facing the front (-z); sway(frame) -> (dx, dz) moves the whole body, jump(frame) -> dy
    lifts it, turn(frame) -> degrees turns the shoulders about the body's axis, lean(frame) -> dx moves the head alone,
    pelvis(frame) -> degrees turns the lower body (the hip joints, the toes under them and the way 下半身 faces) instead
    of turn"""
    out = {name: [] for name in oc.LANDMARKS + ("lhip", "rhip", "ltoe", "rtoe", "pelvis_front")}
    for f in range(frames):
        dx, dz = sway(f) if sway else (0.0, 0.0)
        dy = jump(f) if jump else 0.0
        a = math.radians(turn(f)) if turn else 0.0
        b = math.radians(pelvis(f)) if pelvis else a
        hx = lean(f) if lean else 0.0
        for name in oc.LANDMARKS + ("lhip", "rhip", "ltoe", "rtoe"):
            h = REST[name] + dy
            s = SIDE.get(name, 0.0)
            c = b if name in ("lhip", "rhip", "ltoe", "rtoe") else a
            out[name].append((x + dx + s * math.cos(c) + (hx if name in HEAD else 0.0), h, z + dz + s * math.sin(c)))
        # a unit in front of 下半身: its -Z turned with the lower body (the side axis is (cos, 0, sin), the front (sin, 0, -cos))
        out["pelvis_front"].append((x + dx + math.sin(b), REST["waist"] + dy, z + dz - math.cos(b)))
    return oc.Dancer(out)


def look_down_at_her_hips(dancer, frame, position):
    """the least of the angles a camera at `position` looks down at the hips (the point between the hip joints, at their
    height) and at either hip joint: its height over each against its distance on the floor, in degrees"""
    out = []
    for name in ("hips", "lhip", "rhip"):
        p = dancer.at(name, frame)
        out.append(math.degrees(math.atan2(position[1] - p[1], math.hypot(position[0] - p[0], position[2] - p[2]))))
    return min(out)


def look_down_at_points(position, points):
    """the least of the angles a camera at `position` looks down at `points`, in degrees"""
    return min(math.degrees(math.atan2(position[1] - p[1], math.hypot(position[0] - p[0], position[2] - p[2])))
               for p in points)


def between_frames(dancer, name, frame, k, of=16):
    """where a landmark of a dancer given per frame is at frame + k / of: straight between its frames (the most a dancer of
    frames tells)"""
    a, b = dancer.at(name, frame), dancer.at(name, frame + 1)
    return tuple(x + (y - x) * k / float(of) for x, y in zip(a, b))


def knees_of(dancer, frame):
    """her knees as the lift of the aim keeps them: half way from each hip joint to the toe under it"""
    return [tuple((a + b) / 2.0 for a, b in zip(dancer.at(hip, frame), dancer.at(toe, frame)))
            for hip, toe in (("lhip", "ltoe"), ("rhip", "rtoe"))]


def look_at_of(cam):
    return tuple(p + cam.reach * v for p, v in zip(cam.position, oc.direction(cam.yaw, cam.pitch)))


def angle_between(a, b):
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


class CameraMathTest(unittest.TestCase):
    def test_the_window_values_put_the_camera_where_it_was_asked(self):
        # whatever the place and the turn, MMD's own reading of the written key (fk.camera_at, camera_position,
        # camera_direction) gives back the camera's place and the way it looks
        rng = random.Random(3)
        for _ in range(200):
            position = (rng.uniform(-40, 40), rng.uniform(1, 40), rng.uniform(-90, 20))
            yaw, pitch = rng.uniform(-179, 179), rng.uniform(-60, 60)
            reach = rng.uniform(5, 300)
            key = oc.camera_key(0, oc.CameraFrame(position, yaw, pitch, 0.0, 30, reach), cut=True)
            back = fk.camera_keys(vmd.loads(vmd.dumps(vmd.Motion.for_camera(cameras=[key]))))
            state = fk.camera_at(back, 0)
            for a, b in zip(fk.camera_position(state), position):
                self.assertAlmostEqual(a, b, places=3)
            self.assertLess(angle_between(fk.camera_direction(state), oc.direction(yaw, pitch)), 1e-3)

    def test_aim_turns_the_camera_onto_the_point(self):
        rng = random.Random(4)
        for _ in range(200):
            p = (rng.uniform(-30, 30), rng.uniform(0, 30), rng.uniform(-80, 0))
            t = (rng.uniform(-10, 10), rng.uniform(0, 20), rng.uniform(-10, 10))
            yaw, pitch = oc.aim(p, t)
            self.assertLess(angle_between(oc.direction(yaw, pitch), [b - a for a, b in zip(p, t)]), 1e-5)

    def test_the_window_yaw_moves_the_camera_to_the_dancers_left(self):
        # Y +90 in the window puts the camera at +x (the dancer's left, the viewer's right when she faces the front)
        p = oc.place_camera((0.0, 10.0, 0.0), 90.0, 0.0, 30.0)
        self.assertGreater(p[0], 29.0)
        self.assertAlmostEqual(p[2], 0.0, places=6)

    def test_a_point_on_the_line_of_sight_is_in_the_middle_and_the_edges_are_at_one(self):
        p, yaw, pitch, fov = (0.0, 12.0, -40.0), 0.0, 0.0, 30
        u, v, depth = oc.project(p, yaw, pitch, 0.0, fov, (0.0, 12.0, 0.0))
        self.assertAlmostEqual(u, 0.0, places=9)
        self.assertAlmostEqual(v, 0.0, places=9)
        self.assertAlmostEqual(depth, 40.0, places=9)
        top = (0.0, 12.0 + 40.0 * math.tan(math.radians(15.0)), 0.0)
        self.assertAlmostEqual(oc.project(p, yaw, pitch, 0.0, fov, top)[1], 1.0, places=9)
        # right on the screen is +x when the camera looks along +z
        self.assertGreater(oc.project(p, yaw, pitch, 0.0, fov, (1.0, 12.0, 0.0))[0], 0.0)

    def test_the_yaw_stays_continuous_through_the_back(self):
        # a camera going round behind the dancer passes Y 180: the written angles do not jump by 360 degrees
        # between two frames (MMD would turn the camera all the way round in one frame)
        yaws = oc.unwrap([170.0, 178.0, -176.0, -170.0])
        self.assertTrue(all(abs(b - a) < 10.0 for a, b in zip(yaws, yaws[1:])), yaws)


class SizeTest(unittest.TestCase):
    def test_the_size_classes_follow_the_share_of_the_body_in_the_picture(self):
        self.assertEqual(oc.classify(1.3, 0.3), "long")
        self.assertEqual(oc.classify(1.05, 0.8), "full")
        self.assertEqual(oc.classify(0.78, 1.2), "knee")
        self.assertEqual(oc.classify(0.5, 2.0), "waist")
        self.assertEqual(oc.classify(0.33, 3.0), "chest")
        self.assertEqual(oc.classify(0.22, 4.0), "face")

    def test_every_size_frames_a_standing_dancer_as_its_class(self):
        dancer = standing(10)
        for size in oc.SIZES:
            for yaw in (0.0, 35.0, -40.0, 180.0):
                cam = oc.frame_size(dancer, 0, size, yaw)
                seen = oc.seen(dancer, 0, cam)
                self.assertEqual(oc.classify(seen["visible"], seen["body_share"]), size, (size, yaw, seen))
                # the head top is inside the picture with room above it (a face shot may lose the tip of the ribbon)
                self.assertLess(seen["headtop_v"], 1.0, (size, seen))
                self.assertGreater(seen["headtop_v"], 0.6 if size != "long" else 0.0, (size, seen))
                self.assertLess(abs(seen["eyes_u"]), 0.05, (size, seen))

    def test_closer_sizes_use_longer_lenses_and_no_size_is_shot_from_below_the_hips(self):
        dancer = standing(10)
        fovs = [oc.SIZE_SPEC[s]["fov"] for s in oc.SIZES]
        self.assertEqual(fovs, sorted(fovs, reverse=True))
        for size in oc.SIZES:
            for yaw in (0.0, 90.0, 180.0):
                for high in (False, True):
                    cam = oc.frame_size(dancer, 0, size, yaw, high=high)
                    self.assertGreaterEqual(cam.position[1], max(oc.LOWEST, REST["hips"] + oc.HIP_MARGIN) - 1e-9, (size, high))

    def test_every_size_is_framed_from_any_height_or_from_the_nearest_height_that_can(self):
        # from far above the head a wide lens cannot put the head top on its row and the cut on the bottom edge at any
        # distance (the two heights never open to the angle needed): the camera comes down until it can, and the
        # result is checked by projecting it back (no silent rounding of an impossible frame)
        dancer = standing(2)
        for size in oc.SIZES:
            for fov in (5, 17, 30, 45):
                for rise in (0.0, 4.0, 8.0, 15.0, 30.0):
                    cam = oc.frame_size(dancer, 0, size, 0.0, fov=fov, height=REST["headtop"] + rise)
                    s = oc.seen(dancer, 0, cam)
                    row = 1.0 - 2.0 * oc.SIZE_SPEC[size]["room"]
                    self.assertAlmostEqual(s["headtop_v"], row, delta=1e-3, msg=(size, fov, rise))
                    self.assertGreater(cam.reach, 1.0, (size, fov, rise))
                    # the cut height lands on the bottom edge
                    bottom, _, _ = oc.picture_span(size, REST["headtop"], REST["toes"])
                    cut = oc.project(cam.position, cam.yaw, cam.pitch, 0.0, cam.fov, (0.0, bottom, 0.0))[1]
                    self.assertAlmostEqual(cut, -1.0, delta=1e-3, msg=(size, fov, rise))
                    # read off the picture the size is the same as long as the lens is no wider than the size's own
                    # (a close size through a wide lens from near and above shows the lower body shortened)
                    if fov <= oc.SIZE_SPEC[size]["fov"]:
                        self.assertEqual(oc.classify(s["visible"], s["body_share"]), size, (size, fov, rise))

    def test_a_high_shot_looks_down(self):
        dancer = standing(10)
        level = oc.frame_size(dancer, 0, "full", 0.0)
        high = oc.frame_size(dancer, 0, "full", 0.0, high=True)
        self.assertGreater(high.pitch, level.pitch + 8.0)
        self.assertGreater(high.position[1], REST["headtop"])


class OperatorTest(unittest.TestCase):
    """the pan and tilt of a person: the camera holds while the dancer stays near the middle, starts a little after
    she has left it, turns at an even pace that it reaches and leaves gently, and comes to rest without swinging past"""

    def run_targets(self, targets, fov=30.0):
        return oc.operate([(t, 0.0) for t in targets], [fov] * len(targets), (targets[0], 0.0))

    def test_the_camera_holds_while_the_target_stays_inside_the_slack(self):
        half = math.degrees(math.atan(math.tan(math.radians(15.0)) * oc.FOLLOW["slack"][0] * 0.8))
        targets = [half * math.sin(2 * math.pi * f / 45.0) for f in range(300)]
        aims = self.run_targets(targets)
        self.assertEqual(max(abs(y) for y, _ in aims), 0.0)

    def test_the_camera_starts_after_the_reaction_time_when_she_nears_the_edge(self):
        # she jumps to near the edge of the picture: the person answers after the reaction time (R2: 0.23-0.37 s)
        edge = math.degrees(math.atan(math.tan(math.radians(15.0)) * 1.3))
        targets = [0.0] * 30 + [edge] * 120
        aims = self.run_targets(targets)
        moved = [f for f, (y, _) in enumerate(aims) if abs(y) > 1e-9]
        reaction = round((oc.FOLLOW["delay"] + oc.FOLLOW["persist"][0]) * FPS)
        self.assertTrue(0.23 * FPS <= reaction <= 0.37 * FPS, reaction)
        self.assertGreaterEqual(moved[0] - 30, reaction)
        self.assertLess(moved[0] - 30, reaction + 3)

    def test_a_moderate_offset_is_answered_later_but_answered(self):
        # still well inside the picture there is no hurry: the person waits to see that she stays there
        slack = math.degrees(math.atan(math.tan(math.radians(15.0)) * oc.FOLLOW["slack"][0]))
        targets = [0.0] * 30 + [2.0 * slack] * 150
        aims = self.run_targets(targets)
        moved = [f for f, (y, _) in enumerate(aims) if abs(y) > 1e-9]
        self.assertGreater(moved[0] - 30, round((oc.FOLLOW["delay"] + oc.FOLLOW["persist"][0]) * FPS) + 3)
        self.assertLess(moved[0] - 30, round((oc.FOLLOW["delay"] + oc.FOLLOW["persist"][1]) * FPS) + 3)
        release = math.degrees(math.atan(math.tan(math.radians(15.0)) * oc.FOLLOW["release"]))
        self.assertAlmostEqual(aims[-1][0], 2.0 * slack, delta=release + 0.05)

    def test_a_long_turn_has_an_even_pace_reached_and_left_gently(self):
        targets = [0.0] * 20 + [40.0] * 200
        aims = self.run_targets(targets)
        speeds = [(b[0] - a[0]) * FPS for a, b in zip(aims, aims[1:])]
        top = max(speeds)
        steady = [s for s in speeds if s > 0.97 * top]
        self.assertGreaterEqual(len(steady), 8)                     # an even pace, not a peak
        accel = [abs(b - a) * FPS for a, b in zip(speeds, speeds[1:])]
        limit = math.degrees(max(oc.FOLLOW["accel"], oc.FOLLOW["brake"]) * math.tan(math.radians(15.0)))
        self.assertLessEqual(max(accel), limit * 1.01)
        # a person's pan speeds up quickly and slows down slowly (R2: the slowing down 48-77 % longer)
        rising = [i for i, s in enumerate(speeds) if 0.02 * top < s < 0.98 * top and i < speeds.index(top)]
        falling = [i for i, s in enumerate(speeds) if 0.02 * top < s < 0.98 * top and i > len(speeds) - 1 - speeds[::-1].index(top)]
        self.assertGreater(len(falling), 1.3 * len(rising), (len(rising), len(falling)))
        self.assertLess(max(y for y, _ in aims), 40.0 + 0.5)       # no swing past the target
        self.assertAlmostEqual(aims[-1][0], 40.0, delta=math.degrees(math.atan(math.tan(math.radians(15.0)) * oc.FOLLOW["release"])) + 0.05)

    def test_the_camera_does_not_chase_a_quick_dip_of_the_head(self):
        # the head swings well out of the slack for half a second and comes back (a move of the dance): a person does not
        # pan after it, or the pan lands after she is back and throws her to the other side (R1: do not follow the
        # dancer's back and forth with the camera)
        slack = math.degrees(math.atan(math.tan(math.radians(15.0)) * oc.FOLLOW["slack"][0]))
        dip = 2.0 * slack
        targets = [0.0] * 30 + [dip] * 18 + [0.0] * 120
        aims = self.run_targets(targets)
        self.assertLess(max(abs(y) for y, _ in aims), 0.5 * dip)               # a small answer at most
        self.assertGreater(min(t - y for t, (y, _) in zip(targets, aims)), -slack)  # never throws her to the other side
        self.assertLess(abs(aims[-1][0]), 0.25 * slack)     # and ends near where it was (a rest inside the slack stays)

    def test_following_a_steady_walk_lags_behind(self):
        # the dancer drifts at a steady pace: the camera follows a little late, never ahead (a14: the old camera led
        # her steps by 2.6 s)
        targets = [0.0] * 30 + [0.15 * f for f in range(270)]
        aims = self.run_targets(targets)
        lag = oc.lag_seconds([t for t in targets], [y for y, _ in aims])
        self.assertGreater(lag, 0.15)
        self.assertLess(lag, 0.8)
        self.assertTrue(all(y <= t + 1e-9 for t, (y, _) in zip(targets, aims)))

    def test_the_pace_scales_with_the_lens(self):
        # a long lens turns by fewer degrees for the same share of the picture
        wide = oc.operate([(t, 0.0) for t in [0.0] * 20 + [8.0] * 120], [30.0] * 140, (0.0, 0.0))
        tele = oc.operate([(t, 0.0) for t in [0.0] * 20 + [1.3] * 120], [5.0] * 140, (0.0, 0.0))
        w = max((b[0] - a[0]) for a, b in zip(wide, wide[1:]))
        t = max((b[0] - a[0]) for a, b in zip(tele, tele[1:]))
        self.assertAlmostEqual(t / w, math.tan(math.radians(2.5)) / math.tan(math.radians(15.0)), delta=0.02)


class MoveTest(unittest.TestCase):
    def test_a_move_holds_then_eases_into_an_even_pace_and_holds_again(self):
        f = oc.move_profile(120, 30, 90)
        self.assertEqual(f[:31], [0.0] * 31)
        self.assertEqual(f[90:], [1.0] * 30)
        speeds = [b - a for a, b in zip(f, f[1:])]
        middle = speeds[45:75]
        self.assertLess(max(middle) - min(middle), 1e-9)            # even pace in the middle
        self.assertTrue(all(b >= a for a, b in zip(f, f[1:])))
        self.assertLess(speeds[31], 0.25 * max(speeds))             # starts gently
        self.assertLess(speeds[88], 0.25 * max(speeds))             # ends gently

    def test_a_short_move_is_eased_all_the_way(self):
        f = oc.move_profile(20, 2, 12)
        self.assertEqual((f[2], f[12]), (0.0, 1.0))
        self.assertTrue(all(b >= a for a, b in zip(f, f[1:])))


def song(last_bar=40):
    """a song of 120 BPM (a bar of 2 s, 60 frames) starting on frame 0: intro 4 bars, verse 8, build 4, chorus 16,
    outro to the end; lines are sung at the heads of bars 5, 13 and 21"""
    return oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=last_bar * 60 - 1,
                    sections=[(0, "intro", "intro"), (16, "A", "verse"), (48, "B", "build"), (64, "chorus", "chorus"),
                              (128, "outro", "outro")],
                    lines=[10.0, 26.0, 42.0], hooks=[])


def calm(frames):
    return standing(frames, sway=lambda f: (0.4 * math.sin(2 * math.pi * f / 90.0), 0.0))


class MusicTest(unittest.TestCase):
    def test_the_bar_lines_and_the_sections(self):
        m = song()
        self.assertEqual(m.bar_frame(0), 0)
        self.assertEqual(m.bar_frame(5), 300)
        self.assertEqual(m.section_at(299)[0], "A")
        self.assertEqual(m.section_at(960)[1], "chorus")
        self.assertEqual(m.section_at(2399)[0], "outro")

    def test_the_music_file_is_read_and_checked(self):
        data = {"first_beat": 0.016, "period": 0.4285714, "beats_per_bar": 4, "last_frame": 7742,
                "sections": [[0, "intro", "intro"], [140, "chorus1", "chorus"]], "lines": [32.6], "hooks": [86.9]}
        m = oc.Music.from_json(data)
        self.assertEqual(m.bar_frame(35), round((0.016 + 140 * 0.4285714) * 30))
        for broken in ({"period": 0.4}, dict(data, sections=[[0, "x", "dance"]]), dict(data, sections=[[4, "a", "verse"]])):
            with self.assertRaises(ValueError):
                oc.Music.from_json(broken)


class MusicPlanTest(unittest.TestCase):
    def setUp(self):
        self.music = song()
        self.dancer = calm(self.music.last_frame + 1)
        self.shots = oc.plan_music(self.music, self.dancer, seed=0)

    def test_the_shots_cover_the_song_in_order(self):
        self.assertEqual(self.shots[0].start, 0)
        self.assertEqual(self.shots[-1].end, self.music.last_frame)
        for a, b in zip(self.shots, self.shots[1:]):
            self.assertEqual(b.start, a.end + 1)

    def test_cuts_fall_on_bar_lines_and_on_every_section_head(self):
        bars = {self.music.bar_frame(b) for b in range(41)}
        starts = [s.start for s in self.shots]
        self.assertTrue(set(starts) <= bars, sorted(set(starts) - bars))
        for beat, _, _ in self.music.sections:
            self.assertIn(self.music.beat_frame(beat), starts)
        # 8-bar phrases are cut too: bar 24 is the second phrase of the chorus (bar 16)
        self.assertIn(self.music.bar_frame(24), starts)

    def test_chorus_shots_are_shorter_than_verse_shots(self):
        def bars_of(kind):
            return [(s.end - s.start + 1) / 60.0 for s in self.shots if s.kind == kind]
        self.assertLessEqual(max(bars_of("chorus")), 2.0)
        self.assertEqual(min(bars_of("verse")), 4.0)

    def test_every_cut_changes_the_size_by_half_or_the_view_by_30_degrees(self):
        for a, b in zip(self.shots, self.shots[1:]):
            ratio = oc.size_ratio(a.size, b.size)
            turn = abs(((b.yaw - a.yaw) + 180.0) % 360.0 - 180.0)
            self.assertTrue(ratio >= 1.5 or turn >= 30.0, (a.start, a.size, a.yaw, b.size, b.yaw))
        # and so the frames show it, though she has moved since the cut was planned
        dancer = standing(self.music.last_frame + 1, sway=lambda f: (3.0 * math.sin(2 * math.pi * f / 170.0),
                                                                      2.0 * math.sin(2 * math.pi * f / 230.0)))
        shots = oc.plan_music(self.music, dancer, seed=0)
        frames, cuts = oc.make_path(dancer, shots)
        for c in cuts[1:]:
            ratio, turn = oc.cut_change(dancer, c, frames[c - 1], frames[c])
            self.assertTrue(ratio >= 1.5 or turn >= 30.0, (c, ratio, turn))

    def test_the_sizes_are_mixed_and_close_ones_come_with_sung_lines(self):
        sizes = {s.size for s in self.shots}
        self.assertTrue({"long", "full"} & sizes and {"knee", "waist"} & sizes and {"chest", "face"} & sizes, sizes)
        sung = [s for s in self.shots if any(s.start <= t * 30 <= s.end for t, _ in self.music.lines)]
        self.assertTrue(all(s.size in ("chest", "face", "waist") for s in sung), [(s.start, s.size) for s in sung])

    def test_a_close_shot_on_a_sung_line_is_taken_from_where_she_faces(self):
        # she sings turned 30 degrees round to +x: the close shot of the line comes from that side, where her eyes can
        # reach the camera (the gaze tool looks at the camera only within 18 degrees of her face), not from a side angle
        dancer = standing(self.music.last_frame + 1, turn=lambda f: 30.0,
                          sway=lambda f: (0.4 * math.sin(2 * math.pi * f / 90.0), 0.0))
        for shot in oc.plan_music(self.music, dancer, seed=0):
            if shot.size in ("face", "chest") and self.music.sung(shot.start, shot.end):
                turn = abs(((shot.yaw - 30.0) + 180.0) % 360.0 - 180.0)
                self.assertLessEqual(turn, oc.FACE_REACH, shot)
        # a line in every bar of the chorus: one close shot after another may not swing round to the side to make
        # its cut clear; it takes another size instead
        music = oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=self.music.last_frame,
                         sections=self.music.sections, lines=[(2.0 * b + 0.2, 2.0 * b + 1.8) for b in range(16, 32)], hooks=[])
        shots = oc.plan_music(music, calm(self.music.last_frame + 1), seed=0)
        close = [s for s in shots if s.size in ("face", "chest") and music.sung(s.start, s.end)]
        self.assertTrue(close)
        for shot in close:
            self.assertLessEqual(abs(((shot.yaw - 0.0) + 180.0) % 360.0 - 180.0), oc.FACE_REACH, shot)

    def test_a_shot_inside_a_long_sung_line_counts_as_sung(self):
        # the line starts in the shot before (a 4-bar verse shot) and is sung through most of the next, short one (as
        # the line sung at 197 s, standing still into chorus 3): the short shot is a close one
        music = oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=959,
                         sections=[(0, "A", "verse"), (16, "B", "build")], lines=[(7.5, 10.0)], hooks=[])
        dancer = calm(960)
        shots = oc.plan_music(music, dancer, seed=0)
        inside = [s for s in shots if s.start == 240]            # the build's first shot, 8.0-12.0 s
        self.assertEqual(len(inside), 1)
        self.assertIn(inside[0].size, ("face", "chest"), inside[0])
        self.assertEqual(oc.Music.from_json({"first_beat": 0, "period": 0.5, "beats_per_bar": 4, "last_frame": 99,
                                             "sections": [[0, "A", "verse"]], "lines": [[1.0, 2.5], 3.0]}).lines,
                         [(1.0, 2.5), (3.0, None)])

    def test_a_close_shot_that_ends_in_a_fast_move_of_her_head_is_cut_onto_the_move(self):
        # the close shot of a sung line (8.0-12.0 s) would end with her head moving fast in its last beat (from frame 350,
        # 3 units in 8 frames: as 198.5 s, the head turning into chorus 3, where the face shot of 197 s ended blurred and
        # off to the side: review camera-v2).  The cut comes onto the move (cut on action), up to a beat before the bar
        # line; the close shot shows her head calm to its end
        music = oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=959,
                         sections=[(0, "A", "verse"), (16, "B", "build")], lines=[(7.5, 10.0)], hooks=[])
        dancer = standing(960, sway=lambda f: (0.4 * math.sin(2 * math.pi * f / 90.0), 0.0),
                          lean=lambda f: 3.0 * min(1.0, max(0.0, (f - 350) / 8.0)))
        shots = oc.plan_music(music, dancer, seed=0)
        close = [s for s in shots if s.start == 240]
        self.assertEqual(len(close), 1)
        self.assertIn(close[0].size, ("face", "chest"), close[0])
        after = shots[shots.index(close[0]) + 1]
        self.assertEqual(after.start, close[0].end + 1)
        self.assertTrue(345 <= after.start <= 351, (close[0], after))
        speeds = oc.Moments(dancer).head_speed
        self.assertLessEqual(max(speeds[f] for f in range(close[0].start, close[0].end + 1)), oc.CALM_HEAD, close[0])
        self.assertEqual(after.early, 360 - after.start)
        # the cut still changes the picture clearly, and the frames show it
        frames, cuts = oc.make_path(dancer, shots)
        ratio, turn = oc.cut_change(dancer, after.start, frames[after.start - 1], frames[after.start])
        self.assertTrue(ratio >= 1.5 or turn >= 30.0, (ratio, turn))
        # without the move the cut stays on the bar line
        plain = oc.plan_music(music, calm(960), seed=0)
        self.assertIn(360, [s.start for s in plain])
        self.assertTrue(all(s.early == 0 for s in plain))

    def test_no_close_shot_where_she_spins_or_jumps(self):
        busy = list(range(1300, 1316))           # in the chorus: a jump of 2 units for half a second

        def jump(f):
            return 2.0 * math.sin(math.pi * (f - 1300) / 16.0) if 1300 <= f < 1316 else 0.0
        dancer = standing(self.music.last_frame + 1, jump=jump)
        for shot in oc.plan_music(self.music, dancer, seed=0):
            if shot.start <= busy[-1] and shot.end >= busy[0]:
                self.assertIn(shot.size, ("long", "full", "knee"), shot)
        # a full turn in a second, inside the verse where a line is sung at frame 300
        dancer = standing(self.music.last_frame + 1, turn=lambda f: 360.0 * min(1.0, max(0.0, (f - 310) / 30.0)))
        for shot in oc.plan_music(self.music, dancer, seed=0):
            if shot.start <= 340 and shot.end >= 310:
                self.assertIn(shot.size, ("long", "full", "knee"), shot)

    def test_moves_start_and_end_on_the_beat_and_hold_before_and_after(self):
        moving = [s for s in self.shots if s.move != "hold"]
        self.assertTrue(moving)
        beats = {self.music.beat_frame(b) for b in range(161)}
        for s in moving:
            self.assertIn(s.move_start, beats, s)
            self.assertIn(s.move_end, beats, s)
            self.assertGreater(s.move_start, s.start)
            self.assertLess(s.move_end, s.end)

    def test_a_cut_planned_30_degrees_round_her_is_less_once_she_has_walked_aside(self):
        # the shot before was framed where she stood at its start; at the cut she is 6 units to the side away from the
        # next camera (it stands 30 degrees round to +x): seen from where she is now the old camera is round to +x as
        # well, and the two are less than 30 degrees apart
        still = standing(2)
        moved = standing(2, sway=lambda f: (-6.0 * f, 0.0))
        before = oc.frame_size(still, 0, "waist", 0.0)
        after = oc.frame_size(moved, 1, "waist", 30.0)
        self.assertTrue(oc.clear_cut(oc.Shot(0, 0, "waist", 0.0, 20), "waist", 30.0))
        ratio, turn = oc.cut_change(moved, 1, before, after)
        self.assertLess(turn, 30.0)
        self.assertFalse(oc.clear_on_frames(moved, 1, before, after))

    def test_the_camera_holds_while_she_jumps_and_moves_while_she_is_calm(self):
        # a dance DP: "when the dancers are still, the camera moves.  When dancers move, the camera is still" (R1 2-3)
        def jump(f):
            return 2.0 * math.sin(math.pi * ((f % 60) - 20) / 16.0) if 240 <= f < 720 and 20 <= f % 60 < 36 else 0.0
        dancer = standing(self.music.last_frame + 1, jump=jump)       # a jump in every bar of the verse (bars 4-11)
        moving = [s for s in oc.plan_music(self.music, dancer, seed=0) if s.move != "hold"]
        self.assertTrue(moving)
        for s in moving:
            self.assertFalse(s.move_end > 240 and s.move_start < 720, s)

    def test_face_shots_are_short_and_chest_shots_not_long(self):
        for s in self.shots:
            bars = (s.end - s.start + 1) / 60.0
            if s.size == "face":
                self.assertLessEqual(bars, 2.0, s)
            if s.size == "chest":
                self.assertLessEqual(bars, 4.0, s)

    def test_a_jump_does_not_widen_a_knee_shot_to_a_long_one(self):
        # her head top leaving the picture for a moment is no reason to lose the size; her eyes leaving it is
        def jump(f):
            return 2.0 * math.sin(math.pi * ((f % 60) - 20) / 16.0) if 20 <= f % 60 < 36 else 0.0
        dancer = standing(240, jump=jump)
        shot = oc.Shot(start=0, end=239, size="knee", yaw=0.0, fov=oc.SIZE_SPEC["knee"]["fov"])
        self.assertLessEqual(oc.eyes_out_share(dancer, shot, oc.shoot(dancer, shot)), oc.EYES_OUT)

    def test_the_same_seed_plans_the_same_shots(self):
        again = oc.plan_music(self.music, self.dancer, seed=0)
        self.assertEqual([dataclasses_tuple(s) for s in again], [dataclasses_tuple(s) for s in self.shots])


def dataclasses_tuple(shot):
    return (shot.start, shot.end, shot.size, round(shot.yaw, 6), shot.move, shot.move_start, shot.move_end)


class ShootTest(unittest.TestCase):
    """the frames of a shot: the cut shows the planned size, the camera never sits below the hips, and the dancer's
    eyes stay in the picture while she moves"""

    def test_the_first_frame_of_a_shot_shows_its_size(self):
        dancer = calm(200)
        for size in oc.SIZES:
            shot = oc.Shot(start=0, end=119, size=size, yaw=20.0, fov=oc.SIZE_SPEC[size]["fov"])
            first = oc.shoot(dancer, shot)[0]
            s = oc.seen(dancer, 0, first)
            self.assertEqual(oc.classify(s["visible"], s["body_share"]), size)

    def test_no_frame_puts_the_camera_below_the_hips_of_a_jumping_dancer(self):
        def jump(f):
            return 3.0 * max(0.0, math.sin(2 * math.pi * f / 40.0))
        dancer = standing(240, jump=jump)
        for size in oc.SIZES:
            for move, amount in (("hold", 0.0), ("crane", -8.0), ("push", 0.8)):
                shot = oc.Shot(start=0, end=239, size=size, yaw=0.0, fov=oc.SIZE_SPEC[size]["fov"], move=move,
                               move_start=30, move_end=150, amount=amount)
                for f, cam in enumerate(oc.shoot(dancer, shot)):
                    self.assertGreaterEqual(cam.position[1], dancer.at("hips", f)[1] + oc.HIP_MARGIN - 1e-6, (size, move, f))
                    self.assertGreaterEqual(cam.position[1], oc.LOWEST - 1e-9)

    def test_the_requesters_floor_holds_in_literal_numbers(self):
        # the requester's rule (no low angle: a camera below the hips showed what is under the skirt in a spin) in the
        # numbers it was given in, not the tool's own constants: never below height 10 nor below her hips + 1 unit
        def jump(f):
            return 3.0 * max(0.0, math.sin(2 * math.pi * f / 40.0))

        def crouch(f):                       # low the whole shot, hips 7.7: hips + 1 is under 10, and 10 is the floor
            return -3.0
        for dancer in (standing(240, jump=jump), standing(240, jump=crouch)):
            for size in oc.SIZES:
                for move, amount in (("hold", 0.0), ("crane", -8.0)):
                    shot = oc.Shot(start=0, end=239, size=size, yaw=0.0, fov=oc.SIZE_SPEC[size]["fov"], move=move,
                                   move_start=30, move_end=150, amount=amount, height=0.0)
                    for f, cam in enumerate(oc.shoot(dancer, shot)):
                        self.assertGreaterEqual(cam.position[1], max(10.0, dancer.at("hips", f)[1] + 1.0) - 1e-6,
                                                (size, move, f))

    def test_a_shot_that_shows_her_hips_looks_down_at_them_however_far_away(self):
        # review camera-v2: a long lens 240 units away at hips + 3 looked at her hips from 0.7 degrees above (level), and
        # the skirt lifted by a spin and a kick showed what is under it (99.4 s and 253.6 s of the live trace).  A size
        # that shows the hips (long, full, knee) looks down at them by 4 degrees or more on every frame, near or far,
        # while the trace pulls out too (D and A looked down 3.3 to 6.8 degrees at the same moment and showed nothing)
        dancer = standing(90, turn=lambda f: 12.0 * f)
        for size in ("long", "full", "knee"):
            for fov, pull in ((5, 1.3), (30, 1.0)):
                shot = oc.Shot(0, 89, size, 0.0, fov, height=REST["hips"] + 1.0,
                               reach_path=[1.0 + (pull - 1.0) * i / 89.0 for i in range(90)], source="trace")
                for f, cam in enumerate(oc.shoot(dancer, shot)):
                    hips = dancer.at("hips", f)
                    d = math.hypot(cam.position[0] - hips[0], cam.position[2] - hips[2])
                    look_down = math.degrees(math.atan2(cam.position[1] - hips[1], d))
                    self.assertGreaterEqual(look_down, 4.0 - 1e-6, (size, fov, f, look_down))
        # a close size cuts the skirt out of the picture and may stay at the height of the eyes
        chest = oc.shoot(dancer, oc.Shot(0, 89, "chest", 0.0, 5, height=REST["eyes"], reach_path=[1.0] * 90, source="trace"))
        self.assertAlmostEqual(chest[0].position[1], REST["eyes"], delta=0.5)

    def test_every_frame_that_shows_her_hips_looks_down_at_them_by_4_5_degrees(self):
        # the rule as the coordinator gave it (HANDOVER 10/14): the camera looks down at her hips by 4.5 degrees or more,
        # counted on every frame whose picture shows them, from where the camera is on that frame.  The review's fix
        # raised the camera for the distance planned at the cut; she can still walk away from the camera during the shot
        # (here 30 units in 4 s from a long lens 200 units off), and a waist shot shows her hips too (its bottom edge is
        # at half her body, the hips at 0.46); the review's measure still found 3.2-3.5 degrees in two such places
        def look_down(dancer, f, cam):
            hips = dancer.at("hips", f)
            u, v, depth = oc.project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, hips)
            inside = depth > 0 and abs(u) <= ASPECT_EDGE and abs(v) <= 1.0
            d = math.hypot(cam.position[0] - hips[0], cam.position[2] - hips[2])
            return inside, math.degrees(math.atan2(cam.position[1] - hips[1], d))
        away = standing(120, sway=lambda f: (0.0, 0.25 * f), turn=lambda f: 9.0 * f)
        for size in ("full", "knee", "waist"):
            shot = oc.Shot(0, 119, size, 0.0, 5, height=REST["hips"] + 1.0, reach_path=[1.0] * 120, source="trace")
            seen_hips = 0
            for f, cam in enumerate(oc.shoot(away, shot)):
                inside, angle = look_down(away, f, cam)
                if inside:
                    seen_hips += 1
                    self.assertGreaterEqual(angle, 4.5 - 1e-6, (size, f, angle))
            self.assertGreater(seen_hips, 100, size)

    def test_a_fast_spin_is_looked_down_at_from_15_degrees(self):
        # in the strongest spin of the song (58.9 s, up to 696 deg/s) the skirt flares nearly level, and the underwear
        # showed from the current camera looking down at her hips by 4.35 to 10 degrees, not from 12 or more (the look-down
        # test of the fix round, NOTES).  While her shoulders turn faster than FLARE_SPIN (and FLARE_HOLD frames around),
        # every frame that shows her hips looks down at them by 15 degrees or more; a slow turn keeps the 4.5 degrees
        def look_down(dancer, f, cam):
            hips = dancer.at("hips", f)
            u, v, depth = oc.project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, hips)
            inside = depth > 0 and abs(u) <= ASPECT_EDGE and abs(v) <= 1.0
            d = math.hypot(cam.position[0] - hips[0], cam.position[2] - hips[2])
            return inside, math.degrees(math.atan2(cam.position[1] - hips[1], d))
        spin = standing(120, turn=lambda f: 20.0 * min(30.0, max(0.0, f - 40.0)))     # 600 deg/s over frames 40-70
        flare = oc.flare_frames(spin)
        self.assertTrue(all(flare[f] for f in range(40, 71)))
        self.assertFalse(any(flare[f] for f in list(range(0, 25)) + list(range(90, 120))))
        for size, fov in (("full", 5), ("knee", 24), ("long", 30)):
            shot = oc.Shot(0, 119, size, 0.0, fov, height=REST["hips"] + 1.0, reach_path=[1.0] * 120, source="trace")
            for f, cam in enumerate(oc.shoot(spin, shot)):
                inside, angle = look_down(spin, f, cam)
                if inside and flare[f]:
                    self.assertGreaterEqual(angle, 15.0 - 1e-6, (size, f, angle))
        slow = standing(120, turn=lambda f: 3.0 * f)                                   # 90 deg/s
        self.assertFalse(any(oc.flare_frames(slow)))
        shot = oc.Shot(0, 119, "full", 0.0, 5, height=REST["hips"] + 1.0, reach_path=[1.0] * 120, source="trace")
        angles = [look_down(slow, f, cam)[1] for f, cam in enumerate(oc.shoot(slow, shot))]
        self.assertLess(max(angles), 10.0)

    def test_the_eyes_stay_in_the_picture_of_a_close_shot_while_she_sways(self):
        dancer = standing(300, sway=lambda f: (2.5 * math.sin(2 * math.pi * f / 150.0), 0.0))
        shot = oc.Shot(start=0, end=299, size="chest", yaw=0.0, fov=oc.SIZE_SPEC["chest"]["fov"])
        inside = 0
        for f, cam in enumerate(oc.shoot(dancer, shot)):
            s = oc.seen(dancer, f, cam)
            inside += abs(s["eyes_u"]) < ASPECT_EDGE and abs(s["eyes_v"]) < 1.0
        self.assertEqual(inside, 300)

    def test_a_quick_swing_of_the_whole_body_is_not_chased_but_a_step_aside_is_followed_late(self):
        # 3 units to the left and back within 0.9 s (a move of the dance, as at 4680 of the song): in a chest shot she
        # goes most of the way to the edge of the picture and is back before a person who turned there would arrive;
        # the camera hardly turns.  3 units to the left to stay there: the camera follows, not before she has started
        def swing(f):
            u = (f - 60) / 27.0
            return (-3.0 * math.sin(math.pi * u) if 0 <= u <= 1 else 0.0, 0.0)
        dancer = standing(240, sway=swing)
        frames = oc.shoot(dancer, oc.Shot(start=0, end=239, size="chest", yaw=0.0, fov=oc.SIZE_SPEC["chest"]["fov"]))
        pan = max(c.yaw for c in frames) - min(c.yaw for c in frames)
        swing_angle = math.degrees(math.atan2(3.0, abs(frames[0].position[2])))
        self.assertLess(pan, 0.3 * swing_angle, (pan, swing_angle))
        self.assertLess(max(abs(oc.seen(dancer, f, c)["eyes_u"]) for f, c in enumerate(frames)), ASPECT_EDGE)

        def step(f):
            return (-3.0 * min(1.0, max(0.0, (f - 60) / 15.0)), 0.0)
        dancer = standing(240, sway=step)
        frames = oc.shoot(dancer, oc.Shot(start=0, end=239, size="waist", yaw=0.0, fov=oc.SIZE_SPEC["waist"]["fov"]))
        moved = [f for f, c in enumerate(frames) if abs(c.yaw - frames[0].yaw) > 1e-6]
        self.assertTrue(moved)
        self.assertGreaterEqual(moved[0], 60 + round((oc.FOLLOW["delay"] + oc.FOLLOW["persist"][0]) * FPS))
        s = oc.seen(dancer, 239, frames[-1])
        self.assertLess(abs(s["eyes_u"]), 0.5)

    def test_a_chest_shot_follows_her_body_more_than_her_swinging_head(self):
        # the head leans 1.5 units to each side every 3 s while the body stays: the camera of a chest shot frames the
        # upper body and turns less than the head's swing (a face shot keeps the eyes, so it may follow more)
        dancer = standing(300, lean=lambda f: 1.5 * math.sin(2 * math.pi * f / 90.0))
        frames = oc.shoot(dancer, oc.Shot(start=0, end=299, size="chest", yaw=0.0, fov=oc.SIZE_SPEC["chest"]["fov"]))
        pan = max(c.yaw for c in frames) - min(c.yaw for c in frames)
        swing = 2.0 * math.degrees(math.atan2(1.5, abs(frames[0].position[2])))
        self.assertLess(pan, 0.25 * swing, (pan, swing))
        for f, cam in enumerate(frames):
            s = oc.seen(dancer, f, cam)
            self.assertLess(abs(s["eyes_u"]), ASPECT_EDGE)

    def test_an_arc_goes_round_her_and_a_push_comes_closer(self):
        dancer = standing(200)
        arc = oc.shoot(dancer, oc.Shot(start=0, end=199, size="full", yaw=0.0, fov=27, move="arc", move_start=30,
                                       move_end=150, amount=20.0))
        self.assertAlmostEqual(arc[-1].yaw - arc[0].yaw, 20.0, delta=1.0)
        push = oc.shoot(dancer, oc.Shot(start=0, end=199, size="full", yaw=0.0, fov=27, move="push", move_start=30,
                                        move_end=150, amount=0.8))
        d0 = math.hypot(push[0].position[0], push[0].position[2])
        d1 = math.hypot(push[-1].position[0], push[-1].position[2])
        self.assertAlmostEqual(d1 / d0, 0.8, delta=0.01)


ASPECT_EDGE = 16.0 / 9.0


def tkey(frame, look_at, distance, rot, fov):
    from mmd_cli import motion_edit
    return motion_edit.camera_key_from_ui({"pos": look_at, "distance": distance, "rot": rot, "fov": fov, "perspective": True},
                                          frame=frame)


def live_trace():
    """a traced live camera in the manner of the distributed one: two keys a shot, straight between them, cut by two
    keys one frame apart.  0-59 a wide view of the hall from below (the dancer tiny, the camera under the floor's
    level of her hips), 60-119 a long lens level at her waist, 120-179 a long lens pulling out (distance 100 -> 125),
    180-239 a wide view going round her (Y -20 -> +20), 240-299 a long lens from behind (Y 180)"""
    keys = [tkey(0, (0, 60, 0), 500, (-6, 0, 0), 30), tkey(59, (0, 60, 0), 500, (-6, 0, 0), 30),
            tkey(60, (0, 12, 0), 325, (0, 0, 0), 5), tkey(119, (0, 12, 0), 325, (0, 0, 0), 5),
            tkey(120, (0, 16, 0), 100, (0, 0, 0), 5), tkey(179, (0, 16, 0), 125, (0, 0, 0), 5),
            tkey(180, (0, 40, 0), 250, (-9, -20, 0), 30), tkey(239, (0, 40, 0), 250, (-9, 20, 0), 30),
            tkey(240, (0, 12, 0), 300, (0, 180, 0), 5), tkey(299, (0, 12, 0), 300, (0, 180, 0), 5)]
    return vmd.Motion.for_camera(cameras=keys)


def trace_song():
    return oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=299,
                    sections=[(0, "A", "verse")], lines=[2.5, 6.5], hooks=[])


class TraceTest(unittest.TestCase):
    def test_the_trace_is_read_as_its_shots(self):
        shots = oc.read_trace(live_trace(), 299)
        self.assertEqual([(s.start, s.end) for s in shots], [(0, 59), (60, 119), (120, 179), (180, 239), (240, 299)])
        self.assertEqual([s.fov for s in shots], [30, 5, 5, 30, 5])
        self.assertAlmostEqual(shots[3].yaws[0], -20.0, places=3)
        self.assertAlmostEqual(shots[3].yaws[-1], 20.0, places=3)
        self.assertAlmostEqual(shots[2].distances[-1] / shots[2].distances[0], 1.25, places=3)

    def test_a_quick_change_of_lens_inside_a_shot_is_a_cut(self):
        # the lens changes from 5 to 30 in 4 frames (40 -> 44, as 3018 -> 3022 of the distributed camera at 100.6 s): the
        # cut comes where the change starts, and the new shot holds where the change lands until it gets there; the frames
        # of the change are no part of the shot before (kept there, they came in on her for 0.1 s, 300 -> 166 units at a
        # field of 5, just before the cut: review camera-v2)
        keys = [tkey(0, (0, 12, 0), 300, (0, 0, 0), 5), tkey(40, (0, 12, 0), 300, (0, 0, 0), 5),
                tkey(44, (0, 60, 0), 150, (-20, 0, 0), 30), tkey(99, (0, 50, 0), 400, (-7, 0, 0), 30)]
        shots = oc.read_trace(vmd.Motion.for_camera(cameras=keys), 99)
        self.assertEqual([(s.start, s.end) for s in shots], [(0, 40), (41, 99)])
        self.assertEqual(shots[1].fov, 30)
        landed = fk.camera_at(fk.camera_keys(vmd.Motion.for_camera(cameras=keys)), 44)
        for i in range(4):                                     # frames 41-44: the landing, held
            self.assertAlmostEqual(shots[1].distances[i], landed.distance, places=6)
            self.assertAlmostEqual(shots[1].yaws[i], landed.angles[1], places=6)
            self.assertAlmostEqual(shots[1].states[i].fov, 30.0, places=6)
        self.assertTrue(all(abs(d - 300.0) < 1e-6 for d in shots[0].distances))   # the shot before stays as it was

    def test_the_trace_is_framed_again_for_this_scene(self):
        dancer = standing(300, sway=lambda f: (3.0 * math.sin(2 * math.pi * f / 200.0), 0.0))
        shots = oc.plan_trace(oc.read_trace(live_trace(), 299), dancer, trace_song())
        self.assertEqual([(s.start, s.end) for s in shots], [(0, 59), (60, 119), (120, 179), (180, 239), (240, 299)])
        self.assertEqual([s.fov for s in shots], [30, 5, 5, 30, 5])
        # the tiny wide view becomes a long shot of her; the long lens keeps the human's size
        self.assertEqual(shots[0].size, "long")
        self.assertEqual(shots[1].size, "full")
        frames, cuts = oc.make_path(dancer, shots)
        self.assertEqual(cuts, [0, 60, 120, 180, 240])
        for f, cam in enumerate(frames):
            self.assertGreaterEqual(cam.position[1], max(oc.LOWEST, dancer.at("hips", f)[1] + oc.HIP_MARGIN) - 1e-6, f)
            s = oc.seen(dancer, f, cam)
            self.assertLess(abs(s["eyes_u"]), ASPECT_EDGE, f)
            self.assertLess(abs(s["eyes_v"]), 1.0, f)
        first = oc.seen(dancer, 0, frames[0])
        self.assertGreaterEqual(first["body_share"], 0.3)
        # the pull out and the turn round her are kept
        d = [math.hypot(c.position[0] - dancer.at("eyes", 120 + i)[0], c.position[2]) for i, c in enumerate(frames[120:180])]
        self.assertAlmostEqual(d[-1] / d[0], 1.25, delta=0.03)
        self.assertAlmostEqual(frames[239].yaw - frames[180].yaw, 40.0, delta=4.0)
        # from behind stays behind
        self.assertGreater(frames[260].position[2], 0.0)

    def test_a_traced_zoom_in_keeps_her_head_in_the_picture(self):
        # the trace comes in to half its distance during a full shot (as 2809-2921 of the distributed camera): the
        # picture tightens from the bottom and her head top keeps its row
        dancer = standing(120)
        shot = oc.Shot(0, 119, "full", 0.0, 5, reach_path=[1.0 - 0.5 * i / 119.0 for i in range(120)], source="trace")
        frames = oc.shoot(dancer, shot)
        rows = [oc.seen(dancer, f, c)["headtop_v"] for f, c in enumerate(frames)]
        self.assertLess(max(rows), 1.0)
        self.assertLess(max(rows) - min(rows), 0.05)
        last = oc.seen(dancer, 119, frames[-1])
        self.assertLess(last["visible"], 1.0)                    # the feet have gone out at the bottom

    def test_a_close_shot_from_a_traced_high_view_is_not_steep(self):
        # the trace stands 35 units up (looking at the roof of the hall, as 3693-3720 of the distributed camera), and a
        # cut made clear turned the shot into a waist shot: it is taken from no higher than HIGH_RISE above her head
        dancer = standing(60, sway=lambda f: (0.0, -0.05 * f))
        for size in ("waist", "chest", "face"):
            shot = oc.Shot(0, 59, size, 0.0, 30, height=35.0, reach_path=[1.0] * 60, source="trace")
            frames = oc.shoot(dancer, shot)
            self.assertLessEqual(frames[0].position[1], REST["headtop"] + oc.HIGH_RISE[size] + 1e-6, size)
            for f, c in enumerate(frames):
                self.assertLess(abs(oc.seen(dancer, f, c)["eyes_v"]), 1.0, (size, f))

    def test_a_traced_shot_that_would_lose_her_eyes_takes_a_wider_size(self):
        # she sinks 4 units for the second half of a long-lens face shot (as at 157.5 s): her eyes would leave the
        # bottom of the picture; the shot takes the nearest size that keeps them in and still cuts clearly
        dancer = standing(120, jump=lambda f: -4.0 if f >= 90 else 0.0)
        shots = [oc.Shot(0, 59, "full", 0.0, 5, reach_path=[1.0] * 60, source="trace"),
                 oc.Shot(60, 119, "face", 0.0, 5, reach_path=[1.0] * 60, source="trace")]
        self.assertGreater(oc.eyes_out_share(dancer, shots[1], oc.shoot(dancer, shots[1])), oc.EYES_OUT)
        fixed = oc.ensure_clear_on_frames(list(shots), dancer)
        self.assertNotEqual(fixed[1].size, "face")
        self.assertLessEqual(oc.eyes_out_share(dancer, fixed[1], oc.shoot(dancer, fixed[1])), oc.EYES_OUT)
        self.assertTrue(oc.clear_on_frames(dancer, 60, oc.shoot(dancer, fixed[0])[-1], oc.shoot(dancer, fixed[1])[0]))

    def test_a_long_lens_trace_shot_is_never_a_long_shot(self):
        # from 550 units away a long lens frames her small, and sees past the near edge of the stage's floor below her
        # (a dark band at the bottom of the picture: the floor floats); through a long lens she is framed full instead
        keys = [tkey(0, (0, 26, 0), 550, (0, 0, 0), 5), tkey(59, (0, 26, 0), 550, (0, 0, 0), 5)]
        trace = oc.read_trace(vmd.Motion.for_camera(cameras=keys), 59)
        shots = oc.plan_trace(trace, standing(60), oc.Music(0.0, 0.5, 4, 59, [(0, "A", "verse")]))
        self.assertEqual(shots[0].size, "full")
        self.assertNotIn("long", oc.lens_sizes(5))
        dancer = standing(120)
        pair = [oc.Shot(0, 59, "full", 0.0, 30, reach_path=[1.0] * 60, source="trace"),
                oc.Shot(60, 119, "full", 0.0, 5, reach_path=[1.0] * 60, source="trace")]
        self.assertNotEqual(oc.ensure_clear_on_frames(oc.ensure_clear_cuts(list(pair)), dancer)[1].size, "long")

    def test_a_wide_lens_trace_shot_is_never_made_closer_than_knee(self):
        # making a cut clear may change a traced shot's size, never into a close size through the trace's wide lens
        dancer = standing(120)
        shots = [oc.Shot(0, 59, "knee", 0.0, 5, reach_path=[1.0] * 60, source="trace"),
                 oc.Shot(60, 119, "knee", 0.0, 30, reach_path=[1.0] * 60, source="trace")]
        fixed = oc.ensure_clear_on_frames(oc.ensure_clear_cuts(list(shots)), dancer)
        self.assertIn(fixed[1].size, ("long", "full", "knee"))
        self.assertTrue(oc.clear_on_frames(dancer, 60, oc.shoot(dancer, fixed[0])[-1], oc.shoot(dancer, fixed[1])[0]))

    def test_a_cut_the_frames_show_too_small_is_made_clear(self):
        # the first shot pulls out (as a traced zoom does) until its end is nearly the size of the next one: planned
        # as waist and knee (1.59 apart) the frames around the cut differ by less than 1.5; the next shot changes size
        dancer = standing(120)
        first = oc.Shot(0, 59, "waist", 0.0, 5, reach_path=[1.0 + 0.4 * i / 59.0 for i in range(60)], source="trace")
        second = oc.Shot(60, 119, "knee", 0.0, 5, reach_path=[1.0] * 60, source="trace")
        before = oc.shoot(dancer, first)[-1]
        self.assertFalse(oc.clear_on_frames(dancer, 60, before, oc.shoot(dancer, second)[0]))
        fixed = oc.ensure_clear_on_frames([first, second], dancer)
        self.assertNotEqual(fixed[1].size, "knee")
        self.assertEqual(fixed[1].fov, 5)                       # the trace's lens is kept
        self.assertTrue(oc.clear_on_frames(dancer, 60, oc.shoot(dancer, fixed[0])[-1], oc.shoot(dancer, fixed[1])[0]))

    def test_close_ups_take_a_share_of_the_calm_long_lens_shots(self):
        keys, f = [], 0
        for i in range(20):                     # 20 shots of 45 frames: long lens and wide view in turn
            if i % 2 == 0:
                keys += [tkey(f, (0, 12, 0), 325, (0, 0, 0), 5), tkey(f + 44, (0, 12, 0), 325, (0, 0, 0), 5)]
            else:
                keys += [tkey(f, (0, 40, 0), 300, (-6, 0, 0), 30), tkey(f + 44, (0, 40, 0), 300, (-6, 0, 0), 30)]
            f += 45
        music = oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=899, sections=[(0, "A", "verse")],
                         lines=[(45 * i + 10) / 30.0 for i in range(0, 20, 2)], hooks=[])
        dancer = calm(900)
        trace = oc.read_trace(vmd.Motion.for_camera(cameras=keys), 899)
        plain = oc.plan_trace(trace, dancer, music)
        close = oc.plan_trace(trace, dancer, music, close_ups=0.3)
        def share(shots):
            return sum(s.end - s.start + 1 for s in shots if s.size in ("chest", "face")) / 900.0
        self.assertLess(share(plain), 0.05)
        self.assertGreaterEqual(share(close), 0.3)
        self.assertLess(share(close), 0.45)
        for a, b in zip(close, close[1:]):
            self.assertFalse(a.size in ("chest", "face") and b.size in ("chest", "face"), (a.start, b.start))
            turn = abs(((b.yaw - a.yaw) + 180.0) % 360.0 - 180.0)
            self.assertTrue(oc.size_ratio(a.size, b.size) >= 1.5 or turn >= 30.0, (a.start, a.size, b.size))
        for s in close:
            if s.size in ("chest", "face"):
                self.assertEqual(s.fov, 5)
                self.assertEqual(s.source, "close_up")
        # a calm shot that ends with her head moving fast (its last 3 frames, 1 unit: still calm by the 90 % point of the
        # shot, and her eyes stay in the picture) is not made close: the traced cut cannot come onto the move, and the
        # close shot would end on a blurred face.  Asked for more than the long-lens shots hold, all the others are
        every = oc.plan_trace(trace, dancer, music, close_ups=0.6)
        self.assertTrue(all(s.size in ("chest", "face") for s in every[0::2]), [(s.start, s.size) for s in every])
        moving = standing(900, sway=lambda f: (0.4 * math.sin(2 * math.pi * f / 90.0), 0.0),
                          lean=lambda f: 1.0 * min(1.0, max(0.0, (f - 41) / 3.0)))
        self.assertTrue(oc.Moments(moving).of(0, 44)["calm"])
        shots = oc.plan_trace(trace, moving, music, close_ups=0.6)
        self.assertNotIn(shots[0].size, ("chest", "face"))
        self.assertTrue(all(s.size in ("chest", "face") for s in shots[2::2]), [(s.start, s.size) for s in shots])


class GuardTest(unittest.TestCase):
    """guard: another camera (the current one, make_camera's) tilted down about its own look-at point where it would look
    at her hips or either hip joint from too low (4.5 degrees, 15 while she spins fast, and what a window asks), keeping
    the look-at point, the distance, the heading and the lens, rising and settling at a gentle pace, never across a cut"""

    SPIN = set(range(31, 80))           # her shoulders turn 600 deg/s over 40-70: the spin and 9 frames (0.3 s) each way

    def setUp(self):
        self.dancer = standing(120, turn=lambda f: 20.0 * min(30.0, max(0.0, f - 40.0)))   # 600 deg/s over 40-70
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)                  # level at her hips, 200 off
        high = oc.place_camera((0.0, REST["chest"], 0.0), 60.0, 25.0, 40.0)                # 25 degrees down, from the side
        frames = [oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0) for _ in range(60)] + \
                 [oc.CameraFrame(high, 60.0, 25.0, 0.0, 30, 40.0) for _ in range(60)]
        self.keys = fk.camera_keys(oc.camera_motion(frames, [0, 60]))
        self.before = frames

    def test_the_low_shot_is_tilted_down_about_its_look_at_point_as_far_as_it_must(self):
        frames, cuts, tilts = oc.guard_camera(self.dancer, self.keys, 119)
        self.assertEqual(cuts, [60])
        for f, cam in enumerate(frames):
            old = self.before[f]
            # the look-at point, the distance, the heading and the lens stay: the camera only swings up round the point
            self.assertLess(math.dist(look_at_of(cam), look_at_of(old)), 1e-6, f)
            self.assertAlmostEqual(cam.reach, old.reach, places=6)
            self.assertAlmostEqual(cam.yaw, old.yaw, places=6)
            self.assertEqual(cam.fov, old.fov)
            self.assertAlmostEqual(cam.pitch, old.pitch + tilts[f], places=6)
            self.assertGreaterEqual(tilts[f], 0.0)
            # the requester's rule in its own numbers: 4.5 degrees, 15 while she spins fast
            need = 15.0 if f in self.SPIN else 4.5
            self.assertGreaterEqual(look_down_at_her_hips(self.dancer, f, cam.position), need - 1e-6, f)
        # the tilt is not overdone: away from the spin the low shot looks down by less than 10 degrees
        self.assertLess(look_down_at_her_hips(self.dancer, 0, frames[0].position), 10.0)

    def test_the_high_shot_stays_as_it_was_and_the_tilt_rises_and_settles_gently(self):
        frames, cuts, tilts = oc.guard_camera(self.dancer, self.keys, 119)
        for f in range(60, 120):
            self.assertEqual(tilts[f], 0.0, f)
            self.assertLess(math.dist(frames[f].position, self.before[f].position), 1e-9, f)
        low = tilts[:60]
        self.assertGreater(max(low), 10.0)
        steps = [abs(b - a) for a, b in zip(low, low[1:])]
        # no faster than 20 degrees a second (two thirds of a degree a frame), and eased: the pace changes by at most half
        # of its top from one frame to the next (a rise without easing changes it by all of it at once)
        self.assertLessEqual(max(steps), 20.0 / 30.0 + 1e-9)
        bends = [abs(c - 2.0 * b + a) for a, b, c in zip(low, low[1:], low[2:])]
        self.assertLessEqual(max(bends), 0.5 * max(steps))

    def test_the_far_hip_joint_counts_as_well_as_the_hips_between_them(self):
        # she stands sideways (her left hip joint 0.9 further away) before a camera 10 off that looks down at the point
        # between her hip joints by 4.6 degrees: the far joint is seen from 4.2 and the camera must tilt for it
        dancer = standing(60, turn=lambda f: 90.0)
        hips = dancer.at("hips", 0)
        place = oc.place_camera(hips, 0.0, 4.6, 10.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(place, 0.0, 4.6, 0.0, 30, 10.0)] * 60, [0]))
        far = dancer.at("lhip", 0)
        self.assertLess(math.degrees(math.atan2(place[1] - far[1], math.hypot(place[0] - far[0], place[2] - far[2]))), 4.5)
        frames, _, tilts = oc.guard_camera(dancer, keys, 59)
        self.assertGreater(min(tilts), 0.0)
        for f, cam in enumerate(frames):
            self.assertGreaterEqual(look_down_at_her_hips(dancer, f, cam.position), 4.5 - 1e-6, f)

    def test_a_fast_turn_of_the_lower_body_alone_is_guarded_like_one_of_the_shoulders(self):
        # her shoulders stay, her lower body turns 400 deg/s over frames 40-46: frames 35-51 (5 before, 6 after the frames
        # it turns from) need 15 degrees, the rest 4.5
        dancer = standing(100, pelvis=lambda f: 400.0 / 30.0 * min(6.0, max(0.0, f - 40.0)))
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 100, [0]))
        frames, _, tilts = oc.guard_camera(dancer, keys, 99)
        for f, cam in enumerate(frames):
            need = 15.0 if 35 <= f <= 51 else 4.5
            self.assertGreaterEqual(look_down_at_her_hips(dancer, f, cam.position), need - 1e-6, f)
        self.assertLess(look_down_at_her_hips(dancer, 0, frames[0].position), 10.0)

    def test_a_fast_turn_of_the_shoulders_alone_is_guarded(self):
        # her lower body stays, her shoulders turn 600 deg/s over 40-70: frames 31-79 need 15 degrees
        dancer = standing(100, turn=lambda f: 20.0 * min(30.0, max(0.0, f - 40.0)), pelvis=lambda f: 0.0)
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 100, [0]))
        frames, _, _ = oc.guard_camera(dancer, keys, 99)
        for f in range(31, 80):
            self.assertGreaterEqual(look_down_at_her_hips(dancer, f, frames[f].position), 15.0 - 1e-6, f)

    def test_the_camera_stays_up_between_two_spins_close_together(self):
        # two spins a second apart (600 deg/s over 20-30 and 70-80): the tilt does not bob down between them
        def turn(f):
            return 20.0 * (min(10.0, max(0.0, f - 20.0)) + min(10.0, max(0.0, f - 70.0)))
        dancer = standing(140, turn=turn)
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 140, [0]))
        _, _, tilts = oc.guard_camera(dancer, keys, 139)
        first, second = max(tilts[11:40]), max(tilts[61:90])
        self.assertGreaterEqual(min(tilts[25:76]), min(first, second) - 1e-6)

    def test_the_tilt_does_not_bob_between_two_spins_four_seconds_apart(self):
        # two spins (600 deg/s over 20-30 and 140-150): between them the tilt either stays up or goes down once and comes
        # back once; it does not rise again in the middle of the gap (a comb: up, down, up, down, up)
        def turn(f):
            return 20.0 * (min(10.0, max(0.0, f - 20.0)) + min(10.0, max(0.0, f - 140.0)))
        dancer = standing(200, turn=turn)
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 200, [0]))
        _, _, tilts = oc.guard_camera(dancer, keys, 199)
        gap = tilts[30:141]
        falls_after_rise = any(gap[j + 1] < gap[j] - 1e-6 for i in range(len(gap) - 1) if gap[i + 1] > gap[i] + 1e-6
                               for j in range(i + 1, len(gap) - 1))
        self.assertFalse(falls_after_rise, [round(v, 2) for v in gap])

    def test_a_frame_the_first_tilt_leaves_short_is_tilted_further(self):
        # (the look-down grows with the tilt for these cameras; should a profile fall short on some frame, the guard asks
        # that frame for more instead of writing it short)
        real = oc.guard_profile
        calls = []

        def short_once(asked, bounds):
            out = real(asked, bounds)
            calls.append(1)
            return [t * 0.5 for t in out] if len(calls) == 1 else out
        oc.guard_profile = short_once
        try:
            frames, _, _ = oc.guard_camera(self.dancer, self.keys, 119)
        finally:
            oc.guard_profile = real
        self.assertGreaterEqual(len(calls), 2)
        for f, cam in enumerate(frames):
            need = 15.0 if f in self.SPIN else 4.5
            self.assertGreaterEqual(look_down_at_her_hips(self.dancer, f, cam.position), need - 1e-6, f)

    def test_a_window_asks_for_its_own_look_down(self):
        frames, _, tilts = oc.guard_camera(self.dancer, self.keys, 119, windows=[(10, 15, 30.0)])
        for f in range(10, 16):
            self.assertGreaterEqual(look_down_at_her_hips(self.dancer, f, frames[f].position), 30.0 - 1e-6, f)
        # outside the window the rule is as before (and the window does not reach across the cut)
        self.assertLess(look_down_at_her_hips(self.dancer, 0, frames[0].position), 30.0)
        for f in range(60, 120):
            self.assertEqual(tilts[f], 0.0, f)

    def test_a_window_never_lowers_what_a_spin_needs(self):
        # a window asking less than the spin (10 degrees over the spin's frames of the low shot) leaves the spin's 15
        frames, _, _ = oc.guard_camera(self.dancer, self.keys, 119, windows=[(31, 59, 10.0)])
        for f in range(31, 60):
            self.assertGreaterEqual(look_down_at_her_hips(self.dancer, f, frames[f].position), 15.0 - 1e-6, f)

    def test_the_camera_is_up_before_the_spin_and_stays_up_after_it(self):
        # the tilt a spin needs is held beyond its frames, so the camera is already up on the frames just before the
        # first that needs it (the skirt starts to lift before the turn is counted fast) and still up just after the last
        dancer = standing(140, turn=lambda f: 20.0 * min(30.0, max(0.0, f - 50.0)))       # 600 deg/s over 50-80: 42-88 need 15
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 140, [0]))
        frames, _, _ = oc.guard_camera(dancer, keys, 139)
        for f in (38, 39, 40, 90, 91, 92):
            self.assertGreaterEqual(look_down_at_her_hips(dancer, f, frames[f].position), 15.0 - 1e-6, f)

    def test_a_small_tilt_rises_over_half_a_second_not_at_once(self):
        # a camera that already looks down 14.5 degrees needs half a degree more for the spin (frames 31-59 of the
        # shot): that half degree is not jerked in over a few frames, it rises over GUARD_RAMP frames (half a second)
        hips = (0.0, REST["hips"], 0.0)
        place = oc.place_camera(hips, 0.0, 14.5, 40.0)
        frames_in = [oc.CameraFrame(place, 0.0, 14.5, 0.0, 30, 40.0)] * 60 + list(self.before[60:])
        keys = fk.camera_keys(oc.camera_motion(frames_in, [0, 60]))
        frames, _, tilts = oc.guard_camera(self.dancer, keys, 119)
        top = max(tilts[31:60])
        self.assertGreater(top, 0.2)
        self.assertLess(top, 2.0)
        # the rise has begun 16 frames before the first frame that needs it, and is not yet half way 10 frames before
        self.assertGreater(tilts[15], 0.0)
        self.assertLess(tilts[21], 0.5 * top)
        self.assertEqual(tilts[0], 0.0)

    def test_a_look_down_no_tilt_can_give_is_refused_not_rounded_away(self):
        with self.assertRaises(ValueError):
            oc.guard_camera(self.dancer, self.keys, 119, windows=[(10, 15, 89.0)])

    def test_every_subframe_of_a_frame_looks_down_as_far_as_the_frame_must(self):
        # MMD keeps the camera of a frame (a key on every frame) over the frame's subframes (16 at 480 fps) while her body
        # moves on: she walks away from the camera, half a unit a frame, through a window (frames 10-15, 30 degrees).
        # Every subframe f + k/16 of the window's frames is looked down at by 30 degrees from the camera of frame f (her
        # body straight between its frames: a dancer given per frame tells no more)
        dancer = standing(60, sway=lambda f: (0.0, 0.5 * min(max(f - 5, 0), 20)))
        place = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 40.0)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(place, 0.0, 0.0, 0.0, 30, 40.0)] * 60, [0]))
        frames, _, _ = oc.guard_camera(dancer, keys, 59, windows=[(10, 15, 30.0)])
        for f in range(10, 16):
            for k in range(16):
                points = [between_frames(dancer, name, f, k) for name in ("hips", "lhip", "rhip")]
                self.assertGreaterEqual(look_down_at_points(frames[f].position, points), 30.0 - 1e-6, (f, k))
        # and the rule of 4.5 degrees holds over the subframes of every other frame
        for f in range(59):
            points = [between_frames(dancer, name, f, k) for name in ("hips", "lhip", "rhip") for k in range(16)]
            self.assertGreaterEqual(look_down_at_points(frames[f].position, points), 4.5 - 1e-6, f)

    def test_a_dance_read_with_subframes_gives_her_hips_where_the_dance_puts_them_between_frames(self):
        # (the dance's own curves at f + k/16, not a straight line between frames: her lower body turns 90 degrees over
        # frames 0-30, so her hip joints go round between the frames)
        import tempfile
        import shutil
        from mmd_cli.formats import pmx
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "rin.pmx")
        with open(path, "wb") as f:
            f.write(rin_like_model())
        model = pmx.load(path)
        turn = (0.0, math.sin(math.radians(45.0)), 0.0, math.cos(math.radians(45.0)))
        motion = vmd.Motion(model_name="dancer", bones=[vmd.BoneKey("下半身", 0, (0.0, 0.0, 0.0), fk.IDENTITY),
                                                        vmd.BoneKey("下半身", 30, (0.0, 0.0, 0.0), turn)])
        dancer = oc.dancer_from_motion(model, motion, 40, hip_joints=True, subframes=16)
        pose = fk.Pose(model, motion, ["下半身", "左足", "右足"])
        for f in (3, 17, 29):
            got = {name: dancer.over(name, f) for name in ("hips", "lhip", "rhip")}
            self.assertEqual(len(got["lhip"]), 16)
            for k in (0, 5, 8, 15):
                w = pose.at(f + k / 16.0)
                low = w["下半身"][0]
                want = {"hips": (low[0], low[1] - oc.HIPS_BELOW_WAIST, low[2]), "lhip": w["左足"][0], "rhip": w["右足"][0]}
                for name in want:
                    for a, b in zip(got[name][k], want[name]):
                        self.assertAlmostEqual(a, b, places=9, msg=(f, k, name))
        # (at mid frame the turning hip joint is off the straight line between the frames: the straight line is not used)
        mid = dancer.over("lhip", 17)[8]
        line = between_frames(dancer, "lhip", 17, 8)
        self.assertGreater(math.dist(mid, line), 1e-5)

    def lifted_shot(self, look_at, pitch, reach, window=(90, 110, 35.0)):
        dancer = standing(200)
        place = oc.place_camera(look_at, 0.0, pitch, reach)
        keys = fk.camera_keys(oc.camera_motion([oc.CameraFrame(place, 0.0, pitch, 0.0, 30, reach)] * 200, [0]))
        frames, cuts, tilts = oc.guard_camera(dancer, keys, 199, [window])
        _, _, base = oc.guard_camera(dancer, keys, 199)
        lifted, lifts, runs = oc.lift_aim(dancer, frames, tilts, base, cuts, [window])
        return dancer, frames, tilts, base, lifted, lifts, runs

    def test_a_lifted_aim_keeps_the_eye_and_her_knees_and_gives_back_part_of_the_windows_tilt(self):
        # a camera from the front, 5 degrees down at her chest from 70 off; a window (frames 90-110) asks 35 degrees, so
        # guard swings it up round its look-at point and the picture looks down onto the street.  Lifting the aim turns
        # the camera back up from where the window put it: the eye stays (the same look-down at her hips on every frame),
        # her knees stay in the picture LIFT_ROOM above its bottom edge, and it never looks higher than the camera would
        # without the window
        dancer, frames, tilts, base, lifted, lifts, runs = self.lifted_shot((0.0, REST["chest"], 0.0), 5.0, 70.0)
        self.assertGreater(max(lifts), 2.0)
        self.assertEqual(len(runs), 1)
        least_room = 9.0
        for f, (a, b) in enumerate(zip(frames, lifted)):
            self.assertLess(math.dist(a.position, b.position), 1e-9, f)
            self.assertAlmostEqual(a.reach, b.reach, places=9)
            self.assertAlmostEqual(a.yaw, b.yaw, places=9)
            self.assertEqual(a.fov, b.fov)
            self.assertAlmostEqual(b.pitch, a.pitch - lifts[f], places=9)
            self.assertGreaterEqual(lifts[f], 0.0, f)
            self.assertLessEqual(lifts[f], tilts[f] - base[f] + 1e-9, f)
            for knee in knees_of(dancer, f):
                u, v, depth = oc.project(b.position, b.yaw, b.pitch, b.roll, b.fov, knee)
                self.assertGreater(depth, 0.0)
                self.assertGreaterEqual(v, -1.0 + oc.LIFT_ROOM - 1e-9, f)
                if lifts[f] > 0.0:
                    least_room = min(least_room, v - (-1.0 + oc.LIFT_ROOM))
        # as far as the knees let it (a knee comes to the edge of the room), not all of the window's tilt
        self.assertLess(least_room, 1e-3)
        self.assertLess(runs[0]["share"], 1.0)
        # only the window's run is lifted (the frames the window adds no tilt to stay as guard made them), and the view
        # turns no faster than guard's tilt may (20 degrees a second)
        untouched = [f for f in range(200) if tilts[f] - base[f] <= 0.0]
        self.assertGreater(len(untouched), 10)
        for f in untouched:
            self.assertEqual(lifted[f], frames[f], f)
        pitches = [c.pitch for c in lifted]
        self.assertLessEqual(max(abs(q - p) for p, q in zip(pitches, pitches[1:])), 20.0 / 30.0 + 1e-9)

    def test_no_lift_when_her_knees_have_no_room_under_them(self):
        # a camera close on her eyes: her knees are at the bottom edge or out of the picture through the window's run, so
        # the aim is not lifted at all
        dancer, frames, tilts, base, lifted, lifts, runs = self.lifted_shot((0.0, REST["eyes"], 0.0), 0.0, 30.0)
        self.assertGreater(max(t - b for t, b in zip(tilts, base)), 5.0)
        self.assertEqual(max(lifts), 0.0)
        self.assertEqual(lifted, frames)
        self.assertEqual([r["share"] for r in runs], [0.0])

    def test_without_a_window_nothing_is_lifted(self):
        frames, cuts, tilts = oc.guard_camera(self.dancer, self.keys, 119)
        lifted, lifts, runs = oc.lift_aim(self.dancer, frames, tilts, tilts, cuts, [])
        self.assertEqual(lifted, frames)
        self.assertEqual(max(lifts), 0.0)
        self.assertEqual(runs, [])

    def test_the_command_writes_a_key_on_every_frame_with_the_step_on_the_cuts(self):
        import contextlib
        import io
        import json
        import shutil
        import tempfile
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model, dance = os.path.join(folder, "rin.pmx"), os.path.join(folder, "dance.vmd")
        with open(model, "wb") as f:
            f.write(rin_like_model())
        with open(dance, "wb") as f:
            f.write(vmd.dumps(walking_dance(119)))
        camera, out, report = (os.path.join(folder, n) for n in ("cam.vmd", "guarded.vmd", "r.json"))
        with open(camera, "wb") as f:
            f.write(vmd.dumps(oc.camera_motion(self.before, [0, 60])))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = oc.main(["guard", dance, model, camera, out, "--report", report, "--window", "10", "15", "30"])
        self.assertEqual(code, 0, buf.getvalue())
        keys = sorted(vmd.load(out).cameras, key=lambda k: k.frame)
        self.assertEqual([k.frame for k in keys], list(range(120)))
        steps = [k.frame for k in keys if tuple(vmd.camera_curves(k.interpolation)["distance"]) == oc.CUT_CURVE]
        self.assertEqual(steps, [0, 60])
        with open(report, encoding="ascii") as f:
            data = json.load(f)
        self.assertEqual(data["after"]["short_frames"], 0)
        self.assertGreater(data["before"]["short_frames"], 0)
        self.assertEqual(data["windows"], [[10, 15, 30.0]])
        self.assertGreaterEqual(data["after"]["windows"][0]["min"], 30.0 - 1e-6)
        self.assertLess(data["before"]["windows"][0]["min"], 30.0)
        # the table of what was changed: every tilted frame is in one of its spans, and each span says how far
        tilted = set()
        for span in data["spans"]:
            a, b = span["frames"]
            tilted.update(range(a, b + 1))
            for key in ("seconds", "tilt_max", "rise_max", "moved_max", "look_down_min_before", "look_down_min_after"):
                self.assertIn(key, span)
        self.assertEqual(len(tilted), data["frames_tilted"])
        self.assertTrue(set(range(0, 60)) & tilted)
        self.assertFalse(set(range(60, 120)) & tilted)
        # the written file reads back to the same cameras: the look-at points and distances of the input
        back = fk.camera_keys(vmd.load(out))
        for f in (0, 30, 59, 60, 119):
            got, was = fk.camera_at(back, f), fk.camera_at(self.keys, f)
            self.assertLess(math.dist(got.look_at, was.look_at), 1e-4, f)
            self.assertAlmostEqual(got.distance, was.distance, places=4)
        # the same file as input and output, or a window that is not one, is refused, and nothing is written
        for bad in ([camera], [out + "2", "--window", "15", "10", "30"], [out + "2", "--window", "10", "15", "90"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = oc.main(["guard", dance, model, camera] + bad)
            self.assertEqual(code, 2, bad)
        self.assertFalse(os.path.exists(out + "2"))
        # --lift-aim: the same eye on every frame (the written look-at points move, the cameras stay), the report says
        # how far each window's run was lifted and the lift of every frame
        lifted, report2 = os.path.join(folder, "lifted.vmd"), os.path.join(folder, "r2.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = oc.main(["guard", dance, model, camera, lifted, "--report", report2, "--window", "10", "15", "30",
                            "--lift-aim"])
        self.assertEqual(code, 0, buf.getvalue())
        with open(report2, encoding="ascii") as f:
            data2 = json.load(f)
        self.assertEqual(data2["after"]["short_frames"], 0)
        self.assertEqual(len(data2["per_frame"]["lift"]), 120)
        for run in data2["lifts"]:
            for key in ("frames", "share", "lift_max", "top_edge_max_before", "top_edge_max_after"):
                self.assertIn(key, run)
        a_keys, b_keys = fk.camera_keys(vmd.load(out)), fk.camera_keys(vmd.load(lifted))
        for f in range(120):
            self.assertLess(math.dist(fk.camera_position(fk.camera_at(a_keys, f)), fk.camera_position(fk.camera_at(b_keys, f))),
                            1e-3, f)


def rin_like_model():
    """the bones the camera reads, laid out as on Sour's Rin at rest"""
    from tests.test_pmx import NORMAL, TRANSLATE, Writer
    w = Writer(bone=2)
    bones = [("全ての親", -1, (0.0, 0.0, 0.0), NORMAL | TRANSLATE), ("センター", 0, (0.0, 7.85, 0.0), NORMAL | TRANSLATE),
             ("上半身", 1, (0.0, 12.23, -0.65), NORMAL), ("上半身2", 2, (0.0, 13.8, -0.68), NORMAL),
             ("首", 3, (0.0, 15.65, -0.13), NORMAL), ("頭", 4, (0.0, 16.24, 0.0), NORMAL),
             ("左目", 5, (0.41, 17.21, -0.56), NORMAL), ("右目", 5, (-0.41, 17.21, -0.56), NORMAL),
             ("下半身", 1, (0.0, 12.23, -0.65), NORMAL), ("左腕", 3, (0.91, 15.28, -0.25), NORMAL),
             ("右腕", 3, (-0.91, 15.28, -0.25), NORMAL), ("左つま先ＩＫ", 0, (1.05, 0.1, -1.15), NORMAL | TRANSLATE),
             ("右つま先ＩＫ", 0, (-1.05, 0.1, -1.15), NORMAL | TRANSLATE), ("左足", 8, (0.90, 10.66, 0.007), NORMAL),
             ("右足", 8, (-0.90, 10.59, 0.007), NORMAL)]
    return w.build(name="rin-like", bones=[w.bone(n, parent=p, position=pos, flags=fl) for n, p, pos, fl in bones])


def walking_dance(last):
    """the center walks 4 units to the side and back over the dance"""
    keys = [vmd.BoneKey("センター", f, (4.0 * math.sin(2 * math.pi * f / float(last)), 0.0, 0.0), fk.IDENTITY)
            for f in range(0, last + 1, 30)]
    return vmd.Motion(model_name="dancer", bones=keys)


class CommandTest(unittest.TestCase):
    def setUp(self):
        import json
        import shutil
        import tempfile
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.model = os.path.join(self.folder, "rin.pmx")
        with open(self.model, "wb") as f:
            f.write(rin_like_model())
        self.dance = os.path.join(self.folder, "dance.vmd")
        with open(self.dance, "wb") as f:
            f.write(vmd.dumps(walking_dance(899)))
        self.music = os.path.join(self.folder, "music.json")
        with open(self.music, "w", encoding="utf-8") as f:
            json.dump({"first_beat": 0.0, "period": 0.5, "beats_per_bar": 4, "last_frame": 899,
                       "sections": [[0, "intro", "intro"], [16, "A", "verse"], [32, "chorus", "chorus"], [48, "outro", "outro"]],
                       "lines": [9.0, 17.0], "hooks": []}, f)
        self.trace = os.path.join(self.folder, "live.vmd")
        with open(self.trace, "wb") as f:
            f.write(vmd.dumps(live_trace()))

    def run_main(self, argv):
        import contextlib
        import io
        import json
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = oc.main(argv)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_music_writes_a_key_on_every_frame_and_a_report_mv_chunks_reads(self):
        import importlib.util as iu
        import json
        out, report = os.path.join(self.folder, "cam.vmd"), os.path.join(self.folder, "r.json")
        code, result = self.run_main(["music", self.dance, self.model, self.music, out, "--report", report])
        self.assertEqual(code, 0, result)
        keys = sorted(vmd.load(out).cameras, key=lambda k: k.frame)
        self.assertEqual([k.frame for k in keys], list(range(900)))
        with open(report, encoding="ascii") as f:
            data = json.load(f)
        spec = iu.spec_from_file_location("mv_chunks", os.path.join(ROOT, "tools", "mv_chunks.py"))
        mv_chunks = iu.module_from_spec(spec)
        spec.loader.exec_module(mv_chunks)
        spans = mv_chunks.spans_from_report(data)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], 899)
        self.assertEqual([s[0] for s in spans], [k.frame for k in keys if tuple(vmd.camera_curves(k.interpolation)["x"]) == oc.CUT_CURVE])
        m = data["measures"]
        for name in ("size_share", "eyes_in_picture", "camera_above_hips_min", "cuts_on_bar_lines", "jump_cuts",
                     "shot_seconds", "still_share", "follow_lag_s", "hips_look_down_min", "hips_look_down_low"):
            self.assertIn(name, m)
        # every shot says how far before its bar line it starts (0 unless a close shot before it was cut onto a move)
        self.assertTrue(all(s["early"] == 0 for s in data["shots"]), data["shots"])
        self.assertEqual(m["jump_cuts"], 0)
        self.assertEqual(m["cuts_on_bar_lines"], 1.0)
        self.assertGreaterEqual(m["camera_above_hips_min"], oc.HIP_MARGIN - 1e-6)
        self.assertAlmostEqual(sum(m["size_share"].values()), 1.0, places=3)     # each share is rounded to 4 places

    def test_the_same_input_gives_the_same_bytes(self):
        a, b = os.path.join(self.folder, "a.vmd"), os.path.join(self.folder, "b.vmd")
        self.assertEqual(self.run_main(["music", self.dance, self.model, self.music, a, "--seed", "3"])[0], 0)
        self.assertEqual(self.run_main(["music", self.dance, self.model, self.music, b, "--seed", "3"])[0], 0)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_trace_keeps_the_cuts_of_the_trace(self):
        out = os.path.join(self.folder, "t.vmd")
        code, result = self.run_main(["trace", self.dance, self.model, self.music, self.trace, out, "--last", "299"])
        self.assertEqual(code, 0, result)
        keys = sorted(vmd.load(out).cameras, key=lambda k: k.frame)
        cuts = [k.frame for k in keys if tuple(vmd.camera_curves(k.interpolation)["x"]) == oc.CUT_CURVE]
        self.assertEqual(cuts, [0, 60, 120, 180, 240])

    def test_errors_exit_2_and_write_nothing(self):
        out = os.path.join(self.folder, "x.vmd")
        for argv in (["music", self.dance, self.model, self.music, self.dance],          # over the dance
                     ["music", self.dance, self.model, os.path.join(self.folder, "none.json"), out],
                     ["trace", self.dance, self.model, self.music, self.trace, out, "--close-ups", "1.5"]):
            code, result = self.run_main(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(result["ok"])
        self.assertFalse(os.path.exists(out))
        self.assertEqual(vmd.load(self.dance).bones[0].name, "センター")


class MeasuresTest(unittest.TestCase):
    """the report backs the claims (no jump cut, the eyes always in the picture, never below the hips, every section head
    cut): each measure must see the fault it counts (review camera-v2: all four could be broken and no test fell)"""

    def setUp(self):
        self.music = oc.Music(first_beat=0.0, period=0.5, beats_per_bar=4, last_frame=239,
                              sections=[(0, "A", "verse"), (8, "B", "verse")], lines=[], hooks=[])     # B: frame 120
        self.dancer = standing(240)

    def path(self, shots):
        frames, _ = oc.make_path(self.dancer, shots)
        return frames

    def test_a_jump_cut_is_counted(self):
        # the same size from 5 degrees round: a jump cut at frame 120
        shots = [oc.Shot(0, 119, "waist", 0.0, 20), oc.Shot(120, 239, "waist", 5.0, 20)]
        m = oc.measures(self.dancer, self.music, shots, self.path(shots))
        self.assertEqual(m["jump_cuts"], 1)
        self.assertEqual([j["frame"] for j in m["jump_cut_list"]], [120])

    def test_eyes_out_of_the_picture_and_a_camera_under_the_hips_are_counted(self):
        shots = [oc.Shot(0, 119, "waist", 0.0, 20), oc.Shot(120, 239, "full", 40.0, 27)]
        away = self.path(shots)
        for f in range(30):                                   # looking away for 30 frames: the eyes leave the picture
            away[f] = dataclasses.replace(away[f], yaw=away[f].yaw + 90.0)
        self.assertAlmostEqual(oc.measures(self.dancer, self.music, shots, away)["eyes_in_picture"], 210 / 240.0, places=4)
        low = self.path(shots)
        p = low[200].position                                 # one frame half a unit under her hips
        low[200] = dataclasses.replace(low[200], position=(p[0], REST["hips"] - 0.5, p[2]))
        self.assertAlmostEqual(oc.measures(self.dancer, self.music, shots, low)["camera_above_hips_min"], -0.5, places=3)

    def test_a_camera_looking_level_at_her_hips_is_counted(self):
        # one frame seen from a long lens 200 units off at the height of her hips: the report's least look-down angle
        # over the frames that show her hips is about 0 and that frame is counted below the rule
        shots = [oc.Shot(0, 119, "waist", 0.0, 20), oc.Shot(120, 239, "full", 40.0, 27)]
        level = self.path(shots)
        clean = oc.measures(self.dancer, self.music, shots, level)
        self.assertGreaterEqual(clean["hips_look_down_min"], 4.5)
        self.assertEqual(clean["hips_look_down_low"], 0)
        hips = self.dancer.at("hips", 200)
        place = (hips[0], hips[1], hips[2] - 200.0)
        yaw, pitch = oc.aim(place, hips)
        level[200] = oc.CameraFrame(place, yaw, pitch, 0.0, 5, 200.0)
        m = oc.measures(self.dancer, self.music, shots, level)
        self.assertAlmostEqual(m["hips_look_down_min"], 0.0, delta=0.01)
        self.assertEqual(m["hips_look_down_low"], 1)

    def test_a_spin_seen_from_less_than_15_degrees_is_counted(self):
        # the path made for her standing still, measured on her spinning fast over frames 100-130: the frames of the spin
        # (and FLARE_HOLD around) that show her hips from less than 15 degrees are counted below the rule
        shots = [oc.Shot(0, 119, "waist", 0.0, 20), oc.Shot(120, 239, "full", 40.0, 27)]
        frames = self.path(shots)
        spin = standing(240, turn=lambda f: 20.0 * min(30.0, max(0.0, f - 100.0)))
        m = oc.measures(spin, self.music, shots, frames)
        flare = oc.flare_frames(spin)
        low = 0
        for f, cam in enumerate(frames):
            shown, angle, _ = oc.hips_look_down(spin, f, cam)
            low += shown and angle < (15.0 if flare[f] else 4.5) - 1e-6
        self.assertGreater(low, 0)
        self.assertEqual(m["hips_look_down_low"], low)
        self.assertEqual(m["flare_frames"], sum(flare))
        self.assertLess(m["hips_look_down_flare_min"], 15.0)

    def test_a_section_head_is_cut_only_within_a_beat(self):
        # the second section starts on frame 120 (beat 16); a cut two beats later does not cut its head
        shots = [oc.Shot(0, 149, "waist", 0.0, 20), oc.Shot(150, 239, "full", 40.0, 27)]
        m = oc.measures(self.dancer, self.music, shots, self.path(shots))
        self.assertEqual(m["section_heads_cut"], [0, 1])

    def test_a_line_with_its_end_is_sung_only_while_it_lasts(self):
        # a line from 7.5 to 8.4 s is sung 0.4 s into the shot 8-12 s: not a sung shot; its start alone would be taken to
        # last 2 s and make it one
        with_end = oc.Music(0.0, 0.5, 4, 479, [(0, "A", "verse")], lines=[(7.5, 8.4)])
        start_only = oc.Music(0.0, 0.5, 4, 479, [(0, "A", "verse")], lines=[7.5])
        self.assertFalse(with_end.sung(240, 359))
        self.assertTrue(start_only.sung(240, 359))


import dataclasses  # noqa: E402


class MotionTest(unittest.TestCase):
    def test_a_key_on_every_frame_and_a_step_on_every_cut(self):
        frames = [oc.CameraFrame((0.0, 15.0, -40.0 - f * 0.1), 0.0, 3.0, 0.0, 30, 40.0) for f in range(60)]
        motion = oc.camera_motion(frames, cuts=[0, 25])
        keys = sorted(motion.cameras, key=lambda k: k.frame)
        self.assertEqual([k.frame for k in keys], list(range(60)))
        for k in keys:
            curves = vmd.camera_curves(k.interpolation)
            expected = oc.CUT_CURVE if k.frame in (0, 25) else vmd.LINEAR_CURVE
            self.assertEqual(tuple(curves["distance"]), tuple(expected), k.frame)


SONG = os.environ.get("CAMERA_SONG")


def song_paths():
    """the MV's inputs named by CAMERA_SONG: a JSON {"dance", "model", "music", "trace"} (the dance the cameras are made
    for, its model, the song's MUSIC.json and the distributed live camera).  SkipTest, with the reason, when it is not
    set (this PC runs no whole-song test); a set variable naming files that are not there fails instead"""
    if not SONG:
        raise unittest.SkipTest("CAMERA_SONG is not set: it names a JSON of the MV's inputs (dance, model, music, trace), "
                                "on hinata C:/work/hibikase/stage6/camera/song_inputs.json")
    import json
    with open(SONG, encoding="utf-8") as f:
        paths = json.load(f)
    keys = ("dance", "model", "music", "trace")
    missing = ["%s %s" % (k, paths.get(k)) for k in keys if not paths.get(k) or not os.path.isfile(paths[k])]
    if missing:
        raise AssertionError("CAMERA_SONG (%s) names files that are not there: %s" % (SONG, "; ".join(missing)))
    return paths


class RealSongTest(unittest.TestCase):
    """the MV (CAMERA_SONG) with Sour's Rin: the three cameras of stage 6 (music, trace, trace with close-ups), measured
    on the written path.  The current camera (make_camera --handheld 1) cut 20 times, all of them jump cuts (a15), 6 of
    the 14 section heads, every shot 6-15 s; knee 86 % and full 14 % of the frames, nothing closer"""

    @classmethod
    def setUpClass(cls):
        import json
        from mmd_cli.formats import pmx
        paths = song_paths()
        with open(paths["music"], encoding="utf-8-sig") as f:
            cls.music = oc.Music.from_json(json.load(f))
        cls.dancer = oc.dancer_from_motion(pmx.load(paths["model"]), vmd.load(paths["dance"]), cls.music.last_frame)
        cls.trace = oc.read_trace(vmd.load(paths["trace"]), cls.music.last_frame)

    def common(self, shots):
        frames, cuts = oc.make_path(self.dancer, shots)
        self.assertEqual(len(frames), self.music.last_frame + 1)
        self.assertEqual(shots[0].start, 0)
        self.assertEqual(shots[-1].end, self.music.last_frame)
        m = oc.measures(self.dancer, self.music, shots, frames)
        self.assertEqual(m["jump_cuts"], 0, m["jump_cut_list"])
        self.assertGreaterEqual(m["eyes_in_picture"], 0.995)
        # the requester's rule in the numbers it was given in: never below height 10 nor her hips + 1, every frame that
        # shows her hips looks down at them by 4.5 degrees or more (HANDOVER 10/14), and by 15 while she spins fast (the
        # look-down test of the fix round)
        self.assertGreaterEqual(m["camera_above_hips_min"], 1.0 - 1e-6)
        self.assertGreaterEqual(m["camera_height_min"], 10.0 - 1e-6)
        self.assertEqual(m["hips_look_down_low"], 0)
        self.assertGreaterEqual(m["hips_look_down_min"], 4.5 - 1e-6)
        self.assertGreater(m["flare_frames"], 0)
        self.assertGreaterEqual(m["hips_look_down_flare_min"], 15.0 - 1e-6)
        return m

    def test_music(self):
        shots = oc.plan_music(self.music, self.dancer, seed=0)
        m = self.common(shots)
        # on the bar lines, but for the cuts brought onto a move of her head that a close shot would end in (a beat
        # before the bar line at most)
        beat = round(self.music.period * oc.FPS)
        bars = [self.music.bar_frame(b) for b in range(int(self.music.last_frame / (4 * beat)) + 3)]
        for a, b in zip(shots, shots[1:]):
            gap = min(abs(b.start - x) for x in bars)
            if b.early:
                self.assertIn(a.size, ("face", "chest"), (a, b))
                self.assertLessEqual(b.early, beat, b)
                self.assertTrue(any(b.start + b.early == x for x in bars), b)
            else:
                self.assertLessEqual(gap, 1, b)
        self.assertEqual(m["section_heads_cut"], [14, 14])
        self.assertTrue(2.0 <= m["shot_seconds"]["median"] <= 5.0, m["shot_seconds"])
        for size, share in m["size_share"].items():
            self.assertTrue(0.05 <= share <= 0.40, (size, m["size_share"]))
        self.assertGreaterEqual(m["still_share"], 0.5)
        # every close shot ends calm
        moments = oc.Moments(self.dancer)
        for s in shots:
            if s.size in ("face", "chest"):
                self.assertIsNone(moments.tail_move(s.start, s.end, beat), s)

    def test_trace_and_close_ups(self):
        plain_shots = oc.plan_trace(self.trace, self.dancer, self.music)
        plain = self.common(plain_shots)
        self.assertEqual(plain["cuts"], len(self.trace) - 1)
        self.assertGreaterEqual(plain["section_heads_cut"][0], 11)
        self.assertLess(plain["size_share"]["face"], 0.05)
        # the quick change of lens at 100.6 s (3018 -> 3022, field 5 -> 30) is cut where it starts
        self.assertIn(3019, [s.start for s in plain_shots])
        self.assertNotIn(3022, [s.start for s in plain_shots])
        close_shots = oc.plan_trace(self.trace, self.dancer, self.music, close_ups=0.3)
        close = self.common(close_shots)
        self.assertEqual(close["cuts"], plain["cuts"])
        self.assertGreaterEqual(close["size_share"]["face"], 0.08)
        self.assertGreaterEqual(close["size_share"]["chest"] + close["size_share"]["face"], 0.2)
        moments = oc.Moments(self.dancer)
        beat = round(self.music.period * oc.FPS)
        for s in close_shots:
            if s.source == "close_up":
                self.assertIsNone(moments.tail_move(s.start, s.end, beat), s)



GUARD = os.environ.get("CAMERA_GUARD")


class RealGuardTest(unittest.TestCase):
    """the MV's camera D (make_camera --handheld 1) guarded over the whole song.  CAMERA_GUARD names a JSON {"dance",
    "model", "camera", "windows", "lift_aim"} (the dance the camera is drawn with, its model, the camera, guard's --window
    and whether --lift-aim); without it the test is skipped with the reason, with it naming files that are not there it
    fails.  The requester's rule in its own numbers, on every frame and on every subframe of it at 480 fps: every frame
    looks down at her hips and hip joints by 4.5 degrees, by 15 while she turns fast, and
    by 20 at least at the spin of 213.4 s whose skirt flies above level (frames 6402-6404, HANDOVER 10/14-15) and at
    the spin of 58.9 s (frames 1768-1771: the review camfinalrev saw the underwear there at 14.9 degrees in 1 of 3
    renders and at 13.9 in all of them, with the skirt of v11 (pmx_skirt --ceiling 70); 15 leaves about 1 degree)"""

    @classmethod
    def setUpClass(cls):
        import json
        from mmd_cli.formats import pmx
        if not GUARD:
            raise unittest.SkipTest("CAMERA_GUARD is not set: it names a JSON of the MV's dance, model, camera D and "
                                    "guard's windows (on hinata C:/work/hibikase/stage6/camfinal/guard_inputs.json)")
        with open(GUARD, encoding="utf-8") as f:
            paths = json.load(f)
        missing = ["%s %s" % (k, paths.get(k)) for k in ("dance", "model", "camera")
                   if not paths.get(k) or not os.path.isfile(paths[k])]
        if missing:
            raise AssertionError("CAMERA_GUARD (%s) names files that are not there: %s" % (GUARD, "; ".join(missing)))
        dance = vmd.load(paths["dance"])
        model = pmx.load(paths["model"])
        cls.keys = fk.camera_keys(vmd.load(paths["camera"]))
        cls.last = max(fk.last_frame(dance), cls.keys[-1].frame)
        cls.dancer = oc.dancer_from_motion(model, dance, cls.last, hip_joints=True, subframes=oc.GUARD_SUBFRAMES)
        cls.pose = fk.Pose(model, dance, ["下半身", "左足", "右足"])
        cls.windows = [tuple(w) for w in paths.get("windows", [])]
        cls.frames, cls.cuts, cls.tilts = oc.guard_camera(cls.dancer, cls.keys, cls.last, cls.windows)
        cls.lift = bool(paths.get("lift_aim"))
        if cls.lift:
            _, _, cls.base = oc.guard_camera(cls.dancer, cls.keys, cls.last)
            cls.lifted, cls.lifts, cls.runs = oc.lift_aim(cls.dancer, cls.frames, cls.tilts, cls.base, cls.cuts, cls.windows)

    def need_of(self, f, fast):
        need = 15.0 if f in fast else 4.5
        for a, b, degrees in self.windows:
            if a <= f <= b:
                need = max(need, degrees)
        if 6402 <= f <= 6404 or 1768 <= f <= 1771:
            need = max(need, 20.0)
        return need

    def fast_turns(self):
        """the frames she turns fast, counted here from her bones: her shoulders faster than 450 deg/s (over the frames
        either side) and 9 frames each way, her lower body faster than 360 deg/s from a frame to the next and 5 frames
        before, 6 after"""
        n = self.last + 1
        d = self.dancer
        sh = []
        for f in range(n):
            l, r = d.at("lshoulder", f), d.at("rshoulder", f)
            sh.append(math.degrees(math.atan2(l[2] - r[2], l[0] - r[0])))
        pv = []
        for f in range(n):
            w, p = d.at("waist", f), d.at("pelvis_front", f)
            pv.append(math.degrees(math.atan2(p[0] - w[0], -(p[2] - w[2]))))
        sh, pv = oc.unwrap(sh), oc.unwrap(pv)
        out = set()
        for f in range(n):
            a, b = max(f - 1, 0), min(f + 1, n - 1)
            if abs(sh[b] - sh[a]) / (b - a) * 30.0 > 450.0:
                out.update(range(max(0, f - 9), min(n, f + 10)))
        for f in range(n - 1):
            if abs(pv[f + 1] - pv[f]) * 30.0 > 360.0:
                out.update(range(max(0, f - 5), min(n, f + 7)))
        return out

    def test_every_frame_looks_down_at_her_hips_as_far_as_the_rule_asks(self):
        fast = self.fast_turns()
        self.assertGreater(len(fast), 200)
        least = {}
        for f, cam in enumerate(self.frames):
            need = 15.0 if f in fast else 4.5
            for a, b, degrees in self.windows:
                if a <= f <= b:
                    need = max(need, degrees)
            if 6402 <= f <= 6404:
                need = max(need, 20.0)
            if 1768 <= f <= 1771:
                need = max(need, 20.0)
            got = look_down_at_her_hips(self.dancer, f, cam.position)
            self.assertGreaterEqual(got, need - 1e-6, (f, got, need))
            least[need] = min(least.get(need, 90.0), got)
        self.assertIn(4.5, least)
        self.assertIn(15.0, least)

    def test_every_subframe_looks_down_at_her_hips_as_far_as_its_frame_asks(self):
        # MMD keeps the camera of a frame over its 16 subframes at 480 fps (a key on every frame) while she moves on: her
        # hips and hip joints at f + k/16 from the dance's own curves (fk.Pose here, not the tool's dancer), seen from
        # the camera of frame f (the review camfinalrev found 5 frames at the end of a spin or a window 0.36 degrees
        # short between the frames)
        fast = self.fast_turns()
        below = oc.HIPS_BELOW_WAIST
        for f, cam in enumerate(self.frames):
            need = self.need_of(f, fast)
            points = []
            for k in range(16):
                w = self.pose.at(f + k / 16.0)
                low = w["下半身"][0]
                points += [(low[0], low[1] - below, low[2]), w["左足"][0], w["右足"][0]]
            got = look_down_at_points(cam.position, points)
            self.assertGreaterEqual(got, need - 1e-6, (f, got, need))

    def test_a_lifted_aim_keeps_the_eye_and_her_knees(self):
        # (when the inputs ask guard to lift the windows' aim, "lift_aim": true): the eye of every frame is guard's, so the
        # look-down at her hips above holds for the camera written; her knees stay LIFT_ROOM above the bottom edge where
        # the aim is lifted; no frame looks higher than it would without the windows
        if not self.lift:
            self.skipTest("the inputs do not ask for --lift-aim")
        self.assertGreater(max(self.lifts), 0.0)
        for f, (a, b) in enumerate(zip(self.frames, self.lifted)):
            self.assertLess(math.dist(a.position, b.position), 1e-9, f)
            self.assertAlmostEqual(b.pitch, a.pitch - self.lifts[f], places=9)
            self.assertLessEqual(self.lifts[f], self.tilts[f] - self.base[f] + 1e-9, f)
            if self.lifts[f] > 0.0:
                for knee in knees_of(self.dancer, f):
                    u, v, depth = oc.project(b.position, b.yaw, b.pitch, b.roll, b.fov, knee)
                    self.assertGreaterEqual(v, -1.0 + oc.LIFT_ROOM - 1e-9, f)

    def test_the_shots_are_the_inputs_but_for_the_tilt(self):
        self.assertEqual(self.cuts, oc.step_cuts(self.keys))
        frames_of_keys = [k.frame for k in self.keys]
        cut_set = set(self.cuts)
        for f, cam in enumerate(self.frames):
            s = fk.camera_at(self.keys, f, frames_of_keys)
            self.assertLess(math.dist(look_at_of(cam), s.look_at), 1e-6, f)
            self.assertAlmostEqual(cam.reach, s.distance, places=6)
            self.assertAlmostEqual(cam.yaw, s.angles[1], places=6)
            self.assertEqual(cam.fov, int(round(s.fov)))
            self.assertAlmostEqual(cam.pitch, s.angles[0] + self.tilts[f], places=6)
            if f > 0 and f not in cut_set:
                self.assertLessEqual(abs(self.tilts[f] - self.tilts[f - 1]), 20.0 / 30.0 + 1e-9, f)

    def test_the_spin_of_213_4_s_is_looked_down_at_by_30_degrees_on_every_subframe(self):
        # COMMON.md (the requester's rule): the spin at 213.40-213.47 s (frames 6402-6404) flings the skirt above level and
        # only a look-down of 30 degrees or more hides what is under it (v8: 15 and 20 showed it, 25 a little).  The 30
        # holds whatever windows the inputs give (the test above takes the windows' own need; this one does not)
        below = oc.HIPS_BELOW_WAIST
        for f in range(6402, 6405):
            points = []
            for k in range(16):
                w = self.pose.at(f + k / 16.0)
                low = w["下半身"][0]
                points += [(low[0], low[1] - below, low[2]), w["左足"][0], w["右足"][0]]
            got = look_down_at_points(self.frames[f].position, points)
            self.assertGreaterEqual(got, 30.0 - 1e-6, (f, got))

    def test_a_shot_the_music_camera_holds_still_is_not_moved_by_the_guard(self):
        # a shot of the input whose distance, heading and look-down do not move beyond the handheld sway (the music
        # camera's break and end, where the song stops) stays still: what the guard and the lifted aim change of its
        # look-down varies over the shot by no more than the input's own sway there, and 0.5 degrees at most (review
        # camsyncrev: a window reaching 13 frames into the still end, 7610-7742, raised it by 16.4 degrees and set it down
        # again over 1.4 s, 12.3 degrees of look-down, while the song had stopped)
        frames_of_keys = [k.frame for k in self.keys]
        states = [fk.camera_at(self.keys, f, frames_of_keys) for f in range(self.last + 1)]
        written = self.lifted if self.lift else self.frames
        bounds = [0] + list(self.cuts) + [self.last + 1]
        still = 0
        for a, b in zip(bounds, bounds[1:]):
            pitch = [s.angles[0] for s in states[a:b]]
            yaw = [s.angles[1] for s in states[a:b]]
            dist = [s.distance for s in states[a:b]]
            if max(dist) - min(dist) >= 0.5 or max(yaw) - min(yaw) >= 1.0 or max(pitch) - min(pitch) >= 1.0:
                continue
            still += 1
            sway = max(pitch) - min(pitch)
            change = [written[f].pitch - states[f].angles[0] for f in range(a, b)]
            self.assertLessEqual(max(change) - min(change), min(sway, 0.5) + 1e-9, (a, b - 1, max(change) - min(change), sway))
        self.assertGreater(still, 0)


# ---- (review camsyncrev 2026-10-21) the cases the tests above let pass: the tools broken one place at a time (139 ways:
# 80 that changed what the tool does were not caught), each case below fails on one of them and passes on the tool as it is
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

from mmd_cli import mathutil  # noqa: E402
from mmd_cli.formats import pmx  # noqa: E402


def keys_of(frames, cuts=(0,)):
    return fk.camera_keys(oc.camera_motion(frames, list(cuts)))


def quiet(main, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def guard_and_lift(dancer, keys, last, window):
    frames, cuts, tilts = oc.guard_camera(dancer, keys, last, [window])
    _, _, base = oc.guard_camera(dancer, keys, last)
    lifted, lifts, runs = oc.lift_aim(dancer, frames, tilts, base, cuts, [window])
    return frames, tilts, base, lifted, lifts, runs


def still_keys(look_at, pitch, reach, n, fov=30):
    return keys_of([oc.CameraFrame(oc.place_camera(look_at, 0.0, pitch, reach), 0.0, pitch, 0.0, fov, reach)] * n)


def least_knee_room(dancer, cams, frames):
    least = 9.0
    for f in frames:
        cam = cams[f]
        for knee in knees_of(dancer, f):
            _, v, depth = oc.project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, knee)
            least = min(least, v if depth > 0 else -9.0)
    return least



class GuardSubframeLiftTest(unittest.TestCase):
    def test_the_command_guards_her_hips_where_the_dance_turns_them_between_frames(self):
        # her lower body turns 120 degrees a frame, so her hip joints go round between the frames, off the straight lines
        # between them; the command guards a level camera through a window of 30 degrees: every subframe f + k/16 of the
        # window, her hips and hip joints where the dance's own curves put them (fk.Pose), is looked down at by 30 degrees
        # from the camera of frame f (T3-09)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model, dance, camera, out = (os.path.join(folder, n) for n in ("rin.pmx", "dance.vmd", "cam.vmd", "out.vmd"))
        with open(model, "wb") as f:
            f.write(rin_like_model())
        motion = vmd.Motion(model_name="dancer", bones=[vmd.BoneKey("下半身", f, (0.0, 0.0, 0.0),
                                                                    mathutil.euler_to_quat(0.0, 120.0 * f, 0.0)) for f in range(31)])
        with open(dance, "wb") as f:
            f.write(vmd.dumps(motion))
        hips = (0.0, 12.23 - oc.HIPS_BELOW_WAIST, -0.65)
        with open(camera, "wb") as f:
            f.write(vmd.dumps(oc.camera_motion([oc.CameraFrame(oc.place_camera(hips, 0.0, 0.0, 10.0), 0.0, 0.0, 0.0, 30, 10.0)] * 31,
                                               [0])))
        code, result = quiet(oc.main, ["guard", dance, model, camera, out, "--window", "10", "20", "30"])
        self.assertEqual(code, 0, result)
        pose = fk.Pose(pmx.load(model), vmd.load(dance), ["下半身", "左足", "右足"])
        back = fk.camera_keys(vmd.load(out))
        frames = [k.frame for k in back]
        least = 90.0
        for f in range(10, 21):
            eye = fk.camera_position(fk.camera_at(back, f, frames))
            for k in range(16):
                w = pose.at(f + k / 16.0)
                low = w["下半身"][0]
                least = min(least, look_down_at_points(eye, [(low[0], low[1] - oc.HIPS_BELOW_WAIST, low[2]), w["左足"][0],
                                                             w["右足"][0]]))
        self.assertGreaterEqual(least, 30.0 - 1e-3)

    def test_a_dancer_without_her_hip_joints_is_refused_by_name(self):
        full = standing(60)
        tracks = {n: full.tracks[n] for n in oc.LANDMARKS + ("pelvis_front",)}
        with self.assertRaises(ValueError) as caught:
            oc.guard_camera(oc.Dancer(tracks), still_keys((0.0, REST["hips"], 0.0), 0.0, 40.0, 60), 59)
        self.assertIn("hip joints", str(caught.exception))                                 # T3-10

    def test_the_measures_count_a_frame_short_when_a_subframe_is(self):
        # she walks away half a unit a frame; a camera on every frame looks down 30 degrees at her hips there: at the
        # frame heads it is enough for 29.9, at the later subframes it is not (T3-13)
        dancer = standing(60, sway=lambda f: (0.0, 0.5 * f))
        cams = [oc.CameraFrame(oc.place_camera(dancer.at("hips", f), 0.0, 30.0, 20.0), 0.0, 30.0, 0.0, 30, 20.0) for f in range(60)]
        heads = min(look_down_at_points(c.position, [dancer.at(n, f) for n in ("hips", "lhip", "rhip")]) for f, c in enumerate(cams))
        self.assertGreater(heads, 29.9)
        view, _ = oc.guard_view(dancer, cams, [29.9] * 60, [False] * 60, [(0, 59, 29.9)])
        self.assertGreater(view["short_frames"], 50)

    def kicking(self):
        """standing, her left foot kicked up to 8 units and 3 forward over frames 60-139 ("toes" between her toes, as
        dancer_from_motion gives it)"""
        base = standing(200)
        tracks = {n: list(base.tracks[n]) for n in base.tracks}
        for f in range(60, 140):
            x, _, z = tracks["ltoe"][f]
            tracks["ltoe"][f] = (x, 8.0, z - 3.0)
        tracks["toes"] = [tuple((a + b) / 2.0 for a, b in zip(l, r)) for l, r in zip(tracks["ltoe"], tracks["rtoe"])]
        return oc.Dancer(tracks)

    def test_a_lift_keeps_her_standing_knee_while_she_kicks(self):
        # her right knee, half way from her right hip joint to her right toe on the floor, is the lower one while she kicks:
        # the lift keeps it LIFT_ROOM over the bottom edge (T3-14: both knees from the toes' middle; T3-19: the left only)
        dancer = self.kicking()
        frames, tilts, base, lifted, lifts, runs = guard_and_lift(dancer, still_keys((0.0, REST["chest"], 0.0), 5.0, 70.0, 200),
                                                                  199, (90, 110, 35.0))
        self.assertGreater(max(lifts), 1.0)
        self.assertGreaterEqual(least_knee_room(dancer, lifted, range(200)), -1.0 + oc.LIFT_ROOM - 1e-9)

    def test_her_knees_keep_a_twentieth_of_the_picture_under_them(self):
        # (pins LIFT_ROOM: "half-heights: 5 % of the picture") a lift as far as her knees let it leaves the lower knee 5 %
        # of the picture's height over its bottom edge (T3-27)
        dancer = standing(200)
        frames, tilts, base, lifted, lifts, runs = guard_and_lift(dancer, still_keys((0.0, REST["chest"], 0.0), 5.0, 70.0, 200),
                                                                  199, (90, 110, 35.0))
        self.assertLess(runs[0]["share"], 1.0)
        self.assertAlmostEqual(least_knee_room(dancer, lifted, [f for f in range(200) if lifts[f] > 0]), -0.9, delta=2e-3)

    def test_the_lift_gives_back_only_what_the_window_adds(self):
        # her shoulders spin over frames 90-110 (15 degrees), a window there asks 18, a far camera gives her knees room:
        # the lift gives back at most what the window adds over the spin, never the spin's own tilt (T3-20)
        dancer = standing(200, turn=lambda f: 20.0 * min(20.0, max(0.0, f - 90.0)))
        frames, tilts, base, lifted, lifts, runs = guard_and_lift(dancer, still_keys((0.0, REST["chest"], 0.0), 5.0, 120.0, 200),
                                                                  199, (85, 115, 18.0))
        self.assertGreater(max(base), 3.0)
        self.assertGreater(max(lifts), 0.5)
        for f in range(200):
            self.assertLessEqual(lifts[f], tilts[f] - base[f] + 1e-9, f)

    def test_with_room_to_spare_the_lift_gives_back_all_of_the_windows_tilt(self):
        # a far camera, a small window: her knees have room for all of it, so the camera turns back up to look as it would
        # without the window, from the window's eye (LIFT_SHARE's "all of it") (T3-28)
        dancer = standing(200)
        frames, tilts, base, lifted, lifts, runs = guard_and_lift(dancer, still_keys((0.0, REST["chest"], 0.0), 5.0, 120.0, 200),
                                                                  199, (90, 110, 12.0))
        self.assertEqual(max(base), 0.0)
        self.assertGreater(max(tilts), 2.0)
        self.assertEqual([r["share"] for r in runs], [1.0])
        for f in range(200):
            self.assertAlmostEqual(lifted[f].pitch, 5.0, places=6, msg=f)

    def test_each_shots_run_is_lifted_on_its_own(self):
        # a window across a cut (80-120, the cut at 100): the shot before the cut has room under her knees, the close shot
        # after it has none; the first is lifted all the same (T3-21)
        dancer = standing(200)
        wide = oc.CameraFrame(oc.place_camera((0.0, REST["chest"], 0.0), 0.0, 5.0, 70.0), 0.0, 5.0, 0.0, 30, 70.0)
        close = oc.CameraFrame(oc.place_camera((0.0, REST["eyes"], 0.0), 0.0, 0.0, 30.0), 0.0, 0.0, 0.0, 30, 30.0)
        frames, tilts, base, lifted, lifts, runs = guard_and_lift(dancer, keys_of([wide] * 100 + [close] * 100, [0, 100]),
                                                                  199, (80, 120, 35.0))
        self.assertGreater(max(lifts[:100]), 1.0)
        self.assertEqual(max(lifts[100:]), 0.0)

    def test_subframes_must_be_as_many_on_every_frame(self):
        d = standing(10)                                                                    # T3-33
        tracks = {n: d.tracks[n] for n in d.tracks}
        point = (0.0, 10.0, 0.0)
        for sub in ({"hips": [[point] * 16] * 9}, {"hips": [[point] * 16] * 9 + [[point] * 8]}):
            with self.assertRaises(ValueError):
                oc.Dancer(tracks, sub)

    def test_the_toes_of_a_dancer_read_from_a_dance_are_her_own(self):
        # her left toe IK steps forward and up: the left toe the knee is made from is that one (T3-34)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "rin.pmx")
        with open(path, "wb") as f:
            f.write(rin_like_model())
        model = pmx.load(path)
        motion = vmd.Motion(model_name="d", bones=[vmd.BoneKey("左つま先ＩＫ", 0, (0.0, 0.0, 0.0), fk.IDENTITY),
                                                   vmd.BoneKey("左つま先ＩＫ", 10, (0.0, 3.0, -3.0), fk.IDENTITY)])
        dancer = oc.dancer_from_motion(model, motion, 10, hip_joints=True)
        track = fk.world_track(model, motion, ["左つま先ＩＫ", "右つま先ＩＫ"], 0, 10)
        for f in (0, 5, 10):
            for a, b in zip(dancer.at("ltoe", f), track["左つま先ＩＫ"][f][0]):
                self.assertAlmostEqual(a, b, places=6)
            for a, b in zip(dancer.at("rtoe", f), track["右つま先ＩＫ"][f][0]):
                self.assertAlmostEqual(a, b, places=6)


class GuardCommandLiftTest(unittest.TestCase):
    def test_the_command_lifts_the_aim_and_says_how_far(self):
        # the command test's cameras (a low shot level at her hips, a high one) and window: with --lift-aim some frames are
        # lifted, the written cameras look higher there from the same eyes, and the top edge of each lifted run comes down
        # (T3-30, T3-31, T3-32)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model, dance, camera = (os.path.join(folder, n) for n in ("rin.pmx", "dance.vmd", "cam.vmd"))
        with open(model, "wb") as f:
            f.write(rin_like_model())
        with open(dance, "wb") as f:
            f.write(vmd.dumps(walking_dance(119)))
        low = oc.place_camera((0.0, REST["hips"], 0.0), 0.0, 0.0, 200.0)
        high = oc.place_camera((0.0, REST["chest"], 0.0), 60.0, 25.0, 40.0)
        before = [oc.CameraFrame(low, 0.0, 0.0, 0.0, 5, 200.0)] * 60 + [oc.CameraFrame(high, 60.0, 25.0, 0.0, 30, 40.0)] * 60
        with open(camera, "wb") as f:
            f.write(vmd.dumps(oc.camera_motion(before, [0, 60])))
        outs = {}
        for name, extra in (("plain", []), ("lifted", ["--lift-aim"])):
            out, report = os.path.join(folder, name + ".vmd"), os.path.join(folder, name + ".json")
            code, result = quiet(oc.main, ["guard", dance, model, camera, out, "--report", report, "--window", "10", "15", "30"]
                                 + extra)
            self.assertEqual(code, 0, result)
            with open(report, encoding="ascii") as f:
                outs[name] = (fk.camera_keys(vmd.load(out)), json.load(f))
        (a_keys, _), (b_keys, data) = outs["plain"], outs["lifted"]
        self.assertGreater(data["frames_lifted"], 0)
        self.assertGreater(data["lift_max"], 0.0)
        lifted = [f for f, x in enumerate(data["per_frame"]["lift"]) if x > 0.01]
        self.assertTrue(lifted)
        for f in lifted:
            a, b = fk.camera_at(a_keys, f), fk.camera_at(b_keys, f)
            self.assertLess(math.dist(fk.camera_position(a), fk.camera_position(b)), 1e-3, f)
            self.assertLess(b.angles[0], a.angles[0] - 1e-4, f)                            # it looks less down
        for run in data["lifts"]:
            if run["lift_max"] > 0.0:
                self.assertLess(run["top_edge_max_after"], run["top_edge_max_before"], run)


class CloseLookDownTest(unittest.TestCase):
    """the close sizes (waist and closer) look down at her hips by 30 degrees or more (COMMON.md, 2026-10-17: legs drawn
    close from 8 and 15 degrees above showed the underwear at 213.43 s; a viewpoint near the height of her hip joints is
    not used close either): frame_size frames a size from as high as a look-down asks, and guard holds the close pictures
    of another camera to it (camsync2: the camera D had no close size at all)"""

    def test_a_close_size_is_framed_from_as_high_as_its_look_down_asks(self):
        d = standing(10)
        for size in ("waist", "chest"):
            plain = oc.frame_size(d, 0, size, 0.0, fov=30)
            self.assertLess(look_down_at_her_hips(d, 0, plain.position), 30.0, size)
            cam = oc.frame_size(d, 0, size, 0.0, fov=30, look_down=30.5)
            self.assertGreaterEqual(look_down_at_her_hips(d, 0, cam.position), 30.5 - 1e-6, size)
            # still that size: her head top on the size's row, the picture's bottom edge at its cut
            s = oc.seen(d, 0, cam)
            self.assertAlmostEqual(s["headtop_v"], 1.0 - 2.0 * oc.SIZE_SPEC[size]["room"], places=3)
            self.assertEqual(oc.classify(s["visible"], s["body_share"]), size)
            self.assertGreater(cam.position[1], plain.position[1], size)

    def test_without_a_look_down_the_frame_is_the_one_before(self):
        d = standing(10)
        for size in oc.SIZES:
            self.assertEqual(oc.frame_size(d, 0, size, 25.0), oc.frame_size(d, 0, size, 25.0, look_down=None))

    def test_the_needs_of_the_close_frames_are_the_close_look_down(self):
        d = standing(60)
        close = [20 <= f < 40 for f in range(60)]
        need, _ = oc.guard_needs(d, 59, (), close)
        self.assertEqual(need[:20], [oc.MIN_LOOK_DOWN] * 20)
        self.assertEqual(need[20:40], [oc.CLOSE_LOOK_DOWN] * 20)
        self.assertEqual(need[40:], [oc.MIN_LOOK_DOWN] * 20)
        self.assertEqual(oc.CLOSE_LOOK_DOWN, 30.0)

    def test_guard_raises_a_close_picture_to_the_close_look_down(self):
        # a chest shot from a unit under her eyes (it looks down at her hips by about 20 degrees, and up at her eyes: not
        # clear, ChestClearTest): every frame and subframe of it is raised to look down at them by 30 or more
        d = standing(90)
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30, height=REST["eyes"] - 1.0)
        self.assertLess(look_down_at_her_hips(d, 0, cam.position), 30.0)
        frames, cuts, tilts = oc.guard_camera(d, keys_of([cam] * 90), 89)
        self.assertGreater(min(tilts), 0.0)
        for f in range(90):
            points = [between_frames(d, n, f, k) for n in ("hips", "lhip", "rhip") for k in range(16)]
            self.assertGreaterEqual(look_down_at_points(frames[f].position, points), 30.0 - 1e-6, f)

    def test_guard_leaves_a_knee_picture_to_the_usual_rule(self):
        d = standing(90)
        cam = oc.frame_size(d, 0, "knee", 0.0)
        self.assertGreater(look_down_at_her_hips(d, 0, cam.position), oc.MIN_LOOK_DOWN)
        frames, cuts, tilts = oc.guard_camera(d, keys_of([cam] * 90), 89)
        self.assertEqual(max(tilts), 0.0)

    def test_a_close_shot_is_judged_on_the_camera_it_is_given(self):
        # a knee shot and a waist shot after a cut: only the waist shot's frames ask the close look-down
        d = standing(120)
        knee = oc.frame_size(d, 0, "knee", 0.0)
        waist = oc.frame_size(d, 0, "waist", 40.0, fov=30)
        self.assertEqual(oc.close_frames(d, [knee] * 60 + [waist] * 60), [False] * 60 + [True] * 60)


def row_height(cam, x, z, row):
    """the height a point at (x, z) on the floor plan stands at to fall on the picture's row `row` (v) of `cam`"""
    lo, hi = -40.0, 60.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if oc.project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, (x, mid, z))[1] < row:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


class ChestClearTest(unittest.TestCase):
    """the exception to the close look-down (COMMON, 2026-10-22): a chest picture need not look down at her hips by
    CLOSE_LOOK_DOWN when her hips and hip joints stay CHEST_HIPS_UNDER (5 % of the picture's height) or more under its
    bottom edge on every subframe (her crotch, under them, further) and the camera does not look up at her eyes; the
    general rule (MIN_LOOK_DOWN, FLARE_LOOK_DOWN in a fast turn) still holds there"""

    def test_the_margins_are_five_percent_of_the_picture_and_level_with_her_eyes(self):
        self.assertEqual(oc.CHEST_HIPS_UNDER, 0.10)          # half-heights: 5 % of the picture's height
        self.assertEqual(oc.CHEST_EYES_DOWN, 0.0)

    def test_a_chest_picture_from_her_eye_height_is_clear_and_guard_leaves_it(self):
        d = standing(90)
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30)       # (the chest's eye height: hers)
        s = oc.seen(d, 0, cam)
        self.assertEqual(oc.classify(s["visible"], s["body_share"]), "chest")
        self.assertAlmostEqual(cam.position[1], REST["eyes"], places=6)
        self.assertLess(look_down_at_her_hips(d, 0, cam.position), oc.CLOSE_LOOK_DOWN)
        self.assertTrue(oc.chest_clear(d, 0, cam))
        under, eyes = oc.chest_margins(d, 0, cam)
        self.assertGreater(under, oc.CHEST_HIPS_UNDER)
        self.assertAlmostEqual(eyes, 0.0, places=6)
        self.assertEqual(oc.close_frames(d, [cam] * 90), [False] * 90)
        frames, cuts, tilts = oc.guard_camera(d, keys_of([cam] * 90), 89)
        self.assertEqual(max(tilts), 0.0)

    def test_a_chest_picture_from_under_her_eyes_is_close(self):
        d = standing(30)
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30, height=REST["eyes"] - 0.05)
        s = oc.seen(d, 0, cam)
        self.assertEqual(oc.classify(s["visible"], s["body_share"]), "chest")
        self.assertFalse(oc.chest_clear(d, 0, cam))
        self.assertEqual(oc.close_frames(d, [cam] * 30), [True] * 30)

    def test_her_hips_near_the_bottom_edge_on_one_subframe_make_the_frame_close(self):
        # the hip joints given at 16 subframes a frame (as guard reads the dance): on one subframe of frame 10 her left hip
        # joint comes up to 4 % of the picture's height under the bottom edge (6 % on frame 20's)
        d = standing(30)
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30)
        sub = {name: [[d.at(name, f)] * 16 for f in range(30)] for name in oc.GUARD_POINTS}
        x, _, z = d.at("lhip", 10)
        sub["lhip"][10] = sub["lhip"][10][:7] + [(x, row_height(cam, x, z, -1.08), z)] + sub["lhip"][10][8:]
        sub["lhip"][20] = sub["lhip"][20][:7] + [(x, row_height(cam, x, z, -1.12), z)] + sub["lhip"][20][8:]
        tracks = {n: [d.at(n, f) for f in range(30)] for n in d.tracks}
        d2 = oc.Dancer(tracks, sub)
        self.assertTrue(oc.chest_clear(d2, 9, cam))
        self.assertFalse(oc.chest_clear(d2, 10, cam))
        self.assertTrue(oc.chest_clear(d2, 20, cam))
        self.assertAlmostEqual(oc.chest_margins(d2, 10, cam)[0], 0.08, places=6)
        close = oc.close_frames(d2, [cam] * 30)
        self.assertEqual([f for f in range(30) if close[f]], [10])

    def test_only_a_chest_picture_is_ever_clear(self):
        # a waist picture from her eye height looks down at her hips by less than 30 degrees and is close
        d = standing(30)
        waist = oc.frame_size(d, 0, "waist", 0.0, fov=30, height=REST["eyes"])
        s = oc.seen(d, 0, waist)
        self.assertEqual(oc.classify(s["visible"], s["body_share"]), "waist")
        self.assertEqual(oc.close_frames(d, [waist] * 30), [True] * 30)

    def test_a_clear_chest_picture_still_looks_down_as_a_fast_turn_asks(self):
        # her shoulders spinning: the general rule's 15 degrees (the chest from her eye height looks down about 22 already)
        d = standing(60, turn=lambda f: 900.0 * f / FPS if 20 <= f <= 40 else (900.0 * 20 / FPS if f > 40 else 0.0))
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30)
        close = oc.close_frames(d, [cam] * 60)
        need, fast = oc.guard_needs(d, 59, (), close)
        self.assertTrue(any(fast))
        self.assertFalse(any(close))
        self.assertEqual(max(need), oc.FLARE_LOOK_DOWN)

    def test_the_guard_report_counts_the_clear_chest_frames(self):
        d = standing(30)
        cam = oc.frame_size(d, 0, "chest", 0.0, fov=30)
        close = oc.close_frames(d, [cam] * 30)
        need, fast = oc.guard_needs(d, 29, (), close)
        clear = oc.chest_clear_frames(d, [cam] * 30)
        view, _ = oc.guard_view(d, [cam] * 30, need, fast, (), close, clear)
        self.assertEqual(view["chest_clear_frames"], 30)
        self.assertEqual(view["close_frames"], 0)
        self.assertGreater(view["chest_clear_hips_under_min"], 0.05)          # a share of the picture's height
        self.assertAlmostEqual(view["chest_clear_eyes_down_min"], 0.0, places=4)
        self.assertGreater(view["chest_clear_look_down_min"], oc.MIN_LOOK_DOWN)


def rin_with_ankles():
    """rin_like_model with the leg IK bones (左足ＩＫ, 右足ＩＫ: at the ankles, as on Sour's Rin)"""
    from tests.test_pmx import NORMAL, TRANSLATE, Writer
    w = Writer(bone=2)
    bones = [("全ての親", -1, (0.0, 0.0, 0.0), NORMAL | TRANSLATE), ("センター", 0, (0.0, 7.85, 0.0), NORMAL | TRANSLATE),
             ("上半身", 1, (0.0, 12.23, -0.65), NORMAL), ("上半身2", 2, (0.0, 13.8, -0.68), NORMAL),
             ("首", 3, (0.0, 15.65, -0.13), NORMAL), ("頭", 4, (0.0, 16.24, 0.0), NORMAL),
             ("左目", 5, (0.41, 17.21, -0.56), NORMAL), ("右目", 5, (-0.41, 17.21, -0.56), NORMAL),
             ("下半身", 1, (0.0, 12.23, -0.65), NORMAL), ("左腕", 3, (0.91, 15.28, -0.25), NORMAL),
             ("右腕", 3, (-0.91, 15.28, -0.25), NORMAL), ("左つま先ＩＫ", 0, (1.05, 0.1, -1.15), NORMAL | TRANSLATE),
             ("右つま先ＩＫ", 0, (-1.05, 0.1, -1.15), NORMAL | TRANSLATE), ("左足", 8, (0.90, 10.66, 0.007), NORMAL),
             ("右足", 8, (-0.90, 10.59, 0.007), NORMAL), ("左足ＩＫ", 0, (0.93, 1.75, 0.38), NORMAL | TRANSLATE),
             ("右足ＩＫ", 0, (-0.93, 1.75, 0.38), NORMAL | TRANSLATE), ("左ひざ", 13, (0.92, 6.0, -0.30), NORMAL),
             ("右ひざ", 14, (-0.92, 5.95, -0.30), NORMAL), ("左足首", 17, (0.93, 1.75, 0.38), NORMAL),
             ("右足首", 18, (-0.93, 1.75, 0.38), NORMAL)]
    return w.build(name="rin-ankles", bones=[w.bone(n, parent=p, position=pos, flags=fl) for n, p, pos, fl in bones])


class SizeSpecAndAnklesTest(unittest.TestCase):
    """camsync2: make_camera --song frames its sizes with operator_camera.frame_size and its own cut of a size (a waist shot
    with her hip joints well inside the picture), and checks a knee shot by her ankles: frame_size and picture_span take a
    size's spec, and dancer_from_motion reads the ankles (the leg IK bones) on request"""

    def test_a_size_is_framed_by_the_spec_it_is_given(self):
        d = standing(10)
        spec = {"cut": 0.56, "room": 0.08, "fov": 30, "eye": -0.5}
        cam = oc.frame_size(d, 0, "waist", 0.0, fov=30, spec=spec)
        body = REST["headtop"] - REST["toes"]
        bottom, top, row = oc.picture_span("waist", REST["headtop"], REST["toes"], spec=spec)
        self.assertAlmostEqual(bottom, REST["headtop"] - 0.56 * body, places=9)
        self.assertAlmostEqual(row, 1.0 - 2.0 * 0.08, places=9)
        ax, az = oc.anchor(d, 0, "waist")
        v_bottom = oc.project(cam.position, cam.yaw, cam.pitch, 0.0, 30, (ax, bottom, az))[1]
        self.assertAlmostEqual(v_bottom, -1.0, places=3)
        s = oc.seen(d, 0, cam)
        self.assertEqual(oc.classify(s["visible"], s["body_share"]), "waist")
        # without a spec, the size's own (SIZE_SPEC): the same as before
        self.assertEqual(oc.frame_size(d, 0, "waist", 0.0, fov=30, spec=None), oc.frame_size(d, 0, "waist", 0.0, fov=30))
        self.assertEqual(oc.picture_span("knee", 19.5, 0.1), oc.picture_span("knee", 19.5, 0.1, spec=oc.SIZE_SPEC["knee"]))

    def test_a_dancer_read_with_ankles_has_them_at_the_leg_ik_bones(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "rin.pmx")
        with open(path, "wb") as f:
            f.write(rin_with_ankles())
        model = pmx.load(path)
        motion = vmd.Motion(model_name="d", bones=[vmd.BoneKey("左足ＩＫ", 0, (0.0, 0.0, 0.0), fk.IDENTITY),
                                                   vmd.BoneKey("左足ＩＫ", 10, (0.0, 4.0, -2.0), fk.IDENTITY)])
        dancer = oc.dancer_from_motion(model, motion, 10, hip_joints=True, ankles=True)
        track = fk.world_track(model, motion, ["左足ＩＫ", "右足ＩＫ"], 0, 10)
        for f in (0, 5, 10):
            for name, bone_name in (("lankle", "左足ＩＫ"), ("rankle", "右足ＩＫ")):
                for a, b in zip(dancer.at(name, f), track[bone_name][f][0]):
                    self.assertAlmostEqual(a, b, places=6)
        self.assertAlmostEqual(dancer.at("lankle", 10)[1], 1.75 + 4.0, places=6)
        # read without them, the dancer has none; a model without the leg IK bones is refused when they are asked for
        self.assertFalse(oc.dancer_from_motion(model, motion, 10, hip_joints=True).has("lankle"))
        plain = os.path.join(folder, "plain.pmx")
        with open(plain, "wb") as f:
            f.write(rin_like_model())
        with self.assertRaises(ValueError):
            oc.dancer_from_motion(pmx.load(plain), motion, 10, hip_joints=True, ankles=True)

    def test_her_knees_are_where_the_legs_of_her_length_reach_from_hip_to_ankle_bending_forward(self):
        # (the forward kinematics has no IK, so the knees are solved as two bones of the model's lengths from the hip
        # joint to the ankle, bending the way her lower body faces; the midpoint of hip and ankle missed a deep bend by up
        # to 3.8 units on the MV's dance)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "rin.pmx")
        with open(path, "wb") as f:
            f.write(rin_with_ankles())
        model = pmx.load(path)
        rest = {b.name: b.position for b in model.bones}
        thigh, shin = math.dist(rest["左足"], rest["左ひざ"]), math.dist(rest["左ひざ"], rest["左足首"])
        motion = vmd.Motion(model_name="d", bones=[vmd.BoneKey("左足ＩＫ", 0, (0.0, 0.0, 0.0), fk.IDENTITY),
                                                   vmd.BoneKey("左足ＩＫ", 10, (0.0, 4.0, -2.0), fk.IDENTITY),
                                                   vmd.BoneKey("左つま先ＩＫ", 0, (0.0, 0.0, 0.0), fk.IDENTITY),
                                                   vmd.BoneKey("左つま先ＩＫ", 10, (0.0, 4.0, -2.0), fk.IDENTITY)])
        dancer = oc.dancer_from_motion(model, motion, 10, hip_joints=True, ankles=True)
        for f in (0, 5, 10):
            hip, knee, ankle = dancer.at("lhip", f), dancer.at("lknee", f), dancer.at("lankle", f)
            self.assertAlmostEqual(math.dist(hip, knee), thigh, places=6)
            self.assertAlmostEqual(math.dist(knee, ankle), shin, places=6)
            # in front of the line from her hip to her ankle (-Z, the way her lower body faces)
            t = sum((k - h) * (a - h) for k, h, a in zip(knee, hip, ankle)) / math.dist(hip, ankle) ** 2
            on_line = tuple(h + (a - h) * t for h, a in zip(hip, ankle))
            self.assertLess(knee[2], on_line[2])
        # at rest the solve gives the model's own knee (its lengths, its bend)
        for a, b in zip(dancer.at("lknee", 0), rest["左ひざ"]):
            self.assertAlmostEqual(a, b, delta=0.05)
        # raised 4 and forward 2 the ankle comes 4.5 nearer her hip: the knee goes forward and up
        self.assertLess(dancer.at("lknee", 10)[2], dancer.at("lknee", 0)[2] - 1.0)
        self.assertGreater(dancer.at("lknee", 10)[1], dancer.at("lknee", 0)[1])
        # a leg stretched past its length has the knee on the line at the thigh's length
        far = vmd.Motion(model_name="d", bones=[vmd.BoneKey("左足ＩＫ", 0, (0.0, -6.0, 0.0), fk.IDENTITY)])
        d2 = oc.dancer_from_motion(model, far, 0, hip_joints=True, ankles=True)
        hip, knee, ankle = d2.at("lhip", 0), d2.at("lknee", 0), d2.at("lankle", 0)
        self.assertAlmostEqual(math.dist(hip, knee), thigh, places=6)
        self.assertAlmostEqual(math.dist(hip, knee) + math.dist(knee, ankle), math.dist(hip, ankle), places=6)


if __name__ == "__main__":
    unittest.main()
