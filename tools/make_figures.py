"""Draw the figures of the README from measured data.

    python tools/make_figures.py [--chrome PATH]

Writes docs/img/architecture.png, mmd-window-annotated.png and mmd-window-model-annotated.png.  The
pictures are HTML with inline SVG, turned into PNG by a headless Chrome (no window is opened).

Inputs:
    docs/img/mmd-window.png         a real capture of the MMD v9.32 window (camera mode, empty project)
    docs/img/mmd-window-model.png   the same with a model selected (tools/dump_controls.py --capture-model)
    docs/controls-v932.json         position of every control in both modes (tools/dump_controls.py)
"""
import argparse
import base64
import html
import json
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
FONT = "'Yu Gothic UI', 'Meiryo', sans-serif"
CHROME_CANDIDATES = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

# (label, command, control ids): boxes are the bounding boxes of the controls
COMMON_TOP = [
    ("フレーム移動", "mmd frame get / set N / next / prev / next-key / prev-key / first / last",
     [417, 418, 419, 532, 533, 558, 559]),
    ("指定フレームへ移動", "frame set が内部で使う（番号を入れて Go）", [553, 554, 555]),
    ("表示の切替", "mmd control set ID on|off", [551, 552, 556, 557]),
    ("キーの範囲選択・コピー・削除", "mmd control click ID / set ID 値",
     [415, 416, 420, 421, 422, 423, 424, 425, 426, 429, 434]),
    ("補間曲線", "mmd control click ID / set ID 値", [430, 431, 432, 433, 530]),
]
COMMON_RIGHT = [
    ("視点", "mmd control click ID", [402, 403, 404, 405, 406, 407, 412, 531, 535]),
    ("再生", "mmd play --from --to --wait / mmd stop", [408, 409, 410, 411, 413, 414, 534]),
]
CAMERA_GROUPS = COMMON_TOP + [
    ("モデルの一覧と読込", "mmd model load / list / select / delete",
     [435, 436, 437, 438, 439, 440, 441, 442, 443, 444, 445]),
    ("カメラ", "mmd camera get / set --fov --perspective --register", [446, 447, 448, 449, 450, 451, 452]),
    ("カメラの位置・角度・距離", "mmd camera set --pos --rot --distance",
     [537, 538, 539, 540, 541, 542, 543, 544, 545, 546, 547, 548, 549, 550]),
    ("照明", "mmd light get / set --rgb --dir --register",
     [455, 456, 457, 458, 459, 460, 461, 462, 463, 464, 465, 466, 467, 468]),
    ("セルフ影", "mmd control click ID / set ID 値", [560, 561, 562, 563, 564, 565]),
    ("アクセサリ", "mmd accessory load / list / get / set / delete",
     [471, 472, 473, 474, 475, 476, 477, 478, 479, 480, 481, 482, 483, 484, 485, 486, 487]),
] + COMMON_RIGHT
MODEL_GROUPS = COMMON_TOP + [
    ("モデル", "mmd model select / delete / show / hide（438 は表示・IK の登録）",
     [435, 436, 437, 438, 439, 440, 441, 442, 443, 444, 445]),
    ("ボーン操作", "値は mmd bone set（vmd を作って登録）。ボタンは mmd control click ID",
     [490, 491, 492, 493, 494, 495, 496, 497, 498, 499, 500, 501]),
    ("表情操作", "値は mmd morph set（vmd を作って登録）",
     [504, 505, 506, 507, 508, 509, 510, 511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521, 522, 523,
      524, 525, 526, 527]),
    ("選択中のボーンの位置・角度", "読むのは mmd control get ID（次のフレーム移動で更新される）",
     [537, 538, 539, 540, 541, 542, 544, 545, 546, 547, 548, 549]),
] + COMMON_RIGHT
COLORS = ["#d1495b", "#00798c", "#8f5d00", "#3b6ea5", "#6a4c93", "#2e7d32", "#b23a8f", "#555555",
          "#c1440e", "#1b6f70", "#7a5c00", "#35528c", "#9c2f2f", "#444444", "#00695c", "#5d4037"]


def esc(text):
    return html.escape(text, quote=True)


def find_chrome(explicit):
    for path in [explicit] + CHROME_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    raise SystemExit("no Chrome / Edge found: pass --chrome PATH")


def render(chrome, page_source, width, height, target):
    # Chrome may still hold files of its profile for a moment after it has written the picture
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        source = os.path.join(folder, "page.html")
        with open(source, "w", encoding="utf-8") as f:
            f.write(page_source)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--user-data-dir=" + os.path.join(folder, "profile"), "--force-device-scale-factor=1",
                        "--window-size=%d,%d" % (width, height), "--screenshot=" + target,
                        "file:///" + source.replace(os.sep, "/")],
                       check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=0x08000000)
    print("wrote", os.path.relpath(target, ROOT))


def page(width, height, body):
    return ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:#ffffff}"
            "text{font-family:%s}</style></head><body><svg xmlns='http://www.w3.org/2000/svg' width='%d' "
            "height='%d' viewBox='0 0 %d %d'>%s</svg></body></html>" % (FONT, width, height, width, height, body))


# ---- figure 1: how the pieces talk ------------------------------------------------------------

def box(x, y, w, h, title, lines, fill="#f4f6f8", stroke="#4a5560"):
    out = ["<rect x='%d' y='%d' width='%d' height='%d' rx='6' fill='%s' stroke='%s' stroke-width='1.5'/>"
           % (x, y, w, h, fill, stroke),
           "<text x='%d' y='%d' font-size='17' font-weight='700' fill='#1f2933'>%s</text>"
           % (x + 14, y + 26, esc(title))]
    for i, line in enumerate(lines):
        out.append("<text x='%d' y='%d' font-size='14' fill='#323f4b'>%s</text>"
                   % (x + 14, y + 50 + 21 * i, esc(line)))
    return "".join(out)


def arrow(x1, y, x2, label, color):
    return ("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='%s' stroke-width='2.5' marker-end='url(#head-%s)'/>"
            "<text x='%d' y='%d' font-size='13.5' fill='%s' text-anchor='middle'>%s</text>"
            % (x1, y, x2, y, color, color[1:], (x1 + x2) // 2, y - 8, color, esc(label)))


def architecture():
    width, height = 1280, 700
    send, read = "#00798c", "#b3541e"
    parts = ["<defs>"]
    for color in (send, read):
        parts.append("<marker id='head-%s' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' "
                     "markerHeight='7' orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='%s'/>"
                     "</marker>" % (color[1:], color))
    parts.append("</defs>")
    parts.append("<text x='40' y='44' font-size='22' font-weight='700' fill='#1f2933'>%s</text>"
                 % esc("mmd-cli の仕組み: 窓を前に出さずに操作し、結果を文字で読み返す"))
    parts.append(box(40, 80, 330, 250, "mmd（コマンド）", [
        "1 コマンド = 1 プロセス。常駐しない",
        "結果は JSON を 1 つ出力する",
        "終了コード 0 成功 / 1 失敗",
        "  2 引数の誤り / 3 ダイアログ待ち",
        "",
        "vmd を組み立ててキーを登録する",
        "pmm を解析して場面を読む",
        "ダイアログを見張って応答する",
    ]))
    parts.append(box(880, 80, 360, 250, "MikuMikuDance v9.32（最小化のまま）", [
        "主窓のクラス名 Polygon Movie Maker",
        "コントロール 168 個（ID 400-567）",
        "メニュー（ID 200-302）",
        "",
        "タイムラインと 3D 画面は独自描画で、",
        "窓メッセージでは読めない",
    ], fill="#eef4fb", stroke="#35528c"))
    for label, y in (("WM_COMMAND: ボタンとメニュー", 112), ("WM_SETTEXT と Enter: 数値の入力欄", 150),
                     ("CB_SETCURSEL: モデルやアクセサリの選択", 188), ("WM_DROPFILES（投函）: ファイルの読込", 226)):
        parts.append(arrow(372, y, 876, label, send))
    parts.append(arrow(876, 274, 372, "WM_GETTEXT など: 入力欄・コンボ・チェックの値（mmd state）", read))
    parts.append(arrow(876, 312, 372, "メニューのチェック状態・コントロールの一覧（mmd menu list / control list）", read))
    parts.append("<rect x='452' y='350' width='16' height='4' fill='%s'/><text x='474' y='357' font-size='13' "
                 "fill='#323f4b'>%s</text>" % (send, esc("操作（CLI から MMD へ）")))
    parts.append("<rect x='660' y='350' width='16' height='4' fill='%s'/><text x='682' y='357' font-size='13' "
                 "fill='#323f4b'>%s</text>" % (read, esc("確認（MMD から CLI へ）")))
    parts.append(box(880, 380, 360, 150, "MMD が開くダイアログ", [
        "作られてから表示されるまでの間に検出",
        "透明化して画面外へ動かす（画面に出ない）",
        "既知のものは自動で応答する",
        "未知のものは開いたまま報告する（終了コード 3）",
    ], fill="#fbf3ee", stroke="#b3541e"))
    parts.append(arrow(372, 420, 876, "1 ms 間隔の見張り・応答（ファイル名の入力、OK など）", send))
    parts.append(arrow(876, 470, 372, "題名・本文・ボタン（mmd dialog list）", read))
    parts.append(box(40, 380, 330, 150, "ファイル経由の確認", [
        "pmm: 作業用の写しへ上書き保存させて",
        "  解析する（mmd dump）",
        "画像: MMD 自身に書き出させる",
        "  （mmd render image / avi）",
    ]))
    parts.append(box(40, 570, 1200, 100, "プロジェクトファイルの扱い", [
        "mmd open X.pmm は X を作業用の場所（%LOCALAPPDATA%/mmd-cli/sessions）へ写して開く。"
        "dump はその写しに保存するので X は変わらない。",
        "X が書き換わるのは mmd save のときだけ。利用者が手で開いたプロジェクトに対しては、"
        "dump と save は --in-place を付けたときだけ保存する。",
    ], fill="#f7f7f2", stroke="#7a7a6a"))
    return width, height, page(width, height, "".join(parts))


# ---- figures 2 and 3: the real window with the measured control groups ----------------------------

def annotated_window(shot_name, mode, groups, title, notes):
    with open(os.path.join(ROOT, "docs", "controls-v932.json"), encoding="utf-8") as f:
        data = json.load(f)
    rects = {c["id"]: c[mode]["rect"] for c in data["controls"]}
    with open(os.path.join(IMG, shot_name), "rb") as f:
        shot = base64.b64encode(f.read()).decode("ascii")
    win_w, win_h = data["window"]
    legend_x = win_w + 24
    width, height = win_w + 500, win_h + 110
    top = 56
    parts = ["<text x='16' y='34' font-size='20' font-weight='700' fill='#1f2933'>%s</text>" % esc(title),
             "<image x='0' y='%d' width='%d' height='%d' href='data:image/png;base64,%s'/>"
             % (top, win_w, win_h, shot)]
    boxes = []
    for label, command, ids in groups:
        xs = [rects[i][0] for i in ids] + [rects[i][0] + rects[i][2] for i in ids]
        ys = [rects[i][1] for i in ids] + [rects[i][1] + rects[i][3] for i in ids]
        boxes.append((label, command, "%d-%d" % (min(ids), max(ids)),
                      min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3))
    # areas MMD draws itself have no controls: they are bounded by the neighbouring controls
    bar, hbar = rects[427], rects[428]
    boxes.append(("タイムライン（独自描画）", "読めないので mmd dump で読む", "なし",
                  14, bar[1] - 14, bar[0] + bar[2], hbar[1] + hbar[3]))
    mode_button, info = rects[536], rects[551]
    boxes.append(("3D 画面（独自描画）", "見た目は mmd render image で確かめる", "なし",
                  mode_button[0], info[1] + info[3] + 5, win_w - 9, mode_button[1] - 3))
    origin_y = data["client_origin"][1]
    boxes.append(("メニュー", "mmd menu list / mmd menu click ID", "200-302", 8, origin_y - 21, 520, origin_y - 1))
    badge = ("<rect x='%d' y='%d' width='24' height='20' fill='%s'/><text x='%d' y='%d' font-size='14' "
             "font-weight='700' fill='#ffffff' text-anchor='middle'>%d</text>")
    for n, (label, command, id_range, x1, y1, x2, y2) in enumerate(boxes):
        color = COLORS[n % len(COLORS)]
        parts.append("<rect x='%d' y='%d' width='%d' height='%d' fill='%s' fill-opacity='0.10' stroke='%s' "
                     "stroke-width='2'/>" % (x1, y1 + top, x2 - x1, y2 - y1, color, color))
        parts.append(badge % (x1 + 1, y1 + top + 1, color, x1 + 13, y1 + top + 16, n + 1))
        ly = top + 6 + n * 48
        parts.append(badge % (legend_x, ly, color, legend_x + 12, ly + 15, n + 1))
        parts.append("<text x='%d' y='%d' font-size='15' font-weight='700' fill='#1f2933'>%s"
                     "<tspan font-weight='400' fill='#52606d'>  ID %s</tspan></text>"
                     % (legend_x + 32, ly + 15, esc(label), esc(id_range)))
        parts.append("<text x='%d' y='%d' font-size='12.5' fill='#323f4b'>%s</text>"
                     % (legend_x + 32, ly + 34, esc(command)))
    for i, note in enumerate(notes):
        parts.append("<text x='16' y='%d' font-size='13' fill='#52606d'>%s</text>"
                     % (top + win_h + 26 + 20 * i, esc(note)))
    return width, height, page(width, height, "".join(parts))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--chrome")
    args = parser.parse_args()
    chrome = find_chrome(args.chrome)
    source_note = ("枠はコントロール群の外接矩形で、位置は実行中の MMD から読んだ実測値（docs/controls-v932.json）。"
                   "色の枠・番号・右の一覧はこの図で描き足した。")
    figures = [
        ("architecture.png", architecture()),
        ("mmd-window-annotated.png", annotated_window(
            "mmd-window.png", "camera_mode", CAMERA_GROUPS,
            "MMD の窓と mmd-cli のコマンドの対応: カメラ・照明・アクセサリを選んでいるとき",
            ["元の画像: MikuMikuDance v9.32 (x64) の窓を PrintWindow で取り込んだもの（1280x770、新規プロジェクト）。",
             source_note])),
        ("mmd-window-model-annotated.png", annotated_window(
            "mmd-window-model.png", "model_mode", MODEL_GROUPS,
            "MMD の窓と mmd-cli のコマンドの対応: モデルを選んでいるとき",
            ["元の画像: MikuMikuDance v9.32 (x64) の窓を PrintWindow で取り込んだもの（1280x770、同梱の「ダミーボーン」を読込済み）。",
             source_note])),
    ]
    for name, (width, height, source) in figures:
        render(chrome, source, width, height, os.path.join(IMG, name))


if __name__ == "__main__":
    main()
