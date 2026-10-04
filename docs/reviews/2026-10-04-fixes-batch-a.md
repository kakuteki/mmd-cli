# レビュー 1 への修正 batch A (2026-10-04)

対象: `docs/reviews/2026-10-04-review-1.md` の 1.4 / 1.5 / 1.6 / 1.7 / 1.8 / 1.1(低) / 5.1 / 3.1 / 3.2 / 3.3 / 3.5 / 4.5 と、対応する 5.3 / 5.5 の試験。
作業場所: worktree `.claude/worktrees/agent-a27c08c9738d632f5`、ブランチ `worktree-agent-a27c08c9738d632f5`。
起点: main の 00d1daf（worktree は 34050a2 で切られていたので fast-forward で揃えた）。
査読報告そのものは本体のチェックアウトに未追跡で置かれていたので、そこから読んだ（この worktree にはコピーしていない）。
進め方: 項目ごとに失敗する単体試験を先に書き、失敗を見てから直し、通ることを見てコミット。MMD は起動しない。`schtasks` は本当には呼ばない。
ベースライン: `python -m unittest discover -s tests -t .` は `Ran 114 tests ... OK (skipped=1)`（skip は tests/live）。

書式: 項目ごとに「何を直したか／どの試験が守るか／コミット」。項目が終わるたびに追記する。

## 1.4 relay: 子の `.exit` を原子的に置く・親は空を 0 と読まない

- 何を直したか: `run_job` は `.exit.part` に書いて `os.replace` で `.exit` にする（`_write_whole`）。`collect` は `.exit` が空なら 0.05 秒おきに最大 10 回読み直し（`_read_code`）、埋まらなければ `RelayError`（終了コード 1）にする。`int("" or 0)` の経路は無くした。
- 守る試験（tests/test_relay.py）: `test_collect_waits_for_a_complete_exit_file`（空の `.exit` で 0 を返さない。修正前は 0 == 0 で失敗）、`test_collect_reads_again_when_the_exit_file_fills_up_late`（0.15 秒後に 3 が書かれると 3 を返す。修正前は 0）、`test_run_job_writes_exit_atomically`（`os.replace(".exit.part", ".exit")` が呼ばれ `.part` が残らない。修正前は呼ばれない）。
- コミット: 7235346

## 1.5 relay: 親は子の寿命で待つ

- 何を直したか: `run_in_user_session(argv, start_timeout=15.0, grace=2.0)`。`timeout` 引数は無くした。`.started` が 15 秒以内に現れなければ従来どおり「ログオンしていない」系の `RelayError`。現れたらそこに書かれた PID を `win32.process_alive` で 0.1 秒おきに見張り、`.exit` が無いまま子が死んでから 2 秒たったときだけ `RelayError("... (pid N) ended without leaving a result")`。親が諦めるとき（例外・Ctrl-C）は `finally` で `schtasks /End` を呼んでから `/Delete` と後始末。子は `.started` も `.part` 経由で原子的に書く（親がその中身を読むため）。cli.py の `main()` から `timeout=(args.timeout or 120.0) + 60.0` を外し `run_in_user_session(argv)` にした。
- 設計判断: 親に固定の上限を持たせると子の規則（`render avi` の `60 + 2 × フレーム数` など）を親が二重に知る必要があり、今回の 180 秒の食い違いがまた起きる。子は自分の操作ごとにタイムアウトを持っているので、親は「子が生きている間は待つ」だけで上限は子の寿命に一致する。親が独自に切るのは「子が始まらない（15 秒）」と「子が死んだのに結果が無い（2 秒の猶予）」の 2 つだけで、どちらも待っても意味が無い状況である。
- 未確認: 親（SSH = セッション 0、管理者なら高整合性）から対話セッションの子 pythonw.exe への `OpenProcess(SYNCHRONIZE)` が通ること。この PC では自分のプロセス 680 本すべてがセッション 1 にあり、`schtasks` を本当に動かさない制約の下では別セッションの同一利用者プロセスを作れないので測れなかった。測れた範囲: 自分の PID は True、System(PID 4) は err 5 で False、存在しない PID は err 87 で False。もし通らない場合の症状は「`.started` が出た約 2 秒後に ended without leaving a result」で、実機の通し試験（SSH から `mmd state`）を 1 回流せば判る。
- 守る試験（tests/test_relay.py、偽の schtasks `FakeScheduler`・仮想時計 `FakeClock`・`win32.process_alive` の差し替え。実時間も MMD も使わない）: `test_parent_waits_as_long_as_the_child_lives`（子が仮想時刻 400 秒で終えても結果を回収し `/End` を呼ばない。修正前は 180 秒で RelayError）、`test_parent_gives_up_when_the_child_died_without_a_result`（死んだ子に 2 秒の猶予のあと PID 入りの RelayError、`/End` → `/Delete` の順、relay/ に何も残らない）、`test_parent_reports_no_logon_when_the_child_never_starts`（15 秒で従来の文言、`/End` も呼ぶ。修正前は `/End` が無い）、`test_run_job_writes_the_started_marker_atomically_with_its_pid`。
- コミット: d332c2b

## 1.6 relay: 中継の要否を解析済みの `args.command` で決める

- 何を直したか: `should_relay(window_station=None, session_id=None, argv=None, command=None)`。位置引数の走査（`--out r.json` の `r.json` を命令と誤認していた）を無くし、`command is None`（命令なし）または `command in LOCAL_COMMANDS` なら中継しない。`--version` / `-h` の個別判定も不要になった（argparse がそこで終わる。`command=None` で同じ結果）。`main()` は `relay.should_relay(argv=argv, command=args.command)` を呼ぶ。
- 守る試験（tests/test_relay.py）: `test_should_relay_ignores_option_values_before_the_command`（査読の実測 2 例 `--out r.json file info x.pmm` と `--timeout 9 file info x.pmm` が False、`--out r.json state` は True）、`MainDecisionTest.test_file_info_runs_locally_whatever_options_come_first`（`cli.main` を Service ウィンドウステーション・セッション 0 の偽の答えで動かし、3 例とも `run_in_user_session` が呼ばれず fixture の pmm がその場で読める。修正前は `--out` の例で中継に入り失敗した）、`test_a_command_that_needs_the_window_is_handed_over_as_is`（`state` は argv そのままで渡される＝親のタイムアウト結合が無い）。既存の DecisionTest は `command=` を渡す形に書き換えた。
- コミット: 381be16

## 1.7 relay: 子の argv に `--no-relay`

- 何を直したか: `child_argv` が返す argv の先頭に `--no-relay` を置く（`--in-user-session` / 元の `--no-relay` は従来どおり取り除いてから）。子がもし対話ステーション以外で動いても `should_relay` は最初の判定で False になり、孫のタスクは作られない。
- 守る試験（tests/test_relay.py）: `test_child_argv_adds_no_relay`（3 通りの入力で `--no-relay` がちょうど 1 回・`--in-user-session` なし・その argv を Service ステーションで `should_relay` に掛けると False）、`test_child_argv_with_out_equals`（`--out=` の形）、既存の 2 件は期待値に `--no-relay` を足した。
- コミット: 838f10d
