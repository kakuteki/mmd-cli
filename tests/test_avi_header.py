"""reading what an AVI file says about itself (size, frame count, frame rate), without MMD"""
import os
import struct
import tempfile
import unittest

try:
    from mmd_cli import app
except ImportError:          # not on Windows
    app = None


def chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def lst(kind, *members):
    body = kind + b"".join(members)
    return chunk(b"LIST", body)


def avih(frames, width, height, micro_per_frame=33333):
    fields = [micro_per_frame, 0, 0, 0, frames, 0, 1, 0, width, height, 0, 0, 0, 0]
    return chunk(b"avih", struct.pack("<14I", *fields))


def dmlh(total_frames):
    return chunk(b"dmlh", struct.pack("<I", total_frames) + b"\x00" * 244)


def riff(*members):
    body = b"AVI " + b"".join(members)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def write(data):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "x.avi")
    with open(path, "wb") as f:
        f.write(data)
    return path


@unittest.skipUnless(app is not None, "needs Windows")
class AviHeaderTest(unittest.TestCase):
    def test_plain_avi_header(self):
        path = write(riff(lst(b"hdrl", avih(21, 320, 180))))
        self.assertEqual(app._avi_info(path), {"size": [320, 180], "frames": 21, "fps": 30})

    def test_opendml_total_frames_win_over_the_first_segment_count(self):
        # past 1 GB a Video for Windows AVI continues in AVIX segments; avih counts only the first one
        path = write(riff(lst(b"hdrl", avih(3000, 1280, 720), lst(b"odml", dmlh(7743)))))
        self.assertEqual(app._avi_info(path)["frames"], 7743)

    def test_a_dmlh_pattern_inside_the_movie_data_is_not_mistaken_for_the_header(self):
        # review 2 (6.1): the header is found by walking the RIFF structure, not by searching bytes
        frame = chunk(b"00db", b"\x00" * 100 + dmlh(999) + b"\x00" * 100)     # pixel data that looks like a chunk
        path = write(riff(lst(b"hdrl", avih(21, 320, 180)), lst(b"movi", frame)))
        self.assertEqual(app._avi_info(path)["frames"], 21)

    def test_three_streams_push_dmlh_far_in_but_it_is_still_read(self):
        # each stream list of an MMD AVI carries a 32,024 byte OpenDML super index; a fixed read window missed dmlh
        streams = [lst(b"strl", chunk(b"strh", b"\x00" * 56), chunk(b"indx", b"\x00" * 32024)) for _ in range(3)]
        path = write(riff(lst(b"hdrl", avih(3000, 1280, 720), *streams, lst(b"odml", dmlh(7743)))))
        self.assertEqual(app._avi_info(path)["frames"], 7743)

    def test_not_an_avi(self):
        path = write(b"RIFF\x04\x00\x00\x00WAVE")
        self.assertEqual(app._avi_info(path), {})
        path = write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        self.assertEqual(app._avi_info(path), {})

    def test_zero_frame_time_gives_no_fps(self):
        path = write(riff(lst(b"hdrl", avih(5, 64, 48, micro_per_frame=0))))
        self.assertIsNone(app._avi_info(path)["fps"])


if __name__ == "__main__":
    unittest.main()
