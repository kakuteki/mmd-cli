"""balance-v3's check that the body's layers keep the dance's accents and jumps (stage6/balance_v3/scripts/q1_vertical.py,
the review of balance-v2's script, 2026-10-16), on a version against its reference (the dance before the body's layers):

* dips: every local minimum of 下半身's height in the reference whose drop from the highest point in the 0.5 s before it
  is 2 cm or more; per dip the version's drop (its own minimum within +-6 frames, its own top within +-6 frames of the
  reference's), and whether the reference's minimum is on a beat (within 2 frames of the 140 BPM grid).  Counted: the
  dips on the beat whose drop is under 0.8 of the reference's.
* jumps: both of the reference's feet (balance_layer.Body.height) 1.6 cm off the floor for 4 frames or more; the
  version's top against the reference's over the same frames.  Counted: the jumps whose top is 2 cm or more lower.

The bodies are tools/balance_layer.Body (its FK and its two-bone legs), as the script read them.
"""
import numpy as np

FPS = 30.0
CM = 8.0
BEAT0, PERIOD = 0.01593, 0.4285714


def on_beat(f, beat0=BEAT0, period=PERIOD):
    t = f / FPS
    k = round((t - beat0) / period)
    return abs(t - (beat0 + k * period)) * FPS <= 2.0


def dips(y, win=15, min_cm=2.0):
    out = []
    for f in range(win, len(y) - 2):
        if y[f] < y[f - 1] and y[f] <= y[f + 1]:
            top = f - win + int(np.argmax(y[f - win:f]))
            if (y[top] - y[f]) * CM >= min_cm:
                out.append((f, top))
    return out


def heights(body):
    """(下半身's height [F], {side: the foot's lowest point over the floor [F]}) of a balance_layer.Body"""
    return body.p("下半身")[:, 1].copy(), {s: body.height(s).copy() for s in ("左", "右")}


def compare(ref, ver, beat0=BEAT0, period=PERIOD):
    """q1_vertical's rows and summary for one version against the reference; ref, ver: heights() of each"""
    y0, low0 = ref
    y = ver[0]
    D = dips(y0)
    rows = []
    for f, top in D:
        r = {"f": f, "t": round(f / FPS, 2), "beat": bool(on_beat(f, beat0, period))}
        for lab, yy in (("ref", y0), ("ver", y)):
            a, b = max(0, f - 6), min(len(yy), f + 7)
            fm = a + int(np.argmin(yy[a:b]))
            ta, tb = max(0, top - 6), top + 7
            ft = ta + int(np.argmax(yy[ta:tb]))
            v = -np.diff(yy[ft:fm + 1]) * FPS * CM if fm > ft else np.zeros(1)
            r[lab] = {"drop_cm": round(float(yy[ft] - yy[fm]) * CM, 2), "dt_min": int(fm - f), "dt_top": int(ft - top),
                      "low_cm": round(float(yy[fm] - y0[f]) * CM, 2), "vdown_max": round(float(v.max()), 1)}
        rows.append(r)
    summ = {}
    for sel_name, sel in (("all", rows), ("beat", [r for r in rows if r["beat"]])):
        ratio = np.array([r["ver"]["drop_cm"] / max(r["ref"]["drop_cm"], 1e-9) for r in sel])
        summ[sel_name] = {"n": len(sel), "drop_ratio_under_0.8": int(np.sum(ratio < 0.8)) if len(ratio) else 0,
                          "drop_ratio_under_0.9": int(np.sum(ratio < 0.9)) if len(ratio) else 0}
    air = (low0["左"] >= 0.2) & (low0["右"] >= 0.2)
    jumps = []
    f = 0
    F = len(y0)
    while f < F:
        if air[f]:
            g = f
            while g + 1 < F and air[g + 1]:
                g += 1
            if g - f + 1 >= 4:
                j = {"first": f, "last": g, "t": round(f / FPS, 2), "frames": g - f + 1}
                a = max(0, f - 1)
                j["ref_rise_cm"] = round(float(y0[f:g + 1].max() - y0[a]) * CM, 2)
                j["rise_cm"] = round(float(y[f:g + 1].max() - y[a]) * CM, 2)
                j["top_cm"] = round(float(y[f:g + 1].max() - y0[f:g + 1].max()) * CM, 2)
                jumps.append(j)
            f = g + 1
        else:
            f += 1
    top = np.array([j["top_cm"] for j in jumps])
    summ["jumps"] = {"n": len(jumps), "top_lowered_over_2cm": int(np.sum(top < -2.0)) if len(top) else 0,
                     "top_lowered_over_5cm": int(np.sum(top < -5.0)) if len(top) else 0}
    return {"summary": summ, "dips": rows, "jumps": jumps}
