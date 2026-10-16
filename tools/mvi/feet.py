"""足: the feet on the floor.

* 滑り (a05 s04, review_floaty's rv_slip): a foot is on the floor where its ankle or toe IK target is within 4 mm of its
  rest height; while it stays on, the slowest point of its heel-to-toe line (of the part that touches) moves along the
  floor.  The contacts that slip more than 10 cm (and 3 cm) a minute, the slip's path a minute, the share of the contact
  steps faster than 20 cm/s.  Places: each contact that slips more than 10 cm.
* 床の下 (tools/sink_check.py): the shoe's lowest point (the shoe's vertices skinned on the legs as MMD's IK solves them)
  more than 1 mm under the floor (the shoes' lowest point at rest).  Places: the runs.
* ひざ (a05 s06, the human baseline's p22): the knee's bend gained within 0.2 s of a touchdown, and the share of the
  contact frames with the knee nearly straight (under 5 degrees; the knee of the two-bone leg from the hip to the
  foot IK).  Places: the touchdowns gaining more than people's upper quartile; the runs of nearly straight knees.
* IK の届かないコマ (tools/leg_ik.py, the balance layer's IK_MISS): frames where a supporting shoe (lowest point under
  1.6 cm) has its ankle more than 4 mm from the foot IK's goal as MMD solves it; with a reference dance, those 1 mm and
  more farther than in the dance (a new miss, the balance layer's IK_WORSE).  Places: the runs of new misses.
"""
import numpy as np

from . import base

CONCEPT = "feet"
UNDER_CM = 0.1
SUPPORT_CM = 1.6
IK_MISS = 0.05                  # units (4 mm): tools/balance_layer.IK_MISS
IK_WORSE = 0.0125               # units (1 mm): tools/balance_layer.IK_WORSE


def measure(m):
    rows, events, series = [], [], {}
    a5 = m.a05()
    f = a5["rows"]
    F = a5["frames"]
    src = "a05 s04（足ＩＫ・つま先ＩＫの高さで接地、4 mm）"
    rows.append(base.row("feet.slide10_per_min", "10 cm 以上滑る接地（左右計）", f["slips10_per_min"], "/min", src + "、review_floaty の rv_slip"))
    rows.append(base.row("feet.slide3_per_min", "3 cm 超滑る接地（左右計）", f["slip3_per_min"], "/min", src))
    rows.append(base.row("feet.slide_path_cm_per_min", "滑りの道のり（左右計）", f["slip_path_cm_per_min"], "cm/min", src + "、rv_slip"))
    rows.append(base.row("feet.slide_fast_share", "接地のうち 20 cm/s より速く滑る歩みの割合", f["share_slip20"], "", src + "、rv_slip"))
    edge, scale = base.event_rule("feet.slide10_per_min", 10.0, 10.0)
    for side, rows04 in a5["_s04_rows"].items():
        for r in rows04:
            if r["slip_path_cm"] > max(10.0, edge):
                events.append(base.event("feet.slide10_per_min", r["start"], r["end"], r["slip_path_cm"], "cm", edge, scale,
                                         "%s 足が接地のまま %.1f cm 滑る（%d コマ）" % (side, r["slip_path_cm"], r["frames"])))

    sh = m.shoes()
    floor_y = float(sh["floor_y"])
    under_total = 0
    deepest = 0.0
    for tag, side in (("left", "左"), ("right", "右")):
        h = (sh["low_" + tag] - floor_y) * base.UNIT_CM
        under = h < -UNDER_CM
        under_total += int(under.sum())
        deepest = max(deepest, float(-h.min()) if len(h) else 0.0)
        for a, b in base.runs(under):
            k = a + int(np.argmin(h[a:b + 1]))
            events.append(base.event("feet.under_floor_frames", a, b, float(-h[k]), "cm", UNDER_CM, 0.5,
                                     "%s の靴が床の下 %.2f cm" % (side, -h[k])))
        series["shoe_" + tag] = {"label": "%s の靴の最も低い点 cm（床から）" % side, "unit": "cm", "y": h, "lo": 0.0, "hi": None,
                                 "ids": ["feet.under_floor_frames", "feet.slide10_per_min", "feet.ik_new_miss_frames", "feet.knee_straight_pct",
                                         "feet.knee_gain_deg"]}
    rows.append(base.row("feet.under_floor_frames", "靴が床の下へ入るコマ（1 mm 超、左右計）", under_total, "frames",
                         "tools/sink_check.py（靴の頂点を MMD の IK で解いた脚に皮付け）", deepest_cm=round(max(deepest, 0.0), 3)))

    src = "a05 s06（着地後 0.2 秒のひざの曲がりの増え、左右の中央値の平均）"
    rows.append(base.row("feet.knee_gain_deg", "着地後 0.2 秒のひざの曲がりの増え", f["knee_gain_mean"], "度", src))
    ref = base.reference("feet.knee_gain_deg")
    e6 = a5["_ev"]
    if ref:
        edge, scale = base.event_rule("feet.knee_gain_deg", *base.people_edge(ref, 1))
        for lab in ("L", "R"):
            for td, g in zip(e6["final_%s_td" % lab], e6["final_%s_kgain" % lab]):
                if g > edge:
                    events.append(base.event("feet.knee_gain_deg", td, min(td + 6, F - 1), g, "度", edge, scale,
                                             "%s 足の着地の後にひざが %.1f 度曲がる" % ("左" if lab == "L" else "右", g)))
    p22 = a5["p22"]
    rows.append(base.row("feet.knee_straight_pct", "接地中にひざがほぼまっすぐ（5 度未満）", p22["contact_straight_lt5_pct"], "%",
                         "human_baseline の p22（a05 s04 のひざ）"))
    z = a5["_z"]
    for side in ("左", "右"):
        straight = z[side + "_contact"] & (z[side + "_knee"] < 5.0)
        for a, b in base.runs(straight, 2):
            k = a + int(np.argmin(z[side + "_knee"][a:b + 1]))
            events.append(base.event("feet.knee_straight_pct", a, b, float(z[side + "_knee"][k]), "度", 5.0, 5.0,
                                     "%s 足が床でひざ %.1f 度（%d コマ）" % (side, z[side + "_knee"][k], b - a + 1), side=-1))

    src = "tools/leg_ik.py（MMD の IK のとおりに脚を解く）。床の靴（最も低い点が 1.6 cm 未満）で足首が目標から 4 mm 超"
    miss_total, new_total = 0, 0
    ref_sh = m.shoes("reference")
    for tag, side in (("left", "左"), ("right", "右")):
        sup = (sh["low_" + tag] - floor_y) * base.UNIT_CM < SUPPORT_CM
        reach = sh["reach_" + tag]
        miss = sup & (reach > IK_MISS)
        miss_total += int(miss.sum())
        if ref_sh is not None:
            n = min(len(reach), len(ref_sh["reach_" + tag]))
            new = np.zeros(len(reach), bool)
            new[:n] = miss[:n] & (reach[:n] > ref_sh["reach_" + tag][:n] + IK_WORSE)
            new_total += int(new.sum())
            for a, b in base.runs(new):
                k = a + int(np.argmax(reach[a:b + 1]))
                events.append(base.event("feet.ik_new_miss_frames", a, b, float(reach[k] * base.UNIT_CM), "cm",
                                         IK_MISS * base.UNIT_CM, 1.0,
                                         "%s 足ＩＫに %.2f cm 届かない（踊り %.2f cm）" % (side, reach[k] * base.UNIT_CM, ref_sh["reach_" + tag][k] * base.UNIT_CM)))
    rows.append(base.row("feet.ik_miss_floor_frames", "床の足で MMD の IK が足ＩＫに届かないコマ（左右計）", miss_total, "frames", src))
    if ref_sh is not None:
        rows.append(base.row("feet.ik_new_miss_frames", "同 踊りより 1 mm 以上遠い（新しい届かないコマ）", new_total, "frames", src + "、基準の踊りと比べる"))
    else:
        rows.append(base.row("feet.ik_new_miss_frames", "同 踊りより 1 mm 以上遠い（新しい届かないコマ）", None, "frames",
                             src + "。基準の踊り（reference）が無いので測らない"))
    return {"rows": rows, "events": events, "series": series}
