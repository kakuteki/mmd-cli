# batch B: `mmd model info` と pmx / pmd の読み取り (2026-10-04)

作業場所: worktree `.claude/worktrees/agent-a7769b4f14a7f6723`、ブランチ `worktree-agent-a7769b4f14a7f6723`。
起点: main の da80c0c（worktree は同じ commit で切られていた）。
進め方: 項目ごとに失敗する単体試験を先に書き、失敗を見てから実装し、通ることを見てコミット。MMD は起動しない。tests/live は触らない。
ベースライン: `python -m unittest discover -s tests -t .` は `Ran 195 tests ... OK (skipped=1)`。
途中でネットワークの一時的なエラーにより一度止まった（項目 1 の試験を直した直後。worktree には未コミットの pmx.py と test_pmx.py だけが残っていて、そこから再開した）。

書式: 項目ごとに「何を作ったか／どの試験が守るか／コミット／未確認」。項目が終わるたびに追記する。
仕様の出所と、実ファイルで確かめたことは末尾の「pmx / pmd の構造で判断したこと」にまとめる。

## 1. `mmd_cli/formats/pmx.py`（PMX 2.0 / 2.1）

- 何を作ったか: `load(path)` / `loads(data)` が `Model`（dataclass: format, version, name, name_en, comment, comment_en, counts, bones, morphs, display_frames）を返す。`Bone`（index, name, name_en, parent, layer, flags, append, ik）、`Morph`（index, name, name_en, panel, kind, offsets）、`DisplayFrame`（name, name_en, special, items）も dataclass。`Model.to_json(brief=False)` は `dataclasses.asdict`、`brief=True` で 3 つの一覧を落とす。頂点はウェイト種別（0 BDEF1 / 1 BDEF2 / 2 BDEF4 / 3 SDEF / 4 QDEF）と追加 UV 数で長さを変えて飛ばし、面は index size × 3、材質はトゥーンの持ち方（共有番号 1 バイト／テクスチャ index）で分岐、剛体・ジョイント・（2.1 の）ソフトボディも最後まで歩いて、残りバイトがあれば pmm と同じ文言でエラーにする。件数欄と文字列長は「残りバイトに入らない」なら読む前に `PmxFormatError`（位置つき、`ValueError` の派生）。index は頂点以外すべて符号つき（1/2/4 バイト）、-1 は None。頂点 index は読まず飛ばすだけ（符号なしの扱いが要る場面が無い）。
- 守る試験（tests/test_pmx.py、`Writer` が最小の pmx をバイト列で組み立てる。31 本）: 名前の UTF-16LE / UTF-8（`test_names_and_comments_in_utf16` / `test_names_in_utf8`）、壊れたバイトは置換（`test_bad_bytes_in_a_name_are_replaced_not_fatal`）、ウェイト種別 5 つ × 追加 UV 0/1/4 × 骨 index 1/2/4 の飛ばし方（`test_every_weight_type_is_skipped_so_the_bones_are_found`）、頂点 index 1/2 バイトの符号なし（`test_vertex_indices_of_size_1_and_2_are_unsigned`）、未知のウェイト種別は位置つきエラー、材質の 3 通りの持ち方 × index size、面の個数が 3 の倍数でない、旗 11 個の名前、親・階層・付与・IK（index size 1/2/4）、任意ブロック全部入りの骨の次の骨が正しく読める、表情の枠 1〜4（と 0 = system）と種類 11 個、未知の種類はエラー、表示枠の骨/表情、`to_json` と `brief`、空ファイル・不正な magic・未対応の版・途中で切れた・ヘッダ切れ・巨大な件数と巨大な文字列長（位置つき）・末尾の余りバイト・ヘッダの不正値。実機: `SourRinTest`（White.pmx）と `TdaTetoTest`（ファイルが無ければ skip）。
- 実機で確かめた値（試験に固定）: White.pmx は骨 373・表情 133・表示枠 14・剛体 186・ジョイント 273・材質 26。373 本の妥当性: 表示枠に入っている骨は 287 本で、`flags.visible` の骨の集合と一致する。残り 86 本は 先（tip）・補助・腰キャンセル・スカートの最内周（_7_*）など非表示の補助骨で、名前を目で確かめた。センター は 全ての親 の子（parent は None ではない）なので、試験は「親をたどった根が None で、その名が 全ての親」にした。まばたき は panel "eye"、あ は "mouth" で種類 group、左足ＩＫ は loops 40・角 2.0 rad（float32 なので 2.0000007。等値でなく近似で比べる）、左目 は 両目 からの回転付与 ×1。ファイル末尾に 1 バイト足すとエラー（読み切りの検査）。Tda式重音テトAP.pmx は骨 150・表情 56・表示枠 11、面 index 150192（= 50064 面）。
- コミット: 2f5839c
- 未確認: QDEF（2.1）・フリップ／インパルスモーフ・ソフトボディは手元に実ファイルが無く、仕様書どおりに組み立てた合成データでしか確かめていない。頂点 index の符号も同様（読まないので影響は飛ばす長さだけ）。

## 2. `mmd_cli/formats/pmd.py`（PMD 1.0）

- 何を作ったか: `load(path)` / `loads(data)` が pmx と同じ `Model` を返す（dataclass は pmx.py のものを import）。ヘッダ "Pmd"・float 版（1.0 以外は拒む）・名前 20・コメント 256、頂点 38 バイト、面 u16、材質 70 バイト（50 バイト目からのテクスチャ名を `*` で割って `counts["textures"]` = 異なる名前の数）、骨 39 バイト、IK、表情（頂点 16 バイト × n を飛ばす）、表情枠（u8 件数 + u16）、骨枠名 50 バイト、骨枠所属（u16 + u8）。ここまでが必須。その後ろの 英語ブロック（旗 u8、1 なら 名前 20・コメント 256・骨名 20 × 骨数・表情名 20 × max(表情数 − 1, 0)・枠名 50 × 枠数）、トゥーン 100 × 10、剛体 83 バイト、ジョイント 124 バイト は、ファイルがその前で終わっていれば無いものとして返し（件数 0・英語名 None）、始まっているのに途中で切れていれば位置つきの `PmdFormatError`。最後に余りがあればエラー（pmm と同じ文言）。件数欄（u8/u16/u32）は残りバイトと照らして先に拒む。文字列は cp932・NUL で切る・壊れたバイトは置換。pmd の骨枠名は末尾に改行コードが付いた形で格納されているので取り除く。
- 骨種別 → flags の規則（pmd.py の docstring に表で書いた）: rotate は全種別 True。translate は 1・2。visible = enabled は 0/1/2/4/5/8（枠に出る種別）。ik は 2 または IK 表に名がある骨。append_rotate は 5（parent = ik_parent 欄、ratio 1.0）と 9（parent = tail 欄、ratio = ik_parent 欄 / 100）。fixed_axis は 8。layer は 0、append_translate / local_axis / physics_after / external_parent は常に False。種別 3 は実例が無く 7 と同じ扱い（非表示）。表情の `index` はファイルの skin 番号で、base（種別 0）は一覧と `counts["morphs"]` から外す（他の番号は詰めない）。表情枠は特殊枠「表情」（name_en None）として先頭に置き、骨枠が続く。骨枠所属の枠番号は 1 始まり、範囲外の所属は捨てる。IK の角度は生の値（PMX の radian の 1/4）。
- 守る試験（tests/test_pmd.py、`build()` が最小の pmd を組み立てる。31 本）: 名前・件数・テクスチャ数、NUL で切る・壊れたバイトの置換（Python の cp932 は 0xFF を U+F8F3 に写すので「壊れた」例には末尾の孤立した先行バイト 0x81 を使った）、版 2.0 の拒否、種別 0〜9 全部の flags と append と IK（`test_every_bone_type_becomes_flags`）、IK 表にあれば種別が違っても ik、英語名の対応、表情の枠と skin 番号、骨枠の改行除去と所属、`to_json`、必須部で終わるファイル・英語旗 0・表情 0 件の英語ブロック・トゥーンで終わる・剛体で終わる、空・不正な magic・ヘッダ切れ・骨の途中で切れ・英語ブロックの途中で切れ（短く読まない）・巨大な件数（頂点・表情の頂点数。位置つき）・面の個数が 3 の倍数でない・末尾の余り。実機: 初音ミク.pmd・MEIKO.pmd・カイト.pmd・ダミーボーン.pmd（無ければ skip）。
- 実機で確かめた値（試験に固定）: 初音ミク.pmd は name "初音ミク"・name_en "Miku Hatsune"、counts = 頂点 9036・面 14997・テクスチャ 1・材質 17・骨 122・表情 15・表示枠 8（骨枠 7 + 表情）・剛体 45・ジョイント 27。センター は index 0 で parent None、左ひざ（種別 4）は表示、左目（5）は 両目 からの付与 ×1、左つま先（6）と 頭先（7）は rotate だけ、左足ＩＫ は loops 40・角 0.5・links 左ひざ→左足・target 左足首、IK を持つ骨 7 本。枠に属する骨は visible の集合に含まれ、差は センター だけ（MMD は センター を独立に出す）。まばたき は panel "eye"・index 5・name_en "blink"、あ は "mouth"・index 9。**pmm の照合**: tests/fixtures/scene_v932.pmm（この模型を読み込んで MMD が保存したもの）の骨名の列は pmd の骨名の列と一致し、表情の列は `["base"] + pmd の表情名` と一致する（= MMD の表情番号は skin 番号そのもの。`index` にこれを使う根拠）。MEIKO.pmd は骨 99・表情 42・表示枠 8。カイト.pmd は骨 106・表情 24 で、剛体・ジョイント節が無い（トゥーンで終わる実例）。ダミーボーン.pmd は骨 30・表情 0・頂点 0 で、英語ブロックに表情名が 0 件（−1 件ではない）。全 14 本の pmd で 14 本とも末尾まで読み切った（探査スクリプトで確認、残り 0 バイト）。
- コミット: db0f3d0（pmx.py の `_Reader` を継承できるようにした変更と、この記録の項目 1 を含む）
- 未確認: 種別 3「不明」と、英語ブロックの旗が 0 のファイルは手元に実例が無い（合成データのみ）。種別 9 の比率の解釈は 初音ミクVer2.pmd の 25/50/75 と、同じ骨が pmx 版（Sour式）で 補助 ×0.6 のような回転付与になっていることからの判断で、MMD 本体の計算を測ったわけではない。

## 3. `mmd model info` と `mmd file info` の pmx / pmd

- 何を作ったか: cli.py の `model` グループに `info [TARGET]`（`_dispatch` は `mmd.model_info(parse_target(args.target))` の 1 行）、`file info FILE [--brief]`（`_file_info(path, brief)` に .pmx/.pmd の分岐、`dispatch_any` から `args.brief` を渡す）。app.py は `Mmd.model_info(target=None)` の追加だけ（import も method の中に置き、他の行は触っていない）: TARGET が存在する .pmx/.pmd ならそのまま読む。それ以外は `self.dump(keys=False)` の `models[i]["path"]` から読む（None = `selected_model`、int = index、str = name）。dump が `MmdError`（手で開かれたプロジェクト）を出したら、その文言に「Or read the model file itself: mmd model info FILE.pmx」を添えて `MmdError`。選択なし・範囲外・名前なし・ファイルが移動済みも `MmdError`。結果は `{"path": ..., "format", "version", "name", "name_en", "comment", "comment_en", "counts", "bones", "morphs", "display_frames"}`。`file info` は `path` なしで同じ中身（`--brief` は一覧 3 つを落とす）。
- 制約から来る振る舞い: `model info` は `model` グループなので `run()` が先に MMD へ attach する（`run()`・`STANDALONE` は触っていない）。MMD が動いていないときにファイルだけ読みたい場合は `file info`。SSH などデスクトップの外からは `model info` は中継され、`file info` はその場で走る（従来どおりの区分）。
- 守る試験（tests/test_cli.py に追加、10 本）: 引数解釈 `test_file_info_takes_brief` / `test_model_info_target_is_optional`、`FileInfoTest`（合成 pmx/pmd をファイルに書き `_file_info` の full / brief、parser → `dispatch_any` 経由、JSON 化できる）、`DispatchModelInfoTest`（偽の Mmd に parse_target 済みの値が渡る: "2" → 2、名前、パス、省略 → None）、`ModelInfoTest`（窓なしの `Mmd` に `dump` を差し替え: ファイルなら dump を呼ばない・選択中/番号/名前・`keys=False`・未知の名前と範囲外と選択なしが MmdError・手で開かれたプロジェクトの文言に "mmd model info FILE"・移動済みファイルはパス入りの MmdError）。
- 通し確認（MMD なし、実コマンド）: `python -m mmd_cli file info 初音ミク.pmd --brief` と `... White.pmx --brief` が ASCII の JSON を出す。White.pmx（3.3 MB）の `file info` はプロセスごと 0.26 秒。`--out out/miku.json` で UTF-8 の読める JSON。`.exe` は `ValueError: unsupported file type`、無いファイルは `FileNotFoundError`（どちらも JSON・終了コード 1）。
- コミット: 4e6f590
- 未確認: 実機の MMD に対する `model info`（dump 経由の経路）は走らせていない（MMD を起動しない指示）。`dump` 自体は既存の実機試験で動いているので、残る不確かさは `summary["selected_model"]` が camera モードのときに何を返すか（scene.summarize は pmm の `selected_model_index` をそのまま返す。モデルが無いときだけ None）。

## 4. README と、pmd の `counts` のキー順

- 何を作ったか: README の「状態の確かめ方」の表に `model info` の行を足し `file info` の行に pmx / pmd を足した。コマンド表の `model` 行に `info [名前|番号|F]`、`file info F [--brief]`。`dump` の例の後ろに「モデルの骨と表情」の小節（コマンド 2 行と、初音ミク.pmd の実出力から抜いた JSON、`index` / `panel` / `kind` / `angle` の読み方）。例の数値は `--out out/miku.json` で書いた実出力から写した（センター・左目・左足ＩＫ・まばたき・あ・表情枠の先頭 2 件・ＩＫ枠の先頭 2 件）。ついでに pmd の `counts` のキー順を pmx と同じ（vertices, faces, textures, materials, bones, morphs, display_frames, rigid_bodies, joints）に揃えた（通し確認で順が違うのに気づいた。中身は同じ）。
- 守る試験: tests/test_pmd.py `test_names_counts_and_textures` にキー順の assert を足した（揃える前は失敗、揃えて通る）。README は試験なし。
- コミット: b05c6a8（この記録の項目 2〜4 と「構造で判断したこと」を含む）。まとめの追記は次のコミット。

## pmx / pmd の構造で判断したこと（仕様の出所と実ファイルで確かめたこと）

- 仕様の出所: PMX は PMXEditor 同梱の PMX仕様.txt（2.0 と 2.1 の追加分）の記憶、PMD は MMD 初期からの非公式解析（「PMD 形式まとめ」）の記憶。どちらも手元に原文は無いので、**実ファイルで読み切れること**（14 本の pmd と 11 本の pmx の全部で残り 0 バイト）を根拠にした。読み切れない配置なら末尾まで辿り着けないので、各節の長さの取り違えはここで露見する。
- pmx の index: 頂点以外は符号つき（1 バイトは −128〜127）で −1 が「なし」、頂点 index は 1/2 バイトが符号なし。手元の pmx は全部 頂点 2・テクスチャ 1・材質 1・骨 2・表情 1 か 2・剛体 1 か 2 だったので、1 バイトの骨 index と 4 バイトは合成データでしか確かめていない。
- pmx のウェイト: BDEF1 = 骨 1、BDEF2 = 骨 2 + float、BDEF4 = 骨 4 + float 4、SDEF = BDEF2 + float3 × 3、QDEF（2.1）= BDEF4 と同じ長さ。手元の pmx に出るのは 0〜3 だけ（例: White.pmx は 16553 / 9533 / 12279 / 2511）。
- pmx の材質のトゥーン: 共有トゥーン旗が 1 なら 1 バイト、0 ならテクスチャ index。表情のオフセット長は 種類 × index size で固定（材質モーフは index + 1 + 112 バイト = 4 floats ×4 + 3 floats ×2 + float ×2 … の合計 113 バイト）。
- pmx の表情の panel 0: 仕様では「システム予約」。White.pmx には panel 0 の表情が 23 個ある（グループモーフの部品。MMD の表情パネルには出ない）。語は "system" にした。
- pmx の `センター`: Sour式も Tda式も `全ての親` の子なので「parent が None」は成り立たない。試験は根が None（= 全ての親）であることで置き換えた。pmd（ミク・MEIKO）では センター は index 0 で parent None。
- pmd の骨種別の写し方は pmd.py の docstring の表のとおり。根拠は「どの種別が骨枠に属するか」（14 本で 0/1/2/4/5/8 のみ。6「IK接続先」= 左つま先 や 7「非表示」= 〜先、9「回転運動」= 腕捩1〜3 は一度も枠に無い）。`enabled` を visible と同じにしたのは私の判断（PMXEditor が pmd を pmx に変換すると 先 骨にも 操作可 を立てるようなので、変換結果と比べると 先 骨の `enabled` が違う可能性がある。推測）。
- pmd の種別 9 の欄の意味: 初音ミクVer2.pmd の 左腕捩1/2/3 は parent = 左腕、tail = 左腕捩（19）、ik_parent = 25 / 50 / 75。ik_parent が骨番号なら 左親指２・右腕・両目 になり意味をなさないので、tail が回転元・ik_parent が百分率と読んだ。種別 5 の 左目 は ik_parent = 両目（71）、tail = 左目先。
- pmd の IK の角度は pmx の 1/4: 同じ標準リグで 足ＩＫ 0.5 ↔ 2.0、つま先ＩＫ 1 ↔ 4、ﾈｸﾀｲＩＫ 0.03 ↔（Tda 0.0872665 = 5°）。値は変換せず生のまま持ち、docstring と README に単位を書いた。
- pmd の表情番号: pmm の表情一覧が `["base", ...]`（16 件）で、まばたき が 5 番・あ が 9 番 = skin 番号そのもの。だから `index` は skin 番号、base は一覧と件数から外す（`mmd dump` の `morph_count` は 16 と出て `model info` の `counts["morphs"]` は 15 になる。この差は MMD が base を数えるためで、意図したもの）。
- pmd の英語ブロックの表情名は (表情数 − 1) 件。表情 0 件のダミーボーン.pmd では 0 件（−1 件と計算すると 20 バイト戻って以後が全部ずれる。探査スクリプトで最初にこの誤りを踏んだ）。
- pmd の後置節: カイト.pmd とダミーボーン.pmd は英語ブロックとトゥーンで終わり、剛体・ジョイント節が無い。他の 12 本は全部そろっている。
- pmd の骨枠名は "ＩＫ\n" のように改行つきで格納（ダミーボーンの 'ﾎﾞｰﾝ02～' には無い）。改行は取り除く。センター はどの枠にも属さない（MMD が独立に出す）ので、Root 枠は作らない。
- pmd の `counts["textures"]`: 材質 70 バイトの末尾 20 バイトのテクスチャ名を `*` で割った異なる名前の数（ミクは eye2.bmp だけで 1）。トゥーンの 10 枚は数えない。

## まとめ

- コミット（worktree のブランチ `worktree-agent-a7769b4f14a7f6723`、起点 da80c0c、push していない）: 2f5839c（pmx）→ db0f3d0（pmd）→ 4e6f590（model info / file info）→ b05c6a8（README・counts の順・記録）→ このまとめ。
- 単体試験: `python -m unittest discover -s tests -t .` → `Ran 267 tests in 13.616s` / `OK (skipped=1)`（195 → 267、skip は tests/live のまま）。内訳の追加分は test_pmx 31・test_pmd 31・test_cli 10。MMD は起動していない。tests/live は触っていない。
- 実機モデルで読めた件数（骨 / 表情 / 表示枠、すべて末尾まで読み切り）: 初音ミク.pmd 122 / 15（+ base）/ 8、MEIKO.pmd 99 / 42 / 8、カイト.pmd 106 / 24 / 8（剛体・ジョイント節なし）、ダミーボーン.pmd 30 / 0 / 2、Sour式鏡音リン White.pmx 373 / 133 / 14、Tda式重音テトAP.pmx 150 / 56 / 11。残りの pmd 8 本・pmx 9 本も探査スクリプトで残り 0 バイトまで読めた。
- Python 3.9: 触った 7 ファイルを `ast.parse(..., feature_version=(3, 9))` で通した。match 文・`X | Y`・removeprefix は使っていない。
- 触ったファイル: 新規 mmd_cli/formats/pmx.py・mmd_cli/formats/pmd.py・tests/test_pmx.py・tests/test_pmd.py・docs/reviews/2026-10-04-batch-b-model-info.md、追加のみ mmd_cli/cli.py（`model info` の parser と `_dispatch` の 1 行、`file info --brief`、`_file_info` の分岐、`dispatch_any` の `brief` 引き渡し）・mmd_cli/app.py（`Mmd.model_info` だけ。import は method の中）・tests/test_cli.py・README.md。guard.py / relay.py / win32.py / scene.py / formats/pmm.py / HANDOVER.md は触っていない。
- できなかった・やらなかったこと:
  - 実機の MMD に対する `mmd model info 名前`（dump 経由）の通し確認。指示どおり MMD を起動していない。実機の `tests/live` に 1 本足すのも範囲外（tests/live は触らない）。
  - `model info ファイル` は MMD が無いと attach で失敗する（`run()` と `STANDALONE` を触らない制約のため）。MMD なしなら `file info`。
  - QDEF・フリップ／インパルスモーフ・ソフトボディ・pmd 種別 3・英語旗 0 の実例は無く、合成データのみ。
  - pmd の `enabled` は visible と同じにした（PMXEditor の変換結果とは 先 骨で違いうる。推測）。
  - 探査に使った使い捨てのスクリプト（probe_pmd.py / probe_pmx.py）と出力は worktree から消した（リポジトリには入れていない）。
