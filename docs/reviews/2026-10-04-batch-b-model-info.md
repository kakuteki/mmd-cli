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
