# レビュー 6: `tools/mv_text.py`（batch E）取り込み前の敵対的レビュー (2026-10-05)

対象: ブランチ `worktree-agent-ae4a7ddfdfb43b168`（先頭 b7a129b、起点 8ecbb80）。`tools/mv_text.py`・`tests/test_mv_text.py`・README の節・
`docs/reviews/2026-10-04-batch-e-mv-text.md`（以下「記録」）。
方法: 読むだけ。リポジトリは変更していない（worktree は `git status` が空のまま）。台本と出力はすべて
`C:/Users/kaga/Desktop/mmd-cli/_spike/out/verify/review6/`（`t01`〜`t22` の `.py` と `.out.txt`）。実行は Python 3.12.10 / Pillow 12.2.0 /
fontTools 4.63.0 / ffmpeg 8.1.2、この PC。MMD・schtasks は動かしていない。
レビュー中に main が 2661163 から 14f51ee へ進んだ（636caad で mv_look の setpts が `round(...)` になった。その後の 2 本は lip_timing と HANDOVER）。
mv_look との組み合わせは da44f6e の `tools/`・`tests/` で見た（mv_look は da44f6e から 14f51ee まで変わっていない）。

## 結論

重大な誤りは見つからなかった。時刻（フレーム単位）、描画域、書体の代替、太さ、色、音声の複製、残った連番の掃除、1 コマンドの合図数の上限は、
実物の ffmpeg を通して主張どおりだった。取り込んでよい水準。直したほうがよい点は中 3 件・低 12 件、試験の穴は生き残った変異 13 件。

件数: 高 0 / 中 3 / 低 12。

## 指摘

### 中-1 空白類の文字が「箱」として動画に出る。警告も出ない

- 場所: `tools/mv_text.py:282`（`has_glyph` が `ch.isspace()` を無条件に「持っている」と返す）、`:403`（行を `"\n"` だけで切る）。
- 何が起きるか: 合図の text に TAB、CR（CRLF の改行）、EM SPACE（U+2003）などが入ると、その書体の「字が無い」箱（.notdef）が描かれる。
  代替も警告も働かない。`"響かせて\r\nいくよ\r\n"`（lyric）は各行の末尾に × 入りの箱、`"Motion\tえぬた"`（credit）は語の間に箱。
- 根拠: `python t04_whitespace.py` → `exit 0`、`"warnings": []`。絵は `evidence/whitespace_tofu.png`。
  `python t03_edges.py` → `lyric CR font=NotoSansJP-VF.ttf ink=(0, -41, 46, 6)`、`credit TAB font=Y1Vectura.otf ink=(0, -16, 12, 0)`。
  `python t05_fonts.py`（fontTools の cmap と突き合わせ）→ Y1 の 3 書体は TAB・U+0085・U+1680・U+2000〜200A・U+2028・U+2029・U+202F・U+205F が
  cmap に無く墨が出る。Noto は TAB・CR・VT・FF・U+001C〜001F・U+0085・U+2000・U+2001・U+2004〜200A なども同じ。
  空白・NBSP・U+3000 は問題ない。注釈の「white space draws nothing in any face」（`:281`）は実測と合わない。
- 直し方: 行は `str.splitlines()` で切る（CR が残らない）。`has_glyph` は空白でも実際に墨が出るかを見る
  （`font.getmask(ch).getbbox() is None` のときだけ「持っている」）。どの書体にも無い空白は描かずに送り幅だけ取り、警告を出す。TAB は空白に置き換えるか誤りにする。
- 重大度: 中（黙って画面に出る。Windows で作った文字列は CRLF になりやすい）。

### 中-2 大文字と小文字だけが違う id が同じフォルダになり、片方の合図が別の合図の絵で出る

- 場所: `tools/mv_text.py:439`（重複の判定が `cue.id == other.id`）、`:918`（フォルダ名 `cue_<id>`）。
- 何が起きるか: id が `Hook` と `hook` の 2 合図は誤りにならない。Windows では同じフォルダなので、後の合図が先の合図の連番を消して書き直す。
  先の合図（文面 HI）の時刻に、後の合図の絵（KASE）が先の合図の位置に出る。終了コード 0、警告なし。
- 根拠: `python t07_commands.py` → `frames [ids that differ only in case] -> exit 0`、`folders: {'cue_Hook': 12}`、
  `cue Hook: plan canvas=[187, 163] frames=12 | picture 0 on disk size=[463, 134]`。実物の動画の静止画は `evidence/case_collision.png`
  （`python t20_evidence.py`。フレーム 12 に KASE が左上に出ている）。
- 直し方: 重複の判定を `casefold()` で行う。この変更で既存の試験は 110 本とも通る（変異 M24）。
- 重大度: 中（起きにくいが、起きると黙って違う絵になる）。

### 中-3 同じ様式・同じ置き場所でも、文面によって基線の高さが変わる

- 場所: `tools/mv_text.py:713-726`（置く箱を実際の墨まで広げ、その箱を `_anchor` が余白に当てる）。注釈 `:44` と `:293` は
  「lines of a style sit alike whatever they say」と書いているが、成り立つのは基準の箱の中だけ。
- 何が起きるか: 下に出る字（g, y, j, Q, 読点）や上に出る字（濁点）があると箱が広がり、同じ `x`・`y` の次の合図と基線がずれる。
  歌詞を同じ場所で入れ替えると行ごとに上下する。設計の追記（2026-10-05）の「題名を 1 文字ずつ出す」は、
  `ヒ` と `ヒビ` で基線が 8 px（logo・top）、4 px（middle）、3 px（lower）動く。U+3000 で幅をそろえても縦は直らない。
  **本番の合図ファイルで実際に起きている**: `_spike/out/hibikase/mv/production/cues_mv.json`（読むだけ）は題名を 1 文字 1 合図
  （`ヒ　　　`・`　ビ　　`・`　　カ　`・`　　　セ`、title_jp・104 px・lower）で出しており、4 組とも「ビ」だけ基線が 3 px 低い
  （ヒ・カ・セは y=637、ビは 640。1 つの合図に 4 文字を書けば全部 640）。
- 根拠: `python t22_production.py` → 「ビ」の行は `pen x=216.0 baseline y=640 block=(416, 102) anchor=(112, 549)`、ほかの 3 文字は
  `baseline y=637 block=(416, 96) anchor=(112, 552)`、`baseline spread 3 px`（hibikase1〜4 で同じ。出力では字は `ビ` のように表示）。
  87.4 秒の `preview` の拡大は `evidence/production_title_87.4_crop_x2.png`。
  `python t14_baseline.py`（1280x720、同じ置き場所で文面だけ変えたときの基線 y の幅）→
  `caption x=left y=bottom ... spread 7 px`（"ABC" 672、"gypsy jig" 665）、`lyric ... y=bottom spread 4 px`・`y=lower spread 2 px`、
  `logo ... y=bottom spread 15 px`、`hook ... y=top spread 30 px`（"Q"）。日本語だけの lyric は 0〜1 px。
  `python t16_misc.py` → `x=left y=top padded with U+3000 first letter's pen (x, baseline y): [(64.0, 171), (64.0, 179), (64.0, 179), (64.0, 179)]`。
  図は `evidence/baseline_caption_bottom.png`、`evidence/baseline_title_reveal_top.png`。
- 直し方: 置き場所は基準の箱で決め、墨のはみ出しは描画域だけを広げる。はみ出しが画面の外に出るときだけ内側へ寄せる。
- 重大度: 中（歌詞と題名の 1 文字ずつの表示が主な用途で、そこで見える。日本語だけの歌詞行なら 1 px 以内）。

### 低-1 入りと抜けの合計より短い合図は不透明度が上がりきらない。wipe は右側が出ないまま終わる

- 場所: `tools/mv_text.py:510`（`alpha=min(came, 1.0 - gone)`）、`:508-509`（wipe）。
- 何が起きるか: 既定の enter 0.6・exit 0.4 のまま 0.2 秒の合図を書くと最大の不透明度は 0.42、0.1 秒なら 0.23。
  wipe の 0.2 秒は箱 146 px のうち 49 px までしか現れない。警告は無い。
- 根拠: `python t01_motion.py` の E → `fade dur=0.2 ... frames=6 peak alpha=0.421`、`fade dur=0.1 ... peak alpha=0.230`、
  `wipe dur=0.2 ... max wipe=0.623 widest shown(>50% alpha)=49 of block 146`。
- 直し方: enter + exit が長さを超える合図は警告する（または両方を長さに合わせて縮める）。
- 重大度: 低。

### 低-2 flash 以外の合図は 0 枚目が完全に透明（start の次のフレームから見える）

- 場所: `tools/mv_text.py:500-515`、`render_cue`（`:873`）。注釈どおりの挙動（「picture 0 of a cue is the State at its start」）。
- 何が起きるか: fade・rise・tracking-in・wipe・roll は 0 枚目の最大 alpha が 0。合図の `start` のフレームには何も出ない。
  歌の母音のフレームに合わせて字を出す用途では 1 フレーム遅く見える。`"enter": 0` なら 0 枚目から出る。
- 根拠: `python t01_motion.py` の B → `fade f0:max=0 bbox=None | f1:max=40`、wipe・rise・tracking-in・roll も `f0:max=0`、flash は `f0:max=255`。
- 直し方: README に書く。または動きを 1 フレーム先から数える。
- 重大度: 低。

### 低-3 フレームのちょうど中間の時刻が偶数へ丸められ、向きがそろわない

- 場所: `tools/mv_text.py:602`（`int(round(Fraction))` は偶数丸め）。
- 何が起きるか: 30 fps で 0.25 秒（7.5 フレーム）は 8、0.75 秒（22.5）は 22。`[0.25, 0.75)` は 14 枚、`[0.75, 1.25)` は 16 枚。
  x.25・x.75 秒は合図に書きやすい値。ずれは半フレーム以内。
- 根拠: `python t01_motion.py` の C・D → `0.25 s -> 15/2 frames -> frame 8`、`0.75 s -> 45/2 frames -> frame 22`、
  `fps=30 [0.25,0.75): start_frame=8 frames=14`。
- 直し方: `math.floor(x + Fraction(1, 2))` で半分は常に切り上げる。
- 重大度: 低。

### 低-4 id の検査が末尾の改行を通し、書き始めてから OS の誤りで止まる

- 場所: `tools/mv_text.py:135`（`^...$` の `$` は末尾の改行の前でも一致する）。
- 何が起きるか: id `"second\n"` が検査を通り、フォルダ作成で `OSError [WinError 123]`。先の合図のフォルダは書かれた後。
  `render_sequences` の注釈「a cue file with an error leaves the folder as it was」（`:906`）と合わない。300 字の id も同じく `WinError 3`。
- 根拠: `python t16_misc.py` → `exit 2 {"ok": false, "error": {"type": "OSError", ...`、`work folder after the error: {'cue_first': 6}`。
- 直し方: `re.fullmatch` にし、長さの上限を置く。この変更で既存の試験は通る（変異 M42）。
- 重大度: 低。

### 低-5 動画の外にある合図・極端に長い合図に、警告も上限も無い

- 場所: `run_render`（`:1014-1043`）、`render_cue`（`:863`）。
- 何が起きるか: 2 秒の動画に 100 秒目の合図を書いても終了コード 0・警告なしで、見えない 30 枚を描く。動画の終わりをまたぐ合図は黙って切れる。
  `"fps": 1000000` のような書き間違いは 0.2 秒の合図で 200,000 枚を書く（このレビューでは書き終わるまで数分かかった。時間は測っていない）。
- 根拠: `python t07_commands.py` → `render outside -> exit 0 ... "warnings": []`、`pictures drawn for the cue that is never seen: 30`。
  `python t08_robust.py` → `fps 1000000  exit 0  ok cues=[('a', 0, 200000)]`。
- 直し方: `render` は ffprobe で長さも読み、外に出る合図を警告する。1 合図の枚数が大きいとき（例: 10 分ぶん超）は警告する。
- 重大度: 低。

### 低-6 BOM つき UTF-8 の合図ファイルを読めない

- 場所: `tools/mv_text.py:446`（`encoding="utf-8"`）。
- 何が起きるか: メモ帳や PowerShell 5.1 が書いた BOM つきのファイルは `is not JSON: Unexpected UTF-8 BOM` で終了コード 2。
- 根拠: `python t08_robust.py` → `UTF-8 with BOM (Notepad, PS 5.1)  exit 2  ValueError: ... Unexpected UTF-8 BOM (decode using utf-8-sig)`。
- 直し方: `encoding="utf-8-sig"`。
- 重大度: 低。

### 低-7 ffmpeg が失敗したときの報告から、原因の行が落ちる

- 場所: `tools/mv_text.py:1042`（stderr の末尾 600 字だけを返す）。
- 何が起きるか: 321x181 の動画では原因は 1 行目の `width not divisible by 2 (321x181)` だが、ffmpeg 8 は後始末の行を多く出すので
  末尾 600 字に入らない。利用者には `Could not open encoder before EOF` などしか見えない。
- 根拠: `python t19_odd.py` → `stderr is 977 characters`、`'not divisible' is in the whole: True | in the last 600: False`。
- 直し方: 先頭の数行と末尾を両方返す。奇数の大きさは ffmpeg の前に誤りにする。
- 重大度: 低。

### 低-8 AVI の PCM 音声は MP4 に `ipcm` として入る

- 場所: `tools/mv_text.py:982-983`（`-c:a copy`）。
- 何が起きるか: MMD の AVI（PCM）を `OUT.mp4` にすると音声は `pcm_s16le`・タグ `ipcm`。ffmpeg では復号でき、復号した音は入力と同一。
  ほかのプレイヤーで鳴るかは確かめていない（記録も未確認としている）。
- 根拠: `python t07_commands.py` → `out ... ('audio', 'pcm_s16le', 'ipcm', '88200', '44100')`、`decoded audio md5 ... same=True`。
- 直し方: 入力の音声が PCM のときは AAC にする（または README に `.mov` / `.mkv` を勧めると書く）。配る前に相手のプレイヤーで確かめる。
- 重大度: 低（未確認の互換性）。

### 低-9 入力が無圧縮 RGB（bgr24）のとき、文字と無関係に画面全体の色が最大 5/255 ずれる

- 場所: `ffmpeg_command`（`:963-989`。RGB から YUV への変換を既定の丸めに任せている）。合図が 0 個の経路でも同じ。
- 何が起きるか: 灰色 (128,128,128) の bgr24 の AVI が出力では (124,126,123) になる。h264・MJPEG の入力では 0。文字の色は正しい。
- 根拠: `python t12b_colour.py` → `gray_raw_bgr24 ... outside the canvases: mean abs change per channel (4.0, 2.0, 5.0)`、
  `with no cue (plain re-encode by the same command): mean abs change (4.0, 2.0, 5.0)`。
  `ffmpeg -i in_gray_raw_bgr24.avi -vf format=yuv420p,format=rgb24` → (124, 126, 123)、
  `-vf scale=flags=accurate_rnd+full_chroma_int:...` → (128, 128, 128)。
- 直し方: `-sws_flags accurate_rnd+full_chroma_int` を付ける。
- 重大度: 低。

### 低-10 縦長や幅の狭い画面では題名が大きく縮み、行の大小が逆になる

- 場所: `tools/mv_text.py:688`（倍率は高さだけ）。
- 何が起きるか: 720x1280 では倍率 1.78 で余白の内側が 492 px。logo の行は 22 %（59 px）まで縮み、下の title_jp（78 px）より小さくなる。
  幅が余白 2 つぶんより狭い画面（127x721 など）では警告が `does not fit the -1 px ... drawn at -1 %` になる。
- 根拠: `python t03_edges.py` → `title at 720x1280 ... sizes=[59, 78]`、`line 0 does not fit the 492 px ..., it is drawn at 22 %`。
- 直し方: 倍率を `min(height / 720, width / 1280)` にする。設計は 1280x720 が前提なので、当面は README に横長が前提と書くだけでもよい。
- 重大度: 低。

### 低-11 5 フレームより短い flash は暗いフレームで終わる

- 場所: `tools/mv_text.py:502-504`。
- 何が起きるか: 2 フレームの flash は alpha `[1.0, 0.0]`、4 フレームは `[1.0, 0.0, 1.0, 0.35]`。最後の 1 枚が消灯か減光。
- 根拠: `python t01_motion.py` の F。
- 直し方: 5 フレーム未満の flash は警告するか、点滅を長さに合わせて切り詰める。
- 重大度: 低。

### 低-12 引数の誤りでは標準出力が空になる

- 場所: `main`（`:1078-1117`。argparse の誤りは usage を stderr に出して終了コード 2）。README:304 は「標準出力は 1 行の JSON」。
- 根拠: `python t07_commands.py` → `['render', '...'] -> exit 2 stdout='' stderr starts 'usage: mv_text.py render ...'`。
- 直し方: README に「引数の誤りは stderr に usage」と書く（ほかの道具と同じ扱いでよい）。
- 重大度: 低。

## 試験について

`tests/test_mv_text.py` の 110 本は強い。時刻・枚数・0 枚目の絵・描画域・字の代替を壊した変異はすべて赤くなった。台本 `t10_mutants.py` は `tools/mv_text.py` の写し
（`mut/<名前>/mv_text.py`）を 1 か所だけ書き換え、試験の読み込み先を写しへ差し替えて走らせる（`run_mut.py`。worktree には触れない）。
挙動を変える変異 43 本のうち 30 本が赤、13 本が生き残った。

赤くなった主なもの: setpts の round を外す（M01）、古い連番を消さない（M02）、枚数を 1 多くする（M03）、0 枚目を次のフレームの絵にする（M04）、
太さを設定しない（M05）、字が無いときの代替をやめる（M06）、rise・tracking-in・影のぶんの描画域を取らない（M07・M11・M22）、
描画域を画面で切らない（M08）、動きをフレームの格子に乗せない（M09）、端数のずらしを逆向きにする（M10）、音声を落とす（M23）、
`eof_action=repeat`（M37）。

生き残った変異（試験が見ていない挙動）:

| 変異 | 壊したこと | 足すとよい試験 |
| --- | --- | --- |
| M13 | 置き場所のパスの `%` を `%%` にしない | `%` を含むフォルダで `render_sequences` の `pattern % 0` が実在すること |
| M14 | `COMMAND_LIMIT` を 40000 にする（Windows の 32767 を超える） | 上限が 32767 未満であること、上限ちょうどの本数 |
| M15 | IN と OUT の同一判定で大文字小文字を区別する | 大文字だけ違う OUT が誤りになること |
| M17・M31・M32・M33 | title_jp・lyric・logo の太さを 100 に、caption を 900 にする | 様式ごとに、描いた絵の墨の量が太さの順に並ぶこと |
| M34 | logo の字間 0.02 em を 0 にする | logo の行幅 |
| M18 | 空白類の扱いを変える | 中-1 の直しと合わせて TAB・CR の試験 |
| M19 | 入りの途中では抜けを無視する | 入りと抜けが重なる合図の最後のフレームの alpha |
| M35・M36・M41 | 結果・誤り・警告の ASCII 化を外す | ASCII でない文字を含む警告や誤り（id に日本語、文面に絵文字）を `main` に通す |

太さは「Noto の既定は Thin で、気づかれずに通ってはいけない」と注釈にあるが、`FontBook.font` が太さを渡さない変異（M05）を止めたのは、
小さい字の最大 alpha が 255 に届かなくなるという偶然の 1 本だけだった。様式の表の太さを書き間違えても試験は通る。

名前どおりには落ちない試験: `test_the_warnings_are_printed_as_ascii`（`tests/test_mv_text.py:1535`）。出る警告が元から ASCII だけなので、
ASCII 化を外しても通る（M35・M41）。`test_more_cues_than_a_command_line_holds_is_an_error`（`:1321`）は 400 本で誤り・60 本で通ることしか見ておらず、
上限の値を縛っていない（M14）。`test_the_shift_is_rounded...`（`:1285`）の最初の 2 行は Python の浮動小数の計算を確かめているだけで、道具を見ていない
（同じ試験の残りの行と `FfmpegTest` が実物を見ているので、試験全体は有効）。

## README・記録・注釈のうち、確かめた範囲を越えている記述

- 注釈 `:281`「white space draws nothing in any face」: 実測と合わない（中-1）。
- 注釈 `:44`・`:293`、記録 3 節「同じ様式の行は文面が違っても同じ高さに座る」: 画面の中の位置としては成り立たない（中-3）。
- 注釈 `:906`「誤りのある合図ファイルは何も書かない」: 書き込みの段階で起きる誤りには成り立たない（低-4）。
- README:304「標準出力は 1 行の JSON」: 引数の誤りでは空（低-12）。
- README:290「credit … 文字色の 70 %」: dark だけ。light は文字 (22,22,30) に対して (120,120,130)。
- 記録 7 節「箱の外の最大の変化は 8〜10/255」: 320x180 に縮めて比べた値（台本 `_spike/real_check.py` の `W, H = 320, 180`）。
  原寸では最大 50/255、最初の合図より前でも 41/255（`python t17_real.py`）。合図の前から同じ大きさなので「文字は箱の外に出ていない」という結論は変わらない。
- 記録 8 節「mv_look は合図が 1 フレーム早く出る」: 当時は正しい。main の 636caad で直っており、da44f6e の mv_look ではフレーム 16・31・46 の合図が
  計画どおりに出た（`python t13b_mv_look.py`）。
- 記録「変異試験 107 通りのうち 1 つを除いて赤」: 出力（worktree の `_spike/mutate_out.txt`）と合う。上の 13 本はその 107 通りに含まれていない。

## 確かめて問題なかったこと

- 単体試験: ブランチの全体 `Ran 523 tests ... OK (skipped=1)`、`tests.test_mv_text` は 110 本 OK。`LOCALAPPDATA` を空のフォルダに向けると
  110 本中 2 本 skip・残り OK（記録どおり）。`-W error::DeprecationWarning` でも 110 本 OK。
- main（da44f6e）の `tools/`・`tests/` にブランチの 2 ファイルを重ねた写し（`merged/`）で `tests.test_mv_look tests.test_mv_text` は 141 本 OK。
  main とブランチの両方が変えたファイルは README.md だけで、変更箇所は離れている。
- 動きの各時点（`t01_motion.py`）: fade・rise（+24 → 0 → 最後の 1 枚 −9.2 px）・tracking-in（0.6 → 0 → 0.077 em）・wipe・flash（1, 0, 1, 0.35, 1）・
  roll（一定 1.31 px/フレーム）は注釈どおり。抜けの最後の 1 枚は alpha 0.23 で、透明でも重複でもない。
- 枚数は `round(end*fps) - round(start*fps)`（両端をそれぞれ最寄りのフレームへ。`round((end-start)*fps)` とは 1 枚違うことがある）。
  30000/1001、約 30.00003、60、24、29.97 fps で、計画の枚数と ffmpeg の出力で点灯したフレーム数が一致。
- フレーム単位の時刻（`t06_ffmpeg_timing.py`）: flash 13 本を 7 種の入力（mp4 30 / 30000/1001 / 60 / 24 fps、MJPEG の AVI 約 30.00003 fps、
  無圧縮 bgr24 の AVI、mkv 29.97）に重ね、全フレームの明るさを計画と照合して全部一致。`select='eq(n\,N)'` で番号指定でも
  4.1 秒の合図は 122 消灯・123 点灯・124 消灯・125 点灯・126 減光・132 消灯。
- 実物の抜粋（`rin_hibikase_enuta_excerpt.avi`、10000000/333333 fps、300 フレーム）に記録の合図を重ねると、出力は 300 フレーム・同じ fps、
  flash はフレーム 123 と 125〜137 で変化（記録と同じ。`t17_real.py`）。
- 開始時刻が 0 でない入力（MPEG-TS 1.47 秒始まり、mkv 0.25 秒ずらし）でも合図は計画のフレームに出る。約 30.00003 fps の AVI に `--fps 30` を
  与えても 240 フレーム目まで計画どおり（`t18_ts.py`、`t21_fps_forced.py`）。
- 描画域（`t02_layout.py`）: 8 種の文面 × 6 つの動き × 20 の置き場所を 1280x720 で、4 種の文面を 640x360・1920x1080 で。計 1,920 の割り付け・
  24,960 枚を、四方に 96 px 広げた描画域の絵と比べ、画面の中で描画域の外に出る画素は 0。静止時に箱が画面の外に出る組み合わせも 0。
  dark と light で割り付けの数値は 480 通りすべて同じ。
- 長い行・1 文字・空の文面（`t03_edges.py`）: 余白に入らない行は縮んで警告、空・空白だけは `no text to draw`。2,000 文字でも 1 秒で終わる。
- 書体（`t05_fonts.py`）: Y1 の 3 書体が持たない ASCII は fontTools の cmap と `has_glyph` で一致（RevForge は `!#$%&()*+<>?@[\]^`{|}~`、
  Vectura は `%*+<>@[\]^`{|}~`、Glitch は `$%&()*+/:;<=>@[\]^`{|}~`。数字は 3 書体とも全部ある）。U+0020〜U+2E7F の空白以外の全文字で食い違い 0。
  太さは描いた結果で 900 / 700 / 400 が区別できる（「ヒビカセ響」44 px の不透明画素 3104 / 2470 / 1353、既定の Thin は 261）。
  Y1 が無い・1 本だけ無い・Noto も無い（YuGothB、meiryo、msgothic）の代替と警告は記録どおり。NFD の日本語も濁点が字に載る。
- 色（`t12b_colour.py`）: 黒・灰・白の動画に重ねた文字の色は、不透明な所で palette の値から各チャネル 4 以内。
- 音声: AAC の MP4 は複製され、復号した音の md5 が入力と一致。
- 合図 0 個は再エンコードだけ。同じ id は誤り。`../x`・空白・日本語・空・`.` を含む id は誤り。古い連番（長い実行の後の短い実行）は消える。
  空白・日本語・`%d`・`%s` を含むフォルダとファイル名でも `render` は通り、flash は 15・17・19〜29 に出る。OUT と IN が大文字違いでも同一と判定する。
- 合図ファイルの入力 91 通り（`t08_robust.py`）: JSON でない、型が違う、負の時刻、end <= start、知らない鍵、NaN、Infinity など 71 通りは
  終了コード 2 と 1 行の JSON で止まり、追跡表示（traceback）は 0。受理された 20 通りは妥当なもの（fps の文字列表記、`note` の自由記述など。
  `"fps": 1000000` も受理される。低-5）。旧形式の実ファイル 2 本（`cues_excerpt.json`、`cues_full.json`）は警告なしで読める。
- 本番の合図ファイル（`production/cues_mv.json`、24 合図）: 連番 1,929 枚を 6.2 秒・14.7 MB で描き、コマンド行は 6,169 字。警告は題名の縮小 1 件だけ。
  flash のカード（フレーム 2608）は 0 枚目から点灯、1 文字ずつの合図は 0 枚目が透明で 4 枚目（開始 +4 フレーム）に不透明になる（`t22_production.py`）。
- 1 コマンドの合図数（`t11_many.py`）: 81 字の連番パスで上限は 133 個。133 個（入力 134 本）を実際に ffmpeg へ渡して終了コード 0、5.1 秒、
  133 個とも計画のフレームに出た。道具が数えた長さ 31,660 字に対し実際のコマンド行は 30,009 字で、32,767 字より安全側。

## 実測（60 秒の合図、1280x720、30 fps、1,800 枚）

| 合図 | 描画域 | 連番を描く時間 | 連番の大きさ |
| --- | --- | --- | --- |
| 題名の組み（tracking-in） | 1224x240 | 4.7 秒 | 23.9 MB |
| 歌詞（rise） | 362x131 | 4.5 秒 | 33.3 MB |
| クレジット 12 行（roll。毎フレーム違う絵） | 312x720 | 49.0 秒（27 ms/枚） | 42.3 MB |
| カード（flash） | 799x163 | 3.9 秒 | 25.9 MB |

62 秒・1280x720 の動画への重ね（ffmpeg）: 合図なし 21.8 秒・最大 466 MB、60 秒の合図 1 本で 39〜41 秒・約 500 MB、4 本同時で 49.9 秒・874 MB。
合図は時刻に関係なく開始時に全部開かれ、入力 1 本あたりのメモリは歌詞の大きさで約 5 MB、題名の大きさで約 10 MB（40 本で 677 MB / 884 MB）。
上限いっぱい（125〜170 本）では 1〜2 GB の見込み（外挿。1280x720 で 40 本までしか測っていない）。

## 確かめられなかったこと

- ffmpeg 以外のプレイヤーでの再生: `ipcm` の音声、MJPEG 入力のときの出力（フルレンジの `yuvj420p`）。音は出していない。
- hinata（Python 3.10、別の版の Pillow・FreeType・ffmpeg）。試験は画素数を固定値で見ている（影 13 / 17 px、ワイプの縁 152 px、7 文字 322 px など）ので、
  版が違うと落ちるおそれがある。
- 動きの見え方（tracking-in が整数画素で刻むこと、roll）。数値と静止画だけを見た。
- 曲全体（7,742 フレーム）に数十本の合図を 1280x720 で重ねる実行。上のメモリは外挿。
- 黒い舞台・alpha つきの実物の AVI に dark を重ねた絵。
- Y1 の無い実機（環境変数で模しただけ）。
- 中-1・中-2 が今後の合図ファイルでどの程度起きるか。いまある 3 本（`production/cues_mv.json`、`cues_excerpt.json`、`cues_full.json`）には、
  該当する空白類も、大文字小文字だけが違う id も無い（確認済み）。中-3 だけが本番のファイルで起きている。

## 証拠の置き場所

`C:/Users/kaga/Desktop/mmd-cli/_spike/out/verify/review6/` に台本（`t01_motion.py` 〜 `t22_production.py`、`run_mut.py`、`ff.py`、`load.py`）と
出力（同名の `.out.txt`）。途中で作った動画と連番（約 490 MB）は消した。台本を走らせれば作り直される
（`t21` は `t06` の後、`t12b` は `t12` の後、`t13b` は `t13` の後、`t19`・`t20` は `t07` の後に走らせる）。絵は `evidence/`:

- `whitespace_tofu.png` — 中-1。CRLF・TAB・EM SPACE が箱になった `preview`（実物）。
- `case_collision.png` — 中-2。id `Hook` の時刻に `hook` の絵が出ている動画の 2 フレーム（実物）。
- `production_title_87.4_crop_x2.png` — 中-3。本番の合図ファイルの 87.4 秒（題名の 4 文字。ビだけ 3 px 低い。2 倍に拡大）。
- `baseline_caption_bottom.png`、`baseline_title_reveal_top.png`、`baseline_hook_top.png` — 中-3。同じ置き場所の 2 つの文面を色を変えて重ねた図。
