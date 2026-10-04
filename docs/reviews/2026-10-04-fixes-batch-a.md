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
