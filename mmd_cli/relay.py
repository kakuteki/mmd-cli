"""Run a command inside the user's interactive desktop session when we are not in one.

Window messages do not cross window stations: an `mmd` started from an SSH login, a service or a
CI agent (session 0, window station "Service-...") cannot see or drive an MMD that runs on the
user's desktop, and MMD itself does not finish starting without an interactive desktop (measured
on v9.32: the window is created but it never answers).  So in that situation the command is handed
to the Task Scheduler as a one-shot task marked "interactive": the scheduler starts pythonw.exe in
the logged-on user's session, where it runs the same command line, writes the JSON to a file, and
this process returns that file.  Nothing is shown on the desktop (pythonw has no console and the
MMD window stays hidden or minimized).  If the user is not logged on, the task never starts and
the error says so.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes as wt
from dataclasses import dataclass, field
from typing import Dict, List

RELAY_FLAGS = ("--in-user-session", "--no-relay")
LOCAL_COMMANDS = ("file",)          # work on files only; no window needed
_NO_WINDOW = 0x08000000


# ---- where are we? -------------------------------------------------------------------------

def window_station_name():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetProcessWindowStation.restype = ctypes.c_void_p
    user32.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                                 ctypes.POINTER(wt.DWORD)]
    buf = ctypes.create_unicode_buffer(256)
    needed = wt.DWORD(0)
    if not user32.GetUserObjectInformationW(user32.GetProcessWindowStation(), 2, buf, 512, ctypes.byref(needed)):
        return ""
    return buf.value


def current_session_id():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sid = wt.DWORD(0)
    kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    return sid.value


def should_relay(window_station=None, session_id=None, argv=None, command=None):
    """decide whether this invocation must be handed to the interactive session.  command is the
    parsed sub-command (argparse knows which words are option values; a scan of argv does not)"""
    session_id_ = session_id
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--no-relay" in argv:
        return False
    if "--in-user-session" in argv:
        return True
    if command is None or command in LOCAL_COMMANDS:
        return False
    if window_station is None:
        window_station = window_station_name()
    if session_id_ is None:
        session_id_ = current_session_id()
    return session_id_ == 0 or window_station != "WinSta0"


# ---- the job handed over -------------------------------------------------------------------

@dataclass
class Job:
    argv: List[str]
    out_path: str
    cwd: str = ""
    env: Dict[str, str] = field(default_factory=dict)


def child_argv(argv, out_path):
    """the relayed command line: relay flags removed, --out pointed at the relay's result file"""
    out = []
    skip = False
    had_out = False
    for a in argv:
        if skip:
            skip = False
            out.append(out_path)
            continue
        if a in RELAY_FLAGS:
            continue
        if a == "--out":
            had_out = True
            out.append(a)
            skip = True
            continue
        if a.startswith("--out="):
            had_out = True
            out.append("--out=" + out_path)
            continue
        out.append(a)
    if not had_out:
        out = ["--out", out_path] + out
    return out


def write_job(job, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"argv": job.argv, "out": job.out_path, "cwd": job.cwd, "env": job.env}, f, ensure_ascii=False)


def read_job(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return Job(argv=d["argv"], out_path=d["out"], cwd=d.get("cwd", ""), env=d.get("env", {}))


def relay_dir():
    base = os.environ.get("MMD_CLI_HOME") or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                                                          "mmd-cli")
    return os.path.join(os.path.abspath(base), "relay")


def task_name():
    return "mmd-cli\\relay-" + uuid.uuid4().hex[:12]


def windowless_interpreter(python_exe):
    """pythonw.exe next to the given python.exe: it opens no console window on the user's desktop"""
    return os.path.join(os.path.dirname(python_exe), "pythonw.exe")


def task_command(interpreter, job_path):
    return '"%s" -m mmd_cli --job "%s"' % (interpreter, job_path)


def _write_whole(path, text):
    """write a marker file in one step (to .part, then moved) so a reader never sees it half written"""
    with open(path + ".part", "w") as f:
        f.write(text)
    os.replace(path + ".part", path)


def _read_code(exit_path, retries=10):
    """the child's exit code; an empty file is read again after a short wait and is never taken as 0"""
    for _ in range(retries):
        with open(exit_path) as f:
            text = f.read().strip()
        if text:
            return int(text)
        time.sleep(0.05)
    raise ValueError("%s stayed empty" % exit_path)


def collect(out_path):
    """the child's JSON and exit code, or an error when it left nothing behind"""
    try:
        with open(out_path, encoding="utf-8") as f:
            payload = json.load(f)
        code = _read_code(out_path + ".exit")
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": {"type": "RelayError",
                                       "message": "the relayed command left no result (%s)" % exc}}, 1
    payload["relayed"] = True
    return payload, code


# ---- running through the Task Scheduler -----------------------------------------------------

def _schtasks(*args, timeout=60):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.run(["schtasks.exe"] + list(args), capture_output=True, startupinfo=startup,
                          creationflags=_NO_WINDOW, timeout=timeout)


def _text(raw):
    for enc in ("utf-8", "cp932", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


class RelayError(Exception):
    pass


def _child_pid(started_marker):
    with open(started_marker) as f:
        text = f.read().strip()
    if not text.isdigit():
        raise RelayError("the relayed command did not record its process id in %s" % started_marker)
    return int(text)


def run_in_user_session(argv, start_timeout=15.0, grace=2.0):
    """hand argv to a copy of this program in the interactive session; returns (payload, exit_code).
    The parent has no clock of its own: it waits as long as the child process lives (the child
    times out its own operations) and gives up only when the child did not start or died without
    leaving a result; then it stops the task before taking its files away."""
    from . import win32
    folder = relay_dir()
    os.makedirs(folder, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    job_path = os.path.join(folder, job_id + ".json")
    out_path = os.path.join(folder, job_id + ".out.json")
    env = {k: v for k, v in os.environ.items() if k.startswith("MMD_")}
    write_job(Job(argv=child_argv(argv, out_path), out_path=out_path, cwd=os.getcwd(), env=env), job_path)
    name = task_name()
    interpreter = windowless_interpreter(sys.executable)
    if not os.path.isfile(interpreter):
        interpreter = sys.executable
    command = task_command(interpreter, job_path)
    if len(command) > 260:
        raise RelayError("the command line for the Task Scheduler is longer than 260 characters: %s" % command)
    created = _schtasks("/Create", "/TN", name, "/TR", command, "/SC", "ONCE", "/ST", "00:00", "/IT", "/F")
    if created.returncode != 0:
        raise RelayError("schtasks /Create failed: %s" % _text(created.stderr or created.stdout).strip())
    finished = False
    try:
        started = _schtasks("/Run", "/TN", name)
        if started.returncode != 0:
            raise RelayError("schtasks /Run failed: %s" % _text(started.stderr or started.stdout).strip())
        started_marker = out_path + ".started"
        deadline = time.monotonic() + start_timeout
        while not os.path.exists(started_marker):
            if time.monotonic() > deadline:
                raise RelayError("the command did not start in an interactive session within %.0f s: is anyone "
                                 "logged on to this machine's desktop? (the task runs only while the user is "
                                 "logged on; a virtual display and a disconnected session are fine)" % start_timeout)
            time.sleep(0.1)
        pid = _child_pid(started_marker)
        dead_at = None
        while not os.path.exists(out_path + ".exit"):
            if dead_at is None and not win32.process_alive(pid):
                dead_at = time.monotonic()
            if dead_at is not None and time.monotonic() - dead_at > grace:
                raise RelayError("the relayed command (pid %d) ended without leaving a result" % pid)
            time.sleep(0.1)
        finished = True
        return collect(out_path)
    finally:
        if not finished:
            _schtasks("/End", "/TN", name)          # stop the child before taking its files away
        _schtasks("/Delete", "/TN", name, "/F")
        for p in (job_path, out_path, out_path + ".exit", out_path + ".started"):
            try:
                os.remove(p)
            except OSError:
                pass


def run_job(job_path, main):
    """child side: executed by the scheduled task"""
    job = read_job(job_path)
    _write_whole(job.out_path + ".started", str(os.getpid()))
    os.environ.update(job.env)
    if job.cwd and os.path.isdir(job.cwd):
        os.chdir(job.cwd)
    try:
        code = main(job.argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # the parent must never wait forever
        with open(job.out_path, "w", encoding="utf-8") as f:
            json.dump({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, f)
        code = 1
    _write_whole(job.out_path + ".exit", str(code))
    return code
