"""The human baseline's body measures (stage6/human_baseline/scripts/hb_measures.py, 2026-10-15) on the pack arrays of a
version, with the analysts' functions of analysts.py.  The same expressions; what is added is the list of the places
behind each count (the spikes' steps, the stops and their times, a18's sudden stops and holds), for the timeline.

The frame range is the baseline's rule for every sequence, people and MV alike (dance_range): from the first to the last
step where the upper body (a01's part speed) is above 50 mm/s, cut by 15 steps on both ends.

    res, ev = measure(names, pos, rot)       # res: hb_measures.measure's dict; ev: the places
"""
import numpy as np

from . import analysts as A

FPS = 30.0
U2M = 0.08
UPPER = ["trunk", "head", "arm_L", "arm_R", "hand_L", "hand_R"]
PTS9 = ["頭", "左手首", "右手首", "左ひじ", "右ひじ", "上半身2", "センター", "左足ＩＫ", "右足ＩＫ"]      # a20 s04_energy.py
JOINTS09 = [("torso", "下半身", "上半身2"), ("clav", "上半身2", "%s肩"), ("shoulder", "%s肩", "%s腕"),
            ("elbow", "%s腕", "%sひじ"), ("wrist", "%sひじ", "%s手首"), ("finger", "%s手首", "%s中指３")]   # a09 s02_signals.py
CHAIN09 = ["torso", "clav", "shoulder", "elbow", "wrist", "finger"]


def dance_range(part, trim=15, thr=50.0):
    """steps [a, b) from the first to the last step of the upper body above thr mm/s, cut by trim steps on both ends"""
    up = part["upper_body"]
    k = np.flatnonzero(up > thr)
    if len(k) == 0:
        return None
    a, b = int(k[0]) + trim, int(k[-1]) + 1 - trim
    return (a, b) if b - a >= 4 * 30 else None


def _runs_in(mask, a, b, min_len=1):
    return [(s, e) for s, e in A.runs20(mask, min_len) if a <= s < b]


def _pct(x):
    return round(100.0 * float(np.mean(x)), 4)


def m_a01(part, a, b):
    out = {}
    for p in UPPER + ["upper_body"]:
        s = part[p][a:b]
        out[p] = {"exact_pct": _pct(s < A.EXACT), "lt1_pct": _pct(s < A.MAIN), "lt5_pct": _pct(s < 5), "lt20_pct": _pct(s < 20),
                  "p01": round(float(np.percentile(s, 1)), 3), "p05": round(float(np.percentile(s, 5)), 3),
                  "median": round(float(np.median(s)), 2)}
    anyst = np.zeros(len(part["trunk"]), bool)
    for p in UPPER:
        anyst |= part[p] < A.MAIN
    out["any_upper_lt1_pct"] = _pct(anyst[a:b])
    hold = part["upper_body"] < 50.0
    hr = [(s, L) for s, L in A.runs(hold) if L >= 8 and a <= s and s + L <= b]
    hs = np.concatenate([part["head"][s:s + L] for s, L in hr]) if hr else np.zeros(0)
    out["holds_ub50_8f"] = {"per_min": round(len(hr) / ((b - a) / FPS / 60.0), 3), "share_pct": round(100.0 * sum(L for _, L in hr) / (b - a), 3),
                            "head_median": round(float(np.median(hs)), 3) if len(hs) else None,
                            "head_p05": round(float(np.percentile(hs, 5)), 3) if len(hs) else None,
                            "head_in_3_9_pct": _pct((hs >= 3) & (hs <= 9)) if len(hs) else None,
                            "head_lt1_pct": _pct(hs < 1) if len(hs) else None}
    return out, {"holds": hr}


def m_a20(names, pos, rot, a, b):
    ix = {n: i for i, n in enumerate(names)}
    pos, rot = pos.astype(np.float64), rot.astype(np.float64)
    out = {}
    sp = np.stack([A.lin_speed(pos[:, ix[n]]) for n in PTS9], axis=1)
    mx = sp.max(axis=1)
    ev = {}
    for thr in (0.5, 2.0, 5.0):
        m = mx < thr
        rr = _runs_in(m, a, b)
        lens = np.array([min(e, b - 1) - s + 1 for s, e in rr]) if rr else np.zeros(0, int)
        out["all9_lt%g" % thr] = {"pct": _pct(m[a:b]), "longest_f": int(lens.max()) if len(lens) else 0,
                                  "runs_ge10_per_min": round(int((lens >= 10).sum()) / ((b - a) / FPS / 60.0), 3)}
        ev["all9_lt%g" % thr] = rr
    hs, cs = A.lin_speed(pos[:, ix["頭"]]), A.lin_speed(pos[:, ix["上半身2"]])
    ha = A.ang_speed(rot[:, ix["頭"]])
    frozen = (hs < 0.5) & (cs < 0.5) & (ha < 2)
    fr = [r for r in A.runs20(frozen, 6) if a <= r[0] < b]
    L = np.array([e - s + 1 for s, e in fr])
    out["head_chest_frozen_6f"] = {"runs": len(fr), "runs_per_min": round(len(fr) / ((b - a) / FPS / 60.0), 3),
                                   "pct": round(100.0 * float(L.sum()) / (b - a), 4) if len(L) else 0.0}
    cen, ch, cha = A.lin_speed(pos[:, ix["センター"]]), A.lin_speed(pos[:, ix["上半身2"]]), A.ang_speed(rot[:, ix["上半身2"]])
    tf = (cen < 0.5) & (ch < 0.5) & (cha < 1.0)
    out["torso_frozen_pct"] = _pct(tf[a:b])
    out["chest_turn_min"] = round(float(cha[a:b].min()), 4)
    ev["head_chest_frozen_6f"] = fr
    ev["torso_frozen"] = _runs_in(tf, a, b)
    return out, ev


def m_a02(names, pos, a, b):
    ix = {n: i for i, n in enumerate(names)}
    out = {}
    for side, bone in (("R", "右手首"), ("L", "左手首"), ("head", "頭")):
        v = np.diff(pos[a:b, ix[bone]].astype(np.float64), axis=0)
        d = A.dips(np.linalg.norm(v, axis=1))
        out[side] = {"dips_per_s": [round(float(x), 4) for x in d], "deep_per_s": round(float(d[0] + d[1]), 4),
                     "band3_6_pct": round(100.0 * A.band(v), 3)}
    return out


def m_a08(names, pos, a, b):
    ix = {n: i for i, n in enumerate(names)}
    pm = pos.astype(np.float64) * A.UNIT_M
    minutes = (b - a) / FPS / 60.0
    out, ev = {}, {}
    for name in A.POINTS:
        p = pm[a:b, ix[name]]
        v = np.diff(p, axis=0) * A.FPS08
        s = np.linalg.norm(v, axis=1)
        up, dn = A.spikes(s, A.T_SPIKE[name])
        fv, pv = A.welch(v)
        bands = A.band_power(fv, pv)
        sf = np.linalg.norm(A.step(p), axis=1)
        st = {}
        evs = {}
        for kind, falling in (("stop", True), ("start", False)):
            found = A.find_events(sf, A.VFAST[name], falling)
            ms = [A.measure_stop(sf, i, falling) for i in found]
            t = np.array([m["t_80_20"] for m in ms], float)
            st[kind] = {"n": len(found), "per_min": round(len(found) / minutes, 3),
                        "t80_20_med_ms": round(float(np.nanmedian(t)) / FPS * 1000.0, 1) if np.isfinite(t).any() else None}
            evs[kind] = [(a + m["imin"], a + m["ipk"], m["t_80_20"] / FPS * 1000.0, m["vpk"]) for m in ms]
        out[name] = {"spikes_per_min": round((up + dn) / minutes, 3), "spikes_up_dn": [int(up), int(dn)],
                     # (a point that never moves has no power at all: None; the analysts' data never had one)
                     "vel_share_ge8hz_pct": round(100.0 * sum(bands[6:]) / sum(bands), 3) if sum(bands) > 0 else None,
                     "stop": st["stop"], "start": st["start"]}
        su, sd = A.spike_steps(s, A.T_SPIKE[name])
        ev[name] = {"spikes": sorted([(a + int(k), float(s[k] - 0.5 * (s[k - 1] + s[k + 1])), "up") for k in su] +
                                     [(a + int(k), float(0.5 * (s[k - 1] + s[k + 1]) - s[k]), "dn") for k in sd]),
                    "stops": evs["stop"], "starts": evs["start"]}
    return out, ev


def m_a18(names, pos, rot, a, b):
    """body_motion.py as it is, on the range only; plus the vertical acceleration of グルーブ (the baseline's addition)"""
    res, lines, events = A.body_motion(names, pos[a:b], rot[a:b])
    minutes = (b - a) / FPS / 60.0
    out = {"minutes": round(minutes, 3)}
    out["spins_per_min"] = round(len(events["spins"]) / minutes, 3)
    for nm, key in (("頭", "head"), ("上半身", "upper"), ("下半身", "lower")):
        out["sudden_stops_%s_per_min" % key] = round(len(events["sudden_stops"][nm]) / minutes, 3)
    out["head_holds_per_min"] = round(len(events["holds"]) / minutes, 3)
    out["head_holds_pct"] = round(100.0 * sum(h - g for g, h, _, _ in events["holds"]) / (b - a), 3)
    for k in ("yawrate_下半身", "angspeed_頭", "angspeed_上半身", "head_speed", "head_acc", "hip_acc", "center_vy"):
        x = np.abs(res[k])
        key = k.replace("下半身", "lower").replace("上半身", "upper").replace("頭", "head")
        out[key] = {"p50": round(float(np.percentile(x, 50)), 3), "p90": round(float(np.percentile(x, 90)), 3),
                    "p99": round(float(np.percentile(x, 99)), 3)}
    ay = np.gradient(res["center_vy"]) * FPS
    out["center_ay"] = {"p01": round(float(np.percentile(ay, 1)), 2), "min": round(float(ay.min()), 2),
                        "down_gt_98u_pct": _pct(ay < -98.0), "down_gt_g_pct": _pct(ay < -9.81 / U2M),
                        "down_gt_98u_runs_per_min": round(len(A.runs20(ay < -98.0, 1)) / minutes, 3)}
    shift = lambda xs: [tuple([x[0] + a, x[1] + a] + list(x[2:])) for x in xs]      # noqa: E731
    ev = {"spins": shift(events["spins"]), "sudden_stops": {k: shift(v) for k, v in events["sudden_stops"].items()},
          "holds": shift(events["holds"]), "center_ay": np.asarray(ay, dtype=np.float64), "first": a, "lines": lines}
    return out, ev


def m_a09(names, rot, a, b):
    ix = {n: i for i, n in enumerate(names)}
    r = rot[a:b].astype(np.float64)
    out = {}
    for s, jp in (("L", "左"), ("R", "右")):
        sp = {}
        for j, par, chi in JOINTS09:
            pa = par % jp if "%" in par else par
            ch = chi % jp if "%" in chi else chi
            q = A.continuous(A.relative(r[:, ix[pa]], r[:, ix[ch]]))
            sp[j] = A.angular_speed(q)
        xc = {}
        for x, y in zip(CHAIN09[:-1], CHAIN09[1:]):
            lg = [l for _, l, _ in A.xcorr_lags(sp[x], sp[y])]
            xc["%s->%s" % (x, y)] = A.summary(lg)
        rs = A.rests(sp["shoulder"], sp["elbow"], sp["wrist"])
        stops = []
        for (i, j) in rs:
            lo = max(0, i - 15)
            off = {}
            for jt in ("shoulder", "wrist"):
                idx = np.where(sp[jt][lo:i] > 15)[0]
                off[jt] = None if len(idx) == 0 else lo + int(idx[-1])
            if off["shoulder"] is not None and off["wrist"] is not None:
                stops.append(off["wrist"] - off["shoulder"])
        out[s] = {"xcorr": xc, "rests": len(rs), "rests_per_min": round(len(rs) / ((b - a) / FPS / 60.0), 3),
                  "wrist_stops_after_shoulder": A.summary(stops)}
    return out


def measure(names, pos, rot, rng=None, trim=15, parts=("a01", "a20", "a02", "a08", "a18", "a09")):
    """all the measures on one sequence; rng = (a, b) steps, or None for dance_range.  (res, places)"""
    part = A.part_speeds(np.asarray(pos), np.asarray(rot), list(names))
    if rng is None:
        rng = dance_range(part, trim)
    if rng is None:
        return {"skipped": "no dance range"}, {}
    a, b = rng
    res = {"range": [a, b], "seconds": round((b - a) / FPS, 2)}
    ev = {"part": part}
    if "a01" in parts:
        res["a01"], ev["a01"] = m_a01(part, a, b)
    if "a20" in parts:
        res["a20"], ev["a20"] = m_a20(names, pos, rot, a, b)
    if "a02" in parts:
        res["a02"] = m_a02(names, pos, a, b)
    if "a08" in parts:
        res["a08"], ev["a08"] = m_a08(names, pos, a, b)
    if "a18" in parts:
        res["a18"], ev["a18"] = m_a18(names, pos, rot, a, b)
    if "a09" in parts:
        res["a09"] = m_a09(names, rot, a, b)
    return res, ev
