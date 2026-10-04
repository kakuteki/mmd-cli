"""Run the live test suite in the logged-on user's desktop session and wait for its verdict.

For a machine reached over SSH (session 0, no desktop): the tests themselves could not drive MMD
from there, so they are started the way `mmd` relays its commands, as a one-shot Task Scheduler
task that runs only while the user is logged on, under pythonw.exe (no console window appears).
The log is tailed when the run is over; the exit code is that of the suite.

    python tools/run_live_tests_in_session.py --exe C:/tools/MikuMikuDance_v932x64/MikuMikuDance.exe
    python tools/run_live_tests_in_session.py --exe ... --home C:/work/mmd-cli-home --tail 40
"""
import argparse
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmd_cli import relay, win32  # noqa: E402

START_TIMEOUT = 15.0
GRACE = 2.0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--exe", required=True, help="MikuMikuDance.exe for the tests to start")
    p.add_argument("--home", help="MMD_CLI_HOME for the tested instance (default: the user's usual one)")
    p.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p.add_argument("--tail", type=int, default=25, help="lines of the log to print at the end")
    args = p.parse_args(argv)

    repo = os.path.abspath(args.repo)
    folder = relay.relay_dir()
    os.makedirs(folder, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    log = os.path.join(folder, "live-%s.log" % run_id)
    job_path = os.path.join(folder, "live-%s.json" % run_id)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump({"repo": repo, "log": log, "exe": os.path.abspath(args.exe), "home": args.home or ""}, f)
    child = os.path.join(repo, "tools", "live_in_session.py")
    name = "mmd-cli\\live-" + run_id
    created = relay.create_task(name, relay.windowless_interpreter(sys.executable), '"%s" "%s"' % (child, job_path))
    if created.returncode != 0:
        print("schtasks /Create failed: %s" % relay._text(created.stderr or created.stdout).strip())
        return 2
    code = 2
    try:
        started = relay._schtasks("/Run", "/TN", name)
        if started.returncode != 0:
            print("schtasks /Run failed: %s" % relay._text(started.stderr or started.stdout).strip())
            return 2
        deadline = time.monotonic() + START_TIMEOUT
        while not os.path.exists(log + ".started"):
            if time.monotonic() > deadline:
                print("the tests did not start within %.0f s: is anyone logged on to this machine's desktop?" % START_TIMEOUT)
                return 2
            time.sleep(0.1)
        pid = relay._child_pid(log + ".started")
        print("running as pid %d in the desktop session; log: %s" % (pid, log), flush=True)
        dead_at = None
        while not os.path.exists(log + ".exit"):
            if dead_at is None and win32.process_alive(pid) is False:
                dead_at = time.monotonic()
            if dead_at is not None and time.monotonic() - dead_at > GRACE:
                print("the test process (pid %d) ended without leaving a verdict" % pid)
                break
            time.sleep(0.5)
        if os.path.exists(log + ".exit"):
            code = relay._read_code(log + ".exit")
    finally:
        relay._schtasks("/Delete", "/TN", name, "/F")
        for leftover in (log + ".started", log + ".exit", job_path):
            try:
                os.remove(leftover)
            except OSError:
                pass
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        for line in lines[-args.tail:]:
            print(line.encode("ascii", "backslashreplace").decode())
    print("exit code %d" % code)
    return code


if __name__ == "__main__":
    sys.exit(main())
