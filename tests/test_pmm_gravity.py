"""tools/pmm_gravity.py: a copy of an MMD project (.pmm) whose physics gravity is changed in the current setting and in
every gravity key, with every other byte the same; and pmm.loads(positions=...) that tells where those fields are."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

from mmd_cli.formats import pmm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pmm_gravity  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "scene_v932.pmm")
TOOL = os.path.join(ROOT, "tools", "pmm_gravity.py")
KEYS_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "gravity_keys_v932.pmm")
RESAVED_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "gravity_keys_g1225_n20_resaved_v932.pmm")


def read(path):
    with open(path, "rb") as f:
        return f.read()


def with_one_key(data, frame=300, acceleration=5.0):
    """the fixture with one gravity key more after the frame-0 key (index 1, links 0/0, noise off), its count set to 1"""
    pos = {}
    pmm.loads(data, positions=pos)
    count_at = pos["gravity_frames"][0] + 22          # after the frame-0 key: flag, noise, acceleration, direction, selected
    assert struct.unpack_from("<i", data, count_at)[0] == 0
    key = struct.pack("<4iBif3fB", 1, frame, 0, 0, 0, 10, acceleration, 0.0, -1.0, 0.0, 0)
    return data[:count_at] + struct.pack("<i", 1) + key + data[count_at + 4:]


class PositionsTest(unittest.TestCase):
    def test_the_positions_point_at_the_gravity_fields(self):
        data = read(FIXTURE)
        pos = {}
        p = pmm.loads(data, positions=pos)
        g, cur = p["gravity"], pos["gravity_current"]
        self.assertEqual(struct.unpack_from("<f", data, cur)[0], g["current"]["acceleration"])
        self.assertEqual(struct.unpack_from("<i", data, cur + 4)[0], g["current"]["noise"])
        self.assertEqual(struct.unpack_from("<3f", data, cur + 8), g["current"]["direction"])
        self.assertEqual(data[cur + 20] != 0, g["current"]["noise_enabled"])
        self.assertEqual(len(pos["gravity_frames"]), 1 + len(g["keys"]))
        at = pos["gravity_frames"][0]
        self.assertEqual(data[at] != 0, g["init"]["noise_enabled"])
        self.assertEqual(struct.unpack_from("<i", data, at + 1)[0], g["init"]["noise"])
        self.assertEqual(struct.unpack_from("<f", data, at + 5)[0], g["init"]["acceleration"])
        self.assertEqual(struct.unpack_from("<3f", data, at + 9), g["init"]["direction"])

    def test_the_positions_of_a_later_key(self):
        data = with_one_key(read(FIXTURE), frame=300, acceleration=5.0)
        pos = {}
        p = pmm.loads(data, positions=pos)
        self.assertEqual([k["frame"] for k in p["gravity"]["keys"]], [300])
        self.assertEqual(struct.unpack_from("<f", data, pos["gravity_frames"][1] + 5)[0], 5.0)

    def test_loads_reads_the_same_with_or_without_positions(self):
        data = read(FIXTURE)
        self.assertEqual(pmm.loads(data), pmm.loads(data, positions={}))


class SavedByMmdTest(unittest.TestCase):
    """a project MMD 9.32 saved itself (hinata, 2026-10-16): `new`, then 登録 in the 重力設定 window (menu 266) at frames
    300 and 600, then `save`.  The later keys' layout is MMD's, not the test's"""

    def test_mmd_wrote_two_later_keys(self):
        g = pmm.loads(read(KEYS_FIXTURE))["gravity"]
        self.assertEqual([k["frame"] for k in g["keys"]], [300, 600])
        self.assertEqual([(k["pre"], k["next"]) for k in g["keys"]], [(0, 2), (1, 0)])
        self.assertEqual((g["init"]["pre"], g["init"]["next"]), (0, 1))
        for part in [g["current"], g["init"]] + g["keys"]:
            self.assertAlmostEqual(part["acceleration"], 9.8, 5)
            self.assertEqual((part["direction"], part["noise"], part["noise_enabled"]), ((0.0, -1.0, 0.0), 10, False))

    def test_every_key_mmd_wrote_is_changed_and_nothing_else(self):
        data = read(KEYS_FIXTURE)
        out = pmm_gravity.with_gravity(data, acceleration=12.25, direction=(0.0, -1.0, 0.25), noise=20)
        g = pmm.loads(out)["gravity"]
        for part in [g["current"], g["init"]] + g["keys"]:
            self.assertAlmostEqual(part["acceleration"], 12.25, 6)
            self.assertEqual((part["direction"], part["noise"], part["noise_enabled"]), ((0.0, -1.0, 0.25), 20, True))
        self.assertEqual([k["frame"] for k in g["keys"]], [300, 600])
        changed = [i for i in range(len(data)) if data[i] != out[i]]
        pos = {}
        pmm.loads(data, positions=pos)
        starts = [pos["gravity_current"]] + pos["gravity_frames"]
        self.assertEqual(len(starts), 4)
        self.assertTrue(all(any(s <= i < s + 21 for s in starts) for i in changed))
        for s in starts:                                    # each of the four places got its new acceleration
            self.assertTrue(any(s <= i < s + 21 for i in changed))
        a, b = pmm.loads(data), pmm.loads(out)
        a.pop("gravity")
        b.pop("gravity")
        self.assertEqual(a, b)

    def test_mmd_reads_what_was_written_noise_too(self):
        # the copy with --acceleration 12.25 --noise 20, opened by MMD 9.32 (`open`) and saved again (`save`): MMD kept
        # every field of every key, the noise on with its amount included (its `dump` shows 12.25 as well)
        written = pmm.loads(pmm_gravity.with_gravity(read(KEYS_FIXTURE), acceleration=12.25, noise=20))["gravity"]
        resaved = pmm.loads(read(RESAVED_FIXTURE))["gravity"]
        self.assertEqual(resaved, written)
        self.assertEqual([(k["noise_enabled"], k["noise"]) for k in [resaved["current"], resaved["init"]] + resaved["keys"]],
                         [(True, 20)] * 4)


class GravityTest(unittest.TestCase):
    def test_the_acceleration_of_the_current_setting_and_the_frame_0_key(self):
        data = read(FIXTURE)
        g = pmm.loads(pmm_gravity.with_gravity(data, acceleration=12.25))["gravity"]
        self.assertAlmostEqual(g["current"]["acceleration"], 12.25, 6)
        self.assertAlmostEqual(g["init"]["acceleration"], 12.25, 6)
        before = pmm.loads(data)["gravity"]
        for part in ("current", "init"):
            for k in ("noise", "noise_enabled", "direction"):
                self.assertEqual(g[part][k], before[part][k])

    def test_every_later_key_too(self):
        data = with_one_key(read(FIXTURE), frame=300, acceleration=5.0)
        g = pmm.loads(pmm_gravity.with_gravity(data, acceleration=12.25))["gravity"]
        self.assertEqual([round(k["acceleration"], 6) for k in g["keys"]], [12.25])
        self.assertEqual([k["frame"] for k in g["keys"]], [300])

    def test_nothing_else_changes(self):
        data = read(FIXTURE)
        out = pmm_gravity.with_gravity(data, acceleration=12.25, direction=(0.0, -1.0, 0.25), noise=20)
        self.assertEqual(len(out), len(data))
        pos = {}
        pmm.loads(data, positions=pos)
        cur, at = pos["gravity_current"], pos["gravity_frames"][0]
        allowed = set(range(cur, cur + 21)) | set(range(at, at + 21))
        changed = {i for i in range(len(data)) if data[i] != out[i]}
        self.assertTrue(changed)
        self.assertLessEqual(changed, allowed)
        a, b = pmm.loads(data), pmm.loads(out)
        a.pop("gravity")
        b.pop("gravity")
        self.assertEqual(a, b)

    def test_direction_and_noise(self):
        data = read(FIXTURE)
        g = pmm.loads(pmm_gravity.with_gravity(data, direction=(0.0, -1.0, 0.25), noise=20))["gravity"]
        for part in ("current", "init"):
            self.assertEqual(g[part]["direction"], (0.0, -1.0, 0.25))
            self.assertEqual((g[part]["noise_enabled"], g[part]["noise"]), (True, 20))
            self.assertAlmostEqual(g[part]["acceleration"], 9.8, 5)
        off = pmm.loads(pmm_gravity.with_gravity(pmm_gravity.with_gravity(data, noise=20), noise=False))["gravity"]
        self.assertEqual((off["current"]["noise_enabled"], off["init"]["noise_enabled"]), (False, False))
        self.assertEqual(off["current"]["noise"], 20)          # the amount stays, as MMD keeps it when the box is cleared

    def test_a_noise_that_does_not_read_back_is_refused(self):
        data = read(FIXTURE)
        real = pmm.loads

        def lying(raw, **kw):                  # the copy reads back with the noise MMD would not see
            out = real(raw, **kw)
            if raw != data:
                for part in [out["gravity"]["current"], out["gravity"]["init"]] + out["gravity"]["keys"]:
                    part["noise"] += 1
            return out
        with unittest.mock.patch.object(pmm_gravity.pmm, "loads", lying):
            with self.assertRaises(AssertionError):
                pmm_gravity.with_gravity(data, noise=20)
            with self.assertRaises(AssertionError):
                pmm_gravity.with_gravity(data, acceleration=12.25)      # a field not asked for must not move either

    def test_a_noise_switched_off_that_reads_back_on_is_refused(self):
        data = pmm_gravity.with_gravity(read(FIXTURE), noise=20)
        real = pmm.loads

        def lying(raw, **kw):
            out = real(raw, **kw)
            if raw != data:
                out["gravity"]["init"]["noise_enabled"] = True
            return out
        with unittest.mock.patch.object(pmm_gravity.pmm, "loads", lying):
            with self.assertRaises(AssertionError):
                pmm_gravity.with_gravity(data, noise=False)

    def test_bad_values_are_refused(self):
        data = read(FIXTURE)
        for kwargs in ({"acceleration": -1.0}, {"acceleration": float("nan")}, {"direction": (0.0, 0.0, 0.0)},
                       {"direction": (0.0, -1.0)}, {"noise": -3}, {"noise": 2.5}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                pmm_gravity.with_gravity(data, **kwargs)
        with self.assertRaises(ValueError):
            pmm_gravity.with_gravity(data)                    # nothing to change
        with self.assertRaises(pmm.PmmFormatError):
            pmm_gravity.with_gravity(b"not a project at all", acceleration=12.25)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "g.pmm")
            r = subprocess.run([sys.executable, TOOL, FIXTURE, out, "--acceleration", "12.25"], capture_output=True,
                               text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            self.assertAlmostEqual(report["before"]["current"]["acceleration"], 9.8, 5)
            self.assertAlmostEqual(report["after"]["current"]["acceleration"], 12.25, 5)
            self.assertEqual(report["keys"], 1)
            self.assertAlmostEqual(pmm.loads(read(out))["gravity"]["init"]["acceleration"], 12.25, 5)
            same = subprocess.run([sys.executable, TOOL, out, out, "--acceleration", "9.8"], capture_output=True,
                                  text=True, encoding="utf-8")
            self.assertNotEqual(same.returncode, 0)
            self.assertAlmostEqual(pmm.loads(read(out))["gravity"]["init"]["acceleration"], 12.25, 5)


if __name__ == "__main__":
    unittest.main()
