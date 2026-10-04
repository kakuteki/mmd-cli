"""Guard.run and FocusShield against a fake win32: no MMD, no real windows."""
import contextlib
import time
import unittest
from unittest import mock

try:
    from mmd_cli import guard
except ImportError:          # not on Windows
    guard = None

MAIN, OTHER_APP, THIRD_APP = 1, 50, 60
PID, OTHER_PID, THIRD_PID = 7, 9, 11


class FakeWin32:
    """a table of top-level windows; child controls are (id, class, text) tuples with made-up hwnds"""
    WM_NULL = 0x0000
    WM_COMMAND = 0x0111
    BM_CLICK = 0x00F5

    def __init__(self):
        self.windows = {}
        self.posted = []
        self.foreground = OTHER_APP
        self.locks = []
        self.sends = 0
        self.fail_first_sends = 0
        self.add(MAIN, PID, "Polygon Movie Maker", "MikuMikuDance")
        self.add(OTHER_APP, OTHER_PID, "CASCADIA_HOSTING_WINDOW_CLASS", "terminal")
        self.add(THIRD_APP, THIRD_PID, "Chrome_WidgetWin_1", "browser")

    def add(self, hwnd, pid, cls, title, controls=(), visible=True, enabled=True, responsive=True):
        self.windows[hwnd] = {"pid": pid, "cls": cls, "title": title, "controls": list(controls),
                              "visible": visible, "hidden": False, "enabled": enabled, "responsive": responsive}

    def _owner(self, hwnd):
        return self.windows.get(hwnd // 1000) if hwnd >= 1000 else None

    def _control(self, hwnd):
        return self._owner(hwnd)["controls"][hwnd % 1000 - 1]

    # ---- what guard.py calls ----
    def find_windows(self, pid=None, cls=None):
        return [h for h, w in self.windows.items()
                if (pid is None or w["pid"] == pid) and (cls is None or w["cls"] == cls)]

    def class_name(self, hwnd):
        if hwnd >= 1000:
            return self._control(hwnd)[1]
        return self.windows[hwnd]["cls"] if hwnd in self.windows else ""

    def get_text(self, hwnd, timeout_ms=None):
        if hwnd >= 1000:
            return self._control(hwnd)[2]
        return self.windows[hwnd]["title"] if hwnd in self.windows else ""

    def child_windows(self, hwnd):
        return [hwnd * 1000 + i + 1 for i in range(len(self.windows[hwnd]["controls"]))]

    def control_id(self, hwnd):
        return self._control(hwnd)[0]

    def is_window(self, hwnd):
        return hwnd in self.windows or (hwnd >= 1000 and hwnd // 1000 in self.windows)

    def is_visible(self, hwnd):
        if hwnd >= 1000:
            return True
        return hwnd in self.windows and self.windows[hwnd]["visible"]

    def is_hidden(self, hwnd):
        return self.windows[hwnd]["hidden"]

    def hide_window(self, hwnd):
        self.windows[hwnd]["hidden"] = True

    def move_offscreen(self, hwnd):
        pass

    def hide(self, hwnd):
        self.windows[hwnd]["visible"] = False

    def is_enabled(self, hwnd):
        return self.windows[hwnd]["enabled"]

    def send(self, hwnd, msg, wparam=0, lparam=None, timeout_ms=None, abort_if_hung=True):
        self.sends += 1
        if self.fail_first_sends > 0:
            self.fail_first_sends -= 1
            return None
        return 0 if self.windows[hwnd]["responsive"] else None

    def post(self, hwnd, msg, wparam=0, lparam=None):
        self.posted.append((hwnd, msg, wparam))
        return True

    @staticmethod
    def command_wparam(cid, code=0):
        return cid | (code << 16)

    @contextlib.contextmanager
    def timer_resolution(self):
        yield

    def foreground_window(self):
        return self.foreground

    def window_pid(self, hwnd):
        return self.windows[hwnd]["pid"] if hwnd in self.windows else 0

    def lock_foreground(self, on):
        self.locks.append(on)
        return True

    def give_foreground_back(self, hwnd):
        self.foreground = hwnd
        return True


OK_BUTTON = (1, "Button", "OK")
MESSAGE = [(0, "Static", "something happened"), OK_BUTTON]
FILE_DIALOG = [(1001, "Edit", ""), (1, "Button", "保存(&S)"), (2, "Button", "キャンセル")]


@unittest.skipUnless(guard is not None, "needs Windows")
class GuardRunTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeWin32()
        patches = [mock.patch.object(guard, "win32", self.fake),
                   mock.patch.object(guard, "SETTLE_SECONDS", 0.2),
                   mock.patch.object(guard, "LINGER_SECONDS", 0.2),
                   mock.patch.object(guard, "RETRY_SECONDS", 0.4)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.guard = guard.Guard(PID, MAIN)

    def dialog(self, hwnd, title, controls, **kw):
        self.fake.add(hwnd, PID, "#32770", title, controls, **kw)

    def test_no_dialog_finishes_after_quiet_rounds(self):
        self.fake.fail_first_sends = 3
        self.assertEqual(self.guard.run(None, {}, timeout=2.0), [])
        self.assertGreaterEqual(self.fake.sends, 3 + guard.QUIET_ROUNDS)

    def test_a_dialog_nobody_handles_is_hidden_and_reported_after_settle(self):
        self.dialog(2, "何か", MESSAGE)
        started = time.monotonic()
        with self.assertRaises(guard.DialogPending) as ctx:
            self.guard.run(None, {}, timeout=5.0)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual([d.title for d in ctx.exception.dialogs], ["何か"])
        self.assertEqual(ctx.exception.events[-1]["action"], "left open")
        self.assertTrue(self.fake.windows[2]["hidden"])

    def test_a_handler_that_returns_false_is_called_again(self):
        self.dialog(2, "何か", MESSAGE)
        calls = []

        def handler(dialog):
            calls.append(dialog.hwnd)
            if len(calls) < 2:
                return False
            del self.fake.windows[2]
            return "closed"

        events = self.guard.run(None, {"message": handler}, timeout=2.0)
        self.assertEqual(calls, [2, 2])
        self.assertEqual([e["action"] for e in events], ["closed"])

    def test_a_handler_that_never_understands_the_dialog_gives_up_before_the_timeout(self):
        self.dialog(2, "何か", MESSAGE)
        started = time.monotonic()
        with self.assertRaises(guard.DialogPending) as ctx:
            self.guard.run(None, {"message": lambda dialog: False}, timeout=5.0)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(ctx.exception.events[-1]["action"], "not understood")

    def test_a_file_dialog_still_open_after_its_answer_is_handed_back(self):
        self.dialog(2, "名前を付けて保存", FILE_DIALOG)
        calls = []

        def handler(dialog):
            calls.append(time.monotonic())
            if len(calls) == 1:
                return "file name entered"
            del self.fake.windows[2]
            return "cancelled"

        events = self.guard.run(None, {"file_dialog": handler}, timeout=5.0)
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(calls[1] - calls[0], 0.2)
        self.assertEqual([e["action"] for e in events], ["file name entered", "cancelled"])

    def test_a_file_dialog_that_stays_after_the_second_answer_is_reported(self):
        self.dialog(2, "名前を付けて保存", FILE_DIALOG)
        with self.assertRaises(guard.DialogPending) as ctx:
            self.guard.run(None, {"file_dialog": lambda dialog: "file name entered"}, timeout=5.0)
        self.assertEqual(ctx.exception.events[-1]["action"], "still open after being answered")

    def test_a_disabled_file_dialog_has_something_on_top_and_is_not_handed_back(self):
        self.dialog(2, "名前を付けて保存", FILE_DIALOG, enabled=False)
        calls = []

        def handler(dialog):
            calls.append(1)
            return "file name entered"

        with self.assertRaises(guard.DialogPending):
            self.guard.run(None, {"file_dialog": handler}, timeout=0.8)
        self.assertEqual(len(calls), 1)

    def test_mmds_own_dialog_that_stays_open_is_left_alone(self):
        # the model information dialog stays while the model loads: no second answer, no early failure
        self.dialog(2, "モデル情報", MESSAGE)
        calls = []

        def handler(dialog):
            calls.append(1)
            return "ok"

        started = time.monotonic()
        with self.assertRaises(guard.DialogPending):
            self.guard.run(None, {"model_info": handler}, timeout=0.8)
        self.assertGreaterEqual(time.monotonic() - started, 0.8)
        self.assertEqual(len(calls), 1)

    def test_a_hidden_main_window_that_mmd_shows_is_hidden_again(self):
        self.fake.windows[MAIN]["visible"] = False
        real_send = self.fake.send

        def send(*args, **kw):
            if self.fake.sends == 2:                    # MMD shows its window in the middle of the work
                self.fake.windows[MAIN]["visible"] = True
            return real_send(*args, **kw)
        self.fake.send = send
        events = self.guard.run(None, {}, timeout=2.0, keep_hidden=True)
        self.assertFalse(self.fake.windows[MAIN]["visible"])
        self.assertEqual([e["action"] for e in events], ["hidden again"])

    def test_running_out_of_time_without_a_dialog_is_a_timeout(self):
        with self.assertRaises(guard.OperationTimeout):
            self.guard.run(None, {}, timeout=0.3, done=lambda: False)

    def test_click_posts_a_command_to_the_dialog_and_a_click_to_a_file_dialog_button(self):
        self.dialog(2, "何か", MESSAGE)
        self.dialog(3, "名前を付けて保存", FILE_DIALOG)
        guard.click(guard.describe(2), 1)
        guard.click(guard.describe(3), 2)
        self.assertEqual(self.fake.posted, [(2, FakeWin32.WM_COMMAND, 1), (3003, FakeWin32.BM_CLICK, 0)])


@unittest.skipUnless(guard is not None, "needs Windows")
class FocusShieldTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeWin32()
        p = mock.patch.object(guard, "win32", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_nested_shields_share_the_outer_one(self):
        with guard.FocusShield(PID) as outer:
            with guard.FocusShield(PID) as inner:
                self.assertIs(inner, outer)
            self.assertIsNotNone(guard.FocusShield._outer)
        self.assertIsNone(guard.FocusShield._outer)
        self.assertEqual(self.fake.locks, [True, False])

    def test_the_foreground_is_handed_back_only_when_mmd_takes_it(self):
        with guard.FocusShield(PID) as shield:
            self.fake.foreground = THIRD_APP           # another application: none of our business
            time.sleep(0.05)
            self.assertEqual(self.fake.foreground, THIRD_APP)
            self.fake.foreground = MAIN                 # MMD: handed straight back to where it was
            time.sleep(0.05)
            self.assertEqual(self.fake.foreground, OTHER_APP)
        self.assertEqual([e["foreground_taken_by"] for e in shield.events], ["Polygon Movie Maker"])

    def test_nothing_is_restored_when_mmd_was_already_in_front(self):
        self.fake.foreground = MAIN
        with guard.FocusShield(PID) as shield:
            self.fake.foreground = THIRD_APP
            time.sleep(0.03)
            self.fake.foreground = MAIN
            time.sleep(0.05)
        self.assertEqual(self.fake.foreground, MAIN)
        self.assertEqual(shield.events, [])


if __name__ == "__main__":
    unittest.main()
