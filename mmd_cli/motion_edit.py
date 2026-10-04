"""List and edit the keys of a .vmd file without MMD: a frame range of camera, bone, morph or light
keys can be listed, shifted, deleted, copied, given new values or a new interpolation curve.

Numbers are shown and taken the way the MMD window shows them (positive camera distance, degrees,
the bone angles of the angle boxes); the file keeps its own representation (formats/vmd.py).
One call applies its operations in ORDER; --delete stands alone.
"""
import dataclasses
import difflib
import math
import os
from typing import Optional, Tuple

from . import mathutil
from .formats import vmd

KINDS = ("camera", "bone", "morph", "light")
ORDER = ("shift", "copy", "values", "interp")           # how one call applies its operations
_SECTIONS = (("bones", "bones"), ("morphs", "morphs"), ("cameras", "cameras"), ("lights", "lights"),
             ("shadows", "shadows"), ("show_ik", "show_iks"))


@dataclasses.dataclass(frozen=True)
class Target:
    """whose keys: the camera, the light, one bone or one morph by name (name None on a bone / morph
    target means every name in the file; resolve_targets expands it)"""
    kind: str
    name: Optional[str] = None

    def label(self):
        return self.kind if self.name is None else "%s %r" % (self.kind, self.name)

    def to_json(self):
        d = {"kind": self.kind}
        if self.name is not None:
            d["name"] = self.name
        return d


@dataclasses.dataclass
class Operations:
    shift: Optional[int] = None
    delete: bool = False
    copy_to: Optional[int] = None
    replace: bool = False
    distance_scale: Optional[float] = None
    distance_add: Optional[float] = None
    distance_clamp: Optional[Tuple[float, float]] = None
    pos_add: Optional[Tuple[float, float, float]] = None
    fov_add: Optional[int] = None
    fov_set: Optional[int] = None
    rot_add: Optional[Tuple[float, float, float]] = None
    weight_scale: Optional[float] = None
    weight_set: Optional[float] = None
    interp: Optional[Tuple[int, int, int, int]] = None


# which kinds of keys each value operation applies to (the option names are the command's)
_APPLIES_TO = {
    "distance_scale": ("camera",), "distance_add": ("camera",), "distance_clamp": ("camera",),
    "fov_add": ("camera",), "fov_set": ("camera",), "pos_add": ("camera", "bone"), "rot_add": ("bone",),
    "weight_scale": ("morph",), "weight_set": ("morph",), "interp": ("camera", "bone"),
}
_VALUE_OPS = ("distance_scale", "distance_add", "distance_clamp", "pos_add", "fov_add", "fov_set", "rot_add",
              "weight_scale", "weight_set")


def _option(field):
    return "--" + field.replace("_", "-")


def _r(value):
    return round(float(value), 4) + 0.0


def _vec(values):
    return [_r(v) for v in values]


def check_range(start, end):
    """--from A --to B: both or neither, 0 <= A <= B; returns (A, B) or None"""
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("give both --from and --to (or neither for the whole motion)")
    if start < 0 or end < 0:
        raise ValueError("frames start at 0: --from %d --to %d" % (start, end))
    if start > end:
        raise ValueError("--from %d is after --to %d" % (start, end))
    return (int(start), int(end))


def _span(span):
    return None if span is None else check_range(span[0], span[1])


def check_operations(ops, targets):
    """what is asked for must make sense before anything is read or changed"""
    given = [f for f in ("shift", "copy_to", "interp") + _VALUE_OPS if getattr(ops, f) is not None]
    if ops.delete:
        if given:
            raise ValueError("--delete cannot be combined with other operations (%s)" % ", ".join(_option(f) for f in given))
        if ops.replace:
            raise ValueError("--replace goes with --shift or --copy-to, not with --delete")
        return
    if not given:
        raise ValueError("give at least one operation (--shift, --delete, --copy-to, a value change or --interp)")
    if ops.replace and ops.shift is None and ops.copy_to is None:
        raise ValueError("--replace goes with --shift or --copy-to")
    if ops.copy_to is not None and ops.copy_to < 0:
        raise ValueError("--copy-to needs a frame of 0 or more, not %d" % ops.copy_to)
    if ops.distance_scale is not None and not ops.distance_scale > 0:
        raise ValueError("--distance-scale needs a factor above 0 (the sign of the distance is kept), not %r" % ops.distance_scale)
    if ops.distance_clamp is not None:
        bounds = tuple(ops.distance_clamp)
        if len(bounds) != 2 or not 0 <= bounds[0] <= bounds[1]:
            raise ValueError("--distance-clamp needs MIN MAX with 0 <= MIN <= MAX, not %r" % (ops.distance_clamp,))
    if ops.fov_set is not None and ops.fov_set < 1:
        raise ValueError("--fov-set needs an angle of 1 or more, not %d" % ops.fov_set)
    if ops.interp is not None:
        vmd.check_curve(ops.interp)
    for field, kinds in _APPLIES_TO.items():
        if getattr(ops, field) is None:
            continue
        for t in targets:
            if t.kind not in kinds:
                raise ValueError("%s applies to %s keys, not to the %s" % (_option(field), " / ".join(kinds), t.label()))


# ---- picking keys ---------------------------------------------------------------------------

def _section(motion, target):
    return {"camera": motion.cameras, "light": motion.lights, "bone": motion.bones, "morph": motion.morphs}[target.kind]


def _owns(target, key):
    return target.name is None or key.name == target.name


def _inside(key, span):
    return span is None or span[0] <= key.frame <= span[1]


def keys_of(motion, target):
    return [k for k in _section(motion, target) if _owns(target, k)]


def select(motion, target, span=None):
    """the target's keys inside the frame range (both ends included), in file order"""
    return [k for k in keys_of(motion, target) if _inside(k, span)]


def names(motion, kind):
    """bone or morph names that have keys, in order of first appearance"""
    return list(dict.fromkeys(k.name for k in _section(motion, Target(kind))))


def _no_such_name(motion, kind, name):
    have = names(motion, kind)
    if not have:
        return ValueError("no %s named %r: the file has no %s keys" % (kind, name, kind))
    close = difflib.get_close_matches(name, have, n=5, cutoff=0.5)
    if close:
        hint = "did you mean %s?" % ", ".join(repr(c) for c in close)
    else:
        shown = ", ".join(repr(n) for n in have[:10]) + (" ..." if len(have) > 10 else "")
        hint = "the file has %d %s names: %s" % (len(have), kind, shown)
    return ValueError("no %s named %r in the file; %s" % (kind, name, hint))


def resolve_targets(motion, specs):
    """check the names against the file and expand 'every bone' / 'every morph' into one target per name.
    A target named twice (or once and again through --all-bones) is one target: an operation applies once."""
    out, seen = [], set()
    for spec in specs:
        if spec.kind not in KINDS:
            raise ValueError("unknown kind of key: %r" % spec.kind)
        if spec.kind in ("camera", "light"):
            found = [Target(spec.kind)]
        elif spec.name is None:
            have = names(motion, spec.kind)
            if not have:
                raise ValueError("the file has no %s keys" % spec.kind)
            found = [Target(spec.kind, n) for n in have]
        elif spec.name in names(motion, spec.kind):
            found = [spec]
        else:
            raise _no_such_name(motion, spec.kind, spec.name)
        for target in found:
            if (target.kind, target.name) not in seen:
                seen.add((target.kind, target.name))
                out.append(target)
    return out


# ---- showing keys ---------------------------------------------------------------------------

def camera_to_ui(key):
    """a camera key as the MMD window shows it: positive distance, degrees (X with the other sign)"""
    x, y, z = key.rotation
    return {"frame": key.frame, "distance": _r(-key.distance), "pos": _vec(key.position),
            "rot": [_r(math.degrees(-x)), _r(math.degrees(y)), _r(math.degrees(z))],
            "fov": key.fov, "perspective": key.perspective}


def ui_camera_rotation(x_deg, y_deg, z_deg):
    """the radians a camera key stores for the angles the window shows"""
    return (-math.radians(x_deg), math.radians(y_deg), math.radians(z_deg))


def camera_key_from_ui(values, curve=None, frame=0):
    """a CameraKey from the numbers the window shows ({pos, rot, distance, fov, perspective}),
    optionally with an interpolation curve on every channel"""
    x, y, z = values["rot"]
    interpolation = vmd.camera_interpolation(curve) if curve is not None else vmd.DEFAULT_CAMERA_INTERPOLATION
    return vmd.CameraKey(frame=frame, distance=-float(values["distance"]),
                         position=tuple(float(v) for v in values["pos"]), rotation=ui_camera_rotation(x, y, z),
                         fov=int(values["fov"]), perspective=bool(values["perspective"]), interpolation=interpolation)


def key_json(target, key):
    if target.kind == "camera":
        return camera_to_ui(key)
    if target.kind == "bone":
        return {"frame": key.frame, "pos": _vec(key.position), "rot": _vec(mathutil.quat_to_ui(key.rotation))}
    if target.kind == "morph":
        return {"frame": key.frame, "weight": _r(key.weight)}
    return {"frame": key.frame, "rgb": [int(round(v * 256.0)) for v in key.rgb], "dir": _vec(key.direction)}


def counts(motion, span=None):
    return {label: sum(1 for k in getattr(motion, attr) if _inside(k, span)) for label, attr in _SECTIONS}


def summary(motion, span=None):
    """how many keys of each kind, and their first and last frame"""
    out = {"model_name": motion.model_name, "kind": "camera" if motion.is_camera else "model",
           "counts": counts(motion, span), "ranges": {}}
    for label, attr in _SECTIONS:
        frames = [k.frame for k in getattr(motion, attr) if _inside(k, span)]
        out["ranges"][label] = [min(frames), max(frames)] if frames else None
    return out


def list_keys(motion, target, span=None):
    keys = sorted(select(motion, target, span), key=lambda k: k.frame)
    return {"target": target.to_json(), "count": len(keys), "keys": [key_json(target, k) for k in keys]}


def keys_file(path, spec=None, span=None):
    """`mmd motion keys`: the summary of the file, or the keys of one target inside the range"""
    full = os.path.abspath(path)
    span = _span(span)
    motion = vmd.load(full)
    if spec is None:
        out = summary(motion, span)
    else:
        target = resolve_targets(motion, [spec])[0]
        out = dict(model_name=motion.model_name, kind="camera" if motion.is_camera else "model",
                   **list_keys(motion, target, span))
    return dict(path=full, range=list(span) if span else None, **out)


# ---- changing keys --------------------------------------------------------------------------

def _remove(section, keys):
    ids = set(map(id, keys))
    section[:] = [k for k in section if id(k) not in ids]


def _frames_text(keys):
    frames = sorted({k.frame for k in keys})
    return ", ".join(str(f) for f in frames[:8]) + (" ..." if len(frames) > 8 else "")


def _make_room(section, target, frames, exclude, replace, what):
    """keys of the target already at `frames` (other than `exclude`) are an error, or are removed
    with --replace; returns the removed keys"""
    excluded = set(map(id, exclude))
    blocking = [k for k in section if _owns(target, k) and k.frame in frames and id(k) not in excluded]
    if not blocking:
        return []
    if not replace:
        raise ValueError("%s: %s would land on existing keys at frame %s; add --replace to overwrite them"
                         % (target.label(), what, _frames_text(blocking)))
    _remove(section, blocking)
    return blocking


def _clamped_distance(stored, bounds):
    """|distance| held inside bounds; the sign of the file value stays (0 counts as the usual negative)"""
    low, high = bounds
    size = min(max(abs(stored), float(low)), float(high))
    return size if stored > 0 else -size


def _change_values(target, keys, ops):
    """the value operations, in a fixed order: scale / set first, then add, then clamp"""
    if not any(getattr(ops, f) is not None for f in _VALUE_OPS):
        return 0
    if ops.fov_add is not None:
        low = [k for k in keys if (ops.fov_set if ops.fov_set is not None else k.fov) + ops.fov_add < 1]
        if low:
            raise ValueError("%s: --fov-add %d would make the view angle smaller than 1 at frame %s"
                             % (target.label(), ops.fov_add, _frames_text(low)))
    for k in keys:
        if target.kind == "camera":
            if ops.distance_scale is not None:
                k.distance = k.distance * ops.distance_scale          # the file holds -distance: the sign stays
            if ops.distance_add is not None:
                k.distance = k.distance - ops.distance_add
            if ops.distance_clamp is not None:
                k.distance = _clamped_distance(k.distance, ops.distance_clamp)
            if ops.fov_set is not None:
                k.fov = int(ops.fov_set)
            if ops.fov_add is not None:
                k.fov = int(k.fov + ops.fov_add)
        if ops.pos_add is not None:
            k.position = tuple(p + float(d) for p, d in zip(k.position, ops.pos_add))
        if ops.rot_add is not None:
            # the added rotation turns about the bone's own axes: key rotation first, then the addition
            k.rotation = mathutil.quat_multiply(k.rotation, mathutil.ui_to_quat(*ops.rot_add))
        if ops.weight_set is not None:
            k.weight = float(ops.weight_set)
        if ops.weight_scale is not None:
            k.weight = k.weight * ops.weight_scale
    return len(keys)


def _apply_one(motion, target, ops, span):
    section = _section(motion, target)
    selected = select(motion, target, span)
    report = dict(target.to_json(), selected=len(selected))
    if ops.delete:
        _remove(section, selected)
        report["deleted"] = report["touched"] = len(selected)
        return report
    touched = list(selected)
    replaced = []
    if ops.shift is not None:
        moved = {id(k): k.frame + ops.shift for k in selected}
        if moved and min(moved.values()) < 0:
            raise ValueError("%s: --shift %d would put a key at frame %d (frames start at 0)"
                             % (target.label(), ops.shift, min(moved.values())))
        replaced += _make_room(section, target, set(moved.values()), selected, ops.replace, "--shift %d" % ops.shift)
        for k in selected:
            k.frame = moved[id(k)]
        report["shifted"] = len(selected)
    if ops.copy_to is not None:
        copies = []
        if selected:
            offset = ops.copy_to - min(k.frame for k in selected)
            copies = [dataclasses.replace(k, frame=k.frame + offset) for k in selected]
            gone = _make_room(section, target, {c.frame for c in copies}, [], ops.replace, "--copy-to %d" % ops.copy_to)
            replaced += gone
            gone_ids = set(map(id, gone))
            touched = [k for k in touched if id(k) not in gone_ids]
            section.extend(copies)
        touched += copies
        report["copied"] = len(copies)
    if replaced:
        report["replaced"] = len(replaced)
    changed = _change_values(target, touched, ops)
    if changed:
        report["changed"] = changed
    if ops.interp is not None:
        for k in touched:
            if target.kind == "bone":
                k.interpolation = vmd.bone_interpolation(ops.interp, keep=k.interpolation)
            else:
                k.interpolation = vmd.camera_interpolation(ops.interp)
        report["interp"] = len(touched)
    report["touched"] = len(touched) + len(replaced)
    return report


def apply(motion, targets, ops, span=None):
    """change `motion` in place: every target's keys inside the range get the operations in ORDER
    (--delete alone).  Returns one report per target.  Nothing is changed when a check fails before
    the first change; a failure in a later target leaves earlier targets changed, so callers write
    the result only after this returns."""
    check_operations(ops, targets)
    return [_apply_one(motion, t, ops, span) for t in targets]


def _write(path, data):
    # an existing file (the input itself when IN and OUT are the same path) is kept aside while
    # writing and comes back if the write fails, like every other output of mmd-cli
    from .app import keeping_the_old_file
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with keeping_the_old_file(path):
        part = path + ".part"
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)


def edit_file(src, dst, specs, ops, span=None):
    """`mmd motion edit`: read src, apply, write dst, read dst back for the counts in the result"""
    src_full, dst_full = os.path.abspath(src), os.path.abspath(dst)
    span = _span(span)
    if not specs:
        raise ValueError("give whose keys to edit: --camera, --bone NAME, --all-bones, --morph NAME, --all-morphs or --light")
    check_operations(ops, specs)
    motion = vmd.load(src_full)
    targets = resolve_targets(motion, specs)
    reports = apply(motion, targets, ops, span)
    data = vmd.dumps(motion)
    _write(dst_full, data)
    back = vmd.load(dst_full)
    return {"in": src_full, "out": dst_full, "range": list(span) if span else None,
            "order": ["delete"] if ops.delete else list(ORDER), "targets": reports, "counts": counts(back)}
