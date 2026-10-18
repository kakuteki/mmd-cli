"""Read the credits of MMD videos from their descriptions: the effects (MME and the rest), their authors, the tools
besides MMD, and the model, motion, camera and stage lines, then count them over a channel.

    python tools/look_credits.py META.jsonl OUT.json [--md OUT.md] [--top 60]

META.jsonl has one video a line with at least id, title and description (yt-dlp's --dump-json, or fewer fields).
The credits are the part of a description before the channel's own text (the paragraph that begins "English",
"-English-", "Hello!" or "*Reprinting without").  Their lines are fields: "Model：", "【模型】", "MME：", "Effects：",
"Tools：", "使用软件：" and the like in English, Chinese and Japanese (the lines after a key belong to it).  Effects are
found by name in the whole credits (EFFECTS: a name as written, with its variants); the authors are the names in the
effects field (split at / | 、 & and newlines, and the names in brackets after an effect), put together by their
spellings (AUTHORS); tools by name (TOOLS: short ones like PR, AE, PE only as whole words).  Each count keeps the
line it was found in, as written, as the source.
"""
import argparse
import json
import re
import sys
import unicodedata

BOILERPLATE = ("\nEnglish\n", "\nEnglish\r", "-English-", "*Reprinting without", "Hello!\n", "Hello!\r",
               "English\n\n", "\n-\n\nEnglish")

FIELD_KEYS = {
    "model": ("model", "models", "模型", "模組", "モデル"),
    "motion": ("motion", "motions", "动作", "動作", "モーション", "振付", "dance", "choreography"),
    "camera": ("camera", "镜头", "鏡頭", "カメラ", "相机", "相機", "cam"),
    "stage": ("stage", "场景", "場景", "ステージ", "舞台"),
    "music": ("music", "bgm", "音乐", "音樂", "曲", "song", "cover"),
    "facial": ("表情", "facials", "facial"),
    "effects": ("mme", "effects", "effect", "fx", "エフェクト", "特效", "效果", "渲染", "shader"),
    "tools": ("tools", "tool", "使用软件", "软件", "軟體", "ソフト", "后期", "後期", "剪辑", "剪輯", "video", "视频渲染制作",
              "视频", "渲染制作", "software"),
}

# name: patterns (case-insensitive unless the pattern says otherwise); a name written in several ways is one effect
_W = r"(?<![A-Za-z0-9_])"      # a short name is a whole word: no letter, digit or _ next to it
_E = r"(?![A-Za-z0-9_])"
EFFECTS = {
    "ray-mmd": [r"ray[-_ ]?mmd", _W + r"ray(?![A-Za-z])", r"ray-cast", r"Copyright \(C\) 2016-2017 Rui"],
    "ray-toon": [r"ray[-_ ]?toon"],
    "AutoLuminous": [r"AutoLuminous", _W + r"AL4" + _E, r"発光エフェクト"],
    "Diffusion": [r"(?<!ik)Diffusion(?!.{0,3}ik)", r"ディフュージョン"],
    "ikDiffusion": [r"ikDiffusion"],
    "MotionBlur": [r"MotionBlur", r"モーションブラー"],
    "LightBloom": [r"LightBloom"],
    "o_Bloom": [r"o_Bloom"],
    "Bloom (other)": [r"(?<![A-Za-z_])Bloom(?!.{0,2}(?:Light))"],
    "ikBokeh": [r"ikBokeh", r"ikボケ"],
    "ikClut": [r"ikClut"],
    "ikGodray": [r"ikGodray"],
    "ikPolishShader": [r"ikPolish"],
    "LWF": [_W + r"LWF" + _E],
    "PowerShader": [r"PowerShader"],
    "SvSSAO": [r"SvSSAO"],
    "HgSAO": [r"HgSAO"],
    "SSAO (other)": [r"(?<![A-Za-z])(?<!Sv)SSAO", r"(?<!Hg)(?<![A-Za-z])SAO\.fx"],
    "HgShadow": [r"HgShadow"],
    "HgSpotLight": [r"HgSpotLight"],
    "HgSL_ObjectMask": [r"HgSL_ObjectMask"],
    "ScreenTex": [r"(?<!Anime)ScreenTex"],
    "AnimeScreenTex": [r"AnimeScreenTex"],
    "A-screen (アニメ風画面スクリーン)": [r"アニメ風画面", r"A-screen"],
    "PostRimLighting": [r"PostRimLighting"],
    "PostRimLightToon": [r"PostRimLightToon"],
    "SJ_RimLight": [r"SJ_RimLight"],
    "PostDirectionalLight": [r"PostDirectionalLight"],
    "NeonPost": [r"NeonPost"],
    "PostAlphaEye": [r"PostAlphaEye"],
    "PostAlphaEffect": [r"PostAlphaEffect"],
    "FXAA/SMAA": [_W + r"FXAA" + _E, _W + r"SMAA" + _E],
    "CheapLens": [r"CheapLens"],
    "KiraKira": [r"KiraKira", r"キラキラエフェクト"],
    "dust (空中に漂う埃)": [r"空中に漂う埃", r"埃エフェクト"],
    "fog (フォグ)": [r"フォグ", _W + r"fog" + _E],
    "GradeForge": [r"GradeForge"],
    "SimpleColorEditor": [r"SimpleColorEditor"],
    "LUT / Lomograph": [r"Lomograph", _W + r"LUT" + _E],
    "WorkingFloor": [r"WorkingFloor"],
    "ExcellentShadow": [r"ExcellentShadow"],
    "sdPBR": [r"sdPBR"],
    "HAToon": [r"HAToon"],
    "toon (トゥーン)": [r"トゥーン"],
    "Genshin-like material (仿原神材质)": [r"仿原神"],
    "wdark": [r"wdark"],
    "ray lights with mask (带遮罩的ray灯光)": [r"带遮罩的ray灯光"],
    "SoftLight": [r"SoftLight"],
    "Gaussian": [r"Gaussian"],
    "Godray (other)": [r"(?<!ik)Godray", r"ゴッドレイ"],
    "LensFlare": [r"LensFlare", r"レンズフレア"],
    "Glare": [r"Glare"],
    "chromatic aberration": [r"色収差", r"ChromaticAberration", r"色差"],
    "vignette": [r"vignette", r"ビネット"],
    "film grain / noise": [r"FilmGrain", r"フィルムグレイン"],
    "o_Tonemap": [r"o_Tonemap"],
    "o_SelfOverlay": [r"o_SelfOverlay", r"SelfOverlay"],
    "Croquis": [r"Croquis"],
    "N3+CShader": [r"N3\+C", r"N2\+C"],
    "SelfBlend": [r"SelfBlend"],
    "o_SurplusFilter": [r"SurplusFilter"],
    "likelooks": [r"likelooks"],
    "grid floor (tk_grid-floor)": [r"grid-floor"],
    "CameraScreen": [r"CameraScreen"],
    "DOF (other)": [_W + r"DOF" + _E, r"_DOF", r"被写界深度"],
    "Particle_Offset": [r"Particle_Offset"],
    "o_LikeHDR": [r"LikeHDR"],
    "PostHatchingShader": [r"PostHatching"],
}

AUTHORS = {
    "Rui": ("rui", "rui_cg", "rui_g", "ruicg", "rui氏"),
    "そぼろ": ("そぼろ", "sovoro", "sovoro_mmd", "そぼろ式"),
    "ikeno": ("ikeno", "ikeno_mmd", "ik"),
    "針金P": ("針金p", "针金p", "hariganep", "針金p：hariganep"),
    "P.I.P": ("p.i.p", "pip", "p.i.", "p.i.p."),
    "ビームマンP": ("ビームマンp", "ビームマン p", "ビームマンp(ロベリア)"),
    "三金络合物": ("三金络合物", "sj"),
    "给你柠檬椰果养乐多你会跟我玩吗": ("养乐多", "给你柠檬椰果养乐多你会跟我玩吗"),
    "データP": ("データp",),
    "less": ("less",),
    "Azolt": ("azolt",),
    "RedialC": ("redialc", "redialc_", "rc"),
    "おたもん": ("おたもん",),
    "ミーフォ茜": ("ミーフォ茜",),
    "化身バレッタ": ("化身バレッタ",),
    "ましまし": ("ましまし",),
    "角砂糖": ("角砂糖",),
    "Elle": ("elle", "elle/データp"),
    "サンドマン": ("サンドマン",),
    "呉石": ("呉石",),
}

TOOLS = {
    "MikuMikuDance": [r"MikuMikuDance"],
    "Premiere Pro": [r"Premiere", r"(?-i:" + _W + r"PR" + _E + r")"],
    "After Effects": [r"After ?Effects", r"(?-i:" + _W + r"AE" + _E + r")"],
    "AviUtl": [r"AviUtl"],
    "DaVinci Resolve": [r"DaVinci", r"达芬奇", r"達芬奇"],
    "Vegas": [r"(?-i:Vegas)"],
    "CapCut / 剪映": [r"CapCut", r"剪映"],
    "SVFI": [r"(?-i:SVFI)"],
    "RIFE": [r"(?-i:" + _W + r"RIFE" + _E + r")"],
    "Topaz": [r"Topaz"],
    "Blender": [r"Blender"],
    "Unreal Engine": [r"Unreal", r"(?-i:" + _W + r"UE ?5" + _E + r")"],
    "Cinema 4D": [r"(?-i:C4D)", r"Cinema ?4D"],
    "PmxEditor": [r"PmxEditor", r"PMX ?Editor", r"(?-i:" + _W + r"PE" + _E + r")"],
    "MikuMikuMoving": [r"MikuMikuMoving", r"(?-i:" + _W + r"MMM" + _E + r")"],
}
_MMD_SHORT = re.compile(_W + r"MMD" + _E)

_COMPILED = {}


def _patterns(table):
    key = id(table)
    if key not in _COMPILED:
        _COMPILED[key] = {name: [re.compile(p, re.IGNORECASE) for p in pats] for name, pats in table.items()}
    return _COMPILED[key]


def _norm(text):
    return unicodedata.normalize("NFKC", text)


def credit_section(description):
    """the credits: the description up to the channel's own text, stripped ("" if it starts with that text)"""
    text = (description or "").replace("\r\n", "\n")
    cut = len(text)
    for marker in BOILERPLATE:
        i = text.find(marker)
        if i >= 0:
            cut = min(cut, i)
    if text.lstrip().startswith(("English", "-English-", "Hello!")):
        return ""
    return text[:cut].strip()


_KEY_LINE = re.compile(r"^\s*(?:【([^】]{1,16})】\s*[：:]?\s*|([^：:\n]{1,16}?)\s*[：:]\s*)(.*)$")


def _field_of(key):
    k = _norm(key).strip().strip("【】[]()（）").lower()
    for field, names in FIELD_KEYS.items():
        for n in names:
            if k == n or k.startswith(n):
                return field
    return None


def fields(section):
    """the fields of the credits: {field: text}; a line with a known key starts a field, the lines after it without
    one belong to it (the effects field often spans many lines)"""
    out = {}
    current = None
    for line in section.split("\n"):
        if not line.strip():
            continue
        m = _KEY_LINE.match(line)
        field = None
        if m:
            key = m.group(1) or m.group(2)
            field = _field_of(key)
        if field:
            current = field
            value = m.group(3).strip()
            out[field] = (out[field] + "\n" + value) if field in out and value else (out.get(field) or value)
        elif current:
            out[current] = (out[current] + "\n" + line.strip()) if out.get(current) else line.strip()
    return out


def _find(table, text):
    found = {}
    pats = _patterns(table)
    for line in text.split("\n"):
        n = _norm(line)
        for name, ps in pats.items():
            if name not in found and any(p.search(n) for p in ps):
                found[name] = line.strip()
    return found


def effects(section, lines=False):
    """the effects named in the credits (sorted names; lines: {name: the line it was found in})"""
    found = _find(EFFECTS, section)
    return found if lines else sorted(found)


def _canonical(token):
    t = _norm(token).strip().strip("-:：,.;").strip()
    for suffix in ("様", "氏", "さん", "様r"):
        if t.endswith(suffix):
            t = t[:-len(suffix)].strip()
    low = t.lower()
    for name, spellings in AUTHORS.items():
        if low == name.lower() or low in spellings:
            return name
    return t


_SPLIT = re.compile(r"[/／|｜、,，&＆\n]+")
_BRACKETED = re.compile(r"[（(]([^）)]{1,40})[）)]")


def authors(f):
    """the effects' authors: the names in the effects field (each split off, or in brackets after an effect),
    spellings put together (AUTHORS); tokens that name an effect are not authors"""
    text = f.get("effects", "") if isinstance(f, dict) else str(f)
    names = set()
    pats = _patterns(EFFECTS)
    for token in _SPLIT.split(text):
        token = token.strip()
        if not token:
            continue
        inner = _BRACKETED.findall(token)
        for x in inner:
            for part in _SPLIT.split(x):
                if part.strip():
                    names.add(_canonical(part))
        rest = _BRACKETED.sub("", token).strip()
        if not rest:
            continue
        n = _norm(rest)
        if any(p.search(n) for ps in pats.values() for p in ps):
            continue                                            # an effect's name, not an author
        if re.search(r"https?://|\.fx|ver\.?\s*\d|v\d", n, re.IGNORECASE):
            continue
        if len(n) > 24 or " " in n.strip() and not re.match(r"^[\w.\-]+ ?P$", n.strip()):
            continue                                            # a sentence, not a name
        names.add(_canonical(rest))
    return sorted(x for x in names if x)


def tools(section, lines=False):
    """the tools besides the effects: MikuMikuDance (also "MMD" in a tools field), editors, frame interpolators,
    other renderers"""
    f = fields(section)
    scope = f.get("tools", "")
    found = _find(TOOLS, section)
    for line in scope.split("\n"):
        if _MMD_SHORT.search(_norm(line)) and "MikuMikuDance" not in found:
            found["MikuMikuDance"] = line.strip()
    return found if lines else sorted(found)


def count(path, examples=3):
    """the credits of every video in META.jsonl counted: how many videos name each effect, author and tool (with up to
    `examples` of the lines as written), and each video's own"""
    per_video = []
    totals = {"effects": {}, "authors": {}, "tools": {}, "fields": {}}
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            n += 1
            sec = credit_section(v.get("description"))
            f = fields(sec) if sec else {}
            eff = effects(sec, lines=True) if sec else {}
            too = tools(sec, lines=True) if sec else {}
            auth = authors(f) if sec else []
            rec = {"id": v.get("id"), "title": v.get("title"), "date": v.get("upload_date"),
                   "views": v.get("view_count"), "effects": sorted(eff), "authors": auth, "tools": sorted(too),
                   "fields": sorted(f), "credits": sec}
            per_video.append(rec)
            for name, where in eff.items():
                e = totals["effects"].setdefault(name, {"videos": 0, "examples": []})
                e["videos"] += 1
                if len(e["examples"]) < examples:
                    e["examples"].append({"id": v.get("id"), "line": where})
            for name, where in too.items():
                e = totals["tools"].setdefault(name, {"videos": 0, "examples": []})
                e["videos"] += 1
                if len(e["examples"]) < examples:
                    e["examples"].append({"id": v.get("id"), "line": where})
            for name in auth:
                e = totals["authors"].setdefault(name, {"videos": 0, "examples": []})
                e["videos"] += 1
                if len(e["examples"]) < examples:
                    e["examples"].append({"id": v.get("id"), "line": _line_with(f.get("effects", ""), name)})
            for name in f:
                totals["fields"][name] = totals["fields"].get(name, 0) + 1
    with_credits = sum(1 for r in per_video if r["credits"])
    for table in ("effects", "authors", "tools"):
        for e in totals[table].values():
            e["share"] = e["videos"] / float(with_credits) if with_credits else 0.0
    return {"videos": n, "with_credits": with_credits, "effects": totals["effects"], "authors": totals["authors"],
            "tools": totals["tools"], "fields": totals["fields"], "per_video": per_video}


def _line_with(text, name):
    for line in text.split("\n"):
        if name.lower() in _norm(line).lower() or any(s in _norm(line).lower() for s in AUTHORS.get(name, ())):
            return line.strip()
    return text.split("\n")[0].strip() if text else ""


def to_md(report, top=60):
    out = ["videos %d, with credits %d" % (report["videos"], report["with_credits"]), ""]
    for table, title in (("effects", "effects"), ("authors", "authors"), ("tools", "tools")):
        out += ["### " + title, "", "| name | videos | share of credited | example (as written) |", "| --- | --- | --- | --- |"]
        items = sorted(report[table].items(), key=lambda kv: (-kv[1]["videos"], kv[0]))[:top]
        for name, e in items:
            ex = e["examples"][0] if e["examples"] else {"id": "", "line": ""}
            out.append("| %s | %d | %.1f %% | %s: %s |" % (name, e["videos"], 100 * e["share"], ex["id"],
                                                           ex["line"].replace("|", "/")[:120]))
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("meta", help="one video a line (JSON) with id, title and description")
    ap.add_argument("out", help="the counts and each video's credits (JSON)")
    ap.add_argument("--md", help="the counts as markdown tables")
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args(argv)
    report = count(args.meta)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(to_md(report, args.top))
    print("videos %d, with credits %d, effects %d, authors %d, tools %d" % (
        report["videos"], report["with_credits"], len(report["effects"]), len(report["authors"]), len(report["tools"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
