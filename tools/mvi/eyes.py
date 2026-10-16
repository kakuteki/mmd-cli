"""目: where the eyes sit in the face.

The eyes' angles in the head (yaw to the model's left, pitch up, from the rest gaze along -Z) from the merged motion:
the turn of 両目 against 頭 applied to the rest gaze (the gaze VMD writes 両目 as tools/eye_gaze.eye_rotation(yaw,
pitch)), and tools/eye_gaze.eye_measures (the analysis' a07 / a13 definitions): the share of frames at the edge (90 % or
more of a limit on some axis; the limits of eye_gaze, 18 sideways, 6 up, 10 down, unless the version names its own
"eye_limits"), the longest stay there, and the share 15 degrees or more off the middle.  People (the literature the
analysts cited): 99 % of eye movements within 15 degrees of the middle (Lancaster 1941 via Bahill, Adler & Stark 1975;
Stahl 1999); people pass half their range under 1 % of the time (a07).  Places: the stays at the edge of 0.5 s or more.
"""
import math

import numpy as np

from . import base

CONCEPT = "eyes"
EDGE_RUN_S = 0.5


def eye_angles(m):
    """[(yaw, pitch)] per frame, degrees; None when the model has no 両目"""
    try:
        _, qh = m.v.bone("頭")
        _, qe = m.v.bone("両目")
    except ValueError:
        return None
    qh, qe = np.asarray(qh, dtype=np.float64), np.asarray(qe, dtype=np.float64)
    from .analysts import qconj, qmul, qrot
    rel = qmul(qconj(qh), qe)
    d = qrot(rel, np.broadcast_to(np.array([0.0, 0.0, -1.0]), (len(rel), 3)))
    yaw = np.degrees(np.arctan2(d[:, 0], -d[:, 2]))
    pitch = np.degrees(np.arctan2(d[:, 1], np.hypot(d[:, 0], d[:, 2])))
    return list(zip(yaw.tolist(), pitch.tolist()))


def measure(m):
    rows, events, series = [], [], {}
    eg = base.tool("eye_gaze")
    lim = m.v.spec.get("eye_limits")
    limits = eg.Limits(*lim) if lim else eg.Limits()
    angles = eye_angles(m)
    src = "tools/eye_gaze.eye_measures（a07・a13 の定義、両目の頭に対する回り、範囲 %g・上 %g・下 %g 度）" % (limits.yaw, limits.up, limits.down)
    if angles is None:
        for mid, name in (("eyes.edge_pct", "目が範囲の端（90 % 以上）にいるコマ"), ("eyes.edge_longest_s", "端に居続けた最長"),
                          ("eyes.eccentric15_pct", "目が顔の中で正面から 15 度以上")):
            rows.append(base.row(mid, name, None, "", src + "。両目の骨が無い"))
        return {"rows": rows, "events": events, "series": series}
    me = eg.eye_measures(angles, limits)
    rows.append(base.row("eyes.edge_pct", "目が範囲の端（90 % 以上）にいるコマ", 100.0 * me["edge_share"], "%", src))
    rows.append(base.row("eyes.edge_longest_s", "端に居続けた最長", me["edge_longest_s"], "s", src))
    rows.append(base.row("eyes.eccentric15_pct", "目が顔の中で正面から 15 度以上", 100.0 * me["eccentric_15_share"], "%", src))
    edge = np.array([max(abs(y) / limits.yaw, p / limits.up if p > 0 else -p / limits.down) for y, p in angles])
    longest = (base.reference("eyes.edge_longest_s") or {}).get("max", 1.0)
    for a, b in base.runs(edge >= eg.EDGE):
        sec = (b - a + 1) / base.FPS
        if sec >= EDGE_RUN_S:
            y, p = angles[a + (b - a) // 2]
            # a stay longer than the longest-stay rule stands for that rule too (listed when it breaks, whatever the share)
            events.append(base.event("eyes.edge_pct", a, b, sec, "s", EDGE_RUN_S, EDGE_RUN_S,
                                     "目が端に %.2f 秒（%s）" % (sec, eg.describe(y, p)),
                                     also=[("eyes.edge_longest_s", 1)] if sec > longest else None))
    series["eye_edge"] = {"label": "目の向き / 範囲（1 が端、%g 以上を端と数える）" % eg.EDGE, "unit": "", "y": edge,
                          "lo": None, "hi": eg.EDGE, "ids": ["eyes.edge_pct", "eyes.edge_longest_s"]}
    return {"rows": rows, "events": events, "series": series}
