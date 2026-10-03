import os
import tempfile
import unittest

try:
    from mmd_cli import app
except ImportError:          # not on Windows
    app = None


OUTSIDE = chr(0xD55C)       # a Hangul syllable: not in cp932, the code page of Japanese Windows


def outside_code_page(text):
    try:
        text.encode("mbcs")
    except UnicodeEncodeError:
        return True
    return False


@unittest.skipUnless(app is not None, "needs Windows")
class PathTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def make(self, name):
        path = os.path.join(self.folder, name)
        with open(path, "wb"):
            pass
        return path

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            app.check_input_file(os.path.join(self.folder, "none.pmx"), (".pmx",), "a model")

    def test_wrong_extension(self):
        with self.assertRaises(app.MmdError):
            app.check_input_file(self.make("a.txt"), (".pmx", ".pmd"), "a model")

    def test_returns_the_absolute_path(self):
        path = self.make("a.PMX")
        self.assertEqual(app.check_input_file(path, (".pmx",), "a model"), os.path.abspath(path))

    @unittest.skipUnless(outside_code_page(OUTSIDE), "the system code page can encode the test character")
    def test_names_mmd_cannot_open_are_rejected_early(self):
        # MMD is an ANSI program: a path with characters outside the system code page never reaches it intact
        with self.assertRaises(app.MmdError) as ctx:
            app.check_input_file(self.make(OUTSIDE + ".pmx"), (".pmx",), "a model")
        self.assertIn("code page", str(ctx.exception))

    @unittest.skipUnless(outside_code_page(OUTSIDE), "the system code page can encode the test character")
    def test_output_paths_are_checked_too(self):
        with self.assertRaises(app.MmdError):
            app.check_output_file(os.path.join(self.folder, OUTSIDE + ".png"))
        self.assertEqual(app.check_output_file(os.path.join(self.folder, "ok.png")),
                         os.path.abspath(os.path.join(self.folder, "ok.png")))


@unittest.skipUnless(app is not None, "needs Windows")
class HomeTest(unittest.TestCase):
    def test_home_is_an_absolute_path_with_backslashes(self):
        # the file dialogs of MMD refuse paths written with forward slashes
        folder = tempfile.mkdtemp()
        previous = os.environ.get("MMD_CLI_HOME")
        os.environ["MMD_CLI_HOME"] = folder.replace(os.sep, "/") + "/nested/home"
        try:
            home = app.home_dir()
        finally:
            if previous is None:
                del os.environ["MMD_CLI_HOME"]
            else:
                os.environ["MMD_CLI_HOME"] = previous
        self.assertNotIn("/", home)
        self.assertEqual(home, os.path.join(folder, "nested", "home"))
        self.assertTrue(os.path.isdir(home))


if __name__ == "__main__":
    unittest.main()
