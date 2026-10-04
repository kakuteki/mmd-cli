# mmd-cli コードレビュー 3: batch B（`mmd model info`、pmx / pmd の読み取り）(2026-10-04)

対象: ブランチ `worktree-agent-a7769b4f14a7f6723` の 5 コミット（起点 main の da80c0c、先頭 8c0fb6b）。
2f5839c（pmx）→ db0f3d0（pmd）→ 4e6f590（model info / file info）→ b05c6a8（README・counts の順）→ 8c0fb6b（記録）。
差分は `git diff da80c0c worktree-agent-a7769b4f14a7f6723`（9 ファイル、+1627 / -6）を通読した。
worktree `.claude/worktrees/agent-a7769b4f14a7f6723` はブランチ先頭と一致（`git status` は空）。読み取りのみ。コードは変更していない。
main は査読中 5cc9bcc（da80c0c から 6 コミット進んでいる。取り込みの試算は 10 節）。

読んだ版の指紋（blob の先頭 8 桁、`git ls-tree`）:

| ファイル | blob |
| --- | --- |
| mmd_cli/formats/pmx.py | 32252014 |
| mmd_cli/formats/pmd.py | 5b35c56c |
| mmd_cli/app.py | f7316c99 |
| mmd_cli/cli.py | f3a744e3 |
| tests/test_pmx.py | 8139f770 |
| tests/test_pmd.py | 06e566ab |
| tests/test_cli.py | 5bd41761 |
| README.md | f36bc0f2 |
| docs/reviews/2026-10-04-batch-b-model-info.md | 381f6d59 |

方法: 差分を通読し、確かめられる点は MMD を起動しない小さなスクリプトで実測した。**MMD は起動していない。schtasks は実行していない。**

- 実機モデル: `C:/Users/kaga/Desktop/MikuMikuDance_v932x64/UserFile/Model/` 以下の **pmd 13 本・pmx 11 本（計 24 本）** 全部。
- 独立の照合: 仕様（PMXEditor の PMX仕様.txt 2.0 / 2.1、PMD の非公式仕様）から**自前で書き直した読み取り器**
  （`exp_models.py` の `walk_pmd` / `walk_pmx`。本体のコードは使わない）で同じ 24 本を歩き、骨名の列・表情名の列・表示枠数・
  剛体数・ジョイント数・残りバイトを本体の結果と突き合わせた。本体の `plausible` や `_Reader` は通っていないので、
  「試験と実装が同じ誤りを持つ」種類の見落としはここで出る。
- 合成データ: tests の `Writer` / `build()` を借りて端の場合を作った（`exp_bounds.py`、B1〜B12）。
- Python 3.9: `ast.parse(feature_version=(3, 9))`、3.10+ の API の文字列検索、識別子の非 ASCII 検査（`exp_py39.py`）。
- 単体試験: worktree で `python -m unittest discover -s tests -t .` → **267 本 OK、skip 1**（tests/live）。記録の主張と一致。
  main 5cc9bcc との `git merge-tree` の結果（衝突なし）を scratchpad に展開して同じ試験 → 272 本 OK、skip 1。

書式: 各指摘は「場所／何が起きるか／根拠／直し方／重要度（高・中・低）」。推測は推測と書く。行番号はブランチ先頭 8c0fb6b のもの。

## 1. `mmd_cli/formats/pmx.py`

### 1.0 仕様との突き合わせ（見たが問題なし）

| 節 | 本体の長さの取り方 | 判定 |
| --- | --- | --- |
| ヘッダ | "PMX "（大文字小文字を無視。"Pmx " も通る、実測）、float 版を 2 桁に丸める（float32 の 2.1 = 2.0999999 → 2.1、実測）、globals 数 n（< 8 は拒否、> 8 は余りを無視、実測）、encoding 0/1、追加 UV 0〜4、index size 6 つ（1/2/4 以外は拒否） | 一致 |
| 頂点 | 32 + 16 × UV、種別 0 BDEF1 = b、1 BDEF2 = 2b + 4、2 BDEF4 = 4b + 16、3 SDEF = 2b + 40、4 QDEF = 4b + 16、縁 4。実機 11 本に出るのは 0〜3 だけ（QDEF は合成のみ） | 一致 |
| 面 | 件数 × 頂点 index size を飛ばす（符号は読まないので無関係）、3 の倍数検査 | 一致 |
| テクスチャ | 件数 + 文字列 | 一致 |
| 材質 | 文字列 2 + 65（拡散 16・鏡面 12・鏡面係数 4・環境 12・描画旗 1・縁色 16・縁幅 4）+ テクスチャ index 2 本 + スフィアモード 1 + 共有トゥーン旗 1 + （旗 1 なら 1 バイト／0 ならテクスチャ index）+ メモ + 面数 4。共有トゥーンは実機では Tda 式の 5/26 材質だけで、両経路とも実機で通っている | 一致 |
| 骨 | 文字列 2 + 位置 12 + 親 index + 階層 4 + 旗 2 + 接続先（0x0001 なら index、でなければ 12）+ 付与（0x0100 \| 0x0200: index + 4）+ 軸固定（0x0400: 12）+ ローカル軸（0x0800: 24）+ 外部親（0x2000: 4）+ IK（0x0020: index + 4 + 4 + 件数 + リンク（index + 1 + （1 なら 24））） | 順序・長さとも一致 |
| 表情 | 文字列 2 + 枠 1 + 種類 1 + 件数 + オフセット: group / flip = morph index + 4、vertex = vertex index + 12、bone = bone index + 28、uv・uv1〜4 = vertex index + 16、material = material index + 113（1 + 16 + 12 + 4 + 12 + 16 + 4 + 16 + 16 + 16）、impulse = rigid index + 25 | 一致 |
| 表示枠 | 文字列 2 + 特殊 1 + 件数 + 項目（種別 1 + bone index か morph index） | 一致（種別の検査は 1.6） |
| 剛体 | 文字列 2 + bone index + 61（群 1・非衝突 2・形状 1・寸法 12・位置 12・回転 12・質量〜摩擦 20・種別 1） | 一致 |
| ジョイント | 文字列 2 + 種別 1 + rigid index 2 本 + 96 | 一致 |
| ソフトボディ（2.1） | 文字列 2 + 形状 1 + material index + 124 + アンカー（件数 + (rigid + vertex + 1) × n）+ ピン（件数 + vertex × n） | 一致（合成のみ。実機に 2.1 は無い） |
| index の符号 | 頂点以外は `<b` `<h` `<i`（符号つき）。頂点 index は飛ばすだけ | 一致 |
| 文字列 | 長さが負・残りを超えると位置つきエラー。decode は replace: UTF-16 の奇数長（5 バイト）→ "ab\ufffd"、UTF-8 の孤立継続バイト → "a\ufffdc"（実測）。長さ == 残りバイトは通る | 問題なし |
| 件数欄 | `plausible` が読む前に `n × 最小長 > 残り` で拒否。頂点・面・テクスチャ・材質・表情・表示枠・剛体・ジョイント・ソフトボディ・アンカー・ピン・IK リンク・表情オフセット・枠項目の最小長は真の下限（骨だけ例外、1.1）。0x7FFFFFFF と負数を、頂点数・文字列長（試験）、ソフトボディのアンカー数・IK リンク数・表情オフセット数（実測 B8）で即時の位置つき例外を確認。`range` も `bytes` の確保も起きない | 問題なし |
| 読み切り | 実機 24 本すべて残り 0 バイト、末尾に 1 バイト足すと 24 本とも「1 bytes are left」。独立の読み取り器も 24 本で残り 0、骨名の列・表情名の列・枠数・剛体数・ジョイント数が本体と一致。参照 index（親・付与親・IK target / links・枠項目）は 24 本で全部表の範囲内、名前の U+FFFD は 0 文字 | 問題なし |

実機 11 本（全部 2.0、UTF-16LE、追加 UV 0、index size は 頂点 2・テクスチャ 1・材質 1・骨 2・表情 1 か 2・剛体 1 か 2）に
現れない配置は、骨 index 1 / 4 バイト、追加 UV、QDEF、flip / impulse、ソフトボディ、UTF-8。これらは仕様から手で計算した長さと
本体・`Writer` の長さが一致することを確かめた（上の表）。

### 1.1 骨の件数の下限が「接続先は 12 バイト」を仮定している（低）

場所: pmx.py:323 `r.count(8 + 12 + sizes["bone"] + 6 + 12, "bone")`。

何が起きるか: 接続先を骨 index で持つ骨（旗 0x0001。実機では大半）は 12 ではなく index size（1〜4）バイトなので、
`plausible` に渡す「最小長」が真の下限より 8〜11 バイト大きい。骨の後ろが短いファイルでは、入り切るのに
「implausible bone count」で拒否される。

根拠（実測 B1）: 骨 index 1 バイト、1 文字の名前、接続先が骨、の骨 3 本だけの pmx（骨 1 本 30 バイト、後続は件数欄 16 バイト、
残り 106 バイト）→ 検査は 3 × 39 = 117 を要求して拒否。同じ骨に 12 バイトの接続先を持たせると通る。名前が 2 文字以上あるか
表情が 1 つでもあれば通るので、実機では起きない（24 本は全部通った）。

直し方: 最小長を `8 + 12 + size + 6 + min(size, 12)`（= 26 + 2 × size）にする。

重要度: 低（実害は合成データだけ。ただし「入り切らないときだけ拒否する」という不変条件が崩れている）。

### 1.2 付与親と IK の target / links の -1 が None にならない（docstring と食い違う）（低）

場所: pmx.py:242、251、253（`r.index(size)` のまま）。`_optional` は親（232）にだけ使われている。モジュール docstring 6〜7 行
「the "none" index -1 becomes None」。

何が起きるか: 付与旗が立っているのに付与親が -1 の骨（PMXEditor で作れる）は `append.parent = -1`、IK target -1 も -1 のまま
出る。`parent` だけ None。利用者が `bones[append["parent"]]` と引くと Python では末尾の骨を黙って指す。

根拠: 実測 B2（合成）。実機 11 本には -1 の付与親も target も無い。pmd 側も種別 9 の tail が 0xFFFF だと `append.parent = -1`（B9）。

直し方: `_optional()` を通す（pmd の `_bone` も同じ）。docstring を直す方向でもよいが、JSON の読み手には None の方が安全。

重要度: 低。

### 1.3 ソフトボディは歩くが数えない（低）

場所: pmx.py:329-330（`_skip_soft_bodies` の戻り値を捨てる）。docstring 5〜6 行「rigid bodies, joints and soft bodies ... are only counted」。

何が起きるか: 2.1 のソフトボディ節は正しく飛ばすが `counts` に `soft_bodies` が無い（実測 B4）。

直し方: `counts["soft_bodies"] = _skip_soft_bodies(...)`（2.0 と節の無い 2.1 では 0）。README の counts の例にも足す。

重要度: 低（手元に 2.1 の実ファイルが無い）。

### 1.4 2.0 と 2.1 で末尾の扱いが非対称（低・情報）

場所: pmx.py:329-333。

2.0 のファイルに 4 バイトのゼロ（ソフトボディ件数 0 を書く書き出し器があった場合）が付いていると「4 bytes are left」で拒否、
2.1 では件数欄が丸ごと無くても通す（実測 B3）。前者は厳格、後者は寛容で、方針が揃っていない。手元の 11 本は全部 2.0 で
ぴったり終わるので実害は見ていない（推測: 2.0 を名乗りつつソフトボディ節を書く書き出し器があるかは未確認）。
寛容に寄せるなら「版に関係なく、残りが 4 バイト以上ならソフトボディ節として読む」、厳格に寄せるなら 2.1 でも件数欄を要求する。

重要度: 低。

### 1.5 旗 0x0080（ローカル付与）を出していない（低）

場所: pmx.py:20-22 `FLAG_BITS`。

PMX 2.0 の骨旗には 0x0080（付与対象を親のローカル変形量にする）もある。任意欄を伴わないので配置には関係せず読み取りは正しいが、
`flags` に出ない。実機 11 本では 0 本。足すなら `("append_local", 0x0080)` の 1 項目と試験の名前の列。

重要度: 低。

### 1.6 表示枠の項目種別が 0 / 1 以外でも「morph」になる（低）

場所: pmx.py:276 `if r.u8():`。

仕様は 0 = 骨、1 = 表情。2 以上は壊れたファイルだが、morph index の長さで読み進めるので、morph と bone の index size が違う
ファイル（実機では 1 と 2 の組がある）はそこから配置がずれ、読み切り検査で止まるか別の文言になる。種別が 0 / 1 以外なら
位置つきのエラーにした方が原因が分かる（実測 B7: 種別 2 は morph として読まれた）。

重要度: 低。

## 2. `mmd_cli/formats/pmd.py`

### 2.0 仕様との突き合わせ（見たが問題なし）

- 長さ: ヘッダ 283（"Pmd" 3 + 版 4 + 名前 20 + コメント 256）、頂点 38、面 u16、材質 70（テクスチャ名は +50 から 20 バイト、`*` で分割）、
  骨 39（`<20shhBH3f`: 名前・親 i16・接続先 i16・種別 u8・IK 親 u16・位置 3f）、IK 11（`<HHBHf`: IK 骨・target・連鎖長・反復・角度）+ 連鎖 u16 × n、
  表情 25 + 16 × n、表情枠 u8 + u16 × n、骨枠名 u8 + 50 × n、骨枠所属 u32 + (u16 + u8) × n、英語ブロック（旗 u8、名前 20・コメント 256・
  骨 20 × n・表情 20 × max(n − 1, 0)・枠 50 × n）、トゥーン 100 × 10、剛体 83、ジョイント 124。全部仕様どおり。
- 独立の読み取り器で 13 本の骨名の列・表情数・剛体数・ジョイント数・残り 0 バイトが一致。末尾 +1 バイトは 13 本とも拒否。
- 骨種別 → 旗（docstring の表）: 13 本・1,453 本の骨を種別ごとに数えた。骨枠に属する骨の種別は 0 / 1 / 2 / 4 / 5 / 8 だけで、
  6 / 7 / 9 は 0 本。種別 3 は実例なし。

  | 種別 | 骨数 | うち骨枠に属する | 本体の visible |
  | --- | --- | --- | --- |
  | 0 回転 | 660 | 656 | True |
  | 1 回転と移動 | 52 | 39 | True |
  | 2 IK | 62 | 62 | True |
  | 4 IK影響下 | 131 | 131 | True |
  | 5 回転影響下 | 32 | 32 | True |
  | 6 IK接続先 | 38 | 0 | False |
  | 7 非表示 | 454 | 0 | False |
  | 8 捻り | 12 | 12 | True |
  | 9 回転運動 | 12 | 0 | False |

  枠に属さないのに visible な骨は、センター（13 本中 12 本。ダミーボーンは ﾎﾞｰﾝ01）と、鏡音リン_act2.pmd の
  左目光・右目光・左目光先・右目光先（種別 0）だけ（B11）。「センター は独立に出す」という docstring の説明と合う。
- 種別 9 の欄の意味（記録の主張）: 初音ミクVer2.pmd の 左腕捩1 / 2 / 3 は tail = 19（左腕捩）、ik_parent = 25 / 50 / 75
  （骨番号と読むと 左親指２・右腕・両目 で意味をなさない）。右腕捩1〜3 も同じ形（tail = 51 右腕捩）。種別 5 の 左目・右目は
  ik_parent = 75（両目）、tail は 左目先・右目先。種別 8 の 左腕捩 は tail = 左腕捩先、ik_parent = 0。種別 4 の ik_parent は
  所属する IK 骨（ﾈｸﾀｲ1〜3 → ﾈｸﾀｲＩＫ、左足・左ひざ・左足首 → 左足ＩＫ）。本体の出力は 左腕捩1 → `{"parent": 19, "ratio": 0.25}`、
  左目 → `{"parent": 75, "ratio": 1.0}`。主張どおり。
- IK の角度は生値のまま: 足 0.5（loops 40）、つま先 1.0（loops 3。巡音ルカだけ 0.5・loops 10）、髪・ネクタイ・ポニテ・マフラー 0.03（loops 8 か 15）。
- 表情番号: pmm fixture（MMD が保存。モデルのパスは `C:\MMD\UserFile\Model\初音ミク.pmd`、絶対パス）の表情一覧は
  `["base", ...]` 16 件で、pmd の skin 番号そのもの。base を外した `morphs` の `index` が MMD の番号と一致する
  （`test_mmd_numbers_bones_and_morphs_the_same_way` が守る）。13 本とも base は skin 0、表情枠の値は 1〜n − 1 の範囲、
  骨枠所属の枠番号は 1〜枠数の範囲。
- 骨枠名の末尾改行: 12 本は "ＩＫ\n" 形式、ダミーボーンは改行なし。`rstrip("\r\n")` で正しい。
- 文字列: cp932、NUL で切る、壊れたバイトは置換（試験は 0x81 の孤立先行バイト。0xFF は Python の cp932 が U+F8F3 に写すという
  試験の注記も正しい）。
- 後置節: カイト.pmd と ダミーボーン.pmd はトゥーンで終わる（剛体・ジョイント 0）。英語旗 0 の実例は無い（合成のみ）。
  英語旗が 1 で直後に終わる、トゥーンが 500 バイトで切れる、はどちらも位置つきのエラー（実測 B9）。
- 件数欄: u8 / u16 / u32 とも `plausible` で先に拒否（頂点 3 で 50 バイトしか無い → 「implausible vertex count 3 at offset 283」、実測）。
  IK の重複は先勝ち。版 1.0 は float32 でも厳密に 1.0。
- counts のキー順は pmx と同じ（試験が守る）。

### 2.1 base が先頭にないと英語の表情名が 1 つずれる（低・合成のみ）

場所: pmd.py:174-175 `english["skins"][i - 1] if english and i >= 1`。

何が起きるか: 英語ブロックの表情名は「base 以外を順に」n − 1 件なので、base が skin 0 以外にあるファイルでは対応がずれる
（実測 B9: skins = [a, base, b] に英語 [A, Bee] → a は None、b は Bee）。MMD 自身も base = skin 0 を前提にしている
（pmm の表情一覧の 0 番が base）ので実ファイルでは起きないはずで、13 本とも base は 0 だった。

直し方: `kind != 0` の表情を数えながら英語名を順に割り当てる。

重要度: 低。

### 2.2 表情枠が skin 0 を指すと `morphs` に無い index の項目になる（低・合成のみ）

場所: pmd.py:176。`skin_display` の値をそのまま morph 項目にするので、0（base）が入っていると `display_frames[0].items` に
index 0 が出るが `morphs` に 0 は無い（B9）。実機 13 本では 0 は現れない。弾くなら `if s != 0`。

重要度: 低。

### 2.3 骨枠所属の範囲外は黙って捨てる（低・情報）

場所: pmd.py:177-179。枠番号 0 や枠数超えの所属は無視される（B9）。実機では範囲内。壊れたファイルの診断として捨てた数を
出す手もあるが、必須ではない。

### 2.4 「14 本の pmd」は 13 本（低・記録）

場所: pmd.py:8 docstring「Measured on the 14 models shipped with MMD 9.32」、記録 `docs/reviews/2026-10-04-batch-b-model-info.md`
の「14 本の pmd」「全 14 本の pmd」。

実測（B12、再帰 glob。`find -iname` でも同じ）: Model フォルダ以下は pmd 13 本・pmx 11 本。結論は変わらないが数字を直す。

## 3. `Mmd.model_info`（app.py:690-724）と `cli.py`

### 3.1 MMD が無いときの `mmd model info FILE.pmx` は「MMD is not running」で止まり、`file info` を案内しない（中）

場所: cli.py:117-119（`model info` のヘルプ「... or a model file」）、cli.py:302 `STANDALONE = ("file", "ps", "launch")`、
cli.py:372-376（`model` は `_attach` を通る）、app.py:305-306（attach の文言）。

何が起きるか: ヘルプと README は「ファイルのパスを渡せばそのファイルを読む」と言うので、利用者は MMD を起動せずに
`mmd model info C:/models/x.pmx` と打つ。返るのは
`{"ok": false, "error": {"type": "MmdError", "message": "MMD is not running (start it with: mmd launch --exe PATH)"}}`（実測、`--no-relay`、終了コード 1）で、
ファイルを読むのに MMD の起動を促し、`mmd file info` には触れない。記録はこの制約を書いているが、利用者の目に入るのは
ヘルプとエラー文だけで、README は括弧の中に 1 行ある。

直し方（どれか）: (a) `run()` で `args.command == "model" and args.action == "info"` かつ target が存在する .pmx / .pmd なら
attach せずに `_file_info` と同じ経路で読む（`STANDALONE` の判定を関数にする）。(b) 少なくとも `model info` のヘルプと attach の
失敗文に「a model file without MMD: mmd file info FILE」を足す。(a) なら SSH 側でも中継せずその場で読める（`relay.should_relay`
の `LOCAL_COMMANDS` にも同じ判定が要る）。

重要度: 中（壊れないが、案内が誤っている）。

### 3.2 存在しないファイルパスを渡すと、プロジェクトを保存してから「no model named 'C:/nowhere/miku.pmx'」と言う（中）

場所: app.py:697-699（`os.path.isfile(target)` が偽だと名前の経路に落ちる）、702-704（`dump`）、715-717（名前の文言）。

何が起きるか: パスの打ち間違い、フォルダ、`.vmd` を渡した、のどれでも `self.dump(keys=False)` が走る。`dump` は
`_save_project()` でプロジェクトの作業コピーを **MMD に保存させる**（README の dump の説明どおりの副作用）ので、
打ち間違い 1 回で保存が 1 回起きる。その上で文言は「no model named 'C:/nowhere/miku.pmx' (loaded: x)」で、
ファイルが無いことを言わない。手で開いたプロジェクトでは `dump` が「this project (...) was not opened through mmd-cli;
reading it needs a save ...」を投げ、本体がそれに「Or read the model file itself: mmd model info FILE.pmx」を添える。
利用者はまさにそれをしたつもりなので、助言が循環する。

根拠: 実測 B10（偽の `dump` を差した `Mmd`）: 「C:/nowhere/miku.pmx」→ `dump` が 1 回呼ばれ、MmdError「no model named ...」。
フォルダ `dir.pmx`、既存の `m.vmd` も同じ経路。大文字の `.PMX`、相対パス（cwd 基準。中継は cwd を運ぶ: relay.py:276, 334-335）は正しく読める。

直し方: `target` が str で、パス区切りを含むか拡張子がモデルのものなら「ファイル」と決め、`os.path.isfile` が偽なら
`dump` を呼ばずに `FileNotFoundError(path)`（`check_input_file` と同じ形。`model load` は既にそうしている: app.py:142-148）。
拡張子がモデル以外なら「x must be one of .pmx, .pmd」。

重要度: 中（副作用が保存だけで、データは壊れない。文言の誤りが主）。

### 3.3 見たが問題なし

- 名前・番号・省略の解決: `dump` の `selected_model` は `scene.summarize` の番号（モデルが無ければ None）、`models[i]["path"]` は
  pmm が持つ絶対パス（fixture では `C:\MMD\UserFile\Model\初音ミク.pmd`。MMD は絶対パスを書く）。移動済みなら名前とパス入りの
  MmdError（試験あり）。pmm のパスが相対だった場合は cwd 基準になるが（B10）、MMD がそう書くことは無い。
- `parse_target`: "2" → 2、名前は str、パスは str、省略と "camera" は None（= 選択中。`model info camera` が選択中のモデルを
  返すのは意図とずれるが害は無い。低）。bool は int として扱われ範囲検査に掛かる。
- `dump(keys=False)` でキーを読まない。`in_place` は `dump` が自分で面倒を見る。`require_ready` は `dump` 側で呼ばれるので、
  再生中は従来どおり拒否される。ファイルの経路では MMD に触らない（試験 `test_a_file_path_is_read_without_touching_the_project`）。
- cp932 の検査（`_require_ansi`）はこの経路に要らない: ファイルを読むのは Python だけで、MMD にパスを渡さない。
- `_file_info` の `--brief` はモデル以外では黙って無視される（ヘルプが「for models」と断っている。低・情報）。
- 出力の形: `{"ok": true, "path": ..., "format": ..., "version": ..., "name": ..., ..., "counts": ..., "bones": ..., "morphs": ...,
  "display_frames": ...}`。`file info` は `path` なし。実測の `file info Tda式重音テトAP.pmx --brief` は ASCII の 1 行 JSON。
  無いファイルは `FileNotFoundError` の JSON、終了コード 1（main 5cc9bcc 以降は `ValueError` が 2 になったが、`FileNotFoundError` は 1 のまま）。
- `_dispatch` の `info` 分岐は `target = parse_target(...)` の前にあるが、同じ関数を呼ぶので差は無い。

## 4. 試験

### 4.1 合成データの書き手は本物の配置と同じか

`tests/test_pmx.py` の `Writer` と `tests/test_pmd.py` の `build()` / `bone()` / `skin()` を、本体ではなく仕様に対して読んだ。
材質のテクスチャ index の大きさ（`self.index(..., "texture")`）、骨の任意欄の順序（接続先 → 付与 → 軸固定 → ローカル軸 → 外部親 → IK）、
IK リンクの角度制限（1 バイト + 24）、表情のオフセット長、ソフトボディの 124 バイト、pmd の 39 / 11 / 25 / 83 / 124 は
いずれも仕様と一致する（1.0、2.0 の表）。`Writer` と本体は同じ著者の同じ理解から書かれているので、両方が同じ誤りを持つ危険は
あったが、独立の読み取り器が実機 24 本で本体と一致し、実機に無い配置（QDEF、flip / impulse、ソフトボディ、index size 1 / 4、
追加 UV）は上の手計算で確かめた。

### 4.2 実機モデルの試験が skip されるとき

`SourRinTest` / `TdaTetoTest` / `MikuTest` / `MeikoTest` / `ShortFilesTest` は `skipUnless(os.path.isfile(...))`。この PC では全部
走っている（skip は tests/live の 1 本だけ。実測）。フォルダが移れば 5 クラス（+ pmm fixture の 1 本）が黙って skip になり、
unittest の末尾の「OK (skipped=N)」の N が 1 から 7 に増えるだけで、失敗にはならない。合成データの試験だけでも配置は守られるので
重大ではないが、実機の件数（373 / 133 / 14 など）は実機でしか守れない。環境変数（例 `MMD_CLI_MODEL_DIR`）でフォルダを指定でき、
指定されているのに無ければ失敗、未指定なら skip、にすると「静かに通る」を防げる。重要度: 低。

### 4.3 その他（低）

- `ModelFiles.setUp` の `tempfile.mkdtemp()` は後始末が無い（毎回 7 フォルダ残る）。同じファイルの既存の試験（139、152、160 行）も
  同じ流儀なので新しい問題ではない。`addCleanup(shutil.rmtree, ...)` で揃えられる。
- `ModelInfoTest.bare()` は `Mmd.__new__` で初期化を飛ばす（査読 2 の 8.2 と同じ形）。`_parking` を自分で足しているので今は通る。
- `test_truncated_in_the_middle_of_a_bone_names_the_offset` は "offset" の有無しか見ない。位置の値（例: 切った位置以下）まで見ると
  文言の退行を捕まえられる。
- 試験されていない分岐: 1.1（骨の下限）、1.2（-1）、1.3（soft_bodies）、1.6（枠項目の種別）、2.1 / 2.2（base の位置、枠の 0）、
  3.2（無いパス）、`panel_name` の "unknown N"（枠 5 以上）、`_header` の globals 数 > 8。
- `tests/test_cli.py` が `tests.test_pmd` / `tests.test_pmx` から書き手を import する。`tests/__init__.py` があるので discover でも
  `python -m unittest tests.test_cli` でも通るが、書き手を `tests/pmx_writer.py` のような補助モジュールに出した方が依存の向きが素直。

## 5. Python 3.9 と識別子

触った 7 ファイル（pmx.py、pmd.py、app.py、cli.py、test_pmx.py、test_pmd.py、test_cli.py）を `ast.parse(feature_version=(3, 9))` で
解析: 全部通る。`removeprefix` / `removesuffix` / `zip(strict=)` / `bit_count` / match 文 / 注釈の `X | Y` / `kw_only` / `slots` の
文字列検索: 0 件。`typing.Dict / List / Optional` を使っている。識別子（名前・引数・属性）に非 ASCII は無い
（"表情" はリテラルだけ）。この PC には 3.9 の実行系が無いので実行はしていない（`py -0` は 3.12 のみ）。

## 6. README と実装

| README の記述 | 実装 | 判定 |
| --- | --- | --- |
| 「ファイルのパスを渡せばそのファイルを読む（MMD が動いていなくてよいのは `mmd file info ファイル`）」 | そのとおり。ただし `model info` のヘルプと attach の失敗文はそれを言わない | 3.1 |
| 「`mmd model info` は ... ファイルを `dump` の結果から探して読む」 | そのとおり（`dump` の保存の副作用も README の dump の説明どおり） | 一致 |
| JSON の例（センター・左目・左足ＩＫ・まばたき・あ・表情枠・ＩＫ枠の値） | 初音ミク.pmd の実出力と一致（左目 index 4 / parent 3 / append 71、左足ＩＫ 83 / target 40 / links [39, 38]、まばたき 5 / 147、あ 9 / 88、表情枠 [9, 10]、ＩＫ枠 [80, 81]、name_en eye_L / leg IK_L、旗の並び） | 一致。`path` だけ `C:\tools\...` に書き換えてある（例としては差し支えない） |
| 「`special` は Root と 表情」 | pmx はそのとおり（実機 11 本の特殊枠は Root と 表情）。pmd には Root を作らないので 表情 だけ | 低（pmd の但し書きがあるとよい） |
| 「IK の `angle` は pmx がラジアン、pmd はファイルの値のまま（pmx の 1/4）」 | 実測: pmd 0.5 / 1.0 / 0.03、pmx 2.0（足）。変換していない | 一致 |
| 「`kind` ... pmd は常に `vertex`」「`panel` は eyebrow / eye / mouth / other」 | `MORPH_KINDS`、`PANELS`（0 は "system"、5 以上は "unknown N"。README に無いが実機では出ない） | 一致 |
| 「0 番の base は一覧に出さない」 | そのとおり。`dump` の `morph_count`（16）と `counts["morphs"]`（15）が 1 違うことは記録にあるが README には無い | 低 |
| counts の例の 9 項目 | 実装の 9 項目と同じ。2.1 の soft_bodies は無い | 1.3 |
| コマンド表 `info [名前\|番号\|F]`、`file info F [--brief]` | parser と一致 | 一致 |

## 7. 記録（docs/reviews/2026-10-04-batch-b-model-info.md）の主張の検証

| 主張 | 結果 |
| --- | --- |
| 単体 267 本 OK、skip 1 | 確認（worktree で再実行。skip は tests/live） |
| 初音ミク 122 / 15 / 8、MEIKO 99 / 42 / 8、カイト 106 / 24 / 8（剛体・ジョイント無し）、ダミーボーン 30 / 0 / 2、White.pmx 373 / 133 / 14、Tda 150 / 56 / 11 | 確認（1 節の表の元データ） |
| 「14 本の pmd・11 本の pmx」で読み切り | pmd は **13 本**。読み切りは 24 本すべて確認、独立の読み取り器も一致 |
| White.pmx のウェイト 16553 / 9533 / 12279 / 2511、panel 0 の表情 23 | 確認（独立の読み取り器で同じ数） |
| 骨枠に属する種別は 0 / 1 / 2 / 4 / 5 / 8 だけ | 確認（13 本・1,453 本の骨で 6 / 7 / 9 は 0 本） |
| 種別 9 は tail が回転元・ik_parent が百分率、種別 5 は ik_parent が回転元 | 確認（初音ミクVer2.pmd の生の欄） |
| 「-1 は None」 | 親だけ。付与親・IK target / links は -1 のまま（1.2） |
| 「ソフトボディも最後まで歩いて」「only counted」 | 歩くが `counts` に無い（1.3） |
| pmm の表情一覧は base + 15 で skin 番号と同じ | 確認（fixture を読んだ） |
| 英語ブロックの表情名は max(n − 1, 0) 件 | 確認（ダミーボーン.pmd が読み切れる） |
| `model info ファイル` は MMD 無しでは attach で失敗 | 確認。文言に `file info` の案内は無い（3.1） |
| Python 3.9 の構文 | 確認（5 節） |
| `file info` が 0.26 秒 | 測っていない（重要でない） |

## 8. 見たが問題なしの領域（まとめ）

- pmx の全節の長さと順序、index の符号、文字列の端、件数欄の即時拒否、読み切り（1.0 の表）。実機 11 本と独立の読み取り器の一致。
- pmd の全節の長さ、骨種別の写し方（1,453 本の骨の集計）、種別 9 / 5 の欄、表情番号と pmm の一致、後置節の有無、cp932 の扱い（2.0）。
- `Mmd.model_info` の名前・番号・省略の解決、移動済みファイル、`keys=False`、ファイル経路では MMD に触らない（3.3）。
- 中継: cwd を運ぶので相対パスが通る（relay.py:276、334-335）。`file info` は従来どおりローカル。
- 3.9 の構文、識別子（5 節）。README の例の値（6 節）。counts のキー順。
- main 5cc9bcc への取り込み: `git merge-tree` は衝突なし。その木で 272 本 OK、skip 1。

## 9. 追加すべき試験

「現状で失敗するはず」のものはそう印を付けた。

### tests/test_pmx.py
- `test_bone_count_lower_bound_allows_tails_that_are_bone_indices`（**現状で失敗するはず**）: 骨 index 1 バイト・1 文字の名前・接続先が骨、の骨 3 本だけの pmx が読める（1.1）。
- `test_minus_one_append_parent_and_ik_target_become_none`（1.2 を採るなら **現状で失敗するはず**）: 付与親 -1、IK target -1、リンク -1 が None。
- `test_soft_bodies_are_counted`（1.3 を採るなら **現状で失敗するはず**）: 2.1 で `counts["soft_bodies"] == 2`、2.0 で 0。
- `test_frame_item_kind_other_than_bone_or_morph_is_an_error`（1.6 を採るなら）: 種別 2 で位置つきの PmxFormatError。
- `test_append_local_flag_is_named`（1.5 を採るなら）: 0x0080 が `flags["append_local"]`。
- `test_header_with_more_than_eight_globals_is_read`: globals 9 で通る（今は実測のみ）。
- `test_unknown_panel_is_named_with_its_number`: 枠 5 → "unknown 5"。

### tests/test_pmd.py
- `test_english_skin_names_follow_the_non_base_skins`（2.1 を採るなら **現状で失敗するはず**）: skins = [a, base, b] に英語 [A, Bee] → a = A、b = Bee。
- `test_skin_display_entries_for_the_base_are_dropped`（2.2 を採るなら）。
- `test_a_type_9_tail_of_minus_one_is_none`（1.2 と同じ修正）。

### tests/test_cli.py
- `test_model_info_with_a_missing_file_path_does_not_touch_the_project`（**現状で失敗するはず**）: `dump` が呼ばれず、例外文に
  パスが入り「no model named」でない（3.2）。フォルダと `.vmd` も同じ。
- `test_model_info_file_without_mmd_says_file_info`（3.1 を (b) で採るなら **現状で失敗するはず**）: `_attach` を MmdError に差し替えて
  `run(parse(["model", "info", pmx]))` → 文言に "mmd file info"。(a) なら `_attach` が呼ばれずに結果が返ることを見る。
- `test_file_info_through_main_is_ascii`: `cli.main(["--no-relay", "file", "info", pmx, "--brief"])` の標準出力が ASCII で `"ok": true`。

### 実機モデル
- `MMD_CLI_MODEL_DIR` が指定されているのにファイルが無ければ失敗にする 1 本（4.2）。
- pmd と pmx を同じ骨格で比べる 1 本（例: 初音ミク.pmd の 左足ＩＫ 0.5 と Sour 式の 2.0 の比 4、`左目` の付与親がどちらも `両目`）。
  記録が根拠にした関係を試験に固定する。

## 10. 要約

### 重要度 高
- なし。

### 重要度 中
- 3.1 MMD が無いときの `mmd model info FILE.pmx` は「MMD is not running (start it with: mmd launch --exe PATH)」で止まり、
  ヘルプが約束した「モデルファイル」を MMD なしでは読めないことも `file info` の存在も言わない。attach を飛ばすか、文言に足す。
- 3.2 存在しないパス・フォルダ・`.vmd` を `model info` に渡すと、`dump`（プロジェクトの保存）が走った上で
  「no model named 'C:/nowhere/miku.pmx'」。手で開いたプロジェクトでは「Or read the model file itself」と循環する。
  `isfile` が偽なら `dump` の前に `FileNotFoundError`。

### 重要度 低
- 1.1 骨の件数の下限が 12 バイトの接続先を仮定（合成データで誤拒否）。1.2 付与親・IK の -1 が None にならない（docstring と不一致）。
  1.3 ソフトボディを数えない。1.4 2.0 / 2.1 の末尾の扱いが非対称。1.5 旗 0x0080 を出さない。1.6 枠項目の種別 2 以上を morph 扱い。
- 2.1 base が先頭にないと英語の表情名がずれる。2.2 表情枠の 0。2.3 範囲外の所属を黙って捨てる。2.4 「14 本」は 13 本。
- 4.2 実機モデルの試験は無ければ黙って skip。4.3 mkdtemp の後始末、未試験の分岐。

### 実測したこと（MMD は起動していない。schtasks も実行していない）
1. 単体試験: worktree で 267 本 OK、skip 1。main 5cc9bcc との `merge-tree`（衝突なし）を展開した木で 272 本 OK、skip 1。
2. 実機 24 本（pmd 13・pmx 11）: 本体で読み切り（残り 0、+1 バイトで全部エラー）、参照 index が全部範囲内、U+FFFD 0 文字。
   仕様から独立に書いた読み取り器（`exp_models.py`）で同じ 24 本を歩き、骨名・表情名の列、枠数、剛体数、ジョイント数、残りバイトが一致。
3. pmd の骨種別の集計（1,453 本）、初音ミクVer2.pmd の種別 9 / 5 / 8 の生の欄、IK の角度、表情枠・骨枠所属の値域、base の位置、
   pmm fixture のモデルのパスと表情一覧。
4. 合成データ（`exp_bounds.py` B1〜B12）: 骨の下限の誤拒否、-1 の扱い、2.0 + 4 バイト、soft_bodies の有無、文字列の端、ヘッダの端、
   枠項目の種別 2、深い場所の巨大な件数、pmd の端（base の位置、枠の 0、英語旗、トゥーン切れ、IK 重複）、`model_info` の
   無いパス・フォルダ・`.vmd`・大文字拡張子・相対パス・camera・bool・相対な pmm パス。
5. CLI（`--no-relay`）: `model info FILE` の失敗文、`file info --brief` の出力、無いファイルの文言、`model info --help`。
6. README の例の値を 初音ミク.pmd の実出力と照合。
7. Python 3.9: `ast` と API の文字列検索、識別子の文字種（`exp_py39.py`）。

スクリプトは `C:/Users/kaga/AppData/Local/Temp/claude/C--Users-kaga/d507b1f9-47a1-437a-81cf-30b68431c4c5/scratchpad/`
（`exp_models.py`、`exp_bounds.py`、`exp_py39.py`、`exp_readme.py`。セッション限りの場所。残すなら `tools/` へ写す）。

### 取り込みの判断

**取り込んでよい。** 読み取りの配置は仕様・実機 24 本・独立の読み取り器の三方で一致し、高はなく、中の 2 件は案内と文言の
問題で、データを壊す経路は無い。条件:

1. main 5cc9bcc への merge は衝突なし（`merge-tree` で確認）。merge 後に `python -m unittest discover -s tests -t .` を
   走らせて 272 本 OK を見る（展開した木では確認済み。実際の merge 結果でもう一度）。
2. main の作業ツリーには **未コミットの `tests/live/test_live.py` の変更**（この査読のものではない）がある。merge の前に
   退避するか commit する。
3. 3.1 と 3.2 は merge 後の小さな直し（`run()` の判定 1 つと `model_info` の冒頭 3 行）で足りる。同じ機会に 1.1〜1.3 と
   2.4 の数字を直すと記録と実装が揃う。
