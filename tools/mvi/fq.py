"""floaty's measures of 'no weight / floating' on the pelvis's height (stage6/floaty/scripts/fq.py, 2026-10-17), the same
function on people (FineDance, on hinata) and on the MV (the 26 pack bones):

Pelvis = the 下半身 bone's world position.  cm for heights, cm/s, units/s^2 for accelerations (1 unit = 8 cm; gravity
9.8 m/s^2 = 122.5 units/s^2).  30 fps central differences, no smoothing.  The air: both feet (the foot and toe IKs,
over their own 5th percentile) above 2.5 cm for 4 frames or more; its pelvis acceleration is a parabola's.  Descents:
from a maximum to the next minimum (turning points with a 1 cm hysteresis) of 3 cm or more.  Apexes: maxima 3 cm above
both neighbouring minima; their dwell within 1 cm of the top.

The frame range: floaty's own (the human baseline's dance_range on the pack's positions with the rotations left at
rest, dance_range_fq), as floaty measured people and the MV.
"""
import numpy as np

from . import analysts as A
from . import hb

FPS = 30.0
DT = 1.0 / FPS
G_CM = 980.0
U = 8.0
NAMES = ["全ての親", "センター", "グルーブ", "腰", "下半身", "上半身", "上半身2", "首", "頭", "両目", "左目", "右目", "左肩",
         "右肩", "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首", "左中指３", "右中指３", "左足ＩＫ", "右足ＩＫ",
         "左つま先ＩＫ", "右つま先ＩＫ"]
BI = {n: i for i, n in enumerate(NAMES)}
CONTACT_CM = 2.5
DROP_CM = 3.0
HALF_G = -61.25                 # units/s^2: half of gravity, downwards


def runs(mask, min_len=1):
    out, s = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and s is None:
            s = i
        elif not m and s is not None:
            if i - s >= min_len:
                out.append((s, i))
            s = None
    return out


def turning_points(y, hyst):
    """alternating extrema of y with a hysteresis of hyst (cm): [(index, 'max'/'min')]"""
    pts = []
    mode, ext_i = None, 0
    for i in range(1, len(y)):
        if mode is None:
            if y[i] - y[0] >= hyst:
                mode, ext_i = "up", i
                pts.append((int(np.argmin(y[:i + 1])), "min"))
            elif y[0] - y[i] >= hyst:
                mode, ext_i = "down", i
                pts.append((int(np.argmax(y[:i + 1])), "max"))
            continue
        if mode == "up":
            if y[i] > y[ext_i]:
                ext_i = i
            elif y[ext_i] - y[i] >= hyst:
                pts.append((ext_i, "max"))
                mode, ext_i = "down", i
        else:
            if y[i] < y[ext_i]:
                ext_i = i
            elif y[i] - y[ext_i] >= hyst:
                pts.append((ext_i, "min"))
                mode, ext_i = "up", i
    return pts


def contacts(pos):
    out = []
    for s in ("左", "右"):
        an = pos[:, BI[s + "足ＩＫ"], 1] * U
        to = pos[:, BI[s + "つま先ＩＫ"], 1] * U
        h = np.minimum(an - np.percentile(an, 5), to - np.percentile(to, 5))
        out.append(h < CONTACT_CM)
    return out[0], out[1]


def measure(pos, a, b, events=False):
    """pos[F, 26, 3] in MMD units; the measures on steps [a, b)"""
    y = pos[:, BI["下半身"], 1].astype(np.float64) * U                     # cm
    v = np.zeros_like(y)
    v[1:-1] = (y[2:] - y[:-2]) / (2 * DT)
    acc = np.zeros_like(y)
    acc[1:-1] = (y[2:] - 2 * y[1:-1] + y[:-2]) / DT ** 2 / U          # u/s^2
    cl, cr = contacts(pos)
    air = ~cl & ~cr
    inr = np.zeros(len(y), bool)
    inr[a:b] = True
    minutes = (b - a) / FPS / 60.0
    r, ev = {}, {"air": [], "desc": [], "apex": [], "drift": []}
    ap = [(s, e) for s, e in runs(air & inr, 4)]
    accs = []
    for s, e in ap:
        t = np.arange(e - s) * DT
        c = np.polyfit(t, y[s:e], 2)
        aa = 2 * c[0] / U
        accs.append(aa)
        ev["air"].append({"t": round(s / FPS, 2), "frames": e - s, "acc": round(aa, 1), "first": s, "last": e - 1})
    r["air_per_min"] = len(ap) / minutes
    r["air_acc_median"] = float(np.median(accs)) if accs else None
    r["air_frac_slower_half_g"] = float(np.mean(np.array(accs) > HALF_G)) if accs else None
    tp = turning_points(y[a:b], 1.0)
    fr, pk, br, dur = [], [], [], []
    fr6 = []
    for (i0, k0), (i1, k1) in zip(tp, tp[1:]):
        if k0 != "max" or k1 != "min":
            continue
        s, e = a + i0, a + i1
        h = y[s] - y[e]
        if h < DROP_CM or e - s < 2:
            continue
        T = (e - s) * DT
        ratio = T / np.sqrt(2 * h / G_CM)
        pdown = float(acc[s:e + 1].min())
        third = s + (2 * (e - s)) // 3
        pbrake = float(acc[third:min(e + 5, len(acc))].max())
        fr.append(ratio)
        pk.append(pdown)
        br.append(pbrake)
        dur.append(T)
        if h >= 6:
            fr6.append(ratio)
        ev["desc"].append({"t": round(s / FPS, 2), "t_end": round(e / FPS, 2), "drop_cm": round(h, 2), "ratio": round(ratio, 2),
                           "peak_down": round(pdown, 1), "brake": round(pbrake, 1), "first": s, "last": e})
    r["desc_per_min"] = len(fr) / minutes
    r["desc_ratio_median"] = float(np.median(fr)) if fr else None
    r["desc6_ratio_median"] = float(np.median(fr6)) if fr6 else None
    r["desc_peak_down_median"] = float(np.median(pk)) if pk else None
    r["desc_brake_median"] = float(np.median(br)) if br else None
    r["desc_drop_median_cm"] = float(np.median([d["drop_cm"] for d in ev["desc"]])) if fr else None
    dw = []
    for j in range(1, len(tp) - 1):
        i, k = tp[j]
        if k != "max":
            continue
        s = a + i
        if y[s] - y[a + tp[j - 1][0]] < DROP_CM or y[s] - y[a + tp[j + 1][0]] < DROP_CM:
            continue
        lo, hi = s, s
        while lo > a + tp[j - 1][0] and y[lo - 1] > y[s] - 1.0:
            lo -= 1
        while hi < a + tp[j + 1][0] and y[hi + 1] > y[s] - 1.0:
            hi += 1
        d = (hi - lo + 1) * DT * 1000
        dw.append(d)
        ev["apex"].append({"t": round(s / FPS, 2), "dwell_ms": round(d), "rise": round(y[s] - y[a + tp[j - 1][0]], 1),
                           "fall": round(y[s] - y[a + tp[j + 1][0]], 1), "first": lo, "last": hi})
    r["apex_per_min"] = len(dw) / minutes
    r["apex_dwell_median_ms"] = float(np.median(dw)) if dw else None
    aa = acc[a:b]
    r["acc_down_p1"] = float(np.percentile(aa, 1))
    r["acc_up_p99"] = float(np.percentile(aa, 99))
    r["acc_abs_median"] = float(np.median(np.abs(aa)))
    r["vy_abs_median"] = float(np.median(np.abs(v[a:b])))
    r["vy_abs_p95"] = float(np.percentile(np.abs(v[a:b]), 95))
    W = 13                                                             # 0.43 s: one beat of the song
    rng = np.array([y[i:i + W].max() - y[i:i + W].min() for i in range(a, b - W)])
    r["beat_range_median_cm"] = float(np.median(rng))
    r["beat_range_p90_cm"] = float(np.percentile(rng, 90))
    vv = v[a:b] - v[a:b].mean()
    P = np.abs(np.fft.rfft(vv * np.hanning(len(vv)))) ** 2
    f = np.fft.rfftfreq(len(vv), DT)
    r["vy_power_above_3hz_pct"] = float(100 * P[f >= 3].sum() / P[f > 0.2].sum())
    ph = pos[:, BI["下半身"], [0, 2]].astype(np.float64) * U
    hs = np.zeros(len(y))
    hs[1:-1] = np.linalg.norm(ph[2:] - ph[:-2], axis=1) / (2 * DT)
    still = cl & cr & (hs < 3.0) & inr
    sr = runs(still, 15)
    dv = np.concatenate([np.abs(v[s:e]) for s, e in sr]) if sr else np.zeros(0)
    r["still_per_min"] = len(sr) / minutes
    r["still_vy_median"] = float(np.median(dv)) if len(dv) else None
    for s, e in sr:
        ev["drift"].append({"t": round(s / FPS, 2), "frames": e - s, "vy_med": round(float(np.median(np.abs(v[s:e]))), 2),
                            "dy_cm": round(float(y[e - 1] - y[s]), 2)})
    if events:
        r["events"] = ev
        r["series"] = {"y_cm": y, "acc": acc, "beat_range": rng, "beat_range_first": a}
    return r


def dance_range_fq(pos):
    """floaty's dance_range: the human baseline's on the positions with every rotation at rest"""
    part = A.part_speeds(np.asarray(pos), np.zeros(pos.shape[:2] + (4,), np.float32) + np.array([0, 0, 0, 1], np.float32),
                         NAMES)
    return hb.dance_range(part)
