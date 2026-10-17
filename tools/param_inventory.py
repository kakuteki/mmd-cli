"""The tuned values of the MV's tools, taken from the code, in the order the v11 rebuild re-tunes them (adapt, 2026-10-17:
after retarget and rig the dance's lengths and the model change, and every value tuned on the old ones is to be looked
at again; this table is the list, made from the code, not by hand).

    python tools/param_inventory.py [--json docs/params.json] [--md docs/params.md] [--notes docs/params_notes.json]
    python tools/param_inventory.py --check        # exit 1 when the files are not what the code gives, or a note is stale

What is taken (every tools/*.py and tools/mvi/*.py, by its syntax tree, nothing is run):
* const: a module-level name in capitals given a value with a number in it (a tuple target gives one entry each; a dict
  of numbers gives one entry per key, NAME.key.key, its comments from inside the dict);
* option: a command-line option's default (add_argument with default=, a number, a string or a constant's name: then
  the constant's value, and the constant's row names the option);
* default: a number a function's keyword defaults to (thr_mm_s=50.0), not a name, None, True or False.
Each with its comment: the comment on its line(s) and the comment-only lines right after that stand further in
(the continuation), and the comment block right above (``above``).
The unit is read from the name's end (_CM, _MM, _M, _DEG, _S, _MS, _HZ, _PX, _DEG_S, _MM_S ...) and the comment's start
("units/s^2:", "cm:", "(4 mm)" ...).  What a value depends on, read from the unit and the words of its comment (an
estimate, written as such in the table): body (a length, speed or acceleration in cm, mm, m or model units: the size
of the body and of the dance's moves), gravity (an acceleration or a word of gravity), dance (measured on the song, the
dance, its trace, its beats or a version), model (measured on Sour's Rin's model: White.pmx, her bones, morphs,
materials, physics), people (from people's measures) and literature (a cited study).  review: "retarget" for body and
gravity, "rig" for model, "dance" for the dance alone (to measure again after the rebuild).
docs/params_notes.json adds where a value was decided in the records (HANDOVER's items, the reviews) by "tool:NAME";
a note whose value is gone is stale (--check fails).  ORDER is the rebuild's order (from upstream: what a later layer
reads first) with the measures of tools/mv_inspect.py that check each step; every tool has a place in it or in
CHECKERS (the test says so).
"""
import argparse
import ast
import io
import json
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
NOTES = os.path.join(DOCS, "params_notes.json")
OUT_JSON = os.path.join(DOCS, "params.json")
OUT_MD = os.path.join(DOCS, "params.md")
FORMAT = 1

# ---- the rebuild's order ---------------------------------------------------------------------------------------------
# (step, title, tools, what the step makes, the measures of tools/mv_inspect.py that check it, other checks).  From the
# v10 build (hinata v10/NOTES.md: motor -> spine -> feet0 -> balance -> feet -> wb -> hands -> skirt -> gaze -> face ->
# lips -> eye_optics -> render) and its inputs (v4s -> breath -> anatomy: variants/v5a/anat_v5a.vmd; the arms opened 6
# degrees and fix_twist before the smoothing); retarget and rig (other branches, 2026-10-17) go first.
ORDER = [
    (1, "模型の写し（rig の受け持ち）", ["pmx_rig.py", "rig_skin.py", "pmx_spine.py", "pmx_eyes.py", "pmx_skirt.py"],
     "骨とモーフの受け皿・皮付け・物理（枝 rig）、背骨の骨 2 本・目の光の骨 4 本・スカートの天井 70 を足したモデルの写し",
     ["skirt.floor_over122_frames", "skirt.floor_max", "pixels.pants_frames"], ["rig_check.py", "spine_check.py", "skirt_probe.py"]),
    (2, "踊りを体に写す（retarget の受け持ち）と手捩", ["retarget.py", "fix_twist.py"],
     "体格の写し（枝 retarget）、腕の開き 6 度（_spike の台本）、手捩の 180 度を手首へ",
     ["feet.under_floor_frames", "feet.ik_miss_floor_frames"], ["motion_fk.py"]),
    (3, "平滑化と手ぶれ除去（v4s）", ["smooth_motion.py"], "キーを曲線で通し直し、密なキーのゆらぎを均す",
     ["spikes.centre_per_min", "spikes.wrist_R_per_min", "spikes.wrist_L_per_min", "spikes.head_per_min", "arms.wrist_8hz_pct",
      "arms.wrist_3_6hz_pct", "upper.head_stop_ms"], ["motion_jerk.py"]),
    (4, "呼吸", ["breath_layer.py"], "胸と肩の呼吸、止めの間の動き", ["upper.head_stops_per_min", "upper.upper_sudden_stops_per_min"], []),
    (5, "関節の拘束", ["anatomy_layer.py"], "ひじの蝶番・上腕のねじり・胴と首の分け直し・肩甲帯・可動域",
     ["arms.a09_shoulder_elbow_L", "arms.a09_shoulder_elbow_R"], []),
    (6, "運動（遅れと堅さ、--preset human --elbow-hinge on）", ["motor_layer.py"], "近位から遠位の時刻、追従の柔らかさ、ひじの蝶番",
     ["arms.a09_shoulder_elbow_L", "arms.a09_shoulder_elbow_R", "arms.a09_elbow_wrist_L", "arms.a09_elbow_wrist_R",
      "upper.head_sudden_stops_per_min", "upper.head_stop_ms"], []),
    (7, "背骨 4 本へ配る", ["spine_layer.py"], "体幹の曲がりを解剖学の割合で腰椎上部・上半身2・胸椎上部へ",
     ["upper.upper_sudden_stops_per_min", "upper.chest_follow"], ["spine_check.py"]),
    (8, "足（最初の足の層 feet0、--landing off）", ["foot_layer.py"], "転がり・母指球・床に入れない・距骨下",
     ["feet.under_floor_frames", "feet.ik_miss_floor_frames"], ["sink_check.py", "leg_ik.py"]),
    (9, "体重（順 C の balance）", ["balance_layer.py"], "片足立ちの重心・XcoM の余裕・腰の下向きの加速度の上限・宙・突起のならし",
     ["gravity.centre_down_max", "gravity.centre_down_gt98_pct", "skirt.floor_over122_frames", "skirt.floor_max",
      "balance.com_lateral_cm", "balance.moving_com_lateral_cm", "balance.moving_mos_ml_cm", "balance.still_com_lateral_cm",
      "balance.touchdown_xcom_cm", "gravity.landing_sink_cm", "gravity.jump_apex_lowered", "gravity.beat_dips_weak",
      "spikes.centre_per_min"], ["sink_check.py", "leg_ik.py"]),
    (10, "足（着地・浮きの下げ、--landing human、既定の --hover sink）", ["foot_layer.py"], "着地のひざ・浮きを床へ・つま先",
     ["feet.slide10_per_min", "feet.slide3_per_min", "feet.slide_path_cm_per_min", "feet.slide_fast_share", "feet.knee_gain_deg",
      "feet.knee_straight_pct", "feet.ik_new_miss_frames", "gravity.hover_pct", "gravity.hover_runs6_per_min",
      "gravity.air_per_min"], ["sink_check.py"]),
    (11, "接地の計画（枝 contact、査読中）", ["contact_layer.py"], "立ち足を置く・宙の放物線・体重を受ける足の浮き",
     ["gravity.hover_pct", "gravity.hover_runs6_per_min", "balance.single_share_pct", "balance.zmp_inside_pct",
      "feet.ik_new_miss_frames", "gravity.jump_apex_lowered", "spikes.centre_per_min"], ["contact_check.py"]),
    (12, "上体の慣性", ["wb_layer.py", "wb_dynamics.py"], "骨盤の速い動きに頭が付く分を背骨で戻す（全身の重心・ZMP の計算器）",
     ["upper.head_follow", "upper.chest_follow", "upper.arms_follow", "upper.head_follow_2_4hz", "balance.zmp_inside_pct",
      "balance.single_share_pct", "balance.zmp_margin_single_cm", "balance.zmp_tilt_deg_per_min"], ["upper_body_check.py"]),
    (13, "手と指", ["hand_layer.py"], "指の形・遅れ・触れ・受け身の指", ["arms.finger_speed_L", "arms.finger_speed_R",
                                                                     "arms.finger_wrist_ratio_L", "arms.finger_wrist_ratio_R",
                                                                     "arms.a09_wrist_finger_L", "arms.a09_wrist_finger_R",
                                                                     "arms.rests_per_min_R"], []),
    (14, "視線", ["eye_gaze.py"], "固視とサッカード・カメラ目線・手を見る", ["eyes.edge_pct", "eyes.edge_longest_s", "eyes.eccentric15_pct"], []),
    (15, "表情", ["face_life.py"], "KAZUSA の表情を元に、時刻の型・瞼・まばたき・保持（瞳1off・HL・HL２）", [], []),
    (16, "口", ["lip_sync.py", "lip_timing.py"], "歌声と歌詞の音節で口の形と時刻（文字の時刻は lip_timing）",
     ["mouth.lag_median_ms", "mouth.lag_open_ms", "mouth.late_pct", "mouth.late_open_pct", "mouth.early_open_pct",
      "mouth.shut_singing_pct"], ["lip_check.py"]),
    (17, "目の光と寄り", ["eye_optics.py"], "光の骨を角膜反射の式で・手を見る間の寄り目・瞳孔", [], []),
    (18, "描画と後処理", ["mv_chunks.py", "mv_world.py", "mv_look.py", "mv_text.py", "make_stage.py", "mme_shadow.py", "pmm_gravity.py"],
     "区間の描画・舞台と光・床と体の影・文字・物理の重力", ["pixels.pants_frames", "pixels.shadow_rough", "pixels.shadow_total_rough"],
     ["shadow_check.py", "shadow_measure.py", "selfshadow_check.py"]),
    (19, "カメラ（加賀さんの指示で後回し）", ["make_camera.py"], "ショットの切り分けと控えめに動くカメラ", [], []),
]
# tools the sibling branches add (2026-10-17): placed above, taken from the code once they are merged
EXPECTED = {"pmx_rig.py": "rig", "rig_skin.py": "rig", "rig_check.py": "rig", "retarget.py": "retarget",
            "contact_layer.py": "contact", "contact_check.py": "contact"}
# the tools that measure, check or serve (their thresholds are the measures' rules, looked at with the measures)
CHECKERS = ["mv_inspect.py", "param_inventory.py", "spine_check.py", "skirt_probe.py", "motion_fk.py", "motion_jerk.py",
            "sink_check.py", "leg_ik.py", "upper_body_check.py", "lip_check.py", "shadow_check.py", "shadow_measure.py",
            "selfshadow_check.py", "dump_controls.py", "live_in_session.py", "run_live_tests_in_session.py", "make_figures.py",
            "mvi/a05.py", "mvi/analysts.py", "mvi/arms.py", "mvi/balance.py", "mvi/base.py", "mvi/body.py", "mvi/eyes.py",
            "mvi/feet.py", "mvi/fq.py", "mvi/gravity.py", "mvi/hb.py", "mvi/marks.py", "mvi/mouth.py", "mvi/pixels.py",
            "mvi/plot.py", "mvi/report.py", "mvi/shared.py", "mvi/skirt.py", "mvi/spikes.py", "mvi/upper.py", "mvi/vertical.py"]


def placed_tools():
    """every tool file ORDER or CHECKERS names, once"""
    out = []
    for _, _, tools, _, _, checks in ORDER:
        for t in tools + checks:
            if t not in out:
                out.append(t)
    for t in CHECKERS:
        if t not in out:
            out.append(t)
    return out


def step_of(tool):
    for step, title, tools, _, _, _ in ORDER:
        if tool in tools:
            return step
    return None


def mvi_measure_ids():
    """the measure ids tools/mv_inspect.py reports (tools/mvi/human.json names every one)"""
    with open(os.path.join(HERE, "mvi", "human.json"), encoding="utf-8") as f:
        return sorted(k for k in json.load(f) if not k.startswith("_"))


# ---- units and what a value depends on ---------------------------------------------------------------------------
_NAME_UNITS = [("_DEG_S", "deg/s"), ("_MM_S", "mm/s"), ("_CM_S", "cm/s"), ("_M_S", "m/s"), ("_U_S2", "units/s^2"),
               ("_PCT", "%"), ("_DEG", "deg"), ("_MS", "ms"), ("_HZ", "Hz"), ("_CM", "cm"), ("_MM", "mm"), ("_PX", "px"),
               ("_FRAMES", "frames"), ("_S", "s"), ("_M", "m")]
_COMMENT_UNITS = [(r"units?/s\^?2|units/s²|u/s\^?2|u/s²", "units/s^2"), (r"m/s\^?2|m/s²", "m/s^2"), (r"cm/s\^?2", "cm/s^2"),
                  (r"units?/s(?:ec(?:ond)?)?\b|units a second", "units/s"), (r"cm/s\b|cm a second", "cm/s"),
                  (r"mm/s\b", "mm/s"), (r"m/s\b", "m/s"), (r"deg(?:rees?)?/s\b|degrees a second", "deg/s"),
                  (r"model units|units?\b|u\b", "units"), (r"cm\b|centimetres", "cm"), (r"mm\b|millimetres", "mm"),
                  (r"metres|m\b", "m"), (r"deg(?:rees?)?\b|°", "deg"), (r"frames?\b|コマ", "frames"), (r"ms\b", "ms"),
                  (r"seconds?\b|s\b|秒", "s"), (r"Hz\b", "Hz"), (r"px\b|pixels?\b", "px"), (r"%|per ?cent", "%")]
LENGTH_UNITS = {"cm", "mm", "m", "units", "units/s", "units/s^2", "cm/s", "mm/s", "m/s", "m/s^2", "cm/s^2"}
ACCEL_UNITS = {"units/s^2", "m/s^2", "cm/s^2"}
WORDS = {
    "gravity": r"\bgravity\b|重力|\bg\b(?! of)|free fall|自由落下",
    "dance": r"\b(?:song|dance|dancer|dances|trace|traced|tracer|choreograph\w*|beats?|Hibikase|enuta|KAZUSA)\b|踊り|曲|ヒビカセ|"
             r"\bv(?:[2-9]|1[0-9])[a-z]?\b",
    "model": r"\bRin\b|Sour|White(?:_spine\w*)?\.pmx|\.pmx\b|\bmorphs?\b|モーフ|\bmaterials?\b|材質|\brigid\b|剛体|\bjoints? of the model|"
             r"\bthe model\b|her model|the model's|rest pose|休み",
    "people": r"\bpeople\b|\bhuman\b|\bFineDance\b|\bAIST|\bperson\b|\bpersons\b|人の",
    "literature": r"\b[A-Z][A-Za-z\-]+(?: (?:et al\.?|and|&) [A-Z][A-Za-z\-]+)?,? \(?(?:19|20)\d\d[a-z]?\)?",
}


_ANYWHERE = [(r"degrees? (?:per|a) second|deg(?:rees)?/s\b", "deg/s"), (r"(?:MMD |model )?units? (?:per|a) second", "units/s"),
             (r"\((?:MMD |model |window )?units?\b[^)]*\)", "units"), (r"\(frames?\b[^)]*\)", "frames"),
             (r"\(degrees?\b[^)]*\)", "deg"), (r"\(cm\b[^)]*\)", "cm"), (r"\(mm\b[^)]*\)", "mm"), (r"\((?:s|seconds?)\)", "s"),
             (r"\(Hz\)", "Hz"), (r",\s*cm\b", "cm"), (r",\s*mm\b", "mm"), (r",\s*frames\b", "frames"), (r",\s*degrees\b", "deg"),
             (r",\s*seconds\b", "s"), (r",\s*(?:MMD |model )?units\b", "units"), (r"\bin seconds\b", "s"), (r"\bin frames\b", "frames")]


def unit_of(name, comment):
    """the unit of a value from its name's end, else from its comment's start, else from a unit the comment names (in
    brackets or after a comma: "(model units)", ", cm (0 keeps it)") ("" when none says)"""
    parts = name.upper().split("(")[-1].rstrip(")").split(".")
    for n in reversed(parts):                         # CONTACT_MM.waist: the dict's name says it
        for suffix, unit in _NAME_UNITS:
            if n.endswith(suffix) and len(n) > len(suffix):
                return unit
    text = (comment or "").strip().lstrip("\"'([").strip()
    head = re.sub(r"^(?:MMD|model|window|the)\s+(?=units?\b|frames?\b)", "", text[:60])
    head = re.sub(r"^[\d.]+\s*(?=[a-zA-Z%°])", "", head)          # "32 ms", "4 mm (a05's contact)"
    for pat, unit in _COMMENT_UNITS:
        if re.match(r"\(?\s*(?:" + pat + r")(?=[\s:;,.)]|$)", head):
            return unit
    m = re.match(r"[^:]{0,40}\((?:[\d.]+\s*)(cm|mm|m)\b", head)
    if m:
        return {"cm": "cm", "mm": "mm", "m": "m"}[m.group(1)]
    for pat, unit in _ANYWHERE:
        if re.search(pat, text[:240]):
            return unit
    return ""


def depends(entry):
    """what the value hangs on (the module's doc): {body, gravity, dance, model, people, literature}"""
    text = " ".join(x for x in (entry.get("comment"), entry.get("above"), entry.get("help")) if x)
    unit = entry.get("unit", "")
    d = {k: bool(re.search(p, text)) for k, p in WORDS.items()}
    d["body"] = unit in LENGTH_UNITS
    d["gravity"] = unit in ACCEL_UNITS or d["gravity"]
    if entry["name"] in ("FPS", "SONG_FPS", "DT"):
        d = {k: False for k in d}
    return d


def review_of(dep):
    out = []
    if dep["body"] or dep["gravity"]:
        out.append("retarget")
    if dep["model"]:
        out.append("rig")
    if dep["dance"] and not out:
        out.append("dance")
    return "・".join(out)


# ---- scanning -----------------------------------------------------------------------------------------------------

def _comments(source):
    """line -> (column, text) of each comment, and the set of comment-only lines"""
    by, only = {}, set()
    toks = tokenize.generate_tokens(io.StringIO(source).readline)
    line_has_code = {}
    try:
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                by[tok.start[0]] = (tok.start[1], tok.string.lstrip("#").strip())
            elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                for ln in range(tok.start[0], tok.end[0] + 1):
                    line_has_code[ln] = True
    except tokenize.TokenError:
        pass
    for ln in by:
        if not line_has_code.get(ln):
            only.add(ln)
    return by, only


def _gather(by, only, first, last, col):
    """(comment, above): the comments on lines first..last and the comment-only lines right after them standing further in
    than col (the continuation); the comment-only block right above first standing no further in than col"""
    parts = [by[ln][1] for ln in range(first, last + 1) if ln in by and ln not in only]
    ln = last + 1
    while ln in only and by[ln][0] > col:
        parts.append(by[ln][1])
        ln += 1
    above = []
    ln = first - 1
    while ln in only and by[ln][0] <= col:
        above.append(by[ln][1])
        ln -= 1
    return " ".join(p for p in parts if p), " ".join(reversed([a for a in above if a]))


def _has_number(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return True
    return False


def _is_number(node):
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_number(node.operand)
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts) and all(_is_number(e) for e in node.elts)
    return False


CAPS = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _dict_entries(tool, prefix, node, source, by, only, out):
    for k, v in zip(node.keys, node.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        name = prefix + "." + k.value
        if isinstance(v, ast.Dict):
            _dict_entries(tool, name, v, source, by, only, out)
        elif _has_number(v):
            comment, above = _gather(by, only, k.lineno, v.end_lineno, k.col_offset)
            out.append({"tool": tool, "kind": "const", "name": name, "value": " ".join((ast.get_source_segment(source, v) or "").split()),
                        "line": v.lineno, "comment": comment, "above": above})


def scan_source(source, tool):
    """the entries of one tool's source (the module's doc)"""
    tree = ast.parse(source)
    by, only = _comments(source)
    out = []
    consts = {}
    for node in tree.body:
        targets, value = None, None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if not targets or len(targets) != 1:
            continue
        t = targets[0]
        if isinstance(t, ast.Name) and CAPS.match(t.id):
            if isinstance(value, ast.Dict) and any(isinstance(v, ast.Dict) or _has_number(v) for v in value.values) and \
                    all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in value.keys if k is not None):
                _dict_entries(tool, t.id, value, source, by, only, out)
                consts[t.id] = None
                continue
            if not _has_number(value):
                continue
            comment, above = _gather(by, only, node.lineno, node.end_lineno, 0)
            e = {"tool": tool, "kind": "const", "name": t.id, "value": " ".join((ast.get_source_segment(source, value) or "").split()),
                 "line": node.lineno, "comment": comment, "above": above}
            out.append(e)
            consts[t.id] = e
        elif isinstance(t, ast.Tuple) and all(isinstance(x, ast.Name) and CAPS.match(x.id) for x in t.elts):
            vals = value.elts if isinstance(value, ast.Tuple) and len(value.elts) == len(t.elts) else None
            comment, above = _gather(by, only, node.lineno, node.end_lineno, 0)
            for i, x in enumerate(t.elts):
                v = vals[i] if vals else value
                if not _has_number(v):
                    continue
                e = {"tool": tool, "kind": "const", "name": x.id, "value": " ".join((ast.get_source_segment(source, v) or "").split()),
                     "line": node.lineno, "comment": comment, "above": above}
                out.append(e)
                consts[x.id] = e
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = a.posonlyargs + a.args
            pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + \
                [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            for arg, d in pairs:
                if _is_number(d):
                    comment, above = _gather(by, only, d.lineno, d.end_lineno, 10 ** 6)
                    out.append({"tool": tool, "kind": "default", "name": "%s(%s)" % (node.name, arg.arg),
                                "value": " ".join((ast.get_source_segment(source, d) or "").split()), "line": d.lineno,
                                "comment": comment, "above": "", "function": node.name})
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            flags = [x.value for x in node.args if isinstance(x, ast.Constant) and isinstance(x.value, str)]
            opt = next((f for f in flags if f.startswith("--")), None)
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if opt is None or "default" not in kw:
                continue
            d = kw["default"]
            help_ = kw.get("help")
            help_text = ""
            if help_ is not None:
                try:
                    help_text = " ".join(str(ast.literal_eval(help_)).split())
                except ValueError:
                    help_text = " ".join((ast.get_source_segment(source, help_) or "").split())
            e = {"tool": tool, "kind": "option", "name": opt, "line": node.lineno, "comment": help_text, "above": "", "help": help_text}
            if isinstance(d, ast.Name) and d.id in consts:
                c = consts[d.id]
                e["constant"] = d.id
                e["value"] = c["value"] if c else d.id
                if c is not None:
                    c["option"] = opt
            elif _is_number(d) or (isinstance(d, ast.Constant) and isinstance(d.value, str)):
                e["value"] = " ".join((ast.get_source_segment(source, d) or "").split())
            else:
                continue
            out.append(e)
    for e in out:
        e["unit"] = unit_of(e["name"], e["comment"] or e.get("above", ""))
        e["depends"] = depends(e)
        e["review"] = review_of(e["depends"])
    out.sort(key=lambda e: (e["line"], e["name"]))
    return out


def tool_files():
    files = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    files += sorted("mvi/" + f for f in os.listdir(os.path.join(HERE, "mvi")) if f.endswith(".py") and f != "__init__.py")
    return files


def load_notes(path=NOTES):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        notes = json.load(f)
    return {k: v for k, v in notes.items() if not k.startswith("_")}


def join_notes(entries, notes):
    """the entries with their notes ("from", and any field the note overrides); the notes whose value is gone"""
    by = {"%s:%s" % (e["tool"], e["name"]): e for e in entries}
    stale = []
    for key, note in notes.items():
        e = by.get(key)
        if e is None:
            stale.append(key)
            continue
        for k, v in note.items():
            e[k] = v
    return entries, sorted(stale)


def inventory(notes_path=NOTES):
    entries = []
    for f in tool_files():
        with open(os.path.join(HERE, f), encoding="utf-8") as fh:
            src = fh.read()
        for e in scan_source(src, f):
            e["step"] = step_of(f)
            entries.append(e)
    entries, stale = join_notes(entries, load_notes(notes_path))
    for e in entries:
        if e.get("constant"):
            e["same_as"] = e["constant"]               # the option of a constant: its row is the constant's
    counted = [e for e in entries if not e.get("same_as")]
    order = []
    for step, title, tools, what, measures, checks in ORDER:
        mine = [e for e in counted if e["tool"] in tools]
        order.append({"step": step, "title": title, "tools": tools, "what": what, "measures": measures, "checks": checks,
                      "values": len(mine), "retarget": sum(1 for e in mine if "retarget" in e["review"]),
                      "rig": sum(1 for e in mine if "rig" in e["review"]),
                      "dance": sum(1 for e in mine if e["review"] == "dance"),
                      "noted": sum(1 for e in mine if e.get("from"))})
    return {"tool": "param_inventory", "format": FORMAT, "entries": entries, "order": order, "stale_notes": stale,
            "counts": {"entries": len(counted), "const": sum(1 for e in counted if e["kind"] == "const"),
                       "option": sum(1 for e in counted if e["kind"] == "option"),
                       "option_of_constant": len(entries) - len(counted),
                       "default": sum(1 for e in counted if e["kind"] == "default"),
                       "review": sum(1 for e in counted if e["review"]),
                       "retarget": sum(1 for e in counted if "retarget" in e["review"]),
                       "rig": sum(1 for e in counted if "rig" in e["review"]),
                       "dance": sum(1 for e in counted if e["review"] == "dance"),
                       "noted": sum(1 for e in counted if e.get("from"))}}


# ---- writing ------------------------------------------------------------------------------------------------------

def _cell(text, n=170):
    t = " ".join(str(text or "").split()).replace("|", "／")
    return t if len(t) <= n else t[:n - 1] + "…"


def _mark(b):
    return "○" if b else ""


def markdown(inv):
    c = inv["counts"]
    lines = ["# 調整した値の一覧（tools/param_inventory.py が作る。手で直さない）", "",
             "- 作り方: `python tools/param_inventory.py`（コードの構文木から。走らせない）。確かめ: `python tools/param_inventory.py --check`。",
             "- 何を拾うか: 大文字の名の定数で数を持つもの（辞書はキーごと）、コマンドの引数の既定、関数の数の既定。"
             "注釈はその行と続きの行、すぐ上の注釈の塊から。",
             "- 単位・依存・見直しはコードの名と注釈の言葉から推した目安（印 ○）。「記録」の欄は `docs/params_notes.json`"
             "（HANDOVER などの記録から手で付けた出所）。",
             "- 依存: 体 = cm・mm・m・単位の長さ・速さ・加速度（体と踊りの大きさで変わる）／重 = 重力に結んだ値／踊 = 曲・踊り・トレース・拍・版で測った値／"
             "模 = リンのモデル（White.pmx・骨・モーフ・材質・物理）で測った値／人 = 人の測りから／文 = 文献から。",
             "- 見直し: retarget（体・重）、rig（模）、dance（踊りだけ。組み直しの後に物差しで測り直す）。",
             "- 数: 全部 %d（定数 %d・引数 %d・関数の既定 %d。定数を既定にする引数 %d は定数の行に書き、数えない）、"
             "見直しの印 %d（retarget %d・rig %d・踊りだけ %d）、記録の出所つき %d。" % (
                 c["entries"], c["const"], c["option"], c["default"], c["option_of_constant"], c["review"], c["retarget"], c["rig"],
                 c["dance"], c["noted"]), ""]
    if inv["stale_notes"]:
        lines += ["**記録の古い注（値が無い）**: " + "、".join(inv["stale_notes"]), ""]
    lines += ["## v11 の組み直しで見直す順番（上流から）", "",
              "| 順 | 段 | 道具 | 値 | retarget | rig | 踊り | 確かめの物差し（tools/mv_inspect.py） | ほかの確かめ |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    first = {}
    for s in inv["order"]:
        names = []
        for t in s["tools"]:
            names.append(t if t not in first else "%s（%d と同じ道具・同じ値）" % (t, first[t]))
            first.setdefault(t, s["step"])
        lines.append("| %d | %s | %s | %d | %d | %d | %d | %s | %s |" % (
            s["step"], _cell(s["title"], 60), "・".join(names), s["values"], s["retarget"], s["rig"], s["dance"],
            "、".join(s["measures"]) or "（物差しなし）", "・".join(s["checks"]) or "-"))
    lines += ["", "各段は、その段より上流をすべて直してから測る（下流の層は上流の出力を読む）。物差しは `mv_inspect.py measure`"
              "（--size legs の「脚でそろえた」値も見る）と `compare`。", ""]
    by_tool = {}
    for e in inv["entries"]:
        if not e.get("same_as"):
            by_tool.setdefault(e["tool"], []).append(e)
    seen = []
    for s in inv["order"]:
        for t in s["tools"]:
            if t in seen:
                continue
            seen.append(t)
            lines += _tool_section(t, by_tool.get(t, []), "%d. %s" % (s["step"], s["title"]))
    rest = [t for t in placed_tools() if t not in seen]
    lines += ["## 確かめの道具と部品（物差しの決め）", ""]
    for t in rest:
        lines += _tool_section(t, by_tool.get(t, []), "確かめ・部品", level="###")
    return "\n".join(lines) + "\n"


def _tool_section(tool, entries, where, level="##"):
    head = ["%s %s（%s、%d）" % (level, tool, where, len(entries)), ""]
    if not entries and tool in EXPECTED and not os.path.isfile(os.path.join(HERE, tool)):
        return head + ["（この枝にはまだ無い。枝 %s の取り込みで入る。取り込んだら `python tools/param_inventory.py` で作り直す）" % EXPECTED[tool], ""]
    if not entries:
        return head + ["（数を持つ定数・引数の既定なし）", ""]
    rows = ["| 名前 | 値 | 単位 | 行 | どう決めたか（コードの注釈） | 記録 | 体 | 重 | 踊 | 模 | 人 | 文 | 見直し |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in entries:
        d = e["depends"]
        name = e["name"] + ("（引数 %s）" % e["option"] if e.get("option") else "") + \
            ("（定数 %s）" % e["constant"] if e.get("constant") else "")
        rows.append("| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            _cell(name, 60), _cell(e["value"], 60), e["unit"] or "", e["line"], _cell(e["comment"] or e.get("above", "")),
            _cell(e.get("from", ""), 120), _mark(d["body"]), _mark(d["gravity"]), _mark(d["dance"]), _mark(d["model"]),
            _mark(d["people"]), _mark(d["literature"]), e["review"]))
    return head + rows + [""]


def write(inv, json_path=OUT_JSON, md_path=OUT_MD):
    for p in (json_path, md_path):
        d = os.path.dirname(os.path.abspath(p))
        os.makedirs(d, exist_ok=True)
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(inv, ensure_ascii=False, indent=1) + "\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown(inv))
    return json_path, md_path


def check(inv, json_path=OUT_JSON, md_path=OUT_MD):
    """what differs from what the code gives: [problem]"""
    problems = []
    want = {json_path: json.dumps(inv, ensure_ascii=False, indent=1) + "\n", md_path: markdown(inv)}
    for p, text in want.items():
        if not os.path.isfile(p):
            problems.append("%s is missing" % p)
            continue
        with open(p, encoding="utf-8", newline="") as f:
            if f.read() != text:
                problems.append("%s is not what the code gives (run tools/param_inventory.py)" % p)
    if inv["stale_notes"]:
        problems.append("stale notes: %s" % ", ".join(inv["stale_notes"]))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", default=OUT_JSON)
    ap.add_argument("--md", default=OUT_MD)
    ap.add_argument("--notes", default=NOTES)
    ap.add_argument("--check", action="store_true", help="exit 1 when the files differ from the code or a note is stale")
    a = ap.parse_args(argv)
    inv = inventory(a.notes)
    if a.check:
        problems = check(inv, a.json, a.md)
        print(json.dumps({"ok": not problems, "problems": problems, "counts": inv["counts"]}, ensure_ascii=True))
        return 1 if problems else 0
    write(inv, a.json, a.md)
    print(json.dumps({"ok": True, "counts": inv["counts"], "stale_notes": inv["stale_notes"], "json": a.json, "md": a.md},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
