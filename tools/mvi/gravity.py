"""重力感: does the body fall like a body?  The measures of the work that took it in (floaty, balance-v2/v3, the human
baseline), each against people (FineDance K-pop, choreography and jazz) or the dance itself:

* 支えの無い浮き (a05 s11 hover support): neither foot within 0.4 cm (a05's contact, 4 mm) of the floor and the lower one
  under 4 cm: the body held by nothing.  The share of frames and the runs of 6 frames or more a minute.  Places: the
  runs of 6 frames or more.
* 宙 (floaty fq): both feet over 2.5 cm for 4 frames or more; the pelvis's parabola in it.  The share of the air whose
  pelvis falls slower than half of gravity (61.25 units/s^2).  Places: those air phases.
* the pelvis's descents and apexes (fq): a 3 cm drop's time over the free fall's, the strongest downward acceleration
  in it, the catch at its bottom, the apex's dwell within 1 cm, the beat's range, the vertical speed's 95 % point and its
  share over 3 Hz.
* a18 センターの下向き加速度 (the human baseline's addition to a18): グルーブ's second gradient over the dance range, its
  largest downward value and the share past 98 units/s^2.  Places: the runs past 98.
* 跳びの頂き / 拍の上の窪み (balance-v3's q1_vertical, against the reference dance): the jumps whose top is 2 cm or more
  lower than the dance's and the dips on the beat under 0.8 of the dance's drop.  Places: each of them.
* 着地の沈み (a05 s06): the pelvis's lowest point within 0.2 s of a touchdown, the median of each foot averaged.
  Places: the touchdowns deeper than people's lower quartile.
"""
import numpy as np

from . import base

CONCEPT = "gravity"


def measure(m):
    rows, events, series = [], [], {}
    a5 = m.a05()
    f = a5["rows"]
    F = a5["frames"]
    hs = a5["s11"]["hover_support"]
    src_s11 = "a05 s11（human_baseline の ported/a05h、floaty の s11_collect の数え方）"
    rows.append(base.row("gravity.hover_pct", "支えの無い浮き（どの足も床に無く、低い方が 4 cm 未満）", f["hover_support_pct"], "%",
                         src_s11, frames=hs["frames"]))
    rows.append(base.row("gravity.hover_runs6_per_min", "支えの無い浮きが 6 コマ以上続く", f["hover_support_runs6_per_min"], "/min",
                         src_s11, runs=hs["runs_>=6frames"]))
    low = hs["_lower_cm"]
    edge, scale = base.event_rule("gravity.hover_runs6_per_min", 5.0, 6.0)
    for a, b in hs["_runs"]:
        n = b - a + 1
        if n > edge:
            events.append(base.event("gravity.hover_runs6_per_min", a, b, n, "コマ", edge, scale,
                                     "%d コマ続く（低い方の足 %.1f cm、中央値）" % (n, float(np.median(low[a:b + 1])))))
    series["hover"] = {"label": "支えの無い浮き（低い方の足の高さ cm、浮きのコマだけ）", "unit": "cm",
                       "y": np.where(hs["_mask"], low, np.nan), "lo": 0.4, "hi": 4.0,
                       "ids": ["gravity.hover_runs6_per_min", "gravity.hover_pct"]}

    q = m.fq()
    if q is not None:
        src = "floaty の fq.py（下半身の高さ、floaty の範囲）"
        for mid, name, key, unit in (
                ("gravity.air_per_min", "宙（両足が 2.5 cm 超、4 コマ以上）", "air_per_min", "/min"),
                ("gravity.air_slow_share", "宙のうち腰の落ち方が重力の半分より遅い割合", "air_frac_slower_half_g", ""),
                ("gravity.air_acc_median", "宙の腰の加速度 中央値", "air_acc_median", "u/s²"),
                ("gravity.desc_ratio_median", "腰の下がり（3 cm 以上）の時間 / 自由落下の時間", "desc_ratio_median", ""),
                ("gravity.desc_peak_down_median", "下がりの中の下向き加速度の最大（中央値）", "desc_peak_down_median", "u/s²"),
                ("gravity.desc_brake_median", "下がりの底の受け止め（上向き加速度、中央値）", "desc_brake_median", "u/s²"),
                ("gravity.apex_dwell_ms", "頂きの滞空（頂きから 1 cm 以内）", "apex_dwell_median_ms", "ms"),
                ("gravity.beat_range_cm", "拍（0.43 秒）の中の腰の上下の幅", "beat_range_median_cm", "cm"),
                ("gravity.vy_p95", "腰の上下の速さ 95 % 点", "vy_abs_p95", "cm/s"),
                ("gravity.vy_above_3hz_pct", "腰の上下の速さの 3 Hz 超の割合", "vy_power_above_3hz_pct", "%")):
            rows.append(base.row(mid, name, q.get(key), unit, src, range=q["range"]))
        for e in q["events"]["air"]:
            if e["acc"] > -61.25:
                events.append(base.event("gravity.air_slow_share", e["first"], e["last"], e["acc"], "u/s²", -61.25, 61.25,
                                         "宙 %d コマ、腰の放物線の加速度 %.0f（重力 -122.5）" % (e["frames"], e["acc"])))
        s = q["series"]
        series["pelvis_acc"] = {"label": "腰（下半身）の上下の加速度 u/s²（+ 上）", "unit": "u/s²", "y": s["acc"],
                                "lo": -122.5, "hi": None,
                                "ids": ["gravity.air_slow_share", "gravity.landing_sink_cm", "gravity.jump_apex_lowered",
                                        "gravity.beat_dips_weak"]}

    res, ev = m.hb()
    if "a18" in res:
        ay = res["a18"]["center_ay"]
        src = "a18 body_motion（グルーブの高さの 2 階の勾配、human_baseline の hb_measures の範囲）"
        rows.append(base.row("gravity.centre_down_max", "センターの下向き加速度の最大", ay["min"], "u/s²", src, range=res["range"]))
        rows.append(base.row("gravity.centre_down_gt98_pct", "センターの下向き加速度が 98 を越えるコマ", ay["down_gt_98u_pct"], "%", src))
        a = ev["a18"]["first"]
        acc = ev["a18"]["center_ay"]
        edge, scale = base.event_rule("gravity.centre_down_gt98_pct", -98.0, 28.0)
        for r0, r1 in base.runs(acc < -98.0):
            k = r0 + int(np.argmin(acc[r0:r1 + 1]))
            if acc[k] < edge:
                events.append(base.event("gravity.centre_down_gt98_pct", a + r0, a + r1, float(acc[k]), "u/s²", edge, scale,
                                         "%.2f 秒にセンターが %.0f u/s² で落ちる（重力 -122.5）" % ((a + k) / base.FPS, acc[k]), side=-1))
        full = np.full(m.v.frames, np.nan)
        full[a:a + len(acc)] = acc
        series["centre_ay"] = {"label": "センター（グルーブ）の上下の加速度 u/s²（a18、+ 上）", "unit": "u/s²", "y": full,
                               "lo": -98.0, "hi": None,
                               "ids": ["gravity.centre_down_gt98_pct", "gravity.centre_down_max"]}

    vt = m.vertical()
    src = "balance-v3 の q1_vertical（基準の踊りと比べる）"
    if vt is not None:
        js = vt["summary"]["jumps"]
        rows.append(base.row("gravity.jump_apex_lowered", "跳びの頂きが踊りより 2 cm 以上下がる（回）", js["top_lowered_over_2cm"], "回",
                             src, jumps=js["n"]))
        for j in vt["jumps"]:
            if j["top_cm"] < -2.0:
                events.append(base.event("gravity.jump_apex_lowered", j["first"], j["last"], j["top_cm"], "cm", -2.0, 2.0,
                                         "跳びの頂き %.1f cm 低い" % j["top_cm"], side=-1))
        bt = vt["summary"]["beat"]
        rows.append(base.row("gravity.beat_dips_weak", "拍の上の窪みが踊りの 8 割を切る（回）", bt["drop_ratio_under_0.8"], "回", src,
                             dips=bt["n"]))
        for d in vt["dips"]:
            if d["beat"] and d["ref"]["drop_cm"] > 0:
                ratio = d["ver"]["drop_cm"] / max(d["ref"]["drop_cm"], 1e-9)
                if ratio < 0.8:
                    events.append(base.event("gravity.beat_dips_weak", d["f"], d["f"], ratio, "比", 0.8, 0.2,
                                             "窪み %.1f cm（踊り %.1f cm）" % (d["ver"]["drop_cm"], d["ref"]["drop_cm"]), side=-1))
    else:
        rows.append(base.row("gravity.jump_apex_lowered", "跳びの頂きが踊りより 2 cm 以上下がる（回）", None, "回",
                             src + "。基準の踊り（reference）が無いので測らない"))
        rows.append(base.row("gravity.beat_dips_weak", "拍の上の窪みが踊りの 8 割を切る（回）", None, "回",
                             src + "。基準の踊り（reference）が無いので測らない"))

    src = "a05 s06（着地後 0.2 秒の骨盤の沈み、左右の中央値の平均）"
    rows.append(base.row("gravity.landing_sink_cm", "着地後 0.2 秒の骨盤の沈み", f["sink_mean"], "cm", src))
    ref = base.reference("gravity.landing_sink_cm")
    if ref:
        edge, scale = base.event_rule("gravity.landing_sink_cm", *base.people_edge(ref, -1))
        e6 = a5["_ev"]
        for lab in ("L", "R"):
            for td, sink in zip(e6["final_%s_td" % lab], e6["final_%s_sink_cm" % lab]):
                if sink < edge:
                    events.append(base.event("gravity.landing_sink_cm", td, min(td + 6, F - 1), sink, "cm", edge, scale,
                                             "%s 足の着地の後 %.1f cm 沈む" % ("左" if lab == "L" else "右", sink), side=-1))
    return {"rows": rows, "events": events, "series": series}
