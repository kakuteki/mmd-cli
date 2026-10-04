"""mmd: operate MikuMikuDance from the command line without showing its window.

Every command prints one JSON object.  Exit codes: 0 ok, 1 error, 2 usage, 3 a dialog is waiting.
"""
import argparse
import json
import math
import os
import sys

from . import __version__


def parse_target(text):
    """model / accessory selector: None or "camera" -> camera mode, ASCII digits -> index, else a name
    (str.isdigit alone is also true for full-width digits, which are a legitimate model name)"""
    if text is None or text == "camera":
        return None
    if text.isascii() and text.isdigit():
        return int(text)
    return text


def emit(payload, out_path, stream):
    """stdout is always ASCII (non-ASCII is escaped) so it survives any console code page;
    --out writes readable UTF-8 to a file instead (written whole, then moved into place)"""
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        tmp = out_path + ".part"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, out_path)
        payload = {"ok": payload.get("ok", True), "out": out_path}
    if stream is not None:                       # pythonw.exe has no console
        stream.write(json.dumps(payload, ensure_ascii=True) + "\n")


def failure(exc):
    error = {"type": type(exc).__name__, "message": str(exc)}
    code = 2 if isinstance(exc, ValueError) else 1       # a value that cannot be used is a usage error, like argparse's
    answered = getattr(exc, "answered_dialogs", None)      # attached by run(): what was pressed before the failure
    dialogs = getattr(exc, "dialogs", None)
    if dialogs is not None:
        code = 3
        error["dialogs"] = [d.to_json() for d in dialogs]
        error["hint"] = "answer it with: mmd dialog click BUTTON   (or: mmd dialog close)"
        if answered is None:
            answered = [e for e in getattr(exc, "events", []) if e.get("action") != "left open"]
    if answered:
        error["answered_dialogs"] = list(answered)
    kept = getattr(exc, "kept_output", None)                 # what MMD wrote before the operation failed
    if kept:
        error["kept_output"] = kept
    return {"ok": False, "error": error}, code


# ---- argument parsing -----------------------------------------------------------------------

def finite(text):
    """a float that is a number: argparse's float also accepts nan and inf, which MMD has no use for"""
    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError("%r is not a finite number" % text)
    return value


def _vector(parser, flag, count, help_text, cast=finite):
    parser.add_argument(flag, nargs=count, type=cast, metavar=tuple("XYZW"[:count]) if count <= 4 else None,
                        help=help_text)


def curve_value(text):
    """one number of an interpolation curve: a whole number from 0 to 127"""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a whole number" % text) from None
    if not 0 <= value <= 127:
        raise argparse.ArgumentTypeError("%r is outside 0 to 127" % text)
    return value


def _interp(parser, what):
    parser.add_argument("--interp", nargs=4, type=curve_value, metavar=("X1", "Y1", "X2", "Y2"),
                        help="interpolation curve of %s, 0-127 each (default 20 20 107 107: linear)" % what)


def _range(parser, what):
    parser.add_argument("--from", dest="start", type=int, metavar="A", help="first frame of %s (with --to; default: all)" % what)
    parser.add_argument("--to", dest="end", type=int, metavar="B", help="last frame of %s, included" % what)


def build_parser():
    p = argparse.ArgumentParser(prog="mmd", description=__doc__.split("\n")[0])
    p.add_argument("--version", action="version", version="mmd-cli " + __version__)
    p.add_argument("--pid", type=int, help="the MMD process to talk to (default: the one started by 'mmd launch')")
    p.add_argument("--out", help="write the JSON result to this file as UTF-8 (stdout then only points to it)")
    p.add_argument("--timeout", type=float,
                   help="seconds to wait for MMD (default 120; render avi, when this is not given, allows 60 s plus 2 s per frame)")
    p.add_argument("--in-place", action="store_true",
                   help="allow saving into a project file that was not opened through mmd-cli")
    p.add_argument("--in-user-session", action="store_true",
                   help="run this command inside the logged-on user's desktop session (done by itself when "
                        "started from SSH, a service or a scheduled task without a desktop)")
    p.add_argument("--no-relay", action="store_true", help="never hand the command to the desktop session")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def group(name, help_text):
        g = sub.add_parser(name, help=help_text)
        return g.add_subparsers(dest="action", required=True, metavar="ACTION")

    sub.add_parser("ps", help="list running MMD instances")
    s = sub.add_parser("launch", help="start MMD minimized, without activating it")
    s.add_argument("--exe", help="path to MikuMikuDance.exe (default: MMD_EXE or the one used last time)")
    s.add_argument("--headless", action="store_true",
                   help="keep the window hidden (no taskbar button, nothing on screen); mmd window show undoes it")
    s = sub.add_parser("quit", help="close MMD")
    s.add_argument("--force", action="store_true", help="terminate the process if it does not close")
    sub.add_parser("state", help="what the controls of the MMD window show")
    s = sub.add_parser("dump", help="the whole scene (saves the working copy of the project and parses it)")
    s.add_argument("--keys", action="store_true", help="include every key frame (can be long)")
    sub.add_parser("new", help="start a new project (discards the current one)")
    s = sub.add_parser("open", help="open a copy of a .pmm project")
    s.add_argument("file")
    s = sub.add_parser("save", help="save the project to a .pmm file")
    s.add_argument("file", nargs="?")

    g = group("model", "models")
    s = g.add_parser("load", help="load a .pmx / .pmd model")
    s.add_argument("file")
    g.add_parser("list")
    s = g.add_parser("select", help="select a model by name or index, or 'camera'")
    s.add_argument("target")
    for name in ("delete", "show", "hide"):
        s = g.add_parser(name)
        s.add_argument("target", nargs="?")
    s = g.add_parser("info", help="bones (parents, flags, IK, append), morphs (panel, kind) and display frames of a model, "
                                  "read from its .pmx / .pmd file")
    s.add_argument("target", nargs="?", help="a loaded model by name or index (default: the selected one), or a model file")

    g = group("motion", "motion data (.vmd)")
    s = g.add_parser("load", help="load a motion at the current (or given) frame")
    s.add_argument("file")
    s.add_argument("--frame", type=int)
    s.add_argument("--model")
    s = g.add_parser("save", help="write the selected model's motion (or the camera motion in camera mode)")
    s.add_argument("file")
    s.add_argument("--model")
    s = g.add_parser("keys", help="list the keys of a .vmd file (no MMD needed): counts per kind, or one target's keys")
    s.add_argument("file")
    which = s.add_mutually_exclusive_group()
    which.add_argument("--camera", action="store_true", help="camera keys")
    which.add_argument("--bone", metavar="NAME", help="keys of one bone")
    which.add_argument("--morph", metavar="NAME", help="keys of one morph")
    which.add_argument("--light", action="store_true", help="light keys")
    _range(s, "the keys to list")
    s = g.add_parser("edit", help="write a copy of a .vmd with keys of a frame range shifted, deleted, copied, changed "
                                  "or given a curve (no MMD needed). The operations apply in the order shift, copy, values, interp")
    s.add_argument("src", help="the .vmd to read (left as it is unless dst is the same path)")
    s.add_argument("dst", help="the .vmd to write (an existing file is kept aside until the new one is written)")
    s.add_argument("--camera", action="store_true", help="the camera keys")
    s.add_argument("--light", action="store_true", help="the light keys")
    s.add_argument("--bone", action="append", metavar="NAME", help="the keys of this bone (repeatable)")
    s.add_argument("--all-bones", action="store_true", help="the keys of every bone in the file")
    s.add_argument("--morph", action="append", metavar="NAME", help="the keys of this morph (repeatable)")
    s.add_argument("--all-morphs", action="store_true", help="the keys of every morph in the file")
    _range(s, "the keys to edit")
    s.add_argument("--shift", type=int, metavar="N", help="move the keys by N frames (negative moves them earlier)")
    s.add_argument("--delete", action="store_true", help="remove the keys (not combined with other operations)")
    s.add_argument("--copy-to", type=int, metavar="F", help="add a copy of the keys, the first one at frame F")
    s.add_argument("--replace", action="store_true", help="let --shift / --copy-to overwrite keys already at the destination")
    s.add_argument("--distance-scale", type=finite, metavar="K", help="camera: multiply the distance by K (K > 0)")
    s.add_argument("--distance-add", type=finite, metavar="D", help="camera: add D to the distance the window shows")
    s.add_argument("--distance-clamp", nargs=2, type=finite, metavar=("MIN", "MAX"),
                   help="camera: keep the distance between MIN and MAX (applied after scale and add)")
    _vector(s, "--pos-add", 3, "camera / bone: add to the position")
    s.add_argument("--fov-add", type=int, metavar="F", help="camera: add F degrees to the view angle")
    s.add_argument("--fov-set", type=int, metavar="F", help="camera: set the view angle to F degrees")
    _vector(s, "--rot-add", 3, "bone: turn further by these degrees (as the angle boxes show them), about the bone's own axes")
    s.add_argument("--weight-scale", type=finite, metavar="K", help="morph: multiply the weight by K")
    s.add_argument("--weight-set", type=finite, metavar="W", help="morph: set the weight to W")
    _interp(s, "camera / bone keys, on every channel")

    g = group("pose", "pose data (.vpd)")
    s = g.add_parser("load")
    s.add_argument("file")
    s.add_argument("--register", action="store_true", help="also register key frames for the posed bones")
    s.add_argument("--model")
    s = g.add_parser("save", help="write the selected model's current pose")
    s.add_argument("file")
    s.add_argument("--model")

    g = group("wav", "sound")
    s = g.add_parser("load")
    s.add_argument("file")

    g = group("accessory", "accessories (.x)")
    s = g.add_parser("load")
    s.add_argument("file")
    g.add_parser("list")
    s = g.add_parser("get")
    s.add_argument("target")
    s = g.add_parser("set", help="change an accessory and register it at the current frame")
    s.add_argument("target")
    _vector(s, "--pos", 3, "position")
    _vector(s, "--rot", 3, "rotation in degrees")
    s.add_argument("--scale", type=float)
    s.add_argument("--alpha", type=float, help="1 = opaque (the Tr box)")
    s.add_argument("--show", dest="visible", action="store_const", const=True, default=None)
    s.add_argument("--hide", dest="visible", action="store_const", const=False)
    s = g.add_parser("delete")
    s.add_argument("target")

    g = group("frame", "the current frame")
    g.add_parser("get")
    s = g.add_parser("set")
    s.add_argument("number", type=int)
    for name in ("next", "prev", "next-key", "prev-key", "first", "last"):
        g.add_parser(name)

    s = sub.add_parser("play", help="start playback")
    s.add_argument("--from", dest="start", type=int)
    s.add_argument("--to", dest="end", type=int)
    s.add_argument("--wait", action="store_true", help="return when playback has finished")
    s.add_argument("--from-current", action="store_true", help="start at the current frame (the 'frame start' box)")
    s.add_argument("--stay", action="store_true",
                   help="stay on the frame where playback ended (the 'frame stop' box)")
    s.add_argument("--repeat", action="store_true")
    sub.add_parser("stop", help="stop playback")

    g = group("camera", "camera")
    g.add_parser("get")
    s = g.add_parser("set")
    _vector(s, "--pos", 3, "camera centre")
    _vector(s, "--rot", 3, "angles in degrees, as shown in the MMD window")
    s.add_argument("--distance", type=float)
    s.add_argument("--fov", type=int, help="view angle in degrees")
    s.add_argument("--perspective", choices=("on", "off"))
    s.add_argument("--register", action="store_true", help="register a key at the current frame")

    g = group("light", "light")
    g.add_parser("get")
    s = g.add_parser("set")
    _vector(s, "--rgb", 3, "0-255 each", cast=int)
    _vector(s, "--dir", 3, "direction, -1 to 1 each")
    s.add_argument("--register", action="store_true")

    g = group("bone", "bones of the selected model")
    s = g.add_parser("list")
    s.add_argument("--model")
    s = g.add_parser("get")
    s.add_argument("name")
    s.add_argument("--model")
    s = g.add_parser("set", help="register a key for one bone")
    s.add_argument("name")
    _vector(s, "--pos", 3, "translation")
    rotation = s.add_mutually_exclusive_group()
    rotation.add_argument("--rot", nargs=3, type=finite, metavar=("X", "Y", "Z"), help="degrees")
    rotation.add_argument("--quat", nargs=4, type=finite, metavar=("X", "Y", "Z", "W"))
    s.add_argument("--frame", type=int)
    s.add_argument("--model")

    g = group("morph", "morphs (facial expressions) of the selected model")
    s = g.add_parser("list")
    s.add_argument("--model")
    s = g.add_parser("get")
    s.add_argument("name")
    s.add_argument("--model")
    s = g.add_parser("set", help="register a key for one morph")
    s.add_argument("name")
    s.add_argument("value", type=finite)
    s.add_argument("--frame", type=int)
    s.add_argument("--model")

    g = group("render", "write pictures and video")
    s = g.add_parser("image", help="write the current frame (.png .bmp .jpg)")
    s.add_argument("file")
    s.add_argument("--size", nargs=2, type=int, metavar=("W", "H"))
    s = g.add_parser("avi", help="write a frame range as .avi")
    s.add_argument("file")
    s.add_argument("--from", dest="start", type=int, required=True)
    s.add_argument("--to", dest="end", type=int, required=True)
    s.add_argument("--fps", type=int, default=30)
    s.add_argument("--size", nargs=2, type=int, metavar=("W", "H"))
    s.add_argument("--codec", help="part of a codec name from the AVI dialog (default: MMD's current choice)")
    s = g.add_parser("size", help="show or set the output size")
    s.add_argument("size", nargs="*", type=int, metavar="N")
    g.add_parser("codecs", help="list the video codecs the AVI dialog offers")

    g = group("menu", "any menu item, by id")
    g.add_parser("list")
    s = g.add_parser("click")
    s.add_argument("id", type=int)

    g = group("control", "any control of the main window, by id")
    g.add_parser("list")
    s = g.add_parser("get")
    s.add_argument("id", type=int)
    s = g.add_parser("set")
    s.add_argument("id", type=int)
    s.add_argument("value")
    s.add_argument("--no-commit", action="store_true", help="for input boxes: do not send Enter")
    s = g.add_parser("click")
    s.add_argument("id", type=int)

    g = group("dialog", "dialogs MMD is waiting in")
    g.add_parser("list")
    s = g.add_parser("click")
    s.add_argument("button", help="start of the button label, or its control id")
    g.add_parser("close")
    g.add_parser("show", help="put the dialogs on screen for a person to answer")

    g = group("window", "the MMD window")
    g.add_parser("status")
    g.add_parser("minimize")
    g.add_parser("hide", help="take the window off the screen and the taskbar (it keeps working)")
    g.add_parser("show", help="bring a hidden window back, minimized")

    g = group("file", "inspect files without MMD")
    s = g.add_parser("info", help="show a .vmd / .vpd / .pmm / .pmx / .pmd file as JSON")
    s.add_argument("file")
    s.add_argument("--brief", action="store_true", help="for models: names and counts only, without the bone and morph lists")

    s = sub.add_parser("batch", help="run many commands from a file (one per line; '-' reads stdin) in one process")
    s.add_argument("file")
    s.add_argument("--keep-going", action="store_true", help="carry on after a failing line (default: stop there)")
    return p


# ---- commands -------------------------------------------------------------------------------

def _file_info(path, brief=False):
    from . import scene
    from .formats import pmm, vmd, vpd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".pmx", ".pmd"):
        from .formats import pmd, pmx
        return (pmd if ext == ".pmd" else pmx).load(path).to_json(brief=brief)
    if ext == ".pmm":
        return scene.summarize(pmm.load(path))
    if ext == ".vpd":
        pose = vpd.load(path)
        return {"model_file": pose.model_file,
                "bones": [{"bone": b.name, "pos": list(b.position), "quat": list(b.rotation)} for b in pose.bones]}
    if ext == ".vmd":
        m = vmd.load(path)
        frames = [k.frame for k in m.bones + m.morphs + m.cameras + m.lights]
        return {"model_name": m.model_name, "kind": "camera" if m.is_camera else "model",
                "counts": {"bones": len(m.bones), "morphs": len(m.morphs), "cameras": len(m.cameras),
                           "lights": len(m.lights), "shadows": len(m.shadows), "show_ik": len(m.show_iks)},
                "bone_names": sorted({k.name for k in m.bones}), "morph_names": sorted({k.name for k in m.morphs}),
                "last_frame": max(frames) if frames else 0}
    raise ValueError("unsupported file type: %s" % ext)


def _motion_targets(args):
    from .motion_edit import Target
    specs = []
    if args.camera:
        specs.append(Target("camera"))
    if args.light:
        specs.append(Target("light"))
    for kind in ("bone", "morph"):
        given = getattr(args, kind)
        for name in (given if isinstance(given, list) else [given] if given is not None else []):
            specs.append(Target(kind, name))
        if getattr(args, "all_%ss" % kind, False):
            specs.append(Target(kind, None))             # every name in the file
    return specs


def _motion_file_command(args):
    """`motion keys` / `motion edit`: the file is read (and written) here, without MMD"""
    from . import motion_edit
    span = motion_edit.check_range(args.start, args.end)
    specs = _motion_targets(args)
    if args.action == "keys":
        return motion_edit.keys_file(args.file, specs[0] if specs else None, span)
    ops = motion_edit.Operations(
        shift=args.shift, delete=args.delete, copy_to=args.copy_to, replace=args.replace,
        distance_scale=args.distance_scale, distance_add=args.distance_add,
        distance_clamp=tuple(args.distance_clamp) if args.distance_clamp else None,
        pos_add=tuple(args.pos_add) if args.pos_add else None, fov_add=args.fov_add, fov_set=args.fov_set,
        rot_add=tuple(args.rot_add) if args.rot_add else None, weight_scale=args.weight_scale, weight_set=args.weight_set,
        interp=tuple(args.interp) if args.interp else None)
    return motion_edit.edit_file(args.src, args.dst, specs, ops, span)


STANDALONE = ("file", "ps", "launch")       # commands that do not need an attached instance


def _model_file(args):
    """`model info FILE`: the file itself is read, like `file info`"""
    target = getattr(args, "target", None)
    return (args.command == "model" and getattr(args, "action", None) == "info" and isinstance(target, str)
            and os.path.splitext(target)[1].lower() in (".pmx", ".pmd") and os.path.isfile(target))


def _motion_file(args):
    """`motion keys` / `motion edit` work on the file alone"""
    return args.command == "motion" and getattr(args, "action", None) in ("keys", "edit")


def standalone(args):
    """commands that need neither a running MMD nor the relay into the desktop session"""
    return args.command in STANDALONE or _model_file(args) or _motion_file(args)


def dispatch_any(mmd, args):
    """run one parsed command.  mmd may be None for the standalone commands; a launch returns the
    new instance under "_instance" so a batch can keep using it."""
    if args.command == "file":
        return _file_info(args.file, brief=args.brief)
    if _model_file(args):
        return dict(_file_info(args.target), path=os.path.abspath(args.target))
    if _motion_file(args):
        return _motion_file_command(args)
    from . import app
    if args.command == "ps":
        return {"instances": app.instances(), "current": app.load_state().get("current")}
    if args.command == "launch":
        exe = args.exe or os.environ.get("MMD_EXE") or app.load_state().get("exe")
        if not exe:
            raise app.MmdError("give the program with --exe PATH (or set MMD_EXE)")
        from .guard import FocusShield
        with FocusShield(pid=None) as shield:
            mmd = app.launch(exe, timeout=getattr(args, "timeout", None) or 90.0, headless=args.headless)
            shield.pid = mmd.pid
            result = mmd.state()
        if shield.events:
            result["foreground_restored"] = list(shield.events)
        result["_instance"] = mmd
        return result
    return _dispatch(mmd, args)


def _attach(args):
    from . import app
    mmd = app.Mmd.attach(args.pid)
    if args.timeout:
        mmd.timeout = args.timeout
    mmd.in_place = args.in_place
    return mmd


def _run_batch(args):
    from . import batch
    from .guard import FocusShield
    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file, encoding="utf-8-sig") as f:
            text = f.read()
    entries = batch.parse_lines(text)
    with FocusShield(pid=None) as shield:
        def make():
            mmd = _attach(args)
            shield.pid = mmd.pid
            return mmd

        def dispatch(mmd, parsed):
            result = dispatch_any(mmd, parsed)
            if isinstance(result, dict) and result.get("_instance") is not None:
                shield.pid = result["_instance"].pid
                if args.timeout:
                    result["_instance"].timeout = args.timeout
                result["_instance"].in_place = args.in_place
            return result

        results, code = batch.run_batch(entries, make, dispatch, build_parser(), stop_on_error=not args.keep_going)
    result = batch.summary(results, code)
    if shield.events:
        result["foreground_restored"] = list(shield.events)
    return result


def run(args):
    if args.command == "batch":
        return _run_batch(args)
    if standalone(args):
        result = dispatch_any(None, args)
        result.pop("_instance", None)
        return result
    mmd = _attach(args)
    with mmd.shield() as shield:
        try:
            result = dict(_dispatch(mmd, args))
        except Exception as exc:
            exc.answered_dialogs = mmd.take_events()        # what was pressed on the way is part of the report
            raise
        answered = mmd.take_events()
    if answered:
        result["answered_dialogs"] = answered
    if shield.events:
        result["foreground_restored"] = list(shield.events)
    return result


def _dispatch(mmd, args):
    command, action = args.command, getattr(args, "action", None)

    if command == "quit":
        return mmd.quit(force=args.force)
    if command == "state":
        return mmd.state()
    if command == "dump":
        return mmd.dump(keys=args.keys)
    if command == "new":
        return mmd.new_project()
    if command == "open":
        return mmd.open_project(args.file)
    if command == "save":
        return mmd.save(args.file)
    if command == "play":
        return mmd.play(start=args.start, end=args.end, wait=args.wait, from_current=args.from_current,
                        stay=args.stay, repeat=args.repeat)
    if command == "stop":
        return mmd.stop()

    if command == "model":
        if action == "load":
            return mmd.load_model(args.file)
        if action == "list":
            state = mmd.state()
            return {"models": state["models"], "selected": state["selected_model"]}
        if action == "select":
            return mmd.select_model(parse_target(args.target))
        if action == "info":
            return mmd.model_info(parse_target(args.target))
        target = parse_target(args.target)
        if action == "delete":
            return mmd.delete_model(target)
        return mmd.set_model_visible(action == "show", target)

    if command == "motion":
        if action in ("keys", "edit"):
            return _motion_file_command(args)
        if action == "save":
            if args.model is not None:
                mmd.select_model(parse_target(args.model))
            return mmd.save_motion(args.file)
        return mmd.load_motion(args.file, frame=args.frame, model=parse_target(args.model))
    if command == "pose":
        if action == "save":
            if args.model is not None:
                mmd.select_model(parse_target(args.model))
            return mmd.save_pose(args.file)
        return mmd.load_pose(args.file, register=args.register, model=parse_target(args.model))
    if command == "wav":
        return mmd.load_wav(args.file)

    if command == "accessory":
        if action == "load":
            return mmd.load_accessory(args.file)
        if action == "list":
            return {"accessories": mmd.accessories()}
        target = parse_target(args.target)
        if action == "get":
            return mmd.accessory(target)
        if action == "set":
            return mmd.set_accessory(target, pos=args.pos, rot=args.rot, scale=args.scale, alpha=args.alpha,
                                     visible=args.visible)
        return mmd.delete_accessory(target)

    if command == "frame":
        if action == "set":
            return {"frame": mmd.set_frame(args.number)}
        if action in ("next", "prev"):
            return {"frame": mmd.step_frame(1 if action == "next" else -1)}
        if action in ("next-key", "prev-key"):
            return {"frame": mmd.jump_key(action == "next-key")}
        if action == "first":
            return {"frame": mmd.go_first()}
        if action == "last":
            return {"frame": mmd.go_last()}
        return {"frame": mmd.frame()}

    if command == "camera":
        if action == "get":
            return mmd.camera()
        perspective = None if args.perspective is None else args.perspective == "on"
        return mmd.set_camera(pos=args.pos, rot=args.rot, distance=args.distance, fov=args.fov,
                              perspective=perspective, register=args.register)
    if command == "light":
        if action == "get":
            return mmd.light()
        return mmd.set_light(rgb=args.rgb, direction=args.dir, register=args.register)

    if command == "bone":
        model = parse_target(args.model)
        if action == "list":
            return {"bones": mmd.bones(model)}
        if action == "get":
            return mmd.bone(args.name, model)
        return mmd.set_bone(args.name, pos=args.pos, rot=args.rot, quat=args.quat, frame=args.frame, model=model)
    if command == "morph":
        model = parse_target(args.model)
        if action == "list":
            return {"morphs": mmd.morphs(model)}
        if action == "get":
            return mmd.morph(args.name, model)
        return mmd.set_morph(args.name, args.value, frame=args.frame, model=model)

    if command == "render":
        if action == "image":
            return mmd.render_image(args.file, size=args.size, timeout=args.timeout)
        if action == "avi":
            return mmd.render_avi(args.file, args.start, args.end, fps=args.fps, size=args.size,
                                  codec=args.codec, timeout=args.timeout)
        if action == "codecs":
            return {"codecs": mmd.render_codecs()}
        if len(args.size) == 2:
            return {"size": mmd.set_output_size(*args.size)}
        if args.size:
            raise ValueError("give both width and height, or nothing to read the size")
        return {"size": mmd.output_size()}

    if command == "menu":
        if action == "list":
            return {"items": mmd.menu_items()}
        return mmd.menu_click(args.id)
    if command == "control":
        if action == "list":
            return {"controls": mmd.controls()}
        if action == "get":
            return mmd.control_get(args.id)
        if action == "click":
            return mmd.control_click(args.id)
        return mmd.control_set(args.id, args.value, commit=not args.no_commit)
    if command == "dialog":
        if action == "list":
            return {"dialogs": mmd.dialogs()}
        if action == "click":
            return mmd.dialog_click(args.button)
        if action == "close":
            return mmd.dialog_close()
        return {"dialogs": mmd.dialog_show()}
    if command == "window":
        if action == "minimize":
            return mmd.minimize()
        if action == "hide":
            return mmd.hide()
        if action == "show":
            return mmd.show()
        state = mmd.state()
        return {k: state[k] for k in ("pid", "hwnd", "minimized", "visible", "project_path", "dialogs")}
    raise ValueError("unhandled command: %s" % command)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "--job":            # we are the copy running inside the desktop session
        from . import relay
        return relay.run_job(argv[1], main)
    args = build_parser().parse_args(argv)
    try:
        from . import relay
        if relay.should_relay(argv=argv, command=None if standalone(args) else args.command):
            parked = None
            try:
                if args.command == "batch" and args.file == "-":
                    # stdin does not travel through the relay: park it in a file first
                    folder = relay.relay_dir()
                    os.makedirs(folder, exist_ok=True)
                    parked = os.path.join(folder, "stdin-%d.txt" % os.getpid())
                    with open(parked, "w", encoding="utf-8") as f:
                        f.write(sys.stdin.read())
                    argv = [parked if a == "-" else a for a in argv]
                payload, code = relay.run_in_user_session(argv)
            finally:
                if parked:
                    try:
                        os.remove(parked)
                    except OSError:
                        pass
            emit(payload, args.out, sys.stdout)
            return code
        result = run(args)
        payload = {"ok": result.get("ok", True)}
        payload.update(result)
        code = 0 if payload["ok"] else int(payload.get("exit_code", 1))
    except Exception as exc:  # every failure is reported as JSON
        if os.environ.get("MMD_CLI_DEBUG"):
            raise
        payload, code = failure(exc)
    emit(payload, args.out, sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
