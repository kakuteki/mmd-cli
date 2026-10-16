"""tools/mvi/mouth.py (口): tools/lip_check on a synthetic song (tests.test_lip_check: 4 lines of known times) with mouths
of known leads; judged against ITU-R BT.1359-1, the onsets outside it are the places."""
import os
import shutil
import tempfile
import unittest

from tests import mvi_fixtures as MF
from tests.test_lip_check import face_leading, synth, write_wav
from mvi import mouth, report

F = 420


def rep_events(res):
    return report.mark_listed({"measures": res["rows"], "events": res["events"]})["events"]


class MouthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        x, cls.morae = synth()
        cls.vocal = os.path.join(cls.folder, "voice.wav")
        write_wav(cls.vocal, x)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def measure(self, lead, vocal=True):
        names, pos, rot = MF.pack(F)
        motion, _ = face_leading(self.morae, lead)
        spec = {"vocal": self.vocal} if vocal else {}
        return mouth.measure(MF.FakeMeasured(MF.FakeVersion(names, pos, rot, spec=spec, merged=motion)))

    def rows(self, res):
        return {r["id"]: r for r in res["rows"]}

    def test_a_mouth_a_little_ahead_of_the_voice_is_in_the_window(self):
        res = self.measure(0.05)
        r = self.rows(res)
        self.assertAlmostEqual(r["mouth.lag_median_ms"]["value"], 50.0, delta=25.0)
        self.assertEqual(r["mouth.lag_median_ms"]["judge"]["word"], "中")
        self.assertEqual(r["mouth.lag_open_ms"]["judge"]["word"], "中")

    def test_a_mouth_behind_the_voice_is_out_of_the_window_and_its_onsets_are_places(self):
        # (a mouth far ahead pairs with the next syllable's rise, the nearest: lip_check reads it late; a late mouth
        # pairs with its own)
        res = self.measure(-0.10)
        r = self.rows(res)
        self.assertLess(r["mouth.lag_median_ms"]["value"], -45.0)
        self.assertEqual(r["mouth.lag_median_ms"]["judge"]["word"], "下へ外")
        self.assertEqual(r["mouth.lag_open_ms"]["judge"]["word"], "下へ外")
        closed = [e for e in rep_events(res) if e["id"] == "mouth.late_pct"]
        self.assertTrue(all(not e["listed"] for e in closed))
        rep = report.mark_listed({"measures": res["rows"], "events": res["events"]})
        listed = [e for e in rep["events"] if e["listed"] and e["id"] == "mouth.lag_open_ms"]
        self.assertGreater(len(listed), 5)
        self.assertTrue(all(e["value"] < -45.0 for e in listed))

    def test_without_a_voice_the_mouth_is_not_measured(self):
        r = self.rows(self.measure(0.05, vocal=False))
        self.assertIsNone(r["mouth.lag_median_ms"]["value"])


if __name__ == "__main__":
    unittest.main()
