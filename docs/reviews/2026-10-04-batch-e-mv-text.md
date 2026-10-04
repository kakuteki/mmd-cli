# batch E: MV の文字を Pillow の連番 PNG に描いて ffmpeg で重ねる道具（`tools/mv_text.py`）(2026-10-04)

作業場所: worktree `.claude/worktrees/agent-ae4a7ddfdfb43b168`、ブランチ `worktree-agent-ae4a7ddfdfb43b168`。
起点: main の 8ecbb80（worktree は 02608b9 で切られていたので、着手前に `git merge --ff-only main` で 8ecbb80 に進めた）。
進め方: まとまりごとに失敗する単体試験を先に書き、失敗を見てから実装し、通ることを見てコミット。MMD は起動しない。push していない。
ベースライン: `python -m unittest discover -s tests -t .` は `Ran 416 tests ... OK (skipped=1)`（この PC は Python 3.12.10、Pillow 12.2.0、ffmpeg 8.1.2）。
設計の記録: `docs/design-20261004-mv-text.md`（main の d399d46 にある。この枝には無い。下の「途中で受けた連絡」）。

途中で受けた連絡（協調役から 2 通。どちらも反映済み）:
1. 追加: 合図に `layer`（front / back）、ffmpeg を走らせずに計画を返す関数 `render_sequences`、`x` に left-third / right-third、
   `lyric` にやわらかい影、`preview` は層に関係なく描く。MMD が人物を alpha つきで書けるので、`tools/mv_look.py`（協調役が作成）が
   背景 → back の文字 → 人物 → グロー → front の文字 の順に重ねるため。
2. 設計の記録は main にあるので枝に写さない／mv_look からの呼び方（`render_sequences(doc, work_dir, size=(w, h), fps=fps)`）を変えない／
   rebase せず、枝の単体試験が自分の起点で通るかを報告する。

書式: まとまりごとに「何を作ったか／どの試験が守るか／実測／指示書に無く自分で決めたこと」。最後に確かめていないこととまとめ。

## 0. 先に測ったこと（設計を決めた事実）

- 書体: `%LOCALAPPDATA%/Microsoft/Windows/Fonts` に `Y1*.otf` が 204 本。使う 3 本（Y1RevForge / Y1Vectura / Y1Cybanin3000-Glitch）は在る。
  `C:/Windows/Fonts/NotoSansJP-VF.ttf` も在る。Noto の軸は Weight 1 本（100〜900、**既定は 100 = Thin**）。
  `set_variation_by_axes([w])` は Pillow 12.2 で通る。「あ」の送り幅は太さによらず 1 em、墨の幅だけが変わる（100 px で 400: 80 px、
  700: 84 px、900: 85 px）。
- **"HIBIKASE" を RevForge 150 px で組むと 1207 px、字間 0.02 em を入れて 1228 px**。1280 の画面の余白の内側（1152 px）に入らない。
- Y1 の 3 書体にカーニングは無い（1 文字ずつの送り幅の和 = 文字列の幅）。Vectura の空白は 1.275 em と広い。
- Y1 が持たない ASCII（fontTools の cmap と、Pillow だけで判定した結果が一致）: RevForge は `!#$%&()*+<>?@[\]^`{|}~`、
  Vectura は `%*+<>@[\]^`{|}~`、Cybanin3000 Glitch は `$%&()*+/:;<=>@[\]^`{|}~`。設計の記録にある「Glitch は `/` が無い」だけではない。
- Cybanin3000 Glitch は大文字の高さの箱から墨がはみ出す（180 px で H は −87〜+30、I と K は −117 まで）。
- Pillow の `getbbox` は、横は「送り幅の箱と墨の和」、縦は墨。
- **Pillow はグリフを整数画素にしか描かない**（x.25 は x、x.5 と x.75 は x+1 と同じ絵。Y1・Noto・Arial・Meiryo・Yu Gothic で同じ）。
- `GaussianBlur(r)` が届く距離は r = 1.5 / 3 / 6 / 9 / 12 で 4 / 8 / 15 / 23 / 31 px（r の 2.5〜2.7 倍）。
- ffmpeg 8.1.2: 連番を `setpts` でずらして `overlay=eof_action=pass` で重ねる方法は、36 枚を 9 フレームずらすとフレーム 9〜44 に
  ちょうど出る。AVI の PCM 音声は MP4 に copy できる（終了コード 0、出力に pcm_s16le）。
- **`setpts` は式の値の小数を切り捨てて刻みにする**。指示書の形 `PTS-STARTPTS+<秒>/TB` は浮動小数で 1 刻み足りなくなることがある。
  30 fps で開始フレーム 0〜19999 のうち 404 個（2 %。最初は 123）、秒を小数 6 桁で書くと 6803 個（34 %）、30000/1001 fps では 10595 個（53 %）。
  ffmpeg で確かめた: `+123/30/TB` はフレーム 122〜134 に 13 枚出る（1 フレーム早い）、`+round(123/30/TB)` は 123〜134 に 12 枚。
- 実物の抜粋 `_spike/out/hibikase/hinata_out/rin_hibikase_enuta_excerpt.avi`（main の checkout、読むだけ）: 1280x720、MJPEG、
  300 フレーム、`r_frame_rate` は `10000000/333333`（約 30.00003）。

## 1. 書体と合図ファイル

- 何を作ったか: `runs`（U+2E80 以上を日本語、それ未満を欧文として 1 行を切る）、`FontBook`（役割 logo / latin / accent / jp を
  ファイルに結びつけ、読み込んだ書体を持つ。Y1 が無ければ Noto、Noto が無ければ候補の次（YuGothB・meiryo・msgothic）で代替し
  `warnings` に書く）、`load_font`（太さは可変軸で指定。軸が無い・失敗したら既定のまま使い警告。同じ警告は 1 回）、
  `has_glyph`（その書体が文字を自分で描けるか。持たない文字の絵は U+10FFFF の絵と同じになることで見分ける）、
  `parse_cues` / `load_cues`（新形式と、旧 overlay_text の平らな一覧）。
- 守る試験: `RunsTest`、`FontFilesTest`、`LoadFontTest`、`CueFileTest`。
- 自分で決めたこと:
  - **Y1 が持たない文字は Noto で描いて警告する**。持たない文字は空の箱として描かれ、そのまま動画に出るため。
  - 合図ファイルは厳しく読む: 知らない鍵はエラー（書き間違いが黙って既定値になるのを避ける。`note` だけは自由に書ける）。
    `id` は英数字と `_` `-`（フォルダ名になる）、無ければ `c00`・`c01`…。重複はエラー。
  - 行の `size`（720 の高さでの px。旧形式の `fontsize` もここに入る）と、`text` の中の改行で複数行、を足した。
    旧道具の `--crf` と `--frames` は無い（crf は 18 固定、静止画は `preview`）。旧 `slide-left` は指示どおり rise になる（横には動かない）。
  - 片方の字種しか決まっていない様式には相方を同じ大きさで当てた: logo の日本語は Noto 900・150、sub は Noto 700・30、
    hook は Noto 900・180。title_jp / lyric / caption の欧文は Noto 自身。字間は欧文の文字にだけ掛かる（日本語は 0）。

## 2. 動き（`Motion.at`）

- 何を作ったか: 時刻から `State`（alpha・dx・dy・tracking_extra・wipe・underline）を出す。入りは 3 次 ease-out、抜けは ease-in。
  fade / rise（+24 → 0 → −12 px）/ tracking-in（0.6 → 0 → 0.1 em）/ wipe（alpha 1 のまま左から、抜けは fade）/
  flash（1・0・1・0.35・1 のあと保持、最後は切る。フレーム数で数える）/ roll（一定の速さ）。px は画面の高さに比例。
- 守る試験: `MotionTest`（12 本）。
- 指示書との違い: 抜けは ease-in なので、最後に描くフレーム（終わりの 1 フレーム前）には alpha が 1 − (11/12)³ = 0.23 残り、次で消える。
  指示どおりの式の結果で、変えていない。

## 3. 割り付け（`layout_cue`）

- 何を作ったか: 1 文字ずつ置く（送り幅 + 字間）。行を積み、箱を置き場所に当て、動きの分だけ広げた描画域（canvas）を決める。
- 守る試験: `AnchorTest`（余白 64 / 48 px、中央は 1 px 以内、三分の一、高さに比例、題名の組みが 20 通りの置き場所すべてで余白の
  内側、roll）、`LinesTest`、`CanvasTest`、`FramesTest`。
- 自分で決めたこと:
  - **余白の内側に入らない行は入る大きさまで縮めて警告する**。題名は 150 px の指定が 139 px（93 %）になる。
    1 % 刻みで縮めるので、入る最大より 1〜2 % 小さいことがある。
  - 行の上端と下端は文面でなく基準の文字の墨で決める（欧文は H で下端は基線、日本語は「国」）。同じ様式の行は文面が違っても同じ
    高さに座る。行間 0.35 em は「上の行の下端から次の行の上端まで」に取り、整数画素に丸める（静止時の字をぼかさないため）。
  - 置く箱（block）は「基準の箱」に実際の墨を足したもの（Glitch のはみ出し・下に出る字・墨の写し）。墨が描画域の外に切れない。
  - `lower` は箱の中心を高さの 5/6 に置く（下 1/3 の中央）。下の余白は割らない。
  - **roll は置き場所によらず、画面のすぐ下からすぐ上まで動かす**（指示は +H から −(箱の高さ)。上の余白に置いた箱は最後に 48 px 残る）。
  - 描画域は画面で切る（roll や字間の広がりで PNG が画面より大きくならない。overlay の x, y は負にならない）。
  - 下線は箱に 1 本（最後の行の 0.2 em 下、幅は文字の幅の 60 %、太さ 2 px）。入りに合わせて左端から伸びる。

## 4. 描画（`draw`）

- 何を作ったか: 色ごとに L のマスクへ描き、後ろから（影 → 墨の写し → 文字 → 下線）RGBA に重ねる。最後に alpha とワイプを掛ける。
- 守る試験: `DrawTest`（15 本）。
- 自分で決めたこと:
  - **透明な RGBA に直接文字を描かない**。縁の半透明の画素の色が透明な黒と混ざって暗くなり、動画に重ねると黒い縁になる。
    色ごとのマスクから作ると、縁でも色はそのままで alpha だけが半分になる（試験が画素の色を全部見ている）。
  - **文字は最寄りの整数画素に置く**（半分は切り上げ）。Pillow がそうしか描けないので、どの画素かを道具の側で決めた。
    箱ごとの移動（rise・roll の dy）の端数は、できたマスクを双線形でずらして出す。roll の 1 フレームあたりの移動を測ると
    1.92〜1.93 px で一定（整数画素だけだと 2・2・…・1 と刻む）。字間が詰まる動き（tracking-in）は整数画素のまま（速い動きなので）。
  - 影の色は palette で持つ: dark は指示どおり黒 (0,0,0)・alpha 170・ぼかし 6 px・下へ 2 px。**light は白**にした
    （墨の文字の下に黒い影を敷くと字がにじんで見えた。`_spike/look/all_hold_light.png` で確認して変更）。影は文字だけに付く（下線には無い）。
    描画域の余白は影のぶん 20 px（3 × 6 + 2）取る。試験が端の 1 画素の輪が空であることを見ている。
  - ワイプの縁は 24 px、影の届く範囲の外から外まで動く（wipe = 0 で影も見えない）。

## 5. 連番と計画（`render_sequences`、協調役の追加 2）

- 何を作ったか: `render_sequences(cues, work_dir, size=None, fps=None, book=None)`。`cues` は合図ファイルの中身（オブジェクトか旧形式の
  一覧）・そのパス・`Sheet` のどれか。全合図を割り付けてから書くので、誤りのある合図ファイルは何も書かない。印字しない。
  返すもの: `{"fps", "size": [w, h], "cues": [{"id", "layer", "x", "y", "canvas": [w, h], "start_frame", "start", "frames", "pattern"}], "warnings"}`。
  `start` は連番の 0 枚目の時刻（秒、フレームの格子に乗せた開始 = start_frame / fps）。`pattern` は絶対パス・スラッシュ区切りの printf 形式
  （フォルダ名の `%` は `%%`）。連番は `WORK/cue_<id>/f%05d.png`、0 から、ちょうど `frames` 枚。
- 守る試験: `SequencesTest`（10 本。枚数、各フレームが `draw` の結果と同じ、計画の鍵と値、相対パス、size / fps の上書き、float の fps、
  前回の残りの連番を消す、同じ絵は同じバイト列、印字しない、誤りは書く前に止まる）。
- 自分で決めたこと:
  - 前回の実行が残した連番は消す（ffmpeg は番号が途切れるまで読むので、合図を短くしても古い絵が続いてしまう）。
  - `fps` は整数ならその数、そうでなければ分数の文字列（"30000/1001"）。ffmpeg の `-framerate` にそのまま渡せる。
  - **`frames` コマンドは計画の前に `"ok": true` を付けて出す**（他のコマンドと同じ形にした。「計画そのまま」という指示との違いはこの 1 鍵）。

## 6. 動画（`ffmpeg_command`、`render` / `preview` / `frames`）

- 何を作ったか: `ffmpeg_command(video, out, plan)` は argv の一覧を返す（合図ごとに `-framerate FPS -start_number 0 -i 連番`、
  `[k:v]format=rgba,setpts=PTS-STARTPTS+round(n/d/TB)[tk];[前][tk]overlay=x=X:y=Y:eof_action=pass[vk]`、`-map [vN] -map 0:a?`、
  libx264 medium crf 18 yuv420p faststart、`-c:a copy`）。`render` は ffprobe で大きさと fps を読む（`--size` と `--fps` の両方があれば読まない）。
- 守る試験: `CommandTest`（9 本）、`MainTest`（11 本）、`FfmpegTest`（3 本。ffmpeg と ffprobe が PATH に無ければ skip）。
- 自分で決めたこと:
  - **ずらしは `round(開始フレーム/fps の分数/TB)`**。指示書の `+<秒>/TB` のままだと上の実測のとおり 1 フレーム早く出る合図がある。
  - fps は動画の値を分数のまま使う（抜粋は 10000000/333333）。絵が動画のフレームに 1 対 1 で乗る。
  - ffmpeg は OUT の隣（`名前.part.mp4`）に書き、成功したら置き換える。失敗は終了コード 1 で、元の OUT は残る。
    IN・合図ファイル・OUT が同じファイルならエラー。
  - 連番の置き場所の既定は `OUT.work`（mv_look と同じ）。消さずに残す。
  - 1 コマンドの文字数が 32000 を超える数の合図はエラーにして、分けるよう伝える（Windows の上限は 32767 文字）。入る数は連番の
    置き場所の長さで決まり、短いパス（1 合図 189 文字）で 168 個、`…/hibikase_mv.mp4.work` のような長さ（255 文字）で 125 個。
  - ffmpeg には `-nostdin` を付け、Windows では窓を作らない（`CREATE_NO_WINDOW`）。

## 7. 実物での実行（`_spike/real_check.py`、gitignore 内）

抜粋 AVI（白い舞台、10 秒）に、題名の組み（tracking-in）・クレジット（rise）・サビ頭のカード（flash、4.1〜4.6 秒）・歌詞（rise、left-third）を
palette light で重ねた。

- 出力: h264、1280x720、`10000000/333333`、300 フレーム（入力と同じ）。
- 合図の時刻: カードは計画がフレーム 123〜137、絵が変わったのは **123 と 125〜137**（124 は点滅の消灯）。題名は計画 15〜149、変化 16〜149
  （15 は alpha 0）。
- 合図の箱の外（画面の 47 %）の最大の変化は全 300 フレームで 8〜10/255（3 回の実行。最後の 1 回は最終のコード）、合図が始まる前の
  全面で 5/255。MJPEG から H.264 への再エンコードの分で、文字は箱の外に出ていない。
- 時間: 全体 11.2〜14.9 秒（連番 378 枚は 2.8〜5.1 秒、残りは ffmpeg。この PC の負荷で振れる）。連番は 4.5 MB。
- 別に測った描画: 題名（1224x240）は 1 枚 32 ms・12 KB。6 合図・684 枚で 3.1 秒・5.8 MB（静止中のフレームは描き直さない）。

## 8. mv_look と合わせた確認（枝の外、`_spike/merge_check/` と `_spike/merged/`）

- この枝の起点には `tools/mv_look.py` も `tests/test_mv_look.py` も無いので、枝の上で `python -m unittest tests.test_mv_look` は
  ImportError になる（rebase していない）。
- `git merge-tree --write-tree HEAD main`（main は 6cc16f0）は衝突なし。その結果の木を `_spike/merged/` に展開して全試験を走らせると
  `Ran 575 tests ... OK (skipped=3)`、`tests.test_mv_look tests.test_mv_text` は 134 本 OK。
- `mv_look render --cues`（合成した alpha つきの人物、back と front の合図 1 本ずつ）: 成功。back の文字は人物の脇に 996 画素・人物の上に 0 画素、
  front の文字は人物の上に出る。
- **見つけたこと（mv_look 側）**: front の合図は計画がフレーム 16 始まりなのに、出力ではフレーム 15 から出た。mv_look は
  `setpts=PTS-STARTPTS+%.3f/TB` でずらしていて、16/30 秒は "0.533" → 15.99 刻み → 切り捨てで 15 になる。30 fps では開始フレーム
  0〜8999 のうち 3068 個（ほぼ 3 個に 1 個。1・4・7・10…）が 1 フレーム早く出る計算で、16 と 31 は ffmpeg で実際にそうなった。
  `round(...)` で包めば直る（小数 3 桁のままでも直ることを ffmpeg で確認）。main の 6cc16f0 でも同じ行（275 行目）。
  mv_look はこの枝の外なので触っていない。直すと `tests/test_mv_look.py` の `setpts=PTS-STARTPTS+0.500/TB` を見ている行も変わる。

## 9. 置き換えと文書

- `tools/overlay_text.py` と `tests/test_overlay_text.py` を削除。README に「動画に文字を重ねる」の節を足した（make_camera の節の後）。
- HANDOVER.md は一度書き換えたが、main の 72a3ebf が同じ項目を書き直していて衝突するので戻した。項目の更新は取り込む側に任せる。
  `_spike/out/hibikase/mv/build_mv.md`（リポジトリの外）の手順 4 は旧道具の名前のまま。
- 設計の記録は最初のコミットで枝に写したが、連絡を受けて外した（写しは main のものと同一だった）。

## 確かめていないこと

- **曲全体（7742 フレーム）と多数の合図**。入力が数十本の ffmpeg は走らせていない（60 合図はコマンドの組み立てだけ）。
- **黒い舞台・alpha つきの実物の AVI**。dark は黒地の `preview` と、合成した人物での mv_look だけ。
- **音声つきの実物**。AAC の MP4 は copy されることを試験で、PCM の AVI → MP4 の copy は別の確認で見ただけ。PCM 入りの MP4 が
  プレイヤーで鳴るかは見ていない。
- **hinata**（Python 3.10、あちらの Pillow と ffmpeg の版）。構文を 3.9 として解析しただけで、実行していない。
- **見た目の良し悪し**は私が `preview` と静止画を見ただけ。気づいた点: Vectura の空白が広くクレジットが間延びして見える／
  かなの左端が欧文より約 6 px 右に見える／logo の下の行間（0.35 em = 49 px）は下の行間（15 px）より広い。直していない（設計の判断）。
- 動画での動きは見ていない（フレームの数値と静止画だけ）。tracking-in が整数画素で動くことの見え方、roll の実物。
- 60 fps の実物、奇数の大きさの動画（libx264 の yuv420p は偶数が要る。エラーになるはず）、Windows 以外。
- Y1 の無い PC は環境変数で模しただけ（`LOCALAPPDATA` を変えて test_mv_text の 110 本中 2 本 skip・残り OK。Noto も無い場合は
  YuGothB・meiryo・msgothic で 684 枚が描けて警告 7 件）。実機では見ていない。
- パスに空白・日本語・`%` を含むフォルダとファイル名での `render` は 1 回確かめた（flash がフレーム 15・17・19〜29 に出た）。試験には入れていない。
- 変異試験（挙動を 1 つ壊して試験が赤くなるかを見る、107 通り）は 1 つを除いて全部赤くなった。残る 1 つ（端数の取り方を floor から
  round に変える）は結果が同じになる変更。台本は `_spike/mutate.py`（リポジトリに入れていない）。

## まとめ

- コミット（ブランチ `worktree-agent-ae4a7ddfdfb43b168`、起点 8ecbb80、push していない）: a061b35（設計の記録の写し。後で外した）→
  093f9cf（書体・合図）→ c45f1f1（動き）→ 2c9f300（layer・三分の一）→ a7783db（割り付け）→ 28b5dca（描画）→ e24306a（写しを外す）→
  2d10c95（連番・計画）→ de36e87（render / preview / frames）→ 92863af（overlay_text の置き換え・README）→ e40cef5（整数画素と端数の移動）→
  14982d2（HANDOVER を戻す）→ fcc83e4（mv_look からの呼び方の試験とこの記録）→ 最後の 1 本（道具の注釈 2 か所とこの行）。
- 単体試験: `python -m unittest discover -s tests -t .` → `Ran 523 tests ... OK (skipped=1)`（416 − 3（overlay_text）+ 110（test_mv_text）。
  test_mv_text の内訳: Runs 3・FontFiles 4・LoadFont 4・CueFile 13・Motion 12・Anchor 6・Lines 10・Canvas 6・Frames 4・Draw 15・
  Sequences 10・Command 9・Main 11・Ffmpeg 3。この PC では Y1・Noto・ffmpeg が在るので 110 本とも走った）。
- 触ったファイル: 新規 `tools/mv_text.py`・`tests/test_mv_text.py`・この記録。削除 `tools/overlay_text.py`・`tests/test_overlay_text.py`。
  `README.md` は節の追加だけ。`mmd_cli/`・tests/live・HANDOVER.md は起点のまま。
- 道具の依存: Pillow（描画）と ffmpeg / ffprobe（render だけ）。numpy は使わない。`mmd` 本体の依存は増えない。
  Pillow が無ければ試験は module ごと skip する。
- 見本の絵（gitignore 内。`python tools/mv_text.py preview _spike/preview/cues_showcase.json OUT.png --at 秒` で作り直せる）:
  `_spike/preview/preview_title_hold.png`（3.0 秒）、`preview_title_entering.png`（1.2 秒、字間が詰まる途中）、`preview_hook.png`（44.7 秒）、
  `preview_lyrics.png`（62.25 秒、左右の三分の一・右はワイプの途中）。実物に重ねた静止画は `_spike/real/still_*.png`。
