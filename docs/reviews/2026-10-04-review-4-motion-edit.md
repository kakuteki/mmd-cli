# mmd-cli コードレビュー 4: batch C（`motion keys` / `motion edit`、`bone set` / `camera set --interp`）(2026-10-04)

対象: ブランチ `worktree-agent-aaa6ff549d2593c39` の 4 コミット（起点 main の f6b69a5、先頭 43d2179）。
1b76366（vmd の補間の組み立て補助・`quat_multiply`）→ 00691aa（`motion keys` / `motion edit`、motion_edit.py）→ 7129ce8（`bone set` / `camera set --interp`）→ 43d2179（README・記録）。
差分は `git diff main worktree-agent-aaa6ff549d2593c39`（11 ファイル、+1673 / -23。うち HANDOVER.md の差はブランチが触ったのではなく main 側が 4062977 で進んだぶん）を通読した。
worktree `.claude/worktrees/agent-aaa6ff549d2593c39` はブランチ先頭と一致（`git status` は空）。読み取りのみ。コードは変更していない。
main は査読中 4062977（f6b69a5 から 1 コミット進んでいる。HANDOVER.md だけ。取り込みの試算は 11 節）。

読んだ版の指紋（blob の先頭 8 桁、`git ls-tree`）:

| ファイル | blob |
| --- | --- |
| mmd_cli/motion_edit.py（新規） | 0b7dfc48 |
| mmd_cli/formats/vmd.py | 847519c3 |
| mmd_cli/mathutil.py | e6beb6ae |
| mmd_cli/app.py | e5e1901c |
| mmd_cli/cli.py | 902a372f |
| tests/test_motion_edit.py（新規） | 61b2a8f6 |
| tests/test_vmd.py | f8e2fdd3 |
| tests/test_cli.py | a024bd94 |
| README.md | 646fc9be |
| docs/reviews/2026-10-04-batch-c-motion-edit.md | 3f2b8933 |

方法: 差分を通読し、確かめられる点は MMD を起動しない小さなスクリプトで実測した。**MMD は起動していない。schtasks は実行していない。**
探査スクリプトは scratchpad（`measure_interp.py` `probe_behaviour.py` `probe_real_files.py` `probe_roundtrip2.py` `check_syntax_idents.py`）に置き、リポジトリには入れていない。

- 実物の vmd: `_spike/out/hibikase/enuta/MMD_モーションデータ_ヒビカセ_0_992/` の 3 本（カメラ 260 キー、ダンス 袖の値あり / なし 各 39,660 キー・表情 54・表示IK 1）と、
  MMD v9.32 が書いた `_spike/out/t1.vmd`（4 キー）・`fx.vmd`（3 キー）。記録にある KAZUSA 版（52,030 キー）は手元に無く、その分の主張は確かめていない。
- 固定資料 `tests/fixtures/scene_v932.pmm`（pmm 側の補間 16 / 24 バイトの並び）。
- 単体試験: worktree で `python -m unittest discover -s tests -t .` → **363 本 OK、skip 1**（tests/live）。記録の主張と一致。
  内訳 test_motion_edit 60・test_vmd 25（main 17 → +8）・test_cli 50（main 33 → +17）も記録どおり。
  main 4062977 との `git merge-tree --write-tree`（衝突なし、tree e31c6b19）を scratchpad に展開して同じ試験 → 363 本 OK、skip 1。
- Python 3.9: 触った 8 ファイルを `ast.parse(feature_version=(3, 9))` で通し、識別子（関数・クラス・変数・引数・属性・import）に非 ASCII が無いことを AST で確認した。match 文・PEP 604 の `X | Y` は無い。
- 補間の配置: 本体の `bone_curves` / `camera_curves` を使わず、自前で「1 行目の 2・3 バイト目を 2 行目から補った 16 バイト」を作り、
  2 つの読み方（群 = x1,y1,x2,y2 と 群 = x1,x2,y1,y2）で x1 > x2 になる曲線の数を数えた（下の 1 節）。

書式: 各指摘は「場所／何が起きるか／根拠／直し方／重要度（高・中・低）」。推測は推測と書く。行番号はブランチ先頭 43d2179 のもの。

## 0. 要約

- 高: なし。
- 中 4 件: 2.1 同じ対象を二重に指定すると操作が二重に効く（`--bone X --all-bones --shift 10` で X は 20 ずれる）／2.2 骨名が 15 バイトで 2 バイト文字の途中で切れている vmd（MMD が長い名前を切って書いたもの）は `motion edit` がファイル全体を拒む／3.1 `camera set --register --interp` の「登録できたか」の検査がフレーム 0 では常に通り、カメラにはボーンのような `interp_in_project` も無いので、新しい経路の唯一の証拠が無い／3.2 その経路（カメラ vmd を落として現在のフレームに置く・既存キーを上書きする）は実機で未検証（記録も認めている）。
- 低 13 件（1.1、2.3〜2.9、3.3・3.4、4.1、6.1、8.1）。
- 補間データの配置（1 節）は実物で裏が取れた。`motion edit` の中核（区間・ずらし・複製・値・順序・書き順・退避）は問題なし。
- 判断は 11 節: **取り込んでよい（条件つき）**。

## 1. 補間データの配置（`formats/vmd.py` 23〜76 行）

### 1.0 実測（見たが問題なし）

ボーンの 64 バイト（えぬた ダンス 2 本、各 39,660 キー。2 本は同じモデル `DIVA風ミク_105改` で、曲線の分布も同じ）:

| 項目 | 袖の値あり | 袖の値なし | MMD v9.32 が書いた t1 / fx |
| --- | --- | --- | --- |
| 2〜4 行目が 1 行目を 1 バイトずつ左にずらした写し（1 行目の 2・3 バイト目と行末の詰め物は除く） | 39,660 / 39,660 | 39,660 / 39,660 | 4 / 4、3 / 3 |
| 1 行目の 2・3 バイト目が 0 0 | 39,660 / 39,660 | 39,660 / 39,660 | 4 / 4、3 / 3 |
| `DEFAULT_BONE_INTERPOLATION` と 64 バイト一致 | 36,616 | 36,618 | 全部 |
| 行末の詰め物（31、46・47、61〜63 バイト目）が 0 | 36,644 | 36,646 | 全部 |
| 曲線つき（既定と違う 16 バイト）のキー | 339 | 339 | 0 |
| 異なる 16 バイトの種類 | 185 | 185 | 1 |

曲線つきのキーの 16 バイト（2・3 バイト目は 2 行目から補ったもの）を 2 通りに読んで、制御点が x1 > x2 になる（2 つの制御点が左右に入れ替わる。通常の緩急では使わない形）チャンネルの数:
群 = x1, y1, x2, y2（本体の読み）では **0**、群 = x1, x2, y1, y2 では 273（曲線つき 339 キー × 4 = 1,356 チャンネルのうち。既定のキーはどちらの読みでも 0）。例: `64 64 64 20 | 0 0 0 20 | 64 64 64 107 | 127 127 127 107`（11 キー）は前者で X Y Z = (64,0)-(64,127)・回転 = 線形、後者では (64,64)-(0,127) になる。
`20 20 20 0 | 20 20 20 0 | 107 107 107 127 | 107 107 107 65`（6 キー）は前者で回転 = (0,0)-(127,65)、後者で (0,127)-(0,65)。本体の読み方では全キーが見慣れた緩急（ease in / out / in-out、線形からの片寄せ）になり、もう一方では 273 チャンネルが左右の入れ替わった形になる。

カメラの 24 バイト（えぬた カメラ 260 キー）: 5 種類。`20 107 20 107`×6 が 250、`64 64 0 127`×6 が 4、`64 127 0 127`×6 が 4、`0 64 0 127`×6 が 1、
回転だけ `20 107 20 107` で他 5 チャンネルが `64 127 0 127` のものが 1。1 チャンネル 4 バイトを x1, x2, y1, y2 と読むと x1 > x2 は **0 / 60**、x1, y1, x2, y2 と読むと 53 / 60（曲線つき 10 キー × 6 チャンネル。残る 7 は混在キーの線形な回転 1 と `0 64 0 127` の 6）。
本体の `camera_curves` / `camera_interpolation` の並びと一致する。既定 `20 107 20 107` が (20,20)-(107,107) になることとも整合する。

公開されている vmd の資料（針金P の VMD メモ系、mmd_tools の読み書き）が示す配置も「1 行目 = X Y Z 回転 の x1、同 y1、同 x2、同 y2 の 4 群、2〜4 行目は 1 バイトずつずれた写し、行末は 01 / 00 の詰め物」「カメラは 1 チャンネル 4 バイトで x1 x2 y1 y2」で、本体の実装と同じ（**記憶による照合**。資料そのものは今回開いていない）。
古い MMD は詰め物に 01 を書いたとされるが、v9.32 が書いた t1 / fx は 0、配布物には 102 102 230 のようなごみが残っている（本体は新規・置換とも 0 を書く。MMD と同じ）。

`bone_interpolation(LINEAR_CURVE) == DEFAULT_BONE_INTERPOLATION`、`camera_interpolation(LINEAR_CURVE) == DEFAULT_CAMERA_INTERPOLATION` を本体の外から確認した（True）。
`bone_curves` が 2・3 バイト目を 2 行目（17・18 バイト目）から読む根拠（2 行目 = 1 行目の左 1 バイトずらし）は、上の表の 1 行目で全キーについて成り立つ。

pmm 側（`tests/fixtures/scene_v932.pmm`）: ボーンキー 125 件（init 122 + 3）の 16 バイトは全部 `20 20 107 107`×4、カメラ init の 24 バイトは `20 20 107 107`×6。
pmm は 1 チャンネル `x1 y1 x2 y2` で、vmd のカメラ（`x1 x2 y1 y2`）とも vmd のボーン（4 群）とも違う。記録 0 節の主張と一致（4.1 で使う）。

推測のまま残るもの（記録も推測と書いている。結果には影響しない）:
- 群の中のチャンネルの並び（X Y Z 回転 / X Y Z 回転 距離 視野角）は実物から区別できない。全チャンネルに同じ値を書く機能なので影響は読み戻しの名前づけだけ。
- 1 行目の 2・3 バイト目の意味（物理 ON/OFF の旗と言われる）。物理 OFF のキーを含む実例は手元に無い。固定資料の pmm も `physics_disabled` のキーは 0 件。本体は既存キーでは保ち、新規キーは MMD と同じ 0 を書くので、どちらにしても安全側。

### 1.1 `keep` は 2・3 バイト目だけ保ち、詰め物のごみは 0 に正規化する（低・問題なしの確認）

場所: vmd.py:42-56 `bone_interpolation(curve, keep)`。

実測: えぬた ダンスの センター 1207 / 1209 / 1211 に `--interp 64 0 64 127` を当てると、2・3 バイト目は 0 0 のまま、行末の `102 102 230` は `0 0 0` になった（5 節の実測 d）。MMD 自身が 0 を書くので問題ない。記録に「詰め物は 0 にする」と一言あると親切。

## 2. `motion_edit` の意味（`mmd_cli/motion_edit.py`）

### 2.0 見たが問題なし

- 区間は両端を含む（`_inside` 140-141、`<=` 両側）。`--from 7 --to 7` は 1 フレーム。
- `--shift` の負: 0 未満になるキーがあれば `_apply_one` 336-339 で何も変える前に `ValueError`（実測: メモリ上のキーも動かず、ファイルも書かれない）。複数対象で 2 つ目以降が失敗すると先の対象はメモリ上では変わっているが、`edit_file` は `apply` が返った後にだけ書くのでファイルは変わらない（docstring にも明記）。
- 行き先の衝突: `_make_room` 271-282 は同じ対象（同じ骨名・表情名・カメラ・照明）の区間外キーだけを衝突とし、区間内のキー同士の入れ替わりは衝突にしない。`--replace` 無しはフレーム一覧つきのエラー、有りは消して `replaced` に数える。別の骨の同じフレームには触れない（試験 `test_same_frames_of_another_bone_are_not_in_the_way`、実測でも確認）。
- `--copy-to F`: 複製は `dataclasses.replace` で別オブジェクト（試験あり）。`offset = F - min(選んだキーのフレーム)`。複製の行き先が元のキー（区間内を含む）に重なればエラー、`--replace` で置換し、消えた元キーは `touched` から外す。順序 shift → copy なので、複製は「ずらした後のキー」の複製。README の文と一致。
- 値の順序: scale / set → add → clamp（`_change_values` 292-322）。距離はファイルの負の値に対して `*K`（符号保持）、`- D`（表示値に D 足す）、`_clamped_distance`（|距離| を [MIN, MAX] に、符号は保つ、0 は負扱い）。実測: -45/-60/-30 → clamp(35,50) → -45/-50/-35。
- `--rot-add`: `q_new = quat_multiply(q_key, q_add)`（ハミルトン積、式は正しい。a*b の 4 成分を手で検算）。v → q_key (q_add v) なので、キーの回転の後に「ボーン自身の軸」で回す内在回転（右から掛ける）に相当し、README の文と合う。試験は独立に書いた `rotate`（tests/test_mathutil.py）で順序を固定している。符号の約束は `ui_to_quat` を両方に使うので整合する。同じ軸なら表示値の足し算になる（実測: Z30 + Z10 → (0,0,40)）。ただし 2.5。
- カメラの表示値: 距離は `-distance`、X の角度は符号反転（`camera_to_ui` 193-198）。scene.py の `_camera_key` と同じ約束。`camera_key_from_ui` はその逆で、往復の試験あり。
- 適用順と「複製にも効く」: `touched` = 選んだキー（置換で消えたものを除く）+ 複製。値と `--interp` はこの `touched` に効く。試験 `OrderTest` と README が一致。
- IN と OUT が同じパス: `edit_file` 395-409 は IN を全部読んでから `_write` で `keeping_the_old_file(dst)`（既存を `.mmdcli-old` に退避、`.part` に書いて `os.replace`、成功で退避を消す）。実測: えぬたカメラの写しを IN = OUT で clamp → フォルダに `.mmdcli-old` も `.part` も残らない。失敗したときの戻しは app.py の既存の経路。
- 書き順: `section.extend(copies)` と in-place の変更だけで並べ替えない。実測: えぬたカメラ（ファイル順はフレーム順でない）の 0〜247 を 0.6 倍 → 260 キーの順序は同一、区間外の 257 キーはフィールドまで同一。ダンスの センター 3 キーの `--interp` でも 39,660 キーの (名前, フレーム) の並びが同一、表情 54・表示IK 1 も保たれた。
- 検査の順番: `check_range` → `check_operations`（対象の種類と操作の相性もここ）→ `vmd.load` → `resolve_targets`（無い名前は difflib の候補 5 件、無ければ先頭 10 件）→ `apply` → `dumps` → 書く。ファイルを読む前に落ちる検査は実測どおり（`--from` だけ・`--to < --from`・`--replace` 単独・`--delete` との併用・種類違い）。
- 終了コード: `ValueError` は 2（`cli.failure`）。`motion keys` に vmd でないファイルを渡すと "not a VMD file (bad magic)" の 2。IN が無いと `FileNotFoundError` の 1。
- 同名ボーンのキーが混ざる vmd: 名前の完全一致で選ぶので、同じフレームにある別名のキーには触れない。配布物に実在する「同じ骨・同じフレームの重複キー」（えぬた ダンスに 2 組）は両方選ばれ、両方動く（衝突の除外に入る）。入力を保つという意味で妥当。

### 2.1 同じ対象を二重に指定すると操作が二重に効く（中）

場所: motion_edit.py:171-188 `resolve_targets`、cli.py:359-372 `_motion_targets`、apply 372-378。

何が起きるか: `--bone X --bone X`、または `--bone X --all-bones`（`--morph X --all-morphs` も同じ）で X の `Target` が 2 つできる。`resolve_targets` は重複を落とさず、`apply` は対象ごとに `_apply_one` を呼ぶので、X のキーは shift が 2 回、`--pos-add` / `--rot-add` / `--distance-*` / `--weight-scale` も 2 回効く。

根拠（実測、tests の `model_motion()` を書き出したファイル）:
- `motion edit in out --bone センター --all-bones --shift 10` → センター の フレーム 0/10/20/30 が **20/30/40/50**（右腕は +10）。結果 JSON の `targets` は `センター` の報告が 2 つ並ぶ。
- `--bone センター --bone センター --pos-add 0 1 0` → センター@0 の位置が (0, 2, 0)。
- tests/test_cli.py の `test_motion_edit_combines_targets_range_and_operations` 自身が `--bone a --bone b --all-bones` を正しい引数として解析しており、組み合わせは想定内。

直し方: `resolve_targets` の末尾で `(kind, name)` で重複を落とす（順序は保つ: `list(dict.fromkeys(out))`。`Target` は frozen dataclass なので hash できる）。または `_motion_targets` で `--all-bones` があれば個別の `--bone` を捨てる。試験: `--bone X --all-bones --shift N` で X が N だけ動くこと、報告が 1 つになること。

### 2.2 骨名が 15 バイトで 2 バイト文字の途中で切れている vmd は `motion edit` がファイル全体を拒む（中）

場所: vmd.py:161-165 `_fixed` → 154-158 `_encode`、186-187 `_text`。motion_edit.py:405 `vmd.dumps(motion)`。

何が起きるか: vmd の骨名欄は 15 バイトで、MMD はそれより長い名前を 15 バイトで切って書く（既知の性質。今回は測っていない。cp932 の 2 バイト文字の途中で切れることがある。例: `右手首キャンセル` は 16 バイト）。読み込み `_text` は `decode("cp932", "replace")` で末尾を U+FFFD にし、書き出し `_fixed` は U+FFFD を cp932 に戻せず `ValueError("bone name '右手首キャンセ�' has characters outside cp932")` を投げる。`motion edit` は編集対象でないキーも含めて全部を書き直すので、**カメラや表情だけを編集する呼び出しでも**その骨が 1 つあればファイル全体が失敗する。`motion keys` は読むだけなので通る。

根拠（実測、合成）: 骨名欄に `右手首キャンセル` の先頭 15 バイトを置いた vmd → `motion keys` は通る、`motion edit --all-bones --shift 1` も `--all-morphs --shift 1` も上のメッセージで失敗。えぬた ダンス 2 本と t1 / fx にはこの形の名前が無く、219 件の骨・表情名は全部通った（`--all-bones --all-morphs --shift 100` が成功）。

これは vmd.py の既存の性質（`dumps` は今まで本体が組み立てたモーションだけを書いていた）で、配布ファイルを丸ごと書き戻す `motion edit` が初めて踏む。
利用者から見るとファイル名も骨も自分で触っていないのに「cp932 の外」と言われるので、原因にたどり着きにくい。

直し方（どれか）:
1. 読み込み時に名前欄の生バイトを `BoneKey` / `MorphKey` に持ち（例: `raw_name`）、名前が変わっていなければ `dumps` がそのバイトを書き戻す（MMD が書いたままを保つ。最も忠実）。
2. 最低限: `dumps` のメッセージを「骨名 '…' は 15 バイトで切れている（MMD が長い名前を切ったもの）。このファイルは motion edit で書き直せない」と原因が分かる文にし、README の「モーションファイルの編集」節に制限として書く。
試験: 上の合成ファイルで `motion edit --camera` 相当（骨を触らない編集）が通ること（1 を採る場合）、または原因が分かるメッセージになること（2 の場合）。

### 2.3 `--distance-clamp` は |距離| を収める。表示値が負（カメラが反対側）なら README の「MIN〜MAX に収める」と違う結果になる（低）

場所: motion_edit.py:285-289 `_clamped_distance`、README 84 行。

実測: ファイル +80（表示 -80）に clamp(10, 60) → ファイル 60（表示 -60）。記録は「|距離| を [MIN, MAX] に。符号は保つ」と正しく書いているが README は「距離を MIN〜MAX に収める」。表示値が負のカメラキーは稀（えぬたの 260 キーには無い）なので実害は小さい。
直し方: README を「距離の大きさを MIN〜MAX に収める（符号はそのまま）」に。

### 2.4 視野角の上限と表情の重みの範囲を検査しない（低）

場所: motion_edit.py:118-119（`fov_set` は 1 以上のみ）、296-300（`fov_add` は結果 1 未満だけ拒む）、318-321（重み）。

実測: `--fov-add 500` → fov 530 / 540 のキーが書ける。`--weight-set 5` → 5.0、`--weight-scale -1` → -0.5。MMD の視野角欄は 1〜125 と**記憶している**（記録は「測っていないので下限だけ」とし、推測を避けた判断は妥当）。重みは MMD の表情スライダーが 0〜1。
直し方: 実機で視野角欄の上限を 1 回測り（`camera set --fov 126` の読み戻しで足りる）、`fov_set` / `fov_add` の結果にその上限を足す。重みは 0〜1 の外を拒むか、少なくとも README の表に「MMD の表示は 0〜1」と書く。

### 2.5 README「単一軸のキーなら角度の足し算と同じ」は、足す軸がキーと同じ軸のときだけ（低）

場所: README 87 行、cli.py の `--rot-add` の help。

実測: キー Z30 + 加算 Z10 → (0, 0, 40)。キー X30 + Z10 → (30, 0, 10)。しかしキー Z30 + X10 → **(8.65, 5.04, 30.38)**、キー X30 + Y10 → (29.50, 11.51, 5.73)。MMD の分解順（Y・X・Z、Z が先）に沿う組み合わせだけが足し算に見える。
直し方: 「同じ軸どうしなら足し算と同じ」に直す。

### 2.6 空の区間は 0 件で成功する（低・設計の確認）

実測: `--from 1 --to 2 --shift 1`（キー無し）→ `selected 0, shifted 0, touched 0`、終了 0。結果に件数が出るので黙ってはいないが、区間の打ち間違いを気づきにくい。現状のままでよいが、README に「区間にキーが無くても成功（`selected 0`）」と一言。

### 2.7 `--copy-to F` の「区間の先頭」は `--from` ではなく区間内の最初のキー（低）

場所: motion_edit.py:347、README 82 行。

`--from 0 --to 247` で最初のキーが 5 にあれば、複製は F から始まる（F+5 ではない）。CLI の help（"the first one at frame F"）は正確。README の「区間の先頭が F に来るように」は `--from` と読める。直し方: 「区間内の最初のキーが F に来るように」。

### 2.8 セルフ影・表示IK のキーは対象にできない（低）

実測: えぬた ダンスに `--all-bones --all-morphs --shift 100` → 骨と表情は 100 から始まるが、表示IK のキーはフレーム 0 のまま。カメラ編の shadows も同じ。「全部ずらす」用途では置き去りになる。README の対象一覧は正確なので誤りではない。直し方: 必要になったら `--all` か `--shadow` / `--show-ik` を足す。HANDOVER に残すだけでよい。

### 2.9 出力は名前欄の NUL の後ろを 0 に正規化する（低・問題なしの確認）

実測: `vmd.dumps(vmd.loads(raw))` と元を比べると、えぬた カメラは 9 バイト（ヘッダ 30 バイトの詰め物 `@\xdc` とモデル名欄の後ろ）、ダンスは 300,274 バイトが違い、
その全部が名前欄（モデル名・骨名 39,652 / 39,660 件・表情名・表示IK 名）の NUL の後ろの `0xFD` の詰め物。キーの値・順序・補間バイトの差は 0。
MMD は NUL までしか読まないので無害だが、`fc` で比べると大量に違って見える。記録か README に一言。

## 3. `camera set --register --interp`（app.py:799-841）

### 3.0 経路の読み（見たが問題なし）

- `require_ready()` → `--interp` には `--register` が要る（`ValueError`、終了 2）→ `check_curve` → `_require_register_or_camera_mode`（register なので通る）→ `_camera_mode()`（モデル選択中なら一時的にカメラへ、終わりに戻す）→ 欄に値 → `_register_camera_through_motion(curve)` → `_read_camera()` を結果に、`interp` を添える。
- `_register_camera_through_motion`: `_read_camera()`（欄の表示値）→ `camera_key_from_ui`（距離は負、X は符号反転、ラジアン、fov は int、perspective は bool）→ `Motion.for_camera` の 1 キー（フレーム 0、照明・影のキー無し）を `%pid%-camera.vmd` に書く → `_drop_motion`（「モーションデータ読込」の確認が出れば押す）→ `frame()` → `_project()` のカメラキーに現在のフレームがあるか。
- 試験 `SetCameraInterpTest` は `_camera_mode` / `enter` / `click` / `_read_camera` / `_drop_motion` / `_project` を全部差し替えた窓なしの Mmd で、落とす vmd の中身（距離 -30、位置、角度の符号と単位、fov、perspective、24 バイト）と、`--interp` なしでは登録ボタン・落とさないことを見ている。経路の形としては矛盾がない。
- 失敗の文言: "--interp needs --register (the curve belongs to the registered key)"、"MMD did not register a camera key at frame N"。利用者に分かる。

### 3.1 登録できたかの検査がフレーム 0 では常に通り、カメラには曲線の証拠が返らない（中）

場所: app.py:838-841。

何が起きるか: pmm のカメラには常にフレーム 0 の `init` があり、検査は `[camera["init"]] + camera["keys"]` に現在のフレームがあるかだけを見る。現在のフレームが 0（起動直後の既定）なら、MMD が何も登録しなくても通る。他のフレームでも、既にキーがあるフレームへの登録（値の変更）は MMD が上書きしなくても通る。`set_bone` の同種の検査（`bone_init` にも全骨のフレーム 0 がある）は以前からの弱さだが、ボーンは `interp_in_project`（pmm のそのキーの 16 バイト）を返すので実機試験で曲線が入ったことを見られる。カメラの結果は入力の `interp` をそのまま写すだけで、pmm から読んだ値が無い。
つまり**新しい経路（vmd を落としてカメラを登録する）の成否を示す証拠が、結果にも検査にも無い**。

根拠: `_project()["camera"]["keys"]` の各要素は pmm.py:99-109 のとおり `distance` `position` `rotation` `interpolation`（24 バイト）`fov` `orthographic` を持っているので、取れる材料はある。

直し方: 現在のフレームのキーを取り出し、(a) `interp_in_project` に 24 バイトをそのまま返す（ボーンと揃える）、(b) 距離・fov が欄の値と一致することを確かめて、違えば `MmdError("MMD placed a key at frame N but its values are ...")`。実機試験は `interp_in_project == list(curve) * 6`（pmm は 1 チャンネル x1 y1 x2 y2、1.0 節）を期待値にする。
試験（窓なし）: `_project` が返すキーの距離が欄と違うとき `MmdError` になること、結果に `interp_in_project` が入ること。

### 3.2 カメラ vmd を落として登録する経路は実機で未検証（中・推測を含む）

記録は「カメラモードでの vmd 読込に確認ダイアログが出るか、現在のフレームに置かれるか、`_project()` のキーに現れるか」を未検証と明記している。査読で加えておく点:

- 「キーは現在のフレームを起点に取り込まれる」の実測（docs/spike-result-20261004.md 36 行）はモデルのモーションでのもの。カメラモーションでも同じと**推測**しているが、確かめていない。違えばキーはフレーム 0 に入り、3.1 の検査はフレーム 0 では通ってしまう。
- 既にキーがあるフレームへ落としたとき、MMD が上書きするか（値と曲線の両方）。`camera set --register` を同じフレームで繰り返す使い方では必須。
- 照明・影のキーを持たないカメラ vmd を落として、既存の照明キーが消えないこと（**推測**: 足すだけ）。
- モデル選択中（`_camera_mode` で一時的にカメラへ切り替えた状態）でも同じに動くこと。

実機試験（hinata、既存の `tools/run_live_tests_in_session.py` の枠）に次を足してから使う:
`test_camera_set_with_interp_keys_the_current_frame`: フレーム 30 で `set_camera(distance=20, register=True, interp=(64,0,64,127))` → `dump()["camera"]["keys"]` に (30, 20.0) があり、`interp_in_project`（3.1 を直した後）が `[64,0,64,127]*6`、フレーム 0 の init の距離は 45 のまま、照明キーの数が変わらない。
`test_camera_set_with_interp_overwrites_the_key_at_the_same_frame`: フレーム 0 で距離 30 + 曲線 → init の距離が 30、曲線が入る。
`test_camera_set_with_interp_while_a_model_is_selected`: モデルを読み込んだまま同じこと、終わりに選択がモデルに戻る。

補足: main の作業木には未コミットの `tests/live/test_live.py` の追加（`InterpTest` 2 本、+24 行、2026-10-04 18:52。査読で書いたものではない）があり、
ボーンは `interp_in_project` の 16 バイトの集合が {10, 20, 100, 110} になること、カメラはフレーム 15 に距離 30 のキーが 1 つ入ることを見る（フレーム 0 の罠は避けている）。
カメラの曲線のバイト（3.1 を直すまで取れない）、同じフレームへの上書き、照明キーの保持はまだ無い。

### 3.3 `--interp` に `--register` が無いエラーは MMD に接続した後に出る（低）

場所: app.py:805-807。cli.py で `camera set` を解析した段階で分かる組み合わせなので、attach や中継の前に `ValueError` にできる（`_dispatch` 583 行の手前）。実害は待ち時間だけ。

### 3.4 登録の後の `_project()` が失敗すると、登録できているのに失敗と報告する（低・既存の性質）

場所: app.py:838-840（`set_bone` 1065-1066 も同じ）。

手で開いたプロジェクト（mmd-cli 経由でない）で `--in-place` が無いとき、`_save_project` は "this project (...) was not opened through mmd-cli; reading it needs a save ..." を投げる。これはキーを登録した後なので、コマンドは失敗を返すが MMD の中には登録されている。`set_bone` も同じ順序で以前からこうなっている。直し方: メッセージに「キーは登録済みのはずで、確認だけができなかった」を足すか、`_project()` の可否（record の有無と in_place）を登録の前に確かめる。

## 4. `bone set --interp`（app.py:1042-1079）

### 4.0 見たが問題なし

- `check_curve` を `select_model` / `set_frame` より前に通す（不正なら何も変えない。試験 `test_a_bad_curve_is_refused_before_anything_is_dropped`）。
- 64 バイトは `bone_interpolation(curve)`（4 チャンネル同じ曲線、2・3 バイト目 0、詰め物 0）。MMD が書く形と同じ配置なので、MMD がどの行を読んでいても同じ曲線になる（1.0 節: 全行が同じ写しであることが実物で成り立っている）。
- `--interp` 無しは `DEFAULT_BONE_INTERPOLATION` のまま（挙動不変。試験あり）。
- 結果の `interp_in_project` は pmm のそのキーの 16 バイトを生で返す（pmm.py:75、`list(r.take(16))`）。

### 4.1 `dump` からは補間が見えない。実機試験の期待値と見せ方を決めておく（低）

場所: scene.py:31-36 `_bone_key`（`interpolation` を出さない）、app.py:1078。

`interp_in_project` の 16 バイトは pmm の並び（1 チャンネル x1 y1 x2 y2。固定資料で `20 20 107 107`×4）なので、曲線 (64,0,64,127) を登録した実機試験の期待値は `[64, 0, 64, 127] * 4`（MMD が vmd の 4 群から pmm の 4 チャンネルへ写すときの並びは推測。実機の値で確定させる）。
`dump` / `file info F.pmm` には補間が出ないので、利用者が「曲線が入ったか」を見る手段は `set_bone` の戻り値だけ。`_bone_key` と `_camera_key` に線形でないときだけ `interp`（チャンネル → x1 y1 x2 y2）を足すと、`motion keys` との照合もできる。今回の範囲外でよい。

## 5. 入力の検査

見たが問題なし（実測は `probe_behaviour.py`）:

- `--interp` の 0〜127: 解析段階は `curve_value`（整数でない・範囲外は終了 2。試験 `test_interp_values_outside_0_127_are_usage_errors`）、API 段階は `check_curve`（bool・小数・文字列・個数違いを拒む。試験あり）。
- `--from` だけ・`--to` だけ・負・`--to < --from`: `check_range` が `ValueError`、ファイルを読む前（`_motion_file_command` の先頭）。
- 存在しない骨名: 近い名前を 5 件まで（`difflib`、cutoff 0.5）、無ければ先頭 10 件 + 件数。カメラ vmd に `--bone`: "no bone named '…': the file has no bone keys"。
- 空の区間: 0 件で成功（2.6）。
- `--copy-to` 負、`--distance-scale` ≤ 0、`--distance-clamp` の MIN MAX（負・逆順・個数）、`--fov-set` < 1、`--delete` との併用、`--replace` 単独、操作と対象の種類違い（表情に `--interp`、照明に `--pos-add` など）: いずれも読む前の `ValueError`。
- 足りないもの: 2.1（重複対象）、2.4（視野角の上限・重みの範囲）。

## 6. `cli.standalone()` と中継

### 6.0 見たが問題なし

- `_motion_file(args)`（cli.py:402-404）は `motion` の `keys` / `edit` だけ真。`standalone()` に入り、`run()` は `dispatch_any(None, args)` で attach せず、`dispatch_any` は `from . import app` より前に分岐する（非 Windows でも `motion keys` は動く。`motion edit` は書き込みで `app.keeping_the_old_file` を関数内 import するので Windows のみ。試験は skip で明示）。
- `main()` は `relay.should_relay(command=None if standalone(args) else args.command)` で、`command=None` は中継しない（relay.py:60）。実測: セッション 0 相当の引数でも `motion keys` は中継されず、`motion load` は中継される。
- `motion load` / `motion save` は `_motion_file` に入らない（試験 `test_they_are_standalone` で両方 False を確認）。

### 6.1 `batch` の中では `motion keys` / `motion edit` の行でも MMD に attach する（低・既存の性質）

場所: batch.py:123-125（`args.command not in ("file", "launch", "ps")` で `make_mmd()`）。

実測: `motion keys cam.vmd` の 1 行だけのバッチで `make_mmd` が呼ばれ、MMD が無ければその行が失敗する（RuntimeError を投げる make で確認）。batch B の `model info FILE` も同じ。README の「どちらも MMD に接続せず」は単発の呼び出しでは正しく、batch では成り立たない。直し方: `run_batch` に `cli.standalone` 相当の判定（引数で受け取る）を渡し、standalone の行では attach しない。

## 7. 試験が実装の写しになっていないか

- 配置の試験 `InterpolationLayoutTest`: `test_bone_rows_are_...` と `test_camera_channels_are_...` は**リテラルのバイト列**と比べている（写しではない）。`test_linear_curve_builds_the_bytes_mmd_writes` は MMD が書いた実測値の定数 `DEFAULT_*` が錨。`test_a_distributed_key_with_different_channels_is_read_from_the_intact_rows` は実物の 16 バイトを `shifted_rows`（試験側の独立な組み立て）で 64 バイトにしたもので、実物の 64 バイトそのもの（詰め物のごみを含む）ではない。1.0 節の実測で同じ行が 11 キーあることを確認したので主張は正しいが、実物の 64 バイトをそのまま定数に置く方が強い（10 節）。
- `InterpTest` / `SetBoneInterpTest` / `SetCameraInterpTest` の「期待値 = `vmd.bone_interpolation(...)`」は実装由来だが、配置は上で別に固定されているので可。
- `QuatMultiplyTest` / `BoneValuesTest.test_composition_order...` は tests/test_mathutil.py の独立な `rotate`（自前のハミルトン積）で順序を固定している。写しではない。
- `CameraUiTest` は本体の往復だけ（`camera_to_ui` ↔ `camera_key_from_ui`）だが、符号の約束は `test_camera_keys_show_the_window_values` のリテラル（ファイル -60 → 表示 60、X は `degrees(-0.1)`）と scene.py の既存の約束で止まっている。
- `SetCameraInterpTest` は差し替えが多く（3.0 節）、MMD 側の挙動は何も保証しない。3.2 の実機試験が要る。
- 実物の配布 vmd を通す試験は無い（`_spike` は gitignore）。小さな実物の抜粋を fixtures に置けるなら 2.2 と 2.9 の回帰試験になる。

## 8. Python 3.9・識別子・README

### 8.0 見たが問題なし

- 8 ファイルとも `ast.parse(feature_version=(3, 9))` を通る。`typing.Optional` / `Tuple`、`dataclasses.replace`、`difflib` のみ。識別子に非 ASCII は無い（日本語は文字列・コメント・試験データだけ）。hinata は 3.10、README は 3.9 以上の約束。
- README の例の数値は実コマンドの出力と一致（実測: `motion keys … --camera --from 0 --to 300` → count 4、(0, 500, fov 30) (150, 700) (247, 800) (248, 325, fov 5)、先頭キー `pos [0, 60, 0]`・`rot [-6, 0, 0]`。`motion edit … --from 0 --to 247 --distance-scale 0.6` → `selected 3 / changed 3 / touched 3`、`cameras 260`、OUT の距離 300 / 420 / 480）。
- README の表（対象・操作・順序・退避・書き順・補間の意味・`camera set --interp` の仕組み）は実装と一致。コマンド表の `bone set` / `camera set` の `--interp` も一致。
- README の `motion keys` の行（状態の確かめ方の表）とコマンド表の行は実装と一致。

### 8.1 README の言い回しの直し（低、2.3 / 2.5 / 2.7 の再掲）

「距離を MIN〜MAX に収める」→ 大きさ、「単一軸のキーなら足し算」→ 同じ軸どうし、「区間の先頭が F」→ 区間内の最初のキーが F。あわせて 2.2（名前が切れた骨を含む vmd）と 2.9（名前欄の詰め物の正規化）を制限として書く。

## 9. 記録（docs/reviews/2026-10-04-batch-c-motion-edit.md）の主張と実測の突き合わせ

| 記録の主張 | 査読の実測 |
| --- | --- |
| MMD v9.32 が書いた t1（4 キー）・fx（3 キー）の 64 バイトは `DEFAULT_BONE_INTERPOLATION` と一致 | 一致（7 / 7） |
| 配布 2 本（39,660 + 52,030）の全キーで 2〜4 行目は 1 行目のずらした写し | えぬた 2 本（各 39,660。記録の「えぬた 39,660」は 1 本分、2 本目は KAZUSA 版）で 100%。KAZUSA 版は手元に無く未確認 |
| 1 行目の 2・3 バイト目は全キー 0 | 79,320 / 79,320 で 0 |
| 群 = x1, y1, x2, y2 の読みで `64 64 64 20 | 0 0 0 20 | …` が ease in/out + 線形 | 一致。加えて、この読みでは全 1,356 チャンネル分が x1 ≤ x2、もう一方の読みでは 273 が x1 > x2 |
| カメラは 1 チャンネル x1, x2, y1, y2。曲線つき 10 キー | 一致。曲線つきは 10 キー（4 + 4 + 1 + 1） |
| pmm は 1 チャンネル x1 y1 x2 y2 | 一致（固定資料 125 キー + カメラ init） |
| 単体試験 363 本 OK（skip 1）、内訳 8 / 60 / 17 | 一致。main と合流した木でも 363 本 OK |
| Python 3.9 の構文 | 一致 |
| README の JSON は実出力から | 一致（8.0） |
| HANDOVER.md は触っていない | 一致（ブランチの差分に無い。差が見えるのは main 側の進み） |
| 探査スクリプトは `_spike/probe_interp.py` `probe_interp2.py` | worktree の `_spike/` にある（gitignore 内）。中身は別の実装で、今回は使っていない |

記録に無い・弱いもの: 2.1（重複対象）、2.2（名前が切れた骨）、3.1（検査がフレーム 0 で空になること）、2.9（名前欄の正規化）。それ以外の「迷った点と根拠」は妥当で、推測は推測と書かれている。

## 10. 追加すべき試験

| 名前 | 検証内容 |
| --- | --- |
| `test_duplicate_targets_are_applied_once`（test_motion_edit） | `resolve_targets(m, [Target("bone","センター"), Target("bone", None)])` が センター を 1 つにする。`--bone センター --all-bones --shift 10` で +10、報告が 1 つ（2.1） |
| `test_a_bone_name_cut_inside_a_character_survives_edit`（test_vmd / test_motion_edit） | 骨名欄に 2 バイト文字の途中で切れた 15 バイトを持つ vmd を `--camera` 相当で編集しても通り、その骨名欄のバイトが元のまま（2.2 の案 1）。案 2 なら原因が分かるメッセージ |
| `test_distributed_key_bytes_are_read_as_measured`（test_vmd） | えぬたの センター 1207 の 64 バイト（`20 20 0 0 20 20 20 20 107 87 … 102 102 230`）をリテラルで置き、`bone_curves` が y = (20,20,87,87)・他は線形を返す。詰め物のごみがあっても読めること（7 節） |
| `test_camera_set_with_interp_returns_the_key_from_the_project`（test_cli、窓なし） | `_project` のカメラキーに `interpolation` を持たせ、結果に `interp_in_project` が入る。距離が欄と違えば `MmdError`（3.1） |
| `test_camera_set_with_interp_keys_the_current_frame` ほか 2 本（tests/live） | 3.2 に書いたとおり。実機でだけ分かる |
| `test_fov_above_the_window_limit_is_refused`（test_motion_edit） | 上限を測った後に `--fov-set 126` / `--fov-add` の結果が上限超えなら `ValueError`（2.4） |
| `test_batch_runs_motion_keys_without_attaching`（test_batch か test_cli） | `make_mmd` が呼ばれないこと（6.1） |
| `test_edit_keeps_untouched_bytes`（test_motion_edit） | 合成でも可: 編集対象外のキーのレコードが bytes 単位で同一、名前欄の NUL の後ろだけ 0 になる（2.9 の明文化） |

## 11. 取り込みの判断

**取り込んでよい（条件つき）。**

- 条件 1（取り込み時に直す。1 行）: 2.1 の重複対象の除去。黙って二重に効く唯一の指摘。
- 条件 2（`camera set --interp` を使う前に）: 3.1 を直し（`interp_in_project` と値の照合）、3.2 の実機試験 3 本を hinata で通す。それまでは README に「`camera set --interp` は実機未検証」を残す（現状の記録にはある。README には無い）。
- 取り込み後の直しでよいもの: 2.2（名前が切れた骨を含む vmd。案 1 が望ましい）、2.3 / 2.5 / 2.7 / 8.1 の README、2.4 の上限（実機で 1 回測る）、6.1（batch の attach）。2.6 / 2.8 / 2.9 / 3.3 / 3.4 / 4.1 は HANDOVER に残すだけでよい。
- 合流: `git merge-tree` は衝突なし（HANDOVER.md は main 側だけが変えた）。合流後の木で 363 本 OK。main の HANDOVER.md 残課題 4「着手（batch C、worktree）」を済に書き換え、8 の「`motion edit` に距離の上下限（clamp）が無ければ取り込み時に足す」は済（`--distance-clamp` あり）に。
- ヒビカセの用途（カメラの 0〜247 を寄せる）に限れば、2.1 と 2.2 は踏まない（対象はカメラ 1 つ、骨名無し）。`motion keys` / `motion edit --camera` は今の版でそのまま使える。

実測したことの一覧:

- 単体試験: worktree 363 本 OK（skip 1、9.0 秒）、main 4062977 との合流木 363 本 OK（skip 1）。モジュール別 60 / 25 / 50。
- 補間の配置: えぬた ダンス 2 本 79,320 キーの行の写し・2・3 バイト目・既定値一致・詰め物・曲線つき 339 キー × 2・2 通りの読みの x1 > x2 の数（0 対 273）、カメラ 260 キーの 5 パターンと 2 通りの読み（0 対 53）、MMD が書いた t1 / fx の 7 キー、pmm 固定資料の 125 + 1 キー、`*_interpolation(LINEAR_CURVE)` と既定値の一致。
- 往復: `loads` → `dumps` の差分の位置（カメラ 9 バイト、ダンス 300,274 バイト、全部名前欄の NUL の後ろ）。
- `motion keys` / `motion edit` を実コマンド（`cli.main --no-relay`）でえぬたのカメラとダンスに当てた結果（README の例の再現、書き順、区間外の不変、IN = OUT の退避の後始末、`--interp` の 2・3 バイト目、`--all-bones --all-morphs --shift` と表示IK）。
- 挙動の探り（合成）: 重複対象の二重適用、`--fov-add 500` / 重み 5 / -0.5、clamp の符号、複数対象で 2 つ目が失敗したときの在庫、空の区間、`--copy-to` の衝突、shift と copy の `--replace` の絡み、standalone / `should_relay` の判定、batch の attach、`--rot-add` の 5 通りの組み合わせ、15 バイトで切れた骨名。
- Python 3.9 の構文と識別子の ASCII（AST）。

やらなかったこと: MMD の起動、schtasks、tests/live、KAZUSA 版 vmd の確認、公開資料の原文の再読（配置の照合は記憶による）、視野角の上限の実測。
