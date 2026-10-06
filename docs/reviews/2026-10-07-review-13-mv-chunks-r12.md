# 査読 13: 査読 12 への直し（枝 mv-chunks-r12）の再査読

- 日付: 2026-10-07
- 対象: 枝 mv-chunks-r12 の b1af4a9（e4fb672 の上に 5ea6000・851d103・b1af4a9）。
  - `tools/mv_chunks.py`: `__pycache__` を印から外す・`Invoke-Native` の残りの引数・`Why`・偶数の大きさ
  - `tests/test_mv_chunks.py`: 4 本と subTest 6 つ
  - `tests/test_mv_look.py`: 許容を 1.5 から 2.0 へ
  - README・説明文・査読 11 と 12 の記録
- main は査読の途中で 4e25470 へ進んだ（HANDOVER.md だけ）。枝とファイルが重ならないので、マージで衝突は無い。ただし早送りにはならない。
- やり方:
  - 自分用の worktree（`scratchpad/review13`、b1af4a9 の detached）で読んだ。変異はその中で 1 つずつ当てて戻し、終わりに `git worktree remove --force` で消した（消す前の `git status` は空）。
  - 枝と main には書いていない。
  - 実行環境: PowerShell 5.1.26100.9444（ja-JP）を `powershell -NoProfile -NonInteractive -File` で直接。Python 3.12.10。
  - 試験は `tests.test_mv_chunks`（70 本）・`tests.test_mv_look`（49 本）と自作の場合を、1 つずつ流した。全体の試験は流していない。
  - MMD は起動していない。hinata には触れていない。
  - 台本と出力は `scratchpad/r13/`。台本は消した worktree の場所を読むので、流し直すには同じ場所へ worktree を作り直す。

## 結論

- **マージは可。** 成果物を黙って間違える現実の経路は見つからなかった。
  - 依頼の 1（`Invoke-Native` の新しい形）は、本物の python.exe で確かめた。問題は無い。
  - `__pycache__` の除外は、本物の python で効く。初回に全部描いた直後の `-Resume` が、3 区間とも飛ばした。
- **ただし指摘 1 は今回の直しで入った退行で、1 行で直る。マージの前に直すのが安い。**
  - python のパスに ‘ ’ ‚ ‛ のどれかがあると、駆動台本が構文エラーになり、1 行も走らない。main では走る。
  - 本番の計画は python が "python" なので当たらない。v2 は main の e4fb672 で描かれている。
- 査読 12 の 4（look の確かめの文言）は、一部だけ直った（指摘 2）。

## 重さごとの件数

高 0 / 中 0 / 低 4 / 情報 2

## 指摘

### 1. 低（退行）: python のパスに ‘ ’ ‚ ‛ があると、駆動台本が構文エラーで 1 行も走らない

- 場所: `tools/mv_chunks.py:310`。look の確かめの「did not run」の行は `plan["python"].replace("'", "''")` で、ASCII の `'` しか二重にしない。ほかの箇所は `_ps` を通り、5 文字とも二重にしている。
- 筋書き:
  - 計画の python が `…/Don’t_venv/Scripts/python.exe` だと、駆動台本の 38 行目の文字列が ’ で閉じる。残りは不正なトークンになる。
  - PowerShell は台本全体を先に構文解析する。このため何も走らず、`-File` は終了 1 で、out も作らない。
  - main（e4fb672）が同じ計画で書いた台本は、同じ python で look の確かめを通り、バッチまで走る。sandbox には mmd_cli が無いので、そこで止まる。
  - PowerShell 5.1 が ’ を引用符とみなす件は、査読 10 の 2（中）。`_ps` と QuoteTest はそのためにある。この 1 行だけが、その外にある。
- 根拠: 実測。
  - `parse_drivers.ps1`（`out_parse13.txt`）: U+2018・2019・201A・201B の 4 つとも構文エラー。ASCII の `'`・U+FF07・`{0}`・`$`・バッククォートは通る。main が書いた台本は 5 つとも通る。
  - `quote_python_runs.py`（`out_quote_python_runs.txt`）: ’ を含むフォルダの venv の python を実際に使った。main は走り、枝は構文エラーで止まる。
- 直し方: 下のように `-f` の引数に回す（`{` を含むパスにも安全）。

  ```
  "if ($null -eq $LASTEXITCODE) { 'STOP: {0} did not run for the look check (not found?)' -f %s; exit 1 }" % _ps(plan["python"])
  ```

  試験は `test_paths_with_typographic_quotes_run` と同じ形で、`python="C:/no/Don\u2019t/python.exe"` を渡す。終了 1 と「did not run」を見る。今のコードでは落ちる。指摘 4 の変異 D もこれで落ちる。

### 2. 低: python は走ったが mv_look が失敗した場合も、look の確かめは「the look does not work」と言う（査読 12 の 4 の残り）

- 場所: `tools/mv_chunks.py:311`
- 筋書き（sandbox の駆動台本を `-File` で流した、`look_msgs.py`。mv_look は、その失敗だけを起こす小さな代役に替えた）:

  | 失敗の中身 | 終了コード | 出る文言 |
  | --- | --- | --- |
  | `tools/mv_look.py` が無い（python の can't open file） | 2 | `STOP: the look does not work: …/look.json (mv_look layers, exit 2)` |
  | ライブラリが無い（ImportError） | 1 | 同じ |
  | mv_look の OSError（作業フォルダに書けない等） | 1 | 同じ |
  | look そのものの誤り（ValueError） | 2 | 同じ（この場合だけ正しい） |

  今回直ったのは「python が見つからない」（終了コードが空）だけ。査読 12 の 4 が推論で挙げた残りの理由も、実測で同じ文言になった。直しの表の 4 は、直した範囲を書いていない。
- 根拠: 実測（`out_look_msgs.txt`）。mv_look の JSON（理由）は次の行に出るので、読めば分かる。誤っているのは見出しだけ。
- 直し方: mv_look は look の誤りを `ValueError` で返す（`tools/mv_look.py:553–555`、終了 2）。`$check -match '"type": "ValueError"'` のときだけ今の文言を出し、ほかは「mv_look layers failed ({1})」にする。

### 3. 低: `__pycache__` の除外がフルパスの部分一致なので、この語を名前に含む本物の入力も印から消える

- 場所: `tools/mv_chunks.py:307`（`$_.FullName -notmatch '__pycache__'`。大文字小文字を区別しない）
- 筋書き（`t13.py`）:
  - モデルのフォルダの `tex/skin__pycache__.png` や `__pycache__/toon01.bmp` を書き換えても、`-Resume` は 3 区間とも飛ばす。対照として `tex/skin.png` を書き換えると、3 区間とも描き直す。
  - モデルのフォルダが `…/__pycache__x/model` にあると、フォルダの中身が全部印から消える。`.recipe` に残るのは PMX の 1 行だけで、テクスチャを変えても描き直す区間は 0。
  - どれも、黙って古い区間を使う側に外れる。
- 根拠: 実測（`out_t13_test_texture_whose_name_holds_pycache.txt`・`out_t13_test_model_folder_under_a_pycache_named_folder.txt`）。MMD の配布物でこう名付けることはまず無いので、低とした。
- 直し方: 区切りで挟み、`-notmatch '\\__pycache__\\'` とする（`ps/pycache13.ps1`）。
  - `FullName` の区切りは、フォルダを `/` で渡しても `\` になる（実測）。
  - この形なら `skin__pycache__.png` と `__PYCACHE__x\` は残る。外れるのは、python が書く `.pyc`・`.opt-1.pyc`・書き込み途中の一時ファイル（`.pyc.<数字>`）。
  - さらに絞るなら、`mmd_cli/` と `tools/` の下だけに当てる。

### 4. 低: 試験の穴（生き残る変異）と、試験の包みが構文エラーを終了 0 と読むこと

- 場所: `tests/test_mv_chunks.py`（DriverTest の場合、`run_driver` の 354 行、EndToEndTest の 822 行）
- 筋書き:
  - 変異は `mut13.py` で worktree に 1 つずつ当て、毎回戻した。下地（変異なし）は 70 本とも OK。

    | 変異 | 結果 | 入ったら |
    | --- | --- | --- |
    | D look の確かめの行で python のパスを引用しない | 通る（70 本 OK） | 指摘 1 と同じで、ASCII の `'` でも構文エラーになる |
    | C 除外を `'cache'` の部分一致に広げる | 通る | `cache` を含む本物の入力を見なくなる |
    | A バッチの文言から `Why` を外す | 通る | 本番では届かない（同じ python を look の確かめが先に走らせる） |
    | B 畳みの文言から `Why` を外す | 通る | 同上 |
    | F `Why` を `if (-not $code)` にする | 通る | 同値（0 では呼ばれない） |
    | E `@()` を外す | 落ちる（`test_one_argument_reaches_the_command_whole`） | 1 引数が 1 文字ずつに割れる |
    | G 除外を `$_.Name` に当てる | 落ちる（`test_resume_renders_again_after_any_input_it_watches_changes`） | `.pyc` が印に戻る |

  - 試験の包みは `& driver; exit $LASTEXITCODE`。駆動台本が構文エラーだと、`$LASTEXITCODE` は前の値のまま残り、包みは終了 0 になる。指摘 1 の台本 4 つでは、4 つとも終了 0 だった（`out_t13_quote.txt`）。本番の `-File` では終了 1 になる。今ある試験は、どれもほかの assert（バッチの数・ファイル）で落ちるので見逃しは無い。ただ、終了コードだけを見る試験を足すと、構文エラーを通してしまう。
- 根拠: 実測（`out_mut13_baseline.txt`・`out_mut13.txt`・`out_t13_quote.txt`）。
- 直し方:
  - 指摘 1 の試験を足す（D も落ちる）。
  - 指摘 3 の場合を足す。`skin__pycache__.png` を書き換えたら 3 区間になることを見る（C も落ちる）。
  - 包みは `-File` で台本を起こすか、`& driver` の後に `if (-not $?) { exit 98 }` を置く。

### 5. 情報: 記述の食い違い

- 場所と筋書き:
  - `size`:
    - README 442 行の「`size` は縦横とも偶数」は、-Resume の項の末尾に置かれている。
    - `size` を挙げている plan.json の項（423 行）には、既定値 [1280, 720] も偶数の条件も無い。
    - 説明文 18 行の `"size" ([1280, 720])` にも、偶数の条件が無い。
  - 説明文 36–38 行の「nor the bytecode Python writes under __pycache__: after changing any of those, render without -Resume」: バイトコードには「変えたら -Resume なしで」が当たらない（元の .py を見ている）。38 行は 197 文字で、折り返されていない。
  - 査読 12 の 5 のうち 2 つは、手つかずのまま。直しの表の 5 にも書かれていない。
    - README 435 行「外部コマンドは毎回、終了コードを空にしてから呼ぶ」: `Count-Frames` の ffprobe は `&` のまま。
    - README 437 行「印はバッチ・look・畳みの引数の SHA-256」: 入るのは look のパスで、中身は入らない。
  - README 434 行「走らなかったコマンドは「did not run」と言う」: バッチと畳みでは、この文言は本番では出ない（変異 A・B）。害は無い。
- 根拠: 読んだ。
- 直し方: 偶数の条件と既定値を、plan.json の項と説明文 18 行へ移す。バイトコードは「見ないもの」の並びから外し、「印から除く」と書く。査読 12 の 5 の 2 つを直す。

### 6. 情報: 既存の試験の穴（この枝の変更ではない）。光の位相を四捨五入から切り捨てに変えても、mv_look を描かせる試験はどれも落ちない

- 場所: `tools/mv_look.py` の `phase = int(round(clip_start * fps)) % …`。`tests/test_mv_look.py:552`（ChunkLightRenderTest）と 638 行（ExcerptRenderTest）。
- 筋書き:
  - 変異: `int(clip_start * fps)`。
  - 試験の開始時刻は、どれも 30 倍するとちょうど整数になる（1.9×30 = 57.0、first/30×30（10〜19）、1.1）。
  - 本番の `--from` は `%.6f` で書かれる。たとえば 3.333333×30 = 99.99999 で、切り捨てると光が 1 コマずれる。
- 根拠: 実測（`mut13_look.py`、`out_mut13_look.txt`）。`tests.test_mv_look` の 49 本も EndToEndTest の 2 本も通った。EndToEndTest は look が平ら（beams 0）なので、光が見えない。
- 直し方: ChunkLightRenderTest の開始時刻を `float("%.6f" % (first / 30.0))` にする（mv_chunks と同じ書き方）。これで捉えられるはず（推論）。

## 確かめて問題が無かった点

### Invoke-Native（依頼 1）

`ps/inv13.ps1`・`ps/inv13_out.txt` で確かめた。関数は駆動台本から取り出したものをそのまま使った。比べたのは次の 3 通りで、本物の python.exe に `ps/echoargs.py` を走らせて sys.argv を読んだ。
  - 新: 枝の `Invoke-Native`
  - 旧: main の `Invoke-Native`
  - 直接: `& python …`

- 本番の 4 か所と同じ形では、3 通りとも sys.argv が一致した。`-m`・`--out`・`-f`・`-safe 0` は、文字列のまま届く。
  - バッチ: `-m mmd_cli --out … batch …`
  - look の確かめ: `--size 1280x720 --fps 30`
  - 畳み: 関数の中で `[string[]]$fold` を `@fold` に渡す
  - 連結: `-v error -y -f concat -safe 0 -i … -c copy …`
- 1 引数（査読 12 の 3）:
  - 新は正しく渡る。`Invoke-Native python --version` も正しい。
  - 旧は 1 文字ずつに割れ、python が `C` を開こうとして終了 2 になる。
- 引数の中身ごと:
  - 空白 1 つ・中に空白 2 つ・全角空白と仮名・’・`'`・`[1]`・`{0}`・`$x;&(1)`・30・0.5・`$true`: 3 通りとも同じ。
  - 空文字列: 3 通りとも消える（PS 5.1）。
  - `a"b` と、末尾の `\` に空白を含むもの: 3 通りとも壊れる（PS 5.1 の外部コマンドの既知の挙動）。今の呼び出しには無い。
- `$null`:
  - 外部コマンドには、3 通りとも渡らない。
  - 関数（偽物）には、新は渡さず、旧と直接は渡す（引数の数は 2 と 3）。偽物が本物に近づく向きで、今の呼び出しに `$null` は無い。
- 素の `--` は消え、`-x:y` は `-x:` と `y` に割れる。新と旧で同じで、関数を通す呼び方の性質。今は使っていない。
- 終了コード:
  - 0・1・2・3・255・256・-1・2147483647・-2147483648・-1073741819 は、`| Out-Null`・`| Set-Content`・変数への取り込みのどれでも呼び手に届く。
  - 見つからないコマンドは、`cmd /c exit 0` の後でも `$LASTEXITCODE` が空になる。`| Set-Content` の先のファイルは作られない。
- 関数の呼び先での引数の名前: `param($m)` を持つ関数に `-m mmd_cli` を渡すと、新でも `$m` に結び付く。名前の印は、Select-Object を通っても残る。

### Why と文言（依頼 2）

- `Why` の文言:
  - 空のとき: `did not run`
  - 0 のとき: `exit 0`（ただし実際には呼ばれない）
  - 負の値・大きい値: `exit N`（10 進）
- ffmpeg が見つからないときの連結は、「joining failed (did not run)」と出て終了 1（実装者の試験。下地の 70 本で OK）。
- python のパスの ASCII `'` は `''` で正しく出る（`STOP: C:/no/Don't/python.exe did not run …`、終了 1）。

### `__pycache__` の除外（依頼 3）

- 本物の python で確かめた（`t13.py` の R13E、EndToEndTest の組み立て、`out_t13_e2e.txt`）。
  - 作ったばかりの木（`__pycache__` 無し）で全部描くと、駆動台本の python が `mmd_cli/__pycache__/__init__.cpython-312.pyc` と `__main__.cpython-312.pyc` を書いた（環境変数 `PYTHONDONTWRITEBYTECODE` は空）。
  - その直後の `-Resume` は、3 区間とも飛ばした。査読 12 の 1 は直っている。
  - 出力は utf-8 と cp932 で 2 回読まれるので、各行が 2 回ずつ出る。
- python は、`__pycache__` の .pyc を元の .py なしには読まない。.py を見ているので、.pyc を外しても失うものは無い。

### 偶数の検査と許容 2.0（依頼 4・5）

- 偶数の検査:
  - 既定の [1280, 720] と、EndToEndTest の 64x36 は偶数。
  - mv_look は入力の大きさのまま yuv420p で書く（`tools/mv_look.py:377–379`）。だからこの検査は、ちょうど要る所にある。
  - 1 も、mv_look より先にこの検査で止まる。
- 許容 2.0（`excerpt13.py`・`out_excerpt13.txt`。ExcerptRenderTest と同じ組み立てで、mv_look の写しを描いた）:
  - 変えないときの差の最大は 1.09。
  - 区間だけを 1 コマずらした変異は、どれも捉える。光 ±1 コマで 18.67・18.69、パンチ ±1 コマで 4.85・5.31、区間の前に始まったパンチを落とすと 13.08。実装者の「4〜19」と合う。
  - 全曲も一緒にずれる変異では、両方がそろってずれるので差が出ない。これはこの試験の対象外。

### 実装者の主張

- 本数: 864＋4＝868 で合う。test_mv_chunks の 70 本は、手元の worktree で OK（201 秒）。全体の試験は流していない（決まり）。
- 変異 11 の台本 `mutate_r12.py` を読んだ。11 とも、壊した所を見る試験が足されている。
  - ただしこの台本は、落ちた試験の名前を見ない。`-f` で「どれか 1 本落ちた」を数えるだけ。
  - 下地が通ることは上で確かめた。同じ種類の E・G は、意図した試験が落ちることを名前で確かめた。
- 枝の `tools/mv_chunks.py` に、過去の変異の残り（`[:1]`・`if ($false)`・`$exe, $rest` 等）は無い。

## 確かめられなかったこと

- hinata（決まりで触れない）
- 全体の試験（決まりで流さない）

## 台本と出力（すべて `scratchpad/r13/`）

| 台本 | 中身 | 出力 |
| --- | --- | --- |
| `gen.py`・`gen_main.py`・`parse_drivers.ps1`・`parse_drivers_main.ps1` | python のパスの引用符ごとの構文解析（枝と main） | `out_parse13.txt` |
| `quote_python_runs.py`（`gen_sandbox.py`） | ’ を含むフォルダの実在の python で、main と枝を `-File` で流す | `out_quote_python_runs.txt` |
| `ps/inv13.ps1`（`ps/echoargs.py`） | `Invoke-Native`・終了コード・`Why` | `ps/inv13_out.txt` |
| `t13.py` | DriverTest と EndToEndTest の仕組みで足した場合 | `out_t13_*.txt` |
| `look_msgs.py` | look の確かめの文言 | `out_look_msgs.txt` |
| `ps/pycache13.ps1` | 除外の形の比べ | `ps/pycache13_out.txt` |
| `mut13.py` | 変異 A〜G と下地 | `out_mut13_baseline.txt`・`out_mut13.txt` |
| `excerpt13.py`・`mut13_look.py` | 許容 2.0 の余裕と、位相の切り捨て | `out_excerpt13.txt`・`out_mut13_look.txt` |

## 査読 13 への直し（実装者、2026-10-07、c9175e9）

| 指摘 | 直し | 確かめ方 |
| --- | --- | --- |
| 1 低（退行） `did not run` の行の引用 | python のパスを `_ps` に通す | ’ を含む python のパスで駆動台本が解析でき、「did not run」で止まる試験（直す前は解析できず終了 98） |
| 2 低 look の確かめの文言 | 「mv_look layers failed on the look …」と、mv_look の答えを出す（look のせいと決めつけない） | 既存の試験 |
| 3 低 `__pycache__` の部分一致 | パスの中のフォルダとしてだけ外す（駆動台本の正規表現は `[\\/]__pycache__[\\/]`） | 名前に `__pycache__` を含むテクスチャを足すと描き直す試験 |
| 4 低 試験の穴・包み | 包みは駆動台本を先に解析し、構文誤りなら終了 98（try/catch は見つからないコマンドでも止まり `-File` と違うので使わない） | 変異 D（引用なし）・C（`cache` の部分一致）・光の位相の切り捨ては、写しの作業木で 3 つとも落ちた |
| 5 情報 記述 | 印は「バッチの本文・look のパス・畳みの引数の SHA-256」、終了コードを空にするのは「バッチ・mv_look・連結」、`size` の偶数は plan.json の項へ、説明文のバイトコードの文を直した | ― |
| 6 情報 光の位相の丸め | mv_chunks が書く `%.6f` の `--from`（8.533333）で位相 16 になる試験（切り捨てなら 15） | 変異で確かめた |

- 全体の試験 870 本 OK（1 本は以前からの飛ばし）。

