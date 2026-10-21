"""Make a camera motion (.vmd) that a person could have run: cut on the music, change the picture clearly at every cut,
hold, move at an even pace, and follow the dancer a little late.  Without MMD.

    python tools/operator_camera.py music DANCE.vmd MODEL.pmx MUSIC.json OUT.vmd [--report r.json] [--seed 0]
    python tools/operator_camera.py trace DANCE.vmd MODEL.pmx MUSIC.json TRACE.vmd OUT.vmd [--close-ups 0.3]
                                    [--report r.json] [--seed 0]
    python tools/operator_camera.py guard DANCE.vmd MODEL.pmx CAMERA.vmd OUT.vmd [--report r.json]
                                    [--window FIRST LAST DEGREES ...] [--lift-aim]

`music` plans the shots from the song (MUSIC.json: the beat grid and the sections) and the dance; `trace` keeps the cuts,
the lenses, the views and the moves of a camera traced from a live video (TRACE.vmd) and frames them again for this
scene; with --close-ups S it turns long-lens shots where the head is calm and a line is sung into chest and face shots
until they hold the share S of the frames.  Both write a key on every frame.

The camera.  A camera is its place in the world, the way it looks (yaw and pitch: the Y and X angles the MMD window
shows, X positive looking down), a roll, a vertical field of view (whole degrees: a VMD keeps the angle as an integer,
so moving in and out is done with the distance) and a reach (the window's distance: how far in front of the camera
the look-at point is).  fk.camera_position and fk.camera_direction read the written keys back to the same place and
direction (the tests check it).

The sizes.  The size of a shot is read from the share of the dancer's body, from the head top down, that the picture
shows (`visible`): face (head and shoulders) below 0.27, chest below 0.40, waist below 0.60, knee below 1.0, and the
whole body from 1.0 on: full while the body takes half the picture height or more, long below that.  On Sour's Rin
the shares are: chin 0.17, shoulders 0.21, chest 0.29, waist 0.37, hips 0.46, knees 0.68.  Closer sizes use longer
lenses (narrower fields), as a person shooting faces does, so a face is not drawn from arm's length.  A frame is
solved in the vertical plane of the line of sight (the head top on its row, the cut on the bottom edge) and checked
by projecting it back; from too far above for the lens no distance can make it, and the camera comes down to a
height that can (solve_distance says when there is none instead of rounding it away).

The cuts (plan_music).  On the section heads, the heads of the 8-bar phrases and the bar lines; every cut changes the
size by half or the view by 30 degrees, as planned and as the frames show it (cut_change: the dancer may have moved
since the shot was framed).  Busy moments (fast turns, jumps, a fast head) are shot wide; a sung line (sung for a
second or more in the shot) on a calm dancer is shot close, from within FACE_REACH of the way she faces so that her
eyes can find the camera.

The person behind the camera (FOLLOW).  The pan and the tilt follow a point of the dancer the way a person does:
they hold while she stays near the middle of the picture (the slack), see her late (the delay), judge by where she
is going (her drift over the last tenth of a second carried on), start only when she has stayed outside the slack
for a while (shorter as she nears the edge of the picture), so a swing already on its way back is left alone, then
turn at a pace that grows with how far she is off, never faster than a top pace, speeding up quickly and slowing down
gently, and brake in time to stop on her without swinging past.  Distances are counted in the picture (the
half-height of the picture is 1), so a long lens turns by fewer degrees for the same share of the picture.  Planned
moves of the camera itself (push in, pull out, a turn around her, rising and sinking) hold, ease into an even pace,
and ease out to hold again (move_profile); the camera's head turns with them, and the person corrects only what the
dancer does.

No low angle (the requester's rule: a camera below her hips showed what is under the skirt in a spin).  No camera is
ever below LOWEST or the dancer's hips plus HIP_MARGIN, and every frame whose picture shows her hips looks down at them
by MIN_LOOK_DOWN or more from where the camera stands on that frame: a height over the hips is not enough from far
away (a long lens 240 units off at hips + 3 looks at them level).  While her skirt flares (a spin faster than
FLARE_SPIN, and FLARE_HOLD frames around it) those frames look down by FLARE_LOOK_DOWN.  `guard` keeps another camera
(make_camera's) from the low angle on every frame, measured at her hips and at either hip joint (the far one is the
least looked down at): 4.5 degrees, 15 while her shoulders or her lower body turn fast, and what a --window asks where
her skirt flies higher than a turn alone lifts it.  Where a frame falls short the camera swings up round its own look-at
point (the same point, distance, heading and lens: only the tilt grows, so the picture keeps its subject and its size),
rising before and settling after on a cosine no faster than GUARD_RATE, staying up between two rises close together,
never across a cut.  The look-down holds on every subframe MMD draws at 480 fps (GUARD_SUBFRAMES): a camera with a key
on every frame stays over the frame's subframes while she moves on.  With --lift-aim the steep windows look less
down onto the street: the camera turns back up about its own eye by the largest share of the window's own tilt that
keeps her knees in the picture (the eye stays, so the look-down at her hips stays).
"""
import argparse
import dataclasses
import json
import math
import os
import random
import sys
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk, motion_edit  # noqa: E402
from mmd_cli.formats import pmx, vmd  # noqa: E402

FPS = 30
ASPECT = 16.0 / 9.0
CUT_CURVE = (127, 0, 127, 0)     # on the first key of a shot: the step, so a render above 30 fps draws nothing between shots
LOWEST = 10.0                    # no camera below this height: Rin's hips (a camera below them looks up into the skirt)
HIP_MARGIN = 1.0                 # and none below the dancer's own hips plus this, when she jumps
MIN_LOOK_DOWN = 4.5              # degrees: every frame whose picture shows her hips looks down at them this much
                                 # or more, however far the camera stands: hips + HIP_MARGIN alone is level from a
                                 # long lens 240 units away, and the skirt lifted by a spin and a kick showed what is
                                 # under it (review camera-v2: 99.4 s and 253.6 s of the live trace; D and A looked down
                                 # 3.3-6.8 degrees there and showed nothing).  The sizes that show the hips are planned
                                 # that high at the cut (SHOWS_HIPS); shoot checks every frame as it comes out (she may
                                 # walk away from the camera, a waist shot shows them too)
SHOWS_HIPS = ("long", "full", "knee")
LOOK_DOWN_ROUNDS = 12            # shoot raises a shot's camera at most this many times to look down at her hips
FLARE_SPIN = 450.0               # deg/s: her shoulders turning this fast flare the skirt out nearly level
FLARE_HOLD = 9                   # frames: the skirt flares up before the turn peaks and settles after it (0.3 s each way)
FLARE_LOOK_DOWN = 15.0           # degrees: while the skirt flares, the frames that show her hips look down at them this
                                 # much.  In the strongest spin (58.9 s, 696 deg/s at most) the current camera showed the
                                 # underwear looking down by 4.35-8 degrees and faintly at 10, not at 12, 15 or 20 (drawn
                                 # the same way, the look-down test of the fix round of camera-v2); 12 and a margin

# what the dancer is made of for the camera: the points of the body it frames (world positions per frame)
LANDMARKS = ("headtop", "eyes", "chin", "chest", "waist", "hips", "toes", "center", "lshoulder", "rshoulder")
# and, for guard, the hip joints (左足, 右足), a point a unit in front of 下半身 (its -Z turned with it: the way the
# lower body faces) and either toe (左つま先ＩＫ, 右つま先ＩＫ: with the hip joints, where her knees are about)
HIP_LANDMARKS = ("lhip", "rhip", "pelvis_front", "ltoe", "rtoe")

# sizes, from far to close.  cut: the share of the body (head top to toes) above the bottom edge; body: the body's share
# of the picture height (whole-body sizes); room: the picture's share above the head top; fov: the lens; eye: the
# camera's height against the eyes (units of the model, about 8 cm each)
SIZES = ("long", "full", "knee", "waist", "chest", "face")
SIZE_SPEC = {
    "long": {"body": 0.40, "room": 0.30, "fov": 30, "eye": -1.0},
    "full": {"body": 0.84, "room": 0.06, "fov": 27, "eye": -2.5},
    "knee": {"cut": 0.80, "room": 0.07, "fov": 24, "eye": -1.5},
    "waist": {"cut": 0.50, "room": 0.08, "fov": 20, "eye": -0.5},
    "chest": {"cut": 0.335, "room": 0.08, "fov": 17, "eye": 0.0},
    "face": {"cut": 0.235, "room": 0.05, "fov": 14, "eye": 0.0},
}
SIZE_EDGES = (("face", 0.27), ("chest", 0.40), ("waist", 0.60), ("knee", 1.0))
HIGH_RISE = {"long": 12.0, "full": 9.0, "knee": 7.0, "waist": 5.0, "chest": 4.0, "face": 3.0}   # above the head top

FOLLOW = {
    "delay": 0.2,            # s: seeing late; with the shortest wait below the reaction time is 0.3 s (veteran sports
                             # cameramen answered a player's turn in 0.23-0.37 s)
    "slack": (0.25, 0.15),   # how far off the middle she may be before the camera turns (half-heights; pan, tilt)
    "release": 0.04,         # the camera stops turning when she is this close to the middle again
    "gain": 4.0,             # 1/s: the pace grows with how far off she is
    "max_speed": 0.9,        # half-heights a second (14 deg/s at a field of 30; studio pans top out at 15-20 deg/s)
    "accel": 6.0,            # half-heights a second, per second, speeding up (92 deg/s2 at 30; studio pans stay under 200)
    "brake": 3.75,           # slowing down: 1.6 times gentler (the slowing down of a studio pan lasts 48-77 % longer)
    "trend": 0.1,            # s: the person sees where she is going from her drift over this time
    "look": 0.3,             # s: and judges by where that drift takes her this much later (predictable motion is
                             # followed with little delay: 54 ms against 221 ms for unpredictable, Parker et al. 2021)
    "persist": (0.1, 0.5),   # s: she must stay outside the slack this long (where she is and where she is going) before
                             # the camera starts: 0.5 s while she is well inside the picture, down to 0.1 s as she nears
                             # its edge (EDGE_NEAR of the way); a swing on its way back within that time is left alone
}
EDGE_NEAR = 0.7
EASE = 15                    # frames: a planned move reaches its even pace in half a second, and leaves it the same


# ---- the camera -------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class CameraFrame:
    position: Tuple[float, float, float]
    yaw: float                   # the window's Y angle, degrees
    pitch: float                 # the window's X angle, degrees, positive looking down
    roll: float                  # the window's Z angle, degrees
    fov: int                     # the vertical field of view, whole degrees
    reach: float                 # the window's distance: the look-at point is this far in front of the camera


def direction(yaw, pitch):
    """the unit vector a camera with these window angles looks along (as fk.camera_direction)"""
    y, p = math.radians(yaw), math.radians(pitch)
    return (-math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))


def aim(position, point):
    """(yaw, pitch): the window angles that turn a camera at `position` onto `point`"""
    d = [b - a for a, b in zip(position, point)]
    n = math.sqrt(sum(v * v for v in d))
    if n == 0.0:
        raise ValueError("the camera sits on the point it should look at")
    x, y, z = (v / n for v in d)
    return math.degrees(math.atan2(-x, z)), math.degrees(math.asin(max(-1.0, min(1.0, -y))))


def place_camera(look_at, yaw, pitch, reach):
    """where a camera is whose look-at point is `look_at` at the window distance `reach`"""
    d = direction(yaw, pitch)
    return tuple(a - reach * v for a, v in zip(look_at, d))


def project(position, yaw, pitch, roll, fov, point):
    """(u, v, depth) of a world point in the picture: v is 1 at the top edge and -1 at the bottom, u is right in the same
    unit (the edges are at +-16/9), depth along the line of sight.  The roll is not used (its sense in MMD is not
    measured; the cameras of this tool keep it at 0)"""
    d = direction(yaw, pitch)
    right = (d[2], 0.0, -d[0])
    n = math.hypot(right[0], right[2])
    if n < 1e-12:
        right = (1.0, 0.0, 0.0)
    else:
        right = (right[0] / n, 0.0, right[2] / n)
    up = (d[1] * right[2] - d[2] * right[1], d[2] * right[0] - d[0] * right[2], d[0] * right[1] - d[1] * right[0])
    rel = [p - c for p, c in zip(point, position)]
    depth = sum(a * b for a, b in zip(rel, d))
    t = math.tan(math.radians(fov / 2.0))
    if depth <= 1e-9:
        return float("nan"), float("nan"), depth
    return (sum(a * b for a, b in zip(rel, right)) / depth / t, sum(a * b for a, b in zip(rel, up)) / depth / t, depth)


def unwrap(yaws):
    """the angles made continuous: each differs from the one before by at most 180 degrees"""
    out = []
    for y in yaws:
        if out:
            y = out[-1] + ((y - out[-1] + 180.0) % 360.0) - 180.0
        out.append(float(y))
    return out


def _interpolation(curve):
    out = []
    for _ in vmd.CAMERA_CHANNELS:
        x1, y1, x2, y2 = vmd.check_curve(curve)
        out += [x1, x2, y1, y2]
    return bytes(out)


STEP_BYTES = _interpolation(CUT_CURVE)
LINEAR_BYTES = _interpolation(vmd.LINEAR_CURVE)


def camera_key(frame, cam, cut=False):
    """the VMD key of a camera: the window values (the look-at point `reach` in front of it), the step curve on a cut"""
    d = direction(cam.yaw, cam.pitch)
    look_at = tuple(p + cam.reach * v for p, v in zip(cam.position, d))
    values = {"pos": look_at, "distance": cam.reach, "rot": (cam.pitch, cam.yaw, cam.roll), "fov": cam.fov,
              "perspective": True}
    key = motion_edit.camera_key_from_ui(values, frame=frame)
    return dataclasses.replace(key, interpolation=STEP_BYTES if cut else LINEAR_BYTES)


def camera_motion(frames, cuts):
    """a key on every frame; the first frame of every shot (`cuts`, frame 0 among them) carries the step"""
    cuts = set(cuts)
    yaws = []
    for f, cam in enumerate(frames):
        # the yaw goes on continuously inside a shot: MMD turns linearly between two keys
        if f in cuts or not yaws:
            yaws.append(float(cam.yaw))
        else:
            yaws.append(unwrap([yaws[-1], cam.yaw])[1])
    keys = [camera_key(f, dataclasses.replace(cam, yaw=y), cut=f in cuts) for f, (cam, y) in enumerate(zip(frames, yaws))]
    return vmd.Motion.for_camera(cameras=keys)


# ---- the dancer -------------------------------------------------------------------------------------------------

class Dancer:
    """the landmarks of the dancer per frame (LANDMARKS: name -> [(x, y, z)]), and those of HIP_LANDMARKS when given
    (guard reads them); `sub` (name -> per frame the points at its subframes f + k/n, k = 0..n-1) where the dance gave
    them"""

    def __init__(self, tracks, sub=None):
        missing = [n for n in LANDMARKS if n not in tracks]
        if missing:
            raise ValueError("the dancer lacks %s" % ", ".join(missing))
        names = list(LANDMARKS) + [n for n in HIP_LANDMARKS if n in tracks]
        self.tracks = {n: [tuple(float(v) for v in p) for p in tracks[n]] for n in names}
        self.frames = len(self.tracks["headtop"])
        if any(len(t) != self.frames for t in self.tracks.values()):
            raise ValueError("the landmarks of the dancer have different lengths")
        self.sub = {}
        for name, per_frame in (sub or {}).items():
            if len(per_frame) != self.frames or len({len(points) for points in per_frame}) != 1:
                raise ValueError("the subframes of %s are not as many on every frame of the dancer" % name)
            self.sub[name] = [[tuple(float(v) for v in p) for p in points] for points in per_frame]

    def at(self, name, frame):
        return self.tracks[name][min(max(frame, 0), self.frames - 1)]

    def has(self, name):
        return name in self.tracks

    def over(self, name, frame, count=None):
        """where the landmark is over the frame: at its subframes frame + k/count (k = 0..count-1; count GUARD_SUBFRAMES
        unless given), those the dance gave, or else straight between this frame and the next (all a dancer of frames
        tells)"""
        count = GUARD_SUBFRAMES if count is None else count
        f = min(max(frame, 0), self.frames - 1)
        given = self.sub.get(name)
        if given is not None and len(given[f]) == count:
            return list(given[f])
        a, b = self.at(name, f), self.at(name, f + 1)
        return [tuple(x + (y - x) * k / float(count) for x, y in zip(a, b)) for k in range(count)]


# the bones that give the landmarks, and the offsets from them (Sour's Rin at rest: head bone 16.24, head top 19.5;
# 下半身 12.23, hip joints 10.66; the knee half way between hips and ankles is not needed by any size)
HEAD_TOP_ABOVE_HEAD = 19.5 - 16.243
HIPS_BELOW_WAIST = 12.225 - 10.658
FK_BONES = ("頭", "左目", "右目", "上半身2", "下半身", "センター", "左つま先ＩＫ", "右つま先ＩＫ", "左腕", "右腕")
HIP_BONES = ("左足", "右足")


def dancer_from_motion(model, motion, last=None, hip_joints=False, subframes=1):
    """the landmarks through the forward kinematics of mmd_cli/fk.py (no IK: the feet come from the IK bones); with
    hip_joints also HIP_LANDMARKS (the hip joints are where 左足 and 右足 turn: the leg IK turns them, it does not move
    them, so the forward kinematics puts them right; a model without those bones is refused), and with subframes n > 1
    the points guard looks down at (GUARD_POINTS) at every frame's subframes f + k/n from the dance's own curves"""
    track = fk.world_track(model, motion, list(FK_BONES) + (list(HIP_BONES) if hip_joints else []), 0, last)
    n = len(track["頭"])
    sub = None
    if hip_joints and subframes > 1:
        pose = fk.Pose(model, motion, ["下半身"] + list(HIP_BONES))
        sub = {name: [] for name in GUARD_POINTS}
        for f in range(n):
            worlds = [pose.at(f + k / float(subframes)) for k in range(subframes)]
            sub["hips"].append([(w["下半身"][0][0], w["下半身"][0][1] - HIPS_BELOW_WAIST, w["下半身"][0][2]) for w in worlds])
            sub["lhip"].append([w["左足"][0] for w in worlds])
            sub["rhip"].append([w["右足"][0] for w in worlds])
    out = {k: [] for k in LANDMARKS + (HIP_LANDMARKS if hip_joints else ())}
    for f in range(n):
        head = track["頭"][f][0]
        left, right = track["左目"][f][0], track["右目"][f][0]
        lower = track["下半身"][f][0]
        lt, rt = track["左つま先ＩＫ"][f][0], track["右つま先ＩＫ"][f][0]
        out["headtop"].append((head[0], head[1] + HEAD_TOP_ABOVE_HEAD, head[2]))
        out["eyes"].append(tuple((a + b) / 2.0 for a, b in zip(left, right)))
        out["chin"].append(head)
        out["chest"].append(track["上半身2"][f][0])
        out["waist"].append(lower)
        out["hips"].append((lower[0], lower[1] - HIPS_BELOW_WAIST, lower[2]))
        out["toes"].append(tuple((a + b) / 2.0 for a, b in zip(lt, rt)))
        out["center"].append(track["センター"][f][0])
        out["lshoulder"].append(track["左腕"][f][0])
        out["rshoulder"].append(track["右腕"][f][0])
        if hip_joints:
            out["lhip"].append(track["左足"][f][0])
            out["rhip"].append(track["右足"][f][0])
            front = fk.rotate(track["下半身"][f][1], (0.0, 0.0, -1.0))
            out["pelvis_front"].append(tuple(a + b for a, b in zip(lower, front)))
            out["ltoe"].append(lt)
            out["rtoe"].append(rt)
    return Dancer(out, sub)


# ---- sizes and framing ------------------------------------------------------------------------------------------

def classify(visible, body_share):
    """the size class from the share of the body seen from the head top down and the body's share of the picture"""
    if visible >= 1.0:
        return "long" if body_share < 0.5 else "full"
    for name, edge in SIZE_EDGES:
        if visible < edge:
            return name
    return "knee"


def seen(dancer, frame, cam):
    """what the picture shows of the dancer at `frame`: the share of the body from the head top down (`visible`), the
    body's share of the picture height, and where the head top and the eyes are (u right, v up; the edges at +-1 up
    and down, +-16/9 across)"""
    top = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, dancer.at("headtop", frame))
    toe = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, dancer.at("toes", frame))
    eyes = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, dancer.at("eyes", frame))
    span = top[1] - toe[1]
    visible = (top[1] + 1.0) / span if span > 1e-9 else 0.0
    return {"visible": visible, "body_share": span / 2.0, "headtop_v": top[1], "eyes_u": eyes[0], "eyes_v": eyes[1]}


def picture_span(size, headtop, toes):
    """(bottom, top, head row): the heights the picture covers at the dancer for `size`, and the row (v) of her head top"""
    spec = SIZE_SPEC[size]
    body = headtop - toes
    if "body" in spec:
        height = body / spec["body"]
        foot = 1.0 - spec["body"] - spec["room"]
        bottom = toes - foot * height
    else:
        height = spec["cut"] * body / (1.0 - spec["room"])
        bottom = headtop - spec["cut"] * body
    return bottom, bottom + height, 1.0 - 2.0 * spec["room"]


def solve_distance(top, bottom, camera_height, top_row, fov):
    """(horizontal distance, pitch): where a camera at `camera_height` must stand, and how it must tilt, so that the
    height `top` lands on the row `top_row` and the height `bottom` on the bottom edge (exact in the vertical plane
    of the line of sight); None when no distance can do it from that height.

    Seen from the camera the two heights span an angle that must equal the lens's angle from the bottom edge to the
    row.  From between the two heights that angle falls from 180 degrees to 0 as the camera backs off, so there is
    always one distance.  From above both (or below both) it rises from 0 to its largest at sqrt(a * b) (a and b the
    heights over the camera) and falls again: there is a distance only when that largest angle reaches the one
    needed, and then the far one is taken (the gentler view)."""
    half = math.radians(fov / 2.0)
    want = math.atan(top_row * math.tan(half)) + half
    a, b = top - camera_height, bottom - camera_height

    def spanned(r):
        return math.atan2(a, r) - math.atan2(b, r)
    if a >= 0.0 >= b and a != b:
        lo, hi = 1e-6, 1e6
    else:
        peak = math.sqrt(a * b)
        if spanned(peak) < want:
            return None
        lo, hi = peak, 1e6
    if spanned(hi) > want:
        return None
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if spanned(mid) > want:
            lo = mid
        else:
            hi = mid
    r = math.sqrt(lo * hi)
    # the line of sight rises half the field above the bottom height's direction; the window's X is minus that rise
    pitch = -math.degrees(math.atan2(bottom - camera_height, r) + half)
    return r, pitch


def anchor(dancer, frame, size):
    """the dancer's point on the floor plan the camera centres: the eyes for a face, between the eyes and the chest for
    chest and waist shots (the upper body: a head leaning in the dance is not followed as far), between the eyes and
    the center for the rest"""
    e = dancer.at("eyes", frame)
    if size == "face":
        return e[0], e[2]
    c = dancer.at("chest" if size in ("waist", "chest") else "center", frame)
    return (e[0] + c[0]) / 2.0, (e[2] + c[2]) / 2.0


def lowest_height(dancer, frames):
    """the lowest the camera may sit over `frames`: LOWEST, and the dancer's highest hips plus HIP_MARGIN"""
    return max([LOWEST] + [dancer.at("hips", f)[1] + HIP_MARGIN for f in frames])


def flare_frames(dancer):
    """per frame whether her skirt flares: her shoulders turn faster than FLARE_SPIN (over the frames on each side),
    or did or will within FLARE_HOLD frames.  Kept on the dancer once worked out"""
    cached = getattr(dancer, "_flare", None)
    if cached is not None:
        return cached
    n = dancer.frames
    yaws = unwrap([math.degrees(math.atan2(dancer.at("lshoulder", f)[2] - dancer.at("rshoulder", f)[2],
                                           dancer.at("lshoulder", f)[0] - dancer.at("rshoulder", f)[0])) for f in range(n)])
    fast = []
    for f in range(n):
        a, b = max(f - 1, 0), min(f + 1, n - 1)
        fast.append(b > a and abs(yaws[b] - yaws[a]) / (b - a) * FPS > FLARE_SPIN)
    flare = [any(fast[max(0, f - FLARE_HOLD):f + FLARE_HOLD + 1]) for f in range(n)]
    dancer._flare = flare
    return flare


def look_down_needed(dancer, frame):
    """how far the camera must look down at her hips on `frame` when its picture shows them: FLARE_LOOK_DOWN while her
    skirt flares, MIN_LOOK_DOWN otherwise"""
    return FLARE_LOOK_DOWN if flare_frames(dancer)[min(max(frame, 0), dancer.frames - 1)] else MIN_LOOK_DOWN


def hips_look_down(dancer, frame, cam):
    """(shown, degrees, short): whether the picture of `cam` shows her hips at `frame`, how far the camera looks down at
    them (its height over them against their distance on the floor), and how much higher it would have to stand to look
    down at them as far as that frame needs (look_down_needed; 0 when it does)"""
    hips = dancer.at("hips", frame)
    u, v, depth = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, hips)
    shown = depth > 0 and math.isfinite(u) and abs(u) <= ASPECT and abs(v) <= 1.0
    d = math.hypot(cam.position[0] - hips[0], cam.position[2] - hips[2])
    angle = math.degrees(math.atan2(cam.position[1] - hips[1], d))
    short = max(0.0, hips[1] + d * math.tan(math.radians(look_down_needed(dancer, frame))) - cam.position[1])
    return shown, angle, short


def frame_size(dancer, frame, size, yaw, high=False, fov=None, height=None, frames=None, heights=None, look_reach=1.0,
               at_least=None):
    """the camera that frames the dancer at `frame` as `size` from the direction `yaw` (the window's Y angle):
    at the size's eye height (or `height`, or above her head when `high`), never below lowest_height over `frames`
    (default: the frame itself) nor below `at_least`, and for a size that shows her hips high enough to look down at
    them by MIN_LOOK_DOWN from its distance times `look_reach` (the farthest the shot's move takes it).  `heights`
    (head top, toes, eyes) replaces the frame's own (a steadier reading)"""
    spec = SIZE_SPEC[size]
    fov = int(fov if fov is not None else spec["fov"])
    if heights is None:
        heights = (dancer.at("headtop", frame)[1], dancer.at("toes", frame)[1], dancer.at("eyes", frame)[1])
    headtop, toes, eyes = heights
    bottom, top, top_row = picture_span(size, headtop, min(toes, headtop - 1.0))
    if height is None:
        height = headtop + HIGH_RISE[size] if high else eyes + spec["eye"]
    # never steeper than the size's view from above (a traced camera may stand far up), never below her hips; a height
    # the shot needs to look down at her hips (at_least, from shoot) comes before the cap: from far away it is not steep
    height = min(height, headtop + HIGH_RISE[size])
    low = lowest_height(dancer, frames if frames is not None else [frame])
    if at_least is not None:
        low = max(low, at_least)
    height = max(height, low)
    solved = solve_distance(headtop, bottom, height, top_row, fov)
    middle = (headtop + bottom) / 2.0
    for _ in range(200):
        if solved is not None:
            break
        # too steep from here for this lens: the camera comes towards the heights of the picture, where every frame
        # can be made (never below the dancer's hips)
        height = max(middle + (height - middle) * 0.9, low)
        solved = solve_distance(headtop, bottom, height, top_row, fov)
    if solved is None:
        raise ValueError("no camera height frames %s with a field of %d degrees" % (size, fov))
    if size in SHOWS_HIPS:
        # the skirt: up until the hips are seen from MIN_LOOK_DOWN above at the farthest distance of the shot (the solve
        # moves the camera back a little as it rises, so a few rounds)
        hips_top = max(dancer.at("hips", f)[1] for f in (frames if frames is not None else [frame]))
        slope = math.tan(math.radians(MIN_LOOK_DOWN))
        for _ in range(12):
            need = hips_top + solved[0] * look_reach * slope
            if height >= need - 1e-6:
                break
            raised = solve_distance(headtop, bottom, need + 1e-3, top_row, fov)
            if raised is None:
                raise ValueError("no camera height frames %s with a field of %d degrees looking down at the hips"
                                 % (size, fov))
            height, solved = need + 1e-3, raised
    r, pitch = solved
    ax, az = anchor(dancer, frame, size)
    position = (ax + r * math.sin(math.radians(yaw)), height, az - r * math.cos(math.radians(yaw)))
    reach = r / max(math.cos(math.radians(pitch)), 1e-6)
    # the frame as solved, checked by projecting the two heights back
    v_top = project(position, yaw, pitch, 0.0, fov, (ax, headtop, az))[1]
    v_bottom = project(position, yaw, pitch, 0.0, fov, (ax, bottom, az))[1]
    if abs(v_top - top_row) > 1e-4 or abs(v_bottom + 1.0) > 1e-4:
        raise ValueError("the frame of %s does not come out as solved (rows %.4f and %.4f)" % (size, v_top, v_bottom))
    return CameraFrame(position, float(yaw), pitch, 0.0, fov, reach)


# ---- the person behind the camera -------------------------------------------------------------------------------

def operate(targets, fovs, start, follow=FOLLOW, fps=FPS):
    """per frame the (yaw, pitch) of a camera worked by a person towards `targets` (the (yaw, pitch) that would put the
    dancer's point in the middle), from `start`: see the module docstring.  The person judges by where she is going:
    the error seen (after the reaction time) carried on by its change over the last `trend` seconds for `look` seconds.
    The camera starts when that stays outside the slack for `persist` seconds, so a swing already on its way back is
    left alone, and it brakes as soon as she is seen coming back to the middle"""
    delay = int(round(follow["delay"] * fps))
    trend = max(1, int(round(follow["trend"] * fps)))
    shortest, longest = follow["persist"]
    yaw, pitch = float(start[0]), float(start[1])
    moving, speed, outside = [False, False], [0.0, 0.0], [0, 0]
    seen_errors = [[], []]
    step_up, step_down = follow["accel"] / fps, follow["brake"] / fps
    out = []
    for i in range(len(targets)):
        seen_target = targets[max(0, i - delay)]
        t = math.tan(math.radians(fovs[i] / 2.0))
        current = [yaw, pitch]
        for axis in (0, 1):
            off = seen_target[axis] - current[axis]
            if axis == 0:
                off = ((off + 180.0) % 360.0) - 180.0
            off = max(-80.0, min(80.0, off))
            e = math.tan(math.radians(off)) / t
            history = seen_errors[axis]
            history.append(e)
            rate = (e - history[-1 - trend]) * fps / trend if len(history) > trend else 0.0
            ahead = e + rate * follow["look"]
            slack = follow["slack"][axis]
            outside[axis] = outside[axis] + 1 if abs(e) > slack and abs(ahead) > slack else 0
            # the nearer she is to the edge of the picture, the sooner the person answers
            near = EDGE_NEAR * (ASPECT if axis == 0 else 1.0)
            urgency = max(0.0, min(1.0, (abs(e) - slack) / (near - slack)))
            wait = int(round((longest - (longest - shortest) * urgency) * fps))
            if not moving[axis] and outside[axis] > wait:
                moving[axis] = True
            want = 0.0
            if moving[axis]:
                if abs(e) < follow["release"] and abs(speed[axis]) <= step_down:
                    moving[axis] = False
                elif ahead * e > 0.0:
                    # the pace that still stops on her with the gentler braking; none while she is seen coming back
                    pace = min(follow["max_speed"], follow["gain"] * abs(ahead), math.sqrt(2.0 * follow["brake"] * abs(e)))
                    want = math.copysign(pace, e)
            # speeding up (the pace growing in its own direction) is quick, slowing down gentle
            up = abs(want) > abs(speed[axis]) and want * speed[axis] >= 0.0
            step = step_up if up else step_down
            speed[axis] += max(-step, min(step, want - speed[axis]))
            current[axis] += math.degrees(math.atan(speed[axis] / fps * t))
        yaw, pitch = current
        out.append((yaw, pitch))
    return out


def lag_seconds(target, follower, max_shift=60, fps=FPS):
    """the delay (s) at which `follower` best matches `target` (least squares over the frames both cover)"""
    best, best_shift = None, 0
    n = len(target)
    for s in range(0, max_shift + 1):
        pairs = [(follower[i], target[i - s]) for i in range(s, n)]
        if not pairs:
            break
        err = sum((a - b) ** 2 for a, b in pairs) / len(pairs)
        if best is None or err < best:
            best, best_shift = err, s
    return best_shift / float(fps)


def move_profile(frames, start, end, ease=EASE):
    """the share of a planned move done at each frame 0..frames-1: 0 up to `start`, 1 from `end` on, and between them a
    pace that rises gently (half a cosine) for `ease` frames, stays even, and falls the same way (shorter moves ease
    all the way)"""
    duration = float(end - start)
    if duration <= 0:
        return [0.0 if f < end else 1.0 for f in range(frames)]
    ramp = min(float(ease), duration / 2.0)
    top = 1.0 / (duration - ramp)
    out = []
    for f in range(frames):
        t = f - start
        if t <= 0:
            out.append(0.0)
        elif f >= end:
            out.append(1.0)
        elif t < ramp:
            out.append(top * (t / 2.0 - ramp / (2.0 * math.pi) * math.sin(math.pi * t / ramp)))
        elif t <= duration - ramp:
            out.append(top * (ramp / 2.0 + (t - ramp)))
        else:
            r = duration - t
            out.append(1.0 - top * (r / 2.0 - ramp / (2.0 * math.pi) * math.sin(math.pi * r / ramp)))
    return out


# ---- the music --------------------------------------------------------------------------------------------------

KINDS = ("intro", "verse", "build", "chorus", "interlude", "break", "outro")
SUNG_LINE = 2.0                  # s: how long a sung line given by its start alone is taken to last


@dataclasses.dataclass
class Music:
    """the beat grid and the sections of a song (MUSIC.json): beat k sounds at first_beat + k * period seconds, beat 0
    starts a bar, and every section starts on a bar line"""
    first_beat: float
    period: float
    beats_per_bar: int
    last_frame: int
    sections: List[Tuple[int, str, str]]                               # (beat of the head, name, kind)
    lines: list = dataclasses.field(default_factory=list)             # s: (start, end or None) of the sung lines
    hooks: List[float] = dataclasses.field(default_factory=list)      # s: the hooks (the title word with its flare)

    def __post_init__(self):
        # a line is (start, end) or its start alone
        self.lines = [(float(x[0]), None if x[1] is None else float(x[1])) if isinstance(x, (list, tuple))
                      else (float(x), None) for x in self.lines]

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            raise ValueError("the music is a JSON object")
        missing = [k for k in ("first_beat", "period", "beats_per_bar", "last_frame", "sections") if k not in data]
        if missing:
            raise ValueError("the music lacks %s" % ", ".join(missing))
        period, bpb, last = data["period"], data["beats_per_bar"], data["last_frame"]
        if not (isinstance(period, (int, float)) and period > 0):
            raise ValueError("period is the seconds of a beat, above 0")
        if not (isinstance(bpb, int) and bpb >= 1) or not (isinstance(last, int) and last >= 1):
            raise ValueError("beats_per_bar and last_frame are whole numbers of 1 or more")
        sections = []
        for item in data["sections"]:
            if not (isinstance(item, (list, tuple)) and len(item) == 3 and isinstance(item[0], int)):
                raise ValueError("a section is [beat, name, kind], not %r" % (item,))
            beat, name, kind = item
            if kind not in KINDS:
                raise ValueError("a section's kind is one of %s, not %r" % (", ".join(KINDS), kind))
            if beat % bpb:
                raise ValueError("section %r starts on beat %d, not on a bar line" % (name, beat))
            sections.append((beat, str(name), kind))
        if not sections or sections[0][0] != 0:
            raise ValueError("the first section starts on beat 0")
        if any(b[0] <= a[0] for a, b in zip(sections, sections[1:])):
            raise ValueError("the sections must come in order")
        lines = []
        for item in data.get("lines", []):
            if isinstance(item, (list, tuple)):
                if len(item) != 2 or not item[1] > item[0]:
                    raise ValueError("a sung line is its start or [start, end] with the end after the start, not %r" % (item,))
                lines.append((float(item[0]), float(item[1])))
            else:
                lines.append((float(item), None))
        return cls(float(data["first_beat"]), float(period), bpb, last, sections, lines,
                   [float(t) for t in data.get("hooks", [])])

    def sung(self, start, end):
        """whether the frames start..end are sung: a line is sung in them for a second or more, or over half of them
        when they are shorter (a line without its end is taken to last SUNG_LINE seconds).  A line that only starts
        at the very end of a shot belongs to the next one"""
        need = min(1.0 * FPS, 0.5 * (end - start + 1))
        for a, b in self.lines:
            b = a + SUNG_LINE if b is None else b
            if min(end + 1, b * FPS) - max(start, a * FPS) >= need:
                return True
        return False

    def beat_frame(self, beat):
        return int(round((self.first_beat + beat * self.period) * FPS))

    def bar_frame(self, bar):
        return self.beat_frame(bar * self.beats_per_bar)

    def section_at(self, frame):
        """(name, kind) of the section the frame lies in"""
        name, kind = self.sections[0][1], self.sections[0][2]
        for beat, n, k in self.sections:
            if frame >= self.beat_frame(beat):
                name, kind = n, k
        return name, kind


# ---- the dancer's moments ---------------------------------------------------------------------------------------

BUSY = {"turn": 150.0, "jump": 1.0, "head": 12.0}  # deg in a second; units above her 2-s median; units/s (90 % of the shot)
CALM_HEAD = 8.0                                   # units/s: the head's 90 % point under this is calm enough for a close shot


class Moments:
    """per frame what the dancer does that matters to the camera: the head's speed (units/s), how far the shoulders
    turn within the next second (degrees), how high the body is above its own 2-second median (a jump)"""

    def __init__(self, dancer):
        n = dancer.frames
        head = dancer.tracks["chin"]
        self.head_speed = [0.0] + [math.dist(head[f], head[f - 1]) * FPS for f in range(1, n)]
        yaws = []
        for f in range(n):
            l, r = dancer.at("lshoulder", f), dancer.at("rshoulder", f)
            yaws.append(math.degrees(math.atan2(l[2] - r[2], l[0] - r[0])))
        # the window's Y of a camera straight in front of her: the line of her shoulders turned by a right angle is
        # the way she faces, which the window's Y measures the same way as that line (0 for the front of the stage)
        self.facing = list(yaws)
        yaws = unwrap(yaws)
        self.turn = [abs(yaws[min(n - 1, f + FPS)] - yaws[f]) for f in range(n)]
        lift = [p[1] for p in dancer.tracks["center"]]
        self.jump = []
        for f in range(n):
            around = sorted(lift[max(0, f - FPS):f + FPS + 1])
            self.jump.append(lift[f] - around[len(around) // 2])

    def of(self, start, end):
        frames = range(max(0, start), min(end, len(self.head_speed) - 1) + 1)
        speeds = sorted(self.head_speed[f] for f in frames)
        p90 = speeds[min(len(speeds) - 1, int(0.9 * (len(speeds) - 1) + 0.5))]
        turn = max(self.turn[f] for f in frames)
        jump = max(self.jump[f] for f in frames)
        busy = turn > BUSY["turn"] or jump > BUSY["jump"] or p90 > BUSY["head"]
        x = sum(math.cos(math.radians(self.facing[f])) for f in frames)
        z = sum(math.sin(math.radians(self.facing[f])) for f in frames)
        return {"head_p90": p90, "turn": turn, "jump": jump, "busy": busy, "calm": not busy and p90 < CALM_HEAD,
                "facing": math.degrees(math.atan2(z, x))}

    def tail_move(self, start, end, window):
        """where a fast move of her head that is under way in the last `window` frames of start..end begins (its first
        frame: the head faster than CALM_HEAD on two frames running, followed back while it stays faster), or None.
        A close shot is calm by the 90 % point of its frames, so its last few may be a move into the next part of the
        dance (197 s: the head turning into chorus 3 in the last 0.3 s of a face shot, review camera-v2)"""
        n = len(self.head_speed)

        def fast(f):
            return self.head_speed[min(f, n - 1)] > CALM_HEAD
        first = next((f for f in range(max(start, end - window + 1), end + 1) if fast(f) and fast(f + 1)), None)
        if first is None:
            return None
        while first - 1 >= start and fast(first - 1):
            first -= 1
        return first


# ---- the plan of the shots --------------------------------------------------------------------------------------

@dataclasses.dataclass
class Shot:
    start: int
    end: int                     # both included; the next shot starts at end + 1
    size: str
    yaw: float                   # the window's Y angle at the cut
    fov: int
    high: bool = False
    height: float = None         # the camera's height (None: the size's height)
    move: str = "hold"           # hold, push, pull, arc, crane
    move_start: int = 0
    move_end: int = 0
    amount: float = 0.0          # push and pull: the distance at the end over the distance at the start; arc: degrees
                                 # round her; crane: units up (negative down)
    yaw_path: List[float] = None     # trace: the window's Y on every frame of the shot (replaces an arc)
    reach_path: List[float] = None   # trace: the distance on every frame over the first (replaces a push or a pull)
    section: str = ""
    kind: str = ""
    source: str = "music"
    early: int = 0                   # frames the shot starts before its bar line: a close shot before it was cut onto
                                     # her move (cut on action, a beat at most)


PHRASE_BARS = 8
SHOT_BARS = {"intro": (4, 4), "verse": (4, 4), "build": (2, 2, 2, 2), "chorus": (2, 2, 2, 1, 1), "interlude": (4, 4),
             "break": (4, 4), "outro": (4, 4)}
SIZE_ORDER = {"intro": ("long", "chest", "full", "waist"), "verse": ("full", "waist", "knee", "chest"),
              "build": ("knee", "chest", "full", "waist"), "chorus": ("full", "waist", "long", "chest", "knee", "face"),
              "interlude": ("long", "knee", "full", "waist"), "break": ("waist", "face", "full", "chest"),
              "outro": ("full", "chest", "long", "waist")}
WIDE = ("long", "full", "knee")
YAWS = (0.0, 30.0, -30.0, 45.0, -45.0, 15.0, -15.0)
CLEAR_RATIO, CLEAR_TURN = 1.5, 30.0          # a cut changes the size by half or the view by 30 degrees (the 30-degree rule)
MOVES = {"long": (("hold", 3), ("push", 2), ("pull", 1), ("arc", 2), ("crane", 1)),
         "short": (("hold", 2), ("push", 1), ("arc", 1))}
MOVE_AMOUNT = {"push": 0.85, "pull": 1.18, "crane": 3.0}
EYES_OUT = 0.02                              # a shot whose eyes leave the picture longer than this share goes wider


def size_height(size):
    """the picture's height at the dancer for `size`, for Rin standing (head top 19.5, toes 0.1)"""
    bottom, top, _ = picture_span(size, 19.5, 0.1)
    return top - bottom


def size_ratio(a, b):
    ha, hb = size_height(a), size_height(b)
    return max(ha, hb) / min(ha, hb)


def clear_cut(prev, size, yaw):
    """whether the cut from `prev` (a Shot) to `size` seen from `yaw` changes the picture clearly, as planned"""
    turn = abs(((yaw - prev.yaw) + 180.0) % 360.0 - 180.0)
    return size_ratio(prev.size, size) >= CLEAR_RATIO or turn >= CLEAR_TURN


def cut_change(dancer, frame, before, after):
    """(size ratio, turn) across a cut at `frame` as the frames show it: the dancer's body in the picture before (the
    last frame of the shot before, camera `before`) and after (camera `after`), larger over smaller, and the angle in
    degrees between the two cameras seen from her center"""
    a, b = seen(dancer, frame - 1, before), seen(dancer, frame, after)
    ratio = max(a["body_share"], b["body_share"]) / max(min(a["body_share"], b["body_share"]), 1e-9)
    mid = dancer.at("center", frame)
    va = [p - q for p, q in zip(before.position, mid)]
    vb = [p - q for p, q in zip(after.position, mid)]
    cosine = sum(x * y for x, y in zip(va, vb)) / math.sqrt(sum(x * x for x in va) * sum(y * y for y in vb))
    return ratio, math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def clear_on_frames(dancer, frame, before, after):
    ratio, turn = cut_change(dancer, frame, before, after)
    return ratio >= CLEAR_RATIO or turn >= CLEAR_TURN


def music_cuts(music):
    """(start, end, section name, kind, first beat, bars) of every shot: each section in phrases of 8 bars from its head,
    each phrase in the shots of SHOT_BARS (a piece left at the very end of the song joins the shot before it)"""
    out = []
    heads = list(music.sections)
    bpb = music.beats_per_bar
    for i, (beat0, name, kind) in enumerate(heads):
        last = music.beat_frame(heads[i + 1][0]) - 1 if i + 1 < len(heads) else music.last_frame
        phrase = beat0 // bpb
        starts = []
        while music.bar_frame(phrase) <= last:
            bar = phrase
            for length in SHOT_BARS[kind]:
                if music.bar_frame(bar) > last or bar >= phrase + PHRASE_BARS:
                    break
                starts.append((bar, length))
                bar += length
            phrase += PHRASE_BARS
        for j, (b, length) in enumerate(starts):
            start = music.bar_frame(b)
            end = music.bar_frame(starts[j + 1][0]) - 1 if j + 1 < len(starts) else last
            out.append([start, end, name, kind, b * bpb, length])
    half_bar = (music.bar_frame(1) - music.bar_frame(0)) / 2.0
    if len(out) > 1 and out[-1][1] - out[-1][0] + 1 < half_bar:
        out[-2][1] = out[-1][1]
        out.pop()
    return [tuple(o) for o in out]


def _weighted(rng, choices):
    total = sum(w for _, w in choices)
    r = rng.random() * total
    for item, w in choices:
        r -= w
        if r < 0:
            return item
    return choices[-1][0]


def _wider(size):
    return SIZES[max(0, SIZES.index(size) - 1)]


MAX_BARS = {"face": 2, "chest": 4}             # a face shot lasts 2 bars at most, a chest shot 4 (close shots are short)
FACE_REACH = 20.0      # degrees: a close shot on a sung line comes from no further round than this from the way she faces,
                       # where her eyes can reach the camera (the gaze tool looks at it within 18 degrees of her face)


def _candidates(kind, index, moments, bars):
    order = list(SIZE_ORDER[kind])
    order = order[index % len(order):] + order[:index % len(order)]
    if moments["busy"]:
        order = ["full", "knee", "long"] if index % 2 == 0 else ["knee", "full", "long"]
    elif moments.get("sung") and moments["calm"]:
        order = ["face", "chest", "waist"] + [s for s in order if s not in ("face", "chest", "waist")]
    elif moments.get("sung"):
        order = ["waist"] + [s for s in order if s != "waist"]
    return [s for s in order if bars <= MAX_BARS.get(s, bars)]


HEAD_OUT = 0.08                              # a whole-body shot may lose her head top this share of the time (a jump)


def eyes_out_share(dancer, shot, frames):
    """the share of the shot's frames where the eyes are outside the picture; for a whole-body size (full, long), 1
    when it loses the head top more than HEAD_OUT of the time (it is no longer that size; a closer size may lose the
    head top, as when she jumps)"""
    out, head = 0, 0
    for i, cam in enumerate(frames):
        s = seen(dancer, shot.start + i, cam)
        out += not math.isfinite(s["eyes_u"]) or abs(s["eyes_u"]) > 0.98 * ASPECT or abs(s["eyes_v"]) > 0.98
        head += s["headtop_v"] > 1.0
    if "body" in SIZE_SPEC[shot.size] and head > HEAD_OUT * len(frames):
        return 1.0
    return out / float(len(frames))


def _move_for(rng, shot, music, beat0, bars, arc_sign, moments=None):
    """the planned move of a shot: none in a shot of one bar; else drawn (MOVES) between beats inside the shot, and none
    while she spins, jumps or moves her head fast in that time (a dance DP: when the dancers move, the camera is still)"""
    if bars >= 3:
        choices = MOVES["long"]
        start, end = music.beat_frame(beat0 + music.beats_per_bar), music.beat_frame(beat0 + (bars - 1) * music.beats_per_bar)
    elif bars >= 2:
        choices = MOVES["short"]
        start, end = music.beat_frame(beat0 + 2), music.beat_frame(beat0 + 2 * music.beats_per_bar - 2)
    else:
        return "hold", 0, 0, 0.0
    if shot.size in ("chest", "face"):
        choices = (("hold", 2), ("push", 1))
    move = _weighted(rng, choices)
    if move == "hold" or (moments is not None and moments.of(start, end)["busy"]):
        return "hold", 0, 0, 0.0
    if move == "arc":
        amount = (15.0 if bars >= 3 else 8.0) * arc_sign
    elif move == "crane":
        amount = -MOVE_AMOUNT["crane"] if shot.high else MOVE_AMOUNT["crane"]
    else:
        amount = MOVE_AMOUNT[move]
    return move, start, end, amount


def plan_music(music, dancer, seed=0, follow=FOLLOW):
    """the shots of `music` for `dancer`: cut on the sections, the 8-bar phrases and the bar lines (music_cuts), each a
    size from its section's order (SIZE_ORDER) that changes the picture clearly from the shot before (CLEAR_RATIO or
    CLEAR_TURN), wide where she spins, jumps or moves her head fast, close on a sung line while she is calm, and wider
    again while the person behind the camera would lose her eyes (EYES_OUT).  A close shot that would end in a fast
    move of her head (Moments.tail_move) is cut onto the move, up to a beat before the bar line (the next shot starts
    `early`: a cut on action, as the live switching cuts 0-1 beat before the bar line); a move that starts earlier than
    that leaves the shot no close size.  Moves start and end on beats inside the shot, holding before and after"""
    rng = random.Random(seed)
    moments = Moments(dancer)
    shots, prev, prev_last, arc_sign, yaw_turn = [], None, None, 1.0, rng.randrange(len(YAWS))
    count_in_section, section_name = 0, None
    bar_frames = float(music.bar_frame(1) - music.bar_frame(0))
    beat = max(1, int(round(music.period * FPS)))
    plan = music_cuts(music)
    next_start = None
    for index, (start, end, name, kind, beat0, bars) in enumerate(plan):
        early = 0
        if next_start is not None:
            early, start, next_start = start - next_start, next_start, None
        if name != section_name:
            section_name, count_in_section = name, 0
        # the whole bars the shot really has (the last shot of the song may be cut short or run long)
        bars = int((end - start + 1) / bar_frames + 0.25)
        m = moments.of(start, end)
        m["sung"] = music.sung(start, end)
        # a close shot ends calm: where her head moves fast into its last beat the cut comes onto the move (never in
        # the song's last shot, which has no shot after it to take the move)
        onset = moments.tail_move(start, end, beat)
        close_end = end if onset is None else onset - 1
        close_ok = onset is None or (onset >= end - beat + 1 and index + 1 < len(plan))
        chosen = None
        for size in _candidates(kind, count_in_section, m, bars):
            if size in ("face", "chest") and not close_ok:
                continue
            # the yaws in turn, from the next in the rotation: the first that makes a clear cut, planned and on the frames.
            # A close shot on a sung line takes the yaws nearest the way she faces first (her eyes can reach the camera)
            order = [YAWS[(yaw_turn + k) % len(YAWS)] for k in range(len(YAWS))]
            if size in ("face", "chest") and m.get("sung") and m["calm"]:
                def off(y):
                    return abs(((y - m["facing"]) + 180.0) % 360.0 - 180.0)
                order = sorted([y for y in order if off(y) <= FACE_REACH], key=off)
            for yaw in order:
                if prev is not None and not clear_cut(prev, size, yaw):
                    continue
                high = size in ("long", "full") and ((kind in ("interlude", "outro") and count_in_section == 0)
                                                     or rng.random() < 0.15)
                shot = Shot(start, close_end if size in ("face", "chest") else end, size, yaw, SIZE_SPEC[size]["fov"],
                            high=high, section=name, kind=kind, early=early)
                shot.move, shot.move_start, shot.move_end, shot.amount = _move_for(rng, shot, music, beat0, bars,
                                                                                   arc_sign, moments)
                frames = shoot(dancer, shot, follow)
                while eyes_out_share(dancer, shot, frames) > EYES_OUT and shot.size != "long":
                    wider = _wider(shot.size)
                    # a shot widened out of the close sizes keeps to the bar line
                    shot = dataclasses.replace(shot, size=wider, fov=SIZE_SPEC[wider]["fov"],
                                               end=shot.end if wider in ("face", "chest") else end)
                    frames = shoot(dancer, shot, follow)
                if prev is not None and not (clear_cut(prev, shot.size, shot.yaw)
                                             and clear_on_frames(dancer, start, prev_last, frames[0])):
                    continue
                chosen, prev_last = shot, frames[-1]
                break
            if chosen is not None:
                break
        if chosen is None:
            raise ValueError("no size makes a clear cut at frame %d" % start)
        if chosen.end < end:
            next_start = chosen.end + 1
        if chosen.move == "arc":
            arc_sign = -arc_sign
        yaw_turn = (YAWS.index(chosen.yaw) + 1 + rng.randrange(2)) % len(YAWS)
        shots.append(chosen)
        prev = chosen
        count_in_section += 1
    return shots


# ---- shooting a shot --------------------------------------------------------------------------------------------

STEADY = 15                       # frames: the dancer's heights for the framing are their medians over the cut's half second


def _median(values):
    v = sorted(values)
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2.0


def _carrier(dancer, frame, size):
    """the height that carries the picture's middle: the head top for sizes that cut the body, the middle of the
    body for whole-body sizes"""
    top = dancer.at("headtop", frame)[1]
    if "body" in SIZE_SPEC[size]:
        return (top + dancer.at("toes", frame)[1]) / 2.0
    return top


def shoot(dancer, shot, follow=FOLLOW):
    """the CameraFrame of every frame of the shot: framed at the cut (frame_size on the heights of its first half
    second), the camera's place moved by the planned move (or the trace's paths), never below lowest_height, and
    turned by the person behind it (operate) towards the point of her body the cut put in the middle.  Every frame
    whose picture shows her hips looks down at them by MIN_LOOK_DOWN: where one does not (she walked away from the
    camera, a waist shot from far away, a crane coming down), the whole shot is shot again with a floor under its
    camera at the height that frame needed, until no frame lacks anything (a raised camera stands at another
    distance)"""
    at_least = None
    for _ in range(LOOK_DOWN_ROUNDS):
        out = _shoot_from(dancer, shot, follow, at_least)
        need = None
        for i, cam in enumerate(out):
            shown, _, lack = hips_look_down(dancer, shot.start + i, cam)
            if shown and lack > 1e-6:
                need = max(need if need is not None else -math.inf, cam.position[1] + lack)
        if need is None:
            return out
        at_least = max(at_least if at_least is not None else -math.inf, need + 1e-3)
    raise ValueError("the camera of the shot at frame %d does not come to look down at her hips by %.1f degrees"
                     % (shot.start, MIN_LOOK_DOWN))


def _shoot_from(dancer, shot, follow, at_least):
    """shoot once with no camera below `at_least` (None: no such floor)"""
    frames = list(range(shot.start, shot.end + 1))
    first = frames[:STEADY]
    heights = (_median(dancer.at("headtop", f)[1] for f in first), _median(dancer.at("toes", f)[1] for f in first),
               _median(dancer.at("eyes", f)[1] for f in first))
    if shot.reach_path is not None:
        look_reach = max(shot.reach_path)
    else:
        look_reach = max(1.0, shot.amount) if shot.move == "pull" else 1.0
    cam0 = frame_size(dancer, shot.start, shot.size, shot.yaw, high=shot.high, fov=shot.fov, height=shot.height,
                      frames=frames, heights=heights, look_reach=look_reach, at_least=at_least)
    look0 = tuple(p + cam0.reach * v for p, v in zip(cam0.position, direction(cam0.yaw, cam0.pitch)))
    carrier0 = (heights[0] + heights[1]) / 2.0 if "body" in SIZE_SPEC[shot.size] else heights[0]
    lift = look0[1] - carrier0
    ax0, az0 = anchor(dancer, shot.start, shot.size)
    r0 = math.hypot(cam0.position[0] - ax0, cam0.position[2] - az0)
    low = lowest_height(dancer, frames)
    if at_least is not None:
        low = max(low, at_least)
    profile = move_profile(len(frames), shot.move_start - shot.start, shot.move_end - shot.start)
    # moving in or out, the picture at her narrows or widens with the distance; her head top keeps its row (the picture
    # tightens from the bottom, as a person zooming in on a face does)
    bottom0, top0, _ = picture_span(shot.size, heights[0], min(heights[1], heights[0] - 1.0))
    head_drop = 0.5 - SIZE_SPEC[shot.size]["room"]
    span0 = top0 - bottom0
    factors = []
    positions = []
    for i, f in enumerate(frames):
        if shot.yaw_path is not None or shot.reach_path is not None:
            yaw = shot.yaw_path[i] if shot.yaw_path is not None else shot.yaw
            r = r0 * (shot.reach_path[i] if shot.reach_path is not None else 1.0)
            y = cam0.position[1]
        else:
            yaw, r, y = shot.yaw, r0, cam0.position[1]
            if shot.move == "arc":
                yaw = shot.yaw + shot.amount * profile[i]
            elif shot.move in ("push", "pull"):
                r = r0 * (1.0 + (shot.amount - 1.0) * profile[i])
            elif shot.move == "crane":
                y = cam0.position[1] + shot.amount * profile[i]
        factors.append(r / r0 if r0 > 0 else 1.0)
        positions.append((ax0 + r * math.sin(math.radians(yaw)), max(y, low), az0 - r * math.cos(math.radians(yaw))))
    # the planned move turns the camera with it (a head geared to the track keeps the cut's point in the middle); the
    # person behind the camera answers only what the dancer does: the turn from the cut's point to hers now
    planned, residual, points = [], [], []
    for i, f in enumerate(frames):
        zoom = head_drop * span0 * (1.0 - factors[i])
        point0 = (ax0, carrier0 + lift + zoom, az0)
        ax, az = anchor(dancer, f, shot.size)
        point = (ax, _carrier(dancer, f, shot.size) + lift + zoom, az)
        points.append(point)
        p_yaw, p_pitch = aim(positions[i], point0)
        t_yaw, t_pitch = aim(positions[i], point)
        planned.append((p_yaw, p_pitch))
        residual.append((((t_yaw - p_yaw) + 180.0) % 360.0 - 180.0, t_pitch - p_pitch))
    corrections = operate(residual, [shot.fov] * len(frames), residual[0], follow)
    aims = [(p[0] + c[0], p[1] + c[1]) for p, c in zip(planned, corrections)]
    out = []
    for i, (yaw, pitch) in enumerate(aims):
        horizontal = math.hypot(points[i][0] - positions[i][0], points[i][2] - positions[i][2])
        out.append(CameraFrame(positions[i], yaw, pitch, 0.0, shot.fov, horizontal / max(math.cos(math.radians(pitch)), 1e-6)))
    return out


def make_path(dancer, shots, follow=FOLLOW):
    """the CameraFrame of every frame of the song and the frames of the cuts"""
    frames, cuts = [], []
    for shot in shots:
        cuts.append(shot.start)
        frames += shoot(dancer, shot, follow)
    return frames, cuts


# ---- a traced live camera ---------------------------------------------------------------------------------------

@dataclasses.dataclass
class TraceShot:
    start: int
    end: int
    fov: int
    yaws: List[float]            # the window's Y on every frame
    distances: List[float]       # the window's distance on every frame
    states: list                 # fk.CameraState of every frame


LONG_LENS = 10                   # degrees: a field this narrow or narrower is a long lens (the trace's are 5 and 6)
QUICK_LENS = (5, 10)             # frames, degrees: a field changing this much this fast inside a shot is a cut
WIDE_LENS = 20                   # degrees: through a field this wide or wider a traced shot is knee or wider (a close size
                                 # from near through a wide lens draws a large head over a shortened body)


def lens_sizes(fov):
    """the sizes a traced shot may take through its lens: knee or wider through a wide lens; through a long lens no long
    shot (from that far away the picture reaches past the near edge of the stage's floor below her, a dark band at its
    bottom under a floating floor)"""
    if fov >= WIDE_LENS:
        return ("long", "full", "knee")
    if fov <= LONG_LENS:
        return tuple(z for z in SIZES if z != "long")
    return SIZES


def _nearest_size(size, allowed):
    return min(allowed, key=lambda z: abs(SIZES.index(z) - SIZES.index(size)))


def trace_cuts(keys):
    """(cut, landing) of every cut of a traced camera: two keys a frame apart with a jump (as a15 measured the live
    camera: the cut lands on the later key), and a quick change of lens (QUICK_LENS) between two keys, cut where the
    change starts (the frame after the earlier key) and landing on the later key; the frames between are the change"""
    out = []
    for a, b in zip(keys, keys[1:]):
        gap = b.frame - a.frame
        jump = (abs(b.distance - a.distance) > 1 or math.dist(a.position, b.position) > 0.5
                or math.degrees(max(abs(x - y) for x, y in zip(a.rotation, b.rotation))) > 2 or abs(b.fov - a.fov) >= 1)
        if (gap == 1 and jump) or (gap <= QUICK_LENS[0] and abs(b.fov - a.fov) >= QUICK_LENS[1]):
            out.append((a.frame + 1, b.frame))
    return out


def read_trace(motion, last_frame):
    """the shots of a traced camera up to `last_frame`, each with its lens (the field at its first frame) and the
    window's Y and distance on every frame.  A shot that starts with a quick change of lens holds where the change lands
    until it gets there (the frames of the change, kept in the shot before, came in on her for 0.1 s just before the
    cut: 3019-3021 of the distributed camera, review camera-v2)"""
    keys = fk.camera_keys(motion)
    frames = [k.frame for k in keys]
    cuts = [(c, land) for c, land in trace_cuts(keys) if 0 < c <= last_frame]
    starts = [0] + [c for c, _ in cuts]
    landings = dict(cuts)
    out = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else last_frame
        land = min(landings.get(start, start), end)
        states = [fk.camera_at(keys, max(f, land), frames) for f in range(start, end + 1)]
        out.append(TraceShot(start, end, int(round(states[0].fov)), unwrap([s.angles[1] for s in states]),
                             [s.distance for s in states], states))
    return out


def _trace_camera(state):
    position = fk.camera_position(state)
    return CameraFrame(position, state.angles[1], state.angles[0], 0.0, int(round(state.fov)), abs(state.distance))


def trace_size(dancer, shot):
    """the size the traced view gives this dancer at the middle of the shot: the class of what it shows; a long view
    where her body takes less than half the picture's height (even when the bottom edge cuts her feet: the trace aimed
    at the stage, not at her), or where it does not show her at all (a view of the hall); then the nearest size its
    lens may take (lens_sizes)"""
    middle = (shot.start + shot.end) // 2
    s = seen(dancer, middle, _trace_camera(shot.states[middle - shot.start]))
    if not (math.isfinite(s["eyes_u"]) and abs(s["eyes_u"]) <= ASPECT and abs(s["eyes_v"]) <= 1.0):
        size = "long"
    elif s["body_share"] < 0.5:
        size = "long"
    else:
        size = classify(s["visible"], s["body_share"])
    return _nearest_size(size, lens_sizes(shot.fov))


def ensure_clear_cuts(shots):
    """a cut that changes the picture too little (CLEAR_RATIO, CLEAR_TURN) takes the later shot one size away from the
    earlier one (closer when it can, so the human's view is kept)"""
    for i in range(1, len(shots)):
        prev, shot = shots[i - 1], shots[i]
        if clear_cut(prev, shot.size, shot.yaw):
            continue
        for size in sorted(lens_sizes(shot.fov), key=lambda s: abs(SIZES.index(s) - SIZES.index(shot.size))):
            if clear_cut(prev, size, shot.yaw) and (i + 1 >= len(shots) or clear_cut(dataclasses.replace(shot, size=size),
                                                                                     shots[i + 1].size, shots[i + 1].yaw)):
                shots[i] = dataclasses.replace(shot, size=size)
                break
    return shots


def ensure_clear_on_frames(shots, dancer, follow=FOLLOW):
    """the shots as the frames show them: a cut that changes the picture too little (cut_change), or a shot that would
    lose her eyes (EYES_OUT, as when she sinks in a close shot), takes the nearest size (the wider of two as near) that
    cuts clearly and keeps her eyes in the picture; its lens and view stay (a traced zoom can end a shot near the size
    of the next)"""
    last = None
    for i in range(len(shots)):
        shot = shots[i]
        frames = shoot(dancer, shot, follow)
        clear = last is None or clear_on_frames(dancer, shot.start, last, frames[0])
        if not clear or eyes_out_share(dancer, shot, frames) > EYES_OUT:
            near = sorted(lens_sizes(shot.fov), key=lambda z: (abs(SIZES.index(z) - SIZES.index(shot.size)), SIZES.index(z)))
            for size in near:
                if size == shot.size:
                    continue
                trial = dataclasses.replace(shot, size=size)
                trial_frames = shoot(dancer, trial, follow)
                if (last is None or clear_on_frames(dancer, shot.start, last, trial_frames[0])) and \
                        eyes_out_share(dancer, trial, trial_frames) <= EYES_OUT:
                    shot, frames = trial, trial_frames
                    break
            shots[i] = shot
        last = frames[-1]
    return shots


def plan_trace(trace, dancer, music, close_ups=0.0, follow=FOLLOW):
    """the traced shots framed again for this scene: the trace's cuts, lens, view (its Y on every frame) and its moving in
    and out (its distance on every frame over the first) are kept; the size is what the trace shows of this dancer
    (trace_size); the camera stands at the trace's height but never below lowest_height nor more than 12 above her head
    (the hall's views from under the stage and from its roof come to her); the person behind the camera follows her
    (the trace aims at the middle of the stage).  With close_ups above 0, long-lens shots where she is calm and a line is
    sung become chest or face shots until they hold that share of the frames (add_close_ups)"""
    shots = []
    for t in trace:
        size = trace_size(dancer, t)
        height = min(max(fk.camera_position(t.states[0])[1], LOWEST), dancer.at("headtop", t.start)[1] + 12.0)
        name, kind = music.section_at(t.start)
        shots.append(Shot(t.start, t.end, size, t.yaws[0], t.fov, height=height,
                          yaw_path=list(t.yaws), reach_path=[d / t.distances[0] for d in t.distances],
                          section=name, kind=kind, source="trace"))
    shots = ensure_clear_cuts(shots)
    if close_ups > 0:
        shots = add_close_ups(shots, dancer, music, close_ups, follow)
    return ensure_clear_on_frames(shots, dancer, follow)


def add_close_ups(shots, dancer, music, share, follow=FOLLOW):
    """turn long-lens shots of a second or more where she is calm into face shots (chest where the face would not cut
    clearly from a neighbour, or where the person behind the camera would lose her eyes), those with a sung line first,
    never two close shots in a row, until the close shots hold `share` of the frames.  A shot whose last beat has her
    head moving fast (Moments.tail_move) stays as it is: the traced cut cannot come onto the move"""
    moments = Moments(dancer)
    beat = max(1, int(round(music.period * FPS)))
    total = float(shots[-1].end + 1 - shots[0].start)
    close = sum(s.end - s.start + 1 for s in shots if s.size in ("chest", "face"))
    scored = []
    for i, s in enumerate(shots):
        if s.fov > LONG_LENS or s.end - s.start + 1 < FPS or s.size in ("chest", "face"):
            continue
        m = moments.of(s.start, s.end)
        if not m["calm"] or moments.tail_move(s.start, s.end, beat) is not None:
            continue
        sung = music.sung(s.start, s.end)
        scored.append((-(2 if sung else 0) + m["head_p90"] / CALM_HEAD, s.start, i))
    for _, _, i in sorted(scored):
        if close / total >= share:
            break
        s = shots[i]
        neighbours = [shots[j] for j in (i - 1, i + 1) if 0 <= j < len(shots)]
        if any(n.size in ("chest", "face") for n in neighbours):
            continue
        for size in ("face", "chest"):
            trial = dataclasses.replace(s, size=size, source="close_up")
            if not all(clear_cut(n, size, s.yaw) for n in neighbours):
                continue
            if eyes_out_share(dancer, trial, shoot(dancer, trial, follow)) > EYES_OUT:
                continue
            shots[i] = trial
            close += s.end - s.start + 1
            break
    return shots


# ---- what the camera did: the measures of the report ------------------------------------------------------------

STILL = 0.02                      # half-heights a second: a camera turning and moving slower than this holds still


def _r(value, places=4):
    return round(float(value), places) + 0.0


def measures(dancer, music, shots, frames):
    """measured on the written path (not on the plan): the size of every frame as the picture shows it (classify), how
    often her eyes are in the picture, the camera's least height over her hips, how far it looks down at her hips on
    the frames whose picture shows them (the least angle, and the frames under MIN_LOOK_DOWN), where the cuts fall
    against the bar lines and the section heads, cuts that change the picture too little (jump cuts, measured on the
    frames around them), the shots' lengths, how much of the time the camera holds still, and how late the person
    behind it follows her"""
    n = len(frames)
    sizes, inside, cut_head, above = {s: 0 for s in SIZES}, 0, 0, []
    looks, hips_angles = [], []
    for f, cam in enumerate(frames):
        s = seen(dancer, f, cam)
        size = classify(s["visible"], s["body_share"]) if math.isfinite(s["visible"]) else "long"
        sizes[size] += 1
        ok = math.isfinite(s["eyes_u"]) and abs(s["eyes_u"]) <= ASPECT and abs(s["eyes_v"]) <= 1.0
        inside += ok
        cut_head += s["headtop_v"] > 1.0 and size != "face"
        above.append(cam.position[1] - dancer.at("hips", f)[1])
        looks.append(s)
        shown, angle, _ = hips_look_down(dancer, f, cam)
        if shown:
            hips_angles.append((angle, look_down_needed(dancer, f)))
    cuts = [s.start for s in shots[1:]]
    bars = []
    b = 0
    while music.bar_frame(b) <= music.last_frame + 1:
        bars.append(music.bar_frame(b))
        b += 1
    on_bars = sum(1 for c in cuts if min(abs(c - x) for x in bars) <= 1) / float(len(cuts)) if cuts else 1.0
    heads = [music.beat_frame(beat) for beat, _, _ in music.sections[1:] if music.beat_frame(beat) <= music.last_frame]
    beat_frames = (music.beat_frame(1) - music.beat_frame(0))
    heads_cut = sum(1 for h in heads if any(abs(c - h) <= beat_frames for c in cuts))
    jumps = []
    for c in cuts:
        ratio, turn = cut_change(dancer, c, frames[c - 1], frames[c])
        if ratio < CLEAR_RATIO and turn < CLEAR_TURN:
            jumps.append({"frame": c, "size_ratio": _r(ratio, 3), "turn": _r(turn, 1)})
    still = 0
    starts = set(s.start for s in shots)
    for f in range(1, n):
        if f in starts:
            continue
        a, b2 = frames[f - 1], frames[f]
        t = math.tan(math.radians(b2.fov / 2.0))
        turn = math.radians(math.hypot(((b2.yaw - a.yaw) + 180.0) % 360.0 - 180.0, b2.pitch - a.pitch)) / t
        travel = math.dist(a.position, b2.position) / max(b2.reach, 1e-6) / t
        still += (turn + travel) * FPS < STILL
    lags = []
    for shot in shots:
        if shot.end - shot.start < 3 * FPS:
            continue
        span = range(shot.start, shot.end + 1)
        target = [aim(frames[f].position, (anchor(dancer, f, shot.size)[0], frames[f].position[1], anchor(dancer, f, shot.size)[1]))[0]
                  for f in span]
        follower = unwrap([frames[f].yaw for f in span])
        target = unwrap(target)
        if max(target) - min(target) > 2.0 * math.degrees(math.atan(FOLLOW["slack"][0] * math.tan(math.radians(shot.fov / 2.0)))):
            lags.append(lag_seconds(target, follower))
    seconds = [(s.end - s.start + 1) / float(FPS) for s in shots]
    return {"size_share": {k: _r(v / float(n)) for k, v in sizes.items()}, "eyes_in_picture": _r(inside / float(n)),
            "head_top_cut": _r(cut_head / float(n)), "camera_above_hips_min": _r(min(above)),
            "hips_look_down_min": _r(min(a for a, _ in hips_angles), 2) if hips_angles else None,
            "hips_look_down_low": sum(1 for a, need in hips_angles if a < need - 1e-6),
            "flare_frames": sum(flare_frames(dancer)[:n]),
            "hips_look_down_flare_min": _r(min(a for a, need in hips_angles if need == FLARE_LOOK_DOWN), 2)
            if any(need == FLARE_LOOK_DOWN for _, need in hips_angles) else None,
            "camera_height_min": _r(min(c.position[1] for c in frames)), "cuts": len(cuts),
            "cuts_on_bar_lines": _r(on_bars), "section_heads_cut": [heads_cut, len(heads)], "jump_cuts": len(jumps),
            "jump_cut_list": jumps,
            "shot_seconds": {"mean": _r(sum(seconds) / len(seconds), 2), "median": _r(_median(seconds), 2),
                             "min": _r(min(seconds), 2), "max": _r(max(seconds), 2)},
            "still_share": _r(still / float(max(1, n - len(starts)))),
            "follow_lag_s": {"shots": len(lags), "median": _r(_median(lags), 2) if lags else None},
            "moves": {m: sum(1 for s in shots if s.move == m) for m in ("hold", "push", "pull", "arc", "crane")},
            "sources": {k: sum(1 for s in shots if s.source == k) for k in ("music", "trace", "close_up")}}


def shot_json(shot, music):
    bar = (shot.start / float(FPS) - music.first_beat) / music.period / music.beats_per_bar
    return {"start": shot.start, "end": shot.end, "frames": shot.end - shot.start + 1,
            "seconds": _r((shot.end - shot.start + 1) / float(FPS), 2), "bar": _r(bar, 2), "section": shot.section,
            "kind": shot.kind, "size": shot.size, "yaw": _r(shot.yaw, 2), "fov": shot.fov, "high": shot.high,
            "move": shot.move, "move_frames": [shot.move_start, shot.move_end] if shot.move != "hold" else None,
            "amount": _r(shot.amount, 3), "source": shot.source, "early": shot.early}


# ---- guarding another camera ------------------------------------------------------------------------------------

GUARD_POINTS = ("hips", "lhip", "rhip")    # where guard measures the look-down: the point between the hip joints at their
                                           # height (the hips every earlier check measured, and the look-down test was
                                           # drawn against) and either hip joint (the far one is the least looked down at)
PELVIS_SPIN = 360.0               # deg/s: her lower body (the way 下半身 faces) turning this fast from one frame to the next
PELVIS_BEFORE, PELVIS_AFTER = 5, 6  # frames: and that many before and after that frame flare her skirt as well (the count
                                  # of the fast turns of the v11 base: 292 frames of the song, against FLARE_SPIN's 357 of
                                  # the shoulders; guard takes both)
GUARD_RATE = 20.0                 # deg/s: the top pace of the tilt guard adds (a crane swinging up round the look-at point)
GUARD_RAMP = 15                   # frames: the shortest rise before a frame that needs the tilt, and the shortest settle after
GUARD_HOLD = 6                    # frames: on each side of a frame that needs a tilt the tilt is held at least that high
GUARD_SMOOTH = 5                  # frames: the half width of the cosine that smooths the tilt (under GUARD_HOLD: smoothing
                                  # never lowers a frame below its own need)
GUARD_CLOSE = 60                  # frames: a dip between two rises narrower than twice this is filled (the camera stays
                                  # up rather than bob down and up again within 4 s)
GUARD_MARGIN = 0.05               # degrees over the need
GUARD_TOP = 85.0                  # degrees: no guarded camera looks down more steeply than this
GUARD_ROUNDS = 6
GUARD_SUBFRAMES = 16              # the look-down holds over every frame at f + k/16: MMD keeps the camera of a frame (a key
                                  # on every frame) over the subframes it draws at 480 fps while her body moves on
                                  # (mv_world.view_at); measured at the frames alone, the review camfinalrev found 5 frames
                                  # at the end of a spin or a window 0.36 degrees short between the frames
LIFT_ROOM = 0.1                   # --lift-aim: her knees stay this far over the bottom edge (half-heights: 5 % of the
                                  # picture), the eye stays where guard put it
LIFT_SHARE = 1.0                  # and the aim gives back at most this share of a window's own tilt (all of it: then the
                                  # camera looks the way it would without the window, from the window's eye)


def step_cuts(keys):
    """the frames where a camera motion cuts: its keys that carry the step curve (this tool and make_camera put it on
    the first key of every shot), frame 0 left out"""
    return sorted(k.frame for k in keys if k.frame > 0 and tuple(vmd.camera_curves(k.interpolation)["distance"]) == CUT_CURVE)


def _window_frame(state):
    """a window state as a CameraFrame (the camera where fk puts it, the window's angles, its distance)"""
    return CameraFrame(fk.camera_position(state), state.angles[1], state.angles[0], state.angles[2], int(round(state.fov)),
                       abs(state.distance))


def _tilted(state, tilt):
    """the camera of a window state swung up round its look-at point by `tilt` degrees: the same look-at point, distance,
    heading, roll and lens, only the window's X angle grows (unchanged when 0)"""
    if tilt <= 0.0:
        return _window_frame(state)
    if state.distance <= 0.0:
        raise ValueError("frame %d: guard swings a camera up round its look-at point, and this one stands at or beyond it "
                         "(distance %r)" % (state.frame, state.distance))
    pitch = state.angles[0] + tilt
    yaw = state.angles[1]
    return CameraFrame(place_camera(state.look_at, yaw, pitch, state.distance), yaw, pitch, state.angles[2],
                       int(round(state.fov)), state.distance)


def hip_points(dancer, frame):
    """the points guard looks down at (GUARD_POINTS); a dancer without the hip joints is refused"""
    missing = [n for n in GUARD_POINTS if not dancer.has(n)]
    if missing:
        raise ValueError("guard needs her hip joints (%s): read the dance with dancer_from_motion(hip_joints=True)"
                         % ", ".join(missing))
    return [dancer.at(n, frame) for n in GUARD_POINTS]


def hip_points_over(dancer, frame):
    """the points guard looks down at (GUARD_POINTS) over the whole frame: at each of its GUARD_SUBFRAMES subframes"""
    hip_points(dancer, frame)
    return [p for name in GUARD_POINTS for p in dancer.over(name, frame)]


def look_down_at(position, points):
    """the least of the angles (degrees) a camera at `position` looks down at `points`: its height over each against
    its distance from it on the floor"""
    return min(math.degrees(math.atan2(position[1] - p[1], math.hypot(position[0] - p[0], position[2] - p[2])))
               for p in points)


def pelvis_spins(dancer):
    """per frame whether her lower body turns fast: the way 下半身 faces (pelvis_front) turns more than PELVIS_SPIN
    from a frame to the next, and PELVIS_BEFORE frames before, PELVIS_AFTER after that frame"""
    n = dancer.frames
    if not dancer.has("pelvis_front"):
        raise ValueError("guard needs the way her lower body faces: read the dance with dancer_from_motion(hip_joints=True)")
    heads = []
    for f in range(n):
        w, p = dancer.at("waist", f), dancer.at("pelvis_front", f)
        heads.append(math.degrees(math.atan2(p[0] - w[0], -(p[2] - w[2]))))
    heads = unwrap(heads)
    out = [False] * n
    for f in range(n - 1):
        if abs(heads[f + 1] - heads[f]) * FPS > PELVIS_SPIN:
            for g in range(max(0, f - PELVIS_BEFORE), min(n, f + PELVIS_AFTER + 1)):
                out[g] = True
    return out


def guard_needs(dancer, last, windows=()):
    """the look-down every frame up to `last` needs (degrees): MIN_LOOK_DOWN, FLARE_LOOK_DOWN while her shoulders
    (flare_frames) or her lower body (pelvis_spins) turn fast, and what a window (first, last, degrees) asks over its
    frames when that is more; with the frames of the fast turns"""
    flare, spin = flare_frames(dancer), pelvis_spins(dancer)
    fast = [flare[min(f, dancer.frames - 1)] or spin[min(f, dancer.frames - 1)] for f in range(last + 1)]
    need = [FLARE_LOOK_DOWN if fast[f] else MIN_LOOK_DOWN for f in range(last + 1)]
    for a, b, degrees in windows:
        for f in range(max(0, int(a)), min(last, int(b)) + 1):
            need[f] = max(need[f], float(degrees))
    return need, fast


def tilt_needed(state, points, need):
    """the least tilt (degrees) that swings the camera of `state` up round its look-at point far enough to look down at
    `points` by `need`; ValueError when no tilt up to GUARD_TOP does (it is not rounded away)"""
    if look_down_at(_tilted(state, 0.0).position, points) >= need:
        return 0.0
    top = GUARD_TOP - state.angles[0]
    if top <= 0.0 or look_down_at(_tilted(state, top).position, points) < need:
        raise ValueError("frame %d: no tilt up to %g degrees looks down at her hips by %g (the camera is too close to or "
                         "below them for that)" % (state.frame, GUARD_TOP, need))
    lo, hi = 0.0, top
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if look_down_at(_tilted(state, mid).position, points) >= need:
            hi = mid
        else:
            lo = mid
    return hi


def _ramp(amount):
    """the frames a tilt of `amount` degrees takes to rise (and to settle): GUARD_RAMP at least, and enough that the
    cosine never turns faster than GUARD_RATE"""
    return max(GUARD_RAMP, int(math.ceil(math.pi / 2.0 * amount / GUARD_RATE * FPS)) - 1)


def guard_profile(asked, bounds):
    """the tilt of every frame (degrees) from what each frame asks (`asked`, 0 for none), shot by shot (`bounds`: the
    first frames of the shots and one past the last): every frame that asks holds its tilt GUARD_HOLD frames each way and
    rises and settles on a cosine over _ramp of it; the highest of these on every frame, the dips narrower than twice
    GUARD_CLOSE filled (a closing), smoothed by a cosine GUARD_SMOOTH frames wide.  Every frame keeps at least what it asked (the
    smoothing averages frames that hold it), the tilt never turns faster than GUARD_RATE, and no shot gives any to the
    next"""
    out = [0.0] * len(asked)
    kernel = [0.5 * (1.0 + math.cos(math.pi * j / (GUARD_SMOOTH + 1.0))) for j in range(-GUARD_SMOOTH, GUARD_SMOOTH + 1)]
    for a, b in zip(bounds, bounds[1:]):
        m = b - a
        env = [0.0] * m
        for g in range(m):
            amount = asked[a + g]
            if amount <= 0.0:
                continue
            ramp = _ramp(amount)
            for f in range(max(0, g - GUARD_HOLD - ramp), min(m, g + GUARD_HOLD + ramp + 1)):
                gap = max(0, abs(f - g) - GUARD_HOLD)
                value = amount if gap == 0 else amount * 0.5 * (1.0 + math.cos(math.pi * gap / (ramp + 1.0)))
                if value > env[f]:
                    env[f] = value
        if not any(env):
            continue
        # a closing (the highest within GUARD_CLOSE each way, then the lowest of that within GUARD_CLOSE each way) of the
        # shot with 0 beyond its ends: a dip narrower than twice GUARD_CLOSE between two rises is filled up to the lower of
        # them, all of it; the stretch between a cut and the first rise (or the last rise and the cut) is no dip and is not
        pad = [0.0] * GUARD_CLOSE + env + [0.0] * GUARD_CLOSE
        grown = [max(pad[max(0, j - GUARD_CLOSE):j + GUARD_CLOSE + 1]) for j in range(len(pad))]
        filled = [max(env[f], min(grown[f:f + 2 * GUARD_CLOSE + 1])) for f in range(m)]
        for f in range(m):
            lo, hi = max(0, f - GUARD_SMOOTH), min(m, f + GUARD_SMOOTH + 1)
            w = kernel[lo - f + GUARD_SMOOTH:hi - f + GUARD_SMOOTH]
            out[a + f] = sum(v * k for v, k in zip(filled[lo:hi], w)) / sum(w)
    return out


def guard_camera(dancer, keys, last, windows=()):
    """another camera (keys of a camera motion, up to frame `last`) kept from the low angle: where a frame looks down at
    her hips or either hip joint over its subframes (hip_points_over) less than it needs (guard_needs: 4.5 degrees, 15
    while she turns fast, what a window asks), the camera swings up round its own look-at point, so the picture keeps
    its subject, its size and the way it is seen from, and only tilts; the tilt rises before and settles after inside
    the shot (guard_profile, step_cuts).  The rest of the frames are the input's.  Returns (CameraFrame per frame, the
    cuts, the tilt per frame in degrees)"""
    frames_of_keys = [k.frame for k in keys]
    states = [fk.camera_at(keys, f, frames_of_keys) for f in range(last + 1)]
    cuts = [c for c in step_cuts(keys) if c <= last]
    bounds = [0] + cuts + [last + 1]
    need, _ = guard_needs(dancer, last, windows)
    points = [hip_points_over(dancer, f) for f in range(last + 1)]
    asked = [0.0] * (last + 1)
    for f, s in enumerate(states):
        t = tilt_needed(s, points[f], need[f] + GUARD_MARGIN)
        if t > 0.0:
            asked[f] = t
    for _ in range(GUARD_ROUNDS):
        tilts = guard_profile(asked, bounds)
        cams = [_tilted(s, tilts[f]) for f, s in enumerate(states)]
        short = [f for f, cam in enumerate(cams) if look_down_at(cam.position, points[f]) < need[f] - 1e-9]
        if not short:
            return cams, cuts, tilts
        for f in short:                         # (the look-down did not grow with the tilt there: ask that frame more)
            asked[f] = max(asked[f], tilts[f]) + 0.5
    raise ValueError("the camera does not come to look down at her hips as far as it must after %d rounds" % GUARD_ROUNDS)


def knee_points(dancer, frame):
    """her knees as --lift-aim keeps them in the picture: half way from each hip joint to the toe under it (the knees
    are the leg IK's, the forward kinematics does not give them; the toes between them where the dancer has no own)"""
    out = []
    for hip, toe in (("lhip", "ltoe"), ("rhip", "rtoe")):
        t = dancer.at(toe if dancer.has(toe) else "toes", frame)
        out.append(tuple((a + b) / 2.0 for a, b in zip(dancer.at(hip, frame), t)))
    return out


def lifted(cam, lift):
    """the camera turned up about its own eye by `lift` degrees: the same place, heading, roll, lens and distance to its
    look-at point (the look-at point rises with the line of sight); unchanged for 0"""
    return cam if lift <= 0.0 else dataclasses.replace(cam, pitch=cam.pitch - lift)


def knees_in(dancer, frame, cam):
    """whether both knees (knee_points) are in front of the camera and LIFT_ROOM or more over the bottom edge"""
    for p in knee_points(dancer, frame):
        _, v, depth = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, p)
        if not (depth > 0.0 and math.isfinite(v) and v >= -1.0 + LIFT_ROOM):
            return False
    return True


def lift_aim(dancer, cams, tilts, base_tilts, cuts, windows):
    """the windows' cameras turned back up about their own eyes (--lift-aim): a window's own tilt is what guard tilts
    with the windows (`tilts`) over what it tilts without them (`base_tilts`); on every run of frames of a shot where
    that is above 0 and that holds a window's frames, the camera turns up by one share of it, the largest share up to
    LIFT_SHARE that keeps her knees in the picture (knees_in) on every frame of the run (none where they are not in it
    before the lift).  The eye stays, so the look-down at her hips stays; the view turns no faster than the tilts do.
    Returns (CameraFrame per frame, the lift per frame in degrees, the runs: frames, seconds, windows, share, lift_max)"""
    n = len(cams)
    excess = [max(0.0, t - b) for t, b in zip(tilts, base_tilts)]
    bounds = [0] + [c for c in cuts if 0 < c < n] + [n]
    lifts, runs = [0.0] * n, []
    for a, b in zip(bounds, bounds[1:]):
        f = a
        while f < b:
            if excess[f] <= 0.0:
                f += 1
                continue
            g = f
            while g + 1 < b and excess[g + 1] > 0.0:
                g += 1
            span = range(f, g + 1)
            asked = [[int(w0), int(w1), float(d)] for w0, w1, d in windows if w0 <= g and w1 >= f]
            if asked:
                def fits(share):
                    return all(knees_in(dancer, h, lifted(cams[h], share * excess[h])) for h in span)
                lo, hi = 0.0, LIFT_SHARE
                if fits(hi):
                    lo = hi
                elif fits(lo):
                    for _ in range(40):
                        mid = 0.5 * (lo + hi)
                        if fits(mid):
                            lo = mid
                        else:
                            hi = mid
                for h in span:
                    lifts[h] = lo * excess[h]
                runs.append({"frames": [f, g], "seconds": [_r(f / float(FPS), 2), _r(g / float(FPS), 2)], "windows": asked,
                             "share": _r(lo, 4), "lift_max": _r(max(lifts[h] for h in span), 2),
                             "frames_lifted": sum(1 for h in span if lifts[h] > 0.0)})
            f = g + 1
    return [lifted(c, x) for c, x in zip(cams, lifts)], lifts, runs


def guard_view(dancer, frames, need, fast, windows=()):
    """the measures of the low angle on a camera path, every frame counted over its subframes (hip_points_over): the
    least look-down at her hips and hip joints, the frames under what they need, the least over her fast turns, and over
    every window"""
    angles = [look_down_at(cam.position, hip_points_over(dancer, f)) for f, cam in enumerate(frames)]
    turning = [a for a, t in zip(angles, fast) if t]
    out = {"look_down_min": _r(min(angles), 2), "look_down_min_at": int(min(range(len(angles)), key=angles.__getitem__)),
           "short_frames": sum(1 for a, n in zip(angles, need) if a < n - 1e-6),
           "under_4_5_frames": sum(1 for a in angles if a < MIN_LOOK_DOWN - 1e-6),
           "fast_turn_min": _r(min(turning), 2) if turning else None,
           "fast_turn_under_15_frames": sum(1 for a, t in zip(angles, fast) if t and a < FLARE_LOOK_DOWN - 1e-6),
           "windows": [{"frames": [int(a), int(b)], "need": float(d),
                        "min": _r(min(angles[max(0, int(a)):int(b) + 1]), 2)} for a, b, d in windows]}
    return out, angles


def guard_spans(dancer, before, after, tilts, cuts, angles_before, angles_after, need):
    """the table of what guard changed: every run of tilted frames inside a shot, with its seconds, the largest tilt,
    rise and move of the camera, and the least look-down before and after"""
    shot_of = []
    bounds = [0] + list(cuts) + [len(tilts)]
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        shot_of += [i] * (b - a)
    rows, f, n = [], 0, len(tilts)
    while f < n:
        if tilts[f] <= 0.0:
            f += 1
            continue
        g = f
        while g + 1 < n and tilts[g + 1] > 0.0 and shot_of[g + 1] == shot_of[f]:
            g += 1
        span = range(f, g + 1)
        rows.append({"frames": [f, g], "seconds": [_r(f / float(FPS), 2), _r(g / float(FPS), 2)], "shot": shot_of[f],
                     "tilt_max": _r(max(tilts[h] for h in span), 2),
                     "rise_max": _r(max(after[h].position[1] - before[h].position[1] for h in span), 2),
                     "moved_max": _r(max(math.dist(after[h].position, before[h].position) for h in span), 2),
                     "need_max": max(need[h] for h in span),
                     "look_down_min_before": _r(min(angles_before[h] for h in span), 2),
                     "look_down_min_after": _r(min(angles_after[h] for h in span), 2)})
        f = g + 1
    return rows


def in_picture(dancer, frames, name):
    """the share of the frames whose picture shows the landmark `name`"""
    shown = 0
    for f, cam in enumerate(frames):
        u, v, depth = project(cam.position, cam.yaw, cam.pitch, cam.roll, cam.fov, dancer.at(name, f))
        shown += depth > 0 and math.isfinite(u) and abs(u) <= ASPECT and abs(v) <= 1.0
    return _r(shown / float(len(frames)))


# ---- the command ------------------------------------------------------------------------------------------------

def write_bytes(path, data):
    """write next to the target and move over it, so a failure leaves the old file as it was"""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


def check_distinct(*paths):
    seen_paths = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen_paths:
            raise ValueError("%s and %s are the same file: the inputs, OUT and --report must all differ" % (seen_paths[key], path))
        seen_paths[key] = path


def run(mode, dance_path, model_path, music_path, out_path, trace_path=None, report_path=None, seed=0, close_ups=0.0,
        last=None):
    """read, plan, shoot, write the camera and read it back; the summary is what main prints"""
    if not 0.0 <= close_ups < 1.0:
        raise ValueError("--close-ups is a share of the frames, from 0 up to below 1, not %r" % (close_ups,))
    check_distinct(dance_path, model_path, music_path, trace_path, out_path, report_path)
    with open(music_path, encoding="utf-8-sig") as f:
        music = Music.from_json(json.load(f))
    if last is not None:
        if last < 1:
            raise ValueError("--last is a frame of 1 or more")
        music = dataclasses.replace(music, last_frame=int(last))
    dancer = dancer_from_motion(pmx.load(model_path), vmd.load(dance_path), music.last_frame)
    if mode == "music":
        shots = plan_music(music, dancer, seed)
    else:
        shots = plan_trace(read_trace(vmd.load(trace_path), music.last_frame), dancer, music, close_ups)
    frames, cuts = make_path(dancer, shots)
    out_full = os.path.abspath(out_path)
    write_bytes(out_full, vmd.dumps(camera_motion(frames, cuts)))
    back = vmd.load(out_full)
    m = measures(dancer, music, shots, frames)
    result = {"mode": mode, "out": out_full, "shots": len(shots), "keys": len(back.cameras),
              "key_frames": [min(k.frame for k in back.cameras), max(k.frame for k in back.cameras)],
              "size_share": m["size_share"], "jump_cuts": m["jump_cuts"], "eyes_in_picture": m["eyes_in_picture"]}
    if report_path:
        report = {"mode": mode, "dance": os.path.abspath(dance_path), "music": os.path.abspath(music_path),
                  "trace": os.path.abspath(trace_path) if trace_path else None, "out": out_full, "seed": seed,
                  "close_ups": close_ups, "fps": FPS, "frames": [0, music.last_frame], "follow": FOLLOW,
                  "sizes": {s: SIZE_SPEC[s] for s in SIZES}, "measures": m, "shots": [shot_json(s, music) for s in shots]}
        write_bytes(os.path.abspath(report_path), (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        result["report"] = os.path.abspath(report_path)
    return result


def check_window(window):
    """(first, last, degrees) of a --window: frames first..last look down at her hips by `degrees`"""
    try:
        a, b, d = int(window[0]), int(window[1]), float(window[2])
    except (TypeError, ValueError, IndexError):
        raise ValueError("a window is FIRST LAST DEGREES (two frames and an angle), not %r" % (window,))
    if a < 0 or b < a:
        raise ValueError("a window's frames run from FIRST up to LAST (0 <= FIRST <= LAST), not %d-%d" % (a, b))
    if not 0.0 < d < GUARD_TOP:
        raise ValueError("a window asks for a look-down above 0 and under %g degrees, not %r" % (GUARD_TOP, d))
    return a, b, d


def run_guard(dance_path, model_path, camera_path, out_path, report_path=None, last=None, windows=(), lift=False):
    """guard another camera (guard_camera; with `lift` the windows' aim lifted, lift_aim), write it with a key on every
    frame and the step on its cuts, and read it back; the summary is what main prints, the report adds the table of what
    changed (guard_spans), the runs the aim was lifted on, the share of the frames that show her head top, eyes and toes
    before and after, and the tilt, the lift and the look-down (over the frame's subframes) of every frame"""
    check_distinct(dance_path, model_path, camera_path, out_path, report_path)
    windows = [check_window(w) for w in windows]
    motion = vmd.load(camera_path)
    keys = fk.camera_keys(motion)
    dance = vmd.load(dance_path)
    if last is None:
        last = max(fk.last_frame(dance), keys[-1].frame)
    dancer = dancer_from_motion(pmx.load(model_path), dance, last, hip_joints=True, subframes=GUARD_SUBFRAMES)
    frames_of_keys = [k.frame for k in keys]
    before = [_window_frame(fk.camera_at(keys, f, frames_of_keys)) for f in range(last + 1)]
    frames, cuts, tilts = guard_camera(dancer, keys, last, windows)
    swung = frames
    lifts, runs = [0.0] * (last + 1), []
    if lift and windows:
        _, _, base = guard_camera(dancer, keys, last)
        frames, lifts, runs = lift_aim(dancer, swung, tilts, base, cuts, windows)
        for run in runs:
            span = range(run["frames"][0], run["frames"][1] + 1)
            run["top_edge_max_before"] = _r(max(swung[h].pitch - swung[h].fov / 2.0 for h in span), 2)
            run["top_edge_max_after"] = _r(max(frames[h].pitch - frames[h].fov / 2.0 for h in span), 2)
    out_full = os.path.abspath(out_path)
    write_bytes(out_full, vmd.dumps(camera_motion(frames, [0] + cuts)))
    back = vmd.load(out_full)
    need, fast = guard_needs(dancer, last, windows)
    view_before, angles_before = guard_view(dancer, before, need, fast, windows)
    view_after, angles_after = guard_view(dancer, frames, need, fast, windows)
    cut_set = set(cuts)
    steps = [abs(tilts[f + 1] - tilts[f]) for f in range(last) if f + 1 not in cut_set]
    tilted = [f for f, t in enumerate(tilts) if t > 0.0]
    result = {"mode": "guard", "out": out_full, "keys": len(back.cameras), "cuts": len(cuts), "frames_tilted": len(tilted),
              "tilt_max": _r(max(tilts), 3), "tilt_pace_max": _r(max(steps or [0.0]) * FPS, 2),
              "rise_max": _r(max(a.position[1] - b.position[1] for a, b in zip(frames, before)), 3),
              "moved_max": _r(max(math.dist(a.position, b.position) for a, b in zip(frames, before)), 3),
              "lift_aim": bool(lift), "lift_max": _r(max(lifts), 3), "frames_lifted": sum(1 for x in lifts if x > 0.0),
              "fast_turn_frames": sum(fast), "before": view_before, "after": view_after}
    if report_path:
        spans = guard_spans(dancer, before, frames, tilts, cuts, angles_before, angles_after, need)
        report = dict(result, dance=os.path.abspath(dance_path), model=os.path.abspath(model_path),
                      camera=os.path.abspath(camera_path), windows=[[a, b, d] for a, b, d in windows],
                      min_look_down=MIN_LOOK_DOWN, flare_look_down=FLARE_LOOK_DOWN, flare_spin=FLARE_SPIN,
                      flare_hold=FLARE_HOLD, pelvis_spin=PELVIS_SPIN, pelvis_frames=[PELVIS_BEFORE, PELVIS_AFTER],
                      points=list(GUARD_POINTS), subframes=GUARD_SUBFRAMES, rate=GUARD_RATE, ramp=GUARD_RAMP,
                      hold=GUARD_HOLD, smooth=GUARD_SMOOTH, close=GUARD_CLOSE, margin=GUARD_MARGIN,
                      lift_room=LIFT_ROOM, lift_share=LIFT_SHARE, cut_frames=cuts, spans=spans, lifts=runs,
                      in_picture={name: [in_picture(dancer, before, name), in_picture(dancer, frames, name)]
                                  for name in ("headtop", "eyes", "toes")},
                      per_frame={"tilt": [_r(t, 3) for t in tilts], "lift": [_r(x, 3) for x in lifts], "need": need,
                                 "look_down_before": [_r(a, 3) for a in angles_before],
                                 "look_down_after": [_r(a, 3) for a in angles_after], "fast_turn": [int(t) for t in fast]})
        write_bytes(os.path.abspath(report_path), (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        result["report"] = os.path.abspath(report_path)
    return result


def _spans(frames):
    out = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="mode", required=True)
    g = sub.add_parser("guard", help="tilt another camera (make_camera's) down round its look-at point where it would look "
                                    "at her hips from too low")
    g.add_argument("dance", help="the dance motion (.vmd)")
    g.add_argument("model", help="the model (.pmx) the dance is for")
    g.add_argument("camera", help="the camera motion to guard (.vmd)")
    g.add_argument("out", help="the guarded camera motion to write (.vmd)")
    g.add_argument("--report", help="write what was tilted, the look-down before and after and every frame's to this JSON")
    g.add_argument("--last", type=int, help="the last frame (default: the last of the dance or the camera)")
    g.add_argument("--window", nargs=3, action="append", default=[], metavar=("FIRST", "LAST", "DEGREES"),
                   help="frames FIRST..LAST look down at her hips by DEGREES (repeatable; where her skirt flies higher "
                        "than a fast turn alone would lift it)")
    g.add_argument("--lift-aim", action="store_true",
                   help="turn the windows' cameras back up about their own eyes by the largest share of the window's own "
                        "tilt that keeps her knees in the picture (the eye, so the look-down at her hips, stays; the "
                        "picture shows more than the street's surface)")
    for mode in ("music", "trace"):
        s = sub.add_parser(mode)
        s.add_argument("dance", help="the dance motion (.vmd)")
        s.add_argument("model", help="the model (.pmx) the dance is for: the camera frames its bones")
        s.add_argument("music", help="JSON: first_beat, period, beats_per_bar, last_frame, sections, lines, hooks")
        if mode == "trace":
            s.add_argument("trace", help="the camera traced from a live video (.vmd)")
            s.add_argument("--close-ups", type=float, default=0.0,
                           help="turn calm long-lens shots into chest and face shots up to this share of the frames")
        s.add_argument("out", help="the camera motion to write (.vmd)")
        s.add_argument("--report", help="write the shots and the measures to this JSON (mv_chunks --shots reads it)")
        s.add_argument("--seed", type=int, default=0, help="the draws of the plan (default 0)")
        s.add_argument("--last", type=int, help="the last frame (default: the music's last_frame)")
    args = p.parse_args(argv)
    try:
        if args.mode == "guard":
            result = run_guard(args.dance, args.model, args.camera, args.out, args.report, args.last, args.window,
                               args.lift_aim)
        else:
            result = run(args.mode, args.dance, args.model, args.music, args.out, getattr(args, "trace", None),
                         args.report, args.seed, getattr(args, "close_ups", 0.0), args.last)
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"ok": False, "error": {"type": type(e).__name__, "message": str(e)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
