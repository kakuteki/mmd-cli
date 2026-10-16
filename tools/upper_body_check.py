"""Check the upper body over the hips with measures a layer does not aim at: how sharply the head stops, how fast the
trunk and the neck bend, whether the head comes after the hips or before them, where the head goes against the hips,
what is left of the head's motion on the beat, and whether a hand at the face stays there.

    python tools/upper_body_check.py measure SOURCE [--model MODEL.pmx] --report r.json [--range FIRST LAST]
                                     [--beats beats.json]
    python tools/upper_body_check.py compare BEFORE AFTER [--model MODEL.pmx] --report r.json [--range FIRST LAST]
                                     [--beats beats.json]

SOURCE (BEFORE, AFTER): a dance (.vmd, with --model) or an analysis pack folder (meta.json's bone names, bones_final.npz's
pos and rot: the 26 bones of uncanny/pack and of the human baseline's hbpack, people and the MV alike).

Why (the review of tools/wb_layer.py, 2026-10-17): the layer bends the spine so that the head's pivot moves back by 0.9 of
the pelvis's quick part, and its own report then reads how much the head follows the pelvis.  That number goes down by
construction; whether the result moves like a person needs measures of other things.  Everything here reads the points
the viewer sees (the eyes' middle for the head, the hips' bone for the pelvis) and works on people's data and the MV's
alike.

The measures (measure()):
1. stops: the head's (頭) stops as the analysts' a08 finds them (the step speed |p(f+1) - p(f)| * fps in m/s; a deep
   local minimum, at most 0.4 of the highest speed of the 8 steps before, which is 0.6 m/s or more) and the time the
   speed takes from 80 to 20 % of its drop (sub-frame).  The human baseline: 71.4 ms [63.8, 80.2] (FineDance K-pop,
   choreography and jazz, 62 sequences), v8 45.9.
2. bend: the turn of the chest (上半身2) against the hips (下半身), of the head (頭) against the chest and against the hips,
   of the neck (首) against the chest and of the head against the neck: the angle (degrees from the bones' rest,
   quantiles), the speed of the turn (deg/s: p50, p90, p99), its acceleration's 99th percentile (deg/s^2, 6 Hz
   low-passed) and the share of the turn's speed (its power) over 1.5 Hz and over 4 Hz.
3. lag: does the head (the eyes' middle) come after the hips or before them?  The cross-correlation of their horizontal
   velocities band-passed 1.5-6 Hz (both axes pooled) over +-10 frames: the lag of its peak (ms, + the head after the
   hips) and its lean, (sum c(+k) - sum c(-k)) / sum |c(k)| over k 1..10 (+: the head's motion is more like the hips'
   past than their future).  A zero-phase filter of the hips (a head that moves as a smoothed copy of them) peaks at 0
   with no lean; a body that drags the head behind the hips peaks after 0.
4. local: the follow of the head on the hips in 2 s windows (60 frames, every 15): the slope of the head's horizontal
   acceleration (6 Hz) on the hips', each window weighted by the hips' acceleration power in it; the weighted quantiles
   and the shares under -0.25 (the head goes the other way) and over 0.75 (the head is carried).
5. beats (with --beats, a JSON with "beats": [seconds]): the head's and the hips' horizontal speed (6 Hz) averaged in 8
   bins of the beat's phase (its depth: (max - min) / mean), and the share of the head's stops (1) whose lowest step is
   within 2 frames of a beat.
compare(before, after) adds:
6. face, waist: where a hand's fingertip (中指３, else 手首) is within 10 cm of the eyes' middle (the face) or within 11 cm
   of the line from the hips' middle to 下半身 (the waist, as tools/hand_layer.py reads a hand on the hip; a dance only:
   an analysis pack has no hip joints) before, how that distance changes after (cm: quantiles of the change, frames
   closer by 1 cm and more, frames 2 cm and more farther); and the head's (the eyes' middle) and the fingertips' world
   moves (cm, quantiles, the five largest 0.5 s apart).
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _tool(name):
    spec = importlib.util.spec_from_file_location("_ubc_" + name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = _tool("wb_dynamics")

FPS = 30.0
UNIT_M = 0.08                   # metres a model unit (the analysis pack)
BONES = ["下半身", "上半身", "上半身2", "首", "頭", "左目", "右目", "左手首", "右手首", "左中指３", "右中指３", "左足", "右足"]
PAIRS = {"chest_on_hips": ("下半身", "上半身2"), "head_on_chest": ("上半身2", "頭"), "head_on_hips": ("下半身", "頭"),
         "neck_on_chest": ("上半身2", "首"), "head_on_neck": ("首", "頭")}
STOP_VFAST = 0.6                # m/s: a08's head (s1_events.VFAST["頭"])
STOP_WIN = 8                    # steps before the minimum (a08 WIN)
STOP_DEEP = 0.4                 # the minimum at most this share of the peak (a08 DEEP)
BAND = (1.5, 6.0)               # Hz: the quick part for the lag
MAX_LAG = 10                    # frames
WIN, HOP = 60, 15               # frames: the local follow's windows
FACE_NEAR_CM = 10.0
WAIST_NEAR_CM = 11.0            # a fingertip this near the line from the hips' middle to 下半身 (tools/hand_layer.py's waist)
BEAT_BINS = 8
BEAT_TOL = 2                    # frames


# ---- the parts ----------------------------------------------------------------------------------------------------

def from_pack(names, pos, rot):
    """name -> (pos [F, 3] units, rot [F, 4]) of the bones in BONES that the pack has"""
    ix = {n: i for i, n in enumerate(names)}
    return {n: (np.asarray(pos[:, ix[n]], dtype=np.float64), np.asarray(rot[:, ix[n]], dtype=np.float64))
            for n in BONES if n in ix}


def load_pack(folder):
    with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
        names = json.load(f)["bones"]
    z = np.load(os.path.join(folder, "bones_final.npz"))
    return from_pack(names, z["pos"], z["rot"])


def from_motion(model, motion, frames=None):
    """the same from a dance and its model (FK: the trunk, the head, the eyes and the hands need no IK)"""
    from mmd_cli import fk
    M = _tool("motor_layer")
    sk = M.Skeleton(model)
    F = (fk.last_frame(motion) + 1) if frames is None else frames
    names = [n for n in BONES if sk.has(n)]
    order = sk.closure([sk.i(n) for n in names])
    keys = M.sample_keys(motion, sk, order, F)
    wpos, wrot = M.fk_all(sk, keys, order, F)
    return {n: (wpos[sk.i(n)], wrot[sk.i(n)]) for n in names}


def load_source(path, model_path=None):
    if os.path.isdir(path):
        return load_pack(path)
    if not model_path:
        raise ValueError("%s is a dance: --model is needed" % path)
    from mmd_cli.formats import pmd, pmx, vmd
    model = (pmd if model_path.lower().endswith(".pmd") else pmx).load(model_path)
    return from_motion(model, vmd.load(path))


def eyes(parts):
    """the eyes' middle [F, 3] (units): what the viewer reads as the head's place; 頭 where there are no eyes"""
    if "左目" in parts and "右目" in parts:
        return 0.5 * (parts["左目"][0] + parts["右目"][0])
    return parts["頭"][0]


def dance_range(parts, thr_mm_s=50.0, trim=15, fs=FPS, unit_m=UNIT_M):
    """(first, last) frames of the dance proper: from the first to the last step where the head, the chest or a wrist
    moves faster than thr_mm_s, less `trim` frames at both ends (the human baseline's rule on a01's upper body, read on
    these points); None when that leaves under 4 s"""
    pts = [parts[n][0] for n in ("頭", "上半身2", "左手首", "右手首") if n in parts]
    sp = np.max(np.stack([step_speed(p, fs, unit_m) for p in pts], 1), axis=1) * 1000.0
    k = np.flatnonzero(sp > thr_mm_s)
    if not len(k):
        return None
    a, b = int(k[0]) + trim, int(k[-1]) + 1 - trim
    return (a, b - 1) if b - a >= 4 * fs else None


def fingertips(parts):
    out = {}
    for s in ("左", "右"):
        for n in (s + "中指３", s + "手首"):
            if n in parts:
                out[s] = parts[n][0]
                break
    return out


# ---- 1. stops (a08 s1_events, falling) ------------------------------------------------------------------------------

def step_speed(p, fs=FPS, unit_m=UNIT_M):
    """|p(f+1) - p(f)| * fs (m/s), F - 1 steps"""
    return np.linalg.norm(np.diff(np.asarray(p, dtype=np.float64), axis=0), axis=1) * unit_m * fs


def stop_events(s, vfast=STOP_VFAST, win=STOP_WIN, deep=STOP_DEEP):
    """the steps i of the deep local minima after a fast phase: s[i] the lowest of i-3..i+3, the highest of the `win`
    steps before at least vfast and s[i] at most deep times it"""
    s = np.asarray(s, dtype=np.float64)
    out = []
    for i in range(3, len(s) - 3):
        if s[i] > s[i - 1] or s[i] > s[i + 1] or s[i] != s[i - 3:i + 4].min():
            continue
        a = max(0, i - win)
        pk = s[a:i].max() if i > a else 0.0
        if pk >= vfast and s[i] <= deep * pk:
            out.append(i)
    return out


def _crossing(s, start, stop, level):
    for i in range(start, stop):
        if s[i] >= level > s[i + 1]:
            return i + (s[i] - level) / (s[i] - s[i + 1])
    return float("nan")


def stop_time(s, i0, win=STOP_WIN):
    """(frames from 80 to 20 % of the drop, the lowest step) of the stop at i0: its own minimum within +-2, its own peak
    within `win` before; the last crossing of 80 % before the minimum, then the first of 20 % after it"""
    s = np.asarray(s, dtype=np.float64)
    lo, hi = max(0, i0 - 2), min(len(s) - 1, i0 + 2)
    imin = lo + int(np.argmin(s[lo:hi + 1]))
    a = max(0, imin - win)
    ipk = a + int(np.argmax(s[a:imin + 1]))
    drop = s[ipk] - s[imin]
    hi80, lo20 = s[imin] + 0.8 * drop, s[imin] + 0.2 * drop
    t80 = float("nan")
    for i in range(imin - 1, ipk - 1, -1):
        if s[i] >= hi80 > s[i + 1]:
            t80 = i + (s[i] - hi80) / (s[i] - s[i + 1])
            break
    t20 = _crossing(s, int(math.floor(t80)) if np.isfinite(t80) else ipk, imin, lo20)
    return t20 - t80, imin


def stops(p, rng=None, fs=FPS, unit_m=UNIT_M, vfast=STOP_VFAST):
    """the head's stops in the steps of rng (first, last frame): count, per minute, the 80 -> 20 % time (ms, median and
    quartiles), the lowest steps' frames"""
    p = np.asarray(p, dtype=np.float64)
    a, b = (0, len(p) - 1) if rng is None else rng
    s = step_speed(p[a:b + 1], fs, unit_m)
    ev = stop_events(s, vfast)
    res = [stop_time(s, i) for i in ev]
    t = np.array([r[0] for r in res], dtype=np.float64) * 1000.0 / fs
    minutes = max(len(s) / fs / 60.0, 1e-9)
    ok = t[np.isfinite(t)]
    return {"n": len(ev), "per_min": round(len(ev) / minutes, 3),
            "t80_20_ms": ({"p25": round(float(np.percentile(ok, 25)), 2), "p50": round(float(np.median(ok)), 2),
                           "p75": round(float(np.percentile(ok, 75)), 2)} if len(ok) else None),
            "frames": [int(a + r[1]) for r in res]}


# ---- 2. bend ------------------------------------------------------------------------------------------------------

def relative(qa, qb):
    """the turn of b in a's frame [F, 4]"""
    return D.qmul(D.qconj(np.asarray(qa, dtype=np.float64)), np.asarray(qb, dtype=np.float64))


def angle_deg(q):
    q = np.asarray(q, dtype=np.float64)
    return np.degrees(2.0 * np.arccos(np.clip(np.abs(q[:, 3]) / np.maximum(np.linalg.norm(q, axis=1), 1e-12), 0.0, 1.0)))


def band_share(x, lo_hz, fs=FPS, nw=64):
    """the share of x's power [F, k] (each window's mean off, Hann windows of nw frames, half overlap) at lo_hz and over"""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    win = np.hanning(nw)
    freqs = np.fft.rfftfreq(nw, 1.0 / fs)
    p = np.zeros(len(freqs))
    for st in range(0, len(x) - nw + 1, nw // 2):
        seg = x[st:st + nw] - x[st:st + nw].mean(axis=0)
        p += (np.abs(np.fft.rfft(seg * win[:, None], axis=0)) ** 2).sum(axis=1)
    tot = float(p[1:].sum())
    return float(p[freqs >= lo_hz - 1e-9].sum()) / tot if tot > 0 else float("nan")


def bend(parts, rng=None, fs=FPS):
    out = {}
    for name, (a, b) in PAIRS.items():
        if a not in parts or b not in parts:
            continue
        q = relative(parts[a][1], parts[b][1])
        r0, r1 = (0, len(q) - 1) if rng is None else rng
        q = q[r0:r1 + 1]
        w = D.angular_velocity(q, fs)                                   # rad/s (in the world of the relative track)
        sp = np.degrees(np.linalg.norm(w, axis=1))
        acc = np.degrees(np.linalg.norm(D.diff1(D.lowpass(w, 6.0, fs), fs), axis=1))
        ang = angle_deg(q)
        inner = slice(2, len(q) - 2)
        out[name] = {"angle_deg": {"p50": round(float(np.median(ang)), 2), "p99": round(float(np.percentile(ang, 99)), 2),
                                   "max": round(float(ang.max()), 2)},
                     "speed_deg_s": {k: round(float(np.percentile(sp[inner], v)), 2) for k, v in (("p50", 50), ("p90", 90), ("p99", 99))},
                     "acc_deg_s2_p99": round(float(np.percentile(acc[inner], 99)), 1),
                     "share_over_1_5Hz": round(band_share(w[inner], 1.5, fs), 4),
                     "share_over_4Hz": round(band_share(w[inner], 4.0, fs), 4)}
    return out


# ---- 3. lag -------------------------------------------------------------------------------------------------------

def bandpass(x, lo_hz, hi_hz, fs=FPS):
    return D.lowpass(x, hi_hz, fs) - D.lowpass(x, lo_hz, fs)


def lag(head, pelvis, rng=None, fs=FPS, band=BAND, max_lag=MAX_LAG):
    """the cross-correlation c(k) of the head's and the hips' horizontal velocities (band-passed) for k in -max_lag ..
    max_lag frames (c(k): the head at t + k against the hips at t), its peak's lag (ms, a parabola through the top three)
    and its lean"""
    vh = D.diff1(bandpass(np.asarray(head, dtype=np.float64), band[0], band[1], fs), fs)[:, [0, 2]]
    vp = D.diff1(bandpass(np.asarray(pelvis, dtype=np.float64), band[0], band[1], fs), fs)[:, [0, 2]]
    a, b = (0, len(vh) - 1) if rng is None else rng
    a, b = a + max_lag, b - max_lag
    if b - a < 3 * max_lag:
        return None
    ref = vp[a:b + 1]
    nref = math.sqrt(float(np.sum(ref * ref)))
    c = []
    for k in range(-max_lag, max_lag + 1):
        x = vh[a + k:b + 1 + k]
        nx = math.sqrt(float(np.sum(x * x)))
        c.append(float(np.sum(x * ref)) / max(nref * nx, 1e-300))
    c = np.array(c)
    i = int(np.argmax(c))
    shift = 0.0
    if 0 < i < len(c) - 1:
        den = c[i - 1] - 2.0 * c[i] + c[i + 1]
        shift = 0.5 * (c[i - 1] - c[i + 1]) / den if den < 0 else 0.0
    pos, neg = c[max_lag + 1:], c[:max_lag][::-1]
    lean = float(np.sum(pos) - np.sum(neg)) / max(float(np.sum(np.abs(pos)) + np.sum(np.abs(neg))), 1e-300)
    return {"peak_lag_ms": round((i - max_lag + shift) * 1000.0 / fs, 1), "peak": round(float(c[i]), 4),
            "c0": round(float(c[max_lag]), 4), "lean": round(lean, 4),
            "c": [round(float(v), 4) for v in c]}


# ---- 4. local follow ----------------------------------------------------------------------------------------------

def _wq(v, w, qs):
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w) / max(float(np.sum(w)), 1e-300)
    return {("p%02d" % int(q * 100)): round(float(np.interp(q, cw, v)), 4) for q in qs}


def local_follow(head, pelvis, rng=None, fs=FPS, win=WIN, hop=HOP, cutoff_hz=6.0):
    ah = D.diff2(D.lowpass(np.asarray(head, dtype=np.float64), cutoff_hz, fs), fs)[:, [0, 2]]
    ap = D.diff2(D.lowpass(np.asarray(pelvis, dtype=np.float64), cutoff_hz, fs), fs)[:, [0, 2]]
    a, b = (0, len(ah) - 1) if rng is None else rng
    slopes, weights, starts = [], [], []
    for st in range(a + 3, b - 3 - win + 2, hop):
        x, p = ah[st:st + win], ap[st:st + win]
        den = float(np.sum(p * p))
        if den <= 0:
            continue
        slopes.append(float(np.sum(x * p)) / den)
        weights.append(den)
        starts.append(st)
    if not slopes:
        return None
    s, w = np.array(slopes), np.array(weights)
    tot = float(w.sum())
    strong = np.flatnonzero(w >= 0.25 * np.median(w))          # (a window where the hips hardly move has a wild slope)
    worst = strong[np.argsort(s[strong])[:5]]
    return {"windows": len(s), "weighted": _wq(s, w, (0.1, 0.25, 0.5, 0.75, 0.9)),
            "share_against": round(float(w[s < -0.25].sum()) / tot, 4),
            "share_carried": round(float(w[s > 0.75].sum()) / tot, 4),
            "most_against": [{"first": int(starts[k]), "s": round(starts[k] / fs, 2), "slope": round(float(s[k]), 3)} for k in worst]}


# ---- 5. beats -----------------------------------------------------------------------------------------------------

def beat_phase(F, beats_s, fs=FPS):
    """per frame: the phase in its beat (0 .. 1) and whether it lies between the first and the last beat"""
    t = np.arange(F) / fs
    b = np.asarray(beats_s, dtype=np.float64)
    k = np.searchsorted(b, t, side="right") - 1
    ok = (k >= 0) & (k < len(b) - 1)
    kk = np.clip(k, 0, len(b) - 2)
    ph = (t - b[kk]) / (b[kk + 1] - b[kk])
    return np.where(ok, ph, np.nan), ok


def beat_depth(p, beats_s, rng=None, fs=FPS, unit_m=UNIT_M, nbins=BEAT_BINS):
    v = np.linalg.norm(D.diff1(D.lowpass(np.asarray(p, dtype=np.float64), 6.0, fs), fs)[:, [0, 2]], axis=1) * unit_m
    ph, ok = beat_phase(len(v), beats_s, fs)
    a, b = (0, len(v) - 1) if rng is None else rng
    m = ok.copy()
    m[:a] = False
    m[b + 1:] = False
    bins = np.minimum((ph[m] * nbins).astype(int), nbins - 1)
    means = np.array([float(v[m][bins == i].mean()) if np.any(bins == i) else float("nan") for i in range(nbins)])
    mean = float(np.nanmean(means))
    return {"bins_m_s": [round(float(x), 4) for x in means], "depth": round(float((np.nanmax(means) - np.nanmin(means)) / mean), 4)
            if mean > 0 else None}


def on_beat_share(frames, beats_s, fs=FPS, tol=BEAT_TOL):
    if not len(frames):
        return None
    bf = np.asarray(beats_s, dtype=np.float64) * fs
    d = np.array([float(np.min(np.abs(bf - (f + 0.5)))) for f in frames])     # a step lies between its two frames
    return round(float(np.mean(d <= tol)), 4)


# ---- the reports --------------------------------------------------------------------------------------------------

def measure(parts, rng=None, beats=None, fs=FPS):
    head = eyes(parts)
    pel = parts["下半身"][0]
    rep = {"range": list(rng) if rng is not None else [0, len(pel) - 1],
           "stops": stops(parts["頭"][0], rng, fs), "bend": bend(parts, rng, fs),
           "lag": lag(head, pel, rng, fs), "local": local_follow(head, pel, rng, fs)}
    if beats is not None:
        rep["beats"] = {"head": beat_depth(head, beats, rng, fs), "hips": beat_depth(pel, beats, rng, fs),
                        "head_stops_on_beat": on_beat_share(rep["stops"]["frames"], beats, fs)}
    rep["stops"] = {k: v for k, v in rep["stops"].items() if k != "frames"}
    return rep


def _qd(x):
    x = np.asarray(x, dtype=np.float64)
    if not len(x):
        return None
    out = {k: round(float(np.percentile(x, v)), 3) for k, v in (("p50", 50), ("p90", 90), ("p99", 99))}
    out.update(max=round(float(x.max()), 3), n=int(len(x)))
    return out


def _to_line(p, a, b):
    ab = b - a
    t = np.clip(np.sum((p - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def waist_line(parts):
    """(the hips' middle, 下半身) [F, 3] each, or None without the hip joints (an analysis pack has none)"""
    if "左足" in parts and "右足" in parts:
        return 0.5 * (parts["左足"][0] + parts["右足"][0]), parts["下半身"][0]
    return None


def face(before, after, rng=None, near_cm=FACE_NEAR_CM, unit_m=UNIT_M, where="face"):
    """where a fingertip is within near_cm of the eyes' middle (where="waist": of the line from the hips' middle to
    下半身) before: the change of that distance after"""
    if where == "face":
        dist = lambda parts, p: np.linalg.norm(p - eyes(parts), axis=1)        # noqa: E731
    else:
        if waist_line(before) is None or waist_line(after) is None:
            return None
        dist = lambda parts, p: _to_line(p, *waist_line(parts))               # noqa: E731
    tb, ta = fingertips(before), fingertips(after)
    F = len(before["下半身"][0])
    a, b = (0, F - 1) if rng is None else rng
    cm = unit_m * 100.0
    rows = []
    for s in tb:
        if s not in ta:
            continue
        db = dist(before, tb[s]) * cm
        da = dist(after, ta[s]) * cm
        m = np.zeros(F, bool)
        m[a:b + 1] = True
        m &= db < near_cm
        rows.append((db[m], da[m], np.flatnonzero(m)))
    if not rows:
        return None
    db = np.concatenate([r[0] for r in rows])
    da = np.concatenate([r[1] for r in rows])
    fr = np.concatenate([r[2] for r in rows])
    ch = da - db
    closer = ch <= -1.0
    farther = ch >= 2.0
    worst = np.argsort(-np.abs(ch))[:5] if len(ch) else []
    return {"frames": int(len(ch)), "change_cm": _qd(np.abs(ch)), "closer_1cm": int(closer.sum()), "farther_2cm": int(farther.sum()),
            "worst": [{"frame": int(fr[k]), "s": round(fr[k] / FPS, 2), "before_cm": round(float(db[k]), 2), "after_cm": round(float(da[k]), 2)}
                      for k in worst]}


def compare(before, after, rng=None, beats=None, fs=FPS, unit_m=UNIT_M):
    eb, ea = eyes(before), eyes(after)
    F = min(len(eb), len(ea))
    a, b = (0, F - 1) if rng is None else rng
    cm = unit_m * 100.0
    moves = {"head_cm": _qd(np.linalg.norm(ea[a:b + 1] - eb[a:b + 1], axis=1) * cm)}
    tb, ta = fingertips(before), fingertips(after)
    for s in tb:
        if s in ta:
            d = np.linalg.norm(ta[s][a:b + 1] - tb[s][a:b + 1], axis=1) * cm
            key = "fingertip_%s_cm" % ("L" if s == "左" else "R")
            moves[key] = _qd(d)
            worst = []
            for k in np.argsort(-d):
                if all(abs(int(k) - w) > 15 for w in worst):
                    worst.append(int(k))
                if len(worst) >= 5:
                    break
            moves[key]["worst"] = [{"frame": a + k, "s": round((a + k) / fs, 2), "cm": round(float(d[k]), 2)} for k in worst]
    return {"before": measure(before, rng, beats, fs), "after": measure(after, rng, beats, fs),
            "moves": moves, "face": face(before, after, rng, unit_m=unit_m),
            "waist": face(before, after, rng, near_cm=WAIST_NEAR_CM, unit_m=unit_m, where="waist")}


# ---- the command --------------------------------------------------------------------------------------------------

def write_json(path, obj):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    with open(part, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(part, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("measure", "compare"):
        p = sub.add_parser(name)
        if name == "measure":
            p.add_argument("source", help="a dance (.vmd, with --model) or an analysis pack folder")
        else:
            p.add_argument("before")
            p.add_argument("after")
        p.add_argument("--model", help="the model (.pmx / .pmd) of a dance")
        p.add_argument("--report", required=True)
        p.add_argument("--range", type=int, nargs=2, metavar=("FIRST", "LAST"))
        p.add_argument("--beats", help='a JSON with "beats": [seconds]')
    args = ap.parse_args(argv)
    try:
        beats = None
        if args.beats:
            with open(args.beats, encoding="utf-8") as f:
                beats = json.load(f)["beats"]
        rng = tuple(args.range) if args.range else None
        if args.cmd == "measure":
            rep = measure(load_source(args.source, args.model), rng, beats)
            rep["source"] = os.path.abspath(args.source)
        else:
            if os.path.abspath(args.before) == os.path.abspath(args.after):
                raise ValueError("BEFORE and AFTER are the same")
            rep = compare(load_source(args.before, args.model), load_source(args.after, args.model), rng, beats)
            rep["before_source"], rep["after_source"] = os.path.abspath(args.before), os.path.abspath(args.after)
        write_json(args.report, rep)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    head = rep["stops"] if args.cmd == "measure" else rep["after"]["stops"]
    print(json.dumps({"ok": True, "report": os.path.abspath(args.report), "head_stops_t80_20_ms": head["t80_20_ms"]},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
