"""The copy of the live test suite that runs inside the logged-on user's desktop session.

Started by run_live_tests_in_session.py through the Task Scheduler under pythonw.exe (no console
window on the desktop).  Everything the tests print goes to the log file; the exit code is left
next to it, written whole, so that the parent never reads a half-written marker.

    pythonw live_in_session.py JOB.json      (JOB holds repo, log, exe and home: schtasks allows
                                              only 261 characters for the command line)
"""
import json
import os
import sys
import unittest


def main(argv):
    with open(argv[0], encoding="utf-8") as f:
        job = json.load(f)
    repo, log = job["repo"], job["log"]
    os.chdir(repo)
    sys.path.insert(0, repo)
    os.environ["MMD_CLI_LIVE"] = "1"
    os.environ["MMD_EXE"] = job["exe"]
    os.environ.pop("MMD_CLI_LIVE_ATTACH", None)
    if job.get("home"):
        os.environ["MMD_CLI_HOME"] = job["home"]
    else:
        os.environ.pop("MMD_CLI_HOME", None)
    with open(log + ".started.part", "w") as f:
        f.write(str(os.getpid()))
    os.replace(log + ".started.part", log + ".started")
    code = 1
    try:
        with open(log, "w", encoding="utf-8", buffering=1) as out:
            sys.stdout = sys.stderr = out
            suite = unittest.defaultTestLoader.loadTestsFromName("tests.live.test_live")
            result = unittest.TextTestRunner(stream=out, verbosity=1).run(suite)
            code = 0 if result.wasSuccessful() else 1
    finally:
        with open(log + ".exit.part", "w") as f:
            f.write(str(code))
        os.replace(log + ".exit.part", log + ".exit")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
