"""Operate one running MikuMikuDance instance through window messages.

Nothing here activates or restores the MMD window.  Every operation waits for MMD to finish
(see guard.Guard.run) and reads the result back from MMD.
"""
import contextlib
import json
import os
import re
import shutil
import stat
import struct
import threading
import time

from . import guard, mathutil, scene, win32
from .formats import pmm, vmd, vpd
from .guard import DialogPending, OperationTimeout
from .ids import AviDialog, CONTROL_COUNT, Ctl, MAIN_WINDOW_CLASS, Menu, OutputSizeDialog

_TITLE_PATH = re.compile(r"^MikuMikuDance \[(.*)\]\s*$")
_MODEL_EXTENSIONS = (".pmx", ".pmd")
_IMAGE_EXTENSIONS = (".png", ".bmp", ".jpg", ".dds", ".dib", ".pfm", ".hdr")
# menu items seen with a check mark on MMD v9.32 (2026-10-04, `menu list` on a fresh instance, and 282 after a
# click): the ones `menu set` may click while they show no mark.  215 axes and grid, 221 ground shadow,
# 254 transparent ground shadow, 277 anti-aliasing, 298 mip map, 282 black background (the PNG and the
# uncompressed AVI then carry an alpha channel), 285 physics floor, 295 the motion capture figure
CHECK_ITEMS = frozenset((215, 221, 254, 277, 298, 282, 285, 295))


class MmdError(Exception):
    pass


# ---- where the CLI keeps its own files -----------------------------------------------------

def home_dir():
    base = os.environ.get("MMD_CLI_HOME")
    if not base:
        base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mmd-cli")
    base = os.path.abspath(base)        # also turns forward slashes into the ones MMD's file dialogs accept
    try:
        _require_ansi(base)             # the working copies and key files written here must reach MMD
    except MmdError:
        raise MmdError("the working folder %s has characters outside the system code page, so MMD could not "
                       "open the files kept there: set MMD_CLI_HOME to a plain path"
                       % base.encode("ascii", "backslashreplace").decode("ascii"))
    os.makedirs(base, exist_ok=True)
    return base


def _state_path():
    return os.path.join(home_dir(), "state.json")


def load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    state.setdefault("current", None)
    state.setdefault("projects", {})
    return state


def save_state(state):
    state["projects"] = {pid: rec for pid, rec in state["projects"].items() if win32.process_alive(int(pid)) is not False}
    tmp = "%s.%d-%d.tmp" % (_state_path(), os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    for attempt in range(100):
        try:
            os.replace(tmp, _state_path())
            return
        except PermissionError:         # somebody is reading it at this very moment
            if attempt == 99:
                raise
            time.sleep(0.01)


@contextlib.contextmanager
def _state_lock():
    """one writer at a time, across processes: a lock file that only one can create"""
    lock = _state_path() + ".lock"
    deadline = time.monotonic() + 5.0
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):       # held, or being removed by its holder right now
            try:
                if time.time() - os.path.getmtime(lock) > 10.0:     # left behind by a process that died
                    os.remove(lock)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise MmdError("the state file is locked by another mmd command: %s" % lock)
            time.sleep(0.005)
    try:
        yield
    finally:
        os.close(fd)
        try:
            os.remove(lock)
        except OSError:
            pass


def update_state(change):
    """read, change and write the state file under the lock, so that two commands do not lose each other's entries"""
    with _state_lock():
        state = load_state()
        change(state)
        save_state(state)
    return state


def _same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _num(value):
    return round(float(value), 4) + 0.0


def _vec(values):
    return [_num(v) for v in values]


def _format(value):
    text = "%.6f" % float(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _require_ansi(path):
    """MMD is an ANSI program: a path with characters outside the system code page does not reach it intact"""
    try:
        path.encode("mbcs")
    except UnicodeEncodeError:
        raise MmdError("MMD cannot open this path: it has characters outside the system code page: %s"
                       % path.encode("ascii", "backslashreplace").decode("ascii"))
    return path


def check_input_file(path, extensions, what):
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise FileNotFoundError(full)
    if extensions and os.path.splitext(full)[1].lower() not in extensions:
        raise MmdError("%s must be one of %s: %s" % (what, ", ".join(extensions), full))
    return _require_ansi(full)


def check_output_file(path):
    full = os.path.abspath(path)
    if os.path.isdir(full):
        raise MmdError("%s is a folder: give a file name" % full)
    return _require_ansi(full)


def _free_name(base):
    """base, or base.1, base.2 ... when something is already there"""
    name, n = base, 0
    while os.path.exists(name):
        n += 1
        name = "%s.%d" % (base, n)
    return name


def _remove_quietly(path):
    try:
        os.chmod(path, stat.S_IWRITE)            # a read-only file can be renamed but not removed
        os.remove(path)
    except OSError:
        pass


def _rename_quietly(src, dst):
    try:
        os.replace(src, dst)
    except OSError:
        pass


@contextlib.contextmanager
def keeping_the_old_file(path):
    """MMD is about to write `path`.  A file already there is moved aside first (MMD would otherwise ask
    about overwriting it) and comes back when the operation fails; on success it is dropped.  What a failed
    operation wrote is not thrown away: it stays next to the old file as `path.mmdcli-failed` (the error
    names it).  A `.mmdcli-old` left behind by an interrupted run is somebody's original and is never
    removed: this run's copy takes another name."""
    if os.path.isdir(path):
        raise MmdError("%s is a folder: give a file name" % path)
    aside = None
    if os.path.exists(path):
        aside = _free_name(path + ".mmdcli-old")
        os.replace(path, aside)
    try:
        yield
    except BaseException as exc:
        if os.path.exists(path):
            kept = _free_name(path + ".mmdcli-failed")
            _rename_quietly(path, kept)
            exc.kept_output = kept
            if exc.args:
                exc.args = ("%s (what MMD wrote is kept as %s)" % (exc.args[0], kept),) + exc.args[1:]
        if aside is not None:
            _rename_quietly(aside, path)
        raise
    if aside is not None:
        if os.path.exists(path):
            _remove_quietly(aside)
        else:
            _rename_quietly(aside, path)


def forget_instance(pid):
    """drop what the state file keeps about an instance that is gone"""
    def change(state):
        state["projects"].pop(str(pid), None)
        if state.get("current") == pid:
            state["current"] = None
    update_state(change)


# ---- finding and starting MMD ---------------------------------------------------------------

def instances():
    out = []
    for hwnd in win32.find_windows(cls=MAIN_WINDOW_CLASS):
        out.append({"pid": win32.window_pid(hwnd), "hwnd": hwnd, "title": win32.get_text(hwnd, timeout_ms=500),
                    "minimized": win32.is_iconic(hwnd), "visible": win32.is_visible(hwnd)})
    return out


def launch(exe, timeout=90.0, headless=False):
    """start MMD without activating it: minimized, or with headless=True hidden (no taskbar button,
    nothing on screen; mmd window show brings it back).  Returns when it is ready for commands."""
    exe = os.path.abspath(exe)
    if not os.path.isfile(exe):
        raise FileNotFoundError(exe)
    pid = win32.launch_detached(exe, show=win32.SW_HIDE if headless else win32.SW_SHOWMINNOACTIVE)
    deadline = time.monotonic() + timeout
    hwnd = None
    said = []
    answered = set()
    quoted = lambda: (": " + " / ".join(d["message"] for d in said)) if said else ""
    with win32.timer_resolution():
        while True:
            mains = win32.find_windows(pid=pid, cls=MAIN_WINDOW_CLASS)
            for dialog in guard.open_dialogs(pid, mains[0] if mains else None):
                if dialog.hwnd in answered:
                    continue                    # its OK is posted; MMD closes it when it gets to it
                # MMD may complain while starting (an effect it could not load, a Direct3D device it could not
                # create).  A notice (a single OK) is closed and remembered.  A question cannot be answered
                # blind, and a process stuck in one before it has a main window could not be reached afterwards,
                # so it is ended
                buttons = dialog.buttons
                if len(buttons) != 1 or buttons[0][0] not in (1, 2):
                    win32.terminate_process(pid)
                    raise MmdError("MMD (pid %d) stopped at a dialog while starting and was ended: %s: %s"
                                   % (pid, dialog.title, dialog.message))
                guard.click(dialog, buttons[0][0])
                answered.add(dialog.hwnd)
                said.append(dict(dialog.to_json(), action="ok"))
            if mains:
                hwnd = mains[0]
                if (len(win32.child_windows(hwnd)) >= CONTROL_COUNT
                        and win32.send(hwnd, win32.WM_NULL, timeout_ms=300) is not None):
                    break
            if win32.process_alive(pid) is False:
                raise MmdError("MMD exited right after it was started%s" % quoted())
            if time.monotonic() > deadline:
                # not ready, perhaps stuck behind a notice it does not close: nobody could reach it afterwards
                win32.terminate_process(pid)
                raise MmdError("MMD (pid %d) did not become ready within %.0f s and was ended%s"
                               % (pid, timeout, quoted()))
            time.sleep(0.01)
    mmd = Mmd(pid, hwnd)
    mmd.events.extend(said)
    mmd.wait_quiet()
    if headless and win32.is_visible(hwnd):
        mmd.hide()

    def remember(state):
        state["current"] = pid
        state["exe"] = exe
    update_state(remember)
    return mmd


class Mmd:
    def __init__(self, pid, hwnd):
        self.pid = pid
        self.hwnd = hwnd
        self.guard = guard.Guard(pid, hwnd)
        self.timeout = 120.0
        self.in_place = False
        self.events = []        # dialogs that were answered automatically, oldest first
        self._controls = None
        self._parking = None

    @classmethod
    def attach(cls, pid=None):
        """pick the instance to talk to: explicit pid, MMD_CLI_PID, the one launched last by the
        CLI, or the only one running"""
        running = instances()
        if not running:
            raise MmdError("MMD is not running (start it with: mmd launch --exe PATH)")
        by_pid = {i["pid"]: i for i in running}
        if pid is None and os.environ.get("MMD_CLI_PID"):
            pid = int(os.environ["MMD_CLI_PID"])
        if pid is not None:
            if pid not in by_pid:
                raise MmdError("no MMD window belongs to pid %d (running: %s)" % (pid, sorted(by_pid)))
            return cls(pid, by_pid[pid]["hwnd"])
        current = load_state().get("current")
        if current in by_pid:
            return cls(current, by_pid[current]["hwnd"])
        if len(running) == 1:
            return cls(running[0]["pid"], running[0]["hwnd"])
        raise MmdError("several MMD instances are running (%s): choose one with --pid" % sorted(by_pid))

    # ---- plumbing -----------------------------------------------------------------------------

    def ctl(self, cid):
        if self._controls is None:
            self._controls = {win32.control_id(h): h for h in win32.child_windows(self.hwnd)}
        try:
            return self._controls[cid]
        except KeyError:
            raise MmdError("control %d does not exist (is this MikuMikuDance 9.32?)" % cid)

    def text(self, cid):
        return win32.get_text(self.ctl(cid))

    def playing(self):
        return win32.button_checked(self.ctl(Ctl.PLAY))

    def require_ready(self, allow_playing=False):
        if not win32.is_window(self.hwnd):
            raise MmdError("the MMD window is gone (pid %d)" % self.pid)
        pending = guard.open_dialogs(self.pid, self.hwnd, hide=False)
        if pending:
            raise DialogPending(pending)
        if not allow_playing and self.playing():
            raise MmdError("MMD is playing: stop it first with  mmd stop")

    def _run(self, trigger, handlers=None, timeout=None, done=None):
        with self._parked() as hidden:
            try:
                events = self.guard.run(trigger, handlers, timeout or self.timeout, done, keep_hidden=hidden)
            except Exception as exc:
                self._keep(getattr(exc, "events", []))      # what was answered before the failure is kept
                raise
            self._keep(events)
            return events

    @contextlib.contextmanager
    def _parked(self):
        """a hidden instance must stay off the screen even when MMD shows its window on its own (it does so
        when it starts writing an AVI, and an asynchronous hide only takes effect once MMD is idle again, a
        second later).  For the outermost operation the hidden window is moved off-screen first, so that
        whatever MMD shows appears nowhere, and is put back, hidden, afterwards."""
        outermost = self._parking is None
        if outermost:
            hidden = not win32.is_visible(self.hwnd)
            rect = win32.window_rect(self.hwnd) if hidden else None
            if rect is not None and rect[0] <= win32.OFFSCREEN_X + 100:
                rect = (100, 100) + tuple(rect[2:])     # an interrupted run left it parked: give it a place on the screen
            self._parking = {"hidden": hidden, "rect": rect}
            if hidden:
                win32.move_offscreen(self.hwnd)
        try:
            yield self._parking["hidden"]
        finally:
            if outermost:
                parking, self._parking = self._parking, None
                if parking["hidden"]:
                    put_back = True
                    if win32.is_visible(self.hwnd):
                        win32.hide(self.hwnd)
                        note = {"kind": "main_window", "title": win32.get_text(self.hwnd, timeout_ms=200),
                                "message": "MMD showed its main window on its own", "buttons": []}
                        if self._gone(self.hwnd, 5.0):
                            self.events.append(dict(note, action="hidden again"))
                        else:
                            # still shown: brought back now it would be on the screen.  It stays parked; the next
                            # operation (or window show) gives it a place on the screen again
                            self.events.append(dict(note, action="still visible, left parked"))
                            put_back = False
                    if put_back:
                        win32.move_window(self.hwnd, *parking["rect"][:2])

    def _keep(self, events):
        self.events.extend(e for e in events if e.get("action") != "left open")

    def take_events(self):
        events, self.events = self.events, []
        return events

    def shield(self):
        """context manager: keep the user's foreground while this instance is driven (guard.FocusShield)"""
        return guard.FocusShield(self.pid)

    def wait_quiet(self, timeout=None):
        return self._run(None, None, timeout)

    def _command(self, wparam, lparam=None, handlers=None, timeout=None, done=None):
        return self._run(("send", self.hwnd, win32.WM_COMMAND, wparam, lparam), handlers, timeout, done)

    def click(self, cid, handlers=None, **kw):
        return self._command(win32.command_wparam(cid), self.ctl(cid), handlers, **kw)

    def menu(self, mid, handlers=None, **kw):
        return self._command(mid, None, handlers, **kw)

    def enter(self, cid, text):
        """type a value into an input box and commit it with Enter"""
        hwnd = self.ctl(cid)
        win32.set_text(hwnd, text)
        win32.post_enter(hwnd)
        self.wait_quiet()

    def select_combo(self, cid, index):
        hwnd = self.ctl(cid)
        win32.send(hwnd, win32.CB_SETCURSEL, index)
        return self._command(win32.command_wparam(cid, win32.CBN_SELCHANGE), hwnd)

    def set_check(self, cid, value):
        hwnd = self.ctl(cid)
        if win32.button_checked(hwnd) != bool(value):
            win32.send(hwnd, win32.BM_SETCHECK, 1 if value else 0)
            self._command(win32.command_wparam(cid), hwnd)

    def drop(self, path, handlers=None, timeout=None):
        handle = win32.make_drop_handle([os.path.normpath(path)])
        return self._run(("post", self.hwnd, win32.WM_DROPFILES, handle, None), handlers, timeout)

    @staticmethod
    def _fill_file_dialog(path):
        path = os.path.normpath(path)       # a file dialog rejects forward slashes
        filled = set()

        def handler(dialog):
            if dialog.hwnd in filled:
                # handed back by the guard: still open and idle after its OK.  The new-style save dialog
                # refuses a name it cannot use (characters such as ? or *) with nothing but a balloon tip,
                # which never becomes a window of its own, and clears its box.  One that still shows the
                # name is merely slow (a network drive, a scan) and is given more time
                edit = dialog.file_name_edit()
                if edit is not None and win32.get_text(edit["hwnd"]) == path:
                    return False
                cancel = dialog.find_button(2)
                if cancel is not None:
                    win32.post(cancel["hwnd"], win32.BM_CLICK)
                else:
                    win32.post(dialog.hwnd, win32.WM_COMMAND, win32.IDCANCEL, None)
                closed = Mmd._gone(dialog.hwnd, 5.0)
                raise MmdError("the file dialog refused %s: it stayed open after OK (a name with characters "
                               "Windows does not allow in file names, or a place it cannot write to)%s"
                               % (path, "" if closed else "; the dialog is still open"))
            edit = dialog.file_name_edit()
            button = dialog.find_button(1)
            if edit is None or button is None:
                return False
            win32.set_text(edit["hwnd"], path)
            if win32.get_text(edit["hwnd"]) != path:
                return False
            time.sleep(0.05)
            win32.post(button["hwnd"], win32.BM_CLICK)
            filled.add(dialog.hwnd)
            return "file name entered"
        return handler

    @staticmethod
    @contextlib.contextmanager
    def _quoting(said):
        """a timeout raised inside quotes the notices MMD showed meanwhile (what it said is the clue)"""
        try:
            yield
        except OperationTimeout as exc:
            if said and exc.args:
                exc.args = ("%s (MMD said: %s)" % (exc.args[0], " / ".join(said)),) + exc.args[1:]
            raise

    @staticmethod
    def _closed_by_writer(path, timeout=10.0):
        """wait until the program writing `path` has closed it: an AVI gets its final header on close, and a
        file still open for writing cannot be opened for appending"""
        deadline = time.monotonic() + timeout
        while True:
            try:
                with open(path, "ab"):
                    return True
            except PermissionError:
                if time.monotonic() > deadline:
                    return False
                time.sleep(0.05)

    @staticmethod
    def _gone(hwnd, timeout):
        """wait until a window is destroyed or no longer shown; False when it is still there"""
        deadline = time.monotonic() + timeout
        while win32.is_window(hwnd) and win32.is_visible(hwnd):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def _file_handlers(self, path, said=None):
        """handlers for an operation that goes through a file dialog.

        A message the file dialog opens on top of itself (a folder that does not exist, a device
        name) means it refuses the name: it is read, closed together with the file dialog, and the
        operation fails with the dialog's own words instead of hanging.  A yes/no question of the
        file dialog (replace an existing file) is answered はい.  A notice MMD itself shows meanwhile
        is closed with its OK and its text collected in `said`, so that a failure which follows can
        quote it; a yes/no question of MMD's own is not guessed at and is reported as pending."""
        said = said if said is not None else []

        def on_message(dialog):
            text = dialog.message.strip()
            owner = win32.owner_window(dialog.hwnd)
            parent = guard.describe(owner) if owner and owner != self.hwnd else None
            from_file_dialog = parent is not None and parent.kind == "file_dialog"
            if dialog.find_button(6) is not None:
                if not from_file_dialog:
                    raise DialogPending([dialog])
                guard.click(dialog, 6)
                said.append(text)
                return "yes"
            for cid in (1, 2):                   # some MMD message boxes give their OK the id 2
                if dialog.find_button(cid) is not None:
                    guard.click(dialog, cid)
                    break
            else:
                raise DialogPending([dialog])
            if not from_file_dialog:
                said.append(text)
                return "ok"
            self._gone(dialog.hwnd, 3.0)
            cancel = parent.find_button(2)
            if cancel is not None:
                win32.post(cancel["hwnd"], win32.BM_CLICK)
            else:
                win32.post(owner, win32.WM_COMMAND, win32.IDCANCEL, None)
            closed = self._gone(owner, 5.0)
            raise MmdError("the file dialog refused %s: %s%s" % (
                path, text or "(no message)", "" if closed else " (the file dialog is still open)"))
        return {"file_dialog": self._fill_file_dialog(path), "message": on_message}

    @staticmethod
    def _not_written(path, said):
        return MmdError("MMD did not write %s%s" % (path, (": " + " / ".join(said)) if said else ""))

    @staticmethod
    def _edit(dialog, cid):
        """the hwnd of an edit box of a dialog, or None while the dialog is not built yet"""
        control = dialog.find_control(cid, "Edit")
        return None if control is None else control["hwnd"]

    @staticmethod
    def _filled(dialog, *cids):
        """True once MMD has put its own values into these boxes: ours must go in after that, not before"""
        for cid in cids:
            hwnd = Mmd._edit(dialog, cid)
            if hwnd is None or not win32.get_text(hwnd).strip():
                return False
        return True

    @staticmethod
    def _put(dialog, cid, value):
        """write a value into an edit box of a dialog; False when the box is missing or did not take it"""
        hwnd = Mmd._edit(dialog, cid)
        if hwnd is None:
            return False
        win32.set_text(hwnd, str(value))
        return win32.get_text(hwnd) == str(value)

    @staticmethod
    def _press(button, action, title=None):
        """handler that presses a button; with a title, only for the dialog that carries it"""
        def handler(dialog):
            if title is not None and dialog.title != title:
                raise DialogPending([dialog])
            guard.click(dialog, button)
            return action
        return handler

    def _temp_path(self, name):
        folder = os.path.join(home_dir(), "tmp")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "%d-%s" % (self.pid, name))

    # ---- state --------------------------------------------------------------------------------

    def _model_items(self):
        return win32.combo_items(self.ctl(Ctl.MODEL_LIST))

    def models(self):
        return self._model_items()[1:]

    def frame(self):
        return int(self.text(Ctl.FRAME).strip() or 0)

    def _project_path(self):
        match = _TITLE_PATH.match(win32.get_text(self.hwnd))
        return match.group(1) if match else None

    def state(self):
        items = self._model_items()
        cur = win32.combo_selection(self.ctl(Ctl.MODEL_LIST))
        return {
            "pid": self.pid,
            "hwnd": self.hwnd,
            "minimized": win32.is_iconic(self.hwnd),
            "visible": win32.is_visible(self.hwnd),
            "project_path": self._project_path(),
            "mode": "model" if cur > 0 else "camera",
            "models": items[1:],
            "selected_model": items[cur] if cur > 0 else None,
            "selected_model_index": cur - 1 if cur > 0 else None,
            "frame": self.frame(),
            "playing": self.playing(),
            "accessories": self.accessories(),
            "dialogs": self.dialogs(),
        }

    # ---- models -------------------------------------------------------------------------------

    def _model_combo_index(self, target):
        """None -> camera/light/accessory entry, int -> model index, str -> model name"""
        items = self._model_items()
        if target is None:
            return 0
        if isinstance(target, int):
            if not 0 <= target < len(items) - 1:
                raise MmdError("model index %d is out of range (%d models)" % (target, len(items) - 1))
            return target + 1
        for i, name in enumerate(items[1:]):
            if name == target:
                return i + 1
        raise MmdError("no model named %r (loaded: %s)" % (target, ", ".join(items[1:]) or "none"))

    def select_model(self, target):
        self.require_ready()
        index = self._model_combo_index(target)
        if win32.combo_selection(self.ctl(Ctl.MODEL_LIST)) != index:
            self.select_combo(Ctl.MODEL_LIST, index)
        return self.state()

    def load_model(self, path):
        path = check_input_file(path, _MODEL_EXTENSIONS, "a model")
        self.require_ready()
        before = self.models()
        info = {}

        def on_info(dialog):
            info["comment"] = dialog.message
            guard.click(dialog, 1)
            return "ok"

        events = self.drop(path, {"model_info": on_info})
        after = self.models()
        if len(after) != len(before) + 1:
            raise MmdError("MMD did not load the model: %s (dialogs: %s)" % (path, events))
        return {"name": after[-1], "index": len(after) - 1, "comment": info.get("comment", "")}

    def delete_model(self, target=None):
        self.require_ready()
        if target is not None:
            self.select_model(target)
        state = self.state()
        if state["mode"] != "model":
            raise MmdError("select a model first")
        self.click(Ctl.MODEL_DELETE, {"message": self._press(1, "ok", title="モデル削除")})
        after = self.models()
        if len(after) != len(state["models"]) - 1:
            raise MmdError("MMD did not delete the model")
        return {"deleted": state["selected_model"], "models": after}

    def set_model_visible(self, visible, target=None):
        self.require_ready()
        if target is not None:
            self.select_model(target)
        if self.state()["mode"] != "model":
            raise MmdError("select a model first")
        self.set_check(Ctl.MODEL_VISIBLE, visible)
        self.click(Ctl.MODEL_REGISTER)
        return {"visible": win32.button_checked(self.ctl(Ctl.MODEL_VISIBLE))}

    def model_info(self, target=None):
        """bones (parents, flags, IK and append links), morphs (panel, kind) and display frames of a model,
        read from its .pmx / .pmd file: MMD's window shows nothing but the bone names.  target is the path
        of such a file, or a loaded model (name, 0-based index, None = the selected one) whose path the
        project holds.  Reading the project saves the working copy, so for a project opened by hand the
        file has to be given."""
        from .formats import pmd, pmx
        looks_like_a_path = isinstance(target, str) and (
            os.path.splitext(target)[1].lower() in _MODEL_EXTENSIONS or "/" in target or os.sep in target)
        if looks_like_a_path:
            # missing, of another kind or out of the code page: said here, before the project gets saved
            path = check_input_file(target, _MODEL_EXTENSIONS, "a model")
        else:
            try:
                summary = self.dump(keys=False)
            except MmdError as exc:
                raise MmdError("%s. Or read the model file itself: mmd model info FILE.pmx" % exc)
            models = summary["models"]
            if target is None:
                index = summary["selected_model"]
                if index is None:
                    raise MmdError("select a model first (mmd model select NAME), or give the model file")
            elif isinstance(target, int):
                if not 0 <= target < len(models):
                    raise MmdError("model index %d is out of range (%d models)" % (target, len(models)))
                index = target
            else:
                found = [m["index"] for m in models if m["name"] == target]
                if not found:
                    raise MmdError("no model named %r (loaded: %s)" % (target, ", ".join(m["name"] for m in models) or "none"))
                index = found[0]
            path = models[index]["path"]
            if not os.path.isfile(path):
                raise MmdError("the file of model %r is no longer where MMD loaded it from: %s" % (models[index]["name"], path))
        result = {"path": path}
        result.update((pmd if path.lower().endswith(".pmd") else pmx).load(path).to_json())
        return result

    # ---- frames -------------------------------------------------------------------------------

    def set_frame(self, number):
        number = int(number)
        if number < 0:
            raise ValueError("frame must be 0 or more")
        self.require_ready()
        box = self.ctl(Ctl.BOOKMARK)
        bookmark = win32.get_text(box)
        win32.set_text(box, str(number))
        self.click(Ctl.BOOKMARK_GO)
        win32.set_text(box, bookmark)
        got = self.frame()
        if got != number:
            raise MmdError("MMD went to frame %d instead of %d" % (got, number))
        return got

    def step_frame(self, delta):
        return self.set_frame(max(0, self.frame() + int(delta)))

    def go_first(self):
        self.require_ready()
        self.click(Ctl.FRAME_FIRST)
        return self.frame()

    def go_last(self):
        self.require_ready()
        self.click(Ctl.FRAME_LAST)
        return self.frame()

    def jump_key(self, forward=True):
        """go to the next / previous key frame of the selected rows"""
        self.require_ready()
        self.click(Ctl.KEY_NEXT if forward else Ctl.KEY_PREV)
        return self.frame()

    # ---- camera and light ---------------------------------------------------------------------

    @contextlib.contextmanager
    def _camera_mode(self):
        combo = self.ctl(Ctl.MODEL_LIST)
        previous = win32.combo_selection(combo)
        if previous != 0:
            self.select_combo(Ctl.MODEL_LIST, 0)
        try:
            yield
        finally:
            if previous > 0:
                self.select_combo(Ctl.MODEL_LIST, previous)

    def _floats(self, *cids):
        return [_num(self.text(cid).strip() or 0) for cid in cids]

    def _read_camera(self):
        return {"pos": self._floats(Ctl.VALUE_X, Ctl.VALUE_Y, Ctl.VALUE_Z),
                "rot": self._floats(Ctl.VALUE_RX, Ctl.VALUE_RY, Ctl.VALUE_RZ),
                "distance": self._floats(Ctl.VALUE_DISTANCE)[0],
                "fov": int(float(self.text(Ctl.CAMERA_FOV).strip() or 0)),
                "perspective": win32.button_checked(self.ctl(Ctl.CAMERA_PERSPECTIVE))}

    def camera(self):
        self.require_ready()
        with self._camera_mode():
            return self._read_camera()

    def _require_register_or_camera_mode(self, register, what):
        if not register and win32.combo_selection(self.ctl(Ctl.MODEL_LIST)) > 0:
            raise MmdError("a model is selected: MMD drops %s values that are not registered as soon as the "
                           "model is selected again. Add --register, or switch with: mmd model select camera"
                           % what)

    def set_camera(self, pos=None, rot=None, distance=None, fov=None, perspective=None, register=False, interp=None):
        """change the camera and, with register, key it at the current frame.  interp (x1, y1, x2, y2, each
        0-127) gives the key that curve on all six channels: the register button cannot be told a curve, so
        the key is then registered by loading a one-key camera motion built from the values the boxes show."""
        self.require_ready()
        curve = None
        if interp is not None:
            if not register:
                raise ValueError("--interp needs --register (the curve belongs to the registered key)")
            curve = vmd.check_curve(interp)
        self._require_register_or_camera_mode(register, "camera")
        with self._camera_mode():
            for cids, values in (((Ctl.VALUE_X, Ctl.VALUE_Y, Ctl.VALUE_Z), pos),
                                 ((Ctl.VALUE_RX, Ctl.VALUE_RY, Ctl.VALUE_RZ), rot)):
                if values is not None:
                    for cid, value in zip(cids, values):
                        self.enter(cid, _format(value))
            if distance is not None:
                self.enter(Ctl.VALUE_DISTANCE, _format(distance))
            if fov is not None:
                self.enter(Ctl.CAMERA_FOV, str(int(fov)))
            if perspective is not None:
                self.set_check(Ctl.CAMERA_PERSPECTIVE, perspective)
            if register and curve is None:
                self.click(Ctl.CAMERA_REGISTER)
            evidence = self._register_camera_through_motion(curve) if register and curve is not None else {}
            result = self._read_camera()
            if curve is not None:
                result["interp"] = list(curve)
                result.update(evidence)
            return result

    def _register_camera_through_motion(self, curve):
        """key the camera at the current frame with an interpolation curve: a one-key camera motion (frame 0,
        which MMD places at the current frame) made from what the boxes show, then checked in the project"""
        from .motion_edit import camera_key_from_ui
        path = self._temp_path("camera.vmd")
        vmd.dump(vmd.Motion.for_camera(cameras=[camera_key_from_ui(self._read_camera(), curve)]), path)
        self._drop_motion(path)
        frame_now = self.frame()
        camera = self._project()["camera"]
        # the project is the evidence: a key at this frame whose 24 interpolation bytes are made of the curve
        # (at frame 0 the init record always exists, so its curve is what tells whether anything was registered)
        at_frame = [f for f in [camera["init"]] + camera["keys"] if f["frame"] == frame_now]
        if not at_frame:
            raise MmdError("MMD did not register a camera key at frame %d" % frame_now)
        key = at_frame[-1]
        if set(key["interpolation"]) != set(curve):
            raise MmdError("the camera key at frame %d does not carry the curve %s (the project holds %s)"
                           % (frame_now, list(curve), list(key["interpolation"])))
        return {"interp_in_project": list(key["interpolation"]), "distance_in_project": key["distance"]}

    def _read_light(self):
        return {"rgb": [int(v) for v in self._floats(Ctl.LIGHT_R, Ctl.LIGHT_G, Ctl.LIGHT_B)],
                "dir": self._floats(Ctl.LIGHT_X, Ctl.LIGHT_Y, Ctl.LIGHT_Z)}

    def light(self):
        self.require_ready()
        return self._read_light()

    def set_light(self, rgb=None, direction=None, register=False):
        self.require_ready()
        self._require_register_or_camera_mode(register, "light")
        with self._camera_mode():
            if rgb is not None:
                for cid, value in zip((Ctl.LIGHT_R, Ctl.LIGHT_G, Ctl.LIGHT_B), rgb):
                    self.enter(cid, str(int(value)))
            if direction is not None:
                for cid, value in zip((Ctl.LIGHT_X, Ctl.LIGHT_Y, Ctl.LIGHT_Z), direction):
                    self.enter(cid, _format(value))
            if register:
                self.click(Ctl.LIGHT_REGISTER)
            return self._read_light()

    # ---- project files ------------------------------------------------------------------------

    def _record(self):
        return load_state()["projects"].get(str(self.pid))

    def _set_record(self, record):
        def change(state):
            if record is None:
                state["projects"].pop(str(self.pid), None)
            else:
                state["projects"][str(self.pid)] = record
        update_state(change)

    def forget_project(self):
        self._set_record(None)

    def _new_work_path(self):
        folder = os.path.join(home_dir(), "sessions")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "%d-%d.pmm" % (self.pid, int(time.time() * 1000)))

    def _save_as(self, path):
        said = []
        with self._quoting(said), keeping_the_old_file(path):
            self.menu(Menu.SAVE_AS, self._file_handlers(path, said))
            if not os.path.exists(path):
                raise self._not_written(path, said)

    def _save_project(self, allow_foreign=False):
        """save the project MMD has open and return the file that now holds the current state"""
        current = self.state()["project_path"]
        record = self._record()
        if current is None:
            work = self._new_work_path()
            self._save_as(work)
            self._set_record({"work": work, "origin": record.get("origin") if record else None})
            return work
        if (record and _same_path(current, record["work"])) or self.in_place or allow_foreign:
            before = os.stat(current).st_mtime_ns if os.path.exists(current) else None
            self.menu(Menu.SAVE, done=lambda: os.path.exists(current) and os.stat(current).st_mtime_ns != before)
            return current
        raise MmdError("this project (%s) was not opened through mmd-cli; reading it needs a save. "
                       "Pass --in-place to save into that file, or reopen it with: mmd open FILE" % current)

    def _project(self):
        return pmm.load(self._save_project())

    def dump(self, keys=True, in_place=None):
        self.require_ready()
        previous = self.in_place
        if in_place is not None:
            self.in_place = in_place
        try:
            return scene.summarize(self._project(), keys=keys)
        finally:
            self.in_place = previous

    def save(self, path=None):
        self.require_ready()
        if path:
            target = check_output_file(path)
            current = self.state()["project_path"]
            record = self._record()
            ours = record is not None and current is not None and _same_path(current, record["work"])
            if current is not None and not ours and not _same_path(target, current):
                # a project opened by hand is to go somewhere else: MMD's own "save as".  The file it had
                # open is not written (without a path, or with its own path, the overwrite is what was asked)
                self._save_as(target)
                self._set_record(None)
                return {"path": target, "bytes": os.path.getsize(target)}
        source = self._save_project(allow_foreign=True)
        record = self._record()
        if record and _same_path(source, record["work"]):
            target = check_output_file(path) if path else record.get("origin")
            if not target:
                raise MmdError("this project has no file yet: give one with  mmd save FILE.pmm")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            part = target + ".part"
            shutil.copyfile(source, part)
            os.replace(part, target)
            record["origin"] = target
            self._set_record(record)
            return {"path": target, "bytes": os.path.getsize(target)}
        if path and not _same_path(path, source):
            target = check_output_file(path)
            self._save_as(target)
            return {"path": target, "bytes": os.path.getsize(target)}
        return {"path": source, "bytes": os.path.getsize(source)}

    def new_project(self):
        self.require_ready()
        self.menu(Menu.NEW, {"new_confirm": self._press(1, "ok")})
        self._set_record(None)
        return self.state()

    def open_project(self, path):
        path = check_input_file(path, (".pmm",), "a project")
        self.require_ready()
        work = self._new_work_path()
        shutil.copyfile(path, work)
        def opened():
            current = self._project_path()
            return current is not None and _same_path(current, work)

        said = []
        try:
            # MMD does not ask before discarding the current project; a big project keeps loading
            # after the command has returned, so the title is what tells that it is open
            self.menu(Menu.OPEN, self._file_handlers(work, said), done=opened)
        except OperationTimeout:
            raise MmdError("MMD did not open the project (its title shows %r)%s"
                           % (self._project_path(), (": " + " / ".join(said)) if said else ""))
        self.wait_quiet()
        self._set_record({"work": work, "origin": path})
        return self.state()

    # ---- motion, pose, bones, morphs ----------------------------------------------------------

    def _drop_motion(self, path):
        confirmed = []

        def on_confirm(dialog):
            confirmed.append(dialog.message)
            guard.click(dialog, 1)
            return "ok"

        self.drop(path, {"motion_confirm": on_confirm})
        return bool(confirmed)

    def load_motion(self, path, frame=None, model=None):
        path = check_input_file(path, (".vmd",), "a motion")
        self.require_ready()
        motion = vmd.load(path)
        if motion.is_camera:
            self.select_model(None)
        elif model is not None:
            self.select_model(model)
        state = self.state()
        if not motion.is_camera and state["mode"] != "model":
            raise MmdError("select the model that receives the motion first (mmd model select NAME)")
        if frame is not None:
            self.set_frame(frame)
        confirmed = self._drop_motion(path)
        return {"kind": "camera" if motion.is_camera else "model", "model": state["selected_model"],
                "frame": self.frame(), "bones": len(motion.bones), "morphs": len(motion.morphs),
                "cameras": len(motion.cameras), "lights": len(motion.lights), "confirmed": confirmed}

    def _selected_model(self, model=None):
        """(index, raw model from a fresh save) of the model that bone/morph commands work on"""
        if model is not None:
            self.select_model(model)
        state = self.state()
        if state["mode"] != "model":
            raise MmdError("select a model first (mmd model select NAME)")
        index = state["selected_model_index"]
        return index, self._project()["models"][index]

    def bones(self, model=None):
        self.require_ready()
        return list(self._selected_model(model)[1]["bones"])

    def morphs(self, model=None):
        self.require_ready()
        return list(self._selected_model(model)[1]["morphs"])

    @staticmethod
    def _bone_values(raw, name):
        if name not in raw["bones"]:
            raise MmdError("model %r has no bone %r" % (raw["name"], name))
        cur = raw["bone_current"][raw["bones"].index(name)]
        return cur["position"], cur["rotation"]

    def bone(self, name, model=None):
        self.require_ready()
        position, rotation = self._bone_values(self._selected_model(model)[1], name)
        return {"bone": name, "pos": _vec(position), "rot": _vec(mathutil.quat_to_ui(rotation))}

    def set_bone(self, name, pos=None, rot=None, quat=None, frame=None, model=None, interp=None):
        """register a key for one bone at the current (or given) frame.  rot is in degrees as shown in the MMD window,
        quat is (x, y, z, w); whatever is not given keeps its value at that frame.  interp (x1, y1, x2, y2, each 0-127)
        is the key's interpolation curve on all four channels (default: the linear 20 20 107 107)."""
        self.require_ready()
        curve = vmd.check_curve(interp) if interp is not None else None
        if model is not None:
            self.select_model(model)
        if frame is not None:
            self.set_frame(frame)
        index, raw = self._selected_model()
        position, rotation = self._bone_values(raw, name)
        if pos is not None:
            position = tuple(float(v) for v in pos)
        if quat is not None:
            rotation = tuple(float(v) for v in quat)
        elif rot is not None:
            rotation = mathutil.ui_to_quat(*rot)
        interpolation = vmd.bone_interpolation(curve) if curve is not None else vmd.DEFAULT_BONE_INTERPOLATION
        key = vmd.BoneKey(name, 0, position, rotation, interpolation)
        path = self._temp_path("bone.vmd")
        vmd.dump(vmd.Motion(model_name=raw["name"], bones=[key]), path)
        self._drop_motion(path)
        frame_now = self.frame()
        after = self._project()["models"][index]
        owner = after["bones"].index(name)
        registered = [f for f in after["bone_init"] + after["bone_keys"]
                      if f["bone"] == owner and f["frame"] == frame_now]
        if not registered:
            raise MmdError("MMD did not register a key for bone %r at frame %d" % (name, frame_now))
        position, rotation = self._bone_values(after, name)
        result = {"bone": name, "frame": frame_now, "pos": _vec(position),
                  "rot": _vec(mathutil.quat_to_ui(rotation))}
        if curve is not None:
            # the 16 interpolation bytes the project file holds for the key, as they are (evidence for a live check)
            result["interp"] = list(curve)
            result["interp_in_project"] = list(registered[0]["interpolation"])
        return result

    def morph(self, name, model=None):
        self.require_ready()
        raw = self._selected_model(model)[1]
        if name not in raw["morphs"]:
            raise MmdError("model %r has no morph %r" % (raw["name"], name))
        return {"morph": name, "value": _num(raw["morph_current"][raw["morphs"].index(name)])}

    def set_morph(self, name, value, frame=None, model=None):
        self.require_ready()
        if model is not None:
            self.select_model(model)
        if frame is not None:
            self.set_frame(frame)
        index, raw = self._selected_model()
        if name not in raw["morphs"]:
            raise MmdError("model %r has no morph %r" % (raw["name"], name))
        path = self._temp_path("morph.vmd")
        vmd.dump(vmd.Motion(model_name=raw["name"], morphs=[vmd.MorphKey(name, 0, float(value))]), path)
        self._drop_motion(path)
        after = self._project()["models"][index]
        return {"morph": name, "frame": self.frame(),
                "value": _num(after["morph_current"][after["morphs"].index(name)])}

    def load_pose(self, path, register=False, model=None):
        path = check_input_file(path, (".vpd",), "a pose")
        self.require_ready()
        if model is not None:
            self.select_model(model)
        state = self.state()
        if state["mode"] != "model":
            raise MmdError("select the model that receives the pose first (mmd model select NAME)")
        pose = vpd.load(path)
        if register:
            # a dropped .vpd only moves the bones; keys are registered by loading the same values as a motion
            keys = [vmd.BoneKey(b.name, 0, b.position, b.rotation) for b in pose.bones]
            motion_path = self._temp_path("pose.vmd")
            vmd.dump(vmd.Motion(model_name=state["selected_model"], bones=keys), motion_path)
            self._drop_motion(motion_path)
        else:
            self.drop(path)
        return {"model": state["selected_model"], "frame": self.frame(), "bones": len(pose.bones),
                "registered": bool(register)}

    def _save_through_menu(self, menu_id, path, extension):
        if not path.lower().endswith(extension):
            raise MmdError("the file name must end with %s" % extension)
        self.require_ready()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        said = []
        with self._quoting(said), keeping_the_old_file(path):
            self.menu(menu_id, self._file_handlers(path, said), done=self._written(path))
            if not os.path.exists(path):
                raise self._not_written(path, said)
        return path

    def save_motion(self, path):
        """write the selected model's motion as .vmd (camera + light motion while no model is selected).
        MMD writes only the key frames that are selected in its frame panel, so they are all selected first."""
        path = check_output_file(path)
        state = self.state()
        kind = "model" if state["mode"] == "model" else "camera"
        if kind == "model":
            for mid in (Menu.SELECT_ALL_BONE_FRAMES, Menu.SELECT_ALL_MORPH_FRAMES, Menu.SELECT_ALL_CONFIG_FRAMES):
                self.menu(mid)
        else:
            for mid in (Menu.SELECT_ALL_CAMERA_FRAMES, Menu.SELECT_ALL_LIGHT_FRAMES):
                self.menu(mid)
        self._save_through_menu(Menu.MOTION_SAVE, path, ".vmd")
        motion = vmd.load(path)
        return {"path": path, "kind": kind, "model": state["selected_model"], "bytes": os.path.getsize(path),
                "bones": len(motion.bones), "morphs": len(motion.morphs), "cameras": len(motion.cameras),
                "lights": len(motion.lights)}

    def save_pose(self, path):
        """write the selected model's current pose as .vpd"""
        path = check_output_file(path)
        state = self.state()
        if state["mode"] != "model":
            raise MmdError("select a model first (mmd model select NAME)")
        self.click(Ctl.BONE_SELECT_ALL)          # MMD writes the pose of the selected bones only
        self._save_through_menu(Menu.POSE_SAVE, path, ".vpd")
        pose = vpd.load(path)
        return {"path": path, "model": state["selected_model"], "bytes": os.path.getsize(path), "bones": len(pose.bones)}

    def render_codecs(self):
        """the video codecs the AVI dialog offers on this machine (nothing is written)"""
        self.require_ready()
        found = []

        def on_settings(dialog):
            control = dialog.find_control(AviDialog.CODEC, "ComboBox")
            if control is None:
                return False
            found.extend(win32.combo_items(control["hwnd"]))
            guard.click(dialog, 2)
            return "read and cancelled"

        probe = self._temp_path("codecs.avi")
        if os.path.exists(probe):
            os.remove(probe)
        handlers = dict(self._file_handlers(probe), avi_settings=on_settings)
        self.menu(Menu.AVI_OUT, handlers, done=lambda: bool(found))
        if os.path.exists(probe):
            os.remove(probe)
        return found

    # ---- sound and accessories ----------------------------------------------------------------

    def load_wav(self, path):
        path = check_input_file(path, (".wav",), "a sound file")
        self.require_ready()
        self.drop(path)
        return {"path": path}

    def accessories(self):
        return win32.combo_items(self.ctl(Ctl.ACC_LIST))

    def load_accessory(self, path):
        path = check_input_file(path, (".x", ".vac"), "an accessory")
        self.require_ready()
        before = self.accessories()
        self.drop(path)
        after = self.accessories()
        if len(after) != len(before) + 1:
            raise MmdError("MMD did not load the accessory: %s" % path)
        return {"name": after[-1], "index": len(after) - 1}

    def _accessory_index(self, target):
        names = self.accessories()
        if isinstance(target, int):
            if not 0 <= target < len(names):
                raise MmdError("accessory index %d is out of range (%d accessories)" % (target, len(names)))
            return target
        if target in names:
            return names.index(target)
        raise MmdError("no accessory named %r (loaded: %s)" % (target, ", ".join(names) or "none"))

    def _read_accessory(self):
        values = self._floats(Ctl.ACC_X, Ctl.ACC_Y, Ctl.ACC_Z, Ctl.ACC_RX, Ctl.ACC_RY, Ctl.ACC_RZ,
                              Ctl.ACC_SIZE, Ctl.ACC_TR)
        return {"name": self.text(Ctl.ACC_LIST), "pos": values[0:3], "rot": values[3:6], "scale": values[6],
                "alpha": values[7], "visible": win32.button_checked(self.ctl(Ctl.ACC_VISIBLE)),
                "shadow": win32.button_checked(self.ctl(Ctl.ACC_SHADOW))}

    def accessory(self, target):
        self.require_ready()
        with self._camera_mode():
            self.select_combo(Ctl.ACC_LIST, self._accessory_index(target))
            return self._read_accessory()

    def set_accessory(self, target, pos=None, rot=None, scale=None, alpha=None, visible=None, shadow=None):
        """change an accessory and register the values at the current frame"""
        self.require_ready()
        with self._camera_mode():
            self.select_combo(Ctl.ACC_LIST, self._accessory_index(target))
            for cids, values in (((Ctl.ACC_X, Ctl.ACC_Y, Ctl.ACC_Z), pos),
                                 ((Ctl.ACC_RX, Ctl.ACC_RY, Ctl.ACC_RZ), rot),
                                 ((Ctl.ACC_SIZE,), None if scale is None else (scale,)),
                                 ((Ctl.ACC_TR,), None if alpha is None else (alpha,))):
                if values is not None:
                    for cid, value in zip(cids, values):
                        win32.set_text(self.ctl(cid), _format(value))
            if visible is not None:
                self.set_check(Ctl.ACC_VISIBLE, visible)
            if shadow is not None:
                self.set_check(Ctl.ACC_SHADOW, shadow)
            self.click(Ctl.ACC_REGISTER)
            return dict(self._read_accessory(), frame=self.frame())

    def delete_accessory(self, target):
        self.require_ready()
        with self._camera_mode():
            index = self._accessory_index(target)
            before = self.accessories()
            self.select_combo(Ctl.ACC_LIST, index)
            self.click(Ctl.ACC_DELETE, {"message": self._press(1, "ok", title="アクセサリ削除")})
            after = self.accessories()
            if len(after) != len(before) - 1:
                raise MmdError("MMD did not delete the accessory")
            return {"deleted": before[index], "accessories": after}

    # ---- output -------------------------------------------------------------------------------

    def output_size(self):
        self.require_ready()
        size = {}

        def on_size(dialog):
            if not self._filled(dialog, OutputSizeDialog.WIDTH, OutputSizeDialog.HEIGHT):
                return False
            size["value"] = [int(win32.get_text(self._edit(dialog, OutputSizeDialog.WIDTH))),
                             int(win32.get_text(self._edit(dialog, OutputSizeDialog.HEIGHT)))]
            guard.click(dialog, 2)
            return "read"

        self.menu(Menu.OUTPUT_SIZE, {"output_size": on_size})
        return size["value"]

    def set_output_size(self, width, height):
        self.require_ready()

        def on_size(dialog):
            if not self._filled(dialog, OutputSizeDialog.WIDTH, OutputSizeDialog.HEIGHT):
                return False
            if not (self._put(dialog, OutputSizeDialog.WIDTH, int(width))
                    and self._put(dialog, OutputSizeDialog.HEIGHT, int(height))):
                return False
            guard.click(dialog, 1)
            return "size entered"

        self.menu(Menu.OUTPUT_SIZE, {"output_size": on_size})
        return [int(width), int(height)]

    @staticmethod
    def _written(path):
        """done-condition: the file exists and has kept its size for a moment"""
        last = {"size": -1, "since": 0.0}

        def done():
            try:
                size = os.path.getsize(path)
            except OSError:
                return False
            now = time.monotonic()
            if size != last["size"]:
                last["size"], last["since"] = size, now
                return False
            return size > 0 and now - last["since"] > 0.2
        return done

    def render_image(self, path, size=None, timeout=None):
        path = check_output_file(path)
        if os.path.splitext(path)[1].lower() not in _IMAGE_EXTENSIONS:
            raise MmdError("image file must end with one of %s" % ", ".join(_IMAGE_EXTENSIONS))
        self.require_ready()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if size is not None:
            self.set_output_size(*size)
        said = []
        handlers = dict(self._file_handlers(path, said), recording=lambda dialog: "recording")
        with self._quoting(said), keeping_the_old_file(path), self._camera_mode():   # through the scene camera
            self.menu(Menu.IMAGE_OUT, handlers, timeout=timeout, done=self._written(path))
        return {"path": path, "size": _image_size(path), "bytes": os.path.getsize(path), "frame": self.frame()}

    def render_avi(self, path, start, end, fps=30, size=None, codec=None, timeout=None):
        path = check_output_file(path)
        if not path.lower().endswith(".avi"):
            raise MmdError("video file must end with .avi")
        start, end = int(start), int(end)
        if start < 0 or end < start:
            raise ValueError("need 0 <= start <= end")
        self.require_ready()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if timeout is None:
            timeout = max(self.timeout, 60.0 + 2.0 * (end - start + 1))
        used = {}
        problem = []

        if size is not None:
            self.set_output_size(*size)     # the AVI is written at the output size; the dialog's own boxes only show it

        def on_settings(dialog):
            if not self._filled(dialog, AviDialog.WIDTH, AviDialog.HEIGHT, AviDialog.FPS):
                return False                # MMD has not filled the dialog yet
            control = dialog.find_control(AviDialog.CODEC, "ComboBox")
            if control is None:
                return False
            combo = control["hwnd"]
            if codec is not None:
                names = win32.combo_items(combo)
                matches = [i for i, n in enumerate(names) if codec.lower() in n.lower()]
                if not matches:
                    problem.append("no codec matches %r (available: %s)" % (codec, ", ".join(names)))
                    guard.click(dialog, 2)
                    return "cancelled"
                win32.send(combo, win32.CB_SETCURSEL, matches[0])
                win32.send(dialog.hwnd, win32.WM_COMMAND,
                           win32.command_wparam(AviDialog.CODEC, win32.CBN_SELCHANGE), combo)
            for cid, value in ((AviDialog.FPS, int(fps)), (AviDialog.FRAME_FROM, start), (AviDialog.FRAME_TO, end)):
                if not self._put(dialog, cid, value):
                    return False
            used["codec"] = win32.get_text(combo)
            guard.click(dialog, 1)
            return "settings entered"

        def done():
            return bool(problem) or finished()

        finished = self._written(path)
        said = []
        handlers = dict(self._file_handlers(path, said), avi_settings=on_settings, recording=lambda dialog: "recording")
        with self._quoting(said), keeping_the_old_file(path), self._camera_mode():
            self.menu(Menu.AVI_OUT, handlers, timeout=timeout, done=done)
            if problem:
                raise MmdError(problem[0])
            self._closed_by_writer(path)        # the frame count goes into the header when MMD closes the file
            header = _avi_info(path)
            asked = {"frames": expected_avi_frames(start, end, fps), "fps": int(fps)}
            if size is not None:
                asked["size"] = [int(size[0]), int(size[1])]
            wrong = {k: (asked[k], header.get(k)) for k in asked if header.get(k) != asked[k]}
            if wrong:
                raise MmdError("MMD wrote the video differently from what was asked: %s"
                               % ", ".join("%s asked %s, written %s" % (k, a, w) for k, (a, w) in wrong.items()))
        return dict(header, path=path, codec=used.get("codec"), bytes=os.path.getsize(path))

    # ---- playback -----------------------------------------------------------------------------

    def play(self, start=None, end=None, wait=False, from_current=False, stay=False, repeat=False,
             timeout=None):
        """start playback.  start/end fill the range boxes (empty = whole motion).  Without
        from_current MMD starts at the range start; without stay it jumps back to the frame it was
        on when playback ends.  The frame box of MMD is not updated while it plays."""
        self.require_ready()
        if (start is None) != (end is None):
            raise ValueError("give both --from and --to, or neither")
        if wait and repeat:
            raise ValueError("--wait never returns with --repeat")
        win32.set_text(self.ctl(Ctl.PLAY_FROM), "" if start is None else str(int(start)))
        win32.set_text(self.ctl(Ctl.PLAY_TO), "" if end is None else str(int(end)))
        self.set_check(Ctl.PLAY_FROM_CURRENT, from_current)
        self.set_check(Ctl.PLAY_STAY_AT_STOP, stay)
        self.set_check(Ctl.PLAY_REPEAT, repeat)
        button = self.ctl(Ctl.PLAY)
        win32.post(button, win32.BM_CLICK)
        self._wait_for(self.playing, 10.0, "MMD did not start playing")
        if wait:
            self._wait_for(lambda: not self.playing(), timeout or self.timeout, "playback did not finish in time")
            self.wait_quiet()
        return {"playing": self.playing(), "frame": self.frame()}

    def stop(self):
        self.require_ready(allow_playing=True)
        if self.playing():
            win32.post(self.ctl(Ctl.PLAY), win32.BM_CLICK)
            self._wait_for(lambda: not self.playing(), 10.0, "MMD did not stop playing")
            self.wait_quiet()
        return {"playing": self.playing(), "frame": self.frame()}

    @staticmethod
    def _wait_for(condition, timeout, message):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise OperationTimeout(message)
            time.sleep(0.02)

    # ---- generic access -----------------------------------------------------------------------

    def menu_items(self):
        return win32.menu_items(self.hwnd)

    def menu_click(self, mid):
        self.require_ready()
        known = {i["id"]: i for i in self.menu_items()}
        if mid not in known:
            raise MmdError("no menu item has id %d (see: mmd menu list)" % mid)
        if known[mid]["grayed"]:
            raise MmdError("menu item %d (%s) is disabled right now" % (mid, " > ".join(known[mid]["path"])))
        self.menu(mid)
        return {i["id"]: i for i in self.menu_items()}[mid]

    def menu_set(self, mid, on):
        """bring a menu item with a check mark to `on`: clicked only when it is in the other state, so a batch
        does not depend on how MMD was left (the check marks of the display menus outlive `new`).  An item
        without a mark is only clicked when it is one of CHECK_ITEMS: clicking a command to find out that it
        is not a toggle would already have run it."""
        self.require_ready()
        known = {i["id"]: i for i in self.menu_items()}
        if mid not in known:
            raise MmdError("no menu item has id %d (see: mmd menu list)" % mid)
        item = known[mid]
        name = " > ".join(item["path"])
        if item["grayed"]:
            raise MmdError("menu item %d (%s) is disabled right now" % (mid, name))
        if bool(item["checked"]) == bool(on):
            return dict(item, changed=False)
        if not item["checked"] and mid not in CHECK_ITEMS:
            raise MmdError("menu item %d (%s) shows no check mark and is not a known toggle of MMD v9.32; "
                           "use `menu click %d` if it is one" % (mid, name, mid))
        self.menu(mid)
        after = {i["id"]: i for i in self.menu_items()}[mid]
        if bool(after["checked"]) != bool(on):
            raise MmdError("menu item %d (%s) did not change: it is still %s"
                           % (mid, name, "checked" if after["checked"] else "unchecked"))
        return dict(after, changed=True)

    def _describe_control(self, cid):
        hwnd = self.ctl(cid)
        cls = win32.class_name(hwnd)
        info = {"id": cid, "class": cls, "text": win32.get_text(hwnd), "visible": win32.is_visible(hwnd),
                "enabled": win32.is_enabled(hwnd)}
        if cls == "ComboBox":
            info["items"] = win32.combo_items(hwnd)
            info["selected"] = win32.combo_selection(hwnd)
        elif cls == "Button":
            info["checked"] = win32.button_checked(hwnd)
        elif cls == "msctls_trackbar32":
            info.update(win32.trackbar(hwnd))
        return info

    def controls(self):
        self.ctl(Ctl.FRAME)
        return [self._describe_control(cid) for cid in sorted(self._controls)]

    def control_get(self, cid):
        return self._describe_control(cid)

    def control_click(self, cid):
        self.require_ready()
        self.click(cid)
        return self._describe_control(cid)

    def control_set(self, cid, value, commit=True):
        """Edit: text (Enter is sent when commit is true).  ComboBox: index or item text.
        Button: check state.  Trackbar: position."""
        self.require_ready()
        hwnd = self.ctl(cid)
        cls = win32.class_name(hwnd)
        if cls == "Edit":
            if commit:
                self.enter(cid, str(value))
            else:
                win32.set_text(hwnd, str(value))
        elif cls == "ComboBox":
            items = win32.combo_items(hwnd)
            if isinstance(value, int) or (isinstance(value, str) and value.lstrip("-").isdigit() and value not in items):
                index = int(value)
            elif value in items:
                index = items.index(value)
            else:
                raise MmdError("combo box %d has no item %r" % (cid, value))
            if not 0 <= index < len(items):
                raise MmdError("combo box %d has %d items" % (cid, len(items)))
            self.select_combo(cid, index)
        elif cls == "Button":
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "on", "yes")
            self.set_check(cid, bool(value))
        elif cls == "msctls_trackbar32":
            position = int(value)
            win32.send(hwnd, win32.TBM_SETPOS, 1, position)
            message = win32.WM_VSCROLL if win32.style(hwnd) & 0x0002 else win32.WM_HSCROLL
            for code in (win32.TB_THUMBPOSITION, win32.TB_ENDTRACK):
                self._run(("send", self.hwnd, message, ((position & 0xFFFF) << 16) | code, hwnd))
        else:
            raise MmdError("control %d (%s) cannot be set" % (cid, cls))
        return self._describe_control(cid)

    # ---- dialogs ------------------------------------------------------------------------------

    def dialogs(self):
        """dialogs MMD is waiting in.  Looking does not hide them: one that a person opened by hand
        stays on screen ("hidden" tells which ones the CLI has put away)."""
        return [dict(d.to_json(), hidden=win32.is_hidden(d.hwnd), enabled=win32.is_enabled(d.hwnd))
                for d in guard.open_dialogs(self.pid, self.hwnd, hide=False)]

    def _pending_dialog(self):
        """the dialog that can take an answer: when a dialog has opened another one on top of
        itself, the outer one is disabled until the inner one is closed"""
        pending = guard.open_dialogs(self.pid, self.hwnd, hide=False)
        if not pending:
            raise MmdError("no dialog is open")
        enabled = [d for d in pending if win32.is_enabled(d.hwnd)]
        return (enabled or pending)[-1]

    def _wait_closed(self, dialog):
        self._wait_for(lambda: not (win32.is_window(dialog.hwnd) and win32.is_visible(dialog.hwnd)), 10.0,
                       "the dialog did not close")
        return {"closed": dialog.title, "dialogs": self.dialogs()}

    def dialog_click(self, button):
        dialog = self._pending_dialog()
        if isinstance(button, str) and button.isdigit():
            button = int(button)
        try:
            guard.click(dialog, button)
        except KeyError:
            raise MmdError("dialog %r has no button %r (buttons: %s)"
                           % (dialog.title, button, ", ".join(t for _, t in dialog.buttons)))
        return self._wait_closed(dialog)

    def dialog_close(self):
        dialog = self._pending_dialog()
        if dialog.find_button(2) is not None:
            guard.click(dialog, 2)
        else:
            win32.post(dialog.hwnd, win32.WM_CLOSE)
        return self._wait_closed(dialog)

    def dialog_show(self, x=100, y=100):
        """put pending dialogs back on screen for a person to answer"""
        shown = []
        for i, dialog in enumerate(guard.open_dialogs(self.pid, self.hwnd, hide=False)):
            win32.reveal_window(dialog.hwnd, x + 40 * i, y + 40 * i)
            shown.append(dialog.to_json())
        return shown

    # ---- window and process -------------------------------------------------------------------

    def _window(self):
        return {"minimized": win32.is_iconic(self.hwnd), "visible": win32.is_visible(self.hwnd)}

    def minimize(self):
        win32.minimize_no_activate(self.hwnd)
        self._wait_for(lambda: win32.is_iconic(self.hwnd), 5.0, "the window did not minimize")
        return self._window()

    def hide(self):
        """take the window off the screen and the taskbar; it keeps working"""
        win32.hide(self.hwnd)
        self._wait_for(lambda: not win32.is_visible(self.hwnd), 5.0, "the window did not hide")
        return self._window()

    def show(self):
        """put a hidden window back (minimized, so it still does not cover anything)"""
        if not win32.is_visible(self.hwnd):
            if win32.is_hidden(self.hwnd):              # parked off-screen by an operation that was cut short
                win32.move_window(self.hwnd, 100, 100)
            win32.minimize_no_activate(self.hwnd)
            self._wait_for(lambda: win32.is_visible(self.hwnd), 5.0, "the window did not show")
        return self._window()

    def quit(self, force=False, timeout=20.0):
        if win32.is_window(self.hwnd):
            win32.post(self.hwnd, win32.WM_COMMAND, Menu.EXIT, None)
        deadline = time.monotonic() + timeout
        answered = set()
        with win32.timer_resolution():          # the exit confirmation is hidden on the next pass: keep passes short
            while win32.process_alive(self.pid) is not False and time.monotonic() < deadline:
                for dialog in guard.open_dialogs(self.pid, self.hwnd):
                    if dialog.hwnd in answered:
                        continue
                    answered.add(dialog.hwnd)
                    if dialog.kind == "message" and dialog.find_button(1) is not None:
                        guard.click(dialog, 1)
                    elif dialog.kind == "message" and dialog.find_button(6) is not None:
                        guard.click(dialog, 6)
                    elif not force:
                        raise DialogPending([dialog])
                time.sleep(0.002)
        if win32.process_alive(self.pid) is not False:
            if not force:
                raise OperationTimeout("MMD did not exit within %.0f s (use --force)" % timeout)
            win32.terminate_process(self.pid)
            self._wait_for(lambda: win32.process_alive(self.pid) is False, 10.0, "MMD could not be terminated")
        forget_instance(self.pid)
        return {"pid": self.pid, "running": False}


def _riff_chunks(data):
    """(tag, payload) for the chunks laid end to end in `data`; a LIST's payload starts with its kind"""
    pos = 0
    while pos + 8 <= len(data):
        tag, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        yield tag, data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)


def expected_avi_frames(start, end, fps):
    """how many frames MMD writes for motion frames start..end at `fps`: the motion's frames are 30 fps
    units, so 60 fps gives two per motion frame (measured: 2400..2820 at 60 fps gave 842)"""
    return int(round((end - start + 1) * int(fps) / 30.0))


def _avi_info(path):
    """size, frame count and frame rate from the AVI header list (hdrl); empty when the file is not an AVI.
    The list is walked, not searched: pixel data may contain any bytes."""
    with open(path, "rb") as f:
        head = f.read(20)
        if head[:4] != b"RIFF" or head[8:12] != b"AVI " or head[12:16] != b"LIST":
            return {}
        size = struct.unpack_from("<I", head, 16)[0]
        if size > (4 << 20):
            return {}
        hdrl = f.read(size)
    if hdrl[:4] != b"hdrl":
        return {}
    info, total = {}, None
    for tag, payload in _riff_chunks(hdrl[4:]):
        if tag == b"avih" and len(payload) >= 40:
            micro = struct.unpack_from("<I", payload, 0)[0]
            info = {"size": list(struct.unpack_from("<II", payload, 32)), "frames": struct.unpack_from("<I", payload, 16)[0],
                    "fps": round(1e6 / micro) if micro else None}
        elif tag == b"LIST" and payload[:4] == b"odml":
            # past 1 GB the file goes on in AVIX segments and avih counts only the first; OpenDML has them all
            for inner, data in _riff_chunks(payload[4:]):
                if inner == b"dmlh" and len(data) >= 4:
                    total = struct.unpack_from("<I", data, 0)[0]
    if info and total:
        info["frames"] = total
    return info


def _image_size(path):
    with open(path, "rb") as f:
        head = f.read(32)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return list(struct.unpack(">II", head[16:24]))
    if head[:2] == b"BM":
        width, height = struct.unpack("<ii", head[18:26])
        return [width, abs(height)]
    return None
