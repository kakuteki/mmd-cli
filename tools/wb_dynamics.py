"""Whole-body balance measures: the body's centre of mass (COM) from its segments' masses, the base of support from the feet
on the floor, the zero moment point (ZMP: where the floor's push has to act for the motion; on a flat floor it is the
centre of pressure, CoP, and the floor can only push inside the base of support) and the whole-body angular momentum about
the COM.  MMD's physics does not move the body: a dance can ask the floor for a push it cannot give (a lean that would tip
over, a swing that would need the floor to pull) and nothing in the picture falls.

    python tools/wb_dynamics.py measure DANCE.vmd MODEL.pmx --report r.json [--arrays a.npz] [--cutoff 6]
                                [--contact 0.05] [--range FIRST LAST]
    python tools/wb_dynamics.py measure-pack PACK_DIR MODEL.pmx --report r.json [...]

How:
1. Segments: de Leva 1996 Table 4, females (the 16 segments of tools/balance_layer.py, 99.99 % of the body): head (vertex to
   cervicale), the trunk in three parts (cervicale - xiphion - omphalion - mid-hip), upper arm, forearm, hand, thigh,
   shank, foot.  Each one's COM on the line between its two landmarks, its mass a share of the body, its inertia about its
   COM from the table's radii of gyration (the sagittal and transverse ones averaged: a body of revolution about its long
   axis).  The landmarks of Sour's Rin are her bones (the dance's FK; the legs solved as two bones to the foot IK, the knee
   as tools/balance_layer.py bends it), from a VMD or from an analysis pack's 26 bones; a person's come from the joints of
   the skeleton (the human baseline's FineDance data, on hinata).
2. Dynamics: the segments' COMs low-passed (Butterworth, 2nd order run forwards and backwards: zero phase, -6 dB at
   `cutoff_hz`; the same for every body measured), central differences.  Per kilogram the floor's push is
   F = sum m_i (a_i + g up), its moment about the origin M = sum m_i r_i x (a_i + g up) + sum dH_i/dt (H_i = I_i w_i the
   segment's own angular momentum, w_i from its bone's turn, or from its long axis' turn for the legs); on the floor plane
   y = h the ZMP is where the moment's horizontal part vanishes: x = (M_z + h F_x) / F_y, z = (h F_z - M_x) / F_y, wherever
   the floor holds the body up (F_y over ZMP_MIN_G g).  The angular momentum about the COM is
   L = sum m_i (r_i - c) x (v_i - v_c) + sum H_i.  zmp_lin, the ZMP of the COM alone (c - (c_y - h) c'' / (g + c_y'')),
   splits what the body's turning (the hip strategy, the arms) adds.
3. Support: a foot is on the floor where its lowest point (the ankle IK over its rest height, or the toe IK over its) is
   under `contact` units: flat (both), on the forefoot (the toe only) or on the heel (the ankle only).  The part of the sole
   that touches comes from the body's own sole: Rin's shoe as the mesh has it (RIN_FEET: the convex hulls of the vertices
   under 2.4 cm, the forefoot about the toe IK, the heel about the ankle IK, measured on White.pmx), a person's from the
   foot's length (HUMAN_FEET).  The base of support is the convex hull of the parts on the floor.
4. Measures (measure()): the ZMP's signed distance to the base of support (+ inside), its share inside, the stretches
   outside (when, how deep, the tilt the body would have taken from the unsupported moment), the COM's floor point against
   the base of support, the angular momentum per kilogram over the stature squared (1/s), and in the air (no foot on the
   floor) the COM's horizontal acceleration and the change of the angular momentum, both 0 for a body nothing pushes.
"""
import argparse
import importlib.util
import io
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

FPS = 30.0
UNIT_M = 0.08                   # metres a model unit (the analysis pack)
G = 9.81
SIDES = ("L", "R")
JP = {"L": "左", "R": "右"}

# de Leva P (1996) J Biomech 29:1223-1230, Table 4, females (read in the original: _spike/out/stage2/motor/work/
# deleva1996_table4_text.txt): mass %, COM % of the way from the first end, radii of gyration % of the length (sagittal,
# transverse, longitudinal).  The hand: the table's wrist -> 3rd dactylion (34.27 %), on the wrist -> middle finger's distal
# joint (中指３), which is HAND_TIP_SHARE of that length
HAND_TIP_SHARE = 0.88           # Rin: 手首 -> 中指３ 12.0 cm of about 13.6 to the tip; SMPL-X: 16.4 cm of about 18.7
_ROWS = [("head", ("vertex", "cerv"), 6.68, 48.41, (27.1, 29.5, 26.1), "head"),
         ("upper_trunk", ("cerv", "xyph"), 15.45, 50.50, (46.6, 31.4, 44.9), "upt"),
         ("middle_trunk", ("xyph", "omph"), 14.65, 45.12, (43.3, 35.4, 41.5), "mpt"),
         ("lower_trunk", ("omph", "midh"), 12.47, 49.20, (43.3, 40.2, 44.4), "lpt")]
for _s in SIDES:
    _ROWS += [("upper_arm_" + _s, ("shoulder_" + _s, "elbow_" + _s), 2.55, 57.54, (27.8, 26.0, 14.8), "upper_arm_" + _s),
              ("forearm_" + _s, ("elbow_" + _s, "wrist_" + _s), 1.38, 45.59, (26.1, 25.7, 9.4), "forearm_" + _s),
              ("hand_" + _s, ("wrist_" + _s, "mid3_" + _s), 0.56, 34.27 / HAND_TIP_SHARE,
               tuple(v / HAND_TIP_SHARE for v in (24.4, 20.8, 15.4)), "hand_" + _s),
              ("thigh_" + _s, ("hip_" + _s, "knee_" + _s), 14.78, 36.12, (36.9, 36.4, 16.2), None),
              ("shank_" + _s, ("knee_" + _s, "ankle_" + _s), 4.81, 43.52, (26.7, 26.3, 9.2), None),
              ("foot_" + _s, ("heel_" + _s, "toe_" + _s), 1.29, 40.14, (29.9, 27.9, 13.9), None)]
SEGMENTS = {name: {"ends": ends, "mass": mass, "com": com, "r": r, "rot": rot} for name, ends, mass, com, r, rot in _ROWS}
ROTATED = [v["rot"] for v in SEGMENTS.values() if v["rot"]]
HEEL_BACK = 0.3                 # the foot segment's heel this share of the ankle -> toe line behind the ankle (a05)

ZMP_MIN_G = 0.2                 # the ZMP is read where the floor pushes up at least this share of g
CUTOFF_HZ = 6.0                 # the low-pass on the segments' COMs (Winter 2009's 6 Hz for markers before differentiating)
RUN_DEPTH_M = 0.005             # a stretch outside the base of support: the ZMP 5 mm and more outside ...
EDGE_FRAMES = 3                 # (frames at each end left out of the statistics: the filter's and the differences' ends)
KNEE_FLOOR_M = 0.08             # a knee joint this near the floor kneels on it (the joint's centre over the kneecap's skin)
HAND_FLOOR_M = 0.04             # a hand's wrist or middle finger joint this near the floor is put down on it
OTHER_R_M = 0.03                # the disc of floor under a knee or a hand
AIR_MIN_FRAMES = 5              # an air stretch this long and longer is measured (its parabola and its angular momentum's line)

# Rin's sole (White.pmx, the vertices under y 0.3 units = 2.4 cm, the left foot; the right is its mirror): the convex hulls
# in the foot's frame, metres (u along the rest ankle IK -> toe IK on the floor, w outwards).  The forefoot about the toe
# IK (which stands 0.1217 m ahead of the ankle IK), the heel about the ankle IK.  The shoe is 16.7 cm long, 6.8 cm wide at
# the forefoot and 3.7 cm at the heel (a raised heel: the arch does not touch).
_RIN_FORE = [(0.0472, 0.0300), (0.0504, -0.0333), (0.0662, -0.0350), (0.0679, -0.0349), (0.0840, -0.0337),
             (0.0995, -0.0298), (0.1122, -0.0237), (0.1208, -0.0157), (0.1234, -0.0062), (0.1200, 0.0041),
             (0.1105, 0.0152), (0.0972, 0.0248), (0.0811, 0.0312), (0.0647, 0.0333)]
_RIN_HEEL = [(-0.0438, -0.0078), (-0.0415, -0.0158), (-0.0357, -0.0208), (-0.0275, -0.0233), (-0.0181, -0.0232),
             (-0.0081, -0.0221), (-0.0099, 0.0134), (-0.0199, 0.0125), (-0.0293, 0.0112), (-0.0372, 0.0070),
             (-0.0423, 0.0007)]
RIN_TOE_U = 0.1217
RIN_FEET = {"fore": np.array([(u - RIN_TOE_U, w) for u, w in _RIN_FORE]), "heel": np.array(_RIN_HEEL),
            "ankle_rest_y": 1.7452, "toe_rest_y": 0.1, "floor_y": 0.111, "contact": 0.05, "foot_length_m": 0.1672,
            "stature_m": (18.7663 - 0.111) * UNIT_M, "name": "Rin (White.pmx)"}


def human_feet(ankle_to_ball_m, ankle_rest_y, toe_rest_y, floor_y, stature_m, contact=0.15, tip_floor_y=None):
    """a person's sole from the ankle -> ball (first metatarsal head row) length on the floor: the heel 0.24 of the foot
    behind the ankle, the ball at 0.73 of it, the tip at 1.0 (foot length = ankle_to_ball / 0.49); the forefoot 0.38 of
    the foot wide, the heel 0.25 (foot breadth / length 0.38-0.40 in young women; the heel breadth about 2/3 of it).  The
    toe landmark of a person is the ball (SMPL's foot joint); contact 0.15 units (1.2 cm, the human baseline's).  The rest
    heights may be per foot ({'L', 'R'}).  tip_floor_y: the toes' tip landmarks' planted height (a pointed foot touches
    with the tip alone: a disc of 1.5 cm there)"""
    Lf = ankle_to_ball_m / 0.49
    fore_w, heel_w = 0.38 * Lf / 2.0, 0.25 * Lf / 2.0
    tip = 0.27 * Lf
    back = -0.24 * Lf
    ang = np.linspace(0.0, math.pi, 7)
    fore = [(-0.10 * Lf, -fore_w), (-0.10 * Lf, fore_w)] + [(tip - 0.12 * Lf * (1 - math.sin(a)), fore_w * math.cos(a)) for a in ang]
    heel = [(0.05 * Lf, -heel_w), (0.05 * Lf, heel_w)] + [(back + heel_w * (1 - math.sin(a)), heel_w * math.cos(a)) for a in ang]
    out = {"fore": np.array(fore), "heel": np.array(heel), "ankle_rest_y": ankle_rest_y, "toe_rest_y": toe_rest_y,
           "floor_y": floor_y, "contact": contact, "foot_length_m": Lf, "stature_m": stature_m, "name": "person"}
    if tip_floor_y is not None:
        out["tip"] = np.array([(0.015 * math.cos(a), 0.015 * math.sin(a)) for a in np.linspace(0.0, 2.0 * math.pi, 13)[:-1]])
        out["tip_floor_y"] = tip_floor_y
    return out


# ---- quaternions (x, y, z, w; v' = q v q^-1) -----------------------------------------------------------------------

def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    out = np.array(q, dtype=np.float64, copy=True)
    out[..., :3] *= -1.0
    return out


def qrot(q, v):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], axis=-1)


def angular_velocity(q, fs=FPS):
    """world angular velocity [F, 3] (rad/s) of a world rotation track q [F, 4]: the turn from each frame to the next
    (q(t+1) = dq q(t), its rotation vector times fs, the short way, so the quaternions' sign does not matter), averaged
    onto the frames"""
    q = np.asarray(q, dtype=np.float64)
    F = len(q)
    out = np.zeros((F, 3))
    if F < 2:
        return out
    dq = qmul(q[1:], qconj(q[:-1]))
    dq = np.where(dq[:, 3:4] < 0.0, -dq, dq)
    s = np.linalg.norm(dq[:, :3], axis=1)
    ang = 2.0 * np.arctan2(s, np.clip(dq[:, 3], -1.0, 1.0))
    mid = np.where(s[:, None] > 1e-15, dq[:, :3] / np.maximum(s, 1e-300)[:, None] * ang[:, None], 2.0 * dq[:, :3]) * fs
    out[1:-1] = 0.5 * (mid[1:] + mid[:-1])
    out[0], out[-1] = mid[0], mid[-1]
    return out


# ---- the filter and the differences --------------------------------------------------------------------------------

def lowpass(x, cutoff_hz, fs=FPS):
    """zero-phase low-pass along axis 0: a 2nd order Butterworth (bilinear, prewarped) run forwards and backwards
    (-6 dB at cutoff_hz), each end padded by its odd reflection and the filter started at rest on it (a line and a
    constant come back as they are).  cutoff_hz None: x itself"""
    x = np.asarray(x, dtype=np.float64)
    F = len(x)
    if cutoff_hz is None or F < 4:
        return x.copy()
    K = math.tan(math.pi * float(cutoff_hz) / fs)
    norm = 1.0 / (1.0 + math.sqrt(2.0) * K + K * K)
    b0 = K * K * norm
    b1, b2 = 2.0 * b0, b0
    a1 = 2.0 * (K * K - 1.0) * norm
    a2 = (1.0 - math.sqrt(2.0) * K + K * K) * norm
    P = int(min(F - 1, max(6, round(6.0 * fs / float(cutoff_hz)))))
    pad = np.concatenate([2.0 * x[0] - x[P:0:-1], x, 2.0 * x[-1] - x[-2:-P - 2:-1]], axis=0)

    def run(s):
        y = np.empty_like(s)
        x1 = x2 = s[0]
        y1 = y2 = s[0]
        for n in range(len(s)):
            xn = s[n]
            yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, xn
            y2, y1 = y1, yn
            y[n] = yn
        return y
    y = run(pad)
    y = run(y[::-1])[::-1]
    return y[P:P + F]


def diff1(x, fs=FPS):
    v = np.zeros_like(x)
    if len(x) >= 3:
        v[1:-1] = (x[2:] - x[:-2]) * (fs / 2.0)
        v[0], v[-1] = v[1], v[-2]
    return v


def diff2(x, fs=FPS):
    a = np.zeros_like(x)
    if len(x) >= 3:
        a[1:-1] = (x[2:] - 2.0 * x[1:-1] + x[:-2]) * fs * fs
        a[0], a[-1] = a[1], a[-2]
    return a


# ---- the body ------------------------------------------------------------------------------------------------------

def segments(lm):
    """name -> {"mass" (%), "com" [F, 3], "axis" [F, 3] (unit, first end -> second), "length" [F], "r", "rot"} from the
    landmarks lm (name -> [F, 3], any unit; "midh" and the heels made here when missing)"""
    lm = dict(lm)
    if "midh" not in lm:
        lm["midh"] = 0.5 * (lm["hip_L"] + lm["hip_R"])
    for s in SIDES:
        if "heel_" + s not in lm:
            lm["heel_" + s] = lm["ankle_" + s] - HEEL_BACK * (lm["toe_" + s] - lm["ankle_" + s])
    out = {}
    for name, row in SEGMENTS.items():
        a, b = (np.asarray(lm[e], dtype=np.float64) for e in row["ends"])
        d = b - a
        n = np.linalg.norm(d, axis=1)
        out[name] = {"mass": row["mass"], "com": a + (row["com"] / 100.0) * d,
                     "axis": d / np.maximum(n, 1e-12)[:, None], "length": n, "r": row["r"], "rot": row["rot"]}
    return out


def com(segs):
    """the centre of mass [F, 3] (the landmarks' unit)"""
    total = sum(s["mass"] for s in segs.values())
    return sum(s["mass"] * s["com"] for s in segs.values()) / total


def two_bone_knee(H, A, T, R_lower, L1, L2):
    """the knee of a leg solved as two bones (thigh L1, shank L2) from the hip H to the foot IK's target A [F, 3], as
    tools/balance_layer.py's Body bends it: a hinge about 下半身's side axis (R_lower [F, 4] its world turn), turned out
    towards the foot's front (A -> the toe IK T) as far as the foot lies flat and points the pelvis's way, a little of the
    pelvis's front keeping it defined for a leg straight out to the side; a target out of reach: a straight leg at it.
    Returns (knee, the ankle the leg reaches) [F, 3] each"""
    F = len(H)
    d = A - H
    dist = np.linalg.norm(d, axis=1)
    u = d / np.maximum(dist, 1e-9)[:, None]
    dd = np.minimum(dist, L1 + L2 - 1e-9)
    a = (L1 ** 2 - L2 ** 2 + dd ** 2) / (2.0 * dd)
    h = np.sqrt(np.maximum(L1 ** 2 - a ** 2, 0.0))
    facing = qrot(R_lower, np.broadcast_to(np.array([0.0, 0.0, -1.0]), (F, 3))).copy()
    facing[:, 1] = 0.0
    facing /= np.maximum(np.linalg.norm(facing, axis=1), 1e-9)[:, None]
    side = qrot(R_lower, np.broadcast_to(np.array([1.0, 0.0, 0.0]), (F, 3)))
    hinge = np.cross(side, u)
    foot = T - A
    flat = np.hypot(foot[:, 0], foot[:, 2]) / np.maximum(np.linalg.norm(foot, axis=1), 1e-9)
    foot = foot.copy()
    foot[:, 1] = 0.0
    foot /= np.maximum(np.linalg.norm(foot, axis=1), 1e-9)[:, None]
    agree = np.maximum(np.sum(foot * facing, axis=1), 0.0)
    fwd = hinge + (flat * agree)[:, None] * foot + 0.1 * facing
    n = fwd - np.sum(fwd * u, axis=1)[:, None] * u
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
    return H + a[:, None] * u + h[:, None] * n, H + u * np.minimum(dist, L1 + L2)[:, None]


# the analysis pack's 26 bones (uncanny/pack, the human baseline's hbpack)
PACK_BONES = ["全ての親", "センター", "グルーブ", "腰", "下半身", "上半身", "上半身2", "首", "頭", "両目", "左目", "右目", "左肩",
              "右肩", "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首", "左中指３", "右中指３", "左足ＩＫ", "右足ＩＫ",
              "左つま先ＩＫ", "右つま先ＩＫ"]
HEAD_TIP_FALLBACK = 0.155       # without 頭先: the vertex this share of 頭's height above 頭 (tools/motor_layer.py)


def rin_rest(model):
    """the rest positions (units) the landmarks need from a model: 下半身, the hips, knees and ankles (the legs' lengths),
    頭 and the vertex (頭先, or HEAD_TIP_FALLBACK above 頭), the foot and toe IKs"""
    pos = {b.name: np.array(b.position, dtype=np.float64) for b in model.bones if b.position is not None}
    out = {k: pos[k] for k in ["下半身", "頭"] + [JP[s] + n for s in SIDES for n in ("足", "ひざ", "足首", "足ＩＫ", "つま先ＩＫ")]}
    out["頭先"] = pos["頭先"] if "頭先" in pos else pos["頭"] + np.array([0.0, pos["頭"][1] * HEAD_TIP_FALLBACK, 0.0])
    return out


def _legs(rest, s):
    hip, knee, ankle = rest[JP[s] + "足"], rest[JP[s] + "ひざ"], rest[JP[s] + "足首"]
    return float(np.linalg.norm(knee - hip)), float(np.linalg.norm(ankle - knee))


def landmarks_from_pack(names, pos, rot, rest):
    """(landmarks, rotations) from an analysis pack's bones (names, pos [F, n, 3], rot [F, n, 4]) and the model's rest
    (rin_rest): the hips from 下半身 and their rest offsets (the dance has no 腰 keys, so 腰キャンセル cancels nothing),
    the knees solved as two bones (two_bone_knee), the vertex carried by 頭"""
    ix = {n: i for i, n in enumerate(names)}
    P = lambda n: np.asarray(pos[:, ix[n]], dtype=np.float64)          # noqa: E731
    R = lambda n: np.asarray(rot[:, ix[n]], dtype=np.float64)          # noqa: E731
    F = pos.shape[0]
    lower = R("下半身")
    lm = {"cerv": P("首"), "xyph": P("上半身2"), "omph": P("上半身"),
          "vertex": P("頭") + qrot(R("頭"), np.broadcast_to(rest["頭先"] - rest["頭"], (F, 3)))}
    for s in SIDES:
        j = JP[s]
        hip = P("下半身") + qrot(lower, np.broadcast_to(rest[j + "足"] - rest["下半身"], (F, 3)))
        A, T = P(j + "足ＩＫ"), P(j + "つま先ＩＫ")
        L1, L2 = _legs(rest, s)
        knee, _ = two_bone_knee(hip, A, T, lower, L1, L2)
        lm.update({"hip_" + s: hip, "knee_" + s: knee, "ankle_" + s: A, "toe_" + s: T, "shoulder_" + s: P(j + "腕"),
                   "elbow_" + s: P(j + "ひじ"), "wrist_" + s: P(j + "手首"), "mid3_" + s: P(j + "中指３")})
    rots = {"head": R("頭"), "upt": R("上半身2"), "mpt": R("上半身"), "lpt": lower}
    for s in SIDES:
        j = JP[s]
        rots.update({"upper_arm_" + s: R(j + "腕"), "forearm_" + s: R(j + "ひじ"), "hand_" + s: R(j + "手首")})
    return lm, rots


def landmarks_from_body(body):
    """(landmarks, rotations) from tools/balance_layer.py's Body (the FK of a VMD on the model): the same points as
    landmarks_from_pack, the knees as the body solves them"""
    lm = {"cerv": body.p("首"), "xyph": body.p("上半身2"), "omph": body.p("上半身"), "vertex": body._vertex()}
    for s in SIDES:
        j = JP[s]
        lm.update({"hip_" + s: body.hip(j), "knee_" + s: body.knee(j), "ankle_" + s: body.ankle(j), "toe_" + s: body.toe(j),
                   "shoulder_" + s: body.p(j + "腕"), "elbow_" + s: body.p(j + "ひじ"), "wrist_" + s: body.p(j + "手首"),
                   "mid3_" + s: body.p(j + "中指３")})
    rots = {"head": body.q("頭"), "upt": body.q("上半身2"), "mpt": body.q("上半身"), "lpt": body.q("下半身")}
    for s in SIDES:
        j = JP[s]
        rots.update({"upper_arm_" + s: body.q(j + "腕"), "forearm_" + s: body.q(j + "ひじ"), "hand_" + s: body.q(j + "手首")})
    return lm, rots


# ---- the dynamics --------------------------------------------------------------------------------------------------

def dynamics(lm, rots=None, floor_y=0.0, cutoff_hz=CUTOFF_HZ, spin=True, unit_m=UNIT_M, fs=FPS):
    """per frame (metres, seconds, per kilogram of the body): the COM, its velocity and acceleration, the floor's push
    `force` [F, 3] and its moment about the origin `moment`, the ZMP [F, 2] (x, z) on the plane y = floor_y (units) and
    `zmp_ok` (the floor pushes up at least ZMP_MIN_G g; not on the first and last frame), `zmp_lin` (the ZMP of the COM
    alone), the angular momentum about the COM `angmom` [F, 3] (m^2/s) and its spin part `spin` (the segments' own turns).
    rots: name -> world rotation [F, 4] of the bone carrying a segment (ROTATED); a segment without one turns with its
    long axis (no twist).  spin False: point masses only"""
    segs = segments(lm)
    names = list(segs)
    F = len(segs[names[0]]["com"])
    total = sum(s["mass"] for s in segs.values())
    up = np.array([0.0, G, 0.0])
    # one low-pass over every signal at once (the filter is a loop over the frames)
    cols = [segs[n]["com"] * unit_m for n in names]
    if spin:
        cols += [segs[n]["axis"] for n in names] + [segs[n]["length"][:, None] * unit_m for n in names]
    filt = lowpass(np.concatenate(cols, 1), cutoff_hz, fs)
    k = len(names)
    R = [filt[:, 3 * i:3 * i + 3] for i in range(k)]
    turned = [n for n in names if spin and rots is not None and segs[n]["rot"] in rots]
    W = {}
    if turned:
        wf = lowpass(np.concatenate([angular_velocity(rots[segs[n]["rot"]], fs) for n in turned], 1), cutoff_hz, fs)
        W = {n: wf[:, 3 * i:3 * i + 3] for i, n in enumerate(turned)}
    r_all, v_all, a_all, m_all, H_all = [], [], [], [], []
    for i, name in enumerate(names):
        s = segs[name]
        m = s["mass"] / total
        r = R[i]
        v, a = diff1(r, fs), diff2(r, fs)
        H = np.zeros((F, 3))
        if spin:
            e = filt[:, 3 * k + 3 * i:3 * k + 3 * i + 3].copy()
            e /= np.maximum(np.linalg.norm(e, axis=1), 1e-12)[:, None]
            L = filt[:, 6 * k + i]
            w = W[name] if name in W else np.cross(e, diff1(e, fs))
            rt = 0.5 * (s["r"][0] + s["r"][1]) / 100.0
            rl = s["r"][2] / 100.0
            we = np.sum(w * e, axis=1)[:, None]
            H = m * (L * L)[:, None] * (rt * rt * (w - we * e) + rl * rl * we * e)
        r_all.append(r)
        v_all.append(v)
        a_all.append(a)
        m_all.append(m)
        H_all.append(H)
    msum = sum(m_all)
    c = sum(m * r for m, r in zip(m_all, r_all)) / msum
    vc = sum(m * v for m, v in zip(m_all, v_all)) / msum
    ac = sum(m * a for m, a in zip(m_all, a_all)) / msum
    force = (ac + up) * 1.0
    Hsum = sum(H_all)
    moment = sum(m * np.cross(r, a + up) for m, r, a in zip(m_all, r_all, a_all)) / msum + diff1(Hsum, fs) / msum
    h = floor_y * unit_m
    fy = force[:, 1]
    ok = fy > ZMP_MIN_G * G
    ok[0] = ok[-1] = False
    fsafe = np.where(ok, fy, 1.0)
    zmp = np.stack([(moment[:, 2] + h * force[:, 0]) / fsafe, (h * force[:, 2] - moment[:, 0]) / fsafe], 1)
    zmp[~ok] = np.nan
    gy = np.where(ok, G + ac[:, 1], 1.0)
    zmp_lin = c[:, [0, 2]] - (c[:, 1] - h)[:, None] * ac[:, [0, 2]] / gy[:, None]
    zmp_lin[~ok] = np.nan
    L = sum(m * np.cross(r - c, v - vc) for m, r, v in zip(m_all, r_all, v_all)) / msum + Hsum / msum
    return {"com": c, "com_vel": vc, "com_acc": ac, "force": force, "moment": moment, "zmp": zmp, "zmp_ok": ok,
            "zmp_lin": zmp_lin, "angmom": L, "spin": Hsum / msum, "segments": segs}


# ---- the support ---------------------------------------------------------------------------------------------------

def _hull(pts):
    """the convex hull [k, 2] (counter-clockwise in (x, z)) of points [n, 2] (Andrew's monotone chain)"""
    pts = np.unique(np.round(np.asarray(pts, dtype=np.float64), 9), axis=0)
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in pts[::-1]:
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(float(np.dot(ab, ab)), 1e-18), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + t * ab)))


def polygon_margin(p, poly):
    """the signed distance (+ inside) of the point p [2] to the convex polygon poly [k, 2] (either turning)"""
    poly = np.asarray(poly, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    if len(poly) == 0:
        return float("nan")
    if len(poly) == 1:
        return -float(np.linalg.norm(p - poly[0]))
    if len(poly) == 2:
        return -_seg_dist(p, poly[0], poly[1])
    k = len(poly)
    d = min(_seg_dist(p, poly[i], poly[(i + 1) % k]) for i in range(k))
    cr = [(poly[(i + 1) % k][0] - poly[i][0]) * (p[1] - poly[i][1]) - (poly[(i + 1) % k][1] - poly[i][1]) * (p[0] - poly[i][0])
          for i in range(k)]
    inside = all(c >= 0 for c in cr) or all(c <= 0 for c in cr)
    return d if inside else -d


def _foot_axes(lm, s):
    """the foot's forward f and outward o on the floor [F, 2] (x, z) from its ankle -> toe line (the hips' facing where
    the foot points straight down)"""
    A, T = np.asarray(lm["ankle_" + s], dtype=np.float64), np.asarray(lm["toe_" + s], dtype=np.float64)
    f = (T - A)[:, [0, 2]]
    n = np.linalg.norm(f, axis=1)
    lat = (lm["hip_L"] - lm["hip_R"])[:, [0, 2]]
    lat = lat / np.maximum(np.linalg.norm(lat, axis=1), 1e-12)[:, None]
    facing = np.stack([lat[:, 1], -lat[:, 0]], 1)          # the model's left is +x and it faces -z at rest
    f = np.where((n > 1e-6)[:, None], f / np.maximum(n, 1e-12)[:, None], facing)
    o = np.stack([-f[:, 1], f[:, 0]], 1) if s == "L" else np.stack([f[:, 1], -f[:, 0]], 1)
    return f, o


def _rest(feet, key, s):
    """a rest height (units) of foot s: one number for both feet or a dict per foot"""
    v = feet[key]
    return float(v[s]) if isinstance(v, dict) else float(v)


def foot_polygon(lm, feet, s, frame, part, unit_m=UNIT_M):
    """the part ('flat', 'fore', 'heel' or 'tip') of foot s's sole on the floor at `frame`, [k, 2] metres (x, z)"""
    f, o = _foot_axes(lm, s)
    f, o = f[frame], o[frame]
    A = np.asarray(lm["ankle_" + s][frame], dtype=np.float64)[[0, 2]] * unit_m
    T = np.asarray(lm["toe_" + s][frame], dtype=np.float64)[[0, 2]] * unit_m
    pts = []
    if part in ("flat", "heel"):
        pts += [A + u * f + w * o for u, w in feet["heel"]]
    if part in ("flat", "fore"):
        pts += [T + u * f + w * o for u, w in feet["fore"]]
    if part == "tip" and "tip" in feet and ("tip_" + s) in lm:
        X = np.asarray(lm["tip_" + s][frame], dtype=np.float64)[[0, 2]] * unit_m
        pts += [X + u * f + w * o for u, w in feet["tip"]]
    return _hull(np.array(pts)) if pts else np.zeros((0, 2))


def support(lm, feet, unit_m=UNIT_M):
    """per foot: `contact` [F] (its lowest point under feet['contact'] units over its rest heights), `part` [F] ('flat',
    'fore', 'heel', 'tip' or ''), and per frame the base of support `hull` (the convex hull [k, 2] of the parts on the
    floor, metres, x and z; an empty array in the air).  The rest heights may be per foot ({'L': .., 'R': ..}).  With a
    tip template (feet['tip'], feet['tip_floor_y']) and tip landmarks (a person's toes' tip: the toe landmark is the
    ball), a foot whose ball and heel are up touches with the tip alone ('tip')"""
    F = len(lm["ankle_L"])
    eps = feet["contact"]
    contact, part = {}, {}
    pts = {}
    use_tip = "tip" in feet and all(("tip_" + s) in lm for s in SIDES)
    for s in SIDES:
        A, T = np.asarray(lm["ankle_" + s], dtype=np.float64), np.asarray(lm["toe_" + s], dtype=np.float64)
        heel_dn = A[:, 1] - _rest(feet, "ankle_rest_y", s) < eps
        fore_dn = T[:, 1] - _rest(feet, "toe_rest_y", s) < eps
        f, o = _foot_axes(lm, s)
        hu, hw = feet["heel"][:, 0], feet["heel"][:, 1]
        fu, fw = feet["fore"][:, 0], feet["fore"][:, 1]
        Axz, Txz = A[:, [0, 2]] * unit_m, T[:, [0, 2]] * unit_m
        heel = Axz[:, None, :] + hu[None, :, None] * f[:, None, :] + hw[None, :, None] * o[:, None, :]
        fore = Txz[:, None, :] + fu[None, :, None] * f[:, None, :] + fw[None, :, None] * o[:, None, :]
        tip_dn = np.zeros(F, bool)
        tip = None
        if use_tip:
            X = np.asarray(lm["tip_" + s], dtype=np.float64)
            tip_dn = (X[:, 1] - _rest(feet, "tip_floor_y", s) < eps) & ~heel_dn & ~fore_dn
            tu, tw = feet["tip"][:, 0], feet["tip"][:, 1]
            tip = X[:, None, [0, 2]] * unit_m + tu[None, :, None] * f[:, None, :] + tw[None, :, None] * o[:, None, :]
        contact[s] = heel_dn | fore_dn | tip_dn
        part[s] = np.where(heel_dn & fore_dn, "flat", np.where(fore_dn, "fore", np.where(heel_dn, "heel",
                                                                                         np.where(tip_dn, "tip", ""))))
        pts[s] = (heel, fore, tip, heel_dn, fore_dn, tip_dn)
    # a knee or a hand on the floor (kneeling, a hand put down): a disc of OTHER_R_M under the joint
    fy = float(feet["floor_y"]) * unit_m
    ring = OTHER_R_M * np.stack([np.cos(np.linspace(0.0, 2.0 * math.pi, 9)[:-1]), np.sin(np.linspace(0.0, 2.0 * math.pi, 9)[:-1])], 1)
    others = []
    for s in SIDES:
        for key, limit in (("knee_", KNEE_FLOOR_M), ("mid3_", HAND_FLOOR_M), ("wrist_", HAND_FLOOR_M)):
            if key + s in lm:
                P_ = np.asarray(lm[key + s], dtype=np.float64)
                others.append((P_[:, 1] * unit_m - fy < limit, P_[:, [0, 2]] * unit_m))
    other = np.zeros(F, bool)
    for m_, _ in others:
        other |= m_
    hulls = []
    for t in range(F):
        P = []
        for s in SIDES:
            heel, fore, tip, hd, fd, td = pts[s]
            if hd[t]:
                P.append(heel[t])
            if fd[t]:
                P.append(fore[t])
            if td[t]:
                P.append(tip[t])
        for m_, xz in others:
            if m_[t]:
                P.append(xz[t] + ring)
        hulls.append(_hull(np.concatenate(P, 0)) if P else np.zeros((0, 2)))
    return {"contact": contact, "part": part, "hull": hulls, "other": other}


# ---- the measures --------------------------------------------------------------------------------------------------

def _q(v, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    out = {("p%02d" % int(round(q * 100))): round(float(np.quantile(v, q)), 4) for q in qs}
    out["n"] = int(len(v))
    return out


def runs(mask):
    """[(first, last)] of the runs of True"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    dm = np.diff(m.astype(np.int8))
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(dm == 1), np.flatnonzero(dm == -1) - 1)]


def measure(lm, feet, rots=None, floor_y=None, cutoff_hz=CUTOFF_HZ, rng=None, unit_m=UNIT_M, fs=FPS, arrays=False):
    """the report (plain JSON) of a body's balance: see the module's doc.  rng (first, last): the frames counted (the
    dance's own range); feet: RIN_FEET or human_feet(); arrays: also return the per-frame curves"""
    floor_y = feet["floor_y"] if floor_y is None else floor_y
    dyn = dynamics(lm, rots, floor_y, cutoff_hz, unit_m=unit_m, fs=fs)
    sup = support(lm, feet, unit_m)
    F = len(dyn["com"])
    a, b = (0, F - 1) if rng is None else (max(0, int(rng[0])), min(F - 1, int(rng[1])))
    inrng = np.zeros(F, bool)
    inrng[a + EDGE_FRAMES:b - EDGE_FRAMES + 1] = True
    nfeet = sup["contact"]["L"].astype(int) + sup["contact"]["R"].astype(int)
    on = (nfeet > 0) & inrng
    ok = on & dyn["zmp_ok"]
    margin = np.full(F, np.nan)
    com_margin = np.full(F, np.nan)
    for t in np.flatnonzero(on):
        hull = sup["hull"][t]
        if dyn["zmp_ok"][t]:
            margin[t] = polygon_margin(dyn["zmp"][t], hull)
        com_margin[t] = polygon_margin(dyn["com"][t, [0, 2]], hull)
    single, double = (nfeet == 1) & ok, (nfeet == 2) & ok
    Lf = feet["foot_length_m"]
    H = feet["stature_m"]
    # the stretches outside: deeper than RUN_DEPTH_M; the tilt the body would take from the moment the floor cannot give
    # (the depth times the weight, over the moment of inertia about the support's edge ~ the COM's height squared)
    out_runs = []
    for r0, r1 in runs(ok & (margin < -RUN_DEPTH_M)):
        d = -margin[r0:r1 + 1]
        hcom = dyn["com"][r0:r1 + 1, 1] - floor_y * unit_m
        alpha = G * d / np.maximum(hcom, 0.2) ** 2              # rad/s^2
        omega = np.cumsum(alpha) / fs
        tilt = float(np.sum(omega) / fs)
        foot = "both" if np.all(nfeet[r0:r1 + 1] == 2) else ("L" if np.all(sup["contact"]["L"][r0:r1 + 1] & ~sup["contact"]["R"][r0:r1 + 1])
                                                            else ("R" if np.all(sup["contact"]["R"][r0:r1 + 1] & ~sup["contact"]["L"][r0:r1 + 1]) else "mixed"))
        k = r0 + int(np.argmax(d))
        out_runs.append({"first": r0, "last": r1, "s": [round(r0 / fs, 2), round(r1 / fs, 2)], "frames": r1 - r0 + 1,
                         "depth_cm": round(float(d.max()) * 100.0, 2), "depth_rel": round(float(d.max()) / Lf, 3),
                         "tilt_deg": round(math.degrees(tilt), 2), "support": foot, "deepest_frame": k,
                         "zmp_lin_margin_cm": round(polygon_margin(dyn["zmp_lin"][k], sup["hull"][k]) * 100.0, 2)
                         if np.all(np.isfinite(dyn["zmp_lin"][k])) else None})
    minutes = max((b - a + 1) / fs / 60.0, 1e-9)
    Lnorm = dyn["angmom"] / (H * H)                             # 1/s
    Lh = np.linalg.norm(Lnorm[:, [0, 2]], axis=1)
    Lv = np.abs(Lnorm[:, 1])
    # what the turning of the body adds to the ZMP (against the COM alone)
    rot_part = np.linalg.norm(dyn["zmp"] - dyn["zmp_lin"], axis=1)
    lin_part = np.linalg.norm(dyn["zmp_lin"] - dyn["com"][:, [0, 2]], axis=1)
    # the air: on the frames in the air alone, unfiltered (the low-pass spreads the take-off's and the landing's kinks
    # +-4 frames into the air: a 1 m/s change of speed left 0.7-0.9 m/s^2 3-4 frames in), the COM's path fitted by a
    # parabola (its mean acceleration; a body nothing pushes sideways has none) and the angular momentum (its
    # velocities read inside the air only) by a line (its rate of change; 0 in the air)
    air = (nfeet == 0) & inrng
    raw = dynamics(lm, rots, floor_y, None, unit_m=unit_m, fs=fs)
    Lraw = raw["angmom"] / (H * H)
    air_rows, acc_h, dL = [], [], []
    for r0, r1 in runs(air):
        if r1 - r0 + 1 < AIR_MIN_FRAMES:
            continue
        tt = (np.arange(r0, r1 + 1) - r0) / fs
        cf = np.polyfit(tt, raw["com"][r0:r1 + 1], 2)          # [3, 3]: t^2, t, 1 per axis
        acc = 2.0 * cf[0]
        ah = float(np.hypot(acc[0], acc[2]))
        t2 = tt[1:-1]
        lf = np.polyfit(t2, Lraw[r0 + 1:r1], 1)
        dl = float(np.linalg.norm(lf[0]))
        acc_h.append(ah)
        dL.append(dl)
        air_rows.append({"first": r0, "last": r1, "s": [round(r0 / fs, 2), round(r1 / fs, 2)], "frames": r1 - r0 + 1,
                         "com_acc_h_m_s2": round(ah, 3), "com_acc_v_m_s2": round(float(acc[1]), 3),
                         "angmom_change_per_s2": round(dl, 4)})
    rep = {"params": {"cutoff_hz": cutoff_hz, "floor_y": floor_y, "contact_units": feet["contact"], "feet": feet.get("name"),
                      "foot_length_m": round(Lf, 4), "stature_m": round(H, 4), "range": [a, b], "zmp_min_g": ZMP_MIN_G,
                      "run_depth_m": RUN_DEPTH_M},
           "support": {"frames": int(inrng.sum()), "single": int(np.sum((nfeet == 1) & inrng)),
                       "double": int(np.sum((nfeet == 2) & inrng)), "air": int(air.sum())},
           "com": {"height_m_p50": round(float(np.median(dyn["com"][inrng, 1] - floor_y * unit_m)), 4),
                   "floor_point_inside_share_single": round(float(np.mean(com_margin[(nfeet == 1) & on] > 0)), 4)
                   if np.any((nfeet == 1) & on) else None,
                   "floor_point_margin_cm_single": _scale(_q(com_margin[(nfeet == 1) & on]), 100.0)},
           "zmp": {"frames": int(ok.sum()), "inside_share": round(float(np.mean(margin[ok] > 0)), 4) if ok.any() else None,
                   "inside_share_single": round(float(np.mean(margin[single] > 0)), 4) if single.any() else None,
                   "inside_share_double": round(float(np.mean(margin[double] > 0)), 4) if double.any() else None,
                   "margin_cm": _scale(_q(margin[ok]), 100.0), "margin_cm_single": _scale(_q(margin[single]), 100.0),
                   "margin_rel_single": _scale(_q(margin[single]), 1.0 / Lf),
                   "outside_runs_per_min": round(len(out_runs) / minutes, 2),
                   "outside_runs_per_min_over_1cm_3f": round(sum(1 for r in out_runs if r["depth_cm"] >= 1.0 and r["frames"] >= 3) / minutes, 2),
                   "tilt_deg": _q([r["tilt_deg"] for r in out_runs], (0.5, 0.9)) if out_runs else None,
                   "tilt_deg_per_min": round(sum(r["tilt_deg"] for r in out_runs) / minutes, 2),
                   "outside_runs": sorted(out_runs, key=lambda r: -r["tilt_deg"])[:200],
                   "rotation_part_cm": _scale(_q(rot_part[ok]), 100.0), "com_part_cm": _scale(_q(lin_part[ok]), 100.0)},
           "angmom": {"horizontal_per_s": _q(Lh[inrng], (0.5, 0.9, 0.99)), "vertical_per_s": _q(Lv[inrng], (0.5, 0.9, 0.99)),
                      "normalized": "L / (body mass x stature^2), 1/s"},
           "air": {"runs": len(air_rows), "frames": int(air.sum()), "com_acc_h_m_s2": _q(acc_h, (0.5, 0.9)),
                   "angmom_change_per_s2": _q(dL, (0.5, 0.9)), "stretches": air_rows[:100],
                   "min_frames": AIR_MIN_FRAMES}}
    if arrays:
        arr = {"com": dyn["com"], "zmp": dyn["zmp"], "zmp_lin": dyn["zmp_lin"], "margin": margin, "com_margin": com_margin,
               "angmom": dyn["angmom"], "force": dyn["force"], "contact_L": sup["contact"]["L"], "contact_R": sup["contact"]["R"],
               "part_L": np.array([{"flat": 3, "fore": 2, "heel": 1}.get(v, 0) for v in sup["part"]["L"]], np.int8),
               "part_R": np.array([{"flat": 3, "fore": 2, "heel": 1}.get(v, 0) for v in sup["part"]["R"]], np.int8)}
        return rep, arr
    return rep


def _scale(q, k):
    if q is None:
        return None
    return {key: (round(v * k, 3) if key != "n" else v) for key, v in q.items()}


# ---- the command ---------------------------------------------------------------------------------------------------

def _balance_layer():
    spec = importlib.util.spec_from_file_location("_wb_balance_layer", os.path.join(HERE, "balance_layer.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_bytes(path, data):
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


def load_model(path):
    from mmd_cli.formats import pmd, pmx
    return (pmd if path.lower().endswith(".pmd") else pmx).load(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("measure", "measure-pack"):
        p = sub.add_parser(name)
        p.add_argument("source", help="the dance (.vmd)" if name == "measure" else "an analysis pack folder (meta.json, bones_final.npz)")
        p.add_argument("model", help="the model (.pmx / .pmd): the rest positions")
        p.add_argument("--report", required=True)
        p.add_argument("--arrays", help="write the per-frame curves (.npz)")
        p.add_argument("--cutoff", type=float, default=CUTOFF_HZ, help="Hz: the low-pass on the segments (0: none)")
        p.add_argument("--contact", type=float, default=RIN_FEET["contact"], help="units: a foot this low is on the floor")
        p.add_argument("--range", type=int, nargs=2, metavar=("FIRST", "LAST"), help="the frames counted")
    args = ap.parse_args(argv)
    try:
        model = load_model(args.model)
        if args.cmd == "measure":
            from mmd_cli.formats import vmd
            body = _balance_layer().Body(model, vmd.load(args.source))
            lm, rots = landmarks_from_body(body)
        else:
            with open(os.path.join(args.source, "meta.json"), encoding="utf-8") as f:
                names = json.load(f)["bones"]
            z = np.load(os.path.join(args.source, "bones_final.npz"))
            lm, rots = landmarks_from_pack(names, z["pos"], z["rot"], rin_rest(model))
        feet = dict(RIN_FEET, contact=args.contact)
        rest = rin_rest(model)
        feet.update(ankle_rest_y=float(rest["左足ＩＫ"][1]), toe_rest_y=float(rest["左つま先ＩＫ"][1]))
        rep, arr = measure(lm, feet, rots, cutoff_hz=(args.cutoff or None), rng=args.range, arrays=True)
        rep["source"] = os.path.abspath(args.source)
        rep["model"] = os.path.abspath(args.model)
        write_bytes(os.path.abspath(args.report), (json.dumps(rep, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        if args.arrays:
            buf = io.BytesIO()
            np.savez_compressed(buf, **arr)
            write_bytes(os.path.abspath(args.arrays), buf.getvalue())
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    z = rep["zmp"]
    print(json.dumps({"ok": True, "zmp_inside_share": z["inside_share"], "outside_runs_per_min": z["outside_runs_per_min"],
                      "tilt_deg_per_min": z["tilt_deg_per_min"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
