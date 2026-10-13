"""Give a dancer eyes that look on their own: fixations on where her face is going, saccades that lead the head's
fast turns, eye contact with the camera planned where the camera stays within reach, and looks at her own hand where
it comes to rest before her face, written as a 両目 track to load after the dance.

    python tools/eye_gaze.py DANCE.vmd CAMERA.vmd MODEL.pmx OUT.vmd [--report r.json] [--debug d.json]
                             [--debug-frames F ...] [--probe P.vmd] [--max-yaw 18] [--max-up 6] [--max-down 10]
                             [--max-pitch P (sets up and down to P)] [--seed 0] [--cues CUES.json] [--chorus S ...]
                             [--min-fixation 10]

Why: the dance of the MV keys 両目, 右目 and 左目 once each, on frame 0: her eyes never move.  On Sour's Rin 両目
turns both eyes (右目 and 左目 take its rotation by append, ratio 1), so one track does it.  The first version of this
tool (until 2026-10) made the eyes follow the camera and nothing else: the analysis of the MV v2 (uncanny/a07, a13,
a20) found them at the edge of their range 59 % of the time (up to 4 s on end), 15 degrees or more off the middle
42 %, carried by the head in 93 % of the large gaze changes, ahead of the head in 4 % of its fast turns, and in eye
contacts of 0.30 s (median) that came and went 51 times a minute with no relation to the song.  This version plans
the gaze as a person's: the eyes move first, look where the face goes, and look at the viewer at chosen moments.
Its first form (stage 1) held every fixation still in the world, so the head's dance threw the eyes to the edge of
their range and back 3 times a second, in jumps of one frame (2.98 saccades a second, 487 of them one frame long,
fixations of 0.20 s).  Stage 5 (2026-10-13) smooths them: no one-frame jumps, longer fixations, no saccade for a nod
that comes back, a sustained fast turn carries the gaze, at most MAX_STEP a frame outside saccades; between saccades
the gaze still stays put in the world.  (The first form of stage 5 also slid the eyes toward the face's way and
countered only half of each nod: review gaze-smooth found the gaze then flowed with the head like a doll's eye, on 70 %
of the steps of a still head.  The slide is gone and the nods are countered in full.)  Stage 6 (2026-10-13: "when she
looks at something near, the eyes come together": at 52 s her fingers are before her face and the eyes stay
parallel) gives the eyes her hands as targets, so that tools/eye_optics.py, which brings them together on a near hand
the gaze meets, does so where she looks at one; it moves the eyes on from the wall, where countering every nod in
full had left them (frames at the wall up or down 3.3 % -> 12.8 % in stage 5, the iris low in the eye); and, after
the remeasure of the MV v7 (the head carried the gaze in 57 % of a07's large gaze changes, 1 to 2 % before stage 5;
with the head at 60 to 120 deg/s the gaze stayed put in the world on 54 % of the steps, 89 % before), it keeps the
reflex on in the fast turns too and makes quick phases where the head runs the eyes into their wall.

Where the camera is, seen from her eyes (sights; mmd_cli/fk.py does the forward kinematics):

* The eye center is the midpoint of 右目 and 左目 in the world.  両目 itself is a handle above the head on Sour's
  Rin (height 19.37 against eyes at 17.21: aiming from it would tilt the gaze by 3.5 degrees at 35 units); its
  position is used only when the model lacks 右目 or 左目.
* The head frame is the world rotation of 両目's parent (頭).  The camera is fk.camera_position of the camera motion.
* A direction v in the head frame is read as yaw (positive toward the model's left, +X) and pitch (positive up),
  each relative to the eyes' rest gaze: the direction from 両目 to 両目先 (or to its tail) when it lies within
  FORWARD_TOLERANCE of -Z (on Sour's Rin it is exactly -Z), else -Z.
* A camera cut is a frame on which the camera moves more than CUT_JUMP units or turns its line of sight more than
  CUT_TURN degrees from the frame before.

How the eyes move (plan: the whole song is known, so the plan looks ahead):

* The limits are --max-yaw to either side, --max-up and --max-down (6 up and 10 down by default: at +10 degrees the
  upper lid of Sour's Rin covers 17 % more of the iris, review 8).  Every angle written is clamped to the limits.
  Three zones inside them: the free zone (FREE_SHARE of each limit: 12, 4 and 7 degrees by default), where the eyes
  rest between saccades; beyond it a fixation is pressed softly (tanh) against the wall (WALL of each limit: 15.3,
  5.1 and 8.5), short of the 90 % lines the analysis counts as the edge; and the contact zone (CONTACT_SHARE: 16,
  5.3 and 8.9) for eye contact.  Saccade goals, contacts and leads go through soften() (the last part of each range
  approached along tanh).
* Fixations (state free), stage 5 (2026-10-13: "make the movement of the light and the iris smooth").  The eyes look
  at a point in the world (a direction: far away) and each frame:
  1. turn against the head (the vestibulo-ocular reflex) by VOR_GAIN of what holding the point would take: all of it,
     sideways and up and down, so the gaze stays put in the world (a person's gain is about 1 at 0.5 to 5 Hz both
     ways, and the eyes cannot glide between still targets; review gaze-smooth 1.10), in the fast turns too (stage 6:
     the reflex is off only while the eyes jump, and a lead keeps its angle in the head until its turn's onset; stage
     5 held it off through a sustained fast turn, a person's gaze shift where the head carries the gaze on to its
     target, and the head carried most large gaze changes of the MV v7); where the eyes reach their wall, the rest of
     the head's turn carries the gaze until a quick phase (below);
  2. are pressed against the wall beyond the free zone, and turn at most MAX_STEP a frame (the rest is carried);
  3. look at that point from then on.
  The eyes move on with a saccade (recentre) only when they would stay more than GAP degrees from the face's way (the
  face target: the head's forward averaged over the frame and the next FACE_AHEAD, seen in the head, plus the offset
  of the last glance, inside the free zone and AVOID degrees off the camera) from LOOK_AHEAD frames on for SUSTAIN
  more frames (the head has moved on, not nodded with the beat).  Not before the shortest fixation:
  MIN_FIXATION (--min-fixation; 10 frames by default, the first version had 6 and 57 % of its fixations stopped
  there) plus 0 to FIXATION_SPREAD frames drawn for each fixation (with one fixed length the fixations that wanted
  to end earlier all ended on it).  After GLANCE frames (drawn from the seed) of one fixation,
  a glance: a saccade to a point a few degrees off the face's way.  The analysis measured why the gaze must follow
  the face: the head turns its forward by 10 degrees in 0.2 s (median), so a point held on its own leaves the eyes'
  range in 5 frames.
* Quick phases (stage 6).  With the reflex on, a head that goes on turning runs the eyes into their wall within a
  few frames: their range is narrow (18, 6 and 10 degrees; a person's is 45 to 55 sideways, about 28 to 43 up and 47
  down, and a person who looks at a point while moving the head makes no quick phase, Barnes 1979).  An animal with a
  narrow range (a cat, 25 degrees each way) shifts its gaze with a series of rapid eye movements, closer together the
  faster the head (Guitton, Douglas & Volle 1984); quick phases drive the eyes the way the head turns and start from
  where the eye is in the orbit (Chun & Robinson 1978, Lau & Honrubia 1987).  So, from QUICK_AFTER plus 0 to
  QUICK_SPREAD frames after a landing (drawn for each fixation from a stream of the seed of its own: 5 to 8 frames,
  0.17 to 0.27 s; one slow phase of a person's optokinetic nystagmus lasts 0.26 s, Jell 1984, and what triggers a
  quick phase varies from one to the next, Waddington & Harris 2012; with one fixed wait of 7 frames 56 % of them
  came on it), a fixation ends:
  - inside a sustained fast turn (a fast turn, below, that goes GATE_TURN degrees or more its way: from its onset to
    where it goes furthest or its fast run ends, whichever is later), when the reflex has carried the eyes back beyond
    the free zone sideways or the head keeps them pressed (next), with a quick phase (reason quick) the way of the
    turn, toward where the face will be QUICK_AHEAD frames on or where the turn ends if sooner (as a lead's goal: at
    most LEAD_SHARE of the yaw limit off the middle, at least LEAD_STEP beyond where the eyes are);
  - elsewhere, when the eyes would stay pressed beyond the free zone with the face's way WALL_GAP degrees or more back
    toward the middle on that axis, on that frame and the QUICK_SUSTAIN - 1 after it, with a saccade off the wall
    (reason wall) to the face target.  A press the head lets go of sooner (a nod with the beat) moves nothing.  Up and
    down GAP is as large as the range to the wall (5.1 and 8.5 degrees), so a recentre hardly ever moved the eyes on
    there (they stayed low for 0.4 s on 2955 to 2967 of the MV v7).
* Leads (a20, Lasseter: "the eyes move first, a few frames before the head").  A fast turn is a run of the head
  forward's yaw rate (in the world) above TURN_SPEED for 2 frames or more; its onset is the first of the 15 frames
  before at 30 % of the peak.  The eyes jump the way of the turn and land LEAD frames before the onset (2 to 4, from
  the seed; the saccade starts as many frames earlier as it is long): toward where the face will be when the turn has
  gone furthest (within 20 frames), at most LEAD_SHARE of the yaw limit off the middle and at least LEAD_STEP degrees
  beyond where they are (capped by that; eyes already further the way of the turn keep their angle: a lead never
  jumps back against its turn, which with the quick phase after it made a reversal, review gaze-v8).  Until the
  onset they keep that angle in the head (state lead: a person's
  gaze shift holds the reflex off); from the onset they are a fixation again, so the head turns toward where the eyes
  already are.  For QUIET frames before a lead no other saccade starts, and for GUARD frames after the onset no
  recentre.  A turn whose lead would start before the onset of the lead before (one turn seen as two, with a dip
  between) gets no lead of its own: two leads 2 frames apart were most of the jumps that followed another.  Nor does
  a turn that goes less than GATE_TURN degrees its way (a shake that comes back: held in the head before it, the
  eyes would ride the head's first swing).
* Eye contact (state contact) is planned first, on the whole song.  The camera is within reach on a frame when the
  eyes, held inside the contact zone, would be within CONTACT_ERROR of it (and it is not behind her); gaps of
  CONTACT_GAP frames or less are closed (the analysis joins them too).  No contact from END_CLEAR frames before a
  cut to CUT_CLEAR after it: she cannot see the edit, and searching for the camera at every cut was one of the
  analysis' findings.  Every run of CONTACT_MIN frames or more becomes a contact, cut to CONTACT_MAX with an anchor
  of the song two thirds in when it is longer; runs of CONTACT_MID frames or more become contacts only near an anchor
  (ANCHOR_NEAR frames), the longest first and CONTACT_SPARE fewer than the long ones, so that the median contact is
  a long one.  The anchors are the ends of the lyric lines and the starts of the hooks of --cues and the heads of
  the choruses (--chorus, seconds).  A small shift of a cue (textlight moves four lines by 0.3 to 0.9 s) moves a
  contact by as much at most: a contact is found by the camera's reach and only placed by its anchor.  A contact
  starts with a saccade that lands by its first frame and ends with a look away (a saccade to a point off the face's
  way).  Its eyes follow the camera inside the contact zone (contact_angles), at most MAX_STEP a frame.  With a
  contact due within QUIET + 4 frames no other saccade starts (it would be followed by the one onto the camera 2 or 3
  frames after landing): a lead due then is the saccade onto the camera, and once on it the eyes wait there for the
  contact.
* Looks at a hand (state hand, stage 6), planned after the contacts and the leads (hand_runs).  A hand's look point
  is the mean of its HAND_POINTS (the wrist and the middle finger's tip: the middle of the hand, open or closed).  It
  is looked at over a run of frames on which it is HAND_NEAR to HAND_FAR metres from the eyes, before her face (in
  the HAND_ZONE of the limits seen in the head, the free zone, or HAND_REACH degrees beyond it: the face is turned to
  it), HAND_CAMERA degrees or more off the camera (nearer the camera's line she holds it out to the viewer), with its
  palm turned HAND_PALM degrees or more away from the camera (hand_palms; a palm shown to the viewer is a gesture to
  the viewer: at 120.6 and 178.4 s of the MV v8 the eyes dropped to the backs of her hands) and moving under
  HAND_FAST deg/s seen from the eyes, HAND_MIN frames or more (0.3 s: a person's look at a gesture lasts 0.46 s on
  average, Gullberg & Holmqvist 2006; 5 of the 9 looks of the MV v8 were 6 to 8 frames and left the eyes on the hand
  for 2 to 4 between two large jumps), with the hand under HAND_SLOW deg/s on one frame at least (it comes to rest,
  or nearly: a person looks at a gesture held still; speakers look at 4 % of their gestures, about 1 s each,
  Gullberg & Holmqvist 1999, Gullberg & Kita 2009).  Nearer than HAND_NEAR the hand covers or touches the face, the
  dance's most frequent hand before her face.  The contacts and the leads win.  The eyes aim at the tip, of
  FINGER_TIPS, furthest from the wrist (hand_aims: a raised finger's tip; at 52 s of the MV v8 the look point put the
  gaze on the cuff, 24 degrees below the raised index finger, the eyes 6 to 9 degrees down, review gaze-v8; the tip
  is above their reach there, and they go up as far as they reach).  A saccade (reason hand) lands by the run's first
  frame where the aim will be when the hand settles (its first frame under HAND_SLOW): the eyes
  are there before the hand, as a person's lead the hand she moves (Johansson 2001; Chen 2016: the eyes start about
  20 ms before a self-moved finger).  Then they follow it HAND_AHEAD frames ahead at most PURSUIT_SPEED deg/s in the
  world (smooth pursuit of a self-moved target: gain about 0.9, twice the eyes' own top speed, Chen 2016, Gauthier
  1988), with a saccade that catches up when they trail by more than CATCH_UP degrees, not within CATCH_UP_AFTER
  frames of a landing.  When the run ends a saccade (hand_away) takes them to the face's way, or the contact or lead
  that comes then.  Within QUIET + 4 frames of a look no recentre, glance or away starts.
* Outside the contacts the gaze keeps KEEP_OFF degrees off the camera on every frame, saccades on their way too: a
  pass over the camera would count as a one-frame eye contact.  When the camera passes over the gaze the kept point
  would flip to its other side in one frame (10 degrees with no easing); when it would move FLIP_STEP degrees more
  than the gaze itself, or more than MAX_STEP, the eyes move away with a saccade instead (reason away; the coming
  lead if one is due), as they do when the point nears the camera after the shortest fixation.
* A saccade takes saccade_frames(A) frames: 2 under SHORT_SACCADE (15) degrees, 3 up to LONG_SACCADE (35), 4
  beyond (the coordinator, 2026-10-13: no one-frame jumps, and no slower: the main sequence D = 21 + 2.2 A ms puts 5
  to 15 degrees in 1 to 2 frames, and slower eyes look sluggish, Pejsa 2013), along a minimum-jerk profile from where
  the eyes were to where the target is on each frame of it: the camera, a lead's angle in the head, the hand, or
  the face target (with the offset of a glance or a look away) on that frame.  A goal held still in the world would swing
  across the eyes' range while the head turns 20 degrees a frame and end the saccade with a jump.  The fixation
  starts where the saccade lands.  A move under MIN_SACCADE is no saccade: the fixation alone moves.
* Life: a slow drift (a random walk of up to DRIFT_STEP per frame and axis, kept within DRIFT_LIMIT) and a
  microsaccade every MICRO_INTERVAL frames that jumps back to within MICRO_SIZE of the center are added on top; well
  under a degree (outside saccades the angles written still turn at most MAX_STEP a frame).  Everything random comes
  from the seed (random.Random), so the same seed gives the same file.

What is written: a VMD that holds only the 両目 track, a key on every frame where the angles change (and the first
and last frame) with the linear curve, under the dance's model name.  Load it after the dance: it replaces the
dance's single 両目 key.  The rotation is made with mmd_cli.fk.stored, so it follows the one convention of
mmd_cli/fk.py (KEY_ROTATION_SIGNS).  Keys the dance has on 右目 or 左目 would add to it (the report lists them).

The report (--report, and in short on stdout): the shares of frames in each state (contact, free, lead, in_saccade,
hand; they add up to 1), the saccades (their reasons: contact, look_away, lead, recentre, glance, away, hand,
hand_away, quick, wall; the list has frame, frames, reason and amplitude like the first version's, so the analysis' scripts read
it), the contacts (first and last frame, seconds, the anchor they hold), the looks at a hand (hands: first and last
frame, seconds, the hand, its median distance in metres, the frame it settles; hand_rules: the constants above), the
anchors, the cuts, the error on the camera during the contacts,
and measures: the target numbers of the analysis computed on the plan, by the analysts' definitions (eye_measures,
contact_measures, lead_measure, carried_measure; README: eye_gaze.py), the smoothness of stage 5 (smooth_measures),
whether the gaze stays put in the world between saccades (world_measures) and the frames at the wall
(wall_measures).  --debug writes, for --debug-frames (default: every DEBUG_STEP-th frame), the geometry of those
frames.

--probe P.vmd also writes a short 両目 motion to check the convention on a render: frames 0-29 rest, 30-59 window Y
+15, 60-89 Y -15, 90-119 X +10, 120-149 X -10, rest again on 150.  The summary says which way each should look if
the convention of mmd_cli/fk.py is right.
"""
import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import List, NamedTuple, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmd_cli import fk, mathutil  # noqa: E402
from mmd_cli.formats import pmd, pmx, vmd  # noqa: E402

EYES = "両目"
EYE_TIP = "両目先"
EYE_PAIR = ("右目", "左目")
FPS = 30.0
MAX_YAW = 18.0                        # degrees the eyes turn sideways (default of --max-yaw)
MAX_UP, MAX_DOWN = 6.0, 10.0          # degrees they turn up and down (--max-up, --max-down; review 8, R1: at +10 the
                                      # upper lid of Sour's Rin covers 17 % more of the iris)
LIMIT_MAX = 45.0                      # degrees: the most a limit may be
SOFT_FROM = 0.6                       # share of a limit up to which the eyes follow exactly; beyond, tanh towards it
EDGE = 0.9                            # share of a limit from which the analysis counts the eyes as at the edge
FREE_SHARE = (2.0 / 3.0, 2.0 / 3.0, 0.7)      # the free zone, shares of the yaw, up and down limits (12, 4, 7)
CONTACT_SHARE = (0.889, 0.883, 0.89)          # the contact zone (16, 5.3, 8.9: inside the EDGE lines)
CONTACT_ERROR = 4.0                   # degrees off the camera at most for a frame to be within reach (a13 counts 4;
                                      # 3.5 gave 8 contacts and none at the first chorus, 4.0 gives 13: review eye)
CONTACT_GAP = 2                       # frames out of reach that do not break a run (a13 joins gaps of 2)
CONTACT_MIN = 48                      # frames: a run this long is always a contact (1.6 s)
CONTACT_MID = 30                      # frames: a run this long is a contact near an anchor of the song
CONTACT_SPARE = 2                     # the shorter contacts are this many fewer than the long ones
CONTACT_MAX = 150                     # frames: a contact lasts at most this (5 s)
ANCHOR_NEAR = 30                      # frames from a run within which an anchor counts (1 s)
END_CLEAR, CUT_CLEAR = 2, 6           # frames before and after a cut without a contact
LOOK_AHEAD = 2                        # frames ahead from which a fixation is checked against the face's way
GAP = 8.0                             # degrees off the face's way the eyes may stay before a recentre
SUSTAIN = 6                           # frames past LOOK_AHEAD the gap must last (a nod with the beat comes back)
MIN_FIXATION = 10                     # frames from the landing of a saccade to the earliest recentre or glance (333 ms)
FIXATION_SPREAD = 5                   # frames: each fixation's earliest is MIN_FIXATION plus 0 to this (the seed)
GLANCE = (45, 120)                    # frames of one fixation before a glance (both included)
VOR_GAIN = (1.0, 1.0)                 # share of the counter-rotation the eyes make sideways and up and down
GATE_TURN = 20.0                      # degrees a fast turn goes its way for a lead before it and quick phases in it
QUICK_AFTER = 5                       # frames after a landing before a quick phase or a saccade off the wall, plus
QUICK_SPREAD = 3                      # 0 to this drawn for each fixation (its own stream of the seed)
QUICK_SUSTAIN = 6                     # frames a press against the wall must last, from the frame on, for one
QUICK_AHEAD = 3                       # frames: a quick phase goes toward where the head will be this many frames on
                                      # (at 150 to 600 deg/s, 15 to 60 degrees ahead: never behind her in a spin)
FACE_AHEAD = 12                       # the face's way: the head's forward averaged over the frame and the next 12
WALL = 0.85                           # share of each limit a fixation is pressed softly against beyond the free zone
WALL_SEEN = 0.84                      # share of each limit from which the measures count the eyes as at the wall
MAX_STEP = 8.0                        # degrees the eyes turn in the head a frame at most outside saccades
FLIP_STEP = 4.0                       # degrees the kept-off gaze may move beyond the gaze's own move before it is a
                                      # saccade (the keep-off flipping to the other side of the camera)
SHORT_SACCADE, LONG_SACCADE = 15.0, 35.0  # degrees: saccades of 2 frames below the first, 3 up to the second, then 4
GLANCE_OFF = ((-4.0, 4.0), (-3.0, 1.5))   # degrees off the face's way of a glance or a look away: yaw, pitch
AVOID = 6.0                           # degrees off the camera the face target keeps
KEEP_OFF = 5.0                        # degrees off the camera the gaze keeps outside the contacts
TURN_SPEED = 150.0                    # deg/s of the head's yaw that make a fast turn
LEAD = (2, 4)                         # frames before a fast turn's onset on which the eyes land (both included)
LEAD_SHARE = 13.0 / 18.0              # a lead lands at most this share of the yaw limit off the middle
LEAD_STEP = 6.0                       # degrees beyond where the eyes are that a lead goes at least
QUIET = 8                             # frames before a lead in which no other saccade starts
GUARD = 3                             # frames after a fast turn's onset without a recentre
MIN_SACCADE = 0.5                     # degrees: a smaller move is no saccade, only the fixation moves
CUT_JUMP = 1.0                        # model units the camera moves in one frame on a cut
CUT_TURN = 5.0                        # degrees the camera's line of sight turns in one frame on a cut
DRIFT_STEP = 0.03                     # degrees per frame and axis, at most, of the fixation drift
DRIFT_LIMIT = 0.3                     # degrees: the drift stays within this on each axis
MICRO_INTERVAL = (15, 45)             # frames between microsaccades
MICRO_SIZE = 0.15                     # degrees: a microsaccade lands within this of the center
FORWARD_TOLERANCE = 20.0              # degrees off -Z within which 両目 -> 両目先 is taken as the rest gaze
WALL_GAP = 3.0                        # degrees the face's way lies back toward the middle of a fixation pressed beyond
                                      # the free zone, on that axis, for a quick phase or a saccade off the wall
# looks at her hands (stage 6)
HANDS = ("右", "左")
HAND_POINTS = ("手首", "中指３先")      # their mean is the hand's look point: its middle, open or closed (the runs)
FINGER_TIPS = ("人指３先", "中指３先", "薬指３先", "小指３先", "親指２先")   # the eyes aim at the one furthest from the wrist
UNIT_M = 0.08                         # metres in a unit of the model (Sour's Rin; tools/eye_optics.py unit_mm 80)
HAND_NEAR, HAND_FAR = 0.18, 0.60      # metres from the eyes: nearer, the hand covers or touches the face; further, beyond
                                      # an arm's reach (tools/eye_optics.py: hand_m 0.6)
HAND_ZONE = FREE_SHARE                # shares of the limits within which, or HAND_REACH degrees beyond, a hand lies
HAND_REACH = 4.0                      # before her face: the face turned to it, the eyes resting near the middle
HAND_CAMERA = 10.0                    # degrees: a hand nearer the camera's line is held out to the viewer, not looked at
HAND_FAST = 300.0                     # deg/s: a hand moving faster, seen from the eyes in the world, is not followed
HAND_SLOW = 100.0                     # deg/s: a look at a hand needs it this slow on one frame of it at least
HAND_MIN = 9                          # frames a look at a hand lasts at least (0.3 s: a person's look at a gesture
                                      # lasts 0.46 s on average, Gullberg & Holmqvist 2006; shorter, the eyes only pass)
HAND_PALM = 45.0                      # degrees: a palm turned this near the camera is shown to the viewer, not looked at
HAND_JOIN = 2                         # frames between two runs of the hand that make one
HAND_AHEAD = 1                        # frames: the eyes follow the hand where it will be (a self-moved target is led)
PURSUIT_SPEED = 100.0                 # deg/s: the gaze follows a hand at most this fast in the world
CATCH_UP = 3.0                        # degrees the eyes may trail the hand before a saccade catches up
CATCH_UP_AFTER = 4                    # frames after a landing before a saccade catches up with the hand
DEBUG_STEP = 30
STATES = ("contact", "free", "lead", "in_saccade", "hand")
REASONS = ("contact", "look_away", "lead", "recentre", "glance", "away", "hand", "hand_away", "quick", "wall")
REVERSAL = 3.0                        # degrees: a saccade above this followed, within REVERSAL_WITHIN frames of its
REVERSAL_WITHIN = 10                  # landing, by one above this the opposite way is a reversal (restless eyes)
# the world gaze (review gaze-smooth 1.3 to 1.6), on the steps outside saccades: with the head at STEADY_HEAD deg/s
# (what it would carry a resting eye) the gaze is steady under STEADY_GAZE deg/s; with the head under STILL_HEAD deg/s
# (and outside the contacts) it flows when it moves more than STILL_FLOW degrees a frame
STEADY_HEAD, STEADY_GAZE = (15.0, 120.0), 10.0
STEADY_BANDS = ((15.0, 60.0), (60.0, 120.0))   # the head's deg/s by which the remeasure of stage 6 splits W2
STILL_HEAD, STILL_FLOW = 20.0, 0.1
# the analysis' measures: a07 (edge, large gaze changes), a13 (eccentricity, eye contact), a20 (leads)
CONTACT_SEEN = 4.0                    # degrees: the analysis counts the gaze within this of the camera as eye contact
CONTACT_JOIN = 2                      # frames: gaps it joins
LARGE_WINDOW, LARGE_CHANGE = 15, 20.0     # a large gaze change: more than 20 degrees in the world within 15 frames
LEAD_TURN, LEAD_MIN_FRAMES, LEAD_SEEN = 200.0, 3, 3.0    # a20: yaw rate, frames, degrees of the eyes ahead
LEAD_MARGINS = (330, 172)             # a20 left out turns in the first 330 and the last 172 frames of the song
# (first frame, last frame, window angles of 両目): the probe
PROBE = ((0, 29, (0.0, 0.0, 0.0)), (30, 59, (0.0, 15.0, 0.0)), (60, 89, (0.0, -15.0, 0.0)),
         (90, 119, (10.0, 0.0, 0.0)), (120, 149, (-10.0, 0.0, 0.0)), (150, 150, (0.0, 0.0, 0.0)))


def _r(value, places=4):
    return round(float(value), places) + 0.0


def _vec(values, places=4):
    return [_r(v, places) for v in values]


# ---- directions -----------------------------------------------------------------------------

def angles_of(v):
    """(yaw, pitch) in degrees of a direction: yaw toward +X (the model's left), pitch up, (0, 0) along -Z"""
    x, y, z = v
    return math.degrees(math.atan2(x, -z)), math.degrees(math.atan2(y, math.hypot(x, z)))


def direction_of(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return (math.cos(p) * math.sin(y), math.sin(p), -math.cos(p) * math.cos(y))


def degrees_between(a, b):
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


def _apart(a, b):
    """degrees between two (yaw, pitch) directions"""
    return degrees_between(direction_of(*a), direction_of(*b))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _about(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def eye_rotation(yaw, pitch):
    """the rotation, as applied in the head's frame, that turns the rest gaze by `yaw` (to the model's left, +X) and
    `pitch` (up): pitch about X first, then yaw about the head's vertical (exact for a rest gaze along -Z)"""
    return fk.multiply(_about((0.0, 1.0, 0.0), -yaw), _about((1.0, 0.0, 0.0), pitch))


# ---- where the camera is, seen from her eyes ------------------------------------------------

@dataclass
class Sight:
    frame: int
    eye: Tuple[float, float, float]             # the eye center in the world
    head: Tuple[float, float, float, float]     # the world rotation of the eyes' parent (as applied)
    camera: Tuple[float, float, float]          # the camera in the world
    cut: bool                                   # the camera cut on this frame


def _by_name(model):
    out = {}
    for bone in model.bones:
        out.setdefault(bone.name, bone)
    return out


def eye_bones(model):
    """(the 両目 bone, the names whose positions make the eye center, the name of 両目's parent or None)"""
    by = _by_name(model)
    eyes = by.get(EYES)
    if eyes is None:
        raise ValueError("the model has no %s bone: there is nothing to turn the eyes with" % EYES)
    center = [name for name in EYE_PAIR if name in by]
    if len(center) != len(EYE_PAIR):
        center = [EYES]
    parent = model.bones[eyes.parent].name if eyes.parent is not None else None
    return eyes, center, parent


def rest_forward(model, eyes):
    """(the rest gaze as a unit vector, where it came from): 両目 -> 両目先 (or 両目's tail) when it lies within
    FORWARD_TOLERANCE of -Z, else -Z"""
    candidates = []
    tip = _by_name(model).get(EYE_TIP)
    if tip is not None and tip.position is not None and eyes.position is not None:
        candidates.append((tuple(t - e for t, e in zip(tip.position, eyes.position)), EYE_TIP))
    tail = eyes.tail or {}
    if tail.get("bone") is not None and model.bones[tail["bone"]].position is not None and eyes.position is not None:
        candidates.append((tuple(t - e for t, e in zip(model.bones[tail["bone"]].position, eyes.position)), "tail"))
    elif tail.get("offset") is not None:
        candidates.append((tuple(tail["offset"]), "tail"))
    for v, label in candidates:
        n = math.sqrt(sum(c * c for c in v))
        if n > 1e-6:
            unit = tuple(c / n + 0.0 for c in v)
            if degrees_between(unit, (0.0, 0.0, -1.0)) <= FORWARD_TOLERANCE:
                return unit, label
    return (0.0, 0.0, -1.0), "-Z"


def sights(model, dance, camera, first=0, last=None):
    """per frame from `first` to `last` (the dance's last bone key), where the eyes are, how the head is turned, where
    the camera is and whether it cut"""
    _, center, parent = eye_bones(model)
    names = list(center) + ([parent] if parent is not None and parent not in center else [])
    if last is None:
        last = fk.last_frame(dance)
    track = fk.world_track(model, dance, names, first, last)
    keys = fk.camera_keys(camera)
    frames = [k.frame for k in keys]
    out, previous = [], None
    for i, frame in enumerate(range(first, last + 1)):
        points = [track[name][i][0] for name in center]
        eye = tuple(sum(p[c] for p in points) / len(points) for c in range(3))
        head = track[parent][i][1] if parent is not None else fk.IDENTITY
        state = fk.camera_at(keys, frame, frames)
        position = fk.camera_position(state)
        sight_line = fk.camera_direction(state)             # from the angles: a camera turning on the spot cuts too
        cut = previous is not None and (math.sqrt(sum((a - b) ** 2 for a, b in zip(position, previous[0]))) > CUT_JUMP
                                        or degrees_between(sight_line, previous[1]) > CUT_TURN)
        previous = (position, sight_line)
        out.append(Sight(frame, eye, head, position, cut))
    return out


def hand_points(model, dance, first=0, last=None):
    """side ("右", "左") -> the hand's look point in the world on each frame from `first` to `last`: the mean of the
    bones of HAND_POINTS the model has on that side (mmd_cli/fk.py); sides with none are left out"""
    by = _by_name(model)
    names = {side: [side + p for p in HAND_POINTS if side + p in by] for side in HANDS}
    names = {side: v for side, v in names.items() if v}
    if not names:
        return {}
    if last is None:
        last = fk.last_frame(dance)
    track = fk.world_track(model, dance, [b for v in names.values() for b in v], first, last)
    return {side: [tuple(sum(track[b][i][0][c] for b in v) / len(v) for c in range(3)) for i in range(last - first + 1)]
            for side, v in names.items()}


def hand_palms(model, dance, first=0, last=None):
    """side -> the normal out of the palm in the world on each frame (a unit vector: the wrist to the middle finger's
    tip crossed with the little finger's tip to the index finger's, mirrored on her right), for the sides with those
    four bones; None on a frame where they lie on a line"""
    by = _by_name(model)
    parts = ("手首", "中指３先", "人指３先", "小指３先")
    sides = [side for side in HANDS if all(side + p in by for p in parts)]
    if not sides:
        return {}
    if last is None:
        last = fk.last_frame(dance)
    track = fk.world_track(model, dance, [side + p for side in sides for p in parts], first, last)
    out = {}
    for side in sides:
        rows = []
        for i in range(last - first + 1):
            w, middle, index, little = (track[side + p][i][0] for p in parts)
            along = tuple(m - x for m, x in zip(middle, w))
            across = tuple(a - b for a, b in zip(index, little))
            n = _cross(across, along) if side == "左" else _cross(along, across)
            norm = math.sqrt(sum(c * c for c in n))
            rows.append(tuple(c / norm for c in n) if norm > 1e-9 else None)
        out[side] = rows
    return out


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def hand_aims(model, dance, first=0, last=None):
    """side -> where the eyes aim on the hand in the world on each frame from `first` to `last`: the tip, of
    FINGER_TIPS, furthest from the wrist on that frame (a raised finger's tip; an open hand's longest finger), for the
    sides with a wrist and a tip (review gaze-v8: the middle of the hand put the gaze on the cuff below the finger
    raised at 52 s of the MV)"""
    by = _by_name(model)
    names = {side: [side + t for t in FINGER_TIPS if side + t in by] for side in HANDS if side + HAND_POINTS[0] in by}
    names = {side: v for side, v in names.items() if v}
    if not names:
        return {}
    if last is None:
        last = fk.last_frame(dance)
    track = fk.world_track(model, dance, [s + HAND_POINTS[0] for s in names] + [b for v in names.values() for b in v],
                           first, last)
    out = {}
    for side, tips in names.items():
        rows = []
        for i in range(last - first + 1):
            w = track[side + HAND_POINTS[0]][i][0]
            tip = max(tips, key=lambda b: sum((p - q) ** 2 for p, q in zip(track[b][i][0], w)))
            rows.append(tuple(track[tip][i][0]))
        out[side] = rows
    return out


def _head_angles(sight, direction, rest):
    """((yaw, pitch) of a world direction in the head's frame, relative to the rest gaze; whether it is behind, more
    than 90 degrees off the rest gaze)"""
    v = fk.rotate(fk.conjugate(sight.head), direction)
    yaw, pitch = angles_of(v)
    yaw = (yaw - rest[0] + 180.0) % 360.0 - 180.0
    return (yaw, pitch - rest[1]), sum(a * b for a, b in zip(v, direction_of(*rest))) <= 0.0


def _seen(sight, point, forward, rest):
    """((yaw, pitch) of a world point seen from the eyes in the head's frame, relative to the rest gaze; whether it is
    behind, more than 90 degrees off the rest gaze)"""
    v = fk.rotate(fk.conjugate(sight.head), tuple(p - e for p, e in zip(point, sight.eye)))
    yaw, pitch = angles_of(v)
    yaw = (yaw - rest[0] + 180.0) % 360.0 - 180.0
    return (yaw, pitch - rest[1]), sum(a * b for a, b in zip(v, forward)) <= 0.0


def _world(sight, angles, rest):
    """the world direction seen at `angles` (from the rest gaze) in the head's frame of `sight`"""
    return fk.rotate(sight.head, direction_of(angles[0] + rest[0], angles[1] + rest[1]))


# ---- limits and zones -----------------------------------------------------------------------

@dataclass
class Look:
    frame: int
    yaw: float                      # the eye angles written, degrees from the rest gaze (+ to her left, + up)
    pitch: float
    state: str                      # one of STATES
    target: Tuple[float, float]     # where the camera is (yaw, pitch), not clamped
    error: float                    # degrees between the gaze written and the camera
    mode: str = "free"              # what the eyes hold after this frame: "camera" or "free"
    base: Tuple[float, float] = (0.0, 0.0)     # the eye angles before the drift is added


@dataclass(frozen=True)
class Limits:
    """how far the eyes turn from the rest gaze, in degrees: sideways (both ways), up, down (all positive)"""
    yaw: float = MAX_YAW
    up: float = MAX_UP
    down: float = MAX_DOWN

    def to_json(self):
        return {"yaw": self.yaw, "up": self.up, "down": self.down}


def check_limits(limits):
    for name, value in (("--max-yaw", limits.yaw), ("--max-up", limits.up), ("--max-down", limits.down)):
        if not 0.0 < value <= LIMIT_MAX:
            raise ValueError("%s is how far the eyes turn, above 0 and at most %g degrees, not %r" % (name, LIMIT_MAX, value))


def check_min_fixation(frames):
    if not (isinstance(frames, int) and frames >= 1):
        raise ValueError("--min-fixation is the shortest fixation in frames, 1 or more, not %r" % (frames,))


def _zone(limits, shares):
    return Limits(limits.yaw * shares[0], limits.up * shares[1], limits.down * shares[2])


def free_zone(limits):
    """where a fixation may hold the eyes (FREE_SHARE of the limits)"""
    return _zone(limits, FREE_SHARE)


def contact_zone(limits):
    """where a contact may hold the eyes (CONTACT_SHARE of the limits, inside the EDGE lines)"""
    return _zone(limits, CONTACT_SHARE)


def _clamp(angles, limits):
    return (min(max(angles[0], -limits.yaw), limits.yaw), min(max(angles[1], -limits.down), limits.up))


def soft(value, limit):
    """the eye angle for a wanted angle `value` against `limit` (review 8, R2): the same up to SOFT_FROM of the limit,
    beyond it limit * (SOFT_FROM + (1 - SOFT_FROM) tanh((x - SOFT_FROM) / (1 - SOFT_FROM))) with x = |value| / limit.
    It joins with slope 1 (C1), keeps rising, and approaches the limit: a camera exactly at the limit is looked at
    with 90.5 % of it, one 1.4 times as far with 98.6 %, one 3 times as far with 99.9995 %; far beyond that tanh is
    1.0 in floating point and the eyes are at the limit, never past it."""
    x = abs(value) / limit
    if x <= SOFT_FROM:
        return value
    span = 1.0 - SOFT_FROM
    out = limit * (SOFT_FROM + span * math.tanh((x - SOFT_FROM) / span))
    return out if value > 0 else -out


def soften(angles, limits):
    """soft() on each axis: yaw against limits.yaw, pitch against limits.up above and limits.down below"""
    yaw, pitch = angles
    return soft(yaw, limits.yaw), soft(pitch, limits.up if pitch > 0 else limits.down)


def contact_angles(camera, limits):
    """the eye angles that look at the camera (yaw, pitch) during a contact: softened, then held in the contact zone"""
    zone = contact_zone(limits)
    yaw, pitch = soften(camera, limits)
    return min(max(yaw, -zone.yaw), zone.yaw), min(max(pitch, -zone.down), zone.up)


def keep_off(angles, camera, degrees, limits):
    """angles moved away from the camera's angles until they are `degrees` off it, inside the limits: straight away
    when that stays inside, else the nearest of the other ways round the camera that does (or the farthest)"""
    dy, dp = angles[0] - camera[0], angles[1] - camera[1]
    d = math.hypot(dy, dp)
    if d >= degrees:
        return angles
    base = math.atan2(dp, dy) if d > 1e-9 else -math.pi / 2.0
    best = None
    for k in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6):
        a = base + k * math.pi / 6.0
        cand = _clamp((camera[0] + degrees * math.cos(a), camera[1] + degrees * math.sin(a)), limits)
        sep = math.hypot(cand[0] - camera[0], cand[1] - camera[1])
        if sep >= degrees - 1e-9:
            return cand
        if best is None or sep > best[0]:
            best = (sep, cand)
    return best[1]


def _profile(t):
    """minimum jerk: the share of a saccade done at the time t in 0..1"""
    return t * t * t * (10.0 + t * (6.0 * t - 15.0))


def saccade_frames(amplitude):
    """frames a saccade of `amplitude` degrees takes: 2 under SHORT_SACCADE, 3 up to LONG_SACCADE, 4 beyond (never one:
    at 30 fps a one-frame jump reads as a teleport; the main sequence D = 21 + 2.2 A ms is 54 ms at 15 degrees)"""
    if amplitude < SHORT_SACCADE:
        return 2
    return 3 if amplitude <= LONG_SACCADE else 4


def _press(value, start, ceiling):
    """the same up to `start`, then along tanh toward `ceiling` (slope 1 at `start`)"""
    a = abs(value)
    if a <= start:
        return value
    span = ceiling - start
    if span <= 0.0:
        return math.copysign(start, value)
    return math.copysign(start + span * math.tanh((a - start) / span), value)


def pressed(angles, limits):
    """a fixation's eye angles: the same inside the free zone, pressed softly against the wall (WALL of each limit)
    beyond it, so a fixation never runs to the edge"""
    free = free_zone(limits)
    yaw, pitch = angles
    yaw = _press(yaw, free.yaw, WALL * limits.yaw)
    pitch = _press(pitch, free.up, WALL * limits.up) if pitch >= 0.0 else _press(pitch, free.down, WALL * limits.down)
    return yaw, pitch


def drift_track(frames, rng):
    """(yaw, pitch) offsets of the fixation drift and the microsaccades for each frame, from rng.random() alone"""
    out, dy, dp = [], 0.0, 0.0
    low, high = MICRO_INTERVAL
    next_micro = low + rng.random() * (high - low)
    for frame in range(frames):
        if frame >= next_micro:
            radius, turn = MICRO_SIZE * math.sqrt(rng.random()), 2.0 * math.pi * rng.random()
            dy, dp = radius * math.cos(turn), radius * math.sin(turn)
            next_micro = frame + low + rng.random() * (high - low)
        else:
            dy = min(max(dy + (2.0 * rng.random() - 1.0) * DRIFT_STEP, -DRIFT_LIMIT), DRIFT_LIMIT)
            dp = min(max(dp + (2.0 * rng.random() - 1.0) * DRIFT_STEP, -DRIFT_LIMIT), DRIFT_LIMIT)
        out.append((dy, dp))
    return out


def _runs(mask):
    """[(first, last)] of the runs of True"""
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


# ---- the plan: contacts, fast turns, fixations ------------------------------------------------

def reachable(cameras, limits):
    """per frame whether the camera ((yaw, pitch), behind) is within reach of a contact: within CONTACT_ERROR of the
    eyes held at contact_angles"""
    return [not behind and _apart(contact_angles(angles, limits), angles) <= CONTACT_ERROR for angles, behind in cameras]


def contact_runs(reach, cuts, anchors):
    """[(first, last)] frame indices of the contacts, from `reach` (a bool per frame), the cut indices and the anchor
    indices: see the module docstring"""
    n = len(reach)
    ok = list(reach)
    for a, b in _runs([not v for v in ok]):
        if b - a + 1 <= CONTACT_GAP and a > 0 and b < n - 1:
            for i in range(a, b + 1):
                ok[i] = True
    for c in cuts:
        for i in range(max(0, c - END_CLEAR), min(n, c + CUT_CLEAR)):
            ok[i] = False
    long_, mid = [], []
    for a, b in _runs(ok):
        length = b - a + 1
        if length >= CONTACT_MIN:
            if length > CONTACT_MAX:
                inner = [t for t in anchors if a <= t <= b]
                s = min(max(a, inner[0] - 2 * CONTACT_MAX // 3), b - CONTACT_MAX + 1) if inner else a
                a, b = s, s + CONTACT_MAX - 1
            long_.append((a, b))
        elif length >= CONTACT_MID and any(a - ANCHOR_NEAR <= t <= b + ANCHOR_NEAR for t in anchors):
            mid.append((-length, a, b))
    mid.sort()
    keep = max(0, len(long_) - CONTACT_SPARE)
    return sorted(long_ + [(a, b) for _, a, b in mid[:keep]])


def hand_runs(seen, hands, forward, limits, contacts=(), leads=(), palms=None):
    """[(first, last, side, metres, settle)] frame indices where the eyes look at a hand (`hands`: hand_points),
    sorted: runs of frames on which the hand's look point is HAND_NEAR to HAND_FAR metres from the eyes, before her face
    (in the HAND_ZONE of the limits seen in the head, or within HAND_REACH degrees of it: the face is turned to the
    hand and the eyes rest near their middle on it), HAND_CAMERA degrees or more off the camera, with its palm (`palms`:
    hand_palms, where known) turned HAND_PALM degrees or more away from the camera (a palm shown to the viewer is a
    gesture to the viewer), and moving under HAND_FAST deg/s seen from the eyes in the world (gaps of HAND_JOIN frames
    closed); HAND_MIN frames long or more with the hand under HAND_SLOW deg/s on one frame at least (it comes to rest,
    or nearly, before her face: `settle` is the first such frame).  Where both hands qualify at once the longer run is
    kept (the nearer on a tie).  The contacts and the leads (as plan makes them: the first frame its saccade may start,
    its landing, the turn's onset, ...) win: no run on the frames from the saccade into a contact to its end, nor from
    a lead's saccade to GUARD frames after its turn's onset.  `metres` is the hand's median distance on the run."""
    rest = angles_of(forward)
    n = len(seen)
    longest = saccade_frames(float("inf"))
    zone = _zone(limits, HAND_ZONE)
    blocked = [False] * n
    for a, b in contacts:
        for i in range(max(0, a - longest - 1), min(n, b + 1)):
            blocked[i] = True
    for lead in leads:
        for i in range(max(0, lead[0] - 1), min(n, lead[2] + GUARD + 1)):
            blocked[i] = True
    candidates = []
    for side, points in sorted(hands.items()):
        ok, speed, dist = [], [], []
        before = None
        palm = (palms or {}).get(side)
        for i, s in enumerate(seen):
            v = tuple(p - e for p, e in zip(points[i], s.eye))
            metres = math.sqrt(sum(c * c for c in v)) * UNIT_M
            angles, behind = _seen(s, points[i], forward, rest)
            moving = degrees_between(before, v) * FPS if before is not None else 0.0
            before = v
            dist.append(metres)
            speed.append(moving)
            shown = palm is not None and palm[i] is not None and \
                degrees_between(palm[i], tuple(c - p for c, p in zip(s.camera, points[i]))) < HAND_PALM
            ok.append(not behind and not blocked[i] and HAND_NEAR <= metres <= HAND_FAR and moving <= HAND_FAST
                      and degrees_between(v, tuple(c - e for c, e in zip(s.camera, s.eye))) >= HAND_CAMERA
                      and not shown and _apart(_clamp(angles, zone), angles) <= HAND_REACH)
        joined = []
        for a, b in _runs(ok):
            if joined and a - joined[-1][1] - 1 <= HAND_JOIN and not any(blocked[joined[-1][1] + 1:a]):
                joined[-1] = (joined[-1][0], b)
            else:
                joined.append((a, b))
        for a, b in joined:
            settle = next((i for i in range(a, b + 1) if speed[i] <= HAND_SLOW), None)
            if b - a + 1 >= HAND_MIN and settle is not None:
                candidates.append((a, b, side, _median(dist[a:b + 1]), settle))
    chosen = []
    for run in sorted(candidates, key=lambda r: (r[0] - r[1], r[3], r[0])):
        if all(run[1] < c[0] or run[0] > c[1] for c in chosen):
            chosen.append(run)
    return sorted(chosen)


class Turn(NamedTuple):
    """a fast turn of the head (frame indices)"""
    onset: int
    far: int                        # the frame it has gone furthest by (within 20 frames of the onset)
    sign: float                     # 1.0 toward her left (+yaw), -1.0 toward her right
    last: int                       # the last frame of its run above TURN_SPEED
    degrees: float                  # how far it goes its way from the onset to `far`


def fast_turns(seen, forward):
    """(the head's forward in the world per frame, [Turn]): see the module docstring (Leads)"""
    fw = [fk.rotate(s.head, forward) for s in seen]
    yaw = [math.degrees(math.atan2(f[0], -f[2])) for f in fw]
    step = [0.0] + [(yaw[i] - yaw[i - 1] + 180.0) % 360.0 - 180.0 for i in range(1, len(yaw))]
    rate = [v * FPS for v in step]
    turns = []
    for a, b in _runs([abs(v) > TURN_SPEED for v in rate]):
        if b - a + 1 < 2:
            continue
        sign = 1.0 if sum(rate[a:b + 1]) > 0 else -1.0
        peak = max(sign * v for v in rate[a:b + 1])
        onset = next(i for i in range(max(1, a - 15), b + 1) if sign * rate[i] > 0.3 * peak)
        far, best, total = onset, 0.0, 0.0
        for i in range(onset + 1, min(len(yaw), onset + 21)):
            total += sign * step[i]
            if total > best:
                far, best = i, total
        turns.append(Turn(onset, far, sign, b, best))
    return fw, turns


def face_ways(seen, fw, rest):
    """per frame the face's way seen in the head (yaw, pitch from the rest gaze): the head's forward averaged over the
    frame and the next FACE_AHEAD, where the face is going"""
    n = len(seen)
    total = [(0.0, 0.0, 0.0)]
    for f in fw:
        total.append(tuple(t + c for t, c in zip(total[-1], f)))
    out = []
    for i in range(n):
        j = min(n - 1, i + FACE_AHEAD)
        out.append(_head_angles(seen[i], _unit(tuple(total[j + 1][c] - total[i][c] for c in range(3))), rest)[0])
    return out


def face_target(face, offset, camera, free):
    """where a recentre, a glance or a look away goes (yaw, pitch in the head): the face's way `face` off by
    `offset`, inside the free zone, and AVOID degrees off the camera's angles `camera` (pushed straight away from it
    when nearer)"""
    t = (min(max(face[0] + offset[0], -free.yaw), free.yaw), min(max(face[1] + offset[1], -free.down), free.up))
    dy, dp = t[0] - camera[0], t[1] - camera[1]
    d = math.hypot(dy, dp)
    if d >= AVOID:
        return t
    if d < 1e-9:
        dy, dp, d = 0.0, -1.0, 1.0
    return camera[0] + dy * AVOID / d, camera[1] + dp * AVOID / d


def flips(raw, kept_before, raw_before, camera, limits):
    """True when keeping `raw` off the camera would move the kept gaze FLIP_STEP degrees more than the gaze itself
    moved since the frame before (the keep-off flipping to the other side of the camera), or more than MAX_STEP (the
    keep-off comes after the fixation's MAX_STEP)"""
    if raw_before is None or kept_before is None:
        return False
    kept = keep_off(raw, camera, KEEP_OFF, limits)
    moved = math.hypot(kept[0] - kept_before[0], kept[1] - kept_before[1])
    return moved > MAX_STEP + 1e-6 or moved - math.hypot(raw[0] - raw_before[0], raw[1] - raw_before[1]) > FLIP_STEP


def plan(seen, forward, limits=Limits(), seed=0, life=True, anchors=(), min_fixation=MIN_FIXATION, hands=None,
         aims=None, palms=None):
    """(a Look per sight, the saccades, the contacts as (first, last) frame indices, the leads planned, the looks at a
    hand as (first, last, side, metres, settle)): see the module docstring.  `anchors` are frame indices;
    `min_fixation` frames is the shortest fixation (--min-fixation); `hands` the hands' look points per frame
    (hand_points), which choose the looks; `aims` where the eyes aim on a hand per frame (hand_aims; a side without
    one aims at its look point); `palms` the normals out of the palms per frame (hand_palms)."""
    check_limits(limits)
    check_min_fixation(min_fixation)
    rest = angles_of(forward)
    n = len(seen)
    free = free_zone(limits)
    rng = random.Random(2 * seed + 1)
    quick_rng = random.Random("quick %d" % seed)
    drift = drift_track(n, random.Random(2 * seed)) if life else [(0.0, 0.0)] * n
    cameras = [_seen(s, s.camera, forward, rest) for s in seen]
    camera_dirs = [_unit(tuple(c - e for c, e in zip(s.camera, s.eye))) for s in seen]
    cuts = [i for i, s in enumerate(seen) if s.cut]
    contacts = contact_runs(reachable(cameras, limits), cuts, sorted(anchors))
    contact_end, contact_len, contact_start = [None] * n, [0] * n, [None] * n
    for a, b in contacts:
        for i in range(a, b + 1):
            contact_end[i], contact_len[i], contact_start[i] = b, b - a + 1, a
    fw, turns = fast_turns(seen, forward)
    face = face_ways(seen, fw, rest)
    turn_at = [None] * n                # the sustained fast turn (a Turn) each frame lies in, onset to its end
    for turn in turns:
        if turn.degrees >= GATE_TURN:
            for i in range(turn.onset, min(n, max(turn.far, turn.last) + 1)):
                turn_at[i] = turn

    def target(i, offset):
        return face_target(face[i], offset, cameras[i][0], free)

    def fixate(i, eye, point, offset):
        """(the eye angles, the point they look at) of a fixation on frame i, from the frame before's: the reflex
        (VOR_GAIN), the wall, at most MAX_STEP"""
        full, _ = _head_angles(seen[i], point, rest)
        e = (eye[0] + VOR_GAIN[0] * (full[0] - eye[0]), eye[1] + VOR_GAIN[1] * (full[1] - eye[1]))
        e = pressed(e, limits)
        sy, sp = e[0] - eye[0], e[1] - eye[1]
        moved = math.hypot(sy, sp)
        if moved > MAX_STEP:
            e = (eye[0] + sy * MAX_STEP / moved, eye[1] + sp * MAX_STEP / moved)
        return e, _world(seen[i], e, rest)

    def drifts_off(i, eye, point, offset):
        """True when a fixation left alone stays more than GAP off the face's way from LOOK_AHEAD frames on for
        SUSTAIN more frames (the head has moved on)"""
        far = 0
        for k in range(1, LOOK_AHEAD + SUSTAIN + 1):
            j = min(n - 1, i + k)
            eye, point = fixate(j, eye, point, offset)
            if k >= LOOK_AHEAD:
                t = target(j, offset)
                if math.hypot(eye[0] - t[0], eye[1] - t[1]) <= GAP:
                    return False
                far += 1
        return far > SUSTAIN

    def pushed(i, eye, point, offset):
        """True when a fixation left alone stays pressed beyond the free zone, with the face's way WALL_GAP or more
        back toward the middle on the pressed axis, on this frame and the QUICK_SUSTAIN - 1 after it"""
        for k in range(QUICK_SUSTAIN):
            j = i + k
            if j >= n:
                return False
            eye, point = fixate(j, eye, point, offset)
            tg = target(j, offset)
            side = abs(eye[0]) > free.yaw and (tg[0] - eye[0]) * (1.0 if eye[0] > 0.0 else -1.0) <= -WALL_GAP
            up = eye[1] > free.up and tg[1] - eye[1] <= -WALL_GAP
            down = eye[1] < -free.down and tg[1] - eye[1] >= WALL_GAP
            if not (side or up or down):
                return False
        return True

    def quick_goal(i, turn, origin):
        """a quick phase's goal on frame i of a sustained fast turn: as a lead's, toward where the face will be
        QUICK_AHEAD frames on, or where the turn ends if sooner (the head's forward where the turn goes furthest can
        lie behind her in a spin)"""
        far = min(max(turn.far, turn.last), i + QUICK_AHEAD)
        return lead_goal(seen[i], (None, None, turn.onset, far, turn.sign), origin)

    def lead_goal(s, lead, origin):
        _, _, onset, far, sign = lead
        angles, _ = _head_angles(s, fw[far], rest)
        cap = LEAD_SHARE * limits.yaw
        k = min(1.0, cap / max(1e-9, math.hypot(*angles)))
        angles = (angles[0] * k, max(-free.down, min(free.up, angles[1] * k)))
        # never back against the turn: eyes already beyond the cap the way of the turn keep their angle (review gaze-v8:
        # 22 leads went 2 degrees back and the quick phase after them 15 to 25 degrees forward, a reversal)
        return sign * max(sign * angles[0], min(max(cap, sign * origin[0]), sign * origin[0] + LEAD_STEP)), angles[1]

    leads = []                      # [the first frame it may start, the frame it lands by, onset, far, sign]
    longest = saccade_frames(float("inf"))
    for turn in turns:
        if turn.degrees < GATE_TURN:
            continue        # a shake that comes back: no gaze shift to lead, and the reflex counters it
        onset, far, sign = turn.onset, turn.far, turn.sign
        land = onset - rng.randint(*LEAD)
        first = land - (longest - 1)
        if leads and first <= leads[-1][2]:
            continue        # it would start before the lead before has seen its turn start: one lead (a turn with a dip)
        if first >= 1 and not any(contact_end[k] is not None for k in range(max(0, first - QUIET), min(n, onset + 1))):
            leads.append([first, land, onset, far, sign])
    runs = hand_runs(seen, hands or {}, forward, limits, contacts, leads, palms)
    run_of = [None] * n                 # the look at a hand (an index of runs) each frame lies in
    for k, run in enumerate(runs):
        for i in range(run[0], run[1] + 1):
            run_of[i] = k

    def hand_goal(i, k):
        """the eye angles that look, from frame i, at the aim on the hand of run k where it will be HAND_AHEAD frames
        on, or where it settles if it has not yet (the gaze is there before the hand), within the run; held in the
        contact zone"""
        a, b, side, _, settle = runs[k]
        points = (aims or {}).get(side) or hands[side]
        angles, _ = _seen(seen[i], points[min(b, max(a, settle, i + HAND_AHEAD))], forward, rest)
        return contact_angles(angles, limits)

    looks, saccades = [], []
    mode, held, offset = "free", None, (0.0, 0.0)  # held: (angles in the head, the frame they become a world point)
    eye = (0.0, 0.0)                               # the eye angles of the frame before (before keep-off and drift)
    point = _world(seen[0], eye, rest)             # the point in the world they look at
    saccade, landed, lead_i, guard_until, reason_now, raw_before = None, 0, 0, -1, None, None
    hand_run, left_runs = None, set()              # the run the eyes follow in mode "hand"; the runs they have left
    glance_at = rng.randint(*GLANCE)
    shortest = min_fixation + rng.randint(0, FIXATION_SPREAD)
    soonest = QUICK_AFTER + quick_rng.randint(0, QUICK_SPREAD)
    for i, s in enumerate(seen):
        while lead_i < len(leads) and leads[lead_i][1] < i:
            lead_i += 1
        upcoming = leads[lead_i] if lead_i < len(leads) else None
        due = upcoming is not None and upcoming[0] - i <= QUIET
        if held is not None and i >= held[1]:
            point, held = _world(s, held[0], rest), None
        origin = looks[-1].base if looks else (0.0, 0.0)
        want, want_run, quick_turn = None, None, None
        if saccade is None:
            flip = (mode == "free" and held is None and bool(looks) and i - landed >= 1
                    and flips(fixate(i, eye, point, offset)[0], origin, raw_before, cameras[i][0], limits))
            start = next((i + k for k in range(1, longest + 2) if i + k < n and contact_start[i + k] == i + k), None)
            # a contact due within QUIET + 4 frames: no other saccade first (it would be followed by the contact's
            # 2 or 3 frames after it lands)
            contact_soon = any(i + k < n and contact_start[i + k] == i + k for k in range(1, QUIET + longest + 1))
            # a look at a hand: the run the eyes are in (not left yet), or the next one if a saccade made now lands
            # by its first frame; within QUIET + 4 frames of one no recentre, glance or away first
            hand_now = run_of[i] if run_of[i] is not None and run_of[i] not in left_runs else None
            hand_next = next((run_of[i + k] for k in range(1, longest + 2)
                              if i + k < n and run_of[i + k] is not None and runs[run_of[i + k]][0] == i + k), None)
            hand_soon = any(i + k < n and run_of[i + k] is not None and runs[run_of[i + k]][0] == i + k
                            for k in range(1, QUIET + longest + 1))
            if hand_now is None and hand_next is not None and \
                    i + saccade_frames(_apart(origin, soften(hand_goal(i, hand_next), limits))) < runs[hand_next][0]:
                hand_next = None                         # not yet: a saccade made now would land too early
            hand_in = hand_now if hand_now is not None else hand_next
            # sized as it will be made (by the camera of this frame), it lands on the contact's first frame or the one
            # before; once on the camera the eyes stay there until the contact starts
            if mode != "camera" and start is not None and \
                    i + saccade_frames(_apart(origin, soften(contact_angles(cameras[i][0], limits), limits))) >= start:
                want = ("camera", None, "contact")
            elif mode != "camera" and contact_end[i] is not None and contact_end[i] - i + 1 >= contact_len[i] - 3:
                want = ("camera", None, "contact")
            elif mode == "camera" and contact_end[i] is None and not contact_soon:
                want, want_run = (("hand", None, "hand"), hand_in) if hand_in is not None else (("free", None, "look_away"), None)
            elif mode == "hand" and hand_now != hand_run:
                # the hand has gone: the contact or the lead that comes anyway, a look at the next hand, or away
                left_runs.add(hand_run)
                if contact_soon:
                    want = ("camera", None, "contact")
                elif due:
                    want = ("free", upcoming, "lead")
                    lead_i += 1
                elif hand_in is not None:
                    want, want_run = ("hand", None, "hand"), hand_in
                else:
                    want = ("free", None, "hand_away")
            elif mode == "hand":
                full, _ = _head_angles(s, point, rest)
                goal = hand_goal(i, hand_run)
                if i - landed >= CATCH_UP_AFTER and \
                        math.hypot(goal[0] - full[0], goal[1] - full[1]) - PURSUIT_SPEED / FPS > CATCH_UP:
                    want, want_run = ("hand", None, "hand"), hand_run        # the eyes trail: a catch-up saccade
            elif mode == "free" and held is None and hand_in is not None:
                want, want_run = ("hand", None, "hand"), hand_in
            elif mode == "free" and upcoming is not None and upcoming[0] <= i:
                goal = lead_goal(s, upcoming, origin)
                if flip or i + saccade_frames(_apart(origin, soften(goal, limits))) - 1 >= upcoming[1]:
                    # a turn into a contact: the saccade onto the camera leads it (one saccade, not two in a row)
                    want = ("camera", None, "contact") if contact_soon else ("free", upcoming, "lead")
                    lead_i += 1
            elif flip:
                if mode != "camera" and contact_soon:
                    want = ("camera", None, "contact")           # the contact that comes anyway, a little early
                elif due:
                    want = ("free", upcoming, "lead")             # the lead that comes anyway, a little early
                    lead_i += 1
                else:
                    want = ("free", None, "away")
            elif mode == "free" and held is None and i - landed >= soonest and \
                    not (due or contact_soon or hand_soon) and \
                    ((turn_at[i] is not None and turn_at[i].sign * fixate(i, eye, point, offset)[0][0] < -free.yaw)
                     or pushed(i, eye, point, offset)):
                # inside a sustained fast turn, a quick phase the way of the turn once the reflex has carried the eyes
                # back beyond the free zone or the head keeps them pressed to their wall; outside one, a saccade off
                # the wall back to where the face goes
                want, quick_turn = ("free", None, "wall" if turn_at[i] is None else "quick"), turn_at[i]
            elif mode == "free" and held is None and i - landed >= shortest and not (i <= guard_until or due
                                                                                     or contact_soon or hand_soon):
                if drifts_off(i, eye, point, offset):
                    want = ("free", None, "recentre")
                elif degrees_between(point, camera_dirs[min(n - 1, i + LOOK_AHEAD)]) < KEEP_OFF:
                    want = ("free", None, "away")
                elif i - landed >= glance_at:
                    want = ("free", None, "glance")
        if want is not None:
            to, lead, reason = want
            goal_held, new_offset = None, offset
            if to == "camera":
                goal = contact_angles(cameras[i][0], limits)
            elif to == "hand":
                goal, new_offset = hand_goal(i, want_run), (0.0, 0.0)
            elif quick_turn is not None:
                goal, new_offset = quick_goal(i, quick_turn, origin), (0.0, 0.0)
            elif lead is not None:
                goal = lead_goal(s, lead, origin)
                goal_held, new_offset = (goal, lead[2]), (0.0, 0.0)
                guard_until = lead[2] + GUARD
            else:
                new_offset = (0.0, 0.0)
                if reason in ("glance", "look_away"):
                    new_offset = (rng.uniform(*GLANCE_OFF[0]), rng.uniform(*GLANCE_OFF[1]))
                goal = target(i, new_offset)
            amplitude = _apart(origin, soften(goal, limits))
            if amplitude >= MIN_SACCADE and looks:          # on the first frame the eyes are already where they want
                saccade = {"frame": s.frame, "i": i, "frames": saccade_frames(amplitude), "reason": reason,
                           "amplitude": amplitude, "origin": origin, "to": to, "held": goal_held, "offset": new_offset,
                           "run": want_run, "turn": quick_turn}
                saccades.append(saccade)
            else:
                mode, held, landed, offset, hand_run = to, goal_held, i, new_offset, want_run
                if to in ("free", "hand") and goal_held is None:
                    eye, point = goal, _world(s, goal, rest)
                if held is not None and i >= held[1]:
                    point, held = _world(s, held[0], rest), None
                glance_at = rng.randint(*GLANCE)
                shortest = min_fixation + rng.randint(0, FIXATION_SPREAD)
                soonest = QUICK_AFTER + quick_rng.randint(0, QUICK_SPREAD)
        if saccade is not None:
            if saccade["to"] == "camera":
                goal = contact_angles(cameras[i][0], limits)
            elif saccade["to"] == "hand":
                goal = hand_goal(i, saccade["run"])     # where the hand will be, on this frame of it
            elif saccade["held"] is not None:
                goal = saccade["held"][0]
            elif saccade["turn"] is not None:
                goal = quick_goal(i, saccade["turn"], saccade["origin"])   # the way of the turn, on this frame
            else:
                goal = target(i, saccade["offset"])     # where the face's way is on this frame of it
            step = i - saccade["i"] + 1
            share = _profile(min(1.0, step / float(saccade["frames"])))
            o, g = saccade["origin"], soften(goal, limits)
            base = (o[0] + (g[0] - o[0]) * share, o[1] + (g[1] - o[1]) * share)
            state, reason_now = "in_saccade", saccade["reason"]
            eye, point = base, _world(s, base, rest)
            if step >= saccade["frames"]:
                mode, held, landed, offset = saccade["to"], saccade["held"], i, saccade["offset"]
                hand_run = saccade["run"]
                if held is not None and i >= held[1]:
                    point, held = _world(s, held[0], rest), None
                glance_at = rng.randint(*GLANCE)
                shortest = min_fixation + rng.randint(0, FIXATION_SPREAD)
                soonest = QUICK_AFTER + quick_rng.randint(0, QUICK_SPREAD)
                saccade = None
        elif mode == "hand":
            # smooth pursuit of her own hand: the reflex holds the gaze of the frame before, and the gaze follows the
            # hand from there at most PURSUIT_SPEED (a person tracks the hand she moves with a gain near 1)
            full, _ = _head_angles(s, point, rest)
            goal = hand_goal(i, hand_run)
            dy, dp = goal[0] - full[0], goal[1] - full[1]
            d, most = math.hypot(dy, dp), PURSUIT_SPEED / FPS
            if d > most:
                dy, dp = dy * most / d, dp * most / d
            zone = contact_zone(limits)
            base = (min(max(full[0] + dy, -zone.yaw), zone.yaw), min(max(full[1] + dp, -zone.down), zone.up))
            sy, sp = base[0] - origin[0], base[1] - origin[1]
            moved = math.hypot(sy, sp)
            if moved > MAX_STEP:
                base = (origin[0] + sy * MAX_STEP / moved, origin[1] + sp * MAX_STEP / moved)
            state = "hand"
            eye, point = base, _world(s, base, rest)
        elif mode == "camera":
            base, state = contact_angles(cameras[i][0], limits), "contact"
            if looks:
                sy, sp = base[0] - origin[0], base[1] - origin[1]
                moved = math.hypot(sy, sp)
                if moved > MAX_STEP:
                    base = (origin[0] + sy * MAX_STEP / moved, origin[1] + sp * MAX_STEP / moved)
            eye, point = base, _world(s, base, rest)
        elif held is not None:
            base, state = soften(held[0], limits), "lead"
            eye, point = base, _world(s, base, rest)
        else:
            eye, point = fixate(i, eye, point, offset)
            base, state = eye, "free"
        raw_before = base
        if not (state == "contact" or (state == "in_saccade" and reason_now in ("contact", "look_away"))):
            base = keep_off(base, cameras[i][0], KEEP_OFF, limits)
        final = _clamp((base[0] + drift[i][0], base[1] + drift[i][1]), limits)
        if looks and state != "in_saccade":
            # outside saccades the angles written turn at most MAX_STEP a frame, the drift included
            last = (looks[-1].yaw, looks[-1].pitch)
            sy, sp = final[0] - last[0], final[1] - last[1]
            moved = math.hypot(sy, sp)
            if moved > MAX_STEP:
                final = (last[0] + sy * MAX_STEP / moved, last[1] + sp * MAX_STEP / moved)
        looks.append(Look(s.frame, final[0] + 0.0, final[1] + 0.0, state, cameras[i][0], _apart(final, cameras[i][0]),
                          mode, base))
    out = [{"frame": c["frame"], "frames": c["frames"], "reason": c["reason"], "amplitude": c["amplitude"]} for c in saccades]
    return looks, out, contacts, leads, runs


# ---- the measures of the analysis -----------------------------------------------------------

def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def eye_measures(angles, limits):
    """a07 / a13: the share of frames with the eyes (yaw, pitch from the rest gaze) at the edge (EDGE of a limit on
    some axis), the longest stay there in seconds, and the share 15 degrees or more off the middle"""
    edge = [max(abs(y) / limits.yaw, p / limits.up if p > 0 else -p / limits.down) >= EDGE for y, p in angles]
    longest = max([b - a + 1 for a, b in _runs(edge)] or [0])
    far = [degrees_between(direction_of(y, p), (0.0, 0.0, -1.0)) >= 15.0 for y, p in angles]
    n = float(len(angles))
    return {"edge_share": _r(sum(edge) / n), "edge_longest_s": _r(longest / FPS, 3), "eccentric_15_share": _r(sum(far) / n)}


def contact_measures(errors):
    """a13: eye contact is the gaze within CONTACT_SEEN of the camera, gaps of CONTACT_JOIN frames joined: the share of
    frames, the episodes, their median and longest length in seconds"""
    merged = []
    for a, b in _runs([e <= CONTACT_SEEN for e in errors]):
        if merged and a - merged[-1][1] - 1 <= CONTACT_JOIN:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    lengths = [(b - a + 1) / FPS for a, b in merged]
    return {"share": _r(sum(1 for e in errors if e <= CONTACT_SEEN) / float(len(errors))), "episodes": len(merged),
            "episode_median_s": _r(_median(lengths), 3), "longest_s": _r(max(lengths or [0.0]), 3)}


def _unwrap(values):
    out, last = [], None
    for v in values:
        if last is not None:
            v = last + (v - last + 180.0) % 360.0 - 180.0
        out.append(v)
        last = v
    return out


def lead_measure(head_yaw, gaze_yaw, margins=LEAD_MARGINS):
    """a20: the fast turns of the head (its yaw rate above LEAD_TURN deg/s for LEAD_MIN_FRAMES frames or more, outside
    the margins at the start and the end) and those the eyes lead: the eye in the head (gaze yaw minus head yaw)
    moves more than LEAD_SEEN degrees the way of the turn in the 6 frames before its onset (the first of the 15
    frames before at 30 % of the peak).  Yaws in degrees, in the world."""
    yh, yg = _unwrap(head_yaw), _unwrap(gaze_yaw)
    n = len(yh)
    rate = [0.0] + [(yh[i] - yh[i - 1]) * FPS for i in range(1, n)]
    turns = led = 0
    for a, b in _runs([abs(v) > LEAD_TURN for v in rate]):
        if b - a + 1 < LEAD_MIN_FRAMES or a < margins[0] or b > n - 1 - margins[1] or a < 15:
            continue
        sign = 1.0 if sum(rate[a:b + 1]) / (b - a + 1) > 0 else -1.0
        window = [sign * rate[i] for i in range(a - 15, b + 1)]
        peak = max(window)
        onset = a - 15 + next(k for k, v in enumerate(window) if v > 0.3 * peak)
        turns += 1
        if sign * ((yg[onset] - yh[onset]) - (yg[onset - 6] - yh[onset - 6])) > LEAD_SEEN:
            led += 1
    return {"turns": turns, "led": led, "share": _r(led / float(turns), 3) if turns else 0.0}


def eye_steps(gazes, heads):
    """a13's v_sac per frame step (degrees, step i from frame i to i + 1): the part of the gaze's step in the world
    that the eye makes in the head the same way (not the counter-rotation, which moves the eye but not the gaze, nor
    a head turn carrying a resting eye, which moves the gaze but not the eye).  Small angles: chords as radians."""
    out = []
    for i in range(len(gazes) - 1):
        a = fk.rotate(fk.conjugate(heads[i]), gazes[i])
        b = fk.rotate(fk.conjugate(heads[i + 1]), gazes[i + 1])
        d_eye = tuple(y - x for x, y in zip(a, b))
        d_gaze = fk.rotate(fk.conjugate(heads[i + 1]), tuple(y - x for x, y in zip(gazes[i], gazes[i + 1])))
        n_eye = math.sqrt(sum(v * v for v in d_eye))
        n_gaze = math.sqrt(sum(v * v for v in d_gaze))
        along = sum(x * y for x, y in zip(d_eye, d_gaze)) / n_gaze if n_gaze > 1e-12 else 0.0
        out.append(math.degrees(min(max(along, 0.0), min(n_eye, n_gaze))))
    return out


def carried_measure(gazes, saccades, heads=None):
    """a07: the large changes of the gaze in the world (more than LARGE_CHANGE degrees within LARGE_WINDOW frames, one
    per run, at its largest window) and how many the head carried: less than half of the window's path inside the
    listed saccades (a frame's step counts when the saccade covers either end).  `gazes` are world directions.
    With `heads` (the head's world rotations) also by_eye_motion: the same events split by a13's v_sac instead of
    the list (eye_steps; review eye, finding 1: with many saccades the list's split counts most steps as theirs)."""
    n = len(gazes)
    moving = [False] * n
    for s in saccades:
        for i in range(s["frame"], min(n, s["frame"] + s["frames"])):
            moving[i] = True
    steps = [degrees_between(gazes[i], gazes[i + 1]) for i in range(n - 1)]
    w = LARGE_WINDOW
    change = [degrees_between(gazes[i], gazes[i + w]) for i in range(n - w)]
    by_eye = eye_steps(gazes, heads) if heads is not None else None
    events = carried = carried_by_eye = 0
    for a, b in _runs([c > LARGE_CHANGE for c in change]):
        k = max(range(a, b + 1), key=lambda i: (change[i], -i))
        frames = range(k, k + w)
        path = sum(steps[f] for f in frames)
        by_saccade = sum(steps[f] for f in frames if moving[f] or moving[f + 1])
        events += 1
        carried += by_saccade < 0.5 * path
        if by_eye is not None:
            carried_by_eye += sum(by_eye[f] for f in frames) < 0.5 * path
    out = {"events": events, "saccade_made": events - carried, "head_carried": carried,
           "share": _r(carried / float(events), 3) if events else 0.0}
    if by_eye is not None:
        out["by_eye_motion"] = {"events": events, "head_carried": carried_by_eye,
                                "share": _r(carried_by_eye / float(events), 3) if events else 0.0}
    return out


def _percentile(values, share):
    ordered = sorted(values)
    return ordered[int(round(share * (len(ordered) - 1)))] if ordered else 0.0


def smooth_measures(angles, saccades):
    """stage 5: the per-frame turns of the eye in the head (degrees between consecutive eye directions; the largest
    and the 99th percentile, of all steps and of those outside the listed saccades: a step is a saccade's when it
    ends on one of its frames), the median fixation in seconds (from a saccade's landing to the next one's first
    frame, eye contacts included) and the reversals a second: a saccade that moves the eye in the head more than
    REVERSAL degrees followed, within REVERSAL_WITHIN frames of its landing, by one that moves it more than REVERSAL
    the opposite way (review gaze-smooth 2.4: the eyes' own jumps going back and forth, not the counter-rotation of a
    nod).  `angles` are (yaw, pitch) of the eye in the head per frame."""
    n = len(angles)
    moving = [False] * n
    for s in saccades:
        for i in range(s["frame"], min(n, s["frame"] + s["frames"])):
            moving[i] = True
    dirs = [direction_of(y, p) for y, p in angles]
    steps = [degrees_between(dirs[i], dirs[i + 1]) for i in range(n - 1)]
    outside = [v for i, v in enumerate(steps) if not moving[i + 1]]
    fixations = [b["frame"] - (a["frame"] + a["frames"] - 1) for a, b in zip(saccades, saccades[1:])]
    jumps = []
    for s in saccades:
        a, b = s["frame"] - 1, s["frame"] + s["frames"] - 1
        jumps.append((angles[b][0] - angles[a][0], angles[b][1] - angles[a][1]) if 0 <= a and b < n else (0.0, 0.0))
    turned = sum(1 for s, t, u, v in zip(saccades, saccades[1:], jumps, jumps[1:])
                 if t["frame"] - (s["frame"] + s["frames"] - 1) <= REVERSAL_WITHIN and math.hypot(*u) > REVERSAL
                 and math.hypot(*v) > REVERSAL and u[0] * v[0] + u[1] * v[1] < 0.0)
    return {"eye_steps": {"max": _r(max(steps or [0.0]), 3), "p99": _r(_percentile(steps, 0.99), 3),
                          "outside_saccades_max": _r(max(outside or [0.0]), 3),
                          "outside_saccades_p99": _r(_percentile(outside, 0.99), 3)},
            "fixation_median_s": _r(_median(fixations) / FPS, 3),
            "reversals_per_second": _r(turned / (n / FPS), 4) if n else 0.0}


def world_measures(heads, angles, saccades, contacts=(), rest=(0.0, 0.0)):
    """whether the gaze stays put in the world between saccades (review gaze-smooth 1.3 to 1.6), on the steps from
    frame i to i + 1 that touch no frame of a listed saccade.  `heads` are the head's world rotations, `angles` the
    eye's (yaw, pitch) in the head from the rest gaze `rest`, without the drift and the microsaccades.  The head's
    speed on a step is how far it would carry the gaze of an eye resting in it.  With the head at STEADY_HEAD deg/s:
    the gains of the counter-rotation sideways and up and down (the eye's move regressed on the move that would hold
    the gaze: 1 holds it, 0 is a doll's eye riding the head; None when no step asks for a move that way) and the
    share of steps whose gaze moves under STEADY_GAZE deg/s, also by the head's speed in STEADY_BANDS (steady_by_head:
    the split of W2 in the remeasure of stage 6, 15 to 60 and 60 to 120 deg/s).  With the head under STILL_HEAD
    deg/s, outside the `contacts` ((first, last) frames, where the eyes follow the camera): the share of steps whose
    gaze moves more than STILL_FLOW degrees (eyes gliding with no target)."""
    n = len(angles)
    moving = [False] * n
    for s in saccades:
        for i in range(s["frame"], min(n, s["frame"] + s["frames"])):
            moving[i] = True
    held = [False] * n
    for a, b in contacts:
        for i in range(max(0, a), min(n, b + 1)):
            held[i] = True
    gazes = [fk.rotate(h, direction_of(y + rest[0], p + rest[1])) for h, (y, p) in zip(heads, angles)]
    num, den, steady, still = [0.0, 0.0], [0.0, 0.0], [], []
    bands = {band: [] for band in STEADY_BANDS}
    for i in range(n - 1):
        if moving[i] or moving[i + 1]:
            continue
        g = gazes[i]
        carried = degrees_between(g, fk.rotate(heads[i + 1], fk.rotate(fk.conjugate(heads[i]), g))) * FPS
        step = degrees_between(g, gazes[i + 1])
        if STEADY_HEAD[0] <= carried < STEADY_HEAD[1]:
            hold = angles_of(fk.rotate(fk.conjugate(heads[i + 1]), g))
            hold = ((hold[0] - rest[0] + 180.0) % 360.0 - 180.0, hold[1] - rest[1])
            for axis in (0, 1):
                need = hold[axis] - angles[i][axis]
                num[axis] += (angles[i + 1][axis] - angles[i][axis]) * need
                den[axis] += need * need
            steady.append(step * FPS < STEADY_GAZE)
        for low, high in STEADY_BANDS:
            if low <= carried < high:
                bands[(low, high)].append(step * FPS < STEADY_GAZE)
        if carried < STILL_HEAD and not (held[i] or held[i + 1]):
            still.append(step > STILL_FLOW)
    gain = [_r(num[k] / den[k], 3) if den[k] > 1e-6 else None for k in (0, 1)]
    share = lambda flags: _r(sum(flags) / float(len(flags)), 3) if flags else 0.0
    return {"gain_yaw": gain[0], "gain_pitch": gain[1], "steady_steps": len(steady), "steady_share": share(steady),
            "steady_by_head": {"%d_%d" % band: {"steps": len(flags), "share": share(flags)}
                               for band, flags in bands.items()},
            "still_steps": len(still), "flow_share": share(still)}


def wall_measures(angles, limits):
    """the share of frames with the eyes at WALL_SEEN of their limit or beyond: sideways, and up or down"""
    n = float(len(angles)) or 1.0
    return {"yaw": _r(sum(1 for y, _ in angles if abs(y) >= WALL_SEEN * limits.yaw) / n),
            "pitch": _r(sum(1 for _, p in angles if p >= WALL_SEEN * limits.up or p <= -WALL_SEEN * limits.down) / n)}


def plan_measures(seen, looks, saccades, forward, limits, contacts=()):
    """the measures of the analysis computed on the plan (the world gaze from the head's rotation and the eye angles;
    its steadiness from the angles before the drift is added)"""
    rest = angles_of(forward)
    gazes = [_world(s, (look.yaw, look.pitch), rest) for s, look in zip(seen, looks)]
    yaw = lambda v: math.degrees(math.atan2(v[0], -v[2]))
    out = eye_measures([(look.yaw, look.pitch) for look in looks], limits)
    out["contact"] = contact_measures([look.error for look in looks])
    margins = LEAD_MARGINS if len(seen) > 2 * sum(LEAD_MARGINS) else (15, 0)
    out["lead"] = lead_measure([yaw(fk.rotate(s.head, forward)) for s in seen], [yaw(g) for g in gazes], margins)
    out["head_carried"] = carried_measure(gazes, saccades, [s.head for s in seen])
    out["saccades_per_second"] = _r(len(saccades) / (len(seen) / FPS), 3)
    out.update(smooth_measures([(look.yaw, look.pitch) for look in looks], saccades))
    out["world_gaze"] = world_measures([s.head for s in seen], [look.base for look in looks], saccades, contacts, rest)
    out["wall_share"] = wall_measures([(look.yaw, look.pitch) for look in looks], limits)
    return out


# ---- the song -------------------------------------------------------------------------------

def song_anchors(cues=None, chorus=(), fps=FPS):
    """the frames of the song's anchors: the ends of the lyric lines and the starts of the hooks of a cues file (the
    JSON of tools/mv_text.py: "cues" with "start", "end" in seconds and "style" "lyric" or "hook") and the heads of
    the choruses (seconds)"""
    out = set()
    for cue in (cues or {}).get("cues", []):
        if cue.get("style") == "lyric":
            out.add(int(round(float(cue["end"]) * fps)))
        elif cue.get("style") == "hook":
            out.add(int(round(float(cue["start"]) * fps)))
    for seconds in chorus:
        out.add(int(round(float(seconds) * fps)))
    return sorted(out)


# ---- the motion and the report --------------------------------------------------------------

def eye_motion(looks, model_name):
    """the 両目 track: a key on the first and the last frame and wherever the angles change, linear curves"""
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    values = [(round(look.yaw, 6), round(look.pitch, 6)) for look in looks]
    keys = []
    for i, look in enumerate(looks):
        if 0 < i < len(looks) - 1 and values[i - 1] == values[i] == values[i + 1]:
            continue
        keys.append(vmd.BoneKey(EYES, look.frame, fk.ZERO, fk.stored(eye_rotation(look.yaw, look.pitch)), straight))
    return vmd.Motion(model_name=model_name, bones=keys)


def probe_motion(model_name):
    straight = vmd.bone_interpolation(vmd.LINEAR_CURVE)
    keys = []
    for start, end, ui in PROBE:
        for frame in sorted({start, end}):
            keys.append(vmd.BoneKey(EYES, frame, fk.ZERO, mathutil.ui_to_quat(*ui), straight))
    return vmd.Motion(model_name=model_name, bones=keys)


def describe(yaw, pitch):
    """which way a gaze of (yaw, pitch) from the rest looks, in words"""
    parts = []
    if yaw > 0.5:
        parts.append("to her left (+X), the viewer's right with the camera in front")
    elif yaw < -0.5:
        parts.append("to her right (-X), the viewer's left with the camera in front")
    if pitch > 0.5:
        parts.append("up")
    elif pitch < -0.5:
        parts.append("down")
    return " and ".join(parts) if parts else "straight ahead"


def probe_segments(forward):
    """each piece of the probe with the way the eyes should look under the convention of mmd_cli/fk.py"""
    rest = angles_of(forward)
    out = []
    for start, end, ui in PROBE:
        yaw, pitch = angles_of(fk.rotate(fk.applied(mathutil.ui_to_quat(*ui)), forward))
        yaw, pitch = yaw - rest[0], pitch - rest[1]
        out.append({"frames": [start, end], "window": list(ui), "gaze": [_r(yaw, 3), _r(pitch, 3)], "looks": describe(yaw, pitch)})
    return out


def _count(items):
    out = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def dance_eye_keys(dance):
    """the keys the dance itself has on the eye bones, with the largest turn among them"""
    out = {}
    for name in (EYES,) + EYE_PAIR:
        keys = [k for k in dance.bones if k.name == name]
        out[name] = {"keys": len(keys),
                     "max_degrees": _r(max([math.degrees(2.0 * math.acos(min(1.0, abs(fk.normalized(k.rotation)[3]))))
                                            for k in keys] or [0.0]), 3)}
    return out


def _error_summary(values):
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {"mean": _r(sum(values) / len(values), 3), "p95": _r(ordered[int(round(0.95 * (len(ordered) - 1)))], 3),
            "max": _r(ordered[-1], 3)}


@dataclass
class Gaze:
    looks: List[Look]
    saccades: List[dict]
    cuts: List[int]
    motion: vmd.Motion
    report: dict
    sights: List[Sight]
    forward: Tuple[float, float, float]
    contacts: List[Tuple[int, int]]
    hand_points: dict = None            # side -> the hand's look point in the world per frame (hand_points)
    hand_looks: list = None             # (first, last, side, metres, settle) frame indices of the looks at a hand
    hand_aims: dict = None              # side -> where the eyes aim on the hand in the world per frame (hand_aims)


def gaze(model, dance, camera, max_yaw=MAX_YAW, max_up=MAX_UP, max_down=MAX_DOWN, seed=0, life=True, anchors=(),
         min_fixation=MIN_FIXATION):
    """the 両目 motion for `dance` seen by `camera` on `model`, with the per-frame plan and the report; `anchors` are
    frames of the song (song_anchors)"""
    limits = Limits(float(max_yaw), float(max_up), float(max_down))
    check_limits(limits)
    if not dance.bones:
        raise ValueError("the dance has no bone keys")
    eyes, center, parent = eye_bones(model)
    forward, forward_from = rest_forward(model, eyes)
    seen = sights(model, dance, camera)
    first = seen[0].frame
    marks = sorted({a - first for a in anchors if 0 <= a - first < len(seen)})
    hands = hand_points(model, dance, first, seen[-1].frame)
    aims = hand_aims(model, dance, first, seen[-1].frame)
    palms = hand_palms(model, dance, first, seen[-1].frame)
    looks, saccades, contacts, leads, runs = plan(seen, forward, limits, seed, life, marks, min_fixation, hands, aims,
                                                  palms)
    cuts = [s.frame for s in seen if s.cut]
    counts = {state: 0 for state in STATES}
    for look in looks:
        counts[look.state] += 1
    amplitudes = [s["amplitude"] for s in saccades]
    contact_frames = sum(b - a + 1 for a, b in contacts)
    hand_frames = sum(run[1] - run[0] + 1 for run in runs)

    def anchor_of(a, b):
        near = [m for m in marks if a - ANCHOR_NEAR <= m <= b + ANCHOR_NEAR]
        return near[0] + first if near else None
    report = {
        "frames": [seen[0].frame, seen[-1].frame], "seed": seed, "min_fixation": min_fixation,
        "limits": dict(limits.to_json(), soft_from=SOFT_FROM),
        "zones": {"free": free_zone(limits).to_json(), "contact": contact_zone(limits).to_json(),
                  "contact_error": CONTACT_ERROR,
                  "wall": {k: _r(v) for k, v in _zone(limits, (WALL, WALL, WALL)).to_json().items()}},
        "motion": {"vor_gain": list(VOR_GAIN), "gate_turn": GATE_TURN, "quick_after": QUICK_AFTER,
                   "quick_spread": QUICK_SPREAD, "quick_sustain": QUICK_SUSTAIN, "quick_ahead": QUICK_AHEAD,
                   "face_ahead": FACE_AHEAD,
                   "max_step": MAX_STEP, "gap": GAP,
                   "wall_gap": WALL_GAP, "sustain": SUSTAIN, "fixation_spread": FIXATION_SPREAD,
                   "saccade_frames": {"short": SHORT_SACCADE, "long": LONG_SACCADE}},
        "hand_rules": {"points": list(HAND_POINTS), "aim": list(FINGER_TIPS), "palm": HAND_PALM,
                       "metres": [HAND_NEAR, HAND_FAR],
                       "reach": HAND_REACH,
                       "camera": HAND_CAMERA, "fast": HAND_FAST, "slow": HAND_SLOW, "min_frames": HAND_MIN,
                       "join": HAND_JOIN, "ahead": HAND_AHEAD, "pursuit": PURSUIT_SPEED, "catch_up": CATCH_UP,
                       "catch_up_after": CATCH_UP_AFTER, "zone": list(HAND_ZONE), "sides": sorted(hands)},
        "hands": {"count": len(runs), "frames": hand_frames, "share": _r(hand_frames / float(len(seen))),
                  "list": [{"first": a + first, "last": b + first, "seconds": _r((b - a + 1) / FPS, 3), "hand": side,
                            "metres": _r(metres, 3), "settle": settle + first} for a, b, side, metres, settle in runs]},
        "eye": {"bone": EYES, "center": center, "head": parent, "forward": _vec(forward, 6), "forward_from": forward_from},
        "convention": {"key_rotation_signs": list(fk.KEY_ROTATION_SIGNS)},
        "counts": counts, "shares": {state: counts[state] / float(len(looks)) for state in STATES},
        "saccades": {"count": len(saccades), "per_second": _r(len(saccades) / (len(seen) / FPS), 3),
                     "by_reason": _count(s["reason"] for s in saccades),
                     "by_frames": {str(k): v for k, v in sorted(_count(s["frames"] for s in saccades).items())},
                     "amplitude": {"median": _r(_median(amplitudes), 3) if amplitudes else 0.0,
                                   "max": _r(max(amplitudes), 3) if amplitudes else 0.0},
                     "list": [{"frame": s["frame"], "frames": s["frames"], "reason": s["reason"],
                               "amplitude": _r(s["amplitude"], 3)} for s in saccades]},
        "contacts": {"count": len(contacts), "frames": contact_frames, "share": _r(contact_frames / float(len(seen))),
                     "list": [{"first": a + first, "last": b + first, "seconds": _r((b - a + 1) / FPS, 3),
                               "anchor": anchor_of(a, b)} for a, b in contacts]},
        "anchors": [m + first for m in marks],
        "leads": {"fast_turns": len(fast_turns(seen, forward)[1]), "planned": len(leads),
                  "made": sum(1 for s in saccades if s["reason"] == "lead")},
        "cuts": cuts,
        "error_on_camera": _error_summary([look.error for look in looks if look.state == "contact"]),
        "measures": plan_measures(seen, looks, saccades, forward, limits, contacts),
        "dance_eye_keys": dance_eye_keys(dance),
    }
    return Gaze(looks, saccades, cuts, eye_motion(looks, dance.model_name), report, seen, forward, contacts, hands,
                runs, aims)


def debug_rows(result, frames):
    """the --debug rows for the frames asked for (those inside the dance)"""
    first = result.sights[0].frame
    rows = []
    for frame in sorted(set(frames)):
        i = frame - first
        if not 0 <= i < len(result.looks):
            continue
        sight, look = result.sights[i], result.looks[i]
        stored = fk.stored(eye_rotation(look.yaw, look.pitch))
        rows.append({"frame": frame, "camera": _vec(sight.camera), "eye_center": _vec(sight.eye),
                     "head_forward": _vec(fk.rotate(sight.head, result.forward)),
                     "to_camera": {"yaw": _r(look.target[0], 3), "pitch": _r(look.target[1], 3)},
                     "eye": {"yaw": _r(look.yaw, 3), "pitch": _r(look.pitch, 3)},
                     "window": _vec(mathutil.quat_to_ui(stored), 3), "state": look.state, "error": _r(look.error, 3)})
    return rows


# ---- the command ----------------------------------------------------------------------------

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


def write_json(path, data, indent=1):
    write_bytes(path, (json.dumps(data, ensure_ascii=True, indent=indent) + "\n").encode("ascii"))


def check_distinct(*paths):
    """the inputs and the files written must all differ: no input is ever written over"""
    seen = {}
    for path in paths:
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            raise ValueError("%s and %s are the same file: DANCE, CAMERA, MODEL, OUT, --report, --debug, --probe and "
                             "--cues must all differ" % (seen[key], path))
        seen[key] = path


def load_model(path):
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def load_cues(path):
    """the cues JSON (a dict with "cues"); ValueError when it is not one"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("cues"), list):
        raise ValueError("%s holds no \"cues\" list" % path)
    return data


def resolve_limits(max_yaw=None, max_up=None, max_down=None, max_pitch=None):
    """the limits from the options: --max-pitch sets up and down together and goes with neither of them"""
    if max_pitch is not None:
        if max_up is not None or max_down is not None:
            raise ValueError("--max-pitch sets both --max-up and --max-down: give it or them, not both")
        max_up = max_down = max_pitch
    limits = Limits(MAX_YAW if max_yaw is None else float(max_yaw), MAX_UP if max_up is None else float(max_up),
                    MAX_DOWN if max_down is None else float(max_down))
    check_limits(limits)
    return limits


def run(dance_path, camera_path, model_path, out_path, report_path=None, debug_path=None, debug_frames=None,
        probe_path=None, limits=Limits(), seed=0, cues_path=None, chorus=(), min_fixation=MIN_FIXATION):
    """read, plan, write; the summary is what main prints"""
    started = time.time()
    check_limits(limits)
    check_distinct(dance_path, camera_path, model_path, out_path, report_path, debug_path, probe_path, cues_path)
    dance_full, camera_full, model_full, out_full = (os.path.abspath(p) for p in (dance_path, camera_path, model_path, out_path))
    cues = load_cues(os.path.abspath(cues_path)) if cues_path else None
    dance = vmd.load(dance_full)
    camera = vmd.load(camera_full)
    model = load_model(model_full)
    result = gaze(model, dance, camera, limits.yaw, limits.up, limits.down, seed, anchors=song_anchors(cues, chorus),
                  min_fixation=min_fixation)
    report = result.report
    rows = None
    if debug_path:
        last = report["frames"][1]
        rows = debug_rows(result, debug_frames if debug_frames else range(report["frames"][0], last + 1, DEBUG_STEP))
    write_bytes(out_full, vmd.dumps(result.motion))
    back = vmd.load(out_full)
    summary = {"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full, "frames": report["frames"],
               "keys": len(back.bones), "seed": seed, "min_fixation": min_fixation, "limits": report["limits"],
               "zones": report["zones"],
               "eye": report["eye"], "convention": report["convention"], "cuts": len(report["cuts"]),
               "anchors": len(report["anchors"]), "counts": report["counts"],
               "shares": {k: _r(v) for k, v in report["shares"].items()},
               "saccades": {k: report["saccades"][k] for k in ("count", "per_second", "by_reason", "by_frames", "amplitude")},
               "contacts": {k: report["contacts"][k] for k in ("count", "frames", "share")},
               "leads": report["leads"], "measures": report["measures"], "error_on_camera": report["error_on_camera"]}
    if cues_path:
        summary["cues"] = os.path.abspath(cues_path)
    if report_path:
        full = os.path.abspath(report_path)
        extra = {"in": dance_full, "camera": camera_full, "model": model_full, "out": out_full, "keys": len(back.bones),
                 "cues": os.path.abspath(cues_path) if cues_path else None, "chorus": [float(c) for c in chorus]}
        write_json(full, dict(extra, **report))
        summary["report"] = full
    if debug_path:
        full = os.path.abspath(debug_path)
        write_json(full, {"in": dance_full, "camera": camera_full, "forward": report["eye"]["forward"], "frames": rows})
        summary["debug"] = full
    if probe_path:
        full = os.path.abspath(probe_path)
        write_bytes(full, vmd.dumps(probe_motion(dance.model_name)))
        summary["probe"] = {"out": full, "segments": probe_segments(result.forward)}
    summary["seconds"] = _r(time.time() - started, 2)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("dance", help="the dance motion (.vmd)")
    p.add_argument("camera", help="the camera motion (.vmd)")
    p.add_argument("model", help="the model (.pmx or .pmd) with the bones 両目, 右目, 左目")
    p.add_argument("out", help="the 両目 motion to write (.vmd), to load after the dance")
    p.add_argument("--report", help="write the plan, the saccades, the contacts and the measures to this JSON")
    p.add_argument("--debug", help="write the geometry of some frames to this JSON")
    p.add_argument("--debug-frames", type=int, nargs="+", help="the frames for --debug (default every %d)" % DEBUG_STEP)
    p.add_argument("--probe", help="also write the convention probe (a short 両目 motion) to this .vmd")
    p.add_argument("--max-yaw", type=float, help="degrees the eyes turn sideways (default %g)" % MAX_YAW)
    p.add_argument("--max-up", type=float, help="degrees the eyes turn up (default %g)" % MAX_UP)
    p.add_argument("--max-down", type=float, help="degrees the eyes turn down (default %g)" % MAX_DOWN)
    p.add_argument("--max-pitch", type=float, help="sets --max-up and --max-down to one value (not with either of them)")
    p.add_argument("--seed", type=int, default=0, help="the drift, the microsaccades, the glances, the leads (default 0)")
    p.add_argument("--cues", help="the MV's cues JSON: the ends of the lyric lines and the hooks are anchors for contacts")
    p.add_argument("--chorus", type=float, nargs="+", default=[], help="the heads of the choruses in seconds (anchors)")
    p.add_argument("--min-fixation", type=int, default=MIN_FIXATION,
                   help="frames a fixation lasts at least before a recentre or a glance (default %d; each fixation "
                        "adds 0 to %d frames drawn from the seed)" % (MIN_FIXATION, FIXATION_SPREAD))
    args = p.parse_args(argv)
    try:
        limits = resolve_limits(args.max_yaw, args.max_up, args.max_down, args.max_pitch)
        result = run(args.dance, args.camera, args.model, args.out, args.report, args.debug, args.debug_frames,
                     args.probe, limits, args.seed, args.cues, args.chorus, args.min_fixation)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
