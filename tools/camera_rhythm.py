"""Measure how a camera keeps time with the music: its cuts and its motion against the beat, the strong onsets and the
section heads, in frames; and how much of the song it moves, and how.

    python tools/camera_rhythm.py onsets AUDIO OUT.json [--min-z 2] [--gap 0.3] [--cal 0.0467]
    python tools/camera_rhythm.py vmd CAMERA.vmd OUT.json --song SONG.json [--onsets ONSETS.json] [--strong 4]
                                  [--set SET.json] [--size 128x72] [--last F]
    python tools/camera_rhythm.py video VIDEO OUT.json --voice VOICE.json [--onsets ONSETS.json] [--strong 4]
                                  [--from S] [--to S]
    python tools/camera_rhythm.py compare OUT.md OUT.json NAME=FILE ...

Why (2026-10-21, camsync): the requester asked for the camera's cuts and moves to keep time with the song (音ハメ) and
for moving shots (dolly, orbit, crane, tracking, handheld), not still ones.  How a camera does that is measured here,
for our camera motions and, on the same yardstick, for the reference videos (@PizaCG, @Akashi1939).

onsets: the strong onsets of an audio file, as the a04 analysis of the song took them (_spike/out/uncanny/a04_beat s05):
  mono 16 kHz, a Hann window of 1024 samples every 10 ms, the positive change of the log spectrum summed over 30 to
  8000 Hz (spectral flux), z-scored over the song; its peaks at least --gap apart standing --min-z over the mean, each
  at its frame's time plus --cal (the envelope's delay: a04 measured 46.7 ms against the kick's attack).  The camera
  tools read these (and the beat grid of the song's structure) as their input, so a new recording of the song is a
  new run of this.

vmd: a camera motion read frame by frame as MMD shows it (fk.camera_at).  Its cuts are the keys with the step curve
  (make_camera and operator_camera put it on the first key of every shot) and any jump of the eye of more than
  JUMP_EYE units or of the line of sight of more than JUMP_TURN degrees in a frame.  The motion of a frame (from the
  frame before) is told apart as a camera person would name it, about the look-at point L and the eye E: dolly (the
  distance |E - L| changes), orbit (E goes round L: the heading of E - L), crane (the elevation of E - L), track (L
  moves sideways, the camera with it).  Each in its own unit per second, against a threshold (MOVE): a frame moves
  when one of them is over its threshold (the largest of them over its threshold names it); a frame under all of them
  whose line of sight still turns (HANDHELD_TURN) is handheld; else still.  The series are smoothed by a running
  median of SMOOTH frames; the frames round a cut are no motion.  A run of moving frames (gaps of at most MAX_GAP
  closed, MIN_RUN at least) is a move: its start, its stop (the first frame after it) and its peak (the frame its
  strongest component is at its height) are its events, and a turn is a frame where the eye's velocity changes
  direction by more than TURN_ANGLE within TURN_SPAN frames while moving.
  With --set (a stage set of tools/stage_layer.py), the picture's motion as well: the stage drawn as depth at --size
  from every frame's camera, each pixel's point carried into the next frame's picture (a pixel with nothing behind it
  is at FAR), and the similarity transform fitted to that flow as tools/mograph_analyze.py fits a video's
  (_similarity); the same events as a video's, on the same yardstick as the references.

video: the picture's motion of a video as tools/mograph_analyze.py reads it (EventReader: 72 lines, the similarity
  transform of the optical flow, robust to what moves on its own; its cuts), as 720-line px, log scale and degrees a
  frame: per frame the speed (px/s), the zoom (1/s) and the turn (deg/s), each against its threshold (PICTURE_MOVE),
  a moving frame is named by the largest (pan, zoom, roll); runs and events as above.  The beats are the voice run's
  (tools/typo_analyze.py voice: VOICE.json "beats").

The place in the beat (on_grid): every event's signed distance to the nearest point of a grid (the beats, the strong
onsets, the section heads), in frames (- before it); the median; the share within [LEAD_LOW, LEAD_HIGH] frames (the
references cut 2.3 frames before the beat: typorev) and within a frame; the chance of the former; and Rayleigh's R,
p and place of the events' phase in the grid's step (tools/mograph_analyze.py _on_beat).

compare: a table of the numbers of several outputs side by side (Markdown and JSON).
"""
import argparse
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mmd_cli import fk  # noqa: E402
from mmd_cli.formats import vmd  # noqa: E402

_LAZY = {}


def _tool(name):
    if name not in _LAZY:
        spec = importlib.util.spec_from_file_location("_rhythm_" + name, os.path.join(HERE, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LAZY[name] = module
    return _LAZY[name]


FPS = 30
REFERENCE_HEIGHT = 720.0
SMOOTH = 5                        # frames: the running median the per-frame series are smoothed by
MIN_RUN = 6                       # frames: a move lasts at least this long (0.2 s)
MAX_GAP = 3                       # frames: still frames between two moves closed when there are at most this many
# a frame of a camera motion moves when one of these is over its threshold (per second)
MOVE = {"dolly": 0.3,             # units: the distance to the look-at point (about 1 % of 34 a second)
        "orbit": 1.0,             # degrees: the heading of the eye round the look-at point
        "crane": 0.7,             # degrees: the elevation of the eye over the look-at point
        "track": 0.3}             # units: the look-at point sideways (the camera going with it)
HANDHELD_TURN = 0.05              # deg/s: a frame under the thresholds whose line of sight turns this much is handheld
# (make_camera --handheld 1 sways the window angles by 0.3 degrees at 0.13 to 0.57 Hz: up to about 0.5 deg/s, under MOVE)
PICTURE_MOVE = {"pan": 30.0,      # 720-line px/s the picture shifts (1.3 deg/s at a field of 30; a video's flow noise
                                  # is about 15: mograph_analyze CAMERA_NOISE 0.05 px at 72 lines a frame)
                "zoom": 0.01,     # 1/s: the picture's scale (1 % a second)
                "roll": 0.5}      # deg/s
JUMP_EYE = 3.0                    # units in a frame: a jump of the eye is a cut
JUMP_TURN = 10.0                  # degrees in a frame: a jump of the line of sight is a cut
TURN_ANGLE = 90.0                 # degrees the eye's velocity turns within TURN_SPAN frames: a turn
TURN_SPAN = 6
FAR = 5000.0                      # units: a pixel with nothing of the stage behind it
READ = (128, 72)                  # the read size of the picture's motion (mograph_analyze's)
LEAD_LOW, LEAD_HIGH = -3, 1       # frames: an event this near a grid point (before it .. after it) keeps time with it


# ---- onsets ------------------------------------------------------------------------------------------------------------

ONSET_SR = 16000
ONSET_HOP = 0.01                  # s
ONSET_WIN = 1024                  # samples at ONSET_SR
ONSET_BAND = (30.0, 8000.0)       # Hz
ONSET_CAL = 0.0467                # s: a04's calibration (the full-band envelope's peak against the kick's attack)


def onset_envelope(x, sr):
    """(envelope z-scored, frames a second): the positive change of the log spectrum over ONSET_BAND, every ONSET_HOP"""
    x = np.asarray(x, np.float32)
    hop = int(round(sr * ONSET_HOP))
    win = int(round(ONSET_WIN * sr / float(ONSET_SR)))
    n = (len(x) - win) // hop
    if n < 3:
        raise ValueError("the audio is too short for an onset envelope (%d samples)" % len(x))
    frames = np.lib.stride_tricks.as_strided(x, shape=(n, win), strides=(x.strides[0] * hop, x.strides[0]))
    spec = np.abs(np.fft.rfft(frames * np.hanning(win).astype(np.float32), axis=1)).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    band = (freqs >= ONSET_BAND[0]) & (freqs < ONSET_BAND[1])
    m = np.log1p(spec[:, band])
    f = np.concatenate([[0.0], np.maximum(np.diff(m, axis=0), 0.0).sum(axis=1)])
    return (f - f.mean()) / (f.std() + 1e-9), 1.0 / ONSET_HOP


def onsets_of(x, sr, min_z=2.0, gap=0.3, cal=ONSET_CAL):
    """the strong onsets of audio samples x at sr: [{"t": s, "z": strength}] (see the module's docstring)"""
    from scipy import signal
    env, rate = onset_envelope(x, sr)
    peaks, props = signal.find_peaks(env, height=float(min_z), distance=max(1, int(round(gap * rate))))
    return [{"t": round(float(p) / rate + float(cal), 4), "z": round(float(h), 3)} for p, h in zip(peaks, props["peak_heights"])]


def read_audio(path, sr=ONSET_SR):
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


# ---- the place in the grid ---------------------------------------------------------------------------------------------

def on_grid(times, grid, fps=FPS):
    """how events (s) sit against a grid of times (s): see the module's docstring"""
    g = np.sort(np.asarray([t for t in grid if t is not None], np.float64))
    t = np.asarray(times, np.float64)
    out = {"n": int(t.size)}
    if not t.size or g.size == 0:
        out.update({"offset_median": None, "within_lead": None, "within_1": None, "chance_lead": None,
                    "lock_R": None, "lock_p": None, "lock_offset": None})
        return out
    k = np.clip(np.searchsorted(g, t), 1, max(1, g.size - 1)) if g.size > 1 else np.zeros(t.size, int)
    if g.size > 1:
        left, right = g[k - 1], g[np.minimum(k, g.size - 1)]
        near = np.where(np.abs(t - left) <= np.abs(t - right), left, right)
    else:
        near = np.full(t.size, g[0])
    off = (t - near) * fps
    lead = (off >= LEAD_LOW - 1e-6) & (off <= LEAD_HIGH + 1e-6)
    step = float(np.median(np.diff(g))) * fps if g.size > 1 else float("inf")
    _, _, lock = _tool("mograph_analyze")._on_beat(list(t), list(g), fps)
    out.update({"offset_median": round(float(np.median(off)), 3), "within_lead": round(float(lead.mean()), 4),
                "within_1": round(float((np.abs(off) <= 1.0 + 1e-6).mean()), 4),
                "chance_lead": round(min(1.0, (LEAD_HIGH - LEAD_LOW) / step), 4) if math.isfinite(step) else None,
                "lock_R": None if lock[0] != lock[0] else round(lock[0], 4),
                "lock_p": None if lock[1] != lock[1] else float("%.3g" % lock[1]),
                "lock_offset": None if lock[2] != lock[2] else round(lock[2] * fps, 3),
                "offsets": [round(float(v), 2) for v in off]})
    return out


# ---- per-frame series to moves ------------------------------------------------------------------------------------------

def _median_filter(x, width=SMOOTH):
    x = np.asarray(x, np.float64)
    if width <= 1 or x.size == 0:
        return x.copy()
    half = width // 2
    pad = np.pad(x, (half, half), mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, width), axis=1)


def _runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def _closed(mask, gap=MAX_GAP, least=MIN_RUN):
    """the runs of a mask with gaps of at most `gap` closed, and those shorter than `least` dropped"""
    m = np.asarray(mask, bool).copy()
    runs = _runs(m)
    for (a, b), (c, d) in zip(runs, runs[1:]):
        if c - b <= gap:
            m[b:c] = True
    out = np.zeros(len(m), bool)
    for a, b in _runs(m):
        if b - a >= least:
            out[a:b] = True
    return out


def _blocked(n, cuts, reach=1):
    bad = np.zeros(n, bool)
    for c in cuts:
        bad[max(0, c - reach):min(n, c + reach + 1)] = True
    return bad


def _moves(norms, n, blocked, names):
    """(moving mask, per-frame kind, segments) from {kind: series over its threshold}"""
    stack = np.vstack([np.where(blocked, 0.0, norms[k]) for k in names])
    top = stack.max(axis=0)
    kind = np.array([names[i] for i in stack.argmax(axis=0)], dtype=object)
    moving = _closed(top >= 1.0) & ~blocked
    segments = []
    for a, b in _runs(moving):
        sums = stack[:, a:b].sum(axis=1)
        k = names[int(np.argmax(sums))]
        peak = a + int(np.argmax(stack[names.index(k), a:b]))
        segments.append({"start": int(a), "stop": int(b), "kind": k, "peak": int(peak), "frames": int(b - a)})
    return moving, kind, segments


def picture_track(motion, fps=FPS, cuts=()):
    """the moves of a picture's motion (N x 4: dx, dy in 720-line px, log scale, turn in degrees, each a frame): see the
    module's docstring"""
    m = np.asarray(motion, np.float64)
    n = len(m)
    blocked = _blocked(n, cuts)
    speed = _median_filter(np.where(blocked, 0.0, np.hypot(m[:, 0], m[:, 1])) * fps)
    zoom = _median_filter(np.where(blocked, 0.0, m[:, 2]) * fps)
    roll = _median_filter(np.where(blocked, 0.0, m[:, 3]) * fps)
    norms = {"pan": speed / PICTURE_MOVE["pan"], "zoom": np.abs(zoom) / PICTURE_MOVE["zoom"],
             "roll": np.abs(roll) / PICTURE_MOVE["roll"]}
    names = ["pan", "zoom", "roll"]
    moving, kind, segments = _moves(norms, n, blocked, names)
    usable = max(1, int((~blocked).sum()))
    seconds = {k: round(float(((kind == k) & moving).sum()) / fps, 2) for k in names}
    seconds["still"] = round(float((~moving & ~blocked).sum()) / fps, 2)
    return {"frames": n, "moving": moving, "kind": kind, "segments": segments,
            "moving_share": round(float(moving.sum()) / usable, 4), "kinds_seconds": seconds,
            "kinds_count": {k: sum(1 for s in segments if s["kind"] == k) for k in names},
            "speed": speed, "zoom": zoom, "roll": roll}


def _unwrap_deg(a):
    return np.degrees(np.unwrap(np.radians(np.asarray(a, np.float64))))


def camera_states(keys, last):
    frames = [k.frame for k in keys]
    return [fk.camera_at(keys, f, frames) for f in range(last + 1)]


def step_cut_frames(keys):
    oc = _tool("operator_camera")
    return oc.step_cuts(keys)


def camera_kinematics(keys, last, fps=FPS):
    """the motion of a camera motion frame by frame about its look-at point (see the module's docstring): cuts, the
    per-frame components (per second), the moving mask, the kind of every frame and the moves"""
    states = camera_states(keys, last)
    n = len(states)
    E = np.array([fk.camera_position(s) for s in states], np.float64)
    L = np.array([s.look_at for s in states], np.float64)
    D = np.array([fk.camera_direction(s) for s in states], np.float64)
    rel = E - L
    dist = np.linalg.norm(rel, axis=1)
    heading = _unwrap_deg(np.degrees(np.arctan2(rel[:, 0], -rel[:, 2])))
    elevation = np.degrees(np.arctan2(rel[:, 1], np.hypot(rel[:, 0], rel[:, 2])))
    cuts = set(c for c in step_cut_frames(keys) if 0 < c <= last)
    for f in range(1, n):
        turn = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(D[f], D[f - 1]))))))
        if np.linalg.norm(E[f] - E[f - 1]) > JUMP_EYE or turn > JUMP_TURN:
            cuts.add(f)
    cuts = sorted(cuts)

    def rate(x):
        r = np.zeros(n)
        r[1:] = np.diff(x) * fps
        return r
    dolly, orbit, crane = rate(dist), rate(heading), rate(elevation)
    # the look-at point sideways: its horizontal motion across the line of sight
    dl = np.zeros((n, 3))
    dl[1:] = np.diff(L, axis=0) * fps
    side = np.stack([D[:, 2], np.zeros(n), -D[:, 0]], axis=1)
    side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-9)
    track = np.abs((dl * side).sum(axis=1))
    look_turn = np.zeros(n)
    look_turn[1:] = np.degrees(np.arccos(np.clip((D[1:] * D[:-1]).sum(axis=1), -1.0, 1.0))) * fps
    blocked = _blocked(n, cuts)
    comps = {k: _median_filter(np.where(blocked, 0.0, v)) for k, v in
             (("dolly", dolly), ("orbit", orbit), ("crane", crane), ("track", track))}
    norms = {k: np.abs(comps[k]) / MOVE[k] for k in MOVE}
    names = list(MOVE)
    moving, kind, segments = _moves(norms, n, blocked, names)
    turn_rate = _median_filter(np.where(blocked, 0.0, look_turn))
    handheld = ~moving & ~blocked & (turn_rate >= HANDHELD_TURN)
    usable = max(1, int((~blocked).sum()))
    seconds = {k: round(float(((kind == k) & moving).sum()) / fps, 2) for k in names}
    seconds["handheld"] = round(float(handheld.sum()) / fps, 2)
    seconds["still"] = round(float((~moving & ~handheld & ~blocked).sum()) / fps, 2)
    # turns: the eye's velocity changing direction sharply while it moves
    v = np.zeros((n, 3))
    v[1:] = np.diff(E, axis=0)
    v[blocked] = 0.0
    turns = []
    for f in range(TURN_SPAN, n):
        if not (moving[f] and moving[f - TURN_SPAN]):
            continue
        a, b = v[f - TURN_SPAN], v[f]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-6 or nb < 1e-6:
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b) / (na * nb))))))
        if ang > TURN_ANGLE and (not turns or f - turns[-1] > TURN_SPAN):
            turns.append(f)
    return {"frames": n, "cuts": cuts, "moving": moving, "kind": kind, "segments": segments, "turns": turns,
            "moving_share": round(float(moving.sum()) / usable, 4), "kinds_seconds": seconds,
            "kinds_count": {k: sum(1 for s in segments if s["kind"] == k) for k in names},
            "components": comps, "handheld": handheld, "eye": E, "look_at": L}


# ---- the picture's motion of a camera motion (the stage's geometry) ------------------------------------------------------

def _view(state, size):
    return _tool("mv_world").View(state, size)


def _points_of(view, mesh):
    sl = _tool("stage_layer")
    depth, face = sl.rasterize(view, mesh)
    rays = view.rays(1)
    d = np.where(face >= 0, depth, FAR)
    return view.eye[None, None, :] + rays * (d / view.focal)[..., None]


def picture_motion_of_camera(keys, last, mesh, size=READ):
    """per frame (from the frame before) the similarity transform of the picture's flow, as mograph_analyze fits a
    video's: dx, dy (720-line px), log scale, turn (degrees); frame 0 is 0"""
    MA = _tool("mograph_analyze")
    states = camera_states(keys, last)
    w, h = int(size[0]), int(size[1])
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    out = np.zeros((len(states), 4))
    prev = None
    for f, st in enumerate(states):
        view = _view(st, (w, h))
        if prev is not None:
            pts = _points_of(prev, mesh)
            u, v, depth = view.project(pts.reshape(-1, 3))
            u = u.reshape(h, w)
            v = v.reshape(h, w)
            ok = (depth.reshape(h, w) > 1e-6) & np.isfinite(u) & np.isfinite(v)
            flow = np.zeros((h, w, 2))
            flow[..., 0] = np.where(ok, u - xs, 0.0)
            flow[..., 1] = np.where(ok, v - ys, 0.0)
            tx, ty, ls, turn = MA._similarity(flow, weight=ok.astype(np.float64))
            k = REFERENCE_HEIGHT / h
            out[f] = (tx * k, ty * k, ls, turn)
        prev = view
    return out


def motion_of_frames(frames, fps=FPS):
    """the picture's motion of frames (RGB 0..1) as mograph_analyze reads a video: N x 4 (720-line px, log scale, deg)"""
    MA = _tool("mograph_analyze")
    r = MA.EventReader(fps)
    h = None
    for f in frames:
        h = np.asarray(f).shape[0]
        r.push(f)
    m = np.array(r.motion, np.float64)
    if len(m) and h:
        m[:, 0:2] *= REFERENCE_HEIGHT / float(h)
    return m


# ---- the song ----------------------------------------------------------------------------------------------------------

def load_song(path):
    """the grids of a song's structure (as the MV's song_structure.json): beats (s), bars (s), section heads (s)"""
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    fps = float(s.get("fps", FPS))
    heads = []
    for sec in s.get("sections", []):
        if sec.get("t") is not None:
            heads.append(float(sec["t"]))
        elif sec.get("frame") is not None:
            heads.append(float(sec["frame"]) / fps)
    return {"fps": fps, "beats": [float(b) for b in s.get("beats", [])], "bars": [float(b) for b in s.get("bars", [])],
            "sections": heads, "section_ids": [sec.get("id") for sec in s.get("sections", [])], "raw": s}


def load_onsets(path, strong):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    items = d["onsets"] if isinstance(d, dict) else d
    return [float(o["t"]) for o in items if float(o.get("z", 0.0)) >= strong]


def _grids(song, onsets):
    g = {"beats": song["beats"], "sections": song["sections"]}
    if song.get("bars"):
        g["bars"] = song["bars"]
    if onsets is not None:
        g["onsets"] = onsets
    return g


def _events_times(segments, turns, fps):
    return {"starts": [s["start"] / fps for s in segments], "stops": [s["stop"] / fps for s in segments],
            "peaks": [s["peak"] / fps for s in segments], "turns": [f / fps for f in turns]}


def _summary(cuts, n, fps, segments, turns, grids, moving_share, seconds, counts):
    bounds = [0] + list(cuts) + [n]
    lengths = [(b - a) / fps for a, b in zip(bounds, bounds[1:])]
    ev = _events_times(segments, turns, fps)
    return {"frames": n, "seconds": round(n / fps, 2), "cuts": list(cuts),
            "cuts_per_min": round(len(cuts) / (n / fps / 60.0), 3) if n else None,
            "shots_median_s": round(float(np.median(lengths)), 3) if lengths else None,
            "cuts_on_grid": {name: on_grid([c / fps for c in cuts], g, fps) for name, g in grids.items()},
            "moving_share": moving_share, "kinds_seconds": seconds, "kinds_count": counts,
            "segments": segments, "events": {k: [round(t, 3) for t in v] for k, v in ev.items()},
            "events_on_grid": {k: {name: on_grid(v, g, fps) for name, g in grids.items()} for k, v in ev.items()}}


def run_vmd(camera_path, out_path, song_path, onsets_path=None, strong=4.0, set_path=None, size=READ, last=None):
    keys = fk.camera_keys(vmd.load(camera_path))
    song = load_song(song_path)
    fps = song["fps"]
    if last is None:
        last = keys[-1].frame
    onsets = load_onsets(onsets_path, strong) if onsets_path else None
    grids = _grids(song, onsets)
    k = camera_kinematics(keys, last, fps)
    res = {"camera": os.path.abspath(camera_path), "song": os.path.abspath(song_path),
           "onsets": os.path.abspath(onsets_path) if onsets_path else None, "strong": strong, "fps": fps,
           "move": MOVE, "handheld_turn": HANDHELD_TURN, "smooth": SMOOTH}
    res.update(_summary(k["cuts"], k["frames"], fps, k["segments"], k["turns"], grids, k["moving_share"],
                        k["kinds_seconds"], k["kinds_count"]))
    res["per_frame"] = {"kind": [str(x) if m else ("handheld" if hh else "still") for x, m, hh in
                                 zip(k["kind"], k["moving"], k["handheld"])],
                        **{name: [round(float(v), 3) for v in series] for name, series in k["components"].items()}}
    if set_path:
        sl = _tool("stage_layer")
        mesh = sl.set_mesh(sl.load_set(set_path))
        motion = picture_motion_of_camera(keys, last, mesh, size)
        p = picture_track(motion, fps, k["cuts"])
        res["picture"] = _summary(k["cuts"], p["frames"], fps, p["segments"], [], grids, p["moving_share"],
                                  p["kinds_seconds"], p["kinds_count"])
        res["picture"]["per_frame"] = {"speed": [round(float(v), 2) for v in p["speed"]],
                                       "zoom": [round(float(v), 5) for v in p["zoom"]]}
        res["picture"]["set"] = os.path.abspath(set_path)
    _write(out_path, res)
    return res


def run_video(video_path, out_path, voice_path, onsets_path=None, strong=4.0, start=None, end=None):
    MA = _tool("mograph_analyze")
    LA = _tool("look_analyze")
    info = LA.probe(video_path)
    fps = float(info["fps"])
    start = float(start or 0.0)
    end = float(end) if end else info["duration"]
    w, h = MA.read_size(info, READ)
    mat = LA.matrix_for(info)
    rng = "pc" if info.get("color_range") in ("pc", "jpeg") else "tv"
    vf = "scale=%d:%d:flags=area:in_color_matrix=%s:in_range=%s:out_range=pc,format=rgb24" % (w, h, mat, rng)
    pre, post = LA._range_args(start, end - start)
    argv = ["ffmpeg", "-v", "error", "-nostdin"] + pre + ["-i", video_path] + post + \
           ["-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    reader = MA.EventReader(fps)
    for a in LA._ffmpeg_frames(argv, (w, h)):
        reader.push(a.astype(np.float64) / 255.0)
    with open(voice_path, encoding="utf-8") as f:
        voice = json.load(f)
    beats = [float(b) - start for b in voice.get("beats", [])]
    ev = reader.finish({"beats": beats}, 0.0)
    cuts = [c["frame"] for c in ev["cuts"]]
    motion = np.array(reader.motion, np.float64)
    motion[:, 0:2] *= REFERENCE_HEIGHT / float(h)
    p = picture_track(motion, fps, cuts)
    onsets = [t - start for t in load_onsets(onsets_path, strong)] if onsets_path else None
    grids = {"beats": beats}
    if onsets is not None:
        grids["onsets"] = onsets
    res = {"video": os.path.abspath(video_path), "voice": os.path.abspath(voice_path), "range": [start, end],
           "fps": fps, "size": [w, h], "picture_move": PICTURE_MOVE}
    res["picture"] = _summary(cuts, p["frames"], fps, p["segments"], [], grids, p["moving_share"], p["kinds_seconds"],
                              p["kinds_count"])
    res["picture"]["per_frame"] = {"speed": [round(float(v), 2) for v in p["speed"]],
                                   "zoom": [round(float(v), 5) for v in p["zoom"]]}
    _write(out_path, res)
    return res


def _write(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    with open(part, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, allow_nan=False, default=_plain)
    os.replace(part, path)


def _plain(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


# ---- compare -----------------------------------------------------------------------------------------------------------

ROWS = [("cuts_per_min", "カット（1 分あたり）"), ("shots_median_s", "ショットの長さの中央（秒）"),
        ("cuts.beats.offset_median", "カットと拍の差の中央（コマ、- は前）"), ("cuts.beats.within_lead", "拍の -3〜+1 コマのカット"),
        ("cuts.beats.lock_R", "カットの拍の位相の揃い R"), ("cuts.beats.lock_offset", "その揃う所（コマ）"),
        ("cuts.onsets.within_lead", "強い音の -3〜+1 コマのカット"), ("cuts.sections.within_1", "節の頭の 1 コマ以内のカット"),
        ("moving_share", "動いている時間の割合"),
        ("starts.beats.within_lead", "動き出しが拍の -3〜+1 コマ"), ("starts.beats.lock_R", "動き出しの拍の揃い R"),
        ("starts.onsets.within_lead", "動き出しが強い音の -3〜+1 コマ"), ("stops.beats.within_lead", "止まりが拍の -3〜+1 コマ"),
        ("peaks.beats.within_lead", "速さの山が拍の -3〜+1 コマ")]


def _pick(part, key):
    if key.count(".") == 2:
        ev, grid, stat = key.split(".")
        src = part.get("cuts_on_grid", {}) if ev == "cuts" else part.get("events_on_grid", {}).get(ev, {})
        return (src.get(grid) or {}).get(stat)
    return part.get(key)


def compare(md_path, json_path, items):
    cols = []
    for item in items:
        name, path = item.split("=", 1)
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        cols.append((name, r))
    table = {"columns": [n for n, _ in cols], "rows": []}
    lines = ["| 測り | " + " | ".join(n for n, _ in cols) + " |", "| --- |" + " --- |" * len(cols)]
    for side in ("camera", "picture"):
        for key, label in ROWS:
            vals = []
            for _, r in cols:
                src = r if side == "camera" else r.get("picture")
                if side == "camera" and "camera" not in r:
                    src = None
                vals.append(None if src is None else _pick(src, key))
            if all(v is None for v in vals):
                continue
            table["rows"].append({"side": side, "key": key, "label": label, "values": vals})
            lines.append("| %s（%s） | " % (label, "カメラ" if side == "camera" else "絵の動き") +
                         " | ".join("-" if v is None else ("%.3g" % v if isinstance(v, float) else str(v)) for v in vals) + " |")
        kinds = sorted({k for _, r in cols for k in ((r if side == "camera" else r.get("picture") or {}).get("kinds_seconds") or {})})
        for k in kinds:
            vals = []
            for _, r in cols:
                src = r if side == "camera" else r.get("picture")
                if side == "camera" and "camera" not in r:
                    src = None
                ks = (src or {}).get("kinds_seconds") or {}
                kc = (src or {}).get("kinds_count") or {}
                vals.append(None if k not in ks else "%s 秒 / %s 回" % (ks[k], kc.get(k, "-")))
            table["rows"].append({"side": side, "key": "kind." + k, "values": vals})
            lines.append("| %s（%s） | " % (k, "カメラ" if side == "camera" else "絵の動き") + " | ".join(v or "-" for v in vals) + " |")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    _write(json_path, table)
    return table


def _size(text):
    w, h = (int(v) for v in text.lower().split("x"))
    return w, h


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("onsets", help="the strong onsets of an audio file")
    s.add_argument("audio")
    s.add_argument("out")
    s.add_argument("--min-z", type=float, default=2.0)
    s.add_argument("--gap", type=float, default=0.3)
    s.add_argument("--cal", type=float, default=ONSET_CAL)
    s = sub.add_parser("vmd", help="a camera motion's cuts and moves against the song")
    s.add_argument("camera")
    s.add_argument("out")
    s.add_argument("--song", required=True, help="the song's structure (beats, bars, sections)")
    s.add_argument("--onsets", help="the strong onsets (camera_rhythm.py onsets)")
    s.add_argument("--strong", type=float, default=4.0, help="the least z of an onset counted strong (default 4, a04's)")
    s.add_argument("--set", help="a stage set: measure the picture's motion as well")
    s.add_argument("--size", type=_size, default=READ)
    s.add_argument("--last", type=int)
    s = sub.add_parser("video", help="a video's cuts and picture motion against its beats")
    s.add_argument("video")
    s.add_argument("out")
    s.add_argument("--voice", required=True, help="the voice run of tools/typo_analyze.py (its beats)")
    s.add_argument("--onsets")
    s.add_argument("--strong", type=float, default=4.0)
    s.add_argument("--from", dest="start", type=float)
    s.add_argument("--to", dest="end", type=float)
    s = sub.add_parser("compare", help="the numbers of several outputs side by side")
    s.add_argument("md")
    s.add_argument("json")
    s.add_argument("items", nargs="+", help="NAME=OUT.json")
    a = p.parse_args(argv)
    try:
        if a.what == "onsets":
            x = read_audio(a.audio)
            found = onsets_of(x, ONSET_SR, a.min_z, a.gap, a.cal)
            _write(a.out, {"audio": os.path.abspath(a.audio), "min_z": a.min_z, "gap": a.gap, "cal": a.cal,
                           "band": list(ONSET_BAND), "onsets": found})
            result = {"onsets": len(found), "strong_4": sum(1 for o in found if o["z"] >= 4.0)}
        elif a.what == "vmd":
            r = run_vmd(a.camera, a.out, a.song, a.onsets, a.strong, a.set, a.size, a.last)
            result = {"cuts": len(r["cuts"]), "cuts_per_min": r["cuts_per_min"], "moving_share": r["moving_share"]}
        elif a.what == "video":
            r = run_video(a.video, a.out, a.voice, a.onsets, a.strong, a.start, a.end)
            result = {"cuts": len(r["picture"]["cuts"]), "moving_share": r["picture"]["moving_share"]}
        else:
            t = compare(a.md, a.json, a.items)
            result = {"rows": len(t["rows"])}
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"ok": False, "error": {"type": type(e).__name__, "message": str(e)}}, ensure_ascii=True))
        return 2
    print(json.dumps(dict({"ok": True}, **result), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
