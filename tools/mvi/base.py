"""What every part of tools/mv_inspect.py shares: the units, the people's values (human.json), the judgement against them,
the comparison of two versions, the rows a part reports and the events it lists.

A measure is a row: its id (part.name, ASCII), its Japanese name, the value, the unit, where the measure comes from, and
the reference it is judged against, read from human.json by id:

* "people": the median, the quartiles and the 10 / 90 % points over people's sequences (one value per sequence, as one
  song is one value for the MV), the group (FineDance K-pop, choreography and jazz, 62 sequences, unless named) and
  where the numbers come from.  Only these aggregates are kept: the people's own data stay on hinata.
* "limit": a bound (max or min) set by a rule of the project (the skirt's 122 units/s^2, the floor, the dance's own
  jumps), with the scale a distance is counted in.
* "window": a band set by a rule outside people's data (the lips: ITU-R BT.1359-1).
* "info": shown, not judged.

The judgement is the human baseline's (stage6/human_baseline/scripts/p31_table.py): a value inside [q1 - res, q3 + res]
is inside ("中"), else above or below ("上へ外" / "下へ外"); the distance outside is counted in the scale
max(IQR, (p90 - p10) / 2, res), res the resolution of one event or frame in the MV's dance (246 s).  Two versions A
(before) and B (after): B inside and A outside "入った", both inside "中のまま", B on the other side of people from A
"直しすぎ", B nearer to the median than A "近づいた", farther "遠ざかった", the same distance (to 0.05) "変わらず".
"""
import hashlib
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FPS = 30.0
UNIT_CM = 8.0                   # one unit of Sour's Rin is 8 cm (the analysis pack's README)
G_UNITS = 122.5                 # 9.8 m/s^2 in her units (8 cm a unit)
MV_SECONDS = 246.0              # the MV's dance range (p31_table's resolution)
CONCEPTS = [("gravity", "重力感"), ("feet", "足"), ("balance", "重心とバランス"), ("upper", "上体"), ("arms", "腕と指"),
            ("eyes", "目"), ("mouth", "口"), ("skirt", "スカートの危なさ"), ("spikes", "突起"), ("pixels", "描いた絵")]
CONCEPT_NAMES = dict(CONCEPTS)
SIDE_WORDS = {0: "中", 1: "上へ外", -1: "下へ外"}
HUMAN_PATH = os.path.join(HERE, "human.json")

_TOOLS = {}


def tool(name):
    """a module of tools/ by its file name (loaded once, by path, as the other tools load each other)"""
    if name not in _TOOLS:
        spec = importlib.util.spec_from_file_location("_mvi_" + name, os.path.join(TOOLS, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TOOLS[name] = module
    return _TOOLS[name]


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---- people's values -----------------------------------------------------------------------------------------------

_HUMAN = {}


def human(path=HUMAN_PATH):
    """id -> reference (see the module's doc); human.json's "_about" holds where the groups come from"""
    if path not in _HUMAN:
        with open(path, encoding="utf-8") as f:
            _HUMAN[path] = json.load(f)
    return _HUMAN[path]


def reference(mid, path=HUMAN_PATH):
    return human(path).get(mid)


def resolution(unit, seconds=MV_SECONDS):
    """the value of one frame or one event in the MV's dance (p31_table.resolution)"""
    if unit == "%":
        return 100.0 / (seconds * FPS)
    if unit == "/min":
        return 60.0 / seconds
    if unit == "frames":
        return 1.0
    return 0.0


def band(ref):
    """(lo, hi, middle, scale) of a reference: what lies inside [lo, hi] is inside; distances outside count in scale"""
    kind = ref.get("kind", "people")
    if kind == "people":
        lo, hi = ref["q1"], ref["q3"]
        spread = (ref["p90"] - ref["p10"]) / 2.0 if ref.get("p90") is not None and ref.get("p10") is not None else 0.0
        return lo, hi, ref["median"], max(hi - lo, spread)
    if kind == "window":
        return ref["lo"], ref["hi"], 0.5 * (ref["lo"] + ref["hi"]), ref.get("scale") or (ref["hi"] - ref["lo"])
    if kind == "limit":
        lo = ref.get("min", -math.inf)
        hi = ref.get("max", math.inf)
        mid = hi if math.isfinite(hi) else lo
        if math.isfinite(lo) and math.isfinite(hi):
            mid = 0.5 * (lo + hi)
        return lo, hi, mid, ref.get("scale") or max(abs(mid), 1.0)
    return None


def _side_dist(x, lo, hi, scale, res):
    lo2, hi2 = lo - res, hi + res
    scale = max(scale, res, 1e-12)
    if x < lo2:
        return -1, (lo2 - x) / scale
    if x > hi2:
        return 1, (x - hi2) / scale
    return 0, 0.0


def judge(ref, value, unit=""):
    """{"side": -1 / 0 / 1, "dist": scales outside, "word"} of a value against its reference, or None (no reference, no
    value, or an "info" reference)"""
    if ref is None or value is None or not np.isfinite(value) or ref.get("kind") == "info":
        return None
    b = band(ref)
    if b is None:
        return None
    lo, hi, _, scale = b
    side, dist = _side_dist(float(value), lo, hi, scale, resolution(unit) if ref.get("kind", "people") == "people" else 0.0)
    return {"side": side, "dist": round(dist, 2), "word": SIDE_WORDS[side]}


def compare(ref, before, after, unit=""):
    """the comparison of B (after) with A (before) against the reference (see the module's doc), or None"""
    if ref is None or before is None or after is None or ref.get("kind") == "info":
        return None
    if not (np.isfinite(before) and np.isfinite(after)):
        return None
    b = band(ref)
    if b is None:
        return None
    lo, hi, mid, scale = b
    res = resolution(unit) if ref.get("kind", "people") == "people" else 0.0
    sa, da = _side_dist(float(before), lo, hi, scale, res)
    sb, db = _side_dist(float(after), lo, hi, scale, res)
    if sa != 0 and sb == -sa:
        word = "直しすぎ"
    elif sb == 0:
        word = "中のまま" if sa == 0 else "入った"
    elif abs(db - da) < 0.05:
        word = "変わらず"
    elif sa == 0:
        word = "遠ざかった"
    else:
        word = "近づいた" if db < da else "遠ざかった"
    return {"before_side": sa, "before_dist": round(da, 2), "after_side": sb, "after_dist": round(db, 2), "word": word}


def ref_text(ref, digits=3):
    """the reference as a short text: '1.4 [0.5, 2.2]', '<= 0', '-45 .. 125'"""
    if ref is None:
        return "-"
    kind = ref.get("kind", "people")
    g = lambda x: _num(x, digits)            # noqa: E731
    if kind == "people":
        return "%s [%s, %s]" % (g(ref["median"]), g(ref["q1"]), g(ref["q3"]))
    if kind == "window":
        return "%s 〜 %s" % (g(ref["lo"]), g(ref["hi"]))
    if kind == "limit":
        parts = []
        if "min" in ref:
            parts.append("%s 以上" % g(ref["min"]))
        if "max" in ref:
            parts.append("%s 以下" % g(ref["max"]))
        return "・".join(parts)
    return ref.get("text", "（目安なし）")


def _num(x, digits=3):
    if x is None:
        return "-"
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    x = float(x)
    if not np.isfinite(x):
        return "-"
    if x == 0.0:
        return "0"
    if abs(x) >= 10 ** digits:
        return "%.0f" % x
    return ("%." + str(digits) + "g") % x


num = _num


# ---- rows and events -----------------------------------------------------------------------------------------------

def row(mid, name, value, unit, source, concept=None, ref_path=HUMAN_PATH, **extra):
    """one measure: judged against human.json's reference of `mid`"""
    concept = concept or mid.split(".", 1)[0]
    ref = reference(mid, ref_path)
    value = None if value is None else (float(value) if not isinstance(value, (int, np.integer)) else int(value))
    out = {"id": mid, "concept": concept, "name": name, "value": value, "unit": unit, "from": source, "ref": ref,
           "judge": judge(ref, value, unit)}
    out.update(extra)
    return out


def event(mid, first, last, value, unit, edge, scale, note="", side=1, **extra):
    """one place in the song where a measure lies outside: frames first..last (inclusive), the value there, the edge it is
    past and the scale the severity counts in (severity = how many scales past the edge)"""
    if side >= 0:
        excess = float(value) - float(edge)
    else:
        excess = float(edge) - float(value)
    sev = max(0.0, excess) / max(float(scale), 1e-12)
    out = {"id": mid, "concept": mid.split(".", 1)[0], "first": int(first), "last": int(last),
           "t0": round(int(first) / FPS, 2), "t1": round((int(last) + 1) / FPS, 2), "value": round(float(value), 4),
           "unit": unit, "edge": round(float(edge), 4), "severity": round(sev, 3), "note": note,
           "side": 1 if side >= 0 else -1}
    out.update(extra)
    return out


def runs(mask, min_len=1):
    """[(first, last)] inclusive runs of True at least min_len long"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]]).astype(np.int8)
    d = np.diff(m)
    st = np.flatnonzero(d == 1)
    en = np.flatnonzero(d == -1) - 1
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a + 1 >= min_len]


def event_rule(mid, edge=None, scale=None):
    """(edge, scale) for the places of a measure: people's pooled places (human.json's "event": their 90 % point, or
    10 % on the low side, and the distance from there to their 99 % / 1 % point), else the edge and scale given"""
    ref = reference(mid)
    ev = (ref or {}).get("event")
    if ev:
        return float(ev["edge"]), float(ev["scale"])
    return edge, scale


def people_edge(ref, side):
    """the quartile people lie beyond on `side` (+1: q3, -1: q1) and the scale (the judgement's) of a reference"""
    lo, hi, _, scale = band(ref)
    return (hi if side > 0 else lo), max(scale, 1e-9)


def round_tree(x, digits=6):
    """numbers of a nested structure rounded (JSON of a report)"""
    if isinstance(x, dict):
        return {k: round_tree(v, digits) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [round_tree(v, digits) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return round(v, digits) if np.isfinite(v) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.ndarray):
        return round_tree(x.tolist(), digits)
    return x
