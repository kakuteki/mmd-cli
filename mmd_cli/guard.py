"""Supervise an MMD operation: trigger it, keep every dialog it opens invisible, answer the
dialogs the caller expects, and report the ones it does not.

A dialog is caught while it is still being created (1 ms polling), made fully transparent and
moved off-screen, so it never appears on the user's screen.
"""
import threading
import time

from . import win32
from .dialogs import Dialog

DIALOG_CLASSES = ("#32770", "RecWindow")
QUIET_ROUNDS = 5
SETTLE_SECONDS = 1.0
LINGER_SECONDS = 2.0
RETRY_SECONDS = 5.0


class DialogPending(Exception):
    """MMD is waiting in a dialog that nobody answered.  The dialog stays open (and hidden)."""

    def __init__(self, dialogs, events=None):
        self.dialogs = dialogs
        self.events = events or []
        titles = ", ".join("%s" % d.title for d in dialogs)
        super().__init__("MMD is waiting in a dialog: " + titles)


class OperationTimeout(Exception):
    pass


class FocusShield:
    """Keep the user's foreground window where it is while MMD is being driven.

    When the terminal that runs this command is the foreground window, Windows treats this process
    as allowed to take the foreground, and a synchronous message to MMD passes that right along:
    a dialog MMD opens for us could then come to the front and keep the keyboard focus.  Two
    defences: the foreground is locked for the duration (LockSetForegroundWindow, which only a
    process with the right can do, i.e. exactly when the danger exists), and a watcher thread hands
    the foreground straight back should an MMD window take it anyway.  Nested uses share the
    outermost shield; its `events` list what happened.
    """
    _outer = None

    def __init__(self, pid):
        self.pid = pid
        self.events = []
        self.locked = False
        self.fg_before = None
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if FocusShield._outer is not None:
            return FocusShield._outer
        FocusShield._outer = self
        fg = win32.foreground_window()
        self.fg_before = fg if fg and win32.window_pid(fg) != self.pid else None
        self.locked = win32.lock_foreground(True)
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def _check(self):
        fg = win32.foreground_window()
        if self.fg_before and fg and fg != self.fg_before and self.pid and win32.window_pid(fg) == self.pid:
            if self.locked:
                win32.lock_foreground(False)
            restored = win32.give_foreground_back(self.fg_before)
            if self.locked:
                win32.lock_foreground(True)
            self.events.append({"foreground_taken_by": win32.class_name(fg),
                                "title": win32.get_text(fg, timeout_ms=200), "restored": restored})

    def _watch(self):
        with win32.timer_resolution():
            while not self._stop.is_set():
                self._check()
                time.sleep(0.003)

    def __exit__(self, *exc):
        if FocusShield._outer is not self:
            return False
        self._stop.set()
        self._thread.join(2.0)
        self._check()
        if self.locked:
            win32.lock_foreground(False)
        FocusShield._outer = None
        return False


def describe(hwnd):
    controls = []
    for child in win32.child_windows(hwnd):
        controls.append({"id": win32.control_id(child), "cls": win32.class_name(child),
                         "text": win32.get_text(child, timeout_ms=500), "hwnd": child,
                         "visible": win32.is_visible(child)})
    return Dialog(hwnd=hwnd, cls=win32.class_name(hwnd), title=win32.get_text(hwnd, timeout_ms=500),
                  controls=controls)


def dialog_windows(pid, main_hwnd):
    return [h for h in win32.find_windows(pid=pid)
            if h != main_hwnd and win32.class_name(h) in DIALOG_CLASSES]


def open_dialogs(pid, main_hwnd, hide=True):
    """the dialogs currently shown by the process (hidden from the user as a side effect)"""
    found = []
    for hwnd in dialog_windows(pid, main_hwnd):
        if hide and not win32.is_hidden(hwnd):
            win32.hide_window(hwnd)
        if win32.is_visible(hwnd):
            found.append(describe(hwnd))
    return found


def click(dialog, button):
    """press a button of a dialog (label prefix or control id) without activating the dialog"""
    control = dialog.find_button(button)
    if control is None:
        raise KeyError("no button %r in dialog %r" % (button, dialog.title))
    if dialog.kind == "file_dialog":
        win32.post(control["hwnd"], win32.BM_CLICK)
    else:
        win32.post(dialog.hwnd, win32.WM_COMMAND, win32.command_wparam(control["id"]), control["hwnd"])
    return control


class Guard:
    def __init__(self, pid, main_hwnd):
        self.pid = pid
        self.main = main_hwnd

    def run(self, trigger=None, handlers=None, timeout=60.0, done=None, keep_hidden=False):
        """trigger: None, ("send", hwnd, msg, wparam, lparam) or ("post", hwnd, msg, wparam, lparam).

        handlers maps a dialog kind to a callable(dialog).  The callable answers the dialog and
        returns a short action name, or False when the dialog is not ready yet (it is retried).
        A visible dialog without a handler raises DialogPending.  A file dialog that is still open,
        idle and enabled LINGER_SECONDS after its name was entered has refused the name (the new-style
        save dialog does that without a word; an accepted name closes it at once): it is handed to the
        handler again, which cancels it and reports; should it still stay, DialogPending is raised
        instead of waiting out the timeout.  MMD's own dialogs may stay open while it works (the model
        information dialog does so during the load), so they are left alone.  keep_hidden: the main window
        is hidden and must stay so; should MMD show it on its own (it does when it starts writing an AVI)
        it is hidden again at once.

        The operation is over when the sent message has returned (send), or MMD has answered
        QUIET_ROUNDS pings in a row (post / None), no dialog is open, and done() is true.
        """
        handlers = handlers or {}
        events = []
        seen = {}
        worker = None
        if trigger is not None:
            mode, hwnd, msg, wparam, lparam = trigger
            if mode == "send":
                worker = threading.Thread(
                    target=win32.send, args=(hwnd, msg, wparam, lparam),
                    kwargs={"timeout_ms": int(timeout * 1000) + 5000, "abort_if_hung": False}, daemon=True)
                worker.start()
            elif mode == "post":
                if not win32.post(hwnd, msg, wparam, lparam):
                    raise OSError("PostMessage failed")
            else:
                raise ValueError(mode)
        needs_quiet = worker is None
        first_visible = {}
        retry_at = {}
        handled_at = {}
        kinds = {}
        lingered = set()
        quiet = 0
        deadline = time.monotonic() + timeout
        with FocusShield(self.pid), win32.timer_resolution():
            while True:
                if keep_hidden and win32.is_visible(self.main):
                    win32.hide(self.main)
                    events.append({"kind": "main_window", "title": win32.get_text(self.main, timeout_ms=200),
                                   "message": "MMD showed its main window on its own", "buttons": [],
                                   "action": "hidden again"})
                    keep_hidden = False
                visible = 0
                for hwnd in dialog_windows(self.pid, self.main):
                    if hwnd not in seen:
                        win32.hide_window(hwnd)
                        seen[hwnd] = "new"
                    if not win32.is_visible(hwnd):
                        continue
                    visible += 1
                    if seen[hwnd] == "handled" and kinds[hwnd] == "file_dialog" and self._lingers(hwnd, handled_at[hwnd]):
                        if hwnd in lingered:
                            dialog = describe(hwnd)
                            events.append(dict(dialog.to_json(), action="still open after being answered"))
                            raise DialogPending([dialog], events)
                        lingered.add(hwnd)
                        seen[hwnd] = "new"
                        retry_at.pop(hwnd, None)
                    if seen[hwnd] != "new":
                        continue
                    win32.move_offscreen(hwnd)      # file dialogs put themselves back on screen while starting
                    now = time.monotonic()
                    first_visible.setdefault(hwnd, now)
                    if now < retry_at.get(hwnd, 0.0):
                        continue
                    dialog = describe(hwnd)
                    handler = handlers.get(dialog.kind)
                    if handler is None:
                        # a dialog can be visible before its title and controls exist: look again for a moment
                        if now - first_visible[hwnd] < SETTLE_SECONDS:
                            retry_at[hwnd] = now + 0.02
                            continue
                        events.append(dict(dialog.to_json(), action="left open"))
                        raise DialogPending([dialog], events)
                    action = handler(dialog)
                    if action is False:
                        if now - first_visible[hwnd] > RETRY_SECONDS:
                            # the controls the handler needs never came (another version of the dialog?)
                            events.append(dict(dialog.to_json(), action="not understood"))
                            raise DialogPending([dialog], events)
                        retry_at[hwnd] = now + 0.02
                        continue
                    seen[hwnd] = "handled"
                    handled_at[hwnd] = time.monotonic()
                    kinds[hwnd] = dialog.kind
                    events.append(dict(dialog.to_json(), action=action if isinstance(action, str) else "handled"))
                sent_returned = worker is None or not worker.is_alive()
                if sent_returned and visible == 0 and (done is None or done()):
                    if not needs_quiet:
                        break
                    if win32.is_enabled(self.main) and win32.send(self.main, win32.WM_NULL, timeout_ms=100) is not None:
                        quiet += 1
                        if quiet >= QUIET_ROUNDS:
                            break
                    else:
                        quiet = 0
                else:
                    quiet = 0
                if time.monotonic() > deadline:
                    pending = open_dialogs(self.pid, self.main)
                    if pending:
                        raise DialogPending(pending, events)
                    raise OperationTimeout("MMD did not finish within %.0f s" % timeout)
                time.sleep(0.001)
        return events

    @staticmethod
    def _lingers(hwnd, since):
        """answered a while ago, yet still shown, enabled (nothing on top of it) and idle (one busy
        inside its OK handler does not answer WM_NULL, and is left alone)"""
        if time.monotonic() - since < LINGER_SECONDS:
            return False
        return win32.is_enabled(hwnd) and win32.send(hwnd, win32.WM_NULL, timeout_ms=100) is not None
