"""Thin ctypes layer over user32 / kernel32.  Knows nothing about MMD.

Everything here works on windows of another process without activating them.
"""
import contextlib
import ctypes
import os
import struct
import subprocess
import time
from ctypes import wintypes as wt

if os.name != "nt":
    raise ImportError("mmd_cli.win32 needs Windows")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

# MMD is not DPI aware: use the same (virtualised) coordinates it sees
try:
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-1))
except AttributeError:
    pass

WM_NULL = 0x0000
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
WM_VSCROLL = 0x0115
WM_DROPFILES = 0x0233
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BM_CLICK = 0x00F5
BN_CLICKED = 0
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_SETCURSEL = 0x014E
CBN_SELCHANGE = 1
LB_GETTEXT = 0x0189
LB_GETTEXTLEN = 0x018A
LB_GETCOUNT = 0x018B
TBM_GETPOS = 0x0400
TBM_GETRANGEMIN = 0x0401
TBM_GETRANGEMAX = 0x0402
TBM_SETPOS = 0x0405
TB_THUMBPOSITION = 4
TB_ENDTRACK = 8
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOWMINNOACTIVE = 7
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SMTO_NORMAL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
MF_BYPOSITION = 0x0400
MF_GRAYED = 0x0001
MF_CHECKED = 0x0008
MF_SEPARATOR = 0x0800
BS_TYPEMASK = 0x000F
IDOK = 1
IDCANCEL = 2
IDYES = 6

# far outside any monitor; dialogs are parked here
OFFSCREEN_X = -32000 + 4000
OFFSCREEN_Y = 200

_ENUM_PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [_ENUM_PROC, wt.LPARAM]
user32.EnumChildWindows.argtypes = [wt.HWND, _ENUM_PROC, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, ctypes.c_void_p, wt.UINT, wt.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, ctypes.c_void_p]
user32.PostMessageW.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetDlgCtrlID.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowEnabled.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD]
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND
user32.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetMenu.argtypes = [wt.HWND]
user32.GetMenu.restype = wt.HMENU
user32.GetMenuItemCount.argtypes = [wt.HMENU]
user32.GetSubMenu.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wt.HMENU
user32.GetMenuItemID.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wt.UINT
user32.GetMenuStringW.argtypes = [wt.HMENU, wt.UINT, wt.LPWSTR, ctypes.c_int, wt.UINT]
user32.GetMenuState.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.GetMenuState.restype = wt.UINT
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.CloseHandle.argtypes = [wt.HANDLE]


# ---- windows ---------------------------------------------------------------------------------

def window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_windows(pid=None, cls=None, visible_only=False):
    found = []

    def visit(hwnd, _):
        if pid is not None and window_pid(hwnd) != pid:
            return True
        if cls is not None and class_name(hwnd) != cls:
            return True
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        found.append(hwnd)
        return True

    user32.EnumWindows(_ENUM_PROC(visit), 0)
    return found


def child_windows(hwnd):
    found = []

    def visit(child, _):
        found.append(child)
        return True

    user32.EnumChildWindows(hwnd, _ENUM_PROC(visit), 0)
    return found


def is_window(hwnd):
    return bool(user32.IsWindow(hwnd))


def is_visible(hwnd):
    return bool(user32.IsWindowVisible(hwnd))


def is_enabled(hwnd):
    return bool(user32.IsWindowEnabled(hwnd))


def is_iconic(hwnd):
    return bool(user32.IsIconic(hwnd))


def control_id(hwnd):
    return user32.GetDlgCtrlID(hwnd)


def style(hwnd):
    return user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF


def ex_style(hwnd):
    return user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def window_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def foreground_window():
    return user32.GetForegroundWindow()


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]       # 40 bytes in all on x64, as Windows expects
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
user32.AllowSetForegroundWindow.restype = wt.BOOL
user32.LockSetForegroundWindow.argtypes = [wt.UINT]
user32.LockSetForegroundWindow.restype = wt.BOOL
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = wt.DWORD


def give_foreground_back(hwnd):
    """Return the foreground to hwnd after another process took it.  A process may only set the
    foreground when it is allowed to; injecting a zero-length mouse move makes this process the
    last input provider, which is one of the allowed cases.  Returns True when hwnd is in front."""
    if not user32.IsWindow(hwnd):
        return False
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
        return True
    move = _INPUT()
    move.type = 0                                  # INPUT_MOUSE
    move.mi.dwFlags = 0x0001                       # MOUSEEVENTF_MOVE, dx = dy = 0: nothing visible happens
    user32.SendInput(1, ctypes.byref(move), ctypes.sizeof(_INPUT))
    user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


def send_key_return():
    """press and release Enter through SendInput (goes to whichever window has the focus)"""
    down = _INPUT()
    down.type = 1                                   # INPUT_KEYBOARD
    down.ki.wVk = VK_RETURN
    up = _INPUT()
    up.type = 1
    up.ki.wVk = VK_RETURN
    up.ki.dwFlags = 0x0002                          # KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    time.sleep(0.05)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))


def can_set_foreground():
    """True when this process is currently allowed to take the foreground (Windows grants that to
    the foreground process and to processes it started, as long as the user stays there).
    Granting the right to ourselves is a no-op, so this is a pure query."""
    return bool(user32.AllowSetForegroundWindow(kernel32.GetCurrentProcessId()))


def lock_foreground(lock):
    """LockSetForegroundWindow: while locked, no process may take the foreground (the user can
    still lift the lock by pressing ALT or clicking another window).  Only a process that is
    allowed to take the foreground may lock; returns whether the call succeeded."""
    return bool(user32.LockSetForegroundWindow(1 if lock else 2))


# ---- messages --------------------------------------------------------------------------------

def send(hwnd, msg, wparam=0, lparam=None, timeout_ms=5000, abort_if_hung=True):
    """SendMessageTimeout.  Returns the result, or None when the window did not answer in time."""
    result = ctypes.c_size_t(0)
    flags = SMTO_ABORTIFHUNG if abort_if_hung else SMTO_NORMAL
    ok = user32.SendMessageTimeoutW(hwnd, msg, wparam, lparam, flags, int(timeout_ms), ctypes.byref(result))
    if not ok:
        return None
    return ctypes.c_ssize_t(result.value).value


def post(hwnd, msg, wparam=0, lparam=None):
    return bool(user32.PostMessageW(hwnd, msg, wparam, lparam))


def command_wparam(control, code=BN_CLICKED):
    return ((code & 0xFFFF) << 16) | (control & 0xFFFF)


def get_text(hwnd, timeout_ms=2000):
    length = send(hwnd, WM_GETTEXTLENGTH, timeout_ms=timeout_ms) or 0
    buf = ctypes.create_unicode_buffer(length + 2)
    send(hwnd, WM_GETTEXT, length + 1, buf, timeout_ms=timeout_ms)
    return buf.value


def set_text(hwnd, text):
    return send(hwnd, WM_SETTEXT, 0, ctypes.create_unicode_buffer(text))


def post_enter(hwnd):
    post(hwnd, WM_KEYDOWN, VK_RETURN, 0x001C0001)
    post(hwnd, WM_KEYUP, VK_RETURN, 0xC01C0001)


# ---- controls --------------------------------------------------------------------------------

def _list_texts(hwnd, count_msg, len_msg, text_msg):
    count = send(hwnd, count_msg) or 0
    items = []
    for i in range(max(count, 0)):
        length = send(hwnd, len_msg, i) or 0
        buf = ctypes.create_unicode_buffer(max(length, 0) + 2)
        send(hwnd, text_msg, i, buf)
        items.append(buf.value)
    return items


def combo_items(hwnd):
    return _list_texts(hwnd, CB_GETCOUNT, CB_GETLBTEXTLEN, CB_GETLBTEXT)


def combo_selection(hwnd):
    index = send(hwnd, CB_GETCURSEL)
    return -1 if index is None else index


def listbox_items(hwnd):
    return _list_texts(hwnd, LB_GETCOUNT, LB_GETTEXTLEN, LB_GETTEXT)


def button_checked(hwnd):
    return (send(hwnd, BM_GETCHECK) or 0) == 1


def trackbar(hwnd):
    return {"pos": send(hwnd, TBM_GETPOS), "min": send(hwnd, TBM_GETRANGEMIN), "max": send(hwnd, TBM_GETRANGEMAX)}


# ---- menus -----------------------------------------------------------------------------------

def menu_items(hwnd):
    """flat list of the command items of a window's menu bar"""
    out = []

    def walk(menu, path):
        count = user32.GetMenuItemCount(menu)
        for pos in range(max(count, 0)):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(menu, pos, buf, 256, MF_BYPOSITION)
            state = user32.GetMenuState(menu, pos, MF_BYPOSITION)
            sub = user32.GetSubMenu(menu, pos)
            if sub:
                walk(sub, path + [buf.value])
            elif not (state & MF_SEPARATOR) and buf.value:
                out.append({"id": user32.GetMenuItemID(menu, pos), "path": path + [buf.value],
                            "checked": bool(state & MF_CHECKED), "grayed": bool(state & MF_GRAYED)})

    menu = user32.GetMenu(hwnd)
    if menu:
        walk(menu, [])
    return out


# ---- visibility ------------------------------------------------------------------------------

def hide_window(hwnd):
    """make a window invisible to the user without closing it: fully transparent, off-screen, and
    never chosen by Windows as the next active window (e.g. when the user closes the window they
    are working in while this one is open)"""
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style(hwnd) | WS_EX_LAYERED | WS_EX_NOACTIVATE)
    user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
    move_offscreen(hwnd)


def move_offscreen(hwnd):
    user32.SetWindowPos(hwnd, None, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def move_window(hwnd, x, y):
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def reveal_window(hwnd, x=100, y=100):
    """undo hide_window (for a person who wants to answer a dialog by hand)"""
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style(hwnd) & ~WS_EX_NOACTIVATE)
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


user32.GetLayeredWindowAttributes.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD), ctypes.POINTER(ctypes.c_ubyte),
                                              ctypes.POINTER(wt.DWORD)]


def window_alpha(hwnd):
    """opacity 0-255 of a layered window (255 when the window is not layered)"""
    key, alpha, flags = wt.DWORD(0), ctypes.c_ubyte(255), wt.DWORD(0)
    if not user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)):
        return 255
    return alpha.value if flags.value & LWA_ALPHA else 255


user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND


def owner_window(hwnd):
    return user32.GetWindow(hwnd, 4)        # GW_OWNER


def is_hidden(hwnd):
    return window_rect(hwnd)[0] <= OFFSCREEN_X + 100


def minimize_no_activate(hwnd):
    user32.ShowWindowAsync(hwnd, SW_SHOWMINNOACTIVE)


def hide(hwnd):
    """SW_HIDE: the window keeps running but has no taskbar button and is not on screen"""
    user32.ShowWindowAsync(hwnd, SW_HIDE)


def show_no_activate(hwnd):
    user32.ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE)


# ---- drag and drop ---------------------------------------------------------------------------

def make_drop_handle(paths):
    """HDROP for WM_DROPFILES.  It must be POSTED: the system copies the handle into the target
    process only on the post path (a sent WM_DROPFILES arrives with a handle the target cannot read)."""
    files = "".join(p + "\0" for p in paths) + "\0"
    data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + files.encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0042, len(data))
    if not handle:
        raise OSError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


# ---- processes -------------------------------------------------------------------------------

class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD)]


kernel32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                    ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(_STARTUPINFOW),
                                    ctypes.POINTER(_PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = wt.BOOL


def launch_detached(exe, args=(), show=SW_SHOWMINNOACTIVE):
    """start a GUI program that outlives this process, with the given initial show state"""
    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    startup.dwFlags = 0x00000001                # STARTF_USESHOWWINDOW
    startup.wShowWindow = show
    info = _PROCESS_INFORMATION()
    command = subprocess.list2cmdline([exe] + list(args))
    detached = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    breakaway = 0x01000000                      # CREATE_BREAKAWAY_FROM_JOB (refused inside some job objects)
    for flags in (detached | breakaway, detached):
        buffer = ctypes.create_unicode_buffer(command)
        if kernel32.CreateProcessW(exe, buffer, None, None, False, flags, None, os.path.dirname(exe),
                                   ctypes.byref(startup), ctypes.byref(info)):
            kernel32.CloseHandle(info.hThread)
            kernel32.CloseHandle(info.hProcess)
            return info.dwProcessId
        error = ctypes.get_last_error()
    raise OSError(error, "CreateProcess failed for %s" % exe)


advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi32.OpenProcessToken.restype = wt.BOOL
advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
advapi32.GetTokenInformation.restype = wt.BOOL
advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]
advapi32.ConvertSidToStringSidW.restype = wt.BOOL
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.LocalFree.argtypes = [wt.HLOCAL]
kernel32.LocalFree.restype = wt.HLOCAL


def current_user_sid():
    """the SID of the account this process runs as, as text (S-1-5-21-...)"""
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wt.DWORD(0)
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))                        # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]       # TOKEN_USER.User.Sid comes first
        text = wt.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def process_alive(pid):
    """True or False; None when the process cannot be opened (another account or integrity level):
    not knowing is not the same as dead"""
    handle = kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
    if not handle:
        return None if ctypes.get_last_error() == 5 else False      # 5: ERROR_ACCESS_DENIED
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102   # WAIT_TIMEOUT: still running
    finally:
        kernel32.CloseHandle(handle)


def terminate_process(pid):
    handle = kernel32.OpenProcess(0x0001, False, pid)        # PROCESS_TERMINATE
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


winmm.timeBeginPeriod.argtypes = [wt.UINT]
winmm.timeBeginPeriod.restype = wt.UINT             # MMRESULT
winmm.timeEndPeriod.argtypes = [wt.UINT]
winmm.timeEndPeriod.restype = wt.UINT


@contextlib.contextmanager
def timer_resolution(ms=1):
    """short sleeps (1 ms polling) need the multimedia timer resolution"""
    winmm.timeBeginPeriod(ms)
    try:
        yield
    finally:
        winmm.timeEndPeriod(ms)
