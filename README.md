# mmd-cli

MikuMikuDance（MMD）を、窓を前に出さずにコマンドラインから操作する道具。
同じ PC で人が別の作業をしている間に、エージェント（Claude など）やスクリプトが裏で MMD を動かすために作った。

- MMD は最小化のまま動かす。前面に出さず、入力の焦点も奪わない。
- 操作の途中で MMD が開くダイアログは、画面に出る前に隠して自動で応答する。
- 結果は JSON で返る。画面の取り込み（スクリーンショット）を見なくても、何が起きたかを確かめられる。
- 見た目を確かめたいときは、MMD 自身に画像ファイルを書き出させる。

対象は MikuMikuDance v9.32（x64、日本語表示）と Windows。Python 3.9 以上、標準ライブラリのみ。
MMD 本体・モデル・モーションはこのリポジトリに含まれない。

![仕組み](docs/img/architecture.png)

## 導入

```
git clone https://github.com/kakuteki/mmd-cli.git
cd mmd-cli
python -m pip install --user -e .
mmd --version          # 入らない場合は python -m mmd_cli --version
```

MMD 本体は配布元（VPVP）から入手して、任意の場所に展開しておく。

## 使い方

```
mmd launch --exe C:/tools/MikuMikuDance_v932x64/MikuMikuDance.exe   # 最小化で起動。2 回目以降は --exe を省ける
mmd model load C:/models/miku/miku.pmx
mmd bone set 右腕 --rot 0 0 35 --frame 30      # フレーム 30 に右腕のキーを登録
mmd morph set まばたき 1.0                     # 現在のフレームに表情のキーを登録
mmd camera set --pos 0 12 0 --rot 5 20 0 --distance 28 --register
mmd render image C:/work/shot.png --size 640 360
mmd save C:/work/scene.pmm
mmd quit
```

それぞれのコマンドは JSON を 1 つ出す。上の `bone set` の結果（`--out` で書いたファイルの中身）:

```json
{"ok": true, "bone": "右腕", "frame": 30, "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 35.0]}
```

`mmd model load` の結果には、MMD が出した「モデル情報」ダイアログの本文（モデルのコメント）と、
自動で応答したダイアログの記録が入る。

```json
{"ok": true, "name": "初音ミク", "index": 0,
 "comment": "PolyMo用モデルデータ：初音ミク ver.1.3\n(物理演算対応モデル)\n...",
 "answered_dialogs": [{"kind": "model_info", "title": "モデル情報", "buttons": ["OK", "キャンセル"], "action": "ok"}]}
```

## ヘッドレスで使う

画面に何も出さずに使うには、`--headless` で起動する。主窓は非表示（タスクバーにも出ない）のまま動き、
ダイアログは従来どおり画面に出ない。`mmd window show` で最小化状態に戻せる。
MMD は AVI の書き出しを始めるときに自分で主窓を表示するが、mmd-cli は各コマンドの間、非表示の主窓を画面外に
置いておき、表示されても画面には出さず、終わったら隠し直す（結果の `answered_dialogs` に `hidden again` と残る）。

```
mmd launch --headless --exe C:/tools/MikuMikuDance_v932x64/MikuMikuDance.exe
mmd model load C:/models/miku/miku.pmx
mmd render image C:/work/shot.png
mmd quit
```

SSH 越し・CI・サービスのように **利用者のデスクトップの外** から呼ばれたときは、`mmd` は自分をタスクスケジューラの
一回限りのタスクとして、ログオン中の利用者のデスクトップセッションの中で走らせ、その結果を返す（結果の JSON に
`"relayed": true` が付く）。窓メッセージはデスクトップセッションを越えて届かず、MMD 自体もデスクトップの無い
セッションでは起動が終わらないためである（v9.32 で実測）。

- 利用者がそのマシンにログオンしていることが必要。モニタは要らない（仮想ディスプレイでも、切断された
  セッションでもよい）。誰もログオンしていなければ、その旨のエラーになる。
- タスクは `pythonw.exe` で走るので、デスクトップにコンソール窓は出ない。タスクは終わると消す。
  電源条件の無い XML 定義で作るので、ノート PC がバッテリー駆動でも始まる（`schtasks /Create` の既定は AC 電源のときだけ）。
- `--no-relay` で止められる。デスクトップの中にいても `--in-user-session` で強制できる。
- 待っている側で Ctrl-C しても、デスクトップ側の子は止めない（書き込みやダイアログの途中で止めると半端な状態が残る）。
  子はそのまま終わり、結果は捨てられる。
- `mmd file info` のようにファイルだけを扱うコマンドは、どこでもそのまま走る。
- 確認済み: 別の機から SSH で入ったセッション 0 から、起動（非表示）・読込・キー登録・書き出し・終了まで
  中継で通り、その間デスクトップの前面の窓は変わらず、MMD の窓は一度も表示されなかった。

## 台本をまとめて流す（batch）

1 コマンド 1 プロセスだと、起動・接続・（中継なら）タスクの登録で 1 回あたり 1〜3 秒かかる。
何十手もある台本は `mmd batch` で 1 プロセスにまとめる。

```
mmd batch script.txt            # 1 行 1 コマンド。'-' なら標準入力
mmd batch script.txt --keep-going   # 失敗した行で止めず最後まで
```

```
# script.txt   コメントと空行は飛ばす。mmd の後ろに書く形で 1 行ずつ
new
model load "C:\models\miku\miku.pmx"
frame set 30
["bone", "set", "右腕", "--rot", "0", "0", "35"]
{"id": "wink", "args": ["morph", "set", "ウィンク", "1.0"]}
render image C:\work\shot.png --size 640 360
```

行はそのまま空白で区切り、二重引用符で囲めば 1 語になる。バックスラッシュはそのまま。引用の心配をしたくなければ
JSON の配列か `{"id": ..., "args": [...]}` で書く。`--pid` などの共通オプションは `mmd batch` 側に付ける。

結果は `{"ok", "ran", "failed", "exit_code", "results": [...]}` で、`results` の各要素が行ごとの結果（行番号・引数・
その行の JSON、応答したダイアログ）。既定では失敗した行で止まり、終了コードはその行のもの（1 失敗 / 2 引数の誤り /
3 ダイアログ待ち）。`launch` を台本に入れれば、起動したインスタンスを続く行がそのまま使う。

## 状態の確かめ方

| 知りたいこと | コマンド | 仕組み |
| --- | --- | --- |
| 今の様子（モデル一覧・選択・フレーム・再生中か・保留ダイアログ） | `mmd state` | 入力欄やコンボボックスの値を読む |
| 場面の全体（キーフレーム、現在のポーズ、カメラ、照明、アクセサリ、音） | `mmd dump`、キーの一覧まで欲しいときは `mmd dump --keys` | 作業用の pmm に上書き保存させて解析する |
| 1 つのボーン・表情の現在値 | `mmd bone get 名前` / `mmd morph get 名前` | 同上 |
| カメラ・照明の値 | `mmd camera get` / `mmd light get` | 入力欄の値を読む |
| 見た目 | `mmd render image out.png` | MMD の「画像ファイルに出力」 |
| モデルの骨の親子・種類（IK、回転/移動、表示、付与、物理後）と表情の区分（眉・目・口・その他） | `mmd model info [名前]` | MMD は骨の名前しか見せないので、モデルファイル（pmx / pmd）を読む |
| vmd / vpd / pmm / pmx / pmd ファイルの中身 | `mmd file info ファイル` | MMD を使わずに解析する |
| vmd の中のキー（区間を絞って、表示値で） | `mmd motion keys F.vmd [--camera \| --bone 名前 \| --morph 名前 \| --light] [--from A --to B]` | 同上。「モーションファイルの編集」を参照 |

角度は MMD の窓に表示される値と同じ（度）。ボーンの回転は四元数（`--quat X Y Z W`）でも指定できる。

`mmd dump` の例（モデル 1 体、フレーム 30 に右腕と まばたき のキーがある場面）:

```json
{"ok": true, "frame": 30, "last_frame": 30, "view_size": [640, 360], "mode": "model", "selected_model": 0,
 "models": [{"index": 0, "name": "初音ミク", "path": "C:\\tools\\MikuMikuDance_v932x64\\UserFile\\Model\\初音ミク.pmd",
   "visible": true, "bone_count": 122, "morph_count": 16, "last_frame": 30,
   "key_counts": {"bones": 1, "morphs": 1},
   "current": {"bones": {"右腕": {"pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 35.0]}}, "morphs": {"まばたき": 1.0}}}],
 "camera": {"current_is": "editing view",
   "keys": [{"frame": 0, "pos": [0.0, 10.0, 0.0], "rot": [0.0, 0.0, 0.0], "distance": 45.0, "fov": 30, "perspective": true},
            {"frame": 30, "pos": [0.0, 12.0, 0.0], "rot": [5.0, 20.0, 0.0], "distance": 28.0, "fov": 30, "perspective": true}]},
 "light": {"current": {"rgb": [154, 154, 154], "dir": [-0.5, -1.0, 0.5]}},
 "accessories": [], "wave": {"enabled": false, "path": ""}}
```

（一部の項目を省いてある。モデルを選択している間、`camera.current` は MMD の編集用の視点になる。
場面のカメラは `camera.keys` か `mmd camera get` で見る。）

### モデルの骨と表情

`mmd model info` は、読み込み中のモデル（名前・番号、省略なら選択中）のファイルを `dump` の結果から探して読む。
ファイルのパス（.pmx / .pmd）を渡せば、MMD が無くてもそのファイルを読む（`file info` と同じで、中継もしない）。
ファイルのパスを渡せばそのファイルを読む（MMD が動いていなくてよいのは `mmd file info ファイル`。`--brief` で件数と名前だけ）。
pmx 2.0 / 2.1 と pmd 1.0 に対応し、どちらも同じ形で返す。pmd の骨の種別（回転・IK・IK影響下・非表示 など）は pmx の旗に写してある。

```
mmd model info 初音ミク
mmd file info C:/models/初音ミク.pmd --brief
```

```json
{"ok": true, "path": "C:\\tools\\MikuMikuDance_v932x64\\UserFile\\Model\\初音ミク.pmd", "format": "pmd", "version": 1.0,
 "name": "初音ミク", "name_en": "Miku Hatsune", "comment": "PolyMo用モデルデータ：初音ミク ver.1.3\n...", "comment_en": "...",
 "counts": {"vertices": 9036, "faces": 14997, "textures": 1, "materials": 17, "bones": 122, "morphs": 15, "display_frames": 8,
            "rigid_bodies": 45, "joints": 27},
 "bones": [{"index": 0, "name": "センター", "name_en": "center", "parent": null, "layer": 0,
            "flags": {"rotate": true, "translate": true, "visible": true, "enabled": true, "ik": false, "append_rotate": false,
                      "append_translate": false, "fixed_axis": false, "local_axis": false, "physics_after": false, "external_parent": false},
            "append": null, "ik": null},
           {"index": 4, "name": "左目", "name_en": "eye_L", "parent": 3, "layer": 0, "flags": {"rotate": true, "visible": true, "enabled": true, "append_rotate": true, "...": false},
            "append": {"parent": 71, "ratio": 1.0}, "ik": null},
           {"index": 83, "name": "左足ＩＫ", "name_en": "leg IK_L", "parent": null, "layer": 0, "flags": {"rotate": true, "translate": true, "visible": true, "enabled": true, "ik": true, "...": false},
            "append": null, "ik": {"target": 40, "loops": 40, "angle": 0.5, "links": [39, 38]}}],
 "morphs": [{"index": 5, "name": "まばたき", "name_en": "blink", "panel": "eye", "kind": "vertex", "offsets": 147},
            {"index": 9, "name": "あ", "name_en": "a", "panel": "mouth", "kind": "vertex", "offsets": 88}],
 "display_frames": [{"name": "表情", "name_en": null, "special": true, "items": [{"kind": "morph", "index": 9}, {"kind": "morph", "index": 10}]},
                    {"name": "ＩＫ", "name_en": "IK", "special": false, "items": [{"kind": "bone", "index": 80}, {"kind": "bone", "index": 81}]}]}
```

（骨 122 本・表情 15 個・表示枠 8 個のうち数個だけ示した。`index` はファイルの中の番号で、`parent`・`append.parent`・`ik.target`・
`ik.links`・表示枠の `items` はこの番号で指す。pmd では表情の番号が MMD の内部番号と同じになるよう、ファイルの skin 番号をそのまま使う
（0 番の base は一覧に出さない）。`panel` は眉 `eyebrow` / 目 `eye` / 口 `mouth` / その他 `other`。`kind` は pmx の種類
（`group` `vertex` `bone` `uv` `uv1`〜`uv4` `material` `flip` `impulse`）で、pmd は常に `vertex`。IK の `angle` は pmx が
ラジアン、pmd はファイルの値のまま（pmx の 1/4）。`display_frames` は MMD の左の枠一覧で、`special` は Root と 表情。）

## モーションファイルの編集（MMD なし）

配布されたカメラモーションの一部の区間だけ寄せたい、というような直しは、MMD を動かさずに vmd を直接編集する。
`motion keys` で区間のキーを見て、`motion edit` で別名に書き出す。どちらも MMD に接続せず、中継もしない。
数値は MMD の窓に表示される値（距離は正、角度は度）で見せ、受け取る。

```
mmd motion keys camera.vmd                                      # 種類ごとの件数と、最初と最後のフレーム
mmd motion keys camera.vmd --camera --from 0 --to 300           # 区間のカメラのキー（距離・位置・角度・視野角）
mmd motion edit camera.vmd near.vmd --camera --from 0 --to 247 --distance-scale 0.6     # 距離を 0.6 倍にして near.vmd へ
mmd motion edit camera.vmd near.vmd --camera --from 0 --to 247 --distance-clamp 0 60    # または距離を 60 以下に抑える
```

```json
{"ok": true, "path": "C:\\work\\camera.vmd", "range": [0, 300], "model_name": "カメラ・照明", "kind": "camera",
 "target": {"kind": "camera"}, "count": 4,
 "keys": [{"frame": 0, "distance": 500.0, "pos": [0.0, 60.0, 0.0], "rot": [-6.0, 0.0, 0.0], "fov": 30, "perspective": true}, "..."]}
```

`motion edit` の結果には、対象ごとに触ったキーの数と、書いた OUT を読み戻した件数が入る。

```json
{"ok": true, "in": "C:\\work\\camera.vmd", "out": "C:\\work\\near.vmd", "range": [0, 247],
 "order": ["shift", "copy", "values", "interp"], "targets": [{"kind": "camera", "selected": 3, "changed": 3, "touched": 3}],
 "counts": {"bones": 0, "morphs": 0, "cameras": 260, "lights": 0, "shadows": 0, "show_ik": 0}}
```

対象は `--camera` / `--light` / `--bone 名前`（複数可）/ `--all-bones` / `--morph 名前`（複数可）/ `--all-morphs`。`motion keys` は 1 つだけ。
区間 `--from A --to B` は両端を含み、省略すると全体（片方だけはエラー）。ボーンと表情は名前の完全一致で選ぶので、
同じフレームにある別のボーンのキーには触れない。無い名前はエラーにし、近い名前を添える。

| 操作 | 対象 | 内容 |
| --- | --- | --- |
| `--shift N` | 全部 | フレームを N ずらす（負も可。0 未満になるキーがあれば何も変えずにエラー） |
| `--delete` | 全部 | 消す。他の操作とは組み合わせられない |
| `--copy-to F` | 全部 | 区間の先頭が F に来るように複製を足す |
| `--replace` | | `--shift` / `--copy-to` の行き先に既にあるキーを置き換える（付けなければエラー） |
| `--distance-scale K` / `--distance-add D` / `--distance-clamp MIN MAX` | カメラ | 距離を K 倍（K > 0）/ D 足す / MIN〜MAX に収める。表示値の意味で、ファイルが負で持つ符号はそのまま |
| `--pos-add X Y Z` | カメラ・ボーン | 位置に足す |
| `--fov-set F` / `--fov-add F` | カメラ | 視野角（度） |
| `--rot-add X Y Z` | ボーン | 表示値の度。キーの回転の後にボーン自身の軸で回す（単一軸のキーなら角度の足し算と同じ） |
| `--weight-set W` / `--weight-scale K` | 表情 | 重み |
| `--interp X1 Y1 X2 Y2` | カメラ・ボーン | 補間曲線を全チャンネル同じ値に置き換える |

1 回の呼び出しに複数の操作を書ける。適用の順番は固定で、ずらす → 複製 → 値の変更（倍率・設定 → 加算 → 上下限）→ 補間曲線。
値の変更と補間曲線は、区間のキーとその呼び出しで作った複製の両方に効く。IN は変えずに OUT に書く。OUT に既にあるファイル
（IN と同じパスを指定した場合も）は、書き終えるまで `名前.mmdcli-old` に退避する（他の書き出しと同じ規則）。キーの順番は
ファイルのまま（並べ替えない）。

補間曲線は MMD の補間パネルの 2 つの制御点 (X1, Y1)・(X2, Y2) で、各 0〜127。線形は `20 20 107 107`、`64 0 64 127` は
ゆっくり始まってゆっくり止まる S 字。`bone set --interp` と `camera set --register --interp` で登録するキーにも同じ形で指定できる
（省略すれば今までどおり線形）。カメラの登録ボタンには曲線を渡せないので、`camera set --interp` は欄の表示値から 1 キーの
カメラモーションを組んで読ませる方法で登録する。

### ダンスからカメラモーションを作る（`tools/make_camera.py`、MMD なし）

配布のカメラが会場前提で人物が小さいとき、ダンスの vmd から「人物を程よい大きさで捉え、1 ショットに 1 回だけゆっくり動く」
カメラの vmd を作る。音源は使わず、ボーンキーから出した動きの強さ（骨ごとの回転の角度差と位置の移動量を 30 フレーム窓で合計）の
山と谷でショットを切る（1 ショット 6〜16 秒。`--min-shot` / `--max-shot` はフレーム数で、後者は前者の 2 倍以上）。
ショットの型は 正面の寄り（距離 38→32）・引き（32→42）・回り込み（Y ±15 度）・上から（X +10 度、頭の高さから見下ろす。カメラは腰より下に置かない）の 4 つで、
強い区間は少し引き、静かな区間は寄りを多めにし、同じ型は続けず、直前の終点と絵がほとんど変わらない型も選ばない。注視点は
センターの位置を 3 秒の平均で追う（ショット内に 90 フレーム以下の間隔でキー）。距離と角度は 1 ショットで 1 本の S 字、先頭キーは段差の曲線。
全ショットで画面が膝下から頭上までを覆う（報告の `picture`）。視野 30。同じ入力と `--seed` なら同じ出力。

```
python tools/make_camera.py dance.vmd camera.vmd --report shots.json --analysis strength.json [--seed 0]
```

標準出力はショット数・キー数・型の内訳などの 1 行 JSON。`--report` はショットの一覧（開始・終了フレーム、型、距離・高さ・角度の
始点と終点、注視点、強さ）、`--analysis` はフレームごとの強さと閾値・山と谷の区間。出来た vmd は `motion keys --camera` で見られ、
`motion edit` で直せる。

## 出力

- 標準出力は常に ASCII。日本語などは `\uXXXX` に逃がすので、端末の文字コードが何であっても壊れない。
- 日本語をそのまま読みたいときは `--out FILE` を付ける。結果を UTF-8 でファイルに書き、標準出力にはその場所だけを出す。
- 成功は `{"ok": true, ...}`、失敗は `{"ok": false, "error": {"type": ..., "message": ...}}`。
- 終了コード: 0 成功 / 1 失敗 / 2 引数の誤り（書式だけでなく、`frame set -1` のような使えない値や壊れた入力ファイルも） /
  3 MMD がダイアログで待っている。

共通オプションはコマンド名の前に置く。

```
mmd [--pid N] [--out FILE] [--timeout 秒] [--in-place] [--in-user-session | --no-relay] コマンド ...
```

対象の MMD は、`--pid`、環境変数 `MMD_CLI_PID`、`mmd launch` が最後に起動したもの、唯一起動しているもの、の順で決まる。
`mmd ps` で起動中の一覧が出る。

## コマンド

| コマンド | 内容 |
| --- | --- |
| `ps` / `launch [--exe P] [--headless]` / `quit [--force]` | 一覧・起動（最小化、または非表示）・終了 |
| `state` / `dump [--keys]` | 状態の読み出し |
| `new` / `open F.pmm` / `save [F.pmm]` | プロジェクト |
| `model load F` / `list` / `select 名前\|番号\|camera` / `delete` / `show` / `hide` / `info [名前\|番号\|F]` | モデル（pmx / pmd）。`info` は骨（親・旗・IK・付与）と表情（区分・種類）と表示枠の一覧をモデルファイルから読む |
| `motion load F.vmd [--frame N] [--model M]` / `motion save F.vmd` | モーションの読込と書き出し（保存は選択中のモデルの全キー。カメラ編ならカメラと照明） |
| `motion keys F.vmd [対象] [--from A --to B]` / `motion edit IN.vmd OUT.vmd 対象... [--from A --to B] 操作...` | vmd の中のキーの一覧と、区間のキーのずらし・削除・複製・値の変更・補間曲線の置換（MMD 不要） |
| `pose load F.vpd [--register]` / `pose save F.vpd` | ポーズの読込と書き出し。`--register` でキーも登録する |
| `bone list` / `get 名前` / `set 名前 [--pos X Y Z] [--rot X Y Z \| --quat X Y Z W] [--frame N] [--interp X1 Y1 X2 Y2]` | ボーンのキー登録（`--interp` は補間曲線。省略は線形） |
| `morph list` / `get 名前` / `set 名前 値 [--frame N]` | 表情のキー登録 |
| `camera get` / `set [--pos] [--rot] [--distance] [--fov] [--perspective on\|off] [--register [--interp X1 Y1 X2 Y2]]` | カメラ（`--interp` は登録するキーの補間曲線） |
| `light get` / `set [--rgb R G B] [--dir X Y Z] [--register]` | 照明 |
| `accessory load F.x` / `list` / `get` / `set 名前 [--pos] [--rot] [--scale] [--alpha] [--show\|--hide]` / `delete` | アクセサリ（`set` は現在のフレームに登録する） |
| `wav load F.wav` | 音 |
| `frame get` / `set N` / `next` / `prev` / `next-key` / `prev-key` / `first` / `last` | フレーム移動 |
| `play [--from A --to B] [--wait] [--from-current] [--stay] [--repeat]` / `stop` | 再生 |
| `render image F [--size W H]` / `render avi F --from A --to B [--fps N] [--size W H] [--codec 名前]` / `render size [W H]` / `render codecs` | 書き出し（`codecs` はこの機で選べる AVI のコーデック一覧） |
| `menu list` / `menu click ID` / `menu set ID on\|off` | 任意のメニュー項目（`set` はチェック印を望む状態にそろえる。すでにその状態なら押さない） |
| `control list` / `get ID` / `set ID 値` / `click ID` | 任意のコントロール |
| `dialog list` / `click ボタン` / `close` / `show` | MMD が待っているダイアログ |
| `window status` / `minimize` / `hide` / `show` | 窓（hide は画面にもタスクバーにも出さない） |
| `file info F [--brief]` | vmd / vpd / pmm / pmx / pmd の中身（MMD 不要）。`--brief` はモデルの件数と名前だけ |
| `batch F [--keep-going]` | ファイル（`-` で標準入力）の 1 行 1 コマンドを 1 プロセスで順に実行 |

専用のコマンドが無い操作は、`menu` と `control` で届く。ID の一覧は `mmd menu list` と `mmd control list`、
窓の中の位置は下の図と `docs/controls-v932.json` にある。

## ダイアログ

MMD のプロセスに新しい窓が現れると、表示される前に透明にして画面外へ動かし、Windows が次のアクティブな窓として
選ばないようにする。そのうえで、コマンドが予期しているもの（モデル情報、ファイル名の入力、削除の確認など）は自動で応答する。

予期していないダイアログは、隠したまま開いた状態で残し、終了コード 3 で報告する。

```
$ mmd menu click 201
{"ok": false, "error": {"type": "DialogPending", "message": "MMD is waiting in a dialog: About",
 "dialogs": [{"kind": "message", "title": "About", "message": "MikuMikuDance Ver.9.32 ...", "buttons": ["OK"]}],
 "hint": "answer it with: mmd dialog click BUTTON   (or: mmd dialog close)"}}
$ mmd dialog click OK
{"ok": true, "closed": "About", "dialogs": []}
```

ダイアログが残っている間、他のコマンドは何もせずに同じエラーを返す。人が手で答えたいときは `mmd dialog show` で画面に戻せる。
`mmd state` と `mmd dialog list` は見るだけで、人が手で開いたダイアログを隠すことはない。

失敗した場合も、そこまでに自動で押したボタンは `error.answered_dialogs` に残る。ファイルダイアログが名前を受け付けない
とき（Windows で使えない文字を含む名前など。保存ダイアログはメッセージを出さずに開いたままになる）は、待たずに
ダイアログを閉じ、その理由を付けて失敗する。MMD 自身が出す通知（OK だけのメッセージ）は閉じて文言を控え、
続く失敗の文に添える。

## キーボードの焦点

`mmd` を走らせた端末が前面にあるとき、Windows はそのコマンドのプロセスに「前面を取る権利」を与えていて、
MMD へ同期メッセージを送るとその権利が MMD にも渡る。放っておくと、MMD が開いたダイアログが活性化して、
端末からキーボードの焦点を奪う（quit まで戻らない）。

mmd-cli は各コマンドの実行中、前面を固定する（`LockSetForegroundWindow`）。利用者が ALT を押すか別の窓を
クリックすれば Windows が固定を解くので、利用者の操作は妨げない。固定をすり抜けて MMD の窓が前面になった
場合は、見張りのスレッドが即座に元の窓へ戻し、結果の JSON に `foreground_restored` として残す。
通し確認では、奪われる条件（端末が前面）で 24 コマンド・68 秒の間、前面の窓は一度も変わらなかった。

## プロジェクトファイルの扱い

`mmd dump` は pmm への保存を伴う。利用者のファイルを黙って書き換えないために、MMD が開くのは常に作業用の写しにしてある。

- `mmd open X.pmm`: X を `%LOCALAPPDATA%/mmd-cli/sessions` へ写して、その写しを開く。
- `mmd dump`、`mmd bone set` など: 写しに上書き保存する。X は変わらない。
- `mmd save [X.pmm]`: 写しを保存して X へ写す。X を省くと、開いた元の場所へ書く。
- mmd-cli を通さずに（人が手で）開かれたプロジェクトでは、保存を伴うコマンド（`dump` など）は拒否する。`--in-place` を
  付けるとそのファイルへ保存する。`mmd save 別名.pmm` は MMD の「名前を付けて保存」で、開いていたファイルは書かない。
  パスを省いた `mmd save` だけが、開いているファイルへの上書きになる。
- 書き出し先（pmm / vmd / vpd / 画像 / AVI）に既にあるファイルは、MMD が新しいものを書き終えるまで `名前.mmdcli-old` の
  名前で脇に退避し、失敗したときは元に戻す。失敗までに MMD が書いたものは消さず `名前.mmdcli-failed` として残し、
  エラーの `kept_output` にその場所を入れる。途中で止められた実行が残した `名前.mmdcli-old` は元のファイルなので
  消さない（次の実行の退避は `名前.mmdcli-old.1` になる）。書き出し先がフォルダのときは何も動かさずにエラーにする。

置き場所は環境変数 `MMD_CLI_HOME` で変えられる。

## 窓のどこを操作しているか

実際の MMD の窓に、実測したコントロールの位置と、対応するコマンドを重ねた図。

![カメラ・照明・アクセサリを選んでいるとき](docs/img/mmd-window-annotated.png)

![モデルを選んでいるとき](docs/img/mmd-window-model-annotated.png)

## 制約

- 利用者がログオンしているデスクトップセッションが要る（SSH などからはそのセッションへ中継する。「ヘッドレスで使う」を参照）。
  誰もログオンしていないマシンでは MMD が起動を終えないので動かない。
- 日本語表示の MMD が前提（ダイアログを題名で見分けている）。English Mode では動かない。
- ファイルのパスは、システムのコードページ（日本語 Windows では cp932）で表せること。MMD 自体が開けないため。
- ボーンと表情のキーは vmd を作って読ませる方式で登録する。vmd の制約で、名前が cp932 で 15 バイトを超えるものは指定できない。
- カメラと照明の値は、キーとして登録しない限り、モデルを選択した時点で MMD が捨てる。
  モデルの選択中に登録なしで変更しようとすると、コマンドはエラーにする。
- `render image` と `render avi` は場面のカメラを通して書き出す（モデル編集中の視点ではない）。
- `--size` は MMD の「出力画面サイズ」の設定を変える（AVI 出力設定ダイアログの幅・高さの欄は表示だけで効かない）。
  設定は MMD 側に残るので、次に起動した MMD も同じ大きさで書き出す。`render avi` は書き出した AVI のヘッダで
  大きさ・枚数・fps を確かめ、頼んだものと違えばエラーにする。
- 作業フォルダ（`MMD_CLI_HOME`、既定は `%LOCALAPPDATA%/mmd-cli`）のパスも、システムのコードページで表せること。
- 再生中は `stop` と `state` 以外のコマンドを受け付けない。
- 1 つの MMD に対して、同時に 2 つのコマンドを走らせない。
- `mmd open` は、MMD の仕様どおり確認なしで現在のプロジェクトを破棄する。
- AVI の書き出しは時間がかかる。既定の待ち時間は 1 フレームあたり 2 秒を上乗せしている。足りなければ `--timeout`。
- MME（MikuMikuEffect）を入れた MMD では確かめていない。
- MMD 自身が画面中央に出す確認ダイアログ（モデル情報など）は、生成と同時に可視になるため、隠すまでの最大 1 フレーム
  （約 16 ms）だけ画面に出ることがある（実機試験の見張りで 10 ms 間隔の 1 標本だけ記録される）。ファイルダイアログは
  表示前に隠せる。主窓が画面に出ることは無い。

## 試験

MMD なしで走る単体試験:

```
python -m unittest discover -s tests -t .
```

実機の MMD に対する試験（専用の MMD を非表示で起動し、同梱のモデル・アクセサリ・ポーズだけを使い、終わったら閉じる。
約 4 分。その間、タスクバーに現れる別の MikuMikuDance を触らないこと）:

```
set MMD_CLI_LIVE=1
set MMD_EXE=C:/tools/MikuMikuDance_v932x64/MikuMikuDance.exe
python -m unittest tests.live.test_live
```

実機試験は、試験の間に MMD の窓が一度も前面の窓にならなかったこと、主窓が一度も画面に現れなかったことも検査する。

SSH で入ったマシン（セッション 0）では試験自身が MMD を動かせないので、`mmd` の中継と同じ仕組みで、ログオン中の
利用者のデスクトップセッションの中で試験一式を走らせて判定だけを受け取る道具を使う:

```
python tools/run_live_tests_in_session.py --exe C:/tools/MikuMikuDance_v932x64/MikuMikuDance.exe
```

## 資料

- `docs/design-20261004-mmd-cli.md`: 設計書
- `docs/spike-result-20261004.md`: MMD を実測して分かった事実（どの操作が裏から効くか、ダイアログの挙動、pmm の構造）
- `docs/controls-v932.json`: 全コントロールとメニューの ID・位置
- `tools/make_figures.py` / `tools/dump_controls.py`: この README の図と上の JSON を作り直す道具
