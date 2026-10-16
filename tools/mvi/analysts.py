"""The functions of the uncanny analysis (2026-10-07) that the human baseline (stage 6, 2026-10-15) ran on people and on
the MV, copied as they are from its verbatim copies (stage6/human_baseline/scripts/ported/, md5 in refs/ported_md5.txt):

* a01_hold/analyze.py: PARTS, UPPER, EXACT, MAIN, qrot, runs, part_speeds
* a20_holistic/work/qlib.py: qconj, qmul, qangle, ang_speed, lin_speed, runs (as runs20)
* a02_spacing/s13_dips.py: dips, band (and its BINS)
* a08_smooth/common.py (FPS, UNIT_M, step), s1_events.py (VFAST, WIN, DEEP, crossing_time, measure_stop, find_events),
  s2_spectrum.py (POINTS, T_SPIKE, BANDS, NWIN, welch, band_power, spikes)
* a09_arcs/scripts/qmath.py (qmul9, qconj9, qnorm, qlog, relative, step_rotvec, angular_speed, continuous) and
  s04_timing.py (parabola, xcorr_lags, rests, summary)
* a18_physics/scripts/body_motion.py: its module code as one function, body_motion(names, pos, rot), returning its
  `res` and its printed `lines` (and the events behind them)

Only the module-level code that loaded the pack or wrote files is left out; the expressions are the analysts'.  Where a
name would clash between two analysts' files, the later one has a suffix (runs20, qmul9...).
"""
import numpy as np

# ==== a01_hold/analyze.py ============================================================================================
UNIT_MM = 80.0          # 1 MMD unit ~ 8 cm (pack README)
FPS = 30
EXACT = 0.01            # mm/s: below this a step is a numerically exact hold (float32 positions give ~0.003 mm/s)
MAIN = 1.0              # mm/s: the main "stopped" threshold (see report: 1/6 of the stillest person's head speed)

PARTS = {   # part -> (bones whose world positions are its points, virtual points: (bone, rest offset in units))
    "trunk": (["下半身", "上半身2", "首", "左肩", "右肩"], [("下半身", (0.9, -1.0, 0.0)), ("下半身", (-0.9, -1.0, 0.0))]),
    "head": (["頭", "左目", "右目"], []),
    "arm_L": (["左腕", "左ひじ", "左手首"], []),
    "arm_R": (["右腕", "右ひじ", "右手首"], []),
    "hand_L": (["左手首", "左中指３"], []),
    "hand_R": (["右手首", "右中指３"], []),
    "foot_L": (["左足ＩＫ", "左つま先ＩＫ"], []),
    "foot_R": (["右足ＩＫ", "右つま先ＩＫ"], []),
}
UPPER = ["trunk", "head", "arm_L", "arm_R", "hand_L", "hand_R"]      # whole body without the feet


def qrot(q, v):
    """v turned by unit quaternions q (x, y, z, w), broadcast"""
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], -1)


def runs(mask):
    """[(start, length)] of the True runs of a 1-D bool array"""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return list(zip(starts.tolist(), (ends - starts).tolist()))


def part_speeds(pos, rot, names):
    idx = {n: i for i, n in enumerate(names)}
    p64, r64 = pos.astype(np.float64), rot.astype(np.float64)
    out = {}
    for part, (bones, virtual) in PARTS.items():
        pts = [p64[:, idx[b]] for b in bones]
        for b, off in virtual:
            pts.append(p64[:, idx[b]] + qrot(r64[:, idx[b]], np.array(off)))
        sp = np.stack([np.linalg.norm(np.diff(p, axis=0), axis=-1) for p in pts], 1) * UNIT_MM * FPS
        out[part] = sp.max(1)
    out["upper_body"] = np.max(np.stack([out[p] for p in UPPER], 1), 1)
    out["whole_body"] = np.max(np.stack([out[p] for p in PARTS], 1), 1)
    return out


# ==== a20_holistic/work/qlib.py =====================================================================================
U2CM = 8.0      # 1 MMD unit ~ 8 cm (pack README)
FPS20 = 30.0


def qconj(q):
    c = q.copy(); c[..., :3] *= -1; return c  # noqa: E702


def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qangle(q):
    """rotation angle in degrees of unit quaternions (atan2 form: stable for small angles with float32 inputs)"""
    v = np.linalg.norm(q[..., :3], axis=-1)
    return np.degrees(2.0 * np.arctan2(v, np.abs(q[..., 3])))


def ang_speed(q):
    """deg/s between consecutive frames of q[F,4]; first frame 0"""
    d = qmul(qconj(q[:-1]), q[1:])
    s = np.concatenate([[0.0], qangle(d)]) * FPS20
    return s


def lin_speed(p):
    """cm/s of positions p[F,3] (MMD units)"""
    s = np.linalg.norm(np.diff(p, axis=0), axis=1) * FPS20 * U2CM
    return np.concatenate([[0.0], s])


def runs20(mask, min_len=1):
    """list of (start, end_inclusive) of True runs with length >= min_len"""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    st = np.where(d == 1)[0]; en = np.where(d == -1)[0] - 1  # noqa: E702
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a + 1 >= min_len]


# ==== a02_spacing/s13_dips.py ========================================================================================
BINS = [0.0, 0.25, 0.5, 0.75, 0.9]


def dips(s):
    n = len(s)
    moving = np.median(s[s > 0.05 * np.percentile(s, 90)])
    counts = np.zeros(len(BINS))
    for i in range(1, n - 1):
        if s[i] <= s[i - 1] and s[i] < s[i + 1]:
            j = i
            while j > 0 and s[j - 1] >= s[j]:
                j -= 1
            k = i
            while k < n - 1 and s[k + 1] >= s[k]:
                k += 1
            ref = min(s[j], s[k])
            if ref < moving:
                continue
            r = s[i] / ref
            b = np.searchsorted(BINS, r, side="right") - 1
            if r < 0.9:
                counts[b] += 1
    return counts / (n / 30.0)


def band(v, lo=3.0, hi=6.0):
    x = v - v.mean(0)
    win = np.hanning(128)
    acc, cnt = None, 0
    for a in range(0, len(x) - 128 + 1, 64):
        pw = (np.abs(np.fft.rfft(x[a:a + 128] * win[:, None], axis=0)) ** 2).sum(1)
        acc = pw if acc is None else acc + pw
        cnt += 1
    f = np.fft.rfftfreq(128, 1 / 30.0)
    return float(acc[(f >= lo) & (f < hi)].sum() / acc[1:].sum())


# ==== a08_smooth: common.py, s1_events.py, s2_spectrum.py ============================================================
FPS08 = 30.0
UNIT_M = 0.08                      # 1 MMD unit is about 8 cm (README)


def step(p):
    """forward step velocity between frame f and f+1 (m/s), length F-1"""
    return np.diff(p, axis=0) * FPS08


POINTS = ["右手首", "左手首", "右中指３", "左中指３", "頭", "センター", "右足ＩＫ", "左足ＩＫ"]
VFAST = {"右手首": 1.5, "左手首": 1.5, "右中指３": 1.5, "左中指３": 1.5, "頭": 0.6, "センター": 0.6, "右足ＩＫ": 1.0, "左足ＩＫ": 1.0}
WIN = 8
DEEP = 0.4


def crossing_time(s, start, stop, level, falling=True):
    """first sub-frame position in [start, stop] where s crosses `level` (falling: from above to below)"""
    for i in range(start, stop):
        a, b = s[i], s[i + 1]
        if falling and a >= level > b or (not falling) and a <= level < b:
            return i + (a - level) / (a - b)
    return np.nan


def measure_stop(s, i0, falling=True):
    """around the reference minimum i0: own minimum within +-2, own peak within WIN before (stop) / after (start)"""
    lo, hi = max(0, i0 - 2), min(len(s) - 1, i0 + 2)
    imin = lo + int(np.argmin(s[lo:hi + 1]))
    if falling:
        a = max(0, imin - WIN)
        ipk = a + int(np.argmax(s[a:imin + 1]))
    else:
        b = min(len(s) - 1, imin + WIN)
        ipk = imin + int(np.argmax(s[imin:b + 1]))
    vpk, vmin = s[ipk], s[imin]
    drop = vpk - vmin
    hi80, lo20 = vmin + 0.8 * drop, vmin + 0.2 * drop
    if falling:
        # last time above 80 % before imin, then first below 20 %
        t80 = np.nan
        for i in range(imin - 1, ipk - 1, -1):
            if s[i] >= hi80 > s[i + 1]:
                t80 = i + (s[i] - hi80) / (s[i] - s[i + 1])
                break
        t20 = crossing_time(s, int(np.floor(t80)) if np.isfinite(t80) else ipk, imin, lo20, True)
        dt = t20 - t80
        seg = s[ipk:imin + 1]
        maxchg = float(np.max(-np.diff(seg)) * FPS08) if len(seg) > 1 else 0.0
    else:
        t20 = np.nan
        for i in range(imin, ipk):
            if s[i] <= lo20 < s[i + 1]:
                t20 = i + (lo20 - s[i]) / (s[i + 1] - s[i])
                break
        t80 = crossing_time(s, int(np.floor(t20)) if np.isfinite(t20) else imin, ipk, hi80, False)
        dt = t80 - t20
        seg = s[imin:ipk + 1]
        maxchg = float(np.max(np.diff(seg)) * FPS08) if len(seg) > 1 else 0.0
    return {"imin": int(imin), "ipk": int(ipk), "vpk": float(vpk), "vmin": float(vmin), "t_80_20": float(dt),
            "max_dv": maxchg}


def find_events(r, vfast, falling=True):
    out = []
    n = len(r)
    for i in range(3, n - 3):
        if r[i] > r[i - 1] or r[i] > r[i + 1] or r[i] != r[max(0, i - 3):i + 4].min():
            continue
        if falling:
            a = max(0, i - WIN)
            pk = r[a:i].max() if i > a else 0
        else:
            b = min(n, i + WIN + 1)
            pk = r[i + 1:b].max() if b > i + 1 else 0
        if pk >= vfast and r[i] <= DEEP * pk:
            out.append(i)
    return out


T_SPIKE = {"右手首": 0.5, "左手首": 0.5, "右中指３": 0.6, "左中指３": 0.6, "頭": 0.15, "センター": 0.15, "右足ＩＫ": 0.4, "左足ＩＫ": 0.4}
BANDS = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 8), (8, 10), (10, 12), (12, 15.01)]
NWIN = 128


def welch(x):
    """x[N, 3] -> freqs, psd summed over the 3 axes (units^2 / Hz)"""
    w = np.hanning(NWIN)
    scale = FPS08 * (w ** 2).sum()
    out = None
    n = 0
    for s in range(0, len(x) - NWIN + 1, NWIN // 2):
        seg = x[s:s + NWIN] - x[s:s + NWIN].mean(axis=0)
        f = np.fft.rfft(seg * w[:, None], axis=0)
        p = (np.abs(f) ** 2).sum(axis=1) / scale
        p[1:-1] *= 2
        out = p if out is None else out + p
        n += 1
    return np.fft.rfftfreq(NWIN, 1 / FPS08), out / n


def band_power(freqs, psd):
    df = freqs[1] - freqs[0]
    return [float(psd[(freqs >= lo) & (freqs < hi)].sum() * df) for lo, hi in BANDS]


def spikes(s, t):
    up = (s[1:-1] - s[:-2] > t) & (s[1:-1] - s[2:] > t)
    dn = (s[:-2] - s[1:-1] > t) & (s[2:] - s[1:-1] > t)
    return int(up.sum()), int(dn.sum())


def spike_steps(s, t):
    """(the steps of spikes() itself: the indices into s of the bumps and of the dips) -- added for the event list"""
    up = (s[1:-1] - s[:-2] > t) & (s[1:-1] - s[2:] > t)
    dn = (s[:-2] - s[1:-1] > t) & (s[2:] - s[1:-1] > t)
    return np.flatnonzero(up) + 1, np.flatnonzero(dn) + 1


# ==== a09_arcs/scripts/qmath.py and s04_timing.py ====================================================================

def qmul9(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj9(q):
    out = q.copy()
    out[..., :3] *= -1.0
    return out


def qnorm(q):
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def qlog(q):
    """rotation vector (axis * angle, radians) of unit quaternions, the short way"""
    q = np.where(q[..., 3:4] < 0, -q, q)
    v = q[..., :3]
    s = np.linalg.norm(v, axis=-1)
    ang = 2.0 * np.arctan2(s, q[..., 3])
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(s > 1e-12, ang / s, 2.0)
    return v * k[..., None]


def relative(parent, child):
    """the child's rotation in the parent's frame: parent^-1 * child"""
    return qnorm(qmul9(qconj9(parent), child))


def step_rotvec(q):
    """rotation vector of the turn from frame t to t+1, in the body frame of frame t: log(q_t^-1 q_t+1); shape [F-1, 3]"""
    return qlog(qnorm(qmul9(qconj9(q[:-1]), q[1:])))


def angular_speed(q, fps=30):
    """deg/s of the turn between consecutive frames (at the half frames t+0.5); shape [F-1]"""
    return np.degrees(np.linalg.norm(step_rotvec(q), axis=-1)) * fps


def continuous(q):
    """flip signs so that consecutive quaternions are in the same hemisphere"""
    q = q.copy()
    for t in range(1, len(q)):
        if np.dot(q[t], q[t - 1]) < 0:
            q[t] = -q[t]
    return q


CHAIN = ["torso", "clav", "shoulder", "elbow", "wrist", "finger"]


def parabola(y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if den != 0:
            return i + 0.5 * (a - c) / den
    return float(i)


def xcorr_lags(p, d, win=60, step=15, maxlag=6):
    out = []
    for s in range(0, len(p) - win - 2 * maxlag, step):
        a = p[s + maxlag:s + maxlag + win]
        if a.std() < 20:
            continue
        cs = []
        for L in range(-maxlag, maxlag + 1):
            b = d[s + maxlag + L:s + maxlag + L + win]
            if b.std() < 20:
                cs.append(np.nan)
                continue
            cs.append(np.corrcoef(a, b)[0, 1])
        cs = np.array(cs)
        if np.all(np.isnan(cs)):
            continue
        i = int(np.nanargmax(cs))
        if cs[i] < 0.5 or i in (0, len(cs) - 1):
            continue
        out.append((s, parabola(np.nan_to_num(cs, nan=-1), i) - maxlag, float(cs[i])))
    return out


def rests(sh, el, wr, thr=5.0, minlen=3):
    still = (sh < thr) & (el < thr) & (wr < thr)
    runs_, i, n = [], 0, len(still)
    while i < n:
        if still[i]:
            j = i
            while j < n and still[j]:
                j += 1
            if j - i >= minlen:
                runs_.append((i, j))          # still on [i, j)
            i = j
        else:
            i += 1
    return runs_


def summary(vals):
    v = np.array(vals, float)
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "mean": round(float(v.mean()), 3), "median": round(float(np.median(v)), 3),
            "p10": round(float(np.percentile(v, 10)), 3), "p90": round(float(np.percentile(v, 90)), 3),
            "share_zero": round(float(np.mean(np.abs(v) < 0.5)), 3), "share_pos": round(float(np.mean(v >= 0.5)), 3),
            "share_neg": round(float(np.mean(v <= -0.5)), 3)}


# ==== a18_physics/scripts/body_motion.py =============================================================================
FPS18 = 30.0


def _qmul18(a, b):
    x1, y1, z1, w1 = np.moveaxis(a, -1, 0)
    x2, y2, z2, w2 = np.moveaxis(b, -1, 0)
    return np.stack([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                     w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2], -1)


def _qconj18(q):
    return q * np.array([-1, -1, -1, 1.0])


def _qrot18(q, v):
    """rotate vector v (3,) by quaternions q (...,4)"""
    vq = np.zeros(q.shape[:-1] + (4,))
    vq[..., :3] = v
    return _qmul18(_qmul18(q, vq), _qconj18(q))[..., :3]


def _ang_speed18(q):
    """angular speed (deg/s) between successive frames, central (length F, edges copied)"""
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    d = _qmul18(q[1:], _qconj18(q[:-1]))
    w = np.clip(np.abs(d[:, 3]), 0, 1)
    ang = 2 * np.degrees(np.arccos(w)) * FPS18          # deg/s for each step f -> f+1
    # world angular velocity vector
    s = np.sqrt(np.maximum(1 - w ** 2, 1e-12))
    axis = d[:, :3] * np.sign(d[:, 3:4]) / s[:, None]
    vec = axis * ang[:, None]
    full = np.zeros(len(q))
    full[1:-1] = 0.5 * (ang[1:] + ang[:-1])
    full[0], full[-1] = ang[0], ang[-1]
    vfull = np.zeros((len(q), 3))
    vfull[1:-1] = 0.5 * (vec[1:] + vec[:-1])
    vfull[0], vfull[-1] = vec[0], vec[-1]
    return full, vfull


def _heading18(q):
    f = _qrot18(q, np.array([0, 0, -1.0]))
    return np.degrees(np.unwrap(np.arctan2(f[:, 0], -f[:, 2])))


def body_motion(names, pos, rot):
    """body_motion.py's module code on (names, pos, rot) as the pack gives them: (res, lines, events) -- events (added):
    {"spins": [(a, b, deg)], "sudden_stops": {bone: [(f, g, hold, deg/s)]}, "holds": [(a, b, pre_deg_s, pre_u_s)]}"""
    ix = {n: i for i, n in enumerate(names)}
    res = {}
    for b in ("下半身", "上半身", "上半身2", "頭"):
        q = rot[:, ix[b]]
        res["yaw_" + b] = _heading18(q)
        res["yawrate_" + b] = np.gradient(res["yaw_" + b]) * FPS18
        res["angspeed_" + b], res["angvel_" + b] = _ang_speed18(q)
    grv = pos[:, ix["グルーブ"]]
    head = pos[:, ix["頭"]]
    hip = pos[:, ix["下半身"]]
    res["center_y"] = grv[:, 1]
    res["center_vy"] = np.gradient(grv[:, 1]) * FPS18
    res["hip_pos"] = hip
    res["head_pos"] = head
    vel = np.gradient(head, axis=0) * FPS18
    acc = np.gradient(vel, axis=0) * FPS18
    res["head_speed"] = np.linalg.norm(vel, axis=1)
    res["head_acc"] = np.linalg.norm(acc, axis=1)
    hv = np.gradient(hip, axis=0) * FPS18
    res["hip_speed"] = np.linalg.norm(hv, axis=1)
    res["hip_acc"] = np.linalg.norm(np.gradient(hv, axis=0) * FPS18, axis=1)
    res["hip_vy"] = hv[:, 1]

    lines = []
    events = {"spins": [], "sudden_stops": {}, "holds": []}
    F = len(head)
    for k in ("yawrate_下半身", "yawrate_上半身", "yawrate_頭", "angspeed_頭", "angspeed_上半身", "head_speed", "head_acc", "hip_speed", "hip_acc", "center_vy"):
        a = np.abs(res[k])
        lines.append("%-16s p50=%.1f p90=%.1f p99=%.1f max=%.1f at f%d" % (k, np.percentile(a, 50), np.percentile(a, 90), np.percentile(a, 99), a.max(), a.argmax()))

    # spins: net heading change of the lower body over a 1 s window
    yaw = res["yaw_下半身"]
    win = 30
    d = np.abs(yaw[win:] - yaw[:-win])
    lines.append("lower-body heading change within 1 s: p99=%.0f max=%.0f deg at f%d" % (np.percentile(d, 99), d.max(), d.argmax()))
    # list the spin events: windows with > 150 deg in 1 s, merged
    ev = []
    f = 0
    while f < len(d):
        if d[f] > 150:
            g = f
            while g < len(d) and d[g] > 150:
                g += 1
            seg = d[f:g]
            k = f + seg.argmax()
            ev.append((k, k + win, float(d[k])))
            f = g
        else:
            f += 1
    lines.append("spins (>150 deg of lower-body heading within 1 s): %d" % len(ev))
    events["spins"] = ev
    for a, b, v in ev:
        yr = res["yawrate_下半身"][a:b]
        lines.append("  f%d-%d (%.1f-%.1f s) turn %.0f deg, peak yaw rate %.0f deg/s at f%d" % (a, b, a / FPS18, b / FPS18, v, np.abs(yr).max(), a + np.abs(yr).argmax()))

    # sudden stops of the head / upper body rotation: angular speed falls from > hi to < lo within n frames
    for bname, hi, lo in (("頭", 300, 40), ("上半身", 250, 40), ("下半身", 250, 40)):
        sp = res["angspeed_" + bname]
        stops = []
        f = 0
        while f < F - 1:
            if sp[f] > hi:
                g = f + 1
                while g < min(F, f + 6) and sp[g] > lo:
                    g += 1
                if g < min(F, f + 6) and sp[g] <= lo:
                    # find the hold after: frames below lo
                    h = g
                    while h < F and sp[h] <= lo * 1.5:
                        h += 1
                    stops.append((f, g, h - g, float(sp[f])))
                    f = h
                    continue
            f += 1
        lines.append("sudden stops of %s (>%d -> <%d deg/s within 5 frames): %d" % (bname, hi, lo, len(stops)))
        events["sudden_stops"][bname] = stops
        for a, b, hold, v in stops[:40]:
            lines.append("  f%d -> f%d (%.2f s) from %.0f deg/s, then still for %d frames" % (a, b, a / FPS18, v, hold))

    # holds: windows where head angspeed < 25 and head speed < 1 unit/s for >= 15 frames, preceded within 10 frames by fast motion
    sp = res["angspeed_頭"]
    hs = res["head_speed"]
    still = (sp < 25) & (hs < 1.0)
    holds = []
    f = 0
    while f < F:
        if still[f]:
            g = f
            while g < F and still[g]:
                g += 1
            if g - f >= 15:
                pre = max(0, f - 10)
                holds.append((f, g, float(sp[pre:f].max() if f > pre else 0), float(hs[pre:f].max() if f > pre else 0)))
            f = g
        else:
            f += 1
    lines.append("holds of the head (angspeed<25 deg/s and speed<1 u/s for >=15 frames): %d, total %d frames" % (len(holds), sum(b - a for a, b, _, _ in holds)))
    events["holds"] = holds
    for a, b, pa, ps in sorted(holds, key=lambda h: -h[2])[:25]:
        lines.append("  f%d-%d (%.1f s long) preceded by %.0f deg/s, %.1f u/s" % (a, b, (b - a) / FPS18, pa, ps))
    return res, lines, events
