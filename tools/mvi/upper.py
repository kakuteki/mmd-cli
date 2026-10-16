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
"""
import numpy as np

from . import base

CONCEPT = "upper"


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
        rows.append(base.row("upper.head_stops_per_min", "頭の止まり", hd["stop"]["per_min"], "/min", src))
        ref = base.reference("upper.head_stop_ms")
        if ref:
            edge, scale = base.people_edge(ref, -1)
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
                events.append(base.event(mid, f, g, deg, "度/秒", 0.0, hi,
                                         "%s が %.0f 度/秒から 5 コマ以内に止まり、%d コマ止まったまま" % (bone, deg, hold)))
    ub = base.tool("upper_body_check")
    names, pos, rot = m.v.pack()
    rng = res.get("range")
    if rng:
        parts = ub.from_pack(names, pos, rot)
        u = ub.measure(parts, (rng[0], rng[1] - 1))
        src = "tools/upper_body_check.py（review_wbbalance の測り、pack の骨）"
        rows.append(base.row("upper.head_pelvis_xcorr_peak", "頭と骨盤の速い動きの相互相関の山（1.5〜6 Hz）", (u.get("lag") or {}).get("peak"), "", src))
        loc = u.get("local") or {}
        w = loc.get("weighted") or {}
        rows.append(base.row("upper.local_follow_p50", "2 秒窓の頭の付き方 中央値", w.get("p50"), "", src))
        rows.append(base.row("upper.local_follow_carried", "2 秒窓で頭が骨盤に運ばれる窓の割合（> 0.75）", loc.get("share_carried"), "", src))
    return {"rows": rows, "events": events, "series": series}
