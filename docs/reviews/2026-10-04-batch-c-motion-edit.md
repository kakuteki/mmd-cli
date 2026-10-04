# batch C: vmd のキーの範囲操作（`motion keys` / `motion edit`）と補間曲線の指定（`--interp`）(2026-10-04)

作業場所: worktree `.claude/worktrees/agent-aaa6ff549d2593c39`、ブランチ `worktree-agent-aaa6ff549d2593c39`。
起点: main の f6b69a5（worktree は同じ commit で切られていた。`git merge --ff-only main` は不要だった）。
進め方: 項目ごとに失敗する単体試験を先に書き、失敗を見てから実装し、通ることを見てコミット。MMD は起動しない。tests/live は触らない。
ベースライン: `python -m unittest discover -s tests -t .` は `Ran 278 tests ... OK (skipped=1)`。
途中でネットワークの切断により一度止まった（cli.py を編集し終えた直後、app.py は未着手、記録ファイルは未作成の状態）。worktree の未コミットの変更からそのまま再開した。
再開時に追加された依頼: `motion edit --camera --distance-clamp MIN MAX`（|距離| を範囲に収める。符号は保つ）。

書式: 項目ごとに「何を作ったか／どの試験が守るか／コミット／判断に迷った点と根拠」。項目が終わるたびに追記する。

## 0. 補間データの配置を実物で測った（項目 A・2・3 の前提）

記憶で書かずに、手元にある MMD の書いたファイルと配布モーションで測った（探査スクリプトは `_spike/probe_interp.py` `_spike/probe_interp2.py`、gitignore 内）。

- MMD v9.32 が `motion save` で書いたボーンキー（`_spike/out/t1.vmd` 4 キー、`fx.vmd` 3 キー）の 64 バイトは、`formats/vmd.py` の `DEFAULT_BONE_INTERPOLATION` と 1 バイトも違わない（1 行目 `20 20 0 0 20 20 20 20 107×8`、2 行目 `20×7 107×8 0`、3 行目 `20×6 107×8 0 0`、4 行目 `20×5 107×8 0 0 0`）。
- 配布モーション 2 本（えぬた ヒビカセ ダンス 39,660 キー、KAZUSA 版 52,030 キー）の全キーで、2〜4 行目は 1 行目を 1 バイトずつ左にずらした写しになっている（1 行目の 2・3 バイト目と行末の詰め物を除いて 91,690 / 91,690 キーが一致）。詰め物は MMD v9.32 では 0、配布物には 154 153 25 のようなごみが残っているキーがある（読み飛ばしてよい）。
- 1 行目の 2・3 バイト目は 91,690 キー全部で 0。曲線が線形でないキーでも 0 のままで、2 行目の同じ位置（ずらした写しの側）には Z と回転の x1 が入っている。つまりこの 2 バイトは曲線でなく、MMD が別の用途に使っている（物理 ON/OFF の旗と言われる。**推測**。物理 OFF のキーを含む実例は手元に無く、値は確かめていない）。
- ボーンの 1 行目の並びは「4 群 = x1, y1, x2, y2、各群の中が X Y Z 回転」。根拠は曲線つきのキーの実例: えぬた `64 64 64 20 | 0 0 0 20 | 64 64 64 107 | 127 127 127 107` はこの読みで X Y Z = (64,0)-(64,127)（中央で立つ S 字 = ease in/out）・回転 = 線形になる。もう一方の読み（x1, x2, y1, y2 の群）だと制御点が (64,64)-(0,127) になり x2 < x1 で不自然。KAZUSA 版の `62 | 0 | 107 | 107`（(62,0)-(107,107) = ease in）、`20 | 20 | 60 | 127`（線形から ease out）も同様。
- カメラの 24 バイトは 1 チャンネル 4 バイトで「x1, x2, y1, y2」。既定 `20 107 20 107` が (20,20)-(107,107) になり、えぬたのカメラの曲線つき 10 キーは `64 64 0 127`（= (64,0)-(64,127)、ボーンと同じ ease in/out）・`64 127 0 127`（ease in）・`0 64 0 127`（ease out）。別の読み（x1, y1, x2, y2）だと (64,64)-(0,127) で不自然。
- 群の中のチャンネルの並び（X Y Z 回転 / X Y Z 回転 距離 視野角）は既知の資料どおりとしたが、実物からは区別できない（**推測**）。本機能は全チャンネルに同じ曲線を書くので、並びは結果に影響しない。読み戻し（`bone_curves` / `camera_curves`）の名前づけにだけ効く。
- pmm の 16 / 24 バイトは別の並び（1 チャンネル `x1 y1 x2 y2`。固定資料 `tests/fixtures/scene_v932.pmm` の全キーが `20 20 107 107` の繰り返し）。pmm.py は触っていない。

## A. `formats/vmd.py` の補間の組み立て補助と `mathutil.quat_multiply`

- 何を作ったか: `LINEAR_CURVE = (20, 20, 107, 107)`、`BONE_CHANNELS`、`CAMERA_CHANNELS`、`check_curve(curve)`（4 つの 0〜127 の整数。bool・小数・文字列は拒む）、`bone_interpolation(curve, keep=None)`（上の配置で 64 バイトを組む。`keep` に既存キーの 64 バイトを渡すと 1 行目の 2・3 バイト目だけそのまま残す。新規キーは 0）、`camera_interpolation(curve)`（24 バイト）、`bone_curves(data)` / `camera_curves(data)`（チャンネル → (x1, y1, x2, y2)。ボーンの Z・回転の x1 は 2 行目から読む）。既定値の定数はそのまま（測った証拠として残す）。`mathutil.quat_multiply(a, b)` はハミルトン積（b を先に、次に a）。
- 守る試験: tests/test_vmd.py `InterpolationLayoutTest` 8 本（線形から組むと既定値に一致、行の並び、読み戻し、配布物の実例ブロックの読み、`keep`、カメラの x1 x2 y1 y2、値の検査、ファイルを往復）。`quat_multiply` は tests/test_motion_edit.py `QuatMultiplyTest`（単位元、独立に書いた回転で順序を確認、長さ 1）。
- コミット: 1b76366
- 迷った点: 既定値を組み立て関数で置き換えるか → 置き換えず定数のまま残し、「線形から組むと一致する」を試験にした（測った値が正本）。

## 1. `mmd motion keys FILE.vmd [--camera | --bone 名前 | --morph 名前 | --light] [--from A --to B]`

- 何を作ったか: 新規 `mmd_cli/motion_edit.py` の `keys_file(path, spec, span)`（CLI から独立）。対象なしなら `summary`（種類ごとの件数 `counts` と `ranges`（最初と最後のフレーム。区間を付ければ区間内）、`model_name`、`kind`）。対象ありなら `list_keys`（フレーム順。カメラは frame, distance（正）, pos, rot（度。X は符号を反転）, fov, perspective。ボーンは frame, pos, rot（`mathutil.quat_to_ui`）。表情は frame, weight。照明は frame, rgb（×256 で整数。scene.py と同じ）, dir）。数値は scene.py と同じ丸め（小数 4 桁、-0.0 を消す）。cli.py: `motion` グループに `keys`（対象は排他群、`--from/--to`）、`_motion_file(args)` を `standalone()` に足し、`dispatch_any` と `_dispatch` の motion の行で `_motion_file_command` に回す（MMD なし・中継なし）。`--from` だけ／`--to` だけ／負／逆順は `check_range` が `ValueError`（終了コード 2）。
- 守る試験: tests/test_motion_edit.py `RangeTest` `SelectTest`（両端を含む・空の区間・同名ボーンの混在から名前で選ぶ）`NamesTest`（候補名つきのエラー、`--all-bones` の展開）`ListTest`（件数と区間、表示値、フレーム順）`KeysFileTest`。tests/test_cli.py `MotionKeysEditParserTest.test_motion_keys_takes_one_target_and_a_range`、`MotionFileCommandsTest`（standalone、`--from` だけはファイルを読む前にエラー、summary と一覧、`main` 経由で JSON と `--out`）。
- 通し確認（MMD なし、実コマンド）: えぬたのカメラ vmd で `motion keys` → 260 キー・0〜7742。`--camera --from 0 --to 300` → 4 キー（距離 500 / 700 / 800 が fov 30、248 から距離 325 の fov 5）。`--from 1700 --to 1900` → 8 キー（距離 125〜325、fov 5 と 30 が切り替わる）。
- コミット: 項目 2 と同じコミット（motion_edit.py は一覧と編集を 1 つのモジュールに持ち、cli.py の `motion` グループの変更も共通なので分けなかった）。
- 迷った点: 一覧の並びはファイル順でなくフレーム順にした（人が読むため。編集の方はファイル順を保つ）。summary に骨名・表情名の一覧は入れない（`file info` にある。長くなる）。照明の rgb は scene.py の ×256 に合わせた（1.0 は 256 になる。vmd の値が MMD の 0〜255 からどう写るかは scene.py の実測に従った）。

## 2. `mmd motion edit IN.vmd OUT.vmd 対象... [--from A --to B] 操作...`

- 何を作ったか: motion_edit.py の `Target`（kind, name。bone / morph の name None は「ファイル内の全名前」で `resolve_targets` が展開）、`Operations`（dataclass）、`check_operations`（操作なし／`--delete` と他の併用／`--replace` 単独／`--copy-to` 負／`--distance-scale` ≤ 0／`--distance-clamp` の MIN MAX／`--fov-set` < 1／`--interp` の範囲／操作と対象の種類の不一致を、ファイルを読む前に `ValueError`）、`apply(motion, targets, ops, span)`（対象ごとに `_apply_one`）、`edit_file(src, dst, specs, ops, span)`（読む → 検査 → 名前の解決 → apply → `vmd.dumps` → 書く → `vmd.load` で読み戻して件数を返す）。
  - 適用順は `ORDER = ("shift", "copy", "values", "interp")`。`--delete` は単独（他の操作と併用するとエラー）。
  - `--shift N`: 選んだキーのフレームに N を足す。0 未満になるキーがあれば何も変えずにエラー。移動先に同じ対象（同じ骨名／表情名、カメラ、照明）の区間外のキーがあればエラー、`--replace` ならそのキーを消す。区間内のキー同士が互いの元の位置へ動くのは衝突にしない。
  - `--copy-to F`: 区間の先頭が F に来るように複製（`dataclasses.replace`、別オブジェクト）。既存キー（区間内の元のキーも含む）と重なればエラー、`--replace` なら置き換える。複製は節の末尾に追加（ファイル順は保つ。並べ替えない。配布 vmd はもともとフレーム順でない）。
  - 値の変更は「選んだキー + その呼び出しで作った複製」に効く。順序は scale / set → add → clamp。カメラ: `--distance-scale K`（K > 0。ファイルは負の距離なので符号はそのまま）、`--distance-add D`（表示値の意味。ファイルの値から D を引く）、`--distance-clamp MIN MAX`（|距離| を [MIN, MAX] に。符号は保つ。0 は通常の向き（負）として扱う）、`--pos-add X Y Z`、`--fov-set F` → `--fov-add F`（結果が 1 未満ならエラー）。ボーン: `--pos-add`、`--rot-add X Y Z`（表示値の度。`ui_to_quat` で四元数にし、`q_new = quat_multiply(q_key, q_add)` = キーの回転の後にボーン自身の軸で回す）。表情: `--weight-set W` → `--weight-scale K`。
  - `--interp x1 y1 x2 y2`: 触ったキーの曲線を全チャンネル同じ値に置換。ボーンは `bone_interpolation(curve, keep=元の 64 バイト)`（1 行目の 2・3 バイト目を保つ）、カメラは `camera_interpolation`。表情・照明に付けるとエラー。
  - 書き込みは `app.keeping_the_old_file` の下で `.part` に書いて `os.replace`（既存の OUT は `名前.mmdcli-old` に退避し、成功で消す・失敗で戻す。IN と OUT が同じパスでも IN は先に全部読んであるので同じ規則で安全）。import は関数の中（app は Windows 専用）。
  - 結果 JSON: `in`, `out`, `range`, `order`, `targets`（対象ごとに `kind`/`name`, `selected`, `shifted`/`copied`/`deleted`/`replaced`/`changed`/`interp` の該当分, `touched` = 触った・作った・消したキーの数）, `counts`（OUT を読み戻した種類ごとの件数）。
  - cli.py: `edit` の引数（`--bone`/`--morph` は append、`--all-bones`/`--all-morphs`、`--camera`/`--light`、区間、操作。`--interp` は `curve_value` 型で 0〜127 以外は argparse の段階で終了コード 2）。`_motion_targets(args)` と `_motion_file_command(args)` で `Operations` を組む。
- 守る試験: tests/test_motion_edit.py `ValidationTest` `ShiftTest`（区間外は動かない、負、0 未満は何も変えずエラー、衝突と `--replace`、区間内の入れ替わり、同名の別ボーンは衝突にならない、空の区間）`DeleteTest` `CopyTest`（複製の値と別オブジェクト、重なりと `--replace`、自分の区間に重なる複製、名前で絞る、空の選択）`CameraValuesTest`（距離の符号、add の向き、scale → add → clamp、clamp の符号と 0、fov の順序と下限、区間外は変わらない）`BoneValuesTest`（合成の順序を独立のハミルトン積で固定）`MorphValuesTest` `InterpTest`（2・3 バイト目を保つ、表情・照明はエラー）`OrderTest`（4 操作を 1 回で・複数対象）`CameraUiTest` `EditFileTest`（OUT の読み戻し、IN は不変、エラーは書く前、IN = OUT の退避、既存 OUT の置換、フォルダは拒否）。tests/test_cli.py `MotionKeysEditParserTest`、`MotionFileCommandsTest`（書いて読み戻す、clamp、対象・操作の検査、`main` 経由の終了コード 2）。
- 通し確認（MMD なし、実コマンド）: えぬたのカメラ vmd に `motion edit ... --camera --from 0 --to 300 --distance-clamp 0 60` → `touched 4`、OUT を `motion keys` で読むと 0 / 150 / 247 の距離が 60 に、248（もともと 325・fov 5）も 60 になった（区間の端は `keys` を見て決める必要がある。README の例では 0〜247 にする）。注視点 `pos` は (0, 60, 0) のまま高いので、距離だけ詰めても人物が画面中央に来るとは限らない（`--pos-add` で下げる案を報告に書く）。
- コミット: （項目 1 と同じコミット。後述）
- 迷った点と根拠:
  - `--delete` を他と組み合わせられるか → 単独にした。「消してからずらす」に意味が無く、組み合わせを許すと「触った 0 件」が黙って返るだけになる。指示の例の順序（delete → shift → copy → 値 → 補間）は、delete 以外をその順で固定した。
  - 値の変更を複製にも効かせるか → 効かせる（複製して調整する使い方が自然。原本だけ変えたければ 2 回に分ける）。README に明記。
  - `--rot-add` の合成順 → ボーン自身の軸（`q_key * q_add`）。単一軸のキーなら表示値の足し算と一致する。親の軸で回したい用途は今回は無い。試験で独立のハミルトン積から固定した。
  - 書き順を並べ替えないこと → 配布 vmd 自体がフレーム順でなく MMD はそれを読むので、IN の順を保つのが最も驚きが少ない。
  - 書き込みに `app.keeping_the_old_file` を使う（motion_edit が app に依存する）か自前で同じ規則を書くか → 「同じ規則」を保つには関数を共有するのが確実。import は関数内に置き、読むだけ（`keys`）なら app を読み込まない。
  - 視野角の上限 → MMD の上限を測っていないので下限 1 だけ検査（**推測を避けた**）。
  - 同名ボーンのキーが混ざる場合 → 名前の完全一致で選ぶ。衝突の判定も同じ名前の中だけ。

## 3. `mmd bone set ... --interp` と `mmd camera set ... --register --interp`

- 何を作ったか: app.py `set_bone(..., interp=None)`: `vmd.check_curve` を最初に通し（不正なら何も落とす前に `ValueError`）、`BoneKey` の interpolation に `bone_interpolation(curve)`（指定なしは今までどおり既定の線形）。結果に `interp`（指定値）と `interp_in_project`（登録後の pmm が持つそのキーの 16 バイトを生のまま。実機試験で曲線が入ったかを見るための証拠）を、指定があるときだけ足す。`set_camera(..., interp=None)`: `--interp` には `--register` が要る（無ければ `ValueError`）。**カメラの登録ボタンには曲線を渡せないので、`--interp` のときだけ登録の手段を変える**: 欄に値を入れた後、`_read_camera()` が示す値（表示値）から `motion_edit.camera_key_from_ui` で 1 キーのカメラ vmd（フレーム 0 = MMD が現在のフレームに置く。距離は負、X の角度は符号反転、ラジアン）を組み、`_drop_motion` で読ませ、`_project()` のカメラのキーに現在のフレームのものが無ければ `MmdError`。`--interp` なしは今までどおり登録ボタン（MMD 側の操作は変えていない）。cli.py: `bone set` / `camera set` に `--interp X1 Y1 X2 Y2`（`curve_value` 型）、`_dispatch` で渡す。
- 守る試験: tests/test_cli.py `MotionKeysEditParserTest.test_interp_values_outside_0_127_are_usage_errors`、`DispatchInterpTest`、`SetBoneInterpTest`（窓なしの Mmd で `_drop_motion` に渡った vmd を読む: 指定なしは既定の線形・指定ありは 4 チャンネルに曲線・2・3 バイト目は 0・`interp_in_project`・不正な曲線は落とす前に止まる）、`SetCameraInterpTest`（指定なしは登録ボタンを押し vmd を落とさない・指定ありは登録ボタンを押さず 1 キーのカメラ vmd を落とす（距離 -30、位置、角度の符号と単位、fov、perspective、24 バイト）・`--register` 無しはエラー・登録後にキーが無ければ `MmdError`）。
- 実機: 走らせていない（指示どおり）。**特に `camera set --interp` は MMD にカメラ vmd を落として登録する新しい経路なので、実機試験で確かめるまで未検証**（カメラモードでの vmd の読込で確認ダイアログが出るか、現在のフレームに置かれるか、`_project()` のキーに現れるか）。
- コミット: （後述）
- 迷った点: 指示は「`set_camera` が組み立てる vmd に反映するだけ」だが、現状の `set_camera` は vmd を組み立てず欄と登録ボタンで登録している。曲線を付ける手段は vmd 経由しか無いので、`--interp` のときに限って vmd 経由にした。`--interp` なしの挙動は変えていない。
