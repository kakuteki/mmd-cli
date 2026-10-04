"""Mmd methods that can be checked without MMD: a bare instance whose window-facing methods are
replaced, and a temporary home for the state file."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

try:
    from mmd_cli import app, dialogs, guard
    from mmd_cli.ids import Menu
except ImportError:          # not on Windows
    app = None

from tests.test_app import OUTSIDE, outside_code_page


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def bare(**attrs):
    """an Mmd that never talks to a window; attrs replace methods"""
    m = app.Mmd.__new__(app.Mmd)
    m.pid, m.hwnd, m.events, m.in_place, m.timeout, m._controls = 4242, 1, [], False, 1.0, None
    m._parking = None
    m.require_ready = lambda allow_playing=False: None
    for name, value in attrs.items():
        setattr(m, name, value)
    return m


class TempHome(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"MMD_CLI_HOME": os.path.join(self.folder, "home")})
        p.start()
        self.addCleanup(p.stop)

    def path(self, name):
        return os.path.join(self.folder, name)


@unittest.skipUnless(app is not None, "needs Windows")
class SaveSemanticsTest(TempHome):
    def test_saving_a_hand_opened_project_elsewhere_leaves_the_file_it_has_open_alone(self):
        hand, copy = self.path("hand.pmm"), self.path("copy.pmm")
        write(hand, b"old")
        calls = []

        def save_as(path):
            calls.append(path)
            write(path, b"new")

        def menu(*args, **kw):
            raise AssertionError("no menu command may touch the open file: %r" % (args,))

        m = bare(state=lambda: {"project_path": hand}, _save_as=save_as, menu=menu)
        result = m.save(copy)
        self.assertEqual(calls, [copy])
        self.assertEqual(read(hand), b"old")
        self.assertEqual(result, {"path": copy, "bytes": 3})

    def test_saving_a_hand_opened_project_without_a_path_is_the_asked_for_overwrite(self):
        hand = self.path("hand.pmm")
        write(hand, b"old")
        sent = []

        def menu(mid, handlers=None, **kw):
            sent.append(mid)
            write(hand, b"newer")

        m = bare(state=lambda: {"project_path": hand}, menu=menu)
        self.assertEqual(m.save(), {"path": hand, "bytes": 5})
        self.assertEqual(sent, [Menu.SAVE])


@unittest.skipUnless(app is not None, "needs Windows")
class KeepOldFileTest(TempHome):
    """an existing output file must survive a save that MMD does not complete"""

    def test_the_old_file_comes_back_when_mmd_writes_nothing(self):
        path = self.path("dance.vmd")
        write(path, b"old")
        m = bare(menu=lambda *a, **k: None)
        with self.assertRaises(app.MmdError):
            m._save_through_menu(Menu.MOTION_SAVE, path, ".vmd")
        self.assertEqual(read(path), b"old")
        self.assertEqual(os.listdir(self.folder), ["dance.vmd"])

    def test_the_old_file_comes_back_when_the_operation_fails(self):
        path = self.path("dance.vmd")
        write(path, b"old")

        def menu(*a, **k):
            raise guard.OperationTimeout("no")

        m = bare(menu=menu)
        with self.assertRaises(guard.OperationTimeout):
            m._save_through_menu(Menu.MOTION_SAVE, path, ".vmd")
        self.assertEqual(read(path), b"old")
        self.assertEqual(os.listdir(self.folder), ["dance.vmd"])

    def test_the_new_file_takes_the_place_of_the_old_one(self):
        path = self.path("dance.vmd")
        write(path, b"old")
        m = bare(menu=lambda *a, **k: write(path, b"new"))
        self.assertEqual(m._save_through_menu(Menu.MOTION_SAVE, path, ".vmd"), path)
        self.assertEqual(read(path), b"new")
        self.assertEqual(os.listdir(self.folder), ["dance.vmd"])

    def test_a_leftover_old_copy_is_not_deleted_by_the_next_run(self):
        # review 2 (2.1): an interrupted run leaves X.mmdcli-old (the user's original) and a half-written X;
        # the next run must not remove that original on its way
        path = self.path("dance.vmd")
        write(path + ".mmdcli-old", b"original")
        write(path, b"half")
        m = bare(menu=lambda *a, **k: write(path, b"new"))
        m._save_through_menu(Menu.MOTION_SAVE, path, ".vmd")
        self.assertEqual(read(path), b"new")
        self.assertEqual(read(path + ".mmdcli-old"), b"original")
        self.assertEqual(sorted(os.listdir(self.folder)), ["dance.vmd", "dance.vmd.mmdcli-old"])

    def test_an_output_path_that_is_a_folder_is_refused_before_anything_is_renamed(self):
        folder = self.path("shots.png")
        os.mkdir(folder)
        with self.assertRaises(app.MmdError) as ctx:
            app.check_output_file(folder)
        self.assertIn("folder", str(ctx.exception))
        self.assertTrue(os.path.isdir(folder))
        os.mkdir(self.path("taken.vmd"))
        m = bare(menu=lambda *a, **k: None)
        with self.assertRaises(app.MmdError):
            m._save_through_menu(Menu.MOTION_SAVE, self.path("taken.vmd"), ".vmd")
        self.assertTrue(os.path.isdir(self.path("taken.vmd")))
        self.assertEqual(sorted(os.listdir(self.folder)), ["shots.png", "taken.vmd"])

    def test_a_read_only_old_file_does_not_turn_a_success_into_a_failure(self):
        import stat
        path = self.path("dance.vmd")
        write(path, b"old")
        os.chmod(path, stat.S_IREAD)
        m = bare(menu=lambda *a, **k: write(path, b"new"))
        self.assertEqual(m._save_through_menu(Menu.MOTION_SAVE, path, ".vmd"), path)
        self.assertEqual(read(path), b"new")
        self.assertEqual(os.listdir(self.folder), ["dance.vmd"])

    def test_what_mmd_wrote_is_kept_when_the_operation_fails_afterwards(self):
        # review 2 (2.4 / 2.6): a verification or a timeout after MMD wrote the file must not destroy it
        path = self.path("clip.avi")
        write(path, b"old")

        def menu(*a, **k):
            write(path, b"new")
            raise guard.OperationTimeout("took too long")

        m = bare(menu=menu)
        with self.assertRaises(guard.OperationTimeout) as ctx:
            m._save_through_menu(Menu.MOTION_SAVE, path, ".avi")
        self.assertEqual(read(path), b"old")
        self.assertEqual(read(path + ".mmdcli-failed"), b"new")
        self.assertIn("mmdcli-failed", str(ctx.exception))

    def test_save_as_keeps_the_old_project_file_until_the_new_one_exists(self):
        path = self.path("scene.pmm")
        write(path, b"old")
        m = bare(menu=lambda *a, **k: None)
        with self.assertRaises(app.MmdError):
            m._save_as(path)
        self.assertEqual(read(path), b"old")
        self.assertEqual(os.listdir(self.folder), ["scene.pmm"])


@unittest.skipUnless(app is not None, "needs Windows")
class StateFileTest(TempHome):
    def test_concurrent_updates_are_not_lost(self):
        def bump(state):
            state["n"] = state.get("n", 0) + 1

        def work():
            for _ in range(100):
                app.update_state(bump)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(app.load_state()["n"], 400)
        self.assertEqual(sorted(os.listdir(app.home_dir())), ["state.json"])

    def test_forgetting_an_instance_happens_under_the_lock(self):
        # review 2 (3.1): quit used to read, change and write the state without the lock
        app.update_state(lambda s: s["projects"].update({"4242": {"work": "a"}, "7": {"work": "b"}}) or s.__setitem__("current", 4242))
        stop = threading.Event()

        def other():
            n = 0
            while not stop.is_set():
                app.update_state(lambda s: s["projects"].__setitem__("7", {"work": "b%d" % n}))
                n += 1

        t = threading.Thread(target=other)
        with mock.patch.object(app.win32, "process_alive", return_value=True):
            t.start()
            for _ in range(20):
                app.forget_instance(4242)
            stop.set()
            t.join()
            state = app.load_state()
        self.assertNotIn("4242", state["projects"])
        self.assertIn("7", state["projects"])
        self.assertIsNone(state["current"])

    @unittest.skipUnless(outside_code_page(OUTSIDE), "the system code page can encode the test character")
    def test_a_home_mmd_cannot_reach_is_refused_with_the_variable_to_set(self):
        bad = os.path.join(self.folder, OUTSIDE)
        with mock.patch.dict(os.environ, {"MMD_CLI_HOME": bad}):
            with self.assertRaises(app.MmdError) as ctx:
                app.home_dir()
        self.assertIn("MMD_CLI_HOME", str(ctx.exception))
        self.assertFalse(os.path.isdir(bad))


@unittest.skipUnless(app is not None, "needs Windows")
class PlayArgumentsTest(unittest.TestCase):
    def test_contradicting_flags_are_refused_before_mmd_is_touched(self):
        m = bare()
        with mock.patch.object(app.win32, "set_text", side_effect=AssertionError("MMD was touched")):
            with self.assertRaises(ValueError):
                m.play(wait=True, repeat=True)
            with self.assertRaises(ValueError):
                m.play(start=1)


@unittest.skipUnless(app is not None, "needs Windows")
class ParkedWindowTest(unittest.TestCase):
    """a hidden window is parked off-screen during an operation; one found there (an interrupted run left
    it) must come back to a place on the screen, or a later `window show` would show nothing"""

    def setUp(self):
        import types
        self.calls = []
        self.rect = (-28000, 200, 1280, 770)
        self.visible = False
        patches = [
            mock.patch.object(app.win32, "is_visible", side_effect=lambda h: self.visible),
            mock.patch.object(app.win32, "window_rect", side_effect=lambda h: self.rect),
            mock.patch.object(app.win32, "move_offscreen", side_effect=lambda h: self.calls.append(("park",))),
            mock.patch.object(app.win32, "move_window", side_effect=lambda h, x, y: self.calls.append(("move", x, y))),
            mock.patch.object(app.win32, "hide", side_effect=lambda h: self.calls.append(("hide",))),
            mock.patch.object(app.win32, "minimize_no_activate", side_effect=self.minimize),
            mock.patch.object(app.win32, "is_iconic", return_value=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.m = bare()
        self.m.guard = types.SimpleNamespace(run=lambda *a, **k: [])

    def minimize(self, hwnd):
        self.calls.append(("minimize",))
        self.visible = True

    def test_a_window_found_off_screen_is_given_a_place_on_the_screen_after_the_operation(self):
        self.m._run(None)
        self.assertEqual(self.calls, [("park",), ("move", 100, 100)])

    def test_a_window_found_where_it_belongs_goes_back_there(self):
        self.rect = (40, 60, 1280, 770)
        self.m._run(None)
        self.assertEqual(self.calls, [("park",), ("move", 40, 60)])

    def test_show_brings_a_parked_window_back_before_showing_it(self):
        self.m.show()
        self.assertEqual(self.calls, [("move", 100, 100), ("minimize",)])

    def test_a_window_still_visible_after_the_wait_is_left_parked(self):
        # review 2 (1.2): when MMD has not obeyed the hide yet, moving the window back would put it on the screen
        self.rect = (40, 60, 1280, 770)
        shown = {"after": False}

        def run(*a, **k):
            self.visible = True             # MMD shows the window during the operation and stays busy
            return []
        self.m.guard.run = run
        with mock.patch.object(app.Mmd, "_gone", staticmethod(lambda hwnd, timeout: False)):
            self.m._run(None)
        self.assertEqual(self.calls, [("park",), ("hide",)])
        self.assertEqual([e["action"] for e in self.m.events], ["still visible, left parked"])


@unittest.skipUnless(app is not None, "needs Windows")
class FileDialogRefusalTest(unittest.TestCase):
    """the save dialog refuses a name silently: it stays open and clears its box.  A dialog that is merely
    slow (review 2, 5.1) still holds the name and must be given time instead of being cancelled."""

    def setUp(self):
        self.texts = {}
        self.posted = []
        patches = [
            mock.patch.object(app.win32, "set_text", side_effect=lambda h, t: self.texts.__setitem__(h, t)),
            mock.patch.object(app.win32, "get_text", side_effect=lambda h, timeout_ms=None: self.texts.get(h, "")),
            mock.patch.object(app.win32, "post", side_effect=lambda *a: self.posted.append(a) or True),
            mock.patch.object(app.Mmd, "_gone", staticmethod(lambda hwnd, timeout: True)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.dialog = dialogs.Dialog(7, "#32770", "名前を付けて保存", [
            {"id": 1001, "cls": "Edit", "text": "", "hwnd": 71, "visible": True},
            {"id": 1, "cls": "Button", "text": "保存(&S)", "hwnd": 72, "visible": True},
            {"id": 2, "cls": "Button", "text": "キャンセル", "hwnd": 73, "visible": True}])
        self.handler = app.Mmd._fill_file_dialog("C:/out/a.png")

    def test_a_dialog_that_still_holds_the_name_is_given_more_time(self):
        self.assertEqual(self.handler(self.dialog), "file name entered")
        self.assertIs(self.handler(self.dialog), False)          # the box still shows the name: still working
        self.assertEqual([p[0] for p in self.posted], [72])      # OK once, no cancel

    def test_a_dialog_that_cleared_its_box_has_refused_the_name(self):
        self.handler(self.dialog)
        self.texts[71] = ""
        with self.assertRaises(app.MmdError) as ctx:
            self.handler(self.dialog)
        self.assertIn("refused", str(ctx.exception))
        self.assertEqual([p[0] for p in self.posted], [72, 73])  # OK, then cancel


def notice(*buttons):
    controls = [{"id": 0, "cls": "Static", "text": "Direct3D::Init", "hwnd": 9001, "visible": True}]
    for cid, text in buttons:
        controls.append({"id": cid, "cls": "Button", "text": text, "hwnd": 9000 + cid, "visible": True})
    return dialogs.Dialog(hwnd=9, cls="#32770", title="MikuMikuDance", controls=controls)


@unittest.skipUnless(app is not None, "needs Windows")
class LaunchFailureTest(TempHome):
    """dialogs while MMD starts: a notice is closed and quoted; one that cannot be answered ends the process"""

    def setUp(self):
        super().setUp()
        self.posted = []
        self.ended = []
        self.alive = [True]
        self.dialog_rounds = []
        patches = [
            mock.patch.object(app.win32, "launch_detached", return_value=4242),
            mock.patch.object(app.win32, "post", side_effect=lambda *a: self.posted.append(a) or True),
            mock.patch.object(app.win32, "terminate_process", side_effect=lambda pid: self.ended.append(pid)),
            mock.patch.object(app.win32, "process_alive", side_effect=lambda pid: self.alive[0]),
            mock.patch.object(app.guard, "open_dialogs", side_effect=self.dialogs_now),
            mock.patch.object(app.win32, "find_windows", side_effect=self.windows_now),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.main_ready = False

    def dialogs_now(self, pid, main_hwnd, hide=True):
        return self.dialog_rounds.pop(0) if self.dialog_rounds else []

    def windows_now(self, pid=None, cls=None):
        return [77] if self.main_ready else []

    def test_a_notice_is_closed_and_quoted_when_mmd_then_exits(self):
        self.dialog_rounds = [[notice((1, "OK"))]]
        original_alive = self.alive

        def after_click(*a):
            self.posted.append(a)
            original_alive[0] = False
            return True

        app.win32.post.side_effect = after_click
        with self.assertRaises(app.MmdError) as ctx:
            app.launch(sys.executable, timeout=5.0)
        self.assertIn("Direct3D::Init", str(ctx.exception))
        self.assertEqual([p[0] for p in self.posted], [9])

    def test_a_dialog_without_an_answer_ends_the_process_and_names_it(self):
        self.dialog_rounds = [[notice()]]
        with self.assertRaises(app.MmdError) as ctx:
            app.launch(sys.executable, timeout=5.0)
        self.assertEqual(self.ended, [4242])
        self.assertIn("4242", str(ctx.exception))
        self.assertIn("Direct3D::Init", str(ctx.exception))

    def test_a_notice_still_open_on_the_next_poll_is_not_pressed_again(self):
        # review 2 (4.1): the OK is posted; MMD may take a while to close the notice
        same = notice((1, "OK"))
        self.dialog_rounds = [[same], [same], [same]]
        self.alive = [True]

        def die_on_round_four(*a):
            return self.alive[0]
        with mock.patch.object(app.guard, "open_dialogs", side_effect=self.dialogs_then_death):
            with self.assertRaises(app.MmdError):
                app.launch(sys.executable, timeout=5.0)
        self.assertEqual([p[0] for p in self.posted], [9])

    def dialogs_then_death(self, pid, main_hwnd, hide=True):
        if self.dialog_rounds:
            return self.dialog_rounds.pop(0)
        self.alive[0] = False
        return []

    def test_a_timeout_ends_the_process_and_names_the_dialog(self):
        # review 2 (4.2): a notice that never closes left a transparent dialog on a live MMD nobody could reach
        same = notice((1, "OK"))
        with mock.patch.object(app.guard, "open_dialogs", side_effect=lambda *a, **k: [same]):
            with self.assertRaises(app.MmdError) as ctx:
                app.launch(sys.executable, timeout=0.5)
        self.assertEqual(self.ended, [4242])
        self.assertIn("4242", str(ctx.exception))
        self.assertIn("Direct3D::Init", str(ctx.exception))

    def test_a_notice_answered_on_the_way_is_reported_on_the_instance(self):
        self.dialog_rounds = [[notice((1, "OK"))]]

        def ready_after_click(*a):
            self.posted.append(a)
            self.main_ready = True
            return True

        app.win32.post.side_effect = ready_after_click
        controls = list(range(app.CONTROL_COUNT))
        with mock.patch.object(app.win32, "child_windows", return_value=controls), \
                mock.patch.object(app.win32, "send", return_value=0), \
                mock.patch.object(app.win32, "is_visible", return_value=True), \
                mock.patch.object(app.Mmd, "wait_quiet", return_value=[]):
            m = app.launch(sys.executable, timeout=5.0)
        self.assertEqual(m.pid, 4242)
        self.assertEqual([(e["message"], e["action"]) for e in m.events], [("Direct3D::Init", "ok")])


if __name__ == "__main__":
    unittest.main()
