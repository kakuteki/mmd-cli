"""Tests against a real MikuMikuDance.

Run with:
    set MMD_CLI_LIVE=1
    set MMD_EXE=C:/path/to/MikuMikuDance.exe
    python -m unittest tests.live.test_live -v

A dedicated MMD instance is started minimized and closed at the end.  Only files that ship with
MMD (UserFile/Model, Accessory, Pose) are used.  While the tests run, a watcher checks that no
window of that MMD ever becomes the foreground window and that its main window stays minimized.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave

LIVE = os.environ.get("MMD_CLI_LIVE") == "1"
EXE = os.environ.get("MMD_EXE", "")
ATTACH = os.environ.get("MMD_CLI_LIVE_ATTACH", "")

MMD = None
WATCH = None
WORK = None


def bundled(*parts):
    return os.path.join(os.path.dirname(EXE), "UserFile", *parts)


class FocusWatch(threading.Thread):
    """Every 10 ms: did a window of a watched MMD become the foreground window, or appear on the screen
    (visible, not a taskbar button, opaque, not parked off-screen)?  Dialogs the CLI hides are transparent
    and off-screen, a hidden main window is invisible, a parked one sits at x = -28000: none of them count.
    `pids` can grow while a test runs a second instance."""

    def __init__(self, win32, pid, hwnd):
        super().__init__(daemon=True)
        self.win32, self.pid, self.hwnd = win32, pid, hwnd
        self.pids = {pid}
        self.foreground_hits = []
        self.restored_hits = []
        self.samples = 0
        self.previous = None
        self.current_test = ""
        self._stop_flag = threading.Event()

    def run(self):
        while not self._stop_flag.is_set():
            fg = self.win32.foreground_window()
            if fg and self.win32.window_pid(fg) in self.pids:
                if not self.foreground_hits or self.foreground_hits[-1]["window"] != fg:
                    self.foreground_hits.append({"window": fg, "class": self.win32.class_name(fg),
                                                 "title": self.win32.get_text(fg, timeout_ms=200),
                                                 "during": self.current_test, "before": self.previous})
            elif fg:
                self.previous = "%s (pid %d)" % (self.win32.class_name(fg), self.win32.window_pid(fg))
            else:
                self.previous = "no foreground window"
            for pid in list(self.pids):
                for hwnd in self.win32.find_windows(pid=pid):
                    if self.on_screen(hwnd):
                        self.restored_hits.append((time.time(), self.current_test, self.win32.class_name(hwnd),
                                                   self.win32.get_text(hwnd, timeout_ms=100), hwnd))
            self.samples += 1
            time.sleep(0.01)

    def main_window_hits(self):
        return [h for h in self.restored_hits if h[2] == "Polygon Movie Maker"]

    def dialog_episodes(self):
        """runs of consecutive samples (10 ms apart) in which the same dialog was on the screen.  MMD puts
        its own confirmations in the middle of the screen the instant it creates them, so one sample
        (one compositor frame at most) cannot be prevented from outside the process; two or more mean
        the dialog stayed."""
        episodes = []
        for when, test, cls, title, hwnd in self.restored_hits:
            if cls == "Polygon Movie Maker":
                continue
            if episodes and episodes[-1]["hwnd"] == hwnd and when - episodes[-1]["until"] < 0.04:
                episodes[-1]["until"] = when
                episodes[-1]["samples"] += 1
            else:
                episodes.append({"hwnd": hwnd, "title": title, "test": test, "since": when, "until": when, "samples": 1})
        return episodes

    def on_screen(self, hwnd):
        w = self.win32
        if not w.is_visible(hwnd) or w.is_iconic(hwnd):
            return False
        if w.window_alpha(hwnd) != 255:                 # transparent: hidden by the CLI
            return False
        return w.window_rect(hwnd)[0] > -10000          # not parked or put away off-screen

    def stop(self):
        self._stop_flag.set()


def setUpModule():
    global MMD, WATCH, WORK
    if not LIVE or not EXE:
        raise unittest.SkipTest("set MMD_CLI_LIVE=1 and MMD_EXE to run the live tests")
    from mmd_cli import app, win32
    WORK = tempfile.mkdtemp(prefix="mmdcli-live-")
    os.environ["MMD_CLI_HOME"] = os.path.join(WORK, "home")
    # the shared instance is started hidden: a person at this PC must not be tempted to open or
    # close a "MikuMikuDance" taskbar button in the middle of the run (it happened, 2026-10-04)
    MMD = app.Mmd.attach(int(ATTACH)) if ATTACH else app.launch(EXE, headless=True)
    WATCH = FocusWatch(win32, MMD.pid, MMD.hwnd)
    WATCH.start()


def tearDownModule():
    if WATCH is not None:
        WATCH.stop()
    if MMD is not None and not ATTACH:
        MMD.quit(force=True)
    if WORK:
        shutil.rmtree(WORK, ignore_errors=True)


def out(name):
    return os.path.join(WORK, name)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    with_model = False

    def setUp(self):
        WATCH.current_test = self.id()
        for _ in MMD.dialogs():
            MMD.dialog_close()
        MMD.stop()
        MMD.new_project()
        if self.with_model:
            MMD.load_model(bundled("Model", "初音ミク.pmd"))


class LaunchTest(Base):
    def test_main_window_is_off_the_screen_and_the_taskbar(self):
        s = MMD.state()
        self.assertTrue(s["minimized"] or not s["visible"])

    def test_state_of_an_empty_project(self):
        s = MMD.state()
        self.assertEqual(s["models"], [])
        self.assertEqual(s["mode"], "camera")
        self.assertIsNone(s["selected_model"])
        self.assertEqual(s["frame"], 0)
        self.assertIsNone(s["project_path"])
        self.assertEqual(s["dialogs"], [])
        self.assertEqual(s["pid"], MMD.pid)


class ModelTest(Base):
    def test_load_reports_name_and_comment_and_selects_the_model(self):
        r = MMD.load_model(bundled("Model", "初音ミク.pmd"))
        self.assertEqual(r["name"], "初音ミク")
        self.assertEqual(r["index"], 0)
        self.assertIn("あにまさ", r["comment"])
        s = MMD.state()
        self.assertEqual(s["models"], ["初音ミク"])
        self.assertEqual((s["mode"], s["selected_model"]), ("model", "初音ミク"))

    def test_dialogs_answered_on_the_way_are_recorded(self):
        MMD.take_events()
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        events = MMD.take_events()
        self.assertEqual([(e["kind"], e["title"], e["action"]) for e in events], [("model_info", "モデル情報", "ok")])
        self.assertEqual(MMD.take_events(), [])

    def test_select_camera_mode_and_back(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.select_model(None)
        self.assertEqual(MMD.state()["mode"], "camera")
        MMD.select_model("初音ミク")
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")
        MMD.select_model(None)
        MMD.select_model(0)
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")

    def test_the_same_model_can_be_loaded_twice(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        r = MMD.load_model(bundled("Model", "初音ミク.pmd"))
        self.assertEqual(r["index"], 1)
        self.assertEqual(len(MMD.models()), 2)

    def test_delete(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.load_model(bundled("Model", "鏡音リン.pmd"))
        MMD.delete_model("初音ミク")
        self.assertEqual(MMD.models(), ["鏡音リン"])

    def test_unknown_model_name_is_an_error(self):
        from mmd_cli import app
        with self.assertRaises(app.MmdError):
            MMD.select_model("そんなモデルは無い")

    def test_missing_file_is_rejected_before_mmd_is_touched(self):
        with self.assertRaises(FileNotFoundError):
            MMD.load_model(out("nothing.pmx"))

    def test_visibility(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.set_model_visible(False)
        self.assertFalse(MMD.dump(in_place=False)["models"][0]["visible"])
        MMD.set_model_visible(True)
        self.assertTrue(MMD.dump()["models"][0]["visible"])


class FrameTest(Base):
    def test_set_and_step(self):
        self.assertEqual(MMD.set_frame(25), 25)
        self.assertEqual(MMD.step_frame(1), 26)
        self.assertEqual(MMD.step_frame(-1), 25)
        self.assertEqual(MMD.frame(), 25)
        self.assertEqual(MMD.dump()["frame"], 25)

    def test_negative_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            MMD.set_frame(-1)


class CameraLightTest(Base):
    WANT = {"pos": [1.5, 12.0, -3.25], "rot": [10.0, 20.0, 5.0], "distance": 30.0, "fov": 45, "perspective": True}

    def test_camera_set_and_register(self):
        r = MMD.set_camera(pos=(1.5, 12, -3.25), rot=(10, 20, 5), distance=30, fov=45, register=True)
        self.assertEqual(r, self.WANT)
        self.assertEqual(MMD.camera(), self.WANT)
        d = MMD.dump()
        self.assertEqual(d["camera"]["current"], self.WANT)
        self.assertEqual(d["camera"]["keys"], [dict(self.WANT, frame=0)])

    def test_camera_key_at_another_frame(self):
        MMD.set_frame(30)
        MMD.set_camera(distance=20, register=True)
        keys = MMD.dump()["camera"]["keys"]
        self.assertEqual([(k["frame"], k["distance"]) for k in keys], [(0, 45.0), (30, 20.0)])

    def test_registered_camera_values_survive_while_a_model_is_selected(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        r = MMD.set_camera(distance=33, register=True)
        self.assertEqual(r["distance"], 33.0)
        cam = MMD.dump()["camera"]
        self.assertEqual(cam["current_is"], "editing view")   # a model is selected: not the scene camera
        self.assertEqual(cam["keys"][0]["distance"], 33.0)
        self.assertEqual(MMD.camera()["distance"], 33.0)
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")

    def test_unregistered_values_are_refused_while_a_model_is_selected(self):
        # MMD throws unregistered camera and light values away as soon as a model is selected again
        from mmd_cli import app
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        with self.assertRaises(app.MmdError):
            MMD.set_camera(distance=33)
        with self.assertRaises(app.MmdError):
            MMD.set_light(rgb=(1, 2, 3))
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")

    def test_unregistered_camera_values_hold_in_camera_mode(self):
        MMD.set_camera(distance=20)
        self.assertEqual(MMD.camera()["distance"], 20.0)
        self.assertEqual(MMD.dump()["camera"]["keys"][0]["distance"], 45.0)   # no key was written

    def test_perspective_off(self):
        r = MMD.set_camera(perspective=False, register=True)
        self.assertFalse(r["perspective"])
        self.assertFalse(MMD.dump()["camera"]["keys"][0]["perspective"])

    def test_light(self):
        want = {"rgb": [200, 100, 50], "dir": [-0.2, -0.8, 0.3]}
        self.assertEqual(MMD.set_light(rgb=(200, 100, 50), direction=(-0.2, -0.8, 0.3), register=True), want)
        self.assertEqual(MMD.light(), want)
        d = MMD.dump()
        self.assertEqual(d["light"]["current"], want)
        self.assertEqual(d["light"]["keys"], [dict(want, frame=0)])


class MotionTest(Base):
    with_model = True

    def write_motion(self, model_name="初音ミク"):
        from mmd_cli.formats import vmd
        path = out("motion.vmd")
        vmd.dump(vmd.Motion(
            model_name=model_name,
            bones=[vmd.BoneKey("センター", 0, (0.0, 5.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
                   vmd.BoneKey("センター", 20, (1.0, 2.0, 3.0), (0.0, 0.0, 0.2588190451, 0.9659258263)),
                   vmd.BoneKey("右腕", 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.3826834324, 0.9238795325))],
            morphs=[vmd.MorphKey("まばたき", 0, 1.0), vmd.MorphKey("あ", 5, 0.5)]), path)
        return path

    def test_load_motion_inserts_keys_at_the_given_frame(self):
        r = MMD.load_motion(self.write_motion(), frame=10)
        self.assertEqual(r["frame"], 10)
        self.assertEqual(r["confirmed"], False)
        keys = MMD.dump()["models"][0]["keys"]
        self.assertEqual([(k["bone"], k["frame"]) for k in keys["bones"]],
                         [("センター", 10), ("センター", 30), ("右腕", 10)])
        self.assertEqual(keys["bones"][1]["pos"], [1.0, 2.0, 3.0])
        self.assertEqual(keys["bones"][1]["rot"], [0.0, 0.0, -30.0])   # +Z quaternion, shown by MMD as -30
        self.assertEqual(keys["morphs"], [{"morph": "まばたき", "frame": 10, "value": 1.0},
                                          {"morph": "あ", "frame": 15, "value": 0.5}])

    def test_motion_made_for_another_model_is_confirmed_automatically(self):
        r = MMD.load_motion(self.write_motion(model_name="別のモデル"))
        self.assertEqual(r["confirmed"], True)
        self.assertEqual(MMD.dump()["models"][0]["key_counts"], {"bones": 3, "morphs": 2})

    def test_set_bone_registers_a_key_and_moves_to_the_frame(self):
        r = MMD.set_bone("センター", pos=(0, 5, 0), rot=(0, 0, 30), frame=12)
        self.assertEqual(r, {"bone": "センター", "frame": 12, "pos": [0.0, 5.0, 0.0], "rot": [0.0, 0.0, 30.0]})
        d = MMD.dump()
        self.assertEqual(d["frame"], 12)
        self.assertEqual(d["models"][0]["keys"]["bones"], [r])
        self.assertEqual(d["models"][0]["current"]["bones"], {"センター": {"pos": [0.0, 5.0, 0.0], "rot": [0.0, 0.0, 30.0]}})

    def test_bone_angles_are_the_ones_the_mmd_window_shows(self):
        for rot in ((10.0, -20.0, -30.0), (25.0, -70.0, 110.0), (-40.0, 15.0, 5.0)):
            r = MMD.set_bone("センター", pos=(1, 2, 3), rot=rot)
            self.assertEqual(r["rot"], list(rot))
            MMD.set_frame(r["frame"])     # MMD refreshes its number boxes on the next frame move
            shown = [float(MMD.control_get(cid)["text"]) for cid in (547, 548, 549)]   # センター is the selected bone
            self.assertEqual(shown, list(rot))
            self.assertEqual([float(MMD.control_get(cid)["text"]) for cid in (544, 545, 546)], [1.0, 2.0, 3.0])

    def test_set_bone_keeps_the_part_that_is_not_given(self):
        MMD.set_bone("センター", pos=(1, 2, 3), rot=(0, 40, 0))
        r = MMD.set_bone("センター", rot=(0, 0, 10))
        self.assertEqual(r["pos"], [1.0, 2.0, 3.0])
        self.assertEqual(r["rot"], [0.0, 0.0, 10.0])

    def test_set_bone_with_an_unknown_name_is_an_error(self):
        from mmd_cli import app
        with self.assertRaises(app.MmdError):
            MMD.set_bone("無い骨", pos=(0, 1, 0))

    def test_bone_list_and_get(self):
        bones = MMD.bones()
        self.assertEqual(len(bones), 122)
        self.assertEqual(bones[0], "センター")
        MMD.set_bone("右腕", rot=(0, 0, 45))
        self.assertEqual(MMD.bone("右腕"), {"bone": "右腕", "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 45.0]})

    def test_set_morph_registers_a_key(self):
        r = MMD.set_morph("まばたき", 0.75, frame=8)
        self.assertEqual(r, {"morph": "まばたき", "frame": 8, "value": 0.75})
        d = MMD.dump()
        self.assertEqual(d["models"][0]["keys"]["morphs"], [r])
        self.assertEqual(MMD.morph("まばたき"), {"morph": "まばたき", "value": 0.75})
        self.assertIn("あ", MMD.morphs())

    def test_pose_load_and_register(self):
        r = MMD.load_pose(bundled("Pose", "右手グー.vpd"), register=True)
        self.assertEqual(r["bones"], 14)
        self.assertTrue(r["registered"])
        d = MMD.dump()
        self.assertIn("右親指１", d["models"][0]["current"]["bones"])
        self.assertEqual(d["models"][0]["key_counts"]["bones"], 14)

    def test_pose_load_without_register_changes_the_pose_only(self):
        MMD.load_pose(bundled("Pose", "右手グー.vpd"))
        d = MMD.dump()
        self.assertIn("右親指１", d["models"][0]["current"]["bones"])
        self.assertEqual(d["models"][0]["key_counts"]["bones"], 0)


class AssetTest(Base):
    def test_wav(self):
        path = out("silence.wav")
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(bytes(2 * 44100))
        MMD.load_wav(path)
        w = MMD.dump()["wave"]
        self.assertTrue(w["enabled"])
        self.assertEqual(os.path.normcase(w["path"]), os.path.normcase(path))

    def test_accessory_load_set_and_delete(self):
        r = MMD.load_accessory(bundled("Accessory", "negi.x"))
        self.assertEqual(r, {"name": "negi.x", "index": 0})
        self.assertEqual(MMD.accessories(), ["negi.x"])
        MMD.set_frame(10)
        got = MMD.set_accessory("negi.x", pos=(1, 2, 3), rot=(10, 20, 30), scale=2, alpha=0.5)
        want = {"pos": [1.0, 2.0, 3.0], "rot": [10.0, 20.0, 30.0], "scale": 2.0, "alpha": 0.5}
        self.assertEqual({k: got[k] for k in want}, want)
        acc = MMD.dump()["accessories"][0]
        self.assertEqual({k: acc["current"][k] for k in want}, want)
        self.assertEqual([k["frame"] for k in acc["keys"]], [0, 10])
        MMD.delete_accessory("negi.x")
        self.assertEqual(MMD.accessories(), [])


class ProjectTest(Base):
    def test_dump_of_a_fresh_project_uses_a_working_copy(self):
        d = MMD.dump()
        self.assertEqual(d["models"], [])
        work = MMD.state()["project_path"]
        self.assertTrue(os.path.normcase(work).startswith(os.path.normcase(os.environ["MMD_CLI_HOME"])))

    def test_save_then_open_restores_the_scene_and_leaves_the_file_alone_on_dump(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.set_bone("センター", pos=(0, 5, 0), frame=10)
        target = out("scene.pmm")
        r = MMD.save(target)
        self.assertEqual(os.path.normcase(r["path"]), os.path.normcase(target))
        self.assertTrue(os.path.exists(target))
        before = read_bytes(target)
        MMD.new_project()
        self.assertEqual(MMD.models(), [])
        MMD.open_project(target)
        self.assertEqual(MMD.models(), ["初音ミク"])
        MMD.set_frame(3)
        d = MMD.dump()
        self.assertEqual(d["models"][0]["key_counts"]["bones"], 1)
        self.assertEqual(read_bytes(target), before)   # dump saved the working copy, not the file
        MMD.save()                                            # save without a path goes back to where it was opened
        self.assertNotEqual(read_bytes(target), before)

    def test_opening_a_second_project_right_after_the_first(self):
        # seen on hinata (2026-10-04): open A, save, open B left a file dialog waiting
        a, b = out("a.pmm"), out("b.pmm")
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.save(a)
        MMD.new_project()
        MMD.load_model(bundled("Model", "鏡音リン.pmd"))
        MMD.save(b)
        MMD.open_project(a)
        self.assertEqual(MMD.models(), ["初音ミク"])
        MMD.save()                                   # like apply2: save, then open the other one
        MMD.open_project(b)
        self.assertEqual(MMD.models(), ["鏡音リン"])
        self.assertEqual(MMD.dialogs(), [])

    def test_dump_refuses_a_project_the_cli_did_not_open(self):
        from mmd_cli import app
        MMD.dump()
        MMD.forget_project()
        with self.assertRaises(app.MmdError):
            MMD.dump()
        self.assertEqual(MMD.dump(in_place=True)["models"], [])


class HandOpenedProjectTest(Base):
    def test_saving_a_hand_opened_project_elsewhere_leaves_it_untouched(self):
        # review 1 (4.1): "save as" of a project a person opened must not write the file MMD has open
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        hand, copy = out("hand.pmm"), out("copy.pmm")
        MMD._save_as(hand)                                   # MMD now has hand.pmm itself open ...
        MMD.forget_project()                                 # ... and mmd-cli has no record of it: as if opened by hand
        before = read_bytes(hand)
        MMD.set_frame(7)
        r = MMD.save(copy)
        self.assertEqual(os.path.normcase(r["path"]), os.path.normcase(copy))
        self.assertTrue(os.path.exists(copy))
        self.assertEqual(read_bytes(hand), before)
        self.assertTrue(os.path.normcase(MMD.state()["project_path"]).endswith("copy.pmm"))
        MMD.save()                                           # no path: the overwrite that was asked for, of copy.pmm
        self.assertEqual(read_bytes(hand), before)


class RenderTest(Base):
    with_model = True

    def test_image(self):
        path = out("shot.png")
        r = MMD.render_image(path, size=(320, 180))
        self.assertEqual(r["size"], [320, 180])
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")   # rendered through the camera, then restored
        with open(path, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", head[16:24]), (320, 180))

    def test_avi(self):
        path = out("clip.avi")
        r = MMD.render_avi(path, start=0, end=4, size=(160, 90), fps=30)
        self.assertEqual(r["frames"], 5)
        with open(path, "rb") as f:
            head = f.read(64)
        self.assertEqual((head[:4], head[8:12]), (b"RIFF", b"AVI "))
        self.assertEqual(struct.unpack_from("<I", head, 48)[0], 5)   # avih dwTotalFrames


class PlayTest(Base):
    with_model = True

    def test_play_a_range_and_wait_returns_to_the_frame_it_started_from(self):
        MMD.set_bone("センター", pos=(0, 1, 0), frame=20)
        MMD.set_frame(5)
        r = MMD.play(start=0, end=20, wait=True)
        self.assertEqual(r, {"playing": False, "frame": 5})
        self.assertFalse(MMD.state()["playing"])

    def test_stay_keeps_the_frame_where_playback_ended(self):
        MMD.set_bone("センター", pos=(0, 1, 0), frame=20)
        MMD.set_frame(5)
        r = MMD.play(start=0, end=20, wait=True, stay=True)
        self.assertEqual(r, {"playing": False, "frame": 20})

    def test_stop_and_commands_are_refused_while_playing(self):
        from mmd_cli import app
        MMD.set_bone("センター", pos=(0, 1, 0), frame=600)
        MMD.set_frame(0)
        r = MMD.play(start=0, end=600)
        self.assertTrue(r["playing"])
        self.assertTrue(MMD.state()["playing"])
        with self.assertRaises(app.MmdError):
            MMD.set_frame(3)
        MMD.stop()
        self.assertFalse(MMD.state()["playing"])
        self.assertEqual(MMD.set_frame(3), 3)


class DialogTest(Base):
    def test_an_unexpected_dialog_is_reported_and_blocks_later_commands_until_answered(self):
        from mmd_cli import guard, win32
        with self.assertRaises(guard.DialogPending) as ctx:
            MMD.menu_click(201)   # version information
        self.assertEqual(ctx.exception.dialogs[0].title, "About")
        self.assertEqual([d["title"] for d in MMD.dialogs()], ["About"])
        hwnd = MMD.dialogs()[0]["hwnd"]
        self.assertTrue(win32.is_hidden(hwnd))                                   # transparent and off-screen
        self.assertTrue(win32.ex_style(hwnd) & win32.WS_EX_NOACTIVATE)           # Windows will not hand it the focus
        with self.assertRaises(guard.DialogPending):
            MMD.set_frame(5)
        MMD.dialog_click("OK")
        self.assertEqual(MMD.dialogs(), [])
        self.assertEqual(MMD.set_frame(5), 5)


class ObserveTest(Base):
    def test_looking_does_not_hide_a_dialog_the_cli_did_not_open(self):
        # a person working in this MMD may have a dialog open: state / dialog list must leave it visible
        from mmd_cli import guard, win32
        win32.post(MMD.hwnd, win32.WM_COMMAND, 201, None)        # "about", opened behind the CLI's back
        hwnd = None
        deadline = time.time() + 10
        with win32.timer_resolution():
            while time.time() < deadline:
                found = guard.dialog_windows(MMD.pid, MMD.hwnd)
                if found:
                    hwnd = found[0]
                    # keep it off the real screen for this test, but do not make it transparent
                    win32.user32.SetWindowPos(hwnd, None, -20000, 300, 0, 0, 0x0001 | 0x0004 | 0x0010)
                    if win32.is_visible(hwnd):
                        break
                time.sleep(0.001)
        self.assertIsNotNone(hwnd)
        try:
            listed = MMD.state()["dialogs"]
            self.assertEqual([(d["title"], d["hidden"]) for d in listed], [("About", False)])
            self.assertEqual([d["title"] for d in MMD.dialogs()], ["About"])
            with self.assertRaises(guard.DialogPending):
                MMD.set_frame(1)
            self.assertEqual(win32.window_alpha(hwnd), 255)
            self.assertFalse(win32.is_hidden(hwnd))
        finally:
            MMD.dialog_click("OK")


class NestedDialogTest(Base):
    def test_the_innermost_dialog_is_the_one_that_is_answered(self):
        # a save dialog that rejects its file name opens a message on top of itself: two windows are
        # open, and only the inner one can take an answer
        from mmd_cli import guard
        with self.assertRaises(guard.DialogPending):
            MMD.menu(208, {"file_dialog": MMD._fill_file_dialog("C:/no such folder?/x.pmm")})
        listed = MMD.dialogs()
        self.assertEqual(len(listed), 2)
        self.assertEqual([d["enabled"] for d in listed].count(True), 1)
        MMD.dialog_click("OK")                      # the message
        self.assertEqual([d["kind"] for d in MMD.dialogs()], ["file_dialog"])
        MMD.dialog_close()                          # the save dialog itself
        self.assertEqual(MMD.dialogs(), [])

    def test_a_name_the_file_dialog_refuses_fails_cleanly(self):
        # the dialog's complaint becomes the error, and nothing is left open
        from mmd_cli import app
        with self.assertRaises(app.MmdError) as ctx:
            MMD.render_image(out("no?way.png"))
        self.assertIn("refused", str(ctx.exception))
        self.assertEqual(MMD.dialogs(), [])
        MMD.set_frame(2)
        self.assertEqual(MMD.frame(), 2)

    def test_working_copies_are_found_when_the_home_path_has_forward_slashes(self):
        previous = os.environ["MMD_CLI_HOME"]
        os.environ["MMD_CLI_HOME"] = os.path.join(WORK, "home2").replace(os.sep, "/")
        try:
            self.assertEqual(MMD.dump()["models"], [])
        finally:
            os.environ["MMD_CLI_HOME"] = previous


class GenericTest(Base):
    def test_menu_list_has_ids_and_check_marks(self):
        items = {i["id"]: i for i in MMD.menu_items()}
        self.assertEqual(items[204]["path"], ["ファイル(&F)", "新規(&N)"])
        self.assertTrue(items[215]["checked"])     # 座標軸表示 is on by default

    def test_menu_click_toggles_a_display_option(self):
        MMD.menu_click(215)
        self.assertFalse({i["id"]: i for i in MMD.menu_items()}[215]["checked"])
        MMD.menu_click(215)

    def test_control_get_set_and_click(self):
        self.assertEqual(MMD.control_get(417)["text"], "0")
        MMD.control_click(419)                      # the '>' button
        self.assertEqual(MMD.control_get(417)["text"], "1")
        MMD.control_set(554, "7")                   # the frame bookmark box
        self.assertEqual(MMD.control_get(554)["text"], "7")
        self.assertEqual(len(MMD.controls()), 168)


class GenericControlTest(Base):
    def test_trackbar_moves_the_value_it_controls(self):
        MMD.control_set(447, 60)                                 # view angle slider
        self.assertEqual(MMD.control_get(447)["pos"], 60)
        self.assertEqual(MMD.camera()["fov"], 60)

    def test_check_box(self):
        self.assertTrue(MMD.control_get(446)["checked"])         # perspective
        MMD.control_set(446, "off")
        self.assertFalse(MMD.camera()["perspective"])
        MMD.control_set(446, "on")
        self.assertTrue(MMD.camera()["perspective"])

    def test_combo_box_by_text(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.control_set(436, 0)
        self.assertEqual(MMD.state()["mode"], "camera")
        MMD.control_set(436, "初音ミク")
        self.assertEqual(MMD.state()["selected_model"], "初音ミク")

    def test_frame_first_last_and_key_jumps(self):
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        MMD.set_bone("センター", pos=(0, 1, 0), frame=10)
        MMD.set_bone("センター", pos=(0, 2, 0), frame=40)
        MMD.set_frame(0)
        self.assertEqual(MMD.jump_key(forward=True), 10)
        self.assertEqual(MMD.jump_key(forward=True), 40)
        self.assertEqual(MMD.jump_key(forward=False), 10)
        self.assertEqual(MMD.go_last(), 40)
        self.assertEqual(MMD.go_first(), 0)

    def test_a_revealed_dialog_is_opaque_again(self):
        from mmd_cli import guard, win32
        with self.assertRaises(guard.DialogPending):
            MMD.menu_click(201)
        hwnd = MMD.dialogs()[0]["hwnd"]
        try:
            shown = MMD.dialog_show(x=win32.OFFSCREEN_X, y=300)   # "show", but still where nobody sees it
            self.assertEqual([d["title"] for d in shown], ["About"])
            self.assertFalse(win32.ex_style(hwnd) & win32.WS_EX_NOACTIVATE)
            self.assertEqual(win32.window_alpha(hwnd), 255)
        finally:
            MMD.dialog_click("OK")


class SampleProjectTest(Base):
    def test_a_project_that_ships_with_mmd_opens_and_dumps(self):
        samples = sorted(f for f in os.listdir(bundled()) if f.endswith(".pmm"))
        self.assertTrue(samples)
        smallest = min(samples, key=lambda f: os.path.getsize(bundled(f)))
        MMD.open_project(bundled(smallest))
        d = MMD.dump()
        self.assertGreaterEqual(len(d["models"]), 1)
        self.assertGreater(sum(m["key_counts"]["bones"] for m in d["models"]), 100)
        self.assertGreater(d["last_frame"], 100)


class HeadlessTest(unittest.TestCase):
    """The shared instance runs hidden (nothing on the taskbar); a second instance started the default
    way is a taskbar button that is never activated.  Both render, both can be hidden and shown."""

    def test_hidden_instance_renders_and_stays_hidden(self):
        from mmd_cli import app, win32
        self.assertFalse(win32.is_visible(MMD.hwnd))
        self.assertFalse(MMD.state()["visible"])
        self.assertIn(MMD.pid, [i["pid"] for i in app.instances() if not i["visible"]])
        MMD.load_model(bundled("Model", "初音ミク.pmd"))
        r = MMD.render_image(out("headless.png"), size=(320, 180))
        self.assertEqual(r["size"], [320, 180])
        self.assertFalse(win32.is_visible(MMD.hwnd))                 # still hidden after a render
        # MMD shows its window on its own when it starts writing an AVI: it must appear nowhere and end hidden
        r = MMD.render_avi(out("headless.avi"), 0, 5, fps=30, size=(320, 180))
        self.assertEqual(r["size"], [320, 180])
        self.assertFalse(win32.is_visible(MMD.hwnd))
        self.assertGreater(win32.window_rect(MMD.hwnd)[0], win32.OFFSCREEN_X + 100)   # not left parked
        self.assertIn("hidden again", [e["action"] for e in MMD.take_events()])

    def test_minimized_instance(self):
        from mmd_cli import app, win32
        m = app.launch(EXE)
        WATCH.pids.add(m.pid)                                        # this one is watched too, while it lives
        try:
            self.assertTrue(win32.is_iconic(m.hwnd))
            self.assertTrue(win32.is_visible(m.hwnd))
            self.assertEqual(m.state()["minimized"], True)
            m.load_model(bundled("Model", "初音ミク.pmd"))
            r = m.render_image(out("minimized.png"), size=(320, 180))
            self.assertEqual(r["size"], [320, 180])
            self.assertTrue(win32.is_iconic(m.hwnd))                 # still minimized after a render
            self.assertEqual(m.hide(), {"minimized": True, "visible": False})
            self.assertEqual(m.show(), {"minimized": True, "visible": True})
        finally:
            m.quit(force=True)
            WATCH.pids.discard(m.pid)
        app.update_state(lambda s: s.__setitem__("current", MMD.pid))   # give the shared instance back its role


class RelayTest(unittest.TestCase):
    """The Task Scheduler bridge, driven from this (interactive) session: the scheduled copy runs the
    command and the result comes back as JSON."""

    def test_round_trip(self):
        from mmd_cli import relay
        payload, code = relay.run_in_user_session(["--pid", str(MMD.pid), "state"])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["relayed"])
        self.assertEqual(payload["pid"], MMD.pid)

    def test_errors_and_exit_codes_travel_back(self):
        from mmd_cli import relay
        payload, code = relay.run_in_user_session(["--pid", str(MMD.pid), "model", "select", "nobody"])
        self.assertEqual(code, 1)
        self.assertIn("nobody", payload["error"]["message"])

    def test_nothing_is_left_in_the_scheduler(self):
        import subprocess
        from mmd_cli import relay
        relay.run_in_user_session(["--pid", str(MMD.pid), "frame", "get"])
        listing = subprocess.run(["schtasks.exe", "/Query", "/FO", "CSV"], capture_output=True, creationflags=0x08000000)
        self.assertNotIn(b"mmd-cli\\relay-", listing.stdout)   # the suite itself may be running as mmd-cli\live-*


class SaveTest(Base):
    """motion save / pose save hand MMD's own writers a file name; render codecs reads the AVI dialog."""
    with_model = True

    def test_motion_save_writes_the_registered_keys(self):
        from mmd_cli.formats import vmd
        MMD.set_bone("センター", pos=(0, 5, 0), frame=10)
        MMD.set_morph("まばたき", 1.0, frame=12)
        path = out("saved.vmd")
        r = MMD.save_motion(path)
        self.assertEqual(os.path.normcase(r["path"]), os.path.normcase(path))
        m = vmd.load(path)
        self.assertEqual(m.model_name, "初音ミク")
        self.assertIn(("センター", 10), [(k.name, k.frame) for k in m.bones])
        self.assertIn(("まばたき", 12), [(k.name, k.frame) for k in m.morphs])
        self.assertEqual((r["bones"], r["morphs"]), (len(m.bones), len(m.morphs)))

    def test_motion_save_overwrites_an_existing_file(self):
        path = out("saved2.vmd")
        MMD.save_motion(path)
        before = os.path.getsize(path)
        MMD.set_bone("センター", pos=(0, 1, 0), frame=20)
        MMD.save_motion(path)
        self.assertGreater(os.path.getsize(path), before)

    def test_camera_motion_save(self):
        from mmd_cli.formats import vmd
        MMD.set_frame(15)
        MMD.set_camera(distance=20, register=True)
        MMD.select_model(None)
        path = out("camera.vmd")
        r = MMD.save_motion(path)
        m = vmd.load(path)
        self.assertTrue(m.is_camera)
        self.assertEqual(r["kind"], "camera")
        self.assertIn(15, [k.frame for k in m.cameras])

    def test_pose_save_writes_the_current_pose(self):
        from mmd_cli.formats import vpd
        MMD.set_bone("右腕", rot=(0, 0, 45))
        path = out("pose.vpd")
        r = MMD.save_pose(path)
        pose = vpd.load(path)
        names = [b.name for b in pose.bones]
        self.assertIn("右腕", names)
        self.assertEqual(r["bones"], len(pose.bones))

    def test_render_codecs_lists_what_the_avi_dialog_offers(self):
        codecs = MMD.render_codecs()
        self.assertGreaterEqual(len(codecs), 1)
        self.assertTrue(all(isinstance(c, str) and c for c in codecs))
        self.assertEqual(MMD.dialogs(), [])          # the dialogs were cancelled again


class BatchTest(Base):
    def run_batch(self, text, *extra):
        path = out("script.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        cmd = [sys.executable, "-m", "mmd_cli", "--pid", str(MMD.pid), "batch", path] + list(extra)
        p = subprocess.run(cmd, capture_output=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        return p.returncode, json.loads(p.stdout.decode("ascii"))

    def test_lines_run_in_order_in_one_process(self):
        code, data = self.run_batch("new\nmodel load \"%s\"\nframe set 12\nbone set 右腕 --rot 0 0 20\nstate\n"
                                    % bundled("Model", "初音ミク.pmd"))
        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        self.assertEqual((data["ran"], data["failed"]), (5, 0))
        self.assertEqual(data["results"][1]["name"], "初音ミク")
        self.assertEqual(data["results"][3]["rot"], [0.0, 0.0, 20.0])
        self.assertEqual(data["results"][4]["frame"], 12)
        self.assertEqual([d["kind"] for d in data["results"][1]["answered_dialogs"]], ["model_info"])

    def test_a_failing_line_stops_the_batch_unless_asked_otherwise(self):
        code, data = self.run_batch("frame set 3\nmodel select nobody\nframe set 4\n")
        self.assertEqual(code, 1)
        self.assertEqual([r["ok"] for r in data["results"]], [True, False])
        self.assertEqual(MMD.frame(), 3)
        code, data = self.run_batch("frame set 5\nmodel select nobody\nframe set 6\n", "--keep-going")
        self.assertEqual(code, 1)
        self.assertEqual([r["ok"] for r in data["results"]], [True, False, True])
        self.assertEqual(MMD.frame(), 6)


class CliTest(Base):
    def run_cli(self, *args):
        env = dict(os.environ)
        cmd = [sys.executable, "-m", "mmd_cli", "--pid", str(MMD.pid)] + list(args)
        p = subprocess.run(cmd, capture_output=True, env=env, creationflags=0x08000000,   # no console window
                           cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        return p.returncode, p.stdout.decode("ascii"), p.stderr.decode("utf-8", "replace")

    def test_state_is_ascii_json(self):
        code, stdout, stderr = self.run_cli("state")
        self.assertEqual(code, 0, stderr)
        data = json.loads(stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["pid"], MMD.pid)

    def test_model_load_and_out_file(self):
        target = out("result.json")
        code, stdout, stderr = self.run_cli("--out", target, "model", "load", bundled("Model", "初音ミク.pmd"))
        self.assertEqual(code, 0, stderr)
        raw = read_bytes(target).decode("utf-8")
        data = json.loads(raw)
        self.assertEqual(data["name"], "初音ミク")
        self.assertIn("初音ミク", raw)                                        # not escaped in the file
        self.assertEqual([d["kind"] for d in data["answered_dialogs"]], ["model_info"])
        self.assertEqual(json.loads(stdout)["ok"], True)

    def test_errors_are_json_with_a_nonzero_exit_code(self):
        code, stdout, stderr = self.run_cli("model", "select", "nobody")
        self.assertEqual(code, 1)
        data = json.loads(stdout)
        self.assertFalse(data["ok"])
        self.assertIn("nobody", data["error"]["message"])

    def test_pending_dialog_exit_code(self):
        code, stdout, _ = self.run_cli("menu", "click", "201")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["error"]["dialogs"][0]["title"], "About")
        code, stdout, _ = self.run_cli("dialog", "click", "OK")
        self.assertEqual(code, 0)


class ZzFocusTest(unittest.TestCase):
    """Runs last (alphabetical order): nothing above may have shown or focused an MMD window."""

    def test_mmd_never_became_the_foreground_window(self):
        self.assertGreater(WATCH.samples, 100)
        self.assertEqual(WATCH.foreground_hits, [])

    def test_main_window_never_appeared_on_the_screen(self):
        # the full record goes to a file: unittest's diff cuts the list, and the titles and durations are the clue
        episodes = WATCH.dialog_episodes()
        record = os.path.join(tempfile.gettempdir(), "mmdcli-focus-watch-%d.json" % int(time.time()))
        with open(record, "w", encoding="utf-8") as f:
            json.dump({"on_screen": WATCH.restored_hits, "dialog_episodes": episodes, "foreground": WATCH.foreground_hits,
                       "samples": WATCH.samples}, f, ensure_ascii=False, indent=1)
        self.assertEqual(WATCH.main_window_hits(), [], "the main window was on the screen; the record is in %s" % record)
        stayed = [e for e in episodes if e["samples"] >= 2]
        self.assertEqual(stayed, [], "a dialog stayed on the screen longer than one frame; the record is in %s" % record)


if __name__ == "__main__":
    unittest.main()
