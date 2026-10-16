"""上体: how the head and the chest ride on the hips, and how the head stops.

* 頭と胸の付き方 (tools/wb_dynamics.follow_slope as wbbalance read it): the slope of the head's (the chest's, the arms')
  horizontal acceleration (6 Hz) regressed on the pelvis's: 1 = carried with the hips, 0 = stays.
* 頭の止まり (a08 s1, the human baseline's range): the head's stops (a deep minimum of its step speed after a fast phase
  of 0.6 m/s or more) and the time the speed takes from 80 to 20 % of its drop.  Places: the stops sharper than
  people's lower quartile.
* 頭・上半身の急停止 (a18): the head's (the upper body's) angular speed falling from over 300 (250) degrees/s to under 40
  within 5 frames.  Places: each one.
* 頭の加速度 99 % 点 (a18).
* 頭と骨盤の速い動き (tools/upper_body_check.py, review_wbbalance's independent measures, on the pack): the peak of the
  cross-correlation of the head's (the eyes' middle) and the pelvis's horizontal velocities band-passed 1.5-6 Hz, and
  the 2 s windows' slopes of the head on the pelvis (their weighted median, the share of windows carried, > 0.75).
  Places: the stretches of consecutive windows carried (the hips moving: a window's weight at least a quarter of the
  median, as local_follow's worst), longer than people's (their pooled stretches' 90 % point, 4.5 s; 99 % 8.2 s,
  human.json's "event"): the head riding on the hips for seconds, which the song's shares hardly show when the rest of
  the song is not carried.
"""
import numpy as np

from . import base

CONCEPT = "upper"
CARRIED = 0.75                  # upper_body_check.local_follow: a window whose slope passes this is carried
WIN, HOP = 60, 15               # frames: its windows


def local_windows(head, pelvis, rng, fs=30.0, win=WIN, hop=HOP, cutoff_hz=6.0):
    """upper_body_check.local_follow's 2 s windows one by one (the same expressions): (starts, slopes, weights), the
    weight of a window the hips' power in it"""
    D = base.tool("wb_dynamics")
    ah = D.diff2(D.lowpass(np.asarray(head, dtype=np.float64), cutoff_hz, fs), fs)[:, [0, 2]]
    ap = D.diff2(D.lowpass(np.asarray(pelvis, dtype=np.float64), cutoff_hz, fs), fs)[:, [0, 2]]
    a, b = rng
    starts, slopes, weights = [], [], []
    for st in range(a + 3, b - 3 - win + 2, hop):
        x, p = ah[st:st + win], ap[st:st + win]
        den = float(np.sum(p * p))
        if den <= 0:
            continue
        starts.append(st)
        slopes.append(float(np.sum(x * p)) / den)
        weights.append(den)
    return np.array(starts, int), np.array(slopes, float), np.array(weights, float)


def carried_runs(starts, slopes, weights, win=WIN, hop=HOP):
    """[(first frame, last frame, windows, median slope)] of the stretches of consecutive windows (hop apart) carried,
    among the windows where the hips move (weight at least a quarter of the median)"""
    if not len(starts):
        return []
    car = (weights >= 0.25 * np.median(weights)) & (slopes > CARRIED)
    out, i = [], 0
    while i < len(starts):
        if not car[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(starts) and car[j + 1] and starts[j + 1] - starts[j] == hop:
            j += 1
        out.append((int(starts[i]), int(starts[j] + win - 1), j - i + 1, float(np.median(slopes[i:j + 1]))))
        i = j + 1
    return out


def measure(m):
    rows, events, series = [], [], {}
    rep, _ = m.wb()
    src = "tools/wb_dynamics.py の follow_slope（wbbalance の MV の測り）"
    fol = rep.get("follow", {})
    rows.append(base.row("upper.head_follow", "頭が骨盤の水平の動きに付く傾き（1 = 一緒）", (fol.get("head") or {}).get("slope"), "", src))
    rows.append(base.row("upper.chest_follow", "胸（上部の胴）の傾き", (fol.get("chest") or {}).get("slope"), "", src))
    rows.append(base.row("upper.arms_follow", "腕の傾き", (fol.get("arms") or {}).get("slope"), "", src))
    rows.append(base.row("upper.head_follow_2_4hz", "頭の 2〜4 Hz の応答", (fol.get("head") or {}).get("2-4Hz"), "", src))

    res, ev = m.hb()
    if "a08" in res:
        hd = res["a08"]["頭"]
        src = "a08 s1（頭の止まり 80→20 %、human_baseline の範囲）"
        rows.append(base.row("upper.head_stop_ms", "頭の止まり 80→20 % の時間（中央値）", hd["stop"]["t80_20_med_ms"], "ms", src,
                             stops=hd["stop"]["n"]))
        ref = base.reference("upper.head_stop_ms")
        if ref:
            edge, scale = base.event_rule("upper.head_stop_ms", *base.people_edge(ref, -1))
            for imin, ipk, ms, vpk in ev["a08"]["頭"]["stops"]:
                if np.isfinite(ms) and ms < edge:
                    events.append(base.event("upper.head_stop_ms", ipk, imin, ms, "ms", edge, scale,
                                             "頭が %.2f m/s から %.0f ms で止まる" % (vpk, ms), side=-1))
    if "a18" in res:
        a18 = res["a18"]
        src = "a18 body_motion（急停止 = 角速度が 5 コマ以内に 300（上半身 250）度/秒超から 40 未満へ）"
        rows.append(base.row("upper.head_sudden_stops_per_min", "頭の急停止", a18["sudden_stops_head_per_min"], "/min", src))
        rows.append(base.row("upper.upper_sudden_stops_per_min", "上半身の急停止", a18["sudden_stops_upper_per_min"], "/min", src))
        rows.append(base.row("upper.head_acc_p99", "頭の加速度 99 % 点", a18["head_acc"]["p99"], "u/s²", "a18 body_motion"))
        for bone, mid, hi in (("頭", "upper.head_sudden_stops_per_min", 300.0), ("上半身", "upper.upper_sudden_stops_per_min", 250.0)):
            for f, g, hold, deg in ev["a18"]["sudden_stops"][bone]:
                events.append(base.event(mid, f, g, deg, "度/秒", hi, hi,
                                         "%s が %.0f 度/秒から 5 コマ以内に止まり、%d コマ止まったまま" % (bone, deg, hold)))
    ub = base.tool("upper_body_check")
    names, pos, rot = m.v.pack()
    rng = res.get("range")
    if rng:
        parts = ub.from_pack(names, pos, rot)
        u = ub.measure(parts, (rng[0], rng[1] - 1))
        src = "tools/upper_body_check.py（review_wbbalance の測り、pack の骨）"
        rows.append(base.row("upper.head_stops_per_min", "頭の止まり（a08 と同じ決め方）", (u.get("stops") or {}).get("per_min"), "/min", src))
        rows.append(base.row("upper.head_pelvis_xcorr_peak", "頭と骨盤の速い動きの相互相関の山（1.5〜6 Hz）", (u.get("lag") or {}).get("peak"), "", src))
        loc = u.get("local") or {}
        w = loc.get("weighted") or {}
        rows.append(base.row("upper.local_follow_p50", "2 秒窓の頭の付き方 中央値", w.get("p50"), "", src))
        rows.append(base.row("upper.local_follow_carried", "2 秒窓で頭が骨盤に運ばれる窓の割合（> 0.75）", loc.get("share_carried"), "", src))
        st, sl, wt = local_windows(ub.eyes(parts), parts["下半身"][0], (rng[0], rng[1] - 1))
        edge, scale = base.event_rule("upper.local_follow_carried", 4.0, 4.0)
        for a, b, n, med in carried_runs(st, sl, wt):
            sec = (b - a + 1) / base.FPS
            if sec > edge:
                events.append(base.event("upper.local_follow_carried", a, b, sec, "s", edge, scale,
                                         "頭が骨盤に運ばれる 2 秒窓が %d 続く（傾きの中央値 %.2f、1 = 一緒）" % (n, med)))
    return {"rows": rows, "events": events, "series": series}
