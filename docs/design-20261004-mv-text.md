# MV の文字（タイトル・クレジット・歌詞）の設計 — `tools/mv_text.py` (2026-10-04)

加賀さんの指示（2026-10-04 夜）: 「フォントはゆうた one シリーズのやつ前インストールしたと思うのでそれの中から
いい感じに選定してテキストグラフィックやモーションの編集も行って」。先行する指示: 「テキストを出したり
動かしたりして MV っぽくしてほしい」。

## 実測（この PC、2026-10-04 20:40 ごろ）

- `%LOCALAPPDATA%/Microsoft/Windows/Fonts/` に `Y1*.otf` が **204 本（117 書体）**。name 表の designer は
  **YUTAONE**（= ゆうた one）。全書体が欧文（大文字 26・小文字 26・数字 10）を持ち、**かな・漢字は 0 本**
  （cmap を fontTools で数えた。`_spike/out/hibikase/mv/fonts/fonts.json`、台本 `survey_fonts.py`）。
  → 日本語は別の書体で受ける。システムには **Noto Sans JP（可変、`NotoSansJP-VF.ttf`）**、Yu Gothic、
  BIZ UDPGothic、HG 系が入っている。
- 舞台は **真っ白**（hinata の描画 `final_01800.png` の隅は (255,255,255)）、Sour 式リン White も白主体。
  白文字は消える。文字は墨色が基本、差し色は髪の暖色（実測 (224,144,112) 付近）に寄せた琥珀。
- ffmpeg は 8.1.2（drawtext の fontsize はフレームごとの式を受ける）。Pillow 12.2、fontTools 4.63、numpy あり。

## 選定（見本帳 `specimen_1.png` / `specimen_2.png` と、静止画に重ねた `shortlist_*.png` を目で見て）

| 役割 | 書体 | 理由 |
| --- | --- | --- |
| 見出し（HIBIKASE） | **Y1RevForge** | 太い幾何学サンス。平体気味で画面幅を使える。小さくしても読める |
| 小見出し・欧文クレジット | **Y1Vectura** | 同系統で細め。字間を広げて使うと落ち着く |
| 差し色の瞬間（サビ頭のカードだけ） | **Y1Cybanin3000 Glitch** | 曲の電子音に合う崩し。常用はしない（`/` を持たないので記号は入れない） |
| 日本語（ヒビカセ・クレジット） | **Noto Sans JP**（Black 900 / Regular 400） | 幾何学寄りで RevForge と並ぶ。可変なので太さを自由に取れる |

落選: LunaChord（細すぎて動くと消える）、ZettaStructure・TypeAccelerator（N・A の崩しで可読性が落ちる）、
CosmicIndustry（A に横棒が無く "HIBIKASE" が読みにくい）、Cybanin3000 を常用（くどい）。

## 作り

- **MMD の中では何もしない**。hinata が描いた AVI に、この PC（か hinata）の ffmpeg で重ねる（前の決定どおり）。
- 文字は **Pillow で合図（cue）ごとの RGBA の連番 PNG** に描き、ffmpeg の `overlay` で重ねる。drawtext は字間・
  ワイプ・崩しが作れないので置き換える。PNG は合図の箱の大きさだけ（全画面ではない）なので軽い。
- 合図ごとに `setpts=PTS-STARTPTS+start/TB` で時刻をずらし `overlay=x:y:eof_action=pass`。音声があれば copy。
- 動き（anim）: `fade` / `rise`（24 px 上がりながら出る）/ `tracking-in`（字間を広げた状態から詰まる）/
  `wipe`（左から現れる・下線にも使う）/ `flash`（点滅 5 フレーム → 保持 → 即消え。サビ頭のカード）/
  `roll`（終わりのクレジット）。入りは 3 次の ease-out、抜けは ease-in。
- 1 行の中で欧文と日本語が混ざる（"Motion えぬた"）ので、文字種で走査を分けて書体を切り替える。
- 旧 `tools/overlay_text.py` の cues（text/start/end/style/anim/x/y の平らな一覧）も読める（style 名を対応づける）。
- 検証: 文字の無いフレームの alpha は 0、合図の箱の外に墨が出ない、tracking-in の初フレームは保持より幅が広い、
  wipe 0.5 は左半分だけ、ffmpeg の実走（2 秒の白い動画に 1 合図）で出力の長さと墨の有無。

## 追加の指示（同夜、少し後）と、それへの決め

「一部歌詞の表示とかもしたほうが表現的に良いと思う、背景の設定やグローの設定、光系のエフェクト等もいれて」

- **歌詞**: 文字の仕組みは `lyric`（下 1/3 中央、Noto Sans JP Bold、rise で出て fade で消える、琥珀の細い下線が
  wipe で引かれる）と `hook`（サビ頭の大きなカード、flash）の 2 様式を持つ。**時刻は音源が無いと決められない**。
  今はダンスの強さの区切り（`camera_D_analysis.json` の boundaries）に仮置きし、音源が来たら cues の数字を直す。
  歌詞の文言は加賀さんが出す行だけを入れる（配布物に歌詞全文を写し取らない）。
- **背景**: 舞台が白のままだとグローも光も載らない（screen 合成は白に効かない）。MMD の「背景黒」を切り替えて
  黒い舞台で描き（`menu click`、ID はこの PC の MMD で `menu list` を取って確かめる）、文字の配色は
  **palette = dark（白文字＋琥珀）を既定**、白舞台用に light（墨）も残す。MME は zip が来るまで使えないので、
  グローと光は **後処理（ffmpeg）** で付ける: `tools/mv_look.py`（別の道具。文字とは分ける）。
- **グロー**: ハイライト抽出（しきい値）→ ガウスぼかし → screen 合成。しきい値・半径・強さは JSON の look で持つ。
- **光のエフェクト**: Pillow で作った光条（ゆっくり回る柔らかい筋）と漂う玉ボケの RGBA 連番を加算で重ねる。
  10 秒のループを `-stream_loop` で回して描画を軽くする。サビ頭（hook の時刻）だけ短いフレアを足す。
- 検証は hinata の本番 AVI の前に、手元の抜粋 AVI（白舞台）では見えないので、**黒舞台の抜粋を hinata で先に 1 本**
  作ってから look を合わせる（ログオン待ち）。それまでは PIL で黒地に静止画を置いた合成で設計を見る。

## 残り（音源が来てから）

- 歌詞の cue の時刻。今は題名・クレジット・サビ頭のカード（ダンスの強さの区切りに置く。仮）。
