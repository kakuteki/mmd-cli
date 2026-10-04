"""The ctypes declarations of mmd_cli.win32 against the Windows SDK (x64).

A wrong structure size or a missing argtypes declaration does not fail loudly: SendInput silently
did nothing while INPUT was 32 bytes, and a function called without argtypes raises "int too long to
convert" only for the handles that happen to have bit 31 set.
"""
import ctypes
import os
import re
import struct
import unittest
from ctypes import wintypes as wt
from unittest import mock

try:
    from mmd_cli import win32
except ImportError:          # not on Windows
    win32 = None

SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mmd_cli", "win32.py")
X64 = ctypes.sizeof(ctypes.c_void_p) == 8


def offsets(structure):
    return {name: getattr(structure, name).offset for name, _ in structure._fields_}


@unittest.skipUnless(win32 is not None and X64, "needs 64-bit Windows")
class StructTest(unittest.TestCase):
    def test_input_struct_matches_the_sdk(self):
        # winuser.h on x64: INPUT is 40 bytes, the union starts at 8 (after DWORD type and padding)
        self.assertEqual(ctypes.sizeof(win32._INPUT), 40)
        self.assertEqual(win32._INPUT.type.offset, 0)
        self.assertEqual(win32._INPUT.u.offset, 8)
        self.assertEqual(ctypes.sizeof(win32._MOUSEINPUT), 32)
        self.assertEqual(offsets(win32._MOUSEINPUT),
                         {"dx": 0, "dy": 4, "mouseData": 8, "dwFlags": 12, "time": 16, "dwExtraInfo": 24})
        self.assertEqual(ctypes.sizeof(win32._KEYBDINPUT), 24)
        self.assertEqual(offsets(win32._KEYBDINPUT), {"wVk": 0, "wScan": 2, "dwFlags": 4, "time": 8, "dwExtraInfo": 16})

    def test_startupinfo_and_process_information_sizes(self):
        # processthreadsapi.h on x64
        self.assertEqual(ctypes.sizeof(win32._STARTUPINFOW), 104)
        self.assertEqual(offsets(win32._STARTUPINFOW), {
            "cb": 0, "lpReserved": 8, "lpDesktop": 16, "lpTitle": 24, "dwX": 32, "dwY": 36, "dwXSize": 40,
            "dwYSize": 44, "dwXCountChars": 48, "dwYCountChars": 52, "dwFillAttribute": 56, "dwFlags": 60,
            "wShowWindow": 64, "cbReserved2": 66, "lpReserved2": 72, "hStdInput": 80, "hStdOutput": 88,
            "hStdError": 96})
        self.assertEqual(ctypes.sizeof(win32._PROCESS_INFORMATION), 24)
        self.assertEqual(offsets(win32._PROCESS_INFORMATION),
                         {"hProcess": 0, "hThread": 8, "dwProcessId": 16, "dwThreadId": 20})

    def test_drop_block_layout(self):
        # shellapi.h DROPFILES: pFiles (offset of the list) 20, pt, fNC, fWide 1, then UTF-16 names, double NUL
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)      # our own instance: nothing leaks into win32
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p
        handle = win32.make_drop_handle(["C:\\a.pmx"])
        try:
            size = kernel32.GlobalSize(handle)
            data = ctypes.string_at(kernel32.GlobalLock(handle), size)
            kernel32.GlobalUnlock(handle)
        finally:
            self.assertIsNone(kernel32.GlobalFree(handle))     # NULL means freed
        names = "C:\\a.pmx\0\0".encode("utf-16-le")
        self.assertEqual(size, 20 + len(names))
        self.assertEqual(struct.unpack_from("<IiiII", data, 0), (20, 0, 0, 0, 1))
        self.assertEqual(data[20:], names)
        self.assertTrue(data.endswith(b"\0\0\0\0"))


@unittest.skipUnless(win32 is not None, "needs Windows")
class DeclarationTest(unittest.TestCase):
    def used_functions(self):
        with open(SOURCE, encoding="utf-8") as f:
            source = f.read()
        found = sorted(set(re.findall(r"\b(user32|kernel32|winmm)\.(\w+)\(", source)))
        self.assertGreater(len(found), 30, "the scan of win32.py found too few calls")
        return found

    def test_every_declared_function_has_argtypes(self):
        missing = ["%s.%s" % (lib, name) for lib, name in self.used_functions()
                   if getattr(getattr(win32, lib), name).argtypes is None]
        self.assertEqual(missing, [])

    def test_functions_returning_handles_or_pointers_declare_restype(self):
        # the default restype is a 32-bit int: a 64-bit pointer or a handle with bit 31 set would be mangled
        for lib, name in (("user32", "GetForegroundWindow"), ("user32", "GetMenu"), ("user32", "GetSubMenu"),
                          ("user32", "GetWindow"), ("user32", "SetThreadDpiAwarenessContext"),
                          ("kernel32", "GlobalAlloc"), ("kernel32", "GlobalLock"), ("kernel32", "OpenProcess")):
            self.assertIs(getattr(getattr(win32, lib), name).restype, ctypes.c_void_p, "%s.%s" % (lib, name))
        self.assertIs(win32.kernel32.GetCurrentProcessId.restype, wt.DWORD)


@unittest.skipUnless(win32 is not None, "needs Windows")
class StyleTest(unittest.TestCase):
    def test_hide_and_reveal_pass_the_extended_style_as_unsigned(self):
        # GetWindowLongW returns a c_long: a style with bit 31 set comes back negative.  style() and
        # ex_style() mask it; hide_window / reveal_window must hand on the same unsigned value
        raw = -2147483648 | 0x00000080                  # bit 31 plus WS_EX_TOOLWINDOW, as the API would return it
        fake = mock.MagicMock()
        fake.GetWindowLongW.return_value = raw
        with mock.patch.object(win32, "user32", fake):
            win32.hide_window(7)
            win32.reveal_window(7)
        hidden, revealed = [c.args[2] for c in fake.SetWindowLongW.call_args_list]
        self.assertEqual(hidden, (raw & 0xFFFFFFFF) | win32.WS_EX_LAYERED | win32.WS_EX_NOACTIVATE)
        self.assertEqual(revealed, (raw & 0xFFFFFFFF) & ~win32.WS_EX_NOACTIVATE)
        self.assertTrue(all(0 <= v <= 0xFFFFFFFF for v in (hidden, revealed)), (hidden, revealed))


if __name__ == "__main__":
    unittest.main()
