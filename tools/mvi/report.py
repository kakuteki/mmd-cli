"""The outputs of tools/mv_inspect.py: one version's report (JSON and a short markdown), the timeline of the places outside
(CSV and markdown, the heaviest first), and the comparison of two versions (markdown and JSON).

Which places go into the timeline (listed): a place of a measure judged against people is listed when that measure lies
outside people's quartiles on the place's side (a place on the other side, or of a measure inside, stays in the JSON
only); a place of a rule (limit) is listed when the measure breaks the rule; a place of a window (the lips) is listed
when the place itself lies outside the window; a place of an "info" measure is never listed.  Severity: how many of
the measure's scales the place lies past its edge (base.event).
"""
import csv
import io
import json
import math
import os
import time

from . import base

TOP_MD = 60


def listed(ev, row):
    if row is None:
        return False
    ref = row.get("ref")
    if ref is None or ref.get("kind") == "info":
        return False
    if ref.get("kind") == "window":
        return not (ref["lo"] <= ev["value"] <= ref["hi"])
    j = row.get("judge")
    return bool(j and j["side"] != 0 and j["side"] == ev.get("side", 1))


def mark_listed(report):
    by = {r["id"]: r for r in report["measures"]}
    for ev in report["events"]:
        ev["listed"] = listed(ev, by.get(ev["id"]))
    return report


def timeline(report):
    """the listed places, the heaviest first (ties: earlier first)"""
    return sorted([e for e in report["events"] if e.get("listed")], key=lambda e: (-e["severity"], e["first"]))


def _fmt_t(t):
    m = int(t // 60)
    return "%d:%05.2f" % (m, t - 60 * m)


def _value(r):
    v = r.get("value")
    if v is None:
        return "-"
    u = r.get("unit") or ""
    if u in ("%", "/min", "frames", "回", "cm", "度", "ms", "s", "u/s²", "cm/s", "度/秒", "cm/min", "度/min", "コマ"):
        return "%s %s" % (base.num(v), {"/min": "回/分", "frames": "コマ", "s": "秒", "度/min": "度/分", "cm/min": "cm/分"}.get(u, u))
    return base.num(v)


def measures_md(report):
    lines = ["# %s の測り（tools/mv_inspect.py）" % report["label"], "",
             "- 作成: %s、コマ %d（%d〜%d）" % (report["made"], report["frames"], report["first"], report["last"]),
             "- 人の値: %s（中央値 [四分位]）。決まり・目安のものはその旨。判定は 中 / 上へ外 / 下へ外（外の数は人の幅を単位にした距離）。" % (
                 base.human().get("_about", {}).get("people", "")), ""]
    if report.get("failed"):
        lines += ["**測れなかった部品**: " + "、".join("%s（%s）" % (k, v.splitlines()[-1][:120]) for k, v in report["failed"].items()), ""]
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
        lines += ["## %s" % cname, "", "| 物差し | 値 | 人 / 決まり | 判定 | 外れた所 |", "| --- | --- | --- | --- | --- |"]
        for r in rs:
            j = r.get("judge")
            word = "-" if j is None else (j["word"] if j["side"] == 0 else "%s %.1f" % (j["word"], j["dist"]))
            n = len(ev_by.get(r["id"], []))
            lines.append("| %s | %s | %s | %s | %s |" % (r["name"], _value(r), base.ref_text(r.get("ref")), word, n if n else ""))
        lines.append("")
    lines += ["## 出所", ""]
    for r in report["measures"]:
        ref = r.get("ref") or {}
        lines.append("- %s: 測り %s。人・決まり %s" % (r["name"], r.get("from", "-"), ref.get("source", "（無し）")))
    return "\n".join(lines) + "\n"


def timeline_md(report, top=TOP_MD):
    tl = timeline(report)
    by = {r["id"]: r for r in report["measures"]}
    lines = ["# %s の外れた所（重い順、上位 %d / %d）" % (report["label"], min(top, len(tl)), len(tl)), "",
             "重さ = 物差しの人の幅（決まりの物差しはその目盛り）を単位に、どれだけ境を越えたか。全部は outliers.csv。", "",
             "| 重さ | 時刻 | コマ | 考え方 | 物差し | 値 | 境 | 内容 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in tl[:top]:
        r = by.get(e["id"], {})
        lines.append("| %.2f | %s〜%s | %d〜%d | %s | %s | %s %s | %s | %s |" % (
            e["severity"], _fmt_t(e["t0"]), _fmt_t(e["t1"]), e["first"], e["last"], base.CONCEPT_NAMES.get(e["concept"], e["concept"]),
            r.get("name", e["id"]), base.num(e["value"]), e["unit"], base.num(e["edge"]), e["note"]))
    counts = {}
    for e in tl:
        counts[e["concept"]] = counts.get(e["concept"], 0) + 1
    lines += ["", "考え方ごとの数: " + "、".join("%s %d" % (base.CONCEPT_NAMES.get(c, c), n) for c, n in counts.items())]
    return "\n".join(lines) + "\n"


CSV_COLUMNS = ["severity", "t0", "t1", "first", "last", "concept", "id", "name", "value", "unit", "edge", "note", "listed"]


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
                    e["id"], by.get(e["id"], {}).get("name", ""), e["value"], e["unit"], e["edge"], e["note"], int(bool(e.get("listed")))])
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
    """{"rows": per measure the values of A and B, the reference and the word; "new": B's listed places that no listed
    place of A overlaps (the same measure); "gone": the same the other way}"""
    ra = {r["id"]: r for r in a["measures"]}
    rows = []
    for rb in b["measures"]:
        r0 = ra.get(rb["id"])
        ref = rb.get("ref") or (r0 or {}).get("ref")
        va = None if r0 is None else r0.get("value")
        vb = rb.get("value")
        rows.append({"id": rb["id"], "concept": rb["concept"], "name": rb["name"], "unit": rb.get("unit", ""), "a": va, "b": vb,
                     "ref": ref, "judge_a": None if r0 is None else r0.get("judge"), "judge_b": rb.get("judge"),
                     "word": base.compare(ref, va, vb, rb.get("unit", ""))})
    for r0 in a["measures"]:
        if r0["id"] not in {r["id"] for r in rows}:
            rows.append({"id": r0["id"], "concept": r0["concept"], "name": r0["name"], "unit": r0.get("unit", ""), "a": r0.get("value"),
                         "b": None, "ref": r0.get("ref"), "judge_a": r0.get("judge"), "judge_b": None, "word": None})
    la, lb = timeline(a), timeline(b)
    new = [e for e in lb if not any(x["id"] == e["id"] and _overlap(x, e) for x in la)]
    gone = [e for e in la if not any(x["id"] == e["id"] and _overlap(x, e) for x in lb)]
    return {"a": a["label"], "b": b["label"], "rows": rows, "new": sorted(new, key=lambda e: -e["severity"]),
            "gone": sorted(gone, key=lambda e: -e["severity"]), "listed": [len(la), len(lb)]}


def compare_md(c, top=30):
    lines = ["# %s と %s の比べ（tools/mv_inspect.py）" % (c["a"], c["b"]), "",
             "判定: 入った（%s は外、%s は人の四分位の中）・中のまま・近づいた・遠ざかった・直しすぎ（人の反対側へ出た）・変わらず。" % (c["a"], c["b"]),
             "外れた所の数: %s %d → %s %d。" % (c["a"], c["listed"][0], c["b"], c["listed"][1]), ""]
    by_c = {}
    for r in c["rows"]:
        by_c.setdefault(r["concept"], []).append(r)
    for cc, cname in base.CONCEPTS:
        rs = by_c.get(cc)
        if not rs:
            continue
        lines += ["## %s" % cname, "", "| 物差し | 人 / 決まり | %s | %s | 判定 |" % (c["a"], c["b"]), "| --- | --- | --- | --- | --- |"]
        for r in rs:
            w = r.get("word")
            lines.append("| %s | %s | %s | %s | %s |" % (r["name"], base.ref_text(r.get("ref")), base.num(r["a"]), base.num(r["b"]),
                                                    "-" if w is None else w["word"]))
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
