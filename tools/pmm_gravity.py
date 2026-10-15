"""Copy an MMD project (.pmm) with its physics gravity changed: what MMD's 物理演算 > 重力設定 window holds (the
acceleration, the noise and the direction), in the current setting and in every gravity key (the key at frame 0 and any
registered later, since Ver. 9.00), so that playback and AVI output use it from the first frame.  Every other byte of the
file stays as it was; the copy is read back and checked.

    python tools/pmm_gravity.py IN.pmm OUT.pmm [--acceleration A] [--direction X Y Z] [--noise N | --no-noise]

mmd-cli has no command for the gravity window, so a scene that needs another gravity is built as usual, saved
(`mmd save P.pmm`), changed here and opened again (`mmd open P_g.pmm`) before rendering.  The acceleration is the number
the window shows (9.8 at first); see the README for what it is in the model's units.
"""
import argparse
import json
import math
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mmd_cli.formats import pmm  # noqa: E402

# offsets from pmm.loads(positions=...): the current setting, and each key's fields after its links
CURRENT = {"acceleration": 0, "noise": 4, "direction": 8, "noise_enabled": 20}
KEY = {"noise_enabled": 0, "noise": 1, "acceleration": 5, "direction": 9}


def _check(acceleration, direction, noise):
    if acceleration is None and direction is None and noise is None:
        raise ValueError("nothing to change: give an acceleration, a direction or the noise")
    if acceleration is not None and not (math.isfinite(acceleration) and acceleration >= 0.0):
        raise ValueError("the acceleration must be a finite number of 0 or more, not %r" % (acceleration,))
    if direction is not None:
        direction = tuple(float(v) for v in direction)
        if len(direction) != 3 or not all(math.isfinite(v) for v in direction) or not any(direction):
            raise ValueError("the direction must be three finite numbers, not all 0, not %r" % (direction,))
    if noise is not None and noise is not False:
        if isinstance(noise, bool) or not isinstance(noise, int) or noise < 0:
            raise ValueError("the noise must be a whole number of 0 or more (or False to turn it off), not %r" % (noise,))
    return direction


def with_gravity(data, acceleration=None, direction=None, noise=None):
    """the bytes of the project `data` with the gravity set in the current setting and in every key.  None keeps a field;
    `noise` an int turns the noise on with that amount, False turns it off (the amount stays)"""
    direction = _check(acceleration, direction, noise)
    pos = {}
    pmm.loads(data, positions=pos)
    out = bytearray(data)
    places = [(pos["gravity_current"], CURRENT)] + [(at, KEY) for at in pos["gravity_frames"]]
    for at, field in places:
        if acceleration is not None:
            struct.pack_into("<f", out, at + field["acceleration"], acceleration)
        if direction is not None:
            struct.pack_into("<3f", out, at + field["direction"], *direction)
        if noise is False:
            out[at + field["noise_enabled"]] = 0
        elif noise is not None:
            out[at + field["noise_enabled"]] = 1
            struct.pack_into("<i", out, at + field["noise"], noise)
    out = bytes(out)
    got = pmm.loads(out)["gravity"]
    for part in [got["current"], got["init"]] + got["keys"]:
        if acceleration is not None and part["acceleration"] != struct.unpack("<f", struct.pack("<f", acceleration))[0]:
            raise AssertionError("the acceleration did not read back: %r" % (part,))
        if direction is not None and part["direction"] != struct.unpack("<3f", struct.pack("<3f", *direction)):
            raise AssertionError("the direction did not read back: %r" % (part,))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--acceleration", type=float)
    ap.add_argument("--direction", type=float, nargs=3, metavar=("X", "Y", "Z"))
    noise = ap.add_mutually_exclusive_group()
    noise.add_argument("--noise", type=int)
    noise.add_argument("--no-noise", action="store_true")
    a = ap.parse_args(argv)
    try:
        if os.path.abspath(a.src).lower() == os.path.abspath(a.dst).lower():
            raise ValueError("the copy would overwrite the project")
        with open(a.src, "rb") as f:
            data = f.read()
        out = with_gravity(data, a.acceleration, a.direction, False if a.no_noise else a.noise)
        with open(a.dst, "wb") as f:
            f.write(out)
        before, after = pmm.loads(data)["gravity"], pmm.loads(out)["gravity"]
        print(json.dumps({"ok": True, "dst": a.dst, "keys": 1 + len(after["keys"]),
                          "before": {"current": before["current"], "init": before["init"]},
                          "after": {"current": after["current"], "init": after["init"]}}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, pmm.PmmFormatError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
