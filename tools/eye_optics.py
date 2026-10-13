"""Move the lights in the eyes, the pupils and the eyes' vergence as a person's do, written as one VMD to load after the
dance, the face and the gaze.

    python tools/eye_optics.py MODEL.pmx DANCE.vmd GAZE.vmd CAMERA.vmd OUT.vmd --face FACE.vmd [--look LOOK.json]
                               [--flares S ...] [--audio SONG] [--chorus S ...] [--params P.json] [--report r.json]
                               [--seed 0] [--trace t.json]

MODEL is the model made by tools/pmx_eyes.py (its catchlight bones); GAZE the 両目 track of tools/eye_gaze.py, merged
over the dance as MMD merges a later motion (its keys replace the dance's on the same bone and frame); FACE the face
motion loaded with them (needed when the model's closing morphs move its lights, as Sour's Rin's do: build in the
order gaze, face, this, and give the face VMD that will be drawn).  Every frame of the dance is computed.  The numbers
are PARAMS, each replaceable with --params (a JSON of the same shape; an unknown key is refused); they are those of
stage 5's research (`_spike/out/stage5/research/RESEARCH.md`, cited by section).

The light (the catchlight bones; RESEARCH 1.4, formula A):

* A light is the mirror image of a light source in the cornea.  Seen by the camera, its centre lies off the pupil's
  centre by  R proj(H) - K proj(g)  (R = 7.72 mm the cornea's radius, K = 4.67 mm from the entrance pupil back to the
  cornea's centre of curvature, H the half-way direction between the way to the light and the way to the camera,
  g the eye's axis, proj the part across the line of sight): in iris radii (5.91 mm)  1.31 proj(H) - 0.79 proj(g).
  Neither the head's turn nor its roll nor the eye's torsion enter it: only the eye's axis in the world, the light and
  the camera.
* Why A.  What a viewer compares is how far the light moves against the iris' own move (in iris radii, on the screen):
  the standard for the look is a person's ratio (formula B: the light follows 0.60 of the iris' move across and 0.48
  up and down, Ohlendorf 2022).  Formula A is a person's cornea and iris on this model's larger eyeball: on Sour's
  Rin, whose iris' rim moves 1.48 (across) and 1.42 (up) times a person's a degree in iris radii (the pupil 1.32 and
  1.26; stage 5 review Q2), the light follows 0.73 and 0.63 of the rim's move.  A is used because the model's lights
  were drawn near the rim (0.75 to 0.81 of the radius) and B would press them against it in more of the frames (the
  upper lights in 36 to 39 % of the open-eye frames against 27 to 29 % with A); the two differ by 0.1 iris radius at
  a 15-degree gaze (0.6 px at the MV's size).
* The light source is MMD's (light.direction, the window's numbers: where the light goes; the default -0.5 -1 0.5
  comes from above, in front, on her left); the camera is the camera motion's, seen from each eye's pupil.
* The model's lights were drawn for the eye at rest, looking at a camera straight in front.  Each light keeps that
  drawn place on its iris and moves by the change of the formula from that rest view, on the screen (both lights of
  an eye by the same change: they keep their spacing, RESEARCH 1.8), in the model's iris radii (its half width across
  X, half height across Y; Sour's Rin's iris is an ellipse, 0.1625 by 0.222).  The drawn place is measured from the
  centre of the iris' outline on its frontmost plane (eye_geometry's disc: the rim of Sour's Rin's dish-shaped iris;
  her pupil lies 0.11 deeper and shifts inside the outline when the eye is seen at a slant), carried by the bone the
  iris hangs on (with the vergence on the eye) and laid on the iris' plane along the screen's right and up
  (drawn_on_iris: it shrinks with an iris seen at a slant and does not turn with the head's roll).
* Each light bone (pmx_eyes: the pivot the pupil's depth behind the light) turns with 両目 by its append (pmx_eyes'
  share, formula A across); every frame its key adds the turn (light_turn) that brings its light from where the append
  alone puts it onto the camera's line through that point: damped least squares over the two turns across the bone,
  a few Gauss-Newton steps, so that seen from the front it lands on the line and seen side on (where a turn hardly
  moves the light across the line of sight) the turn stays small instead of swinging the light round.  No smoothing
  and no delay of its own: the same frame as the pupil (RESEARCH 0.2, items 2 to 4).  The key has no roll of its own.
* The change is held under light.cap iris radii (soft: unchanged up to 60 % of it, tanh beyond), and the light's
  centre, where the camera's ray through it meets the iris' plane, stays within light.reach iris radii of the iris'
  centre (keep_on_iris: unchanged up to its drawn radius, along tanh from there; held at the drawn radius if that is
  further out): beyond the iris the reflection would leave the cornea, and the model's lights would hang over the
  eye white.  Where the camera's ray meets the iris' surface itself must lie within the reach too (light.seen): a
  dish seen at a slant shows its deep side off where its rim's plane puts it (the MV's 45.7, 144.1, 214.1, 224.9 and
  253.9 seconds showed lights over the eye white so, at 0.47 to 0.90 on the plane); the light is held back toward the
  iris' centre as the camera sees it, along the camera's rays (iris_hit, the first meeting), until its ray meets the
  iris within the reach (or its drawn radius, if further out).  Seen so much at a slant that no place of the iris
  holds it (the dish hides its own centre: the MV's 253.9 seconds, the eyes 62 degrees off the camera), the light goes
  light.hide_depth behind its iris on the camera's line through where the iris' centre shows, which covers it
  (put back beside the iris, in the socket, nothing covered it).  The key's turn is held under light.key_cap degrees
  (soft from 60 % of it).
* The light rides on its iris (light.ride): the bone also moves, along the camera's line (so where the light shows
  does not change), until the light lies as high in front of the iris' surface where it has come to as it was drawn
  in front of the surface where it was drawn (iris_heights: the iris' frontmost surface over a grid, in the rest
  frame of the bone the iris hangs on; ride_on_iris, a few steps, at most light.ride_cap).  Sour's Rin's iris is a
  shallow dish tilted outward and her lights were drawn 0.01 to 0.04 in front of it: sliding without riding, a light
  hid behind the dish where it rises; lifted once and for all in front of the dish's frontmost point (an earlier
  version), the temporal lights stood 0.1 to 0.15 in front of their part of the dish and showed through the lids, on
  the lash line and the lower lid's skin.  Riding, every light keeps the depth the lids were made to cover.
* Where the camera sees an iris nearly edge on (its line to the iris more than light.side[0] degrees off the iris'
  forward, each eye on its own) the light's place gives way to its drawn place on that iris, wholly at light.side[1]
  degrees (84: past about 84 degrees, SEEN_COS, the iris is not seen and has no place to measure on).  The formula's
  place itself keeps moving toward the near edge as the iris turns away, so the hand-over is kept to the last few
  degrees, where the iris is a sliver: begun at 45 degrees, a head swinging 17 degrees a frame threw the light back
  across the iris in one frame (the MV's 111.2 seconds).  Seen from behind, the solve holds the light at its drawn
  place too (the camera's line runs along the iris' axis there), with small keys.
* The face's morphs also move the light quads themselves: Sour's Rin's まばたき and 笑い drag the upper lights down
  with the lid (at the MV's resting 0.3, by a quarter of the iris' radius) and back, so that a closing lid covers
  them.  That drag is kept (read from --face; held in place, a light lifted in front of the rim showed in front of a
  half-shut lid, stage 5 lid probe): it is added to the light's place (light_drags), the iris' boundary holds the
  light with it (Sour's Rin's drag also runs along the lid, sideways: it carried upper lights 0.36 past the iris'
  edge, stage 5 ray check of the MV), and each bone is solved with the drag on its quad, turning with it; the
  riding sets the light's depth before the drag.  The report and the trace give the places as MMD shows them.
* The lids (light.lids: the lid, lash and face materials about each iris, skinned on their bones and moved by the
  face's morphs every frame, lid_mesh): formula A can put a light where they cover the iris (an upper light under a
  lowered lid while the eye looks down: the MV's 167.2 seconds, the left upper light on the lash line under 笑い 0.6;
  the inner corner's skin at 24.1 seconds).  Such a light slides back along the straight way to its drawn place
  (with the drag) as far as the lids leave its iris uncovered with light.lid_margin around it, as the camera sees it
  (slide_off_lids on the camera's rays); where they cover all the way, it sits at its drawn place, where the model
  has it, under the lid.  Then the guard (light.guard: the lids, the face and the hair): nothing of them may lie
  between a light and the iris behind it (the light would show on them; the guard also looks light.guard_margin
  about its centre).  A light failing it comes down along the camera's line onto its iris (light.hug_height in
  front of it, under whatever covers it, which then covers the light as it covers the iris), or behind it
  (light.hide_depth) if that is not enough.  Neither changes where it shows on the screen.
* The light leaves the cornea when the light source lies more than 90 to 100 degrees from the camera (RESEARCH 1.6;
  the coordinator's rule): the morph HL消 (the light material's opacity) goes from 0 at light.hide[0] to 1 at
  light.hide[1] degrees between the light and the camera seen from the eyes, each frame on its own.  (The research's
  wider rule, H more than 46 to 50 degrees off the eye's axis, would also hide it whenever the eye turns away from the
  light; the report counts those frames as frames_beyond_cornea.)

The pupil (morphs 瞳大 and 瞳細 of Sour's Rin: with 瞳1off at 1 the navy pupil; 瞳大 widens only it, to (1 + 1.71 w) of
its radius, 瞳細 narrows only it, to (1 - 0.61 w); the factors are measured on the model's own morphs, pupil_scales;
瞳小 would shrink the whole iris and is not used).  r, the change of the pupil's diameter against the model's own, sums

* the light reflex at each flare of the MV's look (--look's "flares", seconds, and --flares; RESEARCH 2.1): from
  reflex.latency after the flare, for reflex.hold seconds, the pupil is pulled narrower with the time constant
  reflex.constrict (0.3 s), then widens again with reflex.redilate (2.4 s, 90 % back in 5.5 s): most narrow about
  1 s after the flare (latency 0.25 + hold 0.75; the reflex outlasts a 0.4-second flash), scaled so that one flare
  narrows it by reflex.peak (12 %);
* arousal: the song's loudness (--audio, RMS read with ffmpeg, 0 at its arousal.low and 1 at its arousal.high
  percentile) followed with arousal.rise on the way up and arousal.fall on the way down, arousal.amplitude from the
  quietest to the loudest about its median (music: 1 to 2 %, RESEARCH 2.2);
* at the head of each chorus (--chorus, seconds) a dilation of chorus.amplitude shaped as the pupil's response to an
  event, h(t) = (t / t_max)^n e^(n (1 - t / t_max)), n 10.1, t_max chorus.peak (0.93 s; Hoeks & Levelt via Wierda 2012);
* the near response: near.per_dioptre narrower for each dioptre of the vergence's demand (small; RESEARCH 2.4);
* unrest: unrest.waves sines between unrest.low_hz and high_hz (under 2 Hz) with random phases (from --seed),
  unrest.amplitude RMS together (RESEARCH 2.3: small while awake and busy).
r is kept in pupil.range; r > 0 is 瞳大 r / 1.71, r < 0 瞳細 -r / 0.61 (Sour's Rin's factors).

The vergence (keys on 右目 and 左目, after their append from 両目; RESEARCH 3.2 and 0.2 item 9):

* The eyes converge on her hands only, not on the camera, however near (large eyes look cross-eyed; a person's line of
  sight lies about 6 degrees nasal of the eye's axis anyway).  A hand is looked at (fixation_targets) when one of its
  points (vergence.hand_points) lies within hand_deg of the gaze (both eyes' mean, in the world), between near_m and
  hand_m away, for hand_frames frames on end; the camera, within camera_deg of the gaze, wins when it is nearer the gaze
  for its tolerance.  hand_deg (12) is far wider than what a person fixates (the fovea's 1 to 2 degrees) because
  tools/eye_gaze.py never chooses a hand as its target: the gaze passes near a hand only by chance, and a narrow cone
  would leave almost no look at one.  So the eyes meet on the point at the hand's distance along the gaze, not on the
  hand itself (in the MV's close-ups the two cannot be told apart).
* Looks at a hand split by up to vergence.gap_frames frames (the hand a little off the gaze, or nearer than near_m for
  a moment), with no look at the camera between, are one look (the MV's 52 seconds: the fingers came to 11 cm for 5
  frames in one look).
* The demand during a run on a hand is gain x atan((ipd / 2) / distance) per eye, the distance the run's median but
  not nearer than angle_near_m (ipd 61.5 mm, Murray 2017; gain 1: the geometric angle, RESEARCH 3.2 and the
  coordinator's probe; 15 cm: 11.6 degrees an eye at most); elsewhere 0.
* It is in phase with the look (vergence_in_phase): the eyes start to converge vergence.lead seconds before the run
  (they lead a target the hand moves by about 90 ms and lag a moving real target by under 125 ms: Erkelens et al.
  1989, Proc R Soc B 236:417) and start to diverge on its last frame; they are parallel on every frame on the camera
  (the rise waits for the last frame on the camera before the run, the fall is over by the next one: a look between
  two looks at the camera only begins to converge).  Each way runs along a minimum-jerk curve whose 5 to 95 % time is
  vergence.duration (0.25 s; the coordinator's 0.2 to 0.3 s) or longer, so its top speed stays under max_speed
  (60 deg/s; natural gaze shifts reach 50 to 200: Erkelens et al. 1989, 236:441).  (Tyler 2015's 0.24 s latency and
  8 deg/s, disparity steps on a screen, put the whole vergence after the MV's looks of 0.2 to 0.6 s, partly onto the
  camera: stage 5 review Q1.)
* Each eye then turns from the gaze onto the point at that distance along it (right eye -X, left eye +X: inward is
  +yaw for the right eye and -yaw for the left, as the coordinator's vergence probe keys them).

The eyes' fine motion (drift, microsaccades) is tools/eye_gaze.py's; this tool does not change the gaze.  The VMD keys
where straight lines between keys would miss a frame's value (keys.bone_deg, keys.position, keys.morph), with linear
curves, under the dance's model name.  The face's and the dance's keys on the same bones and morphs would mix with
these: they are refused, except keys on frame 0 that rest (identity, 0).  MMD stops loading a model's motions past
20,000 registered points (its morphs' keys from every motion loaded, one per morph and frame, and one for each morph
with no key on frame 0; bone keys are not counted): they are counted with the dance, the face and the gaze
(registration_points), reported with their margin, and refused within keys.reserve of keys.limit.
"""
import argparse
import copy
import json
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import pmx, pmx_edit, vmd  # noqa: E402
import pmx_eyes  # noqa: E402

FPS = 30.0
SHOWN = 0.1875                  # frames: the MV shows frame f at f + 0.1875 (tools/mv_look.py; tools/face_life.py)
FORWARD = (0.0, 0.0, -1.0)
UP = (0.0, 1.0, 0.0)
BIG, THIN, HIDE = "瞳大", "瞳細", "HL消"
CUT_JUMP, CUT_TURN = 1.0, 5.0   # a camera cut: it moves more than this (units) or turns more (degrees) in a frame
MIN_JERK_5_95 = 0.6162          # the 5 to 95 % time of a minimum-jerk move, as a share of its whole time
MIN_JERK_TOP = 1.875            # its top speed, times step / time
MAX_SPAN = 120                  # frames between two keys at most
OPEN_LID = 0.45                 # an eye whose closing morphs are at this or less is open (the report's open-eye measures)

PARAMS = {
    "light": {
        "cornea_radius_mm": 7.72,            # R (Navarro, via Barsingerhorn 2017)
        "pupil_to_centre_mm": 4.67,          # K: entrance pupil to the cornea's centre of curvature (RESEARCH 1.1)
        "iris_radius_mm": 5.91,              # the visible iris (Aguirre 2019)
        "direction": [-0.5, -1.0, 0.5],      # MMD's light, as its window shows it (where the light goes)
        "hide": [90.0, 100.0],               # degrees between the light and the camera: HL消 0 .. 1 (RESEARCH 1.6)
        "cap": 1.0,                          # iris radii the light moves off its drawn place at most (soft)
        "side": [72.0, 84.0],                # degrees an iris is seen off its forward: its light gives way to its drawn place
        "ride": True,                        # the bones move each light along the camera's line onto its iris' surface
        "ride_cap": 0.3,                     # model units a light's bone moves at most
        "damping": 0.15,                     # light_turn's damping, a share of the bone's depth
        "key_cap": 45.0,                     # degrees a light bone's key turns at most (soft from 60 % of it)
        "reach": 0.9,                        # iris radii from the iris' centre a light's centre goes at most (soft)
        "seen": True,                        # held within the reach where the camera's line meets the iris, too
        "lids": ["face", "目"],               # the materials of the lids, lashes and face (Sour's Rin's names)
        "lid_margin": 0.05,                  # iris radii a light keeps off where the lids cover its iris
        "guard": ["face", "目", "hair"],      # nothing of these may lie between a light and its iris
        "guard_margin": 0.01,                # model units about a light's centre the guard also looks
        "hug_height": 0.002,                 # model units in front of its iris a light under them is brought down to
        "hide_depth": 0.2,                   # model units behind its iris a light is put when that is not enough (into
                                             # the eyeball: beside the iris the eye white lies up to 0.2 behind its rim)
    },
    "vergence": {
        "ipd_mm": 61.5,                      # women's mean (Murray 2017)
        "unit_mm": 80.0,                     # one model unit
        "gain": 1.0,                         # the geometric angle (RESEARCH 0.1 and 3.2, the coordinator's probe)
        "near_m": 0.10,                      # a hand nearer than this is not looked at
        "angle_near_m": 0.15,                # the angle is at most that of a point this near (11.6 degrees an eye)
        "hand_m": 0.6,                       # about an arm's reach
        "hand_deg": 12.0,                    # degrees off the gaze (see the module docstring for why so wide)
        "hand_frames": 6,                    # tools/eye_gaze.py's shortest fixation (0.2 s)
        "gap_frames": 6,                     # looks at a hand this many frames apart or fewer are one look
        "hand_points": ["人指３先", "中指３先", "親指２先", "手先"],
        "camera_deg": 4.0,                   # tools/eye_gaze.py counts a gaze this near the camera as eye contact
        "camera_frames": 3,
        "lead": 0.07,                        # seconds the eyes start before the look (Erkelens 1989: about 90 ms)
        "duration": 0.25,                    # seconds, 5 to 95 %, each way (the coordinator's 0.2 to 0.3)
        "max_speed": 60.0,                   # degrees a second (natural gaze shifts reach 50 to 200, Erkelens 1989)
    },
    "pupil": {
        "iris_mm": 11.82,                    # the visible iris' diameter, to give the pupil in mm
        "reflex": {"peak": 0.12, "latency": 0.25, "hold": 0.75, "constrict": 0.3, "redilate": 2.4},
        "arousal": {"amplitude": 0.015, "rise": 1.0, "fall": 3.0, "low": 10.0, "high": 90.0},
        "chorus": {"amplitude": 0.015, "peak": 0.93, "n": 10.1},
        "near": {"per_dioptre": 0.01},
        "unrest": {"amplitude": 0.01, "low_hz": 0.1, "high_hz": 0.7, "waves": 6},
        "range": [-0.35, 0.5],
    },
    "keys": {
        "bone_deg": 0.05,                    # a bone's keys: straight lines between them miss no frame by more
        "morph": 0.001,                      # a morph's keys: the same in weight
        "position": 0.0005,                  # a light bone's keys: the same in place (model units)
        "limit": 20000,                      # MMD's registered points for a model: loading stops past them
        "reserve": 1000,                     # refused this near the limit (a later touch to the face would cross it)
    },
}


def merge_params(base, override, path="params"):
    """a copy of `base` with the values of `override` (the same shape; ValueError on a key `base` lacks)"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key not in out:
            raise ValueError("%s has no %r (it has %s)" % (path, key, ", ".join(sorted(out))))
        if isinstance(out[key], dict):
            if not isinstance(value, dict):
                raise ValueError("%s.%s is a group of values, not %r" % (path, key, value))
            out[key] = merge_params(out[key], value, path + "." + key)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ---- vectors --------------------------------------------------------------------------------

def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 0.0 else tuple(v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(a, k):
    return tuple(k * x for x in a)


def _degrees_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))))


def _between(a, b):
    """the shortest rotation taking the unit vector a onto the unit vector b"""
    d = _dot(a, b)
    if d < -0.999999:
        axis = _unit(_cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)))
        return (axis[0], axis[1], axis[2], 0.0)
    c = _cross(a, b)
    return fk.normalized((c[0], c[1], c[2], 1.0 + d))


def _angle(q):
    return math.degrees(2.0 * math.acos(min(1.0, abs(fk.normalized(q)[3]))))


def _about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def eye_rotation(yaw, pitch):
    """the rotation (as applied, in the head's frame) that turns -Z by yaw toward +X and pitch up (tools/eye_gaze.py)"""
    return fk.multiply(_about((0.0, 1.0, 0.0), -yaw), _about((1.0, 0.0, 0.0), pitch))


# ---- vergence -------------------------------------------------------------------------------

def vergence_degrees(distance_m, ipd_mm):
    """the turn of each eye toward a point straight ahead: atan((ipd / 2) / distance)"""
    return math.degrees(math.atan((ipd_mm / 2.0) / (distance_m * 1000.0)))


def vergence_turns(gaze, distance, half):
    """(right, left): the rotations (as applied, after the gaze, in the head's frame) that turn each eye from the gaze
    `gaze` onto the point `distance` along it; the right eye sits at -half on X, the left at +half (model units)"""
    g = _unit(gaze)
    target = tuple(distance * c for c in g)
    return tuple(_between(g, _unit(tuple(t - e for t, e in zip(target, (x, 0.0, 0.0))))) for x in (-half, half))


def _runs(mask):
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def fixation_targets(rows, params):
    """(metres, labels) per frame: what the eyes look at.  A row is {"camera": (degrees off the gaze, metres),
    "hands": [(degrees off the gaze, metres), ...]}; see the module docstring.  A frame bridged between two looks at a
    hand (gap_frames or fewer, no look at the camera between) is labelled "hand" with no distance (None)."""
    p = params
    cam_ok = [r["camera"][0] <= p["camera_deg"] for r in rows]
    hand = []
    for r in rows:
        fit = [h[:2] for h in r["hands"] if h[0] <= p["hand_deg"] and p["near_m"] <= h[1] <= p["hand_m"]]
        hand.append(min(fit) if fit else None)
    labels = []
    for i, r in enumerate(rows):
        options = []
        if cam_ok[i]:
            options.append((r["camera"][0] / p["camera_deg"], "camera"))
        if hand[i] is not None:
            options.append((hand[i][0] / p["hand_deg"], "hand"))
        labels.append(min(options)[1] if options else "free")
    looks = _runs([lab == "hand" for lab in labels])
    for (_, b0), (a1, _) in zip(looks, looks[1:]):
        if a1 - b0 - 1 <= p["gap_frames"] and not any(labels[i] == "camera" for i in range(b0 + 1, a1)):
            for i in range(b0 + 1, a1):
                labels[i] = "hand"
    for a, b in _runs([lab == "hand" for lab in labels]):
        if b - a + 1 < p["hand_frames"]:
            for i in range(a, b + 1):
                labels[i] = "camera" if cam_ok[i] else "free"
    for a, b in _runs([lab == "camera" for lab in labels]):
        if b - a + 1 < p["camera_frames"]:
            for i in range(a, b + 1):
                labels[i] = "free"
    metres = []
    for i, r in enumerate(rows):
        if labels[i] == "camera":
            metres.append(r["camera"][1])
        elif labels[i] == "hand" and hand[i] is not None:
            metres.append(hand[i][1])
        else:
            metres.append(None)
    return metres, labels


def _median(values):
    s = sorted(values)
    n = len(s)
    return 0.0 if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def vergence_demand(labels, metres, params):
    """degrees per eye wanted per frame: gain x atan((ipd / 2) / distance) through each run on a hand (its median
    distance, but not nearer than angle_near_m), 0 elsewhere (the camera and things far away are looked at with the
    eyes parallel)"""
    out = [0.0] * len(labels)
    for a, b in _runs([lab == "hand" for lab in labels]):
        seen = [m for m in metres[a:b + 1] if m is not None]
        if not seen:
            continue
        d = params["gain"] * vergence_degrees(max(params["angle_near_m"], _median(seen)), params["ipd_mm"])
        for i in range(a, b + 1):
            out[i] = d
    return out


def _min_jerk(s):
    s = min(1.0, max(0.0, s))
    return s * s * s * (10.0 + s * (6.0 * s - 15.0))


def vergence_in_phase(demands, labels, fps, lead, duration, max_speed):
    """the vergence per frame, in phase with the looks at a hand (each run of a demand above 0): a minimum-jerk rise
    that starts `lead` seconds before the run (not before the last frame on the camera ahead of it) and a fall that
    starts on the run's last frame, or early enough to be over before the next frame on the camera (`labels`); each
    has its 5 to 95 % time `duration` seconds or longer, so that its top speed stays under `max_speed` (degrees a
    second).  A run too short for both (a look between two looks at the camera) rises less: the rise and the fall
    cross below its demand.  Overlapping runs take the larger.  0 on every frame on the camera."""
    n = len(demands)
    out = [0.0] * n
    for a, b in _runs([d > 0.0 for d in demands]):
        top = demands[a]
        whole = max(duration / MIN_JERK_5_95, MIN_JERK_TOP * top / max_speed) * fps     # frames, each way
        start = a - lead * fps
        before = next((i for i in range(a - 1, max(-1, int(math.floor(start)) - 1), -1) if labels[i] == "camera"), None)
        if before is not None:
            start = max(start, float(before))
        stop = float(b)
        after = next((i for i in range(b + 1, min(n, b + 2 + int(math.ceil(whole)))) if labels[i] == "camera"), None)
        if after is not None:
            stop = min(stop, after - whole)
        for i in range(max(0, int(math.floor(start))), min(n, int(math.ceil(stop + whole)) + 1)):
            v = top * min(_min_jerk((i - start) / whole), 1.0 - _min_jerk((i - stop) / whole))
            out[i] = max(out[i], v)
    return [v + 0.0 for v in out]


# ---- the light ------------------------------------------------------------------------------

def toward_light(direction):
    """the unit vector toward MMD's light from the window's direction (where the light goes)"""
    return tuple(-c for c in _unit(direction))


def screen_basis(view):
    """(right, up): the screen's axes for a camera seen along `view` (the unit vector from the eye to the camera),
    with the world's +Y as up (a camera straight in front gives +X and +Y)"""
    right = _cross(view, UP)
    if math.sqrt(_dot(right, right)) < 1e-9:
        right = _cross(view, (0.0, 0.0, 1.0))
    right = _unit(right)
    return right, _cross(right, view)


def light_offset(half, axis, view, cornea, lag):
    """the light's centre minus the pupil's on the screen, in iris radii (right, up): cornea proj(half) - lag proj(axis),
    `half` the half-way direction between the light and the camera, `axis` the eye's, `view` toward the camera"""
    right, up = screen_basis(view)
    return (cornea * _dot(half, right) - lag * _dot(axis, right), cornea * _dot(half, up) - lag * _dot(axis, up))


def _across(v, view):
    return _sub(v, _scale(view, _dot(v, view)))


def _about_vector(w):
    """the rotation of the rotation vector w (radians)"""
    a = math.sqrt(_dot(w, w))
    if a < 1e-15:
        return fk.IDENTITY
    s = math.sin(a / 2.0) / a
    return fk.normalized((w[0] * s, w[1] * s, w[2] * s, math.cos(a / 2.0)))


def _soft_turn(q, cap):
    """the rotation q with its angle kept under `cap` degrees (soft_cap on the angle, the same axis)"""
    q = fk.normalized(q)
    if q[3] < 0.0:
        q = tuple(-c for c in q)
    angle = _angle(q)
    if angle < 1e-12:
        return q
    kept = soft_cap((angle, 0.0), cap)[0]
    return fk.power(q, kept / angle) if kept < angle else q


def light_turn(pivot, depth, radial, target, view, damping=0.15, steps=4, offset=None):
    """the turn (a rotation in the world, about `pivot`) that brings the point pivot + depth radial (+ `offset`, a
    vector that turns with it: the face's morphs on the light's quad) onto the camera's line through `target` (seen
    along `view`): damped least squares over the two turns across the line from the pivot to the point, `damping`
    times that length as the damping, a few Gauss-Newton steps.  Seen from the front it lands on the line; seen side
    on, where a turn hardly moves the light across the line of sight, the damping keeps the turn small."""
    p = _scale(_unit(radial), depth)
    if offset is not None:
        p = _add(p, offset)
    lam = (damping * math.sqrt(_dot(p, p))) ** 2
    total = fk.IDENTITY
    for _ in range(steps):
        r = _unit(p)
        a = _cross(r, view)
        if math.sqrt(_dot(a, a)) < 1e-9:
            a = _cross(r, UP)
        a = _unit(a)
        b = _cross(r, a)
        ja, jb = _across(_cross(a, p), view), _across(_cross(b, p), view)
        e = _across(_sub(target, _add(pivot, p)), view)
        aa, ab, bb = _dot(ja, ja) + lam, _dot(ja, jb), _dot(jb, jb) + lam
        ea, eb = _dot(ja, e), _dot(jb, e)
        det = aa * bb - ab * ab
        if det <= 0.0:
            break
        x, y = (bb * ea - ab * eb) / det, (aa * eb - ab * ea) / det
        step = _about_vector(_add(_scale(a, x), _scale(b, y)))
        total = fk.multiply(step, total)
        p = fk.rotate(step, p)
        if abs(x) + abs(y) < 1e-12:
            break
    return total


def _smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def hide_track(angles, start, end):
    """HL消 per frame from the angle between the light and the camera: 0 at `start`, 1 at `end`, smoothstep between"""
    return [_smoothstep((a - start) / (end - start)) + 0.0 for a in angles]


SOFT_FROM = 0.6                 # share of a cap up to which soft_cap passes values unchanged


def soft_cap(vec, cap):
    """the 2-vector with its length kept under cap: unchanged up to SOFT_FROM of it, along tanh beyond"""
    n = math.hypot(*vec)
    if n <= SOFT_FROM * cap or n == 0.0:
        return tuple(vec)
    span = 1.0 - SOFT_FROM
    k = cap * (SOFT_FROM + span * math.tanh((n / cap - SOFT_FROM) / span)) / n
    return tuple(c * k for c in vec)


def keep_on_iris(uv, drawn, reach):
    """a light's place on its iris (iris radii from the iris' centre, on the iris' own plane) kept within `reach`, or
    within `drawn` (its drawn radius) when that is further out: unchanged up to the knee (the drawn radius, or
    SOFT_FROM of the limit if further), along tanh from there to the limit (the same direction)"""
    n = math.hypot(*uv)
    limit = max(reach, drawn)
    knee = max(drawn, SOFT_FROM * limit)
    if n <= knee or n == 0.0:
        return tuple(uv)
    kept = knee + (limit - knee) * math.tanh((n - knee) / (limit - knee)) if limit > knee else limit
    return tuple(c * kept / n for c in uv)


def drawn_on_iris(dx, dy, up, normal, axis_y):
    """the drawn offset (dx across, dy up, model units) laid on the iris' plane (its unit normal `normal`, toward its
    front): up along the screen's up turned into that plane, across square to it (normal x up, the iris' own +X for an
    iris facing the camera, seen from in front or behind): it shrinks with the iris seen at a slant and does not turn
    with the head's roll.  `axis_y` (the iris' own Y) stands in when the screen's up runs along the normal."""
    rise = _sub(up, _scale(normal, _dot(up, normal)))
    if math.sqrt(_dot(rise, rise)) < 1e-6:
        rise = axis_y
    rise = _unit(rise)
    return _add(_scale(_cross(normal, rise), dx), _scale(rise, dy))


SEEN_COS = 0.1                  # a disc seen more than about 84 degrees off its normal (or from behind) is not seen


def disc_coordinates(camera, point, centre, x, y, normal, half_x, half_y):
    """where the camera's ray through `point` meets the plane of a disc (its centre, unit axes x and y and its normal
    toward its front), in the disc's half widths (u along x, v along y); None when the camera sees the disc edge on
    (the ray within SEEN_COS of the plane), from behind, or meets the plane behind the camera"""
    d = _sub(point, camera)
    den = _dot(d, normal)
    if -den < SEEN_COS * math.sqrt(_dot(d, d)):
        return None
    s = _dot(_sub(centre, camera), normal) / den
    if s <= 0.0:
        return None
    hit = _sub(_add(camera, _scale(d, s)), centre)
    return _dot(hit, x) / half_x, _dot(hit, y) / half_y


# ---- the pupil ------------------------------------------------------------------------------

def _first_order(targets, fps, narrowing, widening):
    """a follower of the targets with the time constant `narrowing` on the way down and `widening` on the way up;
    each frame moves toward that frame's target"""
    out, x = [], 0.0
    for t in targets:
        tau = narrowing if t < x else widening
        x += (t - x) * (1.0 - math.exp(-1.0 / (tau * fps)))
        out.append(x)
    return out


def _reflex_drive(n, flares, fps, latency, hold):
    """-1 through `hold` seconds from each flare's onset (`latency` after it), 0 elsewhere (frames after the onset)"""
    out = [0.0] * n
    for at in flares:
        onset = at + latency * fps
        for i in range(max(0, int(math.floor(onset)) + 1), min(n, int(math.floor(onset + hold * fps)) + 1)):
            out[i] = -1.0
    return out


def reflex_track(n, flares, fps, rx):
    """the pupil's change from the light reflex per frame (0 or below): see the module docstring.  `flares` are
    frames (floats)."""
    one = _first_order(_reflex_drive(int(10 * fps), [0.0], fps, rx["latency"], rx["hold"]), fps, rx["constrict"],
                       rx["redilate"])
    k = rx["peak"] / -min(one)
    drive = _reflex_drive(n, flares, fps, rx["latency"], rx["hold"])
    return [v * k + 0.0 for v in _first_order(drive, fps, rx["constrict"], rx["redilate"])]


def event_shape(t, peak, power):
    """the pupil's response to an event: (t / peak)^power e^(power (1 - t / peak)), 1 at t = peak, 0 at and before 0"""
    if t <= 0.0:
        return 0.0
    x = t / peak
    return math.exp(power * (math.log(x) + 1.0 - x))


def _follow(values, rise_frames, fall_frames):
    """a first-order follower with one time constant on the way up and another on the way down"""
    out, x = [], values[0] if values else 0.0
    for v in values:
        k = 1.0 / (rise_frames if v > x else fall_frames)
        x += (v - x) * (1.0 - math.exp(-k))
        out.append(x)
    return out


def pupil_track(n, flares, arousal, chorus, near, params, seed=0, fps=FPS):
    """the change of the pupil's diameter against the model's own, per frame, with its parts: {"total", "reflex",
    "arousal", "chorus", "near", "unrest"}.  `flares` and `chorus` are frames (floats), `arousal` the loudness per
    frame from 0 to 1 (or None), `near` the vergence's demand in dioptres per frame."""
    p = params
    reflex = reflex_track(n, flares, fps, p["reflex"])
    ar = p["arousal"]
    if arousal:
        env = _follow(list(arousal[:n]) + [arousal[-1]] * max(0, n - len(arousal)), ar["rise"] * fps, ar["fall"] * fps)
        lo, hi = min(env), max(env)
        mid = _median(env)
        span = (hi - lo) if hi > lo else 1.0
        arousal_part = [ar["amplitude"] * (v - mid) / span for v in env]
    else:
        arousal_part = [0.0] * n
    ch = p["chorus"]
    chorus_part = [0.0] * n
    for at in chorus:
        for i in range(max(0, int(math.floor(at)) + 1), n):
            chorus_part[i] += ch["amplitude"] * event_shape((i - at) / fps, ch["peak"], ch["n"])
    near_part = [-p["near"]["per_dioptre"] * max(0.0, d) for d in near]
    un = p["unrest"]
    rng = random.Random(seed)
    waves = [(rng.uniform(un["low_hz"], un["high_hz"]), rng.uniform(0.0, 2.0 * math.pi)) for _ in range(int(un["waves"]))]
    each = un["amplitude"] * math.sqrt(2.0 / len(waves)) if waves else 0.0
    unrest = [sum(each * math.sin(2.0 * math.pi * f * i / fps + ph) for f, ph in waves) + 0.0 for i in range(n)]
    low, high = p["range"]
    total = [min(high, max(low, a + b + c + d + e)) + 0.0
             for a, b, c, d, e in zip(reflex, arousal_part, chorus_part, near_part, unrest)]
    return {"total": total, "reflex": reflex, "arousal": arousal_part, "chorus": chorus_part, "near": near_part,
            "unrest": unrest}


def pupil_weights(change, big, thin):
    """(瞳大, 瞳細) per frame for the diameter changes: the radius goes to (1 + big w) with 瞳大 and (1 + thin w) with
    瞳細 (thin < 0)"""
    wb = [min(1.0, max(0.0, r / big)) + 0.0 if r > 0.0 else 0.0 for r in change]
    wt = [min(1.0, max(0.0, r / thin)) + 0.0 if r < 0.0 else 0.0 for r in change]
    return wb, wt


def pupil_scales(doc, big=BIG, thin=THIN, iris_material=pmx_eyes.IRIS_MATERIAL):
    """{"big", "thin"}: the change of the pupil's radius per unit weight of the two morphs, measured on the model (the
    median over the outer half of the pupil's vertices of the offset along the radius, across the line of sight, over
    the radius), and "ratio", the pupil's width over the iris' (the material iris_material) when the model has it"""
    morphs = pmx_eyes.vertex_morphs(doc)
    if big not in morphs or thin not in morphs:
        raise ValueError("the model lacks the pupil morphs %s / %s" % (big, thin))
    eyes, _ = pmx_eyes.find_eyes(doc)
    out = {}
    side = {v: pmx_eyes._eye_of(doc, v, eyes) for v in morphs[big]}
    centre = {}
    for e in eyes:
        pts = [doc.vertices[v].position() for v in morphs[big] if side[v] == e]
        centre[e] = tuple(sum(p[c] for p in pts) / len(pts) for c in range(3))
    radii = {}
    for v in morphs[big]:
        p, c = doc.vertices[v].position(), centre[side[v]]
        radii[v] = (p[0] - c[0], p[1] - c[1])
    top = max(math.hypot(*r) for r in radii.values())
    for key, name in (("big", big), ("thin", thin)):
        ratios = []
        for v, off in morphs[name].items():
            if v not in radii:
                continue
            r = radii[v]
            n = math.hypot(*r)
            if n >= 0.5 * top:
                ratios.append((off[0] * r[0] + off[1] * r[1]) / (n * n))
        if not ratios:
            raise ValueError("%s moves none of the pupil's vertices" % name)
        out[key] = _median(ratios)
    tri = pmx_eyes.material_triangles(doc, iris_material)
    if tri:
        iris = {v for t in tri for v in t}
        e = eyes[0]
        xs = [doc.vertices[v].position()[0] for v in iris if pmx_eyes._eye_of(doc, v, eyes) == e]
        ps = [doc.vertices[v].position()[0] for v in morphs[big] if side[v] == e]
        if xs and ps and max(xs) > min(xs):
            out["ratio"] = (max(ps) - min(ps)) / (max(xs) - min(xs))
    return out


def iris_heights(doc, eye_idx, material=pmx_eyes.IRIS_MATERIAL, cells=32):
    """{eye index: (x0, y0, dx, dy, rows, (its frontmost z, its deepest z))}: the frontmost z of the eye's iris (the
    material, rest pose) over a grid that covers its outline, rows[j][i] at (x0 + i dx, y0 + j dy); grid points off
    the iris take the nearest point on it"""
    tris = pmx_eyes.eye_surfaces(doc, eye_idx, (material,))
    out = {}
    for e in eye_idx:
        pts = [p for t in tris[e] for p in t]
        if not pts:
            continue
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        dx, dy = (x1 - x0) / cells, (y1 - y0) / cells
        rows = [[pmx_eyes.surface_z(tris[e], x0 + i * dx, y0 + j * dy) for i in range(cells + 1)] for j in range(cells + 1)]
        known = [(i, j, rows[j][i]) for j in range(cells + 1) for i in range(cells + 1) if rows[j][i] is not None]
        for j in range(cells + 1):
            for i in range(cells + 1):
                if rows[j][i] is None:
                    rows[j][i] = min(known, key=lambda k: (k[0] - i) ** 2 + (k[1] - j) ** 2)[2]
        out[e] = (x0, y0, dx, dy, rows, (min(min(r) for r in rows), max(max(r) for r in rows)))
    return out


def surface_at(heights, x, y):
    """the iris' frontmost z at (x, y) (rest pose): bilinear on the grid of iris_heights, held at its edges"""
    x0, y0, dx, dy, rows = heights[:5]
    n = len(rows) - 1
    u = min(float(n), max(0.0, (x - x0) / dx))
    v = min(float(n), max(0.0, (y - y0) / dy))
    i, j = min(n - 1, int(u)), min(n - 1, int(v))
    a, b = u - i, v - j
    return ((1 - a) * (1 - b) * rows[j][i] + a * (1 - b) * rows[j][i + 1]
            + (1 - a) * b * rows[j + 1][i] + a * b * rows[j + 1][i + 1])


def ride_on_iris(start, direction, heights, bone_position, bone_rotation, bone_rest, height, steps=4):
    """(the point start + s direction (direction a unit vector: the camera's line) that lies `height` in front of the
    iris' surface where it lies, the height it ends at).  The iris' rest frame is that of the bone it hangs on: at
    bone_position, turned by bone_rotation, resting at bone_rest.  s stays within the iris' size (0.5 units) of start."""
    inv = fk.conjugate(bone_rotation)
    ur = fk.rotate(inv, direction)

    def rest(point):
        return _add(bone_rest, fk.rotate(inv, _sub(point, bone_position)))
    s = 0.0
    for _ in range(steps):
        r = rest(_add(start, _scale(direction, s)))
        if abs(ur[2]) < 1e-6:
            break
        s = max(-0.5, min(0.5, s + (surface_at(heights, r[0], r[1]) - height - r[2]) / ur[2]))
    point = _add(start, _scale(direction, s))
    r = rest(point)
    return point, surface_at(heights, r[0], r[1]) - r[2]


def _rest_of(point, bone):
    """a world point in the rest frame of a bone (`bone` = (its position, its rotation, its rest position))"""
    return _add(bone[2], fk.rotate(fk.conjugate(bone[1]), _sub(point, bone[0])))


def _world_of(point, bone):
    return _add(bone[0], fk.rotate(bone[1], _sub(point, bone[2])))


def iris_hit(camera, point, heights, bone, shift=fk.ZERO, geo=None, step=0.01, halvings=14):
    """where the camera's line through `point` first meets the iris' surface (iris_heights, moved by `shift`: the
    face's morphs on the iris), in the rest frame of the bone the iris hangs on (`bone` = (position, rotation, rest
    position)); None when the line comes from behind or runs nearly along the surface, or misses it.  With `geo`
    (eye_geometry's) the surface is the iris' alone, within its outline (a line passing beside it misses it; one
    coming in behind its edge meets the edge).  Marched in `step` units through the depths the surface spans, then
    halved (a dish seen at a slant can meet the line twice: the camera sees the first)."""
    o = _rest_of(camera, bone)
    d = _sub(_rest_of(point, bone), o)
    t0 = math.sqrt(_dot(d, d))
    if t0 < 1e-9:
        return None
    d = _scale(d, 1.0 / t0)
    if d[2] < SEEN_COS / 2.0:
        return None
    near, deep = heights[5]

    def gap(t):
        q = _add(o, _scale(d, t))
        if geo is not None and math.hypot(*iris_uv(q, geo, shift)) > 1.0:
            return -1.0                                                # beside the iris: nothing there
        return q[2] - (surface_at(heights, q[0] - shift[0], q[1] - shift[1]) + shift[2])
    a = (near + shift[2] - 1e-4 - o[2]) / d[2]
    end = (deep + shift[2] + 1e-4 - o[2]) / d[2]
    fa = gap(a)
    if fa > 0.0:
        return None
    count = min(200, max(2, int(math.ceil((end - a) / step))))
    for k in range(1, count + 1):
        b = a + (end - a) * k / count if k < count else end
        fb = gap(b)
        if fb >= 0.0:
            lo, hi = b - (end - a) / count, b
            for _ in range(halvings):
                mid = (lo + hi) / 2.0
                if gap(mid) < 0.0:
                    lo = mid
                else:
                    hi = mid
            return _add(o, _scale(d, (lo + hi) / 2.0))
    return None


def iris_uv(rest_point, geo, shift=fk.ZERO):
    """a point of the iris (rest frame) in iris radii from the centre of its outline (eye_geometry's disc, moved by
    `shift`), across X and up Y"""
    return ((rest_point[0] - geo["disc"][0] - shift[0]) / geo["iris"][0],
            (rest_point[1] - geo["disc"][1] - shift[1]) / geo["iris"][1])


def iris_point(uv, heights, geo, bone, shift=fk.ZERO):
    """the world point of the iris' surface at `uv` (iris radii, iris_uv)"""
    x = geo["disc"][0] + shift[0] + uv[0] * geo["iris"][0]
    y = geo["disc"][1] + shift[1] + uv[1] * geo["iris"][1]
    return _world_of((x, y, surface_at(heights, x - shift[0], y - shift[1]) + shift[2]), bone)


# ---- the lids -------------------------------------------------------------------------------

def lid_mesh(doc, eye_idx, geometry, materials, morphs, across=3.0, front=0.6, back=0.4):
    """{eye index: the triangles of `materials` (names the model lacks are left out) about the eye's iris, as arrays}:
    a triangle is taken when a corner, at rest or moved by one of the vertex morphs `morphs` at full weight, lies within
    `across` iris widths across and up of the centre of the iris' outline, `front` units in front of its rim and `back`
    behind.  "tris" (T, 3) index "rest" (V, 3); "bones" (V, 4) index "names" (the bones they hang on) with "weights"
    (V, 4); "morphs" {name: (V, 3)} the offsets of the morphs of `morphs` that move them; "materials" the material of
    each triangle."""
    import numpy as np
    offsets = pmx_eyes.vertex_morphs(doc)
    moving = {m: offsets[m] for m in morphs if m in offsets}
    tris, of = [], {}
    for name in materials:
        for t in pmx_eyes.material_triangles(doc, name) or []:
            tris.append(t)
            of[len(tris) - 1] = name
    out = {}
    for e in eye_idx:
        geo = geometry[e]
        cx, cy, cz = geo["disc"]
        ix, iy = geo["iris"]
        near = {}

        def close(p):
            return abs(p[0] - cx) <= across * ix and abs(p[1] - cy) <= across * iy and -front <= p[2] - cz <= back

        def near_vertex(v):
            if v not in near:
                p = doc.vertices[v].position()
                near[v] = close(p) or any(v in o and close(_add(p, o[v])) for o in moving.values())
            return near[v]
        picked = [j for j, t in enumerate(tris) if any(near_vertex(v) for v in t)]
        mine = [tris[j] for j in picked]
        verts = sorted({v for t in mine for v in t})
        local = {v: k for k, v in enumerate(verts)}
        used, bones, weights = [], [], []
        for v in verts:
            pairs = [(b, w) for b, w in doc.vertices[v].pairs() if w > 0.0][:4]
            row_b, row_w = [], []
            for b, w in pairs:
                if b not in used:
                    used.append(b)
                row_b.append(used.index(b))
                row_w.append(w)
            total = sum(row_w) or 1.0
            bones.append(row_b + [0] * (4 - len(row_b)))
            weights.append([w / total for w in row_w] + [0.0] * (4 - len(row_w)))
        mesh = {"tris": np.array([[local[v] for v in t] for t in mine], dtype=np.int64).reshape(-1, 3),
                "rest": np.array([doc.vertices[v].position() for v in verts], dtype=float).reshape(-1, 3),
                "bones": np.array(bones, dtype=np.int64).reshape(-1, 4),
                "weights": np.array(weights, dtype=float).reshape(-1, 4),
                "names": [doc.bones[b].name for b in used],
                "bone_rest": np.array([doc.bones[b].position for b in used], dtype=float).reshape(-1, 3),
                "materials": [of[j] for j in picked], "morphs": {}}
        for m, o in moving.items():
            arr = np.array([o.get(v, (0.0, 0.0, 0.0)) for v in verts], dtype=float).reshape(-1, 3)
            if np.abs(arr).max(initial=0.0) > 0.0:
                mesh["morphs"][m] = arr
        out[e] = mesh
    return out


def _matrix(q):
    """the 3 x 3 matrix of the rotation q (columns: the turned axes)"""
    return [fk.rotate(q, (1.0, 0.0, 0.0)), fk.rotate(q, (0.0, 1.0, 0.0)), fk.rotate(q, (0.0, 0.0, 1.0))]


def pose_lids(mesh, world, weights):
    """the triangles of a lid_mesh at a frame, as (corner a, edge b - a, edge c - a) arrays: its morphs at `weights`
    ({name: weight}), each vertex skinned linearly by its bones at `world` ({bone name: (position, rotation)})"""
    import numpy as np
    x = mesh["rest"].copy()
    for m, arr in mesh["morphs"].items():
        w = weights.get(m, 0.0)
        if w:
            x += w * arr
    pos = np.array([world[n][0] for n in mesh["names"]], dtype=float).reshape(-1, 3)
    rot = np.array([_matrix(world[n][1]) for n in mesh["names"]], dtype=float).reshape(-1, 3, 3).transpose(0, 2, 1)
    y = np.zeros_like(x)
    for k in range(4):
        b = mesh["bones"][:, k]
        w = mesh["weights"][:, k]
        if not w.any():
            continue
        y += w[:, None] * (pos[b] + np.einsum("vij,vj->vi", rot[b], x - mesh["bone_rest"][b]))
    t = mesh["tris"]
    a = y[t[:, 0]]
    return a, y[t[:, 1]] - a, y[t[:, 2]] - a


def blocked(starts, ends, triangles):
    """per segment starts[k] -> ends[k] ((k, 3) arrays): whether it crosses one of the triangles (pose_lids' arrays;
    Moller and Trumbore, the ends themselves left out)"""
    import numpy as np
    a, e1, e2 = triangles
    starts = np.asarray(starts, dtype=float).reshape(-1, 3)
    ends = np.asarray(ends, dtype=float).reshape(-1, 3)
    if len(a) == 0:
        return np.zeros(len(starts), dtype=bool)
    d = ends - starts
    p = np.cross(d[:, None, :], e2[None, :, :])
    det = np.einsum("ktc,tc->kt", p, e1)
    ok = np.abs(det) > 1e-14
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = starts[:, None, :] - a[None, :, :]
    u = np.einsum("ktc,ktc->kt", s, p) * inv
    q = np.cross(s, e1[None, :, :])
    v = np.einsum("kc,ktc->kt", d, q) * inv
    t = np.einsum("tc,ktc->kt", e2, q) * inv
    return (ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 1e-6) & (t < 1.0 - 1e-6)).any(axis=1)


def slide_off_lids(clear, planned, drawn, steps=8):
    """(the place, the share of the way from the drawn place to the planned one) for a light whose planned place
    (iris radii, iris_uv) the lids cover: the furthest place along the straight way back to its drawn place that
    `clear(uv)` passes (bisection); the drawn place (share 0) when only it passes, None when it does not either"""
    if clear(drawn):
        lo, hi = 0.0, 1.0
        for _ in range(steps):
            mid = (lo + hi) / 2.0
            if clear(tuple(d + mid * (p - d) for p, d in zip(planned, drawn))):
                lo = mid
            else:
                hi = mid
        return tuple(d + lo * (p - d) for p, d in zip(planned, drawn)), lo
    return None


def closing_weights(doc, face, n, eye_idx):
    """{eye index: [the largest weight of the eye's closing morphs (pmx_eyes.closing_morphs) per frame]}"""
    closing = pmx_eyes.closing_morphs(doc, pmx_eyes.plan(doc)[0], pmx_eyes.REVEAL)
    out = {e: [0.0] * n for e in eye_idx}
    if face is None:
        return out
    keyed = {k.name for k in face.morphs}
    for name, eyes in closing.items():
        if name not in keyed:
            continue
        track = morph_track(face, name, n)
        for e in eyes:
            if e in out:
                out[e] = [max(a, b) for a, b in zip(out[e], track)]
    return out


def iris_shifts(doc, face, n, eye_idx, iris_material=pmx_eyes.IRIS_MATERIAL):
    """{eye index: [(dx, dy, dz) per frame]}: the mean move of the eye's iris vertices by the face's morphs (Sour's
    Rin's closing morphs push the iris back: 笑い 0.0275 a unit)"""
    offsets = pmx_eyes.vertex_morphs(doc)
    iris = sorted({v for t in pmx_eyes.material_triangles(doc, iris_material) or [] for v in t})
    own = {e: [v for v in iris if pmx_eyes._eye_of(doc, v, eye_idx) == e] for e in eye_idx}
    out = {e: [fk.ZERO] * n for e in eye_idx}
    if face is None:
        return out
    for name in sorted({k.name for k in face.morphs}):
        if name not in offsets or name in pmx_eyes.REVEAL:
            continue
        mean = {}
        for e in eye_idx:
            if own[e]:
                m = tuple(sum(offsets[name].get(v, (0.0, 0.0, 0.0))[c] for v in own[e]) / len(own[e]) for c in range(3))
                if any(abs(c) > 1e-9 for c in m):
                    mean[e] = m
        if not mean:
            continue
        track = morph_track(face, name, n)
        for e, m in mean.items():
            out[e] = [_add(s, _scale(m, w)) if w else s for s, w in zip(out[e], track)]
    return out


def morph_track(motion, name, n):
    """a morph's weight per frame as MMD shows it: straight between keys, held before the first and after the last"""
    keys = sorted((k for k in motion.morphs if k.name == name), key=lambda k: k.frame)
    if not keys:
        return [0.0] * n
    out, j = [], 0
    for f in range(n):
        while j + 1 < len(keys) and keys[j + 1].frame <= f:
            j += 1
        a = keys[j]
        if f <= a.frame or j + 1 == len(keys):
            out.append(float(a.weight))
        else:
            b = keys[j + 1]
            out.append(a.weight + (b.weight - a.weight) * (f - a.frame) / float(b.frame - a.frame))
    return out


def light_drags(doc, face, n, skip=pmx_eyes.REVEAL):
    """{light quad (bone) name: [(dx, dy, dz) per frame]}: how far the face's morphs move the quad's centre before its
    bone turns it (each keyed vertex morph that moves its vertices, but the reveal morphs `skip` the model is built
    with on, by the mean offset of its vertices times the weight)"""
    quads = pmx_eyes.plan(doc)[0]
    offsets = pmx_eyes.vertex_morphs(doc)
    keyed = sorted({k.name for k in face.morphs}) if face is not None else []
    moving = {}
    for name in keyed:
        if name in skip or name not in offsets:
            continue
        mine = {}
        for q in quads:
            shift = [sum(offsets[name].get(v, (0.0, 0.0, 0.0))[c] for v in q["vertices"]) / len(q["vertices"])
                     for c in range(3)]
            if any(abs(c) > 1e-9 for c in shift):
                mine[q["name"]] = shift
        if mine:
            moving[name] = mine
    tracks = {name: morph_track(face, name, n) for name in moving}
    out = {}
    for q in quads:
        rows = []
        for i in range(n):
            d = [0.0, 0.0, 0.0]
            for name, mine in moving.items():
                if q["name"] in mine:
                    w = tracks[name][i]
                    d = [a + w * b for a, b in zip(d, mine[q["name"]])]
            rows.append(tuple(d))
        out[q["name"]] = rows
    return out


def eye_geometry(doc, pupil_morph=pmx_eyes.PUPIL_MORPH, iris_material=pmx_eyes.IRIS_MATERIAL):
    """per eye index: {"pupil": the rest centre of the pupil morph's vertices, "iris": (half width across X, half
    height across Y) of the iris material, "disc": the centre of the iris' outline (the middle of its X and Y extents)
    on its frontmost plane (its rim, on a dish-shaped iris), "bone": the bone the iris hangs on (the heaviest bone of
    most of its vertices)}"""
    eyes, _ = pmx_eyes.find_eyes(doc)
    pupil = pmx_eyes.vertex_morphs(doc).get(pupil_morph) or {}
    iris = sorted({v for t in pmx_eyes.material_triangles(doc, iris_material) or [] for v in t})
    out = {}
    for e in eyes:
        pts = [doc.vertices[v].position() for v in pupil if pmx_eyes._eye_of(doc, v, eyes) == e]
        if not pts:
            raise ValueError("%s moves no vertex of %s: the pupil's centre is taken from it" % (pupil_morph, doc.bones[e].name))
        own = [v for v in iris if pmx_eyes._eye_of(doc, v, eyes) == e]
        if not own:
            raise ValueError("the model has no %s material on %s: the light's offsets are in iris radii"
                             % (iris_material, doc.bones[e].name))
        mine = [doc.vertices[v].position() for v in own]
        xs, ys = [p[0] for p in mine], [p[1] for p in mine]
        votes = {}
        for v in own:
            b = max(doc.vertices[v].pairs(), key=lambda bw: bw[1])[0]
            votes[b] = votes.get(b, 0) + 1
        out[e] = {"pupil": tuple(sum(p[c] for p in pts) / len(pts) for c in range(3)),
                  "iris": ((max(xs) - min(xs)) / 2.0, (max(ys) - min(ys)) / 2.0),
                  "disc": ((max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0, min(p[2] for p in mine)),
                  "bone": max(sorted(votes), key=lambda b: votes[b])}
    return out


# ---- measures -------------------------------------------------------------------------------

def _pct(values, q):
    s = sorted(values)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(round(q / 100.0 * (len(s) - 1))))]


def _r(value, places=4):
    return round(float(value), places) + 0.0


def step_stats(values, skip=()):
    """the change from one frame to the next (the length for vectors): its largest and its 99th percentile, leaving
    out the steps into the frames of `skip` and those from or to a None"""
    if len(values) < 2:
        return {"max": 0.0, "p99": 0.0}
    skip = set(skip)
    steps = []
    for i in range(1, len(values)):
        if i in skip:
            continue
        u, v = values[i - 1], values[i]
        if u is None or v is None:
            continue
        if isinstance(u, (tuple, list)):
            steps.append(math.sqrt(sum((b - a) ** 2 for a, b in zip(u, v))))
        else:
            steps.append(abs(v - u))
    if not steps:
        return {"max": 0.0, "p99": 0.0}
    return {"max": _r(max(steps), 5), "p99": _r(_pct(steps, 99), 5)}


def summary(values):
    if not values:
        return {}
    return {"min": _r(min(values)), "median": _r(_pct(values, 50)), "p95": _r(_pct(values, 95)), "max": _r(max(values))}


# ---- the motions ----------------------------------------------------------------------------

def merge(*motions):
    """the bone keys of motions loaded one after another: a later motion's keys replace the earlier ones of the same
    bone on the same frame"""
    by = {}
    for m in motions:
        mine = {}
        for k in m.bones:
            mine.setdefault(k.name, []).append(k)
        for name, keys in mine.items():
            frames = {k.frame for k in keys}
            by[name] = [k for k in by.get(name, []) if k.frame not in frames] + keys
    return vmd.Motion(model_name=motions[0].model_name, bones=[k for keys in by.values() for k in keys])


def check_overlaps(motions, bones, morphs):
    """ValueError when one of `motions` ({label: Motion}) keys a bone of `bones` or a morph of `morphs` beyond a
    resting key on frame 0 (identity, weight 0): MMD would mix them with this tool's keys"""
    problems = []
    for label, m in motions.items():
        for k in m.bones:
            if k.name in bones and not (k.frame == 0 and _angle(k.rotation) < 1e-4 and max(abs(c) for c in k.position) < 1e-6):
                problems.append("%s keys bone %s on frame %d" % (label, k.name, k.frame))
        for k in m.morphs:
            if k.name in morphs and not (k.frame == 0 and abs(k.weight) < 1e-9):
                problems.append("%s keys morph %s on frame %d" % (label, k.name, k.frame))
    if problems:
        raise ValueError("these keys would mix with eye_optics': %s%s" % ("; ".join(problems[:6]),
                                                                          " ..." if len(problems) > 6 else ""))


def _decimate(n, misses):
    """the indices of the keys to keep (the first and the last always): each span between two kept keys is as long as
    it can be while misses(a, b) says the straight line from a to b misses no value in between"""
    if n <= 2:
        return list(range(n))
    out, a = [0], 0
    while a < n - 1:
        b = a + 1
        while b + 1 < n and b + 1 - a <= MAX_SPAN and not misses(a, b + 1):
            b += 1
        out.append(b)
        a = b
    return out


def _bone_keys(name, frames, rotations, tolerance=0.05, positions=None, reach=0.0005):
    """a bone's keys (linear curves) where slerps between them stay within `tolerance` degrees of every frame's turn
    and, with `positions` (in the parent's frame), straight lines between them within `reach` of every frame's"""
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    q = [fk.normalized(r) for r in rotations]
    pos = list(positions) if positions is not None else [fk.ZERO] * len(q)

    def misses(a, b):
        for i in range(a + 1, b):
            t = (i - a) / float(b - a)
            if _angle(fk.multiply(fk.conjugate(fk.slerp(q[a], q[b], t)), q[i])) > tolerance:
                return True
            if positions is not None and math.sqrt(sum((pa + (pb - pa) * t - pi) ** 2
                                                       for pa, pb, pi in zip(pos[a], pos[b], pos[i]))) > reach:
                return True
        return False
    return [vmd.BoneKey(name, frames[i], tuple(round(c, 7) + 0.0 for c in pos[i]), tuple(round(c, 7) for c in fk.stored(q[i])),
                        straight) for i in _decimate(len(q), misses)]


def registration_points(morph_names, motions):
    """MMD's registered points for a model (`morph_names`, its morphs' names) after loading `motions` one after
    another: the keys on its morphs (one per morph and frame; names it lacks are not counted) and one for each of its
    morphs with no key on frame 0 (MMD keeps one there for every morph); bone keys are not counted.  MMD refuses to
    load past 20,000 (the dialog 「登録ポイント数が20000個を越えました」; stage 5 review Q5: this count
    met the refusal to the key in six probes)"""
    names = {fk.vmd_name(m) for m in morph_names}
    keys = set()
    for motion in motions:
        if motion is None:
            continue
        for k in motion.morphs:
            if k.name in names:
                keys.add((k.name, k.frame))
    zero = {name for name, frame in keys if frame == 0}
    return len(keys) + sum(1 for m in morph_names if fk.vmd_name(m) not in zero)


def _morph_keys(name, frames, weights, tolerance=0.001):
    """a morph's keys where straight lines between them stay within `tolerance` of every frame's weight (the first and
    the last alone for a weight that never changes)"""
    w = [float(v) for v in weights]
    if w and max(w) == min(w):
        return [vmd.MorphKey(name, frames[i], round(w[i], 6) + 0.0) for i in sorted({0, len(w) - 1})]

    def misses(a, b):
        for i in range(a + 1, b):
            if abs(w[a] + (w[b] - w[a]) * (i - a) / float(b - a) - w[i]) > tolerance:
                return True
        return False
    return [vmd.MorphKey(name, frames[i], round(w[i], 6) + 0.0) for i in _decimate(len(w), misses)]


# ---- everything -----------------------------------------------------------------------------

@dataclass
class Result:
    motion: vmd.Motion
    report: dict
    trace: dict = None          # per frame: what --trace writes


def _catchlights(model, handle, eyes):
    out = []
    names = {model.bones[e].name: e for e in eyes}
    sides = {v: k for k, v in pmx_eyes.SIDE_EN.items()}
    for b in model.bones:
        if not (b.name_en or "").startswith(pmx_eyes.EN_PREFIX):
            continue
        if not (b.append and b.append.get("parent") == handle and b.flags.get("append_rotate")):
            raise ValueError("the catchlight bone %s does not turn with %s by append" % (b.name, model.bones[handle].name))
        tag = b.name_en[len(pmx_eyes.EN_PREFIX):].split("_")
        side = sides.get(tag[1] if len(tag) > 1 else "")
        target = next((n for n in names if side and n.startswith(side)), None)
        if target is None:
            raise ValueError("cannot tell which eye the catchlight bone %s (%s) belongs to" % (b.name, b.name_en))
        tail = b.tail.get("offset") if b.tail else None
        depth = math.sqrt(_dot(tail, tail)) if tail else 0.0
        if depth <= 0.0:
            raise ValueError("the catchlight bone %s has no tail offset to its light (pmx_eyes sets it)" % b.name)
        out.append({"name": b.name, "index": b.index, "eye": target, "eye_index": names[target],
                    "share": float(b.append["ratio"]), "pivot": tuple(b.position), "depth": depth,
                    "rest": _add(b.position, tuple(tail))})
    if not out:
        raise ValueError("the model has no catchlight bones: make it with tools/pmx_eyes.py first")
    return out


def _cuts(cameras):
    out = set()
    for i in range(1, len(cameras)):
        (p0, d0), (p1, d1) = cameras[i - 1], cameras[i]
        if math.sqrt(_dot(_sub(p1, p0), _sub(p1, p0))) > CUT_JUMP or _degrees_between(d0, d1) > CUT_TURN:
            out.add(i)
    return out


def optics(model_bytes, dance, gaze, camera, params=None, flares=(), arousal=None, chorus=(), seed=0, face=None):
    """the eye optics motion and its report for the model (the bytes of a PMX made by pmx_eyes), the dance, the gaze
    (両目) and the camera; `flares` and `chorus` in seconds, `arousal` the loudness per frame from 0 to 1"""
    p = merge_params(PARAMS, {}) if params is None else params
    doc = pmx_edit.loads(model_bytes)
    model = pmx.loads(model_bytes)
    eye_idx, handle = pmx_eyes.find_eyes(doc)
    eyes = [model.bones[e].name for e in eye_idx]
    heads = {model.bones[e].parent for e in eye_idx}
    if len(heads) != 1 or None in heads:
        raise ValueError("the eyes %s do not share one parent" % "/".join(eyes))
    head_index = heads.pop()
    head = model.bones[head_index].name
    lights = _catchlights(model, handle, eye_idx)
    geometry = eye_geometry(doc)
    scales = pupil_scales(doc)
    names = {b.name for b in model.bones}
    vp, lp, pp = p["vergence"], p["light"], p["pupil"]
    hands = [s + h for s in ("右", "左") for h in vp["hand_points"] if s + h in names]
    motion = merge(dance, gaze)
    if not motion.bones:
        raise ValueError("the dance and the gaze have no bone keys")
    last = max(fk.last_frame(dance), fk.last_frame(gaze))
    frames = list(range(0, last + 1))
    n = len(frames)
    track = fk.world_track(model, motion, [head] + eyes + hands, 0, last)
    handle_track = fk.tracks_of(motion).get(model.bones[handle].name) or fk.tracks_of(motion).get(
        fk.vmd_name(model.bones[handle].name))
    handle_frames = [k.frame for k in handle_track] if handle_track else None
    cam_keys = fk.camera_keys(camera)
    cam_frames = [k.frame for k in cam_keys]
    unit_m = vp["unit_mm"] / 1000.0
    half = vp["ipd_mm"] / 2.0 / vp["unit_mm"]
    head_world, gaze_head, rows, cameras = [], [], [], []
    for i in range(n):
        hp, hr = track[head][i]
        inv = fk.conjugate(hr)
        per_eye = [fk.rotate(fk.multiply(inv, track[e][i][1]), FORWARD) for e in eyes]
        g_h = _unit(_add(*per_eye))
        g_w = fk.rotate(hr, g_h)
        centre = _scale(_add(track[eyes[0]][i][0], track[eyes[1]][i][0]), 0.5)
        state = fk.camera_at(cam_keys, frames[i], cam_frames)
        c = fk.camera_position(state)
        to_cam = _sub(c, centre)
        row = {"camera": (_degrees_between(g_w, to_cam), math.sqrt(_dot(to_cam, to_cam)) * unit_m), "hands": []}
        for h in hands:
            to_hand = _sub(track[h][i][0], centre)
            row["hands"].append((_degrees_between(g_w, to_hand), math.sqrt(_dot(to_hand, to_hand)) * unit_m, h))
        rows.append(row)
        head_world.append((hp, hr))
        gaze_head.append(g_h)
        cameras.append((c, fk.camera_direction(state)))
    cuts = _cuts(cameras)
    # vergence
    metres, labels = fixation_targets(rows, vp)
    demand = vergence_demand(labels, metres, vp)
    angle = vergence_in_phase(demand, labels, FPS, vp["lead"], vp["duration"], vp["max_speed"])
    turns = []
    for g, a in zip(gaze_head, angle):
        turns.append(vergence_turns(g, half / math.tan(math.radians(a)), half) if a > 1e-9 else (fk.IDENTITY, fk.IDENTITY))
    eye_keys = []
    for k, e in enumerate(eyes):
        eye_keys += _bone_keys(e, frames, [t[k] for t in turns], p["keys"]["bone_deg"])
    # the irises as they turn (with the vergence on the eyes): the bone each hangs on
    iris_bones = [model.bones[geometry[e]["bone"]].name for e in eye_idx]
    iris_track = fk.world_track(model, merge(dance, gaze, vmd.Motion(model_name=dance.model_name, bones=eye_keys)),
                                sorted(set(iris_bones)), 0, last)
    # the face's morphs on the light quads, and the irises' surfaces the lights ride on
    drags = light_drags(doc, face, n)
    heights = iris_heights(doc, eye_idx)
    drawn_height = {c["name"]: max(pmx_eyes.MARGIN / 2.0, surface_at(heights[c["eye_index"]], c["rest"][0], c["rest"][1])
                                   - c["rest"][2]) for c in lights if c["eye_index"] in heights}
    iris_rest = {e: model.bones[geometry[e]["bone"]].position for e in eye_idx}
    # the lids over each iris (moved by the face's morphs), the iris moved by them, how far they close each eye
    keyed = sorted({k.name for k in face.morphs}) if face is not None else []
    weights_of = {m: morph_track(face, m, n) for m in keyed}
    covering = list(lp["guard"]) + [m for m in lp["lids"] if m not in lp["guard"]]
    meshes = lid_mesh(doc, eye_idx, geometry, covering, keyed) if covering else {}
    lid_bones = sorted({b for m in meshes.values() for b in m["names"]})
    lid_world = fk.world_track(model, motion, lid_bones, 0, last) if lid_bones else {}
    masks = {e: ([m in lp["lids"] for m in mesh["materials"]], [m in lp["guard"] for m in mesh["materials"]])
             for e, mesh in meshes.items()}
    shifts = iris_shifts(doc, face, n, eye_idx)
    closing = closing_weights(doc, face, n, eye_idx)
    around = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
    # the light
    light = toward_light(lp["direction"])
    cornea = lp["cornea_radius_mm"] / lp["iris_radius_mm"]
    lag = lp["pupil_to_centre_mm"] / lp["iris_radius_mm"]
    rest_half = _unit(_add(light, FORWARD))
    rest_offset = light_offset(rest_half, FORWARD, FORWARD, cornea, lag)
    head_rest = model.bones[head_index].position
    side_of = {e: k for k, e in enumerate(eye_idx)}
    drawn = {}
    for c in lights:
        geo = geometry[c["eye_index"]]
        d = _sub(c["rest"], geo["disc"])
        drawn[c["name"]] = (d[0] / geo["iris"][0], d[1] / geo["iris"][1])
    import numpy as np
    masks = {e: (np.array(lid, dtype=bool), np.array(guard, dtype=bool)) for e, (lid, guard) in masks.items()}
    keys_q = {c["name"]: [] for c in lights}
    keys_t = {c["name"]: [] for c in lights}
    rides = {c["name"]: [] for c in lights}
    discs = {c["name"]: [] for c in lights}
    irises = {c["name"]: [] for c in lights}
    ahead = {c["name"]: [] for c in lights}
    screen = {c["name"]: [] for c in lights}
    lid_state = {c["name"]: [] for c in lights}
    rim = {c["name"]: [] for c in lights}           # (the formula's radius on the disc, the rim's push back) or None
    slid = {c["name"]: [] for c in lights}          # how far the lids moved the light (iris radii)
    guarded = {c["name"]: [0, 0] for c in lights}     # light-frames brought down onto the iris, and behind it
    off_iris = {c["name"]: 0 for c in lights}         # light-frames put behind the iris: no place of it held them
    sinks = {c["name"]: [] for c in lights}
    off_camera, off_axis, sideways, aside_of = [], [], [], []
    for i in range(n):
        hp, hr = head_world[i]
        inv = fk.conjugate(hr)
        q_handle = fk.applied(fk.sample(handle_track, frames[i], handle_frames)[1]) if handle_track else fk.IDENTITY
        cam = cameras[i][0]
        per_eye = {}
        alphas, axes_off, asides = [], [], []
        posed = {}
        cam_np = np.array(cam, dtype=float)

        def lids_over(e):
            """the lids' and the guard's triangles over eye e at this frame"""
            if e not in posed:
                if e in meshes:
                    world_i = {b: lid_world[b][i] for b in meshes[e]["names"]}
                    a, e1, e2 = pose_lids(meshes[e], world_i, {m: weights_of[m][i] for m in keyed})
                    lid, guard = masks[e]
                    posed[e] = ((a[lid], e1[lid], e2[lid]), (a[guard], e1[guard], e2[guard]))
                else:
                    empty = np.zeros((0, 3))
                    posed[e] = ((empty, empty, empty), (empty, empty, empty))
            return posed[e]
        for e in eye_idx:
            k = side_of[e]
            eye_local = fk.multiply(turns[i][k], fk.multiply(inv, track[eyes[k]][i][1]))   # the vergence key on top
            axis = fk.rotate(fk.multiply(hr, eye_local), FORWARD)
            bp, bq = iris_track[iris_bones[k]][i]
            disc = (_add(bp, fk.rotate(bq, _sub(geometry[e]["disc"], model.bones[geometry[e]["bone"]].position))),
                    fk.rotate(bq, (1.0, 0.0, 0.0)), fk.rotate(bq, (0.0, 1.0, 0.0)), fk.rotate(bq, FORWARD))
            view = _unit(_sub(cam, disc[0]))
            h = _unit(_add(light, view))
            now = light_offset(h, axis, view, cornea, lag)
            moved = soft_cap((now[0] - rest_offset[0], now[1] - rest_offset[1]), lp["cap"])
            aside = _smoothstep((_degrees_between(view, disc[3]) - lp["side"][0]) / (lp["side"][1] - lp["side"][0]))
            per_eye[e] = (disc, view, moved, aside, (bp, bq))
            alphas.append(_degrees_between(light, view))
            axes_off.append(_degrees_between(h, axis))
            asides.append(aside)
        off_camera.append(sum(alphas) / len(alphas))
        off_axis.append(sum(axes_off) / len(axes_off))
        sideways.append(max(asides))
        aside_of.append(asides)
        for c in lights:
            e = c["eye_index"]
            (centre, ax, ay, normal), view, moved, side, (bp, bq) = per_eye[e]
            geo = geometry[e]
            ix, iy = geo["iris"]
            bone = (bp, bq, iris_rest[e])
            moved_iris = shifts[e][i]
            u0, v0 = drawn[c["name"]]
            fallback = fk.power(q_handle, c["share"])
            pivot = _add(hp, fk.rotate(hr, _sub(c["pivot"], head_rest)))
            right, up = screen_basis(view)
            drag = fk.rotate(fk.multiply(hr, fallback), drags[c["name"]][i])     # the face's morphs on its quad
            base = _add(centre, drawn_on_iris(u0 * ix, v0 * iy, up, normal, ay))           # its drawn place, on the iris
            target = drawn_target = _add(base, drag)
            pushed = None

            def on_disc(duv):
                """the point of the rim's plane at duv (iris radii): the camera's line through it is a place on the iris"""
                return _add(centre, _add(_scale(ax, duv[0] * ix), _scale(ay, duv[1] * iy)))

            def seen_at(duv):
                """(the rest point, its iris radii) where the camera's line through on_disc(duv) first meets the iris"""
                hit = iris_hit(cam, on_disc(duv), heights[e], bone, moved_iris, geo)
                return None if hit is None else (hit, iris_uv(hit, geo, moved_iris))

            def held_seen(duv):
                """the iris as the camera sees it: a dish seen at a slant shows its deep side off where the rim's plane
                puts it; duv held back, along the camera's rays, until the camera's line meets the iris within the
                reach (or the light's drawn radius, if further out): toward the centre of the rim's plane (which keeps
                it within the reach there too); where that is not seen on the iris, toward the first place on the way
                to where the iris' centre shows that is, within the reach on the plane; failing that, toward there"""
                if not lp["seen"]:
                    return duv
                limit = max(lp["reach"], math.hypot(u0, v0))

                def inside(p):
                    got = seen_at(p)
                    return got is not None and math.hypot(*got[1]) <= limit
                if inside(duv):
                    return duv
                mid_iris = disc_coordinates(cam, iris_point((0.0, 0.0), heights[e], geo, bone, moved_iris),
                                            centre, ax, ay, normal, ix, iy)
                anchors = [(0.0, 0.0)]
                if mid_iris is not None:
                    # on the way to where the iris' centre shows, the first place both seen on the iris and within the
                    # reach on the rim's plane (the way from it to duv stays within the reach there), then that place
                    anchors += [tuple(t * m for m in mid_iris) for t in (0.25, 0.5, 0.75, 1.0)
                                if math.hypot(*mid_iris) * t <= lp["reach"]] + [mid_iris]
                for anchor in anchors:
                    if not inside(anchor):
                        continue
                    lo, hi = 0.0, 1.0
                    for _ in range(12):
                        mid = (lo + hi) / 2.0
                        if inside(tuple(a + mid * (d - a) for a, d in zip(anchor, duv))):
                            lo = mid
                        else:
                            hi = mid
                    return tuple(a + lo * (d - a) for a, d in zip(anchor, duv))
                return duv
            at = disc_coordinates(cam, base, centre, ax, ay, normal, ix, iy)
            if side < 1.0:
                want = _add(_add(base, drag), _add(_scale(right, moved[0] * ix), _scale(up, moved[1] * iy)))
                uv = disc_coordinates(cam, want, centre, ax, ay, normal, ix, iy)       # as MMD will show it
                if uv is not None and at is not None:
                    kept = held_seen(keep_on_iris(uv, math.hypot(*at), lp["reach"]))
                    want = on_disc(kept)
                    pushed = (math.hypot(*uv), math.hypot(*uv) - math.hypot(*kept))
                target = _add(_scale(want, 1.0 - side), _scale(target, side))
            # the lids: keep the light where they leave its iris uncovered, back toward its drawn place (on the iris
            # as above); where they cover that too (an eye looking up under its lid, a lid coming down), there, as
            # the model has it, under the lid
            state, moved_by = 1.0, 0.0
            if meshes and side < 1.0 and at is not None:
                planned = disc_coordinates(cam, target, centre, ax, ay, normal, ix, iy)
                at_drawn = disc_coordinates(cam, drawn_target, centre, ax, ay, normal, ix, iy)
                if at_drawn is not None:
                    at_drawn = held_seen(keep_on_iris(at_drawn, math.hypot(*at), lp["reach"]))
                if planned is not None and at_drawn is not None:
                    lid_tris = lids_over(e)[0]

                    def clear(duv, margin=lp["lid_margin"]):
                        got = seen_at(duv)
                        if got is None:
                            return False
                        hit, s_uv = got
                        ends = [_world_of(hit, bone)] + [iris_point((s_uv[0] + du * margin, s_uv[1] + dv * margin),
                                                                    heights[e], geo, bone, moved_iris)
                                                         for du, dv in around if margin > 0.0]
                        return not blocked(np.repeat(cam_np[None, :], len(ends), axis=0), ends, lid_tris).any()
                    if not clear(planned):
                        got = slide_off_lids(clear, planned, at_drawn) or (tuple(at_drawn), 0.0)
                        target = on_disc(got[0])
                        state, moved_by = got[1], math.hypot(got[0][0] - planned[0], got[0][1] - planned[1])
            # where the camera sees the iris so much at a slant that no place of it holds the light (its dish hides
            # its own centre), the light would hang beside the iris: it goes behind it (below)
            unseen = False
            if lp["seen"] and at is not None:
                final = disc_coordinates(cam, target, centre, ax, ay, normal, ix, iy)
                got = seen_at(final) if final is not None else None
                unseen = got is None or math.hypot(*got[1]) > 1.0
                if unseen:
                    # behind the iris on the camera's line through where its centre shows (the iris covers it there;
                    # beside the iris, in the socket, nothing may)
                    mid_iris = disc_coordinates(cam, iris_point((0.0, 0.0), heights[e], geo, bone, moved_iris),
                                                centre, ax, ay, normal, ix, iy)
                    if mid_iris is not None and seen_at(mid_iris) is not None:
                        target = on_disc(mid_iris)
            radial = fk.rotate(fk.multiply(hr, fallback), FORWARD)     # where the append alone points the light
            turn = light_turn(pivot, c["depth"], radial, target, _unit(_sub(cam, target)), lp["damping"], offset=drag)
            key = _soft_turn(fk.multiply(inv, fk.multiply(turn, hr)), lp["key_cap"])   # the turn in the head
            keys_q[c["name"]].append(key)
            turned = fk.multiply(hr, fk.multiply(key, fallback))
            bare = _add(pivot, _scale(fk.rotate(turned, FORWARD), c["depth"]))        # without the face's morphs
            dragged = fk.rotate(turned, drags[c["name"]][i])

            def ride(wanted, dragged_too=False):
                """the bone's move that puts the light on the camera's line through its target, `wanted` in front of
                its iris' surface (the face's morphs on its quad left out, or with them: `dragged_too`), and the
                height it ends at; at most light.ride_cap, and as much further as it is put behind the surface"""
                start = target if dragged_too else _sub(target, dragged)
                place, got = ride_on_iris(start, _unit(_sub(cam, target)), heights[e], bp, bq, iris_rest[e], wanted)
                move = _sub(place, _add(bare, dragged) if dragged_too else bare)
                size = math.sqrt(_dot(move, move))
                cap = lp["ride_cap"] + max(0.0, -wanted)
                return (_scale(move, cap / size) if size > cap else move), got
            shift, height = fk.ZERO, None
            if lp["ride"] and c["name"] in drawn_height and side < 1.0:
                # on the camera's line through its target, at the height it was drawn in front of its iris' surface
                shift, height = ride(drawn_height[c["name"]])
            spot = _add(_add(bare, shift), dragged)                            # as MMD shows it
            # the guard: nothing of the lids, the face or the hair between the light and its iris behind it (else it
            # would show on them): the light is brought down onto its iris, under them; failing that, behind it
            depth = 0
            forced = unseen and lp["ride"] and c["name"] in drawn_height
            if forced:
                depth = 2
                shift, height = ride(-(lp["hide_depth"] + moved_iris[2]), dragged_too=True)
                spot = _add(_add(bare, shift), dragged)
                off_iris[c["name"]] += 1
            for wanted in ((lp["hug_height"] - moved_iris[2]), -(lp["hide_depth"] + moved_iris[2])):
                if forced:
                    break
                behind = iris_hit(cam, spot, heights[e], bone, moved_iris)
                back = _world_of(behind, bone) if behind is not None else None
                ray = _unit(_sub(spot, cam))
                if back is None or _dot(_sub(back, spot), ray) <= 0.0 or not lp["ride"] or c["name"] not in drawn_height:
                    break                                                  # behind its iris already, or not seen
                across = _unit(_cross(ray, UP if abs(ray[1]) < 0.9 else (1.0, 0.0, 0.0)))
                rise = _cross(across, ray)
                offs = [fk.ZERO] + [_add(_scale(across, du * lp["guard_margin"]), _scale(rise, dv * lp["guard_margin"]))
                                    for du, dv in around]
                if not blocked([_add(spot, o) for o in offs], [_add(back, o) for o in offs], lids_over(e)[1]).any():
                    break
                depth += 1
                shift, height = ride(wanted, dragged_too=True)
                spot = _add(_add(bare, shift), dragged)
            behind = iris_hit(cam, spot, heights[e], bone, moved_iris, geo)        # None: not over the iris
            if depth and not forced:
                guarded[c["name"]][depth - 1] += 1
            sinks[c["name"]].append(depth)
            keys_t[c["name"]].append(fk.rotate(inv, shift))                    # the bone's move, in the head's frame
            rides[c["name"]].append(height)
            lid_state[c["name"]].append(state)
            slid[c["name"]].append(moved_by)
            rim[c["name"]].append(pushed)
            uv = disc_coordinates(cam, spot, centre, ax, ay, normal, ix, iy)
            discs[c["name"]].append(uv)
            irises[c["name"]].append(None if behind is None or uv is None else iris_uv(behind, geo, moved_iris))
            ahead[c["name"]].append(_dot(_sub(spot, centre), normal))
            seen_from = _sub(spot, centre)                                 # as the camera sees it, off the iris' centre
            screen[c["name"]].append((_dot(seen_from, right) / ix, _dot(seen_from, up) / iy))
    hide = hide_track(off_camera, lp["hide"][0], lp["hide"][1])
    # the pupil
    near = [1.0 / (half * unit_m / math.tan(math.radians(a))) if a > 1e-9 else 0.0 for a in angle]
    flare_frames = [t * FPS - SHOWN for t in flares]
    chorus_frames = [t * FPS - SHOWN for t in chorus]
    pupil = pupil_track(n, flare_frames, arousal, chorus_frames, near, pp, seed)
    big, thin = pupil_weights(pupil["total"], scales["big"], scales["thin"])
    # the motion
    keys = list(eye_keys)
    for c in lights:
        keys += _bone_keys(c["name"], frames, keys_q[c["name"]], p["keys"]["bone_deg"], keys_t[c["name"]],
                           p["keys"]["position"])
    tol = p["keys"]["morph"]
    morphs = _morph_keys(BIG, frames, big, tol) + _morph_keys(THIN, frames, thin, tol) + _morph_keys(HIDE, frames, hide, tol)
    out = vmd.Motion(model_name=dance.model_name, bones=keys, morphs=morphs)
    # MMD's registered points with the dance, the face and the gaze: refused near the limit
    registered = registration_points([pmx_eyes.morph_name(doc, m) for m in doc.morphs], [dance, face, gaze, out])
    limit = p["keys"]["limit"]
    if registered > limit - p["keys"]["reserve"]:
        raise ValueError("the dance, the face, the gaze and this motion would register %d points of the model's morphs: "
                         "MMD stops loading past %d (keys.limit; refused within keys.reserve %d of it): thin out the "
                         "face's morph keys" % (registered, limit, p["keys"]["reserve"]))
    # the report
    counts = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    hand_runs = []
    for a, b in _runs([lab == "hand" for lab in labels]):
        best = min((h for i in range(a, b + 1) for h in rows[i]["hands"]), key=lambda h: h[0])
        seen_m = [m for m in metres[a:b + 1] if m is not None]
        later = angle[b + 1:min(n, b + 31)]
        hand_runs.append({"first": frames[a], "last": frames[b], "seconds": _r((b - a + 1) / FPS, 3),
                          "median_m": _r(_median(seen_m), 3), "point": best[2], "demand_degrees": _r(demand[a], 3),
                          "reached_within_degrees": _r(max(angle[a:b + 1]), 3),
                          "reached_after_degrees": _r(max(later) if later else 0.0, 3),
                          "peak_frame": frames[max(range(max(0, a - 10), min(n, b + 31)), key=lambda j: angle[j])]})
    total = sum(angle) or 1.0
    share = {lab: _r(sum(a for a, l_ in zip(angle, labels) if l_ == lab) / total, 4) for lab in sorted(counts)}
    first = lights[0]["name"]
    key_angles = [_angle(q) for q in keys_q[first]]
    seen = {name: [uv for uv in rows_ if uv is not None] for name, rows_ in discs.items()}
    moved = [math.hypot(uv[0] - drawn[first][0], uv[1] - drawn[first][1]) for uv in seen[first]]
    radii = [math.hypot(*uv) for name in seen for uv in seen[name]]
    fronts = [a for name in ahead for a in ahead[name]]
    mm0 = pp["iris_mm"] * scales.get("ratio", 0.25)
    geo0 = geometry[eye_idx[0]]
    # the open eye: its closing morphs at OPEN_LID or less and its iris facing the camera (not handed over aside)
    open_rows = {}
    for c in lights:
        k = side_of[c["eye_index"]]
        open_rows[c["name"]] = [i for i in range(n) if closing[c["eye_index"]][i] <= OPEN_LID and aside_of[i][k] == 0.0
                                and discs[c["name"]][i] is not None]
    open_disc = [math.hypot(*discs[name][i]) for name in open_rows for i in open_rows[name]]
    open_iris = [math.hypot(*irises[name][i]) for name in open_rows for i in open_rows[name] if irises[name][i] is not None]
    rim_report = {}
    for name, rows_ in open_rows.items():
        pushes = [rim[name][i] for i in rows_ if rim[name][i] is not None]
        count = max(1, len(pushes))
        rim_report[name] = {"open_frames": len(rows_),
                            "wanted_beyond_iris": _r(sum(1 for w, _ in pushes if w > 1.0) / count),
                            "pushed_over_0.1": _r(sum(1 for _, s in pushes if s > 0.1) / count),
                            "pushed_over_0.2": _r(sum(1 for _, s in pushes if s > 0.2) / count)}
    lids_report = {name: {"slid_frames": sum(1 for s in lid_state[name] if 0.0 < s < 1.0),
                          "at_drawn_frames": sum(1 for s in lid_state[name] if s == 0.0),
                          "slid_max": _r(max(slid[name]) if slid[name] else 0.0),
                          "onto_iris_frames": guarded[name][0], "behind_iris_frames": guarded[name][1],
                          "beside_iris_frames": off_iris[name]}
                   for name in lid_state}
    report = {
        "frames": [frames[0], frames[-1]], "seed": seed, "params": p,
        "model": {"head": head, "eyes": eyes, "handle": model.bones[handle].name, "share": lights[0]["share"],
                  "catchlights": [{k: c[k] for k in ("name", "eye", "share", "depth")} for c in lights],
                  "iris_radius": [_r(v, 5) for v in geo0["iris"]],
                  "pupil_scales": {k: _r(v, 4) for k, v in scales.items()},
                  "pupil_mm": _r(mm0, 3), "half_ipd_units": _r(half, 5)},
        "vergence": {"labels": counts, "hand_runs": hand_runs, "degrees": summary(angle), "demand": summary(demand),
                     "step": step_stats(angle), "share": share,
                     "camera_max_degrees": _r(max([a for a, l_ in zip(angle, labels) if l_ == "camera"] or [0.0]), 4)},
        "light": {"cornea": cornea, "lag": lag, "rest_offset": [_r(v) for v in rest_offset],
                  "drawn": {k: [_r(v) for v in d] for k, d in drawn.items()},
                  "moved": summary(moved), "cuts": len(cuts),
                  "disc_r": summary(radii), "unseen_frames": sum(len(r) for r in discs.values()) - len(radii),
                  "open": {"light_frames": len(open_disc), "disc_r": summary(open_disc), "iris_r": summary(open_iris)},
                  "rim": rim_report, "lids": lids_report,
                  "ahead": summary(fronts), "behind_rim_plane_frames": sum(1 for a in fronts if a < 0.0),
                  "offset_step": step_stats(discs[first]), "offset_step_without_cuts": step_stats(discs[first], cuts),
                  "screen_step_without_cuts": {c["name"]: step_stats(screen[c["name"]], cuts) for c in lights},
                  "key_step": step_stats(key_angles), "key_step_without_cuts": step_stats(key_angles, cuts),
                  "camera_aside": {"frames_partly": sum(1 for s in sideways if s > 0.0),
                                   "frames_fully": sum(1 for s in sideways if s >= 1.0)},
                  "bone": first},
        "fade": {"light_off_camera": summary(off_camera), "frames_on": sum(1 for h in hide if h > 0.0),
                 "frames_half": sum(1 for h in hide if h >= 0.5), "frames_full": sum(1 for h in hide if h >= 0.999),
                 "step": step_stats(hide), "step_without_cuts": step_stats(hide, cuts),
                 "half_off_axis": summary(off_axis),
                 "frames_beyond_cornea": sum(1 for a in off_axis if a > 48.0)},
        "pupil": {"flares_s": list(flares), "chorus_s": list(chorus), "relative": summary(pupil["total"]),
                  "mm": summary([mm0 * (1.0 + r) for r in pupil["total"]]),
                  "parts": {k: {"min": _r(min(v)), "max": _r(max(v))} for k, v in pupil.items() if k != "total"},
                  "steps": {"relative": step_stats(pupil["total"]), BIG: step_stats(big), THIN: step_stats(thin),
                            "mm": step_stats([mm0 * r for r in pupil["total"]])},
                  "weights": {BIG: _r(max(big)), THIN: _r(max(thin))}},
        "ride": {"on": bool(lp["ride"]), "drawn_height": {k: _r(v, 5) for k, v in drawn_height.items()},
                 "move": summary([math.sqrt(_dot(t, t)) for name in keys_t for t in keys_t[name]]),
                 "height": summary([h for name in rides for h in rides[name] if h is not None]),
                 "face": face is not None},
        "keys": {"bones": len(keys), "morphs": len(morphs), "registered": registered, "limit": limit,
                 "margin": limit - registered},
    }
    names_ = [c["name"] for c in lights]

    def _uv(uv):
        return None if uv is None else [_r(uv[0], 4), _r(uv[1], 4)]
    trace = {"frames": frames, "label": labels, "vergence": [_r(a, 4) for a in angle],
             "light": [_uv(uv) for uv in discs[first]], "lights": names_,
             "screen": [[_uv(screen[name][i]) for name in names_] for i in range(n)],
             "disc": [[_uv(discs[name][i]) for name in names_] for i in range(n)],
             "iris": [[_uv(irises[name][i]) for name in names_] for i in range(n)],
             "lid": [[_r(lid_state[name][i], 3) for name in names_] for i in range(n)],
             "sink": [[sinks[name][i] for name in names_] for i in range(n)],
             "closing": [[_r(closing[e][i], 3) for e in eye_idx] for i in range(n)],
             "ahead": [[_r(ahead[name][i], 5) for name in names_] for i in range(n)], "hide": [_r(h, 4) for h in hide],
             "height": [[None if rides[name][i] is None else _r(rides[name][i], 5) for name in names_] for i in range(n)],
             "pupil": [_r(r, 5) for r in pupil["total"]], "camera_aside": [_r(s, 4) for s in sideways],
             "light_off_camera": [_r(a, 2) for a in off_camera], "half_off_axis": [_r(a, 2) for a in off_axis],
             "eye_centre": [[_r(c, 4) for c in _scale(_add(track[eyes[0]][i][0], track[eyes[1]][i][0]), 0.5)]
                            for i in range(n)],
             "camera": [[_r(c, 4) for c in cameras[i][0]] for i in range(n)], "cuts": sorted(cuts),
             "light_bone": first}
    return Result(out, report, trace)


# ---- the song -------------------------------------------------------------------------------

def loudness(path, n, fps=FPS, rate=8000, window=0.2, low=10.0, high=90.0, smooth=0.5):
    """the song's loudness per frame from 0 (its `low` percentile) to 1 (its `high` percentile): RMS over `window`
    seconds about each frame's time in dB, then a moving mean over `smooth` seconds; read with ffmpeg"""
    import numpy as np
    args = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=flags, stdin=subprocess.DEVNULL).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    if len(x) < rate:
        raise ValueError("the sound %s is too short" % path)
    width = int(window * rate / 2)
    csum = np.concatenate([[0.0], np.cumsum(x * x)])
    db = np.zeros(n)
    for i in range(n):
        centre = int(round((i + SHOWN) / fps * rate))
        a, b = max(0, centre - width), min(len(x), centre + width)
        power = (csum[b] - csum[a]) / max(1, b - a) if b > a else 0.0
        db[i] = 10.0 * math.log10(max(power, 1e-12))
    lo, hi = np.percentile(db, low), np.percentile(db, high)
    a = np.clip((db - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    k = max(1, int(round(smooth * fps)))
    kernel = np.ones(k) / k
    a = np.convolve(np.concatenate([[a[0]] * (k // 2), a, [a[-1]] * (k - 1 - k // 2)]), kernel, mode="valid")
    return [float(v) for v in a[:n]], {"low_db": _r(lo, 2), "high_db": _r(hi, 2)}


# ---- the command ----------------------------------------------------------------------------

def _write(path, data):
    folder = os.path.dirname(os.path.abspath(path))
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
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: the inputs and the files written must all differ" % (seen[key], path))
        seen[key] = path


def run(model_path, dance_path, gaze_path, camera_path, out_path, face_path=None, look_path=None, flares=(),
        audio_path=None, chorus=(), params_path=None, report_path=None, seed=0, trace_path=None):
    started = time.time()
    check_distinct(model_path, dance_path, gaze_path, camera_path, out_path, face_path, look_path, audio_path, params_path,
                   report_path, trace_path)
    if params_path:
        with open(params_path, encoding="utf-8") as f:
            params = merge_params(PARAMS, json.load(f))
    else:
        params = merge_params(PARAMS, {})
    all_flares = sorted(set(float(t) for t in flares))
    if look_path:
        with open(look_path, encoding="utf-8") as f:
            look = json.load(f)
        all_flares = sorted(set(float(t) for t in look.get("flares", [])) | set(all_flares))
    with open(model_path, "rb") as f:
        model_bytes = f.read()
    dance = vmd.load(dance_path)
    gaze = vmd.load(gaze_path)
    camera = vmd.load(camera_path)
    model = pmx.loads(model_bytes)
    eye_names = {"右目", "左目"} | {b.name for b in model.bones if (b.name_en or "").startswith(pmx_eyes.EN_PREFIX)}
    motions = {"dance": dance, "gaze": gaze}
    if face_path:
        motions["face"] = vmd.load(face_path)
    else:
        doc = pmx_edit.loads(model_bytes)
        closing = pmx_eyes.closing_morphs(doc, pmx_eyes.plan(doc)[0], pmx_eyes.REVEAL)
        if closing:
            raise ValueError("--face is needed: the model's closing morphs (%s) move its lights with the lids, and the "
                             "lights are kept on the iris and off the lids as the face VMD loaded with them moves them"
                             % ", ".join(sorted(closing)))
    check_overlaps(motions, eye_names, {BIG, THIN, HIDE})
    arousal, loud = None, None
    if audio_path:
        n = max(fk.last_frame(dance), fk.last_frame(gaze)) + 1
        ap = params["pupil"]["arousal"]
        arousal, loud = loudness(audio_path, n, low=ap["low"], high=ap["high"])
    result = optics(model_bytes, dance, gaze, camera, params, all_flares, arousal, [float(c) for c in chorus], seed,
                    motions.get("face"))
    _write(out_path, vmd.dumps(result.motion))
    back = vmd.load(out_path)
    report = dict(result.report)
    report["in"] = {"model": os.path.abspath(model_path), "dance": os.path.abspath(dance_path),
                    "gaze": os.path.abspath(gaze_path), "camera": os.path.abspath(camera_path),
                    "face": os.path.abspath(face_path) if face_path else None,
                    "look": os.path.abspath(look_path) if look_path else None,
                    "audio": os.path.abspath(audio_path) if audio_path else None}
    report["out"] = os.path.abspath(out_path)
    report["written"] = {"bones": len(back.bones), "morphs": len(back.morphs)}
    if loud:
        report["pupil"]["loudness"] = loud
    report["seconds"] = _r(time.time() - started, 2)
    if report_path:
        _write(report_path, (json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    if trace_path:
        _write(trace_path, (json.dumps(result.trace, ensure_ascii=False) + "\n").encode("utf-8"))
        report["trace"] = os.path.abspath(trace_path)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model", help="the model made by tools/pmx_eyes.py (.pmx)")
    ap.add_argument("dance", help="the dance (.vmd)")
    ap.add_argument("gaze", help="the 両目 track of tools/eye_gaze.py (.vmd), loaded after the dance")
    ap.add_argument("camera", help="the camera motion (.vmd)")
    ap.add_argument("out", help="the eye optics motion to write (.vmd), to load after the dance, the face and the gaze")
    ap.add_argument("--face", help="the face motion loaded with this one (needed when the model's closing morphs move "
                                   "its lights): its morphs that move the lights and the lids (まばたき, 笑い, ...) are "
                                   "followed; refused when it keys the pupil or light morphs or bones")
    ap.add_argument("--look", help="the MV's look JSON: its \"flares\" (seconds) narrow the pupils")
    ap.add_argument("--flares", type=float, nargs="+", default=[], help="more flare times in seconds")
    ap.add_argument("--audio", help="the song (read with ffmpeg): its loudness widens the pupils")
    ap.add_argument("--chorus", type=float, nargs="+", default=[], help="the heads of the choruses in seconds")
    ap.add_argument("--params", help="a JSON of PARAMS' shape with the values to change")
    ap.add_argument("--report", help="write the measures to this JSON")
    ap.add_argument("--seed", type=int, default=0, help="the pupil's unrest (default 0)")
    ap.add_argument("--trace", help="write the values of every frame (target, vergence, light offset, HL消, pupil, the "
                                    "eyes' centre and the camera) to this JSON")
    a = ap.parse_args(argv)
    try:
        report = run(a.model, a.dance, a.gaze, a.camera, a.out, a.face, a.look, a.flares, a.audio, a.chorus, a.params,
                     a.report, a.seed, a.trace)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    short = {"ok": True, "out": report["out"], "frames": report["frames"], "keys": report["keys"],
             "vergence": {k: report["vergence"][k] for k in ("labels", "degrees", "step")},
             "light": {k: report["light"][k] for k in ("moved", "offset_step_without_cuts", "key_step_without_cuts", "cuts")},
             "fade": {k: report["fade"][k] for k in ("frames_on", "frames_full", "step_without_cuts")},
             "pupil": {k: report["pupil"][k] for k in ("relative", "mm", "steps")}, "seconds": report["seconds"]}
    if a.report:
        short["report"] = os.path.abspath(a.report)
    print(json.dumps(short, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
