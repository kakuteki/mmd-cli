"""Marks on a rendered picture (実物に図示): the base of support, the centre of mass and the ZMP of the frame, drawn where the
camera of the render puts them, and the listed places of the report that cover the frame, written beside.

The projection (the one wbbalance checked on the front camera's renders, fig_frames.project): the camera of the frame
from its VMD (mmd_cli.fk.camera_at: the window's look-at, distance, angles and vertical view angle), its position and
direction (fk.camera_position, fk.camera_direction), right = up x forward, the focal length (H / 2) / tan(fov / 2) in
pixels of the picture's height H, the picture's middle as the centre.  A camera with a roll (its Z angle) is refused:
the projection has not been checked for one.

The points (the report's marks.npz, written by `measure`): the COM [F, 3] and the ZMP [F, 2] (x, z) of tools/wb_dynamics
(in model units here), the convex hull of the base of support per frame (units, x and z) and the floor's height.
"""
import json
import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw

from . import base
from .plot import font

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402

UNIT_M = 0.08


class Camera:
    def __init__(self, path):
        self.keys = fk.camera_keys(vmd.load(path))
        self.frames = [k.frame for k in self.keys]

    def at(self, frame, size):
        st = fk.camera_at(self.keys, frame, self.frames)
        if abs(st.angles[2]) > 1e-6:
            raise ValueError("the camera rolls (Z angle %.3f) at frame %d: the projection is not checked for a roll" % (st.angles[2], frame))
        C = np.array(fk.camera_position(st))
        fwd = np.array(fk.camera_direction(st))
        right = np.cross(np.array([0.0, 1.0, 0.0]), fwd)
        right /= np.linalg.norm(right)
        up = np.cross(fwd, right)
        W, H = size
        f = (H / 2.0) / math.tan(math.radians(st.fov) / 2.0)
        return C, fwd, right, up, f, (W / 2.0, H / 2.0)


def project(P, cam):
    """pixels [N, 2] of world points P [N, 3] (units); NaN behind the camera"""
    C, fwd, right, up, f, (cx, cy) = cam
    p = np.atleast_2d(np.asarray(P, dtype=np.float64)) - C
    z = p @ fwd
    out = np.stack([cx + f * (p @ right) / np.where(z > 1e-6, z, np.nan), cy - f * (p @ up) / np.where(z > 1e-6, z, np.nan)], 1)
    return out


def save_points(path, wb_arrays):
    """marks.npz from the wb arrays (metres) of shared.Measured.wb()"""
    hulls = wb_arrays["hulls"]
    off = np.zeros(len(hulls) + 1, dtype=np.int64)
    for i, h in enumerate(hulls):
        off[i + 1] = off[i] + len(h)
    pts = np.concatenate([np.asarray(h, dtype=np.float64).reshape(-1, 2) for h in hulls], 0) if off[-1] else np.zeros((0, 2))
    np.savez_compressed(path, com=np.asarray(wb_arrays["com"]) / UNIT_M, zmp=np.asarray(wb_arrays["zmp"]) / UNIT_M,
                        margin_cm=np.asarray(wb_arrays["margin"]) * 100.0, hull_pts=pts / UNIT_M, hull_off=off,
                        floor_y=np.array(float(wb_arrays["floor_y"])))


def load_points(path):
    z = np.load(path)
    return {k: z[k] for k in z.files}


def hull_of(pts, f):
    return pts["hull_pts"][pts["hull_off"][f]:pts["hull_off"][f + 1]]


def frame_of_video(video, t, out):
    """the picture of `video` at t seconds (ffmpeg, exact seek), saved to out"""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.4f" % t, "-i", video, "-frames:v", "1", out], check=True)
    return out


def draw(img, frame, pts, cam, events, label):
    """the picture with the marks; (picture, the drawn points in pixels)"""
    img = img.convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    fy = float(pts["floor_y"])
    info = {"frame": int(frame)}
    hull = hull_of(pts, frame)
    if len(hull) >= 1:
        P = np.stack([hull[:, 0], np.full(len(hull), fy), hull[:, 1]], 1)
        q = project(P, cam)
        if len(hull) >= 3 and np.all(np.isfinite(q)):
            d.polygon([tuple(x) for x in q], fill=(60, 200, 90, 70), outline=(30, 150, 60, 255))
        info["support_px"] = q.round(1).tolist()
    com = pts["com"][frame]
    if np.all(np.isfinite(com)):
        q3 = project(com, cam)[0]
        qf = project([com[0], fy, com[2]], cam)[0]
        if np.all(np.isfinite(q3)) and np.all(np.isfinite(qf)):
            for k in range(0, 20, 2):
                a = q3 + (qf - q3) * k / 20.0
                b = q3 + (qf - q3) * (k + 1) / 20.0
                d.line([tuple(a), tuple(b)], fill=(255, 210, 0, 255), width=2)
            d.ellipse([q3[0] - 6, q3[1] - 6, q3[0] + 6, q3[1] + 6], outline=(255, 210, 0, 255), width=3)
            d.ellipse([qf[0] - 4, qf[1] - 4, qf[0] + 4, qf[1] + 4], fill=(255, 210, 0, 255))
            info["com_px"], info["com_floor_px"] = q3.round(1).tolist(), qf.round(1).tolist()
    zmp = pts["zmp"][frame]
    if np.all(np.isfinite(zmp)):
        qz = project([zmp[0], fy, zmp[1]], cam)[0]
        if np.all(np.isfinite(qz)):
            d.line([qz[0] - 7, qz[1] - 7, qz[0] + 7, qz[1] + 7], fill=(230, 30, 30, 255), width=3)
            d.line([qz[0] - 7, qz[1] + 7, qz[0] + 7, qz[1] - 7], fill=(230, 30, 30, 255), width=3)
            info["zmp_px"] = qz.round(1).tolist()
    out = Image.alpha_composite(img, over)
    d = ImageDraw.Draw(out)
    f_big, f_small = font(20), font(15)
    t = frame / base.FPS
    mg = pts["margin_cm"][frame]
    lines = ["%s  %d コマ（%.2f 秒）" % (label, frame, t),
             "黄 = 重心（丸）とその真下の床（点）、緑 = 支持基底面、赤 × = ZMP" + ("（支えの%s %.1f cm）" % ("中" if mg >= 0 else "外", abs(mg)) if np.isfinite(mg) else "")]
    here = sorted([e for e in events if e["first"] <= frame <= e["last"]], key=lambda e: -e["severity"])[:5]
    for e in here:
        lines.append("● %s %s: %s %s（%s）" % (base.CONCEPT_NAMES.get(e["concept"], e["concept"]), e["id"].split(".", 1)[1],
                                            base.num(e["value"]), e["unit"], e["note"]))
    if not here:
        lines.append("（このコマに時刻表の外れは無い）")
    y = 8
    box_w = max(d.textlength(s, font=f_small) for s in lines) + 20
    d.rectangle([4, 4, 4 + box_w, 8 + 22 + 19 * (len(lines) - 1) + 8], fill=(255, 255, 255))
    for i, s in enumerate(lines):
        d.text((12, y), s, fill=(214, 39, 40) if s.startswith("●") else (30, 30, 30), font=f_big if i == 0 else f_small)
        y += 24 if i == 0 else 19
    info["events"] = [e["id"] for e in here]
    return out.convert("RGB"), info


def mark(report, points_path, camera_path, pictures, out_dir):
    """pictures: [(frame, picture path)]; writes mark_<frame>.png and marks.json; returns the json"""
    pts = load_points(points_path)
    cam = Camera(camera_path)
    evs = [e for e in report["events"] if e.get("listed")]
    os.makedirs(out_dir, exist_ok=True)
    res = []
    for frame, path in pictures:
        img = Image.open(path)
        c = cam.at(frame, img.size)
        out, info = draw(img, frame, pts, c, evs, report["label"])
        p = os.path.join(out_dir, "mark_%05d.png" % frame)
        out.save(p)
        info["picture"] = path
        info["out"] = p
        res.append(info)
    with open(os.path.join(out_dir, "marks.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res
