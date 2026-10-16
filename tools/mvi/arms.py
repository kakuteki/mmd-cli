"""腕と指: the arm chain's timing and the fingers' amount of motion.

* 関節の遅れ (a09 s04, the human baseline's range): per side, the lag (frames, + the distal joint later) of the peak of the
  windowed cross-correlation of adjacent joints' angular speeds: upper arm -> elbow, elbow -> wrist, wrist -> finger
  (the analysts' joints: the elbow holds 腕捩, the wrist 手捩).  The median over the windows.  And the arm's rests.
* 指の速さ (review_fingers_lag's s11_mmd_chain, contents B: wrist = 手捩 -> 手首, finger = 手首 -> 中指３): the median
  angular speed over every frame of the finger joint and of the wrist joint, raw, and the finger / wrist ratio; people
  the same on FineDance (the middle finger's three joints in the hand, the wrist joint without twist).
* 手首の細かい脈 (a02, a08): the share of the right wrist's velocity power in 3-6 Hz and over 8 Hz.
"""
import numpy as np

from . import analysts as A
from . import base

CONCEPT = "arms"


def finger_speeds(m):
    """per side: the median speeds (deg/s) of the wrist (手捩 -> 手首) and of the finger (手首 -> 中指３), every frame"""
    out = {}
    for s, jp in (("L", "左"), ("R", "右")):
        try:
            _, qt = m.v.bone(jp + "手捩")
            _, qw = m.v.bone(jp + "手首")
            _, qf = m.v.bone(jp + "中指３")
        except ValueError:
            return None
        qt, qw, qf = (np.asarray(x, dtype=np.float64) for x in (qt, qw, qf))
        wr = A.angular_speed(A.continuous(A.relative(qt, qw)), fps=30)
        fi = A.angular_speed(A.continuous(A.relative(qw, qf)), fps=30)
        out[s] = {"wrist": float(np.median(wr)), "finger": float(np.median(fi))}
        out[s]["ratio"] = out[s]["finger"] / out[s]["wrist"] if out[s]["wrist"] > 0 else None
    return out


def measure(m):
    rows, events, series = [], [], {}
    res, _ = m.hb()
    if "a09" in res:
        src = "a09 s04（2 秒窓の相互相関の山の遅れの中央値、human_baseline の範囲）"
        for key, label in (("shoulder->elbow", "上腕→ひじ"), ("elbow->wrist", "ひじ→手首"), ("wrist->finger", "手首→指")):
            for s, jp in (("L", "左"), ("R", "右")):
                mid = "arms.a09_%s_%s" % (key.replace("->", "_"), s)
                rows.append(base.row(mid, "腕の連なりの遅れ %s %s" % (label, jp), res["a09"][s]["xcorr"][key].get("median"), "コマ", src,
                                     windows=res["a09"][s]["xcorr"][key].get("n")))
        rows.append(base.row("arms.rests_per_min_R", "腕の休み 右", res["a09"]["R"]["rests_per_min"], "/min", "a09 s04"))
    fs = finger_speeds(m)
    src = "review_fingers_lag の s11_mmd_chain（中身 B、全コマ、生）"
    for s, jp in (("L", "左"), ("R", "右")):
        rows.append(base.row("arms.finger_speed_" + s, "指の速さ 中央値 " + jp, None if fs is None else fs[s]["finger"], "度/秒", src))
        rows.append(base.row("arms.finger_wrist_ratio_" + s, "指 / 手首の速さ " + jp, None if fs is None else fs[s]["ratio"], "", src))
    if "a02" in res:
        rows.append(base.row("arms.wrist_3_6hz_pct", "右手首の速度の 3〜6 Hz の割合", res["a02"]["R"]["band3_6_pct"], "%", "a02 s13"))
    if "a08" in res:
        rows.append(base.row("arms.wrist_8hz_pct", "右手首の速度の 8 Hz 以上の割合", res["a08"]["右手首"]["vel_share_ge8hz_pct"], "%",
                             "a08 s2（人は雑音の床を引いた値）"))
    return {"rows": rows, "events": events, "series": series}
