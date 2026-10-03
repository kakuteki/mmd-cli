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


class DialogPending(Exception):
    """MMD is waiting in a dialog that nobody answered.  The dialog stays open (and hidden)."""

    def __init__(self, dialogs, events=None):
        self.dialogs = dialogs
        self.events = events or []
        titles = ", ".join("%s" % d.title for d in dialogs)
        super().__init__("MMD is waiting in a dialog: " + titles)


class OperationTimeout(Exception):
    pass


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

    def run(self, trigger=None, handlers=None, timeout=60.0, done=None):
        """trigger: None, ("send", hwnd, msg, wparam, lparam) or ("post", hwnd, msg, wparam, lparam).

        handlers maps a dialog kind to a callable(dialog).  The callable answers the dialog and
        returns a short action name, or False when the dialog is not ready yet (it is retried).
        A visible dialog without a handler raises DialogPending.

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
        quiet = 0
        deadline = time.monotonic() + timeout
        with win32.timer_resolution():
            while True:
                visible = 0
                for hwnd in dialog_windows(self.pid, self.main):
                    if hwnd not in seen:
                        win32.hide_window(hwnd)
                        seen[hwnd] = "new"
                    if not win32.is_visible(hwnd):
                        continue
                    visible += 1
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
                        retry_at[hwnd] = now + 0.02
                        continue
                    seen[hwnd] = "handled"
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
