"""Read PMM (Polygon Movie Maker project) files written by MMD 9.x ("...maker 0002").

The result is a plain dict that mirrors the file.  Values keep the stored conventions:
rotations of camera and accessories are radians (the camera X angle is negated relative to
the MMD window), the camera distance is negative, light colours are value / 256.
Use mmd_cli.scene.summarize() for the numbers shown in the MMD window.
"""
import struct

ENCODING = "cp932"
MAGIC_V2 = b"Polygon Movie maker 0002"
MAGIC_PREFIX = b"Polygon Movie maker "
_MAX_COUNT = 5000000


class PmmFormatError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        end = self.pos + size
        if size < 0 or end > len(self.data):
            raise PmmFormatError("PMM ends unexpectedly at offset %d (wanted %d more bytes)" % (self.pos, size))
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))

    def u8(self):
        return self.take(1)[0]

    def flag(self):
        return self.take(1)[0] != 0

    def i32(self):
        return self.unpack("<i")[0]

    def f32(self):
        return self.unpack("<f")[0]

    def floats(self, n):
        return self.unpack("<%df" % n)

    def count(self):
        n = self.i32()
        if n < 0 or n > _MAX_COUNT:
            raise PmmFormatError("implausible element count %d at offset %d" % (n, self.pos - 4))
        return n

    def pstring(self):
        return self.take(self.u8()).decode(ENCODING, "replace")

    def fixed_string(self, size):
        return self.take(size).split(b"\x00", 1)[0].decode(ENCODING, "replace")


def _links(r, with_index):
    d = {}
    if with_index:
        d["index"] = r.i32()
    d["frame"], d["pre"], d["next"] = r.unpack("<3i")
    return d


def _bone_frame(r, with_index):
    d = _links(r, with_index)
    d["interpolation"] = list(r.take(16))
    d["position"] = r.floats(3)
    d["rotation"] = r.floats(4)
    d["selected"] = r.flag()
    d["physics_disabled"] = r.flag()
    return d


def _morph_frame(r, with_index):
    d = _links(r, with_index)
    d["weight"] = r.f32()
    d["selected"] = r.flag()
    return d


def _config_frame(r, with_index, ik_count, parent_count):
    d = _links(r, with_index)
    d["visible"] = r.flag()
    d["ik"] = [r.flag() for _ in range(ik_count)]
    d["outside_parents"] = [r.unpack("<2i") for _ in range(parent_count)]
    d["selected"] = r.flag()
    return d


def _camera_frame(r, with_index):
    d = _links(r, with_index)
    d["distance"] = r.f32()
    d["position"] = r.floats(3)
    d["rotation"] = r.floats(3)
    d["follow_model"], d["follow_bone"] = r.unpack("<2i")
    d["interpolation"] = list(r.take(24))
    d["orthographic"] = r.flag()
    d["fov"] = r.i32()
    d["selected"] = r.flag()
    return d


def _light_frame(r, with_index):
    d = _links(r, with_index)
    d["rgb"] = r.floats(3)
    d["direction"] = r.floats(3)
    d["selected"] = r.flag()
    return d


def _visibility(byte):
    return {"visible": bool(byte & 1), "transparency_percent": byte >> 1}


def _accessory_frame(r, with_index):
    d = _links(r, with_index)
    d.update(_visibility(r.u8()))
    d["parent_model"], d["parent_bone"] = r.unpack("<2i")
    d["position"] = r.floats(3)
    d["rotation"] = r.floats(3)
    d["scale"] = r.f32()
    d["shadow"] = r.flag()
    d["selected"] = r.flag()
    return d


def _accessory_current(r):
    # unlike the key frames, the current state stores rotation and scale before the position
    d = _visibility(r.u8())
    d["parent_model"], d["parent_bone"] = r.unpack("<2i")
    d["rotation"] = r.floats(3)
    d["scale"] = r.f32()
    d["position"] = r.floats(3)
    d["shadow"] = r.flag()
    return d


def _gravity_frame(r, with_index):
    d = _links(r, with_index)
    d["noise_enabled"] = r.flag()
    d["noise"] = r.i32()
    d["acceleration"] = r.f32()
    d["direction"] = r.floats(3)
    d["selected"] = r.flag()
    return d


def _shadow_frame(r, with_index):
    d = _links(r, with_index)
    d["mode"] = r.u8()
    d["distance"] = r.f32()
    d["selected"] = r.flag()
    return d


def _assign_owners(init_frames, keys, field_name):
    """A key frame only says where it is stored; its bone/morph is found by walking the
    'pre' links back to an initial frame (initial frame i belongs to element i)."""
    by_index = {k["index"]: k for k in keys}
    count = len(init_frames)
    for i, frame in enumerate(init_frames):
        frame[field_name] = i
    for key in keys:
        seen = set()
        cur = key
        owner = None
        while True:
            pre = cur["pre"]
            if 0 <= pre < count:
                owner = pre
                break
            if pre in seen or pre not in by_index:
                break
            seen.add(pre)
            cur = by_index[pre]
        key[field_name] = owner


def _model(r):
    m = {"number": r.u8(), "name": r.pstring(), "name_en": r.pstring(), "path": r.fixed_string(256)}
    m["keyframe_editor_rows"] = r.u8()
    m["bones"] = [r.pstring() for _ in range(r.count())]
    m["morphs"] = [r.pstring() for _ in range(r.count())]
    m["ik_bones"] = [r.i32() for _ in range(r.count())]
    m["outside_parent_bones"] = [r.i32() for _ in range(r.count())]
    bone_count, morph_count = len(m["bones"]), len(m["morphs"])
    ik_count, parent_count = len(m["ik_bones"]), len(m["outside_parent_bones"])
    m["draw_order"] = r.u8()
    m["visible"] = r.flag()
    m["selected_bone"] = r.i32()
    m["morph_panel"] = list(r.unpack("<4i"))
    m["frame_open"] = [r.flag() for _ in range(r.u8())]
    m["vscroll"] = r.i32()
    m["last_frame"] = r.i32()
    m["bone_init"] = [_bone_frame(r, False) for _ in range(bone_count)]
    m["bone_keys"] = [_bone_frame(r, True) for _ in range(r.count())]
    m["morph_init"] = [_morph_frame(r, False) for _ in range(morph_count)]
    m["morph_keys"] = [_morph_frame(r, True) for _ in range(r.count())]
    m["config_init"] = _config_frame(r, False, ik_count, parent_count)
    m["config_keys"] = [_config_frame(r, True, ik_count, parent_count) for _ in range(r.count())]
    m["bone_current"] = [{"position": r.floats(3), "rotation": r.floats(4), "uncommitted": r.flag(),
                          "physics_disabled": r.flag(), "row_selected": r.flag()} for _ in range(bone_count)]
    m["morph_current"] = list(r.floats(morph_count))
    m["ik_current"] = [r.flag() for _ in range(ik_count)]
    m["outside_parent_current"] = [dict(zip(("begin", "end", "model", "bone"), r.unpack("<4i")))
                                   for _ in range(parent_count)]
    m["add_blend"] = r.flag()
    m["edge_width"] = r.f32()
    m["self_shadow"] = r.flag()
    m["calc_order"] = r.u8()
    _assign_owners(m["bone_init"], m["bone_keys"], "bone")
    _assign_owners(m["morph_init"], m["morph_keys"], "morph")
    return m


def _accessory(r):
    a = {"number": r.u8(), "name": r.fixed_string(100), "path": r.fixed_string(256), "draw_order": r.u8()}
    a["init"] = _accessory_frame(r, False)
    a["keys"] = [_accessory_frame(r, True) for _ in range(r.count())]
    a["current"] = _accessory_current(r)
    a["add_blend"] = r.flag()
    return a


def _background(r, visible_is_int):
    d = {"offset_x": r.i32(), "offset_y": r.i32(), "scale": r.f32(), "path": r.fixed_string(256)}
    d["visible"] = (r.i32() != 0) if visible_is_int else r.flag()
    return d


def loads(data):
    if data[:len(MAGIC_V2)] != MAGIC_V2:
        if data[:len(MAGIC_PREFIX)] == MAGIC_PREFIX:
            version = data[len(MAGIC_PREFIX):len(MAGIC_PREFIX) + 4].decode("ascii", "replace")
            raise PmmFormatError("PMM version %s is not supported (only 0002, written by MMD 9.x); "
                                 "open and save it once in MMD to convert it" % version)
        raise PmmFormatError("not a PMM file (bad magic)")
    r = _Reader(data)
    p = {"version": 2}
    r.take(30)
    p["view_width"], p["view_height"], p["frame_width"] = r.unpack("<3i")
    p["edit_view_angle"] = r.f32()
    p["editing_camera"] = r.flag()
    p["panels"] = {name: r.flag() for name in ("camera", "light", "accessory", "bone", "morph", "self_shadow")}
    p["selected_model_index"] = r.u8()
    p["models"] = [_model(r) for _ in range(r.u8())]

    camera = {"init": _camera_frame(r, False)}
    camera["keys"] = [_camera_frame(r, True) for _ in range(r.count())]
    camera["current"] = {"position": r.floats(3), "target": r.floats(3), "rotation": r.floats(3),
                         "orthographic": r.flag()}
    p["camera"] = camera

    light = {"init": _light_frame(r, False)}
    light["keys"] = [_light_frame(r, True) for _ in range(r.count())]
    light["current"] = {"rgb": r.floats(3), "direction": r.floats(3)}
    p["light"] = light

    p["selected_accessory_index"] = r.u8()
    p["accessory_vscroll"] = r.i32()
    accessory_count = r.u8()
    p["accessory_names"] = [r.fixed_string(100) for _ in range(accessory_count)]
    p["accessories"] = [_accessory(r) for _ in range(accessory_count)]

    p["frame"], p["hscroll"], p["hscroll_scale"], p["bone_operation"] = r.unpack("<4i")
    p["looking_at"] = r.u8()
    p["repeat"] = r.flag()
    p["play_from_current_frame"] = r.flag()     # the "frame start" check box
    p["play_stay_at_stop_frame"] = r.flag()     # the "frame stop" check box
    p["play_start_frame"], p["play_end_frame"] = r.unpack("<2i")
    p["wave"] = {"enabled": r.flag(), "path": r.fixed_string(256)}
    p["background_avi"] = _background(r, True)
    p["background_image"] = _background(r, False)
    p["show_information"] = r.flag()
    p["show_axis"] = r.flag()
    p["show_ground_shadow"] = r.flag()
    p["fps_limit"] = r.f32()
    p["screen_capture_mode"] = r.i32()
    p["accessory_count_after_models"] = r.i32()
    p["ground_shadow_brightness"] = r.f32()
    p["transparent_ground_shadow"] = r.flag()
    p["physics_mode"] = r.u8()

    gravity = {"current": {"acceleration": r.f32(), "noise": r.i32(), "direction": r.floats(3),
                           "noise_enabled": r.flag()}}
    gravity["init"] = _gravity_frame(r, False)
    gravity["keys"] = [_gravity_frame(r, True) for _ in range(r.count())]
    p["gravity"] = gravity

    shadow = {"visible": r.flag(), "current_distance": r.f32()}
    shadow["init"] = _shadow_frame(r, False)
    shadow["keys"] = [_shadow_frame(r, True) for _ in range(r.count())]
    p["self_shadow"] = shadow

    p["edge_color"] = r.unpack("<3i")
    p["black_background"] = r.flag()
    p["camera_follow_model"], p["camera_follow_bone"] = r.unpack("<2i")
    p["unknown_matrix"] = r.floats(16)
    p["view_follow"] = r.flag()
    p["unknown_flag"] = r.u8()
    p["physics_ground"] = r.flag()
    p["frame_textbox"] = r.i32()
    p["selector_following"] = r.flag()
    p["selectors"] = [r.unpack("<Bi") for _ in range(len(p["models"]))]
    if r.pos != len(data):
        raise PmmFormatError("%d bytes are left after the last known field: the layout was misread"
                             % (len(data) - r.pos))
    return p


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())
