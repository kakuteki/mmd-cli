"""The outputs of tools/mv_inspect.py: one version's report (JSON and a short markdown), the timeline of the places outside
(CSV and markdown, the heaviest first), and the comparison of two versions (markdown and JSON).

Which places go into the timeline (listed, and why): a place of a measure judged against people is listed when that
measure lies outside people's quartiles on the side such places push it to (the event's "toward", else its "side"), or
when a measure it also stands for (the event's "also") does ("measure"); every place of a rule (limit) is listed when
the measure breaks the rule ("measure"); a place of a window (the lips) is listed when the place itself lies outside the
window ("window"); and a place whose own value lies past people's pooled 99 % point of such places (1 % on the low side,
human.json's "event") is listed whatever its measure as a whole ("extreme": one jolt, slide or fall far past any person's
is a place to look at even in a version that is like people overall).  A place of an "info" measure is never listed;
the others stay in the JSON and events.csv.  Severity: how many of the measure's scales the place lies past its edge
(base.event).
"""
import csv
import io
import json
import math
import os
import time

from . import base

TOP_MD = 60
FORMAT = 2                      # 2: which places are listed changed (toward / also / extreme, the review of 10-17)


WHY = {"measure": "物差しが外", "window": "窓の外", "extreme": "人の 99 % 点の外"}


def _outside(row, side):
    """the measure of `row` breaks its rule, or lies outside people on `side`"""
    if row is None:
        return False
    ref = row.get("ref")
    if ref is None or ref.get("kind") in ("info", "window"):
        return False
    j = row.get("judge")
    if ref.get("kind") == "limit":
        return bool(j and j["side"] != 0)              # every place of a broken rule (a place's own side is its value's)
    return bool(j and j["side"] != 0 and j["side"] == side)


def extreme(ev, row):
    """the place's own value past people's pooled 99 % point of the measure's places (1 % on the low side)"""
    pe = ((row or {}).get("ref") or {}).get("event")
    if not pe:
        return False
    if ev.get("side", 1) >= 0:
        return pe.get("p99") is not None and ev["value"] > pe["p99"]
    return pe.get("p01") is not None and ev["value"] < pe["p01"]


def why(ev, row, rows=None):
    """why the timeline lists a place ("measure", "window", "extreme"; the module's doc), or None"""
    if row is None:
        return None
    ref = row.get("ref")
    if ref is None or ref.get("kind") == "info":
        return None
    if ref.get("kind") == "window":
        return None if ref["lo"] <= ev["value"] <= ref["hi"] else "window"
    for mid, side in [(ev["id"], ev.get("toward", ev.get("side", 1)))] + [tuple(x) for x in ev.get("also", [])]:
        if _outside(row if mid == ev["id"] else (rows or {}).get(mid), side):
            return "measure"
    return "extreme" if extreme(ev, row) else None


def listed(ev, row, rows=None):
    return why(ev, row, rows) is not None


def mark_listed(report):
    by = {r["id"]: r for r in report["measures"]}
    for ev in report["events"]:
        w = why(ev, by.get(ev["id"]), by)
        ev["listed"] = w is not None
        if w:
            ev["why"] = w
        else:
            ev.pop("why", None)
    return report


def timeline(report):
    """the listed places, the heaviest first (ties: earlier first)"""
    return sorted([e for e in report["events"] if e.get("listed")], key=lambda e: (-e["severity"], e["first"]))


def _fmt_t(t):
    m = int(t // 60)
    return "%d:%05.2f" % (m, t - 60 * m)


UNITS = ("%", "/min", "frames", "回", "cm", "度", "ms", "s", "u/s²", "cm/s", "度/秒", "cm/min", "度/min", "コマ")


def _unit(u):
    """the unit as the tables write it ("" for the unnamed ones: shares, ratios)"""
    u = u or ""
    return {"/min": "回/分", "frames": "コマ", "s": "秒", "度/min": "度/分", "cm/min": "cm/分"}.get(u, u) if u in UNITS else ""


def _value(r):
    v = r.get("value")
    if v is None:
        return "-"
    u = _unit(r.get("unit"))
    return "%s %s" % (base.num(v), u) if u else base.num(v)


def _judge_text(r):
    """the judgement as the tables write it: 中, 上へ外 1.2; where every person has one value (base.flat_band) the distance
    counts the MV's frames or events, said so"""
    j = r.get("judge")
    if j is None:
        return "-"
    if j["side"] == 0:
        return j["word"]
    if base.flat_band(r.get("ref")):
        return "%s（人は全員 %s。1 コマ・1 回分の %.1f 倍）" % (j["word"], base.num(r["ref"]["median"]), j["dist"])
    return "%s %.1f" % (j["word"], j["dist"])


def _size_text(r):
    """the size-aligned value and judgement of a row (mv_inspect's --size legs), or an empty string"""
    z = r.get("size")
    if not z:
        return ""
    return "%s（%s）" % (_value(dict(r, value=z["value"])), _judge_text(dict(r, judge=z["judge"])))


def _sized(report):
    return (report.get("size") or {}).get("by") == "legs"


def size_flips(report):
    """the rows whose judgement changes when they are measured at people's size: [(row, raw word, size-aligned word)]"""
    out = []
    for r in report["measures"]:
        z, j = r.get("size"), r.get("judge")
        if z and j and z.get("judge") and z["judge"]["side"] != j["side"]:
            out.append((r, j["word"], z["judge"]["word"]))
    return out


def measures_md(report):
    lines = ["# %s の測り（tools/mv_inspect.py）" % report["label"], "",
             "- 作成: %s、コマ %d（%d〜%d）" % (report["made"], report["frames"], report["first"], report["last"]),
             "- 人の値: %s（中央値 [四分位]。列の組が違う物差しは report.json の ref.group）。決まり・目安のものはその旨。"
             "判定は 中 / 上へ外 / 下へ外（外の数は人の幅を単位にした距離）。" % base.human().get("_about", {}).get("people", ""),
             "- 単位: u は MMD の 1 単位（8 cm）、重力は 122.5 u/s²。加速度の符号は物差しの名に書いた向き（「+ 上」の値は負が下向き）。", ""]
    if _sized(report):
        z = report["size"]
        lines[-1:-1] = ["- 体の大きさ: 人の値は FineDance の標準の体（SMPL-X の中立の体、脚 %.1f cm）で測ったもの。リンの脚は %.1f cm"
                        "（股関節→ひざ→足首、8 cm/単位）。「脚でそろえた」値はリンを %.3f 倍に大きくして同じ時刻で測り直した値で、"
                        "長さと長さの閾値を数える物差しだけ（tools/mvi/base.SIZE_ALIGNED。重力に結んだ物差し・スカートの決まり・ZMP・上体はそろえない）。"
                        "判定と外れた所の表は元の値のまま。股関節の床からの高さでそろえると（リンは厚い靴底で人とほぼ同じ）"
                        "判定はほぼ変わらない（README）。" % (z["people_leg_cm"], z["leg_cm"], z["scale"])]
    if report.get("failed"):
        lines += ["**測れなかった部品**: " + "、".join("%s（%s）" % (k, v.splitlines()[-1][:120]) for k, v in report["failed"].items()), ""]
    out_people = [r for r in report["measures"] if r.get("judge") and r["judge"]["side"] != 0 and (r.get("ref") or {}).get("kind") == "people"]
    far = sorted([r for r in out_people if not base.flat_band(r.get("ref"))], key=lambda r: -r["judge"]["dist"])
    if far:
        lines += ["人から遠い物差し（人の幅を単位にした距離の大きい順、上位 %d / %d）: " % (min(10, len(far)), len(far)) +
                  "、".join("%s %s（%s %.1f）" % (r["name"], _value(r), r["judge"]["word"], r["judge"]["dist"]) for r in far[:10]), ""]
    flat = [r for r in out_people if base.flat_band(r.get("ref"))]
    if flat:
        lines += ["人が全員同じ値の物差しで外（人の幅が 0 なので上の距離の順には入れない）: " +
                  "、".join("%s %s（人は全員 %s）" % (r["name"], _value(r), base.num(r["ref"]["median"])) for r in flat), ""]
    broken = [r for r in report["measures"] if r.get("judge") and r["judge"]["side"] != 0 and (r.get("ref") or {}).get("kind") in ("limit", "window")]
    if broken:
        lines += ["決まり・目安を外れた物差し: " + "、".join("%s %s（%s）" % (r["name"], _value(r), base.ref_text(r.get("ref"))) for r in broken), ""]
    if _sized(report):
        flips = size_flips(report)
        lines += ["脚でそろえると判定が変わる物差し（%d）: " % len(flips) +
                  ("、".join("%s %s → %s（%s → %s）" % (r["name"], _value(r), _value(dict(r, value=r["size"]["value"])), a, b)
                            for r, a, b in flips) if flips else "なし"), ""]
    by_c = {}
    for r in report["measures"]:
        by_c.setdefault(r["concept"], []).append(r)
    ev_by = {}
    for e in report["events"]:
        if e.get("listed"):
            ev_by.setdefault(e["id"], []).append(e)
    for c, cname in base.CONCEPTS:
        rs = by_c.get(c)
        if not rs:
            continue
        if _sized(report):
            lines += ["## %s" % cname, "", "| 物差し | 値 | 人 / 決まり | 判定 | 脚でそろえた値（判定） | 外れた所 |",
                      "| --- | --- | --- | --- | --- | --- |"]
        else:
            lines += ["## %s" % cname, "", "| 物差し | 値 | 人 / 決まり | 判定 | 外れた所 |", "| --- | --- | --- | --- | --- |"]
        for r in rs:
            n = len(ev_by.get(r["id"], []))
            if _sized(report):
                lines.append("| %s | %s | %s | %s | %s | %s |" % (r["name"], _value(r), base.ref_text(r.get("ref")), _judge_text(r),
                                                              _size_text(r), n if n else ""))
            else:
                lines.append("| %s | %s | %s | %s | %s |" % (r["name"], _value(r), base.ref_text(r.get("ref")), _judge_text(r), n if n else ""))
        lines.append("")
    lines += ["## 出所", ""]
    for r in report["measures"]:
        ref = r.get("ref") or {}
        lines.append("- %s: 測り %s。人・決まり %s" % (r["name"], r.get("from", "-"), ref.get("source", "（無し）")))
    return "\n".join(lines) + "\n"


PER_CONCEPT = 3
PER_MEASURE = 8                 # one measure's places in the heaviest-first table at most (the ZMP's stretches, whose tilts
                                # run to 80 of their scale, would fill it: the review of 10-17)


def _place_row(e, by):
    r = by.get(e["id"], {})
    note = e["note"] + ("（人の 99 % 点の外。物差し全体は人の中）" if e.get("why") == "extreme" else "")
    return "| %.2f | %s〜%s | %d〜%d | %s | %s | %s %s | %s | %s |" % (
        e["severity"], _fmt_t(e["t0"]), _fmt_t(e["t1"]), e["first"], e["last"], base.CONCEPT_NAMES.get(e["concept"], e["concept"]),
        r.get("name", e["id"]), base.num(e["value"]), e["unit"], base.num(e["edge"]), note)


def timeline_md(report, top=TOP_MD, per_measure=PER_MEASURE):
    tl = timeline(report)
    by = {r["id"]: r for r in report["measures"]}
    shown, seen, left = [], {}, {}
    for e in tl:
        if len(shown) >= top:
            break
        seen[e["id"]] = seen.get(e["id"], 0) + 1
        if seen[e["id"]] <= per_measure:
            shown.append(e)
        else:
            left[e["id"]] = left.get(e["id"], 0) + 1
    head = ["| 重さ | 時刻 | コマ | 考え方 | 物差し | 値 | 境 | 内容 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    lines = ["# %s の外れた所（重い順、%d / %d。1 つの物差しは %d か所まで）" % (report["label"], len(shown), len(tl), per_measure), "",
             "重さ = 境をどれだけ越えたか。人の区間を集めた物差しは境が人の 90 % 点（低い側は 10 % 点）で、そこから 99 % 点までの幅を 1 とする"
             "（1 以上 = 人の 99 % 点の外）。決まりと窓はその目盛り（スカートは 12.2 u/s²、口は 50 ms など）。重さの目盛りは物差しごとに"
             "違うので、下の「考え方ごとの重い順」も見る。全部は outliers.csv（時刻表に入らない所は events.csv）。", ""] + head
    lines += [_place_row(e, by) for e in shown]
    if left:
        lines += ["", "（表の重さの範囲で %d か所を越えて表から外した所: %s。outliers.csv にある）" % (
            per_measure, "、".join("%s %d" % (by.get(k, {}).get("name", k), n) for k, n in left.items()))]
    counts = {}
    for e in tl:
        counts[e["concept"]] = counts.get(e["concept"], 0) + 1
    lines += ["", "考え方ごとの数: " + "、".join("%s %d" % (base.CONCEPT_NAMES.get(c, c), n) for c, n in counts.items())]
    if counts:
        lines += ["", "## 考え方ごとの重い順（各 %d）" % PER_CONCEPT, ""] + head
        for c, _ in base.CONCEPTS:
            lines += [_place_row(e, by) for e in [x for x in tl if x["concept"] == c][:PER_CONCEPT]]
    return "\n".join(lines) + "\n"


CSV_COLUMNS = ["severity", "t0", "t1", "first", "last", "concept", "id", "name", "value", "unit", "edge", "note", "listed", "why"]


def timeline_csv(report, all_events=False):
    by = {r["id"]: r for r in report["measures"]}
    evs = report["events"] if all_events else timeline(report)
    if all_events:
        evs = sorted(evs, key=lambda e: (not e.get("listed"), -e["severity"], e["first"]))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for e in evs:
        w.writerow([e["severity"], e["t0"], e["t1"], e["first"], e["last"], base.CONCEPT_NAMES.get(e["concept"], e["concept"]),
                    e["id"], by.get(e["id"], {}).get("name", ""), e["value"], e["unit"], e["edge"], e["note"], int(bool(e.get("listed"))),
                    WHY.get(e.get("why"), "")])
    return buf.getvalue()


def write(report, out_dir):
    """report.json, report.md, outliers.md, outliers.csv (listed) and events.csv (every place) in out_dir"""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for name, text in (("report.md", measures_md(report)), ("outliers.md", timeline_md(report)),
                       ("outliers.csv", timeline_csv(report)), ("events.csv", timeline_csv(report, all_events=True))):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8-sig" if name.endswith(".csv") else "utf-8", newline="") as f:
            f.write(text)
        paths[name] = p
    p = os.path.join(out_dir, "report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(base.round_tree(report), f, ensure_ascii=False, indent=1)
    paths["report.json"] = p
    return paths


def load(path):
    if os.path.isdir(path):
        path = os.path.join(path, "report.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- two versions ---------------------------------------------------------------------------------------------------

def _overlap(a, b):
    return a["first"] <= b["last"] and b["first"] <= a["last"]


def compare(a, b):
    """{"rows": per measure the values of A and B, the reference and the word; "new": B's listed places that no place of
    A overlaps (the same measure, listed or not); "gone": A's listed places that no place of B overlaps; "unlisted_now":
    A's listed places that B still has, unlisted (B's measure as a whole went inside people: the place is not gone);
    "listed_now": B's listed places that A had, unlisted}"""
    ra = {r["id"]: r for r in a["measures"]}
    rows = []
    for rb in b["measures"]:
        r0 = ra.get(rb["id"])
        ref = rb.get("ref") or (r0 or {}).get("ref")
        va = None if r0 is None else r0.get("value")
        vb = rb.get("value")
        row = {"id": rb["id"], "concept": rb["concept"], "name": rb["name"], "unit": rb.get("unit", ""), "a": va, "b": vb,
               "ref": ref, "judge_a": None if r0 is None else r0.get("judge"), "judge_b": rb.get("judge"),
               "word": base.compare(ref, va, vb, rb.get("unit", ""))}
        za, zb = (r0 or {}).get("size"), rb.get("size")
        if za and zb:
            row["a_size"], row["b_size"] = za["value"], zb["value"]
            row["word_size"] = base.compare(ref, za["value"], zb["value"], rb.get("unit", ""))
        rows.append(row)
    for r0 in a["measures"]:
        if r0["id"] not in {r["id"] for r in rows}:
            rows.append({"id": r0["id"], "concept": r0["concept"], "name": r0["name"], "unit": r0.get("unit", ""), "a": r0.get("value"),
                         "b": None, "ref": r0.get("ref"), "judge_a": r0.get("judge"), "judge_b": None, "word": None})
    la, lb = timeline(a), timeline(b)
    heavy = lambda es: sorted(es, key=lambda e: -e["severity"])          # noqa: E731

    def split(mine, theirs):
        """mine's listed places that theirs has no place over (the same measure), and those it has, unlisted"""
        none, unlisted = [], []
        for e in mine:
            over = [x for x in theirs if x["id"] == e["id"] and _overlap(x, e)]
            if not over:
                none.append(e)
            elif not any(x.get("listed") for x in over):
                unlisted.append(e)
        return heavy(none), heavy(unlisted)
    new, listed_now = split(lb, a["events"])
    gone, unlisted_now = split(la, b["events"])
    return {"a": a["label"], "b": b["label"], "rows": rows, "new": new, "gone": gone, "listed_now": listed_now,
            "unlisted_now": unlisted_now, "listed": [len(la), len(lb)], "formats": [a.get("format"), b.get("format")]}


def _dist_text(side, dist):
    return "中" if side == 0 else "%s %.1f" % ("上へ" if side > 0 else "下へ", dist)


def word_text(w):
    """the comparison's word with the distances outside people (A → B), as the human baseline's table wrote them"""
    if w is None:
        return "-"
    return "%s（%s → %s）" % (w["word"], _dist_text(w["before_side"], w["before_dist"]), _dist_text(w["after_side"], w["after_dist"]))


def compare_md(c, top=30):
    lines = ["# %s と %s の比べ（tools/mv_inspect.py）" % (c["a"], c["b"]), "",
             "判定: 入った（%s は外、%s は人の四分位の中）・中のまま・近づいた・遠ざかった・直しすぎ（人の反対側へ出た）・変わらず。"
             "括弧は人の外の距離（%s → %s、人の幅が単位、中 = 人の四分位の中）。" % (c["a"], c["b"], c["a"], c["b"]),
             "外れた所の数: %s %d → %s %d。" % (c["a"], c["listed"][0], c["b"], c["listed"][1]), ""]
    fa, fb = c.get("formats") or [None, None]
    if fa != fb or fa != FORMAT:
        lines += ["**注意**: 2 つの版の report.json は時刻表の決め方の版が違う（%s %s・%s %s、今の道具は %d）。外れた所の数と"
                  "新しく外れた所・消えた所は測り直してから比べる。" % (c["a"], fa, c["b"], fb, FORMAT), ""]
    if c.get("unlisted_now") or c.get("listed_now"):
        lines += ["同じ物差しの所が両方の版にあり、時刻表に入るかだけが変わったもの（物差し全体が人の中に入った・出た）: "
                  "%s の時刻表から外れたがまだある %d、%s で時刻表に入ったが %s にもあった %d。下の「新しく外れた所」「消えた所」には入れない。" % (
                      c["b"], len(c.get("unlisted_now", [])), c["b"], c["a"], len(c.get("listed_now", []))), ""]
    by_c = {}
    for r in c["rows"]:
        by_c.setdefault(r["concept"], []).append(r)
    for cc, cname in base.CONCEPTS:
        rs = by_c.get(cc)
        if not rs:
            continue
        sized = any("word_size" in r for r in c["rows"])
        if sized:
            lines += ["## %s" % cname, "", "| 物差し | 単位 | 人 / 決まり | %s | %s | 判定 | 脚でそろえた判定 |" % (c["a"], c["b"]),
                      "| --- | --- | --- | --- | --- | --- | --- |"]
        else:
            lines += ["## %s" % cname, "", "| 物差し | 単位 | 人 / 決まり | %s | %s | 判定 |" % (c["a"], c["b"]), "| --- | --- | --- | --- | --- | --- |"]
        for r in rs:
            cells = (r["name"], _unit(r.get("unit")) or "-", base.ref_text(r.get("ref")), base.num(r["a"]), base.num(r["b"]),
                     word_text(r.get("word")))
            if sized:
                cells += (word_text(r["word_size"]) if r.get("word_size") else "",)
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    for key, title in (("new", "%s で新しく外れた所" % c["b"]), ("gone", "%s で消えた所" % c["b"])):
        evs = c[key]
        lines += ["## %s（%d、重い順に %d）" % (title, len(evs), min(top, len(evs))), ""]
        if evs:
            lines += ["| 重さ | 時刻 | 考え方 | 物差し | 値 | 内容 |", "| --- | --- | --- | --- | --- | --- |"]
            for e in evs[:top]:
                lines.append("| %.2f | %s〜%s | %s | %s | %s %s | %s |" % (e["severity"], _fmt_t(e["t0"]), _fmt_t(e["t1"]),
                                                                        base.CONCEPT_NAMES.get(e["concept"], e["concept"]), e["id"],
                                                                        base.num(e["value"]), e["unit"], e["note"]))
        lines.append("")
    return "\n".join(lines) + "\n"


def write_compare(c, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    p_md = os.path.join(out_dir, "compare.md")
    with open(p_md, "w", encoding="utf-8") as f:
        f.write(compare_md(c))
    p_js = os.path.join(out_dir, "compare.json")
    with open(p_js, "w", encoding="utf-8") as f:
        json.dump(base.round_tree(c), f, ensure_ascii=False, indent=1)
    return {"compare.md": p_md, "compare.json": p_js}


def made():
    return time.strftime("%Y-%m-%d %H:%M:%S")
