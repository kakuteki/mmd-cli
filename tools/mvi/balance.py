"""重心とバランス: where the weight is over the feet.

* ZMP (tools/wb_dynamics.py as wbbalance ran it on the MV): the body's segments (de Leva 1996, females, 16 segments) from
  the dance on the model (tools/balance_layer.Body), low-passed at 6 Hz; the base of support from the shoes' lower shell
  as MMD bends them (a shoe's point within 1.2 cm of the floor touches).  The share of the frames with a foot on the
  floor whose ZMP lies inside the base of support; the share of single-support frames; the median margin of the ZMP on
  one foot.  Places: the stretches outside whose tilt (the turn the floor's missing push would give the body) is past
  people's 99 % point of every stretch of every sequence.
* 片足立ちの重心の左右 (a05 s15): on one foot with the other 5 cm or more up, the COM's sideways offset from the
  standing foot's centre (+ towards the lifted foot), the median.
* 動きながらの片足立ち (the human baseline's p24): the same offset from the support capsule's middle on the single-
  support frames that are not a still stance (the COM under 5 cm/s for 0.3 s), and the XcoM's sideways margin there
  (4 cm less the XcoM's sideways offset: + inside the foot's sideways reach).
* 着地の XcoM (a05 s15): the XcoM's sideways offset from the landing foot at each touchdown, the median.
* 重心が立ち足の外 (a05 s11): the share of the single support with the other foot 5 cm up whose COM lies more than 2 cm
  outside the standing foot's capsule; the phases held outside (a05 s14: the XcoM outside that does not fall away).
"""
import numpy as np

from . import base

CONCEPT = "balance"


def measure(m):
    rows, events, series = [], [], {}
    rep, arr = m.wb()
    src = "tools/wb_dynamics.py（wbbalance の MV の測り: balance_layer.Body、MMD が曲げた靴で支持基底面、接地 1.2 cm、6 Hz）"
    z = rep["zmp"]
    rows.append(base.row("balance.zmp_inside_pct", "ZMP が支持基底面の中（床に足があるコマ）",
                         None if z["inside_share"] is None else 100.0 * z["inside_share"], "%", src, frames=z["frames"]))
    sup = rep["support"]
    rows.append(base.row("balance.single_share_pct", "片足のコマ", 100.0 * sup["single"] / max(1, sup["frames"]), "%", src))
    rows.append(base.row("balance.zmp_margin_single_cm", "片足のコマの ZMP の余裕 中央値（+ 中）",
                         (z["margin_cm_single"] or {}).get("p50"), "cm", src))
    rows.append(base.row("balance.zmp_tilt_deg_per_min", "支えの外の区間で体が倒れたはずの傾き 合計", z["tilt_deg_per_min"], "度/min", src))
    p99, scale = base.event_rule("balance.zmp_inside_pct", 32.7, 32.7)
    for r in z["outside_runs"]:
        if r["tilt_deg"] > p99:
            # the stretch's tilt lies above its edge (side +1); such stretches make the share of the ZMP inside go down
            # (toward -1) and the tilt a minute go up (also)
            events.append(base.event("balance.zmp_inside_pct", r["first"], r["last"], r["tilt_deg"], "度", p99, scale,
                                     "ZMP が支えの外 %.1f cm、倒れたはずの傾き %.1f 度（人の区間の 99 %% 点 %.1f 度）、支え %s"
                                     % (r["depth_cm"], r["tilt_deg"], p99, r["support"]), toward=-1,
                                     also=[("balance.zmp_tilt_deg_per_min", 1)]))
    margin = arr["margin"] * 100.0
    series["zmp_margin"] = {"label": "ZMP の支持基底面からの余裕 cm（+ 中）", "unit": "cm", "y": margin, "lo": 0.0, "hi": None,
                            "ids": ["balance.zmp_inside_pct", "balance.held_outside_per_min"]}

    a5 = m.a05()
    f = a5["rows"]
    src = "a05 s15（片足立ち: 他方の足が 5 cm 以上上、重心は a05 の部位の重心）"
    rows.append(base.row("balance.com_lateral_cm", "片足立ちの重心の左右のずれ 中央値（+ 上げた足の側）", f["single_lat_median_cm"], "cm", src,
                         frames=f["single_frames"]))
    rows.append(base.row("balance.touchdown_xcom_cm", "着地の XcoM の左右のずれ 中央値", f["td_xcom_median_cm"], "cm", "a05 s15（着地のコマ）"))
    rows.append(base.row("balance.com_outside_2cm_pct", "片足立ちで重心が立ち足の外 2 cm 超", f["com_outside_2cm_pct(lifted>=5cm)"], "%",
                         "a05 s11（他方の足が 5 cm 以上上）"))
    rows.append(base.row("balance.held_outside_per_min", "足の外に留まる片足立ち（a05 s14 の held）", f["held_per_min"], "/min", "a05 s14"))
    p24 = a5["p24"] or {}
    mv = p24.get("not_still_v5_L9") or {}
    st = p24.get("still_v5_L9") or {}
    src = "human_baseline の p24（止まった片足立ち = 重心 5 cm/s 未満が 0.3 秒以上、それ以外が動きながら）"
    rows.append(base.row("balance.moving_com_lateral_cm", "動きながらの片足立ちの重心の左右（支えの中心から）", mv.get("lat_cap_median"), "cm", src,
                         frames=mv.get("frames")))
    rows.append(base.row("balance.moving_mos_ml_cm", "動きながらの片足立ちの XcoM の横の余裕", mv.get("mos_ml_median"), "cm", src))
    rows.append(base.row("balance.still_com_lateral_cm", "止まった片足立ちの重心の左右（支えの中心から）", st.get("lat_cap_median"), "cm", src,
                         phases=st.get("phases"), frames=st.get("frames"),
                         spans=[[a, b, "左" if side == 0 else "右"] for a, b, side in st.get("_spans", [])]))
    s15 = a5["_s15"]
    full = np.full(a5["frames"], np.nan)
    if len(s15["single_frames"]):
        full[s15["single_frames"]] = s15["single"]
    series["com_lateral"] = {"label": "片足立ちの重心の左右のずれ cm（a05 s15、+ 上げた足の側）", "unit": "cm", "y": full,
                             "ref": "balance.com_lateral_cm", "ids": ["balance.com_lateral_cm"]}
    for h in a5["s14"]["_held"]:
        events.append(base.event("balance.held_outside_per_min", h["start"], h["end"], h["xcom_out_start"], "cm", 2.0, 4.0,
                                 "%s 足の片足立ちで XcoM が足の外 %.1f cm のまま %.2f 秒" % ("左" if h["side"] == "L" else "右",
                                                                                   h["xcom_out_start"], h["T_s"])))
    return {"rows": rows, "events": events, "series": series}
