"""突起: one-frame bumps and dips of a point's speed (a08 s2, the human baseline's range): a step whose speed is above
(below) both neighbours by more than T (0.15 m/s for センター and the head, 0.5 for the wrists), a 15 Hz flicker the
picture shows as a jolt.  Per minute, per point.  Places: each spike, its size (the step against the mean of its
neighbours, m/s).
"""
from . import analysts as A
from . import base

CONCEPT = "spikes"
POINTS = (("センター", "centre"), ("右手首", "wrist_R"), ("左手首", "wrist_L"), ("頭", "head"))


def measure(m):
    rows, events, series = [], [], {}
    res, ev = m.hb()
    if "a08" not in res:
        return {"rows": rows, "events": events, "series": series}
    src = "a08 s2（1 コマの突起、human_baseline の範囲）"
    for bone, key in POINTS:
        mid = "spikes.%s_per_min" % key
        r = res["a08"][bone]
        rows.append(base.row(mid, "1 コマの突起 %s" % bone, r["spikes_per_min"], "/min", src, up_dn=r["spikes_up_dn"]))
        t = A.T_SPIKE[bone]
        edge, scale = base.event_rule(mid, t, t)
        for step, size, kind in ev["a08"][bone]["spikes"]:
            if size <= edge:
                continue
            events.append(base.event(mid, step, step + 1, size, "m/s", edge, scale,
                                     "%s の速さが 1 コマだけ %s（%.2f m/s）" % (bone, "跳ねる" if kind == "up" else "落ちる", size)))
    return {"rows": rows, "events": events, "series": series}
