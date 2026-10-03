"""Measure where MMD puts its controls, for docs/controls-v932.json and the README figures.

    python tools/dump_controls.py --pid PID [--capture-model docs/img/mmd-window-model.png]

The MMD window must NOT be minimized (a minimized window collapses its layout).  To keep it out of
sight, move it off-screen first; this script never activates or moves it.  At least one model has
to be loaded: the layout is read once in camera mode and once with the first model selected.
"""
import argparse
import ctypes
import json
import os
import struct
import sys
import zlib
from ctypes import wintypes as wt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mmd_cli import app, win32  # noqa: E402
from mmd_cli.ids import Ctl  # noqa: E402

user32 = win32.user32
gdi32 = ctypes.WinDLL("gdi32")
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]


def capture(hwnd, path):
    """PrintWindow into a PNG.  A window that is off-screen keeps its controls but loses the 3D view."""
    _, _, width, height = win32.window_rect(hwnd)
    window_dc = user32.GetDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(hwnd, memory_dc, 2)
    gdi32.SelectObject(memory_dc, previous)
    header = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0), 52)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, header, 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    raw = bytearray()
    data = pixels.raw
    for row in range(height):
        line = data[row * width * 4:(row + 1) * width * 4]
        rgb = bytearray(width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        raw.append(0)
        raw += rgb

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def layout(mmd):
    wx, wy, _, _ = win32.window_rect(mmd.hwnd)
    out = {}
    for cid in sorted(mmd._controls):
        hwnd = mmd._controls[cid]
        x, y, w, h = win32.window_rect(hwnd)
        out[cid] = {"rect": [x - wx, y - wy, w, h], "visible": win32.is_visible(hwnd)}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--capture-model", help="also save a capture of the window with a model selected")
    args = parser.parse_args()
    mmd = app.Mmd.attach(args.pid)
    if win32.is_iconic(mmd.hwnd):
        raise SystemExit("the window is minimized: its layout is collapsed. Restore it (off-screen is fine) first.")
    if not mmd.models():
        raise SystemExit("load a model first: the layout with a model selected is measured too")
    mmd.ctl(Ctl.FRAME)
    mmd.select_model(None)
    camera = layout(mmd)
    mmd.select_model(0)
    mmd.wait_quiet()
    model = layout(mmd)
    if args.capture_model:
        capture(mmd.hwnd, os.path.abspath(args.capture_model))
    _, _, width, height = win32.window_rect(mmd.hwnd)
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(mmd.hwnd, ctypes.byref(origin))
    wx, wy, _, _ = win32.window_rect(mmd.hwnd)
    controls = []
    for cid in sorted(camera):
        info = mmd.control_get(cid)
        controls.append({"id": cid, "class": info["class"], "text": info["text"],
                         "camera_mode": camera[cid], "model_mode": model[cid]})
    data = {"note": "MikuMikuDance v9.32 (x64). rect = [x, y, w, h] in window coordinates at 96 dpi, measured with the "
                    "window at its normal size. Several panels move or hide when a model is selected.",
            "window": [width, height], "client_origin": [origin.x - wx, origin.y - wy],
            "controls": controls, "menu": mmd.menu_items()}
    target = os.path.join(ROOT, "docs", "controls-v932.json")
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote", os.path.relpath(target, ROOT), len(controls), "controls, window", width, "x", height)


if __name__ == "__main__":
    main()
