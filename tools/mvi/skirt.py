"""スカートの危なさ: a pelvis that falls faster than gravity while a foot holds the body up throws the skirt up (the skirt's
research, 2026-10-15: MMD's physics lets the cloth past level when the waist's downward acceleration passes gravity).
The balance layer bounds it at 122 units/s^2 on the floor (HANDOVER 2026-10-16); in the air (neither shoe supporting for
4 frames or more) the dance's own fall is kept (balance-v3).

Measured as tools/sink_check.py reads it: the downward acceleration (30 fps second differences, + down) of 下半身's and
センター's world heights above the legs, on the floor: the frames that are not the air (sink_check's air: neither shoe's
lowest point under 1.6 cm for 4 frames or more).  Counted: the frames past 122 by more than 0.5 (the balance layer's
report's count) on the floor, either bone (and each bone apart in by_bone).
Places: the runs of those frames, with the largest value; the frames in the air are listed apart (not judged: the
dance's own fall, kept on purpose).
"""
import numpy as np

from . import base

CONCEPT = "skirt"
BOUND = 122.0
TOL = 0.5


def measure(m):
    rows, events, series = [], [], {}
    sc = base.tool("sink_check")
    sh = m.shoes()
    air = np.asarray(sh["air"], bool)
    a_low, a_cen = sc.down_acc(sh["lower_body_y"]), sc.down_acc(sh["centre_y"])
    acc = np.maximum(a_low, a_cen)
    past = acc > BOUND + TOL
    floor = past & ~air
    src = "tools/sink_check.py（下半身・センターの高さの 2 階差、脚は MMD の IK、床 = 宙（両方の靴が 1.6 cm 以上を 4 コマ以上）でないコマ）"
    rows.append(base.row("skirt.floor_over122_frames", "床のコマで腰の下向きの加速度が 122 を越える", int(floor.sum()), "frames", src,
                         max_floor=round(float(acc[~air].max()) if (~air).any() else 0.0, 1),
                         by_bone={"下半身": int(((a_low > BOUND + TOL) & ~air).sum()), "センター": int(((a_cen > BOUND + TOL) & ~air).sum())}))
    rows.append(base.row("skirt.floor_max", "床のコマの腰の下向きの加速度の最大", float(acc[~air].max()) if (~air).any() else 0.0, "u/s²", src))
    rows.append(base.row("skirt.air_over122_frames", "宙のコマで 122 を越える（踊りの落ち方、判じない）", int((past & air).sum()), "frames", src,
                         max_air=round(float(acc[air].max()), 1) if air.any() else None))
    for a, b in base.runs(floor):
        k = a + int(np.argmax(acc[a:b + 1]))
        events.append(base.event("skirt.floor_over122_frames", a, b, float(acc[k]), "u/s²", BOUND, 12.2,
                                 "床で腰が %.0f u/s² で落ちる（上限 122）" % acc[k]))
    series["pelvis_down"] = {"label": "腰の下向きの加速度 u/s²（下半身・センターの大きい方、+ 下）", "unit": "u/s²",
                             "y": acc, "lo": None, "hi": BOUND, "air": air,
                             "ids": ["skirt.floor_over122_frames"]}
    return {"rows": rows, "events": events, "series": series}
