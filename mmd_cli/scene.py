"""Turn a parsed PMM into the JSON an operator wants to read: names instead of indices and the
same numbers the MMD window shows (degrees, positive camera distance, 0-255 light colours)."""
import math

from . import mathutil

_EPSILON = 1e-6


def _r(value):
    return round(float(value), 4) + 0.0


def _vec(values):
    return [_r(v) for v in values]


def _degrees(radians):
    return [_r(math.degrees(v)) for v in radians]


def _bone_rot(quat):
    return _vec(mathutil.quat_to_euler(quat))


def _is_rest(position, rotation):
    return (all(abs(v) < _EPSILON for v in position)
            and all(abs(v) < _EPSILON for v in rotation[:3]) and abs(abs(rotation[3]) - 1.0) < _EPSILON)


def _bone_key(model, frame):
    d = {"bone": model["bones"][frame["bone"]] if frame["bone"] is not None else None,
         "frame": frame["frame"], "pos": _vec(frame["position"]), "rot": _bone_rot(frame["rotation"])}
    if frame["physics_disabled"]:
        d["physics_off"] = True
    return d


def _model(index, model, keys):
    bone_keys = [f for f in model["bone_init"] if not _is_rest(f["position"], f["rotation"])] + model["bone_keys"]
    morph_keys = [f for f in model["morph_init"] if abs(f["weight"]) > _EPSILON] + model["morph_keys"]
    out = {
        "index": index,
        "name": model["name"],
        "name_en": model["name_en"],
        "path": model["path"],
        "visible": model["visible"],
        "bone_count": len(model["bones"]),
        "morph_count": len(model["morphs"]),
        "last_frame": model["last_frame"],
        "draw_order": model["draw_order"],
        "calc_order": model["calc_order"],
        "ik": {model["bones"][b]: on for b, on in zip(model["ik_bones"], model["ik_current"])},
        "key_counts": {"bones": len(bone_keys), "morphs": len(morph_keys)},
    }
    if keys:
        bone_keys.sort(key=lambda f: (f["bone"] if f["bone"] is not None else -1, f["frame"]))
        morph_keys.sort(key=lambda f: (f["morph"] if f["morph"] is not None else -1, f["frame"]))
        out["keys"] = {
            "bones": [_bone_key(model, f) for f in bone_keys],
            "morphs": [{"morph": model["morphs"][f["morph"]] if f["morph"] is not None else None,
                        "frame": f["frame"], "value": _r(f["weight"])} for f in morph_keys],
        }
    out["current"] = {
        "bones": {name: {"pos": _vec(cur["position"]), "rot": _bone_rot(cur["rotation"])}
                  for name, cur in zip(model["bones"], model["bone_current"])
                  if not _is_rest(cur["position"], cur["rotation"])},
        "morphs": {name: _r(w) for name, w in zip(model["morphs"], model["morph_current"]) if abs(w) > _EPSILON},
    }
    return out


def _camera_rot(radians):
    x, y, z = radians
    return [_r(math.degrees(-x)), _r(math.degrees(y)), _r(math.degrees(z))]


def _camera_key(frame):
    return {"frame": frame["frame"], "pos": _vec(frame["position"]), "rot": _camera_rot(frame["rotation"]),
            "distance": _r(-frame["distance"]), "fov": frame["fov"], "perspective": not frame["orthographic"]}


def _light_values(frame):
    return {"rgb": [int(round(v * 256.0)) for v in frame["rgb"]], "dir": _vec(frame["direction"])}


def _parent(project, state):
    index = state["parent_model"]
    if index < 0 or index >= len(project["models"]):
        return None, None
    model = project["models"][index]
    bone = state["parent_bone"]
    return model["name"], (model["bones"][bone] if 0 <= bone < len(model["bones"]) else None)


def _accessory_values(project, state):
    parent_model, parent_bone = _parent(project, state)
    return {"pos": _vec(state["position"]), "rot": _degrees(state["rotation"]), "scale": _r(state["scale"]),
            "alpha": _r(1.0 - state["transparency_percent"] / 100.0), "visible": state["visible"],
            "shadow": state["shadow"], "parent_model": parent_model, "parent_bone": parent_bone}


def _sorted_keys(section):
    return sorted([section["init"]] + section["keys"], key=lambda f: f["frame"])


def summarize(project, keys=True):
    models = [_model(i, m, keys) for i, m in enumerate(project["models"])]
    camera_cur = project["camera"]["current"]
    camera_keys = _sorted_keys(project["camera"])
    light_keys = _sorted_keys(project["light"])
    accessories = []
    for i, acc in enumerate(project["accessories"]):
        acc_keys = _sorted_keys(acc)
        accessories.append({
            "index": i, "name": acc["name"], "path": acc["path"], "add_blend": acc["add_blend"],
            "current": _accessory_values(project, acc["current"]),
            "keys": [dict(_accessory_values(project, f), frame=f["frame"]) for f in acc_keys],
        })
    last_frames = [m["last_frame"] for m in project["models"]]
    last_frames += [f["frame"] for f in camera_keys + light_keys]
    for acc in project["accessories"]:
        last_frames += [f["frame"] for f in acc["keys"]]
    selected = project["selected_model_index"]
    return {
        "version": project["version"],
        "frame": project["frame"],
        "last_frame": max(last_frames) if last_frames else 0,
        "view_size": [project["view_width"], project["view_height"]],
        "mode": "camera" if project["editing_camera"] else "model",
        "selected_model": selected if selected < len(project["models"]) else None,
        "models": models,
        "camera": {
            "current": {"pos": _vec(camera_cur["position"]), "rot": _camera_rot(camera_cur["rotation"]),
                        "distance": _r(-camera_cur["target"][2]), "fov": int(round(project["edit_view_angle"])),
                        "perspective": not camera_cur["orthographic"]},
            "keys": [_camera_key(f) for f in camera_keys],
        },
        "light": {
            "current": _light_values(project["light"]["current"]),
            "keys": [dict(_light_values(f), frame=f["frame"]) for f in light_keys],
        },
        "accessories": accessories,
        "wave": dict(project["wave"]),
        "background": {"avi": dict(project["background_avi"]), "image": dict(project["background_image"]),
                       "black": project["black_background"]},
        "play": {"repeat": project["repeat"],
                 "from": project["play_start_frame"] if project["play_from_frame_enabled"] else None,
                 "to": project["play_end_frame"] if project["play_to_frame_enabled"] else None},
        "display": {"information": project["show_information"], "axis": project["show_axis"],
                    "ground_shadow": project["show_ground_shadow"], "self_shadow": project["self_shadow"]["visible"],
                    "fps_limit": _r(project["fps_limit"])},
        "physics": {"mode": project["physics_mode"], "ground": project["physics_ground"],
                    "gravity": {"acceleration": _r(project["gravity"]["current"]["acceleration"]),
                                "direction": _vec(project["gravity"]["current"]["direction"])}},
    }
