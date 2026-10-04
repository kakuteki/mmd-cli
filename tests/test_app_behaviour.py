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
