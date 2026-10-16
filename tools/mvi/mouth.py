"""口: the mouth against the singing voice (tools/lip_check.py: the times from the separated voice alone).

The voice (the version's "vocal": the separated singing voice) gives its onsets (the vowels after a consonant or a
rest, from the 300-3500 Hz flux) and which of them open the mouth (OPEN over the onset's vowel, split at Otsu's
threshold); the merged motion's vowel morphs (あ い う え お, linear between keys as MMD) give the mouth's visible
opening and its rises (frame f shown at f + 0.1875, the MV's folded subframes).  Per onset paired with a rise: the lag
(+ the mouth first).  Judged against ITU-R BT.1359-1 (the picture 45 ms after the sound to 125 ms before it goes
unnoticed): the median lag on the open vowels (the lipsync review's main number: after い and う the nearest rise is
often the next syllable's and reads late) and on every onset.  Places: the onsets whose own lag lies outside that
window.  Shown, not judged: the shares noticed late or early, and the time the voice clearly sings with the mouth
looking shut (inside the lyric lines when the version names its "lines").
"""
import math

import numpy as np

from . import base

CONCEPT = "mouth"
NAMES = (("mouth.lag_open_ms", "開く母音の立ち上がりで口が半分開く時刻（中央値、+ 口が先）", "ms"),
         ("mouth.late_open_pct", "開く母音で口が 45 ms より遅い", "%"),
         ("mouth.early_open_pct", "開く母音で口が 125 ms より早い", "%"),
         ("mouth.lag_median_ms", "全部の立ち上がりで口が半分開く時刻（中央値）", "ms"),
         ("mouth.late_pct", "全部の立ち上がりで口が 45 ms より遅い", "%"),
         ("mouth.shut_singing_pct", "声がはっきり鳴るのに口が閉じて見える時間", "%"))


def _pct(x):
    return None if x is None else 100.0 * x


def measure(m):
    rows, events, series = [], [], {}
    vocal = m.v.spec.get("vocal")
    src = "tools/lip_check.py（分けた歌声の立ち上がりと口の開きの立ち上がり、ITU-R BT.1359-1）"
    if not vocal:
        for mid, name, unit in NAMES:
            rows.append(base.row(mid, name, None, unit, src + "。歌声（vocal）が無いので測らない"))
        return {"rows": rows, "events": events, "series": series}
    lc = base.tool("lip_check")
    x = lc.read_sound(vocal)
    voice = lc.Voice(x)
    onsets = lc.voice_onsets(voice)
    opens = lc.onset_open(voice, onsets)
    frames = int(math.ceil(len(x) / float(lc.SR) * lc.FPS)) + 1
    o = lc.opening(m.v.merged, frames)
    res, pairs, lags = lc.lag_measure(onsets, lc.rise_times(o))
    ov = lc.lag_summary([v for (i, _), v in zip(pairs, lags) if opens[i]])
    lines = m.v.spec.get("lines")
    st = lc.states(o, voice, lc.read_spans(lines) if lines else None)
    lag_o, lag_a = ov.get("lag_ms") or {}, res.get("lag_ms") or {}
    n_open = sum(1 for v in opens if v)
    rows.append(base.row(NAMES[0][0], NAMES[0][1], lag_o.get("median"), "ms", src, onsets=n_open,
                         paired=sum(1 for i, _ in pairs if opens[i]), p10=lag_o.get("p10"), p90=lag_o.get("p90")))
    rows.append(base.row(NAMES[1][0], NAMES[1][1], _pct(ov.get("share_mouth_late_over_45ms")), "%", src))
    rows.append(base.row(NAMES[2][0], NAMES[2][1], _pct(ov.get("share_mouth_early_over_125ms")), "%", src))
    rows.append(base.row(NAMES[3][0], NAMES[3][1], lag_a.get("median"), "ms", src, onsets=res["onsets"], paired=res["paired"],
                         p10=lag_a.get("p10"), p90=lag_a.get("p90")))
    rows.append(base.row(NAMES[4][0], NAMES[4][1], _pct(res.get("share_mouth_late_over_45ms")), "%", src,
                         early=_pct(res.get("share_mouth_early_over_125ms"))))
    key = "shut_while_singing_inside_lines" if "shut_while_singing_inside_lines" in st else "shut_while_singing"
    sw = st[key]
    rows.append(base.row(NAMES[5][0], NAMES[5][1] + ("（歌詞の行の中）" if key.endswith("lines") else ""), 100.0 * sw["share"], "%", src,
                         seconds=sw["seconds"], all_song=100.0 * st["shut_while_singing"]["share"]))
    for (i, _), v in zip(pairs, lags):
        t = float(onsets[i])
        f = int(round(t * base.FPS))
        kind = "開く母音" if opens[i] else "閉じた母音"
        if v < -1000.0 * lc.LATE:
            events.append(base.event("mouth.lag_median_ms", f, f, v, "ms", -1000.0 * lc.LATE, 50.0,
                                     "口が声より %.0f ms 遅い（%s）" % (-v, kind), side=-1))
        elif v > 1000.0 * lc.EARLY:
            events.append(base.event("mouth.lag_median_ms", f, f, v, "ms", 1000.0 * lc.EARLY, 50.0, "口が声より %.0f ms 早い（%s）" % (v, kind)))
    for a, b in sw["longest_s"]:
        events.append(base.event("mouth.shut_singing_pct", int(a * base.FPS), max(int(a * base.FPS), int(b * base.FPS) - 1),
                                 b - a, "s", 0.0, 0.25, "声が鳴るのに口が閉じて見える %.2f 秒" % (b - a)))
    series["mouth_open"] = {"label": "口の見える開き（あ = 1）", "unit": "", "y": np.asarray(o, dtype=np.float64)[:m.v.frames],
                            "lo": None, "hi": None, "ids": ["mouth.lag_median_ms", "mouth.shut_singing_pct"]}
    return {"rows": rows, "events": events, "series": series}
