"""the drawtext filters tools/overlay_text.py builds (no ffmpeg run)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import overlay_text  # noqa: E402


class DrawtextTest(unittest.TestCase):
    def test_a_fading_title_in_the_middle(self):
        cue = {"text": "x", "start": 1.0, "end": 4.0, "style": "title", "anim": "fade", "x": "center", "y": "middle"}
        f = overlay_text.drawtext(cue, "C:/tmp/cue00.txt")
        self.assertTrue(f.startswith("drawtext=fontfile='C\:/Windows/Fonts/meiryo"))
        self.assertIn("textfile='C\:/tmp/cue00.txt'", f)
        self.assertIn("x='(w-text_w)/2'", f)
        self.assertIn("y='(h-text_h)/2'", f)
        self.assertIn("enable='between(t,1.000,4.000)'", f)
        self.assertIn("alpha='if(lt(t,1.500),(t-1.000)/0.500,if(gt(t,3.500),(4.000-t)/0.500,1))'", f)
        self.assertIn("fontsize=96", f)

    def test_a_sliding_credit_at_the_bottom_right(self):
        cue = {"text": "x", "start": 0.0, "end": 2.0, "style": "credit", "anim": "slide-up", "x": "right", "y": "bottom"}
        f = overlay_text.drawtext(cue, "c.txt")
        self.assertIn("x='w-text_w-48'", f)
        self.assertIn("y='(h-text_h-48)+36*(1-min(1,(t-0.000)/0.600))'", f)
        self.assertIn("fontsize=28", f)

    def test_the_font_size_can_be_overridden_per_cue(self):
        f = overlay_text.drawtext({"text": "x", "start": 0, "end": 1, "style": "lyric", "fontsize": 60}, "c.txt")
        self.assertIn("fontsize=60", f)
        self.assertNotIn("fontsize=44", f)


if __name__ == "__main__":
    unittest.main()
