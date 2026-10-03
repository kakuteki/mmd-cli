"""Operate one running MikuMikuDance instance through window messages.

Nothing here activates or restores the MMD window.  Every operation waits for MMD to finish
(see guard.Guard.run) and reads the result back from MMD.
"""
import contextlib
import json
import os
import re
import shutil
import struct
import time

from . import guard, mathutil, scene, win32
from .formats import pmm, vmd, vpd
from .guard import DialogPending, OperationTimeout
from .ids import AviDialog, CONTROL_COUNT, Ctl, MAIN_WINDOW_CLASS, Menu, OutputSizeDialog

_TITLE_PATH = re.compile(r"^MikuMikuDance \[(.*)\]\s*$")
_MODEL_EXTENSIONS = (".pmx", ".pmd")
_IMAGE_EXTENSIONS = (".png", ".bmp", ".jpg", ".dds", ".dib", ".pfm", ".hdr")


class MmdError(Exception):
    pass


# ---- where the CLI keeps its own files -----------------------------------------------------

def home_dir():
    base = os.environ.get("MMD_CLI_HOME")
    if not base:
        base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "mmd-cli")
    base = os.path.abspath(base)        # also turns forward slashes into the ones MMD's file dialogs accept
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
    state["projects"] = {pid: rec for pid, rec in state["projects"].items() if win32.process_alive(int(pid))}
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _state_path())


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
    return _require_ansi(os.path.abspath(path))


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
    while True:
        mains = win32.find_windows(pid=pid, cls=MAIN_WINDOW_CLASS)
        pending = guard.open_dialogs(pid, mains[0] if mains else None)
        if pending:
            raise DialogPending(pending)
        if mains:
            hwnd = mains[0]
            if (len(win32.child_windows(hwnd)) >= CONTROL_COUNT
                    and win32.send(hwnd, win32.WM_NULL, timeout_ms=300) is not None):
                break
        if not win32.process_alive(pid):
            raise MmdError("MMD exited right after it was started")
        if time.monotonic() > deadline:
            raise OperationTimeout("MMD did not become ready within %.0f s" % timeout)
        time.sleep(0.1)
    mmd = Mmd(pid, hwnd)
    mmd.wait_quiet()
    if headless and win32.is_visible(hwnd):
        mmd.hide()
    state = load_state()
    state["current"] = pid
    state["exe"] = exe
    save_state(state)
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
        try:
            events = self.guard.run(trigger, handlers, timeout or self.timeout, done)
        except DialogPending as exc:
            self._keep(exc.events)
            raise
        self._keep(events)
        return events

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

        def handler(dialog):
            edit = dialog.file_name_edit()
            button = dialog.find_button(1)
            if edit is None or button is None:
                return False
            win32.set_text(edit["hwnd"], path)
            if win32.get_text(edit["hwnd"]) != path:
                return False
            time.sleep(0.05)
            win32.post(button["hwnd"], win32.BM_CLICK)
            return "file name entered"
        return handler

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

    def set_camera(self, pos=None, rot=None, distance=None, fov=None, perspective=None, register=False):
        self.require_ready()
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
            if register:
                self.click(Ctl.CAMERA_REGISTER)
            return self._read_camera()

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
        state = load_state()
        if record is None:
            state["projects"].pop(str(self.pid), None)
        else:
            state["projects"][str(self.pid)] = record
        save_state(state)

    def forget_project(self):
        self._set_record(None)

    def _new_work_path(self):
        folder = os.path.join(home_dir(), "sessions")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "%d-%d.pmm" % (self.pid, int(time.time() * 1000)))

    def _save_as(self, path):
        if os.path.exists(path):
            os.remove(path)
        self.menu(Menu.SAVE_AS, {"file_dialog": self._fill_file_dialog(path)})
        if not os.path.exists(path):
            raise MmdError("MMD did not write %s" % path)

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
        source = self._save_project(allow_foreign=True)
        record = self._record()
        if record and _same_path(source, record["work"]):
            target = check_output_file(path) if path else record.get("origin")
            if not target:
                raise MmdError("this project has no file yet: give one with  mmd save FILE.pmm")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
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

        try:
            # MMD does not ask before discarding the current project; a big project keeps loading
            # after the command has returned, so the title is what tells that it is open
            self.menu(Menu.OPEN, {"file_dialog": self._fill_file_dialog(work)}, done=opened)
        except OperationTimeout:
            raise MmdError("MMD did not open the project (its title shows %r)" % self._project_path())
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

    def set_bone(self, name, pos=None, rot=None, quat=None, frame=None, model=None):
        """register a key for one bone at the current (or given) frame.  rot is in degrees as shown in the MMD window,
        quat is (x, y, z, w); whatever is not given keeps its value at that frame."""
        self.require_ready()
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
        key = vmd.BoneKey(name, 0, position, rotation)
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
        return {"bone": name, "frame": frame_now, "pos": _vec(position),
                "rot": _vec(mathutil.quat_to_ui(rotation))}

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
            size["value"] = [int(win32.get_text(dialog.find_control(OutputSizeDialog.WIDTH, "Edit")["hwnd"])),
                             int(win32.get_text(dialog.find_control(OutputSizeDialog.HEIGHT, "Edit")["hwnd"]))]
            guard.click(dialog, 2)
            return "read"

        self.menu(Menu.OUTPUT_SIZE, {"output_size": on_size})
        return size["value"]

    def set_output_size(self, width, height):
        self.require_ready()

        def on_size(dialog):
            win32.set_text(dialog.find_control(OutputSizeDialog.WIDTH, "Edit")["hwnd"], str(int(width)))
            win32.set_text(dialog.find_control(OutputSizeDialog.HEIGHT, "Edit")["hwnd"], str(int(height)))
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
        if os.path.exists(path):
            os.remove(path)
        if size is not None:
            self.set_output_size(*size)
        handlers = {"file_dialog": self._fill_file_dialog(path), "recording": lambda dialog: "recording"}
        with self._camera_mode():       # the picture is taken through the scene camera, not the editing view
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
        if os.path.exists(path):
            os.remove(path)
        if timeout is None:
            timeout = max(self.timeout, 60.0 + 2.0 * (end - start + 1))
        used = {}
        problem = []

        def put(dialog, cid, value):
            win32.set_text(dialog.find_control(cid, "Edit")["hwnd"], str(value))

        def on_settings(dialog):
            combo = dialog.find_control(AviDialog.CODEC, "ComboBox")["hwnd"]
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
            if size is not None:
                put(dialog, AviDialog.WIDTH, int(size[0]))
                put(dialog, AviDialog.HEIGHT, int(size[1]))
            put(dialog, AviDialog.FPS, int(fps))
            put(dialog, AviDialog.FRAME_FROM, start)
            put(dialog, AviDialog.FRAME_TO, end)
            used["codec"] = win32.get_text(combo)
            guard.click(dialog, 1)
            return "settings entered"

        def done():
            return bool(problem) or written()

        written = self._written(path)
        handlers = {"file_dialog": self._fill_file_dialog(path), "avi_settings": on_settings,
                    "recording": lambda dialog: "recording"}
        with self._camera_mode():
            self.menu(Menu.AVI_OUT, handlers, timeout=timeout, done=done)
        if problem:
            raise MmdError(problem[0])
        return {"path": path, "frames": end - start + 1, "fps": int(fps), "codec": used.get("codec"),
                "bytes": os.path.getsize(path)}

    # ---- playback -----------------------------------------------------------------------------

    def play(self, start=None, end=None, wait=False, from_current=False, stay=False, repeat=False,
             timeout=None):
        """start playback.  start/end fill the range boxes (empty = whole motion).  Without
        from_current MMD starts at the range start; without stay it jumps back to the frame it was
        on when playback ends.  The frame box of MMD is not updated while it plays."""
        self.require_ready()
        if (start is None) != (end is None):
            raise ValueError("give both --from and --to, or neither")
        win32.set_text(self.ctl(Ctl.PLAY_FROM), "" if start is None else str(int(start)))
        win32.set_text(self.ctl(Ctl.PLAY_TO), "" if end is None else str(int(end)))
        self.set_check(Ctl.PLAY_FROM_CURRENT, from_current)
        self.set_check(Ctl.PLAY_STAY_AT_STOP, stay)
        self.set_check(Ctl.PLAY_REPEAT, repeat)
        button = self.ctl(Ctl.PLAY)
        win32.post(button, win32.BM_CLICK)
        self._wait_for(self.playing, 10.0, "MMD did not start playing")
        if wait:
            if repeat:
                raise ValueError("--wait never returns with --repeat")
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
            win32.minimize_no_activate(self.hwnd)
            self._wait_for(lambda: win32.is_visible(self.hwnd), 5.0, "the window did not show")
        return self._window()

    def quit(self, force=False, timeout=20.0):
        if win32.is_window(self.hwnd):
            win32.post(self.hwnd, win32.WM_COMMAND, Menu.EXIT, None)
        deadline = time.monotonic() + timeout
        answered = set()
        while win32.process_alive(self.pid) and time.monotonic() < deadline:
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
            time.sleep(0.05)
        if win32.process_alive(self.pid):
            if not force:
                raise OperationTimeout("MMD did not exit within %.0f s (use --force)" % timeout)
            win32.terminate_process(self.pid)
            self._wait_for(lambda: not win32.process_alive(self.pid), 10.0, "MMD could not be terminated")
        state = load_state()
        state["projects"].pop(str(self.pid), None)
        if state.get("current") == self.pid:
            state["current"] = None
        save_state(state)
        return {"pid": self.pid, "running": False}


def _image_size(path):
    with open(path, "rb") as f:
        head = f.read(32)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return list(struct.unpack(">II", head[16:24]))
    if head[:2] == b"BM":
        width, height = struct.unpack("<ii", head[18:26])
        return [width, abs(height)]
    return None
